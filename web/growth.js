// Growth tab: a journal of learnings, lessons, quotes and thoughts, and a rulebook of personal rules. Talks only to /api/growth and /api/notebook.
(function () {
    'use strict';
    if (!window.TapanKit) return;
    const JOURNAL_KINDS = [['learning', 'Learning'], ['lesson', 'Lesson'], ['quote', 'Quote'], ['thought', 'Thought']];
    const ALL_KINDS = [...JOURNAL_KINDS, ['rule', 'Rule']];

    const K = window.TapanKit.create({ name: 'growth', load: () => K.host().api('/api/growth'), render: () => view() });
    const { S, h, btn, seg, stat, openForm, paint } = K;
    Object.assign(S.ui, { view: 'journal', kind: '', tag: '', q: '', pickShift: 0 });

    const BODY_LABEL = { learning: 'What did you learn?', lesson: 'What is the lesson?', quote: 'The quote', thought: 'What is on your mind?', rule: 'The rule (first line), and why it matters (the lines after)' };
    const PLACEHOLDER = {
        learning: 'Today I learned that…', lesson: 'Next time I will… because…', quote: 'Words worth keeping', thought: 'A thought to come back to',
        rule: 'Never reply to an angry message the same day\nBecause I have regretted every one I sent in a hurry.',
    };
    const notes = window.TapanKit.notes(K, {
        space: 'growth', kinds: ALL_KINDS, defaultKind: 'learning', formTitle: 'Add to your journal',
        bodyLabel: (k) => BODY_LABEL[k] || 'Text', bodyPlaceholder: (k) => PLACEHOLDER[k] || '',
        titleLabel: (k) => (k === 'quote' ? 'Who said it? (optional)' : k === 'rule' ? 'Short name (optional)' : 'Title (optional)'),
    });
    const rules = window.TapanKit.notes(K, {
        space: 'growth', kinds: ALL_KINDS, defaultKind: 'rule', formTitle: 'Add a rule', numbered: true,
        bodyLabel: (k) => BODY_LABEL[k] || 'Text', bodyPlaceholder: (k) => PLACEHOLDER[k] || '', titleLabel: () => 'Short name (optional)',
    });
    const matches = (n, q) => !q || `${n.title} ${n.body} ${n.tags.join(' ')}`.toLowerCase().includes(q.toLowerCase());

    function todayCard(d) {
        const pool = d.notes.filter((n) => ['rule', 'quote', 'lesson'].includes(n.kind));
        const card = h('div', 'card wk-today');
        card.appendChild(h('div', 'mn-stat-l', 'For today'));
        if (!pool.length) {
            card.append(h('p', 'muted', 'Save a few rules, quotes or lessons and one of them will be shown here each day, so they actually get read.'));
            return card;
        }
        // The server picks today's one (stable all day). "Another" walks through the rest of the pool without changing that.
        let pick = d.pick && pool.find((n) => n.id === d.pick.id) || pool[0];
        if (S.ui.pickShift) pick = pool[(Math.max(0, pool.findIndex((n) => n.id === pick.id)) + S.ui.pickShift) % pool.length];
        const [first, ...rest] = pick.body.split('\n');
        card.append(h('p', 'wk-note-rule', first));
        if (rest.join('\n').trim()) card.appendChild(h('p', 'wk-note-body muted', rest.join('\n').trim()));
        card.appendChild(h('p', 'mn-emi-s', [pick.kind.charAt(0).toUpperCase() + pick.kind.slice(1), pick.title].filter(Boolean).join(' · ')));
        if (pool.length > 1) card.appendChild(btn('Another one', () => { S.ui.pickShift += 1; S.focusNext = 'gr:another'; paint(); }, 'link-btn', 'gr:another', 'Show another rule, quote or lesson'));
        return card;
    }

    function journalView(d) {
        const frag = h('div', 'mn-view');
        frag.appendChild(S.form === 'add-note:growth' ? notes.form(null) : btn('+ Add to journal', () => { delete S.drafts['add-note:growth']; openForm('add-note:growth', 'add-note:growth:body'); }, 'wide-btn', 'add-entry-btn'));
        const journal = d.notes.filter((n) => n.kind !== 'rule');
        const kinds = [['', `All (${journal.length})`], ...JOURNAL_KINDS.map(([v, l]) => [v, `${l} (${d.counts[v] || 0})`])];
        frag.appendChild(seg('Kind of entry', kinds, S.ui.kind, (v) => { S.ui.kind = v; paint(); }, 'gr:kind'));
        if (d.tags.length) {
            const row = h('div', 'wk-tagrow'); row.setAttribute('role', 'group'); row.setAttribute('aria-label', 'Filter by tag');
            d.tags.slice(0, 12).forEach((t) => {
                const b = btn(`#${t.tag}`, () => { S.ui.tag = S.ui.tag === t.tag ? '' : t.tag; S.focusNext = `gr:tag:${t.tag}`; paint(); }, 'mn-chip tag-btn', `gr:tag:${t.tag}`, `Show only #${t.tag}, ${t.count} entr${t.count === 1 ? 'y' : 'ies'}`);
                b.setAttribute('aria-pressed', String(S.ui.tag === t.tag));
                row.appendChild(b);
            });
            frag.appendChild(row);
        }
        const search = h('input'); search.type = 'search'; search.placeholder = 'Search your journal'; search.setAttribute('aria-label', 'Search your journal'); search.dataset.fk = 'gr:q'; search.value = S.ui.q; search.autocomplete = 'off';
        frag.appendChild(search);
        const listHost = h('div', 'wk-list');
        const fill = () => {
            const shown = journal.filter((n) => (!S.ui.kind || n.kind === S.ui.kind) && (!S.ui.tag || n.tags.includes(S.ui.tag)) && matches(n, S.ui.q));
            listHost.replaceChildren(...(shown.length ? shown.map((n) => notes.card(n)) : [h('p', 'muted', journal.length ? 'Nothing matches that.' : 'Your journal is empty. Add what you learned today, a lesson from an experience, a quote, or a thought. You can also tell me in chat: “save this lesson: …”.')]));
        };
        search.addEventListener('input', () => { S.ui.q = search.value; fill(); });
        fill();
        frag.appendChild(listHost);
        return frag;
    }

    function rulebookView(d) {
        const frag = h('div', 'mn-view');
        frag.appendChild(h('p', 'muted', 'Your own rules for living: things you decided once, so you do not have to decide again under pressure. Kept in the order you wrote them; pinned rules are shown first and chosen for “For today”.'));
        frag.appendChild(S.form === 'add-note:growth' ? rules.form(null, 'rule') : btn('+ Add a rule', () => { delete S.drafts['add-note:growth']; openForm('add-note:growth', 'add-note:growth:body'); }, 'wide-btn', 'add-rule-btn'));
        const list = d.notes.filter((n) => n.kind === 'rule');
        if (!list.length && S.form !== 'add-note:growth') frag.appendChild(h('p', 'muted', 'No rules yet. A good first one is something you keep having to relearn.'));
        const ol = h('div', 'wk-list');
        list.forEach((n, i) => ol.appendChild(rules.card(n, i)));
        frag.appendChild(ol);
        return frag;
    }

    function view() {
        const d = S.data, root = h('div', 'mn-view');
        const grid = h('div', 'mn-grid');
        grid.append(stat('Journal entries', String(d.total - (d.counts.rule || 0)), `${d.counts.learning || 0} learnings · ${d.counts.lesson || 0} lessons`), stat('Rules', String(d.counts.rule || 0), `${d.counts.quote || 0} quotes saved`));
        root.append(todayCard(d), grid);
        root.appendChild(seg('Growth sections', [['journal', 'Journal'], ['rules', 'Rulebook']], S.ui.view, (v) => { S.ui.view = v; S.form = null; S.ui.q = ''; paint(); }, 'gr:view'));
        root.appendChild(S.ui.view === 'rules' ? rulebookView(d) : journalView(d));
        return root;
    }

    window.TapanGrowth = { render(panel) { K.mount(panel); }, _state: S };
}());
