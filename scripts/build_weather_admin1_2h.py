#!/usr/bin/env python3
"""Area-weight ERA5-Land grid cells to canonical Ukraine Admin1×2-hour bins."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--netcdf-dir", default="data_external/weather/era5_land_raw")
    ap.add_argument("--admin1-geojson", required=True)
    ap.add_argument("--weather-episodes", default="config/weather_episode_registry_v1.csv")
    ap.add_argument("--output", default="data_derived/weather_admin1_2h.parquet")
    args = ap.parse_args()
    try:
        import geopandas as gpd
        import xarray as xr
    except ImportError as exc:
        raise SystemExit("Install requirements-weather.txt in the preprocessing environment") from exc
    files = sorted(Path(args.netcdf_dir).glob("*.nc"))
    if not files:
        raise SystemExit("No ERA5-Land NetCDF files found")
    geo_path = Path(args.admin1_geojson)
    geo = gpd.read_file(geo_path).to_crs(4326)
    missing = {"country", "admin1"} - set(geo.columns)
    if missing:
        raise SystemExit(f"Admin1 geometry missing columns: {sorted(missing)}")
    ds = xr.open_mfdataset(files, combine="by_coords")
    tname = "t2m" if "t2m" in ds else "2m_temperature"
    dname = "d2m" if "d2m" in ds else "2m_dewpoint_temperature"
    time_name = "valid_time" if "valid_time" in ds.coords else "time"
    lats, lons = ds["latitude"].values, ds["longitude"].values
    xx, yy = np.meshgrid(lons, lats)
    points = gpd.GeoDataFrame({"lat": yy.ravel(), "lon": xx.ravel()},
                              geometry=gpd.points_from_xy(xx.ravel(), yy.ravel()), crs=4326)
    joined = gpd.sjoin(points, geo[["country", "admin1", "geometry"]],
                       predicate="intersects", how="inner")
    times = pd.to_datetime(ds[time_name].values, utc=True)
    t2 = np.asarray(ds[tname].values).reshape(len(times), -1) - 273.15
    d2 = np.asarray(ds[dname].values).reshape(len(times), -1) - 273.15
    rows = []
    for (country, admin1), group in joined.groupby(["country", "admin1"]):
        idx = group.index.to_numpy()
        weights = np.cos(np.deg2rad(group["lat"].to_numpy()))
        weights = weights / weights.sum()
        hourly = pd.DataFrame({
            "measure_time": times, "country": country, "admin1": admin1,
            "t2m": np.average(t2[:, idx], axis=1, weights=weights),
            "d2m": np.average(d2[:, idx], axis=1, weights=weights),
        }).set_index("measure_time")
        two = hourly.resample("2h", origin="start_day").agg(
            country=("country", "first"), admin1=("admin1", "first"),
            t2m_mean_c=("t2m", "mean"), t2m_max_c=("t2m", "max"),
            t2m_min_c=("t2m", "min"), dewpoint_mean_c=("d2m", "mean")).reset_index()
        two["previous_24h_max_c"] = two["t2m_max_c"].rolling(12, min_periods=12).max()
        rows.append(two)
    out = pd.concat(rows, ignore_index=True)
    # Anomaly is relative to each Admin1×calendar-month×2-hour-slot within the
    # frozen study period; this reference is recorded in the sidecar manifest.
    out["month"] = out["measure_time"].dt.month
    out["slot2h"] = out["measure_time"].dt.hour // 2
    climatology = out.groupby(["admin1", "month", "slot2h"])["t2m_mean_c"].transform("mean")
    out["temperature_anomaly_c"] = out["t2m_mean_c"] - climatology
    out["official_heat_warning"] = 0
    out["official_severe_heat_warning"] = 0
    episodes = pd.read_csv(args.weather_episodes, dtype=str, keep_default_na=False)
    for _, episode in episodes.iterrows():
        start = pd.to_datetime(episode["start_utc"], utc=True)
        end = pd.to_datetime(episode["end_utc"], utc=True)
        mask = out["measure_time"].between(start, end, inclusive="left")
        scope = str(episode.get("admin1_scope", episode.get("affected_admin1", "ALL")))
        if scope != "ALL":
            mask &= out["admin1"].isin(scope.split("|"))
        severe = str(episode.get("severity", "")) == "severe_heat"
        out.loc[mask, "official_heat_warning"] = 1
        if severe:
            out.loc[mask, "official_severe_heat_warning"] = 1
    out = out.drop(columns=["month", "slot2h"]).sort_values(["admin1", "measure_time"])
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(target, index=False)
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "output_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "admin1_geometry": str(geo_path.resolve()),
        "admin1_geometry_sha256": hashlib.sha256(geo_path.read_bytes()).hexdigest(),
        "input_files": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
        "aggregation": "cosine-latitude-weighted grid-cell mean; UTC 2h bins",
        "anomaly_reference": "within-study Admin1 x calendar-month x UTC-2h-slot mean",
    }
    target.with_suffix(".manifest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(target, len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
