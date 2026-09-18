from pathlib import Path
import hashlib
import json
import shutil

root = Path('/home/wsl/XiaoLunWen_doc_complete_20260908')
pkg = root / 'paper_final_assets_20260912_bilingual'

def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()

files = {str(p.relative_to(pkg)).replace('\\', '/'): sha(p)
         for p in sorted(pkg.rglob('*'))
         if p.is_file() and p.name != 'FINAL_PAPER_ASSET_MANIFEST.json'}
manifest_path = pkg / 'manifests/FINAL_PAPER_ASSET_MANIFEST.json'
m = json.loads(manifest_path.read_text())
m['bilingual_rendering']['chinese_aug26_full_redraw'] = True
m['bilingual_rendering']['chinese_frozen_figures_full_inplot_rerender'] = True
m['bilingual_rendering']['chinese_from_frozen_png'] = False
m['bilingual_rendering']['chinese_from_frozen_data_tables'] = True
m['files_sha256'] = files
manifest_path.write_text(json.dumps(m, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(pkg / 'README.md').write_text('''# paper_final_assets_20260912_bilingual

冻结结果的双语论文图包。`en/` 保留英文版；`zh/` 对正文和附录选定图逐图重新渲染了图内标题、坐标轴、刻度、州名、图例和注释，使用中文字体。Aug26 exploratory 的 10 组图和其余 H1–H4、Stage 2、聚合图均来自同一冻结数据，只改变显示语言与版式，不改变任何数据、统计估计、置信区间或颜色含义，也未重跑分析。

- `figures_main/en/`、`figures_main/zh/`：正文英文/中文。
- `figures_appendix/en/`、`figures_appendix/zh/`：附录英文/中文。
- `manifests/FIGURE_LANGUAGE_INDEX.json`：逐图对应关系。
- Aug26 图明确属于 exploratory / 探索性州级案例，不属于 H1–H4。
''', encoding='utf-8')
tar = pkg.with_suffix('.tar.gz')
if tar.exists():
    tar.unlink()
shutil.make_archive(str(pkg), 'gztar', root_dir=pkg.parent, base_dir=pkg.name)
print(sha(tar), len(files))
