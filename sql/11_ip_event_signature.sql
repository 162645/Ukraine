-- Per-IP response counts for one geographically scoped scheduled-outage day.
-- Prefixes are batched by the caller and exact regional IP membership is
-- applied after the aggregation. Missing rows mean non-response under the
-- audited static full-scan denominator contract.
SELECT
  dst_ip,
  prefix24,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({normal_cids})) AS x_normal,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({pre_cids})) AS x_pre,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({outage_cids})) AS x_outage,
  uniqIf(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}),
         intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({post_cids})) AS x_post
FROM {ping}
WHERE data_center = '{dc}'
  AND prefix24 IN ({prefix_in})
  AND intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) IN ({all_cids})
GROUP BY dst_ip, prefix24
