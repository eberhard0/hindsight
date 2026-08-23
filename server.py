#!/usr/bin/env python3
"""Hindsight time tracker: serves the app page and a JSON API backed by SQLite.

Routes:
  GET  /            -> index.html
  GET  /api/items   -> {"items": [...]}   full state
  PUT  /api/items   -> replace full state (body: JSON array of things)

Everything else is 404 — the SQLite file and seed.csv are never served.
"""
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("HINDSIGHT_DB", os.path.join(ROOT, "data", "hindsight.db"))
PORT = int(os.environ.get("HINDSIGHT_PORT", "8095"))
BIND = os.environ.get("HINDSIGHT_BIND", "127.0.0.1")
MAX_BODY = 4 * 1024 * 1024

ICON_MAP = [
    (r"haircut|barber|hair", "✂️"), (r"battery", "\U0001f50b"),
    (r"freon|^ac |ac clean|ac top", "❄️"), (r"genset", "⚡"),
    (r"tennis", "\U0001f3be"), (r"sheet", "\U0001f6cf️"), (r"service|wax", "\U0001f527"),
    (r"gas|fuel|petrol|fill up", "⛽"), (r"oil", "\U0001f6e2️"),
    (r"dentist|teeth|tooth", "\U0001f9b7"), (r"doctor|checkup|clinic", "\U0001fa7a"),
    (r"gym|workout|run|exercise", "\U0001f3cb️"), (r"tire|tyre", "\U0001f6de"),
    (r"laundry", "\U0001f9fa"), (r"clean", "\U0001f9f9"), (r"plant|water", "\U0001fab4"),
    (r"filter", "\U0001f32c️"), (r"vitamin|pill|med", "\U0001f48a"),
    (r"call|phone", "\U0001f4de"), (r"bill|pay|rent", "\U0001f4b3"),
    (r"shave|beard", "\U0001fa92"), (r"nail", "\U0001f485"),
    (r"eye|glasses|lens", "\U0001f453"), (r"backup", "\U0001f4be"),
    (r"book|read", "\U0001f4d6"), (r"shop|grocer", "\U0001f6d2"),
]


def guess_icon(name):
    n = name.lower()
    for pat, ico in ICON_MAP:
        if re.search(pat, n):
            return ico
    return "•"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS things(
          id    TEXT PRIMARY KEY,
          name  TEXT NOT NULL,
          icon  TEXT,
          cat   TEXT,
          every INTEGER,
          dueOn INTEGER
        );
        CREATE TABLE IF NOT EXISTS logs(
          id       TEXT PRIMARY KEY,
          thing_id TEXT NOT NULL REFERENCES things(id) ON DELETE CASCADE,
          ts       INTEGER NOT NULL,
          note     TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_logs_thing ON logs(thing_id, ts DESC);
        """
    )
    conn.commit()
    empty = conn.execute("SELECT COUNT(*) FROM things").fetchone()[0] == 0
    seed = os.path.join(ROOT, "seed.csv")
    if empty and os.path.exists(seed):
        with open(seed, encoding="utf-8") as f:
            n = seed_from_csv(conn, f.read())
        print("seeded database from seed.csv: %d log entries" % n)
    conn.close()


def seed_from_csv(conn, text):
    import csv as csvmod
    import io

    rows = list(csvmod.reader(io.StringIO(text)))
    if rows and rows[0] and "category" in (rows[0][0] or "").lower():
        rows = rows[1:]
    things, count = {}, 0
    for row in rows:
        if len(row) < 3:
            continue
        cat, name, occ = row[0].strip(), row[1].strip(), row[2].strip()
        note = row[3].strip() if len(row) > 3 else ""
        if not name or not occ:
            continue
        ts = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                ts = int(datetime.strptime(occ[: len(fmt) + 2], fmt).timestamp() * 1000)
                break
            except ValueError:
                pass
        if ts is None:
            continue
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        t = things.setdefault(
            key,
            {"id": uuid.uuid4().hex[:12], "name": name, "icon": guess_icon(name),
             "cat": cat or None, "every": None, "dueOn": None, "log": []},
        )
        t["log"].append({"id": uuid.uuid4().hex[:12], "ts": ts, "note": note})
        count += 1
    write_items(conn, list(things.values()))
    return count


def write_items(conn, items):
    with conn:
        conn.execute("DELETE FROM logs")
        conn.execute("DELETE FROM things")
        for it in items:
            conn.execute(
                "INSERT INTO things(id,name,icon,cat,every,dueOn) VALUES(?,?,?,?,?,?)",
                (str(it["id"]), str(it["name"]), it.get("icon"), it.get("cat"),
                 it.get("every"), it.get("dueOn")),
            )
            for e in it.get("log", []):
                conn.execute(
                    "INSERT INTO logs(id,thing_id,ts,note) VALUES(?,?,?,?)",
                    (str(e["id"]), str(it["id"]), int(e["ts"]), str(e.get("note") or "")),
                )


def read_items(conn):
    items = []
    for tid, name, icon, cat, every, due in conn.execute(
        "SELECT id,name,icon,cat,every,dueOn FROM things ORDER BY name"
    ):
        log = [
            {"id": lid, "ts": ts, "note": note}
            for lid, ts, note in conn.execute(
                "SELECT id,ts,note FROM logs WHERE thing_id=? ORDER BY ts DESC", (tid,)
            )
        ]
        items.append({"id": tid, "name": name, "icon": icon, "cat": cat,
                      "every": every, "dueOn": due, "log": log})
    return items


def validate(items):
    if not isinstance(items, list) or len(items) > 5000:
        return False
    for it in items:
        if not isinstance(it, dict) or not it.get("id") or not it.get("name"):
            return False
        if not isinstance(it.get("log", []), list) or len(it.get("log", [])) > 100000:
            return False
        for e in it.get("log", []):
            if not isinstance(e, dict) or not e.get("id") or not isinstance(e.get("ts"), (int, float)):
                return False
    return True


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=ROOT, **kw)

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/items":
            conn = connect()
            try:
                return self._json(200, {"items": read_items(conn)})
            finally:
                conn.close()
        if path in ("/", "/index.html"):
            return super().do_GET()
        self.send_error(404)

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/items":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_BODY:
                return self._json(413, {"error": "body too large or missing"})
            items = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        if not validate(items):
            return self._json(400, {"error": "invalid shape"})
        conn = connect()
        try:
            write_items(conn, items)
            n = conn.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
            return self._json(200, {"ok": True, "logs": n})
        finally:
            conn.close()

    def end_headers(self):
        # index.html must never be cached stale — updates ship instantly
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # keep the journal quiet; errors still surface via send_error


if __name__ == "__main__":
    init_db()
    print("hindsight server on %s:%d, db=%s" % (BIND, PORT, DB_PATH))
    ThreadingHTTPServer((BIND, PORT), Handler).serve_forever()
