# Missingness and denominator contract

This contract is normative for the manuscript lineage.

1. A **complete measurement cycle** is a cycle that passes the frozen Stage-0 acquisition-quality gate.
2. If an IP has no successful-response row inside a complete static-full-scan opportunity, its response numerator contribution is zero.
3. If the acquisition cycle itself is missing or incomplete, the opportunity is excluded before any IP-level denominator is formed; it is never silently converted to non-response.
4. Power-window denominators are valid complete opportunities inherited from the frozen cache and mapped oblast/event cohort.
5. Time-stratified normal referent counts are frozen event-level counts. The audit can verify the referent-selection rule and timestamps at event level, but the cache does not retain raw per-probe paired timestamps. The manuscript must not describe this as a raw probe-level paired case-crossover panel.
6. Clean-baseline response rate uses the broader clean complete-cycle pool and is not interchangeable with the event-specific time-stratified normal referent response rate.
7. Event-window reachability drop is signed: pre-event response proportion minus attack-window response proportion. Negative values are retained.

Authoritative implementations:

- Cycle quality: `/home/wsl/XiaoLunWen_doc_complete_20260908/runs/doc_complete_20260908/data_derived/cycle_quality.parquet`
- Clean baseline selection: `/home/wsl/XiaoLunWen_doc_complete_20260908/src/uresil/baseline_pool.py`
- Activity construction: `/home/wsl/XiaoLunWen_doc_complete_20260908/src/uresil/activity_stage.py`
- Power/Normal master: `/home/wsl/XiaoLunWen_doc_complete_20260908/power_availability_infrastructure_v1/scripts/power_availability_infrastructure_v1.py`
- Event reachability drop: `/home/wsl/XiaoLunWen_doc_complete_20260908/src/uresil/h1_endpoint_heterogeneity.py`
