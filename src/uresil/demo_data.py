"""Deterministic synthetic tables for plotting smoke tests only."""
from __future__ import annotations
import numpy as np
import pandas as pd

SEED=20240601

def generate_demo_tables(cfg):
    rng=np.random.default_rng(SEED);out=cfg.out_dir("results_tables")
    times=pd.date_range(cfg.study["start_utc"],cfg.study["end_utc"],freq="2h",tz="UTC")
    n=len(times);x=np.arange(n);reach=.98+.01*np.sin(2*np.pi*x/12)
    ev=cfg.load_event_registry();
    for _,r in ev.iterrows():
        a=pd.to_datetime(r.primary_anchor_utc,utc=True);h=(times-a).total_seconds()/3600
        depth=.05 if r.event_family=="planned_outage" else .15
        reach-=np.where((h>=0)&(h<48),depth*np.exp(-np.clip(np.asarray(h),0,None)/24),0)
    f1=pd.DataFrame({"measure_time":times,"ping_prefixes":20000+rng.integers(-300,300,n),
      "ping_unique_ips":250000+rng.integers(-5000,5000,n),"trace_reached_rate":np.clip(reach+rng.normal(0,.005,n),0,1),
      "as0_path_share":np.clip(.05+rng.normal(0,.003,n),0,1),"geo_unknown_path_share":np.clip(.08+rng.normal(0,.004,n),0,1),
      "is_complete":(rng.random(n)>.02).astype(int)})
    f1.to_csv(out/"f1_coverage.csv",index=False)
    pd.DataFrame({"measure_time":times,"national_reach":np.clip(reach,0,1)}).to_csv(out/"f2_signal.csv",index=False)
    pd.DataFrame({"event_id":ev.event_id,"label_zh":ev.event_name_zh,"label_en":ev.event_name_en,
      "kind":np.where(ev.event_family.eq("planned_outage"),"planned","attack"),"start_utc":ev.primary_anchor_utc,
      "end_utc":ev.outage_end_utc,"anchor_type":ev.primary_anchor_type,"precision_h":ev.anchor_precision_h}).to_csv(out/"f2_timeline.csv",index=False)
    # Full PR curves
    prs=[];aus=[]
    for i,m in enumerate(["B0","B1","B2"]):
        rec=np.linspace(0,1,60);prec=np.clip(.85-.25*rec+.05*i,0,1)
        prs.extend({"method":m,"recall":r,"precision":p,"threshold":np.nan} for r,p in zip(rec,prec))
        aus.append({"method":m,"auprc":np.trapz(prec,rec)})
    pd.DataFrame(prs).to_csv(out/"f3_pr.csv",index=False);pd.DataFrame(aus).to_csv(out/"f3_auprc.csv",index=False)
    valid_planned=ev[(ev.event_family.eq("planned_outage"))&(ev.analysis_role.eq("planned_valid"))]
    event_metrics=[]
    for i,(_,e) in enumerate(valid_planned.iterrows()):
        b1=.62+.01*i; b2=.68+.015*i
        event_metrics.append({"event_id":e.event_id,"auprc_B0":.60,"auprc_B1":b1,"auprc_B2":b2,
                              "delta_b2_vs_b1":b2-b1,"n_cycle":20,"n_admin1":20})
    pd.DataFrame(event_metrics).to_csv(out/"exp_a_event_metrics.csv",index=False)
    attacks=ev[~ev.event_family.eq("planned_outage")].head(4)
    f4=[];f5=[];curves=[];groups=[f"{a}|Ukraine|{s}" for a,s in zip([6849,15895,13188,3326,25229],["Odesa Oblast","Lviv Oblast","Sumy Oblast","Rivne Oblast","Mykolaiv Oblast"])]
    for j,(_,e) in enumerate(attacks.iterrows()):
        for h in range(-24,50,2):
            eff=(0 if h<0 else -(.08+.03*j)*np.exp(-h/30))+rng.normal(0,.005)
            f4.append({"event_id":e.event_id,"rel_h":h,"effect":eff,"ci_lo":eff-.02,"ci_hi":eff+.02,"n_prefix":500,
                       "design_admissible":1,"analysis_role":e.analysis_role})
            for g in groups:
                f5.append({"event_id":e.event_id,"admin1":g.split("|")[-1],"rel_h":h,"reach_dev":eff+rng.normal(0,.02),"n_group":5,
                           "design_admissible":1,"analysis_role":e.analysis_role})
    pd.DataFrame(f4).to_csv(out/"f4_event_study.csv",index=False);pd.DataFrame(f5).to_csv(out/"f5_state_time.csv",index=False)
    for h in range(-24,50,2):
        p=.98 if h<0 else .98-.06*np.exp(-h/12);a=.98 if h<0 else .98-.15*np.exp(-h/35)
        curves.append({"rel_h":h,"planned_reach":p,"planned_lo":p-.02,"planned_hi":p+.02,"planned_n_events":2,
                       "attack_reach":a,"attack_lo":a-.02,"attack_hi":a+.02,"attack_n_events":4})
    pd.DataFrame(curves).to_csv(out/"f6_fingerprint.csv",index=False)
    f7=[];pred=[]
    for gi,g in enumerate(groups):
        for ei,(_,e) in enumerate(attacks.iterrows()):
            auc=.5+.1*gi+.07*ei+rng.normal(0,.04);t90=24+5*gi+3*ei
            f7.append({"group":g,"event_id":e.event_id,"target_asn":g.split('|')[0],"target_country":"Ukraine","target_admin1":g.split('|')[-1],"auc":auc,"t90":t90,"max_deficit":auc/5,"eligible_prefix_n":50})
            for m,bias in [("M4_ridge_history",.03),("M0_global",.15)]:
                pred.append({"target":"deficit_auc_full","model":m,"event_id":e.event_id,"group":g,"pred":auc+rng.normal(0,bias),"actual":auc,"train_event_n":2,
                             "fit_status":"ok" if m.startswith("M4") else "ok_baseline","fit_error":""})
    pd.DataFrame(f7).to_csv(out/"f7_heatmap.csv",index=False);pd.DataFrame(pred).to_csv(out/"f8_pred_scatter.csv",index=False)
    perf=[]
    for m in ["M0_global","M1_admin1","M2_asn","M3_group","M4_ridge_history","M5_gbdt_history"]:
        perf.append({"target":"deficit_auc_full","model":m,"event_id":"EVENT_EQUAL","n":20,"n_test_event":4,"mae":.2-.02*len(perf),"rmse":.25,"auprc_ge_0.1":.8,
                     "fit_status":"ok" if m.startswith(("M4","M5")) else "ok_baseline","fit_failure_n":0})
    pd.DataFrame(perf).to_csv(out/"f8_model_perf.csv",index=False)
    pd.DataFrame({"target":"deficit_auc_full","component":["event","asn","admin1","interaction","residual"],"frac":[.25,.2,.12,.13,.3],"status":"ok","method":"crossed_mixedlm"}).to_csv(out/"f9_variance.csv",index=False)
    dose=pd.DataFrame({"group":np.repeat(groups,6),"exposure_hours":rng.uniform(0,150,30),"next_auc":rng.uniform(.2,1.2,30),"next_t90":rng.uniform(12,100,30)})
    dose.to_csv(out/"f10_dose.csv",index=False)
    surv=[]
    for lab,rate in [("low",.015),("medium",.025),("high",.04)]:
        for h in range(0,169,8):surv.append({"hours":h,"surv_unrecovered":np.exp(-rate*h),"group_label":lab,"n":20})
    pd.DataFrame(surv).to_csv(out/"f10_survival.csv",index=False)
    q=[];ing=[]
    for g in groups:
        q.append({"group":g,"event_id":attacks.iloc[-1].event_id,"auc":rng.uniform(.2,1),"max_deficit":.2,"jsd":rng.uniform(.05,.5),"n_trace_event":rng.integers(100,1000),"quality":"admissible","c_as":.9,"c_geo":.8,"c_edge":.4,"asgeo_jsd_p":.02})
    pd.DataFrame(q).to_csv(out/"f11_quadrant.csv",index=False)
    edges=["AS1|Germany|Hesse=>AS2|Ukraine|Lviv Oblast","AS3|Poland|Mazowieckie=>AS4|Ukraine|Volyn Oblast"]
    for ph in ["baseline","event","recovery"]:
        for ed in edges:ing.append({"event_id":attacks.iloc[-1].event_id,"group":groups[0],"phase":ph,"edge":ed,"count":10,"n_trace":100,"share":.1,"per_1000_trace":100+rng.normal(0,10)})
    pd.DataFrame(ing).to_csv(out/"f12_ingress.csv",index=False)
    pd.DataFrame({"event_id":["E2024_1117_ATTACK","E2024_1128_ATTACK"],"analysis_role":["attack_regional"]*2,"external_network_start_utc":["2024-11-17 05:30:00+00:00","2024-11-28 05:00:00+00:00"],"internal_onset_rel_h":[2,0],"internal_onset_utc":["2024-11-17 07:30:00+00:00","2024-11-28 05:00:00+00:00"],"temporal_offset_h":[2,0],"temporal_concordant":[1,1],"external_admin1":["Odesa Oblast|Sumy Oblast","Lviv Oblast|Rivne Oblast"],"internally_detected_admin1":["Odesa Oblast|Sumy Oblast","Lviv Oblast"],"spatial_jaccard":[1,.5],"external_time_available":[1,1],"external_space_available":[1,1]}).to_csv(out/"f13_external.csv",index=False)
    universe=[]
    for e in ["E2024_0826_ATTACK","E2024_1213_ATTACK","E2024_1225_ATTACK"]:
        base=float(rng.uniform(.6,1.4))
        universe.extend([
            {"event_id":e,"analysis_role":"attack_national","estimand_id":"confirmatory_power","scope_type":"national","sensor_method":"B1","target_universe":"U2_ukraine_valid_asn","n_analysis_unit":20000,"n_sensor":200000,"n_matched_pairs":0,"immediate_drop":.03,"max_deficit":base/8,"deficit_auc_full":base,"t90_h":24},
            {"event_id":e,"analysis_role":"attack_national","estimand_id":"confirmatory_power","scope_type":"national","sensor_method":"B1","target_universe":"U3_ukraine_valid_admin1_asn","n_analysis_unit":18000,"n_sensor":180000,"n_matched_pairs":0,"immediate_drop":.031,"max_deficit":base/8*.96,"deficit_auc_full":base*.97,"t90_h":24},
        ])
    pd.DataFrame(universe).to_csv(out/"exp_b_target_universe_sensitivity.csv",index=False)
    (out/"_DEMO_NOTICE.txt").write_text("SYNTHETIC DATA — NOT FOR SCIENTIFIC USE\n",encoding="utf-8")
    counts={}
    for p in out.glob("*.csv"):
        try: counts[p.name]=len(pd.read_csv(p))
        except pd.errors.EmptyDataError: counts[p.name]=0
    return counts
