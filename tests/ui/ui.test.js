// Browser-logic tests for the web UI (jsdom + fake WebSocket/fetch). No real browser or server needed.
// Run:  cd tests/ui && npm install jsdom@24 && node ui.test.js
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "..", "web") + path.sep;
const html = fs.readFileSync(ROOT + "index.html", "utf8").replace(/<script[^>]*src=[^>]*><\/script>/g, "");
const appJs = fs.readFileSync(ROOT + "app.js", "utf8");
const settingsJs = fs.readFileSync(ROOT + "settings.js", "utf8");
const integrationsJs = fs.readFileSync(ROOT + "settings-integrations.js", "utf8");
const moneyJs = fs.readFileSync(ROOT + "money.js", "utf8");
const moneySpendJs = fs.readFileSync(ROOT + "money-spend.js", "utf8");
const kitJs = fs.readFileSync(ROOT + "panel-kit.js", "utf8");
const themeJs = fs.readFileSync(ROOT + "theme.js", "utf8");
const workJs = fs.readFileSync(ROOT + "work.js", "utf8");
const growthJs = fs.readFileSync(ROOT + "growth.js", "utf8");

let failures = 0;
const check = (name, cond, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + name + (cond ? "" : "   " + extra)); if (!cond) failures++; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const FRAME = (token) => JSON.stringify({ auth: token });

// routes: { "GET /api/history": body | (url) => body | {status, body} }
function boot({ storage = {}, coarse = false, routes: extra = {}, url, ua, standalone = false, drawer = false, sw = false, insecure = false, push, noPush = false, version } = {}) {
  // the poller hits /api/notifications on every boot, so it is always answered; other unknown routes are a 401
  const routes = { "GET /api/notifications": { notifications: [] }, ...extra };
  const dom = new JSDOM(html, { url: url || "https://tapan.example.com/web/index.html", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.__TAPAN_NO_AUTOINIT = true;
  if (ua) Object.defineProperty(w.navigator, "userAgent", { get: () => ua, configurable: true });
  for (const [k, v] of Object.entries(storage)) w.localStorage.setItem(k, v);
  Object.defineProperty(w.HTMLElement.prototype, "innerText", { get() { return this.textContent; }, set(v) { this.textContent = v; } });

  const sockets = [];
  w.WebSocket = class { constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); } send(t) { this.sent.push(t); } close() { this.readyState = 3; } };
  w.WebSocket.OPEN = 1; w.WebSocket.CONNECTING = 0;

  const calls = [];
  w.fetch = async (url, opts = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    calls.push({ method, url, headers: opts.headers || {}, body: opts.body });
    const key = Object.keys(routes).find((k) => { const [m, p] = k.split(" "); return m === method && url.startsWith(p); });
    if (!key) return { ok: false, status: 401, json: async () => ({}) };
    let r = routes[key];
    if (typeof r === "function") r = r(url);
    const status = r && r.status ? r.status : 200;
    const body = r && r.status ? r.body : r;
    return { ok: status < 400, status, json: async () => body };
  };
  w.matchMedia = (q) => ({ matches: q.includes("pointer: coarse") ? coarse : q.includes("max-width: 1000px") ? drawer : q.includes("display-mode: standalone") ? standalone : false, addEventListener() {}, addListener() {} });
  const swCalls = [];
  if (sw) {
    w.isSecureContext = !insecure;
    Object.defineProperty(w.navigator, "serviceWorker", { value: { controller: null, register: (...a) => { swCalls.push(a); return Promise.resolve({}); }, addEventListener() {} }, configurable: true });
  }
  // ── Web Push mock: Notification, PushManager and a service worker registration with a real-ish pushManager ──
  const pushLog = { events: [], subscribeOpts: null, unsubscribed: [], pageNotifications: [], swMessage: () => {} };
  if (push) {
    w.isSecureContext = true;
    let current = push.existing ? makeSub(push.existing.endpoint, push.existing.key) : null;
    function makeSub(endpoint, key) {
      const keyBuf = Uint8Array.from(key).buffer;
      return { endpoint, options: { applicationServerKey: keyBuf },
        toJSON: () => ({ endpoint, expirationTime: null, keys: { p256dh: "BPaaaa", auth: "authsecret" } }),
        unsubscribe: async () => { pushLog.unsubscribed.push(endpoint); current = null; return true; } };
    }
    const Notif = function (title, opts) { pushLog.pageNotifications.push({ title, opts }); };
    Notif.permission = push.permission || "default";
    Notif.requestPermission = async () => { pushLog.events.push("perm"); Notif.permission = push.reply || "granted"; return Notif.permission; };
    w.Notification = Notif;
    if (!noPush) w.PushManager = function () {};
    const reg = { pushManager: {
      getSubscription: async () => current,
      subscribe: async (o) => { pushLog.events.push("subscribe"); pushLog.subscribeOpts = o; current = makeSub("https://fcm.googleapis.com/fcm/send/new-device", new Uint8Array(o.applicationServerKey)); return current; } } };
    const listeners = {};
    Object.defineProperty(w.navigator, "serviceWorker", { value: { controller: null, ready: Promise.resolve(reg), register: () => Promise.resolve(reg),
      addEventListener: (type, fn) => { listeners[type] = fn; } }, configurable: true });
    pushLog.swMessage = (data) => listeners.message && listeners.message({ data });
  } else if (noPush) { /* nothing */ }
  const spoken = [];
  w.speechSynthesis = { cancel() {}, speak(u) { spoken.push(u.text); }, getVoices: () => [] };
  w.SpeechSynthesisUtterance = function (t) { this.text = t; };
  w.eval(themeJs);
  w.eval(version ? appJs.replace(/__WEB_VERSION__/g, version) : appJs);
  w.eval(settingsJs);
  w.eval(integrationsJs);
  w.eval(moneyJs);
  w.eval(moneySpendJs);
  w.eval(kitJs);
  w.eval(workJs);
  w.eval(growthJs);
  w.init();
  const $ = (id) => w.document.getElementById(id);
  return {
    w, sockets, calls, spoken, swCalls, pushLog, $, S: () => w.TapanApp.state,
    overlay: () => $("auth-overlay"), msg: () => $("auth-msg"), pill: () => $("conn-pill"),
    chat: () => $("chat-history"), box: () => $("user-input"),
    open: (s) => { s.readyState = 1; s.onopen && s.onopen(); },
    close: (s, code) => { s.readyState = 3; s.onclose && s.onclose({ code }); },
    say: (s, obj) => s.onmessage({ data: JSON.stringify(obj) }),
    key: (el, opts) => { const e = new w.KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...opts }); el.dispatchEvent(e); return e; },
    type: (text) => { const b = $("user-input"); b.value = text; b.dispatchEvent(new w.Event("input", { bubbles: true })); },
    messages: () => [...w.document.querySelectorAll("#chat-history .message:not(.working)")],
  };
}
const authed = (t, s = t.sockets[t.sockets.length - 1]) => { t.open(s); t.say(s, { type: "auth_ok" }); };

(async () => {
  // ── 1. First visit, server wants a token ────────────────────────
  let t = boot();
  let s = t.sockets[0];
  check("default conversation id is the shared 'main' thread", /\/ws\/main$/.test(s.url), s.url);
  t.open(s);
  check("URL never carries a token; auth is the first frame", !/token/.test(s.url) && s.sent[0] === FRAME(""), JSON.stringify(s.sent));
  t.close(s, 4401);
  check("4401 shows the login overlay", !t.overlay().classList.contains("hidden"));
  check("status pill says Locked", t.pill().dataset.state === "locked");
  check("first prompt is informative, not an error", !t.msg().classList.contains("error") && /access token/i.test(t.msg().textContent));
  check("overlay says it is not the OpenRouter key", /not<\/b> your OpenRouter key/i.test(t.$("auth-form").innerHTML));
  await wait(1400);
  check("no reconnect loop while locked", t.sockets.length === 1, `sockets=${t.sockets.length}`);

  // ── 2. User enters the token ────────────────────────────────────
  t.$("auth-input").value = "  my-secret  ";
  t.$("auth-form").dispatchEvent(new t.w.Event("submit", { cancelable: true }));
  check("submitting opens a new socket", t.sockets.length === 2);
  t.open(t.sockets[1]);
  check("trimmed token is sent as the first frame, not in the URL", t.sockets[1].sent[0] === FRAME("my-secret") && !/secret/.test(t.sockets[1].url));
  check("token is remembered for next time", t.w.localStorage.getItem("tapan.token") === "my-secret");
  t.say(t.sockets[1], { type: "auth_ok" });
  check("auth_ok => Online, overlay gone", t.pill().dataset.state === "online" && t.overlay().classList.contains("hidden"));
  check("Lock button appears once a token is stored", !t.$("lock-btn").classList.contains("hidden"));

  // ── 3. Rejected / stale token ───────────────────────────────────
  t = boot({ storage: { "tapan.token": "stale" } });
  t.open(t.sockets[0]);
  check("a saved token is sent automatically", t.sockets[0].sent[0] === FRAME("stale"));
  t.close(t.sockets[0], 4401);
  check("a rejected token shows an error and is forgotten", t.msg().classList.contains("error") && /not accepted/i.test(t.msg().textContent) && t.w.localStorage.getItem("tapan.token") === null);

  // ── 4. Network drop reconnects, re-authenticates, ignores stale sockets ──
  t = boot({ storage: { "tapan.token": "good" }, routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t);
  t.close(t.sockets[0], 1006);
  check("a drop shows Reconnecting, not the login screen", t.pill().dataset.state === "reconnecting" && t.overlay().classList.contains("hidden"));
  await wait(1300);
  check("it reconnects by itself and re-authenticates", t.sockets.length === 2 && (t.open(t.sockets[1]), t.sockets[1].sent[0] === FRAME("good")));
  const before = t.sockets.length;
  t.close(t.sockets[0], 1006);                       // late event from the dead socket
  await wait(1300);
  check("events from superseded sockets are ignored", t.sockets.length === before);

  // ── 5. REST 401 also opens the login screen ─────────────────────
  t = boot();
  authed(t);
  await wait(60);
  check("401 from the REST API shows the login screen", !t.overlay().classList.contains("hidden"));

  // ── 6. Composer: multiline, keys, touch ─────────────────────────
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t); await wait(30);
  s = t.sockets[0];
  const sent = () => s.sent.slice(1);
  check("message box is a textarea", t.box().tagName === "TEXTAREA");
  check("send is disabled while empty", t.$("send-btn").disabled);
  t.type("line one\nline two");
  check("send enables once there is text", !t.$("send-btn").disabled);
  let e = t.key(t.box(), { key: "Enter", shiftKey: true });
  check("Shift+Enter adds a line (not prevented, nothing sent)", !e.defaultPrevented && sent().length === 0);
  e = t.key(t.box(), { key: "Enter", isComposing: true });
  check("Enter while an IME is composing does not send", !e.defaultPrevented && sent().length === 0);
  t.type("  Remind me to:\n1. call mom 9am\n2. rent on the 1st\n\n3. gym  \n");
  e = t.key(t.box(), { key: "Enter" });
  check("Enter sends (and does not insert a newline)", e.defaultPrevented && sent().length === 1);
  check("multiline text sent intact: ends trimmed, inner/blank lines kept", sent()[0] === "Remind me to:\n1. call mom 9am\n2. rent on the 1st\n\n3. gym", JSON.stringify(sent()[0]));
  check("box is cleared after sending", t.box().value === "");
  check("user bubble keeps its line breaks", t.messages().pop().querySelector(".bubble").textContent.split("\n").length === 5);

  // ── 7. Working indicator, tool chips, busy guard ────────────────
  check("typing indicator appears while waiting", !!t.w.document.querySelector(".message.working .typing"));
  check("pill says Thinking", /Thinking/.test(t.pill().textContent));
  t.type("another");
  check("send is disabled while busy", t.$("send-btn").disabled);
  t.key(t.box(), { key: "Enter" });
  check("a second message while busy is refused with a toast", sent().length === 1 && t.$("toast").classList.contains("show"));
  t.say(s, { type: "tool_start", name: "set_reminders" });
  check("tool chip shows what it is doing", /Setting reminders/.test(t.w.document.querySelector(".working .tool-chip.running").textContent));
  t.say(s, { type: "tool_end", name: "set_reminders", ok: true });
  check("chip turns into done when the tool finishes", !!t.w.document.querySelector(".working .tool-chip.done"));
  t.say(s, { type: "final", text: "All set.", debug: { mode: "agent" } });
  check("reply replaces the typing indicator", !t.w.document.querySelector(".message.working") && /All set\./.test(t.messages().pop().textContent));
  check("reply keeps a record of the tool used", /Setting reminders/.test(t.messages().pop().querySelector(".meta").textContent));
  check("pill is Online again and send is not stuck", t.pill().dataset.state === "online" && !t.S().busy);
  t.say(s, { type: "final", text: "Answer from the offline fallback", debug: { mode: "legacy" } });
  check("offline-fallback answers are labelled", /basic offline mode/.test(t.messages().pop().textContent));

  // touch device: Enter is a newline
  t = boot({ coarse: true, routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t); await wait(30);
  t.type("hi");
  e = t.key(t.box(), { key: "Enter" });
  check("on touch screens Enter does not send", !e.defaultPrevented && t.sockets[0].sent.length === 1);
  t.$("send-btn").click();
  check("...the send button does", t.sockets[0].sent[1] === "hi");

  // ── 8. Conversation history is restored ─────────────────────────
  const hist = { messages: [
    { role: "user", text: "Plan my Goa trip", ts: "2026-11-20T09:00:00+00:00" },
    { role: "assistant", text: "Sure — when?", ts: "2026-11-20T09:00:05+00:00" },
    { role: "user", text: "December", ts: "2026-11-23T09:00:00+00:00" },
    { role: "assistant", text: "Great choice.", ts: "2026-11-23T09:00:03+00:00" } ] };
  t = boot({ routes: { "GET /api/history": hist, "GET /api/briefing": {}, "GET /api/conversations": { conversations: [] } } });
  check("welcome screen is visible before history loads", !t.$("empty-state").classList.contains("hidden"));
  authed(t); await wait(60);
  check("history was requested for this session", t.calls.some((c) => c.url.startsWith("/api/history?session_id=main")));
  check("past messages are rendered in order", t.messages().map((m) => m.querySelector(".bubble").textContent).join("|") === "Plan my Goa trip|Sure — when?|December|Great choice.");
  check("welcome screen hides when history exists", t.$("empty-state").classList.contains("hidden"));
  check("a day separator is shown between days", t.w.document.querySelectorAll(".day-sep").length === 2);
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t); await wait(60);
  check("with no history the welcome screen stays", !t.$("empty-state").classList.contains("hidden"));

  // ── 9. Conversations list, switching, new chat, delete ──────────
  const convs = { conversations: [
    { session_id: "main", title: "Plan my Goa trip", turns: 2, updated: "2026-11-23T09:00:03+00:00" },
    { session_id: "budget", title: "Monthly budget", turns: 5, updated: "2026-11-18T09:00:00+00:00" } ] };
  t = boot({ routes: { "GET /api/history": (u) => (/budget/.test(u) ? { messages: [{ role: "user", text: "Budget chat", ts: "2026-11-18T09:00:00+00:00" }] } : hist),
    "GET /api/briefing": {}, "GET /api/conversations": convs, "DELETE /api/conversations/": { ok: true } } });
  authed(t); await wait(60);
  t.$("history-btn").click(); await wait(60);
  check("History tab lists conversations", t.w.document.querySelectorAll(".conv").length === 2);
  check("current conversation is highlighted and marked for assistive tech", /Plan my Goa/.test(t.w.document.querySelector(".conv.current .title").textContent) && t.w.document.querySelector(".conv.current .conv-open").getAttribute("aria-current") === "true");
  check("no interactive control is nested inside another (axe: nested-interactive)", [...t.w.document.querySelectorAll(".conv")].every((row) => row.querySelectorAll("button").length === 2 && !row.querySelector("button button, [role=button]")));
  t.w.document.querySelectorAll(".conv .conv-open")[1].click();
  check("choosing a conversation opens a socket for that session", /\/ws\/budget$/.test(t.sockets[1].url) && t.w.localStorage.getItem("tapan.session") === "budget");
  check("chat is cleared while it loads", t.messages().length === 0);
  authed(t, t.sockets[1]); await wait(60);
  check("its history is shown", t.messages().length === 1 && /Budget chat/.test(t.messages()[0].textContent));
  check("drawer closes after choosing", t.$("app").dataset.panel === "closed");
  t.$("new-chat-btn").click();
  check("New chat starts a fresh session", /\/ws\/chat-/.test(t.sockets[2].url) && /^chat-/.test(t.S().sessionId));
  authed(t, t.sockets[2]); await wait(60);
  check("a fresh chat shows the welcome screen, not old messages", !t.$("empty-state").classList.contains("hidden") && t.messages().length === 0);
  check("history is not re-fetched for a brand-new chat", !t.calls.some((c) => /session_id=chat-/.test(c.url)));
  t.$("history-btn").click(); await wait(60);
  const del = t.w.document.querySelector(".conv .mini.del");
  del.click();
  check("delete needs a second tap", /Delete\?/.test(t.w.document.querySelector(".conv .mini.confirm").textContent) && !t.calls.some((c) => c.method === "DELETE"));
  t.w.document.querySelector(".conv .mini.confirm").click(); await wait(60);
  check("second tap deletes on the server", t.calls.some((c) => c.method === "DELETE" && /\/api\/conversations\/main$/.test(c.url)));

  // ── 10. Today panel ─────────────────────────────────────────────
  const in2h = new Date(Date.now() + 2 * 3600e3).toISOString();
  const brief = { weather: "Mumbai: now 29°C (feels 33°C), clear sky\n2026-11-24: ...", overdue_reminders: [{ id: 9, title: "Old thing", due_at: "2026-11-01T09:00:00+00:00" }],
    reminders_today: [{ id: 1, title: "Call mom", due_at: in2h }], upcoming_reminders: [{ id: 2, title: "Dentist", due_at: "2026-12-30T10:30:00+00:00" }],
    open_tasks: [{ id: 5, title: "Write report", priority: "high" }], events_today: [{ title: "Standup", start_at: in2h, location: "Zoom" }] };
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": brief, "DELETE /api/reminders/": { ok: true }, "POST /api/tasks/": { ok: true } } });
  authed(t); await wait(80);
  const today = t.$("panel-today");
  check("weather line is shown", /Mumbai: now 29/.test(today.textContent) && !/2026-11-24/.test(today.textContent));
  check("overdue reminders are flagged", /Overdue/.test(today.querySelector(".row.overdue").textContent));
  check("reminders, tasks and events appear", ["Call mom", "Dentist", "Write report", "Standup"].every((x) => today.textContent.includes(x)));
  today.querySelector('button[aria-label="Cancel reminder: Call mom"]').click(); await wait(30);
  check("cancelling a reminder calls the API and removes the row", t.calls.some((c) => c.method === "DELETE" && c.url === "/api/reminders/1") && !today.textContent.includes("Call mom"));
  today.querySelector('button[aria-label="Mark done: Write report"]').click(); await wait(30);
  check("completing a task calls the API and removes the row", t.calls.some((c) => c.method === "POST" && c.url === "/api/tasks/5/complete") && !today.textContent.includes("Write report"));

  // ── 11. Reminders that fire: shown separately, spoken once ──────
  const notes = [1, 2, 3].map((id) => ({ id, kind: "reminder", title: "Reminder", body: `Thing ${id}`, created_at: new Date().toISOString() }));
  t = boot({ storage: { "tapan.token": "ok" }, routes: { "GET /api/notifications": { notifications: notes }, "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  await wait(80);
  check("each fired reminder is shown", ["Thing 1", "Thing 2", "Thing 3"].every((x) => t.chat().textContent.includes(x)));
  check("they are spoken once, not cut off one by one", t.spoken.length === 1 && /3 reminders/.test(t.spoken[0]) && /Thing 3/.test(t.spoken[0]), JSON.stringify(t.spoken));
  check("last seen notification id is remembered", t.w.localStorage.getItem("tapan.lastNotification") === "3");

  // ── 12. Voice mode ──────────────────────────────────────────────
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t); await wait(30);
  check("voice mode defaults to 'only after I use the mic'", t.$("voice-mode-btn").dataset.mode === "voice");
  t.type("typed message"); t.key(t.box(), { key: "Enter" });
  t.say(t.sockets[0], { type: "final", text: "typed reply" });
  check("a reply to a typed message is NOT spoken in that mode", t.spoken.length === 0);
  t.$("voice-mode-btn").click();
  check("button cycles to 'always' and remembers it", t.$("voice-mode-btn").dataset.mode === "always" && t.w.localStorage.getItem("tapan.voice") === "always");
  t.type("again"); t.key(t.box(), { key: "Enter" });
  t.say(t.sockets[0], { type: "final", text: "**Bold** reply with [a link](https://x.y) and `code`" });
  check("'always' speaks replies, with markdown stripped", t.spoken.length === 1 && t.spoken[0] === "Bold reply with a link and code", JSON.stringify(t.spoken));
  t.$("voice-mode-btn").click();
  check("third state is muted", t.$("voice-mode-btn").dataset.mode === "off");

  // ── 13. Safety: nothing user- or model-supplied is parsed as HTML ──
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } });
  authed(t); await wait(30);
  t.type("<img src=x onerror=alert(1)>"); t.key(t.box(), { key: "Enter" });
  const bubble = t.messages().pop().querySelector(".bubble");
  check("user text is rendered as text, never as HTML", bubble.querySelector("img") === null && bubble.textContent.includes("<img"));
  t.say(t.sockets[0], { type: "final", text: "<script>x()</script>hi" });
  check("assistant text without a sanitizer falls back to plain text", t.messages().pop().querySelector("script") === null);

  // ═══════════════ Install as an app ═══════════════
  const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36";
  const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
  const quiet = { routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": {} } };
  const fakePrompt = (t, outcome = "accepted") => {
    const e = new t.w.Event("beforeinstallprompt", { cancelable: true });
    e.prompted = 0; e.prompt = () => { e.prompted++; }; e.userChoice = Promise.resolve({ outcome });
    t.w.dispatchEvent(e);
    return e;
  };
  const hidden = (el) => el.classList.contains("hidden");

  // desktop Chrome/Edge: nothing to show until the browser says the app is installable
  t = boot(quiet); authed(t);
  check("desktop: no install UI before the browser offers it", hidden(t.$("install-btn")) && hidden(t.$("install-banner")));
  let ev = fakePrompt(t);
  check("the browser's own install prompt is suppressed in favour of ours", ev.defaultPrevented);
  check("button and banner appear when installable", !hidden(t.$("install-btn")) && !hidden(t.$("install-banner")));
  t.$("install-yes").click(); await wait(20);
  check("tapping Install shows the native prompt", ev.prompted === 1);
  check("after accepting, the install UI goes away", hidden(t.$("install-btn")) && hidden(t.$("install-banner")));
  t.w.dispatchEvent(new t.w.Event("appinstalled"));
  check("appinstalled remembers it and confirms", t.w.localStorage.getItem("tapan.installed") === "1" && t.$("toast").classList.contains("show"));

  // declined: banner is snoozed (not nagging), flag persists
  t = boot(quiet); authed(t); ev = fakePrompt(t, "dismissed");
  t.$("install-btn").click(); await wait(20);
  check("declining snoozes the banner", hidden(t.$("install-banner")) && Number(t.w.localStorage.getItem("tapan.installDismissed")) > 0);
  t = boot({ ...quiet, storage: { "tapan.installDismissed": String(Date.now() - 3600e3) } }); authed(t); fakePrompt(t);
  check("a recent dismissal keeps the banner hidden but leaves the button", hidden(t.$("install-banner")) && !hidden(t.$("install-btn")));
  t = boot({ ...quiet, storage: { "tapan.installDismissed": String(Date.now() - 20 * 86400e3) } }); authed(t); fakePrompt(t);
  check("...and after two weeks it may ask again", !hidden(t.$("install-banner")));
  t = boot(quiet); authed(t); t.$("install-no").click ? 0 : 0; fakePrompt(t); t.$("install-no").click();
  check("'Not now' hides the banner immediately", hidden(t.$("install-banner")));

  // Android browser without a native prompt: still offer a path
  t = boot({ ...quiet, ua: ANDROID }); authed(t);
  check("Android: install is offered even before the browser event", !hidden(t.$("install-btn")) && !hidden(t.$("install-banner")));
  t.$("install-btn").focus(); t.$("install-btn").click();
  check("without a native prompt, a how-to sheet opens", !hidden(t.$("install-sheet")) && /menu/i.test(t.$("install-steps").textContent) && /Install app/.test(t.$("install-steps").textContent));
  check("sheet moves focus into the dialog and blocks the page behind it", t.w.document.activeElement.id === "install-close" && t.$("app").hasAttribute("inert"));
  t.key(t.$("install-sheet"), { key: "Escape" });
  check("Escape closes the sheet and returns focus", hidden(t.$("install-sheet")) && !t.$("app").hasAttribute("inert") && t.w.document.activeElement.id === "install-btn");
  ev = fakePrompt(t);
  t.$("install-btn").click(); await wait(20);
  check("when the browser event arrives later, the native prompt is used instead of the sheet", ev.prompted === 1 && hidden(t.$("install-sheet")));

  t = boot({ ...quiet, ua: IPHONE }); authed(t); t.$("install-btn").click();
  check("iPhone: instructions mention Share → Add to Home Screen", /Share/.test(t.$("install-steps").textContent) && /Add to Home Screen/.test(t.$("install-steps").textContent));

  t = boot({ ...quiet, ua: ANDROID, standalone: true }); authed(t);
  check("already running as an installed app: no install UI, and it is remembered", hidden(t.$("install-btn")) && hidden(t.$("install-banner")) && t.w.localStorage.getItem("tapan.installed") === "1");
  t = boot({ ...quiet, ua: ANDROID, storage: { "tapan.installed": "1" } }); authed(t);
  check("known-installed phone does not nag", hidden(t.$("install-btn")) && hidden(t.$("install-banner")));
  ev = fakePrompt(t);
  check("...unless the browser says it is installable again (app was removed)", !hidden(t.$("install-btn")) && t.w.localStorage.getItem("tapan.installed") === null);

  // service worker + launch shortcuts
  t = boot({ ...quiet, sw: true });
  check("service worker is registered from the app's own scope", t.swCalls.length === 1 && t.swCalls[0][0] === "sw.js" && t.swCalls[0][1].scope === "./");
  t = boot({ ...quiet, sw: true, insecure: true });
  check("no service worker on an insecure origin", t.swCalls.length === 0);
  t = boot({ ...quiet, url: "https://tapan.example.com/web/index.html?new=1&source=shortcut" });
  check("shortcut ?new=1 opens a brand-new conversation", /^chat-/.test(t.S().sessionId) && /\/ws\/chat-/.test(t.sockets[0].url) && t.w.location.search === "");
  t = boot({ ...quiet, drawer: true, url: "https://tapan.example.com/web/index.html?panel=history" }); await wait(20);
  check("shortcut ?panel=history opens the drawer on that tab", t.$("app").dataset.panel === "open" && t.$("tab-history").getAttribute("aria-selected") === "true");

  // ═══════════════ Accessibility ═══════════════
  t = boot({ ...quiet, drawer: true }); authed(t); await wait(30);
  const side = t.$("side-panel");
  check("phone: a closed off-screen drawer is unreachable by keyboard / screen reader", side.hasAttribute("inert") && side.getAttribute("role") === "complementary");
  t.$("today-btn").focus(); t.$("today-btn").click(); await wait(30);
  check("an open section page is a labelled region, not a modal, and is reachable", side.getAttribute("role") === "region" && side.getAttribute("aria-labelledby") === "panel-title" && !side.hasAttribute("aria-modal") && !side.hasAttribute("inert"));
  check("the chat and top bar behind it are inert, but the bottom bar is not (it is how you move around)", t.w.document.querySelector(".topbar").hasAttribute("inert") && t.w.document.querySelector(".chat").hasAttribute("inert") && !t.$("bottom-nav").hasAttribute("inert"));
  check("focus moves to the page title, so a screen reader announces where you are", t.w.document.activeElement.id === "panel-title" && /Today/.test(t.w.document.activeElement.textContent));
  check("opening pushes a history entry so the Back button can close it", t.w.history.state && t.w.history.state.tapanPanel === true);
  const focusables = [...side.querySelectorAll('a[href], button:not([disabled]), textarea, input, [tabindex]:not([tabindex="-1"])')].filter((el) => !el.closest(".hidden"));
  focusables[focusables.length - 1].focus();
  let tab = t.key(side, { key: "Tab" });
  check("Tab is not trapped inside the page: it can move on to the bottom bar", !tab.defaultPrevented);
  focusables[0].focus();
  tab = t.key(side, { key: "Tab", shiftKey: true });
  check("...and Shift+Tab can move back out", !tab.defaultPrevented);
  // tabs: arrow keys
  t.$("tab-today").focus();
  t.key(t.$("tab-today"), { key: "ArrowRight" });
  check("arrow keys switch tabs and move focus", t.$("tab-history").getAttribute("aria-selected") === "true" && t.w.document.activeElement.id === "tab-history");
  check("only the selected tab is in the Tab order (roving tabindex)", t.$("tab-history").tabIndex === 0 && t.$("tab-today").tabIndex === -1);
  t.key(t.$("tab-history"), { key: "ArrowLeft" });
  check("ArrowLeft wraps back", t.$("tab-today").getAttribute("aria-selected") === "true");
  t.key(t.w.document, { key: "Escape" });
  check("Escape closes and focus returns to the button that opened it", t.$("app").dataset.panel === "closed" && t.w.document.activeElement.id === "today-btn");
  check("background is interactive again", !t.w.document.querySelector(".chat").hasAttribute("inert") && side.hasAttribute("inert"));
  t.$("today-btn").click(); await wait(20);
  t.w.dispatchEvent(new t.w.PopStateEvent("popstate"));
  check("the Android Back button (popstate) closes the drawer", t.$("app").dataset.panel === "closed");

  t = boot({ ...quiet, drawer: false }); authed(t); await wait(30);
  check("desktop: the side panel is a normal landmark, never inert or modal", !t.$("side-panel").hasAttribute("inert") && t.$("side-panel").getAttribute("role") === "complementary" && !t.$("side-panel").hasAttribute("aria-modal"));

  // lock: nothing behind the login gate is reachable
  t = boot(); t.open(t.sockets[0]); t.close(t.sockets[0], 4401);
  check("login gate makes the page behind it inert", t.$("app").hasAttribute("inert"));
  check("login error is announced (role=alert)", t.msg().getAttribute("role") === "alert");
  t.key(t.$("auth-overlay"), { key: "Tab" });
  t.$("auth-input").value = "x"; t.$("auth-form").dispatchEvent(new t.w.Event("submit", { cancelable: true }));
  check("...and is reachable again once unlocked", !t.$("app").hasAttribute("inert"));

  // messages & live regions
  t = boot({ ...quiet }); authed(t); await wait(30);
  t.type("hello"); t.key(t.box(), { key: "Enter" });
  const mine = t.messages().pop();
  check("each message is a labelled group: who and when", mine.getAttribute("role") === "group" && /^You, /.test(mine.getAttribute("aria-label")));
  await wait(60);
  check("thinking state is announced to screen readers", /Tapan is thinking/.test(t.$("sr-status").textContent));
  t.say(t.sockets[0], { type: "final", text: "Hi" });
  const hers = t.messages().pop();
  check("assistant messages are labelled too, decorative avatar hidden", /^Tapan, /.test(hers.getAttribute("aria-label")) && hers.querySelector(".avatar").getAttribute("aria-hidden") === "true");
  check("copy buttons say whose message they copy", /Copy your message/.test(mine.querySelector(".copy-btn").getAttribute("aria-label")) && /Copy Tapan's message/.test(hers.querySelector(".copy-btn").getAttribute("aria-label")));
  check("message box is described by the keyboard hint", t.box().getAttribute("aria-describedby") === "composer-hint" && !!t.$("composer-hint"));
  check("the chat is a live log; the skip link exists", t.chat().getAttribute("role") === "log" && !!t.w.document.querySelector('a.skip-link[href="#user-input"]'));

  t = boot({ routes: { "GET /api/history": hist, "GET /api/briefing": {} } }); authed(t); await wait(300);   // the announcement is deferred 30 ms behind an async fetch
  check("restored history is announced once, not message by message", /Restored 4 messages/.test(t.$("sr-status").textContent) && t.chat().getAttribute("aria-busy") === "false");
  t = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": brief } }); authed(t); await wait(80);
  const prio = t.$("panel-today").querySelector(".prio");
  check("task priority is not conveyed by colour alone", prio.getAttribute("role") === "img" && /High priority/.test(prio.getAttribute("aria-label")));
  check("every icon-only button has an accessible name", [...t.w.document.querySelectorAll("button")].filter((b) => !b.textContent.trim() || b.textContent.trim().length < 2).every((b) => b.getAttribute("aria-label")), [...t.w.document.querySelectorAll("button")].filter((b) => !b.textContent.trim() && !b.getAttribute("aria-label")).map((b) => b.id).join(","));
  t = boot(quiet); t.open(t.sockets[0]);
  check("the mic button reports its pressed state", t.$("voice-toggle").getAttribute("aria-pressed") === "false");

  // ═══════════════ Push notifications ═══════════════
  const SERVER_KEY = Buffer.alloc(65, 7); SERVER_KEY[0] = 4;                      // stands in for the server's 65-byte VAPID public key
  const b64url = (buf) => Buffer.from(buf).toString("base64url");
  const pushRoutes = (over = {}) => ({
    "GET /api/history": { messages: [] }, "GET /api/briefing": {},
    "GET /api/push/key": { enabled: true, public_key: b64url(SERVER_KEY) },
    "POST /api/push/subscribe": { ok: true }, "POST /api/push/unsubscribe": { ok: true }, "POST /api/push/test": { ok: true, sent: 1 },
    ...over,
  });
  const quietNote = { "GET /api/notifications": { notifications: [] } };
  const settle = () => wait(40);
  const bootPush = (opts = {}) => boot({ push: {}, ...opts, routes: pushRoutes(opts.routes) });

  // 1. fresh visit: offered, never auto-prompted
  t = bootPush(); authed(t); await settle();
  check("push: no permission prompt is shown on page load", t.pushLog.events.filter((e) => e === "perm").length === 0 && t.w.Notification.permission === "default");
  check("push: Today panel offers 'Turn on notifications'", /Turn on notifications/.test(t.$("panel-today").textContent) && !!t.$("panel-today").querySelector(".push-card .wide-btn"));
  check("push: the card is a labelled section with a heading", t.$("panel-today").querySelector(".push-card").getAttribute("aria-labelledby") === "push-card-title" && t.$("push-card-title").tagName === "H2");

  // 2. enabling: permission FIRST (needs the user gesture), then subscribe with the server key, then register with the server
  t.pushLog.events.length = 0;
  t.$("panel-today").querySelector(".push-card .wide-btn").click(); await settle();
  check("push: the permission prompt is the very first step after the tap", t.pushLog.events[0] === "perm", JSON.stringify(t.pushLog.events));
  check("push: subscribes with userVisibleOnly and the server's VAPID key", t.pushLog.subscribeOpts && t.pushLog.subscribeOpts.userVisibleOnly === true && Buffer.from(t.pushLog.subscribeOpts.applicationServerKey).equals(SERVER_KEY));
  const post = t.calls.find((c) => c.method === "POST" && c.url === "/api/push/subscribe");
  check("push: registers the subscription with the server (token attached via api())", !!post && JSON.parse(post.body).endpoint.startsWith("https://fcm.googleapis.com/") && JSON.parse(post.body).keys.p256dh);
  check("push: card switches to the 'on' state with test / turn-off", /On for this device/.test(t.$("panel-today").textContent) && /Send a test/.test(t.$("panel-today").textContent) && /Turn off/.test(t.$("panel-today").textContent));
  check("push: success is announced to screen readers", /notifications are on/i.test(t.$("sr-status").textContent) || /notifications are on/i.test(t.$("toast").textContent));
  check("push: 'on' card moves to the bottom (above the footer), not the top", t.$("panel-today").firstElementChild.classList.contains("push-card") === false);

  // 3. test + turn off
  t.$("panel-today").querySelectorAll(".push-card .link-btn")[0].click(); await settle();
  check("push: 'Send a test' calls the server and confirms", t.calls.some((c) => c.method === "POST" && c.url === "/api/push/test") && /Test sent/.test(t.$("toast").textContent));
  t.$("panel-today").querySelectorAll(".push-card .link-btn")[1].click(); await settle();
  check("push: turning off unsubscribes the device locally", t.pushLog.unsubscribed.length === 1);
  const un = t.calls.find((c) => c.url === "/api/push/unsubscribe");
  check("push: ...and tells the server which endpoint to forget", !!un && JSON.parse(un.body).endpoint.startsWith("https://fcm.googleapis.com/"));
  check("push: card returns to the 'off' offer", /Turn on notifications/.test(t.$("panel-today").textContent));

  // 4. permission outcomes
  t = bootPush({ push: { reply: "denied" } }); authed(t); await settle();
  t.$("panel-today").querySelector(".push-card .wide-btn").click(); await settle();
  check("push: if the user denies, nothing is subscribed", t.pushLog.subscribeOpts === null && /blocked for this site/.test(t.$("panel-today").textContent));
  check("push: a blocked state offers no button that cannot work", !t.$("panel-today").querySelector(".push-card button"));
  t = bootPush({ push: { reply: "default" } }); authed(t); await settle();
  t.$("panel-today").querySelector(".push-card .wide-btn").click(); await settle();
  check("push: dismissing the prompt leaves it offerable (not blocked)", /Turn on notifications/.test(t.$("panel-today").textContent) && t.pushLog.subscribeOpts === null);
  t = bootPush({ push: { permission: "denied" } }); authed(t); await settle();
  check("push: already blocked at load => explained, no subscribe attempt", /blocked for this site/.test(t.$("panel-today").textContent) && t.pushLog.subscribeOpts === null);

  // 5. reconciliation on load
  const existing = (key) => ({ endpoint: "https://fcm.googleapis.com/fcm/send/existing", key });
  t = bootPush({ push: { permission: "granted", existing: existing(SERVER_KEY) } }); authed(t); await settle();
  check("push: an existing, valid subscription shows 'on' without any prompt", /On for this device/.test(t.$("panel-today").textContent) && t.pushLog.events.filter((e) => e === "perm").length === 0);
  check("push: ...and is re-sent to the server on load (heals a wiped database)", t.calls.some((c) => c.method === "POST" && c.url === "/api/push/subscribe" && JSON.parse(c.body).endpoint.endsWith("/existing")));
  t = bootPush({ push: { permission: "granted", existing: existing(Buffer.alloc(65, 9)) } }); authed(t); await settle();
  check("push: a subscription made with an OLD server key is dropped...", t.pushLog.unsubscribed.length === 1);
  check("push: ...and replaced silently (permission already granted), with the new key", t.pushLog.subscribeOpts && Buffer.from(t.pushLog.subscribeOpts.applicationServerKey).equals(SERVER_KEY) && /On for this device/.test(t.$("panel-today").textContent));
  t = bootPush({ push: { permission: "granted" } }); authed(t); await settle();
  check("push: permission granted but no subscription => offered again, no prompt needed", /Turn on notifications/.test(t.$("panel-today").textContent) && t.pushLog.events.length === 0);

  // 6. environments where it cannot work say the right thing
  t = bootPush({ routes: { "GET /api/push/key": { enabled: false, public_key: null } } }); authed(t); await settle();
  check("push: server without push => no card at all", !t.$("panel-today").querySelector(".push-card"));
  t = bootPush({ noPush: true }); authed(t); await settle();
  check("push: browser without PushManager => no card, nothing breaks", !t.$("panel-today").querySelector(".push-card") && !t.calls.some((c) => c.url === "/api/push/key"));
  t = bootPush({ ua: IPHONE }); authed(t); await settle();
  check("push: iPhone in a normal tab => explains Add to Home Screen, no dead button", /Add to Home Screen/.test(t.$("panel-today").textContent) && !t.$("panel-today").querySelector(".push-card button") && !t.calls.some((c) => c.url === "/api/push/key"));
  t = bootPush({ ua: IPHONE, standalone: true }); authed(t); await settle();
  check("push: iPhone installed to the Home Screen => can turn on", /Turn on notifications/.test(t.$("panel-today").textContent));
  t = bootPush({ routes: { "GET /api/push/key": { status: 500, body: {} } } }); authed(t); await settle();
  check("push: server error while checking => a Retry, not a broken panel", /Could not check/.test(t.$("panel-today").textContent) && /Retry/.test(t.$("panel-today").textContent));

  // 7. a failed registration must not leave a half-subscribed device behind
  t = bootPush({ routes: { "POST /api/push/subscribe": { status: 400, body: { detail: "bad" } } } }); authed(t); await settle();
  t.$("panel-today").querySelector(".push-card .wide-btn").click(); await settle();
  check("push: if the server refuses the subscription, the browser subscription is rolled back", t.pushLog.unsubscribed.length === 1 && /Turn on notifications/.test(t.$("panel-today").textContent) && /Could not turn on/.test(t.$("toast").textContent));
  t = bootPush({ routes: { "POST /api/push/test": { status: 409, body: {} } }, push: { permission: "granted", existing: existing(SERVER_KEY) } }); authed(t); await settle();
  t.$("panel-today").querySelectorAll(".push-card .link-btn")[0].click(); await settle();
  check("push: a 409 on test says the device is not registered", /not registered/.test(t.$("toast").textContent));
  t = bootPush({ routes: { "POST /api/push/test": { status: 429, body: {} } }, push: { permission: "granted", existing: existing(SERVER_KEY) } }); authed(t); await settle();
  t.$("panel-today").querySelectorAll(".push-card .link-btn")[0].click(); await settle();
  check("push: a 429 on test says to wait", /Wait a minute/.test(t.$("toast").textContent));

  // 8. the offer right after setting a reminder
  const setReminderTurn = (tt) => {
    tt.type("remind me tomorrow"); tt.key(tt.box(), { key: "Enter" });
    tt.say(tt.sockets[0], { type: "tool_start", name: "set_reminders" }); tt.say(tt.sockets[0], { type: "tool_end", name: "set_reminders", ok: true });
    tt.say(tt.sockets[0], { type: "final", text: "Set it." });
  };
  t = bootPush(); authed(t); await settle();
  setReminderTurn(t);
  check("push: after a reminder is set, an inline offer appears in the chat", !!t.chat().querySelector(".push-prompt") && /notification on this device/.test(t.chat().querySelector(".push-prompt").textContent));
  check("push: the offer is a labelled group with a real button and a way out", t.chat().querySelector(".push-prompt").getAttribute("aria-label") === "Suggestion" && !!t.chat().querySelector(".push-prompt .wide-btn") && /Not now/.test(t.chat().querySelector(".push-prompt").textContent));
  t.chat().querySelector(".push-prompt .link-btn").click();
  check("push: 'Not now' removes it and is remembered", !t.chat().querySelector(".push-prompt") && t.w.localStorage.getItem("tapan.pushAsked") === "dismissed");
  t.type("again"); t.key(t.box(), { key: "Enter" }); t.say(t.sockets[0], { type: "tool_start", name: "set_reminder" }); t.say(t.sockets[0], { type: "tool_end", name: "set_reminder", ok: true }); t.say(t.sockets[0], { type: "final", text: "Done." });
  check("push: a dismissed offer is never repeated", !t.chat().querySelector(".push-prompt"));
  t = bootPush(); authed(t); await settle(); setReminderTurn(t);
  t.chat().querySelector(".push-prompt .wide-btn").click(); await settle();
  check("push: accepting from the chat offer turns it on and removes the offer", /On for this device/.test(t.$("panel-today").textContent) && !t.chat().querySelector(".push-prompt"));
  t = bootPush({ push: { permission: "granted", existing: existing(SERVER_KEY) } }); authed(t); await settle(); setReminderTurn(t);
  check("push: no offer when notifications are already on", !t.chat().querySelector(".push-prompt"));
  t = bootPush(); authed(t); await settle();
  t.type("what's 2+2"); t.key(t.box(), { key: "Enter" }); t.say(t.sockets[0], { type: "final", text: "4" });
  check("push: no offer unless a reminder was actually set", !t.chat().querySelector(".push-prompt"));

  // 9. no double notification: the service worker shows it, so the page must not
  const note = { id: 1, kind: "reminder", title: "Reminder", body: "Stretch", created_at: new Date().toISOString() };
  // The notification becomes visible on a LATER poll (the page polls every 15 s), after the push state is known.
  const fallbackCount = async (state, { duringLoad = false } = {}) => {
    const gate = { open: duringLoad };
    const tt = bootPush({ ...state, routes: { "GET /api/notifications": () => ({ notifications: gate.open ? [note] : [] }) } });
    Object.defineProperty(tt.w.document, "hidden", { get: () => true, configurable: true });
    authed(tt); await settle();
    gate.open = true;
    await tt.w.pollNotifications(); await settle();
    return tt.pushLog.pageNotifications.length;
  };
  check("push: push ON + tab in background => the page shows NO second notification", (await fallbackCount({ push: { permission: "granted", existing: existing(SERVER_KEY) } })) === 0);
  check("push: granted but not subscribed + background tab => in-page fallback still works", (await fallbackCount({ push: { permission: "granted" } })) === 1);
  check("push: a notification already present at load (state unknown) is never duplicated", (await (async () => {
    const tt = bootPush({ push: { permission: "granted", existing: existing(SERVER_KEY) }, routes: { "GET /api/notifications": { notifications: [note] } } });
    Object.defineProperty(tt.w.document, "hidden", { get: () => true, configurable: true });
    authed(tt); await settle(); return tt.pushLog.pageNotifications.length; })()) === 0);
  check("push: not granted => no notification attempt at all", (await fallbackCount({ push: { permission: "default" } })) === 0);

  // 10. tapping a notification while the app is open
  t = bootPush({ drawer: true, sw: true }); authed(t); await settle();
  check("push: a notification tap (message from the service worker) opens the Today drawer", (t.pushLog.swMessage({ type: "open-panel", panel: "today" }), t.$("app").dataset.panel === "open" && t.$("tab-today").getAttribute("aria-selected") === "true"));

  // ═══════════════ Focus is kept when the Today panel re-renders ═══════════════
  const inCard = (tt) => !!tt.w.document.activeElement.closest && !!tt.w.document.activeElement.closest(".push-card");
  t = bootPush(); authed(t); await settle();
  let btn = t.$("panel-today").querySelector(".push-card .wide-btn"); btn.focus();
  btn.click(); await settle();
  check("focus: after 'Turn on notifications' the keyboard focus stays inside the card (not lost to <body>)", inCard(t), t.w.document.activeElement.tagName + "." + t.w.document.activeElement.className);
  check("focus: ...on a real control", t.w.document.activeElement.tagName === "BUTTON" && /Send a test|Turn off/.test(t.w.document.activeElement.textContent));
  t.w.document.activeElement.click(); await settle();     // 'Send a test'
  check("focus: after 'Send a test' focus is still in the card", inCard(t));
  const refresh = [...t.$("panel-today").querySelectorAll("button")].find((b) => b.textContent === "Refresh"); refresh.focus(); refresh.click(); await settle();
  check("focus: the Refresh button keeps focus after the panel is rebuilt", t.w.document.activeElement.textContent === "Refresh" && t.w.document.activeElement.isConnected);
  t = bootPush(); authed(t); await settle();
  t.w.document.body.focus();
  t.w.eval("pushRefresh = pushRefresh"); t.w.TapanApp.push.checkedAt = 0; await t.w.pushRefresh(); await settle();
  check("focus: a background re-render never steals focus the user did not have there", t.w.document.activeElement === t.w.document.body || !t.$("panel-today").contains(t.w.document.activeElement));

  // ═══════════════ Weather card in the Today panel ═══════════════
  const wxBoot = async (brief, opts = {}) => { const tt = boot({ drawer: opts.drawer, routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": brief } }); authed(tt); await wait(60); return tt; };
  let wx = await wxBoot({ weather: "Surat, Gujarat, India: now 27.8°C (feels 27.9°C), clear sky\n2026-11-24: 20–31°C", home_location: "Surat, Gujarat, India" });
  check("weather: the forecast line is shown, only the first line", /Surat, Gujarat, India: now 27\.8°C/.test(wx.$("panel-today").textContent) && !/2026-11-24/.test(wx.$("panel-today").textContent));
  wx = await wxBoot({ home_location: null });
  check("weather: no city set => an explanation instead of silence", /tell Tapan which city you live in/.test(wx.$("panel-today").textContent) && !!wx.$("panel-today").querySelector(".weather button"));
  wx = await wxBoot({ home_location: "Surat", weather_error: "The weather service is busy or unreachable right now. Try again in a minute." });
  check("weather: a service outage is explained", /Weather unavailable\. The weather service is busy/.test(wx.$("panel-today").textContent));
  check("weather: ...and no pointless 'Set my city' button for an outage", !wx.$("panel-today").querySelector(".weather button"));
  wx = await wxBoot({ home_location: null, weather_error: "I couldn’t find a place called “home”. Try just the city, like “Surat”." });
  check("weather: an unresolvable configured city offers to fix it", /couldn’t find a place/.test(wx.$("panel-today").textContent) && !!wx.$("panel-today").querySelector(".weather button"));
  wx.$("panel-today").querySelector(".weather button").click();
  check("weather: 'Set my city' pre-fills the message box for the user to finish", wx.box().value === "My city is " && wx.w.document.activeElement === wx.box());
  wx = await wxBoot({});
  check("weather: an old server without the new fields shows nothing odd", !wx.$("panel-today").querySelector(".weather") || /tell Tapan/.test(wx.$("panel-today").textContent) === false);
  wx = await wxBoot({ home_location: "Surat", weather: "Surat: now 28°C" });
  check("panel: 'Nothing scheduled' still appears when only cards (no real content) are present", /Nothing scheduled/.test(wx.$("panel-today").textContent));
  wx = await wxBoot({ home_location: "Surat", open_tasks: [{ id: 1, title: "Write report", priority: "normal" }] });
  check("panel: ...and not when there is real content", !/Nothing scheduled/.test(wx.$("panel-today").textContent));

  // ═══════════════ Milestone 0: staying current, reporting in, Settings > Status ═══════════════
  const diag = (over = {}) => ({
    server: { version: "abc1234", web_version: "build-new", uptime_s: 4000, environment: "prod", database: "postgres", python: "3.12", now: "2026-11-24T10:00:00+00:00", timezone: "Asia/Kolkata" },
    llm: { provider: "openrouter", model: "anthropic/claude-haiku-5.5", calls: 9, ok: 8, failed: 1, last_ok_at: new Date().toISOString(), last_provider: "openrouter", last_error: null },
    scheduler: { ticks: 50, last_tick_at: new Date().toISOString(), fired_total: 3, errors: 0, last_error: null, poll_seconds: 20, pending: 2, overdue_pending: 0, next_due: "2026-11-24T19:00+05:30" },
    push: { enabled: true, devices: [] }, home_location: "Surat, Gujarat, India", home_location_error: null, clients: [], ...over,
  });
  const m0Routes = (over = {}) => ({ "GET /api/history": { messages: [] }, "GET /api/briefing": {}, "POST /api/client-report": { ok: true },
    "GET /health": { web_version: "build-new" }, "GET /api/diagnostics": diag(), ...over });

  // 1. update banner
  let u = boot({ version: "build-old", routes: m0Routes() }); authed(u); await wait(80);
  check("update: a page older than the server shows the Reload banner", !u.$("update-banner").classList.contains("hidden"));
  check("update: ...announced for screen readers", /new version/i.test(u.$("sr-status").textContent));
  check("update: the banner has a real, labelled button", u.$("update-reload").tagName === "BUTTON" && /Reload/.test(u.$("update-reload").textContent));
  let reloaded = 0; u.w.TapanHost.reload = () => { reloaded++; };
  u.$("update-reload").click(); await wait(30);
  check("update: Reload asks the browser to reload", reloaded === 1);
  u = boot({ version: "build-new", routes: m0Routes() }); authed(u); await wait(80);
  check("update: an up-to-date page shows no banner", u.$("update-banner").classList.contains("hidden"));
  u = boot({ routes: m0Routes() }); authed(u); await wait(80);
  check("update: a development build (no injected hash) never nags", u.$("update-banner").classList.contains("hidden"));
  u = boot({ version: "build-old", routes: m0Routes({ "GET /health": { status: 503, body: {} } }) }); authed(u); await wait(80);
  check("update: a failing /health is ignored (no banner, no crash)", u.$("update-banner").classList.contains("hidden"));
  u = boot({ version: "build-old", routes: m0Routes({ "GET /health": { app: "x" } }) }); authed(u); await wait(80);
  check("update: a /health without a version is ignored", u.$("update-banner").classList.contains("hidden"));
  u = boot({ version: "build-new", routes: m0Routes() }); authed(u); await wait(80);
  u.w.TapanHost.checkForUpdate(true); await wait(40);
  check("update: 'Check for update' confirms when current", /latest version/.test(u.$("toast").textContent));
  // coming back to the app triggers a check
  u = boot({ version: "build-old", routes: m0Routes({ "GET /health": { web_version: "build-old" } }) }); authed(u); await wait(80);
  const healthCalls = () => u.calls.filter((c) => c.url === "/health").length;
  const healthBefore = healthCalls();
  u.w.document.dispatchEvent(new u.w.Event("visibilitychange")); await wait(30);
  check("update: returning to the app re-checks for a new version", healthCalls() > healthBefore);

  // 2. what this page tells the server
  u = boot({ version: "build-old", ua: ANDROID, standalone: true, push: { permission: "default" }, routes: pushRoutes(m0Routes()) }); authed(u); await wait(2900);
  const rep = u.calls.filter((c) => c.method === "POST" && c.url === "/api/client-report");
  check("report: a page reports itself once it is signed in", rep.length >= 1);
  const body = JSON.parse(rep[rep.length - 1].body);
  check("report: carries build, install state, push state, permission and service worker state",
    body.web_version === "build-old" && body.standalone === true && body.push.permission === "default" && ["off", "on"].includes(body.push.status) && body.sw.supported === true && /Android/.test(body.ua));
  check("report: device id is well-formed (server requires 6-40 chars of [A-Za-z0-9-])", /^[A-Za-z0-9-]{6,40}$/.test(body.device) && u.w.localStorage.getItem("tapan.device") === body.device);
  const again = boot({ version: "build-old", storage: { "tapan.device": body.device }, routes: m0Routes() }); authed(again); await wait(2900);
  check("report: the same device keeps the same id across visits", JSON.parse(again.calls.filter((c) => c.url === "/api/client-report").pop().body).device === body.device);
  const locked = boot({ routes: m0Routes() }); locked.open(locked.sockets[0]); locked.close(locked.sockets[0], 4401); await wait(2900);
  check("report: nothing is sent while locked", !locked.calls.some((c) => c.url === "/api/client-report"));
  u = boot({ version: "dev-check", routes: m0Routes({ "POST /api/client-report": { status: 500, body: {} } }) }); authed(u); await wait(2900);
  check("report: a failing report endpoint never disturbs the app", u.pill().dataset.state === "online");

  // 3. Settings > Status
  u = boot({ drawer: true, version: "build-new", routes: m0Routes({ "GET /api/diagnostics": diag({ clients: [
      { device: "other-device-1", ua_short: "Android 14 · Chrome 130", reported_at: new Date().toISOString(), current_build: false, web_version: "old0000", standalone: false, push: { status: "unsupported", permission: "default", issue: "unsupported" } }] }) }) });
  authed(u); await wait(60);
  u.$("today-btn").click(); await wait(30);
  u.$("tab-settings").click(); await wait(120);
  check("settings: the Settings tab is selected and its panel visible", u.$("tab-settings").getAttribute("aria-selected") === "true" && !u.$("panel-settings").classList.contains("hidden") && u.$("panel-today").classList.contains("hidden"));
  const st = u.$("panel-settings").textContent;
  check("settings: Status is open by default with the server facts", /Status/.test(st) && /postgres/.test(st) && /Surat, Gujarat, India/.test(st) && /web build-new/.test(st));
  check("settings: shows scheduler health", /Scheduler last ran/.test(st) && /Next due/.test(st) && /2026-11-24T19:00\+05:30/.test(st));
  check("settings: says when no device is registered for push", /No device is registered for push yet/.test(st));
  check("settings: shows other devices and flags an old build and the exact push state", /Android 14 · Chrome 130/.test(st) && /old \(old0000\)/.test(st) && /unsupported · permission default/.test(st));
  check("settings: shows the AI provider and failures", /openrouter · anthropic\/claude-haiku-5\.5/.test(st) && /9 · 8 · 1/.test(st));
  check("settings: the device section reports this page's own push state", /Push notifications/.test(st) && /Notification permission/.test(st) && /Installed as an app/.test(st));
  const rows = u.$("panel-settings").querySelectorAll("dd.bad");
  check("settings: problems are marked (colour is never the only cue: the words say it too)", rows.length >= 1 && /No device|old \(|never|\d/.test(rows[0].textContent + st));
  const copyBtn = [...u.$("panel-settings").querySelectorAll("button")].find((b) => b.textContent === "Copy report");
  let copied = ""; Object.defineProperty(u.w.navigator, "clipboard", { value: { writeText: async (t) => { copied = t; } }, configurable: true });
  copyBtn.click(); await wait(30);
  check("settings: 'Copy report' puts a JSON report on the clipboard for support", copied.startsWith("{") && JSON.parse(copied).server.server.web_version === "build-new");
  check("settings: every button in the tab is a real, named button", [...u.$("panel-settings").querySelectorAll("button")].every((b) => b.textContent.trim().length > 0));
  u.key(u.$("tab-history"), { key: "ArrowRight" });
  check("settings: arrow keys step to Money, then Settings", u.$("tab-money").getAttribute("aria-selected") === "true" && u.$("tab-money").tabIndex === 0 && u.$("tab-today").tabIndex === -1);
  check("settings: ...then Work and Growth, and Settings is the last of the six tabs", (() => {
    u.key(u.$("tab-money"), { key: "ArrowRight" });
    const work = u.$("tab-work").getAttribute("aria-selected") === "true" && !u.$("panel-work").classList.contains("hidden");
    u.key(u.$("tab-work"), { key: "ArrowRight" });
    const growth = u.$("tab-growth").getAttribute("aria-selected") === "true" && !u.$("panel-growth").classList.contains("hidden");
    u.key(u.$("tab-growth"), { key: "ArrowRight" });
    return work && growth && u.$("tab-settings").getAttribute("aria-selected") === "true" && u.$("tab-settings").tabIndex === 0;
  })());
  u.key(u.$("tab-settings"), { key: "ArrowRight" });
  check("settings: ...and wrap around to the first", u.$("tab-today").getAttribute("aria-selected") === "true");
  const deep = boot({ drawer: true, url: "https://tapan.example.com/web/index.html?panel=settings", routes: m0Routes() }); await wait(40);
  check("settings: a ?panel=settings link opens the Settings tab", deep.$("app").dataset.panel === "open" && deep.$("tab-settings").getAttribute("aria-selected") === "true");
  const sick = boot({ drawer: true, routes: m0Routes({ "GET /api/diagnostics": { status: 500, body: {} } }) }); authed(sick); await wait(40);
  sick.$("today-btn").click(); sick.$("tab-settings").click(); await wait(120);
  check("settings: a failing diagnostics call is explained, not blank", /Could not load this section/.test(sick.$("panel-settings").textContent));

  // ═══════════════ Settings > Telegram ═══════════════
  const TOKEN = "123456789:" + "A".repeat(35); // obviously fake, built at runtime so secret scanners stay quiet
  const tgState = (over = {}) => ({ configured: false, from_env: false, bot: null, linked: false, linked_name: null, sent: 0, received: 0, last_sent_at: null, last_error: null, ...over });
  const openTelegram = async (routes, opts = {}) => {
    const tt = boot({ drawer: true, ...opts, routes: m0Routes(routes) });
    authed(tt); await wait(60);
    tt.w.confirm = opts.confirm === undefined ? () => true : opts.confirm;
    tt.$("today-btn").click(); tt.$("tab-settings").click(); await wait(120);
    const section = [...tt.$("panel-settings").querySelectorAll("details")].find((d) => d.dataset.id === "telegram");
    section.open = true; section.dispatchEvent(new tt.w.Event("toggle")); await wait(120);
    tt.tg = section.querySelector(".set-body");
    return tt;
  };

  let tt = await openTelegram({ "GET /api/telegram/status": tgState() });
  check("telegram: a section exists in Settings", !!tt.tg);
  check("telegram: not set up => plain instructions and a hidden token field", /@BotFather/.test(tt.tg.textContent) && /\/newbot/.test(tt.tg.textContent) && tt.tg.querySelector("input").type === "password" && tt.tg.querySelector("input").autocomplete === "off");
  check("telegram: the token field has a visible label", /Bot token/.test(tt.tg.querySelector("label").textContent));

  tt = await openTelegram({ "GET /api/telegram/status": tgState(), "POST /api/telegram/token": { status: 400, body: { detail: "That does not look like a bot token." } } });
  tt.tg.querySelector("input").value = "nonsense"; tt.tg.querySelector("button.wide-btn").click(); await wait(80);
  check("telegram: ...with the reason shown inline (not a generic error)", /does not look like a bot token/.test(tt.tg.textContent) && tt.tg.querySelector(".set-note.bad"));
  check("telegram: ...and the button is usable again", !tt.tg.querySelector("button.wide-btn").disabled);

  tt = await openTelegram({ "GET /api/telegram/status": tgState(), "POST /api/telegram/token": { status: 429, body: {} } });
  tt.tg.querySelector("input").value = TOKEN; tt.tg.querySelector("button.wide-btn").click(); await wait(80);
  check("telegram: rate limiting says to wait", /Wait a minute/.test(tt.tg.textContent));

  let configured = false;
  tt = await openTelegram({ "GET /api/telegram/status": () => (configured ? tgState({ configured: true, bot: "tapan_bot" }) : tgState()),
    "POST /api/telegram/token": () => { configured = true; return { ok: true, bot: "tapan_bot", webhook: true }; } });
  tt.tg.querySelector("input").value = TOKEN; tt.tg.querySelector("button.wide-btn").click(); await wait(120);
  const sentToken = tt.calls.find((c) => c.url === "/api/telegram/token" && c.method === "POST");
  check("telegram: connecting posts the pasted token", sentToken && JSON.parse(sentToken.body).token === TOKEN);
  check("telegram: ...announces the bot and moves on to linking", /Connected to @tapan_bot/.test(tt.$("toast").textContent) && /@tapan_bot/.test(tt.tg.textContent) && /Link my Telegram/.test(tt.tg.textContent));
  check("telegram: the token is never shown again after it is saved", !tt.$("panel-settings").textContent.includes(TOKEN) && !tt.$("panel-settings").innerHTML.includes(TOKEN));

  tt = await openTelegram({ "GET /api/telegram/status": tgState({ configured: true, bot: "tapan_bot" }),
    "POST /api/telegram/pair": { code: "ABCD2345", bot: "tapan_bot", link: "https://t.me/tapan_bot?start=ABCD2345", expires_in: 600, webhook: false, webhook_error: "Telegram needs a public https:// address." } });
  tt.tg.querySelector("button.wide-btn").click(); await wait(80);
  const open = tt.tg.querySelector("a.wide-btn");
  check("telegram: linking offers a deep link that opens Telegram safely", open && open.href === "https://t.me/tapan_bot?start=ABCD2345" && open.rel.includes("noopener") && open.target === "_blank");
  check("telegram: ...plus the code to type by hand and its lifetime", /\/start ABCD2345/.test(tt.tg.textContent) && /expires in 10 minutes/.test(tt.tg.textContent));
  check("telegram: a webhook problem is reported, not hidden", /public https/.test(tt.tg.textContent));

  let linkedNow = false;
  tt = await openTelegram({ "GET /api/telegram/status": () => tgState({ configured: true, bot: "tapan_bot", linked: linkedNow, linked_name: linkedNow ? "Tapan K" : null }),
    "POST /api/telegram/pair": () => { setTimeout(() => { linkedNow = true; }, 500); return { code: "ZZZZ2222", bot: "tapan_bot", link: "https://t.me/tapan_bot?start=ZZZZ2222", expires_in: 600, webhook: true }; } });
  tt.tg.querySelector("button.wide-btn").click(); await wait(3600);
  check("telegram: the section notices by itself when the chat gets linked", /linked to Tapan K/.test(tt.tg.textContent) && /Telegram linked/.test(tt.$("toast").textContent));

  tt = await openTelegram({ "GET /api/telegram/status": tgState({ configured: true, bot: "tapan_bot", linked: true, linked_name: "Tapan K", sent: 4, received: 2, last_error: "Forbidden: bot was blocked by the user" }),
    "POST /api/telegram/test": { ok: true }, "POST /api/telegram/unlink": { ok: true }, "DELETE /api/telegram/token": { ok: true } });
  check("telegram: linked state shows the chat, counters and the last error", /linked to Tapan K/.test(tt.tg.textContent) && /4 · 2/.test(tt.tg.textContent) && /blocked by the user/.test(tt.tg.textContent));
  [...tt.tg.querySelectorAll("button")].find((b) => b.textContent === "Send test message").click(); await wait(60);
  check("telegram: 'Send test message' posts and confirms", tt.calls.some((c) => c.url === "/api/telegram/test") && /Test sent/.test(tt.$("toast").textContent));
  [...tt.tg.querySelectorAll("button")].find((b) => b.textContent === "Unlink").click(); await wait(60);
  check("telegram: 'Unlink' posts", tt.calls.some((c) => c.url === "/api/telegram/unlink"));
  const refused = await openTelegram({ "GET /api/telegram/status": tgState({ configured: true, bot: "tapan_bot", linked: true, linked_name: "T" }), "DELETE /api/telegram/token": { ok: true } }, { confirm: () => false });
  [...refused.tg.querySelectorAll("button")].find((b) => b.textContent === "Remove bot").click(); await wait(60);
  check("telegram: 'Remove bot' asks first and does nothing if you decline", !refused.calls.some((c) => c.method === "DELETE" && c.url === "/api/telegram/token"));
  [...tt.tg.querySelectorAll("button")].find((b) => b.textContent === "Remove bot").click(); await wait(60);
  check("telegram: ...and removes it when you agree", tt.calls.some((c) => c.method === "DELETE" && c.url === "/api/telegram/token"));
  check("telegram: every control is a labelled button, link or input", [...tt.tg.querySelectorAll("button")].every((b) => b.textContent.trim()));

  // ═══════════════ Recurring reminders in the Today panel ═══════════════
  const recBrief = { home_location: "Surat", reminders_today: [{ id: 7, title: "Take vitamins", due_at: new Date(Date.now() + 3600e3).toISOString(), repeats: "every day" }],
    upcoming_reminders: [{ id: 8, title: "Dentist", due_at: "2026-12-30T10:30:00+05:30", repeats: null }] };
  let rr = boot({ routes: { "GET /api/history": { messages: [] }, "GET /api/briefing": recBrief, "DELETE /api/reminders/": { ok: true } } }); authed(rr); await wait(80);
  check("recurring: the Today list says a reminder repeats, in words", /Take vitamins/.test(rr.$("panel-today").textContent) && /repeats every day/.test(rr.$("panel-today").textContent));
  check("recurring: one-off reminders say nothing extra", (rr.$("panel-today").textContent.match(/repeats/g) || []).length === 1);
  check("recurring: the cancel button warns that it ends the whole series", !!rr.$("panel-today").querySelector('button[aria-label="Stop repeating reminder: Take vitamins (ends the whole series)"]'));
  check("recurring: one-off cancel keeps its simple label", !!rr.$("panel-today").querySelector('button[aria-label="Cancel reminder: Dentist"]'));

  // ═══════════════ Money tab (payments, EMIs, banks, advice) ═══════════════
  const mkEmi = (id, seq, amount, due, status, extra = {}) => ({ id, seq, amount_minor: amount, due_date: due, paid_at: status === "paid" ? "2026-11-20T10:00:00+00:00" : null, status, deducted: false, ...extra });
  function moneySnap({ payments, banks, insights } = {}) {
    const bank = { id: 7, name: "HDFC", balance_minor: 1000000, note: "", due_30_minor: 600000, shortfall_minor: 0 };
    const pay = payments || [{ id: 3, title: "Car loan", category: "loan", notes: "", bank_id: 7, total_minor: 900000, due_day: 5, remind_days: 1, emi_count: 3, paid_count: 1,
      paid_minor: 300000, planned_minor: 900000, remaining_minor: 600000, mismatch_minor: 0, next_due: "2026-12-05", finished: false,
      emis: [mkEmi(11, 1, 300000, "2026-11-05", "paid"), mkEmi(12, 2, 300000, "2026-12-05", "upcoming"), mkEmi(13, 3, 300000, "2027-01-05", "upcoming")] }];
    return { currency: "INR", categories: ["loan", "card", "other"], banks: banks || [bank],
      insights: insights || [{ level: "warn", text: "1 EMI(s) worth ₹3,000 are overdue." }, { level: "good", text: "At this schedule your last EMI is on 2027-01-05." }],
      payments: pay,
      overview: { today: "2026-11-24", payments: pay.length, active_payments: pay.length, planned_minor: 900000, paid_minor: 300000, remaining_minor: pay.length ? 600000 : 0,
        overdue: { count: pay.length ? 1 : 0, amount_minor: pay.length ? 300000 : 0 }, due_7: { count: 0, amount_minor: 0 }, due_30: { count: 1, amount_minor: 300000 }, this_month: { count: 0, amount_minor: 0 },
        next: pay.length ? { payment: "Car loan", payment_id: 3, emi_id: 12, seq: 2, of: 3, due_date: "2026-12-05", amount_minor: 300000 } : null, free_by: pay.length ? "2027-01-05" : null,
        months: pay.length ? [{ month: "2026-12", amount_minor: 300000, count: 1 }, { month: "2027-01", amount_minor: 300000, count: 1 }] : [],
        banks: banks ? banks.map((b) => ({ due_30_minor: 0, shortfall_minor: 0, ...b })) : [bank], unassigned_due_minor: 0, balance_minor: 1000000 } };
  }
  function moneyBoot(snapOpts, extraRoutes = {}) {
    const state = { snap: moneySnap(snapOpts || undefined) };
    const holder = {};
    const lastBody = () => { const writes = holder.t.calls.filter((c) => c.method !== "GET"); return JSON.parse(writes[writes.length - 1].body || "{}"); };
    const routes = m0Routes({
      "GET /api/expenses": () => state.snap,
      "PATCH /api/expenses/emis/": () => { const b = lastBody(); if (b.paid !== undefined) state.snap.payments[0].emis.forEach((e) => { if (holder.t.calls[holder.t.calls.length - 1].url.endsWith("/" + e.id)) e.status = b.paid ? "paid" : "upcoming"; }); return state.snap.payments[0]; },
      "POST /api/expenses/payments": () => ({ id: 99 }),
      "POST /api/expenses/banks": () => ({ id: 8 }),
      "DELETE /api/expenses/payments/": () => ({ ok: true }),
      "POST /api/expenses/advice": () => state.advice || { insights: [], advice: null, source: "rules" },
      ...extraRoutes,
    });
    const t = boot({ drawer: true, routes }); holder.t = t; authed(t);
    return { t, state, lastBody, calls: (method, prefix) => t.calls.filter((c) => c.method === method && c.url.startsWith(prefix)) };
  }
  const openMoney = async (m, view) => { m.t.$("today-btn").click(); m.t.$("tab-money").click(); await wait(80); if (view) { [...m.t.$("panel-money").querySelectorAll(".mn-nav-btn")].find((b) => b.textContent === view).click(); await wait(10); } };
  const moneyText = (m) => m.t.$("panel-money").textContent;
  const mbtn = (m, label, root) => [...(root || m.t.$("panel-money")).querySelectorAll("button")].find((b) => b.textContent.trim() === label);

  let m = moneyBoot(); await wait(60);
  check("money: there are six tabs and Money sits between History and Work", [...m.t.w.document.querySelectorAll('[role="tab"]')].map((b) => b.textContent).join(",") === "Today,History,Money,Work,Growth,Settings");
  await openMoney(m);
  check("money: the tab opens its panel and hides the others", m.t.$("tab-money").getAttribute("aria-selected") === "true" && !m.t.$("panel-money").classList.contains("hidden") && m.t.$("panel-settings").classList.contains("hidden"));
  check("money: overview asks the server once for everything", m.calls("GET", "/api/expenses").length === 1);
  check("money: overdue, remaining and the next EMI are shown with the currency", /₹3,000/.test(moneyText(m)) && /₹6,000/.test(moneyText(m)) && /Next: Car loan · EMI 2 of 3/.test(moneyText(m)));
  check("money: advice rules say what kind of note they are in words, not only colour", /Needs attention: 1 EMI/.test(moneyText(m)) && /Good news:/.test(moneyText(m)));
  check("money: the month chart has text values, not only bars", /Dec 2026/.test(moneyText(m)) && /₹3,000 · 1/.test(moneyText(m)));
  check("money: the section buttons say which one is selected", m.t.$("panel-money").querySelector('.mn-nav-btn[aria-pressed="true"]').textContent === "Overview");
  mbtn(m, "Mark paid").click(); await wait(60);
  check("money: 'Mark paid' on the next EMI sends a signed-in PATCH with the bank deduction on by default", m.calls("PATCH", "/api/expenses/emis/12").length === 1 && m.lastBody().paid === true && m.lastBody().deduct === true);
  check("money: ...and the screen reloads from the server afterwards", m.calls("GET", "/api/expenses").length === 2);

  // payments
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  check("money: a payment shows progress and what is left", /Car loan/.test(moneyText(m)) && /1 of 3 paid · ₹6,000 left/.test(moneyText(m)));
  const prog = m.t.$("panel-money").querySelector("progress");
  check("money: progress is a real labelled <progress>", prog && prog.max === 3 && prog.value === 1 && /1 of 3 EMIs paid/.test(prog.getAttribute("aria-label")));
  const boxes = [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")];
  check("money: every EMI has a checkbox with a name that says what ticking does", boxes.length === 3 && boxes.every((b) => b.closest("label") && /Car loan, (paid\. Untick|unpaid\. Tick)/.test(b.closest("label").textContent)));
  check("money: the paid EMI is ticked, the others are not", boxes[0].checked && !boxes[1].checked && !boxes[2].checked);
  check("money: each EMI shows amount and due state in words", /EMI 2 of 3 · ₹3,000/.test(moneyText(m)) && /Due in 11 days/.test(moneyText(m)) && /Paid /.test(moneyText(m)));
  const tick1 = m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")[1]; tick1.focus(); tick1.click(); await wait(60);
  check("money: ticking an EMI marks it paid and reduces the bank (default)", m.calls("PATCH", "/api/expenses/emis/12").length === 1 && m.lastBody().paid === true && m.lastBody().deduct === true);
  const afterTick = m.t.w.document.activeElement;
  check("money: keyboard focus survives the repaint (same EMI checkbox)", afterTick && afterTick.dataset.fk === "emi:12", afterTick && afterTick.dataset.fk);
  m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")[1].click(); await wait(60);
  check("money: unticking sends paid:false and never asks to deduct", m.lastBody().paid === false && m.lastBody().deduct === false);
  const pref = m.t.$("panel-money").querySelector(".mn-pref input");
  pref.click();
  m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")[2].click(); await wait(60);
  check("money: switching the deduction preference off is respected and remembered", m.lastBody().deduct === false && m.t.w.localStorage.getItem("tapan.money.deduct") === "0");

  // double tap
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  const dbl = m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")[1];
  dbl.click(); dbl.click(); await wait(80);
  check("money: a double tap sends one request, not two", m.calls("PATCH", "/api/expenses/emis/12").length === 1);

  // edit an EMI
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  mbtn(m, "Edit", m.t.$("panel-money").querySelectorAll(".mn-emi")[1]).click(); await wait(10);
  const emiForm = m.t.$("panel-money").querySelector(".mn-emi-form");
  check("money: Edit opens an inline form prefilled with the EMI's amount and date", emiForm && emiForm.querySelector('input[name="amount"]').value === "3000" && emiForm.querySelector('input[name="due_date"]').value === "2026-12-05");
  check("money: focus moves into the form's first field", m.t.w.document.activeElement.dataset.fk === "edit-emi:12:amount");
  const amt = emiForm.querySelector('input[name="amount"]'); amt.value = "3,500.50"; amt.dispatchEvent(new m.t.w.Event("input", { bubbles: true }));
  emiForm.dispatchEvent(new m.t.w.Event("submit", { bubbles: true, cancelable: true })); await wait(60);
  check("money: saving sends exactly what was typed (the server does the money maths)", m.calls("PATCH", "/api/expenses/emis/12").length === 1 && m.lastBody().amount === "3,500.50" && m.lastBody().due_date === "2026-12-05");
  check("money: the form closes after a successful save", !m.t.$("panel-money").querySelector(".mn-emi-form"));

  // paid EMI cannot be edited
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  mbtn(m, "Edit", m.t.$("panel-money").querySelectorAll(".mn-emi")[0]).click(); await wait(10);
  const lockedForm = m.t.$("panel-money").querySelector(".mn-emi-form");
  check("money: a paid EMI's fields are disabled and say why", [...lockedForm.querySelectorAll("input")].every((i) => i.disabled) && /Untick it first/.test(lockedForm.textContent) && !mbtn(m, "Save EMI", lockedForm));

  // add a payment
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  mbtn(m, "+ Add payment").click(); await wait(10);
  const addForm = m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]');
  check("money: the add form has labelled fields for title, total, EMIs, first date, day, bank, type, reminder, notes", addForm && ["title", "total", "emis", "first_due", "day", "bank_id", "category", "remind", "notes"].every((n) => { const el = addForm.querySelector(`[name="${n}"]`); return el && el.closest("label"); }));
  check("money: focus starts in the title field", m.t.w.document.activeElement.dataset.fk === "add-payment:title");
  const set = (name, value) => { const el = addForm.querySelector(`[name="${name}"]`); el.value = value; el.dispatchEvent(new m.t.w.Event("input", { bubbles: true })); };
  set("title", "Phone"); set("total", "24000"); set("emis", "6");
  check("money: a live preview shows the approximate EMI", /About ₹4,000 per EMI/.test(addForm.textContent));
  // repaint while the form is open (an EMI tick elsewhere) must not eat what was typed
  m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")[1].click(); await wait(60);
  check("money: typed text survives a repaint", m.t.$("panel-money").querySelector('[name="title"]').value === "Phone" && m.t.$("panel-money").querySelector('[name="total"]').value === "24000");
  const addForm2 = m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]');
  addForm2.dispatchEvent(new m.t.w.Event("submit", { bubbles: true, cancelable: true })); await wait(60);
  const created = m.calls("POST", "/api/expenses/payments")[0];
  const createdBody = JSON.parse(created.body);
  check("money: creating sends title, total, EMIs, date and reminder as the server expects", createdBody.title === "Phone" && createdBody.total === "24000" && createdBody.emis === 6 && /^\d{4}-\d\d-\d\d$/.test(createdBody.first_due) && createdBody.remind_days === 1 && createdBody.bank_id === null && createdBody.day === null);
  check("money: the form closes and the draft is cleared on success", !m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]'));

  // server-side validation keeps the form and explains
  m = moneyBoot(null, { "POST /api/expenses/payments": { status: 400, body: { detail: "That total is too small to split into so many EMIs." } } }); await wait(60); await openMoney(m, "Payments");
  mbtn(m, "+ Add payment").click(); await wait(10);
  const bad = m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]');
  bad.dispatchEvent(new m.t.w.Event("submit", { bubbles: true, cancelable: true })); await wait(60);
  check("money: a rejected form stays open and the reason is shown and announced", m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]') && /too small to split/.test(m.t.$("toast").textContent) && /too small/.test(m.t.$("sr-status").textContent));

  // delete needs two taps
  m = moneyBoot(); await wait(60); await openMoney(m, "Payments");
  m.t.$("panel-money").querySelector("details.mn-pay").open = true;
  mbtn(m, "Delete", m.t.$("panel-money").querySelector(".mn-pay-body")).click(); await wait(10);
  check("money: the first tap on Delete only asks for confirmation", m.calls("DELETE", "/api/expenses/payments/").length === 0 && !!mbtn(m, "Tap again to delete"));
  check("money: the armed button's accessible name says what will be lost", /removes Car loan and all its EMIs/i.test(mbtn(m, "Tap again to delete").getAttribute("aria-label")));
  check("money: focus stays on the armed button", m.t.w.document.activeElement.dataset.fk === "danger:pay:3");
  mbtn(m, "Tap again to delete").click(); await wait(60);
  check("money: the second tap deletes", m.calls("DELETE", "/api/expenses/payments/3").length === 1);

  // mismatch -> rebalance
  const mism = moneySnap(); mism.payments[0].mismatch_minor = -100000;
  m = moneyBoot(); m.state.snap = mism; await wait(60); await openMoney(m, "Payments");
  check("money: when EMIs do not add up to the total it says by how much", /EMIs add up to ₹1,000 less than the total/.test(moneyText(m)));
  m.t.$("panel-money").querySelector("details.mn-pay").open = true;
  mbtn(m, "Spread the rest evenly").click(); await wait(60);
  check("money: 'Spread the rest evenly' calls rebalance", m.calls("POST", "/api/expenses/payments/3/rebalance").length === 1);

  // banks
  const shortBank = { id: 7, name: "HDFC", balance_minor: 100000, note: "salary", due_30_minor: 600000, shortfall_minor: 500000 };
  m = moneyBoot({ banks: [shortBank] }); await wait(60); await openMoney(m, "Banks");
  check("money: a bank shows balance, load and a shortfall in words", /HDFC/.test(moneyText(m)) && /₹1,000/.test(moneyText(m)) && /Short by ₹5,000 for the next 30 days/.test(moneyText(m)) && /1 active payment/.test(moneyText(m)));
  mbtn(m, "+ Add bank").click(); await wait(10);
  const bankForm = m.t.$("panel-money").querySelector('form[aria-label="Add a bank"]');
  const nm = bankForm.querySelector('[name="name"]'); nm.value = "SBI"; nm.dispatchEvent(new m.t.w.Event("input", { bubbles: true }));
  bankForm.dispatchEvent(new m.t.w.Event("submit", { bubbles: true, cancelable: true })); await wait(60);
  check("money: adding a bank posts name, a numeric-safe balance and note", JSON.parse(m.calls("POST", "/api/expenses/banks")[0].body).name === "SBI" && JSON.parse(m.calls("POST", "/api/expenses/banks")[0].body).balance === 0);

  // AI advice
  m = moneyBoot(); m.state.advice = { insights: [], advice: "1. Pay the overdue EMI first.\n2. Move the Dec EMI to your salary bank.", source: "ai" }; await wait(60); await openMoney(m);
  check("money: before asking, the screen says what data would be sent", /sends your payment names, amounts and bank names and balances \(not notes\)/i.test(moneyText(m)));
  mbtn(m, "Get AI advice").click(); await wait(80);
  check("money: AI advice is shown with a 'not professional advice' note", /Pay the overdue EMI first/.test(moneyText(m)) && /not professional financial advice/.test(moneyText(m)));
  check("money: the AI text is rendered as text, never as HTML", !m.t.$("panel-money").querySelector(".mn-advice-text b"));
  m = moneyBoot(); await wait(60); await openMoney(m);
  mbtn(m, "Get AI advice").click(); await wait(80);
  check("money: when the model is unavailable the screen says so instead of staying blank", /AI model is not available/.test(moneyText(m)));
  m = moneyBoot(); m.state.advice = { insights: [], advice: "<img src=x onerror=alert(1)><b>hi</b>", source: "ai" }; await wait(60); await openMoney(m);
  mbtn(m, "Get AI advice").click(); await wait(80);
  check("money: HTML in AI output is shown literally (no injection)", !m.t.$("panel-money").querySelector("img") && /<img src=x/.test(m.t.$("panel-money").querySelector(".mn-advice-text").textContent));

  // empty state
  m = moneyBoot({ payments: [], banks: [], insights: [{ level: "info", text: "Add your first payment" }] }); await wait(60); await openMoney(m);
  check("money: an empty tracker explains itself and offers the first step", /Track what you owe/.test(moneyText(m)) && !!mbtn(m, "Add a payment") && /Add a phone EMI of 24000/.test(moneyText(m)));
  mbtn(m, "Add a payment").click(); await wait(10);
  check("money: the first-step button opens the add form with focus in it", !!m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]') && m.t.w.document.activeElement.dataset.fk === "add-payment:title");

  // failures
  m = moneyBoot(null, { "GET /api/expenses": { status: 500, body: {} } }); await wait(60); await openMoney(m);
  check("money: a failed load says so and offers Try again", /did not work|Check the connection/.test(moneyText(m)) && !!mbtn(m, "Try again"));

  // a11y sweep over all three views
  m = moneyBoot(); await wait(60);
  for (const view of ["Overview", "Payments", "Banks"]) {
    await openMoney(m, view);
    if (view === "Payments") m.t.$("panel-money").querySelectorAll("details.mn-pay").forEach((d) => { d.open = true; });
    const unnamed = [...m.t.$("panel-money").querySelectorAll("button")].filter((b) => !(b.textContent.trim() || b.getAttribute("aria-label")));
    const unlabelled = [...m.t.$("panel-money").querySelectorAll("input, select, textarea")].filter((i) => !(i.closest("label") || i.getAttribute("aria-label")));
    check(`money: ${view} has no unnamed buttons and no unlabelled fields`, unnamed.length === 0 && unlabelled.length === 0, `${unnamed.length}/${unlabelled.length}`);
  }
  check("money: no inline event handlers or innerHTML-style injection anywhere in the script", !/innerHTML|insertAdjacentHTML|outerHTML|onclick=/.test(fs.readFileSync(ROOT + "money.js", "utf8")));


  // ═══════════════ Money v2: queued ticks, payment kinds, auto-total, fixed amounts, bulk paid, groups, spending, subscriptions ═══════════════
  const evt = (m, name) => new m.t.w.Event(name, { bubbles: true, cancelable: true });
  const typeIn = (m, root, name, value) => { const el = root.querySelector(`[name="${name}"]`); el.value = value; el.dispatchEvent(evt(m, "input")); return el; };
  const submitForm = async (m, form) => { form.dispatchEvent(evt(m, "submit")); await wait(80); };
  const fkEl = (m, key) => [...m.t.$("panel-money").querySelectorAll("[data-fk]")].find((n) => n.dataset.fk === key);
  const v2Pay = (over = {}) => ({ id: 3, title: "Car loan", category: "loan", notes: "", bank_id: 7, total_minor: 1200000, due_day: 5, remind_days: 1, kind: "emi", grp: "Home", settled_at: null, open_paid_minor: 0,
    emi_count: 4, paid_count: 0, paid_minor: 0, planned_minor: 1200000, remaining_minor: 1200000, mismatch_minor: 0, next_due: "2026-12-05", finished: false, included: true,
    emis: [mkEmi(21, 1, 300000, "2026-12-05", "upcoming", { custom: false }), mkEmi(22, 2, 300000, "2027-01-05", "upcoming", { custom: false }),
           mkEmi(23, 3, 300000, "2027-02-05", "upcoming", { custom: false }), mkEmi(24, 4, 300000, "2027-03-05", "upcoming", { custom: true })], ...over });
  function moneyBootV2({ pays, spend, subs, groups, excluded, hidden } = {}, specific = {}) {
    const state = { pays: pays || [v2Pay()], delay: 0, spend: spend || null, subs: subs || null };
    const snapNow = () => { const snap = moneySnap({ payments: state.pays }); return { ...snap, payments: state.pays, excluded: excluded || [], hidden: hidden || { payments: 0, overdue: 0 },
      groups: groups || [{ name: "Home", label: "Home", payments: 1, active: 1, remaining_minor: 1200000, due_30_minor: 300000, overdue: 0, included: true }],
      spending: { month: "2026-11", spent_minor: 450000, previous_minor: 300000, projected_minor: 600000, budget_minor: 500000, budget_left_minor: 50000, subs_monthly_minor: 64900, subs_yearly_minor: 778800, subs_active: 1, subs_due_7: 1 },
      overview: { ...snap.overview, open: { count: 0, amount_minor: 0 } } }; };
    state.snap = snapNow;
    const holder = {};
    const lastBody = () => { const writes = holder.t.calls.filter((c) => c.method !== "GET"); return JSON.parse(writes[writes.length - 1].body || "{}"); };
    const slow = (value) => (state.delay ? new Promise((res) => setTimeout(() => res(value), state.delay)) : value);
    const routes = m0Routes({
      ...specific,
      "GET /api/expenses/spending": () => state.spend,
      "GET /api/expenses/subscriptions": () => state.subs,
      "POST /api/expenses/spending": () => ({ id: 1 }), "PATCH /api/expenses/spending/": () => ({ id: 1 }), "DELETE /api/expenses/spending/": () => ({ ok: true }),
      "PUT /api/expenses/budget": () => ({ budget_minor: 100 }),
      "POST /api/expenses/subscriptions": () => ({ id: 5 }), "PATCH /api/expenses/subscriptions/": () => ({ id: 5 }), "DELETE /api/expenses/subscriptions/": () => ({ ok: true }),
      "POST /api/expenses/emis/bulk": () => ({ changed: 2, skipped: 0 }),
      "PATCH /api/expenses/payments/": () => ({ id: 3 }),
      "PATCH /api/expenses/emis/": (url) => { const id = Number(url.split("/").pop()); const b = lastBody(); state.pays.forEach((p) => p.emis.forEach((e) => { if (e.id === id && b.paid !== undefined) { e.status = b.paid ? "paid" : "upcoming"; e.paid_at = b.paid ? "2026-11-24T10:00:00+00:00" : null; } })); return slow({ id }); },
      "GET /api/expenses": () => (state.reloadDelay ? new Promise((res) => setTimeout(() => res(snapNow()), state.reloadDelay)) : snapNow()),
      "POST /api/expenses/payments": () => ({ id: 99 }),
      "POST /api/expenses/banks": () => ({ id: 8 }),
    });
    const t = boot({ drawer: true, routes }); holder.t = t; authed(t);
    return { t, state, lastBody, calls: (method, prefix) => t.calls.filter((c) => c.method === method && c.url.startsWith(prefix)) };
  }
  const openPayCard = (m) => { m.t.$("panel-money").querySelectorAll("details.mn-pay").forEach((d) => { d.open = true; }); };

  // ── the reported bug: ticking several EMIs quickly dropped all but the first ──
  m = moneyBootV2(); m.state.delay = 60; await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  const ticks = () => [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")];
  const getsBefore = m.calls("GET", "/api/expenses").length;
  ticks()[0].click(); ticks()[1].click(); ticks()[2].click();
  await wait(60 * 3 + 200);
  const patches = m.calls("PATCH", "/api/expenses/emis/");
  check("money v2: ticking three EMIs in a row sends three requests, one per EMI, in the order ticked", patches.length === 3 && patches.map((c) => c.url.split("/").pop()).join(",") === "21,22,23");
  check("money v2: ...every one says paid", patches.every((c) => JSON.parse(c.body).paid === true));
  check("money v2: ...the screen ends with all three ticked, from the server's truth", ticks().slice(0, 3).every((b) => b.checked) && !ticks()[3].checked);
  check("money v2: ...and reloads once after the last save, not after each", m.calls("GET", "/api/expenses").length === getsBefore + 1, `${m.calls("GET", "/api/expenses").length - getsBefore}`);
  m = moneyBootV2(); m.state.delay = 80; await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  const one = [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")][0];
  one.click(); one.click(); await wait(300);
  check("money v2: a second tap on the same EMI while it is still saving is ignored", m.calls("PATCH", "/api/expenses/emis/21").length === 1);

  // ── add a payment: kinds ──
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); mbtn(m, "+ Add payment").click(); await wait(10);
  let af = () => m.t.$("panel-money").querySelector('form[aria-label="Add a payment"]');
  check("money v2: the form starts as EMIs and offers all three kinds in plain words", af().querySelector('[name="kind"]').value === "emi" && [...af().querySelectorAll('[name="kind"] option')].map((o) => o.value).join(",") === "emi,due,open" && /No due date \(I pay when I can\)/.test(af().textContent));
  const kindSel = af().querySelector('[name="kind"]'); kindSel.value = "due"; kindSel.dispatchEvent(evt(m, "input")); await wait(10);
  check("money v2: a one-off due asks for the amount due and a date, not a number of EMIs", !!af().querySelector('[name="emi_amount"]') && !!af().querySelector('[name="first_due"]') && !af().querySelector('[name="emis"]') && /minimum due/.test(af().textContent));
  typeIn(m, af(), "title", "Card bill"); typeIn(m, af(), "emi_amount", "1,500"); typeIn(m, af(), "total", "48000");
  await submitForm(m, af());
  let reqBody = JSON.parse(m.calls("POST", "/api/expenses/payments")[0].body);
  check("money v2: creating a one-off sends kind, amount due, outstanding total and date", reqBody.kind === "due" && reqBody.emi_amount === "1,500" && reqBody.total === "48000" && /^\d{4}-\d\d-\d\d$/.test(reqBody.first_due) && reqBody.emis === undefined);

  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); mbtn(m, "+ Add payment").click(); await wait(10);
  const kindSel2 = af().querySelector('[name="kind"]'); kindSel2.value = "open"; kindSel2.dispatchEvent(evt(m, "input")); await wait(10);
  check("money v2: money owed with no date asks only for the amount: no date, bank or reminder", !!af().querySelector('[name="total"]') && !af().querySelector('[name="first_due"]') && !af().querySelector('[name="bank_id"]') && !af().querySelector('[name="remind"]') && /No date, no reminders/.test(af().textContent));
  typeIn(m, af(), "title", "Owe Rahul"); typeIn(m, af(), "total", "5000"); typeIn(m, af(), "grp", "Personal");
  await submitForm(m, af());
  reqBody = JSON.parse(m.calls("POST", "/api/expenses/payments")[0].body);
  check("money v2: creating an open payment sends kind, total, group and no reminder or bank", reqBody.kind === "open" && reqBody.total === "5000" && reqBody.grp === "Personal" && reqBody.remind_days === null && reqBody.bank_id === null && reqBody.first_due === undefined);

  // ── auto total ──
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); mbtn(m, "+ Add payment").click(); await wait(10);
  typeIn(m, af(), "title", "Phone"); typeIn(m, af(), "emis", "4"); typeIn(m, af(), "total", "12000");
  check("money v2: typing the total fills the amount of each EMI", af().querySelector('[name="emi_amount"]').value === "3000");
  typeIn(m, af(), "emi_amount", "2500");
  check("money v2: typing the amount of each EMI works out the total live", af().querySelector('[name="total"]').value === "10000" && /Total will be ₹10,000 \(4 × ₹2,500\)/.test(af().textContent));
  typeIn(m, af(), "emis", "6");
  check("money v2: changing the number of EMIs keeps the figure you typed last and updates the other", af().querySelector('[name="emi_amount"]').value === "2500" && af().querySelector('[name="total"]').value === "15000");
  await submitForm(m, af());
  reqBody = JSON.parse(m.calls("POST", "/api/expenses/payments")[0].body);
  check("money v2: when the EMI amount drove, only it is sent (the server works out the total exactly)", reqBody.emi_amount === "2500" && reqBody.total === undefined && reqBody.emis === 6 && reqBody.kind === "emi");
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); mbtn(m, "+ Add payment").click(); await wait(10);
  typeIn(m, af(), "title", "T"); typeIn(m, af(), "emis", "3"); typeIn(m, af(), "total", "100"); await submitForm(m, af());
  reqBody = JSON.parse(m.calls("POST", "/api/expenses/payments")[0].body);
  check("money v2: when the total drove, only the total is sent", reqBody.total === "100" && reqBody.emi_amount === undefined);

  // ── groups in the form ──
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); mbtn(m, "+ Add payment").click(); await wait(10);
  const groupInput = af().querySelector('[name="grp"]');
  check("money v2: the group field suggests the groups you already have", groupInput.getAttribute("list") && [...af().querySelectorAll("datalist option")].map((o) => o.value).join(",") === "Home");

  // ── fixed amounts ──
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  const chips = [...m.t.$("panel-money").querySelectorAll(".mn-chip")].filter((c) => c.textContent === "fixed");
  check("money v2: an EMI whose amount you set carries a 'fixed' badge, and screen readers hear it", chips.length === 1 && chips[0].closest(".mn-emi").querySelector(".sr-only").textContent.includes("Amount is fixed"));
  mbtn(m, "Spread equally").click(); await wait(60);
  check("money v2: 'Spread equally' posts a rebalance with no reset", m.calls("POST", "/api/expenses/payments/3/rebalance").length === 1 && (m.calls("POST", "/api/expenses/payments/3/rebalance")[0].body === undefined));
  check("money v2: with a fixed EMI the label says it is kept", /keep it/.test(mbtn(m, "Spread equally").getAttribute("aria-label")));
  openPayCard(m);
  mbtn(m, "Spread over all").click(); await wait(10);
  check("money v2: 'Spread over all' (which replaces fixed amounts) needs a second tap", m.calls("POST", "/api/expenses/payments/3/rebalance").length === 1 && /Tap again to replace fixed amounts/.test(moneyText(m)));
  openPayCard(m); mbtn(m, "Tap again to replace fixed amounts").click(); await wait(60);
  check("money v2: ...and then sends reset:true", m.calls("POST", "/api/expenses/payments/3/rebalance").length === 2 && JSON.parse(m.calls("POST", "/api/expenses/payments/3/rebalance")[1].body).reset === true);

  m = moneyBootV2({ pays: [v2Pay({ mismatch_minor: 50000 })] }); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  check("money v2: the mismatch warning offers to spread and mentions the fixed EMI keeps its amount", /1 EMI with an amount you set keeps it/.test(moneyText(m)) && !!mbtn(m, "Spread the rest evenly"));

  // ── editing an EMI: keep checkbox ──
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  mbtn(m, "Edit", m.t.$("panel-money").querySelectorAll(".mn-emi")[1]).click(); await wait(10);
  let ef = () => m.t.$("panel-money").querySelector(".mn-emi-form");
  const keepBox = () => fkEl(m, "edit-emi:22:keep");
  check("money v2: the EMI form has a 'keep this amount' checkbox, off for an automatic EMI", !!keepBox() && keepBox().checked === false && /Keep this amount when I spread equally/.test(ef().textContent));
  typeIn(m, ef(), "amount", "3500");
  check("money v2: typing a new amount ticks 'keep' by itself, because a typed amount is a fixed one", keepBox().checked === true);
  await submitForm(m, ef());
  check("money v2: saving sends the amount and custom:true", m.lastBody().amount === "3500" && m.lastBody().custom === true);
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  mbtn(m, "Edit", m.t.$("panel-money").querySelectorAll(".mn-emi")[3]).click(); await wait(10);
  check("money v2: a fixed EMI opens with 'keep' already on", fkEl(m, "edit-emi:24:keep").checked === true);
  fkEl(m, "edit-emi:24:keep").click(); await wait(10);
  typeIn(m, m.t.$("panel-money").querySelector(".mn-emi-form"), "amount", "2900");
  check("money v2: once you choose, typing no longer overrides your choice", fkEl(m, "edit-emi:24:keep").checked === false);
  await submitForm(m, m.t.$("panel-money").querySelector(".mn-emi-form"));
  check("money v2: ...and unticked sends custom:false so the EMI rejoins the equal split", m.lastBody().custom === false && m.lastBody().amount === "2900");

  // ── mark several paid ──
  m = moneyBootV2({ pays: [v2Pay({ emis: [mkEmi(21, 1, 300000, "2026-11-01", "overdue", { custom: false }), mkEmi(22, 2, 300000, "2026-11-24", "today", { custom: false }),
      mkEmi(23, 3, 300000, "2027-02-05", "upcoming", { custom: false }), mkEmi(24, 4, 300000, "2027-03-05", "upcoming", { custom: false })] })] });
  await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  mbtn(m, "Mark several paid").click(); await wait(10);
  const panel = () => m.t.$("panel-money").querySelector('[role="group"][aria-label^="Mark several EMIs"]');
  check("money v2: the panel lists the unpaid EMIs with their dates", !!panel() && panel().querySelectorAll("li").length === 4 && /EMI 1 of 4 · ₹3,000/.test(panel().textContent) && /Overdue/.test(panel().textContent));
  check("money v2: nothing is ticked yet and the action button is disabled and says what to do", mbtn(m, "Tick the EMIs to mark", panel()).disabled === true);
  mbtn(m, "All due or overdue", panel()).click(); await wait(10);
  check("money v2: 'All due or overdue' picks the overdue and today's EMIs and shows the total", [...panel().querySelectorAll("input:checked")].length === 2 && !!mbtn(m, "Mark 2 paid · ₹6,000", panel()));
  mbtn(m, "Next 3", panel()).click(); await wait(10);
  check("money v2: 'Next 3' picks the three earliest", [...panel().querySelectorAll("input:checked")].length === 3 && !!mbtn(m, "Mark 3 paid · ₹9,000", panel()));
  panel().querySelectorAll("input")[0].click(); await wait(10);
  check("money v2: ticking one by hand updates the count", !!mbtn(m, "Mark 2 paid · ₹6,000", panel()));
  mbtn(m, "Mark 2 paid · ₹6,000", panel()).click(); await wait(80);
  const bulk = m.calls("POST", "/api/expenses/emis/bulk")[0];
  check("money v2: confirming posts the picked ids once, with the bank deduction preference", bulk && JSON.parse(bulk.body).ids.join(",") === "22,23" && JSON.parse(bulk.body).paid === true && JSON.parse(bulk.body).deduct === true);
  check("money v2: the panel closes afterwards", !panel());
  m = moneyBootV2(); await wait(60); await openMoney(m, "Payments"); openPayCard(m); mbtn(m, "Mark several paid").click(); await wait(10);
  mbtn(m, "Cancel", panel()).click(); await wait(10);
  check("money v2: Cancel closes the panel and sends nothing", !panel() && m.calls("POST", "/api/expenses/emis/bulk").length === 0);

  // ── one-off due and open cards ──
  const duePay = v2Pay({ id: 4, title: "Card bill", kind: "due", grp: "Cards", emi_count: 1, total_minor: 4800000, planned_minor: 150000, remaining_minor: 150000, mismatch_minor: 0,
    emis: [mkEmi(31, 1, 150000, "2026-12-01", "upcoming", { custom: false })] });
  const openPay = v2Pay({ id: 5, title: "Owe Rahul", kind: "open", grp: "Personal", bank_id: null, emi_count: 0, total_minor: 500000, planned_minor: 500000, paid_minor: 200000, open_paid_minor: 200000, remaining_minor: 300000, mismatch_minor: 0, next_due: null, emis: [] });
  m = moneyBootV2({ pays: [duePay, openPay] }); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  check("money v2: a one-off due reads as an amount due, not 'EMI 1 of 1', and has no EMI-only actions", /Amount due · ₹1,500/.test(moneyText(m)) && !/EMI 1 of 1/.test(moneyText(m)) && !mbtn(m, "+ EMI") && !mbtn(m, "Spread equally") && !mbtn(m, "Set one day for all"));
  check("money v2: an open payment shows what is owed and no schedule", /₹3,000 owed · no due date/.test(moneyText(m)) && /Paid so far ₹2,000 of ₹5,000/.test(moneyText(m)) && m.t.$("panel-money").querySelectorAll('details[data-id="5"] .mn-emi').length === 0);
  mbtn(m, "Record a payment").click(); await wait(10);
  const opf = m.t.$("panel-money").querySelector('form[aria-label^="Record a payment towards"]');
  typeIn(m, opf, "amount", "1,000"); await submitForm(m, opf);
  check("money v2: recording a payment adds it to what was paid so far", m.lastBody().open_paid === "3000");
  openPayCard(m); mbtn(m, "Mark settled").click(); await wait(60);
  check("money v2: 'Mark settled' sends settled:true", m.lastBody().settled === true);

  // ── groups on the overview ──
  m = moneyBootV2({ groups: [{ name: "Home", label: "Home", payments: 1, active: 1, remaining_minor: 1200000, due_30_minor: 300000, overdue: 0, included: true },
    { name: "~ungrouped", label: "Ungrouped", payments: 1, active: 1, remaining_minor: 500000, due_30_minor: 0, overdue: 0, included: true }] });
  await wait(60); await openMoney(m);
  check("money v2: with two groups the overview lists them with their figures", /Groups/.test(moneyText(m)) && /Home/.test(moneyText(m)) && /₹12,000 left/.test(moneyText(m)) && m.t.$("panel-money").querySelectorAll(".mn-group").length === 2);
  fkEl(m, "group:Home").click(); await wait(80);
  check("money v2: unticking a group asks the server for totals without it", m.calls("GET", "/api/expenses?exclude=home").length === 1);
  check("money v2: ...and remembers the choice on this device", m.t.w.localStorage.getItem("tapan.money.exclude") === '["home"]');
  m = moneyBootV2({ excluded: ["home"], hidden: { payments: 1, overdue: 2 } }, {}); m.t.w.localStorage.setItem("tapan.money.exclude", '["home"]'); await openMoney(m);
  check("money v2: a remembered choice is sent on the first load", m.calls("GET", "/api/expenses?exclude=home").length >= 1);
  check("money v2: hidden payments are admitted, with their overdue EMIs", /1 payment is left out of these totals, and 2 of their EMIs are overdue/.test(moneyText(m)));

  // ── spending ──
  const spendData = (over = {}) => ({ month: "2026-11", categories: ["food", "travel"], items: [
      { id: 1, spent_on: "2026-11-23", amount_minor: 25050, category: "food", note: "Lunch", sub_id: null }, { id: 2, spent_on: "2026-11-20", amount_minor: 64900, category: "entertainment", note: "Netflix", sub_id: 5 }],
    summary: { month: "2026-11", current: true, total_minor: 450000, count: 2, previous_total_minor: 300000, change_pct: 50, average_per_day_minor: 18750, projected_minor: 900000, days_in_month: 30, day_of_month: 24,
      categories: [{ category: "food", amount_minor: 300000, count: 1, share: 67 }, { category: "travel", amount_minor: 150000, count: 1, share: 33 }], by_day: [],
      top: [{ id: 1, spent_on: "2026-11-23", amount_minor: 300000, category: "food", note: "Rent share", sub_id: null }], budget_minor: 500000, budget_left_minor: 50000 }, ...over });
  m = moneyBootV2({ spend: spendData() }); await wait(60); await openMoney(m, "Spending");
  check("money v2: Spending shows the month, totals, change on last month and the pace", /November 2026/.test(moneyText(m)) && /₹4,500/.test(moneyText(m)) && /\+50% this month/.test(moneyText(m)) && /₹187\.5|₹188|₹187/.test(moneyText(m)) && /₹9,000/.test(moneyText(m)));
  check("money v2: the category breakdown has text values", /Food/.test(moneyText(m)) && /₹3,000 · 67%/.test(moneyText(m)));
  check("money v2: the budget bar is labelled with its figures", !!m.t.$("panel-money").querySelector('progress[aria-label="₹4,500 of your ₹5,000 budget"]') && /₹500 left/.test(moneyText(m)));
  check("money v2: entries show note, date, category and amount", /Lunch/.test(moneyText(m)) && /₹250\.5/.test(moneyText(m)) && /Netflix/.test(moneyText(m)) && /subscription/.test(moneyText(m)));
  check("money v2: 'Next month' is disabled on the current month", fkEl(m, "sp:next").disabled === true);
  check("money v2: the add-expense form starts closed so the totals come first", !m.t.$("panel-money").querySelector('form[aria-label="Add what you spent"]') && !!mbtn(m, "+ Add expense"));
  mbtn(m, "+ Add expense").click(); await wait(10);
  check("money v2: opening it puts focus in the amount field", m.t.w.document.activeElement.dataset.fk === "add-spend:amount");
  const sf = () => m.t.$("panel-money").querySelector('form[aria-label="Add what you spent"]');
  typeIn(m, sf(), "amount", "250"); typeIn(m, sf(), "note", "Tea"); const catSel = sf().querySelector('[name="category"]'); catSel.value = "travel"; catSel.dispatchEvent(evt(m, "input"));
  await submitForm(m, sf());
  reqBody = JSON.parse(m.calls("POST", "/api/expenses/spending")[0].body);
  check("money v2: adding an expense posts amount, category, note and date", reqBody.amount === "250" && reqBody.category === "travel" && reqBody.note === "Tea" && /^\d{4}-\d\d-\d\d$/.test(reqBody.spent_on));
  check("money v2: the form stays open for the next entry, with the amount cleared, the category kept and focus back in the amount", sf().querySelector('[name="amount"]').value === "" && sf().querySelector('[name="category"]').value === "travel" && m.t.w.document.activeElement.dataset.fk === "add-spend:amount");
  mbtn(m, "Done", sf()).click(); await wait(10);
  check("money v2: 'Done' closes the add form", !sf() && !!mbtn(m, "+ Add expense"));
  fkEl(m, "sp:prev").click(); await wait(80);
  check("money v2: 'Previous month' asks for that month and focus stays on the button", m.calls("GET", "/api/expenses/spending?month=2026-10").length === 1 && m.t.w.document.activeElement.dataset.fk === "sp:prev");
  const filt = fkEl(m, "sp:filter"); filt.value = "food"; filt.dispatchEvent(evt(m, "change")); await wait(80);
  check("money v2: the category filter is sent to the server", m.calls("GET", "/api/expenses/spending?").some((c) => /category=food/.test(c.url)));
  mbtn(m, "Set a budget") || mbtn(m, "Change budget"); (mbtn(m, "Change budget") || mbtn(m, "Set a budget")).click(); await wait(10);
  const bf = m.t.$("panel-money").querySelector('form[aria-label="Monthly budget"]');
  typeIn(m, bf, "amount", "30000"); await submitForm(m, bf);
  check("money v2: saving a budget does a PUT with the amount", m.calls("PUT", "/api/expenses/budget").length === 1 && m.lastBody().amount === "30000");
  mbtn(m, "Delete", m.t.$("panel-money").querySelectorAll(".sp-row")[0]).click(); await wait(10);
  check("money v2: deleting an expense needs a second tap", m.calls("DELETE", "/api/expenses/spending/").length === 0);
  mbtn(m, "Tap again to delete", m.t.$("panel-money").querySelectorAll(".sp-row")[0]).click(); await wait(60);
  check("money v2: ...then deletes it", m.calls("DELETE", "/api/expenses/spending/1").length === 1);
  m = moneyBootV2({ spend: spendData({ items: [], summary: { ...spendData().summary, total_minor: 0, count: 0, categories: [], top: [], budget_minor: null, budget_left_minor: null, projected_minor: null } }) }); await wait(60); await openMoney(m, "Spending");
  check("money v2: an empty month explains how to add, including chat", /No expenses this month yet/.test(moneyText(m)) && /spent 250 on lunch/.test(moneyText(m)) && /Set a budget/.test(moneyText(m)));

  // ── subscriptions ──
  const sub = (o = {}) => ({ id: 5, name: "Netflix", amount_minor: 64900, cycle: "monthly", next_date: "2026-11-27", category: "entertainment", bank_id: 7, active: true, notes: "", remind_days: 1, monthly_minor: 64900, yearly_minor: 778800, days_until: 3, status: "soon", ...o });
  const subsData = (list) => ({ subs: list, categories: ["entertainment"], cycles: ["monthly"], summary: { active: list.filter((s) => s.active).length, paused: list.filter((s) => !s.active).length, monthly_minor: 64900, yearly_minor: 778800, due_7: { count: 1, amount_minor: 64900 }, by_category: [{ category: "entertainment", monthly_minor: 64900 }] } });
  m = moneyBootV2({ subs: subsData([sub(), sub({ id: 6, name: "Gym", amount_minor: 120000, cycle: "yearly", monthly_minor: 10000, active: false, status: "paused", days_until: 40, next_date: "2027-01-03" })]) });
  await wait(60); await openMoney(m, "Subscriptions");
  check("money v2: subscriptions show the monthly and yearly cost and what renews this week", /₹649/.test(moneyText(m)) && /₹7,788/.test(moneyText(m)) && /1 renewing/.test(moneyText(m)));
  check("money v2: each one says when it renews, in words, with a status chip", /Renews in 3 days · 27 Nov 2026/.test(moneyText(m)) && /Renews soon/.test(moneyText(m)) && /Paused/.test(moneyText(m)) && /₹649 \/ month/.test(moneyText(m)));
  check("money v2: a yearly plan also shows its monthly equivalent", /₹100 a month/.test(moneyText(m)));
  mbtn(m, "Mark renewed").click(); await wait(80);
  check("money v2: 'Mark renewed' posts, logs the spending, and takes the bank balance only if that preference is on", m.calls("POST", "/api/expenses/subscriptions/5/renew").length === 1 && JSON.parse(m.calls("POST", "/api/expenses/subscriptions/5/renew")[0].body).record === true && JSON.parse(m.calls("POST", "/api/expenses/subscriptions/5/renew")[0].body).deduct === true);
  check("money v2: a paused subscription has no 'Mark renewed'", [...m.t.$("panel-money").querySelectorAll("button")].filter((b) => b.textContent === "Mark renewed").length === 1);
  mbtn(m, "Pause").click(); await wait(60);
  check("money v2: Pause sends active:false", m.lastBody().active === false);
  mbtn(m, "Resume").click(); await wait(60);
  check("money v2: Resume sends active:true", m.lastBody().active === true);
  mbtn(m, "+ Add subscription").click(); await wait(10);
  const subf = m.t.$("panel-money").querySelector('form[aria-label="Add a subscription"]');
  typeIn(m, subf, "name", "Spotify"); typeIn(m, subf, "amount", "119"); const cyc = subf.querySelector('[name="cycle"]'); cyc.value = "yearly"; cyc.dispatchEvent(evt(m, "input"));
  typeIn(m, subf, "next_date", "2026-12-15"); await submitForm(m, subf);
  reqBody = JSON.parse(m.calls("POST", "/api/expenses/subscriptions").find((c) => c.url === "/api/expenses/subscriptions").body);
  check("money v2: adding a subscription posts name, amount, cycle, date and reminder", reqBody.name === "Spotify" && reqBody.amount === "119" && reqBody.cycle === "yearly" && reqBody.next_date === "2026-12-15" && reqBody.remind_days === 1);
  mbtn(m, "Delete").click(); await wait(10);
  check("money v2: deleting a subscription needs a second tap and says the history stays", m.calls("DELETE", "/api/expenses/subscriptions/").length === 0 && /Tap again to delete/.test(moneyText(m)));
  m = moneyBootV2({ subs: subsData([]) }); await wait(60); await openMoney(m, "Subscriptions");
  check("money v2: with none, it suggests what to add", /No subscriptions yet/.test(moneyText(m)));

  // ── navigation and accessibility across all five views ──
  m = moneyBootV2({ spend: spendData(), subs: subsData([sub()]) }); await wait(60);
  await openMoney(m);
  check("money v2: five sections in a sensible order", [...m.t.$("panel-money").querySelectorAll(".mn-nav-btn")].map((b) => b.textContent).join(",") === "Overview,Payments,Spending,Subscriptions,Banks");
  check("money v2: the overview links to spending and subscriptions with this month's figures", /Spent this month/.test(moneyText(m)) && /₹4,500/.test(moneyText(m)) && /₹649\/mo/.test(moneyText(m)) && !!mbtn(m, "Open spending") && !!mbtn(m, "Open subscriptions"));
  mbtn(m, "Open subscriptions").click(); await wait(80);
  check("money v2: those links open the right section and mark it as selected", m.t.$("panel-money").querySelector('.mn-nav-btn[aria-pressed="true"]').textContent === "Subscriptions");
  for (const view of ["Overview", "Payments", "Spending", "Subscriptions", "Banks"]) {
    await openMoney(m, view); await wait(60);
    if (view === "Payments") openPayCard(m);
    const unnamed2 = [...m.t.$("panel-money").querySelectorAll("button")].filter((b) => !(b.textContent.trim() || b.getAttribute("aria-label")));
    const unlabelled2 = [...m.t.$("panel-money").querySelectorAll("input, select, textarea")].filter((i) => !(i.closest("label") || i.getAttribute("aria-label")));
    check(`money v2: ${view} still has no unnamed buttons and no unlabelled fields`, unnamed2.length === 0 && unlabelled2.length === 0, `${unnamed2.length}/${unlabelled2.length}`);
  }
  check("money v2: neither Money script uses innerHTML-style injection or inline handlers", !/innerHTML|insertAdjacentHTML|outerHTML|onclick=/.test(fs.readFileSync(ROOT + "money-spend.js", "utf8")));


  // ═══════════════ Work and Growth tabs ═══════════════
  const wTask = (id, title, o = {}) => ({ id, title, project: "", priority: "normal", status: "open", due_at: null, due_date: null, due_time: null, overdue: false, due_today: false, details: "", remind: "", completed_at: null, ...o });
  const wNote = (id, kind, body, o = {}) => ({ id, space: "work", kind, title: "", body, tags: [], pinned: false, created_at: "2026-11-20T10:00:00+00:00", updated_at: "2026-11-20T10:00:00+00:00", ...o });
  const workData = () => ({
    tasks: [wTask(1, "Send the report", { project: "Atlas", priority: "high", due_date: "2026-11-22", overdue: true, remind: "morning" }), wTask(2, "Call vendor", { project: "Ops", due_date: "2026-11-24", due_time: "17:30", due_today: true }),
      wTask(3, "Prepare slides", { due_date: "2026-11-28" }), wTask(4, "Plan offsite", { due_date: "2026-12-20" }), wTask(5, "Tidy inbox", { details: "the shared one" })],
    overview: { open: 5, overdue: 1, due_today: 1, high: 1, no_date: 1, done_7d: 3, projects: [{ name: "Atlas", open: 1, overdue: 1 }, { name: "Ops", open: 1, overdue: 0 }] },
    notes: [wNote(12, "meeting", "Decided: ship Friday", { pinned: true }), wNote(11, "plan", "Launch plan\nStep 1", { title: "Q4 launch", tags: ["q4"] }), wNote(13, "idea", "Weekly demo")],
    priorities: ["high", "normal", "low"], kinds: ["note", "plan", "meeting", "idea"], today: "2026-11-24",
  });
  function workBoot(over = {}, specific = {}) {
    const state = { data: workData(), delay: 0, ...over };
    const holder = {};
    const lastBody = () => { const wk = holder.t.calls.filter((c) => c.method !== "GET"); return JSON.parse(wk[wk.length - 1].body || "{}"); };
    const slow = (v) => (state.delay ? new Promise((res) => setTimeout(() => res(v), state.delay)) : v);
    const routes = m0Routes({
      ...specific,
      "GET /api/work": (url) => { const u = new URL(url, "https://x"); const st = u.searchParams.get("status") || "open", pr = u.searchParams.get("project");
        return { ...state.data, tasks: state.data.tasks.filter((t) => (st === "all" || (st === "done") === (t.status === "done")) && (!pr || t.project === pr)) }; },
      "POST /api/work/tasks/": (url) => { const id = Number(url.split("/")[4]); const done = lastBody().done; state.data.tasks.forEach((t) => { if (t.id === id) { t.status = done ? "done" : "open"; t.completed_at = done ? "2026-11-24T09:00:00+00:00" : null; } }); return slow({ id }); },
      "POST /api/work/tasks": () => ({ id: 99 }), "PATCH /api/work/tasks/": () => ({ id: 1 }), "DELETE /api/work/tasks/": () => ({ ok: true }),
      "POST /api/notebook": () => ({ id: 98 }), "PATCH /api/notebook/": () => ({ id: 11 }), "DELETE /api/notebook/": () => ({ ok: true }),
    });
    const t = boot({ drawer: true, routes }); holder.t = t; authed(t);
    return { t, state, lastBody, calls: (method, prefix) => t.calls.filter((c) => c.method === method && c.url.startsWith(prefix)) };
  }
  const openTab = async (m, tab) => { m.t.$("today-btn").click(); m.t.$(`tab-${tab}`).click(); await wait(80); };
  const pnl = (m, tab) => m.t.$(`panel-${tab}`);
  const tbtn = (m, tab, label, root) => [...(root || pnl(m, tab)).querySelectorAll("button")].find((b) => b.textContent.trim() === label);
  const ptext = (m, tab) => pnl(m, tab).textContent;

  let wk = workBoot(); await wait(60); await openTab(wk, "work");
  check("work: the tab opens its panel and asks for open tasks", wk.t.$("tab-work").getAttribute("aria-selected") === "true" && !pnl(wk, "work").classList.contains("hidden") && wk.calls("GET", "/api/work?status=open").length === 1);
  check("work: the headline counts are shown with words", /Open5/.test(ptext(wk, "work").replace(/\s/g, "")) && /Overdue1needsattention/.test(ptext(wk, "work").replace(/\s/g, "")) && /Donethisweek3/.test(ptext(wk, "work").replace(/\s/g, "")));
  check("work: open tasks are grouped Overdue, Today, This week, Later, No date, in that order, each with a count", [...pnl(wk, "work").querySelectorAll(".wk-group-t")].map((e) => e.textContent).join("|") === "Overdue · 1|Today · 1|This week · 1|Later · 1|No date · 1");
  check("work: an overdue task says by how long, a due-today one says its time", /Overdue by 2 days · was due 22 Nov 2026/.test(ptext(wk, "work")) && /Due today at 17:30/.test(ptext(wk, "work")));
  check("work: priority, project and reminders are visible as text, not colour alone", /High/.test(ptext(wk, "work")) && /Atlas/.test(ptext(wk, "work")) && /reminder on/.test(ptext(wk, "work")));
  check("work: a task's details are shown", /the shared one/.test(ptext(wk, "work")));

  // quick add
  const quickForm = () => pnl(wk, "work").querySelector('form[aria-label="Add a task"]');
  await submitForm(wk, quickForm());
  check("work: submitting an empty quick-add says what to do and sends nothing", wk.calls("POST", "/api/work/tasks").length === 0 && /Type the task first/.test(wk.t.$("toast").textContent));
  typeIn(wk, quickForm(), "title", "Book the venue"); await submitForm(wk, quickForm());
  reqBody = wk.lastBody();
  check("work: quick add posts the title once", wk.calls("POST", "/api/work/tasks").length === 1 && reqBody.title === "Book the venue" && reqBody.project === "");
  check("work: ...clears the box and puts focus back in it for the next task", quickForm().querySelector("input").value === "" && wk.t.w.document.activeElement.dataset.fk === "quick:title");

  // project filter
  const projSel = () => [...pnl(wk, "work").querySelectorAll("select")].find((s) => s.dataset.fk === "wk:project");
  check("work: the project list shows how many are open in each", [...projSel().options].map((o) => o.textContent).join("|") === "All projects|Atlas (1)|Ops (1)");
  projSel().value = "Ops"; projSel().dispatchEvent(evt(wk, "change")); await wait(80);
  check("work: choosing a project asks the server for just that project and keeps focus there", wk.calls("GET", "/api/work?status=open&project=Ops").length === 1 && wk.t.w.document.activeElement.dataset.fk === "wk:project");
  check("work: ...only that project's tasks are listed", [...pnl(wk, "work").querySelectorAll(".wk-task .mn-emi-t")].length === 1 && /Call vendor/.test(ptext(wk, "work")));
  check("work: ...and quick add now says it will add to that project", quickForm().querySelector("input").placeholder === "Add a task to Ops");
  typeIn(wk, quickForm(), "title", "Renew the contract"); await submitForm(wk, quickForm());
  check("work: ...and does", wk.lastBody().project === "Ops");
  projSel().value = ""; projSel().dispatchEvent(evt(wk, "change")); await wait(80);

  // status
  tbtn(wk, "work", "Done").click(); await wait(80);
  check("work: the Done filter asks for done tasks and says so when there are none", wk.calls("GET", "/api/work?status=done").length === 1 && /Nothing finished yet/.test(ptext(wk, "work")) && tbtn(wk, "work", "Done").getAttribute("aria-pressed") === "true");
  tbtn(wk, "work", "Open").click(); await wait(80);

  // ticking
  const tickBox = (id) => [...pnl(wk, "work").querySelectorAll("input[type=checkbox]")].find((b) => b.dataset.fk === `task:${id}`);
  check("work: every task has a checkbox whose name says what ticking does", [...pnl(wk, "work").querySelectorAll(".wk-task .mn-check")].every((l) => /Tick to mark done/.test(l.textContent)));
  tickBox(5).click(); await wait(80);
  check("work: ticking a task posts done:true to its own URL", wk.calls("POST", "/api/work/tasks/5/done").length === 1 && wk.lastBody().done === true);
  wk = workBoot({ delay: 60 }); await wait(60); await openTab(wk, "work");
  const t2 = (id) => [...pnl(wk, "work").querySelectorAll("input[type=checkbox]")].find((b) => b.dataset.fk === `task:${id}`);
  t2(3).click(); t2(4).click(); t2(5).click(); await wait(500);
  check("work: ticking three tasks in a row saves all three, in order", wk.calls("POST", "/api/work/tasks/").map((c) => c.url.split("/")[4]).join(",") === "3,4,5");
  wk = workBoot({ delay: 80 }); await wait(60); await openTab(wk, "work");
  const one2 = [...pnl(wk, "work").querySelectorAll("input[type=checkbox]")].find((b) => b.dataset.fk === "task:2");
  one2.click(); one2.click(); await wait(300);
  check("work: a second tap on the same task while it saves is ignored", wk.calls("POST", "/api/work/tasks/2/done").length === 1);

  // detailed form
  wk = workBoot(); await wait(60); await openTab(wk, "work");
  tbtn(wk, "work", "+ Task with details").click(); await wait(10);
  const tf = () => pnl(wk, "work").querySelector('form[aria-label="Add a task with details"]');
  check("work: the detailed form has every field labelled, and starts in the title", !!tf() && ["title", "project", "priority", "due_date", "due_time", "remind", "details"].every((n) => tf().querySelector(`[name="${n}"]`)) && wk.t.w.document.activeElement.dataset.fk === "add-task:title");
  check("work: its project box suggests your projects", [...tf().querySelectorAll("datalist option")].map((o) => o.value).join(",") === "Atlas,Ops");
  typeIn(wk, tf(), "title", "Prepare board deck"); typeIn(wk, tf(), "project", "Board"); const pr = tf().querySelector('[name="priority"]'); pr.value = "high"; pr.dispatchEvent(evt(wk, "input"));
  typeIn(wk, tf(), "remind", ""); const rem = tf().querySelector('[name="remind"]'); rem.value = "due"; rem.dispatchEvent(evt(wk, "input"));
  await submitForm(wk, tf());
  check("work: a reminder with no due date is refused with a reason, and nothing is sent", /needs a due date/.test(wk.t.$("toast").textContent) && wk.calls("POST", "/api/work/tasks").length === 0);
  typeIn(wk, tf(), "due_date", "2026-12-02"); await submitForm(wk, tf());
  check("work: 'at the due time' without a time is refused too", /Pick a time/.test(wk.t.$("toast").textContent) && wk.calls("POST", "/api/work/tasks").length === 0);
  typeIn(wk, tf(), "due_time", "15:00"); await submitForm(wk, tf());
  reqBody = wk.lastBody();
  check("work: a complete task posts title, project, priority, a date-and-time and the reminder", reqBody.title === "Prepare board deck" && reqBody.project === "Board" && reqBody.priority === "high" && reqBody.due === "2026-12-02T15:00" && reqBody.remind === "due");
  check("work: the form closes afterwards", !tf());
  tbtn(wk, "work", "+ Task with details").click(); await wait(10);
  typeIn(wk, tf(), "title", "Just a date"); typeIn(wk, tf(), "due_date", "2026-12-03"); await submitForm(wk, tf());
  check("work: a date alone is sent as a date alone (due by the end of that day)", wk.lastBody().due === "2026-12-03" && wk.lastBody().remind === "");

  // edit and delete
  wk = workBoot(); await wait(60); await openTab(wk, "work");
  tbtn(wk, "work", "Edit", [...pnl(wk, "work").querySelectorAll(".wk-task")][0]).click(); await wait(10);
  const ef2 = () => pnl(wk, "work").querySelector('form[aria-label="Edit Send the report"]');
  check("work: editing opens a prefilled form in place", !!ef2() && ef2().querySelector('[name="title"]').value === "Send the report" && ef2().querySelector('[name="due_date"]').value === "2026-11-22" && ef2().querySelector('[name="priority"]').value === "high" && ef2().querySelector('[name="remind"]').value === "morning");
  typeIn(wk, ef2(), "due_date", ""); await submitForm(wk, ef2());
  check("work: clearing the date sends due:null and no reminder (a reminder needs a date)", wk.lastBody().due === null && wk.lastBody().remind === "" && wk.calls("PATCH", "/api/work/tasks/1").length === 1);
  const delBtn = () => tbtn(wk, "work", "Delete", [...pnl(wk, "work").querySelectorAll(".wk-task")][0]);
  delBtn().click(); await wait(10);
  check("work: deleting needs a second tap and warns the reminder goes too", wk.calls("DELETE", "/api/work/tasks/").length === 0 && /Tap again to delete/.test(ptext(wk, "work")) && /its reminder/.test(tbtn(wk, "work", "Tap again to delete").getAttribute("aria-label")));
  tbtn(wk, "work", "Tap again to delete").click(); await wait(60);
  check("work: ...then deletes it", wk.calls("DELETE", "/api/work/tasks/1").length === 1);

  // search in place
  wk = workBoot(); await wait(60); await openTab(wk, "work");
  const sbox = () => [...pnl(wk, "work").querySelectorAll("input[type=search]")][0];
  sbox().focus(); sbox().value = "vend"; sbox().dispatchEvent(evt(wk, "input")); await wait(10);
  check("work: searching narrows the list as you type without rebuilding the box (focus and text stay)", [...pnl(wk, "work").querySelectorAll(".wk-task")].length === 1 && wk.t.w.document.activeElement === sbox() && sbox().value === "vend" && wk.calls("GET", "/api/work").length === 1);
  sbox().value = "zzz"; sbox().dispatchEvent(evt(wk, "input")); await wait(10);
  check("work: no match says so", /No tasks match that/.test(ptext(wk, "work")));

  // notes and plans
  wk = workBoot(); await wait(60); await openTab(wk, "work");
  tbtn(wk, "work", "Notes & plans").click(); await wait(10);
  check("work: the Notes & plans section lists notes with a kind and a title, pinned first, with tags", /Q4 launch/.test(ptext(wk, "work")) && /#q4/.test(ptext(wk, "work")) && [...pnl(wk, "work").querySelectorAll(".wk-note")][0].textContent.includes("Pinned") && tbtn(wk, "work", "Notes & plans").getAttribute("aria-pressed") === "true");
  tbtn(wk, "work", "+ New note or plan").click(); await wait(10);
  const nf = () => pnl(wk, "work").querySelector('form[aria-label="Add to your notes"]');
  check("work: the note form starts in the text box", !!nf() && wk.t.w.document.activeElement.dataset.fk === "add-note:work:body" && /Note/.test(nf().textContent));
  const kind = nf().querySelector('[name="kind"]'); kind.value = "plan"; kind.dispatchEvent(evt(wk, "input")); await wait(10);
  check("work: choosing 'Plan' relabels the text box", /The plan/.test(nf().textContent) && /Goal, steps, who does what/.test(nf().querySelector("textarea").placeholder));
  typeIn(wk, nf(), "body", "Goal: ship v2\nStep 1: test"); typeIn(wk, nf(), "title", "v2 plan"); typeIn(wk, nf(), "tags", "Q4, Launch"); await submitForm(wk, nf());
  reqBody = wk.lastBody();
  check("work: saving posts the space, kind, title, text and tags exactly as typed", reqBody.space === "work" && reqBody.kind === "plan" && reqBody.title === "v2 plan" && reqBody.body === "Goal: ship v2\nStep 1: test" && reqBody.tags === "Q4, Launch");
  check("work: the form stays open for the next note, empty, with focus in it, keeping the kind", nf().querySelector("textarea").value === "" && nf().querySelector('[name="kind"]').value === "plan" && wk.t.w.document.activeElement.dataset.fk === "add-note:work:body");
  tbtn(wk, "work", "Done", nf()).click(); await wait(10);
  tbtn(wk, "work", "Meeting").click(); await wait(10);
  check("work: the kind filter shows only that kind", [...pnl(wk, "work").querySelectorAll(".wk-note")].length === 1 && /Decided: ship Friday/.test(ptext(wk, "work")));
  tbtn(wk, "work", "All").click(); await wait(10);
  tbtn(wk, "work", "Pin", [...pnl(wk, "work").querySelectorAll(".wk-note")].find((c) => c.textContent.includes("Weekly demo"))).click(); await wait(60);
  check("work: Pin sends pinned:true for that note", wk.calls("PATCH", "/api/notebook/13").length === 1 && wk.lastBody().pinned === true);
  const noteDel = () => tbtn(wk, "work", "Delete", [...pnl(wk, "work").querySelectorAll(".wk-note")][0]);
  noteDel().click(); await wait(10);
  check("work: deleting a note needs a second tap", wk.calls("DELETE", "/api/notebook/").length === 0);
  tbtn(wk, "work", "Tap again to delete").click(); await wait(60);
  check("work: ...then deletes it", wk.calls("DELETE", "/api/notebook/").length === 1);
  wk = workBoot({ data: { ...workData(), notes: [], tasks: [], overview: { open: 0, overdue: 0, due_today: 0, high: 0, no_date: 0, done_7d: 0, projects: [] } } }); await wait(60); await openTab(wk, "work");
  check("work: with nothing yet, tasks explain how to add one, including by chat", /No tasks yet/.test(ptext(wk, "work")) && /add a task: send the report by Friday/.test(ptext(wk, "work")));
  tbtn(wk, "work", "Notes & plans").click(); await wait(10);
  check("work: ...and notes say what belongs there", /No notes yet/.test(ptext(wk, "work")) && /For something to do, add a task/.test(ptext(wk, "work")));

  // a11y
  wk = workBoot(); await wait(60); await openTab(wk, "work");
  for (const section of ["Tasks", "Notes & plans"]) {
    tbtn(wk, "work", section).click(); await wait(10);
    if (section === "Tasks") { tbtn(wk, "work", "+ Task with details").click(); await wait(10); }
    const unnamedW = [...pnl(wk, "work").querySelectorAll("button")].filter((b) => !(b.textContent.trim() || b.getAttribute("aria-label")));
    const unlabelledW = [...pnl(wk, "work").querySelectorAll("input, select, textarea")].filter((i) => !(i.closest("label") || i.getAttribute("aria-label")));
    check(`work: ${section} has no unnamed buttons and no unlabelled fields`, unnamedW.length === 0 && unlabelledW.length === 0, `${unnamedW.length}/${unlabelledW.length}`);
  }

  // ── growth ──
  const gNote = (id, kind, body, o = {}) => wNote(id, kind, body, { space: "growth", ...o });
  const growthData = () => ({
    total: 6, counts: { learning: 1, lesson: 2, quote: 1, thought: 0, rule: 2 }, kinds: ["learning", "lesson", "quote", "thought", "rule"],
    tags: [{ tag: "calm", count: 2 }, { tag: "work", count: 1 }],
    notes: [gNote(21, "rule", "Never reply angry\nBecause I regret every hurried reply", { tags: ["calm"] }), gNote(22, "rule", "Sleep on big decisions", { tags: ["calm"], pinned: true }),
      gNote(23, "lesson", "Ask for help early", { tags: ["work"] }), gNote(24, "quote", "We suffer more in imagination than in reality", { title: "Seneca" }),
      gNote(25, "learning", "Pomodoro works for me"), gNote(26, "lesson", "Ship small")],
    pick: null,
  });
  function growthBoot(over = {}) {
    const state = { data: growthData(), ...over };
    if (state.data.pick === null && state.data.notes.length) state.data.pick = state.data.notes[1];
    const holder = {};
    const lastBody = () => { const wr = holder.t.calls.filter((c) => c.method !== "GET"); return JSON.parse(wr[wr.length - 1].body || "{}"); };
    const routes = m0Routes({ "GET /api/growth": () => state.data, "POST /api/notebook": () => ({ id: 97 }), "PATCH /api/notebook/": () => ({ id: 22 }), "DELETE /api/notebook/": () => ({ ok: true }) });
    const t = boot({ drawer: true, routes }); holder.t = t; authed(t);
    return { t, state, lastBody, calls: (method, prefix) => t.calls.filter((c) => c.method === method && c.url.startsWith(prefix)) };
  }
  let g = growthBoot(); await wait(60); await openTab(g, "growth");
  check("growth: the tab opens and loads once", g.t.$("tab-growth").getAttribute("aria-selected") === "true" && g.calls("GET", "/api/growth").length === 1);
  check("growth: 'For today' shows the server's pick (the pinned rule)", /For today/.test(ptext(g, "growth")) && pnl(g, "growth").querySelector(".wk-today .wk-note-rule").textContent === "Sleep on big decisions");
  tbtn(g, "growth", "Another one").click(); await wait(10);
  const second = pnl(g, "growth").querySelector(".wk-today .wk-note-rule").textContent;
  check("growth: 'Another one' shows a different item without asking the server", second !== "Sleep on big decisions" && g.calls("GET", "/api/growth").length === 1 && g.t.w.document.activeElement.dataset.fk === "gr:another");
  check("growth: the counts say what is in the journal and the rulebook", /Journalentries4/.test(ptext(g, "growth").replace(/\s/g, "")) && /Rules2/.test(ptext(g, "growth").replace(/\s/g, "")));
  check("growth: the journal lists entries but not rules, with kind counts on the filters", /Ask for help early/.test(ptext(g, "growth")) && !/Never reply angry/.test(ptext(g, "growth").split("Rulebook")[1] || "") && !!tbtn(g, "growth", "Lesson (2)") && !!tbtn(g, "growth", "All (4)"));
  tbtn(g, "growth", "Lesson (2)").click(); await wait(10);
  check("growth: filtering by kind shows just lessons", [...pnl(g, "growth").querySelectorAll(".wk-note")].length === 2 && tbtn(g, "growth", "Lesson (2)").getAttribute("aria-pressed") === "true");
  tbtn(g, "growth", "All (4)").click(); await wait(10);
  const tagBtn = [...pnl(g, "growth").querySelectorAll("button.tag-btn")].find((b) => b.textContent === "#work");
  tagBtn.click(); await wait(10);
  check("growth: a tag chip filters, says it is pressed, and clicking again clears it", [...pnl(g, "growth").querySelectorAll(".wk-note")].length === 1 && [...pnl(g, "growth").querySelectorAll("button.tag-btn")].find((b) => b.textContent === "#work").getAttribute("aria-pressed") === "true" && /1 entry/.test(tagBtn.getAttribute("aria-label")));
  [...pnl(g, "growth").querySelectorAll("button.tag-btn")].find((b) => b.textContent === "#work").click(); await wait(10);
  check("growth: ...and clearing the tag shows everything again", [...pnl(g, "growth").querySelectorAll(".wk-note")].length === 4);
  const gsearch = () => [...pnl(g, "growth").querySelectorAll("input[type=search]")][0];
  gsearch().focus(); gsearch().value = "pomodoro"; gsearch().dispatchEvent(evt(g, "input")); await wait(10);
  check("growth: search narrows in place and keeps focus", [...pnl(g, "growth").querySelectorAll(".wk-note")].length === 1 && g.t.w.document.activeElement === gsearch());

  g = growthBoot(); await wait(60); await openTab(g, "growth");
  tbtn(g, "growth", "+ Add to journal").click(); await wait(10);
  const gf = () => pnl(g, "growth").querySelector('form[aria-label="Add to your journal"]');
  check("growth: the journal form defaults to Learning and asks the right question", !!gf() && gf().querySelector('[name="kind"]').value === "learning" && /What did you learn\?/.test(gf().textContent));
  const gk = gf().querySelector('[name="kind"]'); gk.value = "quote"; gk.dispatchEvent(evt(g, "input")); await wait(10);
  check("growth: choosing Quote asks for the quote and who said it", /The quote/.test(gf().textContent) && /Who said it/.test(gf().textContent));
  typeIn(g, gf(), "body", "Begin at once"); typeIn(g, gf(), "title", "Seneca"); typeIn(g, gf(), "tags", "stoic"); await submitForm(g, gf());
  reqBody = g.lastBody();
  check("growth: saving posts space growth, the kind, text, source and tags", reqBody.space === "growth" && reqBody.kind === "quote" && reqBody.body === "Begin at once" && reqBody.title === "Seneca" && reqBody.tags === "stoic");
  check("growth: the form stays open for the next entry", !!gf() && gf().querySelector("textarea").value === "" && g.t.w.document.activeElement.dataset.fk === "add-note:growth:body");

  g = growthBoot(); await wait(60); await openTab(g, "growth");
  tbtn(g, "growth", "Rulebook").click(); await wait(10);
  const cards = () => [...pnl(g, "growth").querySelectorAll(".wk-note")];
  check("growth: the rulebook numbers the rules in the order written", cards().length === 2 && /Rule 1/.test(cards()[0].textContent) && /Rule 2/.test(cards()[1].textContent));
  check("growth: a rule's first line stands out and the reason is quieter", cards()[0].querySelector(".wk-note-rule").textContent === "Never reply angry" && /regret every hurried reply/.test(cards()[0].querySelector(".wk-note-body.muted").textContent));
  tbtn(g, "growth", "+ Add a rule").click(); await wait(10);
  const rf = () => pnl(g, "growth").querySelector('form[aria-label="Add to your journal"]');
  check("growth: adding a rule starts as a Rule and explains the two-line format", rf().querySelector('[name="kind"]').value === "rule" && /The rule \(first line\), and why it matters/.test(rf().textContent));
  typeIn(g, rf(), "body", "No phones at dinner\nPresence matters."); await submitForm(g, rf());
  check("growth: the new rule posts as kind rule", g.lastBody().kind === "rule" && g.lastBody().space === "growth");
  tbtn(g, "growth", "Done", rf()).click(); await wait(10);
  tbtn(g, "growth", "Unpin", cards().find((c) => c.textContent.includes("Sleep on big decisions"))).click(); await wait(60);
  check("growth: Unpin sends pinned:false", g.calls("PATCH", "/api/notebook/22").length === 1 && g.lastBody().pinned === false);
  g = growthBoot({ data: { ...growthData(), notes: [], total: 0, counts: {}, tags: [], pick: null } }); await wait(60); await openTab(g, "growth");
  check("growth: empty, it explains what 'For today' will become and how to add by chat", /one of them will be shown here each day/.test(ptext(g, "growth")) && /save this lesson/.test(ptext(g, "growth")));
  tbtn(g, "growth", "Rulebook").click(); await wait(10);
  check("growth: an empty rulebook says what makes a good first rule", /No rules yet/.test(ptext(g, "growth")));

  g = growthBoot(); await wait(60); await openTab(g, "growth");
  for (const section of ["Journal", "Rulebook"]) {
    tbtn(g, "growth", section).click(); await wait(10);
    tbtn(g, "growth", section === "Journal" ? "+ Add to journal" : "+ Add a rule").click(); await wait(10);
    const unnamedG = [...pnl(g, "growth").querySelectorAll("button")].filter((b) => !(b.textContent.trim() || b.getAttribute("aria-label")));
    const unlabelledG = [...pnl(g, "growth").querySelectorAll("input, select, textarea")].filter((i) => !(i.closest("label") || i.getAttribute("aria-label")));
    check(`growth: ${section} has no unnamed buttons and no unlabelled fields`, unnamedG.length === 0 && unlabelledG.length === 0, `${unnamedG.length}/${unlabelledG.length}`);
  }
  check("work/growth: none of the new scripts uses innerHTML-style injection or inline handlers", ["panel-kit.js", "work.js", "growth.js"].every((f) => !/innerHTML|insertAdjacentHTML|outerHTML|onclick=/.test(fs.readFileSync(ROOT + f, "utf8"))));


  // ═══════════════ Loading feedback for every request, and long EMI lists ═══════════════
  const later = (ms, value) => new Promise((res) => setTimeout(() => res(value), ms));
  function busyBoot(timing = {}) {
    const routes = m0Routes({
      "GET /api/slow": () => later(300, { ok: true }), "POST /api/slow": () => later(300, { ok: true }), "PATCH /api/slow": () => later(300, { ok: true }),
      "DELETE /api/slow": () => later(300, { ok: true }), "GET /api/long": () => later(700, { ok: true }), "POST /api/glacial": () => later(1800, { ok: true }), "GET /api/fast": () => ({ ok: true }), "POST /api/fast": () => ({ ok: true }),
      "GET /api/broken": () => later(100, { status: 500, body: {} }), "GET /api/notifications": () => later(300, { notifications: [] }),
    });
    const t = boot({ drawer: true, routes }); authed(t);
    Object.assign(t.w.TapanHost.netTiming, { showWrite: 20, showRead: 20, counting: 3, slow: 8 }, timing);
    const el = (id) => t.$(id);
    return { t, call: (method, path) => t.w.TapanHost.api(path, { method }), pill: () => el("busy"), bar: () => el("busy-bar"), text: () => el("busy-text").textContent, sr: () => el("busy-sr").textContent,
      shown: () => !el("busy").classList.contains("hidden") && !el("busy-bar").classList.contains("hidden") && t.w.document.body.classList.contains("is-busy") };
  }
  let bz = busyBoot(); await wait(60);
  check("busy: the page has a status pill, a progress bar and a polite live region for screen readers, all hidden at rest", !!bz.pill() && !!bz.bar() && bz.pill().classList.contains("hidden") && bz.bar().classList.contains("hidden") && bz.t.$("busy-sr").getAttribute("role") === "status" && bz.t.$("busy-sr").getAttribute("aria-live") === "polite");
  check("busy: the pill and bar are decoration for sighted users (hidden from the accessibility tree; the live region speaks instead)", bz.pill().getAttribute("aria-hidden") === "true" && bz.bar().getAttribute("aria-hidden") === "true");
  let pending1 = bz.call("POST", "/api/slow"); await wait(60);
  check("busy: a slow save shows 'Saving…' on the pill with the bar running", bz.shown() && bz.text() === "Saving…");
  check("busy: ...and tells screen readers once, in words", bz.sr() === "Saving…");
  await pending1; await wait(30);
  check("busy: ...and everything disappears when the answer arrives", !bz.shown() && bz.sr() === "");
  pending1 = bz.call("GET", "/api/slow"); await wait(60);
  check("busy: a slow read says 'Loading…'", bz.shown() && bz.text() === "Loading…");
  await pending1; await wait(30);
  pending1 = bz.call("DELETE", "/api/slow"); await wait(60);
  check("busy: a delete says 'Deleting…'", bz.text() === "Deleting…");
  await pending1; await wait(30);
  pending1 = bz.call("PATCH", "/api/slow"); await wait(60);
  check("busy: an edit says 'Saving…'", bz.text() === "Saving…");
  await pending1; await wait(30);
  bz = busyBoot({ showWrite: 150, showRead: 700 }); await wait(60);
  await bz.call("POST", "/api/fast"); await wait(10);
  const quickSeen = bz.shown();
  await bz.call("GET", "/api/fast"); await wait(10);
  check("busy: an answer that arrives quickly never flashes the pill", !quickSeen && !bz.shown());
  bz = busyBoot(); await wait(60);
  const a1 = bz.call("POST", "/api/slow"), a2 = bz.call("GET", "/api/long"); await wait(60);
  check("busy: several requests at once share one pill", bz.shown() && bz.t.w.document.querySelectorAll("#busy").length === 1);
  await a1; await wait(40);
  check("busy: ...which stays after the first one finishes, because the second is still running", bz.shown());
  await a2; await wait(30);
  check("busy: ...and goes when the last one finishes", !bz.shown());
  bz = busyBoot(); await wait(60);
  bz.t.w.fetch = async () => { await later(120, null); return { ok: false, status: 500, json: async () => ({}) }; };         // slow, then a server error
  let failed = null; const badCall = bz.call("GET", "/api/broken").catch((e) => { failed = e; }); await wait(60);
  check("busy: a request that is slow and then fails still shows progress", bz.shown());
  await badCall; await wait(20);
  check("busy: ...and clears when it fails, so a failure never leaves the screen 'busy' forever", failed && failed.status === 500 && !bz.shown());
  bz = busyBoot(); await wait(60);
  const poll = bz.t.w.TapanHost.api("/api/notifications?after=0"); await wait(80);
  check("busy: background polling is never announced", !bz.shown() && bz.sr() === "");
  await poll;
  bz = busyBoot({ counting: 0, slow: 1 }); await wait(60);
  const slowOne = bz.call("POST", "/api/glacial");
  await wait(1250);
  check("busy: after a while it says the server is slow, not just a spinner", /Still working… the server is slow right now/.test(bz.text()));
  check("busy: ...and screen readers are told once about the delay", bz.sr() === "Still working. The server is slow right now.");
  await slowOne;
  bz = busyBoot({ counting: 0, slow: 60 }); await wait(60);
  const counted = bz.call("POST", "/api/glacial"); await wait(1150);
  check("busy: a slow request counts the seconds so it is clear it has not frozen", /Saving… [01]s/.test(bz.text()));
  await counted;
  m = moneyBootV2(); m.state.delay = 250; await wait(60);
  m.t.w.TapanHost.netTiming.showWrite = 20;
  await openMoney(m, "Payments"); openPayCard(m);
  [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")][0].click(); await wait(80);
  check("busy: ticking an EMI on the Money screen shows 'Saving…' while it is saved, and the primary buttons are dimmed", !m.t.$("busy").classList.contains("hidden") && m.t.$("busy-text").textContent === "Saving…" && m.t.$("panel-money").getAttribute("aria-busy") === "true");
  await wait(400);
  check("busy: ...and it is all gone afterwards", m.t.$("busy").classList.contains("hidden") && !m.t.$("panel-money").hasAttribute("aria-busy"));
  m = moneyBootV2(); m.state.delay = 80; await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  m.state.reloadDelay = 400; m.t.w.TapanHost.netTiming.showWrite = 20;
  [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")][0].click(); await wait(250);
  check("busy: the pill stays up while the screen is refreshed after a save (the save has landed, the numbers have not changed yet)", !m.t.$("busy").classList.contains("hidden") && m.calls("PATCH", "/api/expenses/emis/").length === 1 && m.t.$("panel-money").getAttribute("aria-busy") === "true");
  await wait(600);
  check("busy: ...and goes only once the refreshed screen is there", m.t.$("busy").classList.contains("hidden") && [...m.t.$("panel-money").querySelectorAll(".mn-emi input[type=checkbox]")][0].checked === true);


  // long EMI lists scroll inside their card
  const longPay = (n) => v2Pay({ emi_count: n, paid_count: 3, emis: Array.from({ length: n }, (_, i) => mkEmi(500 + i, i + 1, 100000, `2027-${String((i % 12) + 1).padStart(2, "0")}-05`, i < 3 ? "paid" : "upcoming", { custom: false })) });
  m = moneyBootV2({ pays: [longPay(24)] }); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  const box = () => m.t.$("panel-money").querySelector(".scroll-box");
  check("scroll: a 24-EMI loan's list sits in a scroll region", !!box() && box().querySelectorAll(".mn-emi").length === 24);
  check("scroll: ...that the keyboard can reach and screen readers can name", box().tabIndex === 0 && box().getAttribute("role") === "region" && box().getAttribute("aria-label") === "EMIs of Car loan");
  check("scroll: ...and the list inside is still a real list (the region role is on the box, not the <ul>, so list semantics survive)", box().firstElementChild.tagName === "UL" && !box().firstElementChild.hasAttribute("role"));
  check("scroll: ...with a line saying how many there are and where it opens", /24 EMIs\. Scroll inside the list; it opens at the next one to pay\./.test(ptext(m, "money")));
  m = moneyBootV2({ pays: [longPay(6)] }); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  check("scroll: a short list (6 or fewer) is left alone", !box() && !/Scroll inside the list/.test(ptext(m, "money")) && m.t.$("panel-money").querySelectorAll(".mn-emis").length === 1);
  m = moneyBootV2({ pays: [longPay(24)] }); await wait(60); await openMoney(m, "Payments"); openPayCard(m);
  tbtn(m, "money", "Mark several paid").click(); await wait(10);
  const bulkBox = m.t.$("panel-money").querySelector('[role="group"][aria-label^="Mark several EMIs"] .scroll-box');
  check("scroll: the 'mark several' list scrolls too, so its buttons stay in reach", !!bulkBox && bulkBox.getAttribute("aria-label") === "Unpaid EMIs of Car loan" && bulkBox.querySelectorAll("li").length === 21);
  check("scroll: the scrolling regions' accessible names do not collide with each other", new Set([...m.t.$("panel-money").querySelectorAll(".scroll-box")].map((u) => u.getAttribute("aria-label"))).size === 2);


  // ═══════════════ New design: bottom navigation, More menu, themes ═══════════════
  const navRoutes = () => m0Routes({ "GET /api/history": { messages: [] }, "GET /api/briefing": {}, "GET /api/expenses": () => moneySnap(), "GET /api/work": () => workData(), "GET /api/growth": () => growthData(), "GET /api/conversations": { conversations: [] } });
  const dest = (t, d) => [...t.$("bottom-nav").querySelectorAll(".bnav-btn")].find((b) => b.dataset.dest === d);
  const currentDest = (t) => [...t.$("bottom-nav").querySelectorAll(".bnav-btn")].filter((b) => b.getAttribute("aria-current") === "page").map((b) => b.dataset.dest).join(",");
  let nv = boot({ routes: navRoutes(), drawer: true }); authed(nv); await wait(40);
  check("nav: a 'Main' navigation landmark holds named destinations in a sensible order", nv.$("bottom-nav").tagName === "NAV" && nv.$("bottom-nav").getAttribute("aria-label") === "Main" && [...nv.$("bottom-nav").querySelectorAll(".bnav-btn")].map((b) => b.textContent.trim()).join(",") === "Chat,Today,Money,Work,Growth,History,Settings,More");
  check("nav: on a phone the bar shows six (History and Settings sit in More); on a wide screen the rail shows them directly", [...nv.$("bottom-nav").querySelectorAll(".bnav-btn.only-wide")].map((b) => b.dataset.dest).join(",") === "history,settings");
  check("nav: it starts on Chat, and says so for assistive tech (aria-current)", currentDest(nv) === "chat");
  check("nav: the icons are decoration (hidden from screen readers); the visible word is the name", [...nv.$("bottom-nav").querySelectorAll("svg")].every((s) => s.getAttribute("aria-hidden") === "true"));
  dest(nv, "money").click(); await wait(60);
  check("nav: Money opens the Money page and marks it current", nv.$("app").dataset.panel === "open" && nv.$("tab-money").getAttribute("aria-selected") === "true" && currentDest(nv) === "money");
  check("nav: the page has a visible title that matches, and focus lands on it", nv.$("panel-title").textContent === "Money" && nv.w.document.activeElement.id === "panel-title");
  dest(nv, "money").click(); await wait(20);
  check("nav: tapping the current destination keeps you there (it does not toggle the page away)", nv.$("app").dataset.panel === "open" && currentDest(nv) === "money");
  dest(nv, "work").click(); await wait(60);
  check("nav: moving between pages swaps the title and the current marker", nv.$("panel-title").textContent === "Work" && currentDest(nv) === "work" && !nv.$("panel-work").classList.contains("hidden"));
  dest(nv, "growth").click(); await wait(60);
  check("nav: Growth works the same way", nv.$("panel-title").textContent === "Growth" && currentDest(nv) === "growth");
  dest(nv, "today").click(); await wait(60);
  check("nav: Today works the same way", nv.$("panel-title").textContent === "Today" && currentDest(nv) === "today");
  dest(nv, "chat").click(); await wait(40);
  check("nav: Chat closes the page and goes back to the conversation", nv.$("app").dataset.panel === "closed" && currentDest(nv) === "chat");

  // desktop: the same navigation is a rail beside the chat, and every page has its own button
  let dk = boot({ routes: navRoutes() }); authed(dk); await wait(40);
  check("rail: on desktop the current page is marked from the start (the side panel is always showing one)", currentDest(dk) === "today" && dk.$("panel-title").textContent === "Today");
  dest(dk, "history").click(); await wait(60);
  check("rail: History opens in the side panel and is marked current", dk.$("tab-history").getAttribute("aria-selected") === "true" && currentDest(dk) === "history" && dk.$("panel-title").textContent === "History");
  dest(dk, "settings").click(); await wait(60);
  check("rail: Settings likewise", dk.$("tab-settings").getAttribute("aria-selected") === "true" && currentDest(dk) === "settings");
  dest(dk, "growth").click(); await wait(60);
  check("rail: Growth likewise, and the panel's title follows", currentDest(dk) === "growth" && dk.$("panel-title").textContent === "Growth" && !dk.$("panel-growth").classList.contains("hidden"));
  dk.$("tab-work").click(); await wait(60);
  check("rail: changing page by any other route (here the tab) keeps the rail in step", currentDest(dk) === "work");

  // More menu
  dest(nv, "more").focus(); dest(nv, "more").click(); await wait(20);
  const more = () => nv.$("more-sheet");
  check("more: opens a labelled modal sheet, hides the page behind it from assistive tech, and focuses its first choice", !more().classList.contains("hidden") && more().getAttribute("role") === "dialog" && more().getAttribute("aria-modal") === "true" && nv.$("app").hasAttribute("inert") && nv.w.document.activeElement.id === "more-history");
  check("more: it holds History, Settings and the appearance choice", /History/.test(more().textContent) && /Settings/.test(more().textContent) && [...more().querySelectorAll(".seg3 button")].map((b) => b.textContent).join(",") === "Auto,Light,Dark");
  nv.w.document.dispatchEvent(new nv.w.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); await wait(10);
  check("more: Escape closes it and puts focus back on the More button", more().classList.contains("hidden") && !nv.$("app").hasAttribute("inert") && nv.w.document.activeElement === dest(nv, "more"));
  dest(nv, "more").click(); await wait(10);
  nv.$("more-history").click(); await wait(60);
  check("more: History opens the History page, and More is the current destination (History is not in the bar)", more().classList.contains("hidden") && nv.$("tab-history").getAttribute("aria-selected") === "true" && nv.$("panel-title").textContent === "History" && currentDest(nv) === "more");
  dest(nv, "more").click(); await wait(10);
  nv.$("more-settings").click(); await wait(60);
  check("more: Settings opens the Settings page and keeps More current", nv.$("panel-title").textContent === "Settings" && currentDest(nv) === "more");
  dest(nv, "chat").click(); await wait(20);
  dest(nv, "more").click(); await wait(10);
  nv.$("more-close").click(); await wait(10);
  check("more: the Close button closes it", more().classList.contains("hidden"));
  check("more: Install and Lock only appear when they could do something", nv.$("more-lock").classList.contains("hidden"));
  nv.w.localStorage.setItem("tapan.token", "tok"); nv.w.TapanHost.state.token = "tok"; dest(nv, "more").click(); await wait(10);
  check("more: ...Lock appears once there is a token to forget", !nv.$("more-lock").classList.contains("hidden"));
  nv.$("more-close").click(); await wait(10);
  check("nav: every button in the bar and the menu has a name", [...nv.$("bottom-nav").querySelectorAll("button"), ...more().querySelectorAll("button")].every((b) => (b.textContent.trim() || b.getAttribute("aria-label"))));

  // themes
  let th = boot({ routes: navRoutes(), drawer: true }); authed(th); await wait(30);
  const root = () => th.w.document.documentElement;
  check("theme: with no choice it follows the device (no data-theme attribute) and the toggle says so", !root().hasAttribute("data-theme") && th.$("theme-btn").dataset.pref === "auto" && /automatic/.test(th.$("theme-btn").getAttribute("aria-label")));
  th.$("theme-btn").click(); await wait(10);
  check("theme: the first tap chooses Light, remembers it on this device, and updates the browser bar colour", root().getAttribute("data-theme") === "light" && th.w.localStorage.getItem("tapan.theme") === "light" && th.w.document.querySelector('meta[name="theme-color"]').getAttribute("content") === "#f3f5f9");
  check("theme: ...the button's name says what is selected now", th.$("theme-btn").dataset.pref === "light" && /light/.test(th.$("theme-btn").getAttribute("aria-label")) && /Appearance: light/.test(th.$("toast").textContent));
  th.$("theme-btn").click(); await wait(10);
  check("theme: the second tap chooses Dark", root().getAttribute("data-theme") === "dark" && th.w.document.querySelector('meta[name="theme-color"]').getAttribute("content") === "#0c0f15");
  th.$("theme-btn").click(); await wait(10);
  check("theme: the third tap goes back to Automatic and forgets the choice", !root().hasAttribute("data-theme") && th.w.localStorage.getItem("tapan.theme") === null);
  th = boot({ routes: navRoutes(), drawer: true, storage: { "tapan.theme": "light" } }); authed(th); await wait(30);
  check("theme: a remembered choice is applied before anything is drawn", th.w.document.documentElement.getAttribute("data-theme") === "light" && th.$("theme-btn").dataset.pref === "light");
  th = boot({ routes: navRoutes(), drawer: true, storage: { "tapan.theme": "bogus" } }); authed(th); await wait(30);
  check("theme: a corrupted saved value is ignored, not trusted", !th.w.document.documentElement.hasAttribute("data-theme"));
  dest(th, "more").click(); await wait(10);
  [...th.$("more-sheet").querySelectorAll(".seg3 button")].find((b) => b.dataset.pref === "dark").click(); await wait(10);
  check("theme: the More menu's Auto/Light/Dark choice applies, and shows which one is selected", th.w.document.documentElement.getAttribute("data-theme") === "dark" && [...th.$("more-sheet").querySelectorAll(".seg3 button")].filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.pref).join(",") === "dark");
  check("theme: ...and the top-bar toggle agrees", th.$("theme-btn").dataset.pref === "dark");
  [...th.$("more-sheet").querySelectorAll(".seg3 button")].find((b) => b.dataset.pref === "auto").click(); await wait(10);
  check("theme: choosing Auto in the menu clears the override", !th.w.document.documentElement.hasAttribute("data-theme"));

  // what the design must not depend on
  const cssText = fs.readFileSync(ROOT + "style.css", "utf8");
  const rawHtml = fs.readFileSync(ROOT + "index.html", "utf8");
  check("design: nothing is fetched from a font or 3D-library CDN any more (faster first load, nothing leaks to third parties)", !/fonts\.googleapis|fonts\.gstatic|three\.min\.js|Orbitron/.test(rawHtml) && !/Orbitron/.test(cssText));
  check("design: the theme script loads synchronously in the head, before the stylesheet, so there is no flash of the wrong theme", /<script src="theme\.js"><\/script>\s*<link rel="stylesheet" href="style\.css">/.test(rawHtml));
  check("design: both themes define every colour token, and 'auto' follows the device", ["--bg", "--surface", "--surface-2", "--text", "--muted", "--accent", "--on-accent", "--danger", "--good"].every((tok) => (cssText.match(new RegExp(`${tok}:`, "g")) || []).length >= 3) && /prefers-color-scheme: light/.test(cssText) && /:root\[data-theme="light"\]/.test(cssText));
  check("design: the page declares both colour schemes so native controls match", /<meta name="color-scheme" content="dark light">/.test(rawHtml));
  check("design: no colour is hard-coded to the old green any more", !/0, 255, 136|#00ff88|#00160b/i.test(cssText));
  check("design: text on the accent colour always uses the theme's own foreground, never a fixed colour", !/background: var\(--accent\);\s*color: #/.test(cssText));
  check("design: the new scripts are not using innerHTML-style injection", !/innerHTML|insertAdjacentHTML|outerHTML/.test(fs.readFileSync(ROOT + "theme.js", "utf8")));

  console.log(failures ? `\n${failures} FAILED` : "\nALL UI TESTS PASSED");
  process.exit(failures ? 1 : 0);
})();
