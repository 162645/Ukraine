import shutil
import uuid

from uresil.config import load_config
from uresil.provenance import init_or_resume_manifest, mark_stage, read_manifest


def test_resume_preserves_completed_stages():
    run_id = 'prov_' + uuid.uuid4().hex[:10]
    cfg = load_config(run_id=run_id, mode='demo')
    try:
        init_or_resume_manifest(cfg)
        mark_stage(cfg, 'preflight', 'ok', 0.1, [])
        init_or_resume_manifest(cfg, resume=True)
        assert read_manifest(cfg)['stages']['preflight']['status'] == 'ok'
    finally:
        shutil.rmtree(cfg.run_base, ignore_errors=True)
