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
  w.eval(version ? appJs.replace(/__WEB_VERSION__/g, version) : appJs);
  w.eval(settingsJs);
  w.eval(integrationsJs);
  w.eval(moneyJs);
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
  check("open drawer is a modal dialog", side.getAttribute("role") === "dialog" && side.getAttribute("aria-modal") === "true" && !side.hasAttribute("inert"));
  check("everything behind the drawer is inert", t.w.document.querySelector(".topbar").hasAttribute("inert") && t.w.document.querySelector(".chat").hasAttribute("inert"));
  check("focus moves to the close button", t.w.document.activeElement.id === "side-close");
  check("opening pushes a history entry so the Back button can close it", t.w.history.state && t.w.history.state.tapanPanel === true);
  const focusables = [...side.querySelectorAll('a[href], button:not([disabled]), textarea, input, [tabindex]:not([tabindex="-1"])')].filter((el) => !el.closest(".hidden"));
  focusables[focusables.length - 1].focus();
  let tab = t.key(side, { key: "Tab" });
  check("Tab on the last control wraps to the first (focus trap)", tab.defaultPrevented && t.w.document.activeElement === focusables[0]);
  focusables[0].focus();
  tab = t.key(side, { key: "Tab", shiftKey: true });
  check("Shift+Tab on the first control wraps to the last", tab.defaultPrevented && t.w.document.activeElement === focusables[focusables.length - 1]);
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
  u.key(u.$("tab-money"), { key: "ArrowRight" });
  check("settings: ...and Settings is the fourth tab", u.$("tab-settings").getAttribute("aria-selected") === "true" && u.$("tab-settings").tabIndex === 0);
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
  check("money: there are four tabs and Money sits between History and Settings", [...m.t.w.document.querySelectorAll('[role="tab"]')].map((b) => b.textContent).join(",") === "Today,History,Money,Settings");
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

  console.log(failures ? `\n${failures} FAILED` : "\nALL UI TESTS PASSED");
  process.exit(failures ? 1 : 0);
})();
