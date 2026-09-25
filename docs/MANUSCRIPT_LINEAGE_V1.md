# Manuscript scientific-lineage closure v1

This branch pauses manuscript prose and figure iteration. Its only purpose is to close the scientific lineage used by the manuscript.

`scripts/build_manuscript_lineage.py` is run on the measurement server against read-only frozen inputs. It produces:

- `MANUSCRIPT_EVENT_CROSSWALK.csv`: interval-overlap mapping from verified schedule IDs to frozen cache IDs and canonical analysis opportunities;
- `EVENT_COUNT_SEMANTICS.csv`: explicit definitions for schedule rows, schedule IDs, legacy audit rows, and cache-event × oblast opportunities;
- `MANUSCRIPT_VARIABLE_DICTIONARY.csv`: the four manuscript variables with numerator, denominator, time window, unit, missingness, and source code;
- `MISSINGNESS_AND_DENOMINATOR_CONTRACT.md`: normative complete-cycle and non-response semantics;
- `MASTER_IDENTITY_QA.csv`: full-row identity checks between the crosswalk-rebuilt and frozen Power/Normal master columns;
- `MANUSCRIPT_RESULT_MANIFEST.csv`: manuscript result values with source file, source rule, script, commit, and input hash;
- `TRACEROUTE_PROVENANCE.*`: recovered four-target sampler provenance, explicitly separated from the measured data;
- `TRACEROUTE_MEASUREMENT_SCHEMA.tsv`, `TRACEROUTE_MEASUREMENT_MANIFEST_BY_CYCLE.csv`, and `TRACEROUTE_MEASUREMENT_SAMPLE.jsonl`: schema, per-cycle content digests, and a small sample read directly from the authoritative ClickHouse traceroute table.

The script never draws a figure and never fits a new statistical model. If the interval-overlap cohort differs from the frozen cohort, or any frozen master numerator/denominator differs, the closure status is `FAIL_REANALYSIS_REQUIRED`.

Server invocation:

```bash
export CLICKHOUSE_PASSWORD='<set outside git>'
python scripts/build_manuscript_lineage.py \
  --root /home/wsl/XiaoLunWen_doc_complete_20260908 \
  --output /home/wsl/manuscript_lineage_v1 \
  --traceroute-sampler-snapshot /home/test/GlobalPing_ZT/kernal/areaPing/areaPing.go \
  --traceroute-source-repo /home/test/GlobalPing_ZT \
  --clickhouse-url http://10.112.131.168:8124 \
  --clickhouse-user measure_user
```
