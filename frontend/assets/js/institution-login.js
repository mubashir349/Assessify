// institution-login.html — sign in (institution or Super Admin)
// Registration lives on institution-signup.html.
// Demo Super Admin: superadmin@assessai.com (any password). Replace with backend auth.
const SUPER_ADMIN_EMAIL = 'superadmin@assessai.com';

document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);
  const show = msg => { $('authErr').style.display = msg ? 'block' : 'none'; $('authErr').textContent = msg || ''; };

  $('loginForm').addEventListener('submit', e => {
    e.preventDefault();
    const email = $('email').value.trim().toLowerCase(), pass = $('password').value.trim();
    if (!email || !pass) return show('Enter your email and password.');

    if (email === SUPER_ADMIN_EMAIL) { AA.set('role', 'super'); return (location.href = 'admin/super-admin.html'); }
    const su = AA.signups().find(s => s.email === email);
    if (su && su.status === 'pending') return show('Your institution is still awaiting Super Admin approval.');
    if (su && su.status !== 'approved') return show('This institution account is ' + su.status + '. Contact the platform administrator.');
    AA.set('role', 'institution'); if (su) AA.set('me', su);
    location.href = 'admin/dashboard.html';
  });
});
