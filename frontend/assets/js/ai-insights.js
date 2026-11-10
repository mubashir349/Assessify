// ai-insights.js — shared "Ask AI" button for the Reports and Question Bank pages (Phase 7).
// POST /reports/ai-summary {scope, test_id?}. The AI only gets numbers (no names, emails or answers).
async function askAi(body, target, btn) {
  const old = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Thinking…';
  target.innerHTML = '<div class="ai-item"><span class="ic"><i data-icon="sparkles"></i></span><span>Asking the AI…</span></div>';
  try {
    const d = await api('/reports/ai-summary', { method: 'POST', body });
    target.innerHTML = d.insights.map(t => `<div class="ai-item"><span class="ic"><i data-icon="sparkles"></i></span><span>${esc(t)}</span></div>`).join('')
      + `<div class="muted ai-by">Written by ${esc(d.provider)} · ${esc(d.model)} from the numbers above. Check before acting on it.</div>`;
  } catch (e) {
    target.innerHTML = `<div class="ai-item"><span class="ic"><i data-icon="warn"></i></span><span>${esc(e.message)}</span></div>`;
    if (e.status === 401) handleApiError(e);
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}
