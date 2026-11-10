// ============================================================
// Gateway (index.html) — page script
// ============================================================

// Pipeline: how one aptitude test runs, from PDF to report (descriptions summarise what the product already does)
const GATEWAY_STEPS = [
  { icon: 'sparkles', label: 'Generate',   text: 'Upload PDFs and the AI drafts questions.',         tone: 'c-cyan' },
  { icon: 'drafts',   label: 'Review',     text: 'Approve, edit or reject every draft.',             tone: 'c-amber' },
  { icon: 'tests',    label: 'Build test', text: 'Compose the paper and set the schedule.',          tone: 'c-indigo' },
  { icon: 'roster',   label: 'Roster',     text: 'Import candidates and print their slips.',         tone: 'c-violet' },
  { icon: 'play',     label: 'Take test',  text: 'Fullscreen exam with live monitoring.',            tone: 'c-teal' },
  { icon: 'reports',  label: 'Report',     text: 'Scores, analytics, CSV and result emails.',        tone: 'c-emerald' },
];

document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('pipeline');
  if (!el) return;
  el.innerHTML = GATEWAY_STEPS.map((s, i) => `
    <div class="pipe-step">
      <div class="pipe-node">
        <span class="pipe-num">${i + 1}</span>
        <div class="ic ${s.tone}">${AIcon(s.icon)}</div>
        <span class="lb">${s.label}</span>
        <span class="tx">${s.text}</span>
      </div>
    </div>
  `).join('');
});
