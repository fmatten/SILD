# SILD Security Findings

Tracked security/privacy findings for the SILD reference implementation. Mirrors
the format used in the AION project (A.x / SF-x) so findings are comparable across
the dataflow.

| ID | Title | Status | Severity |
|----|-------|--------|----------|
| SILD-SF-1 | Durable v2 intake store holds raw PII — erasure + backup | **Erasure BUILT; backup DOCUMENTED** | high (privacy) |
| SILD-SF-2 | JSONL audit may carry INDIRECT identifiers (order numbers) | **OPEN — documented limitation** | medium (privacy) |

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

**Backup — DOCUMENTED obligation (not yet automated).** The store MUST be
included in the backup story, and **an erasure that does not also reach backups
is incomplete**. Operators MUST either (a) include the store in backups with a
matching backup-erasure procedure, or (b) exclude it from backups and rely on the
durable store + recovery sweep alone. Automating backup-erasure is out of scope
here and remains the open part of SILD-SF-1.

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
