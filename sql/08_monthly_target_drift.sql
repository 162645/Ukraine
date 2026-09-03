SELECT
  toStartOfMonth(measure_time) AS month,
  uniqExact(prefix24) AS responding_prefixes
FROM {ping}
WHERE measure_time >= toDateTime64('{start}', 6, 'UTC')
  AND measure_time <= toDateTime64('{end}', 6, 'UTC')
  AND data_center = '{dc}'
GROUP BY month
ORDER BY month
