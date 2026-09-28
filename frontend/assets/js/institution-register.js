// ============================================================
// institution-register.html — page script
// ============================================================

let fieldRowSeq = 0;

function fieldRowTemplate(id, index) {
  return `
    <div class="rep-row" data-id="${id}">
      <span class="rep-index">FIELD ${String(index).padStart(2, '0')}</span>
      <button type="button" class="rep-remove" title="Remove this field" data-remove="${id}">✕</button>
      <div class="field-row-grid">
        <div class="a-field">
          <label>Field / department name <span class="req">*</span></label>
          <input class="a-input f-name" placeholder="e.g. Pre-Engineering" />
        </div>
        <div class="a-field">
          <label>Expected candidates</label>
          <input class="a-input f-count" type="number" min="1" placeholder="e.g. 340" />
        </div>
        <div class="a-field">
          <label>Subjects tested</label>
          <input class="a-input f-subjects" placeholder="e.g. English, Maths, Physics" />
        </div>
      </div>
    </div>`;
}

function renumberRows() {
  document.querySelectorAll('#fieldRows .rep-row').forEach((row, i) => {
    row.querySelector('.rep-index').textContent = `FIELD ${String(i + 1).padStart(2, '0')}`;
  });
}

function addFieldRow() {
  const wrap = document.getElementById('fieldRows');
  fieldRowSeq++;
  wrap.insertAdjacentHTML('beforeend', fieldRowTemplate(fieldRowSeq, wrap.children.length + 1));
}

function markInvalid(el, bad) {
  el.classList.toggle('invalid', bad);
  return !bad;
}

document.addEventListener('DOMContentLoaded', () => {
  const wrap = document.getElementById('fieldRows');
  if (!wrap) return;

  // Start with two empty rows since most institutions test more than one field
  addFieldRow();
  addFieldRow();

  document.getElementById('addFieldBtn').addEventListener('click', addFieldRow);

  wrap.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-remove]');
    if (!btn) return;
    if (wrap.children.length === 1) return; // keep at least one field row
    btn.closest('.rep-row').remove();
    renumberRows();
  });

  // Clear red state as soon as the user types again
  document.getElementById('regForm').addEventListener('input', (e) => {
    e.target.classList.remove('invalid');
  });

  document.getElementById('regForm').addEventListener('submit', (e) => {
    e.preventDefault();

    const required = ['instName', 'instCity', 'instCountry', 'contactName', 'contactRole', 'contactPhone']
      .map(id => document.getElementById(id));
    let ok = true;
    required.forEach(el => { if (!markInvalid(el, !el.value.trim())) ok = false; });

    const email = document.getElementById('contactEmail');
    if (!markInvalid(email, !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim()))) ok = false;

    const fieldNames = [...document.querySelectorAll('.f-name')];
    fieldNames.forEach(el => { if (!markInvalid(el, !el.value.trim())) ok = false; });

    if (!ok) {
      const first = document.querySelector('.invalid');
      if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    // Fill confirmation summary
    document.getElementById('cfInstName').textContent = document.getElementById('instName').value.trim();
    document.getElementById('cfInst').textContent = document.getElementById('instName').value.trim();
    document.getElementById('cfContact').textContent = document.getElementById('contactName').value.trim();
    document.getElementById('cfEmail').textContent = email.value.trim();
    document.getElementById('cfFieldCount').textContent = fieldNames.length;

    document.getElementById('formState').style.display = 'none';
    document.getElementById('confirmState').classList.add('show');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });
});
