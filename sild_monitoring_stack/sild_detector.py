# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD detector for MLLP-streamed HL7 v2 messages and FHIR R4 bundles.

FM-4 conformance:
  K-1 — Type Narrowing: terminologische Strukturerkennung statt Keywords (Def. 2.1)
  K-3 — Severity-Override-Komposition: Sigma_eff = o_tenant o o_default o Sigma_intrinsic (§2.4)
  M-1 — AD: OBX-2 Value-Type-basierte Prüfung (NM/NA/SN/NR erwarten Device-Info) (Def. 2.3)
  M-2 — TC FHIR: Alle Prozeduren + Kategorie-basierte Observation-TC-Erkennung (Def. 2.2)
  M-3 — RS: Bundle-Referenz-Auflösbarkeit statt Präsenz-Check (Def. 2.4)
  M-5 — Audit: fhir_audit_events_from_report() als FM-1-konformes Tupel (§5.3)
  M-6 — Verlust-Budget: compute_loss_budget_bits_estimate() / Entropie-Schätzer (§4.1)

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
Part of: SILD MLLP Sidecar Demo
"""

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

# Roadmap-Slot: optionaler Delegations-Pfad an cairn.sild.SILDDetector.
# Der Import wird vorgehalten, ist aber bewusst NICHT verkabelt. Solange kein
# realer Delegations-Aufruf in analyse_hl7_message / analyse_fhir_bundle
# existiert, ist der Inline-Detektor die einzige aktive Engine. using_real_cairn()
# bleibt deshalb stets False — bloße Paket-Anwesenheit ist kein Signal.
try:
    from cairn.sild import SILDDetector as RealSILD  # noqa: F401  # type: ignore
    _CAIRN_PACKAGE_PRESENT = True
except ImportError:
    _CAIRN_PACKAGE_PRESENT = False


# ===========================================================================
# FM-4 Korollar A.4: Genau vier Loss-Patterns, unveränderlich
# ===========================================================================

class LossPattern(Enum):
    TYPE_NARROWING     = "Type Narrowing"
    TEMPORAL_COLLAPSE  = "Temporal Collapse"
    ATTRIBUTE_DROPPING = "Attribute Dropping"
    REFERENCE_SEVERED  = "Reference Severing"


# ===========================================================================
# K-1: Terminologische Strukturerkennung (FM-4 Def. 2.1)
# ===========================================================================

HL7_STRUCTURED_SYSTEMS: frozenset = frozenset({
    "LN", "SCT", "I10", "I9CM", "CPT4", "NDC", "NCI", "RXNORM", "CVX", "ATC",
})

FHIR_SPECIFIC_SYSTEMS: frozenset = frozenset({
    "http://loinc.org",
    "http://snomed.info/sct",
    "http://www.nlm.nih.gov/research/umls/rxnorm",
    "http://hl7.org/fhir/sid/icd-10",
    "http://hl7.org/fhir/sid/icd-10-cm",
    "http://fhir.de/CodeSystem/dimdi/icd-10-gm",
    "http://fhir.de/CodeSystem/bfarm/icd-10-gm",
    "http://www.whocc.no/atc",
})

FHIR_GENERIC_SYSTEMS: frozenset = frozenset({
    "http://terminology.hl7.org/CodeSystem/observation-category",
    "http://hl7.org/fhir/observation-category",
    "http://terminology.hl7.org/CodeSystem/condition-category",
})


def _hl7_ce_structured(ce_field: str) -> tuple:
    """FM-4 Def. 2.1: Strukturierter HL7v2 CE/CWE-Code (code^display^system)."""
    parts  = ce_field.split("^")
    code   = parts[0].strip() if len(parts) > 0 else ""
    system = parts[2].strip().upper() if len(parts) > 2 else ""
    return bool(code) and bool(system), code, system


def _fhir_cc_narrowing(cc: dict) -> tuple:
    """
    FM-4 Def. 2.1: CodeableConcept auf Type Narrowing analysieren.

    Returns (is_narrowed, reason, severity).

    Two distinct cases, with different severities:

      1. RFC §9.2 TN-CC-01 (text-only, coding empty/missing AND text present)
         -> severity 'warning'. This is the normative case.

      2. Heuristik (coding mit konkretem code, aber System nicht in LOINC/
         SNOMED/ICD/ATC) -> severity 'info'. Nicht von TN-CC-01 erfasst,
         als ergaenzende Erkennung gefuehrt.

    FHIRPath-Semantik: `coding.empty()` ist wahr fuer fehlende UND fuer
    leere Arrays; `text.exists()` ist falsch fuer fehlende Felder UND fuer
    den leeren String. Beide Faelle werden hier konsistent gehandhabt.
    """
    codings = cc.get("coding", []) or []
    text    = cc.get("text", "") or ""
    # Case 1: RFC TN-CC-01 — coding.empty() and text.exists()
    if not codings and text:
        return (
            True,
            f"CodeableConcept .coding leer/fehlt und .text vorhanden "
            f"('{text[:50]}') (TN-CC-01, RFC §9.2)",
            "warning",
        )
    # Case 2: Heuristik — coding hat code, aber kein anerkanntes System
    if codings:
        systems      = {c.get("system", "") for c in codings}
        has_specific = bool(systems & FHIR_SPECIFIC_SYSTEMS)
        has_code     = any(bool(c.get("code", "")) for c in codings)
        if has_code and not has_specific:
            slist = ", ".join(s for s in systems if s) or "(kein System)"
            return (
                True,
                f"Coding-System '{slist}' nicht in LOINC/SNOMED/ICD/ATC "
                f"(Heuristik, nicht TN-CC-01)",
                "info",
            )
    return False, "", ""


# ===========================================================================
# M-1: Value-Type-Klassifikation (FM-4 Def. 2.3)
# ===========================================================================

# Numerische OBX-2-Typen → Device-Messung erwartet → AD wenn OBX-15/16 fehlen
OBX_NUMERIC_TYPES: frozenset = frozenset({"NM", "NA", "SN", "NR"})
# Rein textuelle Typen → manuelle Eingabe → fehlende Device-Info kein AD
OBX_TEXT_TYPES:    frozenset = frozenset({"TX", "FT", "ST"})


# ===========================================================================
# M-2: Temporal Collapse — Kategorien mit Intervall-Semantik (FM-4 Def. 2.2)
# ===========================================================================

TC_INTERVAL_OBSERVATION_CATEGORIES: frozenset = frozenset({"procedure", "survey"})

CONTINUOUS_PROCEDURE_CODES_FHIR: dict = {
    "182777000": "Monitoring of patient",
    "385763009": "Hospice care",
    "386473003": "Continuous infusion",
}


# ===========================================================================
# M-6: Quantitative Verlust-Metrik — Entropie-Schätzer (FM-4 §4.1)
# ===========================================================================

LOSS_BITS_PER_PATTERN: dict = {
    LossPattern.TYPE_NARROWING.value:     math.log2(95_000),  # LOINC: ~16.5 bit
    LossPattern.TEMPORAL_COLLAPSE.value:  math.log2(60),      # 1h@60s: ~5.9 bit
    LossPattern.ATTRIBUTE_DROPPING.value: math.log2(16),      # konservativ: 4.0 bit
    LossPattern.REFERENCE_SEVERED.value:  24.0,               # FM-4 §4.1: 24 bit
}


def compute_loss_budget_bits_estimate(losses: list) -> float:
    """FM-4 §4.2: Verlust-Budget B(F) = Σ L(fi) in Bit."""
    return round(sum(
        LOSS_BITS_PER_PATTERN.get(
            l.pattern.value if hasattr(l.pattern, "value") else str(l.pattern),
            0.0,
        )
        for l in losses
    ), 2)


# ===========================================================================
# Sonstige Detektionskonstanten
# ===========================================================================

SPECIFIC_LAB_KEYWORDS = {
    "hemoglobin", "troponin", "lactate", "glucose", "creatinine",
    "hematocrit", "erythrocyt", "leukocyt", "platelet", "hba1c",
    "hbg", "wbc", "rbc", "plt", "hgb", "cbc", "panel", "differential",
}
GENERIC_FHIR_CATEGORIES = {
    "laboratory", "vital-signs", "procedure", "medication", "diagnosis",
}


# ===========================================================================
# K-3: Severity-Override-Komposition (FM-4 §2.4)
# ===========================================================================

@dataclass
class SeverityOverrideConfig:
    """
    FM-4 §2.4: Sigma_eff = o_tenant o o_default o Sigma_intrinsic.
    Override-Einträge: {pattern, location_prefix, severity}.
    Intrinsic severity (LossEvent.severity) bleibt unveränderlich.
    """
    default_overrides: list = field(default_factory=list)
    tenant_overrides:  dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, cfg: dict) -> "SeverityOverrideConfig":
        return cls(
            default_overrides=cfg.get("default_overrides", []),
            tenant_overrides=cfg.get("tenant_overrides", {}),
        )

    @classmethod
    def from_json_file(cls, path: str) -> "SeverityOverrideConfig":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def _apply_entries(self, event: "LossEvent", entries: list) -> str:
        sev = event.effective_severity
        for entry in entries:
            pattern_match = (
                not entry.get("pattern") or
                entry["pattern"] == event.pattern.value
            )
            loc_prefix = entry.get("location_prefix", "")
            loc_match  = not loc_prefix or event.location.startswith(loc_prefix)
            if pattern_match and loc_match:
                sev = entry["severity"]
        return sev


# ===========================================================================
# Datenklassen
# ===========================================================================

@dataclass
class LossEvent:
    pattern:            LossPattern
    location:           str
    description:        str
    severity:           str   # intrinsisch (Sigma_intrinsic) — nie verändern
    effective_severity: str = ""  # nach Override (Sigma_eff)

    def __post_init__(self):
        if not self.effective_severity:
            self.effective_severity = self.severity


@dataclass
class SILDReport:
    message_type:     str
    control_id:       str
    total_segments:   int
    total_losses:     int
    losses:           list  = field(default_factory=list)
    has_critical:     bool  = False
    has_warning:      bool  = False
    loss_budget_bits_estimate: float = 0.0   # FM-4 §4.1 Verlust-Budget in Bit

    def severity_counts(self) -> dict:
        return {
            "critical": sum(1 for l in self.losses if l.effective_severity == "critical"),
            "warning":  sum(1 for l in self.losses if l.effective_severity == "warning"),
            "info":     sum(1 for l in self.losses if l.effective_severity == "info"),
        }

    def intrinsic_severity_counts(self) -> dict:
        return {
            "critical": sum(1 for l in self.losses if l.severity == "critical"),
            "warning":  sum(1 for l in self.losses if l.severity == "warning"),
            "info":     sum(1 for l in self.losses if l.severity == "info"),
        }

    def to_json_dict(self) -> dict:
        return {
            "message_type":              self.message_type,
            "control_id":                self.control_id,
            "total_segments":            self.total_segments,
            "total_losses":              self.total_losses,
            "loss_budget_bits_estimate":          round(self.loss_budget_bits_estimate, 2),
            "severity_counts":           self.severity_counts(),
            "intrinsic_severity_counts": self.intrinsic_severity_counts(),
            "losses": [
                {
                    "pattern":            l.pattern.value,
                    "location":           l.location,
                    "description":        l.description,
                    "severity":           l.severity,
                    "effective_severity": l.effective_severity,
                }
                for l in self.losses
            ],
        }


def apply_severity_overrides(
    report: SILDReport,
    config: SeverityOverrideConfig,
    tenant_id: str = "",
) -> SILDReport:
    """FM-4 §2.4: Sigma_eff = o_tenant o o_default o Sigma_intrinsic."""
    tenant_entries = config.tenant_overrides.get(tenant_id, [])
    for event in report.losses:
        event.effective_severity = event.severity          # reset to intrinsic
        if config.default_overrides:
            event.effective_severity = config._apply_entries(event, config.default_overrides)
        if tenant_entries:
            event.effective_severity = config._apply_entries(event, tenant_entries)
    report.has_critical = any(e.effective_severity == "critical" for e in report.losses)
    report.has_warning  = any(e.effective_severity == "warning"  for e in report.losses)
    return report


# ===========================================================================
# M-5: FHIR AuditEvent (FM-4 §5.3) — FM-1-Tupel (t, τ, c, r, m)
# ===========================================================================

_PATTERN_DISPLAY = {
    LossPattern.TYPE_NARROWING.value:     "FM-4 Def. 2.1: Type Narrowing",
    LossPattern.TEMPORAL_COLLAPSE.value:  "FM-4 Def. 2.2: Temporal Collapse",
    LossPattern.ATTRIBUTE_DROPPING.value: "FM-4 Def. 2.3: Attribute Dropping",
    LossPattern.REFERENCE_SEVERED.value:  "FM-4 Def. 2.4: Reference Severing",
}
_SEV_TO_OUTCOME = {"info": "0", "warning": "4", "critical": "8"}


def fhir_audit_events_from_report(
    report: SILDReport,
    agent_info: Optional[dict] = None,
    tenant_id: str = "",
) -> list:
    """
    FM-4 §5.3: Erzeugt FHIR R4 AuditEvent-Ressourcen aus einem SILDReport.

    FM-1-Tupel-Abbildung:
      t  = AuditEvent.recorded
      tau = subtype.code  (SILD-Pattern + Rule-ID)
      c  = entity.what    (klinische Resource)
      r  = agent.who      (SILD-Detektor)
      m  = outcome / outcomeDesc (Severity + Beschreibung)

    Nur WARNING/CRITICAL-Findings erzeugen AuditEvents (FM-4 §5.2).
    """
    if agent_info is None:
        agent_info = {}
    agent_id = agent_info.get("name", "sild-detector")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    events = []
    for loss in report.losses:
        if loss.effective_severity not in ("warning", "critical"):
            continue
        pv      = loss.pattern.value if hasattr(loss.pattern, "value") else str(loss.pattern)
        outcome = _SEV_TO_OUTCOME.get(loss.effective_severity, "4")
        events.append({
            "resourceType": "AuditEvent",
            "type": {
                "system":  "http://terminology.hl7.org/CodeSystem/audit-event-type",
                "code":    "110100",
                "display": "Application Activity",
            },
            "subtype": [{                                              # τ
                "system":  "https://iscad-it.de/fhir/CodeSystem/sild-loss-pattern",
                "code":    pv,
                "display": _PATTERN_DISPLAY.get(pv, pv),
            }],
            "action":   "R",
            "recorded": ts,                                            # t
            "outcome":  outcome,
            "outcomeDesc": f"{loss.effective_severity}: {loss.description[:200]}",
            "agent": [{                                                 # r
                "who": {
                    "identifier": {
                        "system": "https://iscad-it.de/fhir/sild-detector",
                        "value":  agent_id,
                    }
                },
                "requestor": True,
            }],
            "source": {
                "observer": {"display": agent_id},
                "extension": [{
                    "url":         "https://iscad-it.de/fhir/StructureDefinition/sild-tenant",
                    "valueString": tenant_id or "default",
                }],
            },
            "entity": [{                                               # c
                "what": {"reference": loss.location},
                "type": {
                    "system":  "http://terminology.hl7.org/CodeSystem/audit-entity-type",
                    "code":    "2",
                    "display": "System Object",
                },
                "detail": [
                    {"type": "sild-pattern",         "valueString": pv},
                    {"type": "intrinsic-severity",   "valueString": loss.severity},
                    {"type": "effective-severity",   "valueString": loss.effective_severity},
                    {"type": "message-type",         "valueString": report.message_type},
                    {"type": "control-id",           "valueString": report.control_id},
                    {"type": "loss-budget-bits",
                     "valueString": str(LOSS_BITS_PER_PATTERN.get(pv, 0.0))},
                ],
            }],
        })
    return events


# ===========================================================================
# HL7 v2 Analyse
# ===========================================================================

def parse_hl7v2(message_text: str) -> list:
    msg = message_text.replace("\r\n", "\n").replace("\r", "\n")
    segments = []
    for line in msg.split("\n"):
        line = line.strip()
        if not line:
            continue
        fields = line.split("|")
        segments.append({"type": fields[0], "fields": fields, "raw": line})
    return segments


def _msh_info(segments: list) -> tuple:
    for seg in segments:
        if seg["type"] != "MSH":
            continue
        f = seg["fields"]
        msg_type = f[8]  if len(f) > 8  else "UNKNOWN"
        msg_id   = f[9]  if len(f) > 9  else "UNKNOWN"
        return msg_type, msg_id
    return "UNKNOWN", "UNKNOWN"


def analyse_hl7_message(message_text: str) -> SILDReport:
    """HL7 v2 SILD-Analyse mit allen FM-4 Def. 2.1–2.4 Mustern."""
    segments = parse_hl7v2(message_text)
    msg_type, msg_id = _msh_info(segments)
    losses: list = []

    current_obr_id: Optional[str] = None
    for seg in segments:
        seg_type = seg["type"]
        f = seg["fields"]

        if seg_type == "OBR":
            current_obr_id = f[2] if len(f) > 2 else "?"

            # --- Temporal Collapse (FM-4 Def. 2.2) ---
            obr_7 = f[7] if len(f) > 7 else ""
            obr_8 = f[8] if len(f) > 8 else ""
            if obr_7 and obr_8 and obr_7 != obr_8:
                losses.append(LossEvent(
                    LossPattern.TEMPORAL_COLLAPSE, f"OBR/{current_obr_id}",
                    f"OBR-7={obr_7} und OBR-8={obr_8} — Beobachtungsintervall "
                    f"kollabiert bei FHIR-Mapping auf effectiveDateTime (FM-4 Def. 2.2)",
                    "warning",
                ))

            # --- K-1: Type Narrowing — strukturierter Code (FM-4 Def. 2.1) ---
            usi = f[4] if len(f) > 4 else ""
            if usi:
                is_structured, tn_code, tn_system = _hl7_ce_structured(usi)
                if is_structured:
                    losses.append(LossEvent(
                        LossPattern.TYPE_NARROWING, f"OBR/{current_obr_id}",
                        f"OBR-4 strukturierter Code '{tn_code}' (System: '{tn_system}') — "
                        f"FHIR category='laboratory' verliert Terminologie-Spezifizität (FM-4 Def. 2.1)",
                        "info",
                    ))

        elif seg_type == "OBX":
            obx_id = f"{current_obr_id or '?'}.OBX{f[1] if len(f) > 1 else '?'}"
            # M-1 Fix: OBX-2 Value-Type bestimmt ob Device-Info semantisch erwartet wird
            obx_2  = f[2].strip().upper() if len(f) > 2 else ""
            obx_15 = f[15] if len(f) > 15 else ""
            obx_16 = f[16] if len(f) > 16 else ""

            # --- Attribute Dropping (FM-4 Def. 2.3, M-1) ---
            # Nur bei gerätemessbaren Typen (NM/NA/SN/NR oder unbekannt)
            # TX/FT/ST = manuelle Texteingabe → kein AD bei fehlender Device-Info
            if not obx_15 and not obx_16 and obx_2 not in OBX_TEXT_TYPES:
                losses.append(LossEvent(
                    LossPattern.ATTRIBUTE_DROPPING, f"OBX/{obx_id}",
                    f"OBX-2={obx_2 or '?'} (device-messbar): "
                    f"OBX-15/16 (Device/Observer) fehlen — "
                    f"Mess-Provenienz nicht propagierbar (FM-4 Def. 2.3, M-1)",
                    "info",
                ))

        elif seg_type == "ORC":
            orc_2 = f[2] if len(f) > 2 else ""
            if orc_2:
                # N-1 Fix: ORC-2 vorhanden ist kein bestätigtes RS (warning),
                # sondern ein potenzielles RS (info): die Referenz kann im Ziel
                # unauflösbar sein, muss aber nicht. FM-4 Def. 2.4 verlangt,
                # dass die Referenz im Ziel formal vorhanden aber unauflösbar ist —
                # das kann erst beim empfangenden System geprüft werden.
                losses.append(LossEvent(
                    LossPattern.REFERENCE_SEVERED, f"ORC/{orc_2}",
                    f"ORC-2 (Placer Order Number '{orc_2}') vorhanden — "
                    f"ohne ServiceRequest-Mapping im Zielsystem potenziell unauflösbar "
                    f"(FM-4 Def. 2.4, N-1)",
                    "info",
                ))

        elif seg_type == "PV1":
            pv1_19 = f[19] if len(f) > 19 else ""
            if pv1_19:
                losses.append(LossEvent(
                    LossPattern.REFERENCE_SEVERED, f"PV1/{pv1_19}",
                    f"PV1-19 (Visit Number '{pv1_19}') ohne Encounter-Mapping "
                    f"im Ziel nicht auflösbar (FM-4 Def. 2.4)",
                    "warning",
                ))

        elif seg_type == "RXA":
            rxa_6 = f[6] if len(f) > 6 else ""
            rxa_7 = f[7] if len(f) > 7 else ""
            if not rxa_6 or not rxa_7:
                losses.append(LossEvent(
                    LossPattern.ATTRIBUTE_DROPPING, "RXA",
                    "RXA ohne vollständige Dosis (RXA-6) oder Einheit (RXA-7) — "
                    "klinisch kritisch (FM-4 Def. 2.3)",
                    "critical",
                ))

    has_critical = any(l.effective_severity == "critical" for l in losses)
    has_warning  = any(l.effective_severity == "warning"  for l in losses)
    return SILDReport(
        message_type=msg_type,
        control_id=msg_id,
        total_segments=len(segments),
        total_losses=len(losses),
        losses=losses,
        has_critical=has_critical,
        has_warning=has_warning,
        loss_budget_bits_estimate=compute_loss_budget_bits_estimate(losses),
    )


# ===========================================================================
# M-3: Bundle-Referenz-Auflösbarkeit (FM-4 Def. 2.4)
# ===========================================================================

def _build_resolvable_refs(entries: list) -> set:
    """
    M-3: Baut die Menge aller im Bundle auflösbaren Referenzen auf.
    Enthält: ResourceType/id (relativ) und fullUrl (absolut/urn:uuid:).
    """
    refs: set = set()
    for entry in entries:
        res      = entry.get("resource", {})
        rtype_i  = res.get("resourceType", "")
        rid_i    = res.get("id", "")
        full_url = entry.get("fullUrl", "")
        if rtype_i and rid_i:
            refs.add(f"{rtype_i}/{rid_i}")
        if full_url:
            refs.add(full_url)
    return refs


def _rs_check_reference(
    resolvable: set, ref_field: dict, loc: str, field_name: str
) -> Optional[LossEvent]:
    """
    M-3 FM-4 Def. 2.4: Prüft eine einzelne FHIR-Referenz.
    Vorhanden + unauflösbar → warning RS
    Fehlend → info RS (möglicher Kontext-Verlust)
    """
    if not isinstance(ref_field, dict):
        return None
    ref = ref_field.get("reference", "")
    if ref:
        if ref not in resolvable:
            return LossEvent(
                LossPattern.REFERENCE_SEVERED, loc,
                f"{field_name}-Referenz '{ref}' formal vorhanden, aber nicht im Bundle "
                f"auflösbar — phi(r'i) leer (FM-4 Def. 2.4, M-3)",
                "warning",
            )
        return None  # vorhanden und auflösbar — kein Verlust
    else:
        return LossEvent(
            LossPattern.REFERENCE_SEVERED, loc,
            f"Kein {field_name}-Feld vorhanden; klinischer Kontext möglicherweise verloren "
            f"(FM-4 Def. 2.4, M-3)",
            "info",
        )


# ===========================================================================
# FHIR R4 Analyse
# ===========================================================================

def analyse_fhir_bundle(bundle: dict) -> SILDReport:
    """FHIR R4 SILD-Analyse mit allen FM-4 Def. 2.1–2.4 Mustern."""
    losses: list = []

    bundle_id   = bundle.get("id", "no-id")
    bundle_type = bundle.get("type", "unknown")
    entries     = bundle.get("entry", [])
    resources   = [e.get("resource", {}) for e in entries]

    # M-3: Auflösbarkeitsmenge aus allen Bundle-Entries aufbauen (vor Ressourcen-Loop)
    resolvable_refs = _build_resolvable_refs(entries)

    for resource in resources:
        rtype = resource.get("resourceType", "")
        rid   = resource.get("id", "?")
        loc   = f"{rtype}/{rid}"

        if rtype == "Observation":
            code_displays = [
                c.get("display", "").lower()
                for c in resource.get("code", {}).get("coding", [])
            ]
            cat_codes = [
                c.get("code", "")
                for cat in resource.get("category", [])
                for c in cat.get("coding", [])
            ]
            primary_cat = cat_codes[0] if cat_codes else ""

            # --- Temporal Collapse (FM-4 Def. 2.2, M-2) ---
            if "effectiveDateTime" in resource and "effectivePeriod" not in resource:
                # Primär: Kategorie impliziert Intervall (M-2 Fix)
                if primary_cat in TC_INTERVAL_OBSERVATION_CATEGORIES:
                    losses.append(LossEvent(
                        LossPattern.TEMPORAL_COLLAPSE, loc,
                        f"Kategorie '{primary_cat}' impliziert Zeitintervall; "
                        f"effectiveDateTime statt effectivePeriod — "
                        f"dim t(e) > dim t(e'') (FM-4 Def. 2.2, M-2)",
                        "warning",
                    ))
                # Fallback: Aggregat-Keyword im Code-Display
                elif any(
                    kw in disp
                    for disp in code_displays
                    for kw in {"mean", "average", "avg", "durchschnitt"}
                ):
                    losses.append(LossEvent(
                        LossPattern.TEMPORAL_COLLAPSE, loc,
                        f"Aggregat-Wert ('{code_displays[0] if code_displays else '?'}') "
                        f"auf Zeitpunkt reduziert (FM-4 Def. 2.2)",
                        "warning",
                    ))

            # --- K-1: Type Narrowing — CodeableConcept-Analyse (FM-4 Def. 2.1) ---
            code_cc = resource.get("code", {})
            is_narrowed, tn_reason, tn_severity = _fhir_cc_narrowing(code_cc)
            if is_narrowed:
                losses.append(LossEvent(
                    LossPattern.TYPE_NARROWING, loc,
                    f"Observation.code: {tn_reason} (FM-4 Def. 2.1)",
                    tn_severity,
                ))
            elif primary_cat in GENERIC_FHIR_CATEGORIES and any(
                kw in disp for disp in code_displays for kw in SPECIFIC_LAB_KEYWORDS
            ):
                losses.append(LossEvent(
                    LossPattern.TYPE_NARROWING, loc,
                    f"Kategorie '{primary_cat}' generisch; spezifischer Subtyp im Code "
                    f"(FM-4 Def. 2.1, Heuristik)",
                    "info",
                ))

            # --- M-3: Reference Severing — Encounter-Auflösbarkeit ---
            enc_event = _rs_check_reference(
                resolvable_refs,
                resource.get("encounter"),   # None wenn Feld fehlt
                loc, "encounter",
            )
            if enc_event:
                losses.append(enc_event)

            # --- Reference Severing: Labor ohne basedOn ---
            if primary_cat == "laboratory" and "basedOn" not in resource:
                losses.append(LossEvent(
                    LossPattern.REFERENCE_SEVERED, loc,
                    "Labor-Beobachtung ohne basedOn-Referenz; Auftragskontext verloren "
                    "(FM-4 Def. 2.4)",
                    "info",
                ))
            # --- Attribute Dropping: Labor ohne method/device ---
            if primary_cat == "laboratory" and "method" not in resource and "device" not in resource:
                losses.append(LossEvent(
                    LossPattern.ATTRIBUTE_DROPPING, loc,
                    "Labor ohne method/device — Messverfahren-Provenienz verloren "
                    "(FM-4 Def. 2.3)",
                    "info",
                ))

        elif rtype == "Procedure":
            codings    = resource.get("code", {}).get("coding", [])
            code_value = codings[0].get("code", "") if codings else ""

            # M-2 Fix: ALLE Prozeduren mit performedDateTime statt performedPeriod → TC
            if "performedDateTime" in resource and "performedPeriod" not in resource:
                if code_value in CONTINUOUS_PROCEDURE_CODES_FHIR:
                    # Bekannte kontinuierliche Prozedur → critical
                    losses.append(LossEvent(
                        LossPattern.TEMPORAL_COLLAPSE, loc,
                        f"Kontinuierliche Prozedur "
                        f"('{CONTINUOUS_PROCEDURE_CODES_FHIR[code_value]}') "
                        f"auf Zeitpunkt reduziert (FM-4 Def. 2.2, M-2, kritisch)",
                        "critical",
                    ))
                else:
                    # Jede andere Prozedur hat inhärente Dauer → warning
                    disp = (codings[0].get("display", code_value or "?")
                            if codings else "?")
                    losses.append(LossEvent(
                        LossPattern.TEMPORAL_COLLAPSE, loc,
                        f"Prozedur ('{disp}') mit performedDateTime statt "
                        f"performedPeriod — Intervall kollabiert (FM-4 Def. 2.2, M-2)",
                        "warning",
                    ))

        elif rtype == "MedicationAdministration":
            if "dosage" not in resource:
                losses.append(LossEvent(
                    LossPattern.ATTRIBUTE_DROPPING, loc,
                    "Medikamenten-Gabe ohne dosage — klinisch kritisch (FM-4 Def. 2.3)",
                    "critical",
                ))

        elif rtype == "Condition":
            # M-3: Encounter-Auflösbarkeit
            enc_event = _rs_check_reference(
                resolvable_refs,
                resource.get("encounter"),
                loc, "encounter",
            )
            if enc_event:
                losses.append(enc_event)

            # B1-TN: TN-CC-01 fuer Condition.code (RFC §9.2)
            cond_code_cc = resource.get("code", {})
            is_narrowed, tn_reason, tn_severity = _fhir_cc_narrowing(cond_code_cc)
            if is_narrowed:
                losses.append(LossEvent(
                    LossPattern.TYPE_NARROWING, loc,
                    f"Condition.code: {tn_reason} (FM-4 Def. 2.1)",
                    tn_severity,
                ))

            # B1-TN: TN-CC-01 fuer jeden Condition.bodySite[i] (RFC §9.2)
            for i, bs in enumerate(resource.get("bodySite", []) or []):
                is_narrowed, tn_reason, tn_severity = _fhir_cc_narrowing(bs)
                if is_narrowed:
                    losses.append(LossEvent(
                        LossPattern.TYPE_NARROWING, loc,
                        f"Condition.bodySite[{i}]: {tn_reason} (FM-4 Def. 2.1)",
                        tn_severity,
                    ))

    has_critical = any(l.effective_severity == "critical" for l in losses)
    has_warning  = any(l.effective_severity == "warning"  for l in losses)
    return SILDReport(
        message_type=f"Bundle/{bundle_type}",
        control_id=bundle_id,
        total_segments=len(resources),
        total_losses=len(losses),
        losses=losses,
        has_critical=has_critical,
        has_warning=has_warning,
        loss_budget_bits_estimate=compute_loss_budget_bits_estimate(losses),
    )


def using_real_cairn() -> bool:
    # Aktuell stets False: der Import-Hook (RealSILD) ist reserviert, aber kein
    # Delegationspfad implementiert. Die Backend-Gauge soll deshalb 0 melden —
    # bloße Paket-Anwesenheit ist explizit KEIN Signal aktiver Nutzung.
    return False
