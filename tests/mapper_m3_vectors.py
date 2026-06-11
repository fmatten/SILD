"""
Vectors + fixtures for M-2 Stufe 3 (M3 — Plausibilitaet + begrenzte Schaetzung).

ALLE Fixtures hier sind SYNTHETISCH und von Claude Code fuer die M3-Garantien
gebaut — NICHT Teil von Friedhelms 54er-Korpus und nicht dort hineingemischt.
(Der End-to-end-Schaetzungs-Beweis in test_mapper_m3.py nutzt zusaetzlich
ECHTE Korpus-Nachrichten msg26/31/53 ueber die echte M-1-Hold-Queue.)

Der Runner gated jede Fixture gegen ihr RICHTIGES Ziel: Bewegungs-Fixtures
muessen m1.classify == usable sein, zeitlose Hold-Fixtures muessen
m1.classify == hold_timequality sein (sonst testeten wir am Hold vorbei).
"""
from __future__ import annotations

from tests.mapper_m1_vectors import _msg, _seg
from tests.mapper_m2c_vectors import _msh_x, _pid3, a08_update, mov, storno

# Zeiten (2026-06-12, vor FIXED_NOW_M2 12:00 — Ausnahme: excessive-Vektoren
# nutzen den 2026-05, damit auch das Ende vor FIXED_NOW liegt).
T0800 = "20260612080000"
T1000 = "20260612100000"
T1200 = "20260612120000"
T1300 = "20260612130000"


def a02_timeless(ctrl: str, *, pid: str, pv1_3: str, evn2: str) -> bytes:
    """ZEITLOSES A02: Bewegungszeit nur in EVN-2 (Erfassungszeit) — fuer A02
    gibt es bewusst keinen EVN-2-Fallback (Anti-Falsch-Datierung), also haelt
    M-1 es als hold_timequality. Genau der Stufe-3-Schaetz-Kandidat."""
    return _msg(_msh_x("A02", ctrl),
                _seg("EVN", {1: "A02", 2: evn2}),
                _seg("PID", {3: _pid3(pid)}),
                _seg("PV1", {2: "I", 3: pv1_3}))


# --- Teil A: Plausibilitaets-Vektoren ----------------------------------------------

# M3-G1/G2: Entlassung VOR Aufnahme — treu baubar, also markiert durchlassen.
IMPL_A01 = mov("A01", "M3-IA01", pid="P920001", pv1_3="ST1^1^1^UKH", ts=T1000)
IMPL_A03 = mov("A03", "M3-IA03", pid="P920001", pv1_3="ST1^1^1^UKH", ts=T0800)
P_IMPL = "UKH|P920001"

# zero_duration: Ende == Start.
ZERO_A01 = mov("A01", "M3-ZA01", pid="P920002", pv1_3="ST1^2^1^UKH", ts=T1000)
ZERO_A03 = mov("A03", "M3-ZA03", pid="P920002", pv1_3="ST1^2^1^UKH", ts=T1000)
P_ZERO = "UKH|P920002"

# overlapping_open_stays: zwei offene Aufenthalte desselben Patienten.
OVL_A01_A = mov("A01", "M3-OV1", pid="P920003", pv1_3="ST1^3^1^UKH", ts=T0800)
OVL_A01_B = mov("A01", "M3-OV2", pid="P920003", pv1_3="ST2^4^1^UKH", ts=T1000)
P_OVL = "UKH|P920003"

# orphan_transfer: Verlegung in eine Episode ohne Aufnahme (A04 ohne A01).
ORPH_A04 = mov("A04", "M3-OR4", pid="P920004", pv1_3="NA^^^UKH", ts=T0800)
ORPH_A02 = mov("A02", "M3-OR2", pid="P920004", pv1_3="ST1^5^1^UKH", ts=T1000)
P_ORPH = "UKH|P920004"

# unknown_ward: Stationscode ausserhalb der (konfigurierten) Liste.
UNKW_A01 = mov("A01", "M3-UW1", pid="P920005", pv1_3="XX9^1^1^UKH", ts=T0800)
P_UNKW = "UKH|P920005"
KNOWN_WARDS = ("KAR", "IMC", "ITS", "NA", "ST1")

# excessive_duration: 16 Tage — ueber der Stations-Schwelle (14d), aber unter
# der Intensiv-Schwelle (60d). Im Mai, damit das Ende vor FIXED_NOW liegt.
EXC_ST_A01  = mov("A01", "M3-EX1", pid="P920006", pv1_3="ST1^6^1^UKH",
                  ts="20260501080000")
EXC_ST_A03  = mov("A03", "M3-EX3", pid="P920006", pv1_3="ST1^6^1^UKH",
                  ts="20260517080000")
P_EXC_ST = "UKH|P920006"
EXC_ITS_A01 = mov("A01", "M3-EI1", pid="P920007", pv1_3="ITS^101^1^UKH",
                  ts="20260501080000")
EXC_ITS_A03 = mov("A03", "M3-EI3", pid="P920007", pv1_3="ITS^101^1^UKH",
                  ts="20260517080000")
P_EXC_ITS = "UKH|P920007"

# --- Teil B: Schaetzungs-Vektoren ---------------------------------------------------

# Das Sandwich: A01 KAR 08:00 (rid 1) .. zeitloses A02 IMC (rid 2) .. A03 12:00
# (rid 3) -> Schranken [08:00, 12:00].
EST_A01      = mov("A01", "E3-A01", pid="P920010", pv1_3="KAR^402^1^UKH", ts=T0800)
EST_TIMELESS = a02_timeless("E3-A02", pid="P920010", pv1_3="IMC^502^1^UKH", evn2=T1000)
EST_A03      = mov("A03", "E3-A03", pid="P920010", pv1_3="IMC^502^1^UKH", ts=T1200)
P_EST = "UKH|P920010"

# M3-G7a: A08 verschiebt die obere Schranke (A03-Grenze 12:00 -> 13:00).
EST_A08_MOVE_T2 = a08_update("E3-U08", pid="P920010", target_ctrl="E3-A03",
                             target_trigger="A03", target_ts=T1200, new_ts=T1300)
# M3-G7b: A13 storniert das A03 — die obere Schranke ENTFAELLT.
EST_A13_CANCEL_T2 = storno("A13", "E3-S13", pid="P920010", target_ctrl="E3-A03",
                           target_trigger="A03", target_ts=T1200, ts=T1300)
