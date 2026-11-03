# PasarGuard panel + Xray node + nginx داخل یک کانتینر (پورت 8080)
FROM pasarguard/node:latest AS node
FROM pasarguard/panel:latest

RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx openssl ca-certificates curl \
 && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default

COPY --from=node /app/main /opt/pg-node/main
COPY --from=node /usr/local/bin/xray /usr/local/bin/xray
COPY --from=node /usr/local/share/xray /usr/local/share/xray

COPY nginx.conf /etc/nginx/nginx.conf
COPY wait.html /etc/nginx/sepnet/wait.html
COPY entrypoint.sh /entrypoint.sh
COPY bootstrap.py genpaths.py ctl.py /code/

RUN sed -i 's/\r$//' /entrypoint.sh /code/bootstrap.py /code/genpaths.py /code/ctl.py /etc/nginx/nginx.conf \
 && chmod +x /entrypoint.sh /opt/pg-node/main /usr/local/bin/xray

ENV PORT=8080 \
    UVICORN_HOST=127.0.0.1 \
    UVICORN_PORT=8000 \
    UVICORN_PROXY_HEADERS=True \
    UVICORN_FORWARDED_ALLOW_IPS=127.0.0.1 \
    SQLALCHEMY_DATABASE_URL=sqlite+aiosqlite:////var/lib/pasarguard/db.sqlite3 \
    SUBSCRIPTION_PATH=sub \
    XRAY_EXECUTABLE_PATH=/usr/local/bin/xray \
    XRAY_ASSETS_PATH=/usr/local/share/xray \
    SEPNET_DATA=/var/lib/pasarguard \
    SEPNET_RUN=/run/sepnet

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
