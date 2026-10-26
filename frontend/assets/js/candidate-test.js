// candidate-test.html — question flow (difficulty is never shown to candidates)
const QS = [
  ['Mathematics', 'A train travels 120 km at uniform speed. At 10 km/h faster it would take 1 hour less. What is the original speed?', ['30 km/h', '40 km/h', '50 km/h', '60 km/h']],
  ['Mathematics', 'If 3x + 7 = 25, what is x?', ['4', '5', '6', '7']],
  ['Mathematics', 'What is the derivative of x² at x = 3?', ['3', '6', '9', '12']],
  ['Mathematics', 'The sum of the first 10 natural numbers is:', ['45', '50', '55', '60']],
  ['Mathematics', 'Simplify: (a² − b²) / (a − b)', ['a − b', 'a + b', 'a² + b', 'ab']],
  ['Physics', 'The SI unit of force is:', ['Joule', 'Pascal', 'Newton', 'Watt']],
  ['Physics', 'Speed of light in vacuum is approximately:', ['3×10⁶ m/s', '3×10⁸ m/s', '3×10⁵ m/s', '3×10¹⁰ m/s']],
  ['Physics', 'Which quantity is a vector?', ['Speed', 'Mass', 'Velocity', 'Energy']],
  ['Physics', 'Work done is the product of force and:', ['Time', 'Displacement', 'Mass', 'Power']],
  ['Physics', 'A body in free fall near Earth accelerates at about:', ['5 m/s²', '9.8 m/s²', '12 m/s²', '20 m/s²']],
  ['Chemistry', 'Atomic number of Carbon is:', ['4', '6', '8', '12']],
  ['Chemistry', 'pH of a neutral solution at 25°C is:', ['0', '5', '7', '14']],
  ['Chemistry', 'Which gas is most abundant in the atmosphere?', ['Oxygen', 'Nitrogen', 'Argon', 'CO₂']],
  ['Chemistry', 'NaCl is an example of a(n):', ['Covalent bond', 'Ionic compound', 'Metal', 'Alloy']],
  ['Chemistry', 'The lightest element is:', ['Helium', 'Hydrogen', 'Lithium', 'Carbon']],
  ['English', 'Choose the synonym of "abundant".', ['Scarce', 'Plentiful', 'Rare', 'Tiny']],
  ['English', '"The committee ___ decided." Fill in the blank.', ['have', 'has', 'are', 'were']],
  ['English', 'Pick the correctly punctuated sentence.', ['Its a fine day.', "It's a fine day.", "Its' a fine day.", "Its a fine day's."]],
  ['English', 'Antonym of "expand":', ['Grow', 'Contract', 'Stretch', 'Extend']],
  ['English', 'Which is a noun?', ['Quickly', 'Beautiful', 'Happiness', 'Run']],
].map((q, i) => ({ i, subj: q[0], text: q[1], opts: q[2] }));

const S = { cur: 0, ans: {}, flag: new Set() };
const $ = id => document.getElementById(id);

function render() {
  const q = QS[S.cur];
  $('qNum').textContent = `Question ${S.cur + 1} of ${QS.length} · ${q.subj}`;
  $('qText').textContent = q.text;
  $('optList').innerHTML = q.opts.map((o, j) => `<div class="opt${S.ans[S.cur] === j ? ' sel' : ''}" onclick="pick(${j})"><span class="letter">${'ABCD'[j]}</span><span class="t"></span></div>`).join('');
  document.querySelectorAll('#optList .t').forEach((el, j) => el.textContent = q.opts[j]);
  $('flagBtn').classList.toggle('on', S.flag.has(S.cur));
  $('prevBtn').disabled = S.cur === 0; $('nextBtn').textContent = S.cur === QS.length - 1 ? 'Review & submit' : 'Next →';
  $('qGrid').innerHTML = QS.map((_, i) => `<div class="q-dot${S.ans[i] !== undefined ? ' answered' : ''}${S.flag.has(i) ? ' flagged' : ''}${i === S.cur ? ' current' : ''}" onclick="jump(${i})">${i + 1}</div>`).join('');
  const subjects = [...new Set(QS.map(x => x.subj))];
  $('secTabs').innerHTML = subjects.map(s => `<div class="sec-tab${s === q.subj ? ' active' : ''}" onclick="jump(${QS.findIndex(x => x.subj === s)})">${s}</div>`).join('');
  const n = Object.keys(S.ans).length;
  $('progressLabel').textContent = `${n} of ${QS.length} answered`; $('progFill').style.width = (n / QS.length * 100) + '%';
}
function pick(j) { S.ans[S.cur] = j; render(); }
function clearAns() { delete S.ans[S.cur]; render(); }
function toggleFlag() { S.flag.has(S.cur) ? S.flag.delete(S.cur) : S.flag.add(S.cur); render(); }
function jump(i) { S.cur = i; render(); }
function go(d) { if (S.cur + d >= QS.length) return openSubmitConfirm(); S.cur = Math.max(0, S.cur + d); render(); }
function openSubmitConfirm() {
  const n = Object.keys(S.ans).length;
  $('submitMsg').textContent = `You've answered ${n} of ${QS.length} questions${S.flag.size ? ` (${S.flag.size} flagged for review)` : ''}. Unanswered questions will be marked incorrect. This cannot be undone.`;
  $('submitModal').classList.add('open');
}
function closeSubmitConfirm() { $('submitModal').classList.remove('open'); }

document.addEventListener('DOMContentLoaded', () => {
  render();
  // Fixed-time tests end for everyone at the scheduled end time; flexible tests use a per-candidate timer.
  const sc = AA.get('schedule', null), demo = new URLSearchParams(location.search).has('demo');
  let secondsLeft = 2 * 3600 + 30 * 60, fixedEnd = null;
  if (sc && !demo && sc.mode === 'fixed') {
    const [y, m, d] = sc.date.split('-').map(Number), [h, mi] = sc.end.split(':').map(Number);
    fixedEnd = new Date(y, m - 1, d, h, mi, 0);
    secondsLeft = Math.max(0, Math.round((fixedEnd - Date.now()) / 1000));
  } else if (sc && !demo && sc.limit) secondsLeft = sc.limit * 60;
  const submitNow = () => { window.location.href = 'candidate-result.html'; };
  const timerEl = $('timer'), overlay = $('lockOverlay');
  setInterval(() => {
    if (overlay.classList.contains('show') && !fixedEnd) return; // fixed-time clock keeps running while locked
    if (fixedEnd) secondsLeft = Math.max(0, Math.round((fixedEnd - Date.now()) / 1000)); else secondsLeft--;
    if (secondsLeft <= 0) { timerEl.textContent = '⏱ 00:00:00'; return submitNow(); } // auto-submit at end time
    const p = n => String(n).padStart(2, '0');
    timerEl.textContent = `⏱ ${p(Math.floor(secondsLeft / 3600))}:${p(Math.floor((secondsLeft % 3600) / 60))}:${p(secondsLeft % 60)}`;
    timerEl.classList.toggle('low', secondsLeft < 300);
  }, 1000);
  function triggerLock() { if (overlay.classList.contains('show')) return; overlay.classList.add('show'); $('lockTime').textContent = new Date().toLocaleTimeString(); }
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) triggerLock(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) triggerLock(); });
  window.addEventListener('blur', triggerLock);
  // Demo helper: press "L" to preview the lock overlay
  document.addEventListener('keydown', e => { if (e.key === 'l' || e.key === 'L') triggerLock(); });
});
