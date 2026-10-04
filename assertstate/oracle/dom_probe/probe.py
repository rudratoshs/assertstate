"""Trusted DOM probe for `expect.ui` (FEATURE-SPEC §4.6, `[P2, fallback only]`).

The PARENT (trusted side) obtains the app page's DOM ITSELF and extracts the text of a selected
element. It never touches the agent's browser, so a `ui` assertion is still an independent oracle
read — the agent's self-report never decides it (INV-8). Two render modes:
  - render="html" (default, zero-dep): read-only HTTP GET of the SERVER-RENDERED HTML (stdlib).
  - render="js": run a headless Chrome with `--dump-dom` so client-side JavaScript executes and the
    RENDERED DOM is captured (for SPAs). Uses an ISOLATED `--user-data-dir` (never the user's real
    Chrome profile) and fails closed to ERROR if no Chrome is found.

Bounded, by design:
  - render="html" sees no JavaScript; use render="js" for client-rendered apps. Fail-closed: an
    element absent from the obtained DOM reads as "not present", never a silent pass.
  - Minimal CSS-selector subset: `tag`, `#id`, `.class`, `tag#id`, `tag.class`. Anything else is a
    clear error, never a best-effort guess.
  - Read-only (GET / a non-interacting DOM dump). Fetch/launch failure -> OracleError -> ERROR.
"""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

from assertstate.oracle.db_probe.probe import OracleError

_SELECTOR_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)?(?:#([A-Za-z0-9_-]+)|\.([A-Za-z0-9_-]+))?$")
_MAX_HTML = 4 * 1024 * 1024
_CHROME_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
)


def _find_chrome() -> str:
    env = os.environ.get("ASSERTSTATE_CHROME_PATH")
    if env and (shutil.which(env) or os.path.exists(env)):
        return env
    for cand in _CHROME_CANDIDATES:
        hit = shutil.which(cand) if "/" not in cand else (cand if os.path.exists(cand) else None)
        if hit:
            return hit
    raise OracleError(
        "ui render='js' needs a Chrome/Chromium binary (set ASSERTSTATE_CHROME_PATH) — not found"
    )


def _render_js_dom(url: str, *, virtual_time_ms: int, timeout_s: float) -> str:
    """Return the JS-rendered DOM HTML via a headless Chrome `--dump-dom` (isolated profile).

    Chrome dumps the rendered DOM to stdout then, on a fresh profile, often does NOT self-exit, so
    we read stdout until the DOM closes (`</html>`) and then KILL it — never relying on Chrome to
    terminate. The isolated `--user-data-dir` means the user's real Chrome profile is never touched.
    """
    chrome = _find_chrome()
    profile = tempfile.mkdtemp(prefix="assertstate-ui-")
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        f"--user-data-dir={profile}",  # isolated: never the user's real Chrome profile
        f"--virtual-time-budget={virtual_time_ms}",
        "--dump-dom",
        url,
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError as exc:
        shutil.rmtree(profile, ignore_errors=True)
        raise OracleError(f"ui render='js' could not launch Chrome: {exc}") from exc
    try:
        assert proc.stdout is not None
        fd = proc.stdout.fileno()
        chunks: list[bytes] = []
        total = 0
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], max(0.05, deadline - time.monotonic()))
            if not ready:
                continue
            chunk = os.read(fd, 65536)
            if not chunk:  # EOF: Chrome closed stdout on its own
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _MAX_HTML or b"</html>" in b"".join(chunks[-2:]).lower():
                break
        html = b"".join(chunks).decode("utf-8", "replace")
    finally:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        shutil.rmtree(profile, ignore_errors=True)
    if "</html>" not in html.lower():
        raise OracleError(f"ui render='js' produced no complete DOM for {url} within {timeout_s}s")
    return html


def _parse_selector(selector: str) -> tuple[str | None, str | None, str | None]:
    m = _SELECTOR_RE.match(selector.strip())
    if not m or selector.strip() == "":
        raise OracleError(
            f"ui selector {selector!r} unsupported; use tag | #id | .class | tag#id | tag.class"
        )
    tag, id_, cls = m.group(1), m.group(2), m.group(3)
    if not (tag or id_ or cls):
        raise OracleError(f"ui selector {selector!r} is empty")
    return tag, id_, cls


class _FirstMatchText(HTMLParser):
    """Capture the inner text of the FIRST element matching (tag?, #id?, .class?)."""

    def __init__(self, tag: str | None, id_: str | None, cls: str | None) -> None:
        super().__init__()
        self._want = (tag, id_, cls)
        self.found = False
        self._capturing = False
        self._tag = ""
        self._depth = 0
        self._text: list[str] = []

    def _match(self, tag: str, attrs: dict[str, str | None]) -> bool:
        want_tag, want_id, want_cls = self._want
        if want_tag and tag != want_tag:
            return False
        if want_id and attrs.get("id") != want_id:
            return False
        if want_cls and want_cls not in (attrs.get("class") or "").split():
            return False
        return True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.found and self._match(tag, dict(attrs)):
            self.found = True
            self._capturing = True
            self._tag = tag
            self._depth = 1
        elif self._capturing and tag == self._tag:
            self._depth += 1  # a nested same-tag element

    def handle_endtag(self, tag: str) -> None:
        if self._capturing and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._text.append(data)

    @property
    def text(self) -> str:
        return "".join(self._text).strip()


class DomProbe:
    """Trusted, agent-independent DOM reader over server-rendered HTML."""

    def __init__(
        self, base_url: str, *, timeout_s: float = 15.0, virtual_time_ms: int = 3000
    ) -> None:
        self._base = base_url
        self._timeout = timeout_s
        self._virtual_time_ms = virtual_time_ms

    def read(self, path: str, selector: str, render: str = "html") -> tuple[bool, str | None]:
        """Return (found, inner-text-of-first-match). render: 'html' (GET/SSR) | 'js' (headless)."""
        tag, id_, cls = _parse_selector(selector)
        url = urljoin(
            self._base if self._base.endswith("/") else self._base + "/", path.lstrip("/")
        )
        if not url.lower().startswith(("http://", "https://")):
            raise OracleError(f"ui probe needs an http(s) app base_url, got {self._base!r}")
        if render == "js":
            html = _render_js_dom(
                url, virtual_time_ms=self._virtual_time_ms, timeout_s=self._timeout
            )
        elif render == "html":
            try:
                req = urllib.request.Request(url, method="GET")  # read-only
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    raw = resp.read(_MAX_HTML + 1)
            except OSError as exc:
                raise OracleError(f"ui probe GET {url} failed: {exc}") from exc
            if len(raw) > _MAX_HTML:
                raise OracleError(f"ui probe response exceeded {_MAX_HTML} bytes")
            html = raw.decode("utf-8", "replace")
        else:  # pragma: no cover - loader validates the set
            raise OracleError(f"ui render must be 'html' or 'js', got {render!r}")
        parser = _FirstMatchText(tag, id_, cls)
        parser.feed(html)
        return (parser.found, parser.text if parser.found else None)
