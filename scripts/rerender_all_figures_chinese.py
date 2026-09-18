#!/usr/bin/env python3
"""Re-render frozen H1--H4/Stage2/aggregate plots with Chinese in-plot labels.

Only the frozen CSV/Parquet tables are read. Matplotlib label methods are
translated at render time; no observations, grouping, estimates, or tests are
changed. Aug26 has a dedicated full redraw in render_aug26_chinese_full.py.
"""
from pathlib import Path
from types import SimpleNamespace
import shutil, sys, re
import numpy as np, pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.text import Text

ROOT=Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
PKG=ROOT/'paper_final_assets_20260912_bilingual'
TMP=ROOT/'_bilingual_rerender_tmp'
FONT='/usr/share/fonts/wqy-microhei/wqy-microhei.ttc'
FP=FontProperties(fname=FONT)
plt.rcParams['font.family']=FP.get_name(); plt.rcParams['axes.unicode_minus']=False

SUB={
 'Endpoint response loss is distributed across IPs, not a single common drop':'端点响应损失分布于多个 IP，而非统一下降',
 'Activity stratification describes, but does not redefine, endpoint outcomes':'Activity 分层用于描述端点结果，不重新定义端点结果',
 'Within-event heterogeneity summary':'单次事件内异质性总结',
 'Cross-event repeatability':'跨攻击事件重复性',
 'Aggregate IPS loss does not determine the endpoint distribution':'聚合 IPS 损失不能决定端点损失分布',
 'held-out attack reach loss is not monotonic across Sensitivity quintiles':'留出攻击的可达性损失不随 Sensitivity 五分位单调变化',
 'Q5 − Q1 effect by held-out attack (95% CI)':'各留出攻击的 Q5−Q1 效应（95% 置信区间）',
 'Continuous Sensitivity and war-attack reach loss':'连续 Sensitivity 与战争攻击可达性损失',
 'State/event-equal severe degradation risk by quintile':'按州/事件等权的严重退化风险',
 'Mean reach drop by held-out attack and Sensitivity quintile':'各留出攻击与 Sensitivity 五分位的平均可达性下降',
 'Within-Activity reach loss across Sensitivity quintiles':'控制 Activity 后各 Sensitivity 五分位的可达性损失',
 'Activity adjustment changes the Q5 − Q1 association':'Activity 调整改变 Q5−Q1 关联',
 'Activity-adjusted effect by held-out attack (95% CI)':'各留出攻击的 Activity 调整效应（95% 置信区间）',
 'Activity-adjusted reach drop by attack and Sensitivity quintile':'各攻击与 Sensitivity 五分位的 Activity 调整后可达性下降',
 'Continuous Sensitivity association after Activity adjustment':'Activity 调整后的连续 Sensitivity 关联',
 'State-event effect distribution':'州-事件效应分布',
 'Sensitivity population vs signed loss contribution':'Sensitivity 人口占比与有符号损失贡献',
 'Sensitivity contribution lift':'Sensitivity 损失贡献提升',
 'Activity contribution lift':'Activity 损失贡献提升',
 'Activity × Sensitivity contribution lift':'Activity × Sensitivity 损失贡献提升',
 'Sensitivity contribution contrast by event':'各攻击事件的 Sensitivity 贡献对比',
 'Gross positive loss concentration':'正向损失集中性',
 'Normal-period IP Activity is heterogeneous':'正常时期 IP Activity 存在明显异质性',
 'Activity spans the full response-fraction range':'Activity 覆盖完整响应比例范围',
 'Within-oblast Activity deciles are balanced':'州内 Activity 十分位划分平衡',
 'UTC 2-hour measurement cycle':'UTC 2 小时测量周期',
 'Activity / S_i':'Activity / S_i', 'Frozen Activity decile (D1 = lowest)':'冻结的 Activity 十分位（D1 为最低）',
 'Frozen Sensitivity quintile':'冻结的 Sensitivity 五分位', 'Reach drop (pre − attack)':'可达性下降（攻击前−攻击期间）',
 'reach drop':'可达性下降', 'IP count':'IP 数量', 'Population share':'人口占比',
 'Signed loss contribution':'有符号损失贡献', 'Signed contribution lift':'有符号贡献提升',
 'Cumulative gross-loss share':'累计正向损失占比', 'Top endpoints by gross positive loss (%)':'按正向损失排序的前若干端点（%）',
 'State/event count':'州-事件数量', 'Mean reach drop':'平均可达性下降', 'Partial Spearman ρ':'偏 Spearman ρ',
 'Q5 − Q1 mean reach-drop':'Q5−Q1 平均可达性下降', 'Q5 − Q1 mean reach drop':'Q5−Q1 平均可达性下降',
 'Q5 − Q1 mean reach-drop (state equal)':'Q5−Q1 平均可达性下降（州等权）',
 'unadjusted':'未调整', 'Activity-adjusted':'Activity 调整后', 'Activity-adjusted':'Activity 调整后',
 'Frozen continuous Sensitivity $S_i$':'冻结的连续 Sensitivity $S_i$',
 'State-event Activity-adjusted Q5 − Q1 effect':'州-事件 Activity 调整后的 Q5−Q1 效应',
 'endpoint median reach drop (IQR)':'端点可达性下降中位数（IQR）', 'aggregate IPS drop':'聚合 IPS 下降',
 'Population share':'人口占比', 'Share':'占比', 'ECDF':'经验累积分布',
 'attack event':'攻击事件', 'held-out attack':'留出攻击', 'State-level':'州级',
 'State-level Activity effect':'州级 Activity 效应', 'State-level Sensitivity effect':'州级 Sensitivity 效应',
 'within state':'州内', 'Raw':'未调整', 'Activity-adjusted':'Activity 调整后',
 'event-level 95% interval':'事件级 95% 区间', 'mean endpoint reach drop':'端点平均可达性下降',
 'median':'中位数', 'pre − attack':'攻击前−攻击期间', 'pre - attack':'攻击前−攻击期间',
}
CN={'Volyn':'沃伦','Zaporizhzhia':'扎波罗热','Cherkasy':'切尔卡瑟','Kirovohrad':'基洛沃格勒','Sumy':'苏梅','Mykolaiv':'尼古拉耶夫','Lviv':'利沃夫','Poltava':'波尔塔瓦','Rivne':'罗夫诺','Odesa':'敖德萨','Zakarpattia':'外喀尔巴阡','Khmelnytskyi':'赫梅利尼茨基','Ternopil':'捷尔诺波尔','Ivano-Frankivsk':'伊万诺-弗兰科夫斯克','Zhytomyr':'日托米尔','Kyiv City':'基辅市','Kyiv':'基辅','Chernihiv':'切尔尼戈夫','Vinnytsia':'文尼察','Luhansk':'卢甘斯克','Kharkiv':'哈尔科夫','Donetsk':'顿涅茨克','Dnipropetrovsk':'第聂伯罗','Chernivtsi':'切尔诺夫策','Crimea':'克里米亚','Sevastopol':'塞瓦斯托波尔','Kherson':'赫尔松'}

def tr(x):
    if not isinstance(x,str): return x
    y=x
    # Human-readable Chinese event labels in panel titles; keep IDs in data
    # files untouched and only translate them at display time.
    m=re.fullmatch(r'(\d{2})(\d{2})_(ATTACK|SUMY)', y)
    if m:
        month, day, kind = m.groups()
        label = '攻击' if kind == 'ATTACK' else '苏梅事件'
        return f'{int(month)}月{int(day)}日{label}'
    for a,b in SUB.items(): y=y.replace(a,b)
    for a,b in CN.items(): y=y.replace(a+' Oblast',b).replace(a,b)
    return y

_st=Axes.set_title; _xl=Axes.set_xlabel; _yl=Axes.set_ylabel; _xt=Axes.set_xticks; _yt=Axes.set_yticks; _lg=Axes.legend; _tx=Axes.text; _an=Axes.annotate; _su=Figure.suptitle; _tset=Text.set_text
def set_title(self,label,*a,**k): k.setdefault('fontproperties',FP); return _st(self,tr(label),*a,**k)
def set_xlabel(self,label,*a,**k): k.setdefault('fontproperties',FP); return _xl(self,tr(label),*a,**k)
def set_ylabel(self,label,*a,**k): k.setdefault('fontproperties',FP); return _yl(self,tr(label),*a,**k)
def ticks(fn):
    def w(self,ticks,labels=None,*a,**k):
        if labels is not None: labels=[tr(x) for x in labels]
        out=fn(self,ticks,labels,*a,**k) if labels is not None else fn(self,ticks,*a,**k)
        for z in self.get_xticklabels()+self.get_yticklabels(): z.set_fontproperties(FP)
        return out
    return w
def legend(self,*a,**k):
    out=_lg(self,*a,**k)
    if out:
        for t in out.get_texts(): t.set_text(tr(t.get_text())); t.set_fontproperties(FP)
    return out
def text(self,x,y,s,*a,**k): k.setdefault('fontproperties',FP); return _tx(self,x,y,tr(s),*a,**k)
def annotate(self,s,xy,*a,**k): k.setdefault('fontproperties',FP); return _an(self,tr(s),xy,*a,**k)
def suptitle(self,t,*a,**k): k.setdefault('fontproperties',FP); return _su(self,tr(t),*a,**k)
def tset(self,s):
    out = _tset(self,tr(s))
    try: self.set_fontproperties(FP)
    except Exception: pass
    return out
Axes.set_title=set_title; Axes.set_xlabel=set_xlabel; Axes.set_ylabel=set_ylabel; Axes.set_xticks=ticks(_xt); Axes.set_yticks=ticks(_yt); Axes.legend=legend; Axes.text=text; Axes.annotate=annotate; Figure.suptitle=suptitle
Text.set_text=tset

def copy_new(src_dir, dst_dir, names):
    for name in names:
        for ext in ('.png','.pdf','.svg'):
            p=src_dir/(name+ext)
            if p.exists(): shutil.copy2(p,dst_dir/(name+ext))

def render_manual_aggregate_zh():
    """Render the aggregate IPS/FBS panel with readable full Chinese labels.

    The upstream paper renderer uses a compact fixed height that is suitable
    for English state names, but makes 25 Chinese oblast labels collide.  This
    replacement reads the same frozen figure-data CSV and changes only the
    canvas/layout and labels; it does not recompute any signal or threshold.
    """
    p = ROOT/'runs/doc_complete_20260908/results/figure_data/fig02_ips_fbs_oblast_time.csv'
    d = pd.read_csv(p)
    d['measure_time'] = pd.to_datetime(d['measure_time'], utc=True)
    d['admin1_base'] = d['admin1'].astype(str).str.replace(' Oblast','',regex=False)
    states = sorted(d['admin1_base'].dropna().unique().tolist())
    state_y = {s:i for i,s in enumerate(states)}
    times = sorted(d['measure_time'].dropna().unique())
    time_x = {t:i for i,t in enumerate(times)}
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 10.5), sharex=True,
                             gridspec_kw={'hspace':0.10})
    panels = [('ips_outage','IPS 异常','#D55E00'),
              ('fbs_outage','FBS 异常','#009E73')]
    for ax, (flag, ylabel, color) in zip(axes, panels):
        mask = d[flag].fillna(False).astype(bool) if flag in d else pd.Series(False,index=d.index)
        for _, row in d.loc[mask].iterrows():
            s = row['admin1_base']
            t = row['measure_time']
            if s in state_y and t in time_x:
                y = state_y[s]
                ax.vlines(time_x[t], y-0.38, y+0.38, color=color, lw=0.75)
        ax.set_facecolor('#eeeeee')
        ax.set_ylim(-0.6, len(states)-0.4)
        ax.set_yticks(range(len(states)))
        ax.set_yticklabels([CN.get(s,s) for s in states], fontproperties=FP, fontsize=7)
        ax.set_ylabel(ylabel, fontproperties=FP, fontsize=10)
        ax.grid(axis='x', color='white', lw=0.6)
        ax.tick_params(axis='y', length=3, pad=3)
        ax.tick_params(axis='x', labelsize=8)
        for tick in ax.get_xticklabels(): tick.set_fontproperties(FP)
    # Keep the time axis in UTC and let matplotlib choose legible date ticks.
    step = max(1, len(times)//10)
    ticks = list(range(0, len(times), step))
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels([pd.Timestamp(times[i]).strftime('%Y-%m-%d') for i in ticks],
                             rotation=35, ha='right', fontproperties=FP, fontsize=8)
    axes[-1].set_xlabel('UTC 2 小时测量周期', fontproperties=FP, fontsize=10)
    fig.suptitle('按州聚合的 IPS 与 FBS 网络异常', fontproperties=FP, fontsize=13, y=0.995)
    fig.text(0.01, 0.5, '州', rotation=90, va='center', ha='center', fontproperties=FP, fontsize=10)
    fig.subplots_adjust(left=0.19, right=0.99, top=0.96, bottom=0.10)
    out = PKG/'figures_main/zh'
    out.mkdir(parents=True, exist_ok=True)
    fig.savefig(out/'01_aggregate_ips_fbs.png', dpi=300, bbox_inches='tight')
    fig.savefig(out/'01_aggregate_ips_fbs.pdf', bbox_inches='tight')
    fig.savefig(out/'01_aggregate_ips_fbs.svg', bbox_inches='tight')
    plt.close(fig)

def main():
    if TMP.exists(): shutil.rmtree(TMP)
    TMP.mkdir()
    for name in ('h1','h2','h3','h4','s2'):
        (TMP/name).mkdir(parents=True)
    (TMP/'s2/figures').mkdir(parents=True)
    (TMP/'s2/figure_data').mkdir(parents=True)
    sys.path.insert(0,str(ROOT/'src'))
    # H1
    import uresil.h1_endpoint_heterogeneity as h1
    h1d=ROOT/'runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity'; ev=pd.read_csv(h1d/'h1_event_summary.csv'); acts=pd.read_csv(h1d/'h1_activity_decile_summary.csv'); rep=pd.read_csv(h1d/'h1_repeatability.csv'); allout=pd.read_parquet(h1d/'h1_ip_level_outcomes.parquet'); h1._figures(None,TMP/'h1',ev.event_id.tolist(),ev,acts,rep,allout)
    copy_new(TMP/'h1/figures',PKG/'figures_appendix/zh',['H1-1_endpoint_reach_drop_distribution','H1-2_activity_decile_response','H1-3_within_event_heterogeneity','H1-4_cross_event_repeatability','H1-5_aggregate_vs_endpoint_distribution'])
    # H2
    import uresil.h2_sensitivity_external_validity as h2
    h2d=ROOT/'runs/h2_sensitivity_external_validity_20260910/results/stages/stage_h2_sensitivity_external_validity'; se=pd.read_csv(h2d/'h2_state_event_summary.csv'); ef=pd.read_csv(h2d/'h2_event_effects.csv'); cont=pd.read_csv(h2d/'h2_continuous_sensitivity.csv'); bins=pd.DataFrame(columns=['bin','sensitivity','reach_drop']); h2._figures(TMP/'h2',se,ef,bins,pd.DataFrame())
    copy_new(TMP/'h2/figures',PKG/'figures_appendix/zh',['H2-1_quintile_gradient','H2-2_event_effects','H2-3_continuous_sensitivity','H2-4_severe_risk','H2-5_event_quintile_heatmap'])
    # H3
    import uresil.h3_activity_conditional_sensitivity as h3
    h3d=ROOT/'runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity'; q=pd.read_csv(h3d/'h3_main_adjusted_quintile_summary.csv'); e3=pd.read_csv(h3d/'h3_event_adjusted_effects.csv'); p=pd.read_csv(h3d/'h3_partial_spearman.csv'); st=pd.read_csv(h3d/'h3_state_event_adjusted_effects.csv'); cmp=pd.read_csv(h3d/'h3_h2_vs_h3_comparison.csv').iloc[0]; h3.figures(TMP/'h3',q,e3,p,st,float(cmp.h2_effect),float(cmp.h3_effect))
    copy_new(TMP/'h3/figures',PKG/'figures_appendix/zh',['H3-1_adjusted_gradient','H3-2_h2_vs_h3','H3-3_event_effects','H3-4_event_quintile_heatmap','H3-5_partial_spearman','H3-6_state_event_effect_distribution'])
    # H4
    import uresil.h4_loss_contribution_decomposition as h4
    h4d=ROOT/'runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition'; sens=pd.read_csv(h4d/'h4_sensitivity_summary.csv'); act=pd.read_csv(h4d/'h4_activity_summary.csv'); combo=pd.read_csv(h4d/'h4_activity_sensitivity_summary.csv'); e4=pd.read_csv(h4d/'h4_event_effects.csv'); conc=pd.read_csv(h4d/'h4_concentration.csv'); h4.figures(TMP/'h4',sens,act,combo,e4,conc)
    copy_new(TMP/'h4/figures',PKG/'figures_appendix/zh',['H4-1_population_vs_loss','H4-2_sensitivity_lift','H4-3_activity_lift','H4-4_activity_sensitivity_heatmap','H4-5_event_q5_vs_q1','H4-6_lorenz_concentration'])
    # Stage2 Activity: use existing frozen table and the module's figure function.
    import uresil.activity_stage as ast
    aroot=ROOT/'runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity'; ad=pd.read_csv(aroot/'tables/ip_activity.csv'); cfg=SimpleNamespace(figures={'png_dpi':300}); ast._figures(cfg,TMP/'s2',ad,sorted(ad.target_admin1.dropna().unique()))
    copy_new(TMP/'s2/figures',PKG/'figures_appendix/zh',['fig_S2_1_activity_ecdf','fig_S2_2_activity_histogram','fig_S2_3_activity_decile_share','fig_S2_4_activity_by_oblast','fig_S2_5_activity_estimable_coverage'])
    # Canonical IPS/FBS figure: render directly from its frozen figure-data CSV.
    import uresil.viz.paper_figures as pf
    class PaperCfg:
        figures={'png_dpi':300,'double_column_width_in':7.16,'single_column_width_in':3.5,'base_font_size_pt':9,'min_font_size_pt':7}
        def out_dir(self,key,ensure=False):
            p = ROOT/'runs/doc_complete_20260908/results/figure_data' if key == 'results_figure_data' else TMP/'paper_figures'
            if ensure: p.mkdir(parents=True,exist_ok=True)
            return p
    pc=PaperCfg(); pf.render(pc,lang='zh')
    copy_new(TMP/'paper_figures',PKG/'figures_main/zh',['fig02_ips_fbs_oblast_time'])
    for ext in ('.png','.pdf','.svg'):
        p=PKG/'figures_main/zh'/('fig02_ips_fbs_oblast_time'+ext)
        if p.exists(): shutil.copy2(p,PKG/'figures_main/zh'/('01_aggregate_ips_fbs'+ext))
        p=PKG/'figures_appendix/zh'/('fig_S2_1_activity_ecdf'+ext)
        if p.exists(): shutil.copy2(p,PKG/'figures_main/zh'/('02_activity_distribution'+ext))
    render_manual_aggregate_zh()
    print('rerendered frozen H1/H2/H3/H4/Stage2/aggregate Chinese figures')

if __name__=='__main__': main()
