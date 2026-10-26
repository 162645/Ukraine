#!/usr/bin/env node
"use strict";
const fs=require("node:fs"),path=require("node:path"),readline=require("node:readline");
const ROOT=path.resolve(__dirname,".."),ORDER=["Ⅰ类","Ⅱ类","Ⅲ类","Ⅳ类","Ⅴ类"];
function assert(v,m){if(!v)throw Error(m);}
function parse(l){let a=[],s="",q=false;for(let i=0;i<l.length;i++){let c=l[i];if(q){if(c==='"'&&l[i+1]==='"'){s+='"';i++;}else if(c==='"')q=false;else s+=c;}else if(c==='"')q=true;else if(c===","){a.push(s);s="";}else s+=c;}a.push(s);return a;}
async function csv(f){const rl=readline.createInterface({input:fs.createReadStream(f,{encoding:"utf8"}),crlfDelay:Infinity});let h=null,a=[];for await(let l of rl){if(!l)continue;if(l.charCodeAt(0)===0xfeff)l=l.slice(1);let x=parse(l);if(!h){h=x;continue;}assert(x.length===h.length,"CSV shape "+f);let r={};h.forEach((k,i)=>r[k]=x[i]);a.push(r);}return a;}
async function main(){
 const s=JSON.parse(fs.readFileSync(path.join(ROOT,"results","audit_summary.json"),"utf8")),checks=[];
 assert(s.chapter3.target_prefixes===42811&&s.chapter3.formal_monthly_evidence_rows===256866,"formal population and grid");checks.push("42,811 /24 × six formal monthly records");
 assert(JSON.stringify(ORDER.map(c=>s.chapter3.counts[c]))===JSON.stringify([1786,888,6133,11857,22147]),"formal five-class counts");
 assert(s.chapter3.partition_total===42811&&s.chapter3.label_mismatches===0&&s.chapter3.stable_route_key_mismatches===0,"formal class partition and cache match");checks.push("formal class counts, exhaustiveness and per-prefix matches");
 const p=await csv(path.join(ROOT,"data_audit","formal_prefix_classification.csv")),m=await csv(path.join(ROOT,"data_audit","formal_monthly_path_evidence.csv"));
 assert(p.length===42811&&m.length===256866,"formal evidence output row counts");
 const classes=Object.fromEntries(ORDER.map(c=>[c,0]));for(const r of p)classes[r.formal_class]++;
 assert(JSON.stringify(ORDER.map(c=>classes[c]))===JSON.stringify([1786,888,6133,11857,22147]),"formal prefix output marginals");
 const keys=new Set(m.map(r=>r.prefix_key+"|"+r.month));assert(keys.size===256866,"formal monthly rows are unique");
 checks.push("row-level formal class and monthly path evidence tables");
 assert(s.chapter3.core_prefixes===1510&&s.chapter3.core_historical_paths===254&&s.chapter3.core_exact_historical_route_identity_retained===576,"core association/identity");
 assert(JSON.stringify(ORDER.map(c=>s.chapter3.core_local_strict_evidence_counts[c]))===JSON.stringify([1154,2,249,105,0]),"core-local strict evidence");checks.push("core 1,510 /24, 254 routes and 576 exact retained IDs");
 const coreMonthly=await csv(path.join(ROOT,"data_audit","core_monthly_last_hop_evidence.csv"));assert(coreMonthly.length===9060,"core monthly identity/evidence rows");assert(coreMonthly.every(x=>x.month===x.effective_month_utc&&x.evidence_type.includes("last responding hop")&&x.core_prefix_key),"core monthly scope and evidence fields");checks.push("core per-/24 monthly path identity, evidence and validity window"); const chain=await csv(path.join(ROOT,"data_audit","historical_core_selection_chain_audit.csv"));
 assert(JSON.stringify(chain.map(x=>Number(x.prefix24_n)))===JSON.stringify([42811,6972,4804,1652,1625,1510]),"historical chain");
 assert(chain.every(x=>x.member_level_independent_check.includes("unavailable")),"chain row-level limitation is explicit");
 const pathRows=await csv(path.join(ROOT,"data_audit","core_path_identity_audit.csv"));
 assert(pathRows.length===254&&pathRows.reduce((a,x)=>a+Number(x.historical_core_member_n),0)===1510&&pathRows.reduce((a,x)=>a+Number(x.identity_retained_member_n),0)===576,"path identity membership");
 checks.push("historical stage chain and route membership sums");
 assert(s.chapter4.theoretical_hours===4416&&s.chapter4.valid_cycle_hours===4158&&s.chapter4.globally_missing_hours===258&&s.chapter4.grid_cells===6278580,"UTC and core grid");
 assert(s.chapter4.endpoint.ips_evaluable===5922220&&s.chapter4.endpoint.ips_candidate===240325&&s.chapter4.endpoint.rtt_evaluable===5281047&&s.chapter4.endpoint.rtt_candidate===157968,"endpoint statistics");
 assert(s.chapter4.path.ips_evaluable===443186&&s.chapter4.path.ips_candidate===4208&&s.chapter4.path.rtt_evaluable===406636&&s.chapter4.path.rtt_candidate===4202&&s.chapter4.path.union_candidate===8215&&s.chapter4.path.intersection_candidate===195,"path statistics");
 assert(s.chapter4.episodes.total===5866&&s.chapter4.episodes.retained_ge_2h===1117&&s.chapter4.episodes.utc_duration_mismatches===0,"episodes");
 checks.push("Chapter 4 archived aggregate reconciliation");
 const figures=["figA_formal_five_class_distribution","figB_formal_class_conditions","figC_historical_core_selection_flow","figD_path_scale_evaluable_coverage"];
 for(const f of figures)for(const ext of ["svg","png","pdf"])assert(fs.existsSync(path.join(ROOT,"figures",ext,f+"."+ext)),"Missing figure artifact "+f+"."+ext);
 checks.push("four figure SVG/PNG/PDF triplets");
 const forbidden=["classification_transition_matrix.csv","classification_transition_matrices_all.csv","core_sample_selection_cross_tab.csv","figB_class_transition.svg","figB_class_transition.png","figB_class_transition.pdf"];
 for(const rel of forbidden)assert(!fs.existsSync(path.join(ROOT,"data_audit",rel))&&!fs.existsSync(path.join(ROOT,"figures","svg",rel))&&!fs.existsSync(path.join(ROOT,"figures","png",rel))&&!fs.existsSync(path.join(ROOT,"figures","pdf",rel)),"Obsolete formal output exists: "+rel);
 for(let i=1;i<=6;i++){const f=fs.readdirSync(path.join(ROOT,"reports")).find(x=>x.startsWith(String(i).padStart(2,"0")+"_"));assert(f,"Missing report section "+i);}
 checks.push("no old comparison matrix or figure in formal output; six reports present");
 const scanDirs=["scripts","tests","reports","results","figures","data_audit"];
 for(const d of scanDirs){const files=[];function walk(p){for(const e of fs.readdirSync(p,{withFileTypes:true})){const f=path.join(p,e.name);if(e.isDirectory()){if(d==="data_audit"&&path.basename(f)==="source_snapshots")continue;walk(f);}else if(/\.(js|md|json|csv|svg|ya?ml)$/i.test(f))files.push(f);}}walk(path.join(ROOT,d));for(const f of files){const txt=fs.readFileSync(f,"utf8");assert(!/(?:password|passwd)\s*[:=]\s*["'][^"']+["']/i.test(txt),"Credential-like assignment in "+f);}}
 checks.push("credential assignment pattern scan");
 const result={passed:true,check_count:checks.length,checks,scope:"Local archived aggregates and outputs only; ClickHouse/raw Traceroute and private cycle-level Parquet were not rerun."};
 fs.writeFileSync(path.join(__dirname,"validation_results.json"),JSON.stringify(result,null,2)+"\n","utf8");console.log(JSON.stringify(result,null,2));
}
main().catch(e=>{console.error(e.stack||String(e));process.exitCode=1;});
