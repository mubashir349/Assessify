// ============================================================
// Institution Admin — shared shell (sidebar + topbar)
// Every admin page sets: <body data-page="key" data-title="..." data-sub="...">
// Needs theme.js + icons.js (loaded in <head>) for the theme toggle and the icons.
// ============================================================

const A_NAV = [
  { group: 'Overview',    key: 'dashboard', icon: 'dashboard', label: 'Dashboard',            href: 'dashboard.html' },
  { group: 'Question content', key: 'fields',   icon: 'fields',    label: 'Fields & Departments', href: 'fields-subjects.html' },
  {             key: 'generate',  icon: 'sparkles',  label: 'Generate Questions',   href: 'generate.html' },
  {             key: 'drafts',    icon: 'drafts',    label: 'Draft Review',         href: 'draft-review.html' },
  {             key: 'bank',      icon: 'bank',      label: 'Question Bank',        href: 'question-bank.html' },
  { group: 'Assessments', key: 'roster',    icon: 'roster',    label: 'Candidate Roster',     href: 'roster.html' },
  {             key: 'tests',     icon: 'tests',     label: 'Aptitude Tests',       href: 'create-test.html' },
  {             key: 'monitor',   icon: 'monitor',   label: 'Live Monitor',         href: 'monitor.html' },
  {             key: 'reports',   icon: 'reports',   label: 'Reports',              href: 'reports.html' },
];

const A_NAV_SUPER = [
  { group: 'Platform', key: 'super', icon: 'shield', label: 'Institutions', href: 'super-admin.html' },
];

function navHTML(items, page) {
  return items.map(n => `${n.group ? `<div class="nav-group">${n.group}</div>` : ''}
    <a href="${n.href}" class="${n.key === page ? 'active' : ''}"${n.key === page ? ' aria-current="page"' : ''}>
      <span class="ic">${AIcon(n.icon)}</span><span>${n.label}</span>
    </a>`).join('');
}

function initAdminShell() {
  // Only build the admin shell on pages that actually authored admin content —
  // lets other pages (e.g. the candidate test screen) include this file just for aToast().
  if (!document.getElementById('a-content-template')) return;

  const page = document.body.dataset.page || '';
  const title = document.body.dataset.title || '';
  const sub = document.body.dataset.sub || '';
  const isSuper = document.body.dataset.role === 'super';

  const shellRoot = document.createElement('div');
  shellRoot.style.display = 'contents';
  shellRoot.innerHTML = `
    <aside class="a-sidebar" id="a-sidebar">
      <div class="a-brand">
        <div class="mark">Σ</div>
        <div class="txt"><b>Assessify</b><span>${isSuper ? 'PLATFORM ADMIN' : 'ADMIN CONSOLE'}</span></div>
      </div>
      <nav class="a-nav" aria-label="Main">${navHTML(isSuper ? A_NAV_SUPER : A_NAV, page)}</nav>
      <div class="a-sidebar-foot">
        <div class="a-inst-chip">
          <div class="av"></div>
          <div class="meta"><b></b><span></span></div>
        </div>
        <a href="../institution-login.html" class="a-logout" id="a-logout">${AIcon('logout')}<span>Log out</span></a>
      </div>
    </aside>
    <div class="a-scrim" id="a-scrim"></div>
    <div class="a-main">
      <div class="a-topbar">
        <div class="tb-left">
          <button type="button" class="icon-btn a-menu-btn" id="a-menu-btn" aria-label="Open menu" aria-controls="a-sidebar" aria-expanded="false">${AIcon('menu')}</button>
          <div><h1>${title}</h1><div class="sub" id="a-sub"${sub ? '' : ' hidden'}>${sub}</div></div>
        </div>
        <div class="a-topbar-right">
          <div class="a-topbar-actions" id="a-topbar-actions"></div>
          <button type="button" class="icon-btn" data-theme-toggle data-tip="Toggle theme" data-tip-pos="bottom"></button>
        </div>
      </div>
      <div class="a-content" id="a-content"></div>
    </div>
  `;

  const existingContent = document.getElementById('a-content-template');
  document.body.classList.add('admin-body');
  document.body.prepend(shellRoot);

  // Move any pre-authored page content (marked with #a-content-template) into the shell
  if (existingContent) {
    document.getElementById('a-content').innerHTML = existingContent.innerHTML;
    existingContent.remove();
  }
  document.getElementById('a-logout').addEventListener('click', async (e) => {
    e.preventDefault();
    try { await api('/auth/logout', { method: 'POST' }); } catch (err) { /* leave anyway */ }
    window.location.href = '../institution-login.html';
  });
  void guardSession();               // handles its own errors (redirects to the login page)

  const actionsTpl = document.getElementById('a-actions-template');
  if (actionsTpl) {
    document.getElementById('a-topbar-actions').innerHTML = actionsTpl.innerHTML;
    actionsTpl.remove();
  }

  // theme toggle + icons inside the markup that was just injected
  AIcons.hydrate(document.body);
  if (window.AssessifyTheme) window.AssessifyTheme.refresh();
  initMobileNav();
}

// Mobile / tablet: the sidebar is an off-canvas drawer
function initMobileNav() {
  const btn = document.getElementById('a-menu-btn'), scrim = document.getElementById('a-scrim');
  const set = open => {
    document.body.classList.toggle('nav-open', open);
    btn.setAttribute('aria-expanded', String(open));
    btn.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    btn.innerHTML = AIcon(open ? 'x' : 'menu');
  };
  btn.addEventListener('click', () => set(!document.body.classList.contains('nav-open')));
  scrim.addEventListener('click', () => set(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
  document.querySelectorAll('.a-nav a').forEach(a => a.addEventListener('click', () => set(false)));
  window.matchMedia('(min-width: 961px)').addEventListener('change', e => { if (e.matches) set(false); });
}

// Checks the login cookie with the server. No/expired session -> back to the login page.
// While checking, the page is hidden so protected screens never flash for logged-out visitors.
async function guardSession() {
  if (typeof api !== 'function') return;            // api.js not loaded on this page
  const wantSuper = document.body.dataset.role === 'super';
  document.body.style.visibility = 'hidden';
  try {
    const { user } = await api('/auth/me');
    if (wantSuper && user.role !== 'super_admin') return window.location.replace('dashboard.html');
    if (!wantSuper && user.role === 'super_admin') return window.location.replace('super-admin.html');
    window.A_USER = user;                              // pages can read the signed-in user
    if (user.role === 'institution_admin' && typeof AA !== 'undefined' && AA.syncDepts) AA.syncDepts().catch(() => {});
    if (document.body.dataset.subFrom === 'institution' && user.institution) {
      const subEl = document.getElementById('a-sub'); subEl.textContent = user.institution.display_name || user.institution.name; subEl.hidden = false;
    }
    const chip = document.querySelector('.a-inst-chip');
    if (chip) {
      const name = user.institution ? (user.institution.display_name || user.institution.name) : 'Assessify Platform';  // super admin has no institution
      chip.querySelector('.av').textContent = name.split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();
      chip.querySelector('.meta b').textContent = name;
      chip.querySelector('.meta span').textContent = user.full_name;
    }
  } catch (e) {
    if (e.status === 401 || e.status === 403) return window.location.replace('../institution-login.html');
    aToast(e.message, '⚠');                          // server unreachable: show the page, tell the user
  }
  document.body.style.visibility = '';
  document.dispatchEvent(new CustomEvent('admin:ready', { detail: window.A_USER }));
}

// Toast. `icon` keeps accepting the old glyphs (✓ ⚠ ✕ ✦): they are drawn as proper icons and set the colour.
const TOAST_KIND = { '✓': 'ok', '⚠': 'warn', '✕': 'err', '✦': 'ai' };
function aToast(msg, icon = '✓') {
  let el = document.querySelector('.a-toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'a-toast';
    el.setAttribute('role', 'status'); el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
  }
  const glyph = window.AIcons && AIcons.has(icon) ? AIcon(icon) : esc(icon);
  el.className = 'a-toast ' + (TOAST_KIND[icon] || '');
  el.innerHTML = `<span class="t-ico">${glyph}</span><span>${msg}</span>`;
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), icon === '⚠' || icon === '✕' ? 4200 : 2600);
}

document.addEventListener('DOMContentLoaded', initAdminShell);
