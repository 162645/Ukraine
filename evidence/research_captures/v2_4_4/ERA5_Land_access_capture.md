# ERA5-Land official access contract — research capture

- Captured: 2026-08-07T09:36:49.223020+00:00
- Dataset: https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land
- API setup: https://cds.climate.copernicus.eu/how-to-api
- Status: **OFFICIAL ACCESS METHOD VERIFIED**

ERA5-Land is hourly, global, distributed on a regular 0.1°×0.1° grid in CDS (native resolution about 9 km), covering 1950 to present. Programmatic CDS access requires a CDS account, a personal access token in `$HOME/.cdsapirc`, `cdsapi>=0.7.7`, and manual acceptance of the dataset terms before download.

This package therefore cannot truthfully contain the final ERA5-Land-derived parquet until the researcher supplies those credentials/accepted terms. `scripts/materialize_weather_closure.py` automates the rest without rerunning Experiment A.
