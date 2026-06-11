"""
Named proofs for the SILD M-2 ADT-Mapper Stufe 1 (sild_mapper_m2).

One test (or parametrized table) per guarantee M2-G1..G8 plus the briefing's
Pflicht-Testvektoren on Friedhelms committed corpus. Two harness paths:

  - _pipeline(...): END-TO-END intake -> M-1 (real sighting) -> M-2. Proves the
    interface, including that M-1's holds (the EVN-2-only corpus A02) never
    reach M-2.
  - _feed(...): DIRECT feed of usable events into M-2 (bypassing M-1) for the
    vectors the corpus cannot drive through M-1 (the held A02 chain). Every
    direct-fed fixture is asserted m1.classify(...)==usable first — the direct
    feed only ever contains events M-1 WOULD forward (right-target check).

Run:  pytest tests/test_mapper_m2.py -v
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

import sild_mapper_m1 as m1
import sild_mapper_m2 as m2mod
from sild_durable_store import DurableStore, SimulatedCrash, extract_marker
from sild_mapper_m2 import (
    EV_DEFERRED,
    FINDING_OPEN_OVERDUE,
    FINDING_OUT_OF_ORDER,
    FINDING_UNASSIGNED,
    GRAN_BED,
    GRAN_ROOM,
    GRAN_WARD,
    M1OutputReader,
    M2Store,
    MapperM2,
    OUT_BUFFERED,
    OUT_DEFERRED,
    OUT_SUPPRESSED,
    OUT_UNASSIGNED,
    PATTERN_A,
    PATTERN_B,
    PATTERN_C,
    PATTERN_PENDING,
    WindowConfig,
    contact_unit,
)
from tests.mapper_m2_vectors import (
    ERASE_X_A01,
    ERASE_X_A04,
    ERASE_X_KEY,
    ERASE_Y_A04,
    ERASE_Y_KEY,
    EXPECTED_CORPUS_STAYS,
    EXPECTED_M1_CORPUS_COUNTS,
    EXPECTED_P100005_CLEAN_SEGMENTS,
    FIXED_NOW_M2,
    JITTER_SWAP_A01,
    JITTER_SWAP_A04,
    ORPHAN_A02,
    OVERDUE_AMB_A04,
    OVERDUE_ICU_A01,
    OVERDUE_ST_A01,
    OVERDUE_ST_A04,
    SPERRE_FEED,
    STORNO_A11,
    TRAP_PV1_4_E,
    UNRESOLVED_PID,
    corpus_msg,
    interface_a02,
    iso,
    load_corpus,
    p100005_clean_chain,
    p100006_clean_chain,
    with_zbe,
)


# --- harness ------------------------------------------------------------------

class _Clock:
    """Injected arrival wall clock (M2-G5: Ankunfts-Wanduhr, testbar)."""

    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


class _FakeNotifier:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.sent = []

    def send(self, subject, body):
        self.sent.append((subject, body))
        return (False, "fake-smtp-down") if self.fail else (True, "fake-ok")


def _direct(tmp_path, *, windows: WindowConfig = None):
    """M-2 alone (reader=None) for direct usable-event feeds."""
    store = M2Store(tmp_path / "m2.sqlite")
    clock = _Clock(FIXED_NOW_M2)
    notifier = _FakeNotifier()
    mapper = MapperM2(None, store, notifier, windows=windows, now_fn=clock)
    return store, mapper, clock, notifier


def _feed(mapper, raws, *, start_rid=1):
    """Direct feed. GATE: every fixture must be M-1-usable (m1.classify) — the
    direct path only carries events M-1 WOULD forward."""
    outcomes = []
    for i, raw in enumerate(raws):
        c = m1.classify(raw, now=FIXED_NOW_M2)
        assert c.kind == m1.USABLE, \
            f"direct-feed fixture must be M-1-usable, got {c.kind} ({c.reason})"
        outcomes.append(mapper.ingest_usable(start_rid + i, raw, c.trigger, c.time_provenance))
    return outcomes


def _feed_apply(mapper, clock, raws, *, start_rid=1):
    outcomes = _feed(mapper, raws, start_rid=start_rid)
    clock.advance(mapper.windows.jitter_window_s + 1)
    mapper.apply_ripe()
    return outcomes


def _pipeline(tmp_path, messages, *, windows: WindowConfig = None):
    """END-TO-END: SILD intake -> M-1 (real) -> M-2. Two M-2 polls: ingest,
    then (clock past the jitter window) apply."""
    clock = _Clock(FIXED_NOW_M2)
    intake = DurableStore(tmp_path / "intake.sqlite")
    for raw in messages:
        intake.persist(raw, extract_marker(raw))
    m1_mapper = m1.MapperM1(
        m1.IntakeReader(tmp_path / "intake.sqlite"),
        m1.MapperStore(tmp_path / "m1.sqlite"),
        _FakeNotifier(), now_fn=clock,
    )
    m1_mapper.poll_once()
    m2_store = M2Store(tmp_path / "m2.sqlite")
    notifier = _FakeNotifier()
    m2 = MapperM2(M1OutputReader(tmp_path / "m1.sqlite", tmp_path / "intake.sqlite"),
                  m2_store, notifier, windows=windows, now_fn=clock)
    m2.poll_once()
    clock.advance(m2.windows.jitter_window_s + 1)
    m2.poll_once()
    return m2_store, m2, clock, notifier


def _single_stay(store, patient_key):
    stays = store.stays_for_patient(patient_key)
    assert len(stays) == 1, f"expected exactly ONE stay for {patient_key}, got {len(stays)}"
    return stays[0], store.segments_of(stays[0].stay_id)


def _m1_kind_counts(tmp_path) -> dict:
    with sqlite3.connect(str(tmp_path / "m1.sqlite")) as c:
        rows = c.execute("SELECT kind, COUNT(*) FROM disposition GROUP BY kind").fetchall()
    return dict(rows)


# --- M2-G2: Muster A (direkt stationaer) ---------------------------------------

def test_m2g2_muster_a_p100005_admission(tmp_path):
    """Korpus-Vektor Muster A: P100005s A01 ohne A04-Vorlauf -> EIN stay,
    Muster A, ein OFFENES Segment ab A01 (KAR, rohe PV1-3-Komponenten)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(26)])
    stay, segs = _single_stay(store, "UKH|P100005")
    assert stay.pattern == PATTERN_A and stay.status == "open"
    assert stay.visit_id == "V100005"
    assert len(segs) == 1
    assert (segs[0].ward, segs[0].room, segs[0].bed) == ("KAR", "402", "1")
    assert segs[0].pv1_3_raw == "KAR^402^1^UKH"
    assert segs[0].start_ts == iso("20260610152000")
    assert segs[0].end_ts is None, "offenes Segment endet auf NULL, nie last-known-time"


# --- M2-G2: Muster B (A04 -> A01 = EIN stay, KEIN Rewrite) ----------------------

@pytest.mark.parametrize("a04_no,a01_no,pkey,station", [
    (1, 2, "UKH|P100001", "IM1"),
    (16, 17, "UKH|P100003", "IM2"),
    (41, 42, "UKH|P100007", "NEU"),
], ids=["P100001", "P100003", "P100007"])
def test_m2g2_muster_b_one_stay_end_to_end(tmp_path, a04_no, a01_no, pkey, station):
    """Korpus-Vektoren Muster B end-to-end (intake -> M-1 -> M-2): A04(O/NA)
    gefolgt von A01(I) -> EIN stay, Segment 1 NA (A04->A01-Zeit), Segment 2 ab
    A01, Muster B."""
    store, _, _, _ = _pipeline(tmp_path, [corpus_msg(a04_no), corpus_msg(a01_no)])
    stay, segs = _single_stay(store, pkey)
    assert stay.pattern == PATTERN_B and stay.status == "open"
    assert [s.ward for s in segs] == ["NA", station]
    assert segs[0].end_ts == segs[1].start_ts, "der A01 schliesst das NA-Segment (Event-Invariante)"
    assert segs[1].end_ts is None


def test_m2g2_muster_b_forward_no_rewrite(tmp_path):
    """(Review-Fokus a) Die B-Bindung ist VORWAERTS: das bei A04 angelegte
    NA-Segment behaelt seine Identitaet (gleiche segment_id); der A01 setzt nur
    dessen offenes Ende und oeffnet Segment 2 — kein Loeschen, kein Rewrite."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(1)])                    # A04 P100001
    stay, segs = _single_stay(store, "UKH|P100001")
    assert stay.pattern == PATTERN_PENDING
    na_segment_id = segs[0].segment_id
    assert segs[0].end_ts is None

    _feed_apply(mapper, clock, [corpus_msg(2)], start_rid=2)       # A01, Ankunft im Join-Fenster
    stay2, segs2 = _single_stay(store, "UKH|P100001")
    assert stay2.stay_id == stay.stay_id, "EIN stay (Muster B), kein zweiter"
    assert stay2.pattern == PATTERN_B
    assert [s.segment_id for s in segs2][0] == na_segment_id, "NA-Segment-Zeile blieb dieselbe"
    assert segs2[0].end_ts == iso("20260610080500")
    assert len(segs2) == 2 and segs2[1].end_ts is None


@pytest.mark.parametrize("chain,pkey,wards", [
    ([corpus_msg(9), corpus_msg(10), with_zbe(corpus_msg(15))], "UKH|P100002",
     ["NA", "CH1", "ENDO"]),
    (p100006_clean_chain(), "UKH|P100006", ["NA", "GYN", "GYN"]),
], ids=["P100002", "P100006"])
def test_m2g2_muster_b_three_segments(tmp_path, chain, pkey, wards):
    """Korpus-Vektoren P100002/P100006: A04 -> A01 -> A02 = EIN stay, DREI
    Segmente. (A02 als sauber-datierte synthetische Ableitung mit ZBE-2 — der
    Korpus-A02 selbst wird von M-1 geholdet, s. Verlegungspfad-Test.)"""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, chain)
    stay, segs = _single_stay(store, pkey)
    assert stay.pattern == PATTERN_B and stay.status == "open"
    assert [s.ward for s in segs] == wards
    assert [s.end_ts is None for s in segs] == [False, False, True]


# --- M2-G2: Muster C (rein ambulant) --------------------------------------------

def test_m2g2_muster_c_p100004_closed_by_a03(tmp_path):
    """Korpus-Vektor Muster C end-to-end: A04(O/AMB) ... A03(O) -> EIN stay,
    Muster C, ein AMB-Segment, durch das A03 geschlossen."""
    store, _, _, _ = _pipeline(tmp_path, [corpus_msg(21), corpus_msg(49)])
    stay, segs = _single_stay(store, "UKH|P100004")
    assert stay.pattern == PATTERN_C and stay.status == "closed"
    assert stay.visit_id == "V100004"
    assert len(segs) == 1 and segs[0].ward == "AMB"
    assert segs[0].start_ts == iso("20260610140000")
    assert segs[0].end_ts == iso("20260611001500")


def test_m2g2_muster_c_finalized_after_join_window(tmp_path):
    """A04 ohne A01: nach Ablauf des Join-Fensters wird die vorlaeufige Episode
    durabel als Muster C festgeschrieben; ihr Segment darf offen bleiben."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(21)])
    stay, _ = _single_stay(store, "UKH|P100004")
    assert stay.pattern == PATTERN_PENDING, "im Join-Fenster noch unentschieden"

    clock.advance(mapper.windows.join_window_s + 1)
    finalized = mapper.finalize_patterns()
    assert stay.stay_id in finalized
    stay2, segs = _single_stay(store, "UKH|P100004")
    assert stay2.pattern == PATTERN_C and stay2.status == "open"
    assert segs[0].end_ts is None, "Muster C kann offen bleiben (M2-G6)"


def test_m2g2_a01_beyond_join_window_is_new_stay(tmp_path):
    """Ein A01 JENSEITS des Join-Fensters bindet NICHT an die A04-Episode
    (das waere Stufe 2): die Episode wird C, der A01 ein NEUER Muster-A-stay."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(1)])                    # A04 P100001
    clock.advance(mapper.windows.join_window_s + 60)
    _feed_apply(mapper, clock, [corpus_msg(2)], start_rid=2)       # A01, zu spaet
    mapper.finalize_patterns()
    stays = store.stays_for_patient("UKH|P100001")
    assert sorted(s.pattern for s in stays) == [PATTERN_A, PATTERN_C]


# --- Briefing-Vektor "M2-G1 vier Segmente" + Gap 2 + Granularitaet ---------------

def test_m2_vector_vier_segmente_p100005(tmp_path):
    """P100005 (A01 + 3x sauber-datierter A02 + A03) -> EIN stay, VIER Segmente;
    das doppelte IMC bleibt zeitlich getrennt und wird NIE ueber die Einheiten-
    Identitaet kollabiert (Dedup-Verbot)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, p100005_clean_chain())
    stay, segs = _single_stay(store, "UKH|P100005")
    assert stay.pattern == PATTERN_A and stay.status == "closed"
    got = [(s.pv1_3_raw, s.ward, s.room, s.bed, s.start_ts, s.end_ts) for s in segs]
    assert got == EXPECTED_P100005_CLEAN_SEGMENTS, "vier Segmente, exakt die Korpus-Kette"
    imc = [s for s in segs if s.ward == "IMC"]
    assert len(imc) == 2 and imc[0].segment_id != imc[1].segment_id
    assert imc[0].unit(GRAN_WARD) == imc[1].unit(GRAN_WARD) == "IMC", \
        "gleiche Kontakt-Einheit (ward) zu verschiedenen Zeiten -> ZWEI Segmente"
    assert imc[0].end_ts <= imc[1].start_ts, "zeitlich getrennt"


def test_m2g4_granularity_and_gap2_msg54(tmp_path):
    """(Review-Fokus b+g) MSG54 (GYN^221^2^UKH): rohe PV1-3-Komponenten am
    Segment, Kontakt-Einheit kollabiert ZUR COMPUTE-ZEIT je Granularitaet.
    Gap 2: GYN^220 -> GYN^221 ist bei `ward` DIESELBE Einheit — der Mapper
    liefert trotzdem ZWEI Segmente und verschmilzt NICHTS (Verschmelzung =
    AION-seitige Delta_con-Regel, M-4, nur dokumentiert)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, p100006_clean_chain())
    _, segs = _single_stay(store, "UKH|P100006")
    s220, s221 = segs[1], segs[2]
    assert (s221.pv1_3_raw, s221.ward, s221.room, s221.bed) == \
        ("GYN^221^2^UKH", "GYN", "221", "2"), "rohe PV1-3-Komponenten gespeichert"
    assert s221.unit(GRAN_WARD) == "GYN"
    assert s221.unit(GRAN_ROOM) == "GYN^221"
    assert s221.unit(GRAN_BED) == "GYN^221^2"
    # Gap 2: gleiche ward-Einheit, trotzdem zwei gelieferte Lage-Segmente.
    assert s220.unit(GRAN_WARD) == s221.unit(GRAN_WARD) == "GYN"
    assert s220.segment_id != s221.segment_id
    assert s220.unit(GRAN_ROOM) != s221.unit(GRAN_ROOM)
    with pytest.raises(ValueError):
        contact_unit("GYN", "221", "2", "zimmer")


# --- M2-G4: Ueber-Kontaktierungs-Sperre ------------------------------------------

def test_m2g4_na_ueberkontaktierungs_sperre(tmp_path):
    """(Review-Fokus c) Implizites NA (keine Raum-/Bettkomponente) faellt auf
    Stationsebene zurueck; Kontakt gibt es NUR bei zeitlicher Ueberlappung —
    halb-offen: disjunkt zaehlt nicht, beruehren zaehlt nicht."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, SPERRE_FEED)
    pa_stay = store.stays_for_patient("UKH|P900001")[0]
    pa_na = store.segments_of(pa_stay.stay_id)[0]
    assert pa_na.ward == "NA" and pa_na.end_ts == iso("20260612090000")
    assert pa_na.unit(GRAN_BED) == "NA", "implizites NA bleibt Stationsebene auch bei bed"

    contacts = store.find_contacts(pa_na.segment_id, GRAN_WARD)
    contact_patients = {store.get_stay(s.stay_id).patient_key for s in contacts}
    assert contact_patients == {"UKH|P900003"}, \
        "NUR die ueberlappende NA-Episode kontaktiert (disjunkt + beruehrend nicht)"
    assert store.find_contacts(pa_na.segment_id, GRAN_BED) == contacts, \
        "NA ohne Raum/Bett: bed-Granularitaet aendert die Kontaktmenge nicht"


# --- M2-G5: Wartefenster + Verspaetungs-Protokoll --------------------------------

def test_m2g5_jitter_window_holds_then_applies(tmp_path):
    """Ein Event wird erst NACH Ablauf des Jitter-Fensters angewandt (Ankunfts-
    Wanduhr); der Mapper haelt dabei nie an (Ingest bleibt durabel sofort)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed(mapper, [corpus_msg(26)])
    assert mapper.apply_ripe() == 0, "im Jitter-Fenster wird nichts angewandt"
    assert store.counts()["events"] == 1, "aber durabel eingelagert (kein Verlust)"
    clock.advance(mapper.windows.jitter_window_s + 1)
    assert mapper.apply_ripe() == 1
    assert store.counts()["segments"] == 1


def test_m2g5_jitter_reorder_heals_swapped_arrival(tmp_path):
    """A01 kommt VOR dem A04 an (Transport-Vertauschung im Jitter-Fenster):
    die zeit-sortierte Anwendung stellt die NA->Station-Folge her -> EIN stay,
    Muster B."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [JITTER_SWAP_A01, JITTER_SWAP_A04])   # Ankunft vertauscht
    stay, segs = _single_stay(store, "UKH|P900020")
    assert stay.pattern == PATTERN_B
    assert [s.ward for s in segs] == ["NA", "ST1"]
    assert segs[0].end_ts == iso("20260612090000")


def test_m2g5_delay_log_records_event_vs_arrival_and_window(tmp_path):
    """Verspaetungs-Protokoll pro Event: Ereigniszeit<->Ankunft-Differenz und
    welches Fenster (A04/A01 -> join, sonst jitter) — Lerngrundlage."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed(mapper, [ERASE_X_A04, ORPHAN_A02])     # Events 08:00 / 09:00, Ankunft 12:00
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        rows = c.execute(
            "SELECT trigger, delay_seconds, window FROM delay_log ORDER BY receipt_id"
        ).fetchall()
    assert rows == [("A04", 4 * 3600, "join"), ("A02", 3 * 3600, "jitter")]


# --- M2-G6: offene Segmente + Offen-Dauer-Befund ---------------------------------

def test_m2g6_open_segment_null_end_and_overdue_finding(tmp_path):
    """(Review-Fokus d) Offenes Segment endet auf NULL. Ueberschreitet die
    Offen-Dauer die Schwelle -> Befund 'vermutlich fehlende A03' (durabel ->
    aktiv, PID-frei), genau EINMAL pro Segment."""
    store, mapper, clock, notifier = _pipeline(tmp_path, [corpus_msg(1), corpus_msg(2)])
    _, segs = _single_stay(store, "UKH|P100001")
    assert segs[1].end_ts is None, "IM1 ist offen (kein A03 im Feed)"

    clock.advance(15 * 24 * 3600)                 # > Default-Schwelle 14d
    assert mapper.check_open_durations() == 1
    assert mapper.check_open_durations() == 0, "genau einmal pro Segment (kein Befund-Sturm)"
    subject, body = notifier.sent[-1]
    assert FINDING_OPEN_OVERDUE in subject
    assert "vermutlich fehlende A03" in body
    assert "P100001" not in subject + body, "Befund ist PID-frei (kein Patienten-Schluessel)"
    assert store.pending_findings() == [], "durabel gespeichert UND zugestellt"


def test_m2g6_overdue_thresholds_differ_by_class(tmp_path):
    """Die Offen-Dauer-Schwelle ist NACH KLASSE differenziert: das offene
    ambulante Segment loest FRUEHER aus (1d), das stationaere bei 14d, das
    ITS-Segment NICHT unter der Stationsschwelle, sondern erst bei seiner
    eigenen (60d) — eine Pauschale waere in beide Richtungen falsch."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [OVERDUE_AMB_A04, OVERDUE_ST_A04,
                                OVERDUE_ST_A01, OVERDUE_ICU_A01])
    clock.advance(mapper.windows.join_window_s + 1)
    mapper.finalize_patterns()                       # AMB-Episode -> Muster C (ambulant)
    assert mapper.check_open_durations() == 0, "unter allen Schwellen: kein Befund"

    clock.advance(2 * 24 * 3600)                     # Alter ~2d
    assert mapper.check_open_durations() == 1, "NUR das ambulante Segment (Schwelle 1d)"
    assert "Klasse ambulant" in notifier.sent[-1][1]

    clock.advance(13 * 24 * 3600)                    # Alter ~15d
    assert mapper.check_open_durations() == 1, "jetzt das stationaere (14d); ITS NICHT"
    assert "Klasse stationaer" in notifier.sent[-1][1]

    clock.advance(46 * 24 * 3600)                    # Alter ~61d
    assert mapper.check_open_durations() == 1, "erst jetzt das ITS-Segment (60d)"
    assert "Klasse intensiv" in notifier.sent[-1][1]
    assert mapper.check_open_durations() == 0, "jedes Segment genau einmal"


# --- M2-G1: Idempotenz + Cursor-Disziplin (geerbt aus M-1) ------------------------

def test_m2g1_event_twice_yields_one_segment(tmp_path):
    """(Review-Fokus e / Gap 1) Dasselbe Event zweimal eingespeist — gleiche
    receipt_id (Re-Scan) UND neue receipt_id mit gleichem Marker (Re-Read nach
    Neustart) -> genau EIN Segment."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [corpus_msg(26)])
    c = m1.classify(corpus_msg(26), now=FIXED_NOW_M2)
    assert mapper.ingest_usable(1, corpus_msg(26), c.trigger) == OUT_BUFFERED, \
        "gleiche receipt_id: bestehender Vermerk, keine Doppel-Einlagerung"
    assert mapper.ingest_usable(99, corpus_msg(26), c.trigger) == OUT_SUPPRESSED, \
        "neue receipt_id, gleicher Marker: Event-Identitaet schon verarbeitet"
    clock.advance(mapper.windows.jitter_window_s + 1)
    mapper.apply_ripe()
    assert store.counts()["segments"] == 1, "genau EIN Segment"

    # Neustart-Simulation: frischer Store + Mapper auf DERSELBEN DB.
    store2 = M2Store(tmp_path / "m2.sqlite")
    mapper2 = MapperM2(None, store2, _FakeNotifier(), now_fn=clock)
    assert mapper2.ingest_usable(100, corpus_msg(26), c.trigger) == OUT_SUPPRESSED, \
        "Marker-Identitaet ist durabel (ueberlebt Neustart)"
    clock.advance(mapper2.windows.jitter_window_s + 1)
    mapper2.apply_ripe()
    assert store2.counts()["segments"] == 1, "immer noch EIN Segment (kein Doppel)"


def test_m2g1_crash_before_vermerk_no_skip(tmp_path):
    """Crash VOR dem durablen Vermerk -> nichts vermerkt; das Event wird nach
    Neustart erneut gesichtet (kein Skip)."""
    store, mapper, clock, _ = _direct(tmp_path)
    c = m1.classify(corpus_msg(26), now=FIXED_NOW_M2)
    with pytest.raises(SimulatedCrash):
        mapper.ingest_usable(1, corpus_msg(26), c.trigger, _crash="before_persist")
    assert store.processed_outcome(1) is None, "kein Vermerk nach Pre-Commit-Crash"
    assert mapper.ingest_usable(1, corpus_msg(26), c.trigger) == OUT_BUFFERED, \
        "nach Neustart erneut gesichtet (kein Skip)"


def test_m2g1_persist_before_cursor_end_to_end(tmp_path):
    """Crash nach dem Vermerk, VOR dem Cursor (im echten M-1->M-2-Pfad):
    Re-Scan nach Neustart ist idempotent — kein Doppel-Event, kein Doppel-
    Segment, Cursor rueckt im sauberen Lauf nach."""
    clock = _Clock(FIXED_NOW_M2)
    intake = DurableStore(tmp_path / "intake.sqlite")
    for raw in [corpus_msg(26), corpus_msg(53)]:                   # A01 + A03 P100005
        intake.persist(raw, extract_marker(raw))
    m1_mapper = m1.MapperM1(m1.IntakeReader(tmp_path / "intake.sqlite"),
                            m1.MapperStore(tmp_path / "m1.sqlite"),
                            _FakeNotifier(), now_fn=clock)
    m1_mapper.poll_once()

    m2_store = M2Store(tmp_path / "m2.sqlite")
    m2 = MapperM2(M1OutputReader(tmp_path / "m1.sqlite", tmp_path / "intake.sqlite"),
                  m2_store, _FakeNotifier(), now_fn=clock)
    with pytest.raises(SimulatedCrash):
        m2.poll_once(_crash_before_cursor_at=1)
    assert m2_store.processed_outcome(1) is not None, "der Vermerk ist durabel"
    assert m2_store.get_cursor() == 0, "Cursor rueckte vor dem Crash nicht vor"

    # Neustart: frische Objekte auf denselben DBs.
    m2_store2 = M2Store(tmp_path / "m2.sqlite")
    m2b = MapperM2(M1OutputReader(tmp_path / "m1.sqlite", tmp_path / "intake.sqlite"),
                   m2_store2, _FakeNotifier(), now_fn=clock)
    m2b.poll_once()
    clock.advance(m2b.windows.jitter_window_s + 1)
    m2b.poll_once()
    assert m2_store2.get_cursor() == 2
    assert m2_store2.counts()["events"] == 2, "kein Doppel-Event nach Re-Scan"
    _, segs = _single_stay(m2_store2, "UKH|P100005")
    assert len(segs) == 1, "genau EIN Segment (A01), durch A03 geschlossen"
    assert segs[0].end_ts == iso("20260611180000")


# --- Verlegungspfad zweifach (Review-Fokus f) ------------------------------------

def test_m2_verlegungspfad_zweifach_end_to_end(tmp_path):
    """(1) Der Korpus-A02 (Zeit nur in EVN-2) wird von M-1 GEHOLDET und erreicht
    M-2 nie (Anti-Falsch-Datierung wirkt). (2) Der SEPARATE sauber-datierte A02
    (ZBE-2, samples/adt_m2_interface/) fliesst M-1 -> usable -> M-2 und baut die
    Segmentgrenze KAR->IMC mit Provenienz 'measured'."""
    store, _, _, _ = _pipeline(
        tmp_path, [corpus_msg(26), corpus_msg(31), interface_a02()])

    kinds = _m1_kind_counts(tmp_path)
    assert kinds.get(m1.USABLE) == 2 and kinds.get(m1.HOLD_TIMEQUALITY) == 1, \
        "M-1: A01 + sauberer A02 usable, Korpus-A02 geholdet"
    assert store.processed_outcome(2) is None, "der geholdete Korpus-A02 erreicht M-2 NICHT"

    stay, segs = _single_stay(store, "UKH|P100005")
    assert [s.ward for s in segs] == ["KAR", "IMC"]
    assert segs[0].end_ts == iso("20260610173000"), "Segmentgrenze aus dem sauberen A02"
    assert segs[0].end_provenance == m1.PROV_MEASURED, "ZBE-2 = gemessene Bewegungszeit"
    assert segs[1].start_provenance == m1.PROV_MEASURED
    assert segs[1].end_ts is None


# --- M2-G7: Provenienz an jeder Segmentgrenze ------------------------------------

def test_m2g7_provenance_at_every_boundary(tmp_path):
    """Korpus-Zeiten stammen aus EVN-2 -> recorded_substitute (markiert, nicht
    als gemessen verrechenbar); ZBE-2-Grenzen sind measured; EVN-6 ist event."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, p100005_clean_chain())
    _, segs = _single_stay(store, "UKH|P100005")
    assert segs[0].start_provenance == m1.PROV_RECORDED, "A01-Zeit nur aus EVN-2 (Korpus)"
    assert segs[0].end_provenance == m1.PROV_MEASURED, "A02-Grenze aus ZBE-2"
    assert [s.start_provenance for s in segs[1:]] == [m1.PROV_MEASURED] * 3
    assert segs[3].end_provenance == m1.PROV_RECORDED, "A03-Zeit nur aus EVN-2 (Korpus)"
    # EVN-6 -> event (synthetischer Gegenpol)
    store2, mapper2, clock2, _ = _direct(tmp_path / "b")
    _feed_apply(mapper2, clock2, [ERASE_X_A04])
    _, segs2 = _single_stay(store2, ERASE_X_KEY)
    assert segs2[0].start_provenance == m1.PROV_EVENT
    assert m1.provenance_code(("ZBE", 2)) == m1.PROV_MEASURED, "eine Quelle, zwei Sichten"


# --- Fallen (MDM/ORR/PV1-4=E) + Stufe-2-Grenzen ----------------------------------

def test_m2_trap_pv1_4_e_is_not_inpatient(tmp_path):
    """PV1-4 'E' ist die AUFNAHMEART, nicht die Klasse: das A04 bleibt
    PV1-2='O' und damit eine ambulante/NA-Episode (C ohne A01) — nie Muster A/B."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [TRAP_PV1_4_E])
    clock.advance(mapper.windows.join_window_s + 1)
    mapper.finalize_patterns()
    stay, _ = _single_stay(store, "UKH|P900010")
    assert stay.pattern == PATTERN_C
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        klass = c.execute("SELECT patient_class FROM m2_event WHERE receipt_id=1").fetchone()[0]
    assert klass == "O", "Klasse bleibt PV1-2='O' trotz PV1-4='E'"


def test_m2_storno_without_zst_failclosed(tmp_path):
    """Seit Stufe 2 (M2c) werden Storni aufgeloest — aber NUR mit ZST: ein A11
    OHNE ZST haelt fail-closed an (Hold + Befund, M2c-G5) und mutiert NICHTS.
    (Frueher Stufe-1-Grenze 'deferred'; Verhalten bewusst geaendert.)"""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [STORNO_A11])
    assert store.counts()["stays"] == 0 and store.counts()["segments"] == 0
    assert store.counts()["retro_audits"] == 0, "KEINE Mutation ohne ZST"
    assert store.event_status(1)[0] == m2mod.EV_HELD, "fail-closed Hold, nicht still"
    assert any(m2mod.FINDING_RETRO_FAILCLOSED in s for s, _ in notifier.sent)


def test_m2_a02_without_open_stay_is_deferred_finding(tmp_path):
    """A02 ohne offenen Aufenthalt (Out-of-Order) -> KEIN Raten: deferred +
    Befund (Stufe-2-Input), kein Segment."""
    store, mapper, clock, notifier = _direct(tmp_path)
    _feed_apply(mapper, clock, [ORPHAN_A02])
    assert store.counts()["segments"] == 0
    assert store.event_status(1)[0] == EV_DEFERRED
    assert any(FINDING_OUT_OF_ORDER in s for s, _ in notifier.sent)


def test_m2_unassigned_usable_raises_finding(tmp_path):
    """Ein usable Event ohne lesbaren Patienten-Schluessel ist nicht
    sequenzierbar -> unassigned + Befund (PID-frei), zaehlt als 'unresolved'."""
    store, mapper, clock, notifier = _direct(tmp_path)
    assert _feed(mapper, [UNRESOLVED_PID]) == [OUT_UNASSIGNED]
    assert any(FINDING_UNASSIGNED in s for s, _ in notifier.sent)
    with sqlite3.connect(str(tmp_path / "m2.sqlite")) as c:
        status = c.execute("SELECT pkey_status FROM m2_event WHERE receipt_id=1").fetchone()[0]
    assert status == "unresolved", "PID-3 vorhanden-aber-unlesbar = Restrisiko (fail-closed)"


# --- Voll-Korpus end-to-end (alle 54 durch intake -> M-1 -> M-2) ------------------

def test_m2_full_corpus_end_to_end(tmp_path):
    """Der komplette 54er-Korpus durch den echten Pfad: M-1 sichtet (14 usable /
    5 A02-Holds / 35 ignoriert — MDM/ORR/ORM/ORU sind keine Bewegungen und
    erreichen M-2 nie), M-2 rekonstruiert exakt die README-verifizierten
    Sequenzen: 7 stays, 12 Segmente, Muster und Grenzen wie erwartet."""
    store, _, _, _ = _pipeline(tmp_path, load_corpus())

    kinds = _m1_kind_counts(tmp_path)
    assert kinds.get(m1.USABLE) == EXPECTED_M1_CORPUS_COUNTS["usable"]
    assert kinds.get(m1.HOLD_TIMEQUALITY) == EXPECTED_M1_CORPUS_COUNTS["hold_timequality"]
    assert kinds.get(m1.IGNORED) == EXPECTED_M1_CORPUS_COUNTS["ignored"]

    counts = store.counts()
    assert counts["events"] == 14, "genau die 14 usable erreichen M-2"
    assert counts["stays"] == 7 and counts["segments"] == 12, \
        "7 Patienten; 5x Muster B je 2 Segmente + P100004 (C) 1 + P100005 (A, A02 geholdet) 1"

    for pkey, exp in EXPECTED_CORPUS_STAYS.items():
        stay, segs = _single_stay(store, pkey)
        assert stay.pattern == exp.pattern, pkey
        assert stay.status == exp.status, pkey
        assert stay.visit_id == exp.visit_id, pkey
        assert [(s.ward, s.start_ts, s.end_ts) for s in segs] == exp.segments, pkey


# --- M2-G8: Durchsuchbarkeit + Erasure + AION-Uebergabe ---------------------------

def test_m2g8_searchable_by_patient_visit_timerange(tmp_path):
    """Stufe-2-Voraussetzung: die M-2-DB ist nach Patient, Visit und Zeitraum
    abfragbar (offene Segmente gelten im Zeitraum als andauernd)."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, p100005_clean_chain())
    assert len(store.stays_for_visit("V100005")) == 1
    assert len(store.stays_for_patient("UKH|P100005")) == 1
    hits = store.segments_in_range(iso("20260611090000"), iso("20260611110000"))
    assert [s.ward for s in hits] == ["ITS"], "Zeitraum-Schnitt trifft genau das ITS-Segment"

    store2, mapper2, clock2, _ = _direct(tmp_path / "open")
    _feed_apply(mapper2, clock2, p100006_clean_chain())
    hits2 = store2.segments_in_range(iso("20260612000000"), iso("20260613000000"))
    assert [s.pv1_3_raw for s in hits2] == ["GYN^221^2^UKH"], \
        "offenes Segment (Ende NULL) gilt als andauernd"


def test_m2g8_erasure_x_gone_y_intact_fail_closed(tmp_path):
    """Erasure mit SILD-Lesart-A-Semantik: dry-run per Default, X komplett weg
    (Events + stay + Segmente), Y intakt; ein unresolved-Event (PID-3 unlesbar)
    macht JEDE Loeschung fail-closed incomplete_uncertain."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, [ERASE_X_A04, ERASE_X_A01, ERASE_Y_A04, UNRESOLVED_PID])

    dry = store.erase_patient(ERASE_X_KEY)                  # dry-run per Default
    assert dry.dry_run and dry.deleted == 5, "2 Events + 1 stay + 2 Segmente"
    assert store.counts()["stays"] == 2, "dry-run loescht nichts"

    result = store.erase_patient(ERASE_X_KEY, commit=True)
    assert result.deleted == 5
    assert result.unresolvable == 1 and result.status == "incomplete_uncertain", \
        "vorhandenes-aber-unlesbares PID-3 koennte X sein -> fail-closed"
    assert store.stays_for_patient(ERASE_X_KEY) == []
    assert len(store.stays_for_patient(ERASE_Y_KEY)) == 1, "Y intakt"
    assert store.counts()["delays"] >= 3, "PID-freies Protokoll bleibt (Audit)"


def test_m2_export_for_aion_carries_raw_components_and_provenance(tmp_path):
    """(Review-Fokus b+g) Die Uebergabe-Sicht traegt die rohen PV1-3-Komponenten
    (Ableitungsschluessel) und die Grenz-Provenienz — unverschmolzen; Kollaps
    und Delta_con-Regeln sind AION/M-4."""
    store, mapper, clock, _ = _direct(tmp_path)
    _feed_apply(mapper, clock, p100005_clean_chain())
    export = store.export_for_aion()
    assert len(export) == 1
    segs = export[0]["segments"]
    assert len(segs) == 4, "unverschmolzen uebergeben"
    assert segs[1]["ward"] == "IMC" and segs[1]["room"] == "502" and segs[1]["bed"] == "1"
    assert segs[1]["start_provenance"] == m1.PROV_MEASURED
    assert segs[0]["end_ts"] == segs[1]["start_ts"]
