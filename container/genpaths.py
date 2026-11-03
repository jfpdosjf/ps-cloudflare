"""مسیرهای تصادفی کانفیگ‌ها: یک بار ساخته میشن و تو بکاپ می‌مونن (لینک کاربرها عوض نمیشه)."""
import json, os, secrets

DATA = os.getenv("SEPNET_DATA", "/var/lib/pasarguard")

# tag -> پورت داخلی Xray
PORTS = {
    "SP-VLESS-WS-1": 10001,
    "SP-VLESS-WS-2": 10002,
    "SP-TROJAN-WS": 10003,
    "SP-VMESS-WS": 10004,
    "SP-VLESS-HU": 10005,
}

PJ = f"{DATA}/paths.json"
try:
    with open(PJ) as f:
        paths = json.load(f)
except Exception:
    paths = {}

changed = False
for tag in PORTS:
    if tag not in paths:
        paths[tag] = "/" + secrets.token_hex(5) + "/"
        changed = True
if changed or not os.path.exists(PJ):
    with open(PJ, "w") as f:
        json.dump(paths, f, indent=1)

BLOCK = """location ^~ %(path)s {
  proxy_pass http://127.0.0.1:%(port)d;
  proxy_http_version 1.1;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_set_header Host $host;
  proxy_set_header X-Real-IP $remote_addr;
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
  proxy_buffering off;
}
"""

with open(f"{DATA}/inbounds.inc.tmp", "w") as f:
    for tag, port in PORTS.items():
        f.write(BLOCK % {"path": paths[tag], "port": port})
os.replace(f"{DATA}/inbounds.inc.tmp", f"{DATA}/inbounds.inc")
print("[genpaths] ok:", len(PORTS), "paths", flush=True)
