// ------------------------------------------------ In-document text search (docs/handbook/viewer.md §본문 검색)
// The pages are canvases, so the browser's own find has nothing to find in them: the nav bar's field (#doc-search) searches the
// text of the PDF on screen instead. The text comes from PDF.js (a page's getTextContent), read page by page only once a query
// asks for it, after any page that is being drawn, and kept for as long as that document object is open (one per build). A hit
// lies within one line of text; its box is drawn over the page from the text items' geometry, in page fractions like a mark.
// No text layer is added - a drag on the page stays a region selection (pdf-open.js).
// - Matching: searchFold() on both sides (case, Unicode composition and width, runs of spaces, curly quotes and dashes).
// - Where the field is: in the nav bar when there is room (inline), folded to a magnifier when there is not (icon), and on the
//   phone - which has no nav bar - a row in place of the sheet's bar, opened from the navigation sheet (dock). searchFit().
// - Ends with: Esc or [검색 닫기] (cleared, focus back), another document or a new build (searchClear, from vecOpen), the changes
//   view and a PDF that cannot be read (searchOffer hides it).

// The text as it is matched: Unicode NFKC (Hangul jamo composed, a letter and its combining mark joined, ligatures and
// full-width forms unfolded), lower case, curly quotes and dashes as ' " and -, soft hyphens and zero-width marks dropped, every
// run of white space one space. Returns {t, at}: the folded text and, for each of its UTF-16 units, the index in s where the
// cluster it came from starts, then s.length - so a match in t maps back to a run of s. Pure.
/** @param {string} s @returns {{t:string,at:number[]}} */
function searchFold(s){const plain={'\u2018':"'",'\u2019':"'",'\u201A':"'",'\u201C':'"','\u201D':'"','\u201E':'"'},t=[],at=[]; s=String(s);
  // a cluster: Hangul jamo that compose one syllable, or one character, each with the combining marks after it; or a run of spaces
  const cluster=/[\u1100-\u115F\uA960-\uA97C]+[\u1160-\u11A7\uD7B0-\uD7C6]*[\u11A8-\u11FF\uD7CB-\uD7FB]*\p{M}*|\s+|[^]\p{M}*/gu;
  for(const m of s.matchAll(cluster)){
    const p=/^\s+$/.test(m[0])?' ':m[0].normalize('NFKC').toLowerCase().replace(/[\u00AD\u200B-\u200D\u2060\uFEFF]/g,'')
      .replace(/[\u2018\u2019\u201A\u201C\u201D\u201E]/g,c=>plain[c]).replace(/[\u2010-\u2015\u2212]/g,'-').replace(/\s+/g,' ');
    for(let k=0;k<p.length;k++){if(p[k]===' '&&t[t.length-1]===' ')continue; t.push(p[k]); at.push(/** @type {number} */(m.index));}}
  at.push(s.length); return {t:t.join(''),at};}
// A page's lines from PDF.js text items: the items up to one marked hasEOL are one line, whatever their fonts, so a query may
// span them. Each line is {t, at, parts}: its text folded (searchFold: at maps into the line's unfolded text) and, per item
// with text, the item's index i and where its text starts in the unfolded line (from). Blank lines are left out. Pure.
/** @param {any[]} items */
function searchLines(items){const lines=/** @type {{t:string,at:number[],parts:{i:number,from:number}[]}[]} */([]); let raw='',parts=/** @type {{i:number,from:number}[]} */([]);
  const end=()=>{if(raw.trim()){const f=searchFold(raw); lines.push({t:f.t,at:f.at,parts});} raw=''; parts=[];};
  items.forEach((it,i)=>{if(typeof it.str!=='string')return; if(it.str){parts.push({i,from:raw.length}); raw+=it.str;} if(it.hasEOL)end();});
  end(); return lines;}
// Where q occurs in t, left to right and without overlap; nothing for an empty q. Pure.
/** @param {string} t @param {string} q @returns {number[]} */
function searchFind(t,q){const out=[]; if(!q)return out; for(let i=t.indexOf(q);i>=0;i=t.indexOf(q,i+q.length))out.push(i); return out;}
// The hit after (d=1) or before (d=-1) hit i of n, wrapping at both ends; from no current hit (i<0) the first or the last;
// -1 with no hits. Pure.
/** @param {number} i @param {number} n @param {number} d */
function searchStep(i,n,d){if(!n)return -1; if(i<0)return d>0?0:n-1; return ((i+d)%n+n)%n;}
// The field's width in the nav bar for `room` px left beside its neighbours: its full width, else the room in whole pixels
// down to its minimum, else 0 - it folds to the magnifier rather than squeeze them. Pure.
/** @param {number} room @param {number} full @param {number} min */
function searchWidth(room,full,min){return room>=full?full:room>=min?Math.floor(room):0;}
// The box of characters [s,e) of text item it on its page, as fractions [x, y, w, h] of the pw x ph viewport whose transform
// is vt: along the item's direction by the measured share of its width (measure(text, family) in any unit - the item's own
// width scales it, as PDF.js's text layer does), across it from the font's ascent to its descent (style; 0.8 and -0.2 when the
// font gives none). A turned item gives the bounding box of its turned run. Pure.
/** @param {any} it @param {any} style @param {number[]} vt @param {number} pw @param {number} ph @param {number} s @param {number} e @param {(text:string,family:string)=>number} measure */
function searchBox(it,style,vt,pw,ph,s,e,measure){const T=it.transform,fam=style.fontFamily||'sans-serif';
  const m=[vt[0]*T[0]+vt[2]*T[1],vt[1]*T[0]+vt[3]*T[1],vt[0]*T[2]+vt[2]*T[3],vt[1]*T[2]+vt[3]*T[3],vt[0]*T[4]+vt[2]*T[5]+vt[4],vt[1]*T[4]+vt[3]*T[5]+vt[5]];
  const run=Math.hypot(m[0],m[1])||1,up=Math.hypot(m[2],m[3])||1,W=it.width*Math.hypot(vt[0],vt[1]),all=measure(it.str,fam)||1;
  const asc=typeof style.ascent==='number'?style.ascent:typeof style.descent==='number'?1+style.descent:0.8,desc=typeof style.descent==='number'?style.descent:-0.2;
  const xs=[],ys=[];
  for(const a of [W*measure(it.str.slice(0,s),fam)/all,W*measure(it.str.slice(0,e),fam)/all])for(const k of [asc*up,desc*up]){
    xs.push(m[4]+a*m[0]/run+k*m[2]/up); ys.push(m[5]+a*m[1]/run+k*m[3]/up);}
  const x0=Math.min(...xs),y0=Math.min(...ys);
  return [x0/pw,y0/ph,(Math.max(...xs)-x0)/pw,(Math.max(...ys)-y0)/ph];}

// The search on screen. q: the folded query ('' = none). doc: the PDF.js document the hits are of. hits: every hit in
// document order as {page, line, a, b, box?} (a-b in the line's folded text; box cached by searchRect). cur: the current
// hit. ref: where a new query starts looking (the page on screen, or the hit that was current). reading: the document whose
// pages are being read. open: the field is disclosed (focused or holding a query). back: what had the focus before it.
// side: the phone's sheet was open when the search row took its place. near: the pages near the view, the only ones that carry
// hit boxes. text: each open document's pages as read ({items, styles, vt, w, h, lines}; null until read).
const SEARCH={q:'',doc:/** @type {any} */(null),hits:/** @type {any[]} */([]),cur:/** @type {any} */(null),ref:{page:1,line:0,a:0},reading:/** @type {any} */(null),
  open:false,back:/** @type {HTMLElement|null} */(null),side:false,near:new Set(),io:/** @type {IntersectionObserver|null} */(null),text:new WeakMap()};
// The pages of document doc as read so far, index 0 for page 1 (null = not read yet); kept until the document is closed.
function searchPages(doc){let P=SEARCH.text.get(doc); if(!P){P=new Array(doc.numPages).fill(null); SEARCH.text.set(doc,P);} return P;}
// The hits of query q on read page P, number n, in reading order.
function searchPageHits(P,n,q){return P.lines.flatMap((L,line)=>searchFind(L.t,q).map(a=>({page:n,line,a,b:a+q.length})));}
// The width of text in a generic font family, in an arbitrary unit (a shared canvas): searchBox()'s measure.
let SEARCH_CTX=/** @type {CanvasRenderingContext2D|null} */(null);
/** @param {string} text @param {string} family */
function searchMeasure(text,family){const c=/** @type {CanvasRenderingContext2D} */(SEARCH_CTX||(SEARCH_CTX=document.createElement('canvas').getContext('2d')));
  c.font='100px '+family; return c.measureText(text).width;}
// A hit's box on its page as fractions [x, y, w, h]: the union of its run in each text item of its line (a hit never leaves
// its line). The folded match maps back to the line's own characters through the line's map, to the end of the last
// character's cluster - both letters of a ligature are the ligature's box.
function searchRect(h){if(h.box)return h.box; const P=searchPages(SEARCH.doc)[h.page-1],L=P.lines[h.line]; let k=h.b;
  while(k<L.at.length-1&&L.at[k]<=L.at[h.b-1])k++;
  const r0=L.at[h.a],r1=L.at[k]; let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(const p of L.parts){const it=P.items[p.i],s=Math.max(r0,p.from)-p.from,e=Math.min(r1,p.from+it.str.length)-p.from; if(e<=s)continue;
    const b=searchBox(it,P.styles[it.fontName]||{},P.vt,P.w,P.h,s,e,searchMeasure);
    x0=Math.min(x0,b[0]); y0=Math.min(y0,b[1]); x1=Math.max(x1,b[0]+b[2]); y1=Math.max(y1,b[1]+b[3]);}
  return h.box=x1>=x0?[x0,y0,x1-x0,y1-y0]:[0,0,0,0];}
// Draws page n's hit boxes (the current one marked), or removes them when the page is not near the view or has none.
function searchDrawPage(n){const pg=document.getElementById('p'+n); if(!pg)return; pg.querySelectorAll('.search-hit').forEach(e=>e.remove());
  if(!SEARCH.near.has(n))return;
  for(const h of SEARCH.hits){if(h.page!==n)continue; const b=searchRect(h),d=document.createElement('div'); d.className='search-hit'+(h===SEARCH.cur?' cur':'');
    Object.assign(d.style,{left:b[0]*100+'%',top:b[1]*100+'%',width:b[2]*100+'%',height:b[3]*100+'%'}); pg.appendChild(d);}}
// Follows which pages are near the view (within one view height) while there is a query: only those carry hit boxes, drawn as
// they come near and removed as they leave, so a common letter in a long document does not fill the page list with boxes.
function searchWatch(){if(SEARCH.io||!window.IntersectionObserver)return;
  const io=SEARCH.io=new IntersectionObserver(es=>{for(const en of es){const n=Number(/** @type {HTMLElement} */(en.target).dataset.page);
    if(en.isIntersecting)SEARCH.near.add(n); else SEARCH.near.delete(n); searchDrawPage(n);}},{root:$('#left'),rootMargin:'100% 0px'});
  $$('.pg').forEach(pg=>io.observe(pg));}
// Stops following the pages and removes every hit box.
function searchUnwatch(){if(SEARCH.io)SEARCH.io.disconnect(); SEARCH.io=null; SEARCH.near.clear(); $$('.search-hit').forEach(e=>e.remove());}
// Whether the count is not final yet: the PDF is still opening (another document or build on its way), or pages of the
// searched document are still unread.
function searchBusy(){return !!SEARCH.q&&(!SEARCH.doc||searchPages(SEARCH.doc).some(p=>!p));}
// Hits in document order.
function searchOrder(x,y){return x.page-y.page||x.line-y.line||x.a-y.a;}
// The part of the PDF area nothing covers (selPopArea), above the phone's search row while it is up: where a hit is shown.
function searchArea(){const a=selPopArea(),nav=$('#doc-nav');
  if(BAND===LAYOUT_BAND.PHONE&&nav.getClientRects().length)a.bottom=Math.min(a.bottom,nav.getBoundingClientRect().top);
  return a;}
// Scrolls hit h into the free part of the PDF area - 30% down it, as [보기] puts a mark - unless it already is, with 8px to
// spare; sideways only when a zoomed page has it off to a side. Its page counts as near the view from here on.
function searchReveal(h){const pg=document.getElementById('p'+h.page); if(!pg)return; const b=searchRect(h),L=$('#left'),a=searchArea();
  const r=pg.getBoundingClientRect(),x=r.left+pg.clientLeft,y=r.top+pg.clientTop,w=pg.clientWidth,ht=pg.clientHeight;
  const top=y+b[1]*ht,bottom=top+b[3]*ht,left=x+b[0]*w,right=left+b[2]*w;
  if(top<a.top+8||bottom>a.bottom-8)L.scrollTop+=top-(a.top+(a.bottom-a.top)*0.3);
  if(left<a.left+8||right>a.right-8)L.scrollLeft+=(left+right)/2-(a.left+a.right)/2;
  SEARCH.near.add(h.page);}   // in view now: its boxes are drawn at once, ahead of the observer
// Picks the current hit when there is none: the first at or after the reference (the page on screen, or the hit that was
// current), once every page between the two has been read; the first of all once the pages from the reference on hold none.
function searchPick(){if(SEARCH.cur||!SEARCH.hits.length)return; const r=SEARCH.ref,P=searchPages(SEARCH.doc);
  const c=SEARCH.hits.find(h=>h.page>r.page||(h.page===r.page&&(h.line>r.line||(h.line===r.line&&h.a>=r.a))));
  for(let n=r.page;n<=(c?c.page-1:P.length);n++)if(!P[n-1])return;
  SEARCH.cur=c||SEARCH.hits[0]; searchReveal(SEARCH.cur);}
// Draws the search's state: the count ('n/m', with '…' while pages are still unread; nothing without a query), the arrows,
// the hit boxes of the pages near the view, and - once the count is final - the announcement for a screen reader.
function searchPaint(){const n=SEARCH.hits.length,i=SEARCH.cur?SEARCH.hits.indexOf(SEARCH.cur)+1:0,busy=searchBusy();
  $('#search-count').textContent=SEARCH.q?i+'/'+n+(busy?'…':''):'';
  $('#search-prev').disabled=$('#search-next').disabled=!n;
  SEARCH.near.forEach(searchDrawPage);
  if(busy)return; const sr=$('#search-sr'),say=!SEARCH.q?'':n?tl('{m}개 중 {n}번째 · {page}쪽',{n:i,m:n,page:SEARCH.cur?SEARCH.cur.page:0}):tr('결과 없음');
  if(sr.textContent!==say)sr.textContent=say;}
// Reads the text of the searched document's unread pages, from the reference page on and then round to the pages before it,
// one page at a time and never while a page is being drawn; each page read adds its hits. Stops when the query is cleared or
// another document is searched; a page whose text cannot be read counts as blank.
async function searchRead(){const doc=SEARCH.doc; if(!doc||SEARCH.reading===doc)return; SEARCH.reading=doc;
  const P=searchPages(doc),N=P.length,from=Math.min(N,Math.max(1,SEARCH.ref.page));
  try{for(let k=0;k<N;k++){const n=(from-1+k)%N+1; if(P[n-1])continue;
      while(VEC.pumping||VEC.cur){await new Promise(r=>setTimeout(r,60)); if(SEARCH.doc!==doc||!SEARCH.q)return;}
      let got;
      try{const page=await doc.getPage(n),tc=await page.getTextContent(),vp=page.getViewport({scale:1});
        got={items:tc.items,styles:tc.styles,vt:vp.transform,w:vp.width,h:vp.height,lines:searchLines(tc.items)};}
      catch(e){if(VEC.doc!==doc)return; got={items:[],styles:{},vt:[1,0,0,1,0,0],w:1,h:1,lines:[]};}
      P[n-1]=got; if(SEARCH.doc!==doc||!SEARCH.q)return;
      const more=searchPageHits(got,n,SEARCH.q); if(more.length)SEARCH.hits=SEARCH.hits.concat(more).sort(searchOrder);
      searchPick(); searchPaint();}}
  finally{if(SEARCH.reading===doc)SEARCH.reading=null; if(SEARCH.doc===doc)searchPaint();}}
// Runs the field's query on the PDF on screen: the hits of the pages already read at once, the rest as searchRead() reads
// them. A new query starts from the hit that was current, the first one from the page on screen. No query, or no PDF: no hits.
function searchRun(){const q=searchFold(/** @type {HTMLInputElement} */($('#search-q')).value).t.trim(),doc=VEC.doc; if(q===SEARCH.q&&doc===SEARCH.doc)return;
  const a=topAnchor(); SEARCH.ref=SEARCH.cur&&doc===SEARCH.doc?SEARCH.cur:{page:a?a.page:1,line:0,a:0};
  SEARCH.q=q; SEARCH.doc=doc; SEARCH.cur=null; SEARCH.hits=[]; $('#doc-search').classList.toggle('has-q',!!q);
  if(!q||!doc){searchUnwatch(); searchPaint(); return;}
  searchPages(doc).forEach((P,i)=>{if(P)SEARCH.hits.push(...searchPageHits(P,i+1,q));});
  searchWatch(); searchPick(); searchPaint(); searchRead();}
// Goes to the next (d=1) or previous (d=-1) hit, wrapping, and shows it.
function searchGo(d){const n=SEARCH.hits.length; if(!n)return;
  SEARCH.cur=SEARCH.hits[searchStep(SEARCH.cur?SEARCH.hits.indexOf(SEARCH.cur):-1,n,d)]; searchReveal(SEARCH.cur); searchPaint();}

// The field's place for the layout now (docs/handbook/viewer.md §본문 검색): on the phone it is the dock; elsewhere its width
// is what the bar leaves beside its neighbours at their full width (searchWidth) - inline, or the magnifier alone - and
// --search-cap is how far the opened field may reach to the left inside the bar.
function searchFit(){const s=$('#doc-search'),nav=$('#doc-nav');
  searchInk(); if(BAND===LAYOUT_BAND.PHONE){s.dataset.mode='dock'; s.style.width=''; return;}
  if(s.hidden||!nav.getClientRects().length)return;
  const cs=getComputedStyle(nav),root=getComputedStyle(document.documentElement),px=v=>parseFloat(v)||0; let used=0,n=0;
  for(const k of /** @type {HTMLElement[]} */([...nav.children])){if(k===s||!k.getClientRects().length)continue; const m=getComputedStyle(k);
    used+=(k.id==='doc-links'?Math.max(k.getBoundingClientRect().width,k.scrollWidth):k.getBoundingClientRect().width)+px(m.marginLeft)+px(m.marginRight); n++;}
  const left=nav.getBoundingClientRect().left+px(cs.paddingLeft),room=nav.clientWidth-px(cs.paddingLeft)-px(cs.paddingRight)-used-px(cs.columnGap)*n;
  const w=searchWidth(room,px(root.getPropertyValue('--search-w')),px(root.getPropertyValue('--search-min')));
  s.dataset.mode=w?'inline':'icon'; s.style.width=w?w+'px':'';
  s.style.setProperty('--search-cap',Math.max(0,s.getBoundingClientRect().right-left)+'px');}
// The field's text on the row's centre line in any font: a line box puts a font's capitals above or below its centre by the
// font's metrics and the engine's rounding of them. #search-probe is the input's line laid out as an element (search.css): its
// baseline, less half the cap height (canvas metrics at 64 times the size, which the canvas rounds), says where the capitals'
// centre is, and --search-ink moves the input by what that misses the line's centre, in whole device pixels (the text stays
// crisp; a half goes up, where hinted capitals end up shorter than their outline). Measured with every fit of the field
// and when a font arrives (the bundled one, or a fallback before it).
function searchInk(){const p=$('#search-probe'),r=p.getBoundingClientRect(); if(!r.height)return;
  const cs=getComputedStyle(p),c=/** @type {CanvasRenderingContext2D} */(SEARCH_CTX||(SEARCH_CTX=document.createElement('canvas').getContext('2d')));
  c.font=cs.fontStyle+' '+cs.fontWeight+' '+parseFloat(cs.fontSize)*64+'px '+cs.fontFamily;
  const cap=c.measureText('H').actualBoundingBoxAscent/64,base=p.firstElementChild.getBoundingClientRect().bottom-r.top;
  const dpr=window.devicePixelRatio||1; $('#search-q').style.setProperty('--search-ink',Math.ceil((r.height/2-(base-cap/2))*dpr-0.5)/dpr+'px');}
// Whether the search is offered: not in the changes view (its PDF is a comparison, not the manuscript) and not while the PDF
// on screen cannot be read (PNG fallback, or not open yet). Hides the field and the navigation sheet's row otherwise, and a
// search that was open ends.
function searchOffer(){const off=document.body.classList.contains('revision-open')||!VEC.doc; if(off)searchClose(false);
  $('#doc-search').hidden=off; $('#ns-search').hidden=off; searchFit(); if(!off)searchRun();}
// Discloses the field (the dock on the phone, where an open sheet folds away for it; the opened box elsewhere) without
// moving the focus.
function searchShow(){if(SEARCH.open)return; SEARCH.open=true; document.body.classList.add('search-open'); $('#search-open').setAttribute('aria-expanded','true');
  if(BAND===LAYOUT_BAND.PHONE){SEARCH.side=SIDE_OPEN; if(SIDE_OPEN)setSide(false); searchInk();}}   // the phone's row is laid out only now
// The shortcut, the magnifier and the navigation sheet's row: discloses the field and puts the focus in it with its text
// selected, remembering what had the focus. Returns false when the search is not offered.
function searchOpen(){const s=$('#doc-search'),q=/** @type {HTMLInputElement} */($('#search-q')); if(s.hidden)return false;
  if(!SEARCH.open){const a=/** @type {HTMLElement|null} */(document.activeElement); SEARCH.back=a&&a!==document.body&&!s.contains(a)?a:null;}
  searchShow(); q.focus({preventScroll:true}); q.select(); return true;}
// Folds the disclosed field away; the phone's sheet comes back up if the search row had taken its place.
function searchHide(){if(!SEARCH.open)return; SEARCH.open=false; document.body.classList.remove('search-open'); $('#search-open').setAttribute('aria-expanded','false');
  if(SEARCH.side){SEARCH.side=false; if(BAND===LAYOUT_BAND.PHONE&&!SIDE_OPEN)setSide(true);}}
// Esc, [검색 닫기] and leaving the manuscript: the query and its hits go and the field folds away. back gives the focus to
// what had it before the search - or, when that is gone, to the magnifier or the phone's position button that leads to it.
function searchClose(back){const s=$('#doc-search'),q=/** @type {HTMLInputElement} */($('#search-q')),had=s.contains(document.activeElement),to=SEARCH.back;
  q.value=''; searchRun(); SEARCH.back=null; if(!SEARCH.open)return; searchHide();
  if(!back||!had)return;
  const next=to&&document.contains(to)&&to.getClientRects().length?to:BAND===LAYOUT_BAND.PHONE?$('#btn-pos'):s.dataset.mode==='icon'?$('#search-open'):null;
  if(next)next.focus({preventScroll:true}); else q.blur();}
// Another document or another build is on screen (vecOpen): the query, its hits and the reading of the old text end; the
// field stays as it is.
function searchClear(){/** @type {HTMLInputElement} */($('#search-q')).value=''; searchRun();}
$('#search-q').addEventListener('input',searchRun);
// Focusing the field discloses it (a click or a Tab into it; what lost the focus is where Esc returns to), and it folds away
// again when the focus leaves the search with nothing typed.
$('#search-q').addEventListener('focus',e=>{if(!SEARCH.open)SEARCH.back=/** @type {HTMLElement|null} */(e.relatedTarget); searchShow();});
$('#doc-search').addEventListener('focusout',e=>{const to=/** @type {Node|null} */(e.relatedTarget);
  if(SEARCH.open&&!SEARCH.q&&!(to&&$('#doc-search').contains(to)))searchHide();});
// Keys in the search: Enter is the next hit and Shift+Enter the previous (not while an IME composes); Esc ends the search.
// Neither reaches the viewer's own keys (events.js), so Esc here never cancels a selection or a draft.
$('#doc-search').addEventListener('keydown',e=>{if(e.isComposing||e.keyCode===229)return;
  if(e.key==='Escape'){e.preventDefault(); e.stopPropagation(); searchClose(true);}
  else if(e.key==='Enter'&&e.target===$('#search-q')){e.preventDefault(); e.stopPropagation(); searchGo(e.shiftKey?-1:1);}});
// ⌘F on an Apple platform, Ctrl+F elsewhere: the field takes the focus instead of the browser's find, which finds nothing in a
// canvas. Pressed again in the field, under a sheet, or where the search is not offered, it is the browser's.
/** @param {KeyboardEvent} e */
function searchShortcut(e){if(e.code!=='KeyF'&&e.key!=='f'&&e.key!=='F')return;
  if(e.altKey||e.shiftKey||(IS_MAC?!e.metaKey||e.ctrlKey:!e.ctrlKey||e.metaKey))return;
  if(document.activeElement===$('#search-q')||document.querySelector('dialog[open]'))return;
  if(searchOpen())e.preventDefault();}
document.addEventListener('keydown',searchShortcut);
$('#search-hint').textContent=IS_MAC?'⌘F':'Ctrl F';
// The bar's room changes with its width and with its neighbours (the document links drawn, a page count growing, a font
// arriving): fitted again on the next frame, never inside the observer.
if(window.ResizeObserver){const o=new ResizeObserver(()=>requestAnimationFrame(searchFit)); o.observe($('#doc-nav'));
  for(const k of $('#doc-nav').children)if(k.id!=='doc-search')o.observe(k);}
document.fonts.addEventListener('loadingdone',searchFit);
