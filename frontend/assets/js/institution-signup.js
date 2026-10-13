// ============================================================
// institution-signup.html — page script
// Demo client-side validation. Registration is saved as "pending"
// so the Super Admin can approve it. Fields & departments are NOT
// collected here — the institution adds them after approval.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('signupForm');
  if (!form) return;
  const err = document.getElementById('signupErr');
  const ok = document.getElementById('signupOk');
  const v = id => document.getElementById(id).value.trim();

  function showErr(msg) {
    ok.style.display = 'none';
    err.textContent = msg;
    err.style.display = 'block';
  }

  // Show / hide password
  document.querySelectorAll('.pw-toggle').forEach(b => b.addEventListener('click', () => {
    const i = document.getElementById(b.dataset.for), show = i.type === 'password';
    i.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show';
  }));
  // Password strength meter
  document.getElementById('pw1').addEventListener('input', e => {
    const x = e.target.value; let sc = 0;
    if (x.length >= 6) sc++; if (x.length >= 10) sc++; if (/[A-Z]/.test(x) && /[a-z]/.test(x)) sc++; if (/\d/.test(x) && /[^A-Za-z0-9]/.test(x)) sc++;
    document.getElementById('pwMeter').className = 'pw-meter' + (x ? ' s' + Math.max(1, sc) : '');
    document.getElementById('pwLabel').textContent = x ? ['', 'Weak', 'Fair', 'Good', 'Strong'][Math.max(1, sc)] : '';
  });
  // Clear red outline as the user types
  form.querySelectorAll('.a-input, .a-select').forEach(el => el.addEventListener('input', () => el.classList.remove('invalid')));
  const mark = ids => ids.forEach(id => document.getElementById(id).classList.add('invalid'));

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    err.style.display = 'none';

    const email = v('adminEmail').toLowerCase();
    const req = ['instName', 'instType', 'instCity', 'adminName', 'adminEmail', 'adminPhone'].filter(id => !v(id));
    if (req.length) { mark(req); return showErr('Please fill in every required field.'); }
    if (document.getElementById('pw1').value.length < 6) { mark(['pw1']); return showErr('Password should be at least 6 characters.'); }
    if (document.getElementById('pw1').value !== document.getElementById('pw2').value) { mark(['pw2']); return showErr('Passwords do not match.'); }
    if (!document.getElementById('terms').checked) return showErr('Please confirm you\'re authorised and accept the Terms & Privacy Policy.');

    const signups = AA.signups();
    if (signups.some(s => s.email === email)) return showErr('This email is already registered.');

    // Demo only: a real backend would create the institution + admin account
    // (hashing the password) and send a verification email.
    signups.push({ id: AA.uid(), inst: v('instName'), type: v('instType'), city: v('instCity'), site: v('instSite'),
      admin: v('adminName'), email, phone: v('adminPhone'), role: v('adminRole'), status: 'pending', date: new Date().toISOString().slice(0, 10) });
    AA.saveSignups(signups);

    ok.style.display = 'block';
    form.querySelector('button[type="submit"]').disabled = true;
    setTimeout(() => { window.location.href = 'institution-login.html'; }, 2200);
  });
});
