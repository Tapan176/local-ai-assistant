// Money tab: payments (EMIs, one-off dues, money owed with no date), groups, banks and advice. Spending and subscriptions live in
// money-spend.js and plug in through TapanMoney.extend. Talks only to /api/expenses.
// Rendering is a plain "state in, DOM out" repaint; open forms keep their text in `S.drafts` so a repaint never eats typing,
// and the focused control is found again by its data-fk key so keyboard and screen-reader users keep their place.
(function () {
    'use strict';
    const host = () => window.TapanHost;
    const h = (tag, cls, text) => host().h(tag, cls, text);

    const S = {
        data: null, view: 'overview', loading: false, error: null, busy: false,
        open: new Set(), drafts: {}, form: null,          // form: which inline form is open, e.g. 'add-payment', 'edit-emi:12', 'bank:3'
        confirm: null, advice: null, adviceBusy: false, focusNext: null,
        excluded: new Set(),                                // groups left out of the overview totals (remembered on this device)
        pick: {},                                           // payment id -> Set of EMI ids ticked in the "mark several" panel
    };
    const ticking = new Set();                              // EMI ids whose paid/unpaid change is still being saved
    const EXTRA = [];                                       // views added by other scripts: { id, label, render(), load() }
    let root = null;
    let confirmTimer = null;

    // ── formatting ───────────────────────────────────────────────
    function currency() { return (S.data && S.data.currency) || 'INR'; }
    function money(minor) {
        const code = currency();
        try {
            const whole = minor % 100 === 0;
            return new Intl.NumberFormat(code === 'INR' ? 'en-IN' : undefined, {
                style: 'currency', currency: code, minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2,
            }).format(minor / 100);
        } catch (e) { return `${code} ${(minor / 100).toFixed(2)}`; }
    }
    function parseDay(iso) { const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); }
    function niceDate(iso) { return parseDay(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' }); }
    function niceMonth(key) {
        if (key === 'overdue') return 'Overdue';
        const [y, m] = key.split('-').map(Number);
        return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
    }
    function daysFromToday(iso) {
        const today = parseDay(S.data.overview.today);
        return Math.round((parseDay(iso) - today) / 86400000);
    }
    function whenText(emi) {
        if (emi.status === 'paid') return emi.paid_at ? `Paid ${niceDate(emi.paid_at)}` : 'Paid';
        const d = daysFromToday(emi.due_date);
        if (d < 0) return `Overdue by ${-d} day${d === -1 ? '' : 's'} · was due ${niceDate(emi.due_date)}`;
        if (d === 0) return 'Due today';
        if (d === 1) return 'Due tomorrow';
        return d <= 31 ? `Due in ${d} days · ${niceDate(emi.due_date)}` : `Due ${niceDate(emi.due_date)}`;
    }
    function todayIso() { return S.data ? S.data.overview.today : new Date().toISOString().slice(0, 10); }

    async function errorText(err) {
        try { const j = err && err.response ? await err.response.json() : null; if (j && j.detail) return typeof j.detail === 'string' ? j.detail : 'Check the values and try again.'; } catch (e) { /* ignore */ }
        return err && err.message === 'unauthorized' ? 'Locked. Enter your access token first.' : 'That did not work. Check the connection and try again.';
    }
    const jsonOpts = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

    // ── data ─────────────────────────────────────────────────────
    function exclParam() { const x = Array.from(S.excluded); return x.length ? `?exclude=${encodeURIComponent(x.join(','))}` : ''; }
    async function fetchAll() {
        S.data = await host().api('/api/expenses' + exclParam());
        const extra = EXTRA.find((v) => v.id === S.view);
        if (extra && extra.load) await extra.load();
    }
    async function load() {
        S.loading = true; S.error = null; paint();
        try { await fetchAll(); }
        catch (err) { S.error = await errorText(err); }
        S.loading = false; paint();
    }
    let chain = Promise.resolve();
    let pending = 0;
    // Run one change. A tick may queue behind another tick so ticking several EMIs quickly applies every one, in order; anything
    // else is dropped while a change is in flight (a double tap must not double-apply). Reload once, after the last change.
    function change(path, method, body, doneText, queue) {
        if (pending > 0 && !queue) return Promise.resolve(false);
        pending += 1; S.busy = true; root.setAttribute('aria-busy', 'true');
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
            if (pending === 0) {
                try { await fetchAll(); } catch (err) { S.error = await errorText(err); }
                S.busy = false; root.removeAttribute('aria-busy');
            }
            return ok;
        });
    }
    async function act(path, method, body, doneText, after, queue) {
        const ok = await change(path, method, body, doneText, queue);
        if (ok && after) after();
        if (pending === 0) paint();                        // repainting while ticks are still queued would undo the ones not yet saved
        return ok;
    }
    async function go(view, focus) {
        S.view = view; S.form = null; S.focusNext = focus || `nav:${view}`; paint();
        const extra = EXTRA.find((v) => v.id === view);
        if (extra && extra.load) { try { await extra.load(); } catch (err) { S.error = await errorText(err); } paint(); }
    }
    function saveExcluded() { try { host().store('tapan.money.exclude', JSON.stringify(Array.from(S.excluded).slice(0, 30))); } catch (e) { /* ignore */ } }
    async function toggleGroup(name, include, fk) {
        if (include) S.excluded.delete(name.toLowerCase()); else S.excluded.add(name.toLowerCase());
        saveExcluded(); S.focusNext = fk;
        try { await fetchAll(); S.error = null; } catch (err) { S.error = await errorText(err); }
        paint();
    }

    // ── tiny building blocks ─────────────────────────────────────
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
        const b = btn(armed ? armedLabel : label, () => {
            if (S.confirm === key) { clearTimeout(confirmTimer); S.confirm = null; action(); return; }
            S.confirm = key; S.focusNext = `danger:${key}`; paint();
            clearTimeout(confirmTimer);
            confirmTimer = setTimeout(() => { if (S.confirm === key) { S.confirm = null; paint(); } }, 5000);
        }, 'link-btn danger', `danger:${key}`, armed ? `${armedLabel}. ${aria || ''}` : aria);
        return b;
    }
    function draft(formKey, init) {
        if (!S.drafts[formKey]) S.drafts[formKey] = Object.assign({}, init);
        return S.drafts[formKey];
    }
    function field(formKey, name, label, opts = {}) {
        const d = S.drafts[formKey];
        const wrap = h('label', 'set-field');
        wrap.appendChild(h('span', null, label));
        let input;
        if (opts.options) {
            input = h('select');
            opts.options.forEach(([value, text]) => { const o = h('option', null, text); o.value = value; input.appendChild(o); });
        } else if (opts.area) {
            input = h('textarea'); input.rows = 2;
        } else {
            input = h('input'); input.type = opts.type || 'text';
            if (opts.type !== 'date' && opts.type !== 'number') input.setAttribute('inputmode', opts.inputmode || 'text');
            if (opts.type === 'number') { input.min = opts.min; input.max = opts.max; input.step = '1'; input.setAttribute('inputmode', 'numeric'); }
        }
        input.name = name; input.autocomplete = 'off'; input.spellcheck = false;
        if (opts.maxLength) input.maxLength = opts.maxLength;
        if (opts.placeholder) input.placeholder = opts.placeholder;
        if (opts.required) input.required = true;
        input.value = d[name] === undefined || d[name] === null ? '' : d[name];
        input.dataset.fk = `${formKey}:${name}`;
        input.addEventListener('input', () => { d[name] = input.value; if (opts.onInput) opts.onInput(); });
        wrap.appendChild(input);
        if (opts.list && opts.list.length) {
            const id = `dl-${formKey}-${name}`.replace(/[^a-z0-9-]/gi, '-');
            input.setAttribute('list', id);
            const dl = h('datalist'); dl.id = id;
            opts.list.forEach((v) => { const o = h('option'); o.value = v; dl.appendChild(o); });
            wrap.appendChild(dl);
        }
        if (opts.hint) wrap.appendChild(h('small', 'mn-hint', opts.hint));
        return wrap;
    }
    function checkField(formKey, name, label, hint, onChange) {
        const d = S.drafts[formKey];
        const wrap = h('label', 'mn-pref');
        const box = h('input'); box.type = 'checkbox'; box.checked = Boolean(d[name]); box.dataset.fk = `${formKey}:${name}`;
        box.addEventListener('change', () => { d[name] = box.checked; if (onChange) onChange(box.checked); });
        const text = h('span', null, label);
        if (hint) text.appendChild(h('small', 'mn-hint', hint));
        wrap.append(box, text);
        return wrap;
    }
    function groupNames() { return (S.data.groups || []).filter((g) => g.name !== '~ungrouped').map((g) => g.label); }
    function setDom(formKey, name, value) {
        const el = Array.from(root.querySelectorAll('[data-fk]')).find((n) => n.dataset.fk === `${formKey}:${name}`);
        if (el) el.value = value;
    }
    const round2 = (x) => String(Math.round(x * 100) / 100);
    const toNum = (v) => Number(String(v).replace(/,/g, ''));
    function closeForm() { S.form = null; paint(); }
    function openForm(key, focus) { S.form = key; S.focusNext = focus || null; paint(); }

    function bankOptions() { return [['', 'No bank chosen'], ...S.data.banks.map((b) => [String(b.id), b.name])]; }
    const REMIND_OPTIONS = [['-1', 'No reminders'], ['0', 'On the day, 9 am'], ['1', '1 day before, 9 am'], ['2', '2 days before'], ['3', '3 days before'], ['7', 'A week before']];
    const CATEGORY_LABEL = { loan: 'Loan', card: 'Credit card', rent: 'Rent', insurance: 'Insurance', subscription: 'Subscription', purchase: 'Purchase on EMI', tax: 'Tax', personal: 'Personal / owed to someone', other: 'Other' };
    const KIND_LABEL = { emi: 'Paid in EMIs', due: 'One payment with a due date (e.g. a minimum due)', open: 'No due date (I pay when I can)' };
    const kindOf = (p) => p.kind || 'emi';

    // ── overview ─────────────────────────────────────────────────
    function stat(label, value, sub, tone) {
        const c = h('div', `mn-stat${tone ? ' ' + tone : ''}`);
        c.append(h('div', 'mn-stat-l', label), h('div', 'mn-stat-v', value));
        if (sub) c.appendChild(h('div', 'mn-stat-s', sub));
        return c;
    }
    function payNext(next) {
        return btn('Mark paid', () => act(`/api/expenses/emis/${next.emi_id}`, 'PATCH', { paid: true, deduct: deductPref() && payHasBank(next.payment_id) }, 'Marked as paid'),
            'link-btn', `next-paid`, `Mark EMI ${next.seq} of ${next.payment} as paid`);
    }
    function payHasBank(paymentId) { const p = S.data.payments.find((x) => x.id === paymentId); return Boolean(p && p.bank_id); }
    function deductPref() { return host().store('tapan.money.deduct') !== '0'; }

    function spendCards() {
        const sp = S.data.spending;
        if (!sp || !EXTRA.length) return null;
        const wrap = h('div', 'mn-cards2');
        const a = h('div', 'card mn-mini');
        a.append(h('div', 'mn-stat-l', 'Spent this month'), h('div', 'mn-stat-v', money(sp.spent_minor)));
        if (sp.budget_minor) {
            const prog = h('progress', 'mn-progress'); prog.max = sp.budget_minor; prog.value = Math.min(sp.spent_minor, sp.budget_minor);
            prog.setAttribute('aria-label', `${money(sp.spent_minor)} of your ${money(sp.budget_minor)} budget`);
            a.append(prog, h('div', `mn-stat-s${sp.spent_minor > sp.budget_minor ? ' bad' : ''}`, sp.budget_left_minor >= 0 ? `${money(sp.budget_left_minor)} left of ${money(sp.budget_minor)}` : `${money(-sp.budget_left_minor)} over ${money(sp.budget_minor)}`));
        } else a.appendChild(h('div', 'mn-stat-s', sp.previous_minor ? `Last month ${money(sp.previous_minor)}` : 'Add what you spend to see where it goes'));
        a.appendChild(btn('Open spending', () => go('spending'), 'link-btn', 'open-spending'));
        const b = h('div', 'card mn-mini');
        b.append(h('div', 'mn-stat-l', 'Subscriptions'), h('div', 'mn-stat-v', sp.subs_active ? `${money(sp.subs_monthly_minor)}/mo` : 'None'),
            h('div', 'mn-stat-s', sp.subs_active ? `${money(sp.subs_yearly_minor)} a year${sp.subs_due_7 ? ` · ${sp.subs_due_7} renewing this week` : ''}` : 'Track what renews and when'));
        b.appendChild(btn('Open subscriptions', () => go('subs'), 'link-btn', 'open-subs'));
        wrap.append(a, b);
        return wrap;
    }
    function groupsBlock() {
        const d = S.data;
        if (!(d.groups || []).length || (d.groups.length < 2 && !d.excluded.length)) return null;
        const sec = h('section', 'sec');
        sec.appendChild(h('h2', null, 'Groups'));
        sec.appendChild(h('p', 'muted', 'Untick a group to leave it out of the totals above, for example to see everything except your home loan. Bank checks always count every payment.'));
        const ul = h('ul', 'mn-groups');
        d.groups.forEach((g) => {
            const li = h('li', 'mn-group');
            const label = h('label', 'mn-check');
            const box = h('input'); box.type = 'checkbox'; box.checked = g.included; box.dataset.fk = `group:${g.name}`;
            box.addEventListener('change', () => toggleGroup(g.name, box.checked, `group:${g.name}`));
            const text = h('span', 'mn-emi-text');
            text.append(h('span', 'mn-emi-t', g.label), h('span', 'mn-emi-s', `${g.active} active · ${money(g.remaining_minor)} left · ${money(g.due_30_minor)} in 30 days${g.overdue ? ` · ${g.overdue} overdue` : ''}`));
            label.append(box, text, h('span', 'sr-only', g.included ? ' included in totals' : ' left out of totals'));
            li.appendChild(label);
            ul.appendChild(li);
        });
        sec.appendChild(ul);
        return sec;
    }
    function overviewView() {
        const d = S.data, ov = d.overview, frag = h('div', 'mn-view');
        if (!d.payments.length) {
            const card = h('div', 'card mn-empty');
            card.append(h('h3', null, 'Track what you owe'),
                h('p', 'muted', 'Add the payments you have to make (a loan, a card bill, a phone on EMI, money you owe someone). I split them into EMIs, remind you before each one, and check your banks can cover them.'));
            const row = h('div', 'set-actions');
            row.append(btn('Add a payment', () => { S.view = 'payments'; openForm('add-payment', 'add-payment:title'); }, 'wide-btn', 'empty-add'),
                btn('Add a bank', () => { S.view = 'banks'; openForm('add-bank', 'add-bank:name'); }, 'link-btn', 'empty-bank'));
            card.appendChild(row);
            card.appendChild(h('p', 'muted', 'You can also just tell me in chat: "Add a phone EMI of 24000 over 6 months starting 5 Dec".'));
            frag.appendChild(card);
            const sc = spendCards(); if (sc) frag.appendChild(sc);
            frag.appendChild(insightsBlock());
            return frag;
        }
        const scope = d.excluded && d.excluded.length ? ' (selected groups)' : '';
        const grid = h('div', 'mn-grid');
        grid.append(
            stat('Overdue', ov.overdue.count ? money(ov.overdue.amount_minor) : 'None', ov.overdue.count ? `${ov.overdue.count} EMI${ov.overdue.count === 1 ? '' : 's'}` : 'All caught up', ov.overdue.count ? 'bad' : 'good'),
            stat('Due in 7 days', money(ov.due_7.amount_minor), `${ov.due_7.count} EMI${ov.due_7.count === 1 ? '' : 's'}`),
            stat('Due in 30 days', money(ov.due_30.amount_minor), `${ov.due_30.count} EMI${ov.due_30.count === 1 ? '' : 's'}`),
            stat('Still to pay', money(ov.remaining_minor), (ov.free_by ? `Last EMI ${niceDate(ov.free_by)}` : 'Nothing left') + scope),
        );
        if (ov.open && ov.open.count) grid.appendChild(stat('Pay when you can', money(ov.open.amount_minor), `${ov.open.count} with no due date`));
        frag.appendChild(grid);
        if (d.hidden && d.hidden.payments) {
            const note = h('p', `set-note${d.hidden.overdue ? ' bad' : ''}`, `${d.hidden.payments} payment${d.hidden.payments === 1 ? ' is' : 's are'} left out of these totals${d.hidden.overdue ? `, and ${d.hidden.overdue} of their EMIs ${d.hidden.overdue === 1 ? 'is' : 'are'} overdue` : ''}.`);
            frag.appendChild(note);
        }
        const gb = groupsBlock(); if (gb) frag.appendChild(gb);
        if (ov.next) {
            const n = ov.next, card = h('div', 'card mn-next');
            const info = h('div', 'mn-next-info');
            info.append(h('div', 'mn-next-t', n.of > 1 ? `Next: ${n.payment} · EMI ${n.seq} of ${n.of}` : `Next: ${n.payment}`), h('div', 'muted', `${money(n.amount_minor)} · ${whenText({ status: 'x', due_date: n.due_date })}`));
            card.append(info, payNext(n));
            frag.appendChild(card);
        }
        const sc = spendCards(); if (sc) frag.appendChild(sc);
        frag.appendChild(monthsBlock());
        frag.appendChild(insightsBlock());
        frag.appendChild(adviceBlock());
        const foot = h('div', 'set-actions');
        foot.appendChild(btn('Download all EMIs (CSV)', downloadCsv, 'link-btn', 'export'));
        frag.appendChild(foot);
        return frag;
    }
    function monthsBlock() {
        const months = S.data.overview.months.slice(0, 12);
        const sec = h('section', 'sec');
        sec.appendChild(h('h2', null, 'What is coming, month by month'));
        if (!months.length) { sec.appendChild(h('p', 'muted', 'Nothing left to pay.')); return sec; }
        const max = Math.max(...months.map((m) => m.amount_minor), 1);
        const list = h('ul', 'mn-months');
        months.forEach((m) => {
            const li = h('li', `mn-month${m.month === 'overdue' ? ' bad' : ''}`);
            const bar = h('span', 'mn-bar'); bar.style.setProperty('--w', `${Math.max(3, Math.round((m.amount_minor / max) * 100))}%`);
            bar.setAttribute('aria-hidden', 'true');
            li.append(h('span', 'mn-month-l', niceMonth(m.month)), bar, h('span', 'mn-month-v', `${money(m.amount_minor)} · ${m.count}`));
            list.appendChild(li);
        });
        sec.appendChild(list);
        return sec;
    }
    const LEVEL = { warn: 'Needs attention', info: 'Heads-up', good: 'Good news' };
    function insightsBlock() {
        const sec = h('section', 'sec');
        sec.appendChild(h('h2', null, 'What to watch'));
        const ul = h('ul', 'mn-insights');
        S.data.insights.forEach((i) => {
            const li = h('li', `mn-insight ${i.level}`);
            li.append(h('strong', null, `${LEVEL[i.level] || 'Note'}: `), document.createTextNode(i.text));
            ul.appendChild(li);
        });
        sec.appendChild(ul);
        return sec;
    }
    function adviceBlock() {
        const sec = h('section', 'sec');
        sec.appendChild(h('h2', null, 'AI money advice'));
        const card = h('div', 'card mn-advice');
        if (S.advice && S.advice.advice) {
            card.appendChild(h('p', 'mn-advice-text', S.advice.advice));
            card.appendChild(h('p', 'muted', 'Written by your AI model from the figures above. It is a prompt to think, not professional financial advice.'));
        } else if (S.advice) {
            card.appendChild(h('p', 'muted', 'The AI model is not available right now. The checks above are the advice I can give without it.'));
        } else {
            card.appendChild(h('p', 'muted', 'Ask your AI model for a short plan based on these figures. This sends your payment names, amounts and bank names and balances (not notes) to the model you configured.'));
        }
        const b = btn(S.adviceBusy ? 'Thinking…' : (S.advice ? 'Ask again' : 'Get AI advice'), askAdvice, 'wide-btn', 'advice');
        b.disabled = S.adviceBusy;
        card.appendChild(b);
        sec.appendChild(card);
        return sec;
    }
    async function askAdvice() {
        if (S.adviceBusy) return;
        S.adviceBusy = true; S.focusNext = 'advice'; paint();
        try { S.advice = await host().api('/api/expenses/advice', jsonOpts('POST')); host().announce('Advice ready'); }
        catch (err) { const msg = await errorText(err); host().toast(msg, 4000); S.advice = null; }
        S.adviceBusy = false; S.focusNext = 'advice'; paint();
    }
    async function downloadCsv() {
        try {
            const res = await fetch('/api/expenses/export', { headers: host().state.token ? { Authorization: `Bearer ${host().state.token}` } : {} });
            if (!res.ok) throw new Error('export');
            const url = URL.createObjectURL(await res.blob());
            const a = document.createElement('a'); a.href = url; a.download = 'tapan-expenses.csv'; document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 2000);
        } catch (e) { host().toast('Could not download the file. Try again.', 3500); }
    }

    // ── payments ─────────────────────────────────────────────────
    function paymentsView() {
        const frag = h('div', 'mn-view');
        const top = h('div', 'mn-bar-row');
        top.appendChild(btn('+ Add payment', () => openForm('add-payment', 'add-payment:title'), 'wide-btn', 'add-payment-btn'));
        frag.appendChild(top);
        if (S.form === 'add-payment') frag.appendChild(addPaymentForm());
        const prefWrap = h('label', 'mn-pref');
        const box = h('input'); box.type = 'checkbox'; box.checked = deductPref(); box.dataset.fk = 'pref-deduct';
        box.addEventListener('change', () => { host().store('tapan.money.deduct', box.checked ? '1' : '0'); });
        prefWrap.append(box, h('span', null, 'When I tick an EMI as paid, also reduce that payment\'s bank balance'));
        frag.appendChild(prefWrap);
        const pays = S.data.payments.slice().sort((a, b) => (a.finished - b.finished) || String(a.next_due || '9').localeCompare(String(b.next_due || '9')) || a.id - b.id);
        if (!pays.length && S.form !== 'add-payment') frag.appendChild(h('p', 'muted', 'No payments yet. Add one above.'));
        pays.forEach((p) => frag.appendChild(paymentCard(p)));
        return frag;
    }

    function addPaymentForm() {
        const key = 'add-payment';
        const d = draft(key, { kind: 'emi', title: '', total: '', emi_amount: '', driver: 'total', emis: '1', first_due: todayIso(), day: '', bank_id: '', category: 'loan', remind: '1', grp: '', notes: '' });
        const form = h('form', 'card mn-form');
        form.noValidate = true;
        form.setAttribute('aria-label', 'Add a payment');
        const preview = h('p', 'muted mn-preview');
        const refresh = () => {
            const n = parseInt(d.emis, 10);
            if (d.kind !== 'emi') { preview.textContent = ''; return; }
            const total = toNum(d.total), each = toNum(d.emi_amount), ok = n >= 1 && n <= 360;
            if (!ok) preview.textContent = '';
            else if (d.driver === 'each' && each > 0) preview.textContent = `Total will be ${money(Math.round(each * 100) * n)} (${n} × ${money(Math.round(each * 100))}).`;
            else if (total > 0) preview.textContent = `About ${money(Math.round((total * 100) / n))} per EMI; the last EMI absorbs any rounding. You can change any EMI afterwards.`;
            else preview.textContent = '';
        };
        // Type the total OR the amount of each EMI: whichever you touched last drives, the other is worked out live.
        const recompute = () => {
            const n = parseInt(d.emis, 10);
            if (!(n >= 1 && n <= 360)) return;
            if (d.driver === 'each') { const each = toNum(d.emi_amount); d.total = each > 0 ? round2(Math.round(each * 100) * n / 100) : ''; setDom(key, 'total', d.total); }
            else { const total = toNum(d.total); d.emi_amount = total > 0 ? round2(Math.round((total * 100) / n) / 100) : ''; setDom(key, 'emi_amount', d.emi_amount); }
            refresh();
        };
        const kindField = field(key, 'kind', 'What kind of payment?', { options: Object.entries(KIND_LABEL), onInput: () => paint() });
        form.append(h('h3', null, 'New payment'), field(key, 'title', 'What is it?', { required: true, maxLength: 120, placeholder: d.kind === 'open' ? 'Money I owe Rahul' : 'Car loan' }), kindField);
        if (d.kind === 'emi') {
            form.append(
                field(key, 'total', 'Total amount', { inputmode: 'decimal', placeholder: '120000', onInput: () => { d.driver = 'total'; recompute(); } }),
                field(key, 'emis', 'Number of EMIs', { type: 'number', min: 1, max: 360, onInput: recompute, hint: '1 for a one-off payment' }),
                field(key, 'emi_amount', 'Amount of each EMI', { inputmode: 'decimal', placeholder: '5000', onInput: () => { d.driver = 'each'; recompute(); }, hint: 'Know the EMI instead of the total? Type it and the total is worked out for you.' }),
                field(key, 'first_due', 'First EMI date', { type: 'date', required: true }),
                field(key, 'day', 'Same day every month (optional)', { type: 'number', min: 1, max: 31, hint: 'Leave empty to use the first EMI\'s day. Day 31 becomes the last day of shorter months.' }),
            );
        } else if (d.kind === 'due') {
            form.append(
                field(key, 'emi_amount', 'Amount due', { inputmode: 'decimal', required: true, placeholder: '1500', hint: 'For a credit card this is the minimum due.' }),
                field(key, 'total', 'Total outstanding (optional)', { inputmode: 'decimal', placeholder: '48000', hint: 'Only for your records. It must not be less than the amount due.' }),
                field(key, 'first_due', 'Due date', { type: 'date', required: true }),
            );
        } else {
            form.append(field(key, 'total', 'Amount you owe', { inputmode: 'decimal', required: true, placeholder: '5000', hint: 'No date, no reminders. It stays on your list until you settle it. You can pay it off in parts.' }));
        }
        if (d.kind !== 'open') form.append(field(key, 'bank_id', 'Paid from', { options: bankOptions() }));
        form.append(
            field(key, 'grp', 'Group (optional)', { maxLength: 40, list: groupNames(), placeholder: 'Home loan', hint: 'Payments in one group can be left out of the totals together.' }),
            field(key, 'category', 'Type', { options: Object.entries(CATEGORY_LABEL) }),
        );
        if (d.kind !== 'open') form.append(field(key, 'remind', 'Remind me', { options: REMIND_OPTIONS }));
        form.append(field(key, 'notes', 'Notes (optional)', { area: true, maxLength: 500 }), preview);
        refresh();
        const row = h('div', 'set-actions');
        const submit = h('button', 'wide-btn', 'Create payment'); submit.type = 'submit'; submit.dataset.fk = 'add-payment:submit';
        row.append(submit, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', 'add-payment:cancel'));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const body = {
                title: d.title, kind: d.kind, bank_id: d.kind !== 'open' && d.bank_id ? Number(d.bank_id) : null, category: d.category, grp: d.grp, notes: d.notes,
                remind_days: d.kind === 'open' || d.remind === '-1' ? null : Number(d.remind),
            };
            if (d.kind === 'emi') {
                Object.assign(body, { emis: parseInt(d.emis, 10) || 0, first_due: d.first_due, day: d.day ? parseInt(d.day, 10) : null });
                if (d.driver === 'each' && d.emi_amount) body.emi_amount = d.emi_amount; else body.total = d.total;
            } else if (d.kind === 'due') {
                Object.assign(body, { emi_amount: d.emi_amount, first_due: d.first_due });
                if (String(d.total).trim()) body.total = d.total;
            } else body.total = d.total;
            act('/api/expenses/payments', 'POST', body, 'Payment added', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function metaLine(p) {
        const kind = kindOf(p);
        if (kind === 'open') return p.finished ? 'Settled' : `${money(p.remaining_minor)} owed · no due date${p.paid_minor ? ` · ${money(p.paid_minor)} paid so far` : ''}`;
        if (kind === 'due') return p.finished ? 'Paid' : `${money(p.emis[0] ? p.emis[0].amount_minor : 0)} due ${p.next_due ? niceDate(p.next_due) : ''}`;
        return p.finished ? `Finished · ${p.emi_count} EMIs paid` : `${p.paid_count} of ${p.emi_count} paid · ${money(p.remaining_minor)} left${p.next_due ? ' · next ' + niceDate(p.next_due) : ''}`;
    }
    function paymentCard(p) {
        const kind = kindOf(p);
        const bankName = (S.data.banks.find((b) => b.id === p.bank_id) || {}).name;
        const det = h('details', `mn-pay${p.finished ? ' done' : ''}${p.included === false ? ' muted-out' : ''}`);
        det.dataset.id = p.id;
        det.open = S.open.has(p.id);
        det.addEventListener('toggle', () => { if (det.open) S.open.add(p.id); else S.open.delete(p.id); });
        const sum = h('summary', 'mn-pay-sum');
        sum.dataset.fk = `pay:${p.id}`;
        const head = h('span', 'mn-pay-head');
        head.append(h('span', 'mn-pay-title', p.title), h('span', 'mn-pay-meta', metaLine(p)));
        const prog = h('progress', 'mn-progress');
        if (kind === 'open') { prog.max = Math.max(p.total_minor, 1); prog.value = Math.min(p.paid_minor, p.total_minor); prog.setAttribute('aria-label', `${money(p.paid_minor)} of ${money(p.total_minor)} paid`); }
        else { prog.max = Math.max(p.emi_count, 1); prog.value = p.paid_count; prog.setAttribute('aria-label', `${p.paid_count} of ${p.emi_count} EMIs paid`); }
        sum.append(head, prog);
        det.appendChild(sum);

        const body = h('div', 'mn-pay-body');
        const facts = [CATEGORY_LABEL[p.category] || p.category, kind === 'due' ? `Outstanding ${money(p.total_minor)}` : `Total ${money(p.total_minor)}`];
        if (p.grp) facts.push(`group ${p.grp}`);
        if (kind !== 'open') facts.push(bankName ? `from ${bankName}` : 'no bank chosen', p.remind_days === null ? 'no reminders' : p.remind_days === 0 ? 'reminds on the day' : `reminds ${p.remind_days} day${p.remind_days === 1 ? '' : 's'} before`);
        body.appendChild(h('p', 'muted', facts.join(' · ')));
        if (p.notes) body.appendChild(h('p', 'mn-notes', p.notes));
        const fixed = p.emis.filter((e) => e.custom && e.status !== 'paid').length;
        if (p.mismatch_minor !== 0) {
            const warn = h('div', 'mn-warn');
            const diff = Math.abs(p.mismatch_minor);
            warn.appendChild(h('span', null, p.mismatch_minor > 0 ? `The EMIs add up to ${money(diff)} more than the total.` : `The EMIs add up to ${money(diff)} less than the total.`));
            warn.appendChild(btn('Spread the rest evenly', () => act(`/api/expenses/payments/${p.id}/rebalance`, 'POST', undefined, 'EMIs rebalanced'), 'link-btn', `rebalance:${p.id}`,
                fixed ? `Spread what is left of ${p.title} evenly over the unpaid EMIs you have not fixed` : `Spread what is left of ${p.title} evenly over the unpaid EMIs`));
            if (fixed) warn.appendChild(h('small', 'mn-hint', `${fixed} EMI${fixed === 1 ? '' : 's'} with an amount you set keep${fixed === 1 ? 's' : ''} it.`));
            body.appendChild(warn);
        }
        if (S.form === `edit-payment:${p.id}`) body.appendChild(editPaymentForm(p));
        else if (S.form === `redate:${p.id}`) body.appendChild(redateForm(p));
        else if (S.form === `bulk:${p.id}`) body.appendChild(bulkPanel(p));
        else if (S.form === `open-pay:${p.id}`) body.appendChild(openPayForm(p));
        if (kind === 'open') {
            const info = h('p', 'mn-open-line', p.finished ? `Settled ${p.settled_at ? niceDate(p.settled_at) : ''}. ${money(p.paid_minor)} paid in total.` : `Paid so far ${money(p.paid_minor)} of ${money(p.total_minor)}. Still owed: ${money(p.remaining_minor)}.`);
            body.appendChild(info);
        } else {
            const ul = h('ul', 'mn-emis');
            p.emis.forEach((e) => ul.appendChild(emiRow(p, e)));
            body.appendChild(ul);
        }
        const actions = h('div', 'set-actions');
        if (kind === 'open') {
            if (!p.finished) actions.appendChild(btn('Record a payment', () => { delete S.drafts[`open-pay:${p.id}`]; openForm(`open-pay:${p.id}`, `open-pay:${p.id}:amount`); }, 'link-btn', `open-pay-btn:${p.id}`, `Record money paid towards ${p.title}`));
            actions.appendChild(btn(p.finished ? 'Reopen' : 'Mark settled', () => act(`/api/expenses/payments/${p.id}`, 'PATCH', { settled: !p.finished }, p.finished ? 'Reopened' : 'Marked settled'), 'link-btn', `settle:${p.id}`, `${p.finished ? 'Reopen' : 'Mark as fully paid'}: ${p.title}`));
        }
        actions.appendChild(btn('Edit', () => { delete S.drafts[`edit-payment:${p.id}`]; openForm(`edit-payment:${p.id}`, `edit-payment:${p.id}:title`); }, 'link-btn', `edit-pay:${p.id}`, `Edit ${p.title}`));
        if (kind === 'emi') {
            if (p.emis.some((e) => e.status !== 'paid')) actions.appendChild(btn('Mark several paid', () => { S.pick[p.id] = new Set(); openForm(`bulk:${p.id}`, `bulk:${p.id}:first`); }, 'link-btn', `bulk-btn:${p.id}`, `Pick several EMIs of ${p.title} and mark them paid together`));
            actions.append(
                btn('Spread equally', () => act(`/api/expenses/payments/${p.id}/rebalance`, 'POST', undefined, 'Spread equally'), 'link-btn', `spread:${p.id}`,
                    fixed ? `Spread what is left evenly over the unpaid EMIs of ${p.title}; ${fixed} with an amount you set keep it` : `Spread what is left evenly over the unpaid EMIs of ${p.title}`),
            );
            if (fixed) actions.appendChild(dangerBtn(`spread-all:${p.id}`, 'Spread over all', 'Tap again to replace fixed amounts', () => act(`/api/expenses/payments/${p.id}/rebalance`, 'POST', { reset: true }, 'Spread over every unpaid EMI'), `Replaces the ${fixed} amount${fixed === 1 ? '' : 's'} you set by hand`));
            actions.append(
                btn('Set one day for all', () => openForm(`redate:${p.id}`, `redate:${p.id}:day`), 'link-btn', `redate-btn:${p.id}`, `Set one common EMI day for every unpaid EMI of ${p.title}`),
                btn('+ EMI', () => act(`/api/expenses/payments/${p.id}/emis`, 'POST', {}, 'EMI added. Tap Edit on it to set its amount or date.'), 'link-btn', `add-emi:${p.id}`, `Add another EMI to ${p.title}`),
            );
        }
        actions.appendChild(dangerBtn(`pay:${p.id}`, 'Delete', 'Tap again to delete', () => act(`/api/expenses/payments/${p.id}`, 'DELETE', undefined, 'Payment deleted', () => S.open.delete(p.id)), `This removes ${p.title} and all its EMIs. Bank balances already changed stay as they are.`));
        body.appendChild(actions);
        det.appendChild(body);
        return det;
    }

    function bulkPanel(p) {
        const key = `bulk:${p.id}`;
        const pick = S.pick[p.id] || (S.pick[p.id] = new Set());
        const unpaid = p.emis.filter((e) => e.status !== 'paid');
        const box = h('div', 'card mn-form');
        box.setAttribute('role', 'group'); box.setAttribute('aria-label', `Mark several EMIs of ${p.title} as paid`);
        box.appendChild(h('strong', null, 'Mark several EMIs as paid'));
        const quick = h('div', 'set-actions');
        const choose = (ids, fk) => { pick.clear(); ids.forEach((i) => pick.add(i)); S.focusNext = fk; paint(); };
        quick.append(
            btn('Next 3', () => choose(unpaid.slice(0, 3).map((e) => e.id), `${key}:first`), 'link-btn', `${key}:n3`),
            btn('All due or overdue', () => choose(unpaid.filter((e) => e.status === 'overdue' || e.status === 'today').map((e) => e.id), `${key}:due`), 'link-btn', `${key}:due`),
            btn('All unpaid', () => choose(unpaid.map((e) => e.id), `${key}:all`), 'link-btn', `${key}:all`),
            btn('Clear', () => choose([], `${key}:clear`), 'link-btn', `${key}:clear`),
        );
        box.appendChild(quick);
        const ul = h('ul', 'mn-emis');
        unpaid.forEach((e, i) => {
            const li = h('li', `mn-emi ${e.status}`);
            const label = h('label', 'mn-check');
            const cb = h('input'); cb.type = 'checkbox'; cb.checked = pick.has(e.id); cb.dataset.fk = i === 0 ? `${key}:first` : `pick:${e.id}`;
            cb.addEventListener('change', () => { if (cb.checked) pick.add(e.id); else pick.delete(e.id); S.focusNext = cb.dataset.fk; paint(); });
            const text = h('span', 'mn-emi-text');
            text.append(h('span', 'mn-emi-t', `${kindOf(p) === 'due' ? 'Amount due' : `EMI ${e.seq} of ${p.emi_count}`} · ${money(e.amount_minor)}`), h('span', 'mn-emi-s', whenText(e)));
            label.append(cb, text);
            li.appendChild(label);
            ul.appendChild(li);
        });
        box.appendChild(ul);
        const total = unpaid.filter((e) => pick.has(e.id)).reduce((sum, e) => sum + e.amount_minor, 0);
        const row = h('div', 'set-actions');
        const go2 = btn(pick.size ? `Mark ${pick.size} paid · ${money(total)}` : 'Tick the EMIs to mark', () => {
            const ids = unpaid.filter((e) => pick.has(e.id)).map((e) => e.id);
            act('/api/expenses/emis/bulk', 'POST', { ids, paid: true, deduct: deductPref() && Boolean(p.bank_id) }, `${ids.length} EMI${ids.length === 1 ? '' : 's'} marked paid`, () => { S.pick[p.id] = new Set(); S.form = null; });
        }, 'wide-btn', `${key}:go`);
        go2.disabled = pick.size === 0;
        row.append(go2, btn('Cancel', () => { S.pick[p.id] = new Set(); closeForm(); }, 'link-btn', `${key}:cancel`));
        box.appendChild(row);
        return box;
    }

    function openPayForm(p) {
        const key = `open-pay:${p.id}`;
        const d = draft(key, { amount: '' });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', `Record a payment towards ${p.title}`);
        form.append(field(key, 'amount', 'Amount you paid now', { inputmode: 'decimal', required: true, placeholder: String(Math.round(p.remaining_minor / 100)), hint: `${money(p.remaining_minor)} is still owed. Paying all of it settles this.` }));
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', 'Record payment'); save.type = 'submit';
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const add = Math.round(toNum(d.amount) * 100);
            if (!(add > 0)) { host().toast('Enter the amount you paid.', 3000); return; }
            act(`/api/expenses/payments/${p.id}`, 'PATCH', { open_paid: round2((p.paid_minor + add) / 100) }, 'Payment recorded', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function editPaymentForm(p) {
        const key = `edit-payment:${p.id}`;
        const kind = kindOf(p);
        const d = draft(key, { title: p.title, total: String(p.total_minor / 100), bank_id: p.bank_id ? String(p.bank_id) : '', category: p.category, remind: p.remind_days === null ? '-1' : String(p.remind_days), grp: p.grp || '', notes: p.notes });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', `Edit ${p.title}`);
        form.append(
            field(key, 'title', 'Name', { required: true, maxLength: 120 }),
            field(key, 'total', kind === 'open' ? 'Amount you owe' : kind === 'due' ? 'Total outstanding' : 'Total amount', { inputmode: 'decimal', required: true,
                hint: kind === 'emi' ? 'Changing the total does not change your EMIs. You will be offered to spread the difference.' : undefined }),
            field(key, 'grp', 'Group (optional)', { maxLength: 40, list: groupNames(), hint: 'Payments in one group can be left out of the totals together.' }),
        );
        if (kind !== 'open') form.append(field(key, 'bank_id', 'Paid from', { options: bankOptions() }));
        form.append(field(key, 'category', 'Type', { options: Object.entries(CATEGORY_LABEL) }));
        if (kind !== 'open') form.append(field(key, 'remind', 'Remind me', { options: REMIND_OPTIONS }));
        form.append(field(key, 'notes', 'Notes', { area: true, maxLength: 500 }));
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', 'Save'); save.type = 'submit';
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const body = { title: d.title, total: d.total, category: d.category, grp: d.grp, notes: d.notes };
            if (kind !== 'open') Object.assign(body, { bank_id: d.bank_id ? Number(d.bank_id) : null, remind_days: d.remind === '-1' ? null : Number(d.remind) });
            act(`/api/expenses/payments/${p.id}`, 'PATCH', body, 'Saved', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function redateForm(p) {
        const key = `redate:${p.id}`;
        const d = draft(key, { day: String(p.due_day) });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', `Common EMI day for ${p.title}`);
        form.append(
            field(key, 'day', 'EMI day of the month', { type: 'number', min: 1, max: 31, required: true, hint: 'Moves every unpaid EMI to this day of its month. Paid EMIs are not touched. Day 31 becomes the last day in shorter months.' }),
        );
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', 'Apply'); save.type = 'submit';
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            act(`/api/expenses/payments/${p.id}/redate`, 'POST', { day: parseInt(d.day, 10) || 0 }, 'All unpaid EMIs moved', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function emiRow(p, e) {
        const li = h('li', `mn-emi ${e.status}`);
        if (S.form === `edit-emi:${e.id}`) { li.appendChild(editEmiForm(p, e)); return li; }
        const single = kindOf(p) === 'due';
        const label = h('label', 'mn-check');
        const box = h('input'); box.type = 'checkbox'; box.checked = e.status === 'paid'; box.dataset.fk = `emi:${e.id}`;
        box.addEventListener('change', () => {
            if (ticking.has(e.id)) { box.checked = !box.checked; return; }          // a second tap on the same EMI while it is saving is ignored
            const paid = box.checked;                      // ticks on different EMIs queue: ticking several in a row saves every one, in order
            ticking.add(e.id);
            act(`/api/expenses/emis/${e.id}`, 'PATCH', { paid, deduct: paid && deductPref() && Boolean(p.bank_id) }, paid ? `${single ? 'Payment' : 'EMI ' + e.seq} marked paid` : `${single ? 'Payment' : 'EMI ' + e.seq} marked unpaid`, undefined, true)
                .finally(() => ticking.delete(e.id));
        });
        const text = h('span', 'mn-emi-text');
        const title = h('span', 'mn-emi-t', single ? `Amount due · ${money(e.amount_minor)}` : `EMI ${e.seq} of ${p.emi_count} · ${money(e.amount_minor)}`);
        if (e.custom && e.status !== 'paid') { const chip = h('span', 'mn-chip', 'fixed'); chip.title = 'You set this amount. Spreading equally leaves it alone.'; title.append(' ', chip); }
        text.append(title, h('span', 'mn-emi-s', whenText(e) + (e.deducted ? ' · bank balance reduced' : '')));
        const sr = h('span', 'sr-only', ` ${p.title}, ${e.status === 'paid' ? 'paid. Untick to mark unpaid' : 'unpaid. Tick to mark paid'}${e.custom && e.status !== 'paid' ? '. Amount is fixed' : ''}`);
        label.append(box, text, sr);
        li.appendChild(label);
        li.appendChild(btn('Edit', () => { delete S.drafts[`edit-emi:${e.id}`]; openForm(`edit-emi:${e.id}`, `edit-emi:${e.id}:amount`); }, 'link-btn', `edit-emi-btn:${e.id}`, `Edit ${single ? 'the payment' : 'EMI ' + e.seq} of ${p.title}`));
        return li;
    }

    function editEmiForm(p, e) {
        const key = `edit-emi:${e.id}`;
        const single = kindOf(p) === 'due';
        const d = draft(key, { amount: String(e.amount_minor / 100), due_date: e.due_date, keep: Boolean(e.custom), keepTouched: false });
        const form = h('form', 'mn-form mn-emi-form');
        form.noValidate = true; form.setAttribute('aria-label', `Edit ${single ? 'payment' : 'EMI ' + e.seq} of ${p.title}`);
        const locked = e.status === 'paid';
        form.appendChild(h('strong', null, single ? 'Amount due' : `EMI ${e.seq} of ${p.emi_count}`));
        if (locked) form.appendChild(h('p', 'muted', 'This EMI is marked paid. Untick it first to change its amount or date.'));
        const amount = field(key, 'amount', 'Amount', { inputmode: 'decimal', required: true, onInput: () => {
            if (!d.keepTouched && !single) { d.keep = true; const cb = Array.from(root.querySelectorAll('[data-fk]')).find((n) => n.dataset.fk === `${key}:keep`); if (cb) cb.checked = true; }
        } });
        const date = field(key, 'due_date', 'Date', { type: 'date', required: true });
        if (locked) [amount, date].forEach((w) => { w.querySelector('input').disabled = true; });
        form.append(amount, date);
        if (!single && !locked) form.appendChild(checkField(key, 'keep', 'Keep this amount when I spread equally', 'Off: this EMI takes an equal share like the others.', () => { d.keepTouched = true; }));
        const row = h('div', 'set-actions');
        if (!locked) { const save = h('button', 'wide-btn', 'Save EMI'); save.type = 'submit'; row.appendChild(save); }
        row.appendChild(btn(locked ? 'Close' : 'Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        if (!locked && !single) row.appendChild(dangerBtn(`emi:${e.id}`, 'Delete EMI', 'Tap again to delete', () => act(`/api/expenses/emis/${e.id}`, 'DELETE', undefined, 'EMI deleted', () => { delete S.drafts[key]; S.form = null; }), `Removes EMI ${e.seq} of ${p.title}`));
        form.appendChild(row);
        form.addEventListener('submit', (ev) => {
            ev.preventDefault();
            if (locked) return;
            const body = { amount: d.amount, due_date: d.due_date };
            if (!single) body.custom = Boolean(d.keep);
            act(`/api/expenses/emis/${e.id}`, 'PATCH', body, 'EMI updated', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    // ── banks ────────────────────────────────────────────────────
    function banksView() {
        const frag = h('div', 'mn-view');
        frag.appendChild(h('p', 'muted', 'Banks hold the balance you enter. I use it to warn you when upcoming EMIs cannot be covered. It never connects to a real bank.'));
        frag.appendChild(btn('+ Add bank', () => openForm('add-bank', 'add-bank:name'), 'wide-btn', 'add-bank-btn'));
        if (S.form === 'add-bank') frag.appendChild(bankForm(null));
        if (!S.data.banks.length && S.form !== 'add-bank') frag.appendChild(h('p', 'muted', 'No banks yet.'));
        S.data.overview.banks.forEach((b) => {
            if (S.form === `bank:${b.id}`) { frag.appendChild(bankForm(b)); return; }
            const row = h('div', 'card mn-bank');
            const info = h('div', 'mn-bank-info');
            const used = S.data.payments.filter((p) => p.bank_id === b.id && !p.finished).length;
            info.append(h('div', 'mn-bank-name', b.name), h('div', `mn-bank-bal${b.balance_minor < 0 ? ' bad' : ''}`, money(b.balance_minor)),
                h('div', 'muted', `${used} active payment${used === 1 ? '' : 's'} · ${money(b.due_30_minor)} due in 30 days`));
            if (b.note) info.appendChild(h('div', 'muted', b.note));
            if (b.shortfall_minor > 0) info.appendChild(h('div', 'mn-warn-text', `Short by ${money(b.shortfall_minor)} for the next 30 days`));
            else if (b.due_30_minor > 0) info.appendChild(h('div', 'mn-ok-text', 'Covers the next 30 days'));
            const acts = h('div', 'mn-bank-acts');
            acts.append(btn('Edit', () => { delete S.drafts[`bank:${b.id}`]; openForm(`bank:${b.id}`, `bank:${b.id}:name`); }, 'link-btn', `bank-edit:${b.id}`, `Edit ${b.name}`),
                dangerBtn(`bank:${b.id}`, 'Delete', 'Tap again to delete', () => act(`/api/expenses/banks/${b.id}`, 'DELETE', undefined, 'Bank deleted'), `Payments using ${b.name} stay, but without a bank.`));
            row.append(info, acts);
            frag.appendChild(row);
        });
        return frag;
    }
    function bankForm(b) {
        const key = b ? `bank:${b.id}` : 'add-bank';
        const d = draft(key, b ? { name: b.name, balance: String(b.balance_minor / 100), note: b.note } : { name: '', balance: '', note: '' });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', b ? `Edit ${b.name}` : 'Add a bank');
        form.append(
            field(key, 'name', 'Bank name', { required: true, maxLength: 60, placeholder: 'HDFC savings' }),
            field(key, 'balance', 'Balance now', { inputmode: 'decimal', placeholder: '25000', hint: 'Type what you have today. Use a minus sign if overdrawn.' }),
            field(key, 'note', 'Note (optional)', { maxLength: 200 }),
        );
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', b ? 'Save' : 'Add bank'); save.type = 'submit';
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const body = { name: d.name, balance: d.balance === '' ? 0 : d.balance, note: d.note };
            act(b ? `/api/expenses/banks/${b.id}` : '/api/expenses/banks', b ? 'PATCH' : 'POST', body, b ? 'Saved' : 'Bank added', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    // ── shell ────────────────────────────────────────────────────
    const viewList = () => [['overview', 'Overview'], ['payments', 'Payments'], ...EXTRA.map((v) => [v.id, v.label]), ['banks', 'Banks']];
    function paint() {
        if (!root) return;
        const active = document.activeElement;
        const fk = S.focusNext || (active && root.contains(active) ? active.dataset.fk : null);
        const scroll = root.scrollTop;
        S.focusNext = null;

        const nav = h('div', 'mn-nav');
        nav.setAttribute('role', 'group'); nav.setAttribute('aria-label', 'Money sections');
        viewList().forEach(([id, label]) => {
            const b = btn(label, () => go(id), 'mn-nav-btn', `nav:${id}`);
            b.setAttribute('aria-pressed', String(S.view === id));
            nav.appendChild(b);
        });
        const children = [nav];
        if (S.error && !S.data) {
            children.push(h('p', 'set-note bad', S.error), btn('Try again', load, 'wide-btn', 'retry'));
        } else if (!S.data) {
            children.push(h('p', 'set-note', 'Loading…'));
        } else {
            if (S.error) children.push(h('p', 'set-note bad', S.error));
            const extra = EXTRA.find((v) => v.id === S.view);
            children.push(extra ? extra.render() : S.view === 'payments' ? paymentsView() : S.view === 'banks' ? banksView() : overviewView());
        }
        root.replaceChildren(...children);
        root.scrollTop = scroll;
        if (fk) {
            const target = Array.from(root.querySelectorAll('[data-fk]')).find((n) => n.dataset.fk === fk);
            if (target && !target.disabled) target.focus({ preventScroll: false });
            else if (active && active !== document.body) {                // what had focus is gone (deleted, form closed): land somewhere sensible
                const fallback = root.querySelector('.mn-nav-btn[aria-pressed="true"]');
                if (fallback) fallback.focus({ preventScroll: true });
            }
        }
    }

    window.TapanMoney = {
        render(panel) {
            root = panel;
            try { const saved = JSON.parse(host().store('tapan.money.exclude') || '[]'); S.excluded = new Set(Array.isArray(saved) ? saved.filter((x) => typeof x === 'string').slice(0, 30) : []); } catch (e) { S.excluded = new Set(); }
            paint(); load();
        },
        extend(view) { EXTRA.push(view); },
        // What other Money scripts (spending, subscriptions) build their screens from.
        kit: { S, h, btn, dangerBtn, draft, field, checkField, act, change, paint, openForm, closeForm, money, niceDate, parseDay, todayIso, bankOptions, deductPref, errorText, jsonOpts, go, host, round2, toNum, setDom },
        _state: S,
    };
}());
