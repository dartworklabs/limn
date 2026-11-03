// ------------------------------------------------ HTML surface (throwaway PoC)
// docs/superpowers/specs/2026-10-24-html-document-surface.md - deferred and not approved; this part only lets the owner touch
// the direction. A Markdown document (kind "markdown") is drawn by the viewer from its source:
// - GET /api/source answers the file as the server numbers it (str.splitlines(), already split), so the lines this screen shows
//   are the server's lines by construction: they are joined with "\n" for the parser and never re-split from raw bytes.
// - markdown-it (vendored ESM, imported only here) parses with raw HTML off; every block token's `map` becomes data-lo/data-hi on
//   the element drawn for it, and each source line inside a paragraph, heading or code block gets its own span (data-line).
// - The DOM is built with createElement/textContent only: markdown-it's HTML renderer is never used, so the one innerHTML sink
//   (markup.js setHtml) stays the only one. A link keeps only http(s), mailto and an in-document #heading; an image is never
//   fetched - its alt text stands in its place.
// - A text selection (mouse drag, a phone's long-press handles) becomes lines lo..hi; a tap or click on a block picks that block.
//   The ladder is: the chosen lines -> the block -> the heading's section. Saving goes through the ordinary POST /api/pin.
const MD_VERSION='15.0.3';
const MD={lib:/** @type {any} */(null),gen:0,doc:'',file:'',name:'',lines:/** @type {string[]} */([]),
  heads:/** @type {{level:number,lo:number,el:HTMLElement,title:string}[]} */([])};
function rendersInBrowser(kind){return kind===DOC_KIND.MARKDOWN;}
// Whether pin p belongs to a browser-rendered document of this instance (its card names no page).
function isMdPin(p){const d=docInfo(pdoc(p)); return !!d&&rendersInBrowser(d.kind);}
function isMdDoc(){return !!(typeof META!=='undefined'&&META&&rendersInBrowser(META.kind));}
async function mdLib(){if(MD.lib)return MD.lib;
  const m=await import('/vendor/markdown-it/markdown-it.esm.min.mjs?v='+MD_VERSION);
  // html:true only so raw HTML comes as its own tokens (html_block, html_inline) instead of running into the text: they are
  // never drawn as HTML - a block becomes a muted placeholder that keeps its lines, an inline tag shows as code.
  MD.lib=m.default({html:true,linkify:false,typographer:false}); return MD.lib;}
// Draws the Markdown document on screen into #doc (buildDoc's branch for a browser-rendered document).
async function mdBuild(){const gen=++MD.gen,k=DOC,doc=$('#doc');
  document.body.classList.add('md-surface');
  if(!doc.querySelector('#md')){const w=document.createElement('div'); w.className='md-wait dim'; w.textContent=tr('원문을 읽는 중입니다.'); doc.replaceChildren(w);}
  let src; try{src=(await api(dq('/api/source'),{what:'원문 읽기',silent:true})).data;}catch(e){return;}
  if(gen!==MD.gen||k!==DOC||!src||!Array.isArray(src.lines))return;
  let md; try{md=await mdLib();}catch(e){const w=document.createElement('div'); w.className='md-wait'; w.textContent='markdown-it 를 불러오지 못했습니다'; doc.replaceChildren(w); return;}
  if(gen!==MD.gen||k!==DOC)return;
  MD.doc=k; MD.file=src.file; MD.name=src.name; MD.lines=src.lines;
  const root=document.createElement('article'); root.className='md'; root.id='md'; root.setAttribute('translate','no');
  MD.heads=[]; mdRender(md.parse(MD.lines.join('\n'),{}),root);
  const keep=$('#left').scrollTop; doc.replaceChildren(root); $('#left').scrollTop=keep; if(MD_RO)MD_RO.observe(root);
  mdOutline(); marks(); if(COMPOSE.current)mdSelMark(COMPOSE.current);}
// The lines lo..hi of a block token's map, its trailing blank lines left out (a loose list item's map runs over them).
function mdSpan(t){if(!t.map)return null; let lo=t.map[0]+1,hi=Math.max(lo,t.map[1]);
  while(hi>lo&&!String(MD.lines[hi-1]||'').trim())hi--; return {lo,hi};}
function mdMap(el,t,kind){const s=mdSpan(t); if(!s)return; el.dataset.lo=String(s.lo); el.dataset.hi=String(s.hi); el.dataset.kind=kind;}
const MD_KIND={paragraph_open:'paragraph',heading_open:'heading',bullet_list_open:'list',ordered_list_open:'list',list_item_open:'item',
  blockquote_open:'quote',table_open:'table',tr_open:'row'};
// Builds the DOM for markdown-it's token stream into root: block tokens nest by `nesting`, an inline token's children are drawn by
// mdInline. A paragraph markdown-it hides (a tight list's) puts its text straight into the list item.
function mdRender(tokens,root){const stack=[root];
  for(const t of tokens){const top=stack[stack.length-1];
    if(t.nesting===1){
      if(t.hidden){stack.push(top); continue;}
      const tag=t.tag||'div',el=document.createElement(tag); const kind=MD_KIND[t.type]; if(kind)mdMap(el,t,kind);
      if(t.type==='ordered_list_open'){const s=t.attrGet('start'); if(s&&/^\d{1,9}$/.test(s))el.setAttribute('start',s);}
      if(t.type==='th_open'||t.type==='td_open'){const st=t.attrGet('style'),m=/^text-align:(left|right|center)$/.exec(st||''); if(m)el.style.textAlign=m[1];}
      if(t.type==='heading_open'&&t.map){el.id='md-h'+(t.map[0]+1); MD.heads.push({level:+tag.slice(1),lo:t.map[0]+1,el,title:''});}
      top.appendChild(el); stack.push(el);}
    else if(t.nesting===-1)stack.pop();
    else if(t.type==='inline'){mdInline(t,top); if(top.id&&top.id.startsWith('md-h')){const h=MD.heads[MD.heads.length-1]; if(h&&h.el===top)h.title=top.textContent||'';}}
    else if(t.type==='fence'||t.type==='code_block'){const pre=document.createElement('pre'),code=document.createElement('code'); mdMap(pre,t,'code');
      const lang=String(t.info||'').trim().split(/\s+/)[0]; if(lang)pre.dataset.lang=lang;
      const first=t.map?t.map[0]+1+(t.type==='fence'?1:0):0;
      String(t.content).replace(/\n$/,'').split('\n').forEach((ln,i)=>{const s=document.createElement('span'); s.className='ln'; if(first)s.dataset.line=String(first+i); s.textContent=ln+'\n'; code.appendChild(s);});
      pre.appendChild(code); top.appendChild(pre);}
    else if(t.type==='hr'){const hr=document.createElement('hr'); mdMap(hr,t,'rule'); top.appendChild(hr);}
    else if(t.type==='html_block'){const box=document.createElement('div'); mdMap(box,t,'html'); box.className='md-html';
      const sp=mdSpan(t),n=sp?sp.hi-sp.lo+1:0,first=String(t.content).split('\n').find(l=>l.trim())||'';
      const lab=document.createElement('span'); lab.className='md-html-l'; lab.textContent=tl('HTML {n}줄 · 그리지 않습니다',{n});
      const code=document.createElement('code'); code.textContent=first.trim().slice(0,120); if(sp)code.dataset.line=String(sp.lo);
      box.append(lab,code); top.appendChild(box);}
  }}
// An inline token's children into parent: one span per source line (softbreak and hardbreak end a line), emphasis, code, links.
function mdInline(t,parent){let line=t.map?t.map[0]+1:0;
  const mk=()=>{const s=document.createElement('span'); s.className='ln'; if(line)s.dataset.line=String(line); parent.appendChild(s); return s;};
  const stack=[mk()];
  for(const c of t.children||[]){const top=stack[stack.length-1];
    switch(c.type){
      case 'text':top.appendChild(document.createTextNode(c.content));break;
      case 'code_inline':{const e=document.createElement('code'); e.textContent=c.content; top.appendChild(e); break;}
      case 'softbreak':case 'hardbreak':
        top.appendChild(c.type==='hardbreak'?document.createElement('br'):document.createTextNode('\n')); if(line)line++;
        if(stack.length===1)stack[0]=mk(); break;   // an emphasis that runs over a line break keeps its line in the span it began in
      case 'strong_open':case 'em_open':case 's_open':{const e=document.createElement(c.tag); top.appendChild(e); stack.push(e); break;}
      case 'link_open':{const e=mdLink(c.attrGet('href')); top.appendChild(e); stack.push(e); break;}
      case 'strong_close':case 'em_close':case 's_close':case 'link_close':if(stack.length>1)stack.pop(); break;
      case 'image':{const e=document.createElement('span'); e.className='md-img';
        e.textContent=tr('그림')+': '+(c.content||c.attrGet('alt')||c.attrGet('src')||'');
        e.dataset.tip=tl('그림은 불러오지 않습니다 · {src}',{src:String(c.attrGet('src')||'')}); top.appendChild(e); break;}
      case 'html_inline':{const e=document.createElement('code'); e.className='md-html-in'; e.textContent=c.content; top.appendChild(e); break;}
      default:if(c.content)top.appendChild(document.createTextNode(c.content));}}}
// A link element for href: http(s) and mailto open in a new tab without a referrer or opener; an in-document '#…' scrolls to the
// heading it names; anything else (a relative path, another scheme markdown-it let through) is inert text with its target in the tip.
function mdLink(href){const h=String(href||'');
  if(/^(https?:|mailto:)/i.test(h)){const a=document.createElement('a'); a.href=h; a.target='_blank'; a.rel='noopener noreferrer'; a.dataset.tip=h; return a;}
  if(/^#[^#]*$/.test(h)){const a=document.createElement('a'); a.href='javascript:void 0'; a.className='md-anchor'; a.dataset.mdAnchor=h.slice(1); a.removeAttribute('href'); a.setAttribute('role','link'); a.tabIndex=0; return a;}
  const s=document.createElement('span'); s.className='md-rel'; s.dataset.tip=tl('문서 밖 경로는 열지 않습니다 · {href}',{href:h}); return s;}
// GitHub-like heading slug: lower case, punctuation dropped, spaces to '-'.
function mdSlug(s){return String(s).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu,'').replace(/\s/g,'-');}
// ---------------- Picking: selection -> lines, and the ladder
// The lines a DOM point is on: its line span's, else its nearest block's range, else null (outside the document).
function mdRangeAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  const md=$('#md'); if(!md||!md.contains(e))return null;
  const ln=e.closest('[data-line]'); if(ln&&md.contains(ln)){const n=+(/** @type {HTMLElement} */(ln).dataset.line||0); if(n)return {lo:n,hi:n};}
  const b=/** @type {HTMLElement|null} */(e.closest('[data-lo]')); return b&&md.contains(b)?{lo:+(b.dataset.lo||0),hi:+(b.dataset.hi||0)}:null;}
// The block a point belongs to for the ladder's second rung: a table row's table, a list item's paragraph's item, else its nearest block.
function mdBlockAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  let b=/** @type {HTMLElement|null} */(e.closest('[data-lo]')); if(!b)return null;
  if(b.dataset.kind==='row')b=/** @type {HTMLElement|null} */(b.closest('table[data-lo]'))||b;
  else if(b.dataset.kind==='paragraph'&&b.parentElement&&b.parentElement.dataset.kind==='item')b=b.parentElement;
  return b;}
const MD_BLOCK_LABEL={html:'HTML 블록',paragraph:'문단',heading:'제목',item:'목록 항목',list:'목록',quote:'인용',table:'표',code:'코드 블록',rule:'구분선'};
function mdSnippet(lo,hi){const out=[]; for(let n=lo;n<=Math.min(hi,lo+79);n++)out.push(String(n).padStart(5,' ')+'  '+(MD.lines[n-1]||''));
  if(hi-lo+1>80)out.push('      ... ('+(hi-lo+1-80)+'줄 더)'); return out.join('\n');}
// The section around line n: from the nearest heading at or above it to the line before the next heading of the same or a higher
// level (the file's end when none), its trailing blank lines left out. null above the first heading.
function mdSection(lo,hi){let h=null; for(const x of MD.heads){if(x.lo<=lo)h=x; else break;} if(!h)return null;
  let end=MD.lines.length; for(const x of MD.heads){if(x.lo>h.lo&&x.level<=h.level){end=x.lo-1; break;}}
  while(end>h.lo&&!String(MD.lines[end-1]||'').trim())end--; if(end<hi)return null; return {lo:h.lo,hi:end,title:h.title};}
// The ladder for lines a..b (a drag) and the blocks it began and ended in: rungs with equal ranges merge into the first.
function mdLevels(r,b0,b1){const ls=[]; const add=(level,label,lo,hi)=>{const same=ls.find(l=>l.lo===lo&&l.hi===hi);
    if(same){(same.merged=same.merged||[]).push(level); return;} ls.push({level,label,lo,hi,n:hi-lo+1,snippet:mdSnippet(lo,hi)});};
  add('raw','고른 줄',r.lo,r.hi);
  if(b0&&b1){const lo=Math.min(+(b0.dataset.lo||0),+(b1.dataset.lo||0)),hi=Math.max(+(b0.dataset.hi||0),+(b1.dataset.hi||0));
    add('block',b0===b1?(MD_BLOCK_LABEL[b0.dataset.kind||'']||'블록'):'블록',Math.min(lo,r.lo),Math.max(hi,r.hi));}
  const s=mdSection(r.lo,r.hi); if(s)add('section','절 · '+(s.title.length>18?s.title.slice(0,18)+'…':s.title),s.lo,s.hi);
  return ls;}
// Fills the composer with a selection of lines (what pick() does with a /api/pick answer). tapped: a tap picked a block, so
// the block rung is the default.
function mdPick(r,b0,b1,quote,tapped){if(REPICK||EDITOR.current||REPLY)return;
  endTopic(NOTICE_TOPIC.PICK); PICKSEQ++;
  const levels=mdLevels(r,b0,b1);
  const sel=/** @type {Selection} */(/** @type {unknown} */({doc:DOC,file:MD.file,name:MD.name,lo:r.lo,hi:r.hi,raw_lo:r.lo,raw_hi:r.hi,kind:'lines',
    score:null,warn:null,snippet:mdSnippet(r.lo,r.hi),levels,default_level:tapped?'block':'raw',n_lines:MD.lines.length,
    quote:String(quote||'').replace(/\s+/g,' ').trim().slice(0,160),overlaps:[]}));
  COMPOSE.current=sel; COMPOSE.intent++; COMPOSE.picking=false; sel.scope=null; sel.elSel=null; useLevel(sel,sel.default_level);
  $('#composer').hidden=false; setBusy(false); $('#c-err').hidden=true; $('#c-body').hidden=false;
  setSide(true); applySide(); COMPOSE.dismissedOverlap=null; sel.overlaps=overlapsFor(sel,PINS); SNIP_OPEN=false;
  renderComposer(); renderVerdictRow(); $('#composer').scrollTop=0; if(LAYOUT!==LAYOUT_MODE.WIDE)$('#right').scrollTop=0;
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});}
// The chosen lines drawn on the document: their line spans and blocks get .md-sel (null clears).
function mdSelMark(d){$$('#md .md-sel').forEach(e=>e.classList.remove('md-sel')); if(!d||!isMdDoc()||d.file!==MD.file)return;
  mdLeaves(d.lo,d.hi).forEach(e=>e.classList.add('md-sel'));}
// The elements that stand for lines lo..hi: each line span in range, and each block in range that has no line spans of its own
// and no smaller block in range (a rule, an empty item) - the smallest things on screen that carry those lines.
function mdLeaves(lo,hi){const md=$('#md'); if(!md)return [];
  const lines=[...md.querySelectorAll('[data-line]')].filter(e=>{const n=+(/** @type {HTMLElement} */(e).dataset.line||0); return n>=lo&&n<=hi;});
  const blocks=[...md.querySelectorAll('[data-lo]')].filter(e=>{const h=/** @type {HTMLElement} */(e),a=+(h.dataset.lo||0),b=+(h.dataset.hi||0);
    return a<=hi&&b>=lo&&!h.querySelector('[data-line],[data-lo]');});
  // A table cell's line stands for its row: the row is what is tinted, so a pinned row reads as one band.
  const out=new Set(); for(const e of [...lines,...blocks]){const row=e.closest('tr[data-lo]'); out.add(row&&md.contains(row)?row:e);}
  return /** @type {HTMLElement[]} */([...out]);}
// ---------------- Pins on the document
// The marks of the pins on screen (marks()' branch): each pin's lines get .md-pin (review .rv, lost .st), and the first of them a
// number badge in the left gutter that jumps to the card (data-act mark-jump, as on a PDF page).
function mdMarks(){const md=$('#md'); if(!md)return;
  md.querySelectorAll('.md-badges').forEach(e=>e.remove()); md.querySelectorAll('.md-pin').forEach(e=>e.classList.remove('md-pin','rv','st'));
  const pins=PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).filter(p=>!isRegion(p)&&typeof p.lo==='number'&&typeof p.hi==='number');
  const rows=/** @type {Map<number,HTMLElement>} */(new Map()), top=md.getBoundingClientRect().top-md.scrollTop;
  for(const p of pins){const leaves=mdLeaves(/** @type {number} */(p.lo),/** @type {number} */(p.hi)); if(!leaves.length)continue;
    const rv=pinState(p)===PIN_STATE.REVIEW,lost=!!p.stale;
    leaves.forEach(e=>{e.classList.add('md-pin'); if(rv)e.classList.add('rv'); if(lost)e.classList.add('st');});
    // The badge stands in the column's left gutter at the height of the pin's first line (a layer of #md, never inside a
    // paragraph, list or table, so it moves no text). Pins whose first lines share a height stack down.
    const y=Math.round(leaves[0].getBoundingClientRect().top-top);
    let box=rows.get(y); if(!box){box=document.createElement('span'); box.className='md-badges'; box.setAttribute('translate','no'); box.style.top=y+'px'; md.appendChild(box); rows.set(y,box);}
    const b=document.createElement('button'); b.type='button'; b.className='md-badge'+(rv?' rv':'')+(lost?' st':''); b.dataset.act='mark-jump'; b.dataset.id=String(p.id);
    b.dataset.pin=String(p.id); b.textContent=String(p.id); b.setAttribute('aria-label',tl('핀 #{id} 카드로 이동',{id:p.id}));
    const n=String(p.note||'').replace(/\s+/g,' ').trim(); b.dataset.tip='#'+p.id+' · '+rng(/** @type {number} */(p.lo),/** @type {number} */(p.hi))+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):tr('(메모 없음)'));
    box.appendChild(b);}}
// The column reflows when its width changes (a panel, a rotation): the badges follow their lines.
let MD_RO_T=0; const MD_RO=window.ResizeObserver?new ResizeObserver(()=>{clearTimeout(MD_RO_T); MD_RO_T=setTimeout(()=>{if(isMdDoc())mdMarks();},120);}):null;
// Scrolls pin id's first line to the reading depth and flashes its lines (jumpPin's branch).
function mdJump(id){const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id); if(!p||typeof p.lo!=='number'||typeof p.hi!=='number')return;
  const leaves=mdLeaves(p.lo,p.hi); if(!leaves.length)return; const L=$('#left'),lr=L.getBoundingClientRect(),r=leaves[0].getBoundingClientRect();
  L.scrollTop+=(r.top-(lr.top+lr.height*0.30)); leaves.forEach(e=>{e.classList.remove('md-flash'); void e.offsetWidth; e.classList.add('md-flash');});
  setTimeout(()=>leaves.forEach(e=>e.classList.remove('md-flash')),1200);}
// ---------------- Outline from headings
function mdOutline(){outlineForget(); OUTLINE_ENTRIES=MD.heads.map((h,i)=>({title:h.title,number:'',depth:Math.max(0,h.level-1),page:i+1,pageLabel:'L'+h.lo,frac:0,up:-1}));
  OUTLINE_DOC=DOC; OUTLINE_BUILD=''; renderOutline();}
function mdGoHeading(i){const h=MD.heads[i]; if(!h)return; OUTLINE_SELECTED=i; markOutline();
  const L=$('#left'),lr=L.getBoundingClientRect(),r=h.el.getBoundingClientRect(); L.scrollTo({top:L.scrollTop+r.top-lr.top-8,behavior:SMOOTH});
  if(LAYOUT===LAYOUT_MODE.NARROW&&typeof closeNavSheet==='function')closeNavSheet();}
// ---------------- Input on the document
// A mouse drag ends: its text selection, if inside the document, is the pick. A press without a selection (a click, a tap) picks the
// block under it - not on a link, a badge or another control.
function mdSelectionPick(tapTarget){const s=window.getSelection(); const md=$('#md'); if(!md)return false;
  if(s&&!s.isCollapsed&&s.rangeCount){const r=s.getRangeAt(0); if(!md.contains(r.commonAncestorContainer))return false;
    let a=mdRangeAt(r.startContainer),b=mdRangeAt(r.endContainer); if(!a||!b)return false;
    // A selection that ends before any character of its last line (a triple click ends at the start of the next block) does
    // not take that line: nothing of it is selected.
    if(b.lo>a.hi&&mdNothingOfEnd(r)){const prev=b.lo-1; b={lo:Math.max(a.lo,prev),hi:Math.max(a.lo,prev)};}
    let lo=Math.min(a.lo,b.lo),hi=Math.max(a.hi,b.hi); while(hi>lo&&!String(MD.lines[hi-1]||'').trim())hi--;
    mdPick({lo,hi},mdBlockAt(r.startContainer),mdBlockAt(r.endContainer),s.toString(),false); return true;}
  if(tapTarget){const t=/** @type {Element} */(tapTarget); if(t.closest('a,button,.md-badges,[role=link]'))return false;
    const b=/** @type {HTMLElement|null} */(t.closest('#md [data-lo]')); if(!b)return false;
    const r=mdRangeAt(t)||{lo:+(b.dataset.lo||0),hi:+(b.dataset.hi||0)},blk=mdBlockAt(t);
    mdPick(r,blk,blk,(blk||b).innerText||'',true); return true;}
  return false;}
// Whether range r takes no visible character of the line (or block) its end is in.
function mdNothingOfEnd(r){const e=r.endContainer.nodeType===1?/** @type {Element} */(r.endContainer):r.endContainer.parentElement; if(!e)return false;
  const host=e.closest('[data-line]')||e.closest('[data-lo]'); if(!host)return false;
  const head=document.createRange(); head.setStart(host,0); head.setEnd(r.endContainer,r.endOffset); return !head.toString().trim();}
$('#doc').addEventListener('mouseup',e=>{if(!isMdDoc()||e.button!==0)return; setTimeout(()=>mdSelectionPick(null),0);});
$('#doc').addEventListener('click',e=>{if(!isMdDoc())return; const t=/** @type {Element} */(e.target);
  const an=/** @type {HTMLElement|null} */(t.closest('.md-anchor')); if(an){const want=an.dataset.mdAnchor||'',i=MD.heads.findIndex(h=>mdSlug(h.title)===want); if(i>=0)mdGoHeading(i); return;}
  const s=window.getSelection(); if(s&&!s.isCollapsed)return; mdSelectionPick(t);});
// A finger: the long-press handles make a selection with no mouseup; it is picked once it rests.
let MD_SEL_T=0;
document.addEventListener('selectionchange',()=>{if(!isMdDoc()||!MQ_COARSE.matches)return; clearTimeout(MD_SEL_T);
  MD_SEL_T=setTimeout(()=>{const s=window.getSelection(); if(s&&!s.isCollapsed)mdSelectionPick(null);},500);});
