# SILD — Signal-Loss Inspection at Data-boundaries

SILD ist die offene **Referenz-Implementierung und Mess-Methodik** zur Erkennung
semantischen Datenverlusts an klinischen System-Grenzen — die operative Umsetzung
von **FM-4**. Veröffentlicht zur **methodischen Nachprüfbarkeit**: vier kanonische
Verlustmuster, ein trägerunabhängiger Detektor (FHIR R4 + HL7 v2), maschinell
verifizierte Conformance-Vektoren. Für produktive Einbettung in Klinik-Infrastruktur
und für signierte Einmal-Diagnosen einzelner Schnittstellen siehe Abschnitt
**Nutzung & Lizenz** unten.

[![Licence: AGPL-3.0](https://img.shields.io/badge/Licence-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

> Lizenz: [AGPL-3.0 OR Commercial](LICENSE) · Autor: Friedhelm Matten / [ISCaD GmbH](https://iscad-it.de) · Theorie-DOI: [10.5281/zenodo.20391260](https://doi.org/10.5281/zenodo.20391260)
> GitHub: [fmatten/SILD](https://github.com/fmatten/SILD) · Codeberg: [fmatten/sild](https://codeberg.org/fmatten/sild)

---

## Nutzung & Lizenz

SILD ist offen (AGPL-3.0), weil die Methode öffentlich nachprüfbar sein muss.
Der gesamte Code, alle Conformance-Vektoren und der formale Hintergrund (FM-4)
liegen offen — jeder kann die Detektion reproduzieren, die Spezifikation prüfen
und die Mess-Methodik kritisieren.

Für die **produktive Einbettung** in Klinik-Infrastruktur (laufende Überwachung,
eigene Tenant-Konfigurationen, Integration in bestehende Compliance-Prozesse) ist
die AGPL meist die falsche Wahl, weil §13 weitreichende Offenlegungspflichten
erzeugt. Dafür existiert die **kommerzielle Lizenzschiene** — Kontakt:
[ISCaD GmbH](https://iscad-it.de).

Für eine **einmalige, signierte Diagnose** einer konkreten Schnittstelle — was
die meisten Häuser zuerst brauchen, bevor produktive Integration überhaupt
sinnvoll ist — gibt es das **Grenzverlust-Assessment**: 2–3 Wochen, Festpreis,
Befundbericht mit priorisierter Mängelliste, durchgeführt durch den
Methodenurheber. Kontakt: ebenfalls ISCaD.

---

## Arbeitsweise & KI-Transparenz

Methode, Spezifikation und konforme Entscheidungen verantwortet der Autor
(ISCaD GmbH). Die Code-Umsetzung erfolgt im Workflow
*Spezifikation → Implementierung → Konformitätsprüfung* unter Einsatz von
KI-Assistenz (Claude Code), erkennbar an den entsprechenden
`Co-authored-by`-Trailern in der Commit-Historie.

Jede Spec-Entscheidung, jede Severity-Wahl und jede Vektor-Anpassung ist
nachvollziehbar dokumentiert; das offen veröffentlichte Selbst-Audit
prüft genau diese Konsistenz von Spezifikation und Code. Lizenz- und
Urheberverantwortung liegt vollständig beim Autor — die KI-Attribution
ist ein Beleg der Werkzeug-Nutzung, kein Urheberanspruch.

---

## Theoretische Grundlage

SILD ist die direkte operative Umsetzung von **FM-4** (*Signal-Loss Inspection at
Data-boundaries*, Matten, ISCaD GmbH, Mai 2026), aufbauend auf dem formalen
Informationsraum aus **FM-1** (*Grundlagen zur wissenschaftlichen Auswertung von
klinischen Informationen*, Matten, März 2026).

FM-4 definiert vier kanonische Verlustmuster als Endo-Operatoren auf dem
Informationsraum `I`:

| Pattern | FM-4 | Beschreibung | Beispiel |
|---|---|---|---|
| **Type Narrowing** (TN) | Def. 2.1 | τ(e'') liegt in schwächerer Terminologie | LOINC-Code → Freitext |
| **Temporal Collapse** (TC) | Def. 2.2 | dim t(e) > dim t(e'') | Intervall [t₁,t₂] → Zeitpunkt t* |
| **Attribute Dropping** (AD) | Def. 2.3 | Modifier mᵢ ∈ m(e), aber mᵢ ∉ m(e'') | Diagnosesicherheit geht verloren |
| **Reference Severing** (RS) | Def. 2.4 | Referenz vorhanden, aber φ(r'ᵢ) = ∅ | Encounter-Referenz nicht auflösbar |

**Vollständigkeitssatz (FM-4 Satz 2.5):** Jede verlustbehaftete Übertragung liegt
in `TN ∪ TC ∪ AD ∪ RS` — die vier Muster decken alle möglichen semantischen
Verluste ab.

---

## Architektur

```
KIS / LIS / Testsender
        │
        ├──── HL7v2 / MLLP ────► sild-filter :2575 ────► aion-mock :2576
        │                         sild.v2.rules             (Zielsystem)
        │                         Metriken: :9100
        │
        └──── FHIR R4 / HTTP ───► sild-fhir-filter :8080 ► aion-fhir-mock :8081
                                   sild.fhir.rules
                                   + sild.fhir.profiles_de (DE/MII)
                                   Metriken: :9101

Beide Filter ──► Prometheus :9090 ──► Grafana :3000
```

### FM-4 Adapter-Architektur (Abschnitt 3)

| Modul | Datei | Aufgabe |
|---|---|---|
| `sild.core` | `sild_detector.py` | Trägerunabhängige Mustererkennung, Datenklassen, Verlust-Budget |
| `sild.v2.rules` | `sild_mllp_filter.py` | HL7v2-Segment-Pfade und -Prädikate |
| `sild.fhir.rules` | `sild_fhir_filter.py` | FHIR-R4-Ressourcen-Pfade und -Prädikate |
| `sild.fhir.profiles_de` | `sild_fhir_profiles_de.py` | MII/KBV DE-Basisprofile |

> Der `core`-Layer ist zwischen v2- und FHIR-Sibling **byte-identisch** —
> direkte Konsequenz aus FM-4 Theorem 2.5 (Trägerunabhängigkeit der Tupelfaktorisierung).

---

## Methode reproduzieren (lokal)

Diese Schritte fahren die Mess-Methodik lokal nach — Stack + beide Carrier +
Conformance-Vektoren. Sinn: die Methode mit eigenen Augen prüfen, nicht eine
produktive Audit-Pipeline aufsetzen.

```bash
cd sild_monitoring_stack
docker compose up -d
sleep 30

open http://localhost:3000   # Grafana-Dashboard (anonymer Zugriff)
open http://localhost:9090   # Prometheus-UI
```

Grafana-Login für Editierrechte: **admin** / **sild-demo**

### Ports

| Port | Dienst |
|---|---|
| 2575 | SILD MLLP-Filter (eingehend HL7v2) |
| 2576 | Mock AION MLLP-Empfänger |
| 8080 | SILD FHIR-Filter (eingehend FHIR R4) |
| 8081 | Mock AION FHIR-Empfänger |
| 9090 | Prometheus |
| 9100 | MLLP-Filter Metriken |
| 9101 | FHIR-Filter Metriken |
| 3000 | Grafana |

> Für die **Anwendung auf eine konkrete Klinik-Schnittstelle**
> (Stichprobe, Pseudonymisierung, signierter Befundbericht) siehe Abschnitt
> „Nutzung & Lizenz" oben — das ist Beratungsleistung, kein Self-Service.

---

## Features

### Erkennung

- **Vier kanonische Verlustmuster** (FM-4 Def. 2.1–2.4): TN, TC, AD, RS
- **HL7v2:** Strukturierter Code-Erkennung via CE/CWE-Analyse (OBR, OBX, ORC, PV1, RXA)
- **FHIR R4:** CodeableConcept-Strukturanalyse, Bundle-Referenz-Auflösbarkeit, Kategorie-basiertes TC
- **DE-Basisprofile (MII/KBV):** ICD-10-GM Diagnosesicherheit, UCUM-Einheiten, ATC-Codes, KVid

### Severity-Komposition (FM-4 §2.4)

`Σ_eff = o_tenant ∘ o_default ∘ Σ_intrinsic` — drei-stufige Override-Hierarchie:

```bash
# Beispiel: Kardiologie-Tenant mit erhöhter Sensitivität
python sild_mllp_filter.py --listen 2575 \
    --severity-config severity_overrides_example.json
```

```json
{
  "default_overrides": [
    {"pattern": "Attribute Dropping", "location_prefix": "OBX/", "severity": "warning"}
  ],
  "tenant_overrides": {
    "KIS-KARDIOLOGIE|KH-NORD": [
      {"pattern": "Reference Severing", "location_prefix": "", "severity": "critical"}
    ]
  }
}
```

Tenant-ID wird automatisch aus `MSH-3|MSH-4` (MLLP) bzw. HTTP-Header `X-Tenant-ID` (FHIR) extrahiert.

### Block-Mechanik (FM-4 §5.2)

| Severity | HL7v2 | FHIR | Audit |
|---|---|---|---|
| CRITICAL | MLLP NAK-AE mit ERR-Segment | HTTP 422 OperationOutcome | FHIR AuditEvent |
| WARNING | Pass-through | Pass-through | FHIR AuditEvent |
| INFO | Pass-through | Pass-through | nur Metrik |

```bash
# Block-Modus aktivieren
docker compose run sild-filter \
    python sild_mllp_filter.py --listen 2575 --mode block-on-critical
```

### Verlust-Budget-Schätzung (FM-4 §4)

Jede Übertragung erhält eine **kategoriale Größenordnungs-Schätzung des Informationsverlusts in Bit** (`B(F) = Σ L(fᵢ)`). Die Bit-Beiträge sind **pro Muster konstant**, **nicht pro Nachricht kalibriert**:

| Pattern | Konstanter Beitrag pro Finding |
|---|---|
| Type Narrowing | log₂(95 000) ≈ 16,5 bit (LOINC-Universum, fix) |
| Temporal Collapse | log₂(60) ≈ 5,9 bit (1 h bei 60 s Auflösung, fix) |
| Attribute Dropping | log₂(16) ≈ 4,0 bit (konservativ, fix) |
| Reference Severing | 24,0 bit (konservativ, fix) |

Diese Werte sind als Vergleichs- und Trendgröße brauchbar, **nicht** als absolute Bit-Quantifizierung. Pro-Nachricht-Kalibrierung (Terminologie-Größe, Feld-Spezifität, Bundle-Kontext) ist offene Arbeit (FM-4 §8.2, [Rfc draft v0.2.md](Rfc%20draft%20v0.2.md) §8.1).

Prometheus-Metrik: `sild_loss_budget_bits_estimate{protocol, message_type}` (Histogram)

### FHIR AuditEvent (FM-4 §5.3)

Jede WARNING/CRITICAL-Finding wird als FM-1-konformes Tupel (t, τ, c, r, m) persistiert:

```json
{
  "resourceType": "AuditEvent",
  "subtype": [{"system": "https://iscad-it.de/fhir/CodeSystem/sild-loss-pattern",
               "code": "Temporal Collapse"}],
  "recorded": "2026-05-24T18:00:00Z",
  "entity": [{"what": {"reference": "Procedure/proc-1"}}]
}
```

### DE-Basisprofile / MII (FM-4 §3.2)

```bash
python sild_fhir_filter.py --listen 8080 --profiles-de
```

Zusätzliche Regeln für den deutschen Versorgungskontext:

- ICD-10-GM ohne Diagnosesicherheit (V/A/Z/G) → Attribute Dropping
- `valueQuantity` ohne UCUM-Einheit → Type Narrowing
- `MedicationAdministration` ohne ATC-Code → Type Narrowing
- `Patient` ohne GKV/PKV-KVid-Identifier → Attribute Dropping

---

## Prometheus-Metriken

Alle Metriken tragen das Label `protocol` (`hl7v2` oder `fhir_r4`):

| Metrik | Typ | Beschreibung |
|---|---|---|
| `sild_messages_total` | Counter | Nachrichten gesamt |
| `sild_losses_total` | Counter | Verlust-Events (pattern, effective_severity, message_type) |
| `sild_forward_decisions_total` | Counter | Weiterleitungsentscheidungen |
| `sild_filter_latency_seconds` | Histogram | Verarbeitungslatenz |
| `sild_active_connections` | Gauge | Aktive Verbindungen |
| `sild_using_real_cairn` | Gauge | 1 wenn ein realer Delegations-Aufruf an `cairn.sild` erfolgt; aktuell stets 0 (Plug-in-Stelle, kein Delegationspfad) |
| `sild_loss_budget_bits_estimate` | Histogram | Kategoriale Größenordnungs-Schätzung des Verlust-Budgets in Bit pro Nachricht (pro Muster konstant, nicht pro Nachricht kalibriert) |

---

## Konfiguration

### Filter-Modi

| Modus | Verhalten |
|---|---|
| `log-only` | Alles durchleiten, Verluste protokollieren (Standard) |
| `block-on-critical` | CRITICAL-Nachrichten blockieren |
| `analyse-only` | Keine Weiterleitung, nur Analyse |

### MLLP NAK-Test (--response-mode)

Der Mock-Empfänger simuliert verschiedene ACK-Antworten für End-to-End-Tests:

```bash
# Immer NAK-AE (testet K-2 MLLP-NAK-ERR-Segment)
python sild_mllp_target.py --listen 2576 --response-mode ae

# Wechselt alle 5 Nachrichten zwischen AA und AE (testet Retry-Logik)
python sild_mllp_target.py --listen 2576 --response-mode flap --flap-n 5
```

### Latenz-Monitoring

```bash
python load_generator.py --target localhost:2575 --rate 2.0 \
    --latency-warn-ms 2.0
# [LoadGen] lat p50=0.45ms p95=0.89ms p99=1.23ms [OK: p99<2.0ms, FM-4 §6]
```

---

## Projektstruktur

```
sild_monitoring_stack/
├── sild_detector.py          sild.core — FM-4 Korollar A.4/A.5
├── sild_mllp_filter.py       sild.v2.rules (HL7v2/MLLP)
├── sild_fhir_filter.py       sild.fhir.rules (FHIR R4/HTTP)
├── sild_fhir_profiles_de.py  sild.fhir.profiles_de (MII/KBV)
├── sild_mllp_target.py       Mock AION MLLP (NAK-Support)
├── sild_fhir_target.py       Mock AION FHIR
├── sild_mllp_sender.py       Manueller HL7-Testsender
├── sild_fhir_sender.py       Manueller FHIR-Testsender
├── load_generator.py         Lastgenerator + p99-Latenz
├── severity_overrides_example.json
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── prometheus/
│   └── prometheus.yml
├── grafana/
│   ├── dashboards/sild_operations.json   (8 Panels)
│   └── provisioning/
├── samples/                  HL7v2-Testdaten (ADT, ORU, RDE)
└── samples_fhir/             FHIR-R4-Bundles (Admission, ICU, Medication)
```

---

## Voraussetzungen

- Docker Engine 20+ und Docker Compose v2
- Freie Ports: 2575, 2576, 8080, 8081, 9090, 9100, 9101, 3000

Die Inline-Engine in `sild_detector.py` ist aktuell die einzige aktive Detektor-Implementierung. Im Quellcode existiert ein vorgehaltener Plug-in-Slot für `cairn.sild.SILDDetector` (Roadmap, FM-2); dieser ist bewusst _nicht_ verkabelt und wird hier deshalb auch nicht als Abhängigkeit empfohlen.

---

## FM-4-Konformität

Implementierungsstand der 15 identifizierten K/M/N-Lücken:

| Priorität | Lücken | Code-Pfad implementiert |
|---|---|---|
| Kritisch (K-1–K-3) | 3 | ✓ 3 |
| Mittel (M-1–M-8) | 8 | ✓ 8 (M-6 als kategoriale Schätzung, siehe `loss_budget_bits_estimate`) |
| Niedrig (N-1–N-4) | 4 | ✓ 4 |

**Automatisierte Verifikation:** Beide Trägerformate sind über getrennte Vektor-Sätze verifiziert:

- **FHIR-Adapter** ([Test Vectors v0.1](SILD%20Conformance%20Test%20Vectors%20v0.1.md), Runner `tests/test_conformance.py`): **23/23** der spezifizierten Vektoren (RFC §9.2, FHIR-Adapter) grün — lokal via pytest.
- **HL7-v2-Adapter** ([Test Vectors v2 v0.1](SILD%20Conformance%20Test%20Vectors%20v2%20v0.1.md), Runner `tests/test_conformance_v2.py`): **21/21** der spezifizierten Vektoren (RFC §9.2, v2-Adapter) grün — lokal via pytest.

Beide Carrier vollabgedeckt im Mindest-Regelsatz (Stand B2). Externe CI-Reproduktion ausstehend; ein CI-Badge wird erst nach einem automatisierten CI-Lauf gesetzt.

Aufruf des Runners:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r tests/requirements.txt
pytest tests/ -v
```

Verbleibende Punkte (FM-4 §8) sind in FM-4 selbst als offene Forschungsfragen
markiert (subadditive Aggregation, empirische Kalibrierung, Cross-Bundle-RS,
StructureDefinition-Validierung).

Vollständige Dokumentation: [PROJEKTBERICHT.md](PROJEKTBERICHT.md) und [KONFORMITAETSBERICHT.md](KONFORMITAETSBERICHT.md).

---

## Lizenz

SILD ist **dual-lizenziert**: **AGPL-3.0-only** (Open Source) **OR Commercial** (ISCaD GmbH).

### Open Source — AGPL-3.0-only

- Frei verwendbar, modifizierbar und weitergabe erlaubt
- Änderungen müssen unter AGPL-3.0 zurückgegeben werden
- Copyleft gilt auch für Netzwerknutzung (SaaS)
- Volltext: [LICENSE](./LICENSE)

### Kommerzielle Lizenz

Für proprietäre Integration, SaaS ohne Copyleft-Verpflichtungen oder OEM-Einbettung:

Kontakt: **friedhelm.matten@iscad-it.de**  
Details: [LICENSE-COMMERCIAL.md](./LICENSE-COMMERCIAL.md)

### SPDX

```
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
```

### Drittkomponenten

Prometheus und Grafana werden als unmodifizierte Container-Images verwendet
(Apache 2.0 bzw. AGPLv3) — nicht von der Dual-Lizenz betroffen.

**Wichtig:** Nicht als Medizinprodukt nach EU MDR 2017/745 zugelassen.
Werkzeug für Datenqualitäts-Monitoring — keine klinische Entscheidungssoftware.

---

## Weitere Dokumente

| Datei | Beschreibung |
|---|---|
| [PROJEKTBERICHT.md](PROJEKTBERICHT.md) | Vollständiger Projektbericht v3.0 |
| [KONFORMITAETSBERICHT.md](KONFORMITAETSBERICHT.md) | FM-4-Konformitätsbericht (alle 15 Lücken) |
| [INHALT.md](INHALT.md) | Dokumentationspaket-Übersicht |
| [Rfc draft v0.2.md](Rfc%20draft%20v0.2.md) | RFC-Entwurf v0.2 (DE) |
| [Rfc draft v0.2_en.md](Rfc%20draft%20v0.2_en.md) | RFC draft v0.2 (EN) |
| [SILD Conformance Test Vectors v0.1.md](SILD%20Conformance%20Test%20Vectors%20v0.1.md) | Konformitätstestfälle v0.1 (FHIR-Adapter) |
| [SILD Conformance Test Vectors v2 v0.1.md](SILD%20Conformance%20Test%20Vectors%20v2%20v0.1.md) | Konformitätstestfälle v2 v0.1 (HL7-v2-Adapter) |
| [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md) | Release Notes v1.0.0 |
| [CHANGELOG.md](CHANGELOG.md) | Änderungshistorie |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Beitragsrichtlinien |

---

## Verwandte Projekte

| Projekt | Beschreibung |
|---|---|
| [CAIRN](https://codeberg.org/iscad/cairn) | FM-2: Clinical Interoperability Reference Architecture (Python) |
| [AION](https://github.com/fmatten/aion) | FM-3: Algebraic Interval Ontology for Clinical Networks · [codeberg.org/iscad/aion](https://codeberg.org/iscad/aion) · [10.5281/zenodo.19553130](https://doi.org/10.5281/zenodo.19553130) |
| [FM-1](https://doi.org/10.5281/zenodo.19205557) | Grundlagen zur wissenschaftlichen Auswertung klinischer Informationen (DOI: 10.5281/zenodo.19205557) |
| [FM-4 Paper v2](https://doi.org/10.5281/zenodo.20391260) | Signal-Loss Inspection at Data-boundaries, Version 2 — AGPL-3.0 OR Commercial (DOI: 10.5281/zenodo.20391260) |
| [SILD auf Codeberg](https://codeberg.org/fmatten/sild) | Mirror dieses Repositories |

**ISCaD GmbH · 30900 Wedemark · `licensing@iscad-it.de`**
