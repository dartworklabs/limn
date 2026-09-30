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
