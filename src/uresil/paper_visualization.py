"""Shared, paper-sized visualization contract for the frozen Stage 0--3.5 data.

This module deliberately contains no scientific estimators.  It only defines labels,
fonts, missing-value rendering and reproducible export metadata for the paper figures.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Mapping

import matplotlib as mpl
import matplotlib.pyplot as plt

PLOT_LABELS = {
    "en": {
        "ips": "IPS (responsive IP count)", "fbs": "FBS (active /24 count)",
        "ips_ratio": "IPS ratio to preceding 7-day mean", "fbs_ratio": "FBS ratio to preceding 7-day mean",
        "activity": "Activity A_i", "outage_hours": "Outage hours per day",
        "date": "UTC date", "time": "UTC time", "oblast": "Oblast",
        "primary": "Primary", "augmented": "Augmented", "missing": "Missing / not observed",
        "outside": "Outside support", "attack": "Attack anchor", "baseline": "7-day mean",
        "threshold90": "0.90 threshold", "threshold95": "0.95 threshold",
    },
    "zh": {
        "ips": "IPS（响应 IP 数）", "fbs": "FBS（活跃 /24 数）",
        "ips_ratio": "IPS / 前 7 天均值", "fbs_ratio": "FBS / 前 7 天均值",
        "activity": "Activity A_i", "outage_hours": "每日中断小时数",
        "date": "UTC 日期", "time": "UTC 时间", "oblast": "州",
        "primary": "Primary（高置信）", "augmented": "Augmented（扩展）", "missing": "缺失/未观测",
        "outside": "不在支持范围", "attack": "攻击锚点", "baseline": "前 7 天均值",
        "threshold90": "0.90 阈值", "threshold95": "0.95 阈值",
    },
}

# Canonical names used by the frozen tables; never mix Odessa/Odesa in labels.
STATE_ZH = {
    "Autonomous Republic of Crimea": "克里米亚自治共和国", "Cherkasy Oblast": "切尔卡瑟州",
    "Chernihiv Oblast": "切尔尼戈夫州", "Chernivtsi Oblast": "切尔诺夫策州", "Dnipropetrovsk Oblast": "第聂伯罗彼得罗夫斯克州",
    "Donetsk Oblast": "顿涅茨克州", "Ivano-Frankivsk Oblast": "伊万诺-弗兰科夫斯克州", "Kharkiv Oblast": "哈尔科夫州",
    "Kherson Oblast": "赫尔松州", "Khmelnytskyi Oblast": "赫梅利尼茨基州", "Kirovohrad Oblast": "基洛沃格勒州",
    "Kyiv City": "基辅市", "Kyiv Oblast": "基辅州", "Luhansk Oblast": "卢甘斯克州", "Lviv Oblast": "利沃夫州",
    "Mykolaiv Oblast": "尼古拉耶夫州", "Odesa Oblast": "敖德萨州", "Poltava Oblast": "波尔塔瓦州",
    "Rivne Oblast": "罗夫诺州", "Sevastopol": "塞瓦斯托波尔", "Sumy Oblast": "苏梅州", "Ternopil Oblast": "捷尔诺波尔州",
    "Transcarpathia Oblast": "外喀尔巴阡州", "Vinnytsia Oblast": "文尼察州", "Volyn Oblast": "沃伦州",
    "Zaporizhzhia Oblast": "扎波罗热州", "Zhytomyr Oblast": "日托米尔州",
}

COLORS = {"ips": "#c43d4b", "fbs": "#2f7f76", "primary": "#7b3294", "augmented": "#d95f02", "missing": "#eeeeee", "outside": "#f5f5f5"}

def configure_theme(lang: str = "en") -> bool:
    """Set a restrained print theme and return whether a Chinese font was found."""
    candidates = ["DejaVu Sans", "Arial", "Liberation Sans"] if lang == "en" else ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "Source Han Sans SC"]
    available = {f.name for f in mpl.font_manager.fontManager.ttflist}
    chosen = next((f for f in candidates if f in available), candidates[0])
    has_cjk = any(f in available for f in ["Noto Sans CJK SC", "Microsoft YaHei", "SimHei", "Source Han Sans SC"])
    if lang == "zh" and not has_cjk:
        warnings.warn("No Chinese font found; Chinese figures may not render correctly.", RuntimeWarning)
    mpl.rcParams.update({"font.family": chosen, "font.size": 8, "axes.titlesize": 9, "axes.labelsize": 8,
                         "xtick.labelsize": 7, "ytick.labelsize": 7, "legend.fontsize": 7,
                         "axes.linewidth": 0.7, "lines.linewidth": 0.9, "savefig.bbox": "tight",
                         "axes.spines.top": False, "axes.spines.right": False, "axes.unicode_minus": False})
    return has_cjk

def zh_name(name: str, lang: str) -> str:
    return STATE_ZH.get(name, name) if lang == "zh" else name

def save_figure(fig: plt.Figure, base: Path, lang: str, metadata: Mapping[str, Any]) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=350, facecolor="white")
    fig.savefig(base.with_suffix(".pdf"), metadata={"Creator": "uresil paper visualization"})
    fig.savefig(base.with_suffix(".svg"), metadata={"Creator": "uresil paper visualization"})
    base.with_suffix(".meta.json").write_text(json.dumps(dict(metadata, language=lang, dpi=350, same_source_data=True), indent=2), encoding="utf-8")
    plt.close(fig)

def state_order(values):
    return sorted({str(v) for v in values if str(v) and str(v) != "nan"}, key=lambda x: (STATE_ZH.get(x, x), x))

def shade_missing(ax, times, missing, color=COLORS["missing"]):
    """Draw narrow bands for known missing cycles; never interpolate or connect them."""
    for t in times[missing]:
        ax.axvspan(t, t, color=color, alpha=0.9, linewidth=2.0, zorder=0)
