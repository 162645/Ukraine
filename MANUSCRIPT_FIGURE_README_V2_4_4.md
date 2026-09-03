# Reviewer-facing manuscript figures

This package contains the selected v2.4.4 paper figure set. It reads the frozen
`paper_v24_real_01` tables and never reruns the v2.4 core experiment.

## Recommended placement

- Main text: six core-question/design figures (`Fig1` to `Fig6`).
- Supplement: four robustness/secondary figures (`FigS1` to `FigS4`).
- Do not paste the older six-page closure audit book into the main paper.

The reasoning and figure-by-figure claims are documented in
`docs/MANUSCRIPT_FIGURE_PLAN_V2_4_4.md`.

## Reproduce

```bash
cd /Users/bytedance/WorkPlace/code_file/TTADK/else/ukraine/ukraine_resilience_experiment_v2_4
MPLBACKEND=Agg MPLCONFIGDIR=.mplconfig PYTHONPATH=src \
  python3 scripts/render_manuscript_figures.py --run-id paper_v24_real_01
```

Outputs are written to
`runs/paper_v24_real_01/results/figures_manuscript/{en,zh}` as combined PDFs and
individual PDF, 300-dpi PNG, and editable SVG files.

## Standalone Experiment B pack

`results/figures_manuscript/experiment_b/{en,zh}` contains five focused figures:
B1/B2 held-out generalization, event outcome profile, event-time dynamics,
anchor-shift sensitivity, and the internal/external evidence-gate matrix. Each
is available as an individual PDF/PNG/SVG plus a five-page combined PDF.
