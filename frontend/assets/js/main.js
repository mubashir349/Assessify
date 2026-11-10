// ============================================================
// Assessify — shared front-end behaviors
// ============================================================

/** Sticky nav: adds a blurred background once the page scrolls. */
function initStickyNav(selector = '.nav', threshold = 20) {
  const nav = document.querySelector(selector);
  if (!nav) return;
  const onScroll = () => nav.classList.toggle('scrolled', window.scrollY > threshold);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });
}

/** Renders the three ambient floating blobs. Colours come from the theme tokens (see .blob-field in theme.css). */
function renderBlobField(container) {
  if (!container) return;
  container.innerHTML = '<span class="blob1"></span><span class="blob2"></span><span class="blob3"></span>';
}

/**
 * Password show / hide toggle.
 * Any <button class="pw-toggle" data-for="inputId"> flips that input between password and text.
 */
function initPasswordToggles(root = document) {
  root.querySelectorAll('.pw-toggle[data-for]').forEach(btn => {
    if (btn.dataset.ready) return;
    btn.dataset.ready = '1';
    const input = document.getElementById(btn.dataset.for);
    if (!input) return;
    const paint = () => {
      const shown = input.type === 'text';
      btn.innerHTML = window.AIcon ? AIcon(shown ? 'eye-off' : 'eye') : (shown ? 'Hide' : 'Show');
      btn.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
      btn.setAttribute('aria-pressed', String(shown));
    };
    btn.addEventListener('click', () => { input.type = input.type === 'password' ? 'text' : 'password'; paint(); input.focus(); });
    paint();
  });
}

/** Loading state for a button: shows a spinner and blocks double clicks. The button keeps its text for screen readers. */
function setBtnLoading(btn, on) {
  if (!btn) return;
  btn.classList.toggle('is-loading', !!on);
  btn.disabled = !!on;
  btn.setAttribute('aria-busy', on ? 'true' : 'false');
}

document.addEventListener('DOMContentLoaded', () => {
  initStickyNav();
  renderBlobField(document.querySelector('.blob-field'));
  initPasswordToggles();
});
