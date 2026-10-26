// candidate-start.html — instructions + fixed-time gate
// Schedule comes from the published test (AA store). Add ?demo=1 to bypass the time gate while previewing.
function schedTimes(sc) {
  const [y, m, d] = sc.date.split('-').map(Number), at = t => { const [h, mi] = t.split(':').map(Number); return new Date(y, m - 1, d, h, mi, 0); };
  return { start: at(sc.start), end: at(sc.end) };
}
document.addEventListener('DOMContentLoaded', () => {
  const ack = document.getElementById('ack'), startBtn = document.getElementById('startBtn'), banner = document.getElementById('schedBanner');
  if (!ack || !startBtn) return;
  const sc = AA.get('schedule', null), demo = new URLSearchParams(location.search).has('demo');
  const p = n => String(n).padStart(2, '0');
  let gate = { open: true, msg: '' };

  function refresh() {
    let open = true;
    if (sc && !demo) {
      const { start, end } = schedTimes(sc), now = new Date();
      banner.style.display = 'flex';
      const range = `${start.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} – ${end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`;
      if (now < start) {
        const s = Math.floor((start - now) / 1000);
        open = false;
        banner.innerHTML = `<span class="ic">⏳</span><div><b>The test hasn't started yet</b><p>Scheduled ${range} on ${sc.date}. You can enter in <b style="color:#fff;">${Math.floor(s / 3600)}:${p(Math.floor(s % 3600 / 60))}:${p(s % 60)}</b>.</p></div>`;
      } else if (now >= end) {
        open = false;
        banner.innerHTML = `<span class="ic">🏁</span><div><b>This test has ended</b><p>The window closed at ${end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}. Contact your institution if you missed it.</p></div>`;
      } else if (sc.mode === 'fixed') {
        const mins = Math.round((end - now) / 60000);
        banner.innerHTML = `<span class="ic">⏰</span><div><b>Fixed-time test · ends at ${end.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</b><p>Your test will be submitted automatically at the end time. You have <b style="color:#fff;">${mins} min</b> remaining, regardless of when you start.</p></div>`;
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
