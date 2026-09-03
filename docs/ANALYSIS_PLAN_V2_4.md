# Analysis plan v2.4

## 1. Fixed scientific question

Can scheduled-outage records weakly supervise a power-sensitive endpoint set; can that frozen set quantify held-out wartime energy attacks; and do ASN×Admin1 effects form repeatable and prospectively predictable resilience characteristics?

## 2. Evidence layers

1. Event registry: physical attack, outage implementation, affected regions, recovery, uncertainty and confounds.
2. Active Ping: endpoint and /24 response from Frankfurt.
3. Traceroute: target reachability and conditionally observed direct AS/ASGeo relations.
4. Third-party network evidence: temporal/spatial replication only, never sensor training or confirmatory treatment assignment.

## 3. Event-stage design

Each event has up to three clocks:

- `attack_start_utc`: earliest credible physical treatment boundary;
- `outage_start_utc`: power-exposure anchor;
- `network_anomaly_start_utc`: external network-observation anchor.

The clean baseline ends `clean_baseline_buffer_h` before the earliest of these times. The interval from earliest treatment to the estimand anchor is explicitly labelled `transition` and excluded from pretrend equivalence.

### Estimands

- `confirmatory_power`: power-affected geography, anchored at outage start or attack start when outage start is unavailable.
- `attack_onset`: descriptive transition estimate.
- `network_replication`: external network-observed geography, anchored at external anomaly start; non-causal.

## 4. Target universes

- U1: all destinations ever responding in the original task table;
- U2: target mapping confirms Ukraine and valid ASN;
- U3: U2 plus valid Ukrainian Admin1.

National analyses use U2. Regional and fingerprint analyses use U3. U1/U2/U3 counts are always reported so Geo filtering cannot remain hidden.

## 5. Experiment A — scheduled-outage weak supervision

B0 contains all observed candidate endpoints. B1 contains historically stable endpoints. B2 is the B1 subset with a positive posterior lower bound for normal response probability minus planned-outage response probability.

Training and validation are separated by complete outage event. Negative validation cycles are clean pre-event, same day-of-week×2-hour-slot controls. Recovery cycles are never negative controls.

### Registered segmented schedules

The primary weak label is now the final-version Ukrenergo queue schedule, stored as non-overlapping Europe/Kyiv and UTC segments. A two-hour measurement cycle is positive only when at least 50% of the cycle overlaps a segment with `queue_count>0`; a zero-queue gap inside the same day is never filled by the event's bounding interval. Queue count is retained for a preregistered dose-response diagnostic.

Nominal dates are not independent replicates. Validation evidence is clustered into independently registered weather/recovery episodes. Consecutive 19–21 August schedules form one `august_heat` cluster. Publication closure requires at least two eligible validation clusters, not merely two dates. The 9 December schedule is retained as winter/post-attack-recovery transport validation but is excluded from the clean publication-cluster count.

### Positive publication gate

- full PR curve;
- B2 sensor count above threshold;
- bootstrap lower bound of ΔAUPRC(B2−B1) > 0;
- all required independent holdout events positive;
- at least two estimable, publication-eligible validation clusters;
- configured normal exposure support is met.

If the gate fails, B1 is frozen before attacks are opened. The negative claim is limited to the available weak-label quality.

### Auxiliary operator-level falsification and weather sensitivity

The frozen operator registry supplies a same-window Admin1 contrast that is never used to select
B2. The primary contrast is 24 July 16:00–18:00 Europe/Kyiv: Zaporizhzhia commanded execution
versus Volyn cancellation. It requires exact-window support, within-ASN overlap, balance and
pretrend equivalence. The 30 August contrast is recovery-confounded and sensitivity-only; the
6 July contrast remains disabled until both official arms are archived and verified.

ERA5-Land Admin1×2-hour temperature and the official 8–15 July heat episode are confound controls,
not treatments. Positive calibration must survive temperature adjustment, heat-cluster exclusion,
and heat/non-heat stratification. See `V2_4_CLOSURE_EXTENSION.md`.

## 6. Experiment B — held-out attack effects

### National attacks

Each /24 unit is centered against its clean same-slot baseline. No fictitious unaffected region is introduced.

### Regional attacks

Treated and control /24×ASN×Admin1 units are matched within ASN using clean-baseline level, variability, expected responding endpoints, and RTT. The event curve is pair-centered DID:

`(treated_t − control_t) − mean_clean_baseline(treated − control)`.

### Inference gate

- sufficient matched pairs and covariate balance;
- practical equivalence of clean-pre level and slope;
- complete confidence intervals and effect metrics;
- regional fake-treatment and national fake-date placebos;
- anchor sensitivity and B1/B2 method sensitivity.

11 November 28 is estimated twice: power geography for the confirmatory question, external network geography for replication.

## 7. External validation

Internal spatial detections require consecutive negative cycles and BH-FDR correction. Results include Jaccard, top-k Jaccard, precision, recall and false-positive rate. The external region set never feeds the confirmatory power estimator.

## 8. Experiment C — repeatability and prediction

Only group-event rows that were actually treated enter resilience repeatability. Pairwise Spearman rho includes bootstrap confidence intervals. The group ICC must be positive.

Prediction is rolling-origin by whole event. Every feature must precede the test event. M4 Ridge is confirmatory; M5 GBDT is exploratory. Success requires at least three held-out events, no leakage, no fit failure, event-wise improvement over M3, aggregate MAE improvement and a permutation result.

A valid null is a result when the model was estimable.

## 9. Experiment D — recovery debt

Official outage exposure is computed as exact interval overlap over 72, 168 and 720 hours. `pre_event_debt` is a separate observable network state, not a substitute for official power exposure. Models include event and group controls with group-clustered uncertainty. If the preregistered exposure lacks within-event variation, the output is explicitly not identified.

## 10. Experiment E — AS/ASGeo adaptation

The analysis is conditional on `reached_target=1`. Direct edges require adjacent observed public hops, nonzero ASN and known country/Admin1. Source-common baseline edges can be removed for target-specific JSD. Target overlap is reported. BH-FDR is applied across admissible tests.

Claims are limited to observed forwarding-relation distributions from Frankfurt, not complete BGP paths or physical links.

## 11. Figures

Main figures use one- or two-column dimensions, vector PDF/SVG, 600-dpi PNG, embedded/source-preserved fonts, color plus line/marker redundancy, common y axes where comparison requires it, source-table hashes and alt text. Chinese and English versions are generated from identical source tables.

## 12. Stopping rule

The study is scientifically closed only when the core questions are estimable. Positive answers are not required. Missing independent holdouts, contaminated pre-periods or leakage are incomplete evidence, not negative findings.
