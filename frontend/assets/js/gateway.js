// ============================================================
// Gateway (index.html) — page script
// ============================================================

// Pipeline strip: Generate -> Review -> Validate -> Deliver -> Report
const GATEWAY_STEPS = [
  { icon: '✦', label: 'Generate', grad: ['#6366f1', '#7c3aed'] },
  { icon: '◎', label: 'Review',   grad: ['#7c3aed', '#9333ea'] },
  { icon: '▦', label: 'Validate', grad: ['#9333ea', '#c026d3'] },
  { icon: '📋', label: 'Deliver',  grad: ['#06b6d4', '#0891b2'] },
  { icon: '📊', label: 'Report',   grad: ['#22c55e', '#0d9488'] },
];

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('pipeline');
  if (!el) return;
  el.innerHTML = GATEWAY_STEPS.map((s, i) => `
    <div class="pipe-step">
      <div class="pipe-node">
        <div class="ic" style="background:linear-gradient(135deg, ${s.grad[0]}, ${s.grad[1]});">${s.icon}</div>
        <span class="lb">${s.label}</span>
      </div>
      ${i < GATEWAY_STEPS.length - 1 ? '<div class="pipe-link"></div>' : ''}
    </div>
  `).join('');
});
