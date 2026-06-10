"""
Vectors + fixtures for the SILD M-1 Mapper (sild_mapper_m1).

Sibling to durability_vectors_v2.py. The thin runner is tests/test_mapper_m1.py.
These are behavioural/classification vectors (relevance filter, three-way time
quality, dedup, persist-before-notify), so the tables here are plain Python.

A FIXED reference NOW makes G4's "ferne Zukunft"/"absurdes Jahr" deterministic
(M-1 is otherwise stateless; only the absurd-bounds check needs a clock, and that
clock is injected, never read implicitly).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

import sild_mapper_m1 as m1   # noqa: E402 — conftest.py sys.path injection

# Deterministic reference clock for all G4 vectors.
FIXED_NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


# --- message builders (CR-separated, raw bytes, as on the wire) ---------------

def _msg(*segments: str) -> bytes:
    return ("\r".join(segments) + "\r").encode("utf-8")


def _seg(name: str, fields_at: dict) -> str:
    """Build one HL7 segment placing values at the given 1-based field indices
    (index 0 is the segment name). Lets us address PV1-44 without 44 literal '|'."""
    n = max(fields_at) if fields_at else 0
    arr = [""] * (n + 1)
    arr[0] = name
    for i, v in fields_at.items():
        arr[i] = v
    return "|".join(arr)


def _msh(trigger: str, ctrl: str, *, msg_code: str = "ADT", msh10: Optional[str] = None) -> str:
    """MSH with a COMPLETE marker by default (msh3=KIS, msh4=KH, msh10=ctrl).
    Pass msh10="" for an incomplete marker (G2 NULL-marker case)."""
    ctrl_field = ctrl if msh10 is None else msh10
    type_field = f"{msg_code}^{trigger}" if trigger else msg_code
    return (rf"MSH|^~\&|KIS|KH|AION|AF|20260610090000||{type_field}|{ctrl_field}|P|2.5")


def adt(trigger: str, ctrl: str, *extra_segments: str, msh10: Optional[str] = None) -> bytes:
    return _msg(_msh(trigger, ctrl, msh10=msh10), *extra_segments)


# A valid in-range event time and the various bad ones (relative to FIXED_NOW).
GOOD_TS      = "20260610100000"   # 2026-06-10 10:00 — within range
OTHER_TS     = "20260609080000"   # a DIFFERENT in-range time (for priority checks)
ABSURD_YEAR  = "19000101000000"   # 1900 sentinel
FAR_FUTURE   = "20310101120000"   # 2031 — > now + 1y
UNPARSEABLE  = "not-a-date"


# --- G3: relevance filter (relevant -> through, irrelevant -> ignored) --------
# Every relevant ADT carries a GOOD time so it lands on `usable` (so the G3 table
# also proves "relevant -> not ignored"). The default movement-time field is
# EVN-6 -> EVN-2 (inspection-backed, see sild_mapper_m1.TimeFieldConfig), so the
# usable fixtures carry EVN-6. PV1-44/45 helpers stay around for the config-
# override proof (a site that maps PV1 instead).

PV1_ADMIT     = _seg("PV1", {44: GOOD_TS})
PV1_DISCHARGE = _seg("PV1", {45: GOOD_TS})


def _evn(trigger: str, occurred: str = GOOD_TS) -> str:
    return _seg("EVN", {1: trigger, 6: occurred})


def _evn2(trigger: str, recorded: str = GOOD_TS) -> str:
    """EVN with only EVN-2 (Recorded) populated — the shape of the real sample."""
    return _seg("EVN", {1: trigger, 2: recorded})


@dataclass
class ClassifyCase:
    name:             str
    raw:              bytes
    expected_kind:    str
    expected_trigger: Optional[str]


# --- G3 + G4 combined classification table ------------------------------------

RELEVANCE_CASES: List[ClassifyCase] = [
    # relevant, intervall-bestimmend (EVN-6 carries the movement time by default)
    ClassifyCase("A01 Aufnahme + EVN-6 -> usable",   adt("A01", "C-A01", _evn("A01")),   m1.USABLE, "A01"),
    ClassifyCase("A02 Verlegung + EVN-6 -> usable",  adt("A02", "C-A02", _evn("A02")),   m1.USABLE, "A02"),
    ClassifyCase("A03 Entlassung + EVN-6 -> usable", adt("A03", "C-A03", _evn("A03")),   m1.USABLE, "A03"),
    # relevant, rueckwirkend veraendernd (Update + Storni durchgereicht!)
    ClassifyCase("A08 Update + EVN-6 -> usable",     adt("A08", "C-A08", _evn("A08")),   m1.USABLE, "A08"),
    ClassifyCase("A11 Storno Aufnahme -> usable",    adt("A11", "C-A11", _evn("A11")),   m1.USABLE, "A11"),
    ClassifyCase("A12 Storno Verlegung -> usable",   adt("A12", "C-A12", _evn("A12")),   m1.USABLE, "A12"),
    ClassifyCase("A13 Storno Entlassung -> usable",  adt("A13", "C-A13", _evn("A13")),   m1.USABLE, "A13"),
    # EVN-6 absent but EVN-2 present (the real sample's shape) -> usable via fallback
    ClassifyCase("A01 + only EVN-2 -> usable",       adt("A01", "C-E2", _evn2("A01")),   m1.USABLE, "A01"),
    # NICHT-ADT -> ignored (not my topic, no finding, no M-2 push)
    ClassifyCase("ORU^R01 (Befund) -> ignored",
                 _msg(_msh("R01", "C-ORU", msg_code="ORU"), _evn("R01")),  m1.IGNORED, "R01"),
    ClassifyCase("RDE^O11 (Order) -> ignored",
                 _msg(_msh("O11", "C-RDE", msg_code="RDE")),               m1.IGNORED, "O11"),
    # known-but-not-interval-relevant ADT -> ignored (documented, extensible boundary)
    ClassifyCase("ADT^A04 Registrierung -> ignored", adt("A04", "C-A04", _evn("A04")),   m1.IGNORED, "A04"),
    ClassifyCase("ADT^A05 Voraufnahme -> ignored",   adt("A05", "C-A05", _evn("A05")),   m1.IGNORED, "A05"),
    # CORRECTION (category error fix): ADT WITH a missing/unreadable trigger code is
    # "my topic but broken" -> hold_malformed + finding, NEVER silently ignored.
    ClassifyCase("ADT, kein Trigger -> hold_malformed",
                 adt("", "C-NT", _evn("A01")),                            m1.HOLD_MALFORMED, None),
    ClassifyCase("ADT, unlesbarer Trigger (XX) -> hold_malformed",
                 _msg(_msh("XX", "C-XT")),                                m1.HOLD_MALFORMED, "XX"),
]


# --- G4: three-way time quality (relevant ADT only; default time field EVN-6) --

TIMEQUALITY_CASES: List[ClassifyCase] = [
    ClassifyCase("good EVN-6 time -> usable",
                 adt("A01", "TQ-1", _evn("A01", GOOD_TS)),            m1.USABLE,           "A01"),
    ClassifyCase("missing time field -> hold_timequality",
                 adt("A01", "TQ-2"),                                  m1.HOLD_TIMEQUALITY, "A01"),
    ClassifyCase("unparseable time -> hold_timequality",
                 adt("A01", "TQ-3", _evn("A01", UNPARSEABLE)),        m1.HOLD_TIMEQUALITY, "A01"),
    ClassifyCase("absurd year 1900 -> hold_timequality",
                 adt("A01", "TQ-4", _evn("A01", ABSURD_YEAR)),        m1.HOLD_TIMEQUALITY, "A01"),
    ClassifyCase("far future -> hold_timequality",
                 adt("A01", "TQ-5", _evn("A01", FAR_FUTURE)),         m1.HOLD_TIMEQUALITY, "A01"),
    # structurally defective: no parseable ADT / MSH-9 missing / broken trigger
    ClassifyCase("no MSH-9 -> hold_malformed",
                 _msg(r"MSH|^~\&|KIS|KH|AION|AF|20260610090000||"),   m1.HOLD_MALFORMED,   None),
    ClassifyCase("ADT without trigger -> hold_malformed",
                 adt("", "TQ-NT", _evn("A01")),                       m1.HOLD_MALFORMED,   None),
    ClassifyCase("garbage / no MSH -> hold_malformed",
                 b"NOTHL7-AT-ALL\rxxx\r",                             m1.HOLD_MALFORMED,   None),
    ClassifyCase("empty -> hold_malformed",
                 b"",                                                 m1.HOLD_MALFORMED,   None),
]


# --- G2: dedup fixtures -------------------------------------------------------

# Two intake rows with the SAME complete marker (transport duplicate).
DUP_A = adt("A01", "DUP-CTRL", _evn("A01"))
DUP_B = adt("A01", "DUP-CTRL", _evn("A01"))   # identical marker

# Two rows with an INCOMPLETE marker (MSH-10 empty) — must NOT be suppressed.
NULL_MARKER_A = adt("A01", "", _evn("A01"), msh10="")
NULL_MARKER_B = adt("A01", "", _evn("A01"), msh10="")


# --- G5: PID-free fixture -----------------------------------------------------

# A relevant ADT that will HOLD (missing time -> finding) carrying a secret token
# in PID-5 (patient name). The token must never reach the finding/mail; only the
# hold-queue raw retains it (G6-analog).
SECRET_TOKEN = "ZZSECRET-NAME-9999"
SECRET_HOLD = adt(
    "A01", "SEC-M1",
    _seg("PID", {3: "PAT-9999^^^HOSP^MR", 5: f"{SECRET_TOKEN}^Max"}),
    # no time field -> hold_timequality -> a finding is produced
)


# --- Erasure fixtures (SILD-SF-1-analog) — held raws are the only PID source ---
# A relevant A01 with NO time field -> hold_timequality, so the raw lands in the
# hold-queue; the PID-3 state then drives the keyed/unresolved/patientless class.

def hold_with_pid(ctrl: str, pid3: str, secret: str = "Name") -> bytes:
    return adt("A01", ctrl, _seg("PID", {3: pid3, 5: f"{secret}^Max"}))


PATIENT_X_KEY = "HOSP|P-X"
PATIENT_Y_KEY = "HOSP|P-Y"

HOLD_X       = hold_with_pid("HX-1", "P-X^^^HOSP^MR")           # keyed -> HOSP|P-X
HOLD_X2      = hold_with_pid("HX-2", "P-X^^^HOSP^MR")           # second X hold (distinct marker)
HOLD_Y       = hold_with_pid("HY-1", "P-Y^^^HOSP^MR")           # keyed -> HOSP|P-Y
HOLD_BROKEN  = hold_with_pid("HB-1", "UNREADABLE-NO-COMPONENTS")  # PID-3 present, unreadable -> unresolved
HOLD_NOPID_A = adt("A01", "HP-1")                              # no PID, no time -> patientless
HOLD_NOPID_B = adt("A01", "HP-2")                              # another patientless hold
HOLD_X_SECRET = hold_with_pid("HX-S", "P-X^^^HOSP^MR", secret=SECRET_TOKEN)
