// ------------------------------------------------ Range levels
function lvOf(obj,key){return (obj.levels||[]).find(l=>l.level===key||(l.merged||[]).includes(key));}
function kindFor(scope,env){if(!scope)return null; if(scope.startsWith('env'))return 'env:'+(env||'?');
  return scope==='para'?'paragraph':'lines';}
function scopeLabel(o){const lv=o.scope&&lvOf(o,o.scope); if(lv)return levelLabel(lv.label); if(o.scope==='lines')return tr('줄 직접 지정');
  return tr(({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일',lines:'줄'})[o.kind]||o.kind||'');}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(s){s=String(s||''); if(LANG!=='en')return s; const m=/^환경 (.+?)( \(바깥( 2)?\))?$/.exec(s);
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
function levelName(lv,all){if(!lv.env)return levelLabel(lv.label);
  const dup=(all||[]).filter(o=>o.env===lv.env).length>1; return dup?levelLabel(lv.label).replace(/^(환경|Environment) /,''):lv.env;}
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur;
  const tip=isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?tr('지금 범위'):levelName(lv,ls),nl=tl('{n}줄',{n:lv.n});
  return '<button class="'+(on?'on':'')+'" data-act="level" data-level="'+esc(lv.level)+'" aria-pressed="'+on+'" aria-label="'+
    esc(label+' '+rng(lv.lo,lv.hi)+' · '+nl)+'" data-tip="'+esc(rng(lv.lo,lv.hi)+' · '+tr(tip))+'">'+
    esc(label)+' <span class="k'+(lv.n>50?' wn':'')+'">· '+esc(nl)+'</span></button>';}).join('');}
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left untouched).
function segReveal(seg){const on=seg&&seg.querySelector('.on'); if(!on){segFade(seg);return;}
  const l=on.offsetLeft,r=l+on.offsetWidth;
  if(l<seg.scrollLeft)seg.scrollLeft=Math.max(0,l-4); else if(r>seg.scrollLeft+seg.clientWidth)seg.scrollLeft=r-seg.clientWidth+4;
  segFade(seg);}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, the right-side
// segment (after 'minipage - 43 lines') used to just get clipped with no indication there was more (QA 2026-09-24). The same idea as the document-links row (docLinksFade).
function segFade(seg){if(!seg)return; const over=seg.scrollWidth-seg.clientWidth;
  seg.classList.toggle('fade-l',over>1&&seg.scrollLeft>1); seg.classList.toggle('fade-r',over>1&&over-seg.scrollLeft>1);}
document.addEventListener('scroll',e=>{const t=e.target; if(t&&t.classList&&t.classList.contains('seg'))segFade(t);},true);
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet;}
function nudge(o,dir){let lo=o.lo,hi=o.hi; const max=o.n_lines||hi+1;
  if(dir==='up-grow')lo=Math.max(1,lo-1); else if(dir==='up-shrink')lo=Math.min(hi,lo+1);
  else if(dir==='down-grow')hi=Math.min(max,hi+1); else if(dir==='down-shrink')hi=Math.max(lo,hi-1);
  if(lo===o.lo&&hi===o.hi)return false; o.lo=lo;o.hi=hi;o.scope='lines';o.env=null;return true;}
let snipT=null;
function refetchSnip(o,after){clearTimeout(snipT); snipT=setTimeout(async()=>{
  try{const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+o.lo+'&hi='+o.hi,o.doc),{what:'원문 읽기'});
    if(data.lo===o.lo&&data.hi===o.hi){o.snippet=data.snippet;after();}}catch(e){}},250);}
function snipText(text,open){const ls=String(text||'').split('\n');
  return (open||ls.length<=8)?ls.join('\n'):ls.slice(0,8).join('\n')+'\n      … '+tl('{n}줄 접힘',{n:ls.length-8});}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that, '위치 불확실';
// below 30%, the warning color. The method used, match rate, and what to check go in the description instead ('match 100%' alone was meaningless). Shared by the composer panel and cards.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via==='synctex'?tr('좌표로 찾음'):(p.via==='text'?tr('글자로 찾음'):tl('찾은 방법: {via}',{via:p.via}));
  const why=tr(p.via==='text'?T.text:T.synctex);
  return {t:tr('위치 불확실'),tip:tl('{how} · 일치 {pct}% — {why}',{how,pct,why})+(low?' '+tr('많이 어긋났을 수 있습니다.'):''),low};}

