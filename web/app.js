// TAPAN_AI web client — chat, history, Today panel, voice and the live status orb.
// No build step: plain browser JavaScript. Test hook: set window.__TAPAN_NO_AUTOINIT before loading to call init() yourself.

// The server replaces the placeholder with this build's hash when it serves the file. Written split so the replacement
// does not also rewrite the comparison below. In development (no replacement) update checks are skipped.
const WEB_VERSION = '__WEB_VERSION__';
const WEB_VERSION_KNOWN = WEB_VERSION !== '__WEB_' + 'VERSION__';

// ── Small helpers ─────────────────────────────────────────────────
function $(id) { return document.getElementById(id); }

function store(key, value) {
    try {
        if (value === undefined) return localStorage.getItem(key);
        if (value === null) localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    } catch (e) { /* storage blocked: stay in memory */ }
    return null;
}

function h(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
}

const ICON = {
    copy: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path fill="currentColor" d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z"/></svg>',
};

function parseTs(ts) {
    const d = ts ? new Date(ts) : new Date();
    return isNaN(d.getTime()) ? new Date() : d;
}
function fmtTime(d) { return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
function dayKey(d) { return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`; }
function dayLabel(d) {
    const now = new Date();
    const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
    if (dayKey(d) === dayKey(now)) return 'Today';
    if (dayKey(d) === dayKey(yesterday)) return 'Yesterday';
    return d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' });
}
function whenLabel(d) {
    const now = new Date();
    const tomorrow = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
    const time = fmtTime(d);
    if (dayKey(d) === dayKey(now)) return `Today · ${time}`;
    if (dayKey(d) === dayKey(tomorrow)) return `Tomorrow · ${time}`;
    return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} · ${time}`;
}

// ── State ─────────────────────────────────────────────────────────
const state = {
    // One shared thread by default ("main"), so every device continues the same conversation.
    sessionId: store('tapan.session') || 'main',
    token: store('tapan.token') || '',
    voiceMode: store('tapan.voice') || 'voice',      // voice = speak replies only after I used the mic | always | off
    lastNotificationId: parseInt(store('tapan.lastNotification') || '0', 10) || 0,
    socket: null, seq: 0, retry: 0, retryTimer: null, wakeTimer: null,
    conn: 'connecting', everOnline: false, authNeeded: false, historyFor: null,
    busy: false, busyTimer: null, workEl: null, activity: [], pendingResync: false,
    lastSent: '', lastInputWasVoice: false, lastDay: null, unread: 0, tab: 'today', baseTitle: document.title,
    isSpeaking: false, isListening: false, recognition: null, voices: [], selectedVoice: null,
};

const dom = {};
function bindDom() {
    Object.assign(dom, {
        app: $('app'), chat: $('chat-history'), empty: $('empty-state'), greeting: $('greeting'),
        attachBtn: $('attach-btn'), fileInput: $('file-input'), tray: $('attach-tray'),
        userInput: $('user-input'), sendBtn: $('send-btn'), voiceBtn: $('voice-toggle'), composer: $('composer'),
        pill: $('conn-pill'), statusText: document.querySelector('.status-text'),
        jump: $('jump-btn'), jumpLabel: $('jump-label'), toast: $('toast'), scrim: $('scrim'),
        side: $('side-panel'), sideClose: $('side-close'), panelToday: $('panel-today'), panelHistory: $('panel-history'),
        panelSettings: $('panel-settings'), panelMoney: $('panel-money'), panelWork: $('panel-work'), panelGrowth: $('panel-growth'), tabToday: $('tab-today'), tabHistory: $('tab-history'), tabMoney: $('tab-money'), tabWork: $('tab-work'), tabGrowth: $('tab-growth'), tabSettings: $('tab-settings'),
        updateBanner: $('update-banner'), updateReload: $('update-reload'),
        todayBtn: $('today-btn'), historyBtn: $('history-btn'), newBtn: $('new-chat-btn'), lockBtn: $('lock-btn'),
        voiceModeBtn: $('voice-mode-btn'), voiceModeLabel: $('voice-mode-label'), stopBtn: $('stop-speech-btn'),
        orbCanvas: $('avatar-canvas'), srStatus: $('sr-status'),
        topbar: document.querySelector('.topbar'), chatMain: document.querySelector('.chat'),
        installBtn: $('install-btn'), installBanner: $('install-banner'), installYes: $('install-yes'), installNo: $('install-no'),
        installSheet: $('install-sheet'), installSteps: $('install-steps'), installClose: $('install-close'),
        bnav: $('bottom-nav'), panelTitle: $('panel-title'), themeBtn: $('theme-btn'), moreSheet: $('more-sheet'), moreClose: $('more-close'), moreHistory: $('more-history'),
        moreSettings: $('more-settings'), moreInstall: $('more-install'), moreLock: $('more-lock'),
        authOverlay: $('auth-overlay'), authForm: $('auth-form'), authInput: $('auth-input'), authMsg: $('auth-msg'),
    });
}

// ── Screen-reader announcements ───────────────────────────────────
function announce(text) {
    if (!dom.srStatus) return;
    dom.srStatus.textContent = '';                 // clear first so repeating the same sentence is announced again
    setTimeout(() => { dom.srStatus.textContent = text; }, 30);
}

// ── Focus helpers (dialogs, drawer) ───────────────────────────────
const FOCUSABLE = 'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
function trapTab(container, event) {
    if (event.key !== 'Tab') return;
    const items = [...container.querySelectorAll(FOCUSABLE)].filter((el) => !el.closest('.hidden') && !el.hidden);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
}
function setInert(el, on) { if (el) { if (on) el.setAttribute('inert', ''); else el.removeAttribute('inert'); } }

// ── Toast ─────────────────────────────────────────────────────────
let toastTimer = null;
function toast(message, ms = 2400) {
    dom.toast.textContent = message;
    dom.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => dom.toast.classList.remove('show'), ms);
}

// ── Access gate ───────────────────────────────────────────────────
const AUTH_DEFAULT_MSG = 'This assistant is private. Enter your access token to unlock it.';

function showAuth(rejectedToken) {
    state.authNeeded = true;
    setConn('locked', 'Locked');
    dom.authMsg.textContent = rejectedToken ? 'That token was not accepted. Check it and try again.' : AUTH_DEFAULT_MSG;
    dom.authMsg.classList.toggle('error', Boolean(rejectedToken));
    dom.authOverlay.classList.remove('hidden');
    setInert(dom.app, true);
    dom.authInput.value = '';
    dom.authInput.focus();
}

function hideAuth() {
    state.authNeeded = false;
    dom.authOverlay.classList.add('hidden');
    setInert(dom.app, false);
}

function rejectToken() {
    const had = Boolean(state.token);
    if (had) { state.token = ''; store('tapan.token', null); }
    showAuth(had);
}

// ── REST helper (adds the token, reacts to 401) ───────────────────
// ── Loading feedback ──────────────────────────────────────────────
// Every request made through api() shows that something is happening: a bar across the top and a small status pill ("Saving…",
// "Loading…", "Deleting…") that appears if the answer takes more than a moment, counts the seconds, and admits when it is slow.
// Background polling is not announced. Screen readers hear one short message when it starts and one if it is slow, not a ticking clock.
const NET = { showWrite: 150, showRead: 700, counting: 3, slow: 8 };      // ms / s thresholds (tests shorten them)
const netState = { active: [], showTimer: null, ticker: null, started: 0, spoke: false, slowSpoken: false };
const QUIET_REQUESTS = /^\/api\/(notifications|briefing|client-report|push\/key)/;
function netText() {
    const secs = Math.floor((Date.now() - netState.started) / 1000);
    const last = netState.active[netState.active.length - 1];
    if (secs >= NET.slow) return 'Still working… the server is slow right now';
    return last ? last.label + (secs >= NET.counting ? ` ${secs}s` : '') : '';
}
function netPaint() {
    const text = netText();
    const pill = document.getElementById('busy-text');
    if (pill) pill.textContent = text;
    const sr = document.getElementById('busy-sr');
    if (sr) {
        const secs = Math.floor((Date.now() - netState.started) / 1000);
        if (!netState.spoke) { sr.textContent = netState.active.length ? netState.active[netState.active.length - 1].label : ''; netState.spoke = true; }
        else if (secs >= NET.slow && !netState.slowSpoken) { sr.textContent = 'Still working. The server is slow right now.'; netState.slowSpoken = true; }
    }
}
function netShow(visible) {
    ['busy', 'busy-bar'].forEach((id) => { const el = document.getElementById(id); if (el) el.classList.toggle('hidden', !visible); });
    document.body.classList.toggle('is-busy', visible);
}
function netStart(op) {
    netState.active.push(op);
    if (netState.active.length > 1) return;
    netState.started = Date.now(); netState.spoke = false; netState.slowSpoken = false;
    netState.showTimer = setTimeout(() => { netShow(true); netPaint(); netState.ticker = setInterval(netPaint, 1000); }, op.delay);
}
function netStop(op) {
    netState.active = netState.active.filter((o) => o !== op);
    if (netState.active.length) return;
    clearTimeout(netState.showTimer); clearInterval(netState.ticker);
    netShow(false);
    const sr = document.getElementById('busy-sr');
    if (sr) sr.textContent = '';
}

async function api(path, options = {}) {
    const headers = Object.assign({}, options.headers || {});
    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    const method = String(options.method || 'GET').toUpperCase();
    const op = QUIET_REQUESTS.test(path) ? null : { label: method === 'GET' ? 'Loading…' : method === 'DELETE' ? 'Deleting…' : 'Saving…', delay: method === 'GET' ? NET.showRead : NET.showWrite };
    if (op) netStart(op);
    try {
        const res = await fetch(path, Object.assign({}, options, { headers }));
        if (res.status === 401) {
            if (!state.authNeeded) rejectToken();
            throw new Error('unauthorized');
        }
        if (!res.ok) { const err = new Error(`HTTP ${res.status}`); err.status = res.status; err.response = res; throw err; }
        return await res.json();
    } finally {
        if (op) netStop(op);
    }
}

// ── Connection ────────────────────────────────────────────────────
function setConn(kind, label) {
    state.conn = kind;
    dom.pill.dataset.state = kind;
    dom.statusText.textContent = label;
    dom.app.dataset.conn = kind === 'busy' ? 'online' : kind;
    dom.lockBtn.classList.toggle('hidden', !state.token);
}

function connect() {
    clearTimeout(state.retryTimer);
    clearTimeout(state.wakeTimer);
    const seq = ++state.seq;                       // events from superseded sockets are ignored
    if (state.socket) {
        try { state.socket.onclose = null; state.socket.close(); } catch (e) { /* already closed */ }
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // The token goes in the first frame, never in the URL (URLs are written to server access logs).
    const url = `${proto}//${window.location.host}/ws/${encodeURIComponent(state.sessionId)}`;
    const sentToken = Boolean(state.token);

    if (!state.authNeeded) setConn(state.everOnline ? 'reconnecting' : 'connecting', state.everOnline ? 'Reconnecting…' : 'Connecting…');
    // Free hosting plans put the server to sleep when idle; say so instead of looking broken.
    state.wakeTimer = setTimeout(() => {
        if (seq === state.seq && state.conn !== 'online' && state.conn !== 'busy' && !state.authNeeded) {
            setConn(state.conn, 'Waking the server…');
        }
    }, 6000);

    const ws = new WebSocket(url);
    state.socket = ws;

    ws.onopen = () => {
        if (seq !== state.seq) return;
        ws.send(JSON.stringify({ auth: state.token }));
    };
    ws.onmessage = (event) => {
        if (seq !== state.seq) return;
        let data;
        try { data = JSON.parse(event.data); } catch (e) { return; }
        handleSocketMessage(data);
    };
    ws.onclose = (event) => {
        if (seq !== state.seq) return;
        clearTimeout(state.wakeTimer);
        if (state.busy) { endWork(); state.pendingResync = true; toast('Connection dropped mid-answer. It will appear in History if I finished.', 4000); }
        if (event.code === 4401) {                 // the server wants a token: stop retrying until the user supplies one
            if (sentToken) { state.token = ''; store('tapan.token', null); }
            showAuth(sentToken);
            return;
        }
        scheduleReconnect(seq);
    };
}

function scheduleReconnect(seq) {
    const delay = Math.min(1000 * 2 ** state.retry, 15000);
    state.retry += 1;
    setConn(navigator.onLine === false ? 'offline' : 'reconnecting', navigator.onLine === false ? 'Offline' : 'Reconnecting…');
    state.retryTimer = setTimeout(() => { if (seq === state.seq) connect(); }, delay);
}

function onAuthenticated() {
    clearTimeout(state.wakeTimer);
    hideAuth();
    state.everOnline = true;
    state.retry = 0;
    setConn(state.busy ? 'busy' : 'online', state.busy ? 'Thinking…' : 'Online');
    if (state.historyFor !== state.sessionId || state.pendingResync) {
        const replace = state.pendingResync;
        state.pendingResync = false;
        loadHistory(replace);
    }
    refreshToday(true);
    pushRefresh();
    checkForUpdate();
    scheduleClientReport();
    if (state.tab === 'history') loadConversations();
}

function handleSocketMessage(data) {
    switch (data.type) {
        case 'auth_ok': onAuthenticated(); return;
        case 'tool_start': addActivity(data.name); return;
        case 'tool_end': finishActivity(data.name, data.ok !== false); return;
        default: finalReply(data);
    }
}

// ── Chat rendering ────────────────────────────────────────────────
let sanitizerReady = false;
function renderInto(bubble, text, role) {
    if (role === 'assistant' && window.marked && window.DOMPurify) {
        if (!sanitizerReady) {
            DOMPurify.addHook('afterSanitizeAttributes', (node) => {
                if (node.tagName === 'A') { node.setAttribute('target', '_blank'); node.setAttribute('rel', 'noopener noreferrer'); }
            });
            sanitizerReady = true;
        }
        // Assistant text may echo web content: always sanitize before injecting HTML.
        bubble.innerHTML = DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }));
    } else {
        bubble.textContent = text;                 // plain text (line breaks kept by CSS); never interpreted as HTML
    }
}

function nearBottom() { return dom.chat.scrollHeight - dom.chat.scrollTop - dom.chat.clientHeight < 140; }
function scrollToBottom(smooth = true) {
    if (typeof dom.chat.scrollTo === 'function') dom.chat.scrollTo({ top: dom.chat.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    else dom.chat.scrollTop = dom.chat.scrollHeight;
    state.unread = 0;
    dom.jump.classList.add('hidden');
}

function copyText(text, button) {
    const done = () => {
        button.innerHTML = `${ICON.check}<span>Copied</span>`;
        setTimeout(() => { button.innerHTML = `${ICON.copy}<span>Copy</span>`; }, 1500);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, () => toast('Could not copy'));
        return;
    }
    const area = h('textarea');
    area.value = text;
    document.body.appendChild(area);
    area.select();
    try { document.execCommand('copy'); done(); } catch (e) { toast('Could not copy'); }
    area.remove();
}

function addMessage(text, role, opts = {}) {
    const when = parseTs(opts.ts);
    const stick = opts.instant ? false : (role === 'user' || nearBottom());

    if (state.lastDay !== dayKey(when)) {
        dom.chat.appendChild(h('div', 'day-sep', dayLabel(when)));
        state.lastDay = dayKey(when);
    }

    const row = h('div', `message ${role}`);
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', `${role === 'user' ? 'You' : 'Tapan'}, ${fmtTime(when)}`);
    if (role === 'assistant') { const av = h('div', 'avatar', 'T'); av.setAttribute('aria-hidden', 'true'); row.appendChild(av); }
    const body = h('div', 'msg-body');
    if ((opts.images || []).length) {
        const pics = h('div', 'msg-images');
        opts.images.forEach((src, i) => { const img = h('img'); img.src = src; img.alt = `Picture ${i + 1} you attached`; img.addEventListener('load', () => { if (stick) scrollToBottom(); }); pics.appendChild(img); });
        body.appendChild(pics);
    }
    if (text) {
        const bubble = h('div', 'bubble');
        renderInto(bubble, text, role);
        body.appendChild(bubble);
    }

    const meta = h('div', 'meta');
    const time = h('time', null, fmtTime(when));
    time.title = when.toLocaleString();
    meta.appendChild(time);
    (opts.tools || []).forEach((t) => meta.appendChild(h('span', `tool-chip ${t.ok === false ? 'error' : 'done'}`, t.label)));
    if (opts.note) meta.appendChild(h('span', 'tool-chip note', opts.note));
    if (text) {                                             // a picture-only message has nothing to copy
        const copy = h('button', 'copy-btn');
        copy.type = 'button';
        copy.setAttribute('aria-label', role === 'user' ? 'Copy your message' : 'Copy Tapan\'s message');
        copy.innerHTML = `${ICON.copy}<span>Copy</span>`;
        copy.addEventListener('click', () => copyText(text, copy));
        meta.appendChild(copy);
    }
    body.appendChild(meta);

    row.appendChild(body);
    dom.chat.appendChild(row);
    dom.empty.classList.add('hidden');

    if (stick) scrollToBottom();
    else if (!opts.instant) {
        state.unread += 1;
        dom.jumpLabel.textContent = state.unread > 1 ? `${state.unread} new messages` : 'New message';
        dom.jump.classList.remove('hidden');
    }
    if (role === 'assistant' && document.hidden && !opts.instant) {
        document.title = `● ${state.baseTitle}`;
    }
    return row;
}

function clearChat() {
    dom.chat.replaceChildren();
    state.lastDay = null;
    state.unread = 0;
    dom.jump.classList.add('hidden');
    dom.empty.classList.remove('hidden');
}

// ── Work-in-progress indicator (typing dots + live tool chips) ────
const TOOL_LABELS = {
    set_reminder: 'Setting reminder', set_reminders: 'Setting reminders', list_reminders: 'Checking reminders',
    cancel_reminder: 'Cancelling reminder', add_task: 'Adding task', list_tasks: 'Checking tasks',
    complete_task: 'Completing task', delete_task: 'Deleting task', add_note: 'Saving note', search_notes: 'Searching notes',
    delete_note: 'Deleting note', remember: 'Saving to memory', recall: 'Recalling', forget: 'Forgetting',
    search_history: 'Searching past chats', web_search: 'Searching the web', fetch_url: 'Reading a page',
    get_weather: 'Checking weather', daily_briefing: 'Preparing briefing', calculate: 'Calculating',
    get_current_time: 'Checking the time', finance_assistant: 'Updating finances', people_assistant: 'Checking contacts',
    calendar_assistant: 'Checking calendar', read_file: 'Reading a file', write_file: 'Writing a file', list_files: 'Listing files',
    open_url: 'Opening a link', open_app: 'Opening an app', system_info: 'Checking the system',
};
function toolLabel(name) {
    return TOOL_LABELS[name] || String(name || 'Working').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

function beginWork() {
    state.busy = true;
    state.activity = [];
    setConn('busy', 'Thinking…');
    dom.app.dataset.orb = 'thinking';
    announce('Tapan is thinking');

    const row = h('div', 'message assistant working');
    const wav = h('div', 'avatar', 'T');
    wav.setAttribute('aria-hidden', 'true');
    row.appendChild(wav);
    const body = h('div', 'msg-body');
    const bubble = h('div', 'bubble');
    const dots = h('div', 'typing');
    dots.setAttribute('aria-label', 'Tapan is thinking');
    dots.append(h('span'), h('span'), h('span'));
    bubble.appendChild(dots);
    body.appendChild(bubble);
    body.appendChild(h('div', 'tools'));
    row.appendChild(body);
    dom.chat.appendChild(row);
    state.workEl = row;
    scrollToBottom();

    clearTimeout(state.busyTimer);
    state.busyTimer = setTimeout(() => {
        if (!state.busy) return;
        endWork();
        state.pendingResync = true;
        addMessage('This is taking unusually long. If I do finish, the answer will be saved in History.', 'assistant', { note: 'timeout' });
    }, 120000);
    refreshSend();
}

function endWork() {
    clearTimeout(state.busyTimer);
    state.busy = false;
    if (state.workEl) { state.workEl.remove(); state.workEl = null; }
    dom.app.dataset.orb = state.isSpeaking ? 'speaking' : 'idle';
    if (state.conn === 'busy') setConn('online', 'Online');
    refreshSend();
}

function addActivity(name) {
    if (!state.workEl) return;
    const chip = h('span', 'tool-chip running', toolLabel(name));
    state.workEl.querySelector('.tools').appendChild(chip);
    state.activity.push({ name, chip, ok: null, label: toolLabel(name) });
    setConn('busy', `${toolLabel(name)}…`);
    if (nearBottom()) scrollToBottom();
}

function finishActivity(name, ok) {
    const entry = state.activity.find((a) => a.name === name && a.ok === null);
    if (!entry) return;
    entry.ok = ok;
    entry.chip.className = `tool-chip ${ok ? 'done' : 'error'}`;
    setConn('busy', 'Thinking…');
}

function finalReply(data) {
    const setReminder = state.activity.some((a) => (a.name === 'set_reminder' || a.name === 'set_reminders') && a.ok !== false);
    const tools = state.activity.map((a) => ({ label: a.label, ok: a.ok !== false }));
    // identical consecutive chips (e.g. calculate ×3) collapse to one for the transcript
    const unique = tools.filter((t, i) => i === 0 || t.label !== tools[i - 1].label || t.ok !== tools[i - 1].ok);
    endWork();
    const legacy = data.debug && data.debug.mode === 'legacy';
    addMessage(data.text || '…', 'assistant', { tools: unique, note: legacy ? 'basic offline mode' : null });
    if (tools.length) refreshToday(true);
    if (setReminder) offerPush();
    maybeSpeak(data.text);
}

// ── Composer ──────────────────────────────────────────────────────
const INPUT_PLACEHOLDER = 'Message Tapan…';
// On touch screens there is no Shift key, so Enter inserts a newline and the send button sends.
const enterSends = !(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);

function autoGrow() {
    const el = dom.userInput;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 180) + 'px';
}
function refreshSend() { dom.sendBtn.disabled = state.busy || !(dom.userInput.value.trim() || (state.attach || []).length); }

// ── Pictures ──────────────────────────────────────────────────────
// Chosen, pasted or dropped pictures are shrunk here (long side 1280 px, JPEG under about 1.2 MB) so a phone photo does not cost
// the user's data or the server's patience; the server re-checks everything. The picture is described by a vision model on the
// server and only the description is kept.
const PIC = { max: 3, maxSide: 1280, maxBytes: 1200000, types: /^image\/(jpeg|png|webp|gif|heic|heif)$/i };
state.attach = [];
let picSeq = 0;

function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.onerror = () => reject(new Error('read')); r.readAsDataURL(blob); });
}
function canvasToBlob(canvas, quality) {
    return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('encode'))), 'image/jpeg', quality));
}
async function loadBitmap(file) {
    if (window.createImageBitmap) {
        try { return await window.createImageBitmap(file, { imageOrientation: 'from-image' }); } catch (e) { /* fall back to an <img> */ }
    }
    const url = URL.createObjectURL(file);
    try {
        const img = await new Promise((resolve, reject) => { const i = new Image(); i.onload = () => resolve(i); i.onerror = () => reject(new Error('decode')); i.src = url; });
        return img;
    } finally { URL.revokeObjectURL(url); }
}
async function prepareImage(file) {
    const bitmap = await loadBitmap(file);
    const w0 = bitmap.width || bitmap.naturalWidth, h0 = bitmap.height || bitmap.naturalHeight;
    let scale = Math.min(1, PIC.maxSide / Math.max(w0, h0));
    for (let attempt = 0; attempt < 3; attempt += 1) {
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(w0 * scale)); canvas.height = Math.max(1, Math.round(h0 * scale));
        const g = canvas.getContext('2d');
        g.fillStyle = '#ffffff'; g.fillRect(0, 0, canvas.width, canvas.height);          // transparent PNGs become white, not black
        g.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        let quality = 0.82, blob = await canvasToBlob(canvas, quality);
        while (blob.size > PIC.maxBytes && quality > 0.5) { quality -= 0.12; blob = await canvasToBlob(canvas, quality); }
        if (blob.size <= PIC.maxBytes || attempt === 2) {
            if (blob.size > PIC.maxBytes) throw new Error('too large');
            if (bitmap.close) bitmap.close();
            return { dataUrl: await blobToDataUrl(blob), preview: URL.createObjectURL(blob), name: file.name || 'picture' };
        }
        scale *= 0.75;
    }
    throw new Error('too large');
}
const imageTools = { prepare: prepareImage };          // replaceable (tests have no canvas)

function renderTray() {
    const items = state.attach.map((p, i) => {
        const li = h('li', 'attach-chip');
        const img = h('img'); img.src = p.preview; img.alt = `Picture ${i + 1}: ${p.name}`;
        const x = h('button', 'attach-x'); x.type = 'button'; x.setAttribute('aria-label', `Remove picture ${i + 1}: ${p.name}`);
        x.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z"/></svg>';
        x.addEventListener('click', () => removePicture(p.id));
        li.append(img, x);
        return li;
    });
    dom.tray.replaceChildren(...items);
    dom.tray.classList.toggle('hidden', !items.length);
    dom.attachBtn.setAttribute('aria-label', items.length ? `Attach another picture (${items.length} of ${PIC.max} attached)` : 'Attach a picture');
}
function removePicture(id) {
    const p = state.attach.find((x) => x.id === id);
    state.attach = state.attach.filter((x) => x.id !== id);
    if (p && URL.revokeObjectURL) { try { URL.revokeObjectURL(p.preview); } catch (e) { /* already gone */ } }
    renderTray(); refreshSend();
    announce('Picture removed');
    dom.attachBtn.focus();
}
async function addPictures(files) {
    const list = Array.from(files || []).filter(Boolean);
    if (!list.length) return;
    const okFiles = list.filter((f) => PIC.types.test(f.type || ''));
    if (!okFiles.length) { toast('That is not a picture I can read. Use a JPEG, PNG, WebP or GIF.', 3500); return; }
    const room = PIC.max - state.attach.length;
    if (room <= 0) { toast(`You can attach up to ${PIC.max} pictures at a time.`, 3000); return; }
    const take = okFiles.slice(0, room);
    if (okFiles.length > take.length) toast(`Only ${PIC.max} pictures at a time. Added the first ${take.length}.`, 3500);
    else if (okFiles.length < list.length) toast('Some files were not pictures and were skipped.', 3000);
    dom.attachBtn.setAttribute('aria-busy', 'true');
    for (const file of take) {
        try { state.attach.push(Object.assign({ id: ++picSeq }, await imageTools.prepare(file))); }
        catch (e) { toast(`Could not read ${file.name || 'that picture'}. Try another.`, 3500); }
    }
    dom.attachBtn.removeAttribute('aria-busy');
    renderTray(); refreshSend();
    if (state.attach.length) announce(`${state.attach.length} picture${state.attach.length === 1 ? '' : 's'} attached. Add a message or just send.`);
}

function sendMessage(override, opts = {}) {
    const text = (override !== undefined && override !== null ? override : dom.userInput.value).trim();  // ends only; inner line breaks stay
    const pics = override === undefined || override === null ? state.attach.slice() : [];
    if (!text && !pics.length) return false;
    if (state.busy) { toast('Still working on your last message…'); return false; }
    if (!state.socket || state.socket.readyState !== WebSocket.OPEN || state.conn === 'locked') {
        toast('Not connected yet — reconnecting…');
        return false;
    }
    state.lastSent = text;
    state.lastInputWasVoice = Boolean(opts.voice);
    addMessage(text, 'user', { images: pics.map((p) => p.preview) });
    if (override === undefined || override === null) { dom.userInput.value = ''; autoGrow(); }
    beginWork();
    if (pics.length) {
        state.socket.send(JSON.stringify({ type: 'message', text, images: pics.map((p) => p.dataUrl) }));     // pictures ride in a JSON frame; plain text stays plain
        state.attach = [];                                  // the previews now live in the message bubble, so they are not revoked here
        renderTray(); refreshSend();
    } else state.socket.send(text);
    return true;
}

function useStarter(button) {
    if (button.dataset.send) { sendMessage(button.dataset.send); return; }
    const text = button.dataset.fill || '';
    dom.userInput.value = text;
    autoGrow();
    refreshSend();
    dom.userInput.focus();
    const firstBreak = text.indexOf('\n');
    const caret = firstBreak === -1 ? text.length : firstBreak;
    dom.userInput.setSelectionRange(caret, caret);
}

// ── History & conversations ───────────────────────────────────────
async function loadHistory(replace) {
    try {
        const { messages } = await api(`/api/history?session_id=${encodeURIComponent(state.sessionId)}&limit=60`);
        state.historyFor = state.sessionId;
        if (replace || dom.chat.children.length === 0) {
            dom.chat.setAttribute('aria-busy', 'true');         // restored history is not announced message by message
            clearChat();
            messages.forEach((m) => addMessage(m.text, m.role, { ts: m.ts, instant: true }));
            if (messages.length) scrollToBottom(false);
            dom.chat.setAttribute('aria-busy', 'false');
            if (messages.length) announce(`Restored ${messages.length} messages from this conversation`);
        }
    } catch (e) { /* offline or locked: the chat simply starts empty */ }
}

function relDate(ts) {
    if (!ts) return '';
    const d = parseTs(ts);
    return `${dayLabel(d)} · ${fmtTime(d)}`;
}

async function loadConversations() {
    try {
        const { conversations } = await api('/api/conversations?limit=40');
        renderConversations(conversations);
    } catch (e) { /* ignore */ }
}

function renderConversations(list) {
    const panel = dom.panelHistory;
    panel.replaceChildren();
    const fresh = h('button', 'wide-btn');
    fresh.type = 'button';
    fresh.innerHTML = `${ICON.plus}<span>New conversation</span>`;
    fresh.addEventListener('click', newChat);
    panel.appendChild(fresh);
    if (!list.length) {
        panel.appendChild(h('p', 'muted', 'No conversations yet. Say hello — everything is saved here and I can search all of it later.'));
        return;
    }
    const sec = h('div', 'sec');
    sec.appendChild(h('h2', null, 'Past conversations'));
    list.forEach((c) => {
        const current = c.session_id === state.sessionId;
        const item = h('div', `conv${current ? ' current' : ''}`);
        const open = h('button', 'conv-open');
        open.type = 'button';
        if (current) open.setAttribute('aria-current', 'true');
        open.appendChild(h('span', 'title', c.title));
        open.appendChild(h('span', 'sub', `${relDate(c.updated)} · ${c.turns} ${c.turns === 1 ? 'message' : 'messages'}`));
        item.appendChild(open);
        const del = h('button', 'mini del');
        del.type = 'button';
        del.setAttribute('aria-label', `Delete conversation: ${c.title}`);
        del.innerHTML = ICON.x;
        let armed = null;
        del.addEventListener('click', async (e) => {
            e.stopPropagation();
            if (!armed) {                                   // first tap arms, second confirms
                del.className = 'mini confirm';
                del.textContent = 'Delete?';
                armed = setTimeout(() => { armed = null; del.className = 'mini del'; del.innerHTML = ICON.x; }, 3000);
                return;
            }
            clearTimeout(armed);
            try {
                await api(`/api/conversations/${encodeURIComponent(c.session_id)}`, { method: 'DELETE' });
                if (c.session_id === state.sessionId) newChat();
                loadConversations();
                toast('Conversation deleted. Saved memories are untouched.');
            } catch (err) { toast('Could not delete'); }
        });
        item.appendChild(del);
        open.addEventListener('click', () => switchSession(c.session_id));
        sec.appendChild(item);
    });
    panel.appendChild(sec);
}

function switchSession(id, { fresh = false } = {}) {
    if (id === state.sessionId && !fresh) { closePanel(); return; }
    state.sessionId = id;
    store('tapan.session', id);
    state.historyFor = fresh ? id : null;
    if (state.busy) endWork();
    clearChat();
    closePanel();
    connect();                                       // new socket for the new session; history loads once it authenticates
}

function newChat() {
    switchSession(`chat-${Date.now().toString(36)}`, { fresh: true });
    dom.userInput.focus();
}

// ── Today panel ───────────────────────────────────────────────────
function emptyNote(text) { return h('p', 'muted', text); }

function reminderRow(r, overdue) {
    const row = h('div', `row${overdue ? ' overdue' : ''}`);
    const main = h('div', 'main');
    main.appendChild(h('div', 'title', r.title));
    const when = overdue ? `Overdue · ${whenLabel(parseTs(r.due_at))}` : whenLabel(parseTs(r.due_at));
    main.appendChild(h('div', 'sub', r.repeats ? `${when} · repeats ${r.repeats}` : when));
    row.appendChild(main);
    const del = h('button', 'mini del');
    del.type = 'button';
    del.setAttribute('aria-label', r.repeats ? `Stop repeating reminder: ${r.title} (ends the whole series)` : `Cancel reminder: ${r.title}`);
    del.innerHTML = ICON.x;
    del.addEventListener('click', async () => {
        row.remove();
        try { await api(`/api/reminders/${r.id}`, { method: 'DELETE' }); } catch (e) { toast('Could not cancel that reminder'); refreshToday(true); }
    });
    row.appendChild(del);
    return row;
}

function taskRow(t) {
    const row = h('div', 'row');
    const done = h('button', 'mini');
    done.type = 'button';
    done.setAttribute('aria-label', `Mark done: ${t.title}`);
    done.innerHTML = ICON.check;
    done.addEventListener('click', async () => {
        row.remove();
        try { await api(`/api/tasks/${t.id}/complete`, { method: 'POST' }); } catch (e) { toast('Could not complete that task'); refreshToday(true); }
    });
    row.appendChild(done);
    const main = h('div', 'main');
    main.appendChild(h('div', 'title', t.title));
    if (t.due_at) main.appendChild(h('div', 'sub', `Due ${whenLabel(parseTs(t.due_at))}`));
    row.appendChild(main);
    const prio = h('span', `prio ${t.priority || 'normal'}`);
    prio.setAttribute('role', 'img');
    prio.setAttribute('aria-label', `${(t.priority || 'normal')[0].toUpperCase()}${(t.priority || 'normal').slice(1)} priority`);
    prio.title = prio.getAttribute('aria-label');
    row.appendChild(prio);
    return row;
}

function section(title, rows, danger) {
    const sec = h('div', 'sec');
    sec.appendChild(h('h2', danger ? 'danger' : null, title));
    rows.forEach((r) => sec.appendChild(r));
    return sec;
}

// Weather card: the forecast line, or an honest explanation (never silence) with a one-tap way to fix a missing city.
function buildWeatherCard(d) {
    const line = typeof d.weather === 'string' ? d.weather.split('\n')[0] : '';
    if (line) return h('div', 'card weather', line);
    let text = null;
    let canSetCity = false;
    if (d.weather_error) { text = `Weather unavailable. ${d.weather_error}`; canSetCity = /city|find a place/i.test(d.weather_error); }
    else if (d.home_location === null) { text = 'See your local weather here: tell Tapan which city you live in.'; canSetCity = true; }
    if (!text) return null;
    const card = h('div', 'card weather muted-card');
    card.appendChild(h('p', null, text));
    if (canSetCity) {
        const btn = h('button', 'link-btn', 'Set my city');
        btn.type = 'button';
        btn.addEventListener('click', () => {
            closePanel();
            dom.userInput.value = 'My city is ';
            autoGrow();
            refreshSend();
            dom.userInput.focus();
            dom.userInput.setSelectionRange(dom.userInput.value.length, dom.userInput.value.length);
        });
        card.appendChild(btn);
    }
    return card;
}

function renderToday(d) {
    state.lastBrief = d;
    const panel = dom.panelToday;
    const active = document.activeElement;
    // The panel is rebuilt wholesale; remember what had keyboard focus so a keyboard / screen-reader user does not lose their place.
    const prevFocus = active && active !== panel && panel.contains(active)
        ? { label: active.getAttribute('aria-label') || active.textContent.trim(), inPushCard: Boolean(active.closest('.push-card')) }
        : null;
    panel.replaceChildren();
    if (push.status !== 'on') appendPushCard(panel);        // not set up yet: this is the first thing to see
    const weatherCard = buildWeatherCard(d);
    if (weatherCard) panel.appendChild(weatherCard);
    let sections = 0;                                         // real content sections (the push / weather cards do not count)
    if (d.overdue_reminders && d.overdue_reminders.length) { panel.appendChild(section('Overdue', d.overdue_reminders.map((r) => reminderRow(r, true)), true)); sections++; }
    const upcoming = [...(d.reminders_today || []), ...(d.upcoming_reminders || [])];
    if (upcoming.length) { panel.appendChild(section('Reminders', upcoming.map((r) => reminderRow(r, false)))); sections++; }
    if (d.events_today && d.events_today.length) {
        sections++;
        panel.appendChild(section('Events today', d.events_today.map((e) => {
            const row = h('div', 'row');
            const main = h('div', 'main');
            main.appendChild(h('div', 'title', e.title));
            main.appendChild(h('div', 'sub', [e.start_at ? fmtTime(parseTs(e.start_at)) : '', e.location].filter(Boolean).join(' · ')));
            row.appendChild(main);
            return row;
        })));
    }
    if (d.open_tasks && d.open_tasks.length) { panel.appendChild(section('Tasks', d.open_tasks.map(taskRow))); sections++; }
    if (sections === 0) {
        panel.appendChild(emptyNote('Nothing scheduled. Ask me to set reminders or add tasks — you can paste a whole list.'));
    }
    if (push.status === 'on') appendPushCard(panel);          // set up: a quiet status line near the bottom
    const foot = h('div', 'panel-foot');
    foot.appendChild(h('span', null, `Updated ${fmtTime(new Date())}`));
    const refresh = h('button', 'link-btn', 'Refresh');
    refresh.type = 'button';
    refresh.addEventListener('click', () => refreshToday(false));
    foot.appendChild(refresh);
    const installLink = h('button', 'link-btn', 'Install app');
    installLink.id = 'install-link';
    installLink.type = 'button';
    installLink.addEventListener('click', startInstall);
    foot.appendChild(installLink);
    panel.appendChild(foot);
    updateInstallUI();
    if (prevFocus) restoreTodayFocus(prevFocus);
}

function restoreTodayFocus(prev) {
    const panel = dom.panelToday;
    const buttons = [...panel.querySelectorAll('button:not([disabled])')].filter((b) => !b.closest('.hidden'));
    let target = prev.label ? buttons.find((b) => (b.getAttribute('aria-label') || b.textContent.trim()) === prev.label) : null;
    if (!target && prev.inPushCard) {              // the control changed (e.g. 'Turn on' became 'Send a test'): land on the card
        const card = panel.querySelector('.push-card');
        target = card ? (card.querySelector('button:not([disabled])') || Object.assign(card, { tabIndex: -1 })) : null;
    }
    if (!target) target = buttons[0];
    if (target && typeof target.focus === 'function') target.focus({ preventScroll: true });
}

async function refreshToday(silent) {
    try {
        renderToday(await api('/api/briefing'));
    } catch (e) {
        if (!silent && !state.authNeeded) {
            dom.panelToday.replaceChildren(emptyNote('Could not load your day. Check the connection and try Refresh.'));
        }
    }
}

// ── Side panel / drawer ───────────────────────────────────────────
const TAB_TITLES = { today: 'Today', history: 'History', money: 'Money', work: 'Work', growth: 'Growth', settings: 'Settings' };
function setTab(tab) {
    state.tab = tab;
    [['today', dom.tabToday, dom.panelToday], ['history', dom.tabHistory, dom.panelHistory], ['money', dom.tabMoney, dom.panelMoney], ['work', dom.tabWork, dom.panelWork],
        ['growth', dom.tabGrowth, dom.panelGrowth], ['settings', dom.tabSettings, dom.panelSettings]].forEach(([name, tabEl, panelEl]) => {
        tabEl.setAttribute('aria-selected', String(tab === name));
        tabEl.tabIndex = tab === name ? 0 : -1;
        panelEl.classList.toggle('hidden', tab !== name);
        if (tab === name && tabEl.scrollIntoView) tabEl.scrollIntoView({ inline: 'nearest', block: 'nearest' });     // six tabs scroll sideways on a narrow phone: keep this one in view
    });
    const screens = { money: ['TapanMoney', dom.panelMoney, 'Money'], work: ['TapanWork', dom.panelWork, 'Work'], growth: ['TapanGrowth', dom.panelGrowth, 'Growth'] };
    if (tab === 'today') refreshToday(true);
    else if (tab === 'history') loadConversations();
    else if (screens[tab]) { const [mod, panel, label] = screens[tab]; if (window[mod]) window[mod].render(panel); else panel.textContent = `The ${label} tab could not load. Reload the page.`; }
    else if (window.TapanSettings) window.TapanSettings.render(dom.panelSettings);
    syncBottomNav();
}

const drawerQuery = window.matchMedia ? window.matchMedia('(max-width: 1000px)') : { matches: false, addEventListener() {} };
function drawerMode() { return drawerQuery.matches; }

// On phones/tablets the panel is a modal drawer; on desktop it is a normal always-visible column.
function syncDrawerA11y() {
    const drawer = drawerMode();
    const open = dom.app.dataset.panel === 'open';
    setInert(dom.side, drawer && !open);                       // a closed, off-screen drawer must not be reachable by Tab
    setInert(dom.topbar, drawer && open);
    setInert(dom.chatMain, drawer && open);
    setInert(dom.installBanner, drawer && open);
    if (drawer && open) { dom.side.setAttribute('role', 'region'); dom.side.setAttribute('aria-labelledby', 'panel-title'); }   // a page, not a modal: the bottom bar stays usable
    else { dom.side.setAttribute('role', 'complementary'); dom.side.removeAttribute('aria-labelledby'); }
    dom.side.removeAttribute('aria-modal');
    dom.scrim.hidden = true;
    syncBottomNav();
}

// ── Navigation: the bottom bar (phones and tablets) and its More menu ──
function bottomNavActive() {
    if (!drawerMode()) return state.tab;                                  // desktop: the rail shows which page the side panel is on (every page has its own button)
    if (dom.app.dataset.panel !== 'open') return 'chat';
    return ['today', 'money', 'work', 'growth'].includes(state.tab) ? state.tab : 'more';
}
function syncBottomNav() {
    if (dom.bnav) {
        const active = bottomNavActive();
        dom.bnav.querySelectorAll('.bnav-btn').forEach((b) => { if (b.dataset.dest === active) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current'); });
    }
    if (dom.panelTitle) dom.panelTitle.textContent = TAB_TITLES[state.tab] || '';
}
function goDest(dest) {
    if (dest === 'chat') { closePanel(); return; }
    if (dest === 'more') { openMoreSheet(); return; }
    if (dom.app.dataset.panel === 'open' && state.tab === dest) return;
    openPanel(dest);
}
function updateMoreSheet() {
    const pref = window.TapanTheme ? window.TapanTheme.get() : 'auto';
    dom.moreSheet.querySelectorAll('.seg3 button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.pref === pref)));
    dom.moreInstall.classList.toggle('hidden', isStandalone());
    dom.moreLock.classList.toggle('hidden', !state.token);
}
function openMoreSheet() {
    state.sheetOpener = document.activeElement;
    updateMoreSheet();
    dom.moreSheet.classList.remove('hidden');
    setInert(dom.app, true);
    dom.moreHistory.focus();
}
function closeMoreSheet(restoreFocus = true) {
    if (dom.moreSheet.classList.contains('hidden')) return;
    dom.moreSheet.classList.add('hidden');
    setInert(dom.app, state.authNeeded);
    if (restoreFocus && state.sheetOpener && state.sheetOpener.isConnected) state.sheetOpener.focus();
}
const THEME_WORDS = { auto: 'automatic, follows your device', light: 'light', dark: 'dark' };
function paintThemeButton() {
    if (!dom.themeBtn || !window.TapanTheme) return;
    const pref = window.TapanTheme.get();
    dom.themeBtn.dataset.pref = pref;
    dom.themeBtn.setAttribute('aria-label', `Appearance: ${THEME_WORDS[pref]}. Tap to change.`);
}

function openPanel(tab) {
    setTab(tab);
    state.opener = document.activeElement;
    dom.app.dataset.panel = 'open';
    dom.todayBtn.setAttribute('aria-expanded', String(tab === 'today'));
    dom.historyBtn.setAttribute('aria-expanded', String(tab === 'history'));
    syncDrawerA11y();
    if (drawerMode()) {
        if (!state.drawerPushed) { history.pushState({ tapanPanel: true }, ''); state.drawerPushed = true; }   // Android Back closes it
        (dom.panelTitle || dom.sideClose).focus();           // screen readers land on the page title; the bottom bar is one Tab away
    }
}

function closePanel(fromPop) {
    if (dom.app.dataset.panel !== 'open') return;
    dom.app.dataset.panel = 'closed';
    dom.todayBtn.setAttribute('aria-expanded', 'false');
    dom.historyBtn.setAttribute('aria-expanded', 'false');
    syncDrawerA11y();
    if (state.drawerPushed) {
        state.drawerPushed = false;
        if (!fromPop) history.back();
    }
    const back = state.opener;
    state.opener = null;
    if (back && back.isConnected && typeof back.focus === 'function' && drawerMode()) back.focus();
}

function togglePanel(tab) {
    if (dom.app.dataset.panel === 'open' && state.tab === tab) closePanel(); else openPanel(tab);
}

// ── Notifications (reminders the server fired on its own) ─────────
async function pollNotifications() {
    if (state.authNeeded) return;
    try {
        const { notifications } = await api(`/api/notifications?after=${state.lastNotificationId}`);
        const spoken = [];
        for (const n of notifications) {
            state.lastNotificationId = Math.max(state.lastNotificationId, n.id);
            store('tapan.lastNotification', String(state.lastNotificationId));
            addMessage(`**Reminder:** ${n.body}`, 'assistant', { ts: n.created_at, note: 'reminder' });
            spoken.push(n.body);
            // With push on, the service worker already shows this on the lock screen: a second one would be a duplicate buzz.
            // This is only the fallback for a granted-but-not-subscribed browser whose tab is in the background.
            // 'checking' (state not known yet, e.g. the very first poll at page load) counts as ON: a duplicate is worse than a miss.
            if (['off', 'error'].includes(push.status) && document.hidden && 'Notification' in window && Notification.permission === 'granted') {
                try { new Notification('TAPAN_AI', { body: n.body }); } catch (e) { /* Android Chrome only allows this via a service worker */ }
            }
        }
        if (spoken.length) {
            refreshToday(true);
            // Speak once: several reminders firing together would otherwise cancel each other mid-sentence.
            if (state.voiceMode !== 'off') speak(spoken.length === 1 ? `Reminder: ${spoken[0]}` : `You have ${spoken.length} reminders: ${spoken.join('. ')}`);
        }
    } catch (e) { /* offline: try again next tick */ }
}

function startNotifications() {
    pollNotifications();
    setInterval(pollNotifications, 15000);
    // Permission is deliberately NOT requested here: browsers (Chrome on Android especially) suppress prompts that are not
    // triggered by a tap, and a dismissed prompt can block the site for good. See enablePush().
}

// ── Push notifications (reminders on the lock screen, even when the app is closed) ──
// status: checking | unsupported | ios-install | server-off | blocked | off | on | error
const push = { status: 'checking', busy: false, serverKey: null, checkedAt: 0 };

function pushIssue() {
    if (platformKind() === 'ios' && !isStandalone()) return 'ios-install';        // iOS only allows push for apps added to the Home Screen
    const secure = window.isSecureContext || ['localhost', '127.0.0.1'].includes(location.hostname);
    if (!secure || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) return 'unsupported';
    return null;
}

function urlBase64ToUint8Array(b64) {
    const padded = (b64 + '='.repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/');
    const raw = atob(padded);
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

function sameKey(buffer, bytes) {
    if (!buffer || !bytes) return false;
    const a = new Uint8Array(buffer);
    return a.length === bytes.length && a.every((v, i) => v === bytes[i]);
}

function swReady(ms = 6000) {
    return Promise.race([navigator.serviceWorker.ready, new Promise((_, reject) => setTimeout(() => reject(new Error('service worker not ready')), ms))]);
}

async function sendSubscription(sub) {
    await api('/api/push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub.toJSON()) });
}

function setPushStatus(status) {
    push.status = status;
    refreshPushCards();
    scheduleClientReport();
}

// Reconcile three things that can drift apart: the browser's subscription, the server's key, and the server's database.
async function pushRefresh() {
    if (Date.now() - push.checkedAt < 30000 && push.status !== 'checking') return;
    push.checkedAt = Date.now();
    const issue = pushIssue();
    if (issue) { setPushStatus(issue); return; }
    try {
        const info = await api('/api/push/key');
        if (!info.enabled) { setPushStatus('server-off'); return; }
        push.serverKey = urlBase64ToUint8Array(info.public_key);
        if (Notification.permission === 'denied') { setPushStatus('blocked'); return; }
        const reg = await swReady();
        let sub = await reg.pushManager.getSubscription();
        if (sub && !sameKey(sub.options && sub.options.applicationServerKey, push.serverKey)) {
            // The server's key changed (e.g. its database was reset): the old subscription can never work again.
            try { await sub.unsubscribe(); } catch (e) { /* already gone */ }
            sub = null;
            if (Notification.permission === 'granted') {                 // already allowed, so resubscribing needs no new prompt
                try { sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: push.serverKey }); } catch (e) { sub = null; }
            }
        }
        if (sub) {
            await sendSubscription(sub);                                  // idempotent: also repairs a row lost on the server
            setPushStatus('on');
        } else {
            setPushStatus('off');
        }
    } catch (e) {
        if (state.authNeeded) return;
        setPushStatus(push.status === 'on' ? 'on' : 'error');
    }
}

async function enablePush() {
    if (push.busy) return false;
    push.busy = true;
    refreshPushCards();
    try {
        // The permission prompt must be the FIRST await: it only works while the tap's "user activation" is still alive.
        const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission();
        if (permission !== 'granted') {
            setPushStatus(permission === 'denied' ? 'blocked' : 'off');
            toast(permission === 'denied' ? 'Notifications are blocked for this site' : 'Notifications were not turned on');
            return false;
        }
        if (!push.serverKey) {
            const info = await api('/api/push/key');
            if (!info.enabled) { setPushStatus('server-off'); return false; }
            push.serverKey = urlBase64ToUint8Array(info.public_key);
        }
        const reg = await swReady();
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: push.serverKey });
        try { await sendSubscription(sub); } catch (err) { await sub.unsubscribe().catch(() => {}); throw err; }   // never leave a half-registered device
        store('tapan.pushAsked', '1');
        setPushStatus('on');
        toast('Reminder notifications are on');
        announce('Reminder notifications are on for this device');
        return true;
    } catch (err) {
        toast('Could not turn on notifications. Try again in a moment.');
        setPushStatus(push.status === 'on' ? 'on' : 'off');
        return false;
    } finally {
        push.busy = false;
        refreshPushCards();
    }
}

async function disablePush() {
    if (push.busy) return;
    push.busy = true;
    refreshPushCards();
    try {
        const reg = await swReady();
        const sub = await reg.pushManager.getSubscription();
        if (sub) {
            const endpoint = sub.endpoint;
            await sub.unsubscribe();                                      // stop this device first, then tell the server
            try { await api('/api/push/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint }) }); } catch (e) { /* the server drops it on the next 404/410 */ }
        }
        setPushStatus('off');
        toast('Reminder notifications are off');
        announce('Reminder notifications are off');
    } catch (e) {
        toast('Could not turn notifications off');
    } finally {
        push.busy = false;
        refreshPushCards();
    }
}

async function testPush() {
    if (push.busy) return;
    push.busy = true;
    refreshPushCards();
    try {
        const result = await api('/api/push/test', { method: 'POST' });
        toast(result.ok ? 'Test sent. It should appear in a moment.' : 'The push service did not accept it. Try turning notifications off and on.', 4000);
    } catch (e) {
        toast(e.status === 429 ? 'Too many tests. Wait a minute.' : e.status === 409 ? 'This device is not registered yet. Turn notifications on first.' : 'Could not send a test', 4000);
    } finally {
        push.busy = false;
        refreshPushCards();
    }
}

function pushButton(label, cls, handler) {
    const b = h('button', cls, label);
    b.type = 'button';
    b.disabled = push.busy;
    b.addEventListener('click', handler);
    return b;
}

function buildPushCard() {
    const card = h('section', 'card push-card');
    card.setAttribute('aria-labelledby', 'push-card-title');
    const title = h('h2', 'push-title', 'Reminder notifications');
    title.id = 'push-card-title';
    card.appendChild(title);
    const text = h('p', null);
    const actions = h('div', 'push-actions');
    switch (push.status) {
        case 'on':
            text.textContent = 'On for this device. Reminders arrive even when Tapan is closed.';
            actions.append(pushButton('Send a test', 'link-btn', testPush), pushButton('Turn off', 'link-btn', disablePush));
            break;
        case 'off':
            text.textContent = 'Get a notification on this device when a reminder is due, even when Tapan is closed.';
            actions.appendChild(pushButton(push.busy ? 'Working…' : 'Turn on notifications', 'wide-btn', enablePush));
            break;
        case 'blocked':
            text.textContent = 'Notifications are blocked for this site. Allow them in your browser’s site settings, then reopen this panel.';
            break;
        case 'ios-install':
            text.textContent = 'On iPhone and iPad, first add Tapan to your Home Screen (Share → Add to Home Screen), then open it from there to turn on notifications.';
            break;
        case 'error':
            text.textContent = 'Could not check the notification status.';
            actions.appendChild(pushButton('Retry', 'link-btn', () => { push.checkedAt = 0; pushRefresh(); }));
            break;
        default:
            return null;                                                    // checking / unsupported / server-off: nothing to offer
    }
    card.appendChild(text);
    if (actions.children.length) card.appendChild(actions);
    return card;
}

function appendPushCard(panel) {
    const card = buildPushCard();
    if (card) panel.appendChild(card);
}

// Re-render in place when the state changes (the Today panel is otherwise rebuilt only when its data refreshes).
function refreshPushCards() {
    if (state.lastBrief) renderToday(state.lastBrief);
    const prompt = document.querySelector('.push-prompt');
    if (prompt && push.status === 'on') prompt.remove();
}

// Offer notifications right after the assistant sets a reminder: the one moment the benefit is obvious.
function offerPush() {
    if (push.status !== 'off' || store('tapan.pushAsked') || document.querySelector('.push-prompt')) return;
    const row = h('div', 'message assistant push-prompt');
    row.setAttribute('role', 'group');
    row.setAttribute('aria-label', 'Suggestion');
    const body = h('div', 'msg-body');
    const bubble = h('div', 'bubble');
    bubble.appendChild(h('p', null, 'Want a notification on this device when these are due, even if Tapan is closed?'));
    const actions = h('div', 'push-actions');
    const yes = h('button', 'wide-btn', 'Turn on notifications');
    yes.type = 'button';
    yes.addEventListener('click', async () => { if (await enablePush()) row.remove(); });
    const no = h('button', 'link-btn', 'Not now');
    no.type = 'button';
    no.addEventListener('click', () => { store('tapan.pushAsked', 'dismissed'); row.remove(); });
    actions.append(yes, no);
    bubble.appendChild(actions);
    body.appendChild(bubble);
    row.appendChild(body);
    dom.chat.appendChild(row);
    if (nearBottom()) scrollToBottom();
}

// ── Voice ─────────────────────────────────────────────────────────
const VOICE_MODES = {
    voice: { label: 'Voice', toast: 'Spoken replies: only when you use the microphone', aria: 'Spoken replies: only after I use the microphone' },
    always: { label: 'Speak', toast: 'Spoken replies: always on', aria: 'Spoken replies: always' },
    off: { label: 'Muted', toast: 'Spoken replies: off', aria: 'Spoken replies: off' },
};

function applyVoiceMode() {
    if (!VOICE_MODES[state.voiceMode]) state.voiceMode = 'voice';
    const mode = VOICE_MODES[state.voiceMode];
    dom.voiceModeBtn.dataset.mode = state.voiceMode;
    dom.voiceModeLabel.textContent = mode.label;
    dom.voiceModeBtn.setAttribute('aria-label', mode.aria);
    dom.voiceModeBtn.title = mode.aria;
}

function cycleVoiceMode() {
    const order = ['voice', 'always', 'off'];
    state.voiceMode = order[(order.indexOf(state.voiceMode) + 1) % order.length];
    store('tapan.voice', state.voiceMode);
    applyVoiceMode();
    toast(VOICE_MODES[state.voiceMode].toast);
    if (state.voiceMode === 'off') stopSpeaking();
}

function maybeSpeak(text) {
    const speakIt = state.voiceMode === 'always' || (state.voiceMode === 'voice' && state.lastInputWasVoice);
    state.lastInputWasVoice = false;
    if (speakIt) speak(text);
}

function speakable(text) {
    return String(text || '')
        .replace(/```[\s\S]*?```/g, ' ')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/https?:\/\/\S+/g, 'a link')
        .replace(/[*_#`>~|]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 600);
}

function speak(text) {
    const clean = speakable(text);
    if (!clean || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(clean);
    if (state.selectedVoice) utterance.voice = state.selectedVoice;
    utterance.onstart = () => { state.isSpeaking = true; dom.stopBtn.classList.remove('hidden'); if (!state.busy) dom.app.dataset.orb = 'speaking'; };
    utterance.onend = utterance.onerror = () => { state.isSpeaking = false; dom.stopBtn.classList.add('hidden'); if (!state.busy) dom.app.dataset.orb = 'idle'; };
    window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
    if (window.speechSynthesis) window.speechSynthesis.cancel();
    state.isSpeaking = false;
    dom.stopBtn.classList.add('hidden');
}

function initVoice() {
    if (window.speechSynthesis) {
        const pick = () => {
            state.voices = window.speechSynthesis.getVoices();
            state.selectedVoice = state.voices.find((v) => /natural|google (uk|us) english/i.test(v.name)) || null;
        };
        pick();
        window.speechSynthesis.onvoiceschanged = pick;
    }
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) { dom.voiceBtn.classList.add('hidden'); return; }

    state.recognition = new Recognition();
    state.recognition.continuous = false;
    state.recognition.interimResults = true;
    state.recognition.lang = navigator.language || 'en-US';

    state.recognition.onstart = () => {
        state.isListening = true;
        stopSpeaking();
        dom.voiceBtn.classList.add('active');
        dom.voiceBtn.setAttribute('aria-pressed', 'true');
        dom.userInput.placeholder = 'Listening…';
        announce('Listening');
    };
    state.recognition.onend = () => {
        state.isListening = false;
        dom.voiceBtn.classList.remove('active');
        dom.voiceBtn.setAttribute('aria-pressed', 'false');
        dom.userInput.placeholder = INPUT_PLACEHOLDER;
    };
    state.recognition.onerror = (e) => { if (e.error === 'not-allowed') toast('Microphone permission is blocked for this site'); };
    state.recognition.onresult = (event) => {
        let transcript = '';
        let final = false;
        for (let i = 0; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
            if (event.results[i].isFinal) final = true;
        }
        dom.userInput.value = transcript;
        autoGrow();
        refreshSend();
        if (final && transcript.trim()) sendMessage(undefined, { voice: true });
    };
    dom.voiceBtn.addEventListener('click', () => {
        if (state.isListening) state.recognition.stop();
        else { try { state.recognition.start(); } catch (e) { /* already started */ } }
    });
}

// ── Status orb (small three.js scene; pauses when hidden or if reduced motion) ──
let orb = null;
let orbRaf = 0;
let orbLast = 0;
const reduceMotion = Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

function init3D() {
    const container = dom.orbCanvas;
    if (!window.THREE || !container) return;      // decorative: the CSS orb stays as the fallback
    const T = window.THREE;
    const size = container.clientWidth || 46;
    const renderer = new T.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(size, size, false);
    container.appendChild(renderer.domElement);

    const scene = new T.Scene();
    const camera = new T.PerspectiveCamera(60, 1, 0.1, 100);
    camera.position.z = 21;
    const group = new T.Group();
    scene.add(group);

    const positions = [];
    const colors = [];
    const core = new T.Color(0x00ff88);
    const depth = new T.Color(0x006a38);
    for (let i = 0; i < 1100; i++) {                 // two hemispheres of points with gyri-like noise
        const side = Math.random() > 0.5 ? 2.2 : -2.2;
        const theta = 2 * Math.PI * Math.random();
        const phi = Math.acos(2 * Math.random() - 1);
        const r = 5 + Math.random() * 0.8 + Math.sin(theta * 8) * Math.cos(phi * 7) * 0.5;
        let x = r * Math.sin(phi) * Math.cos(theta);
        const y = r * Math.sin(phi) * Math.sin(theta) * 0.85;
        const z = r * Math.cos(phi) * 1.1;
        if ((side > 0 && x < 0) || (side < 0 && x > 0)) x *= 0.1;
        const c = new T.Color().lerpColors(depth, core, Math.min(1, Math.hypot(x, y, z) / 6));
        positions.push(x + side, y, z);
        colors.push(c.r, c.g, c.b);
    }
    const pg = new T.BufferGeometry();
    pg.setAttribute('position', new T.Float32BufferAttribute(positions, 3));
    pg.setAttribute('color', new T.Float32BufferAttribute(colors, 3));
    const points = new T.Points(pg, new T.PointsMaterial({ size: 0.9, vertexColors: true, transparent: true, opacity: 0.95, blending: T.AdditiveBlending }));
    group.add(points);

    const linePos = [];
    for (let i = 0; i < positions.length / 3 && linePos.length < 1800; i += 2) {
        for (let j = i + 1; j < positions.length / 3; j += 9) {
            const dx = positions[i * 3] - positions[j * 3], dy = positions[i * 3 + 1] - positions[j * 3 + 1], dz = positions[i * 3 + 2] - positions[j * 3 + 2];
            const d2 = dx * dx + dy * dy + dz * dz;
            if (d2 < 3 && d2 > 0.1) linePos.push(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2], positions[j * 3], positions[j * 3 + 1], positions[j * 3 + 2]);
        }
    }
    const lg = new T.BufferGeometry();
    lg.setAttribute('position', new T.Float32BufferAttribute(linePos, 3));
    const lines = new T.LineSegments(lg, new T.LineBasicMaterial({ color: 0x00ff88, transparent: true, opacity: 0.22, blending: T.AdditiveBlending }));
    group.add(lines);

    const ring = new T.Mesh(new T.RingGeometry(8.4, 8.7, 64), new T.MeshBasicMaterial({ color: 0x00ff88, side: T.DoubleSide, transparent: true, opacity: 0.45, blending: T.AdditiveBlending }));
    ring.rotation.x = Math.PI / 2.3;
    group.add(ring);

    orb = { renderer, scene, camera, group, points, lines };
    renderer.render(scene, camera);
    startOrb();
}

function orbFrame(t) {
    orbRaf = requestAnimationFrame(orbFrame);
    if (t - orbLast < 33) return;                    // ~30 fps is plenty for a 46px orb
    orbLast = t;
    const mode = state.busy ? 'thinking' : state.isSpeaking ? 'speaking' : 'idle';
    const s = t * 0.001;
    orb.group.rotation.y += mode === 'thinking' ? 0.03 : mode === 'speaking' ? 0.014 : 0.004;
    orb.group.scale.setScalar(mode === 'idle' ? 1 + Math.sin(s * 2) * 0.02 : 1 + Math.sin(s * (mode === 'thinking' ? 9 : 11)) * 0.06);
    orb.points.material.size = mode === 'idle' ? 0.9 : 1.3;
    orb.lines.material.opacity = mode === 'idle' ? 0.22 : 0.45;
    orb.renderer.render(orb.scene, orb.camera);
}

function startOrb() {
    if (!orb || orbRaf || document.hidden || reduceMotion) return;
    orbRaf = requestAnimationFrame(orbFrame);
}
function stopOrb() { if (orbRaf) cancelAnimationFrame(orbRaf); orbRaf = 0; }

// ── Install as an app (PWA) ───────────────────────────────────────
const install = { event: null };

function isStandalone() {
    return Boolean((window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) || navigator.standalone === true);
}
function platformKind() {
    const ua = navigator.userAgent || '';
    if (/Android/i.test(ua)) return 'android';
    if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1)) return 'ios';
    return 'desktop';
}
const INSTALL_SNOOZE_MS = 14 * 24 * 3600 * 1000;
function installDismissed() {
    const at = parseInt(store('tapan.installDismissed') || '0', 10);
    return Boolean(at) && Date.now() - at < INSTALL_SNOOZE_MS;
}

function updateInstallUI() {
    if (!dom.installBtn) return;
    if (isStandalone()) { store('tapan.installed', '1'); }
    const standalone = isStandalone();
    const mobile = platformKind() !== 'desktop';
    const knownInstalled = store('tapan.installed') === '1';
    // A native prompt only exists when the app is NOT installed, so it overrides any stale "installed" flag.
    const available = !standalone && (Boolean(install.event) || (mobile && !knownInstalled));
    dom.installBtn.classList.toggle('hidden', !available);
    dom.installBanner.classList.toggle('hidden', !available || installDismissed());
    const link = $('install-link');
    if (link) link.classList.toggle('hidden', !available);
}

function openInstallSheet() {
    const steps = {
        android: ['Open your browser\'s menu (the ⋮ at the top right).', 'Tap “Install app” (or “Add to Home screen”).', 'Confirm. Tapan opens full-screen from your home screen, like any other app.'],
        ios: ['Open this page in Safari.', 'Tap the Share button (the square with an arrow).', 'Scroll down and tap “Add to Home Screen”, then tap Add.'],
        desktop: ['Open your browser\'s menu.', 'Choose “Install Tapan” (Chrome/Edge) or “Add to Dock/Home screen”.'],
    }[platformKind()];
    dom.installSteps.replaceChildren(...steps.map((text) => h('li', null, text)));
    state.sheetOpener = document.activeElement;
    dom.installSheet.classList.remove('hidden');
    setInert(dom.app, true);
    dom.installClose.focus();
}
function closeInstallSheet() {
    if (dom.installSheet.classList.contains('hidden')) return;
    dom.installSheet.classList.add('hidden');
    setInert(dom.app, state.authNeeded);
    if (state.sheetOpener && state.sheetOpener.isConnected) state.sheetOpener.focus();
}

async function startInstall() {
    const ev = install.event;
    if (!ev) { openInstallSheet(); return; }
    install.event = null;                           // a prompt event can be used only once
    ev.prompt();
    let outcome = 'dismissed';
    try { outcome = (await ev.userChoice).outcome; } catch (e) { /* prompt closed */ }
    if (outcome === 'accepted') toast('Installing…');
    else store('tapan.installDismissed', String(Date.now()));
    updateInstallUI();
}

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();                             // we show our own button and banner instead of the browser's mini-infobar
    install.event = e;
    store('tapan.installed', null);
    updateInstallUI();
});
window.addEventListener('appinstalled', () => {
    install.event = null;
    store('tapan.installed', '1');
    updateInstallUI();
    if (dom.toast) toast('Installed. Open Tapan from your home screen.', 4000);
});

function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    const secure = window.isSecureContext || ['localhost', '127.0.0.1'].includes(location.hostname);
    if (!secure) return;
    const hadController = Boolean(navigator.serviceWorker.controller);
    navigator.serviceWorker.register('sw.js', { scope: './' }).catch((err) => console.warn('Offline support unavailable:', err));
    navigator.serviceWorker.addEventListener('message', (event) => {
        const msg = event.data || {};
        if (msg.type === 'open-panel') openPanel(['history', 'settings'].includes(msg.panel) ? msg.panel : 'today');
    });
    navigator.serviceWorker.addEventListener('controllerchange', () => {
        if (hadController) toast('Tapan was updated. Reload to use the latest version.', 6000);
    });
}

// ── Staying current: an open page can otherwise run old code for days ──────────
let updateShown = false;
async function checkForUpdate(manual) {
    if (!WEB_VERSION_KNOWN) { if (manual) toast('Development build: update checks are off'); return false; }
    try {
        const res = await fetch('/health', { cache: 'no-store' });
        const info = await res.json();
        if (info.web_version && info.web_version !== WEB_VERSION) {
            if (!updateShown) { updateShown = true; dom.updateBanner.classList.remove('hidden'); announce('A new version of Tapan is available. Use the Reload button.'); }
            return true;
        }
        if (manual) toast('You are on the latest version');
    } catch (e) { if (manual) toast('Could not check for updates'); }
    return false;
}

async function reloadForUpdate() {
    try {
        const reg = navigator.serviceWorker && await navigator.serviceWorker.getRegistration();
        if (reg) await reg.update();
    } catch (e) { /* offline: the reload below still works from cache */ }
    (window.TapanHost && window.TapanHost.reload ? window.TapanHost.reload : () => window.location.reload())();
}

// ── Tell the server what this page can and cannot do (answers "it did not work on my phone") ──
function deviceId() {
    let id = store('tapan.device');
    if (!id) {
        id = ((window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `d${Date.now()}${Math.random().toString(16).slice(2, 8)}`).replace(/[^A-Za-z0-9-]/g, '').slice(0, 24);
        store('tapan.device', id);
    }
    return id;
}

let reportTimer = null;
function scheduleClientReport() {
    clearTimeout(reportTimer);
    reportTimer = setTimeout(sendClientReport, 2500);
}
async function sendClientReport() {
    if (state.authNeeded || state.conn === 'locked') return;
    try {
        await api('/api/client-report', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                device: deviceId(), web_version: WEB_VERSION_KNOWN ? WEB_VERSION : 'dev', ua: navigator.userAgent.slice(0, 300),
                standalone: isStandalone(), online: navigator.onLine, tz: (Intl.DateTimeFormat().resolvedOptions() || {}).timeZone || '',
                push: { status: push.status, issue: pushIssue(), permission: 'Notification' in window ? Notification.permission : 'n/a', has_push_manager: 'PushManager' in window },
                sw: { supported: 'serviceWorker' in navigator, controlled: Boolean(navigator.serviceWorker && navigator.serviceWorker.controller) },
            }),
        });
    } catch (e) { /* diagnostics must never get in the way */ }
}

// ── Wiring ────────────────────────────────────────────────────────
function greetingText() {
    const hour = new Date().getHours();
    if (hour >= 5 && hour < 12) return 'Good morning';
    if (hour >= 12 && hour < 17) return 'Good afternoon';
    if (hour >= 17 && hour < 22) return 'Good evening';
    return 'Hello';
}

function bindEvents() {
    dom.authForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const entered = dom.authInput.value.trim();
        if (!entered) return;
        state.token = entered;
        store('tapan.token', entered);
        hideAuth();
        connect();
    });

    dom.composer.addEventListener('submit', (e) => { e.preventDefault(); sendMessage(); });
    dom.attachBtn.addEventListener('click', () => dom.fileInput.click());
    dom.fileInput.addEventListener('change', () => { const files = Array.from(dom.fileInput.files || []); dom.fileInput.value = ''; addPictures(files); });
    dom.userInput.addEventListener('paste', (e) => {
        const files = Array.from((e.clipboardData && e.clipboardData.files) || []).filter((f) => /^image\//.test(f.type));
        if (files.length) { e.preventDefault(); addPictures(files); }
    });
    ['dragenter', 'dragover'].forEach((type) => dom.chatMain.addEventListener(type, (e) => {
        if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files')) { e.preventDefault(); dom.chatMain.classList.add('dropping'); }
    }));
    ['dragleave', 'drop'].forEach((type) => dom.chatMain.addEventListener(type, (e) => {
        dom.chatMain.classList.remove('dropping');
        if (type === 'drop' && e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); addPictures(e.dataTransfer.files); }
    }));
    dom.userInput.addEventListener('input', () => { autoGrow(); refreshSend(); });
    dom.userInput.addEventListener('focus', () => { setTimeout(() => { if (nearBottom()) scrollToBottom(false); }, 250); });
    dom.userInput.addEventListener('keydown', (e) => {
        // Enter sends, Shift+Enter adds a line. Ignore Enter while an IME is composing (Japanese/Chinese/etc.).
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && enterSends) {
            e.preventDefault();
            sendMessage();
        } else if (e.key === 'ArrowUp' && !dom.userInput.value && state.lastSent) {
            e.preventDefault();                       // recall the last message to edit or resend
            dom.userInput.value = state.lastSent;
            autoGrow();
            refreshSend();
        }
    });

    document.querySelectorAll('.starter').forEach((b) => b.addEventListener('click', () => useStarter(b)));

    // install
    dom.installBtn.addEventListener('click', startInstall);
    dom.installYes.addEventListener('click', startInstall);
    dom.installNo.addEventListener('click', () => { store('tapan.installDismissed', String(Date.now())); updateInstallUI(); });
    dom.installClose.addEventListener('click', closeInstallSheet);
    dom.installSheet.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeInstallSheet(); else trapTab(dom.installSheet, e); });
    dom.authOverlay.addEventListener('keydown', (e) => trapTab(dom.authOverlay, e));

    // bottom bar, More menu, appearance
    if (dom.bnav) dom.bnav.addEventListener('click', (e) => { const b = e.target.closest('.bnav-btn'); if (b) goDest(b.dataset.dest); });
    dom.moreClose.addEventListener('click', () => closeMoreSheet());
    dom.moreSheet.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMoreSheet(); else trapTab(dom.moreSheet, e); });
    dom.moreHistory.addEventListener('click', () => { closeMoreSheet(false); openPanel('history'); });
    dom.moreSettings.addEventListener('click', () => { closeMoreSheet(false); openPanel('settings'); });
    dom.moreInstall.addEventListener('click', () => { closeMoreSheet(false); startInstall(); });
    dom.moreLock.addEventListener('click', () => { closeMoreSheet(false); dom.lockBtn.click(); });
    dom.moreSheet.querySelectorAll('.seg3 button').forEach((b) => b.addEventListener('click', () => { if (window.TapanTheme) window.TapanTheme.set(b.dataset.pref); updateMoreSheet(); }));
    if (dom.themeBtn) dom.themeBtn.addEventListener('click', () => { if (window.TapanTheme) { const next = window.TapanTheme.cycle(); toast(`Appearance: ${THEME_WORDS[next]}`); } });
    document.addEventListener('tapan-theme', () => { paintThemeButton(); updateMoreSheet(); });
    paintThemeButton();
    syncBottomNav();

    // drawer: keyboard focus stays inside while open, Android Back closes it, layout changes re-sync the semantics
    window.addEventListener('popstate', () => { if (dom.app.dataset.panel === 'open') closePanel(true); });
    if (drawerQuery.addEventListener) drawerQuery.addEventListener('change', syncDrawerA11y);

    // tab list: arrow keys move between tabs (WAI-ARIA tabs pattern)
    const tabs = [dom.tabToday, dom.tabHistory, dom.tabMoney, dom.tabWork, dom.tabGrowth, dom.tabSettings];
    tabs.forEach((tab) => tab.addEventListener('keydown', (e) => {
        const i = tabs.indexOf(tab);
        let next = null;
        if (e.key === 'ArrowRight') next = tabs[(i + 1) % tabs.length];
        else if (e.key === 'ArrowLeft') next = tabs[(i + tabs.length - 1) % tabs.length];
        else if (e.key === 'Home') next = tabs[0];
        else if (e.key === 'End') next = tabs[tabs.length - 1];
        if (next) { e.preventDefault(); next.focus(); setTab(next.dataset.tab); }
    }));
    dom.chat.addEventListener('scroll', () => { if (nearBottom()) { state.unread = 0; dom.jump.classList.add('hidden'); } });
    dom.jump.addEventListener('click', () => scrollToBottom());

    dom.todayBtn.addEventListener('click', () => togglePanel('today'));
    dom.historyBtn.addEventListener('click', () => togglePanel('history'));
    dom.tabToday.addEventListener('click', () => setTab('today'));
    dom.tabHistory.addEventListener('click', () => setTab('history'));
    dom.tabMoney.addEventListener('click', () => setTab('money'));
    dom.tabWork.addEventListener('click', () => setTab('work'));
    dom.tabGrowth.addEventListener('click', () => setTab('growth'));
    dom.tabSettings.addEventListener('click', () => setTab('settings'));
    dom.sideClose.addEventListener('click', () => closePanel());
    dom.updateReload.addEventListener('click', reloadForUpdate);
    setInterval(() => { if (!document.hidden) checkForUpdate(); }, 5 * 60 * 1000);
    dom.scrim.addEventListener('click', () => closePanel());
    dom.newBtn.addEventListener('click', newChat);
    dom.voiceModeBtn.addEventListener('click', cycleVoiceMode);
    dom.stopBtn.addEventListener('click', stopSpeaking);
    dom.lockBtn.addEventListener('click', () => {
        state.token = '';
        store('tapan.token', null);
        state.seq += 1;                               // retire the current socket
        if (state.socket) { try { state.socket.close(); } catch (e) { /* ignore */ } }
        showAuth(false);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !dom.installSheet.classList.contains('hidden')) closeInstallSheet();
        else if (e.key === 'Escape' && !dom.moreSheet.classList.contains('hidden')) closeMoreSheet();
        else if (e.key === 'Escape' && dom.app.dataset.panel === 'open') closePanel();
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || '');
        if (e.key === '/' && !typing && !state.authNeeded) { e.preventDefault(); dom.userInput.focus(); }
    });
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stopOrb();
        else { startOrb(); document.title = state.baseTitle; checkForUpdate(); if (state.conn === 'offline' || state.conn === 'reconnecting') connect(); }
    });
    window.addEventListener('online', () => { if (!state.authNeeded) connect(); });
    try {
        if (navigator.permissions && navigator.permissions.query) {
            navigator.permissions.query({ name: 'notifications' }).then((p) => { p.onchange = () => { push.checkedAt = 0; pushRefresh(); }; }, () => {});
        }
    } catch (e) { /* not supported */ }
    window.addEventListener('offline', () => setConn('offline', 'Offline'));

    // Keep the composer above the on-screen keyboard (iOS/Android shrink the *visual* viewport only).
    if (window.visualViewport) {
        const fit = () => {
            document.documentElement.style.setProperty('--vvh', `${window.visualViewport.height}px`);
            dom.app.classList.toggle('kbd', window.innerHeight - window.visualViewport.height > 150);      // the on-screen keyboard is up: hide the bottom bar
            window.scrollTo(0, 0);
        };
        window.visualViewport.addEventListener('resize', fit);
        fit();
    }
}

// App shortcuts / deep links from the home-screen icon: ?new=1 starts a fresh chat, ?panel=today|history opens the drawer.
function handleLaunchIntent() {
    let params;
    try { params = new URLSearchParams(window.location.search); } catch (e) { return; }
    if (params.get('new') === '1') {
        state.sessionId = `chat-${Date.now().toString(36)}`;
        store('tapan.session', state.sessionId);
        state.historyFor = state.sessionId;
    }
    const panel = params.get('panel');
    if (panel === 'today' || panel === 'history' || panel === 'settings') setTimeout(() => openPanel(panel), 0);
    if (params.toString() && window.history.replaceState) window.history.replaceState(null, '', window.location.pathname);   // keep the URL clean
}

function init() {
    bindDom();
    dom.greeting.textContent = greetingText();
    dom.userInput.placeholder = INPUT_PLACEHOLDER;
    applyVoiceMode();
    bindEvents();
    initVoice();
    syncDrawerA11y();
    updateInstallUI();
    registerServiceWorker();
    handleLaunchIntent();
    try { init3D(); } catch (err) { console.warn('Status orb disabled:', err); }   // decorative: never break chat
    setInterval(() => { if (!document.hidden && !state.authNeeded && state.conn !== 'locked') refreshToday(true); }, 60000);
    connect();
    startNotifications();
    refreshSend();
}

window.TapanApp = { state, dom, push, sendMessage };
window.TapanHost = { reload: () => window.location.reload(), api, netTiming: NET, imageTools, addPictures, busyStart: (label) => { const op = { label, delay: NET.showWrite }; netStart(op); return op; }, busyEnd: (op) => netStop(op), toast, announce, h, store, state, push, deviceId, webVersion: WEB_VERSION, isStandalone, copyText, checkForUpdate, sendClientReport, closePanel: () => closePanel() };   // read-only handle for tests and debugging in the console

if (!window.__TAPAN_NO_AUTOINIT) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
}
