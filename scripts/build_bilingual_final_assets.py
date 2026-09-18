#!/usr/bin/env python3
"""Create English and Chinese renderings from the frozen final figure package.

No data or analysis is recomputed. English files are copied byte-for-byte;
Chinese files are downstream presentation renderings with Chinese title,
axis/reading notes and the same frozen raster plot. This keeps the scientific
geometry identical across languages while making the intended interpretation
explicit for a Chinese manuscript.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from PIL import Image


FONT = "/usr/share/fonts/wqy/wqy-microhei/wqy-microhei.ttc"
if not Path(FONT).exists():
    FONT = "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc"
FP = FontProperties(fname=FONT)

TITLES = {
    "01_aggregate_ips_fbs": ("聚合 IPS/FBS 中断信号对比", "时间（UTC）", "州（Oblast）"),
    "02_activity_distribution": ("正常时期 IP 活跃度分布", "正常响应活跃度 Activity", "IP 数量 / 累积分布"),
    "03_h1_cross_event_repeatability": ("H1：跨攻击端点损失排序重复性", "事件或端点损失指标", "跨事件损失排序关系"),
    "04_h3_h2_vs_h3_adjustment": ("H2 与 H3：Activity 调整前后对比", "Sensitivity 分位组", "攻击期间可达性损失"),
    "05_h4_activity_lift": ("H4：Activity 对损失贡献的提升", "Activity 分组", "损失贡献提升倍数"),
    "06_h4_loss_concentration": ("H4：IP 级损失集中性", "端点累计人口占比", "累计损失占比"),
    "07_aug26_sensitivity_forest": ("2024-08-26 探索性州级 Sensitivity 森林图", "Activity 调整后的 Q5−Q1 可达性下降（百分点）", "州（统一排序）"),
    "08_aug26_sensitivity_heatmap": ("2024-08-26 探索性州级 Sensitivity 热图", "Sensitivity 分位组 / Activity 分组", "州（Oblast）"),
    "stage2_activity_histogram": ("附录：正常 IP Activity 直方图", "正常响应活跃度 Activity", "IP 数量"),
    "stage2_activity_decile_share": ("附录：州内 Activity 十分位占比", "Activity 十分位（D1–D10）", "州（Oblast）"),
    "stage2_activity_by_oblast": ("附录：各州正常 Activity 分布", "正常响应活跃度 Activity", "州（Oblast）"),
    "h1_endpoint_distribution": ("附录：H1 端点损失分布", "端点可达性损失", "IP 数量 / 密度"),
    "h1_within_event": ("附录：H1 单次事件内端点异质性", "端点可达性损失", "事件或分组"),
    "h2_quintile_gradient": ("附录：H2 Sensitivity 分位梯度", "Sensitivity 分位组", "攻击损失"),
    "h2_event_effects": ("附录：H2 各事件效应", "战争攻击事件", "Sensitivity 组间效应"),
    "h3_adjusted_gradient": ("附录：H3 Activity 调整后的梯度", "Sensitivity 分位组", "调整后攻击损失"),
    "h3_partial_spearman": ("附录：H3 偏 Spearman 关联", "事件或模型规格", "偏 Spearman 相关系数"),
    "h4_population_vs_loss": ("附录：H4 人口占比与损失占比", "Activity / Sensitivity 分组", "占比"),
    "h4_sensitivity_lift": ("附录：H4 Sensitivity 贡献提升", "Sensitivity 分组", "损失贡献提升倍数"),
    "h4_activity_sensitivity": ("附录：Activity × Sensitivity", "Activity 分组", "Sensitivity 分组"),
    "h4_event_q5_vs_q1": ("附录：各事件 Q5 与 Q1 对比", "战争攻击事件", "Q5−Q1 损失"),
    "aug26_activity_forest": ("附录：2024-08-26 探索性 Activity 森林图", "Activity D10−D1 可达性下降（百分点）", "州（统一排序）"),
    "aug26_shock_vs_sensitivity": ("附录：冲击强度与 Sensitivity（探索性）", "州级冲击严重度", "州级 Sensitivity 指标"),
    "aug26_shock_vs_activity": ("附录：冲击强度与 Activity（探索性）", "州级冲击严重度", "州级 Activity 指标"),
    "aug26_activity_sensitivity_quadrants": ("附录：Activity × Sensitivity 四象限（探索性）", "正常 Activity", "Sensitivity"),
    "aug26_classification_map": ("附录：Sensitivity 州级分类图（探索性）", "经度", "纬度"),
    "09_aug26_paired_sensitivity_activity_forest": ("2024-08-26 探索性州级对照：Sensitivity 与 Activity", "效应估计（百分点）", "州（统一排序）"),
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def zh_render(src: Path, out_stem: Path, title: str, xlabel: str, ylabel: str) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    dpi = 160
    fig = plt.figure(figsize=(w / dpi, (h + 150) / dpi), facecolor="white")
    ax = fig.add_axes([0.01, 0.10, 0.98, 0.78])
    ax.imshow(im)
    ax.axis("off")
    fig.text(0.5, 0.965, title, ha="center", va="top", fontproperties=FP, fontsize=13)
    fig.text(0.5, 0.048, f"横轴：{xlabel}    ｜    纵轴：{ylabel}", ha="center", va="center", fontproperties=FP, fontsize=9, color="#333333")
    fig.text(0.5, 0.018, "中文版本：数据、颜色、区间与英文版完全一致；仅替换图形说明文字。", ha="center", va="center", fontproperties=FP, fontsize=7.5, color="#666666")
    for ext, dpi_out in (("png", 300), ("pdf", None), ("svg", None)):
        fig.savefig(out_stem.with_suffix("." + ext), dpi=dpi_out, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    root = Path("/home/wsl/XiaoLunWen_doc_complete_20260908")
    src = root / "paper_final_assets_20260912"
    dst = root / "paper_final_assets_20260912_bilingual"
    if dst.exists():
        shutil.rmtree(dst)
    for d in ("figures_main/en", "figures_main/zh", "figures_appendix/en", "figures_appendix/zh", "tables", "narrative", "manifests"):
        (dst / d).mkdir(parents=True)
    # Copy all non-figure final materials and frozen tables.
    for p in src.rglob("*"):
        if p.is_file() and "figures_main" not in p.parts and "figures_appendix" not in p.parts and p.name not in {"README.md"}:
            rel = p.relative_to(src)
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
    index = []
    for section in ("figures_main", "figures_appendix"):
        for p in sorted((src / section).glob("*.png")):
            stem = p.stem
            # English: all three original formats, unchanged.
            for ext in (".png", ".pdf", ".svg"):
                q = p.with_suffix(ext)
                if q.exists():
                    shutil.copy2(q, dst / section / "en" / q.name)
            key = stem
            if key not in TITLES:
                key = next((k for k in TITLES if stem.startswith(k)), stem)
            title, xlabel, ylabel = TITLES.get(key, (stem, "", ""))
            zh_stem = dst / section / "zh" / stem
            zh_render(p, zh_stem, title, xlabel, ylabel)
            index.append({"section": section, "stem": stem, "english": f"{section}/en/{stem}", "chinese": f"{section}/zh/{stem}", "data_unchanged": True})
    (dst / "manifests" / "FIGURE_LANGUAGE_INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = """# paper_final_assets_20260912_bilingual

这是冻结论文结果的双语图包。所有数据、统计估计、置信区间、颜色含义和图形几何均直接来自 `paper_final_assets_20260912`，本步骤没有重跑任何实验。

- `figures_main/en/`：正文英文版（原始冻结图，未改动）。
- `figures_main/zh/`：正文中文版（中文标题、轴含义和读图说明；底层图像与英文版完全一致）。
- `figures_appendix/en/`、`figures_appendix/zh/`：附录英文/中文版。
- `manifests/FIGURE_LANGUAGE_INDEX.json`：逐图语言对应关系。

Aug26 的所有图仍明确标为 exploratory / 探索性州级案例，不属于 H1–H4 主实验。
"""
    (dst / "README.md").write_text(readme, encoding="utf-8")
    # Rebuild final manifest with all bilingual file hashes.
    files = {}
    for p in sorted(dst.rglob("*")):
        if p.is_file() and p.name != "FINAL_PAPER_ASSET_MANIFEST.json":
            files[str(p.relative_to(dst)).replace("\\", "/")] = sha256(p)
    old_manifest = json.loads((src / "manifests" / "FINAL_PAPER_ASSET_MANIFEST.json").read_text())
    manifest = {
        "final_git_commit": old_manifest.get("final_git_commit"),
        "github_visible_head": old_manifest.get("github_visible_head"),
        "server_head": old_manifest.get("server_head"),
        "working_tree_status": old_manifest.get("working_tree_status"),
        "source_final_manifest_sha256": sha256(src / "manifests" / "FINAL_PAPER_ASSET_MANIFEST.json"),
        "bilingual_rendering": {"analysis_rerun": False, "english_byte_copied": True, "chinese_from_frozen_png": True, "font": FONT},
        "files_sha256": files,
    }
    (dst / "manifests" / "FINAL_PAPER_ASSET_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tar = dst.with_suffix(".tar.gz")
    if tar.exists(): tar.unlink()
    shutil.make_archive(str(dst), "gztar", root_dir=dst.parent, base_dir=dst.name)
    print(json.dumps({"package": str(dst), "tar": str(tar), "figure_count": len(index), "file_count": len(files)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
