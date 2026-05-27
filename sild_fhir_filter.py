#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD FHIR R4 Filter Sidecar — HTTP/REST variant.

Listens on an HTTP port for FHIR R4 Bundle POSTs, runs SILD analysis on each,
logs the loss report, optionally forwards to a downstream FHIR endpoint, and
exposes Prometheus metrics. Parallel to sild_mllp_filter.py for HL7v2 traffic.

Endpoints:
    POST /fhir/Bundle    - analyze a FHIR Bundle
    POST /Bundle         - same (without /fhir prefix)
    GET  /health         - liveness probe
    GET  /ready          - readiness probe

Run with metrics:
    python sild_fhir_filter.py --listen 8080 --forward http://aion-fhir-mock:8081 \\
                               --log sild_reports.jsonl --mode log-only \\
                               --metrics-port 9101

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import json
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from sild_detector import analyse_fhir_bundle, SILDReport, using_real_cairn


# Prometheus integration (optional)
_prom_enabled = False
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    _prom_enabled = True
except ImportError:
    pass


# ============== Prometheus metrics ==============
# Reuse the same metric names as the MLLP filter; protocol label distinguishes them.

if _prom_enabled:
    M_MESSAGES = Counter(
        "sild_messages_total",
        "Anzahl verarbeiteter Nachrichten",
        ["protocol", "message_type", "ack_code"],
    )
    M_LOSSES = Counter(
        "sild_losses_total",
        "Anzahl detektierter SILD-Loss-Ereignisse",
        ["protocol", "pattern", "severity", "message_type"],
    )
    M_FORWARDS = Counter(
        "sild_forward_decisions_total",
        "Forward-Entscheidungen",
        ["protocol", "decision", "message_type"],
    )
    M_LATENCY = Histogram(
        "sild_filter_latency_seconds",
        "Verarbeitungslatenz pro Nachricht",
        ["protocol", "message_type"],
        buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
    )
    M_CONNECTIONS = Gauge(
        "sild_active_connections",
        "Aktive eingehende Verbindungen",
        ["protocol"],
    )
    M_BACKEND = Gauge(
        "sild_using_real_cairn",
        "1 wenn produktive cairn.sild verwendet wird",
        ["protocol"],
    )


PROTOCOL = "fhir_r4"


# ============== Forwarder ==============

class FHIRForwarder:
    """POST a FHIR resource to a downstream HTTP endpoint."""

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def send(self, path: str, body_bytes: bytes,
             content_type: str = "application/fhir+json") -> tuple[bool, int, str]:
        url = self.base_url + path
        try:
            req = urllib.request.Request(
                url, data=body_bytes, method="POST",
                headers={"Content-Type": content_type, "Accept": "application/fhir+json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_body = resp.read().decode("utf-8", errors="replace")
                return True, resp.getcode(), resp_body
        except urllib.error.HTTPError as e:
            return False, e.code, f"HTTP {e.code}: {e.reason}"
        except Exception as e:
            return False, 0, f"forward error: {type(e).__name__}: {e}"


# ============== Logger ==============

class JSONLogger:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def log(self, record: dict):
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ============== Operation Outcome helpers ==============

def operation_outcome(severity: str, code: str, diagnostics: str) -> dict:
    """Build a FHIR OperationOutcome resource."""
    return {
        "resourceType": "OperationOutcome",
        "issue": [{"severity": severity, "code": code, "diagnostics": diagnostics}],
    }


# ============== HTTP request handler ==============

class FHIRRequestHandler(BaseHTTPRequestHandler):
    # Set by the server instance
    forwarder = None    # type: FHIRForwarder | None
    logger = None       # type: JSONLogger | None
    mode: str = "log-only"
    stats: dict = None
    stats_lock = None
    received_counter = 0
    received_lock = threading.Lock()

    def log_message(self, format, *args):
        # Suppress default access log; we do our own logging
        pass

    def _write_json(self, status: int, body: dict):
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/fhir+json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_GET(self):
        if self.path in ("/health", "/ready"):
            self._write_json(200, {"status": "ok", "service": "sild-fhir-filter"})
            return
        self._write_json(404, operation_outcome(
            "error", "not-found", f"Path {self.path} not handled"))

    def do_POST(self):
        if self.path not in ("/fhir/Bundle", "/Bundle"):
            self._write_json(404, operation_outcome(
                "error", "not-found", f"Path {self.path} not handled"))
            return

        # Read body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = 0
        if content_length <= 0:
            self._write_json(400, operation_outcome(
                "error", "structure", "Empty body"))
            return

        body_bytes = self.rfile.read(content_length)

        # Parse JSON
        try:
            bundle = json.loads(body_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._write_json(400, operation_outcome(
                "error", "structure", f"Invalid JSON: {e}"))
            return

        # Must be a Bundle
        if bundle.get("resourceType") != "Bundle":
            self._write_json(400, operation_outcome(
                "error", "structure",
                f"Expected Bundle, got {bundle.get('resourceType')}"))
            return

        self._process_bundle(bundle, body_bytes)

    def _process_bundle(self, bundle: dict, body_bytes: bytes):
        t_start = time.time()

        # SILD analysis
        try:
            report: SILDReport = analyse_fhir_bundle(bundle)
        except Exception as e:
            print(f"[SILD-FHIR] SILD error: {e}")
            with self.stats_lock:
                self.stats["errors"] += 1
            self._write_json(500, operation_outcome(
                "error", "exception", f"SILD analysis failed: {e}"))
            return

        with self.stats_lock:
            self.stats["received"] += 1
        recv_no = self.stats["received"]

        # Decide forward
        forward_decision = "skip"
        forward_status = ""
        status_code = 200
        ack_code = "AA"
        downstream_body = None

        if self.mode == "analyse-only" or self.forwarder is None:
            forward_decision = "skip"
        elif self.mode == "block-on-critical" and report.has_critical:
            forward_decision = "blocked"
            status_code = 422
            ack_code = "AE"
        else:
            ok, code, body = self.forwarder.send(self.path, body_bytes)
            if ok:
                forward_decision = "forwarded"
                forward_status = f"HTTP {code}"
                downstream_body = body
                status_code = 200
            else:
                forward_decision = "forward-failed"
                forward_status = body
                status_code = 502
                ack_code = "AE"

        elapsed = time.time() - t_start

        # Prometheus metrics
        if _prom_enabled:
            mt = report.message_type or "Bundle"
            M_MESSAGES.labels(protocol=PROTOCOL, message_type=mt, ack_code=ack_code).inc()
            M_LATENCY.labels(protocol=PROTOCOL, message_type=mt).observe(elapsed)
            M_FORWARDS.labels(protocol=PROTOCOL, decision=forward_decision, message_type=mt).inc()
            for loss in report.losses:
                pname = loss.pattern.value if hasattr(loss.pattern, "value") else str(loss.pattern)
                M_LOSSES.labels(
                    protocol=PROTOCOL, pattern=pname, severity=loss.severity, message_type=mt
                ).inc()

        # Log record
        log_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "protocol": PROTOCOL,
            "remote_addr": f"{self.client_address[0]}:{self.client_address[1]}",
            "received_no": recv_no,
            "message_type": report.message_type,
            "control_id": report.control_id,
            "total_resources": report.total_segments,
            "sild": report.to_json_dict(),
            "forward_decision": forward_decision,
            "forward_status": forward_status,
            "elapsed_ms": round(elapsed * 1000, 2),
            "ack_code": ack_code,
            "http_status": status_code,
        }
        self.logger.log(log_record)

        # Console summary
        sev = report.severity_counts()
        sev_str = f"crit:{sev['critical']} warn:{sev['warning']} info:{sev['info']}"
        flag = "OK   " if not report.has_critical else "CRIT "
        if forward_decision == "blocked":
            flag = "BLOCK"
        elif forward_decision == "forward-failed":
            flag = "FWERR"
        print(f"[SILD-FHIR] #{recv_no} {flag} {report.message_type} {report.control_id} "
              f"| {report.total_segments} res, {report.total_losses} losses ({sev_str}) "
              f"| {elapsed*1000:.1f}ms | {forward_decision}")

        if forward_decision == "forwarded":
            with self.stats_lock:
                self.stats["forwarded"] += 1
        elif forward_decision == "blocked":
            with self.stats_lock:
                self.stats["blocked"] += 1

        # Send response
        if status_code == 200 and downstream_body:
            try:
                body_obj = json.loads(downstream_body)
            except json.JSONDecodeError:
                body_obj = {"resourceType": "Bundle", "type": "transaction-response", "entry": []}
            self._write_json(200, body_obj)
        elif status_code == 200:
            self._write_json(200, {
                "resourceType": "Bundle", "type": "transaction-response",
                "id": str(uuid.uuid4()), "entry": [],
            })
        elif status_code == 422:
            self._write_json(422, operation_outcome(
                "error", "business-rule",
                f"Blocked by SILD: {report.severity_counts()['critical']} critical findings"))
        elif status_code == 502:
            self._write_json(502, operation_outcome(
                "error", "transient",
                f"Downstream forward failed: {forward_status}"))
        else:
            self._write_json(status_code, operation_outcome(
                "error", "exception", "Unhandled status code"))


# ============== Threaded server ==============

class ThreadedHTTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


# ============== CLI ==============

def main():
    parser = argparse.ArgumentParser(description="SILD FHIR R4 Filter Sidecar")
    parser.add_argument("--listen", type=int, default=8080)
    parser.add_argument("--forward", type=str, default=None,
                        help="Downstream FHIR base URL, e.g. http://aion:8081 (omit for analyse-only)")
    parser.add_argument("--log", type=str, default="sild_reports.jsonl")
    parser.add_argument("--mode", choices=["log-only", "block-on-critical", "analyse-only"],
                        default="log-only")
    parser.add_argument("--metrics-port", type=int, default=None)
    args = parser.parse_args()

    if args.metrics_port:
        if not _prom_enabled:
            print("[SILD-FHIR] WARN: prometheus_client not installed; --metrics-port ignored.")
        else:
            start_http_server(args.metrics_port)
            print(f"[SILD-FHIR] Prometheus metrics on http://0.0.0.0:{args.metrics_port}/metrics")

    forwarder = None
    if args.forward and args.mode != "analyse-only":
        forwarder = FHIRForwarder(args.forward)

    logger = JSONLogger(Path(args.log))
    stats = {"received": 0, "forwarded": 0, "blocked": 0, "errors": 0}
    stats_lock = threading.Lock()

    # Inject server state into handler class
    FHIRRequestHandler.forwarder = forwarder
    FHIRRequestHandler.logger = logger
    FHIRRequestHandler.mode = args.mode
    FHIRRequestHandler.stats = stats
    FHIRRequestHandler.stats_lock = stats_lock

    if _prom_enabled:
        M_BACKEND.labels(protocol=PROTOCOL).set(1 if using_real_cairn() else 0)

    backend = "CAIRN" if using_real_cairn() else "Inline"
    forward_info = f"forwarding to {args.forward}" if forwarder else "no forwarding (analyse-only)"
    print(f"[SILD-FHIR] Listening on http://0.0.0.0:{args.listen}")
    print(f"[SILD-FHIR] Mode: {args.mode} | Backend: {backend} | {forward_info}")
    print(f"[SILD-FHIR] Log: {args.log}")
    print(f"[SILD-FHIR] Endpoints: POST /fhir/Bundle, POST /Bundle, GET /health\n")

    server = ThreadedHTTPServer(("0.0.0.0", args.listen), FHIRRequestHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[SILD-FHIR] Shutting down...")
        print(f"[SILD-FHIR] Stats: received={stats['received']}  forwarded={stats['forwarded']}  "
              f"blocked={stats['blocked']}  errors={stats['errors']}")
        server.shutdown()


if __name__ == "__main__":
    main()
