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

"""PSF (Axis 6) and CC (Axis 7) must reject unusable scores and empty runs.

Regression guard: a model returning NaN produced SDI/CDI 0.0 (FAIL) with no
explanation; negative scores were averaged into a meaningless ratio; ``None``
or a string crashed deep inside ``sum()`` with a bare TypeError; and
``n_per_level=0`` returned SDI 0.0 (FAIL) instead of an error.
"""

import math

import pytest

from hipaasynth import CCAudit, CCConfig, MockClinicalModel, PSFAudit, PSFConfig
from hipaasynth.core.model_interface import ModelInterface, validate_model_score


class _Const(ModelInterface):
    def __init__(self, value):
        self.value = value

    def evaluate(self, patient):
        return self.value


_SMALL_PSF = PSFConfig(n_per_level=3)
_SMALL_CC = CCConfig(n_per_profile=3, n_matched_pairs=2)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_non_finite_or_negative_scores_raise_value_error(bad):
    with pytest.raises(ValueError, match="finite, non-negative"):
        PSFAudit().run(_Const(bad), _SMALL_PSF)
    with pytest.raises(ValueError, match="finite, non-negative"):
        CCAudit().run(_Const(bad), _SMALL_CC)


@pytest.mark.parametrize("bad", [None, "0.9", True, [0.5]])
def test_non_numeric_scores_raise_type_error(bad):
    with pytest.raises(TypeError, match="expected a finite, non-negative number"):
        PSFAudit().run(_Const(bad), _SMALL_PSF)
    with pytest.raises(TypeError, match="expected a finite, non-negative number"):
        CCAudit().run(_Const(bad), _SMALL_CC)


def test_error_message_says_where():
    with pytest.raises(ValueError, match=r"PSF level S1, patient 0"):
        PSFAudit().run(_Const(math.nan), _SMALL_PSF)


@pytest.mark.parametrize("ok", [0, 0.0, 0.5, 1, 1.0, 7.5])
def test_valid_scores_accepted(ok):
    assert validate_model_score(ok, "x") == float(ok)
    PSFAudit().run(_Const(ok), _SMALL_PSF)
    CCAudit().run(_Const(ok), _SMALL_CC)


def test_constant_model_shows_no_degradation_at_any_scale():
    # A constant score means record completeness does not change the output.
    assert PSFAudit().run(_Const(2.5), _SMALL_PSF).sdi == 1.0
    assert CCAudit().run(_Const(0.4), _SMALL_CC).cdi == 1.0


@pytest.mark.parametrize("n", [0, -1, 1.5, True])
def test_psf_rejects_empty_or_invalid_sizes(n):
    with pytest.raises(ValueError, match="n_per_level"):
        PSFConfig(n_per_level=n)


@pytest.mark.parametrize("field", ["n_per_profile", "n_matched_pairs"])
@pytest.mark.parametrize("n", [0, -3])
def test_cc_rejects_empty_sizes(field, n):
    with pytest.raises(ValueError, match=field):
        CCConfig(**{field: n})


def test_reference_results_unchanged():
    assert PSFAudit().run(MockClinicalModel(), PSFConfig()).sdi == pytest.approx(0.1003)
    assert CCAudit().run(MockClinicalModel(), CCConfig()).cdi == pytest.approx(0.2704)
