#!/usr/bin/env python3
"""Run-isolated orchestration for the Ukraine energy-shock resilience study."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from uresil.config import load_config
from uresil.db import CHClient
from uresil.mapping_snapshot import (DEFAULT_MAPPING_FREEZE_CUTOFF_UTC,
                                     mapping_manifest_needs_freeze,
                                     query_mapping_snapshot,
                                     write_frozen_manifest)
from uresil.progress import get_logger
from uresil.provenance import (assert_real_output, init_or_resume_manifest, mark_stage,
                               read_manifest)
from uresil.time_contract import measurement_time_contract

# The paper's confirmatory chain is H1--H4: frozen labels -> independent
# attack application (Exp B) -> paper tables.  Historical sensor-panel,
# prediction and recovery-debt stages remain available as explicit
# supplemental diagnostics, but never delay or redefine the main estimand.
FORMAL_STAGE_ORDER = ["stage00_quality", "stage01_canonical", "stage02_activity",
                      "stage03_calibration_events", "stage03_5_episode_audit",
                      "stage04_sensitivity", "stage05_h1",
                      "stage06_h2", "stage07_h3", "stage08_h4", "stage09_robustness",
                      "stage10_paper"]
CORE_STAGE_ORDER = ["preflight", "audit", "panels", "canonicalSignals", "baseline", "calibrate",
                    "expB", "paperAnalysis", "figures", "validate"]
SUPPLEMENTAL_STAGE_ORDER = ["sensorPanels", "features", "expF", "expD"]
LEGACY_STAGE_ORDER = ["preflight", "audit", "panels", "canonicalSignals", "baseline", "calibrate", "expB",
                      "paperAnalysis", "sensorPanels", "features", "expF", "expD", "figures", "validate"]
STAGE_ORDER = FORMAL_STAGE_ORDER + LEGACY_STAGE_ORDER


def completed(cfg, stage: str) -> bool:
    x = read_manifest(cfg).get("stages", {}).get(stage, {})
    return x.get("status") in {"ok", "warning", "GREEN_POSITIVE_CHAIN",
                               "GREEN_VALID_NEGATIVE_FINDINGS", "YELLOW_INCOMPLETE_CORE_EVIDENCE",
                               "diagnostic_only_no_admissible_group"}


def execute(stage: str, cfg):
    if stage == "preflight":
        from uresil import preflight as m
        return m.run(cfg)
    if stage == "stage00_quality":
        from uresil import stage00_quality as m
        return m.run(cfg)
    if stage == "stage01_canonical":
        from uresil import canonical_stage as m
        return m.run(cfg)
    if stage == "stage02_activity":
        from uresil import activity_stage as m
        return m.run(cfg)
    if stage == "stage03_calibration_events":
        from uresil import calibration_stage as m
        return m.run(cfg)
    if stage == "stage03_5_episode_audit":
        from uresil import episode_audit_stage as m
        return m.run(cfg)
    if stage in FORMAL_STAGE_ORDER[2:]:
        raise RuntimeError(
            f"{stage} is not implemented as a formal frozen stage yet; refusing to fall back to legacy outputs"
        )
    if stage == "audit":
        from uresil import audit as m
        return m.run(cfg)
    if stage == "panels":
        from uresil import panels as m
        return m.run(cfg)
    if stage == "canonicalSignals":
        from uresil import canonical_stage as m
        return m.run(cfg)
    if stage == "baseline":
        from uresil import baseline_pool as m
        return m.run(cfg)
    if stage == "calibrate":
        from uresil import simple_calibration as m
        return m.run(cfg)
    if stage == "sensorPanels":
        from uresil import sensor_panels as m
        return m.run(cfg)
    if stage == "features":
        from uresil import features as m
        return m.run(cfg)
    if stage == "expB":
        from uresil import exp_b_event_study as m
        return m.run(cfg)
    if stage == "expF":
        from uresil import exp_f_external_validation as m
        return m.run(cfg)
    if stage == "expD":
        from uresil import exp_d_recovery_debt as m
        return m.run(cfg)
    if stage == "paperAnalysis":
        from uresil import paper_analysis as m
        return m.run(cfg)
    if stage == "figures":
        from uresil import viz
        from uresil.viz import paper_figures
        results = [viz.render_all(cfg, lang) for lang in ("zh", "en")]
        paper = paper_figures.render(cfg, "en")
        results.append(paper)
        return {"status": "warning" if any(r["warnings"] for r in results) else "ok",
                "outputs": sum((r["outputs"] for r in results), []),
                "warnings": sum((r["warnings"] for r in results), [])}
    if stage == "validate":
        from uresil import validate as m
        return m.run(cfg)
    raise ValueError(stage)


def auto_freeze_mapping_if_needed(cfg, *, stages: list[str], resume: bool) -> None:
    if cfg.mode != "real" or resume:
        return
    if not bool(cfg.runtime.get("require_frozen_mapping", True)):
        return
    if not stages or "preflight" not in stages:
        return
    path = cfg.resource_path("mapping_manifest")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not mapping_manifest_needs_freeze(payload):
        return
    table = cfg.table("mapping")
    with CHClient(cfg) as ch:
        try:
            snap = query_mapping_snapshot(ch, table, DEFAULT_MAPPING_FREEZE_CUTOFF_UTC)
        except RuntimeError as exc:
            if "contains no IP rows" not in str(exc):
                raise
            print(
                f"Auto-freeze found no mapping rows at {DEFAULT_MAPPING_FREEZE_CUTOFF_UTC}; "
                "falling back to the latest available mapping snapshot.",
                file=sys.stderr,
            )
            snap = query_mapping_snapshot(ch, table, None)
    write_frozen_manifest(path, payload, table=table, cutoff=snap["cutoff"],
                          row_count=snap["row_count"], checksum=snap["content_checksum_uint64"])


def assert_timestamp_contract_before_any_experiment_query(cfg) -> None:
    """Mandatory first database action for every real run/resume."""
    if cfg.mode != "real":
        return
    with CHClient(cfg) as ch:
        report = measurement_time_contract(ch, cfg)
    path = cfg.out_dir("results_tables") / "timestamp_contract_bootstrap.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--run-id", default=None, help="Stable run identifier; required to resume the same run")
    ap.add_argument("--mode", choices=["real", "demo"], default="real")
    ap.add_argument("--stage", nargs="+", default=None, choices=STAGE_ORDER + ["all"])
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clean-run", action="store_true", help="Delete this run directory before starting")
    args = ap.parse_args()

    cfg = load_config(args.config, run_id=args.run_id, mode=args.mode)
    cfg.raw.setdefault("_runtime_flags", {})["force_stage_recompute"] = bool(args.force)
    if args.stage is None or args.stage == ["all"]:
        raise SystemExit("Formal runs require exactly one explicit --stage; --stage all is forbidden")
    if any(s in FORMAL_STAGE_ORDER for s in args.stage) and len(args.stage) != 1:
        raise SystemExit("Formal runs accept exactly one stage per invocation")
    if args.stage == ["all"]:
        # H1--H4 are the default paper run.  ExpF/ExpD are explicitly
        # supplemental and cannot delay the core observational results.
        run_supplemental = bool(cfg.raw.get("run_supplemental", False))
        stages = STAGE_ORDER if run_supplemental else CORE_STAGE_ORDER
    else:
        stages = args.stage
    if stages and stages[0] not in FORMAL_STAGE_ORDER and stages[0] != "preflight":
        stages = ["preflight"] + [x for x in stages if x != "preflight"]
    # This must precede mapping auto-freeze and every analytical query. It uses
    # raw timestamps plus Unix epoch only; outage labels never enter inference.
    assert_timestamp_contract_before_any_experiment_query(cfg)
    if not any(x in FORMAL_STAGE_ORDER for x in stages):
        auto_freeze_mapping_if_needed(cfg, stages=stages, resume=args.resume)
    if args.clean_run and cfg.run_base.exists():
        shutil.rmtree(cfg.run_base)
        cfg.run_base.mkdir(parents=True)
    init_or_resume_manifest(cfg, resume=args.resume, force=args.force)
    logger = get_logger(cfg.out_dir("logs"))
    logger.info("启动实验编排: run_id=%s, mode=%s, stages=%s", cfg.run_id, cfg.mode, ", ".join(stages))
    logger.info("运行输出目录: %s", cfg.run_base)
    if args.resume:
        logger.info("已开启续跑模式；同一 RUN_ID 下已完成阶段会自动跳过")
    if args.clean_run:
        logger.info("已执行 clean run，请确认这是一次全量重跑")
    if args.force:
        logger.info("已开启 force 模式；目标阶段会强制重算")

    if cfg.mode == "demo":
        from uresil.demo_data import generate_demo_tables
        generate_demo_tables(cfg)
        notice = cfg.run_base / "_DEMO_NOTICE.txt"
        notice.write_text("SYNTHETIC DATA — FOR PIPELINE TESTING ONLY — NOT FOR SCIENTIFIC USE\n", encoding="utf-8")
        from uresil import viz
        from uresil import paper_analysis
        from uresil.viz import paper_figures
        demo_outputs = [str(notice)]
        demo_warnings = []
        contract = paper_analysis.run(cfg)
        demo_outputs.extend(contract.get("outputs", []))
        rendered_paper = paper_figures.render(cfg, "en")
        demo_outputs.extend(rendered_paper.get("outputs", []))
        demo_warnings.extend(rendered_paper.get("warnings", []))
        for lang in ("zh", "en"):
            rendered = viz.render_all(cfg, lang)
            demo_outputs.extend(rendered.get("outputs", []))
            demo_warnings.extend(rendered.get("warnings", []))
        mark_stage(cfg, "demo", "warning" if demo_warnings else "ok", 0, demo_outputs,
                   {"scientific_use": False, "warnings": demo_warnings})
        print(cfg.run_base)
        return

    assert_real_output(cfg)
    if stages and stages[0] not in FORMAL_STAGE_ORDER and stages[0] != "preflight" and not completed(cfg, "preflight"):
        stages = ["preflight"] + stages
    for stage in stages:
        if args.resume and not args.force and completed(cfg, stage):
            logger.info("跳过已完成阶段 %s（run_id=%s）", stage, cfg.run_id)
            continue
        t0 = time.time()
        try:
            logger.info("阶段 %s 开始执行；内部续跑/缓存由各子模块自行处理", stage)
            result = execute(stage, cfg) or {"status": "ok", "outputs": []}
            status = str(result.get("status", "ok"))
            mark_stage(cfg, stage, status, time.time()-t0, result.get("outputs", []),
                       {k:v for k,v in result.items() if k not in {"status","outputs"}})
            logger.info("阶段 %s 完成，状态=%s，内部摘要=%s", stage, status,
                        {k:v for k,v in result.items() if k not in {"status","outputs"}})
        except Exception as exc:
            mark_stage(cfg, stage, "failed", time.time()-t0, [], {"error": f"{type(exc).__name__}: {exc}"})
            logger.exception("阶段 %s 失败；可在修复问题后使用同一 RUN_ID 配合 --resume 继续", stage)
            raise
    logger.info("实验运行结束，输出目录: %s", cfg.run_base)
    print(cfg.run_base)

if __name__ == "__main__":
    main()
