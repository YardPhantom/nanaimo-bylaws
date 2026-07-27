const C=window.CivicRecords;
const esc=value=>C.escapeHtml(value);
const q=document.querySelector('#timeline-q');
const type=document.querySelector('#timeline-type');
const action=document.querySelector('#timeline-action');
const year=document.querySelector('#timeline-year');
const order=document.querySelector('#timeline-order');
const list=document.querySelector('#timeline-list');
const status=document.querySelector('#timeline-status');
const count=document.querySelector('#timeline-count');
let events=[];

function valueArray(payload,key){
  if(Array.isArray(payload))return payload;
  return Array.isArray(payload?.[key])?payload[key]:[];
}
function dateValue(event){
  if(event.date)return event.date;
  if(event.year)return `${event.year}-01-01`;
  return '0000-01-01';
}
function displayDate(event){
  if(event.date){
    const parsed=new Date(`${event.date}T12:00:00`);
    if(!Number.isNaN(parsed.getTime())){
      return parsed.toLocaleDateString('en-CA',{year:'numeric',month:'long',day:'numeric'});
    }
  }
  return event.year?String(event.year):'Date unavailable';
}
function populate(select,values,label){
  select.innerHTML=`<option value="">${label}</option>`+values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('');
}

function localPdfPath(value){return C.localPdfPath(value)}
function viewerUrl(path,event){return C.viewerUrl(path,event,'')}

function councilEvents(items){
  return items.map(item=>({
    id:`council-${item.id||item.date||''}-${item.number||item.title||''}`,
    type:'Council action',
    date:item.date||null,
    year:String(item.date||'').slice(0,4)||null,
    title:item.title||item.summary||'Council item',
    number:item.number||item.base_number||null,
    action:item.action||'Discussed',
    summary:item.summary||'',
    category:item.category||'',
    department:item.department||'',
    meeting:item.meeting_title||'Council meeting',
    primaryUrl:C.primaryUrl(item,''),
    meetingUrl:item.meeting_url||null,
    localDocument:item.local_document||null,
    sourceKind:item.source_kind||'Council source'
  }));
}
function bylawEvents(records){
  return records.map(record=>({
    id:`bylaw-${record.number}`,
    type:'Bylaw record',
    date:null,
    year:record.year||null,
    title:record.title||`Bylaw ${record.number}`,
    number:record.number||null,
    action:record.status||'Published',
    summary:record.description||'',
    category:record.category||'',
    department:record.department||'',
    meeting:'',
    primaryUrl:record.detail_url||`bylaws/detail.html?number=${encodeURIComponent(record.number||'')}`,
    meetingUrl:null,
    localDocument:null,
    sourceKind:record.source||'City of Nanaimo'
  }));
}
function eventStar(event){
  if(!event.number||!window.BylawWatchlist)return '';
  const active=window.BylawWatchlist.has(event.number);
  return `<button class="watch-star${active?' active':''}" type="button" data-watch-number="${esc(event.number)}" aria-pressed="${active}" aria-label="${active?'Remove':'Add'} Bylaw ${esc(event.number)} ${active?'from':'to'} watchlist">${active?'★':'☆'}</button>`;
}
function render(){
  const term=q.value.trim().toLowerCase();
  const filtered=events.filter(event=>{
    const haystack=[
      event.title,event.number,event.action,event.summary,event.category,
      event.department,event.meeting,event.sourceKind,event.year
    ].join(' ').toLowerCase();
    return (!term||haystack.includes(term))
      &&(!type.value||event.type===type.value)
      &&(!action.value||event.action===action.value)
      &&(!year.value||String(event.year||'')===year.value);
  }).sort((a,b)=>{
    const comparison=dateValue(a).localeCompare(dateValue(b));
    return order.value==='asc'?comparison:-comparison;
  });

  count.textContent=`${filtered.length.toLocaleString()} events`;
  status.textContent=`Showing ${filtered.length.toLocaleString()} of ${events.length.toLocaleString()} collected timeline events.`;

  let previousYear='';
  list.innerHTML=filtered.map(event=>{
    const eventYear=String(event.year||'Unknown');
    const yearMarker=eventYear!==previousYear
      ? `<h2 class="timeline-year-marker">${esc(eventYear)}</h2>`
      : '';
    previousYear=eventYear;
    const external=C.isExternal(event.primaryUrl||'');
    const badgeClass=event.type==='Council action'?'amended':'active';
    return `${yearMarker}<article class="timeline-event">
      <div class="timeline-rail" aria-hidden="true"><span></span></div>
      <div class="timeline-event-card">
        <div class="timeline-event-meta">
          <time>${esc(displayDate(event))}</time>
          <span class="status ${badgeClass}">${esc(event.type)}</span>
          <span class="timeline-action">${esc(event.action)}</span>
        </div>
        <h3>${eventStar(event)}<a href="${esc(event.primaryUrl)}"${external?' target="_blank" rel="noopener"':''}>${event.number?`Bylaw ${esc(event.number)} — `:''}${esc(event.title)}</a></h3>
        ${event.summary?`<p>${esc(event.summary)}</p>`:''}
        <div class="timeline-event-details">
          ${event.category?`<span>${esc(event.category)}</span>`:''}
          ${event.department?`<span>${esc(event.department)}</span>`:''}
          ${event.meeting?`<span>${esc(event.meeting)}</span>`:''}
          ${event.sourceKind?`<span>${esc(event.sourceKind)}</span>`:''}
        </div>
        <div class="timeline-event-links">
          ${C.link(C.safeExternalUrl(event.meetingUrl),'Official meeting')}
          ${localPdfPath(event.localDocument)?`<a href="${esc(viewerUrl(localPdfPath(event.localDocument),event))}">Local document</a>`:''}
        </div>
      </div>
    </article>`;
  }).join('')||'<p class="empty-state">No timeline events match these filters.</p>';
}

Promise.all([
  NanaimoData.fetch(`data/council-items.json?v=${Date.now()}`,{cache:'no-store'}).then(response=>response.ok?response.json():({items:[]})),
  NanaimoData.fetch(`data/bylaws.json?v=${Date.now()}`,{cache:'no-store'}).then(response=>response.ok?response.json():({bylaws:[]}))
]).then(([councilPayload,bylawPayload])=>{
  const council=valueArray(councilPayload,'items');
  const bylaws=valueArray(bylawPayload,'bylaws');
  events=[...councilEvents(council),...bylawEvents(bylaws)];
  populate(action,[...new Set(events.map(event=>event.action).filter(Boolean))].sort(),'All actions');
  populate(year,[...new Set(events.map(event=>String(event.year||'')).filter(Boolean))].sort((a,b)=>Number(b)-Number(a)),'All years');
  const params=new URLSearchParams(location.search);
  q.value=params.get('q')||'';
  type.value=params.get('type')||'';
  action.value=params.get('action')||'';
  year.value=params.get('year')||'';
  render();
}).catch(error=>{
  console.error(error);
  count.textContent='Unavailable';
  status.textContent='Timeline data could not be loaded.';
  list.innerHTML='<p class="empty-state">Run the bylaw and Council collectors to populate the timeline.</p>';
});

[q,type,action,year,order].forEach(control=>control.addEventListener('input',render));

list.addEventListener('click',event=>{const button=event.target.closest('[data-watch-number]');if(!button||!window.BylawWatchlist)return;window.BylawWatchlist.toggle(button.dataset.watchNumber);render();});
window.addEventListener('bylaw-watchlist-change',render);
