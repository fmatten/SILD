#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD M-1 — Mapper / Intake-Sichter (read-only over SILD's durable v2 intake).

M-1 ist die Stufe ZWISCHEN SILDs persist-before-ack-Intake (sild_durable_store)
und dem (noch nicht gebauten) Intervall-Aufbau M-2. M-1 liest SILDs Intake-DB
*nur lesend*, sichtet jede Nachricht und entscheidet — zustandsleicht, ohne
Aufenthaltskontext — was an M-2 weitergereicht, was zurueckgehalten und was
ignoriert wird. M-1 baut KEINE Intervalle, widerruft keine Stornos, schaetzt
keine Zeiten und schreibt NIE in SILDs Store (alles M-2/M-3 bzw. fremder Scope).

Garantien (jede mit benanntem Test in tests/test_mapper_m1.py):

  M1-G1  Speichern-vor-Cursor (kein Skip, kein Verlust). Pro Intake-Receipt wird
         die Entscheidung ("Vermerk") durabel committet, BEVOR der Lese-Cursor
         vorgerueckt wird. Crash vor dem Vermerk -> Receipt wird nach Neustart
         erneut gesichtet (kein Skip). Crash nach dem Vermerk, vor dem Cursor ->
         Receipt wird erneut gesichtet, ist aber per receipt_id idempotent
         (keine Doppel-Weiterleitung, kein Doppel-Befund) -> kein Verlust.

  M1-G2  Duplikat-Unterdrueckung (Transport + Neustart), PID-frei begruendet.
         Dedup-Schluessel = vollstaendiger Marker (MSH-3, MSH-4, MSH-10) — die
         gleiche Idempotenz-Marke wie in SILDs Intake (G3 dort). Ein NEUES
         Receipt mit bereits gesehenem vollstaendigen Marker -> suppressed.
         Der seen_marker-Speicher ist durabel -> Unterdrueckung ueberlebt den
         Neustart. UNVOLLSTAENDIGER Marker (irgendeine Komponente NULL) wird NIE
         unterdrueckt (Verlust waere schlimmer als ein Duplikat).

  M1-G3  Relevanz-Filter (durchreichen vs. ignorieren), zustandslos. Relevant =
         intervall-bestimmende ADT-Trigger {A01, A02, A03} und rueckwirkend
         intervall-veraendernde {A08, A11, A12, A13 = Update/Storni}. M-1 reicht
         Storni als relevant DURCH; das Widerrufen eines Intervalls ist M-2.
         NICHT-ADT (ORU/RDE/technisch) und bekannte, nicht intervall-relevante
         ADT (A05/A06/A07/A21/A22 etc.) -> ignoriert (kein Befund, kein
         M-2-Push; bewusste, erweiterbare Grenze). ABER: eine ADT mit fehlendem/
         unlesbarem Trigger-Code (MSH-9 Schluesselfeld) ist NICHT irrelevant,
         sondern strukturell defekt -> hold_malformed + Befund (unparsebar !=
         irrelevant; sonst verschwaende eine potenziell intervall-relevante
         Bewegung spurlos).

  M1-G4  Zeitqualitaet — SYNTAKTISCHE Drei-Wege-Klassifikation, zustandslos:
           usable           — maßgebliches Bewegungs-Zeitfeld (je Trigger
                              konfigurierbar: A01->PV1-44, A03->PV1-45,
                              A02->ZBE-2->EVN-6 [NICHT PV1-44], EVN-Fallback)
                              vorhanden, parsebar, nicht absurd -> an M-2.
           hold_timequality — Zeit fehlt/nicht parsebar/absurd, Event aber
                              strukturell ok -> Hold-Queue + Befund.
           hold_malformed   — strukturell defekt (kein parsebares ADT, MSH-9
                              fehlt) -> Hold-Queue + Befund.
         Semantische Plausibilitaet (Entlassung-vor-Aufnahme) und das SCHAETZEN
         fehlender Zeiten brauchen den Aufenthaltskontext -> ausdruecklich M-2.

  M1-G5  Notifier — Speichern VOR Melden, aktiv, PID-frei. Jeder Befund (aus
         G4-Holds) wird zuerst durabel in der Mapper-DB gespeichert, dann aktiv
         per SMTP zugestellt. Mail-Fehlschlag verliert den Befund NICHT (er
         bleibt durabel, als unzugestellt markiert, erneut zustellbar). Der
         Mail-Inhalt ist PID-frei (Zaehler/Marker/Status/Zeit — NIE PID/Name/
         rohe Bewegungsdaten; Mail ist ein unkontrollierter Kanal). Ohne
         SMTP-Konfig: laute Start-Warnung, Befund trotzdem durabel.

  M1-G6-analog  Die Mapper-DB (Hold-Queue) enthaelt rohe v2-Events -> PID-haltig.
         Encryption-at-rest ist an Ops delegiert (laut dokumentiert); Erasure
         der Mapper-DB ist ein getracktes Folge-Item (analog SILD-SF-1). Hier
         festgehalten, nicht hier geloest.

Stdlib only (sqlite3, smtplib, email). Read path: SILDs intake-DB read-only
(PRAGMA query_only + file:...?mode=ro). Eigene Mapper-DB auf gemountetem Volume.

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
Part of: SILD MLLP Sidecar Demo
"""
from __future__ import annotations

import argparse
import re
import smtplib
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from sild_detector import parse_hl7v2
from sild_durable_store import (
    PKEY_PATIENTLESS,
    PKEY_UNRESOLVED,
    EraseResult,
    PatientKeyConfig,
    SimulatedCrash,
    build_erase_audit_record,
    classify_patient_keys,
    extract_marker,
)

# --- Dispositions: das Sichtungs-Ergebnis pro Intake-Receipt -------------------

USABLE              = "usable"               # G4: an M-2 weitergereicht
IGNORED             = "ignored"              # G3: nicht intervall-relevant
SUPPRESSED_DUPLICATE = "suppressed_duplicate" # G2: schon gesehener Marker
HOLD_TIMEQUALITY    = "hold_timequality"     # G4: Zeit fehlt/absurd, Struktur ok
HOLD_MALFORMED      = "hold_malformed"       # G4: strukturell defekt (kein ADT)

_HOLD_KINDS = (HOLD_TIMEQUALITY, HOLD_MALFORMED)

# --- G3: Relevanz-Filter (intervall-bestimmend + rueckwirkend veraendernd) -----

RELEVANT_TRIGGERS: frozenset = frozenset({
    "A01",  # Aufnahme        — intervall-bestimmend
    "A02",  # Verlegung       — intervall-bestimmend
    "A03",  # Entlassung      — intervall-bestimmend
    "A04",  # Registrierung   — Eintritts-Event der ambulanten/Notaufnahme-Phase.
            #                    Frueher als "nicht intervall-relevant" gefuehrt;
            #                    seit der "Notaufnahme-Phase = eigenes Intervall"-
            #                    Entscheidung IST A04 der Eintritts-Trigger (Muster
            #                    B/C in M-2). M-1 reicht nur syntaktisch durch — die
            #                    B-vs-C-Entscheidung trifft M-2.
    "A08",  # Update          — rueckwirkend intervall-veraendernd
    "A11",  # Storno Aufnahme — rueckwirkend (widerrufen ist M-2)
    "A12",  # Storno Verlegung
    "A13",  # Storno Entlassung
})

# G4: gueltiger ADT-Trigger-Code = 'A' + zwei Ziffern (A01..A99). Der Trigger ist
# ein Schluesselfeld der Bewegung; fehlt er / ist er unlesbar (kein Axx), ist die
# ADT strukturell defekt (hold_malformed), NICHT bloss irrelevant (ignored).
_ADT_TRIGGER_RE = re.compile(r"^A\d{2}$")


def _valid_adt_trigger(trigger: str) -> bool:
    return bool(_ADT_TRIGGER_RE.match(trigger or ""))

# Laute Warnung bei fehlender SMTP-Konfig (M1-G5).
SMTP_NOT_CONFIGURED_WARNING = (
    "[sild-m1] WARNUNG: Daten-Qualitaets-Benachrichtigung NICHT konfiguriert — "
    "Befunde werden nur lokal (Mapper-DB) gespeichert, niemand wird aktiv "
    "benachrichtigt. SMTP (Server/Absender/Empfaenger) ist ein "
    "Pflicht-Konfigurationsschritt (siehe Handbuch)."
)


# ===========================================================================
# G4: syntaktische Zeitqualitaet (zustandslos)
# ===========================================================================

@dataclass
class TimeQualityConfig:
    """
    Grenzen fuer "offensichtlich absurd" (rein syntaktisch, kein Kontext).
    `min_year` faengt das 1900-Sentinel und Vor-Epoche-Muell; `max_future_days`
    faengt die ferne Zukunft. Beides site-konfigurierbar.
    """
    min_year:        int = 1970
    max_future_days: int = 366


# Maßgebliches BEWEGUNGS-Zeitfeld je Trigger (erstes nicht-leeres Kandidatenfeld
# gewinnt; alles standortkonfigurierbar). Finale Regel:
#   A01 Aufnahme   -> PV1-44 (eindeutig)        + EVN-6 -> EVN-2 Fallback*
#   A03 Entlassung -> PV1-45 (eindeutig)        + EVN-6 -> EVN-2 Fallback*
#   A02 Verlegung  -> ZBE-2 -> EVN-6. AUSDRUECKLICH NICHT PV1-44: bei einer
#                     Verlegung wird PV1-44 oft nicht neu gesetzt und bliebe die
#                     AUFNAHMEzeit -> falsch. ZBE ist das dedizierte
#                     Bewegungssegment, EVN-6 der generische Ereigniszeitpunkt.
#                     Greift weder ZBE-2 noch EVN-6 -> hold_timequality (NICHT
#                     spekulativ auf PV1-44 datieren). KEIN EVN-2-Fallback hier.
#   A08/A11/A12/A13 -> Storno/Update-Zeitfeld ist PROFILABHAENGIG und wird in M-2
#                     geklaert (Storno-Verarbeitung = M-2). M-1 klassifiziert nur
#                     syntaktisch gegen ein generisches Default-Feld (EVN-6->EVN-2).
# (*) Fallback gerechtfertigt: EVN-6 ist derselbe Aufnahme-/Entlassungs-
#     Ereigniszeitpunkt, nicht eine fremde (Aufnahme-)Zeit -> nicht irrefuehrend.
#     Das Sample adt_a01_admission.hl7 traegt die Zeit z.B. nur in EVN-2.
# TODO(M-2 / echte Daten): ZWEI offene Punkte, beide auf derselben duerftigen
#   Sample-Lage (kein ZBE, kein EVN-6, keine A02 in den Samples) — daher BEIDE als
#   zu-verifizieren markiert, nicht nur A02:
#   (a) ZBE-Vorkommen und Prioritaet fuer A02 (ZBE-2 vor EVN-6) an echten
#       Verlegungsnachrichten verifizieren.
#   (b) EVN-2 ist Recorded Date/Time (ERFASSUNGSzeit), NICHT Event Occurred.
#       Als Bewegungszeit-Fallback (letzte Stufe bei A01/A03) an echten Daten zu
#       verifizieren. Provenienz haelt das sichtbar (s. _PROVENANCE) -> M-2/AION
#       darf eine Erfassungs-Ersatzzeit nicht als gemessenes Faktum verrechnen.
_PV1_ADMIT     = ("PV1", 44)   # PV1-44 Admit Date/Time      -> gemessene Bewegungszeit
_PV1_DISCHARGE = ("PV1", 45)   # PV1-45 Discharge Date/Time   -> gemessene Bewegungszeit
_ZBE_START     = ("ZBE", 2)    # ZBE-2 Start der Bewegung     -> gemessene Bewegungszeit
_EVN_OCCURRED  = ("EVN", 6)    # EVN-6 Event Occurred         -> Ereigniszeit
_EVN_RECORDED  = ("EVN", 2)    # EVN-2 Recorded Date/Time     -> Erfassungs-ERSATZ (zu verifizieren)

_DEFAULT_TIME_CANDIDATES: dict = {
    "A01": [_PV1_ADMIT,     _EVN_OCCURRED, _EVN_RECORDED],   # Aufnahme
    "A02": [_ZBE_START,     _EVN_OCCURRED],                  # Verlegung -> ZBE-2 -> EVN-6, NICHT PV1-44
    "A03": [_PV1_DISCHARGE, _EVN_OCCURRED, _EVN_RECORDED],   # Entlassung
    "A04": [_EVN_OCCURRED,  _EVN_RECORDED],                  # Registrierung — EVN-6 -> EVN-2 (kein PV1-44 beim A04)
    "A08": [_EVN_OCCURRED,  _EVN_RECORDED],                  # Update — profilabhaengig, final in M-2
    "A11": [_EVN_OCCURRED,  _EVN_RECORDED],                  # Storno Aufnahme — profilabhaengig, M-2
    "A12": [_EVN_OCCURRED,  _EVN_RECORDED],                  # Storno Verlegung — profilabhaengig, M-2
    "A13": [_EVN_OCCURRED,  _EVN_RECORDED],                  # Storno Entlassung — profilabhaengig, M-2
}


@dataclass
class TimeFieldConfig:
    """
    Standortkonfigurierbare Zuordnung Trigger -> geordnete Kandidaten-Felder
    (segment, 0-basierter Feldindex) fuer die Bewegungszeit (analog zum
    konfigurierbaren Patienten-Schluessel). Erstes nicht-leeres Feld gewinnt.
    Default s.o. — A02 ist BEWUSST ohne PV1-44 (Anti-Falsch-Datierung). Ein
    abweichendes Haus ueberschreibt pro Trigger (z.B. {"A02": [("ZBE", 2)]}).
    """
    candidates: dict = field(default_factory=lambda: {
        t: list(c) for t, c in _DEFAULT_TIME_CANDIDATES.items()
    })

    def for_trigger(self, trigger: str) -> List[Tuple[str, int]]:
        return self.candidates.get(trigger, [_EVN_OCCURRED, _EVN_RECORDED])


# Zeit-Provenienz pro Intervallgrenze (Anfang der fuer M-2 vorgemerkten
# Provenienz). Haelt sichtbar, WOHER die verwendete Zeit stammt — damit M-2/AION
# eine gemessene Bewegungszeit von einer Erfassungs-Ersatzzeit unterscheiden und
# letztere NICHT als Faktum in Delta_con verrechnen. PID-frei (nur Feldherkunft).
PROV_MEASURED = "measured"             # PV1-44/45, ZBE-2 — gemessene Bewegungszeit
PROV_EVENT    = "event"                # EVN-6 — Ereigniszeit (Event Occurred)
PROV_RECORDED = "recorded_substitute"  # EVN-2 — Erfassungs-Ersatz (zu verifizieren)

_PROVENANCE: dict = {
    _PV1_ADMIT:     (PROV_MEASURED, "PV1-44 (gemessene Bewegungszeit)"),
    _PV1_DISCHARGE: (PROV_MEASURED, "PV1-45 (gemessene Bewegungszeit)"),
    _ZBE_START:     (PROV_MEASURED, "ZBE-2 (gemessene Bewegungszeit)"),
    _EVN_OCCURRED:  (PROV_EVENT,    "EVN-6 (Ereigniszeit)"),
    _EVN_RECORDED:  (PROV_RECORDED, "EVN-2 (Erfassungs-Ersatz)"),
}


def provenance_label(source_field: Optional[Tuple[str, int]]) -> Optional[str]:
    """Mensch-lesbares, PID-freies Provenienz-Label fuer das genutzte Zeitfeld."""
    if source_field is None:
        return None
    return _PROVENANCE.get(source_field, (PROV_EVENT, str(source_field)))[1]


@dataclass
class Classification:
    """Reines G3+G4-Ergebnis (ohne Dedup — das ist die einzige zustandsbehaftete
    Stufe und liegt in MapperM1.process_receipt). `time_provenance` ist nur fuer
    usable Events gesetzt (woher die genutzte Bewegungszeit stammt)."""
    kind:    str
    trigger: Optional[str]
    marker:  Tuple[Optional[str], Optional[str], Optional[str]]
    reason:  str
    time_provenance: Optional[str] = None


def _msh9(segments: list) -> Optional[Tuple[str, str]]:
    """(message_code, trigger) aus MSH-9, oder None wenn MSH/MSH-9 fehlt."""
    for seg in segments:
        if seg["type"] != "MSH":
            continue
        f = seg["fields"]
        raw9 = f[8].strip() if len(f) > 8 else ""
        if not raw9:
            return None
        parts = raw9.split("^")
        code = parts[0].strip()
        trig = parts[1].strip() if len(parts) > 1 else ""
        return (code, trig) if code else None
    return None


def _field(segments: list, name: str, idx: int) -> str:
    for seg in segments:
        if seg["type"] == name:
            f = seg["fields"]
            return f[idx].strip() if len(f) > idx else ""
    return ""


def resolve_event_time(segments: list, trigger: str,
                       cfg: Optional[TimeFieldConfig] = None
                       ) -> Tuple[str, Optional[Tuple[str, int]]]:
    """G4: das je-Trigger maßgebliche Bewegungs-Zeitfeld als (roher TS-String,
    Quellfeld) — erstes nicht-leeres Kandidatenfeld nach `cfg`. Das Quellfeld
    treibt die Zeit-Provenienz (gemessen vs. Ereignis vs. Erfassungs-Ersatz).
    Liefert ("", None) wenn kein Kandidat greift."""
    cfg = cfg or TimeFieldConfig()
    for seg_name, idx in cfg.for_trigger(trigger):
        val = _field(segments, seg_name, idx)
        if val:
            return val, (seg_name, idx)
    return "", None


def parse_hl7_ts(value: str) -> Optional[datetime]:
    """
    HL7 v2 TS (YYYYMMDD[HHMMSS][...]) -> tz-aware datetime (UTC angenommen) oder
    None. Verlangt mindestens YYYYMMDD (8 fuehrende Ziffern); Stunden/Minuten/
    Sekunden optional. Tz-Offset/Bruchteile/Komponenten werden ignoriert — G4 ist
    syntaktisch, keine praezise Zeitrechnung.
    """
    if not value:
        return None
    digits = ""
    for ch in value.strip():
        if ch.isdigit():
            digits += ch
        else:
            break
    if len(digits) < 8:
        return None
    try:
        y, mo, d = int(digits[0:4]), int(digits[4:6]), int(digits[6:8])
        hh = int(digits[8:10])  if len(digits) >= 10 else 0
        mi = int(digits[10:12]) if len(digits) >= 12 else 0
        ss = int(digits[12:14]) if len(digits) >= 14 else 0
        return datetime(y, mo, d, hh, mi, ss, tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_absurd(dt: datetime, now: datetime, cfg: TimeQualityConfig) -> bool:
    return dt.year < cfg.min_year or dt > now + timedelta(days=cfg.max_future_days)


def classify(
    raw: bytes,
    *,
    now: datetime,
    cfg: Optional[TimeQualityConfig] = None,
    time_fields: Optional[TimeFieldConfig] = None,
) -> Classification:
    """
    G3 (Relevanz) + G4 (Zeitqualitaet), zustandslos. Liefert NIE
    suppressed_duplicate — die Dedup-Ueberlagerung (G2) braucht Store-Zustand und
    liegt in MapperM1.process_receipt.

    Kategorien-Disziplin (Korrektur): eine NICHT-ADT (ORU/RDE/technisch) -> ignored
    (nicht mein Thema). Eine ADT MIT fehlendem/unlesbarem Trigger-Code -> NICHT
    ignored, sondern hold_malformed + Befund: der Trigger ist ein Schluesselfeld
    der Bewegung; verschwaende man sie still, ginge eine potenziell intervall-
    relevante Bewegung spurlos verloren ('unparsebar != irrelevant').
    """
    cfg    = cfg or TimeQualityConfig()
    marker = extract_marker(raw)
    text   = raw.decode("utf-8", errors="replace")
    segments = parse_hl7v2(text)

    msh9 = _msh9(segments)
    if msh9 is None:
        # G4: strukturell defekt — kein parsebarer Nachrichtentyp -> halten, nicht verwerfen.
        return Classification(HOLD_MALFORMED, None, marker,
                              "kein parsebares ADT / MSH-9 (Nachrichtentyp) fehlt")
    code, trigger = msh9

    # G3: Relevanz-Filter — NICHT-ADT ist nicht mein Thema.
    if code != "ADT":
        return Classification(IGNORED, trigger, marker,
                              f"{code}^{trigger} ist keine ADT-Bewegung (M1-G3-Grenze)")

    # ADT = mein Thema. Trigger fehlt/unlesbar (kein Axx) -> kaputt, nicht irrelevant.
    if not _valid_adt_trigger(trigger):
        return Classification(HOLD_MALFORMED, trigger or None, marker,
                              "ADT mit fehlendem/unlesbarem Trigger-Code "
                              "(MSH-9 Schluesselfeld der Bewegung)")

    # Bekannter, aber nicht intervall-relevanter Trigger (A05/A06/A07/...) -> bewusste Grenze.
    if trigger not in RELEVANT_TRIGGERS:
        return Classification(IGNORED, trigger, marker,
                              f"ADT^{trigger} nicht intervall-relevant (M1-G3-Grenze)")

    # G4: syntaktische Drei-Wege-Zeitqualitaet (relevantes ADT).
    ts_raw, src = resolve_event_time(segments, trigger, time_fields)
    if not ts_raw:
        return Classification(HOLD_TIMEQUALITY, trigger, marker,
                              f"Zeitfeld fuer Trigger {trigger} fehlt")
    dt = parse_hl7_ts(ts_raw)
    if dt is None:
        return Classification(HOLD_TIMEQUALITY, trigger, marker,
                              f"Zeit fuer Trigger {trigger} nicht parsebar")
    if _is_absurd(dt, now, cfg):
        return Classification(HOLD_TIMEQUALITY, trigger, marker,
                              f"Zeit fuer Trigger {trigger} syntaktisch absurd "
                              f"(Jahr/ferne Zukunft)")
    # usable -> Zeit-Provenienz mitfuehren (gemessen vs. Ereignis vs. Erfassungs-Ersatz).
    return Classification(USABLE, trigger, marker, "", time_provenance=provenance_label(src))


def marker_complete(marker: Tuple[Optional[str], Optional[str], Optional[str]]) -> bool:
    """G2: nur ein VOLLSTAENDIGER Marker (alle drei Komponenten gesetzt) ist als
    Identitaet sicher genug, um zu unterdruecken."""
    return all(c is not None for c in marker)


# ===========================================================================
# Mapper-DB (eigener Store, schreibt NICHT in SILDs Store)
# ===========================================================================

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class Disposition:
    receipt_id: int
    kind:       str
    trigger:    Optional[str]
    marker:     Tuple[Optional[str], Optional[str], Optional[str]]
    reason:     str = ""
    time_provenance: Optional[str] = None   # nur fuer usable Events (an M-2 mitgereicht)


@dataclass
class Finding:
    """Ein Daten-Qualitaets-Befund (G5). PID-FREI: Marker = MSH-3/4/10 (Sending
    App/Facility/Control-ID = Quellsystem-Metadaten, KEIN PID). Keine rohe Payload,
    kein Name. Die rohe Nachricht liegt nur in der Hold-Queue."""
    receipt_id: int
    kind:       str
    trigger:    Optional[str]
    msh3:       Optional[str]
    msh4:       Optional[str]
    msh10:      Optional[str]
    reason:     str
    created_ts: str
    finding_id: Optional[int] = None


_MAPPER_SCHEMA = """
CREATE TABLE IF NOT EXISTS mapper_cursor (
    id              INTEGER PRIMARY KEY CHECK (id = 0),
    last_receipt_id INTEGER NOT NULL
);
-- M1-G1: der durable "Vermerk" — idempotent per Intake-receipt_id.
-- time_provenance: Herkunft der genutzten Bewegungszeit (nur usable) -> an M-2.
CREATE TABLE IF NOT EXISTS disposition (
    receipt_id      INTEGER PRIMARY KEY,
    kind            TEXT NOT NULL,
    trigger         TEXT,
    msh3            TEXT, msh4 TEXT, msh10 TEXT,
    time_provenance TEXT,
    decided_ts      TEXT NOT NULL
);
-- M1-G2: Dedup-Schluessel (vollstaendiger Marker), durabel ueber Neustart.
CREATE TABLE IF NOT EXISTS seen_marker (
    msh3       TEXT NOT NULL,
    msh4       TEXT NOT NULL,
    msh10      TEXT NOT NULL,
    receipt_id INTEGER NOT NULL,
    PRIMARY KEY (msh3, msh4, msh10)
);
-- M1-G5: Befund — zuerst durabel (delivery_status='pending'), dann gemeldet.
CREATE TABLE IF NOT EXISTS finding (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    trigger         TEXT,
    msh3            TEXT, msh4 TEXT, msh10 TEXT,
    reason          TEXT NOT NULL,
    created_ts      TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'pending',   -- pending|delivered|failed
    delivery_info   TEXT,
    delivered_ts    TEXT
);
CREATE INDEX IF NOT EXISTS idx_finding_delivery ON finding (delivery_status);
-- M1-G6-analog: rohe v2-Events (PID!) — Encryption-at-rest an Ops delegiert.
-- pkey_status (Step-4-Lesart wie SILD): 'keyed' (zuordenbar) / 'unresolved'
-- (PID-3 vorhanden, aber unlesbar -> Restrisiko) / 'patientless' (kein PID-3 ->
-- gehoert zu KEINEM Patienten -> KEIN Restrisiko).
CREATE TABLE IF NOT EXISTS hold_queue (
    receipt_id  INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,
    trigger     TEXT,
    raw         BLOB NOT NULL,
    held_ts     TEXT NOT NULL,
    pkey_status TEXT NOT NULL DEFAULT 'patientless'
);
CREATE INDEX IF NOT EXISTS idx_hold_pkey_status ON hold_queue (pkey_status);
-- Patienten-Schluessel der Hold-Zeilen (Erasure, SILD-SF-1-analog). Kind-Tabelle
-- statt Spalte, weil PID-3 mit '~' mehrere MR-Identifier tragen kann (multi-MR).
CREATE TABLE IF NOT EXISTS hold_patient_key (
    receipt_id  INTEGER NOT NULL,
    patient_key TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hold_patient_key         ON hold_patient_key (patient_key);
CREATE INDEX IF NOT EXISTS idx_hold_patient_key_receipt ON hold_patient_key (receipt_id);
"""


class MapperStore:
    """SQLite-backed Mapper-DB. WAL + synchronous=FULL: der Vermerk (G1) und der
    Befund (G5) sind pro Commit durabel (fsync vor Commit-Return)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_MAPPER_SCHEMA)

    # --- G1: Cursor (durabel, NACH dem Vermerk vorgerueckt) -----------------

    def get_cursor(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_receipt_id FROM mapper_cursor WHERE id=0"
            ).fetchone()
        return row[0] if row else 0

    def set_cursor(self, receipt_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO mapper_cursor (id, last_receipt_id) VALUES (0, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_receipt_id=excluded.last_receipt_id",
                (receipt_id,),
            )

    # --- G1: der durable Vermerk (idempotent per receipt_id) ----------------

    def get_disposition(self, receipt_id: int) -> Optional[Disposition]:
        with self._lock:
            row = self._conn.execute(
                "SELECT kind, trigger, msh3, msh4, msh10, time_provenance "
                "FROM disposition WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
        if not row:
            return None
        kind, trig, msh3, msh4, msh10, prov = row
        return Disposition(receipt_id, kind, trig, (msh3, msh4, msh10), time_provenance=prov)

    # --- G2: Dedup ----------------------------------------------------------

    def marker_seen(self, marker) -> bool:
        if not marker_complete(marker):
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM seen_marker WHERE msh3=? AND msh4=? AND msh10=?", marker
            ).fetchone()
        return row is not None

    # --- G1 + G5: alles in EINEM durablen Commit (Speichern vor Melden/Cursor) --

    def commit_decision(
        self,
        receipt_id: int,
        kind: str,
        trigger: Optional[str],
        marker,
        finding: Optional[Finding],
        *,
        time_provenance: Optional[str] = None,
        hold_raw: Optional[bytes],
        hold_patient_keys: Optional[List[str]] = None,
        hold_pkey_status: str = PKEY_PATIENTLESS,
        record_seen_marker: bool,
        _crash_before_commit: bool = False,
    ) -> Optional[Finding]:
        """Schreibt Vermerk (+ ggf. Befund 'pending', Hold-Queue-Zeile inkl.
        Patienten-Schluessel, seen_marker) als EINE Transaktion und fsynct vor
        Commit-Return. Gibt den gespeicherten Befund (mit finding_id) zurueck —
        Melden passiert NACH diesem Return (G5)."""
        ts = _utcnow_iso()
        msh3, msh4, msh10 = marker
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT OR IGNORE INTO disposition "
                "(receipt_id, kind, trigger, msh3, msh4, msh10, time_provenance, decided_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (receipt_id, kind, trigger, msh3, msh4, msh10, time_provenance, ts),
            )
            stored: Optional[Finding] = None
            if finding is not None:
                cur.execute(
                    "INSERT INTO finding "
                    "(receipt_id, kind, trigger, msh3, msh4, msh10, reason, created_ts, delivery_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                    (finding.receipt_id, finding.kind, finding.trigger,
                     finding.msh3, finding.msh4, finding.msh10, finding.reason, finding.created_ts),
                )
                stored = replace(finding, finding_id=cur.lastrowid)
            if hold_raw is not None:
                cur.execute(
                    "INSERT OR REPLACE INTO hold_queue "
                    "(receipt_id, kind, trigger, raw, held_ts, pkey_status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (receipt_id, kind, trigger, sqlite3.Binary(hold_raw), ts, hold_pkey_status),
                )
                cur.execute("DELETE FROM hold_patient_key WHERE receipt_id=?", (receipt_id,))
                for key in (hold_patient_keys or []):    # same commit as the held raw
                    cur.execute(
                        "INSERT INTO hold_patient_key (receipt_id, patient_key) VALUES (?, ?)",
                        (receipt_id, key),
                    )
            if record_seen_marker:
                cur.execute(
                    "INSERT OR IGNORE INTO seen_marker (msh3, msh4, msh10, receipt_id) "
                    "VALUES (?, ?, ?, ?)",
                    (msh3, msh4, msh10, receipt_id),
                )
            if _crash_before_commit:
                self._conn.rollback()
                raise SimulatedCrash("crash before the durable Vermerk commit")
            self._conn.commit()                          # fsync hier (G1/G5)
            return stored

    # --- G5: Zustellungs-Status (Melden NACH dem Speichern) -----------------

    def set_finding_delivery(self, finding_id: int, ok: bool, info: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE finding SET delivery_status=?, delivery_info=?, delivered_ts=? "
                "WHERE finding_id=?",
                ("delivered" if ok else "failed", info, _utcnow_iso() if ok else None, finding_id),
            )

    def pending_findings(self) -> List[Finding]:
        """G5: Befunde, die (noch) nicht zugestellt sind — Retry/Backlog."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT finding_id, receipt_id, kind, trigger, msh3, msh4, msh10, reason, created_ts "
                "FROM finding WHERE delivery_status != 'delivered' ORDER BY finding_id"
            ).fetchall()
        return [
            Finding(receipt_id=r[1], kind=r[2], trigger=r[3], msh3=r[4], msh4=r[5],
                    msh10=r[6], reason=r[7], created_ts=r[8], finding_id=r[0])
            for r in rows
        ]

    def get_hold_raw(self, receipt_id: int) -> Optional[bytes]:
        with self._lock:
            row = self._conn.execute(
                "SELECT raw FROM hold_queue WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return bytes(row[0]) if row else None

    # --- SILD-SF-1-analog: Erasure der Mapper-DB (Hold-Queue = einzige PID-Quelle) --

    def erase_patient(self, patient_key: str, *, commit: bool = False) -> EraseResult:
        """
        Loescht jede gehaltene Nachricht, die `patient_key` traegt — exakt die
        SILD-Lesart-A-Semantik (wiederverwendet, nicht neu erfunden). Die
        Hold-Queue ist die EINZIGE PID-Quelle der Mapper-DB (finding/disposition/
        seen_marker sind PID-frei und bleiben als inhaltsfreies Audit erhalten).

        FAIL-CLOSED mit der KORREKTEN Unterscheidung (kein globaler Count):
          - patientenlose Hold-Zeile (kein PID-3)            -> NICHT Restrisiko.
          - Hold-Zeile mit PID-3 vorhanden, aber unlesbar    -> 'unresolved',
            zaehlt -> Status incomplete_uncertain (koennte X sein).
        Delete-Praedikat exakt auf den Schluessel (X-weg / Y-intakt). dry-run per
        Default; commit=True loescht wirklich (destruktiver PID-Pfad).
        """
        with self._lock:
            matched = [
                r[0] for r in self._conn.execute(
                    "SELECT DISTINCT receipt_id FROM hold_patient_key WHERE patient_key=? "
                    "ORDER BY receipt_id",
                    (patient_key,),
                ).fetchall()
            ]
            unresolvable = self._conn.execute(
                "SELECT COUNT(*) FROM hold_queue WHERE pkey_status=?", (PKEY_UNRESOLVED,)
            ).fetchone()[0]

            if commit and matched:
                cur = self._conn.cursor()
                cur.execute("BEGIN")
                qmarks = ",".join("?" * len(matched))
                cur.execute(f"DELETE FROM hold_patient_key WHERE receipt_id IN ({qmarks})", matched)
                cur.execute(f"DELETE FROM hold_queue WHERE receipt_id IN ({qmarks})", matched)
                self._conn.commit()

        status = "incomplete_uncertain" if unresolvable > 0 else "complete"
        return EraseResult(
            patient_key=patient_key, deleted=len(matched),
            unresolvable=unresolvable, status=status, dry_run=not commit,
        )

    def counts(self) -> dict:
        with self._lock:
            disp = self._conn.execute("SELECT COUNT(*) FROM disposition").fetchone()[0]
            hold = self._conn.execute("SELECT COUNT(*) FROM hold_queue").fetchone()[0]
            find = self._conn.execute("SELECT COUNT(*) FROM finding").fetchone()[0]
        return {"dispositions": disp, "holds": hold, "findings": find}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ===========================================================================
# Intake-Reader: SILDs Store NUR LESEND
# ===========================================================================

class IntakeReader:
    """Read-only Sicht auf SILDs intake-Tabelle. mode=ro + PRAGMA query_only:
    M-1 kann SILDs Store nicht beschreiben (G6/Spec: 'nur lesend'). Die WAL des
    Schreibers bleibt waehrend SILDs Betrieb offen -> der ro-Reader liest den
    committeten Stand."""

    def __init__(self, path):
        uri = f"file:{Path(path)}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.execute("PRAGMA query_only=ON")

    def scan_after(self, cursor: int) -> List[Tuple[int, bytes]]:
        rows = self._conn.execute(
            "SELECT receipt_id, raw FROM intake WHERE receipt_id > ? ORDER BY receipt_id",
            (cursor,),
        ).fetchall()
        return [(rid, bytes(raw)) for (rid, raw) in rows]

    def close(self) -> None:
        self._conn.close()


# ===========================================================================
# G5: Notifier — aktiv, kanal-abstrahiert, PID-frei
# ===========================================================================

@dataclass
class SmtpConfig:
    host:       str = ""
    port:       int = 25
    sender:     str = ""
    recipients: List[str] = field(default_factory=list)
    use_tls:    bool = False
    timeout:    int = 10

    def is_configured(self) -> bool:
        return bool(self.host and self.sender and self.recipients)


def build_notification(finding: Finding) -> Tuple[str, str]:
    """G5: PID-FREIER Mail-Inhalt. Nur Marker (Quellsystem-Metadaten), Status,
    Zeit, Klassifikation, Grund — NIE Name/PID/rohe Payload."""
    subject = f"[SILD M-1] Daten-Qualitaets-Befund: {finding.kind}"
    body = "\n".join([
        "SILD M-1 Mapper — Daten-Qualitaets-Befund (Inhalt absichtlich PID-frei).",
        "",
        f"Zeitstempel:     {finding.created_ts}",
        f"Befund-ID:       {finding.finding_id}",
        f"Intake-Receipt:  {finding.receipt_id}",
        f"Klassifikation:  {finding.kind}",
        f"Trigger:         {finding.trigger or '-'}",
        f"Marker:          {finding.msh3 or '-'}|{finding.msh4 or '-'}|{finding.msh10 or '-'}",
        f"Grund:           {finding.reason}",
        "",
        "Hinweis: Marker = MSH-3|MSH-4|MSH-10 (Sending App|Facility|Control-ID), "
        "Quellsystem-Metadaten, KEIN Patientenbezug. Die rohe Nachricht liegt nur "
        "in der Mapper-DB (Hold-Queue), nicht in dieser Mail.",
    ])
    return subject, body


class SmtpNotifier:
    """Aktiver SMTP-Kanal. send() faengt JEDE Exception (Netz/Auth/SMTP) und
    liefert (False, info) -> der Aufrufer haelt den Befund durabel (G5)."""

    def __init__(self, cfg: SmtpConfig):
        self.cfg = cfg

    def send(self, subject: str, body: str) -> Tuple[bool, str]:
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"]    = self.cfg.sender
            msg["To"]      = ", ".join(self.cfg.recipients)
            msg.set_content(body)
            with smtplib.SMTP(self.cfg.host, self.cfg.port, timeout=self.cfg.timeout) as s:
                if self.cfg.use_tls:
                    s.starttls()
                s.send_message(msg)
            return True, "sent"
        except Exception as e:                           # noqa: BLE001 — Mail-Fehler verliert nichts
            return False, f"smtp-error: {e.__class__.__name__}: {e}"


class UnconfiguredNotifier:
    """G5: kein aktiver Kanal — Befunde bleiben durabel, niemand wird aktiv
    benachrichtigt. send() liefert immer (False, ...) -> Befund bleibt 'failed'
    und erneut zustellbar, sobald SMTP konfiguriert ist."""

    def send(self, subject: str, body: str) -> Tuple[bool, str]:
        return False, "smtp-not-configured"


def build_notifier(cfg: Optional[SmtpConfig], *, warn: Callable[[str], None] = None):
    """G5: SMTP wenn konfiguriert, sonst laute Warnung + UnconfiguredNotifier.
    Kein stilles Nicht-Benachrichtigen."""
    warn = warn or (lambda m: print(m, file=sys.stderr))
    if cfg is not None and cfg.is_configured():
        return SmtpNotifier(cfg)
    warn(SMTP_NOT_CONFIGURED_WARNING)
    return UnconfiguredNotifier()


# ===========================================================================
# MapperM1: Orchestrierung (G1-Reihenfolge, G2-Dedup, G5-Speichern-vor-Melden)
# ===========================================================================

class MapperM1:
    """
    `forward_fn(receipt_id, raw, trigger)` (optional, best-effort) reicht usable
    Events an M-2 weiter; in dieser Referenz-Implementierung ist M-2 noch nicht
    gebaut -> die disposition-Tabelle IST der Weiterreichungs-Vermerk. `now_fn`
    liefert die G4-Referenzzeit (testbar injizierbar).
    """

    def __init__(
        self,
        reader: IntakeReader,
        store: MapperStore,
        notifier,
        *,
        forward_fn: Optional[Callable[[int, bytes, Optional[str], Optional[str]], None]] = None,
        tq_cfg: Optional[TimeQualityConfig] = None,
        time_fields: Optional[TimeFieldConfig] = None,
        patient_key_config: Optional[PatientKeyConfig] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.reader      = reader
        self.store       = store
        self.notifier    = notifier
        self.forward_fn  = forward_fn
        self.tq_cfg      = tq_cfg or TimeQualityConfig()
        self.time_fields = time_fields or TimeFieldConfig()
        self.patient_key_config = patient_key_config or PatientKeyConfig()
        self.now_fn      = now_fn or (lambda: datetime.now(timezone.utc))

    def process_receipt(self, receipt_id: int, raw: bytes, *, _crash: Optional[str] = None) -> Disposition:
        # G1 (idempotenz): schon vermerkt -> exakt einmal verarbeitet, kein
        # Doppel-Befund/Doppel-Weiterleitung beim Re-Scan nach Crash/Neustart.
        existing = self.store.get_disposition(receipt_id)
        if existing is not None:
            return existing

        c    = classify(raw, now=self.now_fn(), cfg=self.tq_cfg, time_fields=self.time_fields)
        kind = c.kind

        # G2: Dedup-Ueberlagerung (einzige zustandsbehaftete Stufe). Nur ein
        # bereits gesehener VOLLSTAENDIGER Marker unterdrueckt.
        if kind in (USABLE,) + _HOLD_KINDS and marker_complete(c.marker) and self.store.marker_seen(c.marker):
            kind = SUPPRESSED_DUPLICATE

        if _crash == "before_persist":
            raise SimulatedCrash("crash before the durable Vermerk (M1-G1)")

        # G5: Befund + Hold-Queue (rohe v2!) gehoeren zu den Hold-Kinds. Fuer
        # gehaltene Zeilen die Patienten-Schluessel + Erasure-Klasse mit-ableiten
        # (SILD-SF-1-analog) — selbe erprobte Logik wie SILDs Store.
        finding = None
        hold_keys: List[str] = []
        hold_pclass = PKEY_PATIENTLESS
        if kind in _HOLD_KINDS:
            finding = Finding(
                receipt_id=receipt_id, kind=kind, trigger=c.trigger,
                msh3=c.marker[0], msh4=c.marker[1], msh10=c.marker[2],
                reason=c.reason, created_ts=_utcnow_iso(),
            )
            hold_keys, hold_pclass = classify_patient_keys(raw, self.patient_key_config)
        record_seen = kind in (USABLE,) + _HOLD_KINDS and marker_complete(c.marker)

        # Provenienz nur fuer das tatsaechlich weitergereichte usable Event.
        provenance = c.time_provenance if kind == USABLE else None

        # Speichern (durabel) — Vermerk (G1, inkl. Zeit-Provenienz) + Befund
        # 'pending' (G5) in einem Commit.
        stored = self.store.commit_decision(
            receipt_id, kind, c.trigger, c.marker, finding,
            time_provenance=provenance,
            hold_raw=raw if kind in _HOLD_KINDS else None,
            hold_patient_keys=hold_keys,
            hold_pkey_status=hold_pclass,
            record_seen_marker=record_seen,
        )

        # Weiterreichen an M-2 (best-effort, NACH dem durablen Vermerk) — inkl.
        # Zeit-Provenienz, damit M-2/AION eine Erfassungs-Ersatzzeit nicht als
        # gemessenes Faktum verrechnet.
        if kind == USABLE and self.forward_fn is not None:
            try:
                self.forward_fn(receipt_id, raw, c.trigger, provenance)
            except Exception:                            # noqa: BLE001 — best-effort
                pass

        # Melden — erst NACH dem Speichern (G5). Mail-Fehlschlag verliert nichts.
        if stored is not None:
            self._notify(stored)

        return Disposition(receipt_id, kind, c.trigger, c.marker, c.reason,
                           time_provenance=provenance)

    def _notify(self, finding: Finding) -> None:
        subject, body = build_notification(finding)
        ok, info = self.notifier.send(subject, body)
        self.store.set_finding_delivery(finding.finding_id, ok, info)

    def poll_once(self, *, _crash_before_cursor_at: Optional[int] = None) -> List[Disposition]:
        """G1: pro Receipt erst den Vermerk durabel committen, DANN den Cursor
        vorruecken. Crash zwischen beidem -> Re-Scan, idempotent (kein Verlust)."""
        cursor = self.store.get_cursor()
        out: List[Disposition] = []
        for receipt_id, raw in self.reader.scan_after(cursor):
            out.append(self.process_receipt(receipt_id, raw))
            if _crash_before_cursor_at == receipt_id:
                raise SimulatedCrash("crash after the Vermerk, before the cursor advance (M1-G1)")
            self.store.set_cursor(receipt_id)
        return out

    def redeliver_pending(self) -> int:
        """G5: alle noch unzugestellten Befunde erneut aktiv zustellen (Backlog)."""
        n = 0
        for finding in self.store.pending_findings():
            self._notify(finding)
            n += 1
        return n


# ===========================================================================
# CLI / Betrieb
# ===========================================================================

def _build_smtp_config(args) -> Optional[SmtpConfig]:
    if not args.smtp_host:
        return None
    return SmtpConfig(
        host=args.smtp_host, port=args.smtp_port, sender=args.smtp_from,
        recipients=[r.strip() for r in args.smtp_to.split(",") if r.strip()],
        use_tls=args.smtp_tls,
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="sild_mapper_m1",
        description="SILD M-1 Mapper: sichtet SILDs durable v2-Intake (read-only), "
                    "reicht relevante usable Events an M-2 durch, haelt zeit-/struktur-"
                    "defekte zurueck und meldet Daten-Qualitaets-Befunde (PID-frei).",
    )
    p.add_argument("--intake-db", required=True, help="Pfad zu SILDs intake-DB (nur lesend)")
    p.add_argument("--mapper-db", required=True, help="Pfad zur eigenen Mapper-DB (gemountetes Volume)")
    p.add_argument("--poll-interval", type=float, default=5.0, help="Poll-Intervall in Sekunden")
    p.add_argument("--once", action="store_true", help="genau einen Poll-Durchlauf, dann beenden")
    p.add_argument("--smtp-host", default="", help="SMTP-Server (leer -> laute Warnung, nur lokal)")
    p.add_argument("--smtp-port", type=int, default=25)
    p.add_argument("--smtp-from", default="", help="Absender")
    p.add_argument("--smtp-to",   default="", help="Empfaenger (Komma-getrennt)")
    p.add_argument("--smtp-tls",  action="store_true", help="STARTTLS verwenden")
    args = p.parse_args(argv)

    notifier = build_notifier(_build_smtp_config(args))
    reader   = IntakeReader(args.intake_db)
    store    = MapperStore(args.mapper_db)
    mapper   = MapperM1(reader, store, notifier)

    def _poll():
        disp = mapper.poll_once()
        if disp:
            kinds = {}
            for d in disp:
                kinds[d.kind] = kinds.get(d.kind, 0) + 1
            print(f"[sild-m1] poll: {len(disp)} neue Receipts {kinds}")
        return disp

    if args.once:
        _poll()
        store.close(); reader.close()
        return 0
    print(f"[sild-m1] Mapper laeuft. intake-db={args.intake_db} (ro) "
          f"mapper-db={args.mapper_db} poll={args.poll_interval}s")
    try:
        while True:
            _poll()
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("[sild-m1] beendet.")
    finally:
        store.close(); reader.close()
    return 0


def _erase_cli(argv=None) -> int:
    """
    SILD-SF-1-analoge Erasure der Mapper-DB (Hold-Queue). dry-run per DEFAULT;
    --commit loescht wirklich. Schreibt eine INHALTSFREIE Lösch-Audit-Zeile
    (Schluessel/Zaehler/Status/Zeit — nie Payload) nach --erase-log, falls gesetzt.
    Wiederverwendung der SILD-Lösch-Audit-Helfer (nicht neu erfunden).
    """
    p = argparse.ArgumentParser(
        prog="sild_mapper_m1 erase",
        description="Loescht die gehaltenen Nachrichten EINES Patienten aus der "
                    "Mapper-DB (Hold-Queue, SILD-SF-1-analog). dry-run per Default; "
                    "--commit zum Loeschen.",
    )
    p.add_argument("--mapper-db", required=True, help="Pfad zur Mapper-DB")
    p.add_argument("--patient-key", required=True,
                   help="zu loeschender Patienten-Schluessel, Format 'Authority|ID'")
    p.add_argument("--commit", action="store_true",
                   help="wirklich loeschen (ohne -> dry-run, loescht nichts)")
    p.add_argument("--erase-log", default=None,
                   help="inhaltsfreie Lösch-Audit-Zeile (JSONL) hier anhaengen")
    args = p.parse_args(argv)

    store  = MapperStore(args.mapper_db)
    result = store.erase_patient(args.patient_key, commit=args.commit)
    record = build_erase_audit_record(result)
    store.close()

    if args.erase_log:
        import json
        with open(args.erase_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    mode = "DRY-RUN (nichts geloescht)" if result.dry_run else "COMMITTED"
    print(f"[sild-m1-erase] {mode} key={result.patient_key} "
          f"deleted={result.deleted} unresolvable={result.unresolvable} status={result.status}")
    if result.status == "incomplete_uncertain":
        sys.stderr.write(
            f"[sild-m1-erase] WARNUNG: {result.unresolvable} Hold-Zeile(n) mit "
            f"vorhandenem aber unlesbarem PID-3 — Loeschung von {result.patient_key} "
            f"kann NICHT als vollstaendig zertifiziert werden (fail-closed). Manuell pruefen.\n"
        )
    return 0


if __name__ == "__main__":
    # 'erase' Subkommando (SILD-SF-1-analog) ohne den poll-CLI zu stoeren.
    if len(sys.argv) > 1 and sys.argv[1] == "erase":
        sys.exit(_erase_cli(sys.argv[2:]))
    sys.exit(main())
