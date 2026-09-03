from uresil.config import load_config


def test_current_registry_counts_events_and_independent_clusters_separately():
    cfg = load_config(run_id="capacity", mode="demo")
    ready = cfg.load_event_registry()
    ready = ready[ready["analysis_ready"].eq(1)]
    registered = int(ready["analysis_role"].eq("planned_valid").sum())
    required = int(cfg.calibration["min_publication_validation_events"])
    schedule = cfg.load_schedule_registry()
    valid_ids = set(ready.loc[ready["analysis_role"].eq("planned_valid"), "event_id"])
    clusters = schedule[(schedule["event_id"].isin(valid_ids)) &
                        schedule["publication_eligible"].eq(1)]["independence_cluster"].nunique()
    assert registered == 5
    assert required == 2
    assert clusters == 2
    assert clusters >= int(cfg.calibration["min_publication_validation_clusters"])
