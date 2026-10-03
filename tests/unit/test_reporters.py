"""P1 reporters: JUnit + HTML formatters (pure; never alter a verdict)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from assertstate.reporters.html import to_html
from assertstate.reporters.junit import to_junit

_VERDICT = {
    "verdict": "FAIL",
    "total_trials": 3,
    "passed": 1,
    "failed": 1,
    "errored": 1,
    "skipped": 0,
    "wilson_lower": 0.0,
    "pass_threshold": 0.5,
    "reason": "wilson below threshold",
    "per_trial": [
        {"outcome": "PASS", "reason": "ok"},
        {"outcome": "FAIL", "reason": "duplicate added=2/max1"},
        {"outcome": "ERROR", "reason": "oracle unavailable"},
    ],
}


def test_junit_is_wellformed_xml_with_counts() -> None:
    xml = to_junit(_VERDICT, "run-x")
    root = ET.fromstring(xml)
    assert root.tag == "testsuite"
    assert root.attrib["tests"] == "3"
    assert root.attrib["failures"] == "1"
    assert root.attrib["errors"] == "1"
    cases = root.findall("testcase")
    assert len(cases) == 3
    assert cases[1].find("failure") is not None
    assert cases[2].find("error") is not None


def test_junit_escapes_reason() -> None:
    v = dict(
        _VERDICT,
        per_trial=[{"outcome": "FAIL", "reason": "a < b & c > d"}],
        failed=1,
        total_trials=1,
        passed=0,
        errored=0,
    )
    xml = to_junit(v, "run <x>")
    ET.fromstring(xml)  # must still parse (attrs/text escaped)


def test_html_contains_verdict_and_rows() -> None:
    out = to_html(_VERDICT, "run-x")
    assert "<!doctype html>" in out
    assert "FAIL" in out and "duplicate added=2/max1" in out
    assert out.count("<tr>") == 4  # header + 3 trials
