#!/usr/bin/env node
"use strict";

// Render SVG previews to PNG with sharp and write vector PDF pages directly.
// Local-only; SVG text and paths remain vector elements in PDF.
const fs=require("node:fs");
const path=require("node:path");
const sharp=require("sharp");
const {svgToPdf}=require("./svg_to_vector_pdf.js");
const ROOT=path.resolve(__dirname,"..");
const SVG=path.join(ROOT,"figures","svg");
const PNG=path.join(ROOT,"figures","png");
const PDF=path.join(ROOT,"figures","pdf");
async function main(){
  fs.mkdirSync(PNG,{recursive:true});fs.mkdirSync(PDF,{recursive:true});
  const files=fs.readdirSync(SVG).filter(f=>f.endsWith(".svg")).sort();
  if(files.length!==4)throw new Error(`Expected 4 SVG files, found ${files.length}`);
  const fontFile=process.env.CHINESE_FONT_TTF||path.join(process.env.WINDIR||"C:\\Windows","Fonts","simhei.ttf");
  if(!fs.existsSync(fontFile))throw new Error(`CJK TrueType font not found: ${fontFile}`);
  const fontBytes=fs.readFileSync(fontFile);
  for(const file of files){
    const name=path.basename(file,".svg");
    const svgPath=path.join(SVG,file),pngPath=path.join(PNG,`${name}.png`),pdfPath=path.join(PDF,`${name}.pdf`);
    const svgBytes=fs.readFileSync(svgPath);
    await sharp(svgBytes).png().toFile(pngPath);
    fs.writeFileSync(pdfPath,svgToPdf(svgBytes.toString("utf8"),fontBytes));
    if(fs.statSync(pngPath).size<1000)throw new Error(`PNG render failed: ${pngPath}`);
    if(fs.statSync(pdfPath).size<100000)throw new Error(`Vector PDF render failed: ${pdfPath}`);
    console.log(`${name}: SVG -> ${fs.statSync(pngPath).size} byte PNG + vector PDF (${fs.statSync(pdfPath).size} bytes)`);
  }
  console.log(`Rendered ${files.length} figures with sharp PNG previews and embedded CJK vector PDF text.`);
}
main().catch(e=>{console.error(e.stack||String(e));process.exitCode=1;});
