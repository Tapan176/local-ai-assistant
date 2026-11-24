// Money > Spending and Subscriptions. Built on the helpers money.js exposes (TapanMoney.kit); talks only to /api/expenses.
(function () {
    'use strict';
    if (!window.TapanMoney || !window.TapanMoney.kit) return;
    const K = window.TapanMoney.kit;
    const { S, h, btn, dangerBtn, draft, field, act, openForm, closeForm, money, niceDate, todayIso, bankOptions, deductPref, host, go } = K;

    const SP = { month: null, cat: '', spend: null };          // spending screen: month shown (null = this month), category filter, last fetch
    const SB = { subs: null };                                  // subscriptions screen
    const SPEND_CATS = ['food', 'groceries', 'transport', 'shopping', 'bills', 'rent', 'health', 'entertainment', 'travel', 'education', 'personal', 'gifts', 'other'];
    const SUB_CATS = ['entertainment', 'music', 'software', 'cloud', 'news', 'fitness', 'education', 'shopping', 'bills', 'other'];
    const CYCLES = [['weekly', 'Every week'], ['monthly', 'Every month'], ['quarterly', 'Every 3 months'], ['yearly', 'Every year']];
    const CYCLE_WORD = { weekly: 'week', monthly: 'month', quarterly: '3 months', yearly: 'year' };
    const REMIND = [['-1', 'No reminder'], ['0', 'On the day, 9 am'], ['1', '1 day before, 9 am'], ['2', '2 days before'], ['3', '3 days before'], ['7', 'A week before']];
    const label = (c) => c.charAt(0).toUpperCase() + c.slice(1);
    const opts = (list) => list.map((c) => [c, label(c)]);
    const thisMonth = () => todayIso().slice(0, 7);
    const shiftMonth = (key, n) => { const [y, m] = key.split('-').map(Number); const d = new Date(y, m - 1 + n, 1); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`; };
    const monthName = (key) => { const [y, m] = key.split('-').map(Number); return new Date(y, m - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }); };
    const stat = (l, v, sub, tone) => { const c = h('div', `mn-stat${tone ? ' ' + tone : ''}`); c.append(h('div', 'mn-stat-l', l), h('div', 'mn-stat-v', v)); if (sub) c.appendChild(h('div', 'mn-stat-s', sub)); return c; };

    async function download(path, name) {
        try {
            const res = await fetch(path, { headers: host().state.token ? { Authorization: `Bearer ${host().state.token}` } : {} });
            if (!res.ok) throw new Error('export');
            const url = URL.createObjectURL(await res.blob());
            const a = document.createElement('a'); a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 2000);
        } catch (e) { host().toast('Could not download the file. Try again.', 3500); }
    }

    // ── spending ─────────────────────────────────────────────────
    async function loadSpend() {
        const q = new URLSearchParams();
        if (SP.month) q.set('month', SP.month);
        if (SP.cat) q.set('category', SP.cat);
        SP.spend = await host().api('/api/expenses/spending' + (q.toString() ? `?${q}` : ''));
    }

    function monthBar(summary) {
        const key = summary.month, bar = h('div', 'sp-monthbar');
        bar.setAttribute('role', 'group'); bar.setAttribute('aria-label', 'Choose the month');
        bar.append(
            btn('‹', () => { SP.month = shiftMonth(key, -1); go('spending', 'sp:prev'); }, 'link-btn sp-step', 'sp:prev', 'Previous month'),
            h('strong', 'sp-month', monthName(key)),
        );
        const next = btn('›', () => { const n = shiftMonth(key, 1); SP.month = n === thisMonth() ? null : n; go('spending', 'sp:next'); }, 'link-btn sp-step', 'sp:next', 'Next month');
        next.disabled = key >= thisMonth();
        bar.appendChild(next);
        return bar;
    }

    function addSpendForm(summary) {
        const key = 'add-spend';
        const d = draft(key, { amount: '', category: 'food', note: '', spent_on: todayIso() });
        const form = h('form', 'card mn-form sp-add');
        form.noValidate = true; form.setAttribute('aria-label', 'Add what you spent');
        form.append(
            h('h3', null, 'Add an expense'),
            field(key, 'amount', 'Amount', { inputmode: 'decimal', required: true, placeholder: '250' }),
            field(key, 'category', 'Category', { options: opts(SPEND_CATS) }),
            field(key, 'note', 'What was it? (optional)', { maxLength: 200, placeholder: 'Lunch with team' }),
            field(key, 'spent_on', 'Date', { type: 'date' }),
        );
        const row = h('div', 'set-actions');
        const submit = h('button', 'wide-btn', 'Add expense'); submit.type = 'submit'; submit.dataset.fk = 'add-spend:submit';
        row.append(submit, btn('Done', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', 'add-spend:done'));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            act('/api/expenses/spending', 'POST', { amount: d.amount, category: d.category, note: d.note, spent_on: d.spent_on || null }, 'Expense added', () => {
                d.amount = ''; d.note = '';                          // stay open for the next one; keep the category and date
                S.focusNext = 'add-spend:amount';
            });
        });
        return form;
    }

    function budgetBlock(sm) {
        const sec = h('div', 'card mn-mini sp-budget');
        if (S.form === 'budget') {
            const key = 'budget';
            const d = draft(key, { amount: sm.budget_minor ? String(sm.budget_minor / 100) : '' });
            const form = h('form', 'mn-form');
            form.noValidate = true; form.setAttribute('aria-label', 'Monthly budget');
            form.appendChild(field(key, 'amount', 'Spend at most, per month', { inputmode: 'decimal', placeholder: '30000', hint: 'Leave empty to remove the budget.' }));
            const row = h('div', 'set-actions');
            const save = h('button', 'wide-btn', 'Save budget'); save.type = 'submit';
            row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', 'budget:cancel'));
            form.appendChild(row);
            form.addEventListener('submit', (e) => {
                e.preventDefault();
                act('/api/expenses/budget', 'PUT', { amount: String(d.amount).trim() === '' ? null : d.amount }, 'Budget saved', () => { delete S.drafts[key]; S.form = null; });
            });
            sec.appendChild(form);
            return sec;
        }
        if (sm.budget_minor) {
            const over = sm.total_minor > sm.budget_minor;
            const prog = h('progress', 'mn-progress'); prog.max = sm.budget_minor; prog.value = Math.min(sm.total_minor, sm.budget_minor);
            prog.setAttribute('aria-label', `${money(sm.total_minor)} of your ${money(sm.budget_minor)} budget`);
            sec.append(h('div', 'mn-stat-l', 'Monthly budget'), h('div', `mn-stat-v${over ? ' bad' : ''}`, `${money(sm.total_minor)} of ${money(sm.budget_minor)}`), prog,
                h('div', `mn-stat-s${over ? ' bad' : ''}`, over ? `${money(sm.total_minor - sm.budget_minor)} over budget` : `${money(sm.budget_left_minor)} left`));
        } else sec.append(h('div', 'mn-stat-l', 'Monthly budget'), h('div', 'mn-stat-s', 'Set a limit and I will warn you before you pass it.'));
        sec.appendChild(btn(sm.budget_minor ? 'Change budget' : 'Set a budget', () => { delete S.drafts.budget; openForm('budget', 'budget:amount'); }, 'link-btn', 'budget-btn'));
        return sec;
    }

    function spendRow(item) {
        const li = h('li', 'sp-row');
        if (S.form === `edit-spend:${item.id}`) { li.appendChild(editSpendForm(item)); return li; }
        const info = h('span', 'sp-info');
        info.append(h('span', 'sp-note', item.note || label(item.category)), h('span', 'mn-emi-s', `${niceDate(item.spent_on)} · ${label(item.category)}${item.sub_id ? ' · subscription' : ''}`));
        const amount = h('span', 'sp-amt', money(item.amount_minor));
        const acts = h('span', 'sp-acts');
        acts.append(
            btn('Edit', () => { delete S.drafts[`edit-spend:${item.id}`]; openForm(`edit-spend:${item.id}`, `edit-spend:${item.id}:amount`); }, 'link-btn', `edit-spend-btn:${item.id}`, `Edit ${item.note || label(item.category)}, ${money(item.amount_minor)}`),
            dangerBtn(`spend:${item.id}`, 'Delete', 'Tap again to delete', () => act(`/api/expenses/spending/${item.id}`, 'DELETE', undefined, 'Expense deleted'), `Removes ${money(item.amount_minor)} from your spending`),
        );
        li.append(info, amount, acts);
        return li;
    }
    function editSpendForm(item) {
        const key = `edit-spend:${item.id}`;
        const d = draft(key, { amount: String(item.amount_minor / 100), spent_on: item.spent_on, category: item.category, note: item.note });
        const form = h('form', 'mn-form');
        form.noValidate = true; form.setAttribute('aria-label', 'Edit expense');
        form.append(
            field(key, 'amount', 'Amount', { inputmode: 'decimal', required: true }), field(key, 'category', 'Category', { options: opts(SPEND_CATS) }),
            field(key, 'note', 'Note', { maxLength: 200 }), field(key, 'spent_on', 'Date', { type: 'date' }),
        );
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', 'Save'); save.type = 'submit';
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            act(`/api/expenses/spending/${item.id}`, 'PATCH', { amount: d.amount, category: d.category, note: d.note, spent_on: d.spent_on }, 'Expense updated', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function spendingView() {
        const frag = h('div', 'mn-view');
        if (!SP.spend) { frag.appendChild(h('p', 'set-note', 'Loading…')); return frag; }
        const sm = SP.spend.summary;
        frag.appendChild(monthBar(sm));
        // The totals come first; the form opens on demand and then stays open for the next entry.
        frag.appendChild(S.form === 'add-spend' ? addSpendForm(sm) : btn('+ Add expense', () => openForm('add-spend', 'add-spend:amount'), 'wide-btn', 'add-spend-btn'));
        const grid = h('div', 'mn-grid');
        grid.append(
            stat('Spent', money(sm.total_minor), sm.count ? `${sm.count} entr${sm.count === 1 ? 'y' : 'ies'}` : 'Nothing yet'),
            stat('Last month', money(sm.previous_total_minor), sm.change_pct === null ? 'No data' : `${sm.change_pct >= 0 ? '+' : ''}${sm.change_pct}% this month`, sm.change_pct > 20 ? 'bad' : ''),
            stat('Per day', money(sm.average_per_day_minor), 'average so far'),
            sm.projected_minor !== null ? stat('Month-end', money(sm.projected_minor), 'at this pace') : stat('Biggest', sm.top[0] ? money(sm.top[0].amount_minor) : '–', sm.top[0] ? (sm.top[0].note || label(sm.top[0].category)) : ''),
        );
        frag.appendChild(grid);
        frag.appendChild(budgetBlock(sm));
        if (sm.categories.length) {
            const sec = h('section', 'sec');
            sec.appendChild(h('h2', null, 'Where it went'));
            const max = Math.max(...sm.categories.map((c) => c.amount_minor), 1);
            const ul = h('ul', 'mn-months');
            sm.categories.forEach((c) => {
                const li = h('li', 'mn-month');
                const bar = h('span', 'mn-bar'); bar.style.setProperty('--w', `${Math.max(3, Math.round((c.amount_minor / max) * 100))}%`); bar.setAttribute('aria-hidden', 'true');
                li.append(h('span', 'mn-month-l', label(c.category)), bar, h('span', 'mn-month-v', `${money(c.amount_minor)} · ${c.share}%`));
                ul.appendChild(li);
            });
            sec.appendChild(ul);
            frag.appendChild(sec);
        }
        const sec = h('section', 'sec');
        sec.appendChild(h('h2', null, 'Entries'));
        const filter = h('label', 'set-field');
        filter.appendChild(h('span', null, 'Show'));
        const sel = h('select'); sel.dataset.fk = 'sp:filter';
        [['', 'All categories'], ...opts(SPEND_CATS)].forEach(([v, t]) => { const o = h('option', null, t); o.value = v; sel.appendChild(o); });
        sel.value = SP.cat;
        sel.addEventListener('change', () => { SP.cat = sel.value; go('spending', 'sp:filter'); });
        filter.appendChild(sel);
        sec.appendChild(filter);
        if (!SP.spend.items.length) sec.appendChild(h('p', 'muted', SP.cat ? 'No entries in that category this month.' : 'No expenses this month yet. Add the first one above, or tell me in chat: “spent 250 on lunch”.'));
        const ul = h('ul', 'sp-list');
        SP.spend.items.forEach((i) => ul.appendChild(spendRow(i)));
        sec.appendChild(ul);
        const foot = h('div', 'set-actions');
        foot.appendChild(btn('Download all spending (CSV)', () => download('/api/expenses/spending-export', 'tapan-spending.csv'), 'link-btn', 'export-spend'));
        sec.appendChild(foot);
        frag.appendChild(sec);
        return frag;
    }

    // ── subscriptions ────────────────────────────────────────────
    async function loadSubs() { SB.subs = await host().api('/api/expenses/subscriptions'); }
    const STATUS = { overdue: 'Renewal passed', soon: 'Renews soon', paused: 'Paused', ok: '' };
    function when(sub) {
        if (sub.status === 'paused') return 'Paused. No reminders.';
        const d = sub.days_until;
        const t = d < 0 ? `Renewal date passed ${-d} day${d === -1 ? '' : 's'} ago` : d === 0 ? 'Renews today' : d === 1 ? 'Renews tomorrow' : `Renews in ${d} days`;
        return `${t} · ${niceDate(sub.next_date)}`;
    }

    function subForm(sub) {
        const key = sub ? `edit-sub:${sub.id}` : 'add-sub';
        const d = draft(key, sub ? {
            name: sub.name, amount: String(sub.amount_minor / 100), cycle: sub.cycle, next_date: sub.next_date, category: sub.category,
            bank_id: sub.bank_id ? String(sub.bank_id) : '', remind: sub.remind_days === null ? '-1' : String(sub.remind_days), notes: sub.notes,
        } : { name: '', amount: '', cycle: 'monthly', next_date: todayIso(), category: 'entertainment', bank_id: '', remind: '1', notes: '' });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', sub ? `Edit ${sub.name}` : 'Add a subscription');
        form.append(
            h('h3', null, sub ? 'Edit subscription' : 'New subscription'),
            field(key, 'name', 'Name', { required: true, maxLength: 80, placeholder: 'Netflix' }),
            field(key, 'amount', 'Amount each time', { inputmode: 'decimal', required: true, placeholder: '649' }),
            field(key, 'cycle', 'Billed', { options: CYCLES }),
            field(key, 'next_date', 'Next renewal date', { type: 'date', required: true, hint: 'The day it next charges you. After you mark it renewed, this moves forward by itself.' }),
            field(key, 'category', 'Type', { options: opts(SUB_CATS) }),
            field(key, 'bank_id', 'Paid from', { options: bankOptions() }),
            field(key, 'remind', 'Remind me', { options: REMIND }),
            field(key, 'notes', 'Notes (optional)', { area: true, maxLength: 300 }),
        );
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', sub ? 'Save' : 'Add subscription'); save.type = 'submit'; save.dataset.fk = `${key}:submit`;
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const body = { name: d.name, amount: d.amount, cycle: d.cycle, next_date: d.next_date, category: d.category, bank_id: d.bank_id ? Number(d.bank_id) : null,
                notes: d.notes, remind_days: d.remind === '-1' ? null : Number(d.remind) };
            act(sub ? `/api/expenses/subscriptions/${sub.id}` : '/api/expenses/subscriptions', sub ? 'PATCH' : 'POST', body, sub ? 'Saved' : 'Subscription added', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function subCard(sub) {
        if (S.form === `edit-sub:${sub.id}`) return subForm(sub);
        const card = h('div', `card mn-bank sub ${sub.status}`);
        const info = h('div', 'mn-bank-info');
        const head = h('div', 'mn-bank-name', sub.name);
        if (STATUS[sub.status]) { const chip = h('span', `mn-chip ${sub.status}`, STATUS[sub.status]); head.append(' ', chip); }
        info.append(head, h('div', 'mn-bank-bal', `${money(sub.amount_minor)} / ${CYCLE_WORD[sub.cycle]}`),
            h('div', 'muted', sub.cycle === 'monthly' ? when(sub) : `${money(sub.monthly_minor)} a month · ${when(sub)}`));
        if (sub.notes) info.appendChild(h('div', 'muted', sub.notes));
        const acts = h('div', 'mn-bank-acts');
        if (sub.active) acts.appendChild(btn('Mark renewed', () => act(`/api/expenses/subscriptions/${sub.id}/renew`, 'POST', { record: true, deduct: deductPref() && Boolean(sub.bank_id) },
            `${sub.name} renewed. Next: see the new date.`), 'link-btn', `renew:${sub.id}`, `Mark ${sub.name} as renewed and log ${money(sub.amount_minor)} as spending`));
        acts.append(
            btn(sub.active ? 'Pause' : 'Resume', () => act(`/api/expenses/subscriptions/${sub.id}`, 'PATCH', { active: !sub.active }, sub.active ? 'Paused' : 'Resumed'), 'link-btn', `pause:${sub.id}`, `${sub.active ? 'Pause' : 'Resume'} ${sub.name}`),
            btn('Edit', () => { delete S.drafts[`edit-sub:${sub.id}`]; openForm(`edit-sub:${sub.id}`, `edit-sub:${sub.id}:name`); }, 'link-btn', `edit-sub-btn:${sub.id}`, `Edit ${sub.name}`),
            dangerBtn(`sub:${sub.id}`, 'Delete', 'Tap again to delete', () => act(`/api/expenses/subscriptions/${sub.id}`, 'DELETE', undefined, 'Subscription deleted'), `Removes ${sub.name}. Charges already logged stay in your spending.`),
        );
        card.append(info, acts);
        return card;
    }

    function subsView() {
        const frag = h('div', 'mn-view');
        if (!SB.subs) { frag.appendChild(h('p', 'set-note', 'Loading…')); return frag; }
        const sm = SB.subs.summary;
        frag.appendChild(h('p', 'muted', 'Everything that renews on a schedule. “Mark renewed” logs the charge as spending and moves the date forward.'));
        const grid = h('div', 'mn-grid');
        grid.append(
            stat('Per month', money(sm.monthly_minor), `${sm.active} active`),
            stat('Per year', money(sm.yearly_minor), 'if nothing changes'),
            stat('This week', money(sm.due_7.amount_minor), `${sm.due_7.count} renewing`),
            stat('Paused', String(sm.paused), sm.paused ? 'not counted above' : 'none'),
        );
        frag.appendChild(grid);
        frag.appendChild(btn('+ Add subscription', () => { delete S.drafts['add-sub']; openForm('add-sub', 'add-sub:name'); }, 'wide-btn', 'add-sub-btn'));
        if (S.form === 'add-sub') frag.appendChild(subForm(null));
        if (!SB.subs.subs.length && S.form !== 'add-sub') frag.appendChild(h('p', 'muted', 'No subscriptions yet. Add Netflix, your phone plan, cloud storage, a gym… anything that renews.'));
        SB.subs.subs.forEach((s) => frag.appendChild(subCard(s)));
        if (sm.by_category.length > 1) {
            const sec = h('section', 'sec');
            sec.appendChild(h('h2', null, 'By type'));
            const ul = h('ul', 'mn-months');
            const max = Math.max(...sm.by_category.map((c) => c.monthly_minor), 1);
            sm.by_category.forEach((c) => {
                const li = h('li', 'mn-month');
                const bar = h('span', 'mn-bar'); bar.style.setProperty('--w', `${Math.max(3, Math.round((c.monthly_minor / max) * 100))}%`); bar.setAttribute('aria-hidden', 'true');
                li.append(h('span', 'mn-month-l', label(c.category)), bar, h('span', 'mn-month-v', `${money(c.monthly_minor)}/mo`));
                ul.appendChild(li);
            });
            sec.appendChild(ul);
            frag.appendChild(sec);
        }
        return frag;
    }

    window.TapanMoney.extend({ id: 'spending', label: 'Spending', render: spendingView, load: loadSpend });
    window.TapanMoney.extend({ id: 'subs', label: 'Subscriptions', render: subsView, load: loadSubs });

}());
