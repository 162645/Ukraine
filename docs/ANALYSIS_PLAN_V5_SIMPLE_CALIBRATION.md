# Analysis plan v5: state-level continuous outage sensitivity

## Research question

Can state-level scheduled outages estimate continuous IP-level reachability and
RTT sensitivity, and do those frozen sensitivities describe within-state
network loss and recovery during independent energy attacks?

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
The formal workbook supplies the frozen `episode_id` and `window_id`. A
`window_id` is the exact planned-outage observation window; an `episode_id` is
the independent evidence unit. Multiple windows may belong to one episode.
The code never rebuilds episode identities from Admin1, civil date, date
continuity, or a 36-hour heuristic.

Actual execution intervals replace planned intervals only when both actual start
and actual end are available and ordered. Cancelled and national rows do not
calibrate endpoints.

## Frozen continuous IP sensitivity

For endpoint i and scheduled-outage event e:

- `S_reach(i,e) = reach(normal matched cycles) - reach(outage cycles)`
- `S_rtt(i,e) = (RTT(outage cycles) - RTT(normal matched cycles)) / RTT(normal matched cycles)`

For each independent episode, all valid outage cycles from its frozen windows
are first unioned, and normal cycles are matched once to that union. Normal
cycles are complete, non-outage
cycles from the same weekday-by-two-hour slot. An IP contributes when it has
adequate normal and outage cycles. Activity is a continuous covariate; the
legacy 0.8 response-rate rule is diagnostic only and does not exclude low-
Activity IPs. No positive drop, recovery, or RTT threshold turns an IP into a
binary power label. The
primary transition buffer is 30 minutes.

Explicit state-level no-outage intervals in the same daily schedule are retained
as a second, within-day contrast (`S_reach_explicit_clear` and
`S_rtt_explicit_clear`). They do not replace the weekday-slot primary control.
Clear gaps between windows are not filled. A multi-window episode is scored
once by pooling its cycle IDs; its episode-level score receives one weight in
the final episode-equal mean.

For each IP, the episode-specific sensitivities are averaged across frozen
independent episodes. `S_reach` and `S_rtt` remain separate; RTT is evaluated
only for responsive observations. Frozen low/middle/high strata are calculated
within each state solely for attack-time presentation.

## Activity-supported comparison pool

The primary population is every region-mapped endpoint with at least the
configured clean-normal-cycle support. The raw Activity score is retained for
all such endpoints; B1 is only a legacy diagnostic alias and never gates the
canonical IPS/FBS or planned-outage sensitivity population.

## Independent application

After calibration, the sensitivity table and state strata are frozen. Registered
attacks, emergency outages, and recovery observations cannot alter scores,
strata, or calibration windows. For each attack's independently registered
affected state, the primary descriptive validation compares high and low
`S_reach`/`S_rtt` strata on reachability deficit, cumulative deficit, recovery,
and conditional RTT change. Cross-state summaries follow those within-state
comparisons and never redefine the state treatment geography.
The companion continuous analysis estimates, inside each affected state, the
slope between frozen `S_i` and each attack-period outcome rather than relying
only on low/middle/high strata. Recovery is time to the first consecutive
complete cycles at or above 90 percent of the same-slot clean baseline; units
not recovering in the observation window are right-censored.

## Falsification and claim boundary

Normal same-slot cycles bound ordinary endpoint instability. Cancelled schedules,
time-shifted windows, and same-network outside-region behavior are required
diagnostics as data support permits. Network-wide ISP/ASN failures cannot be
interpreted as electricity effects.

The sensitivity table describes network-visible planned-outage association, not
IP-level physical power ground truth.
