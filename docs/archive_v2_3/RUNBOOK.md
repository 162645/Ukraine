# Operational runbook

## A. One-time preparation

1. Create a clean virtual environment and install `requirements.txt`.
2. Put local ClickHouse connection values in `config/experiment_v2.local.yaml` when you want one-command local runs; do not commit that file.
3. Review table names and the data-centre label in `config/experiment_v2.yaml`.
4. Confirm whether the Ping scanner truly attempted the same frozen target inventory every two hours. If not, set `static_full_scan_confirmed=false` and do not interpret missing response rows as endpoint outages.
5. Review all event UTC anchors, treated Admin1 lists, roles and confound flags in `event_registry_v2.csv`.
6. Review every exposure interval and scope in `outage_exposure_registry_v2.csv`.
7. Complete the Admin1 aliases and freeze the mapping snapshot with `scripts/freeze_mapping_manifest.py`, or let `run_all.py` auto-freeze it on the first local run. When the paper cutoff has no rows in your local mapping table, the runner automatically falls back to the latest available mapping snapshot.
8. Run `pytest`.

## B. Paper run

```bash
scripts/run_paper.sh
```

The wrapper now auto-generates a timestamped `RUN_ID` when you do not provide one. You can still override it:

```bash
RUN_ID=paper_v23_real_01 scripts/run_paper.sh
```

For the local convenience path, `python3 run_all.py --stage all` auto-discovers `config/experiment_v2.local.yaml` and auto-freezes the mapping manifest when needed.

Follow the stages in order.

### 1. `preflight`

Hard failures:

- missing required ClickHouse columns;
- invalid or duplicate event records;
- insufficient planned training/validation events;
- absent Ping denominator confirmation;
- frozen mapping database snapshot does not match its manifest.

Inspect `preflight_report.json`.

### 2. `audit`

Inspect:

- cycle interval and completeness;
- monthly target-set drift;
- valid target ASN and Admin1 ratios;
- import-status failures;
- response-set expansion or contraction.

Do not proceed if target Admin1 contains ISP domains, cities, countries in place of Admin1, or blank keys. The target group must be `target_asn|target_country|target_admin1` from the target IP mapping.

### 3. `panels`

This stage creates memory-bounded B0 response diagnostics and same-slot expectations. Verify:

- two-hour cycles;
- zero-response cells are materialised only for complete cycles;
- equal-/24 national reach is not a response-only mean;
- sparse partitions cover the full study interval without overlap.

### 4. `expA`

Experiment A fits endpoints only on scheduled-outage training events and validates B0/B1/B2 on whole held-out scheduled-outage events.

Inspect:

- full PR curves, not two endpoint points;
- event × Admin1 block-bootstrap `ΔAUPRC(B2-B1)`;
- permutation null;
- B1 and B2 sensor counts;
- `exp_a_validation_cycle_audit.csv`: every negative control is clean, slot-matched and strictly before its held-out event;
- `exp_a_event_metrics.csv`: B2 improves over B1 in the preregistered fraction of held-out events, rather than being carried by one event.

A positive calibration claim requires the frozen success gate. If it fails, do not tune the rule against attack results. Continue with B1 under the negative-calibration branch.

### 5. `sensorPanels`

This is the key denominator-correction stage. It builds every event-cycle-prefix cell from the complete selected B1/B2 endpoint set. Missing responses are zero; expected normal responders are the sum of endpoint `pN`.

Inspect `sensor_panel_summary.csv`, `sensor_denominators.parquet`, and at least one event panel.

### 6. `features`

Group-event outcomes are generated from the primary frozen method:

- B2 after successful calibration;
- otherwise B1.

Inspect group sample gates, prefix counts and recovery censoring. Do not mix B0 outcomes into primary resilience fingerprints.

### 7. `expB`

Regional attacks use same-ASN controls selected from pre-event covariates. Inspect:

- `exp_b_matching_balance.csv` before and after matching;
- minimum pair count;
- maximum absolute standardised mean difference;
- event-study pretrend equivalence;
- anchor ±2/±4/±6 hour sensitivity;
- immediate drop, maximum deficit, AUC and T90;
- B1/B2 method sensitivity;
- complete outputs for 17 November, 28 November and the 17 September Sumy blind test.

National events use historical same-slot estimates and placebo dates; they do not pretend to have an untreated region.

### 8. `expF`

Compare the internally detected onset and anomalous Admin1 set with frozen third-party network observations. This is independent validation, not a training feature. Inspect temporal offset and spatial Jaccard.

### 9. `expD`

Before modelling recovery debt, inspect `exp_d_exposure_audit.csv`:

- exposure hours must vary;
- regional intervals must apply only to listed canonical Admin1 regions;
- national intervals apply to all groups;
- within-event fixed-effect models require within-event variation.

All-zero exposure is a pipeline failure, not a null finding.

### 10. `expE`

Interpret only quality-admissible rows. Confirm:

- target group key is valid;
- analysis is conditional on `reached_target=1`;
- stars, reserved/private IPs, AS0 and unknown Geo break adjacency;
- direct-edge completeness and sample thresholds pass;
- ingress frequencies are per 1,000 valid traces, event-specific;
- JSD exceeds its multinomial/permutation null;
- target-specific JSD remains after removing baseline edges seen across the configured fraction of target groups, reducing Frankfurt/source-side confounding;
- `common_target_ip_n` and overlap shares are adequate for the random-four-IP-per-/24 limitation to be transparent.

The same-target-IP fields are overlap diagnostics, not paired-path estimates. If overlap or quality gates fail, retain a diagnostic or small case study and remove the general path-adaptation claim.

### 11. `expC`

Prediction is rolling-origin by whole event. Inspect `prediction_feature_audit.csv` first. Every feature must predate the held-out event. Then inspect:

- repeatability correlations and ICC;
- event-equal MAE/AUPRC;
- performance versus the simple group-history baseline;
- joint within-event outcome-vector permutation p-value;
- calibration across several held-out events;
- `fit_status` and `fit_failure_n`: M4/M5 must fit successfully for every event used in the primary closure.

Near-perfect performance is treated as leakage until disproved. A diagnostic fallback to M3 after an ML exception is retained for debugging but cannot count as M4/M5 evidence.

### 12. `figures`

Figures are output in Chinese and English as PDF, SVG and 600-dpi PNG. A skipped figure means its evidence table was absent or invalid. Do not manually recreate an empty scientific result.

### 13. `validate`

Read both closure reports before drafting the paper. A path-quality warning may be optional; a denominator, mapping, attack-validation or leakage failure is not.

## C. First debugging files

- `run_manifest.json`
- `logs/run.log`
- `results/tables/preflight_report.json`
- `results/tables/quality_report.json`
- `results/tables/exp_a_summary.csv`
- `results/tables/sensor_panel_summary.csv`
- `results/tables/exp_b_matching_balance.csv`
- `results/tables/exp_b_main_results.csv`
- `results/tables/exp_f_external_validation.csv`
- `results/tables/prediction_feature_audit.csv`
- `results/tables/exp_d_exposure_audit.csv`
- `results/tables/exp_e_summary.csv`
- `results/tables/figure_warnings_zh.csv`
- `results/tables/closure_report.json`
