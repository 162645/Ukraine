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
| Activity raw score and clean-cycle exclusions | PARTIAL | Raw/smoothed Activity and planned/attack exclusion are implemented; no dedicated persisted `ip_activity.parquet` and no separate recovery-window test. |
| No `A_i >= .8` primary gate | PASS | `simple_calibration.py` uses `is_event_candidate`; legacy stable flag is diagnostic. |
| Within-state D1–D10 | PASS | `activity_decile` is computed in `simple_calibration.py`; real population still needs execution. |
| Event-level `S_i,e = p_ctrl - p_out` | PASS | `score_event_rows`; negative values are retained. |
| Same-IP/state/slot/weekday controls | PARTIAL | Same-slot control logic exists; no dedicated regression test proving every exclusion condition. |
| Episode-equal final `S_i` | PASS | `aggregate_sensors`; episode collapse and equal averaging are implemented. |
| Support ≥2/3/4 | PASS | `support_ge_2/3/4` fields and state summary. |
| Within-state Q1–Q5 | PASS | `s_reach_quintile`/`s_rtt_quintile`. |
| RTT separate and conditional | PASS | `s_rtt_event`; no combined score. |
| Canonical IPS independent of labels | PASS | `canonical_stage.py` queries the measurement universe. |
| Canonical FBS monthly E≥3 | PARTIAL | Pure function and ClickHouse stage exist; monthly modal mapping and full real output are not yet verified in this branch. |
| Required execution order | PARTIAL | `paperAnalysis` is wired before figures; no completed real run through all stages. |

## Sections 18–38: figures

| Figure | Status | Finding |
|---|---|---|
| Figure 0 quality timeline/availability | BLOCKED | Existing `f1_coverage.csv` supports legacy coverage; new Figure 0 functions/source contract are not implemented. |
| Figure 1 Oblast coverage | BLOCKED | No dedicated `fig01_oblast_coverage` plot function. |
| Figure 2 IPS/FBS heatmap | PARTIAL | Canonical source, metadata, and renderer exist; attack markers, missing-cycle lane, and real output not verified. |
| Figure 3 power/internet calendar | BLOCKED | Source filename is registered, but no plot function. |
| Figure 4 monthly outage hours | BLOCKED | No dedicated source computation/plot. |
| Figure 5 Activity distribution | PARTIAL | Basic ECDF renderer exists; required decile population panel and full source table are missing. |
| Figure 6 Sensitivity distribution | PARTIAL | Basic histogram exists; support distribution and complete source table are missing. |
| Figure 7 Activity×Sensitivity | PARTIAL | Basic hexbin exists; correlation statistics and formal information contract are missing. |
| Figure 8 overall attack IPS | BLOCKED | No dedicated event-aligned overall IPS source/plot in the new renderer. |
| Figure 9 Q1–Q5 curves | BLOCKED | No event-equal curve reducer/CI plot. |
| Figure 10 H1 heterogeneity | PARTIAL | H1 table and simple summary plot exist; cluster CI and outage/recovery supplements are missing. |
| Figure 11 H2 gradient | PARTIAL | H2 table/plot entry exists; complete peak/outage/recovery panels and CI are missing. |
| Figure 12 H3 10×5 heatmap | PARTIAL | Joint Activity×Sensitivity table exists; NA hatch, minimum support and heatmap rendering are missing. |
| Figure 13 H3 continuous association | BLOCKED | Existing legacy association output is not converted to the requested new source/plot contract. |
| Figure 14 H4 decomposition | PARTIAL | Reducer and basic plot exist; sum-to-one gate and Activity supplementary version are missing. |
| Figure 15 ASN / /24 structure | BLOCKED | No new reducer/plot. |
| Figure 16 AS event timeline | BLOCKED | No new reducer/plot. |
| Figure 17 RTT heatmap | BLOCKED | No new reducer/plot. |
| Figure 18 threshold sensitivity | BLOCKED | No new threshold sweep reducer/plot. |
| Figure 19 power–internet correlation | BLOCKED | No new reducer/plot. |
| No big titles, vector outputs, metadata, source CSV | PARTIAL | Core renderer follows these rules; all registered figures do not yet have real plot functions. |

## Sections 39–49: tables and source-data contract

| Requirement | Status | Finding |
|---|---|---|
| Dataset summary | FAIL | `dataset_summary.csv` is not generated. |
| Planned-outage event summary | PARTIAL | Calibration audit exists, but the specified `calibration_event_summary.csv` is not generated. |
| Held-out attack summary | FAIL | `attack_event_summary.csv` is not generated. |
| H1/H2/H3/H4 machine-readable tables | PARTIAL | H1–H4 filenames are generated by `paperAnalysis`, but H2/H3/H4 are empty until upstream features exist and do not yet include all requested CI/model fields. |
| Figure metadata | PARTIAL | Metadata sidecars are generated for registered source files; many corresponding plots are absent. |

## Sections 50–58: tests, run protocol, and scientific boundary

| Requirement | Status | Finding |
|---|---|---|
| Required config blocks | PASS | Activity, sensitivity, macro signals, and figure analysis blocks exist. |
| 20 requested tests | PARTIAL | 54 tests pass, but dedicated tests are missing for recovery exclusion, frozen labels, figure row/stat consistency, checkpoint invalidation, and all H4 cases. |
| No synthetic scientific results | PASS | Demo is explicitly marked synthetic; real reducers do not fill missing evidence with zeros. |
| GeoIP longitudinal limitation | PASS | README and audit document single-snapshot limitation. |
| Preflight | PASS_WITH_LIMITS | Previous remote preflight passed with optional weather/source warnings; it has not been rerun after this latest commit. |
| Dry run | PASS_WITH_LIMITS | Local demo pipeline passed; it is not a real ClickHouse dry run. |
| Full real run | BLOCKED | Not rerun after the latest changes; remote SSH became unresponsive. |
| Final report with all requested fields | PARTIAL | Core definitions/status are documented; per-figure actual results and real-run evidence remain unavailable. |
| Scientific boundary | PASS | Code/docs use planned-outage-associated reachability sensitivity, not physical electricity dependence. |

## Verdict

The repository is **not yet fully compliant** with the pasted plan. The core
population/sensitivity/canonical-signal redesign is substantially implemented,
but the publication layer is incomplete: 10+ requested figures, three summary
tables, threshold robustness, complete H1–H4 inference, and the post-change
real remote run remain outstanding. The correct release state is
`PARTIAL / BLOCKED`, not “finished”.
