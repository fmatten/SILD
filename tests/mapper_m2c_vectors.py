"""
Vectors + fixtures for M-2 Stufe 2 (M2c — revidierbarer Intervall-Kern).

ALLE Fixtures hier sind SYNTHETISCH und von Claude Code fuer die M2c-Garantien
gebaut (Briefing M-2 Stufe 2, M-2c-4) — sie sind NICHT Teil von Friedhelms
54er-Korpus (samples/adt_m2_corpus/) und werden nicht dort hineingemischt.
Der Korpus enthaelt bewusst keine Storni/Out-of-Order/verspaeteten Events.

ZST = das VERPFLICHTENDE Storno-/Update-Referenzsegment dieser Referenz-
Implementierung: ZST-1 Aktion (CANCELS|UPDATES), ZST-2 MSH-10 des Quell-Events,
ZST-3 Message Type des Quell-Events, ZST-4 Event-Zeit des Quell-Events.

Der duenne Runner ist tests/test_mapper_m2c.py; er nutzt den Stufe-1-Harness
(tests/test_mapper_m2.py) inkl. des m1.classify==usable-Gates fuer jede direkt
eingespeiste Fixture (Beweis: nur Events, die M-1 weiterreichen WUERDE).
"""
from __future__ import annotations

from typing import Optional

from tests.mapper_m1_vectors import _msg, _seg

# Zeiten: alle am 2026-06-12 (vor FIXED_NOW_M2 12:00, s. mapper_m2_vectors).
T0700 = "20260612070000"
T0800 = "20260612080000"
T0830 = "20260612083000"
T0900 = "20260612090000"
T0930 = "20260612093000"
T1000 = "20260612100000"
T1030 = "20260612103000"
T1200 = "20260612120000"


def _msh_x(trigger: str, ctrl: str, *, app: str = "KIS", fac: str = "KH") -> str:
    """MSH mit steuerbarem Sender (msh3/msh4) — fuer die G4-Duplikat-Vektoren
    (gleiches MSH-10, anderer Absender -> vollstaendiger Marker verschieden)."""
    return rf"MSH|^~\&|{app}|{fac}|AION|AF|20260612070000||ADT^{trigger}|{ctrl}|P|2.5"


def _pid3(pid: str) -> str:
    return f"{pid}^^^UKH^MR"


def mov(trigger: str, ctrl: str, *, pid: str, pv1_3: str, ts: str,
        visit: Optional[str] = None, app: str = "KIS", fac: str = "KH") -> bytes:
    """Synthetisches Bewegungs-Event (A01/A03 via EVN-6; A02 via ZBE-2 —
    sauber datiert, M-1-usable)."""
    segs = []
    if trigger == "A02":
        segs.append(_seg("EVN", {1: trigger, 2: ts}))
        segs.append(_seg("ZBE", {2: ts}))                  # gemessene Bewegungszeit
    else:
        segs.append(_seg("EVN", {1: trigger, 6: ts}))
    segs.append(_seg("PID", {3: _pid3(pid)}))
    pv1 = {2: "O" if trigger == "A04" else "I", 3: pv1_3}
    if visit:
        pv1[15] = visit
    segs.append(_seg("PV1", pv1))
    return _msg(_msh_x(trigger, ctrl, app=app, fac=fac), *segs)


def storno(trigger: str, ctrl: str, *, pid: str, target_ctrl: str,
           target_trigger: str, target_ts: str, ts: str,
           action: str = "CANCELS", omit_zst: bool = False,
           app: str = "KIS", fac: str = "KH") -> bytes:
    """Synthetisches Storno (A11/A12/A13) mit (oder ohne — G5) ZST-Referenz."""
    segs = [_seg("EVN", {1: trigger, 6: ts}), _seg("PID", {3: _pid3(pid)})]
    if not omit_zst:
        segs.append(_seg("ZST", {1: action, 2: target_ctrl,
                                 3: f"ADT^{target_trigger}", 4: target_ts}))
    return _msg(_msh_x(trigger, ctrl, app=app, fac=fac), *segs)


def a08_update(ctrl: str, *, pid: str, target_ctrl: str, target_trigger: str,
               target_ts: str, new_ts: str) -> bytes:
    """Synthetisches A08-Update: ZST-1=UPDATES referenziert das Quell-Event,
    die EIGENE Bewegungszeit (EVN-6) ist die NEUE Grenzzeit."""
    return _msg(
        _msh_x("A08", ctrl),
        _seg("EVN", {1: "A08", 6: new_ts}),
        _seg("PID", {3: _pid3(pid)}),
        _seg("ZST", {1: "UPDATES", 2: target_ctrl,
                     3: f"ADT^{target_trigger}", 4: target_ts}),
    )


# --- Basis-Kette (P910001): A01 KAR 08:00 -> A02 IMC 09:00 -> A03 10:00 ---------

P_BASE = "UKH|P910001"
CHAIN_A01 = mov("A01", "RC-A01", pid="P910001", pv1_3="KAR^402^1^UKH", ts=T0800,
                visit="V910001")
CHAIN_A02 = mov("A02", "RC-A02", pid="P910001", pv1_3="IMC^502^1^UKH", ts=T0900,
                visit="V910001")
CHAIN_A03 = mov("A03", "RC-A03", pid="P910001", pv1_3="IMC^502^1^UKH", ts=T1000,
                visit="V910001")

# --- M2c-G3: die drei Storno-Mutationen -----------------------------------------

STORNO_A11_OK = storno("A11", "RC-S11", pid="P910001", target_ctrl="RC-A01",
                       target_trigger="A01", target_ts=T0800, ts=T1030)
STORNO_A12_OK = storno("A12", "RC-S12", pid="P910001", target_ctrl="RC-A02",
                       target_trigger="A02", target_ts=T0900, ts=T1030)
STORNO_A13_OK = storno("A13", "RC-S13", pid="P910001", target_ctrl="RC-A03",
                       target_trigger="A03", target_ts=T1000, ts=T1030)

# --- A08-Update: Grenze RC-A02 (09:00) -> 09:30 ----------------------------------

A08_MOVE_BOUNDARY = a08_update("RC-U08", pid="P910001", target_ctrl="RC-A02",
                               target_trigger="A02", target_ts=T0900, new_ts=T0930)

# --- M2c-G4: MSH-10-Duplikate -----------------------------------------------------
# Decoy: GLEICHES MSH-10 ('DUP-1'), aber anderer Absender, anderer Patient,
# andere Zeit -> darf vom Storno NICHT getroffen werden.

G4_TARGET_A01 = mov("A01", "DUP-1", pid="P910001", pv1_3="KAR^402^1^UKH", ts=T0800)
G4_DECOY_A01  = mov("A01", "DUP-1", pid="P910002", pv1_3="ST9^1^1^UKH", ts=T0700,
                    app="KIS2", fac="KH2")
G4_STORNO = storno("A11", "G4-S11", pid="P910001", target_ctrl="DUP-1",
                   target_trigger="A01", target_ts=T0800, ts=T1030)

# Voll-Duplikat: GLEICHES MSH-10 + Typ + Zeit + Patient (nur Absender anders) ->
# Zielbindung mehrdeutig -> fail-closed, NICHTS wird mutiert.
G4_AMB_A = mov("A01", "AMB-1", pid="P910003", pv1_3="ST1^1^1^UKH", ts=T0800)
G4_AMB_B = mov("A01", "AMB-1", pid="P910003", pv1_3="ST1^1^1^UKH", ts=T0800,
               app="KIS2", fac="KH2")
G4_AMB_STORNO = storno("A11", "AMB-S11", pid="P910003", target_ctrl="AMB-1",
                       target_trigger="A01", target_ts=T0800, ts=T1030)

# --- M2c-G5: fail-closed (ZST fehlt / ZST-3 passt nicht) --------------------------

STORNO_NO_ZST   = storno("A11", "G5-NOZST", pid="P910001", target_ctrl="RC-A01",
                         target_trigger="A01", target_ts=T0800, ts=T1030,
                         omit_zst=True)
STORNO_BAD_ZST3 = storno("A11", "G5-BAD3", pid="P910001", target_ctrl="RC-A01",
                         target_trigger="A02", target_ts=T0800, ts=T1030)

# --- M2c-G6: Tombstone (A12 vor A02 — Out-of-Order) -------------------------------

TB_A01    = mov("A01", "TB-A01", pid="P910010", pv1_3="KAR^402^1^UKH", ts=T0800)
TB_STORNO = storno("A12", "TB-S12", pid="P910010", target_ctrl="TB-A02",
                   target_trigger="A02", target_ts=T0900, ts=T0830)  # VOR dem A02
TB_A02    = mov("A02", "TB-A02", pid="P910010", pv1_3="IMC^502^1^UKH", ts=T0900)

# --- M2c-G8: verspaetetes Normal-Event (A02 nach Festschreiben) --------------------

L8_A01      = mov("A01", "L8-A01", pid="P910020", pv1_3="KAR^402^1^UKH", ts=T0800)
L8_A03      = mov("A03", "L8-A03", pid="P910020", pv1_3="KAR^402^1^UKH", ts=T1200)
L8_LATE_A02 = mov("A02", "L8-A02", pid="P910020", pv1_3="IMC^502^1^UKH", ts=T1000)
P_L8 = "UKH|P910020"
