# Results contract v2.4

## Mandatory core tables

- `quality_report.json`
- `event_data_availability.csv`
- `estimand_data_availability.csv`: separate temporal/geographic feasibility for confirmatory power and external network-replication estimands
- `target_universe_sensitivity.csv`
- `exp_a_summary.csv`, `exp_a_event_metrics.csv`
- `exp_a_cluster_metrics.csv`, `exp_a_queue_dose.csv`: episode-level replication and queue-dose diagnostics
- `exp_b_main_results.csv`, `exp_b_estimand_results.csv`
- `exp_b_matching_balance.csv`, `exp_b_placebo.csv`
- `exp_f_external_validation.csv`, `exp_f_spatial_detection.csv`
- `exp_c_summary.csv`, `exp_c_repeatability.csv`, `prediction_feature_audit.csv`
- `closure_report.json`

## Secondary tables

- `exp_d_models.csv`, `exp_d_summary.csv`
- `exp_e_path_results.csv`, `exp_e_summary.csv`

## Interpretation rules

- `confirmatory_power` supports the energy-to-network question.
- `network_replication` supports cross-platform consistency only.
- `inference_admissible=0` estimates are descriptive diagnostics.
- B2 can become primary only through the frozen Experiment-A gate.
- A failed positive gate is not equivalent to evidence of no effect unless the required independent events were estimable.
- Path p-values are not interpreted without their BH-FDR q-values and effect sizes.
- All figures must be regenerable from the named source tables.
- A green closure also requires at least one identified recovery-debt model and at least one quality-admissible path group-event, because both are part of this paper's stated chain. A null coefficient or null path test is acceptable; a model that never ran or an empty admissible sample is incomplete evidence.
- The registered-event capacity check counts both dates and independence clusters. Consecutive schedules in one heat episode cannot be counted as independent replication. Winter schedules attributed to prior attack damage are transport/robustness evidence, not clean calibration clusters.

## Figure addition

- F15 compares national confirmatory effects under U2 (Ukraine + valid ASN, including country-only Geo) and U3 (Ukraine + valid ASN + valid Admin1). It is a mapping-sensitivity figure, not a new treatment definition.
