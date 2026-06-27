<!--
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
-->

# SILD-Deploy auf Staging — Phase 1: Interop-Inventur + Decision-Sheet

**Status:** Phase 1 (doc-only, read-only). Kein Deploy, kein `/srv/sild`, kein
Container/Compose, keine Stack-Änderung. Phase 2 erst nach Gate.
**Box:** `aion-staging` (AION-Stack läuft: aion-api/keycloak/postgres/redis).
**Erstellt:** 2026-06-14. Jeder Befund mit Beleg (Datei:Zeile).

---

## Teil 1 — Interop-Inventur (Ist-Stand der Mapper-Kette M-1…M-4)

### 0. Reale Datenfluss-Topologie (Beleg statt Annahme)

```
HL7-v2-Quelle ──MLLP──▶ sild_mllp_filter ──(persist-before-ack)──▶ intake.db
                         (--listen 2575,           (sild_durable_store)
                          --forward host:port,
                          --durable-store PFAD)
                                                          │ read-only Poll
                                                          ▼
                                        sild_mapper_m1 (--intake-db RO, --mapper-db) ──▶ m1.db
                                                          │ read-only Poll
                                                          ▼
                        sild_mapper_m2 (--m1-db RO, --intake-db RO, --m2-db) ──▶ m2.db
                                                          │
                                                          ▼  v_aion_stay / v_aion_segment / v_aion_change
                                                   AION liest m2.db READ-ONLY
```

Belege: `sild_mllp_filter.py:45-47,296-300,614-636`; `sild_mapper_m1.py:5-12,958-959`
(`--intake-db` *nur lesend*, `--mapper-db` eigenes Volume); `sild_mapper_m2.py:3181-3186`
(`--m1-db`/`--intake-db` *nur lesend*, `--m2-db` eigen); `sild_mapper_m2.py:3226-3228`
(`M1OutputReader(args.m1_db, args.intake_db)`, `M2Store(args.m2_db)`).

> **Wichtig:** `sild_mllp_target.py` ist ein **Mock von AIONs Listener**
> (`sild_mllp_target.py:5,8`), NICHT SILDs Ingest. SILDs Ingest ist
> `sild_mllp_filter.py`.

### 1. HL7-v2-ADT-Trigger — real unterstützt

| Trigger | Bedeutung | Behandlung | Beleg |
|---|---|---|---|
| **A01** | Aufnahme | intervall-**bestimmend**, Zeit→PV1-44→EVN-6→EVN-2 | `sild_mapper_m1.py:114,194` |
| **A02** | Verlegung | intervall-bestimmend, Zeit→ZBE-2→EVN-6 (**bewusst NICHT** PV1-44, Anti-Falsch-Datierung) | `sild_mapper_m1.py:115,166,195` |
| **A03** | Entlassung | intervall-bestimmend, Zeit→PV1-45→EVN-6→EVN-2 | `sild_mapper_m1.py:116,196` |
| **A04** | Registrierung (ambulant/Notaufnahme) | Eintritts-Event, Zeit→EVN-6→EVN-2 | `sild_mapper_m1.py:117-122,197` |
| **A08** | Update | rückwirkend intervall-verändernd, Zeitfeld profilabhängig → final M-2 | `sild_mapper_m1.py:123,198` |
| **A11/A12/A13** | Storno Aufnahme/Verlegung/Entlassung | als relevant **durchgereicht**; Widerruf des Intervalls ist M-2 | `sild_mapper_m1.py:124-126,199-201` |

- **Bewusst ignoriert** (kein Befund, kein M-2-Push): Nicht-ADT (ORU/RDE/technisch)
  und nicht-intervall-relevante ADT (A05/A06/A07/A21/A22 …). Beleg:
  `sild_mapper_m1.py:34-37` (M1-G3-Grenze, erweiterbar).
- **Defekt ≠ irrelevant:** ADT mit fehlendem/unlesbarem Trigger (MSH-9) →
  `hold_malformed` + Befund, geht NICHT verloren. Beleg: `sild_mapper_m1.py:37-39,363-365`.
- Trigger-Validierung: `A` + 2 Ziffern (A01..A99), `sild_mapper_m1.py:129-136`.

**Ehrlicher Vorbehalt:** A02→ZBE-2 und der EVN-Fallback sind im Code als
*an echten Daten zu verifizieren* markiert (Sample-Lage ohne ZBE/EVN-6),
`sild_mapper_m1.py:179-184`. Für die Demo unkritisch (synthetisch steuerbar).

### 2. FHIR

- **Version:** FHIR **R4**. Beleg: `sild_fhir_filter.py:5,116` (`PROTOCOL = "fhir_r4"`).
- **Eingang:** HTTP POST `/fhir/Bundle` bzw. `/Bundle`; akzeptiert nur
  `resourceType == "Bundle"`, sonst `OperationOutcome`. Beleg:
  `sild_fhir_filter.py:18-19,210,235-238`.
- **Ressourcen (analysiert):** Bundle (`transaction`), Patient, Encounter,
  Observation, Condition, Procedure; Ausgabe `transaction-response` + FHIR
  **AuditEvent** (M-5, FM-1-Tupel). Beleg: `sild_fhir_filter.py:235,357,394,400`;
  `KONFORMITAETSBERICHT.md:572-587`.
- **DE-Profile (M-8, MII/KBV):** ICD-10-GM Condition ohne Diagnosesicherheit,
  Observation ohne UCUM-Einheit, Patient ohne KVid. Beleg:
  `sild_fhir_profiles_de.py:10-13,66,99,164`.

### 3. MLLP-Ingest — Framing & ACK/NAK

- **Port:** Default `--listen 2575` (`sild_mllp_filter.py:614`); Forward-Ziel
  konfigurierbar (`--forward`, `:615`).
- **Framing:** Standard-MLLP `VT(0x0B) … FS(0x1C) CR(0x0D)`; durabler Pfad
  verlangt **vollständigen Frame** (`strict=True`) vor Persist. Beleg:
  `sild_mllp_filter.py:188-193`; `sild_mllp_target.py:33` (Framing-Konstanten).
- **ACK (AA):** nur MSH+MSA, Standard-Accept. Beleg: `sild_mllp_filter.py:113-148`.
- **NAK (AE):** protokollkonform mit **ERR-Segment** bei SILD-Block oder
  Forward-Fehler (K-2-Fix, FM-4 §5.2). Beleg: `sild_mllp_filter.py:117-118,142-146`.
- **persist-before-ack (Variante A):** `frame → persist(fsync) → analyse → ack →
  forward`. Invariante **ACK ⇒ durabel**; unvollständiger Frame wird NICHT
  geackt → kein stiller Verlust. Beleg: `sild_mllp_filter.py:296-299,188-191`;
  `sild_durable_store.py:21,34` (G1/G4). → **Kein Absturz bei standardwidriger
  Nachricht:** entweder NAK-AE oder durabler Hold, je nach Defektart.

### 4. Contract-Fläche — die M-2-SQLite (was AION liest)

Der Vertrag **sind die drei Views** (internes Schema darf sich ändern,
View-Spalten bleiben stabil — M4-G1). Beleg: `sild_mapper_m2.py:1052-1057`;
`docs/aion-pull-contract.md:16-18,202`.

| View | PID? | Inhalt | Beleg |
|---|---|---|---|
| `v_aion_stay` | **PID-tragend** (`patient_key`, `visit_id`) | aktueller Aufenthalts-Stand, `revision`, `status`, `pattern`, Marker | `sild_mapper_m2.py:1058-1073`; Kontrakt §3 |
| `v_aion_segment` | PID-frei (Quasi-Identifikator) | Lage-Segmente, `pv1_3_raw`, ward/room/bed, start/end + `*_provenance`, Schätz-Schranken | `sild_mapper_m2.py:1075-1098`; Kontrakt §4 |
| `v_aion_change` | PID-frei (Quasi-Identifikator) | Änderungs-Log; `notification_id` = Cursor (AUTOINCREMENT, monoton), `after_json` = **vollständiger** neuer Stay-Zustand | `sild_mapper_m2.py:1100-1110`; Kontrakt §5 |

Read-only-Vertrag: AION öffnet `mode=ro` + `PRAGMA query_only=ON`, schreibt NIE,
liest nur über Views; Cursor `WHERE notification_id > :cursor`. Geschätzte Grenzen
(`provenance = 'estimated'`) tragen **Schranken, keinen Punkt** — AION muss sie
ausschließen/intervallweise behandeln (M4-G6). Beleg:
`docs/aion-pull-contract.md:9-18,42-44,100-116,202-208`.

**M-2 DB-Engine:** WAL + `synchronous=FULL` (`sild_mapper_m2.py:1118-1124`).
→ relevant für DEP-S2: AION liest **nicht** die Live-`m2.db`, sondern einen
publizierten Snapshot (`m2_pull.db`); Begründung + Probe in `docs/dep1-wal-probe.md`.

**Inventur-Fazit Teil 1:** SILD spricht ADT {A01,A02,A03,A04,A08,A11–A13} und
FHIR R4 (+DE-Profile) **standardkonform und ehrlich abgegrenzt**; MLLP mit
persist-before-ack und protokollkonformem NAK-AE; Contract-Fläche = drei stabile
read-only-Views in `m2.db`. **Keine Abweichung von der Erwartung** — der
Demo-Pfad A01→A02→A03(→A08) wird von der realen Kette getragen.

---

## Teil 2 — Deploy-Decision-Sheet (Vorschläge zur Gate-Entscheidung)

### D-S1 — Topologie (Vorschlag, in Phase 1 NICHT angelegt)

- Zielwurzel **`/srv/sild`** (neu). Verifiziert: existiert noch nicht
  (Phase-0-Inventur: „`/srv/sild` Datei oder Verzeichnis nicht gefunden").
  **Nicht** in Tabu-Zonen (`/srv/aionprod`, `/srv/repositories`, workpool/ZFS, `/media/*`).
- Eigentümer-Konto: eigenes `sild`-Konto (nicht `iscad`, nicht `fmatten/aionprod`).
- Layout-Vorschlag:
  ```
  /srv/sild/repo/            # frischer Clone (Account-Key heute, Deploy-Key Prod → D-S4)
  /srv/sild/data/intake.db   # persist-before-ack store
  /srv/sild/data/m1.db       # M-1 Mapper-DB
  /srv/sild/data/m2.db       # M-2-DB (LIVE, WAL) — NUR SILD-intern, nicht für AION
  /srv/sild/data/m2_pull.db  # Snapshot (self-contained) = Contract-Fläche, AION liest hier RO
  /srv/sild/logs/
  ```

### D-S2 — Integration: wie erreicht `aion-api` die M-2-SQLite read-only? (Kernpunkt)

> **AKTUALISIERT nach DEP-1 / WAL-RO-Probe (`docs/dep1-wal-probe.md`).**
> Mechanismus **A (publizierter Checkpoint-Snapshot)** ratifiziert und in der
> Sandbox verifiziert (`:ro`-Read 7/13/1 grün, Schreibversuch abgewiesen).

- **Transport = Dateisystem, nicht Netzwerk.** Der Kontrakt ist ein read-only
  SQLite-Zugriff (`docs/aion-pull-contract.md:9-11`), kein HTTP/OIDC-Pfad. →
  **keine OIDC-Pflicht auf diesem Pfad** (B.1b liegt außerhalb dieses Repos).
- **❌ VERWORFEN — Einzeldatei-`:ro`-Mount der LIVE `m2.db`** (frühere Skizze
  `/srv/sild/data/m2.db:…:ro`). Die Probe zeigt: die Live-DB hält ihre Daten im
  `-wal`; ein Einzeldatei-Mount lässt das `-wal` weg → AION sähe eine **leere**
  DB. Beleg: `dep1-wal-probe.md` Matrix-Zeile #4.
- **❌ FALLE — `immutable=1` auf der LIVE-DB:** ignoriert das `-wal` → stiller
  **Stale-Read**. Nur auf einem checkpointeten Snapshot ohne `-wal` korrekt.
  Beleg: Matrix-Zeilen #4/#6.
- **⚠ NICHT für Vertragsfläche — direkter Live-Verzeichnis-`:ro`-Mount:** liest
  zwar (Matrix #5), aber nur solange der Writer das `-shm` pflegt → fragil,
  koppelt AIONs Lese-Korrektheit an SILDs Prozess-Lebenszyklus.
- **✅ GEWÄHLT — Mechanismus A, publizierter Snapshot:** ein Publisher
  (`sild_m2_snapshot.py`) erzeugt per `VACUUM INTO` eine **self-contained**
  `m2_pull.db` (kein `-wal`, `journal_mode=delete`) und publiziert sie **atomar**
  (`os.replace`). AION mountet die **Snapshot-Einzeldatei `:ro`** und liest
  `mode=ro` + `query_only=ON`. Verifiziert: 7 Stays / 13 Segmente / 1 Change
  grün, Schreibversuch abgewiesen (`dep1-wal-probe.md`).
  - Vertragspfad: `/srv/sild/data/m2_pull.db` (nicht die Live-`m2.db`).
  - **UID-Mapping:** `aion-api` liest als **uid 1000(aion)**; Snapshot mit
    `0644` (welt-/gruppenlesbar) publiziert → uid 1000 kann lesen. Optional
    gemeinsame Gruppe statt 0644.
  - **Kadenz/Trigger:** s. DEP-S3 — demo-wahrnehmbar (nach jedem M-2-Batch bzw.
    kurzes Intervall).

### D-S3 — Synthetisches Demo-Szenario (Demo-Kern, nur synthetisch)

- Patientenpfad als ADT-Sequenz **A01 → A02 → A03 (→ A08)**, auf Knopfdruck
  reproduzierbar; parallel FHIR-R4-Darstellung (Bundle mit Encounter/Patient).
- **Trägt die reale Kette?** Ja — alle vier Trigger sind in M-1 verdrahtet
  (Teil 1.1). A08-Rückwirkung wird in M-2 final aufgelöst.
- **Material vorhanden:** synthetischer Korpus `samples/adt_m2_corpus/` enthält
  bereits A01×6, A02×5, A03×2, A04×6 (verifiziert per `ls`); zusätzlich
  `samples/adt_m2_interface/`. Lastgeber: `load_generator.py`. → Für die Demo
  genügt ein kleiner, kuratierter Pfad eines synthetischen Patienten.
- **Striktes Verbot echter Patientendaten** — nur synthetisch.

### D-S4 — Deploy-Key-Härtung

- Account-Key → repo-gebundener **read-only Deploy-Key** = **Prod-Vorbedingung**,
  vor Produktivgang registrieren. **Kein Phase-1-Blocker:** der Clone funktioniert
  bereits über den Account-Key.

---

## Vorgeschlagenes Label

SILD führt **M/K/N/H/FM** (kein I — „I-2" war Geister-Label im aionprod-Namensraum,
gestrichen). Vorschlag: **neuer `D`-Namensraum (Deploy)** —
**`D-1` — SILD-Staging-Deploy (Interop-Demo)**, mit Unterposten D-S1…D-S4.
Vergabe erst durch die Review-/Gate-Ebene.

## Koordination (für Phase 2 vorgemerkt)

`v_aion_*`-Änderungen berühren AION → versionierte Migration (M4-G1) +
Abstimmung über `aion-coordination`. Phase 1 = reine Inventur, hier nur vorgemerkt.

---

## Offene Punkte fürs Gate

1. **D-S2 WAL-Reader:** read-only-Zugriff auf WAL-`m2.db` praktisch verifizieren
   (Mount-Form `-wal`/`-shm` bzw. `immutable`).
2. **D-S2 OIDC:** bestätigen, dass der Dateisystem-Pull keinen OIDC-Pfad braucht
   (AION-seitig B.1b).
3. **A02/EVN-Fallback** an (synthetisch nachgestellten) realistischen Daten
   gegenprüfen (`sild_mapper_m1.py:179-184`).
