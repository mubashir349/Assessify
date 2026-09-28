// ============================================================
// candidate-test.html — page script
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  // ---- Question navigator (demo data: 60 questions, some pre-answered) ----
  const total = 60, current = 7;
  const answered = new Set([1,2,3,4,5,6,9,12,15,18,20,22,25,30,33,35,38,40,42,45,47]);
  const grid = document.getElementById('qGrid');
  for (let i = 1; i <= total; i++) {
    const d = document.createElement('div');
    d.className = 'q-dot' + (answered.has(i) ? ' answered' : '') + (i === current ? ' current' : '');
    d.textContent = i;
    grid.appendChild(d);
  }
  document.getElementById('progressLabel').textContent = `${answered.size} of ${total} answered`;

  // ---- Countdown timer ----
  let secondsLeft = 2 * 3600 + 30 * 60; // 02:30:00
  const timerEl = document.getElementById('timer');
  const overlay = document.getElementById('lockOverlay');
  function tick() {
    if (overlay.classList.contains('show')) return; // pauses while locked
    secondsLeft--;
    const h = String(Math.floor(secondsLeft / 3600)).padStart(2, '0');
    const m = String(Math.floor((secondsLeft % 3600) / 60)).padStart(2, '0');
    const s = String(secondsLeft % 60).padStart(2, '0');
    timerEl.textContent = `${h}:${m}:${s}`;
    timerEl.classList.toggle('low', secondsLeft < 300);
  }
  setInterval(tick, 1000);

  // ---- Fullscreen / focus-loss detection -> immediate lock (FR-4.14.45-49) ----
  function triggerLock() {
    if (overlay.classList.contains('show')) return;
    overlay.classList.add('show');
    document.getElementById('lockTime').textContent = new Date().toLocaleTimeString();
  }
  document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) triggerLock(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) triggerLock(); });
  window.addEventListener('blur', () => triggerLock());

  // Demo helper: press "L" to preview the lock overlay without actually leaving fullscreen
  document.addEventListener('keydown', (e) => { if (e.key === 'l' || e.key === 'L') triggerLock(); });
});

function selectOpt(el) {
  document.querySelectorAll('#optList .opt').forEach(o => o.classList.remove('sel'));
  el.classList.add('sel');
}

function openSubmitConfirm() { document.getElementById('submitModal').classList.add('open'); }
function closeSubmitConfirm() { document.getElementById('submitModal').classList.remove('open'); }
function aToastCand(msg) { if (typeof aToast === 'function') aToast(msg); }
