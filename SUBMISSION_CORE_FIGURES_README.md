# Submission core figures

This directory is a clean paper-facing figure set rendered directly from the
frozen `paper_v24_real_01` result tables. It does not select from or depend on
any previously generated figure. It never reruns v2.4.

## Main-text selection

1. **Core Figure 1 - calibration gate.** Scheduled-outage-supervised B2 improves
   AUPRC by only 0.008 over B1; the confidence interval crosses zero and the
   permutation test is not significant (`p=0.323`).
2. **Core Figure 2 - Experiment B generalization.** On the five
   inference-admissible held-out attacks, B2 has a larger maximum deficit in
   3/5 events but a larger cumulative deficit in only 2/5. The sign is not
   consistent across estimands or attacks.
3. **Core Figure 3 - Experiment B measurement.** Event-time curves show that
   attack-aligned reachability deficits are observable, while magnitude and
   recovery are heterogeneous. Sumy is gray and descriptive because it fails
   the primary pretrend gate.
4. **Core Figure 4 - fingerprint validation.** ASN-Admin1 rankings have weak and
   incomplete cross-event repeatability, and the apparent history-model gain
   does not pass permutation validation (`p=0.294`).

Together, the figures support a negative/boundary closure: attack-aligned
network effects are observable, but scheduled-outage calibration does not
produce a consistently generalizing B2 panel, and the resulting ASN-Admin1
responses are not validated as repeatable or predictive fingerprints.

## Outputs

`runs/paper_v24_real_01/results/figures_submission_core/{zh,en}` contains a
four-page combined PDF and individual PDF, 300-dpi PNG, and SVG files.

## Reproduce without rerunning v2.4

```bash
MPLBACKEND=Agg MPLCONFIGDIR=.mplconfig PYTHONPATH=src \
  python3 scripts/render_submission_core_figures.py --run-id paper_v24_real_01
```
