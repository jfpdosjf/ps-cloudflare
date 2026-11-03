import { Container, getContainer } from "@cloudflare/containers";
import helpHtml from "./helpsep.html";

const CONTAINER_NAME = "main";
const PORT = 8080;

const hex = (n) =>
  [...crypto.getRandomValues(new Uint8Array(n))].map((b) => b.toString(16).padStart(2, "0")).join("");

// ---------- تنظیمات اولیه: یک بار ساخته میشه و تو R2 میمونه ----------
async function loadConfig(env) {
  const obj = await env.BACKUP.get("meta/config.json");
  let cfg = obj ? await obj.json() : null;
  if (!cfg) {
    cfg = { token: hex(24), user: "owner", pass: "Sp" + hex(8) + "-Aa9" };
    await env.BACKUP.put("meta/config.json", JSON.stringify(cfg, null, 2));
  }
  if (env.PANEL_USER) cfg.user = env.PANEL_USER;
  if (env.PANEL_PASS) cfg.pass = env.PANEL_PASS;
  return cfg;
}

// ---------- کانتینر: PasarGuard + Xray + nginx ----------
export class Panel extends Container {
  defaultPort = PORT;
  sleepAfter = "2h";
  enableInternet = true;

  constructor(ctx, env) {
    super(ctx, env);
    this.lastHash = "";
    ctx.blockConcurrencyWhile(async () => {
      this.cfg = await loadConfig(env);
      this.envVars = {
        SEPNET_TOKEN: this.cfg.token,
        PANEL_USER: this.cfg.user,
        PANEL_PASS: this.cfg.pass,
        CONFIG_TITLE: env.CONFIG_TITLE || "SEPNET",
        PUBLIC_DOMAIN: env.PUBLIC_DOMAIN || "",
      };
    });
  }

  auth() {
    return { authorization: `Bearer ${this.cfg.token}` };
  }

  // هر بار که کانتینر بالا میاد، آخرین بکاپ رو بهش میدیم (اگه نباشه، شروع تازه)
  async onStart() {
    try {
      const obj = await this.env.BACKUP.get("data.tgz");
      const body = obj ? await obj.arrayBuffer() : new ArrayBuffer(0);
      const res = await this.containerFetch(
        new Request("http://container/_sepnet/restore", { method: "POST", headers: this.auth(), body }),
        PORT,
      );
      this.lastHash = "";
      console.log("restore:", res.status, obj ? `${body.byteLength} bytes` : "no backup yet");
    } catch (e) {
      console.error("restore failed:", String(e));
    }
  }

  // RPC: از Worker صدا زده میشه (cron هر دقیقه)
  async tick() {
    await this.startAndWaitForPorts({ ports: [PORT] });
    const res = await this.containerFetch(
      new Request("http://container/_sepnet/backup", { headers: this.auth() }),
      PORT,
    );
    if (!res.ok) return { ok: false, status: res.status };
    const sha = res.headers.get("x-sha") || "";
    if (sha && sha === this.lastHash) return { ok: true, skipped: true };
    const buf = await res.arrayBuffer();
    if (buf.byteLength < 100) return { ok: false, reason: "empty archive" };
    await this.env.BACKUP.put("data.tgz", buf);
    this.lastHash = sha;
    return { ok: true, bytes: buf.byteLength };
  }

  async status() {
    return { running: Boolean(this.ctx.container?.running) };
  }
}

// ---------- Worker ----------
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    // صفحه‌ی راهنما
    if (path === "/helpsep" || path === "/helpsep/") {
      return new Response(helpHtml.replaceAll("__ORIGIN__", url.origin), {
        headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" },
      });
    }
    if (path === "/helpsep/status") {
      const s = await getContainer(env.PANEL, CONTAINER_NAME).status();
      return Response.json(s, { headers: { "cache-control": "no-store" } });
    }

    // مسیرهای داخلی از بیرون بسته‌ان
    if (path.startsWith("/_sepnet")) return new Response("Not found", { status: 404 });

    if (path === "/") return Response.redirect(`${url.origin}/dashboard/`, 302);

    // بقیه‌ی درخواست‌ها (پنل، ساب، کانفیگ‌های WS) میرن تو کانتینر
    const headers = new Headers(request.headers);
    headers.set("x-sepnet-host", url.hostname);
    return getContainer(env.PANEL, CONTAINER_NAME).fetch(new Request(request, { headers }));
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(
      getContainer(env.PANEL, CONTAINER_NAME)
        .tick()
        .catch((e) => console.error("tick failed:", String(e))),
    );
  },
};
