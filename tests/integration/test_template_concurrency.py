"""build_template / create_trial_db must be hermetic under concurrency: multiple workers
sharing one template DB must not collide on DROP/CREATE (the defect both deep-test audits hit).
Requires Postgres."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from assertstate.env.template import (
    ClusterConfig,
    build_template,
    create_trial_db,
    drop_db,
)


def _worker(cfg: ClusterConfig) -> str:
    # Each worker rebuilds the SHARED template and then carves its own trial DB from it.
    build_template(cfg)
    trial = f"assertstate_conc_{uuid.uuid4().hex[:12]}"
    create_trial_db(cfg, trial)
    try:
        return trial
    finally:
        drop_db(cfg, trial)


def test_concurrent_build_and_create_do_not_collide(cluster: ClusterConfig) -> None:
    cfg = cluster
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_worker, cfg) for _ in range(8)]
        results = [f.result() for f in futs]  # any collision -> TemplateError raised here
    assert len(results) == 8
