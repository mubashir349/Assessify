// ============================================================
// institution-signup.html — page script
// Handles the "Fields & Departments" chip input and demo
// client-side validation for the registration form.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('signupForm');
  if (!form) return;

  const deptBox = document.getElementById('deptBox');
  const deptEntry = document.getElementById('deptEntry');
  const deptCount = document.getElementById('deptCount');
  const deptSuggest = document.getElementById('deptSuggest');
  const err = document.getElementById('signupErr');
  const ok = document.getElementById('signupOk');

  let departments = [];

  function renderCount() {
    deptCount.textContent = departments.length;
  }

  function addDept(name) {
    const clean = name.trim();
    if (!clean) return;
    const exists = departments.some(d => d.toLowerCase() === clean.toLowerCase());
    if (exists) { deptEntry.value = ''; return; }

    departments.push(clean);

    const chip = document.createElement('span');
    chip.className = 'chip-tag';
    chip.dataset.dept = clean;
    chip.innerHTML = `${clean} <button type="button" title="Remove">✕</button>`;
    chip.querySelector('button').addEventListener('click', () => {
      departments = departments.filter(d => d !== clean);
      chip.remove();
      renderCount();
    });
    deptBox.insertBefore(chip, deptEntry);

    // A department only appears once as a quick-suggest option.
    const suggestBtn = deptSuggest.querySelector(`button[data-dept="${CSS.escape(clean)}"]`);
    if (suggestBtn) suggestBtn.disabled = true;

    deptEntry.value = '';
    renderCount();
  }

  deptEntry.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault();
      addDept(deptEntry.value);
    }
  });
  deptEntry.addEventListener('blur', () => addDept(deptEntry.value));

  deptSuggest.querySelectorAll('button[data-dept]').forEach(btn => {
    btn.addEventListener('click', () => addDept(btn.dataset.dept));
  });

  function showErr(msg) {
    ok.style.display = 'none';
    err.textContent = msg;
    err.style.display = 'block';
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    err.style.display = 'none';

    const instName = document.getElementById('instName').value.trim();
    const instType = document.getElementById('instType').value;
    const instCity = document.getElementById('instCity').value.trim();
    const adminName = document.getElementById('adminName').value.trim();
    const adminEmail = document.getElementById('adminEmail').value.trim();
    const adminPhone = document.getElementById('adminPhone').value.trim();
    const pw1 = document.getElementById('pw1').value;
    const pw2 = document.getElementById('pw2').value;
    const terms = document.getElementById('terms').checked;

    if (!instName || !instType || !instCity || !adminName || !adminEmail || !adminPhone) {
      showErr('Please fill in every required field.');
      return;
    }
    if (departments.length === 0) {
      showErr('Add at least one field/department you\'ll be testing candidates in.');
      return;
    }
    if (pw1.length < 6) {
      showErr('Password should be at least 6 characters.');
      return;
    }
    if (pw1 !== pw2) {
      showErr('Passwords do not match.');
      return;
    }
    if (!terms) {
      showErr('Please confirm you\'re authorised and accept the Terms & Privacy Policy.');
      return;
    }

    // Demo only: a real backend would create the institution + admin
    // account here, then send a verification email before login.
    ok.style.display = 'block';
    form.querySelector('button[type="submit"]').disabled = true;
    setTimeout(() => { window.location.href = 'institution-login.html'; }, 1400);
  });
});