# Final v2.4 closure without rerunning the core experiment

The completed core run is `runs/paper_v24_real_01`. The closure workflow reads
its frozen tables and cached Parquet files; it does not execute `run_all.py`,
query ClickHouse, rebuild B1/B2, or rerun Experiments A-G.

After configuring CDS credentials (and optionally Cloudflare) run:

```bash
bash scripts/finish_v24_closure.sh --run-id paper_v24_real_01 --execute-external
```

Without `--execute-external`, the same command performs an offline dry run and
generates every sensitivity and figure supported by already available inputs.

Telegram Desktop export remains manual. Ingest it before the final release:

```bash
python3 scripts/ingest_telegram_export.py /path/to/result.json --root .
python3 scripts/verify_evidence_archive.py --root .
```

The workflow is intentionally fail-visible: missing weather, evidence, or
episode-specific endpoint scores appear as `not_estimable` in
`final_closure_sensitivity_status.csv`; no result is silently omitted.
