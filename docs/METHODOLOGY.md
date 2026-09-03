# Frozen methodological decisions

## 1. Research estimand

The primary outcome is equal-weight `/24` reachability among a frozen endpoint sensor set, normalised by the sum of each selected endpoint's expected normal response probability for the same day-of-week and two-hour slot.

The measurement view is explicitly `AWS Frankfurt -> Ukrainian target IP`. It is not a measure of reverse paths, Ukraine-internal traffic, users, households or physical damage.

## 2. Event truth and labels

Event times, affected regions, outage type and third-party observations are frozen independently of self-measured results. Scheduled outages are weak labels. National announcements are not assumed to identify which individual feeder, building or endpoint actually lost power.

Separate fields are maintained for attack start, outage start, self-measured anomaly onset, external anomaly onset and recovery. Anchor uncertainty is tested rather than concealed.

## 3. Experiment A: endpoint calibration

- **B0:** all endpoints in the valid frozen target universe; diagnostic only.
- **B1:** historically stable endpoints satisfying baseline exposure and response thresholds.
- **B2:** B1 endpoints whose posterior lower bound supports a positive normal-minus-planned response difference.

Training and validation are split by whole scheduled-outage event.  Validation positives are only registered outage cycles.  Negative controls are complete clean cycles from the same day-of-week × two-hour slot, strictly before the held-out event; post-outage recovery is never labelled as normal. Success requires held-out B2 AUPRC to exceed B1 under an event × Admin1 block bootstrap whose lower confidence limit is above zero, enough B2 endpoints, at least the frozen number of validation events, and a positive B2-minus-B1 gain in the preregistered fraction of held-out events.

If calibration fails, the code does not tune B2 on attacks. B1 becomes the primary downstream method, and a negative-calibration conclusion remains possible.

## 4. Frozen sensor panels

For B1 and B2, the denominator is the complete selected endpoint set for each prefix. The numerator contains observed responders. A complete cycle with no response contributes zero. Expected normal responders are `sum(pN)` rather than the number of rows that happened to respond.

This is the central correction to response-only bias.

## 5. Experiment B: held-out attacks

Regional attacks use exact same-ASN control prefixes from unaffected Admin1 regions, matched only on pre-event reach, variability, expected sensor mass and RTT. Covariate balance is reported before and after matching. Cross-ASN fallback is disabled in the primary design.

National attacks use prefix-centred historical same-slot baselines and placebo dates because no untreated Ukrainian region is credible.

Reported outcomes are dynamic event-study effects, pretrend-equivalence diagnostics, anchor sensitivity, immediate drop, maximum deficit, deficit AUC, time to recovery and right-censoring. The Sumy event remains blind until all rules are frozen.

## 6. Experiment F: independent external concordance

Frozen third-party network observations are not labels for endpoint selection and are not predictors. After self-measured results are complete, the code compares internal versus external anomaly onset and the overlap of anomalous first-level administrative regions. Different platforms are expected to differ in magnitude because they observe different populations.

## 7. Experiment C: repeatability and prospective prediction

A resilience group is `target ASN × target country × target Admin1`. Repeatability is estimated only for groups shared across events. Prediction is chronological rolling origin with the test event held out as a whole.

Allowed predictors are identity, baseline characteristics and lagged outcomes from events strictly before the test anchor. Current-event outcomes, current-event paths and globally constructed post-event features are forbidden. A feature-time audit and joint within-event outcome-vector permutation benchmark are mandatory. If an ML estimator fails, any emitted baseline fallback is explicitly marked and cannot be credited to the primary model.

A predictive fingerprint claim requires the primary model to improve on the frozen simple baseline by the configured event-equal margin, pass permutation testing, and be accompanied by positive cross-event repeatability.

## 8. Experiment D: accumulated exposure and recovery debt

Exposure is exact interval overlap between each pre-event lookback window and frozen scheduled/emergency outage intervals. National intervals apply to all groups; regional intervals apply only to listed canonical Admin1 regions. A model is not estimated when the exposure lacks variation. Event fixed effects are primary only where exposure varies within event.

Results support an association with recovery debt, not proof of battery ageing, fuel exhaustion or a specific physical mechanism.

## 9. Experiment E: conditional path adaptation

ASGeo means `ASN + country + first-level administrative region` for every hop worldwide. Ukrainian hops usually map to an oblast; foreign hops map to their own country/Admin1.

The path estimand is a distribution change in high-confidence adjacent AS or ASGeo edges among traceroutes that reach the target. A star, reserved/private address, AS0, unknown country or unknown Admin1 breaks adjacency. Nodes separated by a gap are not direct neighbours.

The primary unit is an admitted ASN × target-Admin1 group over six-hour windows. Frequencies are normalised by valid traceroutes; raw counts are never compared across phases. Two sensitivity diagnostics address the single-Frankfurt/random-target design: (1) target-specific JSD removes baseline edges ubiquitous across a frozen fraction of target groups, and (2) baseline-event overlap in target IPs is reported for every group. The overlap statistic does not turn the aggregate analysis into a paired path experiment. Path findings are conditional on survival and on the Frankfurt source view. Failing quality gates downgrades this experiment to diagnostics or selected cases.

## 10. Inference and multiplicity

- equal-/24 and event-equal estimands are primary;
- clustering/block resampling respects `/24`, region and event dependence;
- effect sizes and uncertainty are reported, not p-values alone;
- placebo dates, false treated regions, anchor shifts and threshold sensitivity are required;
- no millions-of-IP pseudo-replication is used as the scientific sample size.
