# Closure-input supplement v2.4.2

This supplement closes four pre-run engineering/evidence gaps without changing the paper's core question.
It does not guarantee a positive result.

## 1. Oblast-level falsification

The strongest currently verified contrast is 24 July 2024, 16:00-18:00 EEST (13:00-15:00 UTC):

- Volynoblenergo's final operator update cancelled scheduled outages through 20:00.
- Zaporizhzhyaoblenergo retained Queue 1 for 16:00-18:00.

Because Queue 1 covers only part of Zaporizhzhia and no IP-to-queue map exists, this contrast must not train
B2. It is an auxiliary oblast-level falsification: within the same national dispatch environment, does the
partially executing oblast show a larger reachability reduction than the cancelled oblast?

Frozen gates:

- at least one complete 2-hour measurement cycle;
- at least 20 eligible /24s per side;
- at least 3 common ASNs;
- within-ASN matching;
- clean pre-window level and slope equivalence;
- no post-hoc expansion beyond 16:00-18:00 EEST;
- report partial-treatment dilution explicitly.

## 2. Weather

`config/weather_episode_registry_v1.csv` freezes the official 8-15 July heat episode and the severe
11-15 July subepisode. These are confounders/stratifiers, never treatments.

For continuous controls:

```bash
python -m pip install -r requirements-weather.txt
python scripts/download_era5_land.py --start 2024-06-22 --end 2025-01-09
python scripts/build_weather_admin1_2h.py \
  --admin1-geojson /absolute/path/ukraine_admin1.geojson
```

The geometry must have `country` and `admin1` fields and must be frozen and hashed. The output is
`data_external/weather/weather_admin1_2h.parquet` with 2-hour UTC temperature/dewpoint aggregates,
previous-24-hour maximum and official heat flags.

Primary analysis remains unadjusted. Weather-adjusted and heat-exclusion estimates are sensitivity analyses.
An estimate that appears only after weather adjustment is conditional evidence, not a rescued main finding.

## 3. Evidence snapshots

Use `config/source_post_registry_v1.csv` plus the three archive scripts. A public web snapshot is required for
all critical sources; official Telegram sources additionally require Telegram Desktop JSON. The final run must
store the evidence verification report and its hash in the run manifest.

## 4. statsmodels

The paper environment pins `statsmodels==0.14.6`. Recreate the virtual environment rather than installing into
an ambiguous global interpreter:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts/check_environment.py
PYTHONPATH=src pytest -q
```

## Corrections applied

- 19 August 2024 official schedule corrected to 17:00-21:00 EEST = 14:00-18:00 UTC.
- 11 December same-day cancelled control restricted to Volyn. Lviv and Ivano-Frankivsk are excluded until
  equivalent operator records are archived.
- 24 July falsification added as an auxiliary partial-queue event, not calibration training.
