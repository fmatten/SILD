# CHANGELOG

Alle nennenswerten Änderungen an SILD werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

---

## [Unreleased] — durabler v2-Eingang (Variante A) + ADT-Mapper-Kette M-1–M-4

### Hinzugefügt
- **M-1 ADT-Mapper** (`sild_mapper_m1.py`): Polling-Konsument, liest den
  SILD-Intake **read-only**, eigene Mapper-DB; A04 intervall-relevant
  (Eintritts-Event für Muster B/C); 3-Wege-Zeitqualität
  (usable / hold_timequality / hold_malformed) mit Zeit-Provenienz;
  PID-freier Notifier (Speichern vor Melden); Mapper-DB-Erasure
  (SILD-Lesart-A, fail-closed).
- **Synthetischer ADT-Korpus** (54 Nachrichten, 7 Patienten,
  `samples/adt_m2_corpus/`) + separates Interface-Sample
  (`samples/adt_m2_interface/`, sauber datierter A02 mit ZBE-2) — beide
  synthetisch etikettiert.
- **M-2 Stufe 1** (`sild_mapper_m2.py`): zeit-sortierte
  Vorwärts-Rekonstruktion von `stay` + Lage-Segmenten (Eintrittsmuster
  A/B/C), zwei Wartefenster (Jitter + Notaufnahme-Join, Ankunfts-Wanduhr),
  offene Segmente (NULL-Ende) mit klassendifferenzierter
  Offen-Dauer-Überwachung (ambulant/stationär/intensiv), Idempotenz +
  Cursor-Disziplin aus M-1 geerbt, rohe PV1-3-Komponenten am Segment +
  Kontakt-Einheit zur Compute-Zeit (Über-Kontaktierungs-Sperre nur bei
  zeitlicher Überlappung).
- **M-2 Stufe 2 (M2c)**: revidierbarer Intervall-Kern — Storno A11/A12/A13,
  Update A08, verspätetes Normal-Event über EINEN mutate-Kern; Modell A
  (Mutation in place, Historie im Audit-Log) mit persist-before-mutate +
  idempotenter Mutation; ZST-Zielbindung fail-closed (MSH-10 + Typ + Zeit +
  Patient, kein Vier-Felder-Fallback); wartende Negationen (Tombstones)
  mit TTL, bleiben nach Ablauf liegen; aktive PID-freie
  AION-Benachrichtigung (alt→neu, Faktum statt Bewertung).
- **M-2 Stufe 3**: Plausibilität markieren + durchlassen, **nie reparieren**
  (Originalzeiten erhalten; 7 Marker-Arten, abgeleitet statt eingefroren);
  begrenzte Zeit-Schätzung `PROV_ESTIMATED` — nur beidseitig begrenzt
  (zeitloses A02 zwischen zwei bekannten Nachbar-Grenzen), geliefert als
  Intervall [t₁,t₂] (Maximal-Ausdehnungs-Kodierung, nie ein Punkt),
  isolierbar für ε-DP-Ausschluss; Schätzung folgt Stufe-2-Rückwirkungen
  (Neuableitung / Rückfall auf Hold).
- **M-4 Pull-Kontrakt SILD→AION (SILD-Seite)**: SQL-Views
  `v_aion_stay` / `v_aion_segment` / `v_aion_change` als stabile
  Vertragsfläche (AION liest read-only), `stay_revision` (atomare Revision
  an allen Schreibstellen) + `change_payload` (selbst-erklärender
  Änderungs-Strom); Kontrakt-Dokument `docs/aion-pull-contract.md`
  (Lese-Regeln, PID-Scope, Storno vs. Erasure). AION-Konsument B.1b ist
  separat im AION-Repo.
- `sild_durable_store.py` — durabler v2-Eingang **persist-before-ack** (Variante A):
  `frame → persist(fsync) → analyse → ack → forward`. SQLite (stdlib),
  `journal_mode=WAL, synchronous=FULL`. Garantien G1–G6 mit benannten Tests.
- **Default an** (fail-secure): Durability ist Standard; `--no-durable` schaltet
  ab (nur Demo/Test) und gibt eine laute Nicht-durabel-Warnung aus. Store-Pfad
  konfigurierbar via `--durable-store` (Default: Geschwister-Datei der `--log`).
- **Store-Erasure (SILD-SF-1)**: `sild_durable_store.py erase` — patientenbezogene
  Löschung, Schlüssel = PID-3/MR/`Authority|ID` (standortkonfigurierbar), dry-run
  per Default + `--commit` explizit, fail-closed `incomplete_uncertain` bei nicht
  zuordenbaren Zeilen, Lösch-Audit ohne Inhalt, X-weg/Y-intakt.
- `tests/test_durability_v2.py` + `tests/durability_vectors_v2.py` — 20 benannte
  Beweise (G1–G6, Patienten-Schlüssel, Erasure). `docs/security-findings.md` mit
  SILD-SF-1 (Erasure gebaut, Backup dokumentiert) und SILD-SF-2 (indirekte
  Identifier im JSONL).

### Geändert
- **ACK-Semantik unter persist-before-ack** (betrifft jetzt alle, da Default an):
  NAK-AE ist **signal-and-duplicate, NICHT reject**. Die Nachricht ist beim ACK
  bereits durabel; AE bei CRITICAL (K-2, FM-4 §5.2) signalisiert den Verlust,
  lehnt aber nicht ab — Sender-Retry erzeugt ein (downstream dedup-bares) Duplikat.
- Frame-Vollständigkeit: der durable Pfad liest strikt (VT … FS CR); kein
  Teil-Frame wird durabel geackt.

### Sicherheit
- **G6 (Verschlüsselung at-rest)**: laut delegiert an den Betreiber (RFC §11.1) —
  Startup-Warnung, keine rohe Payload im JSONL. „G6 grün" ≠ „PII-frei": indirekte
  Identifier (Order-Nummern in Finding-Locations) siehe SILD-SF-2.
---

## [1.1.0] — 2026-05-30 — HL7v2 B2-Conformance-Batch (21/21 Vektoren)

### Hinzugefügt
- B2-Infra: HL7v2-Conformance-Vektor-Satz + pytest-Runner (`tests/test_conformance_v2.py`); Baseline 11/21
- B2-TN: TN-CE-01 geschlossen — Prädikat-Inversion, OBX-3-Abdeckung, Severity-Korrektur
- B2-AD: AD-OBX-01 geschlossen — Prädikat-Verschärfung, Severity-Korrektur
- B2-RS: RS-ORC-01 geschlossen — Whitespace-Handling, Severity-Korrektur
- README: Abschnitt „Arbeitsweise & KI-Transparenz" ergänzt

### Geändert
- Docs: Konformitätsstatus auf FHIR 23/23 · v2 21/21 synchronisiert (README, PROJEKTBERICHT, KONFORMITAETSBERICHT)
- Docs: Selbst-Audit-Scope auf v1.0.6 präzisiert

---

## [1.0.6] — 2026-05-29 — FHIR B1-Conformance-Batch (23/23 Vektoren)

### Hinzugefügt
- B1-TC: TC-PERIOD-01 — Timing.repeat ohne event-Liste als Temporal Collapse erkannt
- B1-AD: AD-VAL-01 — Observation ohne value und ohne dataAbsentReason als Attribute Dropping erkannt

### Geändert
- B1-TN: TN-CC-01 Severity auf WARNING angehoben; Condition.code & bodySite abgedeckt
- B1-RS: RS-BUNDLE-01 geschlossen (Severity-Korrektur, urn:uuid:-Referenzen, #contained, externe URLs)
- AUDIT_BEFUND.md mit v1.0.5-Closure-Status finalisiert und aus Git-Tracking entfernt (.gitignore)

---

## [1.0.5] — 2026-05-28 — Selbst-Audit-Closure (H1–H5, Z1–Z2)

### Hinzugefügt
- H1(a): YAML-Conformance-Vector-Runner unter pytest hinzugefügt; Vollständigkeitsanspruch im README korrigiert

### Geändert
- Z1: Phantom-SHAs in RELEASE_NOTES durch `pre-public-baseline` ersetzt
- H2: Toten `CONTINUOUS_PROCEDURE_KEYWORDS`-Code entfernt, verbleibende Heuristik offengelegt
- H3: Veraltete Top-Level-Duplikate der Stack-Dateien gelöscht
- H4: CAIRN-Marketing entfernt; `sild_using_real_cairn`-Gauge vom Import entkoppelt
- H5: `loss_budget_bits` → `loss_budget_bits_estimate` (Metrik + Code + Dokumentation)
- Z2: Repository-URL in INHALT.md korrigiert (`codeberg/fmatten/sild` → `github/fmatten/SILD`)

---

## [1.0.4] — 2026-05-26 — RFC- und Conformance-Test-Korrekturen

### Geändert
- RFC-Entwurf v0.2 (DE + EN): FM-4 DOI ergänzt (`10.5281/zenodo.20391260`), FM-3/AION DOI ergänzt (`10.5281/zenodo.19553130`), CAIRN-URL korrigiert (`fm2-project/cairn` → `iscad/cairn`)
- Conformance Test Vectors v0.1: GitHub-Issues-URL korrigiert (`fm2-project/sild` → `fmatten/SILD`)

---

## [1.0.3] — 2026-05-26 — DOI-Korrekturen, Lizenz-Lücken, RFC-Entwürfe

### Hinzugefügt
- `Rfc draft v0.2.md` / `Rfc draft v0.2_en.md` — RFC-Entwurf v0.2 (DE + EN)
- `SILD Conformance Test Vectors v0.1.md` — Konformitätstestfälle
- `zenodo_upload_fm4v2.py` — Upload-Script für FM-4 v2 auf Zenodo

### Geändert
- FM-4-v2.pdf auf Zenodo veröffentlicht — neuer DOI: `10.5281/zenodo.20391260`
- Alle DOI-Referenzen auf FM-4 v2 (`20375435` → `20391260`) aktualisiert
- Lizenz-Lücken nachgezogen: EUPL-1.2 → AGPL-3.0-only in 11 Python-Docstrings, 2 Dockerfiles, 3 Dokumenten
- Pfade `start_sild` → `SILD` in PROJEKTBERICHT.md und KONFORMITAETSBERICHT.md
- Repository-Links `iscad/cairn` → `fmatten/sild` in PROJEKTBERICHT.md und INHALT.md
- FM-1-Jahreszahl: 2020 → März 2026 (README, PROJEKTBERICHT, INHALT, RELEASE_NOTES)
- PDF-Referenzen in INHALT.md durch DOI-Links ersetzt
- Repository auf GitHub öffentlich gestellt (`fmatten/SILD`)

---

## [1.0.2] — 2026-05-25 — NOTICE, dual-licence documentation

### Hinzugefügt
- `NOTICE` — Urheberrechtshinweise, Drittkomponenten, NOT A MEDICAL DEVICE-Disclaimer
- `CONTRIBUTING.md` — Beitragsrichtlinien, CLA, SPDX-Anforderungen
- `LICENSE-COMMERCIAL.md` — Kommerzielles Lizenzmodell dokumentiert

### Geändert
- README: Lizenzabschnitt auf AGPL-3.0-only OR LicenseRef-ISCaD-Commercial erweitert
- SPDX-Identifier in allen Quelldateien: `AGPL-3.0-only`

---

## [1.0.1] — 2026-05-25 — Lizenzwechsel EUPL-1.2 → AGPL-3.0-only OR Commercial

### Geändert
- Open-Source-Lizenz von EUPL-1.2 auf **GNU Affero General Public License v3 (AGPL-3.0-only)** umgestellt
- `LICENSE`-Datei erstellt mit vollständigem AGPL-3.0-Text
- Alle 13 Python-Quelldateien: `SPDX-License-Identifier: AGPL-3.0-only` Header hinzugefügt
- README: Badge `AGPL-3.0` hinzugefügt, Lizenztext auf AGPL-3.0 aktualisiert
- Dual-Lizenzmodell eingeführt: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial

---

## [1.0.0] — 2026-05-24 — Erstveröffentlichung

### Hinzugefügt
- SILD Monitoring Stack v3.0 — vollständige FM-4-Referenzimplementierung
- `sild_detector.py` — `sild.core`: trägerunabhängige Mustererkennung (FM-4 Korollar A.4/A.5)
- `sild_mllp_filter.py` — `sild.v2.rules`: HL7v2/MLLP-Filter mit Prometheus-Metriken
- `sild_fhir_filter.py` — `sild.fhir.rules`: FHIR-R4/HTTP-Filter
- `sild_fhir_profiles_de.py` — `sild.fhir.profiles_de`: MII/KBV DE-Basisprofile
- `sild_mllp_target.py` / `sild_fhir_target.py` — Mock AION MLLP/FHIR-Empfänger
- `sild_mllp_sender.py` / `sild_fhir_sender.py` — Testsender
- `load_generator.py` — Lastgenerator mit p99-Latenzüberwachung
- Grafana-Dashboard `sild_operations.json` (8 Panels)
- Prometheus-Konfiguration, Docker Compose Stack
- HL7v2-Testdaten (`samples/`) und FHIR-R4-Bundles (`samples_fhir/`)
- `severity_overrides_example.json` — K-3 Override-Konfiguration

### FM-4-Konformität (15/15 Lücken behoben)
- **K-1–K-3** (Kritisch): Type Narrowing terminologisch, MLLP NAK-AE, Severity-Override-Komposition
- **M-1–M-8** (Mittel): AD OBX-2, TC FHIR, RS Bundle-Referenzen, Verlust-Budget, Latenz, Audit-Tupel, MLLP/FHIR-Sibling, DE-Basisprofile
- **N-1–N-4** (Niedrig): NAK-Test-Modus, FHIR-Location-Fix, Dokumentation, requirements.txt

---

## [2026-05-26] — Lizenz-Lücken: EUPL-1.2 → AGPL-3.0-only OR LicenseRef-ISCaD-Commercial

### Korrekturen (nachgezogene Datei-Aktualisierungen)

- **11 Python-Docstrings** (alle `sild_*.py`): `License: EUPL-1.2` → `License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial`
  - `sild_fhir_filter.py`, `sild_fhir_sender.py`, `sild_fhir_target.py` (Root)
  - `sild_monitoring_stack/sild_detector.py`, `sild_fhir_filter.py`, `sild_fhir_profiles_de.py`,
    `sild_fhir_sender.py`, `sild_fhir_target.py`, `sild_mllp_filter.py`,
    `sild_mllp_sender.py`, `sild_mllp_target.py`
- **2 Dockerfiles** OCI-Label: `licenses="EUPL-1.2"` → `licenses="AGPL-3.0-only OR LicenseRef-ISCaD-Commercial"`
  - `Dockerfile-v2`, `sild_monitoring_stack/Dockerfile`
- **`sild_monitoring_stack/README.md`** Lizenzabschnitt: EUPL-1.2 → AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
- **`PROJEKTBERICHT.md`** Metadaten-Tabelle: EUPL-1.2 → AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
- **`INHALT.md`** Fußzeile: EUPL-1.2 → AGPL-3.0-only OR LicenseRef-ISCaD-Commercial

---

## [2026-05-25] — Lizenzwechsel EUPL-1.2 → AGPL-3.0

### Lizenzwechsel

- Open-Source-Lizenz von EUPL-1.2 auf GNU Affero General Public License v3 (AGPL-3.0-only) umgestellt
- `LICENSE`-Datei erstellt mit vollständigem AGPL-3.0-Text
- Alle 13 Python-Quelldateien: `SPDX-License-Identifier: AGPL-3.0-only` Header hinzugefügt
- README: Badge `AGPL-3.0` hinzugefügt, Lizenztext auf AGPL-3.0 aktualisiert
