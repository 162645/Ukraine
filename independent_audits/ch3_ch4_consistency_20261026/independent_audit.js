#!/usr/bin/env node
"use strict";
const fs=require("node:fs"),path=require("node:path"),crypto=require("node:crypto"),readline=require("node:readline"),{createGunzip}=require("node:zlib");
const ROOT=path.resolve(__dirname,".."),CH3=path.join(ROOT,"data_audit","source_snapshots","ch3"),CH4=path.join(ROOT,"data_audit","source_snapshots","ch4"),PAPER=path.join(ROOT,"data_audit","source_snapshots","paper");
const MONTHS=["2024-07","2024-08","2024-09","2024-10","2024-11","2024-12"],CLASSES=["Ⅰ类","Ⅱ类","Ⅲ类","Ⅳ类","Ⅴ类"];
const NAMES={"Ⅰ类":"跨月主路径一致","Ⅱ类":"跨月主路径变化","Ⅲ类":"阶段性主路径可判定","Ⅳ类":"无合格月度主路径","Ⅴ类":"末端路径证据不完整"};
const EXPECTED={"Ⅰ类":1786,"Ⅱ类":888,"Ⅲ类":6133,"Ⅳ类":11857,"Ⅴ类":22147};
function assert(x,m){if(!x)throw Error(m);}function num(x){if(x===""||x==null)return 0;let n=Number(x);assert(Number.isFinite(n),"Invalid number "+x);return n;}function truth(x){return x===true||x==="true"||x==="True"||x==="1";}
function parseLine(l){let a=[],s="",q=false;for(let i=0;i<l.length;i++){let c=l[i];if(q){if(c==='"'&&l[i+1]==='"'){s+='"';i++;}else if(c==='"')q=false;else s+=c;}else if(c==='"')q=true;else if(c===","){a.push(s);s="";}else s+=c;}a.push(s.replace(/\r$/,""));return a;}
async function readCsv(f){let rl=readline.createInterface({input:fs.createReadStream(f,{encoding:"utf8"}),crlfDelay:Infinity}),h=null,a=[];for await(let x of rl){if(!x)continue;if(x.charCodeAt(0)===0xfeff)x=x.slice(1);let r=parseLine(x);if(!h){h=r;continue;}assert(h.length===r.length,"CSV width mismatch "+f);let o={};h.forEach((k,i)=>o[k]=r[i]);a.push(o);}return a;}
function cell(v){let s=v==null?"":String(v);return /[",\r\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;}
function writeCsv(f,h,rows){fs.mkdirSync(path.dirname(f),{recursive:true});fs.writeFileSync(f,"\ufeff"+[h,...rows.map(r=>h.map(k=>r[k]))].map(r=>r.map(cell).join(",")).join("\r\n")+"\r\n","utf8");}
function pct(a,b){return b?100*a/b:0;}function sum(a,k){return a.reduce((s,r)=>s+num(r[k]),0);}
function classify(ms){let ev=ms.filter(x=>x.evidence).length,q=ms.filter(x=>x.qualified),rs=new Set(q.map(x=>x.routeKey));assert(q.every(x=>x.routeKey),"Qualified monthly path lacks ID");let label=ev<6?"Ⅴ类":q.length===6&&rs.size===1?"Ⅰ类":q.length===6?"Ⅱ类":q.length>0?"Ⅲ类":"Ⅳ类";return {label,ev,qn:q.length,rs,stable:label==="Ⅰ类"?Array.from(rs)[0]:""};}
function esc(s){return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function text(x,y,s,size=20,fill="#1f2937",weight=400,anchor="start"){return '<text x="'+x+'" y="'+y+'" font-family="Microsoft YaHei, sans-serif" font-size="'+size+'" fill="'+fill+'" font-weight="'+weight+'" text-anchor="'+anchor+'">'+esc(s)+"</text>";}
function rect(x,y,w,h,fill,stroke="#d5dee7",rx=12,sw=2){return '<rect x="'+x+'" y="'+y+'" width="'+w+'" height="'+h+'" rx="'+rx+'" fill="'+fill+'" stroke="'+stroke+'" stroke-width="'+sw+'"/>';}
function line(x1,y1,x2,y2,color="#64748b",sw=3,arrow=false){return '<line x1="'+x1+'" y1="'+y1+'" x2="'+x2+'" y2="'+y2+'" stroke="'+color+'" stroke-width="'+sw+'"'+(arrow?' marker-end="url(#arrow)"':"")+'/>';}
function svg(w,h,c){return '<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="'+w+'" height="'+h+'" viewBox="0 0 '+w+" "+h+'"><rect width="100%" height="100%" fill="#ffffff"/>'+c+"</svg>\n";}
function save(name,w,h,c){let f=path.join(ROOT,"figures","svg",name+".svg");fs.mkdirSync(path.dirname(f),{recursive:true});fs.writeFileSync(f,svg(w,h,c),"utf8");}
function walk(d){let a=[];for(const e of fs.readdirSync(d,{withFileTypes:true})){let f=path.join(d,e.name);if(e.isDirectory())a.push(...walk(f));else a.push(f);}return a;}
async function sha(f){return new Promise((ok,no)=>{let h=crypto.createHash("sha256"),s=fs.createReadStream(f);s.on("data",x=>h.update(x));s.on("error",no);s.on("end",()=>ok(h.digest("hex")));});}
async function main(){
 let by=new Map(),seen=new Set(),archiveRows=0,formalRows=0,head=null;
 const rl=readline.createInterface({input:fs.createReadStream(path.join(CH3,"full_population_prefix_month_hashed.csv.gz")).pipe(createGunzip()),crlfDelay:Infinity});
 for await(let l of rl){if(!l)continue;if(l.charCodeAt(0)===0xfeff)l=l.slice(1);let f=parseLine(l);if(!head){head=f;continue;}assert(f.length===head.length,"Monthly CSV width mismatch");let o={};head.forEach((k,i)=>o[k]=f[i]);archiveRows++;if(o.criterion!=="target_asgeo_last_hop")continue;
  let mi=MONTHS.indexOf(o.month);assert(mi>=0,"Unexpected month");let key=o.prefix_key+"|"+mi;assert(!seen.has(key),"Duplicate formal /24-month");seen.add(key);let a=by.get(o.prefix_key);if(!a){a=Array(6).fill(null);by.set(o.prefix_key,a);}
  let e=num(o.eligible_path_observations),ties=num(o.top_route_tie_count),share=num(o.top_share);a[mi]={month:o.month,evidence:e>0,qualified:e>0&&ties===1&&share>=.5,eligible:e,ties,share,routeKey:o.route_key||""};formalRows++;
 }
 assert(by.size===42811&&formalRows===42811*6,"Formal population/evidence grid incomplete");
 let vals=new Map(),counts=Object.fromEntries(CLASSES.map(c=>[c,0])),monthly=[];
 for(const [p,ms] of by){assert(ms.every(Boolean),"Missing month "+p);let z=classify(ms);vals.set(p,z);counts[z.label]++;for(const m of ms)monthly.push({prefix_key:p,month:m.month,
  evidence_type:"last responding hop with nonempty IP and RTT; IP matches target ASGeo mid-node set; terminal ASGeo label is non-placeholder",
  evidence_present:m.evidence,eligible_terminal_asgeo_path_observations:m.eligible,unique_top_route_tie_count:m.ties,top_route_share:m.share.toFixed(8),monthly_route_key:m.routeKey,
  qualified_monthly_main_path:m.qualified,monthly_path_identity_status:m.qualified?"qualified ASGeo route key":m.evidence?"evidence present, no qualifying unique main path":"no eligible last-hop ASGeo evidence",effective_month_utc:m.month});}
 assert(CLASSES.every(c=>counts[c]===EXPECTED[c])&&Object.values(counts).reduce((a,b)=>a+b,0)===42811,"Formal counts mismatch "+JSON.stringify(counts));
 let cache=(await readCsv(path.join(CH3,"full_population_class_hashed.csv"))).filter(x=>x.criterion==="target_asgeo_last_hop"),cm=new Map();for(const x of cache){assert(!cm.has(x.prefix_key),"Duplicate cached formal label");cm.set(x.prefix_key,x);}
 assert(cm.size===42811,"Formal label cache incomplete");let mismatch=0,keyMismatch=0,prefixRows=[];
 for(const [p,z] of vals){let c=cm.get(p);assert(c,"Missing cached label");if(c.class_label!==z.label)mismatch++;if(z.label==="Ⅰ类"&&c.route_key!==z.stable)keyMismatch++;prefixRows.push({prefix_key:p,formal_class:z.label,formal_class_name:NAMES[z.label],evidence_months:z.ev,qualified_main_path_months:z.qn,distinct_qualified_route_identities:z.rs.size,stable_route_key:z.stable,validity_window_utc:"2024-07 through 2024-12"});}
 assert(mismatch===0&&keyMismatch===0,"Formal class/key archive mismatch");
 for(const row of monthly){let z=vals.get(row.prefix_key);row.formal_class=z.label;row.formal_class_name=NAMES[z.label];}
 const classRows=CLASSES.map(c=>({class_label:c,class_name:NAMES[c],prefix24_n:counts[c],share_pct:pct(counts[c],42811).toFixed(2),denominator:42811}));
 writeCsv(path.join(ROOT,"data_audit","formal_prefix_classification.csv"),["prefix_key","formal_class","formal_class_name","evidence_months","qualified_main_path_months","distinct_qualified_route_identities","stable_route_key","validity_window_utc"],prefixRows);
 writeCsv(path.join(ROOT,"data_audit","formal_monthly_path_evidence.csv"),["prefix_key","month","evidence_type","evidence_present","eligible_terminal_asgeo_path_observations","unique_top_route_tie_count","top_route_share","monthly_route_key","qualified_monthly_main_path","monthly_path_identity_status","effective_month_utc","formal_class","formal_class_name"],monthly);
 const rules=[
  {class_label:"Ⅰ类",class_name:NAMES["Ⅰ类"],priority:2,rule:"6/6月有末跳证据，6/6月有唯一且占比≥50%的合格月度主路径，六个月路径身份一致。"},
  {class_label:"Ⅱ类",class_name:NAMES["Ⅱ类"],priority:3,rule:"6/6月有末跳证据，6/6月均有合格主路径，跨月路径身份数≥2。"},
  {class_label:"Ⅲ类",class_name:NAMES["Ⅲ类"],priority:4,rule:"6/6月有末跳证据；至少1个月但不足6个月有合格月度主路径。"},
  {class_label:"Ⅳ类",class_name:NAMES["Ⅳ类"],priority:5,rule:"6/6月有末跳证据；六个月均无合格月度主路径。"},
  {class_label:"Ⅴ类",class_name:NAMES["Ⅴ类"],priority:1,rule:"有末跳 ASGeo 证据的月份少于6；优先判定。"}
 ];
 writeCsv(path.join(ROOT,"data_audit","formal_class_conditions.csv"),["class_label","class_name","priority","rule"],rules);
 writeCsv(path.join(ROOT,"data_audit","figure_data","figA_formal_five_class_distribution.csv"),["class_label","class_name","prefix24_n","share_pct","denominator"],classRows);
 writeCsv(path.join(ROOT,"data_audit","figure_data","figB_class_conditions.csv"),["class_label","class_name","priority","rule"],rules);
 // Historical selection chain: archived stage totals only.
 const chain=await readCsv(path.join(CH3,"historical_sample_selection_chain.csv")),exp=[42811,6972,4804,1652,1625,1510];
 assert(chain.length===6,"Historical chain stages changed");chain.forEach((x,i)=>assert(num(x.prefixes)===exp[i],"Historical chain total mismatch"));
 const desc=["42,811 target /24; Jul-Dec 2024","6/6月唯一主路径且月度占比≥50%","六个月沿用同一历史主路径身份","稳定关联且有成功Ping记录","地区纯度条件","最终保留ASGeo核心样本"];
 const stages=chain.map((x,i)=>({stage_order:i+1,stage:x.stage,prefix24_n:num(x.prefixes),previous_stage_retention_pct:x.previous_stage_retention_pct||"",recorded_condition:desc[i],member_level_independent_check:"unavailable; archived file has stage totals only"}));
 writeCsv(path.join(ROOT,"data_audit","historical_core_selection_chain_audit.csv"),["stage_order","stage","prefix24_n","previous_stage_retention_pct","recorded_condition","member_level_independent_check"],stages);
 const assoc=await readCsv(path.join(CH3,"core_path_prefix_association_hashed.csv")),pRoute=new Map(),members=new Map();
 for(const x of assoc){assert(!pRoute.has(x.prefix_key),"Core prefix assigned multiple historical routes");pRoute.set(x.prefix_key,x.route_key);if(!members.has(x.route_key))members.set(x.route_key,new Set());members.get(x.route_key).add(x.prefix_key);}
 assert(assoc.length===1510&&pRoute.size===1510&&members.size===254,"Frozen 1510/254 association mismatch");
 const coreMr=await readCsv(path.join(CH3,"core_last_hop_prefix_month_hashed.csv")),coreMs=new Map();
 for(const x of coreMr){let i=MONTHS.indexOf(x.month);assert(i>=0,"Core month invalid");let a=coreMs.get(x.prefix_key);if(!a){a=Array(6).fill(null);coreMs.set(x.prefix_key,a);}assert(!a[i],"Duplicate core month");let e=num(x.last_hop_terminal_geo_attempts),ti=num(x.top_route_ties),sh=num(x.top_route_share),q=e>0&&ti===1&&sh>=.5;assert(q===truth(x.qualified_unique_main_route),"Core month qualification mismatch");a[i]={month:x.month,evidence:e>0,qualified:q,eligible:e,ties:ti,share:sh,routeKey:x.top_route_key||""};}
 assert(coreMs.size===1510&&coreMr.length===9060,"Core monthly grid incomplete");
 const coreClasses=await readCsv(path.join(CH3,"core_last_hop_class_hashed.csv")),cmap=new Map(),coreCounts=Object.fromEntries(CLASSES.map(c=>[c,0]));let identity=0;
 for(const x of coreClasses){assert(!cmap.has(x.prefix_key)&&pRoute.has(x.prefix_key),"Core class key mismatch");let z=classify(coreMs.get(x.prefix_key));assert(z.label===x.class_label&&z.ev===num(x.last_hop_evidence_months)&&z.qn===num(x.qualified_main_route_months)&&z.rs.size===num(x.distinct_qualified_routes),"Core reclassification mismatch");let same=z.label==="Ⅰ类"&&z.stable===pRoute.get(x.prefix_key);assert(same===truth(x.same_original_route_all_six),"Core identity mismatch");if(same)identity++;coreCounts[z.label]++;cmap.set(x.prefix_key,{z,route:pRoute.get(x.prefix_key),same});}
 const coreMonthlyAudit=[];for(const [p,ms] of coreMs){let z=cmap.get(p).z;for(const m of ms)coreMonthlyAudit.push({core_prefix_key:p,month:m.month,evidence_type:"last responding hop with nonempty IP and RTT; IP matches target ASGeo mid-node set; terminal ASGeo label is non-placeholder",evidence_present:m.evidence,eligible_terminal_asgeo_path_observations:m.eligible,unique_top_route_tie_count:m.ties,top_route_share:m.share.toFixed(8),monthly_route_key:m.routeKey,qualified_monthly_main_path:m.qualified,formal_core_class:z.label,effective_month_utc:m.month});}
 writeCsv(path.join(ROOT,"data_audit","core_monthly_last_hop_evidence.csv"),["core_prefix_key","month","evidence_type","evidence_present","eligible_terminal_asgeo_path_observations","unique_top_route_tie_count","top_route_share","monthly_route_key","qualified_monthly_main_path","formal_core_class","effective_month_utc"],coreMonthlyAudit); assert(cmap.size===1510&&identity===576&&JSON.stringify(CLASSES.map(c=>coreCounts[c]))===JSON.stringify([1154,2,249,105,0]),"Core strict counts mismatch");
 const coreRows=[];for(const [p,x] of cmap)coreRows.push({core_prefix_key:p,original_historical_route_key:x.route,strict_last_hop_evidence_class:x.z.label,evidence_months:x.z.ev,qualified_main_path_months:x.z.qn,distinct_qualified_route_identities:x.z.rs.size,recomputed_stable_route_key:x.z.stable,exact_historical_route_key_retained:x.same,validity_window_utc:"2024-07 through 2024-12"});
 writeCsv(path.join(ROOT,"data_audit","core_prefix_evidence_audit.csv"),["core_prefix_key","original_historical_route_key","strict_last_hop_evidence_class","evidence_months","qualified_main_path_months","distinct_qualified_route_identities","recomputed_stable_route_key","exact_historical_route_key_retained","validity_window_utc"],coreRows);
 let histGe3=0,anyKept=0,ge3Kept=0,routeRows=[];
 for(const [route,ps] of members){let kept=Array.from(ps).filter(p=>cmap.get(p).same).length;if(ps.size>=3)histGe3++;if(kept>=1)anyKept++;if(kept>=3)ge3Kept++;routeRows.push({original_historical_route_key:route,historical_core_member_n:ps.size,identity_retained_member_n:kept,identity_not_retained_member_n:ps.size-kept,historical_members_ge3:ps.size>=3,retained_identity_members_ge3:kept>=3});}
 assert(routeRows.reduce((s,x)=>s+x.historical_core_member_n,0)===1510&&routeRows.reduce((s,x)=>s+x.identity_retained_member_n,0)===576&&histGe3===113&&anyKept===115&&ge3Kept===49,"Core route sums mismatch");
 writeCsv(path.join(ROOT,"data_audit","core_path_identity_audit.csv"),["original_historical_route_key","historical_core_member_n","identity_retained_member_n","identity_not_retained_member_n","historical_members_ge3","retained_identity_members_ge3"],routeRows);
 const status=JSON.parse(fs.readFileSync(path.join(CH4,"RUN_STATUS.json"),"utf8")),summary=JSON.parse(fs.readFileSync(path.join(CH4,"00_audit","summary.json"),"utf8")),linkAudit=JSON.parse(fs.readFileSync(path.join(CH4,"00_audit","path_association_audit.json"),"utf8"));
 const endpointDaily=await readCsv(path.join(CH4,"01_endpoint","endpoint_daily_summary.csv")),pathDaily=await readCsv(path.join(CH4,"02_path","path_daily_summary.csv")),ablation=await readCsv(path.join(CH4,"03_ablation_sensitivity","ablation_summary.csv"));
 const obs=await readCsv(path.join(CH4,"02_path","path_endpoint_observability.csv")),episodes=await readCsv(path.join(CH4,"02_path","path_anomaly_episodes_aggregate.csv"));
 const endpoint={ips_evaluable:sum(endpointDaily,"ips_evaluable_n"),ips_candidate:sum(endpointDaily,"ips_candidate_n"),rtt_evaluable:sum(endpointDaily,"rtt_evaluable_n"),rtt_candidate:sum(endpointDaily,"rtt_candidate_n")};
 const pathStats={ips_evaluable:sum(pathDaily,"ips_path_evaluable_n"),ips_candidate:sum(pathDaily,"ips_path_candidate_n"),rtt_evaluable:sum(pathDaily,"rtt_path_evaluable_n"),rtt_candidate:sum(pathDaily,"rtt_path_candidate_n"),union_candidate:sum(pathDaily,"any_path_candidate_n")};
 pathStats.intersection_candidate=pathStats.ips_candidate+pathStats.rtt_candidate-pathStats.union_candidate;
 const a3=ablation.find(x=>x.configuration==="A3_path_multi_endpoint"),a4=ablation.find(x=>x.configuration==="A4_path_multi_endpoint_persistence_ge2h"),input=status.stages.P0_input_inventory.sample,si=summary["4_4_input_audit"],grid=si.row_n;
 const theory=(Date.parse("2025-01-01T00:00:00Z")-Date.parse("2024-07-01T00:00:00Z"))/3600000,missing=theory-input.cycle_n,maxPathCycles=input.path_n*input.cycle_n;
 const reuse=status.stages.P0_input_inventory["4_4_cache_reuse"]||{},diff=reuse.recomputed_vs_cached_score_value_differences||{},decisions=(reuse.checks||{})["4_5_independent_candidate_vs_4_4_frozen_candidate"]||{};
 const dyn={};for(const metric of ["IPS","RTT"]){let rows=obs.filter(x=>x.metric===metric);dyn[metric]={paths_with_3plus_valid_endpoints_at_any_cycle:rows.filter(x=>num(x.cycles_with_min3_valid_n)>0).length,historical_paths_with_3plus_associated_prefixes:rows.filter(x=>num(x.associated_prefix_count)>=3).length};}
 let ids=new Set(),ep2=0,ep3=0,durationMismatch=0;for(const x of episodes){assert(!ids.has(x.event_id),"Duplicate episode ID");ids.add(x.event_id);let h=(Date.parse(x.end_time_utc)-Date.parse(x.start_time_utc))/3600000+1;if(h!==num(x.duration_hours)||!Number.isInteger(h))durationMismatch++;if(truth(x.retained_ge_2h))ep2++;if(truth(x.retained_ge_3h))ep3++;}
 const frozen=fs.readFileSync(path.join(CH4,"07_reproducibility","config","frozen_4_4_baseline_config.yaml"),"utf8");
 function yamlNum(section,key){let active=false;for(const l of frozen.split(/\r?\n/)){if(!/^\s/.test(l))active=l.trim()===section+":";else if(active){let m=l.match(new RegExp("^\\s+"+key+":\\s*([0-9.]+)\\s*$"));if(m)return Number(m[1]);}}return null;}
 const thresholds={ips:yamlNum("ips","score_threshold"),rtt:yamlNum("rtt","score_threshold"),history_window_days:14,minimum_history_hours:236,path_minimum_valid_endpoints:3,path_minimum_abnormal_endpoints:2,path_minimum_abnormal_fraction:.5,persistence_hours:2};
 assert(input.prefix_n===1510&&input.path_n===254&&input.cycle_n===4158&&grid===6278580&&theory===4416&&missing===258&&maxPathCycles===1056132,"Ch4 input/time grid mismatch");
 assert(endpoint.ips_evaluable===5922220&&endpoint.ips_candidate===240325&&endpoint.rtt_evaluable===5281047&&endpoint.rtt_candidate===157968,"Endpoint sums mismatch");
 assert(pathStats.ips_evaluable===443186&&pathStats.ips_candidate===4208&&pathStats.rtt_evaluable===406636&&pathStats.rtt_candidate===4202&&pathStats.union_candidate===8215&&pathStats.intersection_candidate===195,"Path sums mismatch");
 assert(a3&&num(a3.evaluable_n)===443186&&num(a3.candidate_n)===8215&&a4&&num(a4.evaluable_n)===443186&&num(a4.candidate_n)===3909,"A3/A4 mismatch");
 assert(si.ips_zero_n===82162&&si.zero_reconstructed_n===82162&&episodes.length===5866&&ep2===1117&&ep3===515&&durationMismatch===0,"Zero or episode mismatch");
 assert(dyn.IPS.historical_paths_with_3plus_associated_prefixes===113&&linkAudit.frozen_core_prefix_n===1510&&linkAudit.frozen_core_path_n===254&&linkAudit.strict_exact_core_prefix_n===1405&&linkAudit.strict_path_id_n_all_link===248,"Route link audit mismatch");
 assert(thresholds.ips===2.041800735241416&&thresholds.rtt===2.442791575725654,"Threshold mismatch");
 const ch4Rows=[
 ["study UTC theoretical hours",theory,"hours"],["valid measurement cycle timestamps",input.cycle_n,"hours"],["globally missing measurement hours",missing,"hours"],["core prefix-cycle grid",grid,"cells"],["conditional IPS=0 cells",si.zero_reconstructed_n,"cells"],
 ["endpoint IPS evaluable cells",endpoint.ips_evaluable,"cells"],["endpoint IPS candidates",endpoint.ips_candidate,"cells"],["endpoint RTT evaluable cells",endpoint.rtt_evaluable,"cells"],["endpoint RTT candidates",endpoint.rtt_candidate,"cells"],
 ["path IPS evaluable path-cycles",pathStats.ips_evaluable,"path-cycles"],["path IPS candidates",pathStats.ips_candidate,"path-cycles"],["path RTT evaluable path-cycles",pathStats.rtt_evaluable,"path-cycles"],["path RTT candidates",pathStats.rtt_candidate,"path-cycles"],
 ["path candidate union",pathStats.union_candidate,"path-cycles"],["path candidate intersection",pathStats.intersection_candidate,"path-cycles"],["A3 union-evaluable denominator",num(a3.evaluable_n),"path-cycles"],["persistent >=2h candidates",num(a4.candidate_n),"path-cycles"],
 ["historical paths with >=3 members",113,"paths"],["IPS paths with >=3 valid endpoints any cycle",dyn.IPS.paths_with_3plus_valid_endpoints_at_any_cycle,"paths"],["RTT paths with >=3 valid endpoints any cycle",dyn.RTT.paths_with_3plus_valid_endpoints_at_any_cycle,"paths"],
 ["path candidate episodes",episodes.length,"episodes"],["episodes retained >=2h",ep2,"episodes"],["episodes retained >=3h",ep3,"episodes"],["episode duration mismatches",durationMismatch,"episodes"],
 ["route-link exact core prefixes",linkAudit.strict_exact_core_prefix_n,"prefixes"],["route-link strict path IDs",linkAudit.strict_path_id_n_all_link,"paths"],
 ["4.4/4.5 overlap keys source-reported",num(reuse.common_row_n),"keys"],["IPS score differences source-reported",num((diff.IPS||{}).score_mismatch_n),"cells"],["RTT score differences source-reported",num((diff.RTT||{}).score_mismatch_n),"cells"],
 ["IPS decision mismatches source-reported",num((decisions.IPS||{}).IPS_mismatch_n),"cells"],["RTT decision mismatches source-reported",num((decisions.RTT||{}).RTT_mismatch_n),"cells"]
 ].map(x=>({statistic:x[0],value:x[1],unit:x[2],verification_status:x[0].includes("source-reported")?"source-reported; private cycle rows unavailable":"reconciled from archived aggregate tables"}));
 writeCsv(path.join(ROOT,"results","chapter4_verified_statistics.csv"),["statistic","value","unit","verification_status"],ch4Rows);
 // Chapter 3 and cross-chapter tables, with core-local fields explicitly scoped.
 const keyOverlap=Array.from(pRoute.keys()).filter(k=>by.has(k)).length;
 const ch3Rows=[
  {statistic:"unique target /24 population",value:by.size,unit:"/24",verification_status:"complete formal universe"},
  {statistic:"formal strict last-hop monthly evidence rows",value:formalRows,unit:"/24-month",verification_status:"all 42,811 x 6 months"},
  {statistic:"formal class partition sum",value:Object.values(counts).reduce((a,b)=>a+b,0),unit:"/24",verification_status:"mutually exclusive and exhaustive"},
  {statistic:"formal class label mismatches vs cached labels",value:mismatch,unit:"/24",verification_status:"independent monthly reconstruction"},
  {statistic:"formal class I stable route key mismatches",value:keyMismatch,unit:"/24",verification_status:"independent monthly reconstruction"},
  ...CLASSES.map(c=>({statistic:"formal "+c+" "+NAMES[c],value:counts[c],unit:"/24",verification_status:"strict last-hop formal population"})),
  {statistic:"core unique prefix-to-historical-route associations",value:pRoute.size,unit:"/24",verification_status:"directly recounted final association file"},
  {statistic:"core distinct historical route IDs",value:members.size,unit:"paths",verification_status:"directly recounted final association file"},
  ...CLASSES.map(c=>({statistic:"core-local strict evidence "+c,value:coreCounts[c],unit:"/24",verification_status:"core-only monthly reclassification; not a whole-population cross-tab"})),
  {statistic:"core exact historical route identity retained",value:identity,unit:"/24",verification_status:"core-local six-month route-key comparison"},
  {statistic:"historical core paths with >=3 members",value:histGe3,unit:"paths",verification_status:"directly recounted"},
  {statistic:"paths with >=1 exact identity-retained core member",value:anyKept,unit:"paths",verification_status:"directly recounted"},
  {statistic:"paths with >=3 exact identity-retained core members",value:ge3Kept,unit:"paths",verification_status:"directly recounted"},
  {statistic:"full-population/core hashed key overlap",value:keyOverlap,unit:"keys",verification_status:"salts differ; row-level join unavailable"}
 ];
 writeCsv(path.join(ROOT,"results","chapter3_verified_statistics.csv"),["statistic","value","unit","verification_status"],ch3Rows);
 const cross=[
  {check:"formal taxonomy",finding:"42,811 /24; strict actual-last-hop classes reproduce from 42,811 x 6 monthly evidence rows.",scope:"Only one official taxonomy."},
  {check:"Chapter 4 object",finding:"Historical selection chain records 42,811→6,972→4,804→1,652→1,625→1,510; final association independently contains 1,510 /24 and 254 paths.",scope:"Stage counts are archived totals; intermediate membership and exclusion reasons unavailable."},
  {check:"Chapter 4 grouping",finding:"Runner uses all 1,510 core prefixes and frozen 254 retrospective route groups.",scope:"Not strict-I-only; not real-time routes."},
  {check:"4.4–4.6 outputs",finding:"Aggregate daily, path and episode totals reconcile.",scope:"Private cycle Parquet absent; reuse score/candidate checks source-reported."},
  {check:"manuscript coverage",finding:"Chapter 4 excerpt figure/table caption references were checked.",scope:"No complete current Chapter 3/4 DOCX available."}
 ];
 writeCsv(path.join(ROOT,"results","cross_chapter_consistency.csv"),["check","finding","scope"],cross);
 // Caption/reference audit limited to available excerpt.
 const doc=fs.readFileSync(path.join(PAPER,"current_ch4_docx_text.txt"),"utf8"),lines=doc.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),capRe=/^(图|表)\s*(4[-－—]\d+(?:[-－—]\d+)?)\s+(.+)$/u,caps=[];
 for(const l of lines){let m=l.match(capRe);if(m)caps.push({kind:m[1],id:m[2].replace(/[－—]/g,"-"),caption:l});}
 const capCounts=new Map();for(const c of caps){let k=c.kind+"|"+c.id;capCounts.set(k,(capCounts.get(k)||0)+1);}
 const refs=new Map();for(const m of lines.filter(l=>!capRe.test(l)).join("\n").matchAll(/([图表])\s*(4[-－—]\d+(?:[-－—]\d+)?)/gu)){let k=m[1]+"|"+m[2].replace(/[－—]/g,"-");refs.set(k,(refs.get(k)||0)+1);}
 const docRows=caps.map(c=>{let k=c.kind+"|"+c.id;return {document:"Ch4 4.5-4.6 excerpt, 2026-10-23",kind:c.kind,id:c.id,caption_count:capCounts.get(k),reference_count:refs.get(k)||0,status:capCounts.get(k)>1?"DUPLICATE_CAPTION":(refs.get(k)||0)===0?"CAPTION_NOT_CITED":"UNIQUE_CAPTION",caption:c.caption};});
 for(const [k,n] of refs)if(!capCounts.has(k)){let x=k.split("|");docRows.push({document:"Ch4 4.5-4.6 excerpt, 2026-10-23",kind:x[0],id:x[1],caption_count:0,reference_count:n,status:"REFERENCE_WITHOUT_CAPTION",caption:""});}
 docRows.push({document:"Complete current Ch3/Ch4 thesis",kind:"coverage",id:"",caption_count:0,reference_count:0,status:"NOT_AVAILABLE_LOCALLY",caption:"Only a Chapter 4 excerpt and older full draft were available."});
 writeCsv(path.join(ROOT,"results","document_reference_audit.csv"),["document","kind","id","caption_count","reference_count","status","caption"],docRows);
 let dup=docRows.filter(x=>x.status==="DUPLICATE_CAPTION").length,uncited=docRows.filter(x=>x.status==="CAPTION_NOT_CITED").length,unmatched=[...refs.keys()].filter(k=>!capCounts.has(k)).length;
 const issues=[
  {priority:"P0",location:"Archived numerical evidence",issue:"No confirmed computational error in formal classes or reconciled aggregates.",evidence:"Independent strict-month recomputation; set partition checks; Ch4 aggregate sums.",recommendation:"Retain with stated source limits.",rerun:"No for available cache reproduction."},
  {priority:"P1",location:"Ch3 to Ch4 object definition",issue:"Formal 42,811 taxonomy and 1,510/254 historical core are distinct study objects; local hashes prevent direct member join.",evidence:"Historical chain totals plus separate salted identifiers.",recommendation:"Define Ch4 as the Ping/region-selected historical core and avoid formal-class subset claims.",rerun:"Common-ID export only if row-level selection claims are needed."},
  {priority:"P1",location:"Ch4 4.5-4.6 scope statement",issue:"A claim that detection is restricted to formal class I, the 576 exact-key members, or event-time routes conflicts with the actual runner.",evidence:"Runner loads the frozen 1,510/254 retrospective association without class filtering.",recommendation:"Describe all-core retrospective path-group detection; strict evidence remains an annotation.",rerun:"Not if retrospective scope is intended; required if scope changes to strict-only."},
  {priority:"P1",location:"Ch4 candidate and validity claims",issue:"Aggregates support candidate counts but no ground-truth accuracy or physical fault claim.",evidence:"Private cycle data unavailable; no labeled event truth in audit archive.",recommendation:"Use candidate language and preserve IPS=0 preconditions.",rerun:"New truth data required for accuracy."},
  {priority:"P2",location:"Manuscript numbering and wording",issue:"Current full Ch3/Ch4 thesis was unavailable; excerpt audit is incomplete.",evidence:"document_reference_audit.csv.",recommendation:"Run final numbering and cross-reference review on the final DOCX.",rerun:"Document review only."}
 ];
 writeCsv(path.join(ROOT,"results","discrepancy_register.csv"),["priority","location","issue","evidence","recommendation","rerun"],issues);
 const stageLabel=stages.map(x=>({stage_order:x.stage_order,stage:x.stage,prefix24_n:x.prefix24_n,condition:x.recorded_condition}));
 writeCsv(path.join(ROOT,"data_audit","figure_data","figC_historical_core_selection_flow.csv"),["stage_order","stage","prefix24_n","condition"],stageLabel);
 const figD=[
  {measure:"core endpoints",n:1510,denominator:1510,share_pct:"100.00",unit:"/24",interpretation:"frozen retrospective input"},
  {measure:"historical path groups",n:254,denominator:254,share_pct:"100.00",unit:"paths",interpretation:"original association IDs"},
  {measure:"historical paths with >=3 associated members",n:histGe3,denominator:254,share_pct:pct(histGe3,254).toFixed(2),unit:"paths",interpretation:"static association scale"},
  {measure:"IPS-evaluable path-cycles",n:pathStats.ips_evaluable,denominator:maxPathCycles,share_pct:pct(pathStats.ips_evaluable,maxPathCycles).toFixed(2),unit:"path-cycles",interpretation:"of 254 x 4,158 maximum grid"},
  {measure:"RTT-evaluable path-cycles",n:pathStats.rtt_evaluable,denominator:maxPathCycles,share_pct:pct(pathStats.rtt_evaluable,maxPathCycles).toFixed(2),unit:"path-cycles",interpretation:"of 254 x 4,158 maximum grid"},
  {measure:"IPS paths reaching >=3 valid endpoints in any cycle",n:dyn.IPS.paths_with_3plus_valid_endpoints_at_any_cycle,denominator:254,share_pct:pct(dyn.IPS.paths_with_3plus_valid_endpoints_at_any_cycle,254).toFixed(2),unit:"paths",interpretation:"dynamic observability"},
  {measure:"RTT paths reaching >=3 valid endpoints in any cycle",n:dyn.RTT.paths_with_3plus_valid_endpoints_at_any_cycle,denominator:254,share_pct:pct(dyn.RTT.paths_with_3plus_valid_endpoints_at_any_cycle,254).toFixed(2),unit:"paths",interpretation:"dynamic observability"},
  {measure:"candidate union path-cycles",n:pathStats.union_candidate,denominator:num(a3.evaluable_n),share_pct:pct(pathStats.union_candidate,num(a3.evaluable_n)).toFixed(2),unit:"path-cycles",interpretation:"not accuracy"}
 ];
 writeCsv(path.join(ROOT,"data_audit","figure_data","figD_path_scale_evaluable_coverage.csv"),["measure","n","denominator","share_pct","unit","interpretation"],figD);
 // Four manuscript-appropriate figures only.
 const C={navy:"#1d3557",blue:"#457b9d",teal:"#2a9d8f",gold:"#e9c46a",orange:"#f4a261",red:"#c84c3a",ink:"#1f2937",muted:"#64748b",grid:"#dbe3ea",green:"#4d9a7b"};
 {
  let w=1500,h=790,c=text(60,60,"图A  42,811 个末端/24的唯一正式五类分布",32,C.ink,700)+text(60,108,"分类依据：实际末跳 ASGeo 证据、月度主路径及跨月路径身份；分母为完整总体",19,C.muted);
  const colors=[C.teal,C.blue,C.gold,C.orange,"#aab5c2"],max=22147,x=330,bw=850;
  classRows.forEach((z,i)=>{let y=175+i*105,b=bw*z.prefix24_n/max;c+=text(300,y+31,z.class_label+" "+z.class_name,20,C.ink,650,"end")+rect(x,y,Math.max(3,b),54,colors[i],colors[i],8,1)+text(x+b+18,y+26,z.prefix24_n.toLocaleString("en-US")+" /24",21,C.ink,700)+text(x+b+18,y+50,z.share_pct+"%",17,C.muted);});
  c+=line(60,710,1440,710,C.grid,2)+text(60,750,"合计 42,811 /24 · 100.00%。条长按数量比例绘制。",16,C.muted);save("figA_formal_five_class_distribution",w,h,c);
 }
 {
  let w=1600,h=1100,c=text(60,58,"图B  正式五类路径观测状态及证据条件",31,C.ink,700);
  c+=text(60,103,"月度资格：末跳 ASGeo 路径观测数 >0，最高路径唯一，且 top_share ≥0.5。",18,C.muted);
  c+=text(60,137,"有效证据：末个有响应且具 RTT 的 hop IP 命中目标 ASGeo 中间节点集合；末端 ASGeo 标签非占位值。",17,C.muted);
  const cards=[["Ⅰ  跨月主路径一致","6/6 月有末跳证据；6/6 月主路径均合格；六个月路径身份一致。",C.teal],["Ⅱ  跨月主路径变化","6/6 月有末跳证据；6/6 月主路径均合格；跨月路径身份数 ≥2。",C.blue],["Ⅲ  阶段性主路径可判定","6/6 月有末跳证据；至少1个月但不足6个月有合格月度主路径。",C.gold],["Ⅳ  无合格月度主路径","6/6 月有末跳证据；六个月均无合格月度主路径。",C.orange],["Ⅴ  末端路径证据不完整","末跳 ASGeo 证据少于6个月；优先判定，之后不再判Ⅰ—Ⅳ。",C.red]];
  const pos=[[60,180,710,245],[830,180,710,245],[60,450,710,245],[830,450,710,245],[60,720,1480,235]];
  cards.forEach((a,i)=>{let p=pos[i];c+=rect(p[0],p[1],p[2],p[3],"#ffffff",a[2],14,3)+rect(p[0],p[1],12,p[3],a[2],a[2],6,1)+text(p[0]+35,p[1]+57,a[0],22,C.ink,700);let words=a[1].match(/.{1,38}/gu)||[a[1]];words.forEach((s,j)=>c+=text(p[0]+35,p[1]+112+j*38,s,18,C.ink,450));});
  c+=text(60,990,"优先级：Ⅴ → Ⅰ → Ⅱ → Ⅲ → Ⅳ。",17,C.muted)+text(60,1030,"有效期：2024-07 至 2024-12 UTC。",17,C.muted);save("figB_formal_class_conditions",w,h,c);
 }
 {
  let w=1900,h=830,c=text(60,58,"图C  全部目标/24到第四章核心对象的历史筛选链",31,C.ink,700)+text(60,105,"历史研究对象构建记录；阶段汇总不等于正式五类的类别迁移。",19,C.muted);
  c+='<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#64748b"/></marker></defs>';
  const a=[["目标总体","42,811","2024-07—12 目标 /24"],["月度主路径","6,972","6/6月唯一且占比≥50%"],["历史路径一致","4,804","六个月相同历史路径身份"],["Ping关联","1,652","稳定关联且有成功Ping"],["地区筛选","1,625","地区纯度条件"],["核心对象","1,510","最终ASGeo核心样本"]];
  const x0=45,y=175,nw=275,nh=220,gap=36;a.forEach((q,i)=>{let x=x0+i*(nw+gap),co=i===5?C.green:i===2?C.gold:C.blue;c+=rect(x,y,nw,nh,i===5?"#e9f5ef":i===2?"#fff8df":"#eef4f8",co,14,2)+text(x+nw/2,y+48,q[0],19,C.ink,650,"middle")+text(x+nw/2,y+112,q[1],33,i===5?C.green:C.navy,700,"middle")+text(x+nw/2,y+164,q[2].slice(0,18),15,C.muted,400,"middle")+text(x+nw/2,y+188,q[2].slice(18),15,C.muted,400,"middle");if(i<5)c+=line(x+nw+4,y+nh/2,x+nw+gap-5,y+nh/2,C.muted,3,true);});
  c+=rect(55,470,1780,130,"#f5f8fa",C.grid,12,2)+text(85,515,"第四章关联文件：1,510 个 /24 一对一映射到 254 条原历史路径（回顾性分组）。",21,C.ink,700)+text(85,562,"阶段成员清单及 1,625→1,510 的逐前缀排除原因未包含在本地匿名材料中。",18,C.muted);
  c+=rect(55,650,1780,105,"#fff9e8","#e6c66c",12,2)+text(85,693,"4,804 是历史筛选链的阶段计数，不是第二套正式分类；阶段数不能替代逐前缀交集。",18,C.ink,600)+text(85,730,"正式末跳五类见图A；本图不表示两套分类间的流向。",16,C.muted);save("figC_historical_core_selection_flow",w,h,c);
 }
 {
  let w=1550,h=880,c=text(60,58,"图D  第四章核心路径关联规模与可评价覆盖",31,C.ink,700)+text(60,105,"检测输入沿用 1,510 个核心末端和 254 条回顾性历史路径。",19,C.muted);
  c+=rect(60,140,470,145,"#eef4f8",C.blue,14,2)+text(90,190,"1,510 个核心 /24",25,C.navy,700)+text(90,240,"每个前缀唯一归属一条历史路径",17,C.muted);
  c+=rect(560,140,390,145,"#e9f5ef",C.green,14,2)+text(590,190,"254 条历史路径",25,C.green,700)+text(590,240,"113 条静态成员数 ≥3",17,C.muted);
  c+=rect(980,140,510,145,"#fff8df",C.gold,14,2)+text(1010,190,"1,056,132 个最大路径周期格",23,C.ink,650)+text(1010,240,"254 路径 × 4,158 个有效时点",17,C.muted);
  c+=text(60,350,"路径—周期可评价覆盖（相对 254 × 4,158 最大网格）",20,C.ink,700);
  const bars=[["IPS",pathStats.ips_evaluable,pct(pathStats.ips_evaluable,maxPathCycles),C.teal],["RTT",pathStats.rtt_evaluable,pct(pathStats.rtt_evaluable,maxPathCycles),C.blue]];
  bars.forEach((q,i)=>{let y=395+i*95,bw=820*q[2]/100;c+=text(170,y+34,q[0],20,C.ink,700,"end")+rect(205,y,bw,52,q[3],q[3],8,1)+text(225+bw,y+25,q[1].toLocaleString("en-US")+" / 1,056,132",18,C.ink,650)+text(225+bw,y+49,q[2].toFixed(2)+"%",16,C.muted);});
  c+=text(60,610,"至少一个周期有 ≥3 个有效端点的路径：IPS "+dyn.IPS.paths_with_3plus_valid_endpoints_at_any_cycle+"/254；RTT "+dyn.RTT.paths_with_3plus_valid_endpoints_at_any_cycle+"/254。",17,C.ink,550);
  c+=text(60,660,"冻结阈值：有效端点 N≥3、异常端点 K≥2、异常比例 Q≥0.5。可评价覆盖和候选数不代表准确率。",17,C.muted);
  c+=text(60,715,"候选并集 8,215 path-cycles；A3 可评价分母 443,186；持续≥2h保留 3,909 path-cycles。",17,C.muted);
  c+=text(60,785,"历史路径是回顾性关联，不等于异常时刻真实转发路径。",16,C.muted);save("figD_path_scale_evaluable_coverage",w,h,c);
 }
 const srcFiles=walk(path.join(ROOT,"data_audit","source_snapshots")),inventory=[];for(const f of srcFiles.sort())inventory.push({file:path.relative(ROOT,f).replace(/\\/g,"/"),bytes:fs.statSync(f).size,sha256:await sha(f),role:f.endsWith(".docx")?"user manuscript excerpt":"archived anonymized/public source"});
 writeCsv(path.join(ROOT,"data_audit","source_inventory.csv"),["file","bytes","sha256","role"],inventory);
 const lineage=[
  {dataset:"full_population_prefix_month_hashed.csv.gz",source:"chapter3_asgeo_final_closure_20261020_public.zip",unit:"hashed /24 × month × criterion",purpose:"Only target_asgeo_last_hop rows are used to reconstruct the formal taxonomy.",limit:"Aggregates only; raw traceroute and ClickHouse query not rerun."},
  {dataset:"full_population_class_hashed.csv",source:"chapter3_asgeo_final_closure_20261020_public.zip",unit:"hashed /24 × criterion",purpose:"Comparison target only for formal last-hop labels.",limit:"Same upstream archive."},
  {dataset:"core_last_hop_prefix_month_hashed.csv + core_path_prefix_association_hashed.csv",source:"chapter3_asgeo_final_closure_20261020_public.zip",unit:"core /24 × month and /24-to-historical-route",purpose:"Core-local strict evidence and path identity.",limit:"Different salt from full-population export."},
  {dataset:"historical_sample_selection_chain.csv",source:"chapter3_asgeo_final_closure_20261020_public.zip",unit:"historical stage totals",purpose:"Historical object chain only.",limit:"Intermediate member IDs and exclusion reasons unavailable; 4,804 is not a formal class result."},
  {dataset:"endpoint/path daily summaries, observability and episodes",source:"chapter4_section45_46_closure_final_20261023.zip",unit:"daily and aggregate candidate tables",purpose:"Reconcile Chapter 4 counts and coverage.",limit:"Private cycle-level Parquet absent."},
  {dataset:"current_ch4_docx_text.txt",source:"chapter4_section45_46_thesis_figures_final_20261023_FINAL.zip",unit:"available excerpt text",purpose:"Caption/reference audit.",limit:"No complete current thesis DOCX."}
 ];
 writeCsv(path.join(ROOT,"data_audit","dataset_lineage.csv"),["dataset","source","unit","purpose","limit"],lineage);
 const summaryOut={audit_date:"2026-10-26",formal_taxonomy:"one formal taxonomy: actual last-hop ASGeo evidence",
  chapter3:{target_prefixes:by.size,formal_monthly_evidence_rows:formalRows,archived_monthly_rows_scanned:archiveRows,counts:counts,shares_pct:Object.fromEntries(CLASSES.map(c=>[c,pct(counts[c],42811).toFixed(2)])),partition_total:Object.values(counts).reduce((a,b)=>a+b,0),label_mismatches:mismatch,stable_route_key_mismatches:keyMismatch,
   core_prefixes:1510,core_historical_paths:254,core_local_strict_evidence_counts:coreCounts,core_exact_historical_route_identity_retained:identity,core_paths_original_members_ge3:histGe3,paths_with_any_identity_retained:anyKept,paths_with_ge3_identity_retained:ge3Kept,
   historical_selection_stages:stages.map(x=>({stage:x.stage,prefix24_n:x.prefix24_n})),full_population_core_hash_key_overlap:keyOverlap},
  chapter4:{prefixes:input.prefix_n,paths:input.path_n,valid_cycle_hours:input.cycle_n,theoretical_hours:theory,globally_missing_hours:missing,grid_cells:grid,max_possible_path_cycles:maxPathCycles,endpoint:endpoint,path:pathStats,
   path_union_evaluable_path_cycles:num(a3.evaluable_n),persistence_ge_2h_path_cycles:num(a4.candidate_n),episodes:{total:episodes.length,retained_ge_2h:ep2,retained_ge_3h:ep3,utc_duration_mismatches:durationMismatch},dynamic_paths:dyn,route_link_audit:linkAudit,thresholds:thresholds,
   score_reuse_source_report:{overlap_keys:num(reuse.common_row_n),ips_score_differences:num((diff.IPS||{}).score_mismatch_n),rtt_score_differences:num((diff.RTT||{}).score_mismatch_n),ips_decision_mismatches:num((decisions.IPS||{}).IPS_mismatch_n),rtt_decision_mismatches:num((decisions.RTT||{}).RTT_mismatch_n)}},
  document:{caption_count:caps.length,duplicate_captions:dup,uncited_captions:uncited,unmatched_references:unmatched,complete_current_thesis_available:false},
  limits:["Formal classes were independently reconstructed from an archived monthly aggregate; ClickHouse and raw traceroute rows were not rerun.","Full-population and core prefix hashes use different salts; no direct row-level join is available.","Historical selection archive provides stage counts only, not intermediate member sets or removal reasons.","Private Chapter 4 cycle-level Parquet is missing; daily/episode sums were reconciled, but cache replay checks are source-reported.","Only a Chapter 4 excerpt was locally available; whole thesis wording/numbering remains unaudited."]};
 fs.writeFileSync(path.join(ROOT,"results","audit_summary.json"),JSON.stringify(summaryOut,null,2)+"\n","utf8");
 const figureNotes="# 图表说明与数据来源\n\n"+
 "## 图A：正式五类分布\n来源：42,811×6 月末跳 ASGeo 匿名证据缓存独立重算。结论：正式五类数量与比例可复现。适用：第三章分类结果。\n\n"+
 "## 图B：正式分类条件\n来源：正式末跳证据规则、唯一主路径及 50% 条件。适用：第三章分类方法/定义。不含任何类别迁移分析。\n\n"+
 "## 图C：历史核心筛选链\n来源：归档历史阶段总数与 1,510→254 关联文件。成员级中间集合和最终排除原因不可用。4,804 仅作历史构建阶段数。\n\n"+
 "## 图D：第四章路径规模与可评价覆盖\n来源：核心路径关联文件、路径日汇总、端点可观测表及 A3/A4 汇总。覆盖不代表检测准确率；历史路径不是实时转发路径。\n\nSVG、PNG 预览和矢量 PDF 均提供；图中数值表见 data_audit/figure_data/。\n";
 fs.writeFileSync(path.join(ROOT,"figures","FIGURE_NOTES.md"),figureNotes,"utf8");
 console.log(JSON.stringify({formal_counts:counts,formal_monthly_rows:formalRows,class_mismatches:mismatch,route_key_mismatches:keyMismatch,core:1510,historical_paths:254,core_identity_retained:identity,chapter4_path:pathStats,figures:4,source_files:inventory.length},null,2));
}
main().catch(e=>{console.error(e.stack||String(e));process.exitCode=1;});
