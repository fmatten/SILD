"""
Named proofs for the SILD persist-before-ack durable v2 intake (Variante A).

One test per guarantee G1–G6. A guarantee without its proof is not satisfied;
a green test that checks the wrong thing does not count — so the G5 test asserts
the WIRE ACK CODE (which the 21/21 conformance vectors never assert), and the G1
test asserts the correctness-critical direction (ACK => durable), not only no-loss.

Run:  pytest tests/test_durability_v2.py -v
"""
from __future__ import annotations

import json

import pytest

import sild_durable_store as ds          # noqa: E402 — conftest.py sys.path injection
from sild_durable_store import (
    DurableIntake,
    DurableStore,
    PatientKeyConfig,
    SimulatedCrash,
    build_audit_record,
    build_erase_audit_record,
    classify_patient_keys,
    extract_marker,
    extract_patient_keys,
)
from tests.durability_vectors_v2 import (
    ACK_CASES,
    BROKEN_PID,
    CLASS_CASES,
    CLEAN,
    CRITICAL,
    CRITICAL_DUP,
    EMPTY_AUTH_MR,
    KEY_CASES,
    MALFORMED,
    PATIENT_X_KEY,
    PATIENT_Y_KEY,
    SECRET,
    SECRET_TOKEN,
    TECHNICAL,
    patient_msg,
)


# --- harness ------------------------------------------------------------------

class _AckRecorder:
    def __init__(self):
        self.acks = []

    def __call__(self, code, text):
        self.acks.append((code, text))


def _make(tmp_path, *, forward_fn=None):
    """Return (store, intake, ack_recorder, audit_records list)."""
    store    = DurableStore(tmp_path / "intake.sqlite")
    records  = []
    intake   = DurableIntake(
        store,
        forward_fn=forward_fn,
        audit_writer=records.append,
    )
    return store, intake, _AckRecorder(), records


# --- G1: durability before ACK (the correctness-critical direction) -----------

def test_g1_reverse_no_ack_without_durability(tmp_path):
    """ACK => durable: crash before/during commit -> no AA reached the sender,
    and nothing is durable. This is the violating-state guard, not no-loss."""
    store, intake, ack, _ = _make(tmp_path)
    with pytest.raises(SimulatedCrash):
        intake.handle(CLEAN, ack, _crash="before_commit")
    assert ack.acks == [], "ACK must NOT be sent when the commit did not complete"
    # Reopen (simulated restart): the message was never durably committed.
    store.close()
    store2 = DurableStore(tmp_path / "intake.sqlite")
    assert store2.count() == 0, "no row may be durable when no ACK was sent"


def test_g1_noloss_crash_after_commit(tmp_path):
    """No-loss: crash after commit, before ACK -> message survives, sender saw no
    ACK (so it will retry -> G3 duplicate, never loss)."""
    store, intake, ack, _ = _make(tmp_path)
    with pytest.raises(SimulatedCrash):
        intake.handle(CLEAN, ack, _crash="after_commit")
    assert ack.acks == [], "no ACK before the crash"
    store.close()
    store2 = DurableStore(tmp_path / "intake.sqlite")
    assert store2.count() == 1, "the committed message must survive the crash"
    assert store2.get_status(1) == ds.STATUS_RECEIVED, "still pending after restart"


# --- G2: raw before interpretation, null-tolerant markers, never block insert --

def test_g2_malformed_survives_with_null_markers(tmp_path):
    store, intake, ack, _ = _make(tmp_path)
    outcome = intake.handle(MALFORMED, ack)
    assert store.count() == 1, "malformed message must be durably stored, not rejected"
    assert store.get_raw(1) == MALFORMED, "raw bytes stored verbatim"
    # truncated MSH: MSH-3 present, MSH-4 / MSH-10 unextractable -> NULL
    assert extract_marker(MALFORMED) == ("KIS-NORD", None, None)
    assert ack.acks and ack.acks[0][0] == "AA", "malformed-but-parseable -> AA (G5)"


# --- G3: at-least-once + idempotency marker (non-unique, findable) ------------

def test_g3_duplicate_marker_is_findable(tmp_path):
    store, intake, ack, _ = _make(tmp_path)
    intake.handle(CRITICAL, ack)
    intake.handle(CRITICAL_DUP, ack)        # sender retry -> a second durable row
    assert store.count() == 2, "duplicate is stored (loss is worse than a duplicate)"
    msh3, msh4, msh10 = extract_marker(CRITICAL)
    dups = store.find_by_marker(msh3, msh4, msh10)
    assert dups == [1, 2], "both copies findable via the (sender, control-id) marker"


# --- G4: inspection durability (recovery sweep + deterministic audit key) ------

def test_g4_recovery_sweep_rewrites_auditevent(tmp_path):
    # Crash after the durable commit, before the audit write.
    store, intake, ack, records = _make(tmp_path)
    with pytest.raises(SimulatedCrash):
        intake.handle(CRITICAL, ack, _crash="after_commit")
    assert records == [], "no audit written before the crash"
    store.close()

    # Restart: a fresh intake on the same store runs the recovery sweep.
    store2  = DurableStore(tmp_path / "intake.sqlite")
    rec2    = []
    intake2 = DurableIntake(store2, audit_writer=rec2.append)
    n = intake2.recover()
    assert n == 1, "the pending row is recovered"
    assert store2.get_status(1) == ds.STATUS_DONE, "marked done after recovery"
    assert len(rec2) == 1, "§9.3.4: the CRITICAL finding's AuditEvent exists after restart"
    rec = rec2[0]
    assert rec["receipt_id"] == 1
    assert rec["audit_events"], "CRITICAL -> at least one AuditEvent"
    # deterministic key: re-inspection yields the SAME id -> dedup-able
    assert rec["audit_events"][0]["id"] == "1-0"


def test_g4_audit_key_is_deterministic(tmp_path):
    """The recovery sweep is at-least-once; a duplicate AuditEvent must carry the
    same deterministic key so the consumer can dedup."""
    from sild_detector import analyse_hl7_message
    report = analyse_hl7_message(CRITICAL.decode())
    a = build_audit_record(42, CRITICAL, report, ack_code="AE",
                            forward_decision="recovered", forward_status="")
    b = build_audit_record(42, CRITICAL, report, ack_code="AE",
                            forward_decision="recovered", forward_status="")
    ids_a = [e["id"] for e in a["audit_events"]]
    ids_b = [e["id"] for e in b["audit_events"]]
    assert ids_a and ids_a == ids_b, "same receipt -> identical AuditEvent ids"


# --- G5: ACK code is a total function (all three branches) ---------------------

@pytest.mark.parametrize("case", ACK_CASES, ids=lambda c: c.name)
def test_g5_ack_code_total_function(tmp_path, monkeypatch, case):
    store, intake, ack, _ = _make(tmp_path)
    if case.raise_in_analyse:
        def _boom(_text):
            raise ValueError("simulated analyser failure")
        monkeypatch.setattr(ds, "analyse_hl7_message", _boom)
    intake.handle(case.raw, ack)
    assert ack.acks, "an ACK is always sent for a durably stored message"
    assert ack.acks[0][0] == case.expected_ack, f"{case.name}: {case.why}"
    assert store.count() == 1, "the message is durable regardless of the ACK code"


# --- G6: no cleartext PHI leak outside the store ------------------------------

def test_g6_no_cleartext_payload_in_audit(tmp_path):
    store, intake, ack, records = _make(tmp_path)
    intake.handle(SECRET, ack)
    assert records, "a CRITICAL message produces an audit record"
    line = json.dumps(records[0], ensure_ascii=False)
    assert SECRET_TOKEN not in line, "raw PHI (PID-5) must NOT appear in the JSONL audit"
    assert "raw" not in records[0], "the audit record carries no raw-payload field"
    # the PHI lives only in the durable store
    assert SECRET_TOKEN.encode() in store.get_raw(1), "the store holds the raw payload"


# --- Step 3: patient-key extraction (PID-3, MR-typed, Authority|ID) -----------

@pytest.mark.parametrize("case", KEY_CASES, ids=lambda c: c.name)
def test_patient_key_extraction(case):
    assert extract_patient_keys(case.raw) == case.expected, case.name


def test_patient_key_empty_authority_with_default():
    """Edge 2: MR with empty authority + a configured default authority -> keyed."""
    cfg = PatientKeyConfig(default_authority="DEFAULT")
    assert extract_patient_keys(EMPTY_AUTH_MR, cfg) == ["DEFAULT|P-NOAUTH"]


# --- Step 4: erase_patient (fail-closed, X-gone/Y-intact, audit, dry-run) ------

def _persist_patients(tmp_path):
    """Two X messages + one Y message, via the real intake path (keys derived)."""
    store, intake, ack, _ = _make(tmp_path)
    intake.handle(patient_msg("X-ADT", "P-X"), ack)
    intake.handle(patient_msg("X-ORU", "P-X", with_critical_orc="PLACER-X"), ack)
    intake.handle(patient_msg("Y-ADT", "P-Y"), ack)
    return store


def test_g_erase_x_gone_y_intact(tmp_path):
    store = _persist_patients(tmp_path)
    assert store.count() == 3
    result = store.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 2, "both of patient X's messages deleted"
    assert result.status == "complete", "no unattributable rows -> complete"
    assert store.count() == 1, "only patient Y remains"
    assert store.find_by_marker(*extract_marker(patient_msg("Y-ADT", "P-Y"))), "Y intact"
    # X is fully gone — no row carries X's key any more
    assert store.erase_patient(PATIENT_X_KEY, commit=False).deleted == 0


@pytest.mark.parametrize("case", CLASS_CASES, ids=lambda c: c.name)
def test_patient_key_classification(case):
    """The A.6b distinction: 'no PID-3' (patientless) vs 'PID-3 present but
    unreadable' (unresolved) vs 'keyed'."""
    assert classify_patient_keys(case.raw)[1] == case.expected, case.name


def test_g_erase_patientless_rows_do_not_block_completeness(tmp_path):
    """FIX: a patientless technical/ACK row (no PID-3) belongs to NO patient, so it
    must NOT make X's erasure incomplete. Otherwise the alarm rings forever."""
    store, intake, ack, _ = _make(tmp_path)
    intake.handle(patient_msg("X-ADT", "P-X"), ack)
    intake.handle(TECHNICAL, ack)                       # no PID -> patientless
    intake.handle(TECHNICAL, ack)                       # another technical message
    result = store.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 1
    assert result.unresolvable == 0, "patientless rows are not residual risk"
    assert result.status == "complete", "complete is reachable in normal operation"


def test_g_erase_broken_pid_is_residual_incomplete(tmp_path):
    """FIX: only a PRESENT-but-unreadable PID-3 (could be X) forces
    incomplete_uncertain — that is the real fail-closed case."""
    store, intake, ack, _ = _make(tmp_path)
    intake.handle(patient_msg("X-ADT", "P-X"), ack)
    intake.handle(BROKEN_PID, ack)                      # PID-3 present, unreadable
    result = store.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 1
    assert result.unresolvable == 1, "the unreadable-PID row could be X -> residual"
    assert result.status == "incomplete_uncertain", "fail-closed on the real uncertain"


def test_g_erase_dry_run_deletes_nothing(tmp_path):
    store = _persist_patients(tmp_path)
    before = store.count()
    result = store.erase_patient(PATIENT_X_KEY, commit=False)   # dry-run default
    assert result.dry_run is True
    assert result.deleted == 2, "reports what WOULD be deleted"
    assert store.count() == before, "dry-run must not delete anything"


def test_g_erase_audit_has_no_content(tmp_path):
    store, intake, ack, _ = _make(tmp_path)
    intake.handle(patient_msg("X-SEC", "P-X", secret=SECRET_TOKEN), ack)
    result = store.erase_patient(PATIENT_X_KEY, commit=True)
    record = build_erase_audit_record(result)
    line = json.dumps(record, ensure_ascii=False)
    assert SECRET_TOKEN not in line, "erase audit must not contain the deleted payload/PII"
    assert "raw" not in record and "payload" not in record
    assert record["patient_key"] == PATIENT_X_KEY
    assert record["deleted"] == 1 and record["status"] == "complete"
