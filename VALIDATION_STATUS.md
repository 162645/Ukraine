# Validation status — v2.4

Packaging-environment checks completed:

- Python compilation of `src/`, `run_all.py`, scripts and tests: **PASS**
- Unit tests: **25 passed**
- Synthetic end-to-end smoke run: **PASS**
- Chinese figure render: **15/15 rendered, 0 warnings**
- English figure render: **15/15 rendered, 0 warnings**
- Demo graphics produced: **30 PDF + 30 SVG + 30 PNG + 30 alt-text + 30 metadata sidecars**
- Demo PNG resolution: **150 dpi for fast smoke testing**
- Real-run PNG configuration: **600 dpi**, with PDF and SVG vector outputs
- Credential scan: **no live database credentials included**
- Font distribution check: **no font file included**
- Local Chinese submission font: **Hiragino Sans GB resolved; representative glyph check passed**
- Local configuration inheritance: **deep-merge regression test passed**
- Registered closure capacity: **five validation dates in three episodes; two summer clusters are publication-eligible, while December is a post-attack-recovery transport test**

Not completed in this environment:

- Connection to the user's remote ClickHouse instance
- Full real-data v2.4 run
- Scientific closure on the newly estimated results

Those steps require the user's read-only database connection. The authoritative result is the new run's `results/tables/closure_report.json`; a positive result is not forced. A scientifically complete negative or mixed result is represented by `GREEN_VALID_NEGATIVE_FINDINGS`.
