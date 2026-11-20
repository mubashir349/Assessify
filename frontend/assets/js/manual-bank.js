// Manual question bank editor. Uses POST /questions/manual only; it never calls the AI generation endpoints.
const $ = id => document.getElementById(id);
let META = null, DEPTS = [], MAX_QUESTIONS = 100, nextQuestionId = 1, saving = false;

function levelFor(dept) {
  const level = META.levels.find(item => item.value === dept?.level);
  return level ? level.term : 'Department / Field';
}

function deptOptions() {
  return META.levels.map(level => {
    const rows = DEPTS.filter(dept => dept.level === level.value);
    if (!rows.length) return '';
    return `<optgroup label="${esc(level.value)} — ${esc(level.term_plural)}">${rows.map(dept =>
      `<option value="${dept.id}">${esc(dept.name)}</option>`).join('')}</optgroup>`;
  }).join('');
}

function fillSubjects() {
  const dept = DEPTS.find(item => String(item.id) === $('bankDept').value);
  $('bankLevel').value = dept?.level || '';
  $('deptLabel').textContent = dept ? levelFor(dept) : 'Department / Field';
  $('bankSubject').innerHTML = (dept?.subjects || []).map(subject => `<option>${esc(subject)}</option>`).join('');
  $('bankSubject').disabled = !dept || !dept.subjects.length;
}

function qTypeOptions(selected) {
  return META.question_types.map(type => `<option value="${esc(type.value)}" ${type.value === selected ? 'selected' : ''}>${esc(type.label)}</option>`).join('');
}
function difficultyOptions(selected) {
  return META.difficulties.map(type => `<option value="${esc(type.value)}" ${type.value === selected ? 'selected' : ''}>${esc(type.label)}</option>`).join('');
}

function questionCard(id, number) {
  return `<section class="a-card manual-question" data-question-id="${id}">
    <div class="section-head">
      <div><h3 class="manual-q-title">Question ${number}</h3><p>Question statement, answer options and marks</p></div>
      <button type="button" class="a-btn a-btn-danger a-btn-sm" data-remove-question="${id}" ${document.querySelectorAll('.manual-question').length <= 1 ? 'disabled' : ''}><i data-icon="trash"></i> Remove</button>
    </div>
    <div class="a-field"><label>Question statement</label><textarea class="a-textarea" data-field="text" rows="3" maxlength="2000" placeholder="Write your question clearly (10–2000 characters)."></textarea></div>
    <div class="a-grid a-grid-3" style="margin-top:12px;">
      <div class="a-field"><label>Question type</label><select class="a-select" data-field="question_type">${qTypeOptions('mcq')}</select></div>
      <div class="a-field"><label>Difficulty</label><select class="a-select" data-field="difficulty">${difficultyOptions('medium')}</select></div>
      <div class="a-field"><label>Marks / weightage</label><input class="a-input" data-field="marks" type="number" min="1" max="100" value="1" /></div>
    </div>
    <div class="a-field" data-options-wrap style="margin-top:12px;">
      <label>Answer options (one option per line; 2–6 options)</label>
      <textarea class="a-textarea" data-field="options" rows="4">Option A\nOption B\nOption C\nOption D</textarea>
      <span class="hint">Keep every option different and non-empty.</span>
    </div>
    <div class="a-grid a-grid-2" style="margin-top:12px;">
      <div class="a-field"><label>Correct answer</label><select class="a-select" data-field="correct_index"></select></div>
      <div class="a-field"><label>Topic / category (optional)</label><input class="a-input" data-field="topic" maxlength="120" placeholder="e.g. Cell structure" /></div>
    </div>
    <div class="a-field" style="margin-top:12px;"><label>Explanation (optional)</label><textarea class="a-textarea" data-field="explanation" rows="2" maxlength="2000" placeholder="Explain why this is the correct answer."></textarea></div>
  </section>`;
}

function questionCards() { return [...document.querySelectorAll('.manual-question')]; }
function optionsOf(card) { return (card.querySelector('[data-field="options"]')?.value || '').split('\n').map(v => v.trim()).filter(Boolean); }
function refreshAnswerOptions(card) {
  const type = card.querySelector('[data-field="question_type"]').value;
  const select = card.querySelector('[data-field="correct_index"]');
  const options = type === 'true_false' ? ['True', 'False'] : optionsOf(card);
  const selected = Number(select.value || 0);
  select.innerHTML = options.map((value, index) => `<option value="${index}">${esc(value || `Option ${index + 1}`)}</option>`).join('');
  select.value = String(Math.min(selected, Math.max(0, options.length - 1)));
  card.querySelector('[data-options-wrap]').hidden = type === 'true_false';
}

function renumber() {
  const cards = questionCards();
  cards.forEach((card, index) => {
    card.querySelector('.manual-q-title').textContent = `Question ${index + 1}`;
    card.querySelector('[data-remove-question]').disabled = cards.length <= 1;
  });
  $('questionCountLabel').textContent = `${cards.length} question${cards.length === 1 ? '' : 's'}`;
  $('questionCount').value = cards.length;
}

function addQuestion() {
  if (questionCards().length >= MAX_QUESTIONS) return aToast(`The maximum is ${MAX_QUESTIONS} questions per bank.`, 'warn');
  const id = nextQuestionId++;
  $('questionForms').insertAdjacentHTML('beforeend', questionCard(id, questionCards().length + 1));
  const card = questionCards().find(item => Number(item.dataset.questionId) === id);
  refreshAnswerOptions(card); renumber();
}

function buildForms() {
  const count = Number($('questionCount').value);
  if (!Number.isInteger(count) || count < 1 || count > MAX_QUESTIONS) {
    return aToast(`Enter a whole number from 1 to ${MAX_QUESTIONS}.`, 'warn');
  }
  $('questionForms').innerHTML = '';
  for (let i = 0; i < count; i++) addQuestion();
  $('questionArea').hidden = false; $('emptyBankTip').hidden = true;
  $('questionArea').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function readQuestions() {
  return questionCards().map(card => {
    const type = card.querySelector('[data-field="question_type"]').value;
    const options = type === 'true_false' ? ['True', 'False'] : optionsOf(card);
    return {
      text: card.querySelector('[data-field="text"]').value.trim(),
      question_type: type,
      options,
      correct_index: Number(card.querySelector('[data-field="correct_index"]').value || 0),
      difficulty: card.querySelector('[data-field="difficulty"]').value,
      marks: Number(card.querySelector('[data-field="marks"]').value),
      topic: card.querySelector('[data-field="topic"]').value.trim(),
      explanation: card.querySelector('[data-field="explanation"]').value.trim(),
    };
  });
}

async function saveBank() {
  if (saving) return;
  const title = $('bankTitle').value.trim(), departmentId = Number($('bankDept').value), subject = $('bankSubject').value;
  if (title.length < 2) return aToast('Enter a question bank title (at least 2 characters).', 'warn');
  if (!departmentId || !subject) return aToast('Choose a department and subject first.', 'warn');
  const questions = readQuestions();
  const invalid = questions.findIndex(q => q.text.length < 10 || q.text.length > 2000 || !Number.isInteger(q.marks) || q.marks < 1 || q.marks > 100 ||
    (q.question_type === 'mcq' && (q.options.length < 2 || q.options.length > 6 || q.options.some(x => !x))));
  if (invalid >= 0) {
    const card = questionCards()[invalid];
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    aToast(`Please check Question ${invalid + 1}: statement, options and marks are required.`, 'warn');
    return;
  }
  saving = true; const btn = $('saveBankBtn'); btn.disabled = true; btn.textContent = 'Saving question bank…';
  try {
    const { attempt } = await api('/questions/manual', { method: 'POST', body: { title, department_id: departmentId, subject, questions } });
    aToast(`Saved “${esc(title)}” with ${attempt.generated_count} approved questions. No AI service was used.`, 'check');
    window.location.href = 'question-bank.html';
  } catch (error) {
    if (error.status === 401) return handleApiError(error);
    const details = error.details || {};
    const key = Object.keys(details).find(k => /^question_\d+_/.test(k));
    if (key) {
      const index = Number(key.match(/^question_(\d+)_/)[1]) - 1;
      questionCards()[index]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    handleApiError(error);
  } finally {
    saving = false; btn.disabled = false; btn.innerHTML = '<i data-icon="check"></i> Review and save question bank';
    if (window.AIcons) window.AIcons.hydrate(btn);
  }
}

async function init() {
  try {
    [META, { items: DEPTS }] = await Promise.all([loadMeta(), api('/departments')]);
  } catch (error) { return handleApiError(error); }
  MAX_QUESTIONS = META.generation_limits.max_questions || 100;
  $('questionCount').max = MAX_QUESTIONS;
  $('countHint').textContent = `You can add 1–${MAX_QUESTIONS} questions. This manual workflow does not call AI.`;
  $('bankDept').innerHTML = deptOptions();
  fillSubjects();
  if (!DEPTS.length) {
    $('buildBtn').disabled = true;
    aToast('Create a department and subject before adding a question bank.', 'warn');
  }
  $('bankDept').addEventListener('change', fillSubjects);
  $('buildBtn').addEventListener('click', buildForms);
  $('addQuestionBtn').addEventListener('click', addQuestion);
  $('saveBankBtn').addEventListener('click', () => void saveBank());
  $('questionForms').addEventListener('change', event => {
    const card = event.target.closest('.manual-question');
    if (card && (event.target.matches('[data-field="question_type"]'))) refreshAnswerOptions(card);
  });
  $('questionForms').addEventListener('input', event => {
    const card = event.target.closest('.manual-question');
    if (card && event.target.matches('[data-field="options"]')) refreshAnswerOptions(card);
  });
  $('questionForms').addEventListener('click', event => {
    const button = event.target.closest('[data-remove-question]');
    if (!button) return;
    const cards = questionCards();
    if (cards.length <= 1) return;
    button.closest('.manual-question').remove(); renumber();
  });
}

document.addEventListener('admin:ready', () => void init(), { once: true });
