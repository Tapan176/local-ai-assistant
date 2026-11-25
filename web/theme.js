// Light / dark / automatic appearance. Loaded synchronously in <head> so the right theme is on the page before the first paint
// (no flash of the wrong colours). "auto" follows the device; an explicit choice is remembered on this device only.
(function () {
    'use strict';
    const KEY = 'tapan.theme';
    const root = document.documentElement;
    const query = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;
    const COLORS = { light: '#f3f5f9', dark: '#0c0f15' };          // the browser UI / status bar colour for each theme

    function saved() {
        try { const v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' ? v : 'auto'; } catch (e) { return 'auto'; }
    }
    function resolved(pref) { return pref === 'auto' ? (query && query.matches ? 'light' : 'dark') : pref; }
    function apply(pref) {
        if (pref === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', pref);
        const theme = resolved(pref);
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) meta.setAttribute('content', COLORS[theme]);
        document.dispatchEvent(new CustomEvent('tapan-theme', { detail: { pref, theme } }));
    }
    function set(pref) {
        const value = pref === 'light' || pref === 'dark' ? pref : 'auto';
        try { if (value === 'auto') localStorage.removeItem(KEY); else localStorage.setItem(KEY, value); } catch (e) { /* private mode: the choice just lasts for this visit */ }
        apply(value);
        return value;
    }

    apply(saved());
    if (query && query.addEventListener) query.addEventListener('change', () => { if (saved() === 'auto') apply('auto'); });

    window.TapanTheme = {
        get: saved,
        resolved: () => resolved(saved()),
        set,
        cycle() { const order = ['auto', 'light', 'dark']; return set(order[(order.indexOf(saved()) + 1) % order.length]); },
    };
}());
