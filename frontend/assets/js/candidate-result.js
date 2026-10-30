// candidate-result.html — after submitting (Phase 6). GET /exam/result.
// "immediate" tests show the score (scored on the server); "scheduled" tests show when it will be emailed.
// The page never shows which questions were right: other candidates may still be taking a flexible test.
document.addEventListener('DOMContentLoaded', async () => {
  const $ = id => document.getElementById(id);
  const when = s => new Date(s).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  const rows = list => list.map(([k, v]) => `<div class="res-row"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
  $('signOut').addEventListener('click', async () => {
    try { await api('/candidate/logout', { method: 'POST' }); } catch (e) { /* leave anyway */ }
    window.location.replace('candidate-login.html');
  });

  let res, me;
  for (let tries = 0; ; tries++) {
    try { [res, { candidate: me }] = await Promise.all([api('/exam/result'), api('/candidate/me')]); break; }
    catch (e) {
      if (e.status === 401 || e.status === 403) return window.location.replace('candidate-login.html');
      if (e.code === 'ATTEMPT_NOT_STARTED') return window.location.replace('candidate-start.html');
      // NOT_SUBMITTED right at the end time (a clock a second ahead): ask again, then go back to the paper
      if (e.code === 'NOT_SUBMITTED' && tries < 3) { await new Promise(r => setTimeout(r, 2000)); continue; }
      if (e.code === 'NOT_SUBMITTED') return window.location.replace('candidate-test.html');
      $('loadingCard').innerHTML = `<p style="color:#f87171;">${esc(e.message)}</p>`;
      return;
    }
  }

  const a = res.attempt;
  $('candInst').textContent = `${me.institution.name} · ${me.test.name}`;
  $('loadingCard').style.display = 'none';
  const who = [['Candidate', `${me.full_name} · ${me.roll_number}`], [me.test.level === 'Undergraduate' ? 'Field' : 'Department', me.department.name]];
  const submitted = ['Submitted', when(a.submitted_at) + (a.submit_reason === 'time_up' ? ' (time ran out)' : '')];
  if (a.submit_reason === 'time_up') {
    document.querySelectorAll('.res-title').forEach(el => el.textContent = 'Time is up — test submitted');
    document.querySelectorAll('.res-note').forEach(el => el.insertAdjacentText('afterbegin', 'Your answers saved before the end time were submitted automatically. '));
  }

  if (res.score) {
    const s = res.score;
    $('pct').textContent = `${Math.round(s.percent)}%`;
    $('marks').textContent = `${s.score} / ${s.max_score}`;
    $('ring').setAttribute('stroke-dashoffset', String(414.7 * (1 - s.percent / 100)));
    $('immediateRows').innerHTML = rows([...who, submitted, ['Answered', `${s.answered} of ${s.questions}`],
      ...(s.by_subject.length > 1 ? s.by_subject.map(b => [b.subject, `${b.score} / ${b.max_score}`]) : [])]);
    $('immediateCard').style.display = 'block';
  } else {
    $('scheduledRows').innerHTML = rows([...who, submitted, ['Result will be sent to', res.email],
      ['Release date', res.release_on ? new Date(res.release_on + 'T00:00:00').toLocaleDateString([], { dateStyle: 'medium' }) : 'To be announced']]);
    $('scheduledCard').style.display = 'block';
  }
});
