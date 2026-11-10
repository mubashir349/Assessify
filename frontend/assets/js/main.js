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

/** Renders the three ambient floating blobs used on dark mesh backgrounds. */
function renderBlobField(container) {
  if (!container) return;
  container.innerHTML = `
    <span class="blob1" style="top:-200px;left:-100px;width:600px;height:600px;
      background:radial-gradient(circle,rgba(99,102,241,0.15) 0%,transparent 70%);"></span>
    <span class="blob2" style="top:30%;right:-150px;width:500px;height:500px;
      background:radial-gradient(circle,rgba(139,92,246,0.12) 0%,transparent 70%);"></span>
    <span class="blob3" style="bottom:-100px;left:40%;width:400px;height:400px;
      background:radial-gradient(circle,rgba(6,182,212,0.10) 0%,transparent 70%);"></span>
  `;
}

document.addEventListener('DOMContentLoaded', () => {
  initStickyNav();
  renderBlobField(document.querySelector('.blob-field'));
});
