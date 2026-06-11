"""
Vectors for M-4 (Pull-Kontrakt SILD->AION).

Die ZENTRALE Vektortabelle ist die VERTRAGSFLAECHE selbst: die erwarteten
Spalten der drei Views (docs/aion-pull-contract.md §3-§5). M4-G1 prueft sie
per PRAGMA — ein interner Schema-Refactor, der die Views aendert, schlaegt
hier fehl, BEVOR er B.1b bricht.

Szenario-Fixtures werden aus den Stufe-2/3-Vektoren wiederverwendet
(mapper_m2c_vectors / mapper_m3_vectors) — M-4 fuegt keine neue Fachlichkeit
hinzu, nur Pull-Flaeche + Revision + Strom.
"""
from __future__ import annotations

from tests.mapper_m2c_vectors import mov, storno

# --- M4-G1: die Vertragsflaeche (Spalten exakt wie im Kontrakt-Dokument) --------

EXPECTED_VIEW_COLUMNS = {
    "v_aion_stay": [
        "stay_id", "revision", "pattern", "status",
        "patient_key", "visit_id", "opened_event_ts", "closed_event_ts",
        "stay_markers",
    ],
    "v_aion_segment": [
        "stay_id", "revision", "segment_id", "seq",
        "pv1_3_raw", "ward", "room", "bed",
        "start_ts", "start_provenance", "end_ts", "end_provenance",
        "is_open", "segment_markers",
        "estimate_lower", "estimate_upper",
        "estimate_lower_source", "estimate_upper_source",
    ],
    "v_aion_change": [
        "notification_id", "stay_id", "revision", "kind",
        "after_json", "receipt_id", "created_ts",
    ],
}

# --- M4-G2: synthetische Ergaenzungen fuer die 6-Stellen-Begehung ---------------
# (Korpus liefert A04+A01; A03/A13 synthetisch fuer denselben Patienten.)

G2_A03 = mov("A03", "M4-A03", pid="P100001", pv1_3="IM1^101^1^UKH",
             ts="20260612110000")
G2_A13 = storno("A13", "M4-S13", pid="P100001", target_ctrl="M4-A03",
                target_trigger="A03", target_ts="20260612110000",
                ts="20260612113000")
