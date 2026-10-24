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

"""The CLI must answer ordinary mistakes with one line, not a traceback.

Regression guard: ``--count 0``, a missing or malformed profile, and an
``--out`` that is a file all crashed with Python tracebacks; ``--profile``
rejected bundled names (``karachi_pakistan``) that the API and SDK accept; and
out-of-range seeds were accepted although the API rejects them.
"""

import pytest

from hipaasynth.run.main import SEED_MAX, main


def _usage_error(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    err = capsys.readouterr().err
    assert exc.value.code == 2
    assert "Traceback" not in err
    return err


@pytest.mark.parametrize("count", ["0", "-5"])
def test_count_below_one(capsys, tmp_path, count):
    err = _usage_error(capsys, ["--count", count, "--out", str(tmp_path)])
    assert "--count: must be >= 1" in err


@pytest.mark.parametrize("seed", ["-1", str(SEED_MAX + 1), "99999999999999999999"])
def test_seed_out_of_range(capsys, tmp_path, seed):
    err = _usage_error(capsys, ["--seed", seed, "--out", str(tmp_path)])
    assert f"--seed: must be between 0 and {SEED_MAX}" in err


def test_unknown_profile_lists_bundled_names(capsys, tmp_path):
    err = _usage_error(capsys, ["--profile", "nope", "--out", str(tmp_path)])
    assert "unknown profile 'nope'" in err and "nd_tribal_region_a" in err


def test_malformed_profile(capsys, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    err = _usage_error(capsys, ["--profile", str(bad), "--out", str(tmp_path / "o")])
    assert "cannot load profile" in err


def test_out_is_a_file(capsys, tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    err = _usage_error(capsys, ["--count", "2", "--out", str(f)])
    assert "exists and is not a directory" in err


def test_bundled_profile_name_works(tmp_path):
    assert main(["--profile", "karachi_pakistan", "--module", "dka", "--count", "3",
                 "--out", str(tmp_path)]) == 0
    assert (tmp_path / "cohort.json").is_file()


def test_bundled_name_and_path_give_identical_output(tmp_path):
    import hipaasynth
    from pathlib import Path

    path = Path(hipaasynth.__file__).resolve().parent / "profiles" / "minot_nd.json"
    main(["--profile", "minot_nd", "--count", "3", "--out", str(tmp_path / "a")])
    main(["--profile", str(path), "--count", "3", "--out", str(tmp_path / "b")])
    assert (tmp_path / "a" / "cohort.csv").read_text() == (tmp_path / "b" / "cohort.csv").read_text()


def test_runtime_error_is_one_line(capsys, tmp_path, monkeypatch):
    import hipaasynth.run.main as cli

    def boom(cfg):
        raise OSError("disk full")

    monkeypatch.setattr(cli, "generate_patients", boom)
    assert main(["--count", "2", "--out", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "hipaasynth: error: disk full"


def test_seed_bounds_accepted(tmp_path):
    assert main(["--seed", "0", "--count", "1", "--out", str(tmp_path / "a")]) == 0
    assert main(["--seed", str(SEED_MAX), "--count", "1", "--out", str(tmp_path / "b")]) == 0
