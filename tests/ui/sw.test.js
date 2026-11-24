// Runs the real web/sw.js in a sandbox with a fake service-worker global. No browser needed.
// Run:  cd tests/ui && node sw.test.js
const vm = require("vm");
const fs = require("fs");
const path = require("path");

const code = fs.readFileSync(path.join(__dirname, "..", "..", "web", "sw.js"), "utf8");
const ORIGIN = "https://tapan.example.com";

let failures = 0;
const check = (name, cond, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + name + (cond ? "" : "   " + extra)); if (!cond) failures++; };

function loadWorker({ windows = [], fetchImpl } = {}) {
  const handlers = {};
  const shown = [];
  const opened = [];
  const closedByTag = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, fn) => { handlers[type] = fn; },
    registration: {
      showNotification: (title, options) => { shown.push({ title, options }); return Promise.resolve(); },
      getNotifications: async ({ tag } = {}) => shown.filter((n) => n.options.tag === tag).map(() => ({ close() { closedByTag[tag] = (closedByTag[tag] || 0) + 1; } })),
    },
    clients: { matchAll: async () => windows, openWindow: async (url) => { opened.push(url); }, claim: async () => {} },
    skipWaiting: () => {},
  };
  const context = vm.createContext({ self, URL, Request: class {}, Response: class {}, caches: {}, fetch: fetchImpl || (async () => ({})), setTimeout: (fn, ms, ...a) => (ms >= 5000 ? (fn(...a), 0) : setTimeout(fn, ms, ...a)), Promise, Date, String, Boolean, JSON });
  vm.runInContext(code, context);
  const run = async (type, event) => {
    const pending = [];
    handlers[type]({ ...event, waitUntil: (p) => pending.push(p) });
    await Promise.all(pending);
  };
  return { handlers, shown, opened, closedByTag, run };
}

const pushEvent = (payload) => ({ data: payload === undefined ? null : { json: () => (typeof payload === "string" ? (() => { throw new SyntaxError("not json"); })() : payload), text: () => String(payload) } });
const clickEvent = (data) => { const n = { data, closed: false, close() { this.closed = true; } }; return { notification: n, n }; };
const fakeWindow = (url) => { const w = { url, focused: 0, messages: [], focus() { this.focused++; return Promise.resolve(this); }, postMessage(m) { this.messages.push(m); } }; return w; };

(async () => {
  // ── push ──
  let sw = loadWorker();
  await sw.run("push", pushEvent({ title: "Reminder", body: "Call mom · was due 9:00 AM", tag: "reminder-7", url: "/web/index.html?panel=today" }));
  const n = sw.shown[0];
  check("push: shows exactly one notification", sw.shown.length === 1);
  check("push: title, body and tag come from the message", n.title === "Reminder" && n.options.body === "Call mom · was due 9:00 AM" && n.options.tag === "reminder-7");
  check("push: re-alerts when the same tag is reused", n.options.renotify === true);
  check("push: has an icon and a separate monochrome badge", n.options.icon === "icons/icon-192.png" && n.options.badge === "icons/badge-96.png");
  check("push: stores the target url for the click handler", n.options.data.url === "/web/index.html?panel=today");
  check("push: vibrates", Array.isArray(n.options.vibrate) && n.options.vibrate.length > 0);

  sw = loadWorker();
  await sw.run("push", pushEvent({ title: "T".repeat(500), body: "B".repeat(2000) }));
  check("push: oversized title/body are clipped", sw.shown[0].title.length === 100 && sw.shown[0].options.body.length === 300);
  check("push: no tag => no renotify flag and the default target", sw.shown[0].options.tag === undefined && sw.shown[0].options.renotify === false && sw.shown[0].options.data.url === "/web/index.html?panel=today");

  sw = loadWorker();
  await sw.run("push", pushEvent("this is plain text, not JSON"));
  check("push: a non-JSON payload is still shown (browsers require every push to be visible)", sw.shown.length === 1 && sw.shown[0].options.body === "this is plain text, not JSON" && sw.shown[0].title === "Tapan");
  sw = loadWorker();
  await sw.run("push", pushEvent(undefined));
  check("push: an empty push is still shown, with a safe default", sw.shown.length === 1 && sw.shown[0].title === "Tapan" && sw.shown[0].options.body === "");
  sw = loadWorker();
  await sw.run("push", pushEvent({ title: "x", url: { evil: true } }));
  check("push: a non-string url falls back to the default", sw.shown[0].options.data.url === "/web/index.html?panel=today");

  // ── notification click ──
  sw = loadWorker({ windows: [fakeWindow(ORIGIN + "/web/index.html")] });
  let ev = clickEvent({ url: "/web/index.html?panel=today" });
  await sw.run("notificationclick", ev);
  check("click: the notification is dismissed", ev.n.closed === true);

  const open = fakeWindow(ORIGIN + "/web/index.html");
  sw = loadWorker({ windows: [open] });
  ev = clickEvent({ url: "/web/index.html?panel=today" });
  await sw.run("notificationclick", ev);
  check("click: an open app window is focused, not duplicated", open.focused === 1 && sw.opened.length === 0);
  check("click: ...and told to open the Today panel", JSON.stringify(open.messages) === JSON.stringify([{ type: "open-panel", panel: "today" }]));

  sw = loadWorker({ windows: [] });
  await sw.run("notificationclick", clickEvent({ url: "/web/index.html?panel=today" }));
  check("click: with no window open, the app is launched on the Today panel", sw.opened.length === 1 && sw.opened[0] === ORIGIN + "/web/index.html?panel=today", JSON.stringify(sw.opened));

  sw = loadWorker({ windows: [fakeWindow(ORIGIN + "/somewhere-else"), fakeWindow("https://other.example.com/web/index.html")] });
  await sw.run("notificationclick", clickEvent({ url: "/web/index.html?panel=today" }));
  check("click: windows that are not this app are never hijacked", sw.opened.length === 1);

  for (const [label, url] of [["a foreign origin", "https://evil.example.com/web/index.html"], ["a protocol-relative URL", "//evil.example.com/web/x"],
                              ["a javascript: URL", "javascript:alert(1)"], ["a path outside /web/", "/admin"], ["garbage", "http://[bad"], ["nothing", undefined]]) {
    sw = loadWorker({ windows: [] });
    await sw.run("notificationclick", clickEvent(url === undefined ? {} : { url }));
    check(`click: ${label} is never opened (falls back to the app)`, sw.opened.length === 1 && sw.opened[0] === ORIGIN + "/web/index.html?panel=today", JSON.stringify(sw.opened));
  }
  sw = loadWorker({ windows: [] });
  await sw.run("notificationclick", clickEvent(null));
  check("click: a notification without data does not throw", sw.opened.length === 1);

  // ── Snooze buttons ──
  const makeFetch = (impl) => { const calls = []; const fn = async (url, opts) => { calls.push({ url, opts }); return impl(url, opts); }; fn.calls = calls; return fn; };
  const okFetch = () => makeFetch(async () => ({ ok: true, status: 200, json: async () => ({ ok: true, label: "Snoozed until 9:10 PM" }) }));
  const snoozeData = { url: "/web/index.html?panel=today", reminder_id: 41, sigs: { "10": "SIG10", "60": "SIG60" } };

  sw = loadWorker();
  await sw.run("push", pushEvent({ title: "Reminder", body: "Call mom", tag: "reminder-41", reminder_id: 41, sigs: { "10": "A", "60": "B" },
    actions: [{ action: "snooze10", title: "Snooze 10 min" }, { action: "snooze60", title: "Snooze 1 h" }, { action: "third", title: "Too many" }] }));
  const withButtons = sw.shown[0].options;
  check("actions: the push shows at most two buttons with their labels", withButtons.actions.length === 2 && withButtons.actions[0].action === "snooze10" && withButtons.actions[1].title === "Snooze 1 h");
  check("actions: the reminder id and signatures travel in the notification's data", withButtons.data.reminder_id === 41 && withButtons.data.sigs["10"] === "A" && withButtons.data.sigs["60"] === "B");
  sw = loadWorker();
  await sw.run("push", pushEvent({ title: "x", actions: "not-an-array", sigs: "nope" }));
  check("actions: malformed action data is ignored safely", sw.shown[0].options.actions.length === 0 && JSON.stringify(sw.shown[0].options.data.sigs) === "{}");

  let f = okFetch();
  sw = loadWorker({ fetchImpl: f });
  ev = clickEvent(snoozeData); ev.action = "snooze10";
  await sw.run("notificationclick", ev);
  const call = f.calls[0];
  check("actions: tapping Snooze 10 posts the signed action to the server", f.calls.length === 1 && call.url === "/api/push/action" && call.opts.method === "POST" && JSON.parse(call.opts.body).m === 10 && JSON.parse(call.opts.body).s === "SIG10" && JSON.parse(call.opts.body).r === 41);
  check("actions: ...without credentials and without any access token", call.opts.credentials === "omit" && !JSON.stringify(call.opts.headers).toLowerCase().includes("authorization"));
  check("actions: ...the notification is dismissed and the app is NOT opened", ev.n.closed === true && sw.opened.length === 0);
  check("actions: a confirmation with the server's wording is shown, quietly", sw.shown.length === 1 && sw.shown[0].title === "Snoozed" && sw.shown[0].options.body === "Snoozed until 9:10 PM" && sw.shown[0].options.silent === true);
  check("actions: the confirmation cleans itself up", sw.closedByTag["snooze-41"] === 1);

  f = okFetch(); sw = loadWorker({ fetchImpl: f });
  ev = clickEvent(snoozeData); ev.action = "snooze60";
  await sw.run("notificationclick", ev);
  check("actions: Snooze 1 h uses its own signature", JSON.parse(f.calls[0].opts.body).m === 60 && JSON.parse(f.calls[0].opts.body).s === "SIG60");

  for (const [label, impl] of [["a server error", async () => ({ ok: false, status: 400, json: async () => ({}) })], ["a missing reminder", async () => ({ ok: false, status: 404, json: async () => ({}) })],
                               ["no network", async () => { throw new TypeError("Failed to fetch"); }]]) {
    sw = loadWorker({ fetchImpl: makeFetch(impl) });
    ev = clickEvent(snoozeData); ev.action = "snooze10";
    await sw.run("notificationclick", ev);
    check(`actions: ${label} => an honest 'Could not snooze' instead of silence`, sw.shown.length === 1 && sw.shown[0].title === "Could not snooze" && /try again/i.test(sw.shown[0].options.body));
  }
  f = okFetch(); sw = loadWorker({ fetchImpl: f });
  ev = clickEvent({ url: "/web/index.html" }); ev.action = "snooze10";
  await sw.run("notificationclick", ev);
  check("actions: a button without signature data never calls the server", f.calls.length === 0 && sw.shown[0].title === "Could not snooze");
  f = okFetch(); sw = loadWorker({ fetchImpl: f });
  ev = clickEvent(snoozeData); ev.action = "snooze999";
  await sw.run("notificationclick", ev);
  check("actions: an unknown snooze length has no signature, so nothing is sent", f.calls.length === 0);
  f = okFetch(); sw = loadWorker({ windows: [], fetchImpl: f });
  ev = clickEvent(snoozeData); ev.action = "open-something";
  await sw.run("notificationclick", ev);
  check("actions: any other action falls back to opening the app", f.calls.length === 0 && sw.opened.length === 1);
  f = okFetch(); sw = loadWorker({ windows: [], fetchImpl: f });
  ev = clickEvent(snoozeData);
  await sw.run("notificationclick", ev);
  check("actions: tapping the body (no action) still just opens the app", f.calls.length === 0 && sw.opened.length === 1);

  // ── the existing offline behaviour is untouched ──
  const fetchEvents = [];
  sw = loadWorker();
  for (const [url, expectHandled] of [["/api/push/key", false], ["/api/briefing", false], ["/chat", false], ["/health", false], ["/web/app.js", true]]) {
    let handled = false;
    sw.handlers.fetch({ request: { method: "GET", url: ORIGIN + url, mode: "no-cors" }, respondWith: () => { handled = true; }, waitUntil() {} });
    check(`fetch: ${url} ${expectHandled ? "is served by the worker" : "bypasses the worker"}`, handled === expectHandled);
  }
  let postHandled = false;
  sw.handlers.fetch({ request: { method: "POST", url: ORIGIN + "/web/app.js", mode: "no-cors" }, respondWith: () => { postHandled = true; }, waitUntil() {} });
  check("fetch: non-GET requests are never intercepted", postHandled === false);

  console.log(failures ? `\n${failures} FAILED` : "\nALL SERVICE WORKER TESTS PASSED");
  process.exit(failures ? 1 : 0);
})();
