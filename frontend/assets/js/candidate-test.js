// candidate-test.html — the live paper (Phase 6). Everything that matters is decided by the server:
//   the paper (GET /exam/paper), the time left (remaining_seconds), saving each answer (PUT /exam/answers/<n>),
//   locking (POST /exam/lock), submitting and scoring (POST /exam/submit). This page never sees the correct answers.
// The timer counts down from the server's remaining_seconds, so a wrong clock on the candidate's PC changes nothing.
// Difficulty is never shown to candidates.
const $ = id => document.getElementById(id);
const S = {
  attempt: null, qs: [], cur: 0,
  endsAtMs: 0,            // local Date.now() value when time runs out (from the server's remaining_seconds)
  armed: false,           // true once the candidate entered fullscreen: from then on leaving it locks the test
  pending: new Map(),     // question number -> body still to save (retried until it gets through)
  finishing: false,
};
const pad = n => String(n).padStart(2, '0');

function toResult() { S.finishing = true; window.location.replace('candidate-result.html'); }

function handleFatal(e) {
  if (e.status === 401 || (e.status === 403 && e.code !== 'TEST_NOT_STARTED')) return window.location.replace('candidate-login.html');
  if (e.code === 'ATTEMPT_NOT_STARTED' || e.code === 'TEST_NOT_STARTED') return window.location.replace('candidate-start.html');
  if (e.code === 'TIME_UP' || e.code === 'ALREADY_SUBMITTED') return toResult();
  if (e.code === 'ATTEMPT_LOCKED') return showLocked();
  return false;
}

// ---------------------------------------------------------------- rendering
function render() {
  const q = S.qs[S.cur];
  if (!q) return;
  $('qNum').textContent = `Question ${q.number} of ${S.qs.length} · ${q.subject}${q.marks > 1 ? ` · ${q.marks} marks` : ''}`;
  $('qText').textContent = q.text;
  $('optList').innerHTML = q.options.map((o, j) => `<div class="opt${q.choice === j ? ' sel' : ''}" data-j="${j}"><span class="letter">${'ABCDEFGH'[j]}</span><span class="t">${esc(o)}</span></div>`).join('');
  $('flagBtn').classList.toggle('on', q.flagged);
  $('prevBtn').disabled = S.cur === 0;
  $('nextBtn').textContent = S.cur === S.qs.length - 1 ? 'Review & submit' : 'Next →';
  $('qGrid').innerHTML = S.qs.map((x, i) => `<div class="q-dot${x.choice !== null ? ' answered' : ''}${x.flagged ? ' flagged' : ''}${i === S.cur ? ' current' : ''}" data-i="${i}">${x.number}</div>`).join('');
  const subjects = [...new Set(S.qs.map(x => x.subject))];
  $('secTabs').innerHTML = subjects.length > 1 ? subjects.map(s => `<div class="sec-tab${s === q.subject ? ' active' : ''}" data-i="${S.qs.findIndex(x => x.subject === s)}">${esc(s)}</div>`).join('') : '';
  const n = S.qs.filter(x => x.choice !== null).length;
  $('progressLabel').textContent = `${n} of ${S.qs.length} answered`;
  $('progFill').style.width = (S.qs.length ? n / S.qs.length * 100 : 0) + '%';
}

function setSaveState() {
  const el = $('saveState'), waiting = S.pending.size;
  el.className = 'save-state' + (S.saveError ? ' error' : waiting ? ' pending' : '');
  el.textContent = S.saveError ? `${waiting} answer(s) not saved — retrying…` : waiting ? 'Saving…' : 'All answers saved';
}

// ---------------------------------------------------------------- saving answers (one request per change, retried)
function queueSave(q, body) {
  S.pending.set(q.number, { ...(S.pending.get(q.number) || {}), ...body });
  setSaveState();
  flush();
}

async function flush() {
  if (S.flushing || S.finishing) return;
  S.flushing = true;
  try {
    for (const [number, body] of [...S.pending]) {
      try {
        const d = await api(`/exam/answers/${number}`, { method: 'PUT', body });
        if (S.pending.get(number) === body) S.pending.delete(number);   // not changed again meanwhile
        S.attempt = d.attempt;
        S.saveError = false;
      } catch (e) {
        if (handleFatal(e) !== false) return;
        if (e.status === 422 || e.status === 404) { S.pending.delete(number); continue; }   // drop a bad one
        S.saveError = true;             // network / server hiccup: keep it and try again shortly
        setTimeout(flush, 3000);
        return;
      }
    }
  } finally {
    S.flushing = false;
    setSaveState();
    if (S.pending.size && !S.saveError) flush();
  }
}

function pick(j) { const q = S.qs[S.cur]; q.choice = j; render(); queueSave(q, { choice: j }); }
function clearAns() { const q = S.qs[S.cur]; if (q.choice === null) return; q.choice = null; render(); queueSave(q, { choice: null }); }
function toggleFlag() { const q = S.qs[S.cur]; q.flagged = !q.flagged; render(); queueSave(q, { flagged: q.flagged }); }
function jump(i) { S.cur = i; render(); }
function go(d) { if (S.cur + d >= S.qs.length) return openSubmitConfirm(); S.cur = Math.max(0, S.cur + d); render(); }

// ---------------------------------------------------------------- timer + auto-submit
function syncTime(attempt) {
  S.attempt = attempt;
  S.endsAtMs = Date.now() + attempt.remaining_seconds * 1000;
}

function tick() {
  if (S.finishing || !S.attempt) return;
  const frozen = S.attempt.status === 'locked' && S.attempt.timing_mode === 'flexible';
  const left = frozen ? S.attempt.remaining_seconds : Math.max(0, Math.round((S.endsAtMs - Date.now()) / 1000));
  const el = $('timer');
  el.textContent = `⏱ ${pad(Math.floor(left / 3600))}:${pad(Math.floor(left % 3600 / 60))}:${pad(left % 60)}`;
  el.classList.toggle('low', left < 300);
  if (left <= 0) autoSubmit();
}

async function autoSubmit() {
  if (S.finishing) return;
  S.finishing = true;
  $('timer').textContent = '⏱ 00:00:00';
  await new Promise(r => setTimeout(r, 1500));     // let the server's clock pass the deadline too
  try { await api('/exam/submit', { method: 'POST' }); } catch (e) { /* the server submits it on the next request anyway */ }
  window.location.replace('candidate-result.html');
}

async function resync() {      // every 30 s and while locked: picks up an unlock, a time change or an auto-submit
  if (S.finishing) return;
  try {
    const { attempt } = await api('/exam/paper');
    if (attempt.status === 'submitted') return toResult();
    const wasLocked = S.attempt && S.attempt.status === 'locked';
    syncTime(attempt);
    if (attempt.status === 'locked') showLocked();
    else if (wasLocked) {        // the proctor unlocked it: back to the questions through fullscreen
      $('lockOverlay').classList.remove('show');
      S.armed = false;
      showFsGate('Your test was unlocked');
    }
  } catch (e) { handleFatal(e); }
}

// ---------------------------------------------------------------- fullscreen gate + lock
function showFsGate(title) {
  if (title) $('fsTitle').textContent = title;
  const min = Math.ceil(S.attempt.remaining_seconds / 60);
  $('fsTime').textContent = ` You have about ${min} minute${min === 1 ? '' : 's'} left.`;
  $('fsGate').classList.add('show');
  $('testShell').classList.remove('active');
}

function enterTest() {
  const done = () => {
    S.armed = true;
    $('fsGate').classList.remove('show');
    $('testShell').classList.add('active');
    render();
  };
  const el = document.documentElement;
  if (el.requestFullscreen && document.fullscreenEnabled) el.requestFullscreen().then(done).catch(done);
  else done();                 // browsers without fullscreen (some phones): the tab-switch lock still applies
}

function showLocked() {
  $('fsGate').classList.remove('show');
  $('testShell').classList.remove('active');
  $('lockOverlay').classList.add('show');
  if (S.attempt) {
    $('lockRef').textContent = S.attempt.reference;
    $('lockTime').textContent = new Date(S.attempt.locked_at || Date.now()).toLocaleTimeString();
    if (S.attempt.timing_mode === 'fixed') {
      $('lockText').textContent = 'You exited fullscreen or switched away from the test window. Your saved answers are safe, '
        + 'but this is a fixed-time test: the clock keeps running and the test is submitted automatically at the end time. '
        + 'Please contact your test proctor — only an Institution Admin can unlock your attempt.';
    }
  }
  return true;
}

async function lock(reason) {
  if (!S.armed || S.finishing || (S.attempt && S.attempt.status !== 'in_progress')) return;
  S.armed = false;
  S.attempt.status = 'locked';
  showLocked();
  try { syncTime((await api('/exam/lock', { method: 'POST', body: { reason } })).attempt); showLocked(); }
  catch (e) { handleFatal(e); }
}

// ---------------------------------------------------------------- submit
function openSubmitConfirm() {
  const n = S.qs.filter(x => x.choice !== null).length, flagged = S.qs.filter(x => x.flagged).length;
  $('submitMsg').textContent = `You've answered ${n} of ${S.qs.length} questions${flagged ? ` (${flagged} flagged for review)` : ''}. `
    + 'Unanswered questions will be marked incorrect. This cannot be undone.';
  $('submitModal').classList.add('open');
}

async function submitNow() {
  const btn = $('submitConfirm');
  btn.disabled = true; btn.textContent = 'Submitting…';
  for (let i = 0; i < 20 && (S.pending.size || S.flushing); i++) {    // let the last answers reach the server first
    flush();
    await new Promise(r => setTimeout(r, 250));
  }
  try { await api('/exam/submit', { method: 'POST' }); toResult(); }
  catch (e) {
    if (handleFatal(e) !== false) return;
    btn.disabled = false; btn.textContent = 'Submit';
    $('submitMsg').textContent = e.message + ' Please try again.';
  }
}

// ---------------------------------------------------------------- start
document.addEventListener('DOMContentLoaded', async () => {
  let data, me;
  try {
    [data, { candidate: me }] = await Promise.all([api('/exam/paper'), api('/candidate/me')]);
  } catch (e) {
    if (handleFatal(e) === false) $('loadMsg').textContent = e.message;
    return;
  }
  if (data.attempt.status === 'submitted') return toResult();
  S.qs = data.questions;
  syncTime(data.attempt);
  $('loadMsg').style.display = 'none';
  $('testTitle').textContent = `${me.department.name} · ${me.test.name}`;
  document.title = `${me.test.name} — In Progress`;
  const first = S.qs.findIndex(q => q.choice === null);
  S.cur = first === -1 ? 0 : first;
  render(); setSaveState();

  // clicks (no inline handlers, so question text can never run as code)
  $('optList').addEventListener('click', e => { const o = e.target.closest('.opt'); if (o) pick(+o.dataset.j); });
  $('qGrid').addEventListener('click', e => { const d = e.target.closest('.q-dot'); if (d) jump(+d.dataset.i); });
  $('secTabs').addEventListener('click', e => { const t = e.target.closest('.sec-tab'); if (t) jump(+t.dataset.i); });
  $('flagBtn').addEventListener('click', toggleFlag);
  $('prevBtn').addEventListener('click', () => go(-1));
  $('nextBtn').addEventListener('click', () => go(1));
  $('clearBtn').addEventListener('click', clearAns);
  $('submitOpen').addEventListener('click', openSubmitConfirm);
  $('submitCancel').addEventListener('click', () => $('submitModal').classList.remove('open'));
  $('submitConfirm').addEventListener('click', submitNow);
  $('fsBtn').addEventListener('click', enterTest);

  if (data.attempt.status === 'locked') showLocked();
  else showFsGate(data.attempt.answered_count ? 'Continue your test' : 'Enter fullscreen to begin');

  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) lock('fullscreen_exit'); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) lock('tab_hidden'); });
  window.addEventListener('online', flush);

  tick(); setInterval(tick, 1000);
  setInterval(() => { if (S.attempt.status === 'locked') resync(); }, 10000);
  setInterval(resync, 30000);
});
