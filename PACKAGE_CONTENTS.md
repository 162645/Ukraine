# Package contents — v2.4

## Entry points

- `run_all.py` — immutable run orchestrator for real and synthetic modes.
- `scripts/run_paper.sh` — full real-data execution using a new v2.4 run ID.
- `scripts/reproduce_figures.sh` — recreate bilingual figures from completed tables.
- `scripts/inspect_closure.py` — summarize the machine-readable closure report.
- `scripts/freeze_mapping_manifest.py` — freeze and verify the historical IP mapping snapshot.
- `scripts/check_environment.py` — verify required scientific Python packages and versions.
- `check_ch.sh` — read-only ClickHouse connectivity and schema smoke test.

## Frozen analysis inputs

- `config/experiment_v2.yaml` — analysis plan `analysis_plan_v2_4_1_segmented_schedule`.
- `config/event_registry_v2.csv` — attack, outage and external network clocks plus independent power/network regions.
- `config/planned_outage_schedule_v1.csv` — verified final-version queue segments, local/UTC clocks, episode clusters and source URLs.
- `config/outage_exposure_registry_v2.csv` — interval-level official outage exposure.
- `config/admin1_aliases_v1.csv` — canonical country/Admin1 aliases.
- `config/mapping_manifest_v2.frozen.json` — frozen target and hop mapping snapshot contract.
- `config/mapping_manifest_v2.json` — blank template for a newly frozen snapshot.
- `config/experiment_v2.local.example.yaml` and `.env.example` — credential-free local examples.

## Scientific code

- `src/uresil/event_design.py` — clean baseline, transition and outcome stages; confirmatory and replication estimands.
- `src/uresil/audit.py`, `panels.py`, `sensor_panels.py` — denominator, support, target-universe, estimand-availability and frozen endpoint panels.
- `src/uresil/exp_a_calibration.py` — scheduled-outage weak-supervision calibration and held-out validation.
- `src/uresil/exp_b_event_study.py` — clean-baseline-centered matched event studies and placebos.
- `src/uresil/exp_f_external_validation.py` — independent temporal/spatial replication.
- `src/uresil/exp_c_fingerprint.py` — repeatability, ICC and whole-event prospective prediction.
- `src/uresil/exp_d_recovery_debt.py` — official exposure and observable recovery-debt models.
- `src/uresil/exp_e_path.py` — quality-gated AS/ASGeo direct-edge adaptation with BH-FDR.
- `src/uresil/viz/` — bilingual vector-first F1–F15 publication graphics.
- `src/uresil/validate.py` — positive, valid-negative, incomplete-evidence and design-failure closure states.

## Query contracts and tests

- `sql/` — ClickHouse query contracts using the current table fields.
- `tests/` — 20 unit tests covering denominator, event staging, calibration, geography, exposure, path, prediction and provenance.

## Documentation

- `README.md` — quick start and claim boundaries.
- `docs/ANALYSIS_PLAN_V2_4.md` — estimands, hypotheses, gates and interpretation.
- `docs/RUNBOOK_V2_4.md` — staged real-data operation and failure triage.
- `docs/RESULTS_CONTRACT_V2_4.md` — exact output tables and claim rules.
- `docs/RELEASE_NOTES_V2_4.md` — changes driven by the latest real run.
- `docs/ARTIFACT_EVALUATION.md` — independent artifact reproduction guide.
- `docs/archive_v2_3/` — historical documents retained only for provenance; do not follow them for a new run.
- `VALIDATION_STATUS.md` — release checks completed without the remote database.
- `PACKAGE_MANIFEST.txt` — SHA-256 manifest generated at packaging time.

Generated runs, credentials, cached bytecode and bundled font files are deliberately excluded.
