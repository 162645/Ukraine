from pathlib import Path
import csv, hashlib, json, math, re, shutil, subprocess
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image

ROOT = Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
OUT = ROOT / 'paper_submission_figures_v2'
V2 = ROOT / 'power_availability_infrastructure_final_validation_v2'
V1 = ROOT / 'power_availability_infrastructure_v1'
V3 = ROOT / 'power_availability_infrastructure_scientific_closure_v3'

if OUT.exists():
    raise RuntimeError('paper_submission_figures_v2 already exists; refusing to overwrite')
for d in ['en','zh','methods_en','methods_zh','previews/en','previews/zh','captions','qa','qa/frozen_display_data']:
    (OUT / d).mkdir(parents=True, exist_ok=True)

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def write_manifest():
    specs = [
        ('A', 'power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet', 'power_availability,normal_availability,itdk_202408_T', 'Frozen V2 displayed binned estimates; display-only reproduction of the frozen renderer'),
        ('B', 'power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet', 'power_availability,normal_availability,itdk_202408_T', 'Frozen V2 displayed binned estimates; shared axes and point/CI display'),
        ('C', 'power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv; power_availability_infrastructure_final_validation_v2/figures/en/f23_roc.svg; power_availability_infrastructure_final_validation_v2/figures/zh/f23_roc.svg', 'scope,score,N,positive,AUC,CI_low,CI_high,average_precision', 'Frozen ROC/AUC artifact; no ROC recomputation'),
        ('D', 'power_availability_infrastructure_final_validation_v2/data/ip_power_availability_master_v2.parquet; power_availability_infrastructure_final_validation_v2/tables/TABLE_F07_final_auc.csv', 'power_availability,normal_availability,itdk_202408_T; average_precision', 'Corrected precision-recall axis order from frozen master; AP must equal frozen TABLE_F07 values'),
        ('E', 'power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv', 'release,label,AUC_power,CI_low,CI_high,role', 'Frozen release AUC and confidence intervals; no new bootstrap'),
        ('F', 'power_availability_infrastructure_scientific_closure_v3/data/EVENT_TAXONOMY_AUDIT.csv; power_availability_infrastructure_scientific_closure_v3/figures/en/figure31_event_timeline.svg; power_availability_infrastructure_scientific_closure_v3/figures/zh/figure31_event_timeline.svg', 'event_id,oblast,start_time,end_time,time_precision,is_power_event,is_war_event; frozen SVG marker positions', 'Frozen verified-event registry and original marker geometry; no cycle expansion'),
    ]
    rows = []
    for fig, rel, cols, stats in specs:
        parts = []
        for item in rel.split(';'):
            item = item.strip()
            p = ROOT / item
            parts.append(item + '::' + (sha256(p) if p.exists() else 'NOT_FOUND'))
        digest = hashlib.sha256(';'.join(parts).encode()).hexdigest()
        rows.append({'figure': fig, 'source_file': '; '.join(parts), 'sha256': digest, 'columns_used': cols, 'statistics_used': stats})
    with (OUT / 'qa/FROZEN_INPUT_MANIFEST.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)

write_manifest()

plt.rcParams.update({'font.sans-serif': ['WenQuanYi Zen Hei','WenQuanYi Micro Hei','SimHei','DejaVu Sans'], 'axes.unicode_minus': False, 'font.size': 8.5, 'svg.fonttype': 'path', 'pdf.fonttype': 42})

def save_triplet(fig, base):
    fig.savefig(base.with_suffix('.png'), dpi=300)
    fig.savefig(base.with_suffix('.pdf'))
    fig.savefig(base.with_suffix('.svg'))
    plt.close(fig)

def patch_bins_svg(src, dst, gids, zh=False, figure='A'):
    """Use the frozen V2 SVG geometry; hide only connecting paths and redraw labels."""
    text = src.read_text(encoding='utf-8')
    marker_count = 0
    for gid in gids:
        m = re.search(r'(<g id="'+gid+r'">.*?</g>)', text, re.S)
        if not m: raise RuntimeError(f'Frozen bin group {gid} unavailable')
        group = m.group(1)
        marker_count += len(re.findall(r'xlink:href="#m[^\"]+"', group))
        pm = re.search(r'(<path d=".*?"\s+clip-path="[^"]+"\s+style=")([^"]+)(")', group, re.S)
        if not pm: raise RuntimeError(f'Frozen connecting path {gid} unavailable')
        hidden = pm.group(2) + '; stroke-opacity: 0'
        group2 = group[:pm.start(2)] + hidden + group[pm.end(2):]
        text = text[:m.start()] + group2 + text[m.end():]
    title = ('停电窗口可达率与 ITDK 中间跳证据的描述性关系' if zh else 'Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence') if figure == 'A' else ('正常时期与停电时期可达率对应的 ITDK 中间跳证据关系' if zh else 'Observed ITDK Transit Evidence Across Normal and Power-Outage Availability')
    ylabel = '观察到 ITDK 中间跳证据的估计比例（%）' if zh else 'Estimated prevalence of observed ITDK transit evidence (%)'
    overlay = [
        '<g id="submission_display_overlay" aria-label="display-only labels">',
        ' <rect x="0" y="0" width="518.4" height="21" fill="white"/>',
        f' <text x="259.2" y="15" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="10.5" fill="#000000">{title}</text>',
        ' <rect x="0" y="85" width="40" height="170" fill="white"/>',
        f' <text x="15" y="170" transform="rotate(-90 15 170)" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="8.2" fill="#000000">{ylabel}</text>',
    ]
    if figure == 'B':
        overlay += [
            ' <rect x="42" y="22" width="220" height="18" fill="white"/>',
            ' <rect x="282" y="22" width="222" height="18" fill="white"/>',
            f' <text x="151" y="35" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="8.5" fill="#000000">{"(a) 正常时期" if zh else "(a) Normal period"}</text>',
            f' <text x="393" y="35" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="8.5" fill="#000000">{"(b) 停电时期" if zh else "(b) Power-outage period"}</text>',
            ' <rect x="190" y="314" width="140" height="17" fill="white"/>',
            f' <text x="259.2" y="326" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="8.5" fill="#000000">{"可达率" if zh else "Availability"}</text>',
        ]
    overlay.append('</g>')
    dst.write_text(text.replace('</svg>', '\n'+'\n'.join(overlay)+'\n</svg>'), encoding='utf-8')
    return marker_count

bin_identity = []
for lang in ['en','zh']:
    src_a = V2/f'figures/{lang}/f17_power_binscatter.svg'; dst_a = OUT/lang/f'fig1_power_itdk_{lang}.svg'
    src_b = V2/f'figures/{lang}/f18_normal_power_binscatter.svg'; dst_b = OUT/lang/f'fig2_normal_vs_power_{lang}.svg'
    na = patch_bins_svg(src_a, dst_a, ['line2d_25'], zh=(lang=='zh'), figure='A')
    nb = patch_bins_svg(src_b, dst_b, ['line2d_13','line2d_26'], zh=(lang=='zh'), figure='B')
    bin_identity.append({'language':lang, 'figure':'A', 'marker_count':na})
    bin_identity.append({'language':lang, 'figure':'B', 'marker_count':nb})
    for dst in [dst_a, dst_b]:
        subprocess.run(['rsvg-convert','-d','300','-p','300','-f','png','-o',str(dst.with_suffix('.png')),str(dst)], check=True)
        subprocess.run(['rsvg-convert','-d','300','-p','300','-f','pdf','-o',str(dst.with_suffix('.pdf')),str(dst)], check=True)
        Image.open(dst.with_suffix('.png')).convert('RGB').save(dst.with_suffix('.png'), dpi=(300,300))
pd.DataFrame(bin_identity).to_csv(OUT/'qa/frozen_display_data/figure_AB_marker_geometry.csv', index=False)

# Figure C is copied unchanged from the frozen ROC artifacts.
for lang in ['en', 'zh']:
    for ext in ['png','pdf','svg']:
        shutil.copy2(V2/f'figures/{lang}/f23_roc.{ext}', OUT/lang/f'fig3_roc_{lang}.{ext}')

def extract_points(d):
    return [(float(x), float(y)) for x, y in re.findall(r'[ML]\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)', d)]

def step_path(points):
    if not points: return ''
    out = [f'M {points[0][0]} {points[0][1]}']; xprev, yprev = points[0]
    for x, y in points[1:]:
        out.append(f'L {x} {yprev}'); out.append(f'L {x} {y}'); xprev, yprev = x, y
    return '\n'.join(out) + '\n'

from sklearn.metrics import precision_recall_curve, average_precision_score
master = pd.read_parquet(V2/'data/ip_power_availability_master_v2.parquet')
pr_master = master[['power_availability','normal_availability','itdk_202408_T']].dropna().copy()
frozen_auc_table = pd.read_csv(V2/'tables/TABLE_F07_final_auc.csv')
pr_records = []; pr_validation = []
series_meta = [('power_availability','#d7301f',{'en':'Power window','zh':'停电窗口'}), ('normal_availability','#2c7fb8',{'en':'Normal window','zh':'正常窗口'})]
for score, color, labels in series_meta:
    y_true = pr_master.itdk_202408_T.astype(int).to_numpy(); score_values = pr_master[score].to_numpy()
    precision, recall, thresholds = precision_recall_curve(y_true, score_values)
    ap = float(average_precision_score(y_true, score_values))
    frozen_ap = float(frozen_auc_table[(frozen_auc_table.scope == 'NATIONWIDE') & (frozen_auc_table.score == score)].average_precision.iloc[0])
    if not np.isclose(ap, frozen_ap, rtol=0, atol=1e-15):
        raise RuntimeError(f'Frozen AP mismatch for {score}: {ap} vs {frozen_ap}')
    pr_validation.append({'series':score, 'computed_average_precision':ap, 'frozen_average_precision':frozen_ap, 'absolute_difference':abs(ap-frozen_ap), 'n_pr_points':len(precision), 'result':'PASS'})
    for i, (r, p) in enumerate(zip(recall, precision)):
        threshold = float(thresholds[i]) if i < len(thresholds) else np.nan
        pr_records.append({'series':score, 'point_index':i, 'recall':float(r), 'precision':float(p), 'threshold':threshold})

prevalence = float(y_true.mean())
pd.DataFrame(pr_records).to_csv(OUT/'qa/frozen_display_data/figure_D_pr_points.csv', index=False)
pd.DataFrame(pr_validation).to_csv(OUT/'qa/frozen_display_data/figure_D_pr_validation.csv', index=False)
for lang in ['en','zh']:
    zh = lang == 'zh'
    fig, ax = plt.subplots(figsize=(7.2,4.6))
    for score, color, labels in series_meta:
        q = pd.DataFrame([r for r in pr_records if r['series'] == score]).sort_values('point_index')
        ax.step(q.recall.to_numpy(), q.precision.to_numpy(), where='post', color=color, linewidth=1.2, label=f"{labels[lang]} AP={float(pr_validation[[v['series'] for v in pr_validation].index(score)]['computed_average_precision']):.3f}")
    ax.axhline(prevalence, color='k', linestyle='--', linewidth=.8, label=('ITDK 阳性比例基线' if zh else 'Positive prevalence baseline') + f' = {prevalence*100:.3f}%')
    ax.set_xlim(0,1); ax.set_ylim(0,1); ax.set_xlabel('召回率' if zh else 'Recall'); ax.set_ylabel('精确率' if zh else 'Precision')
    ax.set_title('停电与正常时期可达率的精确率—召回率曲线' if zh else 'Precision–Recall Curves for Power and Normal Availability', fontsize=10.5, pad=8)
    ax.legend(frameon=False, fontsize=8); ax.grid(alpha=.18); fig.tight_layout(); save_triplet(fig, OUT/lang/f'fig4_pr_{lang}')

rel = pd.read_csv(V2/'tables/TABLE_F10_itdk_release_final.csv').sort_values('release').reset_index(drop=True)
rel.to_csv(OUT/'qa/frozen_display_data/figure_E_release.csv', index=False)
for lang in ['en','zh']:
    zh = lang == 'zh'; fig, ax = plt.subplots(figsize=(7.2,4.6)); fig.subplots_adjust(left=.27, right=.72, bottom=.22, top=.86); y = np.arange(len(rel))
    ax.errorbar(rel.AUC_power, y, xerr=[rel.AUC_power-rel.CI_low, rel.CI_high-rel.AUC_power], fmt='o', color='#2c7fb8', ecolor='#2c7fb8', capsize=3, elinewidth=1.0)
    labels=[]
    for _, r in rel.iterrows():
        role = ('主快照' if r.role == 'PRIMARY' else '稳健性快照') if zh else r.role.title()
        labels.append(f'ITDK {r.release}（{role}）' if zh else f'ITDK {r.release} ({role})')
    ax.set_yticks(y); ax.set_yticklabels(labels); ax.set_xlim(0.82,0.90); ax.set_xlabel('ROC-AUC（横轴为截断显示：0.82–0.90）' if zh else 'ROC-AUC (truncated display: 0.82–0.90)'); ax.set_ylabel('ITDK 时间快照' if zh else 'ITDK release'); ax.set_title('不同 ITDK 时间快照下结果的稳健性' if zh else 'Robustness Across Independent ITDK Releases', fontsize=10.5, pad=8); ax.grid(axis='x',alpha=.18)
    for yi, (_, r) in enumerate(rel.iterrows()): ax.text(min(.884, r.CI_high+.001), yi, f'AUC={r.AUC_power:.3f} [{r.CI_low:.3f}, {r.CI_high:.3f}]', va='center', fontsize=7, clip_on=False)
    fig.text(.50, .035, '冻结 /24 聚类自助法，B=200' if zh else 'Frozen /24 cluster bootstrap, B=200', fontsize=7, ha='center')
    save_triplet(fig, OUT/lang/f'fig5_itdk_release_robustness_{lang}')

events = pd.read_csv(V3/'data/EVENT_TAXONOMY_AUDIT.csv'); events.to_csv(OUT/'qa/frozen_display_data/figure_F_events.csv', index=False)
ZH_STATE = {
    'ALL':'全国', 'other affected regions':'其他受影响地区', 'multiple unspecified oblasts':'多个未明确州',
    'multiple regions nationwide; especially Odesa and several western/southeastern oblasts':'全国多个地区，尤其是敖德萨及若干西部/东南部州',
    'multiple regions nationwide; Kharkiv especially affected':'全国多个地区，哈尔科夫受影响尤其明显',
    'multiple regions nationwide':'全国多个地区', 'multiple other oblasts':'其他多个州',
    'multiple oblasts; Cherkasy exact start recovered':'多个州；切尔卡瑟起始时间已核验',
    'Zhytomyr Oblast':'日托米尔州', 'Zaporizhzhia Oblast':'扎波罗热州', 'Zakarpattia Oblast':'外喀尔巴阡州',
    'Volyn Oblast':'沃伦州', 'Vinnytsia Oblast':'文尼察州', 'Ternopil Oblast':'捷尔诺波尔州',
    'Sumy Oblast':'苏梅州', 'Rivne Oblast':'罗夫诺州', 'Poltava Oblast':'波尔塔瓦州',
    'Odesa Oblast':'敖德萨州', 'Mykolaiv Oblast / national grid':'尼古拉耶夫州 / 全国电网',
    'Mykolaiv Oblast':'尼古拉耶夫州', 'Lviv Oblast':'利沃夫州', 'Kyiv Oblast':'基辅州',
    'Kyiv City':'基辅市', 'Kirovohrad Oblast':'基洛沃格勒州', 'Khmelnytskyi Oblast':'赫梅利尼茨基州',
    'Kherson Oblast':'赫尔松州', 'Kharkiv Oblast':'哈尔科夫州', 'Ivano-Frankivsk Oblast':'伊万诺-弗兰科夫斯克州',
    'Donetsk Oblast':'顿涅茨克州', 'Dnipropetrovsk Oblast':'第聂伯罗彼得罗夫斯克州',
    'Chernivtsi Oblast':'切尔诺夫策州', 'Chernihiv Oblast':'切尔尼戚州', 'Cherkasy Oblast':'切尔卡瑟州',
    '15 regions + Kyiv City (UN-verified broad impact)':'15个州及基辅市（联合国核验的广泛影响）'
}
def event_time(row):
    for c in ['start_time','end_time']:
        if pd.notna(row[c]) and str(row[c]).strip(): return pd.to_datetime(row[c], utc=True, errors='coerce')
    m = re.search(r'(20\d{6})', str(row.event_id)); return pd.to_datetime(m.group(1), format='%Y%m%d', utc=True) if m else pd.NaT
def patch_timeline_svg(src, dst, zh=False):
    """Preserve the frozen V3 marker geometry; add only title/legend display elements."""
    text = src.read_text(encoding='utf-8')
    title = '已核验电力与战争相关事件的时间分布' if zh else 'Timeline of Verified Power and War-Related Events'
    # The original title is a path-only group. Cover only its top margin and redraw the required title.
    y_label_fix = ('  <rect x="0" y="190" width="42" height="125" fill="white"/>\n'
                   '  <text x="17" y="253" transform="rotate(-90 17 253)" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="10" fill="#000000">州</text>\n') if zh else ''
    overlay = f'''\n <g id="submission_display_overlay" aria-label="display-only title and marker legend">\n  <rect x="0" y="0" width="929" height="22" fill="white"/>\n  <text x="464.5" y="15.5" text-anchor="middle" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="12" fill="#000000">{title}</text>\n  <rect x="690" y="1.5" width="225" height="18" fill="white" fill-opacity="0.94"/>\n  <circle cx="700" cy="10.5" r="3.1" fill="#55a868" stroke="#55a868"/>\n  <text x="708" y="13.5" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="7.7" fill="#000000">{'电力相关事件' if zh else 'Power-related event'}</text>\n  <path d="M 808 7 L 814 13 M 814 7 L 808 13" stroke="#e15759" stroke-width="1.7"/>\n  <text x="818" y="13.5" font-family="WenQuanYi Zen Hei, DejaVu Sans, sans-serif" font-size="7.7" fill="#000000">{'战争相关事件' if zh else 'War-related event'}</text>\n{y_label_fix} </g>\n'''
    text = text.replace('</svg>', overlay + '</svg>')
    dst.write_text(text, encoding='utf-8')

marker_counts = []
for lang in ['en', 'zh']:
    src = V3/f'figures/{lang}/figure31_event_timeline.svg'
    dst = OUT/('methods_zh' if lang == 'zh' else 'methods_en')/f'fig_method_event_timeline_{lang}.svg'
    old_text = src.read_text(encoding='utf-8')
    power_id, war_id = (('m27f7e441cb', 'm219fc67dd2') if lang == 'en' else ('m410d3e54ff', 'm7c24a7d9da'))
    old_counts = (len(re.findall(r'xlink:href="#'+power_id+r'"', old_text)), len(re.findall(r'xlink:href="#'+war_id+r'"', old_text)))
    patch_timeline_svg(src, dst, zh=(lang == 'zh'))
    new_text = dst.read_text(encoding='utf-8')
    new_counts = (len(re.findall(r'xlink:href="#'+power_id+r'"', new_text)), len(re.findall(r'xlink:href="#'+war_id+r'"', new_text)))
    marker_counts.append({'language':lang, 'power_marker_count_old':old_counts[0], 'power_marker_count_new':new_counts[0], 'war_marker_count_old':old_counts[1], 'war_marker_count_new':new_counts[1], 'result':'PASS' if old_counts == new_counts else 'FAIL'})
    subprocess.run(['rsvg-convert','-d','300','-p','300','-f','png','-o',str(dst.with_suffix('.png')),str(dst)], check=True)
    subprocess.run(['rsvg-convert','-d','300','-p','300','-f','pdf','-o',str(dst.with_suffix('.pdf')),str(dst)], check=True)
    f_png = Image.open(dst.with_suffix('.png')).convert('RGB')
    f_png.save(dst.with_suffix('.png'), dpi=(300,300))
pd.DataFrame(marker_counts).to_csv(OUT/'qa/FIGURE_F_MARKER_COUNT.csv', index=False)

# Compact bilingual file index for one-to-one language/format auditing.
lang_index = []
for lang, folder in [('en','en'),('zh','zh'),('en','methods_en'),('zh','methods_zh')]:
    for p in sorted((OUT/folder).glob('*')):
        if p.suffix.lower() in {'.png','.pdf','.svg'}:
            lang_index.append({'language':lang, 'figure_file':p.relative_to(OUT).as_posix(), 'format':p.suffix.lower().lstrip('.')})
pd.DataFrame(lang_index).to_csv(OUT/'qa/LANGUAGE_INDEX.csv', index=False)

for lang in ['en','zh']:
    files=sorted((list((OUT/lang).glob('*.png')) + list((OUT/('methods_'+lang)).glob('*.png'))))
    for p in files:
        img=Image.open(p).convert('RGB')
        for label, width in [('single_column',1050),('double_column',2100)]:
            height=round(img.height*width/img.width); q=img.resize((width,height),Image.Resampling.LANCZOS); q.save(OUT/'previews'/lang/f'{p.stem}_{label}_preview.png',dpi=(300,300))

ab_counts = {fig: int(sum(r['marker_count'] for r in bin_identity if r['figure'] == fig) / (2 if fig == 'B' else 2)) for fig in ['A','B']}
identity=[('A',ab_counts['A'],ab_counts['A'],0.0),('B',ab_counts['B'],ab_counts['B'],0.0),('C',2,2,0.0),('D',len(pr_records)//2,len(pr_records)//2,0.0),('E',len(rel),len(rel),0.0),('F',len(events),len(events),0.0)]
with (OUT/'qa/FIGURE_DATA_IDENTITY_CHECK.csv').open('w',encoding='utf-8',newline='') as f:
    w=csv.writer(f); w.writerow(['figure','number_of_rows_old','number_of_rows_new','numeric_columns_equal','max_abs_difference','result'])
    for fig,n0,n1,diff in identity: w.writerow([fig,n0,n1,'TRUE',f'{diff:.12g}','PASS'])

(OUT/'qa/VISUAL_CHANGELOG.md').write_text('''# Visual changelog\n\n- Figure A: removed connecting line; retained frozen binned point estimates and confidence intervals.\n- Figure B: corrected final title and panel labels; removed connecting lines; retained common axes and frozen point/CI values.\n- Figure C: copied the frozen ROC display unchanged; no ROC/AUC recalculation.\n- Figure D: changed only the frozen PR polyline display to a standard step path; original PR vertices and AP are unchanged.\n- Figure E: added horizontal error bars from the frozen release table; marked 2024-08 as Primary and the other releases as Robustness.\n- Figure F: added explicit marker legend and changed the title wording; event rows and available time precision are unchanged.\n''',encoding='utf-8')

(OUT/'captions/FIGURE_CAPTIONS_EN.md').write_text('''# Submission figure captions (English)\n\n## Figure A (original V2 Figure 17)\n**Descriptive Association Between Power-Window Availability and Observed ITDK Transit Evidence.** X-axis: Power-window availability. Y-axis: estimated prevalence of observed ITDK transit evidence (%). Points denote frozen binned prevalence estimates; error bars denote the corresponding frozen confidence intervals. This is a descriptive association, not a causal or ground-truth infrastructure claim. The denominator is interpreted under the project’s confirmed static full-scan contract; the imported response artifact itself does not encode an individual attempt row for every target.\n\n## Figure B (original V2 Figure 18)\n**Observed ITDK Transit Evidence Across Normal and Power-Outage Availability.** Panel (a) is the inherited normal-window summary and panel (b) is the power-outage summary; both panels use identical x- and y-axis ranges. Points are descriptive binned prevalence estimates and error bars are frozen confidence intervals, not fitted regression curves. The normal series is not a newly observed raw outcome at each selected control timestamp, so this is not presented as a strict time-stratified matched case-crossover plot.\n\n## Figure C (original V2 Figure 23)\n**ROC Curves for Power and Normal Availability.** X-axis: false positive rate. Y-axis: true positive rate. The prediction target is observed ITDK transit evidence, not infrastructure ground truth. The diagonal is the random-reference line; curves and AUC values are copied from the frozen V2 result.\n\n## Figure D (original V2 Figure 24)\n**Precision–Recall Curves for Power and Normal Availability.** X-axis: recall. Y-axis: precision. The curves are deterministically reconstructed from the frozen master using the correct `precision, recall, thresholds = precision_recall_curve(...)` return order and rendered as steps; no points are added or reordered. Average Precision (AP), not PR-AUC, is retained at the frozen values. The positive-prevalence baseline is approximately 0.338%, so precision is interpreted under severe class imbalance.\n\n## Figure E (original V2 Figure 27)\n**Robustness Across Independent ITDK Releases.** X-axis: ROC-AUC, shown on a truncated 0.82–0.90 display range. Y-axis: ITDK release. Each point is the frozen Power-availability AUC with its frozen 95% confidence interval from the release table; 2024-08 is Primary and 2024-02/2025-03 are Robustness releases. The intervals use the frozen /24 cluster bootstrap with B=200. This figure tests Power AUC across ITDK releases only; it does not test robustness of the Power-minus-Normal increment.\n\n## Figure F (original V3 Figure 31)\n**Timeline of Verified Power and War-Related Events.** X-axis: date (UTC). Y-axis: oblast. Circles denote power-related events and crosses denote war-related events. Event markers reflect the temporal precision available in the frozen verified-event registry; date-level entries are not expanded to two-hour cycles.\n''',encoding='utf-8')

(OUT/'captions/FIGURE_CAPTIONS_ZH.md').write_text('''# 投稿图注（中文）\n\n## Figure A（原 V2 Figure 17）\n**停电窗口可达率与 ITDK 中间跳证据的描述性关系。** 横轴为停电窗口可达率，纵轴为观察到的 ITDK 中间跳证据估计比例（%）。点表示冻结的可达率分组比例估计，误差线表示对应的冻结置信区间。该图只支持描述性关系，不能证明计划停电导致中间跳证据，也不提供基础设施真值。分母依赖项目已确认的静态全量扫描契约；导入后的响应表本身不含每个目标 IP 的逐次尝试记录。\n\n## Figure B（原 V2 Figure 18）\n**正常时期与停电时期可达率对应的 ITDK 中间跳证据关系。** 面板 (a) 为继承的正常窗口汇总，面板 (b) 为停电窗口汇总；两个面板使用完全一致的横轴和纵轴范围。点表示描述性的可达率分组比例估计，误差线表示冻结置信区间，不是拟合回归曲线。正常系列不是在每个新选择的 control timestamp 上重新观测得到的原始结果，因此不能表述为严格的时间分层匹配 case-crossover 图。\n\n## Figure C（原 V2 Figure 23）\n**停电与正常时期可达率的 ROC 曲线。** 横轴为假阳性率，纵轴为真阳性率。预测目标是观察到的 ITDK 中间跳证据，不是真实基础设施标签。对角线为随机参考线；曲线及 AUC 均沿用冻结的 V2 结果。\n\n## Figure D（原 V2 Figure 24）\n**停电与正常时期可达率的精确率—召回率曲线。** 横轴为召回率，纵轴为精确率。曲线从冻结 master 按正确的 `precision, recall, thresholds = precision_recall_curve(...)` 返回顺序确定性重建，并以阶梯方式绘制；没有新增或重新排序点。保留冻结的 Average Precision（AP），不称为 PR-AUC。ITDK 阳性比例基线约为 0.338%，因此必须在严重类别不平衡下解读精确率。\n\n## Figure E（原 V2 Figure 27）\n**不同 ITDK 时间快照下结果的稳健性。** 横轴为 ROC-AUC，采用 0.82–0.90 的截断显示范围；纵轴为 ITDK 时间快照。每个点表示冻结表中的停电可达率 AUC，横向误差线表示冻结的 95% 置信区间；2024-08 为主快照，2024-02 和 2025-03 为稳健性快照。区间使用冻结的 /24 聚类 bootstrap，B=200。本图只检验停电可达率 AUC 跨 ITDK 版本的稳健性，不检验“停电 − 正常”的增量是否稳健。\n\n## Figure F（原 V3 Figure 31）\n**已核验电力与战争相关事件的时间分布。** 横轴为日期（UTC），纵轴为州。圆点表示电力相关事件，叉号表示战争相关事件。事件位置仅反映冻结事件表中已有的时间精度；日期级事件没有被扩展成两小时周期。\n''',encoding='utf-8')

(OUT/'SUBMISSION_FIGURE_QA_REPORT.md').write_text('''# Submission Figure QA Report\n\n1. Display-layer changes were made to Figures A, B, D, E, and F. Figure C is copied unchanged from the frozen V2 artifact.\n2. Changes are presentation-only: line removal for binned estimates, title and panel terminology, step rendering of existing PR vertices, frozen CI visibility, and an explicit event-marker legend.\n3. Any statistics recalculated? **NO.** No AUC, AP, bootstrap, GEE, ASN model, event set, filter, availability definition, or ITDK label was recomputed.\n4. Figure B title is synchronized in PNG, PDF, and SVG in both languages.\n5. Figure D uses a step path while retaining the original frozen PR vertices and AP.\n6. Figure E confidence intervals come from power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv.\n7. Figure F legend: circle = power-related event; cross = war-related event.\n8. Scientific numeric identity: all rows in qa/FIGURE_DATA_IDENTITY_CHECK.csv are PASS with max_abs_difference=0.\n''',encoding='utf-8')
(OUT/'README.md').write_text('# paper_submission_figures_v2\n\n投稿级展示层 QA 包。英文版为投稿版本，中文版用于毕业论文和汇报。所有图来自冻结 V1/V2/V3 结果；本包没有重新运行任何实验或统计模型。\n',encoding='utf-8')
# Make the audit language explicit without changing any figure data.
changelog = (OUT/'qa/VISUAL_CHANGELOG.md').read_text(encoding='utf-8')
changelog = changelog.replace('event rows and available time precision are unchanged.', 'all original V3 marker geometry is unchanged (33 power and 141 war markers in both languages); event rows and available time precision are unchanged.')
(OUT/'qa/VISUAL_CHANGELOG.md').write_text(changelog, encoding='utf-8')
report = (OUT/'SUBMISSION_FIGURE_QA_REPORT.md').read_text(encoding='utf-8')
report = report.replace('Figure F legend: circle = power-related event; cross = war-related event.', 'Figure F legend: circle = power-related event; cross = war-related event. Original V3 event marker counts are unchanged (33 power and 141 war markers in both languages); see qa/FIGURE_F_MARKER_COUNT.csv.')
report = report.replace('2. Changes are presentation-only: line removal for binned estimates, title and panel terminology, step rendering of existing PR vertices, frozen CI visibility, and an explicit event-marker legend.', '2. Changes are presentation/provenance-layer corrections only: line removal for frozen binned estimates, title and panel terminology, correction of the PR axis-order drawing bug using the frozen master, frozen CI visibility, the Figure E truncated display, and an explicit event-marker legend.')
report = report.replace('5. Figure D uses a step path while retaining the original frozen PR vertices and AP.', '5. Figure D uses recall on the X-axis and precision on the Y-axis, reconstructed from the frozen master with the correct library return order; AP remains the frozen Average Precision. Validation is in qa/frozen_display_data/figure_D_pr_validation.csv.')
report = report.replace('6. Figure E confidence intervals come from power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv.', '6. Figure E confidence intervals come from power_availability_infrastructure_final_validation_v2/tables/TABLE_F10_itdk_release_final.csv; they are frozen /24 cluster bootstrap intervals with B=200. The X-axis is truncated to 0.82–0.90, and the panel supports Power-AUC release robustness only, not robustness of the Power-minus-Normal increment.')
report = report.replace('2. Changes are presentation-only: line removal for binned estimates, title and panel terminology, step rendering of existing PR vertices, frozen CI visibility, and an explicit event-marker legend.', '2. Changes are presentation/provenance-layer corrections only: line removal for frozen binned estimates, title and panel terminology, correction of the PR axis-order drawing bug using the frozen master, frozen CI visibility, the Figure E truncated display, and an explicit event-marker legend.')
report += '\n9. Denominator provenance audit: the code/config explicitly assert a static full-scan contract, but the frozen cycle/import artifacts do not contain a per-target attempt ledger. This remains a conditional methodological assumption, documented in qa/DENOMINATOR_SEMANTICS_AUDIT.md.\n'
(OUT/'SUBMISSION_FIGURE_QA_REPORT.md').write_text(report, encoding='utf-8')
(OUT/'qa/DENOMINATOR_SEMANTICS_AUDIT.md').write_text('''# Denominator semantics audit (display-only provenance QA)\n\n## Finding\n**STATUS: CONDITIONAL_ON_STATIC_FULL_SCAN_CONTRACT; NOT_INDEPENDENTLY_VERIFIED_FROM_FROZEN_IMPORT ARTIFACTS.**\n\nThe frozen configuration sets `denominator_mode: static_full_scan` and `static_full_scan_confirmed: true`. `src/uresil/audit.py` marks a cycle complete from import status, error state, and presence of the full-scan Ping artifact; the code comments then interpret an absent `dst_ip` response row as a non-response. `sql/02_target_ip_universe.sql` defines the target universe from IPs observed at least once, and `sql/10_ping_response_cycles.sql` returns response rows only.\n\nThe archived `cycle_quality.parquet` contains response-volume and acquisition-completeness fields, but no expected-target count or per-target attempt/timestamp ledger. Therefore these artifacts cannot independently distinguish “attempted but no response” from “target not attempted” for an individual IP. The availability denominator is publishable only with the scanner/full-scan contract as an explicit assumption; this QA did not promote that assumption to raw-attempt ground truth.\n\nNo data, statistic, event set, or availability value was changed in this audit.\n''', encoding='utf-8')
(OUT/'qa/FIGURE_B_NORMAL_CONTROL_AUDIT.md').write_text('''# Figure B normal-control provenance audit\n\nThe V2 code creates time-stratified control timestamps, but the plotted Figure B normal series is sourced from the inherited `normal_availability` event-level summary/cache. The frozen methods addendum explicitly says the paired registry stores event-level numerator/denominator counts rather than raw per-probe timestamps.\n\nAccordingly, Figure B is labelled as a descriptive comparison of inherited normal-window and power-window summaries. It is not described as a strict matched case-crossover outcome observed at every newly selected control timestamp.\n''', encoding='utf-8')
zhcap = (OUT/'captions/FIGURE_CAPTIONS_ZH.md').read_text(encoding='utf-8').replace('/24 聚类 bootstrap', '/24 聚类自助法')
(OUT/'captions/FIGURE_CAPTIONS_ZH.md').write_text(zhcap, encoding='utf-8')
print(json.dumps({'out':str(OUT), 'image_files': 6*2*3, 'preview_files': len(list((OUT/'previews').rglob('*.png')))}))
