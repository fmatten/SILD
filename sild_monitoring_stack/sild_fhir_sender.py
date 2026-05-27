#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
FHIR test sender + continuous load generator.

Reads FHIR Bundle JSON files from a directory and POSTs them to an HTTP
endpoint. Two modes:

  --once    Send each file once and exit (default)
  --loop    Loop continuously, random selection, with optional bursts

Usage:
    # Single round
    python sild_fhir_sender.py --target http://localhost:8080 --dir samples_fhir/

    # Continuous load for live demo
    python sild_fhir_sender.py --target http://localhost:8080 --dir samples_fhir/ \\
        --loop --rate 1.5 --burst

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


def post_bundle(target: str, body_bytes: bytes, timeout: float = 5.0) -> tuple[bool, int, str]:
    url = target.rstrip("/") + "/fhir/Bundle"
    try:
        req = urllib.request.Request(
            url, data=body_bytes, method="POST",
            headers={"Content-Type": "application/fhir+json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, e.code, body
    except Exception as e:
        return False, 0, f"{type(e).__name__}: {e}"


def vary_bundle(template: dict, counter: int) -> dict:
    """Give every send a unique bundle id + timestamp."""
    out = dict(template)  # shallow copy is enough for top-level fields
    out["id"] = f"demo-{counter:06d}-{uuid.uuid4().hex[:8]}"
    out["timestamp"] = datetime.now().isoformat(timespec="seconds")
    return out


def short_summary(bundle: dict) -> str:
    entries = bundle.get("entry", [])
    types = {}
    for e in entries:
        rt = e.get("resource", {}).get("resourceType", "?")
        types[rt] = types.get(rt, 0) + 1
    parts = [f"{n}x{t}" for t, n in sorted(types.items())]
    return f"{len(entries)} entries [{', '.join(parts)}]"


def parse_outcome(body: str) -> str:
    """Try to extract OperationOutcome diagnostic message."""
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if obj.get("resourceType") == "OperationOutcome":
        issues = obj.get("issue", [])
        if issues:
            return issues[0].get("diagnostics", "") or issues[0].get("code", "")
    return ""


def send_round(target: str, files: list[Path], counter: int, status: dict) -> int:
    for path in files:
        try:
            template = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[FHIR-Sender] {path.name}: cannot parse: {e}")
            status["errors"] += 1
            continue

        counter += 1
        bundle = vary_bundle(template, counter)
        body = json.dumps(bundle, ensure_ascii=False).encode("utf-8")

        ok, code, resp = post_bundle(target, body)
        summary = short_summary(bundle)
        if ok and 200 <= code < 300:
            status["accepted"] += 1
            print(f"[FHIR-Sender] #{counter} {path.name} ({summary}) -> HTTP {code}")
        elif code in (422, 4):
            outcome = parse_outcome(resp)
            status["rejected"] += 1
            print(f"[FHIR-Sender] #{counter} {path.name} ({summary}) -> HTTP {code}: {outcome}")
        else:
            status["errors"] += 1
            outcome = parse_outcome(resp) if resp else ""
            print(f"[FHIR-Sender] #{counter} {path.name} ({summary}) -> ERROR HTTP {code}: {outcome or resp[:80]}")
        status["sent"] += 1
    return counter


def main():
    parser = argparse.ArgumentParser(description="FHIR sender + load generator")
    parser.add_argument("--target", required=True, help="Base URL, e.g. http://localhost:8080")
    parser.add_argument("--dir", type=str, default="samples_fhir",
                        help="Directory with *.json FHIR Bundle files")
    parser.add_argument("--file", type=str, default=None, help="Single FHIR Bundle file")
    parser.add_argument("--once", action="store_true", help="Send once and exit (default)")
    parser.add_argument("--loop", action="store_true", help="Loop continuously")
    parser.add_argument("--rate", type=float, default=1.0, help="Messages per second (loop mode)")
    parser.add_argument("--burst", action="store_true", help="Random bursts in loop mode")
    parser.add_argument("--interval", type=float, default=0.2,
                        help="Sleep between messages (once mode)")
    args = parser.parse_args()

    files: list[Path] = []
    if args.file:
        files.append(Path(args.file))
    if args.dir:
        files.extend(sorted(Path(args.dir).glob("*.json")))
    if not files:
        sys.exit("No FHIR Bundle files found")

    print(f"[FHIR-Sender] Target: {args.target}")
    print(f"[FHIR-Sender] Files:  {[f.name for f in files]}")

    counter = 0
    status = {"sent": 0, "accepted": 0, "rejected": 0, "errors": 0}

    if args.loop:
        print(f"[FHIR-Sender] Mode: loop (rate={args.rate}/s, {'burst' if args.burst else 'steady'})")
        print(f"[FHIR-Sender] Press Ctrl-C to stop\n")
        interval = 1.0 / max(args.rate, 0.01)
        last_status = time.time()
        try:
            while True:
                burst_size = random.randint(1, 5) if args.burst else 1
                pick = random.sample(files, k=min(burst_size, len(files)))
                if len(pick) < burst_size:
                    pick = pick + [random.choice(files) for _ in range(burst_size - len(pick))]
                counter = send_round(args.target, pick, counter, status)

                if time.time() - last_status >= 5.0:
                    print(f"[FHIR-Sender] sent={status['sent']}  accepted={status['accepted']}  "
                          f"rejected={status['rejected']}  errors={status['errors']}")
                    last_status = time.time()

                wait = interval * burst_size
                if args.burst:
                    wait = wait * random.uniform(1.5, 3.0)
                time.sleep(wait)
        except KeyboardInterrupt:
            print(f"\n[FHIR-Sender] Stopping. {status}")
    else:
        # Send once
        print(f"[FHIR-Sender] Mode: once (interval={args.interval}s)\n")
        for path in files:
            counter = send_round(args.target, [path], counter, status)
            if args.interval > 0:
                time.sleep(args.interval)
        print(f"\n[FHIR-Sender] Done. {status}")


if __name__ == "__main__":
    main()
