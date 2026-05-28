# SILD — Selbst-Audit und Remediation

**Methode:** technische Due-Diligence aus externem Blickwinkel, vom Autor auf das eigene Projekt angewandt
**Audit-Datum:** 2026-05-28
**Repo-Stand zum Audit (lokal & remote):** `58e8ce27` (sauber, identisch)
**Werkzeuge:** `git`, `gh`, statische Inspektion. Keine Ausführung des Codes.

> **Zweck dieses Dokuments.** Ich habe SILD demselben Prüfblick unterzogen, mit dem ich fremde Schnittstellen bewerte: aus externer Perspektive, beleggestützt, ohne Verlass auf interne Kenntnis. Festgehalten sind die Befunde zum Audit-Zeitpunkt, ihre Behebung und die Punkte, die bewusst auf der Roadmap bleiben. Leitlinie: Befunde, bei denen die Darstellung dem Code vorauseilte, werden begradigt; Punkte, die den frühen Reifegrad widerspiegeln, werden offen benannt statt überspielt.

---

## Status der Behebung (Closure)

**Closure-Datum:** 2026-05-28
**Closure-Releases:** [v1.0.5 — Audit-Fix-Bundle](https://github.com/fmatten/SILD/releases/tag/v1.0.5) (Kategorie-A-Fixes) · [v1.0.6 — B1: Conformance-Vektoren 23/23](https://github.com/fmatten/SILD/releases/tag/v1.0.6)
**Closure-Range:** `58e8ce27..7f7ce3d`

> **Nachtrag (v1.0.6).** Die zum v1.0.5-Stand noch offenen Conformance-Vektoren wurden im B1-Paket geschlossen: Alle **23/23 der spezifizierten Vektoren des verpflichtenden Mindest-Regelsatzes (RFC §9.2, v0.1, FHIR-Adapter) laufen lokal grün** — durch RFC-konforme Anhebungen des Detektors, ohne Vektoren oder Spezifikation zu schwächen. Offen bleiben bewusst nur die externe CI-Reproduktion samt Badge (H1 b) und die feldgenaue Pfad-Granularität.

Übersicht je Hypothese — Detail in der Befund-Tabelle, Spalte „Closure":

| # | Hypothese (Kurz) | Closure | Commit |
|---|---|---|---|
| H1 | Keine Tests / kein CI | **TEILWEISE GESCHLOSSEN** — Runner steht; mit v1.0.6 alle 23/23 der spezifizierten Vektoren grün (lokal); externe CI-Reproduktion + Badge bewusst Roadmap (kein Badge ohne CI-Lauf) | `132fa70` / `7f7ce3d` |
| H2 | „Struktur statt Keywords" halb zutreffend | **GESCHLOSSEN** — ungenutzter Code entfernt, verbleibende Heuristik im Bericht offengelegt | `8dcc690` |
| H3 | Redundante Dateien mit Drift | **GESCHLOSSEN** — 5 Top-Level-Dateien entfernt (878 Zeilen) | `090f425` |
| H4 | Alternativer Engine-Hook nicht verkabelt | **TEILWEISE GESCHLOSSEN** — Genauigkeits-Aussagen entfernt + Gauge entkoppelt; echte CAIRN-Delegation bewusst Roadmap | `df53001` |
| H5 | Verlust-Budget = kategoriale Konstanten | **TEILWEISE GESCHLOSSEN** — Sprache + Rename `loss_budget_bits_estimate`; pro-Nachricht-Schätzer bewusst Roadmap | `619ce65` |
| H6 | Einzelautoren-Projekt | **AKZEPTIERT, NICHT BESEITIGT** — bleibt einer; CODEOWNERS optional als Follow-up | — |
| Z1 | Commit-Referenzen ohne Entsprechung im Repo | **GESCHLOSSEN** — alle vier IDs durch `pre-public-baseline` ersetzt | `b6ff011` |
| Z2 | Repository-URL codeberg vs. github | **GESCHLOSSEN** — `INHALT.md:65` korrigiert | `0558fc4` |

**Roadmap-Punkte, die bewusst nicht als erledigt dargestellt werden:**

- **H1 (b)** GitHub-Actions-Workflow + Badge → erst nach vollständig grünem Lauf.
- **H4 (a)** Echter `cairn.sild.SILDDetector`-Delegations-Pfad → wenn `cairn.sild` freigegeben und getestet ist. Plug-in-Slot dokumentiert erhalten (`sild_detector.py:26-35`).
- **H5 (b)** Pro-Nachricht-Bit-Schätzer (Terminologie-Größe, Feld-Spezifität, Bundle-Kontext) → FM-4 §8.2, offen.
- **Feldgenaue Pfad-Granularität** (`strict_path`) → der Vektor-Vergleich ist derzeit ressource-stufig; sobald der Detektor feldgenaue Pfade (`Observation.code` statt `Observation/id`) liefert, wird strikt geprüft. Die zum v1.0.5-Stand 10 offenen Vektoren sind mit v1.0.6 geschlossen (siehe Nachtrag oben).

**Was auf `github.com/fmatten/SILD` ab v1.0.6 gilt:**

- Keine Commit-Referenzen ohne Entsprechung in der Doku.
- Keine redundanten Dateien und keine widersprüchlichen Versionen unter demselben Tag.
- Keine Aussagen zu nicht-aktiven Genauigkeits-Fähigkeiten.
- Maschinell überprüfbare 23/23-Vektor-Aussage (Mindest-Regelsatz RFC §9.2, lokal via pytest) statt „vollständiger Konformität"; CI-Badge erst nach externer Reproduktion.
- Korrekte Repository-URL in der Doku.
- Erhaltene Plug-in-Slots und Roadmap-Punkte sind als solche markiert, nicht als Fähigkeiten dargestellt.

---

## Fazit

Die folgenden fünf Punkte beschreiben den Stand **zum Audit-Zeitpunkt**; der aktuelle Stand ergibt sich aus der Closure-Spalte und dem Abschnitt oben.

1. **Was sofort überzeugt:** Saubere Trennung `sild.core` ↔ Carrier-Adapter (HL7v2/FHIR), präzise FM-4-Begriffsanwendung in `sild_detector.py`, gut strukturierter RFC-Entwurf v0.2, ehrlicher „NOT A MEDICAL DEVICE"-Disclaimer, dokumentierter Dual-Lizenz-Mechanismus; K-3/M-5/M-6/M-8 sind im Stack-Code tatsächlich verkabelt.
2. **Darstellung vs. Versionsgeschichte:** Zum Audit-Zeitpunkt zeigten alle fünf Release-Tags auf denselben Commit, und `KONFORMITAETSBERICHT.md`/`INHALT.md` referenzierten Commit-IDs (`ae012a2`, `fbf2fa3`, `f185c28`, `739ad0d`), die im Repository nicht existierten. → behoben (Z1).
3. **Darstellung vs. Drift:** Vier Dateien lagen doppelt (`sild_fhir_filter.py`, `sild_fhir_target.py`, `docker-compose-v2.yml`, `Dockerfile-v2`); die Top-Level-Kopien waren veraltet und enthielten weder K-3 noch M-5/M-6/M-8/N-3, wurden aber unter demselben Tag mit ausgeliefert. → behoben (H3).
4. **Darstellung vs. Engine:** Der als „CAIRN-Fallback auf höhere Genauigkeit" beschriebene Pfad war nicht verkabelt — `RealSILD = cairn.sild.SILDDetector` wurde importiert, aber nie aufgerufen; die Gauge `sild_using_real_cairn` hätte positiv erscheinen können, ohne dass sich an der Berechnung etwas ändert. → behoben (H4: Aussagen entfernt, Gauge entkoppelt).
5. **Darstellung vs. Verifikation:** Es existierten weder CI noch ein ausführbares Test-Harness; die „Conformance Test Vectors v0.1" waren ein normatives Dokument ohne Runner. „Vollständige FM-4-Konformität" war damit eine Selbstinspektions-Aussage, nicht maschinell verifiziert. → behoben (H1: Runner steht; mit v1.0.6 alle 23/23 der spezifizierten Vektoren grün, lokal; Aussage skopiert; externe CI-Reproduktion + Badge weiterhin Roadmap).

---

## Befund-Tabelle (mit Closure-Spalte)

Status / Beleg / Severity / empfohlener Fix / Aufwand entsprechen dem Audit-Stand; die Closure-Spalte rechts dokumentiert die Umsetzung.

| # | Hypothese | Status | Beleg (datei:zeile, Audit-Stand) | Severity | Empfohlener Fix | Aufwand | **Closure (v1.0.5–v1.0.6, 2026-05-28)** |
|---|---|---|---|---|---|---|---|
| H1 | Keine ausführbaren Tests / kein CI; „vollständige FM-4-Konformität" beruht auf Selbstinspektion | **BESTÄTIGT** | Kein `.github/`-Pfad; kein `tests/`, kein `pytest.ini`, kein `conftest.py`; `CONTRIBUTING.md:40` definiert Test = „docker compose up -d"; `SILD Conformance Test Vectors v0.1.md:5,45` ist Spezifikation ohne Runner; Aussage `KONFORMITAETSBERICHT.md:20` „vollstandig" | **hoch** | (a) Python-Harness, der die YAML-Vektoren parst und `analyse_fhir_bundle()` gegen `expected_findings` ausführt; (b) GitHub-Actions-Workflow mit `pytest` + Vektor-Runner + Coverage; (c) „Vollständig"-Aussage nur halten, wenn der Runner grün ist (Badge in README) | 2–4 PT | **TEILWEISE GESCHLOSSEN** (`132fa70` Runner; B1-Commits bis `7f7ce3d` / v1.0.6): (a) Runner steht (`tests/conformance_vectors.py`, `tests/test_conformance.py`); mit v1.0.6 laufen alle 23/23 der spezifizierten Vektoren grün (lokal). „Vollständig"-Aussage durch skopierte 23/23-Aussage ersetzt. (b) externe CI-Reproduktion + Badge weiterhin Roadmap: kein Badge ohne CI-Lauf. |
| H2 | „Struktur statt Keywords" nur teilweise zutreffend | **TEILWEISE** | Primär strukturell: `sild_detector.py:78-91` (`_fhir_cc_narrowing`), `sild_detector.py:70-75` (`_hl7_ce_structured`). Heuristik-Pfade bestehen weiter: `sild_detector.py:147-151` (`SPECIFIC_LAB_KEYWORDS`), genutzt `sild_detector.py:624-630`; TC-Aggregat-Substring `sild_detector.py:602-609`; `.lower()` `sild_detector.py:580-583`. Ungenutzter Code: `sild_detector.py:144-146` (`CONTINUOUS_PROCEDURE_KEYWORDS` ohne Verwendung). Spannung zur Selbstdarstellung `KONFORMITAETSBERICHT.md:42-44` | **mittel** | (a) Fallback-Pfad im Bericht ausdrücklich als „Heuristik für generische Kategorien" deklarieren — nicht als Strukturanalyse. (b) `CONTINUOUS_PROCEDURE_KEYWORDS` entfernen (ungenutzter Code fällt in einer Prüfung negativ auf). (c) README-Schlagzeile um „mit Keyword-Heuristik für Restfälle" ergänzen | 0.5 PT | **GESCHLOSSEN** (`8dcc690`): ungenutzter `CONTINUOUS_PROCEDURE_KEYWORDS`-Set entfernt; neuer Abschnitt „Verbleibende Display-Heuristik" im `KONFORMITAETSBERICHT.md` benennt die Heuristik explizit. |
| H3 | Redundante Dateien mit Drift: Top-Level vs. `sild_monitoring_stack/` | **BESTÄTIGT** | `sild_fhir_sender.py` md5 identisch. `sild_fhir_target.py` 111 vs. 125 Zeilen → Top-Level ohne N-3-Fix (`sild_fhir_target.py:73`). `sild_fhir_filter.py` 391 vs. 519 Zeilen → Top-Level ohne K-3 / M-5 / M-6 / M-8 (Import-Zeilen 47-51, `_get_tenant_id`, `apply_severity_overrides`, `compute_loss_budget_bits`, `--profiles-de` fehlen). `docker-compose-v2.yml` ≡ `sild_monitoring_stack/docker-compose.yml`; `Dockerfile-v2` ≡ Stack-Dockerfile. Bericht prüfte laut `KONFORMITAETSBERICHT.md:5` nur `sild_monitoring_stack/` — Top-Level-Kopien also ungeprüft. `README.md:73-74` Schnellstart `cd sild_monitoring_stack` → Top-Level-Pfad produktiv nie ausgeführt. | **hoch** (Risiko: veraltete, nicht gepflegte Kopie unter demselben Tag) | (a) Top-Level-Kopien entfernen. (b) Alternativ Stack ins Repo-Root ziehen — eine kanonische Position. (c) `.gitattributes`/`pre-commit`-Check gegen Duplikate | 0.5–1 PT | **GESCHLOSSEN** (`090f425`): Variante (a) — 5 Top-Level-Dateien entfernt (878 Zeilen). `PROJEKTBERICHT.md`-Tree bereinigt. Optionaler Hook nicht umgesetzt. |
| H4 | Alternativer Engine-Hook beschrieben, aber nicht verkabelt | **BESTÄTIGT — Befund präzisiert** | `sild_detector.py:26-30` importiert `RealSILD = cairn.sild.SILDDetector`. `grep -rn "RealSILD"` liefert genau eine Zeile (den Import); kein Code-Pfad ruft `RealSILD` auf. `_USING_CAIRN` wird nur von `using_real_cairn()` (`sild_detector.py:718-719`) gelesen und setzt die Gauge `sild_using_real_cairn` (`sild_fhir_filter.py:103`). `requirements.txt:11` `# cairn>=1.0.0` (auskommentiert). Aussagen: `PROJEKTBERICHT.md:482-483`, `README.md:268-272` („höhere Erkennungsgenauigkeit"). | **hoch** (Risiko: Telemetrie könnte aktive Nutzung suggerieren, ohne dass sie erfolgt) | (a) Delegations-Pfad einbauen (`if _USING_CAIRN: return RealSILD().analyse(...)`, mit Fallback und Test). (b) Oder CAIRN-Hinweis aus `requirements.txt`/README/PROJEKTBERICHT entfernen. (c) Mindestens: Gauge nur bei realer Delegation auf 1, nicht beim Import | (a) 1–3 PT; (b) 0.25 PT | **TEILWEISE GESCHLOSSEN** (`df53001`): (b) + (c) — Genauigkeits-Aussagen entfernt, `using_real_cairn()` liefert immer `False`, Gauge meldet stets 0; Plug-in-Slot dokumentiert erhalten. (a) bewusst Roadmap, bis `cairn.sild` freigegeben + getestet. |
| H5 | Verlust-Budget = kategoriale Konstanten — Sprache präziser als Implementierung | **TEILWEISE BESTÄTIGT** | `sild_detector.py:121-127` `LOSS_BITS_PER_PATTERN`: vier statische Konstanten. `sild_detector.py:129-138` flacher Lookup ohne Bezug zu Nachrichten-Inhalt/Terminologie/Feld-Spezifität. Sprache: `README.md:146,148` „Quantitative Verlust-Metrik" / „Verlust-Budget in Bit"; `PROJEKTBERICHT.md:476`. Der RFC selbst ist bereits ehrlich (`Rfc draft v0.2.md:314`: Größenordnungs-Schätzungen, empirische Kalibrierung offen); `KONFORMITAETSBERICHT.md:464` führt §8.2 als nicht implementiert. README/PROJEKTBERICHT verkürzten. | **mittel** | (a) README-Sprache an die RFC angleichen („kategoriale Größenordnungs-Schätzung; pro Muster konstant, nicht pro Nachricht kalibriert"). (b) Optional echter Pro-Nachricht-Schätzer. (c) `loss_budget_bits` → `loss_budget_bits_estimate` umbenennen | (a) 0.25 PT; (b) 2–3 PT | **TEILWEISE GESCHLOSSEN** (`619ce65`): (a) + (c) — Sprache angepasst; Feld/Funktion/JSON-Schlüssel/Prometheus-Metrik auf `loss_budget_bits_estimate` umbenannt; M-6-Status TEILWEISE statt BEHOBEN. (b) bewusst Roadmap (FM-4 §8.2). |
| H6 | Einzelautoren-Projekt | **BESTÄTIGT** | `gh api .../contributors`: ein Eintrag, `fmatten`. `git log --all`: ein Commit `58e8ce27`. Fünf Tags v1.0.0–v1.0.4 auf demselben SHA. `stats/contributors` leer. | **mittel-hoch** (organisatorisch, nicht technisch) | (a) Bus-Faktor bleibt zunächst 1 — für ein Einzelautoren-Projekt normal. (b) Reproduzierbarkeit über CI + Tags auf echte Commits. (c) `CODEOWNERS` für explizite Verantwortung. (d) Zweiter Reviewer (`Co-authored-by`) auf künftigen Releases als günstiges Signal | 0.25 PT | **AKZEPTIERT, NICHT BESEITIGT**: bleibt einer. Indirekte Verbesserung über Z1 + v1.0.5: Tags zeigen wieder auf reproduzierbare Commits, Release-Notes referenzieren echte SHAs. CODEOWNERS und Co-authored-by bleiben optionales Follow-up. |
| Z1 | Commit-Referenzen ohne Entsprechung im Repository | **BESTÄTIGT** | `gh api .../tags`: v1.0.0–v1.0.4 zeigen alle auf `58e8ce27…`. `KONFORMITAETSBERICHT.md:6,28-32` zitiert `ae012a2`, `fbf2fa3`, `f185c28`; `INHALT.md:5` `739ad0d`. Keine dieser IDs existiert in `git log`. | **hoch** (in einer externen Prüfung irreführend) | (a) Pre-Squash-Historie öffentlich rekonstruieren. (b) Oder die IDs in `KONFORMITAETSBERICHT.md`/`INHALT.md` durch „pre-public-baseline" ersetzen — die einfache, korrekte Variante | 0.5 PT | **GESCHLOSSEN** (`b6ff011`): Variante (b) — vier IDs durch `pre-public-baseline` ersetzt in `KONFORMITAETSBERICHT.md`, `INHALT.md`, `PROJEKTBERICHT.md`. v1.0.5 ist das erste Tag auf einem real existierenden Commit (`132fa70`). |
| Z2 | Repository-URL-Inkonsistenz | **BESTÄTIGT** | `INHALT.md:65` nennt „codeberg.org/fmatten/sild", gehostet wird auf `github.com/fmatten/SILD`. `PROJEKTBERICHT.md:496` verweist CAIRN auf `codeberg.org/iscad/cairn`; `INHALT.md` war nicht nachgezogen. | **niedrig** | URL in `INHALT.md:65` korrigieren | 5 min | **GESCHLOSSEN** (`0558fc4`): URL korrigiert. |

**Severity-Skala:** _niedrig_ = kosmetisch / leicht behebbar; _mittel_ = inhaltlich falsche oder irreführende Aussage; _hoch_ = in einer externen Prüfung stark vertrauensmindernd oder ein latentes Anwendungsrisiko.

---

## Abgleich lokal ↔ `github.com/fmatten/SILD` (Audit-Stand)

**Ergebnis zum Audit-Zeitpunkt: kein Code-Drift zwischen lokalem Repo und Public-Remote.**

| Aspekt | Lokal | Remote `origin/main` |
|---|---|---|
| HEAD-SHA | `58e8ce27` | `58e8ce27` |
| `git rev-list --count HEAD..origin/main` | 0 | — |
| `git rev-list --count origin/main..HEAD` | 0 | — |
| Working-Tree-Status | sauber | — |
| Datei-Liste (Tree) | wie Repo | identisch |

Der gesamte dokumentierte Drift war **intra-Repository** (Top-Level- vs. Stack-Kopien) — bereits im veröffentlichten Stand enthalten, kein lokaler Bearbeitungszustand vor dem Push.

**Stand am Audit-Tag:** 5 redundante Dateien (H3), 0 CI / 0 Test-Harness (H1), 1 nicht verkabelter Engine-Hook (H4), Commit-Referenzen ohne Entsprechung (Z1), 1 falsche Repo-URL (Z2).
**Stand ab v1.0.5 (`132fa70`):** siehe Abschnitt „Status der Behebung" — alle Punkte adressiert oder als Roadmap markiert.

---

## Entscheidungen zur Behebung (Protokoll)

Die fünf Rückfragen aus dem Audit wurden vor der Umsetzung vom Autor entschieden und sind zur Nachvollziehbarkeit festgehalten:

| Frage | Entscheidung |
|---|---|
| Layout (H3) | Variante A — Top-Level-Kopien entfernen, `sild_monitoring_stack/` ist kanonisch. |
| Engine-Hook (H4) | (b) + (c) — Genauigkeits-Aussagen entfernen, Gauge entkoppeln. (a) bewusst nicht: keine Fähigkeit darstellen, die nicht real und stabil ist. |
| Commit-Referenzen (Z1) | (a) — durch `pre-public-baseline` ersetzen. Keine Historie-Rekonstruktion (das wäre eine geschönte Darstellung). |
| Verlust-Budget (H5) | (a) jetzt — Text + Umbenennung auf `loss_budget_bits_estimate`. (b) bewusst Roadmap. |
| CI (H1) | (a) jetzt — YAML-Runner unter pytest. (b) GitHub-Actions + Badge erst nach grünem Lauf. |

**Grundprinzip der Behebung:**
> Wo die Darstellung dem Code vorauseilte: jetzt begradigen.
> Wo es der frühe Reifegrad ist: offen benennen, nicht vortäuschen und nicht kaschieren.
> Lieber ehrlich offen als unecht „erledigt".

Commit-Reihenfolge (nach Dringlichkeit für externe Prüfbarkeit): Z1 → H4 → H3 → H2 → Z2 → H5 → H1(a). Alle sieben Commits liegen unter Tag `v1.0.5` / Release [SILD v1.0.5 — Audit-Fix-Bundle](https://github.com/fmatten/SILD/releases/tag/v1.0.5).
