# Traceroute provenance

## Recovered sampler

- Server source: `/home/test/GlobalPing_ZT/kernal/areaPing/areaPing.go`
- Source repository HEAD: `042b48afcbdba553d80c5928bff991c09a8ccf1e`
- Source file worktree status: `DIRTY`
- Frozen source SHA-256: `99a6cab5c27f5501d6fdd6d42719f347f31fdff96b348e1d97b34cee735dcea6`
- Frozen snapshot: `evidence/traceroute_sampler/areaPing.go.server_snapshot`

The recovered `Traceroute` function executes four measurements per C segment. It chooses one host address from each of the ranges 1–63, 65–127, 129–191, and 192–254. The implementation calls `rand.Seed(time.Now().UnixNano())` during measurement, so there is no fixed historical seed that can reproduce the same random choices.

The actual selected destination and its measured route are stored in ClickHouse. `dst_ip` recovers the historical target; `hop_count`, `responded_hop_count`, `star_hop_count`, `reached_target`, `hop_path`, `ip_path_hash`, and `raw_trace` are measurement-result fields. The sampler snapshot is not treated as measured data.

## Frozen measured traceroute ledger

ClickHouse status: `PASS`. The authoritative measurements remain in the read-only ClickHouse table because committing hundreds of millions of rows to Git would be inappropriate. `TRACEROUTE_MEASUREMENT_SCHEMA.tsv` freezes its schema; `TRACEROUTE_MEASUREMENT_MANIFEST_BY_CYCLE.csv` records observed-route counts plus order-independent hashes; `TRACEROUTE_MEASUREMENT_SAMPLE.jsonl` is a small auditable sample. Fields ending in `_estimate_n` use ClickHouse `uniqCombined64` to bound memory on the shared server and are explicitly estimates; row counts and both ledger hashes are exact deterministic scans of the structured measurement columns. `raw_trace` is sampled but is not decompressed across the full table because the normalized hop/path columns carry the measured result used downstream. The full measured ledger can be queried with:

```sql
SELECT cycle_id, measure_time, data_center, prefix24, dst_ip,
       hop_count, responded_hop_count, star_hop_count, reached_target,
       hop_path, ip_path_hash, raw_trace, probe_ts_us
FROM active_measurement.`UKRAINE__quarter-traceroute_AWS_frankfurt_2024-06-22`
ORDER BY cycle_id, prefix24, dst_ip;
```

Global source-table summary is recorded in `TRACEROUTE_PROVENANCE.json`.
