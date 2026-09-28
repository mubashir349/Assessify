// ============================================================
// candidate-start.html — page script
// ============================================================

document.addEventListener('DOMContentLoaded', () => {
  const ack = document.getElementById('ack');
  const startBtn = document.getElementById('startBtn');
  if (!ack || !startBtn) return;

  ack.addEventListener('change', () => { startBtn.disabled = !ack.checked; });

  startBtn.addEventListener('click', () => {
    const el = document.documentElement;
    const goToTest = () => window.location.href = 'candidate-test.html';
    if (el.requestFullscreen) {
      el.requestFullscreen().then(goToTest).catch(goToTest);
    } else {
      goToTest();
    }
  });
});
