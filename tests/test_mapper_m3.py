"""
Named proofs for M-2 Stufe 3 (M3 — Plausibilitaet + begrenzte Zeit-Schaetzung).

Ein Test pro Pflicht-Garantie M3-G1..G7 plus Marker-Vektoren, Idempotenz,
Erasure und ein End-to-end-Beweis ueber die ECHTE M-1-Hold-Queue mit
Korpus-Nachrichten. Harness aus tests/test_mapper_m2.py; ZWEI Gates:
Bewegungs-Fixtures muessen m1.classify == usable sein, zeitlose Fixtures
m1.classify == hold_timequality (richtige-Ziel-Pruefung in beide Richtungen).

Run:  pytest tests/test_mapper_m3.py -v
"""
from __future__ import annotations

import sqlite3

import pytest

import sild_mapper_m1 as m1
import sild_mapper_m2 as m2mod
from sild_mapper_m2 import (
    EST_ACTIVE,
    EST_REVERTED,
    EST_WAITING,
    FINDING_ESTIMATE_REVERT,
    FINDING_PLAUSIBILITY,
    M2Store,
    MapperM2,
    MARK_EXCESSIVE_DURATION,
    MARK_IMPLAUSIBLE_ORDER,
    MARK_NEGATIVE_DURATION,
    MARK_ORPHAN_TRANSFER,
    MARK_OVERLAPPING_OPEN,
    MARK_UNKNOWN_WARD,
    MARK_ZERO_DURATION,
    OUT_ESTIMATION_CANDIDATE,
    OUT_SUPPRESSED,
    PROV_ESTIMATED,
    PlausibilityConfig,
)
from tests.mapper_m2_vectors import FIXED_NOW_M2, corpus_msg, iso
from tests.mapper_m3_vectors import (
    EST_A01,
    EST_A03,
    EST_A08_MOVE_T2,
    EST_A13_CANCEL_T2,
    EST_TIMELESS,
    EXC_ITS_A01,
    EXC_ITS_A03,
    EXC_ST_A01,
    EXC_ST_A03,
    IMPL_A01,
    IMPL_A03,
    KNOWN_WARDS,
    ORPH_A02,
    ORPH_A04,
    OVL_A01_A,
    OVL_A01_B,
    P_EST,
    P_EXC_ITS,
    P_EXC_ST,
    P_IMPL,
    P_ORPH,
    P_OVL,
    P_UNKW,
    P_ZERO,
    T0800,
    T1000,
    T1200,
    T1300,
    UNKW_A01,
    ZERO_A01,
    ZERO_A03,
)
from tests.test_mapper_m2 import (
    _FakeNotifier,
    _direct,
    _feed,
    _feed_apply,
    _pipeline,
    _single_stay,
)


def _feed_hold(mapper, raws, *, start_rid):
    """Direkt-Einspeisung zeitloser Events. GATE: jede Fixture MUSS von M-1
    geholdet werden (hold_timequality) — sonst testeten wir am Hold vorbei."""
    outcomes = []
    for i, raw in enumerate(raws):
        c = m1.classify(raw, now=FIXED_NOW_M2)
        assert c.kind == m1.HOLD_TIMEQUALITY, \
            f"Hold-Fixture muss M-1-geholdet sein, war {c.kind}"
        outcomes.append(mapper.ingest_hold(start_rid + i, raw, c.trigger))
    return outcomes


def _marker_kinds(store, stay_id):
    return {(m["scope"], m["kind"]) for m in store.markers_for_stay(stay_id)}


def _build_sandwich(tmp_path):
    """A01 (rid 1) .. zeitloses A02 (rid 2) .. A03 (rid 3), angewandt +
    Schaetzungen abgeleitet."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed(mapper, [EST_A01], start_rid=1)
    assert _feed_hold(mapper, [EST_TIMELESS], start_rid=2) == [OUT_ESTIMATION_CANDIDATE]
    _feed(mapper, [EST_A03], start_rid=3)
    clock.advance(mapper.windows.jitter_window_s + 1)
    mapper.apply_ripe()
    mapper.process_estimates()
    return store, mapper, clock, notifier


# --- M3-G1/G2: markiert, NIE Hold, NIE reparieren -----------------------------------

def test_m3g1_negative_duration_marked_passed_through(tmp_path):
    """(Review-Fokus a) Entlassung VOR Aufnahme: das Artefakt wird mit
    ORIGINALZEITEN durchgelassen (Segment Ende < Start), durabel markiert
    (negative_duration + implausible_order) und NICHT geholdet."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [IMPL_A01])                 # Aufnahme 10:00
    _feed_apply(mapper, clock, [IMPL_A03], start_rid=2)    # Entlassung 08:00
    mapper.reassess_plausibility()

    stay, segs = _single_stay(store, P_IMPL)
    assert stay.status == "closed", "durchgelassen, nicht geholdet"
    assert store.event_status(2)[0] == m2mod.EV_APPLIED, "A03 angewandt, kein Hold"
    assert segs[0].start_ts == iso(T1000) and segs[0].end_ts == iso(T0800), \
        "ORIGINALZEITEN erhalten — kein Tausch, kein Klemmen"
    kinds = _marker_kinds(store, stay.stay_id)
    assert ("segment", MARK_NEGATIVE_DURATION) in kinds
    assert ("stay", MARK_IMPLAUSIBLE_ORDER) in kinds
    assert any(FINDING_PLAUSIBILITY in s for s, _ in notifier.sent), "Hinweis-Befund"


def test_m3g2_never_repaired_original_times_equal_event_times(tmp_path):
    """(Review-Fokus a) Beleg gegen Reparatur: die Segment-Grenzen sind
    feld-genau die ORIGINAL-Event-Zeiten aus dem Puffer — der Mapper hat
    nirgends 'korrigierte' Zeiten geschrieben."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [IMPL_A01])
    _feed_apply(mapper, clock, [IMPL_A03], start_rid=2)
    mapper.reassess_plausibility()
    _, segs = _single_stay(store, P_IMPL)
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        ev_times = dict(c.execute(
            "SELECT receipt_id, event_ts FROM m2_event").fetchall())
    assert segs[0].start_ts == ev_times[1], "Start == Original-A01-Zeit"
    assert segs[0].end_ts == ev_times[2], "Ende == Original-A03-Zeit (frueher!)"


def test_m3g6_plausibility_finding_pid_free_no_quasi_identifier(tmp_path):
    """(M3-G6) Der Hinweis-Befund traegt Marker-Art/stay/scope — KEINEN
    Patienten, KEINE Standort+Zeit-Paare (SF-2: Quasi-Identifikator bleibt
    DB-intern, nie im Mail-Kanal)."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [IMPL_A01])
    _feed_apply(mapper, clock, [IMPL_A03], start_rid=2)
    mapper.reassess_plausibility()
    bodies = " ".join(s + b for s, b in notifier.sent if FINDING_PLAUSIBILITY in s)
    assert bodies, "Befund vorhanden"
    assert "P920001" not in bodies, "PID-frei"
    assert "ST1" not in bodies, "kein Standort im Befund"
    assert "2026-06-12T10" not in bodies and "2026-06-12T08" not in bodies, \
        "keine Patienten-Zeitstempel im Befund"


@pytest.mark.parametrize("feeds,pkey,expected", [
    ([ZERO_A01, ZERO_A03], P_ZERO, ("segment", MARK_ZERO_DURATION)),
    ([ORPH_A04, ORPH_A02], P_ORPH, ("stay", MARK_ORPHAN_TRANSFER)),
], ids=["zero-duration", "orphan-transfer"])
def test_m3_marker_vectors(tmp_path, feeds, pkey, expected):
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, feeds)
    mapper.reassess_plausibility()
    stay, _ = _single_stay(store, pkey)
    assert expected in _marker_kinds(store, stay.stay_id)
    assert stay.status in ("open", "closed"), "durchgelassen (nie Hold)"


def test_m3_marker_overlapping_open_stays_marks_both(tmp_path):
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [OVL_A01_A, OVL_A01_B])
    mapper.reassess_plausibility()
    stays = store.stays_for_patient(P_OVL)
    assert len(stays) == 2
    for s in stays:
        assert ("stay", MARK_OVERLAPPING_OPEN) in _marker_kinds(store, s.stay_id), \
            "BEIDE gleichzeitig offenen Aufenthalte markiert"


def test_m3_marker_unknown_ward_is_site_configurable(tmp_path):
    """known_wards ist STANDORTSPEZIFISCH: ohne Konfiguration (Default None)
    prueft niemand; mit Liste wird der fremde Code markiert (nie geholdet)."""
    store, mapper, clock, _ = _direct(tmp_path)
    mapper.plausibility = PlausibilityConfig(known_wards=KNOWN_WARDS)
    _feed_apply(mapper, clock, [UNKW_A01])
    mapper.reassess_plausibility()
    stay, _ = _single_stay(store, P_UNKW)
    assert ("segment", MARK_UNKNOWN_WARD) in _marker_kinds(store, stay.stay_id)

    store2, mapper2, clock2, _ = _direct(tmp_path / "default")
    _feed_apply(mapper2, clock2, [UNKW_A01])
    mapper2.reassess_plausibility()
    stay2, _ = _single_stay(store2, P_UNKW)
    assert _marker_kinds(store2, stay2.stay_id) == set(), \
        "Default: Pruefung aus (eine falsche Liste markierte jeden legitimen Code)"


def test_m3_marker_excessive_duration_class_differentiated(tmp_path):
    """16 Tage: ueber der Stations-Schwelle (14d) -> Marker; auf ITS (60d)
    legitim -> KEIN Marker. NUR Marker, NIE Hold — beide durchgelassen."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [EXC_ST_A01, EXC_ST_A03, EXC_ITS_A01, EXC_ITS_A03])
    mapper.reassess_plausibility()
    st_stay, st_segs = _single_stay(store, P_EXC_ST)
    its_stay, its_segs = _single_stay(store, P_EXC_ITS)
    assert ("segment", MARK_EXCESSIVE_DURATION) in _marker_kinds(store, st_stay.stay_id)
    assert ("segment", MARK_EXCESSIVE_DURATION) not in _marker_kinds(store, its_stay.stay_id), \
        "langer ITS-Aufenthalt ist legitim (klassen-differenziert)"
    assert st_stay.status == "closed" and its_stay.status == "closed", "durchgelassen"
    assert st_segs[0].end_ts is not None and its_segs[0].end_ts is not None


def test_m3_markers_are_derived_not_frozen(tmp_path):
    """Marker werden bei jedem Neubau neu abgeleitet: hebt eine Stufe-2-
    Rueckwirkung die Unstimmigkeit auf (A13 storniert die zu fruehe
    Entlassung), verschwinden die Marker."""
    from tests.mapper_m2c_vectors import storno
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [IMPL_A01])
    _feed_apply(mapper, clock, [IMPL_A03], start_rid=2)
    mapper.reassess_plausibility()
    stay, _ = _single_stay(store, P_IMPL)
    assert _marker_kinds(store, stay.stay_id) != set()

    s13 = storno("A13", "M3-S13", pid="P920001", target_ctrl="M3-IA03",
                 target_trigger="A03", target_ts=T0800, ts=T1200)
    _feed_apply(mapper, clock, [s13], start_rid=3)
    mapper.reassess_plausibility()
    assert _marker_kinds(store, stay.stay_id) == set(), \
        "Storno der zu-fruehen Entlassung -> Unstimmigkeit weg -> Marker weg"


# --- M3-G3/G4: Schaetzung NUR beidseitig begrenzt, als Intervall --------------------

def test_m3g3_both_sided_clamp_yields_estimated_interval(tmp_path):
    """(Review-Fokus b+c) Das Sandwich A01..zeitloses A02..A03 wird
    eingeklemmt: Schranken [t1,t2] aus den live Nachbar-Grenzen, geliefert
    als INTERVALL (Maximal-Ausdehnungs-Kodierung, beide Grenzseiten
    PROV_ESTIMATED) — nie ein Punkt."""
    store, _, _, _ = _build_sandwich(tmp_path)
    est = store.get_estimate(2)
    assert est["status"] == EST_ACTIVE
    assert (est["lower_ts"], est["upper_ts"]) == (iso(T0800), iso(T1200))
    assert (est["lower_source_receipt"], est["upper_source_receipt"]) == (1, 3), \
        "Provenienz traegt die zwei Schranken-Quellen (M3-G4)"
    _, segs = _single_stay(store, P_EST)
    assert [s.ward for s in segs] == ["KAR", "IMC"]
    assert segs[0].end_ts == iso(T1200) and segs[0].end_provenance == PROV_ESTIMATED, \
        "Vorgaenger-Ende = OBERE Schranke (kein gewaehlter Punkt)"
    assert segs[1].start_ts == iso(T0800) and segs[1].start_provenance == PROV_ESTIMATED, \
        "Nachfolger-Start = UNTERE Schranke"
    assert segs[1].end_ts == iso(T1200) and segs[1].end_provenance == m1.PROV_EVENT, \
        "die gemessene/Ereignis-Seite bleibt unangetastet"


def test_m3g3_one_sided_stays_hold_until_bound_appears(tmp_path):
    """(Review-Fokus b) Fehlt eine Seite -> WEITER Hold (waiting, kein
    Segment-Eingriff). Kommt die fehlende Schranke spaeter, klemmt der
    naechste Ableitungs-Lauf ein."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed(mapper, [EST_A01], start_rid=1)
    _feed_hold(mapper, [EST_TIMELESS], start_rid=2)
    clock.advance(mapper.windows.jitter_window_s + 1)
    mapper.apply_ripe()
    mapper.process_estimates()
    assert store.get_estimate(2)["status"] == EST_WAITING, "einseitig -> weiter Hold"
    _, segs = _single_stay(store, P_EST)
    assert len(segs) == 1, "kein Segment-Eingriff ohne beide Schranken"

    _feed_apply(mapper, clock, [EST_A03], start_rid=3)     # t2 trifft ein
    mapper.process_estimates()
    assert store.get_estimate(2)["status"] == EST_ACTIVE
    assert len(store.segments_of(segs[0].stay_id)) == 2


# --- M3-G5: PROV_ESTIMATED isolierbar (epsilon-DP-Schutz) ---------------------------

def test_m3g5_estimated_cleanly_isolable(tmp_path):
    """(Review-Fokus d) Der Filter liefert NUR Grenzen ohne Schaetzung;
    geschaetzte Segmente + Schranken sind als eigener Kanal trennbar."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    all_segs = store.segments_in_range(iso(T0800), iso(T1300))
    assert len(all_segs) == 2
    clean = store.segments_in_range(iso(T0800), iso(T1300), include_estimated=False)
    assert clean == [], "beide Segmente tragen eine geschaetzte Grenzseite"

    export = store.export_for_aion()
    est_channel = export[0]["estimates"]
    assert len(est_channel) == 1
    assert est_channel[0]["lower_ts"] == iso(T0800)
    assert est_channel[0]["upper_ts"] == iso(T1200)
    # Gegenprobe: ein komplett gemessener Aufenthalt besteht den Filter.
    _feed_apply(mapper, clock, [EXC_ST_A01, EXC_ST_A03], start_rid=10)
    clean2 = store.segments_in_range(iso("20260501000000"), iso("20260601000000"),
                                     include_estimated=False)
    assert [s.ward for s in clean2] == ["ST1"]


# --- M3-G7: Schaetzung x Rueckwirkung -----------------------------------------------

def test_m3g7a_a08_moves_bound_interval_adapts(tmp_path):
    """(Review-Fokus e) A08 verschiebt die obere Schranke (A03 12:00 ->
    13:00): die Schaetzung wird NEU abgeleitet — Intervall passt sich an,
    nichts ist eingefroren."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    _feed_apply(mapper, clock, [EST_A08_MOVE_T2], start_rid=4)
    mapper.process_estimates()
    est = store.get_estimate(2)
    assert est["status"] == EST_ACTIVE
    assert est["upper_ts"] == iso(T1300), "obere Schranke folgt der A08-Mutation"
    assert est["lower_ts"] == iso(T0800)
    _, segs = _single_stay(store, P_EST)
    assert segs[0].end_ts == iso(T1300) and segs[0].end_provenance == PROV_ESTIMATED
    assert segs[1].end_ts == iso(T1300), "gemessene Seite folgt dem A08 selbst"


def test_m3g7b_storno_removes_bound_falls_back_to_hold(tmp_path):
    """(Review-Fokus e) A13 storniert das A03 — die obere Schranke ENTFAELLT:
    die geschaetzte Grenze wird ZURUECKGEBAUT (ein Segment, offen), die
    Schaetzung faellt auf Hold zurueck (reverted_hold) + Befund. M-1s Hold
    war nie weg — nichts geht verloren."""
    store, mapper, clock, notifier = _build_sandwich(tmp_path)
    _feed_apply(mapper, clock, [EST_A13_CANCEL_T2], start_rid=4)
    mapper.process_estimates()
    est = store.get_estimate(2)
    assert est["status"] == EST_REVERTED, "Rueckfall auf Hold"
    stay, segs = _single_stay(store, P_EST)
    assert stay.status == "open"
    assert len(segs) == 1 and segs[0].ward == "KAR", "geschaetzte Grenze zurueckgebaut"
    assert segs[0].end_ts is None
    assert PROV_ESTIMATED not in (segs[0].start_provenance, segs[0].end_provenance), \
        "keine geschaetzte Grenzseite verbleibt"
    assert any(FINDING_ESTIMATE_REVERT in s for s, _ in notifier.sent)
    assert "P920010" not in " ".join(s + b for s, b in notifier.sent), "Befund PID-frei"


# --- Idempotenz + Neustart -----------------------------------------------------------

def test_m3_estimation_idempotent_and_survives_restart(tmp_path):
    """Ableitung ist idempotent (zweiter Lauf = no-op); Schaetz-Zustand und
    Vermerk ueberleben den Neustart; Duplikate (receipt/Marker) unterdrueckt."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    before = [(s.segment_id, s.start_ts, s.end_ts)
              for s in store.segments_of(_single_stay(store, P_EST)[0].stay_id)]
    stats = mapper.process_estimates()
    assert stats["applied"] == 0 and stats["updated"] == 0 and stats["reverted"] == 0
    after = [(s.segment_id, s.start_ts, s.end_ts)
             for s in store.segments_of(_single_stay(store, P_EST)[0].stay_id)]
    assert before == after, "zweiter Lauf veraendert nichts"

    assert mapper.ingest_hold(2, EST_TIMELESS, "A02") == OUT_ESTIMATION_CANDIDATE, \
        "gleiche receipt_id: bestehender Vermerk zurueckgegeben"
    assert mapper.ingest_hold(99, EST_TIMELESS, "A02") == OUT_SUPPRESSED, \
        "Marker-Duplikat unterdrueckt"

    store2 = M2Store(tmp_path / "m2.sqlite")                 # Neustart
    mapper2 = MapperM2(None, store2, _FakeNotifier(), now_fn=clock)
    stats2 = mapper2.process_estimates()
    assert stats2["applied"] == 0 and stats2["reverted"] == 0
    assert store2.get_estimate(2)["status"] == EST_ACTIVE, "Schaetzung durabel"


# --- End-to-end ueber die ECHTE M-1-Hold-Queue (Korpus-Nachrichten) -----------------

def test_m3_end_to_end_estimation_via_real_m1_hold_queue(tmp_path):
    """Voller Pfad mit Friedhelms Korpus-Nachrichten: msg31 (A02, Zeit nur in
    EVN-2) wird von M-1 GEHOLDET; M-2 liest die Hold-Queue read-only, klemmt
    es zwischen msg26 (A01 15:20) und msg53 (A03 18:00) ein und liefert das
    Intervall — die EVN-2-Zeit (17:30) wird NIE als Bewegungszeit verwendet."""
    store, _, _, _ = _pipeline(tmp_path, [corpus_msg(26), corpus_msg(31),
                                          corpus_msg(53)])
    est = store.get_estimate(2)
    assert est["status"] == EST_ACTIVE
    assert (est["lower_ts"], est["upper_ts"]) == (iso("20260610152000"),
                                                  iso("20260611180000"))
    _, segs = _single_stay(store, "UKH|P100005")
    assert [s.ward for s in segs] == ["KAR", "IMC"]
    assert segs[0].end_provenance == PROV_ESTIMATED
    assert iso("20260610173000") not in (segs[0].end_ts, segs[1].start_ts), \
        "die EVN-2-Erfassungszeit wurde NIE als Grenze verwendet (Schranken statt Punkt)"


def test_m3_verification_own_evn2_has_no_influence_on_interval(tmp_path):
    """ANTI-FALSCH-DATIERUNGS-BEWEIS (Review-Verifikation): das Intervall des
    geholdeten A02 stammt AUSSCHLIESSLICH aus den Nachbar-Schranken — seine
    eigene EVN-2 fliesst nirgends ein. Struktur-Beweis: wird die EVN-2 des
    msg31 kuenstlich auf einen ANDEREN Wert gesetzt (16:45 statt 17:30),
    bleibt das Intervall IDENTISCH [15:20, 18:00]. Waere die EVN-2 eine
    Quelle, wuerde das Intervall reagieren. Zusaetzlich: das Event traegt in
    M-2 gar keinen Zeitwert (event_ts NULL — die A02-Zeitfeld-Regel ZBE-2 ->
    EVN-6 liest EVN-2 nie), und die Schranken-Quellen sind exakt die zwei
    Nachbarn (msg26/msg53), NIE der geholdete A02 selbst."""
    original = corpus_msg(31)
    # SYNTHETISCHE Ableitung (etikettiert): NUR die EVN-2 des Korpus-msg31
    # umdatiert — eindeutiger Treffer ueber die volle EVN-Zeile.
    patched = original.replace(b"EVN|A02|20260610173000", b"EVN|A02|20260610164500")
    assert patched != original, "Patch hat gegriffen"

    intervals = {}
    for label, a02 in (("original", original), ("patched", patched)):
        sub = tmp_path / label
        sub.mkdir()
        store, _, _, _ = _pipeline(sub, [corpus_msg(26), a02, corpus_msg(53)])
        est = store.get_estimate(2)
        assert est["status"] == EST_ACTIVE
        intervals[label] = (est["lower_ts"], est["upper_ts"])
        # (3) Schranken-Quellen = NUR die zwei Nachbarn, nie das Event selbst.
        assert (est["lower_source_receipt"], est["upper_source_receipt"]) == (1, 3), \
            "Quellen sind msg26 (A01) und msg53 (A03)"
        assert 2 not in (est["lower_source_receipt"], est["upper_source_receipt"]), \
            "der geholdete A02 ist NIE seine eigene Schranken-Quelle"
        # Das zeitlose Event traegt in M-2 KEINEN Zeitwert (EVN-2 nie geparst).
        with sqlite3.connect(str(sub / "m2.sqlite")) as c:
            assert c.execute("SELECT event_ts FROM m2_event WHERE receipt_id=2"
                             ).fetchone()[0] is None, \
                "A02-Zeitfeld-Regel (ZBE-2 -> EVN-6) liest EVN-2 nicht"
        # Und die verdaechtige EVN-2-Zeit taucht NIRGENDS als Grenze auf.
        for seg in store.segments_of(_single_stay(store, "UKH|P100005")[0].stay_id):
            assert seg.start_ts not in (iso("20260610173000"), iso("20260610164500"))
            assert seg.end_ts not in (iso("20260610173000"), iso("20260610164500"))

    assert intervals["original"] == intervals["patched"] == \
        (iso("20260610152000"), iso("20260611180000")), \
        "EVN-2 umdatiert -> Intervall UNVERAENDERT: die eigene Zeit hat keinen Einfluss"


# --- Erasure deckt Marker + Schaetzungen (SF-2 proaktiv) ----------------------------

def test_m3_erasure_covers_markers_and_estimates(tmp_path):
    """plausibility_marker (stay-gebunden) und boundary_estimate (Zeit-
    Schranken) sind Quasi-Identifikatoren -> Erasure loescht sie mit;
    Nachbar-Patient bleibt intakt."""
    store, mapper, clock, _ = _build_sandwich(tmp_path)
    _feed_apply(mapper, clock, [IMPL_A01], start_rid=10)
    _feed_apply(mapper, clock, [IMPL_A03], start_rid=11)
    mapper.reassess_plausibility()
    assert store.counts()["estimates"] == 1 and store.counts()["markers"] >= 2

    result = store.erase_patient(P_EST, commit=True)
    assert result.deleted >= 6, "Events + stay + 2 Segmente + Schaetzung"
    assert store.counts()["estimates"] == 0, "Schaetzung (Schranken) geloescht"
    assert store.stays_for_patient(P_EST) == []
    impl_stay, _ = _single_stay(store, P_IMPL)
    assert _marker_kinds(store, impl_stay.stay_id) != set(), "Nachbar-Marker intakt"

    result2 = store.erase_patient(P_IMPL, commit=True)
    assert store.counts()["markers"] == 0, "Marker des geloeschten Patienten weg"
