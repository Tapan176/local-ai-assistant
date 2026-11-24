// Settings sections for integrations: Telegram (more are added further down by later features).
(function () {
    if (!window.TapanSettings) return;
    const { register, helpers } = window.TapanSettings;
    const { el, list, note, button, guarded } = helpers;
    const host = () => window.TapanHost;

    function field(label, input) {
        const wrap = el('label', 'set-field');
        wrap.append(el('span', null, label), input);
        return wrap;
    }
    async function post(path, body, method = 'POST') {
        return host().api(path, { method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    }
    async function errorText(err) {
        try { const j = err.response ? await err.response.json() : null; if (j && j.detail) return String(j.detail); } catch (e) { /* ignore */ }
        return err && err.status === 429 ? 'Too many attempts. Wait a minute.' : 'That did not work. Check the details and try again.';
    }

    // ── Telegram ─────────────────────────────────────────────────
    let tgPoll = null;
    function stopPolling() { if (tgPoll) { clearInterval(tgPoll); tgPoll = null; } }

    async function renderTelegram(container) {
        stopPolling();
        await guarded(container, async () => {
            const s = await host().api('/api/telegram/status');
            container.replaceChildren();
            const refresh = () => renderTelegram(container);

            container.appendChild(note('Reminders and chat on any phone, including iPhone. Free, and delivery is confirmed by Telegram, so you can see if a message was accepted.'));

            if (!s.configured) {
                const steps = el('ol', 'set-steps');
                ['In Telegram, open @BotFather and send /newbot, then follow the two questions.', 'Copy the token it gives you (it looks like 123456789:AAE…).', 'Paste it below.']
                    .forEach((t) => steps.appendChild(el('li', null, t)));
                container.appendChild(steps);
                const input = el('input');
                input.type = 'password'; input.autocomplete = 'off'; input.spellcheck = false; input.name = 'bot-token'; input.placeholder = '123456789:AAE…';
                container.appendChild(field('Bot token', input));
                const out = note('');
                container.appendChild(button('Connect', async (e) => {
                    const btn = e.currentTarget; btn.disabled = true;
                    try {
                        const r = await post('/api/telegram/token', { token: input.value });
                        input.value = '';
                        host().toast(`Connected to @${r.bot}`);
                        if (!r.webhook) host().toast(r.webhook_error || 'Webhook not set', 5000);
                        refresh();
                    } catch (err) { out.textContent = await errorText(err); out.className = 'set-note bad'; btn.disabled = false; }
                }, 'wide-btn'));
                container.appendChild(out);
                return;
            }

            container.appendChild(list([['Bot', s.bot ? `@${s.bot}` : '–'], ['Token from', s.from_env ? 'server environment' : 'saved in the app'],
                ['Chat', s.linked ? `linked to ${s.linked_name}` : 'not linked yet', s.linked ? 'good' : 'bad'],
                ['Messages sent · received', `${s.sent} · ${s.received}`], s.last_error ? ['Last error', s.last_error, 'bad'] : null]));

            const actions = el('div', 'set-actions');
            if (!s.linked) {
                const box = el('div', 'set-body');
                container.appendChild(button('Link my Telegram', async (e) => {
                    const btn = e.currentTarget; btn.disabled = true;
                    try {
                        const p = await post('/api/telegram/pair');
                        box.replaceChildren();
                        const open = el('a', 'wide-btn', 'Open Telegram to finish');
                        open.href = p.link; open.target = '_blank'; open.rel = 'noopener noreferrer';
                        box.append(open, note(`Tap Start in the chat. If the link does not open, send this to the bot yourself: /start ${p.code}`), note('The code works once and expires in 10 minutes.'));
                        if (!p.webhook) box.appendChild(note(p.webhook_error || 'The webhook could not be set.', 'bad'));
                        stopPolling();
                        tgPoll = setInterval(async () => {
                            try { if ((await host().api('/api/telegram/status')).linked) { stopPolling(); host().toast('Telegram linked'); refresh(); } } catch (err) { /* keep waiting */ }
                        }, 3000);
                    } catch (err) { box.replaceChildren(note(await errorText(err), 'bad')); btn.disabled = false; }
                }, 'wide-btn'));
                container.appendChild(box);
            } else {
                actions.appendChild(button('Send test message', async () => {
                    try { await post('/api/telegram/test'); host().toast('Test sent to Telegram'); } catch (err) { host().toast(await errorText(err), 4000); }
                }));
                actions.appendChild(button('Unlink', async () => { await post('/api/telegram/unlink'); refresh(); }));
            }
            actions.appendChild(button('Remove bot', async () => {
                if (!window.confirm('Remove this bot from Tapan? You can connect it again later.')) return;
                await host().api('/api/telegram/token', { method: 'DELETE' }); refresh();
            }));
            actions.appendChild(button('Refresh', refresh));
            container.appendChild(actions);
        });
    }
    register('telegram', 'Telegram', renderTelegram, { order: 20 });

    window.TapanSettings.helpers.field = field;
    window.TapanSettings.helpers.post = post;
    window.TapanSettings.helpers.errorText = errorText;
})();
