# CHANGELOG

Alle nennenswerten Änderungen an SILD werden hier dokumentiert.
Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

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
