// fields-subjects.html — fully dynamic departments (stored in AA store)
let editId = null, tags = [];
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function renderTags() {
  const box = document.getElementById('tagBox'), inp = document.getElementById('tagInput');
  box.querySelectorAll('.a-chip').forEach(c => c.remove());
  tags.forEach((t, i) => { const c = document.createElement('span'); c.className = 'a-chip'; c.innerHTML = `${AA.esc(t)}<button onclick="tags.splice(${i},1);renderTags()">✕</button>`; box.insertBefore(c, inp); });
}
function lvlChange() {
  const t = AA.term(document.getElementById('dLevel').value);
  document.getElementById('nameLbl').textContent = t + ' name';
  document.getElementById('dName').placeholder = t === 'Field' ? 'e.g. Pre-Engineering, Commerce' : 'e.g. Data Science, Physics';
  document.getElementById('mTitle').textContent = (editId ? 'Edit ' : 'New ') + t.toLowerCase();
}
function openDeptModal(id) {
  editId = id || null;
  const d = id ? AA.depts().find(x => x.id === id) : null;
  document.getElementById('mTitle').textContent = d ? 'Edit department' : 'New department / field';
  document.getElementById('dName').value = d ? d.name : '';
  document.getElementById('dLevel').value = d ? d.level : 'Undergraduate';
  document.querySelectorAll('input[name=dmode]').forEach(r => r.checked = r.value === (d ? d.mode : 'field'));
  tags = d ? [...d.subjects] : []; renderTags(); lvlChange(); openModal('fieldModal');
}
function saveDept() {
  const name = document.getElementById('dName').value.trim();
  if (!name) return aToast('Enter a ' + AA.term(document.getElementById('dLevel').value).toLowerCase() + ' name.', '⚠');
  if (!tags.length) return aToast('Add at least one subject.', '⚠');
  const d = { id: editId || AA.uid(), name, level: document.getElementById('dLevel').value, mode: document.querySelector('input[name=dmode]:checked').value, subjects: [...tags] };
  const all = AA.depts(); const i = all.findIndex(x => x.id === d.id);
  i >= 0 ? all[i] = d : all.push(d);
  AA.saveDepts(all); closeModal('fieldModal'); renderDepts(); aToast(AA.term(d.level) + ' saved.');
}
function delDept(id) { if (!confirm('Delete this field / department?')) return; AA.saveDepts(AA.depts().filter(d => d.id !== id)); renderDepts(); }
function renderDepts() {
  const lv = document.getElementById('lvlFilter').value, q = document.getElementById('dSearch').value.toLowerCase();
  const list = AA.depts().filter(d => (!lv || d.level === lv) && d.name.toLowerCase().includes(q));
  document.getElementById('deptGrid').innerHTML = list.map(d => `
    <div class="a-card field-card">
      <div class="field-card-head">
        <div><h3>${AA.esc(d.name)}</h3><p class="muted">${d.subjects.length} subjects · ${d.level} ${AA.term(d.level).toLowerCase()} · ${d.mode === 'general' ? 'General test' : 'Specific'}</p></div>
        <div style="display:flex;gap:6px;"><button class="a-btn a-btn-ghost a-btn-sm" onclick="openDeptModal('${d.id}')">Edit</button><button class="a-btn a-btn-danger a-btn-sm" onclick="delDept('${d.id}')">✕</button></div>
      </div>
      <div class="subj-list">${d.subjects.map(s => `<span class="a-chip">${AA.esc(s)}</span>`).join('')}</div>
    </div>`).join('') || '<div class="a-card a-empty">Nothing here yet — click “New Field / Department”.</div>';
}
document.addEventListener('DOMContentLoaded', () => {
  renderDepts();
  document.addEventListener('keydown', e => {
    if (e.target.id === 'tagInput' && e.key === 'Enter') { e.preventDefault(); const v = e.target.value.trim(); if (v && !tags.includes(v)) tags.push(v); e.target.value = ''; renderTags(); }
  });
});
