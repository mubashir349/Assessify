// ============================================================
// create-test.html — 4-step Aptitude Test creation wizard
// ============================================================

// ---- Reference data: this Institution's Fields, their subjects, and each
//      subject's currently APPROVED question-bank size (used for the live
//      sufficiency check). "shared: true" subjects draw from one Institution-
//      level pool, so their requirement is the MAX across Fields, not the sum
//      (SRS FR-4.14.17 / BR-26). ----
const FIELDS = {
  'Pre-Engineering': { candidates: 340, subjects: [
    { name: 'Mathematics', shared: false, pool: 48 },
    { name: 'Chemistry',   shared: false, pool: 40 },
    { name: 'Physics',     shared: false, pool: 40 },
    { name: 'English',     shared: true,  pool: 160 },
  ]},
  'Pre-Medical': { candidates: 298, subjects: [
    { name: 'Biology',   shared: false, pool: 7 },   // intentionally short, for the demo
    { name: 'Chemistry', shared: false, pool: 40 },
    { name: 'Physics',   shared: false, pool: 40 },
    { name: 'English',   shared: true,  pool: 160 },
  ]},
  'Computer Science': { candidates: 412, subjects: [
    { name: 'Mathematics',      shared: false, pool: 44 },
    { name: 'Computer Science', shared: false, pool: 48 },
    { name: 'Physics',          shared: false, pool: 40 },
    { name: 'English',          shared: true,  pool: 160 },
  ]},
  'Commerce': { candidates: 234, subjects: [
    { name: 'Accounting',    shared: false, pool: 38 },
    { name: 'General Math',  shared: false, pool: 40 },
    { name: 'English',       shared: true,  pool: 160 },
  ]},
};
const TYPES = ['MCQ', 'True/False'];
const DIFFICULTIES = ['Easy', 'Medium', 'Hard'];

// ---- Wizard state ----
let currentStep = 1;
let rowIdSeq = 1;
const state = {
  selectedFields: new Set(['Pre-Engineering', 'Pre-Medical', 'Computer Science']),
  activeTab: 'Pre-Engineering',
  compositions: {}, // { fieldName: [ {id, subject, type, difficulty, count} ] }
  release: { mode: 'scheduled' },
};

function defaultRowsFor(field) {
  const subjects = FIELDS[field].subjects;
  return subjects.map(s => ({
    id: rowIdSeq++,
    subject: s.name,
    type: 'MCQ',
    difficulty: s.name === 'Biology' ? 'Hard' : 'Medium',
    count: s.name === 'Biology' ? 10 : 15,
  }));
}
[...state.selectedFields].forEach(f => { state.compositions[f] = defaultRowsFor(f); });

// ---- Sufficiency logic ----
function subjectDef(field, subjectName) {
  return FIELDS[field].subjects.find(s => s.name === subjectName);
}

// For a shared subject, the required count for a given type/difficulty combo
// is the LARGEST count requested by any selected Field using that subject —
// not the sum — since every candidate still only draws their own Field's count.
function requiredFor(field, row) {
  const def = subjectDef(field, row.subject);
  if (!def.shared) return row.count;
  let max = row.count;
  state.selectedFields.forEach(f => {
    (state.compositions[f] || []).forEach(r => {
      if (r.subject === row.subject && r.type === row.type && r.difficulty === row.difficulty) {
        max = Math.max(max, r.count);
      }
    });
  });
  return max;
}

function rowStatus(field, row) {
  const def = subjectDef(field, row.subject);
  const required = requiredFor(field, row);
  const sufficient = def.pool >= required;
  return { sufficient, pool: def.pool, required, shared: def.shared };
}

function collectAllShortfalls() {
  const seen = new Set();
  const shortfalls = [];
  state.selectedFields.forEach(field => {
    (state.compositions[field] || []).forEach(row => {
      const st = rowStatus(field, row);
      const key = st.shared ? `SHARED::${row.subject}::${row.type}::${row.difficulty}` : `${field}::${row.subject}::${row.type}::${row.difficulty}`;
      if (!st.sufficient && !seen.has(key)) {
        seen.add(key);
        shortfalls.push({
          label: st.shared ? `${row.subject} (Shared) · ${row.type}, ${row.difficulty}` : `${field} → ${row.subject} · ${row.type}, ${row.difficulty}`,
          pool: st.pool, required: st.required,
        });
      }
    });
  });
  return shortfalls;
}

// ---- Step 1: Field selection ----
function renderStep1() {
  const wrap = document.getElementById('fieldToggleList');
  wrap.innerHTML = Object.keys(FIELDS).map(field => {
    const checked = state.selectedFields.has(field);
    return `
      <label class="field-toggle ${checked ? 'checked' : ''}" onclick="toggleField(event,'${field}')">
        <span><b style="color:#fff;">${field}</b> <span class="muted">· ${FIELDS[field].candidates} candidates</span></span>
        <input type="checkbox" ${checked ? 'checked' : ''} />
      </label>`;
  }).join('');
}

function toggleField(e, field) {
  e.preventDefault();
  if (state.selectedFields.has(field)) {
    state.selectedFields.delete(field);
    delete state.compositions[field];
  } else {
    state.selectedFields.add(field);
    if (!state.compositions[field]) state.compositions[field] = defaultRowsFor(field);
  }
  if (!state.selectedFields.has(state.activeTab)) {
    state.activeTab = [...state.selectedFields][0] || null;
  }
  renderStep1();
}

// ---- Step 2: Paper composition ----
function renderStep2() {
  const tabsEl = document.getElementById('fieldTabs');
  const fields = [...state.selectedFields];
  if (!fields.includes(state.activeTab)) state.activeTab = fields[0] || null;

  tabsEl.innerHTML = fields.map(f => {
    const hasShortfall = (state.compositions[f] || []).some(row => !rowStatus(f, row).sufficient);
    return `<div class="field-tab ${f === state.activeTab ? 'active' : ''}" onclick="switchFieldTab('${f}')">
      ${f}${hasShortfall ? '<span class="shortfall-dot"></span>' : ''}
    </div>`;
  }).join('');

  const area = document.getElementById('compositionArea');
  if (!state.activeTab) { area.innerHTML = '<div class="a-empty"><p>Select at least one Field in Step 1.</p></div>'; return; }

  const rows = state.compositions[state.activeTab] || [];
  const subjectOptions = FIELDS[state.activeTab].subjects.map(s => `<option value="${s.name}">${s.name}${s.shared ? ' (Shared)' : ''}</option>`).join('');

  area.innerHTML = `
    <div class="comp-table-head"><span>Subject</span><span>Type</span><span>Difficulty</span><span>Count</span><span>Status</span><span></span></div>
    <div id="compRows">
      ${rows.map(row => renderCompRow(state.activeTab, row, subjectOptions)).join('')}
    </div>
    <button class="a-btn a-btn-ghost a-btn-sm comp-add-row" onclick="addRow('${state.activeTab}')">+ Add row</button>
  `;
}

function renderCompRow(field, row, subjectOptions) {
  const st = rowStatus(field, row);
  const statusHtml = st.sufficient
    ? `<span class="badge badge-approved">Sufficient</span>`
    : `<span class="badge badge-draft">${st.pool} of ${st.required}</span>`;
  return `
    <div class="comp-row" data-row-id="${row.id}">
      <select class="a-select" onchange="updateRow('${field}',${row.id},'subject',this.value)">${subjectOptions.replace(`value="${row.subject}"`, `value="${row.subject}" selected`)}</select>
      <select class="a-select" onchange="updateRow('${field}',${row.id},'type',this.value)">${TYPES.map(t => `<option ${t === row.type ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <select class="a-select" onchange="updateRow('${field}',${row.id},'difficulty',this.value)">${DIFFICULTIES.map(d => `<option ${d === row.difficulty ? 'selected' : ''}>${d}</option>`).join('')}</select>
      <input class="a-input" type="number" min="1" value="${row.count}" onchange="updateRow('${field}',${row.id},'count',parseInt(this.value)||1)" />
      <span class="status-cell">${statusHtml}</span>
      <button class="rm-btn" onclick="removeRow('${field}',${row.id})" title="Remove row">✕</button>
    </div>`;
}

function switchFieldTab(field) { state.activeTab = field; renderStep2(); }

function updateRow(field, id, key, value) {
  const row = state.compositions[field].find(r => r.id === id);
  if (row) row[key] = value;
  renderStep2(); // re-render to refresh sufficiency across any shared-subject siblings too
}

function addRow(field) {
  const firstSubject = FIELDS[field].subjects[0].name;
  state.compositions[field].push({ id: rowIdSeq++, subject: firstSubject, type: 'MCQ', difficulty: 'Medium', count: 10 });
  renderStep2();
}

function removeRow(field, id) {
  state.compositions[field] = state.compositions[field].filter(r => r.id !== id);
  renderStep2();
}

// ---- Step 3: Schedule & release ----
function setRelease(mode) {
  state.release.mode = mode;
  document.getElementById('relImmediate').classList.toggle('sel', mode === 'immediate');
  document.getElementById('relScheduled').classList.toggle('sel', mode === 'scheduled');
  document.getElementById('relDateField').style.display = mode === 'immediate' ? 'none' : 'flex';
}

// ---- Step 4: Review & publish ----
function renderStep4() {
  const reviewFields = document.getElementById('reviewFields');
  reviewFields.innerHTML = [...state.selectedFields].map(field => {
    const rows = state.compositions[field] || [];
    const rowsHtml = rows.map(row => {
      const st = rowStatus(field, row);
      const statusHtml = st.sufficient ? `<span class="badge badge-approved">Sufficient</span>` : `<span class="badge badge-draft">${st.pool} of ${st.required}</span>`;
      return `<tr><td>${row.subject}${st.shared ? ' <span class="a-chip shared" style="padding:2px 7px;font-size:10px;">Shared</span>' : ''}</td><td>${row.type}</td><td>${row.difficulty}</td><td>${row.count}</td><td>${statusHtml}</td></tr>`;
    }).join('');
    return `
      <div class="a-card review-field-card">
        <div class="review-field-head"><h3>${field}</h3><span class="muted">${FIELDS[field].candidates} candidates</span></div>
        <div class="a-table-wrap"><table class="a-table">
          <thead><tr><th>Subject</th><th>Type</th><th>Difficulty</th><th>Count</th><th>Status</th></tr></thead>
          <tbody>${rowsHtml || '<tr><td colspan="5" class="muted">No subjects configured.</td></tr>'}</tbody>
        </table></div>
      </div>`;
  }).join('');

  const timeLimit = document.getElementById('timeLimit').value;
  const testDate = document.getElementById('testDate').value;
  const winOpen = document.getElementById('winOpen').value;
  const winClose = document.getElementById('winClose').value;
  document.getElementById('reviewSchedule').innerHTML = `
    <div>Time limit: <b style="color:#fff;">${timeLimit} minutes</b></div>
    <div>Date: <b style="color:#fff;">${testDate}</b></div>
    <div>Window: <b style="color:#fff;">${winOpen} – ${winClose}</b></div>`;

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
    list.innerHTML = shortfalls.map(s => `<li>⚠ ${s.label} — ${s.pool} of ${s.required} approved</li>`).join('');
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

function publishTest() {
  if (document.getElementById('publishBtn').hasAttribute('disabled')) return;
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
    if (state.selectedFields.size === 0) { aToast('Select at least one Field to continue.', '⚠'); return false; }
    if (!document.getElementById('testName').value.trim()) { aToast('Give this test a name.', '⚠'); return false; }
    return true;
  }
  if (step === 2) {
    const empty = [...state.selectedFields].find(f => (state.compositions[f] || []).length === 0);
    if (empty) { aToast(`${empty} needs at least one subject row.`, '⚠'); return false; }
    return true;
  }
  if (step === 3) {
    if (!document.getElementById('timeLimit').value || !document.getElementById('testDate').value) { aToast('Set a time limit and test date.', '⚠'); return false; }
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
  setTimeout(renderStep, 0); // wait one tick for admin-shell.js to inject the template content
});
