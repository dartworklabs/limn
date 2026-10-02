// ------------------------------------------------ Range excerpt (docs/handbook/viewer.md §패널 정리 범위 발췌)
// On the compact bands the source under the range ladder is the range control itself: the selected lines in a tinted band
// with one dimmed line above and below. A tap on a dimmed line widens the range to it; the '−' on the band's first or last
// line drops that line. The owner read the stepper '위 + − 아래 + −' as moving the pin. The composer and the edit card draw
// the same excerpt; the mouse desktop keeps the stepper and the plain source.

// The range lo..hi widened to line k: [min(lo,k), max(hi,k)]. Pure.
function widenTo(lo,hi,k){return [Math.min(lo,k),Math.max(hi,k)];}
// The range lo..hi less its end line k: [lo+1,hi] or [lo,hi-1]; null when k is no end of a range of two or more lines. Pure.
function dropLine(lo,hi,k){if(lo>=hi)return null; return k===lo?[lo+1,hi]:k===hi?[lo,hi-1]:null;}
// The rows the excerpt draws round lo..hi in a file of n lines, top to bottom: a dimmed line above (none above line 1), the
// band - folded to its first two and last two lines round {kind:'fold', n} when longer than five and not opened - and a
// dimmed line below (none past line n). Each row is {k, kind:'ctx'|'on', edge} (edge: an end of a band of two or more). Pure.
function excerptRows(lo,hi,n,open){const out=[],c=hi-lo+1,on=k=>({k,kind:'on',edge:c>1&&(k===lo||k===hi)});
  if(lo>1)out.push({k:lo-1,kind:'ctx',edge:false});
  if(c<=5||open)for(let k=lo;k<=hi;k++)out.push(on(k));
  else out.push(on(lo),on(lo+1),{kind:'fold',n:c-4},on(hi-1),on(hi));
  if(hi<n)out.push({k:hi+1,kind:'ctx',edge:false});
  return out;}
// Each selection's or edit card's source lines (line -> text, null when the server gave none) and the ones being fetched.
// Kept beside the object, not on it: the composer's selection is written to the tab's draft (draft.js) as JSON.
const XP_LINES=new WeakMap(),XP_BUSY=new WeakSet();
// o's line cache (XP_LINES), made on first use.
function excerptLines(o){let m=XP_LINES.get(o); if(!m){m=new Map(); XP_LINES.set(o,m);} return m;}
// Reads a numbered snippet ('   40  text' lines, limn.pins.location.mapping.snippet) into o's line cache.
function excerptTake(o,snip){const L=excerptLines(o);
  String(snip||'').split('\n').forEach(s=>{const m=/^\s*(\d+)(?: {2}(.*))?$/.exec(s); if(m)L.set(+m[1],m[2]||'');});}
// Fetches the lines the excerpt shows that o's cache lacks - its ends and their neighbours - in at most two windows of
// /api/snippet, then redraws o's panel. A line the server did not give is cached as null ('…'), so a failure never loops.
async function excerptFetch(o){const n=o.n_lines||o.hi,want=new Set();
  for(const k of [o.lo-1,o.lo,o.lo+1,o.hi-1,o.hi,o.hi+1])if(k>=1&&k<=n)want.add(k);
  const L=excerptLines(o),miss=[...want].filter(k=>!L.has(k)).sort((a,b)=>a-b); if(!miss.length||XP_BUSY.has(o))return; XP_BUSY.add(o);
  const wins=[]; miss.forEach(k=>{const w=wins[wins.length-1]; if(w&&k<=w[1]+4)w[1]=k; else wins.push([k,k]);});
  try{for(const [a,b] of wins){const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+a+'&hi='+b,o.doc),{what:'원문 읽기'});
      excerptTake(o,data.snippet); if(data.n_lines)o.n_lines=data.n_lines;}}catch(e){}
  miss.forEach(k=>{if(!L.has(k))L.set(k,null);}); XP_BUSY.delete(o); excerptRedraw(o);}
// Redraws the panel o belongs to (the composer's selection or the open edit card); a stale o draws nothing.
function excerptRedraw(o){if(o===COMPOSE.current)renderComposer(); else if(o===EDITOR.current)renderEdit();}
// o's excerpt box: the composer's #c-xp or the open edit card's .e-xp, else null.
function excerptBox(o){return o===COMPOSE.current?$('#c-xp'):o===EDITOR.current?EDITOR.current.el.querySelector('.e-xp'):null;}
// Draws o's excerpt into box on the compact bands, or clears and hides it (the mouse desktop, a region, no selection).
// isEdit: an edit card (the composer's [원문 펼치기] unfolds a long band; an edit card's band stays folded).
function drawExcerpt(o,box,isEdit){const on=LAYOUT!==LAYOUT_MODE.WIDE&&!!o&&!o.region&&!isRegion(o);
  box.hidden=!on; if(!on){box.innerHTML=''; return;}
  excerptTake(o,o.snippet); excerptFetch(o);
  const L=excerptLines(o),text=k=>{const t=L.get(k); return esc(t==null?'…':t);};
  const rows=excerptRows(o.lo,o.hi,o.n_lines||o.hi,!isEdit&&SNIP_OPEN).map(r=>r.kind==='fold'?'<div class="xp-fold">… '+esc(tl('{n}줄',{n:r.n}))+'</div>':
    r.kind==='ctx'?'<button class="xp-row ctx" data-act="xp-to" data-line="'+r.k+'" aria-label="'+esc(tl('L{n}까지 넓히기',{n:r.k}))+'"><span class="ln">'+r.k+'</span>'+
      '<span class="tx">'+text(r.k)+'</span><span class="xp-chip add" aria-hidden="true">'+ic('plus')+'</span></button>':
    '<div class="xp-row on" data-line="'+r.k+'"><span class="ln">'+r.k+'</span><span class="tx">'+text(r.k)+'</span>'+
      (r.edge?'<button class="xp-chip xp-drop" data-act="xp-drop" data-line="'+r.k+'" aria-label="'+esc(tl('이 줄 빼기 (L{n})',{n:r.k}))+'">'+ic('minus')+'</button>':'<span></span>')+'</div>');
  box.innerHTML='<div class="xp-hint">'+esc(tr('흐린 줄을 누르면 그 줄까지 넓어지고, −를 누르면 그 줄이 빠집니다'))+'</div>'+
    '<div class="xp-list '+(WRAP?'wrap':'nowrap')+'" translate="no">'+rows.join('')+'</div>';
  if(!isEdit){const c=o.hi-o.lo+1; $('#c-expand').hidden=c<=5; $('#c-expand').textContent=SNIP_OPEN?tr('원문 접기'):tr('원문 펼치기')+' · '+tl('{n}줄',{n:c});}}
// Applies range r ([lo,hi], kept inside the file) to o as lines set by hand (scope 'lines', as the stepper does), then the
// overlap (composer), the panel and the source text. The sheet scrolls by whatever the redraw moved line anchor's row - the
// end that stayed - so a row that came or went above never shifts the band under the finger. Nothing changed: nothing done.
function applyRange(o,r,anchor){if(!o||!r)return; const n=o.n_lines||Math.max(r[1],o.hi),lo=Math.max(1,Math.min(r[0],n)),hi=Math.max(lo,Math.min(r[1],n));
  if(lo===o.lo&&hi===o.hi)return;
  const row=()=>{const b=excerptBox(o); return b&&b.querySelector('.xp-row[data-line="'+anchor+'"]');},r0=row(),y0=r0&&r0.getBoundingClientRect().top;
  o.lo=lo; o.hi=hi; o.scope='lines'; o.env=null; if(o===COMPOSE.current)recomputeOverlap(); excerptRedraw(o);
  const r1=row(); if(r0&&r1)$('#right').scrollTop+=r1.getBoundingClientRect().top-y0;
  refetchSnip(o,()=>excerptRedraw(o));}
