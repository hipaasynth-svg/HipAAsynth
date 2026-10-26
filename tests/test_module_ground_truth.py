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

"""Every decision module must actually produce the condition it is named for.

Regression guard: ``MODULES["sepsis"]`` used to map to ``None`` (no required
condition), so every front door's ``module=sepsis`` — the default for the API,
the SDK and the web UI — produced a general population with zero septic
patients. With no positive ground truth, the DIF audit cannot detect
under-triage, and the web UI's demo showed the built-in *biased* model passing
every patient.
"""

import pytest

from hipaasynth.api import build_config, parse_generate_request
from hipaasynth.dif import DIFConfig, run_audit
from hipaasynth.dif.model_interface import MockBiasedModel, _ground_truth
from hipaasynth.pipelines.population_pipeline import generate_patients
from hipaasynth.scenarios import load_scenarios
from hipaasynth.sdk import MODULES, available_profiles, generate


@pytest.mark.parametrize("module", sorted(MODULES))
def test_every_module_requests_a_condition(module):
    assert MODULES[module] is not None, f"module {module!r} requests no condition"


@pytest.mark.parametrize("profile", available_profiles())
@pytest.mark.parametrize("module", sorted(MODULES))
def test_every_module_yields_positive_ground_truth_on_every_profile(module, profile):
    cohort = generate(count=40, seed=3, module=module, profile=profile)
    positives = sum(_ground_truth(p) for p in cohort)
    assert positives > 0, f"{module} on {profile}: no positive ground-truth patients"


def test_sepsis_module_patients_all_carry_sepsis():
    cohort = generate(count=25, seed=42, module="sepsis")
    assert all(any(c.name == "sepsis" for c in p.conditions) for p in cohort)
    assert all((p.observations or {}).get("sepsis_flag") for p in cohort)


def _biased_demo_pass_count(params):
    req = parse_generate_request({**params, "count": "20"}, max_count=10_000)
    passports = run_audit(
        MockBiasedModel(), generate_patients, build_config(req), DIFConfig(device_name="demo")
    )
    return sum(p.passed() for p in passports), len(passports)


def test_default_web_demo_biased_model_fails():
    # /viz/fairness with no module/scenario uses the default module (sepsis).
    passed, total = _biased_demo_pass_count({"model": "biased"})
    assert passed == 0, f"biased model passed {passed}/{total} on the default demo"


@pytest.mark.parametrize(
    "scenario", sorted(n for n, s in load_scenarios().items() if s.module == "sepsis")
)
def test_sepsis_scenarios_expose_the_biased_model(scenario):
    passed, total = _biased_demo_pass_count({"model": "biased", "scenario": scenario})
    assert passed == 0, f"{scenario}: biased model passed {passed}/{total}"


def test_cohort_repr_does_not_invent_a_module():
    from datetime import date

    from hipaasynth.core.config import GenerationConfig
    from hipaasynth.sdk import Cohort

    cfg = GenerationConfig(patient_count=1, seed=1, run_date=date.today().isoformat())
    assert "module=None" in repr(Cohort(generate_patients(cfg), cfg))
