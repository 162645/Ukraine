# v2.1 change log

## Scientific fixes

1. Replaced raw-cycle assumptions with UTC two-hour bins.
2. Added an explicit full-scan denominator contract and zero-inclusive panels.
3. Made panel construction memory-bounded by two-day sparse partitions.
4. Added a separate frozen B1/B2 sensor-panel stage after held-out calibration.
5. Forced downstream primary analysis to use B2 only after a positive gate; otherwise B1.
6. Restricted target geography to the frozen target-IP country/Admin1 mapping.
7. Added mapping snapshot cutoff, row-count/checksum contract and database verification.
8. Added same-ASN matching balance diagnostics and prohibited primary cross-ASN fallback.
9. Added B1/B2 downstream sensitivity, pretrend equivalence and anchor sensitivity.
10. Added independent third-party temporal/spatial concordance as Experiment F.
11. Replaced row-random prediction with chronological whole-event rolling origin.
12. Removed current-event outcomes/path variables from prediction and added leakage/permutation audits.
13. Added exact regional/national outage-interval overlap and exposure-variation gates.
14. Rebuilt path groups from target mapping and selected sensor-panel prefixes.
15. Restricted direct path edges to adjacent known public hops and normalised event-specific frequencies.
16. Added a conditional negative-calibration paper branch and an optional path-analysis branch.

## Figure fixes

- Chinese and English labels throughout;
- vector PDF/SVG and 600-dpi PNG;
- embedded/outlined-compatible fonts;
- colour-blind-safe palette plus line/marker redundancy;
- event-specific ingress panels instead of pooled raw counts;
- event-coded functional-loss/path-adaptation scatter;
- external-concordance figure F13;
- invalid results are skipped with machine-readable warnings.

## Engineering fixes

- run-scoped manifests and output directories;
- no stored credentials;
- isolated and watermarked synthetic demo mode;
- mapping-freeze helper;
- unit tests for calibration, geography, exposure, path adjacency, event centring, prediction time order and zero filling;
- final scientific closure report.

## v2.2 — closure hardening and artifact packaging

- fixed `--resume` so the existing manifest and completed-stage records are preserved;
- reject stale run reuse and frozen-input changes;
- register output SHA-256 or directory inventory provenance in every stage;
- retry ClickHouse read-only connections without client-side settings;
- added matched pre-event validation controls and event-specific B2-vs-B1 calibration consistency;
- added Figure F14 for event-specific held-out calibration gain;
- primary prediction now records ML fit failures and cannot credit a diagnostic fallback;
- permutation null jointly shuffles the current-event outcome vector within event;
- path analysis reports target-specific JSD after excluding source-common baseline edges;
- added same-target-IP overlap diagnostics for random traceroute targets;
- added per-figure metadata sidecars with source-table hashes;
- aligned README and results contract with the actual ClickHouse schema and outputs;
- added artifact-evaluation instructions and expanded unit tests.

## v2.3 — support-aware audit and endpoint-level spatial contract

- Replaced nominal-edge completeness gating with observed-support completeness.
- Added event-specific data availability audit.
- Added 2024-06-24 prospective training outage and moved unsupported June events to context-only.
- Added exact aliases for Kyiv City/Kyiv Oblast and Kirovohrad variants.
- Added `COUNTRY_ONLY_UA` national-only geography policy.
- Added endpoint-level target mapping and split `/24×group` analysis units.
- Corrected event-panel response numerators for mixed-prefix groups.
- Corrected path target grouping to use exact destination-IP mapping.
- Added three regression tests; total test suite now 13 tests.

## v2.3 — import-ledger completeness, endpoint geography, and prospective calibration

- Replaced response-row-volume completeness gating with `import_files` acquisition gating. Low/zero Ping response volume remains an outcome in a completed full-scan cycle.
- Added endpoint-level frozen mapping and `/24×ASN×country×Admin1` split analysis units.
- Added `COUNTRY_ONLY_UA`, explicit Kyiv City/Kyiv Oblast and Kirovohrad aliases, plus a raw-to-canonical mapping audit.
- Added event-level time-coverage and treated-region target-coverage checks before downstream experiments.
- Changed scheduled-outage design to 2024-08-19 training and 2024-12-09 held-out validation; 2024-06-24 is contextual/confounded only.
- Added provisional-vs-publication-grade calibration status because only one independent clean held-out planned outage is currently available.
- Preserved B1 fallback when B2 does not add held-out value.
- Kept path adaptation conditional on high-confidence adjacent observed hops and exact destination-IP mapping.

## v2.4 — stage-aware inference and valid-negative scientific closure

- Separated attack start, outage implementation and third-party network anomaly times.
- Added clean baseline, transition, outcome and post-recovery event stages.
- Added independent `confirmatory_power`, `attack_onset` and `network_replication` estimands.
- Replaced raw matched differences with pair-level clean-baseline-centered DID.
- Replaced nonsignificant-trend gating with practical level-and-slope equivalence intervals.
- Added target-universe U1/U2/U3 sensitivity and separate national/regional geography eligibility.
- Added regional false-treatment and national false-date placebos.
- Strengthened repeatability with bootstrap confidence intervals and ICC requirements.
- Strengthened prediction with whole-event holdouts, event-wise wins and minimum test-event counts.
- Added dependency preflight and clustered fallback models for recovery debt.
- Added BH-FDR correction for quality-admissible AS/ASGeo path tests.
- Added positive, valid-negative, incomplete-evidence and design-failure closure states.
- Reworked bilingual figures for common support, common event scales, vector output, 600-dpi real PNGs, accessible line/marker encodings and explicit CJK font resolution.
- Expanded the release to 20 unit tests and added a complete artifact reproduction contract.
