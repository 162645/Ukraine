"""Auditable downstream H4 reframe."""
from pathlib import Path
import hashlib
import pandas as pd

ROOT = Path("/home/wsl/XiaoLunWen_doc_complete_20260908")
H4 = ROOT / "runs/h4_final_experiment_20260911/results/stages/stage_h4_loss_contribution_decomposition"
H1 = ROOT / "runs/h1_endpoint_heterogeneity_20260910/results/stages/stage_h1_endpoint_heterogeneity/h1_ip_level_outcomes.parquet"

def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def frozen_panel():
    x = pd.read_parquet(H4 / "h4_ip_level_main.parquet")
    x = x.drop_duplicates(["dst_ip", "event_id"], keep="first").copy()
    x["reach_drop"] = pd.to_numeric(x["reach_drop"], errors="coerce")
    x = x[x["reach_drop"].notna()].copy()
    x["activity_score"] = pd.to_numeric(x["activity_score_smoothed"], errors="coerce")
    x["positive_loss"] = x["reach_drop"].clip(lower=0)
    x["positive_loss_flag"] = x["reach_drop"].gt(0)
    n = pd.to_numeric(x["activity_decile"].astype(str).str.extract(r"(\d+)")[0], errors="coerce")
    x["activity_quintile"] = n.apply(lambda v: "Q%d" % int((v + 1) // 2) if pd.notna(v) else pd.NA)
    return x

def verify():
    x = frozen_panel()
    per_ip = x.groupby("dst_ip").size()
    return {
        "h4_input_sha256": sha256(H4 / "h4_ip_level_main.parquet"),
        "h1_input_sha256": sha256(H1),
        "unique_ip_n": int(x.dst_ip.nunique()),
        "ip_event_rows": int(len(x)),
        "duplicate_ip_count": int((per_ip > 1).sum()),
        "ip_event_rows_per_ip_median": float(per_ip.median()),
        "ip_event_rows_per_ip_p95": float(per_ip.quantile(.95)),
        "ip_event_rows_per_ip_max": int(per_ip.max()),
        "positive_loss_count": int(x.positive_loss_flag.sum()),
        "positive_loss_rate": float(x.positive_loss_flag.mean()),
        "frozen_activity_deciles": sorted(x.activity_decile.dropna().unique().tolist()),
    }

if __name__ == "__main__":
    import json
    print(json.dumps(verify(), indent=2, ensure_ascii=False))
