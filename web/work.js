// Work tab: tasks with projects, due dates and reminders; notes and plans. Talks only to /api/work and /api/notebook.
(function () {
    'use strict';
    if (!window.TapanKit) return;
    const PRIORITY = [['high', 'High'], ['normal', 'Normal'], ['low', 'Low']];
    const REMIND = [['', 'No reminder'], ['morning', 'The morning of the due date, 9 am'], ['day_before', 'The day before, 9 am'], ['due', 'At the due time (needs a time)']];
    const KINDS = [['note', 'Note'], ['plan', 'Plan'], ['meeting', 'Meeting'], ['idea', 'Idea']];

    const K = window.TapanKit.create({
        name: 'work',
        load: (S) => {
            const q = new URLSearchParams({ status: S.ui.status });
            if (S.ui.project) q.set('project', S.ui.project);
            return K.host().api(`/api/work?${q}`);
        },
        render: (S) => view(S),
    });
    const { S, h, btn, dangerBtn, draft, field, seg, stat, openForm, closeForm, act, paint, reload, host } = K;
    Object.assign(S.ui, { view: 'tasks', status: 'open', project: '', q: '', kind: '', ticking: new Set() });
    const notes = window.TapanKit.notes(K, {
        space: 'work', kinds: KINDS, defaultKind: 'note', formTitle: 'New note or plan',
        bodyLabel: (k) => ({ plan: 'The plan', meeting: 'Meeting notes', idea: 'The idea' }[k] || 'Note'),
        titleLabel: (k) => (k === 'meeting' ? 'Meeting with / about (optional)' : 'Title (optional)'),
        bodyPlaceholder: (k) => ({ plan: 'Goal, steps, who does what, by when', meeting: 'Decisions, action items', idea: 'What if…' }[k] || ''),
    });

    const parseDay = (iso) => { const [y, m, d] = String(iso).slice(0, 10).split('-').map(Number); return new Date(y, m - 1, d); };
    const niceDate = (iso) => parseDay(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
    const daysFrom = (iso) => Math.round((parseDay(iso) - parseDay(S.data.today)) / 86400000);
    function dueText(t) {
        if (!t.due_date) return 'No due date';
        const time = t.due_time ? ` at ${t.due_time}` : '';
        const d = daysFrom(t.due_date);
        if (t.overdue) return `Overdue${d < 0 ? ` by ${-d} day${d === -1 ? '' : 's'}` : ''} · was due ${niceDate(t.due_date)}${time}`;
        if (d === 0) return `Due today${time}`;
        if (d === 1) return `Due tomorrow${time}`;
        return `Due ${niceDate(t.due_date)}${time}`;
    }
    function group(t) {
        if (t.status !== 'open') return 'done';
        if (t.overdue) return 'overdue';
        if (!t.due_date) return 'nodate';
        const d = daysFrom(t.due_date);
        return d <= 0 ? 'today' : d <= 7 ? 'week' : 'later';
    }
    const GROUPS = [['overdue', 'Overdue'], ['today', 'Today'], ['week', 'This week'], ['later', 'Later'], ['nodate', 'No date'], ['done', 'Done']];
    const matches = (t, q) => !q || `${t.title} ${t.project} ${t.details}`.toLowerCase().includes(q.toLowerCase());
    const noteMatches = (n, q) => !q || `${n.title} ${n.body} ${n.tags.join(' ')}`.toLowerCase().includes(q.toLowerCase());
    async function refresh(focus) { if (focus) S.focusNext = focus; await reload(); paint(); }

    // ── tasks ────────────────────────────────────────────────────
    function quickAdd() {
        const d = draft('quick', { title: '' });
        const form = h('form', 'wk-quick');
        form.noValidate = true; form.setAttribute('aria-label', 'Add a task');
        const input = h('input'); input.type = 'text'; input.name = 'title'; input.maxLength = 200; input.autocomplete = 'off';
        input.placeholder = S.ui.project ? `Add a task to ${S.ui.project}` : 'Add a task, then press Enter';
        input.setAttribute('aria-label', 'New task'); input.dataset.fk = 'quick:title'; input.value = d.title;
        input.addEventListener('input', () => { d.title = input.value; });
        const add = h('button', 'wide-btn', 'Add'); add.type = 'submit';
        form.append(input, add);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            if (!d.title.trim()) { host().toast('Type the task first.', 2500); return; }
            act('/api/work/tasks', 'POST', { title: d.title, project: S.ui.project || '' }, 'Task added', () => { d.title = ''; S.focusNext = 'quick:title'; });
        });
        return form;
    }

    function taskForm(t) {
        const key = t ? `edit-task:${t.id}` : 'add-task';
        const d = draft(key, t ? { title: t.title, project: t.project, priority: t.priority, due_date: t.due_date || '', due_time: t.due_time || '', remind: t.remind, details: t.details }
            : { title: '', project: S.ui.project || '', priority: 'normal', due_date: '', due_time: '', remind: '', details: '' });
        const form = h('form', 'card mn-form');
        form.noValidate = true; form.setAttribute('aria-label', t ? `Edit ${t.title}` : 'Add a task with details');
        const projects = (S.data.overview.projects || []).map((p) => p.name);
        form.append(
            h('h3', null, t ? 'Edit task' : 'New task'),
            field(key, 'title', 'Task', { required: true, maxLength: 200, placeholder: 'Send the Q4 report to finance', spellcheck: true }),
            field(key, 'project', 'Project (optional)', { maxLength: 60, list: projects, placeholder: 'Website redesign' }),
            field(key, 'priority', 'Priority', { options: PRIORITY }),
            field(key, 'due_date', 'Due date', { type: 'date', hint: 'Clearing the date also clears the reminder.', onInput: (v) => {
                if (!v && d.remind) { d.remind = ''; const sel = form.querySelector('[name="remind"]'); if (sel) sel.value = ''; }          // no date, no reminder
            } }),
            field(key, 'due_time', 'Due time (optional)', { type: 'time', hint: 'Without a time the task is due by the end of that day.' }),
            field(key, 'remind', 'Remind me', { options: REMIND, hint: 'Needs a due date. The reminder moves with the task and disappears when you finish it.' }),
            field(key, 'details', 'Details (optional)', { area: true, maxLength: 2000, spellcheck: true }),
        );
        const row = h('div', 'set-actions');
        const save = h('button', 'wide-btn', t ? 'Save task' : 'Add task'); save.type = 'submit'; save.dataset.fk = `${key}:submit`;
        row.append(save, btn('Cancel', () => { delete S.drafts[key]; closeForm(); }, 'link-btn', `${key}:cancel`));
        form.appendChild(row);
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            if (d.remind && !d.due_date) { host().toast('A reminder needs a due date.', 3500); return; }
            if (d.remind === 'due' && !d.due_time) { host().toast('Pick a time for that reminder, or choose another one.', 3500); return; }
            const body = { title: d.title, project: d.project, priority: d.priority, details: d.details,
                due: d.due_date ? (d.due_time ? `${d.due_date}T${d.due_time}` : d.due_date) : null, remind: d.due_date ? d.remind : '' };
            act(t ? `/api/work/tasks/${t.id}` : '/api/work/tasks', t ? 'PATCH' : 'POST', body, t ? 'Task saved' : 'Task added', () => { delete S.drafts[key]; S.form = null; });
        });
        return form;
    }

    function taskRow(t) {
        const li = h('li', `wk-task ${t.status}${t.overdue ? ' overdue' : ''}`);
        if (S.form === `edit-task:${t.id}`) { li.appendChild(taskForm(t)); return li; }
        const label = h('label', 'mn-check');
        const box = h('input'); box.type = 'checkbox'; box.checked = t.status === 'done'; box.dataset.fk = `task:${t.id}`;
        box.addEventListener('change', () => {
            if (S.ui.ticking.has(t.id)) { box.checked = !box.checked; return; }          // a second tap on the same task while it saves is ignored
            const done = box.checked;
            S.ui.ticking.add(t.id);
            act(`/api/work/tasks/${t.id}/done`, 'POST', { done }, done ? 'Task done' : 'Task reopened', undefined, true).finally(() => S.ui.ticking.delete(t.id));
        });
        const text = h('span', 'mn-emi-text');
        const title = h('span', 'mn-emi-t', t.title);
        if (t.priority !== 'normal') { const chip = h('span', `mn-chip prio-${t.priority}`, t.priority === 'high' ? 'High' : 'Low'); title.append(' ', chip); }
        if (t.project) { const chip = h('span', 'mn-chip', t.project); title.append(' ', chip); }
        const meta = [t.status === 'done' && t.completed_at ? 'Done' : dueText(t)];
        if (t.remind && t.status === 'open') meta.push('reminder on');
        text.append(title, h('span', 'mn-emi-s', meta.join(' · ')));
        if (t.details) text.appendChild(h('span', 'mn-emi-s wk-details', t.details));
        label.append(box, text, h('span', 'sr-only', ` ${t.status === 'done' ? 'done. Untick to reopen' : 'open. Tick to mark done'}`));
        li.appendChild(label);
        const acts = h('span', 'wk-acts');
        acts.append(
            btn('Edit', () => { delete S.drafts[`edit-task:${t.id}`]; openForm(`edit-task:${t.id}`, `edit-task:${t.id}:title`); }, 'link-btn', `edit-task-btn:${t.id}`, `Edit ${t.title}`),
            dangerBtn(`task:${t.id}`, 'Delete', 'Tap again to delete', () => act(`/api/work/tasks/${t.id}`, 'DELETE', undefined, 'Task deleted'), `Removes ${t.title} and its reminder`),
        );
        li.appendChild(acts);
        return li;
    }

    function tasksView() {
        const d = S.data, ov = d.overview, frag = h('div', 'mn-view');
        const grid = h('div', 'mn-grid');
        grid.append(stat('Open', String(ov.open), ov.high ? `${ov.high} high priority` : 'tasks'), stat('Due today', String(ov.due_today), ov.due_today ? 'on your plate' : 'nothing due'),
            stat('Overdue', String(ov.overdue), ov.overdue ? 'needs attention' : 'all caught up', ov.overdue ? 'bad' : 'good'), stat('Done this week', String(ov.done_7d), 'last 7 days'));
        frag.appendChild(grid);
        frag.appendChild(quickAdd());
        frag.appendChild(S.form === 'add-task' ? taskForm(null) : btn('+ Task with details', () => openForm('add-task', 'add-task:title'), 'link-btn', 'add-task-btn'));

        const filters = h('div', 'wk-filters');
        filters.appendChild(seg('Which tasks', [['open', 'Open'], ['done', 'Done'], ['all', 'All']], S.ui.status, (v) => { S.ui.status = v; refresh(); }, 'wk:status'));
        if (ov.projects.length) {
            const wrap = h('label', 'set-field'); wrap.appendChild(h('span', null, 'Project'));
            const sel = h('select'); sel.dataset.fk = 'wk:project';
            [['', 'All projects'], ...ov.projects.map((p) => [p.name, `${p.name} (${p.open})`])].forEach(([v, t]) => { const o = h('option', null, t); o.value = v; sel.appendChild(o); });
            sel.value = S.ui.project;
            sel.addEventListener('change', () => { S.ui.project = sel.value; refresh('wk:project'); });
            wrap.appendChild(sel); filters.appendChild(wrap);
        }
        const search = h('input'); search.type = 'search'; search.placeholder = 'Search tasks'; search.setAttribute('aria-label', 'Search tasks'); search.dataset.fk = 'wk:q'; search.value = S.ui.q;
        search.autocomplete = 'off'; filters.appendChild(search);
        frag.appendChild(filters);

        const listHost = h('div', 'wk-list');
        const fill = () => {
            const shown = d.tasks.filter((t) => matches(t, S.ui.q));
            const parts = [];
            GROUPS.forEach(([key, title]) => {
                const items = shown.filter((t) => group(t) === key);
                if (!items.length) return;
                const sec = h('section', 'wk-group');
                sec.appendChild(h('h3', `wk-group-t${key === 'overdue' ? ' bad' : ''}`, `${title} · ${items.length}`));
                const ul = h('ul', 'mn-emis'); items.forEach((t) => ul.appendChild(taskRow(t))); sec.appendChild(ul);
                parts.push(sec);
            });
            if (!parts.length) parts.push(h('p', 'muted', S.ui.q ? 'No tasks match that.' : S.ui.status === 'done' ? 'Nothing finished yet.' : 'No tasks yet. Type one above, or tell me in chat: “add a task: send the report by Friday”.'));
            listHost.replaceChildren(...parts);
        };
        search.addEventListener('input', () => { S.ui.q = search.value; fill(); });                    // filters the list in place; the box itself is not rebuilt, so the caret stays
        fill();
        frag.appendChild(listHost);
        return frag;
    }

    // ── notes and plans ──────────────────────────────────────────
    function notesView() {
        const d = S.data, frag = h('div', 'mn-view');
        frag.appendChild(h('p', 'muted', 'Meeting notes, plans and ideas for work. For something to do, add a task instead.'));
        frag.appendChild(S.form === 'add-note:work' ? notes.form(null) : btn('+ New note or plan', () => { delete S.drafts['add-note:work']; openForm('add-note:work', 'add-note:work:body'); }, 'wide-btn', 'add-note-btn'));
        frag.appendChild(seg('Kind of note', [['', 'All'], ...KINDS], S.ui.kind, (v) => { S.ui.kind = v; paint(); }, 'wk:kind'));
        const search = h('input'); search.type = 'search'; search.placeholder = 'Search notes'; search.setAttribute('aria-label', 'Search notes'); search.dataset.fk = 'wk:nq'; search.value = S.ui.q; search.autocomplete = 'off';
        frag.appendChild(search);
        const listHost = h('div', 'wk-list');
        const fill = () => {
            const shown = d.notes.filter((n) => (!S.ui.kind || n.kind === S.ui.kind) && noteMatches(n, S.ui.q));
            listHost.replaceChildren(...(shown.length ? shown.map((n) => notes.card(n)) : [h('p', 'muted', d.notes.length ? 'No notes match.' : 'No notes yet. Capture the next meeting or plan above.')]));
        };
        search.addEventListener('input', () => { S.ui.q = search.value; fill(); });
        fill();
        frag.appendChild(listHost);
        return frag;
    }

    function view() {
        const root = h('div', 'mn-view');
        root.appendChild(seg('Work sections', [['tasks', 'Tasks'], ['notes', 'Notes & plans']], S.ui.view, (v) => { S.ui.view = v; S.form = null; S.ui.q = ''; paint(); }, 'wk:view'));
        root.appendChild(S.ui.view === 'notes' ? notesView() : tasksView());
        return root;
    }

    window.TapanWork = { render(panel) { K.mount(panel); }, _state: S };
}());
