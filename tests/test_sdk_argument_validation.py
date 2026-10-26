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

"""hipaasynth.generate() must validate count and seed like the REST API.

Regression guard: the SDK accepted seeds the API rejects (-1, 2**64...), and
count="5" / count=2.7 failed deep in the engine with unrelated TypeErrors
("'<' not supported between instances of 'str' and 'int'").
"""

import pytest

import hipaasynth
from hipaasynth.sdk import SEED_MAX


@pytest.mark.parametrize("seed", [-1, SEED_MAX + 1, 2**64])
def test_seed_out_of_range(seed):
    with pytest.raises(ValueError, match=f"seed must be between 0 and {SEED_MAX}"):
        hipaasynth.generate(count=1, seed=seed)


@pytest.mark.parametrize("seed", ["42", 4.2, True, None])
def test_seed_wrong_type(seed):
    with pytest.raises(TypeError, match="seed must be an integer"):
        hipaasynth.generate(count=1, seed=seed)


@pytest.mark.parametrize("count", ["5", 2.7, True, None])
def test_count_wrong_type(count):
    with pytest.raises(TypeError, match="count must be an integer"):
        hipaasynth.generate(count=count)


@pytest.mark.parametrize("count", [0, -3])
def test_count_below_one(count):
    with pytest.raises(ValueError, match="count must be >= 1"):
        hipaasynth.generate(count=count)


@pytest.mark.parametrize("seed", [0, 42, SEED_MAX])
def test_valid_bounds(seed):
    assert len(hipaasynth.generate(count=2, seed=seed)) == 2


def test_api_uses_the_same_seed_range():
    from hipaasynth.api import ApiError, parse_generate_request

    parse_generate_request({"seed": str(SEED_MAX)}, max_count=1000)
    with pytest.raises(ApiError):
        parse_generate_request({"seed": str(SEED_MAX + 1)}, max_count=1000)
