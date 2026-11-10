// candidate-result.html — after submitting (Phase 6). GET /exam/result.
// "immediate" tests show the score (scored on the server); "scheduled" tests show when it will be emailed.
// The page never shows which questions were right: other candidates may still be taking a flexible test.
const $ = id => document.getElementById(id);
const when = s => new Date(s).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
const rows = list => list.map(([k, v]) => `<div class="res-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
const wait = ms => new Promise(r => setTimeout(r, ms));

/** Loads the result + the candidate. Returns null when the page already moved on (redirect or error shown). */
async function loadResult(tries = 0) {
  try {
    const [res, { candidate }] = await Promise.all([api('/exam/result'), api('/candidate/me')]);
    return { res, me: candidate };
  } catch (e) {
    if (e.status === 401 || e.status === 403) { window.location.replace('candidate-login.html'); return null; }
    if (e.code === 'ATTEMPT_NOT_STARTED') { window.location.replace('candidate-start.html'); return null; }
    // NOT_SUBMITTED right at the end time (a clock a second ahead): ask again, then go back to the paper
    if (e.code === 'NOT_SUBMITTED' && tries < 3) { await wait(2000); return loadResult(tries + 1); }
    if (e.code === 'NOT_SUBMITTED') { window.location.replace('candidate-test.html'); return null; }
    $('loadingCard').innerHTML = `<p style="color:var(--danger-text);">${esc(e.message)}</p>`;
    return null;
  }
}

function showScore(s, who, submitted) {
  $('pct').textContent = `${Math.round(s.percent)}%`;
  $('marks').textContent = `${s.score} / ${s.max_score}`;
  $('ring').setAttribute('stroke-dashoffset', String(414.7 * (1 - s.percent / 100)));
  const bySubject = s.by_subject.length > 1 ? s.by_subject.map(b => [b.subject, `${b.score} / ${b.max_score}`]) : [];
  $('immediateRows').innerHTML = rows([...who, submitted, ['Answered', `${s.answered} of ${s.questions}`], ...bySubject]);
  $('immediateCard').style.display = 'block';
}

function showScheduled(res, who, submitted) {
  const release = res.release_on
    ? new Date(res.release_on + 'T00:00:00').toLocaleDateString([], { dateStyle: 'medium' })
    : 'To be announced';
  $('scheduledRows').innerHTML = rows([...who, submitted, ['Result will be sent to', res.email || 'your institution (no email on the roster)'], ['Release date', release]]);
  $('scheduledCard').style.display = 'block';
}

document.addEventListener('DOMContentLoaded', async () => {
  $('signOut').addEventListener('click', async () => {
    try { await api('/candidate/logout', { method: 'POST' }); } catch (e) { /* leave anyway */ }
    window.location.replace('candidate-login.html');
  });

  const loaded = await loadResult();
  if (!loaded) return;
  const { res, me } = loaded;
  const a = res.attempt, timeUp = a.submit_reason === 'time_up';
  $('candInst').textContent = `${me.institution.name} · ${me.test.name}`;
  $('loadingCard').style.display = 'none';
  const term = me.test.level === 'Undergraduate' ? 'Field' : 'Department';
  const who = [['Candidate', `${me.full_name}${me.roll_number ? ' · ' + me.roll_number : ''}`], [term, me.department.name]];
  const submitted = ['Submitted', when(a.submitted_at) + (timeUp ? ' (time ran out)' : '')];
  if (timeUp) {
    document.querySelectorAll('.res-title').forEach(el => { el.textContent = 'Time is up — test submitted'; });
    document.querySelectorAll('.res-note').forEach(el => el.prepend('Your answers saved before the end time were submitted automatically. '));
  }
  if (res.score) showScore(res.score, who, submitted);
  else showScheduled(res, who, submitted);
});
