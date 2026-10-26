// ============================================================
// Shared demo store — ONLY for pages whose backend phase is not built yet (candidates, test taking, reports).
// NOT stored here any more (they come from the API): accounts, institutions, fields / departments (Phase 1-2),
// question generation, draft review and the question bank (Phase 3), creating tests (Phase 4) and the candidate
// roster + candidate login (Phase 5).
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
  signups() { return this.get('signups', []); },
  saveSignups(s) { this.set('signups', s); },
  esc(s) { return String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); },
};

// Terminology: "Field" for Undergraduate, "Department" for Masters / PhD
AA.term = function (level, plural) {
  const w = level === 'Undergraduate' ? 'Field' : level ? 'Department' : 'Field / Department';
  return plural ? (w === 'Department' ? 'Departments' : w === 'Field' ? 'Fields' : 'Fields / Departments') : w;
};
