#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
DEP-1 Demo-Nachrichten — REIN SYNTHETISCH (kein echter Patient).

Erzeugt die Interop-Demo-Sequenz A01 -> A02 -> A03 fuer EINEN synthetischen
Patienten (DEMO001 / Visit VDEMO01). Sauber datiert, sodass M-1 alle drei als
`usable` weiterreicht (A01 via EVN, A02 via ZBE-2, A03 via EVN) und M-2 EINEN
Stay mit drei Lage-Segmenten bildet (NA -> IM1 -> Entlassung).

HL7-Segmente sind \\r-getrennt (MLLP-konform).
"""
from pathlib import Path

DEMO = "DEMO001"
VISIT = "VDEMO01"
OUT = Path(__file__).resolve().parent / "messages"

def msg(segs):
    return ("\r".join(segs) + "\r").encode("ascii")

A01 = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612080000||ADT^A01|DEMO0001|P|2.5.1",
    f"EVN|A01|20260612080000",
    f"PID|1||{DEMO}^^^UKH^MR||DEMOPATIENT^ANNA||19700101|F",
    f"PV1|1|I|NA^001^1^UKH||||10001^DEMOARZT^DANA|||IM|||||{VISIT}",
])
A02 = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612120000||ADT^A02|DEMO0002|P|2.5.1",
    f"EVN|A02|20260612120000",
    f"ZBE|1|20260612120000",
    f"PID|1||{DEMO}^^^UKH^MR||DEMOPATIENT^ANNA",
    f"PV1|1|I|IM1^210^2^UKH||||10001^DEMOARZT^DANA|||IM|||||{VISIT}",
])
A03 = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612160000||ADT^A03|DEMO0003|P|2.5.1",
    f"EVN|A03|20260612160000",
    f"PID|1||{DEMO}^^^UKH^MR||DEMOPATIENT^ANNA",
    f"PV1|1|I|IM1^210^2^UKH||||10001^DEMOARZT^DANA|||IM|||||{VISIT}",
])

# --- Rot-Negativ-Sample (P6 Rot-Korpus) ---------------------------------------
# RS-ORC-01 (sild_detector.py): ein ORC-Segment mit nicht-leerem ORC-2 (Placer
# Order Number) ist ein gebrochener Verweis auf einen Auftrag, dessen Kontext der
# Sender NICHT mitliefert -> Reference Severing (kritisch) -> ack_code="AE" +
# sild_losses_total{pattern="Reference Severing",severity="critical"}.
# Herkunft des Musters: tests/durability_vectors_v2.py (CRITICAL / RS-ORC-01,
# CI-Contract expected_ack="AE"). Eigener Patient/Visit (DEMORS1), damit das rote
# Sample NICHT in den sauberen DEMO001-Stay (A01->A02->A03) einflieSSt.
RS_DEMO  = "DEMORS1"
RS_VISIT = "VDEMORS1"
RS = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612090000||ADT^A01|DEMO0004|P|2.5.1",
    f"EVN|A01|20260612090000",
    f"PID|1||{RS_DEMO}^^^UKH^MR||DEMOPATIENT^ROBERT||19650505|M",
    f"PV1|1|I|NA^001^1^UKH||||10001^DEMOARZT^DANA|||IM|||||{RS_VISIT}",
    f"ORC|NW|PLACER-DEMO9001|FILLER-1|||||20260612090000",
])

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, raw in (("demo01_adt_a01.hl7", A01),
                      ("demo02_adt_a02.hl7", A02),
                      ("demo03_adt_a03.hl7", A03),
                      ("demo04_adt_rs.hl7",  RS)):
        (OUT / name).write_bytes(raw)
        print(f"[demo] {OUT / name} ({len(raw)} B)")
