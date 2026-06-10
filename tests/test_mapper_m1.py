"""
Named proofs for the SILD M-1 Mapper (sild_mapper_m1).

One test (or parametrized table) per guarantee M1-G1..G5. A guarantee without
its proof is not satisfied. The crash-injection tests assert the correctness-
critical directions: G1 proves BOTH "no skip" (crash before the Vermerk) AND
"no loss / no double-action" (crash after the Vermerk, before the cursor).

Run:  pytest tests/test_mapper_m1.py -v
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import sild_mapper_m1 as m1
from sild_durable_store import (
    DurableStore,
    SimulatedCrash,
    build_erase_audit_record,
    extract_marker,
)
from sild_mapper_m1 import (
    IntakeReader,
    MapperM1,
    MapperStore,
    SmtpConfig,
    build_notification,
    build_notifier,
    classify,
)
from tests.mapper_m1_vectors import (
    DUP_A,
    DUP_B,
    FIXED_NOW,
    GOOD_TS,
    HOLD_BROKEN,
    HOLD_NOPID_A,
    HOLD_NOPID_B,
    HOLD_X,
    HOLD_X2,
    HOLD_X_SECRET,
    HOLD_Y,
    NULL_MARKER_A,
    NULL_MARKER_B,
    PATIENT_X_KEY,
    PATIENT_Y_KEY,
    RELEVANCE_CASES,
    SECRET_HOLD,
    SECRET_TOKEN,
    TIMEQUALITY_CASES,
    _msg,
    _msh,
    _seg,
    adt,
)


# --- harness ------------------------------------------------------------------

class _FakeNotifier:
    """Records every send; can be told to fail (SMTP unreachable simulation)."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    def send(self, subject, body):
        self.sent.append((subject, body))
        return (False, "fake-smtp-down") if self.fail else (True, "fake-ok")


def _seed_intake(tmp_path, messages):
    """Write `messages` into a real SILD durable intake store (the read source)."""
    store = DurableStore(tmp_path / "intake.sqlite")
    for raw in messages:
        store.persist(raw, extract_marker(raw))
    return store


def _make_mapper(tmp_path, *, notifier=None, forward_calls=None):
    reader = IntakeReader(tmp_path / "intake.sqlite")
    store  = MapperStore(tmp_path / "mapper.sqlite")
    notifier = notifier or _FakeNotifier()
    forward_fn = None
    if forward_calls is not None:
        forward_fn = lambda rid, raw, trig, prov: forward_calls.append((rid, trig))  # noqa: E731
    mapper = MapperM1(reader, store, notifier, forward_fn=forward_fn,
                      now_fn=lambda: FIXED_NOW)
    return reader, store, mapper


# --- M1-G3: relevance filter --------------------------------------------------

@pytest.mark.parametrize("case", RELEVANCE_CASES, ids=lambda c: c.name)
def test_m1g3_relevance_filter(case):
    """Relevant ADT (incl. A08 update + A11/A12/A13 storni) -> passed through;
    everything else (other ADT / ORU / RDE) -> ignored, no finding, no M-2 push."""
    c = classify(case.raw, now=FIXED_NOW)
    assert c.kind == case.expected_kind, case.name
    if case.expected_trigger is not None:
        assert c.trigger == case.expected_trigger, case.name


# --- M1-G4: three-way syntactic time quality ----------------------------------

@pytest.mark.parametrize("case", TIMEQUALITY_CASES, ids=lambda c: c.name)
def test_m1g4_three_way_time_quality(case):
    c = classify(case.raw, now=FIXED_NOW)
    assert c.kind == case.expected_kind, case.name


# --- M1-G1: persist-the-Vermerk before the cursor (no skip / no loss) ---------

def test_m1g1_crash_before_vermerk_no_skip(tmp_path):
    """Crash before the durable Vermerk -> nothing recorded, cursor unmoved ->
    the receipt is re-sighted on restart (NO SKIP)."""
    store = _seed_intake(tmp_path, [adt("A01", "G1-A", _good_time())])
    reader, mstore, mapper = _make_mapper(tmp_path)
    with pytest.raises(SimulatedCrash):
        mapper.process_receipt(1, store.get_raw(1), _crash="before_persist")
    assert mstore.get_disposition(1) is None, "no Vermerk may exist after a pre-commit crash"
    assert mstore.get_cursor() == 0, "cursor must not advance"
    # Restart: a fresh sighting records it — the message was not skipped.
    disp = mapper.process_receipt(1, store.get_raw(1))
    assert disp.kind == m1.USABLE
    assert mstore.get_disposition(1) is not None, "re-sighted after restart (no skip)"


def test_m1g1_noloss_crash_after_vermerk_before_cursor(tmp_path):
    """Crash after the Vermerk, before the cursor -> on restart the receipt is
    re-scanned but is idempotent by receipt_id: NO double-forward, NO loss."""
    store = _seed_intake(tmp_path, [adt("A01", "G1-B", _good_time())])
    forwarded = []
    reader, mstore, mapper = _make_mapper(tmp_path, forward_calls=forwarded)
    with pytest.raises(SimulatedCrash):
        mapper.poll_once(_crash_before_cursor_at=1)
    assert mstore.get_disposition(1) is not None, "the Vermerk is durable"
    assert mstore.get_cursor() == 0, "cursor did not advance before the crash"
    assert forwarded == [(1, "A01")], "forwarded exactly once before the crash"

    # Restart: new store + mapper on the SAME mapper.sqlite (durable state).
    reader2 = IntakeReader(tmp_path / "intake.sqlite")
    mstore2 = MapperStore(tmp_path / "mapper.sqlite")
    mapper2 = MapperM1(reader2, mstore2, _FakeNotifier(),
                       forward_fn=lambda rid, raw, t, prov: forwarded.append((rid, t)),
                       now_fn=lambda: FIXED_NOW)
    disp = mapper2.poll_once()
    assert [d.receipt_id for d in disp] == [1], "the pending receipt is re-scanned"
    assert forwarded == [(1, "A01")], "idempotent: NOT forwarded a second time"
    assert mstore2.get_cursor() == 1, "cursor advances on the clean re-run"
    assert mstore2.counts()["dispositions"] == 1, "no duplicate Vermerk"


# --- M1-G2: duplicate suppression (transport + restart), NULL marker passes ---

def test_m1g2_transport_duplicate_suppressed(tmp_path):
    """Two intake rows, identical complete marker -> first usable, second
    suppressed_duplicate (not forwarded twice to M-2)."""
    _seed_intake(tmp_path, [DUP_A, DUP_B])
    forwarded = []
    reader, mstore, mapper = _make_mapper(tmp_path, forward_calls=forwarded)
    disp = mapper.poll_once()
    kinds = [d.kind for d in disp]
    assert kinds == [m1.USABLE, m1.SUPPRESSED_DUPLICATE]
    assert forwarded == [(1, "A01")], "the duplicate is NOT forwarded again"


def test_m1g2_restart_duplicate_suppressed(tmp_path):
    """The seen-marker store is durable: after a restart, a fresh intake row with
    an already-seen marker is still suppressed."""
    store = _seed_intake(tmp_path, [DUP_A])
    reader, mstore, mapper = _make_mapper(tmp_path)
    assert mapper.poll_once()[0].kind == m1.USABLE

    # A transport duplicate arrives AFTER the mapper restarted.
    store.persist(DUP_B, extract_marker(DUP_B))
    reader2 = IntakeReader(tmp_path / "intake.sqlite")
    mstore2 = MapperStore(tmp_path / "mapper.sqlite")
    mapper2 = MapperM1(reader2, mstore2, _FakeNotifier(), now_fn=lambda: FIXED_NOW)
    disp = mapper2.poll_once()
    assert [d.kind for d in disp] == [m1.SUPPRESSED_DUPLICATE], "restart dedup holds"


def test_m1g2_null_marker_not_suppressed(tmp_path):
    """An incomplete marker (MSH-10 empty) can never be proven a duplicate ->
    never suppressed (loss is worse than a duplicate)."""
    _seed_intake(tmp_path, [NULL_MARKER_A, NULL_MARKER_B])
    forwarded = []
    reader, mstore, mapper = _make_mapper(tmp_path, forward_calls=forwarded)
    disp = mapper.poll_once()
    assert [d.kind for d in disp] == [m1.USABLE, m1.USABLE], "NULL-marker copies both pass"
    assert len(forwarded) == 2, "both forwarded — never suppressed"


# --- M1-G5: store before notify, mail failure loses nothing, PID-free, warning -

def test_m1g5_store_before_notify_and_mail_failure_loses_nothing(tmp_path):
    """A finding is durable BEFORE the mail; an SMTP failure leaves it stored and
    re-deliverable (not lost)."""
    _seed_intake(tmp_path, [adt("A01", "G5-F")])              # missing time -> hold + finding
    notifier = _FakeNotifier(fail=True)
    reader, mstore, mapper = _make_mapper(tmp_path, notifier=notifier)
    disp = mapper.poll_once()
    assert disp[0].kind == m1.HOLD_TIMEQUALITY
    assert notifier.sent, "an active send was attempted"
    pending = mstore.pending_findings()
    assert len(pending) == 1, "the finding survives the mail failure (durable, re-deliverable)"
    assert pending[0].receipt_id == 1

    # Backlog re-delivery once SMTP is healthy again.
    notifier.fail = False
    assert mapper.redeliver_pending() == 1
    assert mstore.pending_findings() == [], "re-delivered -> no backlog left"


def test_m1g5_notification_is_pid_free(tmp_path):
    """The mail body and the stored finding carry counters/marker/status/time —
    NEVER the patient name/PID/raw. The raw lives only in the hold-queue."""
    _seed_intake(tmp_path, [SECRET_HOLD])
    notifier = _FakeNotifier()
    reader, mstore, mapper = _make_mapper(tmp_path, notifier=notifier)
    mapper.poll_once()

    subject, body = notifier.sent[0]
    assert SECRET_TOKEN not in subject and SECRET_TOKEN not in body, \
        "raw PHI (PID-5) must NOT appear in the notification"
    finding = mstore.pending_findings()[0] if mstore.pending_findings() else None
    # delivered (fake ok) -> not pending; re-read via build_notification on a fresh fetch
    # Assert the finding row itself is PID-free.
    with sqlite3.connect(str(tmp_path / "mapper.sqlite")) as c:
        row = c.execute("SELECT reason, msh3, msh4, msh10 FROM finding").fetchone()
    assert SECRET_TOKEN not in " ".join(str(x) for x in row), "finding row is PID-free"
    # The raw payload (with the token) lives only in the hold-queue.
    assert SECRET_TOKEN.encode() in mstore.get_hold_raw(1), "hold-queue retains the raw v2"


def test_m1g5_loud_warning_without_smtp_config(tmp_path):
    """No SMTP config -> a loud warning is emitted and findings stay durable
    (no silent non-notification)."""
    warnings = []
    notifier = build_notifier(None, warn=warnings.append)
    assert warnings and "NICHT konfiguriert" in warnings[0]

    _seed_intake(tmp_path, [adt("A01", "G5-W")])              # missing time -> finding
    reader = IntakeReader(tmp_path / "intake.sqlite")
    mstore = MapperStore(tmp_path / "mapper.sqlite")
    mapper = MapperM1(reader, mstore, notifier, now_fn=lambda: FIXED_NOW)
    mapper.poll_once()
    pending = mstore.pending_findings()
    assert len(pending) == 1, "without SMTP the finding is still durably stored"
    assert pending[0].kind == m1.HOLD_TIMEQUALITY


def test_m1g5_smtp_config_selects_active_notifier():
    """A configured SMTP target yields the active SMTP notifier (no warning)."""
    warnings = []
    cfg = SmtpConfig(host="smtp.example.org", sender="m1@example.org",
                     recipients=["ops@example.org"])
    notifier = build_notifier(cfg, warn=warnings.append)
    assert isinstance(notifier, m1.SmtpNotifier)
    assert warnings == [], "configured SMTP must not warn"


def test_build_notification_shape():
    """build_notification carries the marker (source metadata) and the
    classification, and is self-describing as PID-free."""
    f = m1.Finding(receipt_id=7, kind=m1.HOLD_MALFORMED, trigger=None,
                   msh3="KIS", msh4="KH", msh10="CTRL-1", reason="MSH-9 fehlt",
                   created_ts="2026-06-10T12:00:00Z", finding_id=3)
    subject, body = build_notification(f)
    assert m1.HOLD_MALFORMED in subject
    assert "KIS|KH|CTRL-1" in body and "PID-frei" in body


# --- M1-G3 correction: ADT with a broken trigger holds (never silently ignored) --

def test_m1g3_adt_without_trigger_holds_not_ignored(tmp_path):
    """Category fix: an ADT whose MSH-9 trigger code is missing/unreadable is
    'my topic but broken' -> hold_malformed + a durable finding, NOT ignored
    (a potentially interval-relevant movement must not vanish silently)."""
    _seed_intake(tmp_path, [adt("", "NO-TRIG", _good_time())])   # MSH-9 = 'ADT' (no trigger)
    reader, mstore, mapper = _make_mapper(tmp_path)
    disp = mapper.poll_once()
    assert disp[0].kind == m1.HOLD_MALFORMED, "broken-trigger ADT must hold, not ignore"
    assert mstore.counts()["findings"] == 1, "a finding is raised (no silent drop)"
    assert mstore.get_hold_raw(1) is not None, "the broken ADT is held, not dropped"
    # contrast: a genuine non-ADT IS ignored (no finding)
    c = classify(_msg(_msh("R01", "X", msg_code="ORU")), now=FIXED_NOW)
    assert c.kind == m1.IGNORED


# --- M1-G4 time field: inspection-backed default + configurability ------------

def test_m1g4_real_sample_admission_is_usable(tmp_path):
    """Regression guard for the time-field finding: the real ADT sample carries
    its movement time in EVN-2 (EVN-6 and PV1-44/45 are absent). The default
    (EVN-6 -> EVN-2) must classify it usable, not hold_timequality."""
    import os
    sample = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          "sild_monitoring_stack", "samples", "adt_a01_admission.hl7")
    with open(sample, "rb") as fh:
        raw = fh.read()
    c = classify(raw, now=FIXED_NOW)
    assert c.kind == m1.USABLE, "real admission (EVN-2 time) must be usable under the default"
    assert c.trigger == "A01"


def test_m1g4_a02_movement_time_zbe_then_evn6():
    """A02 (Verlegung) movement time = ZBE-2 -> EVN-6. ZBE-2 wins when present;
    EVN-6 carries it when ZBE is not in the stream."""
    from sild_mapper_m1 import resolve_event_time
    from sild_detector import parse_hl7v2
    from tests.mapper_m1_vectors import OTHER_TS
    a02_zbe = adt("A02", "A2-ZBE", _seg("ZBE", {2: GOOD_TS}))
    a02_evn = adt("A02", "A2-EVN", _seg("EVN", {1: "A02", 6: GOOD_TS}))
    assert classify(a02_zbe, now=FIXED_NOW).kind == m1.USABLE, "ZBE-2 carries the movement time"
    assert classify(a02_evn, now=FIXED_NOW).kind == m1.USABLE, "EVN-6 carries it when no ZBE"
    # priority: ZBE-2 is read BEFORE EVN-6 when both are present
    both = adt("A02", "A2-BOTH", _seg("ZBE", {2: GOOD_TS}), _seg("EVN", {1: "A02", 6: OTHER_TS}))
    val, src = resolve_event_time(parse_hl7v2(both.decode()), "A02")
    assert val == GOOD_TS and src == ("ZBE", 2), "ZBE-2 wins over EVN-6"


def test_m1g4_a02_not_misdated_to_pv1_44(tmp_path):
    """THE anti-misdating proof: an A02 with PV1-44 present but NO ZBE-2 and NO
    EVN-6 must NOT be dated to PV1-44 (that would be the stale admit time). It is
    surfaced as hold_timequality + a finding, never silently mis-dated."""
    a02 = adt("A02", "A2-MISDATE", _seg("PV1", {44: GOOD_TS}))   # only PV1-44, no ZBE/EVN
    assert classify(a02, now=FIXED_NOW).kind == m1.HOLD_TIMEQUALITY, \
        "A02 without a real movement time must hold, not date to PV1-44"
    # and it actually surfaces as a finding via the mapper (visible, not dropped)
    _seed_intake(tmp_path, [a02])
    reader, mstore, mapper = _make_mapper(tmp_path)
    disp = mapper.poll_once()
    assert disp[0].kind == m1.HOLD_TIMEQUALITY
    assert mstore.counts()["findings"] == 1, "the un-datable transfer is surfaced, not lost"


def test_m1g4_time_field_is_configurable_per_trigger():
    """The movement-time field is configurable (not hard-coded): an A01 carrying
    time only in PV1-45 holds under the default (which reads PV1-44) and becomes
    usable once a site maps A01 -> PV1-45."""
    from sild_mapper_m1 import TimeFieldConfig
    msg = adt("A01", "CFG-1", _seg("PV1", {45: GOOD_TS}))    # time only in PV1-45
    assert classify(msg, now=FIXED_NOW).kind == m1.HOLD_TIMEQUALITY, "default A01 reads PV1-44"
    cfg = TimeFieldConfig(candidates={"A01": [("PV1", 45), ("EVN", 6)]})
    assert classify(msg, now=FIXED_NOW, time_fields=cfg).kind == m1.USABLE, "override reads PV1-45"


# --- M1-G4: time provenance (measured vs event vs recorded-substitute) --------

def test_m1g4_time_provenance_measured_vs_recorded_substitute():
    """The used time carries WHERE it came from, so M-2/AION can keep a recorded
    SUBSTITUTE out of Δ_con as if it were a measured fact."""
    measured = classify(adt("A01", "P-PV", _seg("PV1", {44: GOOD_TS})), now=FIXED_NOW)
    assert measured.kind == m1.USABLE
    assert measured.time_provenance == "PV1-44 (gemessene Bewegungszeit)"

    event = classify(adt("A02", "P-E6", _seg("EVN", {1: "A02", 6: GOOD_TS})), now=FIXED_NOW)
    assert event.time_provenance == "EVN-6 (Ereigniszeit)"

    # A01 whose time is ONLY in EVN-2 (the real sample shape): usable, but flagged
    # as a recorded substitute — NOT "measured".
    substitute = classify(adt("A01", "P-E2", _seg("EVN", {1: "A01", 2: GOOD_TS})), now=FIXED_NOW)
    assert substitute.kind == m1.USABLE
    assert substitute.time_provenance == "EVN-2 (Erfassungs-Ersatz)", "recorded substitute, not measured"
    assert m1.PROV_RECORDED != m1.PROV_MEASURED


def test_m1g4_provenance_is_persisted_and_forwarded(tmp_path):
    """The provenance is written to the durable Vermerk AND handed to M-2 via
    forward_fn — it starts here, the provenance M-2 was already promised."""
    forwarded = []
    _seed_intake(tmp_path, [adt("A01", "FWD-E2", _seg("EVN", {1: "A01", 2: GOOD_TS}))])
    reader = IntakeReader(tmp_path / "intake.sqlite")
    mstore = MapperStore(tmp_path / "mapper.sqlite")
    mapper = MapperM1(reader, mstore, _FakeNotifier(),
                      forward_fn=lambda rid, raw, trig, prov: forwarded.append((rid, trig, prov)),
                      now_fn=lambda: FIXED_NOW)
    disp = mapper.poll_once()
    assert disp[0].kind == m1.USABLE
    assert disp[0].time_provenance == "EVN-2 (Erfassungs-Ersatz)"
    assert forwarded == [(1, "A01", "EVN-2 (Erfassungs-Ersatz)")], "provenance reaches M-2"
    # durable on the disposition (survives a reload)
    assert mstore.get_disposition(1).time_provenance == "EVN-2 (Erfassungs-Ersatz)"


# --- M1 Mapper-DB erasure (SILD-SF-1-analog, reuses SILD's erase semantics) ---

def _map_holds(tmp_path, messages):
    """Seed intake, run M-1 once so the holds land in the Mapper-DB, return store."""
    _seed_intake(tmp_path, messages)
    reader, mstore, mapper = _make_mapper(tmp_path)
    mapper.poll_once()
    return mstore


def test_m1_erase_x_gone_y_intact(tmp_path):
    mstore = _map_holds(tmp_path, [HOLD_X, HOLD_X2, HOLD_Y])
    assert mstore.counts()["holds"] == 3
    result = mstore.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 2, "both of patient X's held messages deleted"
    assert result.status == "complete", "no unattributable hold -> complete"
    assert mstore.counts()["holds"] == 1, "only patient Y's hold remains"
    assert mstore.erase_patient(PATIENT_Y_KEY, commit=False).deleted == 1, "Y intact"
    assert mstore.erase_patient(PATIENT_X_KEY, commit=False).deleted == 0, "X fully gone"


def test_m1_erase_patientless_holds_do_not_block_completeness(tmp_path):
    """A patientless hold (no PID-3 — e.g. a malformed technical message) belongs
    to NO patient, so it must NOT make X's erasure incomplete (no global count)."""
    mstore = _map_holds(tmp_path, [HOLD_X, HOLD_NOPID_A, HOLD_NOPID_B])
    result = mstore.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 1
    assert result.unresolvable == 0, "patientless holds are not residual risk"
    assert result.status == "complete"


def test_m1_erase_broken_pid3_is_residual_incomplete(tmp_path):
    """Only a PRESENT-but-unreadable PID-3 (could be X) forces incomplete_uncertain."""
    mstore = _map_holds(tmp_path, [HOLD_X, HOLD_BROKEN])
    result = mstore.erase_patient(PATIENT_X_KEY, commit=True)
    assert result.deleted == 1
    assert result.unresolvable == 1, "the unreadable-PID hold could be X -> residual"
    assert result.status == "incomplete_uncertain", "fail-closed on the real uncertain"


def test_m1_erase_dry_run_deletes_nothing(tmp_path):
    mstore = _map_holds(tmp_path, [HOLD_X, HOLD_X2])
    before = mstore.counts()["holds"]
    result = mstore.erase_patient(PATIENT_X_KEY, commit=False)
    assert result.dry_run is True
    assert result.deleted == 2, "reports what WOULD be deleted"
    assert mstore.counts()["holds"] == before, "dry-run deletes nothing"


def test_m1_erase_audit_has_no_content(tmp_path):
    mstore = _map_holds(tmp_path, [HOLD_X_SECRET])
    # the held raw carries the secret (PID), but the erase audit must not
    assert SECRET_TOKEN.encode() in mstore.get_hold_raw(1), "held raw holds the PID"
    result = mstore.erase_patient(PATIENT_X_KEY, commit=True)
    record = build_erase_audit_record(result)
    line = json.dumps(record, ensure_ascii=False)
    assert SECRET_TOKEN not in line, "erase audit must not contain the deleted payload/PII"
    assert "raw" not in record and "payload" not in record
    assert record["patient_key"] == PATIENT_X_KEY and record["deleted"] == 1


# --- small helpers ------------------------------------------------------------

def _good_time():
    """A segment carrying a good movement time in a DEFAULT field (PV1-44)."""
    return _seg("PV1", {44: "20260610100000"})
