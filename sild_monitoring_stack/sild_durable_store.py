#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD persist-before-ack durable v2 intake — Variante A.

Ordering (fixed):  frame(complete) -> persist(fsync) -> analyse -> ack -> forward

This module is ADDITIVE to the existing SILD MLLP filter. It does not change the
four-pattern inspection, the forwarding, or the JSONL audit *content* beyond what
G4/G6 require (a `receipt_id` link and deterministic AuditEvent ids). Stdlib only
(`sqlite3`); no new dependency.

Guarantees (each has a named test in tests/test_durability_v2.py):

  G1  Durability before ACK. The ack is sent only after the raw bytes are durably
      committed. PRAGMA pinned as a pair: journal_mode=WAL, synchronous=FULL
      (per-commit durability; synchronous=FULL alone is journal-mode dependent —
      WAL+NORMAL would fsync only at checkpoint and violate G1). Precondition,
      not a proof: the storage stack must honour fsync (a lying write cache makes
      durability impossible).  Invariant: ACK => durable. send_ack() is reached
      strictly after a successful persist() return.

  G2  Raw before interpretation, in the same commit as the markers. The bytes are
      stored as received; the (G3) marker columns are derived best-effort and
      null-tolerant in the same INSERT — a parse failure yields NULL markers and
      never blocks the insert.

  G3  At-least-once + idempotency marker (metadata, never an insert-blocker).
      Marker = (MSH-3 Sending Application, MSH-4 Sending Facility, MSH-10 Message
      Control ID). The index is NON-UNIQUE — rejecting a duplicate insert would be
      loss. Dedup/resolution is a downstream stage's job, not SILD's.

  G4  Inspection durability. Status column = received | done. On startup a recovery
      sweep re-inspects every non-`done` row from the raw bytes and (re)writes its
      AuditEvent, then marks it `done`. Forward is best-effort: the sweep does NOT
      re-forward. Audit is at-least-once (a crash after audit-write before the
      status update re-inspects on restart -> duplicate AuditEvent); every
      AuditEvent carries a deterministic id (`<receipt_id>-<n>`) so the consumer
      can dedup.

  G5  ACK code is a total function of the analysis outcome (see ack_code_for_report):
      unparseable -> AA (poison-loop guard), clean -> AA, CRITICAL -> AE. Under
      persist-before-ack NAK-AE signals-and-duplicates; it does NOT reject (the
      message is already durable).

  G6  Encryption-at-rest is delegated to ops (LOUD, non-sabotaging): the store path
      is configurable, a startup warning is emitted, and NO raw payload is mirrored
      into the JSONL audit (findings/metadata only). See sild_mllp_filter.py for
      the warning and the no-cleartext-leak test in tests/.

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from sild_detector import (
    analyse_hl7_message,
    apply_severity_overrides,
    fhir_audit_events_from_report,
    SILDReport,
)

STATUS_RECEIVED = "received"
STATUS_DONE     = "done"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS intake (
    receipt_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    received_ts TEXT NOT NULL,
    raw         BLOB NOT NULL,
    msh3        TEXT,
    msh4        TEXT,
    msh10       TEXT,
    status      TEXT NOT NULL DEFAULT 'received',
    -- Erasure class (Step 4 fix): 'keyed' (attributable), 'unresolved' (PID-3
    -- PRESENT but unreadable -> could be any patient -> residual risk), or
    -- 'patientless' (no PID-3 at all -> belongs to NO patient -> NOT residual).
    pkey_status TEXT NOT NULL DEFAULT 'patientless'
);
-- G3: NON-UNIQUE — duplicate *detection* is a cheap query; an insert is never
-- rejected (a UNIQUE constraint here would turn a duplicate into a lost message).
CREATE INDEX IF NOT EXISTS idx_intake_marker ON intake (msh4, msh3, msh10);
CREATE INDEX IF NOT EXISTS idx_intake_status ON intake (status);
CREATE INDEX IF NOT EXISTS idx_intake_pkey_status ON intake (pkey_status);

-- Patient key(s) for erasure (Step 3/4). A child table — NOT a column — because
-- one message may carry several MR-typed identifiers (PID-3 with '~'); deletion
-- must hit a row carrying ANY of the patient's keys (else under-deletion). A row
-- with no resolvable key has NO entry here and is therefore unattributable
-- (fail-closed: it counts as residual risk, never silently 'clean').
CREATE TABLE IF NOT EXISTS intake_patient_key (
    receipt_id  INTEGER NOT NULL,
    patient_key TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_patient_key         ON intake_patient_key (patient_key);
CREATE INDEX IF NOT EXISTS idx_patient_key_receipt ON intake_patient_key (receipt_id);
"""


@dataclass
class PatientKeyConfig:
    """
    Site-configurable patient-key extractor (Step 3). Default confirmed against
    the SILD sample messages: PID-3, the MR-typed repetition, key = Authority|ID
    (PID-3.4 | PID-3.1) — NOT the bare ID (bare MRN is unique only per authority;
    two hospitals share '12345'). Override for a different site.
    """
    segment:           str = "PID"
    field:             int = 3       # PID-3 (index after splitting the segment on '|')
    id_comp:           int = 0       # CX-1 ID Number
    authority_comp:    int = 3       # CX-4 Assigning Authority
    type_comp:         int = 4       # CX-5 Identifier Type Code
    want_type:         str = "MR"    # Medical Record Number = patient-stable
    default_authority: Optional[str] = None   # used only when CX-4 is empty


def extract_patient_keys(raw: bytes, cfg: Optional[PatientKeyConfig] = None) -> List[str]:
    """
    Step 3: best-effort, null-tolerant patient key(s). Never raises, never blocks
    an insert. Returns a (deduped, sorted) list of 'Authority|ID' keys:

      - no PID / no PID-3 / no MR-typed repetition        -> []  (NULL -> uncertain)
      - one or more MR repetitions with an authority      -> [Authority|ID, ...]
      - MR repetition with EMPTY authority + default set  -> [default|ID]
      - MR repetition with EMPTY authority + no default   -> that repetition is
                                                             dropped (uncertain);
                                                             other valid MR keys
                                                             on the same message
                                                             still count.

    Returning [] means the row is unattributable -> fail-closed residual risk.
    """
    return classify_patient_keys(raw, cfg)[0]


# Erasure classes (Step 4 fix).
PKEY_KEYED       = "keyed"        # attributable -> deleted when its key is erased
PKEY_UNRESOLVED  = "unresolved"  # PID-3 PRESENT but unreadable -> could be X -> residual
PKEY_PATIENTLESS = "patientless" # no PID-3 at all -> belongs to NO patient -> NOT residual


def _has_patient_field(raw: bytes, cfg: PatientKeyConfig) -> bool:
    """True iff the configured patient field (PID-3) is PRESENT and non-empty."""
    try:
        text = raw.decode("utf-8", errors="replace")
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            f = line.split("|")
            if f and f[0] == cfg.segment and len(f) > cfg.field and f[cfg.field].strip():
                return True
        return False
    except Exception:
        return False


def classify_patient_keys(
    raw: bytes, cfg: Optional[PatientKeyConfig] = None
) -> Tuple[List[str], str]:
    """
    Step 4 (fix): return (keys, class). The class drives erasure completeness and
    is the A.6b dead-letter distinction — "parser failed" ≠ "contains no patient":

      keyed       -> at least one usable Authority|ID key extracted.
      unresolved  -> PID-3 is PRESENT but no usable key could be read (no MR type,
                     broken components, empty authority + no default). The row
                     COULD belong to any patient -> it is residual risk for every
                     erasure -> this is the *real* incomplete_uncertain.
      patientless -> no PID-3 at all (technical/ACK/structurally patientless). It
                     belongs to NO patient, so it can belong to X neither -> it
                     must NOT inflate X's residual count. (Counting it would make
                     every erasure incomplete forever -> the alarm that always
                     rings is no alarm.)
    """
    cfg = cfg or PatientKeyConfig()
    keys: List[str] = []
    try:
        text = raw.decode("utf-8", errors="replace")
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            f = line.split("|")
            if not f or f[0] != cfg.segment or len(f) <= cfg.field:
                continue
            for repetition in f[cfg.field].split("~"):       # PID-3 may repeat
                comps = repetition.split("^")
                idnum = comps[cfg.id_comp].strip()        if len(comps) > cfg.id_comp        else ""
                auth  = comps[cfg.authority_comp].strip() if len(comps) > cfg.authority_comp else ""
                ctype = comps[cfg.type_comp].strip()      if len(comps) > cfg.type_comp      else ""
                if ctype != cfg.want_type or not idnum:
                    continue
                if not auth:
                    auth = cfg.default_authority or ""
                if not auth:
                    # MR present but unqualifiable -> drop (uncertain), do not
                    # fall back to the bare ID (collision risk, point 2).
                    continue
                keys.append(f"{auth}|{idnum}")
    except Exception:
        return [], PKEY_PATIENTLESS
    keys = sorted(set(keys))
    if keys:
        return keys, PKEY_KEYED
    # No usable key: present-but-unreadable PID-3 is residual; no PID-3 is patientless.
    return [], (PKEY_UNRESOLVED if _has_patient_field(raw, cfg) else PKEY_PATIENTLESS)


class SimulatedCrash(RuntimeError):
    """Raised at an injected crash point in tests (never in production paths)."""


Marker = Tuple[Optional[str], Optional[str], Optional[str]]   # (msh3, msh4, msh10)


def _first_line_fields(raw: bytes) -> List[str]:
    text  = raw.decode("utf-8", errors="replace")
    first = text.replace("\r\n", "\n").replace("\r", "\n").split("\n", 1)[0]
    return first.split("|")


def extract_marker(raw: bytes) -> Marker:
    """
    G3: best-effort, null-tolerant idempotency marker (MSH-3, MSH-4, MSH-10).
    Never raises and never blocks an insert — a field that cannot be extracted
    becomes NULL. MSH-10 is not reliably unique in the real world; the marker is
    a detection aid, not an enforcement.
    """
    try:
        f = _first_line_fields(raw)
        msh3  = (f[2].strip() or None) if len(f) > 2 else None
        msh4  = (f[3].strip() or None) if len(f) > 3 else None
        msh10 = (f[9].strip() or None) if len(f) > 9 else None
        return msh3, msh4, msh10
    except Exception:
        return None, None, None


def extract_tenant(raw: bytes) -> str:
    """FM-4 §2.4 tenant id 'MSH-3|MSH-4' — best-effort, mirrors the filter's helper."""
    try:
        f   = _first_line_fields(raw)
        app = f[2].strip() if len(f) > 2 else ""
        fac = f[3].strip() if len(f) > 3 else ""
        return f"{app}|{fac}" if (app or fac) else ""
    except Exception:
        return ""


def ack_code_for_report(report: Optional[SILDReport]) -> Tuple[str, str]:
    """
    G5: total ACK function of the analysis outcome.

      report is None (parse/analyser error) -> AA  (poison-loop guard: the bytes
                                                     are already durable; NAKing
                                                     here would make the sender
                                                     retry forever and grow the
                                                     store — and would make
                                                     brokenness an acceptance
                                                     refusal, against G2)
      has_critical                          -> AE  (K-2 preserved; but AE now
                                                     SIGNALS, it does not reject —
                                                     the retry duplicates, which is
                                                     dedup-able downstream via the
                                                     G3 marker)
      otherwise                             -> AA
    """
    if report is None:
        return "AA", "uninspectable — durably stored (G5 poison-loop guard)"
    if report.has_critical:
        n = report.severity_counts()["critical"]
        return "AE", f"SILD CRITICAL: {n} finding(s) — source lost critical info (durably stored)"
    return "AA", ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class DurableStore:
    """
    SQLite-backed durable intake store. One serialized connection guarded by a
    lock (SQLite's single writer; matches "concurrent MLLP connections serialize
    on the write lock" in the perf note). Only the raw-bytes INSERT needs FULL
    durability; losing a `done` flag costs at most a re-inspection (= one duplicate
    AuditEvent), never a loss.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # isolation_level=None -> no implicit transactions; we control BEGIN/COMMIT
        # explicitly so the crash seam (after INSERT, before COMMIT) is testable.
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL")    # G1 (pair, part 1)
        self._conn.execute("PRAGMA synchronous=FULL")    # G1 (pair, part 2)
        self._conn.executescript(_SCHEMA)

    def persist(
        self,
        raw: bytes,
        marker: Marker,
        patient_keys: Optional[List[str]] = None,
        pkey_status: str = PKEY_PATIENTLESS,
        *,
        _crash_before_commit: bool = False,
    ) -> int:
        """
        G1/G2/G3 + Step 3: durably commit the raw bytes + null-tolerant marker +
        zero-or-more patient keys as ONE transaction; the fsync (synchronous=FULL)
        completes before commit returns. Returns the receipt_id. The caller MUST
        NOT ack before this returns. An empty patient_keys list is fine — the row
        is then simply unattributable (fail-closed residual risk for erasure).
        """
        msh3, msh4, msh10 = marker
        ts = _utcnow_iso()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT INTO intake (received_ts, raw, msh3, msh4, msh10, status, pkey_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ts, sqlite3.Binary(raw), msh3, msh4, msh10, STATUS_RECEIVED, pkey_status),
            )
            receipt_id = cur.lastrowid
            for key in (patient_keys or []):             # same commit as the raw row (G2)
                cur.execute(
                    "INSERT INTO intake_patient_key (receipt_id, patient_key) VALUES (?, ?)",
                    (receipt_id, key),
                )
            if _crash_before_commit:
                # Simulate a crash during/before commit (before fsync returns):
                # the transaction is rolled back, so nothing is durable. The caller
                # never reaches send_ack() -> proves ACK => durable.
                self._conn.rollback()
                raise SimulatedCrash("crash before commit")
            self._conn.commit()                          # fsync here (G1)
            return receipt_id

    def erase_patient(self, patient_key: str, *, commit: bool = False) -> "EraseResult":
        """
        Step 4 (Lesart A): erase every stored message carrying `patient_key`.

        FAIL-CLOSED completeness: 'complete' is reported ONLY when no unattributable
        row exists. A row whose patient key could not be extracted (technical/ACK/
        malformed message, missing MR) MIGHT belong to this patient but cannot be
        confirmed — so any such row forces status `incomplete_uncertain` with a
        residual-risk count, NEVER a silent 'clean' (the AION A/B dead-letter case,
        one stage earlier). The delete predicate is scoped EXACTLY to the key, so a
        different patient's rows are untouched (X-gone / Y-intact). dry-run is the
        default; pass commit=True to actually delete (destructive PID path).
        """
        with self._lock:
            matched = [
                r[0] for r in self._conn.execute(
                    "SELECT DISTINCT receipt_id FROM intake_patient_key WHERE patient_key=? "
                    "ORDER BY receipt_id",
                    (patient_key,),
                ).fetchall()
            ]
            # Residual risk = rows with a PRESENT-but-unreadable PID-3 only. Rows
            # with NO PID-3 (patientless: technical/ACK) belong to no patient and
            # are NOT counted — otherwise every erasure would read incomplete
            # forever and the status would be meaningless.
            unresolvable = self._conn.execute(
                "SELECT COUNT(*) FROM intake WHERE pkey_status=?", (PKEY_UNRESOLVED,)
            ).fetchone()[0]

            if commit and matched:
                cur = self._conn.cursor()
                cur.execute("BEGIN")
                qmarks = ",".join("?" * len(matched))
                cur.execute(f"DELETE FROM intake_patient_key WHERE receipt_id IN ({qmarks})", matched)
                cur.execute(f"DELETE FROM intake WHERE receipt_id IN ({qmarks})", matched)
                self._conn.commit()

        status = "incomplete_uncertain" if unresolvable > 0 else "complete"
        return EraseResult(
            patient_key=patient_key,
            deleted=len(matched),
            unresolvable=unresolvable,
            status=status,
            dry_run=not commit,
        )

    def mark_done(self, receipt_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE intake SET status=? WHERE receipt_id=?", (STATUS_DONE, receipt_id)
            )

    def pending(self) -> List[Tuple[int, bytes]]:
        """G4: rows not yet `done`, in arrival order (for the recovery sweep)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT receipt_id, raw FROM intake WHERE status=? ORDER BY receipt_id",
                (STATUS_RECEIVED,),
            ).fetchall()
        return [(rid, bytes(raw)) for (rid, raw) in rows]

    def find_by_marker(self, msh3, msh4, msh10) -> List[int]:
        """G3: duplicate detection via the (sender, control-id) marker (NULL-safe)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT receipt_id FROM intake WHERE msh3 IS ? AND msh4 IS ? AND msh10 IS ? "
                "ORDER BY receipt_id",
                (msh3, msh4, msh10),
            ).fetchall()
        return [r[0] for r in rows]

    def get_raw(self, receipt_id: int) -> Optional[bytes]:
        with self._lock:
            row = self._conn.execute(
                "SELECT raw FROM intake WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return bytes(row[0]) if row else None

    def get_status(self, receipt_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM intake WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return row[0] if row else None

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM intake").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


@dataclass
class IntakeOutcome:
    receipt_id:     int
    ack_code:       str
    ack_text:       str
    uninspectable:  bool
    report:         Optional[SILDReport]
    forwarded:      Optional[bool]   # None = no forwarder / not attempted
    forward_status: str


@dataclass
class EraseResult:
    patient_key:  str
    deleted:      int     # rows matching the key (deleted, or would-be in dry-run)
    unresolvable: int     # rows with NO patient key -> residual risk (fail-closed)
    status:       str     # "complete" | "incomplete_uncertain"
    dry_run:      bool


def build_erase_audit_record(result: EraseResult) -> dict:
    """
    Step 4: erasure audit WITHOUT content. Carries the key, counts, status and a
    timestamp — NEVER the deleted raw payload or any PID. ("G6 honesty": the key
    itself is Authority|MRN, an identifier; the record is an erasure log, kept
    under the same access controls as the store, not a PII-free artifact.)
    """
    return {
        "event":        "store_erase",
        "timestamp":    _utcnow_iso(),
        "patient_key":  result.patient_key,
        "deleted":      result.deleted,
        "unresolvable": result.unresolvable,
        "status":       result.status,
        "dry_run":      result.dry_run,
    }


def build_audit_record(
    receipt_id: int,
    raw: bytes,
    report: Optional[SILDReport],
    *,
    ack_code: str,
    forward_decision: str,
    forward_status: str,
    agent_info: Optional[dict] = None,
) -> dict:
    """
    G4/G6: JSONL audit record for one intake. Carries `receipt_id` (links the
    finding to its durable receipt) and gives every AuditEvent a DETERMINISTIC id
    `<receipt_id>-<n>` so a duplicate produced by the recovery sweep is dedup-able.
    Contains findings/metadata ONLY — never the raw payload (G6 no-cleartext-leak).
    """
    tenant_id = extract_tenant(raw)
    events = fhir_audit_events_from_report(report, agent_info, tenant_id) if report else []
    for i, ev in enumerate(events):
        ev["id"] = f"{receipt_id}-{i}"          # deterministic dedup key (G4)
    return {
        "timestamp":        _utcnow_iso(),
        "receipt_id":       receipt_id,         # NEW: SQLite receipt <-> JSONL finding
        "tenant_id":        tenant_id or "default",
        "message_type":     report.message_type if report else "UNPARSEABLE",
        "control_id":       report.control_id if report else "",
        "uninspectable":    report is None,
        "sild":             report.to_json_dict() if report else None,
        "forward_decision": forward_decision,
        "forward_status":   forward_status,
        "ack_code":         ack_code,
        "audit_events":     events,
    }


class DurableIntake:
    """
    Orchestrates the Variante-A ordering. `send_ack(code, text)` is supplied per
    call so the caller (socket server or test) controls how the ack is delivered;
    it is invoked strictly after a successful persist() (G1). `forward_fn`, if set,
    runs AFTER the ack and best-effort only (its failure never changes the ack).
    `audit_writer(record: dict)` appends one JSONL line (system-of-record for
    findings).
    """

    def __init__(
        self,
        store: DurableStore,
        *,
        agent_info: Optional[dict] = None,
        severity_config=None,
        forward_fn: Optional[Callable[[str], Tuple[bool, str]]] = None,
        audit_writer: Optional[Callable[[dict], None]] = None,
        patient_key_config: Optional[PatientKeyConfig] = None,
    ):
        self.store          = store
        self.agent_info     = agent_info or {"name": "sild-mllp-filter", "version": "1.0"}
        self.severity_config = severity_config
        self.forward_fn     = forward_fn
        self.audit_writer   = audit_writer
        self.patient_key_config = patient_key_config or PatientKeyConfig()

    def _analyse(self, raw: bytes) -> Tuple[Optional[SILDReport], Optional[str]]:
        """Total: returns (None, None) on any parse/analyser error (G5 guard)."""
        try:
            text   = raw.decode("utf-8", errors="replace")
            report = analyse_hl7_message(text)
            if self.severity_config is not None:
                report = apply_severity_overrides(report, self.severity_config, extract_tenant(raw))
            return report, text
        except Exception:
            return None, None

    def handle(
        self,
        raw: bytes,
        send_ack: Callable[[str, str], None],
        *,
        _crash: Optional[str] = None,
    ) -> IntakeOutcome:
        # 1. PERSIST (G1, G2, G3 + Step 3 patient keys) — durable before anything else.
        marker               = extract_marker(raw)
        patient_keys, pclass = classify_patient_keys(raw, self.patient_key_config)
        receipt_id           = self.store.persist(
            raw, marker, patient_keys, pclass,
            _crash_before_commit=(_crash == "before_commit"),
        )
        if _crash == "after_commit":
            # committed + durable, but the process dies before the ack: no AA
            # reaches the sender; the recovery sweep finishes the work on restart.
            raise SimulatedCrash("crash after commit, before ack")

        # 2. ANALYSE (before the ack -> K-2 NAK-AE on CRITICAL stays possible).
        report, text  = self._analyse(raw)
        uninspectable = report is None

        # 3. ACK code = total function of the outcome (G5).
        ack_code, ack_text = ack_code_for_report(report)
        if _crash == "before_ack":
            raise SimulatedCrash("crash before ack")

        # 4. ACK — strictly after the durable commit (G1).
        send_ack(ack_code, ack_text)

        # 5. FORWARD — after the ack, best-effort; never changes the ack (G4 non-goal).
        forwarded: Optional[bool] = None
        forward_status = ""
        forward_decision = "skip"
        if self.forward_fn is not None and text is not None:
            ok, info = self.forward_fn(text)
            forwarded, forward_status = ok, info
            forward_decision = "forwarded" if ok else "forward-failed"

        # 6. AUDIT (G4 + G6) — findings/metadata only, deterministic AuditEvent ids.
        self._write_audit(
            receipt_id, raw, report,
            ack_code=ack_code, forward_decision=forward_decision, forward_status=forward_status,
            uninspectable=uninspectable,
        )

        # 7. mark done (G4) — soft flag; losing it only costs a re-inspection.
        self.store.mark_done(receipt_id)

        return IntakeOutcome(
            receipt_id, ack_code, ack_text, uninspectable, report, forwarded, forward_status
        )

    def recover(self) -> int:
        """
        G4 startup recovery sweep. Re-inspect every non-`done` row from its raw
        bytes, (re)write its AuditEvent, mark it done. Does NOT re-forward (forward
        is best-effort). Returns the number of rows recovered.
        """
        n = 0
        for receipt_id, raw in self.store.pending():
            report, _ = self._analyse(raw)
            ack_code, _ = ack_code_for_report(report)
            self._write_audit(
                receipt_id, raw, report,
                ack_code=ack_code, forward_decision="recovered", forward_status="recovery-sweep",
                uninspectable=report is None,
            )
            self.store.mark_done(receipt_id)
            n += 1
        return n

    def _write_audit(
        self, receipt_id, raw, report, *, ack_code, forward_decision, forward_status, uninspectable
    ) -> None:
        if self.audit_writer is None:
            return
        # Same gate as the legacy filter (FM-4 §5.2: INFO-only -> no audit), plus
        # always surface an uninspectable message and any non-clean forward.
        record = build_audit_record(
            receipt_id, raw, report,
            ack_code=ack_code, forward_decision=forward_decision,
            forward_status=forward_status, agent_info=self.agent_info,
        )
        has_wc = bool(record["audit_events"])
        if has_wc or uninspectable or forward_decision == "forward-failed":
            self.audit_writer(record)


# ============== Erasure CLI (Step 4) ==============

def _erase_cli(argv=None) -> int:
    """
    SILD-SF-1 store erasure. dry-run by DEFAULT; --commit to actually delete
    (destructive PID path, A.6b discipline). Writes a content-free erase-audit
    line (key/counts/status/timestamp — never payload) to --erase-log if given.
    """
    p = argparse.ArgumentParser(
        prog="sild_durable_store",
        description="Erase one patient's messages from the persist-before-ack store "
                    "(SILD-SF-1). dry-run by default; --commit to delete.",
    )
    p.add_argument("action", choices=["erase"], help="store admin action")
    p.add_argument("--store", required=True, help="path to the SQLite intake store")
    p.add_argument("--patient-key", required=True,
                   help="patient key to erase, format 'Authority|ID' (e.g. 'HOSP|P-2026-12345')")
    p.add_argument("--commit", action="store_true",
                   help="actually delete (omit for dry-run, which deletes nothing)")
    p.add_argument("--erase-log", default=None,
                   help="append the content-free erase-audit record (JSONL) here")
    args = p.parse_args(argv)

    store  = DurableStore(args.store)
    result = store.erase_patient(args.patient_key, commit=args.commit)
    record = build_erase_audit_record(result)
    store.close()

    if args.erase_log:
        with open(args.erase_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    mode = "DRY-RUN (nothing deleted)" if result.dry_run else "COMMITTED"
    print(f"[sild-erase] {mode} key={result.patient_key} "
          f"deleted={result.deleted} unresolvable={result.unresolvable} status={result.status}")
    if result.status == "incomplete_uncertain":
        sys.stderr.write(
            f"[sild-erase] WARNING: {result.unresolvable} unattributable row(s) remain "
            f"(no resolvable patient key) — erasure of {result.patient_key} canNOT be "
            f"certified complete (fail-closed). Inspect these rows manually.\n"
        )
    return 0


if __name__ == "__main__":
    sys.exit(_erase_cli())
