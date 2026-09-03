# Artifact execution and evaluation guide — v2.4

This guide is for an independent researcher who has read-only access to the same ClickHouse tables but did not write the pipeline.

## Scientific scope

The artifact implements one chain:

1. use independently registered scheduled outages as weak supervision;
2. compare B2 outage-sensitive endpoints with the B1 historical-stability baseline on held-out scheduled outages;
3. freeze B1 or B2 before opening held-out attacks;
4. estimate clean-baseline-centered national and regional event dynamics;
5. test ASN × country × Admin1 repeatability and whole-event prospective prediction;
6. estimate recovery debt when exposure has identifiable variation;
7. test AS/ASGeo adaptation only in quality-admissible, target-reaching direct-hop samples.

The pipeline never treats network measurements as proof of physical damage. `network_replication` uses third-party network-observed regions only as an independent replication target, never as the confirmatory power-treatment definition.

## Minimal offline reproduction

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/check_environment.py
PYTHONPATH=src pytest -q
python run_all.py --mode demo --run-id artifact_smoke_v24 --stage all --clean-run
```

Expected release checks:

- 17 tests pass;
- all 15 Chinese and 15 English demo figures render;
- each demo figure has a visible synthetic watermark;
- each figure has PDF, SVG, PNG, alt text and metadata;
- demo PNG uses 150 dpi for speed; a real run uses 600 dpi;
- `_DEMO_NOTICE.txt` is present and demo values are not scientifically interpretable.

## Real-data prerequisites

1. Read-only access to the ClickHouse tables listed in `README.md` and the SQL contracts.
2. Factual confirmation that the scanner attempted its frozen full target inventory each two-hour cycle. Otherwise set `static_full_scan_confirmed: false`; the response-only Ping table cannot support zero materialization.
3. Review and freeze `event_registry_v2.csv`, especially attack, outage and external network times.
4. Review `outage_exposure_registry_v2.csv`; coarse national windows cannot be represented as precise IP-level power truth.
5. Verify or regenerate `mapping_manifest_v2.frozen.json`.
6. Install a local CJK font or set `URESIL_CJK_FONT` for Chinese figures. The artifact does not distribute font files.

## Reproduce the real analysis

```bash
source .env.local
RUN_ID=paper_v24_real_01 scripts/run_paper.sh
```

For a staged run:

```bash
python run_all.py --mode real --run-id "$RUN_ID" --stage preflight audit
python run_all.py --mode real --run-id "$RUN_ID" --stage panels expA sensorPanels --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage features expB expF --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage expD expE expC --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage figures validate --resume
```

Do not resume a v2.3 directory: v2.4 changes event stages, estimands, target universe and result contracts.

## Figure and table reproduction map

- F1–F2: audit coverage, import completeness and event timeline.
- F3/F14: Experiment A calibration curves, AUPRC and event-specific B2−B1 gains.
- F4–F6: Experiment B clean-stage event studies, spatial responses and planned-versus-attack fingerprints.
- F7–F9: Experiment C group-event outcomes, prospective predictions and variance components.
- F10: Experiment D exposure/recovery outputs.
- F11–F12: Experiment E conditional path adaptation and normalized ingress relations.
- F13: Experiment F independent temporal/spatial replication.
- F14: event-specific held-out calibration gains.
- F15: national effect sensitivity to U2 country-only inclusion versus U3 strict Admin1.

Every figure metadata sidecar contains the producing source-table paths and SHA-256 hashes. Recreate only figures with:

```bash
RUN_ID=paper_v24_real_01 scripts/reproduce_figures.sh
```

## Evaluation checklist

1. `run_manifest.json` says `demo=false` and all input hashes match.
2. `quality_report.json` passes required acquisition/denominator gates.
3. `event_data_availability.csv` contains enough clean-baseline and outcome cycles for each claimed event; `estimand_data_availability.csv` separately verifies power and network-replication geographies.
4. `exp_a_summary.csv` distinguishes operational sensor selection from publication-grade calibration evidence.
5. `exp_b_estimand_results.csv` keeps `confirmatory_power` separate from `network_replication`.
6. Confirmatory event claims use `inference_admissible=1`; transition periods are not used as pretrends.
7. Prediction uses whole-event holdouts and `prediction_feature_audit.csv` reports no leakage.
8. Repeatability includes bootstrap confidence intervals and ICC.
9. Recovery models report `identified=1` rather than merely completing execution.
10. Path claims use quality-admissible rows and BH-FDR-corrected values.
11. `closure_report.json` is interpreted as written; do not tune thresholds after seeing outcomes.
