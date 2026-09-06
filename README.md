# Ukraine state-level outage sensitivity measurement

This repository implements one paper question:

> Can state-level scheduled-outage evidence weakly supervise continuous IP-level network sensitivity to power interruption, and does that frozen sensitivity predict state-specific reachability loss and recovery during independent energy attacks?

## Scientific design

The current design has no national outage labels, IP-to-power-operator
assignment, inferred queue membership, or attack-tuned endpoint classifier.
The archived binary-sensor implementation is tagged
`archive-v4-regional-operator-isp-20260906`.

The analysis has two main populations:

- `B1`: stable endpoints built only from complete non-event measurement cycles.
- Frozen state-level sensitivity: for every stable IP with usable state-level
  planned-outage evidence, `S_reach = reach(normal) - reach(outage)` and
  `S_rtt = (RTT(outage) - RTT(normal)) / RTT(normal)`. The two scores remain
  separate and are averaged across independent outage events.

Power operator and queue fields remain event provenance. ISP/ASN fields are used
for network-confounding checks and are never treated as electricity providers.
National schedule rows do not calibrate endpoints.

After calibration, sensitivity is frozen. Independent attacks are first
evaluated within each publicly affected state: the reachability deficit,
cumulative deficit, recovery profile, and conditional RTT change of high- and
low-sensitivity strata are reported. Cross-state summaries come only after
these within-state contrasts. A null gradient remains a valid result.

The frozen protocol is documented in
`docs/ANALYSIS_PLAN_V5_SIMPLE_CALIBRATION.md`.

## Main intermediate outputs

Only three reader-facing calibration artifacts are central:

- `candidate_ips.parquet`: quality-eligible measured endpoints.
- `calibration_events.csv`: eligible Admin1-date scheduled-outage events.
- `calibrated_sensors.csv`: frozen per-IP `S_reach`, `S_rtt`, support counts,
  and within-state sensitivity strata.
- `exp_b_state_sensitivity_validation.csv`: frozen high-versus-low sensitivity
  comparisons within each attack-affected state.

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
