import pandas as pd

from uresil.time_contract import infer_display_timezone


def test_infers_utc_from_epoch_without_event_labels():
    raw = pd.to_datetime(["2024-07-07 12:00:00", "2024-12-09 06:00:00"])
    epoch = [int(pd.Timestamp(x, tz="UTC").timestamp() * 1_000_000) for x in raw.astype(str)]
    got = infer_display_timezone(pd.DataFrame({"raw_time": raw, "epoch_us": epoch}),
                                 server_timezone="UTC")
    assert got["inferred_timezone"] == "UTC"


def test_detects_shanghai_display_semantics():
    raw = pd.to_datetime(["2024-07-07 20:00:00", "2024-12-09 14:00:00"])
    epoch = [int(pd.Timestamp(x, tz="Asia/Shanghai").timestamp() * 1_000_000)
             for x in raw.astype(str)]
    got = infer_display_timezone(pd.DataFrame({"raw_time": raw, "epoch_us": epoch}),
                                 server_timezone="Asia/Shanghai")
    assert got["inferred_timezone"] == "Asia/Shanghai"
