"""Write the frozen, downstream-only final experiment synthesis after H4."""
from __future__ import annotations
import hashlib, json, os
from pathlib import Path
import pandas as pd

def sha256(p:Path):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()

def run(root:Path,h4_dir:Path,h1_report:Path,h2_report:Path,h3_report:Path,git_commit:str,run_id='final_experiment_synthesis_20260911'):
    out=root/'runs'/run_id/'results'/'final_synthesis'; out.mkdir(parents=True,exist_ok=True)
    h4=json.loads((h4_dir/'h4_manifest.json').read_text())
    q=pd.read_csv(h4_dir/'h4_sensitivity_summary.csv').set_index('quintile'); a=pd.read_csv(h4_dir/'h4_activity_summary.csv'); ce=pd.read_csv(h4_dir/'h4_concentration.csv')
    q1,q5=q.loc['Q1'],q.loc['Q5']; topa=a.sort_values('loss_contribution_share',ascending=False).iloc[0]
    top={f'top{int(r.top_fraction*100)}':float(r.gross_loss_share) for _,r in ce[ce.top_fraction.notna()].iterrows()}
    h4ver=h4['h4_verdict']; h4dir=pd.read_csv(h4_dir/'h4_event_effects.csv'); q5n=int(h4dir.q5_or_d10_lift.gt(h4dir.q1_or_d1_lift).sum())
    combo=pd.read_csv(h4_dir/'h4_activity_sensitivity_summary.csv')
    combo_q5=float(combo.loc[combo.quintile.eq('Q5'),'contribution_lift'].mean())
    combo_q1=float(combo.loc[combo.quintile.eq('Q1'),'contribution_lift'].mean())
    rows=[
      {'hypothesis':'H1','verdict':'SUPPORTED','key_effect':'Endpoint reach loss is heterogeneous across IPs; cross-event ranking repeatability is weak.','source':str(h1_report)},
      {'hypothesis':'H2','verdict':'PARTIALLY_SUPPORTED','key_effect':'Q5-Q1=0.0102; 95% CI [0.0005,0.0213]; severe RR=1.069 [1.005,1.150]; Q5>Q1 in 4/6; event-equal Spearman=-0.0018.','source':str(h2_report)},
      {'hypothesis':'H3','verdict':'NOT_SUPPORTED','key_effect':'Activity-adjusted Q5-Q1=-0.0005; 95% CI [-0.0083,0.0071]; partial Spearman=0.0001; Q5>Q1 in 1/6.','source':str(h3_report)},
      {'hypothesis':'H4','verdict':h4ver,'key_effect':f'Q5 signed contribution lift={q5.contribution_lift:.4f} vs Q1={q1.contribution_lift:.4f}; Q5>Q1 in {q5n}/6 events; top Activity group={topa.activity_decile}.','source':str(h4_dir/'H4_LOSS_CONTRIBUTION_REPORT.md')},
    ]
    pd.DataFrame(rows).to_csv(out/'FINAL_HYPOTHESIS_TABLE.csv',index=False)
    lines=['# Final experiment synthesis','', 'This closure report reads only frozen Stage 0–4.5 and H1–H4 artifacts. It does not modify or rerun upstream stages.','', '## Frozen main panel',f"- Label: **AUGMENTED_STRICT_SUPPORT3**; valid IPs **{h4['valid_ip_n']:,}**; states **{h4['valid_state_n']}**; endpoint-event rows **{h4['valid_endpoint_event_rows']:,}**.",f"- H4 verdict: **{h4ver}**.",'', '## H1–H4 verdicts','',pd.DataFrame(rows)[['hypothesis','verdict','key_effect']].to_string(index=False),'', '## H4 headline values',f"- Q1: population share **{q1.population_share:.4f}**, signed loss share **{q1.loss_contribution_share:.4f}**, lift **{q1.contribution_lift:.4f}**.",f"- Q5: population share **{q5.population_share:.4f}**, signed loss share **{q5.loss_contribution_share:.4f}**, lift **{q5.contribution_lift:.4f}**; Q5/Q1 lift ratio **{q5.contribution_lift/q1.contribution_lift:.4f}**.",f"- Q5 exceeds Q1 in **{q5n}/6** events.",f"- Largest Activity decile: **{topa.activity_decile}**; population share **{topa.population_share:.4f}**, loss share **{topa.loss_contribution_share:.4f}**, lift **{topa.contribution_lift:.4f}**.",f"- Activity-composition check: Sensitivity Q5 lift **{combo_q5:.4f}** vs Q1 **{combo_q1:.4f}**.",f"- Gross positive loss concentration: top 10/20/50% endpoints account for **{top.get('top10',float('nan')):.4f} / {top.get('top20',float('nan')):.4f} / {top.get('top50',float('nan')):.4f}**.",'', '## Five-sentence scientific conclusion','', '1. War-related Internet reach loss is strongly heterogeneous at the endpoint level, rather than a uniform state-wide response.', '2. Endpoint rankings are not reliably repeated across attacks, so a single static vulnerability ordering is not supported.', '3. Planned-outage-associated Sensitivity shows a small positive unadjusted association with attack loss, but the association largely disappears after controlling for normal Activity.', '4. H4 shows that loss contribution is concentrated in endpoint populations, with the observed concentration and Activity gradient reported as descriptive decomposition rather than causal attribution.', '5. The defensible scientific story is therefore an activity- and event-conditioned pattern of endpoint disruption, not proof that planned outages identify intrinsically vulnerable IPs.','', '## Unsupported claims','', '- The results do not establish that planned outages cause war-time outages, that Sensitivity is an intrinsic vulnerability trait, or that any subgroup causes an outage.','', '## Paper-level assessment','', 'A. The original positive “stable-IP vulnerability score” loop is **not fully supported**: H2 is partial and H3 is negative.', 'B. A publishable alternative is a careful endpoint-heterogeneity and measurement-decomposition story with explicit negative results.', 'C. Strongest findings: endpoint-level heterogeneity; weak cross-event rank repeatability; Activity-adjustment erases the apparent Sensitivity gradient.', 'D. Main limitations: sparse/seasonally concentrated calibration evidence; geographic and acquisition confounding; incomplete causal identification and event-specific support.', 'E. Main figures: H1 endpoint heterogeneity, H2/H3 contrast, H4 contribution decomposition. Appendix: frozen-label coverage, robustness, concentration and audit tables. Negative-result/limitation section: H3 null and cross-event instability.','']
    (out/'FINAL_EXPERIMENT_SYNTHESIS.md').write_text('\n'.join(lines),encoding='utf-8')
    manifest={'stage':'FINAL_EXPERIMENT_SYNTHESIS','run_id':run_id,'git_commit':git_commit,'h4_manifest_sha256':sha256(h4_dir/'h4_manifest.json'),'h1_report_sha256':sha256(h1_report) if h1_report.exists() else None,'h2_report_sha256':sha256(h2_report) if h2_report.exists() else None,'h3_report_sha256':sha256(h3_report) if h3_report.exists() else None,'upstream_manifest_hashes':{k:v.get('sha256') for k,v in h4.get('upstream_manifests',{}).items()},'h4_verdict':h4ver,'upstream_rerun':False,'main_label':'AUGMENTED_STRICT_SUPPORT3','support_threshold':3,'random_seed':20260911,'github_push_status':'failed_no_remote'}
    (out/'FINAL_EXPERIMENT_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return {'output_dir':str(out),'h4_verdict':h4ver,'q1_lift':float(q1.contribution_lift),'q5_lift':float(q5.contribution_lift),'top_activity':topa.activity_decile,'concentration':top}

def main(argv=None):
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument('--root',default='/home/wsl/XiaoLunWen_doc_complete_20260908'); ap.add_argument('--h4-dir',required=True); ap.add_argument('--h1-report',required=True); ap.add_argument('--h2-report',required=True); ap.add_argument('--h3-report',required=True); ap.add_argument('--git-commit',default=os.environ.get('GIT_COMMIT','unknown')); a=ap.parse_args(); print(json.dumps(run(Path(a.root),Path(a.h4_dir),Path(a.h1_report),Path(a.h2_report),Path(a.h3_report),a.git_commit),indent=2))
if __name__=='__main__': main()
