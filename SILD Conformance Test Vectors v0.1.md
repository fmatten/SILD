# SILD Conformance Test Vectors v0.1

**Companion document to RFC-DRAFT v0.2 (SILD), §9.2 Minimum Rule Set.**

This document provides normative test vectors for the four mandatory rules of the SILD FHIR adapter. Implementations claiming SILD conformance per RFC §9.2 MUST produce the expected findings for the positive cases and MUST NOT produce findings for the negative cases.

------

## 1. Format

Each test vector is a single YAML document with these fields:

| Field               | Required | Description                                                  |
| ------------------- | -------- | ------------------------------------------------------------ |
| `test_id`           | yes      | Globally unique identifier (`<rule>.<category>.<slug>`).     |
| `rule`              | yes      | The rule under test (e.g., `TN-CC-01`).                      |
| `category`          | yes      | One of `positive`, `negative`, `edge`.                       |
| `description`       | yes      | One-sentence statement of what is being tested.              |
| `input`             | yes      | A FHIR R4 Bundle (or fragment) the detector receives.        |
| `source_context`    | no       | Information about the upstream representation (e.g., HL7 v2 segment). Used for rules that require source awareness. |
| `expected_findings` | yes      | Array of findings. May be empty. Order is not significant.   |
| `notes`             | no       | Implementation notes, rationale for edge cases.              |

A finding object has the structure:

```yaml
rule_id: TN-CC-01
pattern: TN
detected_severity: WARNING
path: Observation.code
```

Implementations MAY add fields (timestamp, estimated_loss_bits, resource reference, etc.) — these are not checked by these vectors.

------

## 2. Scope and Conventions

**Detection mode.** These vectors assume **target-only** detection where possible. Rules that genuinely require source awareness (e.g., "the source HL7 v2 segment had a time range, the FHIR target collapsed it to a point") include a `source_context` field. Implementations that do not yet support source-aware detection MUST still pass the target-only vectors.

**FHIR version.** All vectors use FHIR R4 syntax. R5 equivalents follow the same logic with version-dispatched paths (see RFC §5.3).

**Bundles.** Inputs are wrapped in a transaction Bundle unless noted, so that `RS-BUNDLE-01` can be tested against the same envelope as the other rules.

**Conformance.** An implementation passes a vector if its output for the given input contains exactly the findings in `expected_findings` for the rule under test (other rules may add additional findings; only the rule under test is checked).

------

## 3. Test Vectors: TN-CC-01 (Type Narrowing — CodeableConcept)

**Rule definition (RFC §9.2 / Appendix B):**

```yaml
id: TN-CC-01
pattern: TN
path: "CodeableConcept"
predicate: "coding.empty() and text.exists()"
severity: WARNING
```

### 3.1 Positive Cases (MUST produce a finding)

```yaml
test_id: TN-CC-01.positive.observation-code-text-only
rule: TN-CC-01
category: positive
description: Observation.code has text but no coding entries.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-001
      resource:
        resourceType: Observation
        id: obs-001
        status: final
        code:
          text: Troponin
        subject:
          reference: Patient/p-001
        valueQuantity:
          value: 0.05
          unit: ng/mL
expected_findings:
  - rule_id: TN-CC-01
    pattern: TN
    detected_severity: WARNING
    path: Observation.code
test_id: TN-CC-01.positive.coding-empty-array
rule: TN-CC-01
category: positive
description: coding is an empty array (not missing), text is present.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-002
      resource:
        resourceType: Observation
        id: obs-002
        status: final
        code:
          coding: []
          text: Hemoglobin
        subject:
          reference: Patient/p-001
expected_findings:
  - rule_id: TN-CC-01
    pattern: TN
    detected_severity: WARNING
    path: Observation.code
notes: |
  An empty coding array is FHIRPath-equivalent to a missing coding for the
  purposes of `coding.empty()`. Implementations MUST treat both as equal.
test_id: TN-CC-01.positive.multiple-narrowed-fields
rule: TN-CC-01
category: positive
description: Multiple CodeableConcept fields narrowed in one resource.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:cond-001
      resource:
        resourceType: Condition
        id: cond-001
        code:
          text: Pneumonia
        bodySite:
          - text: Right lower lobe
        subject:
          reference: Patient/p-001
expected_findings:
  - rule_id: TN-CC-01
    pattern: TN
    detected_severity: WARNING
    path: Condition.code
  - rule_id: TN-CC-01
    pattern: TN
    detected_severity: WARNING
    path: Condition.bodySite[0]
notes: |
  Detectors MUST report one finding per affected CodeableConcept instance,
  not one summary finding per resource.
```

### 3.2 Negative Cases (MUST NOT produce a finding)

```yaml
test_id: TN-CC-01.negative.coding-present
rule: TN-CC-01
category: negative
description: Coding is present alongside text. No narrowing.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-101
      resource:
        resourceType: Observation
        id: obs-101
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
              display: Troponin T
          text: Troponin T
        subject:
          reference: Patient/p-001
expected_findings: []
test_id: TN-CC-01.negative.coding-only-no-text
rule: TN-CC-01
category: negative
description: Only coding, no text. Not a TN case (no fallback occurred).
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-102
      resource:
        resourceType: Observation
        id: obs-102
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 718-7
        subject:
          reference: Patient/p-001
expected_findings: []
```

### 3.3 Edge Cases

```yaml
test_id: TN-CC-01.edge.text-empty-string
rule: TN-CC-01
category: edge
description: text is present but is the empty string. By FHIRPath, empty() is true.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-201
      resource:
        resourceType: Observation
        id: obs-201
        status: final
        code:
          text: ""
        subject:
          reference: Patient/p-001
expected_findings: []
notes: |
  FHIRPath `exists()` on a primitive returns true if the element is present
  AND has a value. The empty string has no value in FHIR; `text.exists()` is
  false. No finding is produced.

  Detectors that treat empty strings as values would produce a false TN here.
test_id: TN-CC-01.edge.coding-without-system-or-code
rule: TN-CC-01
category: edge
description: coding[0] is present but has only display, no system or code.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-202
      resource:
        resourceType: Observation
        id: obs-202
        status: final
        code:
          coding:
            - display: Troponin
          text: Troponin
        subject:
          reference: Patient/p-001
expected_findings: []
notes: |
  A coding entry without system/code is FHIR-valid but semantically degenerate.
  TN-CC-01 as specified does not catch this; a stricter rule
  TN-CC-02 (`coding.where(system.exists() and code.exists()).empty()`) is
  RECOMMENDED but not part of the minimum set.
```

------

## 4. Test Vectors: TC-PERIOD-01 (Temporal Collapse — Period)

**Rule definition (RFC Appendix B):**

```yaml
id: TC-PERIOD-01
pattern: TC
path: "MedicationRequest.dosage"
predicate: "timing.repeat.exists() and timing.event.empty()"
severity: WARNING
```

This is an intra-resource rule: a `Timing.repeat` structure is present but the `event` list is empty, suggesting a repetition was lost on conversion.

### 4.1 Positive Cases

```yaml
test_id: TC-PERIOD-01.positive.repeat-without-events
rule: TC-PERIOD-01
category: positive
description: timing.repeat is present, but timing.event is empty.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:mr-001
      resource:
        resourceType: MedicationRequest
        id: mr-001
        status: active
        intent: order
        subject:
          reference: Patient/p-001
        dosageInstruction:
          - timing:
              repeat:
                frequency: 3
                period: 1
                periodUnit: d
            doseAndRate:
              - doseQuantity:
                  value: 500
                  unit: mg
expected_findings:
  - rule_id: TC-PERIOD-01
    pattern: TC
    detected_severity: WARNING
    path: MedicationRequest.dosageInstruction[0].timing
```

### 4.2 Negative Cases

```yaml
test_id: TC-PERIOD-01.negative.repeat-with-events
rule: TC-PERIOD-01
category: negative
description: timing.repeat is present and timing.event lists concrete instants.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:mr-101
      resource:
        resourceType: MedicationRequest
        id: mr-101
        status: active
        intent: order
        subject:
          reference: Patient/p-001
        dosageInstruction:
          - timing:
              event:
                - "2026-05-26T08:00:00Z"
                - "2026-05-26T16:00:00Z"
                - "2026-05-27T00:00:00Z"
              repeat:
                frequency: 3
                period: 1
                periodUnit: d
expected_findings: []
test_id: TC-PERIOD-01.negative.no-repeat-structure
rule: TC-PERIOD-01
category: negative
description: A single-shot administration with no repeat at all.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:mr-102
      resource:
        resourceType: MedicationRequest
        id: mr-102
        status: completed
        intent: order
        subject:
          reference: Patient/p-001
        dosageInstruction:
          - timing:
              event:
                - "2026-05-26T08:00:00Z"
expected_findings: []
```

### 4.3 Edge Cases

```yaml
test_id: TC-PERIOD-01.edge.empty-event-array
rule: TC-PERIOD-01
category: edge
description: timing.event is present but is an empty array, with repeat present.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:mr-201
      resource:
        resourceType: MedicationRequest
        id: mr-201
        status: active
        intent: order
        subject:
          reference: Patient/p-001
        dosageInstruction:
          - timing:
              event: []
              repeat:
                count: 5
expected_findings:
  - rule_id: TC-PERIOD-01
    pattern: TC
    detected_severity: WARNING
    path: MedicationRequest.dosageInstruction[0].timing
notes: |
  An empty event array is equivalent to a missing event list for `empty()`.
  This case MUST behave identically to a missing event field.
```

------

## 5. Test Vectors: AD-VAL-01 (Attribute Dropping — Observation Value)

**Rule definition (RFC §9.2 / Appendix B):**

```yaml
id: AD-VAL-01
pattern: AD
path: "Observation"
predicate: "value.empty() and dataAbsentReason.empty()"
severity: CRITICAL
```

A final `Observation` MUST either carry a value or explicitly indicate why none is present. Neither is a CRITICAL semantic loss.

### 5.1 Positive Cases

```yaml
test_id: AD-VAL-01.positive.no-value-no-reason
rule: AD-VAL-01
category: positive
description: Final Observation with neither value nor dataAbsentReason.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-301
      resource:
        resourceType: Observation
        id: obs-301
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
expected_findings:
  - rule_id: AD-VAL-01
    pattern: AD
    detected_severity: CRITICAL
    path: Observation
```

### 5.2 Negative Cases

```yaml
test_id: AD-VAL-01.negative.value-present
rule: AD-VAL-01
category: negative
description: Observation has a valueQuantity.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-401
      resource:
        resourceType: Observation
        id: obs-401
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
        valueQuantity:
          value: 0.05
          unit: ng/mL
expected_findings: []
test_id: AD-VAL-01.negative.data-absent-reason-present
rule: AD-VAL-01
category: negative
description: No value, but dataAbsentReason explains why.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-402
      resource:
        resourceType: Observation
        id: obs-402
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
        dataAbsentReason:
          coding:
            - system: http://terminology.hl7.org/CodeSystem/data-absent-reason
              code: error
expected_findings: []
test_id: AD-VAL-01.negative.value-string
rule: AD-VAL-01
category: negative
description: Observation has a valueString (also a value[x] variant).
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-403
      resource:
        resourceType: Observation
        id: obs-403
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 33747-0
        subject:
          reference: Patient/p-001
        valueString: "no growth"
expected_findings: []
notes: |
  FHIRPath `value.empty()` is false for any of the value[x] choice variants:
  valueQuantity, valueString, valueBoolean, valueCodeableConcept, etc.
  Implementations MUST handle the choice type correctly.
```

### 5.3 Edge Cases

```yaml
test_id: AD-VAL-01.edge.status-cancelled
rule: AD-VAL-01
category: edge
description: Observation status is `cancelled`, no value, no reason.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-501
      resource:
        resourceType: Observation
        id: obs-501
        status: cancelled
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
expected_findings:
  - rule_id: AD-VAL-01
    pattern: AD
    detected_severity: CRITICAL
    path: Observation
notes: |
  AD-VAL-01 as defined does not condition on status. A cancelled observation
  without dataAbsentReason still triggers, because the reason for absence is
  not made explicit at the value level. Profiles MAY override this to INFO
  for non-final statuses, but the base rule fires.
test_id: AD-VAL-01.edge.component-without-value
rule: AD-VAL-01
category: edge
description: Top-level value is absent (component-based observation).
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-502
      resource:
        resourceType: Observation
        id: obs-502
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 85354-9
        subject:
          reference: Patient/p-001
        component:
          - code:
              coding:
                - system: http://loinc.org
                  code: 8480-6
            valueQuantity:
              value: 120
              unit: mmHg
          - code:
              coding:
                - system: http://loinc.org
                  code: 8462-4
            valueQuantity:
              value: 80
              unit: mmHg
expected_findings: []
notes: |
  Component-based observations (e.g., blood pressure) legitimately carry
  values only at the component level. AD-VAL-01 MUST recognize that
  `value.empty()` at the top is acceptable when components exist and carry
  values. A stricter rule AD-VAL-02 may check component-level absence;
  it is not part of the minimum set.

  Implementations of AD-VAL-01 MUST either treat component presence as
  satisfying the rule, or document the false-positive behavior. The
  conformance kit MAY add a profile override for `status='final' and
  component.exists()`.
```

------

## 6. Test Vectors: RS-BUNDLE-01 (Reference Severing — Bundle)

**Rule definition (RFC Appendix B):**

```yaml
id: RS-BUNDLE-01
pattern: RS
path: "Bundle"
predicate: "any Reference.reference does not match any Bundle.entry.fullUrl"
severity: CRITICAL
```

Within a transaction Bundle, every literal `Reference.reference` MUST match the `fullUrl` of some entry in the same Bundle, OR be resolvable via the detector's configured resolver (out of scope for these vectors).

### 6.1 Positive Cases

```yaml
test_id: RS-BUNDLE-01.positive.dangling-patient-reference
rule: RS-BUNDLE-01
category: positive
description: Observation references Patient/p-999, but Patient/p-999 is not in the bundle.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-601
      resource:
        resourceType: Observation
        id: obs-601
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-999
        valueQuantity:
          value: 0.05
          unit: ng/mL
expected_findings:
  - rule_id: RS-BUNDLE-01
    pattern: RS
    detected_severity: CRITICAL
    path: Bundle.entry[0].resource.subject.reference
test_id: RS-BUNDLE-01.positive.contained-anchor-missing
rule: RS-BUNDLE-01
category: positive
description: Reference to `#enc-1` but no contained resource with id `enc-1`.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-602
      resource:
        resourceType: Observation
        id: obs-602
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
        encounter:
          reference: "#enc-1"
        contained:
          - resourceType: Practitioner
            id: prac-1
    - fullUrl: Patient/p-001
      resource:
        resourceType: Patient
        id: p-001
expected_findings:
  - rule_id: RS-BUNDLE-01
    pattern: RS
    detected_severity: CRITICAL
    path: Bundle.entry[0].resource.encounter.reference
notes: |
  A `#anchor` reference resolves only against the same resource's
  `contained[]` list. Here `#enc-1` is not the id of any contained entry.

  Patient/p-001 is included as a separate bundle entry (entry[1]) so the
  subject reference resolves in-bundle, focusing the test purely on the
  contained-anchor failure. Otherwise a strict per-reference RS-BUNDLE-01
  implementation would necessarily emit two findings (subject + encounter)
  for two unresolved references, contradicting the single expected finding.
```

### 6.2 Negative Cases

```yaml
test_id: RS-BUNDLE-01.negative.reference-resolves-in-bundle
rule: RS-BUNDLE-01
category: negative
description: Patient/p-001 is present in the bundle.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: Patient/p-001
      resource:
        resourceType: Patient
        id: p-001
        gender: female
    - fullUrl: urn:uuid:obs-701
      resource:
        resourceType: Observation
        id: obs-701
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-001
        valueQuantity:
          value: 0.05
          unit: ng/mL
expected_findings: []
test_id: RS-BUNDLE-01.negative.identifier-only-no-literal
rule: RS-BUNDLE-01
category: negative
description: Reference uses identifier instead of literal. No severance per this rule.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-702
      resource:
        resourceType: Observation
        id: obs-702
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          identifier:
            system: "http://example.org/mrn"
            value: "12345"
        valueQuantity:
          value: 0.05
          unit: ng/mL
expected_findings: []
notes: |
  An identifier-only reference is NOT detected by RS-BUNDLE-01 — the rule
  requires a literal `Reference.reference`. A separate rule TN-REF-01
  catches the loss-of-resolved-target case and produces a TN finding.
```

### 6.3 Edge Cases

```yaml
test_id: RS-BUNDLE-01.edge.fullurl-uuid-vs-typed-reference
rule: RS-BUNDLE-01
category: edge
description: Bundle uses urn:uuid: fullUrls; reference uses typed form.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:p-abc
      resource:
        resourceType: Patient
        id: p-abc
    - fullUrl: urn:uuid:obs-801
      resource:
        resourceType: Observation
        id: obs-801
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: Patient/p-abc
expected_findings:
  - rule_id: RS-BUNDLE-01
    pattern: RS
    detected_severity: CRITICAL
    path: Bundle.entry[1].resource.subject.reference
notes: |
  This is the most common false-positive trap. FHIR R4 transaction bundles
  commonly use `urn:uuid:...` fullUrls together with typed references.
  Per FHIR §3.2.5.7.1, a literal `Patient/p-abc` reference does NOT match a
  `urn:uuid:p-abc` fullUrl directly — only `urn:uuid:p-abc` would match.

  Implementations MUST flag this as RS. If a converter actually intended
  `Patient/p-abc` to resolve to the urn:uuid: entry, it should have used
  a `urn:uuid:` reference. The detection is correct; the source data is
  wrong.

  Profiles MAY add a separate "identifier resolution" extension that
  resolves UUIDs to typed references, but that is outside RS-BUNDLE-01.
test_id: RS-BUNDLE-01.edge.external-reference-allowed
rule: RS-BUNDLE-01
category: edge
description: Reference is an absolute URL pointing outside the bundle.
input:
  resourceType: Bundle
  type: transaction
  entry:
    - fullUrl: urn:uuid:obs-802
      resource:
        resourceType: Observation
        id: obs-802
        status: final
        code:
          coding:
            - system: http://loinc.org
              code: 6598-7
        subject:
          reference: "https://other.example.org/fhir/Patient/p-001"
        valueQuantity:
          value: 0.05
          unit: ng/mL
source_context:
  resolver_configured: true
  external_resolution_policy: trust
expected_findings: []
notes: |
  An absolute external reference is out of bundle scope. RS-BUNDLE-01 only
  fires when the reference SHOULD resolve in-bundle. Implementations MUST
  distinguish absolute external references (no finding) from relative
  references that should resolve in-bundle but do not (finding).

  If `external_resolution_policy: strict` is configured, a separate rule
  RS-EXTERNAL-01 (not in the minimum set) MAY fire.
```

------

## 7. Counting and Coverage

For an implementation to demonstrate conformance with the minimum rule set, the following matrix MUST be passed:

| Rule         | Positive | Negative | Edge  | Total  |
| ------------ | -------- | -------- | ----- | ------ |
| TN-CC-01     | 3        | 2        | 2     | 7      |
| TC-PERIOD-01 | 1        | 2        | 1     | 4      |
| AD-VAL-01    | 1        | 3        | 2     | 6      |
| RS-BUNDLE-01 | 2        | 2        | 2     | 6      |
| **Total**    | **7**    | **9**    | **7** | **23** |

A pass requires:

- 100% of positive cases produce **exactly** the listed expected findings (no extra findings from the rule under test, no missing findings).
- 100% of negative cases produce **no** findings from the rule under test.
- 100% of edge cases match the documented expected behavior.

Findings from rules other than the rule under test are NOT checked by this vector set and MAY be present.

------

## 8. Maintenance

This document is versioned independently of the SILD RFC.

| Version | Date    | Changes                                      |
| ------- | ------- | -------------------------------------------- |
| v0.1    | 2026-05 | Initial release with the four minimum rules. |

Future versions will extend coverage to:

- HL7 v2 segment-based equivalents
- DICOM SR equivalents
- DE/MII profile-specific rules (AD-MII-DX-01, AD-MII-SEC-01, …)
- Cross-bundle reference resolution (when the session concept is specified)
- Profile override interactions (override changing effective severity)

Contributions and corrections are tracked at: `https://github.com/fmatten/SILD/issues` (label: `test-vectors`).

------

**End of test vector specification v0.1.**