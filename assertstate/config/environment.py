"""ConfiguredEnvironment: run against a real app described by assertstate.yaml (§6, §14).

Resolves the trusted OracleTarget (read-only DSN) and the agent-visible BrowserTarget from
config. Attribution is honest: `reset_hook` (per-trial reset) => causal; `shared` staging =>
observed (db_delta becomes non-gating, §6.5). Read-only is verified at setup (fail-closed).

Known limitation (first config slice): read-only verification uses the privilege sentinel
`assertstate_readonly_probe`. A real app either provides that sentinel table (recommended) or
the operator vouches for a read-only role; a fully schema-agnostic privilege probe is a
follow-up. The session is set read-only regardless (defence in depth).
"""

from __future__ import annotations

import shlex
import subprocess
import uuid
from typing import Any

from assertstate.config.model import AppConfig
from assertstate.domain.result import Attribution
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.orchestrator.environment import TrialContext


class ConfiguredEnvironment:
    def __init__(self, app: AppConfig, *, run_id_prefix: str = "run") -> None:
        self._app = app
        self._prefix = run_id_prefix

    def setup(self, trial_index: int) -> TrialContext:
        app = self._app
        run_id = f"{self._prefix}-{trial_index}-{uuid.uuid4().hex[:8]}"

        if app.environment.strategy == "reset_hook" and app.environment.reset_cmd:
            subprocess.run(shlex.split(app.environment.reset_cmd), check=True, timeout=120)
            attribution = Attribution.CAUSAL  # each trial starts from a reset, single-writer
        else:
            attribution = Attribution.OBSERVED  # shared staging — db_delta is non-gating (§6.5)

        # Fail closed: a writable oracle role raises OracleError -> the trial is ERROR.
        DbProbe(app.oracle.db_dsn).verify_read_only()

        browser_target: dict[str, Any] = {"base_url": app.browser.base_url}
        if app.browser.creds is not None:
            browser_target["creds"] = app.browser.creds

        return TrialContext(
            run_id=run_id,
            oracle_dsn=app.oracle.db_dsn,
            browser_target=browser_target,
            db_name="(external)",
            attribution=attribution,
            adapter_env=dict(app.adapter_env),
            api_base=app.oracle.api_base,
            api_creds=app.oracle.api_creds,
        )

    def teardown(self, ctx: TrialContext) -> None:
        return None  # external app — AssertState does not provision or drop it
