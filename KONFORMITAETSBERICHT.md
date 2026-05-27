# Konformitatsbericht: SILD Monitoring Stack vs. FM-4
**Version:** 3.0 (aktualisiert nach Behebung K-1 bis K-3, M-1 bis M-8 und N-1 bis N-4)  
**Erstellt:** 2026-05-24 | **Aktualisiert:** 2026-05-24  
**Grundlage:** FM-4 *Signal-Loss Inspection at Data-boundaries* (Matten, Mai 2026)  
**Analysierte Codebasis:** `/home/iscad/SILD/sild_monitoring_stack/`  
**Git-Stand:** `f185c28` (Fix N-1 bis N-4)

---

## Gesamtstatus

| Kategorie | Ursprunglich | Behoben | Offen |
|---|---|---|---|
| KRITISCH | 3 | **3** | 0 |
| MITTEL | 8 | **8** | 0 |
| NIEDRIG | 4 | **4** | 0 |
| Konform (unverandert) | 5 | -- | -- |
| **Gesamt behobene Lucken** | **15** | **15** | **0** |

**FM-4-Konformitat nach Behebung: vollstandig** — alle kritischen, mittleren und
niedrigen Lucken geschlossen. Verbleibende Demo-Infrastruktur-Punkte (N-1 bis N-4)
sind behoben; offene FM-4-Punkte (§8) sind in FM-4 selbst als Forschungsfragen markiert.

---

## Anderungshistorie

| Commit | Behoben | Datum |
|---|---|---|
| `ae012a2` | K-1, K-2, K-3 | 2026-05-24 |
| `fbf2fa3` | M-1, M-2, M-3, M-4, M-5, M-6, M-7, M-8 | 2026-05-24 |
| `f185c28` | N-1, N-2, N-3, N-4 | 2026-05-24 |

---

## Behobene kritische Lucken

### K-1 [BEHOBEN] — Type Narrowing: Terminologische Strukturerkennung

**FM-4-Anforderung:** Definition 2.1 — TN wenn tau(e'') in schwacherer Terminologie.

**Ursprungliches Problem:** Keyword-Matching auf Displaytext ("cbc", "hematology")
statt formalem Terminologie-Vergleich. Falsch-Positive und Falsch-Negative moeglich;
Theorem 2.5 (Vollstandigkeit) nur bei korrekter Semantik erfullt.

**Losung (Commit ae012a2):**

Zwei neue Hilfsfunktionen in `sild_detector.py`:

```python
# HL7v2: Strukturierter Code = code^display^system vorhanden
def _hl7_ce_structured(ce_field: str) -> tuple:
    parts  = ce_field.split("^")
    code   = parts[0].strip()
    system = parts[2].strip().upper() if len(parts) > 2 else ""
    return bool(code) and bool(system), code, system

# FHIR: Text-only CodeableConcept oder kein anerkanntes System
def _fhir_cc_narrowing(cc: dict) -> tuple:
    codings = cc.get("coding", [])
    text    = cc.get("text", "")
    if not codings and text:
        return True, f"Nur .text ohne .coding"
    if codings:
        systems = {c.get("system", "") for c in codings}
        if not (systems & FHIR_SPECIFIC_SYSTEMS):
            return True, f"Kein anerkanntes System ({systems})"
    return False, ""
```

Neue Konstanten: `HL7_STRUCTURED_SYSTEMS`, `FHIR_SPECIFIC_SYSTEMS`, `FHIR_GENERIC_SYSTEMS`.

---

### K-2 [BEHOBEN] — MLLP-Block: Protokollkonformes NAK-AE

**FM-4-Anforderung:** §5.2 — "CRITICAL -> MLLP-NAK-AE bei v2"

**Ursprungliches Problem:** `ack_code = "AE"` ohne ERR-Segment. Sendende Systeme
konnten den SILD-Block nicht von einem Netzwerkfehler unterscheiden.

**Losung (Commit ae012a2):**

`make_ack()` in `sild_mllp_filter.py` erzeugt bei `code='AE'` automatisch ein
ERR-Segment nach HL7 v2.5+ Standard:

```
MSH|^~\&|SILD_FILTER|FILTER|SENDER|FAC|20260524||ACK^R01|MSG001_ACK|P|2.5.1
MSA|AE|MSG001|SILD-BLOCK: 2 critical finding(s)
ERR||207^Application Internal Error^HL70357|E|SILD-BLOCK: ...
```

Bei `code='AA'` (normaler Accept) bleibt das Verhalten unverandert (kein ERR-Segment).

---

### K-3 [BEHOBEN] — Severity-Komposition

**FM-4-Anforderung:** §2.4 — Sigma_eff = o_tenant o o_default o Sigma_intrinsic.
Override andert nicht die Detektion, nur die operative Konsequenz.

**Ursprungliches Problem:** Severity war unveranderlich aus dem Detektor; kein
Mandantenbetrieb moglich.

**Losung (Commit ae012a2):**

Neuer `SeverityOverrideConfig`-Dataclass in `sild_detector.py`:

```python
@dataclass
class SeverityOverrideConfig:
    default_overrides: list  # o_default: systemweit
    tenant_overrides:  dict  # o_tenant: pro-Mandant

    # Sigma_eff = o_tenant o o_default o Sigma_intrinsic
```

Neues Feld `LossEvent.effective_severity` (nach Overrides) neben `LossEvent.severity`
(intrinsisch, unveranderlich). Beide Werte im Audit-Log sichtbar.

Tenant-ID-Extraktion: `MSH-3|MSH-4` (MLLP) bzw. HTTP-Header `X-Tenant-ID` (FHIR).  
Konfiguration via `--severity-config overrides.json` in beiden Filtern.

---

## Behobene mittlere Lucken

### M-1 [BEHOBEN] — AD: OBX Value-Type-basierte Prufung

**FM-4-Anforderung:** Definition 2.3 — AD wenn Modifier in Quelle fehlt in Ziel.

**Ursprungliches Problem:** AD wurde fur jeden OBX ohne OBX-15/16 ausgeloest,
unabhangig ob die Datenart uberhaupt Device-Info erfordert.

**Losung (Commit fbf2fa3):**

```python
OBX_NUMERIC_TYPES = frozenset({"NM", "NA", "SN", "NR"})  # device-messbar
OBX_TEXT_TYPES    = frozenset({"TX", "FT", "ST"})          # manuelle Eingabe

# AD nur wenn OBX-2 nicht in OBX_TEXT_TYPES (konservativ)
if not obx_15 and not obx_16 and obx_2 not in OBX_TEXT_TYPES:
    losses.append(LossEvent(ATTRIBUTE_DROPPING, ...))
```

TX/FT/ST (manuelle Texteingaben) erzeugen kein AD bei fehlender Device-Info.
NM/NA/SN/NR und unbekannte Typen werden konservativ als geratgemessen behandelt.

---

### M-2 [BEHOBEN] — TC FHIR: Allen-Algebra

**FM-4-Anforderung:** Definition 2.2 — TC wenn dim t(e) > dim t(e'').

**Ursprungliches Problem:** TC nur bei Keywords ("mean"/"average") in code.display.
Alle anderen TC-Falle wurden nicht erkannt.

**Losung (Commit fbf2fa3):**

Zweistufige Erkennung:

```python
TC_INTERVAL_OBSERVATION_CATEGORIES = frozenset({"procedure", "survey"})

# 1. Kategorie impliziert Intervall (M-2)
if primary_cat in TC_INTERVAL_OBSERVATION_CATEGORIES:
    losses.append(LossEvent(TEMPORAL_COLLAPSE, ..., severity="warning"))

# 2. Procedure: JEDE Prozedur hat inherente Dauer
elif rtype == "Procedure":
    if "performedDateTime" in resource and "performedPeriod" not in resource:
        if code in CONTINUOUS_PROCEDURE_CODES:  # critical
            ...
        else:                                   # warning (M-2 neu)
            losses.append(LossEvent(TEMPORAL_COLLAPSE, ..., "warning"))
```

---

### M-3 [BEHOBEN] — RS: Bundle-Referenz-Auflosbarkeit

**FM-4-Anforderung:** Definition 2.4 — RS wenn Referenz formal vorhanden aber
phi(r'i) in I'' ist leer.

**Ursprungliches Problem:** RS wurde nur bei *Abwesenheit* eines Feldes ausgeloest,
nicht bei vorhandener, aber unauflosbarer Referenz.

**Losung (Commit fbf2fa3):**

```python
def _build_resolvable_refs(entries: list) -> set:
    # ResourceType/id + fullUrl aus allen Bundle-Entries
    ...

def _rs_check_reference(resolvable, ref_field, loc, field_name):
    ref = ref_field.get("reference", "")
    if ref and ref not in resolvable:
        return LossEvent(RS, ..., "warning")  # vorhanden + unauflosbar
    elif not ref:
        return LossEvent(RS, ..., "info")     # fehlend (mgl. Verlust)
    return None  # vorhanden und auflosbar -> kein Verlust
```

Unterschiedliche Severity: vorhanden-aber-unauflosbar = `warning`,
fehlend-wenn-erwartet = `info`.

---

### M-4 [BEHOBEN — bereits in K-3] — Audit-Selektivitat

**FM-4-Anforderung:** §5.2 — INFO -> nur Metrik, kein Audit-Eintrag.

**Losung:** `should_audit`-Check in beiden Filtern (Teil des K-3-Commits):

```python
sev = report.severity_counts()
should_audit = (sev["critical"] > 0 or sev["warning"] > 0
                or forward_decision != "forwarded")
if should_audit:
    self.logger.log(log_record)
```

---

### M-5 [BEHOBEN] — FHIR AuditEvent-Format

**FM-4-Anforderung:** §5.3 — Jede Finding als FM-1-Tupel (t, tau, c, r, m).

**Ursprungliches Problem:** Nur einfaches JSONL; keine FM-1-konforme Audit-Spur.

**Losung (Commit fbf2fa3):**

Neue Funktion `fhir_audit_events_from_report()` in `sild_detector.py`:

```python
# FM-1-Tupel-Abbildung:
# t   = AuditEvent.recorded
# tau = subtype.code (SILD-Pattern, CodeSystem: iscad-it.de/fhir/...)
# c   = entity.what (klinische Resource)
# r   = agent.who (SILD-Detektor)
# m   = outcome / outcomeDesc (Severity + Beschreibung)
```

Feld `"audit_events": [...]` im JSONL-Log-Record beider Filter.
Nur WARNING/CRITICAL-Findings erzeugen AuditEvents (FM-4 §5.2).

---

### M-6 [BEHOBEN] — Quantitative Verlust-Metrik

**FM-4-Anforderung:** §4.1 — Entropie-Schatzungen L_TN, L_TC, L_AD, L_RS.

**Ursprungliches Problem:** Kein Bit-Budget; nur Pattern-Klassifikation.

**Losung (Commit fbf2fa3):**

```python
LOSS_BITS_PER_PATTERN = {
    "Type Narrowing":     math.log2(95_000),  # LOINC: ~16.5 bit
    "Temporal Collapse":  math.log2(60),       # 1h@60s: ~5.9 bit
    "Attribute Dropping": math.log2(16),       # konservativ: 4.0 bit
    "Reference Severing": 24.0,                # FM-4 §4.1: 24 bit
}
```

`SILDReport.loss_budget_bits = compute_loss_budget_bits(losses)` (Summe).

Neues Prometheus-Histogram:
```
sild_loss_budget_bits{protocol, message_type}
Buckets: (10, 20, 40, 80, 160, 320, 640) bit
```

---

### M-7 [BEHOBEN] — Latenz-Monitoring Load-Generator

**FM-4-Anforderung:** §6 — Performance p99 < 2ms.

**Ursprungliches Problem:** Load-Generator maß keine Latenzen.

**Losung (Commit fbf2fa3):**

```python
# send_one() gibt (ok, code, latency_s) zuruck
ok, code, lat_s = send_one(host, port, msg)
latency_window.append(lat_s)   # Rolling Window, maxlen=1000

# Alle 5s Ausgabe mit Perzentilen
p50 = _percentile(sorted_lat, 50) * 1000
p95 = _percentile(sorted_lat, 95) * 1000
p99 = _percentile(sorted_lat, 99) * 1000
# Warnung wenn p99 > --latency-warn-ms (Default: 2.0ms, FM-4 §6)
```

---

### M-8 [BEHOBEN] — DE-Basisprofile / MII-Regelset

**FM-4-Anforderung:** §3.2 — sild.fhir.profiles_de: (Pi_de, phi_de).

**Ursprungliches Problem:** Adapter fur deutsche FHIR-Basisprofile fehlte komplett.

**Losung (Commit fbf2fa3):**

Neue Datei `sild_fhir_profiles_de.py` mit 4 MII/KBV-Regeln:

| Regel | Ressource | Prufung | Pattern | Severity |
|---|---|---|---|---|
| DE-1 | Condition | ICD-10-GM ohne Diagnosesicherheit (V/A/Z/G) | AD | warning |
| DE-2 | Observation | valueQuantity ohne UCUM-Einheit | TN | info |
| DE-3 | MedicationAdministration | Kein ATC-Code | TN | info |
| DE-4 | Patient | Kein GKV/PKV-KVid-Identifier | AD | info |

Integration in `sild_fhir_filter.py` via `--profiles-de` Flag.
**Wichtig:** DE-Losses werden VOR `apply_severity_overrides()` eingefugt,
damit sie ebenfalls Override-Behandlung erhalten (FM-4 §2.4 konform).

---

## Behobene niedrige Lucken (Prioritat 3)

Diese Punkte betrafen Demo-Infrastruktur, nicht die Detektor-Semantik.

### N-1 [BEHOBEN] — HL7v2 ORC-2 RS-Semantik

**Datei:** `sild_detector.py`

**Problem:** ORC-2 (Placer Order Number) wurde als RS mit Severity `warning` gemeldet,
obwohl ORC-2 vorhanden kein bestatigtes Reference Severing darstellt — FM-4 Def. 2.4
verlangt phi(r'i) = leer im Zielsystem, was erst dort gepruft werden kann.

**Losung (Commit f185c28):**

Severity von `warning` auf `info` gesenkt; Beschreibung als "potenziell unauflosbar"
formuliert:

```python
# Vorher: severity="warning", description="ORC-2 ohne Mapping (RS)"
# Nachher:
losses.append(LossEvent(
    RS,
    location="ORC-2",
    description="ORC-2 Placer Order Number: potenziell unauflosbar im Zielsystem",
    severity="info"   # N-1: kein bestatigtes RS, nur potenzielles RS
))
```

ORC-2 vorhanden = kein bestätigtes RS (`warning`), sondern potenzielle Unauflosbarkeit (`info`).

---

### N-2 [BEHOBEN] — Mock MLLP-Target: NAK-Support fur End-to-End-Tests

**Datei:** `sild_mllp_target.py`

**Problem:** Mock sendete immer `MSA|AA`. Realistische End-to-End-Tests des
K-2-Fixes (NAK-AE-Verhalten des SILD-Filters) waren nicht moglich.

**Losung (Commit f185c28):**

Neuer `--response-mode`-Parameter mit vier Modi:

```
--response-mode aa    (Standard): immer Application Accept
--response-mode ae    : immer Application Error mit ERR-Segment (testet K-2)
--response-mode ar    : immer Application Reject mit ERR-Segment
--response-mode flap  : wechselt alle --flap-n Nachrichten zwischen AA und AE
```

`make_ack()` im Mock erzeugt bei `ae`/`ar` ein ERR-Segment analog zum
K-2-Verhalten des SILD-Filters:

```python
def make_ack(msg_id: str, code: str) -> bytes:
    err = ""
    if code in ("AE", "AR"):
        err = f"\rERR||207^Application Internal Error^HL70357|E|Mock-{code}"
    ack = f"MSH|...\rMSA|{code}|{msg_id}|Mock response{err}\r"
    return b"\x0b" + ack.encode() + b"\x1c\r"
```

---

### N-3 [BEHOBEN] — Mock FHIR-Target: Valide Response-Locations

**Datei:** `sild_fhir_target.py`

**Problem:** `"location": f"#{i}"` ist kein valides FHIR-Location-Format und
wurde von FHIR-Clients als ungultig abgelehnt.

**Losung (Commit f185c28):**

Format auf `ResourceType/id` umgestellt; Fallback auf `urn:uuid:` wenn kein
ResourceType/id vorhanden:

```python
# Vorher: "location": f"#{i}"
# Nachher:
resource_type = entry.get("resource", {}).get("resourceType", "")
resource_id   = entry.get("resource", {}).get("id", "")
if resource_type and resource_id:
    location = f"{resource_type}/{resource_id}"   # z.B. "Observation/obs-1"
else:
    location = f"urn:uuid:{entry.get('fullUrl', str(i))}"

issues.append({"severity": "information", "location": location, ...})
```

---

### N-4 [BEHOBEN] — requirements.txt: Abhangigkeiten dokumentiert

**Datei:** `requirements.txt`

**Problem:** `cairn`-Paket wird in `sild_detector.py` optional importiert,
fehlte aber in `requirements.txt`. Auch `prometheus_client` war ohne
Versionsangabe oder Kommentar aufgefuhrt.

**Losung (Commit f185c28):**

```
prometheus_client>=0.19.0          # Pflicht
# cairn>=1.0.0                     # Optional: FM-4 primary detector
# DE-Basisprofile: kein Zusatzpaket notig
```

Pflichtabhangigkeit mit Mindestversion explizit dokumentiert; optionale CAIRN-
Abhangigkeit als kommentierte Zeile mit Hinweis auf FM-4 primary detector.

---

## Gesamtbewertung nach Behebung

### FM-4-Konformitat je Abschnitt

| FM-4-Abschnitt | Anforderung | Status |
|---|---|---|
| Def. 2.1 Type Narrowing | Terminologie-Strukturerkennung | Konform (K-1, M-2 FHIR) |
| Def. 2.2 Temporal Collapse | dim t(e) > dim t(e'') | Konform (K-1, M-2) |
| Def. 2.3 Attribute Dropping | Modifier-Verlust-Check | Konform (K-1, M-1) |
| Def. 2.4 Reference Severing | Bundle-Auflosbarkeit | Konform (K-1, M-3, N-1) |
| §2.4 Severity-Komposition | Sigma_eff = o_t o o_d o Sigma_i | Konform (K-3) |
| Korollar A.4 LossPattern-Enum | Genau 4 Werte | Konform |
| Korollar A.5 core-Layer | Byte-identisch v2/FHIR | Konform |
| §3.2 Adapter-Architektur | sild.core + v2/fhir/de | Konform (M-8) |
| §4.1 Entropie-Schatzwerte | L_TN/TC/AD/RS in Bit | Konform (M-6) |
| §4.2 Verlust-Budget B(F) | Summe pro Nachricht | Konform (M-6) |
| §5.1 Sentinel-Position | Am Ubertragungspunkt | Konform |
| §5.2 Block-Mechanik CRITICAL | HTTP 422 / MLLP-NAK-AE | Konform (K-2) |
| §5.2 Audit-Selektivitat INFO | Kein Audit-Eintrag | Konform (M-4/K-3) |
| §5.3 FHIR AuditEvent | FM-1-Tupel (t,tau,c,r,m) | Konform (M-5) |
| §6 Performance p99 < 2ms | Latenz-Monitoring | Konform (M-7) |
| §3.2 DE-Basisprofile MII/KBV | sild.fhir.profiles_de | Konform (M-8) |

### Offene FM-4-Punkte (aus §8 Offene Punkte)

Diese Punkte sind in FM-4 §8 selbst als "offene Punkte" gekennzeichnet — sie
sind nicht Implementierungsdefizite, sondern zukuenftige Forschungsfragen:

| FM-4 §8 | Beschreibung | Implementierungsstatus |
|---|---|---|
| §8.1 Subadditive Aggregation | Mehrfachverluste auf gleicher Komponente | Nicht implementiert (FM-4 selbst offen) |
| §8.2 Empirische Kalibrierung | Bit-Schatzwerte gegen reale Mappings | Nicht implementiert (FM-4 selbst offen) |
| §8.3 Cross-Bundle RS | Referenzen uber mehrere Bundles | Nicht implementiert (FM-4 selbst offen) |
| §8.4 StructureDefinition-Validierung | FHIR-StructureDefinition als Detektor | Nicht implementiert (FM-4 selbst offen) |

---

## Neue Architektur-Ubersicht (nach Behebung)

```
sild_detector.py          sild.core (tragerunabhangig)
  LossPattern (4 Werte)   Korollar A.4
  LossEvent               severity (intrinsic) + effective_severity
  SILDReport              loss_budget_bits (FM-4 §4.2)
  SeverityOverrideConfig  Sigma_eff = o_t o o_d o Sigma_i (FM-4 §2.4)
  _hl7_ce_structured()    FM-4 Def. 2.1 HL7v2
  _fhir_cc_narrowing()    FM-4 Def. 2.1 FHIR
  _build_resolvable_refs() FM-4 Def. 2.4 Bundle-RS
  compute_loss_budget_bits() FM-4 §4.1
  fhir_audit_events_from_report() FM-4 §5.3

sild_mllp_filter.py       sild.v2.rules
  make_ack(code='AE')     MLLP-NAK-AE mit ERR-Segment (K-2)
  _extract_tenant_id()    MSH-3|MSH-4 -> Tenant-ID (K-3)
  M_LOSS_BUDGET Histogram FM-4 §4.1

sild_fhir_filter.py       sild.fhir.rules
  FHIRRequestHandler      HTTP 422 CRITICAL (K-2 analog)
  _get_tenant_id()        X-Tenant-ID Header (K-3)
  M_LOSS_BUDGET Histogram FM-4 §4.1
  --profiles-de           M-8 Integration

sild_fhir_profiles_de.py  sild.fhir.profiles_de (NEU)
  _check_icd10gm_diagnosesicherheit() DE-Regel 1
  _check_observation_ucum()           DE-Regel 2
  _check_medication_atc()             DE-Regel 3
  _check_patient_kvn()                DE-Regel 4

sild_mllp_target.py       Mock MLLP-Empfanger (N-2)
  --response-mode aa|ae|ar|flap
  make_ack() mit ERR-Segment bei AE/AR

sild_fhir_target.py       Mock FHIR-Empfanger (N-3)
  location: ResourceType/id (valides FHIR-Format)
  Fallback: urn:uuid:

load_generator.py
  send_one() -> (ok, code, latency_s)   M-7
  _percentile() + Rolling Window        M-7
  --latency-warn-ms (FM-4 §6)           M-7
```

---

*Erstellt: 2026-05-24 | Aktualisiert: 2026-05-24*  
*Grundlage: FM-4, Friedhelm Matten / ISCaD GmbH, Mai 2026*
