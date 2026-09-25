SELECT
  hop.1 AS ip,
  min(measure_time) AS first_seen,
  max(measure_time) AS last_seen,
  count() AS observed_response_n,
  countIf(hop_position < path_length AND hop.1 != dst_ip) AS intermediate_observation_n,
  countIf(hop_position = path_length AND hop.1 != dst_ip) AS terminal_non_target_observation_n,
  countIf(hop.1 = dst_ip) AS target_address_observation_n,
  min(hop_position) AS hop_position_min,
  max(hop_position) AS hop_position_max
FROM
(
  SELECT measure_time, dst_ip, hop_path, length(hop_path) AS path_length
  FROM `UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22`
  WHERE measure_time >= toDateTime64('{MONTH_START_UTC}', 6, 'UTC')
    AND measure_time < toDateTime64('{NEXT_MONTH_START_UTC}', 6, 'UTC')
)
ARRAY JOIN hop_path AS hop, arrayEnumerate(hop_path) AS hop_position
WHERE hop.1 != '*'
  AND IPv4StringToNumOrNull(hop.1) IS NOT NULL
GROUP BY ip
HAVING intermediate_observation_n > 0
    OR terminal_non_target_observation_n > 0
ORDER BY ip
SETTINGS
  max_threads = 6,
  max_memory_usage = 6442450944,
  max_bytes_before_external_group_by = 1073741824
FORMAT CSVWithNames
