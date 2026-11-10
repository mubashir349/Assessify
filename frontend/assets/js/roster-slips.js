// roster-slips.html — one printable slip per candidate of a test (Phase 9). Data from GET /roster/slips?test_id=.
// Shows the access code and, for candidates without a date of birth, their PIN. Never the date of birth.
const $ = id => document.getElementById(id);
let DATA = null;

function when(sc) {
  if (!sc) return '';
  const f = iso => new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  return `${f(sc.starts_at)} – ${f(sc.ends_at)}`;
}

function slipHtml(s, t, loginUrl) {
  const second = s.login_with === 'pin'
    ? `<div class="factor"><span>PIN</span><b class="code">${esc(s.pin)}</b></div>`
    : '<div class="factor"><span>Second step</span><b>Your date of birth</b></div>';
  return `<article class="slip">
    <div class="slip-head"><b>${esc(t.institution)}</b><span>${esc(t.name)}</span></div>
    <div class="who"><b>${esc(s.full_name)}</b>
      <span>${s.roll_number ? 'Roll no. ' + esc(s.roll_number) + ' · ' : ''}${esc(t.term)}: ${esc(s.department)}</span></div>
    <div class="factor"><span>Access code</span><b class="code">${esc(s.access_code)}</b></div>
    ${second}
    <div class="slip-foot">${esc(when(t.schedule))}<br/>Sign in at ${esc(loginUrl)} · keep this slip private</div>
  </article>`;
}

function render() {
  const q = $('filter').value.trim().toLowerCase();
  const t = DATA.test, loginUrl = new URL('../candidate-login.html', location.href).href;
  const list = DATA.slips.filter(s => !q || s.full_name.toLowerCase().includes(q) || (s.roll_number || '').toLowerCase().includes(q));
  $('slips').innerHTML = list.map(s => slipHtml(s, t, loginUrl)).join('') || '<p class="note">No candidates.</p>';
  $('barSub').textContent = ` · ${t.name} · ${list.length} slip${list.length === 1 ? '' : 's'}`;
}

document.addEventListener('DOMContentLoaded', async () => {
  const testId = new URLSearchParams(location.search).get('test_id');
  try { DATA = await api('/roster/slips?test_id=' + encodeURIComponent(testId || '')); }
  catch (e) {
    if (e.status === 401) { location.href = '../institution-login.html'; return; }
    $('barSub').textContent = ' · ' + e.message; return;
  }
  render();
  $('filter').addEventListener('input', render);
  $('printBtn').addEventListener('click', () => window.print());
});
