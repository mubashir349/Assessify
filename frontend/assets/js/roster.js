// roster.html — page script

function toggleReveal(el, real) {
  const masked = el.dataset.masked || el.textContent;
  el.dataset.masked = masked;
  if (el.classList.contains('shown')) { el.textContent = masked; el.classList.remove('shown'); }
  else { el.textContent = real; el.classList.add('shown'); }
}
