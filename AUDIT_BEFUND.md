# AUDIT_BEFUND — SILD Due-Diligence (extern, schonungslos)

**Datum:** 2026-05-28
**Prüfer:** technische DD (externer Blickwinkel)
**Repo-Stand lokal:** `58e8ce27` (sauber)
**Repo-Stand remote `github.com/fmatten/SILD`:** `58e8ce27` (identisch, 0 ahead / 0 behind)
**Werkzeuge:** `git`, `gh`, statische Inspektion. **Keine Ausführung** des Codes.

---

## Fazit (5 Zeilen)

1. **Was sofort überzeugt:** Saubere Trennung `sild.core` ↔ Carrier-Adapter (HL7v2/FHIR), präzise FM-4-Begriffsanwendung in `sild_detector.py`, gut strukturierter RFC-Entwurf v0.2, ehrlicher „NOT A MEDICAL DEVICE"-Disclaimer, dokumentierter Dual-Lizenz-Mechanismus, K-3/M-5/M-6/M-8 sind im Stack-Code tatsächlich verkabelt.
2. **Wo das Vertrauen wackelt — Geschichte:** Alle fünf Release-Tags zeigen auf denselben Commit; `KONFORMITAETSBERICHT.md`/`INHALT.md` referenzieren Commit-SHAs (`ae012a2`, `fbf2fa3`, `f185c28`, `739ad0d`), die im Repo nicht existieren.
3. **Wo das Vertrauen wackelt — Drift:** Vier Dateien liegen doppelt (`sild_fhir_filter.py`, `sild_fhir_target.py`, `docker-compose-v2.yml`, `Dockerfile-v2`); die Top-Level-Kopien sind veraltet und enthalten weder K-3 noch M-5/M-6/M-8/N-3, sind aber im selben Tag mit veröffentlicht.
4. **Wo das Vertrauen wackelt — Engine:** Der beworbene „CAIRN-Fallback auf höhere Accuracy" ist **nicht verkabelt**: `RealSILD = cairn.sild.SILDDetector` wird importiert, aber **nie aufgerufen**; die Gauge `sild_using_real_cairn=1` würde positiv aussehen, ohne dass irgendetwas anders rechnet.
5. **Wo das Vertrauen wackelt — Verifikation:** Es existiert weder CI noch ein ausführbares Test-Harness; die „Conformance Test Vectors v0.1" sind ein normatives Dokument ohne Runner. Die „vollständige FM-4-Konformität" ist eine Selbstinspektions-Behauptung, keine maschinell verifizierte Aussage.

---

## Befund-Tabelle

| # | Hypothese | Status | Beleg (datei:zeile) | Severity | Empfohlener Fix | Aufwand |
|---|---|---|---|---|---|---|
| H1 | Keine ausführbaren Tests / kein CI; „vollständige FM-4-Konformität" ist Selbstinspektion | **BESTÄTIGT** | Kein `.github/`-Pfad; kein `tests/`, kein `pytest.ini`, kein `conftest.py`; `CONTRIBUTING.md:40` definiert Test = „docker compose up -d"; `SILD Conformance Test Vectors v0.1.md:5,45` ist Spezifikation ohne Runner; Behauptung `KONFORMITAETSBERICHT.md:20` „vollstandig" | **hoch** | (a) Python-Harness, der die YAML-Vektoren in `SILD Conformance Test Vectors v0.1.md` parst und `analyse_fhir_bundle()` gegen `expected_findings` ausführt; (b) GitHub-Actions-Workflow `.github/workflows/ci.yml` mit `pytest` + Vektor-Runner + Coverage; (c) Konformitätsbehauptung im Bericht nur dann als „vollständig" stehenlassen, wenn der Runner grün ist (Badge in README) | 2–4 PT |
| H2 | „Struktur statt Keywords" nur halb wahr | **TEILWEISE** | Primär strukturell: `sild_detector.py:78-91` (`_fhir_cc_narrowing`, Mengen-Check gegen `FHIR_SPECIFIC_SYSTEMS`), `sild_detector.py:70-75` (`_hl7_ce_structured`). Aber Keyword-Pfade leben: `sild_detector.py:147-151` (`SPECIFIC_LAB_KEYWORDS`, 17 Wörter), genutzt `sild_detector.py:624-630` mit `kw in disp for disp in code_displays`; TC-Aggregat-Substring `sild_detector.py:602-609` `{"mean","average","avg","durchschnitt"}`; `.lower()`-Plattform `sild_detector.py:580-583`. Toter Code: `sild_detector.py:144-146` (`CONTINUOUS_PROCEDURE_KEYWORDS` — Definition ohne einzige Verwendung). Widerspruch zur Selbstdarstellung `KONFORMITAETSBERICHT.md:42-44` („Keyword-Matching" als _ursprüngliches_ Problem) | **mittel** | (a) Den Fallback-Pfad im Konformitätsbericht ausdrücklich benennen und als „Heuristik für generische Kategorien" deklarieren — nicht als Strukturanalyse. (b) `CONTINUOUS_PROCEDURE_KEYWORDS` löschen oder verkabeln (toter Code ist Trust-Killer in DD). (c) README-Schlagzeile (Z. 103-104) um Nebensatz „mit Keyword-Heuristik für Restfälle" ergänzen | 0.5 PT |
| H3 | Duplikate mit Drift: Top-Level vs. `sild_monitoring_stack/` | **BESTÄTIGT** | `sild_fhir_sender.py` md5 `ae6b94a0…` beide → identisch. `sild_fhir_target.py` 111 vs. 125 Zeilen → Top-Level **ohne N-3-Fix** (valide FHIR-Location, `sild_fhir_target.py:73` Diff). `sild_fhir_filter.py` 391 vs. 519 Zeilen → Top-Level **ohne K-3 / M-5 / M-6 / M-8** (`sild_fhir_filter.py` Import-Zeilen 47-51 fehlen; `_get_tenant_id`, `apply_severity_overrides`, `compute_loss_budget_bits`, `--profiles-de` fehlen). `docker-compose-v2.yml` ≡ `sild_monitoring_stack/docker-compose.yml` (byte-identisch); `Dockerfile-v2` ≡ `sild_monitoring_stack/Dockerfile`. Bericht selbst grenzt sich ein: `KONFORMITAETSBERICHT.md:5` „Analysierte Codebasis: `sild_monitoring_stack/`" — die Top-Level-Kopien wurden also **nicht geprüft**. Doku: `INHALT.md:50-60` listet nur Stack-Pfade, `README.md:73-74` Schnellstart `cd sild_monitoring_stack` → Top-Level-Pfad wird produktiv nie ausgeführt. | **hoch** (Footgun: stille kaputte Version unter dem gleichen Tag) | (a) Top-Level-Kopien löschen: `sild_fhir_filter.py`, `sild_fhir_target.py`, `sild_fhir_sender.py`, `docker-compose-v2.yml`, `Dockerfile-v2`. (b) Wenn der Wunsch ist, das Repo-Root als Entrypoint zu erhalten: Stack hoch ins Root ziehen und das Unterverzeichnis aufheben — _eine_ kanonische Position. (c) `.gitattributes`/`pre-commit`-Check, der Datei-Duplikate verhindert | 0.5–1 PT (je nach Layout-Entscheidung) |
| H4 | „Echte" Engine fehlt — und der Hook ist nicht verkabelt | **BESTÄTIGT (verschärft)** | `sild_detector.py:26-30` `try: from cairn.sild import SILDDetector as RealSILD … except ImportError: _USING_CAIRN = False`. **`grep -rn "RealSILD"` liefert genau eine Treffer-Zeile (den Import).** Es gibt **keinen Code-Pfad**, der `RealSILD` jemals aufruft. `_USING_CAIRN` wird ausschließlich von `using_real_cairn()` (`sild_detector.py:718-719`) gelesen und setzt die Prometheus-Gauge `sild_using_real_cairn` (`sild_fhir_filter.py:103`). `requirements.txt:11` `# cairn>=1.0.0` (auskommentiert). Marketing: `PROJEKTBERICHT.md:482-483` „Inline-Detector ist Fallback; produktive Accuracy erfordert das CAIRN Python-Paket"; `README.md:268-272` „Optional für höhere Erkennungsgenauigkeit". | **hoch** (Anschein-Risiko: Gauge=1 ohne semantische Wirkung) | (a) Entweder: Delegations-Pfad einbauen — `if _USING_CAIRN: return RealSILD().analyse(bundle)` (mit Fallback, mit Test). (b) Oder: den CAIRN-Hinweis aus `requirements.txt`/README/PROJEKTBERICHT entfernen und ehrlich sagen „die Inline-Engine ist die einzige verfügbare". (c) Mindestens: Gauge nur auf 1 setzen, wenn tatsächlich delegiert wird, nicht beim bloßen Import | (a) 1–3 PT je nach CAIRN-API-Stabilität; (b) 0.25 PT |
| H5 | Verlust-Budget = flache Konstanten — Sprache präziser als Implementierung | **TEILWEISE BESTÄTIGT** | `sild_detector.py:121-127` `LOSS_BITS_PER_PATTERN`: vier statische Konstanten (`log2(95_000)`, `log2(60)`, `log2(16)`, `24.0`). `sild_detector.py:129-138` `compute_loss_budget_bits = sum(LOSS_BITS_PER_PATTERN.get(...))` — flacher Lookup, **kein Bezug** zu Nachrichten-Inhalt, Terminologie-Größe, Feld-Spezifität, Bundle-Kontext. README-Sprache: `README.md:146` „**Quantitative Verlust-Metrik (FM-4 §4)**"; `README.md:148` „Jede Übertragung erhält ein **Verlust-Budget in Bit**"; `PROJEKTBERICHT.md:476` „**Quantifizierbar:** Verlust-Budget in Bit". **Aber:** Der RFC selbst ist ehrlich (`Rfc draft v0.2.md:314`): „**Diese Zahlen sind nicht exakt** — sie sind Größenordnungs-Schätzungen … Empirische Kalibrierung ist offene Arbeit." `KONFORMITAETSBERICHT.md:464` listet §8.2 „Empirische Kalibrierung" als **nicht implementiert**. Die RFC ist also korrekt; README/PROJEKTBERICHT verkürzen. | **mittel** | (a) README-Z. 146 umformulieren: „**Verlust-Budget in Bit** (kategoriale Größenordnungs-Schätzung; pro Muster konstant, _nicht_ pro Nachricht kalibriert — siehe RFC §8 und §8.2)". (b) Falls echte Pro-Nachricht-Schätzung gewünscht: pro Loss-Event ein `bits_estimate`-Feld führen, das `_fhir_cc_narrowing`/`_hl7_ce_structured`-Befunde berücksichtigt (z. B. Display-Länge, Terminologie-Größe). (c) Bis dahin: `loss_budget_bits` als `loss_budget_bits_estimate` umbenennen — Signal an den Käufer, dass die Zahl ein Proxy ist | (a) 0.25 PT; (b) 2–3 PT |
| H6 | Bus-Faktor 1 | **BESTÄTIGT** | `gh api repos/fmatten/SILD/contributors`: ein Eintrag, `fmatten`, `contributions: 1`. `git log --all`: ein Commit `58e8ce27` `2026-05-27 04:28:19 +0200`, Autor Friedhelm Matten. Fünf Tags v1.0.0–v1.0.4 zeigen auf denselben SHA. `gh api repos/fmatten/SILD/stats/contributors` → `{}` (leer). | **mittel-hoch** (organisatorisch, nicht technisch) | (a) Realistisch: Bus-Faktor bleibt erstmal 1, das ist normal für ein Einzelautoren-Projekt. Aber: (b) Externe Reproducibility durch CI + Tag-Reproduzierbarkeit dokumentieren (Commit-SHA in Release-Notes statt verwaister Pre-Squash-SHAs). (c) `CODEOWNERS` einrichten, damit zumindest die Verantwortung explizit ist. (d) Für DD: einen zweiten Contributor (z. B. Reviewer mit `Co-authored-by`) auf den nächsten Releases ist ein günstiges Signal | 0.25 PT (CODEOWNERS), Vertrauensaufbau dauerhaft |
| Z1 | **Zusatzbefund: Tag-Theater + Phantom-Commits** | **BESTÄTIGT** | `gh api repos/fmatten/SILD/tags`: v1.0.0, v1.0.1, v1.0.2, v1.0.3, v1.0.4 zeigen **alle** auf `58e8ce277b3e4a857aac8b4b019ac816ba71b262`. `KONFORMITAETSBERICHT.md:6` „Git-Stand: `f185c28`"; `KONFORMITAETSBERICHT.md:28-32` zitiert `ae012a2`, `fbf2fa3`, `f185c28` als Behebungs-Commits; `INHALT.md:5` „Git-Stand: `739ad0d`". **Keiner dieser SHAs existiert in `git log`**. | **hoch** (Vertrauensschaden bei einem DD-Prüfer) | (a) Entweder die Pre-Squash-Historie öffentlich rekonstruieren (`git replace --graft` oder einfacher: pre-public-branch nachpushen). (b) Oder die SHA-Referenzen in `KONFORMITAETSBERICHT.md` und `INHALT.md` entfernen / durch „pre-public-baseline" ersetzen. Letzteres ist die ehrliche, billige Variante | 0.5 PT |
| Z2 | **Zusatzbefund: Repo-URL-Inkonsistenz** | **BESTÄTIGT** | `INHALT.md:65` „Repository: codeberg.org/fmatten/sild" — tatsächlich auf `github.com/fmatten/SILD` gehostet. `PROJEKTBERICHT.md:496` verweist CAIRN auf `codeberg.org/iscad/cairn`; Release-Notes v1.0.4 erwähnen Korrektur im RFC, aber `INHALT.md` ist nicht nachgezogen. | **niedrig** | URL in `INHALT.md:65` korrigieren | 5 min |

**Severity-Skala:** _niedrig_ = kosmetisch / leicht zu fixen; _mittel_ = inhaltlich falsche oder irreführende Aussage; _hoch_ = blockierender Vertrauensschaden im DD-Kontext oder latenter Footgun für den Anwender.

---

## PHASE 2 — Abgleich lokal ↔ `github.com/fmatten/SILD`

**Ergebnis: Kein Code-Drift zwischen lokalem Repo und Public-Remote.**

| Aspekt | Lokal | Remote `origin/main` |
|---|---|---|
| HEAD-SHA | `58e8ce27` | `58e8ce27` |
| `git rev-list --count HEAD..origin/main` | 0 | — |
| `git rev-list --count origin/main..HEAD` | 0 | — |
| Working-Tree-Status | sauber (nichts unversioniert, nichts modifiziert) | — |
| Datei-Liste (Tree) | wie unten | identisch (per `gh api repos/fmatten/SILD/git/trees/main?recursive=1`) |

**Damit gibt es keine „Code, der lokal existiert/fehlt"-Asymmetrien zwischen deinem Arbeitsverzeichnis und dem, was ein Käufer sehen würde.** Der gesamte in der Befund-Tabelle dokumentierte Drift ist **intra-Repository** (Top-Level- vs. Stack-Kopien) — also bereits im veröffentlichten Stand drin, nicht ein lokaler Bearbeitungszustand vor Push.

**Was der Käufer also sieht (1:1 wie lokal):**
- 5 dupliziert ausgelieferte Dateien (siehe H3)
- 0 CI, 0 Test-Harness (siehe H1)
- 1 nicht-verkabelter CAIRN-Importhook (siehe H4)
- 5 Tags auf demselben Commit + Phantom-SHAs im Konformitätsbericht (siehe Z1)
- 1 falsche Repo-URL (siehe Z2)

---

## Rückfragen vor Korrekturen

Ich habe noch keinen Code geändert. Bevor du grünes Licht gibst, brauche ich von dir Entscheidungen:

1. **Layout (H3-Fix).** Soll ich die Top-Level-Kopien (`sild_fhir_filter.py`, `sild_fhir_target.py`, `sild_fhir_sender.py`, `docker-compose-v2.yml`, `Dockerfile-v2`) **löschen** (Stack ist kanonisch), oder umgekehrt die Stack-Dateien **nach oben verschieben** und das Unterverzeichnis abschaffen? Die Doku (`INHALT.md`, `README.md:73`) legt klar Variante A nahe — ich frage aber, weil es einen impact auf Docker-Compose-Pfade hat.

2. **CAIRN-Hook (H4-Fix).** Soll ich (a) `RealSILD` tatsächlich als Delegations-Pfad einbauen, (b) den CAIRN-Hinweis komplett entfernen, oder (c) als Plug-in-Stelle stehenlassen, aber dann die Prometheus-Gauge nur auf 1 setzen, wenn ein realer Aufruf erfolgt? Variante (a) ist die ehrlichste, aber abhängig davon, ob `cairn.sild.SILDDetector` eine kompatible API hat — kennst du die?

3. **Phantom-Commits (Z1-Fix).** Lieber (a) die alten SHAs durch `pre-public-baseline` ersetzen (billig, ehrlich), oder (b) die Vorgeschichte aus deinem lokalen Pre-Squash rekonstruieren und pushen (teurer, sieht besser aus)?

4. **Verlust-Budget (H5-Fix).** Reicht dir die Textänderung in README (Variante a — „Größenordnungs-Schätzung"), oder soll ich tatsächlich einen pro-Nachricht-Schätzer in `LossEvent.bits_estimate` einbauen (Variante b, ~2–3 PT)?

5. **CI (H1-Fix).** Soll ich (a) nur einen YAML-Parser + Vektor-Runner bauen und `pytest` darauf aufsetzen, oder (b) zusätzlich einen GitHub-Actions-Workflow mit Matrix-Tests (Py 3.10/3.11/3.12) und Coverage-Badge?

Sobald du diese fünf Punkte beantwortet hast, kann ich die Fixes in der Reihenfolge ihrer Severity (H3 → H4 → Z1 → H1 → H2 → H5 → H6 → Z2) als getrennte Commits umsetzen.
