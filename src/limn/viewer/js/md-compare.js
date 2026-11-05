// ------------------------------------------------ The rendered compare of a Markdown document ([그린 비교], the changes view)
// docs/superpowers/specs/2026-11-05-markdown-rendered-compare.md. The document's own file on the two sides the source diff
// compares (GET /api/revision-source: the commit's first parent and the commit, or a range's old side and its commit) is
// parsed in a worker of its own and drawn by the Markdown surface's renderer, side by side in memory; the two drawn documents
// are then compared block by block (a paragraph, a heading, a list item's own text, a table row, a code block, a rule, a raw
// HTML placeholder): a block the other side has as it is, one changed in place (its words marked), one added, one taken out,
// one moved. Nothing here picks, pins or follows a link: the view reads. Images are the manuscript tree's files of now
// (GET /api/asset, as the Markdown surface draws them) on both sides - the old side's own image files are not read; the
// status line says so.
// MDC: the compare on screen (key: revKey() it was drawn for), its parse worker and job, the change groups in order (stops,
// each the blocks of one change) and the one the navigator is at, the layout (split: two columns, the candidate a ?cmp=split
// page asks for) and the observer that lays the gutter chips and the columns' alignment out again when a width changes.
const MDC={seq:0,key:'',worker:/** @type {Worker|null} */(null),job:/** @type {{id:number,resolve:(r:any)=>void,t:ReturnType<typeof setTimeout>}|null} */(null),
  stops:/** @type {HTMLElement[][]} */([]),at:-1,split:false,ro:/** @type {ResizeObserver|null} */(null),pairs:/** @type {[HTMLElement,HTMLElement][]} */([]),
  roots:/** @type {HTMLElement[]} */([]),line:''};
const MDC_SPLIT_MIN=880;   // px of the pane two columns need (two 26rem columns and the gap); narrower, the two stack into one column
const MDC_ALIGN_PASSES=4;   // layout reads the two columns' alignment takes at most (mdcAlign)
const MDC_DIFF_CELLS=4e6;   // the most cells one block or word comparison fills; past it the blocks between the common ends are all changed
const MDC_UNIT='p,h1,h2,h3,h4,h5,h6,pre,tr,hr,li,.md-html,.md-html-run';
const MDC_LABEL={ins:'더함',del:'뺌',mod:'고침',move:'옮김'};
// Whether the document on screen is drawn from Markdown (the rendered compare's documents): a text document shows its lines
// as they are, and its source diff is that already.
function mdcDrawn(){return isMdDoc()&&!isTextDoc();}
// The layout the page asks for: one column by default; two columns side by side with ?cmp=split (the PoC's second candidate).
function mdcWantsSplit(){return /(?:^|[?&])cmp=split(?:&|$)/.test(location.search.slice(1));}
// ---------------- Parsing both sides, apart from the Markdown surface's own worker
/** @param {string} text @returns {Promise<any>} */
function mdcParse(text){mdcParseStop(null);
  return new Promise(resolve=>{let w=MDC.worker;
    try{if(!w){w=new Worker('/md-parse.mjs',{type:'module'}); MDC.worker=w;
        w.onmessage=e=>{const j=MDC.job; if(!j||!e.data||e.data.id!==j.id)return; clearTimeout(j.t); MDC.job=null; j.resolve(e.data);};
        w.onerror=e=>{e.preventDefault(); mdcParseStop({ok:false,limit:MD_LIMIT.LOAD});};}}
    catch(e){resolve({ok:false,limit:MD_LIMIT.LOAD}); return;}
    const id=++MD.seq; MDC.job={id,resolve,t:setTimeout(()=>mdcParseStop({ok:false,limit:MD_LIMIT.TIME}),MD_LIMITS.ms)};
    w.postMessage({id,text,limits:{nesting:MD_LIMITS.nesting,blocks:MD_LIMITS.blocks,inlines:MD_LIMITS.inlines}});});}
/** @param {any} r */
function mdcParseStop(r){const j=MDC.job; if(!j)return; MDC.job=null; clearTimeout(j.t);
  if(MDC.worker){MDC.worker.terminate(); MDC.worker=null;} j.resolve(r);}
// One side drawn with the Markdown surface's renderer (mdRender) into a root of its own, at once: the renderer reads the lines
// it trims and counts its elements on MD, so those are this side's for the build and the surface's again after it, with no
// pause in between for the surface to run in. null past MD_LIMITS.elements. Ids go (a heading's): the surface keeps them.
/** @param {any[]} tokens @param {string[]} lines @returns {HTMLElement|null} */
function mdcBuild(tokens,lines){const keep={lines:MD.lines,els:MD.els,heads:MD.heads},root=document.createElement('div');
  root.className='md mdc-doc'; root.setAttribute('translate','no'); root.lang='';
  MD.lines=lines; MD.els=0; MD.heads=[];
  try{for(const pause of mdRender(root,tokens))void pause;}
  catch(e){if(e===MD_OVER)return null; throw e;}
  finally{MD.lines=keep.lines; MD.els=keep.els; MD.heads=keep.heads;}
  root.querySelectorAll('[id]').forEach(e=>e.removeAttribute('id'));
  // a link here reads: an in-document heading and another document stay words, so the view never leaves for the manuscript
  root.querySelectorAll('[data-act="md-anchor"],[data-act="md-doc"]').forEach(e=>{const x=/** @type {HTMLElement} */(e); delete x.dataset.act; x.removeAttribute('role'); x.removeAttribute('tabindex');
    x.dataset.tip=tr('비교 화면에서는 문서 안 링크를 따라가지 않습니다');});
  return root;}
// ---------------- Blocks and their keys
/** @typedef {{el:HTMLElement,tag:string,key:string,text:string,pics:string,lo:number,hi:number}} MdcUnit */
// Whether element e is a block another unit stands for: a list, a nested paragraph or code, a quote, a table - a tight list
// item's own text leaves these out.
/** @param {Element} e */
function mdcNested(e){return /^(UL|OL|P|PRE|BLOCKQUOTE|TABLE|DIV|H[1-6]|HR)$/.test(e.tagName);}
// The comparable blocks of a drawn side, in document order (pure over the DOM): every paragraph, heading, code block, table
// row, rule and raw HTML placeholder, and a list item whose text is its own (a tight list's; a loose item's paragraphs are
// units of their own). A raw HTML run is one unit. Each has its tag, its key - the text it shows, whitespace folded, with what
// it points at that the text does not show (an image's tree path, a link's target) - and its source lines.
/** @param {HTMLElement} root @returns {MdcUnit[]} */
function mdcUnits(root){const out=/** @type {MdcUnit[]} */([]);
  for(const x of root.querySelectorAll(MDC_UNIT)){const el=/** @type {HTMLElement} */(x);
    if(el.tagName==='LI'&&[...el.children].some(c=>c.tagName==='P'))continue;
    if(el.classList.contains('md-html')&&el.closest('.md-html-run'))continue;
    const text=mdcText(el),refs=mdcRefs(el,'a,[data-anchor],.md-rel'),pics=mdcRefs(el,'.md-pic,.md-img');
    const lo=+(el.dataset.lo||el.dataset.rLo||0),hi=+(el.dataset.hi||el.dataset.rHi||lo);
    out.push({el,tag:el.tagName,key:el.tagName+'\u0001'+text+'\u0001'+pics+'\u0001'+refs,text,pics,lo,hi});}
  return out;}
// A unit's own text: a table row's cells joined with ' | ', a list item's without its nested blocks, whitespace folded.
/** @param {HTMLElement} el */
function mdcText(el){if(el.tagName==='TR')return [...el.children].map(c=>(c.textContent||'').replace(/\s+/g,' ').trim()).join(' | ');
  let s=''; const walk=(/** @type {Node} */n)=>{for(const c of n.childNodes){if(c.nodeType===3)s+=c.nodeValue; else if(c.nodeType===1&&!(el.tagName==='LI'&&mdcNested(/** @type {Element} */(c))))walk(c);}};
  walk(el); return s.replace(/\s+/g,' ').trim();}
// What a unit's images (sel '.md-pic,.md-img': tree path or alt text) or links (their targets) point at, in order.
/** @param {HTMLElement} el @param {string} sel */
function mdcRefs(el,sel){const out=[];
  for(const x of el.querySelectorAll(sel)){const e=/** @type {HTMLElement} */(x);
    if(el.tagName==='LI'&&e.closest('li')!==el)continue;
    out.push(e.dataset.path||e.dataset.tipUrl||e.getAttribute('href')||e.dataset.anchor||e.textContent||'');}
  return out.join(' ');}
// ---------------- Comparing sequences
// The longest common subsequence of a and b (eq tests two items) as ops in order - {t:'eq',a,b}, {t:'del',a}, {t:'ins',b} -
// its common ends taken first, and within each gap the deletions before the insertions. Past MDC_DIFF_CELLS the middle is all
// deleted and inserted (never a wrong match). Pure.
/** @template T @param {T[]} a @param {T[]} b @param {(x:T,y:T)=>boolean} eq @returns {{t:string,a:number,b:number}[]} */
function mdcLcs(a,b,eq){const ops=[]; let s=0; while(s<a.length&&s<b.length&&eq(a[s],b[s]))s++;
  let ea=a.length,eb=b.length; while(ea>s&&eb>s&&eq(a[ea-1],b[eb-1])){ea--; eb--;}
  for(let i=0;i<s;i++)ops.push({t:'eq',a:i,b:i});
  const n=ea-s,m=eb-s;
  if(n*m>MDC_DIFF_CELLS){for(let i=s;i<ea;i++)ops.push({t:'del',a:i,b:-1}); for(let j=s;j<eb;j++)ops.push({t:'ins',a:-1,b:j});}
  else{const w=m+1,L=new Uint32Array((n+1)*w);
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)L[i*w+j]=eq(a[s+i],b[s+j])?L[(i+1)*w+j+1]+1:Math.max(L[(i+1)*w+j],L[i*w+j+1]);
    let i=0,j=0; while(i<n&&j<m){if(eq(a[s+i],b[s+j])){ops.push({t:'eq',a:s+i,b:s+j}); i++; j++;}
      else if(L[(i+1)*w+j]>=L[i*w+j+1]){ops.push({t:'del',a:s+i,b:-1}); i++;} else{ops.push({t:'ins',a:-1,b:s+j}); j++;}}
    for(;i<n;i++)ops.push({t:'del',a:s+i,b:-1}); for(;j<m;j++)ops.push({t:'ins',a:-1,b:s+j});}
  for(let k=0;k<a.length-ea;k++)ops.push({t:'eq',a:ea+k,b:eb+k});
  return ops;}
// The words and marks of a text (pure): letters and digits together, every other visible character alone.
/** @param {string} s */
function mdcWordsOf(s){return String(s).match(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu)||[];}
// How alike two texts are (pure): twice the words they share over all their words (1 for two empty texts).
/** @param {string} x @param {string} y */
function mdcSim(x,y){const a=mdcWordsOf(x),b=mdcWordsOf(y); if(!a.length&&!b.length)return 1; const m=new Map(); let c=0;
  for(const w of a)m.set(w,(m.get(w)||0)+1); for(const w of b){const k=m.get(w)||0; if(k){c++; m.set(w,k-1);}} return 2*c/(a.length+b.length);}
const MDC_PAIR=0.4;   // the likeness above which a taken-out block and an added one of the same kind in one gap are one block changed in place
const MDC_MOVE_MIN=6;   // the fewest characters a block taken out and an identical one added elsewhere need to count as one moved block
// The block ops of two sides (pure over the units): mdcLcs over the keys, then in each gap between unchanged blocks a block
// taken out and a block added of the same tag, alike enough and in order, become one block changed in place ({t:'mod'}); then
// a block taken out and an identical one added anywhere else are one block moved ({t:'from'} where it was, {t:'to'} where it
// is now). A heading moves at any length, any other block from MDC_MOVE_MIN characters.
/** @param {MdcUnit[]} ou @param {MdcUnit[]} nu */
function mdcOps(ou,nu){const raw=mdcLcs(ou,nu,(x,y)=>x.key===y.key),out=[]; let i=0;
  while(i<raw.length){if(raw[i].t==='eq'){out.push(raw[i++]); continue;}
    const gap=[]; while(i<raw.length&&raw[i].t!=='eq')gap.push(raw[i++]);
    const dels=gap.filter(o=>o.t==='del'),ins=gap.filter(o=>o.t==='ins'),pair=new Map(); let from=0;
    for(const d of dels)for(let x=from;x<ins.length;x++){const n=ins[x];
      if(nu[n.b].tag===ou[d.a].tag&&nu[n.b].pics===ou[d.a].pics&&mdcSim(ou[d.a].text,nu[n.b].text)>=MDC_PAIR){pair.set(d,n); from=x+1; break;}}
    let di=0,ni=0; while(di<dels.length||ni<ins.length){const d=dels[di],n=ins[ni];
      if(d&&pair.has(d)){const p=pair.get(d); if(n&&n!==p){out.push(n); ni++; continue;} out.push({t:'mod',a:d.a,b:p.b}); di++; ni++; continue;}
      if(d){out.push(d); di++; continue;} out.push(n); ni++;}}
  const added=new Map(); out.forEach((o,k)=>{if(o.t!=='ins')return; const u=nu[o.b]; if(!/^H/.test(u.tag)&&u.text.length<MDC_MOVE_MIN)return;
    const l=added.get(u.key)||[]; l.push(k); added.set(u.key,l);});
  out.forEach(o=>{if(o.t!=='del')return; const l=added.get(ou[o.a].key); if(!l||!l.length)return; const k=/** @type {number} */(l.shift()),to=out[k];
    o.t='from'; o.b=to.b; to.t='to'; to.a=o.a;});
  return out;}
// ---------------- Marking words inside a block changed in place
/** @typedef {{node:Text,s:number,e:number,w:string}} MdcTok */
// The words of a unit as they sit in its text nodes (a list item's own text only); a code block's lines are its words.
/** @param {HTMLElement} el @returns {MdcTok[]} */
function mdcToks(el){const out=/** @type {MdcTok[]} */([]);
  if(el.tagName==='PRE'){for(const ln of el.querySelectorAll('.ln')){const t=ln.firstChild; if(t&&t.nodeType===3){const v=String(t.nodeValue||'').replace(/\n$/,''); out.push({node:/** @type {Text} */(t),s:0,e:v.length,w:v});}} return out;}
  const walk=(/** @type {Node} */n)=>{for(const c of n.childNodes){
    if(c.nodeType===3){const v=String(c.nodeValue||''); for(const m of v.matchAll(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu))out.push({node:/** @type {Text} */(c),s:/** @type {number} */(m.index),e:/** @type {number} */(m.index)+m[0].length,w:m[0]});}
    else if(c.nodeType===1&&!(el.tagName==='LI'&&mdcNested(/** @type {Element} */(c)))&&!(/** @type {Element} */(c)).classList.contains('sr-only'))walk(c);}};
  walk(el); return out;}
// Marks the words of a block changed in place: the added words on the new side (ins), the taken-out ones on the old side
// (del) - or, in one column (inline), the taken-out words put back into the new block where they were, struck through.
// Edits run from each text node's end to its start, so the offsets still to come stay right.
/** @param {HTMLElement} oldEl @param {HTMLElement} newEl @param {boolean} inline */
function mdcWordMarks(oldEl,newEl,inline){const a=mdcToks(oldEl),b=mdcToks(newEl),ops=mdcLcs(a,b,(x,y)=>x.w===y.w);
  /** @type {{node:Text,s:number,e:number,kind:string,text?:string}[]} */
  const edits=[]; const span=(/** @type {MdcTok[]} */ts,kind)=>{let k=0; while(k<ts.length){let j=k; while(j+1<ts.length&&ts[j+1].node===ts[k].node)j++; edits.push({node:ts[k].node,s:ts[k].s,e:ts[j].e,kind}); k=j+1;}};
  let gone=/** @type {MdcTok[]} */([]);
  const flushGone=(/** @type {number} */bAt)=>{if(!gone.length)return; if(!inline){span(gone,'del');} else{const at=b[bAt]||b[b.length-1];
      const text=gone.map((t,i)=>i&&gone[i-1].node===t.node&&gone[i-1].e===t.s?t.w:(i?' ':'')+t.w).join('');
      if(at)edits.push({node:at.node,s:b[bAt]?at.s:at.e,e:b[bAt]?at.s:at.e,kind:'put',text:(b[bAt]?'':' ')+text+(b[bAt]?' ':'')}); else edits.push({node:/** @type {any} */(null),s:0,e:0,kind:'put',text});}
    gone=[];};
  let bi=0; for(const o of ops){if(o.t==='eq'){flushGone(o.b); bi=o.b+1; continue;} if(o.t==='del'){gone.push(a[o.a]); continue;} flushGone(o.b); span([b[o.b]],'ins'); bi=o.b+1;}
  flushGone(bi);
  // one edit per run of adjacent added words in one text node
  const merged=[]; for(const x of edits){const p=merged[merged.length-1]; if(p&&x.kind==='ins'&&p.kind==='ins'&&p.node===x.node&&/^\s*$/.test(String(x.node.nodeValue||'').slice(p.e,x.s))){p.e=x.e; continue;} merged.push(x);}
  for(const x of merged.filter(x=>!x.node&&x.kind==='put')){const d=mdcEl('del',x.text||''); newEl.appendChild(d);}
  const byNode=new Map(); for(const x of merged){if(!x.node)continue; const l=byNode.get(x.node)||[]; l.push(x); byNode.set(x.node,l);}
  for(const [node,l] of byNode){l.sort((p,q)=>q.s-p.s||(p.kind==='put'?1:-1));
    for(const x of l){if(x.kind==='put'){const rest=node.splitText(x.s); /** @type {Node} */(rest.parentNode).insertBefore(mdcEl('del',x.text||''),rest); continue;}
      const mid=node.splitText(x.s); mid.splitText(x.e-x.s); const w=mdcEl(x.kind==='ins'?'ins':'del',''); /** @type {Node} */(mid.parentNode).insertBefore(w,mid); w.appendChild(mid);}}}
// A link of a block changed in place whose target the other side's block does not have: marked like an added (new side) or a
// taken-out word (old side), its tip saying the target changed - a link's words can stay while where it goes changes.
/** @param {HTMLElement} oldEl @param {HTMLElement} newEl */
function mdcLinkMarks(oldEl,newEl){const sel='a,.md-rel,[data-anchor]',to=(/** @type {Element} */e)=>{const x=/** @type {HTMLElement} */(e); return x.dataset.tipUrl||x.getAttribute('href')||x.dataset.anchor||'';};
  const olds=[...oldEl.querySelectorAll(sel)],news=[...newEl.querySelectorAll(sel)],ot=new Set(olds.map(to)),nt=new Set(news.map(to));
  for(const e of news){const t=to(e); if(t&&!ot.has(t)){e.classList.add('mdc-wl'); /** @type {HTMLElement} */(e).dataset.tip=tl('링크 대상이 바뀜 · {to}',{to:ccPlain(t)});}}
  for(const e of olds){const t=to(e); if(t&&!nt.has(t))e.classList.add('mdc-wl-del');}}
/** @param {string} tag @param {string} text */
function mdcEl(tag,text){const e=document.createElement(tag); e.className='mdc-w'; if(text)e.textContent=text; return e;}
// ---------------- Laying the marks
// Marks unit element el as a change of kind (ins, del, mod, move): its tint and, for a screen reader, the kind before its text.
/** @param {HTMLElement} el @param {string} kind */
function mdcMark(el,kind){el.classList.add('mdc-'+kind); el.dataset.mdc=kind;
  const s=document.createElement('span'); s.className='sr-only'; s.textContent=tr({ins:'더한 블록',del:'뺀 블록',mod:'고친 블록',move:'옮긴 블록'}[kind]||'')+': ';
  if(el.tagName==='TR'){const c=el.firstElementChild; if(c)c.prepend(s);} else if(el.tagName!=='HR')el.prepend(s);}
// The element a taken-out list item leaves behind in one column: its own text, without the nested blocks the new side keeps.
/** @param {MdcUnit} u */
function mdcOwn(u){if(u.el.tagName!=='LI')return u.el; const c=/** @type {HTMLElement} */(u.el.cloneNode(true));
  [...c.children].forEach(x=>{if(mdcNested(x))x.remove();}); return c;}
/** @param {Element} e @param {Element} root */
function mdcBox(e,root){const p=e.parentElement; return !p||p===root?'root':p.tagName;}
/** @param {Element} e @param {Element} root */
function mdcTop(e,root){let x=e; while(x.parentElement&&x.parentElement!==root)x=x.parentElement; return x;}
// Puts el - a block taken out of the old side (its old place: ref, in oroot) - into the new side's root: right after the last
// block laid (prev) or before the next new block when that one sits in the same kind of box (a list, a table, a quote, the
// column); otherwise inside shallow copies of the boxes it sat in, after prev's top block. Returns el, the next block's prev.
/** @param {HTMLElement} el @param {HTMLElement} ref @param {HTMLElement} oroot @param {HTMLElement|null} prev @param {HTMLElement|null} next @param {HTMLElement} root */
function mdcPlace(el,ref,oroot,prev,next,root){const want=mdcBox(ref,oroot);
  if(prev&&mdcBox(prev,root)===want){prev.after(el); return el;}
  if(next&&mdcBox(next,root)===want){next.before(el); return el;}
  let node=/** @type {HTMLElement} */(el); for(let a=ref.parentElement;a&&a!==oroot;a=a.parentElement){const c=/** @type {HTMLElement} */(a.cloneNode(false));
    delete c.dataset.lo; delete c.dataset.hi; c.appendChild(node); node=c;}
  if(prev)mdcTop(prev,root).after(node); else if(next)mdcTop(next,root).before(node); else root.appendChild(node);
  return el;}
// A moved block's place on the side it left, in one column: a slim line that says where it went.
/** @param {MdcUnit} u @param {MdcUnit} to */
function mdcGhost(u,to){const p=u.el.parentElement,tag=p&&/^(UL|OL)$/.test(p.tagName)?'li':p&&/^(TBODY|THEAD)$/.test(p.tagName)?'tr':'div',g=document.createElement(tag);
  g.className='mdc-ghost'; g.dataset.toLo=String(to.lo); g.dataset.n='1'; const t=tl('여기 있던 블록을 L{line}로 옮김',{line:to.lo}),box=tag==='tr'?document.createElement('td'):g;
  if(tag==='tr'){/** @type {HTMLTableCellElement} */(box).colSpan=Math.max(1,u.el.children.length); g.appendChild(box);} box.textContent=t; return g;}
// ---------------- The two layouts
// One column: the new side, with each block taken out put back where it was (struck through), each moved block's old place a
// slim line, the words of a block changed in place marked inside it. Returns the column, the new units it shows and its stops.
/** @param {HTMLElement} oroot @param {HTMLElement} nroot @param {MdcUnit[]} ou @param {MdcUnit[]} nu @param {any[]} ops */
function mdcInline(oroot,nroot,ou,nu,ops){let prev=/** @type {HTMLElement|null} */(null);
  const next=(/** @type {number} */k)=>{for(let x=k+1;x<ops.length;x++){const o=ops[x]; if(o.t!=='del'&&o.t!=='from')return nu[o.b].el;} return null;};
  ops.forEach((o,k)=>{
    if(o.t==='eq'){prev=nu[o.b].el; return;}
    if(o.t==='ins'||o.t==='to'||o.t==='mod'){const el=nu[o.b].el; mdcMark(el,o.t==='ins'?'ins':o.t==='to'?'move':'mod');
      if(o.t==='to')el.dataset.mdcFrom=String(ou[o.a].lo);
      if(o.t==='mod'){mdcWordMarks(ou[o.a].el,el,true); mdcLinkMarks(ou[o.a].el,el);} prev=el; return;}
    const u=ou[o.a]; if(o.t==='del'){const el=mdcOwn(u); mdcMark(el,'del'); prev=mdcPlace(el,u.el,oroot,prev,next(k),nroot); return;}
    // blocks moved together (a section) leave one line: the first one's, widened to their lines
    const last=k>0?ops[k-1]:null; if(last&&last.t==='from'&&prev&&prev.classList.contains('mdc-ghost')&&mdcBox(u.el,oroot)===mdcBox(ou[last.a].el,oroot)){
      const n=(+(prev.dataset.n||1))+1,lo=+(prev.dataset.toLo||0),hi=nu[o.b].hi; prev.dataset.n=String(n);
      (prev.querySelector('td')||prev).textContent=tl('여기 있던 블록 {n}개를 L{lo}–L{hi}로 옮김',{n,lo,hi}); return;}
    prev=mdcPlace(mdcGhost(u,nu[o.b]),u.el,oroot,prev,next(k),nroot);});
  return nroot;}
// Two columns, the old side left and the new side right, each marked on its own side; a block changed in place has its taken-out
// words marked on the left and its added words on the right. The blocks both sides have are aligned (mdcAlign).
/** @param {HTMLElement} oroot @param {HTMLElement} nroot @param {MdcUnit[]} ou @param {MdcUnit[]} nu @param {any[]} ops */
function mdcSplit(oroot,nroot,ou,nu,ops){MDC.pairs=[];
  for(const o of ops){
    if(o.t==='eq'){MDC.pairs.push([ou[o.a].el,nu[o.b].el]); continue;}
    if(o.t==='mod'){mdcMark(ou[o.a].el,'mod'); mdcMark(nu[o.b].el,'mod'); mdcWordMarks(ou[o.a].el,nu[o.b].el,false); mdcLinkMarks(ou[o.a].el,nu[o.b].el); MDC.pairs.push([ou[o.a].el,nu[o.b].el]); continue;}
    if(o.t==='del')mdcMark(ou[o.a].el,'del'); else if(o.t==='ins')mdcMark(nu[o.b].el,'ins');
    else{const u=o.t==='from'?ou[o.a]:nu[o.b]; mdcMark(u.el,'move'); if(o.t==='to')u.el.dataset.mdcFrom=String(ou[o.a].lo);}}
  const wrap=document.createElement('div'); wrap.className='mdc-cols';
  for(const [root,label] of /** @type {[HTMLElement,string][]} */([[oroot,tr('옛 판')],[nroot,tr('새 판')]])){const col=document.createElement('div'); col.className='mdc-col';
    const h=document.createElement('div'); h.className='mdc-side'; h.textContent=label; col.append(h,root); wrap.appendChild(col);}
  return wrap;}
// Aligns the blocks both columns have: each pair's tops meet, the column that is behind taking a gap before its block. One read of
// every top, one write of every gap, and again - at most MDC_ALIGN_PASSES times - while a pair is still a pixel off: a new gap
// stops two margins from collapsing, so it moves what follows by more than its height once. A table row is left as it is (a row
// takes no gap); the next block after the table aligns again.
function mdcAlign(){const pairs=MDC.pairs; if(!MDC.split||!pairs.length)return;
  document.querySelectorAll('#revision-rendered .mdc-gap').forEach(g=>g.remove());
  const cols=MDC.roots; if(cols.length!==2)return;
  const gaps=new Map();
  for(let pass=0;pass<MDC_ALIGN_PASSES;pass++){const t0=cols[0].getBoundingClientRect().top,t1=cols[1].getBoundingClientRect().top;
    const tops=pairs.map(([a,b])=>[a.getBoundingClientRect().top-t0,b.getBoundingClientRect().top-t1]);
    let s0=0,s1=0,moved=false;
    pairs.forEach(([a,b],i)=>{if(a.tagName==='TR'||b.tagName==='TR')return; const o=tops[i][0]+s0,n=tops[i][1]+s1,d=Math.round(n-o);
      if(Math.abs(d)<1)return; moved=true; const el=d>0?a:b,g=mdcGap(el,gaps); const h=(parseFloat(g.style.height)||0)+Math.abs(d); g.style.height=h+'px'; if(d>0)s0+=Math.abs(d); else s1+=Math.abs(d);});
    if(!moved)break;}
  mdcChips();}
/** @param {HTMLElement} el @param {Map<HTMLElement,HTMLElement>} gaps */
function mdcGap(el,gaps){let g=gaps.get(el); if(g&&g.isConnected)return g; const p=el.parentElement,li=!!p&&/^(UL|OL)$/.test(p.tagName);
  g=document.createElement(li?'li':'div'); g.className='mdc-gap'; g.setAttribute('aria-hidden','true'); el.before(g); gaps.set(el,g); return g;}
// The gutter chips: each marked block's kind as a word at its first line, in the column's left gutter (a layer of the column,
// laid out again when a width changes). Not read aloud: the block itself carries its kind (mdcMark).
function mdcChips(){for(const root of MDC.roots){root.querySelectorAll(':scope>.mdc-chips').forEach(x=>x.remove());
    const layer=document.createElement('div'); layer.className='mdc-chips'; layer.setAttribute('aria-hidden','true'); const top=root.getBoundingClientRect().top;
    const items=/** @type {{y:number,cls:string,text:string}[]} */([]);
    for(const x of root.querySelectorAll('[data-mdc],.mdc-pin')){const e=/** @type {HTMLElement} */(x),r=e.getBoundingClientRect(); if(!r.height)continue;
      if(e.classList.contains('mdc-pin'))items.push({y:r.top-top,cls:'pin',text:e.dataset.mdcPin||''});
      if(e.dataset.mdc)items.push({y:r.top-top,cls:e.dataset.mdc,text:tr(MDC_LABEL[e.dataset.mdc]||'')});}
    items.sort((p,q)=>p.y-q.y||(p.cls==='pin'?1:-1)); let last=-1e9;
    for(const it of items){const c=document.createElement('span'); c.className='mdc-chip mdc-chip-'+it.cls; c.textContent=it.text;
      const y=Math.max(it.y,last+22); c.style.top=y+'px'; last=y; layer.appendChild(c);}
    root.appendChild(layer);}}
// The unit elements of a drawn side in document order, as mdcUnits takes them (and a moved block's old place, ghosts).
/** @param {HTMLElement} root @param {boolean} ghosts @returns {HTMLElement[]} */
function mdcUnitEls(root,ghosts){return [...root.querySelectorAll(MDC_UNIT+(ghosts?',.mdc-ghost':''))].map(x=>/** @type {HTMLElement} */(x))
  .filter(e=>!(e.tagName==='LI'&&[...e.children].some(c=>c.tagName==='P'))&&!(e.classList.contains('md-html')&&e.closest('.md-html-run')));}
// ---------------- Showing a compare
// The change groups in order: runs of marked blocks with nothing unchanged between them, on the new side (in two columns, a run
// the old side alone has is a group of its own, between the new side's groups in order). The navigator steps through them.
/** @param {HTMLElement[]} roots */
function mdcStops(roots){const stops=/** @type {HTMLElement[][]} */([]); let cur=/** @type {HTMLElement[]|null} */(null);
  // one column: document order; two columns: the new side's order with the old side's lone changes after the pair before them
  const seq=roots.length===2?mdcSplitOrder(roots):mdcUnitEls(roots[0],true);
  for(const e of seq){const marked=!!e.dataset.mdc||e.classList.contains('mdc-ghost');
    if(marked){if(!cur){cur=[]; stops.push(cur);} cur.push(e);} else if(!/^(UL|OL|TABLE|TBODY|THEAD)$/.test(e.tagName))cur=null;}
  return stops;}
// Both columns' units in one reading order: the new side's, each of the old side's lone units after the old unit of the pair before it.
/** @param {HTMLElement[]} roots */
function mdcSplitOrder(roots){const old=mdcUnitEls(roots[0],false),neu=mdcUnitEls(roots[1],false);
  const mate=new Map(MDC.pairs.map(([a,b])=>[a,b])),after=new Map(); let anchor=/** @type {HTMLElement|null} */(null);
  for(const e of old){if(mate.has(e)){anchor=/** @type {HTMLElement} */(mate.get(e)); continue;} if(!e.dataset.mdc)continue; const l=after.get(anchor)||[]; l.push(e); after.set(anchor,l);}
  const out=[...(after.get(null)||[])]; for(const e of neu){out.push(e); for(const x of after.get(e)||[])out.push(x);} return out;}
// The navigator (#revision-nav): where it is among the change groups, and its buttons pressed only where there is a next one.
function mdcDrawNav(){const n=MDC.stops.length,box=$('#revision-nav'); box.hidden=REV.format!==DIFF_FORMAT.RENDERED||!n;
  $('#mdc-at').textContent=!n?'':MDC.at<0?tl('바뀐 곳 {n}곳',{n}):tl('바뀐 곳 {at}/{n}',{at:MDC.at+1,n});
  /** @type {HTMLButtonElement} */($('#mdc-prev')).disabled=MDC.at<=0; /** @type {HTMLButtonElement} */($('#mdc-next')).disabled=MDC.at>=n-1;}
// Goes to change group i: brings its first block to a third of the pane's height and rings the group for a moment.
/** @param {number} i */
/** @param {number} i @param {boolean} [ring] */
function mdcGo(i,ring){const g=MDC.stops[i]; if(!g)return; MDC.at=i; mdcDrawNav();
  document.querySelectorAll('#revision-rendered .mdc-cur').forEach(e=>e.classList.remove('mdc-cur')); if(ring)g.forEach(e=>e.classList.add('mdc-cur'));
  const pane=LAYOUT===LAYOUT_MODE.NARROW?$('#revision-body'):$('#revision-rendered'),r=g[0].getBoundingClientRect(),p=pane.getBoundingClientRect();
  pane.scrollTo({top:pane.scrollTop+r.top-p.top-Math.round(pane.clientHeight/3),behavior:'smooth'});}
/** @param {number} d */
function mdcStep(d){if(!MDC.stops.length)return; mdcGo(Math.min(MDC.stops.length-1,Math.max(0,MDC.at+d)),true);}
// Forgets the compare on screen (another commit, another document, the manuscript view).
function mdcClear(){++MDC.seq; MDC.key=''; MDC.line=''; MDC.stops=[]; MDC.at=-1; MDC.pairs=[]; MDC.roots=[]; mdcParseStop(null);
  if(MDC.ro){MDC.ro.disconnect(); MDC.ro=null;} $('#revision-rendered').replaceChildren(); $('#revision-nav').hidden=true;}
// A notice in the compare's place (a side that cannot be drawn, a limit), with the way to the source diff.
/** @param {string} text */
function mdcNote(text){const n=document.createElement('div'); n.className='md-note mdc-note'; n.setAttribute('role','status');
  setHtml(n,html`<span>${text}</span> <button class="btn-sm" data-act="revision-format" data-format="source">소스 diff 보기</button>`); return n;}
// Why a side carries no lines (GET /api/revision-source's reason), in a line.
/** @param {any} side @param {string} which */
function mdcSideWhy(side,which){switch(side&&side.reason){
  case 'source_too_large':return tl('{side}이 {size}라 그려 비교하지 않습니다(한도 {limit})',{side:which,size:mdMiB(side.bytes),limit:mdMiB(side.limit)});
  case 'source_not_utf8':return tl('{side}이 UTF-8이 아니라 그려 비교하지 않습니다',{side:which});
  case 'not_a_file':return tl('{side}에서 이 경로가 파일이 아니라 그려 비교하지 않습니다',{side:which});
  default:return tl('{side}을 읽지 못했습니다',{side:which});}}
// Parses and draws one side's lines (null: the file is not on that side - an empty document). {root} or {why}.
/** @param {string[]|null} lines @returns {Promise<{root:HTMLElement|null,why?:string}>} */
async function mdcSide(lines){if(!lines)return {root:mdcBuild([],[])};
  const res=await mdcParse(lines.join('\n')); if(!res)return {root:null,why:''};
  if(!res.ok)return {root:null,why:mdLimitText(String(res.limit||MD_LIMIT.ERROR))};
  const root=mdcBuild(res.tokens,lines); return root?{root}:{root:null,why:mdLimitText(MD_LIMIT.ELEMENTS)};}
// Shows the rendered compare of commit id (from base for a range) in #revision-rendered, for the visit seq of document k: reads
// both sides, draws and compares them, lays them out in one column or two (two only where the pane is wide enough), marks a
// pin's blocks when the view was opened for one ([변경 보기]), and says on the status line what changed.
/** @param {string} id @param {string} base @param {number} seq @param {string|null} k */
async function mdcShow(id,base,seq,k){const pane=$('#revision-rendered'),key=revKey(),mine=++MDC.seq,live=()=>mine===MDC.seq&&revisionCurrent(seq,k,id)&&MDC.key===key;
  MDC.key=key; MDC.line=''; MDC.stops=[]; MDC.at=-1; MDC.pairs=[]; MDC.roots=[]; if(MDC.ro){MDC.ro.disconnect(); MDC.ro=null;}
  pane.replaceChildren(mdWait(tr('두 판을 읽는 중입니다.'))); mdcDrawNav();
  const tg0=revisionPinFor(id);
  let r,scope=null; try{const q='/api/revision-source?commit='+encodeURIComponent(id)+(base?'&base='+encodeURIComponent(base):'');
    const [src,sc]=await Promise.all([api(dq(q,k),{what:'두 판 읽기',silent:true}),tg0?api(dq('/api/revision-diff?commit='+encodeURIComponent(id)+'&pin='+tg0.id,k),{what:'변경 내용 읽기',silent:true}).catch(()=>null):Promise.resolve(null)]);
    r=src.data; scope=sc&&sc.data?{...(sc.data.scope||{}),whole:String(sc.data.diff||'')}:null;}
  catch(e){if(live()){const why=e&&/** @type {ApiError} */(e).data?errText(/** @type {ApiError} */(e).data):''; pane.replaceChildren(mdcNote(why?tl('두 판을 읽지 못했습니다: {error}',{error:why}):tr('두 판을 읽지 못했습니다.')));} return;}
  if(!live())return;
  const bad=[[r.old,tr('옛 판')],[r.new,tr('새 판')]].find(([s])=>s&&!Array.isArray(s.lines));
  if(bad){pane.replaceChildren(mdcNote(mdcSideWhy(bad[0],bad[1]))); mdcStatus(r,null); return;}
  pane.replaceChildren(mdWait(tr('두 판을 그려 견주는 중입니다.')));
  const o=await mdcSide(r.old?r.old.lines:null); if(!live())return;
  const n=o.root?await mdcSide(r.new?r.new.lines:null):{root:null,why:''}; if(!live())return;
  if(!o.root||!n.root){pane.replaceChildren(mdcNote(tl('그려 비교하지 못했습니다 — {why}',{why:o.why||n.why||tr('파서를 쓸 수 없습니다')}))); mdcStatus(r,null); return;}
  const ou=mdcUnits(o.root),nu=mdcUnits(n.root),ops=mdcOps(ou,nu),counts={ins:0,del:0,mod:0,move:0};
  for(const x of ops){if(x.t==='ins')counts.ins++; else if(x.t==='del')counts.del++; else if(x.t==='mod')counts.mod++; else if(x.t==='to')counts.move++;}
  MDC.split=mdcWantsSplit()&&pane.clientWidth>=MDC_SPLIT_MIN;
  const view=MDC.split?mdcSplit(o.root,n.root,ou,nu,ops):mdcInline(o.root,n.root,ou,nu,ops);
  MDC.roots=MDC.split?[o.root,n.root]:[n.root];
  const head=document.createElement('div'); head.className='mdc-legend'; head.setAttribute('aria-hidden','true');
  setHtml(head,html`<span class="mdc-chip mdc-chip-ins">${tr('더함')}</span><span class="mdc-chip mdc-chip-del">${tr('뺌')}</span><span class="mdc-chip mdc-chip-mod">${tr('고침')}</span><span class="mdc-chip mdc-chip-move">${tr('옮김')}</span><span class="mdc-legend-t">${tr('그림은 지금 원고 트리의 파일입니다')}</span>`);
  const frame=document.createElement('div'); frame.className='mdc-frame'+(MDC.split?' split':'');
  if(!r.old)frame.appendChild(mdcInfo(tr('이 커밋에서 파일이 처음 생겼습니다 — 모든 블록이 더한 블록입니다.')));
  if(!r.new)frame.appendChild(mdcInfo(tr('이 커밋에서 파일을 지웠습니다 — 모든 블록이 뺀 블록입니다.')));
  if(mdcWantsSplit()&&!MDC.split)frame.appendChild(mdcInfo(tr('화면이 좁아 두 판을 한 단으로 겹쳐 보입니다.')));
  frame.append(head,view); pane.replaceChildren(frame);
  MDC.stops=mdcStops(MDC.roots);
  const at=mdcTarget(tg0,scope,nu); mdcStatus(r,counts);
  if(!MDC.stops.length)frame.insertBefore(mdcInfo(tr('두 판의 그린 문서가 같습니다 — 줄 끝·공백·HTML 주석처럼 그리지 않는 곳만 바뀌었습니다. 정확한 변경은 [소스 diff]에 있습니다.')),head);
  requestAnimationFrame(()=>{if(!live())return; mdcAlign(); if(!MDC.split)mdcChips();
    MDC.ro=window.ResizeObserver?new ResizeObserver(()=>{if(live())requestAnimationFrame(()=>{if(MDC.split)mdcAlign(); else mdcChips();});}):null;
    if(MDC.ro)MDC.roots.forEach(x=>/** @type {ResizeObserver} */(MDC.ro).observe(x));
    if(at>=0)mdcGo(at); else{MDC.at=-1; mdcDrawNav();}});
  if(REV.target)revTargetNote();}
/** @param {string} text */
function mdcInfo(text){const d=document.createElement('div'); d.className='mdc-info'; d.setAttribute('role','status'); d.textContent=text; return d;}
// The status line of a compare: its two sides and what changed.
/** @param {any} r @param {{ins:number,del:number,mod:number,move:number}|null} c */
function mdcStatus(r,c){const ends=(r.base?String(r.base).slice(0,8):tr('없음'))+' → '+String(r.id||'').slice(0,8);
  let t=ends+(r.merge_base?' · '+tl('공통 조상 {mb}부터 비교',{mb:String(r.merge_base).slice(0,8)}):'');
  if(c){const n=c.ins+c.del+c.mod+c.move; t+=' · '+(n?tl('바뀐 블록 {n}곳 — 고침 {mod} · 더함 {ins} · 뺌 {del} · 옮김 {move}',{n,mod:c.mod,ins:c.ins,del:c.del,move:c.move}):tr('바뀐 블록 없음'));}
  MDC.line=t; if(REV.format===DIFF_FORMAT.RENDERED)$('#revision-status').textContent=t;}
// The pin the view was opened for ([변경 보기]): its blocks on the new side - those whose lines meet the pin's own changes (the
// server's hunks of the pin, scope) or else its lines - ringed in the review colour, the changed ones first. Returns the change
// group to open at (-1: none), and leaves on the pin the line the guide says (tg.mdcMsg).
/** @param {RevTarget|null} tg @param {any} scope @param {MdcUnit[]} nu */
function mdcTarget(tg,scope,nu){const t=REV.target; if(t&&!tg)t.mdcMsg=tl('핀 #{id}의 커밋을 볼 때만 핀 자리를 표시합니다',{id:t.id}); if(!tg)return -1;
  // the pin's own hunks when it owns part of the commit; every hunk when it owns all of it; else its lines as they are now
  const lo=tg.lo||0,ranges=scope&&scope.mode===SCOPE_MODE.PIN?hunkRanges(scope.diff):scope&&scope.hunks>0?hunkRanges(scope.whole):[[lo,tg.hi||lo]];
  const meets=nu.filter(u=>u.lo&&ranges.some(([a,b])=>u.hi>=a&&u.lo<=b)&&u.el.isConnected);
  const changed=meets.filter(u=>u.el.dataset.mdc);
  const shown=changed.length?changed:meets;
  shown.forEach(u=>{u.el.classList.add('mdc-pin'); u.el.dataset.mdcPin=tl('핀 #{id}',{id:tg.id});});
  tg.mdcMsg=changed.length?tl('핀 #{id} 자리의 바뀐 블록 {n}곳을 보라 테두리로 표시했습니다',{id:tg.id,n:changed.length})+(scope&&scope.hunks>0?' ('+tr(scope.source===SCOPE_SOURCE.CHANGES?'에이전트가 기록한 줄':'핀 자리로 추정')+')':''):
    meets.length?tr('핀 자리의 블록은 이 커밋에서 바뀌지 않았습니다 — 그 블록을 보라 테두리로 표시했습니다'):tr('새 판에서 핀 자리를 찾지 못했습니다 — 정확한 줄은 [소스 diff]');
  const first=shown[0]; if(!first)return -1;
  const i=MDC.stops.findIndex(g=>g.includes(first.el)); return i;}
