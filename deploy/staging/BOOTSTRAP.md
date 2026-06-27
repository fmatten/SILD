<!--
SPDX-FileCopyrightText: 2026 Friedhelm Matten / ISCaD GmbH
SPDX-License-Identifier: AGPL-3.0-only OR LicenseRef-ISCaD-Commercial
-->

# DEP-1 — Root-Bootstrap-Rezept (Friedhelm-Checkpoint)

**Box:** `aion-staging` · **Label:** DEP-1 · **Mechanismus:** A (Snapshot-Pull,
ratifiziert) · **Beleg:** `docs/dep1-wal-probe.md`, `docs/deploy-decision-sheet.md`.

Die Deploy-Instanz hat **kein passwortloses sudo**. Die folgenden Schritte sind
**irreversible Systemschritte (root)** und daher ein bewusster Friedhelm-Checkpoint
(S-0-[F]-Block). Bitte **prüfen und ausführen**; danach übernimmt die Instanz den
nicht-privilegierten Rest (Build, `up` als `sild`, Demo).

> **Schutzklausel:** SILD ausschließlich nach `/srv/sild`. Tabu = workpool/ZFS,
> `/srv/repositories`, `/media/*`, `/srv/aionprod`. Nur synthetische Daten.

## B-1 — `sild`-Systemkonto (nicht root, kein Login nötig)

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin sild
# uid/gid notieren — werden fuer die Compose-.env gebraucht:
id sild        # -> z.B. uid=997(sild) gid=997(sild)
```

## B-2 — Verzeichnislayout unter `/srv/sild` (Eigentümer `sild`)

```bash
sudo mkdir -p /srv/sild/repo /srv/sild/data/logs
sudo chown -R sild:sild /srv/sild
sudo chmod 750 /srv/sild /srv/sild/data
# Clone des SILD-Repos als sild (Account-Key reicht; RO-Deploy-Key = DEP-S4, Prod):
sudo -u sild git clone <SILD-REMOTE> /srv/sild/repo
```

## B-3 — Lesbarkeit des Snapshots für `aion-api` (uid 1000)

`aion-api` liest als **uid 1000(aion)**. Der Publisher schreibt den Snapshot mit
`0644` (welt-/gruppenlesbar) — damit kann uid 1000 lesen, **ohne** Schreibrecht.
Falls `0644` unerwünscht (strenger), stattdessen eine gemeinsame Gruppe:

```bash
# Variante "gemeinsame Gruppe" (optional, statt 0644):
sudo groupadd sild-pull
sudo usermod -aG sild-pull aion        # falls ein Host-User 'aion' (uid 1000) existiert
# dann Publisher mit --mode 0640 starten und /srv/sild/data g+rx setzen.
```

> Die Datei-Mutations-Invariante bleibt gewahrt: AION erhält **nur Leserecht**
> auf `m2_pull.db`; der `:ro`-Mount (B-5) verhindert Schreiben zusätzlich.

## B-4 — `.env` für die SILD-Compose (Instanz, nach B-1)

Die Instanz legt `deploy/staging/.env` an (kein root):

```
SILD_UID=997      # aus `id sild`
SILD_GID=997
```

## B-5 — `aion-api`-Mount (berührt `/srv/aionprod` → Koordination/Gate)

**Dieser Schritt liegt in aionprods Arbeitsgebiet (Tabu für die SILD-Instanz).**
Er gehört in die `aion-coordination` und wird von der AION-Seite ausgeführt.
Vorschlag für `docker-compose.staging.yml` des `aion-api`-Dienstes:

```yaml
    volumes:
      - /srv/sild/data/m2_pull.db:/srv/sild-pull/m2_pull.db:ro   # DEP-1 Pull-Flaeche
```

AION öffnet die Datei `file:/srv/sild-pull/m2_pull.db?mode=ro` + `PRAGMA query_only=ON`
und liest die drei Views (`v_aion_stay`, `v_aion_segment`, `v_aion_change`).
**Nur die Snapshot-Datei mounten — niemals die Live-`m2.db`** (deren Daten liegen
im `-wal`; Beleg `docs/dep1-wal-probe.md`).

---

## Danach (Instanz, nicht-privilegiert, als `sild`)

```bash
cd /srv/sild/repo/deploy/staging
# Image bauen + Kette starten (laeuft als SILD_UID/SILD_GID):
docker compose -f docker-compose.sild.yml --env-file .env up -d --build
# Demo (synthetisch) A01 -> A02 -> A03:
PULL_DB=/srv/sild/data/m2_pull.db bash demo/replay_demo.sh
```

Erwartung der Demo (in der Sandbox bereits durch die echte Kette bestätigt):
**1 Stay** `UKH|DEMO001` / `VDEMO01`, Muster A, am Ende `closed`; Lage-Segmente
**NA → IM1**; AION liest alles read-only aus `m2_pull.db`.

## Offene DEP-S4 (Prod-Vorbedingung, kein Staging-Blocker)

Account-Key → repo-gebundener **read-only Deploy-Key** vor Produktivgang
registrieren.
