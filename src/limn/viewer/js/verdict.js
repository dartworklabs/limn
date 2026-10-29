// ------------------------------------------------ Verdict pins (docs/handbook/viewer.md §판정 핀, domain.md §판정 핀)
// A document may declare verdict words (its word file, served as `verdicts` on /api/docs and the full /api/meta). A verdict
// pin is a pin saved with one of them (`verdict`); its verdict and target are fixed when it is made. The viewer offers the
// words in two places: the composer's verdict row (#c-verdict-row), which saves the selection and its note as that verdict,
// and - on a figure document or a view-only PDF whose word file says page: true - a page verdict line, which saves a
// verdict about the page's whole target and never touches the composer. The words are the manuscript's: they are drawn as
// text, translate="no", and the names around them are put in the screen's language here.

const VD_ARM_MS=4000;   // how long a confirm word's first press waits for its second (D9)
// The verdict words of document doc (default: the one on screen): the full meta's for the document on screen (it is read with
// the document), else its /api/docs entry's; null without usable words.
/** @param {string|null} [doc] @returns {DocVerdicts|null} */
function docVerdicts(doc){const k=doc===undefined?DOC:doc,m=META&&(!k||META.doc===k)?META.verdicts:undefined,d=docInfo(k),v=m||(d&&d.verdicts);
  return v&&Array.isArray(v.choices)&&v.choices.length?v:null;}
// The page verdict line is drawn for a document whose words say page: true (the server sets it only for a figure document
// or a view-only PDF): the words, else null.
/** @returns {DocVerdicts|null} */
function pageVerdictsOn(){const v=docVerdicts(); return v&&v.page?v:null;}
// Whether this screen may make a verdict pin: a person who edits (a viewer reads, an agent never makes one, D11).
function canVerdict(){const r=META&&META.me&&META.me.role; return r!==ROLE.VIEWER&&r!==ROLE.AGENT;}
// A pin's verdict key, or null: a stored value counts only when it is key-shaped, as the server reads it (pins/verdict.py
// verdict_of: 1-16 letters, digits, '-' or '_'). Pure.
/** @param {Pin|null|undefined} p @returns {string|null} */
function verdictOf(p){const v=p&&p.verdict; return typeof v==='string'&&/^[\p{L}\p{N}_-]{1,16}$/u.test(v)?v:null;}
// The name a verdict key is shown by: its word's label in the word file of document doc (default: the one on screen) - a card
// of another document under [모든 문서] names its own document's word - else the key itself (a word the file no longer
// declares stays the pin's verdict).
/** @param {string} key @param {string|null} [doc] @returns {string} */
function verdictLabel(key,doc){const v=docVerdicts(doc),c=v&&v.choices.find(x=>x.key===key); return c?c.label:key;}
// A card's verdict badge, '판정 채택' (the question badge's shape; the words carry the meaning, no colour of its own), or null.
/** @param {Pin} p */
function verdictBadge(p){const k=verdictOf(p); if(!k)return null;
  return html`<span class="badge badge-verdict" data-tip="${tr('버튼으로 고른 판정입니다. 판정과 대상은 바뀌지 않고 메모만 고칠 수 있습니다')}">${tr('판정')} <span class="vd-w" translate="no">${verdictLabel(k,pdoc(p))}</span></span>`;}

// A verdict card's target by name, so a person finds the figure they gave a verdict: on a figure document the figure it is
// about (figureRootOf) - its title in the map ('[후보] PL26 · …') while the page it is on still shows it, else '그림 <id>'.
// null for any other pin or document: a view-only PDF's page and a LaTeX range are in the card's head already.
/** @param {Pin} p */
function verdictTarget(p){if(!verdictOf(p)||!isFigureKind(docKindOf(pdoc(p))))return null; const root=figureRootOf(p); if(!root)return null;
  const page=figurePageOf(root,p),pg=page&&META&&(!DOC||pdoc(p)===DOC)?META.pages[page-1]:null,title=pg&&pg.figure===root&&pg.title?pg.title:'';
  return html`<span class="vd-target" translate="no" data-tip="${tl('판정 대상 그림 · {id}',{id:root})}">${title||tl('그림 {id}',{id:root})}</span>`;}
// A card's pin with the overlaps its card reports: a verdict pin's overlap with another verdict pin is left out where the page
// verdict line shows both - the pins of the document on screen whose words say page: true, counted on the same page's line
// ('#4와 같은 범위' between two verdicts on one figure only repeats the order the line gives). Anywhere no line replaces it
// (page false, no usable word file, a card of another document under [모든 문서]) the badge stays, as do a verdict pin's
// overlaps with ordinary pins and ordinary pins' own. The pin itself, or a copy with the shorter rel.
/** @param {Pin} p @returns {Pin} */
function pvQuietRel(p){if(!verdictOf(p)||!p.rel||!p.rel.length||(DOC&&pdoc(p)!==DOC)||!pageVerdictsOn())return p;
  const t=pageTargetOf(p,META?META.kind:undefined),list=t?pageVerdictPins().get(t.page)||[]:[]; if(!list.some(x=>x.id===p.id))return p;
  const rel=p.rel.filter(x=>!list.some(q=>q.id===x.id)); return rel.length===p.rel.length?p:{...p,rel};}

// ---------------- The page's whole target (domain.md §쪽 전체 대상)
const WHOLE_PAGE=[0,0,1,1];
// The figure a figure document's pin is about: the root of its element's path (el.path[0]). A figure document is one figure a
// page, so a pin on any of its elements is about that figure (ADR-0022 D1). null without an element path.
/** @param {Pin} p @returns {string|null} */
function figureRootOf(p){const el=p.el,r=el&&Array.isArray(el.path)?el.path[0]:null; return typeof r==='string'&&r?r:null;}
// The page figure `root` is on now: by the map's page facts (meta pages[].figure) for the document on screen - null when the
// build's map no longer has that figure - else, without those facts (another document, a map that does not load), the page
// pin p's element is on in this build unless the build lost it.
/** @param {string} root @param {Pin} p @returns {number|null} */
function figurePageOf(root,p){const pages=META&&(!DOC||pdoc(p)===DOC)&&Array.isArray(META.pages)?META.pages:null;
  if(pages&&pages.some(x=>typeof x.figure==='string')){const i=pages.findIndex(x=>x.figure===root); return i>=0?i+1:null;}
  return elLost(p)?null:pinPlace(p).page;}
// Whether page `page` of the document on screen takes a verdict: every page but one its figure map marks verdict: false (a
// list, a question or a removed-figure page) - no page line, no composer verdict there.
/** @param {number} page */
function pageTakesVerdict(page){const pg=META&&Array.isArray(META.pages)?META.pages[page-1]:null; return !(pg&&pg.verdict===false);}
// What a pin's verdict is about when it is a page's whole target, and on which page it is now: on a figure document the
// figure its element belongs to (figureRootOf: el.path[0], whatever element of it the pin names), on the page that figure is
// on now (figurePageOf); on a view-only PDF a region pin over the whole page (each frac value within 1e-6 of [0, 0, 1, 1])
// placed on this PDF (est false). null for any other pin, and always on a LaTeX document. Pure but for the page lookups.
/** @param {Pin} p @param {string|undefined} kind @returns {{page:number,id:string}|null} */
function pageTargetOf(p,kind){
  if(isFigureKind(kind)){const root=figureRootOf(p),page=root?figurePageOf(root,p):null; return root&&page?{page,id:root}:null;}
  if(kind!==DOC_KIND.PDF||!isRegion(p)||p.est===true||!isFrac(p.frac))return null;
  const f=p.frac; return f.every((v,i)=>Math.abs(v-WHOLE_PAGE[i])<=1e-6)?{page:p.page,id:'page '+p.page}:null;}
// The kind of document doc: the meta's for the document on screen, else its /api/docs entry's.
/** @param {string} doc @returns {string|undefined} */
function docKindOf(doc){return (!DOC||doc===DOC)&&META?META.kind:(docInfo(doc)||{}).kind;}
// The target a verdict pin is about, as far as its stored place says it without a project's rules: the page's whole target
// (pageTargetOf: a figure document's figure, a view-only PDF's whole page) - the page line's targets; else, on a figure
// document, still its figure (el.path[0]) when the page it is on cannot be told (the figure left the map): one order, on no
// line; else, on a LaTeX document, its exact lines (file and range) unless their anchor is lost (stale). A key that pins
// about the same thing share, with whether it is a whole page's; null when the target cannot be resolved (a PDF region that
// is not its whole page, a figure pin without an element path, a lost line). Lines are only a candidate: the server
// re-matches an open pin's lines to the text now, never a closed one's, so two pins with the same key are about the same
// lines only when both are open or both were saved on the same text (sameLines).
/** @param {Pin} p @param {string|undefined} kind @returns {VerdictTarget|null} */
function verdictTargetOf(p,kind){const t=pageTargetOf(p,kind); if(t)return {key:'whole '+t.id,whole:true,page:t.page,lines:null};
  if(isFigureKind(kind)){const root=figureRootOf(p); return root?{key:'whole '+root,whole:false,page:p.page,lines:null}:null;}
  if(kind!==DOC_KIND.PDF&&!isRegion(p)&&p.file&&typeof p.lo==='number'&&typeof p.hi==='number'&&!p.stale)
    return {key:'lines '+p.file+':'+p.lo+'-'+p.hi,whole:false,page:p.page,lines:{open:pinState(p)===PIN_STATE.OPEN,anchor:anchorKey(p)}};
  return null;}
// A line pin's anchor - the text of its first and last lines when it was saved or last re-matched - as one string, or null.
/** @param {Pin} p @returns {string|null} */
function anchorKey(p){const a=p.anchor; return a&&typeof a.head==='string'&&typeof a.tail==='string'?JSON.stringify([a.head,a.tail,a.head_off,a.tail_off]):null;}
// Whether two pins on the same file and line numbers are about the same lines: both open (their lines are matched to the text
// now), or both saved on the same text (one anchor). A closed pin's numbers may be from an older text; without a shared
// anchor it is only its own target - never superseded, never another pin's current verdict.
/** @param {VerdictTarget} a @param {VerdictTarget} b */
function sameLines(a,b){const x=a.lines,y=b.lines; return !x||!y||(x.open&&y.open)||(!!x.anchor&&x.anchor===y.anchor);}
let VO_CACHE=/** @type {{lists:unknown[],by:Map<string,VerdictOrder>}} */({lists:[],by:new Map()});
// The verdict order of document doc (D4, docs/handbook/domain.md §순서): its verdict pins that are not deleted - open, awaiting
// review (one whose [확인] waits for its undo too: it leaves the review list at once, but it is still a verdict, while the list
// still has it - applyPinLists) and done - by resolved target (verdictTargetOf), newest (largest number) first, and for every
// pin its current verdict: its target's newest pin (on lines, the newest that sameLines says is about the same lines). The page
// verdict line (pageVerdictPins) and a card's '이전 판정' marker (verdictSuperseder) both read this one order, so they never
// disagree. Built once per change of the lists (an index, not a scan per card).
/** @param {string} doc @returns {VerdictOrder} */
function verdictOrder(doc){const lists=[OPEN_ALL,REVIEW_ALL,DONE_ALL,CONFIRMING_PIN.size,META&&META.kind,DOCS];
  if(VO_CACHE.lists.length!==lists.length||VO_CACHE.lists.some((x,i)=>x!==lists[i]))VO_CACHE={lists,by:new Map()};
  const hit=VO_CACHE.by.get(doc); if(hit)return hit;
  const kind=docKindOf(doc),groups=/** @type {Map<string,{t:VerdictTarget,all:{p:Pin,t:VerdictTarget}[]}>} */(new Map()),seen=new Set();
  for(const p of OPEN_ALL.concat(REVIEW_ALL,DONE_ALL,[...CONFIRMING_PIN.values()])){
    if(seen.has(p.id)||pdoc(p)!==doc||!verdictOf(p))continue; seen.add(p.id);
    const t=verdictTargetOf(p,kind); if(!t)continue; const g=groups.get(t.key)||{t,all:[]}; g.all.push({p,t}); groups.set(t.key,g);}
  const out=/** @type {VerdictOrder} */({groups:new Map(),cur:new Map()});
  groups.forEach((g,key)=>{g.all.sort((a,b)=>b.p.id-a.p.id);
    g.all.forEach(x=>{const c=x.t.lines?g.all.find(y=>y===x||sameLines(x.t,y.t)):g.all[0]; out.cur.set(x.p.id,(c||x).p);});
    const w=g.all.find(x=>x.t.whole);   // a whole target's page: the newest pin's that has one
    out.groups.set(key,{whole:!!w,page:w?w.t.page:g.t.page,pins:g.all.map(x=>x.p)});});
  VO_CACHE.by.set(doc,out); return out;}
// The verdict pins about each page's whole target on the document on screen, in the verdict order (verdictOrder), by page. A
// page whose pins name two figures (a re-render moved one away) keeps the figure of its newest pin.
/** @returns {Map<number,Pin[]>} */
function pageVerdictPins(){const out=/** @type {Map<number,Pin[]>} */(new Map());
  verdictOrder(DOC||DEFAULT_DOC).groups.forEach(g=>{if(!g.whole)return;
    const had=out.get(g.page); if(!had||had[0].id<g.pins[0].id)out.set(g.page,g.pins);});
  return out;}
// The current verdict that supersedes verdict pin p - the newest verdict about p's target when that is not p - or null: p is
// the current one, not a verdict pin, or its target cannot be resolved.
/** @param {Pin} p @returns {Pin|null} */
function verdictSuperseder(p){if(!verdictOf(p))return null; const c=verdictOrder(pdoc(p)).cur.get(p.id); return c&&c.id!==p.id?c:null;}
// A card's marker for a superseded verdict: '이전 판정 · #4로 대체됨', the number a link (the viewer's link look) to the current
// verdict's card. Neutral: a badge with no colour of its own - the words carry it. null for a current verdict or another pin.
/** @param {Pin} p */
function verdictOldMarker(p){const cur=verdictSuperseder(p); if(!cur)return null; const S='\u0001',id=cur.id;
  const parts=tl('이전 판정 · {ref}{p} 대체됨',{ref:S,p:josaRo(id)}).split(S);
  const desc=tl('같은 대상에 더 새 판정 #{id}{p} 있습니다 — 에이전트는 가장 새 판정만 실행합니다',{id,p:josa(id,'이','가')});
  return html`<span class="badge vd-old" role="note" aria-label="${desc}" data-tip="${desc}">${parts[0]}<span class="pin-ref vd-old-ref hit" role="link" tabindex="0" \
data-act="pin-ref" data-ref="${id}" aria-label="${tl('지금 판정 #{id} 카드로 갑니다',{id})}">#${id}</span>${parts[1]||''}</span>`;}
// The ids of the pins a page verdict line shows now (drawPageVerdicts): their page-size mark is not drawn and their card's
// [보기] goes to the line (marks, jumpPin).
let PV_SHOWN=/** @type {Set<number>} */(new Set());
let PV_KEYS=0;   // the page whose line the keys 1-5 act on (pvKeysPage), 0 for none
// A pin's state on the line: what the dot would say, in the line's words. The pin is the page target's newest verdict.
/** @param {Pin} p */
function pvStateWord(p){const st=pinState(p); if(st===PIN_STATE.REVIEW||CONFIRMING.has(p.id))return tr('검토 대기'); if(st===PIN_STATE.DONE)return tr('처리됨');
  return claimActive(p)?tr('처리 중'):tr('처리 대기');}

// ---------------- Two presses for a confirm word (D9)
// The armed first press: the word, where (VD_WHERE) and - on a page line - the page, with the document, build and (in the
// composer) selection it is bound to; null when nothing is armed.
let VD_ARM=/** @type {{key:string,label:string,where:string,page:number,doc:string|null,build:string,sel:string,kbd:boolean,timer:ReturnType<typeof setTimeout>}|null} */(null);
// What the composer's selection is, for the binding: its page, lines, rung, box and element.
function vdSelKey(){const d=COMPOSE.current; return d?JSON.stringify([d.page,d.lo,d.hi,d.scope,d.frac,d.elSel&&d.elSel.id]):'';}
// Whether the armed press is this word's button.
/** @param {string} key @param {string} where @param {number} page */
function vdArmedHere(key,where,page){const a=VD_ARM; return !!a&&a.key===key&&a.where===where&&(where===VD_WHERE.COMPOSER||a.page===page);}
// Whether an armed press still holds: the same document, build and (in the composer) selection.
function vdArmStill(a){return a.doc===DOC&&!!META&&a.build===META.pages_build&&(a.where!==VD_WHERE.COMPOSER||a.sel===vdSelKey());}
// Arms word key's button: it reads '<낱말> 확정' for VD_ARM_MS and a screen reader hears that the next press saves. kbd: armed
// by a key (verdictKey), which also lets it go when the reading page changes (pvStick).
/** @param {string} key @param {string} where @param {number} page @param {string} label @param {boolean} [kbd] */
function armVerdict(key,where,page,label,kbd){disarmVerdict(false);
  VD_ARM={key,label,where,page,doc:DOC,build:META?META.pages_build:'',sel:where===VD_WHERE.COMPOSER?vdSelKey():'',kbd:!!kbd,timer:setTimeout(()=>disarmVerdict(true,true),VD_ARM_MS)};
  vdRedraw(where); announce(tl('{word} — 한 번 더 누르면 저장합니다',{word:label}));}
// Lets an armed press go (Esc, another press, a press elsewhere, a new selection, document or build, the time running out).
// When it goes by itself or by Esc (say) a screen reader hears so - '삭제 확정을 풀었습니다' replaces '한 번 더 누르면 저장합니다'.
/** @param {boolean} redraw @param {boolean} [say] */
function disarmVerdict(redraw,say){const a=VD_ARM; if(!a)return; clearTimeout(a.timer); VD_ARM=null; if(redraw)vdRedraw(a.where);
  if(say)announce(tl('{word} 확정을 풀었습니다',{word:a.label}));}
/** @param {string} where */
function vdRedraw(where){if(where===VD_WHERE.COMPOSER)renderVerdictRow(); else drawPageVerdicts();}
// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else.
window.addEventListener('click',e=>{if(!VD_ARM)return; const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-act="verdict-save"],[data-act="pv-save"]'));
  if(!(b&&vdArmedHere(b.dataset.key||'',vdWhereOf(b),Number(b.dataset.page)||0)))disarmVerdict(true);},true);
window.addEventListener('keydown',e=>{if(e.key!=='Escape'||!VD_ARM)return; e.preventDefault(); e.stopImmediatePropagation(); disarmVerdict(true,true);},true);
/** @param {HTMLElement} b */
function vdWhereOf(b){return b.dataset.act==='verdict-save'?VD_WHERE.COMPOSER:VD_WHERE.PAGE;}

// One word's button: outline, a confirm word's text in the danger colour, '<낱말> 확정' while armed. Its name says what it
// saves about ('채택 판정으로 저장 — 3쪽'); the word is the manuscript's, so the button is translate="no" and its name is put
// in the screen's language here.
// Its description says what a press does at once: in the composer the selection and note become that verdict's pin, on a page
// line a new verdict pin for the page.
// Off: a composer's button is disabled; a page line's waits for its page's save (aria-disabled, verdictPress ignores it) and
// keeps the focus a keyboard press left on it - a disabled button would drop it to the page.
// kn: on the line of the page the keys act on (PV_KEYS), the word's key 1-5 - drawn after the word as a key hint (data-kn,
// generated text on a mouse screen only, so the button's text stays the word), said in its description and as
// aria-keyshortcuts; 0 elsewhere.
/** @param {VerdictChoice} c @param {string} where @param {number} page @param {string} target @param {boolean} off @param {number} [kn] */
function vdButton(c,where,page,target,off,kn){const armed=vdArmedHere(c.key,where,page),line=where!==VD_WHERE.COMPOSER;
  const name=armed?tl('{word} 확정 — 한 번 더 누르면 저장합니다',{word:c.label}):tl('{word} 판정으로 저장 — {target}',{word:c.label,target});
  const fig=where===VD_WHERE.COMPOSER&&!!figureVerdictRoot(COMPOSE.current);
  let tip=armed?name:fig?tl('누르면 메모와 함께 이 그림 전체({target})의 {word} 판정 핀으로 바로 저장합니다',{word:c.label,target}):where===VD_WHERE.COMPOSER?tl('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다',{word:c.label}):tr('누르면 이 쪽에 새 판정 핀을 저장합니다');
  if(kn)tip+=' · '+tl(c.confirm?'단축키 {key} (두 번)':'단축키 {key}',{key:kn});
  return html`<button type="button" class="vd-b hit${c.confirm?' vd-confirm':''}${armed?' armed':''}" translate="no" data-act="${where===VD_WHERE.COMPOSER?'verdict-save':'pv-save'}" \
data-key="${c.key}" data-page="${page}" aria-label="${name}" data-tip="${tip}"${kn?html` data-kn="${kn}" aria-keyshortcuts="${kn}"`:''}${off?line?html` aria-disabled="true"`:html` disabled`:''}>\
<span class="lbl">${armed?tl('{word} 확정',{word:c.label}):c.label}</span></button>`;}
// Gives the focus back to the button it was on after a redraw (an armed press redraws its buttons).
/** @param {HTMLElement|null} f */
function vdRefocus(f){if(!f||document.contains(f)||!f.dataset||!f.dataset.act)return;
  const sel=f.dataset.ref?'#doc .pv [data-act="'+f.dataset.act+'"][data-ref="'+CSS.escape(f.dataset.ref)+'"]'   // a line's '#N' link or its earlier link
    :'[data-act="'+f.dataset.act+'"][data-key="'+CSS.escape(f.dataset.key||'')+'"][data-page="'+(f.dataset.page||'0')+'"]';
  const b=/** @type {HTMLElement|null} */(document.querySelector(sel));
  if(b)b.focus({preventScroll:true});}
// A press on a verdict button: a confirm word arms on the first press and saves on the second while what it is bound to
// holds; any other word saves at once - the composer's through savePin, a page line's through savePageVerdict. how: 'key'
// for a digit key (verdictKey), 'kb' for a click the keyboard made (Enter or Space on the button); a page line's save from
// either puts the focus in its reason field.
/** @param {HTMLElement} b @param {string} [how] */
function verdictPress(b,how){const key=b.dataset.key||'',where=vdWhereOf(b),page=Number(b.dataset.page)||0,v=docVerdicts(),c=v&&v.choices.find(x=>x.key===key);
  if(!c||b.getAttribute('aria-disabled')==='true'||viewerBlocked())return;
  if(c.confirm&&!(vdArmedHere(key,where,page)&&VD_ARM&&vdArmStill(VD_ARM))){const f=/** @type {HTMLElement|null} */(document.activeElement);
    armVerdict(key,where,page,c.label,how==='key'); vdRefocus(f&&f.closest&&f.closest('.vd-btns')?f:null); return;}
  disarmVerdict(false);
  if(where!==VD_WHERE.COMPOSER){savePageVerdict(page,key,!!how); return;}
  renderVerdictRow(); if(COMPOSE.current)savePin(key);}   // while the pick runs the row is off (composer.css): nothing is queued

// ---------------- The composer's verdict row
// What the selection is, for a button's name: on a figure document the figure it is saved for (figureName), else its page's
// region, else its file and lines.
/** @param {Selection} d */
function selTarget(d){const fr=figureVerdictRoot(d); if(fr)return figureName(d.page,fr);
  return isRegion(d)?tl('{page}쪽 영역',{page:d.page}):d.name+' '+rng(d.lo,d.hi);}
// A figure's name for a person: its title in the map (meta pages[].title, '[후보] PL26 · …'), else '그림 <id>', with its page:
// '5쪽 · [후보] PL26 · …'. The title is only taken while that page still shows the figure.
/** @param {number} page @param {string} root */
function figureName(page,root){const pg=META&&Array.isArray(META.pages)?META.pages[page-1]:null,t=pg&&pg.figure===root&&pg.title?pg.title:'';
  return tl('{page}쪽',{page})+' · '+(t||tl('그림 {id}',{id:root}));}
// A figure's short name: its map title ('[후보] PL26 · …') while page `page` still shows it, else its id. For the composer's
// lead, the floating line and the status line's undo, which say which figure a verdict is for before and after the press.
/** @param {number} page @param {string} root */
function figureShort(page,root){const pg=META&&Array.isArray(META.pages)?META.pages[page-1]:null; return pg&&pg.figure===root&&pg.title?pg.title:root;}
// What page `page`'s verdict is about, by a short name: on a figure document its figure (figureShort of the map's figure),
// else the page ('7쪽').
/** @param {number} page */
function pageTargetShort(page){const pg=META&&Array.isArray(META.pages)?META.pages[page-1]:null;
  return META&&isFigureKind(META.kind)&&pg&&typeof pg.figure==='string'?figureShort(page,pg.figure):tl('{page}쪽',{page});}
// The figure a figure document's selection d is about - the root of its element's path - or null: not a figure document,
// or a pick without an element (a map it could not read).
/** @param {Selection|null} d @returns {string|null} */
function figureVerdictRoot(d){if(!d||!isFigureKind(docKindOf(d.doc||DOC||'')))return null; const el=d.elSel||d.el;
  const r=el&&Array.isArray(el.path)?el.path[0]:null; return typeof r==='string'&&r?r:null;}
// The pin body of a verdict saved from the composer on a figure document (ADR-0022 D2): a verdict is about the figure, so
// whatever element the selection names, it is saved as the verdict of the figure - the root of the element's path, the
// page's whole target, as a page line's press saves it. The root's rung of the pick's ladder when it has one (its lines,
// element and kind), else a region over the whole page naming the root (an element drawn without code, whose answer has
// no ladder). null when the selection is not about a figure (figureVerdictRoot): it is saved as it is.
/** @param {Selection} d @returns {Record<string, unknown>|null} */
function figureVerdictBody(d){const root=figureVerdictRoot(d); if(!root)return null;
  const lv=isRegion(d)?null:(d.levels||[]).find(l=>!!l.el&&Array.isArray(l.el.path)&&l.el.path.length===1&&l.el.path[0]===root&&l.el.id===root);
  if(lv)return figureFields({file:d.file,name:d.name,page:d.page,lo:lv.lo,hi:lv.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,quote:d.quote,pdf_build:d.pdf_build||undefined,scope:lv.level},lv.el,lv);
  return figureFields({page:d.page,frac:WHOLE_PAGE.slice(),quote:'',pdf_build:d.pdf_build||undefined},{id:root,path:[root],frac:WHOLE_PAGE.slice()},null);}
// The composer's verdict row (#c-verdict-row, after the note and its lines, before the kind row): '판정 바로 저장' and one
// button per word in file order. Shown for a document with words to a person who may make a verdict pin; its buttons are
// off, with the reason under them, while the kind is a question or [제안 수정] is on (a verdict pin is a fix request with
// no suggestion) and while the selection is still being found - really disabled, with the reason, also during a second pick
// over a selection (pick redraws the row when it starts).
function renderVerdictRow(){const row=$('#c-verdict-row'),v=docVerdicts(),d=COMPOSE.current;
  dropStaleRetry();
  // A figure page that takes no verdict (its map says verdict: false - a list or a question page) offers no word either.
  const show=!!v&&canVerdict()&&!$('#composer').hidden&&!(d&&isFigureKind(docKindOf(d.doc||DOC||''))&&!pageTakesVerdict(d.page)); row.hidden=!show;
  if(VD_ARM&&VD_ARM.where===VD_WHERE.COMPOSER&&(!show||!vdArmStill(VD_ARM)))disarmVerdict(false);
  if(!v||!show)return;
  const why=COMPOSE.picking&&!d?tr('위치를 찾는 중입니다'):KIND_NEW===KIND_REQ.QUESTION?tr('질문에는 판정을 붙이지 않습니다 — 아래에서 [수정 요청]을 고릅니다')
    :SG.on?tr('판정을 저장하려면 [제안 수정]을 끕니다'):'';
  const f=/** @type {HTMLElement|null} */(document.activeElement),inRow=!!f&&row.contains(f);
  // On a figure document the lead says whose verdict it is - the selected element's figure, by name ('· PL35 … 전체') -
  // whatever element is selected: a panel that shows another figure is still this page's figure's verdict.
  const fr=d?figureVerdictRoot(d):null,S='\u0001',sp=tl('{name} 전체',{name:S}).split(S);
  const scope=fr&&d?html`<span class="vd-scope"> · ${sp[0]}<span class="vd-fig" translate="no">${figureShort(d.page,fr)}</span>${sp[1]||''}</span>`
    :isFigureKind(docKindOf((d&&d.doc)||DOC||''))&&!d?html`<span class="vd-scope"> · ${tr('그림 전체')}</span>`:'';
  setHtml(row,html`<span id="c-verdict-l" class="vd-l">${tr('판정 바로 저장')}${scope}</span><span class="vd-btns">${v.choices.map(c=>vdButton(c,VD_WHERE.COMPOSER,0,d?selTarget(d):'',!!why||!d||COMPOSE.saving))}</span>\
${why?html`<span class="vd-why" id="c-verdict-why">${why}</span>`:''}`);
  if(why)row.setAttribute('aria-describedby','c-verdict-why'); else row.removeAttribute('aria-describedby');
  vdWrapFit(row.querySelector('.vd-btns'));
  if(inRow)vdRefocus(f);}
// A word group that wraps (the 280px panel in English with a word armed) keeps every button at its own width, left-aligned
// (.wrapped): stretched to share the row, a lone last word ran across the whole second row. Measured after drawing and when
// the row's width changes; the class changes how the buttons grow, never where they wrap, so it never measures itself again.
/** @param {Element|null} g */
function vdWrapFit(g){if(!g)return; const tops=new Set([...g.children].map(b=>Math.round(b.getBoundingClientRect().top)));
  g.classList.toggle('wrapped',tops.size>1);}
if(typeof ResizeObserver!=='undefined'){const row=document.getElementById('c-verdict-row');
  if(row)new ResizeObserver(()=>vdWrapFit(row.querySelector('.vd-btns'))).observe(row);}
// A failed verdict save's retry the composer no longer asks for (COMPOSE.intent moved since its press): it goes, and the
// failure's banner says so (verdictDropped). Run on every redraw of the verdict row, which every such change makes.
function dropStaleRetry(){const rv=COMPOSE.retryVerdict; if(!rv||rv.gen===COMPOSE.intent)return; COMPOSE.retryVerdict=null; verdictDropped();}
// The composer's failed-save banner when the verdict it was for is no longer asked for - dropped after the failure, or the
// intent changed while the request was out (savePin): '핀 저장 실패 — 선택했던 판정은 해제됐습니다 — ...'. [다시 저장] saves the
// selection as the composer has it, without the verdict; pressing the word again saves the verdict.
function verdictDropped(){const b=BANNERS.get(NOTICE_HOST.COMPOSER); if(!b||!b.save||$('#composer').hidden)return;
  bannerNote(NOTICE_HOST.COMPOSER,tl('{what} 실패',{what:tr('핀 저장')})+' — '+tr('선택했던 판정은 해제됐습니다 — 판정으로 저장하려면 판정 버튼을 다시 누릅니다'),NOTICE_KIND.ERR,null,{save:true,source:b.source});}
// The undo of a verdict pin's save (D10): the pin goes again - a withdrawn request - and the composer does not come back. When
// an agent claimed or closed it meanwhile it still goes, and the status line says its run may have started - one
// sentence with no ' — ', so the folded line shows all of it.
/** @param {number} id @returns {()=>Promise<boolean>} */
function verdictUndo(id){const undo=async()=>{let was=null;
    try{was=(await api('/api/pins/'+id,{what:'핀 읽기',silent:true})).data.pin;}catch(e){}
    const ok=await dropPin(id,true,undo);
    if(ok&&PV_REASON&&PV_REASON.id===id){PV_REASON=null; drawPageVerdicts();}   // a withdrawn verdict takes no reason
    if(ok&&was&&(claimActive(was)||pinState(was)!==PIN_STATE.OPEN))lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다',NOTICE_KIND.WARN);
    return ok;};
  return undo;}

// ---------------- The page verdict line (figure documents and view-only PDFs, page: true)
// The pin body a page verdict saves from the whole page's pick answer d (D7): on a figure document the rung whose element is
// the page's figure (el.path == [el.id]) - its lines and element - else a region answer whose element is that figure; on a
// view-only PDF the region answer as it is. null when a figure page gives neither. Pure but for the figure helpers.
/** @param {any} d @param {string|undefined} kind @returns {Record<string, unknown>|null} */
function pageVerdictBody(d,kind){const root=el=>!!el&&Array.isArray(el.path)&&el.path.length===1&&el.path[0]===el.id;
  if(isFigureKind(kind)){
    const lv=isRegion(d)?null:(d.levels||[]).find(l=>root(l.el));
    if(lv)return figureFields({file:d.file,name:d.name,page:d.page,lo:lv.lo,hi:lv.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
      frac:d.frac,quote:d.quote,pdf_build:d.pdf_build||undefined,scope:lv.level},lv.el,lv);
    if(isRegion(d)&&root(d.el))return figureFields({page:d.page,frac:d.frac,quote:d.quote,pdf_build:d.pdf_build||undefined},d.el,null);
    return null;}
  return isRegion(d)?{page:d.page,frac:d.frac,quote:d.quote,pdf_build:d.pdf_build||undefined}:null;}
const PV_BUSY=new Set();   // pages whose page verdict is being saved: their buttons wait for the answer
// A page line's last failed save, by page: said on the line that was pressed (pvLineHtml) as well as on the status line, until
// the next press on that line or another document or build. The document and build it was for come with it.
const PV_ERR=/** @type {Map<number,{text:string,doc:string|null,build:string}>} */(new Map());
// A reason with a verdict, in place: after a save on a page line, that line offers one optional line of text - '이유 (선택)' -
// for the new pin (the fast save and its undo stay as they are). It has the focus when the press came from the keyboard (a
// digit key, or Enter or Space on the button); after a click it waits to be pressed, never raising a phone's keyboard by
// itself. The session (PV_REASON) belongs to its pin, document and visit, and keeps what is typed (text), so the field comes
// back with it when the line is drawn anew (a rebuild) and follows its pin's page. Enter saves the text as the pin's note
// (the note edit a verdict pin takes, ADR-0021 D3) and Esc lets it go; either way the focus goes to the PDF area, not to a
// word that may be on a page out of view. Moving on - the reading page leaving the field's page after it was there, another
// save, another document - closes it and saves what was typed as Enter would, saying so in one line ('이유 저장됨 · PL16');
// an empty field just closes, as it does when the focus leaves it. The undo takes the field with the pin, its text unsaved.
let PV_REASON=/** @type {{page:number,id:number,key:string,doc:string|null,visit:any,text:string,focus:boolean,seen:boolean,listed:boolean}|null} */(null);
/** @param {number} page */
function pvReasonOn(page){const r=PV_REASON; return !!r&&r.page===page&&r.doc===DOC&&currentVisit(r.visit);}
// The pin a reason session is for, from the lists, or undefined.
/** @param {number} id */
function pvReasonPin(id){return OPEN_ALL.concat(REVIEW_ALL,DONE_ALL).find(p=>p.id===id);}
// Before a line is drawn: a session of another document or visit goes (its text saved, pvReasonLeave); one whose pin left
// the lists (undone or deleted elsewhere) goes unsaved; else it follows its pin to the page that pin's target is on now.
function pvReasonSync(){const r=PV_REASON; if(!r)return;
  if(r.doc!==DOC||!currentVisit(r.visit)){pvReasonLeave(); return;}
  if(!PINS_APPLIED_SEQ)return; const p=pvReasonPin(r.id);
  if(!p){if(r.listed)PV_REASON=null; return;}   // not listed yet right after its save; gone once it was
  r.listed=true; const t=pageTargetOf(p,META?META.kind:undefined); if(t)r.page=t.page;}
// Closes the field: Esc and Enter (after its save) give the focus to the PDF area, out of the line.
/** @param {boolean} pdf */
function pvReasonEnd(pdf){const f=document.querySelector('#doc .pv-reason'),had=!!f&&document.activeElement===f; PV_REASON=null; drawPageVerdicts();
  if(pdf||had)searchToPage();}
// Moving on: the session closes and what was typed is saved as Enter would, said in one line; an empty one just closes.
function pvReasonLeave(){const r=PV_REASON; if(!r)return; pvReasonEnd(false); const text=r.text.trim(); if(text)pvReasonWrite(r,text,true);}
// Writes text as reason session r's pin's note: the note edit with the pin's rev (read again when the lists do not hold the
// pin); a note someone wrote meanwhile is kept and the reason is added to it (note_append). A pin that is gone takes nothing.
// said: it is saved on moving on, and the status line says so with the target's name. Returns whether it was written.
/** @param {NonNullable<typeof PV_REASON>} r @param {string} text @param {boolean} said @returns {Promise<boolean>} */
async function pvReasonWrite(r,text,said){if(viewerBlocked())return false;
  let p=pvReasonPin(r.id); if(!p){try{p=(await api('/api/pins/'+r.id,{what:'핀 읽기',silent:true})).data.pin;}catch(e){p=undefined;}}
  if(!p||p.dropped_at){lineNote(tl('핀 #{id} 은 그사이 다른 곳에서 지워졌습니다',{id:r.id}),NOTICE_KIND.WARN); return false;}
  try{const body=p.note?{note_append:text}:{note:text,base_rev:p.rev};
    const {status,data}=await api('/api/pins/'+r.id+'/edit',{method:'POST',body,what:'이유 저장',where:NOTICE_HOST.LINE,expect:[409],intent:'reason'});
    if(status===409){const q=data&&data.pin; if(!q)return false;   // someone changed the pin meanwhile: their note stays
      await api('/api/pins/'+r.id+'/edit',{method:'POST',body:q.note?{note_append:text}:{note:text,base_rev:q.rev},what:'이유 저장',where:NOTICE_HOST.LINE,intent:'reason'});}
  }catch(e){return false;}   // api() said it on the status line
  const name=r.doc===DOC?pageTargetShort(r.page):'#'+r.id;
  if(said)lineNote(tl('이유 저장됨 · {target} — 판정 #{id}',{target:name,id:r.id}),NOTICE_KIND.OK,null,{life:NOTICE_LIFE.TIMER,literal:true});   // the target in the title: the folded line shows it
  else quietNote(tl('판정 #{id} 이유를 저장했습니다',{id:r.id}));
  if(r.doc===DOC)loadPins().catch(()=>{});
  return true;}
// Enter: the text saved as the note and the field closed (empty text is Esc). While the request is out the field waits; a
// failure leaves the text in it for another Enter.
/** @param {HTMLInputElement} f */
async function pvReasonSave(f){const r=PV_REASON; if(!r||f.disabled)return; const text=f.value.trim(); r.text=f.value;
  if(!text){pvReasonEnd(true); return;}
  f.disabled=true; const ok=await pvReasonWrite(r,text,false);
  if(PV_REASON!==r)return;   // closed meanwhile (moved on, the undo, another document): that path took the text
  if(ok)pvReasonEnd(true); else{f.disabled=false; f.focus({preventScroll:true});}}
$('#doc').addEventListener('input',e=>{const f=/** @type {HTMLInputElement} */(e.target); if(f.classList&&f.classList.contains('pv-reason')&&PV_REASON&&String(PV_REASON.id)===f.dataset.id)PV_REASON.text=f.value;});
$('#doc').addEventListener('keydown',e=>{const f=/** @type {HTMLInputElement} */(e.target); if(!f.classList||!f.classList.contains('pv-reason')||e.isComposing)return;
  if(e.key==='Enter'){e.preventDefault(); e.stopPropagation(); pvReasonSave(f);}
  else if(e.key==='Escape'){e.preventDefault(); e.stopPropagation(); pvReasonEnd(true);}});
$('#doc').addEventListener('focusout',e=>{const f=/** @type {HTMLInputElement} */(e.target); if(!f.classList||!f.classList.contains('pv-reason'))return;
  setTimeout(()=>{if(f.isConnected&&document.activeElement!==f&&!f.disabled&&!f.value.trim()&&PV_REASON&&String(PV_REASON.id)===f.dataset.id)pvReasonEnd(false);},0);});
// The key marks follow the focus: off on every line while a text field has it - digits typed there are text (pvKeysPage).
// (Another document closes the field through pvReasonSync, whose leave saves what was typed.)
document.addEventListener('focusin',()=>pvStickSoon()); document.addEventListener('focusout',()=>pvStickSoon());
// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build on screen, the body
// pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's selection and draft stay as
// they are. Every press makes a new pin (the same word twice is two pins - the agent runs one, D4 and D5). Saved: '#42 저장됨
// [되돌리기]' on the line for NOTICE_MS; a refusal or a failure is said on the status line and under the pressed line.
/** @param {number} page @param {string} key @param {boolean} [kb] - pressed from the keyboard: the reason field takes the focus */
async function savePageVerdict(page,key,kb){const pg=META&&META.pages[page-1]; if(!pg||PV_BUSY.has(page))return;
  const visit=captureVisit(),kind=META.kind,f=/** @type {HTMLElement|null} */(document.activeElement);
  const build=META.pages_build||'',fail=(/** @type {string} */text)=>{if(currentVisit(visit))PV_ERR.set(page,{text,doc:DOC,build});};
  let saved=false; PV_ERR.delete(page);
  let back=!!f&&!!f.closest&&!!f.closest('#doc .pv')&&f.dataset.act==='pv-save'&&f.dataset.key===key;   // a keyboard press: the focus comes back
  // ...unless it moved meanwhile to anything but that button (another page's word, a '#N' link, the panel): a redraw that puts
  // it back on the same word's button is no move.
  let away=false;   // the person put the focus anywhere else meanwhile: neither the button nor the reason field takes it back
  const moved=e=>{const t=/** @type {HTMLElement} */(e.target); if(!(t&&t.dataset&&t.dataset.act==='pv-save'&&t.dataset.key===key&&t.dataset.page===String(page))){back=false; away=true;}};
  document.addEventListener('focusin',moved);
  PV_BUSY.add(page); drawPageVerdicts();
  try{const d=(await api('/api/pick',{method:'POST',body:{page,x0:0,y0:0,x1:pg.pt_w,y1:pg.pt_h,frac:WHOLE_PAGE.slice(),pdf_build:META.pages_build||undefined,doc:DOC||undefined},
      what:'판정 저장',where:NOTICE_HOST.LINE})).data;
    if(!currentVisit(visit))return;
    if(d.error){const m=tl('{what} 실패',{what:tr('판정 저장')})+' — '+errText(d); lineNote(m,NOTICE_KIND.ERR,null,{source:'page-verdict'}); fail(m); if(d.pdf_build_gone)refreshDoc().catch(()=>{}); return;}
    const body=pageVerdictBody(d,kind);
    if(!body){lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다',NOTICE_KIND.WARN,null,{source:'page-verdict'}); fail(tr('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다')); return;}
    Object.assign(body,{note:'',doc:DOC||undefined,kind_req:KIND_REQ.FIX,assignee:ASSIGNEE_AGENT,verdict:key});
    const id=(await api('/api/pin',{method:'POST',body,what:'판정 저장',where:NOTICE_HOST.LINE})).data.id; saved=true;
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다',{id,word:verdictLabel(key),target:pageTargetShort(page)}),{label:'되돌리기',wait:true,fn:verdictUndo(id)},
      {pin:id,pending:true,label:tl('#{id} 저장됨 · {word}',{id,word:verdictLabel(key)})});
    if(currentVisit(visit)){pvReasonLeave(); PV_REASON={page,id,key,doc:DOC,visit,text:'',focus:!!kb,seen:pvReadingPage()===page,listed:false};}   // the reason field under it (another one's text saved first)
    await loadPins(); settleChip(chip);
  }catch(e){const x=/** @type {ApiError} */(e);   // api() said it on the status line: the pressed line says it too
    if(!saved)fail(tl('{what} 실패',{what:tr('판정 저장')})+' — '+(x&&x.data?errText(x.data)||('HTTP '+x.status):tr('서버에 닿지 않습니다')));}
  finally{document.removeEventListener('focusin',moved); PV_BUSY.delete(page); drawPageVerdicts();
    const rs=PV_REASON,r=rs&&rs.page===page&&rs.focus?/** @type {HTMLInputElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] .pv-reason')):null;
    if(rs&&r&&!away){rs.focus=false; r.focus({preventScroll:true});} else if(back)pvRefocus(page,key);}}
// Gives the focus back to word key's button on page `page`'s line after its save: the pressed button was disabled and redrawn
// while the request ran, which dropped the focus. Not when the person put the focus somewhere else meanwhile (savePageVerdict
// watches for that) or it is on something now.
/** @param {number} page @param {string} key */
function pvRefocus(page,key){const a=document.activeElement; if(a&&a!==document.body&&document.contains(a))return;
  const b=/** @type {HTMLButtonElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-save"][data-key="'+CSS.escape(key)+'"]'));
  if(b&&!b.disabled&&b.getAttribute('aria-disabled')!=='true')b.focus({preventScroll:true});}
// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and word,
// and who made it and when if that was someone else - the earlier open verdicts as a link ('앞선 판정 N건(처리하지 않음)'),
// and, for a person who may make one, a button per word. No pressed look: a verdict is a request until it is handled.
/** @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v */
function pvLineHtml(page,list,v){const cur=list&&list[0],earlier=list?list.slice(1).filter(p=>pinState(p)===PIN_STATE.OPEN):[];
  // Before the first pin list is applied (PINS_APPLIED_SEQ) the line knows no verdict yet: '판정 읽는 중…', buttons waiting.
  const loading=!PINS_APPLIED_SEQ;
  const k=cur&&verdictOf(cur),other=!!cur&&!!cur.author&&!isMe(cur.author);
  // One order for every state: '판정 #4 채택 · 처리 대기', then who made it and when if someone else did. The number is a link to
  // the card (the viewer's link style), the word is bold.
  // A claimed one names who has it: '처리 중(Agent B)' - the name after it is the pin's author.
  const S='\u0001',by=cur&&pinState(cur)===PIN_STATE.OPEN&&claimActive(cur)&&cur.claimed_by?who(cur.claimed_by):'',st=cur?pvStateWord(cur):'',sp=by?tl('처리 중({name})',{name:S}).split(S):[st];
  const text=cur&&k?html`<span class="pv-s">${tr('판정')} <span class="pin-ref pv-ref hit" role="link" tabindex="0" data-act="pin-ref" data-ref="${cur.id}" \
aria-label="${tl('지금 판정 #{id} 카드로 갑니다',{id:cur.id})}" data-tip="${tl('핀 #{id} 로 갑니다',{id:cur.id})}">#${cur.id}</span> <b class="vd-w" translate="no">${verdictLabel(k)}</b></span>\
<span class="pv-sep" aria-hidden="true">·</span><span class="pv-st">${sp[0]}${by?html`<span class="pv-by" translate="no">${by}</span>${sp[1]||''}`:''}</span>\
${other?html`<span class="pv-sep" aria-hidden="true">·</span><span class="pv-au" translate="no">${who(cur.author)}</span> ${relSpan(cur.at,'pv-at','')}`:''}\
${cur.note?html`<span class="pv-sep" aria-hidden="true">·</span><span class="pv-note" translate="no" data-tip="${cur.note}">${String(cur.note).split('\n')[0]}</span>`:''}`
    :html`<span class="pv-s pv-none">${tr(loading?'판정 읽는 중…':'판정 없음')}</span>`;
  const early=earlier.length?html`<button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" \
data-tip="${tr('이 쪽의 더 새 판정으로 대체되어 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다')}">${tl('이전 판정 {n}건 · 새 판정으로 대체됨',{n:earlier.length})}</button>`:'';
  // The reading page's line - the one that floats - names what it decides: '7쪽 · [후보] PL18 · …' (figureName), cut to fit.
  // Its two spans are on every line, empty and hidden but on the reading one: the line's children keep their places when
  // the reading page moves, so the morph (pvMorph) never takes a focused button out of the page.
  const rd=PV_READ===page,nm=rd?META&&isFigureKind(META.kind)&&META.pages[page-1]&&META.pages[page-1].figure?figureName(page,String(META.pages[page-1].figure)):tl('{page}쪽',{page}):'';
  const name=html`<span class="pv-fig" translate="no"${rd?'':html` hidden`}>${nm}</span><span class="pv-sep pv-fig-sep" aria-hidden="true"${rd?'':html` hidden`}>·</span>`;
  const busy=PV_BUSY.has(page)||loading,keys=PV_KEYS===page,target=tl('{page}쪽',{page});
  const btns=canVerdict()?html`<span class="vd-btns">${v.choices.map((c,i)=>vdButton(c,VD_WHERE.PAGE,page,target,busy,keys?i+1:0))}</span>`:'';
  // The line's last failed save, said where it was pressed (PV_ERR) - for the document and build on screen only.
  const e=PV_ERR.get(page),eo=!!e&&e.doc===DOC&&!!META&&e.build===(META.pages_build||'');
  const err=html`<span class="pv-err"${eo?'':html` hidden`}>${eo&&e?e.text:''}</span>`;   // always there, so the reason field after it keeps its place
  // The reason field after a save on this line (PV_REASON): one line, optional, Enter saves it as the pin's note.
  const rs=pvReasonOn(page)&&canVerdict()?/** @type {NonNullable<typeof PV_REASON>} */(PV_REASON):null;
  const why=rs?html`<input class="pv-reason" type="text" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="${rs.id}" value="${rs.text}" \
placeholder="${tr('이유 (선택) — Enter 저장 · Esc 건너뜀')}" aria-label="${tl('판정 #{id} 이유 (선택) — Enter 저장, Esc 건너뜀',{id:rs.id})}">`:'';
  return html`${name}<span class="pv-t">${text}${early}</span>${btns}${err}${why}`;}
// Draws page `page`'s line.
/** @param {HTMLElement} el @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v */
// The list redraws on every poll and many other changes, so a line is never rewritten: what changed is changed in place
// (pvMorph) - its words and links, a button's state - and every button, the '#N' link and the earlier link stay the same
// elements. A press whose down and up straddle a redraw still lands on its button (a rewritten one sent the click to the
// line), and the focus stays where it was, also on a '#N' whose number just changed. A line whose words are what it shows is
// left alone. Every verdict pin the line accounts for - the current one and the earlier ones - draws no page-size mark.
const PV_TEXT=/** @type {WeakMap<HTMLElement,string>} */(new WeakMap());   // what fillPv last wrote into each line
function fillPv(el,page,list,v){el.dataset.page=String(page); el.classList.toggle('reading',PV_READ===page); const cur=list&&list[0];
  if(cur)el.dataset.pin=String(cur.id); else delete el.dataset.pin; (list||[]).forEach(p=>PV_SHOWN.add(p.id));
  el.setAttribute('role','group'); el.setAttribute('aria-label',tl('{page}쪽 판정',{page}));
  const m=pvLineHtml(page,list,v); if(PV_TEXT.get(el)===m.text)return; PV_TEXT.set(el,m.text);
  const chip=el.querySelector(':scope>.nt-chip');   // a save's undo chip (drawChips) stays on its line; drawChips moves it if it is another pin's
  if(chip)chip.remove(); const next=document.createElement('div'); setHtml(next,m); pvMorphKids(el,next); if(chip)el.appendChild(chip);}
// Makes a's children b's, keeping every node that is the same kind in the same place (pvMorph).
/** @param {Node} a @param {Node} b */
function pvMorphKids(a,b){const ac=[...a.childNodes],bc=[...b.childNodes];
  bc.forEach((n,i)=>{if(i<ac.length)pvMorph(ac[i],n); else a.appendChild(n);}); ac.slice(bc.length).forEach(n=>n.remove());}
// Makes node a read as b: the same text, or the same element (tag, data-act and data-id - a reason field of another pin is
// another field, never one keeping the first pin's typed text) with b's attributes and children; another kind of node takes
// a's place.
/** @param {Node} a @param {Node} b */
function pvMorph(a,b){if(a.nodeType!==b.nodeType||a.nodeName!==b.nodeName||(a instanceof Element&&b instanceof Element&&(a.getAttribute('data-act')!==b.getAttribute('data-act')||a.getAttribute('data-id')!==b.getAttribute('data-id')))){
    /** @type {ChildNode} */(a).replaceWith(b); return;}
  if(!(a instanceof Element&&b instanceof Element)){if(a.nodeValue!==b.nodeValue)a.nodeValue=b.nodeValue; return;}
  [...a.attributes].forEach(x=>{if(!b.hasAttribute(x.name))a.removeAttribute(x.name);});
  [...b.attributes].forEach(x=>{if(a.getAttribute(x.name)!==x.value)a.setAttribute(x.name,x.value);});
  pvMorphKids(a,b);}
// The width of each line: its own page's, never past what the PDF area shows - a zoomed page scrolls sideways under a
// line that stays in view (sticky) and keeps its size; a page narrower than the widest has a line as narrow, under it. Then one rhythm for every page: when any page's line cannot hold its
// words and its buttons on one row (a phone, a folded cover), every line puts its buttons on a row of their own, at its
// start (#doc.pv-stack) - a short line beside a long one no longer keeps them at the end of its row. Measured only while the
// pages are laid out (the changes view hides them).
function sizePv(){const ir=pvInsetR(),room=innerW()-ir,doc=$('#doc'),lines=$$('#doc .pv');
  $('#left').style.setProperty('--pv-inset-r',ir+'px'); PV_INSET_R=ir;
  lines.forEach(e=>{const pg=document.getElementById('p'+e.dataset.page),w=pg?parseFloat(pg.style.width)||room:room; e.style.width=Math.round(Math.min(w,room))+'px';});
  if(!lines.length||!lines[0].getClientRects().length){if(!lines.length)doc.classList.remove('pv-stack'); return;}
  doc.classList.remove('pv-stack');
  // The reading line's figure name (pv-fig) comes and goes as the reading page moves: it never decides the rhythm.
  const wraps=lines.some(l=>{if(l.classList.contains('reading'))return false; const t=l.querySelector('.pv-t'),b=l.querySelector('.vd-btns');
    return !!t&&!!b&&b.getBoundingClientRect().top>=t.getBoundingClientRect().bottom-1;});
  doc.classList.toggle('pv-stack',wraps); lines.forEach(l=>vdWrapFit(l.querySelector('.vd-btns')));}
// Draws the page verdict line under every page after the pages, the pin lists or the build change. Without page verdicts
// every line goes and the marks draw every pin as before.
function drawPageVerdicts(){const v=pageVerdictsOn(),f=/** @type {HTMLElement|null} */(document.activeElement);
  const had=!!f&&!!f.closest&&!!f.closest('.pv');
  if(VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&(!v||!vdArmStill(VD_ARM)))disarmVerdict(false);
  PV_SHOWN=new Set();
  if(!v||!META){$$('#doc .pv').forEach(e=>e.remove()); return;}
  pvReasonSync(); const map=pageVerdictPins(); PV_READ=pvReadingPage(); PV_KEYS=pvKeysPage(PV_READ);
  $$('#doc .pg').forEach(pg=>{const page=+pg.dataset.page; let line=/** @type {HTMLElement|null} */(pg.nextElementSibling);
    if(!pageTakesVerdict(page)){if(line&&line.classList.contains('pv'))line.remove(); return;}   // the map says this page takes none
    if(!line||!line.classList.contains('pv')){line=document.createElement('div'); line.className='pv'; pg.after(line);}
    fillPv(line,page,map.get(page),v);});
  sizePv(); pvStick();
  if(had)vdRefocus(f);}
// Whether pin p's page verdict line shows it, so its page-size mark is not drawn (marks).
/** @param {Pin} p */
function pvShows(p){return PV_SHOWN.has(p.id);}
// A card's [보기] for a pin a line shows: its page comes into view with the line and the line flashes. The page and its line
// are one block (.pgw): centred when it fits the PDF area, else from the page's top - the line then floats at the area's
// bottom (scrolling to the sticky line itself would follow where it floats, not where it is). Returns whether it did.
/** @param {number} id */
function jumpPv(id){if(!PV_SHOWN.has(id))return false; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id)||DONE.find(x=>x.id===id);
  const t=p&&pageTargetOf(p,META?META.kind:undefined); if(!t)return false;
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);
  const flash=el=>{el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);};
  const line=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+t.page+'"]')); if(!line)return false;
  const block=/** @type {HTMLElement} */(line.parentElement),L=$('#left');
  block.scrollIntoView({behavior:SMOOTH,block:block.getBoundingClientRect().height<=L.clientHeight?'center':'start'}); flash(line); return true;}

// ---------------- The line that floats, and the keys (docs/handbook/viewer.md §판정 핀)
// Only the reading page's line floats: the page under the reading line, the one the section strip names and the keys act
// on (PV_READ). Its line (.reading) is sticky to the PDF area's bottom within its page's block (.pgw, pages.js buildDoc):
// while its own place is below the area it floats there over the page (.stuck: an edge that sets it off the page), and it
// names the figure it decides; at the page's end it settles under it. Every other line stays in its place - a next page's
// line floating as soon as that page's top edge came in showed a second '판정 없음' for a figure not yet in view, and put
// another figure's buttons under a resting mouse or thumb. It does not float while a selection is being written (the
// composer has its own verdict row, and the line would cover the selection - or on a phone the sheet) nor over an open
// phone sheet (CSS). pvStick follows the reading page and marks the floating line; run once a frame while the area scrolls.
function pvStick(){const lines=$$('#doc .pv'); if(!lines.length)return; const L=$('#left'),lr=L.getBoundingClientRect();
  if(!lr.height)return;
  const pad=getComputedStyle(L).paddingBottom; if(L.style.getPropertyValue('--pv-pad-b')!==pad)L.style.setProperty('--pv-pad-b',pad);   // the end padding a sticky line keeps clear of (components.css)
  if(pvInsetR()!==PV_INSET_R)sizePv();   // a panel came over the area, went, or changed its width
  const r=pvReadingPage(),k=pvKeysPage(r);
  if(PV_REASON&&PV_REASON.page===r)PV_REASON.seen=true;
  else if(PV_REASON&&PV_REASON.seen)pvReasonLeave();   // the reading page left the field's page: moving on
  // A key's armed confirm word belongs to the page it was read on: another reading page lets it go.
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==r)disarmVerdict(false,true);
  if(r!==PV_READ||k!==PV_KEYS){const was=[PV_READ,PV_KEYS]; PV_READ=r; PV_KEYS=k; const map=pageVerdictPins(),v=pageVerdictsOn();
    if(v)new Set([...was,r,k]).forEach(n=>{const e=/** @type {HTMLElement|null} */(n?document.querySelector('#doc .pv[data-page="'+n+'"]'):null); if(e)fillPv(e,n,map.get(n),v);});}
  lines.forEach(l=>{const pg=/** @type {HTMLElement|null} */(l.previousElementSibling); if(!pg)return; const b=l.getBoundingClientRect();
    l.classList.toggle('stuck',l.classList.contains('reading')&&b.bottom>lr.top&&b.top<lr.bottom&&b.top<pg.getBoundingClientRect().bottom+4);});}   // in its own place it stands 8px under the page
// What lies over the PDF area's right side, in px in from the area's content edge: a panel laid over it - the unfolded
// foldable's overlay panel, beside which the pages run on underneath - and its handle's touch area, as for a save chip
// (chipInRoom). 0 where the panel stands beside the area or at its bottom (a sheet). A line is never wider than the room
// left of them, and keeps out of them as it floats (sticky right, --pv-inset-r): its words would lie under the panel.
let PV_INSET_R=0;
function pvInsetR(){const L=$('#left'),R=$('#right'),G=$('#grip'); if(!L.getClientRects().length)return 0;
  const lr=L.getBoundingClientRect(),edge=lr.left+L.clientWidth-parseFloat(getComputedStyle(L).paddingRight); let right=edge;
  if(R&&R.getClientRects().length){const rr=R.getBoundingClientRect(); if(rr.left>lr.left+40&&rr.top<lr.bottom-40)right=Math.min(right,rr.left-4);}
  if(G&&G.getClientRects().length){const gr=G.getBoundingClientRect(),reach=Math.max(gr.width,parseFloat(getComputedStyle(G,'::after').width)||0);
    if(gr.left>lr.left+40)right=Math.min(right,gr.right-reach-4);}
  return Math.max(0,Math.round(edge-right));}
// The page under the reading line - the one the section strip and the page count name, readingDepth under the PDF area's
// top - while the pages are shown and the document has page lines; 0 otherwise. Read from the layout as it is now.
function pvReadingAt(){if(!pageVerdictsOn()||document.body.classList.contains('revision-open')||!$('#left').getClientRects().length)return 0;
  const a=topAnchor(readingDepth($('#left'))); return a?a.page:0;}
// The reading page when it has a line (pageTakesVerdict), else 0: its line floats and names its figure (PV_READ).
function pvReadingPage(){const n=pvReadingAt(); return n&&pageTakesVerdict(n)?n:0;}
// The page the keys 1-5 act on: reading page r while this screen may make a verdict, no selection is being written and no
// text field has the focus (its digits are text).
/** @param {number} r */
function pvKeysPage(r){return r&&canVerdict()&&$('#composer').hidden&&!typingNow()?r:0;}
let PV_READ=0;   // the reading page with a line: its line floats and names its figure
let PV_FRAME=0;
function pvStickSoon(){if(!PV_FRAME)PV_FRAME=requestAnimationFrame(()=>{PV_FRAME=0; pvStick();});}
$('#left').addEventListener('scroll',pvStickSoon,{passive:true});
addEventListener('resize',pvStickSoon);
new MutationObserver(pvStickSoon).observe(document.body,{attributes:true,attributeFilter:['class']});   // composing, the sheet, the band
if(typeof ResizeObserver!=='undefined'){const R=document.getElementById('right'); if(R)new ResizeObserver(pvStickSoon).observe(R);}   // the panel's width
// The keys: 1-5 press the document's verdict words in file order on the line of the page under the reading line, as a press
// on that button does - a confirm word arms on the first press and saves on the second while its page, document and build
// hold (verdictPress). The page is read from the layout at the key, not from the last frame: a key right after a scroll
// across a page's end would otherwise go to the page before - and confirm its armed word. A confirm word armed for another
// page is let go first. Not in a text field, not while a dialog or a popover is open, not while a selection is being
// written (the composer is open) or the changes view is shown, not with Ctrl, Alt or Meta (Alt+digit switches documents).
// On a page that takes no verdict a key says so on the status line, once. The button and its line say the key (vdButton kn).
/** @param {KeyboardEvent} e */
function verdictKey(e){if(e.defaultPrevented||e.repeat||e.isComposing||e.ctrlKey||e.metaKey||e.altKey||!/^[1-5]$/.test(e.key))return;
  const t=/** @type {HTMLElement|null} */(e.target);
  if(t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable))return;
  if(document.querySelector('dialog[open]')||!$('#page-pop').hidden||!$('#doc-pop').hidden||!$('#composer').hidden)return;
  const v=pageVerdictsOn(),n=+e.key,c=v&&v.choices[n-1],at=pvReadingAt(); if(!c||!at||!canVerdict())return;
  if(!pageTakesVerdict(at)){e.preventDefault(); lineNote('이 쪽은 판정을 받지 않습니다',NOTICE_KIND.INFO,null,{source:'verdict-key',life:NOTICE_LIFE.TIMER}); return;}
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==at)disarmVerdict(true,true);
  const b=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+at+'"] button[data-act="pv-save"][data-key="'+CSS.escape(c.key)+'"]'));
  if(!b)return; e.preventDefault(); verdictPress(b,'key');}
addEventListener('keydown',verdictKey);
