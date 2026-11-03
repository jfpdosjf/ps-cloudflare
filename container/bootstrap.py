"""راه‌اندازی خودکار PasarGuard روی Cloudflare. idempotent: هر بار بوت امنه."""
import json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

BASE = "http://127.0.0.1:8000"
DATA = os.getenv("SEPNET_DATA", "/var/lib/pasarguard")
RUN = os.getenv("SEPNET_RUN", "/run/sepnet")
USER, PASS = os.environ["PANEL_USER"], os.environ["PANEL_PASS"]
TITLE = (os.getenv("CONFIG_TITLE") or "SEPNET").strip()
GB, DAY = 1024 ** 3, 86400

CORE_NAME, NODE_NAME, GROUP_NAME = "SEPNET-Core", "SEPNET-Core", "SEPNET"

# tag proto port net fingerprint name
INBOUNDS = [
    ("SP-VLESS-WS-1", "vless", 10001, "ws", "chrome", "Pro"),
    ("SP-VLESS-WS-2", "vless", 10002, "ws", "firefox", "Flash"),
    ("SP-TROJAN-WS", "trojan", 10003, "ws", "safari", "Fire"),
    ("SP-VMESS-WS", "vmess", 10004, "ws", "edge", "Diamond"),
    ("SP-VLESS-HU", "vless", 10005, "httpupgrade", "ios", "Night"),
]
EARLY = "?ed=2560"

TEMPLATES = [  # name, GB (0 = نامحدود), days
    ("10GB · 30 روز", 10, 30),
    ("30GB · 30 روز", 30, 30),
    ("50GB · 30 روز", 50, 30),
    ("100GB · 30 روز", 100, 30),
    ("نامحدود · 30 روز", 0, 30),
]

try:
    PATHS = json.load(open(f"{DATA}/paths.json"))
except Exception as e:
    print("[bootstrap] paths.json missing:", e, flush=True)
    sys.exit(1)

TOKEN = None
_G = object()


def log(*a):
    print("[bootstrap]", *a, flush=True)


# ---------------- دامنه: از env یا از بازدیدهای واقعی (هدر Worker) ----------------
DOMAIN_FILE = f"{DATA}/domain.txt"
HOST_LOG = f"{RUN}/host.log"
_DOM = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def _valid(d):
    d = (d or "").strip().lower().rstrip(".")
    return d if _DOM.match(d) else ""


def get_domain():
    env = _valid(os.getenv("PUBLIC_DOMAIN"))
    if env:
        return env
    learned = ""
    try:
        if os.path.exists(HOST_LOG) and os.path.getsize(HOST_LOG):
            with open(HOST_LOG, "r+") as f:
                lines = f.read().split()
                f.seek(0)
                f.truncate()
            for h in reversed(lines):
                d = _valid(h.split(":")[0])
                if d:
                    learned = d
                    break
    except Exception as e:
        log("domain learn:", e)
    saved = ""
    try:
        saved = _valid(open(DOMAIN_FILE).read())
    except Exception:
        pass
    if learned and learned != saved:
        open(DOMAIN_FILE, "w").write(learned)
        log("domain:", learned)
        return learned
    return saved


# ---------------- HTTP به پنل ----------------
def req(method, path, body=None, form=False, token=_G):
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    tok = TOKEN if token is _G else token
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, (json.loads(raw) if raw.strip() else None)
            except ValueError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="ignore")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, txt


def must(method, path, body=None):
    code, res = req(method, path, body)
    if code == 401:
        login()
        code, res = req(method, path, body)
    if code not in (200, 201, 204):
        raise RuntimeError(f"{method} {path} -> {code}: {res}")
    return res


def as_list(res, key):
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        return res.get(key) or []
    return []


def wait_panel():
    for _ in range(180):
        try:
            code, _ = req("GET", "/api/system")
            if code in (200, 401, 403):
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError("panel did not come up")


# ---------------- مالک پنل (کلید موقت از داخل خود پنل) ----------------
TEMP_KEY_PY = """
import asyncio
from app.db.base import GetDB
from app.db.crud.temp_key import create_temp_key
async def main():
    async with GetDB() as db:
        k = await create_temp_key(db)
        print("KEY=" + k.key)
asyncio.run(main())
"""

TOKEN_PY = """
import asyncio
from app.db.base import GetDB
from app.db.crud.admin import get_owner
from app.utils.jwt import create_admin_token
async def main():
    async with GetDB() as db:
        o = await get_owner(db)
        if o is None:
            print("NOOWNER"); return
        print("TOKEN=" + await create_admin_token(o.id, o.username))
asyncio.run(main())
"""


def _py(code):
    return subprocess.run([sys.executable, "-c", code], cwd="/code", capture_output=True, text=True, timeout=90)


def temp_key():
    out = _py(TEMP_KEY_PY)
    for line in out.stdout.splitlines():
        if line.startswith("KEY="):
            return line[4:].strip()
    raise RuntimeError(f"temp key failed: {out.stderr[-500:]}")


def owner_token():
    out = _py(TOKEN_PY)
    for line in out.stdout.splitlines():
        if line.startswith("TOKEN="):
            return line[6:].strip()
        if line.strip() == "NOOWNER":
            return None
    raise RuntimeError(f"token failed: {(out.stdout + out.stderr)[-400:]}")


def ensure_owner():
    """اولین بوت: مالک با یوزر/رمزی که Worker ساخته. بعدش دیگه بهش دست نمیزنیم."""
    if owner_token() is None:
        code, res = req("POST", "/api/setup/owner", {"key": temp_key(), "username": USER, "password": PASS}, token=None)
        if code in (200, 201):
            log("owner created:", USER)
        elif code != 409:
            raise RuntimeError(f"owner create failed {code}: {res}")


def login():
    global TOKEN
    ensure_owner()
    for _ in range(30):
        tok = owner_token()
        if tok:
            TOKEN = tok
            return
        time.sleep(3)
    raise RuntimeError("no owner token")


# ---------------- هسته Xray ----------------
def inbound(tag, proto, port, net):
    stream = {"network": net, "security": "none"}
    path = PATHS[tag]
    if net == "ws":
        stream["wsSettings"] = {"path": path, "heartbeatPeriod": 30}
    elif net == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": path}
    settings = {"clients": []}
    if proto == "vless":
        settings["decryption"] = "none"
    return {"tag": tag, "listen": "127.0.0.1", "port": port, "protocol": proto,
            "settings": settings, "streamSettings": stream,
            "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}}


CORE_CONFIG = {
    "log": {"loglevel": "warning"},
    "dns": {"servers": ["1.1.1.1", "8.8.8.8", "localhost"], "queryStrategy": "UseIPv4"},
    "inbounds": [inbound(t, p, po, n) for (t, p, po, n, _fp, _nm) in INBOUNDS],
    "outbounds": [
        {"protocol": "freedom", "tag": "DIRECT", "settings": {"domainStrategy": "UseIPv4"}},
        {"protocol": "blackhole", "tag": "BLOCK"},
    ],
    "routing": {"domainStrategy": "AsIs", "rules": [
        {"type": "field", "ip": ["geoip:private"], "outboundTag": "BLOCK"},
        {"type": "field", "protocol": ["bittorrent"], "outboundTag": "BLOCK"},
        {"type": "field", "network": "udp", "port": "443", "outboundTag": "BLOCK"},
    ]},
    "policy": {"levels": {"0": {"handshake": 8, "connIdle": 300, "uplinkOnly": 2, "downlinkOnly": 5, "bufferSize": 512}}},
}


def ensure_core():
    for c in as_list(must("GET", "/api/cores"), "cores"):
        if c.get("name") == CORE_NAME:
            if c.get("config") == CORE_CONFIG:
                log("core ok", c["id"])
                return c["id"]
            body = {"name": CORE_NAME, "config": CORE_CONFIG, "exclude_inbound_tags": [], "fallbacks_inbound_tags": []}
            code, res = req("PUT", f"/api/core/{c['id']}?restart_nodes=true", body)
            if code not in (200, 201):
                code, res = req("PUT", f"/api/core/{c['id']}?restart_nodes=false", body)
            log("core updated" if code in (200, 201) else f"core update failed {code}: {res}")
            return c["id"]
    c = must("POST", "/api/core", {"name": CORE_NAME, "config": CORE_CONFIG,
                                    "exclude_inbound_tags": [], "fallbacks_inbound_tags": []})
    log("core created", c["id"])
    return c["id"]


def ensure_node(core_id):
    body = {"name": NODE_NAME, "address": "127.0.0.1", "port": 62050, "usage_coefficient": 1,
            "connection_type": "grpc", "keep_alive": 60, "core_config_id": core_id,
            "server_ca": open(f"{DATA}/node-certs/cert.pem").read().strip(),
            "api_key": open(f"{DATA}/node_api_key").read().strip()}
    for n in as_list(must("GET", "/api/nodes"), "nodes"):
        if n.get("name") == NODE_NAME:
            if n.get("core_config_id") != core_id or n.get("server_ca", body["server_ca"]) != body["server_ca"]:
                must("PUT", f"/api/node/{n['id']}", body)
                log("node updated")
            return
    must("POST", "/api/node", body)
    log("node created")


def ensure_group():
    tags = [i[0] for i in INBOUNDS]
    for g in as_list(must("GET", "/api/groups"), "groups"):
        if g.get("name") == GROUP_NAME:
            if sorted(g.get("inbound_tags") or []) != sorted(tags):
                must("PUT", f"/api/group/{g['id']}", {"name": GROUP_NAME, "inbound_tags": tags})
            return g["id"]
    g = must("POST", "/api/group", {"name": GROUP_NAME, "inbound_tags": tags})
    log("group created")
    return g["id"]


def ensure_templates(gid):
    have = {t.get("name"): t for t in as_list(must("GET", "/api/user_templates"), "templates")}
    for name, gb, days in TEMPLATES:
        body = {"name": name, "data_limit": gb * GB, "expire_duration": days * DAY, "group_ids": [gid],
                "status": "active", "data_limit_reset_strategy": "no_reset"}
        if name not in have:
            must("POST", "/api/user_template", body)
    log("templates ready")


# ---------------- هاست‌ها (آدرس هر کانفیگ) و تنظیمات ساب ----------------
def _norm(v):
    if isinstance(v, list):
        return [str(x).lower() for x in v]
    if v is None or isinstance(v, bool):
        return v
    return str(v).lower()


def _addr(h):
    a = h.get("address")
    if isinstance(a, list):
        a = a[0] if a else ""
    return str(a or "").lower()


STATE = {}


def ensure_hosts():
    dom = get_domain()
    if not dom:
        if not STATE.get("nodom"):
            log("waiting for first visit to learn the domain (open the panel once)")
            STATE["nodom"] = True
        return
    STATE["nodom"] = False
    existing = as_list(must("GET", "/api/hosts"), "hosts")
    changed = 0
    for prio, (tag, _p, _po, _n, fp, name) in enumerate(INBOUNDS, 1):
        body = {"remark": f"{name} | {TITLE}", "allowinsecure": False, "address": [dom], "inbound_tag": tag,
                "port": 443, "sni": [dom], "host": [dom], "path": PATHS[tag] + EARLY, "security": "tls",
                "alpn": ["http/1.1"], "fingerprint": fp, "priority": prio, "is_disabled": False}
        mine = [h for h in existing if h.get("inbound_tag") == tag and _addr(h) == dom]
        if mine:
            cur = mine[0]
            if any(_norm(cur.get(k)) != _norm(v) for k, v in body.items()):
                must("PUT", f"/api/host/{cur['id']}", {**body, "id": cur["id"]})
                changed += 1
            for extra in mine[1:]:
                req("DELETE", f"/api/host/{extra['id']}")
        else:
            must("POST", "/api/host/", body)
            changed += 1
    for h in existing:  # هاست‌های دامنه‌ی قدیمی (فقط تگ‌های خودمون)
        if str(h.get("inbound_tag") or "").startswith("SP-") and _addr(h) != dom:
            req("DELETE", f"/api/host/{h['id']}")
            changed += 1
    if changed or not STATE.get("hosts"):
        log(f"{len(INBOUNDS)} configs ready on {dom}")
        STATE["hosts"] = True
    if STATE.get("settings_for") != dom:
        ensure_settings(dom)


def ensure_settings(dom):
    code, s = req("GET", "/api/settings")
    if code != 200 or not isinstance(s, dict) or "subscription" not in s:
        log("settings endpoint not as expected, skipped")
        return
    sub = s["subscription"]
    want = {"url_prefix": f"https://{dom}", "profile_title": TITLE, "update_interval": 12}
    if all(sub.get(k) == v for k, v in want.items()):
        STATE["settings_for"] = dom
        return
    sub.update(want)
    code, _ = req("PUT", "/api/settings", {"subscription": sub})
    if code in (200, 201):
        STATE["settings_for"] = dom
    log("subscription settings", "ok" if code in (200, 201) else f"skipped ({code})")


# ---------------- نگهبان: خودترمیمی ----------------
def attach_orphans(gid):
    code, res = req("GET", "/api/users?no_group=true&limit=200")
    if code == 401:
        login()
        code, res = req("GET", "/api/users?no_group=true&limit=200")
    if code != 200:
        return
    for u in as_list(res, "users"):
        if not u.get("group_ids"):
            c, r = req("PUT", f"/api/user/{u['username']}", {"group_ids": [gid]})
            log(f"user {u['username']} -> group {GROUP_NAME}" if c == 200 else f"attach failed {c}: {r}")


def heal_node(state):
    code, res = req("GET", "/api/nodes")
    if code == 401:
        login()
        code, res = req("GET", "/api/nodes")
    if code != 200:
        return
    for n in as_list(res, "nodes"):
        if n.get("name") != NODE_NAME:
            continue
        st = str(n.get("status") or "")
        if st in ("connected", "disabled"):
            state["bad"] = 0
            continue
        state["bad"] = state.get("bad", 0) + 1
        if state["bad"] >= 2:
            log(f"node status '{st}' -> reconnect")
            c, _ = req("POST", f"/api/node/{n['id']}/reconnect")
            if c not in (200, 204):
                req("POST", f"/api/core/{n.get('core_config_id')}/restart")
            state["bad"] = 0


def tune_db():
    import sqlite3
    db = f"{DATA}/db.sqlite3"
    if not os.path.exists(db):
        return
    try:
        con = sqlite3.connect(db, timeout=30)
        if con.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
            con.execute("PRAGMA journal_mode=WAL")
            log("database: WAL on")
        con.close()
    except Exception as e:
        log("db tune:", e)


def step(name, fn, *a):
    for _ in range(20):
        try:
            return fn(*a)
        except Exception as e:
            log(f"{name} retry:", e)
            time.sleep(5)
    raise RuntimeError(f"{name} failed")


def watch(gid):
    log("watcher on")
    state, i = {}, 0
    while True:
        for job, every in ((ensure_hosts, 2), (lambda: attach_orphans(gid), 1),
                           (lambda: heal_node(state), 4), (tune_db, 240)):
            if i % every == 0:
                try:
                    job()
                except Exception as e:
                    log("self-heal:", e)
        i += 1
        time.sleep(15)


def main():
    wait_panel()
    login()
    core = step("core", ensure_core)
    step("node", ensure_node, core)
    gid = step("group", ensure_group)
    step("templates", ensure_templates, gid)
    try:
        step("hosts", ensure_hosts)
    except Exception as e:
        log("hosts later:", e)
    open(f"{RUN}/ready", "w").write("1")
    log("setup done")
    watch(gid)


if __name__ == "__main__":
    main()
