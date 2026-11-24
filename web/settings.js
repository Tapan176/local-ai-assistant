// Settings tab: a list of collapsible sections, each rendering itself on demand. Other scripts add sections with
// TapanSettings.register(id, title, render). The host (app.js) exposes helpers on window.TapanHost.
(function () {
    const sections = [];
    const host = () => window.TapanHost;
    const el = (tag, cls, text) => host().h(tag, cls, text);

    function register(id, title, render, opts = {}) {
        if (sections.some((s) => s.id === id)) return;
        sections.push({ id, title, render, open: Boolean(opts.open), order: opts.order || 100 });
        sections.sort((a, b) => a.order - b.order);
    }

    // ── tiny view helpers ────────────────────────────────────────
    function ago(iso) {
        if (!iso) return 'never';
        const t = new Date(iso).getTime();
        if (Number.isNaN(t)) return String(iso);
        const s = Math.max(0, Math.round((Date.now() - t) / 1000));
        if (s < 60) return `${s}s ago`;
        if (s < 3600) return `${Math.round(s / 60)} min ago`;
        if (s < 86400) return `${Math.round(s / 3600)} h ago`;
        return `${Math.round(s / 86400)} d ago`;
    }
    function duration(seconds) {
        if (seconds < 90) return `${seconds}s`;
        if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
        if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} h`;
        return `${Math.round(seconds / 86400)} d`;
    }
    function list(rows) {
        const dl = el('dl', 'kv');
        rows.filter(Boolean).forEach(([k, v, tone]) => {
            dl.appendChild(el('dt', null, k));
            dl.appendChild(el('dd', tone || null, v === null || v === undefined || v === '' ? '–' : String(v)));
        });
        return dl;
    }
    function note(text, tone) { return el('p', `set-note${tone ? ' ' + tone : ''}`, text); }
    function button(label, onClick, cls = 'link-btn') {
        const b = el('button', cls, label);
        b.type = 'button';
        b.addEventListener('click', onClick);
        return b;
    }
    async function guarded(container, work) {
        container.replaceChildren(note('Loading…'));
        try { await work(); } catch (err) {
            container.replaceChildren(note(err && err.status === 401 ? 'Locked. Enter your access token first.' : 'Could not load this section. Check the connection and try again.', 'bad'));
        }
    }

    // ── Status ───────────────────────────────────────────────────
    function deviceRows() {
        const H = host();
        const nav = window.navigator;
        const perm = 'Notification' in window ? Notification.permission : 'not supported';
        const swState = 'serviceWorker' in nav ? (nav.serviceWorker.controller ? 'active' : 'not controlling this page') : 'not supported';
        return [
            ['App build', H.webVersion === '__WEB_' + 'VERSION__' ? 'dev' : H.webVersion],
            ['Installed as an app', H.isStandalone() ? 'yes' : 'no (browser tab)'],
            ['Push notifications', H.push.status, ['on'].includes(H.push.status) ? 'good' : (['error', 'blocked'].includes(H.push.status) ? 'bad' : null)],
            ['Notification permission', perm, perm === 'granted' ? 'good' : perm === 'denied' ? 'bad' : null],
            ['Offline support', swState],
            ['Online', nav.onLine ? 'yes' : 'no'],
            ['Browser', (nav.userAgent || '').slice(0, 90)],
        ];
    }

    async function renderStatus(container) {
        const H = host();
        await guarded(container, async () => {
            const d = await H.api('/api/diagnostics');
            const s = d.server, sch = d.scheduler, llm = d.llm;
            container.replaceChildren();

            container.appendChild(el('h3', 'set-h', 'This device'));
            container.appendChild(list(deviceRows()));
            const mine = d.clients.find((c) => c.device === H.deviceId());
            if (mine && !mine.current_build) container.appendChild(note('The server has a newer version than this page. Reload to update.', 'bad'));

            container.appendChild(el('h3', 'set-h', 'Server'));
            container.appendChild(list([
                ['Version', `${s.version} · web ${s.web_version}`],
                ['Uptime', duration(s.uptime_s)],
                ['Database', s.database],
                ['Time zone', s.timezone],
                ['Server time', s.now],
                ['Home city', d.home_location || d.home_location_error || 'not set', d.home_location ? 'good' : 'bad'],
            ]));
            if (s.uptime_s < 600) container.appendChild(note('The server restarted recently. On a free plan it sleeps when idle, so reminders that came due while it slept fire when it wakes.'));

            container.appendChild(el('h3', 'set-h', 'Reminders'));
            container.appendChild(list([
                ['Scheduler last ran', ago(sch.last_tick_at), sch.last_tick_at && (Date.now() - new Date(sch.last_tick_at)) < (sch.poll_seconds * 3000 + 5000) ? 'good' : 'bad'],
                ['Pending', sch.pending],
                ['Overdue and unfired', sch.overdue_pending, sch.overdue_pending ? 'bad' : null],
                ['Next due', sch.next_due],
                ['Fired since start', sch.fired_total],
                ['Scheduler errors', sch.errors, sch.errors ? 'bad' : null],
                sch.last_error ? ['Last error', sch.last_error, 'bad'] : null,
            ]));

            container.appendChild(el('h3', 'set-h', 'Push devices'));
            if (!d.push.enabled) container.appendChild(note('Push is disabled on this server.', 'bad'));
            else if (!d.push.devices.length) container.appendChild(note('No device is registered for push yet. Turn on notifications in the Today tab.', 'bad'));
            d.push.devices.forEach((p) => container.appendChild(list([
                ['Device', p.device], ['Registered', ago(p.since)], ['Last delivery', ago(p.last_success_at)],
                p.last_error ? ['Last error', p.last_error, 'bad'] : null,
            ])));

            container.appendChild(el('h3', 'set-h', 'Pages that reported in'));
            d.clients.forEach((c) => container.appendChild(list([
                ['Device', c.ua_short + (c.device === H.deviceId() ? ' (this one)' : '')],
                ['Reported', ago(c.reported_at)],
                ['Build', c.current_build ? 'current' : `old (${c.web_version || 'unknown'})`, c.current_build ? 'good' : 'bad'],
                ['Push', `${(c.push && c.push.status) || '?'} · permission ${(c.push && c.push.permission) || '?'}${c.push && c.push.issue ? ' · ' + c.push.issue : ''}`],
                ['Installed app', c.standalone ? 'yes' : 'no'],
            ])));

            container.appendChild(el('h3', 'set-h', 'AI'));
            container.appendChild(list([
                ['Provider', `${llm.provider} · ${llm.model}`],
                ['Last answer from', llm.last_ok_at ? `${llm.last_provider} (${ago(llm.last_ok_at)})` : 'nothing yet'],
                ['Calls · ok · failed', `${llm.calls} · ${llm.ok} · ${llm.failed}`],
                llm.last_error ? ['Last error', llm.last_error, 'bad'] : null,
            ]));

            const actions = el('div', 'set-actions');
            actions.appendChild(button('Refresh', () => renderStatus(container)));
            actions.appendChild(button('Copy report', () => H.copyText(JSON.stringify({ device: deviceRows(), server: d }, null, 2), actions.lastChild)));
            actions.appendChild(button('Check for update', async () => { await H.checkForUpdate(true); }));
            container.appendChild(actions);
        });
    }

    register('status', 'Status', renderStatus, { open: true, order: 10 });

    // ── panel rendering ──────────────────────────────────────────
    function render(panel) {
        if (panel.dataset.built === '1') {
            panel.querySelectorAll('details[open] > .set-body').forEach((body) => { const s = sections.find((x) => x.id === body.parentElement.dataset.id); if (s) s.render(body); });
            return;
        }
        panel.dataset.built = '1';
        panel.replaceChildren();
        sections.forEach((s) => {
            const details = el('details', 'set-sec');
            details.dataset.id = s.id;
            const summary = el('summary', null, s.title);
            const body = el('div', 'set-body');
            details.append(summary, body);
            details.addEventListener('toggle', () => { if (details.open) s.render(body); });
            panel.appendChild(details);
            if (s.open) { details.open = true; s.render(body); }
        });
    }

    window.TapanSettings = { register, render, helpers: { ago, duration, list, note, button, guarded, el } };
})();
