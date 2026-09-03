-- 05_path_trace_window.sql
-- 实验E: 在一个时间窗口内、针对给定目标 /24 集合,**流式**拉取原始 traceroute。
-- 关键: 以 hop_path(原始逐跳)为主输入重建高置信直接边,而不是用 as_path_hash/asgeo_path_hash。
-- 逐块 yield,避免一次性物化 520 万行。
-- 占位符: {trace} {win_start} {win_end} {dc} {prefix_in}
SELECT
    cycle_id,
    measure_time,
    prefix24,
    dst_ip,
    hop_count,
    responded_hop_count,
    star_hop_count,
    reached_target,
    hop_path,                 -- Array(Tuple(ip String, rtt Nullable(Float32), ttl Nullable(UInt16)))
    probe_ts_us
FROM {trace}
WHERE measure_time >= toDateTime64('{win_start}', 6, 'UTC')
  AND measure_time <  toDateTime64('{win_end}', 6, 'UTC')
  AND data_center = '{dc}'
  AND prefix24 IN ({prefix_in})
ORDER BY prefix24, cycle_id, dst_ip;
