// ============================================================
// institution-login.html — page script
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('loginForm');
  if (!form) return;

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    // Demo: any non-empty credentials proceed to the dashboard.
    const email = document.getElementById('email').value.trim();
    const pass = document.getElementById('password').value.trim();
    const err = document.getElementById('authErr');
    if (email && pass) {
      window.location.href = 'admin/dashboard.html';
    } else {
      err.style.display = 'block';
    }
  });
});
