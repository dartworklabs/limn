import { REQUEST_KIND, DOC_KIND, LAYOUT_MODE, LAYOUT_BAND } from './rules-tables.ts';
('use strict');
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
function isFigureKind(kind: string | undefined) {
  return kind === DOC_KIND.FIGURE;
}
// Whether a document of this `kind` is rebuilt from its source: only a LaTeX one. A view-only PDF and a figure redraw
// when their files change, so they have no rebuild and word a finished build as a redraw.
function buildsFromSource(kind: string) {
  return kind === DOC_KIND.TEX;
}
// Whether a document of this `kind` is drawn by the browser from its source (the server's renders_in_browser,
// limn.runtime.documents.Doc.renders_in_browser): a Markdown one and a text one (ADR-0029). It has no pages - #doc
// holds its column (markdown/view.ts) - and its line pins carry no page.
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
  PINS: Pin[] = [],
  DONE: Pin[] = [],
  DROPPED: Pin[] = [],
  REPICK: Repick | null = null,
  PICKSEQ = 0;
// PAGE_SCALE: the scale of the document on screen, CSS px per PDF point (pdf/view-pages.ts §page sizes); 0 until its
// first pages are built.
let SNIP_OPEN = false,
  PAGE_SCALE = 0;
// Mobile: BAND is a LAYOUT_BAND (layoutFor of BAND_IN, the settled {w,h,coarse} - settleBand) and LAYOUT its
// LAYOUT_MODE (wide|mid|narrow, BAND_MODE), SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch
// selection mode, ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to
// the screen width).
const COARSE_POINTER_QUERY = matchMedia('(pointer:coarse)');
let OUTLINE_MID_OPEN = false,
  MID_OVERLAY = false;
let LAYOUT: string | null = null,
  BAND: string | null = null,
  BAND_IN: { w: number; h: number; coarse: boolean } | null = null,
  SIDE_OPEN = true,
  SELMODE = false,
  ZOOMED = false;
const OPEN_CARDS = new Set<number | null>(); // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY
// = the open reply/reopen input field {id,mode,el} (holds onto the DOM like EDITOR.current does, and re-inserts it in
// place when the list redraws), THREAD_OPEN = cards with the thread fully expanded, REPLY_DRAFT = a closed input
// field's text and selected recipient hints ('reply:12').
let KIND_NEW = REQUEST_KIND.FIX as string,
  REPLY: ReplyBox | null = null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (people recorded on a real change or added as members +
// pin authors/actors), PEOPLE_KNOWN = that list has arrived (until then no tag resolves, which says nothing about the
// note), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE: PersonSeen[] = [],
  PEOPLE_KNOWN = false,
  MENTION_ONLY = false;
const THREAD_OPEN = new Set<number>();
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
let DOCS: DocEntry[] = [],
  DOC: string | null = null,
  DEFAULT_DOC = 'main',
  OPEN_ALL: Pin[] = [],
  DONE_ALL: Pin[] = [],
  SHOW_ALL = false,
  SWITCHSEQ = 0;
// NAVGEN = the history traversals so far (the browser's back or forward, not the back layer's own entry): a document
// switch still waiting when one happens opens nothing (switchDoc, documents/flow-switch.ts).
let NAVGEN = 0;
/** One visit of a document: the document and the visit's number (captureVisit). */
interface Visit {
  doc: string | null;
  seq: number;
}
// A continuation may paint visit-local UI only while both the document and its visit number still match.
function captureVisit() {
  return { doc: DOC, seq: SWITCHSEQ };
}
// Match a captured visit after an await, including leave-and-return to the same document.
function currentVisit(visit: Visit) {
  return DOC === visit.doc && SWITCHSEQ === visit.seq;
}
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], pinState(p)===PIN_STATE.REVIEW). Never put
// into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL: Pin[] = [];
const META_BY = new Map(),
  VIEW_BY = new Map(),
  BUILD_ERR_BY = new Map<string | null, BuildStatus>(),
  DOC_SEQ = new Map<string | null, number>();
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
interface ComposeState {
  current: ComposerSelection | null;
  box: HTMLElement | null;
  picking: boolean;
  pendingSave: boolean;
  saving: boolean;
  dismissedOverlap: string | null;
  intent: number;
  retryVerdict: { key: string; sel: ComposerSelection; gen: number } | null;
}
// The active selection owns its PDF box, in-flight pick/save, and overlap choice for one composer visit. intent: a
// counter every change to what the composer asks bumps (setComposeIntent) - a new, cleared or restored selection (pick,
// cancelSelection, restoreSelection, restoreDraft), its rung or lines (the 'level' press, applyRange), the kind
// (setKind) and the [제안 수정] switch (suggestAct). retryVerdict: the verdict a failed save carried, the selection it
// was bound to and the intent it was pressed with; the failure's [다시 저장] saves it again only while that intent is
// unchanged (savePin).
const COMPOSE: ComposeState = {
  current: null,
  box: null,
  picking: false,
  pendingSave: false,
  saving: false,
  dismissedOverlap: null,
  intent: 0,
  retryVerdict: null,
};
interface EditorState {
  current: EditCard | null;
  saving: boolean;
}
// The active edit card and its save request share a lifetime; a dirty card may remain visible across document switches.
const EDITOR: EditorState = { current: null, saving: false };
// Each sets one field of COMPOSE or EDITOR, which this module declares, for another module that changes it (ADR-0042
// D1): the assignment the caller wrote, nothing more.
function setComposeCurrent(value: typeof COMPOSE.current) {
  COMPOSE.current = value;
}
function setComposeBox(value: typeof COMPOSE.box) {
  COMPOSE.box = value;
}
function setComposePicking(value: boolean) {
  COMPOSE.picking = value;
}
function setComposePendingSave(value: boolean) {
  COMPOSE.pendingSave = value;
}
function setComposeSaving(value: boolean) {
  COMPOSE.saving = value;
}
function setComposeDismissedOverlap(value: typeof COMPOSE.dismissedOverlap) {
  COMPOSE.dismissedOverlap = value;
}
function setComposeIntent(value: number) {
  COMPOSE.intent = value;
}
function setComposeRetryVerdict(value: typeof COMPOSE.retryVerdict) {
  COMPOSE.retryVerdict = value;
}
// Sets the overlapping pins of selection (the composer's current one, COMPOSE.current).
function setSelectionOverlaps(selection: ComposerSelection, overlaps: ComposerSelection['overlaps']) {
  selection.overlaps = overlaps;
}
function setEditorCurrent(value: typeof EDITOR.current) {
  EDITOR.current = value;
}
function setEditorSaving(value: boolean) {
  EDITOR.saving = value;
}
// Sets the assignee and the requested kind of card (the open edit card, EDITOR.current).
function setEditAssignee(card: EditCard, assignee: EditCard['assignee']) {
  card.assignee = assignee;
}
function setEditRequestKind(card: EditCard, kind: EditCard['kind_req']) {
  card.kind_req = kind;
}
// The largest pin number the lists hold: a verdict whose answer was lost is looked for above it (findLandedVerdict).
function topPinId() {
  return OPEN_ALL.concat(REVIEW_ALL, DONE_ALL).reduce((highest, pin) => Math.max(highest, pin.id), 0);
}

export type { Visit };
export {
  setComposeCurrent,
  setComposeBox,
  setComposePicking,
  setComposePendingSave,
  setComposeSaving,
  setComposeDismissedOverlap,
  setComposeIntent,
  setComposeRetryVerdict,
  setSelectionOverlaps,
  setEditorCurrent,
  setEditorSaving,
  setEditAssignee,
  setEditRequestKind,
  BAND,
  BAND_IN,
  BAND_MODE,
  BUILD_ERR_BY,
  DEFAULT_DOC,
  DOC,
  DOCS,
  DOC_SEQ,
  DONE,
  DONE_ALL,
  DROPPED,
  IME_ON_FREE,
  IS_MAC,
  PAGE_SCALE,
  KIND_NEW,
  LAYOUT,
  MENTION_ONLY,
  META,
  META_BY,
  MID_OVERLAY,
  COARSE_POINTER_QUERY,
  REDUCED_MOTION_QUERY,
  NAVGEN,
  OPEN_ALL,
  OPEN_CARDS,
  OUTLINE_MID_OPEN,
  PEOPLE,
  PEOPLE_KNOWN,
  PICKSEQ,
  PINS,
  REPICK,
  REPLY,
  REPLY_DRAFT,
  REPLY_VISITS,
  REVIEW_ALL,
  SELMODE,
  SHOW_ALL,
  SIDE_OPEN,
  SNIP_OPEN,
  SWITCHSEQ,
  THREAD_OPEN,
  VIEW_BY,
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
  COMPOSE,
  EDITOR,
  topPinId,
};
