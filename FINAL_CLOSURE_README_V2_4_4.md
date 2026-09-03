# v2.4.4 final closure supplement

This supplement consumes the already completed run `runs/paper_v24_real_01`.
It does **not** rerun the v2.4 ClickHouse/core pipeline.

## Reproduce the incremental closure

```bash
cd /Users/bytedance/WorkPlace/code_file/TTADK/else/ukraine/ukraine_resilience_experiment_v2_4
bash scripts/finish_v24_closure.sh --run-id paper_v24_real_01
```

Add `--execute-external` only after CDS credentials/terms are configured and
network retrieval is intended. Missing external inputs remain explicit and do
not trigger retuning.

## Scientific decision

The positive causal chain is not supported. The study can close as a negative,
boundary-setting result: weak scheduled-outage supervision is directionally
consistent but fails the preregistered calibration gate; the ASN-Admin1
fingerprint is neither repeatably stable nor predictively validated. Observable
attack deficits and selected recovery/path signals remain conditional secondary
findings.

See `docs/MANUSCRIPT_CLOSURE_DECISION_V2_4_4.md` and
`runs/paper_v24_real_01/results/tables/closure_decision_v2_4_4.csv`.

## Included evidence and data access

- All CSV/JSON result tables from the frozen run.
- English and Chinese closure figures as PDF, PNG, and SVG.
- Official-warning Admin1 x 2-hour table and checksum.
- Downloaded IODA and geography inputs with manifests.
- Public-page response-byte snapshots where retrieval succeeded, failure logs,
  research captures, source correction registry, and hashes.
- Source code and scripts needed to reproduce the incremental checks.

The v2.4.4 materials do not contain ERA5 continuous weather values or a native
Telegram Desktop JSON export. They must not be described as present.

