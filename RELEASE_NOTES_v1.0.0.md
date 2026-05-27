## SILD v1.0.0 — FM-4 konform

Erste vollständige Release des **SILD Monitoring Stack** (Semantic Information Loss Detection).

SILD erkennt, klassifiziert und visualisiert semantischen Datenverlust beim Austausch zwischen Krankenhausinformationssystemen (KIS) und klinischen Analyseplattformen — in Echtzeit, an der Übertragungskante.

### Theoretische Grundlage

Direkte operative Umsetzung von **FM-4** (*Signal-Loss Inspection at Data-boundaries*, Matten, ISCaD GmbH, Mai 2026), aufbauend auf **FM-1** (*Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen*, Matten, März 2026).

Theorie-DOI: [10.5281/zenodo.20391260](https://doi.org/10.5281/zenodo.20391260)

### Vier kanonische Verlustmuster (FM-4 Def. 2.1–2.4)

| Pattern | Beschreibung |
|---|---|
| **Type Narrowing** | LOINC-Code → Freitext; CodeableConcept ohne .coding |
| **Temporal Collapse** | Intervall [t₁,t₂] → Zeitpunkt t* |
| **Attribute Dropping** | Modifier mᵢ in Quelle, nicht im Ziel |
| **Reference Severing** | Referenz vorhanden, aber nicht auflösbar |

### Komponenten

- `sild_detector.py` — sild.core (trägerunabhängig, FM-4 Korollar A.4/A.5)
- `sild_mllp_filter.py` — sild.v2.rules (HL7v2/MLLP, Port 2575)
- `sild_fhir_filter.py` — sild.fhir.rules (FHIR R4/HTTP, Port 8080)
- `sild_fhir_profiles_de.py` — sild.fhir.profiles_de (MII/KBV DE-Basisprofile)
- Prometheus + Grafana (8-Panel-Dashboard, 5 s Refresh)
- Lastgenerator mit p99-Latenz-Monitoring (FM-4 §6)

### FM-4-Konformität: 15/15 Lücken behoben

| Priorität | Inhalt |
|---|---|
| K-1–K-3 | Terminologie-Strukturerkennung, MLLP-NAK-AE, Severity-Komposition |
| M-1–M-8 | AD/TC/RS-Detektoren, AuditEvent, Verlust-Budget, DE-Basisprofile, Latenz |
| N-1–N-4 | ORC-2-Semantik, NAK-Mock, FHIR-Locations, requirements.txt |

### Schnellstart

```bash
cd sild_monitoring_stack
docker compose up -d
sleep 30
open http://localhost:3000   # Grafana-Dashboard
```

### Hinweis

Nicht als Medizinprodukt nach EU MDR 2017/745 zugelassen.
Werkzeug für Datenqualitäts-Monitoring — keine klinische Entscheidungssoftware.
