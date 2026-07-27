const navToggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('.primary-nav');
const note = document.querySelector('#category-data-note');

navToggle?.addEventListener('click', () => {
  const open = nav.classList.toggle('open');
  navToggle.setAttribute('aria-expanded', String(open));
});

NanaimoData.fetch(`data/bylaws.json?v=${Date.now()}`, {cache:'no-store'})
  .then(response => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(data => {
    const records = Array.isArray(data.bylaws) ? data.bylaws : [];
    const counts = records.reduce((totals, record) => {
      const category = record.category || 'Other';
      totals[category] = (totals[category] || 0) + 1;
      return totals;
    }, {});

    document.querySelectorAll('#category-directory [data-category]').forEach(card => {
      const category = card.dataset.category;
      const count = counts[category] || 0;
      const countNode = card.querySelector('.category-count');
      if (countNode) countNode.textContent = count;
      card.setAttribute('aria-label', `${category}: ${count} ${count === 1 ? 'bylaw' : 'bylaws'}. Open filtered bylaw search.`);
    });

    note.textContent = `${records.length} connected records across ${Object.keys(counts).length} categories.`;
  })
  .catch(() => {
    note.textContent = 'Category counts could not be loaded. Serve the site through IIS or a local web server.';
  });
