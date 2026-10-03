// ------------------------------------------------ Range levels
function lvOf(obj,key){return (obj.levels||[]).find(l=>l.level===key||(l.merged||[]).includes(key));}
function kindFor(scope,env){if(!scope)return null; if(scope.startsWith('env'))return 'env:'+(env||'?');
  return scope==='para'?'paragraph':'lines';}
// The name of o's range kind for a description: its rung's, else its kind's; '' for lines set one by one (scope 'lines'),
// whose lines alone say what they are.
function scopeLabel(o){const lv=o.scope&&lvOf(o,o.scope); if(lv)return levelLabel(lv.label); if(o.scope==='lines')return '';
  return tr(({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일',lines:'줄'})[o.kind]||o.kind||'');}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(s){s=String(s||''); if(LANG!==UI_LANG.EN)return s; const m=/^환경 (.+?)( \(바깥( 2)?\))?$/.exec(s);
  return m?tl(m[3]?'환경 {env} (바깥 2)':m[2]?'환경 {env} (바깥)':'환경 {env}',{env:m[1]}):tr(s);}
// Shows the level matching the current range as pressed. If scope is set, that level (when the range also matches); otherwise the first level whose lo/hi match
// (shown as '지금 범위' on an edit card).
function curLevel(o){const ls=o.levels||[];
  const s=o.scope&&lvOf(o,o.scope); if(s&&s.lo===o.lo&&s.hi===o.hi)return s;
  return ls.find(l=>l.lo===o.lo&&l.hi===o.hi)||null;}
// Line-range notation: 'L159' for a single line, 'L155-L173' for multiple (the copy/pins.md format 'L159-L159' is left as-is).
function rng(lo,hi){return 'L'+lo+(hi!==lo?'-L'+hi:'');}
// Segment-control labels are kept short - '환경 abstract' -> 'abstract'. When the same environment name appears more than
// once, '(바깥)' is kept to distinguish them. The line range is left out of the label, going instead into the description (data-tip)/aria-label and the location line.
// A figure rung is named by its element as the server labelled it (a person's words, not run through levelLabel).
function levelName(lv,all){if(lv.el)return String(lv.label||elName(lv.el)); if(!lv.env)return levelLabel(lv.label);
  const dup=(all||[]).filter(o=>o.env===lv.env).length>1; return dup?levelLabel(lv.label).replace(/^(환경|Environment) /,''):lv.env;}
// The range ladder's segments (composer and edit card) as Html, one button per rung, the rung matching the range pressed. A
// figure rung (it carries an element) gets the element's tooltip; its line count comes from lo-hi when the rung has no n.
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur,n=rungLines(lv);
  const tip=lv.el?rungTip(lv):isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?tr('지금 범위'):levelName(lv,ls),nl=tl('{n}줄',{n});
  return html`<button class="${on?'on':''}" data-act="level" data-level="${lv.level}" aria-pressed="${on}" aria-label="${label+' '+rng(lv.lo,lv.hi)+' · '+nl}" \
data-tip="${rng(lv.lo,lv.hi)+' · '+tr(tip)}">${label} <span class="k${n>50?' wn':''}">· ${nl}</span></button>`;});}
// A rung's line count: the server's n, else its lo-hi span (a figure rung may come without n).
function rungLines(lv){return typeof lv.n==='number'?lv.n:lv.hi-lv.lo+1;}
// Draws the range ladder of o into box (#c-levels or an edit card's .e-levels): its segments, shown only when there are two
// or more rungs - one segment is no choice, and '문단 · 1줄' alone read as noise (the owner's phone); the caption then names
// that rung (rangeCap). data-rungs keeps the count for the CSS and the tests.
function drawLadder(box,o,isEdit){const n=(o.levels||[]).length; box.dataset.rungs=String(n); box.hidden=n<2;
  setHtml(box,n<2?html``:html`<div class="lad-t">${levelBtns(o,isEdit)}</div>`); if(n>=2)segReveal(box);}   // .lad-t: the drawn track inside the scroll box
// The range caption over the ladder (composer and edit card): '범위 L5-L6 · 2줄' - the lines a save will hand over and their
// count, whatever set them (a rung or the excerpt). When the ladder is hidden (one rung) and the range is that
// rung, its name follows ('범위 L5 · 1줄 · 문단'); with a ladder, its pressed segment names it. An edit card's own lines (its
// 'raw' rung) get no name. A range matching no rung has none either: the lines say what it is ('줄 직접 지정' is gone). In
// an edit card the range copies as 'file Llo-Lhi' (the composer's location line has its copy).
// Writes the caption markup (Html) into el only when its text changed: the caption is a polite live region (a screen
// reader hears the new range after a rung or an excerpt press, not every redraw), and its copyable range keeps its focus.
function setCap(el,markup){if(el._cap!==markup.text){el._cap=markup.text; setHtml(el,markup);}}
function rangeCap(o,isEdit){const ls=o.levels||[],cur=curLevel(o),r=rng(o.lo,o.hi);
  const named=ls.length<2&&cur&&!(isEdit&&cur.level==='raw')?' · '+levelName(cur,ls):'';
  const v=isEdit?html`<span class="e-range loc" tabindex="0" data-copy="${o.name+' L'+o.lo+'-L'+o.hi}" data-tip="${tr('저장하면 핀이 가리킬 원문 줄. 누르면 복사')}">${r}</span>`:html`<span class="rg-v">${r}</span>`;
  return html`<b class="rg-l">${tr('범위')}</b> ${v} · ${tl('{n}줄',{n:o.hi-o.lo+1})}${named}`;}
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left untouched).
function segReveal(seg){const on=seg&&seg.querySelector('.on'); if(!on){segFade(seg);return;}
  const l=on.offsetLeft,r=l+on.offsetWidth;
  if(l<seg.scrollLeft)seg.scrollLeft=Math.max(0,l-4); else if(r>seg.scrollLeft+seg.clientWidth)seg.scrollLeft=r-seg.clientWidth+4;
  segFade(seg);}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, the right-side
// segment (after 'minipage - 43 lines') used to just get clipped with no indication there was more (QA 2026-09-24). The same idea as the document-links row (docLinksFade).
function segFade(seg){if(!seg)return; const over=seg.scrollWidth-seg.clientWidth;
  seg.classList.toggle('fade-l',over>1&&seg.scrollLeft>1); seg.classList.toggle('fade-r',over>1&&over-seg.scrollLeft>1);}
document.addEventListener('scroll',e=>{const t=/** @type {HTMLElement} */(e.target); if(t&&t.classList&&t.classList.contains('seg'))segFade(t);},true);
// Applies rung key to o (the composer's selection or an edit card): its lines, scope and source; a figure rung also selects
// its element (elSel), which lines later set in the excerpt keep (setLines).
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet; if(lv.el)o.elSel=lv.el;}
let snipT=null;
// Refreshes the text of a range set in the excerpt only while its selection still owns the visit or its edit card survives.
function refetchSnip(o,after){const visit=captureVisit(); clearTimeout(snipT); snipT=setTimeout(async()=>{
  try{const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+o.lo+'&hi='+o.hi,o.doc),{what:'원문 읽기'});
    if((o===EDITOR.current||(o===COMPOSE.current&&currentVisit(visit)))&&data.lo===o.lo&&data.hi===o.hi){o.snippet=data.snippet;after();}}catch(e){}},250);}
function snipText(text,open){const ls=String(text||'').split('\n');
  return (open||ls.length<=8)?ls.join('\n'):ls.slice(0,8).join('\n')+'\n      … '+tl('{n}줄 접힘',{n:ls.length-8});}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that, '위치 불확실';
// below 30%, the warning color. The method used (coordinates, text, or the figure map - whose score is how much of the drag lies in
// the chosen element), the match rate and what to check go in the description. Shared by the composer panel and cards.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via===VIA.SYNCTEX?tr('좌표로 찾음'):p.via===VIA.TEXT?tr('글자로 찾음'):p.via===VIA.MAP?tr('지도로 찾음'):tl('찾은 방법: {via}',{via:p.via});
  const why=tr(p.via===VIA.SYNCTEX?T.synctex:p.via===VIA.TEXT?T.text:p.via===VIA.MAP?T.map:T.viaother);
  return {t:tr('위치 불확실'),tip:tl('{how} · 일치 {pct}% — {why}',{how,pct,why})+(low?' '+tr('많이 어긋났을 수 있습니다.'):''),low};}
