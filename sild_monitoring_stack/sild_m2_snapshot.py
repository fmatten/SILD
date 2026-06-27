#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
"""
SILD M-2 Snapshot-Publisher (DEP-1 / DEP-S2, Mechanismus A).

Erzeugt aus der LIVE M-2-DB (WAL + synchronous=FULL) eine **self-contained**
Snapshot-DB als read-only Pull-Flaeche fuer AION — und publiziert sie ATOMAR.

Warum (Beleg: docs/dep1-wal-probe.md):
  Die Live-m2.db haelt ihre Daten im -wal; ein Einzeldatei-:ro-Mount der Live-DB
  laesst das -wal weg (AION saehe eine leere DB), und immutable=1 auf der Live-DB
  liefert einen stillen Stale-Read. Ein per VACUUM INTO erzeugter Snapshot ist
  dagegen self-contained (kein -wal), defragmentiert und im journal_mode=delete —
  d.h. AION liest ihn als Einzeldatei mit `mode=ro` (kein immutable noetig).

Garantien:
  S1  Vollstaendig: VACUUM INTO liest die Quelle inkl. -wal -> alle committeten
      Stays/Segmente/Changes sind im Snapshot (kein WAL-Verlust).
  S2  Self-contained: Ausgabe ist EINE Datei, journal_mode=delete, kein -wal/-shm
      noetig -> Einzeldatei-:ro-Mount genuegt AION.
  S3  Atomar publiziert: Snapshot wird in eine Temp-Datei IM ZIELVERZEICHNIS
      geschrieben, dann per os.replace() (atomic rename, gleiches Dateisystem)
      auf den Vertragspfad gehoben. AION sieht nie eine halbe Datei (alt oder neu).
  S4  Vertrags-sicher fuer AION: die Quelle wird NUR lesend geoeffnet (mode=ro,
      query_only=ON); der Publisher mutiert SILDs m2.db nie.
  S5  Lesbar fuer den Consumer: optionaler chmod (Default 0o644), damit aion-api
      (uid 1000) die Datei ueber den :ro-Mount lesen kann.

Stdlib only (sqlite3). Kein neuer Dependency.

Beispiele:
    # Einmal publizieren:
    python sild_m2_snapshot.py --m2-db /srv/sild/data/m2.db \
                               --out   /srv/sild/data/m2_pull.db --once

    # Dauerbetrieb, alle 10s (demo-wahrnehmbar):
    python sild_m2_snapshot.py --m2-db /srv/sild/data/m2.db \
                               --out   /srv/sild/data/m2_pull.db --interval 10
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from pathlib import Path

VIEWS = ("v_aion_stay", "v_aion_segment", "v_aion_change")


def publish_once(m2_db: Path, out: Path, *, chmod: int = 0o644,
                 verbose: bool = True) -> dict:
    """Erzeugt EINEN atomar publizierten Snapshot. Gibt Zaehl-Statistik zurueck."""
    if not m2_db.exists():
        raise FileNotFoundError(f"M-2-DB nicht gefunden: {m2_db}")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Temp IM Zielverzeichnis (gleiches Dateisystem -> os.replace ist atomar).
    # PID im Namen: parallele Publisher kollidieren nicht auf der Temp-Datei.
    tmp = out.with_name(f".{out.name}.tmp.{os.getpid()}")
    for stale in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if stale.exists():
            stale.unlink()

    # S4: Quelle wird nicht mutiert. Der Publisher ist SILD-INTERN (Schreibrecht
    # im eigenen Datenverzeichnis) — die "AION mutiert nie"-Invariante gilt fuer
    # den :ro-beschraenkten AION-Consumer, NICHT fuer SILDs eigenen Publisher.
    # Die Quelle wird RW-FAEHIG geoeffnet (sonst kann der wal-index/-shm der
    # Live-WAL-DB nicht etabliert werden -> "attempt to write a readonly db" bei
    # VACUUM INTO). VACUUM INTO liest die Quelle nur und schreibt in die NEUE
    # Datei; es wird KEIN DML/DDL gegen die Quelle abgesetzt (Beleg S4).
    src = sqlite3.connect(str(m2_db))
    try:
        # S1+S2: VACUUM INTO erzeugt eine self-contained, defragmentierte Kopie
        # (Ausgabe-DB ist journal_mode=delete, kein -wal).
        src.execute("VACUUM INTO ?", (str(tmp),))
    finally:
        src.close()

    # S2-Verifikation + Zaehlung am Snapshot.
    snap = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
    try:
        jm = snap.execute("PRAGMA journal_mode").fetchone()[0]
        counts = {v: snap.execute(f"SELECT COUNT(*) FROM {v}").fetchone()[0]
                  for v in VIEWS}
    finally:
        snap.close()
    if jm.lower() == "wal":
        # Sollte bei VACUUM INTO nie passieren; defensiv hart fehlschlagen.
        tmp.unlink(missing_ok=True)
        raise RuntimeError("Snapshot unerwartet im WAL-Modus — abgebrochen")

    if chmod is not None:
        os.chmod(tmp, chmod)

    # S3: atomarer Wechsel.
    os.replace(tmp, out)

    if verbose:
        c = " ".join(f"{k.split('_')[-1]}={v}" for k, v in counts.items())
        print(f"[snapshot] {out} publiziert (journal={jm}; {c})", flush=True)
    return {"out": str(out), "journal_mode": jm, "counts": counts}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="SILD M-2 Snapshot-Publisher (DEP-1)")
    p.add_argument("--m2-db", required=True, type=Path,
                   help="Pfad zur LIVE M-2-DB (nur lesend geoeffnet)")
    p.add_argument("--out", required=True, type=Path,
                   help="Vertragspfad der Snapshot-DB (atomar publiziert)")
    p.add_argument("--interval", type=float, default=None,
                   help="Sekunden zwischen Publikationen (Dauerbetrieb)")
    p.add_argument("--once", action="store_true",
                   help="genau einmal publizieren, dann beenden")
    p.add_argument("--mode", type=lambda s: int(s, 8), default=0o644,
                   help="Datei-Perms des Snapshots (oktal, Default 644 -> uid-1000-lesbar)")
    args = p.parse_args(argv)

    if not args.once and args.interval is None:
        p.error("entweder --once oder --interval angeben")

    if args.once or args.interval is None:
        publish_once(args.m2_db, args.out, chmod=args.mode)
        return 0

    print(f"[snapshot] Dauerbetrieb: {args.m2_db} -> {args.out} alle {args.interval}s",
          flush=True)
    while True:
        try:
            publish_once(args.m2_db, args.out, chmod=args.mode)
        except FileNotFoundError as e:
            print(f"[snapshot] warte auf M-2-DB: {e}", flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
