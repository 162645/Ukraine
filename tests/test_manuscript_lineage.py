from pathlib import Path
import importlib.util
import sys

import pandas as pd


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_manuscript_lineage.py"
SPEC = importlib.util.spec_from_file_location("build_manuscript_lineage", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_temporal_overlap_resolves_adjacent_utc_date_ids():
    schedule = pd.DataFrame({
        "event_id": ["E_LOCAL_DAY_1", "E_LOCAL_DAY_2"],
        "admin1": ["ALL", "ALL"],
        "schedule_start_utc": pd.to_datetime(["2024-07-17T21:00:00Z", "2024-07-18T21:00:00Z"]),
        "schedule_end_utc": pd.to_datetime(["2024-07-18T02:00:00Z", "2024-07-19T02:00:00Z"]),
        "record_id": ["r1", "r2"],
        "scope_type_norm": ["national", "national"],
        "source_authority": ["official", "official"],
        "source_url": ["u1", "u2"],
    })
    cache = pd.DataFrame({
        "dst_ip": ["1.1.1.1"], "prefix24": ["1.1.1.0"],
        "target_admin1": ["Example Oblast"], "event_id": ["CAL_20240718"],
        "x_normal": [1], "x_outage": [0], "n_normal": [4], "n_outage": [1],
    })
    calibration = pd.DataFrame({
        "event_id": ["CAL_20240718"], "geo_name": ["Example Oblast"],
        "event_date": ["2024-07-18"],
        "calibration_start_utc": pd.to_datetime(["2024-07-18T21:15:00Z"]),
        "calibration_end_utc": pd.to_datetime(["2024-07-18T23:00:00Z"]),
        "segment_n": [1], "source_record_n": [1], "evidence_tier": ["P1"],
        "use_main": [1], "use_augmented": [1],
    })
    crosswalk, _ = MODULE.build_crosswalk(schedule, schedule, cache, calibration)
    assert crosswalk.loc[0, "mapping_status"] == "EXACT_ONE_SCHEDULE_EVENT"
    assert crosswalk.loc[0, "schedule_event_id"] == "E_LOCAL_DAY_2"


def test_temporal_overlap_marks_real_ambiguity():
    schedule = pd.DataFrame({
        "event_id": ["E1", "E2"], "admin1": ["ALL", "ALL"],
        "schedule_start_utc": pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"]),
        "schedule_end_utc": pd.to_datetime(["2024-01-01T03:00:00Z", "2024-01-01T04:00:00Z"]),
        "record_id": ["r1", "r2"], "scope_type_norm": ["national", "national"],
        "source_authority": ["a", "b"], "source_url": ["u1", "u2"],
    })
    cache = pd.DataFrame({
        "dst_ip": ["1.1.1.1"], "prefix24": ["1.1.1.0"], "target_admin1": ["X"],
        "event_id": ["CAL"], "x_normal": [1], "x_outage": [0], "n_normal": [1], "n_outage": [1],
    })
    calibration = pd.DataFrame({
        "event_id": ["CAL"], "geo_name": ["X"], "event_date": ["2024-01-01"],
        "calibration_start_utc": pd.to_datetime(["2024-01-01T01:30:00Z"]),
        "calibration_end_utc": pd.to_datetime(["2024-01-01T02:30:00Z"]),
        "segment_n": [1], "source_record_n": [1], "evidence_tier": ["P1"],
        "use_main": [1], "use_augmented": [1],
    })
    crosswalk, _ = MODULE.build_crosswalk(schedule, schedule, cache, calibration)
    assert crosswalk.loc[0, "mapping_status"] == "AMBIGUOUS_MULTIPLE_SCHEDULE_EVENTS"


def test_union_hours_does_not_double_count_overlapping_queue_rows():
    intervals = [
        (pd.Timestamp("2024-01-01T00:00:00Z"), pd.Timestamp("2024-01-01T02:00:00Z")),
        (pd.Timestamp("2024-01-01T01:00:00Z"), pd.Timestamp("2024-01-01T03:00:00Z")),
    ]
    assert MODULE._union_hours(intervals) == 3.0


def test_measured_traceroute_facts_enter_result_manifest():
    base = pd.DataFrame(columns=[
        "manuscript_name", "value", "value_scale", "analysis_sample",
        "source_file", "source_column_or_rule", "generating_script",
        "code_git_commit", "source_sha256", "source_content_digest", "note",
    ])
    summary = {
        "status": "PASS", "table": "trace_table", "measurement_row_n": "10",
        "cycle_n": "2", "reached_target_row_n": "3",
        "min_measure_time": "2024-01-01 00:00:00.000000",
        "max_measure_time": "2024-01-01 01:00:00.000000",
        "measurement_ledger_hash_xor": "11", "measurement_ledger_hash_sum": "22",
    }
    result = MODULE.append_traceroute_results(base, summary, "abc123")
    assert len(result) == 5
    assert int(result.loc[result["manuscript_name"].eq("Measured traceroute rows"), "value"].iloc[0]) == 10
    assert result["source_file"].str.contains("ClickHouse active_measurement.trace_table", regex=False).all()
    assert result["source_sha256"].eq("").all()
    assert result["source_content_digest"].str.contains("measurement_hash_xor=11", regex=False).all()
