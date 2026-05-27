#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
Kontinuierlicher Lastgenerator fuer die SILD-Live-Demo.

Sendet zufaellig ausgewaehlte HL7-Nachrichten in einer Endlosschleife an
den SILD-Filter, um auf dem Grafana-Dashboard kontinuierliche Aktivitaet
zu zeigen.

M-7 Fix (FM-4 §6): Latenz-Monitoring hinzugefuegt.
  - send_one() gibt Laufzeit in Sekunden zurueck
  - Rolling Window (letzte 1000 Messungen) fuer Perzentil-Berechnung
  - Statistik-Ausgabe zeigt p50/p95/p99 in ms

Usage:
    python load_generator.py --target localhost:2575 --rate 2.0
"""

import argparse
import collections
import random
import socket
import sys
import time
from pathlib import Path
from datetime import datetime


VT, FS, CR = b"\x0b", b"\x1c", b"\x0d"


def wrap_mllp(message_text: str) -> bytes:
    normalized = message_text.replace("\r\n", "\r").replace("\n", "\r")
    if not normalized.endswith("\r"):
        normalized += "\r"
    return VT + normalized.encode("utf-8", errors="replace") + FS + CR


def read_mllp_response(sock, timeout=5.0):
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


def vary_message(template: str, counter: int) -> str:
    """Vary the control ID and timestamp so every message is unique."""
    lines = template.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        return template
    msh = lines[0].split("|")
    if len(msh) > 9:
        msh[9] = f"DEMO-{counter:06d}"
    if len(msh) > 6:
        msh[6] = datetime.now().strftime("%Y%m%d%H%M%S")
    lines[0] = "|".join(msh)
    return "\r".join(lines)


def send_one(
    host: str, port: int, message_text: str, timeout: float = 5.0
) -> tuple:
    """
    Sendet eine MLLP-Nachricht und gibt (ok, code, latency_s) zurück.

    M-7 Fix (FM-4 §6): Latenz wird mit time.perf_counter() gemessen
    (monotoner Hochauflösungs-Timer, besser als time.time()).
    Latenz wird auch bei Fehler zurückgegeben.
    """
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(wrap_mllp(message_text))
            ack = read_mllp_response(s, timeout=timeout)
            latency = time.perf_counter() - t0
            if ack is None:
                return False, "no ACK", latency
            for line in ack.replace("\r", "\n").split("\n"):
                if line.startswith("MSA"):
                    parts = line.split("|")
                    code  = parts[1] if len(parts) > 1 else "?"
                    return (code == "AA"), code, latency
            return False, "no MSA", latency
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", time.perf_counter() - t0


def _percentile(sorted_data: list, p: float) -> float:
    """Berechnet das p-te Perzentil einer sortierten Liste."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    k = (n - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, n - 1)
    return sorted_data[lo] + (k - lo) * (sorted_data[hi] - sorted_data[lo])


def main():
    parser = argparse.ArgumentParser(description="Continuous SILD MLLP load generator")
    parser.add_argument("--target",  required=True, help="host:port of MLLP receiver")
    parser.add_argument("--dir",     type=str, default="samples",
                        help="Directory with *.hl7 files")
    parser.add_argument("--rate",    type=float, default=1.0,
                        help="Messages per second (avg)")
    parser.add_argument("--burst",   action="store_true",
                        help="Random bursts (1 to 5 msgs at once, then idle)")
    parser.add_argument("--latency-warn-ms", type=float, default=2.0,
                        help="Warnschwelle fuer p99-Latenz in ms (FM-4 §6: <2ms)")
    args = parser.parse_args()

    if ":" not in args.target:
        sys.exit("--target must be host:port")
    host, port_str = args.target.rsplit(":", 1)
    port = int(port_str)

    files = sorted(Path(args.dir).glob("*.hl7"))
    if not files:
        sys.exit(f"No HL7 files in {args.dir}/")

    templates = [(p.name, p.read_text(encoding="utf-8", errors="replace")) for p in files]

    print(f"[LoadGen] Target: {host}:{port}")
    print(f"[LoadGen] Templates: {[n for n, _ in templates]}")
    print(f"[LoadGen] Rate: {args.rate}/s {'(bursty)' if args.burst else '(steady)'}")
    print(f"[LoadGen] p99-Warnschwelle: {args.latency_warn_ms}ms (FM-4 §6)")
    print(f"[LoadGen] Press Ctrl-C to stop\n")

    counter      = 0
    sent         = 0
    accepted     = 0
    rejected     = 0
    errors       = 0
    interval     = 1.0 / max(args.rate, 0.01)
    last_status  = time.time()

    # M-7: Rolling Window für p50/p95/p99-Berechnung (letzte 1000 Messungen)
    latency_window: collections.deque = collections.deque(maxlen=1000)

    try:
        while True:
            burst_size = random.randint(1, 5) if args.burst else 1
            for _ in range(burst_size):
                counter += 1
                name, template = random.choice(templates)
                msg = vary_message(template, counter)

                # M-7: Latenz messen
                ok, code, lat_s = send_one(host, port, msg)
                latency_window.append(lat_s)
                sent += 1

                if ok:
                    accepted += 1
                else:
                    if code in {"AE", "AR"}:
                        rejected += 1
                    else:
                        errors += 1

            # Periodic status line mit Latenz-Perzentilen (M-7)
            if time.time() - last_status >= 5.0:
                lat_str = ""
                if latency_window:
                    sorted_lat = sorted(latency_window)
                    p50 = _percentile(sorted_lat, 50) * 1000
                    p95 = _percentile(sorted_lat, 95) * 1000
                    p99 = _percentile(sorted_lat, 99) * 1000
                    lat_str = (
                        f"  lat p50={p50:.2f}ms p95={p95:.2f}ms "
                        f"p99={p99:.2f}ms"
                    )
                    # FM-4 §6: Warnung wenn p99 > Schwellwert
                    if p99 > args.latency_warn_ms:
                        lat_str += f" [WARN: p99>{args.latency_warn_ms}ms]"
                print(
                    f"[LoadGen] sent={sent}  accepted={accepted}  "
                    f"rejected={rejected}  errors={errors}{lat_str}"
                )
                last_status = time.time()

            # Warte
            wait = interval * burst_size
            if args.burst:
                wait = wait * random.uniform(1.5, 3.0)
            time.sleep(wait)

    except KeyboardInterrupt:
        # Abschluss-Statistik mit Latenz
        lat_summary = ""
        if latency_window:
            sorted_lat = sorted(latency_window)
            p50 = _percentile(sorted_lat, 50) * 1000
            p95 = _percentile(sorted_lat, 95) * 1000
            p99 = _percentile(sorted_lat, 99) * 1000
            lat_summary = (
                f"  Latenz: p50={p50:.2f}ms p95={p95:.2f}ms p99={p99:.2f}ms"
            )
            if p99 <= args.latency_warn_ms:
                lat_summary += f" [OK: p99<{args.latency_warn_ms}ms, FM-4 §6]"
            else:
                lat_summary += f" [WARN: p99>{args.latency_warn_ms}ms, FM-4 §6]"
        print(
            f"\n[LoadGen] Stopping. Total sent={sent}  accepted={accepted}  "
            f"rejected={rejected}  errors={errors}{lat_summary}"
        )


if __name__ == "__main__":
    main()
