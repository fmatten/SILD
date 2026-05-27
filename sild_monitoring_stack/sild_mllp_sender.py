#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
MLLP test sender — simulates a KIS/LIS sending HL7 v2 messages.

Reads HL7 messages from a directory or single file, opens an MLLP connection
to the target port, sends each with proper framing, waits for ACK.

Usage:
    # Send all *.hl7 files from samples/ once
    python sild_mllp_sender.py --target localhost:2575 --dir samples/

    # Send a single file with repetition for stress test
    python sild_mllp_sender.py --target localhost:2575 \\
        --file samples/oru_r01_sepsis.hl7 --repeat 5 --interval 0.5

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import socket
import sys
import time
from pathlib import Path


VT, FS, CR = b"\x0b", b"\x1c", b"\x0d"


def wrap_mllp(message_text: str) -> bytes:
    # Normalize: HL7 segments must end with \r
    normalized = message_text.replace("\r\n", "\r").replace("\n", "\r")
    if not normalized.endswith("\r"):
        normalized += "\r"
    return VT + normalized.encode("utf-8", errors="replace") + FS + CR


def read_mllp_response(sock, timeout=5.0):
    sock.settimeout(timeout)
    buffer = bytearray()
    state = "wait_start"
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            return None
        if not chunk:
            return None
        for byte in chunk:
            b = bytes([byte])
            if state == "wait_start":
                if b == VT:
                    state = "in_message"; buffer.clear()
            elif state == "in_message":
                if b == FS:
                    state = "wait_cr"
                else:
                    buffer.append(byte)
            elif state == "wait_cr":
                if b == CR:
                    return buffer.decode("utf-8", errors="replace")
                return buffer.decode("utf-8", errors="replace")


def parse_ack(ack_text: str) -> tuple[str, str]:
    """Return (ack_code, ack_text). Defaults to ('?', '') if MSA missing."""
    for line in ack_text.replace("\r", "\n").split("\n"):
        if line.startswith("MSA"):
            f = line.split("|")
            return f[1] if len(f) > 1 else "?", f[3] if len(f) > 3 else ""
    return "?", ""


def msg_summary(text: str) -> str:
    first = text.replace("\r\n", "\n").replace("\r", "\n").split("\n", 1)[0]
    fields = first.split("|")
    msg_type = fields[8] if len(fields) > 8 else "?"
    msg_id = fields[9] if len(fields) > 9 else "?"
    return f"{msg_type} id={msg_id}"


def send_one(target_host: str, target_port: int, message_text: str,
             timeout: float = 5.0) -> tuple[bool, str, str]:
    try:
        with socket.create_connection((target_host, target_port), timeout=timeout) as s:
            s.sendall(wrap_mllp(message_text))
            ack = read_mllp_response(s, timeout=timeout)
            if ack is None:
                return False, "?", "no ACK"
            code, text = parse_ack(ack)
            return code == "AA", code, text
    except Exception as e:
        return False, "?", f"connection error: {type(e).__name__}: {e}"


def main():
    parser = argparse.ArgumentParser(description="MLLP test sender")
    parser.add_argument("--target", required=True, help="host:port of MLLP receiver")
    parser.add_argument("--dir", type=str, default=None, help="Directory with *.hl7 files")
    parser.add_argument("--file", type=str, default=None, help="Single HL7 file")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat count per message")
    parser.add_argument("--interval", type=float, default=0.2, help="Seconds between messages")
    args = parser.parse_args()

    if not args.dir and not args.file:
        sys.exit("Provide --dir or --file")
    if ":" not in args.target:
        sys.exit("--target must be host:port")
    host, port = args.target.rsplit(":", 1)
    port = int(port)

    files: list[Path] = []
    if args.file:
        files.append(Path(args.file))
    if args.dir:
        files.extend(sorted(Path(args.dir).glob("*.hl7")))

    if not files:
        sys.exit("No HL7 files found")

    print(f"[Sender] Target: {host}:{port}")
    print(f"[Sender] Files:  {len(files)} (each repeated {args.repeat}x, {args.interval}s interval)\n")

    sent = 0
    accepted = 0
    rejected = 0
    errors = 0

    for path in files:
        msg = path.read_text(encoding="utf-8", errors="replace")
        for r in range(args.repeat):
            sent += 1
            ok, code, text = send_one(host, port, msg)
            summary = msg_summary(msg)
            if ok:
                accepted += 1
                print(f"[Sender] #{sent} {path.name} ({summary}) -> ACK={code}")
            else:
                if code in {"AE", "AR"}:
                    rejected += 1
                    print(f"[Sender] #{sent} {path.name} ({summary}) -> {code}: {text}")
                else:
                    errors += 1
                    print(f"[Sender] #{sent} {path.name} ({summary}) -> ERROR: {text}")
            if args.interval > 0:
                time.sleep(args.interval)

    print(f"\n[Sender] Done. Sent={sent} Accepted={accepted} Rejected={rejected} Errors={errors}")


if __name__ == "__main__":
    main()
