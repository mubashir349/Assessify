// ============================================================
// candidate-result.html — page script
// ============================================================

function toggleMode() {
  const imm = document.getElementById('immediateCard');
  const sch = document.getElementById('scheduledCard');
  const btn = document.getElementById('modeBtn');
  const showingImmediate = imm.style.display !== 'none';
  imm.style.display = showingImmediate ? 'none' : 'block';
  sch.style.display = showingImmediate ? 'block' : 'none';
  btn.textContent = showingImmediate ? 'Preview: immediate-score mode' : 'Preview: scheduled-release mode';
}
