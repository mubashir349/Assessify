// ============================================================
// create-test.html — 4-step Aptitude Test creation wizard
// Step 1: degree level -> fields/departments (incl. General Test)
// Step 2: paper composition with random-pool sufficiency
// ============================================================
const TYPES = ['MCQ', 'True/False'];
const DIFFICULTIES = ['Any', 'Easy', 'Medium', 'Hard'];
const POOL_FACTOR = 1.5; // pool needed = per-candidate count x 1.5, so each candidate gets a different random paper

let currentStep = 1, rowIdSeq = 1, nameDirty = false;
const state = { level: 'Undergraduate', selected: new Set(), activeTab: null, compositions: {}, release: { mode: 'scheduled' }, timeMode: 'flex' };
const DEPT = name => AA.depts().find(d => d.name === name && d.level === state.level);
const T = (plural) => AA.term(state.level, plural);

function defaultRowsFor(name) {
  return DEPT(name).subjects.map(s => ({ id: rowIdSeq++, subject: s, type: 'MCQ', difficulty: 'Any', count: 10 }));
}

// ---- Sufficiency: approved questions in the bank vs pool needed ----
function poolSize(name, row) {
  return AA.seedQ.concat(AA.bank()).filter(q => q.status === 'approved' && q.dept === name && q.level === state.level &&
    q.subject === row.subject && q.type === row.type && (row.difficulty === 'Any' || q.difficulty === row.difficulty)).length;
}
function rowStatus(name, row) {
  const needed = Math.ceil(row.count * POOL_FACTOR), pool = poolSize(name, row);
  return { needed, pool, sufficient: pool >= needed, short: Math.max(0, needed - pool) };
}
function collectAllShortfalls() {
  const out = [];
  state.selected.forEach(name => (state.compositions[name] || []).forEach(row => {
    const st = rowStatus(name, row);
    if (!st.sufficient) out.push({ label: `${name} → ${row.subject} · ${row.type}, ${row.difficulty}`, pool: st.pool, required: st.needed, short: st.short });
  }));
  return out;
}

// ---- Step 1: level, then fields / departments ----
function defaultName() { return `${state.level} Admission Test — Fall 2026`; }
function renderStep1() {
  document.getElementById('levelSeg').innerHTML = AA.LEVELS.map(l => `<label><input type="radio" name="lvl" value="${l}" ${l === state.level ? 'checked' : ''} onchange="setLevel('${l}')" />${l}</label>`).join('');
  document.getElementById('step1Lbl').textContent = 'Level & ' + T(true);
  document.getElementById('selTitle').textContent = '2 · Select ' + T(true).toLowerCase();
  const list = AA.depts().filter(d => d.level === state.level).sort((a, b) => (b.mode === 'general') - (a.mode === 'general'));
  document.getElementById('fieldToggleList').innerHTML = list.map(d => {
    const checked = state.selected.has(d.name), gen = d.mode === 'general';
    return `<label class="field-toggle ${checked ? 'checked' : ''}" onclick="toggleField(event,'${AA.esc(d.name).replace(/'/g, "\\'")}')">
      <span><b style="color:#fff;">${AA.esc(d.name)}</b>${gen ? '<span class="lvl-pill">General test — same paper subjects for everyone</span>' : ''}
      <span class="muted">· ${d.subjects.length} subjects · ${AA.candidates(d.name)} candidates</span></span>
      <input type="checkbox" ${checked ? 'checked' : ''} /></label>`;
  }).join('') || `<div class="a-empty"><p>No ${T(true).toLowerCase()} exist for ${state.level} yet. Create one under Fields &amp; Departments (or add a General Test).</p></div>`;
  const nm = document.getElementById('testName'); if (!nameDirty) nm.value = defaultName();
}
function setLevel(l) {
  state.level = l; state.selected.clear(); state.compositions = {}; state.activeTab = null; renderStep1();
}
function toggleField(e, name) {
  e.preventDefault();
  if (state.selected.has(name)) { state.selected.delete(name); delete state.compositions[name]; }
  else { state.selected.add(name); state.compositions[name] = defaultRowsFor(name); }
  renderStep1();
}

// ---- Step 2: paper composition ----
function renderStep2() {
  document.getElementById('compSub').textContent = `Questions per candidate, and the ${POOL_FACTOR}× pool needed so each candidate gets a different random paper`;
  const tabsEl = document.getElementById('fieldTabs'), names = [...state.selected];
  if (!names.includes(state.activeTab)) state.activeTab = names[0] || null;
  tabsEl.innerHTML = names.map(n => {
    const bad = (state.compositions[n] || []).some(r => !rowStatus(n, r).sufficient);
    return `<div class="field-tab ${n === state.activeTab ? 'active' : ''}" data-n="${AA.esc(n)}" onclick="switchFieldTab(this.dataset.n)">${AA.esc(n)}${bad ? '<span class="shortfall-dot"></span>' : ''}</div>`;
  }).join('');
  const area = document.getElementById('compositionArea');
  if (!state.activeTab) { area.innerHTML = `<div class="a-empty"><p>Select at least one ${T().toLowerCase()} in Step 1.</p></div>`; return; }
  const d = DEPT(state.activeTab), rows = state.compositions[state.activeTab] || [];
  const totalQ = rows.reduce((a, r) => a + r.count, 0), totalPool = rows.reduce((a, r) => a + rowStatus(state.activeTab, r).needed, 0);
  const subjOpts = d.subjects.map(s => `<option>${AA.esc(s)}</option>`).join('');
  area.innerHTML = `
    <div class="comp-table-head"><span>Subject</span><span>Type</span><span>Difficulty</span><span>Per candidate</span><span>Pool needed</span><span>In bank</span><span>Status</span><span></span></div>
    ${rows.map(r => renderCompRow(state.activeTab, r, subjOpts)).join('')}
    <button class="a-btn a-btn-ghost a-btn-sm comp-add-row" data-n="${AA.esc(state.activeTab)}" onclick="addRow(this.dataset.n)">+ Add row</button>
    <div class="rand-note">🎲 <b>Randomization:</b> each candidate receives <b style="color:#fff;">${totalQ}</b> questions, drawn at random from a pool of at least <b style="color:#fff;">${totalPool}</b>
      (${POOL_FACTOR}× per subject). ${d.mode === 'general' ? 'This is a <b>general test</b> — every candidate is tested on the same subjects.' : `Papers are assembled only from this ${T().toLowerCase()}'s approved questions.`}
      ${rows.some(r => !rowStatus(state.activeTab, r).sufficient) ? ' <a href="generate.html" style="color:var(--apt-light);text-decoration:underline;">Generate more questions →</a>' : ''}</div>`;
}
function renderCompRow(name, row, subjOpts) {
  const st = rowStatus(name, row), n = AA.esc(name).replace(/'/g, "\\'");
  const badge = st.sufficient ? '<span class="badge badge-approved">Sufficient</span>' : `<span class="badge badge-draft">Short by ${st.short}</span>`;
  return `<div class="comp-row">
    <select class="a-select" onchange="updateRow('${n}',${row.id},'subject',this.value)">${subjOpts.replace(`<option>${AA.esc(row.subject)}</option>`, `<option selected>${AA.esc(row.subject)}</option>`)}</select>
    <select class="a-select" onchange="updateRow('${n}',${row.id},'type',this.value)">${TYPES.map(t => `<option ${t === row.type ? 'selected' : ''}>${t}</option>`).join('')}</select>
    <select class="a-select" onchange="updateRow('${n}',${row.id},'difficulty',this.value)">${DIFFICULTIES.map(x => `<option ${x === row.difficulty ? 'selected' : ''}>${x}</option>`).join('')}</select>
    <input class="a-input" type="number" min="1" value="${row.count}" onchange="updateRow('${n}',${row.id},'count',parseInt(this.value)||1)" />
    <span class="num-cell">${st.needed}</span><span class="num-cell ${st.sufficient ? '' : 'bad'}">${st.pool}</span>
    <span class="status-cell">${badge}</span>
    <button class="rm-btn" onclick="removeRow('${n}',${row.id})" title="Remove row">✕</button></div>`;
}
function switchFieldTab(n) { state.activeTab = n; renderStep2(); }
function updateRow(name, id, key, value) { const r = state.compositions[name].find(x => x.id === id); if (r) r[key] = value; renderStep2(); }
function addRow(name) { state.compositions[name].push({ id: rowIdSeq++, subject: DEPT(name).subjects[0], type: 'MCQ', difficulty: 'Any', count: 10 }); renderStep2(); }
function removeRow(name, id) { state.compositions[name] = state.compositions[name].filter(r => r.id !== id); renderStep2(); }

// ---- Step 3: Schedule & release ----
function toMin(t) { const [h, m] = (t || '0:0').split(':').map(Number); return h * 60 + m; }
function fmt12(t) { const [h, m] = t.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'am' : 'pm'}`; }
function updFixed() {
  const a = document.getElementById('fixStart').value, b = document.getElementById('fixEnd').value, d = toMin(b) - toMin(a);
  document.getElementById('fixedNote').innerHTML = d > 0
    ? `⏰ Test runs <b style="color:#fff;">${fmt12(a)} → ${fmt12(b)}</b> (${Math.floor(d / 60)}h ${d % 60}m).<br/>• Candidates <b>cannot start before ${fmt12(a)}</b>.<br/>• The test <b>ends for everyone at ${fmt12(b)}</b> and is auto-submitted — a candidate who starts at ${fmt12(String(Math.floor((toMin(a) + 30) / 60)).padStart(2, '0') + ':' + String((toMin(a) + 30) % 60).padStart(2, '0'))} gets 30 minutes less, not a full timer.`
    : '<span style="color:#f87171;">End time must be after the start time.</span>';
}
function setTimeMode(m) {
  state.timeMode = m;
  document.getElementById('modeFlex').classList.toggle('sel', m === 'flex');
  document.getElementById('modeFixed').classList.toggle('sel', m === 'fixed');
  document.getElementById('flexFields').style.display = m === 'flex' ? 'block' : 'none';
  document.getElementById('fixedFields').style.display = m === 'fixed' ? 'block' : 'none';
  document.getElementById('timeTitle').textContent = m === 'flex' ? 'Time limit & window' : 'Fixed start & end time';
  if (m === 'fixed') updFixed();
}
function setRelease(mode) {
  state.release.mode = mode;
  document.getElementById('relImmediate').classList.toggle('sel', mode === 'immediate');
  document.getElementById('relScheduled').classList.toggle('sel', mode === 'scheduled');
  document.getElementById('relDateField').style.display = mode === 'immediate' ? 'none' : 'flex';
}

// ---- Step 4: Review & publish ----
function renderStep4() {
  const reviewFields = document.getElementById('reviewFields');
  reviewFields.innerHTML = [...state.selected].map(field => {
    const rows = state.compositions[field] || [];
    const rowsHtml = rows.map(row => {
      const st = rowStatus(field, row);
      const statusHtml = st.sufficient ? `<span class="badge badge-approved">Sufficient</span>` : `<span class="badge badge-draft">Short by ${st.short}</span>`;
      return `<tr><td>${AA.esc(row.subject)}</td><td>${row.type}</td><td>${row.difficulty}</td><td>${row.count}</td><td>${st.pool} / ${st.needed}</td><td>${statusHtml}</td></tr>`;
    }).join('');
    return `
      <div class="a-card review-field-card">
        <div class="review-field-head"><h3>${AA.esc(field)}</h3><span class="muted">${AA.candidates(field)} candidates · ${state.level}</span></div>
        <div class="a-table-wrap"><table class="a-table">
          <thead><tr><th>Subject</th><th>Type</th><th>Difficulty</th><th>Per candidate</th><th>Bank / needed</th><th>Status</th></tr></thead>
          <tbody>${rowsHtml || '<tr><td colspan="6" class="muted">No subjects configured.</td></tr>'}</tbody>
        </table></div>
      </div>`;
  }).join('');

  const sc = getSchedule();
  document.getElementById('reviewSchedule').innerHTML = sc.mode === 'fixed' ? `
    <div>Mode: <b style="color:#fff;">Fixed time</b></div>
    <div>Date: <b style="color:#fff;">${sc.date}</b></div>
    <div>Runs: <b style="color:#fff;">${fmt12(sc.start)} – ${fmt12(sc.end)}</b> (hard stop, auto-submit)</div>` : `
    <div>Mode: <b style="color:#fff;">Flexible window</b></div>
    <div>Time limit: <b style="color:#fff;">${sc.limit} minutes</b></div>
    <div>Date: <b style="color:#fff;">${sc.date}</b></div>
    <div>Window: <b style="color:#fff;">${fmt12(sc.start)} – ${fmt12(sc.end)}</b></div>`;

  const relText = state.release.mode === 'immediate'
    ? 'Score shown immediately on submission'
    : `Scheduled email on <b style="color:#fff;">${document.getElementById('releaseDate').value}</b>`;
  document.getElementById('reviewRelease').innerHTML = `<div>${relText}</div>`;

  const shortfalls = collectAllShortfalls();
  const banner = document.getElementById('shortfallBanner');
  const list = document.getElementById('shortfallList');
  const publishBtn = document.getElementById('publishBtn');
  const title = document.getElementById('publishTitle');
  const sub = document.getElementById('publishSub');

  if (shortfalls.length) {
    banner.style.display = 'block';
    list.innerHTML = shortfalls.map(s => `<li>⚠ ${s.label} — ${s.pool} in bank, ${s.required} needed (short by ${s.short})</li>`).join('');
    publishBtn.setAttribute('disabled', 'true');
    publishBtn.title = 'Resolve every shortfall first';
    title.textContent = 'Publish is blocked';
    sub.textContent = `${shortfalls.length} combination(s) still short of their approved-pool requirement.`;
  } else {
    banner.style.display = 'none';
    publishBtn.removeAttribute('disabled');
    publishBtn.title = '';
    title.textContent = 'Ready to publish';
    sub.textContent = 'Every required combination meets its approved-pool requirement.';
  }
}

function getSchedule() {
  const v = id => document.getElementById(id).value;
  return state.timeMode === 'fixed'
    ? { mode: 'fixed', date: v('testDate'), start: v('fixStart'), end: v('fixEnd'), name: v('testName') }
    : { mode: 'flex', date: v('testDate'), start: v('winOpen'), end: v('winClose'), limit: +v('timeLimit'), name: v('testName') };
}
function publishTest() {
  if (document.getElementById('publishBtn').hasAttribute('disabled')) return;
  AA.set('schedule', getSchedule());
  aToast('Aptitude test published — candidates can now log in within the scheduled window.');
  setTimeout(() => { window.location.href = 'monitor.html'; }, 900);
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

  document.getElementById('backBtn').disabled = currentStep === 1;
  const nextBtn = document.getElementById('nextBtn');
  if (currentStep === 4) { nextBtn.style.display = 'none'; }
  else { nextBtn.style.display = 'inline-flex'; nextBtn.innerHTML = STEP_LABELS[currentStep]; }

  if (currentStep === 1) renderStep1();
  if (currentStep === 2) renderStep2();
  if (currentStep === 4) renderStep4();
}

function validateStep(step) {
  if (step === 1) {
    if (state.selected.size === 0) { aToast(`Select at least one ${T().toLowerCase()} to continue.`, '⚠'); return false; }
    if (!document.getElementById('testName').value.trim()) { aToast('Give this test a name.', '⚠'); return false; }
    return true;
  }
  if (step === 2) {
    const empty = [...state.selected].find(f => (state.compositions[f] || []).length === 0);
    if (empty) { aToast(`${empty} needs at least one subject row.`, '⚠'); return false; }
    return true;
  }
  if (step === 3) {
    if (!document.getElementById('testDate').value) { aToast('Set the test date.', '⚠'); return false; }
    if (state.timeMode === 'fixed') {
      const a = document.getElementById('fixStart').value, b = document.getElementById('fixEnd').value;
      if (!a || !b || toMin(b) <= toMin(a)) { aToast('End time must be after the start time.', '⚠'); return false; }
    } else if (!document.getElementById('timeLimit').value || toMin(document.getElementById('winClose').value) <= toMin(document.getElementById('winOpen').value)) { aToast('Set a time limit and a valid window.', '⚠'); return false; }
    return true;
  }
  return true;
}

function wizNext() {
  if (!validateStep(currentStep)) return;
  if (currentStep < 4) { currentStep++; renderStep(); }
}
function wizBack() {
  if (currentStep > 1) { currentStep--; renderStep(); }
}

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => { document.getElementById('testName').addEventListener('input', () => nameDirty = true); renderStep(); }, 0); // wait one tick for admin-shell.js to inject the template content
});
