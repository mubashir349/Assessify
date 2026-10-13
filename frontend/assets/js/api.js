// ============================================================
// api.js — the ONLY place pages talk to the Flask backend.
// Usage:  const data = await api('/auth/login', { method: 'POST', body: { email, password } });
// Errors: throws ApiRequestError { code, message, status, details }
// ============================================================

// Frontend and API must share a host (both 127.0.0.1 or both localhost) so the login cookie is sent.
// Override for deployment by setting window.ASSESSIFY_API_URL before this script loads.
const API_BASE = window.ASSESSIFY_API_URL || `http://${location.hostname || '127.0.0.1'}:5000/api/v1`;

class ApiRequestError extends Error {
  constructor(code, message, status, details) {
    super(message);
    this.code = code; this.status = status; this.details = details || null;
  }
}

async function api(path, { method = 'GET', body } = {}) {
  let res;
  try {
    res = await fetch(API_BASE + path, {
      method,
      credentials: 'include',                       // sends / receives the httpOnly login cookie
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
