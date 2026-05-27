# SILD Monitoring Stack — Dokumentationspaket
**Version:** 3.0  
**Datum:** 2026-05-26  
**Autor:** Friedhelm Matten / ISCaD GmbH  
**Git-Stand:** `739ad0d` — Lizenz AGPL-3.0-only OR Commercial, DOI 10.5281/zenodo.20391260

---

## Enthaltene Dokumente

### Theoretische Grundlagen

| Dokument | Beschreibung |
|---|---|
| [FM-1](https://doi.org/10.5281/zenodo.19205557) | Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen (Matten, März 2026) — formaler Informationsraum I als Grundlage für SILD |
| [FM-4 v2](https://doi.org/10.5281/zenodo.20391260) | Signal-Loss Inspection at Data-boundaries (Matten, Mai 2026) — Loss-Pattern-Algebra, Adapter-Architektur, Vollständigkeitssatz |

### Projektberichte

| Datei | Beschreibung |
|---|---|
| `PROJEKTBERICHT.md` | Vollständiger Projektbericht v3.0: theoretische Grundlagen, Implementierungsübersicht, Architektur, Verlustmuster, Prometheus-Metriken, FM-4-Konformitätsanalyse |
| `KONFORMITAETSBERICHT.md` | Detaillierter Konformitätsbericht v3.0: alle 15 Lücken (K/M/N) mit Originaldefund, Lösung und Code-Snippets; FM-4-§-Konformitätstabelle |

---

## Konformitätsstatus (Zusammenfassung)

| Kategorie | Lücken | Behoben | Commits |
|---|---|---|---|
| KRITISCH (K-1–K-3) | 3 | 3 | `ae012a2` |
| MITTEL (M-1–M-8) | 8 | 8 | `fbf2fa3` |
| NIEDRIG (N-1–N-4) | 4 | 4 | `f185c28` |
| **Gesamt** | **15** | **15** | — |

**Verbleibend (FM-4 §8 — selbst als offene Forschungsfragen markiert):**
- §8.1 Subadditive Aggregation
- §8.2 Empirische Kalibrierung der Bit-Schätzwerte
- §8.3 Cross-Bundle Reference Resolution
- §8.4 StructureDefinition-Validierung als Detektor

**Technische Schuld (Produktionsbetrieb):**
- TLS/mTLS auf MLLP (klinischer Standard)

---

## Implementierte Komponenten

```
sild_monitoring_stack/
  sild_detector.py          sild.core     — FM-4 Korollar A.4/A.5
  sild_mllp_filter.py       sild.v2.rules — Port 2575 / Metriken 9100
  sild_fhir_filter.py       sild.fhir.rules — Port 8080 / Metriken 9101
  sild_fhir_profiles_de.py  sild.fhir.profiles_de — MII/KBV (M-8)
  sild_mllp_target.py       Mock AION MLLP (NAK-Support N-2)
  sild_fhir_target.py       Mock AION FHIR (valide Locations N-3)
  load_generator.py         Lastgenerator + p99-Latenz (M-7)
  severity_overrides_example.json  Beispiel-Override-Konfiguration (K-3)
  requirements.txt          Dokumentierte Abhängigkeiten (N-4)
```

---

*ISCaD GmbH, 30900 Wedemark — licensing@iscad-it.de*  
*Lizenz: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial — Repository: codeberg.org/fmatten/sild*  
*Theory DOI: 10.5281/zenodo.20391260*
