# Analysis plan v5: simple regional scheduled-outage calibration

## Research question

Can regional scheduled outages calibrate IP endpoints that are unusually
responsive to power interruptions, and do those frozen endpoints improve
observation of independent unplanned energy shocks and recovery?

## Calibration population

The candidate population contains actively measured Ukrainian endpoints with a
valid Admin1 mapping and sufficient acquisition support. City matching is used
only when both schedule and endpoint city labels are directly compatible;
otherwise the analysis falls back to Admin1. National schedule rows are excluded.

Power-operator and queue labels are event metadata. They never assign an IP to a
power company or queue. ISP and ASN identify network strata only.

## Scheduled-outage event

Eligible positive schedule rows must have valid time intervals, publication
eligibility, no registered attack/weather/technical confound, an explicit
regional geography, and overlap with complete active-measurement cycles.
Rows for the same Admin1 and civil date form one calibration event; their exact
intervals are unioned when measurement cycles are labelled.

Actual execution intervals replace planned intervals only when both actual start
and actual end are available and ordered. Cancelled and national rows do not
calibrate endpoints.

## Frozen endpoint rule

For endpoint i and scheduled-outage event e:

- `drop = pre_reach - outage_reach`
- `recovery = post_reach - outage_reach`
- `signature = min(drop, recovery)`

An event candidate must have adequate complete cycles, stable historical and
pre-event reachability, a drop of at least 0.5, recovery of at least 0.5, and
historical non-response no greater than 0.2. The primary transition buffer is
30 minutes. These values are frozen before the real run.

One eligible event can calibrate a candidate endpoint. Repeated supporting
events are reported as stronger evidence but are not required for entry.

## Stable comparison pool

B1 is estimated only from complete cycles outside registered regional scheduled
outages and registered energy events. No scheduled-outage outcome contributes to
B1 membership. B2 is the subset of B1 present in the frozen calibrated-sensor
registry.

## Independent application

After calibration, B2 membership is frozen. Registered attack, emergency-outage,
and recovery events cannot alter membership or thresholds. The primary
application estimand is the event-equal difference in deficit AUC between B2 and
B1. Maximum deficit and recovery timing are secondary outcomes.

## Falsification and claim boundary

Normal same-slot cycles bound ordinary endpoint instability. Cancelled schedules,
time-shifted windows, and same-network outside-region behavior are required
diagnostics as data support permits. Network-wide ISP/ASN failures cannot be
interpreted as electricity effects.

The calibrated set is described as network-visible scheduled-outage-responsive
candidate sensors. It is not IP-level physical power ground truth.
