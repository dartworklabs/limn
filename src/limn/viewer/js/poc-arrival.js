// PoC for issue #345 item 2 - where a figure page is arrived at. An exploration for the owner to choose by touching it; not
// for merge as it is (docs/handbook/workflow.md §경로가 달라지는 경우, the exploration row).
//
// Two arrivals, switched live by the PoC pill in the nav bar or the hash (#arrive=page|figure, default page = today's):
// - page:   the page's top at the PDF area's top (pvGlideInto, unchanged).
// - figure: on a page whose map has a figure element (<id>/@figure, meta pages[i].figure_box), that element's top edge
//           under the free PDF area's top (selPopArea), with its label line above it (pocFigureTop) - lower only where the reading line would leave the page,
//           as outlinePickTop. The reading line (readingDepth under the area's top) then falls inside the figure, so the
//           section strip, the page count, the keys 1-5 and the verdict panel name the arrived page.
// Only goPage arrives this way: the outline, the page field (#jump, the navigation sheet's) and the page list. A card's
// [보기] and reading by scroll are unchanged. Every arrival starts with pvGlideTo/pvGlideInto, so the glide guard holds.
//
// The way back to the page top, in figure arrival: the same entry again (outline row, page row, page number) while the
// pages rest on that figure goes to the page's top (and once more, back to the figure); and the chip [↑ 쪽 머리], shown while
// the arrived page's top is above the area, glides to it.
//
// Demo-only aids (#aids=0 or the pill's [보조선] hides them): a dashed line on the page where the first screen ended on arrival,
// labelled with how much of the figure that screen showed, and the figure's box outlined.

const POC_GAP=8;   // px at least between the free PDF area's top and an arrived figure's top edge (OUTLINE_PICK_GAP)
const POC_ROOM_PT=24;   // pt of the page kept above an arrived figure at most: its label line
let POC_MODE=pocHashMode()||'page';
let POC_AIDS=!/(?:^#|[#&])aids=0(?:&|$)/.test(location.hash||'');
let POC_AT=/** @type {{page:number,mode:string,seq:number}|null} */(null),POC_SEQ=0,POC_POLL=0;
/** @type {ReturnType<typeof pocMeasure>} */
let POC_LAST=null;

function pocHashMode(){const m=/(?:^#|[#&])arrive=(page|figure)(?:&|$)/.exec(location.hash||''); return m?m[1]:null;}
function pocSetHash(){const keep=(location.hash||'').replace(/^#/,'').split('&').filter(s=>s&&!/^(arrive|aids)=/.test(s));
  keep.push('arrive='+POC_MODE); if(!POC_AIDS)keep.push('aids=0');
  history.replaceState(history.state,'',location.pathname+location.search+'#'+keep.join('&'));}
window.addEventListener('hashchange',()=>{const m=pocHashMode(); if(m&&m!==POC_MODE){POC_MODE=m; pocDrawPill();}});

/** @param {number} n @param {string} key */
function pocBox(n,key){const p=META&&META.pages&&META.pages[n-1],b=p&&/** @type {any} */(p)[key]; return isFrac(b)?b:null;}
function pocIsFigureDoc(){return !!META&&isFigureKind(META.kind);}
// #left's scrollTop that puts page n's figure top edge POC_GAP under the free area's top, or null with no figure box.
/** @param {number} n */
// The figure keeps up to POC_ROOM_PT of room above it, down to the element above (figure_above): its label line ('PL18 · 지금
// 판', '본문 Fig. D3') has no element of its own and stood cut in half under the area's top.
function pocFigureTop(n){const pg=document.getElementById('p'+n),b=pocBox(n,'figure_box'),pm=META&&META.pages&&META.pages[n-1]; if(!pg||!b||!pm)return null;
  const L=$('#left'),r=pg.getBoundingClientRect(),y=r.top+b[1]*r.height,read=L.getBoundingClientRect().top+readingDepth(L);
  const above=/** @type {any} */(pm).figure_above,ptPx=r.height/(pm.pt_h||1),room=Math.min(POC_ROOM_PT*ptPx,typeof above==='number'?Math.max(0,(b[1]-above)*r.height):Infinity);
  const want=Math.max(selPopArea().top+Math.max(POC_GAP,room),read+2-(r.bottom-y));
  return Math.max(0,Math.min(L.scrollHeight-L.clientHeight,Math.round(L.scrollTop+y-want)));}

// goPage's arrival (pages.js). The same entry again while the pages rest on the figure goes to the page's top.
/** @param {number} n @param {HTMLElement} el */
function pocGoPage(n,el){const L=$('#left'),fig=POC_MODE==='figure'?pocFigureTop(n):null;
  let mode=fig===null?'page':'figure';
  if(mode==='figure'&&!pvAutoScrolling()&&Math.abs(L.scrollTop-/** @type {number} */(fig))<=2)mode='page';
  if(mode==='figure')pvGlideTo(/** @type {number} */(fig)); else pvGlideInto(el);
  pocArrived(n,mode);}
// The chip's way back: the arrived page's top.
function pocToPageTop(){if(!POC_AT)return; const n=POC_AT.page,el=document.getElementById('p'+n); if(!el)return;
  pvGlideInto(el); pocArrived(n,'page');}

// After an arrival: wait until the pages rest (two still reads 80ms apart, 3s at most), then measure and draw the aids.
/** @param {number} n @param {string} mode */
function pocArrived(n,mode){const seq=++POC_SEQ,L=$('#left'),t0=performance.now(); POC_AT={page:n,mode,seq}; POC_LAST=null;
  pocClearAids(); pocChip(); clearInterval(POC_POLL); let last=-1,still=0;
  POC_POLL=setInterval(()=>{if(!POC_AT||POC_AT.seq!==seq){clearInterval(POC_POLL); return;}
    const s=L.scrollTop; still=Math.abs(s-last)<0.5?still+1:0; last=s;
    if(still>=2||performance.now()-t0>3000){clearInterval(POC_POLL); POC_LAST=pocMeasure(n); pocDrawAids(); pocChip(); pocDrawPill();}},80);}

// What the screen shows of page n now: the free area (under the strip, above a sheet, above the floating verdict line of
// that page while it floats there), and the figure's and caption's boxes in it. Read from the layout as it is.
/** @param {number} n */
function pocMeasure(n){const pg=document.getElementById('p'+n); if(!pg)return null;
  const r=pg.getBoundingClientRect(),a=selPopArea(); let bottom=a.bottom;
  if(!document.body.classList.contains('pv-beside')){const ln=document.querySelector('#doc .pv[data-page="'+n+'"]');
    if(ln&&ln.getClientRects().length){const lr=ln.getBoundingClientRect(); if(lr.top<bottom&&lr.bottom>a.top&&lr.bottom>=a.bottom-16)bottom=Math.min(bottom,lr.top);}}   // the line counts while it floats at the area's bottom
  /** @param {number[]|null} b */
  const box=b=>b?{top:r.top+b[1]*r.height,bottom:r.top+(b[1]+b[3])*r.height}:null;
  /** @param {{top:number,bottom:number}|null} x */
  const seen=x=>x?Math.max(0,Math.min(x.bottom,bottom)-Math.max(x.top,a.top)):0;
  /** @param {{top:number,bottom:number}|null} x */
  const whole=x=>!!x&&x.top>=a.top-0.5&&x.bottom<=bottom+0.5;
  const f=box(pocBox(n,'figure_box')),c=box(pocBox(n,'caption_box'));
  return {page:n,top:a.top,bottom,pageTop:r.top,pageH:r.height,fig:f,figH:f?f.bottom-f.top:0,figSeen:seen(f),figWhole:whole(f),
    cap:c,capH:c?c.bottom-c.top:0,capSeen:seen(c),capWhole:whole(c),headSeen:r.top>=a.top-0.5,reading:pvReadingAt()};}

function pocClearAids(){for(const x of $$('.poc-guide,.poc-figbox'))x.remove();}
// The aids on the arrived page, in page fractions so a zoom keeps them on the same spot of the page.
function pocDrawAids(){pocClearAids(); const m=POC_LAST; if(!POC_AIDS||!m||!m.fig)return;
  const pg=document.getElementById('p'+m.page),b=pocBox(m.page,'figure_box'); if(!pg||!b)return;
  const fb=document.createElement('div'); fb.className='poc-figbox';
  Object.assign(fb.style,{left:b[0]*100+'%',top:b[1]*100+'%',width:b[2]*100+'%',height:b[3]*100+'%'}); pg.appendChild(fb);
  const raw=(m.bottom-m.pageTop)/m.pageH,y=Math.min(1,Math.max(0,raw)),g=document.createElement('div');
  g.className='poc-guide'; g.style.top=y*100+'%';
  const t=document.createElement('span'); t.className='poc-guide-t'; t.textContent=(raw>1?'쪽 끝까지 보임 ▲ ':'첫 화면 끝 ▲ ')+pocCountText(m); g.appendChild(t); pg.appendChild(g);}
/** @param {NonNullable<ReturnType<typeof pocMeasure>>} m */
function pocCountText(m){const pct=m.figH?Math.round(m.figSeen/m.figH*100):0;
  const cap=!m.cap?'':m.capWhole?' · 캡션 다 보임':m.capSeen>0?' · 캡션 일부':' · 캡션 안 보임';
  return '그림 '+Math.round(m.figSeen)+'/'+Math.round(m.figH)+' px ('+pct+'%)'+cap;}

// The chip [↑ 쪽 머리]: while a figure arrival's page is the reading page and its top is above the free area.
const POC_CHIP=document.createElement('button');
POC_CHIP.id='poc-top'; POC_CHIP.type='button'; POC_CHIP.hidden=true; POC_CHIP.textContent='↑ 쪽 머리';
POC_CHIP.setAttribute('aria-label','이 쪽의 맨 위로'); POC_CHIP.addEventListener('click',pocToPageTop); document.body.appendChild(POC_CHIP);
function pocChip(){const at=POC_AT,pg=at?document.getElementById('p'+at.page):null;
  if(!at||at.mode!=='figure'||!pg||!pocIsFigureDoc()||document.body.classList.contains('revision-open')){POC_CHIP.hidden=true; return;}
  const a=selPopArea(),r=pg.getBoundingClientRect(),read=topAnchor(readingDepth($('#left')));
  const show=!!read&&read.page===at.page&&r.top<a.top-1; POC_CHIP.hidden=!show; if(!show)return;
  const right=Math.min(a.right,r.right)-8; POC_CHIP.style.top=Math.round(a.top+2)+'px';   // on the figure's label line, right of its short text
  POC_CHIP.style.left=Math.round(Math.max(a.left+8,right-POC_CHIP.offsetWidth))+'px';}
let POC_CHIP_RAF=0;
$('#left').addEventListener('scroll',()=>{if(POC_CHIP_RAF)return; POC_CHIP_RAF=requestAnimationFrame(()=>{POC_CHIP_RAF=0; pocChip();});},{passive:true});

// The PoC pill: [쪽 위 | 그림] and [보조선], in the nav bar's free stretch (left of the search) or, without room there,
// under the nav bar at the free area's left.
const POC_PILL=document.createElement('div');
POC_PILL.id='poc-pill'; POC_PILL.setAttribute('role','group'); POC_PILL.setAttribute('aria-label','PoC: 그림 쪽 도착 자리'); POC_PILL.hidden=true;
document.body.appendChild(POC_PILL);
function pocDrawPill(){
  const b=(/** @type {string} */ k,/** @type {string} */ t,/** @type {boolean} */ on)=>html`<button type="button" data-poc="${k}" aria-pressed="${on?'true':'false'}">${t}</button>`;
  setHtml(POC_PILL,html`<span class="poc-tag">PoC</span><span class="poc-l">도착</span>${b('page','쪽 위',POC_MODE==='page')}${b('figure','그림',POC_MODE==='figure')}<span class="poc-sep"></span>${b('aids','보조선',POC_AIDS)}`);
  pocPlacePill();}
function pocPlacePill(){const show=pocIsFigureDoc()&&!document.body.classList.contains('revision-open'); POC_PILL.hidden=!show; if(!show)return;
  const nav=$('#doc-nav').getBoundingClientRect(),vs=$('#view-switch'),sr=$('#doc-search'),w=POC_PILL.offsetWidth,h=POC_PILL.offsetHeight;
  const from=vs&&vs.getClientRects().length?vs.getBoundingClientRect().right+12:nav.left+56;
  const to=sr&&sr.getClientRects().length?sr.getBoundingClientRect().left-12:nav.right-120;
  if(to-from>=w){POC_PILL.style.left=Math.round(from+(to-from-w)/2)+'px'; POC_PILL.style.top=Math.round(nav.top+(nav.height-h)/2)+'px';}
  else{const a=selPopArea(); POC_PILL.style.left=Math.round(a.left+8)+'px'; POC_PILL.style.top=Math.round(a.top+8)+'px';}}
POC_PILL.addEventListener('click',e=>{const t=/** @type {HTMLElement|null} */(e.target),k=t&&t.closest('[data-poc]')?/** @type {HTMLElement} */(t.closest('[data-poc]')).dataset.poc:null;
  if(!k)return;
  if(k==='aids'){POC_AIDS=!POC_AIDS; pocSetHash(); pocDrawPill(); if(POC_AIDS)pocDrawAids(); else pocClearAids(); return;}
  POC_MODE=k; pocSetHash(); pocDrawPill();
  const a=topAnchor(readingDepth($('#left'))); if(a)goPage(a.page);});   // flip live: arrive again on the reading page
addEventListener('resize',()=>{pocPlacePill(); pocChip();});
let POC_PILL_DOC='';
setInterval(()=>{const k=(META&&META.kind?META.kind:'')+':'+(DOC||'')+':'+document.body.classList.contains('revision-open');
  if(k!==POC_PILL_DOC){POC_PILL_DOC=k; pocDrawPill();}},500);
pocDrawPill();
