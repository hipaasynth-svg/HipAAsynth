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

"""Tests for the PSF (Population Sparsity Fairness) adversarial axis."""

import pytest

from hipaasynth.core.model_interface import MockClinicalModel, ScoredMockModel
from hipaasynth.psf import PSFAudit, PSFConfig, PSFGenerator, SPARSITY_LEVELS
from hipaasynth.psf.report import PSFReport


class TestPSFGenerator:
    def test_generate_returns_correct_count(self) -> None:
        gen = PSFGenerator(seed=42)
        for level in SPARSITY_LEVELS:
            patients = gen.generate(n=10, sparsity_level=level)
            assert len(patients) == 10, f"Expected 10 at {level}"

    def test_sparsity_level_field_is_set(self) -> None:
        gen = PSFGenerator(seed=42)
        for level in SPARSITY_LEVELS:
            patients = gen.generate(n=5, sparsity_level=level)
            for p in patients:
                assert p["sparsity_level"] == level

    def test_s1_has_minimal_fields(self) -> None:
        gen = PSFGenerator(seed=42)
        patients = gen.generate(n=5, sparsity_level="S1")
        required = {
            "patient_id",
            "sparsity_level",
            "age",
            "sex",
            "race_ethnicity",
            "geography_type",
            "chief_complaint",
        }
        forbidden = {
            "current_labs",
            "comorbidities",
            "visit_history",
            "lab_history",
            "ses_proxy",
            "insurance_type",
        }
        for p in patients:
            assert required.issubset(p.keys()), f"S1 missing required fields: {required - p.keys()}"
            for f in forbidden:
                assert f not in p, f"S1 should not have {f!r}"

    def test_s7_has_all_fields(self) -> None:
        gen = PSFGenerator(seed=42)
        patients = gen.generate(n=5, sparsity_level="S7")
        required = {
            "current_labs",
            "primary_dx",
            "comorbidities",
            "visit_history",
            "lab_history",
            "ses_proxy",
            "insurance_type",
        }
        for p in patients:
            assert required.issubset(p.keys()), f"S7 missing fields: {required - p.keys()}"

    def test_invalid_level_raises(self) -> None:
        gen = PSFGenerator(seed=42)
        with pytest.raises(ValueError, match="Unknown sparsity level"):
            gen.generate(n=5, sparsity_level="S99")

    def test_determinism(self) -> None:
        gen1 = PSFGenerator(seed=99)
        gen2 = PSFGenerator(seed=99)
        for level in SPARSITY_LEVELS:
            assert gen1.generate(10, level) == gen2.generate(10, level)

    def test_generate_all_levels_keys(self) -> None:
        gen = PSFGenerator(seed=42)
        cohort = gen.generate_all_levels(n_per_level=5)
        assert set(cohort.keys()) == set(SPARSITY_LEVELS)


class TestPSFAudit:
    def test_sdi_computed_correctly(self) -> None:
        """SDI = mean_score(S1) / mean_score(S7) — verify arithmetic."""
        model = MockClinicalModel(seed=42)
        audit = PSFAudit()
        result = audit.run(model, PSFConfig(n_per_level=20, seed=42))

        s1 = result.per_level_scores["S1"]
        s7 = result.per_level_scores["S7"]
        expected_sdi = round(s1 / s7, 4)
        assert abs(result.sdi - expected_sdi) < 1e-6

    def test_scores_decrease_with_sparsity(self) -> None:
        """Mean score must be monotonically non-increasing from S7 to S1."""
        model = MockClinicalModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=30, seed=42))
        scores = [result.per_level_scores[lvl] for lvl in reversed(SPARSITY_LEVELS)]
        # Each level should be >= the next (S7 >= S6 >= ... >= S1).
        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1] - 0.05, (
                f"Score inversion at levels {list(reversed(SPARSITY_LEVELS))[i]}"
                f" vs {list(reversed(SPARSITY_LEVELS))[i+1]}"
            )

    def test_sdi_fails_for_biased_model(self) -> None:
        """
        MockClinicalModel returns completeness * 0.90 at each level.
        S1 completeness = 0.10, S7 = 1.00 → SDI ≈ 0.10 / 0.90 ≈ 0.11.
        This should be a FAIL (< 0.80 threshold).
        """
        model = MockClinicalModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=50, seed=42))
        assert not result.sdi_pass, "MockClinicalModel should FAIL the SDI threshold"
        assert result.sdi < 0.80

    def test_demographic_scores_present_for_each_level(self) -> None:
        model = MockClinicalModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=30, seed=42))
        for level in SPARSITY_LEVELS:
            assert level in result.demographic_scores
            assert len(result.demographic_scores[level]) > 0

    def test_scored_model_shows_demographic_sparsity_interaction(self) -> None:
        """
        ScoredMockModel penalises AIAN patients (−0.06) and Frontier/Tribal
        geography (−0.03) while rewarding White patients (+0.03).
        At S1 this penalty is more visible because completeness is only 0.10.
        AIAN mean score at S1 must be lower than White mean score at S1.
        """
        model = ScoredMockModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=200, seed=42))
        demo_s1 = result.demographic_scores.get("S1", {})
        aian_score = demo_s1.get("American Indian or Alaska Native")
        white_score = demo_s1.get("White")
        assert aian_score is not None, "AIAN group not found at S1"
        assert white_score is not None, "White group not found at S1"
        assert (
            aian_score < white_score
        ), f"Expected AIAN ({aian_score:.4f}) < White ({white_score:.4f}) at S1"

    def test_result_raw_scores_length(self) -> None:
        model = MockClinicalModel(seed=42)
        n = 15
        result = PSFAudit().run(model, PSFConfig(n_per_level=n, seed=42))
        for level in SPARSITY_LEVELS:
            assert len(result.raw_scores[level]) == n


class TestPSFReport:
    def test_report_markdown_structure(self) -> None:
        model = MockClinicalModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=10, seed=42))
        report = PSFReport(result)
        md = report.to_markdown()
        assert "# HipAAsynth — Population Sparsity Fairness (PSF) Report" in md
        assert "Sparsity Degradation Index" in md
        assert "PASS" in md or "FAIL" in md
        assert "synthetic" in md.lower()

    def test_report_contains_all_levels(self) -> None:
        model = MockClinicalModel(seed=42)
        result = PSFAudit().run(model, PSFConfig(n_per_level=10, seed=42))
        md = PSFReport(result).to_markdown()
        for level in SPARSITY_LEVELS:
            assert level in md
