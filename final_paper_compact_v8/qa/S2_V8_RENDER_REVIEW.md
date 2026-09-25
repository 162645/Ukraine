# V8 strict-traceroute render review

Review date: 2026-09-26 (Asia/Shanghai)

Reviewed the server-rendered PNG files at their exported dimensions:

- `S2_own_traceroute_strict_en.png` — 1905 × 1183 px, 300 dpi
- `S2_own_traceroute_strict_zh.png` — 1906 × 1182 px, 300 dpi
- `figure5_multisource_robustness_v8_en.png` — 4936 × 1576 px, 600 dpi
- `figure5_multisource_robustness_v8_zh.png` — 4936 × 1596 px, 600 dpi

The first Figure 5(c) render used an overlong vertical label and was rejected.
The final render shortens only the panel title and axis label; the complete
strict label definition remains in both formal captions.

Final visual checks:

- titles, axes, ticks, points, and Wilson intervals are visible;
- Chinese and English glyphs render correctly;
- no title, axis label, tick label, or interval is clipped;
- Figure 5 panels remain separated and readable on their frozen layout;
- Supplement S2 uses the frozen coordinate ranges and preserves the existing
  point/error-bar grammar;
- the figures make a descriptive association claim only and do not imply a
  threshold, fitted model, causality, or infrastructure ground truth.

Three-second reading: the strict own-traceroute evidence is concentrated more
toward the high-availability end. Thirty-second reading: the reader can inspect
the full bin sequence and Wilson 95% intervals on a common linear scale.

`render_review_status = PASS`
