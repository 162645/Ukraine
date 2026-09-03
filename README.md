# Ukraine Energy Shock & Internet Resilience — reproducible pipeline v2.4

Formal-run readiness and the selectively integrated v2.4.2 supplement are documented in
`PRE_RUN_DECISION_2026-08-05.md`. The pipeline now includes auxiliary stage `expG` for the
frozen 24 July operator execution-versus-cancellation falsification.

Before the one-shot real run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-weather.txt
python scripts/download_era5_land.py --start 2024-06-22 --end 2025-01-09
python scripts/build_weather_admin1_2h.py --admin1-geojson /absolute/path/ukraine_admin1.geojson
python scripts/archive_public_sources.py --root .
python scripts/ingest_telegram_export.py /absolute/path/result.json --root .
python scripts/verify_evidence_archive.py --root .
./scripts/run_paper.sh --check --run-id paper_v24_frozen_01 --no-resume --clean-run
```

This package implements one fixed paper question:

> Can precisely registered scheduled outages calibrate power-sensitive Internet endpoints, enabling remote measurement of wartime energy shocks and tests of repeatable/predictive ASN × country × Admin1 resilience?

The pipeline does **not** require the hypotheses to be positive. It distinguishes a scientifically valid negative finding from missing or invalid evidence.

## v2.4 scientific corrections

1. **Three event times are separated.** `attack_start_utc`, `outage_start_utc`, and `network_anomaly_start_utc` are never collapsed. Matching and pretrend covariates use a clean interval ending before the earliest credible treatment boundary. The attack-to-outage interval is a transition phase, not untreated pretrend.
2. **Two independent regional estimands are produced.** `confirmatory_power` uses independently registered power-affected regions. `network_replication` uses third-party network-observed regions only for non-causal replication. This is essential for 28 November, where the two region sets differ.
3. **Regional matched estimates are clean-baseline centered DID.** Each treated-control pair's normal difference is removed before event dynamics are estimated.
4. **Pretrend is an equivalence test.** Both level and slope confidence intervals must lie within practical margins. A nonsignificant classical trend p-value is not treated as proof of equivalence.
5. **National and regional geography are separated.** Country-only Ukrainian mappings remain in national analyses but never enter Admin1 inference. The target-universe audit reports U1/U2/U3 sensitivity counts.
6. **Scheduled-outage calibration remains frozen and falsifiable.** B2 is primary only if it beats B1 on the operational holdout gate; publication-grade support additionally requires at least two independent validation outages and the configured exposure support.
7. **Repeatability and prediction gates are stronger.** Repeatability needs at least three admissible event pairs, positive bootstrap lower bound, and nonzero ICC. Prediction needs at least three whole-event holdouts, no leakage, no primary-model failures, event-wise improvement, and permutation support.
8. **Recovery debt cannot silently fail.** Preflight checks `statsmodels`; Experiment D also provides a documented clustered NumPy fallback and reports whether the preregistered exposure is identified.
9. **Path claims use BH-FDR.** Only quality-admissible, target-reached, direct observed AS/ASGeo edges enter claims. Raw and corrected p-values remain available.
10. **Publication graphics are bilingual and vector-first.** Every figure is emitted in PDF, SVG, and 600-dpi PNG. Color, line style, marker shape, source-table hashes, alt text, and resolved font metadata are retained.

## Data contract

The Ping table stores successful responses only. Under the explicitly confirmed static full-scan design, a missing row for a sensor IP in an import-complete cycle is a non-response. A missing/failed Ping artifact is an acquisition gap, not a zero.

Target geography comes only from the frozen target-IP mapping snapshot. Traceroute path geography comes from each observed hop. `ASN=0`, unknown Geo, private/reserved hops, and `*` break high-confidence direct adjacency.

## Install

Python 3.11 or 3.12 is recommended because scientific/database wheel availability is most reliable on those versions.

```bash
unzip ukraine_resilience_experiment_v2_4.zip
cd ukraine_resilience_experiment_v2_4
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
PYTHONPATH=src pytest -q
```

Expected release result:

```text
25 passed
```

## Configure ClickHouse without committing credentials

```bash
cp .env.example .env.local
# Edit .env.local, then optionally verify connectivity:
./check_ch.sh
```

`config/experiment_v2.local.example.yaml` is also provided, but environment variables are recommended. The release contains no live database password.

Chinese figures require a local CJK font. The renderer searches common system fonts. When needed:

```bash
export URESIL_CJK_FONT='/path/to/NotoSansCJK-Regular.ttc'
```

No font file is distributed in this artifact.

On macOS the renderer automatically prefers `/System/Library/Fonts/Hiragino Sans GB.ttc` when present. Preflight now verifies both the resolved path and representative Chinese glyph coverage before a real run starts.

## Registered scheduled-outage evidence

The frozen schedule registry now contains official, final-version segmented schedules for 7, 20 and 28 July; 19–21 August; and 9 December. It preserves Europe/Kyiv local time, UTC conversion, queue count, zero-queue gaps, source URL, episode cluster and publication eligibility. Two summer validation clusters are currently eligible; the three consecutive August dates count as one cluster. The 9 December schedule is a post-attack-recovery transport test and cannot manufacture clean replication.

Preflight records date and independent-cluster capacity as `registered_core_closure_capacity` before the long database stages begin.

## Run

Recommended one-command entry:

```bash
./scripts/run_paper.sh --run-id paper_v24_real_01
```

What the launcher does by default:
- auto-loads `.env.local` when present
- runs the full pipeline in `real` mode unless `--mode demo` is passed
- enables `--resume` by default so the same `RUN_ID` continues a stopped run
- retries a failed top-level invocation a small number of times with the same `RUN_ID`

Useful variants:

```bash
./scripts/run_paper.sh --mode demo --run-id paper_v24_demo_01
./scripts/run_paper.sh --run-id paper_v24_real_01 --clean-run
./scripts/run_paper.sh --run-id paper_v24_real_01 --check
```

Manual resume remains available:

```bash
python run_all.py --mode real --run-id "$RUN_ID" --stage all --resume
```

Recreate only bilingual figures and the closure report after a completed run:

```bash
RUN_ID=paper_v24_real_01 scripts/reproduce_figures.sh
```

Inspect closure:

```bash
python scripts/inspect_closure.py paper_v24_real_01
```

## Stage order

```text
preflight → audit → panels → expA → sensorPanels → features
→ expB → expF → expD → expE → expC → figures → validate
```

## First outputs to inspect

```text
runs/<run_id>/results/tables/preflight_report.json
runs/<run_id>/results/tables/quality_report.json
runs/<run_id>/results/tables/event_data_availability.csv
runs/<run_id>/results/tables/estimand_data_availability.csv
runs/<run_id>/results/tables/target_universe_sensitivity.csv
runs/<run_id>/results/tables/exp_a_summary.csv
runs/<run_id>/results/tables/exp_b_estimand_results.csv
runs/<run_id>/results/tables/exp_b_target_universe_sensitivity.csv
runs/<run_id>/results/tables/exp_f_spatial_detection.csv
runs/<run_id>/results/tables/exp_c_summary.csv
runs/<run_id>/results/tables/exp_d_summary.csv
runs/<run_id>/results/tables/exp_e_summary.csv
runs/<run_id>/results/tables/closure_report.json
```

## Closure states

- `GREEN_POSITIVE_CHAIN`: the complete positive chain is estimable and supported.
- `GREEN_VALID_NEGATIVE_FINDINGS`: the complete chain is estimable, but one or more preregistered hypotheses are not supported. This is a valid paper result.
- `YELLOW_INCOMPLETE_CORE_EVIDENCE`: the pipeline is coherent, but there are too few independent events or holdouts.
- `RED_DATA_OR_DESIGN_FAILURE`: provenance, denominator, frozen sensor, leakage, or event-inference contracts failed.

## Claim boundaries

- Network measurements are functional evidence, not physical damage proof.
- B2 trained from L3 national outage windows is weak supervision, not IP-level power truth.
- `network_replication` is an external consistency estimand, not a causal treatment definition.
- Country-only Geo participates only in national analysis.
- AS/ASGeo results are conditional on the Frankfurt vantage point, target reachability, sampled destinations, and direct observed hops.
- Negative calibration, repeatability, or prediction results are reported rather than tuned away.

See `docs/ANALYSIS_PLAN_V2_4.md`, `docs/RUNBOOK_V2_4.md`, and `docs/RESULTS_CONTRACT_V2_4.md`.
