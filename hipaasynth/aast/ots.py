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

"""OpenTimestamps in the standard library: prove a report existed by a date.

A report hash is sent to public OpenTimestamps calendars, which commit it into
the Bitcoin blockchain within a few hours. The proof is a standard ``.ots``
file, so anyone can check it with this module, the ``ots`` tool or
https://opentimestamps.org without trusting HipAAsynth.

* :func:`stamp` sends a SHA-256 digest to the calendars and returns a ``.ots``
  file (PENDING: the calendars have promised to commit it).
* :func:`upgrade` asks the calendars for the finished Bitcoin path (a few hours
  later) and returns the completed proof.
* :func:`info` replays the proof offline: which digest it covers, which
  calendars hold it, which Bitcoin blocks it reaches.
* :func:`verify_bitcoin` checks a Bitcoin attestation against the block's
  merkle root fetched from a block explorer, and returns the block time. For a
  check that trusts no one, compare with your own Bitcoin node.

The format follows python-opentimestamps (``DetachedTimestampFile``); the tests
check files against that library.
"""

from __future__ import annotations

import base64
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

#: Public calendars run by the OpenTimestamps project and Eternity Wall.
CALENDARS = (
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
)
#: Block explorers (Esplora API) used to read a block's merkle root.
EXPLORERS = ("https://blockstream.info/api", "https://mempool.space/api")

HEADER_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
MAJOR_VERSION = 1
OP_SHA256 = 0x08
PENDING_TAG = bytes.fromhex("83dfe30d2ef90c8e")
BITCOIN_TAG = bytes.fromhex("0588960d73d71901")
USER_AGENT = "HipAAsynth-7AAST (+https://github.com/hipaasynth-svg/HipAAsynth)"
_MAX_PAYLOAD = 8192
_MAX_DEPTH = 256


class OTSError(ValueError):
    """A proof that cannot be read, or a calendar or explorer that failed."""


# ------------------------------------------------------------------ the tree


def _unary(tag: int, msg: bytes) -> bytes:
    if tag == 0x08:
        return hashlib.sha256(msg).digest()
    if tag == 0x02:
        return hashlib.sha1(msg).digest()  # noqa: S324 - part of the OTS format
    if tag == 0x03:
        try:
            return hashlib.new("ripemd160", msg).digest()
        except ValueError as err:  # pragma: no cover - depends on the OpenSSL build
            raise OTSError("this Python cannot compute RIPEMD-160 for this proof") from err
    if tag == 0xF2:
        return msg[::-1]
    if tag == 0xF3:
        return msg.hex().encode()
    raise OTSError(f"unknown operation 0x{tag:02x}")


_UNARY = {0x08, 0x02, 0x03, 0xF2, 0xF3}
_BINARY = {0xF0, 0xF1}  # append, prepend


@dataclass
class Timestamp:
    """One message and what proves it: attestations and operations to more messages."""

    msg: bytes
    attestations: list[tuple[bytes, bytes]] = field(default_factory=list)  # (tag, payload)
    ops: dict[tuple[int, bytes], Timestamp] = field(default_factory=dict)

    def apply(self, tag: int, arg: bytes = b"") -> Timestamp:
        """The child reached by an operation (made if new)."""
        key = (tag, arg)
        if key not in self.ops:
            if tag == 0xF0:
                result = self.msg + arg
            elif tag == 0xF1:
                result = arg + self.msg
            else:
                result = _unary(tag, self.msg)
            self.ops[key] = Timestamp(result)
        return self.ops[key]

    def merge(self, other: Timestamp) -> None:
        if other.msg != self.msg:
            raise OTSError("cannot merge proofs of different messages")
        for att in other.attestations:
            if att not in self.attestations:
                self.attestations.append(att)
        for (tag, arg), child in other.ops.items():
            self.apply(tag, arg).merge(child)

    def leaves(self) -> list[tuple[bytes, bytes, bytes]]:
        """Every attestation as (message it attests, tag, payload)."""
        out = [(self.msg, tag, payload) for tag, payload in self.attestations]
        for child in self.ops.values():
            out.extend(child.leaves())
        return out


def _varuint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _varbytes(b: bytes) -> bytes:
    return _varuint(len(b)) + b


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.pos = data, 0

    def read(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise OTSError("proof ends early")
        out = self.data[self.pos : self.pos + n]
        self.pos += n
        return out

    def byte(self) -> int:
        return self.read(1)[0]

    def varuint(self) -> int:
        value, shift = 0, 0
        while True:
            b = self.byte()
            value |= (b & 0x7F) << shift
            if not b & 0x80:
                return value
            shift += 7
            if shift > 63:
                raise OTSError("number too large in proof")

    def varbytes(self, limit: int = _MAX_PAYLOAD) -> bytes:
        n = self.varuint()
        if n > limit:
            raise OTSError("field too large in proof")
        return self.read(n)


def _serialize(ts: Timestamp) -> bytes:
    items: list[bytes] = []
    for att_tag, payload in sorted(ts.attestations):
        items.append(b"\x00" + att_tag + _varbytes(payload))
    for (op, arg), child in sorted(ts.ops.items(), key=lambda kv: kv[0]):
        head = bytes([op]) + (_varbytes(arg) if op in _BINARY else b"")
        items.append(head + _serialize(child))
    if not items:
        raise OTSError("empty proof")
    return b"".join(b"\xff" + item for item in items[:-1]) + items[-1]


def _deserialize(reader: _Reader, msg: bytes, depth: int = 0) -> Timestamp:
    if depth > _MAX_DEPTH:
        raise OTSError("proof nests too deeply")
    ts = Timestamp(msg)

    def one(tag: int) -> None:
        if tag == 0x00:
            att_tag = reader.read(8)
            ts.attestations.append((att_tag, reader.varbytes()))
            return
        arg = reader.varbytes(4096) if tag in _BINARY else b""
        if tag not in _BINARY and tag not in _UNARY:
            raise OTSError(f"unknown operation 0x{tag:02x}")
        child = ts.apply(tag, arg)
        child.merge(_deserialize(reader, child.msg, depth + 1))

    tag = reader.byte()
    while tag == 0xFF:
        one(reader.byte())
        tag = reader.byte()
    one(tag)
    return ts


def serialize_file(ts: Timestamp) -> bytes:
    """A ``.ots`` file for a SHA-256 digest (``ts.msg``)."""
    if len(ts.msg) != 32:
        raise OTSError("the root of a proof must be a 32-byte SHA-256 digest")
    return HEADER_MAGIC + _varuint(MAJOR_VERSION) + bytes([OP_SHA256]) + ts.msg + _serialize(ts)


def parse_file(data: bytes) -> Timestamp:
    """Read a ``.ots`` file made for a SHA-256 digest."""
    reader = _Reader(data)
    if reader.read(len(HEADER_MAGIC)) != HEADER_MAGIC:
        raise OTSError("not an OpenTimestamps proof file")
    if reader.varuint() != MAJOR_VERSION:
        raise OTSError("unsupported OpenTimestamps version")
    if reader.byte() != OP_SHA256:
        raise OTSError("proof is not for a SHA-256 digest")
    ts = _deserialize(reader, reader.read(32))
    if reader.pos != len(data):
        raise OTSError("extra data after the proof")
    return ts


# --------------------------------------------------------------- the network


def _http(url: str, data: bytes | None, timeout: float) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.opentimestamps.v1"}
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")  # fmt: skip
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https URLs only
        return bytes(resp.read(1_000_000))


def stamp(
    digest: bytes, *, calendars: tuple[str, ...] | None = None, timeout: float = 15.0
) -> tuple[bytes, list[str]]:
    """Send ``digest`` to the calendars; return the ``.ots`` file and the calendars that took it.

    Raises :class:`OTSError` if no calendar answered.
    """
    if len(digest) != 32:
        raise OTSError("stamp a 32-byte SHA-256 digest")
    root = Timestamp(digest)
    took, errors = [], []
    for url in CALENDARS if calendars is None else calendars:
        try:
            body = _http(url.rstrip("/") + "/digest", digest, timeout)
            root.merge(_deserialize(_Reader(body), digest))
            took.append(url)
        except (urllib.error.URLError, OSError, OTSError) as err:
            errors.append(f"{url}: {err}")
    if not took:
        raise OTSError("no OpenTimestamps calendar answered (" + "; ".join(errors) + ")")
    return serialize_file(root), took


def upgrade(proof: bytes, *, timeout: float = 15.0) -> tuple[bytes, bool]:
    """Ask each pending calendar for its Bitcoin path; return (proof, changed)."""
    root = parse_file(proof)
    changed = False

    def walk(ts: Timestamp) -> None:
        nonlocal changed
        for tag, payload in list(ts.attestations):
            if tag != PENDING_TAG:
                continue
            uri = _pending_uri(payload)
            try:
                body = _http(f"{uri.rstrip('/')}/timestamp/{ts.msg.hex()}", None, timeout)
            except (urllib.error.URLError, OSError):
                continue  # not committed yet (404) or calendar unreachable
            ts.merge(_deserialize(_Reader(body), ts.msg))
            if any(t == BITCOIN_TAG for _, t, _ in ts.leaves()):
                ts.attestations.remove((tag, payload))
            changed = True
        for child in list(ts.ops.values()):
            walk(child)

    walk(root)
    return serialize_file(root), changed


def _pending_uri(payload: bytes) -> str:
    uri = _Reader(payload).varbytes(1000).decode("ascii", "replace")
    if not uri.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise OTSError(f"calendar address is not https: {uri!r}")
    return uri


# ------------------------------------------------------------------- reading


@dataclass
class ProofInfo:
    digest: str
    pending: list[str]
    bitcoin: list[tuple[int, str]]  # (block height, attested merkle root as hex, internal order)

    @property
    def status(self) -> str:
        return "BITCOIN" if self.bitcoin else ("PENDING" if self.pending else "EMPTY")


def info(proof: bytes) -> ProofInfo:
    """Replay a proof offline and say what it attests."""
    root = parse_file(proof)
    pending, bitcoin = [], []
    for msg, tag, payload in root.leaves():
        if tag == PENDING_TAG:
            pending.append(_pending_uri(payload))
        elif tag == BITCOIN_TAG:
            bitcoin.append((_Reader(payload).varuint(), msg.hex()))
    return ProofInfo(root.msg.hex(), sorted(set(pending)), sorted(set(bitcoin)))


def verify_bitcoin(
    proof: bytes, *, explorers: tuple[str, ...] | None = None, timeout: float = 15.0
) -> tuple[int, str]:
    """Check the proof's Bitcoin attestation against a block explorer.

    Returns (block height, block time as ISO-8601 UTC). Raises :class:`OTSError`
    when there is no Bitcoin attestation yet, or it does not match the block.
    """
    attested = info(proof).bitcoin
    if not attested:
        raise OTSError("the proof has no Bitcoin attestation yet; upgrade it in a few hours")
    errors = []
    for height, merkle in attested:
        for api in EXPLORERS if explorers is None else explorers:
            try:
                block_hash = _http(f"{api}/block-height/{height}", None, timeout).decode().strip()
                block = json.loads(_http(f"{api}/block/{block_hash}", None, timeout))
            except (urllib.error.URLError, OSError, ValueError) as err:
                errors.append(f"{api}: {err}")
                continue
            if bytes.fromhex(block["merkle_root"])[::-1].hex() != merkle:
                raise OTSError(f"block {height} does not contain this proof")
            when = datetime.fromtimestamp(int(block["timestamp"]), timezone.utc)
            return height, when.isoformat().replace("+00:00", "Z")
    raise OTSError("no block explorer answered (" + "; ".join(errors) + ")")


def encode(proof: bytes) -> str:
    return base64.b64encode(proof).decode("ascii")


def decode(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as err:
        raise OTSError("the stored proof is not valid base64") from err


def describe(proof: bytes, digest_hex: str) -> dict[str, Any]:
    """A JSON-ready summary for a report: status, calendars, blocks, and a digest check."""
    pi = info(proof)
    return {
        "status": pi.status,
        "covers_report_hash": pi.digest == digest_hex,
        "calendars": pi.pending,
        "bitcoin_blocks": [h for h, _ in pi.bitcoin],
    }
