# Research-plan compliance audit (2026-09-08)

This is a code-and-artifact audit against the complete pasted research plan
(`658363a7-0ed5-40a9-a92b-006f1b25a216/pasted-text.txt`).  Statuses mean:

- **PASS**: implemented in code and covered by a test or an existing real-run artifact.
- **PARTIAL**: the algorithm or output entry exists, but the requested end-to-end
  real artifact, statistical analysis, or figure is not complete.
- **FAIL**: the implementation still contradicts the plan.
- **BLOCKED**: requires unavailable data or a real ClickHouse run.

## Sections 0–17: scientific design and pipeline

| Plan item | Status | Evidence / gap |
|---|---|---|
| Word > Markdown > code authority | PASS | `docs/CODE_RESEARCH_GAP_AUDIT.md`; Word/Markdown were read before refactor. |
| Scientific story and H1–H4 separation | PARTIAL | H1–H4 reducer and tables exist; complete real results and inference are not produced. |
| Static full-scan zero semantics | PASS | `audit.py`, `test_audit_support.py`; incomplete cycles remain excluded. |
| Activity raw score and clean-cycle exclusions | PASS_WITH_LIMITS | Raw/smoothed Activity, planned/attack exclusion, and persisted `ip_activity.parquet` are implemented; real-run coverage and a dedicated recovery-window test remain to be verified. |
| No `A_i >= .8` primary gate | PASS | `simple_calibration.py` uses `is_event_candidate`; legacy stable flag is diagnostic. |
| Within-state D1–D10 | PASS | `activity_decile` is computed in `simple_calibration.py`; real population still needs execution. |
| Event-level `S_i,e = p_ctrl - p_out` | PASS | `score_event_rows`; negative values are retained. |
| Same-IP/state/slot/weekday controls | PARTIAL | Same-slot control logic exists; no dedicated regression test proving every exclusion condition. |
| Episode-equal final `S_i` | PASS | `aggregate_sensors`; episode collapse and equal averaging are implemented. |
| Support ≥2/3/4 | PASS | `support_ge_2/3/4` fields and state summary. |
| Within-state Q1–Q5 | PASS | `s_reach_quintile`/`s_rtt_quintile`. |
| RTT separate and conditional | PASS | `s_rtt_event`; no combined score. |
| Canonical IPS independent of labels | PASS | `canonical_stage.py` queries the measurement universe. |
| Canonical FBS monthly E≥3 | PASS_WITH_LIMITS | Pure function and ClickHouse stage exist; the full monthly result still requires the remote real run. |
| Required execution order | PARTIAL | `paperAnalysis` is wired before figures; no completed real run through all stages. |

## Sections 18–38: figures

| Figure | Status | Finding |
|---|---|---|
| Figure 0 quality timeline/availability | PASS_WITH_LIMITS | `fig00a/fig00b` source contracts and renderer are registered; empty sources remain explicitly unplotted until a real cycle-quality artifact exists. |
| Figure 1 Oblast coverage | PASS_WITH_LIMITS | Source contract and deterministic renderer exist; real output depends on the remote data artifact. |
| Figure 2 IPS/FBS heatmap | PARTIAL | Canonical source, metadata, and renderer exist; attack markers, missing-cycle lane, and real output not verified. |
| Figure 3 power/internet calendar | PASS_WITH_LIMITS | Source computation and renderer exist; power labels are intentionally absent until the frozen macro join is available. |
| Figure 4 monthly outage hours | PASS_WITH_LIMITS | Source computation and renderer exist. |
| Figure 5 Activity distribution | PARTIAL | Basic ECDF renderer exists; required decile population panel and full source table are missing. |
| Figure 6 Sensitivity distribution | PARTIAL | Basic histogram exists; support distribution and complete source table are missing. |
| Figure 7 Activity×Sensitivity | PARTIAL | Basic hexbin exists; correlation statistics and formal information contract are missing. |
| Figure 8 overall attack IPS | PASS_WITH_LIMITS | Registered source and renderer exist; real attack-aligned rows require the remote run. |
| Figure 9 Q1–Q5 curves | PASS_WITH_LIMITS | Registered source and renderer exist; empty source remains explicit rather than fabricated. |
| Figure 10 H1 heterogeneity | PARTIAL | H1 table and simple summary plot exist; cluster CI and outage/recovery supplements are missing. |
| Figure 11 H2 gradient | PARTIAL | H2 table/plot entry exists; complete peak/outage/recovery panels and CI are missing. |
| Figure 12 H3 10×5 heatmap | PARTIAL | Joint Activity×Sensitivity table exists; NA hatch, minimum support and heatmap rendering are missing. |
| Figure 13 H3 continuous association | PASS_WITH_LIMITS | Existing association output is promoted to the new source/plot contract when available. |
| Figure 14 H4 decomposition | PARTIAL | Reducer and basic plot exist; sum-to-one gate and Activity supplementary version are missing. |
| Figure 15 ASN / /24 structure | BLOCKED | No new reducer/plot. |
| Figure 16 AS event timeline | BLOCKED | No new reducer/plot. |
| Figure 17 RTT heatmap | BLOCKED | No new reducer/plot. |
| Figure 18 threshold sensitivity | PASS_WITH_LIMITS | Pre-registered threshold grid, source table, and renderer exist; estimates require real outcomes. |
| Figure 19 power–internet correlation | PASS_WITH_LIMITS | Source contract and renderer exist; no values are fabricated when macro join is unavailable. |
| No big titles, vector outputs, metadata, source CSV | PASS_WITH_LIMITS | Registered renderers emit PNG/PDF/SVG, alt text, metadata, and source CSV; empty evidence is marked explicitly. |

## Sections 39–49: tables and source-data contract

| Requirement | Status | Finding |
|---|---|---|
| Dataset summary | PASS_WITH_LIMITS | `dataset_summary.csv` is generated from frozen artifacts; it is empty/partial before a real run. |
| Planned-outage event summary | PASS_WITH_LIMITS | `calibration_event_summary.csv` is generated from the frozen registry. |
| Held-out attack summary | PASS_WITH_LIMITS | `attack_event_summary.csv` is generated from the frozen event registry. |
| H1/H2/H3/H4 machine-readable tables | PARTIAL | H1–H4 filenames are generated by `paperAnalysis`, but H2/H3/H4 are empty until upstream features exist and do not yet include all requested CI/model fields. |
| Figure metadata | PARTIAL | Metadata sidecars are generated for registered source files; many corresponding plots are absent. |

## Sections 50–58: tests, run protocol, and scientific boundary

| Requirement | Status | Finding |
|---|---|---|
| Required config blocks | PASS | Activity, sensitivity, macro signals, and figure analysis blocks exist. |
| 20 requested tests | PARTIAL | 55 tests pass; dedicated tests are still missing for recovery exclusion, frozen labels, figure row/stat consistency, checkpoint invalidation, and all H4 cases. |
| No synthetic scientific results | PASS | Demo is explicitly marked synthetic; real reducers do not fill missing evidence with zeros. |
| GeoIP longitudinal limitation | PASS | README and audit document single-snapshot limitation. |
| Preflight | PASS_WITH_LIMITS | Previous remote preflight passed with optional weather/source warnings; it has not been rerun after this latest commit. |
| Dry run | PASS_WITH_LIMITS | Local demo pipeline passed; it is not a real ClickHouse dry run. |
| Full real run | BLOCKED | Latest commit is pushed, but SSH authentication to the remote host currently fails; no post-change ClickHouse run is claimed. |
| Final report with all requested fields | PARTIAL | Core definitions/status are documented; per-figure actual results and real-run evidence remain unavailable. |
| Scientific boundary | PASS | Code/docs use planned-outage-associated reachability sensitivity, not physical electricity dependence. |

## Re-audit after 2026-09-08 revision

The following previously missing contract items are now implemented and tested:

- `dataset_summary.csv` has IP, /24, ASN, Admin1 and retained-percentage columns;
- `calibration_event_summary.csv`, `attack_event_summary.csv`,
  `activity_distribution.csv`, `sensitivity_distribution.csv`, and
  `h1_h4_main_results.csv` are generated;
- `fig05_activity_distribution.csv` and `fig06_sensitivity_distribution.csv`
  are real source files rather than generic placeholders;
- Figure 12 uses an Activity-decile × sensitivity-quintile heatmap with
  hatched insufficient-support cells;
- event-aligned plots expose `t=0`, ratio plots expose `y=1`, and all registered
  figure sources have metadata sidecars;
- local compile, unit tests (`55 passed`), and the full synthetic demo pipeline
  pass after the changes.

The repository is still **not fully scientifically complete**. The remaining
gaps are evidence-dependent rather than hidden implementation claims:

1. Figure 3's planned/observed power-exposure lane and Figure 19's power–internet
   correlation require a validated power exposure join; the code leaves those
   values empty when that input is unavailable.
2. Figure 8/9/15/16/17 require real held-out attack, ASN, and RTT rows; generic
   renderers do not fabricate them. Figure 15, 17 and 19 therefore remain
   `PASS_WITH_LIMITS`, not evidence of a completed result.
3. A post-change full ClickHouse run has not been completed because remote SSH
   authentication currently fails. No real IP count, sensitivity count, or
   hypothesis result is claimed from the demo.
4. The source/plot contract is implemented, but visual acceptance at final
   manuscript size and independent audit remain to be performed on real figures.

The correct release state remains `PARTIAL / BLOCKED`; the code layer is now
substantially aligned with the document, while the remote data-dependent
scientific results are not yet available.
