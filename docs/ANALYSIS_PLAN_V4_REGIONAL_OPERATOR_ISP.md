# Analysis plan v4: regional power-operator exposure and network-stratified sensors

## 1. Primary questions

1. Do local scheduled or executed power-restriction windows produce a contemporaneous
   reduction in network reachability inside the named Admin1 or power-operator service area?
2. Can endpoints selected only from earlier, independent outage episodes improve detection
   of a held-out outage episode relative to the historically stable B1 endpoint panel?
3. Does the signal remain after controlling for the same ISP/ASN outside the treated Admin1,
   cancelled/no-restriction windows, attack recovery, weather, and technical outages?

The endpoint claim is limited to **network-visible outage-responsive endpoints**.  IP
geolocation, even when a city and coordinates are present, is not address-, feeder-, or
queue-level power truth.

## 2. Frozen source and deterministic import

- Evidence source: `Ukraine_power_schedule_research_ready_v4_0.xlsx`.
- Analysis sheet: `schedule_verified_merged_v40`.
- Frozen export: `config/planned_outage_schedule_v4_0.csv`.
- Import command: `python scripts/import_v4_schedule.py --input <workbook>`.
- Source rows are retained. Rows with missing/non-positive planned intervals receive
  `interval_valid=0`, `analysis_eligible=0`, and never enter effect estimation.

Positive labels require `restriction_type=hourly_schedule`. Cancelled windows and
`no_restriction` rows are negative controls. Actual start/end times replace planned times
only when both actual timestamps are present and form a positive interval.

## 3. Spatial exposure hierarchy

1. `L1`: reserved for a future verified IP-to-address/queue or IP-to-feeder mapping.
2. `L2_admin2_named_ip_city_unresolved`: an Admin2/service area is named, but the IP city
   cannot yet be proven to lie inside that service area.
3. `L2_operator_admin1_proxy`: the DSO service area is represented by its Admin1.
4. `L2_admin1`: the schedule explicitly covers an Admin1.
5. `L3_national`: national context only; excluded from regional sensor discovery.

Target IP mapping retains canonical Admin1, raw city, city-centroid coordinates, ASN,
AS name, ISP domain, and `network_stratum = isp_domain` with ASN fallback.  Country-only
and unknown-Admin1 targets are excluded from regional inference.

## 4. Independent episode contract

Rows are grouped within `Admin1 x power operator x positive/negative class`. Consecutive
dates, or dates separated by no more than three days, form one episode. A new independent
episode begins only after a gap greater than three days. Train/holdout splits operate on
the complete episode, never on individual rows or dates.

## 5. Sensor construction and validation

- B0: every observed target endpoint.
- B1: normal-period posterior response probability at least 0.8 with the configured
  exposure support.
- B2-region/operator: B1 endpoints with positive posterior sensitivity in at least three
  independent training episodes, a positive-episode fraction of at least two thirds, and
  positive median sensitivity.

For endpoint `i` and episode `e`:

`S(i,e) = posterior response probability in matched normal cycles - posterior response probability in exposed cycles`.

Normal cycles are earlier clean cycles matched on day-of-week x two-hour slot. A cycle is
exposed only when at least 50% overlaps a valid restriction interval after the registered
transition buffer.

Validation uses leave-one-episode-out cross-fitting. The held-out episode does not affect
membership or thresholds. The primary comparison is held-out `AUPRC(B2-region/operator)
- AUPRC(B1)`. The equal-region bootstrap prevents a large Admin1 from dominating.

The publication-facing regional gate requires:

- at least three estimable held-out episodes;
- at least 200 unique regional B2 endpoints;
- at least two thirds of held-out episodes with positive B2-minus-B1 improvement;
- a positive lower 95% bootstrap bound for equal-region mean improvement.

If the gate fails, B1 remains primary downstream. B2 results remain diagnostic and are not
used to rescue later outcomes.

## 6. ISP/ASN control

The ClickHouse ISP/ASN is a network operator, not the DSO in the outage registry. It is a
control stratum. For every treated episode the pipeline reports whether the same network
stratum has at least 100 endpoints outside the treated Admin1. The confirmatory spatial
contrast matches within ASN; ISP-domain matching is added when both arms have sufficient
support. A contemporaneous nationwide drop within one ISP/ASN is a network confound, not
evidence of a local power effect.

## 7. A-H roles

- Experiment A: nationwide scheduled-outage calibration benchmark only.
- Experiment H: primary Admin1/power-operator episode calibration and cross-fitting.
- Experiment G: same-window spatial falsification using affected versus cancelled or
  unaffected Admin1 controls within the same network stratum.
- Experiment B: held-out attack/power effects using the frozen primary sensor method.
- Experiment C: repeatability and rolling-origin prediction by whole event.
- Experiment F: external temporal/spatial concordance.
- Experiment D: accumulated exposure and recovery debt, only when within-event exposure
  variation is identifiable.
- Experiment E: conditional AS/ASGeo forwarding adaptation; mechanism diagnostic only.

## 8. Interpretation states

1. Regional group effect and held-out B2 improvement both pass: evidence supports a
   calibrated panel of network-visible power-sensitive endpoints.
2. Regional group effect passes but B2 does not improve over B1: outages are observable,
   but a special endpoint subset is not reproducibly identified.
3. Regional group effect fails: current exposure labels, spatial resolution, or measurement
   cadence cannot support calibration.

Positive results are not required for scientific closure. Missing independent episodes,
failed pretrends, label leakage, or absent same-network controls are incomplete evidence,
not negative causal findings.

## 9. Resource and reproducibility controls

All ClickHouse queries inherit the configured 32 GiB ceiling, use at most 75% as per-query
memory, allow external aggregation/sort spill, and use bounded prefix batches. Python writes
partitioned Parquet artifacts and never materializes the full 8.3-billion-row ping table.
Every stage is checkpointed under one run ID and can be resumed without recomputing finished
stages.
