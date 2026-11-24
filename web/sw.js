// TAPAN_AI service worker: makes the app installable and keeps the *shell* available offline.
//
// What it caches: the app's own static files (HTML/CSS/JS/icons) and the three CDN libraries it uses.
// What it NEVER touches: /api/*, /chat, /health, WebSockets — conversations and data always come live from the server,
// and are never stored by the service worker.
//
// Push: the server sends an (end-to-end encrypted) JSON message {title, body, tag, url}; the handler below always shows
// a notification, because browsers require every push to be visible. Tapping it opens/focuses the app on the Today panel.
//
// Strategy: network-first for our own files (so a deploy is picked up on the next load) but with a 4 s patience limit —
// if the server is asleep (free hosting) or you are offline, the cached shell opens instantly and the page itself
// shows "Waking the server…" / "Offline" instead of a blank browser error.

const VERSION = "tapan-shell-v4";
const RUNTIME = "tapan-cdn-v1";
const SHELL = [
    "index.html", "style.css", "app.js", "settings.js", "settings-integrations.js", "money.js", "manifest.webmanifest",
    "icon.svg", "icons/icon-192.png", "icons/icon-512.png", "icons/icon-maskable-512.png", "icons/badge-96.png",
];
const CDN_HOSTS = ["cdnjs.cloudflare.com", "cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"];
const NETWORK_PATIENCE_MS = 4000;

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches.open(VERSION)
            .then((cache) => cache.addAll(SHELL.map((path) => new Request(path, { cache: "reload" }))))
            .then(() => self.skipWaiting()),
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k.startsWith("tapan-") && k !== VERSION && k !== RUNTIME).map((k) => caches.delete(k))))
            .then(() => self.clients.claim()),
    );
});

function isOurStatic(url) {
    return url.origin === self.location.origin && url.pathname.startsWith("/web/");
}

async function networkFirst(event, request) {
    const cache = await caches.open(VERSION);
    const fresh = fetch(request).then((response) => {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
    });
    const cached = () => cache.match(request, { ignoreSearch: true });
    try {
        const patience = new Promise((_, reject) => setTimeout(() => reject(new Error("slow")), NETWORK_PATIENCE_MS));
        return await Promise.race([fresh, patience]);
    } catch (err) {
        const hit = await cached();
        if (hit) {
            event.waitUntil(fresh.catch(() => undefined));   // let the slow request finish and refresh the cache
            return hit;
        }
        return fresh;                                        // nothing cached yet: wait for the network
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(RUNTIME);
    const hit = await cache.match(request);
    const refresh = fetch(request).then((response) => {
        if (response && (response.ok || response.type === "opaque")) cache.put(request, response.clone());
        return response;
    });
    return hit || refresh;
}

self.addEventListener("fetch", (event) => {
    const request = event.request;
    if (request.method !== "GET") return;
    const url = new URL(request.url);

    if (isOurStatic(url)) {
        if (request.mode === "navigate") {
            event.respondWith(
                networkFirst(event, request).catch(async () => (await caches.match("index.html", { ignoreSearch: true })) || Response.error()),
            );
        } else {
            event.respondWith(networkFirst(event, request));
        }
        return;
    }
    if (CDN_HOSTS.includes(url.hostname)) {
        event.respondWith(staleWhileRevalidate(request).catch(() => Response.error()));
    }
    // everything else (the API, chat, health, other origins) goes straight to the network, untouched
});


// ── Web Push ──────────────────────────────────────────────────────
const APP_HOME = "/web/index.html?panel=today";

function parsePush(event) {
    if (!event.data) return {};
    try { return event.data.json() || {}; } catch (err) {
        try { return { body: event.data.text() }; } catch (err2) { return {}; }   // a plain-text payload still gets shown
    }
}

self.addEventListener("push", (event) => {
    const data = parsePush(event);
    const title = String(data.title || "Tapan").slice(0, 100);
    const tag = data.tag ? String(data.tag).slice(0, 100) : undefined;
    event.waitUntil(
        self.registration.showNotification(title, {
            body: String(data.body || "").slice(0, 300),
            tag,
            renotify: Boolean(tag),                         // same tag again (e.g. a repeated test) should still alert, not update silently
            icon: "icons/icon-192.png",
            badge: "icons/badge-96.png",
            vibrate: [120, 60, 120],
            timestamp: Date.now(),
            actions: Array.isArray(data.actions) ? data.actions.slice(0, 2).map((a) => ({ action: String(a.action).slice(0, 30), title: String(a.title).slice(0, 40) })) : [],
            data: { url: typeof data.url === "string" ? data.url : APP_HOME, reminder_id: data.reminder_id, sigs: data.sigs && typeof data.sigs === "object" ? data.sigs : {} },
        }),
    );
});

// Only ever open pages that belong to this app, even though the message came from our own (authenticated, encrypted) server.
function safeTarget(raw) {
    try {
        const url = new URL(raw, self.location.origin);
        if (url.origin === self.location.origin && url.pathname.startsWith("/web/")) return url;
    } catch (err) { /* fall through */ }
    return new URL(APP_HOME, self.location.origin);
}

// A Snooze button: ask the server to snooze exactly this reminder, proving it with the signature that came with the push.
// No access token is ever stored in (or sent from) the service worker.
async function snoozeFromNotification(data, minutes) {
    const common = { icon: "icons/icon-192.png", badge: "icons/badge-96.png", silent: true, data: { url: APP_HOME } };
    const id = data && data.reminder_id;
    let title = "Snoozed";
    let body = "";
    try {
        const sig = data && data.sigs && data.sigs[String(minutes)];
        if (!id || !sig) throw new Error("missing action data");
        const res = await fetch("/api/push/action", {
            method: "POST", credentials: "omit", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ r: id, m: minutes, s: sig }),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        body = String((await res.json()).label || `Back in ${minutes} min`);
    } catch (err) {
        title = "Could not snooze";
        body = "Open Tapan and try again.";
    }
    const tag = `snooze-${id || "x"}`;
    await self.registration.showNotification(title, { ...common, tag, body });
    await new Promise((resolve) => setTimeout(resolve, 6000));          // a confirmation, not clutter: remove it shortly
    const shown = await self.registration.getNotifications({ tag });
    shown.forEach((n) => n.close());
}

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const snooze = /^snooze(\d+)$/.exec(event.action || "");
    if (snooze) {
        event.waitUntil(snoozeFromNotification(event.notification.data, Number(snooze[1])));
        return;
    }
    const target = safeTarget(event.notification.data && event.notification.data.url);
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (windows) => {
            const open = windows.find((w) => new URL(w.url).origin === self.location.origin && new URL(w.url).pathname.startsWith("/web/"));
            if (open) {
                if ("focus" in open) await open.focus();
                open.postMessage({ type: "open-panel", panel: target.searchParams.get("panel") || "today" });
                return undefined;
            }
            return self.clients.openWindow(target.href);
        }),
    );
});
