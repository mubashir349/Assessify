// ============================================================
// Institution Admin — shared shell (sidebar + topbar)
// Every admin page sets: <body data-page="key" data-title="..." data-sub="...">
// ============================================================

const A_NAV = [
  { key: 'dashboard',  icon: '🏠', label: 'Dashboard',        href: 'dashboard.html' },
  { key: 'fields',     icon: '🗂️', label: 'Fields & Departments', href: 'fields-subjects.html' },
  { key: 'generate',   icon: '✦',  label: 'Generate Questions', href: 'generate.html' },
  { key: 'drafts',     icon: '📝', label: 'Draft Review',      href: 'draft-review.html' },
  { key: 'bank',       icon: '📚', label: 'Question Bank',     href: 'question-bank.html' },
  { key: 'roster',     icon: '🧾', label: 'Candidate Roster',  href: 'roster.html' },
  { key: 'tests',      icon: '📝', label: 'Aptitude Tests',    href: 'create-test.html' },
  { key: 'monitor',    icon: '🖥️', label: 'Live Monitor',      href: 'monitor.html' },
  { key: 'reports',    icon: '📊', label: 'Reports',           href: 'reports.html' },
];

const A_NAV_SUPER = [
  { key: 'super', icon: '🛡️', label: 'Institutions', href: 'super-admin.html' },
];

function initAdminShell() {
  // Only build the admin shell on pages that actually authored admin content —
  // lets other pages (e.g. the candidate test screen) include this file just for aToast().
  if (!document.getElementById('a-content-template')) return;

  const page = document.body.dataset.page || '';
  const title = document.body.dataset.title || '';
  const sub = document.body.dataset.sub || '';

  const shellRoot = document.createElement('div');
  shellRoot.style.display = 'contents';
  shellRoot.innerHTML = `
    <aside class="a-sidebar">
      <div class="a-brand">
        <div class="mark">Σ</div>
        <div class="txt"><b>AssessAI</b><span>APTITUDE ADMIN</span></div>
      </div>
      <nav class="a-nav">
        ${(document.body.dataset.role === 'super' ? A_NAV_SUPER : A_NAV).map(n => `
          <a href="${n.href}" class="${n.key === page ? 'active' : ''}">
            <span class="ic">${n.icon}</span><span>${n.label}</span>
          </a>`).join('')}
      </nav>
      <div class="a-sidebar-foot">
        <div class="a-inst-chip">
          <div class="av"></div>
          <div class="meta"><b></b><span></span></div>
        </div>
        <a href="../institution-login.html" class="a-logout" id="a-logout">Log out</a>
      </div>
    </aside>
    <div class="a-main">
      <div class="a-topbar">
        <div><h1>${title}</h1><div class="sub" id="a-sub"${sub ? '' : ' hidden'}>${sub}</div></div>
        <div class="a-topbar-actions" id="a-topbar-actions"></div>
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
      const subEl = document.getElementById('a-sub'); subEl.textContent = user.institution.name; subEl.hidden = false;
    }
    const chip = document.querySelector('.a-inst-chip');
    if (chip) {
      const name = user.institution ? user.institution.name : 'AssessAI Platform';  // super admin has no institution
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

function aToast(msg, icon = '✓') {
  let el = document.querySelector('.a-toast');
  if (!el) {
    el = document.createElement('div');
    el.className = 'a-toast';
    document.body.appendChild(el);
  }
  el.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
  requestAnimationFrame(() => el.classList.add('show'));
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2600);
}

document.addEventListener('DOMContentLoaded', initAdminShell);
