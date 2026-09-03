# v2.4.3 — closure external-data package

## Purpose

This package does **not** introduce a new scientific theme. It supplies the final external inputs needed to close the existing paper question:

1. weather/heat as a confounder for scheduled-outage calibration (never as treatment);
2. state-level execution/cancellation evidence for a frozen falsification;
3. independent Internet platforms for post-hoc attack validation;
4. immutable evidence snapshots for scheduled-outage labels.

None of these sources may be used to retune B2 thresholds, move attack anchors after seeing outcomes, or select only favorable events.

## What is already frozen in the ZIP

- `config/oblast_execution_registry_v1.csv`: 24 July Zaporizhzhia partial execution vs Volyn cancellation, plus 11 December Volyn cancellation record.
- `config/weather_episode_registry_v1.csv`: official 8–15 July heat episode and 11–15 July severe-heat subperiod.
- `config/external_validation_targets_v1.csv`: frozen IODA/Cloudflare event windows and the three 28-Nov ASNs.
- `config/external_data_sources_v1.csv`: source, auth, output, and scientific role registry.
- `config/final_closure_sensitivity_plan_v1.csv`: stopping-rule contract for the final supplemental analyses.

Copies of the two small scientific input registries are also under `data_external/static/` so Codex can consume them without importing the main experiment configuration.

## One-command request preview

Before any downloads:

```bash
python scripts/prepare_closure_external_data.py --dry-run
```

This creates request-plan files under `data_external/request_plans/` and prints every endpoint/date window.

## ERA5-Land

Install optional dependencies:

```bash
python -m pip install -r requirements-external.txt
```

Set up a Copernicus CDS account, accept the ERA5-Land licence, and configure the current CDS API token according to the CDS API page. Then:

```bash
python scripts/download_era5_land.py --start 2024-06-22 --end 2025-01-09
python scripts/fetch_geoboundaries_ukraine_adm1.py
python scripts/build_weather_admin1_2h.py
```

Expected output:

```text
data_external/weather/weather_admin1_2h.parquet
```

The aggregation script accepts geoBoundaries `shapeName` automatically and maps it to the project's canonical Admin1 names using `config/admin1_aliases_v1.csv`.

Important: the geoBoundaries geometry is only a climate-grid aggregation aid. It does **not** replace the frozen target-IP geographic mapping.

## IODA v2

No API key is required by the public v2 endpoint documented by IODA. Preview:

```bash
python scripts/fetch_ioda_validation.py --dry-run
```

Execute:

```bash
python scripts/fetch_ioda_validation.py
```

The script requests country `UA` for all frozen attack windows and additionally requests AS6849, AS15895 and AS13188 around 28 November. Raw responses and exact request URLs are frozen under `data_external/ioda/`.

If IODA changes its public query contract, the script deliberately stores the HTTP error and stops instead of silently changing parameters. The API's own documentation remains the source of truth.

## Cloudflare Radar

Create a Cloudflare API token with permission to read Radar data and export it only in your local shell:

```bash
export CLOUDFLARE_API_TOKEN='...'
python scripts/fetch_cloudflare_radar.py --dry-run
python scripts/fetch_cloudflare_radar.py
```

Outputs:

```text
data_external/cloudflare/outages.json
data_external/cloudflare/traffic_anomalies.json
```

These are post-hoc validation sources. They must not alter the internal attack detector or scheduled-outage sensor definition.

## Telegram evidence

Telegram's official Desktop exporter can produce JSON and HTML. Export the relevant official channels locally, then:

```bash
python scripts/ingest_telegram_export.py /path/to/result.json --root .
python scripts/verify_evidence_archive.py --root .
```

Keep the raw JSON/HTML, message IDs, exported-at time and SHA-256. The ZIP intentionally does not contain credentials, a logged-in Telegram session, or proprietary user data.

## Audit before the final sensitivity run

```bash
python scripts/check_external_closure_inputs.py --root . --strict
```

Required for the final weather/evidence closure:

- frozen Ukraine ADM1 geometry;
- `weather_admin1_2h.parquet`;
- official weather episode registry;
- oblast execution registry;
- evidence verification report;
- importable `statsmodels`.

IODA and Cloudflare are deliberately marked useful-but-not-core-required because the paper's core claim must not depend on a third-party platform being available forever.

## Scientific stop rule

After these inputs are frozen, run only the prespecified sensitivity analyses in `config/final_closure_sensitivity_plan_v1.csv`. Do not introduce a new B2 formula, choose a new threshold, move attack windows, or promote a better-looking exploratory predictor. After this pass, positive **or** valid negative closure should be treated as final.

