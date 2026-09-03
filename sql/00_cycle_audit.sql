-- Analysis cycles are defined by UTC floor to the configured 2-hour interval.
WITH
ping_agg AS (
  SELECT
    intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
    toDateTime(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) * {cycle_seconds}, 'UTC') AS measure_time,
    count() AS ping_rows,
    uniqExact(prefix24) AS ping_prefixes,
    uniqExact(dst_ip) AS ping_unique_ips
  FROM {ping}
  WHERE measure_time >= toDateTime64('{start}', 6, 'UTC')
    AND measure_time <= toDateTime64('{end}', 6, 'UTC')
    AND data_center = '{dc}'
  GROUP BY cycle_id, measure_time
),
trace_agg AS (
  SELECT
    intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
    count() AS trace_rows,
    uniqExact(prefix24) AS trace_prefixes,
    avg(reached_target) AS trace_reached_rate,
    sum(star_hop_count) / greatest(sum(hop_count), 1) AS trace_star_rate,
    avg(positionCaseInsensitive(as_path_text, 'AS0') > 0) AS as0_path_share,
    avg(positionCaseInsensitive(asgeo_path_text, 'UNKNOWN') > 0 OR positionCaseInsensitive(asgeo_path_text, '未知') > 0) AS geo_unknown_path_share
  FROM {trace}
  WHERE measure_time >= toDateTime64('{start}', 6, 'UTC')
    AND measure_time <= toDateTime64('{end}', 6, 'UTC')
    AND data_center = '{dc}'
  GROUP BY cycle_id
)
SELECT p.cycle_id, p.measure_time, p.ping_rows, p.ping_prefixes, p.ping_unique_ips,
       ifNull(t.trace_rows, 0) AS trace_rows,
       ifNull(t.trace_prefixes, 0) AS trace_prefixes,
       t.trace_reached_rate, t.trace_star_rate, t.as0_path_share, t.geo_unknown_path_share
FROM ping_agg p
LEFT JOIN trace_agg t USING cycle_id
ORDER BY measure_time
