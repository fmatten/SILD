<!--
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
-->

# DEP-1 / DEP-S2 — WAL-RO-Probe (Ergebnis, STOP-Punkt ans Gate)

**Datum:** 2026-06-14 · **Box:** `aion-staging` · **Label:** DEP-1.
**Bezug:** Phase-2-Briefing, „Kernbedingung DEP-S2 (WAL): Probe ZUERST".
**Ergebnis kurz:** RO-Lesen ist **vertragssicher erreichbar** (Schreibversuch in
**jedem** lesbaren Fall abgewiesen). **Aber** der im Decision-Sheet skizzierte
**Einzeldatei-`:ro`-Mount der Live-DB funktioniert NICHT** (Daten liegen im
`-wal`, unsichtbar). Die robuste, vertragssichere Variante (Checkpoint-Snapshot)
ist eine **Gate-Entscheidung** → daher **STOPP**, nicht improvisiert.

> Zusätzlicher Blocker (separat): `/srv/sild` + `sild`-Konto unter `/srv`
> brauchen root; `sudo` verlangt hier Passwort (kein passwortloses sudo). Die
> Probe lief deshalb in `~/sild-dep1-probe/` — **nur synthetische** Korpus-Daten,
> nicht in `/srv`, Tabu-Zonen unberührt.

## Aufbau (real, nicht gemockt)

- `m2.db` über die **echte** Kette gebaut: `DurableStore.persist` → `MapperM1.poll_once`
  → `M2Store` + `MapperM2` (zwei Polls über das 300s-Jitter-Fenster, fixe Uhr
  `2026-06-12`). Quelle: synthetischer Korpus `samples/adt_m2_corpus/` (54 Nachrichten).
- Ergebnis-DB deckt sich mit `EXPECTED_CORPUS_STAYS`: **7 Stays, 13 Segmente, 1 Change**
  (`v_aion_stay`/`v_aion_segment`/`v_aion_change`).
- Leser = **Wegwerf-Container aus dem `aion-clinical-local:1.19.0`-Image**, `--user 1000:1000`
  (= aion-uid), `--network none`, RO-Bind-Mount. Der **laufende** `aion-api` wurde
  NICHT angefasst (Mounts kann man laufenden Containern ohnehin nicht hinzufügen).
- `aion-api`-Image hat Python 3.12 + sqlite **3.46.1** (identisch zur Host-Engine).

## Zwei Zustände — entscheidend zu unterscheiden

- **Zustand „Snapshot"**: alle Verbindungen sauber geschlossen → SQLite checkpointet
  beim Close → `m2.db` self-contained (176 KB), **kein** `-wal`.
- **Zustand „Live"**: M-2-Writer hält die Verbindung offen (Dauerbetrieb) →
  `m2.db` 4 KB (leer), **`m2.db-wal` 2 MB (alle Daten)**, `m2.db-shm` 32 KB.
  **Das ist der reale Betriebszustand**, in dem AION lesen würde.

## Probe-Matrix (empirisch)

| # | Zustand | Mount | URI | Read der 3 Views | Schreibversuch | Verdikt |
|---|---------|-------|-----|------------------|----------------|---------|
| 1 | Snapshot | Einzeldatei `:ro` | `mode=ro` | **FAIL** „attempt to write" (WAL-Journal-Modus will `-shm` anlegen) | abgewiesen | ✗ |
| 2 | Snapshot | Einzeldatei `:ro` | `immutable=1` | **7/13/1 ✓** | abgewiesen ✓ | ✓ |
| 3 | Snapshot→`journal_mode=DELETE` | Einzeldatei `:ro` | `mode=ro` | **7/13/1 ✓** | abgewiesen ✓ | ✓ (sauberster) |
| 4 | **Live** | Einzeldatei `:ro` (nur `m2.db`) | `immutable=1` | **FAIL** „no such table" (Daten im `-wal`, unsichtbar) | abgewiesen | ✗ Falle |
| 5 | **Live** | Verzeichnis `:ro` (`-wal`+`-shm` sichtbar) | `mode=ro` | **7/13/1 ✓** | abgewiesen ✓ | ⚠ funktioniert **nur solange der Writer `-shm` pflegt** |
| 6 | **Live** | Verzeichnis `:ro` | `immutable=1` | **FAIL** „no such table" (ignoriert `-wal` → stale) | abgewiesen | ✗ Falle (stiller Stale-Read) |

### Lesarten

- **Vertrags-Integrität gewahrt:** In **jedem** Fall wurde der Schreibversuch
  abgewiesen („attempt to write a readonly database"). Die nicht-verhandelbare
  Invariante „AION darf `m2.db` nie mutieren" hält auf allen getesteten Pfaden.
- **Einzeldatei-`:ro` der Live-DB ist falsch (#4):** der im Decision-Sheet (DEP-S2)
  skizzierte `m2.db:…:ro`-Einzelmount lässt das `-wal` weg → AION sähe eine quasi
  leere DB. **Muss verworfen werden.**
- **`immutable=1` auf der Live-DB ist gefährlich (#4/#6):** ignoriert das `-wal`
  und liefert den veralteten Hauptdatei-Stand — ein **stiller** Falsch-/Leer-Read.
  `immutable=1` ist NUR auf einem checkpointeten Snapshot ohne `-wal` korrekt (#2).
- **Direkter Live-Verzeichnis-Mount (#5) liest zwar korrekt, ist aber fragil:**
  klappt nur, **weil der Host-Writer das `-shm` aktiv pflegt**. Bei M-2-Neustart/
  -Stopp (kein `-shm`) fällt der RO-Leser auf #1 zurück (FAIL). Koppelt AIONs
  Lese-Korrektheit an SILDs Prozess-Lebenszyklus + Checkpoint-Timing → für eine
  Vertragsfläche unerwünscht.

## Schlussfolgerung

RO-Lesen unter WAL ist **erreichbar und vertragssicher** — aber **nicht** über den
naiven Live-Mount. Die robuste, entkoppelte Variante ist ein **publizierter
Checkpoint-Snapshot**, den AION read-only liest (Reihe #2 `immutable=1` oder #3
`journal_mode=DELETE`). Die Wahl des Mechanismus berührt die Vertragsfläche und
das Betriebsmodell → **Gate-Entscheidung, nicht improvisiert** (so im Briefing
festgelegt). **STOPP.**

## Optionen fürs Gate

- **Option A — Checkpoint-Snapshot (empfohlen).** M-2 (oder ein kleiner Publisher)
  erzeugt periodisch/triggerbasiert eine self-contained `m2_pull.db`
  (`wal_checkpoint(TRUNCATE)` bzw. `VACUUM INTO`), optional `journal_mode=DELETE`.
  AION mountet diese **Einzeldatei `:ro`** (`mode=ro`+`query_only=ON`, bzw.
  `immutable=1`). Vorteile: vom Live-Writer entkoppelt, atomar publizierbar,
  `:ro` ausreichend, Invariante trivial gewahrt. Kosten: Pull-Latenz = Snapshot-
  Intervall; Publisher-Schritt nötig.
- **Option B — Direkter Live-Verzeichnis-`:ro`-Mount (#5).** Geringere Latenz,
  aber fragil (an `-shm`/Writer-Lebenszyklus gekoppelt), `:ro` muss `-wal`/`-shm`
  mit-mounten; Verhalten bei M-2-Neustart abklären. Nicht empfohlen für eine
  Vertragsfläche.
- **Option C — Carrier wechseln** (z. B. M-2 in `journal_mode=DELETE`/`TRUNCATE`
  statt WAL betreiben, oder Pull über eine Netzwerk-/Read-Replica-Fläche). Größerer
  Eingriff; berührt M-2-Durabilitätsprofil (aktuell WAL + `synchronous=FULL`).

## Offene Punkte (an Gate zurück)

1. **Mechanismus A/B/C wählen** (empfohlen: A).
2. Bei A: Snapshot-Kadenz + Auslöser, Publisher-Eigentümer (`sild`-Konto), Pfad
   (`/srv/sild/data/m2_pull.db`), UID-/Gruppen-Mapping in `aion-api`.
3. **Root-Bootstrap:** `/srv/sild` + `sild`-Konto anlegen (braucht root — hier kein
   passwortloses sudo). Wer/wie? Bis dahin kann der reale Deploy nach `/srv/sild`
   nicht erfolgen.
4. Decision-Sheet `docs/deploy-decision-sheet.md` DEP-S2 entsprechend korrigieren
   (Einzeldatei-Live-Mount streichen).

## Mechanismus A — Verifikation (nach Gate-Ratifikation)

Mechanismus A wurde gebaut (`sild_monitoring_stack/sild_m2_snapshot.py`) und in der
Sandbox **gegen den Live-WAL-Zustand** verifiziert:

| Schritt | Ergebnis |
|---|---|
| Publisher `VACUUM INTO` aus LIVE-`m2.db` (Daten im `-wal`) | Snapshot `m2_pull.db` self-contained, **`journal_mode=delete`**, kein `-wal`; `stay=7 segment=13 change=1` |
| Quelle danach | **unverändert** (4096 B, mtime gleich) → SILD-Publisher mutiert die Live-DB nicht |
| AION-Read: Snapshot-**Einzeldatei** `:ro`, `mode=ro`, Container uid 1000 | **7/13/1 ✓** |
| Schreibversuch des Consumers | **abgewiesen** → Vertrags-Invariante gewahrt |

**Wichtiger Implementierungspunkt:** Der Publisher öffnet die Quelle **RW-fähig**
(nicht `mode=ro`) — sonst scheitert `VACUUM INTO` an genau demselben `-shm`-Caveat
(„attempt to write a readonly database"). Das ist zulässig: die „AION mutiert
nie"-Invariante gilt für den `:ro`-beschränkten **Consumer**, nicht für SILDs
eigenen Publisher; `VACUUM INTO` liest die Quelle nur und schreibt in die NEUE
Datei (kein DML/DDL gegen die Quelle).

## Demo-Sequenz (DEP-S3) — vorab durch die echte Kette verifiziert

Synthetisches Set `deploy/staging/demo/` (Patient `DEMO001`, rein synthetisch),
A01→A02→A03 durch `DurableStore`→M-1→M-2:

- M-1: alle drei **`usable`** (A01 via EVN-2, A02 via **ZBE-2**, A03 via EVN-2).
- M-2: **1 Stay** `UKH|DEMO001`/`VDEMO01`, Muster A, `closed`; Segmente
  **NA** (08:00→12:00) → **IM1** (12:00→16:00).

## Artefakte

- Produktion: `sild_monitoring_stack/sild_m2_snapshot.py` (Publisher),
  `deploy/staging/` (Dockerfile.sild, docker-compose.sild.yml, BOOTSTRAP.md, demo/).
- Probe-Skripte/Daten: `~/sild-dep1-probe/` (`build_m2.py`, `holder.py`, `probe.py`,
  `data/`, `live/`, `demo/`) — synthetisch, außerhalb `/srv`, Tabu-Zonen unberührt.
  Live-Writer-Prozess gestoppt.
