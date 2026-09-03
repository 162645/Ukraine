"""Bilingual publication graphics: vector first, embedded fonts, accessible encodings."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7",
           "#E69F00", "#56B4E9", "#000000", "#999999"]
COLOR_PLANNED, COLOR_ATTACK = PALETTE[0], PALETTE[1]
DIVERGING = "RdBu_r"


def _find_cjk(cfg=None) -> tuple[str, str]:
    """Resolve a CJK font without bundling or redistributing font files.

    A user may set URESIL_CJK_FONT to a local font path.  If no CJK-capable
    font exists, Chinese rendering fails explicitly instead of silently emitting
    square glyphs in a submission figure.
    """
    env_name = str(getattr(cfg, "figures", {}).get("font_env_var", "URESIL_CJK_FONT")) if cfg is not None else "URESIL_CJK_FONT"
    candidates = []
    if os.environ.get(env_name):
        candidates.append(os.environ[env_name])
    candidates += [
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto-cjk-sc/NotoSansCJKsc-Regular.otf",
        "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    ]
    for raw in candidates:
        p = Path(raw)
        if p.exists():
            try:
                fm.fontManager.addfont(str(p))
                return fm.FontProperties(fname=str(p)).get_name(), str(p)
            except Exception:
                pass
    installed = {f.name: f.fname for f in fm.fontManager.ttflist}
    for name in ["Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei",
                 "Hiragino Sans GB", "SimHei", "Arial Unicode MS"]:
        if name in installed:
            return name, installed[name]
    raise RuntimeError(
        f"No CJK font found. Install Noto Sans CJK/Source Han Sans or set {env_name} to a local font path.")


def cjk_font_report(cfg=None) -> dict:
    """Resolve the Chinese font and verify representative manuscript glyphs."""
    name, path = _find_cjk(cfg)
    font = fm.get_font(path)
    cmap = font.get_charmap()
    probe = "乌克兰能源冲击网络韧性恢复迟滞"
    missing = [char for char in probe if ord(char) not in cmap]
    return {"name": name, "path": path, "probe": probe,
            "missing_glyphs": missing, "ok": not missing}


def apply_style(cfg, lang: str) -> None:
    plt.rcdefaults()
    base = float(cfg.figures["base_font_size_pt"])
    cjk_font = _find_cjk(cfg)[0] if cfg else _find_cjk()
    # Always put CJK font first in the stack, regardless of language
    # This ensures Chinese characters in legends/annotations render correctly
    serif_stack = [cjk_font, "DejaVu Serif", "serif"]
    matplotlib.rcParams.update({
        "font.family": "serif",
        "font.serif": serif_stack,
        "font.size": base,
        "axes.labelsize": base,
        "axes.titlesize": base,
        "legend.fontsize": max(float(cfg.figures["min_font_size_pt"]), base - 1),
        "xtick.labelsize": max(float(cfg.figures["min_font_size_pt"]), base - 1),
        "ytick.labelsize": max(float(cfg.figures["min_font_size_pt"]), base - 1),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.7,
        "lines.linewidth": 1.35,
        "lines.markersize": 4.2,
        "legend.frameon": False,
        "grid.linewidth": 0.4,
        "grid.alpha": 0.25,
        "figure.dpi": 150,
        "savefig.dpi": int(cfg.figures["png_dpi"]),
        "savefig.bbox": "tight",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "axes.unicode_minus": False,
        "axes.prop_cycle": matplotlib.cycler(color=PALETTE),
    })


def save_fig(fig, fig_id: str, cfg, lang: str, source_files: list[Path], alt_text: str) -> list[str]:
    out = cfg.out_dir("results_figures", lang=lang)
    if cfg.mode == "demo":
        fig.text(0.5, 0.5, "SYNTHETIC / DEMO", ha="center", va="center", rotation=30,
                 fontsize=28, color="0.5", alpha=0.18, fontweight="bold")
    paths = []
    effective_png_dpi = int(cfg.figures.get("demo_png_dpi", 150) if cfg.mode == "demo" else cfg.figures["png_dpi"])
    for ext in cfg.figures["formats"]:
        p = out / f"{fig_id}.{ext}"
        fig.savefig(p, dpi=effective_png_dpi if ext == "png" else None)
        paths.append(str(p))
    plt.close(fig)
    # Sidecars are machine-readable and let manuscript/artifact tooling verify
    # exactly which tables produced a figure while carrying accessibility text.
    (out / f"{fig_id}.alt.txt").write_text(alt_text, encoding="utf-8")
    sources = []
    for src in source_files:
        src = Path(src)
        sources.append({
            "path": str(src),
            "exists": src.exists(),
            "bytes": src.stat().st_size if src.exists() else None,
            "sha256": hashlib.sha256(src.read_bytes()).hexdigest() if src.exists() and src.is_file() else None,
        })
    resolved_font = None
    if lang == "zh":
        try:
            resolved_font = _find_cjk(cfg)[0]
        except Exception:
            resolved_font = None
    metadata = {
        "figure_id": fig_id, "language": lang, "run_id": cfg.run_id,
        "resolved_font": resolved_font,
        "mode": cfg.mode, "demo": cfg.mode == "demo",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formats": list(cfg.figures["formats"]), "png_dpi": effective_png_dpi,
        "alt_text": alt_text, "source_tables": sources,
    }
    (out / f"{fig_id}.meta.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths + [str(out / f"{fig_id}.alt.txt"), str(out / f"{fig_id}.meta.json")]
