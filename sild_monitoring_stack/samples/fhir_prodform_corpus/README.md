# Synthetischer FHIR-Prod-Form-Korpus — 77 Bundles

**Status: SYNTHETISCH. PII-frei. An echten Daten zu verifizieren.**
Keine echten Patientendaten, kein Klinik-Datenabfluss. Zweck: Prod-Form-Korpus
des Register-Endzustands (FHIR-Ereignis-Register), Test-/Nachweisgrundlage für
den SILD-Filter auf der FHIR-R4-Kette. Dies ist Friedhelms Korpus, **nicht**
von Claude Code erfundene Fixtures.

## PII-Freiheit (belegt)
- Patienten-Referenzen synthetisch (`Patient/p-001`, `Patient/pat-12345`,
  `Patient/pat-77890` …) — keine Real-Person-Kennung.
- Namen ausschließlich Platzhalter/Allerweltsnamen (`Beispiel`, `Muster`,
  `Mustermann`, `Demo`, `Probst` + generische Nachnamen Becker/Fischer/Schulz …).
- `birthDate` generiert; **kein** `identifier`, `telecom`, `address`.
- Herkunft: synthetischer Generator. Manifest-Fingerabdruck (md5)
  `d4a9dcc951279ca8a5af8bb689f3acc7`.

## Inhalt
- `bundles/` — 77 FHIR-R4-Transaction-Bundles, eine `.json` pro Bundle
  (`<control_id>.json`).
- `_templates/` — 7 Vorlagen (clean/lossy-Muster: admission, icu-demo,
  medication-critical, rs, tc-period, tn-cc, ad-val).
- `korpus-manifest.jsonl` — 77 Zeilen, eine je Bundle: `control_id`,
  `expected_total_losses`, Severity-Verteilung (critical/warning/info).

## Verteilung (aus dem Manifest)
- **35 clean / 42 lossy → 77.**
- **Ist-Treue 45,5 % (= 35/77) == Soll** des Register-Endzustands.

## Kontext
Prod-Form-Korpus zum Register-Endzustand — s. LOGBUCH `aion-coordination`
2026-07-02 „REGISTER-ENDZUSTAND LIVE" (durables FHIR-Ereignis-Register,
77er-Korpus, Ist-Treue 45,5 % == Soll).

## Lizenz
Es gilt der Lizenzrahmen des Repos:
`AGPL-3.0-only OR LicenseRef-ISCaD-Commercial` (kein eigener Header).
