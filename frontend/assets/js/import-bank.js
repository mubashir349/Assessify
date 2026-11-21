/* Existing Question Bank import wizard. Extraction is separate from optional AI review. */
const $ = id => document.getElementById(id);
let META = null, DEPTS = [], draft = null, aiRecommendations = [], originalQuestions = [];
// Snapshot of the questions taken the moment an AI review starts, so every applied change can be reverted.
let reviewBaseline = null, appliedCount = 0;
const cleanForServer = q => { const { ai_edited, ...rest } = q; return rest; };   // ai_edited is a screen-only marker
const MAP_FIELDS = [
  ['text', 'Question statement', true], ['correct_answer', 'Correct answer', false], ['options', 'All options (one column)', false],
  ['option_a', 'Option A', false], ['option_b', 'Option B', false], ['option_c', 'Option C', false], ['option_d', 'Option D', false],
  ['option_e', 'Option E', false], ['option_f', 'Option F', false], ['question_type', 'Question type', false],
  ['marks', 'Marks / weightage', false], ['explanation', 'Explanation', false], ['topic', 'Topic / category', false], ['difficulty', 'Difficulty', false],
];

function deptOptions() {
  return META.levels.map(level => {
    const items = DEPTS.filter(d => d.level === level.value);
    return items.length ? `<optgroup label="${esc(level.value)} — ${esc(level.term_plural)}">${items.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('')}</optgroup>` : '';
  }).join('');
}
function fillSubjects() {
  const dept = DEPTS.find(d => String(d.id) === $('bankDept').value);
  $('bankLevel').value = dept?.level || '';
  $('deptLabel').textContent = dept ? (META.levels.find(x => x.value === dept.level)?.term || 'Department / Field') : 'Department / Field';
  $('bankSubject').innerHTML = '<option value="">Choose a subject</option>' + (dept?.subjects || []).map(s => `<option>${esc(s)}</option>`).join('');
  $('bankSubject').disabled = !dept || !dept.subjects.length;
}
function setStage(stage) {
  const active = { upload: ['uploadPanel'], mapping: ['mappingPanel'], preview: ['previewPanel'], review: ['reviewPanel'], save: ['finalPanel'] };
  ['mappingPanel', 'previewPanel', 'reviewPanel', 'finalPanel'].forEach(id => $(id).hidden = !active[stage].includes(id));
  document.querySelectorAll('[data-step-label]').forEach(el => {
    const key = el.dataset.stepLabel;
    const order = ['upload', 'preview', 'review', 'save'];
    const current = stage === 'mapping' ? 'upload' : stage;
    el.classList.toggle('active', key === current);
    el.classList.toggle('done', order.indexOf(key) < order.indexOf(current));
  });
}
function showWarnings(items) {
  const el = $('extractWarnings');
  if (!items?.length) { el.hidden = true; el.innerHTML = ''; return; }
  el.hidden = false;
  el.innerHTML = `<strong>Review notes</strong><ul>${items.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
}
function mappingSelect(key, label, required) {
  const headers = draft?.headers || [];
  const selected = draft?.suggested_mapping?.[key] || '';
  return `<div class="a-field"><label for="map-${key}">${esc(label)}${required ? ' *' : ''}</label><select class="a-select" id="map-${key}"><option value="">— Not present —</option>${headers.map(h => `<option value="${esc(h)}" ${selected === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}</select></div>`;
}
function renderMapping() {
  $('mappingFields').innerHTML = MAP_FIELDS.map(([key, label, required]) => mappingSelect(key, label, required)).join('');
  const headers = draft.headers || [], rows = draft.sample_rows || [];
  $('mappingSample').innerHTML = `<table><thead><tr>${headers.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${headers.map(h => `<td>${esc(row[h] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  setStage('mapping');
}
function currentMapping() {
  const out = {};
  MAP_FIELDS.forEach(([key]) => { const value = $(`map-${key}`)?.value; if (value) out[key] = value; });
  return out;
}
async function confirmMapping() {
  const mapping = currentMapping();
  if (!mapping.text) return aToast('Select the column containing the question statement.', '⚠');
  $('confirmMappingBtn').disabled = true; $('confirmMappingBtn').textContent = 'Extracting…';
  try {
    const result = await api(`/questions/imports/${draft.token}/mapping`, { method: 'POST', body: { mapping } });
    draft = { ...draft, ...result.import };
    originalQuestions = structuredClone(draft.questions || []);
    renderPreview();
  } catch (e) { handleApiError(e); }
  finally { $('confirmMappingBtn').disabled = false; $('confirmMappingBtn').textContent = 'Confirm mapping & extract'; }
}
function setSelectedFile(file) {
  $('selectedFileRow').hidden = !file;
  $('selectedFileName').textContent = file ? `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MB` : '';
  $('filePrompt').textContent = file ? file.name : 'Choose a PDF, Word, CSV or Excel file';
  $('uploadBtn').disabled = !file;
}
async function uploadFile() {
  const file = $('sourceFile').files?.[0];
  if (!file) return aToast('Choose a file first.', '⚠');
  if (file.size > 25 * 1024 * 1024) return aToast('The maximum file size is 25 MB.', '⚠');
  const form = new FormData(); form.append('file', file);
  $('uploadBtn').disabled = true; $('uploadBtn').textContent = 'Uploading and extracting…'; $('uploadStatus').textContent = 'Processing file. No AI service is called at this stage.';
  try {
    const result = await api('/questions/imports', { method: 'POST', body: form });
    draft = result.import;
    aiRecommendations = [];
    if (draft.needs_mapping) renderMapping();
    else { originalQuestions = structuredClone(draft.questions || []); renderPreview(); }
  } catch (e) { handleApiError(e); $('uploadStatus').textContent = e.message; }
  finally { $('uploadBtn').disabled = false; $('uploadBtn').innerHTML = '<i data-icon="file-search"></i> Upload & extract questions'; if (window.AIcons) AIcons.hydrate($('uploadBtn')); }
}
function answerOptions(q) {
  const opts = q.question_type === 'true_false' ? ['True', 'False'] : (q.options || []);
  const idx = Number.isInteger(q.correct_index) ? String(q.correct_index) : '';
  return `<option value="">Select correct answer</option>${opts.map((v, i) => `<option value="${i}" ${idx === String(i) ? 'selected' : ''}>${String.fromCharCode(65+i)}. ${esc(v)}</option>`).join('')}`;
}
function questionCard(q, i) {
  const options = q.question_type === 'true_false' ? '' : (q.options || []).join('\n');
  const flags = [...(q.warnings || [])];
  if (q.possible_duplicate) flags.push('Potential duplicate — will be skipped when saving');
  return `<article class="ib-qcard" data-q-index="${i}">
    <div class="ib-qhead"><div><h3>Question ${i + 1}</h3><p>Source row: ${esc(q.source_row ?? i + 1)} · Edit extracted content before continuing</p></div><button class="a-btn a-btn-danger a-btn-sm" type="button" data-remove-q="${i}">Remove</button></div>
    <div class="ib-field"><label>Question statement</label><textarea rows="3" data-q-field="text">${esc(q.text || '')}</textarea></div>
    <div class="ib-qgrid">
      <div class="ib-field"><label>Question type</label><select data-q-field="question_type"><option value="mcq" ${q.question_type === 'mcq' ? 'selected' : ''}>Multiple choice</option><option value="true_false" ${q.question_type === 'true_false' ? 'selected' : ''}>True / False</option></select></div>
      <div class="ib-field"><label>Difficulty</label><select data-q-field="difficulty"><option value="easy" ${q.difficulty === 'easy' ? 'selected' : ''}>Easy</option><option value="medium" ${q.difficulty !== 'easy' && q.difficulty !== 'hard' ? 'selected' : ''}>Medium</option><option value="hard" ${q.difficulty === 'hard' ? 'selected' : ''}>Hard</option></select></div>
      <div class="ib-field"><label>Marks / weightage</label><input type="number" min="1" max="100" data-q-field="marks" value="${esc(q.marks ?? 1)}" /></div>
      <div class="ib-field wide" data-options-field ${q.question_type === 'true_false' ? 'hidden' : ''}><label>Answer options (one per line; 2–6)</label><textarea rows="4" data-q-field="options">${esc(options)}</textarea></div>
      <div class="ib-field"><label>Correct answer</label><select data-q-field="correct_index">${answerOptions(q)}</select></div>
      <div class="ib-field"><label>Topic / category</label><input maxlength="120" data-q-field="topic" value="${esc(q.topic || '')}" placeholder="Optional" /></div>
      <div class="ib-field wide"><label>Explanation</label><textarea rows="2" data-q-field="explanation">${esc(q.explanation || '')}</textarea></div>
    </div>
    ${flags.length ? `<div class="ib-qflags">${flags.map(f => `<span class="flag ${q.possible_duplicate && f.startsWith('Potential') ? 'dup' : 'warn'}">${esc(f)}</span>`).join('')}</div>` : ''}
  </article>`;
}
function renderPreview() {
  $('questionPreviewList').innerHTML = (draft.questions || []).map(questionCard).join('') || '<div class="a-empty">No questions were extracted. Use Add question to create them manually.</div>';
  $('previewCount').textContent = `${draft.questions?.length || 0} questions`;
  $('sourceFileLabel').textContent = `Original file: ${draft.filename}`;
  showWarnings(draft.warnings || []);
  setStage('preview');
  $('previewPanel').hidden = false;
  syncContinueLabels();
  if (window.AIcons) AIcons.hydrate($('previewPanel'));
}
function syncContinueLabels() {
  // After an AI review has changed the questions, "Continue without AI" would be wrong: those changes are kept.
  const edited = (draft?.questions || []).filter(q => q.ai_edited).length;
  $('withoutAiBtn').textContent = edited ? `Continue to final review (${edited} AI-edited)` : 'Continue without AI';
}
function syncReviewButtons() {
  $('appliedCount').textContent = `${appliedCount} applied`;
  $('revertAiBtn').disabled = appliedCount === 0;
  const cont = $('continueUnchangedBtn');
  cont.textContent = appliedCount ? `Continue to final review (${appliedCount} applied)` : 'Continue without applying recommendations';
  cont.classList.toggle('a-btn-primary', appliedCount > 0);
  cont.classList.toggle('a-btn-ghost', appliedCount === 0);
  $('applySelectedBtn').classList.toggle('a-btn-primary', appliedCount === 0);
  $('applySelectedBtn').classList.toggle('a-btn-ghost', appliedCount > 0);
}
function captureQuestions() {
  // The preview DOM is hidden during AI review/final review. Do not overwrite accepted AI changes with stale DOM.
  if ($('previewPanel').hidden) return draft?.questions || [];
  const cards = [...$('questionPreviewList').querySelectorAll('[data-q-index]')];
  const questions = cards.map(card => {
    const get = f => card.querySelector(`[data-q-field="${f}"]`);
    const type = get('question_type').value;
    const opts = type === 'true_false' ? ['True', 'False'] : get('options').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    const answer = get('correct_index').value;
    const old = draft.questions[Number(card.dataset.qIndex)] || {};
    return { ...old, text: get('text').value.trim(), question_type: type, options: opts,
      correct_index: answer === '' ? null : Number(answer), difficulty: get('difficulty').value,
      marks: Number(get('marks').value), topic: get('topic').value.trim(), explanation: get('explanation').value.trim() };
  });
  draft.questions = questions;
  return questions;
}
function refreshCorrectSelect(card, keep) {
  const type = card.querySelector('[data-q-field="question_type"]').value;
  const optsField = card.querySelector('[data-options-field]');
  const opts = type === 'true_false' ? ['True', 'False'] : card.querySelector('[data-q-field="options"]').value.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  optsField.hidden = type === 'true_false';
  const select = card.querySelector('[data-q-field="correct_index"]');
  select.innerHTML = `<option value="">Select correct answer</option>` + opts.map((o, i) => `<option value="${i}">${String.fromCharCode(65+i)}. ${esc(o)}</option>`).join('');
  if (keep !== undefined && keep !== null && Number(keep) < opts.length) select.value = String(keep);
}
function addQuestion() {
  captureQuestions();
  draft.questions.push({ text: '', question_type: 'mcq', options: ['', '', '', ''], correct_index: null, marks: 1,
    difficulty: 'medium', topic: '', explanation: '', warnings: ['New question — complete all required fields.'], source_row: 'Manual addition' });
  renderPreview();
  const cards = $('questionPreviewList').querySelectorAll('[data-q-index]'); cards[cards.length - 1]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
function validateBeforeReview() {
  const questions = captureQuestions();
  if (!questions.length) { aToast('Add at least one question before continuing.', '⚠'); return false; }
  const incomplete = questions.findIndex(q => q.text.length < 10 || q.options.length < 2 || q.options.length > 6 ||
    q.options.some(x => !x) || !Number.isInteger(q.correct_index) || q.correct_index < 0 || q.correct_index >= q.options.length);
  if (incomplete >= 0) {
    aToast(`Complete Question ${incomplete + 1}: statement, 2–6 options and a correct answer are required.`, '⚠');
    $('questionPreviewList').querySelector(`[data-q-index="${incomplete}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    return false;
  }
  return true;
}
async function initAiStatus() {
  try {
    const status = await api('/questions/ai-status');
    if (!status.configured) {
      $('reviewAiBtn').disabled = true;
      $('aiAvailability').textContent = `AI review is optional and not configured: ${status.message} You can continue without AI.`;
    } else $('aiAvailability').textContent = `AI review is available through ${status.provider}. It will only suggest changes; nothing is applied automatically.`;
  } catch (e) { $('aiAvailability').textContent = 'AI availability could not be checked. You can still import and save without AI.'; }
}
async function requestAiReview() {
  if (!validateBeforeReview()) return;
  $('reviewAiBtn').disabled = true; $('reviewAiBtn').textContent = 'Reviewing questions with AI…';
  try {
    captureQuestions();
    const result = await api(`/questions/imports/${draft.token}/ai-review`, { method: 'POST', body: { questions: draft.questions.map(cleanForServer) } });
    aiRecommendations = result.recommendations || [];
    reviewBaseline = structuredClone(draft.questions);      // "no AI changes applied" state, for Revert
    appliedCount = 0;
    renderRecommendations(result.recommendation_count || 0);
    syncReviewButtons();
    setStage('review'); $('reviewPanel').hidden = false;
  } catch (e) { handleApiError(e); }
  finally { $('reviewAiBtn').disabled = false; $('reviewAiBtn').innerHTML = '<i data-icon="sparkles"></i> Review Question Bank with AI Recommendations'; if (window.AIcons) AIcons.hydrate($('reviewAiBtn')); }
}
function displayValue(rec) {
  const v = rec.suggested_display ?? rec.suggested_value;
  if (Array.isArray(v)) return v.map((x, i) => `${String.fromCharCode(65+i)}. ${x}`).join('\n');
  return String(v ?? '');
}
function renderRecommendations(total) {
  $('recommendationCount').textContent = `${total} recommendations`;
  $('recommendationList').innerHTML = aiRecommendations.length ? aiRecommendations.map(group => {
    const q = draft.questions[group.question_number - 1];
    return `<article class="ib-rec-card"><div class="ib-rec-title">Question ${group.question_number} <span class="badge badge-neutral">${esc(q?.text || '')}</span></div>
      ${group.items.map((rec, idx) => `<div class="ib-rec-row"><input type="checkbox" data-rec-q="${group.question_number - 1}" data-rec-i="${idx}" aria-label="Accept ${esc(rec.category)} recommendation" />
        <div class="ib-rec-content"><div class="ib-rec-title"><span class="badge badge-ai">${esc(rec.category)}</span><span class="badge ${rec.confidence === 'high' ? 'badge-approved' : 'badge-warning'}">${esc(rec.confidence)} confidence</span>${rec.requires_verification ? '<span class="badge badge-warning">Needs manual verification</span>' : ''}</div>
        <div class="ib-rec-comparison"><div class="ib-rec-value"><strong>Original</strong>${esc(Array.isArray(rec.current_value) ? rec.current_value.join('\n') : rec.current_value ?? 'Not provided')}</div><div class="ib-rec-value"><strong>AI suggestion</strong>${esc(displayValue(rec))}</div></div>
        <div class="ib-rec-explain">${esc(rec.explanation)}${rec.evidence ? `<br><b>Basis:</b> ${esc(rec.evidence)}` : ''}</div></div></div>`).join('')}</article>`;
  }).join('') : '<div class="a-empty">The AI reviewer did not find any actionable recommendations. You can continue to final review.</div>';
  $('selectAllRecommendations').checked = false;
}
function applySelectedRecommendations() {
  if (!$('recommendationList').querySelector('input[type="checkbox"][data-rec-q]:checked:not(:disabled)')) {
    return aToast('Tick at least one recommendation first.', '⚠');
  }
  let count = 0;
  $('recommendationList').querySelectorAll('input[type="checkbox"][data-rec-q]:checked').forEach(box => {
    const qi = Number(box.dataset.recQ), ri = Number(box.dataset.recI), rec = aiRecommendations.find(g => g.question_number - 1 === qi)?.items?.[ri];
    const q = draft.questions[qi];
    if (!q || !rec) return;
    // Apply only the one field attached to this independently checked recommendation.
    if (rec.field === 'options') {
      const oldAnswer = Number.isInteger(q.correct_index) ? q.options?.[q.correct_index] : null;
      q.options = structuredClone(rec.suggested_value);
      // Keep the correct answer attached to the same option text; never silently shift its index.
      q.correct_index = oldAnswer ? q.options.findIndex(x => x === oldAnswer) : null;
      if (q.correct_index < 0) {
        q.correct_index = null;
        q.warnings = [...(q.warnings || []), 'An accepted option change altered the selected answer option. Please select the correct answer again.'];
      }
    } else {
      if (rec.field === 'correct_index' && rec.suggested_value >= (q.options || []).length) return;
      q[rec.field] = structuredClone(rec.suggested_value);
    }
    count++;
    q.ai_edited = true;
    box.disabled = true;
    box.checked = true;
    box.closest('.ib-rec-row').classList.add('applied');
    box.closest('.ib-rec-row').querySelector('.ib-rec-content').insertAdjacentHTML('beforeend', '<span class="badge badge-approved">Applied by teacher</span>');
  });
  appliedCount += count;
  syncReviewButtons();
  $('reviewStatus').textContent = `${count} selected recommendation(s) applied (${appliedCount} in total). Unselected recommendations were left unchanged. Use "Revert all AI changes" to undo them.`;
  aToast(`${count} selected recommendation(s) applied to your working preview.`, '✓');
}
function revertAiChanges() {
  if (!reviewBaseline || !appliedCount) return;
  if (!confirm('Remove all applied AI changes? Your questions go back to how they were before this AI review started.')) return;
  draft.questions = structuredClone(reviewBaseline);
  appliedCount = 0;
  renderRecommendations(aiRecommendations.reduce((n, g) => n + g.items.length, 0));   // boxes are free to tick again
  syncReviewButtons();
  $('reviewStatus').textContent = 'All AI changes were reverted. Your questions are exactly as they were before the review.';
  aToast('AI changes reverted.', '✓');
}
function selectHighConfidence() {
  $('recommendationList').querySelectorAll('input[type="checkbox"][data-rec-q]:not(:disabled)').forEach(box => {
    const rec = aiRecommendations.find(g => g.question_number - 1 === Number(box.dataset.recQ))?.items?.[Number(box.dataset.recI)];
    box.checked = !!rec && rec.confidence === 'high' && !rec.requires_verification;
  });
}
function finalReview() {
  captureQuestions();
  if (!draft.questions?.length) return aToast('Add at least one question before final review.', '⚠');
  const deptId = Number($('bankDept').value), subject = $('bankSubject').value, title = $('bankTitle').value.trim();
  if (title.length < 2 || !deptId || !subject) return aToast('Complete bank title, department and subject before saving.', '⚠');
  const duplicates = draft.questions.filter(q => q.possible_duplicate).length;
  const incomplete = draft.questions.filter(q => !q.text || q.text.trim().length < 10 || !Array.isArray(q.options) || q.options.length < 2 || q.options.some(x => !String(x).trim()) || !Number.isInteger(q.correct_index)).length;
  $('finalSummary').innerHTML = `<span class="a-chip">${draft.questions.length} reviewed questions</span><span class="a-chip">${duplicates} possible duplicates (exact matches are skipped)</span><span class="a-chip">${incomplete} incomplete — edit before saving</span><span class="a-chip">${draft.questions.filter(q => q.ai_edited).length} edited by AI recommendations</span><span class="a-chip">Source: ${esc(draft.filename)}</span>`;
  $('finalQuestionList').innerHTML = draft.questions.map((q, i) => {
    const answer = Number.isInteger(q.correct_index) && q.options?.[q.correct_index] ? `${String.fromCharCode(65+q.correct_index)}. ${q.options[q.correct_index]}` : 'Not selected';
    return `<article class="ib-final-q"><strong>Question ${i+1}. ${esc(q.text)}</strong>${q.ai_edited ? ' <span class="badge badge-ai">AI-edited</span>' : ''}<p>${(q.options || []).map((o, j) => `${String.fromCharCode(65+j)}. ${esc(o)}`).join('\n')}</p><small>Correct answer: ${esc(answer)} · Marks: ${esc(q.marks)} · Difficulty: ${esc(q.difficulty)}${q.topic ? ` · Topic: ${esc(q.topic)}` : ''}</small>${q.warnings?.length ? `<div class="ib-qflags">${q.warnings.map(w => `<span class="flag warn">${esc(w)}</span>`).join('')}</div>` : ''}</article>`;
  }).join('');
  setStage('save'); $('finalPanel').hidden = false;
}
function validateQuestions(quiet = false) {
  const questions = draft.questions || [];
  const invalid = questions.findIndex(q => !q.text || q.text.trim().length < 10 || q.text.length > 2000 ||
    !Array.isArray(q.options) || q.options.length < 2 || q.options.length > 6 || q.options.some(x => !String(x).trim()) ||
    new Set(q.options.map(x => String(x).trim().toLowerCase())).size !== q.options.length ||
    !Number.isInteger(q.correct_index) || q.correct_index < 0 || q.correct_index >= q.options.length ||
    !Number.isInteger(Number(q.marks)) || Number(q.marks) < 1 || Number(q.marks) > 100);
  if (invalid >= 0) { if (!quiet) aToast(`Question ${invalid+1} needs a statement, 2–6 unique options, a correct answer and valid marks.`, '⚠'); return false; }
  return true;
}
async function saveBank() {
  if (!validateQuestions()) return;
  const title = $('bankTitle').value.trim(), department_id = Number($('bankDept').value), subject = $('bankSubject').value;
  if (title.length < 2 || !department_id || !subject) return aToast('Complete bank title, department and subject.', '⚠');
  $('saveImportedBankBtn').disabled = true; $('saveImportedBankBtn').textContent = 'Saving…'; $('saveStatus').textContent = 'Saving the teacher-reviewed version to the existing Question Bank…';
  const questions = draft.questions.map(q => ({ ...cleanForServer(q), marks: Number(q.marks), correct_index: Number(q.correct_index) }));
  try {
    const result = await api(`/questions/imports/${draft.token}/save`, { method: 'POST', body: { title, department_id, subject, questions } });
    const skipped = result.skipped_duplicates?.length || 0;
    aToast(`Saved ${result.attempt.generated_count} approved questions. ${skipped} duplicate(s) skipped.`, '✓');
    window.location.href = 'question-bank.html';
  } catch (e) { handleApiError(e); $('saveStatus').textContent = e.message; }
  finally { $('saveImportedBankBtn').disabled = false; $('saveImportedBankBtn').innerHTML = '<i data-icon="check"></i> Save Question Bank'; if (window.AIcons) AIcons.hydrate($('saveImportedBankBtn')); }
}

function init() {
  Promise.all([loadMeta(), api('/departments')]).then(([meta, depts]) => {
    META = meta; DEPTS = depts.items || [];
    $('bankDept').innerHTML = '<option value="">Choose a department</option>' + deptOptions();
    fillSubjects(); $('bankDept').addEventListener('change', fillSubjects);
    if (!DEPTS.length) aToast('Create a department and subject before importing questions.', '⚠');
  }).catch(handleApiError);
  void initAiStatus();
  $('sourceFile').addEventListener('change', () => setSelectedFile($('sourceFile').files?.[0]));
  $('clearFileBtn').addEventListener('click', () => { $('sourceFile').value = ''; setSelectedFile(null); });
  $('uploadBtn').addEventListener('click', () => void uploadFile());
  $('confirmMappingBtn').addEventListener('click', () => void confirmMapping());
  $('downloadSourceBtn').addEventListener('click', () => { if (draft?.token) void downloadFile(`/questions/imports/${draft.token}/source`, draft.filename); });
  $('addQuestionBtn').addEventListener('click', addQuestion);
  $('reviewAiBtn').addEventListener('click', () => void requestAiReview());
  $('withoutAiBtn').addEventListener('click', () => { if (validateBeforeReview()) finalReview(); });
  $('continueUnchangedBtn').addEventListener('click', () => finalReview());
  $('applySelectedBtn').addEventListener('click', applySelectedRecommendations);
  $('revertAiBtn').addEventListener('click', revertAiChanges);
  $('selectHighConfBtn').addEventListener('click', selectHighConfidence);
  $('backToPreviewBtn').addEventListener('click', () => renderPreview());
  $('selectAllRecommendations').addEventListener('change', e => $('recommendationList').querySelectorAll('input[type="checkbox"][data-rec-q]:not(:disabled)').forEach(c => c.checked = e.target.checked));
  $('backToEditBtn').addEventListener('click', () => { renderPreview(); });
  $('saveImportedBankBtn').addEventListener('click', () => void saveBank());
  $('questionPreviewList').addEventListener('click', e => {
    const btn = e.target.closest('[data-remove-q]'); if (!btn) return;
    captureQuestions(); draft.questions.splice(Number(btn.dataset.removeQ), 1); renderPreview();
  });
  $('questionPreviewList').addEventListener('change', e => {
    const card = e.target.closest('[data-q-index]'); if (!card) return;
    if (e.target.matches('[data-q-field="question_type"]')) refreshCorrectSelect(card, null);
    if (e.target.matches('[data-q-field="options"]')) refreshCorrectSelect(card, card.querySelector('[data-q-field="correct_index"]').value);
  });
  const dz = $('dropzone');
  ['dragenter', 'dragover'].forEach(name => dz.addEventListener(name, e => { e.preventDefault(); dz.classList.add('drag'); }));
  ['dragleave', 'drop'].forEach(name => dz.addEventListener(name, e => { e.preventDefault(); dz.classList.remove('drag'); }));
  dz.addEventListener('drop', e => { const file = e.dataTransfer.files?.[0]; if (!file) return; const transfer = new DataTransfer(); transfer.items.add(file); $('sourceFile').files = transfer.files; setSelectedFile(file); });
}
document.addEventListener('admin:ready', init, { once: true });
