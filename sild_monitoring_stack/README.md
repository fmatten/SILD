# SILD — Referenz-Stack (lokale Methoden-Reproduktion)

**Lokaler Referenz-Stack** für den SILD MLLP Sidecar — fährt die Mess-Methodik end-to-end nach: von der eingehenden HL7-Nachricht bis zum Dashboard im Browser. Zweck: die Methode mit eigenen Augen prüfen, keine produktive Monitoring-Pipeline aufsetzen.

```
   KIS/LIS                                                AION
     │                                                     ▲
     │ HL7v2/MLLP                            HL7v2/MLLP   │
     ▼                                                     │
┌─────────────────────────────────────────────────────────────┐
│             SILD Filter (Container, Port 2575)              │
│     verarbeitet, klassifiziert, leitet weiter               │
│     exponiert /metrics auf Port 9100                        │
└──────────────┬─────────────────────────────────────┬────────┘
               │                                     │
               │ /metrics scrape (alle 5s)           │ JSONL log
               ▼                                     ▼
       ┌──────────────────┐                 sild_reports.jsonl
       │   Prometheus     │
       │   (Container,    │
       │    Port 9090)    │
       └────────┬─────────┘
                │ Queries
                ▼
        ┌────────────────────┐
        │     Grafana        │   ◀── Browser (http://localhost:3000)
        │    (Container,     │
        │     Port 3000)     │
        └────────────────────┘
```

## Schnellstart

```bash
# 1. Stack starten
docker compose up -d

# 2. ~30 Sekunden warten (Container-Start, Lastgenerator beginnt zu senden)

# 3. Browser öffnen
open http://localhost:3000      # Grafana (anonymer Zugriff als Viewer)
open http://localhost:9090      # Prometheus-UI (zum Stöbern)
open http://localhost:9100/metrics   # Roher Metrics-Endpunkt
```

Login Grafana (für Editier-Rechte): **admin** / **sild-demo**.

Anonymer Zugriff ist als Viewer aktiviert — fürs Demo-Vorführen brauchst du also keinen Login.

## Was du siehst

Beim Öffnen von Grafana wird automatisch das **SILD Operations Dashboard** geladen:

**Obere Zeile (Stat-Panels):**
- *Nachrichten gesamt* — Counter aller verarbeiteten HL7-Nachrichten
- *Loss-Ereignisse gesamt* — Counter aller SILD-Befunde, mit farbigem Schwellwert (gelb/orange/rot)
- *Critical-Befunde gesamt* — kritische Befunde, rot hinterlegt
- *Latenz P95 (5 min)* — 95. Perzentil der Verarbeitungszeit

**Mitte (Time-Series):**
- *Nachrichten-Rate pro Typ* — Linien-Diagramm, sekundengenaue Rate je Message-Typ (ADT/ORU/RDE)
- *Loss-Rate nach Pattern (gestapelt)* — die vier SILD-Patterns als gefüllte Flächen, farbcodiert in Ocean-Gradient

**Unten:**
- *Latenz P50/P95/P99* — drei Linien für Median, P95, P99
- *Forward-Entscheidungen* — Donut: forwarded (grün) / blocked (rot) / forward-failed (orange)

Das Dashboard refresht alle 5 Sekunden, der Standard-Zeitbereich ist „letzte 15 Minuten".

## Bestandteile

```
sild_monitoring_stack/
├── docker-compose.yml              ← orchestriert alle 5 Services
├── Dockerfile                      ← für die SILD-Python-Services
├── requirements.txt                ← prometheus_client (einzige Dep)
│
├── sild_detector.py                ← geteilte SILD-Logik (HL7v2)
├── sild_mllp_filter.py             ← Filter mit Prometheus-Exporter
├── sild_mllp_target.py             ← Mock-AION-Empfänger
├── sild_mllp_sender.py             ← Manuelle Test-Nachrichten
├── load_generator.py               ← Kontinuierlicher Lastgenerator
│
├── samples/                        ← 3 realistische HL7-Nachrichten
│   ├── adt_a01_admission.hl7
│   ├── oru_r01_sepsis.hl7
│   └── rde_o11_propofol.hl7
│
├── prometheus/
│   └── prometheus.yml              ← Scrape-Konfiguration
│
└── grafana/
    ├── dashboards/
    │   └── sild_operations.json    ← Das Dashboard (8 Panels)
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yaml     ← Datasource auto-konfiguration
        └── dashboards/
            └── dashboards.yaml     ← Dashboard auto-import
```

## Voraussetzungen

- Docker Engine 20+ und Docker Compose v2 (oder `docker-compose` v1.29+)
- Freie Ports: 2575, 2576, 3000, 9090, 9100

Sonst nichts. Keine Python-Installation, keine Node-Installation, kein lokaler Prometheus, kein lokaler Grafana — alles läuft in Containern.

## Services im Detail

### `aion-mock` (Port 2576)
Simuliert AIONs MLLP-Listener. Empfängt HL7-Nachrichten, sendet AA-ACK.

In Produktion ersetzt du diesen Container durch deine echte AION-Instanz oder einen anderen MLLP-Empfänger.

### `sild-filter` (Port 2575 MLLP, Port 9100 Metrics)
Das Herzstück. Empfängt MLLP-Nachrichten, ruft pro Nachricht den SILD-Detector auf, schreibt JSON-Lines-Log nach `/data/sild_reports.jsonl` (im Volume `sild-data`), leitet an `aion-mock:2576` weiter.

Exponiert vier Metric-Familien:

| Metrik | Typ | Labels | Bedeutung |
|---|---|---|---|
| `sild_messages_total` | Counter | message_type, ack_code | Anzahl verarbeiteter Nachrichten |
| `sild_losses_total` | Counter | pattern, severity, message_type | Anzahl Loss-Ereignisse |
| `sild_forward_decisions_total` | Counter | decision, message_type | Forward-Entscheidungen |
| `sild_filter_latency_seconds` | Histogram | message_type | Verarbeitungslatenz |

### persist-before-ack — durabler v2-Eingang (Default an, Variante A)

Der v2-Eingang läuft **standardmäßig durabel** (fail-secure, wie `AUTH_ENABLED`:
im Zweifel durabel): `frame(vollständig) → persist(fsync) → analyse → ack →
forward`. Keine *angenommene* Nachricht geht über einen Absturz verloren —
schlimmstenfalls entsteht ein Duplikat (vom Sender-Retry), nie ein Verlust.
Garantien G1–G6 und ihre Tests: `sild_durable_store.py` bzw.
`tests/test_durability_v2.py`.

```bash
# Default: durabel. Store-Pfad = <Verzeichnis von --log>/sild_intake.sqlite,
# oder explizit:
python sild_mllp_filter.py --listen 2575 --forward localhost:2576 \
                           --log sild_reports.jsonl \
                           --durable-store /data/sild_intake.sqlite

# Durability abschalten (NUR Demo/Test — gibt eine laute Warnung aus):
python sild_mllp_filter.py --listen 2575 --no-durable
```

- **Store:** SQLite, `journal_mode=WAL, synchronous=FULL` (fsync pro Commit).
- **ACK-Latenz:** jetzt durch einen fsync untergrenzt, über Verbindungen am
  SQLite-Single-Writer serialisiert — die RFC-§10-Zahlen (p99 < 2 ms, „no
  persistent store") gelten für diesen Pfad nicht.

**ACK-Semantik unter persist-before-ack (wichtig — betrifft jetzt alle, da
Default an):** Ein NAK-AE ist **signal-and-duplicate, NICHT reject**. Die
Nachricht ist beim ACK bereits durabel angenommen; ein AE bei CRITICAL (K-2,
FM-4 §5.2) *signalisiert* der Quelle einen kritischen Verlust, *lehnt aber nicht
ab* — der übliche Sender-Retry erzeugt dann ein Duplikat (downstream über den
Idempotenz-Marker dedup-bar). Wer SILD im alten „Reject"-Verständnis betreibt,
muss das wissen: AE heißt hier „durabel gespeichert + kritisch", nicht „verworfen".

**⚠️ Verschlüsselung at-rest:** Der Store enthält **rohe v2-Payload inkl. PID/PHI
im Klartext**. SILD verschlüsselt sie **nicht** — das ist Sache des Betreibers
(RFC §11.1): Store auf ein verschlüsseltes Volume legen. Der Filter gibt beim
Start eine entsprechende Warnung aus.

**Löschung (SILD-SF-1, in diesem Stand adressiert):** patientenbezogene Löschung
über `sild_durable_store.py erase` — dry-run per Default, `--commit` explizit
(destruktiver PID-Pfad). Patienten-Schlüssel = PID-3, MR-typisiert,
`Authority|ID` (standortkonfigurierbar). Fail-closed: eine Zeile ohne auflösbaren
Schlüssel (technische/kaputte Nachricht) kann nicht zugeordnet werden → Status
`incomplete_uncertain` + Restrisiko-Zähler, nie still „gelöscht". Das
Lösch-Protokoll trägt Schlüssel/Zähler/Status/Zeit — **nie** die Payload.

```bash
# dry-run (löscht nichts):
python sild_durable_store.py erase --store /data/sild_intake.sqlite \
                                   --patient-key "HOSP|P-2026-12345"
# echte Löschung + Audit-Zeile:
python sild_durable_store.py erase --store /data/sild_intake.sqlite \
                                   --patient-key "HOSP|P-2026-12345" \
                                   --commit --erase-log /data/sild_erase.jsonl
```

> **G6-Ehrlichkeit:** „G6 grün" heißt *kein DIREKTER* Identifikator (Name/PID-5)
> im JSONL — **nicht** „PII-frei". Finding-Locations können INDIREKT
> personenbeziehbare Identifier enthalten (Order-Nummern aus ORC-2/OBR-2,3). Das
> JSONL untersteht denselben Zugriffskontrollen wie der Store. Siehe SILD-SF-1.

### `sild-mapper-m1` — Intake-Sichter (M-1, read-only)

M-1 ist die Stufe **zwischen** SILDs durablem Intake und dem (noch nicht
gebauten) Intervall-Aufbau M-2. M-1 liest SILDs `sild_intake.sqlite` **nur
lesend** (`mode=ro` + `PRAGMA query_only` — kann SILDs Store nicht beschreiben),
sichtet jede Nachricht zustandsleicht und entscheidet, **was an M-2 weitergereicht
wird** — ohne Intervalle zu bauen, Stornos zu widerrufen oder Zeiten zu schätzen
(alles M-2). Garantien G1–G5 und ihre Tests: `sild_mapper_m1.py` bzw.
`tests/test_mapper_m1.py`.

- **G1 Speichern-vor-Cursor:** pro Intake-Receipt erst den Vermerk durabel
  committen, dann den Lese-Cursor vorrücken. Crash davor → kein Skip; Crash
  dazwischen → idempotenter Re-Scan (kein Verlust, keine Doppel-Weiterleitung).
- **G2 Duplikat-Unterdrückung:** Dedup über den vollständigen Marker
  (MSH-3/4/10), durabel über Neustarts. Unvollständiger Marker → **nie**
  unterdrückt.
- **G3 Relevanz-Filter:** relevant = `ADT^A01/A02/A03` (intervall-bestimmend) +
  `A08/A11/A12/A13` (Update + Storni, rückwirkend verändernd → durchgereicht).
  Nicht-ADT (ORU/RDE) und bekannte, nicht intervall-relevante ADT (A04/A05/…) →
  ignoriert (bewusste, erweiterbare Grenze). **Aber** eine ADT mit fehlendem/
  unlesbarem Trigger-Code ist nicht „irrelevant", sondern kaputt →
  `hold_malformed` + Befund (unparsebar ≠ irrelevant).
- **G4 Zeitqualität (syntaktisch, drei-Wege):** `usable` / `hold_timequality`
  (Zeit fehlt/absurd, Struktur ok) / `hold_malformed` (kein parsebares ADT). Das
  maßgebliche **Bewegungs-Zeitfeld ist je Trigger konfigurierbar**
  (`TimeFieldConfig`):
  - **A01 Aufnahme → PV1-44**, **A03 Entlassung → PV1-45** (eindeutig), mit
    EVN-6 → EVN-2 als Fallback (das gebündelte `samples/adt_a01_admission.hl7`
    trägt die Zeit nur in EVN-2 — der Fallback fängt das ab; EVN ist derselbe
    Ereigniszeitpunkt, keine fremde Zeit).
  - **A02 Verlegung → ZBE-2 → EVN-6, ausdrücklich NICHT PV1-44** (bei Verlegung
    oft nicht neu gesetzt → bliebe die Aufnahmezeit = falsch). Greift weder ZBE-2
    noch EVN-6 → `hold_timequality` + Befund, **nie spekulativ auf PV1-44
    datieren**. *Zu verifizieren an echten Verlegungsdaten:* die SILD-Samples
    enthalten kein ZBE und keine A02-Verlegung.
  - **A08/A11/A12/A13 (Update/Storni):** Zeitfeld profilabhängig, final in **M-2**
    geklärt (Storno-Verarbeitung = M-2). M-1 klassifiziert nur syntaktisch gegen
    ein generisches Default-Feld (EVN-6 → EVN-2).

  > **EVN-2 = zu verifizieren (wie A02/ZBE):** EVN-2 ist *Recorded Date/Time*
  > (Erfassungszeit), **nicht** Event Occurred — als Bewegungszeit-Fallback an
  > echten Daten zu verifizieren (gleiche dürftige Sample-Lage wie ZBE/A02).
  >
  > **Zeit-Provenienz (Anfang der für M-2 vorgemerkten Provenienz):** jedes
  > `usable`-Event trägt mit, **woher** die genutzte Zeit stammt — `PV1-44/45` /
  > `ZBE-2` = *gemessene Bewegungszeit*, `EVN-6` = *Ereigniszeit*, `EVN-2` =
  > *Erfassungs-Ersatz*. Das Feld steht durabel am Vermerk und wird an M-2
  > weitergereicht, damit M-2/AION eine Ersatzzeit **nicht** als gemessenes
  > Faktum in Δ_con verrechnet. (PID-frei: nur Feldherkunft.)
- **G5 Notifier — Speichern VOR Melden, PID-frei.** Siehe nächster Absatz.

```bash
python sild_mapper_m1.py \
    --intake-db /data/sild_intake.sqlite \    # SILDs Store, nur lesend
    --mapper-db /data/sild_mapper.sqlite \    # eigene DB (gemountetes Volume)
    --poll-interval 5 \
    --smtp-host smtp.example.org --smtp-from m1@example.org \
    --smtp-to ops@example.org --smtp-tls
# Ein einzelner Durchlauf (z. B. Cron/CI):  ... --once
```

> **⚠️ SMTP ist ein Pflicht-Konfigurationsschritt (G5).** Ohne `--smtp-host`
> gibt M-1 beim Start eine **laute Warnung** aus („Daten-Qualitäts-
> Benachrichtigung NICHT konfiguriert — Befunde werden nur lokal gespeichert,
> niemand wird aktiv benachrichtigt") und stellt **nicht zu** — die Befunde
> bleiben durabel und werden mit `redeliver_pending()` nachgereicht, sobald SMTP
> steht. Kein stilles Nicht-Benachrichtigen.
>
> **Mail-Inhalt ist PID-frei (hart):** nur Marker (MSH-3/4/10 = Quellsystem-
> Metadaten, kein Patientenbezug), Zähler, Status, Zeit, Klassifikation, Grund —
> **nie** Name/PID/rohe Bewegungsdaten. Mail ist ein unkontrollierter Kanal.
>
> **⚠️ G6-analog für die Mapper-DB:** Die Hold-Queue speichert **rohe v2-Events
> inkl. PID/PHI** (zurückgehaltene Nachrichten sind roh!) — und gerade die
> problematischen, liegenbleibenden. Verschlüsselung at-rest ist Betreiber-Sache
> (verschlüsseltes Volume); der Mapper gibt das ebenso laut aus wie SILDs G6.

**Löschung der Mapper-DB (SILD-SF-1-analog, GEBAUT — kein PID-Fenster):** die
erprobte SILD-`erase_patient`-Logik ist wiederverwendet (nicht neu erfunden):
Patienten-Schlüssel = PID-3, MR-typisiert, `Authority|ID`; multi-MR → Schlüssel-
Menge; fail-closed mit der korrekten Unterscheidung (patientenlose Hold-Zeile →
**nicht** Restrisiko; PID-3 vorhanden aber unlesbar → `unresolved`, zählt →
`incomplete_uncertain`); Lösch-Audit **ohne Inhalt** (Schlüssel/Zähler/Status/
Zeit, nie Payload); dry-run per Default. Die Hold-Queue ist die einzige
PID-Quelle der Mapper-DB; `finding`/`disposition`/`seen_marker` sind PID-frei und
bleiben als inhaltsfreies Audit.

```bash
# dry-run (löscht nichts):
python sild_mapper_m1.py erase --mapper-db /data/sild_mapper.sqlite \
                               --patient-key "HOSP|P-2026-12345"
# echte Löschung + inhaltsfreie Audit-Zeile:
python sild_mapper_m1.py erase --mapper-db /data/sild_mapper.sqlite \
                               --patient-key "HOSP|P-2026-12345" \
                               --commit --erase-log /data/sild_mapper_erase.jsonl
```

> **Backup-Story:** Eine Löschung trifft nur die *lebende* Mapper-DB. Backups/
> Snapshots des gemounteten Volumes liegen außerhalb von M-1 — eine vollständige
> Erasure (SILD **und** Mapper-DB) muss die Backup-Rotation des Betreibers
> einschließen (gleiche Linie wie SILD-SF-1 für SILDs Store).

### `load-generator`
Sendet kontinuierlich Test-Nachrichten an den Filter — durchschnittlich 1.5 pro Sekunde, mit zufälligen Bursts (1–5 Nachrichten am Stück, dann längere Pause). Sorgt dafür, dass das Dashboard sofort lebendige Daten zeigt.

Kann im Compose-File auch deaktiviert werden, wenn echte HL7-Quellen angeschlossen werden:

```yaml
load-generator:
  profiles: ["demo"]   # nur starten mit `docker compose --profile demo up`
```

### `prometheus` (Port 9090)
Scraped alle 5 Sekunden den `/metrics`-Endpunkt des Filters. Persistiert die Daten im Volume `prometheus-data` — auch nach Container-Neustart bleibt die Historie erhalten.

Alle Metriken können in der Prometheus-UI direkt erkundet werden: http://localhost:9090/graph

### `grafana` (Port 3000)
Das Dashboard läuft auf Provisioning-Basis — die Datasource und das Dashboard werden beim ersten Start automatisch eingerichtet, ohne manuelle Konfiguration.

Anonymer Read-Only-Zugang ist aktiviert; Edit-Rechte braucht Admin-Login.

## Demo-Szenarien für die Bühne

### Szenario 1 — Live-Verlustprofil

```bash
docker compose up -d
sleep 30
open http://localhost:3000
```

Du zeigst auf den Bildschirm: *„Hier siehst du in Echtzeit, was zwischen KIS und AION an Information verlorengeht. Pro Sekunde 1–2 Nachrichten, vier Verlust-Patterns farbig getrennt, Latenz im Millisekundenbereich."*

### Szenario 2 — Block-Mode aktivieren

Compose anpassen:

```yaml
sild-filter:
  command:
    - "..."
    - "--mode"
    - "block-on-critical"   # statt log-only
```

Dann `docker compose up -d --no-deps sild-filter`. Im Dashboard wird das Pie-Chart „Forward-Entscheidungen" rote Anteile zeigen — die geblockten Nachrichten mit kritischen Befunden.

### Szenario 3 — Spike simulieren

Burst-Modus im Lastgenerator hochsetzen:

```bash
docker compose run --rm load-generator \
  python load_generator.py --target sild-filter:2575 --rate 10 --burst
```

Im Dashboard: kurzer Spike auf der Nachrichten-Rate, kurze Latenz-Spitze auf P99.

### Szenario 4 — Echte AION anbinden

Den Mock-Empfänger im Compose deaktivieren oder ersetzen, AION als externen Service eintragen:

```yaml
sild-filter:
  command:
    - "..."
    - "--forward"
    - "aion.intern.kliniknetz:2575"   # statt aion-mock:2576
```

Der Filter verbindet sich mit der echten AION-Instanz. Dashboard zeigt **Live-Daten aus dem Klinikbetrieb**.

## Stack stoppen / aufräumen

```bash
# Services stoppen, Volumes erhalten
docker compose down

# Services + Volumes löschen (frischer Start beim nächsten up)
docker compose down -v

# Nur Logs ansehen
docker compose logs -f sild-filter
docker compose logs -f load-generator
```

## Konfiguration im laufenden Betrieb

**Prometheus-Konfig nachladen** (ohne Restart):

```bash
curl -X POST http://localhost:9090/-/reload
```

**Grafana-Dashboard ändern:** Das JSON in `grafana/dashboards/sild_operations.json` editieren — wird alle 30 Sekunden automatisch neu eingelesen (siehe `updateIntervalSeconds` in `dashboards.yaml`).

**Filter-Modus wechseln:** Im Compose-File `--mode` ändern, dann:

```bash
docker compose up -d --no-deps sild-filter
```

## Erweiterungen, die naheliegen

| Erweiterung | Aufwand | Zusätzliche Komponenten |
|---|---|---|
| **Loki + Promtail** für JSONL-Log-Suche | 0,5 Tag | 2 Container |
| **Alertmanager** für Pager-Alerts bei Critical | 0,5 Tag | 1 Container + Routing-Config |
| **PostgreSQL** statt JSONL für strukturierte Auswertung | 1 Tag | 1 Container + Migration-Script |
| **TLS auf MLLP** (Klinik-Standard) | 1 Tag | Nur Code-Änderung im Filter |
| **mTLS / Zertifikat-basierte Auth** | 2 Tage | Cert-Management + Filter-Anpassung |

## Lizenz und Disclaimer

**AGPL-3.0-only OR LicenseRef-ISCaD-Commercial** für die Filter-Komponenten und das Dashboard-JSON.  
Prometheus und Grafana stehen unter ihren eigenen Open-Source-Lizenzen (Apache 2.0 bzw. AGPLv3 für Grafana — sind aber als unmodifizierte Container-Images verwendet und nicht Teil des SILD-Codes).

Kommerzielle Lizenz für proprietäre Integration: `licensing@iscad-it.de`.

**Wichtig:** Dieser Stack ist **nicht als Medizinprodukt zugelassen** im Sinne der EU MDR 2017/745. Er ist ein Werkzeug für Datenqualitäts-Monitoring — keine klinische Entscheidungssoftware.

## Kontakt

ISCaD GmbH · 30900 Wedemark · `licensing@iscad-it.de`

Quellen:
- CAIRN auf Codeberg: `codeberg.org/iscad/cairn`
- AION Clinical auf PyPI: `pypi.org/project/aion-clinical`
- Theory-DOI (FM-4): `10.5281/zenodo.20391260`

---

## FHIR R4 Support (seit v1.1)

Der Stack umfasst seit Version 1.1 zwei parallele Verarbeitungspfade:

| Protokoll | Filter | Empfänger | Lastgenerator |
|---|---|---|---|
| **HL7 v2 / MLLP** | `sild-filter` (Port 2575) | `aion-mock` (Port 2576) | `load-generator` |
| **FHIR R4 / HTTP** | `sild-fhir-filter` (Port 8080) | `aion-fhir-mock` (Port 8081) | `fhir-load-generator` |

Beide Filter nutzen denselben `sild_detector`, dieselben vier Loss-Patterns, dieselbe Severity-Skala. Sie schreiben in **denselben** JSON-Lines-Log (`/data/sild_reports.jsonl` für HL7v2, `/data/sild_fhir_reports.jsonl` für FHIR) und exponieren **identische Prometheus-Metriken** mit einem zusätzlichen `protocol`-Label.

### FHIR-Filter selbst testen

```bash
# Eine Test-Datei senden
curl -X POST -H "Content-Type: application/fhir+json" \
     --data @samples_fhir/icu_demo_bundle.json \
     http://localhost:8080/fhir/Bundle

# Antwort enthält Bundle/transaction-response oder OperationOutcome
```

### Dashboard mit Protocol-Filter

Das Grafana-Dashboard hat oben ein **Protokoll-Dropdown**. Standardmäßig „All" — zeigt beide Protokolle aggregiert. Auswahl von `hl7v2` oder `fhir_r4` filtert alle Panels auf nur einen Pfad. Zusätzlich gibt es ein neues Panel „Nachrichten-Rate pro Protokoll", das die beiden Pfade visuell trennt.

### Echte AION-FHIR-Anbindung

Im Compose-File `aion-fhir-mock` entfernen und `--forward` umstellen:

```yaml
sild-fhir-filter:
  command:
    - ...
    - "--forward"
    - "http://aion.intern.kliniknetz.de/fhir"
```

Der Filter postet auf `<forward-url>/fhir/Bundle` bzw. `<forward-url>/Bundle`.

### CAIRN-Plug-in-Slot (Roadmap)

In `sild_detector.py` wird `cairn.sild.SILDDetector` als Plug-in-Slot vorgehalten (try/except-Import). Dieser Slot ist bewusst **nicht** verkabelt: solange `cairn.sild` nicht freigegeben und mit Test belegt ist, bleibt der Inline-Detektor die einzige aktive Engine, und die Gauge `sild_using_real_cairn` meldet stets 0. Ein automatisches Umschalten auf eine "produktive" Implementierung passiert daher derzeit nicht.
