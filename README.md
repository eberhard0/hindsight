# Hindsight

A self-hosted "when did I last do that?" tracker. Log recurring life things — haircuts, gas fill-ups, oil changes, AC cleanings — with one tap, and see how many days it's been, your full history with gaps, and your real average cadence.

Built as a single-file web app with a tiny Python/SQLite backend. No frameworks, no build step, no dependencies beyond the Python standard library.

## Features

- **One-tap logging** — type a name once; after that, "Log again" stamps the current date and time.
- **History per thing** — every occurrence kept, newest first, with `+42d` gap badges and average cadence ("30 logs · averages every 66 days").
- **Backdating and notes** — fix the date/time when you forgot to log, annotate entries (price, place, odometer).
- **Optional reminders** — repeat every N days/weeks/months, or a one-off target date; overdue/due-soon states are visual (color + pill).
- **Sync** — the server's SQLite database is the source of truth; browser localStorage is an offline cache. Works offline, merges back when reachable, dedupes safely.
- **CSV import/export** — round-trips the export format of the classic Hindsight iOS app (`Category,Event,Occurrence,Note`).
- Light/dark theme, mobile-friendly, zero tracking.

## Run it

```sh
python3 server.py
# serves http://127.0.0.1:8095
```

Environment overrides: `HINDSIGHT_PORT`, `HINDSIGHT_BIND`, `HINDSIGHT_DB`.

The database is created at `data/hindsight.db` on first start. If a `seed.csv` (Hindsight-format export) sits next to `server.py`, an empty database is seeded from it once.

### As a service (systemd)

```ini
[Unit]
Description=Hindsight time tracker
After=network.target

[Service]
User=youruser
ExecStart=/usr/bin/python3 /path/to/hindsight/server.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## API

- `GET /api/items` → `{"items": [...]}` — full state
- `PUT /api/items` — replace full state (JSON array)

Item shape:

```json
{
  "id": "abc123", "name": "Haircut", "icon": "✂️", "cat": "Health",
  "every": 42, "dueOn": null,
  "log": [{ "id": "def456", "ts": 1755300000000, "note": "" }]
}
```

`every` (days) and `dueOn` (epoch ms) are the two mutually exclusive reminder modes; both `null` means just count days.

## Caveats

- **No authentication.** Anyone who can reach the server can read and write the data. Run it on localhost, behind a VPN/tunnel with access control, or add auth before exposing it.
- Sync is full-state last-write-wins with a client-side union merge on first contact and after offline periods — fine for personal use, not designed for heavy concurrent editing.
- Reminders are visual only (no push notifications).

## Why

Proof-of-concept for the interaction model of a planned Flutter app; the SQLite schema (`things` + `logs`) is designed to port straight to Drift/sqflite.
