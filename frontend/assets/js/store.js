// ============================================================
// Shared demo store (localStorage) — stands in for the backend
// ============================================================
const AA = {
  LEVELS: ['Undergraduate', 'Masters', 'PhD'],
  get(k, d) { try { const v = localStorage.getItem('aa_' + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('aa_' + k, JSON.stringify(v)); } catch (e) {} },
  uid() { return Math.random().toString(36).slice(2, 8); },
  depts() {
    return this.get('depts', [
      { id: 'gen', name: 'General Test (all candidates)', level: 'Undergraduate', mode: 'general', subjects: ['Mathematics', 'English'] },
      { id: 'pe', name: 'Pre-Engineering', level: 'Undergraduate', mode: 'field', subjects: ['Mathematics', 'Physics', 'Chemistry', 'English'] },
      { id: 'pm', name: 'Pre-Medical', level: 'Undergraduate', mode: 'field', subjects: ['Biology', 'Physics', 'Chemistry', 'English'] },
    ]);
  },
  saveDepts(d) { this.set('depts', d); },
  attempts() { return this.get('attempts', []); },
  saveAttempts(a) { this.set('attempts', a); },
  bank() { return this.get('bank', []); },
  saveBank(b) { this.set('bank', b); },
  signups() { return this.get('signups', []); },
  saveSignups(s) { this.set('signups', s); },
  esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); },
};

// Mock AI question generator (replace with real API call)
const AA_QGEN = {
  Mathematics: [['If 3x + 7 = 25, what is the value of x?', ['4', '5', '6', '7'], 2], ['What is the derivative of x² at x = 3?', ['3', '6', '9', '12'], 1], ['The sum of the first 10 natural numbers is:', ['45', '50', '55', '60'], 2], ['A train covers 120 km in 2 hours. Its speed in km/h is:', ['40', '50', '60', '80'], 2]],
  English: [['Choose the correct synonym of "abundant".', ['Scarce', 'Plentiful', 'Rare', 'Tiny'], 1], ['Pick the correctly punctuated sentence.', ['Its a fine day.', "It's a fine day.", 'Its\' a fine day.', "Its a fine day's."], 1], ['"The committee ___ decided." Fill in the blank.', ['have', 'has', 'are', 'were'], 1]],
  Physics: [['SI unit of force is:', ['Joule', 'Pascal', 'Newton', 'Watt'], 2], ['Speed of light in vacuum is approximately:', ['3×10⁶ m/s', '3×10⁸ m/s', '3×10⁵ m/s', '3×10¹⁰ m/s'], 1]],
  Chemistry: [['Atomic number of Carbon is:', ['4', '6', '8', '12'], 1], ['pH of a neutral solution at 25°C is:', ['0', '5', '7', '14'], 2]],
  Biology: [['Which organelle carries out photosynthesis?', ['Mitochondria', 'Nucleus', 'Chloroplast', 'Ribosome'], 2], ['DNA stands for:', ['Deoxyribonucleic acid', 'Diribonucleic acid', 'Dextro nucleic acid', 'None'], 0]],
};
function aaMakeQuestion(subject, type, marks, difficulty, i) {
  const pool = AA_QGEN[subject];
  if (type === 'True/False') return { id: AA.uid(), text: `${subject}: Statement ${i + 1} is generally considered correct.`, options: ['True', 'False'], answer: i % 2, subject, type, marks, difficulty, status: 'pending' };
  if (pool) { const t = pool[i % pool.length]; return { id: AA.uid(), text: t[0] + (i >= pool.length ? ` (variant ${Math.floor(i / pool.length) + 1})` : ''), options: t[1], answer: t[2], subject, type, marks, difficulty, status: 'pending' }; }
  return { id: AA.uid(), text: `Sample ${subject} question ${i + 1} — which option is correct?`, options: ['Option A', 'Option B', 'Option C', 'Option D'], answer: i % 4, subject, type, marks, difficulty, status: 'pending' };
}

// Terminology: "Field" for Undergraduate, "Department" for Masters / PhD
AA.term = function (level, plural) {
  const w = level === 'Undergraduate' ? 'Field' : level ? 'Department' : 'Field / Department';
  return plural ? (w === 'Department' ? 'Departments' : w === 'Field' ? 'Fields' : 'Fields / Departments') : w;
};
AA.hash = s => [...s].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
// Demo candidate counts (would come from the roster)
AA.candidates = name => ({ 'Pre-Engineering': 340, 'Pre-Medical': 298, 'Computer Science': 412, 'Commerce': 234 })[name] || 60 + AA.hash(name) % 340;
AA.seedQ = [
  { id: 's1', text: 'Which structure in a plant cell is primarily responsible for photosynthesis?', dept: 'Pre-Medical', level: 'Undergraduate', subject: 'Biology', difficulty: 'Easy', type: 'MCQ', marks: 1, status: 'approved' },
  { id: 's2', text: 'A projectile is launched at 30° with speed 40 m/s. What maximum height does it reach? (g = 10 m/s²)', dept: 'Pre-Engineering', level: 'Undergraduate', subject: 'Physics', difficulty: 'Hard', type: 'MCQ', marks: 2, status: 'approved' },
  { id: 's3', text: 'Choose the option that best replaces: "The committee have decided to postpone the meeting."', dept: 'General Test (all candidates)', level: 'Undergraduate', subject: 'English', difficulty: 'Medium', type: 'MCQ', marks: 1, status: 'approved' },
  { id: 's4', text: 'Evaluate the asymptotic complexity of an unbalanced BST search in the worst case.', dept: 'Data Science', level: 'Masters', subject: 'Algorithms', difficulty: 'Medium', type: 'MCQ', marks: 2, status: 'approved' },
  { id: 's5', text: 'A binary search tree with n nodes always has height log₂(n).', dept: 'Computer Science', level: 'Undergraduate', subject: 'Computer Science', difficulty: 'Medium', type: 'True/False', marks: 1, status: 'retired' },
];
