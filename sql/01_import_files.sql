SELECT
  intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) AS cycle_id,
  toDateTime(intDiv(toUnixTimestamp(measure_time), {cycle_seconds}) * {cycle_seconds}, 'UTC') AS measure_time,
  argMax(import_status, updated_at) AS import_status,
  argMax(error_message, updated_at) AS error_message,
  max(has_ping) AS has_ping,
  max(has_trace) AS has_trace,
  sum(ping_rows) AS imported_ping_rows,
  sum(trace_rows) AS imported_trace_rows,
  max(updated_at) AS import_updated_at
FROM {import_files}
WHERE measure_time >= toDateTime64('{start}', 6, 'UTC')
  AND measure_time <= toDateTime64('{end}', 6, 'UTC')
  AND data_center = '{dc}'
GROUP BY cycle_id, measure_time
ORDER BY measure_time
