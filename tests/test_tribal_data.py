"""No shipped file names or points to a specific tribe or reservation.

See docs/TRIBAL_DATA.md. The names are checked by SHA-256 so this test does not
itself put them back into the repository.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from hipaasynth.sdk import PROFILE_ALIASES, _resolve_profile, available_profiles

ROOT = Path(__file__).resolve().parent.parent

#: First 16 hex digits of sha256(lowercase name) for tribal nations, reservations,
#: their counties and towns in the region the tribal profiles were drawn from.
DENY = frozenset({
    "00858ff0dc160f6a", "01fbd4bcd7b98bcf", "07911529b3c5d4ac", "0c76ba929e45b137",
    "22ecc2ad9baa434d", "25ba25a573a67c20", "43107916b5849d7d", "45f80706a1313406",
    "47356b6b6985b0b3", "51107fffea4ca27f", "556f07d09850995f", "5f92545a969abf54",
    "690a4ff24e7d9841", "6a73adb4fb8a7c25", "77979f24c707271f", "86bd5ac255747aed",
    "90c2f16deedb1b66", "92eaeb88996e521d", "94a2958581a85d22", "9a097094a661b09a",
    "9de723596261d153", "aa9326858af18bad", "aafcc1b356ff63ca", "ac58a5d7a2a7342c",
    "bec8720b38e01cf5", "c6f23675e5192a29", "d6f10e09978b8900", "da8b9c9054fd53ad",
    "e331993bb46dcc64", "e4c5da7a90e117ba", "e76a6366e6d293b0", "f298be4f6728f621",
    "f2ef961cdc192381", "f38f9304784e04a1", "fcb4c617e67ea98b",
})  # fmt: skip
TEXT = {".py", ".json", ".md", ".html", ".txt", ".csv", ".toml", ".cfg", ".yml", ".yaml", ".js"}
SKIP_DIRS = {".git", ".gitnexus", "node_modules", "__pycache__", ".venv", "venv", "build", "dist"}


def _files():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in TEXT and not SKIP_DIRS & set(path.parts):
            yield path


def _hits(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    found = set()
    for size in (1, 2, 3):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i : i + size])
            if hashlib.sha256(phrase.encode()).hexdigest()[:16] in DENY:
                found.add(phrase)
    return found


def test_no_shipped_file_names_a_tribe_or_reservation():
    bad = {}
    for path in _files():
        hits = _hits(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            bad[str(path.relative_to(ROOT))] = len(hits)  # the count, not the names
    assert not bad, f"tribal or reservation identifiers found (see docs/TRIBAL_DATA.md): {bad}"


@pytest.mark.parametrize("name", [n for n in available_profiles() if n.startswith("tribal_")])
def test_tribal_profiles_point_to_no_place(name):
    data = json.loads(Path(_resolve_profile(name)).read_text(encoding="utf-8"))
    text = json.dumps(data)
    assert "County" not in text and "county" not in text
    assert data.get("state") == "Northern Plains (US)"
    assert "nd_" not in data["profile_name"]


def test_former_profile_names_still_work():
    for old, new in PROFILE_ALIASES.items():
        assert _resolve_profile(old) == _resolve_profile(new)
        assert old not in available_profiles()
