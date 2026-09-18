# Main power-event cohort audit

- Source files: `config/planned_outage_schedule_v4_0.csv` and `runs/doc_complete_20260908/data_derived/ip_event_sensitivity.parquet`.
- Schedule filters implemented in `power_availability_infrastructure_v1.py`: `analysis_eligible == 1`, `schedule_positive == 1`, `confound_free == 1`, and `interval_valid == 1`.
- Schedule rows: 1100 raw; 801 after these flags; 67 schedule event IDs; 19 schedule oblast labels; date range 2024-06-01 to 2024-09-06.
- Main cached event rows after the same state/date matching: 5,126,358 IP-event rows; 119 unique event IDs; 119 event-oblast records; 17 oblasts; date range 2024-06-22 to 2024-09-06.
- A row in the main cache is an IP-event observation; Figure 2 collapses it to one event-oblast record for plotting.
- `SAME_EVENT_SOURCE = YES` for the schedule-plus-event-cache data chain used by the main availability stage.
- `SAME_EVENT_COHORT = YES` for the corrected Figure 2 input: it is derived from the post-filter, state/date-matched main cache, not from the V3 taxonomy.
- The old V3 taxonomy event set is not identical to this cohort: its namespace and row semantics differ; it is retained only for lineage auditing.
