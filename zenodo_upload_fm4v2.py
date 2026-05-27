#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
FM-4 v2 — Zenodo New-Version Upload Script
============================================
Erstellt eine neue Version des bestehenden FM-4-Deposits auf Zenodo.

Bestehendes Deposit : https://doi.org/10.5281/zenodo.20375435
Neue Datei          : FM-4-v2.pdf
Neue Lizenz         : AGPL-3.0-only OR LicenseRef-ISCaD-Commercial

Ablauf (Zenodo Legacy-API):
  1. POST /deposit/depositions/{id}/actions/newversion  → Draft-ID
  2. Alte Dateien aus Draft löschen
  3. FM-4-v2.pdf hochladen
  4. Metadaten aktualisieren
  5. POST /deposit/depositions/{draft_id}/actions/publish

Usage:
    python3 zenodo_upload_fm4v2.py --token YOUR_TOKEN
    python3 zenodo_upload_fm4v2.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

ZENODO_BASE_URL  = "https://zenodo.org/api"
EXISTING_RECORD  = "20375435"            # DOI 10.5281/zenodo.20375435
PDF_FILE         = Path(__file__).parent / "FM-4-v2.pdf"

METADATA = {
    "metadata": {
        "upload_type":      "publication",
        "publication_type": "technicalnote",
        "publication_date": "2026-05-26",
        "title": (
            "FM-4: Signal-Loss Inspection at Data-boundaries — "
            "Eine formale Detektorklasse für klinische Cross-System-Übertragungen "
            "(Version 2)"
        ),
        "creators": [
            {
                "name":        "Matten, Friedhelm",
                "affiliation": "ISCaD GmbH",
            }
        ],
        "description": (
            "<p>Wir formalisieren <em>Signal-Loss Inspection at Data-boundaries</em> (SILD) "
            "als modalitätsneutrale Detektorklasse für klinische Cross-System-Übertragungen. "
            "Aufbauend auf der in FM-1 entwickelten Informationsalgebra definieren wir vier "
            "kanonische Verlustmuster — <em>Type Narrowing</em>, <em>Temporal Collapse</em>, "
            "<em>Attribute Dropping</em>, <em>Reference Severing</em> — als Endo-Operatoren "
            "auf dem dort eingeführten Informationsraum.</p>"
            "<p>Die SILD-Komponente operationalisiert diese Operatoren als Detektoren an der "
            "Übertragungskante zwischen zwei klinischen Systemen. Wir zeigen, dass die "
            "Loss-Pattern-Algebra unabhängig vom konkreten Trägerformat ist (HL7 v2, FHIR R4, "
            "FHIR R5, DICOM SR), und leiten daraus eine Adapter-Architektur ab, bei der pro "
            "Trägerformat genau ein Pfad-Vokabular und ein Transport-Adapter ausgetauscht werden, "
            "während Taxonomie und Severity-Profil unverändert bleiben.</p>"
            "<p>Der Hauptsatz (Vollständigkeitssatz 2.5) sichert die Erschöpfung des Verlustraums; "
            "der Minimalitätssatz 2.7 zeigt, dass die Vier-Pattern-Taxonomie nicht reduzierbar ist. "
            "Eine quantitative Erweiterung schätzt den Verlust in Bit über Entropieabschätzungen "
            "in den Komponentenräumen. Die FHIR-R4/R5-Referenzimplementierung wird skizziert; "
            "der HL7-v2-MLLP-Sibling teilt denselben <code>core</code>-Layer.</p>"
            "<p>Anschluss an FM-1. Schwesterpaper zu FM-2 (CAIRN) und FM-3 (AION).</p>"
            "<p><strong>Version 2 (2026-05-26):</strong> Lizenz von CC-BY-4.0 auf "
            "AGPL-3.0-only OR Commercial (ISCaD GmbH) umgestellt. "
            "Referenzimplementierung SILD unter "
            "<a href=\"https://github.com/fmatten/SILD\">github.com/fmatten/SILD</a>.</p>"
            "<p>Copyright © 2026 Friedhelm Matten / ISCaD GmbH. "
            "Kommerzielle Lizenz: licensing@iscad-it.de</p>"
        ),
        "access_right": "open",
        "license":      "AGPL-3.0-only",
        "language":     "deu",
        "keywords": [
            "SILD",
            "Signal-Loss Inspection at Data-boundaries",
            "klinische Interoperabilität",
            "Verlustmuster",
            "Informationsalgebra",
            "FHIR",
            "HL7 v2",
            "FM-1",
            "FM-2",
            "CAIRN",
            "Adapter-Architektur",
            "Audit-Inferenz",
            "Type Narrowing",
            "Temporal Collapse",
            "health informatics",
            "formal methods",
        ],
        "related_identifiers": [
            {
                "identifier":    "10.5281/zenodo.19205557",
                "relation":      "cites",
                "resource_type": "publication",
            },
            {
                "identifier":    "10.5281/zenodo.19553130",
                "relation":      "references",
                "resource_type": "publication",
            },
            {
                "identifier":    "https://github.com/fmatten/SILD",
                "relation":      "isSupplementedBy",
                "resource_type": "software",
            },
        ],
        "notes": (
            "Version 2: Lizenzwechsel CC-BY-4.0 → AGPL-3.0-only OR Commercial. "
            "Anschluss an FM-1 (DOI: 10.5281/zenodo.19205557). "
            "Schwesterpaper zu FM-3/AION (DOI: 10.5281/zenodo.19553130). "
            "NOT a medical device (EU MDR 2017/745 / MPDG)."
        ),
    }
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def headers(token: str, json: bool = True) -> dict:
    h = {"Authorization": f"Bearer {token}"}
    if json:
        h["Content-Type"] = "application/json"
    return h


def check(r: requests.Response, action: str) -> dict:
    if not r.ok:
        print(f"  ✗ {action}: {r.status_code} — {r.text[:400]}")
        sys.exit(1)
    print(f"  ✓ {action}")
    return r.json()


# ── Main ───────────────────────────────────────────────────────────────────────

def run(token: str, dry_run: bool = False) -> None:
    print("\n" + "═" * 60)
    print("  FM-4 v2 — Zenodo New-Version Upload")
    print(f"  Datei    : {PDF_FILE.name} ({PDF_FILE.stat().st_size // 1024} KB)")
    print(f"  Basis    : https://doi.org/10.5281/zenodo.{EXISTING_RECORD}")
    print(f"  Lizenz   : {METADATA['metadata']['license']}")
    print(f"  Dry-run  : {dry_run}")
    print("═" * 60)

    if dry_run:
        print(f"\n  ✓ Datei vorhanden : {PDF_FILE.exists()}")
        print(f"  ✓ Titel  : {METADATA['metadata']['title'][:70]}...")
        print(f"  ✓ Autor  : {METADATA['metadata']['creators'][0]['name']}")
        print(f"  ✓ Datum  : {METADATA['metadata']['publication_date']}")
        print(f"  ✓ Lizenz : {METADATA['metadata']['license']}")
        print(f"  ✓ Keywords: {len(METADATA['metadata']['keywords'])} Einträge")
        print(f"  ✓ Related: {len(METADATA['metadata']['related_identifiers'])} Identifier")
        print("\n[DRY-RUN] Bereit für Upload.")
        print("  Starte mit: python3 zenodo_upload_fm4v2.py --token TOKEN")
        return

    # Step 1: Create new version draft from existing record
    print(f"\n[1] Neue Version von Deposit {EXISTING_RECORD} erstellen ...")
    r = requests.post(
        f"{ZENODO_BASE_URL}/deposit/depositions/{EXISTING_RECORD}/actions/newversion",
        headers=headers(token, json=False),
    )
    data     = check(r, "Neue Version (Draft) erstellt")
    draft_url = data["links"]["latest_draft"]
    draft_id  = draft_url.rstrip("/").split("/")[-1]
    print(f"     Draft-ID : {draft_id}")

    # Step 2: Delete old files from draft
    print("\n[2] Alte Dateien aus Draft entfernen ...")
    r = requests.get(
        f"{ZENODO_BASE_URL}/deposit/depositions/{draft_id}/files",
        headers=headers(token),
    )
    files = check(r, "Dateiliste geladen")
    for f in files:
        rd = requests.delete(
            f"{ZENODO_BASE_URL}/deposit/depositions/{draft_id}/files/{f['id']}",
            headers=headers(token, json=False),
        )
        if not rd.ok:
            print(f"  ✗ Löschen {f['filename']}: {rd.status_code}")
            sys.exit(1)
        print(f"  ✓ Entfernt: {f['filename']}")

    # Step 3: Get bucket URL and upload new PDF
    print(f"\n[3] {PDF_FILE.name} hochladen ...")
    r = requests.get(
        f"{ZENODO_BASE_URL}/deposit/depositions/{draft_id}",
        headers=headers(token),
    )
    deposit_data = check(r, "Draft-Details geladen")
    bucket_url   = deposit_data["links"]["bucket"]

    with open(PDF_FILE, "rb") as f:
        r = requests.put(
            f"{bucket_url}/{PDF_FILE.name}",
            data=f,
            headers=headers(token, json=False),
        )
    check(r, f"{PDF_FILE.name} hochgeladen")

    # Step 4: Update metadata
    print("\n[4] Metadaten aktualisieren ...")
    r = requests.put(
        f"{ZENODO_BASE_URL}/deposit/depositions/{draft_id}",
        json=METADATA,
        headers=headers(token),
    )
    check(r, "Metadaten gesetzt")

    # Step 5: Publish
    print("\n[5] Veröffentlichen ...")
    r = requests.post(
        f"{ZENODO_BASE_URL}/deposit/depositions/{draft_id}/actions/publish",
        headers=headers(token, json=False),
    )
    result = check(r, "Veröffentlicht!")
    doi = result.get("doi", "?")
    url = result.get("links", {}).get("html", f"https://zenodo.org/records/{draft_id}")

    print("\n" + "═" * 60)
    print("  ✅ FM-4 v2 auf Zenodo veröffentlicht!")
    print(f"  DOI : {doi}")
    print(f"  URL : {url}")
    print("═" * 60 + "\n")


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FM-4 v2 Zenodo New-Version Upload")
    parser.add_argument("--token",   help="Zenodo API Token")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = args.token or os.environ.get("ZENODO_TOKEN", "")
    if not token:
        try:
            token = Path("/home/iscad/.zt").read_text().strip()
            print("Token aus /home/iscad/.zt gelesen.")
        except FileNotFoundError:
            if args.dry_run:
                token = "dry-run"
            else:
                print("Fehler: Kein Token. Setze ZENODO_TOKEN oder --token TOKEN")
                sys.exit(1)

    run(token=token, dry_run=args.dry_run)
