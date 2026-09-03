SELECT
  intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
  dst_ip,
  prefix24,
  quantileExact(0.5)(rtt_ms) AS rtt_ms
FROM {ping}
WHERE data_center = '{dc}'
  AND measure_time >= toDateTime64('{start}', 6, 'UTC')
  AND measure_time < toDateTime64('{end}', 6, 'UTC')
  AND prefix24 IN ({prefix_in})
GROUP BY cycle_id, dst_ip, prefix24
ORDER BY cycle_id
