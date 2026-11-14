// ------------------------------------------------ The queued pins on screen (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기)
// offline.js reads the queue (offlineSync) on boot, after every pin kept, dropped or sent, and calls offlineUiSync(all)
// with every record each time. This part draws them: where they stand on the page and in the pin panel. A queued pin is
// not on the server yet, so it is drawn apart from a saved pin's mark: a dotted frame with no number (it has none yet),
// its badge a clock - or, held back because its place could not be found again, a warning triangle in the warning colour.
// The panel's section lists every record with its place, words, note and state, and two actions: [버리기] (its undo on
// the status line, since the row is gone) and [다시 찍기] (the record leaves the queue and its note waits in the composer
// for the next drag, the draft's own behaviour, draft.js). Nothing here writes to the server.
/** A record just dropped ([버리기]) or taken back ([다시 찍기], redo: its note text went to the composer), standing as its undo
 * row until its window ends: NOTICE_MS from `from` (its start, again when a mouse leaves it), held while a mouse is on the row
 * (hover), never past NOTICE_HOLD_MAX beyond its first window (`at`).
 * @typedef {{rec:any,redo:boolean,text:string,at:number,from:number,t:ReturnType<typeof setTimeout>|undefined,busy:boolean,hover:boolean}} OffUiUndo */
const OFFUI={all:/** @type {any[]} */([]),open:true,undos:/** @type {Map<number,OffUiUndo>} */(new Map()),
  flashT:/** @type {ReturnType<typeof setTimeout>|0} */(0)};

// Whether frac is a box on the page: four finite numbers, the box inside the page with some size. A record from another
// version of this viewer, or one written by hand, must not draw a frame off the page. Pure.
/** @param {unknown} f @returns {boolean} */
function offUiFrac(f){if(!Array.isArray(f)||f.length<4)return false;
  if(!f.slice(0,4).every(v=>typeof v==='number'&&Number.isFinite(v)))return false;
  return f[0]>=0&&f[1]>=0&&f[2]>0&&f[3]>0&&f[0]+f[2]<=1+1e-6&&f[1]+f[3]<=1+1e-6;}
// The rows the panel lists and the marks the page draws, from every queued record (oldest first): this document's records
// first, then the others', each in the order they were written - the order they are sent. A row says what it is: `here` (on
// the document on screen), `lines` (a Markdown or text document's line pin, which has no page), `mark` (drawn on the page:
// here, on the build on screen - its box is that build's - and on a page this document has), `old` (here, drawn on another
// build: listed, not drawn). doc is the document on screen, defaultDoc the one a record with no document belongs to, build
// the build on screen, nPages its page count. Pure.
/** @param {any[]} all @param {string} doc @param {string} defaultDoc @param {string} build @param {number} nPages */
function offUiRows(all,doc,defaultDoc,build,nPages){const rows=(Array.isArray(all)?all:[]).filter(r=>r&&typeof r==='object').map(rec=>{
    const here=(rec.doc||defaultDoc)===(doc||defaultDoc),lines=rec.page==null&&!!rec.lines&&typeof rec.lines==='object';
    const page=Number.isInteger(rec.page)&&rec.page>=1?rec.page:null,onDoc=page!==null&&page<=nPages;
    const mark=here&&!lines&&onDoc&&!!build&&rec.build===build&&offUiFrac(rec.frac);
    return {rec,here,lines,page,mark,old:here&&!lines&&!!rec.build&&rec.build!==build,held:!!rec.held};});
  return rows.filter(r=>r.here).concat(rows.filter(r=>!r.here));}
// Why a held record is held: the reason it carries, or - an empty one - the reason a held record always has (offline.js
// writes this one when it has no other). '' for a record that waits. Pure but for tr.
/** @param {any} rec @returns {string} */
function offUiWhy(rec){if(!rec||!rec.held)return ''; const w=String(rec.why||'').trim(); return w||tr('위치를 찾지 못했습니다');}
// Where a record was pinned, as the row and the mark's tip say it: '3쪽', a line pin's 'intro.md 12–14줄' (one line:
// '12줄'), '' when it says neither. Pure but for tl.
/** @param {any} rec @returns {string} */
function offUiPlace(rec){const L=rec&&rec.lines;
  if(rec&&rec.page==null&&L&&typeof L==='object'){const name=String(L.file||'').split('/').pop()||'';
    const lo=Number(L.lo),hi=Number(L.hi); if(!Number.isFinite(lo))return name;
    return (name?name+' ':'')+(Number.isFinite(hi)&&hi!==lo?tl('{lo}–{hi}줄',{lo,hi}):tl('{lo}줄',{lo}));}
  return rec&&Number.isInteger(rec.page)&&rec.page>=1?tl('{page}쪽',{page:rec.page}):'';}
// A one-line excerpt of text: its white space folded, cut at n characters with an ellipsis. Pure.
/** @param {unknown} s @param {number} n @returns {string} */
function offUiClip(s,n){const t=String(s==null?'':s).replace(/\s+/g,' ').trim(); return t.length>n?t.slice(0,n-1)+'…':t;}

/** @param {any[]} all every queued record, oldest first (offline.js offAll) */
function offlineUiSync(all){OFFUI.all=Array.isArray(all)?all:[]; offUiDraw();}
// The view of the queue for the document and build on screen.
function offUiView(){const pages=META&&!isMdDoc()&&Array.isArray(META.pages)?META.pages.length:0;
  return offUiRows(OFFUI.all,DOC||DEFAULT_DOC,DEFAULT_DOC,(META&&META.pages_build)||'',pages);}
function offUiDraw(){const rows=offUiView(); offUiMarks(rows); offUiList(rows);}

// The marks: one dotted frame per queued record drawn on the page on screen, under the saved pins' marks' own layer
// (they are drawn into the same page box, after them). The frame lets every press through to the page, as a saved mark
// does - a drag over it is a new selection; only its badge takes a press, which brings the panel's row into view.
/** @param {ReturnType<typeof offUiRows>} rows */
function offUiMarks(rows){$$('.qmark').forEach(m=>m.remove());
  rows.forEach(r=>{if(!r.mark)return; const pg=document.getElementById('p'+r.page); if(!pg)return; const f=r.rec.frac;
    const m=document.createElement('div'); m.className='qmark'+(r.held?' held':''); m.dataset.qid=String(r.rec.id);
    Object.assign(m.style,{left:f[0]*100+'%',top:f[1]*100+'%',width:f[2]*100+'%',height:f[3]*100+'%'});
    const note=offUiClip(r.rec.note,60)||tr('(메모 없음)'),why=offUiWhy(r.rec);
    const tip=(r.held?tr('보류된 핀')+' · '+why:tr('쌓인 핀 · 연결되면 반영합니다'))+' — '+note;
    // A badge too close to the page's left edge to stand outside the box stands in its corner, as a saved one does.
    const inner=f[0]*pg.clientWidth<28;
    if(inner)m.classList.add('in');
    setHtml(m,html`<button type="button" class="qmark-jump" translate="no" data-qid="${r.rec.id}" aria-label="${r.held?tr('보류된 핀 — 목록에서 보기'):tr('쌓인 핀 — 목록에서 보기')}" data-tip="${tip}">${ic(r.held?'triangle-alert':'clock')}</button>`);
    pg.appendChild(m);});}

// The section in the pin panel (#sec-queue): hidden while the queue is empty, else a head with its count (and how many are
// held), a line saying what these are, and one row per record. Sending them now is the status line's [지금 반영], shown
// whenever there is a connection to send on.
// A record dropped or taken back a moment ago keeps its place in the order as its undo row (offUiUndoRow) while that lasts,
// so the section stays while one stands even with the queue empty.
/** @param {ReturnType<typeof offUiRows>} rows */
function offUiList(rows){const sec=$('#sec-queue'); if(!sec)return;
  const f=offUiFocus(),undos=[...OFFUI.undos.values()]; sec.hidden=!rows.length&&!undos.length;
  if(sec.hidden){$('#queue-rows').replaceChildren(); return;}
  const held=rows.filter(r=>r.held).length;
  setHtml($('#queue-toggle'),html`${ic(OFFUI.open?'chevron-down':'chevron-right')}<span class="sec-name" id="queue-h">${tr('쌓인 핀')} <span class="badge badge-secondary sec-n">${rows.length}</span></span>${held?html`<span class="badge q-held-n">${ic('triangle-alert')}${tl('보류 {n}',{n:held})}</span>`:''}`);
  $('#queue-toggle').setAttribute('aria-expanded',String(OFFUI.open)); $('#queue-body').hidden=!OFFUI.open;
  const here=(/** @type {any} */rec)=>(rec.doc||DEFAULT_DOC)===(DOC||DEFAULT_DOC)?0:1;
  const items=rows.map(r=>({rec:r.rec,h:offUiRow(r)})).concat(undos.map(u=>({rec:u.rec,h:offUiUndoRow(u)})))
    .sort((a,b)=>here(a.rec)-here(b.rec)||(Number(a.rec.id)||0)-(Number(b.rec.id)||0));
  setHtml($('#queue-rows'),html`${items.map(x=>x.h)}`);
  offUiFocusBack(f);}
// One row: its state (a clock and '대기', or a triangle and '보류' with its reason - words, never the colour alone), where
// it was pinned (a link to that page; another document's row names that document and goes there), the words it was drawn
// over, its note, and its two actions. A long note is folded to three lines by CSS; the whole of it stays in the row.
/** @param {ReturnType<typeof offUiRows>[number]} r */
function offUiRow(r){const rec=r.rec,id=rec.id,place=offUiPlace(rec),why=offUiWhy(rec),q=offUiClip(rec.quote,160),note=String(rec.note||'').trim();
  const info=r.here?null:docInfo(rec.doc||DEFAULT_DOC),dname=r.here?'':(info&&info.name)||rec.doc||'';
  const goes=!r.here?!!info:(r.page!==null&&!r.lines&&r.page<=(META&&META.pages?META.pages.length:0));
  const at=html`${dname?html`<span class="q-doc" translate="no">${dname}</span>`:''}${place?html`<span class="q-place">${place}</span>`:''}`;
  const where=goes?html`<button type="button" class="q-go" data-q="go" data-qid="${id}" data-tip="${r.here?tr('이 쪽으로 갑니다'):tr('이 문서로 바꿉니다')}">${at}</button>`
    :dname||place?html`<span class="q-at">${at}</span>`:'';
  const name=(r.held?tr('보류'):tr('대기'))+(place?' · '+place:'')+(dname?' · '+dname:'');
  return html`<div class="qrow${r.held?' held':''}" role="group" aria-label="${tl('쌓인 핀: {what}',{what:name})}" data-qid="${id}">\
<div class="q-head"><span class="q-st">${ic(r.held?'triangle-alert':'clock')}<span>${r.held?tr('보류'):tr('대기')}</span></span>${where}</div>\
${r.held?html`<p class="q-why">${why}</p>`:''}\
${r.old?html`<p class="q-old">${tr('다른 PDF에서 찍어 쪽 위에 그리지 않았습니다')}</p>`:''}\
${q?html`<p class="q-quote" translate="no">${q}</p>`:''}\
<p class="q-note${note?'':' dim'}" translate="no">${note||tr('(메모 없음)')}</p>\
<div class="q-acts"><button type="button" class="btn-sm btn-secondary" data-q="redo" data-qid="${id}" data-tip="${tr('이 핀을 쌓인 목록에서 빼고 메모를 작성 칸에 둡니다. 다음에 끈 자리가 이 메모로 새 핀이 됩니다')}">${tr('다시 찍기')}</button>\
<button type="button" class="btn-sm btn-ghost q-drop" data-q="drop" data-qid="${id}" data-tip="${tr('이 핀을 보내지 않고 버립니다. 그 자리에 남는 [되돌리기]로 되살립니다')}">${tr('버리기')}</button></div></div>`;}
// The undo of a drop or a take-back, in the row's place (docs/handbook/viewer.md §알림 자리, an undo stays where the action
// was): the dashed undo row of the list, its words, [되돌리기] (busy while the record is put back) and [x]. The status line
// is not its place: there the kept pins' own count comes before every message, so the undo stood behind '+N'.
/** @param {OffUiUndo} u */
function offUiUndoRow(u){const id=u.rec.id,place=offUiPlace(u.rec),title=u.redo?tr('메모를 작성 칸에 두었습니다'):tr('쌓인 핀을 버렸습니다');
  const desc=u.redo?tr('자리를 다시 끌어 고르세요'):place;
  return html`<div class="nt nt-row nk-${NOTICE_KIND.OK}" role="group" aria-label="${title}" data-qid="${id}" data-undo="1"><span class="nt-ic">${noticeIcon(NOTICE_KIND.OK)}</span>\
<span class="nt-t" translate="no"><span class="nt-ti">${title}</span>${desc?html`<span class="nt-d">${desc}</span>`:''}</span>\
<span class="nt-acts"><button type="button" class="btn-sm btn-secondary nt-act" data-q="undo" data-qid="${id}" data-tip="${T.undo}"${u.busy?html` aria-busy="true"`:''}><span class="lbl">${tr('되돌리기')}</span></button>\
<button type="button" class="btn-icon btn-sm btn-ghost nt-x" data-q="undo-x" data-qid="${id}" aria-label="${tr('알림 닫기')}">${ic('x')}</button></span></div>`;}

// The keyboard focus on one of the section's buttons, as its action and record, so a redraw gives it back (a redraw comes
// whenever the queue is read, which another tab or a send may cause at any time).
/** @returns {{q:string,id:string}|null} */
function offUiFocus(){const a=/** @type {HTMLElement|null} */(document.activeElement);
  return a&&a.closest&&a.closest('#sec-queue')&&a.dataset.q?{q:a.dataset.q,id:a.dataset.qid||''}:null;}
/** @param {{q:string,id:string}|null} f */
function offUiFocusBack(f){if(!f)return; const a=document.activeElement; if(a&&a!==document.body&&document.contains(a))return;
  const b=/** @type {HTMLElement|null} */($('#sec-queue').querySelector('[data-q="'+f.q+'"]'+(f.id?'[data-qid="'+f.id+'"]':''))); if(b)b.focus({preventScroll:true});}

/** @param {number} id @returns {any} */
function offUiRec(id){return OFFUI.all.find(r=>r&&r.id===id)||null;}
// Shows the row of record id in the panel: opens the panel and the section, scrolls the row into view and flashes it.
/** @param {number} id */
function offUiReveal(id){setSide(true); if(!OFFUI.open){OFFUI.open=true; offUiDraw();}
  requestAnimationFrame(()=>{const row=/** @type {HTMLElement|null} */(document.querySelector('.qrow[data-qid="'+id+'"]')); if(!row)return;
    row.scrollIntoView({behavior:scrollMotion(),block:'nearest'});
    row.classList.remove('flash'); void row.offsetWidth; row.classList.add('flash');
    clearTimeout(OFFUI.flashT); OFFUI.flashT=setTimeout(()=>row.classList.remove('flash'),1200);});}
// A row's place: this document's page (and its mark, flashed), or another document, switched to.
/** @param {any} rec */
function offUiGo(rec){const k=rec.doc||DEFAULT_DOC;
  if(k!==(DOC||DEFAULT_DOC)){void switchDoc(k); return;}
  if(LAYOUT===LAYOUT_MODE.NARROW)setSide(false);   // the sheet folds first so the page is not under it
  marksShow(); arrivePage(rec.page);
  const m=/** @type {HTMLElement|null} */(document.querySelector('.qmark[data-qid="'+rec.id+'"]'));
  if(m){m.classList.remove('flash'); void m.offsetWidth; m.classList.add('flash');}}
// [버리기]: the record goes now and is never sent. Its undo row stands in its place (offUiUndoRow) and puts the record back
// as it was - its key is its id, so it takes its place in the order again.
/** @param {any} rec @param {HTMLElement} btn */
async function offUiDrop(rec,btn){if(offUiBusy())return; const had=document.activeElement===btn;
  await offDel(rec.id); offUiUndoStart(rec,false,''); await offlineSync();
  announce(tr('쌓인 핀을 버렸습니다')); if(had)offUiFocusUndo(rec.id);}
// [다시 찍기]: the record leaves the queue and its note, @-tags, kind and assignee go into the composer, where they wait for
// the next drag (or join the selection already open). A note already being written is not overwritten: the person saves
// or discards it first. Another document's record switches to that document first - its draft is that document's.
// A record that may already be a pin on the server (sent, no answer) is not taken back.
/** @param {any} rec @param {HTMLElement} btn */
async function offUiRedo(rec,btn){if(offUiBusy())return; const k=rec.doc||DEFAULT_DOC,had=document.activeElement===btn;
  // A record whose write was attempted and never answered may be a pin on the server already: taken back and drawn
  // again it would be made twice. The next send asks the server by its key and either ends the record or takes the
  // mark off (offline.js offlineFlush), so this is refused only until then.
  if(rec.sent){lineNote('보낸 적이 있어 서버에 이미 있을 수 있습니다 — 연결된 뒤 [지금 반영]으로 확인하세요',NOTICE_KIND.WARN,null,{life:NOTICE_LIFE.CLICK}); return;}
  if(k!==(DOC||DEFAULT_DOC)){if(!docInfo(k))return; await switchDoc(k); if((DOC||DEFAULT_DOC)!==k)return;}
  const n=/** @type {HTMLTextAreaElement} */($('#note')),text=String(rec.note||'');
  if(n.value.trim()&&n.value.trim()!==text.trim()){
    lineNote('작성 중인 메모가 있습니다 — 저장하거나 버린 뒤 다시 찍으세요',NOTICE_KIND.WARN,null,{life:NOTICE_LIFE.CLICK}); return;}
  await offDel(rec.id);
  n.value=text; n._mentions=(rec.mentions||[]).length?new Set(rec.mentions):null;
  setKind(rec.kind_req===KIND_REQ.QUESTION?KIND_REQ.QUESTION:KIND_REQ.FIX);
  if(rec.assignee){ASSIGN_NEW.v=rec.assignee; ASSIGN_NEW.touched=true;}
  renderAssignNew(); autoGrow(n); saveDraftSoon();
  offUiUndoStart(rec,true,text); await offlineSync();
  announce(tr('메모를 작성 칸에 두었습니다')+' · '+tr('자리를 다시 끌어 고르세요'));
  if(!$('#composer').hidden)n.focus({preventScroll:true}); else if(had)offUiFocusUndo(rec.id);
  if(LAYOUT===LAYOUT_MODE.WIDE&&Number.isInteger(rec.page)&&!isMdDoc())arrivePage(rec.page);}   // the page it was on, beside the panel
// While the queue is being sent a record may be on its way: it is neither dropped nor taken back until that is over.
function offUiBusy(){if(!OFF.flushing)return false;
  lineNote('쌓인 핀을 반영하는 중입니다 — 끝난 뒤 다시 누르세요',NOTICE_KIND.INFO,null,{life:NOTICE_LIFE.TIMER}); return true;}

// ---------------- The undo rows' windows
/** @param {any} rec @param {boolean} redo @param {string} text */
function offUiUndoStart(rec,redo,text){const old=OFFUI.undos.get(rec.id); if(old)clearTimeout(old.t);
  const now=Date.now(),u=/** @type {OffUiUndo} */({rec,redo,text,at:now,from:now,t:undefined,busy:false,hover:false}); OFFUI.undos.set(rec.id,u); offUiArm(u);}
// The row's window: NOTICE_MS, or - while a mouse is on it - until it leaves, but never past NOTICE_HOLD_MAX beyond the
// first window (notices.js armNotice, the same rule for every undo). Stopped while its record is being put back.
/** @param {OffUiUndo} u */
function offUiArm(u){clearTimeout(u.t); u.t=undefined; if(u.busy)return;
  const now=Date.now(),left=u.at+NOTICE_MS+NOTICE_HOLD_MAX-now;
  u.t=setTimeout(()=>offUiUndoEnd(u.rec.id),Math.max(0,u.hover?left:Math.min(u.from+NOTICE_MS-now,left)));}
// The window is over (or [x]): the row goes. A focus on it goes to the row now in its place's neighbourhood, else the head.
/** @param {number} id */
function offUiUndoEnd(id){const u=OFFUI.undos.get(id); if(!u)return; clearTimeout(u.t); OFFUI.undos.delete(id);
  const a=document.activeElement,row=a&&a.closest?a.closest('#queue-rows>[data-undo]'):null,inIt=!!row&&row.getAttribute('data-qid')===String(id);
  const sib=inIt&&row?/** @type {HTMLElement|null} */(row.nextElementSibling||row.previousElementSibling):null;
  offUiDraw();
  if(inIt){const b=/** @type {HTMLElement|null} */((sib&&sib.isConnected&&sib.querySelector('button'))||(!$('#sec-queue').hidden&&$('#queue-toggle'))||null);
    if(b)b.focus({preventScroll:true});}}
// [되돌리기]: the record goes back into the queue as it was. A take-back's note leaves the composer with it - unless it is no
// longer the same note there (written on, or already saved with a drag): then the record would make a second pin, so it is
// not put back and the line says why.
/** @param {number} id */
async function offUiUndo(id){const u=OFFUI.undos.get(id); if(!u||u.busy)return;
  const n=/** @type {HTMLTextAreaElement} */($('#note')),inIt=!!document.activeElement&&!!document.activeElement.closest&&!!document.activeElement.closest('#queue-rows>[data-undo]');
  // The composer's note is the document on screen's draft: on another document it is that document's, and clearing it
  // (and saving the draft) would take a note this record never put there. The take-back is undone only where it was made.
  if(u.redo&&(DOC||DEFAULT_DOC)!==(u.rec.doc||DEFAULT_DOC)){offUiUndoEnd(id);
    lineNote('다른 문서로 옮겨 되돌리지 않았습니다 — 그 문서에서 메모를 지우세요',NOTICE_KIND.INFO,null,{life:NOTICE_LIFE.TIMER}); return;}
  if(u.redo&&n.value!==u.text){offUiUndoEnd(id); lineNote('메모가 이미 바뀌어 되돌리지 않았습니다',NOTICE_KIND.INFO,null,{life:NOTICE_LIFE.TIMER}); return;}
  u.busy=true; clearTimeout(u.t); offUiDraw();
  const ok=(await offPut(u.rec))!==null;
  if(ok&&u.redo){n.value=''; n._mentions=null; autoGrow(n); saveDraftSoon();}
  clearTimeout(u.t); OFFUI.undos.delete(id); await offlineSync();
  if(!ok){lineNote('되돌리지 못했습니다 — 이 브라우저가 오프라인 보관을 막고 있습니다',NOTICE_KIND.ERR,null,{}); return;}
  if(inIt){const b=/** @type {HTMLElement|null} */($('#sec-queue').querySelector('.qrow[data-qid="'+id+'"] [data-q="'+(u.redo?'redo':'drop')+'"]')); if(b)b.focus({preventScroll:true});}}
/** @param {number} id */
function offUiFocusUndo(id){const b=/** @type {HTMLElement|null} */($('#sec-queue').querySelector('[data-undo][data-qid="'+id+'"] [data-q="undo"]')); if(b)b.focus({preventScroll:true});}

$('#sec-queue').addEventListener('click',e=>{const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('button')); if(!b)return;
  if(b.id==='queue-toggle'){OFFUI.open=!OFFUI.open; offUiDraw(); return;}
  const id=Number(b.dataset.qid),q=b.dataset.q;
  if(q==='undo'){void offUiUndo(id); return;} if(q==='undo-x'){offUiUndoEnd(id); return;}
  const rec=offUiRec(id); if(!rec)return;
  if(q==='go')offUiGo(rec); else if(q==='drop')void offUiDrop(rec,b); else if(q==='redo')void offUiRedo(rec,b);});
// A mouse on an undo row holds its window; leaving it starts the window again (the status line's undos do the same).
$('#queue-rows').addEventListener('pointermove',e=>{if(e.pointerType!=='mouse')return; const r=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-undo]'));
  const u=r?OFFUI.undos.get(Number(r.dataset.qid)):undefined; if(u&&!u.hover){u.hover=true; offUiArm(u);}},{passive:true});
$('#queue-rows').addEventListener('pointerout',e=>{const r=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('[data-undo]')); if(!r)return;
  const to=/** @type {Node|null} */(e.relatedTarget); if(to&&r.contains(to))return;
  const u=OFFUI.undos.get(Number(r.dataset.qid)); if(u&&u.hover){u.hover=false; u.from=Date.now(); offUiArm(u);}});
// A mark's badge takes its press away from the page: a press on it never starts a selection, a long press or a tap's
// selection there (selection.js reads presses on #doc, and the frame itself lets them through). Its click shows the row.
$('#doc').addEventListener('pointerdown',e=>{if(/** @type {HTMLElement} */(e.target).closest('.qmark-jump'))e.stopPropagation();},true);
$('#doc').addEventListener('mousedown',e=>{if(/** @type {HTMLElement} */(e.target).closest('.qmark-jump')){e.stopPropagation(); e.preventDefault();}},true);
$('#doc').addEventListener('click',e=>{const b=/** @type {HTMLElement|null} */(/** @type {HTMLElement} */(e.target).closest('.qmark-jump')); if(!b)return;
  offUiReveal(Number(b.dataset.qid));});
// The pages are drawn again (a new build, a zoom that rebuilds them, another document): the marks go with the old pages,
// and which records this document and build draw has changed - both are drawn again.
new MutationObserver(()=>offUiDraw()).observe($('#doc'),{childList:true});
