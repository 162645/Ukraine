-- On-demand latest hop-IP mapping at/before the frozen snapshot.
SELECT
    ip,
    argMax(ifNull(asn, 0), updated_at) AS asn,
    argMax(geo_country, updated_at) AS country,
    argMax(geo_region, updated_at) AS admin1
FROM {mapping}
WHERE ip IN ({ip_in})
  {mapping_cutoff_clause}
GROUP BY ip
