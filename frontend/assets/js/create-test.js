// ============================================================
// create-test.html — 4-step Aptitude Test creation wizard (Phase 4, talks to /api/v1/tests)
// Step 1: degree level -> fields/departments (incl. General Test)
// Step 2: paper composition; the 1.5× pool check runs on the server (POST /tests/availability)
// Step 3: schedule — the browser converts local date + time to UTC before sending
// Step 4: review, save as draft (POST/PUT /tests) and publish (POST /tests/<id>/publish)
// ?id=<test id> reopens a saved draft.
// ============================================================
let META = null, DEPTS = [], currentStep = 1, rowIdSeq = 1, nameDirty = false, availTimer = null, availSeq = 0;
const state = {
  testId: null, level: null, selected: [], activeTab: null, compositions: {},  // compositions: {deptId: [row]}
  avail: null, availError: null, release: { mode: 'scheduled' }, timeMode: 'flex',
};
const $ = id => document.getElementById(id);
const DEPT = id => DEPTS.find(d => d.id === +id);
const LEVEL = () => META.levels.find(l => l.value === state.level) || META.levels[0];
const T = plural => plural ? LEVEL().term_plural : LEVEL().term;
const label = (list, v) => { const x = (list || []).find(i => i.value === v); return x ? x.label : v; };
const rowKey = (deptId, r) => `${deptId}|${r.subject.toLowerCase()}|${r.question_type}|${r.difficulty}`;

// ---- Local time <-> UTC (the server only stores UTC) ----
const pad = n => String(n).padStart(2, '0');
function toUtc(date, time) { return date && time ? new Date(`${date}T${time}`).toISOString() : null; }
function fromUtc(iso) {
  const d = new Date(iso);
  return { date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`, time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
}
function isoDate(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }

function newRow(deptId, subject) {
  return { id: rowIdSeq++, subject: subject || DEPT(deptId).subjects[0], question_type: META.question_types[0].value, difficulty: 'any', count: 10 };
}

// ---- Availability: approved questions in the bank vs pool needed (server-side, single source of truth) ----
function compositionsBody() {
  return state.selected.map(id => ({ department_id: id, rows: (state.compositions[id] || []).map(({ subject, question_type, difficulty, count }) => ({ subject, question_type, difficulty, count })) }));
}
function scheduleAvailability() {
  clearTimeout(availTimer);
  availTimer = setTimeout(refreshAvailability, 300);
}
async function refreshAvailability() {
  const seq = ++availSeq;
  if (!state.selected.length || state.selected.some(id => !(state.compositions[id] || []).length)) {
    state.avail = null; state.availError = null; return rerender();
  }
  try {
    const { availability } = await api('/tests/availability', { method: 'POST', body: { level: state.level, compositions: compositionsBody() } });
    if (seq !== availSeq) return;                       // a newer edit already asked again
    state.avail = availability; state.availError = null;
  } catch (e) {
    if (seq !== availSeq) return;
    if (e.status === 401) return handleApiError(e);
    state.avail = null; state.availError = e.details?.compositions || e.message;
  }
  rerender();
}
function rowStatus(deptId, row) {
  const hit = state.avail?.rows.find(r => rowKey(r.department_id, r) === rowKey(deptId, row));
  return hit || { needed: Math.ceil(row.count * META.pool_factor), pool: null, short: 0, sufficient: null };
}
function rerender() {
  if (currentStep === 2) { renderStep2(); }
  if (currentStep === 4) { renderStep4(); }
}
/** "Checking…" / "Sufficient" / "Short by N" for one composition row. */
function availBadge(st) {
  if (st.sufficient === null) return '<span class="muted">Checking…</span>';
  if (st.sufficient) return '<span class="badge badge-approved">Sufficient</span>';
  return `<span class="badge badge-draft">Short by ${st.short}</span>`;
}

// ---- Step 1: level, then fields / departments ----
function defaultName() { return `${state.level} Admission Test`; }
function renderStep1() {
  $('levelSeg').innerHTML = META.levels.map(l => `<label><input type="radio" name="lvl" value="${esc(l.value)}" ${l.value === state.level ? 'checked' : ''} onchange="setLevel(this.value)" />${esc(l.value)}</label>`).join('');
  $('step1Lbl').textContent = 'Level & ' + T(true);
  $('selTitle').textContent = '2 · Select ' + T(true).toLowerCase();
  const list = DEPTS.filter(d => d.level === state.level).sort((a, b) => (b.mode === 'general') - (a.mode === 'general'));
  $('fieldToggleList').innerHTML = list.map(d => {
    const checked = state.selected.includes(d.id), gen = d.mode === 'general';
    return `<label class="field-toggle ${checked ? 'checked' : ''}" onclick="toggleField(event,${d.id})">
      <span><b style="color:#fff;">${esc(d.name)}</b>${gen ? '<span class="lvl-pill">General test — same paper subjects for everyone</span>' : ''}
      <span class="muted">· ${d.subjects.length} subjects</span></span>
      <input type="checkbox" ${checked ? 'checked' : ''} /></label>`;
  }).join('') || `<div class="a-empty"><p>No ${esc(T(true).toLowerCase())} exist for ${esc(state.level)} yet. Create one under <a href="fields-subjects.html" style="text-decoration:underline;">Fields &amp; Departments</a> (or add a General Test).</p></div>`;
  if (!nameDirty) $('testName').value = defaultName();
}
function setLevel(l) {
  state.level = l; state.selected = []; state.compositions = {}; state.activeTab = null; state.avail = null; renderStep1();
}
function toggleField(e, id) {
  e.preventDefault();
  if (state.selected.includes(id)) { state.selected = state.selected.filter(x => x !== id); delete state.compositions[id]; }
  else { state.selected.push(id); state.compositions[id] = DEPT(id).subjects.map(s => newRow(id, s)); }
  renderStep1();
}

// ---- Step 2: paper composition ----
function renderStep2() {
  $('compSub').textContent = `Questions per candidate, and the ${META.pool_factor}× pool needed so each candidate gets a different random paper`;
  if (!state.selected.includes(state.activeTab)) state.activeTab = state.selected[0] || null;
  $('fieldTabs').innerHTML = state.selected.map(id => {
    const bad = (state.compositions[id] || []).some(r => rowStatus(id, r).sufficient === false);
    return `<div class="field-tab ${id === state.activeTab ? 'active' : ''}" onclick="switchFieldTab(${id})">${esc(DEPT(id).name)}${bad ? '<span class="shortfall-dot"></span>' : ''}</div>`;
  }).join('');
  const area = $('compositionArea');
  if (!state.activeTab) { area.innerHTML = `<div class="a-empty"><p>Select at least one ${esc(T().toLowerCase())} in Step 1.</p></div>`; return; }
  const id = state.activeTab, d = DEPT(id), rows = state.compositions[id] || [];
  const totalQ = rows.reduce((a, r) => a + r.count, 0), totalPool = rows.reduce((a, r) => a + rowStatus(id, r).needed, 0);
  const combined = state.avail ? state.avail.shortfalls.filter(s => s.department_id === id && s.difficulty === 'combined') : [];
  area.innerHTML = `
    <div class="comp-table-head"><span>Subject</span><span>Type</span><span>Difficulty</span><span>Per candidate</span><span>Pool needed</span><span>In bank</span><span>Status</span><span></span></div>
    ${rows.map(r => renderCompRow(id, d, r)).join('')}
    <button class="a-btn a-btn-ghost a-btn-sm comp-add-row" onclick="addRow(${id})">+ Add row</button>
    ${state.availError ? `<div class="rand-note" style="color:#f87171;">⚠ ${esc(state.availError)}</div>` : ''}
    ${combined.map(s => `<div class="rand-note" style="color:#f87171;">⚠ ${esc(s.label)}: ${s.pool} in bank, ${s.needed} needed (short by ${s.short}).</div>`).join('')}
    <div class="rand-note">🎲 <b>Randomization:</b> each candidate receives <b style="color:#fff;">${totalQ}</b> questions, drawn at random from a pool of at least <b style="color:#fff;">${totalPool}</b>
      (${META.pool_factor}× per row). ${d.mode === 'general' ? 'This is a <b>general test</b> — every candidate is tested on the same subjects.' : `Papers are assembled only from this ${esc(T().toLowerCase())}'s approved questions.`}
      ${rows.some(r => rowStatus(id, r).sufficient === false) || combined.length ? ' <a href="generate.html" style="color:var(--apt-light);text-decoration:underline;">Generate more questions →</a>' : ''}</div>`;
}
function renderCompRow(id, d, row) {
  const st = rowStatus(id, row);
  const badge = availBadge(st);
  const opts = (list, cur) => list.map(o => `<option value="${esc(o.value)}" ${o.value === cur ? 'selected' : ''}>${esc(o.label)}</option>`).join('');
  return `<div class="comp-row">
    <select class="a-select" onchange="updateRow(${id},${row.id},'subject',this.value)">${opts(d.subjects.map(s => ({ value: s, label: s })), row.subject)}</select>
    <select class="a-select" onchange="updateRow(${id},${row.id},'question_type',this.value)">${opts(META.question_types, row.question_type)}</select>
    <select class="a-select" onchange="updateRow(${id},${row.id},'difficulty',this.value)">${opts(META.row_difficulties, row.difficulty)}</select>
    <input class="a-input" type="number" min="1" max="${META.test_limits.max_per_row}" value="${row.count}" onchange="updateRow(${id},${row.id},'count',Math.max(1,parseInt(this.value)||1))" />
    <span class="num-cell">${st.needed}</span><span class="num-cell ${st.sufficient === false ? 'bad' : ''}">${st.pool ?? '…'}</span>
    <span class="status-cell">${badge}</span>
    <button class="rm-btn" onclick="removeRow(${id},${row.id})" title="Remove row">✕</button></div>`;
}
function switchFieldTab(id) { state.activeTab = id; renderStep2(); }
function updateRow(deptId, rowId, key, value) {
  const r = state.compositions[deptId].find(x => x.id === rowId); if (r) r[key] = value;
  renderStep2(); scheduleAvailability();
}
function addRow(deptId) { state.compositions[deptId].push(newRow(deptId)); renderStep2(); scheduleAvailability(); }
function removeRow(deptId, rowId) {
  state.compositions[deptId] = state.compositions[deptId].filter(r => r.id !== rowId); renderStep2(); scheduleAvailability();
}

// ---- Step 3: Schedule & release ----
function toMin(t) { const [h, m] = (t || '0:0').split(':').map(Number); return h * 60 + m; }
function fmt12(t) { const [h, m] = t.split(':').map(Number); return `${h % 12 || 12}:${pad(m)} ${h < 12 ? 'am' : 'pm'}`; }
function updFixed() {
  const a = $('fixStart').value, b = $('fixEnd').value, d = toMin(b) - toMin(a);
  const late = toMin(a) + 30;
  $('fixedNote').innerHTML = d > 0
    ? `⏰ Test runs <b style="color:#fff;">${fmt12(a)} → ${fmt12(b)}</b> (${Math.floor(d / 60)}h ${d % 60}m).<br/>• Candidates <b>cannot start before ${fmt12(a)}</b>.<br/>• The test <b>ends for everyone at ${fmt12(b)}</b> and is auto-submitted — a candidate who starts at ${fmt12(pad(Math.floor(late / 60) % 24) + ':' + pad(late % 60))} gets 30 minutes less, not a full timer.`
    : '<span style="color:#f87171;">End time must be after the start time.</span>';
}
function setTimeMode(m) {
  state.timeMode = m;
  $('modeFlex').classList.toggle('sel', m === 'flex');
  $('modeFixed').classList.toggle('sel', m === 'fixed');
  $('flexFields').style.display = m === 'flex' ? 'block' : 'none';
  $('fixedFields').style.display = m === 'fixed' ? 'block' : 'none';
  $('timeTitle').textContent = m === 'flex' ? 'Time limit & window' : 'Fixed start & end time';
  if (m === 'fixed') updFixed();
}
function setRelease(mode) {
  state.release.mode = mode;
  $('relImmediate').classList.toggle('sel', mode === 'immediate');
  $('relScheduled').classList.toggle('sel', mode === 'scheduled');
  $('relDateField').style.display = mode === 'immediate' ? 'none' : 'flex';
}
function getSchedule() {
  const v = id => $(id).value;
  return state.timeMode === 'fixed'
    ? { mode: 'fixed', date: v('testDate'), start: v('fixStart'), end: v('fixEnd') }
    : { mode: 'flex', date: v('testDate'), start: v('winOpen'), end: v('winClose'), limit: +v('timeLimit') };
}
function scheduleBody() {
  const sc = getSchedule();
  return {
    timing_mode: sc.mode === 'fixed' ? 'fixed' : 'flexible',
    starts_at: toUtc(sc.date, sc.start), ends_at: toUtc(sc.date, sc.end),
    duration_minutes: sc.mode === 'fixed' ? null : sc.limit,
    result_release: state.release.mode,
    release_on: state.release.mode === 'scheduled' ? $('releaseDate').value : null,
  };
}
function testBody() {
  return { name: $('testName').value.trim(), level: state.level, compositions: compositionsBody(), schedule: scheduleBody() };
}

// ---- Step 4: Review & publish ----
function renderStep4() {
  $('reviewFields').innerHTML = state.selected.map(id => {
    const rows = state.compositions[id] || [];
    const rowsHtml = rows.map(row => {
      const st = rowStatus(id, row);
      const statusHtml = availBadge(st);
      return `<tr><td>${esc(row.subject)}</td><td>${esc(label(META.question_types, row.question_type))}</td><td>${esc(label(META.row_difficulties, row.difficulty))}</td><td>${row.count}</td><td>${st.pool ?? '…'} / ${st.needed}</td><td>${statusHtml}</td></tr>`;
    }).join('');
    return `
      <div class="a-card review-field-card">
        <div class="review-field-head"><h3>${esc(DEPT(id).name)}</h3><span class="muted">${esc(state.level)} · candidates are added on the Roster page after publishing</span></div>
        <div class="a-table-wrap"><table class="a-table">
          <thead><tr><th>Subject</th><th>Type</th><th>Difficulty</th><th>Per candidate</th><th>Bank / needed</th><th>Status</th></tr></thead>
          <tbody>${rowsHtml || '<tr><td colspan="6" class="muted">No subjects configured.</td></tr>'}</tbody>
        </table></div>
      </div>`;
  }).join('');

  const sc = getSchedule();
  $('reviewSchedule').innerHTML = sc.mode === 'fixed' ? `
    <div>Mode: <b style="color:#fff;">Fixed time</b></div>
    <div>Date: <b style="color:#fff;">${esc(sc.date)}</b></div>
    <div>Runs: <b style="color:#fff;">${fmt12(sc.start)} – ${fmt12(sc.end)}</b> (hard stop, auto-submit)</div>` : `
    <div>Mode: <b style="color:#fff;">Flexible window</b></div>
    <div>Time limit: <b style="color:#fff;">${sc.limit} minutes</b></div>
    <div>Date: <b style="color:#fff;">${esc(sc.date)}</b></div>
    <div>Window: <b style="color:#fff;">${fmt12(sc.start)} – ${fmt12(sc.end)}</b></div>`;
  const releaseText = state.release.mode === 'immediate'
    ? 'Score shown immediately on submission'
    : `Scheduled email on <b style="color:#fff;">${esc($('releaseDate').value)}</b>`;
  $('reviewRelease').innerHTML = `<div>${releaseText}</div>`;

  const shortfalls = state.avail ? state.avail.shortfalls : [];
  const btn = $('publishBtn'), title = $('publishTitle'), sub = $('publishSub');
  $('shortfallBanner').style.display = shortfalls.length ? 'block' : 'none';
  $('shortfallList').innerHTML = shortfalls.map(s => `<li>⚠ ${esc(s.label)} — ${s.pool} in bank, ${s.needed} needed (short by ${s.short})</li>`).join('');
  if (!state.avail) {
    btn.setAttribute('disabled', 'true'); title.textContent = 'Checking the question bank…';
    sub.textContent = state.availError || 'Counting approved questions for every row.';
  } else if (shortfalls.length) {
    btn.setAttribute('disabled', 'true'); btn.title = 'Resolve every shortfall first';
    title.textContent = 'Publish is blocked';
    sub.textContent = `${shortfalls.length} combination(s) still short of their approved-pool requirement.`;
  } else {
    btn.removeAttribute('disabled'); btn.title = '';
    title.textContent = 'Ready to publish';
    sub.textContent = 'Every required combination meets its approved-pool requirement.';
  }
}

// ---- Saving and publishing ----
async function save() {
  const body = testBody();
  const { test } = state.testId
    ? await api(`/tests/${state.testId}`, { method: 'PUT', body })
    : await api('/tests', { method: 'POST', body });
  state.testId = test.id; state.avail = test.availability;
  history.replaceState(null, '', `?id=${test.id}`);
  return test;
}
async function saveDraft() {
  try { await save(); aToast('Saved as draft.'); renderStep4(); } catch (e) { handleApiError(e); }
}
async function publishTest() {
  const btn = $('publishBtn');
  if (btn.hasAttribute('disabled')) return;
  btn.setAttribute('disabled', 'true');
  try {
    await save();
    await api(`/tests/${state.testId}/publish`, { method: 'POST' });
    aToast('Aptitude test published — now import its candidates on the Roster page.');
    setTimeout(() => { window.location.href = 'roster.html?test=' + state.testId; }, 900);
  } catch (e) {
    if (e.code === 'POOL_TOO_SMALL') {                  // the bank changed meanwhile: show the server's list
      state.avail = { ...(state.avail || { rows: [] }), all_sufficient: false, shortfalls: e.details.shortfalls };
      renderStep4();
    } else { btn.removeAttribute('disabled'); }
    handleApiError(e);
  }
}

// ---- Wizard navigation ----
const STEP_LABELS = ['', 'Next: Paper Composition →', 'Next: Schedule &amp; Release →', 'Next: Review &amp; Publish →', ''];
function renderStep() {
  document.querySelectorAll('.wiz-step').forEach(s => {
    const n = parseInt(s.dataset.step);
    s.classList.toggle('active', n === currentStep);
    s.classList.toggle('done', n < currentStep);
  });
  document.querySelectorAll('.wiz-panel').forEach(p => p.classList.toggle('active', p.id === `panel-${currentStep}`));
  $('backBtn').disabled = currentStep === 1;
  const nextBtn = $('nextBtn');
  if (currentStep === 4) nextBtn.style.display = 'none';
  else { nextBtn.style.display = 'inline-flex'; nextBtn.innerHTML = STEP_LABELS[currentStep]; }
  if (currentStep === 1) renderStep1();
  // refreshAvailability never rejects: it shows its own errors
  if (currentStep === 2) { renderStep2(); void refreshAvailability(); }
  if (currentStep === 4) { renderStep4(); void refreshAvailability(); }
}
function validateStep(step) {
  if (step === 1) {
    if (!state.selected.length) { aToast(`Select at least one ${esc(T().toLowerCase())} to continue.`, '⚠'); return false; }
    if ($('testName').value.trim().length < 3) { aToast('Give this test a name (at least 3 characters).', '⚠'); return false; }
    return true;
  }
  if (step === 2) {
    const empty = state.selected.find(id => !(state.compositions[id] || []).length);
    if (empty) { aToast(`${esc(DEPT(empty).name)} needs at least one subject row.`, '⚠'); return false; }
    return true;
  }
  if (step === 3) {
    if (!$('testDate').value) { aToast('Set the test date.', '⚠'); return false; }
    const sc = getSchedule();
    if (toMin(sc.end) <= toMin(sc.start)) { aToast('End time must be after the start time.', '⚠'); return false; }
    if (sc.mode === 'flex' && (!sc.limit || sc.limit <= 0)) { aToast('Set a time limit.', '⚠'); return false; }
    if (sc.mode === 'flex' && sc.limit > toMin(sc.end) - toMin(sc.start)) { aToast('The time limit is longer than the window.', '⚠'); return false; }
    if (new Date(`${sc.date}T${sc.start}`) <= new Date()) { aToast('The start time has already passed.', '⚠'); return false; }
    if (state.release.mode === 'scheduled' && !$('releaseDate').value) { aToast('Set the result release date.', '⚠'); return false; }
    return true;
  }
  return true;
}
function wizNext() { if (validateStep(currentStep) && currentStep < 4) { currentStep++; renderStep(); } }
function wizBack() { if (currentStep > 1) { currentStep--; renderStep(); } }

// ---- Reopen a saved draft (?id=) ----
function loadTest(test) {
  state.testId = test.id; state.level = test.level; nameDirty = true;
  $('testName').value = test.name;
  state.selected = test.compositions.map(c => c.department_id);
  test.compositions.forEach(c => { state.compositions[c.department_id] = c.rows.map(r => ({ ...r, id: rowIdSeq++ })); });
  state.avail = test.availability;
  const s = test.schedule, a = fromUtc(s.starts_at), b = fromUtc(s.ends_at);
  $('testDate').value = a.date;
  if (s.timing_mode === 'fixed') { $('fixStart').value = a.time; $('fixEnd').value = b.time; setTimeMode('fixed'); }
  else { $('winOpen').value = a.time; $('winClose').value = b.time; $('timeLimit').value = s.duration_minutes; setTimeMode('flex'); }
  setRelease(s.result_release);
  if (s.release_on) $('releaseDate').value = s.release_on;
}

document.addEventListener('admin:ready', async () => {
  $('testName').addEventListener('input', () => nameDirty = true);
  const week = new Date(Date.now() + 7 * 864e5), fortnight = new Date(Date.now() + 14 * 864e5);
  $('testDate').value = isoDate(week); $('releaseDate').value = isoDate(fortnight);
  try {
    const [meta, depts] = await Promise.all([loadMeta(), api('/departments')]);
    META = meta; DEPTS = depts.items;
    state.level = META.defaults.level;
    const id = new URLSearchParams(location.search).get('id');
    if (id) {
      const { test } = await api(`/tests/${encodeURIComponent(id)}`);
      if (test.status !== 'draft') { aToast('This test is already published and can no longer be edited.', '⚠'); setTimeout(() => location.replace('monitor.html'), 1200); return; }
      loadTest(test);
    }
  } catch (e) { return handleApiError(e); }
  renderStep();
});
