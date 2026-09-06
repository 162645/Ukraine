-- Stable endpoint pool from complete, non-event measurement cycles only.
SELECT
  dst_ip,
  prefix24,
  uniq(intDiv(toUnixTimestamp(measure_time), {cycle_seconds})) AS x_normal
FROM {ping}
WHERE data_center = '{dc}'
  AND prefix24 IN ({prefix_in})
  AND intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({normal_cids})
GROUP BY dst_ip, prefix24
