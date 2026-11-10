# Storage management

iSeeYou stores monitoring history in a local SQLite database. The default path
is `data/isee.sqlite3`, relative to the application working directory; the
systemd user unit sets that directory to the project checkout. Set
`collection.database_path` in `config.toml` to use another path. The database
file is created with owner-only permissions.

Each collection cycle records the run result and timestamp, router resource
data, interface counters and rates, interface inventory, and configured
connectivity probe results. The connected-device inventory is different: only
the latest successful snapshot is retained, not a historical snapshot per
poll.

## Storage view

Open **Storage** in the dashboard navigation.

The storage API has no separate authentication; it inherits the dashboard's
network access controls. Keep the application bound to localhost behind the
configured authenticated reverse proxy, and do not expose its application port
directly to an untrusted network. See [DEPLOYMENT.md](DEPLOYMENT.md).

- **Database files** is the actual combined filesystem size of the SQLite
  database and any `-wal` or `-shm` sidecar files.
- **Monthly history** groups collection records by their UTC completion month.
  The byte count estimates their compact JSON representation. It is not an
  exact allocation of SQLite pages, indexes, or free space to each month.
- The current connected-device snapshot is not counted as monthly history.
- Month rows can be exported as `.jsonl.gz` archives covering that month.

Exports contain timestamped records in gzip-compressed JSON Lines, including
collection runs, interface samples and inventory, connectivity samples, and
the latest device snapshot only when its collection run falls in the selected
date range. Archives can contain network addresses, device identifiers, and
hostnames; store and transfer them as sensitive data. Automatic import or
restore from an export archive is not implemented.

## Exporting and deleting history

Use the month’s **Download .jsonl.gz** action to save an archive before cleanup.
The export API also accepts a `from` date and an inclusive `through` date; both
are interpreted as UTC dates.

The **Delete old history** control deletes collection runs completed before
midnight UTC on the selected date. The server independently rejects any cutoff
that would delete data newer than 30 days, even if a request bypasses the UI.
The date selector also limits its maximum to the protected cutoff. Deletion is
permanent; iSeeYou does not automatically export or back up data before
deleting it.

The current connected-device snapshot and its associated collection run are
preserved if that run would otherwise be deleted. After removing eligible
history, iSeeYou runs SQLite `VACUUM` to rebuild the database and reclaim
unused file space. This can take time, briefly lock the database, and require
temporary free disk space roughly comparable to the database size. Avoid
running cleanup when the host is low on disk space or under heavy collection
load.

There is no automatic retention job. Monitor database growth and export or
delete old history manually when appropriate.

## Database backup and restore

For a consistent full-database backup, stop the service before copying the
SQLite file:

```sh
systemctl --user stop isee.service
cp -a data/isee.sqlite3 "data/isee.sqlite3.backup.$(date +%Y%m%d-%H%M%S)"
systemctl --user start isee.service
```

Keep backups outside source control and restrict access because they contain
the same sensitive monitoring data as the live database. To restore a full
backup, stop iSeeYou, preserve the current database separately, copy the chosen
backup to the configured database path, and start the service. SQLite schema
migrations run on startup; keep an untouched backup until startup and health
checks succeed. Compressed JSONL exports are not a substitute for a restorable
database backup.
