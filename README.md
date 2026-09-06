# Ukraine scheduled-outage sensor calibration

This repository implements one paper question:

> Can regional scheduled outages weakly supervise the calibration of network-visible, power-interruption-responsive IP endpoints, and do those frozen endpoints improve observation of independent unplanned energy shocks and recovery?

## Scientific design

The current `v5-simple-outage-calibration` design has no national B2 pool, no
IP-to-power-operator assignment, no inferred queue membership, and no held-out
scheduled-outage classifier. The archived pre-refactor implementation is tagged
`archive-v4-regional-operator-isp-20260906`.

The analysis has two main populations:

- `B1`: stable endpoints built only from complete non-event measurement cycles.
- `B2`: endpoints that, during at least one eligible regional scheduled outage,
  are stable before the event, lose reachability during it, and recover after it.

Power operator and queue fields remain event provenance. ISP/ASN fields are used
for network-confounding checks and are never treated as electricity providers.
National schedule rows do not calibrate endpoints.

After calibration, B2 is frozen and compared with B1 in independent attack,
emergency-outage, and recovery events. A positive paper result requires B2 to
show greater network-visible disruption signal than B1; a fully estimable null
result is retained as a valid negative finding.

The frozen protocol is documented in
`docs/ANALYSIS_PLAN_V5_SIMPLE_CALIBRATION.md`.

## Main intermediate outputs

Only three reader-facing calibration artifacts are central:

- `candidate_ips.parquet`: quality-eligible measured endpoints.
- `calibration_events.csv`: eligible Admin1-date scheduled-outage events.
- `calibrated_sensors.csv`: frozen stable-drop-recovery endpoint set.

Large event-level candidate partitions are internal checkpoints rather than
manual spreadsheets.

## Configuration

Keep database credentials outside Git:

```bash
cp .env.example .env.local
```

Environment variables such as `UR_CH_HOST`, `UR_CH_USER`, and
`UR_CH_PASSWORD` override the checked-in configuration. `.env.local` and local
YAML overrides are ignored by Git.

## Install and test

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
```

## One-command real run

```bash
./scripts/run_v5_full.sh v5_simple_calibration_01
```

Equivalent manual command:

```bash
python run_all.py --mode real --run-id v5_simple_calibration_01 --stage all --resume
```

Stage order:

```text
preflight → audit → panels → baseline → calibrate → sensorPanels
→ features → expB → expF → expD → figures → validate
```

The main closure output is:

```text
runs/<run_id>/results/tables/closure_report.json
```

## Claim boundary

Selected endpoints are scheduled-outage-calibrated candidate sensors, not
verified electricity-meter observations. The physical electricity claim remains
limited by the absence of IP-to-feeder or IP-to-customer ground truth.
