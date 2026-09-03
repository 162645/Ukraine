# v2.4 closure supplement package

This supplement is designed for the already completed core run
`paper_v24_real_01`. It must not be used to rerun or retune the v2.4 core.

## Included

- Actual CSV/JSON closure tables generated from the frozen v2.4 outputs.
- Five-page English and Chinese closure figure books, plus editable SVG and
  300-DPI PNG figures.
- Raw IODA responses for all frozen country/ASN requests, geoBoundaries ADM1
  geometry, request manifests, and SHA-256 records.
- Reproducible ERA5-Land, IODA, Cloudflare, geography, and evidence-archive
  access code.
- A single incremental runner that never invokes `run_all.py` or ClickHouse.

## One command

From the project root, after configuring a CDS API key and accepting the
ERA5-Land dataset terms:

```bash
bash scripts/finish_v24_closure.sh --run-id paper_v24_real_01 --execute-external
```

This command downloads/prepares external inputs, audits evidence, refreshes
only the weather sensitivity from the already frozen validation table, runs
the other closure checks from cached tables/Parquet, and redraws the bilingual
closure figures. It does not rerun v2.4.

## Honest remaining release gates at packaging time

- `data_derived/weather_admin1_2h.parquet` is absent because CDS credentials
  and accepted terms are user-specific.
- The evidence verification report is present but `ok=false`: Volyn public
  snapshot, UHMC heat snapshot, and the Zaporizhzhia Telegram JSON export are
  not yet submission-ready.
- IP-level B2 membership stability is not estimable without reconstructing
  episode-specific endpoint scores. The completed run stored only the merged
  training-episode score. Because the user requested no core rerun, this is
  reported as a limitation rather than approximated with aggregate data.

These gaps do not invalidate the negative/mixed scientific closure, but the
first two should be completed before artifact release or submission.
