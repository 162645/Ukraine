
import sys,json,hashlib,math,subprocess
from pathlib import Path
import numpy as np,pandas as pd
import matplotlib;matplotlib.use('Agg')
import matplotlib.pyplot as plt
sys.path.insert(0,'.')
from src.uresil.config import load_config
from src.uresil.db import CHClient
R=Path.cwd();base=R/'feasibility_imc2027_v3/outputs/endpoint_role_feasibility_v1';O=R/'feasibility_imc2027_v3/outputs/endpoint_role_negative_control_v1';F=O/'figures'
for p in [O,F,O/'tables',O/'reports',O/'manifests']:p.mkdir(parents=True,exist_ok=True)
U=lambda x:pd.to_datetime(x,utc=True)
def ov(a,b,x,y):return a<y and x<b
def H(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
# frozen role universe
master=pd.read_parquet(R/'feasibility_imc2027_v3/outputs/tables/ip_role_candidate_master.parquet')
target=pd.read_parquet(R/'runs/paper_final_v2_episode_fix_20260910/data_derived/target_ip_universe.parquet').rename(columns={'dst_ip':'ip'})
target=target[[x for x in ['ip','prefix24','target_admin1','target_asn','target_country','valid_target_country','valid_target_admin1'] if x in target]].drop_duplicates('ip')
m=master[master.role_candidate.isin(['END_USER_FULL_PERIOD','NETWORK_TRACE','CONFLICT'])].merge(target,on='ip',how='inner')
m=m[(m.target_country.astype(str).str.upper()=='UKRAINE')&m.get('valid_target_country',pd.Series(1,index=m.index)).fillna(1).astype(int).eq(1)&m.get('valid_target_admin1',pd.Series(1,index=m.index)).fillna(1).astype(int).eq(1)]
m['state']=m.target_admin1.astype(str);m['role']=m.role_candidate.map({'END_USER_FULL_PERIOD':'USER','NETWORK_TRACE':'NETWORK','CONFLICT':'CONFLICT'});m=m.drop_duplicates(['ip','role']);role=m[m.role.isin(['USER','NETWORK'])].copy();conf=m[m.role=='CONFLICT']
role['asn']=role.get('target_asn',pd.Series('UNKNOWN',index=role.index)).fillna('UNKNOWN').astype(str);role['prefix24']=role.get('prefix24',pd.Series('UNKNOWN',index=role.index)).fillna('UNKNOWN').astype(str);ROLE_STATES=set(role.state.astype(str));canon=lambda x: x if x in ROLE_STATES else (str(x)+' Oblast' if str(x)+' Oblast' in ROLE_STATES else str(x))
# treated episodes and frozen measurement catalog
a=pd.read_csv(base/'event_inventory.csv');a['start']=U(a.start);a['end']=U(a.end);a=a[(a.included.astype(bool))&(a.primary_population.astype(bool))].copy()
c=pd.read_csv(R/'runs/paper_final_v2_episode_fix_20260910/results/stages/stage00_quality/tables/stage00_cycle_quality.csv');c['measure_time']=U(c.measure_time);c['is_complete']=c.is_complete.astype(bool);cc=c[c.is_complete].copy();cc['end']=cc.measure_time+pd.Timedelta(hours=2)
# frozen power and attack intervals
pints=list(zip(a.start,a.end))
try:
 cfg=load_config('config/experiment_v2.local.yaml',run_id='negative_control_v1');rg=cfg.load_event_registry();rg['aa']=U(rg.get('anchor_lower_utc',rg.get('attack_start_utc')));rg['bb']=U(rg.get('anchor_upper_utc',rg.get('network_recovery_end_utc')));att=[(x.aa,x.bb) for _,x in rg.iterrows() if pd.notna(x.aa) and pd.notna(x.bb) and str(x.get('analysis_role','')).lower()!='planned_outage']
except:att=[]
# Priority A from frozen v4 schedule
sched=pd.read_csv(R/'config/planned_outage_schedule_v4_0.csv');sched['start']=U(sched.planned_start_utc);sched['end']=U(sched.planned_end_utc);sched['state']=sched.admin1.astype(str).str.replace(' Oblast','',regex=False)
ast={'no_restriction','regional_cancellation_confirmed','operator_cancellation_confirmed','cancelled','regional_cancellation_and_early_return'}
A=sched[sched.status.isin(ast)&(sched.schedule_positive.astype(str).isin(['0','0.0']))].copy()
A=A[(~A.state.str.upper().isin(['ALL','NATIONAL','NAN']))&(A.source_url.fillna('').astype(str).str.len()>0)&A.source_grade.fillna('').astype(str).str.lower().isin(['primary','near_primary'])]
# candidate and exclusion log
cand=[];excl=[]
for _,r in A.iterrows():
 reason=''
 if pd.isna(r.start) or pd.isna(r.end) or r.end<=r.start:reason='invalid_interval'
 elif any(ov(r.start,r.end,*x) for x in pints+att):reason='overlaps_treated_or_attack'
 elif len(cc[(cc.end>r.start)&(cc.measure_time<r.end)])==0:reason='no_complete_cycle'
 cand.append({'candidate_id':'A_'+str(r.record_id),'control_class':'PRIORITY_A','source_record_id':r.record_id,'state':r.state,'start':r.start,'end':r.end,'weekday':r.start.weekday(),'slot':r.start.hour*60+r.start.minute,'status':r.status,'restriction_type':r.restriction_type,'source_url':r.source_url,'verified_source_url':r.verified_source_url,'source_grade':r.source_grade,'evidence_rank':r.evidence_rank,'verification_note':r.get('verification_note_zh',''),'candidate_eligible':not reason,'exclusion_reason':reason})
candidates=pd.DataFrame(cand)
# match A deterministically: same state, then weekday/slot, nearest date, no reuse
used=set();pairs=[];failed=[]
for _,t in a.sort_values('start').iterrows():
 q=candidates[(candidates.candidate_eligible)&(candidates.state==str(t.state).replace(' Oblast',''))].copy()
 if q.empty:failed.append((t,'NO_PRIORITY_A'));continue
 q['wd_mismatch']=(q.weekday!=t.start.weekday()).astype(int);q['slot_diff']=(q.slot-(t.start.hour*60+t.start.minute)).abs();q['date_diff']=(q.start-t.start).abs().dt.total_seconds().abs()/86400;q['reuse']=q.candidate_id.isin(used)
 q=q.sort_values(['reuse','wd_mismatch','slot_diff','date_diff','start']);pick=q.iloc[0];used.add(pick.candidate_id)
 pairs.append({'pair_id':'PAIR_'+str(t.episode_id),'treated_episode_id':t.episode_id,'treated_state':t.state,'treated_start':t.start,'treated_end':t.end,'control_id':pick.candidate_id,'control_class':'PRIORITY_A','control_episode_id':'CTRL_A_'+str(pick.source_record_id),'control_state':canon(pick.state),'control_start':pick.start,'control_end':pick.end,'matching_rule':'same oblast; same weekday/slot preferred; nearest date; deterministic; reuse avoided','calendar_distance_days':abs((pick.start-t.start).total_seconds())/86400,'control_source':pick.source_url})
# B clean windows for failures, fixed same weekday/slot nearest date, no outcomes
occupied=pints+att+[(x['control_start'],x['control_end']) for x in pairs]
for t,_reason in failed:
 q=cc.copy();q=q[(q.measure_time>=t.start-pd.Timedelta(days=120))&(q.measure_time<=t.start+pd.Timedelta(days=120))]
 q=q[q.measure_time.dt.weekday.eq(t.start.weekday())];q=q[q.measure_time.dt.hour.eq(t.start.hour)]
 q=q[~q.apply(lambda x:any(ov(x.measure_time,x.end,*z) for z in occupied),axis=1)]
 if len(q):
  q=q.sort_values(['measure_time']);pick=q.iloc[(q.measure_time-t.start).abs().argmin()];cid='B_'+t.episode_id+'_'+pick.measure_time.strftime('%Y%m%dT%H%M');pairs.append({'pair_id':'PAIR_'+str(t.episode_id),'treated_episode_id':t.episode_id,'treated_state':t.state,'treated_start':t.start,'treated_end':t.end,'control_id':cid,'control_class':'PRIORITY_B','control_episode_id':'CTRL_B_'+cid,'control_state':canon(t.state),'control_start':pick.measure_time,'control_end':pick.end,'matching_rule':'same oblast label; same weekday; same 2-hour slot; nearest clean complete cycle; deterministic','calendar_distance_days':abs((pick.measure_time-t.start).total_seconds())/86400,'control_source':'complete-cycle catalog'})
  occupied.append((pick.measure_time,pick.end))
 else: pairs.append({'pair_id':'PAIR_'+str(t.episode_id),'treated_episode_id':t.episode_id,'treated_state':t.state,'treated_start':t.start,'treated_end':t.end,'control_id':'','control_class':'NONE','control_episode_id':'','control_state':canon(t.state),'control_start':pd.NaT,'control_end':pd.NaT,'matching_rule':'no eligible deterministic control','calendar_distance_days':np.nan,'control_source':''})
pairs=pd.DataFrame(pairs)
candidates.to_csv(O/'negative_control_candidate_inventory.csv',index=False)
candidates[~candidates.candidate_eligible].to_csv(O/'negative_control_exclusion_log.csv',index=False)
pairs.to_csv(O/'matched_treated_control_pairs.csv',index=False)
# independent control episodes
ctrl=pairs[pairs.control_class!='NONE'].copy();ind=ctrl.groupby(['control_episode_id','control_class','control_state'],dropna=False).agg(start=('control_start','min'),end=('control_end','max'),matched_treated_episode_n=('treated_episode_id','nunique'),matched_treated_episode_ids=('treated_episode_id',lambda x:'|'.join(x))).reset_index();ind.to_csv(O/'independent_control_episodes.csv',index=False)
# measurement coverage
cov=[]
for kind,df in [('TREATED',a.rename(columns={'episode_id':'id','state':'state'})),('CONTROL',ctrl.rename(columns={'control_episode_id':'id','control_state':'state','control_start':'start','control_end':'end'}))]:
 for _,r in df.iterrows():
  s,z=r.start,r.end;ex=max(1,math.ceil((z-s).total_seconds()/7200));got=cc[(cc.end>s)&(cc.measure_time<z)];bc=cc[(cc.measure_time>=s-pd.Timedelta(days=7))&(cc.end<=s-pd.Timedelta(hours=6))];clean=bc[~bc.apply(lambda q:any(ov(q.measure_time,q.end,*x) for x in pints+att+[(j.start,j.end) for _,j in ind.iterrows()]),axis=1)]
  cov.append({'window_type':kind,'window_id':r.id,'state':r.state,'start':s,'end':z,'expected_cycles':ex,'complete_cycles':len(got),'coverage':min(1,len(got)/ex),'baseline_complete_cycles':len(bc),'baseline_clean_cycles':len(clean),'measurement_eligible':len(got)>0 and len(clean)>=12})
coverage=pd.DataFrame(cov);coverage.to_csv(O/'treated_control_measurement_coverage.csv',index=False)
# query role response for control baseline only, no outage/affected
db=CHClient(load_config('config/experiment_v2.local.yaml',run_id='negative_control_v1'));control_rows=[];qlog=[]
for st in sorted(ctrl.control_state.unique()):
 rr=role[role.state==st];ee=ctrl[ctrl.control_state==st]
 if rr.empty:continue
 intervals=[]
 for _,x in ee.iterrows():
  p=cc[cc.end<=x.control_start].tail(1)
  if len(p): intervals +=[(p.measure_time.iloc[0],p.measure_time.iloc[0]+pd.Timedelta(hours=2)),(x.control_start-pd.Timedelta(days=7),x.control_start-pd.Timedelta(hours=6))]
 if not intervals:continue
 cond=' OR '.join(["(measure_time>=toDateTime('"+x.strftime('%Y-%m-%d %H:%M:%S')+"') AND measure_time<toDateTime('"+y.strftime('%Y-%m-%d %H:%M:%S')+"'))" for x,y in intervals]);resp={}
 ips=rr.ip.astype(str).tolist()
 for j in range(0,len(ips),500):
  il=','.join("'"+x.replace("'","''")+"'" for x in ips[j:j+500]);q="SELECT dst_ip,toStartOfInterval(measure_time,INTERVAL 2 HOUR) bucket FROM net_measure.UKRAINE__ping PREWHERE data_center='AWS_frankfurt' AND ("+cond+") AND dst_ip IN ("+il+") GROUP BY dst_ip,bucket";z=db.query_df(q);qlog.append(st+' '+str(j)+' '+str(len(z)))
  for ip,g in z.groupby('dst_ip'):resp[str(ip)]=set(U(g.bucket))
 for _,x in ee.iterrows():
  pre=cc[cc.end<=x.control_start].tail(1);bc=cc[(cc.measure_time>=x.control_start-pd.Timedelta(days=7))&(cc.end<=x.control_start-pd.Timedelta(hours=6))];clean=bc[~bc.apply(lambda q:any(ov(q.measure_time,q.end,*z) for z in pints+att+[(j.start,j.end) for _,j in ind.iterrows()]),axis=1)];bs=set(clean.measure_time)
  for _,q in rr.iterrows():
   rs=resp.get(str(q.ip),set());control_rows.append({'pair_id':x.pair_id,'control_episode_id':x.control_episode_id,'state':st,'role':q.role,'ip':q.ip,'prefix24':q.prefix24,'asn':q.asn,'baseline_availability':len(rs&bs)/max(1,len(bs)),'baseline_clean_n':len(bs)})
co=pd.DataFrame(control_rows)
# treated baseline-only subset
to=pd.read_parquet(base/'tables/endpoint_role_outcomes.parquet',columns=['episode_id','state','role','ip','prefix24','asn','baseline_availability','primary_population'])
to=to.merge(a[['episode_id']],on='episode_id',how='inner')
# design-level tables without affected rates
def counts(df,keys):
 return df.groupby(keys+['role'],dropna=False).agg(candidate_n=('ip','nunique'),valid_baseline_n=('baseline_availability','count'),unique_prefix24_n=('prefix24','nunique'),baseline_median=('baseline_availability','median'),baseline_q1=('baseline_availability',lambda x:x.quantile(.25)),baseline_q3=('baseline_availability',lambda x:x.quantile(.75))).reset_index()
tc1=counts(to,['episode_id','state']);tc2=counts(co,['pair_id','control_episode_id','state']);tc1['window_type']='TREATED';tc1=tc1.rename(columns={'episode_id':'window_id'});tc2['window_type']='CONTROL';tc2=tc2.rename(columns={'pair_id':'window_id'});pd.concat([tc1,tc2],ignore_index=True).to_csv(O/'treated_control_baseline_summary.csv',index=False)
# role support and composition
rs=[]
for typ,df,key in [('TREATED',to,'episode_id'),('CONTROL',co,'pair_id')]:
 for k,g in df.groupby(key):
  for asn,h in g.groupby('asn'):
   u=h[h.role=='USER'];n=h[h.role=='NETWORK'];rs.append({'window_type':typ,'window_id':k,'asn':asn,'user_n':len(u),'network_n':len(n),'conflict_n':int(conf[conf.state==h.state.iloc[0]].ip.nunique()) if len(h) else 0,'shared_role_stratum':len(u)>0 and len(n)>0,'user_baseline_median':u.baseline_availability.median() if len(u) else np.nan,'network_baseline_median':n.baseline_availability.median() if len(n) else np.nan,'user_network_overlap_range':(max(u.baseline_availability.min(),n.baseline_availability.min()),min(u.baseline_availability.max(),n.baseline_availability.max())) if len(u) and len(n) else (np.nan,np.nan)})
pd.DataFrame(rs).to_csv(O/'role_support_by_stratum.csv',index=False)
# composition and clusters
counts(to,['state']).to_csv(O/'oblast_composition_audit.csv',index=False);counts(to,['asn']).to_csv(O/'asn_composition_audit.csv',index=False)
cl=pd.concat([to.assign(window_type='TREATED'),co.assign(window_type='CONTROL')]).groupby(['window_type','state','role','prefix24']).ip.nunique().reset_index(name='ip_n');cl.groupby(['window_type','role']).ip_n.agg(n_prefix24='count',median='median',q1=lambda x:x.quantile(.25),q3=lambda x:x.quantile(.75),mean='mean',max='max').reset_index().to_csv(O/'cluster_structure_comparison.csv',index=False)
# baseline support SMD and overlap
sup=[]
for typ,df,key in [('TREATED',to,'episode_id'),('CONTROL',co,'pair_id')]:
 for k,g in df.groupby(key):
  u=g[g.role=='USER'].baseline_availability.dropna();n=g[g.role=='NETWORK'].baseline_availability.dropna()
  if len(u) and len(n):sup.append({'window_type':typ,'window_id':k,'n_user':len(u),'n_network':len(n),'smd':(u.mean()-n.mean())/np.sqrt((u.var()+n.var())/2) if u.var()+n.var()>0 else np.nan,'overlap_min':max(u.min(),n.min()),'overlap_max':min(u.max(),n.max()),'overlap_exists':max(u.min(),n.min())<=min(u.max(),n.max())})
pd.DataFrame(sup).to_csv(O/'baseline_common_support_by_stratum.csv',index=False)
# nuisance and design-level simulation placeholders (no effect regression)
pd.DataFrame([{'parameter':'background_loss_probability','estimate':np.nan,'source':'not estimated; outcome-blind stage'},
{'parameter':'user_network_baseline_nuisance_difference','estimate':np.nan,'source':'descriptive baseline only'},
{'parameter':'prefix24_icc','estimate':np.nan,'source':'no negative-control outcome window estimate'},
{'parameter':'stratum_variance','estimate':np.nan,'source':'not estimated'}]).to_csv(O/'nuisance_parameter_estimates.csv',index=False)
pd.DataFrame([{'delta_rd':x,'power':np.nan,'bias':np.nan,'rmse':np.nan,'ci_coverage':np.nan,'convergence_rate':np.nan,'effective_information':np.nan,'status':'BLOCKED_NO_HIERARCHICAL_OUTCOME_SIMULATION'} for x in [0,.03,.05,.075,.10]]).to_csv(O/'hierarchical_power_curve.csv',index=False)
pd.DataFrame([{'delta_rd':.05,'icc':x,'power':np.nan,'status':'BLOCKED_NO_HIERARCHICAL_OUTCOME_SIMULATION'} for x in [.01,.05,.10]]).to_csv(O/'hierarchical_power_by_icc.csv',index=False)
pd.DataFrame([{'delta_rd':0,'empirical_type1_error':np.nan,'status':'BLOCKED_NO_HIERARCHICAL_OUTCOME_SIMULATION'}]).to_csv(O/'simulation_type1_error.csv',index=False);pd.DataFrame([{'delta_rd':.05,'ci_coverage':np.nan,'status':'BLOCKED_NO_HIERARCHICAL_OUTCOME_SIMULATION'}]).to_csv(O/'simulation_ci_coverage.csv',index=False);pd.DataFrame([{'estimator':'fixed_effect_logistic_cluster_robust','convergence_rate':np.nan,'coverage':np.nan,'bias':np.nan,'recommended':False,'status':'NOT_RUN'}]).to_csv(O/'estimator_stability_comparison.csv',index=False)
pd.DataFrame([{'treated_episode_id':x,'power':np.nan,'status':'BLOCKED_NO_HIERARCHICAL_OUTCOME_SIMULATION'} for x in a.episode_id]).to_csv(O/'leave_one_episode_out_power.csv',index=False)
# concentration uses design counts only
inf=pd.concat([tc1.assign(source='treated'),tc2.assign(source='control')]);inf.to_csv(O/'concentration_dependency_audit.csv',index=False)
# figures
plt.style.use('seaborn-v0_8-whitegrid')
def save(n,f):
 for x in ['png','pdf','svg']:f.savefig(F/(n+'.'+x),dpi=300,bbox_inches='tight')
 plt.close(f)
f,ax=plt.subplots(figsize=(10,5));ax.scatter(a.start,np.ones(len(a)),label='Treated',marker='|',s=180);ax.scatter(ctrl.control_start,np.ones(len(ctrl))*0.8,label='Priority A/B control',marker='|',s=180);ax.set_yticks([.8,1]);ax.set_yticklabels(['Control','Treated']);ax.legend();ax.set_title('Treated and negative-control time structure');save('01_time_structure',f)
f,ax=plt.subplots(figsize=(8,5));pairs2=pairs[pairs.control_class!='NONE'];ax.bar(pairs2.treated_episode_id.astype(str),1);ax.set_ylabel('Control available (1=yes)');ax.set_title('Control availability by treated episode');ax.tick_params(axis='x',rotation=90);save('02_control_availability',f)
f,ax=plt.subplots(figsize=(7,5))
for name,df,col in [('Treated',to,'#377eb8'),('Control',co,'#e41a1c')]:
 x=df.groupby('ip').baseline_availability.mean().dropna().sort_values()
 if len(x):ax.step(x,np.arange(1,len(x)+1)/len(x),where='post',label=name+' n='+str(len(x)),color=col)
ax.set_xlabel('Baseline availability');ax.set_ylabel('Empirical CDF');ax.set_title('Treated/control baseline availability ECDF');ax.legend();save('03_baseline_ecdf',f)
f,ax=plt.subplots(figsize=(6,6));q=rs and pd.DataFrame(rs);ax.scatter(np.log1p(q.user_n),np.log1p(q.network_n),c=q.shared_role_stratum.map({True:'#377eb8',False:'#bbbbbb'}));ax.set_xlabel('log(1+USER candidates)');ax.set_ylabel('log(1+NETWORK candidates)');ax.set_title('USER/NETWORK common-support audit');save('04_role_common_support',f)
f,ax=plt.subplots(figsize=(8,5));ax.hist(to[to.role=='USER'].groupby('ip').size(),bins=30,alpha=.5,label='Treated USER');ax.hist(co[co.role=='USER'].groupby('ip').size(),bins=30,alpha=.5,label='Control USER');ax.set_xlabel('Repeated-window observations per IP');ax.set_ylabel('IP count');ax.set_title('Role sample-size structure');ax.legend();save('05_sample_size_structure',f)
f,ax=plt.subplots(figsize=(7,5));ax.hist(cl[cl.window_type=='TREATED'].ip_n,bins=30,alpha=.6,label='Treated');ax.hist(cl[cl.window_type=='CONTROL'].ip_n,bins=30,alpha=.6,label='Control');ax.set_xlabel('IPs per /24');ax.set_ylabel('/24 count');ax.set_title('/24 cluster-size comparison');ax.legend();save('06_cluster_distribution',f)
for name in ['07_hierarchical_power_curve','08_hierarchical_power_icc','09_leave_one_episode_out','10_information_contribution']:
 f,ax=plt.subplots(figsize=(7,5));ax.text(.5,.5,'Not estimable: no outcome-blind hierarchical simulation result',ha='center',va='center');ax.set_axis_off();save(name,f)
# SAP draft and decision
nA=int((pairs.control_class=='PRIORITY_A').sum());nB=int((pairs.control_class=='PRIORITY_B').sum());n0=int((pairs.control_class=='NONE').sum());nctrl=int(ctrl.control_episode_id.nunique());shared=int(pd.DataFrame(rs).shared_role_stratum.sum()) if rs else 0
decision='NO_GO' if nctrl==0 or n0==len(a) else 'YELLOW'
(O/'proposed_final_SAP.md').write_text(f"""# Proposed final SAP (not executed)

This is a design draft only. It is not authorized for formal effect estimation because the negative-control stage is {decision}. Frozen elements are non-frontline population, USER=END_USER_FULL_PERIOD, NETWORK=NETWORK_TRACE, CONFLICT exclusion, immediate pre-cycle at-risk definition, 7-day clean baseline ending 6 hours before onset, complete 2-hour cycles, independent episode contract, and /24 clustering.

The future primary estimand is Delta_RD = (Risk_USER,power - Risk_NETWORK,power) - (Risk_USER,control - Risk_NETWORK,control), with SESOI +0.05, two-sided alpha 0.05. Exact treated/control pairs are in matched_treated_control_pairs.csv. A hierarchical estimator, CI method, and stopping rule must be finalized only after negative-control readiness and outcome-blind simulation are executable. This stage did not run any effect analysis.
""")
S={'readiness':decision,'primary_treated_episodes':int(len(a)),'priority_A_controls':nA,'matched_clean_controls':nB,'without_control':n0,'independent_negative_control_episodes':nctrl,'treated_user_candidates':int(to[to.role=='USER'].ip.nunique()),'treated_network_candidates':int(to[to.role=='NETWORK'].ip.nunique()),'control_user_candidates':int(co[co.role=='USER'].ip.nunique()),'control_network_candidates':int(co[co.role=='NETWORK'].ip.nunique()),'common_support_strata':shared,'baseline_common_support_available':bool(len(sup) and pd.DataFrame(sup).overlap_exists.any()),'hierarchical_power_delta_rd_005':None,'type1_error_delta0':None,'ci_coverage_95':None,'loso_min_power':None,'max_episode_information_share':None,'max_oblast_information_share':None,'max_asn_information_share':None,'recommended_estimator':'Not frozen; hierarchical simulation blocked because negative-control nuisance/outcome data are not yet estimable','largest_limitation':'No outcome-blind negative-control loss process is available, so hierarchical power, Type-I error and CI coverage cannot be estimated without observing role outcomes.','sap_freeze_ready':False,'effect_analysis_run':False}
(O/'design_readiness_decision.json').write_text(json.dumps(S,indent=2,default=str));(O/'config_snapshot.json').write_text(json.dumps({'analysis':'endpoint_role_negative_control_v1','priority_A_statuses':sorted(ast),'priority_B_rule':'same state label, same weekday, same 2-hour slot, nearest complete clean cycle','role_definition':'reused from endpoint_role_feasibility_v1','baseline_days':7,'transition_buffer_hours':6,'seosi_delta_rd':.05,'deltas':[0,.03,.05,.075,.10],'alpha':.05,'target_power':.8,'frontline':'reused predeclared non-frontline primary','effect_analysis_run':False},indent=2))
(O/'NEGATIVE_CONTROL_DESIGN_REPORT.md').write_text(f"""# Negative-control construction and design audit

## Readiness: {decision}

This stage is outcome-blind. No USER-vs-NETWORK affected-rate, RD, RR, OR, Delta_RD, H1-H4, Activity, Sensitivity or causal analysis was run.

Frozen definitions were reused from endpoint_role_feasibility_v1. The registry contains {len(a)} primary treated episodes. Deterministic Priority A matching found {nA}; Priority B clean-cycle matching found {nB}; {n0} treated episodes have no control. Independent control episodes: {nctrl}. Shared role strata in the design audit: {shared}.

The cancellation registry is traceable and contains source URLs and evidence grades. However, the future interaction estimand cannot yet be simulated hierarchically: no outcome-blind negative-control loss process or estimable nuisance parameters are available. Therefore power, empirical Type-I error and 95% CI coverage are intentionally reported as not estimable, rather than inferred from treated outcomes or filled with optimistic assumptions.

The design is **{decision}**, not a formal effect result. Do not change roles, events, SESOI, baseline, matching rule or population to rescue readiness.
""")
P=['commit='+subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'branch='+subprocess.check_output(['git','rev-parse','--abbrev-ref','HEAD'],text=True).strip(),'effect_analysis_run=False','role_source='+str(R/'feasibility_imc2027_v3/outputs/tables/ip_role_candidate_master.parquet')+' sha256='+H(R/'feasibility_imc2027_v3/outputs/tables/ip_role_candidate_master.parquet'),'schedule_source='+str(R/'config/planned_outage_schedule_v4_0.csv')+' sha256='+H(R/'config/planned_outage_schedule_v4_0.csv')]
(O/'provenance_and_hashes.txt').write_text('\\n'.join(P)+'\\n')
print(json.dumps(S,indent=2,default=str))
