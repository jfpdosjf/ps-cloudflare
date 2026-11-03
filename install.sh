#!/usr/bin/env bash
# نصب آسان: فقط توکن و Account ID رو بده، بقیه‌ی کارها خودکاره.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\n\033[1;31mخطا:\033[0m %s\n' "$*" >&2; exit 1; }

command -v node   >/dev/null || die "Node.js نسخه‌ی ۲۰ یا بالاتر لازمه: https://nodejs.org"
command -v docker >/dev/null || die "Docker لازمه: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1  || die "Docker نصبه ولی روشن نیست. روشنش کن و دوباره بزن."
command -v curl   >/dev/null || die "curl لازمه."
[ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ] || die "نسخه‌ی Node باید ۲۰ یا بالاتر باشه."

cat <<'EOF'

توکن: داشبورد Cloudflare ← My Profile ← API Tokens ← Create Token
      قالب «Edit Cloudflare Workers» رو بزن و بعد دسترسی
      Account ← Workers R2 Storage ← Edit رو هم اضافه کن.
Account ID: صفحه‌ی Workers & Pages، سمت راست.
EOF

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  read -r -s -p $'\nAPI Token (موقع تایپ نشون داده نمیشه): ' CLOUDFLARE_API_TOKEN; echo
fi
if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  read -r -p "Account ID: " CLOUDFLARE_ACCOUNT_ID
fi
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

say "بررسی توکن"
VERIFY="$(curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" https://api.cloudflare.com/client/v4/user/tokens/verify || true)"
echo "$VERIFY" | grep -q '"success":true' || die "توکن معتبر نیست یا اینترنت قطعه."

say "نصب وابستگی‌ها"
npm install --no-audit --no-fund

say "ساخت فضای بکاپ (R2)"
npx wrangler r2 bucket create sepnet-backup 2>&1 | grep -v -i "already exists" || true

say "ساخت ایمیج و دیپلوی (بار اول چند دقیقه)"
LOG="$(mktemp)"
npx wrangler deploy 2>&1 | tee "$LOG"
URL="$(grep -Eo 'https://[A-Za-z0-9.-]+\.workers\.dev' "$LOG" | head -1 || true)"
[ -n "$URL" ] || die "دیپلوی تموم شد ولی آدرس پیدا نشد. از داشبورد Workers آدرسش رو بردار."

say "بیدار کردن پنل و ساخت یوزر/رمز"
curl -s -o /dev/null "$URL/helpsep/status" || true
curl -s -o /dev/null --max-time 20 "$URL/dashboard/" || true   # کانتینر رو استارت می‌کنه و دامنه رو یاد میده

CREDS=""
for _ in $(seq 1 10); do
  CREDS="$(npx wrangler r2 object get sepnet-backup/meta/config.json --remote --pipe 2>/dev/null || true)"
  echo "$CREDS" | grep -q '"pass"' && break
  sleep 3
done
USER_="$(echo "$CREDS" | sed -n 's/.*"user": *"\([^"]*\)".*/\1/p')"
PASS_="$(echo "$CREDS" | sed -n 's/.*"pass": *"\([^"]*\)".*/\1/p')"

cat <<EOF

✓ نصب تموم شد.

  راهنما:   $URL/helpsep
  پنل:      $URL/dashboard/
  یوزر:     ${USER_:-(با npm run creds ببین)}
  رمز:      ${PASS_:-(با npm run creds ببین)}

اولین بالا اومدن کانتینر تا ۲ دقیقه طول می‌کشه؛ اگه صفحه‌ی «در حال آماده‌سازی» اومد صبر کن.
رمز رو بعد از ورود از داخل پنل عوض کن.
EOF
