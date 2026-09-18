# Figure 2 event-type QA

PASS. The main Figure 2 contains only the post-filter main power cohort and one green circle per event-oblast record. It contains no war markers and no red markers. The old V3 taxonomy is audited separately in `event_type_audit.csv`; its non-power rows are not reclassified as war, and no supplementary war timeline is generated in this package. `is_war_event == 0` therefore cannot enter a war-marker set here.
