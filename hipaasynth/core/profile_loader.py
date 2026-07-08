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

import json
import os
from typing import Any


class ProfileError(ValueError):
    """Raised when a population profile is missing required fields or has invalid values."""


# Population profiles are small hand-authored JSON files (the bundled ones are
# 4–7 KB). This bound (1 MiB, ~140x the largest real profile) rejects a
# pathologically large or wrong-file input before it is read into memory, so a
# malformed pipeline output or a malicious oversized file cannot exhaust memory
# during parsing. It cannot reject any legitimate profile.
MAX_PROFILE_BYTES = 1024 * 1024


def _validate_age_band(band: dict, index: int) -> tuple[int, int, float]:
    """Validate and normalize a single age-band entry."""
    if not isinstance(band, dict):
        raise ProfileError(f"age_bands[{index}] must be an object, got {type(band).__name__}")
    for key in ("min", "max", "weight"):
        if key not in band:
            raise ProfileError(f"age_bands[{index}] is missing '{key}'")
    try:
        lo = int(band["min"])
        hi = int(band["max"])
        weight = float(band["weight"])
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"age_bands[{index}] has non-numeric fields: {band}") from exc
    if lo < 0 or hi < lo:
        raise ProfileError(f"age_bands[{index}] has invalid range: ({lo}, {hi})")
    if weight < 0.0:
        raise ProfileError(f"age_bands[{index}] weight must be non-negative: {weight}")
    return lo, hi, weight


def _normalize_age_bands(data: dict) -> list[tuple[int, int, float]]:
    """Convert age_bands or age_band_weights into a normalized list of tuples."""
    if "age_band_weights" in data:
        raw = data["age_band_weights"]
        if not isinstance(raw, list):
            raise ProfileError("age_band_weights must be a list")
        return [(_int_band_field(b, 0), _int_band_field(b, 1), _float_band_field(b, 2)) for b in raw]
    if "age_bands" in data:
        raw = data["age_bands"]
        if not isinstance(raw, list):
            raise ProfileError("age_bands must be a list")
        return [_validate_age_band(b, i) for i, b in enumerate(raw)]
    return []


def _int_band_field(band: Any, index: int) -> int:
    if not isinstance(band, (list, tuple)) or len(band) < 3:
        raise ProfileError(f"Invalid age_band_weights entry: {band!r}")
    try:
        return int(band[index])
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"age_band_weights entry has non-integer field: {band!r}") from exc


def _float_band_field(band: Any, index: int) -> float:
    if not isinstance(band, (list, tuple)) or len(band) < 3:
        raise ProfileError(f"Invalid age_band_weights entry: {band!r}")
    try:
        return float(band[index])
    except (TypeError, ValueError) as exc:
        raise ProfileError(f"age_band_weights entry has non-numeric weight: {band!r}") from exc


def _validate_weights(weights: Any) -> dict[str, float]:
    """Validate ethnicity_weights dict."""
    if weights is None:
        return {}
    if not isinstance(weights, dict):
        raise ProfileError(f"ethnicity_weights must be a dict, got {type(weights).__name__}")
    for key, value in weights.items():
        if not isinstance(key, str):
            raise ProfileError(f"ethnicity_weights key must be a string: {key!r}")
        try:
            float(value)
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"ethnicity_weights['{key}'] must be numeric: {value!r}") from exc
    return dict(weights)


def load_population_profile(path: str) -> dict:
    """
    Load and validate a population profile JSON file.

    Raises:
        FileNotFoundError: if the profile file does not exist.
        ProfileError: if the file exceeds MAX_PROFILE_BYTES, or required fields
            are missing or values are invalid.
        json.JSONDecodeError: if the file is not valid JSON.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Population profile not found: {path}")

    size = os.path.getsize(path)
    if size > MAX_PROFILE_BYTES:
        raise ProfileError(
            f"Population profile too large: {size} bytes exceeds the "
            f"{MAX_PROFILE_BYTES}-byte limit ({path})"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ProfileError(f"Profile root must be a JSON object, got {type(data).__name__}")

    # Validate optional ethnicity weights
    data["ethnicity_weights"] = _validate_weights(data.get("ethnicity_weights"))

    # Normalize and validate age bands
    age_band_weights = _normalize_age_bands(data)
    if age_band_weights:
        total = sum(weight for _, _, weight in age_band_weights)
        if not 0.99 <= total <= 1.01:
            raise ProfileError(f"age band weights must sum to 1.0, got {total}")
    data["age_band_weights"] = age_band_weights

    # Validate sex ratio if present
    sex_ratio = data.get("sex_ratio_female")
    if sex_ratio is not None:
        try:
            sex_ratio = float(sex_ratio)
        except (TypeError, ValueError) as exc:
            raise ProfileError(f"sex_ratio_female must be numeric: {sex_ratio!r}") from exc
        if not 0.0 <= sex_ratio <= 1.0:
            raise ProfileError(f"sex_ratio_female must be between 0.0 and 1.0, got {sex_ratio}")
        data["sex_ratio_female"] = sex_ratio

    return data
