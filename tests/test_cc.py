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

"""Tests for the CC (Care Continuity) adversarial axis."""

import pytest

from hipaasynth.core.model_interface import MockClinicalModel
from hipaasynth.cc import CCAudit, CCConfig, CCGenerator, CONTINUITY_PROFILES
from hipaasynth.cc.report import CCReport


class TestCCGenerator:
    def test_generate_returns_correct_count(self) -> None:
        gen = CCGenerator(seed=42)
        for profile in CONTINUITY_PROFILES:
            patients = gen.generate(n=10, profile=profile)
            assert len(patients) == 10, f"Expected 10 at {profile}"

    def test_profile_field_is_set(self) -> None:
        gen = CCGenerator(seed=42)
        for profile in CONTINUITY_PROFILES:
            patients = gen.generate(n=5, profile=profile)
            for p in patients:
                assert p["continuity_profile"] == profile

    def test_profile_a_has_full_clinical_record(self) -> None:
        gen = CCGenerator(seed=42)
        patients = gen.generate(n=5, profile="PROFILE_A")
        for p in patients:
            clinical = p.get("clinical", {})
            assert clinical.get("pcp_id") is not None
            assert clinical.get("labs_available") is True
            assert clinical.get("medication_reconciled") is True

    def test_profile_d_has_sparse_clinical_record(self) -> None:
        gen = CCGenerator(seed=42)
        patients = gen.generate(n=5, profile="PROFILE_D")
        for p in patients:
            clinical = p.get("clinical", {})
            assert clinical.get("pcp_id") is None
            assert clinical.get("labs_available") is False
            assert clinical.get("provider_count") == 0

    def test_invalid_profile_raises(self) -> None:
        gen = CCGenerator(seed=42)
        with pytest.raises(ValueError, match="Unknown continuity profile"):
            gen.generate(n=5, profile="PROFILE_Z")

    def test_determinism(self) -> None:
        gen1 = CCGenerator(seed=77)
        gen2 = CCGenerator(seed=77)
        for profile in CONTINUITY_PROFILES:
            assert gen1.generate(10, profile) == gen2.generate(10, profile)

    def test_generate_all_profiles_keys(self) -> None:
        gen = CCGenerator(seed=42)
        cohort = gen.generate_all_profiles(n_per_profile=5)
        assert set(cohort.keys()) == set(CONTINUITY_PROFILES)

    def test_matched_pair_shares_demographics(self) -> None:
        gen = CCGenerator(seed=42)
        pair = gen.generate_matched_pair(base_seed=100)
        assert "PROFILE_A" in pair and "PROFILE_D" in pair
        pa = pair["PROFILE_A"]
        pd = pair["PROFILE_D"]
        assert pa["age"] == pd["age"]
        assert pa["sex"] == pd["sex"]
        assert pa["race_ethnicity"] == pd["race_ethnicity"]


class TestCCAudit:
    def test_cdi_computed_correctly(self) -> None:
        """CDI = mean_score(PROFILE_D) / mean_score(PROFILE_A) — verify arithmetic."""
        model = MockClinicalModel(seed=42)
        audit = CCAudit()
        result = audit.run(model, CCConfig(n_per_profile=20, seed=42))

        d = result.per_profile_scores["PROFILE_D"]
        a = result.per_profile_scores["PROFILE_A"]
        expected_cdi = round(d / a, 4)
        assert abs(result.cdi - expected_cdi) < 1e-6

    def test_profile_d_scores_lower_than_profile_a(self) -> None:
        """PROFILE_D must score lower than PROFILE_A."""
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=30, seed=42))
        assert result.per_profile_scores["PROFILE_D"] < result.per_profile_scores["PROFILE_A"], (
            f"PROFILE_D ({result.per_profile_scores['PROFILE_D']:.4f}) should be"
            f" < PROFILE_A ({result.per_profile_scores['PROFILE_A']:.4f})"
        )

    def test_scores_decrease_from_a_to_d(self) -> None:
        """Mean score should be non-increasing from PROFILE_A to PROFILE_D."""
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=30, seed=42))
        scores = [result.per_profile_scores[p] for p in CONTINUITY_PROFILES]
        for i in range(len(scores) - 1):
            assert (
                scores[i] >= scores[i + 1] - 0.05
            ), f"Score inversion at {CONTINUITY_PROFILES[i]} vs {CONTINUITY_PROFILES[i+1]}"

    def test_cdi_fails_for_biased_model(self) -> None:
        """MockClinicalModel completeness for PROFILE_D is near 0; CDI should FAIL."""
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=50, seed=42))
        assert not result.cdi_pass, "MockClinicalModel should FAIL the CDI threshold"
        assert result.cdi < 0.80

    def test_transition_deltas_mostly_positive(self) -> None:
        """Most deltas (score_A − score_D) should be positive — model rewards completeness."""
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=50, n_matched_pairs=30, seed=42))
        positive = sum(1 for d in result.transition_deltas if d > 0)
        assert (
            positive > len(result.transition_deltas) * 0.7
        ), f"Only {positive}/{len(result.transition_deltas)} deltas positive"

    def test_mean_transition_delta_positive(self) -> None:
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=50, n_matched_pairs=30, seed=42))
        assert (
            result.mean_transition_delta > 0
        ), f"Expected positive mean delta, got {result.mean_transition_delta}"

    def test_result_raw_scores_length(self) -> None:
        model = MockClinicalModel(seed=42)
        n = 15
        result = CCAudit().run(model, CCConfig(n_per_profile=n, seed=42))
        for profile in CONTINUITY_PROFILES:
            assert len(result.raw_scores[profile]) == n

    def test_transition_deltas_count(self) -> None:
        model = MockClinicalModel(seed=42)
        n_pairs = 12
        result = CCAudit().run(model, CCConfig(n_per_profile=10, n_matched_pairs=n_pairs, seed=42))
        assert len(result.transition_deltas) == n_pairs


class TestCCReport:
    def test_report_markdown_structure(self) -> None:
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=10, seed=42))
        report = CCReport(result)
        md = report.to_markdown()
        assert "# HipAAsynth — Care Continuity (CC) Report" in md
        assert "Continuity Degradation Index" in md
        assert "PASS" in md or "FAIL" in md
        assert "synthetic" in md.lower()

    def test_report_contains_all_profiles(self) -> None:
        model = MockClinicalModel(seed=42)
        result = CCAudit().run(model, CCConfig(n_per_profile=10, seed=42))
        md = CCReport(result).to_markdown()
        for profile in CONTINUITY_PROFILES:
            assert profile in md
