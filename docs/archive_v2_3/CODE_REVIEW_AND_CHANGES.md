# Code review and redesign summary

This package is a scientific redesign of the submitted experiment code, not a cosmetic refactor.  It is organised around the paper's single chain of evidence:

1. scheduled outages provide externally registered weak labels;
2. B1 stable endpoints and B2 outage-sensitive endpoints are estimated only from training outages;
3. B2 is used downstream only if it beats B1 on held-out scheduled outages under the frozen bootstrap gate;
4. otherwise all downstream primary analyses automatically use B1 and the paper follows the negative-calibration branch;
5. the frozen sensor panel is applied to held-out attacks and the Sumy blind test;
6. only then are repeatability, prospective prediction, recovery debt and conditional path adaptation evaluated.

## Defects corrected

- Synthetic demo outputs are isolated and watermarked.
- Each real run has one immutable `run_id`; no stale table or figure is reused silently.
- Analysis cycles are UTC two-hour bins, not unverified raw cycle identifiers.
- Response-only Ping rows are never averaged without an explicit denominator.
- Missing response cells are materialised as zero only after the user confirms the scanner attempted the full frozen inventory.
- B1/B2 event panels use the complete selected endpoint set and expected normal response mass.
- Target Admin1 comes only from the frozen target-IP mapping (`geo_country`, `geo_region`).
- ISP domains, cities and ASGeo path labels cannot become target regions.
- Regional attack controls are same-ASN pre-event matches; covariate balance is exported and gated.
- Attack timing is tied to the frozen primary anchor and is accompanied by anchor-shift sensitivity.
- Prediction is rolling-origin by whole event and accepts only features available before the test event.
- A feature-time audit and label permutation test are mandatory.
- Repeated-outage exposure is exact interval overlap from a separate frozen registry and is rejected when it has no variation.
- A traceroute star, reserved/private hop, AS0 or unknown Geo breaks adjacency.
- Path frequencies are event-specific and normalised per 1,000 valid target-reaching traceroutes.
- External IODA/Cloudflare/NetBlocks observations are used only for independent temporal/spatial concordance, never as training labels.

## New scientific outputs

- `sensor_denominators.parquet` and per-event frozen sensor panels;
- B1/B2 downstream method-sensitivity table;
- same-ASN matching balance before/after matching;
- pretrend equivalence and anchor sensitivity;
- independent third-party temporal and spatial concordance (`Experiment F`);
- rolling-origin leakage audit, repeatability and permutation benchmarks;
- exposure-variation audit and recovery survival;
- quality-gated AS and ASGeo edge distribution changes;
- RED/YELLOW/GREEN closure report.

## Intentionally conditional claims

The software does not force a positive paper result.  A failed B2 calibration is a valid outcome.  In that case, downstream analyses use B1 and the closure status can be `YELLOW_NEGATIVE_CALIBRATION` if the attack validation chain is otherwise complete.  Path adaptation is also optional: failure of the path-quality gate removes the general path claim rather than fabricating an estimate.

## Final hardening review (v2.2)

### Stale-output prevention

The previous resume implementation initialised a new manifest before checking completed stages.  This erased stage history and defeated resume.  The orchestrator now opens an existing manifest only after verifying run id, mode and all frozen hashes; otherwise it refuses the run.  Output files receive content hashes and large directories receive an explicitly labelled inventory hash.

### Prediction integrity

Ridge/GBDT exceptions previously fell back to M3 while retaining the M4/M5 model label.  This could make a failed estimator appear to have excellent performance.  Fallback rows are now labelled `fallback_failed`, performance tables count failures, and closure requires zero primary-model fit failures.  The permutation null now jointly permutes all current-event outcomes within event, preserving their correlation while destroying persistent group identity.

### Path-view confounding

Because every trace originates in Frankfurt, a European source/upstream change can affect many Ukrainian targets.  Experiment E now reports both raw JSD and target-specific JSD after removing edges present in the configured fraction of baseline groups.  It also reports baseline/event target-IP overlap so the random-four-IP-per-/24 design is visible rather than hidden.  These remain sensitivity diagnostics and do not convert aggregate path distributions into paired physical routes.
