# Ukraine state-level outage sensitivity measurement

This repository implements one paper question:

> Can state-level scheduled-outage evidence weakly supervise continuous IP-level network sensitivity to power interruption, and does that frozen sensitivity predict state-specific reachability loss and recovery during independent energy attacks?

## Scientific design

The current design has no national outage labels, IP-to-power-operator
assignment, inferred queue membership, or attack-tuned endpoint classifier.
The archived binary-sensor implementation is tagged
`archive-v4-regional-operator-isp-20260906`.

The primary endpoint population is every region-mapped IP with the configured
minimum clean-normal-cycle support (24 by default). Raw Activity is retained as
a continuous covariate; `B1` is a legacy stability diagnostic and does not gate
canonical IPS/FBS or sensitivity. For every activity-supported IP with usable
state-level planned-outage evidence, `S_reach = reach(normal) - reach(outage)`
and `S_rtt = (RTT(outage) - RTT(normal)) / RTT(normal)`. The two scores remain
separate and are averaged equally across independent outage episodes.

Calibration begins from the activity-supported regional universe. Normal
controls use the same weekday-by-two-hour slot and exclude registered outage
cycles. Explicit same-day no-outage intervals are retained as an auxiliary
within-day contrast. Consecutive daily restrictions are collapsed to one
episode before they contribute to an IP's final score.

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

- `ip_sensitivity_labels.csv`: one row per measured IP, including B1 status and
  an explicit reason when a primary sensitivity cannot be estimated.
- `calibration_events.csv`: the frozen A/A+ direct-oblast and proxy event whitelist.
- `calibrated_sensors.csv`: frozen per-IP primary `S_reach`, `S_rtt`, proxy-augmented
  robustness scores, support counts,
  and within-state sensitivity strata.
- `exp_b_state_sensitivity_validation.csv`: frozen high-versus-low sensitivity
  comparisons within each attack-affected state.
- `exp_b_state_sensitivity_association.csv`: within-state continuous slopes
  relating frozen `S_i` to attack-period reachability loss, RTT change, and
  time to 90 percent recovery (`t90_h`), with unrecovered units right-censored.

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
preflight → audit → panels → canonicalSignals → baseline → calibrate
→ sensorPanels → features → expB → expF → expD → paperAnalysis → figures → validate
```

The main closure output is:

```text
runs/<run_id>/results/tables/closure_report.json
```

## Claim boundary

Selected endpoints are scheduled-outage-calibrated candidate sensors, not
verified electricity-meter observations. The physical electricity claim remains
limited by the absence of IP-to-feeder or IP-to-customer ground truth.
# Research-plan alignment (v5)

The canonical endpoint population is the regional target universe with at least
the configured number of clean normal cycles (24 by default).  Activity is
stored as the continuous raw response rate; the historical B1 response-rate
threshold is diagnostic only and does not define canonical IPS/FBS or the
planned-outage sensitivity population.  Planned-outage reachability sensitivity
is `p_ctrl - p_out` per independent episode and is averaged equally across
episodes.  RTT sensitivity remains a separate conditional measure.  Attack
validation uses frozen labels and must not feed back into calibration.

The project has only a current IP mapping snapshot.  It therefore does not
claim to reproduce longitudinal monthly GeoIP stability classification.
