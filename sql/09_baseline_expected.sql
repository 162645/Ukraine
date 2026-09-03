-- Zero-inclusive historical same-DOW/same-2h-slot expectation.
-- `baseline_slot_cycles` is supplied by the complete-cycle grid, so cycles with no
-- response for a prefix remain in the denominator.
WITH per_cycle AS (
  SELECT
    prefix24,
    intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
    ((toDayOfWeek(measure_time) - 1) * {slots_per_day} + intDiv(toHour(measure_time), {cycle_hours})) AS slot,
    uniqExact(dst_ip) AS observed_ip_n,
    quantileTDigest(0.5)(rtt_ms) AS cycle_rtt_median
  FROM {ping}
  WHERE data_center = '{dc}'
    AND intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({clean_cids})
  GROUP BY prefix24, cycle_id, slot
)
SELECT
  prefix24,
  slot,
  sum(observed_ip_n) AS observed_ip_sum,
  uniqExact(cycle_id) AS responding_cycles,
  quantileTDigest(0.5)(cycle_rtt_median) AS baseline_rtt_median
FROM per_cycle
GROUP BY prefix24, slot
ORDER BY prefix24, slot
