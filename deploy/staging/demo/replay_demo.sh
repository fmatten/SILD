#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
# SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
#
# DEP-1 Interop-Demo: spielt die SYNTHETISCHE Sequenz A01 -> A02 -> A03 ueber
# MLLP in die laufende SILD-Kette und liest nach jedem Schritt den publizierten
# Snapshot (m2_pull.db) READ-ONLY — genau so, wie aion-api die Pull-Flaeche sieht.
#
# Voraussetzung: die SILD-Kette laeuft (deploy/staging/docker-compose.sild.yml),
# /srv/sild/data/m2_pull.db wird vom sild-snapshot-Dienst aktualisiert.
# NUR synthetische Daten.
set -euo pipefail

PULL_DB="${PULL_DB:-/srv/sild/data/m2_pull.db}"
TARGET="${TARGET:-127.0.0.1:2575}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SETTLE="${SETTLE:-14}"   # > Publisher-Intervall (10s) + Poll (5s) -> Snapshot frisch

python3 "$HERE/make_demo_messages.py"

show() {   # liest den Snapshot READ-ONLY (wie AION), zeigt Stay + Segmente
  echo "    --- AION-Sicht (m2_pull.db, mode=ro) ---"
  python3 - "$PULL_DB" <<'PY'
import sqlite3, sys
db = sys.argv[1]
try:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
except Exception as e:
    print(f"    (Snapshot noch nicht da: {e})"); raise SystemExit
for r in c.execute("SELECT patient_key,visit_id,pattern,status FROM v_aion_stay WHERE patient_key='UKH|DEMO001'"):
    print(f"    stay: {r[0]} visit={r[1]} muster={r[2]} status={r[3]}")
segs = list(c.execute("SELECT ward,start_ts,end_ts FROM v_aion_segment seg "
                      "JOIN v_aion_stay s USING(stay_id) WHERE s.patient_key='UKH|DEMO001' ORDER BY seq"))
for w,a,b in segs:
    print(f"    segment: {w}  {a} -> {b or 'OFFEN'}")
print(f"    changes: {c.execute('SELECT COUNT(*) FROM v_aion_change').fetchone()[0]}")
c.close()
PY
}

send() {   # $1 = HL7-Datei
  docker run --rm --network host -v "$HERE/messages:/m:ro" \
    sild-stack/sild-chain:dep1 \
    python -u sild_mllp_sender.py --target "$TARGET" --file "/m/$1"
}

echo "### Schritt 1: A01 (Aufnahme NA)"; send demo01_adt_a01.hl7
echo "    warte ${SETTLE}s auf Kette+Snapshot..."; sleep "$SETTLE"; show

echo "### Schritt 2: A02 (Verlegung -> IM1)"; send demo02_adt_a02.hl7
echo "    warte ${SETTLE}s..."; sleep "$SETTLE"; show

echo "### Schritt 3: A03 (Entlassung)"; send demo03_adt_a03.hl7
echo "    warte ${SETTLE}s..."; sleep "$SETTLE"; show

echo "### Demo fertig. Erwartung: 1 Stay (Muster A, closed), Segmente NA -> IM1."
