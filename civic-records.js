(()=>{
  const ESCAPE_MAP={'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'};
  const LOCAL_PREFIXES=['archive/','bylaws/pdf/','bylaws/detail.html','committees/detail.html','council/','data/','pdf.html'];
  function escapeHtml(value=''){return String(value??'').replace(/[&<>"']/g,char=>ESCAPE_MAP[char]);}
  function normalizeLocal(value=''){
    const raw=String(value??'').trim().replace(/\\/g,'/');
    if(!raw||raw.startsWith('//')||/[\u0000-\u001f]/.test(raw))return '';
    let path=raw.replace(/^\.\//,'');
    while(path.startsWith('../'))path=path.slice(3);
    if(!path||path.split(/[?#]/)[0].split('/').includes('..'))return '';
    if(/^[a-z][a-z0-9+.-]*:/i.test(path))return '';
    return path;
  }
  function safeUrl(value,{rootPrefix='',allowHash=true,allowedLocalPrefixes=LOCAL_PREFIXES}={}){
    const raw=String(value??'').trim();
    if(!raw)return '';
    if(allowHash&&raw.startsWith('#'))return raw;
    try{
      const parsed=new URL(raw,location.href);
      if(parsed.protocol==='https:'||parsed.protocol==='http:'){
        if(parsed.origin!==location.origin)return parsed.href;
      }
    }catch(_error){}
    const local=normalizeLocal(raw);
    if(!local)return '';
    const plain=local.split(/[?#]/)[0];
    if(allowedLocalPrefixes?.length&&!allowedLocalPrefixes.some(prefix=>plain===prefix||plain.startsWith(prefix)))return '';
    if(window.NanaimoData?.isCloudPath(local))return window.NanaimoData.asset(local);
    return `${rootPrefix}${local}`;
  }
  function safeExternalUrl(value){
    try{const parsed=new URL(String(value??'').trim());return ['https:','http:'].includes(parsed.protocol)?parsed.href:'';}catch(_error){return '';}
  }
  function isExternal(value=''){try{return new URL(value,location.href).origin!==location.origin;}catch(_error){return false;}}
  function localPdfPath(value=''){
    const path=normalizeLocal(value);
    if(!path||/\.(?:ashx|aspx)(?:$|[?#])/i.test(path)||!/\.pdf(?:$|[?#])/i.test(path))return '';
    const plain=path.split(/[?#]/)[0];
    return ['archive/','bylaws/pdf/','council/'].some(prefix=>plain.startsWith(prefix))?plain:'';
  }
  function meetingGroup(item={}){
    const explicit=String(item.meeting_group||'').toLowerCase();
    if(['committee','board','commission','panel'].includes(explicit))return 'committee';
    if(['council','public-hearing'].includes(explicit))return 'council';
    const title=String(item.meeting_title||item.title||'').toLowerCase();
    return /committee|board|commission|panel|governance and priorities|finance and audit/.test(title)?'committee':'council';
  }
  function committeeName(item={}){return String(item.meeting_title||item.committee_name||'Committee, board or panel').trim();}
  function slug(value=''){return String(value).toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'');}
  function activityLabel(item={}){
    const text=`${item.action||''} ${item.status||''} ${item.title||''}`.toLowerCase();
    if(/refer(?:red|ral)? to council/.test(text))return 'Referred to Council';
    if(/received for information|information only/.test(text))return 'Received for information';
    if(/recommend/.test(text))return 'Committee recommendation';
    if(/motion|moved|carried/.test(text))return 'Committee motion';
    return meetingGroup(item)==='committee'?'Committee item':'Council item';
  }
  function viewerUrl(path,item={},prefix=''){
    const local=localPdfPath(path);if(!local)return '';
    const params=new URLSearchParams({file:local,title:item.title||'Archived document',context:item.meeting_title||item.meeting||item.source_kind||'Archived source document'});
    if(item.number||item.base_number)params.set('number',item.number||item.base_number);
    return `${prefix}pdf.html?${params}`;
  }
  function primaryUrl(item={},prefix=''){
    const detail=safeUrl(item.bylaw_detail_url,{rootPrefix:prefix,allowedLocalPrefixes:['bylaws/detail.html']});
    if(detail)return detail;
    const viewer=viewerUrl(item.local_document,item,prefix);if(viewer)return viewer;
    return safeExternalUrl(item.source_document_url)||safeExternalUrl(item.meeting_url)||'#';
  }
  function link(url,label,{className=''}={}){
    if(!url)return '';
    const external=isExternal(url);
    return `<a${className?` class="${escapeHtml(className)}"`:''} href="${escapeHtml(url)}"${external?' target="_blank" rel="noopener noreferrer"':''}>${escapeHtml(label)}</a>`;
  }
  window.CivicRecords={escapeHtml,safeUrl,safeExternalUrl,isExternal,localPdfPath,meetingGroup,committeeName,slug,activityLabel,viewerUrl,primaryUrl,link};
})();
