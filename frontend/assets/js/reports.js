// reports.html — reports of published tests (Phase 7). Every number comes from GET /reports/tests/<id>.
// Filters run on the server; Export CSV uses the same filters as the table.
const $ = id => document.getElementById(id);
const STATE_LABEL = { live: 'Live now', upcoming: 'Upcoming', ended: 'Ended' };
const CAND_STATUS = {
  submitted: ['badge-completed', 'Submitted'],
  in_progress: ['badge-in-progress', 'Taking it'],
  not_attempted: ['badge-not-started', 'Did not attempt'],
};
const MAIL = {
  sent: ['badge-approved', 'Sent'],
  logged: ['badge-draft', 'Logged (test mode)'],
  failed: ['badge-locked', 'Failed'],
};
let TEST_ID = null, listTimer = null, candTimer = null;

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleDateString([], { dateStyle: 'medium' }) : '';
}

function pct(v) {
  return v === null || v === undefined ? '–' : `${v}%`;
}

function bar(label, value, shown) {
  const w = Math.max(0, Math.min(100, value || 0));
  return `<div class="bar-row"><span class="lb">${esc(label)}</span><span class="tr"><span class="fl" style="width:${w}%;display:block"></span></span><span class="v">${shown}</span></div>`;
}

// ---------------------------------------------------------------- test list
function listQuery() {
  const p = new URLSearchParams();
  if ($('tQ').value.trim()) p.set('q', $('tQ').value.trim());
  if ($('tLevel').value) p.set('level', $('tLevel').value);
  if ($('tYear').value) p.set('year', $('tYear').value);
  return p.toString();
}

async function loadTests() {
  let tests;
  try { ({ tests } = await api('/reports/tests?' + listQuery())); } catch (e) { return handleApiError(e); }
  $('testsBody').innerHTML = tests.map(t => `<tr data-id="${t.id}" class="${t.id === TEST_ID ? 'picked' : ''}">
      <td class="name">${esc(t.name)}</td><td>${esc(t.level)}</td><td class="mono">${fmtDate(t.starts_at)}</td>
      <td>${STATE_LABEL[t.state]}</td><td class="mono">${t.candidates}</td><td class="mono">${t.submitted}</td>
      <td class="mono">${pct(t.average_percent)}</td>
      <td><button type="button" class="a-btn a-btn-ghost a-btn-sm" data-open="${t.id}">Open report</button></td></tr>`).join('')
    || '<tr><td colspan="8" class="muted">No published tests match. Reports appear for published tests.</td></tr>';
  if (TEST_ID === null && tests.length) openReport((tests.find(t => t.submitted) || tests[0]).id);
}

function fillYears() {
  const now = new Date().getFullYear();
  const years = [now + 1, now, now - 1, now - 2, now - 3];
  $('tYear').innerHTML += years.map(y => `<option value="${y}">${y}</option>`).join('');
}

// ---------------------------------------------------------------- one report
function candQuery() {
  const p = new URLSearchParams();
  const add = (key, id) => { const v = $(id).value.trim(); if (v) p.set(key, v); };
  add('q', 'cQ'); add('department_id', 'cDept'); add('status', 'cStatus'); add('email', 'cEmail');
  return p.toString();
}

function openReport(id) {
  TEST_ID = id;
  ['cQ', 'cDept', 'cStatus', 'cEmail'].forEach(k => { $(k).value = ''; });
  document.querySelectorAll('#testsBody tr').forEach(tr => tr.classList.toggle('picked', Number(tr.dataset.id) === id));
  $('aiTips').innerHTML = '';
  void loadReport(true);
}

async function loadReport(firstLoad = false) {
  let d;
  try { d = await api(`/reports/tests/${TEST_ID}?${candQuery()}`); } catch (e) { return handleApiError(e); }
  $('reportArea').hidden = false;
  if (firstLoad) {
    $('cDept').innerHTML = '<option value="">All fields / departments</option>'
      + d.test.departments.map(x => `<option value="${x.id}">${esc(x.name)}</option>`).join('');
  }
  renderHead(d);
  renderCharts(d);
  $('ruleTips').innerHTML = d.insights.map(t => `<div class="ai-item"><span class="ic">📊</span><span>${esc(t)}</span></div>`).join('');
  renderMail(d.email, d.test);
  renderCandidates(d.candidates);
}

function renderHead(d) {
  const t = d.test, s = d.summary;
  $('rName').textContent = t.name;
  const release = t.result_release === 'immediate' ? 'Scores shown on submit' : `Results released by email${t.release_on ? ' on ' + fmtDate(t.release_on) : ''}`;
  $('rMeta').textContent = `${t.level} · ${fmtDate(t.starts_at)} · ${STATE_LABEL[t.state]} · ${release}`;
  $('stSubmitted').textContent = `${s.submitted} / ${s.candidates}`;
  const absent = s.absent ? `${s.absent} absent` : `${s.not_attempted} not started`;
  $('stSubmittedSub').textContent = `${absent} · ${s.auto_submitted} auto-submitted`;
  $('stAvg').textContent = pct(s.average_percent);
  $('stMedian').textContent = s.median_percent === null ? '' : `median ${s.median_percent}%`;
  $('stHigh').textContent = pct(s.highest_percent);
  $('stLow').textContent = pct(s.lowest_percent);
}

function renderCharts(d) {
  const most = Math.max(1, ...d.summary.distribution.map(b => b.count));
  $('distBars').innerHTML = d.summary.distribution.map(b => bar(b.label, 100 * b.count / most, b.count)).join('');
  $('deptBars').innerHTML = d.by_department.map(x => bar(x.name, x.average_percent, pct(x.average_percent))).join('');
  $('subjBars').innerHTML = d.by_subject.map(x => bar(x.subject, x.accuracy_percent, pct(x.accuracy_percent))).join('')
    || '<div class="muted">No submitted answers yet.</div>';
  $('hardList').innerHTML = d.hardest_questions.map(q => `<div class="hard-q">${esc(q.text)}
      <div class="meta">${esc(q.subject)} · ${esc(q.difficulty)} · ${q.correct} of ${q.asked} correct (${q.accuracy_percent}%)</div></div>`).join('')
    || '<div class="muted">Shown once a question has been answered by at least two candidates.</div>';
}

function renderMail(mail, test) {
  const c = mail.counts;
  $('mailNote').textContent = mail.message;
  $('mailBadge').className = 'badge ' + (c.failed ? 'badge-locked' : 'badge-approved');
  $('mailBadge').textContent = `${c.sent + c.logged} sent · ${c.failed} failed · ${c.not_sent} not sent`;
  $('sendBtn').disabled = !mail.ready;
  $('sendBtn').title = mail.ready ? `Email each submitted candidate of ${test.name} their score` : mail.message;
}

function mailCell(r) {
  if (r.status !== 'submitted') return '—';
  const m = r.result_email;
  if (!m) return '<span class="muted">Not sent</span>';
  const [cls, label] = MAIL[m.status];
  const errHtml = m.error ? '<span class="mail-err">' + esc(m.error) + '</span>' : '';
  return `<span class="badge ${cls}">${label}</span>${errHtml}`;
}

function scoreCell(r) {
  if (r.score === null) return '—';
  return `<span class="mono">${r.score}/${r.max_score}</span> <b>${r.percent}%</b>`;
}

function renderCandidates(rows) {
  $('candBody').innerHTML = rows.map(r => {
    const [cls, label] = CAND_STATUS[r.status];
    const reason = r.submit_reason === 'time_up' ? ' · time up' : '';
    return `<tr><td class="mono">${r.rank ?? '—'}</td><td class="name">${esc(r.full_name)}<span class="mon-sub">${esc(r.email)}</span></td>
      <td class="mono">${esc(r.roll_number)}</td><td>${esc(r.department.name)}</td>
      <td><span class="badge ${cls}">${label}</span><span class="muted">${reason}</span></td>
      <td>${scoreCell(r)}</td><td class="mono">${r.lock_count}</td><td>${mailCell(r)}</td></tr>`;
  }).join('') || '<tr><td colspan="8" class="muted">No candidates match.</td></tr>';
}

// ---------------------------------------------------------------- actions
async function sendResults() {
  if (!confirm('Email every submitted candidate their score? Candidates already emailed are skipped.')) return;
  const btn = $('sendBtn');
  btn.disabled = true;
  btn.textContent = 'Sending…';
  try {
    const r = await api(`/reports/tests/${TEST_ID}/send-results`, { method: 'POST', body: {} });
    const icon = r.failed ? '⚠' : '✓';
    const logged = r.logged ? `${r.logged} written to the server log (test mode), ` : '';
    const nothing = r.tried ? '' : ' — nothing new to send';
    aToast(`${r.sent} sent, ${logged}${r.failed} failed${nothing}.`, icon);
  } catch (e) { handleApiError(e); }
  btn.textContent = '✉ Send results';
  await loadReport();
}

function wire() {
  const relist = () => { clearTimeout(listTimer); listTimer = setTimeout(() => void loadTests(), 300); };
  $('tQ').addEventListener('input', relist);
  $('tLevel').addEventListener('change', relist);
  $('tYear').addEventListener('change', relist);
  $('testsBody').addEventListener('click', e => {
    const btn = e.target.closest('[data-open]');
    if (btn) openReport(Number(btn.dataset.open));
  });
  const reload = () => { clearTimeout(candTimer); candTimer = setTimeout(() => void loadReport(), 300); };
  ['cQ'].forEach(k => $(k).addEventListener('input', reload));
  ['cDept', 'cStatus', 'cEmail'].forEach(k => $(k).addEventListener('change', reload));
  $('exportBtn').addEventListener('click', () => void downloadFile(`/reports/tests/${TEST_ID}/export.csv?${candQuery()}`, 'report.csv'));
  $('sendBtn').addEventListener('click', () => void sendResults());
  $('aiBtn').addEventListener('click', () => void askAi({ scope: 'test', test_id: TEST_ID }, $('aiTips'), $('aiBtn')));
}

document.addEventListener('admin:ready', async () => {
  wire();
  fillYears();
  try {
    const meta = await loadMeta();
    fillSelect($('tLevel'), meta.levels.map(l => l.value), { keepFirst: true });
  } catch (e) { /* levels list is optional: the filter just stays empty */ }
  const want = Number(new URLSearchParams(location.search).get('test'));
  if (want) openReport(want);
  await loadTests();
}, { once: true });
