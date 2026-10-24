// ============================================================
// Shared demo store — ONLY for pages whose backend phase is not built yet (tests, candidates, reports).
// NOT stored here any more (they come from the API): accounts, institutions, fields / departments (Phase 1-2)
// and question generation, draft review and the question bank (Phase 3).
// ============================================================
const AA = {
  LEVELS: ['Undergraduate', 'Masters', 'PhD'],
  get(k, d) { try { const v = localStorage.getItem('aa_' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('aa_' + k, JSON.stringify(v)); } catch (e) {} },
  uid() { return Math.random().toString(36).slice(2, 8); },
  // Fields / departments live in the database. This is only a read cache of what GET /departments returned,
  // kept in sessionStorage so the later-phase pages (generate, tests...) can read it synchronously.
  depts() { try { return JSON.parse(sessionStorage.getItem('aa_depts_cache') || '[]'); } catch (e) { return []; } },
  async syncDepts() {
    const { items } = await api('/departments');
    const list = items.map(d => ({ ...d, id: String(d.id) }));
    try { sessionStorage.setItem('aa_depts_cache', JSON.stringify(list)); } catch (e) {}
    return list;
  },
  // Phase 4 demo only (create-test.js). The real, approved question bank is GET /api/v1/questions/bank.
  bank() { return this.get('bank', []); },
  saveBank(b) { this.set('bank', b); },
  signups() { return this.get('signups', []); },
  saveSignups(s) { this.set('signups', s); },
  esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); },
};

// Terminology: "Field" for Undergraduate, "Department" for Masters / PhD
AA.term = function (level, plural) {
  const w = level === 'Undergraduate' ? 'Field' : level ? 'Department' : 'Field / Department';
  return plural ? (w === 'Department' ? 'Departments' : w === 'Field' ? 'Fields' : 'Fields / Departments') : w;
};
AA.hash = s => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
// Demo candidate counts (would come from the roster)
AA.candidates = name => ({ 'Pre-Engineering': 340, 'Pre-Medical': 298, 'Computer Science': 412, 'Commerce': 234 })[name] || 60 + AA.hash(name) % 340;
// Phase 4 demo questions for create-test.js only (not shown in the Phase 3 Question Bank).
AA.seedQ = [
  { id: 's1', text: 'Which structure in a plant cell is primarily responsible for photosynthesis?', dept: 'Pre-Medical', level: 'Undergraduate', subject: 'Biology', difficulty: 'Easy', type: 'MCQ', marks: 1, status: 'approved' },
  { id: 's2', text: 'A projectile is launched at 30° with speed 40 m/s. What maximum height does it reach? (g = 10 m/s²)', dept: 'Pre-Engineering', level: 'Undergraduate', subject: 'Physics', difficulty: 'Hard', type: 'MCQ', marks: 2, status: 'approved' },
  { id: 's3', text: 'Choose the option that best replaces: "The committee have decided to postpone the meeting."', dept: 'General Test (all candidates)', level: 'Undergraduate', subject: 'English', difficulty: 'Medium', type: 'MCQ', marks: 1, status: 'approved' },
  { id: 's4', text: 'Evaluate the asymptotic complexity of an unbalanced BST search in the worst case.', dept: 'Data Science', level: 'Masters', subject: 'Algorithms', difficulty: 'Medium', type: 'MCQ', marks: 2, status: 'approved' },
  { id: 's5', text: 'A binary search tree with n nodes always has height log₂(n).', dept: 'Computer Science', level: 'Undergraduate', subject: 'Computer Science', difficulty: 'Medium', type: 'True/False', marks: 1, status: 'retired' },
];
