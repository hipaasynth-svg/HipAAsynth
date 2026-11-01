"""A stand-in OpenTimestamps calendar and block explorer for tests (no internet).

The calendar answers ``POST /digest`` like the public ones (append a nonce,
SHA-256, a pending attestation) and, once :attr:`FakeCalendar.mined` is set,
``GET /timestamp/<commitment>`` with a Bitcoin path. The explorer serves the
matching block, Esplora-style.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hipaasynth.aast import ots

NONCE = b"\x5a" * 16
HEIGHT = 912345
BLOCK_TIME = 1793500000  # 2026-11-01


def _pending(uri: str) -> bytes:
    uri_b = uri.encode()
    payload = ots._varbytes(uri_b)
    return (
        bytes([0xF0])
        + ots._varbytes(NONCE)
        + bytes([0x08])
        + b"\x00"
        + ots.PENDING_TAG
        + (ots._varbytes(payload))
    )


def _bitcoin_path() -> bytes:
    # prepend, sha256, append, sha256 (a two-leaf merkle path), then the block attestation
    return (
        bytes([0xF1]) + ots._varbytes(b"\x11" * 32) + bytes([0x08])
        + bytes([0xF0]) + ots._varbytes(b"\x22" * 32) + bytes([0x08])
        + b"\x00" + ots.BITCOIN_TAG + ots._varbytes(ots._varuint(HEIGHT))
    )  # fmt: skip


def merkle_root(commitment: bytes) -> bytes:
    """The internal-order merkle root the Bitcoin path above reaches."""
    m = hashlib.sha256(b"\x11" * 32 + commitment).digest()
    return hashlib.sha256(m + b"\x22" * 32).digest()


class FakeCalendar:
    def __init__(self) -> None:
        self.mined = False
        self.digests: list[bytes] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code: int, body: bytes, ctype: str = "application/octet-stream"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/digest" and len(body) == 32:
                    outer.digests.append(body)
                    return self._send(200, _pending(outer.url))
                self._send(400, b"bad")

            def do_GET(self):
                if self.path.startswith("/timestamp/"):
                    if not outer.mined:
                        return self._send(404, b"Pending confirmation in Bitcoin blockchain")
                    return self._send(200, _bitcoin_path())
                if self.path.startswith("/api/block-height/"):
                    return self._send(200, b"00000000000000000000blockhash", "text/plain")
                if self.path.startswith("/api/block/"):
                    digest = outer.digests[-1]
                    commitment = hashlib.sha256(digest + NONCE).digest()
                    block = {"merkle_root": merkle_root(commitment)[::-1].hex(),
                             "timestamp": BLOCK_TIME, "height": HEIGHT}  # fmt: skip
                    return self._send(200, json.dumps(block).encode(), "application/json")
                self._send(404, b"no")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
