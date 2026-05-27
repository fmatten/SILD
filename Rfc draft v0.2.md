------

## title: "SILD — Erkennung semantischer Verluste an klinischen Datenübergängen" subtitle: "Ein Leitfaden zur Signal-Loss Inspection at Data-boundaries" author: "Friedhelm Matten, ISCaD GmbH" date: "Mai 2026" version: "Entwurf v0.2 (deutsche Fassung)" status: "Informational" abstract: > Dieses Dokument spezifiziert SILD (Signal-Loss Inspection at Data-boundaries), einen trägerformatunabhängigen Detektor für semantische Informationsverluste bei klinischen Cross-System-Übertragungen. SILD erkennt vier kanonische Verlustmuster an Übertragungskanten — Type Narrowing, Temporal Collapse, Attribute Dropping und Reference Severing — unabhängig vom konkreten Trägerformat (HL7 v2, FHIR R4/R5, DICOM SR). Die formale Grundlage und die Beweise sind in FM-4 [FM-4] dokumentiert; dieses Dokument richtet sich an Implementierer und Anwender.

# Status dieses Dokuments

Dies ist ein individueller Beitrag an die klinische Interoperabilitäts-Community. Das Dokument wird zur öffentlichen Prüfung und Kommentierung verteilt. Die Verbreitung ist nicht eingeschränkt.

**Hinweis für Leser:** Dies ist ein ENTWURF. Implementierungen auf Basis dieses Dokuments müssen mit nicht-rückwärtskompatiblen Änderungen rechnen, bevor eine finale Version vorliegt.

# Copyright

Copyright © 2026 Friedhelm Matten / ISCaD GmbH. Alle Rechte vorbehalten.

------

# 1. Einleitung

## 1.1 Das Problem an einem Beispiel

Ein kardiologisches Labor schickt einen Troponin-Wert an das EHR des Krankenhauses. Im Quellsystem ist der Wert mit einem LOINC-Code verschlagwortet, trägt ein Messfenster („zwischen 14:32 und 14:35 abgenommen"), eine Schutzklassifikation („besonders schutzbedürftig — kardiogenetische Studie") und eine Referenz auf den auslösenden Aufenthalt.

Nach Übertragung durch einen HL7-v2-nach-FHIR-Konverter empfängt das EHR eine `Observation`-Ressource, die

- den Wert enthält, aber den LOINC-Code verloren hat — geblieben ist nur der Freitext „Troponin";
- als `effectiveDateTime` „14:33" trägt — das Messfenster ist auf einen Punkt kollabiert;
- kein `meta.security`-Tag mehr hat — die Schutzklassifikation ist verschwunden;
- als `encounter.reference` „Encounter/xyz" trägt — aber keine `Encounter/xyz`-Ressource ist im Bundle vorhanden.

Ein struktureller Validator wie HAPI nimmt diese Nachricht an. Alle Kardinalitäten sind erfüllt. Alle Typen stimmen. Das Schema ist zufrieden.

Das nachgelagerte klinische Entscheidungsunterstützungssystem kann jedoch:

- nicht nach LOINC filtern (der Code ist weg),
- den zeitlichen Bezug zu anderen Ereignissen nicht herstellen (das Intervall ist kollabiert),
- die spezielle Zugriffspolicy nicht anwenden (das Schutz-Tag ist weg),
- den Aufenthaltskontext nicht auflösen (die Referenz ist gebrochen).

Information ist verloren gegangen, aber kein Validator hat es bemerkt. Diese Lücke schließt SILD.

## 1.2 Was SILD ist

SILD ist ein Detektor, der an der Übertragungskante zwischen zwei klinischen Systemen sitzt und für jede durchlaufende Nachricht vier Fragen beantwortet:

1. **Was ist verloren gegangen?** Welches der vier kanonischen Muster ist aufgetreten (falls überhaupt)?
2. **Wie schwer ist der Verlust?** Informativ, warnend oder kritisch?
3. **Wo ist es passiert?** Welcher Pfad oder welches Feld ist betroffen?
4. **Was sollte das System tun?** Durchlassen, protokollieren oder blocken?

Die vier Muster sind im formalen Sinne erschöpfend (FM-4, Theorem 2.5) — unter den dort genannten Annahmen über die Faktorisierung klinischer Mappings. Ein Implementierer muss den Beweis nicht lesen, um SILD zu nutzen; die Muster sind auch empirisch erschöpfend in allen bekannten Mappings (HL7 v2 → FHIR, FHIR R4 → R5, FHIR → OMOP, FHIR → i2b2).

## 1.3 Was SILD nicht ist

SILD ist insbesondere **nicht**:

- ein neues Übertragungsprotokoll oder Datenformat. SILD inspiziert bestehende Trägerformate.
- ein Ersatz für HAPI oder andere strukturelle Validatoren. SILD läuft nach der strukturellen Validierung und erkennt eine andere Klasse von Defekten.
- ein Auto-Repair-Werkzeug. Es findet, es repariert nicht. Behebung ist eine separate Frage.
- an FHIR gebunden. Die Detektorklasse funktioniert für HL7 v2, FHIR R4/R5 und DICOM SR über eine Adapter-Architektur (siehe §5).

## 1.4 Wie dieses Dokument zu lesen ist

Implementierer können sich auf §3, §4, §5, §6, §9 und Anhang B beschränken und den Rest überspringen. Die mathematischen Grundlagen werden referenziert, nicht reproduziert; Anhang A verweist auf die entsprechenden Stellen in FM-4.

------

# 2. Konventionen und Begriffe

## 2.1 Anforderungsgrade

Die Schlüsselwörter „MUSS", „MUSS NICHT", „ERFORDERLICH", „SOLL", „SOLL NICHT", „EMPFOHLEN", „NICHT EMPFOHLEN", „KANN" und „OPTIONAL" in diesem Dokument sind im Sinne von BCP 14 [RFC2119] [RFC8174] zu interpretieren — und nur dann, wenn sie in Großbuchstaben erscheinen.

## 2.2 Glossar

| Begriff              | Definition                                                   |
| -------------------- | ------------------------------------------------------------ |
| Übertragungskante    | Der Punkt, an dem Daten ein System verlassen und in ein anderes eintreten. |
| Trägerformat         | Die Serialisierung (HL7 v2, FHIR R4, FHIR R5, DICOM SR).     |
| Findung              | Eine erkannte Verlustinstanz mit Pattern, Pfad und Severity. |
| Regel                | Ein Prädikat, das bei eingehenden Daten eine Findung erzeugt, wenn es wahr ist. |
| core-Layer           | Trägerformat-unabhängige Logik (die vier Pattern, das Severity-Modell). |
| Adapter              | Trägerformat-spezifische Regeln und Pfadsprache.             |
| Detektierte Severity | Die Severity, die die auslösende Regel zugewiesen hat.       |
| Effektive Severity   | Die Severity nach Anwendung lokaler Overrides.               |

------

# 3. Die vier Verlustmuster

## 3.1 Warum genau vier

Jeder Verlust in einer klinischen Übertragung, sofern sich diese in unabhängige Komponentenabbildungen (Zeit, Typ, Kontext, Referenzen, Modifier) faktorisieren lässt, reduziert sich auf genau eines der vier Pattern. Das ist FM-4 Theorem 2.5 (Vollständigkeit), bewiesen unter zwei ausdrücklich genannten Annahmen (FM-4 §A.5):

- **A1 (Komponentenweise Faktorisierung):** Klinische Übertragungen zerlegen sich in unabhängige Komponentenabbildungen.
- **A2 (Disjunkte Komponentenräume):** Die Komponentenräume sind algebraisch unterscheidbar.

Ein separates Resultat (FM-4 Theorem 2.7, Minimalität) zeigt, dass die Vier-Pattern-Taxonomie nicht reduzierbar ist: kein Pattern ist redundant.

**Praktische Konsequenz:** Wenn ein vorgeschlagener Detektor sich nicht in TN/TC/AD/RS einordnen lässt, dann adressiert er entweder (a) eine Verletzung von A1 — was in der klinischen Praxis selten vorkommt — oder (b) gehört in eine andere Prüfklasse (Struktur, Geschäftsregeln, Terminology Binding). Er ist dann kein Kandidat für SILD.

## 3.2 Type Narrowing (TN)

**Was es ist.** Ein präziser Code wird durch eine vagere Repräsentation ersetzt.

**Konkrete Beispiele:**

- Ein LOINC-Code wird im `CodeableConcept` durch reinen `text` ersetzt.
- Ein SNOMED-CT-Blattknoten wird zum übergeordneten Knoten („Bakterielle Pneumonie" wird zu „Pneumonie").
- Eine aufgelöste `Reference` wird zu einer reinen `identifier`-Referenz ohne Resolver im Scope.

**Warum es schadet.** Nachgelagerte Systeme können nicht mehr nach Code filtern, aggregieren oder code-spezifische Regeln anwenden. Ein Entscheidungsunterstützungssystem feuert nicht auf Freitext; ein Register zählt nicht nach Code.

**Default-Severity.** WARNING. Bei sicherheitskritischen Codes (Allergene, Medikamentencodes) kann CRITICAL angebracht sein; bei bewusst freitextlich gehaltenen Feldern (Patientenkommentare) reicht INFO.

## 3.3 Temporal Collapse (TC)

**Was es ist.** Ein Zeitintervall oder eine Wiederholungsstruktur kollabiert zu einem einzelnen Punkt.

**Konkrete Beispiele:**

- Ein Medikationszeitraum (`Period` mit `[start, end]`) wird zu einem einzelnen `occurrenceDateTime`.
- Ein `Timing.repeat` („dreimal täglich für sieben Tage") wird auf einen `occurrenceDateTime` reduziert.
- Eine `Observation.effectivePeriod` wird zu `effectiveDateTime`.

**Warum es schadet.** Kausales Schließen wird unmöglich. Die Allen-Intervall-Relationen (`before`, `meets`, `overlaps`, `during`, … — siehe [Allen]) kollabieren alle zu „ist-vor-oder-nicht", sobald beide Operanden Punkte sind. „Fand die Laborabnahme während der Infusion statt?" wird unbeantwortbar.

**Default-Severity.** WARNING. CRITICAL, wenn nachgelagert kausale Inferenz stattfindet (z.B. Attribution unerwünschter Arzneimittelwirkungen, AION-Pipelines).

## 3.4 Attribute Dropping (AD)

**Was es ist.** Ein bedeutungsverändernder Modifier verschwindet.

**Konkrete Beispiele:**

- `meta.security`-Tag wird entfernt; die Schutzklassifikation geht verloren.
- `modifierExtension` wird bei der Übertragung weggelassen.
- `Observation.value[x]` fehlt ohne `dataAbsentReason` („wir wissen nicht, warum dies leer ist").
- Diagnose-Sicherheit (verdacht / gesichert / ausgeschlossen) geht verloren.

**Warum es schadet.** Modifier tragen bedeutungsverändernde Information. Eine Diagnose ohne Sicherheitsstatus liest sich für die meisten Konsumenten als „gesichert", auch wenn die Quelle „verdacht" meinte. Ein fehlendes Schutz-Tag kann Daten in eine niedriger geschützte Zone verschieben.

**Default-Severity.** Hängt vom Modifier ab. CRITICAL für Schutz-Tags und `dataAbsentReason`; WARNING für die meisten klinischen Modifier; INFO für rein darstellungsbezogene Annotationen (`text`, `note`).

## 3.5 Reference Severing (RS)

**Was es ist.** Eine Referenz ist syntaktisch vorhanden, kann aber im Scope nicht aufgelöst werden.

**Konkrete Beispiele:**

- `Reference.reference = "Patient/123"`, aber kein `Bundle.entry` hat `fullUrl` `Patient/123`.
- Eine `#contained-id`-Referenz ohne passenden `contained[]`-Eintrag.
- Eine reine `identifier`-Referenz ohne Resolver.

**Warum es schadet.** Der referenzierte Kontext — Patient, Aufenthalt, zugehörige Erkrankung — ist für das empfangende System unsichtbar. Die klinische Sicherheit kann direkt betroffen sein: eine Medikamentenanordnung ohne auflösbare Patienten-Referenz ist gefährlich.

**Default-Severity.** CRITICAL für sicherheitsrelevante Referenzen (Patient, Medikation, Allergie); WARNING für Kontextreferenzen (Aufenthalt, Behandelnder); INFO für rein informationelle Verknüpfungen (`derivedFrom` auf einen früheren Entwurf).

------

# 4. Severity und operative Reaktion

## 4.1 Drei Stufen

SILD verwendet drei Severity-Stufen, total geordnet:

```
CRITICAL  >  WARNING  >  INFO
```

## 4.2 Was jede Stufe auslöst

| Stufe    | Übertragung | Audit              | Metrik-Zähler |
| -------- | ----------- | ------------------ | ------------- |
| CRITICAL | Geblockt    | Ja                 | Ja            |
| WARNING  | Durchlass   | Ja                 | Ja            |
| INFO     | Durchlass   | Standardmäßig nein | Ja            |

**Block-Reaktion nach Trägerformat:**

- FHIR über HTTP: `HTTP 422 Unprocessable Entity` mit einem `OperationOutcome`, das die Findungen beschreibt.
- HL7 v2 über MLLP: `MSA-1 = AE` (Application Error) mit passendem `ERR`-Segment.
- DICOM SR: implementierungsabhängig, üblicherweise ein negativer Storage Commitment oder eine Association Rejection.

## 4.3 Lokale Overrides

Mandanten und Pfade benötigen mitunter abweichende Severities. SILD unterstützt Overrides als geschichtete Abbildung:

```yaml
overrides:
  - path: "Observation.note"
    pattern: "AD"
    override_severity: "INFO"
    rationale: "Freitext-Notizen sind in unserem Profil rein hinweislich."
```

Overrides DÜRFEN NICHT die **detektierte** Severity verändern — sie verändern ausschließlich die **effektive** Severity (Konsequenz). Diese Unterscheidung ist normativ und wird in §4.4 ausgeführt.

## 4.4 Detektion vs. Konsequenz (normativ)

Die Audit-Spur protokolliert jede Findung mit ihrer **detektierten** Severity. Die operative Konsequenz (blocken / loggen / zählen) wird durch die **effektive** Severity nach Anwendung der Overrides bestimmt.

Daraus folgt:

- Wenn eine Regel ein WARNING erzeugt, das auf INFO heruntergesetzt wird, MUSS die Findung dennoch in das Audit geschrieben werden (weil ihre detektierte Severity WARNING ist), die Übertragung MUSS aber durchlaufen (weil ihre effektive Severity INFO ist).
- Ein Override kann eine Findung niemals aus dem Audit verschwinden lassen. Er kann ausschließlich darüber entscheiden, ob die Übertragung geblockt wird.

Diese Regel verhindert den „Override-zum-Verschwindenlassen"-Angriff, bei dem ein Mandant Findungen, die er nicht sehen möchte, weg-konfiguriert.

------

# 5. Architektur

## 5.1 Core und Adapter

```
┌────────────────────────────────────────────────┐
│                  sild.core                     │
│  Pattern-Enum, Severity, Finding, Result       │
│  ──── trägerunabhängig, byte-identisch ────    │
└────────────────────────────────────────────────┘
         ▲                              ▲
   ┌─────┴──────┐                ┌──────┴──────┐
   │ sild.v2    │                │ sild.fhir   │
   │  adapter   │                │   adapter   │
   │  (HL7 v2)  │                │ (R4 und R5) │
   └────────────┘                └─────────────┘
```

| Modul                   | Aufgabe                             | Trägerformat |
| ----------------------- | ----------------------------------- | ------------ |
| `sild.core`             | Pattern, Severity, Findungs-Records | —            |
| `sild.v2.rules`         | Segment-/Feld-Prädikate             | HL7 v2       |
| `sild.fhir.rules`       | FHIRPath-Prädikate                  | FHIR R4/R5   |
| `sild.fhir.profiles_de` | DE-Basisprofile, MII                | FHIR (DE)    |

Der core-Layer ist zwischen den Adaptern byte-identisch. Das ist keine Konvention und keine Stilentscheidung — es folgt direkt aus FM-4 Theorem 2.5: Die Pattern und ihre Severity-Logik sind trägerunabhängig, also ist es ihre Repräsentation als Code ebenfalls.

## 5.2 Warum Adapter, nicht Code-Forks

Eine einzelne SILD-Installation muss möglicherweise HL7-v2-Nachrichten vom Laboranalysegerät und FHIR-Bundles von einem nachgelagerten EHR im selben Krankenhaus inspizieren. Mit der Core-plus-Adapter-Struktur teilen beide Detektoren dasselbe Pattern-Vokabular; eine TN-Findung aus v2 ist mit einer TN-Findung aus FHIR im Audit-Log direkt vergleichbar.

## 5.3 Versionskompatibilität (R4 und R5)

FHIR R4 und R5 sind nicht zwei getrennte Trägerformate, sondern zwei Punkte im Versionsbaum desselben Trägerformats. Die meisten Pfade sind identisch (`Reference`, `Identifier`, `CodeableConcept`, `Period`, `Bundle.entry`). Geänderte Pfade werden über ein Versionsprofil dispatched:

```python
def path_for(rule_id, fhir_version):
    if fhir_version == "R5" and rule_id in R5_PATH_OVERRIDES:
        return R5_PATH_OVERRIDES[rule_id]
    return DEFAULT_PATHS[rule_id]
```

Die Menge der zwischen R4 und R5 tatsächlich abweichenden Pfade ist klein gegenüber dem gesamten FHIR-Pfadvokabular, sodass ein vollständiger Re-Fork der Regeln unnötig ist.

**Korollar.** Ein Versions-Migrationsdetektor (R4 → R5) ist ein Spezialfall eines Übertragungsdetektors. Die vier Pattern genügen; ein eigenes Pattern „Version-Downgrade" ist nicht nötig (FM-4 Korollar 3.1).

------

# 6. Pipeline-Integration

## 6.1 Wo SILD sitzt

SILD sitzt als Sentinel an der Übertragungskante: zwischen sendendem und empfangendem System, **bevor** der Empfänger irgendetwas in seinen Speicher schreibt.

Diese Positionierung ist nicht zufällig. Stromabwärts der Kante ist der Verlust bereits geschehen und nicht mehr beobachtbar — das Original ist weg. Nur an der Kante sind die gesendete und die empfangene Repräsentation gleichzeitig sichtbar.

## 6.2 Empfohlene Pipeline-Reihenfolge

```
Eingang → [Struktureller Validator] → [SILD-Detektor] → Empfänger
            (HAPI, Schema)              (diese Spec)
            syntaktische Defekte        semantische Verluste
```

**Begründung.** Strukturelle Defekte (fehlende Pflichtfelder, falsche Typen, Profilverletzungen) können semantische Verluste maskieren; HAPI zuerst laufen zu lassen stellt sicher, dass SILD nur wohlgeformte Nachrichten inspiziert.

## 6.3 Deployment-Endpunkte

| Trägerformat | Deployment         | Endpunkt                 |
| ------------ | ------------------ | ------------------------ |
| FHIR         | HTTP-Reverse-Proxy | `/fhir/*`                |
| HL7 v2       | MLLP-Server        | TCP-Port 2575 (Default)  |
| DICOM SR     | DICOM-SCP          | Konfigurierbare AE Title |

------

# 7. Audit-Spur als eigenständiges Objekt

## 7.1 Mapping auf FHIR AuditEvent

Jede SILD-Findung kann als `FHIR AuditEvent`-Resource persistiert werden:

| Findungs-Feld           | AuditEvent-Feld                          |
| ----------------------- | ---------------------------------------- |
| Zeitstempel             | `AuditEvent.recorded`                    |
| Pattern + Regel-ID      | `AuditEvent.type.code` (SILD-CodeSystem) |
| Referenzierte Ressource | `AuditEvent.entity.what`                 |
| Identität des Detektors | `AuditEvent.agent.who`                   |
| Detektierte Severity    | `AuditEvent.outcome.code`                |
| Pfad / FHIRPath         | `AuditEvent.entity.detail`               |

## 7.2 Warum die Audit-Spur selbst analysierbar ist

Eine persistierte SILD-Findung ist strukturell ein klinischer Informationsdatensatz: sie hat eine Zeit, einen Typ (das Pattern), einen Kontext (die inspizierte Ressource), eine Relation (den Detektor) und eine Severity. Das bedeutet, die Audit-Spur lässt sich mit denselben Werkzeugen analysieren, die für klinische Daten verwendet werden — Trenderkennung, Mandantenvergleich, Anomalie-Detektion auf der Übertragungsqualität werden zur Routineabfrage.

Konkret: Ein Krankenhaus kann „zeige mir Mandanten, deren TN-Rate sich gegenüber dem Vormonat verdoppelt hat" als reguläre Abfrage formulieren, nicht als Ad-hoc-Report.

------

# 8. Quantitative Verlust-Abschätzung

## 8.1 Was beansprucht wird und was nicht

SILD liefert eine grobe, konservative Schätzung des Informationsverlusts in Bit pro Findung. **Diese Zahlen sind nicht exakt** — sie sind Größenordnungs-Schätzungen für Vergleich und Trendanalyse, nicht für absolute Quantifizierung. Die empirische Kalibrierung gegen reale Mappings ist offene Arbeit (FM-4 §4.3, §8).

## 8.2 Pattern-spezifische Schätzer

Die Schätzer aus FM-4 §4 lauten:

- **TN:** `log₂(|Terminologie|)` Bit, wenn ein Code zu Freitext wird; `log₂(k)` Bit, wenn ein Code auf einen Vorgängerknoten mit Teilbaumgröße `k` reduziert wird.
- **TC:** `log₂(Δt / δ)` Bit, wenn ein Intervall der Dauer `Δt` zu einem Punkt der Auflösung `δ` kollabiert; `log₂(n)` Bit für Repeat-`n`-Kollaps.
- **AD:** `log₂(|Modifier-Domain|)` Bit beim Wegfall eines Modifiers.
- **RS:** `log₂(N) + 12` Bit, wenn der Auflösungsbereich auf `N` Ressourcen bekannt ist; konservativ `≈ 24` Bit sonst.

Größenordnungs-Beispiele: LOINC → Text ≈ 16,5 Bit; SNOMED CT → Text ≈ 18,5 Bit; fehlende Diagnose-Sicherheit ≈ 2 Bit.

## 8.3 Aggregation und ihre Grenzen

Das Verlust-Budget einer Übertragung ist die Summe der Einzel-Verluste:

```
B(F) = Σ L(fᵢ)
```

Diese Aggregation ist additiv und konservativ — sie **überzählt** korrelierte Verluste auf derselben Komponente. Das Budget eignet sich für **relative Vergleiche** (Übertragung A vs. B, Mandant A vs. B, dieser Monat vs. letzter Monat), nicht als absoluter informationstheoretischer Wert.

Eine subadditive Behandlung über Komponenten-Partitions-Entropie ist offene Arbeit (FM-4 §8.1).

------

# 9. Konformität

## 9.1 Was „SILD-konform" bedeutet

Eine Implementierung ist SILD-konform, wenn sie §9.2 (Minimaler Regelsatz) und §9.3 (Architekturanforderungen) erfüllt. Optionale Fähigkeiten (§9.4) erweitern die Konformität auf höhere Stufen.

## 9.2 Minimaler Regelsatz (normativ)

Ein SILD-konformer FHIR-Adapter MUSS mindestens diese vier Regeln enthalten, je eine pro Pattern:

| Regel-ID       | Pattern | Prädikat (FHIRPath)                                          | Severity |
| -------------- | ------- | ------------------------------------------------------------ | -------- |
| `TN-CC-01`     | TN      | `CodeableConcept.coding.empty() and CodeableConcept.text.exists()` | WARNING  |
| `TC-PERIOD-01` | TC      | Quelle hatte `Period`, Ziel hat nur `effectiveDateTime`      | WARNING  |
| `AD-VAL-01`    | AD      | `Observation.value.empty() and Observation.dataAbsentReason.empty()` | CRITICAL |
| `RS-BUNDLE-01` | RS      | `Bundle.entry.resource.reference` nicht leer und im Bundle nicht auflösbar | CRITICAL |

Ein SILD-konformer HL7-v2-Adapter MUSS analog mindestens vier Regeln enthalten, eine pro Pattern, mit Prädikaten in Segment-/Feld-Notation.

Test-Vektoren zur Validierung dieser Regeln werden der finalen Fassung dieser Spezifikation beigegeben (Anhang B enthält Beispiel-Eingaben und erwartete Ausgaben).

## 9.3 Architekturanforderungen

Eine konforme Implementierung:

1. MUSS alle vier Pattern erkennen können (TN, TC, AD, RS).
2. MUSS jeder Findung eine Severity aus {INFO, WARNING, CRITICAL} zuweisen.
3. MUSS Findungen mit ihrer **detektierten** Severity protokollieren, unabhängig von Overrides (§4.4).
4. MUSS Findungen mit detektierter Severity WARNING oder CRITICAL als Audit-Events protokollieren.
5. MUSS den core-Layer frei von trägerformatspezifischer Logik halten.
6. MUSS mindestens einen Trägerformat-Adapter unterstützen.

## 9.4 Optionale Fähigkeiten

Eine konforme Implementierung KANN zusätzlich:

- Quantitative Verlust-Schätzung unterstützen (§8).
- Eine HAPI-Pre-Stage-Integrationshilfe bereitstellen.
- Prometheus-/OpenMetrics-Zähler für Findungen exportieren.
- Override-Schichtung über die einfache Mandanten-Ebene hinaus unterstützen.
- Cross-Bundle-Referenzauflösung über ein Session-Konzept anbieten.

------

# 10. Performance

## 10.1 Referenzzahlen

Die Referenzimplementierung (Single-Core CPython 3.12, ohne JIT) wurde auf synthetischen MII-typischen FHIR-Bundles vermessen, je 50 Läufe pro Szenario. Die Zahlen unten sind Mikrosekunden **pro Ressource**, nicht pro Bundle.

| Bundle-Größe | Regelset         | p50  | p95  | p99  |
| ------------ | ---------------- | ---- | ---- | ---- |
| N = 50       | default          | 82   | 84   | 87   |
| N = 50       | default + DE/MII | 92   | 138  | 147  |
| N = 200      | default          | 115  | 117  | 122  |
| N = 200      | default + DE/MII | 122  | 123  | 127  |
| N = 500      | default          | 167  | 175  | 177  |
| N = 500      | default + DE/MII | 175  | 191  | 195  |

## 10.2 Methodik und Einschränkungen

Es handelt sich um **synthetische Mikro-Benchmarks**: in-process, ohne Netzwerk, ohne Audit-I/O, ohne persistenten Speicher. Reale Deployments werden zusätzliche Latenz durch Audit-Schreibvorgänge, Netzwerk-I/O und TLS-Terminierung sehen, in der Größenordnung 0,5–5 ms je nach Audit-Backend.

Das Performance-Ziel — p99 < 2 ms pro Ressource — bietet rund zehnfache Sicherheitsmarge auf dem größten gemessenen Bundle mit dem DE/MII-Profil-Pack. Die Last eines DACH-Universitätsklinikums (≈ 5.000 Ressourcen/Sek. Spitze) lässt sich auf einem einzigen CPython-Worker mit asynchron gebatchten Audit-Schreibvorgängen bedienen.

## 10.3 Was die Varianz treibt

Das DE/MII-Profil-Pack verdoppelt grob die Anzahl pro Ressource evaluierter Regeln, aber Regelauswertung ist überwiegend FHIRPath-Traversierungskosten. Die Latenz skaliert sublinear mit der Regelanzahl bis ≈ 200 Regeln; darüber wird ein Cache kompilierter Prädikate nötig.

------

# 11. Sicherheit und Datenschutz

## 11.1 Datenschutz

SILD operiert auf Metadaten, Struktur und Referenzen — nicht auf patientennaher Inhaltsdokumentation. Audit-Einträge können jedoch Referenzen auf Patientenressourcen enthalten. Implementierungen:

- MÜSSEN Audit-Speicher at-rest verschlüsseln.
- MÜSSEN Zugriffskontrollen anwenden, die denen auf den klinischen Quelldaten entsprechen.
- SOLLEN Audit-Daten gemäß lokaler Regulierung aufbewahren (in Deutschland typischerweise mindestens 10 Jahre für behandlungsrelevantes Material; lokale Rechtsberatung konsultieren).

## 11.2 Der Block-Mechanismus ist operativ relevant

Eine CRITICAL-Findung blockt die Übertragung. Das kann klinische Abläufe beeinflussen. Implementierungen:

- MÜSSEN jede Block-Entscheidung mit Regel-ID und Pfad protokollieren.
- SOLLEN eine Notfall-Override-Möglichkeit mit Zwei-Faktor-Authorisierung bieten, und MÜSSEN alle solchen Overrides in der detektierten Severity protokollieren.
- SOLLEN auf anhaltend hohe Block-Raten oberhalb eines konfigurierten Schwellenwerts entsprechend zuständiges Personal alarmieren.

## 11.3 Die Override-Konfiguration ist sicherheitsrelevant

Die Override-Map (§4.3) kann Konsequenzen ändern, aber nicht die Detektion. Die Map selbst MUSS:

- versionskontrolliert sein.
- signiert oder anderweitig integritätsgeschützt sein.
- bei Änderungen auditierbar sein.

Ein böswillig oder fahrlässig gesetzter Override, der CRITICAL-Findungen auf INFO herunterstuft, kann sie nicht unsichtbar machen (§4.4), aber er kann dazu führen, dass das System reale Verluste nicht mehr blockt. Die Override-Map ist als sicherheitsrelevantes Konfigurationsartefakt zu behandeln.

## 11.4 Lieferkette

Adapter sind trägerformatspezifisch und können sich getrennt vom Core weiterentwickeln. Der core-Layer MUSS eine API-Version deklarieren; Adapter MÜSSEN deklarieren, welche Core-API-Versionen sie unterstützen. Adapter-Binaries SOLLEN signiert sein.

------

# 12. URI-Namespace-Deklaration

Dieses Dokument fordert keine IANA-Registrierung. Die folgenden URIs sind als private Namespaces unter der Domain `iscad.de` deklariert, Eigentümerin ISCaD GmbH:

## 12.1 SILD-Pattern-CodeSystem

**URI:** `https://sild.iscad.de/codesystem/pattern`

| Code | Display            | Definition                                                 |
| ---- | ------------------ | ---------------------------------------------------------- |
| `TN` | Type Narrowing     | Präziser Code wird durch vagere Repräsentation ersetzt.    |
| `TC` | Temporal Collapse  | Zeitintervall oder Wiederholung kollabiert zu einem Punkt. |
| `AD` | Attribute Dropping | Bedeutungsverändernder Modifier wird verworfen.            |
| `RS` | Reference Severing | Referenz wird im Scope unauflösbar.                        |

## 12.2 SILD-Severity-CodeSystem

**URI:** `https://sild.iscad.de/codesystem/severity`

| Code       | Display       | Definition                                       |
| ---------- | ------------- | ------------------------------------------------ |
| `INFO`     | Informational | Geringfügiger Verlust; standardmäßig kein Audit. |
| `WARNING`  | Warning       | Mittelschwerer Verlust; Audit erforderlich.      |
| `CRITICAL` | Critical      | Schwerer Verlust; Übertragung wird geblockt.     |

Spätere Versionen dieses Dokuments können diese CodeSystems in die HL7 Terminology Authority oder ein vergleichbares Register überführen.

------

# 13. Verhältnis zur erweiterten Modellfamilie

SILD ist eine Komponente in einer vierteiligen Paper-Familie. Alle vier Papiere teilen ein gemeinsames Informationsmodell — jedes klinische Ereignis wird durch seine Zeit, seinen Typ, seinen Kontext, seine Referenzen und seine Modifier charakterisiert.

| Paper            | Rolle                                                        | Status                 |
| ---------------- | ------------------------------------------------------------ | ---------------------- |
| **FM-1**         | Grundlagen: formales Modell klinischer Information.          | Veröffentlicht [FM-1]  |
| **FM-2 / CAIRN** | Python-Referenzimplementierung von FM-1.                     | In Vorbereitung [FM-2] |
| **FM-3 / AION**  | Algebraische Intervallontologie für kausale Inferenz.        | In Vorbereitung [FM-3] |
| **FM-4 / SILD**  | Boundary-Detektor für semantische Verluste (Grundlage dieser Spec). | Dieses Dokument [FM-4] |

**Verhältnis von SILD zu den anderen Komponenten (laut FM-4 §7):**

- **CAIRN modelliert** klinische Information und wertet sie aus.
- **AION verallgemeinert** das Modell für kausale Inferenz über Intervalle.
- **SILD prüft**, ob Information an Übertragungskanten intakt bleibt.

Als Slogan: SILD verhält sich zu CAIRN/AION wie ein Linter zu einem Compiler.

Eine SILD-Findung ist im AION-Modell direkt interpretierbar: eine TC-Findung impliziert, dass nachgelagerte Allen-Relations-Operatoren auf dem betroffenen Zeitoperanden mit reduzierter Auflösung arbeiten, was bestimmte kausale Schlüsse unmöglich macht. Eine TN-Findung blockt Subsumtionsschlüsse in der Terminologie-Hierarchie. Diese Korrespondenz ist nicht zufällig; sie folgt aus der gemeinsamen Tupel-Zerlegung des Informationsmodells.

------

# 14. Referenzen

## 14.1 Normative Referenzen

**[RFC2119]** Bradner, S. *Key words for use in RFCs to Indicate Requirement Levels.* BCP 14, RFC 2119, März 1997.

**[RFC8174]** Leiba, B. *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words.* BCP 14, RFC 8174, Mai 2017.

**[FM-4]** Matten, F. *Signal-Loss Inspection at Data-boundaries: Eine formale Detektorklasse für klinische Cross-System-Übertragungen.* ISCaD GmbH, Mai 2026. DOI: `https://doi.org/10.5281/zenodo.20391260`. — Enthält die Beweise (Theoreme 2.5, 2.7) und die Operator-Algebra, auf die in diesem Dokument verwiesen wird.

**[FHIR-R4]** HL7 International. *FHIR Release 4.* https://hl7.org/fhir/R4/

**[FHIR-R5]** HL7 International. *FHIR Release 5.* https://hl7.org/fhir/R5/

## 14.2 Informative Referenzen

**[FM-1]** Matten, F. *Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen.* ISCaD GmbH, März 2026 (Zenodo v1.0). DOI: `https://doi.org/10.5281/zenodo.19205557`.

**[FM-2]** Matten, F. *CAIRN: Clinical Interoperability Reference Architecture.* ISCaD GmbH, 2026 (in Vorbereitung). Quelle: `https://codeberg.org/iscad/cairn`.

**[FM-3]** Matten, F. *AION: Algebraic Interval Ontology for Clinical Networks.* ISCaD GmbH, 2026. DOI: `https://doi.org/10.5281/zenodo.19553130`.

**[Allen]** Allen, J. F. *Maintaining knowledge about temporal intervals.* Communications of the ACM, 26(11):832–843, November 1983.

------

# Anhang A. Mathematische Grundlagen

Dieses Dokument hält die Mathematik bewusst minimal. Der formale Kern liegt in FM-4. Das Minimum, das ein Implementierer wissen sollte:

**Theorem 2.5 (Vollständigkeit).** Unter den Annahmen A1 (komponentenweise Faktorisierung) und A2 (disjunkte Komponentenräume) liegt jede verlustbehaftete klinische Übertragung in TN ∪ TC ∪ AD ∪ RS.

**Theorem 2.7 (Minimalität).** Zu jedem der vier Pattern existiert eine Zeuge-Übertragung, die in keinem der drei übrigen liegt. Die Taxonomie ist nicht reduzierbar.

**Praktische Konsequenzen:**

1. Eine neue SILD-Detektor-Regel, die in keines der vier Pattern fällt, detektiert entweder (a) einen strukturellen Defekt (HAPI nutzen), (b) eine Geschäftsregelverletzung (separate Rule-Engine), oder (c) einen Fall, in dem A1 verletzt ist. Fall (c) ist in der klinischen Interop-Praxis selten und sollte vor dem Hinzufügen eines neuen Pattern diskutiert werden.
2. Das Pattern-Enum im core-Layer hat genau aus diesem Grund vier Werte. Es ist **nicht** auf Erweiterung ausgelegt.
3. Die Trägerunabhängigkeit des core-Layers ist ein Theorem, keine Design-Konvention. Adapter können unabhängig entwickelt werden in der Gewissheit, dass der Core sich dafür nicht ändern muss.

Für die Beweise selbst: FM-4 §2 und Anhang A.

------

# Anhang B. Beispiel-Regelsatz

## B.1 Default-FHIR-Regeln (empfohlene Basis)

```yaml
rules:
  # Type Narrowing
  - id: TN-CC-01
    pattern: TN
    path: "CodeableConcept"
    predicate: "coding.empty() and text.exists()"
    severity: WARNING

  - id: TN-REF-01
    pattern: TN
    path: "Reference"
    predicate: "reference.empty() and identifier.exists()"
    severity: WARNING

  # Temporal Collapse
  - id: TC-PERIOD-01
    pattern: TC
    path: "MedicationRequest.dosage"
    predicate: "timing.repeat.exists() and timing.event.empty()"
    severity: WARNING

  - id: TC-OBS-01
    pattern: TC
    path: "Observation"
    predicate: "Quelle hatte effectivePeriod, Ziel hat nur effectiveDateTime"
    severity: WARNING

  # Attribute Dropping
  - id: AD-SEC-01
    pattern: AD
    path: "Resource.meta"
    predicate: "Quelle.meta.security existierte, Ziel.security ist leer"
    severity: CRITICAL

  - id: AD-VAL-01
    pattern: AD
    path: "Observation"
    predicate: "value.empty() and dataAbsentReason.empty()"
    severity: CRITICAL

  - id: AD-NOTE-01
    pattern: AD
    path: "Resource.note"
    predicate: "Quelle hatte note, Ziel hat keine"
    severity: INFO       # rein hinweislich

  # Reference Severing
  - id: RS-BUNDLE-01
    pattern: RS
    path: "Bundle"
    predicate: "irgendeine Reference.reference matcht kein Bundle.entry.fullUrl"
    severity: CRITICAL

  - id: RS-CONTAINED-01
    pattern: RS
    path: "DomainResource"
    predicate: "irgendeine '#anchor'-Referenz hat kein passendes contained[].id"
    severity: WARNING
```

## B.2 Deutsche MII-Profil-Erweiterungen (illustrativ)

```yaml
rules:
  - id: AD-MII-DX-01
    pattern: AD
    path: "Condition"
    predicate: "verificationStatus.coding.empty()"
    severity: WARNING
    rationale: "MII erfordert Diagnose-Sicherheit (V/A/Z/G)."

  - id: AD-MII-SEC-01
    pattern: AD
    path: "Patient.meta"
    predicate: "security.where(system='https://gematik.de/fhir/CodeSystem/patient-privacy').empty()"
    severity: CRITICAL
    rationale: "Gematik-Datenschutzklassifikation ist für MII-Daten verpflichtend."
```

## B.3 Beispiel-Findungen (für Testvektoren)

Eine WARNING-Findung des Typs TN sieht wie folgt aus:

```json
{
  "rule_id": "TN-CC-01",
  "pattern": "TN",
  "path": "Observation.code",
  "detected_severity": "WARNING",
  "effective_severity": "WARNING",
  "estimated_loss_bits": 16.5,
  "timestamp": "2026-05-26T14:33:00Z",
  "resource_ref": "Observation/abc-123"
}
```

------

# Anhang C. Offene Punkte (für Reviewer)

Die folgenden Punkte sind ausdrücklich offen und laden zur Rückmeldung ein, bevor eine nicht-Entwurfsversion dieser Spezifikation veröffentlicht wird:

1. **Empirische Kalibrierung der Bit-Schätzer.** Die Zahlen in §8 sind Größenordnungs-Schätzungen. Eine community-getragene Kalibrierung an realen v2-nach-FHIR-Mappings (idealerweise an MII-Datenintegrationszentren) würde die Metrik substanziell stärken.
2. **Subadditive Aggregation.** Das additive Verlust-Budget in §8.3 überzählt korrelierte Verluste. Ein Ansatz über Entropie der Komponentenpartitionen ist vorgesehen.
3. **Cross-Bundle-Referenzauflösung.** RS-BUNDLE-01 prüft derzeit nur innerhalb eines Bundles. Mehrteilige Transaktionen erfordern ein Session-Konzept (FM-4 §8).
4. **Internalisierung der StructureDefinition-Validierung.** Eine Teilmenge der HAPI-Profil-Constraint-Logik in SILD aufzunehmen, würde das Deployment vereinfachen. Ob das den Wartungsaufwand rechtfertigt, ist offen.
5. **Konformitäts-Testvektoren.** Eine normative Menge von Input-Output-Paaren zum Nachweis der Compliance mit §9.2 wird der finalen Version beigegeben.
6. **Notations-Vereinheitlichung.** Das Begleitpaper FM-4 verwendet sowohl `T` (Zeitraum) als auch `T` (Terminologie) in seiner Notation; dies bedarf einer eindeutigen Konvention im Druck.

------

**Anschrift des Autors**

Friedhelm Matten ISCaD GmbH Deutschland

E-Mail: `friedhelm.matten@iscad.de` Quelle: `https://github.com/fm2-project/sild` Doku: `https://sild.iscad.de`

------

# Danksagung

Der Autor dankt dem Team der ISCaD GmbH und der klinischen Interoperabilitäts-Community für Rückmeldungen zu früheren Entwürfen. Der Übergang von v0.1 zu v0.2 hat Reviewer-Kommentare zur Theoremnummerierung, zur Audit-Semantik unter Overrides, zum IANA-Scope, zur Performance-Methodik und zur Konformitäts-Verifizierbarkeit eingearbeitet.

------

*Ende des RFC-Entwurfs v0.2 (deutsche Fassung)*