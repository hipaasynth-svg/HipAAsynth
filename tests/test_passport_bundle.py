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

"""The readable deliverable for a full audit run: one file per patient,
cross-linked to a cohort summary. Guards that the two never drift apart.
"""
import re

import pytest

from hipaasynth.dif import run_audit, summarize_cohort, write_passport_bundle
from hipaasynth.dif.report import FairnessPassport, _safe_filename_stem
from hipaasynth.polymorphic.metrics import PolymorphicMetrics


def _passing_metrics():
    return PolymorphicMetrics(
        dcs=1.0, isg=0.0, lfdi=0.0, saf=0.0,
        dcs_pass=True, isg_pass=True, lfdi_pass=True, saf_pass=True,
    )


class TestWritePassportBundle:
    def test_writes_one_file_per_patient_plus_a_summary(
        self, tmp_path, gen_config, biased_model, dif_config
    ):
        from hipaasynth.pipelines.population_pipeline import generate_patients

        passports = run_audit(biased_model, generate_patients, gen_config, dif_config)
        result = write_passport_bundle(passports, tmp_path / "bundle")

        assert result["n"] == len(passports) == gen_config.patient_count
        assert result["summary_path"].exists()
        assert len(result["patient_paths"]) == len(passports)
        for path in result["patient_paths"].values():
            assert path.exists()

    def test_summary_links_resolve_to_files_with_matching_content(
        self, tmp_path, gen_config, biased_model, dif_config
    ):
        from hipaasynth.pipelines.population_pipeline import generate_patients

        passports = run_audit(biased_model, generate_patients, gen_config, dif_config)
        out = tmp_path / "bundle"
        write_passport_bundle(passports, out)

        summary_text = (out / "summary.md").read_text(encoding="utf-8")
        rows = re.findall(
            r"\| (\S+) \| (PASS|FAIL) \| \[\S+\]\((patients/[^)]+\.md)\) \|", summary_text
        )
        assert len(rows) == len(passports), "every patient must appear exactly once in the index"

        for patient_id, verdict, rel_path in rows:
            target = out / rel_path
            assert target.exists(), f"summary links to {rel_path} but it was never written"
            body = target.read_text(encoding="utf-8")
            assert patient_id in body
            assert "back to cohort summary" in body
            file_verdict = "PASS" if "**Overall result:** PASS" in body else "FAIL"
            assert file_verdict == verdict, (
                f"{rel_path}: summary claims {verdict}, the file itself says {file_verdict}"
            )

    def test_patients_directory_has_no_orphans_and_no_gaps(
        self, tmp_path, gen_config, fair_model, dif_config
    ):
        from hipaasynth.pipelines.population_pipeline import generate_patients

        passports = run_audit(fair_model, generate_patients, gen_config, dif_config)
        out = tmp_path / "bundle"
        write_passport_bundle(passports, out)

        on_disk = {p.stem for p in (out / "patients").glob("*.md")}
        expected = {_safe_filename_stem(p.patient_id) for p in passports}
        assert on_disk == expected

    def test_empty_cohort_raises(self, tmp_path):
        with pytest.raises(ValueError, match="empty cohort"):
            write_passport_bundle([], tmp_path / "bundle")

    def test_duplicate_patient_id_raises_rather_than_overwriting(self, tmp_path):
        m = _passing_metrics()
        p1 = FairnessPassport.build("D", "1", "SAME-ID", True, {"f": True}, m)
        p2 = FairnessPassport.build("D", "1", "SAME-ID", True, {"f": True}, m)
        with pytest.raises(ValueError, match="duplicate patient_id"):
            write_passport_bundle([p1, p2], tmp_path / "bundle")

    def test_mismatched_precomputed_summary_raises(
        self, tmp_path, gen_config, fair_model, dif_config
    ):
        from hipaasynth.pipelines.population_pipeline import generate_patients

        passports = run_audit(fair_model, generate_patients, gen_config, dif_config)
        wrong_summary = summarize_cohort(passports)  # describes the full cohort
        with pytest.raises(ValueError, match="summary.n"):
            write_passport_bundle(passports[:1], tmp_path / "bundle", summary=wrong_summary)

    def test_precomputed_summary_that_matches_is_accepted(
        self, tmp_path, gen_config, fair_model, dif_config
    ):
        from hipaasynth.pipelines.population_pipeline import generate_patients

        passports = run_audit(fair_model, generate_patients, gen_config, dif_config)
        right_summary = summarize_cohort(passports)
        result = write_passport_bundle(passports, tmp_path / "bundle", summary=right_summary)
        assert result["n"] == len(passports)

    def test_safe_filename_stem_sanitizes_unsafe_characters(self):
        assert _safe_filename_stem("SYN-abc123") == "SYN-abc123"
        # Every unsafe character is replaced 1:1 with "_", so a non-empty input
        # never collapses to an empty stem -- it just gets uglier, never unsafe.
        assert _safe_filename_stem("../../etc/passwd") == ".._.._etc_passwd"
        assert _safe_filename_stem("///") == "___"
        with pytest.raises(ValueError, match="no safe characters"):
            _safe_filename_stem("   ")
