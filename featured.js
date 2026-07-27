const formatDate=value=>{if(!value)return '—';const date=new Date(`${value}T12:00:00`);return new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'long',day:'numeric'}).format(date)};
let featuredNumber='';
const watchButton=document.querySelector('#featured-watch-star');
function updateFeaturedStar(){
  if(!watchButton||!featuredNumber||!window.BylawWatchlist)return;
  const active=window.BylawWatchlist.has(featuredNumber);
  watchButton.hidden=false;
  watchButton.classList.toggle('active',active);
  watchButton.textContent=active?'★':'☆';
  watchButton.setAttribute('aria-pressed',String(active));
  watchButton.setAttribute('aria-label',`${active?'Remove':'Add'} featured bylaw ${active?'from':'to'} watchlist`);
  watchButton.title=`${active?'Remove from':'Add to'} watchlist`;
}
watchButton?.addEventListener('click',()=>{if(featuredNumber&&window.BylawWatchlist){window.BylawWatchlist.toggle(featuredNumber);updateFeaturedStar();}});
window.addEventListener('bylaw-watchlist-change',updateFeaturedStar);
const navToggle=document.querySelector('.nav-toggle'),nav=document.querySelector('.primary-nav');
navToggle?.addEventListener('click',()=>{const open=nav.classList.toggle('open');navToggle.setAttribute('aria-expanded',String(open));});
NanaimoData.fetch('data/featured.json',{cache:'no-store'}).then(response=>{if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}).then(item=>{
  document.querySelector('#featured-title').textContent=item.title;
  featuredNumber=String(item.base_bylaw_number||'');
  updateFeaturedStar();
  document.querySelector('#featured-status').textContent=item.status;
  document.querySelector('#featured-summary').textContent=item.summary;
  document.querySelector('#featured-number').textContent=`Bylaw ${item.base_bylaw_number}`;
  document.querySelector('#featured-stage').textContent=item.stage;
  document.querySelector('#featured-date').textContent=formatDate(item.notice_date);
  document.querySelector('#featured-department').textContent=item.department;
  document.querySelector('#featured-checked').textContent=formatDate(item.last_checked);
  const note=document.querySelector('#featured-note');
  if(note&&item.automatically_selected)note.textContent='Automatically selected from the newest collected bylaw matter in official Council sources.';
  document.querySelector('#featured-pdf').href=item.official_bylaw;
  document.querySelector('#featured-notice').href=item.official_notice;
  document.querySelector('#featured-council').href=item.council_documents;
}).catch(error=>{document.querySelector('#featured-title').textContent='Featured bylaw unavailable';document.querySelector('#featured-summary').textContent=`The featured record could not be loaded (${error.message}).`;});
