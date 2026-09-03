# Planned-outage evidence audit and paper decision

## Decision

The new evidence is worth using because it directly strengthens the weakest link in the paper: scheduled-outage calibration. It does not change the paper topic. It changes Experiment A from a one-train/one-holdout binary design into a multi-date, segmented, dose-aware weak-supervision design with episode-level replication.

It still cannot guarantee a positive result. Its value is that a second negative calibration would now be much harder to dismiss as a single-event accident. Conversely, a positive B2 result must replicate across independent summer episodes and survive a winter/post-attack transport test.

## Source audit

Accepted primary sources are posts on the official Ukrenergo Telegram channel. The frozen schedule contains the final version found during the audit, not a media paraphrase. The following were directly verified:

| Date | Verified final local schedule | Role | Source |
|---|---|---|---|
| 7 Jul | 00:00–07:00 q2; 07:00–15:00 q0; 15:00–24:00 q2 | training | https://t.me/s/Ukrenergo/3012 |
| 20 Jul | 00:00–02:00 q1; 02:00–05:00 q0; 05:00–13:00 q1; 13:00–24:00 q2 | training/dose | https://t.me/s/ukrenergo?before=3074 |
| 28 Jul | 00:00–18:00 q0; 18:00–22:00 q1; 22:00–24:00 q0 | clean holdout | https://t.me/s/Ukrenergo?before=3125 |
| 19 Aug | 00:00–17:00 q0; 17:00–21:00 q1; 21:00–24:00 q0 | holdout | https://t.me/s/Ukrenergo?before=3184 |
| 20 Aug | 00:00–16:00 q0; 16:00–17:00 q1; 17:00–22:00 q2; 22:00–24:00 q1 | dose robustness | https://t.me/s/Ukrenergo?before=3202 |
| 21 Aug | final update: 00:00–15:30 q0; 15:30–18:00 q1; 18:00–22:00 q2; 22:00–24:00 q1 | update robustness | https://t.me/s/Ukrenergo?after=3186 |
| 9 Dec | 08:00–19:00 q1 | winter transport only | https://t.me/s/ukrenergo?before=3546 |

All July/August local times are EEST (UTC+3); 9 December is EET (UTC+2). The canonical machine-readable values are in `config/planned_outage_schedule_v1.csv`.

The 25 July, 7 December, 11 December regional exception, and 12 December update claims from the supplied text were not promoted into the frozen primary registry in this revision. Some are plausible and portions can be found in official archives, but the supplied material did not provide a stable final-version URL plus complete update history sufficient for the same provenance standard. They remain candidates for a later source appendix, not labels used to decide B2.

## Independence and confounding

- A date is not automatically an independent experiment.
- 19–21 August are one heat/demand episode and count as one validation cluster.
- 28 July is a separate short-window replication cluster.
- 9 December explicitly followed the 28 November energy attack and is excluded from the clean publication count.
- Queue schedules are national dispatch intensity, not actual IP-level disconnection truth.
- Heat is a confounder for both power demand and network/device behavior. Weather indicators should be included in event-level sensitivity, but must not be selected after seeing B2 performance.

## Revised core paper chain

1. Verify acquisition denominator and frozen IP mapping.
2. Train B2 only on registered July training schedules and clean pre-holdout normal cycles.
3. Freeze endpoint scores and thresholds before 28 July.
4. Validate by full date and by independence cluster; bootstrap at cluster×Admin1, not date×Admin1.
5. Test whether response deficit increases with registered queue count. Treat this as mechanism support, not IP-level causal dosage.
6. Freeze B2 only if it beats B1 under the preregistered gate; otherwise freeze B1 and report calibration failure.
7. Open held-out attacks only after freezing the sensor method.
8. Require admissible attack pretrends/placebos, whole-event prospective prediction, identified recovery models, and quality-admissible path adaptation before green closure.

## What existing results imply

The v2.3 result B2−B1 = −0.0703 remains a serious warning. It means the next run should not be framed as an attempt to obtain significance. The new schedules answer the scientifically legitimate question of whether the old failure was caused by a single coarse training/validation pair. If B2 again fails across two eligible clusters, the strongest paper is a boundary-condition/negative-result paper: national outage schedules are too coarse to calibrate IP-level power sensors, even though stable endpoints can still describe some attack-period network anomalies.

If B2 succeeds across clusters, the paper gains a much stronger mechanism chain: registered schedule intensity → reproducible endpoint sensitivity → frozen-sensor attack response. The attack, recovery and path sections still require their own gates; calibration success alone is not a full paper closure.

## Remaining evidence needed

1. A state/queue-level L1 or L2 schedule-to-location mapping would materially strengthen physical interpretation. National q1/q2 remains L3 weak supervision.
2. Weather covariates or, at minimum, temperature-wave episode indicators are needed for July/August sensitivity.
3. Actual implementation/cancellation records from at least one oblast would permit a regional falsification test.
4. The current Python environment still needs `statsmodels` before the real run; otherwise recovery debt and variance decomposition cannot close.
