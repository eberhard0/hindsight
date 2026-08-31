#!/usr/bin/env python3
"""Nightly snapshot of the Hindsight DB, keeping the 7 newest."""
import os, sqlite3, glob, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "data", "hindsight.db")
DEST_DIR = os.path.join(ROOT, "backups")
os.makedirs(DEST_DIR, exist_ok=True)

stamp = datetime.date.today().strftime("%Y%m%d")
dest = os.path.join(DEST_DIR, "hindsight-%s.db" % stamp)

src = sqlite3.connect("file:%s?mode=ro" % SRC, uri=True)
dst = sqlite3.connect(dest)
src.backup(dst)          # consistent even mid-write (WAL-safe)
dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
dst.execute("PRAGMA journal_mode=DELETE")   # single self-contained file, no -wal/-shm
dst.close(); src.close()

n = sqlite3.connect("file:%s?mode=ro" % dest, uri=True).execute("SELECT COUNT(*) FROM logs").fetchone()[0]
print("backup %s: %d logs" % (dest, n))

for junk in glob.glob(os.path.join(DEST_DIR, "*.db-wal")) + glob.glob(os.path.join(DEST_DIR, "*.db-shm")):
    os.remove(junk)
for old in sorted(glob.glob(os.path.join(DEST_DIR, "hindsight-*.db")))[:-7]:
    os.remove(old)
    print("pruned", old)
