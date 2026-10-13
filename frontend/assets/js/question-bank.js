// question-bank.html — approved questions only (seed samples + Draft Review approvals)
const SEED_Q = AA.seedQ;
const bank = () => SEED_Q.concat(AA.bank());
function bars(el, counts, total) {
  document.getElementById(el).innerHTML = Object.entries(counts).map(([k, v]) => { const p = total ? Math.round(v / total * 100) : 0;
    return `<div class="bar-row"><span class="lb">${k}</span><span class="tr"><span class="fl" style="width:${p}%;display:block"></span></span><span class="v">${p}%</span></div>`; }).join('');
}
function insights(all) {
  const act = all.filter(q => q.status !== 'retired'), t = act.length;
  const d = { Easy: 0, Medium: 0, Hard: 0 }, l = { Undergraduate: 0, Masters: 0, PhD: 0 };
  act.forEach(q => { d[q.difficulty]++; l[q.level]++; });
  bars('diffBars', d, t); bars('lvlBars', l, t);
  const tips = [];
  if (t && d.Hard / t < 0.2) tips.push(['⚠', 'Only ' + Math.round(d.Hard / t * 100) + '% hard questions — add more to separate top candidates.']);
  if (t && d.Easy / t > 0.5) tips.push(['⚠', 'Bank skews easy — consider generating Medium/Hard drafts.']);
  const thin = AA.LEVELS.filter(x => l[x] === 0); if (thin.length) tips.push(['🎯', 'No questions yet for ' + thin.join(', ') + '.']);
  const seen = {}, dup = act.filter(q => { const k = q.text.toLowerCase().slice(0, 40); return seen[k]++; }).length;
  if (dup) tips.push(['♻', dup + ' near-duplicate question(s) detected — review and retire.']);
  tips.push(['✦', t + ' active questions across ' + new Set(act.map(q => q.subject)).size + ' subjects.']);
  document.getElementById('aiTips').innerHTML = tips.slice(0, 4).map(x => `<div class="ai-item"><span class="ic">${x[0]}</span><span>${x[1]}</span></div>`).join('');
}
function renderBank() {
  const all = bank(); insights(all);
  const v = id => document.getElementById(id).value, q = v('fQ').toLowerCase();
  const list = all.filter(x => (v('fStat') === 'retired' ? x.status === 'retired' : x.status !== 'retired') && (!v('fDept') || x.dept === v('fDept')) && (!v('fLevel') || x.level === v('fLevel')) && (!v('fSubj') || x.subject === v('fSubj')) && (!v('fDiff') || x.difficulty === v('fDiff')) && x.text.toLowerCase().includes(q));
  document.getElementById('bankList').innerHTML = list.map(x => `
    <div class="a-card qrow"><div class="qbody"><p class="qtext">${AA.esc(x.text)}</p>
      <div class="qmeta"><span class="badge ${x.status === 'retired' ? 'badge-retired' : 'badge-approved'}">${x.status === 'retired' ? 'Retired' : 'Approved'}</span>
      <span class="a-chip">${AA.esc(x.dept)}</span><span class="a-chip">${x.level}</span><span class="a-chip">${AA.esc(x.subject)}</span><span class="a-chip">${x.difficulty} · ${x.type}</span><span class="a-chip">${x.marks} mark${x.marks > 1 ? 's' : ''}</span></div></div>
      <div class="qactions"><button class="a-btn a-btn-ghost a-btn-sm" onclick="aToast('Edit from Draft Review keeps an audit trail.','ℹ')">Edit</button>
      ${x.status === 'retired' ? `<button class="a-btn a-btn-ghost a-btn-sm" onclick="setStat('${x.id}','approved')">Restore</button>` : `<button class="a-btn a-btn-danger a-btn-sm" onclick="setStat('${x.id}','retired')">Retire</button>`}</div></div>`).join('') || '<div class="a-card a-empty">No approved questions match. Generate drafts and approve them in Draft Review.</div>';
}
function setStat(id, st) {
  const s = SEED_Q.find(x => x.id === id); if (s) s.status = st; else { const b = AA.bank(); const x = b.find(i => i.id === id); if (x) x.status = st; AA.saveBank(b); }
  renderBank(); aToast(st === 'retired' ? 'Question retired.' : 'Question restored.');
}
function relabel() {
  const lv = fLevel.value, first = fDept.options[0];
  first.textContent = 'All ' + AA.term(lv, true).toLowerCase();
}
document.addEventListener('DOMContentLoaded', () => {
  fLevel.addEventListener('change', relabel); relabel();
  const all = bank();
  fDept.innerHTML += [...new Set(all.map(x => x.dept))].map(x => `<option>${AA.esc(x)}</option>`).join('');
  fSubj.innerHTML += [...new Set(all.map(x => x.subject))].map(x => `<option>${AA.esc(x)}</option>`).join('');
  renderBank();
});
