// ------------------------------------------------ The rendered compare of a Markdown document ([그린 비교], the changes view)
// docs/handbook/viewer.md §변경 보기, ADR-0031. The document's own file on the two sides the source diff compares
// (GET /api/revision-source: the commit's first parent and the commit, or a range's old side and its commit) is parsed in a
// worker of its own and drawn by the Markdown surface's renderer (mdRender) with a render context of its own per side (mdRx),
// pausing for the browser as the document view does; the two drawn documents are then compared block by block (a paragraph,
// a heading, a list item's own text, a table row, a code block, display math, the front matter, a rule, a raw HTML
// placeholder): a block the other side has as it is, one changed in place (its words marked), one added, one taken out, one
// moved. One column: the new side, with the taken-out blocks put back where they were. Nothing here picks, pins or follows an
// in-document link: the view reads. Images are the manuscript tree's files of now (GET /api/asset, as the Markdown surface
// draws them) on both sides - the old side's own image files are not read; a line above the compare says so whenever a side
// has one. A character that would hide or reorder text stays in its box (mdText) on both sides, and a changed one is a
// changed word.
// MDC: the compare on screen (key: revKey() it was drawn for), its parse worker and job, the change groups in order (stops,
// each the blocks of one change) and the one the navigator is at, the drawn column (root) and the observer that lays its
// gutter chips out again when its width changes, the status line it said (line) and what it counted (said: the answer and
// the counts, so a range's line can take the source diff's commit and file counts once they come).
const MDC={seq:0,key:'',worker:/** @type {Worker|null} */(null),job:/** @type {{id:number,resolve:(r:any)=>void,t:ReturnType<typeof setTimeout>}|null} */(null),
  stops:/** @type {HTMLElement[][]} */([]),at:-1,ro:/** @type {ResizeObserver|null} */(null),root:/** @type {HTMLElement|null} */(null),line:'',
  said:/** @type {{r:any,c:{ins:number,del:number,mod:number,move:number}|null}|null} */(null)};
const MDC_DIFF_CELLS=4e6;   // the most cells one block or word comparison fills; past it the blocks between the common ends are all changed
// The most steps one compare spends matching (every subsequence's table cells) and pairing (the words of each pair of blocks it
// weighs): past it no more blocks are paired and no more words marked - what is left is added and taken out as it is, at once.
const MDC_WORK=8e6;
const MDC_UNIT='p,h1,h2,h3,h4,h5,h6,pre,tr,hr,li,.md-html,.md-html-run,.md-front';
// The boxes mdcRegroup looks at, a split or a join of which the two kept blocks beside it show: a quote, a list, a list item.
const MDC_REGROUP=/^(?:BLOCKQUOTE|UL|OL|LI)$/;
const MDC_LABEL={ins:'더함',del:'뺌',mod:'고침',move:'옮김'};
// Whether the document on screen is drawn from Markdown (the rendered compare's documents): a text document shows its lines
// as they are, and its source diff is that already.
function mdcDrawn(){return isMdDoc()&&!isTextDoc();}
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
// One side drawn with the Markdown surface's renderer (mdRender) into a root of its own, with a render context of its own
// (mdRx: its lines, its element count, its marked characters, its headings - the document view's MD is never touched), with
// a yield to the browser whenever mdRender pauses (every MD_LIMITS.chunk units of work, as the document view builds) and
// live() asked after each: null past MD_LIMITS.elements, or once live() is false (a newer compare). Ids go (a heading's: the
// surface keeps them), and an in-document heading or another document is a word here, so the view never leaves for the
// manuscript.
/** @param {any[]} tokens @param {string[]} lines @param {()=>boolean} live @returns {Promise<HTMLElement|null>} */
async function mdcBuild(tokens,lines,live){const root=document.createElement('div'),cx=mdRx(lines);
  root.className='md mdc-doc'; root.setAttribute('translate','no'); root.lang='';
  try{for(const pause of mdRender(root,tokens,cx)){void pause; await mdYield(); if(!live())return null;}}
  catch(e){if(e===MD_OVER)return null; throw e;}
  mdRxKeep(root,cx);   // an image that fails later draws its alt text on this side's count (mdPicError)
  root.querySelectorAll('[id]').forEach(e=>e.removeAttribute('id'));
  root.querySelectorAll('[data-act="md-anchor"],[data-act="md-doc"]').forEach(e=>{const x=/** @type {HTMLElement} */(e); delete x.dataset.act; x.removeAttribute('role'); x.removeAttribute('tabindex');
    x.dataset.tip=tr('비교 화면에서는 문서 안 링크를 따라가지 않습니다');});
  return root;}
// ---------------- Blocks and their keys
/** @typedef {{el:HTMLElement,tag:string,key:string,text:string,pics:string,shape:string,box:string,grp:unknown[],alts:string,lo:number,hi:number}} MdcUnit */
// Whether element e is a block another unit stands for: a list, a nested paragraph or code, a quote, a table - a tight list
// item's own text leaves these out.
/** @param {Element} e */
function mdcNested(e){return /^(UL|OL|P|PRE|BLOCKQUOTE|TABLE|DIV|H[1-6]|HR)$/.test(e.tagName);}
// Whether element e inside unit el is part of the unit's own content: for a list item, nothing between them is a nested
// block (mdcNested) - its nested list, a quote or a table in it are units of their own, wherever they sit below it. The one
// boundary of a list item's text (mdcText), its structure (mdcShape), its words (mdcToks), its images, links and alt texts
// (mdcRefs, mdcUnits) and its marked links (mdcLinkMarks). Pure over the DOM.
/** @param {HTMLElement} el @param {Element} e */
function mdcOwnPart(el,e){if(el.tagName!=='LI')return true;
  for(let a=/** @type {Element|null} */(e);a&&a!==el;a=a.parentElement)if(mdcNested(a))return false; return true;}
// Whether element e (one MDC_UNIT matches) is a unit: not a loose list item (its paragraphs are units of their own), not a raw
// HTML block inside a run (the run is one), not the code box of the front matter (the front matter is one).
/** @param {Element} e */
function mdcIsUnit(e){return !(e.tagName==='LI'&&[...e.children].some(c=>c.tagName==='P'))&&!(e.classList.contains('md-html')&&e.closest('.md-html-run'))
  &&!(e.tagName==='PRE'&&e.closest('.md-front'));}
// A unit's kind as its tag: display math (MATH) and the front matter (FRONT) apart from a code block and a raw HTML block, so
// none of them pairs with another. Pure over the DOM.
/** @param {HTMLElement} el */
function mdcTag(el){return el.classList.contains('md-front')?'FRONT':el.classList.contains('md-math-block')?'MATH':el.tagName;}
// Whether a unit of tag is a block of lines (a code block, display math, the front matter): its lines, spaces and all, are its
// words. Pure.
/** @param {string} tag */
function mdcLined(tag){return tag==='PRE'||tag==='MATH'||tag==='FRONT';}
// The lines of a block of lines, each as it is (without its line end). Pure over the DOM.
/** @param {HTMLElement} el */
function mdcLines(el){return [...el.querySelectorAll('.ln')].map(l=>String(l.textContent||'').replace(/\n$/,''));}
// The comparable blocks of a drawn side, in document order (pure over the DOM): every paragraph, heading, code block, display
// math, front matter, table row, rule and raw HTML placeholder, and a list item whose text is its own (a tight list's). A
// raw HTML run is one unit. Each has its tag, its key, its text, its source lines, the parts of its key that are not words
// and the very boxes it sits in (grp: its box elements, outermost first - which quote, which list, mdcRegroup).
// The key is everything the block shows: its text with its inline structure (shape: emphasis, code, links, images with their
// alt text, a hidden character's box with the character, a table cell's alignment), the boxes it sits in (box: a quote, a
// list - a numbered one with its first number), its images' tree paths and its links' targets. So the same words in bold, out
// of a quote, in a list renumbered or in a column aligned the other way are another block - changed in place, as are an
// image's new alt text, a link's new target and a hidden character put in or taken out. What the renderer adds that shows
// nothing is not in it (mdcShape): the line spans, the copies of an emphasis or a link it opens again after a line break
// inside it, an inline formula's code box per source line - a paragraph rewrapped, inside bold, a link or a formula too, is
// the same block. An alt text is compared with its white space folded, as it is drawn.
/** @param {HTMLElement} root @returns {MdcUnit[]} */
function mdcUnits(root){const out=/** @type {MdcUnit[]} */([]);
  for(const x of root.querySelectorAll(MDC_UNIT)){const el=/** @type {HTMLElement} */(x); if(!mdcIsUnit(el))continue;
    const tag=mdcTag(el),text=mdcText(el,tag),cont=/** @type {Set<Element>} */(new Set()),shape=mdcShape(el,tag,cont);
    const grp=mdcBoxEls(el,root),refs=mdcRefs(el,'a,[data-anchor],.md-rel',cont),pics=mdcRefs(el,'.md-pic,.md-img'),box=mdcBoxes(grp),alts=[...el.querySelectorAll('img')].filter(i=>mdcOwnPart(el,i)).map(i=>(i.getAttribute('alt')||'').replace(/\s+/g,' ').trim()).join('\u0001');
    const lo=+(el.dataset.lo||el.dataset.rLo||0),hi=+(el.dataset.hi||el.dataset.rHi||lo);
    out.push({el,tag,key:[tag,box,shape,pics,refs].join('\u0001'),text,pics,shape,box,grp,alts,lo,hi});}
  return out;}
// The boxes unit el sits in below the drawn root, outermost first: the elements. Pure over the DOM.
/** @param {HTMLElement} el @param {HTMLElement} root @returns {Element[]} */
function mdcBoxEls(el,root){const out=[]; for(let a=el.parentElement;a&&a!==root;a=a.parentElement)out.unshift(a); return out;}
// Those boxes (mdcBoxEls) as one string: each box's tag, a numbered list's with the number it starts at (OL5). Pure over the DOM.
/** @param {Element[]} grp */
function mdcBoxes(grp){return grp.map(a=>a.tagName==='OL'?'OL'+(a.getAttribute('start')||'1'):a.tagName).join('>');}
// The name an inline element goes by in a block's structure (mdcShape) and a word's place (mdcToks): its tag, and for code
// its kind too (inline math and an inline HTML tag are code boxes of their own). Pure over the DOM.
/** @param {Element} e */
function mdcInl(e){return e.tagName.toLowerCase()+(e.tagName==='CODE'&&e.className?'.'+e.className:'');}
// A unit's inline structure as one string: its text, whitespace folded, with every inline element around its part as a mark
// (<strong>…</strong>, <code.md-math>…</code.md-math>, an image as <img alt>, a hidden character's box as <cc char>, a table
// cell with its alignment as <td right>), a list item's nested blocks and the screen reader's words left out. What the
// renderer adds and nothing shows is no structure: the line spans it puts round each source line, the shallow copies of the
// emphasis and links open at a line break that it opens again on the next line's span (mdInline), and the code box it draws
// for each source line of an inline formula (math_inline, one per line) - an emphasis or a link that starts right where one
// of the same kind and target ends is one run (mdcRun), and so is a formula's piece after the last one's, white space alone
// between them. So a paragraph wrapped on other lines, inside bold, a link or a formula too, reads the same. A link's copy
// goes in cont (when given), so it is not counted twice (mdcRefs). A block of lines' shape is its language (a code block's
// fence's info word) and its lines exactly as they are (mdcCode). Pure over the DOM but for cont.
/** @param {HTMLElement} el @param {string} tag @param {Set<Element>} [cont] */
function mdcShape(el,tag,cont){if(mdcLined(tag))return mdcCode(tag==='PRE'?el.dataset.lang||'':'',mdcLines(el));
  const out=/** @type {(string|{t:string,to:string})[]} */([]);
  const walk=(/** @type {Node} */n)=>{for(const c of n.childNodes){if(c.nodeType===3){if(c.nodeValue)out.push(c.nodeValue); continue;} if(c.nodeType!==1)continue;
    const e=/** @type {HTMLElement} */(c); if(el.tagName==='LI'&&mdcNested(e)||e.classList.contains('sr-only'))continue;
    if(e.classList.contains('cc')){out.push('\u0002cc '+(e.textContent||'')+'\u0003'); continue;}
    if(e.classList.contains('ln')&&e.tagName==='SPAN'){walk(e); continue;}
    const t=mdcInl(e); if(t==='img'){out.push('\u0002img '+(e.getAttribute('alt')||'')+'\u0003'); continue;}
    const to=mdcRun(e)?'\u0001'+mdcTo(e):t==='code.md-math'?'':null; let j=out.length-1;
    if(t==='code.md-math')while(j>=0&&typeof out[j]==='string'&&!/\S/.test(/** @type {string} */(out[j])))j--;   // a formula's pieces: one line end apart
    const last=out[j];
    if(to!==null&&typeof last==='object'&&last.t===t&&last.to===to){out.splice(j,1); if(cont&&to)cont.add(e); walk(e); out.push(last); continue;}   // the same run, on the next line
    const al=/^T[DH]$/.test(e.tagName)?(/(?:^|\s)md-al-(left|right|center)(?:\s|$)/.exec(e.className)||[])[1]:'';
    out.push('\u0002'+t+(al?' '+al:'')+'\u0003'); walk(e); out.push({t,to:to===null?'\u0000':to});}};
  walk(el); return out.map(x=>typeof x==='string'?x:'\u0002/'+x.t+'\u0003').join('').replace(/\s+/g,' ').trim();}
// Whether inline element e is one the renderer opens again after a line break inside it (mdInline's stack): an emphasis, a
// strikethrough, a link - an inert one (.md-rel) too. Pure over the DOM.
/** @param {HTMLElement} e */
function mdcRun(e){return /^(STRONG|EM|S|A)$/.test(e.tagName)||e.tagName==='SPAN'&&e.classList.contains('md-rel');}
// Where a link element points (its target, as mdcRefs names it; '' for an emphasis). Pure over the DOM.
/** @param {HTMLElement} e */
function mdcTo(e){return e.dataset.tipUrl||e.getAttribute('href')||e.dataset.anchor||'';}
// A block of lines' inline structure: its language (a code block's fence's info word, '' for any other) and its lines, spaces
// and all, serialized without ambiguity (JSON after a marker no other shape starts with) - so a code block whose body or
// language changed is another block, an empty fence ([]) is not one holding a blank line (['']), and no character in a
// language or a line can make two different blocks read alike. Pure.
/** @param {string} lang @param {string[]} lines */
function mdcCode(lang,lines){return '\u0002pre\u0003'+JSON.stringify([lang,lines]);}
// The language a code block's shape (mdcCode) carries, '' for any other shape. Pure.
/** @param {string} shape */
function mdcLang(shape){if(!shape.startsWith('\u0002pre\u0003'))return ''; try{return String(JSON.parse(shape.slice(5))[0]);}catch{return '';}}
// What changed in a block changed in place, beyond the words marked in it: its own change (mdcWhyOwn), then the boxes split
// or joined at it (how, mdcRegroup's) - '' when only its words changed (the marked words say what). Pure.
/** @param {MdcUnit} o @param {MdcUnit} n @param {string[]} [how] */
function mdcWhy(o,n,how){const box=(how||[]).map(h=>h==='split'?tr('인용·목록이 둘로 갈라짐'):tr('인용·목록이 하나로 합쳐짐'));
  return [mdcWhyOwn(o,n),...box].filter(Boolean).join(' · ');}
// What changed in a block changed in place whose text stayed: its inline structure, an image's alt text, a table cell's
// alignment, the list numbering, the boxes it sits in, a block of lines' language or spaces - '' when its words changed (the
// marked words say what). Pure.
/** @param {MdcUnit} o @param {MdcUnit} n */
function mdcWhyOwn(o,n){if(o.text!==n.text)return '';
  if(o.alts!==n.alts)return tr('그림 대체 글이 바뀜');
  if(o.tag==='PRE'&&o.shape!==n.shape)return mdcLang(o.shape)!==mdcLang(n.shape)?tr('코드 언어가 바뀜'):tr('코드의 공백·들여쓰기가 바뀜');
  if(mdcLined(o.tag)&&o.shape!==n.shape)return tr('줄의 공백·들여쓰기가 바뀜');
  if(o.shape!==n.shape&&mdcUnaligned(o.shape)===mdcUnaligned(n.shape))return tr('표 칸 정렬이 바뀜');
  if(o.shape!==n.shape)return tr('글자 모양(굵게·기울임·코드·링크)이 바뀜');
  if(o.box!==n.box)return o.box.replace(/OL\d+/g,'OL')===n.box.replace(/OL\d+/g,'OL')?tr('목록 번호가 바뀜'):tr('인용·목록 안팎으로 자리가 바뀜');
  return '';}
// A shape (mdcShape) without its table cells' alignment. Pure.
/** @param {string} shape */
function mdcUnaligned(shape){return shape.replace(/(\u0002t[dh]) (?:left|right|center)\u0003/g,'$1\u0003');}
// A unit's own text: a table row's cells joined with ' | ', a list item's without its nested blocks, a block of lines' lines,
// whitespace folded; a hidden character is in it (its box keeps it for the screen reader).
/** @param {HTMLElement} el @param {string} tag */
function mdcText(el,tag){if(el.tagName==='TR')return [...el.children].map(c=>(c.textContent||'').replace(/\s+/g,' ').trim()).join(' | ');
  if(mdcLined(tag))return mdcLines(el).join('\n').replace(/\s+/g,' ').trim();
  let s=''; const walk=(/** @type {Node} */n)=>{for(const c of n.childNodes){if(c.nodeType===3)s+=c.nodeValue; else if(c.nodeType===1&&!(el.tagName==='LI'&&mdcNested(/** @type {Element} */(c))))walk(c);}};
  walk(el); return s.replace(/\s+/g,' ').trim();}
// What a unit's images (sel '.md-pic,.md-img': tree path or alt text) or links (their targets) point at, in order - its own
// (mdcOwnPart: not those of a quote, a table or a list nested in a list item, which are in those blocks' keys); a link the
// renderer opened again after a line break inside it (skip, from mdcShape) is the link before it, not counted again.
/** @param {HTMLElement} el @param {string} sel @param {Set<Element>} [skip] */
function mdcRefs(el,sel,skip){const out=[];
  for(const x of el.querySelectorAll(sel)){const e=/** @type {HTMLElement} */(x);
    if(!mdcOwnPart(el,e)||skip&&skip.has(e))continue;
    out.push(e.dataset.path||e.dataset.tipUrl||e.getAttribute('href')||e.dataset.anchor||e.textContent||'');}
  return out.join(' ');}
// ---------------- Comparing sequences
// A compare's work budget (MDC_WORK steps), spent by mdcLcs, mdcOps and mdcWordMarks.
/** @typedef {{left:number}} MdcBudget */
/** @returns {MdcBudget} */
function mdcBudget(){return {left:MDC_WORK};}
// The longest common subsequence of a and b (eq tests two items) as ops in order - {t:'eq',a,b}, {t:'del',a}, {t:'ins',b} -
// its common ends taken first, and within each gap the deletions before the insertions. Its table's cells are spent from
// budget (when given); past MDC_DIFF_CELLS or what the budget has left the middle is all deleted and inserted (never a wrong
// match) and the budget is spent out, so the compare pairs nothing more. Pure but for the budget.
/** @template T @param {T[]} a @param {T[]} b @param {(x:T,y:T)=>boolean} eq @param {MdcBudget} [budget] @returns {{t:string,a:number,b:number}[]} */
function mdcLcs(a,b,eq,budget){const ops=[]; let s=0; while(s<a.length&&s<b.length&&eq(a[s],b[s]))s++;
  let ea=a.length,eb=b.length; while(ea>s&&eb>s&&eq(a[ea-1],b[eb-1])){ea--; eb--;}
  for(let i=0;i<s;i++)ops.push({t:'eq',a:i,b:i});
  const n=ea-s,m=eb-s;
  if(budget)budget.left-=a.length+b.length;   // the ends just walked
  if(n*m>MDC_DIFF_CELLS||budget&&n*m>budget.left){if(budget&&n*m)budget.left=0;
    for(let i=s;i<ea;i++)ops.push({t:'del',a:i,b:-1}); for(let j=s;j<eb;j++)ops.push({t:'ins',a:-1,b:j});}
  else{if(budget)budget.left-=n*m; const w=m+1,L=new Uint32Array((n+1)*w);
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)L[i*w+j]=eq(a[s+i],b[s+j])?L[(i+1)*w+j+1]+1:Math.max(L[(i+1)*w+j],L[i*w+j+1]);
    let i=0,j=0; while(i<n&&j<m){if(eq(a[s+i],b[s+j])){ops.push({t:'eq',a:s+i,b:s+j}); i++; j++;}
      else if(L[(i+1)*w+j]>=L[i*w+j+1]){ops.push({t:'del',a:s+i,b:-1}); i++;} else{ops.push({t:'ins',a:-1,b:s+j}); j++;}}
    for(;i<n;i++)ops.push({t:'del',a:s+i,b:-1}); for(;j<m;j++)ops.push({t:'ins',a:-1,b:s+j});}
  for(let k=0;k<a.length-ea;k++)ops.push({t:'eq',a:ea+k,b:eb+k});
  return ops;}
// The words and marks of a text (pure): letters and digits together, every other visible character alone.
/** @param {string} s */
function mdcWordsOf(s){return String(s).match(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu)||[];}
// How alike two texts are, from their words (mdcWordsOf, found once per block however many blocks it is weighed against):
// twice the words they share over all their words (1 for two empty texts). Pure.
/** @param {string[]} a @param {string[]} b */
function mdcSimWords(a,b){if(!a.length&&!b.length)return 1; const m=new Map(); let c=0;
  for(const w of a)m.set(w,(m.get(w)||0)+1); for(const w of b){const k=m.get(w)||0; if(k){c++; m.set(w,k-1);}} return 2*c/(a.length+b.length);}
const MDC_PAIR=0.4;   // the likeness above which a taken-out block and an added one of the same kind in one gap are one block changed in place
const MDC_MOVE_MIN=6;   // the fewest characters a block taken out and an identical one added elsewhere need to count as one moved block
// The block ops of two sides (pure over the units, but for the budget): mdcLcs over the keys, then in each gap between
// unchanged blocks a block taken out and a block added of the same tag, alike enough and in order, become one block changed
// in place ({t:'mod'}); then a block taken out and an identical one added anywhere else are one block moved ({t:'from'} where
// it was, {t:'to'} where it is now). A heading moves at any length, any other block from MDC_MOVE_MIN characters. Weighing a
// pair spends its words from budget; once it is spent no more pairs are weighed - the rest stay taken out and added. Last, two
// kept blocks a quote or list split or joined between are changed in place too (mdcRegroup, their ops' how).
/** @param {MdcUnit[]} ou @param {MdcUnit[]} nu @param {MdcBudget} [budget] */
function mdcOps(ou,nu,budget){budget=budget||mdcBudget(); const raw=mdcLcs(ou,nu,(x,y)=>x.key===y.key,budget),out=[]; let i=0;
  const words=new Map(),wordsOf=(/** @type {MdcUnit} */u)=>{let w=words.get(u); if(!w){w=mdcWordsOf(u.text); words.set(u,w);} return w;};
  while(i<raw.length){if(raw[i].t==='eq'){out.push(raw[i++]); continue;}
    const gap=[]; while(i<raw.length&&raw[i].t!=='eq')gap.push(raw[i++]);
    const dels=gap.filter(o=>o.t==='del'),ins=gap.filter(o=>o.t==='ins'),pair=new Map(); let from=0;
    weigh: for(const d of dels)for(let x=from;x<ins.length;x++){const n=ins[x];
      if(budget.left<=0)break weigh;
      if(nu[n.b].tag!==ou[d.a].tag||nu[n.b].pics!==ou[d.a].pics){budget.left--; continue;}
      const a=wordsOf(ou[d.a]),b=wordsOf(nu[n.b]); budget.left-=a.length+b.length+1;
      if(mdcSimWords(a,b)>=MDC_PAIR){pair.set(d,n); from=x+1; break;}}
    let di=0,ni=0; while(di<dels.length||ni<ins.length){const d=dels[di],n=ins[ni];
      if(d&&pair.has(d)){const p=pair.get(d); if(n&&n!==p){out.push(n); ni++; continue;} out.push({t:'mod',a:d.a,b:p.b}); di++; ni++; continue;}
      if(d){out.push(d); di++; continue;} out.push(n); ni++;}}
  const added=new Map(); out.forEach((o,k)=>{if(o.t!=='ins')return; const u=nu[o.b]; if(!/^H/.test(u.tag)&&u.text.length<MDC_MOVE_MIN)return;
    const l=added.get(u.key)||[]; l.push(k); added.set(u.key,l);});
  out.forEach(o=>{if(o.t!=='del')return; const l=added.get(ou[o.a].key); if(!l||!l.length)return; const k=/** @type {number} */(l.shift()),to=out[k];
    o.t='from'; o.b=to.b; to.t='to'; to.a=o.a;});
  mdcRegroup(ou,nu,out); return out;}
// The boxes split or joined between blocks kept on both sides (eq, mod) that come one after the other among those kept: two
// that shared a box on one side and not on the other while each still sits in boxes of the same kinds - one quote become
// two (a blank line between its paragraphs), a list cut in two by another bullet (- then *), two quotes or lists joined
// into one. No key can say it: a key holds the kinds of a block's boxes, never where a box begins or ends, so an item added
// at a list's top changes no other item. A split that a block added or moved in between makes, standing in neither of
// their boxes (a paragraph put between two items), is that block's own change: nothing more is marked. Both blocks of a
// split or a join become blocks changed in place (an eq op a mod) whose op says how ('split', 'merge'; mdcWhy). Only the
// quote and list boxes count (MDC_REGROUP): the words name those, and they are the boxes that split or join with no block
// changing. A table cannot: the second of two tables starts with a header row of its own, so a split or a join adds,
// takes out or changes that row (th cells for td), and that row says it - two tables joined are not "quotes or lists".
// Pure over the units' boxes (grp: which boxes, by identity; box: their kinds, one for each) but for the ops it marks.
/** @param {MdcUnit[]} ou @param {MdcUnit[]} nu @param {{t:string,a:number,b:number,how?:string[]}[]} ops */
function mdcRegroup(ou,nu,ops){const kept=ops.filter(o=>o.t==='eq'||o.t==='mod'),memo=/** @type {Map<MdcUnit,{g:unknown,t:string}[]>} */(new Map());
  // a unit's quote and list boxes, outermost first: each box (by identity) and its kind (a numbered list's start aside)
  const own=(/** @type {MdcUnit} */u)=>{let r=memo.get(u); if(r)return r; const k=u.box?u.box.split('>'):[]; r=[];
    (u.grp||[]).forEach((g,i)=>{const t=String(k[i]||'').replace(/^OL\d+$/,'OL'); if(MDC_REGROUP.test(t))r.push({g,t});}); memo.set(u,r); return r;};
  // how many of those boxes two units of one side share from the outside in
  const shared=(/** @type {MdcUnit} */x,/** @type {MdcUnit} */y)=>{const a=own(x),b=own(y); let d=0; while(d<a.length&&d<b.length&&a[d].g===b[d].g)d++; return d;};
  // the kinds of a unit's d outermost quote and list boxes, null when it sits in fewer
  const kinds=(/** @type {MdcUnit} */u,/** @type {number} */d)=>{const k=own(u); return k.length>=d?k.slice(0,d).map(x=>x.t).join('>'):null;};
  const alike=(/** @type {MdcUnit} */o,/** @type {MdcUnit} */n,/** @type {number} */d)=>{const k=kinds(o,d); return k!==null&&k===kinds(n,d);};
  const mark=(/** @type {{t:string,how?:string[]}} */o,/** @type {string} */how)=>{if(o.t==='eq')o.t='mod'; const l=o.how||(o.how=[]); if(!l.includes(how))l.push(how);};
  for(let i=1;i<kept.length;i++){const p=kept[i-1],q=kept[i],was=shared(ou[p.a],ou[q.a]),now=shared(nu[p.b],nu[q.b]),d=Math.max(was,now);
    if(was===now||!alike(ou[p.a],nu[p.b],d)||!alike(ou[q.a],nu[q.b],d))continue;   // a block that left or entered a box: its own change (mdcWhyOwn)
    let cut=false; if(was>now)for(let j=p.b+1;j<q.b&&!cut;j++)cut=shared(nu[j],nu[p.b])<=now&&shared(nu[j],nu[q.b])<=now;
    if(!cut){const how=was>now?'split':'merge'; mark(p,how); mark(q,how);}}}
// ---------------- Marking words inside a block changed in place
// A word of a unit: a run of a text node (node, s..e), or a whole element (el) - a hidden character's box, or in a block of
// lines one line. w is what it reads (a box's character, a line's text), f the inline elements it sits in below the unit (so a
// word that only became bold is another word), sp whether white space came before it (so taken-out words put back keep it).
/** @typedef {{node:Text|null,el:HTMLElement|null,s:number,e:number,w:string,f:string,sp:boolean}} MdcTok */
// The words of a unit as they sit in its DOM (a list item's own text only); a block of lines' lines are its words. Pure over
// the DOM.
/** @param {HTMLElement} el @returns {MdcTok[]} */
function mdcToks(el){const out=/** @type {MdcTok[]} */([]); let sp=false;
  if(mdcLined(mdcTag(el))){for(const ln of el.querySelectorAll('.ln')){const x=/** @type {HTMLElement} */(ln); out.push({node:null,el:x,s:0,e:0,w:String(x.textContent||'').replace(/\n$/,''),f:'',sp:true});} return out;}
  const walk=(/** @type {Node} */n,/** @type {string} */f)=>{for(const c of n.childNodes){
    if(c.nodeType===3){const v=String(c.nodeValue||''); let at=0;
      for(const m of v.matchAll(/[\p{L}\p{N}_]+|[^\s\p{L}\p{N}_]/gu)){const s=/** @type {number} */(m.index); if(/\s/.test(v.slice(at,s)))sp=true;
        out.push({node:/** @type {Text} */(c),el:null,s,e:s+m[0].length,w:m[0],f,sp}); sp=false; at=s+m[0].length;}
      if(/\s/.test(v.slice(at)))sp=true; continue;}
    if(c.nodeType!==1)continue; const e=/** @type {HTMLElement} */(c);
    if(el.tagName==='LI'&&mdcNested(e)||e.classList.contains('sr-only'))continue;
    if(e.classList.contains('cc')){out.push({node:null,el:e,s:0,e:0,w:e.textContent||'',f,sp}); sp=false; continue;}
    walk(e,e.classList.contains('ln')&&e.tagName==='SPAN'?f:f+'/'+mdcInl(e));}};
  walk(el,''); return out;}
// Marks the words of a block changed in place: the added words of the new block (ins), and the taken-out words of the old one
// put back into it where they were, struck through (del) - text with its hidden characters boxed again (mdcEl). A word in a
// text node is wrapped where it is; a hidden character's box is wrapped whole; a line of a block of lines has its content
// wrapped, and a taken-out line comes back as a line of its own. Edits in a text node run from its end to its start, so the
// offsets still to come stay right. Past the compare's budget the block stays marked as changed with no words marked.
/** @param {HTMLElement} oldEl @param {HTMLElement} newEl @param {MdcBudget} [budget] */
function mdcWordMarks(oldEl,newEl,budget){if(budget&&budget.left<=0)return;
  const a=mdcToks(oldEl),b=mdcToks(newEl),ops=mdcLcs(a,b,(x,y)=>x.w===y.w&&x.f===y.f,budget),lined=mdcLined(mdcTag(newEl));
  /** @type {{node:Text,s:number,e:number,kind:string,text?:string}[]} */
  const edits=[]; /** @type {{el:HTMLElement,kind:string}[]} */ const wraps=[];
  /** @type {{at:HTMLElement|null,after:boolean,text:string}[]} */ const puts=[];
  const mark=(/** @type {MdcTok[]} */ts,/** @type {string} */kind)=>{let k=0; while(k<ts.length){const t=ts[k];
      if(!t.node){if(t.el)wraps.push({el:t.el,kind}); k++; continue;}
      let j=k; while(j+1<ts.length&&ts[j+1].node===t.node)j++; edits.push({node:t.node,s:t.s,e:ts[j].e,kind}); k=j+1;}};
  let gone=/** @type {MdcTok[]} */([]);
  // the taken-out words before new word bAt (or after the last one), as one struck-through run: a block of lines' as lines of
  // their own; other words with the white space they had between them, and a space after the run when the word it goes
  // before has one before it (before the run when it goes after the last word and had one before it)
  const flushGone=(/** @type {number} */bAt)=>{if(!gone.length)return; const at=b[bAt],last=b[b.length-1];
    const words=lined?gone.map(t=>t.w).join('\n')+'\n':gone.map((t,i)=>(i&&t.sp?' ':'')+t.w).join('');
    const before=words+(!lined&&at&&at.sp?' ':''),after=(!lined&&last&&gone[0].sp?' ':'')+words;
    if(at&&at.node)edits.push({node:at.node,s:at.s,e:at.s,kind:'put',text:before});
    else if(at)puts.push({at:at.el,after:false,text:before});
    else if(last&&last.node)edits.push({node:last.node,s:last.e,e:last.e,kind:'put',text:after});
    else puts.push({at:last?last.el:null,after:true,text:after});
    gone=[];};
  let bi=0; for(const o of ops){if(o.t==='eq'){flushGone(o.b); bi=o.b+1; continue;} if(o.t==='del'){gone.push(a[o.a]); continue;} flushGone(o.b); mark([b[o.b]],'ins'); bi=o.b+1;}
  flushGone(bi);
  // one edit per run of adjacent added words in one text node
  const merged=[]; for(const x of edits){const p=merged[merged.length-1]; if(p&&x.kind==='ins'&&p.kind==='ins'&&p.node===x.node&&/^\s*$/.test(String(x.node.nodeValue||'').slice(p.e,x.s))){p.e=x.e; continue;} merged.push(x);}
  const byNode=new Map(); for(const x of merged){const l=byNode.get(x.node)||[]; l.push(x); byNode.set(x.node,l);}
  for(const [node,l] of byNode){l.sort((p,q)=>q.s-p.s||(p.kind==='put'?1:-1));
    for(const x of l){if(x.kind==='put'){const rest=node.splitText(x.s); /** @type {Node} */(rest.parentNode).insertBefore(mdcEl('del',x.text||''),rest); continue;}
      const mid=node.splitText(x.s); mid.splitText(x.e-x.s); const w=mdcEl(x.kind==='ins'?'ins':'del',''); /** @type {Node} */(mid.parentNode).insertBefore(w,mid); w.appendChild(mid);}}
  // a block that had no word left (an emptied paragraph, an emptied code block) takes the put-back words at its end
  const tail=lined?newEl.querySelector('code')||newEl:newEl;
  for(const p of puts){const d=mdcEl('del',p.text); if(!p.at)tail.appendChild(d); else if(p.after)p.at.after(d); else p.at.before(d);}
  for(const x of wraps){const w=mdcEl(x.kind==='ins'?'ins':'del','');
    if(!x.el.classList.contains('ln')){x.el.before(w); w.appendChild(x.el); continue;}
    // a line: its content, up to its line end (the end stays outside, so the mark ends with the line's text)
    const end=x.el.lastChild,nl=end&&end.nodeType===3&&/\n$/.test(String(end.nodeValue||''))?/** @type {Text} */(end).splitText(String(end.nodeValue).length-1):null;
    w.append(...[...x.el.childNodes].filter(c=>c!==nl)); x.el.insertBefore(w,nl);}}
// A link of a block changed in place whose target the other side's block does not have: marked like an added (new side) or a
// taken-out word (old side), its tip saying the target changed - a link's words can stay while where it goes changes. A list
// item's own links only (mdcOwnPart): a nested block's are that block's.
/** @param {HTMLElement} oldEl @param {HTMLElement} newEl */
function mdcLinkMarks(oldEl,newEl){const sel='a,.md-rel,[data-anchor]',to=(/** @type {Element} */e)=>{const x=/** @type {HTMLElement} */(e); return x.dataset.tipUrl||x.getAttribute('href')||x.dataset.anchor||'';};
  const olds=[...oldEl.querySelectorAll(sel)].filter(e=>mdcOwnPart(oldEl,e)),news=[...newEl.querySelectorAll(sel)].filter(e=>mdcOwnPart(newEl,e)),ot=new Set(olds.map(to)),nt=new Set(news.map(to));
  for(const e of news){const t=to(e); if(t&&!ot.has(t)){e.classList.add('mdc-wl'); /** @type {HTMLElement} */(e).dataset.tip=tl('링크 대상이 바뀜 · {to}',{to:ccPlain(t)});}}
  for(const e of olds){const t=to(e); if(t&&!nt.has(t))e.classList.add('mdc-wl-del');}}
// A word mark (ins, del) holding text, each character that would hide or reorder it in its box (ccHtml), as the drawn text has.
/** @param {string} tag @param {string} text */
function mdcEl(tag,text){const e=document.createElement(tag); e.className='mdc-w'; if(text)setHtml(e,ccHtml(text)); return e;}
// ---------------- Laying the marks
// Marks unit element el as a change of kind (ins, del, mod, move): its tint and, for a screen reader, the kind before its text.
// why, for a block changed in place whose words stayed, says what did change - read with the kind and shown as its tip.
/** @param {HTMLElement} el @param {string} kind @param {string} [why] */
function mdcMark(el,kind,why){el.classList.add('mdc-'+kind); el.dataset.mdc=kind; if(why){el.dataset.mdcWhy=why; el.dataset.tip=why;}
  const s=document.createElement('span'); s.className='sr-only'; s.textContent=tr({ins:'더한 블록',del:'뺀 블록',mod:'고친 블록',move:'옮긴 블록'}[kind]||'')+(why?' ('+why+')':'')+': ';
  if(el.tagName==='TR'){const c=el.firstElementChild; if(c)c.prepend(s);} else if(el.tagName!=='HR')el.prepend(s);}
// The element a taken-out list item leaves behind in one column: its own text, without the nested blocks (units of their own,
// put back into it when they are taken out too, mdcPlace). Its own nodes are moved, never copied: an image keeps the load and
// error handlers the renderer gave it (mdImage), so it gets its size or falls back to its alt text as in the document view.
/** @param {MdcUnit} u */
function mdcOwn(u){if(u.el.tagName!=='LI')return u.el; const c=/** @type {HTMLElement} */(u.el.cloneNode(false));
  for(const x of [...u.el.childNodes])if(!(x.nodeType===1&&mdcNested(/** @type {Element} */(x))))c.appendChild(x); return c;}
/** @param {Element} e @param {Element} root */
function mdcBox(e,root){const p=e.parentElement; return !p||p===root?'root':p.tagName;}
// The boxes of the two sides that stand for each other: an old element -> the new side's elements that stand for it. A block
// kept as it was or changed in place stands for its old self, and so does each box it sits in for the old block's box at the
// same height while their tags agree (mdcPair); a block taken out, a moved block's old place and the shallow copy of a box made
// for them stand for what they were put back for (mdcPlace). A moved block's new place stands for nothing on the old side.
/** @typedef {Map<Element,Element[]>} MdcBoxes */
/** @param {MdcBoxes} boxes @param {Element} o @param {Element} n */
function mdcStand(boxes,o,n){const l=boxes.get(o); if(!l)boxes.set(o,[n]); else if(!l.includes(n))l.push(n);}
/** @param {MdcBoxes} boxes @param {HTMLElement} o @param {HTMLElement} n @param {HTMLElement} oroot @param {HTMLElement} nroot */
function mdcPair(boxes,o,n,oroot,nroot){
  for(let a=/** @type {Element|null} */(o),b=/** @type {Element|null} */(n);a&&b&&a!==oroot&&b!==nroot&&a.tagName===b.tagName;a=a.parentElement,b=b.parentElement)mdcStand(boxes,a,b);}
// The child of box that holds e (e itself, or the box's child it sits in), or null when e is not inside box.
/** @param {Element} e @param {Element} box */
function mdcChildOf(e,box){let x=/** @type {Element|null} */(e); while(x&&x.parentElement!==box)x=x.parentElement; return x;}
// Puts el - a block taken out of the old side (its old place: ref, in oroot), or a moved block's old place - into the new side's
// root, inside the very boxes ref sat in: the nearest of ref's old boxes that something on the new side stands for (boxes; the
// column when none) - of those, the one prev (the last block laid) or else next (the next new block) is in - takes it, inside
// shallow copies of the boxes between (a deleted item's nested list, a deleted table's body), right after the part of it that
// holds prev, else before the part that holds next, else at its end. A box is judged by what it stands for, never by its tag
// alone: a nested list is not the list around it, and a list item's paragraph does not join the item before it. Returns el, the
// next block's prev.
/** @param {HTMLElement} el @param {HTMLElement} ref @param {HTMLElement} oroot @param {HTMLElement|null} prev @param {HTMLElement|null} next @param {HTMLElement} root @param {MdcBoxes} boxes */
function mdcPlace(el,ref,oroot,prev,next,root,boxes){mdcStand(boxes,ref,el);
  let node=/** @type {HTMLElement} */(el),a=ref.parentElement;
  for(;a&&a!==oroot&&!boxes.has(a);a=a.parentElement){const c=/** @type {HTMLElement} */(a.cloneNode(false));
    delete c.dataset.lo; delete c.dataset.hi; c.appendChild(node); mdcStand(boxes,a,c); node=c;}
  const l=a&&a!==oroot?/** @type {Element[]} */(boxes.get(a)):[root],box=l.find(b=>!!prev&&b.contains(prev))||l.find(b=>!!next&&b.contains(next))||l[0];
  const p=prev&&prev!==box?mdcChildOf(prev,box):null,q=!p&&next?mdcChildOf(next,box):null;
  if(p)p.after(node); else if(q)q.before(node); else box.appendChild(node);
  return el;}
// A moved block's place on the side it left: a slim line that says where it went.
/** @param {MdcUnit} u @param {MdcUnit} to */
function mdcGhost(u,to){const p=u.el.parentElement,tag=p&&/^(UL|OL)$/.test(p.tagName)?'li':p&&/^(TBODY|THEAD)$/.test(p.tagName)?'tr':'div',g=document.createElement(tag);
  g.className='mdc-ghost'; g.dataset.toLo=String(to.lo); g.dataset.n='1'; const t=tl('여기 있던 블록을 L{line}로 옮김',{line:to.lo}),box=tag==='tr'?document.createElement('td'):g;
  if(tag==='tr'){/** @type {HTMLTableCellElement} */(box).colSpan=Math.max(1,u.el.children.length); g.appendChild(box);} box.textContent=t; return g;}
// ---------------- The column
// The new side, with each block taken out put back where it was (struck through), each moved block's old place a slim line,
// the words of a block changed in place marked inside it. Returns the column.
/** @param {HTMLElement} oroot @param {HTMLElement} nroot @param {MdcUnit[]} ou @param {MdcUnit[]} nu @param {any[]} ops @param {MdcBudget} [budget] */
function mdcInline(oroot,nroot,ou,nu,ops,budget){let prev=/** @type {HTMLElement|null} */(null);
  const next=(/** @type {number} */k)=>{for(let x=k+1;x<ops.length;x++){const o=ops[x]; if(o.t!=='del'&&o.t!=='from')return nu[o.b].el;} return null;};
  const boxes=/** @type {MdcBoxes} */(new Map()); for(const o of ops)if(o.t==='eq'||o.t==='mod')mdcPair(boxes,ou[o.a].el,nu[o.b].el,oroot,nroot);   // before anything moves
  ops.forEach((o,k)=>{
    if(o.t==='eq'){prev=nu[o.b].el; return;}
    if(o.t==='ins'||o.t==='to'||o.t==='mod'){const el=nu[o.b].el; mdcMark(el,o.t==='ins'?'ins':o.t==='to'?'move':'mod',o.t==='mod'?mdcWhy(ou[o.a],nu[o.b],o.how):'');
      if(o.t==='to')el.dataset.mdcFrom=String(ou[o.a].lo);
      if(o.t==='mod'){mdcWordMarks(ou[o.a].el,el,budget); mdcLinkMarks(ou[o.a].el,el);} prev=el; return;}
    const u=ou[o.a]; if(o.t==='del'){const el=mdcOwn(u); mdcMark(el,'del'); prev=mdcPlace(el,u.el,oroot,prev,next(k),nroot,boxes); return;}
    // blocks moved together (a section) leave one line: the first one's, widened to their lines
    const last=k>0?ops[k-1]:null; if(last&&last.t==='from'&&prev&&prev.classList.contains('mdc-ghost')&&mdcBox(u.el,oroot)===mdcBox(ou[last.a].el,oroot)){
      const n=(+(prev.dataset.n||1))+1,lo=+(prev.dataset.toLo||0),hi=nu[o.b].hi; prev.dataset.n=String(n); mdcStand(boxes,u.el,prev);
      (prev.querySelector('td')||prev).textContent=tl('여기 있던 블록 {n}개를 L{lo}–L{hi}로 옮김',{n,lo,hi}); return;}
    prev=mdcPlace(mdcGhost(u,nu[o.b]),u.el,oroot,prev,next(k),nroot,boxes);});
  return nroot;}
// The gutter chips: each marked block's kind as a word at its first line, in the column's left gutter (a layer of the column,
// laid out again when its width changes). Not read aloud: the block itself carries its kind (mdcMark).
function mdcChips(){const root=MDC.root; if(!root)return; root.querySelectorAll(':scope>.mdc-chips').forEach(x=>x.remove());
  const layer=document.createElement('div'); layer.className='mdc-chips'; layer.setAttribute('aria-hidden','true'); const top=root.getBoundingClientRect().top;
  const items=/** @type {{y:number,cls:string,text:string}[]} */([]);
  for(const x of root.querySelectorAll('[data-mdc],.mdc-pin')){const e=/** @type {HTMLElement} */(x),r=e.getBoundingClientRect(); if(!r.height)continue;
    if(e.classList.contains('mdc-pin'))items.push({y:r.top-top,cls:'pin',text:e.dataset.mdcPin||''});
    if(e.dataset.mdc)items.push({y:r.top-top,cls:e.dataset.mdc,text:tr(MDC_LABEL[e.dataset.mdc]||'')});}
  items.sort((p,q)=>p.y-q.y||(p.cls==='pin'?1:-1)); let last=-1e9;
  for(const it of items){const c=document.createElement('span'); c.className='mdc-chip mdc-chip-'+it.cls; c.textContent=it.text;
    const y=Math.max(it.y,last+22); c.style.top=y+'px'; last=y; layer.appendChild(c);}
  root.appendChild(layer);}
// The unit elements of a drawn side in document order, as mdcUnits takes them (and a moved block's old place, ghosts).
/** @param {HTMLElement} root @param {boolean} ghosts @returns {HTMLElement[]} */
function mdcUnitEls(root,ghosts){return [...root.querySelectorAll(MDC_UNIT+(ghosts?',.mdc-ghost':''))].map(x=>/** @type {HTMLElement} */(x)).filter(mdcIsUnit);}
// ---------------- Showing a compare
// Git's lines [a,b] of a side (counted on LF alone, as a hunk counts them) as the screen's lines of that side (the side's
// lines, str.splitlines() - a form feed, a lone CR, U+2028 end a line there and not for git). map is the side's
// git_line_starts from GET /api/revision-source: [git line, screen line] pairs from which on git line g starts on screen line
// s + (g - g0), absent when the two agree - the last pair the line after the last git line, after the last screen line,
// when the last git line holds several; n the side's line count. Line a's first screen line to the last before line b+1's.
// Pure.
/** @param {number[][]|null|undefined} map @param {number} n @param {number[]} range @returns {number[]} */
function mdcGitRange(map,n,range){const [a,b]=range; if(!map||!map.length)return [a,b];
  const at=(/** @type {number} */g)=>{let s=g; for(const [g0,s0] of map){if(g0>g)break; s=s0+(g-g0);} return s;};
  const lo=at(a); return [lo,Math.max(lo,n?Math.min(n,at(b+1)-1):at(b+1)-1)];}
// The change groups in order: runs of marked blocks (a moved block's old place too) with nothing unchanged between them. The
// navigator steps through them.
/** @param {HTMLElement} root */
function mdcStops(root){const stops=/** @type {HTMLElement[][]} */([]); let cur=/** @type {HTMLElement[]|null} */(null);
  for(const e of mdcUnitEls(root,true)){const marked=!!e.dataset.mdc||e.classList.contains('mdc-ghost');
    if(marked){if(!cur){cur=[]; stops.push(cur);} cur.push(e);} else if(!/^(UL|OL|TABLE|TBODY|THEAD)$/.test(e.tagName))cur=null;}
  return stops;}
// The navigator (#revision-nav): where it is among the change groups, and its buttons pressed only where there is a next one.
function mdcDrawNav(){const n=MDC.stops.length,box=$('#revision-nav'); box.hidden=REV.format!==DIFF_FORMAT.RENDERED||!n;
  $('#mdc-at').textContent=!n?'':MDC.at<0?tl('바뀐 곳 {n}곳',{n}):tl('바뀐 곳 {at}/{n}',{at:MDC.at+1,n});
  /** @type {HTMLButtonElement} */($('#mdc-prev')).disabled=MDC.at<=0; /** @type {HTMLButtonElement} */($('#mdc-next')).disabled=MDC.at>=n-1;}
// Goes to change group i: brings its first block to a third of the pane's height and, with ring, rings the group for a moment.
/** @param {number} i @param {boolean} [ring] */
function mdcGo(i,ring){const g=MDC.stops[i]; if(!g)return; MDC.at=i; mdcDrawNav();
  document.querySelectorAll('#revision-rendered .mdc-cur').forEach(e=>e.classList.remove('mdc-cur')); if(ring)g.forEach(e=>e.classList.add('mdc-cur'));
  const pane=LAYOUT===LAYOUT_MODE.NARROW?$('#revision-body'):$('#revision-rendered'),r=g[0].getBoundingClientRect(),p=pane.getBoundingClientRect();
  pane.scrollTo({top:pane.scrollTop+r.top-p.top-Math.round(pane.clientHeight/3),behavior:'smooth'});}
/** @param {number} d */
function mdcStep(d){if(!MDC.stops.length)return; mdcGo(Math.min(MDC.stops.length-1,Math.max(0,MDC.at+d)),true);}
// Forgets the compare on screen (another commit, another document, the manuscript view).
function mdcClear(){++MDC.seq; MDC.key=''; MDC.line=''; MDC.said=null; MDC.stops=[]; MDC.at=-1; MDC.root=null; mdcParseStop(null);
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
// Parses and draws one side's lines (null: the file is not on that side - an empty document), as the document view draws a
// document: a NUL in the source is not parsed (MD_LIMIT.NUL). {root} or {why}; {root:null,why:''} once live() is false.
/** @param {string[]|null} lines @param {()=>boolean} live @returns {Promise<{root:HTMLElement|null,why?:string}>} */
async function mdcSide(lines,live){if(!lines)return {root:await mdcBuild([],[],live)};
  if(lines.some(l=>l.includes('\0')))return {root:null,why:mdLimitText(MD_LIMIT.NUL)};
  const res=await mdcParse(lines.join('\n')); if(!res||!live())return {root:null,why:''};
  if(!res.ok)return {root:null,why:mdLimitText(String(res.limit||MD_LIMIT.ERROR))};
  const root=await mdcBuild(res.tokens,lines,live); return root?{root}:{root:null,why:live()?mdLimitText(MD_LIMIT.ELEMENTS):''};}
// Shows the rendered compare of commit id (from base for a range) in #revision-rendered, for the visit seq of document k: reads
// both sides, draws and compares them, lays them out in one column, rings a pin's blocks when the view was opened for one
// ([변경 보기], then [그린 비교]), and says on the status line what changed.
/** @param {string} id @param {string} base @param {number} seq @param {string|null} k */
async function mdcShow(id,base,seq,k){const pane=$('#revision-rendered'),key=revKey(),mine=++MDC.seq,live=()=>mine===MDC.seq&&revisionCurrent(seq,k,id)&&MDC.key===key;
  MDC.key=key; MDC.line=''; MDC.said=null; MDC.stops=[]; MDC.at=-1; MDC.root=null; if(MDC.ro){MDC.ro.disconnect(); MDC.ro=null;}
  if(REV.target)REV.target.mdcMsg='';   // the guide line says what this compare finds, once it has (mdcTarget)
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
  const o=await mdcSide(r.old?r.old.lines:null,live); if(!live())return;
  const n=o.root?await mdcSide(r.new?r.new.lines:null,live):{root:null,why:''}; if(!live())return;
  if(!o.root||!n.root){pane.replaceChildren(mdcNote(tl('그려 비교하지 못했습니다 — {why}',{why:o.why||n.why||tr('파서를 쓸 수 없습니다')}))); mdcStatus(r,null); return;}
  const budget=mdcBudget(),ou=mdcUnits(o.root),nu=mdcUnits(n.root),ops=mdcOps(ou,nu,budget),counts={ins:0,del:0,mod:0,move:0};
  for(const x of ops){if(x.t==='ins')counts.ins++; else if(x.t==='del')counts.del++; else if(x.t==='mod')counts.mod++; else if(x.t==='to')counts.move++;}
  const pics=!!(o.root.querySelector('.md-pic')||n.root.querySelector('.md-pic'));   // before the layout moves the old side's blocks
  const view=mdcInline(o.root,n.root,ou,nu,ops,budget); MDC.root=view;
  const head=document.createElement('div'); head.className='mdc-legend'; head.setAttribute('aria-hidden','true');
  setHtml(head,html`<span class="mdc-chip mdc-chip-ins">${tr('더함')}</span><span class="mdc-chip mdc-chip-del">${tr('뺌')}</span><span class="mdc-chip mdc-chip-mod">${tr('고침')}</span><span class="mdc-chip mdc-chip-move">${tr('옮김')}</span>`);
  const frame=document.createElement('div'); frame.className='mdc-frame';
  // read and seen: the old side's images are not its own (D8 of ADR-0031) - a plain line, never the hidden legend's
  if(pics)frame.appendChild(mdcInfo(tr('그림은 두 판 모두 지금 원고 트리의 파일입니다 — 옛 판의 그림 파일은 읽지 않습니다.'),false));
  // the characters drawn in their boxes in the column (the new side and the blocks and words put back): the document view's notice
  const boxes=view.querySelectorAll('.cc').length; if(boxes)frame.appendChild(mdcInfo(txMarksText(boxes),false));
  if(budget.left<=0)frame.appendChild(mdcInfo(tr('바뀐 곳이 많아 블록을 짝짓지 않고 더한 블록과 뺀 블록으로만 표시합니다. 낱말 단위는 [소스 diff]에 있습니다.')));
  if(!r.old)frame.appendChild(mdcInfo(tr('이 커밋에서 파일이 처음 생겼습니다 — 모든 블록이 더한 블록입니다.')));
  if(!r.new)frame.appendChild(mdcInfo(tr('이 커밋에서 파일을 지웠습니다 — 모든 블록이 뺀 블록입니다.')));
  frame.append(head,view); pane.replaceChildren(frame);
  MDC.stops=mdcStops(view);
  const at=mdcTarget(tg0,scope,nu,r.new); mdcStatus(r,counts);
  if(!MDC.stops.length)frame.insertBefore(mdcInfo(tr('두 판의 그린 문서가 같습니다 — 줄 끝·공백·HTML 주석처럼 그리지 않는 곳만 바뀌었습니다. 정확한 변경은 [소스 diff]에 있습니다.')),head);
  requestAnimationFrame(()=>{if(!live())return; mdcChips();
    MDC.ro=window.ResizeObserver?new ResizeObserver(()=>{if(live())requestAnimationFrame(mdcChips);}):null;
    if(MDC.ro)MDC.ro.observe(view);
    if(at>=0)mdcGo(at); else{MDC.at=-1; mdcDrawNav();}});
  if(REV.target)revTargetNote();}
// A line above the compare: a status, read when it comes, unless status is false - then a standing note, read in its place.
/** @param {string} text @param {boolean} [status] */
function mdcInfo(text,status){const d=document.createElement('div'); d.className='mdc-info'; if(status!==false)d.setAttribute('role','status'); d.textContent=text; return d;}
// The status line of a compare: its two sides - a range's with the commits and files its source diff counted (REV.rangeN,
// once that answer is in) - and what changed. Kept (MDC.said) so the range's counts can join it when they come (mdcRestatus).
/** @param {any} r @param {{ins:number,del:number,mod:number,move:number}|null} c */
function mdcStatus(r,c){MDC.said={r,c}; const ends=(r.base?String(r.base).slice(0,8):tr('없음'))+' → '+String(r.id||'').slice(0,8),rn=REV.base?REV.rangeN:null;
  let t=rn?tl('{base} → {head} · 커밋 {commits}개 · 파일 {files}개',{base:String(r.base||'').slice(0,8),head:String(r.id||'').slice(0,8),commits:rn.commits,files:rn.files}):ends;
  if(r.merge_base)t+=' · '+tl('공통 조상 {mb}부터 비교',{mb:String(r.merge_base).slice(0,8)});
  if(c){const n=c.ins+c.del+c.mod+c.move; t+=' · '+(n?tl('바뀐 블록 {n}곳 — 고침 {mod} · 더함 {ins} · 뺌 {del} · 옮김 {move}',{n,mod:c.mod,ins:c.ins,del:c.del,move:c.move}):tr('바뀐 블록 없음'));}
  MDC.line=t; if(REV.format===DIFF_FORMAT.RENDERED)$('#revision-status').textContent=t;}
// The range's source diff has answered (loadRevisionSource): the compare's status line says its commits and files too.
function mdcRestatus(){if(MDC.said&&MDC.key===revKey())mdcStatus(MDC.said.r,MDC.said.c);}
// The pin the view was opened for ([변경 보기], then [그린 비교]): its blocks on the new side - those whose lines meet the
// pin's own changes (the server's hunks of the pin, scope) or else its lines - ringed in the review colour, the changed ones
// first. The compare is the whole commit's (ADR-0031 D6: the pin-only side is a later step), so when the pin owns part of it
// the line says so and points at [소스 diff], which shows the pin's hunks alone. Returns the change group to open at (-1:
// none), and leaves on the pin the line the guide says (tg.mdcMsg).
/** @param {RevTarget|null} tg @param {any} scope @param {MdcUnit[]} nu @param {any} side the new side GET /api/revision-source gave */
function mdcTarget(tg,scope,nu,side){const t=REV.target; if(t&&!tg)t.mdcMsg=tl('핀 #{id}의 커밋을 볼 때만 핀 자리를 표시합니다',{id:t.id}); if(!tg)return -1;
  // the pin's own hunks when it owns part of the commit; every hunk when it owns all of it; else its lines as they are now. A
  // hunk counts git's lines (LF only); the blocks count the screen's (the side's lines): mdcGitRange turns one into the other
  const lo=tg.lo||0,map=side&&side.git_line_starts,n=side&&side.lines?side.lines.length:0,hunks=(/** @type {string} */d)=>hunkRanges(d).map(r=>mdcGitRange(map,n,r));
  const part=!!scope&&scope.mode===SCOPE_MODE.PIN,ranges=part?hunks(scope.diff):scope&&scope.hunks>0?hunks(scope.whole):[[lo,tg.hi||lo]];
  const meets=nu.filter(u=>u.lo&&ranges.some(([a,b])=>u.hi>=a&&u.lo<=b)&&u.el.isConnected);
  const changed=meets.filter(u=>u.el.dataset.mdc);
  const shown=changed.length?changed:meets;
  shown.forEach(u=>{u.el.classList.add('mdc-pin'); u.el.dataset.mdcPin=tl('핀 #{id}',{id:tg.id});});
  tg.mdcMsg=(changed.length?tl('핀 #{id} 자리의 바뀐 블록 {n}곳을 보라 테두리로 표시했습니다',{id:tg.id,n:changed.length})+(scope&&scope.hunks>0?' ('+tr(scope.source===SCOPE_SOURCE.CHANGES?'에이전트가 기록한 줄':'핀 자리로 추정')+')':''):
    meets.length?tr('핀 자리의 블록은 이 커밋에서 바뀌지 않았습니다 — 그 블록을 보라 테두리로 표시했습니다'):tr('새 판에서 핀 자리를 찾지 못했습니다 — 정확한 줄은 [소스 diff]'))+
    (part?' · '+tr('그린 비교는 커밋 전체입니다 — 이 핀의 변경만은 [소스 diff]'):'');
  const first=shown[0]; if(!first)return -1;
  const i=MDC.stops.findIndex(g=>g.includes(first.el)); return i;}
