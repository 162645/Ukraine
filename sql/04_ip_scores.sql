-- Endpoint response counts in prospectively selected, slot-matched training cycles.
SELECT
  dst_ip,
  prefix24,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({normal_cids})) AS x_normal,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({planned_cids})) AS x_planned
FROM {ping}
WHERE data_center = '{dc}'
  AND prefix24 IN ({prefix_in})
  AND intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({all_cids})
GROUP BY dst_ip, prefix24
