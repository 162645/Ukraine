#!/usr/bin/env python3
"""Create a deterministic inventory and non-overwriting core-results bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_files(run_dir: Path) -> list[Path]:
    candidates = [run_dir / "run_manifest.json"]
    results = run_dir / "results"
    if results.exists():
        candidates.extend(p for p in results.rglob("*") if p.is_file())
    return sorted({p.resolve() for p in candidates if p.is_file()}, key=lambda p: p.as_posix())


def inventory(run_dir: Path, files: list[Path]) -> dict:
    rows = [{
        "path": p.relative_to(run_dir).as_posix(),
        "bytes": p.stat().st_size,
        "sha256": sha256(p),
    } for p in files]
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "run_id": run_dir.name,
        "scope": "run_manifest_and_results",
        "file_count": len(rows),
        "files": rows,
        "inventory_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, default=Path("run_archives"))
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    if not (run_dir / "run_manifest.json").is_file():
        raise SystemExit(f"Missing run manifest: {run_dir / 'run_manifest.json'}")

    files = selected_files(run_dir)
    report = inventory(run_dir, files)
    inventory_path = run_dir / "artifact_inventory.json"
    inventory_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    bundle_dir = args.bundle_dir.resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle = bundle_dir / f"{run_dir.name}_core_results.zip"
    sidecar = bundle.with_suffix(bundle.suffix + ".sha256.json")
    if bundle.exists() or sidecar.exists():
        if not (bundle.exists() and sidecar.exists()):
            raise SystemExit(f"Incomplete existing archive pair; inspect manually: {bundle}")
        previous = json.loads(sidecar.read_text(encoding="utf-8"))
        if previous.get("inventory_sha256") != report["inventory_sha256"]:
            raise SystemExit(
                f"Refusing to overwrite archive for changed run: {bundle}. "
                "Choose a new run id or move the old archive first."
            )
        if previous.get("bundle_sha256") != sha256(bundle):
            raise SystemExit(f"Existing archive checksum mismatch: {bundle}")
        print(f"Archive already verified: {bundle}")
        return 0

    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(inventory_path, f"{run_dir.name}/artifact_inventory.json")
        for path in files:
            archive.write(path, f"{run_dir.name}/{path.relative_to(run_dir).as_posix()}")
    sidecar.write_text(json.dumps({
        "bundle": bundle.name,
        "bundle_sha256": sha256(bundle),
        "inventory_sha256": report["inventory_sha256"],
        "file_count": report["file_count"],
    }, indent=2) + "\n", encoding="utf-8")
    print(bundle)
    print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
