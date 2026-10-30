// ============================================================
// candidate-login.html — access code + date of birth, checked by the server (POST /candidate/login, Phase 5).
// The server sets the candidate's own httpOnly cookie; nothing about the candidate is kept in the browser.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  if (!form) return;
  const err = document.getElementById('authErr'), btn = document.getElementById('loginBtn');
  const show = msg => { err.textContent = msg; err.style.display = 'block'; };

  // Already signed in (e.g. came back with the Back button) -> go straight on
  api('/candidate/me').then(() => window.location.replace('candidate-start.html')).catch(() => {});

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.style.display = 'none';
    const access_code = document.getElementById('code').value.trim();
    const date_of_birth = document.getElementById('dob').value;
    if (!access_code || !date_of_birth) return show('Enter both your access code and your date of birth.');
    btn.disabled = true;
    try {
      await api('/candidate/login', { method: 'POST', body: { access_code, date_of_birth } });
      window.location.href = 'candidate-start.html';
    } catch (ex) {
      const field = ex.code === 'VALIDATION_ERROR' && ex.details && Object.values(ex.details)[0];
      show(field || ex.message);
      btn.disabled = false;
    }
  });
});
