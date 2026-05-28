#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD MLLP Filter Sidecar — with optional Prometheus metrics export.

Listens for HL7 v2 messages on MLLP (TCP), runs SILD analysis, logs the loss
report, optionally forwards downstream, and (if --metrics-port is given)
exposes a Prometheus /metrics endpoint for live monitoring.

FM-4 conformance (fixes K-2, K-3):
  K-2 — make_ack() mit code='AE' erzeugt protokollkonformes MLLP NAK-AE
         mit ERR-Segment nach HL7 v2.5+ Standard (FM-4 §5.2).
  K-3 — SeverityOverrideConfig wird via --severity-config geladen;
         apply_severity_overrides() wendet Sigma_eff = o_tenant o o_default o
         Sigma_intrinsic an. Tenant-ID aus MSH-3|MSH-4 (FM-4 §2.4).

Run with metrics:
    python sild_mllp_filter.py --listen 2575 --forward localhost:2576 \\
                               --log sild_reports.jsonl --mode log-only \\
                               --metrics-port 9100

Run with severity overrides:
    python sild_mllp_filter.py --listen 2575 --severity-config overrides.json

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""

import argparse
import json
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sild_detector import (
    analyse_hl7_message, SILDReport, using_real_cairn,
    SeverityOverrideConfig, apply_severity_overrides,
    fhir_audit_events_from_report,   # M-5
)


# Prometheus integration is optional — load lazily
_prom_enabled = False
try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server
    _prom_enabled = True
except ImportError:
    pass


# MLLP framing bytes (RFC-3464, HL7 Appendix C)
VT, FS, CR = b"\x0b", b"\x1c", b"\x0d"


# ============== Prometheus metric definitions ==============

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
        "1 wenn ein realer Delegations-Aufruf an cairn.sild erfolgt; "
        "aktuell stets 0 (Plug-in-Stelle, kein Delegationspfad implementiert)",
        ["protocol"],
    )
    # M-6: Quantitative Verlust-Metrik (FM-4 §4.1)
    M_LOSS_BUDGET = Histogram(
        "sild_loss_budget_bits",
        "Geschaetzter Informationsverlust in Bit pro Nachricht (FM-4 §4.1)",
        ["protocol", "message_type"],
        buckets=(10, 20, 40, 80, 160, 320, 640),
    )


PROTOCOL    = "hl7v2"
_AGENT_INFO = {"name": "sild-mllp-filter", "version": "1.0"}  # M-5


# ============== MLLP helpers ==============

def make_ack(original_msg_text: str, code: str = "AA", text: str = "") -> str:
    """
    Erzeugt eine HL7 v2 ACK-Nachricht.

    K-2 Fix (FM-4 §5.2): Bei code='AE' (Application Error, d.h. SILD-Block oder
    Forward-Fehler) wird ein protokollkonformes NAK-AE mit ERR-Segment erzeugt.
    Das ERR-Segment nach HL7 v2.5+ ist zwingend für interoperable Fehlerbehandlung:
      ERR||207^Application Internal Error^HL70357|E|<reason>

    Bei code='AA' (Application Accept) wird nur MSH+MSA erzeugt (Standard-ACK).
    """
    segments  = original_msg_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    msh_fields = segments[0].split("|") if segments else ["MSH", "^~\\&"]
    sending_app = msh_fields[2]  if len(msh_fields) > 2  else "UNKNOWN"
    sending_fac = msh_fields[3]  if len(msh_fields) > 3  else "UNKNOWN"
    msg_type    = msh_fields[8]  if len(msh_fields) > 8  else "ACK"
    control_id  = msh_fields[9]  if len(msh_fields) > 9  else "0"
    version     = msh_fields[11] if len(msh_fields) > 11 else "2.5"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    trigger = msg_type.split("^")[-1] if "^" in msg_type else ""

    # MSH: Sender und Empfänger getauscht (korrektes ACK-Routing)
    msh = (
        f"MSH|^~\\&|SILD_FILTER|FILTER|{sending_app}|{sending_fac}|{ts}||"
        f"ACK^{trigger}|{control_id}_ACK|P|{version}"
    )
    # MSA: code ist AA (accept) oder AE (application error)
    msa = f"MSA|{code}|{control_id}|{text[:80]}"

    if code == "AE":
        # K-2 Fix: NAK-AE erfordert ERR-Segment (FM-4 §5.2: "MLLP-NAK-AE bei v2")
        # HL7 v2.5+ ERR-Segment: Feld 3 = Fehlercode^Text^Tabelle, Feld 4 = Schwere
        err = f"ERR||207^Application Internal Error^HL70357|E|{text[:80]}"
        return msh + "\r" + msa + "\r" + err + "\r"

    return msh + "\r" + msa + "\r"


def wrap_mllp(message_text: str) -> bytes:
    return VT + message_text.encode("utf-8", errors="replace") + FS + CR


def read_mllp_message(sock: socket.socket, timeout: float = 5.0) -> Optional[str]:
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


def _extract_tenant_id(msg_text: str) -> str:
    """
    FM-4 §2.4: Tenant-ID aus MSH-3 (Sending Application) und MSH-4 (Sending Facility).
    Beispiel: 'KIS-NORD|KH-HAUPTHAUS'
    """
    try:
        first_line = msg_text.replace("\r", "\n").split("\n")[0]
        fields = first_line.split("|")
        app = fields[2].strip() if len(fields) > 2 else ""
        fac = fields[3].strip() if len(fields) > 3 else ""
        return f"{app}|{fac}" if (app or fac) else ""
    except Exception:
        return ""


# ============== Forwarder ==============

class MLLPForwarder:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host    = host
        self.port    = port
        self.timeout = timeout

    def send(self, message_text: str) -> tuple:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(wrap_mllp(message_text))
                ack_text = read_mllp_message(s, timeout=self.timeout)
                if ack_text is None:
                    return False, "no ACK received"
                return True, ack_text
        except Exception as e:
            return False, f"forward error: {type(e).__name__}: {e}"


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


# ============== Server ==============

class SILDFilterServer:
    def __init__(
        self,
        listen_port:     int,
        forwarder:       Optional[MLLPForwarder],
        logger:          JSONLogger,
        mode:            str,
        severity_config: Optional[SeverityOverrideConfig] = None,
    ):
        self.listen_port     = listen_port
        self.forwarder       = forwarder
        self.logger          = logger
        self.mode            = mode
        self.severity_config = severity_config or SeverityOverrideConfig()
        self._stop           = threading.Event()
        self._stats          = {"received": 0, "forwarded": 0, "blocked": 0, "errors": 0}
        self._stats_lock     = threading.Lock()

    def start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", self.listen_port))
        sock.listen(20)
        sock.settimeout(1.0)

        backend = "CAIRN" if using_real_cairn() else "Inline"
        if _prom_enabled:
            M_BACKEND.labels(protocol=PROTOCOL).set(1 if using_real_cairn() else 0)

        fwd_info = (
            f"forwarding to {self.forwarder.host}:{self.forwarder.port}"
            if self.forwarder else "no forwarding (analyse-only)"
        )
        override_info = (
            f"overrides: {len(self.severity_config.default_overrides)} default, "
            f"{len(self.severity_config.tenant_overrides)} tenants"
        )
        print(f"[SILD-Filter] Listening on tcp://0.0.0.0:{self.listen_port}")
        print(f"[SILD-Filter] Mode: {self.mode} | Backend: {backend} | {fwd_info}")
        print(f"[SILD-Filter] Severity: {override_info}")
        print(f"[SILD-Filter] Log: {self.logger.path}")
        print(f"[SILD-Filter] Press Ctrl-C to stop\n")

        try:
            while not self._stop.is_set():
                try:
                    client, addr = sock.accept()
                except socket.timeout:
                    continue
                t = threading.Thread(
                    target=self._handle_client, args=(client, addr), daemon=True
                )
                t.start()
        except KeyboardInterrupt:
            print("\n[SILD-Filter] Shutting down...")
        finally:
            sock.close()
            self._print_stats()

    def _handle_client(self, client: socket.socket, addr):
        if _prom_enabled:
            M_CONNECTIONS.labels(protocol=PROTOCOL).inc()
        try:
            while not self._stop.is_set():
                msg_text = read_mllp_message(client, timeout=10.0)
                if msg_text is None:
                    break
                self._process_message(client, msg_text, addr)
        except Exception as e:
            with self._stats_lock:
                self._stats["errors"] += 1
            print(f"[SILD-Filter] {addr} error: {type(e).__name__}: {e}")
        finally:
            if _prom_enabled:
                M_CONNECTIONS.labels(protocol=PROTOCOL).dec()
            try:
                client.close()
            except Exception:
                pass

    def _process_message(self, client: socket.socket, msg_text: str, addr):
        t_start = time.time()

        # --- SILD-Analyse ---
        try:
            report: SILDReport = analyse_hl7_message(msg_text)
        except Exception as e:
            print(f"[SILD-Filter] {addr} SILD error: {e}")
            with self._stats_lock:
                self._stats["errors"] += 1
            # K-2: Auch interne Fehler erzeugen NAK-AE
            self._send_ack(client, msg_text, code="AE", text=f"SILD error: {e}")
            return

        # K-3: Severity-Override-Komposition (FM-4 §2.4)
        tenant_id = _extract_tenant_id(msg_text)
        report = apply_severity_overrides(report, self.severity_config, tenant_id)

        with self._stats_lock:
            self._stats["received"] += 1
        recv_no = self._stats["received"]

        # --- Forward-Entscheidung ---
        forward_decision = "skip"
        forward_status   = ""
        ack_code         = "AA"
        ack_text         = ""

        if self.mode == "analyse-only" or self.forwarder is None:
            forward_decision = "skip"

        elif self.mode == "block-on-critical" and report.has_critical:
            # K-2 Fix: CRITICAL → MLLP-NAK-AE (FM-4 §5.2)
            forward_decision = "blocked"
            ack_code = "AE"
            ack_text = (
                f"SILD-BLOCK: {report.severity_counts()['critical']} critical finding(s) "
                f"[tenant={tenant_id or 'default'}]"
            )

        else:
            ok, downstream_ack = self.forwarder.send(msg_text)
            if ok:
                forward_decision = "forwarded"
                forward_status   = "ok"
            else:
                forward_decision = "forward-failed"
                forward_status   = downstream_ack
                ack_code = "AE"
                ack_text = "Downstream forward failed"

        elapsed = time.time() - t_start

        # --- Prometheus-Metriken ---
        if _prom_enabled:
            mt = report.message_type or "UNKNOWN"
            M_MESSAGES.labels(protocol=PROTOCOL, message_type=mt, ack_code=ack_code).inc()
            M_LATENCY.labels(protocol=PROTOCOL, message_type=mt).observe(elapsed)
            M_FORWARDS.labels(
                protocol=PROTOCOL, decision=forward_decision, message_type=mt
            ).inc()
            for loss in report.losses:
                pname = (
                    loss.pattern.value
                    if hasattr(loss.pattern, "value") else str(loss.pattern)
                )
                M_LOSSES.labels(
                    protocol=PROTOCOL,
                    pattern=pname,
                    severity=loss.effective_severity,
                    message_type=mt,
                ).inc()
            # M-6: Verlust-Budget in Bit beobachten (FM-4 §4.1)
            M_LOSS_BUDGET.labels(protocol=PROTOCOL, message_type=mt).observe(
                report.loss_budget_bits
            )

        # --- JSONL Audit-Log ---
        # FM-4 §5.2: INFO-only → kein Audit; WARNING/CRITICAL → Audit mit AuditEvents
        sev = report.severity_counts()
        should_audit = (
            sev["critical"] > 0 or sev["warning"] > 0 or forward_decision != "forwarded"
        )
        if should_audit:
            log_record = {
                "timestamp":        datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "remote_addr":      f"{addr[0]}:{addr[1]}",
                "tenant_id":        tenant_id or "default",
                "received_no":      recv_no,
                "message_type":     report.message_type,
                "control_id":       report.control_id,
                "total_segments":   report.total_segments,
                "sild":             report.to_json_dict(),
                "forward_decision": forward_decision,
                "forward_status":   forward_status,
                "elapsed_ms":       round(elapsed * 1000, 2),
                "ack_code":         ack_code,
                # M-5: FHIR AuditEvent-Einträge (FM-4 §5.3, FM-1-Tupel)
                "audit_events": fhir_audit_events_from_report(
                    report, _AGENT_INFO, tenant_id
                ),
            }
            self.logger.log(log_record)

        # --- Konsolen-Ausgabe ---
        sev_str = f"crit:{sev['critical']} warn:{sev['warning']} info:{sev['info']}"
        flag = "OK   "
        if forward_decision == "blocked":
            flag = "BLOCK"
        elif report.has_critical:
            flag = "CRIT "
        elif forward_decision == "forward-failed":
            flag = "FWERR"

        override_marker = " [OVR]" if tenant_id in self.severity_config.tenant_overrides else ""
        print(
            f"[SILD-Filter] #{recv_no} {flag} {report.message_type} {report.control_id} "
            f"| {report.total_segments} segs, {report.total_losses} losses ({sev_str})"
            f"{override_marker} | {elapsed*1000:.1f}ms | {forward_decision}"
        )

        if forward_decision == "forwarded":
            with self._stats_lock:
                self._stats["forwarded"] += 1
        elif forward_decision == "blocked":
            with self._stats_lock:
                self._stats["blocked"] += 1

        # K-2: _send_ack erzeugt bei code='AE' automatisch NAK-AE mit ERR-Segment
        self._send_ack(client, msg_text, code=ack_code, text=ack_text)

    def _send_ack(self, client: socket.socket, msg_text: str, code: str, text: str):
        """Sendet ACK (AA) oder NAK-AE (AE) zurück an den Client."""
        ack = make_ack(msg_text, code=code, text=text)
        try:
            client.sendall(wrap_mllp(ack))
        except Exception as e:
            print(f"[SILD-Filter] ACK send error: {e}")

    def _print_stats(self):
        s = self._stats
        print(
            f"\n[SILD-Filter] Stats: received={s['received']}  "
            f"forwarded={s['forwarded']}  blocked={s['blocked']}  errors={s['errors']}"
        )


# ============== CLI ==============

def main():
    parser = argparse.ArgumentParser(description="SILD MLLP Filter Sidecar")
    parser.add_argument("--listen",     type=int,  default=2575)
    parser.add_argument("--forward",    type=str,  default=None,
                        help="Downstream host:port (omit for analyse-only)")
    parser.add_argument("--log",        type=str,  default="sild_reports.jsonl")
    parser.add_argument("--mode",
                        choices=["log-only", "block-on-critical", "analyse-only"],
                        default="log-only")
    parser.add_argument("--metrics-port", type=int, default=None,
                        help="Prometheus metrics port (omit to disable)")
    # K-3: Severity-Override-Konfiguration
    parser.add_argument("--severity-config", type=str, default=None,
                        help="Pfad zur JSON-Datei mit Severity-Overrides (FM-4 §2.4). "
                             "Format: {\"default_overrides\": [...], \"tenant_overrides\": {...}}")
    args = parser.parse_args()

    # Prometheus starten
    if args.metrics_port:
        if not _prom_enabled:
            print("[SILD-Filter] WARN: prometheus_client not installed; --metrics-port ignored.")
        else:
            start_http_server(args.metrics_port)
            print(f"[SILD-Filter] Prometheus metrics on http://0.0.0.0:{args.metrics_port}/metrics")

    # K-3: Severity-Config laden
    severity_config = SeverityOverrideConfig()
    if args.severity_config:
        try:
            severity_config = SeverityOverrideConfig.from_json_file(args.severity_config)
            print(f"[SILD-Filter] Severity-Config geladen: {args.severity_config}")
        except Exception as e:
            print(f"[SILD-Filter] WARN: Severity-Config konnte nicht geladen werden: {e}")

    # Forwarder konfigurieren
    forwarder = None
    if args.forward and args.mode != "analyse-only":
        if ":" not in args.forward:
            sys.exit("--forward must be host:port")
        host, port_str = args.forward.rsplit(":", 1)
        forwarder = MLLPForwarder(host, int(port_str))

    logger = JSONLogger(Path(args.log))
    server = SILDFilterServer(
        args.listen, forwarder, logger, args.mode, severity_config
    )
    server.start()


if __name__ == "__main__":
    main()
