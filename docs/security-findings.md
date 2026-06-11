# SILD Security Findings

Tracked security/privacy findings for the SILD reference implementation. Mirrors
the format used in the AION project (A.x / SF-x) so findings are comparable across
the dataflow.

| ID | Title | Status | Severity |
|----|-------|--------|----------|
| SILD-SF-1 | Durable v2 intake store holds raw PII — erasure + backup | **CLOSED — erasure BUILT; backup-erasure consciously delegated to the operator, documented** | high (privacy) |
| SILD-SF-2 | JSONL audit may carry INDIRECT identifiers (order numbers) | **OPEN — documented limitation** | medium (privacy) |
| SILD-SF-3 | M-1 Mapper-DB hold-queue holds raw PII — erasure + backup + schema evolution | **Erasure BUILT; backup delegated (see SF-1); schema migration DEFERRED — trigger documented** | high (privacy) |

---

## SILD-SF-1 — Durable intake store: erasure + backup of raw PII

**Context.** The persist-before-ack durable v2 intake
(`sild_monitoring_stack/sild_durable_store.py`, opt-in via `--durable-store`)
introduces a new, **live** SQLite store that holds the **full raw HL7 v2 payload,
including PID** — a materially larger and ever-present PHI surface than the
pre-existing JSONL audit log, which carries findings/metadata only.

**Finding.** The store currently has **no erasure and no backup story**:

- **Erasure.** A patient whose data is deleted in the source/EHR will still have
  their raw messages sitting in the SILD intake store. Without an erasure path,
  this becomes a **SILD-side SF-2** (deleted patient survives in the durable
  store) — the same class of finding as AION's A.6b/SF-2, but **one stage earlier
  in the dataflow** (at ingress, before decomposition/stay reconstruction).
- **Backup.** Store backups inherit the same raw PII and the same erasure
  obligation; an erasure that does not also reach backups is incomplete.

**Erasure — BUILT (Lesart A, no PID window).** `DurableStore.erase_patient()` +
the `sild_durable_store.py erase` CLI delete every stored message carrying a
patient key, scoped exactly to that key (a different patient's rows are
untouched — X-gone / Y-intact). The patient key = PID-3, MR-typed,
`Authority|ID` (site-configurable; `Authority|ID`, not the bare MRN, because a
bare MRN collides across hospitals). dry-run is the default; `--commit` is
explicit (destructive PID path, A.6b discipline). The erase audit record carries
key/counts/status/timestamp only — **never** the deleted payload.

**Erasure — fail-closed completeness.** A row whose patient key cannot be
extracted (technical/ACK/malformed message, missing MR identifier) cannot be
attributed and MIGHT belong to the patient → it forces status
`incomplete_uncertain` with a residual-risk count, **never** a silent "complete".
This is the AION A/B dead-letter case, one stage earlier: unattributable ≠ clean.

**Backup — consciously DELEGATED to the operator (this closes SF-1).** SILD
itself creates **no backups** — there is no backup code path anywhere in SILD;
every backup of the SILD stores is operator infrastructure (volume snapshots,
dump jobs, …). Stated as plainly as possible:

- The live erasure (`erase_patient` / the `erase` CLIs) covers **all live
  stores completely** — intake store, M-1 Mapper-DB and M-2 DB, including every
  quasi-identifier table (cf. SILD-SF-2 for what counts as one). It does **not**
  and **cannot** reach operator-made copies; **an erasure that does not also
  reach backups is incomplete**.
- **Operator obligation (GDPR Art. 17, right to erasure):** whoever backs up
  the SILD stores MUST do one of:
  - (a) operate a **backup-erasure procedure** that removes erased patients
    from backups too, or
  - (b) **consciously exclude** the SILD stores from backups, or
  - (c) use **crypto-shredding** (backup encryption + key destruction) as the
    erasure substitute.
- This obligation is anchored as a pre-production checklist in the stack README
  (`sild_monitoring_stack/README.md`, „Vor Produktivbetrieb —
  Betreiber-Checkliste“).

**Status: CLOSED — consciously delegated to the operator, documented.** No
SILD-side backup(-erasure) implementation is planned; the delegation is
architecturally deliberate and consistent with G6 (at-rest encryption is
likewise delegated to ops + enforced loudly).

> **Honest limit.** Whether this delegation legally SUFFICES to shift the
> erasure obligation to the operator is a legal question (ISCaD GmbH / counsel).
> This documentation makes the delegation as clear as possible but makes **no
> legal claim**.

**Multi-identifier edge cases (handled in the extractor).**
- Several MR-typed PID-3 repetitions (`~`, e.g. two authorities) → the message is
  keyed under ALL of them; erasure of any one deletes the row (no under-deletion).
- MR present but Assigning Authority (PID-3.4) empty → either a configured
  default authority, or the repetition is dropped (uncertain) — never the bare ID
  (collision risk).

**Related.**
- RFC §11.1 — at-rest encryption + access control (delegated to ops, enforced
  loudly at startup; see the durable-mode warning in
  `sild_monitoring_stack/sild_mllp_filter.py`).
- AION A.6b / SF-2 — the analogous downstream finding this one mirrors.
- **SILD-SF-2** (below) — indirect identifiers in the JSONL audit.

---

## SILD-SF-2 — JSONL audit may carry INDIRECT identifiers ("G6 honesty")

**Context.** G6 guarantees the durable store is the only artifact holding the raw
v2 payload, and that the JSONL audit carries **no DIRECT identifier** (patient
name / PID-5) — proven by `test_g6_no_cleartext_payload_in_audit`.

**Finding.** "G6 green" is **not** "no PII in the JSONL". A SILD finding's
`location` is, by design, the reference the rule flagged — e.g. `ORC/<placer
order number>` for RS-ORC-01, `OBR/<id>`. Order numbers are case/order-bound
identifiers and may be **indirectly** person-relatable when combined with other
data. The JSONL therefore is **not guaranteed PII-free**.

**Obligation.** The JSONL audit MUST be held under the **same access controls and
at-rest protection as the durable store** (RFC §11.1) — it is not safe to treat
it as a low-sensitivity log just because it omits names. Stripping/pseudonymising
indirect identifiers in finding locations is possible future work; for now it is a
**documented limitation**, surfaced in the README ("G6-Ehrlichkeit").

---

## SILD-SF-3 — M-1 Mapper-DB: erasure + backup of raw PII, and schema evolution

**Context.** M-1 (`sild_monitoring_stack/sild_mapper_m1.py`) reads SILD's intake
store **read-only** (`mode=ro` + `PRAGMA query_only`) and keeps its own Mapper-DB
on a mounted volume. Its `hold_queue` retains the **full raw HL7 v2 payload,
including PID**, for messages held back (time-quality / malformed) — and these are
exactly the *problematic, lingering* messages. `finding` / `disposition` /
`seen_marker` are PID-free (markers = MSH-3/4/10 source metadata only). So the
Mapper-DB is a second SF-1-class PHI surface, one stage downstream of ingress.

**Erasure — BUILT (Lesart A, no PID window), SILD logic reused.**
`MapperStore.erase_patient()` + the `sild_mapper_m1.py erase` CLI reuse SILD's
proven `classify_patient_keys` / `EraseResult` / `build_erase_audit_record` (not
reinvented). Patient key = PID-3 MR-typed `Authority|ID` (multi-MR → key set;
empty authority → default-or-uncertain, never the bare ID). The hold-queue is the
only PID source, so erasure deletes the matching `hold_queue` + `hold_patient_key`
rows, scoped exactly to the key (X-gone / Y-intact). dry-run default, `--commit`
explicit; content-free erase audit (key/counts/status/time, never payload).

**Erasure — fail-closed completeness, correct distinction (NO global count).**
Mirrors the SILD-SF-1 fix exactly: a hold with **no PID-3** (patientless /
technical) belongs to no patient and is **not** residual risk for erase X; only a
hold with a **present-but-unreadable PID-3** is `unresolved` and forces
`incomplete_uncertain`. Counting all unattributable rows globally would make every
erasure read incomplete forever — the alarm that always rings is no alarm.

**At-rest encryption — DELEGATED + LOUD.** Like SILD's G6: the Mapper-DB path is
configurable, raw v2 is not encrypted by M-1 (operator's encrypted volume), and
the surface is documented in the README ("G6-analog für die Mapper-DB").

**Backup — delegated to the operator (see SILD-SF-1, closed).** Same line as
SILD-SF-1: an erasure that does not also reach Mapper-DB backups/snapshots is
incomplete. A full patient erasure must reach **both** SILD's store and the
Mapper-DB and the operator's backup rotation — the operator obligation
(backup-erasure procedure OR conscious exclusion OR crypto-shred) is spelled out
in SILD-SF-1 and in the stack-README operator checklist.

**Schema evolution — DEFERRED with a named trigger (open, deliberate).**
Inventory finding (2026-06): SILD has **never** used `ALTER TABLE`; every schema
extension so far was an **additive new table**, which the self-migration pattern
(`CREATE TABLE IF NOT EXISTS` on every start) covers. So nothing is acute and no
migration rail is built now (greenfield — adding one today would be
over-engineering). What the pattern does **not** migrate:

- (a) **changes to existing tables** — a new/changed column or type would need
  `ALTER TABLE`; `CREATE TABLE IF NOT EXISTS` silently leaves the old shape in
  an existing DB (e.g. the `disposition.time_provenance` column added for
  time-provenance would be missing on an old DB);
- (b) **view-definition changes** — `CREATE VIEW IF NOT EXISTS`
  (`v_aion_stay` / `v_aion_segment` / `v_aion_change` in `sild_mapper_m2.py`)
  leaves the **old** definition standing in existing DBs.

**Trigger.** The first future change to a `v_aion_*` view definition OR the
first column change to an existing table requires a real migration rail:
`PRAGMA user_version` + versioned migration steps (for views, `DROP VIEW` +
`CREATE VIEW` inside the versioned step). Until then the documented assumption
is **additive changes only** (new tables). This is the SILD-side of the Alembic
lesson — recorded here, not solved here.

> **Hinweis (M-4-Kopplung):** Eine `v_aion_*`-View-Änderung ist zugleich eine
> Änderung der **M-4-Vertragsfläche** (M4-G1: die Views sind die eingefrorene
> Pull-Schnittstelle für AION, siehe `docs/aion-pull-contract.md`). Sie
> erfordert daher nicht nur die Migrations-Schiene (DROP+CREATE bzw.
> `user_version`), sondern auch **Koordination mit dem AION-Konsumenten**
> (B.1b im AION-Repo) — eine View-Änderung ist ein **Vertragsbruch gegenüber
> AION**, wenn sie unkoordiniert erfolgt. Daher doppelt teuer; bewusst
> durchführen.

**Status: stays OPEN/deferred with the named trigger — deliberate, not
forgotten.**

**Related.**
- **SILD-SF-1** (above) — the analogous finding on SILD's ingress store; same
  Lesart-A erasure semantics, reused here.
- RFC §11.1 — at-rest encryption + access control (delegated to ops).
- M-1/M-2 boundary — semantic plausibility, time-based ordering and time
  provenance (measured vs. estimated) live in M-2; M-1 only *starts* the time
  provenance (records which field the movement time came from).
