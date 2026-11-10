// ============================================================
// candidate-login.html — access code + date of birth or PIN, checked by the server (POST /candidate/login, Phase 5).
// Phase 9: the "Date of birth | PIN" switch. The candidate picks what their slip says; the server never tells.
// The server sets the candidate's own httpOnly cookie; nothing about the candidate is kept in the browser.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  if (!form) return;
  const err = document.getElementById('authErr'), btn = document.getElementById('loginBtn');
  const show = msg => { err.textContent = msg; err.style.display = 'block'; };
  const factor = () => form.querySelector('input[name="factor"]:checked').value;
  form.querySelectorAll('input[name="factor"]').forEach(r => r.addEventListener('change', () => {
    document.getElementById('dobField').hidden = factor() !== 'dob';
    document.getElementById('pinField').hidden = factor() !== 'pin';
    err.style.display = 'none';
  }));
  document.getElementById('pin').addEventListener('input', e => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6); });

  // Already signed in (e.g. came back with the Back button) -> go straight on
  api('/candidate/me').then(() => window.location.replace('candidate-start.html')).catch(() => {});

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    err.style.display = 'none';
    const access_code = document.getElementById('code').value.trim();
    const usePin = factor() === 'pin';
    const second = usePin ? document.getElementById('pin').value.trim() : document.getElementById('dob').value;
    if (!access_code || !second) return show(usePin ? 'Enter your access code and the 6-digit PIN from your slip.'
                                                    : 'Enter both your access code and your date of birth.');
    if (usePin && second.length !== 6) return show('The PIN has 6 digits.');
    btn.disabled = true;
    try {
      const body = usePin ? { access_code, pin: second } : { access_code, date_of_birth: second };
      await api('/candidate/login', { method: 'POST', body });
      window.location.href = 'candidate-start.html';
    } catch (ex) {
      const field = ex.code === 'VALIDATION_ERROR' && ex.details && Object.values(ex.details)[0];
      show(field || ex.message);
      btn.disabled = false;
    }
  });
});
