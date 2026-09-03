import pandas as pd

from uresil.label_precision import audit_timestamp_pairs, relabel_cached_national


def test_kyiv_dst_offsets_are_not_workstation_timezone_dependent():
    d = pd.DataFrame([
        {"local_start": "2024-08-19 18:00", "local_end": "2024-08-19 21:30",
         "timezone": "Europe/Kyiv", "start_utc": "2024-08-19T15:00:00Z", "end_utc": "2024-08-19T18:30:00Z"},
        {"local_start": "2024-12-09 08:00", "local_end": "2024-12-09 19:00",
         "timezone": "Europe/Kyiv", "start_utc": "2024-12-09T06:00:00Z", "end_utc": "2024-12-09T17:00:00Z"},
    ])
    assert audit_timestamp_pairs(d).timestamp_pair_valid.eq(1).all()


def test_national_relabel_uses_cycle_overlap_not_display_timezone():
    obs = pd.DataFrame({"event_id": ["E2024_0819_PLANNED"] * 2,
                        "cycle_id": [1, 2],
                        "measure_time": ["2024-08-19T14:00:00Z", "2024-08-19T18:00:00Z"],
                        "label": [1, 1], "queue_count": [1, 1]})
    seg = pd.DataFrame({"date": ["2024-08-19"], "start_utc": ["2024-08-19T15:00:00Z"],
                        "end_utc": ["2024-08-19T18:30:00Z"], "queue_count": [1]})
    got = relabel_cached_national(obs, seg)
    assert got.label_refined.tolist() == [1, 0]
