# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
SILD FHIR DE-Basisprofile Adapter — sild.fhir.profiles_de

FM-4 §3.2: Implementiert (Pi_de, phi_de) — die deutsche Pfadsprache und
Prädikate für MII (Medizininformatik-Initiative), KBV und DeBasis-Profile.

Erkannte DE-spezifische Verlustmuster (additiv zur Basis-Analyse):
  TN  — Observation ohne UCUM-Einheit bei numerischen Werten
  TN  — MedicationAdministration ohne ATC-Code
  AD  — Condition (ICD-10-GM) ohne Diagnosesicherheitserweiterung (V/A/Z/G)
  AD  — Patient ohne gesetzliche Krankenversichertennummer (KVid)

Verwendung:
  from sild_fhir_profiles_de import analyse_fhir_bundle_de
  de_losses = analyse_fhir_bundle_de(bundle)  # list[LossEvent]

License: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
Part of: SILD MLLP Sidecar Demo
"""

try:
    from .sild_detector import LossEvent, LossPattern  # package import
except ImportError:
    from sild_detector import LossEvent, LossPattern   # standalone (Docker sidecar)


# ---------------------------------------------------------------------------
# DE-spezifische Terminologie-Konstanten
# ---------------------------------------------------------------------------

# ICD-10-GM Coding-Systeme
ICD10GM_SYSTEMS: frozenset = frozenset({
    "http://fhir.de/CodeSystem/bfarm/icd-10-gm",
    "http://fhir.de/CodeSystem/dimdi/icd-10-gm",
})

# Extension-URL für ICD-10-GM Diagnosesicherheit (V/A/Z/G)
DIAGNOSESICHERHEIT_EXT = (
    "http://fhir.de/StructureDefinition/icd-10-gm-diagnosesicherheit"
)
DIAGNOSESICHERHEIT_VALUES: frozenset = frozenset({"V", "A", "Z", "G"})

# KBV / GKV Krankenversichertennummer-Systeme
KVN_SYSTEMS: frozenset = frozenset({
    "http://fhir.de/sid/gkv/kvid-10",
    "http://fhir.de/NamingSystem/gkv/kvid-10",
    "http://fhir.de/sid/pkv/kvid-10",
    "http://fhir.de/NamingSystem/pkv/pkvid",
})

# ATC-Medikamenten-Klassifikation
ATC_SYSTEM = "http://www.whocc.no/atc"

# UCUM-Einheitensystem (Unified Code for Units of Measure)
UCUM_SYSTEM = "http://unitsofmeasure.org"


# ---------------------------------------------------------------------------
# Regel-Funktionen (je eine pro MII/DE-Profil-Check)
# ---------------------------------------------------------------------------

def _check_icd10gm_diagnosesicherheit(resource: dict, loc: str) -> list:
    """
    FM-4 §3.2 DE-Regel 1: ICD-10-GM Condition ohne Diagnosesicherheit.

    Die KBV-Anforderung schreibt für jede ICD-10-GM-Kodierung die
    Diagnosesicherheitserweiterung (V=Verdacht, A=Ausschluss, Z=Zustand,
    G=Gesichert) vor. Fehlt sie, ist der diagnostische Modifier verloren.

    FM-4 Def. 2.3 (AD): Modifier mi in m(e) aber nicht in m(e'').
    """
    losses = []
    codings = resource.get("code", {}).get("coding", [])
    icd_codings = [c for c in codings if c.get("system", "") in ICD10GM_SYSTEMS]

    if not icd_codings:
        return losses  # kein ICD-10-GM → nicht anwendbar

    extensions = resource.get("extension", [])
    ext_urls   = {e.get("url", "") for e in extensions}

    if DIAGNOSESICHERHEIT_EXT not in ext_urls:
        # Diagnosesicherheit fehlt → AD
        codes = ", ".join(
            c.get("code", "?") for c in icd_codings[:3]
        )
        losses.append(LossEvent(
            LossPattern.ATTRIBUTE_DROPPING, loc,
            f"ICD-10-GM Diagnose ({codes}) ohne Diagnosesicherheitserweiterung "
            f"(V/A/Z/G per KBV-Vorgabe) — Modifier verloren "
            f"(FM-4 Def. 2.3, DE-Profil §3.2)",
            "warning",
        ))
    return losses


def _check_observation_ucum(resource: dict, loc: str) -> list:
    """
    FM-4 §3.2 DE-Regel 2: Numerische Observation ohne UCUM-Einheit.

    MII-Laborbefund-Profil: valueQuantity.system MUSS UCUM sein.
    Fehlt system oder ist nicht UCUM, verliert der Wert seine Einheitssemantik.

    FM-4 Def. 2.1 (TN): Typ (Einheit mit Semantik) auf Freitext degradiert.
    """
    losses = []
    vq = resource.get("valueQuantity", {})
    if not vq:
        return losses  # kein numerischer Wert → nicht anwendbar

    unit_system = vq.get("system", "")
    unit_code   = vq.get("code", "")
    unit_unit   = vq.get("unit", "")

    if not unit_system:
        losses.append(LossEvent(
            LossPattern.TYPE_NARROWING, loc,
            f"valueQuantity ohne Einheitensystem (unit='{unit_unit}', code='{unit_code}') — "
            f"fehlende Einheitssemantik (FM-4 Def. 2.1, DE-Profil §3.2)",
            "info",
        ))
    elif unit_system != UCUM_SYSTEM:
        losses.append(LossEvent(
            LossPattern.TYPE_NARROWING, loc,
            f"valueQuantity.system='{unit_system}' ist nicht UCUM ({UCUM_SYSTEM}) — "
            f"MII-Labor-Profil erfordert UCUM (FM-4 Def. 2.1, DE-Profil §3.2)",
            "info",
        ))
    return losses


def _check_medication_atc(resource: dict, loc: str) -> list:
    """
    FM-4 §3.2 DE-Regel 3: MedicationAdministration ohne ATC-Code.

    Deutsche Medikationsdaten verwenden ATC-Codes (WHO/DIMDI-Klassifikation).
    Fehlt der ATC-Code, verliert die Medikamentensemantik ihre Terminologie-Tiefe.

    FM-4 Def. 2.1 (TN): Spezifischer ATC-Code auf generische Bezeichnung degradiert.
    """
    losses = []
    # Versuche verschiedene FHIR-Felder für Medikamentenkodierung
    med_cc = (
        resource.get("medicationCodeableConcept") or
        resource.get("medication", {}).get("concept") or
        {}
    )
    codings = med_cc.get("coding", []) if isinstance(med_cc, dict) else []
    atc_codings = [c for c in codings if c.get("system", "") == ATC_SYSTEM]

    if codings and not atc_codings:
        systems = {c.get("system", "(?)") for c in codings}
        losses.append(LossEvent(
            LossPattern.TYPE_NARROWING, loc,
            f"MedicationAdministration hat Coding aus {systems} aber keinen ATC-Code — "
            f"DE-Medikationssemantik verloren (FM-4 Def. 2.1, DE-Profil §3.2)",
            "info",
        ))
    return losses


def _check_patient_kvn(resource: dict, loc: str) -> list:
    """
    FM-4 §3.2 DE-Regel 4: Patient ohne Krankenversichertennummer.

    MII-Basismodul Person: Patient SOLLTE GKV/PKV-Identifier tragen.
    Fehlt er, ist der gesetzliche Versicherungskontext nicht rekonstruierbar.

    FM-4 Def. 2.3 (AD): Modifier (Versicherungskontext) in Ziel verloren.
    """
    losses = []
    identifiers = resource.get("identifier", [])
    if not identifiers:
        # Gar keine Identifier → keine KVN möglich
        losses.append(LossEvent(
            LossPattern.ATTRIBUTE_DROPPING, loc,
            "Patient ohne Identifier-Feld — Krankenversichertennummer (KVid) "
            "fehlt (FM-4 Def. 2.3, DE-Profil §3.2)",
            "info",
        ))
        return losses

    kvn_ids = [
        ident for ident in identifiers
        if ident.get("system", "") in KVN_SYSTEMS
    ]
    if not kvn_ids:
        used_systems = {ident.get("system", "?") for ident in identifiers}
        losses.append(LossEvent(
            LossPattern.ATTRIBUTE_DROPPING, loc,
            f"Patient hat Identifier ({used_systems}) aber keine KVid "
            f"(GKV/PKV) — gesetzlicher Versicherungskontext verloren "
            f"(FM-4 Def. 2.3, DE-Profil §3.2)",
            "info",
        ))
    return losses


# ---------------------------------------------------------------------------
# Haupt-Einstiegspunkt
# ---------------------------------------------------------------------------

def analyse_fhir_bundle_de(bundle: dict) -> list:
    """
    FM-4 §3.2: DE-Basisprofile-Adapter — (Pi_de, phi_de).

    Wendet die vier MII/KBV-spezifischen Regeln auf alle Ressourcen im Bundle an.
    Gibt list[LossEvent] zurück — rein additiv, keine Duplikate mit der
    Standard-Analyse (analyse_fhir_bundle).

    Aufruf in sild_fhir_filter.py:
        de_losses = analyse_fhir_bundle_de(bundle)
        report.losses.extend(de_losses)
    """
    losses: list = []

    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rtype    = resource.get("resourceType", "")
        rid      = resource.get("id", "?")
        loc      = f"{rtype}/{rid}"

        if rtype == "Condition":
            losses.extend(_check_icd10gm_diagnosesicherheit(resource, loc))

        elif rtype == "Observation":
            losses.extend(_check_observation_ucum(resource, loc))

        elif rtype == "MedicationAdministration":
            losses.extend(_check_medication_atc(resource, loc))

        elif rtype == "Patient":
            losses.extend(_check_patient_kvn(resource, loc))

    return losses
