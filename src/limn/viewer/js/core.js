
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
// Lucide icons (vendor/lucide/README.md), drawn by ic() in markup.js.
const ICONS=__LUCIDE_JSON__;
const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IS_MAC=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
// Reduced motion (live, not only at load): read where it acts and never kept, so a setting changed with the page open
// applies to the next slide or scroll. The panel's slides are skipped, but thresholds and previews stay (§패널 폭과 시트 높이).
const MQ_REDUCED=matchMedia('(prefers-reduced-motion: reduce)');
// How a scripted scroll moves - a jump of the pages, a heading, a card, a change group: smoothly, or at once ('auto': nothing
// sets a smooth scroll-behavior, and responsive.css holds it auto) while reduced motion is asked for. Asked at each scroll:
// read once at load (a const), a setting turned on later left every jump gliding and one turned off left them instant (#418).
/** @returns {ScrollBehavior} */
function scrollMotion(){return MQ_REDUCED.matches?'auto':'smooth';}
const MQ=matchMedia('(prefers-color-scheme: light)');
// Closed sets (docs/handbook/viewer.md §닫힌 값 표): every value the viewer compares a state, status or mode against is a
// member of one frozen table here, never a string literal at the comparison. The first group comes from the server and
// must equal its strings exactly (tests/viewer/test_viewer_source.py compares each table with the server's Literal or producer);
// the second is the viewer's own. Free text (messages, reasons, DOM and key names) is not tabled.
const PIN_STATE=Object.freeze({OPEN:'open',REVIEW:'review',DONE:'done'});   // a pin's `state` (pins.model.StateName); read it with pinState()
const BUILD_STATE=Object.freeze({IDLE:'idle',RUNNING:'running',OK:'ok',OK_ERRORS:'ok_errors',FAIL:'fail'});   // GET /api/build `state`, meta `last_state`
const PULL_STATE=Object.freeze({OK:'ok',UP_TO_DATE:'up_to_date',SKIPPED:'skipped',ERROR:'error'});   // a build's `pull.state` (pull.pull_record)
const SYNC_STATE=Object.freeze({DISABLED:'disabled',CHECKING:'checking',DEFERRED:'deferred',UPDATING:'updating',UPDATED:'updated',CURRENT:'current',BLOCKED:'blocked',ERROR:'error'});   // meta `sync.state`
const REVISION_STATE=Object.freeze({IDLE:'idle',RUNNING:'running',READY:'ready',ERROR:'error'});   // a comparison PDF's status `state`
const SCOPE_MODE=Object.freeze({PIN:'pin',COMMIT:'commit'});   // a pin's change scope `mode` / a comparison's `scope` (scope.ScopeMode)
const SCOPE_SOURCE=Object.freeze({CHANGES:'changes',INFERRED:'inferred',NONE:'none'});   // where a pin's change scope came from (scope.ScopeSource)
const THREAD_EV=Object.freeze({CLOSE:'close',REOPEN:'reopen',CONFIRM:'confirm',ASSIGN:'assign'});   // a thread record's `ev` (pins.model.ThreadEv)
const RANGE_REL=Object.freeze({EQUAL:'equal',INSIDE:'inside',CONTAINS:'contains',PARTIAL:'partial'});   // how two line ranges overlap (pins.position.selection_rel)
const KIND_REQ=Object.freeze({FIX:'fix',QUESTION:'question'});   // a pin's `kind_req` (pins.model.KindReq)
const ROLE=Object.freeze({OWNER:'owner',EDITOR:'editor',VIEWER:'viewer',AGENT:'agent'});   // a person's `role` (access.ROLES)
const EVENT_TYPE=Object.freeze({MENTION:'mention',REVIEW_REQUESTED:'review_requested',REPLIED:'replied',REOPENED:'reopened',ASSIGNED:'assigned',DROPPED:'dropped'});   // an event's `type` (events.EventType)
const VIA=Object.freeze({SYNCTEX:'synctex',TEXT:'text',MAP:'map'});   // how a pick traced its range: a pick's and a pin's `via` (limn.pins.location.mapping.Via)
const DOC_KIND=Object.freeze({TEX:'tex',PDF:'pdf',FIGURE:'figure',MARKDOWN:'markdown',TEXT:'text'});   // a document's `kind` in /api/docs and /api/meta (limn.runtime.documents.DocKind)
const EL_SYNC=Object.freeze({OK:'ok',MOVED:'moved',LOST:'lost'});   // where a figure pin's element is in the current build: a pin's `el_sync` (limn.builds.figure_map.ElSync)
const SUGGEST_STATE=Object.freeze({READY:'ready',CHANGED:'changed',UNKNOWN:'unknown'});   // whether a pin's suggested edit still fits its lines: a pin's `suggest_state` (limn.pins.suggestion.SuggestState)
const SAVE_MODE=Object.freeze({NEW:'new',APPEND:'append'});   // what a save of the composer's note does: a new pin, or the note joins the open pin the selection overlaps (assignOutcome)
const LOCAL_LOGIN='local',ASSIGNEE_AGENT='agent';   // the identity-less local login (access.LOCAL_LOGIN); the assignee meaning "the agent" (pins.edit.ASSIGNEE_AGENT)
const LAYOUT_MODE=Object.freeze({WIDE:'wide',MID:'mid',NARROW:'narrow'});   // LAYOUT, the band's mode (BAND_MODE)
const LAYOUT_BAND=Object.freeze({PHONE:'phone',TABLET_SHEET:'tablet-sheet',SHORT:'short',MID_OVERLAY:'mid-overlay',MID_SIDE:'mid-side',WIDE:'wide'});   // BAND, by window width, height and primary pointer (layoutFor)
const BAND_STEP=Object.freeze({KEEP:'keep',WAIT:'wait',SETTLE:'settle'});   // what a new window observation does to the band (settleBand)
const CARD_DOT=Object.freeze({OPEN:'open',CLAIMED:'claimed',REVIEW:'review',LOST:'lost'});   // a card's status dot (stDot); also its CSS class
const SUGGEST_OFF=Object.freeze({PDF:'pdf',FIGURE:'figure',REGION:'region',LONG:'long'});   // why a selection or an edit card's range can carry no suggested edit (suggestOff)
const DIFF_FORMAT=Object.freeze({PDF:'pdf',SOURCE:'source',OVERLAY:'overlay',RENDERED:'rendered'});   // the changes view's tab (REVISION_FORMAT); index.html data-format
const OVERLAY_SIDE=Object.freeze({PREV:'prev',CUR:'cur'});   // which build a figure's overlay shows: the previous or the current one; index.html data-side
const RANGE_MODE=Object.freeze({LAST:'last',FROM:'from',ONE:'one'});   // the changes view's quick range (#188): since last seen, from this commit, this commit only; index.html data-range
const SEEN_STATE=Object.freeze({NONE:'none',PENDING:'pending',OK:'ok',GONE:'gone',OLD:'old',ERROR:'error'});   // what the server said of this browser's last-seen commit (#188): no record, asking, counted, not in the history, older than the window, could not answer
const VIEW_MODE=Object.freeze({MANUSCRIPT:'manuscript',REVISIONS:'revisions'});   // the manuscript or the changes view; index.html data-mode
const UI_LANG=Object.freeze({KO:'ko',EN:'en'});   // LANG
const NOTIFY_STATE=Object.freeze({ON:'on',OFF:'off',BLOCKED:'blocked',UNSUPPORTED:'unsupported',LOCAL:'local'});   // browser notifications on this device (notifyState)
const STATUS_KIND=Object.freeze({NOTICE:'notice',FAILED:'failed',ERRORS:'errors',OFFLINE:'offline',QUEUED:'queued',OUTDATED:'outdated',BUILDING:'building',RENDERING:'rendering',SYNC_BLOCKED:'sync-blocked',UNCHANGED:'unchanged',STALE:'stale',SYNC:'sync',PNG:'png'});   // an item of the status line (statusList)
const NOTICE_KIND=Object.freeze({OK:'ok',WARN:'warn',ERR:'err',INFO:'info'});   // what a message reports (notices.js): its icon, colour and how it is read out
const NOTICE_PLACE=Object.freeze({LINE:'line',BANNER:'banner',CHIP:'chip',ROW:'row',CARD:'card',TRASH:'trash'});   // where a message is drawn (notices.js)
const NOTICE_HOST=Object.freeze({COMPOSER:'composer',LIST:'list',REVIEW:'review',TRASH:'trash',LINE:'line'});   // a banner's panel or section; LINE puts an api() error on the status line
const NOTICE_LIFE=Object.freeze({STICKY:'sticky',CLICK:'click',TIMER:'timer'});   // how long a message stays (armNotice)
const NOTICE_DOT=Object.freeze({SIDE:'side',RV:'rv'});   // the chip a background message marks, [핀 N] or [검토 M]; also the body class dot-<value>
const NOTICE_TOPIC=Object.freeze({PICK:'pick',SIDE:'side',OFFLINE:'offline'});   // what a first-visit hint asks for (endTopic): a selection, the panel opened, a pin kept while cut off
const VD_WHERE=Object.freeze({COMPOSER:'composer',PAGE:'page'});   // where a verdict button is (verdict.js): the composer's verdict row or a page verdict line
const LIST_ORDER=Object.freeze({NEW:'new',PAGE:'page',ID:'id'});   // the pin list's order (orderPins); index.html data-order
const STAMP_FORM=Object.freeze({BOTH:'both',SHORT:'short',EDITED:'edited'});   // what a comment's time says (stampText); a .rt's data-form
const MD_LIMIT=Object.freeze({BYTES:'bytes',LINES:'lines',NESTING:'nesting',BLOCKS:'blocks',INLINES:'inlines',ELEMENTS:'elements',TIME:'time',LOAD:'load',ERROR:'error',NUL:'nul'});   // the limit a Markdown document's drawing hit (md-surface.js, MD_LIMITS): #md's data-limit
// Each band's layout mode (docs/handbook/viewer.md §모바일 레이아웃): the sheet (narrow), the panel between the nav bar and the
// action row (mid) or the desktop (wide). Code that only asks which of the three reads LAYOUT; code that differs per band reads BAND.
const BAND_MODE=Object.freeze({[LAYOUT_BAND.PHONE]:LAYOUT_MODE.NARROW,[LAYOUT_BAND.TABLET_SHEET]:LAYOUT_MODE.NARROW,[LAYOUT_BAND.SHORT]:LAYOUT_MODE.MID,[LAYOUT_BAND.MID_OVERLAY]:LAYOUT_MODE.MID,[LAYOUT_BAND.MID_SIDE]:LAYOUT_MODE.MID,[LAYOUT_BAND.WIDE]:LAYOUT_MODE.WIDE});
// Whether a document `kind` is a figure document (a figure set drawn by code, with its element map): the one place this is asked.
function isFigureKind(kind){return kind===DOC_KIND.FIGURE;}
// Whether a document of this `kind` is rebuilt from its source: only a LaTeX one. A view-only PDF and a figure redraw when their
// files change, so they have no rebuild and word a finished build as a redraw.
function buildsFromSource(kind){return kind===DOC_KIND.TEX;}
// Whether a document of this `kind` is drawn by the browser from its source (the server's renders_in_browser,
// limn.runtime.documents.Doc.renders_in_browser): a Markdown one and a text one (ADR-0029). It has no pages - #doc holds its
// column (md-surface.js) - and its line pins carry no page.
/** @param {string|undefined} kind */
function rendersInBrowser(kind){return kind===DOC_KIND.MARKDOWN||kind===DOC_KIND.TEXT;}
// Whether a document drawn in the browser is shown line for line, as its source is, rather than parsed and drawn as Markdown: a
// text document (plain text or source code, ADR-0029). The one place this is asked.
/** @param {string|undefined} kind */
function showsSourceLines(kind){return kind===DOC_KIND.TEXT;}
// Whether a document of this `kind` is view-only - its pins are pages and regions, never lines (the server's view_only,
// limn.runtime.documents.Doc.view_only): only a view-only PDF. Every other kind takes line pins.
/** @param {string|undefined} kind */
function isViewOnlyKind(kind){return kind===DOC_KIND.PDF;}
// The key that ends an input method's composition is the method's (docs/handbook/viewer.md §조합을 끝내는 키): it only ends the
// composition, also held down. While a syllable composes the browser marks its keys (isComposing, keyCode 229). But
// ibus-hangul on Linux ends the composition first and then hands the very Enter or Esc on as a plain keydown: keydown Process
// (marked composing), compositionend, the committed text, keydown Enter (isComposing false), keyup Enter - one press, so both
// keydowns carry its time. So when a key the input method took in that composition (marked composing, in its field) is down
// - not up since - as the composition ends, the first keydown after that compositionend, in the field it ended in, no later
// than IME_TAIL_MS after it, is that key; held, its repeats are that key too, until it comes up (imeTail). A composition that
// no key ended (a click, the focus leaving, text put in at once - Playwright's Firefox types Hangul so) has none. Event times
// are when the OS made the event, so a busy main thread does not stretch them: the handed-on keydown is a few ms before the
// compositionend (Chromium stamps that one when it dispatches it) - 2-4 ms with ibus-hangul. The window leaves room for a
// browser that stamps the two the other way round and for a coarse clock (a privacy setting rounds event times to as much
// as 100 ms), and stays far under the time a person takes to press a key on purpose. A key is known by its physical key
// (code) from its keydown to its keyup. Where the browser names none - no code, or 'Unidentified' (Android's on-screen
// keyboards give key 'Unidentified' or 'Process', keyCode 229 and no code), which every such key shares - any keyup ends
// it, and a repeat is known by its name (Enter, Escape). The input method hands its key on at once, and a key that comes up
// while the page has no focus never reaches the page: so the field or the window losing the focus, the page hidden or left,
// and a new composition forget all of it. A field taken out of the document under the focus (drawn anew in its place) is
// not left: Chromium blurs it as it goes, Firefox does not, and the key goes on down where the focus now is (imeTail).
// While that key is down its field stays (imeHeldIn): what waits for a composition to end - the pages built again, the
// page lines moving - waits for it too and looks again when it is let go (IME_ON_FREE), so the key handed on and its
// repeats land in the field that composed, not in one drawn anew as the viewer's. A release the page never gets with the
// focus kept would hold it for good, so the hold is bounded: it lasts IME_HOLD_MS past that key's last keydown (handed on
// or a repeat), and it ends - the key with it - at a keydown the input method does not take that is neither that key
// handed on nor its repeat (another key: a held key repeats no more once another goes down; that key pressed anew: it was
// up). Text put in ends neither: no text tells the input method's commit from other text. ibus-hangul ends the
// composition with nothing in it and then puts the syllable in as text of its own, which Chromium stamps when it
// dispatches it - after the page's handlers of the end, however long they take -, and a method may commit other text than
// it showed, or in parts, or before the end. A key that brings more text ends it as above when the input method does not
// take it, a new composition forgets it, and text with no such key (a paste from a menu, a letter the method puts in at
// once) leaves the field to the bound. Past the bound the key is still the composition's: a keydown marked as its repeat
// that comes later is not the viewer's and holds the field again. Read with imeKey. Registered here, in the first part, so
// it sees every keydown before any handler does.
// IME_HOLD_MS is longer than the delay before a held key's first repeat that the usual settings give - X's default
// 660 ms, GNOME's 500 ms (its slider goes to 2 s), Windows' at most 1 s - so a held key keeps the field through it, and
// longer than the 2 s within which Chromium marks a key's next keydown as a repeat at all: on Linux it gives a first
// repeat later than that as a new press of the key (repeat false), which nothing tells from one, so that press and its
// repeats are the viewer's, as a key held without an input method. A release that never came costs what waits at most
// this long.
const IME_TAIL_MS=100,IME_HOLD_MS=2500;
/** The last key the input method took in the open composition (marked composing), not up since: its field, its physical key (imeCode) and its name (imeName); null when there is none. @type {{el:EventTarget|null,code:string,name:string}|null} */
let IME_PRESSED=null;
/** The last composition a key ended: its field, its time, that key - its physical key and its name, from the key the input method took and the keydown it handed on ('' where the browser named none) - and the first keydown after it (null until one comes). Ends with that key's keyup, another key, or what forgets it. @type {{el:EventTarget|null,at:number,code:string,name:string,key:KeyboardEvent|null}|null} */
let IME_END=null;
/** While this timer runs (not 0), IME_END's key holds its field (imeHeldIn): IME_HOLD_MS from that key's last keydown. */
let IME_HOLD_T=0;
/** What looks again once that key lets its field go (imeFree): run after the event, so it reads the state the event left. @type {(()=>void)[]} */
const IME_ON_FREE=[];
/** Key event e's physical key (code); '' when the browser does not name it: no code, or 'Unidentified'. @param {KeyboardEvent} e */
function imeCode(e){const c=e.code; return c&&c!=='Unidentified'?c:'';}
/** Key event e's name (key); '' for a key the input method took ('Process') or one the browser does not name ('Unidentified'). @param {KeyboardEvent} e */
function imeName(e){const k=e.key; return k&&k!=='Process'&&k!=='Unidentified'?k:'';}
/** Whether keyup e may be key k's (IME_PRESSED, IME_END): the same physical key, or any where either has none. @param {KeyboardEvent} e @param {{code:string}} k */
function imeUp(e,k){const c=imeCode(e); return !k.code||!c||c===k.code;}
/** Whether keydown e repeats key k (IME_END) held down: the same physical key, or, where either has none, the same name. @param {KeyboardEvent} e @param {{code:string,name:string}} k */
function imeRepeat(e,k){const c=imeCode(e); return e.repeat&&(k.code&&c?c===k.code:!!k.name&&e.key===k.name);}
/** Whether el is a node taken out of the document. @param {EventTarget|null} el */
function imeGone(el){return el instanceof Node&&!el.isConnected;}
// That key came again: it holds its field IME_HOLD_MS more.
function imeHold(){clearTimeout(IME_HOLD_T); IME_HOLD_T=setTimeout(()=>{IME_HOLD_T=0; imeFree();},IME_HOLD_MS);}
function imeFree(){setTimeout(()=>{for(const f of IME_ON_FREE)f();},0);}
function imeEnd(){if(!IME_END)return; IME_END=null; clearTimeout(IME_HOLD_T); IME_HOLD_T=0; imeFree();}
function imeForget(){IME_PRESSED=null; imeEnd();}
addEventListener('compositionstart',imeForget,true);
addEventListener('compositionend',e=>{const p=IME_PRESSED; imeEnd(); IME_PRESSED=null;
  if(p&&p.el===e.target){IME_END={el:e.target,at:e.timeStamp,code:p.code,name:p.name,key:null}; imeHold();}},true);
addEventListener('keyup',e=>{if(IME_PRESSED&&imeUp(e,IME_PRESSED))IME_PRESSED=null; if(IME_END&&imeUp(e,IME_END))imeEnd();},true);
// The field's blur (focus events pass the window on their way down) and the window's own; a field's is looked at once the
// task that blurred it is done, when a field drawn anew has taken its place.
addEventListener('blur',e=>{const t=e.target; if(t instanceof Node)queueMicrotask(()=>{if(t.isConnected)imeForget();}); else imeForget();},true);
addEventListener('pagehide',imeForget,true);
document.addEventListener('visibilitychange',()=>{if(document.hidden)imeForget();});
// The tail Esc's browser defaults are not the composition's either: it would empty a search field and close a sheet (a
// modal dialog), which the same Esc on a platform that marks it composing does not do. A tail Enter's default stays: in a
// note it is the new line the input method gives with every Linux program. Where Enter is the viewer's own key in a text
// box (the reason field, the @-list) its handler takes the newline away too (imeTail).
addEventListener('keydown',e=>{const r=IME_END;
  if(r){if(!r.key){r.key=e; if(imeTail(e)){r.code=imeCode(e)||r.code; r.name=e.key;}}
    if(imeTail(e)||imeRepeat(e,r))imeHold();   // that key, handed on or held
    else if(!e.isComposing&&e.keyCode!==229)imeEnd();}
  if(e.key==='Escape'&&imeTail(e))e.preventDefault();
  if(e.isComposing||e.keyCode===229)IME_PRESSED={el:e.target,code:imeCode(e),name:imeName(e)};},true);
/** Whether keydown e is the Enter or Esc that ended a composition (above): the first keydown after it, in its window, or a
 * repeat of that key while it is held - in the field the composition ended in, or wherever the focus went once that field
 * was taken out of the document. @param {KeyboardEvent} e */
function imeTail(e){const r=IME_END; if(!r||(e.key!=='Enter'&&e.key!=='Escape')||(r.el!==e.target&&!imeGone(r.el)))return false;
  return (r.key===e&&e.timeStamp-r.at<=IME_TAIL_MS)||imeRepeat(e,r);}
/** The field a key ended a composition in while that key holds it (IME_END, IME_HOLD_T, above), else null. @returns {EventTarget|null} */
function imeHeldIn(){return IME_END&&IME_HOLD_T?IME_END.el:null;}
/** Whether keydown e is the input method's, not the viewer's: a key while it composes, or the key that ended its
 * composition (imeTail). Every key handler that acts on Enter or Esc in or near a text field asks this first. @param {KeyboardEvent} e */
function imeKey(e){return e.isComposing||e.keyCode===229||imeTail(e);}
// META is null only until boot() reads /api/meta; nothing reads it before.
let META=/** @type {Meta} */(/** @type {unknown} */(null)),PINS=/** @type {Pin[]} */([]),DONE=/** @type {Pin[]} */([]),DROPPED=/** @type {Pin[]} */([]),REPICK=/** @type {Repick|null} */(null),PICKSEQ=0;
// K: the scale of the document on screen, CSS px per PDF point (pages.js §page sizes); 0 until its first pages are built.
let SNIP_OPEN=false,K=0;
// Mobile: BAND is a LAYOUT_BAND (layoutFor of BAND_IN, the settled {w,h,coarse} - settleBand) and LAYOUT its LAYOUT_MODE (wide|mid|narrow, BAND_MODE), SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch selection mode,
// ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to the screen width).
const MQ_COARSE=matchMedia('(pointer:coarse)');
// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sent a simulated mouseover and left the description stuck over the list (phone QA). Only long-press is used.
const MQ_NOHOVER=matchMedia('(hover:none)');
let OUTLINE_MID_OPEN=false,MID_OVERLAY=false;
let LAYOUT=/** @type {string|null} */(null),BAND=/** @type {string|null} */(null),BAND_IN=/** @type {{w:number,h:number,coarse:boolean}|null} */(null),SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY = the open reply/reopen
// input field {id,mode,el} (holds onto the DOM like EDITOR.current does, and re-inserts it in place when the list redraws), THREAD_OPEN = cards with the thread fully expanded,
// REPLY_DRAFT = a closed input field's text and selected recipient hints ('reply:12').
let KIND_NEW=/** @type {string} */(KIND_REQ.FIX),REPLY=/** @type {ReplyBox|null} */(null);
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (people recorded on a real change or added as members + pin authors/actors), PEOPLE_KNOWN = that list
// has arrived (until then no tag resolves, which says nothing about the note), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE=/** @type {PersonSeen[]} */([]),PEOPLE_KNOWN=false,MENTION_ONLY=false;
const THREAD_OPEN=new Set();
/** Closed reply drafts keyed by pin; these snapshots stay within the current page. @type {Map<string, ReplyDraft>} */
const REPLY_DRAFT=new Map();
/** Latest reply visit for each pin, including visits closed empty or already sent. @type {Map<number, number>} */
const REPLY_VISITS=new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the current document key, DEFAULT_DOC = the first
// document that a legacy pin with no doc field belongs to. OPEN_ALL = open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at PINS).
// META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom, BUILD_ERR_BY = per-document last build error,
// DOC_SEQ = another document's finished-build count (used to notice a build that finished in the background).
let DOCS=/** @type {DocEntry[]} */([]),DOC=/** @type {string|null} */(null),DEFAULT_DOC='main',OPEN_ALL=/** @type {Pin[]} */([]),DONE_ALL=/** @type {Pin[]} */([]),SHOW_ALL=false,SWITCHSEQ=0;
// NAVGEN = the history traversals so far (the browser's back or forward, not the back layer's own entry): a document switch
// still waiting when one happens opens nothing (switchDoc, doc-switch.js).
let NAVGEN=0;
// A continuation may paint visit-local UI only while both the document and its visit number still match.
function captureVisit(){return {doc:DOC,seq:SWITCHSEQ};}
// Match a captured visit after an await, including leave-and-return to the same document.
function currentVisit(visit){return DOC===visit.doc&&SWITCHSEQ===visit.seq;}
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], pinState(p)===PIN_STATE.REVIEW). Never put into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL=/** @type {Pin[]} */([]);
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // a marker for checking reload status from outside

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  ellost:'그림을 다시 그린 뒤 지도에서 이 요소를 찾지 못했습니다(요소 id가 바뀌었거나 지워짐). 표시는 핀을 찍은 때 자리에 그립니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n:"누르면 문서에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc:'핀이 가리키는 원문 줄. 클릭하면 복사',
  view:'문서에서 이 핀 자리로 가서 깜빡입니다', edit:'메모와 범위를 고칩니다. 번호는 그대로입니다',
  close:"처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop:'핀을 휴지통으로 보냅니다. 카드 자리에 남는 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  dropVerdict:'이 판정 핀을 휴지통으로 보냅니다(판정을 거둡니다). 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 카드 자리에 남는 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  repick:'번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave:'수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)', ecancel:'수정을 버립니다 (Esc)',
  restore:'삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  purge:'휴지통에서 영구 삭제합니다(소유자만). 그 자리에 6초 동안 남는 [되돌리기]로 취소할 수 있고, 그 줄이 사라지면 지웁니다',
  synctex:'PDF 좌표(SyncTeX)로 찾은 위치입니다.',
  text:'드래그한 글자를 원문에서 직접 찾아 정한 위치입니다. 표나 기호표처럼 좌표로 찾기 어려운 곳에 쓰는 방법입니다.',
  map:'그림 지도에서 드래그와 가장 많이 겹치는 요소를 골랐습니다.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  mdraw:'넓히기 전에 끌어 고르거나 누른 줄만 잡습니다',
  block:'고른 자리를 감싸는 블록 전체입니다(문단·목록 항목·표·코드 블록·인용·HTML 블록·머리 정보·수식)',
  blocks:'고른 줄이 걸친 블록들 전체입니다',
  section:'이 제목부터 같거나 높은 수준의 다음 제목 앞까지입니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  txpara:'고른 줄을 감싸는, 빈 줄 사이의 문단 전체입니다',
  txparas:'고른 줄이 걸친 문단들 전체입니다',
  indent:'고른 줄이 머리인 들여쓰기 블록, 아니면 고른 줄을 감싼 들여쓰기 블록입니다(머리 줄부터, 닫는 괄호나 end·fi·done·esac 만 있는 줄까지)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  el:'이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다',
  fig:'그림 전체를 그린 코드 줄입니다',
  elregion:'이 요소를 그린 코드 줄을 찾지 못했습니다 — 쪽·영역과 요소로 핀을 남깁니다',
  figregion:'그림 지도를 읽지 못해 쪽·영역과 영역 글자로 핀을 남깁니다',
  shape:'이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다',
  question:'고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:'에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:'결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:'변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:'이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)',
  nochange:'변경 없음', buildanyway:'그래도 빌드',
  buildanywaytip:'남겨 둔 LaTeX 부산물을 지우고 처음부터 다시 빌드합니다. 빌드가 비교하지 않는 것(셸 탈출로 도는 프로그램이 읽는 파일 등)을 바꿨을 때 씁니다',
  reloadtip:'이 탭을 새로 읽어 서버의 새 Limn 화면을 씁니다. 작성 패널의 글과 읽던 자리는 남고, 쓰던 답글·수정이 있으면 먼저 알립니다'
};
