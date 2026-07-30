# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""The Tier 4 validation modules are reachable from a real surface (issue #88).

`fidelity.py` and `utility_probe.py` shipped fully tested but unreachable: the
`hipaasynth.validation` package exported nothing, and no CLI/API/SDK entry point
called them. A trust claim nobody can invoke does not discharge the purpose of
the tier, so these tests pin the public surface rather than the maths — the
maths already has `test_fidelity.py` and `test_utility_probe.py`.
"""

import pytest

import hipaasynth.validation as validation
from hipaasynth.sdk import MODULES, generate
from hipaasynth.validation import UtilityProbeResult

# ── the package actually exports something ───────────────────────────────────


def test_validation_package_exports_the_two_aggregates():
    """The regression this issue is about: `from hipaasynth.validation import
    fidelity_report` used to raise ImportError against an empty __init__."""
    from hipaasynth.validation import downstream_utility_probe, fidelity_report

    assert callable(fidelity_report)
    assert callable(downstream_utility_probe)


def test_validation_package_declares_all_and_every_name_resolves():
    assert validation.__all__, "__all__ must not be empty"
    for name in validation.__all__:
        assert hasattr(validation, name), f"__all__ lists {name!r} but it is not importable"


@pytest.mark.parametrize(
    "name",
    ["fidelity_report", "downstream_utility_probe", "validate_cohort"],
)
def test_headline_names_are_in_all(name):
    assert name in validation.__all__


def test_importing_the_package_needs_no_third_party_dependency():
    """The package is eagerly imported by the SDK, so a heavy import here would
    tax every `import hipaasynth`. Everything it pulls in is stdlib or internal."""
    import importlib
    import sys

    for mod in [m for m in sys.modules if m.startswith("hipaasynth.validation")]:
        del sys.modules[mod]
    importlib.import_module("hipaasynth.validation")


# ── the SDK surface ──────────────────────────────────────────────────────────


def test_cohort_exposes_fidelity_and_utility():
    cohort = generate(count=60, seed=11)
    assert hasattr(cohort, "fidelity")
    assert hasattr(cohort, "utility")


def test_cohort_fidelity_returns_the_report_for_its_own_patients():
    from hipaasynth.validation import fidelity_report

    cohort = generate(count=60, seed=11)
    via_method = cohort.fidelity()
    via_function = fidelity_report(cohort.patients)

    assert via_method["n_patients"] == 60
    # The method must be a pass-through, not a reimplementation that can drift.
    assert via_method == via_function


def test_cohort_fidelity_report_has_its_documented_sections():
    report = generate(count=60, seed=11).fidelity()
    for section in (
        "n_patients",
        "lab_marginals",
        "condition_prevalence",
        "linked_lab_correlations",
        "temporal_consistency",
        "visit_order",
    ):
        assert section in report


def test_cohort_utility_returns_a_probe_result():
    result = generate(count=200, seed=11).utility()
    assert isinstance(result, UtilityProbeResult)
    assert result.n_total == 200
    assert 0.0 <= result.accuracy <= 1.0
    assert result.auc is None or 0.0 <= result.auc <= 1.0
    assert result.as_dict()["target"] == result.target


def test_cohort_utility_passes_keyword_arguments_through():
    cohort = generate(count=200, seed=11)
    assert cohort.utility(seed=1).n_test == cohort.utility(seed=1).n_test
    # test_fraction is honoured, so the kwargs really reach the probe.
    assert cohort.utility(test_fraction=0.5).n_test > cohort.utility(test_fraction=0.2).n_test


@pytest.mark.parametrize("module", sorted(MODULES))
def test_both_entry_points_work_for_every_module(module):
    """A surface that only works for the default module is not a surface."""
    cohort = generate(count=200, seed=7, module=module)
    assert cohort.fidelity()["n_patients"] == 200
    assert cohort.utility().n_total == 200


def test_utility_default_target_is_not_the_modules_own_condition():
    """`module="stroke"` makes every patient a stroke patient, so probing for the
    module's own condition would leave one class and always raise. The default
    must stay a comorbidity that actually varies."""
    cohort = generate(count=200, seed=7, module="stroke")
    assert all(any(c.name == "stroke" for c in p.conditions) for p in cohort.patients)
    assert cohort.utility().target != "stroke"


# ── failure modes stay loud ──────────────────────────────────────────────────


def test_fidelity_on_an_empty_cohort_raises():
    cohort = generate(count=10, seed=11)
    cohort.patients = []
    with pytest.raises(ValueError):
        cohort.fidelity()


def test_utility_on_a_too_small_cohort_raises():
    with pytest.raises(ValueError):
        generate(count=5, seed=11).utility()


def test_utility_on_an_absent_target_raises():
    with pytest.raises(ValueError):
        generate(count=60, seed=11).utility(target="a_condition_no_patient_has")
