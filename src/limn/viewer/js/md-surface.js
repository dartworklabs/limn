// ------------------------------------------------ HTML surface (throwaway PoC)
// docs/superpowers/specs/2026-10-24-html-document-surface.md - deferred and not approved; this part only lets the owner touch
// the direction. A Markdown document (kind "markdown") is drawn by the viewer from its source:
// - GET /api/source answers the file as the server numbers it (str.splitlines(), already split), so the lines this screen shows
//   are the server's lines by construction: they are joined with "\n" for the parser and never re-split from raw bytes.
// - markdown-it (vendored ESM, imported only here) parses with raw HTML as its own tokens; every block token's `map` becomes
//   data-lo/data-hi on the element drawn for it. Inside a paragraph or heading each source line gets its own span (data-line)
//   only when the line breaks the parser kept match the line ends of the source (mdInlineLines); otherwise the whole run of
//   text is one span with the block's lines. A code block's content lines are its source lines one for one.
// - The DOM is built with createElement/textContent only: markdown-it's HTML renderer is never used, so the one innerHTML sink
//   (markup.js setHtml) stays the only one. A link opens only through mdHref's allowlist (another origin's http(s), mailto, an
//   in-document #heading); an image is never fetched - its alt text stands in its place.
// - A text selection (mouse drag, a phone's long-press handles) becomes lines lo..hi; a tap or click on a block picks that block.
//   The ladder is: the chosen lines -> the block -> the heading's section. Saving goes through the ordinary POST /api/pin.
const MD_VERSION='15.0.3';
const MD={lib:/** @type {any} */(null),gen:0,doc:'',file:'',name:'',lines:/** @type {string[]} */([]),at:0,
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
  mdOutline(); marks(); if(COMPOSE.current)mdSelMark(COMPOSE.current); mdStrip();}
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
      if(t.content)String(t.content).replace(/\n$/,'').split('\n').forEach((ln,i)=>{const s=document.createElement('span'); s.className='ln'; if(first)s.dataset.line=String(first+i); s.textContent=ln+'\n'; code.appendChild(s);});
      pre.appendChild(code); top.appendChild(pre);}
    else if(t.type==='hr'){const hr=document.createElement('hr'); mdMap(hr,t,'rule'); top.appendChild(hr);}
    else if(t.type==='html_block'){const box=document.createElement('div'); mdMap(box,t,'html'); box.className='md-html';
      const sp=mdSpan(t),n=sp?sp.hi-sp.lo+1:0,first=String(t.content).split('\n').find(l=>l.trim())||'';
      const lab=document.createElement('span'); lab.className='md-html-l'; lab.textContent=tl('HTML {n}줄 · 그리지 않습니다',{n});
      const code=document.createElement('code'); code.textContent=first.trim().slice(0,120); if(sp)code.dataset.line=String(sp.lo);
      box.append(lab,code); top.appendChild(box);}
  }}
// ---------------- Rendered text -> source lines
// The source line each child of inline token t starts on (pure): t's first line plus the line breaks (softbreak, hardbreak)
// before the child. The children are flat - emphasis and links are open/close tokens among them - so a break inside one is
// counted too. That names the right line only when every line end in t's source became such a break. A code span (it turns
// the line end into a space), a raw HTML tag, a link's destination or title, a reference label or an image's alt text that runs
// over a line end swallows it, and every child after it would be labelled one line early; markdown-it gives inline children no
// source offsets to recover from that. So exact is true only when the breaks and the line ends of t.content are as many, and
// then lines[i] is child i's line; otherwise the caller gives the whole token one range, lo..hi (its first to last line).
/** @param {{map?:number[]|null,content?:string,children?:{type:string}[]|null}} t
    @returns {{exact:boolean,lo:number,hi:number,lines:number[]}} */
function mdInlineLines(t){const lo=t.map?t.map[0]+1:0,ends=(String(t.content||'').match(/\n/g)||[]).length;
  let n=0; const lines=(t.children||[]).map(c=>{const at=lo+n; if(c.type==='softbreak'||c.type==='hardbreak')n++; return at;});
  return {exact:lo>0&&n===ends,lo,hi:lo?lo+ends:0,lines};}
// An inline token's children into parent, its lines as mdInlineLines tells them. Exact: one span per source line (data-line);
// a break inside emphasis or a link ends the open elements in the old line's span and opens shallow copies of them in the new
// one, so the text after the break is under its own line. Not exact: one span with the token's whole range (data-lo/data-hi,
// kind 'lines'), so a selection inside it takes all of those lines - never a wrong one, and never a suggestion's wrong base.
function mdInline(t,parent){const m=mdInlineLines(t);
  const mk=(/** @type {number} */line)=>{const s=document.createElement('span'); s.className='ln';
    if(m.exact)s.dataset.line=String(line); else if(m.lo){s.dataset.lo=String(m.lo); s.dataset.hi=String(m.hi); s.dataset.kind='lines';}
    parent.appendChild(s); return s;};
  let stack=/** @type {HTMLElement[]} */([mk(m.lo)]);
  (t.children||[]).forEach((c,i)=>{const top=stack[stack.length-1];
    switch(c.type){
      case 'text':top.appendChild(document.createTextNode(c.content));break;
      case 'code_inline':{const e=document.createElement('code'); e.textContent=c.content; top.appendChild(e); break;}
      case 'softbreak':case 'hardbreak':
        top.appendChild(c.type==='hardbreak'?document.createElement('br'):document.createTextNode('\n'));
        if(m.exact){const next=[mk(m.lines[i]+1)];
          for(const e of stack.slice(1)){const k=/** @type {HTMLElement} */(e.cloneNode(false)); next[next.length-1].appendChild(k); next.push(k);}
          stack=next;}
        break;
      case 'strong_open':case 'em_open':case 's_open':{const e=document.createElement(c.tag); top.appendChild(e); stack.push(e); break;}
      case 'link_open':{const e=mdLink(c.attrGet('href')); top.appendChild(e); stack.push(e); break;}
      case 'strong_close':case 'em_close':case 's_close':case 'link_close':if(stack.length>1)stack.pop(); break;
      case 'image':{const e=document.createElement('span'); e.className='md-img';
        e.textContent=tr('그림')+': '+(c.content||c.attrGet('alt')||c.attrGet('src')||'');
        e.dataset.tip=tl('그림은 불러오지 않습니다 · {src}',{src:String(c.attrGet('src')||'')}); top.appendChild(e); break;}
      case 'html_inline':{const e=document.createElement('code'); e.className='md-html-in'; e.textContent=c.content; top.appendChild(e); break;}
      default:if(c.content)top.appendChild(document.createTextNode(c.content));}});}
// What a link in the document may do (pure; origin is the viewer page's location.origin). Every link token comes here - an
// ordinary link, an autolink, a reference link - and this allowlist is the gate. markdown-it's own validateLink is a denylist
// (javascript:, vbscript:, file:, data: but data:image/gif|png|jpeg|webp) and lets ftp:, any custom scheme and those images through.
// - '#…' is an in-document heading: {open:'anchor', id}.
// - mailto: is {open:'mail', href}.
// - An absolute http(s) URL is {open:'web', href} when it names an origin other than the viewer's, no loopback host and no user or
//   password. href is the URL as parsed here, so what the browser follows is what was checked: a raw 'https:/api/meta' would
//   resolve against the page to the viewer's own origin, while parsed alone it is https://api/meta.
// - Anything else is {open:null}, inert text with its target in the tip: a relative path, a scheme-relative '//host', another
//   scheme, the viewer's own origin (Limn's API answers GETs with the reader's identity and some of them write - a full /api/meta
//   re-syncs pins, / records the visit), a loopback host (on the server's machine that is Limn again, as the local agent).
// Both checks compare hosts by one spelling (mdHostKey), the destination's and the viewer's alike: 'localhost.:18920' and
// 'x.ts.net.:18020' are Limn again (its Host check reads a name with its trailing dots dropped), not another origin.
/** @param {unknown} raw @param {string} origin @returns {{open:'web'|'mail'|'anchor'|null,href:string,id?:string}} */
function mdHref(raw,origin){const h=String(raw==null?'':raw).trim();
  if(/^#[^#]*$/.test(h))return {open:'anchor',href:h,id:h.slice(1)};
  if(!/^(https?|mailto):/i.test(h))return {open:null,href:h};
  let u; try{u=new URL(h);}catch(e){return {open:null,href:h};}
  if(u.protocol==='mailto:')return {open:'mail',href:u.href};
  if(u.username||u.password||mdSameOrigin(u,origin)||mdLoopback(u.hostname))return {open:null,href:h};
  return {open:'web',href:u.href};}
// A host's one spelling (URL.hostname, or a Host header's name): lower case, without IPv6 brackets or trailing dots. The URL
// parser already folds case, full-width letters, percent escapes and every IPv4 spelling (127.1, 0x7f.1, 017700000001,
// 2130706433, '127.0.0.1.') into dotted form, and IPv6 into its short hex form; the trailing dot of a name ('localhost.',
// also from 'localhost%2e' or 'localhost。') it keeps. DNS reads 'name.' as 'name', and so does Limn's Host and Origin check
// (security/access.py split_host, origin_ok: name.rstrip('.')): this rule is that one. Pure.
function mdHostKey(host){return String(host==null?'':host).toLowerCase().replace(/^\[|\]$/g,'').replace(/\.+$/,'');}
// Whether URL u has the viewer page's origin (location.origin): scheme, host by one spelling (mdHostKey) and port (the URL
// parser leaves a default port out of both). An origin that does not parse ('null') counts as the same: every link is
// inert rather than one let through unchecked. Pure.
/** @param {URL} u @param {string} origin */
function mdSameOrigin(u,origin){let v; try{v=new URL(origin);}catch(e){return true;}
  return u.protocol===v.protocol&&mdHostKey(u.hostname)===mdHostKey(v.hostname)&&u.port===v.port;}
// Whether a URL's host (URL.hostname) is this machine: localhost and *.localhost, 0.0.0.0/8 and 127.0.0.0/8, and in IPv6
// :: and ::1 and an IPv4-mapped (::ffff:a.b.c.d) or -compatible (::a.b.c.d) address of those. Hosts are compared by
// mdHostKey's spelling; the URL parser has put every address in one form (mdHostKey). A name a hosts file maps to loopback
// (ip6-localhost, the machine's own name) is not listed: Limn's Host check admits only localhost, 127.0.0.1 and ::1 as
// loopback and answers any other such name 403. Pure.
function mdLoopback(host){const h=mdHostKey(host);
  if(h==='localhost'||h.endsWith('.localhost'))return true;
  if(/^(127|0)\.\d+\.\d+\.\d+$/.test(h))return true;
  const g=mdIpv6(h); if(!g)return false;
  if(g.slice(0,5).every(x=>x===0)&&(g[5]===0xffff||g[5]===0)){const o=g[6]>>8; return o===127||o===0;}   // also :: and ::1
  return false;}
// An IPv6 address in the URL parser's form (hex groups, one '::' at most, no brackets) -> its eight 16-bit groups; null for
// anything else. Pure.
/** @param {string} h @returns {number[]|null} */
function mdIpv6(h){if(!/^[0-9a-f:]+$/.test(h)||!h.includes(':'))return null;
  const parts=h.split('::'); if(parts.length>2)return null;
  const head=parts[0]?parts[0].split(':'):[],tail=parts.length===2&&parts[1]?parts[1].split(':'):[];
  const fill=parts.length===2?8-head.length-tail.length:0; if(fill<0||(parts.length===1&&head.length!==8))return null;
  const g=[...head,...Array(fill).fill('0'),...tail]; if(g.some(x=>!/^[0-9a-f]{1,4}$/.test(x)))return null;
  return g.map(x=>parseInt(x,16));}
// A link element for href (mdHref): a web or mail link opens in a new tab without a referrer or opener; an in-document '#…'
// scrolls to the heading it names; anything else is inert text with its target in the tip.
function mdLink(href){const r=mdHref(href,location.origin);
  if(r.open==='web'||r.open==='mail'){const a=document.createElement('a'); a.href=r.href; a.target='_blank'; a.rel='noopener noreferrer'; a.dataset.tip=r.href; return a;}
  if(r.open==='anchor'){const a=document.createElement('a'); a.className='md-anchor'; a.dataset.mdAnchor=r.id||''; a.setAttribute('role','link'); a.tabIndex=0; return a;}
  const s=document.createElement('span'); s.className='md-rel'; s.dataset.tip=tl('이 링크는 열지 않습니다 · {href}',{href:r.href}); return s;}
// GitHub-like heading slug: lower case, punctuation dropped, spaces to '-'.
function mdSlug(s){return String(s).trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu,'').replace(/\s/g,'-');}
// ---------------- Picking: selection -> lines, and the ladder
// The lines a DOM point is on: its line span's, else its nearest block's range, else null (outside the document).
function mdRangeAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  const md=$('#md'); if(!md||!md.contains(e))return null;
  const ln=e.closest('[data-line]'); if(ln&&md.contains(ln)){const n=+(/** @type {HTMLElement} */(ln).dataset.line||0); if(n)return {lo:n,hi:n};}
  const b=/** @type {HTMLElement|null} */(e.closest('[data-lo]')); return b&&md.contains(b)?{lo:+(b.dataset.lo||0),hi:+(b.dataset.hi||0)}:null;}
// The block a point belongs to for the ladder's second rung: a table row's table, a list item's paragraph's item, else its nearest
// block (a run of text whose lines could not be told - kind 'lines', mdInline - stands for the block it is in).
function mdBlockAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  let b=/** @type {HTMLElement|null} */(e.closest('[data-lo]')); if(b&&b.dataset.kind==='lines'&&b.parentElement)b=/** @type {HTMLElement|null} */(b.parentElement.closest('[data-lo]')); if(!b)return null;
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
// The source line at the reading line (readingDepth under the pane's top): the last line span or block, in document order, whose
// top is at or above it. 0 before the document is drawn.
function mdReadingLine(){const L=$('#left'),md=$('#md'); if(!L||!md)return 0; const y=L.getBoundingClientRect().top+readingDepth(L);
  let at=0; for(const e of md.querySelectorAll('[data-line],[data-lo]')){const h=/** @type {HTMLElement} */(e);
    if(h.getBoundingClientRect().top>y)break; at=+(h.dataset.line||h.dataset.lo||0)||at;}
  return at;}
// The section strip and the phone's position button for a Markdown document, which has no pages (updateSectionStrip's branch):
// the heading above the reading line is the outline's current entry and the strip's title; the button reads [L<line>/<lines>].
function mdStrip(){if(!isMdDoc())return; MD.at=mdReadingLine();
  let i=-1; MD.heads.forEach((h,j)=>{if(h.lo<=MD.at)i=j;}); if(i!==OUTLINE_SELECTED){OUTLINE_SELECTED=i; markOutline();}
  const h=MD.heads[i]; $('#section-current').textContent=h?h.title:tr('원문'); drawPos();}
let MD_STRIP_F=0; $('#left').addEventListener('scroll',()=>{if(!isMdDoc()||MD_STRIP_F)return; MD_STRIP_F=requestAnimationFrame(()=>{MD_STRIP_F=0; mdStrip();});},{passive:true});
// posLabel's shape for a Markdown document: [L37/164 ▾] - the reading line's source line of the file's lines, '–' for what is not
// known yet - with the document's name as posLabel puts it. Pure but for tl.
/** @param {string} doc @param {number} line @param {number} n @param {boolean} multi @param {boolean} wide */
function mdPosLabel(doc,line,n,multi,wide){const name=multi&&wide?doc:'',p=line||'–',m=n||'–';
  return {name,pages:'L'+p+'/'+m,label:name?tl('이동 · {doc} · {line} / {n}줄',{doc:name,line:p,n:m}):tl('이동 · {line} / {n}줄',{line:p,n:m})};}
// The empty list's help (#empty) speaks of dragging on the PDF; a Markdown document gets its own words, and a PDF document gets the
// page's own back (kept as served).
let MD_HINT_PDF=/** @type {Node[]|null} */(null);
function mdHint(){const e=$('#empty'); if(!e)return; if(!MD_HINT_PDF)MD_HINT_PDF=[...e.childNodes].map(n=>n.cloneNode(true));
  if(!isMdDoc()){if(e.dataset.md){e.replaceChildren(...MD_HINT_PDF.map(n=>n.cloneNode(true))); delete e.dataset.md;} return;}
  if(e.dataset.md)return; e.dataset.md='1';
  setHtml(e,html`<span class="t-mouse">${tr('글을')} <b>${tr('끌어')}</b> ${tr('고르면 그 줄을,')} <b>${tr('블록을 누르면')}</b> ${tr('그 블록을 고르고')}</span><span class="t-touch"><b>${tr('블록을 누르면')}</b> ${tr('그 블록을,')} <b>${tr('길게 눌러')}</b> ${tr('글을 고르면 그 줄을 고르고')}</span> ${tr('그 자리의')} <b>${tr('원문 줄 번호')}</b>${tr('가 핀의 위치가 됩니다.')}<br>
    ${tr('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${tr('를 누르면 도움말.')}</span><span class="t-touch">${tr('도움말은 [더보기]에 있습니다.')}</span>`);}
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
