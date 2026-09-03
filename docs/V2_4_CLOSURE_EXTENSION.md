# v2.4 closure extension: operator contrasts, weather and immutable evidence

## Decision

The next run remains worthwhile, but it is a discriminating experiment rather than a route
to a guaranteed positive result. v2.3 showed no held-out improvement for B2 over B1 and did
not establish predictive fingerprints. The segmented national schedule fixes a real label
error and supplies independent holdout clusters, so one preregistered rerun is justified.
Repeatedly changing thresholds after that result is not justified.

## What is core

1. Frozen national scheduled-outage training and cluster-level holdout validation of B2.
2. Frozen B1/B2 choice before attack outcomes are opened.
3. Attack event studies with admissible pretrends, balance, fake dates/regions and method sensitivity.
4. Whole-event rolling-origin tests of repeatable and predictable ASN×Admin1 effects.
5. Identified recovery-debt and quality-admissible path-adaptation analyses.

The operator contrast strengthens the mechanism but never selects endpoints or thresholds.
Weather controls test confounding but are never treatment labels. Source archiving strengthens
reproducibility but is not an estimand.

## Registered operator contrasts

- Primary: `C2024_0724_ZP_VOL`, 24 July 16:00–18:00 Europe/Kyiv. Zaporizhzhia is the
  commanded execution arm and Volyn is the cancellation arm. Estimate within-ASN,
  prefix-balanced change from the preceding clean cycles. Report common-ASN count, arm sizes,
  standardized baseline differences, pretrend equivalence and the interaction estimate.

The exact Zaporizhzhyaoblenergo update is Telegram message `974`. Message `966`,
which appeared in an earlier supplement, concerns 21 July and must not be cited for
the 24 July contrast.
- Candidate only: `C2024_0706_LVIV_VOL`. Lviv's final cancellation to 18:00 is official;
  the matching Volyn source has not yet passed the same provenance standard. It is disabled.
- Recovery sensitivity: `C2024_0830_VOL_ZP_SUMY`. It is strongly differentiated but follows
  the 26 August attack. It cannot validate clean scheduled-outage calibration.

The primary contrast is only two hours, equal to one nominal measurement cycle. It is therefore
supporting falsification, not an independent foundation for the paper. If the cycle misses the
window, common-ASN support is below the frozen minimum, or pretrends fail, report
`not_estimable`; do not widen the window post hoc.

## Weather sensitivity contract

Create `data_derived/weather_admin1_2h.parquet` with UTC `measure_time`, canonical `admin1`,
`t2m_mean_c`, `previous_24h_max_c`, `temperature_anomaly_c`, and
`official_heat_warning`. Aggregate area-weighted ERA5-Land grid cells to Admin1 polygons, then
align to the same two-hour measurement bins. Freeze polygon version, CDS request, raw-file hashes,
area-weighting rule and anomaly reference period.

Primary calibration remains unadjusted because the national schedule is the weak label. Report
three prespecified sensitivity checks: temperature-adjusted event model, heat/non-heat strata,
and exclusion of the 19–21 August heat cluster. A positive calibration chain is not publication
ready if it disappears under all three. A null result is not rescued by weather adjustment.

## Outcomes and stopping rule

- Positive calibration plus attack replication, repeatability/prediction, recovery and path gates:
  positive mechanistic chain.
- Valid negative calibration with adequate labels and attack estimability: publishable limitation—
  national schedule labels cannot calibrate transportable IP sensors at this resolution.
- Operator contrast is null but adequately powered: evidence against the power-sensitivity mechanism.
- Operator contrast is not estimable: no mechanism claim; retain as a documented data limitation.
- Failed provenance, missing weather sensitivity for a positive chain, failed pretrends, or too few
  independent holdouts: incomplete evidence, not a scientific null.

After this frozen run, stop unless a genuinely new evidence level becomes available, such as
address/queue-to-IP linkage, measured feeder outages, or additional independent seasons. More
threshold tuning or adding adjacent dates from the same heat episode does not add independence.
