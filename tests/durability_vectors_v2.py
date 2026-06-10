"""
Vectors + helpers for the SILD persist-before-ack durable v2 intake (Variante A).

Sibling to conformance_vectors_v2.py: that module holds the FM-4 four-pattern
conformance vectors; this one holds the DURABILITY vectors (G1–G6 of the
persist-before-ack spec). The thin runner is tests/test_durability_v2.py.

These are behavioural vectors (crash-injection, recovery, ack-code total function)
rather than the YAML finding-vectors, so the table here is plain Python. Each
guarantee's proof lives in a named test in the runner; the AckCase table drives
the G5 total-ACK-function proof (the branch the conformance vectors cannot reach,
because they assert findings, not the wire ACK code).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

# --- sample HL7 v2 messages (CR-separated, as on the wire), as raw bytes -------

def _msg(*segments: str) -> bytes:
    return ("\r".join(segments) + "\r").encode("utf-8")


# Clean: MSH + PID only — no OBR/OBX/ORC/PV1/RXA -> no findings -> AA.
CLEAN = _msg(
    r"MSH|^~\&|KIS-NORD|KH-HAUPTHAUS|AION|AION-FAC|20260610120000||ADT^A01|CLEAN-1|P|2.5",
    r"PID|1||PAT-0001^^^HOSP||Mustermann^Erika||19700101|F",
)

# Critical: ORC-2 (Placer Order Number) present -> RS-ORC-01 CRITICAL -> AE.
CRITICAL = _msg(
    r"MSH|^~\&|KIS-NORD|KH-HAUPTHAUS|AION|AION-FAC|20260610120100||ORM^O01|CRIT-1|P|2.5",
    r"ORC|NW|PLACER-9001|FILLER-1|||||20260610120100",
)

# Same control id as CRITICAL but a second copy — for the G3 duplicate-marker test.
CRITICAL_DUP = CRITICAL

# Malformed: truncated MSH (missing fields) — parseable-but-empty.
# markers: msh3='KIS-NORD', msh4/msh10 NULL. analyse() does not raise -> AA.
MALFORMED = (b"MSH|^~\\&|KIS-NORD")

# G6: a CRITICAL message (so an audit record is written) carrying a secret token
# in PID-5 (patient name) — a field NO detector rule echoes, so it must never
# appear in the JSONL audit line, only in the durable store.
SECRET_TOKEN = "ZZSECRET-NAME-7777"
SECRET = _msg(
    r"MSH|^~\&|KIS-NORD|KH-HAUPTHAUS|AION|AION-FAC|20260610120200||ORM^O01|SEC-1|P|2.5",
    r"PID|1||PAT-7777^^^HOSP||" + SECRET_TOKEN + r"^Max||19800202|M",
    r"ORC|NW|PLACER-7777|FILLER-7|||||20260610120200",
)


# --- G5: ACK code is a total function of the analysis outcome ------------------

@dataclass
class AckCase:
    name:        str
    raw:         bytes
    raise_in_analyse: bool   # simulate an analyser exception (unparseable path)
    expected_ack: str        # "AA" | "AE"
    why:         str


ACK_CASES: List[AckCase] = [
    AckCase("unparseable->AA (poison-loop guard)", CLEAN, True,  "AA",
            "analyser error: already durable, NAK would loop -> AA"),
    AckCase("clean->AA",                           CLEAN, False, "AA",
            "no critical finding -> AA"),
    AckCase("critical->AE (K-2 preserved)",        CRITICAL, False, "AE",
            "RS-ORC-01 critical -> AE (signal, not reject)"),
]


# --- Step 3: patient-key extraction (PID-3, MR-typed, Authority|ID) -----------

# Real sample shape: PID-3 = ID^^^Authority^Type, MR-typed.
PATIENT_REAL = _msg(
    r"MSH|^~\&|KIS|KH|AION|AF|20260415080000||ADT^A01|R-1|P|2.5.1",
    r"PID|1||P-2026-12345^^^HOSP^MR||Mustermann^Max||19580312|M",
)
# Two MR repetitions (two authorities) -> key SET, deletion hits ANY (edge 1).
MULTI_MR = _msg(
    r"MSH|^~\&|KIS|KH|AION|AF|20260101||ADT^A01|M-1|P|2.5",
    r"PID|1||P-M^^^HOSP^MR~E-9^^^EXT^MR||A^B||19700101|M",
)
# MR present but Assigning Authority (CX-4) empty -> uncertain (edge 2).
EMPTY_AUTH_MR = _msg(
    r"MSH|^~\&|KIS|KH|AION|AF|20260101||ADT^A01|EA-1|P|2.5",
    r"PID|1||P-NOAUTH^^^^MR||A^B||19700101|M",
)
# Technical message: NO PID at all -> patientless (belongs to no patient).
TECHNICAL = _msg(
    r"MSH|^~\&|APP|FAC|RCV|RF|20260101||ACK^A01|TECH-1|P|2.5",
    r"MSA|AA|SOME-ID",
)
# PID-3 PRESENT but unreadable (no MR type / no components) -> the REAL uncertain:
# it could belong to any patient, including X.
BROKEN_PID = _msg(
    r"MSH|^~\&|KIS|KH|AION|AF|20260101||ADT^A01|BRK-1|P|2.5",
    r"PID|1||UNREADABLE-PID3-NO-COMPONENTS||A^B||19700101|M",
)


@dataclass
class KeyCase:
    name:     str
    raw:      bytes
    expected: List[str]


KEY_CASES: List[KeyCase] = [
    KeyCase("real sample PID-3 MR -> Authority|ID", PATIENT_REAL, ["HOSP|P-2026-12345"]),
    KeyCase("no MR type (CLEAN PID) -> []",         CLEAN,        []),
    KeyCase("technical / no PID -> []",             TECHNICAL,    []),
    KeyCase("multiple MR reps -> key SET",          MULTI_MR,     ["EXT|E-9", "HOSP|P-M"]),
    KeyCase("MR, empty authority, no default -> []", EMPTY_AUTH_MR, []),
]


# --- Step 4: erasure fixtures — two distinct patients (X-gone / Y-intact) ------

def patient_msg(ctrl: str, idnum: str, authority: str = "HOSP",
                secret: str = "Name", with_critical_orc: str = "") -> bytes:
    segs = [
        rf"MSH|^~\&|KIS|KH|AION|AF|20260101||ADT^A01|{ctrl}|P|2.5",
        rf"PID|1||{idnum}^^^{authority}^MR||{secret}^Max||19700101|M",
    ]
    if with_critical_orc:
        segs.append(rf"ORC|NW|{with_critical_orc}|F1")
    return _msg(*segs)


PATIENT_X_KEY = "HOSP|P-X"
PATIENT_Y_KEY = "HOSP|P-Y"


# --- Step 4 (fix): erasure CLASS — patientless vs unresolved vs keyed ----------

@dataclass
class ClassCase:
    name:     str
    raw:      bytes
    expected: str   # "keyed" | "unresolved" | "patientless"


CLASS_CASES: List[ClassCase] = [
    ClassCase("real MR PID-3 -> keyed",                  PATIENT_REAL, "keyed"),
    ClassCase("multiple MR -> keyed",                    MULTI_MR,     "keyed"),
    ClassCase("no PID at all (technical) -> patientless", TECHNICAL,    "patientless"),
    ClassCase("PID-3 present, no MR type -> unresolved",  CLEAN,        "unresolved"),
    ClassCase("PID-3 present, unreadable -> unresolved",  BROKEN_PID,   "unresolved"),
]
