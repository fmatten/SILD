"""
Named proofs for M-4 (Pull-Kontrakt SILD->AION, SILD-Seite).

Ein Test pro Pflicht-Garantie M4-G1..G7. Die Tests lesen die Pull-Flaeche so,
wie B.1b es vertraglich darf: per SQL auf die drei Views (read-only-Sicht der
M-2-DB) — NICHT ueber die internen Python-Methoden. Damit pruefen sie gegen
das richtige Ziel: den Kontrakt (docs/aion-pull-contract.md), nicht die
Implementierung.

Run:  pytest tests/test_mapper_m4.py -v
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from sild_durable_store import SimulatedCrash
from sild_mapper_m2 import (
    CHANGE_ESTIMATE_UPDATED,
    M2Store,
    MapperM2,
    PROV_ESTIMATED,
)
from tests.mapper_m2_vectors import corpus_msg, iso
from tests.mapper_m2c_vectors import (
    CHAIN_A01,
    CHAIN_A02,
    CHAIN_A03,
    P_BASE,
    STORNO_A12_OK,
)
from tests.mapper_m3_vectors import (
    EST_A08_MOVE_T2,
    OVL_A01_A,
    OVL_A01_B,
    P_EST,
    P_OVL,
    T0800,
    T1200,
    T1300,
)
from tests.mapper_m4_vectors import EXPECTED_VIEW_COLUMNS, G2_A03, G2_A13
from tests.test_mapper_m2 import _FakeNotifier, _direct, _feed, _feed_apply
from tests.test_mapper_m3 import _build_sandwich


def _q(tmp_path, sql, params=()):
    """Liest wie B.1b: SQL auf die Views, read-only."""
    with sqlite3.connect(f"file:{tmp_path / 'm2.sqlite'}?mode=ro", uri=True) as c:
        c.execute("PRAGMA query_only=ON")
        return c.execute(sql, params).fetchall()


def _revision(tmp_path, stay_id):
    return _q(tmp_path, "SELECT revision FROM v_aion_stay WHERE stay_id=?",
              (stay_id,))[0][0]


# --- M4-G1: die Views SIND der Vertrag ----------------------------------------------

@pytest.mark.parametrize("view,expected", list(EXPECTED_VIEW_COLUMNS.items()),
                         ids=list(EXPECTED_VIEW_COLUMNS))
def test_m4g1_view_columns_are_the_contract(tmp_path, view, expected):
    """Die drei Views liefern exakt die im Kontrakt definierten Spalten —
    ein interner Schema-Refactor, der sie aendert, faellt HIER, bevor er
    B.1b bricht."""
    M2Store(tmp_path / "m2.sqlite").close()                  # Schema anlegen
    cols = [r[1] for r in _q(tmp_path, f"PRAGMA table_info({view})")]
    assert cols == expected, f"{view}: Vertragsflaeche veraendert"


# --- M4-G2: Revision an ALLEN 6 Stellen, atomar --------------------------------------

def test_m4g2_revision_bumps_at_all_six_sites(tmp_path):
    """Jede sichtbare Veraenderung erhoeht die Revision: (1) open_stay (A04),
    (2) advance (A01-Bindung), (3) close (A03), (5) apply_retro_plan (A13),
    (4) finalize_pending_to_c, (6) apply_derived_plan (Schaetzung) — gelesen
    ueber v_aion_stay (die Vertragsflaeche)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(1)])              # (1) A04 -> rev 1
    sid = store.stays_for_patient("UKH|P100001")[0].stay_id
    assert _revision(tmp_path, sid) == 1
    _feed_apply(mapper, clock, [corpus_msg(2)], start_rid=2) # (2) A01 bindet -> 2
    assert _revision(tmp_path, sid) == 2
    _feed_apply(mapper, clock, [G2_A03], start_rid=3)        # (3) A03 -> 3
    assert _revision(tmp_path, sid) == 3
    _feed_apply(mapper, clock, [G2_A13], start_rid=4)        # (5) Storno -> 4
    assert _revision(tmp_path, sid) == 4

    # (4) finalize_pending_to_c: zweiter Patient, A04 ohne A01.
    _feed_apply(mapper, clock, [corpus_msg(21)], start_rid=5)  # A04 P100004 -> rev 1
    sid2 = store.stays_for_patient("UKH|P100004")[0].stay_id
    assert _revision(tmp_path, sid2) == 1
    clock.advance(mapper.windows.join_window_s + 1)
    mapper.finalize_patterns()                               # -> Muster C -> 2
    assert _revision(tmp_path, sid2) == 2

    # (6) apply_derived_plan: das Sandwich (eigene DB, gleicher Beweis).
    store3, _, _, _ = _build_sandwich(tmp_path / "derived")
    sid3 = store3.stays_for_patient(P_EST)[0].stay_id
    assert _revision(tmp_path / "derived", sid3) == 3, \
        "A01 open (1) + A03 close (2) + Schaetzung angewandt (3)"


def test_m4g2_revision_atomic_with_mutation_crash_proof(tmp_path):
    """(Review-Fokus a) Crash zwischen Intent und Mutation: KEIN Bump ohne
    Zustand — die Revision bleibt unveraendert und v_aion_change leer; der
    Neustart liefert Bump + Payload atomar mit der Mutation."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    sid = store.stays_for_patient(P_BASE)[0].stay_id
    assert _revision(tmp_path, sid) == 3
    _feed(mapper, [STORNO_A12_OK], start_rid=4)
    clock.advance(mapper.windows.jitter_window_s + 1)
    with pytest.raises(SimulatedCrash):
        mapper.apply_ripe(_crash_after_intent_at=4)
    assert _revision(tmp_path, sid) == 3, "kein Bump ohne Mutation (gleiche Txn)"
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change WHERE stay_id=?",
              (sid,))[0][0] == 0, "keine Aenderungs-Zeile ohne Zustand"

    store2 = M2Store(tmp_path / "m2.sqlite")                 # Neustart
    MapperM2(None, store2, _FakeNotifier(), now_fn=clock).apply_ripe()
    assert _revision(tmp_path, sid) == 4, "Mutation + Bump genau einmal"
    rows = _q(tmp_path, "SELECT revision, kind FROM v_aion_change WHERE stay_id=?",
              (sid,))
    assert rows == [(4, "remove_boundary")], "Payload traegt exakt die Bump-Revision"


# --- M4-G3: wirksame Aenderung -> Strom; No-Op still ----------------------------------

def test_m4g3_noop_silent_effective_exactly_one_notification(tmp_path):
    """No-Op-Neuableitung: kein Bump, kein Strom-Eintrag. Wirksame Aenderung
    (A08 verschiebt die Schranke): Revision+1 und GENAU EINE
    estimate_updated-Zeile."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    sid = store.stays_for_patient(P_EST)[0].stay_id
    rev0 = _revision(tmp_path, sid)
    changes0 = _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change")[0][0]

    mapper.process_estimates()                               # No-Op
    assert _revision(tmp_path, sid) == rev0, "No-Op: kein Bump"
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change")[0][0] == changes0, \
        "No-Op: kein Strom-Eintrag (kein Rauschen)"

    _feed_apply(mapper, clock, [EST_A08_MOVE_T2], start_rid=4)   # wirksam (2 Aenderungen:
    mapper.process_estimates()                                   # A08-Mutation + Neuableitung)
    updated = _q(tmp_path,
                 "SELECT revision FROM v_aion_change WHERE kind=?",
                 (CHANGE_ESTIMATE_UPDATED,))
    assert len(updated) == 1, "genau EINE estimate_updated-Benachrichtigung"
    assert _revision(tmp_path, sid) == rev0 + 2, "A08-Mutation +1, Neuableitung +1"
    assert updated[0][0] == rev0 + 2, "Strom-Zeile traegt die erzeugte Revision"

    mapper.process_estimates()                               # wieder No-Op
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change WHERE kind=?",
              (CHANGE_ESTIMATE_UPDATED,))[0][0] == 1, "idempotent: keine zweite"


# --- M4-G4 (K1): vollstaendiger Zustand, ohne Vorwissen verarbeitbar -----------------

def test_m4g4_change_row_self_explaining(tmp_path):
    """Eine v_aion_change-Zeile traegt den VOLLSTAENDIGEN neuen Stay-Zustand:
    ein Konsument, der den Stay NIE zuvor gesehen hat, kann ihn allein aus
    after_json rekonstruieren — feld-gleich mit Strom 1 derselben Revision.
    PID-frei."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    sid = store.stays_for_patient(P_BASE)[0].stay_id

    (notif_id, revision, kind, after_json) = _q(
        tmp_path, "SELECT notification_id, revision, kind, after_json "
                  "FROM v_aion_change WHERE stay_id=?", (sid,))[0]
    assert kind == "remove_boundary"
    state = json.loads(after_json)                           # NUR aus der Zeile
    assert state["stay"]["status"] == "closed"
    assert [(s["ward"], s["start_ts"], s["end_ts"]) for s in state["segments"]] == \
        [("KAR", iso("20260612080000"), iso("20260612100000"))], \
        "vollstaendige Segmentliste ohne Vorwissen"
    # feld-gleich mit Strom 1 derselben Revision:
    live = _q(tmp_path, "SELECT ward, start_ts, end_ts, revision FROM v_aion_segment "
                        "WHERE stay_id=? ORDER BY seq", (sid,))
    assert [(w, s, e) for (w, s, e, _) in live] == \
        [(s["ward"], s["start_ts"], s["end_ts"]) for s in state["segments"]]
    assert live[0][3] == revision
    assert "patient" not in after_json and "P910001" not in after_json, "PID-frei"


# --- M4-G5 (K2): (stay_id, revision) stabil + eindeutig ------------------------------

def test_m4g5_stay_id_revision_unique_and_stable(tmp_path):
    """Idempotenter Konsum: (stay_id, revision) ist im Aenderungs-Strom
    eindeutig; doppelt gelesene Zeile ist als dieselbe erkennbar; mehrere
    Aenderungen desselben Stays tragen strikt verschiedene Revisionen."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    _feed_apply(mapper, clock, [EST_A08_MOVE_T2], start_rid=4)
    mapper.process_estimates()
    dupes = _q(tmp_path, "SELECT stay_id, revision, COUNT(*) FROM v_aion_change "
                         "GROUP BY stay_id, revision HAVING COUNT(*) > 1")
    assert dupes == [], "(stay_id, revision) eindeutig"
    twice_a = _q(tmp_path, "SELECT * FROM v_aion_change ORDER BY notification_id")
    twice_b = _q(tmp_path, "SELECT * FROM v_aion_change ORDER BY notification_id")
    assert twice_a == twice_b, "doppelt gelesen = identisch (Dedup-faehig)"
    revs = [r[0] for r in _q(tmp_path, "SELECT revision FROM v_aion_change "
                                       "ORDER BY notification_id")]
    assert revs == sorted(revs) and len(set(revs)) == len(revs), \
        "Revisionen je Aenderung strikt verschieden"


# --- M4-G6: PROV_ESTIMATED ueber den View ausschliessbar -----------------------------

def test_m4g6_estimated_excludable_via_view(tmp_path):
    """(epsilon-DP-Schutz) Der Kontrakt-Filter auf v_aion_segment liefert NUR
    Grenzen ohne Schaetzung; geschaetzte Zeilen tragen ihre Schranken +
    Quellen direkt an der Zeile."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    _feed_apply(mapper, clock, [OVL_A01_A], start_rid=10)    # sauberer Vergleichs-Stay
    clean = _q(tmp_path,
               "SELECT ward FROM v_aion_segment "
               "WHERE start_provenance != ? "
               "AND (end_provenance IS NULL OR end_provenance != ?)",
               (PROV_ESTIMATED, PROV_ESTIMATED))
    assert [r[0] for r in clean] == ["ST1"], \
        "Kontrakt-Filter: nur der ungeschaetzte Stay besteht"
    est_rows = _q(tmp_path,
                  "SELECT ward, estimate_lower, estimate_upper, "
                  "estimate_lower_source, estimate_upper_source FROM v_aion_segment "
                  "WHERE estimate_lower IS NOT NULL ORDER BY seq")
    assert est_rows == [("KAR", iso(T0800), iso(T1200), 1, 3),
                        ("IMC", iso(T0800), iso(T1200), 1, 3)], \
        "Schranken + Quellen direkt an der geschaetzten Zeile (M3-G4 via View)"


def test_m4_view_markers_exposed(tmp_path):
    """Plausibilitaets-Marker erscheinen an der Vertragsflaeche (defensive
    Behandlung ist AION-Pflicht, Kontrakt §6.3)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [OVL_A01_A, OVL_A01_B])
    mapper.reassess_plausibility()
    marked = _q(tmp_path, "SELECT stay_markers FROM v_aion_stay ORDER BY stay_id")
    assert all("overlapping_open_stays" in (m[0] or "") for m in marked)


# --- M4-G7: Erasure-sauber ------------------------------------------------------------

def test_m4g7_erasure_covers_revision_and_payload(tmp_path):
    """stay_revision (reiner Zaehler) und change_payload (Quasi-Identifikator)
    verschwinden mit dem Patienten; v_aion_change liefert danach nichts mehr
    fuer den Stay — AION muss verschwundene stay_ids tolerieren (Kontrakt
    §6.6). SPURLOSIGKEIT positiv belegt (Kontrakt §6.7): Erasure erzeugt
    KEINERLEI neue Strom-Zeile — auch keine 'Stay geloescht'-Benachrichtigung
    (waere selbst ein Re-Verknuepfungs-Residuum, SF-2)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [CHAIN_A01, CHAIN_A02, CHAIN_A03])
    _feed_apply(mapper, clock, [STORNO_A12_OK], start_rid=4)
    sid = store.stays_for_patient(P_BASE)[0].stay_id
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change WHERE stay_id=?",
              (sid,))[0][0] == 1
    notifs_before = _q(tmp_path, "SELECT COUNT(*) FROM retro_notification")[0][0]
    changes_before = _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change")[0][0]

    store.erase_patient(P_BASE, commit=True)
    for table in ("stay_revision", "change_payload"):
        assert _q(tmp_path, f"SELECT COUNT(*) FROM {table} WHERE stay_id=?",
                  (sid,))[0][0] == 0, f"{table}: kein Residuum"
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change WHERE stay_id=?",
              (sid,))[0][0] == 0
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_stay WHERE stay_id=?",
              (sid,))[0][0] == 0
    # Spurlosigkeit positiv (nicht nur ueber stay_id gefiltert): die Erasure
    # hat NICHTS Neues in den Strom geschrieben — Notifications sind nicht
    # GEWACHSEN (nur geschrumpft), v_aion_change ist komplett leer.
    assert _q(tmp_path, "SELECT COUNT(*) FROM retro_notification")[0][0] < notifs_before, \
        "Erasure loescht, sie benachrichtigt NICHT"
    assert _q(tmp_path, "SELECT COUNT(*) FROM v_aion_change")[0][0] == changes_before - 1 == 0, \
        "kein Strom-Eintrag jedweder Art durch die Erasure (auch nicht mit anderer stay_id)"
