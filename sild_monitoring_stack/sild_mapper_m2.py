#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD M-2 — ADT-Mapper Stufe 1: Vorwaerts-Rekonstruktion von Aufenthalten.

M-2 ist die Stufe NACH M-1 (sild_mapper_m1): ein eigenstaendiger Prozess mit
eigener Mapper-DB, der M-1s `usable`-Output NUR LESEND konsumiert (M-1s
disposition-Tabelle + SILDs intake-DB fuer die Rohbytes) und daraus `stay`
(Aufenthalt) und `stay_unit_segment` (Lage-Segment) rekonstruiert.

Stufe 1 = der eindeutige VORWAERTSPFAD auf der zeit-sortierten Sequenz mit zwei
Wartefenstern. AUSDRUECKLICH NICHT hier (benannte Grenzen, nicht still):
  - Stufe 2: Storno/Rueckwirkung (A08/A11/A12/A13 -> deferred-Tabelle, kein
    Segment, kein Rewrite), Out-of-Order jenseits des Jitter-Fensters,
    verspaetete Normal-Events, A01 jenseits des Join-Fensters.
  - Stufe 3: semantische Plausibilitaet (Entlassung-vor-Aufnahme, Ortswechsel
    im A03) und das Schaetzen fehlender Zeiten.

Garantien (jede mit benanntem Test in tests/test_mapper_m2.py):

  M2-G1  Idempotenz + Cursor-Disziplin (GEERBT aus M-1, kein neuer Mechanismus).
         Pro Event wird ein durabler "verarbeitet"-Vermerk (receipt_id) UND die
         Event-Identitaet (vollstaendiger Marker MSH-3/4/10) committet, BEVOR
         der Lese-Cursor vorrueckt. Re-gelesenes Event nach Crash/Neustart ->
         KEIN Doppel-Segment. Unvollstaendiger Marker wird NIE unterdrueckt.

  M2-G2  Eintrittsmuster A/B/C. Diskriminator = PV1-2 + ob ein A01 folgt
         (PV2 nur advisory). A01 ohne offene A04-Episode -> Muster A. A04
         eroeffnet eine VORLAEUFIGE Episode (pattern='pending'); folgt ein A01
         im Join-Fenster (Ankunfts-Wanduhr) -> Muster B: EIN stay, das offene
         NA/AMB-Segment wird vorwaerts geschlossen (KEIN Rewrite — die
         Segment-Zeile bleibt dieselbe, nur ihr offenes Ende wird gesetzt).
         Kein A01 im Join-Fenster -> Muster C (festgeschrieben). Ein A01
         JENSEITS des Join-Fensters bindet NICHT (Stufe 2) -> neuer Muster-A-
         stay.

  M2-G3  Event-Invariante. JEDES location-tragende Event (A01/A02/A04) schliesst
         das offene Segment und oeffnet das naechste — keine A02-Sonderlogik;
         der A01 schliesst das NA-Segment. A02 erzeugt IMMER ein Segment, auch
         bei Quelle=Ziel auf der Granularitaet (Gap 2: der Mapper verschmilzt
         NICHTS; die Verschmelzung angrenzender gleicher Kontakt-Einheiten ist
         eine AION-seitige Delta_con-Regel -> M-4, s.u.). Nur ein echtes A03
         schliesst den stay (MDM/ORR sind keine Bewegungen; M-1 filtert sie).

  M2-G4  Zwei Ebenen: Lage-Segment (Faktum) vs. Kontakt-Einheit (abgeleitet).
         M-2 speichert die ROHEN PV1-3-Komponenten am Segment (ward=PV1-3.1,
         room=.2, bed=.3); die Kontakt-Einheit wird zur COMPUTE-Zeit ueber
         `contact_unit(...)` kollabiert (granularity in {ward,room,bed},
         Default ward). Gleiche Einheit zu verschiedenen Zeiten bleibt
         getrennt (NIE ueber ID kollabieren). Implizites NA/AMB (keine Raum-/
         Bettkomponente) faellt auf Stationsebene zurueck. UEBER-
         KONTAKTIERUNGS-SPERRE: Kontakt NUR bei zeitlicher Ueberlappung
         (halb-offene Intervalle; beruehren != ueberlappen).

  M2-G5  Zwei Wartefenster (konfigurierbar, Ankunfts-Wanduhr, konservative
         Defaults), der Mapper haelt NIE an: (1) Jitter-Fenster — ein Event
         wird erst angewandt, wenn es `jitter_window_s` alt (Ankunft) ist; die
         reife Menge wird ZEIT-SORTIERT (Event-Zeit) angewandt -> kleine
         Ankunfts-Vertauschungen (A01 vor A04) heilen sich. (2) Join-Fenster —
         wie lange eine A04-Episode auf ihren A01 wartet (Muster B vs. C).
         Verspaetungs-Protokoll pro Event (Ereigniszeit<->Ankunft, Fenster) als
         Lerngrundlage fuer die Fenstergroessen.

  M2-G6  Offene Segmente: Ende = NULL (NICHT last-known-time). Offen-Dauer-
         Ueberwachung: ueberschreitet ein offenes Segment seine Schwelle ->
         Befund "vermutlich fehlende A03" an den M-1-Notifier (durabel ->
         aktiv, PID-frei), genau einmal pro Segment. Die Schwelle ist NACH
         KLASSE differenziert (eine Pauschale waere in beide Richtungen
         falsch): ambulant kurz (eine nach ~1 Tag noch offene ambulante
         Episode ist verdaechtig), stationaer ~14 d, Intensiv (ITS/IMC)
         deutlich hoeher (langer Verbleib ist dort legitim, kein Fehlalarm).
         Konservative Defaults, konfigurierbar, aus dem Betrieb lernbar
         (OpenOverdueThresholds).

  M2-G7  Zeit-Provenienz an JEDER Segmentgrenze (start UND end):
         measured (PV1-44/45, ZBE-2) / event (EVN-6) / recorded_substitute
         (EVN-2). Eine Erfassungs-Ersatzzeit ist markiert und darf von AION
         nicht als gemessenes Faktum verrechnet werden. Korpus-Realitaet:
         meist EVN-2 -> recorded_substitute.

  M2-G8 (G6-analog)  Die M-2-DB traegt Patienten-Schluessel (PID-haltig!).
         Encryption-at-rest ist an Ops delegiert (laut dokumentiert, wie M-1);
         Erasure wiederverwendet die SILD-Lesart-A-Semantik (EraseResult,
         fail-closed mit unresolved-Unterscheidung, dry-run per Default).
         SILD-SF-3-Migrations-Notiz gilt analog.

AION/M-4-ANFORDERUNGEN — hier NUR dokumentiert, NICHT implementiert:
  (a) Verschmelzung zeitlich angrenzender GLEICHER Kontakt-Einheiten ist eine
      Delta_con-Regel der Compute-Seite. M-2 liefert ehrlich ZWEI Segmente
      (Gap 2) plus den Ableitungsschluessel (rohe PV1-3-Komponenten).
  (b) Delta_con-Bezugszeitpunkt fuer OFFENE Segmente (Ende=NULL): welche
      Referenzzeit fuer "noch andauernd" gilt, entscheidet AION — M-2 liefert
      NULL und nie eine geschaetzte Endzeit. `find_contacts` behandelt offen
      als unbeschraenkt und dokumentiert das.
  (c) Uebergabe: `export_for_aion()` ist die Lese-Schnittstelle auf den
      festgeschriebenen Stand; der aktive Push ist M-4.

AN ECHTEN DATEN ZU VERIFIZIEREN (dokumentiert, nicht geloest — vgl. Briefing §6):
  - Visit-Lage: im Korpus sitzt die Visit-Nummer NICHT in PV1-19, sondern auf
    dem letzten belegten PV1-Feld (Index 15). Default-Kandidaten [19, 15] sind
    korpus-kalibriert; die B-Bindung stuetzt sich PRIMAER auf Patient + A01 im
    Join-Fenster, Visit ist nur bestaetigend/advisory.
  - Zeitfelder: der Korpus traegt nur EVN-2; ZBE-2/EVN-6-Prioritaet fuer A02
    ist an echten Verlegungen zu verifizieren (TimeFieldConfig aus M-1).
  - PV1-3-Granularitaets-Konvention (ward^room^bed) je Haus.
  - Intensiv-Zuordnung fuer die Offen-Dauer-Schwelle: ob eine Einheit
    "Intensiv" ist, haengt am Haus (Location-Praefix ITS/IMC ist nur der
    Korpus-kalibrierte Default, alternativ PV1-2-Klasse/Fachabteilung) —
    STANDORTSPEZIFISCH, nicht raten (OpenOverdueThresholds.icu_ward_prefixes).

Stdlib only (sqlite3). Read path: M-1s Mapper-DB + SILDs intake-DB read-only
(mode=ro + PRAGMA query_only). Eigene M-2-DB auf gemountetem Volume.

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
Part of: SILD MLLP Sidecar Demo
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from sild_detector import parse_hl7v2
from sild_durable_store import (
    PKEY_KEYED,
    PKEY_PATIENTLESS,
    PKEY_UNRESOLVED,
    EraseResult,
    PatientKeyConfig,
    SimulatedCrash,
    build_erase_audit_record,
    classify_patient_keys,
    extract_marker,
)
from sild_mapper_m1 import (
    USABLE,
    Finding,
    SmtpConfig,
    TimeFieldConfig,
    build_notification,
    build_notifier,
    marker_complete,
    parse_hl7_ts,
    provenance_code,
    provenance_label,
    resolve_event_time,
)

# --- Ingest-Outcomes: das durable Verarbeitet-Ergebnis pro Event ---------------

OUT_BUFFERED   = "buffered"              # Sequenz-Input (A01-A04), wartet im Jitter-Fenster
OUT_SUPPRESSED = "suppressed_duplicate"  # M2-G1: Event-Identitaet (Marker) schon verarbeitet
OUT_DEFERRED   = "deferred_stufe2"       # A08/A11/A12/A13 — rueckwirkend -> Stufe 2
OUT_UNASSIGNED = "unassigned"            # kein Patient-Schluessel / keine Zeit -> Befund
OUT_MISSING_RAW = "missing_raw"          # intake-Rohbytes fehlen (z.B. Erasure) — vermerkt

# Event-Status im Puffer.
EV_PENDING    = "pending"     # eingelagert, Jitter-Fenster laeuft
EV_APPLIED    = "applied"     # auf stay/segment angewandt (festgeschrieben)
EV_DEFERRED   = "deferred"    # Stufe-2-Grenze (Storno/Out-of-Order) — durabel, abfragbar
EV_UNASSIGNED = "unassigned"  # nicht sequenzierbar (Schluessel/Zeit) — Befund erhoben

# Stufe-2-Trigger: M-1 reicht sie als usable durch, M-2 Stufe 1 wendet sie NICHT an.
STUFE2_TRIGGERS = frozenset({"A08", "A11", "A12", "A13"})

# Location-tragende Eintritts-/Bewegungs-Trigger der Stufe 1.
MOVEMENT_TRIGGERS = frozenset({"A01", "A02", "A03", "A04"})

# Muster (M2-G2).
PATTERN_PENDING = "pending"   # A04-Episode, Join-Fenster laeuft (B vs. C offen)
PATTERN_A = "A"               # direkt stationaer (A01 ohne A04-Vorlauf)
PATTERN_B = "B"               # Notaufnahme -> stationaer (EIN stay, mehrere Segmente)
PATTERN_C = "C"               # rein ambulant (A04 ohne A01)

# Befund-Kinds (M-1-Notifier-Kanal, PID-frei).
FINDING_OPEN_OVERDUE = "m2_open_overdue"    # vermutlich fehlende A03
FINDING_UNASSIGNED   = "m2_unassigned"      # usable, aber nicht sequenzierbar
FINDING_OUT_OF_ORDER = "m2_out_of_order"    # A02/A03 ohne offenen stay -> Stufe 2

# Kontakt-Einheit-Granularitaet (M2-G4).
GRAN_WARD = "ward"
GRAN_ROOM = "room"
GRAN_BED  = "bed"
GRANULARITIES = (GRAN_WARD, GRAN_ROOM, GRAN_BED)


def contact_unit(ward: str, room: str, bed: str, granularity: str = GRAN_WARD) -> str:
    """
    M2-G4: Kontakt-Einheit ZUR COMPUTE-ZEIT aus den rohen PV1-3-Komponenten
    kollabieren (ward=PV1-3.1, room=.1^.2, bed=.1^.2^.3). Fehlt die feinere
    Komponente (implizites NA/AMB), faellt die Einheit auf die naechst-grobere
    Ebene zurueck (Stationsebene) — strukturell, kein NA-Sonderfall.
    Granularitaetswechsel braucht KEINEN Segment-Eingriff: die Segmente tragen
    die Rohkomponenten, nur diese Ableitung aendert sich.
    """
    if granularity not in GRANULARITIES:
        raise ValueError(f"unbekannte Granularitaet {granularity!r} (erlaubt: {GRANULARITIES})")
    if granularity == GRAN_WARD or not room:
        return ward
    if granularity == GRAN_ROOM or not bed:
        return f"{ward}^{room}"
    return f"{ward}^{room}^{bed}"


@dataclass
class OpenOverdueThresholds:
    """
    M2-G6: Offen-Dauer-Schwellen NACH KLASSE (eine Pauschale ist in beide
    Richtungen falsch): ambulant kurz, stationaer ~14 d (der bisherige
    Default als Fallback), Intensiv deutlich hoeher (langer Verbleib ohne
    fehlende Entlassung ist dort legitim -> sonst Fehlalarm). Konservative
    Defaults, standortkonfigurierbar, aus delay_log/Betrieb lernbar.

    Klassen-Zuordnung (Stufe-1-Regel, AN ECHTEN DATEN ZU VERIFIZIEREN):
      - ambulant  = stay-Muster pending/C (die Muster sind das Ergebnis des
                    PV1-2-Diskriminators, robuster als die rohe Klasse am
                    Einzel-Event).
      - intensiv  = Ward-Praefix in `icu_ward_prefixes` — STANDORTSPEZIFISCH
                    (ITS/IMC ist nur der Korpus-kalibrierte Beispiel-Default;
                    alternative Haeuser mappen ueber Fachabteilung/PV1-2).
      - stationaer = alles andere (Fallback = bisherige 14-d-Pauschale).
    """
    stationary_s: int = 14 * 24 * 3600   # stationaer normal (bisheriger Default)
    icu_s:        int = 60 * 24 * 3600   # Intensiv: deutlich hoeher, Fehlalarm-avers
    ambulatory_s: int = 24 * 3600        # ambulant: nach ~1 Tag offen = verdaechtig
    icu_ward_prefixes: Tuple[str, ...] = ("ITS", "IMC")   # STANDORTSPEZIFISCH (s.o.)

    def classify(self, stay_pattern: str, ward: str) -> Tuple[str, int]:
        """(Klassen-Label, Schwelle in s) fuer ein offenes Segment."""
        if stay_pattern in (PATTERN_PENDING, PATTERN_C):
            return "ambulant", self.ambulatory_s
        if any(ward.startswith(p) for p in self.icu_ward_prefixes if p):
            return "intensiv", self.icu_s
        return "stationaer", self.stationary_s


@dataclass
class WindowConfig:
    """
    M2-G5: die zwei Wartefenster + klassen-differenzierte Offen-Dauer-Schwellen.
    Alles Ankunfts-Wanduhr, standortkonfigurierbar, konservative Defaults. Die
    Groessen sind aus dem Verspaetungs-Protokoll (delay_log) lernbar — Lernen
    selbst ist nicht Stufe 1.
    """
    jitter_window_s: int = 300            # normales Jitter-Fenster (klein)
    join_window_s:   int = 6 * 3600       # Notaufnahme-Join-Fenster A04->A01 (groesser)
    open_overdue:    OpenOverdueThresholds = field(default_factory=OpenOverdueThresholds)


@dataclass
class VisitFieldConfig:
    """
    Visit-Nummer-Kandidaten (1-basierte PV1-Feldindizes, erstes nicht-leeres
    gewinnt). Korpus-Befund (an echten Daten zu verifizieren): PV1-19 ist leer,
    die Visit-Nummer sitzt auf dem letzten belegten PV1-Feld (Index 15). Die
    Visit ist in Stufe 1 nur BESTAETIGEND — die B-Bindung laeuft ueber
    Patient + Join-Fenster.
    """
    candidates: List[int] = field(default_factory=lambda: [19, 15])


@dataclass
class M2Event:
    """Ein geparstes usable-Event aus M-1 (der Sequenz-Input von Stufe 1)."""
    receipt_id:    int
    trigger:       str
    marker:        Tuple[Optional[str], Optional[str], Optional[str]]
    patient_key:   Optional[str]          # Gruppierungs-Schluessel (erster sortierter MR-Key)
    patient_keys:  List[str]              # alle MR-Keys (Erasure)
    pkey_status:   str
    visit_id:      Optional[str]
    patient_class: Optional[str]          # PV1-2 (Diskriminator, advisory fuer Klasse)
    pv1_3_raw:     str                    # rohes PV1-3 (Ableitungsschluessel, M2-G4)
    ward:          str
    room:          str
    bed:           str
    event_ts:      Optional[str]          # ISO-UTC (sortierbar)
    provenance:    Optional[str]          # measured | event | recorded_substitute
    provenance_label: Optional[str]
    arrival_ts:    str = ""               # ISO-UTC Ankunfts-Wanduhr (M-2-Eingang)


@dataclass
class StayRow:
    stay_id:           int
    patient_key:       str
    visit_id:          Optional[str]
    pattern:           str
    status:            str                # open | closed
    opened_receipt:    int
    opened_arrival_ts: str
    opened_event_ts:   str
    closed_receipt:    Optional[int]
    closed_event_ts:   Optional[str]


@dataclass
class SegmentRow:
    segment_id:       int
    stay_id:          int
    seq:              int
    pv1_3_raw:        str
    ward:             str
    room:             str
    bed:              str
    start_ts:         str
    start_provenance: str
    start_receipt:    int
    end_ts:           Optional[str]       # NULL = OFFEN (M2-G6) — nie last-known-time
    end_provenance:   Optional[str]
    end_receipt:      Optional[int]

    def unit(self, granularity: str = GRAN_WARD) -> str:
        return contact_unit(self.ward, self.room, self.bed, granularity)


def _pv1_field(segments: list, idx: int) -> str:
    for seg in segments:
        if seg["type"] == "PV1":
            f = seg["fields"]
            return f[idx].strip() if len(f) > idx else ""
    return ""


def parse_usable_event(
    receipt_id: int,
    raw: bytes,
    trigger: str,
    *,
    time_fields: Optional[TimeFieldConfig] = None,
    patient_key_config: Optional[PatientKeyConfig] = None,
    visit_fields: Optional[VisitFieldConfig] = None,
) -> M2Event:
    """
    Parst die Sequenz-Sicht eines usable-Events: Patient-Schluessel (gleiche
    erprobte Extraktion wie SILD/M-1), PV1-2-Klasse, ROHE PV1-3-Komponenten,
    Visit (advisory), Bewegungszeit + Provenienz (dieselbe TimeFieldConfig wie
    M-1 — eine Regel, zwei Stufen). Zustandslos; arrival_ts setzt der Ingest.
    """
    visit_fields = visit_fields or VisitFieldConfig()
    segments = parse_hl7v2(raw.decode("utf-8", errors="replace"))
    keys, pkey_status = classify_patient_keys(raw, patient_key_config)

    pv1_3 = _pv1_field(segments, 3)
    comps = pv1_3.split("^") if pv1_3 else []
    ward = comps[0].strip() if len(comps) > 0 else ""
    room = comps[1].strip() if len(comps) > 1 else ""
    bed  = comps[2].strip() if len(comps) > 2 else ""

    visit = None
    for idx in visit_fields.candidates:
        v = _pv1_field(segments, idx)
        if v:
            visit = v
            break

    ts_raw, src = resolve_event_time(segments, trigger, time_fields)
    dt = parse_hl7_ts(ts_raw)
    return M2Event(
        receipt_id=receipt_id,
        trigger=trigger,
        marker=extract_marker(raw),
        patient_key=keys[0] if keys else None,
        patient_keys=keys,
        pkey_status=pkey_status,
        visit_id=visit,
        patient_class=_pv1_field(segments, 2) or None,
        pv1_3_raw=pv1_3,
        ward=ward, room=room, bed=bed,
        event_ts=dt.isoformat() if dt else None,
        provenance=provenance_code(src),
        provenance_label=provenance_label(src),
    )


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# ===========================================================================
# M-2-DB (eigener Store; durchsuchbar: Patient / Visit / Zeitraum — Stufe-2-
# Voraussetzung). Schreibt NIE in M-1s DB oder SILDs Store.
# ===========================================================================

_M2_SCHEMA = """
CREATE TABLE IF NOT EXISTS m2_cursor (
    id              INTEGER PRIMARY KEY CHECK (id = 0),
    last_receipt_id INTEGER NOT NULL
);
-- M2-G1: durabler "verarbeitet"-Vermerk pro Intake-Receipt (geerbt aus M-1).
CREATE TABLE IF NOT EXISTS m2_processed (
    receipt_id   INTEGER PRIMARY KEY,
    msh3         TEXT, msh4 TEXT, msh10 TEXT,
    outcome      TEXT NOT NULL,
    processed_ts TEXT NOT NULL
);
-- M2-G1: Event-Identitaet (vollstaendiger Marker) — Re-Read unter NEUER
-- receipt_id erzeugt KEIN Doppel-Segment.
CREATE TABLE IF NOT EXISTS m2_seen_marker (
    msh3       TEXT NOT NULL,
    msh4       TEXT NOT NULL,
    msh10      TEXT NOT NULL,
    receipt_id INTEGER NOT NULL,
    PRIMARY KEY (msh3, msh4, msh10)
);
-- Der Event-Puffer (Jitter-Fenster) + die Stufe-2-Ablage (deferred/unassigned).
-- patient_key ist PID-haltig (M2-G8) — Encryption an Ops delegiert.
CREATE TABLE IF NOT EXISTS m2_event (
    receipt_id       INTEGER PRIMARY KEY,
    patient_key      TEXT,
    visit_id         TEXT,
    trigger          TEXT NOT NULL,
    patient_class    TEXT,
    pv1_3_raw        TEXT,
    ward             TEXT, room TEXT, bed TEXT,
    event_ts         TEXT,
    provenance       TEXT,
    provenance_label TEXT,
    arrival_ts       TEXT NOT NULL,
    status           TEXT NOT NULL,
    status_reason    TEXT,
    pkey_status      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_m2_event_status  ON m2_event (status, arrival_ts);
CREATE INDEX IF NOT EXISTS idx_m2_event_patient ON m2_event (patient_key, event_ts);
-- Alle MR-Keys eines Events (PID-3 kann mit '~' mehrere tragen) — Erasure-Basis.
CREATE TABLE IF NOT EXISTS m2_event_patient_key (
    receipt_id  INTEGER NOT NULL,
    patient_key TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_m2_evkey         ON m2_event_patient_key (patient_key);
CREATE INDEX IF NOT EXISTS idx_m2_evkey_receipt ON m2_event_patient_key (receipt_id);
-- M2-G2: der Aufenthalt. Indizes Patient/Visit/Zeitraum = Stufe-2-Voraussetzung.
CREATE TABLE IF NOT EXISTS stay (
    stay_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_key       TEXT NOT NULL,
    visit_id          TEXT,
    pattern           TEXT NOT NULL,
    status            TEXT NOT NULL,
    opened_receipt    INTEGER NOT NULL,
    opened_arrival_ts TEXT NOT NULL,
    opened_event_ts   TEXT NOT NULL,
    closed_receipt    INTEGER,
    closed_event_ts   TEXT
);
CREATE INDEX IF NOT EXISTS idx_stay_patient ON stay (patient_key);
CREATE INDEX IF NOT EXISTS idx_stay_visit   ON stay (visit_id);
CREATE INDEX IF NOT EXISTS idx_stay_opened  ON stay (opened_event_ts);
-- M2-G3/G4: das Lage-Segment. ROHE PV1-3-Komponenten am Segment; end_ts NULL =
-- offen (M2-G6). Provenienz an BEIDEN Grenzen (M2-G7).
CREATE TABLE IF NOT EXISTS segment (
    segment_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    stay_id          INTEGER NOT NULL,
    seq              INTEGER NOT NULL,
    pv1_3_raw        TEXT,
    ward             TEXT, room TEXT, bed TEXT,
    start_ts         TEXT NOT NULL,
    start_provenance TEXT NOT NULL,
    start_receipt    INTEGER NOT NULL,
    end_ts           TEXT,
    end_provenance   TEXT,
    end_receipt      INTEGER,
    overdue_flagged  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segment_stay  ON segment (stay_id, seq);
CREATE INDEX IF NOT EXISTS idx_segment_start ON segment (start_ts);
CREATE INDEX IF NOT EXISTS idx_segment_end   ON segment (end_ts);
CREATE INDEX IF NOT EXISTS idx_segment_ward  ON segment (ward);
-- M2-G5: Verspaetungs-Protokoll (PID-frei: Receipt/Trigger/Zeiten/Fenster) —
-- Lerngrundlage fuer die Fenstergroessen.
CREATE TABLE IF NOT EXISTS delay_log (
    receipt_id    INTEGER PRIMARY KEY,
    trigger       TEXT NOT NULL,
    event_ts      TEXT,
    arrival_ts    TEXT NOT NULL,
    delay_seconds INTEGER,
    window        TEXT NOT NULL
);
-- M2-G6: Befunde — zuerst durabel ('pending'), dann aktiv gemeldet (M-1-Kanal).
CREATE TABLE IF NOT EXISTS finding (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_id      INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    trigger         TEXT,
    msh3            TEXT, msh4 TEXT, msh10 TEXT,
    reason          TEXT NOT NULL,
    created_ts      TEXT NOT NULL,
    delivery_status TEXT NOT NULL DEFAULT 'pending',
    delivery_info   TEXT,
    delivered_ts    TEXT
);
CREATE INDEX IF NOT EXISTS idx_m2_finding_delivery ON finding (delivery_status);
"""


class M2Store:
    """SQLite-backed M-2-DB. WAL + synchronous=FULL wie M-1: jeder Vermerk,
    jedes Segment und jeder Befund ist pro Commit durabel (fsync)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_M2_SCHEMA)

    # --- Cursor (geerbte Disziplin: NACH dem Vermerk vorgerueckt) ------------

    def get_cursor(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_receipt_id FROM m2_cursor WHERE id=0"
            ).fetchone()
        return row[0] if row else 0

    def set_cursor(self, receipt_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO m2_cursor (id, last_receipt_id) VALUES (0, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_receipt_id=excluded.last_receipt_id",
                (receipt_id,),
            )

    # --- M2-G1: verarbeitet-Vermerk + Event-Identitaet -----------------------

    def processed_outcome(self, receipt_id: int) -> Optional[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT outcome FROM m2_processed WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return row[0] if row else None

    def marker_processed(self, marker) -> bool:
        if not marker_complete(marker):
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM m2_seen_marker WHERE msh3=? AND msh4=? AND msh10=?", marker
            ).fetchone()
        return row is not None

    def ingest_event(
        self,
        ev: M2Event,
        outcome: str,
        *,
        status: Optional[str] = None,
        status_reason: Optional[str] = None,
        finding: Optional[Finding] = None,
        window: str = "jitter",
        record_seen_marker: bool = True,
    ) -> Optional[Finding]:
        """EIN durabler Commit pro Event (M2-G1): Vermerk + Marker + Puffer-
        Zeile + Patient-Keys + Verspaetungs-Protokoll + ggf. Befund 'pending'.
        Melden passiert NACH diesem Return (Speichern-vor-Melden, M-1-Kanal)."""
        ts = _utcnow_iso()
        msh3, msh4, msh10 = ev.marker
        delay_s: Optional[int] = None
        if ev.event_ts:
            delay_s = int((datetime.fromisoformat(ev.arrival_ts)
                           - datetime.fromisoformat(ev.event_ts)).total_seconds())
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT OR IGNORE INTO m2_processed "
                "(receipt_id, msh3, msh4, msh10, outcome, processed_ts) VALUES (?,?,?,?,?,?)",
                (ev.receipt_id, msh3, msh4, msh10, outcome, ts),
            )
            if record_seen_marker and marker_complete(ev.marker):
                cur.execute(
                    "INSERT OR IGNORE INTO m2_seen_marker (msh3, msh4, msh10, receipt_id) "
                    "VALUES (?,?,?,?)",
                    (msh3, msh4, msh10, ev.receipt_id),
                )
            if status is not None:
                cur.execute(
                    "INSERT OR REPLACE INTO m2_event "
                    "(receipt_id, patient_key, visit_id, trigger, patient_class, pv1_3_raw, "
                    " ward, room, bed, event_ts, provenance, provenance_label, arrival_ts, "
                    " status, status_reason, pkey_status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ev.receipt_id, ev.patient_key, ev.visit_id, ev.trigger, ev.patient_class,
                     ev.pv1_3_raw, ev.ward, ev.room, ev.bed, ev.event_ts, ev.provenance,
                     ev.provenance_label, ev.arrival_ts, status, status_reason, ev.pkey_status),
                )
                cur.execute("DELETE FROM m2_event_patient_key WHERE receipt_id=?", (ev.receipt_id,))
                for key in ev.patient_keys:
                    cur.execute(
                        "INSERT INTO m2_event_patient_key (receipt_id, patient_key) VALUES (?,?)",
                        (ev.receipt_id, key),
                    )
                cur.execute(
                    "INSERT OR REPLACE INTO delay_log "
                    "(receipt_id, trigger, event_ts, arrival_ts, delay_seconds, window) "
                    "VALUES (?,?,?,?,?,?)",
                    (ev.receipt_id, ev.trigger, ev.event_ts, ev.arrival_ts, delay_s, window),
                )
            stored = self._insert_finding(cur, finding)
            self._conn.commit()
        return stored

    def _insert_finding(self, cur, finding: Optional[Finding]) -> Optional[Finding]:
        if finding is None:
            return None
        cur.execute(
            "INSERT INTO finding "
            "(receipt_id, kind, trigger, msh3, msh4, msh10, reason, created_ts, delivery_status) "
            "VALUES (?,?,?,?,?,?,?,?, 'pending')",
            (finding.receipt_id, finding.kind, finding.trigger,
             finding.msh3, finding.msh4, finding.msh10, finding.reason, finding.created_ts),
        )
        from dataclasses import replace
        return replace(finding, finding_id=cur.lastrowid)

    # --- Puffer-Sicht ---------------------------------------------------------

    _EV_COLS = ("receipt_id, patient_key, visit_id, trigger, patient_class, pv1_3_raw, "
                "ward, room, bed, event_ts, provenance, provenance_label, arrival_ts")

    def _row_to_event(self, r) -> M2Event:
        return M2Event(
            receipt_id=r[0], patient_key=r[1], patient_keys=[r[1]] if r[1] else [],
            visit_id=r[2], trigger=r[3], patient_class=r[4], pv1_3_raw=r[5],
            ward=r[6], room=r[7], bed=r[8], event_ts=r[9], provenance=r[10],
            provenance_label=r[11], arrival_ts=r[12],
            marker=(None, None, None), pkey_status=PKEY_KEYED,
        )

    def ripe_pending_events(self, arrival_cutoff_iso: str) -> List[M2Event]:
        """M2-G5: alle pending Events, deren Ankunft das Jitter-Fenster hinter
        sich hat — ZEIT-SORTIERT (Event-Zeit, dann Receipt) fuer den Apply."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._EV_COLS} FROM m2_event "
                "WHERE status=? AND arrival_ts<=? ORDER BY event_ts, receipt_id",
                (EV_PENDING, arrival_cutoff_iso),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def event_status(self, receipt_id: int) -> Optional[Tuple[str, Optional[str]]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT status, status_reason FROM m2_event WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return (row[0], row[1]) if row else None

    # --- Apply-Transaktionen (eine pro Event — Crash dazwischen laesst das
    # Event 'pending' und damit wiederanwendbar; angewandt = festgeschrieben) --

    def _mark_applied(self, cur, receipt_id: int, reason: Optional[str] = None,
                      status: str = EV_APPLIED) -> None:
        cur.execute(
            "UPDATE m2_event SET status=?, status_reason=? WHERE receipt_id=?",
            (status, reason, receipt_id),
        )

    def open_stay_with_segment(self, ev: M2Event, pattern: str) -> int:
        """A01 (Muster A) / A04 (vorlaeufige Episode): neuer stay + Segment 1."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "INSERT INTO stay (patient_key, visit_id, pattern, status, opened_receipt, "
                "opened_arrival_ts, opened_event_ts) VALUES (?,?,?,?,?,?,?)",
                (ev.patient_key, ev.visit_id, pattern, "open", ev.receipt_id,
                 ev.arrival_ts, ev.event_ts),
            )
            stay_id = cur.lastrowid
            cur.execute(
                "INSERT INTO segment (stay_id, seq, pv1_3_raw, ward, room, bed, "
                "start_ts, start_provenance, start_receipt) VALUES (?,?,?,?,?,?,?,?,?)",
                (stay_id, 1, ev.pv1_3_raw, ev.ward, ev.room, ev.bed,
                 ev.event_ts, ev.provenance, ev.receipt_id),
            )
            self._mark_applied(cur, ev.receipt_id)
            self._conn.commit()
        return stay_id

    def advance_segment(self, stay_id: int, ev: M2Event, *, set_pattern: Optional[str] = None) -> int:
        """M2-G3 Event-Invariante: schliesst das offene Segment an ev.event_ts
        (Provenienz an der Grenze) und oeffnet das naechste an ev's Lage. KEIN
        Rewrite — die bestehende Segment-Zeile bekommt nur ihr Ende gesetzt."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            row = cur.execute(
                "SELECT segment_id, seq FROM segment WHERE stay_id=? AND end_ts IS NULL "
                "ORDER BY seq DESC LIMIT 1", (stay_id,),
            ).fetchone()
            seq = 0
            if row:
                cur.execute(
                    "UPDATE segment SET end_ts=?, end_provenance=?, end_receipt=? "
                    "WHERE segment_id=?",
                    (ev.event_ts, ev.provenance, ev.receipt_id, row[0]),
                )
                seq = row[1]
            cur.execute(
                "INSERT INTO segment (stay_id, seq, pv1_3_raw, ward, room, bed, "
                "start_ts, start_provenance, start_receipt) VALUES (?,?,?,?,?,?,?,?,?)",
                (stay_id, seq + 1, ev.pv1_3_raw, ev.ward, ev.room, ev.bed,
                 ev.event_ts, ev.provenance, ev.receipt_id),
            )
            if set_pattern:
                cur.execute("UPDATE stay SET pattern=? WHERE stay_id=?", (set_pattern, stay_id))
            if ev.visit_id:
                cur.execute(
                    "UPDATE stay SET visit_id=? WHERE stay_id=? AND visit_id IS NULL",
                    (ev.visit_id, stay_id),
                )
            self._mark_applied(cur, ev.receipt_id)
            self._conn.commit()
        return stay_id

    def close_stay(self, stay_id: int, ev: M2Event, *, set_pattern: Optional[str] = None) -> None:
        """A03: schliesst das offene Segment UND den stay. A03 oeffnet NICHTS
        (Entlassung ist Ende, kein Lagewechsel — Orts-Plausibilitaet ist Stufe 3)."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            row = cur.execute(
                "SELECT segment_id FROM segment WHERE stay_id=? AND end_ts IS NULL "
                "ORDER BY seq DESC LIMIT 1", (stay_id,),
            ).fetchone()
            if row:
                cur.execute(
                    "UPDATE segment SET end_ts=?, end_provenance=?, end_receipt=? "
                    "WHERE segment_id=?",
                    (ev.event_ts, ev.provenance, ev.receipt_id, row[0]),
                )
            cur.execute(
                "UPDATE stay SET status='closed', closed_receipt=?, closed_event_ts=? "
                "WHERE stay_id=?",
                (ev.receipt_id, ev.event_ts, stay_id),
            )
            if set_pattern:
                cur.execute("UPDATE stay SET pattern=? WHERE stay_id=?", (set_pattern, stay_id))
            if ev.visit_id:
                cur.execute(
                    "UPDATE stay SET visit_id=? WHERE stay_id=? AND visit_id IS NULL",
                    (ev.visit_id, stay_id),
                )
            self._mark_applied(cur, ev.receipt_id)
            self._conn.commit()

    def mark_event(self, receipt_id: int, status: str, reason: str,
                   finding: Optional[Finding] = None) -> Optional[Finding]:
        """Stufe-2-Grenze (deferred/out-of-order): durabel + sichtbar, kein Segment."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            self._mark_applied(cur, receipt_id, reason, status=status)
            stored = self._insert_finding(cur, finding)
            self._conn.commit()
        return stored

    # --- M2-G2: stay-Suche fuer die Zustandsmaschine --------------------------

    def _stay_rows(self, where: str, params: tuple) -> List[StayRow]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT stay_id, patient_key, visit_id, pattern, status, opened_receipt, "
                "opened_arrival_ts, opened_event_ts, closed_receipt, closed_event_ts "
                f"FROM stay WHERE {where}", params,
            ).fetchall()
        return [StayRow(*r) for r in rows]

    def open_stays(self, patient_key: str) -> List[StayRow]:
        """Offene stays des Patienten, juengster zuerst."""
        return self._stay_rows(
            "patient_key=? AND status='open' ORDER BY opened_event_ts DESC, stay_id DESC",
            (patient_key,),
        )

    def get_stay(self, stay_id: int) -> Optional[StayRow]:
        rows = self._stay_rows("stay_id=?", (stay_id,))
        return rows[0] if rows else None

    def stays_for_patient(self, patient_key: str) -> List[StayRow]:
        return self._stay_rows("patient_key=? ORDER BY opened_event_ts, stay_id", (patient_key,))

    def stays_for_visit(self, visit_id: str) -> List[StayRow]:
        return self._stay_rows("visit_id=? ORDER BY opened_event_ts, stay_id", (visit_id,))

    # --- M2-G5: Muster-Festschreibung nach Join-Fensterablauf ------------------

    def finalize_pending_to_c(self, arrival_cutoff_iso: str) -> List[int]:
        """A04-Episoden, deren Join-Fenster (Ankunfts-Wanduhr) abgelaufen ist,
        ohne dass ein A01 gebunden hat -> Muster C, durabel festgeschrieben."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            ids = [r[0] for r in cur.execute(
                "SELECT stay_id FROM stay WHERE pattern=? AND opened_arrival_ts<=?",
                (PATTERN_PENDING, arrival_cutoff_iso),
            ).fetchall()]
            if ids:
                qmarks = ",".join("?" * len(ids))
                cur.execute(
                    f"UPDATE stay SET pattern=? WHERE stay_id IN ({qmarks})",
                    (PATTERN_C, *ids),
                )
            self._conn.commit()
        return ids

    # --- Segmente / Abfragen (durchsuchbar; Stufe-2-Voraussetzung) -------------

    _SEG_COLS = ("segment_id, stay_id, seq, pv1_3_raw, ward, room, bed, start_ts, "
                 "start_provenance, start_receipt, end_ts, end_provenance, end_receipt")

    def _segment_rows(self, where: str, params: tuple) -> List[SegmentRow]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {self._SEG_COLS} FROM segment WHERE {where}", params,
            ).fetchall()
        return [SegmentRow(*r) for r in rows]

    def segments_of(self, stay_id: int) -> List[SegmentRow]:
        return self._segment_rows("stay_id=? ORDER BY seq", (stay_id,))

    def get_segment(self, segment_id: int) -> Optional[SegmentRow]:
        rows = self._segment_rows("segment_id=?", (segment_id,))
        return rows[0] if rows else None

    def segments_in_range(self, t_from_iso: str, t_to_iso: str) -> List[SegmentRow]:
        """Zeitraum-Suche (halb-offen): Segmente, die [from, to) schneiden;
        offene Segmente (end NULL) gelten als andauernd."""
        return self._segment_rows(
            "start_ts < ? AND (end_ts IS NULL OR end_ts > ?) ORDER BY start_ts, segment_id",
            (t_to_iso, t_from_iso),
        )

    def find_contacts(self, segment_id: int, granularity: str = GRAN_WARD) -> List[SegmentRow]:
        """
        M2-G4 UEBER-KONTAKTIERUNGS-SPERRE: Kontakt-Kandidaten = Segmente ANDERER
        Patienten in derselben Kontakt-Einheit (zur Compute-Zeit kollabiert)
        mit ZEITLICHER UEBERLAPPUNG — halb-offen, beruehren != ueberlappen.
        Offene Segmente gelten als andauernd (unbeschraenkt); welcher
        Bezugszeitpunkt fuer Delta_con gilt, ist AION-seitig (M-4), nicht hier.
        """
        me = self.get_segment(segment_id)
        if me is None:
            return []
        my_stay = self.get_stay(me.stay_id)
        my_unit = me.unit(granularity)
        candidates = self._segment_rows("ward=? AND segment_id != ?", (me.ward, segment_id))
        out: List[SegmentRow] = []
        for seg in candidates:
            other_stay = self.get_stay(seg.stay_id)
            if other_stay is None or other_stay.patient_key == my_stay.patient_key:
                continue
            if seg.unit(granularity) != my_unit:
                continue
            # zeitliche Ueberlappung [start, end): offen (NULL) = unbeschraenkt
            a_end = me.end_ts
            b_end = seg.end_ts
            if (a_end is None or seg.start_ts < a_end) and (b_end is None or me.start_ts < b_end):
                out.append(seg)
        return out

    # --- M2-G6: Offen-Dauer-Ueberwachung ---------------------------------------

    def flag_overdue_open_segments(
        self, now_iso: str,
        *,
        threshold_for: Callable[[SegmentRow, str], int],
        build_finding: Callable[[SegmentRow, str, Tuple[Optional[str], Optional[str], Optional[str]]], Finding],
    ) -> List[Finding]:
        """Offene Segmente aelter als IHRE (klassen-differenzierte) Schwelle ->
        Befund (durabel 'pending'), genau EINMAL pro Segment (overdue_flagged).
        Melden macht der Aufrufer. `threshold_for(seg, stay_pattern)` liefert
        die Schwelle in Sekunden; der Marker des Eroeffnungs-Events wird HIER
        (selbe Transaktion/Lock) nachgeschlagen — die Callbacks duerfen keine
        Store-Methode rufen (nicht-reentranter Lock), sie muessen pur sein."""
        stored: List[Finding] = []
        now_dt = datetime.fromisoformat(now_iso)
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("BEGIN")
            rows = cur.execute(
                f"SELECT {', '.join('s.' + c.strip() for c in self._SEG_COLS.split(','))}, "
                "st.pattern FROM segment s JOIN stay st ON st.stay_id = s.stay_id "
                "WHERE s.end_ts IS NULL AND s.overdue_flagged=0 ORDER BY s.segment_id",
            ).fetchall()
            for r in rows:
                seg, pattern = SegmentRow(*r[:-1]), r[-1]
                threshold_s = threshold_for(seg, pattern)
                age_s = (now_dt - datetime.fromisoformat(seg.start_ts)).total_seconds()
                if age_s <= threshold_s:
                    continue
                mrow = cur.execute(
                    "SELECT msh3, msh4, msh10 FROM m2_processed WHERE receipt_id=?",
                    (seg.start_receipt,),
                ).fetchone()
                marker = (mrow[0], mrow[1], mrow[2]) if mrow else (None, None, None)
                f = self._insert_finding(cur, build_finding(seg, pattern, marker))
                cur.execute(
                    "UPDATE segment SET overdue_flagged=1 WHERE segment_id=?",
                    (seg.segment_id,),
                )
                stored.append(f)
            self._conn.commit()
        return stored

    def marker_of_receipt(self, receipt_id: int) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT msh3, msh4, msh10 FROM m2_processed WHERE receipt_id=?", (receipt_id,)
            ).fetchone()
        return (row[0], row[1], row[2]) if row else (None, None, None)

    # --- Befund-Zustellung (M-1-Disziplin: Speichern vor Melden) ----------------

    def set_finding_delivery(self, finding_id: int, ok: bool, info: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE finding SET delivery_status=?, delivery_info=?, delivered_ts=? "
                "WHERE finding_id=?",
                ("delivered" if ok else "failed", info, _utcnow_iso() if ok else None, finding_id),
            )

    def pending_findings(self) -> List[Finding]:
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

    # --- M2-G8: Erasure (SILD-Lesart-A-Semantik wiederverwendet) ----------------

    def erase_patient(self, patient_key: str, *, commit: bool = False) -> EraseResult:
        """
        Loescht ALLE Zeilen, die `patient_key` tragen: stays + deren Segmente +
        Event-Pufferzeilen. delay_log / m2_processed / finding sind PID-frei
        (Receipt/Marker/Zaehler) und bleiben als inhaltsfreies Audit erhalten —
        exakt die M-1/SILD-Aufteilung. Fail-closed: Event-Zeilen mit
        pkey_status='unresolved' (PID-3 vorhanden, unlesbar) zaehlen als
        Restrisiko -> incomplete_uncertain. dry-run per Default.
        """
        with self._lock:
            event_ids = [r[0] for r in self._conn.execute(
                "SELECT DISTINCT receipt_id FROM m2_event_patient_key WHERE patient_key=? "
                "ORDER BY receipt_id", (patient_key,),
            ).fetchall()]
            stay_ids = [r[0] for r in self._conn.execute(
                "SELECT stay_id FROM stay WHERE patient_key=? ORDER BY stay_id", (patient_key,),
            ).fetchall()]
            seg_count = 0
            if stay_ids:
                qmarks = ",".join("?" * len(stay_ids))
                seg_count = self._conn.execute(
                    f"SELECT COUNT(*) FROM segment WHERE stay_id IN ({qmarks})", stay_ids
                ).fetchone()[0]
            unresolvable = self._conn.execute(
                "SELECT COUNT(*) FROM m2_event WHERE pkey_status=?", (PKEY_UNRESOLVED,)
            ).fetchone()[0]
            deleted = len(event_ids) + len(stay_ids) + seg_count

            if commit and (event_ids or stay_ids):
                cur = self._conn.cursor()
                cur.execute("BEGIN")
                if event_ids:
                    qm = ",".join("?" * len(event_ids))
                    cur.execute(f"DELETE FROM m2_event_patient_key WHERE receipt_id IN ({qm})", event_ids)
                    cur.execute(f"DELETE FROM m2_event WHERE receipt_id IN ({qm})", event_ids)
                if stay_ids:
                    qm = ",".join("?" * len(stay_ids))
                    cur.execute(f"DELETE FROM segment WHERE stay_id IN ({qm})", stay_ids)
                    cur.execute(f"DELETE FROM stay WHERE stay_id IN ({qm})", stay_ids)
                self._conn.commit()

        status = "incomplete_uncertain" if unresolvable > 0 else "complete"
        return EraseResult(
            patient_key=patient_key, deleted=deleted,
            unresolvable=unresolvable, status=status, dry_run=not commit,
        )

    # --- Uebergabe an AION (M-4): Lese-Schnittstelle, kein aktiver Push ---------

    def export_for_aion(self) -> List[dict]:
        """Festgeschriebener Stand als Uebergabe-Sicht: stays mit Segmenten,
        rohen PV1-3-Komponenten (Ableitungsschluessel) und Grenz-Provenienz.
        Kollaps zur Kontakt-Einheit + Verschmelzung + Delta_con-Bezugszeitpunkt
        sind AUSDRUECKLICH Compute-Seite (AION/M-4)."""
        out = []
        with self._lock:
            stays = self._conn.execute(
                "SELECT stay_id, patient_key, visit_id, pattern, status FROM stay ORDER BY stay_id"
            ).fetchall()
        for sid, pkey, visit, pattern, status in stays:
            segs = self.segments_of(sid)
            out.append({
                "stay_id": sid, "patient_key": pkey, "visit_id": visit,
                "pattern": pattern, "status": status,
                "segments": [{
                    "seq": s.seq, "pv1_3_raw": s.pv1_3_raw,
                    "ward": s.ward, "room": s.room, "bed": s.bed,
                    "start_ts": s.start_ts, "start_provenance": s.start_provenance,
                    "end_ts": s.end_ts, "end_provenance": s.end_provenance,
                } for s in segs],
            })
        return out

    def counts(self) -> dict:
        with self._lock:
            c = {}
            for name, table in (("processed", "m2_processed"), ("events", "m2_event"),
                                ("stays", "stay"), ("segments", "segment"),
                                ("findings", "finding"), ("delays", "delay_log")):
                c[name] = self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return c

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ===========================================================================
# Reader: M-1s Output NUR LESEND (disposition usable + intake-Rohbytes)
# ===========================================================================

class M1OutputReader:
    """Read-only Sicht auf M-1s disposition-Tabelle (kind='usable') + SILDs
    intake-Tabelle fuer die Rohbytes. Beide mode=ro + PRAGMA query_only:
    M-2 kann weder M-1s DB noch SILDs Store beschreiben."""

    def __init__(self, m1_db_path, intake_db_path):
        self._m1 = sqlite3.connect(f"file:{Path(m1_db_path)}?mode=ro", uri=True,
                                   check_same_thread=False)
        self._m1.execute("PRAGMA query_only=ON")
        self._intake = sqlite3.connect(f"file:{Path(intake_db_path)}?mode=ro", uri=True,
                                       check_same_thread=False)
        self._intake.execute("PRAGMA query_only=ON")

    def scan_after(self, cursor: int) -> List[Tuple[int, Optional[bytes], str, Optional[str]]]:
        rows = self._m1.execute(
            "SELECT receipt_id, trigger, time_provenance FROM disposition "
            "WHERE kind=? AND receipt_id > ? ORDER BY receipt_id",
            (USABLE, cursor),
        ).fetchall()
        out: List[Tuple[int, Optional[bytes], str, Optional[str]]] = []
        for rid, trig, prov in rows:
            raw_row = self._intake.execute(
                "SELECT raw FROM intake WHERE receipt_id=?", (rid,)
            ).fetchone()
            # raw kann fehlen (z.B. SILD-Erasure nach M-1-Sichtung) — das wird
            # vermerkt (missing_raw), nie still uebersprungen.
            out.append((rid, bytes(raw_row[0]) if raw_row else None, trig, prov))
        return out

    def close(self) -> None:
        self._m1.close()
        self._intake.close()


# ===========================================================================
# MapperM2: Orchestrierung (Ingest -> Jitter-Apply -> Join-Finalize -> Monitor)
# ===========================================================================

class MapperM2:
    """
    Der Poll-Zyklus haelt NIE an (M2-G5):
      1. Ingest: neue usable Events aus M-1, Vermerk-vor-Cursor (M2-G1).
      2. Apply:  reife Events (Jitter-Fenster), zeit-sortiert, je Event eine
                 durable Transaktion (Zustandsmaschine A/B/C, Event-Invariante).
      3. Finalize: A04-Episoden mit abgelaufenem Join-Fenster -> Muster C.
      4. Monitor: offene Segmente ueber der Schwelle -> Befund (durabel->aktiv).
    `reader=None` erlaubt Direkt-Einspeisung (Tests/Embedding) via ingest_usable.
    """

    def __init__(
        self,
        reader: Optional[M1OutputReader],
        store: M2Store,
        notifier,
        *,
        windows: Optional[WindowConfig] = None,
        time_fields: Optional[TimeFieldConfig] = None,
        visit_fields: Optional[VisitFieldConfig] = None,
        patient_key_config: Optional[PatientKeyConfig] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.reader      = reader
        self.store       = store
        self.notifier    = notifier
        self.windows     = windows or WindowConfig()
        self.time_fields = time_fields or TimeFieldConfig()
        self.visit_fields = visit_fields or VisitFieldConfig()
        self.patient_key_config = patient_key_config or PatientKeyConfig()
        self.now_fn      = now_fn or (lambda: datetime.now(timezone.utc))

    # --- Stage 1: Ingest (M2-G1) ----------------------------------------------

    def ingest_usable(
        self,
        receipt_id: int,
        raw: Optional[bytes],
        trigger: str,
        m1_provenance: Optional[str] = None,
        *,
        now: Optional[datetime] = None,
        _crash: Optional[str] = None,
    ) -> str:
        """Nimmt EIN usable-Event aus M-1 entgegen, durabel und idempotent.
        `m1_provenance` (Label aus M-1s Vermerk) ist bestaetigend; massgeblich
        ist die Neu-Aufloesung ueber dieselbe TimeFieldConfig."""
        existing = self.store.processed_outcome(receipt_id)
        if existing is not None:
            return existing                       # M2-G1: Receipt schon verarbeitet

        now = now or self.now_fn()
        arrival = now.isoformat()

        if raw is None:
            ev = M2Event(receipt_id=receipt_id, trigger=trigger, marker=(None, None, None),
                         patient_key=None, patient_keys=[], pkey_status=PKEY_PATIENTLESS,
                         visit_id=None, patient_class=None, pv1_3_raw="", ward="", room="",
                         bed="", event_ts=None, provenance=None, provenance_label=None,
                         arrival_ts=arrival)
            self.store.ingest_event(ev, OUT_MISSING_RAW, record_seen_marker=False)
            return OUT_MISSING_RAW

        ev = parse_usable_event(
            receipt_id, raw, trigger,
            time_fields=self.time_fields,
            patient_key_config=self.patient_key_config,
            visit_fields=self.visit_fields,
        )
        ev.arrival_ts = arrival

        # M2-G1: Event-Identitaet (vollstaendiger Marker) schon verarbeitet ->
        # KEIN Doppel-Segment. Unvollstaendiger Marker wird NIE unterdrueckt.
        if marker_complete(ev.marker) and self.store.marker_processed(ev.marker):
            if _crash == "before_persist":
                raise SimulatedCrash("crash before the durable Vermerk (M2-G1)")
            self.store.ingest_event(ev, OUT_SUPPRESSED, record_seen_marker=False)
            return OUT_SUPPRESSED

        if _crash == "before_persist":
            raise SimulatedCrash("crash before the durable Vermerk (M2-G1)")

        window = "join" if ev.trigger in ("A04", "A01") else "jitter"

        # Stufe-2-Trigger: durabel abgelegt, NICHT angewandt (kein Rewrite hier).
        if ev.trigger in STUFE2_TRIGGERS:
            self.store.ingest_event(
                ev, OUT_DEFERRED, status=EV_DEFERRED, window=window,
                status_reason=f"ADT^{ev.trigger} rueckwirkend intervall-veraendernd — Stufe 2",
            )
            return OUT_DEFERRED

        # Nicht sequenzierbar (kein Patient-Schluessel / keine Bewegungszeit) ->
        # Befund, nie still verworfen. (Zeit sollte fuer M-1-usable immer da
        # sein — defensiv gegen Direkt-Einspeisung/Konfig-Drift.)
        if ev.patient_key is None or ev.event_ts is None:
            missing = "Patienten-Schluessel" if ev.patient_key is None else "Bewegungszeit"
            finding = Finding(
                receipt_id=receipt_id, kind=FINDING_UNASSIGNED, trigger=ev.trigger,
                msh3=ev.marker[0], msh4=ev.marker[1], msh10=ev.marker[2],
                reason=f"usable Event nicht sequenzierbar: {missing} fehlt",
                created_ts=_utcnow_iso(),
            )
            stored = self.store.ingest_event(
                ev, OUT_UNASSIGNED, status=EV_UNASSIGNED, window=window,
                status_reason=f"{missing} fehlt", finding=finding,
            )
            self._notify(stored)
            return OUT_UNASSIGNED

        self.store.ingest_event(ev, OUT_BUFFERED, status=EV_PENDING, window=window)
        return OUT_BUFFERED

    # --- Stage 2: Apply (Jitter-Fenster, zeit-sortiert) -------------------------

    def apply_ripe(self, now: Optional[datetime] = None) -> int:
        now = now or self.now_fn()
        cutoff = (now - _td(self.windows.jitter_window_s)).isoformat()
        applied = 0
        for ev in self.store.ripe_pending_events(cutoff):
            self._apply_event(ev)
            applied += 1
        return applied

    def _apply_event(self, ev: M2Event) -> None:
        """Die Stufe-1-Zustandsmaschine — eine durable Transaktion pro Event."""
        if ev.trigger == "A04":
            # Eintritt der ambulanten/Notaufnahme-Phase: VORLAEUFIGE Episode.
            self.store.open_stay_with_segment(ev, PATTERN_PENDING)
            return

        if ev.trigger == "A01":
            bind = self._pending_stay_in_join_window(ev)
            if bind is not None:
                # Muster B: EIN stay; der A01 schliesst das NA/AMB-Segment
                # vorwaerts und oeffnet Segment 2 (Event-Invariante, KEIN Rewrite).
                self.store.advance_segment(bind.stay_id, ev, set_pattern=PATTERN_B)
            else:
                # Muster A: direkt stationaer. Ein A01 JENSEITS des Join-
                # Fensters bindet bewusst NICHT (Stufe 2) -> neuer stay.
                self.store.open_stay_with_segment(ev, PATTERN_A)
            return

        if ev.trigger == "A02":
            stay = self._best_open_stay(ev)
            if stay is None:
                self._defer_out_of_order(ev, "A02 ohne offenen Aufenthalt (Out-of-Order/Stufe 2)")
                return
            # M2-G3: A02 erzeugt IMMER ein Segment — auch Quelle=Ziel (Gap 2:
            # verschmolzen wird, wenn ueberhaupt, AION-seitig).
            self.store.advance_segment(stay.stay_id, ev)
            return

        if ev.trigger == "A03":
            stay = self._best_open_stay(ev)
            if stay is None:
                self._defer_out_of_order(ev, "A03 ohne offenen Aufenthalt (Out-of-Order/Stufe 2)")
                return
            # A03 auf einer noch-pending Episode beweist den ambulanten
            # Abschluss -> Muster C (frueher als der Fensterablauf).
            set_pattern = PATTERN_C if stay.pattern == PATTERN_PENDING else None
            self.store.close_stay(stay.stay_id, ev, set_pattern=set_pattern)
            return

        # Defensiv: unbekannter Bewegungs-Trigger landet nie hier (Ingest
        # verzweigt vorher) — laut statt still.
        self._defer_out_of_order(ev, f"Trigger {ev.trigger} in Stufe 1 nicht anwendbar")

    def _pending_stay_in_join_window(self, ev: M2Event) -> Optional[StayRow]:
        """Juengste offene A04-Episode des Patienten, deren Ankunfts-Abstand zum
        A01 im Join-Fenster liegt. Visit ist nur BESTAETIGEND (Briefing §6):
        traegt die Episode bereits eine ANDERE Visit, bindet sie nicht."""
        a01_arrival = datetime.fromisoformat(ev.arrival_ts)
        for stay in self.store.open_stays(ev.patient_key):
            if stay.pattern != PATTERN_PENDING:
                continue
            age = (a01_arrival - datetime.fromisoformat(stay.opened_arrival_ts)).total_seconds()
            if age > self.windows.join_window_s:
                continue
            if stay.visit_id and ev.visit_id and stay.visit_id != ev.visit_id:
                continue
            return stay
        return None

    def _best_open_stay(self, ev: M2Event) -> Optional[StayRow]:
        """A02/A03-Ziel: offener stay des Patienten — Visit-Match bevorzugt,
        sonst der juengste offene."""
        stays = self.store.open_stays(ev.patient_key)
        if not stays:
            return None
        if ev.visit_id:
            for s in stays:
                if s.visit_id == ev.visit_id:
                    return s
        return stays[0]

    def _defer_out_of_order(self, ev: M2Event, reason: str) -> None:
        finding = Finding(
            receipt_id=ev.receipt_id, kind=FINDING_OUT_OF_ORDER, trigger=ev.trigger,
            msh3=None, msh4=None, msh10=None, reason=reason, created_ts=_utcnow_iso(),
        )
        # Marker fuer den PID-freien Befund aus dem Vermerk nachladen.
        finding.msh3, finding.msh4, finding.msh10 = self.store.marker_of_receipt(ev.receipt_id)
        stored = self.store.mark_event(ev.receipt_id, EV_DEFERRED, reason, finding=finding)
        self._notify(stored)

    # --- Stage 3: Join-Fenster-Festschreibung -----------------------------------

    def finalize_patterns(self, now: Optional[datetime] = None) -> List[int]:
        now = now or self.now_fn()
        cutoff = (now - _td(self.windows.join_window_s)).isoformat()
        return self.store.finalize_pending_to_c(cutoff)

    # --- Stage 4: Offen-Dauer-Ueberwachung (M2-G6) -------------------------------

    def check_open_durations(self, now: Optional[datetime] = None) -> int:
        now = now or self.now_fn()
        thresholds = self.windows.open_overdue

        def _threshold(seg: SegmentRow, stay_pattern: str) -> int:
            return thresholds.classify(stay_pattern, seg.ward)[1]

        def _build(seg: SegmentRow, stay_pattern: str, marker) -> Finding:
            label, threshold_s = thresholds.classify(stay_pattern, seg.ward)
            fmt = (f"{threshold_s // 86400}d" if threshold_s % 86400 == 0
                   else f"{threshold_s // 3600}h")
            msh3, msh4, msh10 = marker
            return Finding(
                receipt_id=seg.start_receipt, kind=FINDING_OPEN_OVERDUE, trigger=None,
                msh3=msh3, msh4=msh4, msh10=msh10,
                reason=(f"Lage-Segment {seg.segment_id} (stay {seg.stay_id}, Klasse "
                        f"{label}) offen seit {seg.start_ts} > Schwelle {fmt} — "
                        f"vermutlich fehlende A03/Folgebewegung"),
                created_ts=_utcnow_iso(),
            )

        stored = self.store.flag_overdue_open_segments(
            now.isoformat(), threshold_for=_threshold, build_finding=_build)
        for f in stored:
            self._notify(f)
        return len(stored)

    # --- Melden (M-1-Disziplin: erst durabel, dann aktiv) ------------------------

    def _notify(self, finding: Optional[Finding]) -> None:
        if finding is None:
            return
        subject, body = build_notification(finding)
        ok, info = self.notifier.send(subject, body)
        self.store.set_finding_delivery(finding.finding_id, ok, info)

    def redeliver_pending(self) -> int:
        n = 0
        for finding in self.store.pending_findings():
            self._notify(finding)
            n += 1
        return n

    # --- Poll-Zyklus -------------------------------------------------------------

    def poll_once(self, *, _crash_before_cursor_at: Optional[int] = None) -> dict:
        now = self.now_fn()
        ingested = 0
        if self.reader is not None:
            cursor = self.store.get_cursor()
            for receipt_id, raw, trigger, prov in self.reader.scan_after(cursor):
                self.ingest_usable(receipt_id, raw, trigger, prov, now=now)
                ingested += 1
                if _crash_before_cursor_at == receipt_id:
                    raise SimulatedCrash(
                        "crash after the Vermerk, before the cursor advance (M2-G1)")
                self.store.set_cursor(receipt_id)
        applied   = self.apply_ripe(now)
        finalized = self.finalize_patterns(now)
        overdue   = self.check_open_durations(now)
        return {"ingested": ingested, "applied": applied,
                "finalized_c": len(finalized), "overdue_findings": overdue}


def _td(seconds: int) -> timedelta:
    return timedelta(seconds=seconds)


# ===========================================================================
# CLI / Betrieb (Spiegel von M-1; erase-Subkommando SILD-SF-1-analog)
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
        prog="sild_mapper_m2",
        description="SILD M-2 ADT-Mapper Stufe 1: rekonstruiert stay + "
                    "stay_unit_segment vorwaerts aus M-1s usable-Output "
                    "(read-only), mit Jitter-/Join-Fenster, offenen Segmenten "
                    "und Offen-Dauer-Befunden (PID-frei).",
    )
    p.add_argument("--m1-db",     required=True, help="Pfad zu M-1s Mapper-DB (nur lesend)")
    p.add_argument("--intake-db", required=True, help="Pfad zu SILDs intake-DB (nur lesend)")
    p.add_argument("--m2-db",     required=True, help="Pfad zur eigenen M-2-DB (gemountetes Volume)")
    p.add_argument("--poll-interval", type=float, default=5.0)
    p.add_argument("--once", action="store_true", help="genau ein Poll-Zyklus, dann beenden")
    p.add_argument("--jitter-window", type=int, default=WindowConfig.jitter_window_s,
                   help="Jitter-Fenster in Sekunden (Ankunfts-Wanduhr)")
    p.add_argument("--join-window", type=int, default=WindowConfig.join_window_s,
                   help="Notaufnahme-Join-Fenster A04->A01 in Sekunden")
    p.add_argument("--open-overdue", type=int, default=OpenOverdueThresholds.stationary_s,
                   help="Offen-Dauer-Schwelle STATIONAER in Sekunden (Fallback-Klasse)")
    p.add_argument("--open-overdue-icu", type=int, default=OpenOverdueThresholds.icu_s,
                   help="Offen-Dauer-Schwelle INTENSIV in Sekunden (deutlich hoeher legitim)")
    p.add_argument("--open-overdue-ambulant", type=int, default=OpenOverdueThresholds.ambulatory_s,
                   help="Offen-Dauer-Schwelle AMBULANT in Sekunden (kurz)")
    p.add_argument("--icu-wards", default=",".join(OpenOverdueThresholds.icu_ward_prefixes),
                   help="Komma-Liste der Intensiv-Ward-Praefixe (STANDORTSPEZIFISCH, "
                        "an echten Daten zu verifizieren)")
    p.add_argument("--smtp-host", default="", help="SMTP-Server (leer -> laute Warnung, nur lokal)")
    p.add_argument("--smtp-port", type=int, default=25)
    p.add_argument("--smtp-from", default="")
    p.add_argument("--smtp-to",   default="")
    p.add_argument("--smtp-tls",  action="store_true")
    args = p.parse_args(argv)

    thresholds = OpenOverdueThresholds(
        stationary_s=args.open_overdue,
        icu_s=args.open_overdue_icu,
        ambulatory_s=args.open_overdue_ambulant,
        icu_ward_prefixes=tuple(p.strip() for p in args.icu_wards.split(",") if p.strip()),
    )
    windows  = WindowConfig(jitter_window_s=args.jitter_window,
                            join_window_s=args.join_window,
                            open_overdue=thresholds)
    notifier = build_notifier(_build_smtp_config(args))
    reader   = M1OutputReader(args.m1_db, args.intake_db)
    store    = M2Store(args.m2_db)
    mapper   = MapperM2(reader, store, notifier, windows=windows)

    def _poll():
        summary = mapper.poll_once()
        if any(summary.values()):
            print(f"[sild-m2] poll: {summary}")
        return summary

    if args.once:
        _poll()
        store.close(); reader.close()
        return 0
    print(f"[sild-m2] Mapper laeuft. m1-db={args.m1_db} (ro) intake-db={args.intake_db} (ro) "
          f"m2-db={args.m2_db} jitter={windows.jitter_window_s}s join={windows.join_window_s}s")
    try:
        while True:
            _poll()
            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        print("[sild-m2] beendet.")
    finally:
        store.close(); reader.close()
    return 0


def _erase_cli(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="sild_mapper_m2 erase",
        description="Loescht stays/Segmente/Event-Puffer EINES Patienten aus der "
                    "M-2-DB (SILD-SF-1-analog). dry-run per Default; --commit zum Loeschen.",
    )
    p.add_argument("--m2-db", required=True)
    p.add_argument("--patient-key", required=True, help="Format 'Authority|ID'")
    p.add_argument("--commit", action="store_true")
    p.add_argument("--erase-log", default=None,
                   help="inhaltsfreie Loesch-Audit-Zeile (JSONL) hier anhaengen")
    args = p.parse_args(argv)

    store  = M2Store(args.m2_db)
    result = store.erase_patient(args.patient_key, commit=args.commit)
    record = build_erase_audit_record(result)
    store.close()

    if args.erase_log:
        import json
        with open(args.erase_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    mode = "DRY-RUN (nichts geloescht)" if result.dry_run else "COMMITTED"
    print(f"[sild-m2-erase] {mode} key={result.patient_key} "
          f"deleted={result.deleted} unresolvable={result.unresolvable} status={result.status}")
    if result.status == "incomplete_uncertain":
        sys.stderr.write(
            f"[sild-m2-erase] WARNUNG: {result.unresolvable} Event-Zeile(n) mit vorhandenem "
            f"aber unlesbarem PID-3 — Loeschung von {result.patient_key} kann NICHT als "
            f"vollstaendig zertifiziert werden (fail-closed). Manuell pruefen.\n"
        )
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "erase":
        sys.exit(_erase_cli(sys.argv[2:]))
    sys.exit(main())
