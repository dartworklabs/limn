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
// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else.
window.addEventListener('click',e=>{if(!VD_ARM)return; const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-act="verdict-save"],[data-act="pv-save"]'));
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
// generated text on a mouse screen only, so the button's text stays the word), said in its description and as
// aria-keyshortcuts; 0 elsewhere. quiet: drawn without its description (data-tip) - a page line whose save chip stands
// (pvLineHtml) - so no description box comes over the chip; the name and the keys are still said. A page line's armed word
// ('삭제 확정') has no description either: its box covered the line's figure name while the word waited for its second press,
// the button already reads what the box said, and the line says how long it waits beside it (.pv-arm).
/** @param {VerdictChoice} c @param {string} where @param {number} page @param {string} target @param {boolean} off @param {number} [kn] @param {boolean} [quiet] @param {number} [pr] */
function vdButton(c,where,page,target,off,kn,quiet,pr){const armed=vdArmedHere(c.key,where,page),line=where!==VD_WHERE.COMPOSER,on=line&&!!pr&&!armed;
  const name=armed?tl('{word} 확정 — {sec}초 안에 한 번 더 누르면 저장합니다',{word:c.label,sec:VD_ARM_MS/1000}):line?tl('{word} 판정 — {target}',{word:c.label,target})
    :tl('{word} 판정으로 저장 — {target}',{word:c.label,target});
  const fig=where===VD_WHERE.COMPOSER&&!!figureVerdictRoot(COMPOSE.current);
  let tip=armed?name:fig?tl('누르면 메모와 함께 이 그림 전체({target})의 {word} 판정 핀으로 바로 저장합니다',{word:c.label,target}):where===VD_WHERE.COMPOSER?tl('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다',{word:c.label})
    :pr===PV_PRESS.MINE?tr('지금 판정입니다 · 다시 누르면 이 판정을 거둡니다(판정 취소)'):pr===PV_PRESS.OTHER?tr('지금 판정입니다 · 다른 사람의 판정이라 여기서 거두지 않습니다')
    :pr===PV_PRESS.HANDLED?tr('지금 판정입니다 · 처리된 판정이라 카드의 [지우기]로 거둡니다'):pr===PV_PRESS.SAVING?tr('이 판정을 저장하는 중입니다'):tr('누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다');
  if(kn)tip+=' · '+tl(c.confirm?'단축키 {key} (두 번)':'단축키 {key}',{key:kn});
  return html`<button type="button" class="vd-b hit${c.confirm?' vd-confirm':''}${armed?' armed':''}" translate="no" data-act="${where===VD_WHERE.COMPOSER?'verdict-save':'pv-save'}" \
data-key="${c.key}" data-page="${page}" aria-label="${name}"${line?html` aria-pressed="${on?'true':'false'}"`:''}${on?html` aria-describedby="pv-on-${page}"`:''}\
${quiet||(armed&&line)?'':html` data-tip="${tip}"`}${kn?html` data-kn="${kn}" aria-keyshortcuts="${kn}"`:''}${off?line?html` aria-disabled="true"`:html` disabled`:''}>\
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
    if(pvCanCancel(cur)){PV_TOGGLE_HOLD.set(pvSlot(page),{key,until:Date.now()+PV_CANCEL_MS}); setTimeout(()=>drawPageVerdicts(),PV_CANCEL_MS+20); pvCancelPin(cur.id,page,false); return;}
    lineNote(tl('지금 판정 #{id} {word} 그대로 · {why} — {target}',{id:cur.id,word:c.label,target:pageTargetShort(page),
      why:pvPressOf(cur)===PV_PRESS.HANDLED?tr('처리된 판정은 카드의 [지우기]로 거둡니다'):tr('다른 사람의 판정은 여기서 거두지 않습니다')}),
      NOTICE_KIND.INFO,null,{source:'pv-press',life:NOTICE_LIFE.TIMER,literal:true});
    return;}
  if(c.confirm&&!armed){arm(); return;}
  disarmVerdict(false); hideTip();   // the box the press's focus armed: the save chip comes over the line (pvChipWatch)
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
    const r=PV_REASON&&PV_REASON.id===id?PV_REASON:null; if(r&&pvReasonDirty(r))rdPut(r.doc,id,r.text,r.base);
    PV_WITHDRAWN.add(id); const ok=await dropPin(id,true,undo); if(!ok)PV_WITHDRAWN.delete(id);
    if(ok&&PV_REASON&&PV_REASON.id===id){PV_REASON=null; drawPageVerdicts();}   // a withdrawn verdict takes no reason
    const d=ok?rdGet(DOC,id):null,k=was&&verdictOf(was),t=was?pageTargetOf(was,META?META.kind:undefined):null;
    if(d&&k)lineNote(tl('판정 #{id} {word} 저장 되돌림 · 쓰던 이유 보관 — {target}',{id,word:verdictLabel(k),target:t?pageTargetShort(t.page):'#'+id}),NOTICE_KIND.OK,
      {label:'되돌리기',tip:T.undo,wait:true,fn:async()=>{PV_WITHDRAWN.delete(id); const back=await restorePin(id); if(back)pvReasonRevive(id); return back;}},
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
// A line whose word was just taken back by pressing it again (pvSlot): that word waits until then (a double press takes back one).
const PV_TOGGLE_HOLD=/** @type {Map<string,{key:string,until:number}>} */(new Map());
// A page line's last failed save, by page: said on the line that was pressed (pvLineHtml) as well as on the status line, until
// the next press on that line or another document or build. The document and build it was for come with it.
const PV_ERR=/** @type {Map<number,{text:string,doc:string|null,build:string}>} */(new Map());
// The reason after a page line's save - its popover, drafts kept per pin, its writes - is verdict-reason.js (PV_REASON).
// The key marks follow the focus: off on every line while a text field has it - digits typed there are text - but for an
// empty reason field, whose line keeps them (pvKeysPage). (Another document closes the popover through pvReasonSync - or
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
// 24-85px and the click fell on the popover itself - the first tap was lost.
let PV_POP_PRESS=false;
function pvTypingSync(){const a=/** @type {HTMLElement|null} */(document.activeElement),l=a&&a.closest?/** @type {HTMLElement|null} */(a.closest('#doc .pv')):null,b=document.body;
  const pop=!!a&&!!a.closest&&!!a.closest('#doc .pv>.pv-pop'),on=(!!l&&typingNow())||(b.classList.contains('pv-typing')&&(pop||PV_POP_PRESS));
  if(b.classList.contains('pv-typing')===on)return; b.classList.toggle('pv-typing',on);
  const r=l||/** @type {HTMLElement|null} */(document.querySelector('#doc .pv.reading')); if(r)pvFit([r]);}
document.addEventListener('focusin',pvTypingSync); document.addEventListener('focusout',()=>setTimeout(pvTypingSync,0));
document.addEventListener('pointerdown',e=>{const t=/** @type {HTMLElement|null} */(e.target); if(!(t&&t.closest&&t.closest('#doc .pv>.pv-pop')))return;
  PV_POP_PRESS=true; let done=false; const end=()=>{if(done)return; done=true; window.removeEventListener('click',late); setTimeout(()=>{PV_POP_PRESS=false; pvTypingSync();},0);};
  const late=()=>end(); window.addEventListener('click',late); setTimeout(end,500);},true);   // after the press's own click (window, bubbling: after the viewer's handlers), or 500ms
// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build on screen, the body
// pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's selection and draft stay as
// they are. The word becomes the page's current verdict - a new pin (the agent runs the newest, D4 and D5); pressing the
// current word takes it back instead (pvPress). Saved: '#42 저장됨 [되돌리기]' on the line for NOTICE_MS; a refusal or a
// failure is said on the status line, result first ('판정 저장 실패 · <까닭> — <대상>'), and under the pressed line. While it
// is out the line says what it saves ('보류 저장 중…') and presses wait in PV_NEXT; the last of them is applied after it.
/** @param {number} page @param {string} key @param {boolean} [kb] - pressed from the keyboard: the reason popover takes the focus */
async function savePageVerdict(page,key,kb){const pg=META&&META.pages[page-1],slot=pvSlot(page); if(!pg||PV_BUSY.has(slot))return;
  const visit=captureVisit(),kind=META.kind,f=/** @type {HTMLElement|null} */(document.activeElement);
  const build=META.pages_build||'',fail=(/** @type {string} */text)=>{if(currentVisit(visit))PV_ERR.set(page,{text,doc:DOC,build});};
  // Said on the status line with what it was for, result first, and under the pressed line.
  const failed=(/** @type {string} */why)=>{lineNote(tl('판정 저장 실패 · {why} — {target}',{why,target:pageTargetShort(page)}),NOTICE_KIND.ERR,null,{source:'page-verdict',literal:true});
    fail(tl('{what} 실패',{what:tr('판정 저장')})+' — '+why);};
  let saved=false; PV_ERR.delete(page);
  let back=!!f&&!!f.closest&&!!f.closest('#doc .pv')&&f.dataset.act==='pv-save'&&f.dataset.key===key;   // a keyboard press: the focus comes back
  // ...unless it moved meanwhile to anything but that button (another page's word, a '#N' link, the panel): a redraw that puts
  // it back on the same word's button is no move.
  let away=false;   // the person put the focus anywhere else meanwhile: neither the button nor the reason field takes it back
  const moved=e=>{const t=/** @type {HTMLElement} */(e.target);
    if(!(t&&t.dataset&&((t.dataset.act==='pv-save'&&t.dataset.key===key&&t.dataset.page===String(page))||pvIsReasonField(t)))){back=false; away=true;}};
  document.addEventListener('focusin',moved);
  const before=(pageVerdictPins().get(page)||[])[0],prev=before?before.id:0;   // the verdict a save replaces: a draft kept for it moves on
  PV_BUSY.set(slot,key); drawPageVerdicts();
  try{const d=(await api('/api/pick',{method:'POST',body:{page,x0:0,y0:0,x1:pg.pt_w,y1:pg.pt_h,frac:WHOLE_PAGE.slice(),pdf_build:META.pages_build||undefined,doc:DOC||undefined},
      what:'판정 저장',silent:true})).data;
    if(!currentVisit(visit))return;
    if(d.error){failed(errText(d)); if(d.pdf_build_gone)refreshDoc().catch(()=>{}); return;}
    const body=pageVerdictBody(d,kind);
    if(!body){lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다',NOTICE_KIND.WARN,null,{source:'page-verdict'}); fail(tr('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다')); return;}
    Object.assign(body,{note:'',doc:DOC||undefined,kind_req:KIND_REQ.FIX,assignee:ASSIGNEE_AGENT,verdict:key});
    const id=(await api('/api/pin',{method:'POST',body,what:'판정 저장',silent:true})).data.id; saved=true;
    sourceOk('page-verdict');
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다',{id,word:verdictLabel(key),target:pageTargetShort(page)}),{label:'되돌리기',wait:true,fn:verdictUndo(id)},
      {pin:id,pending:true,label:tl('#{id} 저장됨 · {word}',{id,word:verdictLabel(key)})});
    if(currentVisit(visit))pvReasonAfterSave(page,id,key,!!kb,prev);   // the reason popover: a draft on this line moves to the new verdict
    await loadPins(); settleChip(chip); if(currentVisit(visit))pvOnShow(page);
  }catch(e){const x=/** @type {ApiError} */(e);
    if(!saved&&currentVisit(visit))failed(x&&x.status?(x.data&&errText(x.data))||('HTTP '+x.status):tr('서버에 닿지 않습니다'));}
  finally{document.removeEventListener('focusin',moved); PV_BUSY.delete(slot); drawPageVerdicts();
    if(currentVisit(visit)&&!pvReasonFocusAfter(page,away)&&back)pvRefocus(page,key);
    const nx=PV_NEXT.get(slot); PV_NEXT.delete(slot);
    if(nx&&currentVisit(visit)){const cur=(pageVerdictPins().get(page)||[])[0];
      if(!(cur&&verdictOf(cur)===nx.key))savePageVerdict(page,nx.key,!!nx.how);}}}
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
// [판정 취소] on page `page`'s line - or its pressed word pressed again (pvPress): verdict pin id goes to the Trash as the
// card's [지우기] sends it (dropPin) - a withdrawn request - and the line shows at once what is current now: the newest
// earlier verdict about the same target (D4) or '판정 없음'. The status line says so result first ('판정 #17 채택 취소 · 지금
// 판정 #12 보류 — <대상>', or '… · 남은 판정 없음 — …') with [되돌리기], which restores it (restorePin) and its kept reason
// draft (pvReasonRevive); one an agent had claimed still goes, and the status line says its run may have started (as the
// save's undo, verdictUndo). Its reason popover closes with it; what was typed is not written, and stays kept for that
// [되돌리기]. A failure is said on the status line and the line shows the verdict again, its popover too. The page's next
// [판정 취소] waits PV_CANCEL_MS: the same place may now cancel the earlier verdict, which a double press must not reach.
// A keyboard press leaves the focus on the PDF area, as Esc in the reason field does.
/** @param {HTMLElement} b */
function pvCancel(b){const id=Number(b.dataset.ref),page=Number((b.closest('.pv')||b).getAttribute('data-page'))||0;
  if(b.getAttribute('aria-disabled')==='true')return; pvCancelPin(id,page,document.activeElement===b);}
/** @param {number} id @param {number} page @param {boolean} had - the focus was on what was pressed */
async function pvCancelPin(id,page,had){const p=OPEN_ALL.find(x=>x.id===id);
  if(!p||!pvCanCancel(p)||viewerBlocked())return;
  const key=/** @type {string} */(verdictOf(p)),claimed=claimActive(p),target=pageTargetShort(page);
  const inField=pvIsReasonField(document.activeElement)&&!!PV_REASON&&PV_REASON.id===id;
  PV_CANCEL_HOLD.set(pvSlot(page),Date.now()+PV_CANCEL_MS); setTimeout(()=>drawPageVerdicts(),PV_CANCEL_MS+20);
  // Its reason popover leaves with the line's verdict, but the session is kept until the server answers: a failed cancel
  // brings the verdict back and its unsent reason with it (unless a newer session took the line); a done one drops it -
  // its draft stays kept (rdPut) for the [되돌리기].
  const kept=PV_REASON&&PV_REASON.id===id?PV_REASON:null; if(kept){PV_REASON=null; if(pvReasonDirty(kept))rdPut(kept.doc,id,kept.text,kept.base);}
  PV_WITHDRAWN.add(id);
  const say=()=>{const now=(pageVerdictPins().get(page)||[])[0],nk=now&&verdictOf(now);
    const rest=now&&nk?tl('지금 판정 #{id} {word}',{id:now.id,word:verdictLabel(nk)}):tr('남은 판정 없음');
    lineNote(tl('판정 #{id} {word} 취소 · {rest} — {target}',{id,word:verdictLabel(key),rest,target}),NOTICE_KIND.OK,
      {label:'되돌리기',tip:T.undo,wait:true,fn:async()=>{PV_WITHDRAWN.delete(id); const ok=await restorePin(id); if(ok)pvReasonRevive(id); return ok;}},
      {life:NOTICE_LIFE.TIMER,undo:true,literal:true});};
  hideTip();
  const again=()=>{PV_CANCEL_HOLD.delete(pvSlot(page)); drawPageVerdicts(); pvCancelPin(id,page,false);};   // [다시 시도] is a new press: no hold
  const ok=await dropPin(id,false,again,
    {say,where:NOTICE_HOST.LINE,what:'판정 취소'});
  if(!ok){PV_WITHDRAWN.delete(id); if(kept&&!PV_REASON&&kept.doc===DOC&&currentVisit(kept.visit)){kept.focus=false; PV_REASON=kept; drawPageVerdicts();}}
  if((had||inField)&&(!document.activeElement||document.activeElement===document.body))searchToPage();
  if(ok&&claimed)lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다',NOTICE_KIND.WARN);}
// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and word,
// and who made it and when if that was someone else - its reason (pvReasonInline: a check and its first line, a kept draft, [이유 추가]),
// [판정 취소] on the person's own while it is open (pvCanCancel), the earlier open verdicts as a link ('이전 판정 N건 · 새
// 판정으로 대체됨'), and, for a person who may make one, a button per word. The current verdict's word is pressed (a toggle,
// pvPress); while a save on the line is out, the word it saves - or the last one pressed meanwhile (PV_NEXT) - is pressed
// instead and the state says '보류 저장 중…'. The reason popover (pvReasonPop) is the line's last child, laid above it.
/** @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v @param {boolean} [chip] - the line holds a save chip or its reason popover: it draws no descriptions */
function pvLineHtml(page,list,v,chip){const cur=list&&list[0],earlier=list?list.slice(1).filter(p=>pinState(p)===PIN_STATE.OPEN):[];
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
    :html`<span class="pv-s pv-none">${tr(loading?'판정 읽는 중…':'판정 없음')}</span>`;
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
data-ref="${cur.id}" data-id="${cur.id}" aria-label="${tl('내 판정 #{id} 취소',{id:cur.id})}" \
${chip?'':html`data-tip="${tr('이 판정을 거둡니다. 핀은 휴지통으로 가고, 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 상태 줄의 [되돌리기]가 되살립니다')}"`}${cw?html` aria-disabled="true"`:''}>${tr('판정 취소')}</button>`:'';
  const early=earlier.length?html`<button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" \
${chip?'':html`data-tip="${tr('이 쪽의 더 새 판정으로 대체되어 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다')}"`}>${tl('이전 판정 {n}건 · 새 판정으로 대체됨',{n:earlier.length})}</button>`:'';
  // The reading page's line - the one that floats - names what it decides: '7쪽 · [후보] PL18 · …' (figureName), cut to fit.
  // Its two spans are on every line, empty and hidden but on the reading one: the line's children keep their places when
  // the reading page moves, so the morph (pvMorph) never takes a focused button out of the page.
  const rd=PV_READ===page,nm=rd?pvFigParts(page):{id:'',rest:''};
  const name=html`<span class="pv-fig" translate="no"${rd?'':html` hidden`}><span class="pv-fig-id">${nm.id}</span>${nm.rest?html`<span class="pv-fig-t">${' · '+nm.rest}</span>`:''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true"${rd?'':html` hidden`}>·</span>`;
  const keys=PV_KEYS===page,target=tl('{page}쪽',{page}),held=PV_TOGGLE_HOLD.get(slot),hold=held&&held.until>Date.now()?held.key:null;
  const pr=(/** @type {string} */key)=>key!==want?PV_PRESS.NONE:nx||sv!==undefined?PV_PRESS.SAVING:cur?pvPressOf(cur):PV_PRESS.NONE;
  const btns=canVerdict()?html`<span class="vd-btns">${v.choices.map((c,i)=>vdButton(c,VD_WHERE.PAGE,page,target,loading||c.key===hold,keys?i+1:0,!!chip,pr(c.key)))}</span>`:'';
  // The line's last failed save, said where it was pressed (PV_ERR) - for the document and build on screen only.
  const e=PV_ERR.get(page),eo=!!e&&e.doc===DOC&&!!META&&e.build===(META.pages_build||'');
  const err=html`<span class="pv-err"${eo?'':html` hidden`}>${eo&&e?e.text:''}</span>`;   // always there, so the reason field after it keeps its place
  return html`${name}<span class="pv-t">${text}${saving}${armSay}${cancel}${early}</span>${btns}${err}${pvOnHint(page,v,want,nx||sv!==undefined?PV_PRESS.SAVING:cur?pvPressOf(cur):PV_PRESS.NONE)}${pvReasonPop(page)}`;}
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
  const m=pvLineHtml(page,list,v,!!chip||pvReasonOn(page)); if(PV_TEXT.get(el)===m.text)return; PV_TEXT.set(el,m.text);
  if(chip)chip.remove(); const next=document.createElement('div'); setHtml(next,m); pvMorphKids(el,next); if(chip)el.appendChild(chip);
  el.classList.toggle('pv-pop-open',!!el.querySelector(':scope>.pv-pop')); pvReasonAfterDraw(el);}
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
  const room=innerW()-ir,lr=L.getBoundingClientRect(),fitted=L.scrollWidth<=L.clientWidth+1;
  const end=lr.left+L.clientLeft+L.clientWidth-parseFloat(getComputedStyle(L).paddingRight)-ir;   // the room's right edge on screen
  const at=lines.map(e=>{const pg=document.getElementById('p'+e.dataset.page),blk=e.parentElement; if(!pg||!blk)return null;
    const p=pg.getBoundingClientRect(); return {w:parseFloat(pg.style.width)||p.width,left:p.left,off:p.left-blk.getBoundingClientRect().left};});
  lines.forEach((e,i)=>{const a=at[i]; let w=a?Math.min(a.w,room):room,ml='';
    if(a&&fitted&&end-a.left<w&&end-a.left>=PV_MIN_W){w=end-a.left; ml=Math.round(a.off)+'px';}
    e.style.width=Math.round(w)+'px'; e.style.marginLeft=ml;});
  pvFit(lines);}
// One row or stacked, decided per line (.pv-stack; P2-7 of the 0.4.33 review: one line with an earlier verdict or a reason
// stacked every line of the document, 88px over the plot at 1440). Each line is laid out as one row - the figure's title cut
// first, down to its identifier ('6쪽 · PL17', pvFigParts; --pv-fig-min), then the reason and the earlier link
// (components.css) - and stacks only when its state's own words, [판정 취소] and its buttons still cannot share the row: the
// state runs past its share, or the buttons went to a row of their own (a narrow page). On the wide band a line that does not
// fit first lets the reason and the earlier link go further (.pv-tight): a desktop keeps one row, a second row covered the
// plot. A line narrower than a verdict's state beside its words stacks whatever it shows, so a press never stacks it. A line whose confirm word waits for its second press, or whose save is out, keeps the rows it has (pvRowsHeld): its
// words moving between the two presses sent the second one elsewhere. The save chip is placed after (pvChipPlace).
// Read and written in batches.
/** @param {HTMLElement[]} lines */
function pvFit(lines){const held=lines.map(pvRowsHeld);
  lines.forEach((l,i)=>{if(!held[i]){l.classList.toggle('pv-stack',false); l.classList.toggle('pv-tight',false);}});
  // The figure's least width is its identifier's (--pv-fig-min): its title's own text would otherwise count in it.
  const ids=lines.map(l=>{const e=l.querySelector(':scope>.pv-fig>.pv-fig-id'); return e&&e.getClientRects().length?Math.ceil(e.getBoundingClientRect().width):0;});
  lines.forEach((l,i)=>{const v=ids[i]+'px'; if(l.style.getPropertyValue('--pv-fig-min')!==v)l.style.setProperty('--pv-fig-min',v);});
  // Whether line l's row does not hold: the state runs past its share (its parts, also those inside a display: contents span -
  // the reason and [이유 추가]), or the buttons went to a row of their own.
  const tight=(/** @type {HTMLElement} */l)=>{const t=l.querySelector(':scope>.pv-t'),g=l.querySelector(':scope>.vd-btns'); if(!t)return false;
    const tr=t.getBoundingClientRect(); return [...t.querySelectorAll(':scope>*,:scope>*>*')].some(c=>c.getClientRects().length>0&&c.getBoundingClientRect().right>tr.right+1)
      ||(!!g&&g.getClientRects().length>0&&g.getBoundingClientRect().top>=tr.bottom-1);};
  // A line too narrow for a verdict's state beside its words stacks whatever it shows now: a press that turned '판정 없음' into
  // '판정 #26 보류 · 처리 대기 · 이유 추가 · 판정 취소' stacked it then and moved every word under the finger (a phone, a page at
  // a small zoom). PV_STATE_EM is about that state's width in the line's text.
  const narrow=(/** @type {HTMLElement} */l)=>{const g=l.querySelector(':scope>.vd-btns'),f=l.querySelector(':scope>.pv-fig>.pv-fig-id'); if(!g||!g.getClientRects().length)return false;
    const em=parseFloat(getComputedStyle(l).fontSize)||12; return l.getBoundingClientRect().width<g.getBoundingClientRect().width+(f&&f.getClientRects().length?f.getBoundingClientRect().width+8:0)+PV_STATE_EM*em+16;};
  let over=lines.map((l,i)=>!held[i]&&(narrow(l)||tight(l)));
  if(LAYOUT===LAYOUT_MODE.WIDE&&over.some(o=>o)){lines.forEach((l,i)=>{if(over[i])l.classList.add('pv-tight');}); over=lines.map((l,i)=>over[i]&&tight(l));}
  lines.forEach((l,i)=>{if(over[i])l.classList.add('pv-stack');});
  pvChipPlace(lines);
  // A word group that wraps keeps every button at its own width (vdWrapFit), read for every line before any is written.
  const groups=lines.map(l=>l.querySelector('.vd-btns')),wrap=groups.map(g=>!!g&&new Set([...g.children].map(b=>Math.round(b.getBoundingClientRect().top))).size>1);
  groups.forEach((g,i)=>{if(g)g.classList.toggle('wrapped',wrap[i]);});}
const PV_STATE_EM=24;   // the room an own verdict's state takes on the line (pvFit), in the line's em
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
function pvChipPlace(lines){const chips=lines.map(l=>/** @type {HTMLElement|null} */(l.querySelector(':scope>.nt-chip')));
  lines.forEach((l,i)=>{if(chips[i]){l.classList.toggle('pv-chip-short',false); l.classList.toggle('pv-chip-bare',false);}});
  const got=lines.map((l,i)=>{const c=chips[i]; if(!c)return null;
    const lr=l.getBoundingClientRect(),R=(/** @type {Element} */e)=>e.getBoundingClientRect(),shown=(/** @type {Element} */e)=>e.getClientRects().length>0;
    const words=[...l.querySelectorAll(':scope>.vd-btns>*')].filter(shown).map(R);
    const parts=[...l.querySelectorAll(':scope>.pv-fig>.pv-fig-id,:scope>.pv-fig-sep,:scope>.pv-t *,:scope>.pv-err')].filter(e=>shown(e)&&!e.closest('.pv-pop')).map(R);
    const pop=l.querySelector(':scope>.pv-pop'),keep=parts.concat(words,pop&&shown(pop)?[R(pop)]:[]),ch=R(c),w=(/** @type {string} */q)=>{const e=c.querySelector(q); return e&&shown(e)?R(e).width+8:0;};   // a part and its 8px gap
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
  lines.forEach((l,i)=>{const g=got[i],c=chips[i]; if(!g||!c)return;
    if(g.away){chipAway(c); return;}
    l.style.setProperty('--pv-chip-r',g.r+'px'); l.style.setProperty('--pv-chip-y',g.y+'px');
    l.classList.toggle('pv-chip-short',!!g.short); l.classList.toggle('pv-chip-bare',!!g.bare);});}
// The reason popover's side (pvPopPlace): above its line, as drawn - unless the room above inside what the PDF area shows
// (under the section strip) is too short for it while the room below holds it: then under the line (.pv-pop-below). Where
// neither holds it, the larger side, the popover no taller than that (--pv-pop-max; it scrolls). Near the top an in-place
// line's popover opened under the strip and the top bar, a five-line reason showing only its last line.
function pvPopPlace(){const pop=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv>.pv-pop'));
  $$('#doc .pv.pv-pop-below').forEach(l=>{if(!pop||l!==pop.parentElement)l.classList.remove('pv-pop-below');});
  if(!pop)return; const l=/** @type {HTMLElement} */(pop.parentElement),L=$('#left'),lr=L.getBoundingClientRect();
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
  const had=!!f&&!!f.closest&&!!f.closest('.pv');
  if(VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&(!v||!vdArmStill(VD_ARM)))disarmVerdict(false);
  PV_SHOWN=new Set();
  // A document with no page lines has no reason field either: a session left from the one before (or from this one before
  // its words went) closes here, its text saved - pvReasonSync, after this, is never reached for it.
  if(!v||!META){if(PV_REASON)pvReasonLeave(); $$('#doc .pv').forEach(e=>e.remove()); pvTypingSync(); return;}
  pvReasonSync(); const map=pageVerdictPins(); PV_READ=pvReadingPage(); PV_KEYS=pvKeysPage(PV_READ);
  $$('#doc .pg').forEach(pg=>{const page=+pg.dataset.page; let line=/** @type {HTMLElement|null} */(pg.nextElementSibling);
    if(!pageTakesVerdict(page)){if(line&&line.classList.contains('pv'))line.remove(); return;}   // the map says this page takes none
    if(!line||!line.classList.contains('pv')){line=document.createElement('div'); line.className='pv'; pg.after(line); if(PV_CHIP_WATCH)PV_CHIP_WATCH.observe(line,{childList:true});}
    fillPv(line,page,map.get(page),v);});
  sizePv(); pvStick();
  if(had)vdRefocus(f);
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
  // A keyboard laid over the page without the layout giving way (the visual viewport shorter than the PDF area reaches - an
  // iPad's Safari, or a band whose PDF area does not follow --kb): the floating line and its popover rise by what it hides.
  const vv=window.visualViewport,kb=vv&&MQ_COARSE.matches?Math.max(0,Math.round(lr.top+L.clientHeight-(vv.offsetTop+vv.height))):0;
  if(L.style.getPropertyValue('--pv-kb-over')!==kb+'px')L.style.setProperty('--pv-kb-over',kb+'px');
  if(pvInsetR()!==PV_INSET_R)sizePv();   // a panel came over the area, went, or changed its width
  const r=pvReadingPage(),k=pvKeysPage(r);
  if(PV_REASON&&PV_REASON.page===r)PV_REASON.seen=true;
  else if(PV_REASON&&PV_REASON.seen)pvReasonLeave();   // the reading page left the field's page: moving on
  // A key's armed confirm word belongs to the page it was read on: another reading page lets it go.
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==r)disarmVerdict(false,true);
  if(r!==PV_READ||k!==PV_KEYS){const was=[PV_READ,PV_KEYS]; PV_READ=r; PV_KEYS=k; const map=pageVerdictPins(),v=pageVerdictsOn();
    const re=/** @type {HTMLElement[]} */([]);
    if(v)new Set([...was,r,k]).forEach(n=>{const e=/** @type {HTMLElement|null} */(n?document.querySelector('#doc .pv[data-page="'+n+'"]'):null); if(e){fillPv(e,n,map.get(n),v); re.push(e);}});
    if(re.length)pvFit(re);}   // the reading line names its figure: its row is measured again
  lines.forEach(l=>{const pg=/** @type {HTMLElement|null} */(l.previousElementSibling); if(!pg)return; const b=l.getBoundingClientRect();
    const stuck=l.classList.contains('reading')&&b.bottom>lr.top&&b.top<lr.bottom&&b.top<pg.getBoundingClientRect().bottom+4;   // in its own place it stands 8px under the page
    l.classList.toggle('stuck',stuck); pvLean(l,pg,b,stuck,L,lr);});
  pvPopPlace();}
// A phone's floating line holds [판정 취소] back (.pv-lean, components.css): on 390px it put a row of its own on the line that
// already floats over the figure (one verdict 105 -> 131px, with an earlier one 131 -> 191px). The in-place line and the
// card still offer it, with its 44px. Hysteresis keeps the line from flipping at a page's end: shown, it leans once the
// line floats; leaning, it is shown again only when the line with it (its full height, measured when it was last shown)
// fits in its place under the page - showing it never makes the line float again. Desktop and every other band: never.
const PV_FULL_H=/** @type {WeakMap<HTMLElement,{h:number,gap:number}>} */(new WeakMap());
/** @param {HTMLElement} l @param {HTMLElement} pg @param {DOMRect} b @param {boolean} stuck @param {HTMLElement} L @param {DOMRect} lr */
function pvLean(l,pg,b,stuck,L,lr){
  if(!document.body.classList.contains('band-phone')||!l.classList.contains('reading')||!l.querySelector('.pv-cancel')){l.classList.remove('pv-lean'); return;}
  const m=PV_FULL_H.get(l)||{h:0,gap:8},pb=pg.getBoundingClientRect().bottom; PV_FULL_H.set(l,m);
  if(!stuck)m.gap=Math.max(0,b.top-pb);
  if(!l.classList.contains('pv-lean')){m.h=b.height; if(stuck)l.classList.add('pv-lean'); return;}
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
function pvReadingAt(){if(!pageVerdictsOn()||document.body.classList.contains('revision-open')||!$('#left').getClientRects().length)return 0;
  const a=topAnchor(readingDepth($('#left'))); return a?a.page:0;}
// The reading page when it has a line (pageTakesVerdict), else 0: its line floats and names its figure (PV_READ).
function pvReadingPage(){const n=pvReadingAt(); return n&&pageTakesVerdict(n)?n:0;}
// The page the keys 1-5 act on: reading page r while this screen may make a verdict, no selection is being written and no
// text field has the focus (its digits are text).
/** @param {number} r */
function pvKeysPage(r){const rs=PV_REASON,f=document.activeElement;
  // In an empty reason field the digits are the verdict keys of its line (verdict-reason.js): its line carries them.
  if(rs&&pvIsReasonField(f)&&f.dataset.id==='s'+rs.sid&&!f.value.trim()&&canVerdict()&&$('#composer').hidden)return rs.page;
  return r&&canVerdict()&&$('#composer').hidden&&!typingNow()?r:0;}
let PV_READ=0;   // the reading page with a line: its line floats and names its figure
let PV_FRAME=0;
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
  const v=pageVerdictsOn(),n=+e.key,c=v&&v.choices[n-1],at=pvReadingAt(); if(!c||!at||!canVerdict())return;
  if(!pageTakesVerdict(at)){e.preventDefault(); lineNote('이 쪽은 판정을 받지 않습니다',NOTICE_KIND.INFO,null,{source:'verdict-key',life:NOTICE_LIFE.TIMER}); return;}
  if(VD_ARM&&VD_ARM.kbd&&VD_ARM.where===VD_WHERE.PAGE&&VD_ARM.page!==at)disarmVerdict(true,true);
  const b=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+at+'"] button[data-act="pv-save"][data-key="'+CSS.escape(c.key)+'"]'));
  if(!b)return; e.preventDefault(); verdictPress(b,'key');}
addEventListener('keydown',verdictKey);
