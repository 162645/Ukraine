# Ch3/Ch4 consistency audit code

Code snapshot synchronized from the local audit package on 2026-10-26. It contains the formal strict last-hop ASGeo reclassifier, four-figure renderer, and output assertions. Source evidence and generated results remain in the local audit package and are not committed here.

To reproduce, place the required anonymized source snapshots under this folder at data_audit/source_snapshots/ch3, data_audit/source_snapshots/ch4, and data_audit/source_snapshots/paper, then run independent_audit.js, render_figures.js, and validate_audit.js with Node.js 24+. Rendering needs the repository's sharp dependency and a local Chinese TrueType font. No credentials or server configuration are included.
