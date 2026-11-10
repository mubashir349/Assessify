// ============================================================
// institution-signup.html — page script (Phase 10)
// 1. Find the institution + campus in the directory (or type it when it isn't listed).
// 2. Verify the admin's work email with a 6-digit code.
// 3. Submit. The institution is saved as "pending" until the Super Admin approves it.
// The server checks everything again; the checks here only give quick feedback.
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('signupForm');
  if (!form) return;
  const $ = id => document.getElementById(id);
  const v = id => $(id).value.trim();
  const err = $('signupErr'), ok = $('signupOk'), btn = $('submitBtn');

  // what was chosen in section 1
  //   mode: ''        nothing yet
  //         'campus'  a campus from the list          (picked = search item)
  //         'parent'  new campus of a listed institution (picked = search item of that institution)
  //         'manual'  not in the list
  let mode = '', picked = null;
  let emailToken = null, verifiedEmail = '', resendTimer = null;
  let FREE = new Set(), LIMITS = { resend_seconds: 60, proof_max_mb: 5 };

  // server field name -> input id
  const FIELD_IDS = { institution_name: 'instSearch', institution_type: 'instType', city: 'instCity', website: 'instSite',
    campus_name: 'instCampus', admin_name: 'adminName', admin_email: 'adminEmail', password: 'pw1', otp: 'otpCode', proof: 'proofFile' };

  function showErr(msg) { ok.style.display = 'none'; err.textContent = msg; err.style.display = 'block'; err.scrollIntoView({ block: 'nearest' }); }
  function hideErr() { err.style.display = 'none'; }
  const mark = ids => ids.forEach(id => $(id)?.classList.add('invalid'));
  const domainOf = email => (email.split('@')[1] || '').toLowerCase();
  const domains = item => (item?.email_domain || '').split(',').map(d => d.trim()).filter(Boolean);

  loadMeta().then(m => {
    $('instType').insertAdjacentHTML('beforeend', m.institution_types.map(t => `<option value="${esc(t)}">${esc(t)}</option>`).join(''));
    FREE = new Set(m.free_email_domains || []);
    LIMITS = m.signup_limits || LIMITS;
    $('proofHint').textContent = `(PDF, JPG or PNG, max ${LIMITS.proof_max_mb} MB)`;
  }).catch(() => showErr('Cannot reach the server. Is the backend running?'));

  // ---------------- 1. institution search ----------------
  const input = $('instSearch'), list = $('instList');
  let items = [], active = -1, searchTimer = null, lastQ = '';

  function closeList() { list.hidden = true; input.setAttribute('aria-expanded', 'false'); active = -1; }
  function renderList(q) {
    const rows = items.map((it, i) => `
      <li role="option" class="combo-item${it.registered ? ' taken' : ''}" data-i="${i}" aria-disabled="${it.registered}">
        <div class="ci-name">${esc(it.institution_name)}${it.short_name ? ` <span class="ci-short">${esc(it.short_name)}</span>` : ''}</div>
        <div class="ci-sub">${esc(it.campus_name)} · ${esc(it.city)} · ${esc(it.type)}${it.registered ? ' · <b>Already registered</b>' : ''}</div>
      </li>`).join('');
    const none = q.length >= 2 && !items.length ? `<li class="combo-empty">No match for “${esc(q)}”.</li>` : '';
    list.innerHTML = rows + none + `<li role="option" class="combo-item combo-manual" data-i="manual">
        <div class="ci-name">➕ My institution isn't in the list</div><div class="ci-sub">Type its details yourself. It's added to the list once approved.</div></li>`;
    list.hidden = false; input.setAttribute('aria-expanded', 'true');
  }
  async function search() {
    const q = input.value.trim();
    if (q === lastQ && !list.hidden) return;
    lastQ = q;
    if (q.length < 2) { items = []; renderList(q); return; }
    try { items = (await api('/directory/search?q=' + encodeURIComponent(q))).items; }
    catch (e) { items = []; }
    if (input.value.trim() === q) renderList(q);        // a slower old answer never replaces a newer one
  }
  input.addEventListener('input', () => { input.classList.remove('invalid'); clearTimeout(searchTimer); searchTimer = setTimeout(search, 220); });
  input.addEventListener('focus', () => { lastQ = null; search(); });
  input.addEventListener('keydown', e => {
    const opts = [...list.querySelectorAll('.combo-item')];
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); if (list.hidden) return search();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.classList.toggle('active', i === active)); opts[active]?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && !list.hidden && active >= 0) { e.preventDefault(); choose(opts[active].dataset.i); }
    else if (e.key === 'Escape') closeList();
  });
  list.addEventListener('mousedown', e => { const li = e.target.closest('.combo-item'); if (li) { e.preventDefault(); choose(li.dataset.i); } });
  document.addEventListener('click', e => { if (!e.target.closest('.combo')) closeList(); });

  function choose(i) {
    if (i === 'manual') return setMode('manual');
    const it = items[Number(i)];
    if (!it) return;
    if (it.registered) { showErr(`${it.label} is already registered on Assessify. Ask its admin to add you, or pick another campus.`); return; }
    hideErr(); picked = it; setMode('campus');
  }

  function setMode(m) {
    mode = m; closeList();
    const fromList = m === 'campus';
    $('searchField').hidden = m !== '';
    $('instPicked').hidden = !fromList;
    $('campusMissing').hidden = !fromList;
    $('manualBlock').hidden = !(m === 'manual' || m === 'parent');
    if (fromList) {
      $('ipName').textContent = picked.institution_name;
      $('ipSub').textContent = `${picked.campus_name} · ${picked.city}`;
      $('ipMeta').innerHTML = esc(picked.type) + (picked.website ? ` · <a href="${esc(picked.website)}" target="_blank" rel="noopener">${esc(picked.website.replace(/^https?:\/\/(www\.)?/, ''))}</a>` : '');
      $('acParent').textContent = picked.short_name || picked.institution_name;
    }
    const parent = m === 'parent';
    $('nameField').hidden = parent; $('typeField').hidden = parent; $('siteField').hidden = parent;
    $('campusReq').hidden = !parent; $('campusHint').hidden = parent;
    $('manualNote').innerHTML = parent
      ? `Adding a new campus of <b>${esc(picked.institution_name)}</b>. Type the campus name and its city.`
      : m === 'manual' ? 'Type your institution\'s details. After the platform team approves it, it appears in the list for others.' : '';
    if (m === 'manual') { $('instName').value = $('instName').value || input.value.trim(); }
    if (m === '') { picked = null; input.value = ''; setTimeout(() => input.focus(), 0); }
    updateEmailRules();
  }
  $('ipChange').addEventListener('click', () => setMode(''));
  $('backToSearch').addEventListener('click', () => setMode(''));
  $('addCampusLink').addEventListener('click', e => { e.preventDefault(); $('instCampus').value = ''; $('instCity').value = ''; setMode('parent'); });

  // ---------------- 2. work email + code ----------------
  function updateEmailRules() {
    const known = (mode === 'campus' || mode === 'parent') ? domains(picked) : [];
    $('emailHint').innerHTML = known.length
      ? `Use your official ${known.map(d => '<b>@' + esc(d) + '</b>').join(' or ')} email address.`
      : $('noOfficial').checked
        ? 'A personal email (Gmail, Yahoo, Outlook…) is allowed because you ticked “no official email”. Upload the proof below.'
        : "Use your institution's official email. Gmail, Yahoo, Outlook and other personal emails are not accepted.";
    $('noOfficialRow').hidden = known.length > 0;              // a listed domain means they do have official email
    if (known.length && $('noOfficial').checked) { $('noOfficial').checked = false; }
    $('proofBox').hidden = !$('noOfficial').checked;
  }
  $('noOfficial').addEventListener('change', updateEmailRules);

  function emailProblem(email) {
    if (!/^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(email)) return 'Enter a valid email address.';
    const d = domainOf(email), known = (mode === 'campus' || mode === 'parent') ? domains(picked) : [];
    if (FREE.has(d) && !$('noOfficial').checked) return `@${d} is a personal email. Use your work email, or tick “We don't have an official email”.`;
    if (known.length && !known.some(k => d === k || d.endsWith('.' + k))) return `Use your ${known.map(k => '@' + k).join(' or ')} email address.`;
    return '';
  }

  function setVerified(on) {
    $('verifiedTag').hidden = !on;
    $('adminEmail').classList.toggle('verified', on);
    $('sendCode').textContent = on ? 'Change' : 'Send code';
    $('adminEmail').readOnly = on;
    if (on) $('otpBox').hidden = true;
    btn.disabled = !on; $('submitNote').hidden = on;
  }
  setVerified(false);

  function startResendTimer(seconds) {
    clearInterval(resendTimer);
    let left = seconds; $('resendCode').disabled = true;
    const tick = () => {
      $('resendTimer').textContent = left > 0 ? `in ${left}s` : '';
      if (left-- <= 0) { clearInterval(resendTimer); $('resendCode').disabled = false; }
    };
    tick(); resendTimer = setInterval(tick, 1000);
  }

  async function sendCode() {
    hideErr();
    if (emailToken) {                                    // "Change": unlock the email and start over
      emailToken = null; verifiedEmail = ''; setVerified(false); $('adminEmail').focus(); return;
    }
    const email = v('adminEmail').toLowerCase();
    const problem = emailProblem(email);
    if (problem) { mark(['adminEmail']); return showErr(problem); }
    const b = $('sendCode'); b.disabled = true; b.textContent = 'Sending…';
    try {
      const r = await api('/auth/otp/send', { method: 'POST', body: { email } });
      $('otpBox').hidden = false;
      $('otpMsg').innerHTML = `We sent a 6-digit code to <b>${esc(r.sent_to)}</b>. It expires in ${Math.round(r.expires_in / 60)} minutes.` +
        (r.delivery === 'logged' ? '<br><span class="dev-note">Local mode (MAIL_BACKEND=console): the code is printed in the backend terminal.</span>' : '');
      $('otpCode').value = ''; $('otpCode').focus();
      startResendTimer(r.resend_after || LIMITS.resend_seconds);
    } catch (ex) {
      if (ex.details?.retry_after && ex.code === 'OTP_TOO_SOON') { $('otpBox').hidden = false; startResendTimer(ex.details.retry_after); }
      mark(['adminEmail']); showErr(ex.details?.admin_email || ex.message);
    } finally { b.disabled = false; if (!emailToken) b.textContent = 'Send code'; }
  }
  $('sendCode').addEventListener('click', sendCode);
  $('resendCode').addEventListener('click', sendCode);
  $('adminEmail').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendCode(); } });

  async function verifyCode() {
    hideErr();
    const code = v('otpCode');
    if (!/^\d{6}$/.test(code)) { mark(['otpCode']); return showErr('Enter the 6-digit code from the email.'); }
    const b = $('verifyCode'); b.disabled = true; b.textContent = 'Checking…';
    try {
      const r = await api('/auth/otp/verify', { method: 'POST', body: { email: v('adminEmail').toLowerCase(), code } });
      emailToken = r.email_token; verifiedEmail = r.email; setVerified(true);
    } catch (ex) { mark(['otpCode']); showErr(ex.message); }
    finally { b.disabled = false; b.textContent = 'Verify'; }
  }
  $('verifyCode').addEventListener('click', verifyCode);
  $('otpCode').addEventListener('input', e => { e.target.value = e.target.value.replace(/\D/g, '').slice(0, 6); if (e.target.value.length === 6) verifyCode(); });
  $('otpCode').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); verifyCode(); } });

  // ---------------- 3. password ----------------
  document.querySelectorAll('.pw-toggle').forEach(b => b.addEventListener('click', () => {
    const i = $(b.dataset.for), show = i.type === 'password';
    i.type = show ? 'text' : 'password'; b.textContent = show ? 'Hide' : 'Show';
  }));
  $('pw1').addEventListener('input', e => {
    const x = e.target.value; let sc = 0;
    if (x.length >= 8) { sc++; }
    if (x.length >= 12) { sc++; }
    if (/[A-Z]/.test(x) && /[a-z]/.test(x)) { sc++; }
    if (/\d/.test(x) && /[^A-Za-z0-9]/.test(x)) { sc++; }
    $('pwMeter').className = 'pw-meter' + (x ? ' s' + Math.max(1, sc) : '');
    $('pwLabel').textContent = x ? ['', 'Weak', 'Fair', 'Good', 'Strong'][Math.max(1, sc)] : '';
  });
  form.querySelectorAll('.a-input, .a-select').forEach(el => el.addEventListener('input', () => el.classList.remove('invalid')));

  // ---------------- submit ----------------
  function institutionFields() {
    if (mode === 'campus') return { directory_campus_id: picked.campus_id };
    if (mode === 'parent') return { directory_institution_id: picked.institution_id, campus_name: v('instCampus'), city: v('instCity') };
    return { institution_name: v('instName'), institution_type: $('instType').value, campus_name: v('instCampus'),
             city: v('instCity'), website: v('instSite') };
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideErr();
    form.querySelectorAll('.invalid').forEach(el => el.classList.remove('invalid'));

    if (!mode) { mark(['instSearch']); return showErr('Search for your institution and pick your campus, or choose “My institution isn\'t in the list”.'); }
    const need = mode === 'parent' ? ['instCampus', 'instCity'] : mode === 'manual' ? ['instName', 'instType', 'instCity'] : [];
    const missing = need.concat(['adminName']).filter(id => !v(id) && !$(id).value);
    if (missing.length) { mark(missing); return showErr('Please fill in every required field.'); }
    if (!emailToken || verifiedEmail !== v('adminEmail').toLowerCase()) { mark(['adminEmail']); return showErr('Verify your work email with the code first.'); }
    const proof = $('proofFile').files[0];
    if ($('noOfficial').checked && !proof) { mark(['proofFile']); return showErr('Upload a proof document (authorisation letter or registration certificate).'); }
    if (proof && proof.size > LIMITS.proof_max_mb * 1024 * 1024) { mark(['proofFile']); return showErr(`The proof file must be at most ${LIMITS.proof_max_mb} MB.`); }
    if ($('pw1').value.length < 8) { mark(['pw1']); return showErr('Password should be at least 8 characters.'); }
    if ($('pw1').value !== $('pw2').value) { mark(['pw2']); return showErr('Passwords do not match.'); }
    if (!$('terms').checked) return showErr("Please confirm you're authorised and accept the Terms & Privacy Policy.");

    const fields = { ...institutionFields(), admin_name: v('adminName'), admin_email: verifiedEmail, email_token: emailToken,
                     password: $('pw1').value, no_official_email: $('noOfficial').checked };
    let body = fields;
    if ($('noOfficial').checked) {                       // a file goes as multipart form data
      body = new FormData();
      Object.entries(fields).forEach(([k, val]) => { if (val !== undefined && val !== null) body.append(k, String(val)); });
      body.append('proof', proof);
    }
    btn.disabled = true; const label = btn.textContent; btn.textContent = 'Submitting…';
    try {
      await api('/institutions/signup', { method: 'POST', body });
      ok.style.display = 'block';
      setTimeout(() => { window.location.href = 'institution-login.html?registered=1'; }, 2200);
    } catch (ex) {
      const details = ex.details || {};
      const ids = { ...FIELD_IDS, institution_name: mode === 'manual' ? 'instName' : 'instSearch' };
      mark(Object.keys(details).map(k => ids[k]).filter(Boolean));
      if (ex.code === 'EMAIL_NOT_VERIFIED') { emailToken = null; setVerified(false); }
      showErr(Object.values(details)[0] || ex.message);
      btn.disabled = !emailToken; btn.textContent = label;
    }
  });
});
