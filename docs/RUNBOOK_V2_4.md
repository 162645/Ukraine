# Runbook v2.4

## Before starting

1. Use Python 3.11 or 3.12, create a clean virtual environment and install `requirements.txt`.
2. Run `PYTHONPATH=src pytest -q`; all tests must pass. Do not rely on a stale fixed test count.
3. Export ClickHouse credentials from a local, untracked file.
4. Run `./check_ch.sh` (Linux/macOS) or `.\check_ch.ps1` (Windows). This tries both
   ClickHouse HTTP and native protocols and prints a credential-free schema inventory.
   Add `--deep --output diagnostics/clickhouse_inventory.json` only when exact row counts
   and table time ranges are needed.
5. Confirm the frozen mapping snapshot in `config/mapping_manifest_v2.frozen.json` still matches the database snapshot. Preflight checks this.
6. Confirm `study.static_full_scan_confirmed=true` is factually correct.
7. Install a CJK font or set `URESIL_CJK_FONT` for Chinese figures.

## Recommended command

```bash
./scripts/run_paper.sh --run-id paper_v24_real_01
```

默认行为：
- 若存在 `.env.local`，启动前自动加载
- 默认开启 `--resume`，同一个 `RUN_ID` 会自动续跑并跳过已完成阶段
- 顶层失败时会做有限次自动重试，并沿用同一个 `RUN_ID`
- `validate` 成功后自动写入 `artifact_inventory.json`，并在 `run_archives/` 生成拒绝静默覆盖的核心结果 ZIP 与 SHA-256 sidecar

常用变体：

```bash
./scripts/run_paper.sh --run-id paper_v24_real_01 --clean-run
./scripts/run_paper.sh --mode demo --run-id paper_v24_demo_01
./scripts/run_paper.sh --run-id paper_v24_real_01 --check
```

## Staged execution

If you need manual control, staged execution is still supported:

```bash
python run_all.py --mode real --run-id "$RUN_ID" --stage preflight audit
python run_all.py --mode real --run-id "$RUN_ID" --stage panels expA expRegional sensorPanels --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage features expB expE expG --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage expF expD expC --resume
python run_all.py --mode real --run-id "$RUN_ID" --stage figures validate --resume
python scripts/archive_run.py --run-dir "runs/$RUN_ID" --bundle-dir run_archives
```

Use the same `RUN_ID` together with `--resume` whenever you want to continue a stopped run manually.

## Do not resume v2.3

v2.4 changes the frozen plan, event windows, regional estimands, target universe and output contracts. Start a new run ID.

## Failure triage

- Preflight dependency failure: reinstall from requirements; do not continue.
- Audit fatal gate: inspect `quality_report.json` and `event_data_availability.csv`; do not lower thresholds simply to pass.
- Experiment A negative: expected branch; B1 must become primary.
- Regional calibration negative: do not claim that planned outages calibrate power-sensitive
  sensors; retain it as a falsified mechanism/boundary result.
- Experiment B pretrend failure: inspect attack/outage transition and event registry; do not move the anchor by outcome inspection.
- Experiment C insufficient holdouts: report incomplete evidence; do not randomly split group-event rows.
- Experiment D not identified: obtain finer regional outage exposure or remove the claim.
- Experiment E diagnostic only: retain as limitation or selected case studies.

## Reproduce figures

```bash
RUN_ID=paper_v24_real_01 scripts/reproduce_figures.sh
```

Every figure sidecar lists source tables and hashes.
