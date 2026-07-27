const C=window.CivicRecords;
const q=document.querySelector('#council-q');
const meetingGroup=document.querySelector('#council-meeting-group');
const type=document.querySelector('#council-type');
const action=document.querySelector('#council-action');
const year=document.querySelector('#council-year');
const container=document.querySelector('#council-items');
const count=document.querySelector('#council-item-count');
let items=[];
function civicMeetingGroup(item={}){return C.meetingGroup(item);}
const requestedGroup='council';
if(requestedGroup&&meetingGroup)meetingGroup.value=requestedGroup;

function esc(value=''){return C.escapeHtml(value)}
function populate(select,values,label){select.innerHTML=`<option value="">${label}</option>`+values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('')}
function localPdfPath(value){return C.localPdfPath(value)}
function viewerUrl(path,item){return C.viewerUrl(path,item,'../')}
function render(){
  const query=q.value.trim().toLowerCase();
  const filtered=items.filter(item=>{
    const haystack=`${item.title||''} ${item.summary||''} ${item.number||''} ${item.action||''} ${item.meeting_title||''} ${item.date||''}`.toLowerCase();
    return (!query||haystack.includes(query))
      &&(!meetingGroup.value||civicMeetingGroup(item)===meetingGroup.value)
      &&(!type.value||item.type===type.value)
      &&(!action.value||item.action===action.value)
      &&(!year.value||String(item.date||'').startsWith(year.value));
  });
  count.textContent=`${filtered.length.toLocaleString()} of ${items.length.toLocaleString()} items`;
  container.innerHTML=filtered.length?filtered.map(item=>{
    const local=localPdfPath(item.local_document);
    const primary=C.primaryUrl(item,'../');
    const external=C.isExternal(primary);
    return `<article class="council-item">
      <div class="council-item-meta"><span class="status ${civicMeetingGroup(item)==='committee'?'amended':'active'}">${civicMeetingGroup(item)==='committee'?'Committee':'Council'}</span><span class="status ${item.type==='Motion'?'amended':'active'}">${esc(item.type)}</span><span>${esc(item.date||'Date unavailable')}</span><span>${esc(item.action||'Discussed')}</span></div>
      <h2><a href="${esc(primary)}"${external?' target="_blank" rel="noopener"':''}>${esc(item.title||'Council item')}</a></h2>
      <p>${esc(item.summary||'')}</p>
      <div class="council-item-links">
        ${C.link(C.safeExternalUrl(item.meeting_url),'Official meeting')}
        ${local?`<a href="${esc(viewerUrl(local,item))}">Local archived PDF</a>`:''}
        ${!local?C.link(C.safeExternalUrl(item.source_document_url),'Source document'):''}
        ${C.link(C.safeUrl(item.source_text,{rootPrefix:'../',allowedLocalPrefixes:['archive/','council/','data/']}),'Extracted text')}
      </div>
    </article>`;
  }).join(''):'<p>No Council items match these filters.</p>';
}
NanaimoData.fetch(`data/council-items.json?v=${Date.now()}`,{cache:'no-store'})
  .then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()})
  .then(data=>{
    items=Array.isArray(data)?data:(data.items||[]);
    populate(action,[...new Set(items.map(item=>item.action).filter(Boolean))].sort(),'All actions');
    populate(year,[...new Set(items.map(item=>String(item.date||'').slice(0,4)).filter(Boolean))].sort().reverse(),'All years');
    render();
  })
  .catch(error=>{
    console.error(error);
    count.textContent='Data unavailable';
    container.innerHTML='<p>Run <code>python tools/collect_council.py --download</code> to create the Council datasets.</p>';
  });
[q,meetingGroup,type,action,year].forEach(control=>control&&control.addEventListener('input',render));


NanaimoData.fetch(`data/council-verification.json?v=${Date.now()}`, {cache:'no-store'})
  .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
  .then(report => {
    const target = document.querySelector('#council-verification-status');
    if (!target) return;
    const summary = report.summary || {};
    target.className = `council-verification-status verification-${report.status || 'warn'}`;
    target.innerHTML = `<strong>${String(report.status || 'unknown').toUpperCase()}</strong>
      Latest verification: ${summary.meetings || 0} meetings,
      ${summary.documents || 0} documents,
      ${summary.items || 0} extracted items,
      ${summary.matched_bylaw_items || 0}/${summary.bylaw_items || 0} matched bylaws.
      <a href="${esc(NanaimoData.url('data/council-verification.json'))}">View report</a>`;
  })
  .catch(() => {
    const target = document.querySelector('#council-verification-status');
    if (target) {
      target.className = 'council-verification-status verification-warn';
      target.textContent = 'No Council verification report is available yet. Run the Council collector.';
    }
  });


