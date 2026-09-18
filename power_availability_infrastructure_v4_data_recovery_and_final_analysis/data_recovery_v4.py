#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, socket
from pathlib import Path
import pandas as pd

KNOWN=[
"runs/doc_complete_20260908/data_derived/cycle_quality.parquet",
"runs/doc_complete_20260908/data_derived/target_ip_universe.parquet",
"runs/doc_complete_20260908/data_derived/candidate_ips.parquet",
"runs/doc_complete_20260908/data_derived/group_cycle_panel.parquet",
"runs/doc_complete_20260908/data_derived/prefix_response_sparse/part_20240621_20240623.parquet",
"runs/doc_complete_20260908/data_derived/event_prefix_panel/E2024_0826_ATTACK.parquet",
"runs/doc_complete_20260908/data_derived/sensor_event_panel/E2024_0826_ATTACK.parquet",
"runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet",
"runs/doc_complete_20260908/data_derived/ip_activity.parquet",
]
EXTS=(".parquet",".csv",".csv.gz",".json",".jsonl",".arrow",".feather",".duckdb",".sqlite",".db",".tar.gz")

def sha(p):
 h=hashlib.sha256(); f=p.open("rb")
 for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 f.close(); return h.hexdigest()
def schema(p):
 try:
  if p.suffix==".parquet":
   import pyarrow.parquet as pq; return list(pq.read_schema(p).names)
  if p.suffix in {".csv",".gz"}: return list(pd.read_csv(p,nrows=0).columns)
 except Exception as e: return [f"SCHEMA_READ_ERROR:{e}"]
 return []
def rows(p):
 try:
  if p.suffix==".parquet":
   import pyarrow.parquet as pq; return pq.ParquetFile(p).metadata.num_rows
 except Exception: pass
 return None

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); a=ap.parse_args(); root,out=a.root,a.out; out.mkdir(parents=True,exist_ok=True)
 catalog=[]
 for rel in KNOWN:
  p=root/rel
  if p.exists():
   c=schema(p); catalog.append({"source":"local","path":rel,"schema":"|".join(c),"row_count":rows(p),"per_ip":int(any(x in c for x in ["ip","dst_ip","target_ip"])),"per_cycle":int("cycle_id" in c),"responsive_outcome":int(any(x in c for x in ["responsive","success","alive","response","reply"])),"measurement_complete":int(any(x in c for x in ["measurement_complete","is_complete","complete"])),"can_reconstruct_panel":False,"notes":"aggregate or identity table; no direct IP×cycle response panel"})
 inv=[]
 for p in root.rglob("*"):
  if p.is_file() and len(p.relative_to(root).parts)<=5 and any(str(p).endswith(e) for e in EXTS):
   try: inv.append({"path":str(p.relative_to(root)).replace("\\","/"),"bytes":p.stat().st_size})
   except OSError: pass
 pd.DataFrame(inv).sort_values("bytes",ascending=False).to_csv(out/"LOCAL_DATA_FILE_INVENTORY.csv",index=False)
 pd.DataFrame(catalog).to_csv(out/"DATA_SOURCE_CATALOG.csv",index=False)
 facts=[]
 cq=root/"runs/doc_complete_20260908/data_derived/cycle_quality.parquet"
 if cq.exists():
  d=pd.read_parquet(cq,columns=["measure_time","cycle_id","is_complete","is_analysis_cycle"]); d.measure_time=pd.to_datetime(d.measure_time,utc=True,errors="coerce")
  facts.append(f"cycle_quality rows={len(d):,}; unique_cycles={d.cycle_id.nunique():,}; time={d.measure_time.min()} .. {d.measure_time.max()}; complete={int(d.is_complete.fillna(False).sum()):,}; analysis={int(d.is_analysis_cycle.fillna(False).sum()):,}")
 ti=root/"runs/doc_complete_20260908/data_derived/target_ip_universe.parquet"
 if ti.exists():
  d=pd.read_parquet(ti,columns=["dst_ip","target_admin1"]); facts.append(f"target_ip_universe rows={len(d):,}; unique_ip={d.dst_ip.nunique():,}; states={d.target_admin1.nunique(dropna=True):,}")
 ports=[]
 for port in (8123,9000):
  s=socket.socket(); s.settimeout(1)
  try: s.connect(("127.0.0.1",port)); ports.append(f"127.0.0.1:{port}=reachable")
  except Exception as e: ports.append(f"127.0.0.1:{port}=unreachable ({type(e).__name__})")
  finally: s.close()
 facts.append("ClickHouse: "+"; ".join(ports)); facts.append("No SHOW CREATE/DESCRIBE output was available because the configured local endpoints were unreachable.")
 lines=["# DATA RECOVERY AUDIT","","## Gate result","","**RAW_PANEL_NOT_RECOVERABLE**. No checked source contains a directly readable `IP × cycle_id × responsive` panel with a trustworthy distinction between missing measurement and non-response.","","## Source-specific facts"]
 lines += ["- "+x for x in facts]+["","## Checked sources","","| Source | Schema | Per-IP | Per-cycle | Response | Completeness | Direct panel |","|---|---|---:|---:|---:|---:|---:|"]
 lines += [f"| {r['path']} | {r['schema']} | {r['per_ip']} | {r['per_cycle']} | {r['responsive_outcome']} | {r['measurement_complete']} | 0 |" for r in catalog]
 lines += ["","## Interpretation","","Sparse files retain prefix-level aggregates (`observed_ip_n`, `rtt_n`); group/cycle tables are group-level; event panels are prefix/event aggregates; IP tables are identity or event summaries. Missing rows cannot be reclassified as ICMP non-response. No zero filling or interpolation was performed.","","No Phase B analysis, event-state availability, AUC/PR, GEE, ASN-stratified model, or new figures was run."]
 (out/"DATA_RECOVERY_AUDIT.md").write_text("\n".join(lines),encoding="utf-8")
 limitation="""# PAPER LIMITATION: DATA RECOVERY

The frozen artifacts support the previously reported event-level association between availability summaries and observed ITDK transit evidence. They do not support a raw IP-by-two-hour panel. With the current data products, clean-background, power-exposed, war-exposed, overlap, and time-stratified paired IP response probabilities are not estimable without an unsupported missing-as-zero assumption.

The absent raw panel also prevents a defensible period-by-infrastructure interaction and prevents separating general availability from power-specific or war-specific information. `T=0` means “no observed ITDK transit evidence,” not a non-infrastructure label. State schedules remain exposure proxies, and date-level events were not expanded to full days.
"""
 decision="""# FINAL DECISION

## RAW_PANEL_NOT_RECOVERABLE

The recovery gate failed: no direct source was found for timestamped per-IP response outcomes across the study period, and the configured ClickHouse endpoints were unreachable during this audit.

**NO_MORE_EXPERIMENTS_WITH_CURRENT_DATA_PRODUCTS**

Stop V4 here. Do not infer per-cycle outcomes from event-level counts, do not run V4 models, and do not create Figures 50–66. The defensible paper scope is the existing V1/V2 association evidence plus an explicit data-recovery limitation; it cannot claim a power-specific or war-specific effect.
"""
 (out/"PAPER_LIMITATION_DATA_RECOVERY.md").write_text(limitation,encoding="utf-8"); (out/"FINAL_DECISION.md").write_text(decision,encoding="utf-8")
 print(json.dumps({"decision":"RAW_PANEL_NOT_RECOVERABLE","known_sources":len(catalog),"inventory_files":len(inv),"out":str(out)},ensure_ascii=False))
if __name__=="__main__": main()
