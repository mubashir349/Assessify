// roster.html — candidate roster of one published test, stored in the database through the API (Phase 5).
// Flow: pick a test → drop a CSV / Excel file → the server checks it (dry run) → "Import N" saves the good rows → roster table.
// Phase 9: lenient import (name + email / phone / roll number), warnings, skipped rows, errors.csv, updated list, slips.
let TESTS = [], TEST = null, page = 1, searchTimer, pendingFile = null, editId = null, lastResult = null;
const PER_PAGE = 50;
const $ = id => document.getElementById(id);
const term = () => TEST?.term || 'Field';
function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }
function plural(n, w) { return `${n} ${w}${n === 1 ? '' : 's'}`; }

function toggleReveal(el, real) {
  const masked = el.dataset.masked || el.textContent;
  el.dataset.masked = masked;
  if (el.classList.contains('shown')) { el.textContent = masked; el.classList.remove('shown'); }
  else { el.textContent = real; el.classList.add('shown'); }
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
  try { sessionStorage.setItem('aa_roster_test', String(TEST.id)); } catch (e) { /* storage blocked: only the remembered test is lost */ }
  const sc = TEST.schedule;
  const mode = sc?.timing_mode === 'fixed' ? 'Fixed time' : 'Flexible window';
  $('testMeta').innerHTML = sc ? `${mode}<br/><b style="color:var(--text);">${esc(fmtWhen(sc.starts_at))}</b> – ${esc(fmtWhen(sc.ends_at))}` : '';
  $('rosterArea').hidden = false; $('exportBtn').hidden = false; $('addBtn').hidden = false; $('slipsBtn').hidden = false;
  const slipsUrl = 'roster-slips.html?test_id=' + encodeURIComponent(TEST.id);
  $('slipsBtn').href = slipsUrl; $('slipsBtn2').href = slipsUrl;
  $('gTerm').textContent = term();
  $('gDepts').innerHTML = TEST.departments.map(d => `<b>${esc(d.name)}</b>`).join(', ');
  $('deptHead').textContent = term(); $('cDeptLbl').textContent = term();
  $('deptFilter').innerHTML = `<option value="">All ${term() === 'Field' ? 'fields' : 'departments'}</option>` +
    TEST.departments.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  fillSelect($('cDept'), TEST.departments.map(d => ({ value: d.id, label: d.name })));
  $('importBox').hidden = true; pendingFile = null; page = 1;
  void loadRoster();
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
      <td class="name">${esc(c.full_name)}</td><td class="mono">${esc(c.roll_number || '—')}</td>
      <td>${esc(c.email || '')}${c.phone ? `<span class="mon-sub mono">${esc(c.phone)}</span>` : ''}${!c.email && !c.phone ? '<span class="muted">—</span>' : ''}</td>
      <td><span class="a-chip">${esc(c.department.name)}</span></td>
      <td class="mono reveal" data-real="${esc(c.access_code)}">••••-••••</td>
      ${c.login_with === 'pin'
        ? `<td class="mono reveal" data-real="PIN ${esc(c.pin)}" title="No date of birth: signs in with this PIN">PIN ••••••</td>`
        : `<td class="mono reveal" data-real="${esc(new Date(c.date_of_birth + 'T00:00:00').toLocaleDateString([], { day: '2-digit', month: 'short', year: 'numeric' }))}">••-•••-••••</td>`}
      <td class="muted" style="font-size:12px;">${c.last_login_at ? esc(fmtWhen(c.last_login_at)) : '—'}${attemptCell(c.attempt)}</td>
      <td style="white-space:nowrap;">
        ${c.attempt?.status === 'locked' ? `<button class="a-btn a-btn-primary a-btn-sm" onclick="unlockAttempt(${c.attempt.id})" title="${esc(c.attempt.reference)}">Unlock</button>` : ''}
        <button class="a-btn a-btn-ghost a-btn-sm" onclick="openCandModal(${c.id})">Correct</button>
        <button class="a-btn a-btn-ghost a-btn-sm" onclick="newCode(${c.id})" title="Issue a new access code (the old one stops working)">New code</button>
        ${c.attempt ? '' : `<button class="a-btn a-btn-danger a-btn-sm" onclick="removeCand(${c.id})" title="Remove from roster" aria-label="Remove from roster"><i data-icon="trash"></i></button>`}
      </td>
    </tr>`).join('') ||
    `<tr><td colspan="8" class="a-empty">${s.total ? 'No candidate matches the search.' : 'No candidates yet — drop the roster CSV above or click “Add candidate”.'}</td></tr>`;
  window.ROWS = d.items;
  $('pager').innerHTML = pagerHtml(d);
}

function pagerHtml(d) {
  if (d.pages <= 1) return '';
  const prevDis = d.page <= 1 ? 'disabled' : '', nextDis = d.page >= d.pages ? 'disabled' : '';
  return `<div class="pager">
    <button class="a-btn a-btn-ghost a-btn-sm" ${prevDis} onclick="page--;loadRoster()"><i data-icon="arrow-left"></i> Prev</button>
    <span>Page ${d.page} of ${d.pages} · ${plural(d.total, 'candidate')}</span>
    <button class="a-btn a-btn-ghost a-btn-sm" ${nextDis} onclick="page++;loadRoster()">Next <i data-icon="arrow-right"></i></button></div>`;
}

// ---------------------------------------------------------------- Phase 6: test status + unlock (Phase 7 adds the live monitor)
function attemptCell(a) {
  if (!a) return '';
  const score = a.score === null ? '' : ` · ${a.score}/${a.max_score}`;
  const label = { in_progress: '<span style="color:var(--accent-text);">Taking the test</span>',
                  locked: '<span style="color:var(--danger-text);"><i data-icon="lock"></i> Locked</span>',
                  submitted: `<span style="color:var(--success-text);">Submitted${score}</span>` }[a.status] || esc(a.status);
  return `<br/>${label}`;
}

async function unlockAttempt(id) {
  try {
    await api(`/attempts/${id}/unlock`, { method: 'POST' });
    aToast('Unlocked. The candidate can continue after entering fullscreen again.', 'check');
  } catch (e) { handleApiError(e); }
  await loadRoster();
}

// ---------------------------------------------------------------- import (check first, then save)
async function sendCsv(file, dryRun) {
  const fd = new FormData();
  fd.append('test_id', TEST.id); fd.append('file', file);
  if (dryRun) fd.append('dry_run', '1');
  return api('/roster/import', { method: 'POST', body: fd });
}

function rowsHtml(list, key, color) {
  return list.map(e => `
    <tr><td class="mono">#${e.row}</td><td class="name">${esc(e.full_name || '—')}</td><td class="mono">${esc(e.roll_number || '—')}</td>
    <td style="color:${color};">${(key === 'reason' ? [e.reason] : e.issues).map(esc).join('<br/>')}</td></tr>`).join('');
}

function summaryLines(d) {
  const s = d.summary, n = d.dry_run ? d.would_import : d.imported, will = d.dry_run ? 'will get' : 'got';
  const lines = [];
  if (n) {
    lines.push(`${plural(n, 'candidate')} ${will} an access code (${d.codes_generated} made by the system).`);
    lines.push(`${s.login_with_dob} sign in with their date of birth · ${s.login_with_pin} with a new 6-digit PIN (printed on the slip).`);
    const missing = [s.missing_email && `${s.missing_email} without email (no result email)`,
                     s.missing_phone && `${s.missing_phone} without phone`,
                     s.missing_roll && `${s.missing_roll} without roll number`].filter(Boolean);
    if (missing.length) lines.push('Missing: ' + missing.join(' · ') + '.');
  }
  if (d.skipped_count) lines.push(`${plural(d.skipped_count, 'row')} already on the roster: skipped, nothing changed for them.`);
  (d.file_warnings || []).forEach(w => lines.push(w));
  if (!n && !d.skipped_count && d.error_count) lines.push('No row can be imported yet. Fix the rows below and upload again.');
  return lines;
}

function showResult(d, file) {
  lastResult = d;
  $('importBox').hidden = false;
  const n = d.dry_run ? d.would_import : d.imported;
  $('okLbl').textContent = d.dry_run ? 'Ready to import' : 'Imported successfully';
  $('okNum').textContent = n; $('errNum').textContent = d.error_count;
  $('warnNum').textContent = d.warning_count; $('skipNum').textContent = d.skipped_count;
  $('summaryList').innerHTML = summaryLines(d).map(l => `<li>${esc(l)}</li>`).join('');
  $('afterActions').hidden = d.dry_run;
  $('errCsvBtn').hidden = !d.error_count;
  $('previewBar').hidden = !d.dry_run;
  if (d.dry_run) {
    $('previewFile').textContent = file.name;
    $('previewText').textContent = `${plural(d.total_rows, 'row')} checked · ${n} ready · ${d.error_count} need fixing · ${d.warning_count} with warnings · ${d.skipped_count} already on the roster. Nothing is saved until you click Import.`;
    $('confirmBtn').textContent = n ? `Import ${plural(n, 'candidate')}` : 'Nothing to import';
    $('confirmBtn').disabled = !n;
  }
  $('errCard').hidden = !d.error_count;
  $('errTitle').textContent = `Rows that need fixing (${d.error_count})`;
  $('errRows').innerHTML = rowsHtml(d.errors, 'issues', 'var(--danger-text)');
  $('warnCard').hidden = !d.warning_count;
  $('warnTitle').textContent = `Warnings (${d.warning_count})`;
  $('warnRows').innerHTML = rowsHtml(d.warnings, 'issues', 'var(--warn-text)');
  $('skipCard').hidden = !d.skipped_count;
  $('skipTitle').textContent = `Already on the roster (${d.skipped_count})`;
  $('skipRows').innerHTML = rowsHtml(d.skipped, 'reason', 'var(--text-2)');
}

// errors.csv: the bad rows exactly as they were in the file, plus a "problem" column. Fix and upload it as it is:
// the "problem" column is ignored and rows already imported are skipped.
function csvCell(v) {
  const t = String(v ?? '');
  return /[",\n\r]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
}
function downloadErrors() {
  const d = lastResult;
  if (!d || !d.error_count) return;
  const lines = [[...d.header, 'problem'], ...d.errors.map(e => {
    const cells = d.header.map((_, i) => e.cells[i] ?? '');
    return [...cells, e.issues.join(' ')];
  })].map(r => r.map(csvCell).join(','));
  const blob = new Blob(['\ufeff' + lines.join('\r\n') + '\r\n'], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = 'errors.csv';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
function downloadUpdated() {
  if (TEST) void downloadFile('/roster/export.csv?test_id=' + TEST.id, 'roster.csv');
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
    const fixNote = d.error_count ? ` · ${d.error_count} row(s) need fixing` : '';
    aToast(`${plural(d.imported, 'candidate')} imported${fixNote}.`);
    page = 1; await loadRoster();
  } catch (e) { handleApiError(e); btn.disabled = false; }
}
function cancelPreview() { pendingFile = null; $('importBox').hidden = true; }

// ---------------------------------------------------------------- add / correct / new code / remove
function openCandModal(id) {
  editId = id || null;
  const c = id ? window.ROWS.find(x => x.id === id) : null;
  $('cTitle').textContent = c ? 'Correct candidate' : 'Add candidate';
  $('cSub').textContent = c ? 'To change the access code use “New code”. Removing the date of birth gives a PIN.'
                            : 'Name + at least one of email, phone or roll number. An access code is generated automatically.';
  $('cName').value = c ? c.full_name : ''; $('cEmail').value = c?.email || ''; $('cPhone').value = c?.phone || '';
  $('cRoll').value = c?.roll_number || ''; $('cDob').value = c?.date_of_birth || '';
  $('cDept').value = c ? c.department.id : TEST.departments[0]?.id;
  $('cCode').value = ''; $('cCodeField').hidden = !!c;
  $('cErr').style.display = 'none';
  openModal('candModal');
}

async function saveCand() {
  const body = { full_name: $('cName').value, email: $('cEmail').value, phone: $('cPhone').value, roll_number: $('cRoll').value,
                 date_of_birth: $('cDob').value, department_id: Number($('cDept').value) };
  if (!editId) { body.test_id = TEST.id; if ($('cCode').value.trim()) body.access_code = $('cCode').value.trim(); }
  const btn = $('cSave'); btn.disabled = true;
  try {
    const { candidate } = editId ? await api('/roster/' + editId, { method: 'PUT', body })
                                 : await api('/roster', { method: 'POST', body });
    closeModal('candModal');
    const pin = candidate.login_with === 'pin' ? ` · PIN ${esc(candidate.pin)}` : '';
    aToast(editId ? 'Candidate corrected.' : `Added · access code ${esc(candidate.access_code)}${pin}`);
    await loadRoster();
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
  const pinNote = c.login_with === 'pin' ? ' Their PIN is replaced too.' : '';
  if (!confirm(`Issue a new access code for ${c.full_name}? The old code stops working immediately (use this for a lost slip).${pinNote}`)) return;
  try {
    const { candidate } = await api(`/roster/${id}/new-code`, { method: 'POST' });
    const pin = candidate.login_with === 'pin' ? ` · PIN ${esc(candidate.pin)}` : '';
    aToast(`New code for ${esc(candidate.full_name)}: ${esc(candidate.access_code)}${pin}`); await loadRoster();
  }
  catch (e) { handleApiError(e); }
}

async function removeCand(id) {
  const c = window.ROWS.find(x => x.id === id);
  if (!confirm(`Remove ${c.full_name}${c.roll_number ? ` (${c.roll_number})` : ''} from this roster? Their access code stops working.`)) return;
  try { await api('/roster/' + id, { method: 'DELETE' }); aToast('Removed.'); await loadRoster(); }
  catch (e) { handleApiError(e); }
}

// ---------------------------------------------------------------- wiring
// download / pickFile / loadRoster / loadTests never reject (each shows its own error), so their promises are not awaited.
document.addEventListener('admin:ready', () => {
  $('templateBtn').addEventListener('click', e => { e.preventDefault(); void downloadFile('/roster/template.csv', 'roster-template.csv'); });
  $('templateLink').addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); void downloadFile('/roster/template.csv', 'roster-template.csv'); });
  $('exportBtn').addEventListener('click', e => { e.preventDefault(); downloadUpdated(); });
  $('csvFile').addEventListener('change', e => { void pickFile(e.target.files[0]); });
  const drop = $('drop');
  ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', e => { void pickFile(e.dataTransfer.files[0]); });
  $('rosterRows').addEventListener('click', e => { const el = e.target.closest('.reveal'); if (el) toggleReveal(el, el.dataset.real); });
  $('deptFilter').addEventListener('change', () => { page = 1; void loadRoster(); });
  $('search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { page = 1; void loadRoster(); }, 250); });
  void loadTests();
});
