"""
Vectors + fixtures for the SILD M-2 ADT-Mapper Stufe 1 (sild_mapper_m2).

Sibling to mapper_m1_vectors.py; the thin runner is tests/test_mapper_m2.py.

Two fixture sources, kept strictly apart:
  1. FRIEDHELMS KORPUS (committed, samples/adt_m2_corpus/, 54 messages) — loaded
     byte-identical from disk; the per-patient expectations below are derived
     from the corpus README sequences.
  2. SYNTHETIC fixtures BUILT HERE by Claude Code (labeled as such): the
     clean-dated A02 derivations (`with_zbe`), the interface sample
     (samples/adt_m2_interface/), and the window/Sperre/trap vectors. They are
     NEVER mixed into the 54er corpus.

Every direct-feed fixture is gated through m1.classify(...) == usable by the
runner's feeder — proving the direct feed only contains events M-1 WOULD
forward (the tests check against the right target).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import sild_mapper_m1 as m1   # noqa: E402 — conftest.py sys.path injection

from tests.mapper_m1_vectors import _msg, _msh, _seg, adt  # noqa: F401 (re-used builders)

# Deterministic reference clock: AFTER every corpus event (corpus spans
# 2026-06-10 .. 2026-06-11), within M-1's absurd-future bound.
FIXED_NOW_M2 = datetime(2026, 6, 12, 12, 0, 0, tzinfo=timezone.utc)

# --- corpus loading (Friedhelms Korpus, byte-identical from disk) --------------

CORPUS_DIR = (Path(__file__).resolve().parents[1]
              / "sild_monitoring_stack" / "samples" / "adt_m2_corpus")
INTERFACE_SAMPLE = (Path(__file__).resolve().parents[1]
                    / "sild_monitoring_stack" / "samples" / "adt_m2_interface"
                    / "adt_a02_zbe_clean_P100005.hl7")


def load_corpus() -> List[bytes]:
    """All 54 corpus messages in send order (msg000001..msg000054)."""
    files = sorted(CORPUS_DIR.glob("msg*.hl7"))
    assert len(files) == 54, f"corpus must hold 54 messages, found {len(files)}"
    return [f.read_bytes() for f in files]


def corpus_msg(n: int) -> bytes:
    """One corpus message by its number (msg{n:06d}_*.hl7)."""
    matches = list(CORPUS_DIR.glob(f"msg{n:06d}_*.hl7"))
    assert len(matches) == 1, f"corpus message {n} not found"
    return matches[0].read_bytes()


def interface_a02() -> bytes:
    """The SEPARATE clean-dated A02 sample (synthetic-labeled, NOT corpus)."""
    return INTERFACE_SAMPLE.read_bytes()


# --- SYNTHETIC derivation: clean-dated A02 (Claude-built, labeled) --------------

def with_zbe(raw: bytes, *, ctrl_suffix: str = "-Z") -> bytes:
    """
    with_zbe ist eine TEST-Ableitung — NIE auf produktive Daten anwenden.

    Sie behandelt EVN-2 (ERFASSUNGSzeit) als ZBE-2 (BEWEGUNGSzeit) NUR zur
    Pruefung der Segment-TOPOLOGIE (vier Segmente, Grenzfolge), nicht der
    Zeit-Provenienz: ausserhalb der Tests waere genau das die Erfassung-als-
    gemessen-Verwechslung, gegen die die Provenienz (M2-G7) gebaut ist.
    Deshalb lebt die Funktion ausschliesslich im Test-Namespace (tests/) und
    ist aus dem Mapper-Modul nicht importierbar.

    SYNTHETIC TEST DERIVATION (Claude Code), not a corpus edit: returns a copy
    of a corpus message with a ZBE segment inserted after EVN, carrying ZBE-2 =
    the message's EVN-2 time, MSH-10 retagged (ctrl_suffix) so the marker never
    collides with the corpus original. This is how the briefing's "sauber-
    datierter A02" is built for the direct-feed vectors (the end-to-end proof
    uses the separate sample).
    """
    text = raw.decode("utf-8")
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln]
    out: List[str] = []
    for line in lines:
        f = line.split("|")
        if f[0] == "MSH" and len(f) > 9 and ctrl_suffix:
            f[9] = f[9] + ctrl_suffix
            line = "|".join(f)
        out.append(line)
        if f[0] == "EVN":
            evn2 = f[2].strip() if len(f) > 2 else ""
            assert evn2, "with_zbe needs an EVN-2 time to promote into ZBE-2"
            out.append(f"ZBE|1|{evn2}")
    return ("\r".join(out) + "\r").encode("utf-8")


def iso(hl7_ts: str) -> str:
    """HL7 TS -> the ISO-UTC string M-2 stores (sortable)."""
    dt = m1.parse_hl7_ts(hl7_ts)
    assert dt is not None
    return dt.isoformat()


# --- expected corpus reconstruction (from the README-verified sequences) -------
# Through M-1 the five corpus A02 (time only in EVN-2) are HELD, so 14 of 19
# ADT reach M-2: per patient the A04/A01/A03 chain below.

@dataclass
class ExpectedStay:
    pattern:  str
    status:   str                                   # open | closed
    visit_id: Optional[str]
    segments: List[Tuple[str, str, Optional[str]]]  # (ward, start_iso, end_iso|None)


EXPECTED_CORPUS_STAYS = {
    "UKH|P100001": ExpectedStay("B", "open", "V100001", [
        ("NA",  iso("20260610080000"), iso("20260610080500")),
        ("IM1", iso("20260610080500"), None),
    ]),
    "UKH|P100002": ExpectedStay("B", "open", "V100002", [
        ("NA",  iso("20260610103000"), iso("20260610104000")),
        ("CH1", iso("20260610104000"), None),       # ENDO-A02 held by M-1
    ]),
    "UKH|P100003": ExpectedStay("B", "open", "V100003", [
        ("NA",  iso("20260610121000"), iso("20260610121500")),
        ("IM2", iso("20260610121500"), None),
    ]),
    "UKH|P100004": ExpectedStay("C", "closed", "V100004", [
        ("AMB", iso("20260610140000"), iso("20260611001500")),
    ]),
    "UKH|P100005": ExpectedStay("A", "closed", "V100005", [
        ("KAR", iso("20260610152000"), iso("20260611180000")),  # all A02 held
    ]),
    "UKH|P100006": ExpectedStay("B", "open", "V100006", [
        ("NA",  iso("20260610183000"), iso("20260610184500")),
        ("GYN", iso("20260610184500"), None),       # GYN^221-A02 held
    ]),
    "UKH|P100007": ExpectedStay("B", "open", "V100007", [
        ("NA",  iso("20260610213000"), iso("20260610214500")),
        ("NEU", iso("20260610214500"), None),
    ]),
}

# M-1 sighting of the full corpus (19 ADT: 14 usable, 5 A02 held; 35 non-ADT
# ORM/ORU/MDM/ORR ignored).
EXPECTED_M1_CORPUS_COUNTS = {"usable": 14, "hold_timequality": 5, "ignored": 35}

# The four-segment vector (M2-G1 of the briefing): P100005's full chain with
# the three A02 promoted to clean-dated (ZBE-2). One stay, FOUR segments, the
# IMC pair temporally apart and NEVER collapsed by ID.
def p100005_clean_chain() -> List[bytes]:
    return [
        corpus_msg(26),            # A01  I  KAR^402^1     15:20 (06-10)
        with_zbe(corpus_msg(31)),  # A02  I  IMC^502^1     17:30 (06-10)  [synthetic ZBE]
        with_zbe(corpus_msg(51)),  # A02  I  ITS^101^1     08:00 (06-11)  [synthetic ZBE]
        with_zbe(corpus_msg(52)),  # A02  I  IMC^502^2     12:00 (06-11)  [synthetic ZBE]
        corpus_msg(53),            # A03  I                18:00 (06-11)
    ]


EXPECTED_P100005_CLEAN_SEGMENTS = [
    # (pv1_3_raw, ward, room, bed, start_iso, end_iso)
    ("KAR^402^1^UKH", "KAR", "402", "1", iso("20260610152000"), iso("20260610173000")),
    ("IMC^502^1^UKH", "IMC", "502", "1", iso("20260610173000"), iso("20260611080000")),
    ("ITS^101^1^UKH", "ITS", "101", "1", iso("20260611080000"), iso("20260611120000")),
    ("IMC^502^2^UKH", "IMC", "502", "2", iso("20260611120000"), iso("20260611180000")),
]

# Granularity / Gap-2 vector: P100006 with the corpus MSG54 promoted clean —
# GYN^220^1 -> GYN^221^2 (same ward, different room/bed).
def p100006_clean_chain() -> List[bytes]:
    return [corpus_msg(34), corpus_msg(35), with_zbe(corpus_msg(54))]


# --- SYNTHETIC window / Sperre / trap vectors (Claude-built) --------------------

UKH_AUTH = "UKH"


def pid3(pid: str) -> str:
    return f"{pid}^^^{UKH_AUTH}^MR"


def adt_move(
    trigger: str,
    ctrl: str,
    *,
    pid: str,
    pv1_class: str = "I",
    pv1_3: str = "STA^101^1^UKH",
    evn6: Optional[str] = None,
    visit: Optional[str] = None,
    pv1_4: Optional[str] = None,
) -> bytes:
    """Synthetic movement ADT: EVN-6 movement time, PID-3 MR key, PV1 class +
    location (+ optional PV1-4 Aufnahmeart and corpus-style visit at PV1-15)."""
    pv1_fields = {2: pv1_class, 3: pv1_3}
    if pv1_4:
        pv1_fields[4] = pv1_4
    if visit:
        pv1_fields[15] = visit
    evn_fields = {1: trigger}
    if evn6:
        evn_fields[6] = evn6
    return adt(trigger, ctrl,
               _seg("EVN", evn_fields), _seg("PID", {3: pid3(pid)}), _seg("PV1", pv1_fields))


# Ueber-Kontaktierungs-Sperre (M2-G4): four synthetic patients in the implicit
# ward-level unit NA (no room/bed). Only PC truly overlaps PA's NA segment:
#   PA: NA [08:00, 09:00)   (A04 -> A01 ST1 at 09:00 closes it)
#   PC: NA [08:30, 08:50)   -> OVERLAPS PA          => contact
#   PB: NA [10:00, open)    -> disjoint             => no contact
#   PD: NA [09:00, open)    -> TOUCHES PA's end     => no contact (half-open)
SPERRE_FEED: List[bytes] = [
    adt_move("A04", "SP-A4", pid="P900001", pv1_class="O", pv1_3="NA^^^UKH", evn6="20260612080000"),
    adt_move("A01", "SP-A1", pid="P900001", pv1_class="I", pv1_3="ST1^1^1^UKH", evn6="20260612090000"),
    adt_move("A04", "SP-C4", pid="P900003", pv1_class="O", pv1_3="NA^^^UKH", evn6="20260612083000"),
    adt_move("A01", "SP-C1", pid="P900003", pv1_class="I", pv1_3="ST2^2^1^UKH", evn6="20260612085000"),
    adt_move("A04", "SP-B4", pid="P900002", pv1_class="O", pv1_3="NA^^^UKH", evn6="20260612100000"),
    adt_move("A04", "SP-D4", pid="P900004", pv1_class="O", pv1_3="NA^^^UKH", evn6="20260612090000"),
]

# PV1-4-Falle: Aufnahmeart 'E' (emergency) ist NICHT die Klasse — PV1-2 bleibt
# 'O', das A04 bleibt eine ambulante/NA-Episode (C ohne A01), wird NIE als
# stationaere Aufnahme gelesen.
TRAP_PV1_4_E = adt_move("A04", "TRAP-E", pid="P900010", pv1_class="O",
                        pv1_3="NA^^^UKH", evn6="20260612080000", pv1_4="E")

# Storno-Grenze: A11 ist usable durch M-1 (rueckwirkend relevant), aber Stufe-1
# wendet es NICHT an (deferred, Stufe 2).
STORNO_A11 = adt_move("A11", "ST2-A11", pid="P900011", evn6="20260612080000")

# Nicht sequenzierbar: PID-3 vorhanden aber unlesbar (kein MR-Key) -> usable
# durch M-1, aber M-2 kann nicht zuordnen -> unassigned + Befund; zaehlt als
# 'unresolved' (fail-closed) in jeder Erasure.
UNRESOLVED_PID = adt("A01", "UNRES-1",
                     _seg("EVN", {1: "A01", 6: "20260612080000"}),
                     _seg("PID", {3: "UNREADABLE-NO-COMPONENTS"}),
                     _seg("PV1", {2: "I", 3: "ST1^1^1^UKH"}))

# Jitter-Heilung: A01 kommt VOR dem A04 an (Ankunfts-Vertauschung), beide im
# Jitter-Fenster; die Event-Zeit-Sortierung stellt die NA->Station-Folge her.
JITTER_SWAP_A01 = adt_move("A01", "JIT-A1", pid="P900020", pv1_class="I",
                           pv1_3="ST1^5^1^UKH", evn6="20260612090000", visit="V900020")
JITTER_SWAP_A04 = adt_move("A04", "JIT-A4", pid="P900020", pv1_class="O",
                           pv1_3="NA^^^UKH", evn6="20260612084500")

# A02 ohne offenen Aufenthalt (Out-of-Order -> Stufe 2, Befund statt Raten).
ORPHAN_A02 = adt_move("A02", "OOO-A2", pid="P900030", evn6="20260612090000")

# Offen-Dauer nach Klasse (M2-G6): drei Patienten, drei offene Segmente —
# ambulant (AMB-Episode ohne A03), stationaer (B-stay auf Normalstation ST1),
# intensiv (A-stay auf ITS). Erwartung: ambulant loest FRUEHER aus, stationaer
# bei der 14-d-Pauschale, ITS erst weit spaeter (kein Fehlalarm unter der
# Stationsschwelle).
OVERDUE_AMB_A04 = adt_move("A04", "OD-AMB", pid="P900050", pv1_class="O",
                           pv1_3="AMB^^^UKH", evn6="20260612080000")
OVERDUE_ST_A04  = adt_move("A04", "OD-ST4", pid="P900051", pv1_class="O",
                           pv1_3="NA^^^UKH", evn6="20260612080000")
OVERDUE_ST_A01  = adt_move("A01", "OD-ST1", pid="P900051", pv1_class="I",
                           pv1_3="ST1^7^1^UKH", evn6="20260612083000")
OVERDUE_ICU_A01 = adt_move("A01", "OD-ICU", pid="P900052", pv1_class="I",
                           pv1_3="ITS^101^2^UKH", evn6="20260612080000")

# Erasure-Paar.
ERASE_X_A04 = adt_move("A04", "ER-X4", pid="P900040", pv1_class="O",
                       pv1_3="NA^^^UKH", evn6="20260612080000")
ERASE_X_A01 = adt_move("A01", "ER-X1", pid="P900040", pv1_class="I",
                       pv1_3="ST1^1^1^UKH", evn6="20260612081500")
ERASE_Y_A04 = adt_move("A04", "ER-Y4", pid="P900041", pv1_class="O",
                       pv1_3="NA^^^UKH", evn6="20260612082000")
ERASE_X_KEY = f"{UKH_AUTH}|P900040"
ERASE_Y_KEY = f"{UKH_AUTH}|P900041"
