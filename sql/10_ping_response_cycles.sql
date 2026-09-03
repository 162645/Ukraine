-- Responses for a small, frozen set of analysis cycles and /24 prefixes.
-- Used by held-out scheduled-outage calibration so control cycles are matched
-- on day-of-week × two-hour slot rather than drawn from a contaminated post-event window.
SELECT
  intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
  dst_ip,
  prefix24,
  quantileExact(0.5)(rtt_ms) AS rtt_ms
FROM {ping}
WHERE data_center = '{dc}'
  AND prefix24 IN ({prefix_in})
  AND intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({cycle_ids})
GROUP BY cycle_id, dst_ip, prefix24
ORDER BY cycle_id
