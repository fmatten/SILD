# AUDIT_BEFUND — SILD Due-Diligence (extern, schonungslos)

**Audit-Datum:** 2026-05-28
**Prüfer:** technische DD (externer Blickwinkel)
**Repo-Stand zum Audit (lokal & remote):** `58e8ce27` (sauber, identisch)
**Werkzeuge:** `git`, `gh`, statische Inspektion. **Keine Ausführung** des Codes.

---

## Closure-Status

**Closure-Datum:** 2026-05-28
**Closure-Release:** [v1.0.5 — Audit-Fix-Bundle](https://github.com/fmatten/SILD/releases/tag/v1.0.5) (Tag → `132fa708`)
**Closure-Range:** `58e8ce27..132fa708` (7 Commits)

Übersicht je Hypothese — Detail in der Befund-Tabelle, Spalte "Closure":

| # | Hypothese (Kurz) | Closure | Commit |
|---|---|---|---|
| H1 | Keine Tests / kein CI | **TEILWEISE GESCHLOSSEN** — Runner + 13/23 grün; CI-Workflow + Badge bewusst Roadmap (kein Badge ohne grünen Lauf) | `132fa70` |
| H2 | „Struktur statt Keywords" halb wahr | **GESCHLOSSEN** — toter Code raus, lebende Heuristik im Bericht offengelegt | `8dcc690` |
| H3 | Duplikate mit Drift | **GESCHLOSSEN** — 5 Top-Level-Dateien gelöscht (878 Zeilen weg) | `090f425` |
| H4 | „Echte" Engine fehlt / Hook nicht verkabelt | **TEILWEISE GESCHLOSSEN** — Marketing raus + Gauge entkoppelt; echte CAIRN-Delegation bewusst Roadmap | `df53001` |
| H5 | Verlust-Budget = flache Konstanten | **TEILWEISE GESCHLOSSEN** — Sprache + Rename `loss_budget_bits_estimate`; pro-Nachricht-Schätzer bewusst Roadmap | `619ce65` |
| H6 | Bus-Faktor 1 | **AKZEPTIERT, NICHT BESEITIGT** — Einzelautor-Projekt bleibt einer; CODEOWNERS optional als Follow-up | — |
| Z1 | Phantom-Pre-Squash-SHAs | **GESCHLOSSEN** — alle vier SHAs durch `pre-public-baseline` ersetzt | `b6ff011` |
| Z2 | Repo-URL codeberg vs. github | **GESCHLOSSEN** — INHALT.md:65 korrigiert | `0558fc4` |

**Roadmap-Items, die bewusst NICHT vorgetäuscht wurden:**

- **H1 (b)** GitHub-Actions-Workflow + Badge → erst nach grünem Lauf.
- **H4 (a)** Echter `cairn.sild.SILDDetector`-Delegations-Pfad → wenn `cairn.sild` freigegeben + getestet ist. Plug-in-Slot dokumentiert erhalten (`sild_detector.py:26-35`).
- **H5 (b)** Pro-Nachricht-Bit-Schätzer (Terminologie-Größe, Feld-Spezifität, Bundle-Kontext) → FM-4 §8.2 offen.
- **10 rote Vektoren** aus dem H1(a)-Runner sind die nächste konkrete Arbeitsliste (pro Regel im `KONFORMITAETSBERICHT.md`-Abschnitt „Automatisierte Vektor-Verifikation" aufgelistet).

**Was der DD-Prüfer jetzt auf `github.com/fmatten/SILD` sieht:**

- Keine Phantom-Commits in der Doku.
- Keine Datei-Duplikate, keine widersprüchlichen Versionen unter demselben Tag.
- Keine CAIRN-„höhere-Genauigkeit"-Marketing-Aussagen.
- Maschinell überprüfbare 13/23-Vektor-Aussage statt „vollständige Konformität".
- Korrekter Repo-URL in der Doku.
- Erhaltene Plug-in-Slots und Roadmap-Items sind als solche markiert, nicht als Fähigkeiten verkauft.

---

## Fazit (5 Zeilen)

1. **Was sofort überzeugt:** Saubere Trennung `sild.core` ↔ Carrier-Adapter (HL7v2/FHIR), präzise FM-4-Begriffsanwendung in `sild_detector.py`, gut strukturierter RFC-Entwurf v0.2, ehrlicher „NOT A MEDICAL DEVICE"-Disclaimer, dokumentierter Dual-Lizenz-Mechanismus, K-3/M-5/M-6/M-8 sind im Stack-Code tatsächlich verkabelt.
2. **Wo das Vertrauen wackelt — Geschichte:** Alle fünf Release-Tags zeigen auf denselben Commit; `KONFORMITAETSBERICHT.md`/`INHALT.md` referenzieren Commit-SHAs (`ae012a2`, `fbf2fa3`, `f185c28`, `739ad0d`), die im Repo nicht existieren.
3. **Wo das Vertrauen wackelt — Drift:** Vier Dateien liegen doppelt (`sild_fhir_filter.py`, `sild_fhir_target.py`, `docker-compose-v2.yml`, `Dockerfile-v2`); die Top-Level-Kopien sind veraltet und enthalten weder K-3 noch M-5/M-6/M-8/N-3, sind aber im selben Tag mit veröffentlicht.
4. **Wo das Vertrauen wackelt — Engine:** Der beworbene „CAIRN-Fallback auf höhere Accuracy" ist **nicht verkabelt**: `RealSILD = cairn.sild.SILDDetector` wird importiert, aber **nie aufgerufen**; die Gauge `sild_using_real_cairn=1` würde positiv aussehen, ohne dass irgendetwas anders rechnet.
5. **Wo das Vertrauen wackelt — Verifikation:** Es existiert weder CI noch ein ausführbares Test-Harness; die „Conformance Test Vectors v0.1" sind ein normatives Dokument ohne Runner. Die „vollständige FM-4-Konformität" ist eine Selbstinspektions-Behauptung, keine maschinell verifizierte Aussage.

---

## Befund-Tabelle (mit Closure-Spalte)

Inhalte unverändert seit Audit (Status / Beleg / Severity / Empfohlener Fix /
Aufwand) — Closure-Spalte rechts ergänzt.

| # | Hypothese | Status | Beleg (datei:zeile, Audit-Stand) | Severity | Empfohlener Fix | Aufwand | **Closure (v1.0.5, 2026-05-28)** |
|---|---|---|---|---|---|---|---|
| H1 | Keine ausführbaren Tests / kein CI; „vollständige FM-4-Konformität" ist Selbstinspektion | **BESTÄTIGT** | Kein `.github/`-Pfad; kein `tests/`, kein `pytest.ini`, kein `conftest.py`; `CONTRIBUTING.md:40` definiert Test = „docker compose up -d"; `SILD Conformance Test Vectors v0.1.md:5,45` ist Spezifikation ohne Runner; Behauptung `KONFORMITAETSBERICHT.md:20` „vollstandig" | **hoch** | (a) Python-Harness, der die YAML-Vektoren in `SILD Conformance Test Vectors v0.1.md` parst und `analyse_fhir_bundle()` gegen `expected_findings` ausführt; (b) GitHub-Actions-Workflow `.github/workflows/ci.yml` mit `pytest` + Vektor-Runner + Coverage; (c) Konformitätsbehauptung im Bericht nur dann als „vollständig" stehenlassen, wenn der Runner grün ist (Badge in README) | 2–4 PT | **TEILWEISE GESCHLOSSEN** (`132fa70`): (a) Runner steht (`tests/conformance_vectors.py`, `tests/test_conformance.py`) — 13/23 grün. Konformitätsbehauptung in `KONFORMITAETSBERICHT.md` durch 13/23-Aussage ersetzt. (b) CI-Workflow + Badge bewusst Roadmap: kein Badge ohne grünen Lauf. |
| H2 | „Struktur statt Keywords" nur halb wahr | **TEILWEISE** | Primär strukturell: `sild_detector.py:78-91` (`_fhir_cc_narrowing`, Mengen-Check gegen `FHIR_SPECIFIC_SYSTEMS`), `sild_detector.py:70-75` (`_hl7_ce_structured`). Aber Keyword-Pfade leben: `sild_detector.py:147-151` (`SPECIFIC_LAB_KEYWORDS`, 17 Wörter), genutzt `sild_detector.py:624-630` mit `kw in disp for disp in code_displays`; TC-Aggregat-Substring `sild_detector.py:602-609` `{"mean","average","avg","durchschnitt"}`; `.lower()`-Plattform `sild_detector.py:580-583`. Toter Code: `sild_detector.py:144-146` (`CONTINUOUS_PROCEDURE_KEYWORDS` — Definition ohne einzige Verwendung). Widerspruch zur Selbstdarstellung `KONFORMITAETSBERICHT.md:42-44` („Keyword-Matching" als _ursprüngliches_ Problem) | **mittel** | (a) Den Fallback-Pfad im Konformitätsbericht ausdrücklich benennen und als „Heuristik für generische Kategorien" deklarieren — nicht als Strukturanalyse. (b) `CONTINUOUS_PROCEDURE_KEYWORDS` löschen oder verkabeln (toter Code ist Trust-Killer in DD). (c) README-Schlagzeile (Z. 103-104) um Nebensatz „mit Keyword-Heuristik für Restfälle" ergänzen | 0.5 PT | **GESCHLOSSEN** (`8dcc690`): Toter `CONTINUOUS_PROCEDURE_KEYWORDS`-Set entfernt; neuer K-1-Abschnitt „Verbleibende Display-Heuristik" im `KONFORMITAETSBERICHT.md` benennt `SPECIFIC_LAB_KEYWORDS` + Aggregat-Wörter explizit als Heuristik. |
| H3 | Duplikate mit Drift: Top-Level vs. `sild_monitoring_stack/` | **BESTÄTIGT** | `sild_fhir_sender.py` md5 `ae6b94a0…` beide → identisch. `sild_fhir_target.py` 111 vs. 125 Zeilen → Top-Level **ohne N-3-Fix** (valide FHIR-Location, `sild_fhir_target.py:73` Diff). `sild_fhir_filter.py` 391 vs. 519 Zeilen → Top-Level **ohne K-3 / M-5 / M-6 / M-8** (`sild_fhir_filter.py` Import-Zeilen 47-51 fehlen; `_get_tenant_id`, `apply_severity_overrides`, `compute_loss_budget_bits`, `--profiles-de` fehlen). `docker-compose-v2.yml` ≡ `sild_monitoring_stack/docker-compose.yml` (byte-identisch); `Dockerfile-v2` ≡ `sild_monitoring_stack/Dockerfile`. Bericht selbst grenzt sich ein: `KONFORMITAETSBERICHT.md:5` „Analysierte Codebasis: `sild_monitoring_stack/`" — die Top-Level-Kopien wurden also **nicht geprüft**. Doku: `INHALT.md:50-60` listet nur Stack-Pfade, `README.md:73-74` Schnellstart `cd sild_monitoring_stack` → Top-Level-Pfad wird produktiv nie ausgeführt. | **hoch** (Footgun: stille kaputte Version unter dem gleichen Tag) | (a) Top-Level-Kopien löschen: `sild_fhir_filter.py`, `sild_fhir_target.py`, `sild_fhir_sender.py`, `docker-compose-v2.yml`, `Dockerfile-v2`. (b) Wenn der Wunsch ist, das Repo-Root als Entrypoint zu erhalten: Stack hoch ins Root ziehen und das Unterverzeichnis aufheben — _eine_ kanonische Position. (c) `.gitattributes`/`pre-commit`-Check, der Datei-Duplikate verhindert | 0.5–1 PT | **GESCHLOSSEN** (`090f425`): Variante (a) gewählt — 5 Top-Level-Dateien gelöscht (878 Zeilen). `PROJEKTBERICHT.md`-Tree um den „[veraltet]"-Block bereinigt. Optionaler `.gitattributes`/pre-commit-Hook nicht umgesetzt. |
| H4 | „Echte" Engine fehlt — und der Hook ist nicht verkabelt | **BESTÄTIGT (verschärft)** | `sild_detector.py:26-30` `try: from cairn.sild import SILDDetector as RealSILD … except ImportError: _USING_CAIRN = False`. **`grep -rn "RealSILD"` liefert genau eine Treffer-Zeile (den Import).** Es gibt **keinen Code-Pfad**, der `RealSILD` jemals aufruft. `_USING_CAIRN` wird ausschließlich von `using_real_cairn()` (`sild_detector.py:718-719`) gelesen und setzt die Prometheus-Gauge `sild_using_real_cairn` (`sild_fhir_filter.py:103`). `requirements.txt:11` `# cairn>=1.0.0` (auskommentiert). Marketing: `PROJEKTBERICHT.md:482-483` „Inline-Detector ist Fallback; produktive Accuracy erfordert das CAIRN Python-Paket"; `README.md:268-272` „Optional für höhere Erkennungsgenauigkeit". | **hoch** (Anschein-Risiko: Gauge=1 ohne semantische Wirkung) | (a) Entweder: Delegations-Pfad einbauen — `if _USING_CAIRN: return RealSILD().analyse(bundle)` (mit Fallback, mit Test). (b) Oder: den CAIRN-Hinweis aus `requirements.txt`/README/PROJEKTBERICHT entfernen und ehrlich sagen „die Inline-Engine ist die einzige verfügbare". (c) Mindestens: Gauge nur auf 1 setzen, wenn tatsächlich delegiert wird, nicht beim bloßen Import | (a) 1–3 PT; (b) 0.25 PT | **TEILWEISE GESCHLOSSEN** (`df53001`): Varianten (b) + (c) umgesetzt — Marketing raus, `using_real_cairn()` liefert immer `False`, Gauge meldet stets 0; Plug-in-Slot dokumentiert erhalten (`sild_detector.py:26-35`). (a) bewusst Roadmap: keine echte Delegation, bis `cairn.sild` freigegeben + getestet. |
| H5 | Verlust-Budget = flache Konstanten — Sprache präziser als Implementierung | **TEILWEISE BESTÄTIGT** | `sild_detector.py:121-127` `LOSS_BITS_PER_PATTERN`: vier statische Konstanten (`log2(95_000)`, `log2(60)`, `log2(16)`, `24.0`). `sild_detector.py:129-138` `compute_loss_budget_bits = sum(LOSS_BITS_PER_PATTERN.get(...))` — flacher Lookup, **kein Bezug** zu Nachrichten-Inhalt, Terminologie-Größe, Feld-Spezifität, Bundle-Kontext. README-Sprache: `README.md:146` „**Quantitative Verlust-Metrik (FM-4 §4)**"; `README.md:148` „Jede Übertragung erhält ein **Verlust-Budget in Bit**"; `PROJEKTBERICHT.md:476` „**Quantifizierbar:** Verlust-Budget in Bit". **Aber:** Der RFC selbst ist ehrlich (`Rfc draft v0.2.md:314`): „**Diese Zahlen sind nicht exakt** — sie sind Größenordnungs-Schätzungen … Empirische Kalibrierung ist offene Arbeit." `KONFORMITAETSBERICHT.md:464` listet §8.2 „Empirische Kalibrierung" als **nicht implementiert**. Die RFC ist also korrekt; README/PROJEKTBERICHT verkürzen. | **mittel** | (a) README-Z. 146 umformulieren: „**Verlust-Budget in Bit** (kategoriale Größenordnungs-Schätzung; pro Muster konstant, _nicht_ pro Nachricht kalibriert — siehe RFC §8 und §8.2)". (b) Falls echte Pro-Nachricht-Schätzung gewünscht: pro Loss-Event ein `bits_estimate`-Feld führen, das `_fhir_cc_narrowing`/`_hl7_ce_structured`-Befunde berücksichtigt (z. B. Display-Länge, Terminologie-Größe). (c) Bis dahin: `loss_budget_bits` als `loss_budget_bits_estimate` umbenennen — Signal an den Käufer, dass die Zahl ein Proxy ist | (a) 0.25 PT; (b) 2–3 PT | **TEILWEISE GESCHLOSSEN** (`619ce65`): Varianten (a) + (c) umgesetzt — Sprache in `README.md`/`PROJEKTBERICHT.md`/`KONFORMITAETSBERICHT.md` auf „kategoriale Größenordnungs-Schätzung, pro Muster konstant, nicht pro Nachricht kalibriert" angepasst; Feld/Funktion/JSON-Schlüssel/Prometheus-Metrik durchgängig auf `loss_budget_bits_estimate` umbenannt; M-6-Status TEILWEISE statt BEHOBEN. (b) bewusst Roadmap (FM-4 §8.2). |
| H6 | Bus-Faktor 1 | **BESTÄTIGT** | `gh api repos/fmatten/SILD/contributors`: ein Eintrag, `fmatten`, `contributions: 1`. `git log --all`: ein Commit `58e8ce27` `2026-05-27 04:28:19 +0200`, Autor Friedhelm Matten. Fünf Tags v1.0.0–v1.0.4 zeigen auf denselben SHA. `gh api repos/fmatten/SILD/stats/contributors` → `{}` (leer). | **mittel-hoch** (organisatorisch, nicht technisch) | (a) Realistisch: Bus-Faktor bleibt erstmal 1, das ist normal für ein Einzelautoren-Projekt. Aber: (b) Externe Reproducibility durch CI + Tag-Reproduzierbarkeit dokumentieren (Commit-SHA in Release-Notes statt verwaister Pre-Squash-SHAs). (c) `CODEOWNERS` einrichten, damit zumindest die Verantwortung explizit ist. (d) Für DD: einen zweiten Contributor (z. B. Reviewer mit `Co-authored-by`) auf den nächsten Releases ist ein günstiges Signal | 0.25 PT | **AKZEPTIERT, NICHT BESEITIGT**: Einzelautor-Projekt bleibt einer. Indirekte Verbesserung über Z1+v1.0.5: Tags zeigen wieder auf reproduzierbare SHAs, Release-Notes referenzieren echte Commits. CODEOWNERS und Co-Authored-by-Praxis bleiben optionales Follow-up. |
| Z1 | **Zusatzbefund: Tag-Theater + Phantom-Commits** | **BESTÄTIGT** | `gh api repos/fmatten/SILD/tags`: v1.0.0, v1.0.1, v1.0.2, v1.0.3, v1.0.4 zeigen **alle** auf `58e8ce277b3e4a857aac8b4b019ac816ba71b262`. `KONFORMITAETSBERICHT.md:6` „Git-Stand: `f185c28`"; `KONFORMITAETSBERICHT.md:28-32` zitiert `ae012a2`, `fbf2fa3`, `f185c28` als Behebungs-Commits; `INHALT.md:5` „Git-Stand: `739ad0d`". **Keiner dieser SHAs existiert in `git log`**. | **hoch** (Vertrauensschaden bei einem DD-Prüfer) | (a) Entweder die Pre-Squash-Historie öffentlich rekonstruieren (`git replace --graft` oder einfacher: pre-public-branch nachpushen). (b) Oder die SHA-Referenzen in `KONFORMITAETSBERICHT.md` und `INHALT.md` entfernen / durch „pre-public-baseline" ersetzen. Letzteres ist die ehrliche, billige Variante | 0.5 PT | **GESCHLOSSEN** (`b6ff011`): Variante (b) gewählt — vier Phantom-SHAs durch `pre-public-baseline` ersetzt in `KONFORMITAETSBERICHT.md`, `INHALT.md`, `PROJEKTBERICHT.md`. v1.0.5 ist das erste Tag, das auf einen tatsächlich existenten Commit (`132fa70`) zeigt. |
| Z2 | **Zusatzbefund: Repo-URL-Inkonsistenz** | **BESTÄTIGT** | `INHALT.md:65` „Repository: codeberg.org/fmatten/sild" — tatsächlich auf `github.com/fmatten/SILD` gehostet. `PROJEKTBERICHT.md:496` verweist CAIRN auf `codeberg.org/iscad/cairn`; Release-Notes v1.0.4 erwähnen Korrektur im RFC, aber `INHALT.md` ist nicht nachgezogen. | **niedrig** | URL in `INHALT.md:65` korrigieren | 5 min | **GESCHLOSSEN** (`0558fc4`): URL korrigiert. |

**Severity-Skala:** _niedrig_ = kosmetisch / leicht zu fixen; _mittel_ = inhaltlich falsche oder irreführende Aussage; _hoch_ = blockierender Vertrauensschaden im DD-Kontext oder latenter Footgun für den Anwender.

---

## PHASE 2 — Abgleich lokal ↔ `github.com/fmatten/SILD` (Audit-Stand)

**Ergebnis zum Audit-Zeitpunkt: Kein Code-Drift zwischen lokalem Repo und Public-Remote.**

| Aspekt | Lokal | Remote `origin/main` |
|---|---|---|
| HEAD-SHA | `58e8ce27` | `58e8ce27` |
| `git rev-list --count HEAD..origin/main` | 0 | — |
| `git rev-list --count origin/main..HEAD` | 0 | — |
| Working-Tree-Status | sauber (nichts unversioniert, nichts modifiziert) | — |
| Datei-Liste (Tree) | wie unten | identisch (per `gh api repos/fmatten/SILD/git/trees/main?recursive=1`) |

**Damit gab es keine „Code, der lokal existiert/fehlt"-Asymmetrien zwischen Arbeitsverzeichnis und Public-Remote.** Der gesamte in der Befund-Tabelle dokumentierte Drift war **intra-Repository** (Top-Level- vs. Stack-Kopien) — also bereits im veröffentlichten Stand drin.

**Was der Käufer am Audit-Tag sah (1:1 wie lokal):**
- 5 dupliziert ausgelieferte Dateien (siehe H3)
- 0 CI, 0 Test-Harness (siehe H1)
- 1 nicht-verkabelter CAIRN-Importhook (siehe H4)
- 5 Tags auf demselben Commit + Phantom-SHAs im Konformitätsbericht (siehe Z1)
- 1 falsche Repo-URL (siehe Z2)

**Was der Käufer ab v1.0.5 sieht (Closure-Stand `132fa70`):** siehe Abschnitt "Closure-Status" oben — alle obigen Punkte adressiert oder als Roadmap markiert.

---

## Closure-Entscheidungen (Protokoll)

Die fünf Rückfragen aus dem Audit-Bericht wurden vor der Umsetzung vom Autor entschieden. Festgehalten zur Nachvollziehbarkeit:

| Frage | Entscheidung |
|---|---|
| Layout (H3) | Variante A — Top-Level-Kopien löschen, `sild_monitoring_stack/` ist kanonisch. |
| CAIRN-Hook (H4) | (b) + (c) — Marketing entfernen, Gauge entkoppeln. (a) bewusst NICHT: keine Fähigkeit verkaufen, die nicht real und stabil ist. |
| Phantom-Commits (Z1) | (a) — durch `pre-public-baseline` ersetzen. Keine Historie-Rekonstruktion (wäre Theater). |
| Verlust-Budget (H5) | (a) jetzt — Text + Umbenennung auf `loss_budget_bits_estimate`. (b) bewusst NICHT jetzt (Roadmap). |
| CI (H1) | (a) jetzt — YAML-Runner unter pytest. (b) GitHub-Actions + Badge erst nach grünem Lauf. |

**Grundprinzip der Closure:**
> Kategorie A (Darstellung lief dem Code voraus) = jetzt begradigen.
> Roadmap-Punkte (früher Reifegrad) = nicht vortäuschen, nicht kaschieren.
> Lieber ehrlich offen lassen als unecht "erledigt" aussehen lassen.

Closure-Commit-Reihenfolge (nach Dringlichkeit für externe Prüfbarkeit): Z1 → H4 → H3 → H2 → Z2 → H5 → H1(a). Alle sieben Commits liegen unter Tag `v1.0.5` und Release [SILD v1.0.5 — Audit-Fix-Bundle](https://github.com/fmatten/SILD/releases/tag/v1.0.5).
