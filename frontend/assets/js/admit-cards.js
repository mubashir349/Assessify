// roster.html, Phase 11: admit cards by email (GET/POST /admit-cards...). Loaded after roster.js; uses TEST from there.
// The Send button is disabled (with the reason shown on hover and under it) when the test has ended, the roster is
// empty, nobody has an email, or email is not set up. Problems are listed by name with the reason.
let ADMIT = null, admitBusy = false;
window.ADMIT_PEOPLE = {};

function candidateLoginUrl() { return new URL('../candidate-login.html', location.href).href; }

const STATE_TEXT = { failed: 'Not sent', bounced: 'Bounced back', changed: 'Email changed after sending' };

async function loadAdmit() {
  if (!TEST) return;
  let d;
  try { d = await api('/admit-cards?test_id=' + encodeURIComponent(TEST.id)); }
  catch (e) { if (e.status === 401) return handleApiError(e); $('admitBox').hidden = true; return; }
  if (!TEST || d.test.id !== TEST.id) return;            // another test was picked meanwhile
  ADMIT = d;
  window.ADMIT_PEOPLE = {};
  [...d.no_email, ...d.problems, ...d.changed].forEach(p => { window.ADMIT_PEOPLE[p.id] = p.candidate; });
  renderAdmit();
}

function renderAdmit() {
  const d = ADMIT, c = d.counts;
  $('admitBox').hidden = false;
  const waiting = c.not_sent + c.failed + c.bounced + c.changed;
  $('admitStats').innerHTML = [
    ['Delivered', c.sent, 'var(--success-text)'],
    ['Waiting to be sent', c.not_sent + c.changed, 'var(--text)'],
    ['Not delivered', c.failed + c.bounced, 'var(--danger-text)'],
    ['No email on roster', c.no_email, 'var(--warn-text)'],
  ].map(([lbl, n, col]) => `<div class="admit-stat"><span class="num" style="color:${col};">${n}</span><span class="lbl">${lbl}</span></div>`).join('');

  // Send button: disabled with a reason (tooltip on hover + the same text under it)
  const btn = $('admitSendBtn'), wrap = $('admitSendWrap'), why = $('admitBlocked');
  btn.disabled = !d.can_send || admitBusy;
  btn.textContent = waiting && c.sent ? `Send to remaining (${waiting})` : 'Send admit cards';
  if (!d.can_send && d.blocked_reason) {
    wrap.dataset.tip = d.blocked_reason; wrap.title = d.blocked_reason;
    why.textContent = d.blocked_reason; why.hidden = false;
  } else {
    delete wrap.dataset.tip; wrap.removeAttribute('title'); why.hidden = true;
  }
  $('admitResendBtn').hidden = !d.can_resend;
  $('admitBounceBtn').hidden = !(d.bounce_check && c.sent + c.bounced > 0);
  const first = window.ROWS && window.ROWS[0];
  $('admitPreview').hidden = !first;
  if (first) $('admitPreview').href = `${API_BASE}/admit-cards/${first.id}.pdf?login_url=${encodeURIComponent(candidateLoginUrl())}`;
  $('admitNote').textContent = d.mail_note || '';

  // Not delivered: name + email + reason, with a quick way to fix the email
  const problems = [...d.problems, ...d.changed];
  $('admitProblems').innerHTML = problems.length ? `
    <div class="admit-list danger">
      <h3>Admit cards not delivered (${problems.length})</h3>
      <p class="muted">Fix the email address with “Edit email”, then press “Send to remaining”.</p>
      <div class="a-table-wrap"><table class="a-table"><thead><tr><th>Name</th><th>Roll No.</th><th>Email used</th><th>What went wrong</th><th></th></tr></thead><tbody>
      ${problems.map(p => `<tr><td class="name">${esc(p.full_name)}</td><td class="mono">${esc(p.roll_number || '—')}</td>
        <td>${esc(p.sent_to || p.email || '')}</td>
        <td><span class="admit-tag ${p.state}">${esc(STATE_TEXT[p.state] || p.state)}</span> ${esc(p.state === 'changed' ? `Sent to ${p.sent_to}; the email is now ${p.email}.` : (p.error || ''))}</td>
        <td><button class="a-btn a-btn-ghost a-btn-sm" onclick="openCandModal(${p.id})">Edit email</button></td></tr>`).join('')}
      </tbody></table></div>
    </div>` : '';

  // No email: ask the institution to collect them
  $('admitNoEmail').innerHTML = d.no_email.length ? `
    <div class="admit-list warn">
      <h3>${d.no_email.length === d.total ? 'Nobody' : `${d.no_email.length} candidate${d.no_email.length === 1 ? '' : 's'}`} on this roster ${d.no_email.length === 1 ? 'has' : 'have'} no email address</h3>
      <p class="muted">These candidates will <b>not</b> get an admit card by email. Please collect their email addresses and add them with “Add email”
        (or re-import the list with an email column). Until then, give them a printed slip.</p>
      <div class="admit-chips">${d.no_email.map(p => `<span class="admit-person">${esc(p.full_name)}${p.roll_number ? ` <span class="mono muted">${esc(p.roll_number)}</span>` : ''}
        <button class="a-btn a-btn-ghost a-btn-sm" onclick="openCandModal(${p.id})">Add email</button></span>`).join('')}</div>
    </div>` : '';
  if (window.AIcons) window.AIcons.hydrate($('admitBox'));
}

async function sendAdmitCards(resend) {
  if (admitBusy || !ADMIT) return;
  const n = resend ? ADMIT.with_email : ADMIT.counts.not_sent + ADMIT.counts.failed + ADMIT.counts.bounced + ADMIT.counts.changed;
  if (resend && !confirm(`Send the admit card again to all ${n} candidates with an email?`)) return;
  admitBusy = true; renderAdmit();
  $('admitSendBtn').textContent = `Sending ${n} admit card${n === 1 ? '' : 's'}…`;
  try {
    const r = await api('/admit-cards/send', { method: 'POST', body: { test_id: TEST.id, resend: !!resend, login_url: candidateLoginUrl() } });
    const parts = [`${r.sent.length} sent`];
    if (r.failed.length) parts.push(`${r.failed.length} not delivered`);
    if (r.no_email.length) parts.push(`${r.no_email.length} without email`);
    aToast(esc('Admit cards: ' + parts.join(' · ') + '.'), r.failed.length ? '⚠' : '✓');
    if (r.stopped) aToast(esc('Stopped: ' + r.stopped), '⚠');
    ADMIT = r.status;
    window.ADMIT_PEOPLE = {};
    [...ADMIT.no_email, ...ADMIT.problems, ...ADMIT.changed].forEach(p => { window.ADMIT_PEOPLE[p.id] = p.candidate; });
  } catch (e) {
    handleApiError(e);
    await loadAdmit();
  } finally {
    admitBusy = false; if (ADMIT) renderAdmit();
  }
}

async function checkBounces() {
  if (admitBusy) return;
  admitBusy = true; $('admitBounceBtn').disabled = true; $('admitBounceBtn').textContent = 'Checking the mailbox…';
  try {
    const r = await api('/admit-cards/check-bounces', { method: 'POST', body: { test_id: TEST.id } });
    aToast(esc(r.bounced.length ? `${r.bounced.length} email${r.bounced.length === 1 ? '' : 's'} bounced: ${r.bounced.map(b => b.full_name).join(', ')}.`
      : 'No bounced emails found. Bounces usually arrive within a few minutes of sending.'), r.bounced.length ? '⚠' : '✓');
    ADMIT = r.status;
    [...ADMIT.problems].forEach(p => { window.ADMIT_PEOPLE[p.id] = p.candidate; });
  } catch (e) { handleApiError(e); }
  finally {
    admitBusy = false; $('admitBounceBtn').disabled = false; $('admitBounceBtn').textContent = 'Check for bounced emails';
    if (ADMIT) renderAdmit();
  }
}
