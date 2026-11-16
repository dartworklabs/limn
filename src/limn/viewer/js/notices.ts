// ------------------------------------------------ Messages in context (docs/handbook/viewer.md §알림 자리)
// The viewer has no toast (#167): every message has a home where it happened.
// - A success is silent unless it can be undone; a silent one is still read out (#sr-news, quietNote). An undo sits where the
//   action was (undoNote): a chip on the new pin's mark, a row in the card's place, a note in the card, a row in the Trash -
//   or the status line when that place is not on screen.
// - An error or a conflict is a banner at the top of the panel or section concerned (bannerNote), with its action - or, when
//   that place is not on screen now, the same on the status line, read out as an alert, with a dot on the chip that leads
//   there (rule 1: an error appears where the person can see it now; errors come first on the line).
// - Background events and first-visit hints go to the status line (lineNote); a background event also puts a red dot on the
//   chip that leads to it ([핀 N], [검토 M]) until the person looks there.
// - An undo lives its full NOTICE_MS window, or until the person dismisses or uses it; other presses never end it (rule 2).
// Every message is a Notice in NOTICES, numbered n; its buttons carry data-act="notice-act"/"notice-x" and data-n.
import {
  $,
  EVENT_TYPE,
  NOTICE_DOT,
  NOTICE_HOST,
  NOTICE_KIND,
  NOTICE_LIFE,
  NOTICE_PLACE,
  NOTICE_TOPIC,
  REPLY,
  REVIEW_ALL,
  SIDE_OPEN,
  T,
} from './core.ts';
import { html, ic, setHtml } from './markup.ts';
import { tr, trMsg } from './i18n.ts';
import { SEC } from './prefs.ts';
import { tipFollow } from './tooltip.ts';
import { STATUS_TOP, drawStatus, setStatusSig, toggleStatusList } from './status.ts';
import { searchToPage } from './search.ts';
import { saveBtnLabel } from './save.ts';
import { READING_LINE_PAGE, pageVerdictsOn } from './verdict.ts';
import { focusLine, isReasonField } from './verdict-reason.ts';
import { dropBareDayLines, placeRow } from './list.ts';
import { EDITOR } from './edit.ts';
import type { Html } from './markup.ts';

const NOTICE_MS = 6000; // the undo window: a deferred send goes when it ends (deferred()), and a save's chip stays as long
const NOTICE_HOLD_MAX = 30000; // a hold (a mouse on it, the '+N' list open) stretches a window by at most this: a send always goes
const VERDICT_CHIP_HOLD_MAX = 4000; // ...and a page verdict line's save chip by at most this: a mouse resting by the words kept it up for 30s
const LINE_MAX = 5; // the status line keeps five messages besides its undos (lineCap); its '+N' lists the rest
const NOTICES = new Map() as Map<number, Notice>;
const LINE = [] as Notice[]; // the status line's messages, newest first
const BANNERS = new Map() as Map<string, Notice>; // NOTICE_HOST -> its one banner
let NOTICE_SEQ = 0;
// A message's lead icon by its kind (noticeIcon).
const NOTICE_ICONS = {
  [NOTICE_KIND.OK]: () => ic('circle-check'),
  [NOTICE_KIND.WARN]: () => ic('triangle-alert'),
  [NOTICE_KIND.ERR]: () => ic('circle-x'),
  [NOTICE_KIND.INFO]: () => ic('info'),
} as Record<string, () => Html>;
// The lead icon of a message of kind (NOTICE_KIND); an unknown kind draws the success one.
function noticeIcon(kind: string): Html {
  return (NOTICE_ICONS[kind] || NOTICE_ICONS[NOTICE_KIND.OK])();
}

// A message as [title, description]: everything before the first ' — ' (else the first ' · ') is the title, so the title of
// '핀 #10 · 본문 — 서준님이 불렀습니다: …' is '핀 #10 · 본문'. A message without either is all title. Pure.
function splitMessage(message: unknown): [string, string] {
  const text = String(message == null ? '' : message),
    match = /^(.+?) — (.+)$/.exec(text) || /^(.+?) · (.+)$/.exec(text);
  return match ? [match[1], match[2]] : [text, ''];
}

// One event announced twice is shown once (QA: a focused tab showed both '핀 #37 · 본문 — 검토 대기: …' and '#37 이 검토 대기로
// 넘어왔습니다'). shown = the messages on the line; keys = the new message's event keys ('review_requested:37'), rank its path
// (the browser-notification path 2, the list comparison 1). Among shown messages younger than 8 seconds that share a key: a
// higher rank holding every key suppresses the new one ({skip:true}); a lower rank is replaced by it (drop). The same rank is
// the same path and so another event (a second review request after a reopen): never suppressed. No keys, no check. Pure.
function noticeDupe<Entry extends { at: number; keys: string[]; rank: number }>(
  shown: Entry[],
  keys: string[],
  rank: number,
  now: number,
): { skip: boolean; drop: Entry[] } {
  const drop = [] as Entry[];
  if (!keys || !keys.length) return { skip: false, drop };
  for (const x of shown) {
    if (now - x.at > 8000 || !x.keys.length || !keys.some((key) => x.keys.includes(key))) continue;
    if (x.rank > rank && keys.every((key) => x.keys.includes(key))) return { skip: true, drop: [] };
    if (rank > x.rank) drop.push(x);
  }
  return { skip: false, drop };
}

// Where a banner goes (a NOTICE_HOST): the Trash while it is open as a modal - the page under it is inert, so a banner there
// could be neither read nor dismissed - else the host the call names, else the composer while one is open, else the top of
// the panel. Pure.
function bannerHost(want: string | undefined, screen: { trashOpen: boolean; composerOpen: boolean }): string {
  if (screen.trashOpen) return NOTICE_HOST.TRASH;
  if (want) return want;
  return screen.composerOpen ? NOTICE_HOST.COMPOSER : NOTICE_HOST.LIST;
}
// Whether a banner host is on screen now (rule 1): the Trash while it is open; the composer while one is open in the shown
// panel (the phone's unfolded sheet); the list and the review section while the panel is shown. A banner whose host is not
// goes to the status line instead (bannerNote). Pure.
function bannerShown(host: string, screen: { sideOpen: boolean; trashOpen: boolean; composerOpen: boolean }): boolean {
  if (host === NOTICE_HOST.TRASH) return screen.trashOpen;
  if (host === NOTICE_HOST.COMPOSER) return screen.sideOpen && screen.composerOpen;
  return screen.sideOpen;
}

// Whether an undo can be shown where its action happened; if not it goes to the status line. A row or a card note needs the
// panel open and its section expanded, a Trash row the Trash open; a chip waits for its mark (drawChips). Pure.
function offerSeen(place: string, screen: { sideOpen: boolean; secOpen: boolean; trashOpen: boolean }): boolean {
  if (place === NOTICE_PLACE.TRASH) return screen.trashOpen;
  if (place === NOTICE_PLACE.ROW || place === NOTICE_PLACE.CARD) return screen.sideOpen && screen.secOpen;
  return true;
}

// The dot a background message puts on a chip (a NOTICE_DOT, or '' for none): [검토 M]'s always; [핀 N]'s only while the
// panel is closed - an open panel already shows the list. Pure.
function noticeDot(want: string, sideOpen: boolean): string {
  return want === NOTICE_DOT.SIDE && sideOpen ? '' : want || '';
}

// Registers a new message from its fields; msg is split into its title and description (msgSplit).
function makeNotice(fields: Partial<Notice> & { msg: string }): Notice {
  const [title, description] = splitMessage(fields.msg);
  const notice = {
    n: ++NOTICE_SEQ,
    place: fields.place || NOTICE_PLACE.LINE,
    host: fields.host || '',
    pin: fields.pin == null ? null : fields.pin,
    sec: fields.sec || '',
    prev: fields.prev == null ? null : fields.prev,
    rec: fields.rec || null,
    kind: fields.kind || NOTICE_KIND.OK,
    title,
    desc: description,
    label: fields.label || '',
    act: fields.act || null,
    literal: !!fields.literal,
    keys: fields.keys || [],
    rank: fields.rank || 1,
    at: Date.now(),
    life: fields.life || NOTICE_LIFE.STICKY,
    dot: fields.dot || '',
    topic: fields.topic || '',
    save: !!fields.save,
    pending: !!fields.pending,
    away: false,
    alert: !!fields.alert,
    busy: false,
    source: fields.source || '',
    undo: !!fields.undo,
    quiet: !!fields.quiet,
    hover: false,
    held: false,
    timer: undefined,
    gone: fields.gone || null,
    el: null,
    group: fields.group || '',
    keep: !!fields.keep,
    back: !!fields.back,
    dots: fields.dots || [],
    onEnd: fields.onEnd || null,
  } as Notice;
  NOTICES.set(notice.n, notice);
  return notice;
}

// Reads text out politely (#sr-news: a silent success, an undo drawn where it happened, an info banner) or assertively
// (#sr-alert: an error on the status line). The same text twice in a row is read again: the region is emptied first.
function announce(text: string, assertive?: boolean) {
  const region = $(assertive ? '#sr-alert' : '#sr-news');
  if (!region || !text) return;
  if (region.textContent === text) {
    region.textContent = '';
    requestAnimationFrame(() => {
      region.textContent = text;
    });
  } else region.textContent = text;
}

// A success with nothing to undo: nothing is drawn - the change itself is on screen - but it is read out as before.
function quietNote(message: string) {
  announce(trMsg(message));
}

// Puts a message on the status line, newest first, and returns it - or null when it repeats one already there (noticeDupe).
// o: literal (msg is already in the UI language and quotes what people wrote, so it is not translated), keys and rank, life
// (NOTICE_LIFE: STICKY until [x] or its action, CLICK until a press elsewhere, TIMER for NOTICE_MS), dot (the chip it marks,
// noticeDot), topic (a hint's, endTopic), gone (runs when it leaves other than by its action), alert (a warning read out as
// an alert: a banner whose place was not on screen), source (an error's: one entry per source - sourceEntry), undo (it
// offers an undo: lineCap never evicts it). An error is
// always an alert: read out assertively (#sr-alert) and first on the line (statusList). An error from a source that already
// has one replaces it - and when its words are the same it is that one, kept and not said again. Past LINE_MAX the oldest
// information leaves, then the oldest error, never an undo (lineCap). Any other message is read out by the line when it
// shows it, else - another one holds the line - politely (#sr-news).
function lineNote(message: string, kind: string, act?: NoticeAct | null, options?: Partial<Notice>): Notice | null {
  options = options || {};
  const keys = options.keys || [],
    rank = options.rank || 1,
    text = options.literal ? String(message) : trMsg(message);
  if (digestHold(message, kind, act, options)) return null; // gathered while a person was away (digestBegin): said once, together
  if (options.source) {
    const old = sourceEntry(options.source);
    if (old) {
      if (old.place === NOTICE_PLACE.LINE && sameWords(old, text, kind)) return old;
      endNotice(old, true);
    }
  }
  if (newsDupe(keys, rank, null)) return null;
  const notice = makeNotice({
    ...options,
    msg: options.literal ? String(message) : trMsg(message),
    kind,
    act: act || null,
    place: NOTICE_PLACE.LINE,
    pending: false,
    alert: kind === NOTICE_KIND.ERR || !!options.alert,
    dot: noticeDot(options.dot || '', SIDE_OPEN),
  });
  if (notice.back) LINE.push(notice);
  else if (notice.group) LINE.splice(newsSlot(), 0, notice);
  else LINE.unshift(notice); // news: behind the undos (newsSlot); another document's behind all (updates.js)
  lineCap();
  if (notice.dot) document.body.classList.add('dot-' + notice.dot);
  drawStatus();
  armNotice(notice);
  if (notice.alert) announce(noticeText(notice), true);
  else if (STATUS_TOP !== notice.n && !notice.quiet) announce(noticeText(notice));
  return notice;
}
// The line's cap (rule 2): it keeps LINE_MAX messages besides its undos and what must stay (keep: a document's update, a
// gathered line). Past that the oldest piece of information leaves, then the oldest error - oldest by when it came (at), as
// news may stand behind older messages (newsSlot, back) - never the newest message, and never an undo, which leaves only by
// its window, its [되돌리기] or its [x] (an evicted deferred send would go early).
function lineCap() {
  for (;;) {
    const kept = LINE.filter((notice) => !isUndo(notice) && !notice.keep);
    if (kept.length <= LINE_MAX) return;
    const rest = kept.filter((notice) => notice !== LINE[0]),
      oldest = (notices: Notice[]) =>
        notices.reduce((found: Notice | null, x) => (!found || x.at <= found.at ? x : found), null);
    endNotice((oldest(rest.filter((notice) => !notice.alert)) || oldest(rest)) as Notice, false);
  }
}
// Whether message n offers an undo: made as one (undoNote, a discarded selection) or holding a deferred send (gone).
function isUndo(notice: Notice): boolean {
  return notice.undo || !!notice.gone;
}
// Whether message n already says text (its title and description, as msgSplit cuts it) as kind.
function sameWords(notice: Notice, text: string, kind: string): boolean {
  const [title, description] = splitMessage(text);
  return notice.kind === kind && notice.title === title && notice.desc === description;
}
// The message an error source has standing (one at most - a repeat replaces it), or null. A source is a request (its method
// and URL, which names its pin and document, with what it asks of that URL - api()'s intent) or a named one.
function sourceEntry(source: string): Notice | null {
  for (const notice of NOTICES.values()) if (notice.source === source) return notice;
  return null;
}
// Source succeeded - its request was answered, or a build of its document came: its error is no longer true and goes.
function sourceOk(source: string) {
  if (source)
    NOTICES.forEach((notice) => {
      if (notice.source === source) endNotice(notice, true);
    });
}

// Puts a banner on top of its host's panel or section (bannerHost), replacing the one there, and scrolls it into view. ERR and
// WARN banners are alerts, read out when drawn; OK and INFO ones are read out politely. o.save marks a failed save: the
// composer's button then reads [다시 저장]. A host not on screen now (bannerShown) - the Trash closed, the panel collapsed,
// the phone's sheet folded - gets nothing: the message goes to the status line instead, ERR and WARN as alerts, with the dot
// on the chip that leads there ([검토 M] for the review section's, else [핀 N]). Returns the message drawn.
function bannerNote(
  host: string | undefined,
  message: string,
  kind: string,
  act?: NoticeAct | null,
  options?: Partial<Notice>,
): Notice | null {
  options = options || {};
  const screen = { sideOpen: SIDE_OPEN, trashOpen: $('#trash').open, composerOpen: !$('#composer').hidden },
    shownHost = bannerHost(host, screen);
  if (!bannerShown(shownHost, screen))
    return lineNote(message, kind, act, {
      ...options,
      alert: kind === NOTICE_KIND.ERR || kind === NOTICE_KIND.WARN,
      dot: shownHost === NOTICE_HOST.REVIEW ? NOTICE_DOT.RV : NOTICE_DOT.SIDE,
    });
  const text = options.literal ? String(message) : trMsg(message); // a source's repeat in the same words is the banner already there: not drawn or said again
  if (options.source) {
    const same = sourceEntry(options.source);
    if (same) {
      if (same.place === NOTICE_PLACE.BANNER && same.host === shownHost && sameWords(same, text, kind)) return same;
      endNotice(same, true);
    }
  }
  const old = BANNERS.get(shownHost);
  if (old) endNotice(old, false);
  const notice = makeNotice({
    ...options,
    msg: options.literal ? String(message) : trMsg(message),
    kind,
    act: act || null,
    place: NOTICE_PLACE.BANNER,
    host: shownHost,
  });
  BANNERS.set(shownHost, notice);
  drawBanners();
  if (kind !== NOTICE_KIND.ERR && kind !== NOTICE_KIND.WARN) announce(noticeText(notice));
  if (notice.el && notice.el.getClientRects().length) notice.el.scrollIntoView({ block: 'nearest' });
  return notice;
}

// Offers an undo where the action happened (place CHIP, ROW, CARD or TRASH; offerSeen) or, when that place is not on screen,
// on the status line. o: pin, sec (its list section: 'open', 'review' or 'done') and prev (the pin drawn before it), label (a
// chip's short text; the whole message is what is read out), life (TIMER: NOTICE_MS, unless given - rule 2, no other press
// ends it), gone, pending (a chip whose mark comes only with the next list reload: settleChip). act.tip defaults to T.undo;
// act.wait = its action sends a request, and the undo stays until that is answered (noticeAct).
function undoNote(place: string, message: string, act: NoticeAct, options: Partial<Notice>): Notice {
  const action = { tip: T.undo, ...act },
    life = options.life || NOTICE_LIFE.TIMER;
  if (
    !offerSeen(place, { sideOpen: SIDE_OPEN, secOpen: !options.sec || !!SEC[options.sec], trashOpen: $('#trash').open })
  )
    return lineNote(message, NOTICE_KIND.OK, action, { ...options, life, undo: true }) as Notice; // no keys: never suppressed
  const notice = makeNotice({
    ...options,
    life,
    undo: true,
    msg: trMsg(message),
    kind: NOTICE_KIND.OK,
    act: action,
    place,
  });
  // One save chip on the pages at a time, the newest: an earlier one takes its undo to the status line (offerToLine), as a
  // chip whose mark went does - several pages each showing a chip read as several things to answer.
  if (place === NOTICE_PLACE.CHIP)
    [...NOTICES.values()].filter((x) => x !== notice && x.place === NOTICE_PLACE.CHIP).forEach(offerToLine);
  armNotice(notice);
  drawOffer(notice);
  announce(noticeText(notice));
  return notice;
}

// Whether an undo row stands in list section sec ('open', 'review'): drawPins keeps that section shown while one does.
function offersIn(section: string): boolean {
  for (const notice of NOTICES.values()) if (notice.place === NOTICE_PLACE.ROW && notice.sec === section) return true;
  return false;
}

// The id of the element drawn just before pin id's in box (both matching sel: '.pin.card', '.arc-row'), or null - where a
// row left in its place goes. Reads the page.
function drawnBefore(box: HTMLElement, selector: string, id: number | null): number | null {
  const own = box.querySelector(selector + '[data-id="' + id + '"]');
  let before = own && own.previousElementSibling;
  while (before && !before.matches(selector)) before = before.previousElementSibling;
  return before ? Number((before as HTMLElement).dataset.id) : null;
}

// A message's text as one line: its title, then ' · ' and its description.
function noticeText(notice: Notice) {
  return notice.title + (notice.desc ? ' · ' + notice.desc : '');
}

// Draws a new offer in its place now; its place's own redraw keeps it there (drawPins, marks, drawTrash).
function drawOffer(notice: Notice) {
  if (notice.place === NOTICE_PLACE.CHIP) drawChips();
  else if (notice.place === NOTICE_PLACE.TRASH) drawTrashOffers();
  else drawOffers();
}

// Starts (or restarts) a message's life: a TIMER one ends after NOTICE_MS. While it is held (noticeHeld: a mouse on it, or
// for one on the status line the line held) its window waits, and starts from the start again when the hold ends, as the
// toast did - but a hold never stretches it past NOTICE_HOLD_MAX beyond its first window, so no hold can keep it (and a
// send it holds) forever. Not held by the focus, which a reply sent with Ctrl+Enter puts on its [되돌리기], so the send would
// wait for the focus to move; stopped while its action's request is out (busy, noticeAct). CLICK and STICKY ones wait for
// the press listener below, [x] or their action.
function armNotice(notice: Notice) {
  if (notice.life !== NOTICE_LIFE.TIMER) return;
  clearTimeout(notice.timer);
  notice.timer = undefined;
  notice.held = false;
  if (notice.busy) return;
  const line =
    notice.place === NOTICE_PLACE.CHIP &&
    !!notice.el &&
    !!notice.el.parentElement &&
    notice.el.parentElement.classList.contains('pv');
  const left = notice.at + NOTICE_MS + (line ? VERDICT_CHIP_HOLD_MAX : NOTICE_HOLD_MAX) - Date.now();
  notice.held = noticeHeld(notice);
  notice.timer = setTimeout(
    () => {
      const back = noticeFocusBack(notice, true);
      endNotice(notice, false);
      back();
    },
    Math.max(0, notice.held ? left : Math.min(NOTICE_MS, left)),
  );
}
// Whether message n's window is held now: one on the status line while the line is (lineHeld); one drawn in place while a
// mouse is on its element - still in the page and under the pointer, so no hold outlives what was hovered.
function noticeHeld(notice: Notice): boolean {
  if (notice.place === NOTICE_PLACE.LINE) return lineHeld();
  return notice.hover && !!notice.el && notice.el.isConnected && notice.el.matches(':hover');
}
// The status line holds its messages' windows while a mouse is on it (LINE_HOVER) or its '+N' list is open: what it shows
// there is being read. The hover ends however the pointer leaves - out of the line, cancelled, out of the window - and when
// the line hides or loses a message (lineVisible, endNotice): a hold never outlives the thing hovered. holdLine stops the
// windows (bounded, armNotice); releaseLine starts each held one again once nothing holds.
let LINE_HOVER = false;
function lineHeld() {
  return LINE_HOVER || $('#status-list').open;
}
function holdLine() {
  LINE.forEach((notice) => {
    if (notice.life === NOTICE_LIFE.TIMER && !notice.held) armNotice(notice);
  });
}
function releaseLine() {
  LINE.forEach((notice) => {
    if (notice.held) armNotice(notice);
  });
}
// A mouse moves over the line: the hover starts with a real movement (realMove), never with the line drawn under a resting
// pointer - that would hold every undo appearing there. A touch never holds: its pointer leaves as it lifts.
function lineHoverIn(move: {
  pointerType?: string;
  movementX?: number;
  movementY?: number;
  clientX?: number;
  clientY?: number;
}) {
  if (LINE_HOVER || !move || !realMove(move)) return;
  LINE_HOVER = true;
  holdLine();
}
// The pointer's position at the last move the page saw (document pointermove, after the element's own listener has run).
let LAST_POINTER_AT = null as { x: number; y: number } | null;
// Whether pointer move e is a mouse really moving: a non-zero delta, by its own movement or against the last position seen.
// A move the browser makes up under a resting pointer when the page changes under it has neither, so a message drawn under
// a still pointer is not hovered until the mouse moves over it.
function realMove(move: {
  pointerType?: string;
  movementX?: number;
  movementY?: number;
  clientX?: number;
  clientY?: number;
}): boolean {
  if (move.pointerType !== 'mouse') return false;
  if (move.movementX || move.movementY) return true;
  const last = LAST_POINTER_AT;
  return !!last && (last.x !== move.clientX || last.y !== move.clientY);
}
document.addEventListener(
  'pointermove',
  (event) => {
    LAST_POINTER_AT = { x: event.clientX, y: event.clientY };
  },
  { passive: true },
);
// The pointer is off the line, for whatever reason: the hover ends and the windows run again.
function lineHoverOut() {
  if (!LINE_HOVER) return;
  LINE_HOVER = false;
  releaseLine();
}
// The line shows (drawStatus) or hides: hidden - nothing to show, or moved to another band - it holds nothing.
function lineVisible(shown: boolean) {
  if (!shown) lineHoverOut();
}
$('#status').addEventListener('pointermove', lineHoverIn, { passive: true });
for (const eventType of ['pointerleave', 'pointercancel']) $('#status').addEventListener(eventType, lineHoverOut);
document.addEventListener('pointerout', (event) => {
  if (!event.relatedTarget) lineHoverOut();
}); // out of the window
window.addEventListener('blur', lineHoverOut);
$('#status-list').addEventListener('close', releaseLine);

// Takes a message away from its store and the screen. acted = its own action ended it: gone does not run (the action replaces
// it). acted or seen ([x]) = the person has read it: its dot goes unless another message still holds it (dotHeld). One
// leaving the line ends the line's hover (lineHoverOut). Idempotent.
function endNotice(notice: Notice, acted: boolean, seen?: boolean) {
  if (!NOTICES.has(notice.n)) return;
  NOTICES.delete(notice.n);
  clearTimeout(notice.timer);
  notice.held = false;
  const lineIndex = LINE.indexOf(notice);
  if (lineIndex >= 0) {
    LINE.splice(lineIndex, 1);
    lineHoverOut();
  }
  if (notice.place === NOTICE_PLACE.BANNER && BANNERS.get(notice.host) === notice) BANNERS.delete(notice.host);
  if (notice.el) notice.el.remove();
  if (notice.place === NOTICE_PLACE.ROW) dropBareDayLines(); // a day line drawn for this row alone goes with it
  if (acted || seen)
    noticeDots(notice).forEach((dot) => {
      if (!dotHeld(dot)) document.body.classList.remove('dot-' + dot);
    });
  const group = notice.group ? GROUPS.get(notice.group) : undefined;
  if (group && group.n === notice) GROUPS.delete(notice.group);
  if (notice.place === NOTICE_PLACE.LINE) drawStatus();
  if (notice.place === NOTICE_PLACE.BANNER) {
    syncSaveButton();
    tipFollow();
  } // what was under it moved up
  if (notice.onEnd) {
    const ended = notice.onEnd;
    notice.onEnd = null;
    ended(acted, !!seen);
  }
  if (!acted && notice.gone) {
    const gone = notice.gone;
    notice.gone = null;
    gone();
  }
}
// The chips message n marks: its dot, or a gathered message's dots (digestEnd). Pure.
function noticeDots(notice: Notice): string[] {
  return notice.dots && notice.dots.length ? notice.dots : notice.dot ? [notice.dot] : [];
}
function holdsDot(notice: Notice, dot: string): boolean {
  return noticeDots(notice).includes(dot);
}
// Whether a message still marks chip d: one on the line (a gathered line by what it holds), or one being gathered (DIGEST),
// whose dot went on as it was gathered (digestHold) and stays until it is said or seen.
function dotHeld(dot: string): boolean {
  return LINE.some((x) => holdsDot(x, dot)) || (!!DIGEST && digestDots([...DIGEST.items.values()]).includes(dot));
}

// Read before message n goes. A button of it with the focus goes with it, and what is returned, called once it has gone, finds
// the focus a place: on a document with page lines the line of the page the button was on (a chip's) or the reading page's, else
// the pages - never nothing, so Tab goes on from there and not from the top of the page. Called where nothing took the focus
// meanwhile; a press with a reason being typed leaves it in its field (noticeAct). With a card's editor or reply open it is left
// out of the pages: there a digit is the pages' verdict key (verdictKey shuts them for a focus outside the pages), and a person
// in the middle of a reply did not ask for that. anyDoc: on a document without page lines too. An action's press goes without
// it, for the action may put the focus where it wants; the window's end and [x] have no action.
function noticeFocusBack(notice: Notice, anyDoc?: boolean): () => void {
  const focused = document.activeElement as HTMLElement | null;
  const own = !!focused && !!focused.closest && !!focused.closest('[data-act^="notice-"][data-n="' + notice.n + '"]');
  const line = own && focused ? (focused.closest('#doc .pv') as HTMLElement | null) : null,
    page = line ? Number(line.dataset.page) || 0 : 0;
  return () => {
    const nowFocused = document.activeElement;
    if (!own || (nowFocused && nowFocused !== document.body) || EDITOR.current || REPLY) return;
    const lines = !!pageVerdictsOn();
    if (lines ? !focusLine(page || READING_LINE_PAGE) : anyDoc) searchToPage();
  };
}
// How long an action's request may go unanswered before its message says so (noticeLate) - the bound a page line's
// take-back has too (verdict.js CANCEL_ANSWER_WAIT). A let: the tests shorten it.
let NOTICE_ACT_WAIT = 8000;
// [되돌리기], [다시 시도], [보기]… on message num: the message goes and its action runs. An action that sends a request
// (act.wait: restoring, undoing a close, a delete, a save or an append) keeps its message, busy and with its window stopped,
// until the request is answered (rule 1: not cleared as if it had worked) - a failure then says itself where it can be seen.
// Past NOTICE_ACT_WAIT without an answer the message says the answer is late (noticeLate); the answer, whenever it comes,
// is still taken once. A late one leaves the focus the person has put somewhere since the press (a focusin anywhere but the
// message's own button: a redraw giving the focus back to that button, or the focus falling to nothing as the button goes -
// the action's own redraw may take it away before its answer resolves - is not a move): then back() does not run, and the
// action is told (run.away(), save.js) so that it takes no focus either.
function noticeAct(number: number) {
  const notice = NOTICES.get(number);
  if (!notice || notice.busy) return;
  const action = notice.act;
  if (action && action.stay) {
    action.fn();
    return;
  } // an action that leaves the message standing (the next changed place, updates.js)
  const back = noticeFocusBack(notice);
  if (!action || !action.wait) {
    endNotice(notice, true);
    if (action) action.fn();
    back();
    return;
  }
  notice.busy = true;
  clearTimeout(notice.timer);
  notice.timer = undefined;
  notice.held = false;
  document
    .querySelectorAll('[data-act="notice-act"][data-n="' + notice.n + '"]')
    .forEach((button) => button.setAttribute('aria-busy', 'true'));
  let late = false,
    moved = false;
  const wait = setTimeout(() => {
    late = true;
    noticeLate(notice, action);
  }, NOTICE_ACT_WAIT);
  const seen = (event: FocusEvent) => {
    const target = event.target as HTMLElement | null;
    if (!target || !target.closest || !target.closest('[data-act="notice-act"][data-n="' + notice.n + '"]'))
      moved = true;
  };
  document.addEventListener('focusin', seen, true);
  const run: NoticeRun = { away: () => late && moved };
  Promise.resolve(action.fn(run))
    .catch(() => false)
    .then(() => {
      clearTimeout(wait);
      document.removeEventListener('focusin', seen, true);
      endNotice(notice, true);
      sourceOk(NOTICE_LATE_SRC + notice.n);
      if (!run.away()) back();
    });
}
// noticeAct's question for an action run without its watch - a failure's [다시 시도], which is no waiting action, running an
// undo again (save.js): away() = its answer is late (NOTICE_ACT_WAIT) and the person has put the focus somewhere since. The
// watch starts once the press's own work is done (its message going, back()), so the focus that work moves is not counted.
function focusRun(): NoticeRun & { stop: () => void } {
  const at = Date.now();
  let moved = false,
    on = true;
  const seen = () => {
    moved = true;
  };
  queueMicrotask(() => {
    if (on) document.addEventListener('focusin', seen, true);
  });
  return {
    away: () => moved && Date.now() - at >= NOTICE_ACT_WAIT,
    stop: () => {
      on = false;
      document.removeEventListener('focusin', seen, true);
    },
  };
}
// The source of the status line's message that says message n's answer is late, when n is not on the line (noticeLate).
const NOTICE_LATE_SRC = 'notice-late:';
// Message n's action a has sent a request that is not answered after NOTICE_ACT_WAIT: '되돌리기의 답이 늦습니다' (a 되살리기's
// says so) goes before all the message said ('되돌리기의 답이 늦습니다 · #12 채택 판정 저장됨 · …'). It is one title with no
// description: a line too narrow for a long text shows a message's title alone (drawStatus), which as the late words alone
// lost what was being undone and drew the line narrower; whole, the target follows the late words and only the end is
// cut. On the status line the message itself says it, first on the line again (newest) and as a warning: a message whose
// busy button has the focus keeps the line (drawStatus), so a message of its own would wait behind '+N'. Elsewhere - a
// chip, a row, the Trash, or the message gone by its [x] - the status line says it in one message of its own
// (NOTICE_LATE_SRC), which goes with the answer as the message does (noticeAct). Either way one message per action:
// nothing is said twice. The line is not locked meanwhile, so there is nothing to give back.
function noticeLate(notice: Notice, action: NoticeAct) {
  const what =
    tr(
      action.label === '되살리기'
        ? '되살리기의 답이 늦습니다'
        : action.label === '다시 시도'
          ? '다시 시도의 답이 늦습니다'
          : '되돌리기의 답이 늦습니다',
    ) +
    ' · ' +
    noticeText(notice); // every action that waits is one of the three (the review rows' [다시 시도], review-pick.js)
  const index = notice.place === NOTICE_PLACE.LINE && NOTICES.has(notice.n) ? LINE.indexOf(notice) : -1;
  if (index < 0) {
    const lateNotice = lineNote(what, NOTICE_KIND.WARN, null, { literal: true, source: NOTICE_LATE_SRC + notice.n });
    if (lateNotice) {
      lateNotice.title = what;
      lateNotice.desc = '';
      drawStatus();
    }
    return;
  } // lineNote cuts at ' · '
  notice.title = what;
  notice.desc = '';
  notice.kind = NOTICE_KIND.WARN;
  notice.quiet = false;
  LINE.splice(index, 1);
  LINE.unshift(notice);
  drawStatus();
  if (notice.alert) announce(noticeText(notice), true);
  else if (STATUS_TOP !== notice.n) announce(noticeText(notice));
} // as lineNote reads one out
// A press on a message's action does not take the focus from the reason field being typed in: its button goes with the message, and
// the keys typed next would be verdict keys.
document.addEventListener(
  'mousedown',
  (event) => {
    const target = event.target as HTMLElement | null;
    if (
      !!target &&
      !!target.closest &&
      !!target.closest('[data-act="notice-act"]') &&
      isReasonField(document.activeElement)
    )
      event.preventDefault();
  },
  true,
);
// [x] on message num: it goes as read (with its dot), and what it held runs (gone: a deferred send goes now).
function noticeClose(number: number) {
  const notice = NOTICES.get(number);
  if (!notice) return;
  const back = noticeFocusBack(notice, true);
  endNotice(notice, false, true);
  back();
}
// A hint goes once the person does what it says (NOTICE_TOPIC.PICK: a selection was made; SIDE: the panel was opened).
function endTopic(topic: string) {
  NOTICES.forEach((notice) => {
    if (notice.topic === topic) endNotice(notice, false, true);
  });
}
// The person looks where a dot points (the panel opened, the review section gone to): that dot goes, with the panel open the
// hint on how to open it, and with the review section the messages about pins sent to review (seen) - on the line and
// folded in a gathered line (foldedGone), which [펼치기] would otherwise put back with the dot.
function noticeSeen(dot: string) {
  if (dot === NOTICE_DOT.RV) {
    LINE.slice().forEach((notice) => {
      if (reviewPins(notice.keys).length) endNotice(notice, false, true);
    });
    foldedNews().forEach((folded) => {
      if (reviewPins(folded.keys).length) foldedGone(folded, true);
    });
    gatheredGone((options) => reviewPins(options.keys || []).length > 0);
  }
  document.body.classList.remove('dot-' + dot);
  if (dot === NOTICE_DOT.SIDE) endTopic(NOTICE_TOPIC.SIDE);
}
// The gathering under way (DIGEST) loses the messages test picks (by their options), as seen: never said - their groups
// go with them when no message of theirs stands, and what each held for its end runs, as for a message seen on the line.
function gatheredGone(test: (options: any) => boolean) {
  if (!DIGEST) return;
  for (const [group, item] of [...DIGEST.items]) {
    const options = item[3] || {};
    if (!test(options)) continue;
    DIGEST.items.delete(group);
    const entry = GROUPS.get(group);
    if (entry && !(entry.n && NOTICES.has(entry.n.n))) GROUPS.delete(group);
    if (options.onEnd) options.onEnd(false, true);
  }
}
// The pins a message's keys say were sent to review ('review_requested:<id>', noticeDupe's keys). Pure.
function reviewPins(keys: string[]): number[] {
  const prefix = EVENT_TYPE.REVIEW_REQUESTED + ':';
  return keys.filter((key) => key.startsWith(prefix)).map((key) => Number(key.slice(prefix.length)));
}
// Whether a message about pins sent to review is stale: it names some, and none of them awaits review any more (confirmed,
// reopened or deleted - here or elsewhere). inReview = the ids awaiting review. Pure.
function reviewNewsStale(keys: string[], inReview: number[]): boolean {
  const ids = reviewPins(keys);
  return ids.length > 0 && !ids.some((id) => inReview.includes(id));
}
// Each time the list is drawn (drawPins: after a reload, a confirm): the stale review arrivals go (reviewNewsStale) - on the
// line, folded in a gathered line (foldedGone: the line then says, and marks, what is left) and in a gathering still under
// way (DIGEST) - and [검토 M]'s dot - on the collapsed desktop's [핀 N] too - once no message on the line or gathered holds
// it (dotHeld).
function dropStaleReview() {
  const ids = REVIEW_ALL.map((pin) => pin.id);
  LINE.slice().forEach((notice) => {
    if (reviewNewsStale(notice.keys, ids)) endNotice(notice, false, true);
  });
  foldedNews().forEach((folded) => {
    if (reviewNewsStale(folded.keys, ids)) foldedGone(folded, true);
  });
  gatheredGone((options) => reviewNewsStale(options.keys || [], ids)); // still being gathered (the return's poll said it before the list came)
  if (!dotHeld(NOTICE_DOT.RV)) document.body.classList.remove('dot-' + NOTICE_DOT.RV);
}

// ---------------- Messages that gather (docs/handbook/viewer.md §새 소식)
// One status-line message per group ('new:<doc>', 'done', 'upd:<doc>'…): a new event of a group whose message still stands
// merges into it - merge(old data, new data) gives the whole - and the message says the whole again in place, as the newest
// on the line, its window (a passing one's) starting again. view(data) gives what it says: {msg, kind, act, o}. A group held
// by a gathering (digestHold) or by a gathered message not yet unfolded (digestTake) merges the same way, so twelve pins
// closed one by one are one message, never twelve.
// The same event on two paths is said once per event, not per message (noticeDupe's keys): less(data, keys) - given by a
// group whose message carries keys - is its data without the events of those keys, or null when none is left. Events a
// message of a higher rank already says are left out of what a group says (keysHeld); and when such a message comes later,
// it takes its events out of the group's message, which says the rest in place (noticeLess) - the others stay. Such a
// message coming by growing its own group's message does the same, and a group's message folded in a gathered line not yet
// unfolded, or still being gathered, gives way as one on the line does (newsDupe, foldedLess, gatheredLess).
type GroupView = (data: any) => { msg: string; kind: string; act: NoticeAct | null; o: Partial<Notice> };
type GroupLess = (data: any, keys: string[]) => any;
const GROUPS = new Map() as Map<string, { data: any; n: Notice | null; view: GroupView; less: GroupLess | null }>;
function groupNote(
  group: string,
  data: any,
  view: GroupView,
  merge?: ((older: any, newer: any) => any) | null,
  less?: GroupLess | null,
): Notice | null {
  const entry = GROUPS.get(group);
  if (less) {
    const options = view(data).o || {},
      held = keysHeld(options.keys || [], options.rank || 1);
    if (held.length) {
      data = less(data, held);
      if (data == null) return entry && entry.n && NOTICES.has(entry.n.n) ? entry.n : null;
    }
  }
  const alive =
    !!entry &&
    ((!!entry.n && NOTICES.has(entry.n.n) && !entry.n.busy) ||
      (!!DIGEST && DIGEST.items.has(group)) ||
      digestTake(group));
  const merged = alive && entry && merge ? merge(entry.data, data) : data,
    said = view(merged);
  if (alive && entry && entry.n && NOTICES.has(entry.n.n)) {
    const options = view(data).o || {};
    newsDupe(options.keys || [], options.rank || 1, entry.n); // what this event says, said elsewhere
    entry.data = merged;
    entry.view = view;
    entry.less = less || null;
    regroup(entry.n, said);
    return entry.n;
  }
  GROUPS.set(group, { data: merged, n: null, view, less: less || null });
  const notice = lineNote(said.msg, said.kind, said.act, { ...said.o, group });
  const stored = GROUPS.get(group);
  if (stored && notice) stored.n = notice;
  return notice;
}
// The keys among keys that a message of a higher rank than rank already says: one on the line or folded in a gathered line
// (foldedNews), younger than noticeDupe's window, or one gathered (DIGEST).
function keysHeld(keys: string[], rank: number): string[] {
  const now = Date.now(),
    gathered = DIGEST
      ? [...DIGEST.items.values()].map((item) => item[3] || {}).filter((options) => (options.rank || 1) > rank)
      : [],
    folded = foldedNews();
  return keys.filter(
    (key) =>
      noticeDupe(LINE, [key], rank, now).skip ||
      noticeDupe(folded, [key], rank, now).skip ||
      gathered.some((options) => (options.keys || []).includes(key)),
  );
}
// A message of rank that says the events of keys comes (lineNote), or a group's message grows by them (groupNote; except:
// that message): whether one of a higher rank says them all already - on the line, folded in a gathered line not yet
// unfolded (foldedNews) or in the gathering under way (gatheredDupe) - so it is not said again (noticeDupe's skip); else
// each of a lower rank that says some of them gives way (its drop): it says the rest in place (noticeLess, foldedLess,
// gatheredLess) or goes.
function newsDupe(keys: string[], rank: number, except: Notice | null): boolean {
  const now = Date.now(),
    line = noticeDupe(
      LINE.filter((x) => x !== except),
      keys,
      rank,
      now,
    ),
    fold = noticeDupe(foldedNews(), keys, rank, now),
    gathered = gatheredDupe(keys, rank, except ? except.group : '');
  if (line.skip || fold.skip || gathered.skip) return true;
  line.drop.forEach((x) => noticeLess(x, keys));
  fold.drop.forEach((folded) => foldedLess(folded, keys));
  gathered.drop.forEach((group) => gatheredLess(group, keys));
  return false;
}
// The gathering under way (DIGEST) as noticeDupe compares the line - a gathering is shorter than its window: skip when a
// gathered message of a higher rank says every one of keys; else drop names each gathered group of a lower rank that says
// some of them. except: the group of the message that says keys. Pure but for DIGEST.
function gatheredDupe(keys: string[], rank: number, except: string): { skip: boolean; drop: string[] } {
  const drop = [] as string[];
  if (!DIGEST || !keys.length) return { skip: false, drop };
  for (const [group, item] of DIGEST.items) {
    const itemOptions = item[3] || {},
      itemKeys = itemOptions.keys || [],
      itemRank = itemOptions.rank || 1;
    if (group === except || !keys.some((key) => itemKeys.includes(key))) continue;
    if (itemRank > rank && keys.every((key) => itemKeys.includes(key))) return { skip: true, drop: [] };
    if (rank > itemRank) drop.push(group);
  }
  return { skip: false, drop };
}
// Gathered group g gives way to a message of a higher rank that says the events of keys, as noticeLess on the line: a group
// that can leave them out (less) stays gathered with the rest; with nothing left, or a group that cannot, it leaves the
// gathering, never said - its group with it, and what it held for its end runs, as for a folded message (foldedGone).
function gatheredLess(group: string, keys: string[]) {
  const digest = DIGEST,
    item = digest ? digest.items.get(group) : undefined;
  if (!digest || !item) return;
  const entry = GROUPS.get(group),
    rest = entry && entry.less ? entry.less(entry.data, keys) : null;
  if (!entry || rest == null) {
    const options = item[3] || {};
    digest.items.delete(group);
    if (entry && !(entry.n && NOTICES.has(entry.n.n))) GROUPS.delete(group);
    if (options.onEnd) options.onEnd(false, false);
    return;
  }
  entry.data = rest;
  const said = entry.view(rest);
  digest.items.set(group, [said.msg, said.kind, said.act, { ...said.o, group: group }]);
}
// Group's message says its data again wherever it stands - on the line (regroup), gathered (DIGEST) or folded in a gathered
// line not yet unfolded (which then says what it holds, digestRetitle) - for what its view reads besides its data (a
// document's moved pins and changed lines, updates.js). Whether it stands anywhere.
function groupRedraw(group: string): boolean {
  const entry = GROUPS.get(group);
  if (!entry) return false;
  if (entry.n && NOTICES.has(entry.n.n)) {
    regroup(entry.n, entry.view(entry.data));
    return true;
  }
  const said = entry.view(entry.data),
    item = [said.msg, said.kind, said.act, { ...said.o, group }];
  if (DIGEST && DIGEST.items.has(group)) {
    DIGEST.items.set(group, item);
    return true;
  }
  const folded = foldedNews().find((x) => (x.item[3] || {}).group === group),
    items = folded ? folded.line.items || [] : [],
    index = folded ? items.indexOf(folded.item) : -1;
  if (!folded || index < 0) return false;
  items[index] = item;
  digestRetitle(folded.line);
  return true;
}
// The messages gathered lines not yet unfolded hold (digestNote's items), as noticeDupe compares them: each with its keys
// and rank, as old as its gathered line (at), and where it is held (line, item).
function foldedNews(): { at: number; keys: string[]; rank: number; line: Notice; item: any[] }[] {
  return LINE.flatMap((notice) =>
    (notice.items || []).map((item) => {
      const options = item[3] || {};
      return { at: notice.at, keys: options.keys || [], rank: options.rank || 1, line: notice, item: item };
    }),
  );
}
// Folded message f gives way to a message of a higher rank that says the events of keys, as noticeLess on the line: its
// group that can leave them out (less) says the rest in the gathered line; with nothing left, or a group that cannot, it
// leaves the gathered line, not seen (foldedGone). The line says what is left (digestRetitle).
function foldedLess(folded: { line: Notice; item: any[] }, keys: string[]) {
  const items = folded.line.items || [],
    index = items.indexOf(folded.item),
    options = folded.item[3] || {},
    entry = options.group ? GROUPS.get(options.group) : undefined;
  if (index < 0) return;
  const rest = entry && entry.less ? entry.less(entry.data, keys) : null;
  if (!entry || rest == null) {
    foldedGone(folded, false);
    return;
  }
  entry.data = rest;
  const said = entry.view(rest);
  items[index] = [said.msg, said.kind, said.act, { ...said.o, group: options.group }];
  digestRetitle(folded.line);
}
// Folded message f leaves its gathered line, as a message leaving the line does: its group ends with it, what it held for
// its end runs (seen: as read - a review request whose pins left review, or the review section seen), and the line says
// and marks what is left (digestRetitle).
function foldedGone(folded: { line: Notice; item: any[] }, seen: boolean) {
  const items = folded.line.items || [],
    index = items.indexOf(folded.item),
    options = folded.item[3] || {},
    entry = options.group ? GROUPS.get(options.group) : undefined;
  if (index < 0) return;
  items.splice(index, 1);
  if (entry && !(entry.n && NOTICES.has(entry.n.n))) GROUPS.delete(options.group);
  if (options.onEnd) options.onEnd(false, seen);
  digestRetitle(folded.line);
}
// Message x gives way to a message of a higher rank that says the events of keys (noticeDupe's drop): a group's message
// that can leave them out (less) says the rest in place - not as news again: neither moved, nor read out, nor its window
// started again - and one with nothing left, or that cannot, goes.
function noticeLess(notice: Notice, keys: string[]) {
  const entry = notice.group ? GROUPS.get(notice.group) : undefined,
    rest = entry && entry.n === notice && entry.less ? entry.less(entry.data, keys) : null;
  if (!entry || rest == null) {
    endNotice(notice, false);
    return;
  }
  entry.data = rest;
  regroup(notice, entry.view(rest), true);
}
// Where news (a message of a group) stands on the line: right behind the last undo still standing - an undo lives its window
// where it can be pressed (rule 2), and news arriving meanwhile must not hide it behind '+N' - else first.
function newsSlot(): number {
  let slot = 0;
  LINE.forEach((x, index) => {
    if (isUndo(x)) slot = index + 1;
  });
  return slot;
}
// Message n says view v now (groupNote): its words, kind, action, keys and dot, as the newest on the line, read out again
// (politely, unless quiet) when its words changed - by the line's own live region (.st-sr, drawStatus) when the line shows
// it, else by #sr-news, never by both, as lineNote reads a first message - and a passing one's window starts again.
// still: it says less than before (noticeLess) and stays where it is, its window running on, not read out.
function regroup(
  notice: Notice,
  said: { msg: string; kind: string; act: NoticeAct | null; o: Partial<Notice> },
  still?: boolean,
) {
  const options = said.o || {},
    [title, description] = splitMessage(options.literal ? String(said.msg) : trMsg(said.msg));
  const same = notice.title === title && notice.desc === description && notice.kind === said.kind;
  notice.title = title;
  notice.desc = description;
  notice.kind = said.kind;
  notice.act = said.act || null;
  if (!still) notice.at = Date.now();
  if (options.keys) notice.keys = options.keys;
  if (options.onEnd) notice.onEnd = options.onEnd;
  if (options.life) notice.life = options.life;
  notice.back = !!options.back;
  const dot = noticeDot(options.dot || '', SIDE_OPEN);
  if (dot) {
    notice.dot = dot;
    document.body.classList.add('dot-' + dot);
  }
  const index = LINE.indexOf(notice);
  if (index >= 0 && !notice.back && !still) {
    LINE.splice(index, 1);
    LINE.splice(newsSlot(), 0, notice);
  }
  setStatusSig('');
  drawStatus();
  if (still) return;
  armNotice(notice);
  if (!same && !options.quiet && STATUS_TOP !== notice.n) announce(noticeText(notice));
}

// ---------------- Gathering while a person was away (docs/handbook/viewer.md §새 소식)
// Back after a while (the tab hidden or the device asleep, polling.js) or opening the viewer again (boot), what the first
// polls say is gathered for a moment (digestBegin … digestEnd) and said as one message: '자리를 비운 사이 (38분) — 본문이
// 바뀌었습니다 · 나를 부름 2 · 검토 대기 3', with [펼치기], which puts each on the line as it would have come. One gathered
// thing alone is said as itself. Only news is gathered - a message of a group (groupNote: a document's update, new pins, an
// event addressed to me, the list comparison) - and its dots are put on at once. The screen's own messages (a restored draft,
// a hint), an error, an undo, a message with an error source or one that asks not to (digest:false) are said as they come -
// an error where it can be seen now (rule 1).
let DIGEST = null as {
  title: string;
  items: Map<string, any[]>;
  timer: ReturnType<typeof setTimeout> | undefined;
} | null;
const DIGEST_MAX_MS = 8000; // a gathering never lasts longer than this, whatever it waits for
function digestBegin(title: string) {
  if (DIGEST) return;
  DIGEST = { title, items: new Map(), timer: setTimeout(digestEnd, DIGEST_MAX_MS) };
}
// Ends the gathering ms from now (at once without ms): what the first poll set going has come by then.
function digestSoon(ms?: number) {
  const digest = DIGEST;
  if (!digest) return;
  clearTimeout(digest.timer);
  digest.timer = setTimeout(digestEnd, ms || 0);
}
function digestHold(
  message: string,
  kind: string,
  act: NoticeAct | null | undefined,
  options: Partial<Notice>,
): boolean {
  const digest = DIGEST;
  if (
    !digest ||
    !options.group ||
    options.digest === false ||
    options.undo ||
    options.gone ||
    options.source ||
    options.alert ||
    kind === NOTICE_KIND.ERR
  )
    return false;
  // one event on two paths is gathered once, as the line shows it once (noticeDupe): the event path wins over the list's
  // - per event: a gathered group that can leave the events out (less) keeps the rest (gatheredLess)
  const keys = options.keys || [],
    dup = gatheredDupe(keys, options.rank || 1, options.group);
  if (dup.skip) return true;
  dup.drop.forEach((group) => gatheredLess(group, keys));
  digest.items.set(options.group, [message, kind, act, options]);
  const dot = noticeDot(options.dot || '', SIDE_OPEN);
  if (dot) document.body.classList.add('dot-' + dot);
  return true;
}
// The gathering ends: nothing, the one thing as itself, or one message for all of them (digestNote) - behind what the line
// says already (back): what came meanwhile never takes the line from an undo or a hint the screen itself put there.
function digestEnd() {
  const digest = DIGEST;
  if (!digest) return;
  DIGEST = null;
  clearTimeout(digest.timer);
  const items = [...digest.items.values()];
  if (items.length === 1) digestReplay(items[0], true);
  else if (items.length) digestNote(digest.title, items);
}
// The words a gathered message is named by in the gathered line: its brief (o.brief), else its title. Pure.
function digestBrief(item: any[]): string {
  const options = item[3] || {};
  return options.brief || splitMessage(options.literal ? String(item[0]) : trMsg(item[0]))[0];
}
// The gathered line's description: each brief once, in the order they came, with how many - a brief that ends in a count
// ('새 핀 1', one per document) adds its count up ('새 핀 2'), any other counts how many said it ('나를 부름 2'). Pure.
function digestLine(briefs: string[]): string {
  const seen = new Map();
  briefs.forEach((brief) => {
    const match = /^(.*\S) (\d+)$/.exec(brief),
      name = match ? match[1] : brief,
      count = match ? +match[2] : 1,
      was = seen.get(name);
    seen.set(name, { n: (was ? was.n : 0) + count, counted: !!match || (was ? was.counted : false) });
  });
  return [...seen].map(([brief, tally]) => (tally.n > 1 || tally.counted ? brief + ' ' + tally.n : brief)).join(' · ');
}
function digestNote(title: string, items: any[][]) {
  items = [...items.filter((item) => !(item[3] || {}).back), ...items.filter((item) => !!(item[3] || {}).back)]; // this document's news first
  const dots = digestDots(items);
  const notice = lineNote(
    title + ' — ' + digestLine(items.map(digestBrief)),
    NOTICE_KIND.INFO,
    {
      label: '펼치기',
      tip: '모은 소식을 하나씩 상태 줄에 놓습니다',
      fn: () => {
        const all = notice ? notice.items || [] : [];
        all.forEach((item) => digestReplay(item, false));
        if (all.length > 1 && !$('#status-list').open) toggleStatusList();
      },
    },
    {
      literal: true,
      keep: true,
      back: true,
      dots,
      digest: false,
      onEnd: (acted, seen) => {
        if (!acted && notice) digestClosed(notice.items || [], seen);
      },
    },
  );
  if (notice) {
    notice.items = items;
    notice.digestTitle = title;
  }
}
// A gathered line went other than by [펼치기] (its [x]: seen): the groups it held end with it - each of their messages has
// gone, so what a group's end checks (no other new-pins message, updates.js) sees them gone - and then what each held for
// its end runs, as seen.
function digestClosed(items: any[][], seen: boolean) {
  items.forEach((item) => {
    const group = (item[3] || {}).group,
      entry = group ? GROUPS.get(group) : undefined;
    if (entry && !(entry.n && NOTICES.has(entry.n.n))) GROUPS.delete(group);
  });
  items.forEach((item) => {
    const ended = (item[3] || {}).onEnd;
    if (ended) ended(false, seen);
  });
}
// Puts gathered message a on the line as it would have come - behind what the line says (back), or, unfolded by [펼치기], in
// front; a group's message is that group's again.
function digestReplay(item: any[], back: boolean) {
  const options = item[3] || {},
    notice = lineNote(item[0], item[1], item[2], { ...options, digest: false, back: back || !!options.back });
  const entry = options.group && GROUPS.get(options.group);
  if (entry && notice) entry.n = notice;
}
// Takes group's gathered message out of a gathered line not yet unfolded, so the group's new event merges into it and is
// said on its own (groupNote); the line says what is left. Whether there was one.
function digestTake(group: string): boolean {
  for (const notice of NOTICES.values()) {
    const items = notice.items;
    if (!items) continue;
    const index = items.findIndex((item) => (item[3] || {}).group === group);
    if (index < 0) continue;
    items.splice(index, 1);
    digestRetitle(notice);
    return true;
  }
  return false;
}
// The chips the gathered messages items mark (digestNote's dots): each one's dot once. Pure but for SIDE_OPEN.
function digestDots(items: any[][]): string[] {
  return [...new Set(items.map((item) => noticeDot((item[3] || {}).dot || '', SIDE_OPEN)).filter(Boolean))];
}
// Gathered line n says what it holds now (digestTake, foldedLess, foldedGone): each brief once with how many, and the dots
// of those alone - one left stays a gathered line naming it - or, holding nothing more, it goes (nothing it held runs for
// its end: what took them out did).
function digestRetitle(notice: Notice) {
  const items = notice.items || [];
  if (!items.length) {
    notice.onEnd = null;
    endNotice(notice, true);
    return;
  }
  notice.dots = digestDots(items);
  const [title, description] = splitMessage(
    (notice.digestTitle || notice.title) + ' — ' + digestLine(items.map(digestBrief)),
  );
  notice.title = title;
  notice.desc = description;
  setStatusSig('');
  drawStatus();
}

// A CLICK message - a passing notice that is not an undo (a restored draft's [버리기]) - lasts until the next press somewhere
// else: a click (a tap, Enter on a button) outside it ends it; a scroll does not. The press that made it has passed by the time
// it exists. An undo is never CLICK (rule 2).
document.addEventListener(
  'click',
  (event) => {
    const target = event.target as HTMLElement;
    NOTICES.forEach((notice) => {
      if (notice.life !== NOTICE_LIFE.CLICK) return;
      const own =
        notice.place === NOTICE_PLACE.LINE
          ? !!(target.closest && target.closest('#status,#status-list'))
          : !!(notice.el && notice.el.contains(target));
      if (!own) endNotice(notice, false);
    });
  },
  true,
);

// One message's element, made once and kept on n.el (a redraw moves it, so a focus inside survives and an alert is not read
// out again): status icon, title and description (already in the UI language, so translate="no"), its action, and [x] -
// none on a chip, which goes by itself. ERR and WARN banners are alerts. A TIMER message holds while a mouse is on it - from
// a real movement over it (realMove), not from being drawn under a resting pointer - until the pointer leaves (armNotice).
function noticeElement(notice: Notice, className: string): HTMLElement {
  if (notice.el) return notice.el;
  const element = document.createElement('div');
  element.className = 'nt ' + className + ' nk-' + notice.kind;
  element.dataset.n = String(notice.n);
  if (notice.place === NOTICE_PLACE.BANNER && (notice.kind === NOTICE_KIND.ERR || notice.kind === NOTICE_KIND.WARN))
    element.setAttribute('role', 'alert');
  const chip = notice.place === NOTICE_PLACE.CHIP,
    title = chip && notice.label ? notice.label : notice.title,
    description = chip ? '' : notice.desc;
  setHtml(
    element,
    html`<span class="nt-ic">${noticeIcon(notice.kind)}</span><span class="nt-t" translate="no"><span class="nt-ti">${title}</span>${description ? html`<span class="nt-d">${description}</span>` : ''}</span><span class="nt-acts">${noticeButtons(notice, !chip)}</span>`,
  );
  if (chip)
    for (const eventType of ['pointerdown', 'mousedown'])
      element.addEventListener(eventType, (event) => event.stopPropagation()); // a press on the chip never starts a selection on the page under it
  if (notice.life === NOTICE_LIFE.TIMER) {
    element.addEventListener(
      'pointermove',
      (event) => {
        if (!notice.hover && realMove(event) && NOTICES.has(notice.n)) {
          notice.hover = true;
          armNotice(notice);
        }
      },
      { passive: true },
    );
    for (const eventType of ['pointerleave', 'pointercancel'])
      element.addEventListener(eventType, () => {
        if (notice.hover && NOTICES.has(notice.n)) {
          notice.hover = false;
          armNotice(notice);
        }
      });
  }
  notice.el = element;
  return element;
}
// A message's buttons: its action (with its description, if any; aria-busy while its request is out) and, with close, [x]
// named '알림 닫기'.
function noticeButtons(notice: Notice, close: boolean): Html {
  const action = notice.act,
    tip = action && action.tip ? html` data-tip="${action.tip}"` : '',
    busy = notice.busy ? html` aria-busy="true"` : '';
  return html`${action ? html`<button type="button" class="btn-sm btn-secondary nt-act" data-act="notice-act" data-n="${notice.n}"${tip}${busy}><span class="lbl">${tr(action.label)}</span></button>` : ''}\
${close ? html`<button type="button" class="btn-icon btn-sm btn-ghost nt-x" data-act="notice-x" data-n="${notice.n}" aria-label="알림 닫기">${ic('x')}</button>` : ''}`;
}

// The focused element inside a drawn message, if any: a redraw that detaches it gives the focus back (noticeRefocus).
function noticeFocus(): HTMLElement | null {
  const active = document.activeElement as HTMLElement | null;
  return active && active.closest && active.closest('.nt') ? active : null;
}
function noticeRefocus(focused: HTMLElement | null) {
  if (focused && document.contains(focused) && document.activeElement !== focused)
    focused.focus({ preventScroll: true });
}

// Banners in their hosts: the composer's above its save row, the review section's under its head (at the top of the list while
// that section is hidden), the Trash's above its list, the list's at its top. One already in place is not moved.
function drawBanners() {
  const focused = noticeFocus();
  BANNERS.forEach((notice, host) => {
    const element = noticeElement(notice, 'nt-banner'),
      inReview = host === NOTICE_HOST.REVIEW && !$('#sec-review').hidden;
    const parent =
      host === NOTICE_HOST.COMPOSER
        ? $('#c-actions')
        : host === NOTICE_HOST.TRASH
          ? $('#trash')
          : inReview
            ? $('#sec-review')
            : $('#list');
    const before =
      host === NOTICE_HOST.TRASH ? $('#trash-list') : inReview ? $('#review-pins') : parent.firstElementChild;
    if (element.parentNode !== parent || (before !== element && element.nextElementSibling !== before))
      parent.insertBefore(element, before === element ? element.nextElementSibling : before);
  });
  noticeRefocus(focused);
  syncSaveButton();
  tipFollow();
} // a banner moved (the review section hid: to the list's top) keeps its focus; what is under a banner moved down
// The composer's [핀 저장] reads [다시 저장] while its banner is a failed save (saveBtnLabel), and goes back after.
function syncSaveButton() {
  const button = $('#btn-save');
  if (!button || button.dataset.pending) return;
  const banner = BANNERS.get(NOTICE_HOST.COMPOSER),
    retry = !!(banner && banner.save);
  if ((button.dataset.retry === '1') !== retry) {
    if (retry) button.dataset.retry = '1';
    else delete button.dataset.retry;
    setHtml(button, saveBtnLabel());
  }
}
// A composer's banner belongs to its selection: when the composer closes (saved, cancelled), it goes with it.
new MutationObserver(() => {
  if ($('#composer').hidden) {
    const notice = BANNERS.get(NOTICE_HOST.COMPOSER);
    if (notice) endNotice(notice, false);
  }
}).observe($('#composer'), { attributes: true, attributeFilter: ['hidden'] });

// Rows in a card's place and notes in a card, after drawPins drew the list. A row waits until its card has left the section
// (away), then goes into the slot the list drew where its pin would stand in the list's order (cardRows: under its day line), or
// for a row made after that draw where placeRow puts it; once its pin is back in that section, what it offers to
// undo is undone and it goes - unless it holds a deferred send, whose card stays out until the send. A note goes above its
// card's buttons (or a done pin's row's end); a note whose card is not drawn moves to the status line (offerToLine).
// focus = what noticeFocus() saw before the redraw.
function drawOffers(focus?: HTMLElement | null) {
  NOTICES.forEach((notice) => {
    if (notice.place === NOTICE_PLACE.ROW) {
      const box = notice.sec === 'review' ? $('#review-pins') : $('#pins');
      if (box.querySelector('.pin.card[data-id="' + notice.pin + '"]')) {
        if (notice.away && !notice.gone) endNotice(notice, true);
        else if (notice.el) notice.el.remove();
        return;
      }
      notice.away = true;
      if (notice.sec === 'review') $('#sec-review').hidden = false; // its last card may just have left (drawPins keeps it shown too)
      const element = noticeElement(notice, 'nt-row'),
        slot = box.querySelector('.nt-slot[data-slot="' + notice.n + '"]');
      if (slot) slot.replaceWith(element);
      else if (element.parentElement !== box) placeRow(box, notice, element);
    } // one standing since the last draw has its place
    else if (notice.place === NOTICE_PLACE.CARD) {
      const card = document.querySelector(
        '#list .pin.card[data-id="' + notice.pin + '"],#list .arc-row[data-id="' + notice.pin + '"]',
      );
      if (!card) {
        offerToLine(notice);
        return;
      }
      const element = noticeElement(notice, 'nt-note'),
        actions = card.querySelector(':scope>.acts');
      if (actions) actions.before(element);
      else card.appendChild(element);
    }
  });
  noticeRefocus(focus || null);
}

// Chips on marks, after marks() drew them: on the pin's mark, kept on its page. A chip whose mark is not drawn (another
// document, a failed reload) moves to the status line - unless it waits for its first reload (pending) - and so does one
// that would sit under the select mode's bar (chipsClearOfBar).
function drawChips() {
  NOTICES.forEach((notice) => {
    if (notice.place !== NOTICE_PLACE.CHIP) return;
    const anchor = (document.querySelector('.mark[data-pin="' + notice.pin + '"]') ||
      document.querySelector('#doc .pv[data-pin="' + notice.pin + '"]')) as HTMLElement | null; // a page verdict line shows its pin instead of a mark
    if (!anchor) {
      if (!notice.pending) offerToLine(notice);
      return;
    }
    const focused = noticeFocus(),
      element = noticeElement(notice, 'nt-chip');
    if (element.parentNode !== anchor) anchor.appendChild(element);
    element.style.left = '';
    element.style.right = '';
    element.style.maxWidth = '';
    chipInRoom(element, anchor);
    noticeRefocus(focused);
  });
  chipsClearOfBar();
}
// Keeps a chip where it can be pressed: inside its page, inside what the PDF area shows, and clear of a panel laid over the
// PDF area (the unfolded foldable's overlay panel while composing). Where the room is narrower than the chip its words give
// way (ellipsis, .nt-t) - never its [되돌리기] - then it moves left until it fits. A page verdict line's chip stands in the
// line's row (notices.css), which already keeps out of all of that (sizePageLines): nothing to move.
function chipInRoom(chip: HTMLElement, anchor: HTMLElement) {
  if (anchor.classList.contains('pv')) return;
  const scroller = $('#left'),
    panel = $('#right'),
    box = (anchor.closest('.pg') || anchor).getBoundingClientRect(),
    scrollerRect = scroller.getBoundingClientRect();
  let right = Math.min(box.right, scrollerRect.left + scroller.clientWidth) - 4;
  const left = Math.max(box.left, scrollerRect.left) + 4,
    firstRect = chip.getBoundingClientRect();
  // A panel beside or over the PDF area - a column down its right side, not a bottom sheet (which starts at its left) -
  // bounds the chip at every height: the chip may be scrolled up beside it after it is drawn.
  if (panel && panel.getClientRects().length) {
    const panelRect = panel.getBoundingClientRect();
    if (panelRect.left > scrollerRect.left + 40) right = Math.min(right, panelRect.left - 4);
  }
  // ...and so does the panel's handle (#grip), whose touch area (::after, 44px on touch) reaches into the PDF area at the
  // panel's middle: a chip scrolled there had its [되돌리기] under the handle.
  const grip = $('#grip');
  if (grip && grip.getClientRects().length) {
    const gripRect = grip.getBoundingClientRect(),
      reach = Math.max(gripRect.width, parseFloat(getComputedStyle(grip, '::after').width) || 0);
    if (gripRect.left > scrollerRect.left + 40) right = Math.min(right, gripRect.right - reach - 4);
  }
  if (right - left <= 0) return;
  if (firstRect.width > right - left) chip.style.maxWidth = Math.floor(right - left) + 'px';
  const chipRect = chip.getBoundingClientRect(),
    over = chipRect.right - right,
    under = left - chipRect.left;
  if (over > 0) chip.style.left = Math.round(chip.offsetLeft - Math.min(over, chipRect.left - left)) + 'px';
  else if (under > 0) chip.style.left = Math.round(chip.offsetLeft + under) + 'px';
}
// Whether two boxes (left, top, right, bottom) overlap by more than a touching edge. Pure.
function boxesMeet(
  first: { left: number; top: number; right: number; bottom: number },
  second: { left: number; top: number; right: number; bottom: number },
) {
  return (
    first.left < second.right && second.left < first.right && first.top < second.bottom && second.top < first.bottom
  );
}
// A chip never sits under the select mode's bar (#sel-bar, over the top of the PDF area while the mode is on): one whose box
// meets the bar's - the mode turned on, or the page scrolled the mark up under it - takes its undo to the status line.
// Nothing is read while no chip is up, and while the area scrolls only once a frame (with placeChips): read on every scroll
// event it forced a layout each time - seconds of long tasks over a first scroll through a list of a hundred pins.
function chipsClearOfBar() {
  let any = false;
  NOTICES.forEach((notice) => {
    if (notice.place === NOTICE_PLACE.CHIP && notice.el) any = true;
  });
  if (!any) return;
  const bar = $('#sel-bar');
  if (!bar || !bar.getClientRects().length) return;
  const barRect = bar.getBoundingClientRect();
  NOTICES.forEach((notice) => {
    if (
      notice.place === NOTICE_PLACE.CHIP &&
      notice.el &&
      notice.el.getClientRects().length &&
      boxesMeet(notice.el.getBoundingClientRect(), barRect)
    )
      offerToLine(notice);
  });
}
// A page verdict line's chip with no room to stand in (verdict.js placeLineChips) takes its undo to the status line.
function chipAway(chip: HTMLElement) {
  NOTICES.forEach((notice) => {
    if (notice.el === chip && notice.place === NOTICE_PLACE.CHIP) offerToLine(notice);
  });
}
// Places every save chip on screen again by chipInRoom's rules, from its mark's or line's place now: after a zoom (setW) and,
// once a frame, while the PDF area scrolls either way - its place was set in px, so a zoomed page or a sideways scroll could
// leave [되돌리기] off the PDF area or under the panel or its handle.
function placeChips() {
  NOTICES.forEach((notice) => {
    const chip = notice.el,
      anchor = chip && chip.parentElement;
    if (notice.place !== NOTICE_PLACE.CHIP || !chip || !anchor || !chip.isConnected || anchor.classList.contains('pv'))
      return;
    chip.style.left = '';
    chip.style.right = '';
    chip.style.maxWidth = '';
    chipInRoom(chip, anchor);
  });
}
let CHIP_FRAME = 0;
$('#left').addEventListener(
  'scroll',
  () => {
    if (!CHIP_FRAME)
      CHIP_FRAME = requestAnimationFrame(() => {
        CHIP_FRAME = 0;
        placeChips();
        chipsClearOfBar();
      });
  },
  { passive: true },
);
new MutationObserver(chipsClearOfBar).observe(document.body, { attributes: true, attributeFilter: ['class'] }); // body.selmode comes and goes
// The list reload after a save or an append has run: a chip whose mark did not come goes to the status line (drawChips).
function settleChip(notice: Notice | null) {
  if (!notice || !NOTICES.has(notice.n) || notice.place !== NOTICE_PLACE.CHIP) return;
  notice.pending = false;
  drawChips();
}
// Moves an undo whose place left the screen to the status line, with the same action, what it holds (gone) and life; a TIMER
// one gets a window of its own there. A pressed one (busy: its request is out) does not move - it is offered nowhere else,
// and goes when the request is answered (noticeAct); the place it left was its own doing (a save's chip and its mark).
function offerToLine(notice: Notice) {
  if (notice.busy) return;
  const act = notice.act,
    gone = notice.gone;
  notice.gone = null;
  endNotice(notice, true);
  if (!act) return;
  // Its title and description stay as they were split: joined back with ' · ' a title that holds one ('#6 채택 판정 저장됨 · PL16')
  // was cut at it on the line.
  const moved = lineNote(notice.desc ? notice.title + ' — ' + notice.desc : notice.title, NOTICE_KIND.OK, act, {
    life: notice.life,
    gone,
    literal: true,
    undo: true,
    quiet: true,
  }); // said when it came: not again as it moves
  DEFERRED.forEach((send) => {
    if (send.note === notice) send.note = moved;
  });
} // an early send takes the moved undo away

// Trash rows: an undo in the place of the row it took away (after the row drawn before it, or first). drawTrash calls this.
function drawTrashOffers() {
  const box = $('#trash-list');
  NOTICES.forEach((notice) => {
    if (notice.place !== NOTICE_PLACE.TRASH) return;
    const element = noticeElement(notice, 'nt-row'),
      previous = notice.prev != null ? box.querySelector('.arc-row[data-id="' + notice.prev + '"]') : null;
    if (previous) previous.after(element);
    else box.prepend(element);
  });
}
// Closing the Trash takes its rows' undos to the status line: inside a closed dialog they could no longer be pressed.
$('#trash').addEventListener('close', () => {
  NOTICES.forEach((notice) => {
    if (notice.place === NOTICE_PLACE.TRASH) offerToLine(notice);
  });
});

// Deferred send with an undo (docs/handbook/viewer.md §알림 자리): commit runs when its undo leaves - after NOTICE_MS, on [x],
// or when the page is hidden - and [되돌리기] (cancel) runs undo instead, before anything reaches the server. So an agent never
// sees a reply or a permanent delete that was taken back. note = the undo drawn for it, which an early commit takes away. Its
// own bound is the guard: whatever holds or moves its undo, it is sent NOTICE_MS + NOTICE_HOLD_MAX after it was made at the
// latest. Runs once, cancels once, never both.
const DEFERRED = new Set() as Set<Deferred>;
function deferred(commit: () => void, undo: () => void): Deferred {
  let done = false;
  const bound = setTimeout(() => send.run(), NOTICE_MS + NOTICE_HOLD_MAX);
  const send = {
    note: null,
    run: () => {
      if (done) return;
      done = true;
      clearTimeout(bound);
      DEFERRED.delete(send);
      if (send.note) endNotice(send.note, true);
      commit();
    },
    cancel: () => {
      if (done) return;
      done = true;
      clearTimeout(bound);
      DEFERRED.delete(send);
      undo();
    },
  } as Deferred;
  DEFERRED.add(send);
  return send;
}
// Draws deferred send d's undo (undoNote, a TIMER life): its end sends, its [되돌리기] cancels. Returns it.
function deferredNote(send: Deferred, place: string, message: string, options: Partial<Notice>): Notice {
  const notice = undoNote(
    place,
    message,
    { label: '되돌리기', tip: '보내기 전에 취소합니다', fn: send.cancel },
    { ...options, life: NOTICE_LIFE.TIMER, gone: send.run },
  );
  send.note = notice;
  return notice;
}
// The page is hidden or closed: what waits is sent now (fetch keepalive), and its undo goes - it could no longer cancel.
function flushDeferred() {
  Array.from(DEFERRED).forEach((send) => send.run());
}
window.addEventListener('pagehide', flushDeferred);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) flushDeferred();
});
export {
  BANNERS,
  DIGEST,
  GROUPS,
  LINE,
  NOTICES,
  NOTICE_ACT_WAIT,
  NOTICE_HOLD_MAX,
  NOTICE_LATE_SRC,
  NOTICE_MS,
  announce,
  bannerNote,
  chipAway,
  deferred,
  deferredNote,
  digestBegin,
  digestSoon,
  drawBanners,
  drawChips,
  drawOffers,
  drawTrashOffers,
  drawnBefore,
  dropStaleReview,
  endNotice,
  endTopic,
  flushDeferred,
  focusRun,
  groupNote,
  groupRedraw,
  holdLine,
  lineNote,
  lineVisible,
  noticeAct,
  noticeButtons,
  noticeClose,
  noticeFocus,
  noticeIcon,
  noticeSeen,
  offersIn,
  placeChips,
  quietNote,
  settleChip,
  sourceEntry,
  sourceOk,
  undoNote,
};
