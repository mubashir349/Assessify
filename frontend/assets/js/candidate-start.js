// candidate-start.html — instructions + the time gate (Phase 6).
// GET /candidate/me gives the candidate and test; GET /exam gives the gate decided by the SERVER clock
// (state: not_started | open | resume | submitted | closed). The countdown runs from the server's seconds_until_start,
// so a wrong clock on the candidate's PC can't open the test early. POST /exam/start refuses early starts anyway.
document.addEventListener('DOMContentLoaded', async () => {
  const ack = document.getElementById('ack'), startBtn = document.getElementById('startBtn'), banner = document.getElementById('schedBanner');
  if (!ack || !startBtn) return;
  const p = n => String(n).padStart(2, '0');
  const time = d => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const say = (icon, title, text) => {
    banner.style.display = 'flex';
    banner.innerHTML = `<span class="ic">${icon}</span><div><b>${title}</b><p>${text}</p></div>`;
  };
  let me, gate, opensAtMs = 0, refetching = false;

  async function loadGate() {
    ({ gate } = await api('/exam'));
    opensAtMs = Date.now() + gate.seconds_until_start * 1000;
    if (gate.state === 'submitted') window.location.replace('candidate-result.html');
  }

  try { [{ candidate: me }] = await Promise.all([api('/candidate/me'), loadGate()]); }
  catch (e) {
    if (e.status === 401 || e.status === 403) return window.location.replace('candidate-login.html');
    return say('⚠', 'Cannot load your test', esc(e.message));
  }

  const t = me.test, sc = t.schedule;
  document.getElementById('candInst').innerHTML = `${esc(me.institution.name)} · ${esc(t.name)} · <a href="#" id="signOut" style="color:var(--apt-primary);">Not ${esc(me.full_name.split(' ')[0])}? Sign out</a>`;
  document.getElementById('welcome').textContent = `Welcome, ${me.full_name}${me.roll_number ? ' · ' + me.roll_number : ''}`;
  document.getElementById('candDept').textContent = me.department.name;
  document.getElementById('mSubj').textContent = t.subjects.join(', ') || '—';
  document.getElementById('mCount').textContent = t.question_count;
  document.getElementById('mTime').textContent = sc.timing_mode === 'fixed' ? `until ${time(new Date(sc.ends_at))} (fixed end)` : `${sc.duration_minutes} minutes`;
  if (sc.timing_mode === 'fixed') {
    document.getElementById('lockRule').textContent = 'Pressing Esc, switching tabs, or minimizing the window locks your test instantly. '
      + 'This is a fixed-time test, so the clock keeps running while it is locked. Only your test proctor / Institution Admin can unlock it.';
  }
  document.getElementById('signOut').addEventListener('click', async e => {
    e.preventDefault();
    try { await api('/candidate/logout', { method: 'POST' }); } catch (err) { /* leave anyway */ }
    window.location.replace('candidate-login.html');
  });

  const start = new Date(gate.starts_at), end = new Date(gate.ends_at), range = `${time(start)} – ${time(end)}`;
  function refresh() {
    let open = gate.can_start;
    if (gate.state === 'not_started') {
      const s = Math.max(0, Math.ceil((opensAtMs - Date.now()) / 1000));
      say('⏳', "The test hasn't started yet", `Scheduled ${range} on ${start.toLocaleDateString()}. You can start in <b style="color:#fff;">${Math.floor(s / 3600)}:${p(Math.floor(s % 3600 / 60))}:${p(s % 60)}</b>.`);
      if (s === 0 && !refetching) {          // ask the server, it decides
        refetching = true;
        loadGate().catch(() => {}).finally(() => { refetching = false; refresh(); });
      }
    } else if (gate.state === 'closed') {
      say('🏁', 'This test has ended', `The window closed at ${time(end)}. Contact your institution if you missed it.`);
    } else if (gate.state === 'resume') {
      const a = gate.attempt;
      startBtn.textContent = 'Resume test →';
      say(a.status === 'locked' ? '🔒' : '↩', a.status === 'locked' ? 'Your test is locked' : 'You have already started',
        a.status === 'locked' ? 'Please ask your proctor to unlock it. You can open the test page to see when it is unlocked.'
          : `${a.answered_count} of ${a.question_count} answered and saved. Your time kept running while you were away.`);
    } else if (sc.timing_mode === 'fixed') {
      say('⏰', `Fixed-time test · ends at ${time(end)}`, `Your test will be submitted automatically at the end time. You have <b style="color:#fff;">${gate.minutes_if_started_now} min</b> if you start now, regardless of when you start.`);
    } else banner.style.display = 'none';
    startBtn.disabled = !(open && ack.checked);
  }
  ack.addEventListener('change', refresh);
  refresh(); setInterval(refresh, 1000);

  startBtn.addEventListener('click', async () => {
    if (!gate.can_start) return;
    startBtn.disabled = true; startBtn.textContent = 'Building your paper…';
    try {
      await api('/exam/start', { method: 'POST' });
      window.location.href = 'candidate-test.html';
    } catch (e) {
      if (e.code === 'ALREADY_SUBMITTED') return window.location.replace('candidate-result.html');
      startBtn.textContent = 'Start test →';
      say('⚠', 'Could not start', esc(e.message));
      await loadGate().catch(() => {});
      refresh();
    }
  });
});
