# Synthetischer ADT-Korpus (M-2 Stufe 1) — 54 Nachrichten

**Status: SYNTHETISCH. Von Friedhelm konstruiert. An echten Daten zu verifizieren.**
Keine echten Patientendaten. Zweck: Test-/Entwicklungsgrundlage für den ADT-Mapper
M-2 (Sequenz-/Intervall-Rekonstruktion). Dies ist Friedhelms Korpus, **nicht** von
Claude Code erfundene Fixtures.

## Inhalt
- 54 Einzelnachrichten, eine `.hl7`-Datei pro Nachricht
  (`msgNNNNNN_<typ>_<patient>.hl7`), ein Segment pro Zeile.
- `all_messages.hl7` — alle 54 in einer Datei, in Sende-Reihenfolge.

## Normalisierung (bewusst, nicht still)
- **MSH-2 = `^~\&`** (HL7-konform) — wie geliefert in Teilen 1–2; Teile 3–5 trugen
  ein Copy-/Paste-Artefakt `^~&`, durchgängig auf `^~\&` normalisiert.
- **Segment-Terminator = `\r`** (HL7/MLLP-kanonisch). Die Quelle wurde mit `\n`
  geliefert; auf `\r` normalisiert, damit der Korpus sowohl über `parse_hl7v2`
  (normalisiert ohnehin) als auch über den MLLP-Pfad ohne Konvertierung läuft.
  *Triviale Ein-Zeichen-Änderung, falls `\n` gewünscht.*

## Verteilung (verifiziert gegen Manifest — alle OK)
ADT^A01=6, ADT^A02=5, ADT^A03=2, ADT^A04=6, ORM^O01=16, ORU^R01=15, MDM^T02=3,
ORR^O02=1 → **54**; 19 ADT (relevant für M-2).

## Patienten / verifizierte ADT-Sequenzen (aus den Bytes)
- P100001: A04(O/NA) → A01(I/IM1)                       — Muster B
- P100002: A04(O/NA) → A01(I/CH1) → A02(I/ENDO)         — Muster B + Verlegung *(s. Befund)*
- P100003: A04(O/NA) → A01(I/IM2)                       — Muster B
- P100004: A04(O/AMB) → A03(O/AMB)                      — Muster C (ambulant, geschlossen)
- P100005: A01(I/KAR) → A02(I/IMC) → A02(I/ITS) → A02(I/IMC) → A03(I/IMC) — Muster A + Mehrfach-Verlegung
- P100006: A04(O/NA) → A01(I/GYN^220) → A02(I/GYN^221)  — Muster B + Verlegung
- P100007: A04(O/NA) → A01(I/NEU)                       — Muster B

## An echten Daten zu verifizieren
- **Visit Number** sitzt NICHT in PV1-19 (leer), sondern als letzte PV1-Komponente
  (`V100001`…); A04 trägt sie nicht.
- **Bewegungszeit** nur in EVN-2; kein ZBE, kein EVN-6, kein PV1-44/45.
- **PV1-4 ≠ PV1-2:** PV1-4=`E` (Aufnahmeart), Klasse bleibt PV1-2=`O`.

## Nicht enthalten (M-2 Stufe 2 separat)
Kein Storno (A11/A12/A13), kein Out-of-Order, kein verspätetes Event, keine SIU.
