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
})();
