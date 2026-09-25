# Final strict-traceroute figure closure (v8)

`scripts/finalize_traceroute_figures_v8.py` is a display/provenance-only
closure step. It consumes:

- the frozen `final_paper_compact_v7` package;
- the completed strict ClickHouse rebuild artifacts at commit `c1a0844`;
- the historical S2 package only to record audit hashes and preserve its
  coordinate/typography provenance.

The script changes only Figure 5(c) and Supplement S2 from the historical
10,697-label definition to the strict set of 7,430 public intermediate-hop IPs
observed before the target in contemporaneous own-traceroute paths. Figure 1–4
are copied byte-for-byte. Figure 5(a/b) keep their frozen inputs and layout.

It does not query ClickHouse, construct new bins, fit a model, select a
threshold, or modify the frozen main-sample data.

Server invocation:

```bash
python scripts/finalize_traceroute_figures_v8.py \
  --v7-root /home/wsl/final_paper_compact_v7 \
  --strict-rebuild-root /home/wsl/Ukraine_method_lineage_20260925/outputs/own_traceroute_rebuild_v1 \
  --legacy-s2-root /home/wsl/XiaoLunWen_doc_complete_20260908/paper_current_final_v3_fixed \
  --visual-review /home/wsl/Ukraine_paper_figures_v8_work/docs/S2_V8_RENDER_REVIEW.md \
  --out /home/wsl/final_paper_compact_v8
```

The release gate is `qa/S2_STRICT_REBUILD_STATUS.txt`. A passing package must
contain bilingual PNG/PDF/SVG S2 files, the strict frozen figure-data CSV,
coverage table, captions, figure/file manifests, and QA records.
