"""The adapter-execution sandbox is a real, CLI-engaged production path (DoD §37 "real AND
sandboxed"), not a test-only capability: the --config run path engages the container by default.

Covers the container command profile (both network postures) and the sandbox resolver. Pure/no
Docker: asserts the command we WOULD run and the resolver's decisions."""

from __future__ import annotations

import pytest

import assertstate.cli as cli
from assertstate.adapters.runner import _container_cmd


def test_container_cmd_strict_network_none_isolates_everything() -> None:
    cmd = _container_cmd("mod:Adapter", None, network="none")
    assert cmd[cmd.index("--network") + 1] == "none"  # full socket isolation (adversarial proof)
    assert "--read-only" in cmd and "--cap-drop" in cmd and "65534:65534" in cmd
    joined = " ".join(cmd)
    assert "/.assertstate" not in joined, "host artifact store must never be mounted"
    assert ":ro" in joined  # only read-only mounts


def test_container_cmd_bridge_keeps_fs_and_priv_isolation_for_networked_agent() -> None:
    cmd = _container_cmd("mod:Adapter", None, network="bridge")
    assert cmd[cmd.index("--network") + 1] == "bridge"  # agent can reach the app...
    # ...but host-FS / privilege isolation and the no-oracle-mount posture still hold.
    assert "--read-only" in cmd and "--cap-drop" in cmd and "65534:65534" in cmd
    assert "/.assertstate" not in " ".join(cmd)


def test_container_cmd_still_refuses_oracle_shaped_env() -> None:
    from assertstate.adapters.base import AdapterError

    with pytest.raises(AdapterError):
        _container_cmd("mod:Adapter", {"ORACLE_DSN": "x"}, network="bridge")


def test_resolve_sandbox_off_is_subprocess() -> None:
    assert cli._resolve_sandbox("off") == ("subprocess", "none", "subprocess")


def test_resolve_sandbox_auto_uses_container_when_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_docker_available", lambda: True)
    mode, net, img = cli._resolve_sandbox("auto")
    assert mode == "container" and net == "bridge" and img.startswith("container:")


def test_resolve_sandbox_auto_falls_back_with_loud_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_docker_available", lambda: False)
    mode, net, img = cli._resolve_sandbox("auto")
    assert mode == "subprocess" and img == "subprocess-fallback"
    assert "WARNING" in capsys.readouterr().err  # the weaker posture is never silent


def test_resolve_sandbox_container_requires_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_docker_available", lambda: False)
    with pytest.raises(SystemExit):
        cli._resolve_sandbox("container")  # refuse to run unsandboxed when explicitly requested
