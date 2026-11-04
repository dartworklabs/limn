// ------------------------------------------------ The Markdown surface (docs/handbook/viewer.md §Markdown 화면, ADR-0025)
// A document the browser draws from its source (rendersInBrowser: kind "markdown") has no pages. #doc holds one flowing column,
// article#md, drawn here; the panel, the list, the composer and the cards are the same as on the PDF surface.
// - GET /api/source answers the file as the server numbers it (str.splitlines(), already split, 1 MiB at most - over it 413
//   source_too_large and no lines). The lines this screen shows are the server's lines by construction: they are joined with
//   "\n" for the parser and never split again from raw bytes.
// - markdown-it parses in a worker of its own (GET /md-parse.mjs, this origin - no blob: worker, ADR-0026), within MD_LIMITS:
//   nesting, block and inline tokens there; elements while the DOM is built here, with a yield to the browser after every
//   MD_LIMITS.chunk units of work (a token, an inline child, a code line) wherever they fall; the time the worker takes.
//   Over any of them the screen is the plain source-line view (mdLineView), over MD_LIMITS.lines lines not even that, but a
//   notice with the count and the limit (mdNotice). Pins, cards and the agent's paths stay as they are.
// - The DOM is built with createElement and textContent only: markdown-it's HTML renderer is never used, so the one innerHTML
//   sink (markup.js setHtml) stays the only one. Raw HTML is never drawn: a block is a placeholder that keeps its lines, an
//   inline tag shows as code. An image is never fetched: its alt text stands in its place. A link opens only through the
//   allowlist (mdHref) - another origin's http(s), mailto, an in-document #heading; anything else is inert text.
// - Every block token's map becomes data-lo/data-hi on the element drawn for it. Inside a paragraph or heading each source
//   line gets its own span (data-line) only when the inline token's line breaks match its source's line ends (mdInlineLines);
//   otherwise the whole run is one span with its range. A code block's content lines are its source lines one for one.
// - A text selection (a mouse drag, a phone's long-press handles) becomes lines lo..hi; a tap or click on a block picks that
//   block. The ladder is: the chosen lines -> the block -> the heading's section (mdLevels). Saving is the ordinary POST
//   /api/pin, with no page, frac or pdf_build (the server drops them for this document anyway, ADR-0025 D2).
const MD_LIMITS=Object.freeze({nesting:20,blocks:30000,inlines:150000,elements:60000,ms:2000,lines:50000,chunk:2000});
// MD: the document drawn (doc, file, name), its source lines and the src_mtime they were read at (mtime: set only by a read
// that answered, so the light poll, polling.js, sees a failed read as not done), the src_mtime a redraw was last asked for
// (asked: the light poll asks once per change while that read is on its way, and a failed read clears it), the reading line
// (at), the limit hit (limit), its headings, the worker and its parse in flight,
// whether a redraw waits for a field (waiting), the elements built so far (els), the document #doc shows now (shown: '' for
// none - a PDF document's pages, the wait line) and the reading spot a kept view asks for once it is drawn (want).
const MD={gen:0,doc:/** @type {string|null} */(''),file:'',name:'',lines:/** @type {string[]} */([]),mtime:/** @type {number|null} */(null),
  asked:/** @type {number|null} */(null),at:0,limit:/** @type {string|null} */(null),
  heads:/** @type {{level:number,lo:number,el:HTMLElement,title:string,slug:string}[]} */([]),
  worker:/** @type {Worker|null} */(null),job:/** @type {{id:number,resolve:(r:any)=>void,t:ReturnType<typeof setTimeout>}|null} */(null),seq:0,
  waiting:false,els:0,shown:/** @type {string|null} */(''),want:/** @type {{line:number,off:number,top:number}|null} */(null),
  jumpTo:/** @type {{id:number,doc:string|null,seq:number}|null} */(null)};
// Whether the document on screen is drawn here (no pages), and whether pin p belongs to such a document of this instance.
function isMdDoc(){return !!META&&rendersInBrowser(META.kind);}
/** @param {Pin} p */
function isMdPin(p){const d=docInfo(pdoc(p)); return !!d&&rendersInBrowser(d.kind);}
// ---------------- The parse worker
// Parses text in the worker within MD_LIMITS -> {ok:true,tokens} or {ok:false,limit} (MD_LIMIT), or null when a newer parse
// took the worker over. The worker is started the first time and kept; one that runs past MD_LIMITS.ms, fails to load or is
// taken over is stopped (terminate) and a new one starts next time.
/** @param {string} text @returns {Promise<any>} */
function mdParse(text){mdParseStop(null);
  return new Promise(resolve=>{let w=MD.worker;
    try{if(!w){w=new Worker('/md-parse.mjs',{type:'module'}); MD.worker=w;
        w.onmessage=e=>{const j=MD.job; if(!j||!e.data||e.data.id!==j.id)return; clearTimeout(j.t); MD.job=null; j.resolve(e.data);};
        w.onerror=e=>{e.preventDefault(); mdParseStop({ok:false,limit:MD_LIMIT.LOAD});};}}
    catch(e){resolve({ok:false,limit:MD_LIMIT.LOAD}); return;}
    const id=++MD.seq; MD.job={id,resolve,t:setTimeout(()=>mdParseStop({ok:false,limit:MD_LIMIT.TIME}),MD_LIMITS.ms)};
    w.postMessage({id,text,limits:{nesting:MD_LIMITS.nesting,blocks:MD_LIMITS.blocks,inlines:MD_LIMITS.inlines}});});}
// Ends the parse in flight, if any, with result r (null: taken over), and stops its worker.
function mdParseStop(r){const j=MD.job; if(!j)return; MD.job=null; clearTimeout(j.t);
  if(MD.worker){MD.worker.terminate(); MD.worker=null;} j.resolve(r);}
// ---------------- Drawing the document
// A yield to the browser between chunks of the DOM build: a message, not a timer, so a test's frozen clock does not stop it.
function mdYield(){return new Promise(r=>{const c=new MessageChannel(); c.port1.onmessage=()=>r(undefined); c.port2.postMessage(0);});}
// Whether a redraw would take a text field from under the person typing in it: a field inside #doc that is composing, or held
// by the key that ended its composition (imeHeldIn, core.js §조합을 끝내는 키).
function mdFieldBusy(){const a=/** @type {HTMLElement|null} */(document.activeElement),held=imeHeldIn();
  const doc=$('#doc'),inDoc=(/** @type {any} */n)=>n instanceof Node&&doc.contains(n);
  return inDoc(held)||(!!a&&inDoc(a)&&a!==doc&&MD_COMPOSING.has(a));}
const MD_COMPOSING=new Set();
document.addEventListener('compositionstart',e=>{MD_COMPOSING.add(e.target);},true);
document.addEventListener('compositionend',e=>{MD_COMPOSING.delete(e.target);},true);
// Once that key lets its field go (IME_ON_FREE), a redraw that waited for it runs.
IME_ON_FREE.push(()=>{if(MD.waiting&&!mdFieldBusy()){MD.waiting=false; if(isMdDoc())mdBuild();}});
document.addEventListener('compositionend',()=>{if(MD.waiting)setTimeout(()=>{if(MD.waiting&&!mdFieldBusy()){MD.waiting=false; if(isMdDoc())mdBuild();}},0);});
// Draws the document on screen into #doc (buildDoc's branch for a browser-drawn document): its source, parsed in the worker
// and built here, or the line view or a notice when a limit is hit. A newer draw (another document, newer source) drops an
// older one at each wait. A redraw that would take a field being typed in waits until the field is let go (mdFieldBusy).
async function mdBuild(){if(mdFieldBusy()){MD.waiting=true; return;}
  const gen=++MD.gen,k=DOC,stale=()=>gen!==MD.gen||k!==DOC||!isMdDoc();
  document.body.classList.add('md-surface'); const doc=$('#doc');
  if(MD.shown!==k||!doc.querySelector('#md')){MD.shown=''; doc.replaceChildren(mdWait(tr('원문을 읽는 중입니다.')));}
  let r; try{r=await api(dq('/api/source'),{what:'원문 읽기',silent:true,expect:[413]});}
  catch(e){if(!stale()){MD.asked=null; MD.mtime=null; mdShow(mdNote(tr('원문을 읽지 못했습니다'),''));} return;}   // not read: no read answers for this source now (MD.mtime too, or an unchanged source on a return to the document never matches again), so the next light poll asks again
  if(stale())return;
  if(r.status===413){MD.lines=[]; MD.heads=[]; MD.mtime=MD.asked; mdShow(mdNote(tl('이 문서는 {size}라 그리지 않습니다(한도 {limit})',{size:mdMiB(r.data.bytes),limit:mdMiB(r.data.limit)}),MD_LIMIT.BYTES)); return;}
  const src=r.data; MD.doc=k; MD.mtime=src.src_mtime; MD.file=String(src.file||''); MD.name=MD.file.split('/').pop()||MD.file; MD.lines=Array.isArray(src.lines)?src.lines.map(String):[];
  const res=await mdParse(MD.lines.join('\n')); if(stale()||!res)return;
  let root=/** @type {HTMLElement|null} */(null),limit=res.ok?null:String(res.limit||MD_LIMIT.ERROR);
  if(res.ok){root=await mdRenderAll(res.tokens,stale); if(stale())return; if(!root)limit=MD_LIMIT.ELEMENTS;}
  if(!root){MD.heads=[];
    if(MD.lines.length>MD_LIMITS.lines){mdShow(mdNote(tl('이 문서는 원문이 {lines}줄이라 그리지 않습니다(한도 {limit}줄)',{lines:mdCount(MD.lines.length),limit:mdCount(MD_LIMITS.lines)}),MD_LIMIT.LINES)); return;}
    root=mdLineView(/** @type {string} */(limit));}
  mdShow(root);}
// Puts node in #doc, keeping the reading spot (the source line at the pane's top, and how far down it), then the marks, the
// outline, the strip and the chosen lines.
/** @param {HTMLElement} node */
function mdShow(node){const a=MD.want||(MD.shown===DOC?mdAnchor():null); MD.want=null; MD.limit=node.dataset.limit||null;
  $('#doc').replaceChildren(node); MD.shown=DOC; mdRestore(a);
  if(MD_RO)MD_RO.observe(node); mdOutline(); marks(); mdRelevel(); mdSelMark(COMPOSE.current); mdStrip();
  const j=MD.jumpTo; MD.jumpTo=null; if(j&&j.doc===DOC&&j.seq===SWITCHSEQ)mdJump(j.id);}   // a jump asked before the draw (mdJump)
// The line view offers the chosen lines alone (mdLineView): a pick of this document whose ladder came from the drawn document
// (a draft kept from before the parser failed) keeps its lines but takes the ladder a pick there gives - those lines, as lines.
function mdRelevel(){const d=COMPOSE.current; if(!d||REPICK||isRegion(d)||d.doc!==DOC||d.file!==MD.file||!$('#md.md-lines'))return;
  if((d.levels||[]).every(l=>l.level==='raw'&&l.lo===d.lo&&l.hi===d.hi))return;
  const r={lo:/** @type {number} */(d.lo),hi:/** @type {number} */(d.hi)}; d.levels=mdLevels(r,null,null); d.raw_lo=r.lo; d.raw_hi=r.hi; d.default_level='raw';
  useLevel(d,'raw'); renderComposer();}
function mdWait(text){const w=document.createElement('div'); w.className='md-wait dim'; w.textContent=text; return w;}
// A notice in the document's place (a limit hit before anything could be drawn, or a source not read): data-limit names the limit.
/** @param {string} text @param {string} limit */
function mdNote(text,limit){const n=document.createElement('div'); n.className='md-note'; n.id='md'; n.setAttribute('role','status'); n.textContent=text;
  if(limit)n.dataset.limit=limit; return n;}
// A size in MiB as the notices say it: '1.5 MiB', '1 MiB'.
function mdMiB(b){const m=(+b||0)/1048576; return (Math.round(m*10)/10).toLocaleString('en')+' MiB';}
function mdCount(n){return Number(n).toLocaleString('en');}
// The plain source-line view: every server line as a line span (data-line), numbered by CSS, under a line naming the limit
// that was hit. Pins, the composer and suggested edits work as ever; the ladder has the chosen lines only.
/** @param {string} limit @returns {HTMLElement} */
function mdLineView(limit){const root=document.createElement('article'); root.className='md md-lines'; root.id='md'; root.dataset.limit=limit; root.setAttribute('translate','no');
  const head=document.createElement('div'); head.className='md-limit'; head.setAttribute('role','status'); head.textContent=mdLimitText(limit); root.appendChild(head);
  const body=document.createElement('div'); body.className='md-src';
  MD.lines.forEach((ln,i)=>{const s=document.createElement('span'); s.className='ln'; s.dataset.line=String(i+1); s.textContent=ln+'\n'; body.appendChild(s);});
  root.appendChild(body); return root;}
// The line view's head line for limit (MD_LIMIT).
function mdLimitText(limit){switch(limit){
  case MD_LIMIT.NESTING:return tl('중첩이 {max}단을 넘어 원문 줄로 보입니다',{max:MD_LIMITS.nesting});
  case MD_LIMIT.BLOCKS:return tl('블록이 너무 많아 원문 줄로 보입니다(한도 {max}개)',{max:mdCount(MD_LIMITS.blocks)});
  case MD_LIMIT.INLINES:return tl('글 조각이 너무 많아 원문 줄로 보입니다(한도 {max}개)',{max:mdCount(MD_LIMITS.inlines)});
  case MD_LIMIT.ELEMENTS:return tl('그릴 요소가 너무 많아 원문 줄로 보입니다(한도 {max}개)',{max:mdCount(MD_LIMITS.elements)});
  case MD_LIMIT.TIME:return tl('읽는 데 {s}초가 넘게 걸려 원문 줄로 보입니다',{s:MD_LIMITS.ms/1000});
  case MD_LIMIT.LOAD:return tr('Markdown 파서를 불러오지 못해 원문 줄로 보입니다');
  default:return tr('Markdown을 읽지 못해 원문 줄로 보입니다');}}
// The elements that carry lines, in document order (line spans and blocks). Their tops never decrease in that order - a block
// precedes what it holds and stands no lower - so the one at a height is found by halving (mdAt), never by measuring them all.
function mdLineEls(){const md=$('#md'); return md?/** @type {HTMLElement[]} */([...md.querySelectorAll('[data-line],[data-lo]')]):[];}
// The last of els whose top is at or above y (viewport px), or null before the first. O(log n) measures.
/** @param {HTMLElement[]} els @param {number} y */
function mdAt(els,y){let lo=0,hi=els.length-1,at=-1; while(lo<=hi){const m=(lo+hi)>>1; if(els[m].getBoundingClientRect().top<=y){at=m; lo=m+1;} else hi=m-1;}
  return at<0?null:els[at];}
// The reading spot: the line span or block at the pane's top (mdAt), its first line and the px of it above that top.
function mdAnchor(){const L=$('#left'); if(!$('#md')||!MD.lines.length)return null; const top=L.getBoundingClientRect().top,e=mdAt(mdLineEls(),top);
  return e?{line:+(e.dataset.line||e.dataset.lo||0),off:top-e.getBoundingClientRect().top,top:L.scrollTop}:null;}
function mdRestore(a){const L=$('#left'); if(!a){return;} const e=mdLeaves(a.line,a.line)[0]; if(!e){L.scrollTop=a.top; return;}
  L.scrollTop+=e.getBoundingClientRect().top+a.off-L.getBoundingClientRect().top;}
// Builds article#md from the worker's tokens (mdRender), with a yield to the browser and a check for a newer draw whenever
// mdRender pauses, or null when the elements built pass MD_LIMITS.elements (stale(): a newer draw - then whatever was built
// is dropped too).
/** @param {any[]} tokens @param {()=>boolean} stale @returns {Promise<HTMLElement|null>} */
async function mdRenderAll(tokens,stale){const root=document.createElement('article'); root.className='md'; root.id='md'; root.setAttribute('translate','no');
  MD.els=0; MD.heads=[]; const work=mdRender(root,tokens);
  try{for(const pause of work){void pause; await mdYield(); if(stale())return null;}}
  catch(e){if(e===MD_OVER)return null; throw e;}
  return root;}
// The DOM build as a generator that pauses after every MD_LIMITS.chunk units of work - a token, an inline child, a code line,
// one block of a raw HTML run - counted on one counter (w, mdDue) wherever they fall: one paragraph of 120,000 inline tokens
// or one code block of 30,000 lines pauses inside itself. Two or more raw HTML blocks in a row are one run (mdHtmlRunEl).
/** @param {HTMLElement} root @param {any[]} tokens @returns {Generator<void,void,void>} */
function* mdRender(root,tokens){const r=mdRenderer(root),w={n:0};
  for(let i=0;i<tokens.length;i++){const t=tokens[i]; let j=i;
    while(t.type==='html_block'&&tokens[j+1]&&tokens[j+1].type==='html_block')j++;
    if(j>i){yield* r.run(tokens.slice(i,j+1),w); i=j;} else yield* r.token(t,w);
    if(mdDue(w))yield;}}
// One unit of work on counter w: true when MD_LIMITS.chunk of them have been done since the last pause (and the count restarts).
/** @param {{n:number}} w */
function mdDue(w){if(++w.n<MD_LIMITS.chunk)return false; w.n=0; return true;}
const MD_OVER={over:true};   // thrown by mdEl past MD_LIMITS.elements
// One element of the drawn document, counted against MD_LIMITS.elements.
/** @param {string} tag @returns {HTMLElement} */
function mdEl(tag){if(++MD.els>MD_LIMITS.elements)throw MD_OVER; return document.createElement(tag);}
/** @param {any} t @param {string} name @returns {string|null} */
function mdAttr(t,name){const a=(t&&t.attrs)||[]; for(const x of a)if(x[0]===name)return String(x[1]); return null;}
// The lines lo..hi of a block token's map, its trailing blank lines left out (a loose list item's map runs over them).
function mdSpan(t){if(!t.map)return null; let lo=t.map[0]+1,hi=Math.max(lo,t.map[1]);
  while(hi>lo&&!String(MD.lines[hi-1]||'').trim())hi--; return {lo,hi};}
function mdMap(el,t,kind){const s=mdSpan(t); if(!s)return; el.dataset.lo=String(s.lo); el.dataset.hi=String(s.hi); el.dataset.kind=kind;}
const MD_KIND={paragraph_open:'paragraph',heading_open:'heading',bullet_list_open:'list',ordered_list_open:'list',list_item_open:'item',
  blockquote_open:'quote',table_open:'table',tr_open:'row'};
// A renderer into root for markdown-it's token stream, one token at a time: block tokens nest by `nesting`, an inline token's
// children are drawn by mdInline. A paragraph markdown-it hides (a tight list's) puts its text straight into the list item.
/** @param {HTMLElement} root */
function mdRenderer(root){const stack=[root];
  /** @param {any} t @param {{n:number}} w @returns {Generator<void,void,void>} */
  function* token(t,w){const top=stack[stack.length-1];
    if(t.nesting===1){
      if(t.hidden){stack.push(top); return;}
      const tag=/^[a-z][a-z0-9]*$/.test(t.tag||'')?t.tag:'div',el=mdEl(tag),kind=MD_KIND[t.type]; if(kind)mdMap(el,t,kind);
      if(t.type==='ordered_list_open'){const s=mdAttr(t,'start'); if(s&&/^\d{1,9}$/.test(s))el.setAttribute('start',s);}
      if(t.type==='th_open'||t.type==='td_open'){const m=/^text-align:(left|right|center)$/.exec(mdAttr(t,'style')||''); if(m)el.classList.add('md-al-'+m[1]);}
      if(t.type==='heading_open'&&t.map){el.id='md-h'+(t.map[0]+1); MD.heads.push({level:+tag.slice(1)||1,lo:t.map[0]+1,el,title:'',slug:''});}
      top.appendChild(el); stack.push(el); return;}
    if(t.nesting===-1){if(stack.length>1)stack.pop(); return;}
    if(t.type==='inline'){yield* mdInline(t,top,w); const h=MD.heads[MD.heads.length-1]; if(h&&h.el===top){h.title=(top.textContent||'').trim(); h.slug=mdSlug(h.title);} return;}
    if(t.type==='fence'||t.type==='code_block'){const pre=mdEl('pre'),code=mdEl('code'); mdMap(pre,t,'code');
      const lang=String(t.info||'').trim().split(/\s+/)[0]; if(lang)pre.dataset.lang=lang.slice(0,40);
      const first=t.map?t.map[0]+1+(t.type==='fence'?1:0):0;
      pre.appendChild(code); top.appendChild(pre);
      const lines=t.content?String(t.content).replace(/\n$/,'').split('\n'):[];
      for(let i=0;i<lines.length;i++){const s=mdEl('span'); s.className='ln'; if(first)s.dataset.line=String(first+i); s.textContent=lines[i]+'\n'; code.appendChild(s); if(mdDue(w))yield;}
      return;}
    if(t.type==='hr'){const hr=mdEl('hr'); mdMap(hr,t,'rule'); top.appendChild(hr); return;}
    if(t.type==='html_block')top.appendChild(mdHtmlBox(t));}
  // A run of raw HTML blocks in a row (mdHtmlRunEl), or each block on its own when one has no lines.
  /** @param {any[]} ts @param {{n:number}} w @returns {Generator<void,void,void>} */
  function* run(ts,w){const spans=ts.map(mdSpan); if(spans.some(s=>!s)){for(const t of ts){yield* token(t,w); if(mdDue(w))yield;} return;}
    const el=mdHtmlRunEl(ts.length,/** @type {{lo:number,hi:number}} */(spans[0]).lo,/** @type {{lo:number,hi:number}} */(spans[spans.length-1]).hi),body=/** @type {HTMLElement} */(el.lastChild);
    stack[stack.length-1].appendChild(el);
    for(const t of ts){const b=mdHtmlBox(t); mdHtmlHold(b,false); body.appendChild(b); if(mdDue(w))yield;}}
  return {token,run};}
// A raw HTML block's placeholder: its lines (it takes a pin), their count and its first line as code, never the HTML itself.
/** @param {any} t @returns {HTMLElement} */
function mdHtmlBox(t){const box=mdEl('div'); mdMap(box,t,'html'); box.className='md-html';
  const sp=mdSpan(t),n=sp?sp.hi-sp.lo+1:0,first=String(t.content||'').split('\n').find(l=>l.trim())||'';
  const lab=mdEl('span'); lab.className='md-html-l'; lab.textContent=tl('HTML {lines}줄 · 그리지 않습니다',{lines:n});
  const code=mdEl('code'); code.textContent=first.trim().slice(0,120); box.append(lab,code); return box;}
// Two or more raw HTML blocks in a row (a README's head of badges and pictures) are one placeholder, closed: a button naming
// the blocks and their lines (HTML 블록 N개 · M줄) that opens it (mdHtmlRun), each block then its own placeholder that takes a
// pin. Only what is on screen carries lines (data-lo/hi): closed, the run stands for all its lines as one HTML block; open, each
// block for its own (mdHtmlHold keeps the other's in data-r-lo/hi). So the marks, the picks, the ladder and the reading line
// read whatever is shown and nothing hidden.
/** @param {number} n @param {number} lo @param {number} hi @returns {HTMLElement} */
function mdHtmlRunEl(n,lo,hi){const el=mdEl('div'); el.className='md-html-run'; el.dataset.rLo=String(lo); el.dataset.rHi=String(hi); el.dataset.kind='html'; mdHtmlHold(el,true);
  const b=/** @type {HTMLButtonElement} */(mdEl('button')); b.type='button'; b.className='md-html-sum'; b.dataset.act='md-html-run'; b.setAttribute('aria-expanded','false');
  setHtml(b,html`${ic('chevron-right')}<span>${tl('HTML 블록 {n}개 · {lines}줄 · 그리지 않습니다',{n,lines:hi-lo+1})}</span>`);   // the chevron turns down when open (CSS)
  const body=mdEl('div'); body.className='md-html-body'; body.hidden=true; el.append(b,body); return el;}
// Shows (on) or hides (off) element e's lines: data-lo/hi from its kept data-r-lo/hi, or none.
/** @param {HTMLElement} e @param {boolean} on */
function mdHtmlHold(e,on){if(!e.dataset.rLo){e.dataset.rLo=e.dataset.lo||''; e.dataset.rHi=e.dataset.hi||'';}
  if(on){e.dataset.lo=e.dataset.rLo; e.dataset.hi=e.dataset.rHi||'';} else{delete e.dataset.lo; delete e.dataset.hi;}}
// Opens or closes the run of raw HTML blocks whose button btn is (data-act md-html-run), then draws the marks, the chosen lines
// and the strip again over what is shown.
/** @param {HTMLElement} btn */
function mdHtmlRun(btn){const run=/** @type {HTMLElement|null} */(btn.closest('.md-html-run')),body=run&&/** @type {HTMLElement|null} */(run.querySelector('.md-html-body')); if(!run||!body)return;
  const open=btn.getAttribute('aria-expanded')!=='true'; mdHtmlHold(run,!open); body.querySelectorAll('.md-html').forEach(e=>mdHtmlHold(/** @type {HTMLElement} */(e),open));
  body.hidden=!open; btn.setAttribute('aria-expanded',String(open));
  mdMarks(); mdSelMark(COMPOSE.current); mdStrip();}
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
// A table cell's inline token has no map: its span carries nothing and the row's range stands for it.
/** @param {any} t @param {HTMLElement} parent @param {{n:number}} w @returns {Generator<void,void,void>} */
function* mdInline(t,parent,w){const m=mdInlineLines(t),kids=t.children||[];
  const mk=(/** @type {number} */line)=>{const s=mdEl('span'); s.className='ln';
    if(m.exact)s.dataset.line=String(line); else if(m.lo){s.dataset.lo=String(m.lo); s.dataset.hi=String(m.hi); s.dataset.kind='lines';}
    parent.appendChild(s); return s;};
  let stack=/** @type {HTMLElement[]} */([mk(m.lo)]);
  for(let i=0;i<kids.length;i++){const c=kids[i],top=stack[stack.length-1];
    switch(c.type){
      case 'text':top.appendChild(document.createTextNode(c.content)); break;
      case 'code_inline':{const e=mdEl('code'); e.textContent=c.content; top.appendChild(e); break;}
      case 'softbreak':case 'hardbreak':
        top.appendChild(c.type==='hardbreak'?mdEl('br'):document.createTextNode('\n'));
        if(m.exact){const next=[mk(m.lines[i]+1)];
          for(const e of stack.slice(1)){const k=/** @type {HTMLElement} */(e.cloneNode(false)); ++MD.els; next[next.length-1].appendChild(k); next.push(k);}
          stack=next;}
        break;
      case 'strong_open':case 'em_open':case 's_open':{const e=mdEl(c.type==='strong_open'?'strong':c.type==='em_open'?'em':'s'); top.appendChild(e); stack.push(e); break;}
      case 'link_open':{const e=mdLink(mdAttr(c,'href')); top.appendChild(e); stack.push(e); break;}
      case 'strong_close':case 'em_close':case 's_close':case 'link_close':if(stack.length>1)stack.pop(); break;
      case 'image':{const e=mdEl('span'); e.className='md-img';
        e.textContent=tr('그림')+': '+(c.content||mdAttr(c,'alt')||mdAttr(c,'src')||'');
        const src=String(mdAttr(c,'src')||''); e.dataset.tip=tl('그림은 불러오지 않습니다 · {src}',{src}); e.dataset.tipUrl=src; top.appendChild(e); break;}
      case 'html_inline':{const e=mdEl('code'); e.className='md-html-in'; e.textContent=c.content; top.appendChild(e); break;}
      default:if(c.content)top.appendChild(document.createTextNode(c.content));}
    if(mdDue(w))yield;}}
// ---------------- Links: the allowlist
// What a link in the document may do (pure; origin is the viewer page's location.origin). Every link token comes here - an
// ordinary link, an autolink, a reference link - and this allowlist is the gate. markdown-it's own validateLink is a denylist
// (javascript:, vbscript:, file:, data: but data:image/gif|png|jpeg|webp) and lets ftp:, any custom scheme and those images
// through, so it is not relied on.
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
// goes to the heading it names (data-act md-anchor: a click or Enter, the global key handler asking imeKey first); anything
// else is inert text with its target in the tip.
function mdLink(href){const r=mdHref(href,location.origin);
  if(r.open==='web'||r.open==='mail'){const a=/** @type {HTMLAnchorElement} */(mdEl('a')); a.href=r.href; a.target='_blank'; a.rel='noopener noreferrer'; a.dataset.tip=r.href; a.dataset.tipUrl=r.href; return a;}
  if(r.open==='anchor'){const a=mdEl('a'); a.className='md-anchor'; a.dataset.act='md-anchor'; a.dataset.anchor=r.id||''; a.setAttribute('role','link'); a.tabIndex=0; return a;}
  // A link that does not open: a disabled link to assistive technology, reachable by Tab (the focus shows its description, as
  // a hover does), and a tap shows the description instead of picking the block (mdSelectionPick).
  const s=mdEl('span'),tip=tl('이 링크는 열지 않습니다 · {href}',{href:r.href}); s.className='md-rel'; s.dataset.tip=tip; s.dataset.tipUrl=r.href;
  s.tabIndex=0; s.setAttribute('role','link'); s.setAttribute('aria-disabled','true'); s.setAttribute('aria-description',tip); return s;}
// GitHub's heading slug: lower case, punctuation dropped, spaces to '-'. Pure.
function mdSlug(s){return String(s).trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu,'').replace(/\s/g,'-');}
// An in-document link to '#id': the first heading whose slug is id (or id percent-decoded), as GitHub numbers repeats
// (slug, slug-1, ...). Nothing when no heading has it.
/** @param {HTMLElement} a */
function mdGoAnchor(a){let want=String(a.dataset.anchor||''); try{want=decodeURIComponent(want);}catch(e){} want=want.toLowerCase();
  const seen=new Map(); let at=-1;
  MD.heads.forEach((h,i)=>{if(at>=0)return; const n=seen.get(h.slug)||0; seen.set(h.slug,n+1); if((n?h.slug+'-'+n:h.slug)===want)at=i;});
  if(at>=0)mdGoHeading(at);}
// ---------------- Picking: selection -> lines, and the ladder
// The lines a DOM point is on: its line span's, else its nearest block's range, else null (outside the document).
function mdRangeAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  const md=$('#md'); if(!md||!md.contains(e))return null;
  const ln=e.closest('[data-line]'); if(ln&&md.contains(ln)){const n=+(/** @type {HTMLElement} */(ln).dataset.line||0); if(n)return {lo:n,hi:n};}
  const b=/** @type {HTMLElement|null} */(e.closest('[data-lo]')); return b&&md.contains(b)?{lo:+(b.dataset.lo||0),hi:+(b.dataset.hi||0)}:null;}
// The block a point belongs to for the ladder's second rung: a table row's table, a list item's or a quote's paragraph's item or
// quote, else its nearest
// block (a run of text whose lines could not be told - kind 'lines', mdInline - stands for the block it is in).
function mdBlockAt(node){const e=node&&(node.nodeType===1?/** @type {Element} */(node):node.parentElement); if(!e)return null;
  let b=/** @type {HTMLElement|null} */(e.closest('#md [data-lo]')); if(b&&b.dataset.kind==='lines'&&b.parentElement)b=/** @type {HTMLElement|null} */(b.parentElement.closest('#md [data-lo]')); if(!b)return null;
  if(b.dataset.kind==='row')b=/** @type {HTMLElement|null} */(b.closest('table[data-lo]'))||b;
  else if(b.dataset.kind==='paragraph'&&b.parentElement&&/^(item|quote)$/.test(b.parentElement.dataset.kind||''))b=b.parentElement;   // a list item's or a quote's own paragraph is that block
  // A heading or a rule is no block of its own (ADR-0025 D3's block kinds): the block it stands in, if any, is.
  while(b&&!MD_BLOCK_KINDS.includes(b.dataset.kind||''))b=b.parentElement?/** @type {HTMLElement|null} */(b.parentElement.closest('#md [data-lo]')):null;
  return b;}
// The block kinds a block rung takes (its pin kind is md:<kind>, ADR-0025 D3) and their names on the ladder.
const MD_BLOCK_KINDS=['paragraph','item','table','code','quote','html'];
const MD_BLOCK_SEL=MD_BLOCK_KINDS.map(k=>'[data-lo][data-kind="'+k+'"]').join(',');
// The blocks lines lo..hi meet, outermost: each element of a block kind on screen whose lines meet lo..hi and that no other such
// element meeting them holds (a quote's paragraphs are the quote; a list's items are each a block).
function mdBlocksIn(lo,hi){const md=$('#md'); if(!md)return []; const meets=(/** @type {HTMLElement} */e)=>+(e.dataset.lo||0)<=hi&&+(e.dataset.hi||0)>=lo;
  return /** @type {HTMLElement[]} */([...md.querySelectorAll(MD_BLOCK_SEL)]).filter(e=>{if(!meets(e))return false;
    const up=/** @type {HTMLElement|null} */(e.parentElement&&e.parentElement.closest(MD_BLOCK_SEL)); return !(up&&md.contains(up)&&meets(up));});}
const MD_BLOCK_LABEL={'paragraph':'문단','item':'목록 항목','table':'표','code':'코드 블록','quote':'인용','html':'HTML 블록'};
function mdSnippet(lo,hi){const out=[]; for(let n=lo;n<=Math.min(hi,lo+79);n++)out.push(String(n).padStart(5,' ')+'  '+(MD.lines[n-1]||''));
  if(hi-lo+1>80)out.push('      … '+tl('{n}줄 더',{n:hi-lo+1-80})); return out.join('\n');}
// The section around lines lo..hi: from the nearest heading at or above lo to the line before the next heading of the same or a
// higher level (the file's end when none), its trailing blank lines left out. null above the first heading, or when hi is past it.
function mdSection(lo,hi){let h=/** @type {{level:number,lo:number,title:string}|null} */(null); for(const x of MD.heads){if(x.lo<=lo)h=x; else break;} if(!h)return null;
  let end=MD.lines.length; for(const x of MD.heads){if(x.lo>h.lo&&x.level<=h.level){end=x.lo-1; break;}}
  while(end>h.lo&&!String(MD.lines[end-1]||'').trim())end--; if(end<hi)return null; return {lo:h.lo,hi:end,title:h.title};}
// The ladder for lines r (a drag or a tap) and the blocks its start and end are in (mdBlockAt): the chosen lines, the block when
// both ends are in one - else, when they meet two or more blocks (mdBlocksIn), those blocks whole ('블록 N개', level blocks:
// saved as lines, kindFor) - and the heading's section; a rung with the range of one before it merges into that one. A block
// rung carries its block kind as env (kindFor: md:<kind>). A tap (tapped) picks its block: when the block is no more than the
// tapped lines (an HTML block, a one-line paragraph) its rung stands first and the chosen lines merge into it, so the pin is
// md:<kind> as any other tapped block's - merged the other way, the tap's block was saved as lines.
/** @param {{lo:number,hi:number}} r @param {HTMLElement|null} b0 @param {HTMLElement|null} b1 @param {boolean} [tapped] */
function mdLevels(r,b0,b1,tapped){const ls=/** @type {any[]} */([]); const add=(level,label,lo,hi,env)=>{const same=ls.find(l=>l.lo===lo&&l.hi===hi);
    if(same){(same.merged=same.merged||[]).push(level); return;} ls.push({level,label,lo,hi,n:hi-lo+1,snippet:mdSnippet(lo,hi),env:env||null});};
  const k=b0&&b0===b1?b0.dataset.kind||'paragraph':'',blo=b0?Math.min(+(b0.dataset.lo||0),r.lo):0,bhi=b0?Math.max(+(b0.dataset.hi||0),r.hi):0;
  const blockFirst=!!(tapped&&k&&blo===r.lo&&bhi===r.hi); if(blockFirst)add('block',MD_BLOCK_LABEL[k]||'블록',blo,bhi,k);
  add('raw','고른 줄',r.lo,r.hi,null);
  if(k){if(!blockFirst)add('block',MD_BLOCK_LABEL[k]||'블록',blo,bhi,k);}
  else{const bs=mdBlocksIn(r.lo,r.hi); if(bs.length>1)add('blocks',tl('블록 {n}개',{n:bs.length}),Math.min(r.lo,...bs.map(e=>+(e.dataset.lo||0))),Math.max(r.hi,...bs.map(e=>+(e.dataset.hi||0))),null);}
  const s=mdSection(r.lo,r.hi); if(s)add('section',tr('절')+' · '+(s.title.length>18?s.title.slice(0,18)+'…':s.title),s.lo,s.hi,null);
  return ls;}
// Fills the composer with lines r of the document on screen, as pick() does with a /api/pick answer; tapped: a tap picked a
// block, so the block rung is the default (the section rung on a heading). During a re-place it is the candidate instead
// (bannerCompare), with nothing else changed.
function mdPick(r,b0,b1,quote,tapped){const levels=mdLevels(r,b0,b1,tapped),q=String(quote||'').replace(/\s+/g,' ').trim().slice(0,160);
  const head=tapped&&MD.heads.some(h=>h.lo===r.lo&&h.lo===r.hi);
  const def=tapped&&lvOf({levels},head?'section':'block')?(head?'section':'block'):'raw';
  const sel=/** @type {Selection} */(/** @type {unknown} */({doc:DOC,file:MD.file,name:MD.name,lo:r.lo,hi:r.hi,raw_lo:r.lo,raw_hi:r.hi,kind:'lines',
    score:null,warn:null,snippet:mdSnippet(r.lo,r.hi),levels,default_level:def,n_lines:MD.lines.length,quote:q,overlaps:[]}));
  if(REPICK){REPICK.cand=sel; bannerCompare(); return;}
  endTopic(NOTICE_TOPIC.PICK); PICKSEQ++;
  COMPOSE.current=sel; COMPOSE.intent++; COMPOSE.picking=false; sel.scope=null; sel.elSel=null; useLevel(sel,def);
  $('#composer').hidden=false; setBusy(false); $('#c-err').hidden=true; $('#c-body').hidden=false;
  setSide(true); applySide(); COMPOSE.dismissedOverlap=null; sel.overlaps=overlapsFor(sel,PINS); SNIP_OPEN=false;
  renderComposer(); renderVerdictRow(); $('#composer').scrollTop=0; if(LAYOUT!==LAYOUT_MODE.WIDE)$('#right').scrollTop=0;
  revealBox(/** @type {HTMLElement|null} */(document.querySelector('#md .md-sel')));   // the chosen lines out from under the sheet (compact), as a PDF box is
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});}
// The ladder of an edit card on a pin of this document: its lines' rungs from the drawn document (mdLevels), or none when the
// document on screen is another or is not drawn (the line view, a notice) - the card then keeps the lines it has.
/** @param {{doc?:string|null,lo?:number|null,hi?:number|null}} E */
function mdEditLevels(E){if(!isMdDoc()||E.doc!==DOC||typeof E.lo!=='number'||typeof E.hi!=='number')return null;
  const a=mdLeaves(E.lo,E.lo)[0],b=mdLeaves(E.hi,E.hi)[0]; if(!a&&!b)return null;
  const ls=mdLevels({lo:E.lo,hi:E.hi},a?mdBlockAt(a):null,b?mdBlockAt(b):null); return ls.length>1?ls:null;}
// The chosen lines drawn on the document: their line spans and blocks get .md-sel (null clears).
function mdSelMark(d){$$('#md .md-sel').forEach(e=>e.classList.remove('md-sel')); if(!d||!isMdDoc()||d.file!==MD.file||isRegion(d))return;
  mdLeaves(/** @type {number} */(d.lo),/** @type {number} */(d.hi)).forEach(e=>e.classList.add('md-sel'));}
// The elements that stand for lines lo..hi: each line span in range, and each block in range that has no line spans of its own
// and no smaller block in range (a rule, an HTML block) - the smallest things on screen that carry those lines. A table cell's
// line stands for its row: the row is what is tinted, so a pinned row reads as one band.
function mdLeaves(lo,hi){const md=$('#md'); if(!md)return [];
  const lines=[...md.querySelectorAll('[data-line]')].filter(e=>{const n=+(/** @type {HTMLElement} */(e).dataset.line||0); return n>=lo&&n<=hi;});
  const blocks=[...md.querySelectorAll('[data-lo]')].filter(e=>{const h=/** @type {HTMLElement} */(e),a=+(h.dataset.lo||0),b=+(h.dataset.hi||0);
    return a<=hi&&b>=lo&&!h.querySelector('[data-line],[data-lo]');});
  const out=new Set(); for(const e of [...lines,...blocks]){const row=e.closest('tr[data-lo]'); out.add(row&&md.contains(row)?row:e);}
  return /** @type {HTMLElement[]} */([...out]);}
// ---------------- Pins on the document
// The marks of the pins on screen (marks()' branch): each pin's lines get .md-pin (review .rv, lost .st), and the first of them a
// number badge in the left gutter that jumps to the card (data-act mark-jump, as on a PDF page).
function mdMarks(){const md=$('#md'); if(!md)return;
  md.querySelectorAll('.md-badges').forEach(e=>e.remove()); md.querySelectorAll('.md-pin').forEach(e=>e.classList.remove('md-pin','rv','st'));
  const pins=PINS.concat(REVIEW_ALL.filter(p=>pdoc(p)===DOC)).filter(p=>!isRegion(p)&&typeof p.lo==='number'&&typeof p.hi==='number');
  const rows=/** @type {Map<number,HTMLElement>} */(new Map()),top=md.getBoundingClientRect().top;
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
// Scrolls pin id's first line to the reading depth and flashes its lines (jumpPin's branch). A jump asked before this
// document is on screen - [보기] on a pin of another document: switchDoc settles before the source is read and drawn - waits
// for the draw (mdShow) of this visit; another switch drops it.
function mdJump(id){if(MD.shown!==DOC||!$('#md')){MD.jumpTo={id,doc:DOC,seq:SWITCHSEQ}; return;}
  const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id); if(!p||typeof p.lo!=='number'||typeof p.hi!=='number')return;
  const leaves=mdLeaves(p.lo,p.hi); if(!leaves.length)return; const L=$('#left'),lr=L.getBoundingClientRect(),r=leaves[0].getBoundingClientRect();
  pvShow(); L.scrollTop+=(r.top-(lr.top+lr.height*0.30)); leaves.forEach(e=>{e.classList.remove('md-flash'); void e.offsetWidth; e.classList.add('md-flash');});
  setTimeout(()=>leaves.forEach(e=>e.classList.remove('md-flash')),1200);}
// ---------------- Outline from headings, the strip and the position button
function mdOutline(){OUTLINE_DOC=DOC; OUTLINE_BUILD=(META&&META.pages_build)||''; OUTLINE_CUT=0;
  OUTLINE_ENTRIES=MD.heads.map((h,i)=>({title:h.title,number:'',depth:Math.max(0,h.level-1),page:i+1,pageLabel:'L'+h.lo,frac:0,up:-1}));
  OUTLINE_SELECTED=-1; renderOutline();}
// The source line at the reading line (readingDepth under the pane's top): the last line span or block, in document order, whose
// top is at or above it. 0 before the document is drawn.
function mdReadingLine(){const L=$('#left'); if(!$('#md'))return 0; const e=mdAt(mdLineEls(),L.getBoundingClientRect().top+readingDepth(L));
  return e?+(e.dataset.line||e.dataset.lo||0):0;}
// The section strip and the phone's position button (updateSectionStrip's branch): the heading above the reading line is the
// outline's current entry and the strip's title; the button reads [L<line>/<lines>].
function mdStrip(){if(!isMdDoc())return; MD.at=mdReadingLine();
  let i=-1; MD.heads.forEach((h,j)=>{if(h.lo<=MD.at)i=j;}); if(i!==OUTLINE_SELECTED){OUTLINE_SELECTED=i; markOutline();}
  const h=MD.heads[i]; $('#section-current').textContent=h?h.title:tr('문서 처음'); drawPos();}   // above the first heading
let MD_STRIP_F=0; $('#left').addEventListener('scroll',()=>{if(!isMdDoc()||MD_STRIP_F)return; MD_STRIP_F=requestAnimationFrame(()=>{MD_STRIP_F=0; mdStrip();});},{passive:true});
// posLabel's shape for this document: [L37/164 ▾] - the reading line's source line of the file's lines, '–' for what is not
// known yet - with the document's name as posLabel puts it. Pure but for tl.
/** @param {string} doc @param {number} line @param {number} n @param {boolean} multi @param {boolean} wide */
function mdPosLabel(doc,line,n,multi,wide){const name=multi&&wide?doc:'',p=line||'–',m=n||'–';
  return {name,pages:'L'+p+'/'+m,label:name?tl('이동 · {doc} · {line} / {lines}줄',{doc:name,line:p,lines:m}):tl('이동 · {line} / {lines}줄',{line:p,lines:m})};}
// The empty list's help (#empty) speaks of dragging on the PDF; this document gets its own words, and a PDF document the page's
// own back (kept as served).
let MD_HINT_PDF=/** @type {Node[]|null} */(null);
function mdHint(){const e=$('#empty'); if(!e)return; if(!MD_HINT_PDF)MD_HINT_PDF=[...e.childNodes].map(n=>n.cloneNode(true));
  if(!isMdDoc()){if(e.dataset.md){e.replaceChildren(...MD_HINT_PDF.map(n=>n.cloneNode(true))); delete e.dataset.md;} return;}
  if(e.dataset.md)return; e.dataset.md='1';
  setHtml(e,html`<span class="t-mouse">${tr('글을')} <b>${tr('끌어')}</b> ${tr('고르면 그 줄을,')} <b>${tr('블록을 누르면')}</b> ${tr('그 블록을 고르고')}</span><span class="t-touch"><b>${tr('블록을 누르면')}</b> ${tr('그 블록을,')} <b>${tr('길게 눌러')}</b> ${tr('글을 고르면 그 줄을 고르고')}</span> ${tr('그 자리의')} <b>${tr('원문 줄 번호')}</b>${tr('가 핀의 위치가 됩니다.')}<br>
    ${tr('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${tr('를 누르면 도움말.')}</span><span class="t-touch">${tr('도움말은 [더보기]에 있습니다.')}</span>`);}
function mdGoHeading(i){const h=MD.heads[i]; if(!h)return; OUTLINE_SELECTED=i; markOutline();
  const L=$('#left'),lr=L.getBoundingClientRect(),r=h.el.getBoundingClientRect(); pvShow(); L.scrollTo({top:L.scrollTop+r.top-lr.top-8,behavior:SMOOTH});}
// ---------------- Input on the document
// A mouse drag ends: the part of its text selection inside the document (mdDocPart) is the pick. A press without a selection (a click, a tap) picks the
// block under it - not on a link, a badge or another control.
function mdSelectionPick(tapTarget){const s=window.getSelection(),md=$('#md'); if(!md||!md.matches('article'))return false;
  if(s&&!s.isCollapsed&&s.rangeCount){const r0=s.getRangeAt(0),r=mdDocPart(r0,md); if(!r)return false;
    let a=mdRangeAt(r.startContainer),b=mdRangeAt(r.endContainer); if(!a||!b)return false;
    // A selection that ends before any character of its last line (a triple click ends at the start of the next block) does
    // not take that line: nothing of it is selected. An end mdDocPart cut back to the document's last element is no such end -
    // the selection ran past that element, which may have no character of its own (a closing rule, an empty code block).
    const cut=r!==r0&&!md.contains(r0.endContainer);
    if(b.lo>a.hi&&!cut&&mdNothingOfEnd(r)){const prev=b.lo-1; b={lo:Math.max(a.lo,prev),hi:Math.max(a.lo,prev)};}
    let lo=Math.min(a.lo,b.lo),hi=Math.max(a.hi,b.hi); while(hi>lo&&!String(MD.lines[hi-1]||'').trim())hi--;
    mdPick({lo,hi},mdBlockAt(r.startContainer),mdBlockAt(r.endContainer),r===r0?s.toString():r.toString(),false); return true;}
  if(tapTarget){const t=/** @type {Element} */(tapTarget);
    const rel=/** @type {HTMLElement|null} */(t.closest('#md .md-rel')); if(rel&&LAST_PTR!=='mouse'){mdRelTip(rel); return true;}   // a finger has no hover
    if(t.closest('a,button,[data-act],.md-badges,.md-limit'))return false;
    const b=/** @type {HTMLElement|null} */(t.closest('#md [data-lo],#md [data-line]')); if(!b)return false;
    const head=MD.heads.find(h=>h.el===t.closest('#md h1,#md h2,#md h3,#md h4,#md h5,#md h6'));
    const r=head?{lo:head.lo,hi:head.lo}:mdRangeAt(t)||{lo:+(b.dataset.lo||0),hi:+(b.dataset.hi||0)},blk=mdBlockAt(t);
    mdPick(r,blk,blk,(blk||b).innerText||'',true); return true;}
  return false;}
// The part of selection range r inside the document md: r itself when it lies inside; else r cut back to the document's first
// and last line elements where it runs past them - a triple click on the last paragraph ends after the article, there being no
// next block inside it to end at, and a drag may start above it. One end must be in the document: a selection with both ends
// outside it (select-all, one made in the side panel) is no pick, as before - null, as for one that does not reach it or one
// that, cut back, takes nothing of it (from above the document to its very start).
/** @param {Range} r @param {HTMLElement} md */
function mdDocPart(r,md){if(md.contains(r.commonAncestorContainer))return r; if(!md.contains(r.startContainer)&&!md.contains(r.endContainer))return null;
  const els=mdLineEls(); if(!els.length)return null;
  const c=r.cloneRange(); if(!md.contains(r.startContainer))c.setStart(els[0],0);
  if(!md.contains(r.endContainer)){const e=els[els.length-1]; c.setEnd(e,e.childNodes.length);}
  return c.collapsed?null:c;}
// Shows a link's description that does not open (a tap on it), until 4s pass or the next press.
/** @param {HTMLElement} el */
function mdRelTip(el){showTip(el); const txt=TIP.textContent; setTimeout(()=>{if(!TIP.hidden&&TIP.textContent===txt)hideTip();},4000);}
// Whether range r takes no visible character of the line (or block) its end is in.
function mdNothingOfEnd(r){const e=r.endContainer.nodeType===1?/** @type {Element} */(r.endContainer):r.endContainer.parentElement; if(!e)return false;
  const host=e.closest('[data-line]')||e.closest('[data-lo]'); if(!host)return false;
  const head=document.createRange(); head.setStart(host,0); head.setEnd(r.endContainer,r.endOffset); return !head.toString().trim();}
// A release's pick waits one task, for the selection its press made, and it is that press's alone: once the next press is down (a
// double or triple click's next press, which a busy page takes ahead of the timer) it does nothing - that press picks at its own
// release. Run then, it took the new press's selection and the note field's focus took that selection away, so the click that
// followed counted as a tap and chose the block. MD_PRESS counts the document's primary presses.
let MD_PRESS=0;
$('#doc').addEventListener('mousedown',e=>{if(e.button===0)MD_PRESS++;});
$('#doc').addEventListener('mouseup',e=>{if(!isMdDoc()||e.button!==0)return; const press=MD_PRESS; setTimeout(()=>{if(press===MD_PRESS)mdSelectionPick(null);},0);});
$('#doc').addEventListener('click',e=>{if(!isMdDoc())return; const s=window.getSelection(); if(s&&!s.isCollapsed)return; mdSelectionPick(e.target);});
// A finger: the long-press handles make a selection with no mouseup; it is picked once it rests.
let MD_SEL_T=0;
document.addEventListener('selectionchange',()=>{if(!isMdDoc()||!MQ_COARSE.matches)return; clearTimeout(MD_SEL_T);
  MD_SEL_T=setTimeout(()=>{const s=window.getSelection(); if(s&&!s.isCollapsed)mdSelectionPick(null);},500);});
