-- Frozen target-IP universe at endpoint granularity.
-- A target enters the universe if it returned at least once during the observed
-- study period. Missing rows in other complete full-scan cycles are interpreted
-- as non-response only after the denominator contract has passed preflight.
WITH targets AS (
  SELECT DISTINCT dst_ip AS ip, prefix24
  FROM {ping}
  WHERE data_center = '{dc}'
    AND measure_time >= toDateTime64('{start}', 6, 'UTC')
    AND measure_time <  toDateTime64('{end}', 6, 'UTC')
    AND dst_ip != '' AND prefix24 != ''
),
latest AS (
  SELECT
    ip,
    argMax(ifNull(asn, 0), updated_at) AS asn,
    argMax(as_name, updated_at) AS as_name,
    argMax(geo_country, updated_at) AS country,
    argMax(geo_region, updated_at) AS admin1,
    argMax(geo_city, updated_at) AS city,
    argMax(geo_latitude, updated_at) AS latitude,
    argMax(geo_longitude, updated_at) AS longitude,
    argMax(isp_domain, updated_at) AS isp_domain,
    max(updated_at) AS mapping_updated_at
  FROM {mapping}
  WHERE 1 = 1
    {mapping_cutoff_clause}
  GROUP BY ip
)
SELECT
  t.ip AS dst_ip,
  t.prefix24,
  ifNull(l.asn, 0) AS target_asn_raw,
  ifNull(l.as_name, '') AS target_as_name,
  ifNull(l.country, '') AS target_country_raw,
  ifNull(l.admin1, '') AS target_admin1_raw,
  ifNull(l.city, '') AS target_city_raw,
  l.latitude AS target_geo_latitude,
  l.longitude AS target_geo_longitude,
  ifNull(l.isp_domain, '') AS target_isp_domain,
  l.mapping_updated_at
FROM targets AS t
LEFT JOIN latest AS l ON t.ip = l.ip
ORDER BY t.prefix24, t.ip
