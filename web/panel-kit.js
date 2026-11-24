// A small runtime shared by the Work and Growth screens (the Money screens predate it and keep their own copy).
// "State in, DOM out": render() builds the screen from data; open forms keep their text in drafts so a repaint never eats typing; the
// focused control is found again by its data-fk key so keyboard and screen-reader users keep their place; changes are saved one
// request at a time, except ticks, which queue so ticking several things in a row saves every one.
(function () {
    'use strict';
    const host = () => window.TapanHost;
    const h = (tag, cls, text) => host().h(tag, cls, text);

    function create({ render, load, name }) {
        const S = { data: null, error: null, loading: false, busy: false, form: null, drafts: {}, confirm: null, focusNext: null, ui: {} };
        let root = null;
        let confirmTimer = null;
        let chain = Promise.resolve();
        let pending = 0;

        async function errorText(err) {
            try { const j = err && err.response ? await err.response.json() : null; if (j && j.detail) return typeof j.detail === 'string' ? j.detail : 'Check the values and try again.'; } catch (e) { /* ignore */ }
            return err && err.message === 'unauthorized' ? 'Locked. Enter your access token first.' : 'That did not work. Check the connection and try again.';
        }
        const jsonOpts = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

        async function reload() {
            try { S.data = await load(S); S.error = null; } catch (err) { S.error = await errorText(err); }
        }
        async function mount(panel) {
            root = panel; S.loading = true; paint();
            await reload(); S.loading = false; paint();
        }
        // One change at a time (a double tap must not double-apply). queue=true lets ticks line up behind each other; the screen reloads
        // once after the last one so ticks that are still being saved are not undone by a repaint.
        function act(path, method, body, doneText, after, queue) {
            if (pending > 0 && !queue) return Promise.resolve(false);
            pending += 1; S.busy = true; root.setAttribute('aria-busy', 'true');
            const busy = host().busyStart(method === 'DELETE' ? 'Deleting…' : 'Saving…');   // covers the save AND the reload that follows it
            const run = chain.then(async () => {
                try {
                    await host().api(path, jsonOpts(method, body));
                    if (doneText) { host().toast(doneText); host().announce(doneText); }
                    return true;
                } catch (err) {
                    const msg = await errorText(err);
                    host().toast(msg, 4500); host().announce(msg);
                    return false;
                }
            });
            chain = run;
            return run.then(async (ok) => {
                pending -= 1;
                if (ok && after) after();
                if (pending === 0) { await reload(); S.busy = false; root.removeAttribute('aria-busy'); paint(); }
                host().busyEnd(busy);
                return ok;
            });
        }

        // ── building blocks ──
        function btn(label, onClick, cls = 'link-btn', fk, aria) {
            const b = h('button', cls, label);
            b.type = 'button';
            if (fk) b.dataset.fk = fk;
            if (aria) b.setAttribute('aria-label', aria);
            b.addEventListener('click', onClick);
            return b;
        }
        // Two taps to destroy anything: the first arms it for a few seconds.
        function dangerBtn(key, label, armedLabel, action, aria) {
            const armed = S.confirm === key;
            return btn(armed ? armedLabel : label, () => {
                if (S.confirm === key) { clearTimeout(confirmTimer); S.confirm = null; action(); return; }
                S.confirm = key; S.focusNext = `danger:${key}`; paint();
                clearTimeout(confirmTimer);
                confirmTimer = setTimeout(() => { if (S.confirm === key) { S.confirm = null; paint(); } }, 5000);
            }, 'link-btn danger', `danger:${key}`, armed ? `${armedLabel}. ${aria || ''}` : aria);
        }
        function draft(formKey, init) {
            if (!S.drafts[formKey]) S.drafts[formKey] = Object.assign({}, init);
            return S.drafts[formKey];
        }
        function field(formKey, fname, label, opts = {}) {
            const d = S.drafts[formKey];
            const wrap = h('label', 'set-field');
            wrap.appendChild(h('span', null, label));
            let input;
            if (opts.options) {
                input = h('select');
                opts.options.forEach(([value, text]) => { const o = h('option', null, text); o.value = value; input.appendChild(o); });
            } else if (opts.area) {
                input = h('textarea'); input.rows = opts.rows || 3;
            } else {
                input = h('input'); input.type = opts.type || 'text';
                if (!['date', 'time', 'number'].includes(opts.type)) input.setAttribute('inputmode', opts.inputmode || 'text');
            }
            input.name = fname; input.autocomplete = 'off'; input.spellcheck = opts.spellcheck === undefined ? false : opts.spellcheck;
            if (opts.maxLength) input.maxLength = opts.maxLength;
            if (opts.placeholder) input.placeholder = opts.placeholder;
            if (opts.required) input.required = true;
            input.value = d[fname] === undefined || d[fname] === null ? '' : d[fname];
            input.dataset.fk = `${formKey}:${fname}`;
            input.addEventListener('input', () => { d[fname] = input.value; if (opts.onInput) opts.onInput(input.value); });
            wrap.appendChild(input);
            if (opts.list && opts.list.length) {
                const id = `dl-${formKey}-${fname}`.replace(/[^a-z0-9-]/gi, '-');
                input.setAttribute('list', id);
                const dl = h('datalist'); dl.id = id;
                opts.list.forEach((v) => { const o = h('option'); o.value = v; dl.appendChild(o); });
                wrap.appendChild(dl);
            }
            if (opts.hint) wrap.appendChild(h('small', 'mn-hint', opts.hint));
            return wrap;
        }
        // A row of buttons where exactly one is selected (aria-pressed), e.g. the status or kind filter.
        function seg(label, options, current, onPick, fkPrefix) {
            const g = h('div', 'mn-nav pk-seg');
            g.setAttribute('role', 'group'); g.setAttribute('aria-label', label);
            options.forEach(([value, text]) => {
                const b = btn(text, () => { S.focusNext = `${fkPrefix}:${value}`; onPick(value); }, 'mn-nav-btn', `${fkPrefix}:${value}`);
                b.setAttribute('aria-pressed', String(current === value));
                g.appendChild(b);
            });
            return g;
        }
        function stat(label, value, sub, tone) {
            const c = h('div', `mn-stat${tone ? ' ' + tone : ''}`);
            c.append(h('div', 'mn-stat-l', label), h('div', 'mn-stat-v', value));
            if (sub) c.appendChild(h('div', 'mn-stat-s', sub));
            return c;
        }
        function openForm(key, focus) { S.form = key; S.focusNext = focus || null; paint(); }
        function closeForm() { S.form = null; paint(); }

        function paint() {
            if (!root) return;
            const active = document.activeElement;
            const fk = S.focusNext || (active && root.contains(active) ? active.dataset.fk : null);
            const scroll = root.scrollTop;
            S.focusNext = null;
            const children = [];
            if (S.error && !S.data) children.push(h('p', 'set-note bad', S.error), btn('Try again', () => mount(root), 'wide-btn', 'retry'));
            else if (!S.data) children.push(h('p', 'set-note', 'Loading…'));
            else {
                if (S.error) children.push(h('p', 'set-note bad', S.error));
                children.push(render(S));
            }
            root.replaceChildren(...children);
            root.scrollTop = scroll;
            if (fk) {
                const target = Array.from(root.querySelectorAll('[data-fk]')).find((n) => n.dataset.fk === fk);
                if (target && !target.disabled) target.focus({ preventScroll: false });
                else if (active && active !== document.body) {                    // what had focus is gone (deleted, form closed): land somewhere sensible
                    const fallback = root.querySelector('[aria-pressed="true"]') || root.querySelector('button');
                    if (fallback) fallback.focus({ preventScroll: true });
                }
            }
        }

        return { S, h, btn, dangerBtn, draft, field, seg, stat, openForm, closeForm, act, paint, reload, mount, errorText, host, name };
    }

    // Cards and forms for notes, shared by Work (notes and plans) and Growth (journal and rulebook). cfg: { space, kinds: [[value, label]],
    // defaultKind, bodyLabel, bodyPlaceholder, titleLabel(kind), reload }.
    function notes(K, cfg) {
        const { S, h, btn, dangerBtn, draft, field, act, openForm, closeForm } = K;
        const label = (kind) => (cfg.kinds.find(([v]) => v === kind) || [kind, kind])[1];
        const niceDate = (iso) => { try { return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); } catch (e) { return ''; } };

        function form(n, startKind) {
            const key = n ? `edit-note:${n.id}` : `add-note:${cfg.space}`;
            const d = draft(key, n ? { kind: n.kind, title: n.title, body: n.body, tags: n.tags.join(', ') } : { kind: startKind || cfg.defaultKind, title: '', body: '', tags: '' });
            const f = h('form', 'card mn-form');
            f.noValidate = true; f.setAttribute('aria-label', n ? `Edit ${label(n.kind).toLowerCase()}` : `Add to ${cfg.space === 'growth' ? 'your journal' : 'your notes'}`);
            f.append(
                h('h3', null, n ? 'Edit' : cfg.formTitle || 'New note'),
                field(key, 'kind', 'What is it?', { options: cfg.kinds, onInput: () => { K.S.focusNext = `${key}:kind`; K.paint(); } }),
                field(key, 'body', cfg.bodyLabel(d.kind), { area: true, rows: 5, required: true, maxLength: 8000, placeholder: cfg.bodyPlaceholder ? cfg.bodyPlaceholder(d.kind) : '', spellcheck: true }),
                field(key, 'title', cfg.titleLabel(d.kind), { maxLength: 160 }),
                field(key, 'tags', 'Tags (optional)', { maxLength: 200, placeholder: 'habits, focus', hint: 'Separate with commas. Up to 8.' }),
            );
            const row = h('div', 'set-actions');
            const save = h('button', 'wide-btn', n ? 'Save' : 'Add'); save.type = 'submit'; save.dataset.fk = `${key}:submit`;
            row.append(save, btn(n ? 'Cancel' : 'Done', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
            f.appendChild(row);
            f.addEventListener('submit', (e) => {
                e.preventDefault();
                const body = { kind: d.kind, title: d.title, body: d.body, tags: d.tags };
                if (n) act(`/api/notebook/${n.id}`, 'PATCH', body, 'Saved', () => { delete S.drafts[key]; S.form = null; });
                else act('/api/notebook', 'POST', { space: cfg.space, ...body }, 'Saved', () => { d.body = ''; d.title = ''; S.focusNext = `${key}:body`; });      // stays open for the next one
            });
            return f;
        }

        function card(n, index) {
            if (S.form === `edit-note:${n.id}`) return form(n);
            const c = h('article', `card wk-note k-${n.kind}${n.pinned ? ' pinned' : ''}`);
            const head = h('div', 'wk-note-head');
            const chip = h('span', 'mn-chip', cfg.numbered && index !== undefined ? `${label(n.kind)} ${index + 1}` : label(n.kind));
            head.appendChild(chip);
            if (n.pinned) head.appendChild(h('span', 'mn-chip pinned', 'Pinned'));
            if (n.title) head.appendChild(h('strong', 'wk-note-title', n.title));
            c.appendChild(head);
            if (cfg.numbered) {
                const [first, ...rest] = n.body.split('\n');
                c.appendChild(h('p', 'wk-note-rule', first));
                if (rest.join('\n').trim()) c.appendChild(h('p', 'wk-note-body muted', rest.join('\n').trim()));
            } else c.appendChild(h('p', 'wk-note-body', n.body));
            if (n.tags.length) { const tags = h('p', 'wk-tags'); n.tags.forEach((t) => tags.appendChild(h('span', 'mn-chip', `#${t}`))); c.appendChild(tags); }
            c.appendChild(h('p', 'mn-emi-s', niceDate(n.created_at)));
            const acts = h('div', 'set-actions');
            const what = n.title || n.body.slice(0, 30);
            acts.append(
                btn(n.pinned ? 'Unpin' : 'Pin', () => act(`/api/notebook/${n.id}`, 'PATCH', { pinned: !n.pinned }, n.pinned ? 'Unpinned' : 'Pinned'), 'link-btn', `pin:${n.id}`, `${n.pinned ? 'Unpin' : 'Pin'}: ${what}`),
                btn('Edit', () => { delete S.drafts[`edit-note:${n.id}`]; openForm(`edit-note:${n.id}`, `edit-note:${n.id}:body`); }, 'link-btn', `edit-note-btn:${n.id}`, `Edit: ${what}`),
                dangerBtn(`note:${n.id}`, 'Delete', 'Tap again to delete', () => act(`/api/notebook/${n.id}`, 'DELETE', undefined, 'Deleted'), `Removes: ${what}`),
            );
            c.appendChild(acts);
            return c;
        }
        return { form, card, label, niceDate };
    }

    window.TapanKit = { create, notes };
}());
