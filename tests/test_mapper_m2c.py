"""
Named proofs for M-2 Stufe 2 (M2c — revidierbarer Intervall-Kern).

Ein Test pro Pflicht-Garantie M2c-G1..G8 (Briefing §9) + A08 + Erasure.
Harness wiederverwendet aus tests/test_mapper_m2.py — insbesondere das
m1.classify==usable-Gate fuer jede direkt eingespeiste Fixture (die Tests
pruefen gegen das richtige Ziel: nur Events, die M-1 weiterreichen WUERDE).

Run:  pytest tests/test_mapper_m2c.py -v
"""
from __future__ import annotations

import json
import sqlite3

import pytest

import sild_mapper_m1 as m1
import sild_mapper_m2 as m2mod
from sild_durable_store import SimulatedCrash
from sild_mapper_m2 import (
    EV_HELD,
    EV_TOMBSTONED,
    FINDING_RETRO_FAILCLOSED,
    FINDING_TOMBSTONE_EXPIRED,
    M2Store,
    MapperM2,
    OUT_SUPPRESSED,
    RETRO_INSERT_BOUNDARY,
    STAY_CANCELLED,
)
from tests.mapper_m2_vectors import FIXED_NOW_M2, iso
from tests.mapper_m2c_vectors import (
    A08_MOVE_BOUNDARY,
    CHAIN_A01,
    CHAIN_A02,
    CHAIN_A03,
    G4_AMB_A,
    G4_AMB_B,
    G4_AMB_STORNO,
    G4_DECOY_A01,
    G4_STORNO,
    G4_TARGET_A01,
    L8_A01,
    L8_A03,
    L8_LATE_A02,
    P_BASE,
    P_L8,
    STORNO_A11_OK,
    STORNO_A12_OK,
    STORNO_A13_OK,
    STORNO_BAD_ZST3,
    STORNO_NO_ZST,
    T0930,
    TB_A01,
    TB_A02,
    TB_STORNO,
)
from tests.test_mapper_m2 import (  # geteilter Harness (inkl. classify-Gate)
    _FakeNotifier,
    _direct,
    _feed,
    _feed_apply,
    _single_stay,
)


def _retro_sent(notifier) -> list:
    return [(s, b) for s, b in notifier.sent if "Rueckwirkung" in s]


def _pending_status(tmp_path, pending_id=1):
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        return c.execute("SELECT status FROM pending_retro WHERE pending_id=?",
                         (pending_id,)).fetchone()[0]


# --- M2c-G3: die drei Storno-Mutationen ------------------------------------------

def test_m2c_g3_a11_revokes_whole_stay(tmp_path):
    """A11 (storniert A01): der GANZE Aufenthalt faellt — alle Segmente weg,
    stay als 'cancelled' markiert; Benachrichtigung traegt alt->neu."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02])           # offener stay, 2 Segmente
    _feed_apply(mapper, clock, [STORNO_A11_OK], start_rid=3)
    stay, segs = _single_stay(store, P_BASE)
    assert stay.status == STAY_CANCELLED
    assert segs == [], "alle Segmente fallen"
    assert store.counts()["retro_audits"] == 1
    subject, body = _retro_sent(notifier)[0]
    assert "revoke_stay" in subject
    assert "(keine — Aufenthalt storniert)" in body


def test_m2c_g3_a12_merges_boundary_back(tmp_path):
    """A12 (storniert A02): die A02-Segmentgrenze faellt — die zwei
    angrenzenden Segmente verschmelzen wieder zu einem (Vorgaenger erbt das
    Ende des Nachfolgers, gleiche Segment-Identitaet)."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])  # geschlossen, 2 Seg
    _, segs_before = _single_stay(store, P_BASE)
    kar_id = segs_before[0].segment_id
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    stay, segs = _single_stay(store, P_BASE)
    assert stay.status == "closed", "der Aufenthalt selbst bleibt"
    assert len(segs) == 1, "Grenze entfernt -> EIN Segment"
    assert segs[0].segment_id == kar_id, "Vorgaenger-Zeile blieb dieselbe (Mutation in place)"
    assert segs[0].ward == "KAR"
    assert segs[0].start_ts == iso("20260612080000")
    assert segs[0].end_ts == iso("20260612100000"), "erbt das A03-Ende des Nachfolgers"
    assert _retro_sent(notifier), "Benachrichtigung zugestellt"


def test_m2c_g3_a13_reopens_last_segment(tmp_path):
    """A13 (storniert A03): das durch das A03 geschlossene letzte Segment ist
    wieder OFFEN (Ende -> NULL), der stay wieder offen."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A13_OK], start_rid=4)
    stay, segs = _single_stay(store, P_BASE)
    assert stay.status == "open" and stay.closed_event_ts is None
    assert len(segs) == 2
    assert segs[1].end_ts is None and segs[1].end_provenance is None, \
        "letztes Segment wieder offen (NULL-Ende, M2-G6-konform)"


# --- A08: Grenze verschieben (derselbe mutate-Kern) -------------------------------

def test_m2c_a08_update_moves_boundary(tmp_path):
    """A08 (ZST-1=UPDATES) verschiebt die referenzierte Grenze auf seine eigene
    Bewegungszeit — BEIDE Grenzseiten (Vorgaenger-Ende + Nachfolger-Start)."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [A08_MOVE_BOUNDARY], start_rid=4)
    _, segs = _single_stay(store, P_BASE)
    assert segs[0].end_ts == iso(T0930) and segs[1].start_ts == iso(T0930), \
        "eine Grenze, zwei Seiten — beide verschoben"
    assert segs[0].end_provenance == m1.PROV_EVENT, "Provenienz der NEUEN Zeit (A08 EVN-6)"
    assert "change_boundary" in _retro_sent(notifier)[0][0]


# --- M2c-G4: ZST-Zielbindung eindeutig ---------------------------------------------

def test_m2c_g4_msh10_duplicate_not_hit(tmp_path):
    """Ein Decoy mit GLEICHEM MSH-10, aber anderem Patient/Zeit (anderer
    Absender) wird NICHT getroffen — die Bindung verlangt ALLE Felder."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [G4_TARGET_A01, G4_DECOY_A01])
    _feed_apply(mapper, clock, [G4_STORNO], start_rid=3)
    target_stay, target_segs = _single_stay(store, "UKH|P910001")
    decoy_stay, decoy_segs = _single_stay(store, "UKH|P910002")
    assert target_stay.status == STAY_CANCELLED and target_segs == []
    assert decoy_stay.status == "open" and len(decoy_segs) == 1, \
        "der Decoy (gleiches MSH-10) bleibt unberuehrt"


def test_m2c_g4_full_duplicate_is_ambiguous_failclosed(tmp_path):
    """Treffen MEHRERE Events in ALLEN Feldern (MSH-10+Typ+Zeit+Patient),
    ist die Bindung mehrdeutig -> fail-closed Hold, NICHTS wird mutiert."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [G4_AMB_A, G4_AMB_B])
    _feed_apply(mapper, clock, [G4_AMB_STORNO], start_rid=3)
    stays = store.stays_for_patient("UKH|P910003")
    assert [s.status for s in stays] == ["open", "open"], "beide Aufenthalte unberuehrt"
    assert store.counts()["retro_audits"] == 0, "KEINE Mutation bei Mehrdeutigkeit"
    assert store.event_status(3)[0] == EV_HELD
    assert any("mehrdeutig" in b for _, b in notifier.sent)


# --- M2c-G5: fail-closed ohne/mit ungueltigem ZST ----------------------------------

@pytest.mark.parametrize("bad_storno,expected_hint", [
    (STORNO_NO_ZST, "ZST fehlt"),
    (STORNO_BAD_ZST3, "passt nicht"),
], ids=["zst-fehlt", "zst3-typ-mismatch"])
def test_m2c_g5_failclosed_no_four_field_attempt(tmp_path, bad_storno, expected_hint):
    """Storno ohne/mit ungueltigem ZST -> Hold + Befund, KEINE Mutation — und
    BEWUSST kein Vier-Felder-Matching als Fallback (das Ziel waere ueber
    Patient+Zeit auffindbar gewesen; es wird trotzdem NICHT angefasst)."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02])
    _feed_apply(mapper, clock, [bad_storno], start_rid=3)
    stay, segs = _single_stay(store, P_BASE)
    assert stay.status == "open" and len(segs) == 2, "nichts mutiert"
    assert store.counts()["retro_audits"] == 0
    assert store.event_status(3)[0] == EV_HELD
    assert any(FINDING_RETRO_FAILCLOSED in s and expected_hint in b
               for s, b in notifier.sent)


# --- M2c-G6: wartende Negation (A12 vor A02) ---------------------------------------

def test_m2c_g6_tombstone_resolves_when_target_arrives(tmp_path):
    """Out-of-Order (A12 VOR A02, ein Batch): das Storno wird zur wartenden
    Negation; kommt das exakt referenzierte A02, wird es angewandt und sofort
    wieder aufgehoben — netto bleibt EIN Segment."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [TB_A01, TB_STORNO, TB_A02])      # Event-Zeit-sortiert:
    stay, segs = _single_stay(store, "UKH|P910010")              # A01, A12, A02
    assert len(segs) == 1 and segs[0].ward == "KAR" and segs[0].end_ts is None, \
        "A02 angewandt UND automatisch negiert -> wie nie geschehen"
    assert _pending_status(tmp_path) == "resolved"
    assert store.counts()["retro_audits"] == 1
    assert len(_retro_sent(notifier)) == 1


def test_m2c_g6_tombstone_survives_restart(tmp_path):
    """Die wartende Negation ist durabel: Neustart zwischen Storno und Ziel —
    die Aufhebung passiert trotzdem."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [TB_A01, TB_STORNO])
    assert store.event_status(2)[0] == EV_TOMBSTONED
    assert _pending_status(tmp_path) == "waiting"

    store2 = M2Store(tmp_path / "m2.sqlite")                     # Neustart
    notifier2 = _FakeNotifier()
    mapper2 = MapperM2(None, store2, notifier2, now_fn=clock)
    _feed_apply(mapper2, clock, [TB_A02], start_rid=3)
    _, segs = _single_stay(store2, "UKH|P910010")
    assert len(segs) == 1 and segs[0].end_ts is None
    assert _pending_status(tmp_path) == "resolved"


def test_m2c_g6_ttl_expires_finding_then_still_cancels(tmp_path):
    """TTL abgelaufen -> PID-freier Befund (technisches Faktum), die Negation
    bleibt als 'expired' LIEGEN — und ein SEHR spaet kommendes Ziel wird
    trotzdem noch storniert."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [TB_A01, TB_STORNO])
    clock.advance(mapper.windows.tombstone_wait_ttl_s + 1)
    assert mapper.expire_tombstones() == 1
    assert mapper.expire_tombstones() == 0, "Befund genau einmal"
    subject, body = notifier.sent[-1]
    assert FINDING_TOMBSTONE_EXPIRED in subject
    assert "MSH-10=TB-A02" in body and "erhielt nie sein Zielereignis" in body
    assert "P910010" not in subject + body, "Befund ist PID-frei"
    assert _pending_status(tmp_path) == "expired", "bleibt liegen, nicht geloescht"

    _feed_apply(mapper, clock, [TB_A02], start_rid=3)            # Ziel kommt SEHR spaet
    _, segs = _single_stay(store, "UKH|P910010")
    assert len(segs) == 1 and segs[0].end_ts is None, \
        "expired Negation storniert das spaete Ziel trotzdem noch"
    assert _pending_status(tmp_path) == "resolved"


# --- M2c-G1: persist-before-mutate (Crash echt) ------------------------------------

def test_m2c_g1_crash_between_intent_and_mutation(tmp_path):
    """(Review-Fokus a) Crash ZWISCHEN durablem alt->neu-Vermerk und Mutation:
    der alte Stand ist aus before_json rekonstruierbar UND die Benachrichtigung
    steht aus (pending, nicht verloren). Der Neustart vollendet die Mutation
    GENAU EINMAL mit GENAU EINER Zustellung."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed(mapper, [STORNO_A12_OK], start_rid=4)
    clock.advance(mapper.windows.jitter_window_s + 1)
    with pytest.raises(SimulatedCrash):
        mapper.apply_ripe(_crash_after_intent_at=4)

    _, segs = _single_stay(store, P_BASE)
    assert len(segs) == 2, "Mutation NICHT passiert (Crash davor)"
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        applied, before_json = c.execute(
            "SELECT applied, before_json FROM retro_audit WHERE receipt_id=4").fetchone()
        notif_status = c.execute(
            "SELECT delivery_status FROM retro_notification WHERE receipt_id=4"
        ).fetchone()[0]
    assert applied == 0, "Vermerk durabel, Mutation offen"
    before = json.loads(before_json)
    assert [s["start_ts"] for s in before["segments"]] == \
        [seg.start_ts for seg in segs], "alter Stand aus before_json rekonstruierbar"
    assert notif_status == "pending", "Benachrichtigung steht aus, nicht verloren"
    assert _retro_sent(notifier) == [], "vor der Mutation wird NICHT zugestellt"

    store2 = M2Store(tmp_path / "m2.sqlite")                     # Neustart
    notifier2 = _FakeNotifier()
    mapper2 = MapperM2(None, store2, notifier2, now_fn=clock)
    mapper2.apply_ripe()
    _, segs2 = _single_stay(store2, P_BASE)
    assert len(segs2) == 1, "Mutation genau einmal vollendet"
    assert store2.counts()["retro_audits"] == 1, "kein zweiter Vermerk (Resume)"
    assert len(_retro_sent(notifier2)) == 1, "genau EINE Zustellung"
    assert store2.pending_retro_notifications() == []


# --- M2c-G2: Idempotenz dreifach ----------------------------------------------------

def test_m2c_g2_idempotent_threefold(tmp_path):
    """(Review-Fokus b) receipt-Duplikat, Marker-Duplikat und Neustart -> genau
    EINE Mutation, EINE Benachrichtigung."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    _, segs = _single_stay(store, P_BASE)
    assert len(segs) == 1

    c = m1.classify(STORNO_A12_OK, now=FIXED_NOW_M2)
    assert mapper.ingest_usable(4, STORNO_A12_OK, c.trigger) == "buffered", \
        "receipt-Duplikat: bestehender Vermerk, nichts Neues"
    assert mapper.ingest_usable(99, STORNO_A12_OK, c.trigger) == OUT_SUPPRESSED, \
        "Marker-Duplikat: Event-Identitaet schon verarbeitet"

    store2 = M2Store(tmp_path / "m2.sqlite")                     # Neustart
    mapper2 = MapperM2(None, store2, _FakeNotifier(), now_fn=clock)
    assert mapper2.ingest_usable(100, STORNO_A12_OK, c.trigger) == OUT_SUPPRESSED
    clock.advance(mapper2.windows.jitter_window_s + 1)
    mapper2.apply_ripe()
    _, segs2 = _single_stay(store2, P_BASE)
    assert len(segs2) == 1, "immer noch EINE Mutation"
    assert store2.counts()["retro_audits"] == 1
    assert store2.counts()["retro_notifications"] == 1, "EINE Benachrichtigung"
    assert len(_retro_sent(notifier)) == 1


# --- M2c-G7: Benachrichtigung (Fehlschlag verliert nichts, PID-frei, Faktum) --------

def test_m2c_g7_notification_failure_loses_nothing_pid_free(tmp_path):
    """Zustell-Fehlschlag: die Mutation ist durch, die Benachrichtigung bleibt
    durabel ausstehend und ist nachzustellen. Inhalt: Faktum alt->neu, PID-frei,
    Bewertung explizit an AION delegiert."""
    store, mapper, clock, notifier = _direct(tmp_path)
    notifier.fail = True
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    _, segs = _single_stay(store, P_BASE)
    assert len(segs) == 1, "Mutation unabhaengig vom Mail-Kanal"
    assert len(store.pending_retro_notifications()) == 1, "ausstehend, nicht verloren"

    notifier.fail = False
    assert mapper.redeliver_pending_retro() == 1
    assert store.pending_retro_notifications() == []

    subject, body = _retro_sent(notifier)[-1]
    assert "P910001" not in subject + body, "PID-frei (kein Patienten-Schluessel)"
    assert "V910001" not in body, "auch die Visit bleibt draussen"
    assert "Segmente VORHER" in body and "Segmente NACHHER" in body, "Faktum alt->neu"
    assert "entscheidet AION" in body, "Bewertung delegiert, nicht selbst getroffen"


# --- M2c-G8: verspaetetes Normal-Event ----------------------------------------------

def test_m2c_g8_late_a02_inserted_into_past(tmp_path):
    """Verspaetetes A02 nach dem Festschreiben (Aufenthalt schon geschlossen):
    derselbe mutate-Kern fuegt das Segment in die Vergangenheit ein (Split an
    der Grenzzeit) + Benachrichtigung."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [L8_A01, L8_A03])                 # geschlossen, 1 Segment
    _feed_apply(mapper, clock, [L8_LATE_A02], start_rid=3)       # 10:00, mitten drin
    stay, segs = _single_stay(store, P_L8)
    assert stay.status == "closed", "der Abschluss bleibt"
    assert [(s.ward, s.start_ts, s.end_ts) for s in segs] == [
        ("KAR", iso("20260612080000"), iso("20260612100000")),
        ("IMC", iso("20260612100000"), iso("20260612120000")),
    ], "Segment in die Vergangenheit eingefuegt (Split an 10:00)"
    assert segs[0].end_provenance == m1.PROV_MEASURED, "Grenz-Provenienz vom A02 (ZBE-2)"
    subject, _ = _retro_sent(notifier)[0]
    assert RETRO_INSERT_BOUNDARY in subject


def test_m2c_g2_cursor_discipline_end_to_end(tmp_path):
    """A2-Erbe auf dem ECHTEN Pfad (intake -> M-1 -> M-2): Crash nach dem
    durablen Vermerk des Stornos, VOR dem Cursor -> der Re-Scan nach Neustart
    ist idempotent (keine Doppel-Einlagerung), die Mutation passiert genau
    einmal, der Cursor rueckt im sauberen Lauf nach."""
    from sild_durable_store import DurableStore, extract_marker
    from sild_mapper_m2 import M1OutputReader
    from tests.test_mapper_m2 import _Clock

    clock = _Clock(FIXED_NOW_M2)
    intake = DurableStore(tmp_path / "intake.sqlite")
    for raw in [CHAIN_A01, CHAIN_A02, CHAIN_A03, STORNO_A12_OK]:
        intake.persist(raw, extract_marker(raw))
    m1_mapper = m1.MapperM1(m1.IntakeReader(tmp_path / "intake.sqlite"),
                            m1.MapperStore(tmp_path / "m1.sqlite"),
                            _FakeNotifier(), now_fn=clock)
    m1_mapper.poll_once()                                        # alle 4 usable

    m2_store = M2Store(tmp_path / "m2.sqlite")
    m2 = MapperM2(M1OutputReader(tmp_path / "m1.sqlite", tmp_path / "intake.sqlite"),
                  m2_store, _FakeNotifier(), now_fn=clock)
    with pytest.raises(SimulatedCrash):
        m2.poll_once(_crash_before_cursor_at=4)                  # Storno vermerkt, Cursor nicht
    assert m2_store.processed_outcome(4) is not None
    assert m2_store.get_cursor() == 3

    store2 = M2Store(tmp_path / "m2.sqlite")                     # Neustart
    notifier2 = _FakeNotifier()
    m2b = MapperM2(M1OutputReader(tmp_path / "m1.sqlite", tmp_path / "intake.sqlite"),
                   store2, notifier2, now_fn=clock)
    m2b.poll_once()                                              # Re-Scan (idempotent)
    clock.advance(m2b.windows.jitter_window_s + 1)
    m2b.poll_once()                                              # Apply inkl. Storno
    assert store2.get_cursor() == 4
    _, segs = _single_stay(store2, P_BASE)
    assert len(segs) == 1, "Grenze entfernt — genau EINE Mutation trotz Re-Scan"
    assert store2.counts()["retro_audits"] == 1
    assert store2.counts()["retro_notifications"] == 1
    assert len(_retro_sent(notifier2)) == 1, "genau EINE Zustellung"


# --- V2 (SF-1): EIN Plan-Anwendungs-Pfad — vermerktes after == DB-Stand -------------

RETRO_OP_SCENARIOS = [
    ("revoke_stay",     [CHAIN_A01, CHAIN_A02],            STORNO_A11_OK),
    ("remove_boundary", [CHAIN_A01, CHAIN_A02, CHAIN_A03], STORNO_A12_OK),
    ("reopen_last",     [CHAIN_A01, CHAIN_A02, CHAIN_A03], STORNO_A13_OK),
    ("change_boundary", [CHAIN_A01, CHAIN_A02, CHAIN_A03], A08_MOVE_BOUNDARY),
    ("insert_boundary", [L8_A01, L8_A03],                  L8_LATE_A02),
]


def _strip_segment_ids(snapshot: dict) -> dict:
    """Vergleichsform: segment_id raus (ein INSERT hat im vorberechneten after
    noch keine), alles andere — Zeiten, Provenienzen, Receipts, seq — bleibt."""
    return {"stay": snapshot["stay"],
            "segments": [{k: v for k, v in s.items() if k != "segment_id"}
                         for s in snapshot["segments"]]}


@pytest.mark.parametrize("op,setup,trigger_msg", RETRO_OP_SCENARIOS,
                         ids=[s[0] for s in RETRO_OP_SCENARIOS])
def test_m2c_v2_recorded_after_equals_db_state(tmp_path, op, setup, trigger_msg):
    """SF-1-Bindung fuer JEDEN der 5 Plan-Ops: der VOR der Mutation durabel
    vermerkte after-Stand (after_json — speist auch die Benachrichtigung) ist
    feld-genau der tatsaechliche DB-Stand nach der Mutation. Seit der
    Vereinheitlichung ist die Mutation DERSELBE Plan-Anwender
    (apply_plan_to_snapshot, generisch zurueckgeschrieben) — dieser Test pinnt
    das gegen Regression (z.B. vergessene Spalte im Write-back)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, setup)
    rid = len(setup) + 1
    _feed_apply(mapper, clock, [trigger_msg], start_rid=rid)

    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        kind, stay_id, after_json, applied = c.execute(
            "SELECT kind, stay_id, after_json, applied FROM retro_audit "
            "WHERE receipt_id=?", (rid,)).fetchone()
    assert kind == op and applied == 1
    computed = json.loads(after_json)
    db_state = store.stay_snapshot(stay_id)
    assert _strip_segment_ids(computed) == _strip_segment_ids(db_state), \
        f"{op}: vermerktes/gemeldetes 'nachher' weicht vom DB-Stand ab"


# --- M2c: Erasure deckt die wartenden Negationen (PID) ------------------------------

def test_m2c_v1_erasure_leaves_nothing_relinkable(tmp_path):
    """SF-2-Verifikation: nach Erasure eines Patienten MIT Rueckwirkungs-
    Historie bleibt in KEINER der vier neuen Tabellen etwas Re-verknuepfbares
    (ZST-Referenz, Audit-Snapshots mit Standort+Zeit-Sequenzen, Notification-
    Bodies, Negationen) — waehrend die Retro-Historie eines ANDEREN Patienten
    intakt bleibt. Inhaltsfreies (delay_log/m2_processed/finding) bleibt."""
    store, mapper, clock, _ = _direct(tmp_path)
    # Patient A (P910001): Kette + A12-Storno -> Audit + Notification + ZST-Zeile.
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    # Patient B (P910020): verspaetetes A02 -> eigener Audit + Notification.
    _feed_apply(mapper, clock, [L8_A01, L8_A03], start_rid=5)
    _feed_apply(mapper, clock, [L8_LATE_A02], start_rid=7)
    pa_stay = store.stays_for_patient(P_BASE)[0].stay_id
    assert store.counts()["retro_audits"] == 2
    assert store.counts()["retro_notifications"] == 2

    result = store.erase_patient(P_BASE, commit=True)
    # 4 Events + 1 stay + 1 Segment (nach Merge) + 1 ZST + 1 Audit + 1 Notification
    assert result.deleted == 9, "alle re-verknuepfbaren Zeilen gezaehlt"
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        assert c.execute("SELECT COUNT(*) FROM m2_event_zst").fetchone()[0] == 0, \
            "ZST-Referenz des Stornos geloescht (keine verwaiste Quell-Referenz)"
        assert c.execute("SELECT COUNT(*) FROM retro_audit WHERE stay_id=?",
                         (pa_stay,)).fetchone()[0] == 0, \
            "kein verwaister Snapshot (Standort+Zeit-Sequenz) zum geloeschten stay"
        bodies = [r[0] for r in c.execute("SELECT body FROM retro_notification")]
        assert len(bodies) == 1 and f"stay {pa_stay}" not in bodies[0], \
            "nur Patient Bs Notification bleibt; nichts referenziert As stay"
        assert c.execute("SELECT COUNT(*) FROM retro_audit").fetchone()[0] == 1, \
            "Patient Bs Audit bleibt intakt"
    _, pb_segs = _single_stay(store, P_L8)
    assert len(pb_segs) == 2, "Patient B unberuehrt"
    assert store.counts()["delays"] > 0 and store.counts()["processed"] > 0, \
        "wirklich inhaltsfreies Audit (delay_log/processed) bleibt erhalten"


def test_m2c_erasure_covers_tombstones(tmp_path):
    """pending_retro traegt den Patienten-Schluessel -> Erasure loescht auch die
    wartenden Negationen; Audit/Benachrichtigung sind PID-frei und bleiben."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [TB_A01, TB_STORNO])              # stay + waiting Negation
    assert store.counts()["tombstones"] == 1
    result = store.erase_patient("UKH|P910010", commit=True)
    assert result.deleted >= 4, "Events + stay + Segment + Negation"
    assert store.counts()["tombstones"] == 0, "wartende Negation geloescht"
    assert store.stays_for_patient("UKH|P910010") == []
