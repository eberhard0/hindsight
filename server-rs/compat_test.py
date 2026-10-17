#!/usr/bin/env python3
"""Runs server.py and the Rust binary side by side and checks they answer alike.

Usage: compat_test.py <repo root> <path to rust binary>
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO, BIN = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
failures = []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_root(seed=None):
    d = tempfile.mkdtemp()
    shutil.copy(os.path.join(REPO, "server.py"), d)
    shutil.copy(os.path.join(REPO, "index.html"), d)
    if seed:
        with open(os.path.join(d, "seed.csv"), "w", encoding="utf-8") as f:
            f.write(seed)
    return d


def start(kind, root, db=None):
    port = free_port()
    env = dict(os.environ, HINDSIGHT_PORT=str(port), HINDSIGHT_ROOT=root, TZ="Asia/Jakarta")
    if db:
        env["HINDSIGHT_DB"] = db
    cmd = [sys.executable, os.path.join(root, "server.py")] if kind == "py" else [BIN]
    proc = subprocess.Popen(cmd, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc, "http://127.0.0.1:%d" % port
        except OSError:
            time.sleep(0.1)
    proc.kill()
    raise SystemExit("%s server did not start:\n%s" % (kind, proc.stdout.read()))


def call(base, method, path, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        failures.append(name)
        if detail:
            print("     " + str(detail)[:600])


def same(name, py, rs, key=lambda x: x):
    check(name, key(py) == key(rs), "python=%r\nrust=%r" % (key(py), key(rs)))


def as_json(resp):
    return resp[0], json.loads(resp[2]) if resp[2] else None


PAYLOAD = [
    {"id": "a1", "name": "Haircut ✂️", "icon": "✂️", "cat": "Personal", "every": 30, "dueOn": None,
     "deleted": None, "log": [{"id": "l1", "ts": 1700000000000, "note": "short"},
                              {"id": "l2", "ts": 1710000000123.9, "note": None}]},
    {"id": 42, "name": "Battery", "icon": None, "cat": None, "every": None, "dueOn": 1720000000000,
     "deleted": 1730000000000, "log": []},
    {"id": "z9", "name": "Água & 日本", "log": [{"id": "l3", "ts": 5}]},
]

BAD = {
    "not a list": {"id": "x"},
    "missing name": [{"id": "x", "log": []}],
    "empty id": [{"id": "", "name": "n"}],
    "log not list": [{"id": "x", "name": "n", "log": "nope"}],
    "log null": [{"id": "x", "name": "n", "log": None}],
    "ts string": [{"id": "x", "name": "n", "log": [{"id": "e", "ts": "1"}]}],
    "log entry no id": [{"id": "x", "name": "n", "log": [{"ts": 1}]}],
}

roots = [make_root(), make_root()]
(py, pyu), (rs, rsu) = start("py", roots[0]), start("rs", roots[1])
try:
    same("GET / serves index.html", call(pyu, "GET", "/")[2], call(rsu, "GET", "/")[2])
    same("GET /index.html", call(pyu, "GET", "/index.html")[0], call(rsu, "GET", "/index.html")[0])
    for path in ("/server.py", "/data/hindsight.db", "/seed.csv", "/api", "/api/items/x"):
        same("404 for " + path, call(pyu, "GET", path)[0], call(rsu, "GET", path)[0])
    same("empty database", as_json(call(pyu, "GET", "/api/items")), as_json(call(rsu, "GET", "/api/items")))
    same("PUT valid payload", as_json(call(pyu, "PUT", "/api/items", PAYLOAD)),
         as_json(call(rsu, "PUT", "/api/items", PAYLOAD)))
    same("GET after PUT", as_json(call(pyu, "GET", "/api/items")), as_json(call(rsu, "GET", "/api/items")))
    for name, body in BAD.items():
        same("rejects " + name, as_json(call(pyu, "PUT", "/api/items", body)),
             as_json(call(rsu, "PUT", "/api/items", body)))
    same("rejects invalid JSON", as_json(call(pyu, "PUT", "/api/items", raw=b"{nope")),
         as_json(call(rsu, "PUT", "/api/items", raw=b"{nope")))
    same("rejects empty body", call(pyu, "PUT", "/api/items", raw=b"")[0], call(rsu, "PUT", "/api/items", raw=b"")[0])
    same("bad PUT leaves data alone", as_json(call(pyu, "GET", "/api/items")), as_json(call(rsu, "GET", "/api/items")))

    hdrs = ("Access-Control-Allow-Origin", "Access-Control-Allow-Methods", "Access-Control-Allow-Headers",
            "Access-Control-Max-Age", "Vary")
    pick = lambda r: (r[0], {h.lower(): v for h, v in r[1].items() if h in hdrs})
    for origin in ("https://localhost", "capacitor://localhost", "https://evil.example", None):
        h = {"Origin": origin} if origin else {}
        same("OPTIONS preflight, origin=%s" % origin, pick(call(pyu, "OPTIONS", "/api/items", headers=h)),
             pick(call(rsu, "OPTIONS", "/api/items", headers=h)))
        same("GET CORS, origin=%s" % origin, pick(call(pyu, "GET", "/api/items", headers=h)),
             pick(call(rsu, "GET", "/api/items", headers=h)))
    cache = lambda r: r[1].get("Cache-Control")
    same("API is no-store", cache(call(pyu, "GET", "/api/items")), cache(call(rsu, "GET", "/api/items")))
    same("page is no-cache", cache(call(pyu, "GET", "/")), cache(call(rsu, "GET", "/")))
finally:
    py.terminate(); rs.terminate(); py.wait(); rs.wait()

# Each server reads the other's database file.
py_db = os.path.join(roots[0], "data", "hindsight.db")
rs_db = os.path.join(roots[1], "data", "hindsight.db")
(p1, u1) = start("rs", roots[1], db=py_db)
(p2, u2) = start("py", roots[0], db=rs_db)
try:
    same("Rust reads Python's database, Python reads Rust's",
         as_json(call(u1, "GET", "/api/items")), as_json(call(u2, "GET", "/api/items")))
finally:
    p1.terminate(); p2.terminate(); p1.wait(); p2.wait()

# First-start seeding from a Hindsight iOS CSV export.
SEED = ("Category,Event,Occurrence,Note\n"
        "Car,Oil change,2024-01-05 08:30:00,\"5W-30, full synthetic\"\n"
        "Car,Oil Change,2024-06-01 09:00,\n"
        "Health,Dentist,2024-02-10 10:15:00,cleaning\n"
        "Bad,,2024-02-10 10:15:00,\n"
        "Bad,Broken date,yesterday,\n")
roots = [make_root(SEED), make_root(SEED)]
(py, pyu), (rs, rsu) = start("py", roots[0]), start("rs", roots[1])
try:
    norm = lambda r: sorted(
        (i["name"], i["icon"], i["cat"], [(e["ts"], e["note"]) for e in i["log"]])
        for i in json.loads(r[2])["items"])
    same("seed.csv import", call(pyu, "GET", "/api/items"), call(rsu, "GET", "/api/items"), key=norm)
finally:
    py.terminate(); rs.terminate(); py.wait(); rs.wait()

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
