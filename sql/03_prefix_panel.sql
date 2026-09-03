SELECT
  prefix24,
  intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
  toDateTime(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) * {cycle_seconds}, 'UTC') AS measure_time,
  ((toDayOfWeek(measure_time) - 1) * {slots_per_day} + intDiv(toHour(measure_time), {cycle_hours})) AS slot,
  count() AS observed_rows,
  uniq(dst_ip) AS observed_ip_n,
  quantileTDigest(0.5)(rtt_ms) AS rtt_median,
  count(rtt_ms) AS rtt_n
FROM {ping}
WHERE measure_time >= toDateTime64('{batch_start}', 6, 'UTC')
  AND measure_time < toDateTime64('{batch_end}', 6, 'UTC')
  AND data_center = '{dc}'
GROUP BY prefix24, cycle_id, measure_time, slot
ORDER BY cycle_id, prefix24
