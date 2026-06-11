#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
Minimal MLLP target — simulates what AION's MLLP listener would do.

For testing the SILD filter without a real AION instance.
Listens on a TCP port, accepts MLLP-framed HL7 messages, replies with ACK.

N-2 Fix: --response-mode aa|ae|ar steuert den ACK-Code.
  aa   (Standard) — immer Application Accept
  ae               — immer Application Error (NAK-AE, testet K-2)
  ar               — immer Application Reject
  flap <N>         — wechselt nach je N Nachrichten zwischen AA und AE
                     (testet Retry-Logik des Senders)

Damit koennen End-to-End-Tests des K-2-Fixes (MLLP-NAK-AE) durchgefuehrt werden.

Usage:
    python sild_mllp_target.py --listen 2576
    python sild_mllp_target.py --listen 2576 --response-mode ae
    python sild_mllp_target.py --listen 2576 --response-mode flap --flap-n 3

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import socket
import threading
from datetime import datetime, timezone


VT, FS, CR = b"\x0b", b"\x1c", b"\x0d"


def wrap_mllp(message_text: str) -> bytes:
    return VT + message_text.encode("utf-8", errors="replace") + FS + CR


def read_mllp_message(sock, timeout=10.0):
    sock.settimeout(timeout)
    buffer = bytearray()
    state  = "wait_start"
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
                    state = "in_message"
                    buffer.clear()
            elif state == "in_message":
                if b == FS:
                    state = "wait_cr"
                else:
                    buffer.append(byte)
            elif state == "wait_cr":
                if b == CR:
                    return buffer.decode("utf-8", errors="replace")
                return buffer.decode("utf-8", errors="replace")


def make_ack(msg_text: str, code: str = "AA", reason: str = "") -> str:
    """
    Erzeugt HL7 v2 ACK-Antwort.

    N-2 Fix: code kann 'AA', 'AE' oder 'AR' sein.
    Bei 'AE' wird ein ERR-Segment eingefuegt (wie der SILD-Filter in K-2),
    damit der Sender den Unterschied zu einem einfachen AA erkennt.
    """
    segments   = msg_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    msh        = segments[0].split("|") if segments else []
    sending_app = msh[2]  if len(msh) > 2  else "X"
    sending_fac = msh[3]  if len(msh) > 3  else "X"
    msg_type    = msh[8]  if len(msh) > 8  else "ACK"
    control_id  = msh[9]  if len(msh) > 9  else "0"
    version     = msh[11] if len(msh) > 11 else "2.5"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    msh_out = (
        f"MSH|^~\\&|AION_MOCK|HOSPITAL|{sending_app}|{sending_fac}|{ts}||"
        f"ACK|{control_id}|P|{version}"
    )
    msa_out = f"MSA|{code}|{control_id}|{reason}"

    if code in ("AE", "AR"):
        # N-2: NAK mit ERR-Segment (spiegelt K-2-Verhalten des SILD-Filters)
        err_code = "207^Application Internal Error^HL70357" if code == "AE" else "204^Primary Key Value - PID^HL70357"
        err_out = f"ERR||{err_code}|E|{reason or 'Mock NAK'}"
        return msh_out + "\r" + msa_out + "\r" + err_out + "\r"

    return msh_out + "\r" + msa_out + "\r"


def _resolve_ack_code(mode: str, flap_n: int, msg_count: int) -> tuple:
    """
    N-2: Berechnet ACK-Code und Begruendung anhand des Response-Mode.
    Gibt (ack_code, reason) zurueck.
    """
    if mode == "aa":
        return "AA", ""
    elif mode == "ae":
        return "AE", "Mock: Application Error (--response-mode ae)"
    elif mode == "ar":
        return "AR", "Mock: Application Reject (--response-mode ar)"
    elif mode == "flap":
        # Wechselt alle flap_n Nachrichten zwischen AA und AE.
        # (msg_count - 1) damit die erste Gruppe voll flap_n Nachrichten hat.
        cycle = ((msg_count - 1) // max(flap_n, 1)) % 2
        if cycle == 0:
            return "AA", ""
        else:
            return "AE", f"Mock: Flap AE (Nachricht {msg_count}, flap-n={flap_n})"
    return "AA", ""


def handle(client, addr, counter, lock, mode: str, flap_n: int):
    try:
        while True:
            msg = read_mllp_message(client)
            if msg is None:
                break

            with lock:
                counter[0] += 1
                n = counter[0]

            segments   = msg.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            msh        = segments[0].split("|") if segments else []
            msg_type   = msh[8] if len(msh) > 8 else "?"
            control_id = msh[9] if len(msh) > 9 else "?"
            n_segs     = len([s for s in segments if s.strip()])

            ack_code, reason = _resolve_ack_code(mode, flap_n, n)
            flag = {"AA": "OK  ", "AE": "NAK-AE", "AR": "NAK-AR"}.get(ack_code, ack_code)

            print(
                f"[AION-Mock] #{n} from {addr[0]}: {msg_type} id={control_id} "
                f"({n_segs} segs) -> {flag}"
            )
            client.sendall(wrap_mllp(make_ack(msg, code=ack_code, reason=reason)))

    except Exception as e:
        print(f"[AION-Mock] {addr} error: {e}")
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description="Minimal MLLP target (AION mock)")
    parser.add_argument("--listen", type=int, default=2576,
                        help="Listen port (default: 2576)")
    # N-2 Fix: Response-Mode
    parser.add_argument("--response-mode",
                        choices=["aa", "ae", "ar", "flap"],
                        default="aa",
                        help=(
                            "ACK-Code-Modus (N-2): "
                            "aa=immer Accept (Standard), "
                            "ae=immer Application Error (testet K-2 NAK-AE), "
                            "ar=immer Application Reject, "
                            "flap=wechselt AA/AE alle --flap-n Nachrichten"
                        ))
    parser.add_argument("--flap-n", type=int, default=5,
                        help="Nachrichten pro Phase bei --response-mode flap (default: 5)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", args.listen))
    sock.listen(20)
    sock.settimeout(1.0)

    counter = [0]
    lock    = threading.Lock()

    mode_info = {
        "aa":   "immer AA (Application Accept)",
        "ae":   "immer AE (Application Error / NAK, K-2-Test)",
        "ar":   "immer AR (Application Reject)",
        "flap": f"wechselnd AA/AE alle {args.flap_n} Nachrichten",
    }.get(args.response_mode, args.response_mode)

    print(f"[AION-Mock] Listening on tcp://0.0.0.0:{args.listen}")
    print(f"[AION-Mock] Response-Mode: {mode_info}")
    print(f"[AION-Mock] Press Ctrl-C to stop\n")

    try:
        while True:
            try:
                client, addr = sock.accept()
            except socket.timeout:
                continue
            t = threading.Thread(
                target=handle,
                args=(client, addr, counter, lock, args.response_mode, args.flap_n),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        print(f"\n[AION-Mock] Total received: {counter[0]}")
        sock.close()


if __name__ == "__main__":
    main()
