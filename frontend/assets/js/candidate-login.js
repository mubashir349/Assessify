// ============================================================
// candidate-login.html — page script
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  if (!form) return;

  let attempts = 0;
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const code = document.getElementById('code').value.trim();
    const dob = document.getElementById('dob').value.trim();
    const err = document.getElementById('authErr');
    if (code && dob) {
      window.location.href = 'candidate-start.html';
    } else {
      attempts++;
      err.textContent = attempts >= 3
        ? 'Too many failed attempts. Please wait a moment before trying again, or ask your proctor for help.'
        : 'Access code or date of birth is incorrect. Please check your test slip and try again.';
      err.style.display = 'block';
    }
  });
});
