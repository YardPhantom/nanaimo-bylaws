(() => {
  const ICONS = {
    home: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>',
    bylaws: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11a3 3 0 0 1 3 3v15a3 3 0 0 0-3-3H6.5A2.5 2.5 0 0 0 4 20.5zm16 0A2.5 2.5 0 0 0 17.5 3H14v18a3 3 0 0 1 3-3h.5a2.5 2.5 0 0 1 2.5 2.5z"/></svg>',
    council: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 9h18M5 9V7l7-4 7 4v2M5 20h14M7 9v8m4-8v8m4-8v8m4-8v8M4 17h16v3H4z"/></svg>',
    committees: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="8" r="3"/><circle cx="17" cy="7" r="2.5"/><path d="M2.5 20v-2.5A4.5 4.5 0 0 1 7 13h2a4.5 4.5 0 0 1 4.5 4.5V20m1-7h1.5a4 4 0 0 1 4 4v3"/></svg>',
    timeline: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 10h18m-14 4h3m4 0h3m-10 4h3"/></svg>',
    more: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
    about: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 10v7m0-11h.01"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>',
    star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z"/></svg>',
    account: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>'
  };

  const targets = document.querySelectorAll('[data-shared-header]');
  const accountRoot = targets[0] ? (targets[0].dataset.root || '.').replace(/\/$/, '') : '.';

  targets.forEach((target) => {
    const root = (target.dataset.root || '.').replace(/\/$/, '');
    const href = (path) => `${root}/${path}`.replace(/^\.\//, '');
    const currentPath = window.location.pathname.toLowerCase();
    const currentQuery = window.location.search.toLowerCase();
    const isHome = /(?:^|\/)index\.html$/.test(currentPath) && !currentPath.includes('/bylaws/') && !currentPath.includes('/data/') && !currentPath.includes('/council/') && !currentPath.includes('/committees/');
    const isBylaws = currentPath.includes('/bylaws/') || currentPath.endsWith('/categories.html') || currentPath.endsWith('/featured.html');
    const isCouncil = currentPath.includes('/council/');
    const isCommittees = currentPath.includes('/committees/');
    const isTimeline = currentPath.endsWith('/timeline.html');
    const isAbout = currentPath.endsWith('/about.html');
    const isAccount = currentPath.endsWith('/account.html');
    const isMore = currentPath.endsWith('/watchlist.html') || currentPath.endsWith('/subscriptions.html') || currentPath.endsWith('/privacy.html') || currentPath.endsWith('/sitemap.html') || currentPath.includes('/data/');
    const active = (condition) => condition ? ' active' : '';
    const current = (condition) => condition ? ' aria-current="page"' : '';
    const nestedCurrent = (path, query = '') => {
      const pathMatch = currentPath.endsWith(path.toLowerCase()) || currentPath.includes(path.toLowerCase());
      const queryMatch = query ? currentQuery.includes(query.toLowerCase()) : !currentQuery;
      return pathMatch && queryMatch ? ' class="mega-current" aria-current="page"' : '';
    };

    target.outerHTML = `
      <header class="site-header mega-site-header">
        <div class="header-main-row">
          <a aria-label="Nanaimo Bylaw Tracker home" class="brand" href="${href('index.html')}">
            <span aria-hidden="true" class="brand-mark"><img src="${href('assets/brand-icon.svg?v=0.13.1')}" alt="" width="64" height="64"></span>
            <span class="brand-copy"><span class="brand-title">Nanaimo Bylaw Tracker</span><small>Bylaws. Meetings. Accountability.</small></span>
          </a>
          <div class="header-actions" aria-label="Account and search shortcuts">
            <a href="${href('bylaws/index.html')}" class="header-action">${ICONS.search}<span>Search</span></a>
            <a href="${href('watchlist.html')}" class="header-action">${ICONS.star}<span>Watchlist</span></a>
            <a${current(isAccount)} href="${href('account.html')}" class="header-action account-nav-link${active(isAccount)}">${ICONS.account}<span data-account-state>Account</span></a>
          </div>
          <button aria-controls="primary-nav" aria-expanded="false" class="nav-toggle" type="button"><span></span><span></span><span></span><span class="sr-only">Toggle navigation</span></button>
        </div>
        <nav aria-label="Primary navigation" class="primary-nav" id="primary-nav">
          <a${current(isHome)} class="nav-link${active(isHome)}" href="${href('index.html')}">${ICONS.home}<span>Home</span></a>
          <button class="nav-link mega-trigger${active(isBylaws)}" type="button" data-mega-section="bylaws" aria-expanded="false">${ICONS.bylaws}<span>Bylaws</span><b aria-hidden="true">⌄</b></button>
          <button class="nav-link mega-trigger${active(isCouncil)}" type="button" data-mega-section="council" aria-expanded="false">${ICONS.council}<span>Council</span><b aria-hidden="true">⌄</b></button>
          <button class="nav-link mega-trigger${active(isCommittees)}" type="button" data-mega-section="committees" aria-expanded="false">${ICONS.committees}<span>Committees</span><b aria-hidden="true">⌄</b></button>
          <a${current(isTimeline)} class="nav-link${active(isTimeline)}" href="${href('timeline.html')}">${ICONS.timeline}<span>Timeline</span></a>
          <button class="nav-link mega-trigger${active(isMore)}" type="button" data-mega-section="more" aria-expanded="false">${ICONS.more}<span>More</span><b aria-hidden="true">⌄</b></button>
          <a${current(isAbout)} class="nav-link${active(isAbout)}" href="${href('about.html')}">${ICONS.about}<span>About</span></a>
        </nav>
        <div class="mega-menu" id="mega-menu" hidden>
          <div class="mega-menu-grid">
            <section data-mega-column="bylaws"><h2>Bylaws</h2><a${nestedCurrent('/bylaws/index.html')} href="${href('bylaws/index.html')}">Bylaw Archive</a><a${nestedCurrent('/categories.html')} href="${href('categories.html')}">Bylaw Categories</a><a${nestedCurrent('/featured.html')} href="${href('featured.html')}">Featured Bylaws</a><a${nestedCurrent('/timeline.html', 'type=bylaw')} href="${href('timeline.html?type=bylaw')}">Recent Changes</a></section>
            <section data-mega-column="council"><h2>Council</h2><a${nestedCurrent('/council/index.html')} href="${href('council/index.html')}">Council Meetings</a><a${nestedCurrent('/council/index.html', 'type=decision')} href="${href('council/index.html?type=decision')}">Council Decisions</a><a${nestedCurrent('/council/index.html', 'type=document')} href="${href('council/index.html?type=document')}">Meeting Documents</a><a${nestedCurrent('/timeline.html', 'group=council')} href="${href('timeline.html?group=council')}">Meeting Timeline</a></section>
            <section data-mega-column="committees"><h2>Committees</h2><a${nestedCurrent('/committees/index.html')} href="${href('committees/index.html')}">All Committees</a><a${nestedCurrent('/committees/index.html', 'group=board')} href="${href('committees/index.html?group=board')}">Boards &amp; Commissions</a><a${nestedCurrent('/committees/index.html', 'type=recommendation')} href="${href('committees/index.html?type=recommendation')}">Committee Recommendations</a><a${nestedCurrent('/timeline.html', 'group=committee')} href="${href('timeline.html?group=committee')}">Committees Timeline</a></section>
            <section data-mega-column="more"><h2>Explore</h2><a${nestedCurrent('/timeline.html')} href="${href('timeline.html')}">Timeline</a><a${nestedCurrent('/watchlist.html')} href="${href('watchlist.html')}">Watchlist</a><a${nestedCurrent('/data/index.html')} href="${href('data/index.html')}">Data &amp; Reports</a></section>
            <section data-mega-column="more"><h2>About</h2><a${nestedCurrent('/about.html')} href="${href('about.html')}">About This Site</a><a${nestedCurrent('/privacy.html')} href="${href('privacy.html')}">Privacy Policy</a></section>
            <form class="mega-search" action="${href('bylaws/index.html')}" method="get"><h2>Quick Search</h2><label class="sr-only">Search bylaws</label><div><input name="q" type="search" aria-label="Search bylaws" placeholder="Search bylaws, meetings, committees…"><button type="submit" aria-label="Search">${ICONS.search}</button></div><a href="${href('bylaws/index.html')}">Advanced Search →</a></form>
          </div>
        </div>
      </header>`;
  });

  const accountPage = window.location.pathname.toLowerCase().endsWith('/account.html');
  if (!accountPage && !document.querySelector('script[data-account-session]')) {
    let accountSessionQueued = false;
    const loadAccountSession = () => {
      if (accountSessionQueued || document.querySelector('script[data-account-session]')) return;
      accountSessionQueued = true;
      const script = document.createElement('script');
      script.type = 'module';
      script.dataset.accountSession = 'true';
      script.src = `${accountRoot}/account-session.min.js?v=0.13.1`.replace(/^\.\//, '');
      document.head.appendChild(script);
    };
    const idleLoad = () => ('requestIdleCallback' in window)
      ? window.requestIdleCallback(loadAccountSession, { timeout: 2500 })
      : window.setTimeout(loadAccountSession, 1200);
    idleLoad();
    ['pointerdown', 'keydown', 'focusin'].forEach(type =>
      window.addEventListener(type, loadAccountSession, { once: true, passive: type === 'pointerdown' })
    );
  }

  document.querySelectorAll('.mega-site-header').forEach((header) => {
    const menu = header.querySelector('.mega-menu');
    const triggers = [...header.querySelectorAll('.mega-trigger')];
    const navToggle = header.querySelector('.nav-toggle');
    const nav = header.querySelector('.primary-nav');

    const closeMega = () => {
      menu.hidden = true;
      header.classList.remove('mega-open');
      triggers.forEach((trigger) => trigger.setAttribute('aria-expanded', 'false'));
      menu.querySelectorAll('[data-mega-column]').forEach((column) => column.classList.remove('mega-focus'));
      menu.querySelectorAll('.mega-current-suppressed').forEach((link) => link.classList.remove('mega-current-suppressed'));
      delete menu.dataset.openSection;
    };

    const closeMobileNav = () => {
      nav.classList.remove('open');
      navToggle?.setAttribute('aria-expanded', 'false');
    };

    const closeAll = () => {
      closeMega();
      closeMobileNav();
    };

    const syncMobileMegaPosition = () => {
      if (!window.matchMedia('(max-width: 760px)').matches || !nav.classList.contains('open')) {
        header.style.removeProperty('--mobile-mega-top');
        return;
      }
      header.style.setProperty('--mobile-mega-top', `${nav.offsetTop + nav.offsetHeight}px`);
    };

    const openMega = (trigger) => {
      const section = trigger.dataset.megaSection;
      const wasOpen = trigger.getAttribute('aria-expanded') === 'true' && !menu.hidden;
      closeMega();
      if (wasOpen) return;
      menu.hidden = false;
      header.classList.add('mega-open');
      trigger.setAttribute('aria-expanded', 'true');
      menu.dataset.openSection = section;
      menu.querySelectorAll(`[data-mega-column="${section}"]`).forEach((column) => column.classList.add('mega-focus'));
      menu.querySelectorAll('a.mega-current, a[aria-current="page"]').forEach((link) => {
        const column = link.closest('[data-mega-column]')?.dataset.megaColumn || '';
        link.classList.toggle('mega-current-suppressed', column !== section);
      });
      syncMobileMegaPosition();
    };

    triggers.forEach((trigger) => trigger.addEventListener('click', () => openMega(trigger)));
    navToggle?.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
      if (!open) closeMega();
      syncMobileMegaPosition();
    });
    window.addEventListener('resize', syncMobileMegaPosition, { passive: true });
    document.addEventListener('click', (event) => { if (!header.contains(event.target)) closeAll(); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeAll(); });
  });
})();
