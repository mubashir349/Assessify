// monitor.html — live status of every candidate on one published test (Phase 7).
// GET /monitor every 5 s (paused while this tab is hidden). Unlock / End call /attempts/<id>/unlock and /end.
const REFRESH_MS = 5000;
const $ = id => document.getElementById(id);
const STATUSES = [
  { key: '', label: 'All candidates', color: '#fff', countKey: 'all' },
  { key: 'not_started', label: 'Not Started', color: '#94a3b8' },
  { key: 'in_progress', label: 'In Progress', color: '#22c55e' },
  { key: 'locked', label: 'Locked', color: '#ef4444' },
  { key: 'disconnected', label: 'Disconnected', color: '#f59e0b' },
  { key: 'auto_submitted', label: 'Auto-Submitted', color: '#818cf8' },
  { key: 'completed', label: 'Completed', color: '#22d3ee' },
];
const BADGE = {
  not_started: ['badge-not-started', 'Not Started'],
  in_progress: ['badge-in-progress', '● In Progress'],
  locked: ['badge-locked', '🔒 Locked'],
  disconnected: ['badge-disconnected', '⚠ Disconnected'],
  auto_submitted: ['badge-auto-submitted', 'Auto-Submitted'],
  completed: ['badge-completed', '✓ Completed'],
};
const STATE_LABEL = { live: 'Live now', upcoming: 'Upcoming', ended: 'Ended' };
let TESTS = [], MODE = 'fixed', statusFilter = '', timer = null, searchTimer = null, busy = false;

function clock(sec) {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const mm = String(m).padStart(2, '0'), ss = String(r).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function ago(sec) {
  if (sec < 10) return 'just now';
  if (sec < 120) return `${sec}s ago`;
  return `${Math.floor(sec / 60)} min ago`;
}

function fmtWhen(iso) {
  return iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '';
}

// ---------------------------------------------------------------- tests
async function loadTests() {
  try {
    ({ tests: TESTS } = await api('/monitor/tests'));
  } catch (e) { return handleApiError(e); }
  if (!TESTS.length) { $('noTests').hidden = false; setLive('No tests', true); return; }
  $('monitorArea').hidden = false;
  $('testSel').innerHTML = TESTS.map(t => `<option value="${t.id}">${esc(t.name)} · ${STATE_LABEL[t.state]} · ${t.candidates} candidates</option>`).join('');
  const want = new URLSearchParams(location.search).get('test');
  if (want && TESTS.some(t => String(t.id) === want)) $('testSel').value = want;
  selectTest();
}

function selectTest() {
  statusFilter = '';
  $('deptSel').innerHTML = '<option value="">All fields / departments</option>';
  $('searchBox').value = '';
  void refresh(true);
}

function setLive(text, paused) {
  $('liveText').textContent = text;
  $('liveDot').classList.toggle('paused', paused);
}

// ---------------------------------------------------------------- snapshot
function query() {
  const p = new URLSearchParams({ test_id: $('testSel').value });
  if (statusFilter) p.set('status', statusFilter);
  if ($('deptSel').value) p.set('department_id', $('deptSel').value);
  if ($('searchBox').value.trim()) p.set('q', $('searchBox').value.trim());
  return p.toString();
}

async function refresh(firstLoad = false) {
  if (busy || !$('testSel').value) return;
  busy = true;
  try {
    const data = await api('/monitor?' + query());
    render(data, firstLoad);
    const live = data.test.state === 'live';
    setLive(`${live ? 'Live' : STATE_LABEL[data.test.state]} · updated ${new Date().toLocaleTimeString()}`, !live);
  } catch (e) {
    setLive('Connection problem — retrying', true);
    if (e.status === 401 || firstLoad) handleApiError(e);
  } finally {
    busy = false;
  }
  schedule();
}

function schedule() {
  clearTimeout(timer);
  timer = setTimeout(() => { if (!document.hidden) void refresh(); else schedule(); }, REFRESH_MS);
}

function render(data, firstLoad) {
  const t = data.test;
  MODE = t.schedule.timing_mode;
  const sub = document.getElementById('a-sub');
  sub.hidden = false;
  sub.textContent = `${t.name} · ${STATE_LABEL[t.state]} · ${fmtWhen(t.schedule.starts_at)} – ${fmtWhen(t.schedule.ends_at)}`;
  $('offlineSecs').textContent = data.disconnected_after_seconds;
  if (firstLoad) {
    $('deptSel').innerHTML = '<option value="">All fields / departments</option>'
      + t.departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  }
  renderStrip(data.counts);
  renderRows(data.items);
}

function renderStrip(counts) {
  $('statusStrip').innerHTML = STATUSES.map(s => {
    const n = counts[s.countKey || s.key] ?? 0;
    const active = s.key === statusFilter ? ' active' : '';
    return `<button type="button" class="status-pill${active}" data-status="${s.key}" aria-pressed="${s.key === statusFilter}">`
      + `<div class="n" style="color:${s.color};">${n}</div><div class="l">${s.label}</div></button>`;
  }).join('');
}

function remainingCell(r) {
  const a = r.attempt;
  if (!a || a.status === 'submitted') return '—';
  // fixed time keeps running while locked; a locked flexible timer is frozen
  const ticking = r.status !== 'locked' || MODE === 'fixed';
  return `<span class="mono" data-left="${a.remaining_seconds}" data-tick="${ticking ? 1 : 0}">${clock(a.remaining_seconds)}</span>`;
}

function answeredCell(a) {
  if (!a) return '—';
  const pct = a.question_count ? Math.round(100 * a.answered_count / a.question_count) : 0;
  return `<span class="mono">${a.answered_count}/${a.question_count}</span><span class="progress-mini"><span style="width:${pct}%"></span></span>`;
}

function statusCell(r) {
  const [cls, label] = BADGE[r.status];
  const a = r.attempt;
  let note = '';
  if (r.status === 'locked') note = `${esc(a.lock_reason || '')} · lock ${a.lock_count}`;
  else if (r.status === 'completed' && a.submit_reason === 'admin') note = 'Ended by proctor';
  else if (r.status === 'completed' || r.status === 'auto_submitted') note = `Score ${a.score}/${a.max_score}`;
  const noteHtml = note ? '<span class="mon-sub">' + note + '</span>' : '';
  return `<span class="badge ${cls}">${label}</span>${noteHtml}`;
}

function seenCell(r) {
  const a = r.attempt;
  if (!a || a.status === 'submitted') return '—';
  return ago(a.seconds_since_seen);
}

function actionsCell(r) {
  const a = r.attempt;
  if (!a) return '<span class="muted" style="font-size:12px;">Awaiting start</span>';
  if (a.status === 'submitted') return `<span class="mono">${esc(a.reference)}</span>`;
  const unlock = a.status === 'locked'
    ? `<button type="button" class="a-btn a-btn-amber a-btn-sm" data-act="unlock" data-id="${a.id}" data-name="${esc(r.full_name)}">Unlock</button>` : '';
  const end = `<button type="button" class="a-btn a-btn-danger a-btn-sm" data-act="end" data-id="${a.id}" data-name="${esc(r.full_name)}">End</button>`;
  return `<div class="mon-actions">${unlock}${end}</div>`;
}

function renderRows(items) {
  if (!items.length) {
    $('monBody').innerHTML = '<tr><td colspan="8" class="muted">No candidates match.</td></tr>';
    return;
  }
  $('monBody').innerHTML = items.map(r => `<tr>
      <td class="name">${esc(r.full_name)}<span class="mon-sub">${esc(r.email || '')}</span></td>
      <td class="mono">${esc(r.roll_number || '—')}</td><td>${esc(r.department.name)}</td>
      <td>${statusCell(r)}</td><td>${answeredCell(r.attempt)}</td><td>${remainingCell(r)}</td>
      <td class="muted">${seenCell(r)}</td><td>${actionsCell(r)}</td></tr>`).join('');
}

// Between refreshes the timers count down on their own (data-tick 0 = frozen).
function tick() {
  document.querySelectorAll('#monBody [data-tick="1"]').forEach(el => {
    const left = Math.max(0, Number(el.dataset.left) - 1);
    el.dataset.left = left;
    el.textContent = clock(left);
  });
}

// ---------------------------------------------------------------- actions
async function act(btn) {
  const { act: what, id, name } = btn.dataset;
  if (what === 'end' && !confirm(`End the test for ${name}? Their saved answers are scored now and they cannot continue.`)) return;
  btn.disabled = true;
  try {
    await api(`/attempts/${id}/${what}`, { method: 'POST' });
    aToast(what === 'unlock' ? `${esc(name)} unlocked — they can continue.` : `${esc(name)}'s test was ended and scored.`);
  } catch (e) { handleApiError(e); }
  await refresh();
}

function wire() {
  $('testSel').addEventListener('change', selectTest);
  $('deptSel').addEventListener('change', () => void refresh());
  $('searchBox').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => void refresh(), 300); });
  $('statusStrip').addEventListener('click', e => {
    const pill = e.target.closest('[data-status]');
    if (!pill) return;
    statusFilter = pill.dataset.status;
    void refresh();
  });
  $('monBody').addEventListener('click', e => {
    const btn = e.target.closest('button[data-act]');
    if (btn) void act(btn);
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  setInterval(tick, 1000);
}

document.addEventListener('admin:ready', () => { wire(); void loadTests(); }, { once: true });
