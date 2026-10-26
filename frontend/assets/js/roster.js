// roster.html — candidate roster of one published test, stored in the database through the API (Phase 5).
// Flow: pick a test → drop a CSV → the server checks it (dry run) → "Import N" saves the good rows → roster table.
let TESTS = [], TEST = null, page = 1, searchTimer, pendingFile = null, editId = null;
const PER_PAGE = 50;
const $ = id => document.getElementById(id);
const term = () => (TEST && TEST.term) || 'Field';
function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }
function plural(n, w) { return `${n} ${w}${n === 1 ? '' : 's'}`; }

function toggleReveal(el, real) {
  const masked = el.dataset.masked || el.textContent;
  el.dataset.masked = masked;
  if (el.classList.contains('shown')) { el.textContent = masked; el.classList.remove('shown'); }
  else { el.textContent = real; el.classList.add('shown'); }
}

// CSV downloads go through fetch so the login cookie is sent and an error shows as a toast, not a JSON page.
async function download(path, fallbackName) {
  try {
    const res = await fetch(API_BASE + path, { credentials: 'include' });
    if (!res.ok) {
      let msg = 'Download failed.';
      try { msg = (await res.json()).error.message; } catch (e) { /* not JSON */ }
      if (res.status === 401) return window.location.replace('../institution-login.html');
      return aToast(esc(msg), '⚠');
    }
    const name = (/filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '') || [])[1] || fallbackName;
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { aToast('Cannot reach the server. Is the backend running?', '⚠'); }
}

// ---------------------------------------------------------------- tests
async function loadTests() {
  try {
    const [{ items }, { counts }] = await Promise.all([api('/tests?status=published'), api('/roster/counts')]);
    TESTS = items.map(t => ({ ...t, candidates: counts[String(t.id)] || 0 }));
  } catch (e) { return handleApiError(e); }
  if (!TESTS.length) { $('noTests').hidden = false; return; }
  const want = new URLSearchParams(location.search).get('test') || (() => { try { return sessionStorage.getItem('aa_roster_test'); } catch (e) { return null; } })();
  $('testSel').innerHTML = TESTS.map(t => `<option value="${t.id}">${esc(t.name)} · ${esc(t.level)} · ${plural(t.candidates, 'candidate')}</option>`).join('');
  if (want && TESTS.some(t => String(t.id) === String(want))) $('testSel').value = want;
  $('testSel').addEventListener('change', selectTest);
  selectTest();
}

function fmtWhen(iso) {
  return iso ? new Date(iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : '';
}

function selectTest() {
  TEST = TESTS.find(t => String(t.id) === $('testSel').value);
  try { sessionStorage.setItem('aa_roster_test', String(TEST.id)); } catch (e) {}
  const sc = TEST.schedule;
  $('testMeta').innerHTML = sc ? `${sc.timing_mode === 'fixed' ? 'Fixed time' : 'Flexible window'}<br/><b style="color:#fff;">${esc(fmtWhen(sc.starts_at))}</b> – ${esc(fmtWhen(sc.ends_at))}` : '';
  $('rosterArea').hidden = false; $('exportBtn').hidden = false; $('addBtn').hidden = false;
  $('deptHead').textContent = term(); $('cDeptLbl').textContent = term();
  $('deptFilter').innerHTML = `<option value="">All ${term() === 'Field' ? 'fields' : 'departments'}</option>` +
    TEST.departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  fillSelect($('cDept'), TEST.departments.map(d => ({ value: d.id, label: d.name })));
  $('importBox').hidden = true; pendingFile = null; page = 1;
  loadRoster();
}

// ---------------------------------------------------------------- roster table
async function loadRoster() {
  const qs = new URLSearchParams({ test_id: TEST.id, page, per_page: PER_PAGE });
  if ($('deptFilter').value) qs.set('department_id', $('deptFilter').value);
  if ($('search').value.trim()) qs.set('q', $('search').value.trim());
  let d;
  try { d = await api('/roster?' + qs); } catch (e) { return handleApiError(e); }
  const s = d.summary;
  TEST.candidates = s.total;
  const opt = $('testSel').selectedOptions[0];
  if (opt) opt.textContent = `${TEST.name} · ${TEST.level} · ${plural(s.total, 'candidate')}`;
  $('rosterTitle').textContent = `Roster (${s.total})`;
  $('deptChips').innerHTML = s.total ? s.by_department.map(x => `<span class="a-chip">${esc(x.name)} · ${x.count}</span>`).join('') +
    `<span class="a-chip">Signed in · ${s.logged_in}</span>` : '';
  $('rosterRows').innerHTML = d.items.map(c => `
    <tr>
      <td class="name">${esc(c.full_name)}</td><td class="mono">${esc(c.roll_number)}</td><td>${esc(c.email)}</td>
      <td><span class="a-chip">${esc(c.department.name)}</span></td>
      <td class="mono reveal" data-real="${esc(c.access_code)}">••••-••••</td>
      <td class="mono reveal" data-real="${esc(new Date(c.date_of_birth + 'T00:00:00').toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' }))}">••-•••-••••</td>
      <td class="muted" style="font-size:12px;">${c.last_login_at ? esc(fmtWhen(c.last_login_at)) : '—'}</td>
      <td style="white-space:nowrap;">
        <button class="a-btn a-btn-ghost a-btn-sm" onclick="openCandModal(${c.id})">Correct</button>
        <button class="a-btn a-btn-ghost a-btn-sm" onclick="newCode(${c.id})" title="Issue a new access code (the old one stops working)">New code</button>
        <button class="a-btn a-btn-danger a-btn-sm" onclick="removeCand(${c.id})" title="Remove from roster">✕</button>
      </td>
    </tr>`).join('') ||
    `<tr><td colspan="8" class="a-empty">${s.total ? 'No candidate matches the search.' : 'No candidates yet — drop the roster CSV above or click “Add candidate”.'}</td></tr>`;
  window.ROWS = d.items;
  $('pager').innerHTML = d.pages > 1 ? `<div class="pager">
    <button class="a-btn a-btn-ghost a-btn-sm" ${d.page <= 1 ? 'disabled' : ''} onclick="page--;loadRoster()">← Prev</button>
    <span>Page ${d.page} of ${d.pages} · ${plural(d.total, 'candidate')}</span>
    <button class="a-btn a-btn-ghost a-btn-sm" ${d.page >= d.pages ? 'disabled' : ''} onclick="page++;loadRoster()">Next →</button></div>` : '';
}

// ---------------------------------------------------------------- CSV import (check first, then save)
async function sendCsv(file, dryRun) {
  const fd = new FormData();
  fd.append('test_id', TEST.id); fd.append('file', file);
  if (dryRun) fd.append('dry_run', '1');
  return api('/roster/import', { method: 'POST', body: fd });
}

function showResult(d, file) {
  $('importBox').hidden = false;
  const n = d.dry_run ? d.would_import : d.imported;
  $('okLbl').textContent = d.dry_run ? 'Ready to import' : 'Imported successfully';
  $('okNum').textContent = n; $('errNum').textContent = d.error_count; $('genNum').textContent = d.codes_generated;
  $('previewBar').hidden = !d.dry_run;
  if (d.dry_run) {
    $('previewFile').textContent = file.name;
    $('previewText').textContent = `${plural(d.total_rows, 'row')} checked · ${n} ready · ${d.error_count} need fixing. Nothing is saved until you click Import.`;
    $('confirmBtn').textContent = n ? `Import ${plural(n, 'candidate')}` : 'Nothing to import';
    $('confirmBtn').disabled = !n;
  }
  $('errCard').hidden = !d.error_count;
  $('errTitle').textContent = `Rows that need fixing (${d.error_count})`;
  $('errRows').innerHTML = d.errors.map(e => `
    <tr><td class="mono">#${e.row}</td><td class="name">${esc(e.full_name || '—')}</td><td class="mono">${esc(e.roll_number || '—')}</td>
    <td style="color:#f87171;">${e.issues.map(esc).join('<br/>')}</td></tr>`).join('');
}

async function pickFile(file) {
  if (!file || !TEST) return;
  pendingFile = file;
  $('drop').classList.add('busy');
  try { showResult(await sendCsv(file, true), file); }
  catch (e) { pendingFile = null; $('importBox').hidden = true; handleApiError(e); }
  $('drop').classList.remove('busy');
  $('csvFile').value = '';
}

async function confirmImport() {
  if (!pendingFile) return;
  const btn = $('confirmBtn'); btn.disabled = true;
  try {
    const d = await sendCsv(pendingFile, false);
    showResult(d, pendingFile); pendingFile = null;
    aToast(`${plural(d.imported, 'candidate')} imported${d.error_count ? ` · ${d.error_count} row(s) need fixing` : ''}.`);
    page = 1; loadRoster();
  } catch (e) { handleApiError(e); btn.disabled = false; }
}
function cancelPreview() { pendingFile = null; $('importBox').hidden = true; }

// ---------------------------------------------------------------- add / correct / new code / remove
function openCandModal(id) {
  editId = id || null;
  const c = id ? window.ROWS.find(x => x.id === id) : null;
  $('cTitle').textContent = c ? 'Correct candidate' : 'Add candidate';
  $('cSub').textContent = c ? 'To change the access code use “New code”.' : 'An access code is generated automatically if you leave it empty.';
  $('cName').value = c ? c.full_name : ''; $('cEmail').value = c ? c.email : '';
  $('cRoll').value = c ? c.roll_number : ''; $('cDob').value = c ? c.date_of_birth : '';
  $('cDept').value = c ? c.department.id : (TEST.departments[0] || {}).id;
  $('cCode').value = ''; $('cCodeField').hidden = !!c;
  $('cErr').style.display = 'none';
  openModal('candModal');
}

async function saveCand() {
  const body = { full_name: $('cName').value, email: $('cEmail').value, roll_number: $('cRoll').value,
                 date_of_birth: $('cDob').value, department_id: Number($('cDept').value) };
  if (!editId) { body.test_id = TEST.id; if ($('cCode').value.trim()) body.access_code = $('cCode').value.trim(); }
  const btn = $('cSave'); btn.disabled = true;
  try {
    const { candidate } = editId ? await api('/roster/' + editId, { method: 'PUT', body })
                                 : await api('/roster', { method: 'POST', body });
    closeModal('candModal');
    aToast(editId ? 'Candidate corrected.' : `Added · access code ${esc(candidate.access_code)}`);
    loadRoster();
  } catch (e) {
    if (e.status === 401) return handleApiError(e);
    const msgs = e.details ? Object.values(e.details).filter(v => typeof v === 'string') : [];
    $('cErr').innerHTML = (msgs.length ? msgs : [e.message]).map(esc).join('<br/>');
    $('cErr').style.display = 'block';
  }
  btn.disabled = false;
}

async function newCode(id) {
  const c = window.ROWS.find(x => x.id === id);
  if (!confirm(`Issue a new access code for ${c.full_name}? The old code stops working immediately (use this for a lost slip).`)) return;
  try { const { candidate } = await api(`/roster/${id}/new-code`, { method: 'POST' }); aToast(`New code for ${esc(candidate.full_name)}: ${esc(candidate.access_code)}`); loadRoster(); }
  catch (e) { handleApiError(e); }
}

async function removeCand(id) {
  const c = window.ROWS.find(x => x.id === id);
  if (!confirm(`Remove ${c.full_name} (${c.roll_number}) from this roster? Their access code stops working.`)) return;
  try { await api('/roster/' + id, { method: 'DELETE' }); aToast('Removed.'); loadRoster(); }
  catch (e) { handleApiError(e); }
}

// ---------------------------------------------------------------- wiring
document.addEventListener('admin:ready', () => {
  $('templateBtn').addEventListener('click', e => { e.preventDefault(); download('/roster/template.csv', 'roster-template.csv'); });
  $('exportBtn').addEventListener('click', e => { e.preventDefault(); if (TEST) download('/roster/export.csv?test_id=' + TEST.id, 'roster.csv'); });
  $('csvFile').addEventListener('change', e => pickFile(e.target.files[0]));
  const drop = $('drop');
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => pickFile(e.dataTransfer.files[0]));
  $('rosterRows').addEventListener('click', e => { const el = e.target.closest('.reveal'); if (el) toggleReveal(el, el.dataset.real); });
  $('deptFilter').addEventListener('change', () => { page = 1; loadRoster(); });
  $('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page = 1; loadRoster(); }, 250); });
  loadTests();
});
