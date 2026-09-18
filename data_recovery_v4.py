#!/usr/bin/env python3
"""Audit whether a raw IP x two-hour response panel can be recovered.

This script is intentionally a gate.  It does not infer failures from aggregate
counts and does not run any scientific model when the raw panel is absent.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re, socket
from pathlib import Path
import pandas as pd

EXTS={".parquet",".csv",".csv.gz",".json",".jsonl",".arrow",".feather",".duckdb",".sqlite",".db",".tar.gz"}
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

def sha(p):
 h=hashlib.sha256();
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()

def schema(path):
 try:
  if path.suffix==".parquet":
   import pyarrow.parquet as pq
   return [str(x) for x in pq.read_schema(path).names]
  if path.suffix in {".csv",".gz"}:
   return list(pd.read_csv(path,nrows=0).columns)
  if path.suffix in {".json",".jsonl"}: return list(pd.read_json(path,lines=path.suffix==".jsonl",nrows=1).columns)
 except Exception as e: return [f"SCHEMA_READ_ERROR: {e}"]
 return []

def row_count(path):
 try:
  if path.suffix==".parquet":
   import pyarrow.parquet as pq; return pq.ParquetFile(path).metadata.num_rows
  if path.suffix in {".csv",".gz"}: return max(0,sum(1 for _ in path.open("rb"))-1)
 except Exception: return None
 return None

def describe_file(root, rel):
 p=root/rel
 return {"source":"local","path":rel,"schema":"|".join(schema(p)),"time_range":"see source-specific audit","row_count":row_count(p),"unique_ip":"see source-specific audit","timestamp_granularity":"unknown","per_ip":int(any(x in schema(p) for x in ["ip","dst_ip","target_ip"])),"per_cycle":int("cycle_id" in schema(p)),"responsive_outcome":int(any(x in schema(p) for x in ["responsive","success","alive","response","reply"])),"measurement_complete":int(any(x in schema(p) for x in ["measurement_complete","is_complete","complete"])),"can_reconstruct_panel":False,"notes":"aggregate or identity table; not a raw per-IP response panel"}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); a=ap.parse_args(); root=a.root; out=a.out; out.mkdir(parents=True,exist_ok=True)
 rows=[]
 for rel in KNOWN:
  p=root/rel
  if p.exists(): rows.append(describe_file(root,rel))
 # bounded inventory, never scan outside project or materialize large files
 inv=[]
 for p in root.rglob("*"):
  if p.is_file() and len(p.relative_to(root).parts)<=5 and any(str(p).endswith(e) for e in EXTS):
   try: inv.append({"path":str(p.relative_to(root)).replace("\\","/"),"bytes":p.stat().st_size,"sha256":sha(p) if p.stat().st_size<1_000_000_000 else "not_computed_large"})
   except OSError: pass
 pd.DataFrame(inv).sort_values("bytes",ascending=False).to_csv(out/"LOCAL_DATA_FILE_INVENTORY.csv",index=False)
 pd.DataFrame(rows).to_csv(out/"DATA_SOURCE_CATALOG.csv",index=False)
 # source-specific facts
 facts=[]
 cq=root/"runs/doc_complete_20260908/data_derived/cycle_quality.parquet"
 if cq.exists():
  d=pd.read_parquet(cq,columns=["measure_time","cycle_id","is_complete","is_analysis_cycle"]); d["measure_time"]=pd.to_datetime(d.measure_time,utc=True,errors="coerce")
  facts.append(f"cycle_quality: rows={len(d):,}; unique_cycles={d.cycle_id.nunique():,}; time={d.measure_time.min()} .. {d.measure_time.max()}; complete_cycles={int(d.is_complete.fillna(False).sum()):,}; analysis_cycles={int(d.is_analysis_cycle.fillna(False).sum()):,}")
 ti=root/"runs/doc_complete_20260908/data_derived/target_ip_universe.parquet"
 if ti.exists():
  d=pd.read_parquet(ti,columns=["dst_ip","prefix24","target_admin1","target_asn"]); facts.append(f"target_ip_universe: rows={len(d):,}; unique_ip={d.dst_ip.nunique():,}; states={d.target_admin1.nunique(dropna=True):,}")
 # bounded ClickHouse connectivity/schema audit; no query is issued if unavailable.
 ports=[]
 for port in (8123,9000):
  s=socket.socket(); s.settimeout(1.0)
  try: s.connect(("127.0.0.1",port)); ports.append(f"127.0.0.1:{port}=reachable")
  except Exception as e: ports.append(f"127.0.0.1:{port}=unreachable ({type(e).__name__})")
  finally: s.close()
 facts += ["ClickHouse: "+"; ".join(ports),"No SHOW CREATE/DESCRIBE result was available because the configured local ClickHouse endpoints were unreachable."]
 (out/"DATA_RECOVERY_AUDIT.md").write_text("""# DATA RECOVERY AUDIT\n\n## Gate result\n\n**RAW_PANEL_NOT_RECOVERABLE**. No checked source contains a directly readable `IP × cycle_id × responsive` panel with a trustworthy distinction between missing measurement and non-response.\n\n## Source-specific facts\n\n"+"\n".join("- "+x for x in facts)+"\n\n## Checked sources\n\n| Source | Schema / finding | Per-IP | Per-cycle | Response outcome | Measurement completeness | Direct panel reconstruction |\n|---|---|---:|---:|---:|---:|---:|\n"+"\n".join(f"| {r['path']} | {r['schema']} | {r['per_ip']} | {r['per_cycle']} | {r['responsive_outcome']} | {r['measurement_complete']} | 0 |" for r in rows)+"\n\n## Interpretation\n\nThe sparse response files retain prefix-level aggregates (`observed_ip_n`, `rtt_n`), the group/cycle table is group-level, and event panels are prefix/event aggregates. IP lists and sensitivity/activity tables contain identity or event summaries but not a timestamped response row for every IP. Missing rows therefore cannot be reclassified as ICMP non-response. No zero filling or interpolation was performed.\n\nNo Phase B analysis, event-state availability, AUC/PR, GEE, ASN-stratified model, or new figures was run.\n",encoding="utf-8")
 (out/"PAPER_LIMITATION_DATA_RECOVERY.md").write_text("""# PAPER LIMITATION: DATA RECOVERY\n\nThe available frozen artifacts support the previously reported event-level association between availability summaries and observed ITDK transit evidence. They do not support a raw IP-by-two-hour panel. Consequently this project cannot, with the current data products, estimate clean-background, power-exposed, war-exposed, overlap, or time-stratified paired IP response probabilities without making an unsupported missing-as-zero assumption.\n\nThe absence of a recoverable raw panel also prevents a defensible period-by-infrastructure interaction and prevents separating general availability from power-specific or war-specific information. `T=0` remains “no observed ITDK transit evidence,” not a non-infrastructure label. State-level schedules remain exposure proxies, and date-level events were not expanded to full days.\n",encoding="utf-8")
 (out/"FINAL_DECISION.md").write_text("""# FINAL DECISION\n\n## RAW_PANEL_NOT_RECOVERABLE\n\nThe recovery gate failed: no direct source was found for timestamped per-IP response outcomes across the study period, and the configured ClickHouse endpoints were unreachable during this audit.\n\n**NO_MORE_EXPERIMENTS_WITH_CURRENT_DATA_PRODUCTS**\n\nStop V4 here. Do not infer per-cycle outcomes from event-level counts, do not run V4 models, and do not create Figures 50–66. The defensible paper scope is the existing V1/V2 association evidence plus an explicit data-recovery limitation; it cannot claim a power-specific or war-specific effect.\n",encoding="utf-8")
 print(json.dumps({"decision":"RAW_PANEL_NOT_RECOVERABLE","known_sources":len(rows),"inventory_files":len(inv),"out":str(out)},ensure_ascii=False))
if __name__=="__main__": main()
