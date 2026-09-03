# Results contract v2.3

Every output belongs to one immutable `run_id` and is registered in `run_manifest.json`.  Each stage record contains file SHA-256 hashes or, for large directories, a clearly labelled directory-inventory hash over relative names and sizes.  A resumed run must match all frozen input hashes.

## Preflight, audit and B0 diagnostic panels

- `preflight_report.json`
- `quality_report.json`
- `f1_coverage.csv`
- `monthly_target_drift.csv`
- `f2_timeline.csv`
- `f2_signal.csv`
- `target_universe.parquet`
- `cycle_quality.parquet`
- `baseline_expected.parquet`
- `prefix_response_sparse/part_*.parquet`

## Experiment A and frozen sensor panels

- `exp_a_training_cycle_audit.csv`: slot-matched prospective normal cycles used to fit endpoint sensitivity
- `exp_a_validation_cycle_audit.csv`: held-out positive outage cycles and strictly pre-event slot-matched controls
- `exp_a_event_metrics.csv`: event-specific B0/B1/B2 AUPRC and `ΔAUPRC(B2-B1)`
- `exp_a_summary.csv`: global calibration gate, confidence interval, permutation result and event-consistency fraction
- `f3_pr.csv`: full threshold precision-recall curve
- `f3_auprc.csv`
- `exp_a_validation_long.csv`
- `exp_a_bootstrap_delta.csv`
- `exp_a_permutation_null.csv`
- `ip_sensor_score_parts_manifest.csv`
- `sensor_panel_summary.csv`
- `sensor_denominators.parquet`
- `sensor_event_panel/<event_id>.parquet`

A valid B2-positive result requires the preregistered lower confidence bound, minimum B2 sensor count, minimum held-out event count, and minimum fraction of held-out events with positive `ΔAUPRC`.

## Group-event features

- `group_event_features.parquet`: primary B2 if calibrated, otherwise B1
- `group_event_features_all_methods.parquet`
- `group_feature_summary.csv`

## Experiment B

- `f4_event_study.csv`
- `f5_state_time.csv`
- `f6_fingerprint.csv`
- `exp_b_main_results.csv`
- `exp_b_matches.csv`
- `exp_b_matching_balance.csv`
- `exp_b_anchor_sensitivity.csv`
- `exp_b_method_sensitivity.csv`
- `exp_b_placebo.csv`

`design_admissible` is authoritative.  Curves that fail sample-size, matching-balance or pretrend requirements remain diagnostic and are not silently promoted into manuscript figures.

## Experiment F: independent external validation

- `exp_f_external_validation.csv`
- `f13_external.csv`

## Experiment C: repeatability and prospective prediction

- `f7_heatmap.csv`
- `f8_pred_scatter.csv`
- `f8_model_perf.csv`: includes `fit_status` and `fit_failure_n`
- `prediction_feature_audit.csv`: feature-time, split-unit and model-fit audit
- `exp_c_repeatability.csv`
- `exp_c_permutation.csv`: joint within-event outcome-vector permutation null
- `exp_c_summary.csv`: includes `primary_model_fit_failures`
- `f9_variance.csv`

A diagnostic fallback prediction after an ML failure is labelled `fallback_failed`; it cannot satisfy the predictive closure gate.

## Experiment D: repeated exposure and recovery debt

- `exp_d_exposure_audit.csv`
- `exp_d_models.csv`
- `exp_d_summary.csv`
- `f10_dose.csv`
- `f10_survival.csv`

## Experiment E: conditional forwarding adaptation

- `exp_e_path_results.csv`
- `exp_e_summary.csv`
- `f11_quadrant.csv`
- `f12_ingress.csv`
- `path_edge_window.parquet`

Path outputs include raw AS/ASGeo JSD, target-specific JSD after excluding source-common baseline edges, high-confidence edge completeness, same-target-IP overlap diagnostics, and a quality-admission flag.  They remain conditional on `reached_target=1`.

## Figures

- `results/figures/zh/F1...F14.{pdf,svg,png}`
- `results/figures/en/F1...F14.{pdf,svg,png}`
- `F*.alt.txt`
- `F*.meta.json`: run id, mode, format, source-table paths and SHA-256 hashes
- `figure_manifest_{zh,en}.csv`
- `figure_warnings_{zh,en}.csv`

A figure is emitted only when its input contract is valid. F11/F12 are optional when path quality fails.  F14 reports held-out event-specific calibration gains and prevents one planned-outage event from carrying the B2 conclusion.

## Closure

- `closure_report.json`
- `closure_report.md`

The closure report is the only authoritative declaration of whether the experiment is complete.  Manuscript drafting must use the exact run id and table/figure hashes recorded in the final manifest.
