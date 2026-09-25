# Own-traceroute evidence rebuild v1

This read-only experiment rebuilds the manuscript's own-traceroute intermediate-hop evidence directly from the authoritative ClickHouse `hop_path` arrays.

It does not modify the frozen manuscript master, models, event cohort, thresholds, or figures. The frozen field is an identity target only: disagreement produces an IP-level difference file and never an automatic label replacement.

Definition: an eligible address is a valid public IPv4 response observed strictly before the final recorded path element and unequal to the traceroute destination. Stars and special-purpose addresses are excluded; missing hops are never imputed.

The frozen Ukraine target registry supplies the Ukraine-mapped subset. The frozen 1,170,227-IP master supplies the analysis intersection and CAIDA 2024-08 comparison. The descriptive validation reuses the exact frozen S2 Freedman-Diaconis bins and Wilson intervals.

Server invocation:

```bash
export CLICKHOUSE_PASSWORD='<set outside git>'
python scripts/rebuild_own_traceroute_evidence.py \
  --root /home/wsl/XiaoLunWen_doc_complete_20260908 \
  --output /home/wsl/Ukraine_method_lineage_20260925/outputs/own_traceroute_rebuild_v1 \
  --work-dir /home/wsl/own_traceroute_rebuild_cache_v1 \
  --clickhouse-url http://10.112.131.168:8124 \
  --clickhouse-user measure_user
```
