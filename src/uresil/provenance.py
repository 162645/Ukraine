"""Run manifests, stage fingerprints, and anti-stale-output safeguards.

A scientific run is immutable by default.  Resuming a run reuses the existing
manifest only when the run id, mode, and every frozen input hash match.  Stage
records carry file hashes (or directory inventory hashes) so stale or mixed
outputs can be detected without hashing multi-gigabyte parquet trees on every
stage transition.
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Config, file_sha256


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None


def manifest_path(cfg: Config) -> Path:
    return cfg.run_base / "run_manifest.json"


def source_tree_sha256(root: Path) -> str:
    """Deterministic hash of executable analysis code and SQL contracts."""
    h = hashlib.sha256()
    candidates = [root / "run_all.py", root / "requirements.txt"]
    for sub in ("src", "sql", "scripts"):
        base = root / sub
        if base.exists():
            candidates.extend(x for x in base.rglob("*") if x.is_file() and
                              x.suffix in {".py", ".sql", ".sh"})
    for f in sorted(set(candidates)):
        if not f.exists():
            continue
        h.update(f.relative_to(root).as_posix().encode())
        h.update(file_sha256(f).encode())
    return h.hexdigest()


def _new_manifest(cfg: Config) -> dict[str, Any]:
    return {
        "run_id": cfg.run_id,
        "mode": cfg.mode,
        "demo": cfg.mode == "demo",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(cfg.root),
        "git_commit": _git_commit(cfg.root),
        "source_tree_sha256": source_tree_sha256(cfg.root),
        "python": sys.version,
        "platform": platform.platform(),
        "frozen_hashes": cfg.frozen_hashes(),
        "database": {k: v for k, v in cfg.db_conn().items() if k != "password"},
        "tables": cfg.database["tables"],
        "stages": {},
    }


def init_manifest(cfg: Config) -> dict[str, Any]:
    """Create a new manifest.  Refuse to overwrite an existing scientific run."""
    p = manifest_path(cfg)
    if p.exists():
        raise FileExistsError(
            f"Run manifest already exists: {p}. Use --resume to continue, "
            "--force to deliberately rerun stages, or --clean-run to replace the run."
        )
    m = _new_manifest(cfg)
    write_manifest(cfg, m)
    return m


def _assert_manifest_compatible(cfg: Config, m: dict[str, Any], *,
                                allow_source_tree_drift: bool = False) -> tuple[str, str, bool]:
    problems: list[str] = []
    if str(m.get("run_id")) != str(cfg.run_id):
        problems.append(f"run_id {m.get('run_id')} != {cfg.run_id}")
    if str(m.get("mode")) != str(cfg.mode):
        problems.append(f"mode {m.get('mode')} != {cfg.mode}")
    if dict(m.get("frozen_hashes", {})) != cfg.frozen_hashes():
        problems.append("frozen config/event/exposure/mapping/Admin1 hashes changed")
    previous_source = str(m.get("source_tree_sha256", ""))
    current_source = source_tree_sha256(cfg.root)
    source_drift = previous_source != current_source
    if source_drift and not allow_source_tree_drift:
        problems.append("executable source or SQL changed")
    current_db = {k: v for k, v in cfg.db_conn().items() if k != "password"}
    if dict(m.get("database", {})) != current_db:
        problems.append("ClickHouse host/user/port/database configuration changed")
    if problems:
        raise RuntimeError(
            "Cannot resume or force this run because provenance changed: " + "; ".join(problems)
        )
    return previous_source, current_source, source_drift


def init_or_resume_manifest(cfg: Config, *, resume: bool = False,
                            force: bool = False) -> dict[str, Any]:
    """Open an existing compatible run or initialise a new immutable run.

    This fixes the v1/v2 failure mode where ``--resume`` first overwrote the
    manifest, thereby losing the list of completed stages and silently mixing
    old and new output files.
    """
    p = manifest_path(cfg)
    if not p.exists():
        return init_manifest(cfg)
    m = json.loads(p.read_text(encoding="utf-8"))
    prev_source, cur_source, source_drift = _assert_manifest_compatible(
        cfg, m, allow_source_tree_drift=bool(resume or force)
    )
    if not (resume or force):
        raise FileExistsError(
            f"Run {cfg.run_id} already exists. Use --resume, --force, or --clean-run."
        )
    m["last_opened_at_utc"] = datetime.now(timezone.utc).isoformat()
    m["resume_count"] = int(m.get("resume_count", 0)) + int(resume)
    if source_drift:
        m.setdefault("source_tree_sha256_initial", prev_source)
        hist = list(m.get("source_tree_sha256_history", []))
        if not hist:
            hist.append(prev_source)
        if hist[-1] != cur_source:
            hist.append(cur_source)
        m["source_tree_sha256_history"] = hist
        m["source_drift_count"] = int(m.get("source_drift_count", 0)) + 1
        m["last_source_drift_at_utc"] = datetime.now(timezone.utc).isoformat()
        m["source_tree_sha256"] = cur_source
    write_manifest(cfg, m)
    return m


def read_manifest(cfg: Config) -> dict[str, Any]:
    p = manifest_path(cfg)
    if not p.exists():
        raise FileNotFoundError(
            f"Missing run manifest {p}; initialise the run through run_all.py first."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def write_manifest(cfg: Config, m: dict[str, Any]) -> None:
    p = manifest_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def stage_fingerprint(cfg: Config, stage: str, input_paths: list[Path] | None = None) -> str:
    h = hashlib.sha256()
    h.update(stage.encode())
    h.update(json.dumps(cfg.frozen_hashes(), sort_keys=True).encode())
    for p in sorted(input_paths or []):
        if p.exists() and p.is_file():
            h.update(str(p.relative_to(cfg.run_base) if cfg.run_base in p.parents else p).encode())
            h.update(file_sha256(p).encode())
    return h.hexdigest()


def _directory_inventory(path: Path) -> dict[str, Any]:
    """Return a cheap, explicit inventory hash, not a content hash."""
    h = hashlib.sha256()
    n = 0
    total = 0
    for p in sorted(x for x in path.rglob("*") if x.is_file()):
        rel = p.relative_to(path).as_posix()
        size = p.stat().st_size
        h.update(rel.encode("utf-8", errors="replace"))
        h.update(str(size).encode())
        n += 1
        total += size
    return {
        "type": "directory",
        "path": str(path),
        "file_count": n,
        "total_bytes": total,
        "inventory_sha256": h.hexdigest(),
        "hash_scope": "relative_file_names_and_sizes",
    }


def output_record(value: str | Path) -> dict[str, Any]:
    p = Path(value)
    if not p.is_absolute():
        p = p.resolve()
    if not p.exists():
        return {"type": "missing", "path": str(p)}
    if p.is_dir():
        return _directory_inventory(p)
    return {
        "type": "file",
        "path": str(p),
        "bytes": p.stat().st_size,
        "sha256": file_sha256(p),
    }


def mark_stage(cfg: Config, stage: str, status: str, elapsed_s: float,
               outputs: list[str] | None = None, notes: dict | None = None) -> None:
    m = read_manifest(cfg)
    output_values = outputs or []
    m["stages"][stage] = {
        "status": status,
        "elapsed_s": round(float(elapsed_s), 3),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "outputs": output_values,
        "output_provenance": [output_record(x) for x in output_values],
        "notes": notes or {},
    }
    write_manifest(cfg, m)


def assert_real_output(cfg: Config) -> None:
    if cfg.mode != "real":
        raise RuntimeError("Scientific stages require --mode real. Demo output is isolated.")
    if (cfg.run_base / "_DEMO_NOTICE.txt").exists():
        raise RuntimeError("Demo marker found in a real run directory.")
