# power_availability_infrastructure_final_validation_v2

This is the final validation addendum after v1. It preserves v1 and does not read war-outcome panels.

- Period: 2024-06-01--2025-01-31 UTC.
- Frozen inputs: v1 master, verified schedule registry, event-level response cache, cycle-quality registry, CAIDA evidence.
- 67 unique verified schedule event IDs; 263 state/event rows; 108 matched cached rows.
- 1,170,227 IPs in the mapped master across 17 oblasts.
- Event-level cached counts do not contain raw paired probe timestamps; the referent registry labels this explicitly.
- Figure 26 is not generated because there are no verified events after the v1 boundary.
- The grouped-binomial interaction model is not reported as an inferential result because numerical separation produced unstable coefficients.
- All generated figures have zh/en PNG, PDF and SVG with shared data arrays.

See `outputs/FINAL_VALIDATION_REPORT.md`, `outputs/PAPER_CLOSURE_SUMMARY_ZH.md`, `outputs/PAPER_CLOSURE_SUMMARY_EN.md`, `outputs/FINAL_MANIFEST.json`, and `outputs/NOT_GENERATED.md`.
