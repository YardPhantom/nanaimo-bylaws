const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const number=new URLSearchParams(location.search).get('number');

function watchStar(bylaw){
  const watched=window.BylawWatchlist?.has(bylaw.number);
  return `<button class="watch-star detail-watch-star${watched?' active':''}" type="button" data-watch-number="${esc(bylaw.number)}" aria-pressed="${watched}" aria-label="${watched?'Remove':'Add'} ${esc(bylaw.title)} ${watched?'from':'to'} watchlist" title="${watched?'Remove from':'Add to'} watchlist">${watched?'★':'☆'}</button>`;
}


function relationList(values,records,label){
  if(!values?.length)return '';
  return `<section class="relationship-group"><h3>${esc(label)}</h3><ul>${values.map(value=>{
    const match=records.find(record=>String(record.number)===String(value));
    const title=match?.title||`Bylaw ${value}`;
    if(!match){
      return `<li>${esc(title)} <span class="meta-pill">Historical reference</span></li>`;
    }
    const href=match.detail_url||`detail.html?number=${encodeURIComponent(value)}`;
    return `<li><a href="${esc(href)}">${esc(title)}</a>${match?.legal_status?` <span class="meta-pill">${esc(match.legal_status)}</span>`:''}</li>`;
  }).join('')}</ul></section>`;
}

NanaimoData.fetch(`data/bylaws.json?v=${Date.now()}`,{cache:'no-store'})
  .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
  .then(data=>{
    const records=Array.isArray(data)?data:(Array.isArray(data.bylaws)?data.bylaws:[]);
    const bylaw=records.find(record=>String(record.number)===String(number));
    const element=document.querySelector('#detail');
    if(!bylaw){
      element.innerHTML='<article class="detail-card"><h1>Bylaw not found</h1><p>This record is not yet in the local dataset.</p></article>';
      return;
    }

    document.title=`${bylaw.title} | Nanaimo Bylaw Tracker`;
    const relationships=bylaw.relationships||{};
    const relationshipSections=[
      relationList(relationships.amends,records,'Amends'),
      relationList(relationships.amended_by,records,'Amended by'),
      relationList(relationships.repeals,records,'Repeals'),
      relationList(relationships.repealed_by,records,'Repealed by'),
      relationList(relationships.replaces,records,'Replaces'),
      relationList(relationships.replaced_by,records,'Replaced by'),
      relationList(relationships.consolidates,records,'Consolidates'),
      relationList(relationships.consolidated_by,records,'Consolidated by')
    ].filter(Boolean).join('');

    const localTextPath=bylaw.local_text
      ? (String(bylaw.local_text).startsWith('bylaws/')?String(bylaw.local_text):`bylaws/${String(bylaw.local_text).replace(/^\/+/, '')}`)
      : '';
    const localText=localTextPath
      ? `<a class="secondary-button" href="${esc(NanaimoData.asset(localTextPath))}">Open extracted text</a>`
      : '';

    element.innerHTML=`<article class="detail-card">
      <p class="eyebrow">Bylaw No. ${esc(bylaw.number)}</p>
      <div class="detail-title-row">${watchStar(bylaw)}<h1>${esc(bylaw.title)}</h1></div>
      <p>${esc(bylaw.description)}</p>
      <dl>
        <dt>Index status</dt><dd>${esc(bylaw.status)}</dd>
        <dt>Relationship status</dt><dd><span class="status ${['Repealed','Replaced'].includes(bylaw.legal_status)?'repealed':bylaw.legal_status==='Amendment bylaw'?'amended':'active'}">${esc(bylaw.legal_status||'Published')}</span></dd>
        <dt>Year</dt><dd>${esc(bylaw.year||'Unknown')}</dd>
        <dt>Category</dt><dd>${esc(bylaw.category)}</dd>
        <dt>Source</dt><dd>${esc(bylaw.source)}</dd>
        <dt>Last checked</dt><dd>${esc(bylaw.last_checked)}</dd>
        <dt>PDF extraction</dt><dd>${esc(bylaw.text_extraction_method||'Not extracted')}${bylaw.ocr_pages?.length?` · OCR pages ${esc(bylaw.ocr_pages.join(', '))}`:''}</dd>
      </dl>
      <div class="source-actions">
        <a class="primary-button" target="_blank" rel="noopener" href="${esc(bylaw.official_pdf)}">Open official PDF</a>
        <a class="secondary-button" target="_blank" rel="noopener" href="${esc(bylaw.official_index)}">Official bylaw index</a>
        ${localText}
      </div>
    </article>
    <aside class="detail-card">
      <h2>Amendment and repeal relationships</h2>
      ${relationshipSections||'<p>No explicit amendment, repeal, replacement, or consolidation relationship has been detected yet.</p>'}
      <h2>Preserved document</h2>
      <p>The current preserved PDF path is <code>bylaws/${esc(bylaw.local_pdf)}</code>${NanaimoData.status().enabled?' in cloud storage':' in local storage'}.</p>
      <p class="relationship-note">Relationships are inferred from official titles, descriptions, PDF text, and Council records. Verify critical legal status against the official City source.</p>
    </aside>`;
    element.addEventListener('click',event=>{
      const button=event.target.closest('[data-watch-number]');
      if(!button||!window.BylawWatchlist)return;
      const active=window.BylawWatchlist.toggle(button.dataset.watchNumber);
      button.classList.toggle('active',active);
      button.textContent=active?'★':'☆';
      button.setAttribute('aria-pressed',String(active));
      button.setAttribute('aria-label',`${active?'Remove':'Add'} ${bylaw.title} ${active?'from':'to'} watchlist`);
      button.title=`${active?'Remove from':'Add to'} watchlist`;
    });
  })
  .catch(error=>{
    console.error(error);
    document.querySelector('#detail').innerHTML='<article class="detail-card"><h1>Data unavailable</h1><p>The bylaw dataset could not be loaded.</p></article>';
  });
