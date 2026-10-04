"""§8.5 regression/version comparison — two-proportion CI + paired McNemar.

Distinct from the Wilson acceptance gate: these decide "is B significantly WORSE than A?".
"""

from __future__ import annotations

from assertstate.stats.compare import mcnemar, two_proportion


# --- two-sample difference-in-proportions ---
def test_two_proportion_clear_regression() -> None:
    r = two_proportion(30, 30, 24, 30)  # A=100%, B=80%
    assert r.diff < 0 and r.ci_high is not None and r.ci_high < 0
    assert r.regressed is True


def test_two_proportion_small_drop_not_significant() -> None:
    r = two_proportion(30, 30, 29, 30)  # A=100%, B=96.7%
    assert r.regressed is False  # CI on the diff still crosses 0


def test_two_proportion_equal_is_not_regression() -> None:
    assert two_proportion(30, 30, 30, 30).regressed is False


def test_two_proportion_improvement_is_not_regression() -> None:
    assert two_proportion(24, 30, 30, 30).regressed is False


# --- paired McNemar ---
def test_mcnemar_all_discordant_one_way_regresses() -> None:
    # 8 scenarios A passed but B failed, 0 the other way -> B clearly worse.
    r = mcnemar(both_pass=22, a_pass_b_fail=8, a_fail_b_pass=0, both_fail=0)
    assert r.p_value is not None and r.p_value < 0.05
    assert r.regressed is True


def test_mcnemar_symmetric_not_significant() -> None:
    assert mcnemar(both_pass=10, a_pass_b_fail=3, a_fail_b_pass=1, both_fail=10).regressed is False


def test_mcnemar_no_discordant_not_significant() -> None:
    assert mcnemar(both_pass=30, a_pass_b_fail=0, a_fail_b_pass=0, both_fail=0).regressed is False


def test_mcnemar_improvement_not_regression() -> None:
    # B passed more than A on the discordant pairs -> not a regression.
    assert mcnemar(both_pass=10, a_pass_b_fail=0, a_fail_b_pass=8, both_fail=0).regressed is False


def test_mcnemar_large_n_uses_chi_square() -> None:
    r = mcnemar(both_pass=0, a_pass_b_fail=40, a_fail_b_pass=20, both_fail=0)  # 60 discordant
    assert r.p_value is not None and r.regressed is True
