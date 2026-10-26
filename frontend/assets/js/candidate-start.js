// candidate-start.html — instructions + time gate for the signed-in candidate (GET /candidate/me, Phase 5).
// Times come from the published test's schedule (UTC on the wire, shown in the candidate's local time).
// Phase 6 enforces the gate on the server too; this page is only the friendly countdown.
// Add ?demo=1 to bypass the time gate while previewing.
document.addEventListener('DOMContentLoaded', async () => {
  const ack = document.getElementById('ack'), startBtn = document.getElementById('startBtn'), banner = document.getElementById('schedBanner');
  if (!ack || !startBtn) return;
  const demo = new URLSearchParams(location.search).has('demo');
  const p = n => String(n).padStart(2, '0');
  const time = d => d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  let me, gate = { open: false };

  try { ({ candidate: me } = await api('/candidate/me')); }
  catch (e) {
    if (e.status === 401 || e.status === 403) return window.location.replace('candidate-login.html');
    banner.style.display = 'flex';
    banner.innerHTML = `<span class="ic">⚠</span><div><b>Cannot load your test</b><p>${esc(e.message)}</p></div>`;
    return;
  }

  const t = me.test, sc = t.schedule;
  document.getElementById('candInst').innerHTML = `${esc(me.institution.name)} · ${esc(t.name)} · <a href="#" id="signOut" style="color:var(--apt-primary);">Not ${esc(me.full_name.split(' ')[0])}? Sign out</a>`;
  document.getElementById('welcome').textContent = `Welcome, ${me.full_name} · ${me.roll_number}`;
  document.getElementById('candDept').textContent = me.department.name;
  document.getElementById('mSubj').textContent = t.subjects.join(', ') || '—';
  document.getElementById('mCount').textContent = t.question_count;
  document.getElementById('mTime').textContent = sc ? `${sc.duration_minutes} minutes` : '—';
  document.getElementById('signOut').addEventListener('click', async e => {
    e.preventDefault();
    try { await api('/candidate/logout', { method: 'POST' }); } catch (err) { /* leave anyway */ }
    window.location.replace('candidate-login.html');
  });

  const start = new Date(sc.starts_at), end = new Date(sc.ends_at);
  function refresh() {
    let open = true;
    if (!demo) {
      const now = new Date();
      banner.style.display = 'flex';
      const range = `${time(start)} – ${time(end)}`;
      if (now < start) {
        const s = Math.floor((start - now) / 1000);
        open = false;
        banner.innerHTML = `<span class="ic">⏳</span><div><b>The test hasn't started yet</b><p>Scheduled ${range} on ${start.toLocaleDateString()}. You can enter in <b style="color:#fff;">${Math.floor(s / 3600)}:${p(Math.floor(s % 3600 / 60))}:${p(s % 60)}</b>.</p></div>`;
      } else if (now >= end) {
        open = false;
        banner.innerHTML = `<span class="ic">🏁</span><div><b>This test has ended</b><p>The window closed at ${time(end)}. Contact your institution if you missed it.</p></div>`;
      } else if (sc.timing_mode === 'fixed') {
        const mins = Math.round((end - now) / 60000);
        banner.innerHTML = `<span class="ic">⏰</span><div><b>Fixed-time test · ends at ${time(end)}</b><p>Your test will be submitted automatically at the end time. You have <b style="color:#fff;">${mins} min</b> remaining, regardless of when you start.</p></div>`;
      } else banner.style.display = 'none';
    }
    startBtn.disabled = !(open && ack.checked);
    gate.open = open;
  }
  ack.addEventListener('change', refresh);
  refresh(); setInterval(refresh, 1000);

  startBtn.addEventListener('click', () => {
    if (!gate.open) return;
    const el = document.documentElement, go = () => window.location.href = 'candidate-test.html' + (demo ? '?demo=1' : '');
    el.requestFullscreen ? el.requestFullscreen().then(go).catch(go) : go();
  });
});
