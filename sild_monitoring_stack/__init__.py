# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""SILD Python-Paket — öffentliche API.

Importierbar als ``sild`` nach ``pip install git+https://github.com/fmatten/SILD.git``
(oder lokalem ``pip install -e path/to/SILD``).

Öffentliche API:
    LossPattern                     — Enum: TN / TC / AD / RS
    LossEvent                       — Einzelner Verlustevent
    SILDReport                      — Aggregierter Bericht
    analyse_fhir_bundle(bundle)     — R4-Bundle-Dict → SILDReport
    analyse_hl7_message(text)       — HL7-v2-String → SILDReport
    analyse_fhir_bundle_de(bundle)  — additive DE-Profile (MII/KBV/DeBasis)
    compute_loss_budget_bits_estimate(losses) → float
    fhir_audit_events_from_report(report)     → list[dict]
"""
from .sild_detector import (  # noqa: F401
    LossPattern,
    LossEvent,
    SILDReport,
    analyse_fhir_bundle,
    analyse_hl7_message,
    compute_loss_budget_bits_estimate,
    fhir_audit_events_from_report,
)
from .sild_fhir_profiles_de import analyse_fhir_bundle_de  # noqa: F401

__all__ = [
    "LossPattern",
    "LossEvent",
    "SILDReport",
    "analyse_fhir_bundle",
    "analyse_hl7_message",
    "compute_loss_budget_bits_estimate",
    "fhir_audit_events_from_report",
    "analyse_fhir_bundle_de",
]
