// ============================================================
// institution-signup.html — page script
// Validates in the browser for quick feedback, then sends the registration to the API.
// The institution is saved as "pending" until the Super Admin approves it.
// Fields & departments are NOT collected here — added after approval, inside the dashboard.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('signupForm');
  if (!form) return;
  const err = document.getElementById('signupErr');
  const ok = document.getElementById('signupOk');
  const btn = form.querySelector('button[type="submit"]');
  const $ = id => document.getElementById(id);
  const v = id => $(id).value.trim();

  // server field name -> input id
  const FIELD_IDS = { institution_name: 'instName', institution_type: 'instType', city: 'instCity', website: 'instSite',
    admin_name: 'adminName', admin_email: 'adminEmail', admin_phone: 'adminPhone', admin_designation: 'adminRole', password: 'pw1' };

  function showErr(msg) { ok.style.display = 'none'; err.textContent = msg; err.style.display = 'block'; err.scrollIntoView({ block: 'nearest' }); }
  const mark = ids => ids.forEach(id => $(id) && $(id).classList.add('invalid'));

  // Institution types come from the backend
  loadMeta().then(m => { const sel = $('instType'); sel.insertAdjacentHTML('beforeend', m.institution_types.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join('')); })
    .catch(() => showErr('Cannot load institution types. Is the backend running?'));

  // Show / hide password
  document.querySelectorAll('.pw-toggle').forEach(b => b.addEventListener('click', () => {
    const i = $(b.dataset.for), show = i.type === 'password';
    i.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show';
  }));
  // Password strength meter
  $('pw1').addEventListener('input', e => {
    const x = e.target.value; let sc = 0;
    if (x.length >= 8) sc++; if (x.length >= 12) sc++; if (/[A-Z]/.test(x) && /[a-z]/.test(x)) sc++; if (/\d/.test(x) && /[^A-Za-z0-9]/.test(x)) sc++;
    $('pwMeter').className = 'pw-meter' + (x ? ' s' + Math.max(1, sc) : '');
    $('pwLabel').textContent = x ? ['', 'Weak', 'Fair', 'Good', 'Strong'][Math.max(1, sc)] : '';
  });
  // Clear the red outline as the user types
  form.querySelectorAll('.a-input, .a-select').forEach(el => el.addEventListener('input', () => el.classList.remove('invalid')));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.style.display = 'none';
    form.querySelectorAll('.invalid').forEach(el => el.classList.remove('invalid'));

    const req = ['instName', 'instType', 'instCity', 'adminName', 'adminEmail', 'adminPhone'].filter(id => !v(id));
    if (req.length) { mark(req); return showErr('Please fill in every required field.'); }
    if ($('pw1').value.length < 8) { mark(['pw1']); return showErr('Password should be at least 8 characters.'); }
    if ($('pw1').value !== $('pw2').value) { mark(['pw2']); return showErr('Passwords do not match.'); }
    if (!$('terms').checked) return showErr("Please confirm you're authorised and accept the Terms & Privacy Policy.");

    btn.disabled = true; const label = btn.textContent; btn.textContent = 'Submitting…';
    try {
      await api('/institutions/signup', { method: 'POST', body: {
        institution_name: v('instName'), institution_type: $('instType').value, city: v('instCity'), website: v('instSite'),
        admin_name: v('adminName'), admin_email: v('adminEmail'), admin_phone: v('adminPhone'), admin_designation: v('adminRole'),
        password: $('pw1').value,
      } });
      ok.style.display = 'block';
      setTimeout(() => { window.location.href = 'institution-login.html?registered=1'; }, 2200);
    } catch (ex) {
      // Server-side field errors: outline the inputs and show the first message
      const details = ex.details || {};
      mark(Object.keys(details).map(k => FIELD_IDS[k]).filter(Boolean));
      showErr(Object.values(details)[0] || ex.message);
      btn.disabled = false; btn.textContent = label;
    }
  });
});
