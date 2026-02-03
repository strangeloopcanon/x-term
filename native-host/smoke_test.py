#!/usr/bin/env python3
from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
from pathlib import Path


def _send(fp, obj) -> None:
    data = json.dumps(obj).encode("utf-8")
    fp.write(struct.pack("<I", len(data)))
    fp.write(data)
    fp.flush()


def _recv(fp):
    raw_len = fp.read(4)
    if not raw_len:
        return None
    (msg_len,) = struct.unpack("<I", raw_len)
    data = fp.read(msg_len)
    if not data:
        return None
    return json.loads(data.decode("utf-8", errors="replace"))


def main() -> int:
    host = (Path(__file__).parent / "process_gate.py").resolve()
    proc = subprocess.Popen(
        [str(host), "--watch-stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin and proc.stdout

    t0 = time.time()
    first = None
    while time.time() - t0 < 3.0:
        first = _recv(proc.stdout)
        if first is not None:
            break

    if not first or "block_x" not in first:
        proc.terminate()
        print("FAIL: did not receive initial status", file=sys.stderr)
        return 1

    poll_id = 123
    _send(proc.stdin, {"type": "poll", "id": poll_id})

    t1 = time.time()
    reply = None
    while time.time() - t1 < 3.0:
        msg = _recv(proc.stdout)
        if not msg:
            continue
        if msg.get("reply_to") == poll_id:
            reply = msg
            break

    proc.terminate()

    if not reply:
        print("FAIL: did not receive poll reply", file=sys.stderr)
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

