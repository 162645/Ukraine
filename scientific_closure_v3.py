#!/usr/bin/env python3
"""Scientific-boundary closure for the power/infrastructure feasibility study.

This stage is deliberately conservative.  It consumes frozen registries and the
already published v1/v2 artifacts, and never treats an event-level numerator as
a probe-level cycle panel.  Missing raw per-IP cycles are reported as
NOT_GENERATED rather than filled with zeros or reconstructed from counts.
"""
from __future__ import annotations

import argparse, hashlib, json, subprocess
from pathlib import Path
import numpy as np
import pandas as pd

START = pd.Timestamp("2024-06-01", tz="UTC")
END = pd.Timestamp("2025-01-31 23:59:59", tz="UTC")

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def setup(out: Path) -> None:
    for d in ["methods", "data", "tables", "figures/zh", "figures/en", "logs", "outputs"]:
        (out / d).mkdir(parents=True, exist_ok=True)

def safe_dt(x):
    return pd.to_datetime(x, utc=True, errors="coerce")

def source_copy(root: Path, out: Path, rel: str) -> str:
    p = root / rel
    return sha256(p) if p.exists() else "MISSING"

def boundary_audit(out: Path) -> None:
    items = [
        ("State-level schedule is not feeder-level actual outage", "partial", "Keep exposure as scheduled state-level proxy; no IP-level causal wording."),
        ("Rolling outages can misclassify exposure", "partial", "Retain native schedule semantics; discuss non-differential and differential misclassification."),
        ("War can directly interrupt networks", "partial", "Partition verified war windows separately; no power-specific interpretation."),
        ("War can damage power facilities indirectly", "partial", "Use OVERLAP and native mechanism; do not attribute it to Power_ONLY."),
        ("Power and War windows can overlap", "controlled", "Set-theoretic CLEAN/POWER_ONLY/WAR_ONLY/OVERLAP labels only."),
        ("IP is not a physical device", "uncontrolled", "Use endpoint wording and avoid device-level claims."),
        ("DHCP/address churn", "uncontrolled", "Interpret IP as an observation endpoint, not persistent subscriber/device."),
        ("ICMP non-response is not physical offline", "uncontrolled", "Availability is measurement response probability only."),
        ("ITDK T=0 is not confirmed non-infrastructure", "controlled", "Report as no observed ITDK transit evidence."),
        ("ITDK topology observation bias", "uncontrolled", "Call outcome observed ITDK transit evidence and report release robustness."),
        ("ASN composition confounds associations", "partial", "Use ASN-stratified model when estimable; report non-informative strata."),
        ("IPs within a /24 are correlated", "controlled", "Use /24 cluster bootstrap and /24 clustered models."),
        ("Repeated observations within IP are correlated", "partial", "Raw per-cycle panel is required; unavailable artifacts block probe-level inference."),
        ("IPs share event shocks", "partial", "Event/state decomposition is descriptive; do not treat IPs as independent events."),
        ("Measurement gaps", "controlled", "Use cycle-quality registry and never convert absent rows to response=0."),
        ("Vantage outage", "partial", "Use complete-cycle flags; no additional outage correction is invented."),
        ("Unequal valid probe counts", "controlled", "Store responsive and valid counts separately; no minimum threshold is imposed."),
        ("Different event time precision", "controlled", "Retain native precision; coarse date-only events are not assigned to cycles."),
        ("Unequal state event coverage", "controlled", "Report coverage by state and avoid unsupported pooled causal claims."),
        ("Frontline warfare and power outage may coexist", "controlled", "Preserve native mechanism and OVERLAP state."),
        ("Availability series and power observations overlap in time", "controlled", "CLEAN is the intended independent background; overall is descriptive only."),
        ("AUC populations may differ", "controlled", "Incremental AUC uses pairwise common-support populations only."),
        ("ITDK labels are sparse", "controlled", "Report prevalence and uncertainty; do not impose a hand-made cutoff."),
        ("Association is not causation", "uncontrolled", "All conclusions use association/observed evidence language."),
    ]
    lines = ["# SCIENTIFIC BOUNDARY AUDIT (v3)", "", "This audit is a scope contract, not a causal claim.", "", "| Issue | Control status | Treatment / limitation |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a,b,c in items]
    lines += ["", "The frozen artifacts do not contain raw per-IP probe outcomes for every cycle. Any analysis requiring that panel is therefore explicitly NOT_GENERATED."]
    (out / "methods/SCIENTIFIC_BOUNDARY_AUDIT.md").write_text("\n".join(lines), encoding="utf-8")

def provenance(out: Path) -> None:
    text = """# METHOD PROVENANCE V3

| Method | Source | Original use | This stage | Applied as-is? |
|---|---|---|---|---|
| Host availability | Bhagwan, Savage & Voelker, *Understanding Availability*, 2003, USENIX; https://www.usenix.org/legacy/publications/library/proceedings/usits03/tech/full_papers/bhagwan/bhagwan_html/ | Response/valid-probe fraction | Availability definitions | Yes, where probe counts exist |
| GEE | Liang & Zeger, 1986, *Biometrika*, doi:10.1093/biomet/73.1.13 | Correlated binary outcomes | Interaction only if raw panel is estimable | Not generated here |
| Conditional logistic regression | Breslow & Day, 1980, *Statistical Methods in Cancer Research* | Stratified binary association | ASN-stratified association | Not generated here because required exposure panel is absent |
| ROC-AUC | DeLong, DeLong & Clarke-Pearson, 1988, *Biometrics*, doi:10.2307/2531595 | Correlated ROC comparison | Common-support AUC | Not generated here without clean/power/war panel |
| Precision–Recall / Average Precision | Saito & Rehmsmeier, 2015, *PLOS ONE*, doi:10.1371/journal.pone.0118432 | Imbalanced binary discrimination | Common-support PR | Not generated here without common-support panel |
| Binscatter | Cattaneo et al., 2024, *The Stata Journal*, doi:10.1177/1536867X241243339 | Nonparametric binned relationship | Only with documented binsreg implementation | Not generated here |
| Time-stratified case-crossover | Janes, Sheppard & Lumley, 2005, *Epidemiology*, doi:10.1097/01.ede.0000187170.10481.15 | Short-term exposure/control pairing | Only if raw paired cycles can be reread | Not generated here |

No new score, composite index, threshold, or causal estimand is introduced.
"""
    (out / "methods/METHOD_PROVENANCE_V3.md").write_text(text, encoding="utf-8")

def parse_states(x):
    if pd.isna(x) or not str(x).strip(): return []
    return [s.strip() for s in str(x).replace(";", "|").split("|") if s.strip()]

def build_taxonomy(root: Path, out: Path):
    rows = []
    p = root / "config/outage_exposure_registry_v2.csv"
    if p.exists():
        d = pd.read_csv(p)
        for _, r in d.iterrows():
            rows.append({"event_id": r.get("exposure_id"), "oblast": r.get("affected_admin1"), "start_time": r.get("start_utc"), "end_time": r.get("end_utc"), "time_precision": "interval" if pd.notna(r.get("start_utc")) and pd.notna(r.get("end_utc")) else "unknown", "native_event_type": r.get("exposure_type"), "native_mechanism": r.get("exposure_type"), "source": r.get("source_ids"), "verification_status": "frozen_registry", "is_power_event": 1, "is_war_event": 0, "power_event_ids": r.get("exposure_id"), "war_event_ids": ""})
    p = root / "config/key_events_v3_0.csv"
    if p.exists():
        d = pd.read_csv(p)
        for _, r in d.iterrows():
            # Date-only rows remain event-level context; no artificial 00:00–23:59 interval is made.
            rows.append({"event_id": r.get("event_id"), "oblast": r.get("affected_admin1"), "start_time": r.get("event_start_local"), "end_time": r.get("event_end_local"), "time_precision": r.get("time_precision"), "native_event_type": r.get("event_class_norm", r.get("event_class")), "native_mechanism": r.get("direct_power_effect"), "source": r.get("source_url"), "verification_status": "frozen_registry", "is_power_event": 0, "is_war_event": int(str(r.get("event_class_norm", "")).lower() == "attack"), "power_event_ids": "", "war_event_ids": r.get("event_id")})
    tax = pd.DataFrame(rows)
    tax.to_csv(out / "data/EVENT_TAXONOMY_AUDIT.csv", index=False)
    return tax

def exposure_cycles(root: Path, out: Path, tax: pd.DataFrame):
    cq = pd.read_parquet(root / "runs/doc_complete_20260908/data_derived/cycle_quality.parquet")
    cq["timestamp"] = safe_dt(cq["measure_time"])
    cq = cq[(cq.timestamp >= START) & (cq.timestamp <= END)].copy()
    # Only interval-precision registry entries can label a cycle. Date-only events are retained in taxonomy but not expanded.
    power = []
    for _, r in tax[(tax.is_power_event == 1) & tax.start_time.notna() & tax.end_time.notna()].iterrows():
        a,b=safe_dt(r.start_time),safe_dt(r.end_time)
        if pd.notna(a) and pd.notna(b): power.append((a,b,str(r.event_id),str(r.oblast)))
    war = []
    for _, r in tax[(tax.is_war_event == 1) & tax.start_time.notna() & tax.end_time.notna()].iterrows():
        a,b=safe_dt(r.start_time),safe_dt(r.end_time)
        if pd.notna(a) and pd.notna(b): war.append((a,b,str(r.event_id),str(r.oblast)))
    def hit(t, item):
        a,b,_,states=item
        # National/all applies to all; otherwise state granularity cannot be applied to cycle quality alone.
        return bool(a <= t < b)
    labels=[]
    for _,r in cq.iterrows():
        t=r.timestamp
        hp=[x for x in power if hit(t,x)]
        hw=[x for x in war if hit(t,x)]
        hs = "OVERLAP" if hp and hw else ("POWER_ONLY" if hp else ("WAR_ONLY" if hw else "CLEAN"))
        labels.append({"cycle_id":r.cycle_id,"timestamp":t,"measurement_complete":bool(r.get("is_complete",False)),"has_power_event":int(bool(hp)),"has_war_event":int(bool(hw)),"period_state":hs,"power_event_id":"|".join(x[2] for x in hp),"war_event_id":"|".join(x[2] for x in hw),"native_war_mechanism":"|".join(str(tax.loc[tax.event_id.eq(x[2]),'native_mechanism'].iloc[0]) for x in hw) if hw else ""})
    long=pd.DataFrame(labels)
    long.to_csv(out / "tables/cycle_exposure_state_registry.csv", index=False)
    long.groupby("period_state").agg(cycle_n=("cycle_id","nunique"),complete_cycle_n=("measurement_complete","sum")).reset_index().to_csv(out / "tables/exposure_state_cycle_coverage.csv", index=False)
    return long

def availability_stub(root: Path, out: Path):
    m=pd.read_parquet(root/"power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet")
    # Keep the published event-level power aggregate as an explicitly named legacy diagnostic.
    cols=["ip","prefix24","oblast","asn"]
    z=m[cols].copy()
    z["overall_responsive"]=np.nan; z["overall_valid"]=np.nan; z["overall_availability"]=np.nan
    z["clean_responsive"]=np.nan; z["clean_valid"]=np.nan; z["clean_background_availability"]=np.nan
    z["power_responsive"]=m["power_responsive_count"]; z["power_valid"]=m["power_valid_probe_observed"]; z["power_only_availability"]=m["power_availability"]
    for p in ["war","overlap"]:
        z[f"{p}_responsive"]=np.nan; z[f"{p}_valid"]=np.nan; z[f"{p}_availability"]=np.nan
    z["number_of_power_events_observed"]=m["number_of_power_events_observed"]; z["number_of_war_events_observed"]=np.nan
    for c in ["itdk_202402_T","itdk_202408_T","itdk_202503_T","itdk_202408_router","own_traceroute_intermediate"]: z[c]=m[c]
    z.to_parquet(out/"data/ip_availability_by_exposure_state.parquet",index=False,compression="zstd")
    pd.DataFrame([{"artifact":"ip_cycle_exposure_long.parquet","status":"NOT_GENERATED: raw per-IP per-cycle outcomes unavailable; no zero fill"},{"artifact":"power/war paired outcome","status":"NOT_GENERATED: v2 cache contains event-level counts, not raw timestamps"}]).to_csv(out/"tables/NOT_GENERATED_DATASETS.csv",index=False)
    return z

def make_figures(out: Path, tax: pd.DataFrame, cycles: pd.DataFrame):
    import matplotlib; matplotlib.use("Agg")
    # The server image includes WenQuanYi; without an explicit CJK font the
    # Chinese artifact silently renders as tofu while the English artifact is
    # fine.  Keep the language split visible and reproducible.
    matplotlib.rcParams["font.sans-serif"] = ["WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt
    # Figure 31: verified interval events only; date-only records are plotted as points at their date for context.
    ev=tax.copy(); ev["plot_time"]=safe_dt(ev.start_time)
    ev.loc[ev.plot_time.isna(),"plot_time"]=pd.to_datetime(ev.loc[ev.plot_time.isna(),"event_id"].str.extract(r"(20\d{6})")[0],format="%Y%m%d",errors="coerce").dt.tz_localize("UTC")
    ev=ev[ev.plot_time.notna()]
    # The registry keeps free-text affected-scope descriptions.  For the
    # Oblast axis, retain only canonical administrative labels; do not turn
    # phrases such as “especially Odesa” into fake oblast observations.
    canonical=["Cherkasy Oblast","Chernihiv Oblast","Chernivtsi Oblast","Dnipropetrovsk Oblast","Donetsk Oblast","Ivano-Frankivsk Oblast","Kharkiv Oblast","Kherson Oblast","Khmelnytskyi Oblast","Kyiv Oblast","Kyiv City","Kirovohrad Oblast","Luhansk Oblast","Lviv Oblast","Mykolaiv Oblast","Odesa Oblast","Poltava Oblast","Rivne Oblast","Sumy Oblast","Ternopil Oblast","Vinnytsia Oblast","Volyn Oblast","Zakarpattia Oblast","Zaporizhzhia Oblast","Zhytomyr Oblast","ALL"]
    ev["plot_states"] = ev.oblast.map(lambda x: [s for s in canonical if s in str(x)] or (["ALL"] if any(k in str(x).lower() for k in ["national","15 regions","multiple regions"]) else []))
    ev=ev[ev.plot_states.map(bool)]
    states=sorted(set(s for xs in ev.plot_states for s in xs))
    if not states: states=["ALL"]
    y={s:i for i,s in enumerate(states)}
    zh_names={"Cherkasy Oblast":"切尔卡瑟州","Chernihiv Oblast":"切尔尼戈夫州","Chernivtsi Oblast":"切尔诺夫策州","Dnipropetrovsk Oblast":"第聂伯罗彼得罗夫斯克州","Donetsk Oblast":"顿涅茨克州","Ivano-Frankivsk Oblast":"伊万诺-弗兰科夫斯克州","Kharkiv Oblast":"哈尔科夫州","Kherson Oblast":"赫尔松州","Khmelnytskyi Oblast":"赫梅利尼茨基州","Kyiv Oblast":"基辅州","Kyiv City":"基辅市","Kirovohrad Oblast":"基洛沃格勒州","Luhansk Oblast":"卢甘斯克州","Lviv Oblast":"利沃夫州","Mykolaiv Oblast":"尼古拉耶夫州","Odesa Oblast":"敖德萨州","Poltava Oblast":"波尔塔瓦州","Rivne Oblast":"罗夫诺州","Sumy Oblast":"苏梅州","Ternopil Oblast":"捷尔诺波尔州","Vinnytsia Oblast":"文尼察州","Volyn Oblast":"沃伦州","Zakarpattia Oblast":"外喀尔巴阡州","Zaporizhzhia Oblast":"扎波罗热州","Zhytomyr Oblast":"日托米尔州","ALL":"全乌克兰"}
    for lang in ["zh","en"]:
        fig,ax=plt.subplots(figsize=(13,7))
        for _,r in ev.iterrows():
            ss=r.plot_states
            for s in ss:
                ax.scatter(r.plot_time,y.get(s,0),marker="o" if r.is_power_event else "x",c="#2ca02c" if r.is_power_event else "#d62728",s=22,alpha=.65)
        ax.set_xlim(START,END); ax.set_yticks(list(y.values())); ax.set_yticklabels(states,fontsize=7)
        if lang=="zh": ax.set_yticklabels([zh_names.get(s,s) for s in states],fontsize=7); ax.set_title("电力与战争事件的完整时间分布"); ax.set_xlabel("日期（UTC）"); ax.set_ylabel("州（Oblast）")
        else: ax.set_title("Timeline of Verified Power and War-Related Events"); ax.set_xlabel("Date (UTC)"); ax.set_ylabel("Oblast")
        ax.grid(axis="x",alpha=.2); fig.tight_layout()
        for ext,kw in [("png",{"dpi":300}),("pdf",{}),("svg",{})]: fig.savefig(out/f"figures/{lang}/figure31_event_timeline.{ext}",bbox_inches="tight",**kw)
        plt.close(fig)
    # Figure 32 is intentionally not drawn: cycle coverage is not valid IP×cycle coverage.
    (out/"outputs/NOT_GENERATED.md").write_text("""# NOT GENERATED\n\n- Figure 32–42: not generated because the available frozen artifacts do not contain raw per-IP per-cycle outcomes for CLEAN/POWER_ONLY/WAR_ONLY/OVERLAP.\n- No date-only war event was expanded to a full-day interval.\n- No AUC/PR difference, GEE interaction, ASN-stratified coefficient, or case-crossover result was fabricated.\n- The v2 event-level power aggregate remains in the derived table only as a legacy diagnostic, not as a clean/power/war cycle panel.\n""",encoding="utf-8")

def reports(root: Path, out: Path, tax, cycles, z):
    states=cycles.groupby("period_state").agg(cycle_n=("cycle_id","nunique"),complete_cycle_n=("measurement_complete","sum")).reset_index()
    states.to_csv(out/"tables/TABLE_V3_EXPOSURE_STATE_COVERAGE.csv",index=False)
    # native mechanism × event descriptive registry
    tax[["event_id","native_mechanism","oblast","start_time","end_time","time_precision","verification_status","is_power_event","is_war_event"]].to_csv(out/"tables/TABLE_V3_EVENT_MECHANISM.csv",index=False)
    (out/"outputs/PAPER_CLOSURE_SUMMARY_ZH.md").write_text("""# v3 科学闭环阶段\n\n本阶段先修复研究边界和事件集合定义。现有冻结产物可以可靠地保留计划停电事件级汇总和事件注册表，但服务器当前没有可重新读取的逐 IP×2 小时原始响应面板；因此不能把 v2 的事件级计数伪装成 CLEAN/POWER_ONLY/WAR_ONLY/OVERLAP 的逐周期可达率。\n\n已生成事件分类、周期集合标签和边界/方法审计。CLEAN、POWER_ONLY、WAR_ONLY、OVERLAP 的 IP 可达率表、common-support ROC/PR、GEE 交互、ASN 条件模型和 case-crossover 均明确标记为 NOT_GENERATED。\n\n这不是负结果，而是数据可估计边界：在恢复原始 per-IP per-cycle outcome 之前，不应报告 Power 或 War 相对于背景的增量关联，更不能做因果解释。\n""",encoding="utf-8")
    (out/"outputs/PAPER_CLOSURE_SUMMARY_EN.md").write_text("""# Scientific closure v3\n\nThis stage repairs the scientific boundary and event-set definition. The frozen artifacts preserve event-level scheduled-power summaries and verified registries, but the server does not currently expose a rereadable raw IP-by-2-hour response panel. The v2 event counts therefore cannot be relabeled as CLEAN/POWER_ONLY/WAR_ONLY/OVERLAP availability.\n\nEvent taxonomy, cycle set labels, and method/boundary audits are generated. IP availability by exposure state, common-support ROC/PR, GEE interaction, ASN-stratified coefficients, and case-crossover estimates are explicitly NOT_GENERATED.\n\nThis is an estimability boundary, not a null finding. Raw per-IP per-cycle outcomes are required before reporting incremental Power/War associations or any causal interpretation.\n""",encoding="utf-8")
    (out/"outputs/FINAL_SUMMARY.json").write_text(json.dumps({"stage":"power_availability_infrastructure_scientific_closure_v3","taxonomy_rows":int(len(tax)),"cycle_rows":int(len(cycles)),"ip_rows":int(len(z)),"figures_generated":["figure31_event_timeline"],"figures_not_generated":"32-42","pairwise_power_normal":"NOT_ESTIMABLE","causal_inference":"PROHIBITED"},ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"README.md").write_text("""# power_availability_infrastructure_scientific_closure_v3\n\nThis is a new, conservative closure stage. It preserves the frozen v1/v2 artifacts and does not read war outcomes.\n\nGenerated: scientific boundary audit, method provenance, event taxonomy, cycle-level set labels, one verified event timeline, and an explicit estimability report.\n\nNot generated: IP×cycle CLEAN/POWER_ONLY/WAR_ONLY/OVERLAP outcomes, common-support ROC/PR, GEE interaction, ASN conditional model, and case-crossover. The available cache is event-level and cannot be relabeled as raw per-probe data.\n\nDate-only events are not expanded to 00:00–23:59. Missing observations are never converted to zero.\n""",encoding="utf-8")
    (out/"outputs/VALIDATION.txt").write_text("v3 file-level validation\nfigure31: zh/en PNG+PDF+SVG = 6 files\nfigures32-42: NOT_GENERATED (raw IP-cycle panel unavailable)\nno zero-fill of missing probe rows\nno causal inference\n",encoding="utf-8")

def manifest(root: Path, out: Path):
    files=[]
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name not in {"FINAL_MANIFEST.json","OUTPUT_MANIFEST_SHA256.txt"}:
            files.append({"path":str(p.relative_to(out)).replace("\\","/"),"sha256":sha256(p),"bytes":p.stat().st_size})
    try: head=subprocess.check_output(["git","rev-parse","HEAD"],cwd=str(root),text=True).strip()
    except Exception: head="UNKNOWN"
    obj={"stage":"power_availability_infrastructure_scientific_closure_v3","git_head":head,"files":files}
    (out/"outputs/FINAL_MANIFEST.json").write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"methods/OUTPUT_MANIFEST_SHA256.txt").write_text(sha256(out/"outputs/FINAL_MANIFEST.json")+"  outputs/FINAL_MANIFEST.json\n",encoding="utf-8")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--out",type=Path,required=True); a=ap.parse_args()
    out=a.out; setup(out); boundary_audit(out); provenance(out); tax=build_taxonomy(a.root,out); cyc=exposure_cycles(a.root,out,tax); z=availability_stub(a.root,out); make_figures(out,tax,cyc); reports(a.root,out,tax,cyc,z); manifest(a.root,out)
    print(json.dumps({"out":str(out),"taxonomy_rows":len(tax),"cycle_rows":len(cyc),"ip_rows":len(z)},ensure_ascii=False))
if __name__=="__main__": main()
