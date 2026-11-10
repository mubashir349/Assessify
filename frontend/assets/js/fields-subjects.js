// fields-subjects.html — fields / departments are stored in the database through the API.
// Level names, "Field" vs "Department" wording and assessment modes all come from GET /meta.
let META = null, DEPTS = [], editId = null, tags = [], searchTimer;
const $ = id => document.getElementById(id);
const levelInfo = v => (META.levels.find(l => l.value === v) || META.levels[0]);
const term = v => levelInfo(v).term;

function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }
function firstError(ex) { const d = ex.details && Object.values(ex.details)[0]; return d || ex.message; }

function renderTags() {
  const box = $('tagBox'), inp = $('tagInput');
  box.querySelectorAll('.a-chip').forEach(c => c.remove());
  tags.forEach((t, i) => { const c = document.createElement('span'); c.className = 'a-chip'; c.innerHTML = `${esc(t)}<button onclick="tags.splice(${i},1);renderTags()" aria-label="Remove"><i data-icon="x"></i></button>`; inp.before(c); });
}
function lvlChange() {
  const info = levelInfo($('dLevel').value), t = info.term;
  $('nameLbl').textContent = t + ' name';
  $('dName').placeholder = info.name_placeholder;
  $('mTitle').textContent = (editId ? 'Edit ' : 'New ') + t.toLowerCase();
}
function openDeptModal(id) {
  editId = id || null;
  const d = id ? DEPTS.find(x => x.id === id) : null;
  $('dName').value = d ? d.name : '';
  $('dLevel').value = d ? d.level : META.defaults.level;
  document.querySelectorAll('input[name=dmode]').forEach(r => r.checked = r.value === (d ? d.mode : META.defaults.mode));
  tags = d ? [...d.subjects] : []; renderTags(); lvlChange();
  if (!d) $('mTitle').textContent = 'New department / field';
  openModal('fieldModal');
}
async function saveDept() {
  const level = $('dLevel').value, name = $('dName').value.trim();
  if (!name) return aToast('Enter a ' + term(level).toLowerCase() + ' name.', 'warn');
  const pending = $('tagInput').value.trim();                   // a subject typed but not yet confirmed with Enter
  if (pending && !tags.includes(pending)) tags.push(pending);
  $('tagInput').value = '';
  if (!tags.length) return aToast('Add at least one subject.', 'warn');
  const body = { name, level, mode: document.querySelector('input[name=dmode]:checked').value, subjects: [...tags] };
  const btn = $('saveBtn'); btn.disabled = true;
  try {
    const { department } = editId
      ? await api('/departments/' + editId, { method: 'PUT', body })
      : await api('/departments', { method: 'POST', body });
    closeModal('fieldModal'); await loadDepts(); aToast(department.term + ' saved.');
    if (typeof AA !== 'undefined' && AA.syncDepts) AA.syncDepts().catch(() => {});
  } catch (ex) { aToast(firstError(ex), 'warn'); }
  btn.disabled = false;
}
async function delDept(id) {
  if (!confirm('Delete this field / department?')) return;
  try { await api('/departments/' + id, { method: 'DELETE' }); await loadDepts(); aToast('Deleted.'); if (typeof AA !== 'undefined' && AA.syncDepts) AA.syncDepts().catch(() => {}); }
  catch (ex) { aToast(ex.message, 'warn'); }
}

async function loadDepts() {
  const params = new URLSearchParams();
  if ($('lvlFilter').value) params.set('level', $('lvlFilter').value);
  if ($('dSearch').value.trim()) params.set('q', $('dSearch').value.trim());
  try {
    DEPTS = (await api('/departments' + (params.toString() ? '?' + params : ''))).items;
    renderDepts();
  } catch (ex) {
    $('deptGrid').innerHTML = `<div class="a-card a-empty" style="color:var(--danger-text);">${esc(ex.message)}</div>`;
  }
}
function renderDepts() {
  $('deptGrid').innerHTML = DEPTS.map(d => `
    <div class="a-card field-card">
      <div class="field-card-head">
        <div><h3>${esc(d.name)}</h3><p class="muted">${d.subject_count} subjects · ${esc(d.level)} ${esc(d.term.toLowerCase())} · ${esc(META.modes.find(m => m.value === d.mode)?.label || d.mode)}</p></div>
        <div style="display:flex;gap:6px;"><button class="a-btn a-btn-ghost a-btn-sm" onclick="openDeptModal(${d.id})">Edit</button><button class="a-btn a-btn-danger a-btn-sm" onclick="delDept(${d.id})" aria-label="Delete"><i data-icon="trash"></i></button></div>
      </div>
      <div class="subj-list">${d.subjects.map(s => `<span class="a-chip">${esc(s)}</span>`).join('')}</div>
    </div>`).join('') || '<div class="a-card a-empty">Nothing here yet — click “New Field / Department”.</div>';
}

document.addEventListener('DOMContentLoaded', async () => {
  try { META = await loadMeta(); }
  catch (ex) { $('deptGrid').innerHTML = `<div class="a-card a-empty" style="color:var(--danger-text);">${esc(ex.message)}</div>`; return; }

  fillSelect($('lvlFilter'), META.levels.map(l => l.value), { keepFirst: true });
  fillSelect($('dLevel'), META.levels.map(l => l.value));
  $('modeSeg').innerHTML = META.modes.map(m => `<label><input type="radio" name="dmode" value="${esc(m.value)}" ${m.value === META.defaults.mode ? 'checked' : ''} /> ${esc(m.label)}<br/><span class="muted">${esc(m.description)}</span></label>`).join('');

  $('lvlFilter').addEventListener('change', loadDepts);
  $('dSearch').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadDepts, 250); });
  document.addEventListener('keydown', e => {
    if (e.target.id === 'tagInput' && e.key === 'Enter') { e.preventDefault(); const v = e.target.value.trim(); if (v && !tags.includes(v)) tags.push(v); e.target.value = ''; renderTags(); }
  });
  void loadDepts();                     // shows its own errors
});
