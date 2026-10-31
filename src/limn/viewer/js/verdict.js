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
// It is JSON with every object's keys in one order (jsonSortedKeys), so two anchors are one string exactly when they are the
// same JSON value, as the server's anchor_key compares them (limn.pins.verdict, #303): a hand-edited offset that is an object
// is one whatever order its keys were written in, and the list [0] and the string "[0]", or true and 1, stay apart.
/** @param {Pin} p @returns {string|null} */
function anchorKey(p){const a=p.anchor; return a&&typeof a.head==='string'&&typeof a.tail==='string'?JSON.stringify([a.head,a.tail,a.head_off,a.tail_off],jsonSortedKeys):null;}
// A JSON.stringify replacer that writes each object with its keys sorted - after the integer-like keys, which a JavaScript
// object always puts first in their numeric order - and an array or any other value as it is.
/** @param {string} _k @param {unknown} v @returns {unknown} */
function jsonSortedKeys(_k,v){if(!v||typeof v!=='object'||Array.isArray(v))return v; const o=/** @type {Record<string,unknown>} */(v);
  return Object.fromEntries(Object.keys(o).sort().map(k=>[k,o[k]]));}
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
// What an armed word says while it waits, with how long it waits: '삭제 — 4초 안에 한 번 더 누르면 저장합니다'.
/** @param {string} label */
function vdArmSaid(label){return tl('{word} — {sec}초 안에 한 번 더 누르면 저장합니다',{word:label,sec:VD_ARM_MS/1000});}
// Arms word key's button: it reads '<낱말> 확정' for VD_ARM_MS, a screen reader hears that the next press saves and within
// how long (vdArmSaid), and a page line says so beside it (pvLineHtml .pv-arm). kbd: armed by a key (verdictKey), which also
// lets it go when the reading page changes (pvStick).
/** @param {string} key @param {string} where @param {number} page @param {string} label @param {boolean} [kbd] */
function armVerdict(key,where,page,label,kbd){disarmVerdict(false);
  VD_ARM={key,label,where,page,doc:DOC,build:META?META.pages_build:'',sel:where===VD_WHERE.COMPOSER?vdSelKey():'',kbd:!!kbd,timer:setTimeout(()=>disarmVerdict(true,true),VD_ARM_MS)};
  vdRedraw(where); announce(vdArmSaid(label));}
// Lets an armed press go (Esc, another press, a press elsewhere, a new selection, document or build, the time running out).
// Nothing keeps saying it waits: when it goes by itself, by Esc or by a press elsewhere (say) a screen reader hears so -
// '삭제 확정을 풀었습니다' replaces '… 한 번 더 누르면 저장합니다' -, and otherwise (its second press saves, a new document or
// build) that sentence is taken out of the live region; a description box still up for it closes.
/** @param {boolean} redraw @param {boolean} [say] */
function disarmVerdict(redraw,say){const a=VD_ARM; if(!a)return; clearTimeout(a.timer); VD_ARM=null; if(redraw)vdRedraw(a.where); hideTip();
  if(say)announce(tl('{word} 확정을 풀었습니다',{word:a.label}));
  else{const r=$('#sr-news'); if(r&&r.textContent===vdArmSaid(a.label))r.textContent='';}}
/** @param {string} where */
function vdRedraw(where){if(where===VD_WHERE.COMPOSER)renderVerdictRow(); else drawPageVerdicts();}
// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else. The click a long press's release
// ends with is no press (tooltip.js swallows it after this, on the document): it lets nothing go, nor closes the description
// the long press showed.
window.addEventListener('click',e=>{if(!VD_ARM||Date.now()<SWALLOW_CLICK)return; const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-act="verdict-save"],[data-act="pv-save"]'));
  if(!(b&&vdArmedHere(b.dataset.key||'',vdWhereOf(b),Number(b.dataset.page)||0)))disarmVerdict(true,true);},true);
window.addEventListener('keydown',e=>{if(e.key!=='Escape'||!VD_ARM)return; e.preventDefault(); e.stopImmediatePropagation(); disarmVerdict(true,true);},true);
/** @param {HTMLElement} b */
function vdWhereOf(b){return b.dataset.act==='verdict-save'?VD_WHERE.COMPOSER:VD_WHERE.PAGE;}

// One word's button: outline, a confirm word's text in the danger colour, '<낱말> 확정' while armed. The word is the
// manuscript's, so the button is translate="no" and its name is put in the screen's language here.
// In the composer it saves (its name says what about: '채택 판정으로 저장 — 3쪽'; its description, that the selection and
// note become that verdict's pin at once). On a page line it is a toggle: pr says its state (PV_PRESS) - the line's
// current verdict, or the word a save on the line is for, is pressed (aria-pressed, a filled look; a confirm word the
// destructive fill) - and its name stays '채택 판정 — 3쪽' whichever it is. Its description says what a press does: an
// unpressed word saves that verdict (the current one is replaced), the pressed one takes the person's own open verdict
// back (as [판정 취소]), and a pressed one that is not theirs or is handled says why it is not taken back here.
// Off: a composer's button is disabled; a page line's waits (aria-disabled, verdictPress ignores it) before the first list,
// and right after its word was taken back (PV_TOGGLE_HOLD) - it keeps the focus a keyboard press left on it, which a
// disabled button would drop to the page.
// kn: on the line of the page the keys act on (PV_KEYS), the word's key 1-5 - drawn after the word as a key hint (data-kn,
// generated text on a mouse screen only, so the button's text stays the word) and, on that screen only (PV_KEY_MARKS),
// said in its description and as aria-keyshortcuts; 0 elsewhere. quiet: drawn without its description (data-tip) - a page
// line whose save chip stands (pvLineHtml) - so no description box comes over the chip; the name and the keys are still
// said. A page line's armed word ('삭제 확정') has no description either: its box covered the line's figure name while the
// word waited for its second press, the button already reads what the box said, and the line says how long it waits
// beside it (.pv-arm). Either keeps it for a long press (data-tip-press, tooltip.js): hover and focus raise no box, but a
// long press shows it and its release presses nothing, as on a word at rest - a long press on the pressed word took the
// verdict back while a chip or the reason popover was up, and one on the armed word saved it (#320).
// The screen that draws the key marks (components.css .vd-b[data-kn]::after): a mouse's. Only there does a word's description
// end in '단축키 1' and its button carry aria-keyshortcuts - a phone's long press read '… · 단축키 1' for a key it has none of
// (#315). The lines are drawn again when that changes (a tablet's keyboard cover with its touchpad taken off), so the
// description follows the marks.
const PV_KEY_MARKS=matchMedia('(hover:hover) and (pointer:fine)');
PV_KEY_MARKS.addEventListener('change',()=>{if(META)drawPageVerdicts();});
/** @param {VerdictChoice} c @param {string} where @param {number} page @param {string} target @param {boolean} off @param {number} [kn] @param {boolean} [quiet] @param {number} [pr] */
function vdButton(c,where,page,target,off,kn,quiet,pr){const armed=vdArmedHere(c.key,where,page),line=where!==VD_WHERE.COMPOSER,on=line&&!!pr&&!armed;
  const said=!!kn&&PV_KEY_MARKS.matches;   // the key said as well as drawn
  const name=armed?tl('{word} 확정 — {sec}초 안에 한 번 더 누르면 저장합니다',{word:c.label,sec:VD_ARM_MS/1000}):line?tl('{word} 판정 — {target}',{word:c.label,target})
    :tl('{word} 판정으로 저장 — {target}',{word:c.label,target});
  const fig=where===VD_WHERE.COMPOSER&&!!figureVerdictRoot(COMPOSE.current);
  let tip=armed?name:fig?tl('누르면 메모와 함께 이 그림 전체({target})의 {word} 판정 핀으로 바로 저장합니다',{word:c.label,target}):where===VD_WHERE.COMPOSER?tl('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다',{word:c.label})
    :pr===PV_PRESS.MINE?tr('지금 판정입니다 · 다시 누르면 이 판정을 거둡니다(판정 취소)'):pr===PV_PRESS.OTHER?tr('지금 판정입니다 · 다른 사람의 판정이라 여기서 거두지 않습니다')
    :pr===PV_PRESS.HANDLED?tr('지금 판정입니다 · 처리된 판정이라 카드의 [지우기]로 거둡니다'):pr===PV_PRESS.SAVING?tr('이 판정을 저장하는 중입니다'):tr('누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다');
  if(said)tip+=' · '+tl(c.confirm?'단축키 {key} (두 번)':'단축키 {key}',{key:kn});
  return html`<button type="button" class="vd-b hit${c.confirm?' vd-confirm':''}${armed?' armed':''}" translate="no" data-act="${where===VD_WHERE.COMPOSER?'verdict-save':'pv-save'}" \
data-key="${c.key}" data-page="${page}" aria-label="${name}"${line?html` aria-pressed="${on?'true':'false'}"`:''}${on&&pr!==PV_PRESS.SAVING?html` aria-describedby="pv-on-${page}"`:''}\
${quiet||(armed&&line)?html` data-tip-press="${tip}"`:html` data-tip="${tip}"`}${kn?html` data-kn="${kn}"`:''}${said?html` aria-keyshortcuts="${kn}"`:''}${off?line?html` aria-disabled="true"`:html` disabled`:''}>\
${on?ic('check'):''}<span class="lbl">${armed?tl('{word} 확정',{word:c.label}):c.label}</span></button>`;}
// A page line's word state (vdButton pr): not pressed, or pressed as the person's own open verdict (a press takes it back),
// someone else's, a handled one (neither is taken back from the line), or the word a save on the line is for (SAVING). A
// pressed word carries a check before its word and is described by the line's state line (pvOnHint, aria-describedby).
const PV_PRESS=Object.freeze({NONE:0,MINE:1,OTHER:2,HANDLED:3,SAVING:4});
// Gives the focus back to the button it was on after a redraw (an armed press redraws its buttons).
/** @param {HTMLElement|null} f */
function vdRefocus(f){if(!f||document.contains(f)||!f.dataset||!f.dataset.act)return;
  const sel=f.dataset.ref?'#doc .pv [data-act="'+f.dataset.act+'"][data-ref="'+CSS.escape(f.dataset.ref)+'"]'   // a line's '#N' link or its earlier link
    :'[data-act="'+f.dataset.act+'"][data-key="'+CSS.escape(f.dataset.key||'')+'"][data-page="'+(f.dataset.page||'0')+'"]';
  const b=/** @type {HTMLElement|null} */(document.querySelector(sel));
  if(b)b.focus({preventScroll:true});}
// A press on a verdict button: a confirm word arms on the first press and saves on the second while what it is bound to
// holds; any other word saves at once - the composer's through savePin, a page line's through pvPress. how: 'key' for a
// digit key (verdictKey, or one in an empty reason field), 'kb' for a click the keyboard made (Enter or Space on the
// button); a page line's save from either opens its reason popover with the focus.
/** @param {HTMLElement} b @param {string} [how] */
function verdictPress(b,how){const key=b.dataset.key||'',where=vdWhereOf(b),page=Number(b.dataset.page)||0,v=docVerdicts(),c=v&&v.choices.find(x=>x.key===key);
  if(!c||b.getAttribute('aria-disabled')==='true'||viewerBlocked())return;
  if(where!==VD_WHERE.COMPOSER){pvPress(c,page,how); return;}
  if(c.confirm&&!(vdArmedHere(key,where,page)&&VD_ARM&&vdArmStill(VD_ARM))){const f=/** @type {HTMLElement|null} */(document.activeElement);
    armVerdict(key,where,page,c.label,how==='key'); vdRefocus(f&&f.closest&&f.closest('.vd-btns')?f:null); return;}
  disarmVerdict(false); hideTip();
  renderVerdictRow(); if(COMPOSE.current)savePin(key);}   // while the pick runs the row is off (composer.css): nothing is queued
// A press of word c on page `page`'s line - a toggle (0.4.34):
// - While a save on the line is out (PV_BUSY) the press is the line's next intent: the last press wins (PV_NEXT) and is
//   applied when the save is done - a word already current then does nothing. Nothing is dropped and nothing is toggled
//   off meanwhile: the line ends on the last word pressed.
// - The pressed word (the line's current verdict): the person's own open verdict is taken back as [판정 취소] does (pvCancelPin,
//   with its [되돌리기]); anyone else's, or a handled one, is not - the status line says why. Pressing a word never makes a
//   second pin of the word that is current. Right after it was taken back the same word waits PV_CANCEL_MS
//   (PV_TOGGLE_HOLD): a double press takes back one verdict and does not save it again.
// - Any other word saves (savePageVerdict), a confirm word on its second press.
/** @param {VerdictChoice} c @param {number} page @param {string} [how] */
function pvPress(c,page,how){const key=c.key,where=VD_WHERE.PAGE,armed=vdArmedHere(key,where,page)&&!!VD_ARM&&vdArmStill(VD_ARM);
  const arm=()=>{const f=/** @type {HTMLElement|null} */(document.activeElement); hideTip();   // no box over the armed word (it says its wait beside it)
    armVerdict(key,where,page,c.label,how==='key'); vdRefocus(f&&f.closest&&f.closest('.vd-btns')?f:null);};
  if(PV_BUSY.has(pvSlot(page))){if(c.confirm&&!armed){arm(); return;}
    disarmVerdict(false); hideTip(); PV_NEXT.set(pvSlot(page),{key,how:how||''}); drawPageVerdicts(); return;}
  const cur=(pageVerdictPins().get(page)||[])[0];
  if(cur&&verdictOf(cur)===key){const h=PV_TOGGLE_HOLD.get(pvSlot(page)); if(h&&h.key===key&&h.until>Date.now())return;
    disarmVerdict(false); hideTip();
    if(pvCanCancel(cur)){PV_TOGGLE_HOLD.set(pvSlot(page),{key,until:Date.now()+PV_CANCEL_MS}); setTimeout(()=>drawPageVerdicts(),PV_CANCEL_MS+20); pvCancelPin(cur.id,page,!!how,how==='key'); return;}   // by a key: the focus goes to the line's [되돌리기]
    lineNote(tl('지금 판정 #{id} {word} 그대로 · {why} — {target}',{id:cur.id,word:c.label,target:pageTargetShort(page),
      why:pvPressOf(cur)===PV_PRESS.HANDLED?tr('처리된 판정은 카드의 [지우기]로 거둡니다'):tr('다른 사람의 판정은 여기서 거두지 않습니다')}),
      NOTICE_KIND.INFO,null,{source:'pv-press',life:NOTICE_LIFE.TIMER,literal:true});
    return;}
  if(c.confirm&&!armed){arm(); return;}
  disarmVerdict(false); hideTip();   // the box the press's focus armed: the save chip comes over the line (pvChipWatch)
  if(how==='key')PV_KEY_OUT.add(pvSlot(page));
  savePageVerdict(page,key,!!how);}
// What a line's current verdict p is to this person, as a pressed word (PV_PRESS): their own open one, someone else's, or a
// handled one (검토 대기, 처리됨, or one whose [확인] waits for its undo).
/** @param {Pin} p */
function pvPressOf(p){return pvCanCancel(p)?PV_PRESS.MINE:pinState(p)!==PIN_STATE.OPEN||CONFIRMING.has(p.id)?PV_PRESS.HANDLED:PV_PRESS.OTHER;}

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
// A reason draft typed for it is not written to the withdrawn pin; it stays kept, and the status line offers [되돌리기],
// which brings the verdict back with it ('판정 #42 채택 저장 되돌림 · 쓰던 이유 보관 — <대상>'). Without one the undo is
// quiet as before - pressing the word again is the same.
function verdictUndo(id){const undo=async()=>{let was=null;
    try{was=(await api('/api/pins/'+id,{what:'핀 읽기',silent:true})).data.pin;}catch(e){}
    const r=PV_REASON&&PV_REASON.id===id?PV_REASON:null; if(r&&pvReasonDirty(r))rdPut(r.doc,id,r.text,r.base,r.rev,{mode:r.mode,tried:r.tried,from:r.via});
    PV_WITHDRAWN.add(id); const ok=await dropPin(id,true,undo); if(!ok)PV_WITHDRAWN.delete(id);
    if(ok&&PV_REASON&&PV_REASON.id===id){PV_REASON=null; drawPageVerdicts();}   // a withdrawn verdict takes no reason
    const d=ok?rdGet(DOC,id):null,k=was&&verdictOf(was),t=was?pageTargetOf(was,META?META.kind:undefined):null;
    if(d&&k)lineNote(tl('판정 #{id} {word} 저장 되돌림 · 쓰던 이유 보관 — {target}',{id,word:verdictLabel(k),target:t?pageTargetShort(t.page):'#'+id}),NOTICE_KIND.OK,
      {label:'되돌리기',tip:T.undo,wait:true,fn:async()=>{PV_WITHDRAWN.delete(id); const back=await restorePin(id); if(back)pvAfterRestore(id); return back;}},
      {life:NOTICE_LIFE.TIMER,undo:true,literal:true});
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
// A page line's pending state is keyed by its document and page (pvSlot): a save held on one document's page must not hold,
// queue or end the same page number's line of another document.
/** @param {number} page @param {string|null} [doc] - default: the document on screen */
function pvSlot(page,doc){return (doc===undefined?DOC||'':doc||'')+'\u0001'+page;}
const PV_BUSY=/** @type {Map<string,string>} */(new Map());   // the page lines whose verdict is being saved (pvSlot), with the word it saves
// The press made on a line while its save was out, by line (pvSlot) - the last one: applied when that save is done (pvPress).
const PV_NEXT=/** @type {Map<string,{key:string,how:string}>} */(new Map());
// The lines whose save out was a digit key's (pvSlot): Enter on any control of that line then means the reason, one intent with
// the key (pvReasonEnterKey). On the word the focus rests on it pressed that word: a second verdict, over the one being saved.
const PV_KEY_OUT=/** @type {Set<string>} */(new Set());
// A line whose word was just taken back by pressing it again (pvSlot): that word waits until then (a double press takes back one).
const PV_TOGGLE_HOLD=/** @type {Map<string,{key:string,until:number}>} */(new Map());
// A page line's last failed save, by page: said on the line that was pressed (pvLineHtml) as well as on the status line, until
// the next press on that line or another document or build. The document and build it was for come with it.
const PV_ERR=/** @type {Map<number,{text:string,doc:string|null,build:string}>} */(new Map());
// The reason after a page line's save - its popover, drafts kept per pin, its writes - is verdict-reason.js (PV_REASON).
// The key marks follow the focus: off on every line while a text field has it - digits typed there are text, the reason
// field's included (pvKeysPage). (Another document closes the popover through pvReasonSync - or
// drawPageVerdicts when it has no lines - whose leave saves what was typed.)
document.addEventListener('focusin',()=>pvStickSoon()); document.addEventListener('focusout',()=>pvStickSoon());
// body.pv-typing while a text field in a page line has the focus (the reason): on a touch screen the keyboard is up, and the
// line drops its figure's name, its save chip folds to [되돌리기] and the status line over the sheet steps aside
// (components.css, responsive.css) - line, field, chip and sheet took the whole 55% the keyboard left on a foldable. That
// line's row is measured again. Read on every focus move and after every drawing of the lines (drawPageVerdicts): a rebuild
// or a pin deleted elsewhere takes the focused field out of the page, and Chromium sends no focusout for that - the class
// stayed and hid the status line.
// Once on, it stays while the reason popover is being used - the focus on one of its buttons, or a press that started in it
// until that press's click has run (PV_POP_PRESS): a tap on [저장], [접기] or [지우기] took the focus out of the field, the
// status line came back (24px) and on a phone the line stacked again, so between the touch and its click the button moved
// 24-85px and the click fell on the popover itself - the first tap was lost. So does a press on the rest of the line while
// the field folds it: a tap on a word took the focus, the figure's name came back over the words and moved them 22px down
// under the finger, and the click fell on the line - the word took no first tap (#320). The fold goes once that press is
// done: its click has run, the browser took it for a scroll (pointercancel), or 500ms after it let go without a click - a
// long press keeps it as long as it is held, so the words stay under the finger while its description shows. Only the press
// that holds the fold lets it go (PV_PRESS_HOLD): a new press on the line takes it over and the earlier one's wait goes - a
// long press's swallowed click left its 500ms wait running, which let the fold go under the next press, between that press's
// focus and its click. A press whose window loses the focus or is hidden (another app, a tab switch) lets it go at once: let
// go outside the window, it has no pointerup or pointercancel here, and the fold stayed.
let PV_POP_PRESS=false;
let PV_PRESS_HOLD=/** @type {(()=>void)|null} */(null);   // the press holding the fold: drops its own wait without letting go
function pvTypingSync(){const a=/** @type {HTMLElement|null} */(document.activeElement),l=a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#doc .pv')):null,b=document.body;
  const pop=!!a&&!!a.closest&&!!a.closest('#doc .pv>.pv-pop'),on=(!!l&&typingNow())||(b.classList.contains('pv-typing')&&(pop||PV_POP_PRESS));
  if(b.classList.contains('pv-typing')===on)return; b.classList.toggle('pv-typing',on);
  const r=l||/** @type {HTMLElement|null} */(document.querySelector('#doc .pv.reading')); if(r)pvFit([r]);}
document.addEventListener('focusin',pvTypingSync); document.addEventListener('focusout',()=>setTimeout(pvTypingSync,0));
document.addEventListener('pointerdown',e=>{const t=/** @type {HTMLElement|null} */(e.target);
  if(!(t&&t.closest&&(t.closest('#doc .pv>.pv-pop')||(document.body.classList.contains('pv-typing')&&t.closest('#doc .pv')))))return;
  if(PV_PRESS_HOLD)PV_PRESS_HOLD();   // an earlier press still waiting: this one holds the fold now
  PV_POP_PRESS=true; let timer=/** @type {ReturnType<typeof setTimeout>|undefined} */(undefined);
  const drop=()=>{clearTimeout(timer); window.removeEventListener('click',late); window.removeEventListener('pointercancel',late);
    window.removeEventListener('pointerup',up,true); window.removeEventListener('blur',late); document.removeEventListener('visibilitychange',hid);
    if(PV_PRESS_HOLD===drop)PV_PRESS_HOLD=null;};
  const end=()=>{if(PV_PRESS_HOLD!==drop)return; drop(); setTimeout(()=>{if(PV_PRESS_HOLD)return; PV_POP_PRESS=false; pvTypingSync();},0);};
  const late=()=>end(),up=()=>{clearTimeout(timer); timer=setTimeout(end,500);},hid=()=>{if(document.visibilityState==='hidden')end();};   // late: after the press's own click (window, bubbling: after the viewer's handlers)
  PV_PRESS_HOLD=drop; window.addEventListener('click',late); window.addEventListener('pointercancel',late); window.addEventListener('pointerup',up,true);
  window.addEventListener('blur',late); document.addEventListener('visibilitychange',hid);},true);
// What a press on page `page` of the document on screen saves against: its document, kind, build and page size and its
// target's name, with the visit it was made in. A save runs on these - not on the document on screen when it runs - so a
// press made before switching documents is saved, and one queued meanwhile is too (pvPress, savePageVerdict). null when the
// page is not there.
/** @param {number} page @returns {{doc:string|null,kind:string|undefined,build:string,w:number,h:number,target:string,visit:any}|null} */
function pvSaveCtx(page){const pg=META&&META.pages[page-1]; if(!META||!pg)return null;
  return {doc:DOC,kind:META.kind,build:META.pages_build||'',w:pg.pt_w,h:pg.pt_h,target:pageTargetShort(page),visit:captureVisit()};}
// The current verdict of page `page` on document doc - one not on screen too: the verdict order holds every document's.
/** @param {string|null} doc @param {number} page @returns {Pin|null} */
function pvCurOn(doc,page){if(doc===DOC||(!doc&&!DOC))return (pageVerdictPins().get(page)||[])[0]||null; let best=/** @type {Pin|null} */(null);
  verdictOrder(doc||DEFAULT_DOC).groups.forEach(g=>{if(g.whole&&g.page===page&&(!best||best.id<g.pins[0].id))best=g.pins[0];}); return best;}
// The largest pin number the lists hold: a verdict whose answer was lost is looked for above it (pvLanded).
function pvTopId(){return OPEN_ALL.concat(REVIEW_ALL,DONE_ALL).reduce((m,p)=>Math.max(m,p.id),0);}
// A verdict pin this person saved with word key about page `page` of document doc since pin number top - a save whose
// answer was lost may have landed: it is read again before the press is called a failure, or pressed again (a duplicate).
/** @param {string|null} doc @param {number} page @param {string} key @param {number} top @param {string|undefined} kind @returns {Pin|null} */
function pvLanded(doc,page,key,top,kind){return OPEN_ALL.find(p=>p.id>top&&pdoc(p)===(doc||DEFAULT_DOC)&&verdictOf(p)===key&&isMe(p.author)&&(()=>{const t=pageTargetOf(p,kind); return !!t&&t.page===page;})())||null;}
// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build it was pressed on, the
// body pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's selection and draft
// stay as they are. The word becomes the page's current verdict - a new pin (the agent runs the newest, D4 and D5); pressing
// the current word takes it back instead (pvPress). It runs on its press's context (pvSaveCtx): leaving the document while
// it runs does not drop it - it completes, and its undo is offered on the status line. Saved: '#42 저장됨 [되돌리기]' on the
// line for NOTICE_MS. An answer lost on the network - or a 5xx, which a server may send after writing - is checked against
// the list before anything is said (pvLanded): a verdict that landed is a save, not a failure a second press would
// duplicate (a 500 after the write left the line without the verdict, and the next press made a second one). A refusal or a failure is said on the status
// line, result first ('판정 저장 실패 · <까닭> — <대상>'), and under the pressed line. While it is out the line says what it
// saves ('보류 저장 중…') and presses wait in PV_NEXT; the last of them is applied after it - also after a switch away and
// back, on the document it was pressed on - unless that word is the page's verdict by then. No save opens the reason
// popover: the line offers [이유 추가], and 'Enter 이유 쓰기' while the keys act on it.
/** @param {number} page @param {string} key @param {boolean} [kb] - pressed from the keyboard: the focus goes to the line's way to the reason @param {ReturnType<typeof pvSaveCtx>} [ctx0] */
async function savePageVerdict(page,key,kb,ctx0){const ctx=ctx0||pvSaveCtx(page); if(!ctx)return; const slot=pvSlot(page,ctx.doc); if(PV_BUSY.has(slot))return;
  const visit=ctx.visit,here=()=>DOC===ctx.doc;
  const fail=(/** @type {string} */text)=>{if(here())PV_ERR.set(page,{text,doc:ctx.doc,build:ctx.build});};
  // Said on the status line with what it was for, result first, and under the pressed line.
  const failed=(/** @type {string} */why)=>{lineNote(tl('판정 저장 실패 · {why} — {target}',{why,target:ctx.target}),NOTICE_KIND.ERR,null,{source:'page-verdict',literal:true});
    fail(tl('{what} 실패',{what:tr('판정 저장')})+' — '+why);};
  let saved=false,got=0; if(here())PV_ERR.delete(page);
  // A key save (a digit, Enter or Space on a word) hands the focus to the line's way to the reason ('Enter 이유 쓰기'), so
  // Enter there opens it - on the pressed word Enter would take the verdict back - unless the person put the focus anywhere
  // else meanwhile (another page's word, a '#N' link, the panel): a redraw that puts it back on the same word's button is no move.
  let away=false;
  const moved=e=>{const t=/** @type {HTMLElement} */(e.target);
    if(!(t&&t.dataset&&t.dataset.act==='pv-save'&&t.dataset.key===key&&t.dataset.page===String(page)))away=true;};
  document.addEventListener('focusin',moved);
  const before=pvCurOn(ctx.doc,page),prev=before?before.id:0,top=pvTopId();   // the verdict a save replaces: a draft kept for it moves on
  // A new verdict on the line ends the line's offer of a take-back's [되돌리기] (the status line keeps its own): the line
  // is about the new verdict now, and while the offer lasted its [이유 추가] stepped out (components.css) - the focus a key
  // save hands it went nowhere, and PageDown no longer scrolled.
  const f0=document.activeElement,onUndo=!!f0&&!!f0.closest&&!!f0.closest('#doc .pv-undo');   // it goes with the offer: the focus goes to the word being saved
  PV_LINE_UNDO.delete(slot); PV_BUSY.set(slot,key); drawPageVerdicts(); if(onUndo)pvRefocus(page,key);
  try{const d=(await api('/api/pick',{method:'POST',body:{page,x0:0,y0:0,x1:ctx.w,y1:ctx.h,frac:WHOLE_PAGE.slice(),pdf_build:ctx.build||undefined,doc:ctx.doc||undefined},
      what:'판정 저장',silent:true})).data;
    if(d.error){failed(errText(d)); if(d.pdf_build_gone&&here())refreshDoc().catch(()=>{}); return;}
    const body=pageVerdictBody(d,ctx.kind);
    if(!body){lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다',NOTICE_KIND.WARN,null,{source:'page-verdict'}); fail(tr('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다')); return;}
    Object.assign(body,{note:'',doc:ctx.doc||undefined,kind_req:KIND_REQ.FIX,assignee:ASSIGNEE_AGENT,verdict:key});
    let id=0;
    try{id=(await api('/api/pin',{method:'POST',body,what:'판정 저장',silent:true})).data.id;}
    catch(e){const x=/** @type {ApiError} */(e); if(x&&x.status&&x.status<500)throw e;   // no answer, or a 5xx (it may have been written first): the list says whether it landed
      await loadPins(); const got=pvLanded(ctx.doc,page,key,top,ctx.kind); if(!got)throw e; id=got.id;}
    saved=true; got=id; sourceOk('page-verdict');
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다',{id,word:verdictLabel(key,ctx.doc),target:ctx.target}),{label:'되돌리기',wait:true,fn:verdictUndo(id)},
      {pin:id,pending:true,label:tl('#{id} 저장됨 · {word}',{id,word:verdictLabel(key,ctx.doc)})});
    if(here())pvReasonAfterSave(page,id,key,!!kb,prev);   // the reason popover: a draft on this line moves to the new verdict
    await loadPins(); settleChip(chip); if(here())pvOnShow(page);
  }catch(e){const x=/** @type {ApiError} */(e);
    if(!saved)failed(x&&x.status?(x.data&&errText(x.data))||('HTTP '+x.status):tr('서버에 닿지 않습니다'));}
  finally{document.removeEventListener('focusin',moved); PV_BUSY.delete(slot); PV_KEY_OUT.delete(slot);
    // A popover opened by Enter while this save was out: bound to it now if its Enter came after the number was known (the
    // list still being read), else, the save failed, its text kept as the page's draft.
    const un=here()&&PV_REASON&&!PV_REASON.id&&PV_REASON.page===page&&PV_REASON.doc===ctx.doc;
    if(un&&saved)pvReasonAfterSave(page,got,key,!!kb,prev); else if(!saved&&here())pvReasonUnbound(page);
    pvReasonSettle(slot,saved?got:0,key);   // one moved away from meanwhile: written on this verdict wherever the person is now
    drawPageVerdicts();
    if(currentVisit(visit)&&kb&&!away){const c=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-reason-open"]'));
      if(c&&saved)c.focus({preventScroll:true}); else pvRefocus(page,key);
      if(saved&&document.activeElement===document.body)pvFocusLine(page);   // never left on nothing: the line's own control
      // The focus the save moved there raises no description box: the press's own description of the pressed word stands
      // over the words for a few seconds (pvOnShow), and on a one-row line at 1280 the two boxes overlapped by 39px (#308
      // review). A focus the person moves raises it as before.
      if(saved)hideTip();}
    const nx=PV_NEXT.get(slot); PV_NEXT.delete(slot);
    if(nx){const cur=pvCurOn(ctx.doc,page);   // the last press made meanwhile, on the document it was made on
      if(!(cur&&verdictOf(cur)===nx.key)){const fresh=here()?pvSaveCtx(page):null; if(nx.how==='key')PV_KEY_OUT.add(slot); savePageVerdict(page,nx.key,!!nx.how,fresh||ctx);}}
    pvReasonUncancelSettle(slot);}}   // a failed take-back's draft that waited for this save (a next save started just now waits on)
// The reading line's name for page `page`, in two parts: a short identifier that is never cut - the page and the figure's code,
// '6쪽 · PL17' (the map title's head before its first ' · ', a leading tag such as '[후보]' moved to the rest; else the figure
// id) - and the rest of the title, cut first ('[후보] 다섯 비교 쌍의 월별 효과 — …'). Next to the buttons a cut down to '6쪽 · …'
// no longer said which figure a press decides. A view-only PDF's page is its page alone.
/** @param {number} page @returns {{id:string,rest:string}} */
function pvFigParts(page){const pg=META&&Array.isArray(META.pages)?META.pages[page-1]:null,at=tl('{page}쪽',{page});
  if(!META||!isFigureKind(META.kind)||!pg||typeof pg.figure!=='string')return {id:at,rest:''};
  const t=pg.title?String(pg.title):''; if(!t)return {id:at+' · '+pg.figure,rest:''};
  const i=t.indexOf(' · '),head=i>0?t.slice(0,i):'',m=/^(\[[^\]]*\])\s*(\S.*)$/.exec(head);
  if(!head)return {id:at,rest:t};
  return m?{id:at+' · '+m[2],rest:m[1]+' '+t.slice(i+3)}:{id:at+' · '+head,rest:t.slice(i+3)};}
// Gives the focus back to word key's button on page `page`'s line after its save: the pressed button was disabled and redrawn
// while the request ran, which dropped the focus. Not when the person put the focus somewhere else meanwhile (savePageVerdict
// watches for that) or it is on something now.
/** @param {number} page @param {string} key */
function pvRefocus(page,key){const a=document.activeElement; if(a&&a!==document.body&&document.contains(a))return;
  const b=/** @type {HTMLButtonElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-save"][data-key="'+CSS.escape(key)+'"]'));
  if(b&&!b.disabled&&b.getAttribute('aria-disabled')!=='true')b.focus({preventScroll:true});}
// ---------------- Taking one's verdict back (#295)
// Whether the line offers [판정 취소] on verdict pin p, its page's current verdict: the person's own (isMe), still open - not
// yet handled; a handled one's card still offers [지우기] - to a person who may make a verdict (no agent, D16, nor a
// viewer). A pin whose [확인] waits for its undo is not open.
/** @param {Pin} p */
function pvCanCancel(p){return !!verdictOf(p)&&canVerdict()&&isMe(p.author)&&pinState(p)===PIN_STATE.OPEN&&!CONFIRMING.has(p.id);}
const PV_CANCEL_MS=800;   // after a cancel on a page, how long that page's next [판정 취소] waits (a double press never takes two)
const PV_CANCEL_HOLD=/** @type {Map<string,number>} */(new Map());   // line (pvSlot) -> until when its [판정 취소] waits
// The lines whose take-back is out: Enter and Space on them do nothing until it answers (pvOffPageKey). What the focus rests on is
// what the line shows meanwhile, the verdict before it: Enter there opened a reason for it, or took that one back too. An answer
// that does not come must not leave the line deaf: past PV_DROP_WAIT the keys are back and the status line says so; the late
// answer is still taken (its message, its [되돌리기]), but the focus has moved on by then and stays. The value says whose wait it is.
const PV_DROP_OUT=/** @type {Map<string,number>} */(new Map());
let PV_DROP_WAIT=8000;
// A verdict a [되돌리기] brought back (a take-back's, the save chip's): when it is its line's current verdict again its kept reason
// draft opens (pvReasonRevive); when a newer verdict came meanwhile - someone else's - it is restored but superseded, the
// status line says so ('판정 #21 채택 되살림 · 지금 판정은 Bob의 #34 보류 — <대상>') and no popover opens over that line - its
// kept draft, which no line would mark on a verdict that is not current, becomes the page's draft, said with [보기]
// (pvReasonUncancelDraft).
/** @param {number} id */
function pvAfterRestore(id){const p=findAnyPin(id),t=p?pageTargetOf(p,META?META.kind:undefined):null,cur=t?(pageVerdictPins().get(t.page)||[])[0]:null;
  if(p&&t&&cur&&cur.id!==id){const ck=verdictOf(cur)||'',k=verdictOf(p)||'';
    lineNote(tl('판정 #{id} {word} 되살림 · 지금 판정은 {owner} #{cur} {now} — {target}',{id,word:verdictLabel(k),owner:isMe(cur.author)?tr('내'):tl('{name}의',{name:who(cur.author)}),
      cur:cur.id,now:verdictLabel(ck),target:pageTargetShort(t.page)}),NOTICE_KIND.INFO,null,{literal:true,life:NOTICE_LIFE.TIMER});
    pvReasonUncancelDraft(id,t.page,DOC,true); return;}
  pvReasonRevive(id);}
// The take-backs whose [되돌리기] the line offers too, by line (pvSlot): the pin and its status-line message - the offer lasts
// as long as that message (its window, or its action).
const PV_LINE_UNDO=/** @type {Map<string,{id:number,n:number}>} */(new Map());
// The line's [되돌리기]: the status line's action runs (noticeAct), as if pressed there.
/** @param {HTMLElement} a */
function pvLineUndo(a){const line=a.closest('.pv'),page=Number(line&&line.getAttribute('data-page'))||0,u=PV_LINE_UNDO.get(pvSlot(page)); if(!u)return;
  PV_LINE_UNDO.delete(pvSlot(page)); if(NOTICES.has(u.n))noticeAct(u.n); drawPageVerdicts(); pvFocusLine(page);}
// [판정 취소] on page `page`'s line - or its pressed word pressed again (pvPress): verdict pin id goes to the Trash as the
// card's [지우기] sends it (dropPin) - a withdrawn request - and the line shows at once what is current now: the newest
// earlier verdict about the same target (D4) or '판정 없음'. The status line says so result first ('판정 #17 채택 취소 · 지금
// 판정 #12 보류 — <대상>', or '… · 남은 판정 없음 — …') with [되돌리기], which restores it (restorePin) and its kept reason
// draft (pvReasonRevive); one an agent had claimed still goes, and the status line says its run may have started (as the
// save's undo, verdictUndo). Its reason popover closes with it; what was typed is not written, and stays kept for that
// [되돌리기]. A failure is said on the status line and the line shows the verdict again, its popover too - or, when something
// took its place meanwhile, what was typed as a draft its line marks, said with [보기] (pvReasonUncancel). The page's next
// [판정 취소] waits PV_CANCEL_MS: the same place may now cancel the earlier verdict, which a double press must not reach.
// A keyboard press leaves the focus on the PDF area, as Esc in the reason field does.
/** @param {HTMLElement} b */
function pvCancel(b){const id=Number(b.dataset.ref),page=Number((b.closest('.pv')||b).getAttribute('data-page'))||0;
  if(b.getAttribute('aria-disabled')==='true')return; pvCancelPin(id,page,document.activeElement===b);}
/** @param {number} id @param {number} page @param {boolean} had - the focus was on what was pressed */
/** @param {number} id @param {number} page @param {boolean} had @param {boolean} [byKey] - a digit key: the focus goes to the line from wherever it was */
async function pvCancelPin(id,page,had,byKey){const p=OPEN_ALL.find(x=>x.id===id),from=document.activeElement,doc=DOC;
  if(!p||!pvCanCancel(p)||viewerBlocked())return;
  const key=/** @type {string} */(verdictOf(p)),claimed=claimActive(p),target=pageTargetShort(page);
  const inField=pvIsReasonField(document.activeElement)&&!!PV_REASON&&PV_REASON.id===id;
  PV_CANCEL_HOLD.set(pvSlot(page),Date.now()+PV_CANCEL_MS); setTimeout(()=>drawPageVerdicts(),PV_CANCEL_MS+20);
  // Its reason popover leaves with the line's verdict, but the session is kept until the server answers: a failed cancel
  // brings the verdict back and its unsent reason with it, or keeps that as a draft its line marks when something took its
  // place (pvReasonUncancel); a done one drops it - its draft stays kept (rdPut) for the [되돌리기].
  const kept=PV_REASON&&PV_REASON.id===id?PV_REASON:null; if(kept){PV_REASON=null; if(pvReasonDirty(kept))rdPut(kept.doc,id,kept.text,kept.base,kept.rev,{mode:kept.mode,tried:kept.tried,from:kept.via});}
  PV_WITHDRAWN.add(id);
  // The take-back is said on the status line with its [되돌리기], which the line itself also offers for as long (PV_LINE_UNDO):
  // the status line is far away by Tab.
  const say=()=>{const now=(pageVerdictPins().get(page)||[])[0],nk=now&&verdictOf(now);
    const rest=now&&nk?tl('지금 판정 #{id} {word}',{id:now.id,word:verdictLabel(nk)}):tr('남은 판정 없음');
    const n=lineNote(tl('판정 #{id} {word} 취소 · {rest} — {target}',{id,word:verdictLabel(key),rest,target}),NOTICE_KIND.OK,
      {label:'되돌리기',tip:T.undo,wait:true,fn:async()=>{PV_WITHDRAWN.delete(id); const ok=await restorePin(id); if(ok)pvAfterRestore(id); return ok;}},
      {life:NOTICE_LIFE.TIMER,undo:true,literal:true});
    // [이유 추가] steps out while the line offers the undo (components.css): a focus on it goes to the [되돌리기] beside it.
    const f=/** @type {HTMLElement|null} */(document.activeElement),onAdd=!!f&&!!f.closest&&!!f.closest('#doc .pv[data-page="'+page+'"] .pv-ra>.pv-add');
    if(n){PV_LINE_UNDO.set(pvSlot(page),{id,n:n.n}); drawPageVerdicts(); setTimeout(()=>drawPageVerdicts(),NOTICE_MS+NOTICE_HOLD_MAX+50);
      const a=document.activeElement,u=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-undo"]'));
      if(onAdd&&u&&(a===f||a===document.body||!a))u.focus({preventScroll:true});}};
  hideTip();
  const again=()=>{PV_CANCEL_HOLD.delete(pvSlot(page)); drawPageVerdicts(); pvCancelPin(id,page,false);};   // [다시 시도] is a new press: no hold
  const out=pvSlot(page); PV_DROP_OUT.set(out,id); let ok=false,slow=false;
  const wait=setTimeout(()=>{slow=true; if(PV_DROP_OUT.get(out)===id)PV_DROP_OUT.delete(out);
    lineNote('판정 취소의 답이 늦습니다 — 이 줄의 키를 다시 받습니다',NOTICE_KIND.WARN,null,{source:'pv-drop-wait',life:NOTICE_LIFE.TIMER});},PV_DROP_WAIT);
  try{ok=await dropPin(id,false,again,{say,where:NOTICE_HOST.LINE,what:'판정 취소'});}finally{clearTimeout(wait); if(PV_DROP_OUT.get(out)===id)PV_DROP_OUT.delete(out);}
  if(!ok){PV_WITHDRAWN.delete(id); pvReasonUncancel(id,page,kept?kept.doc:doc,kept);}
  // A keyboard press stays on its own page: the line's [되돌리기], else its line (never the PDF area, from which Tab went to the
  // first page's line). A digit key's take-back takes the focus there from wherever it was - the outline, a card - as a key
  // save does, unless the person moved it meanwhile: left in the outline, Enter pressed the outline again instead of undoing.
  // A reason popover that has the focus now is a newer one (the verdict's own left with it): it keeps it - on this line too
  // (a new verdict's, saved while the take-back was out), where the focus went to the line and the next digit was a verdict key.
  const at=/** @type {HTMLElement|null} */(document.activeElement),pop=!!at&&!!at.closest&&!!at.closest('#doc .pv-pop');
  const lost=!pop&&(!at||at===document.body||at===$('#left')||!!(at.closest&&at.closest('#doc .pv[data-page="'+page+'"]'))||(!!byKey&&at===from));
  if((had||inField)&&lost&&!slow){
    const u=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-undo"]')); if(u)u.focus({preventScroll:true}); else if(!pvFocusLine(page))searchToPage();}
  if(ok&&claimed)lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다',NOTICE_KIND.WARN);}
// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and word,
// and who made it and when if that was someone else - its reason (pvReasonInline: a check and its first line, a kept draft, [이유 추가]),
// [판정 취소] on the person's own while it is open (pvCanCancel), the earlier open verdicts as a link ('이전 판정 N건 · 새
// 판정으로 대체됨'), and, for a person who may make one, a button per word. The current verdict's word is pressed (a toggle,
// pvPress); while a save on the line is out, the word it saves - or the last one pressed meanwhile (PV_NEXT) - is pressed
// instead and the state says '보류 저장 중…'. The reason popover (pvReasonPop) is the line's last child, laid above it.
/** @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v @param {boolean} [chip] - the line holds a save chip or its reason popover: it draws no descriptions @param {boolean} [panel] - the panel beside the pages (verdict-panel.js) */
function pvLineHtml(page,list,v,chip,panel){const cur=list&&list[0],earlier=list?list.slice(1).filter(p=>pinState(p)===PIN_STATE.OPEN):[];
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
${pvReasonInline(page,cur)}`
    :html`<span class="pv-s pv-none">${tr(loading?'판정 읽는 중…':'판정 없음')}</span>${loading?'':pvReasonInline(page,undefined)}`;
  // A save on the line that is out: what it saves - or the last word pressed meanwhile, which comes after it.
  const slot=pvSlot(page),nx=PV_NEXT.get(slot),sv=PV_BUSY.get(slot),want=nx?nx.key:sv!==undefined?sv:k||null;
  const saving=sv!==undefined?html`<span class="pv-busy" role="status"><span class="pv-sep" aria-hidden="true">·</span> ${tl('{word} 저장 중…',{word:verdictLabel(want||sv)})}</span>`:'';
  // A confirm word armed on this line says how long it waits, beside it.
  const armed=!!VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page===page?VD_ARM:null;
  const armSay=armed?html`<span class="pv-arm"><span class="pv-sep" aria-hidden="true">·</span> ${tl('{sec}초 안에 한 번 더 누르면 저장',{sec:VD_ARM_MS/1000})}</span>`:'';
  // [판정 취소]: a text action in the row (the viewer's link look, as the earlier link), after the state. It is its verdict's
  // own element (data-id): once that verdict goes the next one's is a new one, which a keyboard focus does not carry over.
  // It waits (aria-disabled) while the page's save is out, the first list is not in, or a cancel on this page just ran.
  const cn=!!cur&&pvCanCancel(cur),cw=PV_BUSY.has(slot)||loading||(PV_CANCEL_HOLD.get(slot)||0)>Date.now();
  const cancel=cn&&cur?html`<span class="pv-sep pv-cn" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" data-act="pv-cancel" \
data-ref="${cur.id}" data-id="${cur.id}" aria-label="${tl('판정 취소 — 내 판정 #{id}',{id:cur.id})}" \
${pvTipAttr(!!chip,tr('이 판정을 거둡니다. 핀은 휴지통으로 가고, 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 상태 줄의 [되돌리기]가 되살립니다'))}${cw?html` aria-disabled="true"`:''}>${tr('판정 취소')}</button>`:'';
  // The earlier link is short - '이전 2건' ('+2 earlier') - and never cut: where its line is tight (.pv-tight, pvFit) it is
  // its count alone, '+2' (data-n, components.css). Its name says it whole ('이전 판정 2건 · 새 판정으로 대체됨'), and so does
  // its tooltip before what it is. The whole words stood in the row and were cut to fit: '1 ea…' on a 620px English line.
  // A dot sets it off from what comes before it, as the state's other parts are (.pv-ea, gone whenever the link is): right
  // after [✓ 채택 1]'s key digit on a stacked line, or after [판정 취소], a bare '+2' read as a count of that button's.
  const ne=earlier.length,eName=tl('이전 판정 {n}건 · 새 판정으로 대체됨',{n:ne});
  const early=ne?html`<span class="pv-sep pv-ea" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" data-n="${ne}" aria-label="${eName}" \
${pvTipAttr(!!chip,eName+' — '+tr('이 쪽의 더 새 판정으로 대체되어 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다'))}><span class="pv-early-w">${tl('이전 {n}건',{n:ne})}</span></button>`:'';
  // The reading page's line - the one that floats - names what it decides: '7쪽 · [후보] PL18 · …' (figureName), cut to fit.
  // Its two spans are on every line, hidden but on the reading one: the line's children keep their places when the reading
  // page moves, so the morph (pvMorph) never takes a focused button out of the page. A hidden one holds the identifier, so
  // every line is fitted as the reading line it may become (pvFit).
  // The panel beside the pages (verdict-panel.js) names its page and figure whole: the title on rows of its own under the
  // identifier, kept even when empty, so the words below stand at one height for every page. A view-only PDF has no titles.
  const rd=PV_READ===page||!!panel,nm=rd?pvFigParts(page):{id:pvFigParts(page).id,rest:''};
  const name=panel?html`<span class="pv-fig" translate="no"><span class="pv-fig-id">${nm.id}</span>${isFigureKind(META?META.kind:undefined)?html`<span class="pv-fig-t">${nm.rest}</span>`:''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true">·</span>`
    :html`<span class="pv-fig" translate="no"${rd?'':html` hidden`}><span class="pv-fig-id">${nm.id}</span>${nm.rest?html`<span class="pv-fig-t">${' · '+nm.rest}</span>`:''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true"${rd?'':html` hidden`}>·</span>`;
  const keys=PV_KEYS===page,target=tl('{page}쪽',{page}),held=PV_TOGGLE_HOLD.get(slot),hold=held&&held.until>Date.now()?held.key:null;
  const pr=(/** @type {string} */key)=>key!==want?PV_PRESS.NONE:nx||sv!==undefined?PV_PRESS.SAVING:cur?pvPressOf(cur):PV_PRESS.NONE;
  const btns=canVerdict()?html`<span class="vd-btns">${v.choices.map((c,i)=>vdButton(c,VD_WHERE.PAGE,page,target,loading||c.key===hold,keys?i+1:0,!!chip,pr(c.key)))}</span>`:'';
  // The line's last failed save, said where it was pressed (PV_ERR) - for the document and build on screen only.
  const e=PV_ERR.get(page),eo=!!e&&e.doc===DOC&&!!META&&e.build===(META.pages_build||'');
  const err=html`<span class="pv-err"${eo?'':html` hidden`}>${eo&&e?e.text:''}</span>`;   // always there, so the reason field after it keeps its place
  // A take-back of this line's, while its status-line [되돌리기] lasts: the line offers it too (PV_LINE_UNDO).
  const lu=PV_LINE_UNDO.get(slot),undo=lu&&NOTICES.has(lu.n)&&canVerdict()?html`<span class="pv-sep pv-un" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-undo pv-un hit" \
data-act="pv-undo" data-id="u${lu.id}" aria-label="${tl('되돌리기 — 거둔 판정 #{id}',{id:lu.id})}">${tr('되돌리기')}</button>`:'';
  if(lu&&!undo)PV_LINE_UNDO.delete(slot);
  const hint=pvOnHint(page,v,want,nx||sv!==undefined?PV_PRESS.SAVING:cur?pvPressOf(cur):PV_PRESS.NONE);
  // In the panel the words come right under the name - one place on the screen for every page, whatever the state under
  // them says - and the Tab order follows the rows: the words, then the state's links and actions.
  if(panel)return html`${name}${btns}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${err}${hint}${pvReasonPop(page)}`;
  return html`${name}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${btns}${err}${hint}${pvReasonPop(page)}`;}
// A line control's description: data-tip, or - on a line that holds a save chip or its reason popover (pvLineHtml chip) -
// data-tip-press, which only a long press shows (tooltip.js): no box over either, and a long press still presses nothing.
/** @param {boolean} quiet @param {string} tip */
function pvTipAttr(quiet,tip){return quiet?html`data-tip-press="${tip}"`:html`data-tip="${tip}"`;}
// The pressed word's context (P2-3: taking a verdict back by pressing its word again must be found without a hover - a
// line holding a save chip or a popover draws no descriptions, and touch has none): one short sentence, the pressed word's
// description for assistive technology (aria-describedby="pv-on-<page>") and shown over the word group - never in the
// line's flow, so the line keeps its height - while the pressed word is hovered or has the keyboard's focus, and for a
// few seconds after a press made it the line's verdict (.pv-onshow, pvOnShow). '지금 삭제 판정 · 다시 누르면 판정 취소' on the
// person's own open verdict; someone else's or a handled one says it stays.
/** @param {number} page @param {DocVerdicts} v @param {string|null} key @param {number} pr */
function pvOnHint(page,v,key,pr){const c=key?v.choices.find(x=>x.key===key):null; if(!c||!pr||pr===PV_PRESS.SAVING||!canVerdict())return '';
  const say=pr===PV_PRESS.MINE?tl('지금 {word} 판정 · 다시 누르면 판정 취소',{word:c.label}):pr===PV_PRESS.OTHER?tl('지금 {word} 판정 · 다른 사람의 판정이라 그대로 둡니다',{word:c.label})
    :tl('지금 {word} 판정 · 처리된 판정이라 그대로 둡니다',{word:c.label});
  return html`<span class="pv-onhint" id="pv-on-${page}" translate="no">${say}</span>`;}
// A press made word key page `page`'s verdict: its line shows the pressed word's context for PV_ONSHOW_MS.
const PV_ONSHOW_MS=4000;
/** @param {number} page */
function pvOnShow(page){const l=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"]')); if(!l)return;
  l.classList.add('pv-onshow'); clearTimeout(l._onT); l._onT=setTimeout(()=>l.classList.remove('pv-onshow'),PV_ONSHOW_MS);}
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
  const chip=el.querySelector(':scope>.nt-chip');   // a save's undo chip (drawChips) stays on its line; drawChips moves it if it is another pin's
  // While its save chip stands or its reason popover is open the line draws no descriptions: no box over either.
  const m=pvLineHtml(page,list,v,!!chip||pvReasonOn(page),el.id==='pv-panel'); if(PV_TEXT.get(el)===m.text)return; PV_TEXT.set(el,m.text);
  // The focused reason field keeps the focus and the caret when the line around it changes shape (its verdict's save landing
  // while it is typed in: a morph by place can replace it), so what is typed next stays text - never a verdict key.
  const a=document.activeElement,f=pvIsReasonField(a)&&el.contains(a)?/** @type {HTMLTextAreaElement} */(a):null,sel=f?[f.selectionStart,f.selectionEnd]:null;
  if(chip)chip.remove(); const next=document.createElement('div'); setHtml(next,m); pvMorphKids(el,next); if(chip)el.appendChild(chip);
  el.classList.toggle('pv-pop-open',!!el.querySelector(':scope>.pv-pop')); pvReasonAfterDraw(el);
  if(f&&sel&&!f.isConnected){const g=/** @type {HTMLTextAreaElement|null} */(el.querySelector('.pv-pop .pv-reason[data-id="'+f.dataset.id+'"]'));
    if(g){g.focus({preventScroll:true}); g.setSelectionRange(sel[0],sel[1]);}}}
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
// The width of each line and whether it is one row or stacked - per line. A line is its own page's width, never past what the
// PDF area shows; a page narrower than the widest has a line as narrow, under it. Where the pages are fitted (no sideways
// scroll) a line also ends before what lies over the area's right side (pvInsetR: an overlay panel, the closed panel's
// status box) and still starts where its page does: centred with the room cut on one side, the sticky line was pushed past
// the page's left edge (1280 x 800 with the panel closed: 36px). A zoomed page's line keeps the room the area shows and
// stays in view as the page scrolls sideways (sticky). Then each line on its own (pvFit). Measured only while the pages are
// laid out (the changes view hides them); read and written in batches.
const PV_MIN_W=320;   // a cut line narrower than this keeps its page's width and lets the sticky edge push it instead
function sizePv(){const ir=pvInsetR(),L=$('#left'),lines=$$('#doc .pv');
  L.style.setProperty('--pv-inset-r',ir+'px'); PV_INSET_R=ir; $('#doc').classList.remove('pv-stack');
  if(!lines.length||!lines[0].getClientRects().length)return;
  // A zoom or a new width took the room across its bar: the lines move at the next frame (pvStick), never here. A zoom restores
  // its place after this call, and the reading page read before that is not the one being read (verdict-panel.js).
  if(pvSideWant()!==PV_SIDE)pvStickSoon();
  if(PV_SIDE){pvFit(lines); return;}   // the panel keeps its own width
  const room=innerW()-ir,lr=L.getBoundingClientRect(),fitted=L.scrollWidth<=L.clientWidth+1;
  const end=lr.left+L.clientLeft+L.clientWidth-parseFloat(getComputedStyle(L).paddingRight)-ir;   // the room's right edge on screen
  const at=lines.map(e=>{const pg=document.getElementById('p'+e.dataset.page),blk=e.parentElement; if(!pg||!blk)return null;
    const p=pg.getBoundingClientRect(); return {w:parseFloat(pg.style.width)||p.width,left:p.left,off:p.left-blk.getBoundingClientRect().left};});
  lines.forEach((e,i)=>{const a=at[i]; let w=a?Math.min(a.w,room):room,ml='';
    if(a&&fitted&&end-a.left<w&&end-a.left>=PV_MIN_W){w=end-a.left; ml=Math.round(a.off)+'px';}
    e.style.width=Math.round(w)+'px'; e.style.marginLeft=ml;});
  pvFit(lines);}
// The verdict pins saved by a key on this screen (PV_KEY_SAVE, each in turn): their lines (.pv-kw) are fitted at either look of
// the way to the reason (pvFit). The last key save's alone says 'Enter 이유 쓰기', but one that stopped being it and was
// fitted again on [이유 추가] alone moved the pages under the next key save.
const PV_KEY_SAVED=/** @type {Set<number>} */(new Set());
// One row or stacked, decided per line (.pv-stack; P2-7 of the 0.4.33 review: one line with an earlier verdict or a reason
// stacked every line of the document, 88px over the plot at 1440). Each line is laid out as one row - the figure's title cut
// first, down to its identifier ('6쪽 · PL17', pvFigParts; --pv-fig-min), then the reason and the earlier link
// (components.css) - and stacks only when its state's own words, [판정 취소] and its buttons still cannot share the row: the
// state runs past its share, or the buttons went to a row of their own (a narrow page). On the wide band a line that does not
// fit first lets the reason go further and the earlier link say its count alone (.pv-tight): a desktop keeps one row, a
// second row covered the plot. A line narrower than a verdict's state beside its words stacks whatever it shows, so a press never stacks it. A line whose confirm word waits for its second press, or whose save is out, keeps the rows it has (pvRowsHeld): its
// words moving between the two presses sent the second one elsewhere. The save chip is placed after (pvChipPlace).
// Read and written in batches.
// While the page is pinch-zoomed the PDF area does not anchor its scroll for the pass (pvHoldView): the pass grows every
// line above the reading page and shrinks it back (#doc.pv-measure), and Chromium carried the anchoring of that shrink -
// the area is the page's root scroller there - into the zoomed view, which went from where it was to the page's top
// (422 -> 0 at 2x) at every drawing of the lines: a save, a take-back (#320). The pass moves nothing below a line it measures
// either (pvKeepBlocks): WebKit anchored the growth on the next page's block and not the shrink, so a key save on a phone
// moved the pages 39px.
/** @param {HTMLElement[]} lines */
function pvFit(lines){const panel=lines.find(l=>l.id==='pv-panel');
  if(panel){pvPanelFit(panel); lines=lines.filter(l=>l!==panel); if(!lines.length)return;}   // the panel: rows down it, never one row (verdict-panel.js)
  const held=lines.map(pvRowsHeld),D=$('#doc'),hold=pvHoldView(true),kept=pvKeepBlocks(lines); try{
  pvFarHold(lines);   // a line skipped far from the view is laid out to be measured, and keeps its height after (pvFarLetGo)
  if(PV_KEY_SAVE)PV_KEY_SAVED.add(PV_KEY_SAVE);
  lines.forEach((l,i)=>{l.classList.toggle('pv-kw',PV_KEY_SAVED.has(Number(l.dataset.pin)));
    if(!held[i]){l.classList.remove('pv-stack','pv-tight','pv-early-out'); l.style.removeProperty('--pv-t-h');}});
  // Every line is measured as the reading line (#doc.pv-measure shows each hidden identifier, components.css): a line that
  // stacked only while it was read shrank when the reading page left (91 -> 32px on a 260px page) and moved the pages.
  D.classList.add('pv-measure');
  // The figure's least width is its identifier's (--pv-fig-min): its title's own text would otherwise count in it.
  const ids=lines.map(l=>{const e=l.querySelector(':scope>.pv-fig>.pv-fig-id'); return e&&e.getClientRects().length?Math.ceil(e.getBoundingClientRect().width):0;});
  lines.forEach((l,i)=>{const v=ids[i]+'px'; if(l.style.getPropertyValue('--pv-fig-min')!==v)l.style.setProperty('--pv-fig-min',v);});
  // How far line l's state runs past its share, in px (its parts, also those inside a display: contents span - the reason and
  // [이유 추가]; 0 or less where it holds), less pvAddCut - a key save's way to the reason is drawn at the wider of its two
  // looks (--pv-add-w, set below) with the earlier link beside it, which it never shows at once -, or Infinity where the
  // buttons went to a row of their own. Its row does not hold (tight) past 1px.
  const past=(/** @type {HTMLElement} */l)=>{const t=l.querySelector(':scope>.pv-t'),g=l.querySelector(':scope>.vd-btns'); if(!t)return -Infinity;
    const tr=t.getBoundingClientRect(); if(g&&g.getClientRects().length>0&&g.getBoundingClientRect().top>=tr.bottom-1)return Infinity;
    const r=[...t.querySelectorAll(':scope>*,:scope>*>*')].reduce((m,c)=>c.getClientRects().length>0?Math.max(m,c.getBoundingClientRect().right):m,-Infinity);
    return r-tr.right-pvAddCut(l,t,addD);};
  const tight=(/** @type {HTMLElement} */l)=>past(l)>1;
  // A line too narrow for the state a press brings beside its words stacks whatever it shows now: a press that turned '판정 없음'
  // into '판정 #26 보류 · 처리 대기 · 이유 추가 · 판정 취소' stacked it then and moved every word under the finger (a phone, a page at
  // a small zoom: 3 rows, 91px, the words 59px down). That state's width is measured, not guessed (pvStateNeed), and so is
  // all that shares its row: the words as they are drawn, with the check a press puts on one of them (PV_NEED.check) where
  // none is pressed yet; the identifier and the dot after it; and the row's gaps between the four (its column gap). The sum
  // is the row the press brings, to the subpixel. An 8px and a 24px allowance in its place counted the dot (3px) as 8 and
  // the check as nothing - 5px too much for a resting line, 21px too little for a press: a line within 21px of the bar
  // stacked under its first press, a Korean one too (#308; the English words are sized for a 620px line, ui_en.json).
  const need=lines.length?pvStateNeed(lines[0]):0,gap=lines.length?parseFloat(getComputedStyle(lines[0]).columnGap)||0:0;
  // A key save's line - read, it says 'Enter 이유 쓰기'; at rest, [이유 추가] - lays its way to the reason out at the wider of
  // the two (the probe's, PV_NEED.add; .pv-kw, components.css #doc.pv-measure), so it is fitted the same whichever page is
  // read. Fitted on the look it showed, a line within the 40px between them (Korean) stacked only while it was read.
  const aw=PV_NEED.add,addD=Math.max(0,aw[1]-aw[0]),addW=Math.max(aw[0],aw[1])+'px'; if(D.style.getPropertyValue('--pv-add-w')!==addW)D.style.setProperty('--pv-add-w',addW);
  const W=(/** @type {Element|null} */e)=>e&&e.getClientRects().length?e.getBoundingClientRect().width:0;
  const narrow=lines.map((l,i)=>{if(held[i])return false; const g=l.querySelector(':scope>.vd-btns'),f=W(l.querySelector(':scope>.pv-fig>.pv-fig-id')); if(!g||!g.getClientRects().length)return false;
    const press=g.querySelector(':scope>.vd-b[aria-pressed="true"]')?0:PV_NEED.check,id=f?f+W(l.querySelector(':scope>.pv-fig-sep'))+2*gap:0;
    return l.getBoundingClientRect().width<W(g)+press+id+gap+need;});
  let over=lines.map((l,i)=>!held[i]&&(narrow[i]||tight(l)));
  // A tight line whose row holds all but its earlier link's count lets that step out too (.pv-early-out) rather than stack:
  // the last thing a desktop row gives way, at its bar - a line the person saved by a key over an earlier verdict there
  // ('+1' beside [이유 추가] at rest, which 'Enter 이유 쓰기' takes the place of while it is read: components.css).
  const out=lines.map(()=>false);
  if(LAYOUT===LAYOUT_MODE.WIDE&&over.some(o=>o)){lines.forEach((l,i)=>{if(over[i])l.classList.add('pv-tight');});
    over=lines.map((l,i)=>{if(!over[i]||narrow[i])return over[i]; const p=past(l); if(p<=1)return false;
      const t=/** @type {HTMLElement} */(l.querySelector(':scope>.pv-t')); out[i]=p-pvEarlyRoom(t)+pvAddCut(l,t,addD)<=1; return !out[i];});
    lines.forEach((l,i)=>{if(out[i])l.classList.add('pv-early-out');});}
  lines.forEach((l,i)=>{if(over[i])l.classList.add('pv-stack');});
  // A stacked line's state rows are the reading line's too: their height, measured here with what only the reading line shows
  // ([이유 추가], laid out unseen), is the least the state takes (--pv-t-h, components.css). Beside an earlier link a 420px
  // line's state wrapped to a second row only while it was read, and the line grew by it (91 -> 123px, #308 review).
  // Where that is more than the state takes now (.pv-t-kept), its rows stand at the top and the room is kept under them: centred
  // in it, a resting line's state stood 40-65px off its identifier's row (#308 review).
  const th=lines.map((l,i)=>{const t=over[i]?l.querySelector(':scope>.pv-t'):null; return t?t.getBoundingClientRect().height:0;});
  D.classList.remove('pv-measure'); pvLetBlocks(kept);   // the lines' fitted heights: what moves now is real, and anchors as ever
  const nat=lines.map((l,i)=>th[i]?/** @type {HTMLElement} */(l.querySelector(':scope>.pv-t')).getBoundingClientRect().height:0);
  lines.forEach((l,i)=>{if(held[i])return; const k=th[i]>nat[i]+0.5; l.classList.toggle('pv-t-kept',k); if(k)l.style.setProperty('--pv-t-h',th[i]+'px');});
  pvChipPlace(lines);
  // A word group that wraps keeps every button at its own width (vdWrapFit), read for every line before any is written.
  const groups=lines.map(l=>l.querySelector('.vd-btns')),wrap=groups.map(g=>!!g&&new Set([...g.children].map(b=>Math.round(b.getBoundingClientRect().top))).size>1);
  groups.forEach((g,i)=>{if(g)g.classList.toggle('wrapped',wrap[i]);});
  pvFocusStays(lines);}
  // Also when a step throws: never left measuring, every line keeps the height it is drawn at and may be skipped again
  // (pvFarLetGo, read once the measure is gone), and the view anchors again only after that - whatever pvFarLetGo does.
  finally{D.classList.remove('pv-measure'); pvLetBlocks(kept); try{pvFarLetGo(lines);}finally{pvHoldView(false,hold);}}}
// Keeps the block of each line pvFit is about to measure at the height it is drawn at, until pvLetBlocks: the pass takes a line's
// rows off and measures it as the reading line (#doc.pv-measure), and the line may grow inside its block, but the block, and the
// pages after it, stand still. So the area's scroll anchoring - WebKit's too, which carried the growth and not the shrink - has
// nothing to follow, while a line whose fitted height does change moves the pages after the pass as it always did. A block's
// height set, its last line's bottom margin no longer collapses through it: the block carries the space to the next block
// itself. The last block, with nothing after it, is left alone. Read before any is written; what each had inline is put back.
/** @param {HTMLElement[]} lines @returns {[HTMLElement,string,string][]} */
function pvKeepBlocks(lines){/** @type {Set<HTMLElement>} */ const set=new Set();
  lines.forEach(l=>{const b=l.parentElement; if(b&&b.classList.contains('pgw')&&b.nextElementSibling)set.add(b);});
  const bs=[...set],at=bs.map(b=>{const r=b.getBoundingClientRect(),n=/** @type {Element} */(b.nextElementSibling); return [r.height,n.getBoundingClientRect().top-r.bottom];});
  /** @type {[HTMLElement,string,string][]} */ const kept=[];
  bs.forEach((b,i)=>{const [h,g]=at[i]; if(!h)return; kept.push([b,b.style.height,b.style.marginBottom]); b.style.height=h+'px'; b.style.marginBottom=g+'px';});
  return kept;}
/** @param {[HTMLElement,string,string][]} kept */
function pvLetBlocks(kept){kept.forEach(([b,h,m])=>{b.style.height=h; b.style.marginBottom=m;}); kept.length=0;}
// Holds a pinch-zoomed view where it is across pvFit's pass (on) and lets go after it (off, given what on returned): the PDF
// area does not anchor its scroll (overflow-anchor), and its layout is brought up to date before it anchors again, so the
// anchor it then takes is where the pass left the pages - never a measure's grown lines. On returns the area's own value it
// replaced, which off puts back (a pass inside a pass leaves the outer one's hold), or null where it held nothing. At no zoom
// it does nothing: the pass moves no block there (pvKeepBlocks), and the area's anchoring stays as it is (no scroll of its own,
// ever).
/** @param {boolean} on @param {string|null} [was] @returns {string|null} */
function pvHoldView(on,was){const L=$('#left'),vv=window.visualViewport;
  if(!on){if(typeof was!=='string')return null; void L.offsetHeight; if(was)L.style.setProperty('overflow-anchor',was); else L.style.removeProperty('overflow-anchor'); return null;}
  if(!vv||vv.scale<=1)return null; const prev=L.style.getPropertyValue('overflow-anchor'); L.style.setProperty('overflow-anchor','none'); return prev;}
// The width the state of a person's fresh verdict takes on a line in a row, drawn in a hidden line like line l (its text size,
// the screen's language and pointer) and kept until those or the next pin number's digits change. Two states follow a
// press: after a click '판정 #0 <the longest word> · 처리 대기 · 이유 추가 · 판정 취소', and on a mouse screen after a key
// 'Enter 이유 쓰기' in place of [이유 추가] - the wider of the two is the need, with one more gap of the state's row for a
// save's words ('· 보류 저장 중…', .pv-busy), which give way down to nothing while the save is out (components.css). The pin
// number is drawn with as many digits as the next pin's (pvTopId), each a 0. A line narrower than that beside its words
// and identifier is stacked before any press (pvFit). Measuring the click state alone, a key save near the bar stacked
// the line under the press, and a second save's words pushed [판정 취소] out of the held row (#308). The probe then draws
// the longest word pressed and not (its check before it, its weight; one key mark on both): what a press adds to the
// words, kept as PV_NEED.check - 21px, which a line with no pressed word did not count and lost to its first press.
// PV_NEED.add: the way to the reason's own width as [이유 추가] and as 'Enter 이유 쓰기' (a mouse screen's; [이유 추가]'s
// again on a touch one), which every line is fitted at the wider of (pvFit).
let PV_NEED={key:'',w:0,check:0,add:[0,0]};
/** @param {HTMLElement} l */
function pvStateNeed(l){const v=pageVerdictsOn(); if(!v)return 0;
  const word=v.choices.map(c=>c.label).reduce((a,b)=>b.length>a.length?b:a,''),fine=matchMedia('(pointer:fine)').matches,num='#'+'0'.repeat(String(pvTopId()+1).length);
  const key=[getComputedStyle(l).fontSize,tr('판정'),word,MQ_COARSE.matches,fine,num].join('|');
  if(PV_NEED.key===key)return PV_NEED.w;
  const probe=document.createElement('div'); probe.className='pv'; probe.setAttribute('aria-hidden','true');
  probe.style.cssText='position:absolute;left:0;top:0;width:max-content;visibility:hidden;pointer-events:none;--pv-add-w:0px';   // its own width, not the lines' (pvFit)
  $('#doc').appendChild(probe);
  const state=(/** @type {boolean} */kb)=>{setHtml(probe,html`<span class="pv-t"><span class="pv-s">${tr('판정')} <span class="pin-ref pv-ref hit">${num}</span> <b class="vd-w">${word}</b></span><span class="pv-sep">·</span>\
<span class="pv-st">${tr('처리 대기')}</span><span class="pv-ra"><span class="pv-sep">·</span><button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">\
${kb?html`<kbd class="pv-kbd">Enter</kbd> ${tr('이유 쓰기')}`:tr('이유 추가')}</button></span>\
<span class="pv-sep pv-cn">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" tabindex="-1">${tr('판정 취소')}</button></span>`);
    const t=/** @type {HTMLElement} */(probe.firstElementChild),a=/** @type {HTMLElement} */(t.querySelector('.pv-add'));
    return [t.getBoundingClientRect().width+(parseFloat(getComputedStyle(t).columnGap)||0),a.getBoundingClientRect().width];};
  const sc=state(false),sk=fine?state(true):sc,w=Math.ceil(Math.max(sc[0],sk[0]));
  setHtml(probe,html`<span class="vd-btns"><button type="button" class="vd-b" aria-pressed="true" data-kn="1" tabindex="-1">${ic('check')}<span class="lbl">${word}</span></button>\
<button type="button" class="vd-b" aria-pressed="false" data-kn="1" tabindex="-1"><span class="lbl">${word}</span></button></span>`);
  const b=[...probe.querySelectorAll('.vd-b')].map(x=>x.getBoundingClientRect().width),check=Math.max(0,b[0]-b[1]); probe.remove();
  PV_NEED={key,w,check,add:[sc[1],sk[1]]}; return w;}
// A web font that arrives after the lines were measured - the bundled Pretendard after the fallback face - changes every
// width: the state's width is measured again and every line fits itself again (sizePv), once each font load is done and
// when the fonts are ready after boot. Kept from the fallback face, a width near the stacking threshold let the first save
// still move the words.
function pvFontsChanged(){PV_NEED={key:'',w:0,check:0,add:[0,0]}; if($$('#doc .pv').length)sizePv();}
if(document.fonts){document.fonts.addEventListener('loadingdone',pvFontsChanged); document.fonts.addEventListener('loadingerror',pvFontsChanged); document.fonts.ready.then(pvFontsChanged);}
// How much less than drawn a key save's line l's state (t) takes at most in a row, while it is fitted (pvFit): with its way to
// the reason drawn at the wider of its looks (d px more than [이유 추가]: 'Enter 이유 쓰기') and the earlier link beside it -
// which a tight line shows beside [이유 추가] but not beside 'Enter 이유 쓰기' (components.css) - the more of the two looks
// takes d less, or the link and its gap less, whichever is less. 0 for any other line, and for one that is not tight: it
// shows the link beside both.
/** @param {HTMLElement} l @param {Element} t @param {number} d @returns {number} */
function pvAddCut(l,t,d){if(!d||!l.classList.contains('pv-kw')||!l.classList.contains('pv-tight')||!t.querySelector(':scope>.pv-ra>.pv-add'))return 0;
  const e=pvEarlyRoom(t); return e?Math.min(d,e):0;}
// A focus on a control of one of these lines that its fitting just took out - the earlier link stepping out at a tight row's
// bar (.pv-early-out), or beside 'Enter 이유 쓰기' or [되돌리기] on a row that turned tight (components.css), after a resize, a
// zoom of the browser or of the pages, or a redraw - moves at once, without a scroll, to the control before it on its line
// ([판정 취소], 'Enter 이유 쓰기', the '#N' link), else to the line's first. Hidden with the focus on it, the link took the
// focus away to nothing and the next Tab started from the top (Chromium lets a hidden focus go a moment later: the move is
// made before that). Every way the fitting hides a control comes through here, and so does a phone's floating line holding
// [판정 취소] back (pvLean).
/** @param {HTMLElement[]} lines */
function pvFocusStays(lines){const a=/** @type {HTMLElement|null} */(document.activeElement),l=a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#doc .pv')):null;
  if(!a||!l||!lines.includes(l)||(a.getClientRects().length&&getComputedStyle(a).visibility!=='hidden'))return;
  const cs=[...l.querySelectorAll(PV_TABBABLE)].filter(pvTabStop),before=cs.filter(x=>!!(x.compareDocumentPosition(a)&Node.DOCUMENT_POSITION_FOLLOWING));
  const to=before.length?before[before.length-1]:cs[0]; if(to)to.focus({preventScroll:true});}
// The room state t's earlier link takes in its row as drawn - its width, the dot before it and the gap before each - or 0
// where it shows none.
/** @param {Element} t @returns {number} */
function pvEarlyRoom(t){const e=t.querySelector(':scope>.pv-early'); if(!e||!e.getClientRects().length)return 0;
  const g=parseFloat(getComputedStyle(t).columnGap)||0,d=e.previousElementSibling,dw=d&&d.classList.contains('pv-ea')&&d.getClientRects().length?d.getBoundingClientRect().width+g:0;
  return e.getBoundingClientRect().width+g+dw;}
// Whether line l keeps the rows it has now: its confirm word waits for the second press, or its save is out.
/** @param {HTMLElement} l */
function pvRowsHeld(l){const p=Number(l.dataset.page)||0; return (!!VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page===p)||PV_BUSY.has(pvSlot(p));}
// The save chip on a line ('#42 저장됨 · 채택 [되돌리기]') never changes the line: it is laid over it (notices.css), in room no
// control or state word of the line takes - never over the figure's identifier, the state, a text action, a word or a focus
// ring (8px clear of each), nor over the reason popover. The first room that holds it: in a row, between everything before the words and the words; in
// a stacked line, after the end of the state's last row; then over the figure's title after its identifier (its own row
// on a stacked line) - words that only describe; its words shown where any room holds them. Its words fold first (.pv-chip-short: its icon and [되돌리기]), then its
// icon (.pv-chip-bare); where not even [되돌리기] fits anywhere, the undo goes to the status line (chipAway). In the line's
// flow the chip added a row on a phone (131 -> 251px) and moved the words under a waiting finger, and laid over them it
// took presses meant for [이유 추가] and [판정 취소]. --pv-chip-r and --pv-chip-y place it from the line's right edge and top.
/** @param {HTMLElement[]} lines */
const PV_CHIP_WAIT_MS=3000;   // how long a chip with no room waits for its line to settle before its undo goes to the status line
const PV_CHIP_WAIT_T=/** @type {WeakMap<HTMLElement,number>} */(new WeakMap());
function pvChipPlace(lines){const chips=lines.map(l=>/** @type {HTMLElement|null} */(l.querySelector(':scope>.nt-chip')));
  lines.forEach((l,i)=>{if(chips[i]){l.classList.toggle('pv-chip-short',false); l.classList.toggle('pv-chip-bare',false);} else l.classList.remove('pv-chip-wait');});
  const got=lines.map((l,i)=>{const c=chips[i]; if(!c)return null;
    const lr=l.getBoundingClientRect(),R=(/** @type {Element} */e)=>e.getBoundingClientRect(),shown=(/** @type {Element} */e)=>e.getClientRects().length>0;
    const words=[...l.querySelectorAll(':scope>.vd-btns>*')].filter(shown).map(R);
    const parts=[...l.querySelectorAll(':scope>.pv-fig>.pv-fig-id,:scope>.pv-fig-sep,:scope>.pv-t *,:scope>.pv-err')].filter(e=>shown(e)&&!e.closest('.pv-pop')).map(R);
    const pop=l.querySelector(':scope>.pv-pop'),keep=parts.concat(words,pop&&shown(pop)?[R(pop)]:[]),ch=R(c),gap=parseFloat(getComputedStyle(c).columnGap)||0,w=(/** @type {string} */q)=>{const e=c.querySelector(q); return e&&shown(e)?R(e).width+gap:0;};   // a part and the chip's own gap beside it (4px): taken as 8px, the folded chip came out 8px wider than measured and stood 2px from the identifier
    const sizes=[ch.width,ch.width-w('.nt-t'),ch.width-w('.nt-t')-w('.nt-ic')];
    // A room on the row through y (a box's middle) from left to right: the room less 8px off every part in that row's height.
    /** @param {number} y @param {number} left @param {number} right */
    const room=(y,left,right)=>{const top=y-ch.height/2,bot=y+ch.height/2; let a=left,z=right;
      keep.filter(b=>b.top<bot&&b.bottom>top).forEach(b=>{if(b.right<=(a+z)/2)a=Math.max(a,b.right+8); else z=Math.min(z,b.left-8);}); return {a,z,y};};
    const rooms=[]; const stack=l.classList.contains('pv-stack');
    if(!stack&&words.length){const y=(Math.min(...words.map(b=>b.top))+Math.max(...words.map(b=>b.bottom)))/2;
      rooms.push(room(y,parts.filter(b=>b.top<y&&b.bottom>y).reduce((m,b)=>Math.max(m,b.right),lr.left)+8,Math.min(...words.map(b=>b.left))-8));}
    else{const t=[...l.querySelectorAll(':scope>.pv-t *')].filter(e=>shown(e)&&!e.closest('.pv-pop')).map(R).filter(b=>b.height>0);
      if(t.length){const last=Math.max(...t.map(b=>b.top)),row=t.filter(b=>b.bottom>last+1),y=(Math.min(...row.map(b=>b.top))+Math.max(...row.map(b=>b.bottom)))/2;
        rooms.push(room(y,row.reduce((m,b)=>Math.max(m,b.right),lr.left)+8,lr.right));}}
    const id=l.querySelector(':scope>.pv-fig>.pv-fig-id'),ft=l.querySelector(':scope>.pv-fig>.pv-fig-t');
    if(id&&ft&&shown(ft)){const ir=R(id); rooms.push(room((ir.top+ir.bottom)/2,ir.right+8,stack?lr.right:R(ft).right));}
    for(let k=0;k<3;k++)for(const r of rooms)if(sizes[k]<=r.z-r.a)return {r:Math.round(lr.right-r.z),y:Math.round(r.y-lr.top),short:k>0,bare:k>1};   // its words where any room holds them
    return {away:true};});
  // Going to the status line is for good (chipAway), so it is never decided on a line that is about to change: while its
  // save is out or a confirm word waits (pvRowsHeld - the chip comes before the save's end, and the line then shows the
  // new verdict and still '· 보류 저장 중…': on CI 69px of room for a 72px chip that had 146px a moment later, and three
  // browser tests lost their chip), or while a web font loads (a fresh state's new characters are drawn in a fallback face
  // until their Pretendard slice arrives). It waits unseen (.pv-chip-wait) and is placed when the line settles - the save's
  // end redraws the lines (drawPageVerdicts), the fonts' load fits them (pvFontsChanged) - or goes once PV_CHIP_WAIT_MS
  // have passed since it first had no room.
  lines.forEach((l,i)=>{const g=got[i],c=chips[i]; if(!g||!c)return;
    if(g.away){const t0=Number(c.dataset.noRoom)||Date.now(); c.dataset.noRoom=String(t0);
      if((pvRowsHeld(l)||(document.fonts&&document.fonts.status==='loading'))&&Date.now()-t0<PV_CHIP_WAIT_MS){l.classList.add('pv-chip-wait');
        clearTimeout(PV_CHIP_WAIT_T.get(c)); PV_CHIP_WAIT_T.set(c,setTimeout(()=>{if(c.isConnected&&c.parentElement===l)pvFit([l]);},PV_CHIP_WAIT_MS+20)); return;}
      l.classList.remove('pv-chip-wait'); chipAway(c); return;}
    delete c.dataset.noRoom; l.classList.remove('pv-chip-wait');
    l.style.setProperty('--pv-chip-r',g.r+'px'); l.style.setProperty('--pv-chip-y',g.y+'px');
    l.classList.toggle('pv-chip-short',!!g.short); l.classList.toggle('pv-chip-bare',!!g.bare);});}
// The reason popover's side (pvPopPlace): above its line, as drawn - unless the room above inside what the PDF area shows
// (under the section strip) is too short for it while the room below holds it: then under the line (.pv-pop-below). Where
// neither holds it, the larger side, the popover no taller than that (--pv-pop-max; it scrolls). Near the top an in-place
// line's popover opened under the strip and the top bar, a five-line reason showing only its last line.
function pvPopPlace(){const pop=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv>.pv-pop'));
  $$('#doc .pv.pv-pop-below').forEach(l=>{if(!pop||l!==pop.parentElement)l.classList.remove('pv-pop-below');});
  if(!pop)return; const l=/** @type {HTMLElement} */(pop.parentElement),L=$('#left'),lr=L.getBoundingClientRect();
  if(l.id==='pv-panel'){l.classList.remove('pv-pop-below'); l.style.removeProperty('--pv-pop-max'); return;}   // in the panel's flow, under its state
  let top=Math.max(lr.top,0); const s=document.getElementById('section-strip');
  if(s&&s.getClientRects().length){const sr=s.getBoundingClientRect(); if(sr.bottom>top&&sr.top<=top+1)top=sr.bottom;}
  const cover=(parseFloat(getComputedStyle(document.body).getPropertyValue('--pv-inset'))||0)+(parseFloat(L.style.getPropertyValue('--pv-kb-over'))||0);
  const bottom=lr.top+L.clientHeight-cover;
  if(l.style.getPropertyValue('--pv-pop-max'))l.style.removeProperty('--pv-pop-max');
  const b=l.getBoundingClientRect(),h=pop.offsetHeight,above=b.top-8-top,below=bottom-(b.bottom+8);
  const under=h>above&&(h<=below||below>above); l.classList.toggle('pv-pop-below',under);
  if(h>Math.max(above,below))l.style.setProperty('--pv-pop-max',Math.max(0,Math.floor(under?below:above))+'px');}
// No description box over a line's save chip (#295). The chip ('#42 저장됨 · 채택 [되돌리기]') stands at the line's end above it,
// where a word's box stands too: the press's own focus armed the box again (tooltip.js armTip), and a resting hand's
// slight move brought it back after anything had hidden it. While a chip is on a line (drawChips puts it there, its
// window takes it away) the line's words are drawn without their descriptions (vdButton quiet), so neither hover nor focus
// has a box to show; a chip that comes closes the box that is up. Its leaving draws the descriptions back. Watched per
// line (childList only: the chip is a child of the line).
const PV_CHIP_WATCH=typeof MutationObserver!=='undefined'?new MutationObserver(recs=>{
  // Whether a line now holds a chip it did not, or lost one: a chip taken out and put back on the same line (fillPv's morph)
  // is no change; one moved to another line is a change on both.
  const had=new Map(); recs.forEach(r=>{const k=(/** @type {NodeList} */l,v)=>[...l].forEach(n=>{if(n instanceof Element&&n.classList.contains('nt-chip')){
      const m=had.get(r.target)||new Map(); m.set(n,(m.get(n)||0)+v); had.set(r.target,m);}}); k(r.addedNodes,1); k(r.removedNodes,-1);});
  let came=false,went=false; had.forEach(m=>m.forEach(d=>{if(d>0)came=true; else if(d<0)went=true;}));
  if(!came&&!went)return;
  if(came)hideTip(); drawPageVerdicts();}):null;
// Draws the page verdict line under every page after the pages, the pin lists or the build change. Without page verdicts
// every line goes and the marks draw every pin as before.
function drawPageVerdicts(){const v=pageVerdictsOn(),f=/** @type {HTMLElement|null} */(document.activeElement);
  const on=!!f&&!!f.closest?/** @type {HTMLElement|null} */(f.closest('.pv')):null,had=!!on,onPage=on?Number(on.dataset.page)||0:0;
  if(VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&(!v||!vdArmStill(VD_ARM)))disarmVerdict(false);
  PV_SHOWN=new Set();
  // A document with no page lines has no reason field either: a session left from the one before (or from this one before
  // its words went) closes here, its text saved - pvReasonSync, after this, is never reached for it.
  if(!v||!META){if(PV_REASON)pvReasonLeave(); $$('#doc .pv,#doc .pv-sum').forEach(e=>e.remove()); pvPanelGone(); if(PV_SIDE)pvSideApply(false); pvTypingSync(); return;}
  const turn=pvSideTurn();   // beside the pages or under them (verdict-panel.js): the reading page holds until the spot is back
  try{pvReasonSync(); const map=pageVerdictPins(); PV_READ=pvReadingPage(); PV_KEYS=pvKeysPage(PV_READ);
    // Beside the pages: one panel for the reading page, and every page's verdicts are its - none draws a page-size mark.
    if(PV_SIDE){$$('#doc .pgw>.pv').forEach(e=>e.remove()); map.forEach(list=>list.forEach(p=>PV_SHOWN.add(p.id))); pvPanelFill(map,v);}
    else{pvPanelGone();
      $$('#doc .pg').forEach(pg=>{const page=+pg.dataset.page; let line=/** @type {HTMLElement|null} */(pg.nextElementSibling);
        if(!pageTakesVerdict(page)){if(line&&line.classList.contains('pv'))line.remove(); return;}   // the map says this page takes none
        if(!line||!line.classList.contains('pv')){line=document.createElement('div'); line.className='pv'; pg.after(line); if(PV_CHIP_WATCH)PV_CHIP_WATCH.observe(line,{childList:true});}
        fillPv(line,page,map.get(page),v);});}
    pvSums(map);
    sizePv();}
  finally{if(turn)pvSideSettle(turn);}
  pvStick();
  if(had)vdRefocus(f);
  pvReasonAfterLines();   // a reason field that went from under the focus hands it to its line
  if(turn)pvSideTurned(turn);   // the lines moved: the reading spot, a save chip and the focus come along
  // The control the focus was on went with this drawing (a take-back shows the verdict before it): its line's, never nothing.
  if(had){const a=document.activeElement; if((!a||a===document.body)&&!pvFocusLine(onPage))searchToPage();}
  pvTypingSync();}   // a redraw or a rebuild can take the focused reason field away without a focusout
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
  if(PV_SIDE){if(!document.getElementById('p'+t.page))return false; pvBring(t.page,true); flash(pvPanel()); return true;}   // the panel follows the page to the reading place
  const line=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+t.page+'"]')); if(!line)return false;
  const block=/** @type {HTMLElement} */(line.parentElement),L=$('#left');
  pvGlideInto(block,block.getBoundingClientRect().height<=L.clientHeight?'center':'start'); flash(line); return true;}

// ---------------- Lines far from the view (docs/handbook/viewer.md §판정 핀)
// A line more than a view's height above or below what the PDF area shows is left for the browser to skip (.pv-far:
// content-visibility:auto, components.css): it is not laid out or painted until it comes near. Each page PDF.js draws for
// the first time adds its embedded fonts to document.fonts, and every font added makes the browser lay out all the text in
// the page again: with the far cards already skipped (list.js lazyCards, #305) the 88 lines of a 91-page figure document
// were about 4,300 of the 7,400 objects laid out at each, and the first wheel scroll through it still had 8-9 long tasks
// (#322). A skipped line breaks none of the line's rules, because it is never another size than the one it is drawn at:
// - It stands at its drawn height: --pv-h (the contain-intrinsic-block-size; the line has no padding or border, so its box
//   is its content box), or the size the browser last drew it at (content-visibility:auto keeps it: contain-intrinsic-size
//   auto), which is the same. Whatever changes what a line shows or its width fits it again (fillPv, sizePv: pvFit), and
//   pvFit lays out every line it measures - a skipped one too (pvFarHold) - and keeps its height as it lets go of it
//   (pvFarLetGo); a line that goes far keeps the height the observer saw instead, where that is the later one. So a skip
//   never moves the pages and nothing scrolls to make up for one; and every line is still measured as the reading line
//   (#doc.pv-measure).
// - Skipping contains a line (paint containment): it draws its parts on whole pixels and clips what reaches past its box (a
//   focus ring, the pressed word's hint, the reason popover, a save chip). So no line in or near the view is skipped (the
//   observer's margin), and - whatever the observer said last - neither is the reading line, which floats, a line holding
//   the focus, its reason popover or a save chip, or a line pvFit is measuring (components.css). A script's measure inside a
//   skipped line lays it out for the answer (the keys' Tab stops), but the innerText of what is skipped is empty.
// Without IntersectionObserver no line is skipped.
let PV_FAR_IO=/** @type {IntersectionObserver|null} */(null),PV_FAR_H=-1;
const PV_FAR_SEEN=/** @type {Set<HTMLElement>} */(new Set());   // the lines the observer watches
const PV_FIT_AT=/** @type {WeakMap<HTMLElement,number>} */(new WeakMap());   // when pvFit last kept each line's height (performance.now())
// The lines pvFit is about to measure are laid out, skipped or not (.pv-fitting).
/** @param {HTMLElement[]} lines */
function pvFarHold(lines){if(typeof IntersectionObserver==='undefined')return; lines.forEach(l=>l.classList.add('pv-fitting'));}
// pvFit is done with lines: each keeps the height it is drawn at now (one not laid out - the changes view - keeps the one it
// had), may be skipped again, and is watched - a new line too; a line no longer in the page (another document, a rebuild)
// is no longer watched. Read before any is written.
/** @param {HTMLElement[]} lines */
function pvFarLetGo(lines){if(typeof IntersectionObserver==='undefined')return; const h=lines.map(l=>l.getBoundingClientRect().height),at=performance.now();
  const L=$('#left'),vh=L.clientHeight;
  lines.forEach((l,i)=>{if(h[i]){l.style.setProperty('--pv-h',h[i]+'px'); PV_FIT_AT.set(l,at);} l.classList.remove('pv-fitting');});
  pvFarWatch(lines,vh);}
// Watches lines (new ones; one no longer in the page is let go) with an observer whose margin is the PDF area's height vh, in
// px above and below its view (a percentage would be of its width): it is made again, watching every line, when that height
// changes.
/** @param {HTMLElement[]} lines @param {number} vh */
function pvFarWatch(lines,vh){
  if(!PV_FAR_IO||PV_FAR_H!==vh){if(PV_FAR_IO)PV_FAR_IO.disconnect(); PV_FAR_SEEN.clear(); PV_FAR_H=vh;
    PV_FAR_IO=new IntersectionObserver(pvFarSort,{root:$('#left'),rootMargin:vh+'px 0px'}); lines=$$('#doc .pgw>.pv,#doc .pv-sum');}   // a line or a summary under a page; never the panel
  const io=PV_FAR_IO;
  PV_FAR_SEEN.forEach(l=>{if(!l.isConnected){io.unobserve(l); PV_FAR_SEEN.delete(l);}});
  lines.forEach(l=>{if(!PV_FAR_SEEN.has(l)&&l.isConnected){io.observe(l); PV_FAR_SEEN.add(l);}});}
// The PDF area's height can change with no line fitted again - a window made only shorter while a scale is saved keeps that
// scale (autoW), so sizePv does not run: the margin follows it here, so far still means a view's height away.
if(window.ResizeObserver&&window.IntersectionObserver)new ResizeObserver(()=>{const vh=$('#left').clientHeight;
  if(PV_FAR_IO&&vh&&vh!==PV_FAR_H)pvFarWatch([],vh);}).observe($('#left'));
// The observer's reports: a line that came within a view's height of the PDF area's view is drawn as it is; one that went
// further is skipped, at the height the observer saw when that is later than pvFit's - not one not laid out (no height to
// stand at) or no longer in the page.
/** @param {IntersectionObserverEntry[]} es */
function pvFarSort(es){for(const e of es){const l=/** @type {HTMLElement} */(e.target);
  if(!l.isConnected)continue;
  if(e.isIntersecting){l.classList.remove('pv-far'); continue;}
  if(l.classList.contains('pv-far')||!e.boundingClientRect.height)continue;
  if(e.time>(PV_FIT_AT.get(l)||-1))l.style.setProperty('--pv-h',e.boundingClientRect.height+'px');
  l.classList.add('pv-far');}}

// ---------------- The line that floats, and the keys (docs/handbook/viewer.md §판정 핀)
// Only the reading page's line floats: the page under the reading line, the one the section strip names and the keys act
// on (PV_READ). Its line (.reading) is sticky to the PDF area's bottom within its page's block (.pgw, pages.js buildDoc):
// while its own place is below the area it floats there over the page (.stuck: an edge that sets it off the page), and it
// names the figure it decides; at the page's end it settles under it. Every other line stays in its place - a next page's
// line floating as soon as that page's top edge came in showed a second '판정 없음' for a figure not yet in view, and put
// another figure's buttons under a resting mouse or thumb. It does not float while a selection is being written (the
// composer has its own verdict row, and the line would cover the selection - or on a phone the sheet) nor over an open
// phone sheet (CSS). pvStick follows the reading page and marks the floating line; run once a frame while the area scrolls.
function pvStick(){if(pageVerdictsOn()&&pvSideCheck())return;   // the room crossed its bar: drawn again beside or under the pages (verdict-panel.js), which ran this
  const lines=$$('#doc .pv'); if(!lines.length)return; const L=$('#left'),lr=L.getBoundingClientRect();
  if(!lr.height)return;
  const pad=getComputedStyle(L).paddingBottom; if(L.style.getPropertyValue('--pv-pad-b')!==pad)L.style.setProperty('--pv-pad-b',pad);   // the end padding a sticky line keeps clear of (components.css)
  // A keyboard laid over the page without the layout giving way (the visual viewport shorter than the PDF area reaches - an
  // iPad's Safari, or a band whose PDF area does not follow --kb): the floating line and its popover rise by what it hides.
  const vv=window.visualViewport,kb=vv&&MQ_COARSE.matches?Math.max(0,Math.round(lr.top+L.clientHeight-(vv.offsetTop+vv.height))):0;
  if(L.style.getPropertyValue('--pv-kb-over')!==kb+'px')L.style.setProperty('--pv-kb-over',kb+'px');
  if(pvInsetR()!==PV_INSET_R)sizePv();   // a panel came over the area, went, or changed its width
  const at=pvReadingAt(),r=at&&pageTakesVerdict(at)?at:0,k=pvKeysPage(r);
  if(PV_REASON&&PV_REASON.page===r)PV_REASON.seen=true;
  else if(PV_REASON&&PV_REASON.seen)pvReasonLeave();   // the reading page left the field's page: moving on
  // A key's armed confirm word belongs to the page it was read on: another reading page lets it go.
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==r)disarmVerdict(false,true);
  // The new reading page stays where it is on screen without a scroll: a stacked line keeps the row of the figure's name it
  // shows while it is the reading line (components.css), so the line the reading page leaves keeps its height. Scrolling the
  // area by what a line's change moved a page ended a jump's smooth scroll where it was (an outline jump from page 4 to 40
  // stopped on page 5), and on a phone a slow scroll down then never passed a page's end: the page above came back under the
  // reading line, the reading page flipped back and the line grew again, 466 times in 14 drags.
  // Two pages in a row that take no verdict read 0 here, one after the other: the panel names the page, so it asks too.
  if(r!==PV_READ||k!==PV_KEYS||pvPanelStale(at)){if(r!==PV_READ)PV_KEY_GUARD=false;   // the person moved on: they are not typing on into a field that went
    const was=[PV_READ,PV_KEYS]; PV_READ=r; PV_KEYS=k; const map=pageVerdictPins(),v=pageVerdictsOn();
    const re=/** @type {HTMLElement[]} */([]);
    if(v&&PV_SIDE){pvPanelFill(map,v); re.push(pvPanel());}   // the panel shows the new reading page
    else if(v)new Set([...was,r,k]).forEach(n=>{const e=/** @type {HTMLElement|null} */(n?document.querySelector('#doc .pv[data-page="'+n+'"]'):null); if(e){fillPv(e,n,map.get(n),v); re.push(e);}});
    if(re.length)pvFit(re);   // the reading line names its figure: its row is measured again
    pvFocusOffPage(r,was[0]);}
  pvPanelPlace(); pvSumOn();
  lines.forEach(l=>{if(l.id==='pv-panel')return;   // the panel stands sticky beside the pages: it never floats at their foot
    const pg=/** @type {HTMLElement|null} */(l.previousElementSibling); if(!pg)return; const b=l.getBoundingClientRect();
    const stuck=l.classList.contains('reading')&&b.bottom>lr.top&&b.top<lr.bottom&&b.top<pg.getBoundingClientRect().bottom+4;   // in its own place it stands 8px under the page
    l.classList.toggle('stuck',stuck); pvLean(l,pg,b,stuck,L,lr);});
  pvPopPlace();}
// A phone's floating line holds [판정 취소] back (.pv-lean, components.css): unseen, not pressed, focused or heard - and in
// its place, so the line keeps its rows whether it floats or stands in its place. Taken out of the row, it let the short
// earlier link ('이전 1건') rise into its row while the line floated: 131 against 191px in place, and the next page jumped
// 60px under the finger as the line crossed its page's end. The in-place line and the card still offer it, with its 44px.
// Hysteresis keeps it from flipping at a page's end: shown, it leans once the line floats; leaning, it is shown again only
// when the line (its full height, measured when it was last shown) fits in its place under the page. Desktop and every
// other band: never.
const PV_FULL_H=/** @type {WeakMap<HTMLElement,{h:number,gap:number}>} */(new WeakMap());
/** @param {HTMLElement} l @param {HTMLElement} pg @param {DOMRect} b @param {boolean} stuck @param {HTMLElement} L @param {DOMRect} lr */
function pvLean(l,pg,b,stuck,L,lr){
  if(!document.body.classList.contains('band-phone')||!l.classList.contains('reading')||!l.querySelector('.pv-cancel')){l.classList.remove('pv-lean'); return;}
  const m=PV_FULL_H.get(l)||{h:0,gap:8},pb=pg.getBoundingClientRect().bottom; PV_FULL_H.set(l,m);
  if(!stuck)m.gap=Math.max(0,b.top-pb);
  if(!l.classList.contains('pv-lean')){m.h=b.height; if(stuck){l.classList.add('pv-lean'); pvFocusStays([l]);} return;}
  // Where a floating line's bottom stands: the area's bottom less its end padding and the line's sticky inset.
  const cs=getComputedStyle(L),limit=lr.top+L.clientHeight-parseFloat(cs.paddingBottom)-(parseFloat(getComputedStyle(l).bottom)||0);
  if(pb+m.gap+(m.h||b.height+64)<=limit)l.classList.remove('pv-lean');}
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
function pvReadingAt(){if(PV_AT_HELD)return PV_AT_HELD;   // the lines are moving beside or under the pages (verdict-panel.js)
  if(!pageVerdictsOn()||document.body.classList.contains('revision-open')||!$('#left').getClientRects().length)return 0;
  const a=topAnchor(readingDepth($('#left'))); return a?a.page:0;}
// The reading page when it has a line (pageTakesVerdict), else 0: its line floats and names its figure (PV_READ).
function pvReadingPage(){const n=pvReadingAt(); return n&&pageTakesVerdict(n)?n:0;}
// The page the keys 1-5 act on: reading page r while this screen may make a verdict, no selection is being written and no
// text field has the focus (its digits are text).
/** @param {number} r */
function pvKeysPage(r){return r&&canVerdict()&&$('#composer').hidden&&!typingNow()?r:0;}
let PV_READ=0;   // the reading page with a line: its line floats and names its figure
let PV_FRAME=0;
// Whether element e shows in the PDF area now (any part of it).
/** @param {Element} e */
function pvInView(e){const L=$('#left'),lr=L.getBoundingClientRect(),b=e.getBoundingClientRect(); return b.bottom>lr.top&&b.top<lr.top+L.clientHeight&&b.right>lr.left&&b.left<lr.right;}
// The reading page moved from page was to page r while the focus stays on a control of another page's line - was's own line
// (still in view after a PageDown) or one now out of view (the saved reason's pencil, a word): the focus goes to the PDF area,
// where Enter opens the reading page's reason and Tab goes to its line. Left there, the next Enter or Space acted on the page
// the person had left - its reason opened (off-screen) and the text meant for this page went into that page's note. A focus
// put on a third page's line in view stays: the person went there.
/** @param {number} r @param {number} was */
function pvFocusOffPage(r,was){const a=/** @type {HTMLElement|null} */(document.activeElement),l=a&&a.closest?a.closest('#doc .pv'):null;
  if(!a||!l||(a.closest&&a.closest('.pv-pop')))return; const n=Number(/** @type {HTMLElement} */(l).dataset.page);
  if(n!==r&&(n===was||!pvInView(a)))searchToPage();}
// The line control the focus went to and the reading page then: one focused on the reading page's line that is no longer it
// is the page the person left (pvOffPageKey), even before the frame that moves the focus (pvFocusOffPage).
let PV_LINE_FOCUS=/** @type {{el:Element,read:number}|null} */(null);
document.addEventListener('focusin',e=>{const t=/** @type {HTMLElement|null} */(e.target); PV_LINE_FOCUS=t&&t.closest&&t.closest('#doc .pv')?{el:t,read:PV_READ}:null;});
// Enter or Space on a control of a line that is not the reading page's - out of view, or the line of the page the person
// left (focused while it was the reading page) - does not act there (a press read before the focus moved, pvFocusOffPage):
// the focus goes to the PDF area, and Enter is taken as on the pages - the reading page's reason (pvReasonEnterKey) - while
// Space is only said.
/** @param {KeyboardEvent} e */
function pvOffPageKey(e){if((e.key!=='Enter'&&e.key!==' ')||e.ctrlKey||e.metaKey||e.altKey||e.isComposing)return; const t=/** @type {HTMLElement|null} */(e.target);
  const l=t&&t.closest?t.closest('#doc .pv'):null; if(!t||!l||(t.closest&&t.closest('.pv-pop'))||typingNow())return;
  const r=pvReadingAt(),n=Number(/** @type {HTMLElement} */(l).dataset.page),left=!!PV_LINE_FOCUS&&PV_LINE_FOCUS.el===t&&PV_LINE_FOCUS.read===n;
  if(PV_DROP_OUT.has(pvSlot(n))){e.preventDefault(); e.stopImmediatePropagation(); return;}   // its take-back is out
  if(!r||n===r||(pvInView(t)&&!left))return;
  e.preventDefault(); e.stopImmediatePropagation(); searchToPage();
  if(e.type!=='keydown')return;
  if(e.key==='Enter'){pvReasonEnterPages(e); return;}
  lineNote('보이지 않는 쪽의 단추라 누르지 않았습니다 — 읽는 쪽에서 다시 누릅니다',NOTICE_KIND.INFO,null,{source:'pv-offpage',life:NOTICE_LIFE.TIMER});}
addEventListener('keydown',pvOffPageKey,true); addEventListener('keyup',pvOffPageKey,true);   // keyup: a button's Space acts on its keyup
function pvStickSoon(){if(!PV_FRAME)PV_FRAME=requestAnimationFrame(()=>{PV_FRAME=0; pvStick();});}
$('#left').addEventListener('scroll',pvStickSoon,{passive:true});
addEventListener('resize',pvStickSoon);
{const vv=window.visualViewport; if(vv){vv.addEventListener('resize',pvStickSoon); vv.addEventListener('scroll',pvStickSoon);}}   // a keyboard over the page
$('#doc').addEventListener('input',e=>{const t=/** @type {HTMLElement} */(e.target); if(t.closest&&t.closest('.pv-pop'))pvStickSoon();});   // the reason field grows: its side again
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
  // A card's editor or reply open with the focus outside the pages (on its [저장], say): its keys, not the pages' - a digit
  // took the focus from it, and the Enter after it then opened nothing (pvReasonEnterPages waits for the editor).
  if((EDITOR.current||REPLY)&&!$('#left').contains(document.activeElement))return;
  const v=pageVerdictsOn(),n=+e.key,c=v&&v.choices[n-1],at=pvReadingAt(); if(!c||!at||!canVerdict())return;
  if(pvKeyGuarded(e))return;   // a reason field went from under the typing: its digits are not verdict keys
  if(pvAutoScrolling()){e.preventDefault(); pvSayGliding(); return;}   // a jump still gliding: the reading page is not yet the one asked for
  if(!pageTakesVerdict(at)){e.preventDefault(); lineNote('이 쪽은 판정을 받지 않습니다',NOTICE_KIND.INFO,null,{source:'verdict-key',life:NOTICE_LIFE.TIMER}); return;}
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==at)disarmVerdict(true,true);
  // The panel shows the page under the reading line at the key, also before the frame that would show it (verdict-panel.js).
  if(PV_SIDE&&pvPanel().dataset.page!==String(at))pvStick();
  const b=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+at+'"] button[data-act="pv-save"][data-key="'+CSS.escape(c.key)+'"]'));
  if(!b)return; e.preventDefault();
  // A digit pressed with the focus outside the pages (an outline entry, the page list's or the section strip's button, a
  // document tab, a card) brings the focus to the PDF area at once, as the save's end brings it to the line: left on that
  // control while the save was out, the Enter typed after the digit pressed it again - the outline jumped, the page field
  // opened and took the reason's text - instead of opening the reason. The area is a named region (index.html), so a screen
  // reader says 'PDF 쪽' for the moment it has the focus, not every page's text one after the other. Where the focus came
  // from is kept: Shift+Tab from the line goes back there (PV_CAME).
  const a=/** @type {HTMLElement|null} */(document.activeElement),L=$('#left'); if(a&&a!==document.body&&a!==L&&!L.contains(a)){pvCame(a); searchToPage();}
  verdictPress(b,'key');}
addEventListener('keydown',verdictKey);
// Whether the pages are gliding where a jump sent them (the outline, the page list, a card's [보기]): the PDF area is scrolling
// - from a scroll event to its scrollend (where the browser has none, 160ms after the last scroll) - and no wheel, touch,
// press or scrolling key of the person's came in the 500ms before it began. While it glides the page under the reading line
// is one it passes, not the one asked for: a verdict key or Enter then would act on a page scrolled past (an outline jump
// to page 64 saved 보류 on page 12). A scroll the person makes goes on acting at once; an instant jump ends at once.
let PV_SCROLL_AT=0,PV_SCROLL_HAND=0,PV_GLIDE=false,PV_JUMP=/** @type {number|null} */(null);   // PV_JUMP: the scrollTop a jump is going to
const PV_HAND=()=>{PV_SCROLL_HAND=performance.now(); PV_GLIDE=false; PV_JUMP=null;};   // the person takes the pages over
for(const t of ['wheel','touchstart','touchmove','pointerdown'])$('#left').addEventListener(t,PV_HAND,{passive:true,capture:true});
$('#left').addEventListener('pointermove',e=>{if(e.buttons)PV_HAND();},{passive:true,capture:true});   // a scroll bar dragged
// A scrolling key is the person's hand on the pages only where it scrolls them: on the PDF area, on a control in it (a
// line's word lets the arrows through) or on nothing - not in a text field, and not Space on a button, which it presses.
// ↓ in the outline's filter or list moves to a result, and the Enter after it started a jump the guard then took for the
// person's own scroll: a digit pressed while it glided saved on a page passed (PL83 from page 60: 보류 on page 71).
addEventListener('keydown',e=>{if(!SCROLL_KEYS.has(e.key))return; const t=e.target;
  if(!(t===document.body||t===document.documentElement||(t instanceof Element&&!!t.closest('#left'))))return;
  if(t instanceof HTMLElement&&(t.isContentEditable||/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)))return;
  if(e.key===' '&&t instanceof Element&&t.closest('button,[role=button],summary'))return;
  PV_HAND();},true);
const PV_SCROLLEND='onscrollend' in window;
$('#left').addEventListener('scroll',()=>{const t=performance.now(); if(PV_JUMP!==null&&t-PV_SCROLL_AT>1000)PV_JUMP=null;   // a jump that never got there
  if(PV_JUMP===null&&t-PV_SCROLL_AT>200)PV_GLIDE=t-PV_SCROLL_HAND>500; PV_SCROLL_AT=t;},{passive:true});   // a new run of scrolling decides, unless a jump said what it is
// The end of a jump is at its place: a manual scroll's own end, coming after the jump began, ended the guard in its first frames.
$('#left').addEventListener('scrollend',()=>{if(PV_JUMP!==null&&Math.abs($('#left').scrollTop-PV_JUMP)>2)return; PV_JUMP=null; PV_GLIDE=false;});
function pvAutoScrolling(){return PV_GLIDE&&performance.now()-PV_SCROLL_AT<(PV_SCROLLEND?1000:160);}
// Every smooth jump of the PDF area starts here (a page, an outline entry's place, a card's [보기]): it is a glide from now, not
// from its first scroll event a frame later, in which a digit acted on the page being left, and whatever the hand did just
// before - a recent wheel made the guard take the jump for the person's own scroll. Nothing to glide (reduced motion, or
// already there): no guard, no scroll event would end it.
/** @param {number} to - the scrollTop it goes to */
function pvGlideArm(to){const L=$('#left'),top=Math.max(0,Math.min(L.scrollHeight-L.clientHeight,to));
  if(SMOOTH==='smooth'&&Math.abs(top-L.scrollTop)>1){PV_JUMP=top; PV_GLIDE=true; PV_SCROLL_AT=performance.now();}}
/** @param {number} top */
function pvGlideTo(top){pvGlideArm(top); $('#left').scrollTo({top,behavior:SMOOTH});}
/** @param {Element} el @param {'start'|'center'} [block] */
function pvGlideInto(el,block){const L=$('#left'),r=el.getBoundingClientRect(),lr=L.getBoundingClientRect();
  pvGlideArm(L.scrollTop+(block==='center'?r.top+r.height/2-(lr.top+L.clientTop+L.clientHeight/2):r.top-lr.top-L.clientTop)); el.scrollIntoView({behavior:SMOOTH,block:block||'start'});}
// Said once while the pages glide: the key was not taken, press it again once they rest.
function pvSayGliding(){lineNote('쪽으로 가는 중이라 판정 키를 받지 않았습니다 — 멈춘 뒤 다시 누릅니다',NOTICE_KIND.INFO,null,{source:'verdict-key',life:NOTICE_LIFE.TIMER});}
// Tab from the PDF area (where Esc, a moved-on popover or a search leaves the focus) goes to the reading page's line - its
// first control - not to the first page's line, whose focus scrolled the document there.
// The focus on nothing (body) counts as on the PDF area after a press there: a press on a page leaves the focus where it was,
// and Chromium's next Tab starts from the pressed node - which a redrawn canvas had taken away, so it started from the
// document's first line (page 4 of 91).
// A reading page with no line (a figure document's list pages, which take no verdict - pageTakesVerdict) or with none of its
// controls to stop on (a viewer who may not make a verdict, '판정 없음') keeps the pages where they are as well: the Tab goes
// to the next stop in the pages from that page on - a mark, the next page's line - while it shows whole in the area's view,
// else on past the pages (pvEdgeStop: the status line's action, the panel's grip), else nowhere (the focus stays). Left to
// the DOM's order it went to the first line after the pages' start and scrolled them there: from page 1 of a 91-page figure
// document to page 4, also on first open (#322).
let PV_PTR_PAGES=false;
addEventListener('pointerdown',e=>{const t=/** @type {HTMLElement|null} */(e.target); PV_PTR_PAGES=!!t&&!!t.closest&&!!t.closest('#left')&&!t.closest('#doc .pv');},true);
document.addEventListener('focusin',e=>{const t=/** @type {HTMLElement|null} */(e.target); if(t&&t!==$('#left'))PV_PTR_PAGES=false;});
// So does Tab with nothing focused where no stop is drawn before the pages - a phone, whose nav bar, outline and section strip
// are not: its first Tab after opening went to page 4's line and scrolled there (0 -> 2067px).
addEventListener('keydown',e=>{const a=document.activeElement; if(e.key!=='Tab'||e.shiftKey||e.ctrlKey||e.metaKey||e.altKey||e.defaultPrevented)return;
  if(!(a===$('#left')||((!a||a===document.body)&&(PV_PTR_PAGES||!pvEdgeStop(false)))))return;
  const at=pvReadingAt(); if(!at)return;   // no page lines, or the pages are not shown: the DOM's order scrolls nothing to a line
  const r=pvReadingPage(),l=r?document.querySelector('#doc .pv[data-page="'+r+'"]'):null;
  const c=/** @type {HTMLElement|undefined} */(l?[...l.querySelectorAll('a,button,[tabindex="0"]')].find(x=>x instanceof HTMLElement&&x.getClientRects().length>0&&!(/** @type {HTMLButtonElement} */(x).disabled)):undefined);
  e.preventDefault(); const v=c?null:pvStopInView(at),to=c||v||pvEdgeStop(true);
  PV_IN_VIEW=v?{el:v,visit:captureVisit(),build:(META&&META.pages_build)||''}:null; if(to)to.focus({preventScroll:true});});
// The stop in the pages that Tab from the PDF area went to in view, while the reading page had no line to go to (above): a
// mark, or a later page's line. Shift+Tab from it leaves the pages the way the reading line's first stop does (pvOutStop,
// below) - the DOM's stop before it is a page above, off the screen, and the focus scrolled the pages there. Let go when the
// focus leaves the pages, on another document or build, and by the next Tab from the area.
let PV_IN_VIEW=/** @type {{el:HTMLElement,visit:{doc:string|null,seq:number},build:string}|null} */(null);
// The first Tab stop in the pages from page `at` on - its own marks, then the next pages' marks and lines in the DOM's
// order - when that stop shows whole in the PDF area's view (its client box, within the window) and nothing lies over any of
// it (the status line or the sheet over the area's bottom, a panel laid over its side: what its middle and four points 4px in
// from its corners hit is it), else null. Hit at its middle alone, a line half under the status line was taken. Reads the
// page blocks from `at` down to the area's bottom only.
/** @param {number} at @returns {HTMLElement|null} */
function pvStopInView(at){const L=$('#left'),v=L.getBoundingClientRect(),top=Math.max(0,v.top+L.clientTop),left=Math.max(0,v.left+L.clientLeft);
  const bot=Math.min(innerHeight,v.top+L.clientTop+L.clientHeight),right=Math.min(innerWidth,v.left+L.clientLeft+L.clientWidth);
  for(let n=at,b=document.querySelector('#doc .pgw[data-page="'+n+'"]');b;b=document.querySelector('#doc .pgw[data-page="'+(++n)+'"]')){
    if(b.getBoundingClientRect().top>=bot)return null;
    const x=[...b.querySelectorAll(PV_TABBABLE)].find(pvTabStop); if(!x)continue;
    const s=x.getBoundingClientRect(); if(s.top<top||s.bottom>bot||s.left<left||s.right>right)return null;
    const ix=Math.min(4,s.width/4),iy=Math.min(4,s.height/4),xs=[s.left+ix,(s.left+s.right)/2,s.right-ix],ys=[s.top+iy,(s.top+s.bottom)/2,s.bottom-iy];
    const pts=[[xs[1],ys[1]],[xs[0],ys[0]],[xs[2],ys[0]],[xs[0],ys[2]],[xs[2],ys[2]]];
    return pts.every(([px,py])=>{const h=document.elementFromPoint(px,py); return !!h&&(h===x||(!!h.closest&&h.closest(PV_TABBABLE)===x));})?x:null;}
  return null;}
// Tab into the pages from outside them - the outline, the section strip, the panel by Shift+Tab - goes to the reading page's
// line too (its first control; its last by Shift+Tab), else to the PDF area: the DOM's next stop is the first page's line (or
// the last page's), whose focus scrolled the document there. Only a Tab across the pages' edge is taken - from the last stop
// before the PDF area (the section strip's page button, where it shows) or, by Shift+Tab, from the first after it (the
// panel's) - and that stop is found by walking out from the area to the nearest one (pvEdgeStop), a few elements: every Tab
// outside the pages read every focusable element of the document and whether it showed (678 on a 91-page figure document).
const PV_TABBABLE='a[href],button,input,select,textarea,summary,[tabindex]';
// Whether x is a stop of the Tab order now: focusable by Tab, enabled, drawn, not hidden and not in an inert or hidden part.
/** @param {Element|null} x @returns {x is HTMLElement} */
function pvTabStop(x){return x instanceof HTMLElement&&x.matches(PV_TABBABLE)&&x.tabIndex>=0&&!(/** @type {HTMLButtonElement} */(x).disabled)&&x.getClientRects().length>0
  &&!x.closest('[inert],[hidden]')&&getComputedStyle(x).visibility!=='hidden';}
// The nearest Tab stop outside the PDF area on one side of it - the last before it, or (after) the first after it - or null.
// Walks out from the area element by element and passes a part that is not drawn (display: none, hidden, inert) whole.
/** @param {boolean} after @returns {HTMLElement|null} */
function pvEdgeStop(after){const w=document.createTreeWalker(document.body,NodeFilter.SHOW_ELEMENT,{acceptNode:n=>{const x=/** @type {Element} */(n);
    if(x.hasAttribute('hidden')||x.hasAttribute('inert')||(!x.getClientRects().length&&getComputedStyle(x).display==='none'))return NodeFilter.FILTER_REJECT;
    return pvTabStop(x)?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_SKIP;}});
  let n=/** @type {Node} */($('#left')); if(after)while(n.lastChild)n=n.lastChild;   // from the area's last node the next one is past the area
  w.currentNode=n; return /** @type {HTMLElement|null} */(after?w.nextNode():w.previousNode());}
// Where the focus came into the pages from, while it is in them: the stop a Tab into the pages was pressed on, or the control a
// digit key was pressed on (verdictKey) - an outline entry, a document tab, the section strip, the phone's tool bar - with
// the visit (captureVisit: the document and its switch) and build it was pressed on: a switch - also away and back - or a
// new build lets it go (pvOutStop), as any focus outside the pages does. Shift+Tab from the reading line goes back there
// (below).
let PV_CAME=/** @type {{el:HTMLElement,visit:{doc:string|null,seq:number},build:string}|null} */(null);
/** @param {HTMLElement} el */
function pvCame(el){PV_CAME={el,visit:captureVisit(),build:(META&&META.pages_build)||''};}
document.addEventListener('focusin',e=>{const t=e.target; if(t instanceof Element&&!t.closest('#left')){PV_CAME=null; PV_IN_VIEW=null;}});
// Where Shift+Tab leaves the pages to: where the focus came from (PV_CAME) while it is still a stop of this document and build
// before the pages - or, where nothing comes before them (a phone: the nav bar, the outline and the section strip are not
// drawn), one in the tool bar over the sheet (#bar1) -, else the last stop before the pages (pvEdgeStop: the section strip's
// or the nav bar's page button), else the phone's position button (#btn-pos, which opens its pages as those do). null for
// none.
function pvOutStop(){const k=PV_CAME; if(k&&!(currentVisit(k.visit)&&k.build===((META&&META.pages_build)||'')))PV_CAME=null;
  const L=$('#left'),edge=pvEdgeStop(false),c=PV_CAME?PV_CAME.el:null;
  if(c&&c.isConnected&&c.classList.contains('pv-sum'))return c;   // the summary whose press brought the focus to the panel (pvSumGo)
  if(c&&c.isConnected&&!L.contains(c)&&pvTabStop(c)&&((c.compareDocumentPosition(L)&Node.DOCUMENT_POSITION_FOLLOWING)||(!edge&&c.closest('#bar1'))))return c;
  const p=$('#btn-pos'); return edge||(pvTabStop(p)?p:null);}
addEventListener('keydown',e=>{const a=/** @type {HTMLElement|null} */(document.activeElement),L=$('#left');
  if(e.key!=='Tab'||e.ctrlKey||e.metaKey||e.altKey||e.defaultPrevented||!a||a===document.body||!a.closest||a.closest('#left'))return;
  // The focus on the side of the area this Tab leaves from, the area shown with page lines, and the focus on the edge's stop.
  if(!(a.compareDocumentPosition(L)&(e.shiftKey?Node.DOCUMENT_POSITION_PRECEDING:Node.DOCUMENT_POSITION_FOLLOWING))||!L.getClientRects().length
    ||!document.querySelector('#doc .pv')||pvEdgeStop(e.shiftKey)!==a)return;
  const r=pvReadingPage(),l=r?document.querySelector('#doc .pv[data-page="'+r+'"]'):null,cs=l?[...l.querySelectorAll('a,button,textarea,[tabindex="0"]')].filter(pvTabStop):[];
  e.preventDefault(); const c=e.shiftKey?cs[cs.length-1]:cs[0]; pvCame(a); if(c)c.focus({preventScroll:true}); else searchToPage();});
// Shift+Tab from the reading page's first stop leaves the pages the way the focus came in (pvOutStop): back to where it came
// from while that is still a stop before the pages - the outline entry or the document tab a digit key was pressed on, the
// section strip's page button Tab came from - else to the last stop before them, the section strip's page button (a
// phone's position button). The pages do not move. The reading page's first stop is its line's first control, or - when pins are marked on
// that page - its first mark's badge, which Shift+Tab from the line reaches first in the DOM's order. The DOM's stop before
// it is the page before's line: each Shift+Tab scrolled the document a page up, and 80 of them on a 91-page figure
// document never reached the outline. The earlier pages' lines are reached by PageUp, which makes each the reading page in
// turn. A line with its reason popover open keeps Tab to itself first (verdict-reason.js, on #doc), and another page's line
// or mark is left to the DOM's order - but for the stop Tab from the PDF area went to in view while the reading page had no
// line (PV_IN_VIEW), which leaves the same way.
addEventListener('keydown',e=>{if(e.key!=='Tab'||!e.shiftKey||e.ctrlKey||e.metaKey||e.altKey||e.defaultPrevented)return;
  // Beside the pages the panel is the reading line, and it stands after the pages in the DOM (verdict-panel.js): from its first
  // stop the reading page's marks come next, as they do from a line, and from the first of those the way out.
  const a=/** @type {HTMLElement|null} */(document.activeElement),panel=a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#pv-panel')):null;
  const blk=panel||(a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#doc .pgw')):null),l=panel||(blk&&(blk.querySelector(':scope>.pv')||document.getElementById('pv-panel')));
  const iv=PV_IN_VIEW; if(iv&&!(currentVisit(iv.visit)&&iv.build===((META&&META.pages_build)||'')))PV_IN_VIEW=null;
  if(!(a&&PV_IN_VIEW&&PV_IN_VIEW.el===a)){   // the stop Tab went to in view (above), on a page with a line or none
    if(!a||!blk||!l||Number(blk.dataset.page)!==pvReadingPage())return;
    const first=[...blk.querySelectorAll(PV_TABBABLE)].find(pvTabStop); if(first!==a)return;
    const m=panel?pvMarkStops(Number(panel.dataset.page)):[]; if(m.length){e.preventDefault(); m[m.length-1].focus(); return;}}
  const to=pvOutStop(); if(!to)return; e.preventDefault(); to.focus({preventScroll:true});
  if(to.closest('#outline')||to.classList.contains('pv-sum'))to.scrollIntoView({block:'nearest'});});   // an outline entry comes into the outline's view; the pages stay
