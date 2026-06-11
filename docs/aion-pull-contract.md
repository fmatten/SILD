# SILD→AION Pull-Kontrakt (M-4)

**Status:** v1, Stand M-2 Stufe 1–3 + M-4.
**Bindet:** den AION-Konsumenten **B.1b** (AION-Repo — NICHT Teil von M-4).
**Geltungsbereich:** EINE M-2-Mapper-DB (s. §8 Scope-Annahmen).

---

## 1. Transport: Pull, read-only

AION liest die M-2-SQLite-DB **read-only** (`mode=ro` + `PRAGMA query_only=ON`),
exakt wie M-2 die M-1-DB liest — durchgehende Lese-Kette, kein Push, kein REST.
AION schreibt NIE in die M-2-DB.

**Die Vertragsfläche sind ausschließlich die drei SQL-Views** in §3–§5
(`v_aion_stay`, `v_aion_segment`, `v_aion_change`). Alle anderen Tabellen sind
internes Schema und dürfen sich ohne Ankündigung ändern; die View-Spalten sind
stabil (Garantie M4-G1, getestet). Wer an den Views vorbei liest, verliert
jede Kompatibilitätszusage.

## 2. Zwei Ströme + Idempotenz (K1/K2)

| Strom | View | Zweck |
|---|---|---|
| 1 | `v_aion_stay` + `v_aion_segment` | aktueller Stand aller Aufenthalte |
| 2 | `v_aion_change` | Änderungs-Log für schon konsumierte Stays |

- **K2 — Identität + Revision:** `stay_id` ist stabil und wird über alle
  Mutationen hinweg NIE neu vergeben (AUTOINCREMENT, Mutationen sind
  in-place-Updates; auch ein per A11 stornierter Stay behält seine Zeile mit
  `status='cancelled'`). `revision` beginnt bei 1 und erhöht sich bei **jeder
  sichtbaren Veränderung** (Vorwärtsbau, Stufe-2-Mutation, wirksame
  Schätzungs-Neuableitung) — **atomar in derselben Transaktion** wie die
  Veränderung: ein Leser sieht nie eine neue Revision mit altem Zustand oder
  umgekehrt. Idempotenter Konsum = Dedup über `(stay_id, revision)`.
- **K1 — selbst-erklärende Änderungen:** jede `v_aion_change`-Zeile trägt den
  **vollständigen neuen Stay-Zustand** (`after_json`). AION kann eine Änderung
  verarbeiten, OHNE den Stay vorher aus Strom 1 zu kennen, und darf sich
  **NICHT auf die Strom-Reihenfolge verlassen** — bei mehreren Änderungen
  desselben Stays gewinnt die höchste `revision`, nicht die zuletzt gelesene
  Zeile.
- **Cursor:** `notification_id` ist AUTOINCREMENT — monoton wachsend, nie
  wiederverwendet. Vorwärts-Cursor: `WHERE notification_id > :cursor ORDER BY
  notification_id`. Eine Zeile erscheint in `v_aion_change` erst, wenn ihre
  Mutation committet ist (INNER JOIN auf den atomar geschriebenen Payload).
- **Vorwärtsbau ist NICHT im Strom 2:** das laufende Aufbauen eines Stays
  (A04/A01/A02/A03) erhöht nur die Revision; Strom 2 enthält Rückwirkungen
  (Storno/Update/verspätet) und wirksame Schätzungs-Änderungen. Konsum-Muster:
  Strom 1 periodisch nach `(stay_id, revision)`-Deltas pollen, Strom 2 für
  Rückwirkungs-Details.

## 3. `v_aion_stay` — Stays (PID-TRAGEND)

| Spalte | Bedeutung |
|---|---|
| `stay_id` | stabile, DB-lokale Identität (K2) |
| `revision` | Revisionsnummer (K2), 0 = nie geschrieben (kommt nicht vor) |
| `pattern` | Eintrittsmuster: `A` (direkt stationär), `B` (NA→stationär), `C` (ambulant), `pending` (A04-Episode im Join-Fenster, noch unentschieden) |
| `status` | `open` / `closed` / `cancelled` (A11-Storno: Zeile bleibt, Segmente sind weg) |
| `patient_key` | **PID** — `Authority\|ID` (PID-3, MR) |
| `visit_id` | **PID-nah** — Visit-Nummer (advisory, korpus-kalibrierte Extraktion) |
| `opened_event_ts` / `closed_event_ts` | Stay-Grenzen (ISO-UTC); `closed_event_ts` NULL solange offen |
| `stay_markers` | Komma-Liste der Stay-Plausibilitäts-Marker (§6.3) oder NULL |

## 4. `v_aion_segment` — Lage-Segmente (PID-frei, Quasi-Identifikator)

| Spalte | Bedeutung |
|---|---|
| `stay_id`, `revision` | wie oben (Join-Schlüssel + K2) |
| `segment_id`, `seq` | Segment-Identität + Ordnung im Stay |
| `pv1_3_raw`, `ward`, `room`, `bed` | **rohe PV1-3-Komponenten** (Gap-2-Ableitungsschlüssel, §6.5) |
| `start_ts`, `start_provenance` | Segment-Start + Provenienz der Grenze |
| `end_ts`, `end_provenance` | Segment-Ende; **NULL = OFFEN** (§6.4) |
| `is_open` | 1 wenn `end_ts` NULL |
| `segment_markers` | Komma-Liste der Segment-Plausibilitäts-Marker oder NULL |
| `estimate_lower/upper` | Schranken [t₁,t₂] der geschätzten Grenzseite (§6.2), NULL wenn keine |
| `estimate_lower_source/upper_source` | Receipt-IDs der zwei Schranken-Quellen |

Provenienz-Werte pro Grenzseite: `measured` (PV1-44/45, ZBE-2) · `event`
(EVN-6) · `recorded_substitute` (EVN-2-Erfassungs-Ersatz, markiert) ·
`estimated` (§6.1/6.2). Nur **aktive** Schätzungen erscheinen — `waiting`/
`reverted_hold` haben keine Segmente (der zugrunde liegende M-1-Hold ist
autoritativ und für AION unsichtbar).

## 5. `v_aion_change` — Änderungs-Log (PID-frei, Quasi-Identifikator)

| Spalte | Bedeutung |
|---|---|
| `notification_id` | **Cursor** (monoton, AUTOINCREMENT) |
| `stay_id`, `revision` | K2: der Zustand, den diese Änderung ERZEUGT hat |
| `kind` | `revoke_stay` · `remove_boundary` · `reopen_last` · `change_boundary` · `insert_boundary` · `estimate_applied` · `estimate_updated` · `estimate_reverted` |
| `after_json` | **K1: vollständiger neuer Stay-Zustand** — `{"stay": {...}, "segments": [...]}`, PID-frei (kein patient_key, keine Visit), feld-gleich dem DB-Stand der Revision (SF-1: derselbe Plan-Anwender erzeugt beides) |
| `receipt_id` | auslösendes Event (Korrelation, nicht Konsum-Schlüssel) |
| `created_ts` | Schreibzeit der Notification |

## 6. Lese-Regeln (verbindlich für B.1b)

### 6.1 ε-DP-Schutz: `PROV_ESTIMATED` MUSS ausschließbar sein
Geschätzte Grenzen sind über das Provenienz-Feld **sauber isolierbar**
(Mapper-Pflicht, M4-G6). Eine geschätzte Kontaktzeit in einer ε-DP-Abfrage
wäre fabriziertes Signal unter harter Garantie — **AION MUSS geschätzte
Grenzen aus DP-Abfragen ausschließen können**; das Ausschließen selbst ist
AION-seitige Entscheidung. Filter-Muster:

```sql
SELECT * FROM v_aion_segment
WHERE start_provenance != 'estimated'
  AND (end_provenance IS NULL OR end_provenance != 'estimated');
```

### 6.2 Maximal-Ausdehnungs-Kodierung (geschätzte Grenzen sind SCHRANKEN)
Eine `estimated`-Grenzseite kodiert eine **Schranke, keinen Punkt**:
Vorgänger-Ende = t₂ (spätestmöglich), Nachfolger-Start = t₁ (frühestmöglich).
Die beiden Segmente um eine geschätzte Grenze **überlappen darum bewusst**
über das volle Intervall [t₁,t₂]. AION darf eine `estimated`-Zeit NIE als
gemessene Zeit lesen; Mittelpunkt/Intervall/Ausschluss entscheidet AION.
Die Schranken + Quell-Events stehen an der Zeile (`estimate_*`-Spalten).

### 6.3 Plausibilitäts-Marker: defensiv behandeln
Markierte Artefakte sind **treu gebaut, mit Originalzeiten, NIE repariert**
(der Mapper markiert, AION bewertet). AION muss sie defensiv behandeln
(isolieren / filtern / bewusst einbeziehen), besonders strukturell entartete,
die eine Δ_con-Rechnung still korrumpieren würden:
`negative_duration` (Ende < Start!) · `zero_duration` · `implausible_order`
(Entlassung vor Aufnahme) · `overlapping_open_stays` · `orphan_transfer` ·
`unknown_ward` (nur bei Standort-Konfiguration) · `excessive_duration`
(klassen-differenziert; langer ITS-Aufenthalt ist legitim). Marker sind
ABGELEITET: sie können mit einer neuen Revision verschwinden.

### 6.4 Offene Segmente
`end_ts` NULL = offen (NIE last-known-time). Welcher Bezugszeitpunkt für
„noch andauernd" in Δ_con gilt, entscheidet AION — der Mapper liefert NULL
und nie eine geschätzte Endzeit.

### 6.5 Gap-2 / Kontakt-Einheit
`v_aion_segment` liefert die **rohen PV1-3-Komponenten**; die Kontakt-Einheit
wird zur Compute-Zeit kollabiert (ward = `ward`, room = `ward^room`, bed =
`ward^room^bed`; fehlende feinere Komponente → Stationsebene). Der Mapper
verschmilzt angrenzende gleiche Einheiten NIE (Gap 2) — die Verschmelzung ist
eine AION-seitige Δ_con-Regel. Kontakt nur bei zeitlicher Überlappung
(halb-offene Intervalle, berühren ≠ überlappen).

### 6.6 Revisionswechsel und Erasure
- Ein Stay kann zwischen zwei Pulls mehrere Revisionen durchlaufen; Strom 2
  enthält je wirksamer Rückwirkung eine Zeile. No-Op-Neuableitungen erzeugen
  KEINE Zeile (kein Rauschen).
- **Erasure (DSGVO):** Stays/Segmente/Änderungs-Payloads eines Patienten
  können VERSCHWINDEN (auch rückwirkend aus `v_aion_change`). AION muss
  verschwundene `stay_id`s tolerieren und darf gelöschte Daten nicht aus
  eigenen Kopien rekonstruieren — die Lösch-Pflicht propagiert (AION-seitiges
  Erasure ist AION-M2-Paket, nicht dieser Kontrakt).

### 6.7 „Stay nicht mehr aktiv": Storno vs. Erasure unterscheiden
„Stay nicht mehr aktiv" hat ZWEI verschiedene Ursachen mit verschiedener
Sichtbarkeit — B.1b MUSS sie unterscheiden:

- **Storno (A11) — fachliches Event, sichtbar:** der Stay BLEIBT in
  `v_aion_stay` mit `status='cancelled'`, erhöhter Revision UND einer
  `v_aion_change`-Zeile (`kind='revoke_stay'`, after-Zustand mit leerer
  Segmentliste). AION sieht das Faktum samt Erklärung im Änderungs-Strom
  und verarbeitet es als Rückwirkung.
- **Erasure (PID-Löschung) — KEIN fachliches Event, spurlos:** der Stay
  verschwindet VOLLSTÄNDIG aus `v_aion_stay`/`v_aion_segment`/
  `v_aion_change`, OHNE change-Zeile. Das ist ABSICHT, nicht Lücke: eine
  Benachrichtigung „Stay X gelöscht" mit `stay_id` wäre selbst ein
  Re-Verknüpfungs-Residuum (SF-2-Logik) — Erasure hinterlässt bewusst
  keinen Strom-Eintrag (getestet, M4-G7).

**Regel für B.1b:**
- Stay weg + zugehörige `cancelled`-Zeile bzw. `revoke_stay`-change-Zeile
  vorhanden → **Storno**: fachlich verarbeiten.
- Stay weg + KEINE change-Zeile → **Erasure**: kein Fehler. AION muss seine
  eingerechneten Daten zu diesem Stay verwerfen, OHNE eine Erklärung im
  Strom zu erwarten.

**Konsequenz:** AION darf NICHT annehmen, dass einmal gesehene Stays stabil
existieren — jeder Pull kann früher gesehene `stay_id`s verlieren.

## 7. PID-Scope (was AION sehen DARF)

| Fläche | Einstufung |
|---|---|
| `v_aion_stay` | **PID-TRAGEND** (`patient_key`, `visit_id`) — Zugriff nur für den autorisierten B.1b-Konsumenten; Weitergabe/Ablage unterliegt denselben Pflichten wie die Mapper-DB (Encryption-at-rest an Ops delegiert) |
| `v_aion_segment` | PID-frei, aber **Quasi-Identifikator** (Standort+Zeit-Sequenzen, über `stay_id` re-verknüpfbar) |
| `v_aion_change` | PID-frei, aber **Quasi-Identifikator** (after_json = Standort+Zeit-Sequenzen) |

## 8. Scope-Annahmen (benannt, nicht gelöst)

- **`stay_id` ist DB-LOKAL** (kein UUID): eindeutig nur innerhalb EINER
  M-2-Mapper-DB. Beim heutigen Ein-DB-Pull ausreichend; eine Zusammenführung
  mehrerer Mapper-DBs wäre NICHT kollisionsfrei (heute kein Fall — bei
  Mehr-DB-Betrieb braucht der Kontrakt eine DB-Instanz-Kennung).
- Bereits herausgegebene Resultate (DP-Antwort/Report) sind nicht
  zurückrufbar; ob ein herausgegebenes Resultat von einer Rückwirkung
  betroffen ist, entscheidet AION (Auswertungs-Audit/Admin-Konsole).
- Zeiten sind ISO-8601-UTC-Strings (lexikographisch sortierbar).

## 9. Garantien (jede mit benanntem Test in tests/test_mapper_m4.py)

| # | Garantie |
|---|---|
| M4-G1 | Views liefern exakt die definierten Spalten (Vertragsfläche stabil) |
| M4-G2 | Revision monoton, an allen 6 Schreibstellen, atomar mit dem Zustand |
| M4-G3 | No-Op-Neuableitung still; wirksame → Revision+1 + genau EINE Notification |
| M4-G4 | K1: `v_aion_change`-Zeile verarbeitbar ohne Vorwissen (vollständiger Zustand) |
| M4-G5 | K2: `(stay_id, revision)` stabil + eindeutig im Änderungs-Strom |
| M4-G6 | `PROV_ESTIMATED` über `v_aion_segment` ausschließbar |
| M4-G7 | `stay_revision`/`change_payload` erasure-sauber (kein Residuum) |
