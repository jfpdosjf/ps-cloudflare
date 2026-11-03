"""سرور کنترل داخلی (127.0.0.1:8081): بکاپ و ریستور. فقط Worker با توکن بهش دسترسی داره."""
import gzip, hashlib, hmac, io, os, shutil, sqlite3, tarfile, tempfile, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DATA = os.getenv("SEPNET_DATA", "/var/lib/pasarguard")
RUN = os.getenv("SEPNET_RUN", "/run/sepnet")
TOKEN = os.environ["SEPNET_TOKEN"]
DONE = f"{RUN}/restore_done"
LOCK = threading.Lock()


def log(*a):
    print("[ctl]", *a, flush=True)


def make_archive():
    """یک tar.gz پایدار (بدون زمان) از دیتا؛ دیتابیس با backup API اسنپ‌شات میشه."""
    tmp = tempfile.mkdtemp()
    try:
        snap = os.path.join(tmp, "db.sqlite3")
        db = os.path.join(DATA, "db.sqlite3")
        if os.path.exists(db):
            src = sqlite3.connect(db, timeout=30)
            dst = sqlite3.connect(snap)
            src.backup(dst)
            dst.close()
            src.close()

        entries = []
        if os.path.exists(snap):
            entries.append((snap, "db.sqlite3"))
        for root, _dirs, files in os.walk(DATA):
            for name in files:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, DATA)
                base = os.path.basename(rel)
                if base.startswith("db.sqlite3") or base.endswith((".log", ".tmp")):
                    continue
                entries.append((full, rel))
        entries.sort(key=lambda e: e[1])

        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w") as t:
            for full, rel in entries:
                ti = t.gettarinfo(full, arcname=rel)
                ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = 0, 0, 0, "", ""
                with open(full, "rb") as fh:
                    t.addfile(ti, fh)
        data = gzip.compress(raw.getvalue(), mtime=0)
        return data, hashlib.sha256(data).hexdigest()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restore(blob):
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as t:
        for m in t.getmembers():
            name = os.path.normpath(m.name)
            if not m.isfile() or name.startswith(("/", "..")) or ".." in name.split(os.sep):
                raise ValueError(f"unsafe member: {m.name}")
        for stale in ("db.sqlite3", "db.sqlite3-wal", "db.sqlite3-shm"):
            try:
                os.remove(os.path.join(DATA, stale))
            except FileNotFoundError:
                pass
        t.extractall(DATA)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ok(self):
        return hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {TOKEN}")

    def _send(self, code, body=b"", ctype="text/plain", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._ok():
            return self._send(403, b"forbidden")
        if self.path.split("?")[0] == "/_sepnet/backup":
            if not os.path.exists(DONE):  # قبل از ریستور بکاپ نگیر، بکاپ سالم رو خراب می‌کنه
                return self._send(425, b"restore pending")
            with LOCK:
                try:
                    data, sha = make_archive()
                except Exception as e:
                    log("backup failed:", e)
                    return self._send(500, b"backup failed")
            return self._send(200, data, "application/gzip", {"x-sha": sha})
        self._send(404, b"not found")

    def do_POST(self):
        if not self._ok():
            return self._send(403, b"forbidden")
        if self.path.split("?")[0] != "/_sepnet/restore":
            return self._send(404, b"not found")
        if os.path.exists(DONE):
            return self._send(409, b"already restored")
        n = int(self.headers.get("Content-Length") or 0)
        blob = self.rfile.read(n) if n else b""
        try:
            if blob:
                restore(blob)
                log("restored", len(blob), "bytes")
            else:
                log("no backup, fresh start")
        except Exception as e:
            log("restore failed:", e)  # شروع تازه بهتر از گیر کردنه
        open(DONE, "w").write("1")
        self._send(200, b"ok")


if __name__ == "__main__":
    os.makedirs(RUN, exist_ok=True)
    ThreadingHTTPServer(("127.0.0.1", 8081), H).serve_forever()
