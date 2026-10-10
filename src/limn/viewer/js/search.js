// ------------------------------------------------ In-document text search (docs/handbook/viewer.md §본문 검색)
// The pages are canvases, so the browser's own find has nothing to find in them: the nav bar's field (#doc-search) searches the
// text of the PDF on screen instead. The text comes from PDF.js (a page's getTextContent), read page by page only once a query
// asks for it, after any page that is being drawn, and kept for as long as that document object is open (one per build). A hit
// lies within one page and may run over its line ends; its boxes - one for each line it lies on - are drawn over the page from
// the text items' geometry, in page fractions like a mark. No text layer is added - a drag on the page stays a region
// selection (pdf-open.js).
// - Matching: searchFold() on both sides (case, Unicode composition and width, runs of spaces, curly quotes and dashes), then
//   searchPattern(): a line break is a space or nothing, and a hyphen that ends a line may be left out.
// - Where the field is: in the nav bar when there is room (inline), folded to a magnifier when there is not (icon), and on the
//   phone - which has no nav bar - a row in place of the sheet's bar, opened from the navigation sheet (dock). searchFit().
//   While the opened field lies over its neighbours in the bar they are taken off it whole (searchCover).
// - Ends with: Esc or [검색 닫기] (cleared, focus back), another document or a new build (searchClear, from vecOpen), the changes
//   view and a PDF that cannot be read (searchOffer hides it).

// The text as it is matched: Unicode NFKC (Hangul jamo composed, a letter and its combining mark joined, ligatures and
// full-width forms unfolded), lower case, curly quotes and dashes as ' " and -, soft hyphens and zero-width marks dropped, every
// run of white space one space; control characters dropped (the flow's break marks, searchFlow, never come from a page). Returns {t, at}: the folded text and, for each of its UTF-16 units, the index in s where the
// cluster it came from starts, then s.length - so a match in t maps back to a run of s. Pure.
/** @param {string} s @returns {{t:string,at:number[]}} */
function searchFold(s){const plain={'\u2018':"'",'\u2019':"'",'\u201A':"'",'\u201C':'"','\u201D':'"','\u201E':'"'},t=[],at=[]; s=String(s);
  // a cluster: Hangul jamo that compose one syllable, or one character, each with the combining marks after it; or a run of spaces
  const cluster=/[\u1100-\u115F\uA960-\uA97C]+[\u1160-\u11A7\uD7B0-\uD7C6]*[\u11A8-\u11FF\uD7CB-\uD7FB]*\p{M}*|\s+|[^]\p{M}*/gu;
  for(const m of s.matchAll(cluster)){
    const p=/^\s+$/.test(m[0])?' ':m[0].normalize('NFKC').toLowerCase().replace(/[\u0000-\u0008\u000E-\u001F\u007F\u00AD\u200B-\u200D\u2060\uFEFF]/g,'')
      .replace(/[\u2018\u2019\u201A\u201C\u201D\u201E]/g,c=>plain[c]).replace(/[\u2010-\u2015\u2212]/g,'-').replace(/\s+/g,' ');
    for(let k=0;k<p.length;k++){if(p[k]===' '&&t[t.length-1]===' ')continue; t.push(p[k]); at.push(/** @type {number} */(m.index));}}
  at.push(s.length); return {t:t.join(''),at};}
// A page's lines from PDF.js text items: the items up to one marked hasEOL are one line, whatever their fonts, so a query may
// span them. A line that jumps across a gap wider than its font's size - a table's cells, a centred row, an \hfill, a line TeX
// had to stretch - is cut there into pieces that are never joined to each other or to the lines around them (searchJoin: only
// a line in one piece is plain). Each piece is {t, at, parts, end, plain, box}: its text folded (searchFold: at maps into the
// piece's unfolded text), per item with text the item's index i and where its text starts in the unfolded piece (from), the
// last character of its own text (end: a line-final hyphen is told from a dash by it), whether its line is in one piece, and
// where it stands in PDF units measured in its own direction - {x0, x1 along the line, y: across it, up being +, size: font
// size, ang: the line's angle in whole degrees}, so a page set sideways reads as an upright one - or null for text that is
// skewed, mirrored or of mixed directions. Blank pieces are left out. Pure.
/** @param {any[]} items */
function searchLines(items){const rows=/** @type {any[][]} */([]); let row=/** @type {any[]} */([]);
  items.forEach((it,i)=>{if(typeof it.str!=='string')return; const T=Array.isArray(it.transform)&&it.transform.length===6?it.transform:[0,0,0,0,0,0];
    const su=Math.hypot(T[0],T[1]),sv=Math.hypot(T[2],T[3]),ok=su>0&&sv>0&&T[0]*T[3]-T[1]*T[2]>0&&Math.abs(T[0]*T[2]+T[1]*T[3])<=1e-3*su*sv;
    const ux=ok?T[0]/su:1,uy=ok?T[1]/su:0,vx=ok?T[2]/sv:0,vy=ok?T[3]/sv:1;   // the line's direction and its up
    row.push({i,it,ok,x:T[4]*ux+T[5]*uy,w:Number(it.width)||0,y:T[4]*vx+T[5]*vy,size:sv,ang:Math.round(Math.atan2(uy,ux)*180/Math.PI)}); if(it.hasEOL){rows.push(row); row=[];}});
  if(row.length)rows.push(row);
  const lines=/** @type {any[]} */([]);
  rows.forEach(r=>{const mine=/** @type {any[]} */([]); let raw='',parts=/** @type {{i:number,from:number}[]} */([]),g=/** @type {any} */(null);
    const end=()=>{if(raw.trim()){const f=searchFold(raw); mine.push({t:f.t,at:f.at,parts,end:raw.trimEnd().slice(-1),plain:true,box:g&&g.ok?{x0:g.x0,x1:g.x1,y:g.y,size:g.size,ang:g.ang}:null});}
      raw=''; parts=[]; g=null;};
    r.forEach(p=>{if(p.it.str.trim()){
        if(g&&g.ok&&p.ok&&p.ang===g.ang&&p.x-g.x1>g.size)end();   // a gap wider than the font: another piece
        if(!g)g={ok:p.ok,x0:p.x,x1:p.x+p.w,y:p.y,size:p.size,ang:p.ang};
        else{g.ok=g.ok&&p.ok&&p.ang===g.ang; if(g.ok){g.x0=Math.min(g.x0,p.x); g.x1=Math.max(g.x1,p.x+p.w); g.size=Math.max(g.size,p.size);}}}
      if(p.it.str){parts.push({i:p.i,from:raw.length}); raw+=p.it.str;}});
    end(); if(mine.length>1)mine.forEach(L=>{L.plain=false;}); lines.push(...mine);});
  return lines;}
// How a line meets the next one in a page's flow (searchFlow), as the mark put between them. A query crosses a line's end only
// between two consecutive lines of one wrapped paragraph, as TeX breaks a paragraph into lines; a false hit - a highlight on
// text that does not hold the query - is worse than a missed one, so everything else is HARD and never crossed (headings,
// centred and short lines, list items with hanging indents, table rows, \hfill lines, equations, captions, another column).
// Two lines are consecutive lines of a paragraph when both are plain (searchLines), run the same way at the same font size,
// the first reaches its column's right edge and starts at the column's left edge or a paragraph indent, and the second starts
// at the left edge or a paragraph indent directly below - one line pitch of that font lower (1 to 1.5 font sizes). The column's
// edges are those of the lines that overlap the line sideways (searchEdges), within SEARCH_EDGE_PT; a paragraph indent is 1 to
// 2 font sizes in from the left edge. Between two such lines: a line that ends in a hyphen (-, U+2010 or a soft hyphen) was
// hyphenated - HYPH, the hyphen may be typed or left out; one that ends in a dash (an en or em dash, folded to -) runs on with
// no space - DASH, the dash must be typed; a Hangul or CJK character on either side - CJK, the break is a space or nothing, as
// such text breaks inside a word; else - SPACE, a word space that a query must type, as TeX never breaks a Latin word without a
// hyphen.
const SEARCH_BREAK=Object.freeze({SPACE:'\n',CJK:'\u0002',HYPH:'\u0003',DASH:'\u0004',HARD:'\u0005'});
const SEARCH_CJK=/[\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u;
const SEARCH_EDGE_PT=3;   // how near a column's edge a line ends or starts to count as reaching it, in PDF points
// The column edges of each line: the least x0 and the greatest x1 over the lines running its way that overlap it sideways
// (itself included), or null for a line without geometry. Pure.
/** @param {any[]} lines */
function searchEdges(lines){return lines.map(L=>{const A=L.box; if(!A)return null; let l=A.x0,r=A.x1;
  for(const M of lines){const B=M.box; if(B&&B.ang===A.ang&&B.x0<A.x1&&B.x1>A.x0){l=Math.min(l,B.x0); r=Math.max(r,B.x1);}}
  return {l,r};});}
// The break between line a and the next line b, with their column edges ea and eb (searchEdges): a SEARCH_BREAK mark. Pure.
/** @param {any} a @param {any} b @param {{l:number,r:number}|null} ea @param {{l:number,r:number}|null} eb */
function searchJoin(a,b,ea,eb){const A=a.box,B=b.box; if(!A||!B||!ea||!eb||!a.plain||!b.plain||A.ang!==B.ang||Math.abs(A.size-B.size)>0.1)return SEARCH_BREAK.HARD;
  const dy=A.y-B.y,starts=(x,e,size)=>x-e.l<=SEARCH_EDGE_PT||(x-e.l>=size&&x-e.l<=2*size);
  if(dy<A.size-0.01||dy>1.5*A.size+0.01||ea.r-A.x1>SEARCH_EDGE_PT||!starts(A.x0,ea,A.size)||!starts(B.x0,eb,B.size))return SEARCH_BREAK.HARD;
  if(/[-\u2010\u00AD]/.test(a.end))return SEARCH_BREAK.HYPH;
  const x=a.t.trimEnd().slice(-1),y=b.t.trimStart().charAt(0);
  if(x==='-')return SEARCH_BREAK.DASH;
  return SEARCH_CJK.test(x)||SEARCH_CJK.test(y)?SEARCH_BREAK.CJK:SEARCH_BREAK.SPACE;}
// A page's lines as one flow of text, so a query may run over a line's end: each line's folded text (searchLines), trimmed,
// joined to the next by the mark of how they meet (searchJoin). Returns {t, rows}: the flow and, for each line, where it starts
// in the flow (at), how many folded characters the trim took off its head (cut) and its trimmed length (n). Pure.
/** @param {any[]} lines */
function searchFlow(lines){let t=''; const rows=/** @type {{at:number,cut:number,n:number}[]} */([]),edges=searchEdges(lines);
  lines.forEach((L,i)=>{const body=L.t.trim(); if(i)t+=searchJoin(lines[i-1],L,edges[i-1],edges[i]); rows.push({at:t.length,cut:L.t.length-L.t.trimStart().length,n:body.length}); t+=body;});
  return {t,rows};}
// The folded query q as a pattern over a page's flow (searchFlow): every character is itself; a space is a space, a SPACE break
// or a CJK one; between two characters there may be a CJK break, a HYPH break (with the line's hyphen before it, or after the
// hyphen when the query types it) or a DASH break. A SPACE break is crossed only by a typed space and a HARD one never. null for
// an empty query. Pure.
/** @param {string} q @returns {RegExp|null} */
function searchPattern(q){const cs=[...q]; if(!cs.length)return null; let p='';
  cs.forEach((c,i)=>{if(c===' '){p+='[ \\n\\u0002]'; return;} p+=/[\\^$.*+?()[\]{}|]/.test(c)?'\\'+c:c; if(i<cs.length-1&&cs[i+1]!==' ')p+='(?:\\u0002|-?\\u0003|\\u0004)?';});
  return new RegExp(p,'gu');}
// Where pattern re matches in flow F, left to right and without overlap. Each hit is its pieces [line, from, to] - one for
// every line it lies on, from-to in that line's folded text - in reading order; nothing without a pattern. Pure.
/** @param {{t:string,rows:{at:number,cut:number,n:number}[]}} F @param {RegExp|null} re @returns {number[][][]} */
function searchFind(F,re){const out=/** @type {number[][][]} */([]); if(!re)return out; let k=0;
  for(const m of F.t.matchAll(re)){const s=/** @type {number} */(m.index),e=s+m[0].length,ps=[];
    while(k<F.rows.length-1&&F.rows[k+1].at<=s)k++;
    for(let i=k;i<F.rows.length&&F.rows[i].at<e;i++){const r=F.rows[i],a=Math.max(s,r.at),b=Math.min(e,r.at+r.n); if(b>a)ps.push([i,a-r.at+r.cut,b-r.at+r.cut]);}
    if(ps.length)out.push(ps);}
  return out;}
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
// Whether keydown e is the search shortcut: Cmd on an Apple platform (mac) and Ctrl elsewhere, alone, with the key that types
// f - whatever its place on the layout (Dvorak's f is the physical Y key; its physical F key types u and is not it). A key
// that types no Latin letter (a Hangul jamo, an input method's 'Process') counts by its place: the physical F key. Pure.
/** @param {{key?:string,code?:string,ctrlKey?:boolean,metaKey?:boolean,altKey?:boolean,shiftKey?:boolean}} e @param {boolean} mac */
function searchKey(e,mac){if(e.altKey||e.shiftKey||(mac?!e.metaKey||e.ctrlKey:!e.ctrlKey||e.metaKey))return false;
  const k=String(e.key||''); return /^\p{Script=Latin}$/u.test(k)?k.toLowerCase()==='f':e.code==='KeyF';}

// The search on screen. q: the folded query ('' = none) and re its pattern. doc: the PDF.js document the hits are of. hits:
// every hit in document order as {page, line, a, pieces, boxes?} (pieces as searchFind gives them; line and a are where the
// first one starts; boxes cached by searchBoxes). cur: the current hit. ref: where a query looks for its current hit from (the
// page on screen when the search began, then the hit that was last current). reading: the document whose pages are being read.
// failed: the pages whose text could not be read for this query. composing: an input method is composing in the field.
// open: the field is disclosed (focused or holding a query). back: what had the focus before the field was entered. away: the
// window lost the focus while it was in the field. side: the phone's sheet was open when the search row took its place.
// ink: the field's text shift in px (searchInk). near: the pages near the view, the only ones that carry hit boxes. text:
// each open document's pages as read ({items, styles, vt, w, h, lines, flow}; null until read).
const SEARCH={q:'',re:/** @type {RegExp|null} */(null),doc:/** @type {any} */(null),hits:/** @type {any[]} */([]),cur:/** @type {any} */(null),ref:{page:1,line:0,a:0},
  reading:/** @type {any} */(null),failed:new Set(),composing:false,open:false,back:/** @type {HTMLElement|null} */(null),away:false,side:false,ink:0,
  near:new Set(),io:/** @type {IntersectionObserver|null} */(null),text:new WeakMap()};
// The pages of document doc as read so far, index 0 for page 1 (null = not read yet); kept until the document is closed.
function searchPages(doc){let P=SEARCH.text.get(doc); if(!P){P=new Array(doc.numPages).fill(null); SEARCH.text.set(doc,P);} return P;}
// The hits of pattern re on read page P, number n, in reading order.
function searchPageHits(P,n,re){return searchFind(P.flow,re).map(pieces=>({page:n,line:pieces[0][0],a:pieces[0][1],pieces,boxes:/** @type {number[][]|null} */(null)}));}
// The width of text in a generic font family, in an arbitrary unit (a shared canvas): searchBox()'s measure.
let SEARCH_CTX=/** @type {CanvasRenderingContext2D|null} */(null);
/** @param {string} text @param {string} family */
function searchMeasure(text,family){const c=/** @type {CanvasRenderingContext2D} */(SEARCH_CTX||(SEARCH_CTX=document.createElement('canvas').getContext('2d')));
  c.font='100px '+family; return c.measureText(text).width;}
// The box of one piece of a hit - characters a to b of line `line`'s folded text - on read page P, as fractions [x, y, w, h]:
// the union of its run in each text item of the line. The folded run maps back to the line's own characters through the
// line's map, to the end of the last character's cluster - both letters of a ligature are the ligature's box.
/** @param {any} P @param {number[]} piece */
function searchPieceBox(P,[line,a,b]){const L=P.lines[line]; let k=b;
  while(k<L.at.length-1&&L.at[k]<=L.at[b-1])k++;
  const r0=L.at[a],r1=L.at[k]; let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(const p of L.parts){const it=P.items[p.i],s=Math.max(r0,p.from)-p.from,e=Math.min(r1,p.from+it.str.length)-p.from; if(e<=s)continue;
    const c=searchBox(it,P.styles[it.fontName]||{},P.vt,P.w,P.h,s,e,searchMeasure);
    x0=Math.min(x0,c[0]); y0=Math.min(y0,c[1]); x1=Math.max(x1,c[0]+c[2]); y1=Math.max(y1,c[1]+c[3]);}
  return x1>=x0?[x0,y0,x1-x0,y1-y0]:[0,0,0,0];}
// A hit's boxes on its page, one for each line it lies on.
function searchBoxes(h){return h.boxes||(h.boxes=h.pieces.map(p=>searchPieceBox(searchPages(SEARCH.doc)[h.page-1],p)));}
// Draws page n's hit boxes (the current hit's marked, every one of them), or removes them when the page is not near the view
// or has none.
function searchDrawPage(n){const pg=document.getElementById('p'+n); if(!pg)return; pg.querySelectorAll('.search-hit').forEach(e=>e.remove());
  if(!SEARCH.near.has(n))return;
  for(const h of SEARCH.hits){if(h.page!==n)continue; for(const b of searchBoxes(h)){const d=document.createElement('div'); d.className='search-hit'+(h===SEARCH.cur?' cur':'');
    Object.assign(d.style,{left:b[0]*100+'%',top:b[1]*100+'%',width:b[2]*100+'%',height:b[3]*100+'%'}); pg.appendChild(d);}}}
// Follows which pages are near the view (within one view height) while there is a query: only those carry hit boxes, drawn as
// they come near and removed as they leave, so a common letter in a long document does not fill the page list with boxes.
function searchWatch(){if(SEARCH.io||!window.IntersectionObserver)return;
  const io=SEARCH.io=new IntersectionObserver(es=>{for(const en of es){const n=Number(/** @type {HTMLElement} */(en.target).dataset.page);
    if(en.isIntersecting)SEARCH.near.add(n); else SEARCH.near.delete(n); searchDrawPage(n);}},{root:$('#left'),rootMargin:'100% 0px'});
  $$('.pg').forEach(pg=>io.observe(pg));}
// Stops following the pages and removes every hit box: the next query follows the pages that are on screen then.
function searchUnwatch(){if(SEARCH.io)SEARCH.io.disconnect(); SEARCH.io=null; SEARCH.near.clear(); $$('.search-hit').forEach(e=>e.remove());}
// Whether the count is not final yet: the PDF is still opening (another document or build on its way), or pages of the
// searched document are still to be read. A page whose text could not be read for this query is not waited for.
function searchBusy(){return !!SEARCH.q&&(!SEARCH.doc||searchPages(SEARCH.doc).some((p,i)=>!p&&!SEARCH.failed.has(i+1)));}
// How many pages of the searched document could not be read for this query: they are left out of the count, and said with it.
function searchUnread(){return SEARCH.q&&SEARCH.doc?searchPages(SEARCH.doc).filter((p,i)=>!p&&SEARCH.failed.has(i+1)).length:0;}
// Hits in document order.
function searchOrder(x,y){return x.page-y.page||x.line-y.line||x.a-y.a;}
// The part of the PDF area nothing covers (selPopArea), above the phone's search rows - and the status line standing on them -
// while they are up: where a hit is shown.
function searchArea(){const a=selPopArea(),nav=$('#doc-nav'),dock=$('#status-dock');
  if(BAND===LAYOUT_BAND.PHONE&&nav.getClientRects().length){a.bottom=Math.min(a.bottom,nav.getBoundingClientRect().top);
    if(dock.getClientRects().length)a.bottom=Math.min(a.bottom,dock.getBoundingClientRect().top);}
  return a;}
// The phone's search rows' height (--search-rows): the status line stands on them while the search is open (search.css).
function searchRows(){if(BAND===LAYOUT_BAND.PHONE&&SEARCH.open)document.documentElement.style.setProperty('--search-rows',Math.round($('#doc-nav').getBoundingClientRect().height)+'px');}
// Scrolls hit h into the free part of the PDF area unless every line of it already is there, with 8px to spare: its first line
// 30% down the area, as [보기] puts a mark, or higher so that its last line still shows when it runs over lines; a hit taller
// than the area shows its first line at the area's top. Sideways only when a zoomed page has its start off to a side. Its page
// counts as near the view from here on.
function searchReveal(h){const pg=document.getElementById('p'+h.page); if(!pg)return; const bs=searchBoxes(h),L=$('#left'),a=searchArea();
  const r=pg.getBoundingClientRect(),x=r.left+pg.clientLeft,y=r.top+pg.clientTop,w=pg.clientWidth,ht=pg.clientHeight;
  const top=y+Math.min(...bs.map(b=>b[1]))*ht,bottom=y+Math.max(...bs.map(b=>b[1]+b[3]))*ht,left=x+bs[0][0]*w,right=left+bs[0][2]*w;
  if(top<a.top+8||bottom>a.bottom-8){const want=bottom-top>a.bottom-a.top-16?a.top+8:Math.min(a.top+(a.bottom-a.top)*0.3,a.bottom-8-(bottom-top)); L.scrollTop+=top-want;}
  if(left<a.left+8||right>a.right-8)L.scrollLeft+=(left+right)/2-(a.left+a.right)/2;
  SEARCH.near.add(h.page);}   // in view now: its boxes are drawn at once, ahead of the observer
// Picks the current hit when there is none: the first at or after the reference, once every page between the two has been
// read (or could not be); the first of all once the pages from the reference on hold none.
function searchPick(){if(SEARCH.cur||!SEARCH.hits.length)return; const r=SEARCH.ref,P=searchPages(SEARCH.doc);
  const c=SEARCH.hits.find(h=>h.page>r.page||(h.page===r.page&&(h.line>r.line||(h.line===r.line&&h.a>=r.a))));
  for(let n=r.page;n<=(c?c.page-1:P.length);n++)if(!P[n-1]&&!SEARCH.failed.has(n))return;
  SEARCH.cur=c||SEARCH.hits[0]; searchReveal(SEARCH.cur);}
// Draws the search's state: the count ('n/m'; with '…' while pages are still to be read, and with how many pages could not
// be read once they have been tried; nothing without a query), the arrows, the hit boxes of the pages near the view, and -
// once the count is final and no input method is composing - the announcement for a screen reader.
function searchPaint(){const n=SEARCH.hits.length,i=SEARCH.cur?SEARCH.hits.indexOf(SEARCH.cur)+1:0,busy=searchBusy(),lost=busy?0:searchUnread();
  const miss=lost?' · '+tl('못 읽은 쪽 {n}',{n:lost}):'';
  $('#search-count').textContent=SEARCH.q?i+'/'+n+(busy?'…':miss):'';
  $('#search-prev').disabled=$('#search-next').disabled=!n;
  SEARCH.near.forEach(searchDrawPage); searchCover(); searchRows();
  if(busy||SEARCH.composing)return; const sr=$('#search-sr');
  const say=!SEARCH.q?'':(n?tl('{m}개 중 {n}번째 · {page}쪽',{n:i,m:n,page:SEARCH.cur?SEARCH.cur.page:0}):tr('결과 없음'))+miss;
  if(sr.textContent!==say)sr.textContent=say;}
// Reads the text of the searched document's unread pages, from the reference page on and then round to the pages before it,
// one page at a time and never while a page is being drawn; each page read adds its hits. Stops when the query is cleared or
// another document is searched. A page whose text cannot be read is left unread and not tried again for this query (the next
// query tries it again); the pages after it are still read.
async function searchRead(){const doc=SEARCH.doc; if(!doc||SEARCH.reading===doc)return; SEARCH.reading=doc;
  const P=searchPages(doc),N=P.length;
  try{for(;;){const from=Math.min(N,Math.max(1,SEARCH.ref.page)); let n=0;
      for(let k=0;k<N&&!n;k++){const c=(from-1+k)%N+1; if(!P[c-1]&&!SEARCH.failed.has(c))n=c;}
      if(!n)return;
      while(VEC.pumping||VEC.cur){await new Promise(r=>setTimeout(r,60)); if(SEARCH.doc!==doc||!SEARCH.q)return;}
      try{const page=await doc.getPage(n),tc=await page.getTextContent(),vp=page.getViewport({scale:1}),lines=searchLines(tc.items);
        P[n-1]={items:tc.items,styles:tc.styles,vt:vp.transform,w:vp.width,h:vp.height,lines,flow:searchFlow(lines)};}
      catch(e){if(VEC.doc!==doc)return; if(SEARCH.doc===doc)SEARCH.failed.add(n);}
      if(SEARCH.doc!==doc||!SEARCH.q)return;
      const more=P[n-1]?searchPageHits(P[n-1],n,SEARCH.re):[]; if(more.length)SEARCH.hits=SEARCH.hits.concat(more).sort(searchOrder);
      searchPick(); searchPaint();}}
  finally{if(SEARCH.reading===doc)SEARCH.reading=null; if(SEARCH.doc===doc)searchPaint();}}
// A Hangul jamo standing alone - what an input method shows between the first key of a syllable and its vowel.
const SEARCH_JAMO=/[\u1100-\u11FF\u3131-\u318E\uA960-\uA97F\uD7B0-\uD7FF]/;
// Runs the field's query on the PDF on screen: the hits of the pages already read at once, the rest as searchRead() reads
// them. While an input method composes, a jamo standing alone before the caret is not part of the query yet (the syllable has
// only begun). The current hit is looked for from the hit that was last current - through queries that had none - and from
// the page on screen when the search starts from an empty field or on another document. No query, or no PDF: no hits.
function searchRun(){const f=/** @type {HTMLInputElement} */($('#search-q')),doc=VEC.doc; let v=f.value;
  if(SEARCH.composing){const c=f.selectionStart||0; if(c>0&&SEARCH_JAMO.test(v[c-1]))v=v.slice(0,c-1)+v.slice(c);}
  const q=searchFold(v).t.trim(); if(q===SEARCH.q&&doc===SEARCH.doc)return;
  if(SEARCH.cur&&doc===SEARCH.doc)SEARCH.ref={page:SEARCH.cur.page,line:SEARCH.cur.line,a:SEARCH.cur.a};
  else if(doc!==SEARCH.doc||!SEARCH.q){const a=topAnchor(); SEARCH.ref={page:a?a.page:1,line:0,a:0};}
  SEARCH.q=q; SEARCH.re=searchPattern(q); SEARCH.doc=doc; SEARCH.cur=null; SEARCH.hits=[]; SEARCH.failed.clear(); $('#doc-search').classList.toggle('has-q',!!q);
  // with a query the overlay panel's width is kept clear of the page (responsive.css), as while composing: re-fit before a hit is shown
  const b=document.body; if(b.classList.contains('searching')!==!!q){b.classList.toggle('searching',!!q); if(q&&MID_OVERLAY&&SIDE_OPEN)relayout();}
  if(!q||!doc){searchUnwatch(); searchPaint(); return;}
  searchPages(doc).forEach((P,i)=>{if(P)SEARCH.hits.push(...searchPageHits(P,i+1,SEARCH.re));});
  searchWatch(); searchPick(); searchPaint(); searchRead();}
// Goes to the next (d=1) or previous (d=-1) hit, wrapping, and shows it.
function searchGo(d){const n=SEARCH.hits.length; if(!n)return;
  SEARCH.cur=SEARCH.hits[searchStep(SEARCH.cur?SEARCH.hits.indexOf(SEARCH.cur):-1,n,d)]; searchReveal(SEARCH.cur); searchPaint();}

// The field's place for the layout now (docs/handbook/viewer.md §본문 검색): on the phone it is the dock; elsewhere its width
// is what the bar leaves beside its neighbours at their full width (searchWidth) - inline, or the magnifier alone - and
// --search-cap is how far the opened field may reach to the left inside the bar.
function searchFit(){const s=$('#doc-search'),nav=$('#doc-nav');
  if(BAND===LAYOUT_BAND.PHONE){s.dataset.mode='dock'; s.style.width=''; searchInk(); searchCover(); return;}
  if(s.hidden||!nav.getClientRects().length){searchCover(); return;}
  const cs=getComputedStyle(nav),root=getComputedStyle(document.documentElement),px=v=>parseFloat(v)||0; let used=0,n=0;
  for(const k of /** @type {HTMLElement[]} */([...nav.children])){if(k===s||!k.getClientRects().length)continue; const m=getComputedStyle(k);
    used+=(k.id==='doc-links'?Math.max(k.getBoundingClientRect().width,k.scrollWidth):k.getBoundingClientRect().width)+px(m.marginLeft)+px(m.marginRight); n++;}
  const left=nav.getBoundingClientRect().left+px(cs.paddingLeft),room=nav.clientWidth-px(cs.paddingLeft)-px(cs.paddingRight)-used-px(cs.columnGap)*n;
  const w=searchWidth(room,px(root.getPropertyValue('--search-w')),px(root.getPropertyValue('--search-min')));
  s.dataset.mode=w?'inline':'icon'; s.style.width=w?w+'px':'';
  s.style.setProperty('--search-cap',Math.max(0,s.getBoundingClientRect().right-left)+'px'); searchInk(); searchCover();}
// While the opened field lies over the bar, every neighbour its box meets - or comes within the bar's gap of - is taken off
// the bar whole (.search-covered: not drawn, no press, no focus; it keeps its place, so closing puts it back as it was), and
// the field takes their place: --search-span widens it to the left, from where it ends to one bar gap after the last neighbour
// left on its left (the bar's content edge when none is), so no blank run is left where they stood. The status line is never
// taken off (the short band holds it in this row): it moves to stand right after what is left on the left (.search-kept, flex
// order) and gives way to the field last (below) - it keeps its icon, its action and, as long as anything else can yield,
// its words: drawn, pressable, spoken. The natural box is
// measured first and the span set in the same task, so the field is drawn at its full span in the frame it opens and its text
// does not move after. Nothing is covered on the phone (it has no bar) or while the field is closed.
function searchCover(){const s=$('#doc-search'),nav=$('#doc-nav'),box=$('#search-box'),kids=/** @type {HTMLElement[]} */([...nav.children]).filter(k=>k!==s);
  if(s.style.getPropertyValue('--search-span'))s.style.removeProperty('--search-span');   // the natural box first: the span is worked out from it
  s.classList.remove('search-squeezed');
  for(const k of kids){if(k.matches('.search-covered,.search-left,.search-kept,.search-tight'))k.classList.remove('search-covered','search-left','search-kept','search-tight'); if(k.style.maxWidth)k.style.maxWidth='';}
  const b=SEARCH.open&&!s.hidden&&BAND!==LAYOUT_BAND.PHONE&&box.getClientRects().length?box.getBoundingClientRect():null; if(!b)return;   // closed: nothing is measured
  const cs=getComputedStyle(nav),gap=parseFloat(cs.columnGap)||0,keep=/** @type {HTMLElement[]} */([]),off=/** @type {HTMLElement[]} */([]),left=/** @type {HTMLElement[]} */([]);
  // Each neighbour before the search in the bar is left in place (it ends a gap short of the field), kept (the status line)
  // or taken off - also one the bar has squeezed to no width (a long status line at rest does that to the document links),
  // which would come back under the field as soon as the status is shortened.
  for(const k of kids){if(!k.getClientRects().length||!(k.compareDocumentPosition(s)&Node.DOCUMENT_POSITION_FOLLOWING))continue;
    const r=k.getBoundingClientRect();
    if(r.width&&r.right<=b.left-gap+0.5)left.push(k);
    else if(r.width||!(r.left>=b.right))(k.matches('[role=status],[aria-live]')||k.querySelector('[role=status],[aria-live]')?keep:off).push(k);}
  if(!off.length&&!keep.length)return;
  off.forEach(k=>k.classList.add('search-covered')); left.forEach(k=>k.classList.add('search-left')); keep.forEach(k=>k.classList.add('search-kept'));
  const edge=()=>[...left,...keep].reduce((e,k)=>Math.max(e,k.getBoundingClientRect().right+gap),nav.getBoundingClientRect().left+nav.clientLeft+(parseFloat(cs.paddingLeft)||0));
  let span=s.getBoundingClientRect().right-edge();
  if(!keep.length){s.style.setProperty('--search-span',Math.max(b.width,span)+'px'); return;}
  // The status line's words are what it says; as the row narrows they give way last. First the field shrinks, down to its
  // least width (the open box's min-content: the query keeps --search-q-min); then the neighbours left of the status are
  // taken off, the nearest first, all but the row's first (the outline toggle); then the status's dismiss button goes (it
  // can be dismissed once the search is closed);
  // only then do its words shorten to an ellipsis.
  const k=keep[keep.length-1];
  s.style.setProperty('--search-span','0px'); const least=box.getBoundingClientRect().width;   // min-width:min-content holds it there
  while(span<least&&left.length>1){const m=/** @type {HTMLElement} */(left.pop()); m.classList.replace('search-left','search-covered'); span=s.getBoundingClientRect().right-edge();}   // the first (the outline toggle) stays
  if(span<least){k.classList.add('search-tight'); span=s.getBoundingClientRect().right-edge();}
  if(span<least){const tx=k.querySelector('.st-tx'),floor=Math.ceil(k.getBoundingClientRect().width-(tx?tx.getBoundingClientRect().width:0));   // its icon and actions
    // shortened again while the field still lacks room: a status wider than the bar at rest had pushed the search to the right,
    // and each shortening brings it back left by as much
    for(let n=0;n<4&&span<least;n++){const w=k.getBoundingClientRect().width; if(w<=floor+0.5)break;
      k.style.maxWidth=Math.max(floor,Math.floor(w-(least-span)))+'px'; span=s.getBoundingClientRect().right-edge();}}
  // (The field's right end is measured again each time: a status line wider than the bar at rest pushes the search to the
  // right until it is shortened.)
  // Last, when even the status's icon and actions leave the field less than its least width, the field goes under it
  // (.search-squeezed: its query shorter than --search-q-min) rather than over the status: nothing overlaps.
  s.classList.toggle('search-squeezed',span<least); s.style.setProperty('--search-span',(span<least?span:Math.max(least,span))+'px');}
// The field's text on the row's ink reference (docs/handbook/viewer.md §글자 가운데): its neighbours' labels are trimmed to
// their cap height (text-box: trim-both cap alphabetic) and centred, which an <input> cannot be - trimming does not reach its
// text. So the field holds that reference itself: #search-ref-row is a trimmed line at the row labels' size and
// #search-ref-own one at the field's own size, both centred in the field as a label would be. --search-ink moves the input,
// as a transform, from where its line box puts its baseline (#search-probe: the input's line laid out as an element, its
// baseline marked):
// - text of the labels' size (a mouse: 12px): onto the baseline a trimmed label is painted on - its layout baseline rounded to
//   a whole pixel - by whole pixels, so field and labels are painted alike, pixel for pixel;
// - text of another size (touch: 16px beside 12px labels): to where its cap height's centre is the row line's, exactly, in
//   layout; painting snaps the text and the labels to device pixels each in its own way, so their inks agree within one
//   device pixel (a fraction of a pixel in a transform does not blur text: it is drawn on the device grid).
// Without text-box-trim there is no reference and the text stays on its line box. Measured with every fit of the field, when
// it is disclosed and when a font arrives.
function searchInk(){const q=$('#search-q'),row=$('#search-ref-row'),own=$('#search-ref-own'),p=$('#search-probe');
  if(!q.getClientRects().length||!row.getClientRects().length||!p.getClientRects().length)return;
  let ink=0;
  if(window.CSS&&CSS.supports('text-box-trim','trim-both')){const R=row.getBoundingClientRect(),O=own.getBoundingClientRect();
    const base=/** @type {Element} */(p.firstElementChild).getBoundingClientRect().bottom-p.getBoundingClientRect().top,stands=q.getBoundingClientRect().top-SEARCH.ink+base;
    ink=getComputedStyle(row).fontSize===getComputedStyle(own).fontSize?Math.round(R.bottom)-Math.round(stands)
      :Math.round(((R.top+R.bottom)/2+O.height/2-stands)*1000)/1000;}
  if(ink!==SEARCH.ink){SEARCH.ink=ink; q.style.setProperty('--search-ink',ink+'px');}}
// Whether the search is offered: not in the changes view (its PDF is a comparison, not the manuscript) and not while the PDF
// on screen cannot be read (PNG fallback, or not open yet). Hides the field and the navigation sheet's row otherwise, and a
// search that was open ends.
function searchOffer(){const off=document.body.classList.contains('revision-open')||!VEC.doc; if(off)searchClose(false);
  $('#doc-search').hidden=off; $('#ns-search').hidden=off; searchFit(); if(!off)searchRun();}
// Discloses the field (the dock on the phone, where an open sheet folds away for it; the opened box elsewhere) without
// moving the focus.
function searchShow(){if(SEARCH.open)return; SEARCH.open=true; document.body.classList.add('search-open'); $('#search-open').setAttribute('aria-expanded','true');
  if(BAND===LAYOUT_BAND.PHONE){SEARCH.side=SIDE_OPEN; if(SIDE_OPEN)setSide(false);}
  searchInk(); searchCover(); searchRows();}   // the box is laid out only now where it was folded
// Remembers what had the focus as the field is entered from outside it: element a, or nothing when that is the page, the
// magnifier (which leads here) or a control of a sheet that closes for the search. Moving inside the field changes nothing.
/** @param {Element|null} a */
function searchFrom(a){if(a&&$('#search-box').contains(a))return;
  SEARCH.back=a instanceof HTMLElement&&a!==document.body&&a!==$('#search-open')&&!a.closest('dialog')?a:null;}
// The shortcut, the magnifier and the navigation sheet's row: discloses the field and puts the focus in it with its text
// selected, remembering what had the focus. The short band hides its top row while a panel field is typed in (body.typing,
// layout.js): the row comes back for the field - the focus then leaves the panel field, so the class would go anyway. Returns
// false, the search left as it was, when the field does not take the focus: it is not offered (the changes view, no PDF), or
// its row is out of the layout for another reason - the shortcut is then the browser's, and the search is never left open
// without the focus in its field.
function searchOpen(){const s=$('#doc-search'),q=/** @type {HTMLInputElement} */($('#search-q')),was=SEARCH.open,from=document.activeElement; if(s.hidden)return false;
  searchShow(); if(!q.getClientRects().length&&BAND===LAYOUT_BAND.SHORT)document.body.classList.remove('typing');
  q.focus({preventScroll:true});
  if(document.activeElement!==q){if(!was)searchHide(); return false;}
  searchFrom(from);
  q.select(); return true;}
// Folds the disclosed field away; the phone's sheet comes back up if the search row had taken its place.
function searchHide(){if(!SEARCH.open)return; SEARCH.open=false; SEARCH.back=null; document.body.classList.remove('search-open'); $('#search-open').setAttribute('aria-expanded','false');
  if(SEARCH.side){SEARCH.side=false; if(BAND===LAYOUT_BAND.PHONE&&!SIDE_OPEN)setSide(true);}
  searchCover();}
// Whether element e is on screen to take the focus: in the document, laid out, and not hidden by visibility - a popover
// that is hidden that way keeps its boxes.
/** @param {HTMLElement} e */
function searchShown(e){return document.contains(e)&&e.getClientRects().length>0&&getComputedStyle(e).visibility!=='hidden';}
// Brings what the search was opened from back into view when it went out of it meanwhile: the note popover with its selection
// box (scrolled back to where [보기] puts a mark) or the composer's field in its panel.
/** @param {HTMLElement} to */
function searchBringBack(to){if($('#sel-pop').contains(to)&&SEL_POP_BOX){const b=SEL_POP_BOX.getBoundingClientRect(),a=selPopArea(),L=$('#left');
    if(b.top<a.top+8||b.bottom>a.bottom-8)L.scrollTop+=b.top-(a.top+(a.bottom-a.top)*0.3);
    if(b.left<a.left+8||b.right>a.right-8)L.scrollLeft+=(b.left+b.right)/2-(a.left+a.right)/2;
    placeSelPop();}
  else if($('#composer').contains(to))to.scrollIntoView({block:'nearest',inline:'nearest'});}
// Puts the focus on the PDF's scroller - where the keys then scroll - for as long as it stays there: it is not a tab stop and
// draws no ring (search.css).
function searchToPage(){const L=$('#left'); L.tabIndex=-1; L.addEventListener('blur',()=>L.removeAttribute('tabindex'),{once:true}); L.focus({preventScroll:true});}
// Esc, [검색 닫기] and leaving the manuscript: the query and its hits go and the field folds away. back moves the focus out
// of the closed field: to what had it before the field was entered if that is still on screen - the note popover or the
// composer is brought back into view for it - else to the PDF's scroller; with nothing remembered, to the control that leads
// to the search (the magnifier, the phone's position button) and without one to the PDF's scroller. The focus is never left
// in the closed field.
function searchClose(back){const s=$('#doc-search'),q=/** @type {HTMLInputElement} */($('#search-q')),had=s.contains(document.activeElement),to=SEARCH.back,was=SEARCH.open;
  q.value=''; searchRun(); if(!was)return; searchHide();   // (clearing disables the arrows: one that had the focus loses it there, and the field folds at once)
  if(!back||!had)return;
  if(to&&!searchShown(to)&&to.closest('#sel-pop,#composer'))searchBringBack(to);
  const next=to?(searchShown(to)?to:null):BAND===LAYOUT_BAND.PHONE?$('#btn-pos'):s.dataset.mode==='icon'?$('#search-open'):null;
  if(next)next.focus({preventScroll:true});
  if(!next||document.activeElement!==next)searchToPage();}   // a control that would not take the focus leaves it on the page, never in the field
// Another build is on screen (vecOpen): the query, its hits and the reading of the old text end; the field stays open while it
// has the focus, else it folds away with the bar whole again.
function searchClear(){/** @type {HTMLInputElement} */($('#search-q')).value=''; searchRun(); if(SEARCH.open&&!$('#doc-search').contains(document.activeElement))searchHide();}
// Another document is being opened (switchDoc, by any route): the search ends at once - query, hits and the open field, the
// bar whole again in this frame - and a focus that was in the field goes back as Esc gives it.
function searchLeave(){searchClose(true);}
$('#search-q').addEventListener('input',searchRun);
// An input method composing in the field (Hangul): its states between keys are searched as typed - but for a jamo standing
// alone (searchRun) - and none of them is announced; the result is announced once the composition ends.
$('#search-q').addEventListener('compositionstart',()=>{SEARCH.composing=true;});
$('#search-q').addEventListener('compositionend',()=>{SEARCH.composing=false; searchRun(); searchPaint();});
// Entering the field (a click or a Tab into it) discloses it and remembers what had the focus - not when the window comes
// back with the focus still in it. It folds away again when the focus leaves the search with nothing typed.
$('#search-box').addEventListener('focusin',e=>{if(SEARCH.away){SEARCH.away=false; return;}
  const from=/** @type {Element|null} */(e.relatedTarget); if(!(from&&$('#search-box').contains(from)))searchFrom(from);
  if(e.target===$('#search-q'))searchShow();});
$('#doc-search').addEventListener('focusout',e=>{const to=/** @type {Node|null} */(e.relatedTarget); if(to&&$('#doc-search').contains(to))return;
  if(!document.hasFocus()){SEARCH.away=$('#search-box').contains(/** @type {Node} */(e.target)); return;}   // the window lost the focus, not the field
  if(SEARCH.open&&!SEARCH.q)searchHide();});
// A press anywhere else folds an empty field away too: a tap on the page takes no focus, so on a touch screen the field would
// stay up (and its keyboard with it).
document.addEventListener('pointerdown',e=>{if(!SEARCH.open||SEARCH.q||$('#doc-search').contains(/** @type {Node} */(e.target)))return;
  const a=/** @type {HTMLElement|null} */(document.activeElement); searchHide(); if(a&&$('#doc-search').contains(a))a.blur();},true);
// Keys in the search: Enter is the next hit and Shift+Enter the previous (not while an input method composes); Esc ends the
// search. Neither reaches the viewer's own keys (events.js), so Esc here never cancels a selection or a draft - but with the
// search closed and empty (the focus on its magnifier) there is nothing to end, and Esc is the viewer's.
$('#doc-search').addEventListener('keydown',e=>{if(e.isComposing||e.keyCode===229)return;
  if(e.key==='Escape'){if(!SEARCH.open&&!SEARCH.q)return; e.preventDefault(); e.stopPropagation(); searchClose(true);}
  else if(e.key==='Enter'&&e.target===$('#search-q')){e.preventDefault(); e.stopPropagation(); searchGo(e.shiftKey?-1:1);}});
// The shortcut (searchKey): the field takes the focus instead of the browser's find, which finds nothing in a canvas. Pressed
// again in the field, under a sheet, or where the search is not offered, it is the browser's.
/** @param {KeyboardEvent} e */
function searchShortcut(e){if(!searchKey(e,IS_MAC))return;
  if(document.activeElement===$('#search-q')||document.querySelector('dialog[open]'))return;
  if(searchOpen())e.preventDefault();}
document.addEventListener('keydown',searchShortcut);
$('#search-hint').textContent=IS_MAC?'⌘F':'Ctrl F';
// The bar's room changes with its width and with its neighbours (the document links drawn, a page count growing, a font
// arriving), and the opened field's width with its count: fitted again on the next frame, never inside the observer.
if(window.ResizeObserver){const o=new ResizeObserver(()=>requestAnimationFrame(searchFit)); o.observe($('#doc-nav')); o.observe($('#search-box'));
  for(const k of $('#doc-nav').children)if(k.id!=='doc-search')o.observe(k);
  o.observe($('#status'));}   // the short band moves the status line into the bar (status.js); a new message changes its width
// ... or not: while the field holds the status to a max-width its box keeps that width whatever it says, so a new message is
// watched as it is drawn too.
new MutationObserver(()=>requestAnimationFrame(searchFit)).observe($('#status'),{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['hidden']});
document.fonts.addEventListener('loadingdone',searchFit);
