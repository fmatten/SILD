# SILD Conformance Test Vectors v2 v0.1

**Companion document to RFC-DRAFT v0.2 (SILD), §9.2 Minimum Rule Set — HL7 v2 carrier.**

This document provides normative test vectors for the four mandatory rules of the SILD HL7 v2 adapter. Implementations claiming SILD conformance per RFC §9.2 (v2 row of the rule table) MUST produce the expected findings for the positive cases and MUST NOT produce findings for the negative cases.

This file is the v2-carrier sibling to `SILD Conformance Test Vectors v0.1.md` (FHIR). The FHIR vectors stay authoritative for the FHIR adapter; this document stays authoritative for the HL7 v2 adapter. Both reference the same RFC §9.2 minimum rule set.

------

## 1. Format

Each test vector is a single YAML document with these fields:

| Field               | Required | Description                                                  |
| ------------------- | -------- | ------------------------------------------------------------ |
| `test_id`           | yes      | Globally unique identifier (`<rule>.<category>.<slug>`).     |
| `rule`              | yes      | The rule under test (e.g., `TN-CE-01`).                      |
| `category`          | yes      | One of `positive`, `negative`, `edge`.                       |
| `description`       | yes      | One-sentence statement of what is being tested.              |
| `input`             | yes      | A raw HL7 v2 message as a pipe-delimited block scalar.       |
| `source_context`    | no       | Information about the upstream representation. Used by rules that require source awareness. |
| `expected_findings` | yes      | Array of findings. May be empty. Order is not significant.   |
| `notes`             | no       | Implementation notes, rationale for edge cases.              |

A finding object has the structure:

```yaml
rule_id: TN-CE-01
pattern: TN
detected_severity: WARNING
path: OBR-4
```

The `path` is given in HL7 v2 segment-and-field notation (`<segment>-<field>`, optionally `<segment>-<field>.<component>`). Implementations MAY emit richer locations (e.g., `OBR/<placer-order-number>`); the conformance runner compares at **segment-level** (`OBR` from `OBR-4` matches `OBR` from `OBR/<id>`). This intentionally mirrors the resource-level granularity used by the FHIR vector runner.

------

## 2. Scope and Conventions

**Detection mode.** v2 vectors operate **target-only** (i.e., on the message as it arrives at the SILD sentinel). Rules that genuinely require source awareness include a `source_context` field. Implementations that do not yet support source-aware detection MUST still pass the target-only vectors.

**HL7 v2 version.** Vectors use v2.5.1 syntax. The rule predicates are version-agnostic across v2.3.1–v2.9 unless noted; segment numbering is fixed.

**Message envelope.** Each input message contains a minimal MSH header plus the segment(s) needed to exercise the rule. Other patterns may incidentally fire — the conformance runner filters to the rule under test, like the FHIR runner.

**Encoding characters.** Standard `|^~\&` are used throughout. The `\r` end-of-segment is encoded as `\n` in the YAML block scalar for human readability; the runner normalises both.

**Conformance.** An implementation passes a vector if its output for the given input contains exactly the findings in `expected_findings` for the rule under test (other rules may add additional findings; only the rule under test is checked).

------

## 3. Test Vectors: TN-CE-01 (Type Narrowing — CE/CWE structure loss)

**Rule definition (RFC §9.2):**

```yaml
id: TN-CE-01
pattern: TN
path: "OBR-4 | OBX-3"
predicate: "CE/CWE component 2 (text) non-empty AND component 1 (identifier) empty AND component 3 (name of coding system) empty"
severity: WARNING
```

This rule fires when a coded element in OBR-4 (Universal Service Identifier) or OBX-3 (Observation Identifier) carries a human-readable display but lacks both code and coding system — the v2 mirror of FHIR `TN-CC-01` (`coding.empty() and text.exists()`).

### 3.1 Positive Cases

```yaml
test_id: TN-CE-01.positive.obr-4-display-only
rule: TN-CE-01
category: positive
description: OBR-4 carries text in component 2 but no identifier and no coding system.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-001|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-001|FILL-001|^Hemoglobin Panel^|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings:
  - rule_id: TN-CE-01
    pattern: TN
    detected_severity: WARNING
    path: OBR-4

test_id: TN-CE-01.positive.obx-3-display-only
rule: TN-CE-01
category: positive
description: OBX-3 carries text in component 2 but no identifier and no coding system.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-002|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-002|FILL-002|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|^Troponin T^||0.05|ng/mL||N|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings:
  - rule_id: TN-CE-01
    pattern: TN
    detected_severity: WARNING
    path: OBX-3
```

### 3.2 Negative Cases

```yaml
test_id: TN-CE-01.negative.fully-structured
rule: TN-CE-01
category: negative
description: OBR-4 and OBX-3 are fully structured (code, text, system all present). No narrowing.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-101|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-101|FILL-101|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []

test_id: TN-CE-01.negative.code-and-system-no-text
rule: TN-CE-01
category: negative
description: OBR-4 carries code and system but no human-readable text. Not a TN case.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-102|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-102|FILL-102|58410-2^^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
notes: |
  Mirror of FHIR `TN-CC-01.negative.coding-only-no-text`. `text.exists()` is
  false when component 2 is empty, so the predicate is not satisfied.
```

### 3.3 Edge Cases

```yaml
test_id: TN-CE-01.edge.empty-ce
rule: TN-CE-01
category: edge
description: OBR-4 has no components at all (just `||`). No text, no code, no system.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-201|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-201|FILL-201||||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
notes: |
  Mirror of FHIR `TN-CC-01.edge.text-empty-string`. With no text component
  there is nothing to "narrow from"; the predicate is not satisfied.

test_id: TN-CE-01.edge.code-without-system
rule: TN-CE-01
category: edge
description: OBR-4 has code and text but no coding system. Degenerate code, not minimum-set TN.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TN-202|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-202|FILL-202|58410-2^CBC panel^|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
notes: |
  Mirror of FHIR `TN-CC-01.edge.coding-without-system-or-code`. A coding
  entry with code but no system is semantically degenerate but not a
  minimum-set TN case; a stricter rule TN-CE-02 may flag this.
```

------

## 4. Test Vectors: TC-OBR-01 (Temporal Collapse — OBR observation interval)

**Rule definition (RFC §9.2):**

```yaml
id: TC-OBR-01
pattern: TC
path: "OBR-7 / OBR-8"
predicate: "OBR-7 (Observation Date/Time) and OBR-8 (Observation End Date/Time) both non-empty AND OBR-7 != OBR-8"
severity: WARNING
```

This rule fires when an OBR explicitly carries a time interval (distinct start and end), which collapses to a single `effectiveDateTime` when mapped to FHIR `Observation`.

### 4.1 Positive Cases

```yaml
test_id: TC-OBR-01.positive.interval-distinct
rule: TC-OBR-01
category: positive
description: OBR-7 and OBR-8 are both set and differ — explicit source interval.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TC-001|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-001|FILL-001|58410-2^CBC panel^LN|||20260516071500|20260516071600
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings:
  - rule_id: TC-OBR-01
    pattern: TC
    detected_severity: WARNING
    path: OBR-7
```

### 4.2 Negative Cases

```yaml
test_id: TC-OBR-01.negative.equal-start-end
rule: TC-OBR-01
category: negative
description: OBR-7 equals OBR-8 — a point in time, not an interval.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TC-101|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-101|FILL-101|58410-2^CBC panel^LN|||20260516071500|20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071500|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []

test_id: TC-OBR-01.negative.only-start
rule: TC-OBR-01
category: negative
description: OBR-7 is set, OBR-8 is empty — single observation timestamp, no interval claim.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TC-102|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-102|FILL-102|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071500|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
```

### 4.3 Edge Cases

```yaml
test_id: TC-OBR-01.edge.both-empty
rule: TC-OBR-01
category: edge
description: Both OBR-7 and OBR-8 empty — no temporal claim at all.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-TC-201|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-201|FILL-201|58410-2^CBC panel^LN
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071500|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
notes: |
  An OBR with no time fields conveys no interval, so no TC. A separate rule
  could flag the missing observation time as AD/TC, but that is not part of
  the minimum set.
```

------

## 5. Test Vectors: AD-OBX-01 (Attribute Dropping — OBX device/observer provenance)

**Rule definition (RFC §9.2):**

```yaml
id: AD-OBX-01
pattern: AD
path: "OBX-2 / OBX-15 / OBX-16"
predicate: "OBX-2 (Value Type) ∈ {NM, NA, SN, NR} AND OBX-15 (Producer's ID) empty AND OBX-16 (Responsible Observer) empty"
severity: CRITICAL
```

This rule fires when a numeric/device-measurable OBX carries no device or observer attribution — the producing instrument and/or responsible observer is dropped, which a downstream FHIR `Observation` would carry in `method` and/or `device`.

**Severity rationale.** The v2 predicate (provenance loss on a numeric value) is structurally weaker than its FHIR pattern-mate `AD-VAL-01` (the value itself missing). Per RFC §9.2 the v2 minimum bears the AD pattern severity (CRITICAL) anyway — implementations that find this strict MUST handle it via the override layer (§4.4), not by softening the intrinsic severity.

### 5.1 Positive Cases

```yaml
test_id: AD-OBX-01.positive.nm-without-device-and-observer
rule: AD-OBX-01
category: positive
description: NM-typed OBX with both OBX-15 (device) and OBX-16 (observer) empty.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-001|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-001|FILL-001|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600
expected_findings:
  - rule_id: AD-OBX-01
    pattern: AD
    detected_severity: CRITICAL
    path: OBX-15
```

### 5.2 Negative Cases

```yaml
test_id: AD-OBX-01.negative.device-present
rule: AD-OBX-01
category: negative
description: OBX-15 carries device identification — provenance preserved.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-101|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-101|FILL-101|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01
expected_findings: []

test_id: AD-OBX-01.negative.observer-present
rule: AD-OBX-01
category: negative
description: OBX-16 carries responsible observer — provenance preserved even without device.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-102|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-102|FILL-102|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600||TECH-01^Schmidt^Berta
expected_findings: []

test_id: AD-OBX-01.negative.text-type-not-device-measurable
rule: AD-OBX-01
category: negative
description: OBX-2=TX (free text) is not device-measurable — rule does not apply.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-103|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-103|FILL-103|58410-2^CBC panel^LN|||20260516071500
  OBX|1|TX|11329-0^History note^LN||Patient reports nausea since morning.||N|||F|||20260516071600
expected_findings: []
notes: |
  Manual text entries (TX, FT, ST) do not carry device-measurability
  semantics. Missing OBX-15/16 is expected, not a loss.
```

### 5.3 Edge Cases

```yaml
test_id: AD-OBX-01.edge.unknown-value-type
rule: AD-OBX-01
category: edge
description: OBX-2 holds an unknown/unspecified value type; OBX-15/16 empty.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-201|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-201|FILL-201|58410-2^CBC panel^LN|||20260516071500
  OBX|1|XX|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600
expected_findings: []
notes: |
  Only the explicitly numeric set {NM, NA, SN, NR} qualifies as
  device-measurable for AD-OBX-01. Unknown types are conservatively
  excluded; a stricter rule may catch them as "type-ambiguous".

test_id: AD-OBX-01.edge.nm-with-only-trailing-pipe
rule: AD-OBX-01
category: edge
description: OBX-15 and OBX-16 fields exist but are explicitly empty.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-AD-202|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1|ORD-202|FILL-202|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|||
expected_findings:
  - rule_id: AD-OBX-01
    pattern: AD
    detected_severity: CRITICAL
    path: OBX-15
notes: |
  Explicit empty trailing fields are FHIRPath-equivalent to missing fields
  for `empty()`. Implementations MUST treat both as equal.
```

------

## 6. Test Vectors: RS-ORC-01 (Reference Severing — ORC placer reference)

**Rule definition (RFC §9.2):**

```yaml
id: RS-ORC-01
pattern: RS
path: "ORC-2"
predicate: "ORC-2 (Placer Order Number) non-empty (literal cross-system reference; resolution at target not guaranteed)"
severity: CRITICAL
```

This rule fires whenever an order segment carries a Placer Order Number — a literal reference to a `ServiceRequest` (or equivalent) in another system. Without a target-side resolution map, the reference is potentially severed by the conversion.

**Severity rationale.** Like `AD-OBX-01`, the v2 predicate (reference presence) is weaker than its FHIR pattern-mate `RS-BUNDLE-01` (verified bundle-internal unresolvability). The v2 carrier has no envelope analog to a transaction `Bundle`, so verification must happen at the target system. The intrinsic severity (CRITICAL) follows the RS pattern per RFC §9.2; implementations that operate inside a closed system where ORC-2 is always resolvable MUST use the override layer (§4.4) to downgrade.

### 6.1 Positive Cases

```yaml
test_id: RS-ORC-01.positive.placer-order-number
rule: RS-ORC-01
category: positive
description: ORC-2 carries a placer order number — cross-system reference present.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-RS-001|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  ORC|RE|ORD-2026-001|FILL-001|GROUP-100||CM
  OBR|1|ORD-2026-001|FILL-001|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings:
  - rule_id: RS-ORC-01
    pattern: RS
    detected_severity: CRITICAL
    path: ORC-2
```

### 6.2 Negative Cases

```yaml
test_id: RS-ORC-01.negative.orc-without-placer
rule: RS-ORC-01
category: negative
description: ORC is present but ORC-2 is empty — no literal placer reference to sever.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-RS-101|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  ORC|RE||FILL-101|GROUP-101||CM
  OBR|1||FILL-101|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []

test_id: RS-ORC-01.negative.no-orc-segment
rule: RS-ORC-01
category: negative
description: Message has no ORC segment at all — no reference, no rule trigger.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-RS-102|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  OBR|1||FILL-102|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
```

### 6.3 Edge Cases

```yaml
test_id: RS-ORC-01.edge.multiple-orc-segments
rule: RS-ORC-01
category: edge
description: Multiple ORC segments, each with its own ORC-2 — one finding per occurrence.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-RS-201|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  ORC|RE|ORD-2026-201A|FILL-201A
  OBR|1|ORD-2026-201A|FILL-201A|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
  ORC|RE|ORD-2026-201B|FILL-201B
  OBR|2|ORD-2026-201B|FILL-201B|789-8^Erythrocytes^LN|||20260516071500
  OBX|2|NM|789-8^Erythrocytes^LN||4.8|10*6/uL||N|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings:
  - rule_id: RS-ORC-01
    pattern: RS
    detected_severity: CRITICAL
    path: ORC-2
  - rule_id: RS-ORC-01
    pattern: RS
    detected_severity: CRITICAL
    path: ORC-2
notes: |
  Detectors MUST report one finding per ORC-2 occurrence, not one summary
  finding per message.

test_id: RS-ORC-01.edge.orc-2-whitespace-only
rule: RS-ORC-01
category: edge
description: ORC-2 contains only whitespace — implementation-defined whether this counts.
input: |
  MSH|^~\&|LIS|HOSPITAL|GATEWAY|HOSPITAL|20260516071500||ORU^R01^ORU_R01|MSG-RS-202|P|2.5.1
  PID|1||P-001^^^HOSP^MR||Mustermann^Max
  ORC|RE|   |FILL-202
  OBR|1|   |FILL-202|58410-2^CBC panel^LN|||20260516071500
  OBX|1|NM|718-7^Hemoglobin^LN||10.2|g/dL||L|||F|||20260516071600|LAB-01|MA-IMMUNO^Roche Cobas^HOSP
expected_findings: []
notes: |
  This document interprets whitespace-only as empty for ORC-2 — the field
  does not address any concrete order. A stricter rule may flag this as
  AD-ORC (Attribute Dropping on a structural field) but it is not RS.
```

------

## 7. Counting and Coverage

For an implementation to demonstrate conformance with the v2 minimum rule set, the following matrix MUST be passed:

| Rule       | Positive | Negative | Edge  | Total  |
| ---------- | -------- | -------- | ----- | ------ |
| TN-CE-01   | 2        | 2        | 2     | 6      |
| TC-OBR-01  | 1        | 2        | 1     | 4      |
| AD-OBX-01  | 1        | 3        | 2     | 6      |
| RS-ORC-01  | 1        | 2        | 2     | 5      |
| **Total**  | **5**    | **9**    | **7** | **21** |

A pass requires:

- 100% of positive cases produce **exactly** the listed expected findings (no extra findings from the rule under test, no missing findings).
- 100% of negative cases produce **no** findings from the rule under test.
- 100% of edge cases match the documented expected behavior.

Findings from rules other than the rule under test are NOT checked by this vector set and MAY be present.

------

## 8. Maintenance

This document is versioned independently of the SILD RFC and of the FHIR vector document.

| Version | Date    | Changes                                       |
| ------- | ------- | --------------------------------------------- |
| v0.1    | 2026-05 | Initial release with the four v2 minimum rules (B2 package). |

Future versions will extend coverage to:

- v2 message-type-specific rules (ADT, ORM, RDE/RDS, SIU, etc.)
- v2.6+ HD/EI composite handling
- Cross-segment reference resolution (OBR-29 Parent → OBR-3 in same message)
- DE-Basisprofile v2 mappings (KVid in PID-3, ICD-10-GM in DG1-3)

Contributions and corrections are tracked at: `https://github.com/fmatten/SILD/issues` (label: `test-vectors-v2`).

------

**End of HL7 v2 test vector specification v0.1.**
