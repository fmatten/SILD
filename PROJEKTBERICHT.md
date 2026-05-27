# Projektbericht: SILD Monitoring Stack
**Version:** 3.0  
**Erstellt:** 2026-05-24 | **Aktualisiert:** 2026-05-24  
**Autor:** Friedhelm Matten / ISCaD GmbH  
**Verzeichnis:** `/home/iscad/SILD`  
**Git-Stand:** `f185c28` (alle Lucken behoben: K-1–K-3, M-1–M-8, N-1–N-4)

---

## 1. Theoretische Grundlagen

### 1.1 FM-1 — Informationsraum fur klinische Daten

**FM-1** (*Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen*,
Friedhelm Matten, März 2026) bildet das formale Fundament des gesamten Softwaresystems.
FM-1 definiert einen **Informationsraum I**, in dem jedes klinische Ereignis `e in I`
durch ein 5-Tupel charakterisiert ist:

| Komponente | Symbol | Bedeutung |
|---|---|---|
| Zeitpunkt / Intervall | `t in T` | Beobachtungszeitraum (Allen-Algebra) |
| Typ-Annotation | `tau in T` | Code aus einer Terminologie (LOINC, SNOMED, ICD) |
| Kontextueller Bezug | `c in C` | Patient, Encounter |
| Relationale Verknupfungen | `r subset R` | Verbindungen zu anderen Ereignissen |
| Modifier | `m in M` | Negation, Sicherheit, Schwere |

**Kernbeitrag FM-1:** Ein mathematisch fundiertes Modell, das klinische Sachverhalte
konsistent, eindeutig und reproduzierbar beschreibt — als Mengen, Zeitintervalle,
Abbildungen und Relationen auf einer gemeinsamen reellen Zeitachse.

### 1.2 FM-4 — SILD: Signal-Loss Inspection at Data-boundaries

**FM-4** (*Signal-Loss Inspection at Data-boundaries*, Friedhelm Matten, ISCaD GmbH,
Mai 2026) ist das unmittelbare theoretische Fundament. FM-4 formalisiert SILD als
**modalitatsneutrale Detektorklasse** fur klinische Cross-System-Ubertragungen,
aufbauend auf dem FM-1-Informationsraum.

#### Die Loss-Pattern-Algebra (FM-4 Abschnitt 2)

Sei `sigma: I -> I'` eine Sender-Reprasentation, `rho: I' -> I''` ein Mapping-Schritt.
Die vier kanonischen Verlustmuster sind **Endo-Operatoren** auf dem Informationsraum:

**Definition 2.1 — Type Narrowing (TN):**
> Es existiert `tau* in T` mit `tau* >= tau(e)` und `tau* > tau(e'')`
> (Subsumtion in der Terminologie-Ordnung)

*Konkret:* LOINC-Code -> Freitext; `CodeableConcept.coding` fallt zugunsten von `.text` weg.

**Definition 2.2 — Temporal Collapse (TC):**
> `dim t(e) > dim t(e'')` (Intervall [t1,t2] kollabiert zu Zeitpunkt t*)

*Konkret:* `effectivePeriod` wird zu `effectiveDateTime`; `Timing.repeat` zu einem
einzelnen `occurrenceDateTime` reduziert; Allen-Relationen (before/meets/overlaps)
gehen verloren.

**Definition 2.3 — Attribute Dropping (AD):**
> Es existiert `mi` mit `mi in m(e)` und `mi not in m(e'')`

*Konkret:* `modifierExtension` wird leer; `meta.security` verschwindet;
`Observation.value[x]` fehlt ohne `dataAbsentReason`.

**Definition 2.4 — Reference Severing (RS):**
> Verknupfung `ri in r(e)` in `e''` formal vorhanden, aber nicht auflosbar
> (phi(r'i) in I'' ist leer)

*Konkret:* `Reference` ohne auflosbares `Bundle.entry.fullUrl`; `#anchor`
ohne `contained[]`-Eintrag.

#### Hauptsatz (Vollstandigkeit, Satz 2.5)
> Jede verlustbehaftete Ubertragung liegt in `TN union TC union AD union RS`.

**Bedeutung:** Die vier Muster sind *vollstandig* — jeder semantische
Informationsverlust lasst sich auf genau eines zuruckfuhren. Korollar A.4:
Der `LossPattern`-Enum ist nicht erweiterungsbedurftig.

#### Adapter-Architektur (FM-4 Abschnitt 3)

| FM-4-Modul | Implementierung | Aufgabe |
|---|---|---|
| `sild.core` | `sild_detector.py` | Tragerunabhangige Muster + Datenklassen |
| `sild.v2.rules` | `sild_mllp_filter.py` | HL7v2-Segmentpfade und -Pradikate |
| `sild.fhir.rules` | `sild_fhir_filter.py` | FHIR-R4-Ressourcenpfade und -Pradikate |
| `sild.fhir.profiles_de` | `sild_fhir_profiles_de.py` | MII/KBV DE-Basisprofile |

> Der `core`-Layer ist zwischen v2- und FHIR-Sibling **byte-identisch** —
> direkte Konsequenz aus Theorem 2.5 (Tragerunabhangigkeit).

#### Quantitative Verlust-Metrik (FM-4 Abschnitt 4)

| Pattern | Formel | Standardwert |
|---|---|---|
| TN: Code -> Text | `L_TN = log2(|T|)` | LOINC: ~16,5 bit |
| TC: Intervall -> Punkt | `L_TC = log2(Delta_t / delta)` | 1h@60s: ~5,9 bit |
| AD: Modifier verloren | `L_AD = log2(|Mi|)` | konservativ: 4,0 bit |
| RS: Referenz unauflosbar | `L_RS approx 24 bit` | konservativ |

Verlust-Budget einer Ubertragung: `B(F) = sum L(fi)`

#### Operative Aspekte (FM-4 Abschnitt 5)

**Sentinel-Position:** Am Ubertragungspunkt — der einzige Ort, an dem beide
Seiten gleichzeitig sichtbar sind.

**Block-Mechanik** (dreistufig):
- `CRITICAL` -> HTTP 422 (FHIR) / MLLP-NAK-AE mit ERR-Segment (v2)
- `WARNING` -> Pass-through + Audit (FHIR AuditEvent als FM-1-Tupel)
- `INFO` -> nur Metric-Counter, kein Audit-Eintrag

**Severity-Komposition:** `Sigma_eff = o_tenant o o_default o Sigma_intrinsic`  
Override andert nur die operative Konsequenz, nie die Detektion selbst.

**Verhaltnis zu AION/CAIRN:** SILD verhalt sich wie ein Linter zu einem Compiler —
AION/CAIRN modellieren was Information *bedeutet*, SILD prufft ob sie unterwegs
*intakt bleibt*.

---

## 2. Projektzusammenfassung

**SILD** (Semantic Information Loss Detection) ist ein Live-Monitoring-Stack zur
Erkennung und Visualisierung von semantischem Datenverlust beim klinischen
Datenaustausch. Die Software ist die **direkte operative Umsetzung von FM-4**,
aufbauend auf dem formalen Informationsraum aus FM-1.

Zwei parallele Ubertragungspfade werden uberwacht:
- **HL7v2 / MLLP** — Legacy-Protokoll (binares Ubertragungsprotokoll)
- **FHIR R4 / HTTP** — Moderner REST-basierter Gesundheitsdatenstandard

> **Rechtlicher Hinweis:** Nicht als Medizinprodukt nach EU MDR 2017/745 zugelassen.

---

## 3. Implementierungs-Ubersicht (aktueller Stand)

### 3.1 FM-4 Def. 2.1–2.4 -> sild_detector.py

| FM-4 | Implementierung | Verbesserungen (v3.0) |
|---|---|---|
| Def. 2.1 TN | `_hl7_ce_structured()`: code^display^system | K-1: Terminologie-Strukturerkennung statt Keywords |
| Def. 2.1 TN | `_fhir_cc_narrowing()`: text-only / kein spez. System | K-1: CodeableConcept-Analyse |
| Def. 2.2 TC | OBR-7 != OBR-8; `effectivePeriod` vs `effectiveDateTime` | M-2: Kategorie-basiert + alle Prozeduren |
| Def. 2.3 AD | OBX-2 Value-Type-Prufung; `dosage`, `method`, `device` | M-1: NM/NA/SN/NR vs TX/FT/ST |
| Def. 2.4 RS | Bundle-Referenz-Auflosbarkeit: `_build_resolvable_refs()` | M-3: vorhanden-unauflosbar vs fehlend |
| Def. 2.4 RS | ORC-2: Severity info (potenziell unauflosbar) | N-1: kein bestatigtes RS |
| §2.4 Severity | `SeverityOverrideConfig`: o_tenant o o_default o Sigma_i | K-3: vollstandige Komposition |
| §4.1 Budget | `LOSS_BITS_PER_PATTERN`, `compute_loss_budget_bits()` | M-6: neu |
| §5.3 Audit | `fhir_audit_events_from_report()` FM-1-Tupel | M-5: neu |

### 3.2 FM-4 Adapter-Architektur -> Modulstruktur

| FM-4 | Datei | Port MLLP/HTTP | Metriken-Port |
|---|---|---|---|
| `sild.core` | `sild_detector.py` | — | — |
| `sild.v2.rules` | `sild_mllp_filter.py` | 2575 | 9100 |
| `sild.fhir.rules` | `sild_fhir_filter.py` | 8080 | 9101 |
| `sild.fhir.profiles_de` | `sild_fhir_profiles_de.py` | (via FHIR-Filter) | — |

### 3.3 Block-Mechanik und Audit

| FM-4 §5 | Implementierung | Status |
|---|---|---|
| CRITICAL -> MLLP-NAK-AE | `make_ack(code='AE')` mit ERR-Segment | K-2 behoben |
| CRITICAL -> HTTP 422 | `OperationOutcome business-rule` | Korrekt |
| WARNING -> Audit | JSONL + `"audit_events": [AuditEvent, ...]` | M-5 behoben |
| INFO -> kein Audit | `should_audit`-Check | M-4/K-3 behoben |
| Sigma_eff Komposition | `apply_severity_overrides(report, cfg, tenant_id)` | K-3 behoben |
| Tenant-ID (MLLP) | `MSH-3|MSH-4` | K-3 behoben |
| Tenant-ID (FHIR) | HTTP-Header `X-Tenant-ID` | K-3 behoben |

---

## 4. Projektstruktur

```
SILD/
|-- FM-1 (DOI: 10.5281/zenodo.19205557)    Formale Grundlagen (Informationsraum)
|-- FM-4 v2 (DOI: 10.5281/zenodo.20391260) SILD-Theorie (Loss-Pattern-Algebra)
|-- PROJEKTBERICHT.md                      Dieser Bericht
|-- KONFORMITAETSBERICHT.md                Detaillierte Luckenanalyse
|
|-- [veraltet — v2-Varianten]
|   |-- sild_fhir_sender/filter/target.py
|   |-- docker-compose-v2.yml / Dockerfile-v2
|
+-- sild_monitoring_stack/             AKTUELLER PRODUKTIVER STACK
    |-- docker-compose.yml             7 Services
    |-- Dockerfile                     Python 3.11 Slim
    |-- requirements.txt               prometheus_client>=0.19.0
    |-- README.md
    |
    |-- sild_detector.py               sild.core — tragerunabhangig
    |-- sild_mllp_filter.py            sild.v2.rules (Port 2575/9100)
    |-- sild_fhir_filter.py            sild.fhir.rules (Port 8080/9101)
    |-- sild_fhir_profiles_de.py       sild.fhir.profiles_de (NEU, M-8)
    |-- severity_overrides_example.json  Beispiel-Override-Konfiguration (NEU, K-3)
    |
    |-- sild_mllp_target.py            Mock AION MLLP-Empfanger (--response-mode, N-2)
    |-- sild_mllp_sender.py            Manueller HL7-Testsender
    |-- sild_fhir_target.py            Mock FHIR-Empfanger (ResourceType/id, N-3)
    |-- sild_fhir_sender.py            FHIR HTTP-Sender
    |-- load_generator.py              HL7-Lastgenerator + p99-Latenz (M-7)
    |
    |-- samples/                       3 realistische HL7v2-Nachrichten
    |   |-- adt_a01_admission.hl7
    |   |-- oru_r01_sepsis.hl7
    |   +-- rde_o11_propofol.hl7
    |
    |-- samples_fhir/                  3 FHIR R4 Bundles
    |   |-- admission_clean_bundle.json
    |   |-- icu_demo_bundle.json
    |   +-- medication_critical_bundle.json
    |
    |-- prometheus/
    |   +-- prometheus.yml             Scrape-Config (5s Intervall, 2 Jobs)
    +-- grafana/
        |-- provisioning/              Auto-Provisioning Datasource + Dashboard
        +-- dashboards/
            +-- sild_operations.json  8-Panel Echtzeit-Dashboard
```

---

## 5. Verwendete Technologien

| Technologie | Version | Zweck |
|---|---|---|
| Python | 3.11 (slim) | Alle Filter, Sender, Generatoren |
| MLLP | HL7v2-Standard | Binares Ubertragungsprotokoll |
| FHIR R4 | HTTP/REST | Moderner Healthcare-Datenstandard |
| HL7 v2.5.1 | Legacy | Legacy-Krankenhaus-Datenformat |
| ICD-10-GM | DE-Basisprofile | Diagnosekodierung (MII/KBV) |
| Prometheus | latest | Metriken-Sammlung (5s Scrape-Intervall) |
| Grafana | latest | Echtzeit-Visualisierung |
| Docker Compose v2 | — | Container-Orchestrierung |
| prometheus_client | >=0.19.0 | Python-Exporter fur Prometheus |

---

## 6. Architektur & Services

### 6.1 Datenfluss

```
KIS / Testsender
      |
      +--- HL7v2/MLLP ----> sild-filter :2575 -----> aion-mock :2576
      |                     sild.v2.rules             (Zielsystem)
      |                     Metrics: :9100
      |                     Severity-Config: --severity-config
      |                     Tenant-ID: MSH-3|MSH-4
      |
      +--- FHIR R4/HTTP --> sild-fhir-filter :8080 -> aion-fhir-mock :8081
                            sild.fhir.rules            (Zielsystem)
                            + sild.fhir.profiles_de    (via --profiles-de)
                            Metrics: :9101
                            Tenant-ID: X-Tenant-ID

Beide Filter --> Prometheus :9090 --> Grafana :3000
```

### 6.2 Die 7 Docker Services

| Service | Port(s) | FM-4-Entsprechung |
|---|---|---|
| aion-mock | 2576 | Empfangendes System (HL7v2) |
| aion-fhir-mock | 8081 | Empfangendes System (FHIR) |
| sild-filter | 2575, 9100 | Sentinel-Position v2 (FM-4 §5.1) |
| sild-fhir-filter | 8080, 9101 | Sentinel-Position FHIR (FM-4 §5.1) |
| load-generator | — | Testlast HL7v2 (1,5/s) + Latenz-Messung |
| fhir-load-generator | — | Testlast FHIR (1,0/s) |
| prometheus | 9090 | Metriken-Aggregation |
| grafana | 3000 | Dashboard-Visualisierung |

### 6.3 Filter-Modi (FM-4 Block-Mechanik)

| Modus | FM-4-Pfad | Verhalten |
|---|---|---|
| `log-only` | WARNING | Alles durchleiten, Verluste protokollieren |
| `block-on-critical` | CRITICAL | MLLP-NAK-AE / HTTP 422 bei critical findings |
| `analyse-only` | INFO | Keine Weiterleitung, nur Analyse |

---

## 7. SILD-Verlustmuster (aktueller Detektionsstand)

### 7.1 HL7v2-Trigger-Punkte

| Segment | Pattern | Pruflogik | Severity |
|---|---|---|---|
| OBR-4 | TN | code^display^system vorhanden (K-1) | info |
| OBR-7/8 | TC | OBR-7 != OBR-8 (Intervall) | warning |
| OBX (NM/NA/SN/NR) | AD | OBX-15/16 fehlen bei Geratemessung (M-1) | info |
| ORC-2 | RS | Placer Order Number: potenziell unauflosbar (N-1) | info |
| PV1-19 | RS | Visit Number ohne Encounter-Mapping | warning |
| RXA-6/7 | AD | Fehlende Dosis oder Einheit | critical |

### 7.2 FHIR R4-Trigger-Punkte (Basis-Analyse)

| Ressource | Pattern | Pruflogik | Severity |
|---|---|---|---|
| Observation.code | TN | text-only / kein FHIR_SPECIFIC_SYSTEMS (K-1) | info |
| Observation | TC | Kategorie procedure/survey + effectiveDateTime (M-2) | warning |
| Observation.encounter | RS | Referenz nicht im Bundle auflosbar (M-3) | warning |
| Observation.encounter | RS | Kein encounter-Feld (M-3) | info |
| Observation (labor) | AD | Keine method/device | info |
| Procedure | TC | performedDateTime statt performedPeriod (M-2) | warning |
| Procedure (kontinuierl.) | TC | Bekannte Codes: monitoring/infusion | critical |
| MedicationAdministration | AD | Kein dosage | critical |
| Condition.encounter | RS | Referenz-Auflosbarkeit (M-3) | warning/info |

### 7.3 DE-Basisprofile MII/KBV (sild.fhir.profiles_de, M-8)

| Ressource | Regel | Pruflogik | Pattern | Severity |
|---|---|---|---|---|
| Condition | DE-1 | ICD-10-GM ohne Diagnosesicherheit (V/A/Z/G) | AD | warning |
| Observation | DE-2 | valueQuantity ohne UCUM-Einheit | TN | info |
| MedicationAdministration | DE-3 | Kein ATC-Code | TN | info |
| Patient | DE-4 | Kein GKV/PKV-KVid-Identifier | AD | info |

---

## 8. Prometheus-Metriken

Alle Metriken tragen das Label `protocol` (hl7v2 oder fhir_r4):

| Metrik | Typ | Beschreibung | Neu? |
|---|---|---|---|
| `sild_messages_total` | Counter | Nachrichten gesamt (Typ, ACK-Code) | — |
| `sild_losses_total` | Counter | Verlustzahler (Pattern, effective_severity, Typ) | — |
| `sild_forward_decisions_total` | Counter | Weiterleitungsentscheidungen | — |
| `sild_filter_latency_seconds` | Histogram | Verarbeitungslatenz p50/p95/p99 | — |
| `sild_active_connections` | Gauge | Aktive MLLP/HTTP-Verbindungen | — |
| `sild_using_real_cairn` | Gauge | 1 wenn CAIRN-Paket verfugbar | — |
| `sild_loss_budget_bits` | Histogram | Verlust-Budget in Bit pro Nachricht (FM-4 §4.1) | NEU M-6 |

Buckets `sild_loss_budget_bits`: (10, 20, 40, 80, 160, 320, 640) bit

---

## 9. Grafana Dashboard

8 Panels in `sild_operations.json`:

| Panel | Typ | Inhalt |
|---|---|---|
| Nachrichten gesamt | Stat | Counter gesamt |
| Loss-Ereignisse | Stat (Schwellwert) | Verlustzahler |
| Critical-Befunde | Stat (rot) | Nur CRITICAL |
| Latenz P95 | Stat | Histogramm-Auswertung |
| Nachrichten-Rate | Time-Series | Pro Nachrichtentyp |
| Loss-Rate | Time-Series (gestapelt) | Pro Pattern |
| Latenz P50/P95/P99 | Time-Series | Perzentilvergleich |
| Forward-Entscheidungen | Donut | forwarded/blocked/forward-failed |

Refresh: 5s — Zeitbereich: letzte 15 Minuten — Zugangsdaten: admin/sild-demo

---

## 10. Schnellstart

### Standardbetrieb

```bash
cd /home/iscad/SILD/sild_monitoring_stack
docker compose up -d
sleep 30
# Grafana:    http://localhost:3000
# Prometheus: http://localhost:9090
# Metriken:   curl http://localhost:9100/metrics
```

### Mit Severity-Overrides (K-3)

```bash
# Beispiel-Config verwenden (severity_overrides_example.json)
python sild_mllp_filter.py --listen 2575 --mode block-on-critical \
    --severity-config severity_overrides_example.json

# Header fur Tenant-ID (FHIR)
curl -X POST http://localhost:8080/fhir/Bundle \
    -H "X-Tenant-ID: KIS-KARDIOLOGIE|KH-NORD" \
    -H "Content-Type: application/fhir+json" \
    -d @samples_fhir/icu_demo_bundle.json
```

### Mit DE-Basisprofilen (M-8)

```bash
python sild_fhir_filter.py --listen 8080 --mode log-only \
    --profiles-de --metrics-port 9101
```

### Latenz-Monitoring (M-7)

```bash
python load_generator.py --target localhost:2575 --rate 2.0 \
    --latency-warn-ms 2.0
# Ausgabe alle 5s:
# [LoadGen] sent=100 accepted=97 rejected=3 errors=0
#   lat p50=0.45ms p95=0.89ms p99=1.23ms [OK: p99<2.0ms, FM-4 §6]
```

### NAK-End-to-End-Test (N-2)

```bash
# Mock im AE-Modus starten (testet K-2-Verhalten des SILD-Filters)
python sild_mllp_target.py --listen 2576 --response-mode ae

# Oder: Wechsel zwischen AA und AE alle 5 Nachrichten
python sild_mllp_target.py --listen 2576 --response-mode flap --flap-n 5
```

---

## 11. FM-4-Konformitatsanalyse (aktueller Stand)

### 11.1 Vollstandig implementiert

| FM-4-Anforderung | Status | Commit |
|---|---|---|
| Def. 2.1 TN: Terminologie-Strukturerkennung | Konform | K-1 |
| Def. 2.2 TC: Allen-Algebra / Kategorie-basiert | Konform | M-2 |
| Def. 2.3 AD: Value-Type-basierte Prufung | Konform | M-1 |
| Def. 2.4 RS: Bundle-Referenz-Auflosbarkeit | Konform | M-3 |
| Def. 2.4 RS: ORC-2 korrekte Severity (info) | Konform | N-1 |
| §2.4 Severity-Komposition (3 Ebenen) | Konform | K-3 |
| Korollar A.4 LossPattern (4 Werte) | Konform | — |
| Korollar A.5 core-Layer Tragerunabhangigkeit | Konform | — |
| §3.2 DE-Basisprofile sild.fhir.profiles_de | Konform | M-8 |
| §4.1 Entropie-Schatzwerte (Bit-Budget) | Konform | M-6 |
| §5.1 Sentinel-Position | Konform | — |
| §5.2 MLLP-NAK-AE mit ERR-Segment | Konform | K-2 |
| §5.2 HTTP 422 bei FHIR CRITICAL | Konform | — |
| §5.2 Audit-Selektivitat (INFO kein Eintrag) | Konform | M-4/K-3 |
| §5.3 FHIR AuditEvent als FM-1-Tupel | Konform | M-5 |
| §6 Performance p99 < 2ms (Monitoring) | Konform | M-7 |

### 11.2 Nicht implementiert (FM-4 §8 — selbst als offen markiert)

Diese Punkte sind in FM-4 §8 als zukunftige Forschungsfragen gekennzeichnet,
nicht als Implementierungsanforderungen:

| FM-4 §8 | Beschreibung |
|---|---|
| §8.1 Subadditive Aggregation | Mehrfachverluste auf gleicher Komponente |
| §8.2 Empirische Kalibrierung | Bit-Schatzwerte gegen reale v2-zu-FHIR-Mappings |
| §8.3 Cross-Bundle RS | Referenzen uber mehrere Bundles |
| §8.4 StructureDefinition-Detektor | FHIR-Profile als Detektor-Klasse |

### 11.3 Technische Schulden (Demo-Infrastruktur)

| Punkt | Datei | Status |
|---|---|---|
| ~~ORC-2 RS-Semantik~~ | ~~`sild_detector.py`~~ | **[BEHOBEN N-1]** Severity info, "potenziell unauflosbar" |
| ~~Mock MLLP-Target kein NAK~~ | ~~`sild_mllp_target.py`~~ | **[BEHOBEN N-2]** `--response-mode aa\|ae\|ar\|flap` |
| ~~Mock FHIR-Target Location~~ | ~~`sild_fhir_target.py`~~ | **[BEHOBEN N-3]** `ResourceType/id` Format |
| ~~CAIRN in requirements.txt~~ | ~~`requirements.txt`~~ | **[BEHOBEN N-4]** Als optional dokumentiert |
| TLS/mTLS auf MLLP | `sild_mllp_filter.py` | Fur Produktionsbetrieb notig |

---

## 12. Code-Qualitat (aktueller Stand)

### Starken

- **FM-4-Konformitat:** Alle kritischen (K-1–K-3), mittleren (M-1–M-8) und
  niedrigen (N-1–N-4) Lucken aus der initialen Analyse behoben
- **Terminologische Korrektheit:** Type Narrowing erkennt strukturierte Codes
  (code^display^system) und text-only CodeableConcept korrekt nach Def. 2.1
- **Bundle-Semantik:** Reference Severing pruft tatsachliche Auflosbarkeit
  im Bundle (M-3), nicht nur Feldbwesenheit
- **RS-Semantik:** ORC-2 korrekt als potenzielles RS (info) statt bestatigtes RS (N-1)
- **Audit-Qualitat:** FHIR AuditEvent als FM-1-Tupel (M-5); Selektivitat nach
  FM-4 §5.2 (INFO kein Audit-Eintrag)
- **Mandantenfahigkeit:** Vollstandige 3-Ebenen-Severity-Komposition (K-3)
- **Quantifizierbar:** Verlust-Budget in Bit (M-6) und Latenz-Monitoring (M-7)
- **DE-Erweiterbar:** `sild_fhir_profiles_de.py` als eigenstandiger Adapter (M-8)
- **Testbar:** Mock-Targets mit NAK-Support (N-2) und validen FHIR-Locations (N-3)

### Verbleibende Verbesserungsfelder

- **CAIRN-Integration:** Inline-Detector ist Fallback; produktive Accuracy
  erfordert das CAIRN Python-Paket (FM-2)
- **TLS:** Kein TLS/mTLS auf MLLP (klinischer Standard fur Produktionsbetrieb)
- **Retry-Logik:** Kein Exponential Backoff bei Forward-Fehlern
- **Tests:** Keine formalen Unit-Tests (manuelle Verifikation via Load-Generator)
- **FHIR R5:** Nur R4 implementiert (FM-4 Versionskompatibilitat als Subfunktor)

---

## 13. Literatur und Quellen

| Dokument | Titel | Datum |
|---|---|---|
| FM-1 | Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen | Marz 2026, Zenodo (DOI: 10.5281/zenodo.19205557) |
| FM-2 / CAIRN | Clinical Interoperability Reference Architecture | 2026, codeberg.org/iscad/cairn |
| FM-3 / AION | Algebraic Interval Ontology for Clinical Networks | 2026, Zenodo (DOI: 10.5281/zenodo.19553130) |
| FM-4 v2 | Signal-Loss Inspection at Data-boundaries | Mai 2026, Zenodo (DOI: 10.5281/zenodo.20391260) |
| Allen (1983) | Maintaining knowledge about temporal intervals | CACM 26(11) |

---

## 14. Metadaten

| Feld | Wert |
|---|---|
| Lizenz | AGPL-3.0-only OR LicenseRef-ISCaD-Commercial |
| Repository | codeberg.org/fmatten/sild |
| Autor | ISCaD GmbH, 30900 Wedemark |
| Kontakt | licensing@iscad-it.de |
| Theory DOI | 10.5281/zenodo.20391260 |

---

*Erstellt: 2026-05-24 | Aktualisiert: 2026-05-24 (v3.0)*  
*Grundlage: FM-1 und FM-4, Friedhelm Matten / ISCaD GmbH*
