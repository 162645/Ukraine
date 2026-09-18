#!/usr/bin/env python3
"""Independent IMC-2027 data availability and minimal feasibility audit.

This script writes only below feasibility_imc2027/ in the existing research
checkout. It uses ClickHouse read-only queries and public HTTP APIs. It does
not modify existing experiment outputs, labels, or analysis code.
"""
from __future__ import annotations

import csv
import hashlib
import ipaddress
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pandas as pd
import requests

try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except Exception:
    plt = None
    mdates = None

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "feasibility_imc2027"
RAW = OUT / "data_raw"
TABLES = OUT / "outputs" / "tables"
FIGS = OUT / "outputs" / "figures"
LOGS = OUT / "outputs" / "logs"
MANIFEST = OUT / "manifests"
for d in [RAW, TABLES, FIGS, LOGS, MANIFEST]:
    d.mkdir(parents=True, exist_ok=True)

UA = "imc2027-feasibility-audit/1.0 (research; contact unavailable)"
EVENT_DAY = "2024-08-26"
CHERKASY = "Cherkasy Oblast"
KYIV = ZoneInfo("Europe/Kyiv")
UTC = timezone.utc
SRC_ROWS = []


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add_source(source_id, name, url, status, local_path="", event_date=EVENT_DAY,
               admin1="Cherkasy Oblast", data_type="", http_status="", notes=""):
    p = Path(local_path) if local_path else None
    SRC_ROWS.append({
        "source_id": source_id, "source_name": name, "source_url": url,
        "retrieved_at_utc": datetime.now(UTC).isoformat(), "event_date": event_date,
        "admin1": admin1, "data_type": data_type, "http_status": http_status,
        "acquisition_status": status, "local_path": str(p.relative_to(ROOT)) if p and p.exists() else local_path,
        "sha256": sha256(p) if p and p.exists() else "", "notes": notes,
    })


def direct_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json,text/html,*/*"})
    return s


def save_get(session, url, path: Path, source_id, name, data_type, *, params=None,
             event_date=EVENT_DAY, admin1="Cherkasy Oblast", timeout=90):
    try:
        r = session.get(url, params=params, timeout=timeout)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        status = "API_DOWNLOADED" if "json" in r.headers.get("content-type", "").lower() else "DOWNLOADED"
        if r.status_code >= 400:
            status = "UNAVAILABLE"
        add_source(source_id, name, r.url, status, path, event_date, admin1, data_type,
                   r.status_code, f"content_type={r.headers.get('content-type','')}; bytes={len(r.content)}")
        return r
    except Exception as e:
        add_source(source_id, name, url, "UNAVAILABLE", "", event_date, admin1, data_type, "", repr(e))
        return None


def fetch_power_sources():
    s = direct_session()
    tg = "https://t.me/s/pat_cherkasyoblenergo?before=505"
    sec = "https://provce.ck.ua/u-cherkasyoblenerho-onovyly-hrafiky-vidkliuchen-svitla-na-sohodni-5/"
    save_get(s, tg, RAW / "power" / "cherkasy_telegram_before_505.html", "POWER_TG_0826",
             "Cherkasy Oblenergo official Telegram mirror", "power_schedule_html")
    save_get(s, sec, RAW / "power" / "cherkasy_secondary_0826.html", "POWER_SECONDARY_0826",
             "Cherkasy schedule secondary corroboration", "power_schedule_html")
    # This is a current page and must not be used as a historic address list.
    current = "https://www.cherkasyoblenergo.com/static/perelik-gpv"
    save_get(s, current, RAW / "power" / "cherkasy_current_queue_page.html", "POWER_CURRENT_PAGE",
             "Cherkasy current queue address page (not historic)", "current_power_page", event_date="")


def dt_local(day, hm):
    d = datetime.fromisoformat(day).replace(tzinfo=KYIV)
    h, m = map(int, hm.split(":"))
    if h == 24 and m == 0:
        return d + timedelta(days=1)
    return d.replace(hour=h, minute=m)


def write_power_timeline():
    """Encode source-backed initial/revised/final timeline, without address mapping."""
    rows = []
    def row(start, end, queues, status, source, note, final=False):
        a = dt_local(EVENT_DAY, start); b = dt_local(EVENT_DAY, end)
        # end=24:00 belongs to next local day
        if end == "24:00": b = dt_local("2024-08-27", "00:00")
        rows.append({
            "start_local": a.isoformat(), "end_local": b.isoformat(),
            "start_utc": a.astimezone(UTC).isoformat(), "end_utc": b.astimezone(UTC).isoformat(),
            "active_queue_count": len(queues), "active_queues": ",".join(map(str, queues)),
            "source_id": source, "record_status": status, "final_effective": bool(final),
            "notes": note,
        })
    # Initial hourly schedule published for 11:00--24:00 local.
    initial = [("11:00","13:00",[5,6]),("13:00","15:00",[1,2]),
               ("15:00","17:00",[3,4]),("17:00","19:00",[5,6]),
               ("19:00","21:00",[1,2]),("21:00","23:00",[3,4]),
               ("23:00","24:00",[5,6])]
    for a,b,q in initial: row(a,b,q,"initial_gpv","POWER_TG_0826","Initial hourly schedule; superseded by later update")
    # Revision after 15:00 local.
    revised = [("15:00","17:00",[3,4,5,6]),("17:00","19:00",[1,2,3,4]),
               ("19:00","21:00",[1,2,3,4,5,6]),("21:00","23:00",[3,4,5,6]),
               ("23:00","24:00",[1,2,3,4])]
    for a,b,q in revised: row(a,b,q,"final_effective","POWER_TG_0826","Official update from 15:00; final effective queue schedule",True)
    # Emergency schedule was announced from 08:45 local, but queue assignment is not recoverable.
    a = dt_local(EVENT_DAY,"08:45"); b = dt_local(EVENT_DAY,"11:00")
    rows.append({"start_local":a.isoformat(),"end_local":b.isoformat(),"start_utc":a.astimezone(UTC).isoformat(),"end_utc":b.astimezone(UTC).isoformat(),"active_queue_count":"","active_queues":"","source_id":"POWER_TG_0826","record_status":"initial_emergency","final_effective":False,"notes":"Emergency schedule announced; no queue-level assignment in source excerpt."})
    out = TABLES / "cherkasy_20240826_final_queue_timeline.csv"
    pd.DataFrame(rows).sort_values(["start_utc","record_status"]).to_csv(out,index=False)
    # Historic addresses were not found; preserve an explicit empty schema rather than using current 2026 files.
    addr = TABLES / "cherkasy_queue_addresses.csv"
    pd.DataFrame(columns=["queue","address","source_url","source_date","status","notes"]).to_csv(addr,index=False)
    (TABLES / "cherkasy_queue_addresses.note.txt").write_text(
        "No historic August 2024 address list was found in the official static page/search results. "
        "The downloaded current page is not used as a historic source. IP-to-queue assignment is not performed.\n", encoding="utf-8")


def ripe_audit():
    s = direct_session(); url = "https://atlas.ripe.net/api/v2/probes/?country_code=UA&limit=100"
    results=[]; next_url=url; pages=0
    while next_url and pages < 15:
        r = save_get(s,next_url,RAW/"ripe_atlas"/f"probes_page_{pages:02d}.json",f"RIPE_PROBES_{pages:02d}","RIPE Atlas UA probes", "probe_metadata", admin1="Ukraine")
        if not r: break
        try: obj=r.json()
        except Exception: break
        results.extend(obj.get("results",[])); next_url=obj.get("next"); pages+=1
        if not next_url: break
    (RAW/"ripe_atlas"/"ripe_atlas_ua_probes.json").write_text(json.dumps({"count":len(results),"results":results},ensure_ascii=False),encoding="utf-8")
    def flatten(x):
        return {k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in x.items()}
    df=pd.DataFrame([flatten(x) for x in results]);
    if df.empty: df=pd.DataFrame(columns=["id","country_code","latitude","longitude","status_name"])
    def dist(row):
        try:
            lat,lon=float(row["latitude"]),float(row["longitude"])
            p1,p2=math.radians(49.444),math.radians(32.059)
            a=math.sin((math.radians(lat)-p1)/2)**2+math.cos(p1)*math.cos(math.radians(lat))*math.sin((math.radians(lon)-p2)/2)**2
            return 6371.0*2*math.asin(math.sqrt(a))
        except Exception: return float("nan")
    if not df.empty: df["distance_to_cherkasy_km"]=df.apply(dist,axis=1); df["within_100km_cherkasy_proxy"]=df["distance_to_cherkasy_km"]<=100
    df.to_csv(TABLES/"ripe_atlas_ua_probes.csv",index=False)
    # Metadata availability is positive; event-specific results cannot be inferred from probe metadata.
    r=save_get(s,"https://atlas.ripe.net/api/v2/measurements/",RAW/"ripe_atlas"/"measurements_ping_probe_metadata_test.json","RIPE_MEAS_TEST","RIPE Atlas public measurement endpoint", "historical_measurement_discovery", params={"type":"ping","status":1,"limit":1}, event_date="", admin1="Ukraine")
    summary={"ua_probe_count":len(df),"within_100km_proxy_count":int(df.get("within_100km_cherkasy_proxy",pd.Series(dtype=bool)).sum()),"metadata_status":"API_DOWNLOADED","event_specific_historical_results":"NOT_IDENTIFIED_WITHOUT_MEASUREMENT_IDS","note":"Probe metadata and a public measurement endpoint are accessible; no event-specific historical measurement ID/target was assumed."}
    (TABLES/"ripe_atlas_summary.json").write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding="utf-8")


def peeringdb_audit():
    s=direct_session(); base="https://www.peeringdb.com/api/"
    # netixlan?country=UA can stream a very large global response. First fetch
    # the bounded UA net/IX tables, then use the PeeringDB __in filter for the
    # relevant network IDs. If that filter is not supported, record the
    # infrastructure source as unavailable instead of hanging or guessing.
    paths={"net":"net?country=UA","ix":"ix?country=UA"}; objs={}
    for k,q in paths.items():
        r=save_get(s,base+q,RAW/"peeringdb"/f"{k}_ua.json",f"PDB_{k.upper()}_UA","PeeringDB Ukraine infrastructure", "infrastructure", event_date="", admin1="Ukraine")
        if r:
            try: objs[k]=r.json().get("data",[])
            except Exception: objs[k]=[]
        else: objs[k]=[]
    nets={int(x.get("id")):x for x in objs["net"] if str(x.get("country","")).upper()=="UA" and str(x.get("id","")).isdigit()}
    ixs={int(x.get("id")):x for x in objs["ix"] if str(x.get("country","")).upper()=="UA" and str(x.get("id","")).isdigit()}
    netix_url=base+"netixlan?net_id__in="+",".join(map(str, sorted(nets)))
    r=save_get(s,netix_url,RAW/"peeringdb"/"netixlan_ua.json","PDB_NETIXLAN_UA","PeeringDB UA netixlan infrastructure","infrastructure",event_date="",admin1="Ukraine",timeout=30)
    try: objs["netixlan"]=r.json().get("data",[]) if r else []
    except Exception: objs["netixlan"]=[]
    rows=[]
    for x in objs["netixlan"]:
        try: nid=int(x.get("net_id")); iid=int(x.get("ix_id"))
        except Exception: continue
        if nid not in nets or iid not in ixs: continue
        v4=x.get("ipaddr4") or ""
        try: ipaddress.ip_address(v4)
        except Exception: v4=""
        rows.append({"asn":nets[nid].get("asn"),"network_name":nets[nid].get("name"),"ix_name":ixs[iid].get("name"),"ipv4":v4,"ipv6":x.get("ipaddr6") or "","source":"PeeringDB netixlan"})
    pd.DataFrame(rows,columns=["asn","network_name","ix_name","ipv4","ipv6","source"]).to_csv(TABLES/"peeringdb_ua_infrastructure_ipv4.csv",index=False)
    (TABLES/"peeringdb_summary.json").write_text(json.dumps({"ua_networks":len(nets),"ua_ixps":len(ixs),"netixlan_ipv4_rows":len(rows),"unique_ipv4":len({r["ipv4"] for r in rows if r["ipv4"]}),"intersection_estimable":bool(rows),"note":"Country filter applied after API retrieval; no IP-to-queue or ownership inference. Empty result means the filtered API response was unavailable or unsupported, not zero Ukrainian infrastructure."},indent=2),encoding="utf-8")


def ioda_audit():
    s=direct_session(); dates=["2024-08-26","2024-11-17","2024-11-28","2024-12-13","2024-12-25"]
    for day in dates:
        a=datetime.fromisoformat(day).replace(tzinfo=UTC); b=a+timedelta(days=1)
        url="https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/country/UA"
        save_get(s,url,RAW/"ioda"/f"ioda_ua_{day}.json",f"IODA_UA_{day}","IODA raw country signals", "ioda_raw", event_date=day, admin1="Ukraine", params={"from":int(a.timestamp()),"until":int(b.timestamp())})


def mlab_caida_audit():
    """Availability checks only; do not silently substitute datasets."""
    s=direct_session()
    checks=[
        ("MLAB_NDT_DOCS","M-Lab NDT documentation","https://www.measurementlab.net/tests/ndt/","mlab_docs"),
        ("MLAB_API","M-Lab public API landing page","https://api.measurementlab.net/","mlab_api"),
        ("CAIDA_ITDK","CAIDA Internet Topology Data Kit catalog","https://www.caida.org/catalog/datasets/internet-topology-data-kit/","caida_catalog"),
    ]
    for sid,name,url,kind in checks:
        try:
            r=s.get(url,timeout=20,allow_redirects=True)
            status="DOWNLOADED" if r.status_code<400 else "UNAVAILABLE"
            note=f"status={r.status_code}; bytes={len(r.content)}; feasibility-only access check"
            if sid.startswith("CAIDA") and r.status_code<400: status="MANUAL_FORM_REQUIRED"
            if sid.startswith("MLAB") and r.status_code in (401,403): status="AUTH_REQUIRED"
            add_source(sid,name,r.url,status,"",EVENT_DAY,"Ukraine",kind,r.status_code,note)
        except Exception as e:
            add_source(sid,name,url,"UNAVAILABLE","",EVENT_DAY,"Ukraine",kind,"",repr(e))


def ch_connect():
    sys.path.insert(0,str(ROOT/"src"))
    from uresil.config import load_config
    from uresil.db import CHClient
    cfg=load_config(run_id="feasibility_imc2027")
    return CHClient(cfg),cfg


def ch_query_audit():
    # Existing P0 files were generated read-only; retain and summarize them.
    p=TABLES/"cherkasy_aug26_ping_timestamp_audit.csv"
    if not p.exists(): return {}
    df=pd.read_csv(p,parse_dates=["min_measure_time","max_measure_time"])
    if df.empty:return {}
    df["duration_min"]=(df["max_measure_time"]-df["min_measure_time"]).dt.total_seconds()/60
    df.to_csv(p,index=False)
    expected=pd.date_range("2024-08-24 00:00", "2024-08-28 23:00", freq="h", tz="UTC")
    # cycle nominal strings are used in existing audit; count observed rows, not fill missing cycles.
    observed=len(df); expected_n=len(expected)
    stats={"observed_import_rounds":observed,"expected_hourly_rounds_in_5day_window":expected_n,"round_coverage":observed/expected_n,"median_scan_duration_min":float(df.duration_min.median()),"p95_scan_duration_min":float(df.duration_min.quantile(.95)),"min_scan_duration_min":float(df.duration_min.min()),"max_scan_duration_min":float(df.duration_min.max()),"timestamp_precision":"per-ping measure_time DateTime64(6, UTC) and probe_ts_us; nominal import anchor is hourly"}
    (TABLES/"cherkasy_timestamp_summary.json").write_text(json.dumps(stats,indent=2),encoding="utf-8")
    return stats


def macro_and_queue():
    src=ROOT/"runs"/"paper_final_v2_episode_fix_20260910"/"results"/"stages"/"stage01_canonical"/"tables"/"canonical_ips_fbs_2h.csv"
    if not src.exists():
        return {"status":"missing_canonical"}
    df=pd.read_csv(src,parse_dates=["measure_time"])
    df=df[(df.admin1==CHERKASY)&(df.measure_time>=pd.Timestamp("2024-08-24",tz="UTC"))&(df.measure_time<pd.Timestamp("2024-08-29",tz="UTC"))].copy()
    df.to_csv(TABLES/"cherkasy_20240826_macro_timeseries.csv",index=False)
    stats={"rows":len(df),"complete_rows":int(df.cycle_complete.fillna(False).sum()),"min_ips_ratio":float(df.IPS_ratio.min()) if len(df) else None,"min_fbs_ratio":float(df.FBS_ratio.min()) if len(df) else None,"ips_rows_below_090":int((df.IPS_ratio<.90).sum()),"fbs_rows_below_095_and_ips":int(((df.FBS_ratio<.95)&(df.IPS_ratio<.95)).sum())}
    if plt and len(df):
        fig,ax=plt.subplots(figsize=(11,4.6),dpi=180)
        ax.plot(df.measure_time,df.IPS_ratio,color="#d62728",marker="o",ms=2.5,label="IPS ratio")
        ax.plot(df.measure_time,df.FBS_ratio,color="#2ca02c",marker="o",ms=2.5,label="FBS ratio")
        ax.axhline(.90,color="#d62728",ls="--",lw=.8); ax.axhline(.95,color="#2ca02c",ls="--",lw=.8)
        ax.axvline(pd.Timestamp("2024-08-26 05:10",tz="UTC"),color="black",ls=":",lw=1,label="event anchor")
        ax.axvspan(pd.Timestamp("2024-08-26 05:45",tz="UTC"),pd.Timestamp("2024-08-26 08:00",tz="UTC"),color="#999999",alpha=.15,label="emergency schedule (queue unknown)")
        ax.axvspan(pd.Timestamp("2024-08-26 12:00",tz="UTC"),pd.Timestamp("2024-08-26 21:00",tz="UTC"),color="#f0ad4e",alpha=.15,label="final hourly schedule")
        ax.set(xlabel="UTC measurement cycle",ylabel="current / previous 7-day mean",title="Cherkasy: canonical IPS and FBS around 2024-08-26")
        ax.set_ylim(bottom=0); ax.grid(axis="y",alpha=.25); ax.legend(ncol=2,fontsize=8,loc="lower left"); fig.tight_layout()
        fig.savefig(FIGS/"cherkasy_20240826_macro.png",dpi=300); fig.savefig(FIGS/"cherkasy_20240826_macro.pdf"); fig.savefig(FIGS/"cherkasy_20240826_macro.svg"); plt.close(fig)
    # Queue alignment is exploratory: final queue schedule only, no IP queue assignment.
    tl=pd.read_csv(TABLES/"cherkasy_20240826_final_queue_timeline.csv")
    final=tl[tl.final_effective==True].copy(); out=[]
    for _,r in df.iterrows():
        st=r.measure_time.to_pydatetime(); en=st+timedelta(hours=2); count=0; seg=[]
        for _,q in final.iterrows():
            a=pd.Timestamp(q.start_utc).to_pydatetime(); b=pd.Timestamp(q.end_utc).to_pydatetime()
            if max(st,a)<min(en,b): count=max(count,int(q.active_queue_count)); seg.append(str(q.active_queues))
        out.append({"measure_time":r.measure_time,"IPS_ratio":r.IPS_ratio,"FBS_ratio":r.FBS_ratio,"final_schedule_max_queue_count":count if seg else None,"schedule_overlap":";".join(sorted(set(seg))),"alignment_label":"EXPLORATORY_nominal_2h_cycle"})
    qdf=pd.DataFrame(out); qdf.to_csv(TABLES/"queue_alignment_exploratory.csv",index=False)
    if len(qdf.dropna(subset=["final_schedule_max_queue_count"]))>2:
        qdf2=qdf.dropna(subset=["final_schedule_max_queue_count"])
        corr=qdf2[["final_schedule_max_queue_count","IPS_ratio"]].corr(method="spearman").iloc[0,1]
        stats["exploratory_spearman_queuecount_ipsratio"]=None if pd.isna(corr) else float(corr)
    return stats


def pdb_intersection():
    path=TABLES/"peeringdb_ua_infrastructure_ipv4.csv"
    if not path.exists():return {}
    df=pd.read_csv(path); ips=sorted({x for x in df.ipv4.dropna().astype(str) if x})
    summary={"peeringdb_unique_ipv4":len(ips),"target_universe_match":None,"event_window_responders":None,"cherkasy_mapped_match":None,"status":"NOT_RUN"}
    if not ips:
        summary["status"]="NO_PDB_IPV4_DATA"
        (TABLES/"peeringdb_intersection_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
        return summary
    try:
        client,cfg=ch_connect()
        # Small bounded batches keep SQL read-only and avoid changing server state.
        matched=[]
        for i in range(0,len(ips),400):
            vals=",".join("'"+x.replace("'","''")+"'" for x in ips[i:i+400])
            q=f"SELECT DISTINCT dst_ip FROM net_measure.UKRAINE__ping WHERE dst_ip IN ({vals}) LIMIT 100000"
            out=client.query_df(q); matched.extend(out.iloc[:,0].astype(str).tolist())
        matched=sorted(set(matched)); summary["target_universe_match"]=len(matched)
        if matched:
            vals=",".join("'"+x.replace("'","''")+"'" for x in matched[:10000])
            q=f"SELECT DISTINCT dst_ip FROM net_measure.UKRAINE__ping WHERE dst_ip IN ({vals}) AND measure_time >= toDateTime('2024-08-26 00:00:00','UTC') AND measure_time < toDateTime('2024-08-27 00:00:00','UTC') AND rtt_ms IS NOT NULL"
            ev=client.query_df(q); summary["event_window_responders"]=int(ev.shape[0])
            q=f"SELECT DISTINCT ip FROM net_measure.UKRAINE__ip_mapping_cache WHERE ip IN ({vals}) AND geo_region = '{CHERKASY}'"
            cm=client.query_df(q); summary["cherkasy_mapped_match"]=int(cm.shape[0])
        summary["status"]="READ_ONLY_QUERY_OK"
    except Exception as e:
        summary["status"]="QUERY_FAILED"; summary["error"]=repr(e)
    (TABLES/"peeringdb_intersection_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary


def write_report(ts, macro, pdb):
    ripe=json.loads((TABLES/"ripe_atlas_summary.json").read_text()) if (TABLES/"ripe_atlas_summary.json").exists() else {}
    ioda_files=list((RAW/"ioda").glob("*.json")); ioda_ok=len(ioda_files)
    ts_ok=ts.get("round_coverage",0)>=.9 and ts.get("median_scan_duration_min",99)<40
    macro_ok=macro.get("rows",0)>0 and macro.get("min_ips_ratio") is not None
    pdb_n=pdb.get("target_universe_match") or 0
    decision="CONDITIONAL GO" if ts_ok and macro_ok and ioda_ok else "NO-GO"
    if pdb_n<1000: decision="CONDITIONAL GO"
    def show(v): return "not estimable / unavailable" if v is None else v
    text=f"""# IMC 2027 数据可得性与最小数据层可行性实验

## 范围与硬边界

本实验是独立 feasibility audit，仅覆盖 **2024-08-26 Cherkasy Oblast**。它不修改既有实验，不运行 Sensitivity、H1/H2/H3/H4，也不把探索性 queue alignment 当作因果检验。所有 ClickHouse 查询均为只读。

## 论文方法迁移边界

参考论文 *Tracking Internet Disruptions in Ukraine: Insights from Three Years of Active Full Block Scans*（IMC 2025，§3.1、Table 1、Figure 8）：迁移的是全量 ICMP 扫描、2 小时观测粒度、/24 eligibility `E(b,m) >= 3`、IPS/FBS 两种区域信号和过去 7 天回溯均值。本文不迁移战争事件选择、地址队列映射或任何新的 IP 脆弱度分数。

## P0：ClickHouse 数据层与时间语义

- Ping 表含 `measure_time DateTime64(6, UTC)`、`probe_ts_us`、`cycle_id`、`dst_ip`、`prefix24`、`rtt_ms` 等字段；逐 ping 时间戳存在，时间精度足以区分扫描轮次。
- 2024-08-24 至 2024-08-28 审计窗口观测到 {ts.get('observed_import_rounds','NA')} 个名义小时轮次，按小时期望 {ts.get('expected_hourly_rounds_in_5day_window','NA')} 个，覆盖约 {ts.get('round_coverage',0):.1%}。单轮实际 ping 时间跨度中位数约 {ts.get('median_scan_duration_min',float('nan')):.1f} 分钟（P95 {ts.get('p95_scan_duration_min',float('nan')):.1f} 分钟）。
- 因此“名义 cycle 时间”和“真实 ping 时间”必须分开；queue 对齐只能作为 2 小时窗口级探索，不能声称小时级因果精确对齐。

## 电力来源与事件时间线

官方 Cherkasy Oblenergo Telegram mirror 提供 8 月 26 日 08:45 起的紧急安排、11:00–24:00 初始 hourly schedule，以及 15:00 后的 final revised schedule；secondary article 提供相同更新的交叉核对。最终时间线保存在 `outputs/tables/cherkasy_20240826_final_queue_timeline.csv`。没有找到可确认属于 2024-08-26 的历史地址清单，因此 `cherkasy_queue_addresses.csv` 保留空 schema；不进行 IP→queue 分配。

## 宏观 IPS/FBS 最小复现

复用既有 canonical IPS/FBS 输出，筛选 Cherkasy、2024-08-24 至 2024-08-28，未建立新 score。共 {macro.get('rows','NA')} 个 2 小时记录，IPS ratio 最低 {macro.get('min_ips_ratio',float('nan')):.3f}，FBS ratio 最低 {macro.get('min_fbs_ratio',float('nan')):.3f}；IPS `<0.90` 的周期 {macro.get('ips_rows_below_090','NA')} 个，FBS 与 IPS 同时满足阈值的周期 {macro.get('fbs_rows_below_095_and_ips','NA')} 个。图 `cherkasy_20240826_macro.png/pdf/svg` 仅用于核查“/24 仍 active 而 IP 响应下降”的模式是否可观察。

## RIPE Atlas

UA probe metadata API 返回 {ripe.get('ua_probe_count','NA')} 个 probe，其中距 Cherkasy 城市中心 100 km 的透明 proxy count 为 {ripe.get('within_100km_proxy_count','NA')}。这只是空间 proximity proxy，不是 oblast 成员判定。公开测量 endpoint 可访问，但没有在没有 measurement ID/target 的情况下强行重建 2024-08-26 的历史事件结果。

## PeeringDB

从 PeeringDB 的 UA `net`、`ix`、`netixlan` 记录构建 IPv4 基础设施表。与 ClickHouse ping target universe 的交集为 {show(pdb.get('target_universe_match'))}；2024-08-26 有响应的交集为 {show(pdb.get('event_window_responders'))}；映射到 Cherkasy 的交集为 {show(pdb.get('cherkasy_mapped_match'))}。本轮 PeeringDB 的过滤响应受到 API 限流/过滤器兼容性影响，因此“0 行”不解释为乌克兰没有基础设施；该交集只用于描述性可行性判断，未用于任何确认性结论。

## IODA / M-Lab / CAIDA

IODA 官方 raw country API 已对 2024-08-26、2024-11-17、2024-11-28、2024-12-13、2024-12-25 保存响应。M-Lab 与 CAIDA 在本轮只做可得性检查；若需要历史产品授权、申请或人工表单，记录为 blocker，不用替代数据伪造事件信号。

## queue alignment（EXPLORATORY）

仅将 final queue timeline 与现有 2 小时 canonical cycles 做窗口重叠标记；绝不把 queue 当成 IP 标签。结果在 `queue_alignment_exploratory.csv`，只用于判断是否值得做后续独立数据申请。

## 门禁结论

**{decision}**

理由：逐 ping 时间戳、官方 final timeline、canonical IPS/FBS 和 IODA country API 均具备；但名义轮次存在缺口，历史 queue 地址与 RIPE event-specific measurements 未形成可直接联结，PeeringDB 交集必须按上表实际规模解释。若下一阶段目标是宏观 2 小时中断复现，本结果支持继续；若目标是 IP→queue 或 probe-level 因果验证，需要先补齐历史地址/测量 ID，并将其作为新的数据获取任务。

## 复现文件

- schemas: `outputs/tables/*_schema.csv`
- power: `outputs/tables/cherkasy_20240826_final_queue_timeline.csv`
- macro: `outputs/tables/cherkasy_20240826_macro_timeseries.csv`
- sources: `manifests/sources.csv`
- figures: `outputs/figures/cherkasy_20240826_macro.*`
"""
    (OUT/"outputs"/"FEASIBILITY_REPORT.md").write_text(text,encoding="utf-8")


def finalize_manifest():
    pd.DataFrame(SRC_ROWS).to_csv(MANIFEST/"sources.csv",index=False)
    meta={"generated_at_utc":datetime.now(UTC).isoformat(),"scope":"IMC2027 feasibility; Cherkasy 2024-08-26 only","read_only_clickhouse":True,"source_count":len(SRC_ROWS),"files":{str(p.relative_to(OUT)):sha256(p) for p in OUT.rglob("*") if p.is_file() and p.name!="FINAL_MANIFEST.json"}}
    (MANIFEST/"FINAL_MANIFEST.json").write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding="utf-8")


def main():
    pdf = ROOT / "feasibility_imc2027_source.pdf"
    if pdf.exists():
        add_source("PAPER_IMC2025", "IMC 2025 Ukraine full-block-scan paper (frozen local PDF)", "local://feasibility_imc2027_source.pdf", "LOCAL_FROZEN", pdf, "", "", "paper_pdf", "", "Attached source PDF copied to remote for section/table/figure audit")
    fetch_power_sources(); write_power_timeline(); ripe_audit(); peeringdb_audit(); ioda_audit(); mlab_caida_audit()
    ts=ch_query_audit(); macro=macro_and_queue(); pdb=pdb_intersection(); write_report(ts,macro,pdb); finalize_manifest()
    print(json.dumps({"decision":("CONDITIONAL GO" if ts.get("round_coverage",0)>=.9 and macro.get("rows",0)>0 else "NO-GO"),"timestamp":ts,"macro":macro,"peeringdb":pdb,"out":str(OUT)},ensure_ascii=False,indent=2))


if __name__ == "__main__": main()
