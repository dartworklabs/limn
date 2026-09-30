// ------------------------------------------------ Figure documents: the element a pick chose, its box and path
// A figure document's pick answers the element under the drag and the ladder of its ancestors; every rung carries its
// element (levels[].el with id, path root first, label, part, impl and its box `frac` on the pick's page). The composer
// shows that element without another request (docs/handbook/viewer.md §패널 정리): the pending box snaps to it - the mark
// the pin will get - and the location line names its path. The selection keeps the element it shows as elSel.

// Whether f is a page box [x, y, w, h] of four finite numbers - the shape of a pin's frac and an element's frac.
function isFrac(f){return Array.isArray(f)&&f.length===4&&f.every(v=>typeof v==='number'&&Number.isFinite(v));}
// A person's name for an element: its label, else its part, else its id - the rule the pick answer's rung labels follow.
function elName(el){return String((el&&(el.label||el.part||el.id))||'');}
// The selected element's path, root first, as the location line shows it ('B2 › 달력 › 7월'). Each id is named by the
// rung that carries it, else by the pick's own element, else by the id itself: an ancestor merged into an inner rung,
// past the ladder's cap or drawn in another file has no rung, and its id still says where it is.
function elPathText(o){const el=o&&o.elSel; if(!el||!Array.isArray(el.path))return '';
  const names=new Map(); if(o.el&&o.el.id)names.set(o.el.id,elName(o.el));
  (o.levels||[]).forEach(lv=>{if(lv.el&&lv.el.id)names.set(lv.el.id,String(lv.label||elName(lv.el)));});
  return el.path.map(id=>names.get(id)||String(id)).join(' › ');}
// A figure rung's tooltip text: the whole figure's lines for the page's root (its path is itself), else the element's.
function rungTip(lv){return Array.isArray(lv.el.path)&&lv.el.path.length<=1?T.fig:T.el;}
// Puts a pending box (the composer's '새 핀', a re-place's '새 위치') on the element it will pin, so the person sees the
// mark before saving. An element without a usable box, or no box on screen, leaves the box as dragged.
function snapBox(box,el){if(!box||!el||!isFrac(el.frac))return; const f=el.frac; drawBox(box,f[0],f[1],f[0]+f[2],f[1]+f[3]);}
// The element part of the composer for selection o and its pending box: the path line '#c-path' (hidden when the pick
// found no element - a manuscript, a view-only PDF, a figure whose map is unreadable) and the snapped box.
function renderElement(o,box){const line=$('#c-path'),el=o.elSel; line.hidden=!el;
  if(el){line.textContent=elPathText(o)+' ·'; line.dataset.tip=tl('요소 {id}',{id:el.id});}
  snapBox(box,el);}
// The page badge of a region on a figure document (composer and card): '코드 없는 요소' when the map chose an element
// it has no code lines for, '영역' when the map could not be read; null off figure documents without an element - the
// caller keeps its view-only wording.
function figRegionBadge(el,figure){return el?{t:tr('코드 없는 요소'),tip:tr(T.elregion)}:figure?{t:tr('영역'),tip:tr(T.figregion)}:null;}
// The `el` a pin stores (POST /api/pin, an edit's loc): the pick's element with only the fields the pin record defines, in
// its order - id, path, label, part, impl and the element's box `frac` on the build it was picked on, which the server's
// read-time follow compares with the current build. A box that is not four finite numbers is left out.
function elForSave(el){const out={id:el.id,path:Array.isArray(el.path)?el.path.slice():[]};
  for(const k of ['label','part'])if(typeof el[k]==='string')out[k]=el[k];
  if(el.impl&&typeof el.impl==='object')out.impl={file:el.impl.file,lo:el.impl.lo,hi:el.impl.hi};
  if(isFrac(el.frac))out.frac=el.frac.slice();
  return out;}
// The range kind of an element rung as the server names it (limn.builds.figure_map.element_kind): 'figure' for the page's
// root (its path is itself), else 'el:<part>' with the part cut to 77 characters (a kind stays within 80), 'el:?' without a
// part. src/limn/viewer/tests/test_viewer.py runs both on the same elements.
function elKind(el){return Array.isArray(el.path)&&el.path.length<=1?'figure':'el:'+String(el.part||'?').slice(0,77);}
// Adds a figure pick's fields to a pin body or a re-place loc and returns it: `el`, the element's box as the pin's own
// `frac` too (a mark drawn without the current map then sits where the person saw the snapped box), and the element's
// kind when the range is that element's rung (rung given). A pick without an element is left as it is; lines nudged by
// hand keep the kind the body already has.
function figureFields(body,el,rung){if(!el)return body; body.el=elForSave(el); if(isFrac(el.frac))body.frac=el.frac.slice();
  if(rung&&rung.el)body.kind=elKind(el); return body;}
// The rung the selection's scope names when it is a figure rung (it carries an element), else null.
function figRung(o){const lv=o&&o.scope&&lvOf(o,o.scope); return lv&&lv.el?lv:null;}
// The element a re-place candidate would move the pin to: its default rung's, else the answer's own (a region answer).
function repickEl(c){const lv=lvOf(c,c.default_level); return (lv&&lv.el)||c.el||null;}
// Whether the server found this figure pin's element in the current build: the read-time `mark` box on `mark_page`.
function hasMark(p){return isFrac(p.mark)&&Number.isInteger(p.mark_page)&&p.mark_page>=1;}
// Where a pin's mark goes (docs/handbook/viewer.md §상태 표현): its element's box in the current build when the server found
// it, else the page and box the pin was placed on - a manuscript pin, a view-only pin, a figure pin whose element was
// lost or whose map is unreadable. The box can be null (a stored box that is not finite reads null as a whole): the caller
// draws nothing for it.
function pinPlace(p){return hasMark(p)?{page:p.mark_page,frac:p.mark}:{page:p.page,frac:p.frac};}
// Whether a figure pin's element is gone from the current build's map (`el_sync` lost) - shown like a lost line.
function elLost(p){return !!p&&p.el_sync===EL_SYNC.LOST;}
// The card badge of a lost element ('요소 잃음', the warning look of '위치 잃음'), or ''.
function elLostTag(p){return elLost(p)?'<span class="badge badge-warning" data-tip="'+esc(tr(T.ellost))+'">'+ic('triangle-alert')+esc(tr('요소 잃음'))+'</span>':'';}
