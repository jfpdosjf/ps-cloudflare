#!/usr/bin/env bash
set -uo pipefail
ulimit -n 65535 2>/dev/null || ulimit -n 16384 2>/dev/null || true

DATA=/var/lib/pasarguard
RUN=/run/sepnet
mkdir -p "$DATA/node-certs" /var/lib/pg-node "$RUN"
rm -f "$RUN"/*
: > "$RUN/host.log"; chmod 666 "$RUN/host.log"

if [ -z "${SEPNET_TOKEN:-}" ]; then
  export SEPNET_TOKEN="$(python -c 'import secrets;print(secrets.token_hex(24))')"
  echo "[sepnet] warning: SEPNET_TOKEN not provided, backup endpoint is unusable"
fi
export PANEL_USER="${PANEL_USER:-owner}"
if [ -z "${PANEL_PASS:-}" ]; then
  export PANEL_PASS="Sp$(python -c 'import secrets;print(secrets.token_hex(8))')-Aa9"
  echo "[sepnet] warning: PANEL_PASS not provided, generated: $PANEL_PASS"
fi
unset SUDO_USERNAME SUDO_PASSWORD

supervise() { # supervise <name> <fn>
  local name="$1"; shift
  while true; do
    "$@" &
    echo $! > "$RUN/$name.pid"
    wait $!
    echo "[sepnet] $name stopped, starting again in 3s"
    sleep 3
  done
}

run_nginx() { exec nginx -g 'daemon off;' 2>&1; }
run_ctl()   { cd /code && exec python ctl.py 2>&1; }
run_node()  { cd /opt/pg-node && SERVICE_PORT=62050 NODE_HOST=127.0.0.1 SERVICE_PROTOCOL=grpc \
                API_KEY="$(cat $DATA/node_api_key)" \
                SSL_CERT_FILE="$DATA/node-certs/cert.pem" SSL_KEY_FILE="$DATA/node-certs/key.pem" \
                exec ./main 2>&1; }
run_panel() { cd /code && exec python main.py 2>&1; }
run_boot()  { cd /code && exec python bootstrap.py 2>&1; }

trap 'echo "[sepnet] stopping"; kill $(jobs -p) 2>/dev/null; exit 0' TERM INT

# 1) nginx + سرور کنترل فوراً بالا میان (healthcheck و ریستور بکاپ)
[ -f "$DATA/inbounds.inc" ] || : > "$DATA/inbounds.inc"
supervise nginx run_nginx &
supervise ctl run_ctl &

# 2) منتظر ریستور بکاپ از Worker (حداکثر ۱۲۰ ثانیه؛ بدون بکاپ = شروع تازه)
for _ in $(seq 1 120); do
  [ -f "$RUN/restore_done" ] && break
  sleep 1
done
[ -f "$RUN/restore_done" ] || { echo "[sepnet] no restore signal, fresh start"; : > "$RUN/restore_done"; }

# 3) کلید و گواهی نود (یک بار؛ تو بکاپ می‌مونه)
[ -f "$DATA/node_api_key" ] || python -c "import uuid;print(uuid.uuid4())" > "$DATA/node_api_key"
if [ ! -f "$DATA/node-certs/cert.pem" ]; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 3650 \
    -keyout "$DATA/node-certs/key.pem" -out "$DATA/node-certs/cert.pem" -subj "/CN=sepnet-node" \
    -addext "subjectAltName=IP:127.0.0.1,DNS:localhost" >/dev/null 2>&1 || { echo "[sepnet] cert failed"; exit 1; }
fi

# 4) مسیرهای کانفیگ + nginx
python /code/genpaths.py || exit 1
nginx -t 2>&1 || exit 1
nginx -s reload 2>&1 || true

# 5) دیتابیس + سرویس‌ها
( cd /code && python -m alembic upgrade head 2>&1 ) || echo "[sepnet] migration warning"

supervise node run_node &
supervise panel run_panel &
supervise boot run_boot &

echo "[sepnet] up"
while true; do sleep 3600 & wait $!; done
