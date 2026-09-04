"""Configuration, run isolation, and frozen-resource loading for analysis plan v2."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge a local override without dropping new base defaults."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path
    config_path: Path
    run_id: str
    mode: str = "real"

    @property
    def config_dir(self) -> Path:
        return self.config_path.parent

    def section(self, name: str) -> dict[str, Any]:
        return self.raw[name]

    @property
    def database(self): return self.section("database")
    @property
    def runtime(self): return self.section("runtime")
    @property
    def study(self): return self.section("study")
    @property
    def quality(self): return self.section("quality")
    @property
    def baseline(self): return self.section("baseline")
    @property
    def aggregation(self): return self.section("aggregation")
    @property
    def group_admission(self): return self.section("group_admission")
    @property
    def event_windows(self): return self.section("event_windows")
    @property
    def calibration(self): return self.section("calibration")
    @property
    def regional_calibration(self): return self.section("regional_calibration")
    @property
    def matching(self): return self.section("matching")
    @property
    def prediction(self): return self.section("prediction")
    @property
    def external_validation(self): return self.section("external_validation")
    @property
    def recovery_debt(self): return self.section("recovery_debt")
    @property
    def path(self): return self.section("path")
    @property
    def inference(self): return self.section("inference")
    @property
    def closure(self): return self.section("closure")
    @property
    def figures(self): return self.section("figures")

    @property
    def max_memory_bytes(self) -> int:
        return int(self.runtime["max_memory_gb"]) * 1024**3

    @property
    def ch_max_memory_usage(self) -> int:
        return int(self.max_memory_bytes * float(self.runtime["ch_max_memory_usage_frac"]))

    @property
    def ch_external_group_by(self) -> int:
        return int(self.max_memory_bytes * float(self.runtime["ch_external_group_by_frac"]))

    @property
    def ch_external_sort(self) -> int:
        return int(self.max_memory_bytes * float(self.runtime["ch_external_sort_frac"]))

    def db_conn(self) -> dict[str, Any]:
        db = dict(self.database)
        db["host"] = os.environ.get("UR_CH_HOST", db.get("host", "127.0.0.1"))
        db["user"] = os.environ.get("UR_CH_USER", db.get("user", "default"))
        db["password"] = os.environ.get("UR_CH_PASSWORD", db.get("password", ""))
        db["http_port"] = int(os.environ.get("UR_CH_HTTP_PORT", db.get("http_port", 8123)))
        db["native_port"] = int(os.environ.get("UR_CH_NATIVE_PORT", db.get("native_port", 9000)))
        db["database"] = os.environ.get("UR_CH_DATABASE", db.get("database", "default"))
        secure = str(os.environ.get("UR_CH_SECURE", db.get("secure", False))).lower()
        db["secure"] = secure in {"1", "true", "yes", "on"}
        db["connect_timeout"] = int(os.environ.get(
            "UR_CH_CONNECT_TIMEOUT", db.get("connect_timeout", 30)))
        db["send_receive_timeout"] = int(os.environ.get(
            "UR_CH_SEND_RECEIVE_TIMEOUT", db.get("send_receive_timeout", 1800)))
        apply_settings = str(os.environ.get(
            "UR_CH_APPLY_SETTINGS", db.get("apply_query_settings", True))).lower()
        db["apply_query_settings"] = apply_settings in {"1", "true", "yes", "on"}
        return db

    def table(self, logical: str) -> str:
        return self.database["tables"][logical]

    @property
    def run_base(self) -> Path:
        key = "demo_run_root" if self.mode == "demo" else "run_root"
        return self.root / self.raw["paths"][key] / self.run_id

    def out_dir(self, key: str, *, lang: str | None = None, ensure: bool = True) -> Path:
        p = self.run_base / self.raw["paths"][key]
        if lang:
            p = p / lang
        if ensure:
            p.mkdir(parents=True, exist_ok=True)
        return p

    def resource_path(self, freeze_key: str) -> Path:
        return self.config_dir / self.raw["freeze"][freeze_key]

    def load_event_registry(self):
        import pandas as pd
        p = self.resource_path("event_registry")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        for c in df.columns:
            if c.endswith("_utc"):
                df[c] = pd.to_datetime(df[c].replace("", None), utc=True, errors="coerce")
        for c in ["analysis_ready", "confound_weather", "confound_holiday", "confound_overlap", "frontline_activity"]:
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
        return df

    def load_exposure_registry(self):
        import pandas as pd
        p = self.resource_path("exposure_registry")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        for c in ("start_utc", "end_utc"):
            df[c] = pd.to_datetime(df[c].replace("", None), utc=True, errors="coerce")
        return df

    def load_schedule_registry(self):
        import pandas as pd
        p = self.resource_path("schedule_registry")
        df = pd.read_csv(p, dtype=str, keep_default_na=False)
        # v3.0 is a wider, evidence-preserving registry exported from the
        # workbook.  Normalize its names to the v2 analysis contract while
        # retaining all precision/provenance columns for regional analyses.
        if "segment_id" not in df and "record_id" in df:
            df["segment_id"] = df["record_id"]
        if "local_start" not in df and "planned_start_local" in df:
            df["local_start"] = df["planned_start_local"]
        if "local_end" not in df and "planned_end_local" in df:
            df["local_end"] = df["planned_end_local"]
        if "start_utc" not in df and "planned_start_utc" in df:
            df["start_utc"] = df["planned_start_utc"]
        if "end_utc" not in df and "planned_end_utc" in df:
            df["end_utc"] = df["planned_end_utc"]
        if "source_authority" not in df and "source_origin" in df:
            df["source_authority"] = df["source_origin"]
        if "verified_at_utc" not in df and "announced_at_utc" in df:
            df["verified_at_utc"] = df["announced_at_utc"]
        if "final_version" not in df:
            df["final_version"] = 1
        if "publication_eligible" not in df:
            df["publication_eligible"] = df.get("analysis_eligible", 0)
        if "independence_cluster" not in df:
            # Preserve known v2 event clusters; date-level fallback keeps new
            # v3 rows identifiable without claiming cross-day independence.
            date_to_cluster = {
                "2024-07-07": "july_training",
                "2024-07-20": "july_training",
                "2024-07-28": "july_holdout",
                "2024-08-19": "august_heat",
                "2024-08-20": "august_heat",
                "2024-08-21": "august_heat",
                "2024-12-09": "winter_attack_recovery",
            }
            df["independence_cluster"] = df.get("event_date", "").map(
                lambda x: date_to_cluster.get(str(x), str(x)))
        if "event_id" not in df:
            date_to_event = {
                "2024-06-10": "E2024_0610_PLANNED",
                "2024-06-21": "E2024_0621_PLANNED",
                "2024-06-24": "E2024_0624_PLANNED",
                "2024-07-07": "E2024_0707_PLANNED",
                "2024-07-20": "E2024_0720_PLANNED",
                "2024-07-28": "E2024_0728_PLANNED",
                "2024-08-19": "E2024_0819_PLANNED",
                "2024-08-20": "E2024_0820_PLANNED",
                "2024-08-21": "E2024_0821_PLANNED",
                "2024-12-09": "E2024_1209_PLANNED",
            }
            df["event_id"] = df.get("event_date", "").map(
                lambda x: date_to_event.get(str(x), f"E{str(x).replace('-', '')}_V3"))
        for c in ("start_utc", "end_utc", "verified_at_utc"):
            if c in df:
                df[c] = pd.to_datetime(df[c].replace("", None), utc=True, errors="coerce")
        # Local operator timestamps are civil times, not UTC.  Preserve their
        # encoded offset (or localize naive values using timezone_name) so a
        # workstation timezone such as Asia/Shanghai can never shift labels.
        for c in ("local_start", "local_end"):
            if c in df:
                parsed = []
                for value, zone in zip(df[c], df.get("timezone_name", "Europe/Kyiv")):
                    if not value:
                        parsed.append(pd.NaT)
                        continue
                    ts = pd.Timestamp(value)
                    parsed.append(ts.tz_localize(zone or "Europe/Kyiv") if ts.tzinfo is None else ts)
                df[c] = parsed
        if "queue_count" in df:
            df["queue_count_known"] = df["queue_count"].astype(str).str.strip().ne("").astype("int8")
        for c in ("queue_count", "final_version", "publication_eligible", "analysis_eligible"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
        if "status_norm" in df:
            df["schedule_positive"] = df["status_norm"].isin(
                {"confirmed", "updated", "extended", "shortened", "partial", "dispatch_confirmed"}
            )
        else:
            df["schedule_positive"] = pd.to_numeric(df.get("queue_count"), errors="coerce").gt(0)
        return df

    def _load_aux_registry(self, freeze_key: str, datetime_columns: tuple[str, ...]):
        import pandas as pd
        df = pd.read_csv(self.resource_path(freeze_key), dtype=str, keep_default_na=False)
        for c in datetime_columns:
            if c in df:
                df[c] = pd.to_datetime(df[c].replace("", None), utc=True, errors="coerce")
        return df

    def load_oblast_execution_registry(self):
        return self._load_aux_registry(
            "oblast_execution_registry", ("start_utc", "end_utc", "announced_at_utc"))

    def load_weather_episode_registry(self):
        return self._load_aux_registry("weather_episode_registry", ("start_utc", "end_utc"))

    def load_source_post_registry(self):
        return self._load_aux_registry("source_post_registry", ())

    def load_mapping_manifest(self) -> dict[str, Any]:
        with self.resource_path("mapping_manifest").open(encoding="utf-8") as f:
            return json.load(f)

    def frozen_hashes(self) -> dict[str, str]:
        out = {"config": file_sha256(self.config_path)}
        for key in ("event_registry", "schedule_registry", "oblast_execution_registry",
                    "weather_episode_registry", "source_post_registry", "exposure_registry",
                    "mapping_manifest", "admin1_aliases"):
            out[key] = file_sha256(self.resource_path(key))
        return out


def load_config(config_path: str | os.PathLike | None = None, *, run_id: str | None = None,
                mode: str = "real") -> Config:
    root = project_root()
    if config_path is None:
        local = root / "config" / "experiment_v2.local.yaml"
        base = root / "config" / "experiment_v2.yaml"
        p = local if local.exists() else base
    else:
        p = Path(config_path)
        if not p.is_absolute() and not p.exists():
            p = root / p
    p = p.resolve()
    with p.open(encoding="utf-8") as f:
        selected = yaml.safe_load(f) or {}
    # A local file is an override, not a forked copy of the scientific plan.
    # Deep merging prevents newly introduced preregistered settings from being
    # silently lost when an older local connection file remains on disk.
    base_path = root / "config" / "experiment_v2.yaml"
    if p != base_path.resolve():
        with base_path.open(encoding="utf-8") as f:
            raw = _deep_merge(yaml.safe_load(f) or {}, selected)
    else:
        raw = selected
    if run_id is None:
        from datetime import datetime, timezone
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if mode not in {"real", "demo"}:
        raise ValueError("mode must be real or demo")
    cfg = Config(raw=raw, root=root, config_path=p, run_id=run_id, mode=mode)
    cfg.run_base.mkdir(parents=True, exist_ok=True)
    return cfg
