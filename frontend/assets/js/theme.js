// ============================================================
// theme.js — dark / light mode for every Assessify page.
// Load it in <head> (before the page paints) so the saved theme is applied with no flash.
//   - first visit: follows the operating system (prefers-color-scheme)
//   - after the user clicks the toggle: the choice is saved in localStorage ("assessify-theme")
//   - any element with [data-theme-toggle] becomes a toggle button (sun in dark mode, moon in light mode)
// ============================================================
(function () {
  const KEY = 'assessify-theme';
  const root = document.documentElement;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

  function stored() { try { const v = localStorage.getItem(KEY); return v === 'light' || v === 'dark' ? v : null; } catch (e) { return null; } }
  function system() { return media && media.matches ? 'light' : 'dark'; }
  function current() { return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark'; }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    root.style.colorScheme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', theme === 'light' ? '#F7F8FC' : '#0B1020');
    document.querySelectorAll('[data-theme-toggle]').forEach(syncButton);
  }

  function syncButton(btn) {
    const light = current() === 'light';
    btn.setAttribute('aria-label', light ? 'Switch to dark mode' : 'Switch to light mode');
    btn.setAttribute('title', light ? 'Switch to dark mode' : 'Switch to light mode');
    btn.setAttribute('aria-pressed', String(light));
    if (window.AIcon) btn.innerHTML = AIcon(light ? 'moon' : 'sun');      // shows the mode you would switch to
    else btn.textContent = light ? 'Dark' : 'Light';
  }

  function set(theme, remember) {
    root.classList.add('theme-anim');                                      // smooth cross-fade, only while switching
    apply(theme);
    if (remember) { try { localStorage.setItem(KEY, theme); } catch (e) { /* private mode: still works for this page */ } }
    clearTimeout(set._t);
    set._t = setTimeout(() => root.classList.remove('theme-anim'), 350);
  }

  apply(stored() || system());                                             // runs immediately, before first paint

  window.AssessifyTheme = {
    get: current,
    set: t => set(t, true),
    toggle: () => set(current() === 'light' ? 'dark' : 'light', true),
    refresh: () => document.querySelectorAll('[data-theme-toggle]').forEach(syncButton),   // after injecting new toggle buttons
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-theme-toggle]').forEach(syncButton);
  });
  document.addEventListener('click', e => {
    const btn = e.target.closest && e.target.closest('[data-theme-toggle]');
    if (btn) { e.preventDefault(); window.AssessifyTheme.toggle(); }
  });
  // follow the OS only while the user has not picked a theme themselves
  if (media && media.addEventListener) media.addEventListener('change', () => { if (!stored()) set(system(), false); });
  // keep other open tabs in step
  window.addEventListener('storage', e => { if (e.key === KEY && (e.newValue === 'light' || e.newValue === 'dark')) set(e.newValue, false); });
})();
