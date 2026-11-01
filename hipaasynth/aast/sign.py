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

"""Ed25519 signatures (RFC 8032) in the standard library: who issued a report.

The hash chain shows a report was not changed; a signature shows *whose key*
issued it. Each tester (or HipAAsynth, for reports it issues) keeps a private
key file; the public key and its fingerprint are printed on the report, and
anyone can check the signature with it.

This follows the RFC 8032 reference code and is checked against its test
vectors. It is plain Python: fine for signing a report on your own computer,
not a constant-time implementation for a shared server.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_Point = tuple[int, int, int, int]

KEY_FORMAT = "hipaasynth-ed25519-key/1"


class SignatureError(ValueError):
    """A key or signature that cannot be used."""


def _add(p: _Point, q: _Point) -> _Point:
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s: int, p: _Point) -> _Point:
    q: _Point = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(p: _Point, q: _Point) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, _P - 2, _P) % _P
_GX = _recover_x(_GY, 0) or 0
_G: _Point = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(p: _Point) -> bytes:
    zinv = pow(p[2], _P - 2, _P)
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(b: bytes) -> _Point | None:
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _h(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _expand(secret: bytes) -> tuple[int, bytes]:
    if len(secret) != 32:
        raise SignatureError("an Ed25519 private key is 32 bytes")
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return _compress(_mul(a, _G))


def sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(secret)
    pub = _compress(_mul(a, _G))
    r = _h(prefix + msg) % _L
    rs = _compress(_mul(r, _G))
    s = (r + _h(rs + pub + msg) * a) % _L
    return rs + int.to_bytes(s, 32, "little")


def verify(public: bytes, msg: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    k = _h(signature[:32] + public + msg) % _L
    return _equal(_mul(s, _G), _add(r, _mul(k, a)))


def fingerprint(public: bytes) -> str:
    """Short, readable id of a public key: the first 16 bytes of its SHA-256, grouped."""
    h = hashlib.sha256(public).hexdigest()[:32].upper()
    return " ".join(h[i : i + 4] for i in range(0, 32, 4))


# ------------------------------------------------------------- key files


def default_key_path() -> Path:
    return Path(
        os.environ.get("HIPAASYNTH_KEY") or Path.home() / ".hipaasynth" / "signing_key.json"
    )


def new_key(path: str | Path, *, signer: str = "", organization: str = "") -> dict[str, Any]:
    """Create a private key file (readable only by you); refuses to overwrite one."""
    path = Path(path)
    if path.exists():
        raise SignatureError(f"{path} already exists; keep using it or move it away first")
    secret = secrets.token_bytes(32)
    pub = public_key(secret)
    data = {
        "format": KEY_FORMAT,
        "algorithm": "ed25519",
        "signer": signer,
        "organization": organization,
        "public_key": pub.hex(),
        "private_key": secret.hex(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    return public_info(data)


def load_key(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise SignatureError(f"cannot read signing key {path}: {err}") from err
    if not isinstance(data, dict) or data.get("format") != KEY_FORMAT:
        raise SignatureError(f"{path} is not a HipAAsynth signing key")
    secret = bytes.fromhex(data["private_key"])
    if public_key(secret).hex() != data.get("public_key"):
        raise SignatureError(f"{path}: the public key does not match the private key")
    return data


def public_info(key: dict[str, Any]) -> dict[str, Any]:
    pub = bytes.fromhex(key["public_key"])
    return {
        "algorithm": "ed25519",
        "public_key": key["public_key"],
        "fingerprint": fingerprint(pub),
        "signer": key.get("signer", ""),
        "organization": key.get("organization", ""),
    }


def sign_hash(key: dict[str, Any], report_hash: str) -> dict[str, Any]:
    """A signature block over a report hash (the UTF-8 hex text is what is signed)."""
    sig = sign(bytes.fromhex(key["private_key"]), report_hash.encode("ascii"))
    return {**public_info(key), "signed": "report hash", "signature": sig.hex()}


def check_block(block: dict[str, Any], report_hash: str) -> tuple[bool, str]:
    try:
        pub = bytes.fromhex(block["public_key"])
        sig = bytes.fromhex(block["signature"])
    except (KeyError, TypeError, ValueError):
        return False, "signature block is unreadable"
    if block.get("fingerprint") != fingerprint(pub):
        return False, "the printed key fingerprint does not match the public key"
    if not verify(pub, report_hash.encode("ascii"), sig):
        return False, "signature does not match this report hash"
    who = ", ".join(x for x in (block.get("signer"), block.get("organization")) if x)
    return True, f"signed by key {block['fingerprint']}" + (f" ({who})" if who else "")
