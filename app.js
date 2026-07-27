const Civic=window.CivicRecords;
const DATA_URL = `data/bylaws.json?v=${Date.now()}`;
const CHANGE_LOG_URL = `data/change-log.json?v=${Date.now()}`;
const COUNCIL_DISCUSSIONS_URL = `data/council-discussions.json?v=${Date.now()}`;
const COUNCIL_DOCUMENTS_URL = `data/council-documents.json?v=${Date.now()}`;
const COUNCIL_ITEMS_URL = `data/council-items.json?v=${Date.now()}`;
const COMMITTEE_ITEMS_URL = `data/committee-items.json?v=${Date.now()}`;
const COUNCIL_MEETINGS_URL = `data/council-meetings.json?v=${Date.now()}`;
const navToggle=document.querySelector('.nav-toggle'), nav=document.querySelector('.primary-nav'), searchInput=document.querySelector('#search-input'), toast=document.querySelector('#toast');
navToggle?.addEventListener('click',()=>{const open=nav.classList.toggle('open');navToggle.setAttribute('aria-expanded',String(open));});
function showToast(m){if(!toast)return;toast.textContent=m;toast.classList.add('show');clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.classList.remove('show'),2600)}
function esc(s=''){return Civic.escapeHtml(s)}
function normalizeCategory(value){return String(value||'')==='Transportation & Parking'?'Transportation':String(value||'')}
function normalizeBylawRecord(record){return {...record,category:normalizeCategory(record?.category)}}
function departmentFor(b){if(b.department)return b.department;return ({'Administration & Governance':'Legislative Services','Animals':'Bylaw Services','Business & Licensing':'Business Licensing','Environment':'Engineering & Public Works','Finance':'Finance','Land Use & Zoning':'Development Services','Other':'Corporate Services','Parks & Recreation':'Parks, Recreation & Culture','Public Safety':'Public Safety','Transportation':'Engineering & Public Works'})[normalizeCategory(b.category)]||'Corporate Services'}
function searchable(b){return `${b.number||''} ${b.title||''} ${b.description||''} ${b.category||''} ${b.status||''} ${b.year||''} ${departmentFor(b)} ${b.source||''}`.toLowerCase()}
function isAmended(b){
  return b?.legal_status==='Amendment bylaw'
    ||Boolean(b?.relationships?.amends?.length);
}
function isRepealed(b){
  return ['Repealed','Replaced'].includes(b?.legal_status)
    ||Boolean(b?.relationships?.repealed_by?.length)
    ||Boolean(b?.relationships?.replaced_by?.length);
}

function councilDocumentsFrom(payload){
  return Array.isArray(payload)
    ?payload
    :(Array.isArray(payload?.documents)?payload.documents:[]);
}

function archivedPdfPaths(payload, type='council'){
  const seen=new Set();
  const records=type==='bylaw'
    ?(Array.isArray(payload)?payload:(Array.isArray(payload?.bylaws)?payload.bylaws:[]))
    :councilDocumentsFrom(payload);
  for(const record of records){
    const paths=type==='bylaw'
      ?[record?.local_pdf,record?.pdf_archive_path,record?.archive_path]
      :[record?.local_path,record?.archive_path,record?.local_document];
    for(const value of paths){
      const path=String(value||'').trim().replace(/\\/g,'/');
      if(path && /\.pdf(?:$|[?#])/i.test(path)){
        seen.add(path.toLowerCase());
        break;
      }
    }
  }
  return seen;
}

function countCouncilMeetings(payload){
  const meetings=Array.isArray(payload)
    ?payload
    :(Array.isArray(payload?.meetings)?payload.meetings:[]);
  const seen=new Set();
  for(const meeting of meetings){
    const identity=String(
      meeting?.id
      ||meeting?.meeting_id
      ||meeting?.url
      ||meeting?.source_url
      ||`${meeting?.date||''}|${meeting?.title||meeting?.name||''}`
    ).trim().toLowerCase();
    if(identity)seen.add(identity);
  }
  return seen.size;
}

function countEscribeDocumentRecords(payload){
  const documents=Array.isArray(payload)
    ?payload
    :(Array.isArray(payload?.documents)?payload.documents:[]);
  const seen=new Set();

  for(const document of documents){
    const identity=String(
      document?.id
      ||document?.document_id
      ||document?.url
      ||document?.source_url
      ||document?.pdf_url
      ||document?.local_path
      ||document?.title
      ||JSON.stringify(document)
    ).trim().toLowerCase();

    if(identity)seen.add(identity);
  }

  return seen.size;
}

let all=[];
let recentChangeEvents=[];
let sortState={key:'date',direction:'desc'};
const activeFilters={status:'',category:'',year:'',department:'',source:''};

function numericBylawNumber(value){
  const parts=String(value??'').match(/\d+/g);
  if(!parts)return -Infinity;
  return Number(parts.map(part=>part.padStart(5,'0')).join('.'));
}
function changeTimestamp(value){
  const parsed=new Date(value||0);
  return Number.isNaN(parsed.getTime())?0:parsed.getTime();
}
function sortedChangeEvents(rows){
  const direction=sortState.direction==='asc'?1:-1;
  return [...rows].sort((a,b)=>{
    if(sortState.key==='number'){
      return (numericBylawNumber(a.number)-numericBylawNumber(b.number))*direction;
    }
    if(sortState.key==='status'||sortState.key==='category'){
      const primary=String(a[sortState.key]||'').localeCompare(
        String(b[sortState.key]||''),
        'en-CA',
        {sensitivity:'base',numeric:true}
      )*direction;
      if(primary!==0)return primary;
      return changeTimestamp(b.date)-changeTimestamp(a.date);
    }
    return (changeTimestamp(a.date)-changeTimestamp(b.date))*direction;
  });
}
function updateSortButtons(){
  document.querySelectorAll('.table-sort').forEach(button=>{
    const active=button.dataset.sort===sortState.key;
    button.classList.toggle('active',active);
    const arrow=button.querySelector('span');
    if(arrow)arrow.textContent=active?(sortState.direction==='asc'?'↑':'↓'):'↕';
  });
}
function statusClass(status){
  const value=String(status||'').toLowerCase();
  if(value==='repealed')return 'repealed';
  if(value==='amended')return 'amended';
  if(value==='consolidated')return 'consolidated';
  return 'active';
}
function formatChangeDate(value,precision){
  if(!value)return '—';
  const parsed=new Date(value);
  if(Number.isNaN(parsed.getTime()))return String(value);
  if(precision==='year')return String(parsed.getUTCFullYear());
  return parsed.toLocaleDateString('en-CA',{
    timeZone:'America/Vancouver',
    year:'numeric',
    month:'short',
    day:'numeric'
  });
}
function renderRecentChanges(){
  const body=document.querySelector('#changes-body');
  if(!body)return;
  const ordered=sortedChangeEvents(recentChangeEvents).slice(0,10);
  body.innerHTML=ordered.length?ordered.map(event=>`
    <tr>
      <td>${esc(formatChangeDate(event.date,event.date_precision))}</td>
      <td>Bylaw ${esc(event.number||'—')}</td>
      <td><a href="bylaws/${esc(event.detail_url||`detail.html?number=${encodeURIComponent(event.number||'')}`)}">${esc(event.title||`Bylaw ${event.number||''}`)}</a></td>
      <td><span class="status ${statusClass(event.status)}">${esc(event.status||'Changed')}</span></td>
      <td>${esc(normalizeCategory(event.category)||'Other')}</td>
      <td><a aria-label="Open ${esc(event.title||`Bylaw ${event.number||''}`)}" href="bylaws/${esc(event.detail_url||`detail.html?number=${encodeURIComponent(event.number||'')}`)}">›</a></td>
    </tr>`).join('')
    :'<tr><td colspan="6">No collected bylaw changes yet. Run the bylaw collector again after a City record changes.</td></tr>';
  updateSortButtons();
}
function filterRows(){
  const q=searchInput?.value.trim().toLowerCase()||'';
  return all.filter(b=>(!q||searchable(b).includes(q))&&(!activeFilters.status||b.status===activeFilters.status)&&(!activeFilters.category||b.category===activeFilters.category)&&(!activeFilters.year||String(b.year)===activeFilters.year)&&(!activeFilters.department||departmentFor(b)===activeFilters.department)&&(!activeFilters.source||b.source===activeFilters.source))
}
function applySearch(){}
function closeMenus(except){document.querySelectorAll('.filter-menu.open').forEach(menu=>{if(menu!==except){menu.classList.remove('open');const trigger=menu.parentElement?.querySelector('.filter-button');if(trigger)trigger.setAttribute('aria-expanded','false')}})}
function optionsFor(key){if(key==='department')return [...new Set(all.map(departmentFor))].sort();return [...new Set(all.map(b=>String(b[key]??'')).filter(Boolean))].sort((a,b)=>key==='year'?Number(b)-Number(a):a.localeCompare(b))}
function setFilter(key,value,label){activeFilters[key]=value;const button=document.querySelector(`.filter-button[data-filter="${key}"]`);if(button){button.classList.toggle('active',Boolean(value));button.querySelector('span').textContent=value?label:key[0].toUpperCase()+key.slice(1)}applySearch()}
function buildFilterMenus(){document.querySelectorAll('.filter-button').forEach(button=>{const key=button.dataset.filter;const wrapper=document.createElement('div');wrapper.className='filter-control';button.parentNode.insertBefore(wrapper,button);wrapper.appendChild(button);const menu=document.createElement('div');menu.className='filter-menu';menu.setAttribute('role','menu');const allLabel=`All ${key==='category'?'categories':key==='status'?'statuses':key==='source'?'sources':key==='department'?'departments':'years'}`;menu.innerHTML=`<button type="button" data-value="">${allLabel}</button>`+optionsFor(key).map(value=>`<button type="button" data-value="${esc(value)}">${esc(value)}</button>`).join('');wrapper.appendChild(menu);button.addEventListener('click',event=>{event.stopPropagation();const opening=!menu.classList.contains('open');closeMenus(menu);menu.classList.toggle('open',opening);button.setAttribute('aria-expanded',String(opening))});menu.addEventListener('click',event=>{const option=event.target.closest('[data-value]');if(!option)return;setFilter(key,option.dataset.value,option.textContent);menu.classList.remove('open');button.setAttribute('aria-expanded','false')})})}
document.addEventListener('click',()=>closeMenus());
document.querySelectorAll('.table-sort').forEach(button=>button.addEventListener('click',()=>{
  const key=button.dataset.sort;
  if(sortState.key!==key){
    sortState={
      key,
      direction:(key==='status'||key==='category')?'asc':'desc'
    };
  }else{
    sortState.direction=sortState.direction==='asc'?'desc':'asc';
  }
  renderRecentChanges();
}));
NanaimoData.fetch(DATA_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()}).then(data=>{
  all=(Array.isArray(data)?data:(Array.isArray(data.bylaws)?data.bylaws:[])).map(normalizeBylawRecord);console.info('[Nanaimo Bylaw Tracker] loaded',all.length,'records from',DATA_URL);
  buildFilterMenus();
  Object.entries({online:all.length,connected:all.length}).forEach(([key,value])=>{
    const el=document.querySelector(`#stat-${key}`);
    if(el)el.textContent=value.toLocaleString();
  });
  const connectedSmall=document.querySelector('#stat-connected')?.parentElement?.querySelector('small');if(connectedSmall)connectedSmall.textContent=`${all.length.toLocaleString()} records connected`;
  const updated=document.querySelector('#dataset-updated');const generated=data?.metadata?.generated_at||data?.metadata?.generated||'';if(updated)updated.textContent=generated?`Dataset updated: ${generated}`:`Current dataset: ${all.length.toLocaleString()} records`;
  const categoryCounts=all.reduce((counts,bylaw)=>{const category=bylaw.category||'Other';counts[category]=(counts[category]||0)+1;return counts;},{});
  document.querySelectorAll('.category-grid [data-category]').forEach(card=>{const category=card.dataset.category,count=categoryCounts[category]||0,countNode=card.querySelector('.category-count');if(countNode)countNode.textContent=count;card.setAttribute('aria-label',`${category}: ${count} ${count===1?'bylaw':'bylaws'}`)});
  const categoryTotal=document.querySelector('#category-bylaw-count');
  if(categoryTotal)categoryTotal.textContent=`${all.length.toLocaleString()} ${all.length===1?'bylaw':'bylaws'}`;
  renderHomepageWatchlist();
}).catch(error=>{console.error('[Nanaimo Bylaw Tracker] dataset load failed',error);['online','connected','amended','repealed'].forEach(key=>{const el=document.querySelector(`#stat-${key}`);if(el)el.textContent='Error'});const categoryTotal=document.querySelector('#category-bylaw-count');if(categoryTotal)categoryTotal.textContent='Unavailable';const updated=document.querySelector('#dataset-updated');if(updated)updated.textContent='Dataset could not be loaded';showToast('Could not load the current bylaw dataset. Confirm data/bylaws.json is available through IIS.');});
document.querySelector('#search-form')?.addEventListener('submit',e=>{e.preventDefault();const p=new URLSearchParams();const q=searchInput.value.trim();if(q)p.set('q',q);Object.entries(activeFilters).forEach(([key,value])=>{if(value)p.set(key,value)});location.href='bylaws/index.html'+(p.toString()?`?${p}`:'')});


NanaimoData.fetch(`data/bylaws-summary.json?v=${Date.now()}`,{cache:'no-store'})
  .then(response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(summary=>{
    const amended=Number(summary.amendment_bylaw_count);
    const repealed=Number(summary.repealed_or_replaced_count);
    const amendedEl=document.querySelector('#stat-amended');
    const repealedEl=document.querySelector('#stat-repealed');
    if(amendedEl)amendedEl.textContent=Number.isFinite(amended)?amended.toLocaleString():'—';
    if(repealedEl)repealedEl.textContent=Number.isFinite(repealed)?repealed.toLocaleString():'—';
  })
  .catch(error=>{
    console.error('[Nanaimo Bylaw Tracker] relationship summary load failed',error);
    const amendedEl=document.querySelector('#stat-amended');
    const repealedEl=document.querySelector('#stat-repealed');
    if(amendedEl)amendedEl.textContent='—';
    if(repealedEl)repealedEl.textContent='—';
  });


function civicMeetingGroup(item={}){
  const explicit=String(item.meeting_group||'').toLowerCase();
  if(explicit==='committee'||explicit==='board'||explicit==='commission'||explicit==='panel')return 'committee';
  if(explicit==='council'||explicit==='public-hearing')return 'council';
  const title=String(item.meeting_title||item.title||'').toLowerCase();
  if(/committee|board|commission|panel|governance and priorities|finance and audit/.test(title))return 'committee';
  return 'council';
}

Promise.allSettled([
  NanaimoData.fetch(COUNCIL_ITEMS_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Council items HTTP ${r.status}`);return r.json()}),
  NanaimoData.fetch(COMMITTEE_ITEMS_URL,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(`Committee items HTTP ${r.status}`);return r.json()}),
]).then(([councilResult,committeeResult])=>{
  const all=councilResult.status==='fulfilled'?(Array.isArray(councilResult.value)?councilResult.value:(councilResult.value.items||[])):[];
  const dedicated=committeeResult.status==='fulfilled'?(Array.isArray(committeeResult.value)?committeeResult.value:(committeeResult.value.items||[])):null;
  const committeeItems=dedicated||all.filter(item=>civicMeetingGroup(item)==='committee');
  const councilItems=all.filter(item=>civicMeetingGroup(item)==='council');
  const councilTarget=document.querySelector('#stat-council-items');
  const committeeTarget=document.querySelector('#stat-committee-items');
  if(councilTarget)councilTarget.textContent=councilItems.length.toLocaleString();
  if(committeeTarget)committeeTarget.textContent=committeeItems.length.toLocaleString();
  if(councilResult.status==='rejected')console.error('[Nanaimo Bylaw Tracker] Council item count failed',councilResult.reason);
  if(committeeResult.status==='rejected')console.warn('[Nanaimo Bylaw Tracker] Dedicated committee dataset unavailable; using Council dataset fallback.',committeeResult.reason);
});

Promise.allSettled([
  NanaimoData.fetch(COUNCIL_DOCUMENTS_URL,{cache:'no-store'}).then(response=>{
    if(!response.ok)throw new Error(`Council documents HTTP ${response.status}`);
    return response.json();
  }),
  NanaimoData.fetch(DATA_URL,{cache:'no-store'}).then(response=>{
    if(!response.ok)throw new Error(`Bylaws HTTP ${response.status}`);
    return response.json();
  })
]).then(([councilResult,bylawResult])=>{
  const paths=new Set();
  if(councilResult.status==='fulfilled'){
    archivedPdfPaths(councilResult.value,'council').forEach(path=>paths.add(path));
  }else{
    console.warn('[Nanaimo Bylaw Tracker] Council PDF count unavailable',councilResult.reason);
  }
  if(bylawResult.status==='fulfilled'){
    archivedPdfPaths(bylawResult.value,'bylaw').forEach(path=>paths.add(path));
  }else{
    console.warn('[Nanaimo Bylaw Tracker] Bylaw PDF count unavailable',bylawResult.reason);
  }
  const pdfTarget=document.querySelector('#stat-archived-pdfs');
  if(pdfTarget)pdfTarget.textContent=paths.size?paths.size.toLocaleString():'—';
});

NanaimoData.fetch(COUNCIL_MEETINGS_URL,{cache:'no-store'})
  .then(response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(data=>{
    const target=document.querySelector('#stat-council-meetings');
    if(target)target.textContent=countCouncilMeetings(data).toLocaleString();
  })
  .catch(error=>{
    console.error('[Nanaimo Bylaw Tracker] Council meeting count load failed',error);
    const target=document.querySelector('#stat-council-meetings');
    if(target)target.textContent='—';
  });

NanaimoData.fetch(CHANGE_LOG_URL,{cache:'no-store'})
  .then(response=>{
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(data=>{
    recentChangeEvents=(Array.isArray(data)?data:(Array.isArray(data.events)?data.events:[])).map(event=>({...event,category:normalizeCategory(event?.category)}));
    renderRecentChanges();
    const recentCount=document.querySelector('#recent-change-count');
    if(recentCount)recentCount.textContent=`${recentChangeEvents.length.toLocaleString()} ${recentChangeEvents.length===1?'change':'changes'}`;
    const updated=document.querySelector('#dataset-updated');
    if(updated){
      updated.textContent=data.last_updated
        ?`Change log updated: ${formatCollectedDate(data.last_updated)}`
        :`${recentChangeEvents.length.toLocaleString()} collected changes`;
    }
  })
  .catch(error=>{
    console.error('[Nanaimo Bylaw Tracker] change log load failed',error);
    recentChangeEvents=[];
    renderRecentChanges();
    const recentCount=document.querySelector('#recent-change-count');
    if(recentCount)recentCount.textContent='Unavailable';
    const updated=document.querySelector('#dataset-updated');
    if(updated)updated.textContent='Change log unavailable';
  });


function setSubscriptionSummary(state){
  const target=document.querySelector('#subscription-summary-status');
  if(!target)return;
  if(state==='enabled'){
    target.textContent='Enabled';
    target.setAttribute('aria-label','Email alerts enabled');
    return;
  }
  const link=document.createElement('a');
  link.href=state==='setup'?'account.html#email-alerts':'account.html';
  link.textContent=state==='setup'?'Setup email alerts':'Login';
  target.replaceChildren(link);
  target.setAttribute('aria-label',link.textContent);
}
async function refreshSubscriptionSummary(user){
  if(!document.querySelector('#subscription-summary-status'))return;
  if(!user){setSubscriptionSummary('login');return;}
  try{
    const subscription=await window.NBTAccount?.loadSubscription?.();
    setSubscriptionSummary(subscription?.active?'enabled':'setup');
  }catch(error){
    console.error('[Nanaimo Bylaw Tracker] subscription summary failed',error);
    setSubscriptionSummary('setup');
  }
}
window.addEventListener('nbt-auth-change',event=>refreshSubscriptionSummary(event.detail?.user||null));
setSubscriptionSummary('login');
if(window.NBTAccount)window.NBTAccount.ready.then(refreshSubscriptionSummary);
function renderHomepageWatchlist(){const preview=document.querySelector('#watchlist-preview'),badge=document.querySelector('#watchlist-count');if(!preview||!badge||!window.BylawWatchlist)return;const selected=BylawWatchlist.read();badge.textContent=selected.length;const matches=selected.map(number=>all.find(b=>String(b.number)===String(number))).filter(Boolean).slice(0,3);preview.innerHTML=matches.length?matches.map(b=>`<li><a href="bylaws/${esc(b.detail_url)}">${esc(b.title)}</a></li>`).join(''):'<li>No bylaws added yet.</li>'}
window.addEventListener('bylaw-watchlist-change',renderHomepageWatchlist);window.addEventListener('DOMContentLoaded',renderHomepageWatchlist);



function homepagePdfViewerUrl(value,item={}){return Civic.viewerUrl(value,item,'')}

function renderCouncilDiscussions(items){
  const list=document.querySelector('#council-discussions');
  if(!list)return;
  const ordered=[...(items||[])].sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).slice(0,4);
  list.innerHTML=ordered.length?ordered.map(item=>{
    const date=item.date?new Date(`${item.date}T12:00:00`).toLocaleDateString('en-CA',{year:'numeric',month:'short',day:'numeric'}):'Date unavailable';
    const viewer=homepagePdfViewerUrl(item.url,item);
    const targetUrl=viewer||Civic.safeExternalUrl(item.url)||Civic.safeUrl(item.url,{allowedLocalPrefixes:['bylaws/','council/','committees/','timeline.html','pdf.html']})||'bylaws/index.html';
    const external=Civic.isExternal(targetUrl);
    const type=item.type==='Motion'?'MOTION':'BYLAW';
    return `<li><span>${type}</span><a href="${esc(targetUrl)}"${external?' target="_blank" rel="noopener"':''}>${esc(item.title||'Council item')}<small>${esc(date)}${item.summary?` · ${esc(item.summary)}`:''}</small></a></li>`;
  }).join(''):'<li><span>—</span><a href="bylaws/index.html">No recent Council discussions are available.</a></li>';
}
NanaimoData.fetch(COUNCIL_DISCUSSIONS_URL,{cache:'no-store'})
  .then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()})
  .then(data=>renderCouncilDiscussions(Array.isArray(data)?data:(data.items||[])))
  .catch(error=>{
    console.error('[Nanaimo Bylaw Tracker] council discussions load failed',error);
    renderCouncilDiscussions([]);
  });


Promise.all([
  NanaimoData.fetch(COUNCIL_ITEMS_URL,{cache:'no-store'}).then(response=>response.ok?response.json():({items:[]})),
  NanaimoData.fetch(COUNCIL_DOCUMENTS_URL,{cache:'no-store'}).then(response=>response.ok?response.json():({documents:[]}))
]).then(([itemData,documentData])=>{
  const items=Array.isArray(itemData)?itemData:(itemData.items||[]);
  const documents=Array.isArray(documentData)?documentData:(documentData.documents||[]);
  const badge=document.querySelector('#council-pdf-count');
  if(badge){
    badge.textContent=`${items.length.toLocaleString()} items · ${documents.length.toLocaleString()} documents`;
    badge.setAttribute('aria-label',`${items.length.toLocaleString()} detected Council items and ${documents.length.toLocaleString()} indexed source documents`);
  }
}).catch(error=>{
  console.error('[Nanaimo Bylaw Tracker] Council activity counts failed',error);
  const badge=document.querySelector('#council-pdf-count');
  if(badge)badge.textContent='Council counts unavailable';
});


function formatCollectedDate(value){
  if(!value)return 'Unavailable';
  const parsed=new Date(value);
  if(Number.isNaN(parsed.getTime()))return String(value);
  return parsed.toLocaleString('en-CA',{
    timeZone:'America/Vancouver',
    year:'numeric',
    month:'long',
    day:'numeric',
    hour:'numeric',
    minute:'2-digit'
  });
}

async function updateCollectionTimestamp(){
  const target=document.querySelector('#data-last-updated');
  if(!target)return;
  try{
    let value=null;
    const summaryResponse=await NanaimoData.fetch(`data/bylaws-summary.json?v=${Date.now()}`,{cache:'no-store'});
    if(summaryResponse.ok){
      const summary=await summaryResponse.json();
      value=summary.generated_at||summary.last_updated||summary.updated_at||summary.collected_at||null;
    }
    if(!value){
      const dataResponse=await NanaimoData.fetch(`data/bylaws.json?v=${Date.now()}`,{cache:'no-store'});
      if(!dataResponse.ok)throw new Error(`HTTP ${dataResponse.status}`);
      const raw=await dataResponse.json();
      value=raw.generated_at||raw.last_updated||raw.updated_at||raw.collected_at
        ||raw.metadata?.generated_at||raw.metadata?.last_updated||null;
    }
    target.textContent=formatCollectedDate(value);
  }catch(error){
    console.error('[Nanaimo Bylaw Tracker] collection timestamp failed',error);
    target.textContent='Unavailable';
  }
}
updateCollectionTimestamp();


function formatFeaturedDate(value){
  if(!value)return '—';
  const date=new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime())?String(value):date.toLocaleDateString('en-CA',{year:'numeric',month:'long',day:'numeric'});
}
NanaimoData.fetch(`data/featured.json?v=${Date.now()}`,{cache:'no-store'})
  .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
  .then(item=>{
    const set=(selector,value)=>{const node=document.querySelector(selector);if(node)node.textContent=value||'—'};
    set('#home-featured-title',item.title);
    set('#home-featured-number',item.base_bylaw_number?`Bylaw ${item.base_bylaw_number}`:'—');
    set('#home-featured-status',item.status);
    set('#home-featured-date',formatFeaturedDate(item.notice_date));
    set('#home-featured-department',item.department);
    set('#home-featured-stage',item.stage);
    set('#home-featured-tracking',item.automatically_selected?'Automatically selected from latest Council activity':'Tracked record');
    const pdf=document.querySelector('#home-featured-pdf');
    if(pdf){pdf.href=item.official_bylaw||'featured.html';if(/^https?:/i.test(pdf.href)){pdf.target='_blank';pdf.rel='noopener'}}
    const council=document.querySelector('#home-featured-council');
    if(council){council.href=item.council_documents||item.official_notice||'council/index.html';if(/^https?:/i.test(council.href)){council.target='_blank';council.rel='noopener'}}
  })
  .catch(error=>{
    console.error('[Nanaimo Bylaw Tracker] featured bylaw load failed',error);
    const title=document.querySelector('#home-featured-title');
    if(title)title.textContent='Featured bylaw unavailable';
  });


function committeeDecisionLabel(item={}){
  const text=`${item.action||''} ${item.status||''} ${item.title||''}`.toLowerCase();
  if(/refer(?:red|ral)? to council/.test(text))return 'Referred to Council';
  if(/received for information|information only/.test(text))return 'Received for information';
  if(/recommend/.test(text))return 'Committee recommendation';
  if(/motion|moved|carried/.test(text))return 'Committee motion';
  return 'Committee item';
}
function committeeLocalPdf(value){
  const path=String(value||'').trim().replace(/^\.\.\//,'').replace(/\\/g,'/');
  if(!path||/^https?:\/\//i.test(path)||path.includes('..')||!/\.pdf(?:$|[?#])/i.test(path))return '';
  return path.split(/[?#]/)[0];
}
function committeeViewerUrl(path,item){return Civic.viewerUrl(path,item,'')}
function renderLatestCommitteeActivity(items=[]){
  const list=document.querySelector('#latest-committee-list');
  const total=document.querySelector('#committee-activity-count');
  if(!list||!total)return;
  const rows=items.filter(item=>civicMeetingGroup(item)==='committee')
    .sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')))
    .slice(0,6);
  total.textContent=`${items.filter(item=>civicMeetingGroup(item)==='committee').length.toLocaleString()} items`;
  list.innerHTML=rows.length?rows.map(item=>{
    const local=committeeLocalPdf(item.local_document);
    const href=item.bylaw_detail_url?item.bylaw_detail_url:(local?committeeViewerUrl(local,item):'committees/index.html');
    return `<article class="latest-council-item"><div class="council-item-meta"><span class="status amended">${esc(committeeDecisionLabel(item))}</span><span>${esc(item.date||'Date unavailable')}</span></div><h3><a href="${esc(href)}">${esc(item.title||'Committee item')}</a></h3><p>${esc(item.meeting_title||'Committee, board or panel')}</p></article>`;
  }).join(''):'<p class="empty-state">No committee or panel items have been collected yet.</p>';
}
NanaimoData.fetch(COMMITTEE_ITEMS_URL,{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error(`HTTP ${r.status}`))).catch(()=>NanaimoData.fetch(COUNCIL_ITEMS_URL,{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject(new Error(`HTTP ${r.status}`)))).then(data=>renderLatestCommitteeActivity(Array.isArray(data)?data:(data.items||[]))).catch(()=>{
  const list=document.querySelector('#latest-committee-list'); const total=document.querySelector('#committee-activity-count');
  if(list)list.innerHTML='<p class="empty-state">Committee activity is unavailable until the Council collector runs.</p>';
  if(total)total.textContent='Unavailable';
});
