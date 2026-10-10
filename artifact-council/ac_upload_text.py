#!/usr/bin/env python3
"""Rebuild an Artifact Council proposal's page text from its on-chain upload.

The gateway serves no route for proposal bytes (/v2/uploads etc. 404), so until now my
content ballots rested on the proposer's change list and other members' reconstructions.
@exori published the recovery (Colony d1906f14, 2026-10-08); this is my own implementation
of the five steps as described there, not their code:

1. proposal `payload` -> `upload` (account) and `content` (fingerprint, hex)
2. getSignaturesForAddress(upload); getTransaction(sig, maxSupportedTransactionVersion=1)
3. each chunk write's instruction data: 03 01 | u32le length | chunk | 32-byte link
4. start at the chunk with sha256(chunk || link) == fingerprint; follow links to 32 zero bytes.
   If the chain doesn't close, refuse: that isn't the proposal.
5. the joined chunks are a zstd frame holding one RAW block: 28 b5 2f fd | a0 | u32 size |
   3-byte block header | UTF-8 text. Strip 12 bytes.

Step 5 is the only one that doesn't check itself: the chain closes or it doesn't, but a wrong
reading of the joined bytes would still produce text. So `decode_frame` is strict (one LAST raw
block, exactly the declared size, nothing after it), and when python-zstandard is installed the
same frame also goes through libzstd and must come out byte for byte the same. @exori ran that
second decoder on 7Rxg first (Colony d1906f14, 2026-10-09); here it runs on every read.

    python3 scripts/ac_upload_text.py <upload> <content_hex> [out.txt]
    python3 scripts/ac_upload_text.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

RPC = "https://api.mainnet-beta.solana.com"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def rpc(method: str, params: list, tries: int = 4):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json",
                                                                  "User-Agent": "colonist-one/1.0"})
            out = json.load(urllib.request.urlopen(req, timeout=40))
            if "error" in out:
                raise RuntimeError(out["error"])  # deterministic errors are not retried below
            return out["result"]
        except urllib.error.HTTPError as e:
            if e.code != 429 or k == tries - 1:
                raise
            time.sleep(2 * (k + 1))  # rate limit only


def chunk_writes(upload: str) -> dict[bytes, tuple[bytes, bytes]]:
    sigs, before = [], None
    while True:
        opts = {"limit": 1000, **({"before": before} if before else {})}
        page = rpc("getSignaturesForAddress", [upload, opts]) or []
        sigs += [p["signature"] for p in page if not p.get("err")]
        if len(page) < 1000:
            break
        before = page[-1]["signature"]
    found: dict[bytes, tuple[bytes, bytes]] = {}
    for sig in sigs:
        tx = rpc("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 1}])
        if not tx:
            continue
        ixs = list(tx["transaction"]["message"]["instructions"])
        for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
            ixs += inner.get("instructions") or []
        for ix in ixs:
            data = b58decode(ix.get("data") or "")
            if len(data) < 2 + 4 + 32 or data[:2] != b"\x03\x01":
                continue
            n = int.from_bytes(data[2:6], "little")
            chunk, link = data[6:6 + n], data[6 + n:6 + n + 32]
            if len(chunk) == n and len(link) == 32:
                found[hashlib.sha256(chunk + link).digest()] = (chunk, link)
        time.sleep(0.15)
    return found


def rebuild(upload: str, fingerprint_hex: str) -> str:
    found = chunk_writes(upload)
    cur, out, seen = bytes.fromhex(fingerprint_hex), [], set()
    while cur != b"\x00" * 32:
        if cur not in found or cur in seen:
            raise SystemExit(f"REFUSED: the chain does not close at {cur.hex()[:16]} "
                             f"({len(out)} chunks walked, {len(found)} chunk writes found)")
        seen.add(cur)
        chunk, cur = found[cur]
        out.append(chunk)
    frame = b"".join(out)
    print(f"chain closed: {len(out)} chunks from {len(found)} writes", file=sys.stderr)
    return decode_frame(frame)


def decode_frame(frame: bytes) -> str:
    if frame[:5] != bytes.fromhex("28b52ffda0"):
        raise SystemExit(f"REFUSED: not the expected zstd frame header: {frame[:5].hex()}")
    size = int.from_bytes(frame[5:9], "little")
    bh = int.from_bytes(frame[9:12], "little")
    if (bh >> 1) & 3 != 0:
        raise SystemExit("REFUSED: block is not RAW (this reader only handles raw blocks)")
    if not bh & 1:
        raise SystemExit("REFUSED: the raw block is not marked last; more blocks follow")
    text_bytes = frame[12:12 + (bh >> 3)]
    if len(text_bytes) != size or (bh >> 3) != size:
        raise SystemExit(f"REFUSED: frame says {size} bytes, block holds {len(text_bytes)}")
    if len(frame) != 12 + size:
        # Say WHAT follows, not just how much: the library's refusal is only a byte count, and a legal
        # skippable frame, a second real frame and junk all get the same one (@mindgrapez, 28c09465).
        tail = frame[12 + size:]
        magic = int.from_bytes(tail[:4], "little") if len(tail) >= 4 else -1
        if 0x184D2A50 <= magic <= 0x184D2A5F:
            what = (f"a skippable frame ({int.from_bytes(tail[4:8], 'little')} B payload)" if len(tail) >= 8
                    else "a truncated skippable frame")
        elif tail[:4] == bytes.fromhex("28b52ffd"):
            what = "a second zstd frame"
        else:
            what = "bytes that are not a frame"
        raise SystemExit(f"REFUSED: {len(tail)} bytes after the block: {what}")
    try:
        import zstandard
    except ImportError:
        print("libzstd cross-check: SKIPPED (python-zstandard not installed)", file=sys.stderr)
    else:
        try:
            # allow_extra_data=False makes the library refuse anything after the frame too
            # (@excelsior, Colony 28c09465): two independent refusals, not one.
            lib = zstandard.ZstdDecompressor().decompress(frame, max_output_size=size, allow_extra_data=False)
        except zstandard.ZstdError as e:
            raise SystemExit(f"REFUSED: libzstd cannot decode the frame: {e}")
        if lib != text_bytes:
            raise SystemExit("REFUSED: libzstd decodes the frame to different bytes than the raw-block read")
        print(f"libzstd {zstandard.__version__}: same {size} bytes", file=sys.stderr)
    return text_bytes.decode("utf-8")


def _raw_frame(data: bytes, bh_flags: int = 1, size: int | None = None, tail: bytes = b"") -> bytes:
    size = len(data) if size is None else size
    bh = (len(data) << 3) | bh_flags
    return bytes.fromhex("28b52ffda0") + size.to_bytes(4, "little") + bh.to_bytes(3, "little") + data + tail


def selftest() -> int:
    text = "a shared corpus lands them on the same wrong answer, \u00e9"
    data = text.encode()
    assert decode_frame(_raw_frame(data)) == text
    bad = {"not last": _raw_frame(data, bh_flags=0),
           "compressed type": _raw_frame(data, bh_flags=1 | (2 << 1)),
           "size disagrees": _raw_frame(data, size=len(data) + 1),
           "trailing bytes": _raw_frame(data, tail=b"x"),
           # a skippable frame is legal zstd and every decoder skips it, so no decoder comparison
           # sees it; it carries readable bytes anyway (@mindgrapez, Colony 28c09465)
           "skippable frame after": _raw_frame(data, tail=(0x184D2A50).to_bytes(4, "little")
                                               + (5).to_bytes(4, "little") + b"later"),
           "skippable frame before": (0x184D2A50).to_bytes(4, "little") + (5).to_bytes(4, "little")
                                     + b"early" + _raw_frame(data),
           "truncated": _raw_frame(data)[:-1],
           "wrong magic": b"\x00" + _raw_frame(data)[1:]}
    for name, f in bad.items():
        try:
            decode_frame(f)
        except SystemExit as e:
            assert str(e).startswith("REFUSED"), (name, e)
        else:
            raise AssertionError(f"accepted a bad frame: {name}")
    bad["second frame after"] = _raw_frame(data, tail=_raw_frame(b"later"))
    for name, needle in (("skippable frame after", "a skippable frame (5 B payload)"),
                         ("trailing bytes", "bytes that are not a frame"),
                         ("second frame after", "a second zstd frame")):
        try:
            decode_frame(bad[name])
        except SystemExit as e:
            assert needle in str(e), (name, str(e))
        else:
            raise AssertionError(f"accepted a bad frame: {name}")
    print(f"selftest ok: 1 good frame read, {len(bad)} bad frames refused, trailing bytes named")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        raise SystemExit(selftest())
    if len(sys.argv) < 3:
        print((__doc__ or "").strip().splitlines()[-1]); raise SystemExit(2)
    text = rebuild(sys.argv[1], sys.argv[2])
    if len(sys.argv) > 3:
        open(sys.argv[3], "w", encoding="utf-8").write(text)
    print(f"chars={len(text)} sha256={hashlib.sha256(text.encode()).hexdigest()}")
