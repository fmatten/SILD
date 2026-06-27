# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
P6 Rot-Korpus — headless-Beweis fuer das RS-ORC-Negativ-Sample.

Beweist OHNE Live-Filter/Netz, dass das versionierte Demo-Rot-Sample
(deploy/staging/demo/make_demo_messages.py :: RS) den Inline-Detektor in genau
das rote Outcome treibt, das die Live-Demo zeigen soll:

  - report.has_critical          -> ack_code == "AE"   (K-2 Signal, kein Reject)
  - report.losses enthaelt einen Reference-Severing-Verlust (kritisch)
    -> Live-Metrik sild_losses_total{pattern="Reference Severing"} > 0

Gegenprobe: das saubere Gruen-Sample (A01) bleibt AA, ohne Verluste — damit ist
die Rot/Gruen-Trennung des Korpus festgeschrieben, nicht nur das Rot allein.

Regel (FM-4 Korollar A.4): genau vier Loss-Patterns; RS = "Reference Severing".
Trigger RS-ORC-01: ORC-Segment mit nicht-leerem ORC-2 (Placer Order Number).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Demo-Modul importierbar machen (liegt ausserhalb des per conftest gesetzten
# Stack-Pfads); make_demo_messages hat keine Import-Seiteneffekte (Schreiben nur
# unter __main__), exportiert aber die Sample-Konstanten.
_DEMO_DIR = Path(__file__).resolve().parents[1] / "deploy" / "staging" / "demo"
if str(_DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(_DEMO_DIR))

import make_demo_messages as demo          # noqa: E402

from sild_detector import analyse_hl7_message      # noqa: E402 — conftest sys.path
from sild_durable_store import ack_code_for_report  # noqa: E402

RS_PATTERN = "Reference Severing"


def test_rs_orc_red_sample_is_critical_ae():
    """Das RS-Rot-Sample -> kritisches Finding -> ack AE + RS-Loss (kritisch)."""
    report = analyse_hl7_message(demo.RS.decode("ascii"))

    assert report.has_critical, "RS-ORC-Sample muss ein kritisches Finding liefern"

    code, _text = ack_code_for_report(report)
    assert code == "AE", "kritisches Finding -> ack_code AE (K-2 Signal)"

    patterns = [l.pattern.value for l in report.losses]
    assert RS_PATTERN in patterns, f"erwartet Reference-Severing-Loss, gefunden: {patterns}"

    rs_sev = [l.effective_severity for l in report.losses if l.pattern.value == RS_PATTERN]
    assert "critical" in rs_sev, f"RS-Loss muss kritisch sein, gefunden: {rs_sev}"


def test_green_a01_sample_stays_clean_aa():
    """Gegenprobe: das saubere A01-Gruen-Sample bleibt AA, ohne Verluste."""
    report = analyse_hl7_message(demo.A01.decode("ascii"))

    assert not report.has_critical, "sauberes A01 darf kein kritisches Finding haben"
    code, _text = ack_code_for_report(report)
    assert code == "AA", "sauberes A01 -> ack_code AA"
    assert not report.losses, f"sauberes A01 darf keine Verluste haben, fand: {report.losses}"
