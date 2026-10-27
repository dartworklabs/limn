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
// What a pin's verdict is about when it is a page's whole target, and on which page it is now: on a figure document a pin
// whose element is its page's figure (el.path == [el.id]) - not one whose element the build lost - on the page its element
// is in this build; on a view-only PDF a region pin over the whole page (each frac value within 1e-6 of [0, 0, 1, 1])
// placed on this PDF (est false). null for any other pin, and always on a LaTeX document. Pure but for pinPlace.
/** @param {Pin} p @param {string|undefined} kind @returns {{page:number,id:string}|null} */
function pageTargetOf(p,kind){
  if(isFigureKind(kind)){const el=p.el; if(!el||!Array.isArray(el.path)||el.path.length!==1||el.path[0]!==el.id||elLost(p))return null;
    return {page:pinPlace(p).page,id:el.id};}
  if(kind!==DOC_KIND.PDF||!isRegion(p)||p.est===true||!isFrac(p.frac))return null;
  const f=p.frac; return f.every((v,i)=>Math.abs(v-WHOLE_PAGE[i])<=1e-6)?{page:p.page,id:'page '+p.page}:null;}
// The verdict pins about each page's whole target, not deleted - open, awaiting review (one whose [확인] waits for its undo
// too: it leaves the review list at once, but it is still the newest verdict, D4) and done - newest (largest number) first,
// by page. A page whose pins name two figures (a re-render moved one away) keeps the figure of its newest pin.
/** @returns {Map<number,Pin[]>} */
function pageVerdictPins(){const kind=META?META.kind:undefined,out=/** @type {Map<number,Pin[]>} */(new Map());
  const here=p=>!DOC||pdoc(p)===DOC;
  const pinned=PINS.concat(REVIEW_ALL.filter(here),DONE),held=[...CONFIRMING_PIN.values()].filter(p=>here(p)&&!pinned.some(x=>x.id===p.id));
  for(const p of pinned.concat(held)){if(!verdictOf(p))continue; const t=pageTargetOf(p,kind); if(!t)continue;
    const list=out.get(t.page)||[]; list.push(p); out.set(t.page,list);}
  out.forEach((list,page)=>{list.sort((a,b)=>b.id-a.id); const t=pageTargetOf(list[0],kind),id=t&&t.id;
    out.set(page,list.filter(p=>{const u=pageTargetOf(p,kind); return !!u&&u.id===id;}));});
  return out;}
// The ids of the pins a page verdict line shows now (drawPageVerdicts): their page-size mark is not drawn and their card's
// [보기] goes to the line (marks, jumpPin).
let PV_SHOWN=/** @type {Set<number>} */(new Set());
// A pin's state on the line: what the dot would say, in the line's words. The pin is the page target's newest verdict.
/** @param {Pin} p */
function pvStateWord(p){const st=pinState(p); if(st===PIN_STATE.REVIEW||CONFIRMING.has(p.id))return tr('검토 대기'); if(st===PIN_STATE.DONE)return tr('처리됨');
  return claimActive(p)?tr('처리 중'):tr('처리 대기');}

// ---------------- Two presses for a confirm word (D9)
// The armed first press: the word, where (VD_WHERE) and - on a page line - the page, with the document, build and (in the
// composer) selection it is bound to; null when nothing is armed.
let VD_ARM=/** @type {{key:string,where:string,page:number,doc:string|null,build:string,sel:string,timer:ReturnType<typeof setTimeout>}|null} */(null);
// What the composer's selection is, for the binding: its page, lines, rung, box and element.
function vdSelKey(){const d=COMPOSE.current; return d?JSON.stringify([d.page,d.lo,d.hi,d.scope,d.frac,d.elSel&&d.elSel.id]):'';}
// Whether the armed press is this word's button.
/** @param {string} key @param {string} where @param {number} page */
function vdArmedHere(key,where,page){const a=VD_ARM; return !!a&&a.key===key&&a.where===where&&(where===VD_WHERE.COMPOSER||a.page===page);}
// Whether an armed press still holds: the same document, build and (in the composer) selection.
function vdArmStill(a){return a.doc===DOC&&!!META&&a.build===META.pages_build&&(a.where!==VD_WHERE.COMPOSER||a.sel===vdSelKey());}
// Arms word key's button: it reads '<낱말> 확정' for VD_ARM_MS and a screen reader hears that the next press saves.
function armVerdict(key,where,page,label){disarmVerdict(false);
  VD_ARM={key,where,page,doc:DOC,build:META?META.pages_build:'',sel:where===VD_WHERE.COMPOSER?vdSelKey():'',timer:setTimeout(()=>disarmVerdict(true),VD_ARM_MS)};
  vdRedraw(where); announce(tl('{word} — 한 번 더 누르면 저장합니다',{word:label}));}
// Lets an armed press go (Esc, another press, a press elsewhere, a new selection, document or build, the time running out).
/** @param {boolean} redraw */
function disarmVerdict(redraw){const a=VD_ARM; if(!a)return; clearTimeout(a.timer); VD_ARM=null; if(redraw)vdRedraw(a.where);}
/** @param {string} where */
function vdRedraw(where){if(where===VD_WHERE.COMPOSER)renderVerdictRow(); else drawPageVerdicts();}
// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else.
window.addEventListener('click',e=>{if(!VD_ARM)return; const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-act="verdict-save"],[data-act="pv-save"]'));
  if(!(b&&vdArmedHere(b.dataset.key||'',vdWhereOf(b),Number(b.dataset.page)||0)))disarmVerdict(true);},true);
window.addEventListener('keydown',e=>{if(e.key!=='Escape'||!VD_ARM)return; e.preventDefault(); e.stopImmediatePropagation(); disarmVerdict(true);},true);
/** @param {HTMLElement} b */
function vdWhereOf(b){return b.dataset.act==='verdict-save'?VD_WHERE.COMPOSER:VD_WHERE.PAGE;}

// One word's button: outline, a confirm word's text in the danger colour, '<낱말> 확정' while armed. Its name says what it
// saves about ('채택 판정으로 저장 — 3쪽'); the word is the manuscript's, so the button is translate="no" and its name is put
// in the screen's language here.
// Its description says what a press does at once: in the composer the selection and note become that verdict's pin, on a page
// line a new verdict pin for the page.
/** @param {VerdictChoice} c @param {string} where @param {number} page @param {string} target @param {boolean} off */
function vdButton(c,where,page,target,off){const armed=vdArmedHere(c.key,where,page);
  const name=armed?tl('{word} 확정 — 한 번 더 누르면 저장합니다',{word:c.label}):tl('{word} 판정으로 저장 — {target}',{word:c.label,target});
  const tip=armed?name:where===VD_WHERE.COMPOSER?tl('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다',{word:c.label}):tr('누르면 이 쪽에 새 판정 핀을 저장합니다');
  return html`<button type="button" class="vd-b hit${c.confirm?' vd-confirm':''}${armed?' armed':''}" translate="no" data-act="${where===VD_WHERE.COMPOSER?'verdict-save':'pv-save'}" \
data-key="${c.key}" data-page="${page}" aria-label="${name}" data-tip="${tip}"${off?html` disabled`:''}><span class="lbl">${armed?tl('{word} 확정',{word:c.label}):c.label}</span></button>`;}
// Gives the focus back to the button it was on after a redraw (an armed press redraws its buttons).
/** @param {HTMLElement|null} f */
function vdRefocus(f){if(!f||document.contains(f)||!f.dataset||!f.dataset.act)return;
  const sel=f.dataset.ref?'#doc .pv [data-act="'+f.dataset.act+'"][data-ref="'+CSS.escape(f.dataset.ref)+'"]'   // a line's '#N' link or its earlier link
    :'[data-act="'+f.dataset.act+'"][data-key="'+CSS.escape(f.dataset.key||'')+'"][data-page="'+(f.dataset.page||'0')+'"]';
  const b=/** @type {HTMLElement|null} */(document.querySelector(sel));
  if(b)b.focus({preventScroll:true});}
// A press on a verdict button: a confirm word arms on the first press and saves on the second while what it is bound to
// holds; any other word saves at once - the composer's through savePin, a page line's through savePageVerdict.
/** @param {HTMLElement} b */
function verdictPress(b){const key=b.dataset.key||'',where=vdWhereOf(b),page=Number(b.dataset.page)||0,v=docVerdicts(),c=v&&v.choices.find(x=>x.key===key);
  if(!c||viewerBlocked())return;
  if(c.confirm&&!(vdArmedHere(key,where,page)&&VD_ARM&&vdArmStill(VD_ARM))){const f=/** @type {HTMLElement|null} */(document.activeElement);
    armVerdict(key,where,page,c.label); vdRefocus(f&&f.closest&&f.closest('.vd-btns')?f:null); return;}
  disarmVerdict(false);
  if(where!==VD_WHERE.COMPOSER){savePageVerdict(page,key); return;}
  renderVerdictRow(); if(COMPOSE.current)savePin(key);}   // while the pick runs the row is off (composer.css): nothing is queued

// ---------------- The composer's verdict row
// What the selection is, for a button's name: its page's region, else its file and lines.
/** @param {Selection} d */
function selTarget(d){return isRegion(d)?tl('{page}쪽 영역',{page:d.page}):d.name+' '+rng(d.lo,d.hi);}
// The composer's verdict row (#c-verdict-row, after the note and its lines, before the kind row): '판정 바로 저장' and one
// button per word in file order. Shown for a document with words to a person who may make a verdict pin; its buttons are
// off, with the reason under them, while the kind is a question or [제안 수정] is on (a verdict pin is a fix request with
// no suggestion) and while the selection is still being found.
function renderVerdictRow(){const row=$('#c-verdict-row'),v=docVerdicts(),d=COMPOSE.current;
  const show=!!v&&canVerdict()&&!$('#composer').hidden; row.hidden=!show;
  if(VD_ARM&&VD_ARM.where===VD_WHERE.COMPOSER&&(!show||!vdArmStill(VD_ARM)))disarmVerdict(false);
  if(!v||!show)return;
  const why=KIND_NEW===KIND_REQ.QUESTION?tr('질문에는 판정을 붙이지 않습니다 — 아래에서 [수정 요청]을 고릅니다')
    :SG.on?tr('판정을 저장하려면 [제안 수정]을 끕니다'):'';
  const f=/** @type {HTMLElement|null} */(document.activeElement),inRow=!!f&&row.contains(f);
  setHtml(row,html`<span id="c-verdict-l" class="vd-l">${tr('판정 바로 저장')}</span><span class="vd-btns">${v.choices.map(c=>vdButton(c,VD_WHERE.COMPOSER,0,d?selTarget(d):'',!!why||!d||COMPOSE.saving))}</span>\
${why?html`<span class="vd-why" id="c-verdict-why">${why}</span>`:''}`);
  if(why)row.setAttribute('aria-describedby','c-verdict-why'); else row.removeAttribute('aria-describedby');
  if(inRow)vdRefocus(f);}
// The undo of a verdict pin's save (D10): the pin goes again - a withdrawn request - and the composer does not come back. When
// an agent claimed or closed it meanwhile it still goes, and the status line says its run may have started.
/** @param {number} id @returns {()=>Promise<boolean>} */
function verdictUndo(id){const undo=async()=>{let was=null;
    try{was=(await api('/api/pins/'+id,{what:'핀 읽기',silent:true})).data.pin;}catch(e){}
    const ok=await dropPin(id,true,undo);
    if(ok&&was&&(claimActive(was)||pinState(was)!==PIN_STATE.OPEN))lineNote('처리 중이던 판정입니다 — 이미 실행됐을 수 있습니다',NOTICE_KIND.WARN);
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
// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build on screen, the body
// pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's selection and draft stay as
// they are. Every press makes a new pin (the same word twice is two pins - the agent runs one, D4 and D5). Saved: '#42 저장됨
// [되돌리기]' on the line for NOTICE_MS; a refusal is said on the status line.
/** @param {number} page @param {string} key */
async function savePageVerdict(page,key){const pg=META&&META.pages[page-1]; if(!pg||PV_BUSY.has(page))return;
  const visit=captureVisit(),kind=META.kind,f=/** @type {HTMLElement|null} */(document.activeElement);
  let back=!!f&&!!f.closest&&!!f.closest('#doc .pv')&&f.dataset.act==='pv-save'&&f.dataset.key===key;   // a keyboard press: the focus comes back
  // ...unless it moved meanwhile to anything but that button (another page's word, a '#N' link, the panel): a redraw that puts
  // it back on the same word's button is no move.
  const moved=e=>{const t=/** @type {HTMLElement} */(e.target); if(!(t&&t.dataset&&t.dataset.act==='pv-save'&&t.dataset.key===key&&t.dataset.page===String(page)))back=false;};
  document.addEventListener('focusin',moved);
  PV_BUSY.add(page); drawPageVerdicts();
  try{const d=(await api('/api/pick',{method:'POST',body:{page,x0:0,y0:0,x1:pg.pt_w,y1:pg.pt_h,frac:WHOLE_PAGE.slice(),pdf_build:META.pages_build||undefined,doc:DOC||undefined},
      what:'판정 저장',where:NOTICE_HOST.LINE})).data;
    if(!currentVisit(visit))return;
    if(d.error){lineNote(tl('{what} 실패',{what:tr('판정 저장')})+' — '+errText(d),NOTICE_KIND.ERR,null,{source:'page-verdict'}); if(d.pdf_build_gone)refreshDoc().catch(()=>{}); return;}
    const body=pageVerdictBody(d,kind);
    if(!body){lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다',NOTICE_KIND.WARN,null,{source:'page-verdict'}); return;}
    Object.assign(body,{note:'',doc:DOC||undefined,kind_req:KIND_REQ.FIX,assignee:ASSIGNEE_AGENT,verdict:key});
    const id=(await api('/api/pin',{method:'POST',body,what:'판정 저장',where:NOTICE_HOST.LINE})).data.id;
    if(SEC_SEEN.open)SEC_SEEN.open.add(id);   // my own new pin is never 'new' on a collapsed header
    const chip=undoNote(NOTICE_PLACE.CHIP,tl('#{id} 저장됨 · {word} 판정',{id,word:verdictLabel(key)}),{label:'되돌리기',wait:true,fn:verdictUndo(id)},
      {pin:id,pending:true,label:tl('#{id} 저장됨',{id})});
    await loadPins(); settleChip(chip);
  }catch(e){} finally{document.removeEventListener('focusin',moved); PV_BUSY.delete(page); drawPageVerdicts(); if(back)pvRefocus(page,key);}}
// Gives the focus back to word key's button on page `page`'s line after its save: the pressed button was disabled and redrawn
// while the request ran, which dropped the focus. Not when the person put the focus somewhere else meanwhile (savePageVerdict
// watches for that) or it is on something now.
/** @param {number} page @param {string} key */
function pvRefocus(page,key){const a=document.activeElement; if(a&&a!==document.body&&document.contains(a))return;
  const b=/** @type {HTMLButtonElement|null} */(document.querySelector('#doc .pv[data-page="'+page+'"] [data-act="pv-save"][data-key="'+CSS.escape(key)+'"]'));
  if(b&&!b.disabled)b.focus({preventScroll:true});}
// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and word,
// and who made it and when if that was someone else - the earlier open verdicts as a link ('앞선 판정 N건(처리하지 않음)'),
// and, for a person who may make one, a button per word. No pressed look: a verdict is a request until it is handled.
/** @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v */
function pvLineHtml(page,list,v){const cur=list&&list[0],earlier=list?list.slice(1).filter(p=>pinState(p)===PIN_STATE.OPEN):[];
  const k=cur&&verdictOf(cur),other=!!cur&&!!cur.author&&!isMe(cur.author);
  // One order for every state: '판정 #4 채택 · 처리 대기', then who made it and when if someone else did. The number is a link to
  // the card (the viewer's link style), the word is bold.
  const text=cur&&k?html`<span class="pv-s">${tr('판정')} <span class="pin-ref pv-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="${cur.id}" \
data-tip="${tl('핀 #{id} 로 갑니다',{id:cur.id})}">#${cur.id}</span> <b class="vd-w" translate="no">${verdictLabel(k)}</b></span>\
<span class="pv-sep" aria-hidden="true">·</span><span class="pv-st">${pvStateWord(cur)}</span>\
${other?html`<span class="pv-sep" aria-hidden="true">·</span><span class="pv-au" translate="no">${who(cur.author)}</span> ${relSpan(cur.at,'pv-at','')}`:''}`
    :html`<span class="pv-s pv-none">${tr('판정 없음')}</span>`;
  const early=earlier.length?html`<button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" \
data-tip="${tr('이 쪽의 더 새 판정이 앞서므로 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다')}">${tl('이전 판정 {n}건 · 새 판정이 앞섬',{n:earlier.length})}</button>`:'';
  const busy=PV_BUSY.has(page),btns=canVerdict()?html`<span class="vd-btns">${v.choices.map(c=>vdButton(c,VD_WHERE.PAGE,page,tl('{page}쪽',{page}),busy))}</span>`:'';
  return html`<span class="pv-t">${text}${early}</span>${btns}`;}
// Draws page `page`'s line.
/** @param {HTMLElement} el @param {number} page @param {Pin[]|undefined} list @param {DocVerdicts} v */
function fillPv(el,page,list,v){el.dataset.page=String(page); const cur=list&&list[0];
  if(cur){el.dataset.pin=String(cur.id); PV_SHOWN.add(cur.id);} else delete el.dataset.pin;
  el.setAttribute('role','group'); el.setAttribute('aria-label',tl('{page}쪽 판정',{page}));
  const chip=el.querySelector(':scope>.nt-chip');   // a save's undo chip (drawChips) stays on its line; drawChips moves it if it is another pin's
  setHtml(el,pvLineHtml(page,list,v)); if(chip)el.appendChild(chip);}
// The width of each line: the page's (W), never past what the PDF area shows - a zoomed page scrolls sideways under a
// line that stays in view (sticky) and keeps its size. Then one rhythm for every page: when any page's line cannot hold its
// words and its buttons on one row (a phone, a folded cover), every line puts its buttons on a row of their own, at its
// start (#doc.pv-stack) - a short line beside a long one no longer keeps them at the end of its row. Measured only while the
// pages are laid out (the changes view hides them).
function sizePv(){const w=Math.round(Math.min(W,innerW()))+'px',doc=$('#doc'),lines=$$('#doc .pv'); lines.forEach(e=>{e.style.width=w;});
  if(!lines.length||!lines[0].getClientRects().length){if(!lines.length)doc.classList.remove('pv-stack'); return;}
  doc.classList.remove('pv-stack');
  const wraps=lines.some(l=>{const t=l.querySelector('.pv-t'),b=l.querySelector('.vd-btns'); return !!t&&!!b&&b.getBoundingClientRect().top>=t.getBoundingClientRect().bottom-1;});
  doc.classList.toggle('pv-stack',wraps);}
// Draws the page verdict line under every page after the pages, the pin lists or the build change. Without page verdicts
// every line goes and the marks draw every pin as before.
function drawPageVerdicts(){const v=pageVerdictsOn(),f=/** @type {HTMLElement|null} */(document.activeElement);
  const had=!!f&&!!f.closest&&!!f.closest('.pv');
  if(VD_ARM&&VD_ARM.where===VD_WHERE.PAGE&&(!v||!vdArmStill(VD_ARM)))disarmVerdict(false);
  PV_SHOWN=new Set();
  if(!v||!META){$$('#doc .pv').forEach(e=>e.remove()); return;}
  const map=pageVerdictPins();
  $$('#doc .pg').forEach(pg=>{const page=+pg.dataset.page; let line=/** @type {HTMLElement|null} */(pg.nextElementSibling);
    if(!line||!line.classList.contains('pv')){line=document.createElement('div'); line.className='pv'; pg.after(line);}
    fillPv(line,page,map.get(page),v);});
  sizePv();
  if(had)vdRefocus(f);}
// Whether pin p's page verdict line shows it, so its page-size mark is not drawn (marks).
/** @param {Pin} p */
function pvShows(p){return PV_SHOWN.has(p.id);}
// A card's [보기] for a pin a line shows: the line comes into view and flashes. Returns whether it did.
/** @param {number} id */
function jumpPv(id){if(!PV_SHOWN.has(id))return false; const p=PINS.find(x=>x.id===id)||REVIEW_ALL.find(x=>x.id===id)||DONE.find(x=>x.id===id);
  const t=p&&pageTargetOf(p,META?META.kind:undefined); if(!t)return false;
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);
  const flash=el=>{el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); clearTimeout(el._flT); el._flT=setTimeout(()=>el.classList.remove('flash'),1200);};
  const line=/** @type {HTMLElement|null} */(document.querySelector('#doc .pv[data-page="'+t.page+'"]')); if(!line)return false;
  line.scrollIntoView({behavior:SMOOTH,block:'center'}); flash(line); return true;}
