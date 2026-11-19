// institution-login.html — sign in (institution admin or platform Super Admin)
// Registration lives on institution-signup.html. Role is decided by the server.

document.addEventListener('DOMContentLoaded', () => {
  const $ = id => document.getElementById(id);
  const err = $('authErr'), okBox = $('authOk'), btn = $('submitBtn');
  const showErr = msg => { okBox.style.display = 'none'; err.textContent = msg; err.style.display = msg ? 'block' : 'none'; };

  const dest = role => role === 'super_admin' ? 'admin/super-admin.html' : 'admin/dashboard.html';

  if (new URLSearchParams(location.search).has('registered')) {
    okBox.textContent = 'Registration submitted. You can sign in once the platform team approves your institution.';
    okBox.style.display = 'block';
  }

  // Already signed in? Skip the form.
  api('/auth/me').then(d => { location.replace(dest(d.user.role)); }).catch(() => {});

  $('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    showErr('');
    const email = $('email').value.trim(), password = $('password').value;
    if (!email || !password) return showErr('Enter your email and password.');

    setBtnLoading(btn, true);
    try {
      const { user } = await api('/auth/login', { method: 'POST', body: { email, password } });
      location.href = dest(user.role);
    } catch (ex) {
      // Phase 11: unpaid registration / ended subscription -> the payment page (the server sends a signed link)
      if ((ex.code === 'INSTITUTION_PAYMENT_REQUIRED' || ex.code === 'INSTITUTION_SUBSCRIPTION_EXPIRED') && ex.details?.payment_token) {
        okBox.textContent = ex.message + ' Opening the payment page…'; okBox.style.display = 'block';
        setTimeout(() => { location.href = 'institution-payment.html?token=' + encodeURIComponent(ex.details.payment_token); }, 1200);
        return;
      }
      showErr(ex.message);
      setBtnLoading(btn, false);
    }
  });
});
