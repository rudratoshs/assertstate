"""ConfiguredEnvironment: run against a real app described by assertstate.yaml (§6, §14).

Resolves the trusted OracleTarget (read-only DSN) and the agent-visible BrowserTarget from
config. Attribution is honest: `reset_hook` (per-trial reset) => causal; `shared` staging =>
observed (db_delta becomes non-gating, §6.5). Read-only is verified at setup (fail-closed).

Trusted network capture (§3): when the app is capturable (http:// base_url, or `capture: on`),
a PARENT-OWNED recording proxy is started per trial and the agent is routed through it via
`browser_target.proxy`. Its records live here, in the trusted parent (the agent can route through
it honestly or bypass it, but can never read or forge the records — INV-8), and they drive the
http/external/trajectory policies as GATING. Without capture (https:// without TLS interception,
or `capture: off`) those observation-based policies run NON-GATING — never a silent pass, never a
false FAIL. `capture_bind`/`capture_advertise` let the caller place the proxy where the agent can
reach it: 127.0.0.1 for an on-host (subprocess) agent, 0.0.0.0 + host.docker.internal for a
containerised agent reaching the parent over the Docker host gateway.

Known limitation (first config slice): read-only verification uses the privilege sentinel
`assertstate_readonly_probe`. A real app either provides that sentinel table (recommended) or
the operator vouches for a read-only role; a fully schema-agnostic privilege probe is a
follow-up. The session is set read-only regardless (defence in depth). HTTPS capture needs TLS
interception (a documented follow-up); an https app stays honestly non-gating for those policies.
"""

from __future__ import annotations

import shlex
import subprocess
import uuid
from typing import Any

from assertstate.config.model import AppConfig, BrowserConfig
from assertstate.domain.result import Attribution
from assertstate.instrumentation.network_capture import TrustedNetworkCapture, proxy_url
from assertstate.oracle.db_probe.probe import DbProbe
from assertstate.orchestrator.environment import TrialContext


def capture_enabled(browser: BrowserConfig) -> bool:
    """Whether a trusted capture proxy should be started for this app (see module docstring)."""
    if browser.capture == "off":
        return False
    if browser.capture == "on":
        return True
    return browser.base_url.lower().startswith("http://")  # "auto": plain-HTTP only


class ConfiguredEnvironment:
    def __init__(
        self,
        app: AppConfig,
        *,
        run_id_prefix: str = "run",
        capture_bind: str = "127.0.0.1",
        capture_advertise: str = "127.0.0.1",
    ) -> None:
        self._app = app
        self._prefix = run_id_prefix
        self._capture_bind = capture_bind
        self._capture_advertise = capture_advertise

    def setup(self, trial_index: int) -> TrialContext:
        app = self._app
        run_id = f"{self._prefix}-{trial_index}-{uuid.uuid4().hex[:8]}"

        # reset_hook / template_restore both run a per-trial reset that re-establishes
        # single-writer isolation -> causal. shared staging -> observed (db_delta non-gating, §6.5).
        env = app.environment
        if env.strategy in ("reset_hook", "template_restore") and env.reset_cmd:
            subprocess.run(shlex.split(env.reset_cmd), check=True, timeout=120)
            attribution = Attribution.CAUSAL
        else:
            attribution = Attribution.OBSERVED

        # Fail closed: a writable oracle role raises OracleError -> the trial is ERROR.
        DbProbe(app.oracle.db_dsn).verify_read_only()

        browser_target: dict[str, Any] = {"base_url": app.browser.base_url}
        if app.browser.creds is not None:
            browser_target["creds"] = app.browser.creds
        if app.browser.cdp_url is not None:
            # Agent-side: the adapter ATTACHES to this operator-controlled remote browser (§9.5).
            browser_target["cdp_url"] = app.browser.cdp_url

        # Parent-owned trusted capture (the agent never gets this object; INV-8).
        capture: TrustedNetworkCapture | None = None
        if capture_enabled(app.browser):
            capture = TrustedNetworkCapture()
            capture.start(bind_host=self._capture_bind)
            assert capture.port is not None
            browser_target["proxy"] = proxy_url(self._capture_advertise, capture.port)

        return TrialContext(
            run_id=run_id,
            oracle_dsn=app.oracle.db_dsn,
            browser_target=browser_target,
            db_name="(external)",
            handle=capture,
            attribution=attribution,
            adapter_env=dict(app.adapter_env),
            capture=capture,  # trusted anchor + http/external/trajectory evidence source
            api_base=app.oracle.api_base,
            api_creds=app.oracle.api_creds,
        )

    def teardown(self, ctx: TrialContext) -> None:
        # External app — AssertState does not provision or drop it; only stop our capture proxy.
        if isinstance(ctx.handle, TrustedNetworkCapture):
            ctx.handle.stop()
