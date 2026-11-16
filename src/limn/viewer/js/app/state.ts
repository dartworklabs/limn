'use strict';
const IS_MAC = /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || '');
// Reduced motion (live, not only at load): read where it acts and never kept, so a setting changed with the page open
// applies to the next slide or scroll. The panel's slides are skipped, but thresholds and previews stay (§패널 폭과
// 시트 높이).
const REDUCED_MOTION_QUERY = matchMedia('(prefers-reduced-motion: reduce)');
// How a scripted scroll moves - a jump of the pages, a heading, a card, a change group: smoothly, or at once ('auto':
// nothing sets a smooth scroll-behavior, and responsive.css holds it auto) while reduced motion is asked for. Asked at
// each scroll, never read once at load: a setting turned on later must stop every jump gliding, and one turned off must
// let them glide again.
function scrollMotion(): ScrollBehavior {
  return REDUCED_MOTION_QUERY.matches ? 'auto' : 'smooth';
}
// Closed sets (docs/handbook/viewer.md §닫힌 값 표): every value the viewer compares a state, status or mode against is
// a member of one frozen table here, never a string literal at the comparison. The first group comes from the server
// and must equal its strings exactly (src/limn/viewer/tests/test_viewer_source.py compares each table with the server's
// Literal or producer); the second is the viewer's own. Free text (messages, reasons, DOM and key names) is not tabled.
// a pin's `state` (pins.model.StateName); read it with pinState()
const PIN_STATE = Object.freeze({ OPEN: 'open', REVIEW: 'review', DONE: 'done' });
// GET /api/build `state`, meta `last_state`
const BUILD_STATE = Object.freeze({ IDLE: 'idle', RUNNING: 'running', OK: 'ok', OK_ERRORS: 'ok_errors', FAIL: 'fail' });
// a build's `pull.state` (pull.pull_record)
const PULL_STATE = Object.freeze({ OK: 'ok', UP_TO_DATE: 'up_to_date', SKIPPED: 'skipped', ERROR: 'error' });
const SYNC_STATE = Object.freeze({
  DISABLED: 'disabled',
  CHECKING: 'checking',
  DEFERRED: 'deferred',
  UPDATING: 'updating',
  UPDATED: 'updated',
  CURRENT: 'current',
  BLOCKED: 'blocked',
  ERROR: 'error',
}); // meta `sync.state`
// a comparison PDF's status `state`
const REVISION_STATE = Object.freeze({ IDLE: 'idle', RUNNING: 'running', READY: 'ready', ERROR: 'error' });
// a pin's change scope `mode` / a comparison's `scope` (scope.ScopeMode)
const SCOPE_MODE = Object.freeze({ PIN: 'pin', COMMIT: 'commit' });
// where a pin's change scope came from (scope.ScopeSource)
const SCOPE_SOURCE = Object.freeze({ CHANGES: 'changes', INFERRED: 'inferred', NONE: 'none' });
// a thread record's `ev` (pins.model.ThreadEv)
const THREAD_EVENT = Object.freeze({ CLOSE: 'close', REOPEN: 'reopen', CONFIRM: 'confirm', ASSIGN: 'assign' });
// how two line ranges overlap (pins.position.selection_rel)
const RANGE_REL = Object.freeze({ EQUAL: 'equal', INSIDE: 'inside', CONTAINS: 'contains', PARTIAL: 'partial' });
const REQUEST_KIND = Object.freeze({ FIX: 'fix', QUESTION: 'question' }); // a pin's `kind_req` (pins.model.KindReq)
// a person's `role` (access.ROLES)
const ROLE = Object.freeze({ OWNER: 'owner', EDITOR: 'editor', VIEWER: 'viewer', AGENT: 'agent' });
// how a pick traced its range: a pick's and a pin's `via` (limn.pins.location.mapping.Via)
const VIA = Object.freeze({ SYNCTEX: 'synctex', TEXT: 'text', MAP: 'map' });
// a document's `kind` in /api/docs and /api/meta (limn.runtime.documents.DocKind)
const DOC_KIND = Object.freeze({ TEX: 'tex', PDF: 'pdf', FIGURE: 'figure', MARKDOWN: 'markdown', TEXT: 'text' });
// where a figure pin's element is in the current build: a pin's `el_sync` (limn.builds.figure_map.ElSync)
const ELEMENT_SYNC = Object.freeze({ OK: 'ok', MOVED: 'moved', LOST: 'lost' });
// whether a pin's suggested edit still fits its lines: a pin's `suggest_state` (limn.pins.suggestion.SuggestState)
const SUGGEST_STATE = Object.freeze({ READY: 'ready', CHANGED: 'changed', UNKNOWN: 'unknown' });
// what a save of the composer's note does: a new pin, or the note joins the open pin the selection overlaps
// (assignOutcome)
const SAVE_MODE = Object.freeze({ NEW: 'new', APPEND: 'append' });
const LOCAL_LOGIN = 'local',
  // the identity-less local login (access.LOCAL_LOGIN); the assignee meaning "the agent" (pins.edit.ASSIGNEE_AGENT)
  ASSIGNEE_AGENT = 'agent';
// LAYOUT, the band's mode (BAND_MODE)
const LAYOUT_MODE = Object.freeze({ WIDE: 'wide', MID: 'mid', NARROW: 'narrow' });
const LAYOUT_BAND = Object.freeze({
  PHONE: 'phone',
  TABLET_SHEET: 'tablet-sheet',
  SHORT: 'short',
  MID_OVERLAY: 'mid-overlay',
  MID_SIDE: 'mid-side',
  WIDE: 'wide',
}); // BAND, by window width, height and primary pointer (layoutFor)
// what a new window observation does to the band (settleBand)
const BAND_STEP = Object.freeze({ KEEP: 'keep', WAIT: 'wait', SETTLE: 'settle' });
// a card's status dot (stateDot); also its CSS class
const CARD_DOT = Object.freeze({ OPEN: 'open', CLAIMED: 'claimed', REVIEW: 'review', LOST: 'lost' });
// why a selection or an edit card's range can carry no suggested edit (suggestOff)
const SUGGEST_OFF = Object.freeze({ PDF: 'pdf', FIGURE: 'figure', REGION: 'region', LONG: 'long' });
// the changes view's tab (REVISION_FORMAT); index.html data-format
const DIFF_FORMAT = Object.freeze({ PDF: 'pdf', SOURCE: 'source', OVERLAY: 'overlay', RENDERED: 'rendered' });
// which build a figure's overlay shows: the previous or the current one; index.html data-side
const OVERLAY_SIDE = Object.freeze({ PREV: 'prev', CUR: 'cur' });
// the changes view's quick range: since last seen, from this commit, this commit only; index.html data-range
const RANGE_MODE = Object.freeze({ LAST: 'last', FROM: 'from', ONE: 'one' });
const SEEN_STATE = Object.freeze({
  NONE: 'none',
  PENDING: 'pending',
  OK: 'ok',
  GONE: 'gone',
  OLD: 'old',
  ERROR: 'error',
  // what the server said of this browser's last-seen commit: no record, asking, counted, not in the history, older than
  // the window, could not answer
});
// the manuscript or the changes view; index.html data-mode
const VIEW_MODE = Object.freeze({ MANUSCRIPT: 'manuscript', REVISIONS: 'revisions' });
const NOTIFY_STATE = Object.freeze({
  ON: 'on',
  OFF: 'off',
  BLOCKED: 'blocked',
  UNSUPPORTED: 'unsupported',
  LOCAL: 'local',
}); // browser notifications on this device (notifyState)
const STATUS_KIND = Object.freeze({
  NOTICE: 'notice',
  FAILED: 'failed',
  ERRORS: 'errors',
  OFFLINE: 'offline',
  QUEUED: 'queued',
  OUTDATED: 'outdated',
  BUILDING: 'building',
  RENDERING: 'rendering',
  SYNC_BLOCKED: 'sync-blocked',
  UNCHANGED: 'unchanged',
  STALE: 'stale',
  SYNC: 'sync',
  PNG: 'png',
}); // an item of the status line (statusList)
// where a verdict button is (verdict.ts): the composer's verdict row or a page verdict line
const VERDICT_PLACE = Object.freeze({ COMPOSER: 'composer', PAGE: 'page' });
// what a comment's time says (stampText); a .rt's data-form
const STAMP_FORM = Object.freeze({ BOTH: 'both', SHORT: 'short', EDITED: 'edited' });
const MARKDOWN_LIMIT = Object.freeze({
  BYTES: 'bytes',
  LINES: 'lines',
  NESTING: 'nesting',
  BLOCKS: 'blocks',
  INLINES: 'inlines',
  ELEMENTS: 'elements',
  TIME: 'time',
  LOAD: 'load',
  ERROR: 'error',
  NUL: 'nul',
}); // the limit a Markdown document's drawing hit (md-surface.ts, MARKDOWN_LIMITS): #md's data-limit
// Each band's layout mode (docs/handbook/viewer.md §모바일 레이아웃): the sheet (narrow), the panel between the nav bar
// and the action row (mid) or the desktop (wide). Code that only asks which of the three reads LAYOUT; code that
// differs per band reads BAND.
const BAND_MODE = Object.freeze({
  [LAYOUT_BAND.PHONE]: LAYOUT_MODE.NARROW,
  [LAYOUT_BAND.TABLET_SHEET]: LAYOUT_MODE.NARROW,
  [LAYOUT_BAND.SHORT]: LAYOUT_MODE.MID,
  [LAYOUT_BAND.MID_OVERLAY]: LAYOUT_MODE.MID,
  [LAYOUT_BAND.MID_SIDE]: LAYOUT_MODE.MID,
  [LAYOUT_BAND.WIDE]: LAYOUT_MODE.WIDE,
});
// Whether a document `kind` is a figure document (a figure set drawn by code, with its element map): the one place this
// is asked.
function isFigureKind(kind) {
  return kind === DOC_KIND.FIGURE;
}
// Whether a document of this `kind` is rebuilt from its source: only a LaTeX one. A view-only PDF and a figure redraw
// when their files change, so they have no rebuild and word a finished build as a redraw.
function buildsFromSource(kind) {
  return kind === DOC_KIND.TEX;
}
// Whether a document of this `kind` is drawn by the browser from its source (the server's renders_in_browser,
// limn.runtime.documents.Doc.renders_in_browser): a Markdown one and a text one (ADR-0029). It has no pages - #doc
// holds its column (md-surface.ts) - and its line pins carry no page.
function rendersInBrowser(kind: string | undefined) {
  return kind === DOC_KIND.MARKDOWN || kind === DOC_KIND.TEXT;
}
// Whether a document drawn in the browser is shown line for line, as its source is, rather than parsed and drawn as
// Markdown: a text document (plain text or source code, ADR-0029). The one place this is asked.
function showsSourceLines(kind: string | undefined) {
  return kind === DOC_KIND.TEXT;
}
// Whether a document of this `kind` is view-only - its pins are pages and regions, never lines (the server's view_only,
// limn.runtime.documents.Doc.view_only): only a view-only PDF. Every other kind takes line pins.
function isViewOnlyKind(kind: string | undefined) {
  return kind === DOC_KIND.PDF;
}
// The key that ends an input method's composition is the method's (docs/handbook/viewer.md §조합을 끝내는 키): it only
// ends the composition, also held down. While a syllable composes the browser marks its keys (isComposing, keyCode
// 229). But ibus-hangul on Linux ends the composition first and then hands the very Enter or Esc on as a plain keydown:
// keydown Process (marked composing), compositionend, the committed text, keydown Enter (isComposing false), keyup
// Enter - one press, so both keydowns carry its time. So when a key the input method took in that composition (marked
// composing, in its field) is down
// - not up since - as the composition ends, the first keydown after that compositionend, in the field it ended in, no
//   later
// than IME_TAIL_MS after it, is that key; held, its repeats are that key too, until it comes up (imeTail). A
// composition that no key ended (a click, the focus leaving, text put in at once - Playwright's Firefox types Hangul
// so) has none. Event times are when the OS made the event, so a busy main thread does not stretch them: the handed-on
// keydown is a few ms before the compositionend (Chromium stamps that one when it dispatches it) - 2-4 ms with
// ibus-hangul. The window leaves room for a browser that stamps the two the other way round and for a coarse clock (a
// privacy setting rounds event times to as much as 100 ms), and stays far under the time a person takes to press a key
// on purpose. A key is known by its physical key (code) from its keydown to its keyup. Where the browser names none -
// no code, or 'Unidentified' (Android's on-screen keyboards give key 'Unidentified' or 'Process', keyCode 229 and no
// code), which every such key shares - any keyup ends it, and a repeat is known by its name (Enter, Escape). The input
// method hands its key on at once, and a key that comes up while the page has no focus never reaches the page: so the
// field or the window losing the focus, the page hidden or left, and a new composition forget all of it. A field taken
// out of the document under the focus (drawn anew in its place) is not left: Chromium blurs it as it goes, Firefox does
// not, and the key goes on down where the focus now is (imeTail). While that key is down its field stays (imeHeldIn):
// what waits for a composition to end - the pages built again, the page lines moving - waits for it too and looks again
// when it is let go (IME_ON_FREE), so the key handed on and its repeats land in the field that composed, not in one
// drawn anew as the viewer's. A release the page never gets with the focus kept would hold it for good, so the hold is
// bounded: it lasts IME_HOLD_MS past that key's last keydown (handed on or a repeat), and it ends - the key with it -
// at a keydown the input method does not take that is neither that key handed on nor its repeat (another key: a held
// key repeats no more once another goes down; that key pressed anew: it was up). Text put in ends neither: no text
// tells the input method's commit from other text. ibus-hangul ends the composition with nothing in it and then puts
// the syllable in as text of its own, which Chromium stamps when it dispatches it - after the page's handlers of the
// end, however long they take -, and a method may commit other text than it showed, or in parts, or before the end. A
// key that brings more text ends it as above when the input method does not take it, a new composition forgets it, and
// text with no such key (a paste from a menu, a letter the method puts in at once) leaves the field to the bound. Past
// the bound the key is still the composition's: a keydown marked as its repeat that comes later is not the viewer's and
// holds the field again. Read with imeKey. Registered here, in the first part, so it sees every keydown before any
// handler does. IME_HOLD_MS is longer than the delay before a held key's first repeat that the usual settings give -
// X's default 660 ms, GNOME's 500 ms (its slider goes to 2 s), Windows' at most 1 s - so a held key keeps the field
// through it, and longer than the 2 s within which Chromium marks a key's next keydown as a repeat at all: on Linux it
// gives a first repeat later than that as a new press of the key (repeat false), which nothing tells from one, so that
// press and its repeats are the viewer's, as a key held without an input method. A release that never came costs what
// waits at most this long.
const IME_TAIL_MS = 100,
  IME_HOLD_MS = 2500;
/**
 * The last key the input method took in the open composition (marked composing), not up since: its field, its physical
 * key (imeCode) and its name (imeName); null when there is none.
 */
let IME_PRESSED: { el: EventTarget | null; code: string; name: string } | null = null;
/**
 * The last composition a key ended: its field, its time, that key - its physical key and its name, from the key the
 * input method took and the keydown it handed on ('' where the browser named none) - and the first keydown after it
 * (null until one comes). Ends with that key's keyup, another key, or what forgets it.
 */
let IME_END: { el: EventTarget | null; at: number; code: string; name: string; key: KeyboardEvent | null } | null =
  null;
/**
 * While this timer runs (not 0), IME_END's key holds its field (imeHeldIn): IME_HOLD_MS from that key's last keydown.
 */
let IME_HOLD_TIMER = 0;
/**
 * What looks again once that key lets its field go (imeFree): run after the event, so it reads the state the event
 * left.
 */
const IME_ON_FREE: (() => void)[] = [];
/** A key event's physical key (code); '' when the browser does not name it: no code, or 'Unidentified'. */
function imeCode(event: KeyboardEvent) {
  const code = event.code;
  return code && code !== 'Unidentified' ? code : '';
}
/**
 * A key event's name (key); '' for a key the input method took ('Process') or one the browser does not name
 * ('Unidentified').
 */
function imeName(event: KeyboardEvent) {
  const name = event.key;
  return name && name !== 'Process' && name !== 'Unidentified' ? name : '';
}
/**
 * Whether a keyup may be the pressed key's (IME_PRESSED, IME_END): the same physical key, or any where either has none.
 */
function imeUp(event: KeyboardEvent, pressed: { code: string }) {
  const code = imeCode(event);
  return !pressed.code || !code || code === pressed.code;
}
/**
 * Whether a keydown repeats the pressed key (IME_END) held down: the same physical key, or, where either has none, the
 * same name.
 */
function imeRepeat(event: KeyboardEvent, pressed: { code: string; name: string }) {
  const code = imeCode(event);
  return event.repeat && (pressed.code && code ? code === pressed.code : !!pressed.name && event.key === pressed.name);
}
/** Whether the target is a node taken out of the document. */
function imeGone(target: EventTarget | null) {
  return target instanceof Node && !target.isConnected;
}
// That key came again: it holds its field IME_HOLD_MS more.
function imeHold() {
  clearTimeout(IME_HOLD_TIMER);
  IME_HOLD_TIMER = setTimeout(() => {
    IME_HOLD_TIMER = 0;
    imeFree();
  }, IME_HOLD_MS);
}
function imeFree() {
  setTimeout(() => {
    for (const lookAgain of IME_ON_FREE) lookAgain();
  }, 0);
}
function imeEnd() {
  if (!IME_END) return;
  IME_END = null;
  clearTimeout(IME_HOLD_TIMER);
  IME_HOLD_TIMER = 0;
  imeFree();
}
function imeForget() {
  IME_PRESSED = null;
  imeEnd();
}
addEventListener('compositionstart', imeForget, true);
addEventListener(
  'compositionend',
  (event) => {
    const pressed = IME_PRESSED;
    imeEnd();
    IME_PRESSED = null;
    if (pressed && pressed.el === event.target) {
      IME_END = { el: event.target, at: event.timeStamp, code: pressed.code, name: pressed.name, key: null };
      imeHold();
    }
  },
  true,
);
addEventListener(
  'keyup',
  (event) => {
    if (IME_PRESSED && imeUp(event, IME_PRESSED)) IME_PRESSED = null;
    if (IME_END && imeUp(event, IME_END)) imeEnd();
  },
  true,
);
// The field's blur (focus events pass the window on their way down) and the window's own; a field's is looked at once
// the task that blurred it is done, when a field drawn anew has taken its place.
addEventListener(
  'blur',
  (event) => {
    const target = event.target;
    if (target instanceof Node)
      queueMicrotask(() => {
        if (target.isConnected) imeForget();
      });
    else imeForget();
  },
  true,
);
addEventListener('pagehide', imeForget, true);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) imeForget();
});
// The tail Esc's browser defaults are not the composition's either: it would empty a search field and close a sheet (a
// modal dialog), which the same Esc on a platform that marks it composing does not do. A tail Enter's default stays: in
// a note it is the new line the input method gives with every Linux program. Where Enter is the viewer's own key in a
// text box (the reason field, the @-list) its handler takes the newline away too (imeTail).
addEventListener(
  'keydown',
  (event) => {
    const ended = IME_END;
    if (ended) {
      if (!ended.key) {
        ended.key = event;
        if (imeTail(event)) {
          ended.code = imeCode(event) || ended.code;
          ended.name = event.key;
        }
      }
      if (imeTail(event) || imeRepeat(event, ended))
        imeHold(); // that key, handed on or held
      else if (!event.isComposing && event.keyCode !== 229) imeEnd();
    }
    if (event.key === 'Escape' && imeTail(event)) event.preventDefault();
    if (event.isComposing || event.keyCode === 229)
      IME_PRESSED = { el: event.target, code: imeCode(event), name: imeName(event) };
  },
  true,
);
/** Whether a keydown is the Enter or Esc that ended a composition (above): the first keydown after it, in its window,
 * or a repeat of that key while it is held - in the field the composition ended in, or wherever the focus went once
 * that field was taken out of the document. */
function imeTail(event: KeyboardEvent) {
  const ended = IME_END;
  if (!ended || (event.key !== 'Enter' && event.key !== 'Escape') || (ended.el !== event.target && !imeGone(ended.el)))
    return false;
  return (ended.key === event && event.timeStamp - ended.at <= IME_TAIL_MS) || imeRepeat(event, ended);
}
/** The field a key ended a composition in while that key holds it (IME_END, IME_HOLD_TIMER, above), else null. */
function imeHeldIn(): EventTarget | null {
  return IME_END && IME_HOLD_TIMER ? IME_END.el : null;
}
/** Whether a keydown is the input method's, not the viewer's: a key while it composes, or the key that ended its
 * composition (imeTail). Every key handler that acts on Enter or Esc in or near a text field asks this first. */
function imeKey(event: KeyboardEvent) {
  return event.isComposing || event.keyCode === 229 || imeTail(event);
}
// META is null only until boot() reads /api/meta; nothing reads it before.
let META = null as unknown as Meta,
  PINS = [] as Pin[],
  DONE = [] as Pin[],
  DROPPED = [] as Pin[],
  REPICK = null as Repick | null,
  PICKSEQ = 0;
// PAGE_SCALE: the scale of the document on screen, CSS px per PDF point (pages.ts §page sizes); 0 until its first pages
// are built.
let SNIP_OPEN = false,
  PAGE_SCALE = 0;
// Mobile: BAND is a LAYOUT_BAND (layoutFor of BAND_IN, the settled {w,h,coarse} - settleBand) and LAYOUT its
// LAYOUT_MODE (wide|mid|narrow, BAND_MODE), SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch
// selection mode, ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to
// the screen width).
const COARSE_POINTER_QUERY = matchMedia('(pointer:coarse)');
let OUTLINE_MID_OPEN = false,
  MID_OVERLAY = false;
let LAYOUT = null as string | null,
  BAND = null as string | null,
  BAND_IN = null as { w: number; h: number; coarse: boolean } | null,
  SIDE_OPEN = true,
  SELMODE = false,
  ZOOMED = false,
  LAST_POINTER = 'mouse',
  LAST_TOUCH_AT = 0;
const OPEN_CARDS = new Set(); // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY
// = the open reply/reopen input field {id,mode,el} (holds onto the DOM like EDITOR.current does, and re-inserts it in
// place when the list redraws), THREAD_OPEN = cards with the thread fully expanded, REPLY_DRAFT = a closed input
// field's text and selected recipient hints ('reply:12').
let KIND_NEW = REQUEST_KIND.FIX as string,
  REPLY = null as ReplyBox | null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (people recorded on a real change or added as members +
// pin authors/actors), PEOPLE_KNOWN = that list has arrived (until then no tag resolves, which says nothing about the
// note), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE = [] as PersonSeen[],
  PEOPLE_KNOWN = false,
  MENTION_ONLY = false;
const THREAD_OPEN = new Set();
/** Closed reply drafts keyed by pin; these snapshots stay within the current page. */
const REPLY_DRAFT: Map<string, ReplyDraft> = new Map();
/** Latest reply visit for each pin, including visits closed empty or already sent. */
const REPLY_VISITS: Map<number, number> = new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the
// current document key, DEFAULT_DOC = the first document that a legacy pin with no doc field belongs to. OPEN_ALL =
// open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at
// PINS). META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom,
// BUILD_ERR_BY = per-document last build error, DOC_SEQ = another document's finished-build count (it tells a build
// that finished in the background).
let DOCS = [] as DocEntry[],
  DOC = null as string | null,
  DEFAULT_DOC = 'main',
  OPEN_ALL = [] as Pin[],
  DONE_ALL = [] as Pin[],
  SHOW_ALL = false,
  SWITCHSEQ = 0;
// NAVGEN = the history traversals so far (the browser's back or forward, not the back layer's own entry): a document
// switch still waiting when one happens opens nothing (switchDoc, doc-switch.ts).
let NAVGEN = 0;
// A continuation may paint visit-local UI only while both the document and its visit number still match.
function captureVisit() {
  return { doc: DOC, seq: SWITCHSEQ };
}
// Match a captured visit after an await, including leave-and-return to the same document.
function currentVisit(visit) {
  return DOC === visit.doc && SWITCHSEQ === visit.seq;
}
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], pinState(p)===PIN_STATE.REVIEW). Never put
// into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL = [] as Pin[];
const META_BY = new Map(),
  VIEW_BY = new Map(),
  BUILD_ERR_BY = new Map(),
  DOC_SEQ = new Map();
window.__pinViewerBoot = Date.now(); // a marker for checking reload status from outside

// Sets BAND, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setBand<Value extends typeof BAND>(value: Value): Value {
  BAND = value;
  return value;
}
// Sets BAND_IN, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setBandIn<Value extends typeof BAND_IN>(value: Value): Value {
  BAND_IN = value;
  return value;
}
// Sets DEFAULT_DOC, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDefaultDoc<Value extends typeof DEFAULT_DOC>(value: Value): Value {
  DEFAULT_DOC = value;
  return value;
}
// Sets DOC, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDoc<Value extends typeof DOC>(value: Value): Value {
  DOC = value;
  return value;
}
// Sets DOCS, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDocs<Value extends typeof DOCS>(value: Value): Value {
  DOCS = value;
  return value;
}
// Sets DONE, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDone<Value extends typeof DONE>(value: Value): Value {
  DONE = value;
  return value;
}
// Sets DONE_ALL, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDoneAll<Value extends typeof DONE_ALL>(value: Value): Value {
  DONE_ALL = value;
  return value;
}
// Sets DROPPED, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setDropped<Value extends typeof DROPPED>(value: Value): Value {
  DROPPED = value;
  return value;
}
// Sets PAGE_SCALE, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setPageScale<Value extends typeof PAGE_SCALE>(value: Value): Value {
  PAGE_SCALE = value;
  return value;
}
// Sets KIND_NEW, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setKindNew<Value extends typeof KIND_NEW>(value: Value): Value {
  KIND_NEW = value;
  return value;
}
// Sets LAST_POINTER, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLastPointer<Value extends typeof LAST_POINTER>(value: Value): Value {
  LAST_POINTER = value;
  return value;
}
// Sets LAST_TOUCH_AT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLastTouchAt<Value extends typeof LAST_TOUCH_AT>(value: Value): Value {
  LAST_TOUCH_AT = value;
  return value;
}
// Sets LAYOUT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLayout<Value extends typeof LAYOUT>(value: Value): Value {
  LAYOUT = value;
  return value;
}
// Sets MENTION_ONLY, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setMentionOnly<Value extends typeof MENTION_ONLY>(value: Value): Value {
  MENTION_ONLY = value;
  return value;
}
// Sets META, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setMeta<Value extends typeof META>(value: Value): Value {
  META = value;
  return value;
}
// Sets MID_OVERLAY, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setMidOverlay<Value extends typeof MID_OVERLAY>(value: Value): Value {
  MID_OVERLAY = value;
  return value;
}
// Sets NAVGEN, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setNavgen<Value extends typeof NAVGEN>(value: Value): Value {
  NAVGEN = value;
  return value;
}
// Sets OPEN_ALL, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setOpenAll<Value extends typeof OPEN_ALL>(value: Value): Value {
  OPEN_ALL = value;
  return value;
}
// Sets OUTLINE_MID_OPEN, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setOutlineMidOpen<Value extends typeof OUTLINE_MID_OPEN>(value: Value): Value {
  OUTLINE_MID_OPEN = value;
  return value;
}
// Sets PEOPLE, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setPeople<Value extends typeof PEOPLE>(value: Value): Value {
  PEOPLE = value;
  return value;
}
// Sets PEOPLE_KNOWN, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setPeopleKnown<Value extends typeof PEOPLE_KNOWN>(value: Value): Value {
  PEOPLE_KNOWN = value;
  return value;
}
// Sets PICKSEQ, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setPickseq<Value extends typeof PICKSEQ>(value: Value): Value {
  PICKSEQ = value;
  return value;
}
// Sets PINS, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setPins<Value extends typeof PINS>(value: Value): Value {
  PINS = value;
  return value;
}
// Sets REPICK, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setRepick<Value extends typeof REPICK>(value: Value): Value {
  REPICK = value;
  return value;
}
// Sets REPLY, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setReply<Value extends typeof REPLY>(value: Value): Value {
  REPLY = value;
  return value;
}
// Sets REVIEW_ALL, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setReviewAll<Value extends typeof REVIEW_ALL>(value: Value): Value {
  REVIEW_ALL = value;
  return value;
}
// Sets SELMODE, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSelmodeState<Value extends typeof SELMODE>(value: Value): Value {
  SELMODE = value;
  return value;
}
// Sets SHOW_ALL, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setShowAll<Value extends typeof SHOW_ALL>(value: Value): Value {
  SHOW_ALL = value;
  return value;
}
// Sets SIDE_OPEN, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSideOpen<Value extends typeof SIDE_OPEN>(value: Value): Value {
  SIDE_OPEN = value;
  return value;
}
// Sets SNIP_OPEN, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSnipOpen<Value extends typeof SNIP_OPEN>(value: Value): Value {
  SNIP_OPEN = value;
  return value;
}
// Sets SWITCHSEQ, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSwitchseq<Value extends typeof SWITCHSEQ>(value: Value): Value {
  SWITCHSEQ = value;
  return value;
}
// Sets ZOOMED, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setZoomed<Value extends typeof ZOOMED>(value: Value): Value {
  ZOOMED = value;
  return value;
}
export {
  ASSIGNEE_AGENT,
  BAND,
  BAND_IN,
  BAND_MODE,
  BAND_STEP,
  BUILD_ERR_BY,
  BUILD_STATE,
  CARD_DOT,
  DEFAULT_DOC,
  DIFF_FORMAT,
  DOC,
  DOCS,
  DOC_KIND,
  DOC_SEQ,
  DONE,
  DONE_ALL,
  DROPPED,
  ELEMENT_SYNC,
  IME_ON_FREE,
  IS_MAC,
  PAGE_SCALE,
  KIND_NEW,
  REQUEST_KIND,
  LAST_POINTER,
  LAST_TOUCH_AT,
  LAYOUT,
  LAYOUT_BAND,
  LAYOUT_MODE,
  LOCAL_LOGIN,
  MARKDOWN_LIMIT,
  MENTION_ONLY,
  META,
  META_BY,
  MID_OVERLAY,
  COARSE_POINTER_QUERY,
  REDUCED_MOTION_QUERY,
  NAVGEN,
  NOTIFY_STATE,
  OPEN_ALL,
  OPEN_CARDS,
  OUTLINE_MID_OPEN,
  OVERLAY_SIDE,
  PEOPLE,
  PEOPLE_KNOWN,
  PICKSEQ,
  PINS,
  PIN_STATE,
  PULL_STATE,
  RANGE_MODE,
  RANGE_REL,
  REPICK,
  REPLY,
  REPLY_DRAFT,
  REPLY_VISITS,
  REVIEW_ALL,
  REVISION_STATE,
  ROLE,
  SAVE_MODE,
  SCOPE_MODE,
  SCOPE_SOURCE,
  SEEN_STATE,
  SELMODE,
  SHOW_ALL,
  SIDE_OPEN,
  SNIP_OPEN,
  STAMP_FORM,
  STATUS_KIND,
  SUGGEST_OFF,
  SUGGEST_STATE,
  SWITCHSEQ,
  SYNC_STATE,
  THREAD_EVENT,
  THREAD_OPEN,
  VERDICT_PLACE,
  VIA,
  VIEW_BY,
  VIEW_MODE,
  ZOOMED,
  buildsFromSource,
  captureVisit,
  currentVisit,
  imeHeldIn,
  imeKey,
  imeTail,
  isFigureKind,
  isViewOnlyKind,
  rendersInBrowser,
  scrollMotion,
  setBand,
  setBandIn,
  setDefaultDoc,
  setDoc,
  setDocs,
  setDone,
  setDoneAll,
  setDropped,
  setPageScale,
  setKindNew,
  setLastPointer,
  setLastTouchAt,
  setLayout,
  setMentionOnly,
  setMeta,
  setMidOverlay,
  setNavgen,
  setOpenAll,
  setOutlineMidOpen,
  setPeople,
  setPeopleKnown,
  setPickseq,
  setPins,
  setRepick,
  setReply,
  setReviewAll,
  setSelmodeState,
  setShowAll,
  setSideOpen,
  setSnipOpen,
  setSwitchseq,
  setZoomed,
  showsSourceLines,
};
