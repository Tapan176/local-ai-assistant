// Settings section "Memory graph": what the assistant has remembered about the people, places and things in your life, and how they connect.
// You can search it and remove anything. New facts are added by telling the assistant ("Zorya works at Quillon Labs").
(function () {
    if (!window.TapanSettings) return;
    const { register, helpers } = window.TapanSettings;
    const { el, note, button, guarded } = helpers;
    const host = () => window.TapanHost;
    const KIND = { person: 'Person', place: 'Place', org: 'Organisation', project: 'Project', topic: 'Topic', event: 'Event', thing: 'Thing' };

    // two-tap removal: the first tap arms the button for a few seconds, the second does it (a stray tap never deletes)
    function danger(label, armedLabel, aria, action) {
        const b = el('button', 'link-btn danger', label);
        b.type = 'button';
        b.setAttribute('aria-label', aria);
        let timer = null;
        b.addEventListener('click', async () => {
            if (b.dataset.armed === '1') { clearTimeout(timer); b.disabled = true; await action(); return; }
            b.dataset.armed = '1'; b.textContent = armedLabel; b.setAttribute('aria-label', `${armedLabel}: ${aria}`);
            timer = setTimeout(() => { b.dataset.armed = '0'; b.textContent = label; b.setAttribute('aria-label', aria); }, 4000);
        });
        return b;
    }

    async function render(container, query) {
        await guarded(container, async () => {
            const q = query || '';
            const data = await host().api(`/api/graph${q ? `?q=${encodeURIComponent(q)}` : ''}`);
            container.replaceChildren();
            const again = (next) => render(container, next === undefined ? q : next);

            container.appendChild(note('Everything the assistant has remembered about the people, places, projects and things in your life, and how they connect. '
                + 'It is used when you mention them in chat. Add things by telling the assistant, for example "Zorya works at Quillon Labs".'));
            container.appendChild(note(`${data.totals.nodes} things · ${data.totals.edges} connections (limit ${data.totals.max_nodes} and ${data.totals.max_edges})`));

            const form = el('form', 'set-field');
            const input = el('input');
            input.type = 'search'; input.name = 'graph-search'; input.value = q; input.placeholder = 'Search a name'; input.autocomplete = 'off';
            input.setAttribute('aria-label', 'Search the memory graph');
            const go = el('button', 'link-btn', 'Search');
            go.type = 'submit';
            form.append(input, go);
            form.addEventListener('submit', (e) => { e.preventDefault(); again(input.value.trim()); });
            container.appendChild(form);

            if (!data.nodes.length) {
                container.appendChild(note(q ? 'Nothing matches that.' : 'Nothing yet. Tell the assistant about the people and places in your life and it will remember how they connect.'));
                return;
            }

            const ul = el('ul', 'graph-list');
            data.nodes.forEach((n) => {
                const li = el('li', 'graph-node');
                const head = el('div', 'graph-head');
                head.appendChild(el('strong', null, n.name));
                head.appendChild(el('span', 'graph-kind', KIND[n.kind] || 'Thing'));
                li.appendChild(head);
                if (n.summary) li.appendChild(el('p', 'graph-summary', n.summary));
                const mine = data.edges.filter((e) => e.src === n.id || e.dst === n.id);
                if (mine.length) {
                    const rel = el('ul', 'graph-edges');
                    mine.forEach((e) => {
                        const row = el('li');
                        row.appendChild(el('span', null, `${e.src_name} → ${e.relation} → ${e.dst_name}${e.note ? ` (${e.note})` : ''}`));
                        row.appendChild(danger('Remove', 'Tap again', `Remove connection: ${e.src_name} ${e.relation} ${e.dst_name}`, async () => {
                            try { await host().api(`/api/graph/edges/${e.id}`, { method: 'DELETE' }); host().toast('Connection removed'); } catch (err) { host().toast('Could not remove that. Try again.', 3500); }
                            again();
                        }));
                        rel.appendChild(row);
                    });
                    li.appendChild(rel);
                }
                li.appendChild(danger('Forget this', 'Tap again to forget', `Forget ${n.name} and its ${n.degree} connection${n.degree === 1 ? '' : 's'}`, async () => {
                    try { await host().api(`/api/graph/nodes/${n.id}`, { method: 'DELETE' }); host().toast(`Forgot ${n.name}`); } catch (err) { host().toast('Could not forget that. Try again.', 3500); }
                    again();
                }));
                ul.appendChild(li);
            });
            container.appendChild(ul);
            if (data.totals.nodes > data.nodes.length) container.appendChild(note(`Showing the ${data.nodes.length} most connected. Search to find others.`));
            container.appendChild(button('Refresh', () => again()));
        });
    }

    register('memory-graph', 'Memory graph', (container) => render(container, ''), { order: 30 });

    // ── Your data: one file with everything (a readable backup, and the way out) ─
    function renderData(container) {
        container.replaceChildren();
        container.appendChild(note('Download everything the assistant keeps about you as one file: chat history, memories, reminders, payments and EMIs, spending, subscriptions, tasks, notes, '
            + 'journal and the memory graph. It never includes your access token, Telegram token or notification keys. The file is not encrypted, so keep it somewhere private.'));
        const out = note('');
        const btn = button('Download my data', async () => {
            btn.disabled = true; out.textContent = 'Preparing…'; out.className = 'set-note';
            try {
                const data = await host().api('/api/export');
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = el('a'); a.href = url; a.download = `tapan-data-${String(data.exported_at || '').slice(0, 10) || 'export'}.json`;
                document.body.appendChild(a); a.click(); a.remove();
                setTimeout(() => URL.revokeObjectURL(url), 10000);
                const total = Object.values(data.counts || {}).reduce((x, y) => x + y, 0);
                out.textContent = `Downloaded ${total} records (${Math.max(1, Math.round(blob.size / 1024))} KB).`;
                host().toast('Your data was downloaded');
            } catch (err) { out.textContent = 'Could not prepare the file. Check the connection and try again.'; out.className = 'set-note bad'; }
            btn.disabled = false;
        }, 'wide-btn');
        container.append(btn, out);
    }
    register('your-data', 'Your data', renderData, { order: 40 });

    // ── Daily briefing: one short morning message (EMIs due, overdue tasks) ───────
    async function renderDigest(container) {
        await guarded(container, async () => {
            const d = await host().api('/api/digest');
            container.replaceChildren();
            container.appendChild(note('A short message each morning with what needs attention today: overdue and due EMIs, overdue and due tasks. It is built from your own data, '
                + 'with no AI guessing, and goes to your phone notifications and Telegram (whichever you have set up) and shows in the chat. It is off until you turn it on.'));
            const form = el('form', 'set-field');
            const on = el('input'); on.type = 'checkbox'; on.checked = d.enabled; on.name = 'digest-on'; on.id = 'digest-on';
            const onLabel = el('label', null, 'Send me a daily briefing'); onLabel.htmlFor = 'digest-on';
            const at = el('input'); at.type = 'time'; at.value = d.time; at.name = 'digest-time'; at.id = 'digest-time'; at.required = true;
            const atLabel = el('label', null, `Time (${d.timezone || 'your time zone'})`); atLabel.htmlFor = 'digest-time';
            const out = note('');
            const save = el('button', 'wide-btn', 'Save'); save.type = 'submit';
            form.append(on, onLabel, atLabel, at, save);
            form.addEventListener('submit', async (e) => {
                e.preventDefault(); save.disabled = true;
                try {
                    const r = await host().api('/api/digest', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ enabled: on.checked, time: at.value }) });
                    out.textContent = r.enabled ? `Saved. You will get it at ${r.time} every day.` : 'Saved. The daily briefing is off.'; out.className = 'set-note';
                    host().toast(r.enabled ? 'Daily briefing is on' : 'Daily briefing is off');
                } catch (err) { out.textContent = 'Could not save that. Check the time and try again.'; out.className = 'set-note bad'; }
                save.disabled = false;
            });
            container.appendChild(form);
            container.appendChild(el('p', 'set-note', 'What it would say right now:'));
            const box = el('pre', 'digest-preview');
            box.textContent = `${d.preview.title}\n${d.preview.body}`;
            container.appendChild(box);
            container.appendChild(button('Send it to me now', async (e) => {
                const btn = e.currentTarget; btn.disabled = true;
                try {
                    const r = await host().api('/api/digest/test', { method: 'POST' });
                    const sent = Object.values(r.delivery || {}).reduce((n, c) => n + ((c && c.sent) || 0), 0);
                    out.textContent = sent ? 'Sent. Check your phone.' : 'Posted in the chat, but no phone or Telegram is set up to receive it (see Notifications and Telegram).';
                    out.className = 'set-note';
                } catch (err) { out.textContent = err && err.status === 429 ? 'Too many tests. Wait a minute.' : 'Could not send it. Try again.'; out.className = 'set-note bad'; }
                btn.disabled = false;
            }));
            container.appendChild(out);
        });
    }
    register('daily-digest', 'Daily briefing', renderDigest, { order: 25 });
})();
