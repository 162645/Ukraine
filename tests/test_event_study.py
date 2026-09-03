import pandas as pd

from uresil.config import load_config
from uresil.exp_b_event_study import national_dynamic


def test_national_curve_is_precentered_per_prefix():
    cfg = load_config(run_id="event_test", mode="demo")
    cfg.raw["runtime"]["n_bootstrap"] = 20
    rows = []
    for p, base in [("a", 0.8), ("b", 1.2)]:
        for rel in [-4, -2, 0, 2]:
            rows.append({"prefix24": p, "rel_bin": rel,
                         "normalized_reach": base if rel < 0 else base - 0.1})
    curve = national_dynamic(pd.DataFrame(rows), cfg, "e", 1)
    pre = curve[curve.rel_h < 0].effect.abs().max()
    post = curve[curve.rel_h >= 0].effect.mean()
    assert pre < 1e-12
    assert abs(post + 0.1) < 1e-12
