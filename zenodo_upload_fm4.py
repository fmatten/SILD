#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only
"""
FM-4 — Zenodo Upload Script
============================
Creates a new Zenodo deposit for FM-4.pdf.

Usage:
    python3 zenodo_upload_fm4.py --token YOUR_TOKEN
    python3 zenodo_upload_fm4.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

ZENODO_BASE_URL = "https://zenodo.org/api"
PDF_FILE        = Path(__file__).parent / "FM-4.pdf"

METADATA = {
    "metadata": {
        "upload_type":      "publication",
        "publication_type": "technicalnote",
        "publication_date": "2026-05-25",
        "title": (
            "FM-4: Signal-Loss Inspection at Data-boundaries — "
            "Eine formale Detektorklasse für klinische Cross-System-Übertragungen"
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
            "<p>Copyright © 2026 Friedhelm Matten / ISCaD GmbH.</p>"
        ),
        "access_right": "open",
        "license":      "cc-by-4.0",
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
        ],
        "notes": (
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
        print(f"  ✗ {action}: {r.status_code} — {r.text[:300]}")
        sys.exit(1)
    print(f"  ✓ {action}")
    return r.json()


# ── Main ───────────────────────────────────────────────────────────────────────

def run(token: str, dry_run: bool = False) -> None:
    print("\n" + "═" * 60)
    print("  FM-4 — Zenodo Upload")
    print(f"  Datei   : {PDF_FILE.name} ({PDF_FILE.stat().st_size // 1024} KB)")
    print(f"  Dry-run : {dry_run}")
    print("═" * 60)

    if dry_run:
        print(f"\n  ✓ Datei vorhanden : {PDF_FILE.exists()}")
        print(f"  ✓ Titel  : {METADATA['metadata']['title'][:60]}...")
        print(f"  ✓ Autor  : {METADATA['metadata']['creators'][0]['name']}")
        print(f"  ✓ Datum  : {METADATA['metadata']['publication_date']}")
        print(f"  ✓ Lizenz : {METADATA['metadata']['license']}")
        print(f"  ✓ Keywords: {len(METADATA['metadata']['keywords'])} Einträge")
        print("\n[DRY-RUN] Bereit für Upload.")
        print("  Starte mit: python3 zenodo_upload_fm4.py --token TOKEN")
        return

    # Step 1: Create deposit
    print("\n[1] Neues Deposit erstellen ...")
    r = requests.post(
        f"{ZENODO_BASE_URL}/deposit/depositions",
        json={},
        headers=headers(token),
    )
    deposit = check(r, "Deposit erstellt")
    deposit_id = deposit["id"]
    bucket_url = deposit["links"]["bucket"]
    print(f"     Deposit-ID : {deposit_id}")

    # Step 2: Upload PDF
    print(f"\n[2] {PDF_FILE.name} hochladen ...")
    with open(PDF_FILE, "rb") as f:
        r = requests.put(
            f"{bucket_url}/{PDF_FILE.name}",
            data=f,
            headers=headers(token, json=False),
        )
    check(r, f"{PDF_FILE.name} hochgeladen")

    # Step 3: Set metadata
    print("\n[3] Metadaten setzen ...")
    r = requests.put(
        f"{ZENODO_BASE_URL}/deposit/depositions/{deposit_id}",
        json=METADATA,
        headers=headers(token),
    )
    check(r, "Metadaten gesetzt")

    # Step 4: Publish
    print("\n[4] Veröffentlichen ...")
    r = requests.post(
        f"{ZENODO_BASE_URL}/deposit/depositions/{deposit_id}/actions/publish",
        headers=headers(token, json=False),
    )
    result = check(r, "Veröffentlicht!")
    doi = result.get("doi", "?")
    url = result.get("links", {}).get("html", f"https://zenodo.org/records/{deposit_id}")

    print("\n" + "═" * 60)
    print("  ✅ FM-4 auf Zenodo veröffentlicht!")
    print(f"  DOI : {doi}")
    print(f"  URL : {url}")
    print("═" * 60 + "\n")


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FM-4 Zenodo Upload")
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
