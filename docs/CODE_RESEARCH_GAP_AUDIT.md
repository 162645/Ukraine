# Word and Code Research Gap Audit

## Scope and authority

The Word research plan is the primary authority, the Markdown plan is the secondary source for event and attack registries, and the current branch is treated as an implementation snapshot. The audit is intentionally limited to the materials present in this workspace; it does not claim that a longitudinal monthly GeoIP snapshot exists.

## Word requirements

- Activity is a continuous baseline covariate: clean normal cycles exclude planned outages, held-out attacks and acquisition failures; the minimum support is configurable (24 cycles in the formal plan).
- Planned-outage sensitivity is computed per independent episode as `S_i,e = p_ctrl - p_out`, retaining negative values, then averaged with equal weight across episodes to obtain continuous `S_i`.
- Reachability and conditional RTT sensitivity remain separate quantities.
- Canonical IPS and FBS are computed from the measurement universe, not from B1, sensitivity-support, or quintile labels.
- Held-out attacks freeze the planned-outage labels before validation. H1--H4 must be reported as separate outputs.
- Within-state Activity uses D1--D10 and sensitivity uses Q1--Q5; these are descriptive strata, not population gates.

## Markdown additions

The Markdown plan supplies the reviewed planned-outage windows, evidence tiers, explicit clear windows, and the six held-out war-energy attacks. It also documents the weak-supervision interpretation and the limitation that a single current GeoIP snapshot cannot reproduce the original paper's longitudinal 70/70 regional classification.

## Current implementation before this pass

The branch already contained event-level calibration, episode collapse,
same-slot controls, conditional RTT, attack registries, and a Figure 8 regional
signal experiment. The audit found that the remaining high-risk gaps were not
just naming: Activity/B1 admission, missing D/Q joint groups, absent H1--H4
tables, and no complete paper source-data contract.

## Resolved in this refactor

This refactor makes the full regional target universe the canonical calibration population whenever an IP has the minimum clean-cycle support. The legacy B1 flag is retained only as a diagnostic compatibility field. Activity is exported continuously (`activity_score_raw`, with an optional smoothed helper), and calibration no longer removes endpoints solely because their normal response rate is below 0.8. Sensitivity labels retain negative values and remain separate for reachability and RTT. The audit and tests explicitly document the canonical-universe boundary.

The current pass additionally adds within-state Activity D1--D10 labels,
canonical Activity×Sensitivity groups, a `paperAnalysis` stage with H1--H4
machine-readable tables, registered figure source CSV/metadata sidecars, and a
publication-oriented renderer for the available core figures. Missing upstream
evidence remains an explicit empty source and warning; no synthetic result is
created to satisfy a figure filename.

## Remaining boundaries

- The current branch still contains legacy B1/B2 validation modules for backward-compatible historical outputs; they are not evidence that canonical IPS/FBS use a label-filtered population.
- The H1--H4 reducer and core paper renderer are now wired into the pipeline,
  but figures whose upstream attack/network table is absent are intentionally
  reported as unavailable rather than presented as completed scientific results.
- Full real-mode ClickHouse execution is not started by this change. It requires a preflight and an explicit long-running command after tests and dry-run pass.
- Longitudinal GeoIP drift correction remains unavailable without monthly mapping snapshots and must remain a limitation in the paper.
