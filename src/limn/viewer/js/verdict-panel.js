// ------------------------------------------------ The page verdict panel beside the pages (docs/handbook/viewer.md §판정 패널, #329)
// On a wide desktop whose PDF area leaves room right of the pages, the page verdict line is one panel in that margin
// (#pv-panel, --pv-panel-w wide, --pv-panel-gap off the page) instead of a line under every page: the reading page's line
// (PV_READ, the page under the 160px reading line that the section strip and the keys name), drawn again (fillPv) when the
// reading page changes, its parts in rows down the panel (the name, the words, the state, the reason) - the words stand at
// one place on the screen for every page. Under each page a one-row summary (.pv-sum: '6쪽 · PL17 · 판정 #7 채택 · 처리
// 대기') says its verdict, the reading page's in bold, and a press brings that page to the panel. Every block (.pgw) is a
// grid [margin | page | margin] whose right margin holds the panel: the page stays centred while both margins hold it and
// moves left only by what the right one lacks. Where the room is short (a narrower window, the pin panel opened, a zoomed
// page) the lines go back under the pages as before, with hysteresis (PV_SIDE_ENTER, PV_SIDE_EXIT) so a width at the bar
// does not flip it. The wide band only: the foldable and phone bands never take it. The line's words, keys, focus, save
// chip and reason are the line's own (verdict.js, verdict-reason.js); this part decides when, places the panel and draws
// the summaries.

// The panel's room in px, as the CSS draws it (verdict-panel.css --pv-panel-w, --pv-panel-gap): the margin right of a page
// holds the panel and its gap, and the left margin keeps at least PV_SIDE_LEFT. The lines go beside the pages when the PDF
// area's inner width less the page's is PV_SIDE_ENTER or more, and back under them below PV_SIDE_EXIT; in between they
// stay as they are.
const PV_SIDE_W=280,PV_SIDE_GAP=24,PV_SIDE_LEFT=24,PV_SIDE_HYST=32;
const PV_SIDE_EXIT=PV_SIDE_W+PV_SIDE_GAP+PV_SIDE_LEFT,PV_SIDE_ENTER=PV_SIDE_EXIT+PV_SIDE_HYST;
let PV_SIDE=false;   // the lines stand beside the pages now: one panel, a summary under each page
// The room the PDF area leaves beside the pages: its inner width less the widest page's width at the scale on screen - below 0
// for a page wider than the area - or null while the area is not drawn (the changes view): the lines then stay as they are.
// One width for the whole document, so the reading page never decides it and scrolling never turns the panel on or off. The
// widest, not the most common: a wider page's block took the panel's margin past the area, the column grew with it, and every
// page moved right under the panel. With it every page stands beside the panel, on one axis (verdict-panel.css).
/** @returns {number|null} */
function pvSideRoom(){const L=$('#left'); if(!META||!Array.isArray(META.pages)||!META.pages.length||!L.getClientRects().length)return null;
  return innerW()-pageWidth(ptMax(),K);}
// Whether the lines should stand beside the pages: the wide band, a document with page lines, and the room - with
// hysteresis around the bar.
function pvSideWant(){if(LAYOUT!==LAYOUT_MODE.WIDE||!pageVerdictsOn())return false;
  const r=pvSideRoom(); if(r===null)return PV_SIDE; return PV_SIDE?r>=PV_SIDE_EXIT:r>=PV_SIDE_ENTER;}
// Sets PV_SIDE and the body's class for it (body.pv-beside). No drawing.
/** @param {boolean} on */
function pvSideApply(on){PV_SIDE=on; document.body.classList.toggle('pv-beside',on);}
// Whether the room crossed its bar since the lines were drawn (pvStick: a resize, the pin panel, a zoom, the frame after it): they
// are drawn again, beside or under the pages. Whether it did.
function pvSideCheck(){if(pvSideWant()===PV_SIDE)return false; drawPageVerdicts(); return true;}
// The reading page held while the lines move (pvSideTurn to pvSideSettle), 0 otherwise: read from the layout between the two it
// was another page - the blocks change their height, by 4px a page, and only the settling puts the spot back - and a reason
// being typed moved on: its half text was written and the digits after it were verdict keys. A var: pvReadingAt reads it.
var PV_AT_HELD=0;
// Before the lines are drawn (drawPageVerdicts): follows the room. When it crossed its bar every line goes and new ones come, so
// what the person has must be carried over: the reading page, the point of it under the reading line, and the focus. Null
// when the lines stay where they are. A composition cannot cross: its field goes, and with it its end.
function pvSideTurn(){const on=pvSideWant(); if(on===PV_SIDE)return null;
  const L=$('#left'),a=/** @type {HTMLElement|null} */(document.activeElement),f=pvIsReasonField(a)?/** @type {HTMLTextAreaElement} */(a):null,at=pvReadingAt();
  const keep={spot:L.scrollTop>0?topAnchor(readingDepth(L)):null,inLine:!!a&&!!a.closest&&!!a.closest('#doc .pv'),caret:f?[f.selectionStart,f.selectionEnd]:null,
    popAct:!!a&&!!a.closest&&!!a.closest('#doc .pv-pop')&&!f&&a.dataset.act||''};
  if(f)PV_COMPOSING=false; PV_AT_HELD=at; pvSideApply(on); return keep;}
// The lines have moved and are fitted: the point that was under the reading line is there again, so the page in view does not
// shift and the reading page is the one held (a rounded scroll position may fall a pixel off a page's edge: taken back).
/** @param {NonNullable<ReturnType<typeof pvSideTurn>>} k */
function pvSideSettle(k){PV_AT_HELD=0; const a=k.spot,pg=a?document.getElementById('p'+a.page):null; if(!a||!pg)return;
  const L=$('#left'),y=()=>L.getBoundingClientRect().top+readingDepth(L),r=pg.getBoundingClientRect(); L.scrollTop+=r.top+a.frac*r.height-y();
  const b=pg.getBoundingClientRect(); if(b.bottom<=y())L.scrollTop-=2; else if(b.top>y())L.scrollTop+=2;}
// After the lines moved: a save chip stands on its pin's new line (drawChips, else its undo goes to the status line), and the reason
// field that had the focus has it again with its caret, or the popover's button its focus - what is typed next stays text,
// never a verdict key. A focus on another page's line, which the panel does not show, goes to the PDF area, not to nothing.
/** @param {NonNullable<ReturnType<typeof pvSideTurn>>} k */
function pvSideTurned(k){drawChips(); const g=k.caret?pvReasonField():null;
  if(g&&k.caret){g.focus({preventScroll:true}); g.setSelectionRange(k.caret[0],k.caret[1]); return;}
  const b=/** @type {HTMLElement|null} */(k.popAct?document.querySelector('#doc .pv-pop [data-act="'+k.popAct+'"]'):null); if(b){b.focus({preventScroll:true}); return;}
  const a=document.activeElement; if(k.inLine&&(!a||a===document.body))searchToPage();}

// ---------------- The panel
// The panel (#pv-panel): a page verdict line of its own, in the last child of the pages' column (#pv-panel-at) - so every
// '#doc .pv[data-page]' look-up of the reading page's line finds it, the DOM's Tab from its last control leaves the pages (to
// the pin panel), and a rebuild of the column (buildDoc) takes it away with the pages. #pv-panel-at has no height and is
// sticky to the PDF area's top, so the panel stays in view while it stays in the area's scroll chain: PageDown, the arrows,
// Home and End on one of its controls and a wheel over it move the pages, by the browser's own steps, as on a line under a
// page. Fixed to the window it was out of that chain: after a key save the keys and the wheel moved nothing, and the next
// digit changed the same page's verdict.
function pvPanel(){let p=/** @type {HTMLElement|null} */(document.getElementById('pv-panel'));
  if(!p){const at=document.createElement('div'); at.id='pv-panel-at'; p=document.createElement('div'); p.id='pv-panel'; p.className='pv pv-panel pv-stack';
    at.appendChild(p); $('#doc').appendChild(at); if(PV_CHIP_WATCH)PV_CHIP_WATCH.observe(p,{childList:true});}
  return p;}
function pvPanelGone(){const at=document.getElementById('pv-panel-at'); if(at)at.remove();}
// Fills the panel with the reading page's line (PV_READ). A page that takes no verdict (a list page, a comparison board)
// names itself in one form whatever its title looks like - the page ('2쪽') on the name's row and the map's whole title, if
// it has one, on the title's row (pvQuietTitle) - and says it takes none, without words. The verdict pages' split of a title
// at its first ' · ' (pvFigParts) put a board's '비교판' beside its page and left a list page's title out. A save chip on the
// panel for a pin of another page goes to the status line with its undo (chipAway), as a chip whose mark is not drawn does:
// the panel no longer shows the verdict it undoes.
/** @param {Map<number,Pin[]>} map @param {DocVerdicts} v */
function pvPanelFill(map,v){const p=pvPanel(),r=PV_READ,at=pvReadingAt(),list=r?map.get(r)||[]:[]; pvPanelLeave(p,at);
  const chip=/** @type {HTMLElement|null} */(p.querySelector(':scope>.nt-chip')); if(chip&&!list.some(x=>x.id===pvChipPin(chip)))chipAway(chip);
  if(r){p.classList.remove('pv-quiet'); fillPv(p,r,map.get(r),v); pvPanelPlace(); pvPanelArrived(r); return;}
  PV_TEXT.delete(p); p.classList.add('pv-quiet'); p.classList.remove('reading'); p.dataset.page=String(at||0); delete p.dataset.pin;
  p.setAttribute('role','group'); p.setAttribute('aria-label',at?tl('{page}쪽 판정',{page:at}):tr('판정'));
  const t=at?pvQuietTitle(at):'';
  setHtml(p,html`<span class="pv-fig" translate="no"><span class="pv-fig-id">${at?tl('{page}쪽',{page:at}):''}</span>${t?html`<span class="pv-fig-t">${t}</span>`:''}</span>\
<span class="pv-t"><span class="pv-s pv-none">${tr('이 쪽은 판정을 받지 않습니다')}</span></span>`);
  pvPanelPlace(); pvPanelArrived(at);}
// The title the map gives page `page` of a figure document, whole ('' for none, or for a view-only PDF, which has no map).
/** @param {number} page @returns {string} */
function pvQuietTitle(page){const pg=META&&isFigureKind(META.kind)&&Array.isArray(META.pages)?META.pages[page-1]:null; return pg&&pg.title?String(pg.title):'';}
// Whether the panel shows another page than the one under the reading line (at, verdict or none). Under the pages: never.
/** @param {number} at */
function pvPanelStale(at){const p=document.getElementById('pv-panel'); return PV_SIDE&&!!p&&p.dataset.page!==String(at);}
// The panel is about to show another page than p's: what the person has on it stays with the page they left. An open reason is
// moved on from as the reading page leaves it (pvReasonLeave), and a focus on a control goes to the PDF area, as one on a left
// line's does (pvFocusOffPage). This must come before the filling: the morph keeps the element and hands it to the new
// page, so Enter or Space on '채택' pressed the next page's word, and a control that goes left the focus on nothing.
/** @param {HTMLElement} p @param {number} at */
function pvPanelLeave(p,at){if(p.dataset.page===String(at))return; if(PV_REASON&&PV_REASON.seen&&PV_REASON.page!==at)pvReasonLeave();
  const a=document.activeElement; if(!!a&&p.contains(a))searchToPage();}
// The pin save chip e is for (its notice's), 0 for none.
/** @param {HTMLElement} e @returns {number} */
function pvChipPin(e){let pin=0; NOTICES.forEach(n=>{if(n.el===e)pin=n.pin||0;}); return pin;}
// The panel's place: --pv-panel-gap right of the widest page on the reading page's axis (page 1 before there is one) - one
// place for pages of every width - its top at the PDF area's top
// padding, where #pv-panel-at sticks: it stands at the column's end, and the inset from the bottom of what a sticky box may
// use (the area less its padding) to that top pulls it up, so its height stays nothing. Taller than the area shows (a short
// window, a long conflict note in the popover) the panel scrolls inside (.pv-tall). Only then: a scroller clips what stands
// outside it, the pressed word's context under the panel, and that context's box would bring a scroll bar with it. Once a
// frame with pvStick.
function pvPanelPlace(){const p=document.getElementById('pv-panel'),at=document.getElementById('pv-panel-at'); if(!p||!at||!PV_SIDE)return; const L=$('#left'),lr=L.getBoundingClientRect(),cs=getComputedStyle(L);
  const n=Number(p.dataset.page)||pvReadingAt()||1,pg=document.getElementById('p'+n)||document.getElementById('p1'); if(!pg)return;
  const pt=parseFloat(cs.paddingTop),inset=Math.max(0,L.clientHeight-pt-parseFloat(cs.paddingBottom))+'px'; if(at.style.bottom!==inset)at.style.bottom=inset;
  const g=pg.getBoundingClientRect(),right=g.left+(g.width+pageWidth(ptMax(),K))/2;
  const x=Math.round(Math.min(right+PV_SIDE_GAP,lr.left+L.clientWidth-PV_SIDE_W)-at.getBoundingClientRect().left)+'px'; if(p.style.left!==x)p.style.left=x;
  const room=Math.max(0,Math.floor(L.clientHeight-pt-PV_SIDE_GAP)),was=p.classList.contains('pv-tall'),tall=(was?p.scrollHeight+2:p.offsetHeight)>room,h=tall?room+'px':'';
  if(tall!==was)p.classList.toggle('pv-tall',tall); if(p.style.maxHeight!==h)p.style.maxHeight=h;}
// The panel's line is laid out in rows (.pv-stack: the name, the words, the state, the reason) and never measured for one row:
// there is room for each part's whole width, so nothing gives way. Its save chip and the reason popover stand in its flow
// under the state (verdict-panel.css): the words above never move.
/** @param {HTMLElement} l */
function pvPanelFit(l){l.classList.remove('pv-tight','pv-early-out','pv-t-kept','pv-chip-short','pv-chip-bare','pv-chip-wait','pv-kw'); l.classList.add('pv-stack');
  l.style.removeProperty('--pv-t-h'); l.style.removeProperty('--pv-chip-r'); l.style.removeProperty('--pv-chip-y'); l.style.width=''; l.style.marginLeft='';
  const g=l.querySelector(':scope>.vd-btns'); if(g)vdWrapFit(g); pvFocusStays([l]);}
// Brings page `page` to the reading place: its top at the PDF area's top padding when the page reaches past the reading line
// (readingDepth), else centred on that line - so the reading page is that page. smooth: a glide (a card's [보기]).
/** @param {number} page @param {boolean} [smooth] */
function pvBring(page,smooth){const L=$('#left'),pg=document.getElementById('p'+page); if(!pg)return;
  const lr=L.getBoundingClientRect(),r=pg.getBoundingClientRect(),pad=parseFloat(getComputedStyle(L).paddingTop),d=readingDepth(L);
  const top=r.height>d-pad+24?pad:d-r.height/2,by=r.top-lr.top-top;
  if(smooth)pvGlideTo(L.scrollTop+by); else L.scrollTop+=by;}

// ---------------- The summary under each page
// The summary's words: what its row says, for its name.
/** @param {number} page @param {Pin[]|undefined} list */
function pvSumSay(page,list){const cur=list&&list[0],k=cur&&verdictOf(cur);
  return pvFigParts(page).id+' · '+(cur&&k?tr('판정')+' #'+cur.id+' '+verdictLabel(k)+' · '+pvStateWord(cur):tr('판정 없음'));}
// '6쪽 · PL17 · 판정 #7 채택 · 처리 대기' (or '판정 없음') under every page that takes a verdict, and '초안 있음' where a reason
// draft waits for that page - a line would mark it, and the panel shows only the reading page: one row of one height whatever
// it says, so neither a verdict changing it nor the reading page changing moves the pages. A press brings that page to the
// panel (pvSumGo). Not a Tab stop - the keyboard has the panel, and PageDown brings the next page to it.
/** @param {number} page @param {Pin[]|undefined} list */
function pvSumHtml(page,list){const cur=list&&list[0],k=cur&&verdictOf(cur),sep=html`<span class="pv-sep" aria-hidden="true">·</span>`;
  const st=cur&&k?html`${tr('판정')} #${cur.id} <b class="vd-w" translate="no">${verdictLabel(k)}</b>${sep}${pvStateWord(cur)}`:html`<span class="pv-none">${tr('판정 없음')}</span>`;
  const d=cur&&pvCanCancel(cur)?rdGet(DOC,cur.id):null,draft=!!rdGet(DOC,'p'+page)||(!!d&&!!cur&&d.text.trim()!==String(cur.note||'').trim());
  return html`<span class="pv-sum-id" translate="no">${pvFigParts(page).id}</span>${sep}<span class="pv-sum-s">${st}${draft?html`${sep}<span class="pv-sum-draft">${tr('초안 있음')}</span>`:''}</span>`;}
// Draws (beside the pages) or takes away (under them) every page's summary, after its page. New rows are watched for being
// far from the view (pvFarWatch: a far row is skipped like a far line).
/** @param {Map<number,Pin[]>} map */
function pvSums(map){const made=/** @type {HTMLElement[]} */([]);
  $$('#doc .pgw').forEach(b=>{const page=Number(/** @type {HTMLElement} */(b).dataset.page)||0; let s=/** @type {HTMLElement|null} */(b.querySelector(':scope>.pv-sum'));
    if(!PV_SIDE||!pageTakesVerdict(page)){if(s)s.remove(); return;}
    if(!s){s=document.createElement('button'); s.setAttribute('type','button'); s.className='pv-sum'; s.tabIndex=-1; s.dataset.act='pv-sum'; s.dataset.page=String(page); b.appendChild(s); made.push(s);}
    const m=pvSumHtml(page,map.get(page)); if(s.dataset.t!==m.text){s.dataset.t=m.text; setHtml(s,m);}
    const say=tl('{state} · 판정 패널로',{state:pvSumSay(page,map.get(page))}); s.setAttribute('aria-label',say); s.dataset.tipPress=say;});
  if(made.length&&typeof IntersectionObserver!=='undefined')pvFarWatch(made,$('#left').clientHeight);
  pvSumOn();}
// The reading page's summary is bold (.on): the page the panel shows - a weight, never a height.
function pvSumOn(){const r=String(PV_SIDE?PV_READ||0:0);
  $$('#doc .pv-sum.on').forEach(e=>{if(/** @type {HTMLElement} */(e).dataset.page!==r)e.classList.remove('on');});
  const s=document.querySelector('#doc .pv-sum[data-page="'+r+'"]'); if(s)s.classList.add('on');}
// A press on page `page`'s summary: the page comes to the reading place, the panel shows it at once, and the focus goes to the
// panel's pressed word, else its first (pvFocusLine); the panel flashes.
/** @param {HTMLElement} a */
function pvSumGo(a){const page=Number(a.dataset.page)||0; if(!document.getElementById('p'+page))return;
  pvCame(a); pvBring(page); pvStick(); const p=document.getElementById('pv-panel'); if(!p||p.dataset.page!==String(page))return;
  pvFocusLine(page); pvFlash(p);}
// ---------------- A jump's glide
// A jump to a far page (the outline, the page list, a card's [보기]) glides past every page between, and the digits and Enter
// wait meanwhile (pvAutoScrolling). The panel keeps the page it shows and is filled once, where the jump lands: filled for
// every page passed it changed 57 times in 1.3s. The reading page it shows (PV_READ), the bold summary, an open reason and
// the keys' page wait with it; the section strip names the pages passed as ever. pvStick asks: the page held, or 0 when
// nothing is (under the pages, at rest, a panel that names no page). The glide's end - its scrollend, else the guard's own
// end - draws the panel again, so at rest the panel, the section strip and the keys name one page.
let PV_HOLD_T=/** @type {ReturnType<typeof setTimeout>|undefined} */(undefined);
function pvPanelHeld(){if(!PV_SIDE||!pvAutoScrolling())return 0; const p=document.getElementById('pv-panel'),n=p?Number(p.dataset.page)||0:0; if(!n)return 0;
  clearTimeout(PV_HOLD_T); PV_HOLD_T=setTimeout(pvStickSoon,Math.min(1000,Math.max(0,(PV_SCROLLEND?1000:160)-(performance.now()-PV_SCROLL_AT))+16)); return n;}
$('#left').addEventListener('scrollend',()=>{if(PV_SIDE)pvStickSoon();});   // after verdict.js's, which ends the guard
// The panel flashes (a card's [보기], a summary's press) once it shows page `page`: at once when it does, else when a glide lands
// and fills it (pvPanelArrived) - flashed as the glide began, it lit the page being left and was over before the landing.
let PV_FLASH_AT=0;
/** @param {number} page */
function pvFlashOn(page){const p=document.getElementById('pv-panel'); if(p&&p.dataset.page===String(page)){PV_FLASH_AT=0; pvFlash(p); return;} PV_FLASH_AT=page;}
// The panel was filled with page `page` (pvPanelFill): the first filling at rest after a flash was asked for ends the wait, and
// flashes if it is that page (a hand that took the pages elsewhere lands on another).
/** @param {number} page */
function pvPanelArrived(page){if(!PV_FLASH_AT||pvAutoScrolling())return; const go=PV_FLASH_AT===page; PV_FLASH_AT=0; const p=document.getElementById('pv-panel'); if(go&&p)pvFlash(p);}
/** @param {HTMLElement} p */
function pvFlash(p){p.classList.remove('flash'); void p.offsetWidth; p.classList.add('flash'); clearTimeout(p._flT); p._flT=setTimeout(()=>p.classList.remove('flash'),1200);}
// ---------------- Keys the panel needs of its own
// The panel stands after the pages in the DOM, so what stands on the reading page comes by hand. Its Tab stops: its marks.
/** @param {number} page @returns {HTMLElement[]} */
function pvMarkStops(page){const b=document.querySelector('#doc .pgw[data-page="'+page+'"]'); return b?/** @type {HTMLElement[]} */([...b.querySelectorAll(PV_TABBABLE)].filter(pvTabStop)):[];}
// Tab from the reading page's last mark, or from a summary a person went back to, goes to the panel: the DOM's next stop is a later
// page's mark, whose focus scrolled the pages there.
addEventListener('keydown',e=>{if(e.key!=='Tab'||e.shiftKey||e.ctrlKey||e.metaKey||e.altKey||e.defaultPrevented||!PV_SIDE)return;
  const a=/** @type {HTMLElement|null} */(document.activeElement),r=pvReadingPage(),m=r?pvMarkStops(r):[]; if(!a||!(a===m[m.length-1]||a.classList.contains('pv-sum')))return;
  const f=/** @type {HTMLElement|undefined} */([...pvPanel().querySelectorAll(PV_TABBABLE)].find(pvTabStop)); if(f){e.preventDefault(); f.focus({preventScroll:true});}});
// Esc on a control of the panel hands the focus to the PDF area: from there the page keys and Tab work as anywhere on the pages.
// A confirm word's Esc lets it go first, and the reason popover's Esc is its own.
addEventListener('keydown',e=>{if(e.key!=='Escape'||e.defaultPrevented||!PV_SIDE)return; const a=document.activeElement;
  if(!a||!a.closest||!a.closest('#pv-panel')||a.closest('.pv-pop'))return; e.preventDefault(); searchToPage();});
// A tall panel (.pv-tall) scrolls inside. A control the keyboard focuses there comes whole into its view, focus ring and all:
// the reason popover's Tab loop focuses without scrolling (verdict-reason.js), so its first word and last control stayed out of
// sight; the browser's own Tab scrolls only the control's edge to the panel's, which cut the ring; and the popover's rows
// change as the focus moves (the field's keys row), after the browser scrolled. A press is left where it is: it is in view.
function pvPanelReveal(){const p=document.getElementById('pv-panel'),a=document.activeElement;
  if(!p||!PV_SIDE||!p.classList.contains('pv-tall')||!(a instanceof HTMLElement)||!p.contains(a)||!a.matches(':focus-visible'))return;
  const c=getComputedStyle(a),m=(parseFloat(c.outlineWidth)||0)+Math.max(0,parseFloat(c.outlineOffset)||0)+PV_RING_ROOM,b=p.getBoundingClientRect(),r=a.getBoundingClientRect();
  const top=b.top+p.clientTop,bottom=top+p.clientHeight;
  if(r.top-m<top||r.height+2*m>p.clientHeight)p.scrollTop-=top-(r.top-m); else if(r.bottom+m>bottom)p.scrollTop+=r.bottom+m-bottom;}
const PV_RING_ROOM=2;   // px kept clear past a revealed control's focus ring
$('#doc').addEventListener('focusin',e=>{const t=/** @type {HTMLElement|null} */(e.target); if(t&&t.closest&&t.closest('#pv-panel.pv-tall'))requestAnimationFrame(pvPanelReveal);});
// The PDF area's width changes with no window resize (the outline folded or dragged): the room is read again.
if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>{if(LAYOUT===LAYOUT_MODE.WIDE&&pageVerdictsOn())pvStickSoon();}).observe($('#left'));
