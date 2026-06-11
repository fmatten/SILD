# M-2 Interface-Fixture — sauber datierter A02 (SYNTHETISCH, Claude-Code-gebaut)

**Status: SYNTHETISCHE TEST-FIXTURE.** Von Claude Code für den
Verlegungspfad-Interface-Test konstruiert (Briefing M-2 Stufe 1, §7) —
**NICHT Teil von Friedhelms 54er-Korpus** (`samples/adt_m2_corpus/`) und
bewusst nicht dort hineingemischt.

## Inhalt
- `adt_a02_zbe_clean_P100005.hl7` — ein ADT^A02 für P100005 (KAR → IMC^502^1),
  identische Bewegung wie Korpus-`msg000031`, aber **MIT ZBE-2**
  (gemessene Bewegungszeit) und eigener Control-ID `MSG900001`
  (kollidiert nicht mit dem Korpus-Marker `MSG000031`).

## Zweck (zweifacher Verlegungspfad-Beweis, end-to-end)
1. Der **Korpus-A02** (`msg000031`, Zeit nur in EVN-2) wird von M-1 geholdet
   (`hold_timequality`, Anti-Falsch-Datierung) und erreicht M-2 **nicht**.
2. **Dieser A02** (ZBE-2 vorhanden) fließt M-1 → `usable` → M-2 und baut die
   Segmentgrenze KAR→IMC mit Provenienz `measured` (ZBE-2).

Test: `tests/test_mapper_m2.py::test_m2_verlegungspfad_zweifach_end_to_end`.

Segment-Terminator `\r` (wie der Korpus).
