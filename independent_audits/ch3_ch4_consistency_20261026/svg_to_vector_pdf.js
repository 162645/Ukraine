#!/usr/bin/env node
"use strict";

// Small SVG-to-PDF writer for this audit's deliberately simple SVG subset.
// It emits vector paths and embedded CID TrueType text; no browser is used.
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");

function parseAttrs(source) {
  const attrs = Object.create(null);
  for (const m of source.matchAll(/([\w-]+)="([^"]*)"/g)) attrs[m[1]] = m[2];
  return attrs;
}
function xmlDecode(s) {
  return s.replace(/&lt;/g,"<").replace(/&gt;/g,">").replace(/&quot;/g,'"')
    .replace(/&apos;/g,"'").replace(/&amp;/g,"&")
    .replace(/&#x([0-9a-f]+);/gi,(_,h)=>String.fromCodePoint(parseInt(h,16)))
    .replace(/&#([0-9]+);/g,(_,n)=>String.fromCodePoint(Number(n)));
}
function color(value) {
  if (!value || value === "none") return null;
  let m = value.match(/^#([0-9a-f]{6})$/i);
  if (m) return [0,2,4].map(i=>parseInt(m[1].slice(i,i+2),16)/255);
  m = value.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/i);
  if (m) return [1,2,3].map(i=>Number(m[i])/255);
  if (value === "white") return [1,1,1];
  if (value === "black") return [0,0,0];
  throw new Error(`Unsupported SVG color ${value}`);
}
function colorOps(c, stroke=false) {
  if (!c) return "";
  const op = stroke ? "RG" : "rg";
  return `${c.map(x=>x.toFixed(4)).join(" ")} ${op}\n`;
}
function number(x) { const v=Number(x); if(!Number.isFinite(v))throw new Error(`Invalid SVG number: ${x}`); return v; }

function parseTrueType(buf) {
  const u16=o=>buf.readUInt16BE(o), i16=o=>buf.readInt16BE(o), u32=o=>buf.readUInt32BE(o);
  const tableCount=u16(4), tables=new Map();
  for(let i=0;i<tableCount;i++){
    const p=12+i*16, tag=buf.toString("ascii",p,p+4);
    tables.set(tag,{offset:u32(p+8),length:u32(p+12)});
  }
  const get=tag=>{const t=tables.get(tag);if(!t)throw new Error(`TTF lacks ${tag} table`);return t.offset;};
  const head=get("head"), hhea=get("hhea"), maxp=get("maxp"), cmap=get("cmap"), hmtx=get("hmtx");
  const units=u16(head+18), bbox=[i16(head+36),i16(head+38),i16(head+40),i16(head+42)];
  const glyphN=u16(maxp+4), ascent=i16(hhea+4), descent=i16(hhea+6), metricN=u16(hhea+34);
  const advances=[];
  let last=0;
  for(let i=0;i<metricN;i++){last=u16(hmtx+i*4);advances.push(last);}
  for(let i=metricN;i<glyphN;i++) advances.push(last);
  const encN=u16(cmap+2), encodings=[];
  for(let i=0;i<encN;i++){
    const p=cmap+4+i*8, platform=u16(p), encoding=u16(p+2), off=cmap+u32(p+4), format=u16(off);
    encodings.push({platform,encoding,off,format});
  }
  const fmt12=encodings.find(e=>e.format===12 && (e.platform===3 && e.encoding===10 || e.platform===0));
  const fmt4=encodings.find(e=>e.format===4 && (e.platform===3 && e.encoding===1 || e.platform===0));
  if(!fmt12&&!fmt4)throw new Error("TTF lacks a supported Unicode cmap (format 4/12)");
  function glyph(cp){
    if(fmt12){
      const p=fmt12.off, groups=u32(p+12);let lo=0,hi=groups-1;
      while(lo<=hi){const mid=(lo+hi)>>1,q=p+16+mid*12,s=u32(q),e=u32(q+4);
        if(cp<s)hi=mid-1;else if(cp>e)lo=mid+1;else return u32(q+8)+(cp-s);}
    }
    if(fmt4&&cp<=0xffff){
      const p=fmt4.off,n=u16(p+6)/2,end=p+14,start=end+2*n+2,delta=start+2*n,range=delta+2*n;
      for(let i=0;i<n;i++){
        const e=u16(end+2*i),s=u16(start+2*i);if(cp<s||cp>e)continue;
        const d=i16(delta+2*i),ro=u16(range+2*i);
        if(ro===0)return (cp+d)&0xffff;
        const addr=range+2*i+ro+2*(cp-s),gid=u16(addr);
        return gid===0?0:(gid+d)&0xffff;
      }
    }
    return 0;
  }
  return {units,bbox,ascent,descent,advances,glyphN,glyph};
}

function pdfStream(dict, data) {
  return Buffer.concat([Buffer.from(`<< ${dict} /Length ${data.length} >>\nstream\n`,"ascii"),data,Buffer.from("\nendstream","ascii")]);
}
function makePdf(pageW,pageH,content,fontBytes,fontMeta,cids) {
  const objects=[];
  const add=x=>{objects.push(Buffer.isBuffer(x)?x:Buffer.from(x,"binary"));return objects.length;};
  const scale=1000/fontMeta.units;
  const cidMap=Buffer.alloc(65536*2);
  for(const cp of cids){const gid=fontMeta.glyph(cp);if(!gid)throw new Error(`SimHei does not contain U+${cp.toString(16).toUpperCase()}`);cidMap.writeUInt16BE(gid,cp*2);}
  const cmapLines=[
    "/CIDInit /ProcSet findresource begin","12 dict begin","begincmap",
    "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
    "/CMapName /Adobe-Identity-UCS def","/CMapType 2 def",
    "1 begincodespacerange","<0000> <FFFF>","endcodespacerange"
  ];
  for(let i=0;i<cids.length;i+=100){
    const slice=cids.slice(i,i+100);cmapLines.push(`${slice.length} beginbfchar`);
    for(const cp of slice){const h=cp.toString(16).toUpperCase().padStart(4,"0");cmapLines.push(`<${h}> <${h}>`);}
    cmapLines.push("endbfchar");
  }
  cmapLines.push("endcmap","CMapName currentdict /CMap defineresource pop","end","end");
  const toUnicode=zlib.deflateSync(Buffer.from(cmapLines.join("\n"),"ascii"));
  const cmapDict=`/Filter /FlateDecode`;
  const widths=[];
  for(const cp of cids) widths.push(`${cp} [${Math.round(fontMeta.advances[fontMeta.glyph(cp)]*scale)}]`);
  const fontBBox=fontMeta.bbox.map(v=>Math.round(v*scale)).join(" ");
  const ascent=Math.round(fontMeta.ascent*scale),descent=Math.round(fontMeta.descent*scale);

  const catalog=add("<< /Type /Catalog /Pages 2 0 R >>");
  const pages=add("<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  const page=add(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageW.toFixed(2)} ${pageH.toFixed(2)}] /Resources << /Font << /F1 4 0 R >> >> /Contents 10 0 R >>`);
  const type0=add("<< /Type /Font /Subtype /Type0 /BaseFont /SimHei /Encoding /Identity-H /DescendantFonts [5 0 R] /ToUnicode 9 0 R >>");
  const cidfont=add(`<< /Type /Font /Subtype /CIDFontType2 /BaseFont /SimHei /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor 6 0 R /DW 1000 /W [${widths.join(" ")}] /CIDToGIDMap 8 0 R >>`);
  const descriptor=add(`<< /Type /FontDescriptor /FontName /SimHei /Flags 4 /FontBBox [${fontBBox}] /ItalicAngle 0 /Ascent ${ascent} /Descent ${descent} /CapHeight ${ascent} /StemV 80 /FontFile2 7 0 R >>`);
  const compressedFont=zlib.deflateSync(fontBytes,{level:9});
  const fontFile=add(pdfStream(`/Filter /FlateDecode /Length1 ${fontBytes.length}`,compressedFont));
  const cidMapRef=add(pdfStream("/Filter /FlateDecode",zlib.deflateSync(cidMap,{level:9})));
  const unicodeRef=add(pdfStream(cmapDict,toUnicode));
  const contentRef=add(pdfStream("",Buffer.from(content,"ascii")));
  if(catalog!==1||pages!==2||page!==3||type0!==4||cidfont!==5||descriptor!==6||fontFile!==7||cidMapRef!==8||unicodeRef!==9||contentRef!==10)throw new Error("PDF object layout changed unexpectedly");
  const header=Buffer.from("%PDF-1.7\n%\xE2\xE3\xCF\xD3\n","binary");
  const pieces=[header];let offset=header.length;const offsets=[0];
  for(let i=0;i<objects.length;i++){
    const pre=Buffer.from(`${i+1} 0 obj\n`,"ascii"),post=Buffer.from("\nendobj\n","ascii");
    offsets.push(offset);pieces.push(pre,objects[i],post);offset+=pre.length+objects[i].length+post.length;
  }
  const xrefOffset=offset;
  let xref=`xref\n0 ${objects.length+1}\n0000000000 65535 f \n`;
  for(let i=1;i<offsets.length;i++)xref+=`${String(offsets[i]).padStart(10,"0")} 00000 n \n`;
  xref+=`trailer\n<< /Size ${objects.length+1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  pieces.push(Buffer.from(xref,"ascii"));
  return Buffer.concat(pieces);
}

function svgToPdf(svg, fontBytes) {
  const root=svg.match(/<svg\b([^>]*)>/);if(!root)throw new Error("SVG root not found");
  const rootAttrs=parseAttrs(root[1]),width=number(rootAttrs.width),height=number(rootAttrs.height),S=.75;
  const fontMeta=parseTrueType(fontBytes),elements=[];let allText="";
  const re=/<rect\b([^>]*)\/>|<line\b([^>]*)\/>|<text\b([^>]*)>([\s\S]*?)<\/text>/g;
  for(const m of svg.matchAll(re)){
    if(m[1]!==undefined)elements.push({kind:"rect",attrs:parseAttrs(m[1])});
    else if(m[2]!==undefined)elements.push({kind:"line",attrs:parseAttrs(m[2])});
    else {const text=xmlDecode(m[4]);elements.push({kind:"text",attrs:parseAttrs(m[3]),text});allText+=text;}
  }
  const cids=[...new Set([...allText].map(ch=>ch.codePointAt(0)))].sort((a,b)=>a-b);
  const pdfY=y=>(height-y)*S;
  const parts=[];
  function strokeFill(a){
    const f=color(a.fill),s=color(a.stroke),sw=a["stroke-width"]?number(a["stroke-width"]):1;
    return {f,s,sw,paint:f&&s?"B":f?"f":s?"S":"n"};
  }
  for(const e of elements){
    const a=e.attrs;
    if(e.kind==="rect"){
      const x=number(a.x||0),y=number(a.y||0),w=a.width==="100%"?width:number(a.width),h=a.height==="100%"?height:number(a.height),r=Math.min(number(a.rx||0),w/2,h/2);
      const p=strokeFill(a);parts.push("q\n",colorOps(p.f),colorOps(p.s,true),`${(p.sw*S).toFixed(2)} w\n`);
      if(r===0){parts.push(`${(x*S).toFixed(2)} ${(height-y-h)*S.toFixed(2)} ${(w*S).toFixed(2)} ${(h*S).toFixed(2)} re\n`);}
      else{
        const k=.5522847498,xx=x*S,yy=pdfY(y),ww=w*S,hh=h*S,rr=r*S,kk=rr*k;
        parts.push(`${(xx+rr).toFixed(2)} ${yy.toFixed(2)} m\n`,`${(xx+ww-rr).toFixed(2)} ${yy.toFixed(2)} l\n`);
        parts.push(`${(xx+ww-rr+kk).toFixed(2)} ${yy.toFixed(2)} ${(xx+ww).toFixed(2)} ${(yy-rr+kk).toFixed(2)} ${(xx+ww).toFixed(2)} ${(yy-rr).toFixed(2)} c\n`);
        parts.push(`${(xx+ww).toFixed(2)} ${(yy-hh+rr).toFixed(2)} l\n`);
        parts.push(`${(xx+ww).toFixed(2)} ${(yy-hh+rr-kk).toFixed(2)} ${(xx+ww-rr+kk).toFixed(2)} ${(yy-hh).toFixed(2)} ${(xx+ww-rr).toFixed(2)} ${(yy-hh).toFixed(2)} c\n`);
        parts.push(`${(xx+rr).toFixed(2)} ${(yy-hh).toFixed(2)} l\n`);
        parts.push(`${(xx+rr-kk).toFixed(2)} ${(yy-hh).toFixed(2)} ${xx.toFixed(2)} ${(yy-hh+rr-kk).toFixed(2)} ${xx.toFixed(2)} ${(yy-hh+rr).toFixed(2)} c\n`);
        parts.push(`${xx.toFixed(2)} ${(yy-rr).toFixed(2)} l\n`);
        parts.push(`${xx.toFixed(2)} ${(yy-rr+kk).toFixed(2)} ${(xx+rr-kk).toFixed(2)} ${yy.toFixed(2)} ${(xx+rr).toFixed(2)} ${yy.toFixed(2)} c\n`);
        parts.push("h\n");
      }
      parts.push(`${p.paint}\nQ\n`);
    } else if(e.kind==="line"){
      const x1=number(a.x1),y1=number(a.y1),x2=number(a.x2),y2=number(a.y2),s=color(a.stroke),sw=number(a["stroke-width"]||1);
      parts.push("q\n",colorOps(s,true),`${(sw*S).toFixed(2)} w\n${(x1*S).toFixed(2)} ${pdfY(y1).toFixed(2)} m ${(x2*S).toFixed(2)} ${pdfY(y2).toFixed(2)} l S\n`);
      if(a["marker-end"]){
        const dx=x2-x1,dy=y2-y1,len=Math.hypot(dx,dy)||1,ux=dx/len,uy=dy/len,vx=-uy,vy=ux,size=10;
        const tip=[x2,y2],base=[x2-ux*size,y2-uy*size],p1=[base[0]+vx*size*.42,base[1]+vy*size*.42],p2=[base[0]-vx*size*.42,base[1]-vy*size*.42];
        parts.push(colorOps(s),`${(tip[0]*S).toFixed(2)} ${pdfY(tip[1]).toFixed(2)} m ${(p1[0]*S).toFixed(2)} ${pdfY(p1[1]).toFixed(2)} l ${(p2[0]*S).toFixed(2)} ${pdfY(p2[1]).toFixed(2)} l h f\n`);
      }
      parts.push("Q\n");
    } else {
      const x=number(a.x)*S,y=pdfY(number(a.y)),size=number(a["font-size"]||16)*S,fill=color(a.fill)||[0,0,0],bold=number(a["font-weight"]||400)>=600;
      const chars=[...e.text].map(ch=>ch.codePointAt(0));
      let widthUnits=0;for(const cp of chars){const gid=fontMeta.glyph(cp);if(!gid)throw new Error(`SimHei missing glyph U+${cp.toString(16).toUpperCase()}`);widthUnits+=fontMeta.advances[gid];}
      const textWidth=widthUnits/fontMeta.units*size;
      const anchor=a["text-anchor"]||"start",tx=anchor==="middle"?x-textWidth/2:anchor==="end"?x-textWidth:x;
      const hex=chars.map(cp=>cp.toString(16).toUpperCase().padStart(4,"0")).join("");
      parts.push("q\n",colorOps(fill),bold?`${(0.22*S).toFixed(3)} w\n2 Tr\n`:"0 Tr\n",`BT /F1 ${size.toFixed(2)} Tf 1 0 0 1 ${tx.toFixed(2)} ${y.toFixed(2)} Tm <${hex}> Tj ET\n`);
      if(bold)parts.push("0 Tr\n");
      parts.push("Q\n");
    }
  }
  return makePdf(width*S,height*S,parts.join(""),fontBytes,fontMeta,cids);
}

function main(){
  const [input,output]=process.argv.slice(2);if(!input||!output)throw new Error("Usage: node svg_to_vector_pdf.js input.svg output.pdf");
  const font=process.env.CHINESE_FONT_TTF||path.join(process.env.WINDIR||"C:\\Windows","Fonts","simhei.ttf");
  if(!fs.existsSync(font))throw new Error(`CJK TrueType font not found: ${font}; set CHINESE_FONT_TTF to a Unicode TTF path.`);
  const pdf=svgToPdf(fs.readFileSync(input,"utf8"),fs.readFileSync(font));
  fs.mkdirSync(path.dirname(path.resolve(output)),{recursive:true});fs.writeFileSync(output,pdf);
  console.log(`${path.basename(input)} -> ${path.basename(output)} (${pdf.length} bytes, vector paths/text)`);
}
if(require.main===module)try{main();}catch(e){console.error(e.stack||String(e));process.exitCode=1;}
module.exports={svgToPdf};
