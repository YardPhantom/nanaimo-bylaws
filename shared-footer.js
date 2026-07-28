(() => {
  const VERSION = "V0.13.2";
  const targets = document.querySelectorAll("[data-shared-footer]");

  targets.forEach((target) => {
    const root = (target.dataset.root || ".").replace(/\/$/, "");
    const href = (path) => `${root}/${path}`.replace(/^\.\//, "");

    target.outerHTML = `
      <footer class="site-footer" id="site-footer">
        <div class="footer-art" aria-hidden="true">
          <svg viewBox="0 0 450 150" preserveAspectRatio="xMidYMax slice">
            <rect width="450" height="150" fill="#c5eff7"></rect>
            <path d="M0 115 100 45l75 55 65-42 90 70H0z" fill="#79c4dd"></path>
            <path d="M0 130 90 75l70 40 70-55 105 70z" fill="#2e82aa"></path>
            <path d="M0 150h450v-35c-90-20-170-10-245 10-70 18-135 13-205-5z" fill="#064b78"></path>
          </svg>
        </div>
        <div class="footer-copy">Nanaimo Bylaw Tracker is an independent civic information service and is not affiliated with the City of Nanaimo.</div>
        <nav aria-label="Footer navigation">
          <span class="footer-links">
            <a href="${href("about.html")}">About</a><span aria-hidden="true">|</span>
            <a href="${href("sitemap.html")}">Sitemap</a><span aria-hidden="true">|</span>
            <a href="${href("privacy.html")}">Privacy</a><span aria-hidden="true">|</span>
            <span class="footer-version">${VERSION}</span>
          </span>
          <p>© 2026 Hesh co. - Nanaimo Bylaw Tracker</p>
        </nav>
      </footer>`;
  });
  if ('serviceWorker' in navigator) {
    const root = targets[0] ? (targets[0].dataset.root || '.').replace(/\/$/, '') : '.';
    const registerWorker = () => navigator.serviceWorker.register(`${root}/sw.js?v=0.13.2`.replace(/^\.\//, ''), { scope: `${root}/`.replace(/^\.\//, '') })
      .catch(error => console.warn('[NBT] Service worker registration skipped', error));
    if ('requestIdleCallback' in window) window.requestIdleCallback(registerWorker, { timeout: 4000 });
    else window.setTimeout(registerWorker, 1800);
  }

})();
