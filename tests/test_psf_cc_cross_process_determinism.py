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

"""PSF (Axis 6) and CC (Axis 7) must be reproducible across processes.

Regression guard: both generators seeded their RNGs with Python's built-in
``hash(str)``, which is salted per process (PYTHONHASHSEED). The same seed gave
a different cohort and a different SDI/CDI in every new interpreter, while
in-process determinism checks (examples/psf_demo.py, examples/cc_demo.py) still
passed. These tests run the audits in separate interpreters with *different*
hash salts and require byte-identical results.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_SCRIPT = r"""
import json
from hipaasynth import CCAudit, CCConfig, PSFAudit, PSFConfig, ScoredMockModel
from hipaasynth.cc.generator import CCGenerator
from hipaasynth.psf.generator import PSFGenerator

psf = PSFAudit().run(ScoredMockModel(), PSFConfig(n_per_level=8, seed=42))
cc = CCAudit().run(ScoredMockModel(), CCConfig(n_per_profile=8, n_matched_pairs=4, seed=42))
print(json.dumps({
    "psf_cohort": PSFGenerator(seed=42).generate_all_levels(n_per_level=4),
    "cc_cohort": CCGenerator(seed=42).generate_all_profiles(n_per_profile=4),
    "cc_pair": CCGenerator(seed=42).generate_matched_pair(base_seed=7),
    "sdi": psf.sdi,
    "psf_raw": psf.raw_scores,
    "cdi": cc.cdi,
    "cc_raw": cc.raw_scores,
    "cc_deltas": cc.transition_deltas,
}, sort_keys=True, default=str))
"""


def _run(hash_seed: str) -> dict:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(_REPO_ROOT)}
    out = subprocess.run(
        [sys.executable, "-c", _SCRIPT],
        capture_output=True, text=True, env=env, cwd=_REPO_ROOT, timeout=120, check=True,
    )
    return json.loads(out.stdout)


@pytest.fixture(scope="module")
def runs():
    return [_run(s) for s in ("0", "1", "12345")]


@pytest.mark.parametrize(
    "key", ["psf_cohort", "cc_cohort", "cc_pair", "sdi", "psf_raw", "cdi", "cc_raw", "cc_deltas"]
)
def test_identical_across_hash_salts(runs, key):
    first = runs[0][key]
    for other in runs[1:]:
        assert other[key] == first, f"{key} differs between interpreter runs"


def test_generators_do_not_use_builtin_hash():
    for rel in ("hipaasynth/psf/generator.py", "hipaasynth/cc/generator.py"):
        src = (_REPO_ROOT / rel).read_text()
        assert " hash(" not in src and "^ hash(" not in src, f"{rel} uses process-salted hash()"
