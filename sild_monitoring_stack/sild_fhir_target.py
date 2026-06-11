#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
Mock FHIR endpoint - simulates AION's FHIR plugin.

Accepts POST /fhir/Bundle and POST /Bundle with FHIR JSON, returns a
transaction-response Bundle with HTTP 200. For local testing of the
SILD FHIR filter without a real AION instance.

Usage:
    python sild_fhir_target.py --listen 8081

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import json
import socketserver
import threading
import uuid
from http.server import BaseHTTPRequestHandler


class MockFHIRHandler(BaseHTTPRequestHandler):
    counter = [0]
    lock = threading.Lock()

    def log_message(self, format, *args):
        pass

    def _write_json(self, status: int, body: dict):
        b = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path in ("/health", "/ready"):
            self._write_json(200, {"status": "ok", "service": "aion-fhir-mock"})
            return
        self._write_json(404, {"resourceType": "OperationOutcome",
                                "issue": [{"severity": "error", "code": "not-found"}]})

    def do_POST(self):
        if self.path not in ("/fhir/Bundle", "/Bundle"):
            self._write_json(404, {"resourceType": "OperationOutcome",
                                    "issue": [{"severity": "error", "code": "not-found"}]})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length > 0 else b""

        try:
            bundle = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"resourceType": "OperationOutcome",
                                    "issue": [{"severity": "error", "code": "structure"}]})
            return

        with self.lock:
            self.counter[0] += 1
            n = self.counter[0]

        entries = bundle.get("entry", [])
        bundle_id = bundle.get("id", "?")
        bundle_type = bundle.get("type", "?")
        print(f"[AION-FHIR-Mock] #{n} from {self.client_address[0]}: "
              f"Bundle/{bundle_type} id={bundle_id} ({len(entries)} entries)")

        # N-3 Fix: Valide FHIR-Location im Format ResourceType/id
        # Vorher: f"#{i}" (kein gueltiges FHIR-Location-Format)
        # Jetzt:  ResourceType/id aus dem Entry, Fallback auf generierte UUID
        def _entry_location(entry: dict, idx: int) -> str:
            res   = entry.get("resource", {})
            rtype = res.get("resourceType", "")
            rid   = res.get("id", "")
            if rtype and rid:
                return f"{rtype}/{rid}"
            # Fallback: generierte UUID wenn kein ResourceType/id vorhanden
            return f"urn:uuid:{uuid.uuid4()}"

        response = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "id": str(uuid.uuid4()),
            "entry": [
                {"response": {
                    "status": "201 Created",
                    "location": _entry_location(entry, i),
                }}
                for i, entry in enumerate(entries)
            ],
        }
        self._write_json(200, response)


class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="Mock FHIR endpoint (AION simulator)")
    parser.add_argument("--listen", type=int, default=8081)
    args = parser.parse_args()

    print(f"[AION-FHIR-Mock] Listening on http://0.0.0.0:{args.listen}")
    print(f"[AION-FHIR-Mock] Endpoints: POST /fhir/Bundle, POST /Bundle, GET /health\n")

    server = ThreadedServer(("0.0.0.0", args.listen), MockFHIRHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[AION-FHIR-Mock] Total received: {MockFHIRHandler.counter[0]}")
        server.shutdown()


if __name__ == "__main__":
    main()
