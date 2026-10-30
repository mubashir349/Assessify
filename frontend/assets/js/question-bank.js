// question-bank.html — APPROVED questions only, read from the backend (GET /questions/bank).
// Filters and pagination run on the server; drafts / rejected questions never appear here.
let META = null, DEPTS = [], page = 1, searchTimer;
const PER_PAGE = 20;
const $ = id => document.getElementById(id);
const LETTER = 'ABCDEF';
const label = (list, v) => { const x = (list || []).find(i => i.value === v); return x ? x.label : v; };

function bars(el, counts, total) {
  $(el).innerHTML = Object.entries(counts).map(([k, v]) => {
    const p = total ? Math.round(v / total * 100) : 0;
    return `<div class="bar-row"><span class="lb">${esc(k)}</span><span class="tr"><span class="fl" style="width:${p}%;display:block"></span></span><span class="v">${p}%</span></div>`;
  }).join('');
}
function insights(s) {
  const t = s.total;
  const d = {}; META.difficulties.forEach(x => d[x.label] = s.by_difficulty[x.value] || 0);
  const l = {}; META.levels.forEach(x => l[x.value] = s.by_level[x.value] || 0);
  bars('diffBars', d, t); bars('lvlBars', l, t);
  const tips = [];
  if (!t) tips.push(['🎯', 'The bank is empty — generate drafts from a PDF and approve them in Draft Review.']);
  if (t && (d.Hard || 0) / t < 0.2) tips.push(['⚠', 'Only ' + Math.round((d.Hard || 0) / t * 100) + '% hard questions — add more to separate top candidates.']);
  if (t && (d.Easy || 0) / t > 0.5) tips.push(['⚠', 'Bank skews easy — consider generating Medium/Hard drafts.']);
  const thin = META.levels.map(x => x.value).filter(x => !l[x]);
  if (t && thin.length) tips.push(['🎯', 'No questions yet for ' + thin.join(', ') + '.']);
  if (t) tips.push(['✦', t + ' approved questions across ' + Object.keys(s.by_subject).length + ' subjects.']);
  $('aiTips').innerHTML = tips.slice(0, 4).map(x => `<div class="ai-item"><span class="ic">${x[0]}</span><span>${esc(x[1])}</span></div>`).join('');
}

function card(x) {
  return `<div class="a-card qrow"><div class="qbody"><p class="qtext">${esc(x.text)}</p>
    <details><summary>Show options &amp; answer</summary>
      <div class="opt-view">${x.options.map((o, j) => `<span class="${j === x.correct_index ? 'ok' : ''}">${LETTER[j]}. ${esc(o)}${j === x.correct_index ? ' ✓' : ''}</span>`).join('')}</div>
      ${x.explanation ? `<div class="q-expl">💡 ${esc(x.explanation)}</div>` : ''}</details>
    <div class="qmeta"><span class="badge badge-approved">Approved</span>
      <span class="a-chip">${esc(x.department_name)}</span><span class="a-chip">${esc(x.level)}</span><span class="a-chip">${esc(x.subject)}</span>
      ${x.topic ? `<span class="a-chip">${esc(x.topic)}</span>` : ''}
      <span class="a-chip">${esc(label(META.difficulties, x.difficulty))} · ${esc(label(META.question_types, x.question_type))}</span>
      <span class="a-chip">${x.marks} mark${x.marks > 1 ? 's' : ''}</span></div></div>
    <div class="qactions"><a class="a-btn a-btn-ghost a-btn-sm" href="draft-review.html?attempt=${+x.attempt_id}">Source attempt</a></div></div>`;
}

async function renderBank() {
  const qs = new URLSearchParams({ page, per_page: PER_PAGE });
  const add = (k, id) => { const v = $(id).value.trim(); if (v) qs.set(k, v); };
  add('department_id', 'fDept'); add('level', 'fLevel'); add('subject', 'fSubj'); add('difficulty', 'fDiff');
  add('question_type', 'fType'); add('q', 'fQ');
  let d;
  try { d = await api('/questions/bank?' + qs); } catch (e) { return handleApiError(e); }
  insights(d.summary);
  $('bankList').innerHTML = d.items.map(card).join('') ||
    `<div class="a-card a-empty">${d.summary.total ? 'No approved questions match these filters.' : 'No approved questions yet. Generate drafts and approve them in Draft Review.'}</div>`;
  $('bankPager').innerHTML = pagerHtml(d);
}
function pagerHtml(d) {
  if (d.pages > 1) {
    const prevDis = d.page <= 1 ? 'disabled' : '', nextDis = d.page >= d.pages ? 'disabled' : '';
    return `<div class="pager">
    <button class="a-btn a-btn-ghost a-btn-sm" ${prevDis} onclick="page--;renderBank()">← Prev</button>
    <span>Page ${d.page} of ${d.pages} · ${d.total} questions</span>
    <button class="a-btn a-btn-ghost a-btn-sm" ${nextDis} onclick="page++;renderBank()">Next →</button></div>`;
  }
  if (!d.total) return '';
  return `<div class="pager"><span>${d.total} question${d.total === 1 ? '' : 's'}</span></div>`;
}
function applyFilters() { page = 1; void renderBank(); }   // renderBank shows its own errors
function onSearch() { clearTimeout(searchTimer); searchTimer = setTimeout(applyFilters, 300); }
function subjectsFor(deptId) {
  const list = deptId ? DEPTS.filter(d => String(d.id) === deptId) : DEPTS;
  return [...new Set(list.flatMap(d => d.subjects))].sort((a, b) => a.localeCompare(b));
}
function onDept() {
  const keep = $('fSubj').value, subs = subjectsFor($('fDept').value);
  $('fSubj').innerHTML = '<option value="">All subjects</option>' + subs.map(s => `<option>${esc(s)}</option>`).join('');
  if (subs.includes(keep)) $('fSubj').value = keep;
  applyFilters();
}
function relabel() {
  const lv = META.levels.find(l => l.value === $('fLevel').value);
  $('fDept').options[0].textContent = 'All ' + (lv ? lv.term_plural : 'fields / departments').toLowerCase();
}

document.addEventListener('admin:ready', async () => {
  try {
    const [meta, depts] = await Promise.all([loadMeta(), api('/departments')]);
    META = meta; DEPTS = depts.items;
  } catch (e) { return handleApiError(e); }
  fillSelect($('fLevel'), META.levels.map(l => l.value), { keepFirst: true });
  fillSelect($('fDiff'), META.difficulties, { keepFirst: true });
  fillSelect($('fType'), META.question_types, { keepFirst: true });
  $('fDept').innerHTML += DEPTS.map(d => `<option value="${d.id}">${esc(d.name)} (${esc(d.level)})</option>`).join('');
  $('fSubj').innerHTML += subjectsFor('').map(s => `<option>${esc(s)}</option>`).join('');
  renderBank();
});
