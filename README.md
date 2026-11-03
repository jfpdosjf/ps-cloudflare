# SEPNET روی Cloudflare

PasarGuard + Xray + nginx داخل Cloudflare Containers، با Worker جلوش.
نصب کامل و مرحله‌به‌مرحله بعد از دیپلوی روی `/helpsep` هست.

## نصب سریع

```bash
./install.sh
```

توکن و Account ID رو می‌پرسه و بقیه‌ی کارها (بررسی توکن، باکت بکاپ، ایمیج، دیپلوی، گرفتن یوزر/رمز) خودکاره.
برای آپدیت‌های بعدی: `./deploy.sh`

یا ریپو رو Fork کن، دو Secret به اسم `CLOUDFLARE_API_TOKEN` و `CLOUDFLARE_ACCOUNT_ID` بذار و Push بزن.

بعد از دیپلوی:

| آدرس | چیه |
|---|---|
| `/helpsep` | راهنمای نصب و استفاده |
| `/dashboard/` | پنل مدیریت |
| `npm run creds` | یوزر و رمز مالک |

## ساختار

```
src/index.js          Worker: مسیریابی، /helpsep، بکاپ هر دقیقه، ریستور موقع بالا اومدن
src/helpsep.html      صفحه‌ی راهنما
container/            ایمیج: nginx + پنل + نود Xray
  bootstrap.py        راه‌اندازی خودکار (مالک، هسته، گروه، کانفیگ‌ها، ساب)
  ctl.py              بکاپ/ریستور داخلی (فقط با توکن Worker)
  genpaths.py         مسیرهای تصادفی کانفیگ‌ها
wrangler.jsonc        کانتینر + Durable Object + R2 + cron
```

## متغیرهای اختیاری (wrangler secret / vars)

`PANEL_USER`, `PANEL_PASS` (به‌جای رمز خودکار)، `CONFIG_TITLE`، `PUBLIC_DOMAIN`
