// ============================================================
// api.js — the ONLY place pages talk to the Flask backend.
// Usage:  const data = await api('/auth/login', { method: 'POST', body: { email, password } });
// Errors: throws ApiRequestError { code, message, status, details }
// ============================================================

// Where the API lives:
//  - pages served by Flask itself (python run.py / serve.py / the deployed site): the same address, /api/v1
//  - pages opened with VS Code Live Server (ports 5500-5599) or as a file: the backend on port 5000 of the same host
//    (use 127.0.0.1 for both so the login cookie is sent)
//  - anything else: set window.ASSESSIFY_API_URL before this script loads.
function defaultApiBase() {
  const port = Number(location.port);
  const devServer = location.protocol === 'file:' || (port >= 5500 && port < 5600);
  if (devServer) return `http://${location.hostname || '127.0.0.1'}:5000/api/v1`;
  return `${location.origin}/api/v1`;
}
const API_BASE = window.ASSESSIFY_API_URL || defaultApiBase();

class ApiRequestError extends Error {
  constructor(code, message, status, details) {
    super(message);
    this.code = code; this.status = status; this.details = details || null;
  }
}

/** Value of a readable (non-httpOnly) cookie, or ''. */
function readCookie(name) {
  const hit = document.cookie.split('; ').find(c => c.startsWith(name + '='));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : '';
}

async function api(path, { method = 'GET', body } = {}) {
  let res;
  // FormData (file uploads) is sent as-is: the browser sets the multipart Content-Type + boundary itself.
  const isForm = typeof FormData !== 'undefined' && body instanceof FormData;
  const headers = {};
  let payload;
  if (isForm) payload = body;
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body); }
  // CSRF double-submit: only present when the server turns it on (JWT_COOKIE_CSRF=true in production).
  const csrf = method === 'GET' ? '' : readCookie('csrf_access_token');
  if (csrf) headers['X-CSRF-TOKEN'] = csrf;
  try {
    res = await fetch(API_BASE + path, {
      method,
      credentials: 'include',                       // sends / receives the httpOnly login cookie
      headers,
      body: payload,
    });
  } catch (e) {
    throw new ApiRequestError('NETWORK_ERROR', 'Cannot reach the server. Is the backend running?', 0);
  }
  let json = null;
  try { json = await res.json(); } catch (e) { /* empty or non-JSON body */ }
  if (!res.ok) {
    const err = json?.error || {};
    throw new ApiRequestError(err.code || 'HTTP_' + res.status, err.message || 'Request failed (' + res.status + ').', res.status, err.details);
  }
  return json ? json.data : null;
}

/** Escape text before putting it into innerHTML. */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Dropdown / label lists (institution types, levels, modes...) come from the backend - nothing is hardcoded here. */
let _metaPromise = null;
function loadMeta() {
  if (!_metaPromise) _metaPromise = api('/meta').catch(e => { _metaPromise = null; throw e; });
  return _metaPromise;
}
/** Fills a <select> from a list of strings or {value,label} objects. Keeps an existing first placeholder <option value="">. */
function fillSelect(select, items, { keepFirst = false } = {}) {
  const first = keepFirst && select.options.length ? select.options[0].outerHTML : '';
  select.innerHTML = first + items.map(i => {
    const v = typeof i === 'string' ? i : i.value, l = typeof i === 'string' ? i : i.label;
    return `<option value="${esc(v)}">${esc(l)}</option>`;
  }).join('');
}

/** Shared error handling for admin pages: expired session -> login page, otherwise a toast with the server's message. */
function handleApiError(e, fallbackIcon = '⚠') {
  if (e?.status === 401) { window.location.replace('../institution-login.html'); return; }
  const field = e?.details && Object.values(e.details).find(v => typeof v === 'string');
  if (typeof aToast === 'function') aToast(esc(field || e?.message || 'Something went wrong.'), fallbackIcon);
}

// CSV downloads go through fetch so the login cookie is sent and an error shows as a toast, not a JSON page.
async function downloadFile(path, fallbackName) {
  try {
    const res = await fetch(API_BASE + path, { credentials: 'include' });
    if (!res.ok) {
      let msg = 'Download failed.';
      try { msg = (await res.json()).error.message; } catch (e) { /* not JSON */ }
      if (res.status === 401) return window.location.replace('../institution-login.html');
      return aToast(esc(msg), '⚠');
    }
    const name = (/filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '') || [])[1] || fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { aToast('Cannot reach the server. Is the backend running?', '⚠'); }
}
