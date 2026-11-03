#!/usr/bin/env bash
# نصب/آپدیت کامل با یک دستور
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mخطا:\033[0m %s\n' "$*" >&2; exit 1; }

command -v node   >/dev/null || die "Node.js نسخه‌ی ۲۰ یا بالاتر لازمه: https://nodejs.org"
command -v docker >/dev/null || die "Docker لازمه (wrangler باهاش ایمیج رو می‌سازه): https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1  || die "Docker نصبه ولی روشن نیست. روشنش کن و دوباره بزن."

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
[ "$NODE_MAJOR" -ge 20 ] || die "نسخه‌ی Node باید ۲۰ یا بالاتر باشه (الان $NODE_MAJOR)."

say "نصب وابستگی‌ها"
npm install --no-audit --no-fund

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  if ! npx wrangler whoami >/dev/null 2>&1; then
    say "ورود به Cloudflare (مرورگر باز میشه)"
    npx wrangler login
  fi
fi

say "ساخت فضای بکاپ (R2)"
npx wrangler r2 bucket create sepnet-backup 2>&1 | grep -v -i "already exists" || true

say "ساخت ایمیج و دیپلوی (بار اول چند دقیقه طول می‌کشه)"
npx wrangler deploy

cat <<'EOF'

✓ دیپلوی تموم شد.

  راهنما:        <آدرس-بالا>/helpsep
  پنل:           <آدرس-بالا>/dashboard/
  یوزر و رمز:    npm run creds

اولین بالا اومدن کانتینر تا ۲ دقیقه طول می‌کشه.
EOF
