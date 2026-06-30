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

# --- Rot-Negativ-Samples: TN / TC / AD (DETECT-SAMPLES-45) --------------------
# Wie RS (oben) je EIGENER Patient/Visit, ADT^A01-Envelope mit NA-Location (bildet
# einen sauberen Stay), plus der EXAKTE Trigger-Segment-Wortlaut aus den
# bestehenden Conformance-Vektoren ("SILD Conformance Test Vectors v2 v0.1.md").
# KEIN neuer Detektor-Code — die Samples loesen bestehende Regeln in
# sild_detector.analyse_hl7_message() aus. Severity = was der Vektor
# DETERMINISTISCH erzeugt (nicht erzwungen):
#   TN-CE-01 -> Type Narrowing  / WARNING   (OBX-3 Text ohne code+system)
#   TC-OBR-01 -> Temporal Collapse / WARNING (OBR-7 != OBR-8, beide gesetzt)
#   AD-OBX-01 -> Attribute Dropping / CRITICAL (OBX-2=NM, OBX-15+OBX-16 leer)
# Trigger-Segmente sauber single-pattern (in S3 deterministisch belegt).

# Type Narrowing — Vektor TN-CE-01.positive.obx-3-display-only
TN_DEMO, TN_VISIT = "DEMOTN1", "VDEMOTN1"
TN = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612093000||ADT^A01|DEMO0005|P|2.5.1",
    f"EVN|A01|20260612093000",
    f"PID|1||{TN_DEMO}^^^UKH^MR||DEMOPATIENT^TINA||19800202|F",
    f"PV1|1|I|NA^001^1^UKH||||10001^DEMOARZT^DANA|||IM|||||{TN_VISIT}",
    f"OBR|1|ORD-TN|FILL-TN|58410-2^CBC panel^LN|||20260612093000",
    f"OBX|1|NM|^Troponin T^||0.05|ng/mL||N|||F|||20260612093000|LAB-01|MA-IMMUNO^Roche Cobas^HOSP",
])

# Temporal Collapse — Vektor TC-OBR-01.positive.interval-distinct
TC_DEMO, TC_VISIT = "DEMOTC1", "VDEMOTC1"
TC = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612094000||ADT^A01|DEMO0006|P|2.5.1",
    f"EVN|A01|20260612094000",
    f"PID|1||{TC_DEMO}^^^UKH^MR||DEMOPATIENT^TOMAS||19751212|M",
    f"PV1|1|I|NA^001^1^UKH||||10001^DEMOARZT^DANA|||IM|||||{TC_VISIT}",
    f"OBR|1|ORD-TC|FILL-TC|58410-2^CBC panel^LN|||20260612094000|20260612095000",
    f"OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260612095000|LAB-01|MA-IMMUNO^Roche Cobas^HOSP",
])

# Attribute Dropping — Vektor AD-OBX-01.positive.nm-without-device-and-observer
AD_DEMO, AD_VISIT = "DEMOAD1", "VDEMOAD1"
AD = msg([
    f"MSH|^~\\&|ADT|UKH|KIS|UKH|20260612095000||ADT^A01|DEMO0007|P|2.5.1",
    f"EVN|A01|20260612095000",
    f"PID|1||{AD_DEMO}^^^UKH^MR||DEMOPATIENT^ADA||19900909|F",
    f"PV1|1|I|NA^001^1^UKH||||10001^DEMOARZT^DANA|||IM|||||{AD_VISIT}",
    f"OBR|1|ORD-AD|FILL-AD|58410-2^CBC panel^LN|||20260612095000",
    f"OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260612095000",
])

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, raw in (("demo01_adt_a01.hl7", A01),
                      ("demo02_adt_a02.hl7", A02),
                      ("demo03_adt_a03.hl7", A03),
                      ("demo04_adt_rs.hl7",  RS),
                      ("demo05_adt_tn.hl7",  TN),
                      ("demo06_adt_tc.hl7",  TC),
                      ("demo07_adt_ad.hl7",  AD)):
        (OUT / name).write_bytes(raw)
        print(f"[demo] {OUT / name} ({len(raw)} B)")
