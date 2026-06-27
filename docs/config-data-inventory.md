<!--
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
-->

# SILD DEP-1 — Config- & Data-Inventory

**Stand:** main `bbc1628` (DEP-1-Konsolidierung) · **Erhebung:** read-only aus Tree
(`deploy/staging/docker-compose.sild.yml` + `sild_monitoring_stack/*.py`).
Host-/Laufzeitwerte (UID/GID/Owner) stammen **nicht** aus dem Tree, sondern sind als
**belegt auf aion-staging `.45`** (Re-Deploy `bbc1628` / Journal `56f5484`) zitiert und
ausdrücklich als host-spezifisch markiert — **keine** Vorgabe.

Betrifft die **DEP-1-Integrationskette** (`deploy/staging/docker-compose.sild.yml`),
**nicht** den eigenständigen Demo-/Betriebs-Stack `sild_monitoring_stack/docker-compose.yml`.

---

## Abschnitt 1 — Konfigurationsvariablen

Die Deploy-Compose referenziert genau **drei** `${VAR}` (erhoben via
`git grep '\$\{[A-Z_]+' -- deploy/staging/docker-compose.sild.yml`). Sie werden über
`deploy/staging/.env` geliefert (gitignored via `deploy/staging/.gitignore`); die
getrackte Vorlage ist `deploy/staging/.env.example`.

### `SILD_UID`
- **Zweck:** UID des `sild`-Service-Users; alle vier Container laufen als `${SILD_UID}:${SILD_GID}` und schreiben die DBs unter `/srv/sild/data` als dieser User.
- **Typ:** Integer. **Host-spezifisch, kein Default.** Leere Substitution ⇒ Container liefe als root (historischer Fehler, geheilt im Re-Deploy `bbc1628`).
- **Compose-Referenz:** `user: "${SILD_UID}:${SILD_GID}"` — Zeilen 23/44/59/81.
- **Beispiel (Vorlage):** `SILD_UID=` (leer; ermitteln mit `id -u sild`).
- **Belegter Ist-Wert `.45`:** `997` (Owner-Kopplung an `/srv/sild/data`; nur dort gültig, nicht portierbar).

### `SILD_GID`
- **Zweck:** GID der `sild`-Service-Gruppe; Owner-Kopplung an `/srv/sild/data` wie `SILD_UID`.
- **Typ:** Integer. **Host-spezifisch, kein Default.**
- **Compose-Referenz:** s. `SILD_UID` (gleiche Zeilen).
- **Beispiel (Vorlage):** `SILD_GID=` (leer; ermitteln mit `id -g sild`).
- **Belegter Ist-Wert `.45`:** `986`.

### `SILD_M2_JITTER`
- **Zweck:** Jitter-Fenster (Sekunden) des M-2-Mappers — puffert ADT-Events gegen Out-of-Order-Ankunft, bevor sie auf Stays angewandt werden. **Tuning-Parameter, nicht host-gebunden, kein Geheimnis.**
- **Typ:** Integer Sekunden. **Funktions-Default: `300`** (prod-sicher).
- **Compose-Referenz:** `--jitter-window "${SILD_M2_JITTER:-300}"` — Zeile 71.
- **Beispiel:** `SILD_M2_JITTER=300` (prod) bzw. `5` für In-Order-Demo (sonst wird ein frisch gesendetes ADT erst nach 5 min sichtbar).
- **Belegter Ist-Wert `.45`:** `300` (fmatten-Override `5` im Re-Deploy entfernt).

---

## Abschnitt 2 — Datenbehälter (DBs)

Alle vier DBs liegen auf **einem geteilten Host-Bind**: `/srv/sild/data:/data`
(`volumes:` Zeilen 35/52/73/89) — **Host-Bind, kein Named Volume**. Owner `sild:sild`
(`997:986`) ist `.45`-Laufzeit (Re-Deploy `bbc1628`), Perms `data/` = `0750`.
Persistenz: über den Host-Pfad, überlebt Container-Recreate.

### `intake.db`
- **Rolle:** Roh-Ingest. `sild-filter` (`sild_mllp_filter.py`) persistiert MLLP-Nachrichten **persist-before-ack** in die `intake`-Tabelle.
- **Schreiber:** `sild-filter` via `--durable-store /data/intake.db` (Compose Z.27); `DurableStore`.
- **Leser:** `sild-m1` und `sild-m2` lesen `intake` **read-only** (`mode=ro` + `PRAGMA query_only=ON`).
- **Typ/WAL:** SQLite, **WAL + `synchronous=FULL`** (`sild_durable_store.py:303-304`) ⇒ erzeugt `intake.db-wal` / `intake.db-shm`.
- **Persistenz:** `/srv/sild/data/intake.db`, Host-Bind, Owner `sild:sild`.

### `m1.db`
- **Rolle:** Output Stufe **M-1** (Sichtung/Mapping der intake-Nachrichten).
- **Schreiber:** `sild-m1` (`sild_mapper_m1.py`) via `--mapper-db /data/m1.db` (Compose Z.49); liest dabei `--intake-db` read-only.
- **Leser:** `sild-m2` liest `m1` read-only (`mode=ro` + `query_only`).
- **Typ/WAL:** SQLite, **WAL + `synchronous=FULL`** (`sild_mapper_m1.py:510-511`) ⇒ `-wal`/`-shm`.
- **Persistenz:** `/srv/sild/data/m1.db`, Host-Bind, Owner `sild:sild`.

### `m2.db`  ← Vertrags-DB der AION-Schnittstelle
- **Rolle:** Output Stufe **M-2** (Intervalle/Stays); trägt die drei Views `v_aion_stay` / `v_aion_segment` / `v_aion_change`. **AION liest diese DB read-only über die 3 Views und mutiert sie nie** (nicht-verhandelbare Invariante).
- **Schreiber:** `sild-m2` (`sild_mapper_m2.py`) via `--m2-db /data/m2.db` (Compose Z.65); liest `m1`+`intake` read-only.
- **Leser:** `sild-snapshot` liest `m2.db` als Quelle für den Snapshot (RW-geöffnet **nur** wegen `VACUUM INTO` / `-shm`-Caveat; **kein** DML gegen die Quelle — Quelle bleibt unverändert). AION liest die Daten **nicht** live, sondern über `m2_pull.db` (s. u.).
- **Typ/WAL:** SQLite, **WAL + `synchronous=FULL`** (`sild_mapper_m2.py:1122-1123`) ⇒ `m2.db-wal`/`-shm`. Hinweis: bei Langzeit-Writer liegen die Daten im `-wal` (Ops-Beobachtung `.45`: `-wal`-Wachstum, kein Checkpoint — offener Ops-Posten, RO-Vertrag unberührt).
- **Persistenz:** `/srv/sild/data/m2.db`, Host-Bind, Owner `sild:sild`.

### `m2_pull.db`  ← Pull-Contract-DB für AION
- **Rolle:** Atomar publizierter, **self-contained** Snapshot von `m2.db` als read-only Pull-Fläche; AION mountet diese **Einzeldatei `:ro`** (separater aion-api-Mount, berührt `/srv/aionprod`, nicht diese Compose — Compose Z.7).
- **Schreiber:** `sild-snapshot` (`sild_m2_snapshot.py`) via `--out /data/m2_pull.db` (Compose Z.86), Intervall 10s, `os.replace` (atomar).
- **Leser:** AION-Consumer, **read-only** (`mode=ro`, `query_only`; `immutable` nicht nötig).
- **Typ/WAL:** SQLite, **`journal_mode=delete`** — **self-contained, kein `-wal`/`-shm`** (`sild_m2_snapshot.py:14,20,77`; per `VACUUM INTO` erzeugt). Genau deshalb genügt AION ein Einzeldatei-`:ro`-Mount.
- **Persistenz:** `/srv/sild/data/m2_pull.db`, Host-Bind, Owner `sild:sild`, Perms `0644` (uid-1000/aion-lesbar).

---

## Befund-Abweichungen von der Erwartung (Befund gewinnt)

- **WAL betrifft alle drei Live-DBs**, nicht nur `m2.db`: `intake.db`, `m1.db` **und** `m2.db` laufen `WAL + synchronous=FULL` (Belege oben). Nur `m2_pull.db` ist `journal_mode=delete`.
- **Genau drei** Compose-Variablen (`SILD_UID`, `SILD_GID`, `SILD_M2_JITTER`); keine weiteren `${VAR}` in der Deploy-Compose.
- Geteilter **Host-Bind** `/srv/sild/data:/data` für alle vier Dienste (kein Named Volume).
