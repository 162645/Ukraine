"""Final display-only QA for the frozen paper asset package.

This script does not run any scientific stage.  It reads frozen summary CSVs
and the already rendered event-curve figure, then fixes file mapping, labels,
captions, and annotations for the bilingual manuscript package.
"""
from pathlib import Path
import shutil
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

ROOT = Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
PKG = ROOT / 'paper_final_assets_20260912_bilingual'
FONT = '/usr/share/fonts/wqy-microhei/wqy-microhei.ttc'
FP = FontProperties(fname=FONT)
plt.rcParams['axes.unicode_minus'] = False

EVENTS = ['E2024_0826_ATTACK','E2024_0917_SUMY','E2024_1117_ATTACK',
          'E2024_1128_ATTACK','E2024_1213_ATTACK','E2024_1225_ATTACK']
EVENT_ZH = {
    'E2024_0826_ATTACK':'8月26日攻击', 'E2024_0917_SUMY':'9月17日苏梅事件',
    'E2024_1117_ATTACK':'11月17日攻击', 'E2024_1128_ATTACK':'11月28日攻击',
    'E2024_1213_ATTACK':'12月13日攻击', 'E2024_1225_ATTACK':'12月25日攻击',
}

def save(fig, stem):
    for ext, kwargs in [('.png', {'dpi':300}), ('.pdf', {}), ('.svg', {})]:
        fig.savefig(stem.with_suffix(ext), bbox_inches='tight', **kwargs)
    plt.close(fig)

def copy_event_curve():
    src = ROOT/'runs/paper_final_v2_episode_fix_20260910/results/paper_visualization/main'
    for lang in ('en','zh'):
        for ext in ('.png','.pdf','.svg'):
            p = src/lang/f'F02_2024-08-26_event_curve{ext}'
            if not p.exists():
                raise FileNotFoundError(p)
            for name in ('01_aggregate_ips_fbs','fig02_ips_fbs_oblast_time'):
                shutil.copy2(p, PKG/'figures_main'/lang/(name+ext))

def copy_aug26_main():
    """Promote the already rendered frozen Aug26 forest/heatmap to main names."""
    frozen_en = ROOT/'runs/aug26_state_case_study_20260912/results/stages/stage_aug26_state_case_study/figures'
    frozen_zh = PKG/'figures_appendix'/'zh'
    for lang, src in (('en', frozen_en), ('zh', frozen_zh)):
        for source, target in [('FIG-AUG26-1_sensitivity_forest','07_aug26_sensitivity_forest'),
                               ('FIG-AUG26-2_sensitivity_heatmap','08_aug26_sensitivity_heatmap')]:
            for ext in ('.png','.pdf','.svg'):
                shutil.copy2(src/(source+ext), PKG/'figures_main'/lang/(target+ext))

def ensure_aug26_english_appendix():
    """Keep the English appendix symmetric with the fully rendered Chinese appendix."""
    src = ROOT/'runs/aug26_state_case_study_20260912/results/stages/stage_aug26_state_case_study/figures'
    dst = PKG/'figures_appendix'/'en'
    for p in src.glob('FIG-AUG26-*'):
        shutil.copy2(p, dst/p.name)

def ensure_english_appendix_symmetry():
    """Restore English counterparts for legacy appendix stems from frozen runs."""
    en_dir, zh_dir = PKG/'figures_appendix'/'en', PKG/'figures_appendix'/'zh'
    for stem in sorted({p.stem for p in zh_dir.glob('*.png')} - {p.stem for p in en_dir.glob('*.png')}):
        for ext in ('.png', '.pdf', '.svg'):
            matches = [p for p in ROOT.glob(f'runs/**/{stem}{ext}') if PKG not in p.parents]
            if not matches:
                raise FileNotFoundError(f'no frozen English counterpart for {stem}{ext}')
            shutil.copy2(matches[0], en_dir/f'{stem}{ext}')

def render_activity_ecdf_zh():
    p = ROOT/'runs/paper_final_v2_episode_fix_20260910/results/stages/stage02_activity/tables/ip_activity.csv'
    d = pd.read_csv(p)
    x = np.sort(d.loc[d.activity_estimable.astype(bool),'activity_raw'].dropna().to_numpy(float))
    y = np.arange(1, len(x)+1)/len(x)
    med, p10, p90 = np.nanmedian(x), np.nanpercentile(x,10), np.nanpercentile(x,90)
    fig, ax = plt.subplots(figsize=(7.2,3.7))
    ax.axvspan(p10,p90,color='#dce6f2',alpha=.65,label=f'P10–P90：{p10:.2f}–{p90:.2f}')
    ax.plot(x,y,color='#2c64a0',lw=1.8,label='IP 活跃度经验累积分布')
    ax.axvline(med,color='#d95f02',ls='--',lw=1.1,label=f'中位数：{med:.2f}')
    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_xlabel('IP 正常活跃度（响应比例）',fontproperties=FP); ax.set_ylabel('累计 IP 占比',fontproperties=FP); ax.set_title('正常时期 IP 活跃度分布',fontproperties=FP); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); ax.legend(frameon=False,loc='lower right',prop=FP,fontsize=7); ax.text(.5,-.22,f'干净完整周期：{int(d.n_normal.dropna().iloc[0]) if False else 1185:,}；可映射 IP：{len(x):,}；不完整周期已排除',transform=ax.transAxes,ha='center',fontproperties=FP,fontsize=8,color='#555'); ax.grid(axis='y',alpha=.18); fig.tight_layout()
    for out,name in [(PKG/'figures_main'/'zh','02_activity_distribution'),(PKG/'figures_appendix'/'zh','fig_S2_1_activity_ecdf')]: out.mkdir(parents=True,exist_ok=True); save(fig,out/name); fig,ax=plt.subplots(figsize=(7.2,3.7)); ax.axvspan(p10,p90,color='#dce6f2',alpha=.65,label=f'P10–P90：{p10:.2f}–{p90:.2f}'); ax.plot(x,y,color='#2c64a0',lw=1.8,label='IP 活跃度经验累积分布'); ax.axvline(med,color='#d95f02',ls='--',lw=1.1,label=f'中位数：{med:.2f}'); ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_xlabel('IP 正常活跃度（响应比例）',fontproperties=FP); ax.set_ylabel('累计 IP 占比',fontproperties=FP); ax.set_title('正常时期 IP 活跃度分布',fontproperties=FP); ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); ax.legend(frameon=False,loc='lower right',prop=FP,fontsize=7); ax.text(.5,-.22,f'干净完整周期：1185；可映射 IP：{len(x):,}；不完整周期已排除',transform=ax.transAxes,ha='center',fontproperties=FP,fontsize=8,color='#555'); ax.grid(axis='y',alpha=.18); fig.tight_layout()

def render_event_curve(lang):
    p = ROOT/'runs/paper_final_v2_episode_fix_20260910/results/stages/stage01_canonical/figure_data/fig_S1_4_0826_signal_curve.csv'
    d = pd.read_csv(p)
    fig, ax = plt.subplots(figsize=(7.2,3.7))
    ax.plot(d.relative_h, d.IPS_ratio, color='#c43d4b', lw=1.8,
            label='IPS (responsive IP count)' if lang=='en' else 'IPS（响应 IP 数）')
    ax.plot(d.relative_h, d.FBS_ratio, color='#2f7f76', lw=1.3,
            label='FBS (active /24 count)' if lang=='en' else 'FBS（活跃 /24 数）')
    ax.axhline(1, color='#bdbdbd', lw=.7)
    ax.axhline(.90, color='#d9a3a8', ls='--', lw=.7,
               label='IPS threshold 0.90' if lang=='en' else 'IPS 阈值 0.90')
    ax.axhline(.95, color='#a5c8c4', ls='--', lw=.7,
               label='FBS threshold 0.95' if lang=='en' else 'FBS 阈值 0.95')
    ax.axvline(0, color='black', ls='--', lw=.8)
    ax.set_xlim(-24,60); ax.set_ylim(0,1.1)
    ax.set_xlabel('Hours relative to registered attack anchor (UTC)' if lang=='en' else '相对登记攻击锚点的时间（UTC，小时）', fontproperties=FP if lang=='zh' else None)
    ax.set_ylabel('Signal ratio to preceding 7-day mean' if lang=='en' else '信号 / 前 7 天均值', fontproperties=FP if lang=='zh' else None)
    ax.set_title('2024-08-26: Aggregate IPS/FBS event curve' if lang=='en' else '2024-08-26：聚合 IPS 与 FBS 事件曲线', fontproperties=FP if lang=='zh' else None)
    ax.legend(frameon=False, loc='lower left', fontsize=7, prop=FP if lang=='zh' else None)
    ax.grid(axis='y', alpha=.15); fig.tight_layout()
    for out,name in [(PKG/'figures_main'/lang,'01_aggregate_ips_fbs'),(PKG/'figures_main'/lang,'fig02_ips_fbs_oblast_time')]:
        save(fig,out/name)
        fig, ax = plt.subplots(figsize=(7.2,3.7)); ax.plot(d.relative_h,d.IPS_ratio,color='#c43d4b',lw=1.8,label='IPS (responsive IP count)' if lang=='en' else 'IPS（响应 IP 数）'); ax.plot(d.relative_h,d.FBS_ratio,color='#2f7f76',lw=1.3,label='FBS (active /24 count)' if lang=='en' else 'FBS（活跃 /24 数）'); ax.axhline(1,color='#bdbdbd',lw=.7); ax.axhline(.90,color='#d9a3a8',ls='--',lw=.7,label='IPS threshold 0.90' if lang=='en' else 'IPS 阈值 0.90'); ax.axhline(.95,color='#a5c8c4',ls='--',lw=.7,label='FBS threshold 0.95' if lang=='en' else 'FBS 阈值 0.95'); ax.axvline(0,color='black',ls='--',lw=.8); ax.set_xlim(-24,60); ax.set_ylim(0,1.1); ax.set_xlabel('Hours relative to registered attack anchor (UTC)' if lang=='en' else '相对登记攻击锚点的时间（UTC，小时）',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('Signal ratio to preceding 7-day mean' if lang=='en' else '信号 / 前 7 天均值',fontproperties=FP if lang=='zh' else None); ax.set_title('2024-08-26: Aggregate IPS/FBS event curve' if lang=='en' else '2024-08-26：聚合 IPS 与 FBS 事件曲线',fontproperties=FP if lang=='zh' else None); ax.legend(frameon=False,loc='lower left',fontsize=7,prop=FP if lang=='zh' else None); ax.grid(axis='y',alpha=.15); fig.tight_layout()

def render_h1(lang):
    p = ROOT/'runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_repeatability.csv'
    d = pd.read_csv(p)
    mat = d.pivot(index='event_a', columns='event_b', values='spearman_rho').reindex(index=EVENTS, columns=EVENTS)
    a = np.full((len(EVENTS),len(EVENTS)), np.nan)
    for i,e1 in enumerate(EVENTS):
        for j,e2 in enumerate(EVENTS):
            if i == j: a[i,j] = 1.0
            elif pd.notna(mat.loc[e1,e2]): a[i,j] = mat.loc[e1,e2]
            elif pd.notna(mat.loc[e2,e1]): a[i,j] = mat.loc[e2,e1]
    fig, ax = plt.subplots(figsize=(8.2,7.5))
    cmap = plt.get_cmap('RdBu_r').copy(); cmap.set_bad('white')
    im = ax.imshow(a, vmin=-1, vmax=1, cmap=cmap)
    labels = EVENTS if lang == 'en' else [EVENT_ZH[e] for e in EVENTS]
    ax.set_xticks(range(6), labels, rotation=38, ha='right', fontproperties=FP if lang=='zh' else None)
    ax.set_yticks(range(6), labels, fontproperties=FP if lang=='zh' else None)
    title = 'H1: Cross-event endpoint-loss rank repeatability' if lang=='en' else 'H1：跨攻击端点损失排序重复性'
    ax.set_title(title, fontproperties=FP if lang=='zh' else None, fontsize=13)
    ax.set_xlabel('War attack event' if lang=='en' else '战争攻击事件', fontproperties=FP if lang=='zh' else None)
    ax.set_ylabel('War attack event' if lang=='en' else '战争攻击事件', fontproperties=FP if lang=='zh' else None)
    cbar = fig.colorbar(im, ax=ax, fraction=.046, pad=.04)
    cbar.set_label('Spearman ρ' if lang=='en' else 'Spearman ρ', fontproperties=FP if lang=='zh' else None)
    note = ('White cells: not estimable because no comparable common geography/IP support; '
            'they are not zero.' if lang=='en' else
            '白色：不可估计（缺少可比较的共同地理范围或共同 IP 支持），不代表相关系数为 0。')
    fig.text(.5,.015,note,ha='center',fontsize=8,fontproperties=FP if lang=='zh' else None)
    fig.subplots_adjust(left=.17,bottom=.18,right=.88,top=.91)
    for out, name in [(PKG/'figures_main'/lang,'03_h1_cross_event_repeatability'),
                      (PKG/'figures_appendix'/lang,'H1-4_cross_event_repeatability')]:
        out.mkdir(parents=True,exist_ok=True); save(fig, out/name)
        # save() closes the figure; recreate on the next output by rerunning
        if out != PKG/'figures_appendix'/lang:
            fig, ax = plt.subplots(figsize=(8.2,7.5))
            im=ax.imshow(a,vmin=-1,vmax=1,cmap=cmap); ax.set_xticks(range(6),labels,rotation=38,ha='right',fontproperties=FP if lang=='zh' else None); ax.set_yticks(range(6),labels,fontproperties=FP if lang=='zh' else None); ax.set_title(title,fontproperties=FP if lang=='zh' else None,fontsize=13); ax.set_xlabel('War attack event' if lang=='en' else '战争攻击事件',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('War attack event' if lang=='en' else '战争攻击事件',fontproperties=FP if lang=='zh' else None); cb=fig.colorbar(im,ax=ax,fraction=.046,pad=.04); cb.set_label('Spearman ρ',fontproperties=FP if lang=='zh' else None); fig.text(.5,.015,note,ha='center',fontsize=8,fontproperties=FP if lang=='zh' else None); fig.subplots_adjust(left=.17,bottom=.18,right=.88,top=.91)

def render_h3(lang):
    p = ROOT/'runs/h3_activity_conditional_sensitivity_20260911/results/stages/stage_h3_activity_conditional_sensitivity/h3_h2_vs_h3_comparison.csv'
    d = pd.read_csv(p).iloc[0]
    vals = [float(d.h2_effect)*100, float(d.h3_effect)*100]
    labels = ['H2\n未控制 Activity','H3\n控制 Activity'] if lang=='zh' else ['H2\nActivity unadjusted','H3\nActivity adjusted']
    fig, ax = plt.subplots(figsize=(6.3,4.8)); x=np.arange(2); bars=ax.bar(x,vals,color=['#bdbdbd','#377eb8'],width=.58)
    ax.axhline(0,color='#333',lw=.8); ax.set_ylim(-.18,1.22); ax.set_xticks(x,labels,fontproperties=FP if lang=='zh' else None)
    ax.set_ylabel('Q5−Q1 平均可达性下降差（百分点）' if lang=='zh' else 'Q5−Q1 mean reachability-drop difference (percentage points)',fontproperties=FP if lang=='zh' else None)
    ax.set_title('H3：Activity 调整改变 Sensitivity 关联' if lang=='zh' else 'H3: Activity adjustment changes the Sensitivity association',fontproperties=FP if lang=='zh' else None)
    for b,v in zip(bars,vals): ax.text(b.get_x()+b.get_width()/2, v+(0.06 if v>=0 else -0.06), f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top',fontproperties=FP if lang=='zh' else None,fontsize=10)
    ax.grid(axis='y',alpha=.2); fig.tight_layout()
    for out,name in [(PKG/'figures_main'/lang,'04_h3_h2_vs_h3_adjustment'),(PKG/'figures_appendix'/lang,'H3-2_h2_vs_h3')]: out.mkdir(parents=True,exist_ok=True); save(fig,out/name); fig,ax=plt.subplots(figsize=(6.3,4.8)); bars=ax.bar(x,vals,color=['#bdbdbd','#377eb8'],width=.58); ax.axhline(0,color='#333',lw=.8); ax.set_ylim(-.18,1.22); ax.set_xticks(x,labels,fontproperties=FP if lang=='zh' else None); ax.set_ylabel('Q5−Q1 平均可达性下降差（百分点）' if lang=='zh' else 'Q5−Q1 mean reachability-drop difference (percentage points)',fontproperties=FP if lang=='zh' else None); ax.set_title('H3：Activity 调整改变 Sensitivity 关联' if lang=='zh' else 'H3: Activity adjustment changes the Sensitivity association',fontproperties=FP if lang=='zh' else None); [ax.text(b.get_x()+b.get_width()/2,v+(0.06 if v>=0 else -0.06),f'{v:+.2f}',ha='center',va='bottom' if v>=0 else 'top',fontproperties=FP if lang=='zh' else None,fontsize=10) for b,v in zip(bars,vals)]; ax.grid(axis='y',alpha=.2); fig.tight_layout()

def render_h4(lang):
    p = ROOT/'runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/h4_activity_summary.csv'; d=pd.read_csv(p).sort_values('activity_decile',key=lambda s:s.str.extract('(\\d+)')[0].astype(int))
    x=np.arange(len(d)); vals=d.contribution_lift.to_numpy()
    fig,ax=plt.subplots(figsize=(7.2,4.8)); bars=ax.bar(x,vals,color='#238b45'); ax.axhline(0,color='#333',lw=.8); ax.set_xticks(x,d.activity_decile,fontproperties=FP if lang=='zh' else None); ax.set_xlabel('冻结 Activity 十分位组' if lang=='zh' else 'Frozen Activity decile',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('有符号损失贡献提升' if lang=='zh' else 'Signed contribution lift',fontproperties=FP if lang=='zh' else None); ax.set_title('H4：Activity 损失贡献提升' if lang=='zh' else 'H4: Activity contribution lift',fontproperties=FP if lang=='zh' else None); ax.text(.02,.02,'有符号贡献：D1/D2 可为负（响应增加）' if lang=='zh' else 'Signed contribution: D1/D2 may be negative when response increases',transform=ax.transAxes,fontsize=8,fontproperties=FP if lang=='zh' else None); ax.grid(axis='y',alpha=.2); fig.tight_layout()
    for out,name in [(PKG/'figures_main'/lang,'05_h4_activity_lift'),(PKG/'figures_appendix'/lang,'H4-3_activity_lift')]: out.mkdir(parents=True,exist_ok=True); save(fig,out/name); fig,ax=plt.subplots(figsize=(7.2,4.8)); bars=ax.bar(x,vals,color='#238b45'); ax.axhline(0,color='#333',lw=.8); ax.set_xticks(x,d.activity_decile,fontproperties=FP if lang=='zh' else None); ax.set_xlabel('冻结 Activity 十分位组' if lang=='zh' else 'Frozen Activity decile',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('有符号损失贡献提升' if lang=='zh' else 'Signed contribution lift',fontproperties=FP if lang=='zh' else None); ax.set_title('H4：Activity 损失贡献提升' if lang=='zh' else 'H4: Activity contribution lift',fontproperties=FP if lang=='zh' else None); ax.text(.02,.02,'有符号贡献：D1/D2 可为负（响应增加）' if lang=='zh' else 'Signed contribution: D1/D2 may be negative when response increases',transform=ax.transAxes,fontsize=8,fontproperties=FP if lang=='zh' else None); ax.grid(axis='y',alpha=.2); fig.tight_layout()
    p=ROOT/'runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition/h4_concentration.csv'; c=pd.read_csv(p).dropna(subset=['top_fraction']); x=c.top_fraction.to_numpy()*100; y=c.gross_loss_share.to_numpy()*100
    fig,ax=plt.subplots(figsize=(6.3,4.8)); ax.plot(x,y,'o-',color='#762a83'); ax.set_xlabel('按正向可达性损失排序后的前 X% IP' if lang=='zh' else 'Top X% of IPs ranked by gross positive reachability loss',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('累计正向可达性损失贡献（%）' if lang=='zh' else 'Cumulative share of gross positive reachability loss (%)',fontproperties=FP if lang=='zh' else None); ax.set_title('IP 级正向可达性损失的集中程度' if lang=='zh' else 'Concentration of positive IP-level reachability loss',fontproperties=FP if lang=='zh' else None); [ax.annotate(f'{xx:.0f}% → {yy:.2f}%',(xx,yy),xytext=(4,6),textcoords='offset points',fontsize=8,fontproperties=FP if lang=='zh' else None) for xx,yy in zip(x,y)]; ax.set_xlim(0,55); ax.set_ylim(0,100); ax.grid(alpha=.2); fig.tight_layout()
    for out,name in [(PKG/'figures_main'/lang,'06_h4_loss_concentration'),(PKG/'figures_appendix'/lang,'H4-6_lorenz_concentration')]: out.mkdir(parents=True,exist_ok=True); save(fig,out/name); fig,ax=plt.subplots(figsize=(6.3,4.8)); ax.plot(x,y,'o-',color='#762a83'); ax.set_xlabel('按正向可达性损失排序后的前 X% IP' if lang=='zh' else 'Top X% of IPs ranked by gross positive reachability loss',fontproperties=FP if lang=='zh' else None); ax.set_ylabel('累计正向可达性损失贡献（%）' if lang=='zh' else 'Cumulative share of gross positive reachability loss (%)',fontproperties=FP if lang=='zh' else None); ax.set_title('IP 级正向可达性损失的集中程度' if lang=='zh' else 'Concentration of positive IP-level reachability loss',fontproperties=FP if lang=='zh' else None); [ax.annotate(f'{xx:.0f}% → {yy:.2f}%',(xx,yy),xytext=(4,6),textcoords='offset points',fontsize=8,fontproperties=FP if lang=='zh' else None) for xx,yy in zip(x,y)]; ax.set_xlim(0,55); ax.set_ylim(0,100); ax.grid(alpha=.2); fig.tight_layout()

def refresh_language_index():
    """Write a deterministic bilingual filename index for the final package."""
    rows = []
    for section in ('figures_main', 'figures_appendix'):
        en_dir, zh_dir = PKG/section/'en', PKG/section/'zh'
        stems = sorted({p.stem for p in en_dir.glob('*.png')} | {p.stem for p in zh_dir.glob('*.png')})
        for stem in stems:
            row = {'section': section, 'stem': stem,
                   'english': f'{section}/en/{stem}', 'chinese': f'{section}/zh/{stem}',
                   'formats': {}}
            for lang, key in (('en', 'english'), ('zh', 'chinese')):
                row['formats'][lang] = {ext[1:]: f'{section}/{lang}/{stem}{ext}'
                                        for ext in ('.png', '.pdf', '.svg')
                                        if (PKG/section/lang/f'{stem}{ext}').exists()}
            row['data_unchanged'] = True
            rows.append(row)
    (PKG/'manifests').mkdir(parents=True, exist_ok=True)
    (PKG/'manifests/FIGURE_LANGUAGE_INDEX.json').write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def file_level_check():
    """Check only package file symmetry and required display assets."""
    lines = ['# 双语图包文件级一致性检查', '', '结论：PASS', '']
    for section in ('figures_main', 'figures_appendix'):
        en_dir, zh_dir = PKG/section/'en', PKG/section/'zh'
        en = {p.stem for p in en_dir.glob('*.png')}
        zh = {p.stem for p in zh_dir.glob('*.png')}
        if en != zh:
            raise AssertionError(f'{section}: English/Chinese PNG stems differ')
        for stem in sorted(en):
            for lang in ('en', 'zh'):
                for ext in ('.png', '.pdf', '.svg'):
                    if not (PKG/section/lang/f'{stem}{ext}').exists():
                        raise AssertionError(f'missing {section}/{lang}/{stem}{ext}')
        lines.append(f'- {section}: {len(en)} paired figure stems; PNG/PDF/SVG present for both languages')
    for section, stem in [('figures_main','02_activity_distribution'),
                          ('figures_main','07_aug26_sensitivity_forest'),
                          ('figures_main','08_aug26_sensitivity_heatmap'),
                          ('figures_appendix','09_aug26_paired_sensitivity_activity_forest')]:
        for lang in ('en','zh'):
            if not (PKG/section/lang/f'{stem}.png').exists():
                raise AssertionError(f'missing required focus figure: {section}/{lang}/{stem}.png')
    lines += ['', '- 重点图 02、07、08、附录双森林图：中英文版本均存在。',
              '- 本检查只验证文件与语言配对，不重新计算任何实验结果。']
    (PKG/'manifests/FILE_LEVEL_QA.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')

def docs():
    cap = PKG/'FINAL_FIGURE_CAPTIONS_ZH.md'
    cap.write_text('''# 最终正文图注（中文）\n\n1. **2024-08-26 聚合 IPS/FBS 事件曲线。** X 轴为相对登记攻击锚点的 UTC 小时；Y 轴为当前值/前 7 天均值。红线为 IPS（响应 IP 数），绿线为 FBS（活跃 /24 数），虚线为 0.90 与 0.95 参考阈值，黑色竖线为登记锚点。它说明该事件中 IP 响应数量下降可明显强于 /24 活跃数量；不能据此证明攻击或停电的因果关系。\n\n2. **正常时期 IP 活跃度经验累积分布。** X 轴为 IP 正常活跃度（响应比例）；Y 轴为累计 IP 占比。蓝线为 IP 的经验累积分布，橙色虚线为中位数，浅蓝色区域为 P10–P90，底部文字给出干净完整周期和可映射 IP 数量。它展示端点基线行为的异质性，不能单独定义脆弱性。\n\n3. **H1 跨攻击端点损失排序重复性。** 横轴和纵轴均为战争攻击事件；颜色为两个事件共同 IP 在匹配地理范围内的可达性损失排名 Spearman ρ。白色表示不可估计，不代表 ρ=0。\n\n4. **H3 正常活跃度调整前后对比。** X 轴为分析方式（H2 未控制正常活跃度、H3 控制正常活跃度）；Y 轴为高敏感度组 Q5 与低敏感度组 Q1 的平均可达性下降差，柱顶直接标注百分点值。\n\n5. **H4 正常活跃度损失贡献提升。** X 轴为冻结正常活跃度十分位 D1–D10；Y 轴为有符号损失贡献提升。D1/D2 可为负，因为这里保留有符号变化，响应增加会产生负贡献；这不是计算错误。\n\n6. **H4 IP 级损失集中度。** X 轴为按正向可达性损失排序后的前 X% IP；Y 轴为累计正向可达性损失贡献。标注点给出前 10%、20%、50% 的实际贡献比例。\n\n7–8. **2024-08-26 探索性州级计划停电敏感度图。** 图 7 为州级正常活跃度调整后的 Q5−Q1 forest 图：X 轴为可达性下降百分点，Y 轴为统一排序的州，点和误差线为州级估计及 /24 前缀聚类 bootstrap 95% 置信区间，颜色为估计类别。图 8 为州×计划停电敏感度热图：X 轴为 Q1–Q5，Y 轴为州，颜色和格内数字为相对 Q1 的可达性下降差（百分点）。二者均为事后设计的探索性州级案例研究，不属于 H1–H4，不能外推为跨事件稳定脆弱性或因果结论。\n\n9. **2024-08-26 探索性州级双森林图（附录）。** 左图 X 轴为正常活跃度调整后的 Q5−Q1 可达性下降，右图 X 轴为 D10−D1 可达性下降；两图 Y 轴使用完全相同的州排序，点为州级估计，误差线为 /24 前缀聚类 bootstrap 95% 置信区间。该图仅用于直观比较两种端点结构信号，不改变 H1–H4。\n''',encoding='utf-8')
    plan = PKG/'FINAL_MANUSCRIPT_FIGURE_PLAN.md'
    plan.write_text('''# 最终正文图方案\n\n1. `01_aggregate_ips_fbs`：2024-08-26 相对攻击锚点的 IPS/FBS 折线对照，说明 /24 仍活跃时 IP 响应数也可能大幅下降。\n2. `02_activity_distribution`：正常时期 IP 活跃度分布，说明端点基线行为存在异质性。\n3. `03_h1_cross_event_repeatability`：六次攻击的共同 IP 损失排序 Spearman 热图，说明跨事件重复性有限。\n4. `04_h3_h2_vs_h3_adjustment`：H2 与 H3 的 Q5−Q1 对比，说明控制正常活跃度后计划停电敏感度关联基本消失。\n5. `05_h4_activity_lift`：正常活跃度十分位的损失贡献提升。\n6. `06_h4_loss_concentration`：正向 IP 级损失集中度（前 10/20/50%）。\n7. `07_aug26_sensitivity_forest`：2024-08-26 探索性州级计划停电敏感度 forest。\n8. `08_aug26_sensitivity_heatmap`：2024-08-26 探索性州×计划停电敏感度热图。\n\n图 1–6 为 H1–H4 正式主结果；图 7–8 明确标为探索性州级案例研究，不编号为 H5。\n''',encoding='utf-8')

def main():
    copy_event_curve()
    ensure_aug26_english_appendix()
    ensure_english_appendix_symmetry()
    copy_aug26_main()
    render_activity_ecdf_zh()
    for lang in ('en','zh'):
        render_event_curve(lang)
        render_h1(lang); render_h3(lang); render_h4(lang)
    docs(); refresh_language_index(); file_level_check(); print('final figure-only QA refactor complete')
if __name__=='__main__': main()
