# Backup and restore

## Scope

`scripts/backup-config.sh` backs up **Vigilience only**: the Home Assistant
config volume (users, integrations, dashboards state, automations made in
the UI, and the history database via SQLite's online backup API).

It does **not** back up Immich photos/videos or Plex media. Those currently
exist on a single USB drive with no second copy. That is the largest data
risk on the server and is shown permanently on the dashboard.

## Backing up

```bash
cd ~/vigilience && ./scripts/backup-config.sh
```

- Output: `~/vigilience-backups/vigilience-config-<timestamp>-<commit>.tar.gz` (mode 600).
- Keeps the 14 newest archives.
- Updates the *Backups* badge on the dashboard (last backup time).
- `deploy.sh` takes one automatically before every update.

Optional daily backup (user crontab, no sudo):

```bash
crontab -e
# 03:30 every day
30 3 * * * cd $HOME/vigilience && ./scripts/backup-config.sh >> $HOME/vigilience-backups/backup.log 2>&1
```

Archives are on the same machine. Copy `~/vigilience-backups/` to another
device (e.g. the Mac) periodically:

```bash
rsync -av <user>@<server-ip>:vigilience-backups/ ~/Backups/vigilience/
```

## Restoring

```bash
./scripts/restore-config.sh ~/vigilience-backups/<archive>.tar.gz
```

Takes a safety backup of the current state first, stops Home Assistant,
replaces the volume contents, starts it again. Then run `./scripts/verify.sh`.

## Restore test

Run after any change to the backup scripts:

1. `./scripts/backup-config.sh`
2. Change something harmless in the UI (e.g. the CPU temperature threshold).
3. `./scripts/restore-config.sh <the archive from step 1> --yes`
4. Log in; the threshold is back to its previous value and history is intact.
