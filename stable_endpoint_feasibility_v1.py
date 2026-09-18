#!/usr/bin/env python3
"""Outcome-blind stable endpoint screening and feasibility audit.

Only normal Ping responses, frozen pair timestamps, and cycle-quality/exposure
registries are used. No treated/control primary outcomes or role labels enter.
"""
from __future__ import annotations
import hashlib, json, math, subprocess
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pyarrow as pa
import pyarrow.parquet as pq

ROOT=Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
STAGE=ROOT/'stable_endpoint_feasibility_v1'; OUT=STAGE/'outputs'; FIG=OUT/'figures'
PAIR=ROOT/'feasibility_imc2027_v3/outputs/endpoint_role_final_design_v1/unique_matched_pairs.csv'
CYC=ROOT/'runs/paper_final_v2_episode_fix_20260910/results/stages/stage00_quality/tables/stage00_cycle_quality.csv'
TARGET=ROOT/'runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet'
SCHED=ROOT/'config/planned_outage_schedule_v4_0.csv'; REG=ROOT/'config/event_registry_v2.csv'

def sha256(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def wilson(k,n,z=1.959963984540054):
    if n<=0:return (np.nan,np.nan,np.nan)
    p=k/n; den=1+z*z/n; cen=(p+z*z/(2*n))/den; half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return p,cen-half,cen+half

def wilson_series(k, n, z=1.959963984540054):
    """Vectorised Wilson interval for one fixed n and a pandas Series k."""
    k=np.asarray(k,dtype=float); n=float(n)
    if n<=0:
        return np.full(k.shape,np.nan), np.full(k.shape,np.nan)
    p=k/n; den=1+z*z/n
    centre=(p+z*z/(2*n))/den
    half=z*np.sqrt(np.maximum(0,p*(1-p)/n+z*z/(4*n*n)))/den
    return centre-half, centre+half

def savefig(name):
    plt.tight_layout()
    for e,kw in [('png',{'dpi':300}),('pdf',{}),('svg',{})]: plt.savefig(FIG/f'{name}.{e}',bbox_inches='tight',**kw)
    plt.close()

def norm_state(x):
    if pd.isna(x): return None
    s=str(x).strip().lower().replace('_',' ')
    for t in [' oblast',' city',' region']:
        s=s.replace(t,'')
    return ' '.join(s.split())

def intervals_from_configs():
    xs=[]
    s=pd.read_csv(SCHED)
    for c in ['start_utc','end_utc','planned_start_utc','planned_end_utc']:
        if c in s: s[c]=pd.to_datetime(s[c],utc=True,errors='coerce')
    # Only registered positive exposure windows are exclusions.  Cancellation
    # and explicit no-restriction rows are evidence of clean time and must not
    # erase the normal baseline.
    if 'schedule_positive' in s.columns:
        s=s[s.schedule_positive.fillna(0).astype(int).eq(1)].copy()
    for _,r in s.iterrows():
        a=r.get('start_utc'); b=r.get('end_utc')
        if pd.isna(a) or pd.isna(b): a=r.get('planned_start_utc'); b=r.get('planned_end_utc')
        if pd.notna(a) and pd.notna(b) and b>a:
            state=r.get('affected_admin1') if pd.notna(r.get('affected_admin1')) else r.get('admin1')
            xs.append((a-pd.Timedelta(hours=2),b+pd.Timedelta(hours=2),'planned_outage',norm_state(state)))
    e=pd.read_csv(REG)
    for c in ['attack_start_utc','anchor_lower_utc','network_recovery_end_utc','outage_start_utc','outage_end_utc']:
        if c in e:e[c]=pd.to_datetime(e[c],utc=True,errors='coerce')
    for _,r in e.iterrows():
        a=r.get('attack_start_utc'); b=r.get('network_recovery_end_utc')
        if pd.isna(a): a=r.get('anchor_lower_utc')
        if pd.isna(b): b=r.get('outage_end_utc')
        if pd.notna(a) and pd.notna(b) and b>a: xs.append((a-pd.Timedelta(hours=2),b+pd.Timedelta(hours=2),'war_or_recovery',None))
    return xs

def merge_intervals(xs):
    """Union overlapping exclusion intervals (already state-filtered)."""
    if not xs: return []
    out=[]
    for a,b in sorted(xs,key=lambda z:z[0]):
        if out and a<=out[-1][1]: out[-1]=(out[-1][0],max(out[-1][1],b))
        else: out.append((a,b))
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True); FIG.mkdir(parents=True,exist_ok=True)
    pairs=pd.read_csv(PAIR); assert len(pairs)==21, f'expected 21 frozen pairs, got {len(pairs)}'
    for c in ['treated_start','treated_end','control_start','control_end']: pairs[c]=pd.to_datetime(pairs[c],utc=True)
    pairs=pairs.sort_values(['treated_start','pair_id']).reset_index(drop=True); pairs['split']=np.where(pairs.index<13,'discovery','holdout')
    pairs.to_csv(OUT/'frozen_21_pairs.csv',index=False)
    target=pd.read_parquet(TARGET,columns=['dst_ip','prefix24','target_admin1','target_asn','valid_target_admin1'])
    target=target[target.valid_target_admin1.eq(1)].drop_duplicates('dst_ip').rename(columns={'dst_ip':'ip','target_admin1':'oblast','target_asn':'asn'})
    target['ip']=target.ip.astype(str); target['prefix24']=target.prefix24.fillna('UNKNOWN').astype(str); target['asn']=target.asn.fillna('UNKNOWN').astype(str)
    target['_oblast_norm']=target.oblast.map(norm_state)
    cyc=pd.read_csv(CYC); cyc.measure_time=pd.to_datetime(cyc.measure_time,utc=True); cyc=cyc[cyc.is_complete.astype(bool)].copy(); cyc['cycle_end']=cyc.measure_time+pd.Timedelta(hours=2)
    excl=intervals_from_configs()
    # Pre-union interval lists by oblast; the previous row-wise
    # "any(all intervals)" check was needlessly quadratic.
    states=sorted(set(norm_state(x) for x in pairs.treated_state.tolist()+pairs.control_state.tolist()))
    excl_by_state={}
    for st in states:
        rows=[(a,b) for a,b,label,es in excl if label!='planned_outage' or es in (None,st)]
        excl_by_state[st]=merge_intervals(rows)
    def clean_mask(frame, intervals):
        bad=np.zeros(len(frame),dtype=bool)
        mt=pd.to_datetime(frame.measure_time,utc=True).astype('int64').to_numpy()
        ce=pd.to_datetime(frame.cycle_end,utc=True).astype('int64').to_numpy()
        def ns(x): return pd.Timestamp(x).value
        for start,end in intervals: bad |= (mt<ns(end)) & (ce>ns(start))
        return ~bad
    def clean_cycles(anchor,state):
        a=anchor-pd.Timedelta(days=21); b=anchor-pd.Timedelta(days=7); q=cyc[(cyc.measure_time>=a)&(cyc.measure_time<b)].copy()
        return q[clean_mask(q,excl_by_state.get(norm_state(state),[]))]
    # frozen normal historical windows
    windows=[]
    for _,p in pairs.iterrows():
        for side,anchor,state in [('treated',p.treated_start,p.treated_state),('control',p.control_start,p.control_state)]:
            q=clean_cycles(anchor,state)
            state_norm=norm_state(state); prev_pool=cyc[(cyc.cycle_end<=anchor)].copy(); prev=prev_pool[clean_mask(prev_pool,excl_by_state.get(state_norm,[]))].tail(1)
            primary=cyc[(cyc.measure_time>=anchor.floor('2h'))&(cyc.measure_time<anchor.floor('2h')+pd.Timedelta(hours=2))]
            # control anchors can be off-grid; use the first complete cycle at/after anchor
            if len(primary)==0: primary=cyc[(cyc.measure_time>=anchor)&(cyc.measure_time<anchor+pd.Timedelta(hours=2))]
            windows.append({'pair_id':p.pair_id,'side':side,'oblast':state,'asn_hint':'','window_start':anchor-pd.Timedelta(days=21),'window_end':anchor-pd.Timedelta(days=7),'anchor_time':anchor,'primary_cycle_time':primary.measure_time.iloc[0] if len(primary) else pd.NaT,'previous_clean_cycle_time':prev.measure_time.iloc[0] if len(prev) else pd.NaT,'clean_cycle_times':q.measure_time.tolist(),'clean_n':len(q),'primary_complete':bool(len(primary)),'previous_complete':bool(len(prev)),'split':p.split})
    # query only aggregate normal responses; no outcome table is touched
    import sys; sys.path.insert(0,str(ROOT))
    from src.uresil.config import load_config
    from src.uresil.db import CHClient
    db=CHClient(load_config('config/experiment_v2.local.yaml',run_id='stable_endpoint_feasibility_v1'))
    # The eligibility table is intentionally streamed: 42 windows x ~2M
    # mapped targets is too large to concatenate safely in RAM.
    elig_path=OUT/'stable_window_eligibility.parquet'
    if elig_path.exists(): elig_path.unlink()
    writer=None
    summary_rows=[]
    stable_sets=[]
    stable_counts=Counter()
    observed_counts=Counter()
    paired_stable_atrisk=defaultdict(set)
    available_window_n=sum(bool(w['clean_n']) for w in windows)
    for wi,w in enumerate(windows,1):
        hist=list(w['clean_cycle_times']); prev_time=w['previous_clean_cycle_time']
        hist_sql=','.join("toDateTime('%s')"%x.strftime('%Y-%m-%d %H:%M:%S') for x in hist)
        all_times=list(hist)
        if pd.notna(prev_time): all_times.append(prev_time)
        all_sql=','.join("toDateTime('%s')"%x.strftime('%Y-%m-%d %H:%M:%S') for x in sorted(set(all_times)))
        if all_sql:
            lower=min(all_times); upper=max(all_times)+pd.Timedelta(hours=2)
            count_expr=f"countDistinctIf(toStartOfInterval(measure_time,INTERVAL 2 HOUR), toStartOfInterval(measure_time,INTERVAL 2 HOUR) IN ({hist_sql}))" if hist_sql else "toUInt64(0)"
            risk_expr=f", maxIf(1, toStartOfInterval(measure_time,INTERVAL 2 HOUR)=toDateTime('{prev_time.strftime('%Y-%m-%d %H:%M:%S')}')) AS at_risk" if pd.notna(prev_time) else ", toUInt8(0) AS at_risk"
            q=f"SELECT dst_ip AS ip, {count_expr} AS responsive_cycles{risk_expr} FROM net_measure.UKRAINE__ping PREWHERE data_center='AWS_frankfurt' AND measure_time>=toDateTime('{lower.strftime('%Y-%m-%d %H:%M:%S')}') AND measure_time<toDateTime('{upper.strftime('%Y-%m-%d %H:%M:%S')}') WHERE toStartOfInterval(measure_time,INTERVAL 2 HOUR) IN ({all_sql}) GROUP BY dst_ip"
            xresp=db.query_df(q); xresp['ip']=xresp.ip.astype(str)
        else: xresp=pd.DataFrame(columns=['ip','responsive_cycles','at_risk'])
        # Only historical normal responses and previous-clean at-risk are used.
        # Map aggregate query results onto the fixed target universe.  This is
        # substantially faster and lower-memory than a full pandas merge for
        # every 2M-IP window.
        window_target=target[target._oblast_norm.eq(norm_state(w['oblast']))].copy()
        for ip in window_target.ip: observed_counts[ip]+=1
        if len(xresp):
            xm=xresp.drop_duplicates('ip').set_index('ip')
            resp_counts=window_target.ip.map(xm.responsive_cycles).fillna(0).astype('int32')
            risk_flags=window_target.ip.map(xm.at_risk).fillna(0).astype('int8')
        else:
            resp_counts=pd.Series(0,index=window_target.index,dtype='int32'); risk_flags=pd.Series(0,index=window_target.index,dtype='int8')
        p=pd.DataFrame({'pair_id':str(w['pair_id']),'side':w['side'],'oblast':w['oblast'],'split':w['split'],'window_start':w['window_start'],'window_end':w['window_end'],'anchor_time':w['anchor_time'],'primary_cycle_time':w['primary_cycle_time'],'previous_clean_cycle_time':w['previous_clean_cycle_time'],'complete_cycles':int(w['clean_n']),'responsive_cycles':resp_counts.to_numpy(),'historical_availability':resp_counts.to_numpy()/max(1,w['clean_n']),'at_risk':risk_flags.to_numpy(),'ip':window_target.ip.to_numpy(),'prefix24':window_target.prefix24.to_numpy(),'asn':window_target.asn.to_numpy(),'primary_complete':bool(w['primary_complete']),'previous_complete':bool(w['previous_complete'])})
        lo,hi=wilson_series(p.responsive_cycles,max(1,w['clean_n'])); p['wilson_lower_95']=lo; p['wilson_upper_95']=hi
        p['stable_primary']=(p.complete_cycles>=84)&(p.wilson_lower_95>=.80); p['stable_sensitivity_A']=(p.complete_cycles>=60)&(p.wilson_lower_95>=.80); p['stable_sensitivity_B']=(p.complete_cycles>=120)&(p.wilson_lower_95>=.80); p['stable_sensitivity_C']=(p.complete_cycles>=84)&(p.wilson_lower_95>=.75); p['stable_sensitivity_D']=(p.complete_cycles>=84)&(p.wilson_lower_95>=.85)
        # Persist only the frozen per-IP×window eligibility contract.  Anchor
        # and cycle-completeness helper fields remain in-memory for the paired
        # opportunity audit and are intentionally not duplicated on disk.
        elig_cols=['ip','pair_id','side','oblast','asn','prefix24','window_start','window_end','complete_cycles','responsive_cycles','historical_availability','wilson_lower_95','wilson_upper_95','stable_primary','stable_sensitivity_A','stable_sensitivity_B','stable_sensitivity_C','stable_sensitivity_D']
        p_out=p[elig_cols]
        if writer is None:
            table=pa.Table.from_pandas(p_out,preserve_index=False); writer=pq.ParquetWriter(str(elig_path),table.schema,compression='zstd')
        writer.write_table(pa.Table.from_pandas(p_out,preserve_index=False,schema=writer.schema))
        stable=p[p.stable_primary].copy()
        stable_set=set(stable.ip)
        stable_sets.append({'side':w['side'],'pair_id':str(w['pair_id']),'anchor_time':w['anchor_time'],'stable_ips':stable_set})
        for ip in stable_set: stable_counts[ip]+=1
        if w['primary_complete'] and w['previous_complete']:
            paired_stable_atrisk[(str(w['pair_id']),w['side'])]=set(p.loc[p.stable_primary & p.at_risk.eq(1),'ip'])
        summary_rows.append({'pair_id':str(w['pair_id']),'side':w['side'],'oblast':w['oblast'],'split':w['split'],'window_start':w['window_start'],'window_end':w['window_end'],'complete_cycles':int(w['clean_n']),'candidate_ip_n':int(p.ip.nunique()),'n_ge84_ip':int((p.complete_cycles>=84).sum()),'stable_primary_ip_n':int(p.stable_primary.sum()),'stable_A_ip_n':int(p.stable_sensitivity_A.sum()),'stable_B_ip_n':int(p.stable_sensitivity_B.sum()),'stable_C_ip_n':int(p.stable_sensitivity_C.sum()),'stable_D_ip_n':int(p.stable_sensitivity_D.sum()),'complete_cycle_median':float(p.complete_cycles.median()),'availability_median':float(p.historical_availability.median()),'wilson_lower_median':float(p.wilson_lower_95.median())})
        print(f'window {wi}/{len(windows)} {w["side"]} {w["pair_id"]} rows={len(p)} n={w["clean_n"]}',flush=True)
    if writer is not None: writer.close()
    summary=pd.DataFrame(summary_rows)
    summary.to_csv(OUT/'stable_window_summary.csv',index=False)
    # repeatability across historical windows, outcome blind
    rep=target[['ip','oblast','asn','prefix24']].drop_duplicates('ip').copy(); rep['n_windows_observed']=rep.ip.map(observed_counts).fillna(0).astype(int); rep['n_windows_stable']=rep.ip.map(stable_counts).fillna(0).astype(int); rep['stable_fraction']=rep.n_windows_stable/rep.n_windows_observed.replace(0,np.nan)
    rep.to_parquet(OUT/'stable_repeatability_by_ip.parquet',index=False); pd.DataFrame([{'ip_n':len(rep),'stable_ge1':int((rep.n_windows_stable>=1).sum()),'stable_ge2':int((rep.n_windows_stable>=2).sum()),'stable_ge3':int((rep.n_windows_stable>=3).sum()),'stable_ge5':int((rep.n_windows_stable>=5).sum()),'stable_ge8':int((rep.n_windows_stable>=8).sum()),'stable_ge10':int((rep.n_windows_stable>=10).sum()),'mean_stable_fraction':rep.stable_fraction.mean()}]).to_csv(OUT/'stable_repeatability_summary.csv',index=False)
    # adjacent-window Jaccard and transitions, stratified by side and chronological anchor
    jacc=[]
    # Compare adjacent historical windows only within the same side and
    # oblast; switching oblasts would mechanically force disjoint IP sets.
    for side in ['treated','control']:
        for oblast in sorted(set(r['oblast'] for r in windows if any(x['side']==side and x['oblast']==r['oblast'] for x in windows))):
            rows=sorted([(r['anchor_time'],r['stable_ips']) for r in stable_sets if r['side']==side and next((w['oblast'] for w in windows if str(w['pair_id'])==r['pair_id'] and w['side']==side),None)==oblast],key=lambda x:x[0])
            for (a,x),(b,y) in zip(rows,rows[1:]): jacc.append({'side':side,'oblast':oblast,'from_pair_time':a,'to_pair_time':b,'jaccard':len(x&y)/len(x|y) if x|y else np.nan,'stable_to_stable':len(x&y)/len(x) if x else np.nan,'stable_to_unstable':1-(len(x&y)/len(x)) if x else np.nan})
    pd.DataFrame(jacc).to_csv(OUT/'stable_transition_audit.csv',index=False)
    # paired stable opportunities: no primary response columns
    opp_rows=[]
    for _,pr in pairs.iterrows():
        pid=str(pr.pair_id); both=paired_stable_atrisk.get((pid,'treated'),set()) & paired_stable_atrisk.get((pid,'control'),set())
        for ip in both: opp_rows.append({'pair_id':pid,'ip':ip,'treated_episode_id':pr.treated_episode_id,'control_episode_id':pr.control_episode_id,'treated_state':pr.treated_state,'control_state':pr.control_state,'split':pr.split,'paired_stable_opportunity':True})
    opp=pd.DataFrame(opp_rows,columns=['pair_id','ip','treated_episode_id','control_episode_id','treated_state','control_state','split','paired_stable_opportunity']); opp.to_parquet(OUT/'paired_stable_opportunities.parquet',index=False)
    od=opp.groupby('ip',as_index=False).agg(n_paired_stable_opportunities=('pair_id','nunique')) if len(opp) else pd.DataFrame(columns=['ip','n_paired_stable_opportunities']); od.to_csv(OUT/'paired_stable_opportunity_distribution.csv',index=False)
    thresholds=[1,2,3,4,5,6,8,10]; pd.DataFrame([{'threshold':n,'unique_ip_n':int((od.n_paired_stable_opportunities>=n).sum())} for n in thresholds]).to_csv(OUT/'paired_stable_opportunity_thresholds.csv',index=False)
    # discovery/holdout and dispersion
    ps=opp.groupby('ip').agg(discovery_n=('split',lambda x:int((x=='discovery').sum())),holdout_n=('split',lambda x:int((x=='holdout').sum())),oblast=('treated_state','first')).reset_index() if len(opp) else pd.DataFrame(columns=['ip','discovery_n','holdout_n','oblast']); target_idx=target.set_index('ip'); ps['prefix24']=ps.ip.map(target_idx.prefix24) if len(ps) else pd.Series(dtype=str); ps['asn']=ps.ip.map(target_idx.asn) if len(ps) else pd.Series(dtype=str); ps.to_csv(OUT/'discovery_holdout_stable_support.csv',index=False); q=ps[(ps.discovery_n>=3)&(ps.holdout_n>=1)].copy()
    dist=pd.DataFrame([{'unique_ip_n':len(q),'unique_prefix24_n':q.ip.nunique(),'unique_asn_n':q.asn.nunique(),'unique_oblast_n':q.oblast.nunique(),'max_oblast_share':q.oblast.value_counts(normalize=True).max() if len(q) else np.nan,'max_asn_share':q.asn.value_counts(normalize=True).max() if len(q) else np.nan,'max_prefix24_share':q.prefix24.value_counts(normalize=True).max() if len(q) else np.nan}]); dist.to_csv(OUT/'stable_cohort_dispersion.csv',index=False)
    stable_ip_set=set(rep.loc[rep.n_windows_stable>0,'ip'])
    for col,name in [('oblast','stable_distribution_by_oblast.csv'),('asn','stable_distribution_by_asn.csv'),('prefix24','stable_distribution_by_24.csv')]:
        eligible_counts=rep.groupby(col).ip.nunique().rename('eligible_ip_n'); stable_counts_by=rep[rep.ip.isin(stable_ip_set)].groupby(col).ip.nunique().rename('stable_ip_n'); g=pd.concat([eligible_counts,stable_counts_by],axis=1).fillna(0).reset_index(); g['stable_proportion']=g.stable_ip_n/g.eligible_ip_n.replace(0,np.nan); g.to_csv(OUT/name,index=False)
    top=rep.groupby('asn').agg(eligible_ip_n=('ip','nunique')); top['stable_ip_n']=rep[rep.ip.isin(stable_ip_set)].groupby('asn').ip.nunique(); top=top.fillna(0).reset_index(); top['stable_proportion']=top.stable_ip_n/top.eligible_ip_n; top.sort_values('stable_ip_n',ascending=False).head(20).to_csv(OUT/'stable_top20_asn.csv',index=False)
    # event/pair contribution is support structure only
    ec=opp.groupby('pair_id').ip.nunique().reset_index(name='stable_opportunity_ip_n'); ec['share']=ec.stable_opportunity_ip_n/ec.stable_opportunity_ip_n.sum() if len(ec) else np.nan; ec.to_csv(OUT/'event_contribution_audit.csv',index=False)
    # Sensitivity rules are audit-only, primary remains fixed.
    sens=[]
    # Threshold counts are accumulated from the per-window summaries; no primary
    # outcome or outage-cycle table is needed.
    for col,label in [('stable_primary','primary'),('stable_sensitivity_A','A'),('stable_sensitivity_B','B'),('stable_sensitivity_C','C'),('stable_sensitivity_D','D')]:
        idx={'primary':'stable_primary_ip_n','A':'stable_A_ip_n','B':'stable_B_ip_n','C':'stable_C_ip_n','D':'stable_D_ip_n'}[label]
        sens.append({'rule':col,'eligible_ip_n':int((rep.n_windows_stable>0).sum()) if label=='primary' else np.nan,'eligible_window_rows':int(summary[idx].sum()),'paired_opportunity_ip_n':np.nan})
    pd.DataFrame(sens).to_csv(OUT/'stable_threshold_sensitivity.csv',index=False)
    prev=pd.read_csv(ROOT/'resilient_endpoint_feasibility_v1/outputs/support_threshold_summary.csv'); cur=pd.DataFrame([{'dataset':'previous_power_resilient','support_ge1':int(prev.loc[prev.metric=='all','ip_n'].iloc[0]),'support_ge2':int(prev.loc[prev.metric=='ge2','ip_n'].iloc[0]),'support_ge3':int(prev.loc[prev.metric=='ge3','ip_n'].iloc[0]),'support_ge5':int(prev.loc[prev.metric=='ge5','ip_n'].iloc[0])},{'dataset':'stable_primary','support_ge1':int((od.n_paired_stable_opportunities>=1).sum()),'support_ge2':int((od.n_paired_stable_opportunities>=2).sum()),'support_ge3':int((od.n_paired_stable_opportunities>=3).sum()),'support_ge5':int((od.n_paired_stable_opportunities>=5).sum())}]); cur.to_csv(OUT/'primary_vs_previous_support_comparison.csv',index=False)
    # Figures
    plt.figure(figsize=(7,5)); plt.hist(summary.availability_median.dropna(),bins=20,color='#4472c4'); plt.xlabel('各窗口 IP 历史可达率中位数');plt.ylabel('窗口数量');plt.title('正常历史可达率（窗口中位数）');savefig('01_historical_availability')
    plt.figure(figsize=(7,5)); plt.hist(summary.wilson_lower_median.dropna(),bins=20,color='#70ad47');plt.xlabel('各窗口 Wilson 95% 下界中位数');plt.ylabel('窗口数量');plt.title('Wilson 下界（窗口中位数）');savefig('02_wilson_lower')
    stable_window_rows=int(summary.stable_primary_ip_n.sum()); ge84_rows=int(summary.n_ge84_ip.sum())
    plt.figure(figsize=(7,5)); plt.bar(['候选（唯一IP）','n≥84（窗口行）','Primary稳定（窗口行）'],[len(target),ge84_rows,stable_window_rows]);plt.ylabel('数量');plt.title('Primary 稳定窗口筛选规模');savefig('03_primary_stable_count')
    plt.figure(figsize=(7,5)); plt.hist(rep.n_windows_stable,bins=np.arange(-.5,max(1,rep.n_windows_stable.max())+1.5),color='#ed7d31');plt.xlabel('被判定为稳定的历史窗口数');plt.ylabel('IP 数量');plt.title('每个 IP 的稳定历史窗口数');savefig('04_stable_windows_per_ip')
    plt.figure(figsize=(7,5)); plt.hist(pd.DataFrame(jacc).jaccard.dropna() if jacc else [],bins=20,color='#a5a5a5');plt.xlabel('相邻窗口稳定集合 Jaccard');plt.ylabel('窗口对数量');plt.title('稳定标签时间重复性');savefig('05_stable_repeatability')
    plt.figure(figsize=(7,5)); plt.hist(od.n_paired_stable_opportunities if len(od) else [],bins=np.arange(.5,max(1,od.n_paired_stable_opportunities.max() if len(od) else 1)+1.5),color='#5b9bd5');plt.xlabel('配对稳定机会数');plt.ylabel('IP 数量');plt.title('配对稳定机会次数分布');savefig('06_paired_stable_opportunities')
    pv=cur.set_index('dataset')[['support_ge1','support_ge2','support_ge3','support_ge5']];pv.T.plot(kind='bar',figsize=(8,5));plt.xlabel('支持阈值');plt.ylabel('IP 数量');plt.title('上一轮与稳定筛选后的支持结构比较');plt.legend(frameon=False);savefig('07_support_comparison')
    plt.figure(figsize=(8,5));
    for col,label in [('discovery_n','发现期'),('holdout_n','留出期')]: plt.hist(ps[col],bins=np.arange(-.5,max(1,ps[col].max())+1.5),alpha=.55,label=label)
    plt.xlabel('配对稳定机会数');plt.ylabel('IP 数量');plt.title('发现期/留出期支持');plt.legend(frameon=False);savefig('08_discovery_holdout_support')
    g=rep.groupby('oblast').ip.nunique().sort_values();plt.figure(figsize=(8,6));plt.barh(g.index,g.values);plt.xlabel('稳定 IP 数量');plt.ylabel('州');plt.title('稳定 IP 的州级分布');savefig('09_stable_by_oblast')
    g=rep.groupby('asn').ip.nunique().sort_values(ascending=False).head(20).sort_values();plt.figure(figsize=(8,6));plt.barh(g.index.astype(str),g.values);plt.xlabel('稳定 IP 数量');plt.ylabel('ASN');plt.title('稳定 IP 的 ASN 分布（前20）');savefig('10_stable_by_asn')
    max_event=float(ec.share.max()) if len(ec) else np.nan; max_ob=float(dist.max_oblast_share.iloc[0]) if len(dist) else np.nan; max_asn=float(dist.max_asn_share.iloc[0]) if len(dist) else np.nan; max_pfx=float(dist.max_prefix24_share.iloc[0]) if len(dist) else np.nan
    stable_ip_n=int((rep.n_windows_stable>0).sum()); ge3=int((od.n_paired_stable_opportunities>=3).sum()); ge5=int((od.n_paired_stable_opportunities>=5).sum()); d2h1=int(((ps.discovery_n>=2)&(ps.holdout_n>=1)).sum()); d3h1=int(((ps.discovery_n>=3)&(ps.holdout_n>=1)).sum()); d3h2=int(((ps.discovery_n>=3)&(ps.holdout_n>=2)).sum()); d5h2=int(((ps.discovery_n>=5)&(ps.holdout_n>=2)).sum()); stable_repeat=float(np.nanmean([x['stable_to_stable'] for x in jacc])) if jacc else np.nan
    reasons=[]
    if stable_ip_n<500: reasons.append('stable IP 数量不足500')
    if ge3<500: reasons.append('至少3次配对稳定机会的IP少于500')
    if ge5<100: reasons.append('至少5次配对稳定机会的IP少于100')
    if d2h1<500: reasons.append('discovery≥2且holdout≥1的IP少于500')
    if d3h1<200: reasons.append('discovery≥3且holdout≥1的IP少于200')
    if max_ob>0.5: reasons.append('州级集中度超过50%')
    if max_asn>0.4: reasons.append('ASN集中度超过40%')
    verdict='GO_FOR_STABLE_ENDPOINT_OUTAGE_TEST' if not reasons else 'NO_GO_FOR_STABLE_ENDPOINT_COHORT'
    decision={'final_verdict':verdict,'primary_rule':'n>=84 and Wilson 95% lower bound>=0.80','stable_ip_n':stable_ip_n,'stable_window_rows':stable_window_rows,'paired_stable_opportunity_ip_n_ge3':ge3,'paired_stable_opportunity_ip_n_ge5':ge5,'discovery_ge2_holdout_ge1':d2h1,'discovery_ge3_holdout_ge1':d3h1,'discovery_ge3_holdout_ge2':d3h2,'discovery_ge5_holdout_ge2':d5h2,'stable_to_stable_transition_probability':stable_repeat,'max_oblast_share':max_ob,'max_asn_share':max_asn,'max_prefix24_share':max_pfx,'max_event_pair_contribution':max_event,'reasons':reasons,'outcome_blind':True,'read_treated_control_primary_outcomes':False,'used_caida_itdk_traceroute_roles':False}
    (OUT/'STABLE_ENDPOINT_FEASIBILITY_DECISION.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2)+'\n')
    # Compatibility object for the report template; the value is computed from
    # streamed window summaries, not from a retained full eligibility table.
    class _Count:
        def sum(self): return stable_window_rows
    elig=type('EligibilityCount',(),{'stable_primary':_Count()})()
    report=f"# Stable Endpoint Screening + Feasibility Audit\n\n## Final decision\n\n**{verdict}**\n\nPrimary rule: `n >= 84` and Wilson 95% lower bound `>= 0.80`.\n\n- Stable IP: {stable_ip_n:,}\n- Stable window observations: {int(elig.stable_primary.sum()):,}\n- Paired stable opportunity IPs ≥3: {ge3:,}; ≥5: {ge5:,}\n- Discovery≥2/holdout≥1: {d2h1:,}\n- Discovery≥3/holdout≥1: {d3h1:,}\n- Discovery≥3/holdout≥2: {d3h2:,}\n- Discovery≥5/holdout≥2: {d5h2:,}\n- Stable→stable transition probability: {stable_repeat:.4f}\n- Maximum oblast/ASN/prefix24 shares: {max_ob:.4f} / {max_asn:.4f} / {max_pfx:.4f}\n- Maximum event-pair contribution: {max_event:.4f}\n\nReasons: \n"+'\n'.join('- '+x for x in reasons)+'\n\nThis stage did not read treated/control primary outcomes, CAIDA/ITDK/traceroute role information, M-Lab USER/NETWORK labels, H1-H4 outcomes, or Sensitivity. It is an outcome-blind sample-structure audit only.\n'
    (OUT/'STABLE_ENDPOINT_FEASIBILITY_REPORT.md').write_text(report,encoding='utf-8')
    (OUT/'config_snapshot.json').write_text(json.dumps({'stage':'Stable Endpoint Screening + Feasibility Audit','frozen_pairs':21,'historical_window':'[-21d,-7d)','primary_rule':'n>=84; Wilson lower>=0.80','sensitivity_rules':{'A':'n>=60; lower>=0.80','B':'n>=120; lower>=0.80','C':'n>=84; lower>=0.75','D':'n>=84; lower>=0.85'},'discovery_pairs':13,'holdout_pairs':8,'outcome_blind':True,'caida_used':False},ensure_ascii=False,indent=2)+'\n')
    prov={'inputs':{str(p):sha256(p) for p in [PAIR,CYC,TARGET,SCHED,REG]},'outcome_blind':True,'outputs':{}}
    for p in OUT.glob('*'):
        if p.is_file() and p.name!='provenance_and_hashes.txt': prov['outputs'][p.name]=sha256(p)
    (OUT/'provenance_and_hashes.txt').write_text(json.dumps(prov,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__': main()
