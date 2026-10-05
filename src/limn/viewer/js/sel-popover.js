// ------------------------------------------------ The note popover by the selection box (docs/handbook/viewer.md §패널 정리 '선택 상자 곁 메모', #192)
// With a mouse on the desktop and mid layouts, a drag that ends opens a small popover under the dashed box: the location, a note
// field, [자세히 →] and [저장], so the note can be written where the eye already is. The field is the composer's note - one
// value, edited from either place - and [저장] and Ctrl/⌘+Enter take savePin(), the composer's own path, so the saved chip
// with its undo and every rule of §알림 자리 hold unchanged. [자세히 →] hands over to the composer in the panel, which keeps
// the kind, the range and the overlap. Esc and a short click off the box cancel the selection as before; a press on the
// popover is a press inside the box (pressOutsideSelection). Touch and the phone keep the composer alone (it is a sheet).
const SEL_POP=$('#sel-pop'),SEL_POP_FIELD=/** @type {HTMLTextAreaElement} */(SEL_POP.querySelector('textarea')),SEL_POP_GAP=8;
// The box the popover belongs to; null while it is closed.
let SEL_POP_BOX=/** @type {HTMLElement|null} */(null);
// Where a w x h popover goes for a box in the free area (rectangles {left, top, right, bottom}), gap px from the box and from
// the area's edges: below the box with its left edge, above it when below has no room, at the area's foot when neither side
// has room; moved left to stay inside the area's right edge, never past its left. Not shown when the box is outside the area
// (scrolled away). Whole pixels, so its text is drawn crisp. Pure.
/** @param {{left:number,top:number,right:number,bottom:number}} box @param {{left:number,top:number,right:number,bottom:number}} area
 * @param {number} w @param {number} h @param {number} gap @returns {{left:number,top:number,side:string,shown:boolean}} */
function popPlace(box,area,w,h,gap){
  const below=box.bottom+gap+h<=area.bottom-gap,above=box.top-gap-h>=area.top+gap;
  const top=below||!above?Math.max(area.top+gap,Math.min(box.bottom+gap,area.bottom-gap-h)):box.top-gap-h;
  const left=Math.max(area.left+gap,Math.min(box.left,area.right-gap-w));
  return {left:Math.round(left),top:Math.round(top),side:below||!above?'below':'above',shown:box.bottom>area.top&&box.top<area.bottom};}
// The part of the PDF area nothing covers (the select mode's frame, #sel-mode: under the section strip, above a sheet, left of an
// overlay panel and its handle), inside #left's scrollbar and under the select mode's bar while it shows.
function selPopArea(){const L=$('#left'),l=L.getBoundingClientRect(),m=$('#sel-mode').getBoundingClientRect(),bar=$('#sel-bar');
  const a={left:Math.max(l.left,m.left),top:Math.max(l.top,m.top),right:Math.min(l.left+L.clientLeft+L.clientWidth,m.right),
    bottom:Math.min(l.top+L.clientTop+L.clientHeight,m.bottom)};
  if(bar.getClientRects().length)a.top=Math.max(a.top,bar.getBoundingClientRect().bottom);
  return a;}
// Whether this selection gets the popover: a mouse drag outside the phone layout, not a re-place.
function selPopWanted(){return LAYOUT!==LAYOUT_MODE.NARROW&&LAST_PTR==='mouse'&&!REPICK;}
// Opens the popover for the box a mouse drag just drew (finishRect): the field takes the composer's note and the focus.
/** @param {HTMLElement} box */
function openSelPop(box){if(!selPopWanted())return; SEL_POP_BOX=box; SEL_POP_FIELD.value=$('#note').value;
  drawSelPop(); if(!SEL_POP.hidden)SEL_POP_FIELD.focus({preventScroll:true});}
function closeSelPop(){SEL_POP_BOX=null; SEL_POP.hidden=true;}
function selPopOpen(){return !SEL_POP.hidden;}
// Draws the popover from the selection: the location (or '찾는 중' while the pick runs), the note's placeholder, its place. It
// closes when its box is no longer the selection's, the composer closed, the pick failed or the layout became the phone's.
function drawSelPop(){const d=COMPOSE.current;
  if(!SEL_POP_BOX||COMPOSE.box!==SEL_POP_BOX||!document.contains(SEL_POP_BOX)||$('#composer').hidden||(!d&&!COMPOSE.picking)||!selPopWanted()){closeSelPop(); return;}
  const loc=SEL_POP.querySelector('.sp-loc');
  loc.textContent=!d?tr('찾는 중'):isRegion(d)?tl('쪽 {page} 영역',{page:d.page}):d.name+' '+rng(/** @type {number} */(d.lo),/** @type {number} */(d.hi));
  SEL_POP_FIELD.placeholder=$('#note').placeholder; SEL_POP.hidden=false; placeSelPop();}
// Puts the popover by its box in the free area (popPlace); hidden while the box is scrolled out of it.
function placeSelPop(){if(SEL_POP.hidden||!SEL_POP_BOX)return; if(!selPopWanted()){closeSelPop(); return;}
  const p=popPlace(SEL_POP_BOX.getBoundingClientRect(),selPopArea(),SEL_POP.offsetWidth,SEL_POP.offsetHeight,SEL_POP_GAP);
  SEL_POP.style.left=p.left+'px'; SEL_POP.style.top=p.top+'px'; SEL_POP.dataset.side=p.side; SEL_POP.style.visibility=p.shown?'':'hidden';}
// One note: what is typed here is the composer's note (its @-tag preview, assignee row, question hint and draft follow), and
// what is typed in the composer shows here.
SEL_POP_FIELD.addEventListener('input',()=>{const n=/** @type {HTMLTextAreaElement} */($('#note')); n.value=SEL_POP_FIELD.value; autoGrow(n);
  mentionPreview(n); renderAssignNew(); qHint($('#c-qhint'),n.value,KIND_NEW); saveDraftSoon();});
$('#note').addEventListener('input',()=>{const v=/** @type {HTMLTextAreaElement} */($('#note')).value; if(selPopOpen()&&SEL_POP_FIELD.value!==v)SEL_POP_FIELD.value=v;});
SEL_POP_FIELD.addEventListener('focus',()=>{SEL_POP_FIELD.value=/** @type {HTMLTextAreaElement} */($('#note')).value;});
// [자세히 →]: the composer in the panel takes over with the focus in its note; the popover does not come back for this selection.
function selPopMore(){closeSelPop(); setSide(true); applySide(); $('#note').focus();}
$('#left').addEventListener('scroll',placeSelPop,{passive:true});
addEventListener('resize',placeSelPop);
new ResizeObserver(placeSelPop).observe($('#doc'));   // a zoom moves the box with its page
