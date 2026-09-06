from types import SimpleNamespace

import pandas as pd

from uresil.validate import _application_gain


def test_application_gain_compares_frozen_sensors_with_stable_pool():
    table = pd.DataFrame([
        {"event_id": "attack1", "estimand_id": "main", "sensor_method": "B1",
         "status": "ok", "deficit_auc_full": 1.0, "max_deficit": .2},
        {"event_id": "attack1", "estimand_id": "main", "sensor_method": "B2",
         "status": "ok", "deficit_auc_full": 1.4, "max_deficit": .3},
        {"event_id": "attack2", "estimand_id": "main", "sensor_method": "B1",
         "status": "ok", "deficit_auc_full": .8, "max_deficit": .1},
        {"event_id": "attack2", "estimand_id": "main", "sensor_method": "B2",
         "status": "ok", "deficit_auc_full": 1.0, "max_deficit": .2},
    ])
    cfg = SimpleNamespace(runtime={"random_seed": 7, "n_bootstrap": 50})
    rows, summary = _application_gain(table, cfg)
    assert len(rows) == 2
    assert summary["estimable"]
    assert summary["independent_event_n"] == 2
    assert summary["mean_gain_deficit_auc"] > 0
