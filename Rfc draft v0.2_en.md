------

## title: "SILD — Detecting Semantic Loss at Clinical Data Boundaries" subtitle: "An Implementer's Guide to Signal-Loss Inspection at Data-boundaries" author: "Friedhelm Matten, ISCaD GmbH" date: "May 2026" version: "Draft v0.2" status: "Informational" abstract: > This document specifies SILD (Signal-Loss Inspection at Data-boundaries), a carrier-neutral detector for semantic information loss in clinical cross-system transmissions. SILD identifies four canonical loss patterns at transmission boundaries — Type Narrowing, Temporal Collapse, Attribute Dropping, and Reference Severing — independent of carrier format (HL7 v2, FHIR R4/R5, DICOM SR). The formal foundations and proofs are in FM-4 [FM-4]; this document is written for implementers and adopters.

# Status of This Memo

This is an individual contribution to the clinical interoperability community. It is distributed for public review and comment. Distribution is unlimited.

**Note to Readers:** This is a DRAFT. Implementations based on this document should expect non-backwards-compatible changes before any final version.

# Copyright Notice

Copyright © 2026 Friedhelm Matten / ISCaD GmbH. All rights reserved.

------

# 1. Introduction

## 1.1 The Problem, in One Story

A cardiology lab sends a troponin result to the hospital's EHR. In the source system, the result is coded with a LOINC code, has a measurement window ("collected between 14:32 and 14:35"), carries a security tag ("specially protected — cardiac genomic study"), and references the ordering encounter.

After transmission through an HL7 v2 → FHIR converter, the EHR receives a `Observation` resource that:

- contains the value, but the LOINC code is gone — only free text "Troponin" remains;
- has `effectiveDateTime` "14:33" — the measurement window collapsed to a point;
- has no `meta.security` tag — the protection class disappeared;
- has `encounter.reference = "Encounter/xyz"` — but no `Encounter/xyz` resource is in the bundle.

A structural validator like HAPI will accept this message. All cardinalities are satisfied. All types are correct. The schema is happy.

The downstream clinical decision support system, however, cannot:

- filter by LOINC (the code is gone),
- reason about timing relative to other events (the interval collapsed),
- apply the special access policy (the security tag is gone),
- resolve the encounter context (the reference is broken).

The information was lost, but no validator noticed. This is the gap SILD fills.

## 1.2 What SILD Is

SILD is a detector that sits at the transmission boundary between two clinical systems and answers four questions about every message that passes through:

1. **What was lost?** Of the four canonical patterns, which (if any) occurred?
2. **How severe is the loss?** Informational, warning, or critical?
3. **Where did it happen?** Which path or field is affected?
4. **What should the system do?** Pass-through, log, or block?

The four patterns are exhaustive in a formal sense (see FM-4, Theorem 2.5) under stated assumptions about how clinical mappings factorize. An implementer does not need to read the proof to use SILD; the patterns are also empirically exhaustive across known mappings (HL7 v2 → FHIR, FHIR R4 → R5, FHIR → OMOP, FHIR → i2b2).

## 1.3 What SILD Is Not

SILD is **not** any of the following:

- A new wire protocol or data format. It inspects existing carriers.
- A replacement for HAPI or other structural validators. SILD runs after structural validation and detects a different class of defect.
- An auto-repair tool. Detection only. Remediation is a separate concern.
- Tied to FHIR. The detector class works for HL7 v2, FHIR R4/R5, and DICOM SR through an adapter architecture (see §5).

## 1.4 Reading This Document

Implementers can read §3, §4, §5, §6, §9, and Appendix B and skip the rest. The mathematical foundations are referenced, not reproduced; see Appendix A for pointers into FM-4.

------

# 2. Conventions and Terminology

## 2.1 Requirement Levels

The key words "MUST", "MUST NOT", "REQUIRED", "SHALL", "SHALL NOT", "SHOULD", "SHOULD NOT", "RECOMMENDED", "NOT RECOMMENDED", "MAY", and "OPTIONAL" are to be interpreted as described in BCP 14 [RFC2119] [RFC8174] when, and only when, they appear in all capitals.

## 2.2 Glossary

| Term                  | Definition                                                   |
| --------------------- | ------------------------------------------------------------ |
| Transmission boundary | The point where data leaves one system and enters another.   |
| Carrier format        | The serialization (HL7 v2, FHIR R4, FHIR R5, DICOM SR).      |
| Finding               | One detected loss instance, with pattern, path, and severity. |
| Rule                  | A predicate that, when true on incoming data, produces a finding. |
| Core layer            | Format-independent logic (the four patterns, severity model). |
| Adapter               | Format-specific rules and path language.                     |
| Detected severity     | The severity assigned by the rule that produced the finding. |
| Effective severity    | The severity after local overrides are applied.              |

------

# 3. The Four Loss Patterns

## 3.1 Why Four

Every loss in a clinical transmission, when the transmission can be decomposed into independent component mappings (time, type, context, references, modifiers), reduces to exactly one of four patterns. This is FM-4 Theorem 2.5 (Completeness), proven under two stated assumptions (FM-4 §A.5):

- **A1 (Component factorization):** Clinical transmissions factorize into independent per-component mappings.
- **A2 (Disjoint component spaces):** The component spaces are algebraically distinct.

A separate result (FM-4 Theorem 2.7, Minimality) shows the four patterns cannot be reduced further: no pattern is redundant.

**Practical reading:** If a proposed detector does not fit TN/TC/AD/RS, it is either (a) addressing a violation of A1 — which is rare in practice — or (b) belongs to a different class of check (structural, business rules, terminology binding). It is not a candidate for SILD.

## 3.2 Type Narrowing (TN)

**What it is.** A precise code is replaced by a vaguer representation.

**Concrete examples:**

- A LOINC code becomes free text in `CodeableConcept.text` only.
- A SNOMED CT leaf concept becomes a parent concept ("Bacterial pneumonia" becomes "Pneumonia").
- A resolved `Reference` becomes an `identifier`-only reference with no resolver in scope.

**Why it hurts.** Downstream systems lose the ability to filter, aggregate, or apply code-specific rules. A clinical decision support engine cannot fire on free text; a registry cannot count by code.

**Default severity.** WARNING. May be CRITICAL for safety-critical codes (allergens, medication codes); may be INFO when the code system is deliberately omitted by policy (e.g., free-text patient comments).

## 3.3 Temporal Collapse (TC)

**What it is.** A time interval or repetition pattern collapses to a single point.

**Concrete examples:**

- A medication administration `Period` (`[start, end]`) becomes a single `occurrenceDateTime`.
- A `Timing.repeat` ("three times daily for seven days") becomes one `occurrenceDateTime`.
- An `Observation.effectivePeriod` becomes `effectiveDateTime`.

**Why it hurts.** Causal reasoning becomes impossible. The Allen interval relations (`before`, `meets`, `overlaps`, `during`, etc. — see [Allen]) all collapse to "at-or-before" when both operands are points. "Did the lab draw happen during the infusion?" becomes unanswerable.

**Default severity.** WARNING. CRITICAL if the downstream system performs causal inference (e.g., adverse event attribution, AION pipelines).

## 3.4 Attribute Dropping (AD)

**What it is.** A meaning-changing modifier disappears.

**Concrete examples:**

- `meta.security` tag is removed; protection class is lost.
- `modifierExtension` is dropped on transmission.
- `Observation.value[x]` is missing with no `dataAbsentReason` ("we don't know why this is empty").
- Diagnosis verification status (provisional / confirmed / refuted) is lost.

**Why it hurts.** Modifiers carry meaning-changing information. A diagnosis without verification status reads as "confirmed" to most consumers, even if the source meant "suspected". A missing security tag may move data into a less-protected zone.

**Default severity.** Depends on the modifier. CRITICAL for security tags and `dataAbsentReason`; WARNING for most clinical modifiers; INFO for optional display-only annotations (`text`, `note`).

## 3.5 Reference Severing (RS)

**What it is.** A reference is syntactically present but cannot be resolved in scope.

**Concrete examples:**

- `Reference.reference = "Patient/123"` but no `Bundle.entry` has `fullUrl` matching `Patient/123`.
- A `#contained-id` reference with no matching `contained[]` entry.
- An `identifier`-only reference with no resolver.

**Why it hurts.** The referenced context — patient, encounter, related condition — is invisible to the downstream system. Clinical safety can be directly affected: a medication request without a resolvable patient reference is dangerous.

**Default severity.** CRITICAL for safety-relevant references (patient, medication, allergy); WARNING for context references (encounter, practitioner); INFO for purely informational links (`derivedFrom` to an older draft).

------

# 4. Severity and Operational Response

## 4.1 Three Levels

SILD uses three severity levels, totally ordered:

```
CRITICAL  >  WARNING  >  INFO
```

## 4.2 What Each Level Triggers

| Level    | Transmission | Audit           | Metric Counter |
| -------- | ------------ | --------------- | -------------- |
| CRITICAL | Blocked      | Yes             | Yes            |
| WARNING  | Pass-through | Yes             | Yes            |
| INFO     | Pass-through | No (by default) | Yes            |

**Blocking response by carrier:**

- FHIR over HTTP: `HTTP 422 Unprocessable Entity` with an `OperationOutcome` describing the findings.
- HL7 v2 over MLLP: `MSA-1 = AE` (Application Error) with appropriate `ERR` segment.
- DICOM SR: implementation-defined, typically a negative storage commitment or association rejection.

## 4.3 Local Overrides

Tenants and paths may need to override default severities. SILD supports overrides as a layered map:

```yaml
overrides:
  - path: "Observation.note"
    pattern: "AD"
    override_severity: "INFO"
    rationale: "Free-text notes are advisory only in our profile."
```

Overrides MUST NOT change the **detected** severity — they only change the **effective** severity (consequence). This distinction is normative and is addressed in §4.4.

## 4.4 Detection vs. Consequence (Normative)

The audit trail records every finding at its **detected** severity. The operational consequence (block / log / count) is determined by the **effective** severity after overrides.

This means:

- If a rule produces a WARNING that is overridden to INFO, the finding **MUST** still be written to the audit trail (because its detected severity is WARNING), but the transmission **MUST** pass through (because its effective severity is INFO).
- An override cannot silence a finding from the audit. It can only change whether it blocks.

This rule prevents the "override-to-suppress" attack where a tenant configures away findings they do not want to see.

------

# 5. Architecture

## 5.1 Core and Adapters

```
┌────────────────────────────────────────────────┐
│                  sild.core                     │
│  Pattern enum, Severity, Finding, Result       │
│  ────  carrier-independent, byte-identical ──  │
└────────────────────────────────────────────────┘
         ▲                              ▲
   ┌─────┴──────┐                ┌──────┴──────┐
   │ sild.v2    │                │ sild.fhir   │
   │  adapter   │                │   adapter   │
   │  (HL7 v2)  │                │ (R4 and R5) │
   └────────────┘                └─────────────┘
```

| Module                  | Purpose                             | Carrier    |
| ----------------------- | ----------------------------------- | ---------- |
| `sild.core`             | Patterns, severity, finding records | —          |
| `sild.v2.rules`         | Segment/field predicates            | HL7 v2     |
| `sild.fhir.rules`       | FHIRPath predicates                 | FHIR R4/R5 |
| `sild.fhir.profiles_de` | German base profiles, MII           | FHIR (DE)  |

The core layer is byte-identical across adapters. This is not a coincidence or a coding convention — it follows from FM-4 Theorem 2.5: the patterns and their severity logic are carrier-independent, so their representation as code is too.

## 5.2 Why Adapters, Not Code Forks

A single SILD implementation may need to inspect HL7 v2 messages from a lab analyzer and FHIR bundles from a downstream EHR in the same hospital. With the core-plus-adapter shape, both detectors share the same pattern vocabulary; a TN finding from v2 and a TN finding from FHIR are directly comparable in the audit trail.

## 5.3 Version Compatibility (R4 and R5)

FHIR R4 and R5 are treated as two points in the same carrier's version tree, not separate carriers. Most paths are identical (`Reference`, `Identifier`, `CodeableConcept`, `Period`, `Bundle.entry`). Changed paths are dispatched through a version profile:

```python
def path_for(rule_id, fhir_version):
    if fhir_version == "R5" and rule_id in R5_PATH_OVERRIDES:
        return R5_PATH_OVERRIDES[rule_id]
    return DEFAULT_PATHS[rule_id]
```

The set of paths that genuinely differ between R4 and R5 is small relative to the full FHIR path vocabulary, so a full re-fork of rules is unnecessary.

**Corollary.** A version-migration detector (R4 → R5) is a special case of a transmission detector. The four patterns suffice; no new "Version Downgrade" category is needed (FM-4 Corollary 3.1).

------

# 6. Pipeline Integration

## 6.1 Where SILD Sits

SILD sits at the transmission boundary as a sentinel: between the sending system and the receiving system, **before** the receiver writes anything to its store.

This positioning matters. Downstream of the boundary, the loss has already happened and cannot be observed — the original is gone. Only at the boundary are both the sent and the received representations visible.

## 6.2 Recommended Pipeline Order

```
Incoming → [Structural Validator] → [SILD Detector] → Receiver
              (HAPI, schema)         (this spec)
              syntactic defects      semantic loss
```

**Rationale.** Structural defects (missing required fields, wrong types, profile violations) can mask semantic loss; running HAPI first ensures SILD inspects only well-formed messages.

## 6.3 Deployment Endpoints

| Carrier  | Deployment         | Endpoint                |
| -------- | ------------------ | ----------------------- |
| FHIR     | HTTP reverse proxy | `/fhir/*`               |
| HL7 v2   | MLLP server        | TCP port 2575 (default) |
| DICOM SR | DICOM SCP          | Configurable AE Title   |

------

# 7. Audit Trail as First-Class Object

## 7.1 FHIR AuditEvent Mapping

Each SILD finding can be persisted as a `FHIR AuditEvent` resource:

| Finding field       | AuditEvent field                         |
| ------------------- | ---------------------------------------- |
| Timestamp           | `AuditEvent.recorded`                    |
| Pattern + Rule ID   | `AuditEvent.type.code` (SILD CodeSystem) |
| Referenced resource | `AuditEvent.entity.what`                 |
| Detector identity   | `AuditEvent.agent.who`                   |
| Detected severity   | `AuditEvent.outcome.code`                |
| Path / FHIRPath     | `AuditEvent.entity.detail`               |

## 7.2 Why the Audit Is Itself Analyzable

A persisted SILD finding is structurally a clinical-information record: it has a time, a type (the pattern), a context (the inspected resource), a relation (the detector), and a severity. This means the audit trail itself can be analyzed by the same tools used for clinical data analysis — trend detection, tenant comparison, anomaly detection on transmission quality become straightforward.

In practical terms: a hospital can run "show me tenants whose TN rate doubled month-over-month" as a routine query, not as a custom report.

------

# 8. Quantitative Loss Estimation

## 8.1 What Is and Is Not Claimed

SILD provides a rough, conservative estimate of information loss in bits per finding. **These numbers are not exact** — they are order-of-magnitude estimates intended for comparison and trend analysis, not for absolute quantification. Empirical calibration against real mappings is open work (FM-4 §4.3, §8).

## 8.2 Per-Pattern Estimators

The estimators in FM-4 §4 are:

- **TN:** `log₂(|terminology|)` bits when a code becomes free text; `log₂(k)` bits when a code is narrowed to an ancestor whose subtree has size `k`.
- **TC:** `log₂(Δt / δ)` bits when an interval of duration `Δt` collapses to a point at resolution `δ`; `log₂(n)` bits when a repeat-`n` collapses.
- **AD:** `log₂(|modifier domain|)` bits when a modifier is dropped.
- **RS:** `log₂(N) + 12` bits when the resolution scope is known to be `N` resources; conservatively `≈ 24` bits otherwise.

Order-of-magnitude examples: LOINC → text ≈ 16.5 bits; SNOMED CT → text ≈ 18.5 bits; missing diagnosis verification status ≈ 2 bits.

## 8.3 Aggregation and Its Caveats

The total loss budget for a transmission is the sum of per-finding losses:

```
B(F) = Σ L(fᵢ)
```

This is additive and conservative — it **overcounts** correlated losses on the same component. The budget is intended for **relative comparison** (transmission A vs. B, tenant A vs. B, this month vs. last month), not as an absolute information-theoretic value.

A subadditive treatment via component-partition entropy is open work (FM-4 §8.1).

------

# 9. Conformance

## 9.1 What "SILD-Conformant" Means

An implementation claims SILD conformance if it satisfies §9.2 (Minimum Rule Set) and §9.3 (Architecture Requirements). Optional capabilities (§9.4) extend conformance to specific tiers.

## 9.2 Minimum Rule Set (Normative)

A SILD-conformant FHIR adapter **MUST** include at least these four rules, one per pattern:

| Rule ID        | Pattern | Predicate (FHIRPath)                                         | Severity |
| -------------- | ------- | ------------------------------------------------------------ | -------- |
| `TN-CC-01`     | TN      | `CodeableConcept.coding.empty() and CodeableConcept.text.exists()` | WARNING  |
| `TC-PERIOD-01` | TC      | `Observation.effectivePeriod.exists() and Observation.effectiveDateTime.empty()` is false but inverse | WARNING  |
| `AD-VAL-01`    | AD      | `Observation.value.empty() and Observation.dataAbsentReason.empty()` | CRITICAL |
| `RS-BUNDLE-01` | RS      | `Bundle.entry.resource.reference` is non-empty and unresolvable in-bundle | CRITICAL |

A SILD-conformant HL7 v2 adapter **MUST** include at least four analogous rules, with predicates expressed in segment/field notation, one per pattern.

Test vectors validating these rules will accompany the final version of this specification (see Appendix B for example inputs and expected outputs).

## 9.3 Architecture Requirements

A conformant implementation:

1. **MUST** detect all four patterns (TN, TC, AD, RS).
2. **MUST** assign one of INFO, WARNING, CRITICAL to each finding.
3. **MUST** record findings at their **detected** severity, regardless of overrides (§4.4).
4. **MUST** record findings as audit events for WARNING and CRITICAL detected severities.
5. **MUST** keep the core layer free of carrier-specific logic.
6. **MUST** support at least one carrier adapter.

## 9.4 Optional Capabilities

A conformant implementation **MAY** additionally:

- Support quantitative loss estimation (§8).
- Provide a HAPI-pre-stage integration helper.
- Export Prometheus / OpenMetrics counters for findings.
- Implement override layering beyond a single tenant level.
- Support cross-bundle reference resolution via a session concept.

------

# 10. Performance

## 10.1 Reference Numbers

The reference implementation (single-core CPython 3.12, no JIT) was measured on synthetic MII-style FHIR bundles, 50 runs per scenario. Numbers below are microseconds **per resource**, not per bundle.

| Bundle size | Rule set         | p50  | p95  | p99  |
| ----------- | ---------------- | ---- | ---- | ---- |
| N = 50      | default          | 82   | 84   | 87   |
| N = 50      | default + DE/MII | 92   | 138  | 147  |
| N = 200     | default          | 115  | 117  | 122  |
| N = 200     | default + DE/MII | 122  | 123  | 127  |
| N = 500     | default          | 167  | 175  | 177  |
| N = 500     | default + DE/MII | 175  | 191  | 195  |

## 10.2 Methodology and Caveats

These are **synthetic micro-benchmarks**: in-process, no network, no audit I/O, no persistent store. Real deployments will see additional latency from audit writes, network I/O, and TLS termination, on the order of 0.5–5 ms depending on the audit backend.

The target — p99 < 2 ms per resource — leaves roughly tenfold headroom on the largest measured bundle with the DE/MII profile pack. A DACH university hospital workload (≈ 5,000 resources/sec peak) can be served by a single CPython worker with audit writes batched asynchronously.

## 10.3 What Drives the Variance

The DE/MII profile pack roughly doubles the number of rules evaluated per resource, but rule evaluation is largely FHIRPath traversal cost. Latency scales sublinearly with rule count up to ≈ 200 rules; above that, a compiled-predicate cache becomes necessary.

------

# 11. Security and Privacy Considerations

## 11.1 Data Privacy

SILD operates on metadata, structure, and references — not patient narrative content. Audit entries may, however, contain references to patient resources. Implementations:

- **MUST** encrypt audit storage at rest.
- **MUST** apply access controls equivalent to those on the source clinical data.
- **SHOULD** retain audit data according to local regulation (in Germany, typically minimum 10 years for treatment-relevant material; consult local counsel).

## 11.2 The Blocking Mechanism Is Operationally Significant

A CRITICAL finding blocks the transmission. This can impact clinical workflows. Implementations:

- **MUST** log every blocking decision with rule ID and path.
- **SHOULD** provide an emergency-override capability requiring two-factor authorization, and **MUST** log all such overrides at detected severity.
- **SHOULD** alert designated personnel on sustained block rates exceeding a configured threshold.

## 11.3 Override Configuration Is Sensitive

The override map (§4.3) can change consequences but not detection. The map itself **MUST** be:

- Version-controlled.
- Signed or otherwise integrity-protected.
- Auditable on change.

A malicious or careless override that downgrades CRITICAL findings to INFO cannot make them invisible (§4.4), but it can cause the system to stop blocking real losses. Treat the override map as a security-relevant configuration artifact.

## 11.4 Supply Chain

Adapters are format-specific and may evolve separately from the core. The core layer **MUST** declare an API version; adapters **MUST** declare which core API versions they support. Adapter binaries **SHOULD** be signed.

------

# 12. URI Namespace Declaration

This document does not request IANA registration. The following URIs are declared as private namespaces under the `iscad.de` domain, owned by ISCaD GmbH:

## 12.1 SILD Pattern CodeSystem

**URI:** `https://sild.iscad.de/codesystem/pattern`

| Code | Display            | Definition                                             |
| ---- | ------------------ | ------------------------------------------------------ |
| `TN` | Type Narrowing     | A precise code is replaced by a vaguer representation. |
| `TC` | Temporal Collapse  | A time interval or repetition collapses to a point.    |
| `AD` | Attribute Dropping | A meaning-changing modifier is dropped.                |
| `RS` | Reference Severing | A reference becomes unresolvable in scope.             |

## 12.2 SILD Severity CodeSystem

**URI:** `https://sild.iscad.de/codesystem/severity`

| Code       | Display       | Definition                                |
| ---------- | ------------- | ----------------------------------------- |
| `INFO`     | Informational | Minor loss; no audit required by default. |
| `WARNING`  | Warning       | Moderate loss; audit required.            |
| `CRITICAL` | Critical      | Severe loss; transmission blocked.        |

Future versions of this document may move these CodeSystems into the HL7 Terminology Authority or an equivalent registry.

------

# 13. Relationship to the Wider Model Family

SILD is one component in a four-paper family. All four papers share a common information model — every clinical event is characterized by its time, type, context, references, and modifiers.

| Paper            | Role                                                         | Status                |
| ---------------- | ------------------------------------------------------------ | --------------------- |
| **FM-1**         | Foundations: formal model of clinical information.           | Published [FM-1]      |
| **FM-2 / CAIRN** | Reference implementation of FM-1 in Python.                  | In preparation [FM-2] |
| **FM-3 / AION**  | Algebraic interval ontology for causal inference.            | In preparation [FM-3] |
| **FM-4 / SILD**  | Boundary detector for semantic loss (this spec's foundation). | This document [FM-4]  |

**Relation of SILD to the others (per FM-4 §7):**

- **CAIRN models** what clinical information means and evaluates it.
- **AION generalizes** the model to causal inference over intervals.
- **SILD inspects** whether information stays intact at transmission boundaries.

In a slogan: SILD is to CAIRN/AION as a linter is to a compiler.

A SILD finding is directly interpretable in the AION model: a TC finding implies that downstream Allen-relation operators on the affected time operand work with reduced resolution, which forecloses certain causal inferences. A TN finding blocks subsumption queries in the terminology hierarchy. This correspondence is not coincidental; it follows from the shared information-tuple decomposition.

------

# 14. References

## 14.1 Normative References

**[RFC2119]** Bradner, S. *Key words for use in RFCs to Indicate Requirement Levels.* BCP 14, RFC 2119, March 1997.

**[RFC8174]** Leiba, B. *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words.* BCP 14, RFC 8174, May 2017.

**[FM-4]** Matten, F. *Signal-Loss Inspection at Data-boundaries: A formal detector class for clinical cross-system transmissions.* ISCaD GmbH, May 2026. — Provides the proofs (Theorems 2.5, 2.7) and the operator algebra referenced throughout this document.

**[FHIR-R4]** HL7 International. *FHIR Release 4.* https://hl7.org/fhir/R4/

**[FHIR-R5]** HL7 International. *FHIR Release 5.* https://hl7.org/fhir/R5/

## 14.2 Informative References

**[FM-1]** Matten, F. *Grundlagen zur wissenschaftlichen Auswertung von klinischen Informationen.* ISCaD GmbH, March 2026 (Zenodo v1.0). DOI: `https://doi.org/10.5281/zenodo.19205557`.

**[FM-2]** Matten, F. *CAIRN: Clinical Interoperability Reference Architecture.* ISCaD GmbH, 2026 (in preparation). Source: `https://codeberg.org/fm2-project/cairn`.

**[FM-3]** Matten, F. *AION: Algebraic Interval Ontology for Clinical Networks.* ISCaD GmbH, 2026 (in preparation).

**[Allen]** Allen, J. F. *Maintaining knowledge about temporal intervals.* Communications of the ACM, 26(11):832–843, November 1983.

------

# Appendix A. Mathematical Foundations

This document deliberately keeps the math at a minimum. The formal core is in FM-4. The minimum an implementer should know:

**Theorem 2.5 (Completeness).** Under assumptions A1 (component factorization) and A2 (disjoint component spaces), every lossy clinical transmission is in TN ∪ TC ∪ AD ∪ RS.

**Theorem 2.7 (Minimality).** Each of the four patterns has a witness transmission that lies in none of the other three. The taxonomy cannot be reduced.

**Practical implications:**

1. A new SILD detector rule that does not fit one of the four patterns either (a) detects a structural defect (use HAPI instead), (b) detects a business rule violation (use a separate rules engine), or (c) targets a case where A1 fails. Case (c) is rare in clinical interop practice and should be flagged for discussion before adding a new pattern.
2. The core layer's pattern enum has exactly four values for a reason. It is **not** intended to be extended.
3. The carrier-independence of the core layer is a theorem, not a design convention. Adapters can be developed independently with confidence that the core will not need to change to accommodate them.

For the proofs themselves, see FM-4 §2 and Appendix A.

------

# Appendix B. Example Rule Set

## B.1 Default FHIR Rules (Recommended Baseline)

```yaml
rules:
  # Type Narrowing
  - id: TN-CC-01
    pattern: TN
    path: "CodeableConcept"
    predicate: "coding.empty() and text.exists()"
    severity: WARNING

  - id: TN-REF-01
    pattern: TN
    path: "Reference"
    predicate: "reference.empty() and identifier.exists()"
    severity: WARNING

  # Temporal Collapse
  - id: TC-PERIOD-01
    pattern: TC
    path: "MedicationRequest.dosage"
    predicate: "timing.repeat.exists() and timing.event.empty()"
    severity: WARNING

  - id: TC-OBS-01
    pattern: TC
    path: "Observation"
    predicate: "effectivePeriod.empty() and effectiveDateTime.exists() and source-had-period"
    severity: WARNING

  # Attribute Dropping
  - id: AD-SEC-01
    pattern: AD
    path: "Resource.meta"
    predicate: "source.meta.security.exists() and security.empty()"
    severity: CRITICAL

  - id: AD-VAL-01
    pattern: AD
    path: "Observation"
    predicate: "value.empty() and dataAbsentReason.empty()"
    severity: CRITICAL

  - id: AD-NOTE-01
    pattern: AD
    path: "Resource.note"
    predicate: "source-had-note and note.empty()"
    severity: INFO       # advisory only

  # Reference Severing
  - id: RS-BUNDLE-01
    pattern: RS
    path: "Bundle"
    predicate: "any Reference.reference does not match any Bundle.entry.fullUrl"
    severity: CRITICAL

  - id: RS-CONTAINED-01
    pattern: RS
    path: "DomainResource"
    predicate: "any '#anchor' reference has no matching contained[].id"
    severity: WARNING
```

## B.2 German MII Profile Extensions (Illustrative)

```yaml
rules:
  - id: AD-MII-DX-01
    pattern: AD
    path: "Condition"
    predicate: "verificationStatus.coding.empty()"
    severity: WARNING
    rationale: "MII requires diagnosis certainty (V/A/Z/G)."

  - id: AD-MII-SEC-01
    pattern: AD
    path: "Patient.meta"
    predicate: "security.where(system='https://gematik.de/fhir/CodeSystem/patient-privacy').empty()"
    severity: CRITICAL
    rationale: "Gematik privacy classification is mandatory for MII data."
```

## B.3 Example Findings (For Test Vectors)

A WARNING-level TN finding looks like:

```json
{
  "rule_id": "TN-CC-01",
  "pattern": "TN",
  "path": "Observation.code",
  "detected_severity": "WARNING",
  "effective_severity": "WARNING",
  "estimated_loss_bits": 16.5,
  "timestamp": "2026-05-26T14:33:00Z",
  "resource_ref": "Observation/abc-123"
}
```

------

# Appendix C. Open Issues (For Reviewer Attention)

The following items are explicitly open and invite reviewer input before any non-draft version of this specification:

1. **Empirical calibration of bit estimators.** §8 numbers are order-of-magnitude only. A community-driven calibration effort against real v2 → FHIR mappings (ideally on MII integration centers) would strengthen the metric.
2. **Subadditive aggregation.** The additive loss budget in §8.3 overcounts correlated losses. An entropy-of-partitions approach is anticipated.
3. **Cross-bundle reference resolution.** RS-BUNDLE-01 currently checks only within one bundle. Multi-bundle transactions need a session concept (FM-4 §8).
4. **Internalizing StructureDefinition validation.** Folding a subset of HAPI's profile-constraint logic into SILD would simplify deployment. Whether this is worth the maintenance burden is open.
5. **Conformance test vectors.** A normative set of input/output pairs demonstrating compliance with §9.2 will accompany the final version.
6. **Notation alignment.** The companion paper FM-4 uses both `T` (time range) and `T` (terminology) in its notation; this needs a single, unambiguous convention in print.

------

**Author's Address**

Friedhelm Matten ISCaD GmbH Germany

Email: `friedhelm.matten@iscad.de` Source: `https://github.com/fm2-project/sild` Docs: `https://sild.iscad.de`

------

# Acknowledgments

The author thanks the ISCaD GmbH team and the clinical interoperability community for feedback on earlier drafts. The transition from v0.1 to v0.2 incorporated reviewer comments on theorem numbering, audit semantics under overrides, IANA scope, performance methodology, and conformance verifiability.

------

*End of RFC Draft v0.2*