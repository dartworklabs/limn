// ------------------------------------------------ Verdict pins (docs/handbook/viewer.md §판정 핀, domain.md §판정 핀)
// A document may declare verdict words (its word file, served as `verdicts` on /api/docs and the full /api/meta). A
// verdict pin is a pin saved with one of them (`verdict`); its verdict and target are fixed when it is made. The viewer
// offers the words in two places: the composer's verdict row (#c-verdict-row), which saves the selection and its note
// as that verdict, and - on a figure document or a view-only PDF whose word file says page: true - a page verdict line,
// which saves a verdict about the page's whole target and never touches the composer. The words are the manuscript's:
// they are drawn as text, translate="no", and the names around them are put in the screen's language here.
import {
  DEFAULT_DOC,
  DOC,
  DOCS,
  DONE,
  DONE_ALL,
  KIND_NEW,
  LAYOUT,
  META,
  COARSE_POINTER_QUERY,
  OPEN_ALL,
  PINS,
  REPLY,
  REVIEW_ALL,
  captureVisit,
  currentVisit,
  imeKey,
  isFigureKind,
  isViewOnlyKind,
  COMPOSE,
  EDITOR,
  setComposeRetryVerdict,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { errText, translateTemplate, translate, TIP_TEXT, josa } from '../platform/i18n.ts';
import { SECTION_SEEN } from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import {
  BANNERS,
  NOTICES,
  NOTICE_ACT_WAIT,
  NOTICE_HOLD_MAX,
  NOTICE_MS,
  announce,
  bannerNote,
  chipAway,
  lineNote,
  noticeAct,
  settleChip,
  sourceOk,
  undoNote,
} from '../platform/notices.ts';
import { SWALLOW_CLICK, hideTip } from '../platform/tooltip.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { arrivePage, figureTop, pdfAreaInnerWidth } from '../pdf/view-pages.ts';
import { SCROLL_KEYS, readingDepth } from '../pdf/view-outline.ts';
import { setSide, topAnchor } from '../layout/flow.ts';
import { isElementLost, figureFields, isFrac, pinPlace } from '../pdf/view-figure.ts';
import { SUGGEST_DRAFT } from '../composer/flow-suggest.ts';
import { savePin } from '../composer/flow-save.ts';
import {
  LAST_KEY_SAVE,
  REASON_SESSION,
  WITHDRAWN_PINS,
  focusLine,
  isReasonField,
  isKeyGuarded,
  fillReasonField,
  refocusAfterLines,
  followSaveWithReason,
  hasUnsavedReason,
  openReadingReason,
  inlineReason,
  leaveReason,
  isReasonOpenOn,
  reasonPopoverHtml,
  reviveReason,
  settleDetachedReason,
  syncReasonSession,
  keepUnboundReason,
  bringBackReason,
  placeFailedCancelDraft,
  settleFailedCancelDraft,
  getDraft,
  putDraft,
  setKeyGuard,
  setReasonSession,
} from './flow-reason.ts';
import {
  HELD_READING_PAGE,
  BUILD_READING_PAGE,
  IS_BESIDE_PAGES,
  bringPage,
  flashPanelOn,
  heldReadingPage,
  markStops,
  ensurePanel,
  fillPanel,
  fitPanel,
  removePanel,
  heldPanelPage,
  placePanel,
  isPanelStale,
  applyBeside,
  redrawOnBesideChange,
  settleBesideTurn,
  startBesideTurn,
  finishBesideTurn,
  shouldStandBeside,
  markReadingSummary,
  drawSummaries,
} from './view-panel.ts';
import { claimActive, josaToward } from '../pins/view-card-parts.ts';
import { relSpan } from '../pins/view-cards.ts';
import { PINS_APPLIED_SEQ, loadPins } from '../pins/flow-list.ts';
import { CONFIRMING, CONFIRMING_PIN, dropPin, restorePin } from '../pins/flow-actions.ts';
import { refreshDoc } from '../documents/flow-rebuild.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_LIFE, NOTICE_PLACE } from '../platform/tables.ts';
import { $, $$, typingNow, searchToPage } from '../platform/dom.ts';
import { ASSIGNEE_AGENT, REQUEST_KIND, LAYOUT_MODE, PIN_STATE, ROLE, VERDICT_PLACE } from '../app/rules-tables.ts';
import { pinState, verdictOf, lineRange } from '../app/rules-pins.ts';
import { who, isMe } from '../app/state-people.ts';
import {
  isRegion,
  pdoc,
  docVerdicts,
  verdictLabel,
  docKindOf,
  viewerBlocked,
  pageVerdictsOn,
} from '../documents/state.ts';
import {
  arrivalWatch,
  LAST_SCROLL_AT,
  HAND_SCROLL_AT,
  JUMP_TARGET,
  HAND_ON_PAGES,
  endJumpForScroll,
  setJumpTarget,
  isAutoScrolling,
  scrollTopFor,
  glideInto,
  setGliding,
  setLastScrollAt,
} from '../layout/flow-scroll.ts';

const VERDICT_ARM_MS = 4000; // how long a confirm word's first press waits for its second (D9)
// Whether this screen may make a verdict pin: a person who edits (a viewer reads, an agent never makes one, D11).
function canVerdict() {
  const role = META && META.me && META.me.role;
  return role !== ROLE.VIEWER && role !== ROLE.AGENT;
}
// A card's verdict badge, '판정 채택' (the question badge's shape; the words carry the meaning, no colour of its own),
// or null.
function verdictBadge(pin: Pin) {
  const key = verdictOf(pin);
  if (!key) return null;
  return html`<span class="badge badge-verdict" data-tip="${translate('버튼으로 고른 판정입니다. 판정과 대상은 바뀌지 않고 메모만 고칠 수 있습니다')}">${translate('판정')} <span class="vd-w" translate="no">${verdictLabel(key, pdoc(pin))}</span></span>`;
}

// A verdict card's target by name, so a person finds the figure they gave a verdict: on a figure document the figure it
// is about (figureRootOf) - its title in the map ('[후보] PL26 · …') while the page it is on still shows it, else '그림
// <id>'. null for any other pin or document: a view-only PDF's page and a LaTeX range are in the card's head already.
function verdictTarget(pin: Pin) {
  if (!verdictOf(pin) || !isFigureKind(docKindOf(pdoc(pin)))) return null;
  const root = figureRootOf(pin);
  if (!root) return null;
  const page = figurePageOf(root, pin),
    facts = page && META && (!DOC || pdoc(pin) === DOC) ? META.pages[page - 1] : null,
    title = facts && facts.figure === root && facts.title ? facts.title : '';
  return html`<span class="vd-target" translate="no" data-tip="${translateTemplate('판정 대상 그림 · {id}', { id: root })}">${title || translateTemplate('그림 {id}', { id: root })}</span>`;
}
// A card's pin with the overlaps its card reports: a verdict pin's overlap with another verdict pin is left out where
// the page verdict line shows both - the pins of the document on screen whose words say page: true, counted on the same
// page's line ('#4와 같은 범위' between two verdicts on one figure only repeats the order the line gives). Anywhere no
// line replaces it (page false, no usable word file, a card of another document under [모든 문서]) the badge stays, as
// do a verdict pin's overlaps with ordinary pins and ordinary pins' own. The pin itself, or a copy with the shorter
// rel.
function dropPageLineOverlaps(pin: Pin): Pin {
  if (!verdictOf(pin) || !pin.rel || !pin.rel.length || (DOC && pdoc(pin) !== DOC) || !pageVerdictsOn()) return pin;
  const target = pageTargetOf(pin, META ? META.kind : undefined),
    list = target ? pageVerdictPins().get(target.page) || [] : [];
  if (!list.some((x) => x.id === pin.id)) return pin;
  const rel = pin.rel.filter((x) => !list.some((linePin) => linePin.id === x.id));
  return rel.length === pin.rel.length ? pin : { ...pin, rel };
}

// ---------------- The page's whole target (domain.md §쪽 전체 대상)
const WHOLE_PAGE = [0, 0, 1, 1];
// The figure a figure document's pin is about: the root of its element's path (el.path[0]). A figure document is one
// figure a page, so a pin on any of its elements is about that figure (ADR-0022 D1). null without an element path.
function figureRootOf(pin: Pin): string | null {
  const element = pin.el,
    root = element && Array.isArray(element.path) ? element.path[0] : null;
  return typeof root === 'string' && root ? root : null;
}
// The page figure `root` is on now: by the map's page facts (meta pages[].figure) for the document on screen - null
// when the build's map does not have that figure - else, without those facts (another document, a map that does not
// load), the page the pin's element is on in this build unless the build lost it.
function figurePageOf(root: string, pin: Pin): number | null {
  const pages = META && (!DOC || pdoc(pin) === DOC) && Array.isArray(META.pages) ? META.pages : null;
  if (pages && pages.some((x) => typeof x.figure === 'string')) {
    const index = pages.findIndex((x) => x.figure === root);
    return index >= 0 ? index + 1 : null;
  }
  return isElementLost(pin) ? null : pinPlace(pin).page;
}
// Whether page `page` of the document on screen takes a verdict: every page but one its figure map marks verdict: false
// (a list, a question or a removed-figure page) - no page line, no composer verdict there.
function pageTakesVerdict(page: number) {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null;
  return !(facts && facts.verdict === false);
}
// What a pin's verdict is about when it is a page's whole target, and on which page it is now: on a figure document the
// figure its element belongs to (figureRootOf: el.path[0], whatever element of it the pin names), on the page that
// figure is on now (figurePageOf); on a view-only PDF a region pin over the whole page (each frac value within 1e-6 of
// [0, 0, 1, 1]) placed on this PDF (est false). null for any other pin, and always on a LaTeX document. Pure but for
// the page lookups.
function pageTargetOf(pin: Pin, kind: string | undefined): { page: number; id: string } | null {
  if (isFigureKind(kind)) {
    const root = figureRootOf(pin),
      page = root ? figurePageOf(root, pin) : null;
    return root && page ? { page, id: root } : null;
  }
  if (!isViewOnlyKind(kind) || !isRegion(pin) || pin.est === true || !isFrac(pin.frac)) return null;
  const frac = pin.frac;
  return frac.every((value, index) => Math.abs(value - WHOLE_PAGE[index]) <= 1e-6)
    ? { page: pin.page, id: 'page ' + pin.page }
    : null;
}
// The target a verdict pin is about, as far as its stored place says it without a project's rules: the page's whole
// target (pageTargetOf: a figure document's figure, a view-only PDF's whole page) - the page line's targets; else, on a
// figure document, still its figure (el.path[0]) when the page it is on cannot be told (the figure left the map): one
// order, on no line; else, on a document that takes line pins (LaTeX, Markdown), its exact lines (file and range)
// unless their anchor is lost (stale). A key that pins about the same thing share, with whether it is a whole page's;
// null when the target cannot be resolved (a PDF region that is not its whole page, a figure pin without an element
// path, a lost line). Lines are only a candidate: the server re-matches an open pin's lines to the text now, never a
// closed one's, so two pins with the same key are about the same lines only when both are open or both were saved on
// the same text (sameLines).
function verdictTargetOf(pin: Pin, kind: string | undefined): VerdictTarget | null {
  const target = pageTargetOf(pin, kind);
  if (target) return { key: 'whole ' + target.id, whole: true, page: target.page, lines: null };
  if (isFigureKind(kind)) {
    const root = figureRootOf(pin);
    return root ? { key: 'whole ' + root, whole: false, page: pin.page, lines: null } : null;
  }
  if (
    !isViewOnlyKind(kind) &&
    !isRegion(pin) &&
    pin.file &&
    typeof pin.lo === 'number' &&
    typeof pin.hi === 'number' &&
    !pin.stale
  )
    return {
      key: 'lines ' + pin.file + ':' + pin.lo + '-' + pin.hi,
      whole: false,
      page: pin.page,
      lines: { open: pinState(pin) === PIN_STATE.OPEN, anchor: anchorKey(pin) },
    };
  return null;
}
// A line pin's anchor - the text of its first and last lines when it was saved or last re-matched - as one string, or
// null. It is JSON with every object's keys in one order (jsonSortedKeys), so two anchors are one string exactly when
// they are the same JSON value, as the server's anchor_key compares them (limn.pins.verdict): a hand-edited offset that
// is an object is one whatever order its keys were written in, and the list [0] and the string "[0]", or true and 1,
// stay apart.
function anchorKey(pin: Pin): string | null {
  const anchor = pin.anchor;
  return anchor && typeof anchor.head === 'string' && typeof anchor.tail === 'string'
    ? JSON.stringify([anchor.head, anchor.tail, anchor.head_off, anchor.tail_off], jsonSortedKeys)
    : null;
}
// A JSON.stringify replacer that writes each object with its keys sorted - after the integer-like keys, which a
// JavaScript object always puts first in their numeric order - and an array or any other value as it is.
function jsonSortedKeys(_key: string, value: unknown): unknown {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return value;
  const object = value as Record<string, unknown>;
  return Object.fromEntries(
    Object.keys(object)
      .sort()
      .map((key) => [key, object[key]]),
  );
}
// Whether two pins on the same file and line numbers are about the same lines: both open (their lines are matched to
// the text now), or both saved on the same text (one anchor). A closed pin's numbers may be from an older text; without
// a shared anchor it is only its own target - never superseded, never another pin's current verdict.
function sameLines(first: VerdictTarget, second: VerdictTarget) {
  const x = first.lines,
    y = second.lines;
  return !x || !y || (x.open && y.open) || (!!x.anchor && x.anchor === y.anchor);
}
let VERDICT_ORDER_CACHE = { lists: [], by: new Map() } as { lists: unknown[]; by: Map<string, VerdictOrder> };
// The verdict order of document doc (D4, docs/handbook/domain.md §순서): its verdict pins that are not deleted - open,
// awaiting review (one whose [확인] waits for its undo too: it leaves the review list at once, but it is still a
// verdict, while the list still has it - applyPinLists) and done - by resolved target (verdictTargetOf), newest
// (largest number) first, and for every pin its current verdict: its target's newest pin (on lines, the newest that
// sameLines says is about the same lines). The page verdict line (pageVerdictPins) and a card's '이전 판정' marker
// (verdictSuperseder) both read this one order, so they never disagree. Built once per change of the lists (an index,
// not a scan per card).
function verdictOrder(doc: string): VerdictOrder {
  const lists = [OPEN_ALL, REVIEW_ALL, DONE_ALL, CONFIRMING_PIN.size, META && META.kind, DOCS];
  if (
    VERDICT_ORDER_CACHE.lists.length !== lists.length ||
    VERDICT_ORDER_CACHE.lists.some((x, index) => x !== lists[index])
  )
    VERDICT_ORDER_CACHE = { lists, by: new Map() };
  const hit = VERDICT_ORDER_CACHE.by.get(doc);
  if (hit) return hit;
  const kind = docKindOf(doc),
    groups = new Map() as Map<string, { t: VerdictTarget; all: { p: Pin; t: VerdictTarget }[] }>,
    seen = new Set();
  for (const pin of OPEN_ALL.concat(REVIEW_ALL, DONE_ALL, [...CONFIRMING_PIN.values()])) {
    if (seen.has(pin.id) || pdoc(pin) !== doc || !verdictOf(pin)) continue;
    seen.add(pin.id);
    const target = verdictTargetOf(pin, kind);
    if (!target) continue;
    const group = groups.get(target.key) || { t: target, all: [] };
    group.all.push({ p: pin, t: target });
    groups.set(target.key, group);
  }
  const out = { groups: new Map(), cur: new Map() } as VerdictOrder;
  groups.forEach((group, key) => {
    group.all.sort((left, right) => right.p.id - left.p.id);
    group.all.forEach((x) => {
      const current = x.t.lines ? group.all.find((y) => y === x || sameLines(x.t, y.t)) : group.all[0];
      out.cur.set(x.p.id, (current || x).p);
    });
    const wholeEntry = group.all.find((x) => x.t.whole); // a whole target's page: the newest pin's that has one
    out.groups.set(key, {
      whole: !!wholeEntry,
      page: wholeEntry ? wholeEntry.t.page : group.t.page,
      pins: group.all.map((x) => x.p),
    });
  });
  VERDICT_ORDER_CACHE.by.set(doc, out);
  return out;
}
// The verdict pins about each page's whole target on the document on screen, in the verdict order (verdictOrder), by
// page. A page whose pins name two figures (a re-render moved one away) keeps the figure of its newest pin.
function pageVerdictPins(): Map<number, Pin[]> {
  const out = new Map() as Map<number, Pin[]>;
  verdictOrder(DOC || DEFAULT_DOC).groups.forEach((group) => {
    if (!group.whole) return;
    const had = out.get(group.page);
    if (!had || had[0].id < group.pins[0].id) out.set(group.page, group.pins);
  });
  return out;
}
// The current verdict that supersedes a verdict pin - the newest verdict about its target when that is another pin - or
// null: the pin is the current one, not a verdict pin, or its target cannot be resolved.
function verdictSuperseder(pin: Pin): Pin | null {
  if (!verdictOf(pin)) return null;
  const current = verdictOrder(pdoc(pin)).cur.get(pin.id);
  return current && current.id !== pin.id ? current : null;
}
// A card's marker for a superseded verdict: '이전 판정 · #4로 대체됨', the number a link (the viewer's link look) to
// the current verdict's card. Neutral: a badge with no colour of its own - the words carry it. null for a current
// verdict or another pin.
function verdictOldMarker(pin: Pin) {
  const cur = verdictSuperseder(pin);
  if (!cur) return null;
  const mark = '\u0001',
    id = cur.id;
  const parts = translateTemplate('이전 판정 · {ref}{p} 대체됨', { ref: mark, p: josaToward(id) }).split(mark);
  const description = translateTemplate(
    '같은 대상에 더 새 판정 #{id}{p} 있습니다 — 에이전트는 가장 새 판정만 실행합니다',
    {
      id,
      p: josa(id, '이', '가'),
    },
  );
  return html`<span class="badge vd-old" role="note" aria-label="${description}" data-tip="${description}">${parts[0]}<span class="pin-ref vd-old-ref hit" role="link" tabindex="0" \
data-act="pin-ref" data-ref="${id}" aria-label="${translateTemplate('지금 판정 #{id} 카드로 갑니다', { id })}">#${id}</span>${parts[1] || ''}</span>`;
}
// The ids of the pins a page verdict line shows now (drawPageVerdicts): their page-size mark is not drawn and their
// card's [보기] goes to the line (marks, jumpPin).
let SHOWN_ON_PAGE_LINES = new Set() as Set<number>;
let KEYED_PAGE = 0; // the page whose line the keys 1-5 act on (keyedPageFor), 0 for none
// A pin's state on the line: what the dot would say, in the line's words. The pin is the page target's newest verdict.
function verdictStateWord(pin: Pin) {
  const state = pinState(pin);
  if (state === PIN_STATE.REVIEW || CONFIRMING.has(pin.id)) return translate('검토 대기');
  if (state === PIN_STATE.DONE) return translate('처리됨');
  return claimActive(pin) ? translate('처리 중') : translate('처리 대기');
}

// ---------------- Two presses for a confirm word (D9)
// The armed first press: the word, where (VERDICT_PLACE) and - on a page line - the page, with the document, build and
// (in the composer) selection it is bound to; null when nothing is armed.
let ARMED_VERDICT = null as {
  key: string;
  label: string;
  where: string;
  page: number;
  doc: string | null;
  build: string;
  sel: string;
  kbd: boolean;
  timer: ReturnType<typeof setTimeout>;
} | null;
// What the composer's selection is, for the binding: its page, lines, rung, box and element.
function selectionBindingKey() {
  const selection = COMPOSE.current;
  return selection
    ? JSON.stringify([
        selection.page,
        selection.lo,
        selection.hi,
        selection.scope,
        selection.frac,
        selection.elSel && selection.elSel.id,
      ])
    : '';
}
// Whether the armed press is this word's button.
function isArmedHere(key: string, where: string, page: number) {
  const armed = ARMED_VERDICT;
  return (
    !!armed && armed.key === key && armed.where === where && (where === VERDICT_PLACE.COMPOSER || armed.page === page)
  );
}
// Whether an armed press still holds: the same document, build and (in the composer) selection.
function armStillHolds(armed) {
  return (
    armed.doc === DOC &&
    !!META &&
    armed.build === META.pages_build &&
    (armed.where !== VERDICT_PLACE.COMPOSER || armed.sel === selectionBindingKey())
  );
}
// What an armed word says while it waits, with how long it waits: '삭제 — 4초 안에 한 번 더 누르면 저장합니다'.
function armedWaitText(label: string) {
  return translateTemplate('{word} — {sec}초 안에 한 번 더 누르면 저장합니다', {
    word: label,
    sec: VERDICT_ARM_MS / 1000,
  });
}
// Arms word key's button: it reads '<낱말> 확정' for VERDICT_ARM_MS, a screen reader hears that the next press saves
// and within how long (armedWaitText), and a page line says so beside it (pageLineHtml .pv-arm). kbd: armed by a key
// (verdictKey), which also lets it go when the reading page changes (stickReadingLine).
function armVerdict(key: string, where: string, page: number, label: string, kbd?: boolean) {
  disarmVerdict(false);
  ARMED_VERDICT = {
    key,
    label,
    where,
    page,
    doc: DOC,
    build: META ? META.pages_build : '',
    sel: where === VERDICT_PLACE.COMPOSER ? selectionBindingKey() : '',
    kbd: !!kbd,
    timer: setTimeout(() => disarmVerdict(true, true), VERDICT_ARM_MS),
  };
  redrawVerdictButtons(where);
  announce(armedWaitText(label));
}
// Lets an armed press go (Esc, another press, a press elsewhere, a new selection, document or build, the time running
// out). Nothing keeps saying it waits: when it goes by itself, by Esc or by a press elsewhere (say) a screen reader
// hears so - '삭제 확정을 풀었습니다' replaces '… 한 번 더 누르면 저장합니다' -, and otherwise (its second press saves,
// a new document or build) that sentence is taken out of the live region; a description box still up for it closes.
function disarmVerdict(redraw: boolean, say?: boolean) {
  const armed = ARMED_VERDICT;
  if (!armed) return;
  clearTimeout(armed.timer);
  ARMED_VERDICT = null;
  if (redraw) redrawVerdictButtons(armed.where);
  hideTip();
  if (say) announce(translateTemplate('{word} 확정을 풀었습니다', { word: armed.label }));
  else {
    const liveRegion = $('#sr-news');
    if (liveRegion && liveRegion.textContent === armedWaitText(armed.label)) liveRegion.textContent = '';
  }
}
function redrawVerdictButtons(where: string) {
  if (where === VERDICT_PLACE.COMPOSER) renderVerdictRow();
  else drawPageVerdicts();
}
// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else. The click a long press's
// release ends with is no press (platform/tooltip.ts swallows it after this, on the document): it lets nothing go, nor
// closes the description the long press showed.
window.addEventListener(
  'click',
  (event) => {
    if (!ARMED_VERDICT || Date.now() < SWALLOW_CLICK) return;
    const button = (event.target as HTMLElement).closest(
      '[data-act="verdict-save"],[data-act="pv-save"]',
    ) as HTMLElement | null;
    if (!(button && isArmedHere(button.dataset.key || '', whereOfButton(button), Number(button.dataset.page) || 0)))
      disarmVerdict(true, true);
  },
  true,
);
window.addEventListener(
  'keydown',
  (event) => {
    if (event.key !== 'Escape' || !ARMED_VERDICT || imeKey(event)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    disarmVerdict(true, true);
  },
  true,
);
function whereOfButton(button: HTMLElement) {
  return button.dataset.act === 'verdict-save' ? VERDICT_PLACE.COMPOSER : VERDICT_PLACE.PAGE;
}

// One word's button: outline, a confirm word's text in the danger colour, '<낱말> 확정' while armed. The word is the
// manuscript's, so the button is translate="no" and its name is put in the screen's language here. In the composer it
// saves (its name says what about: '채택 판정으로 저장 — 3쪽'; its description, that the selection and note become that
// verdict's pin at once). On a page line it is a toggle: `pressed` says its state (PRESSED_AS) - the line's current
// verdict, or the word a save on the line is for, is pressed (aria-pressed, a filled look; a confirm word the
// destructive fill) - and its name stays '채택 판정 — 3쪽' whichever it is. Its description says what a press does: an
// unpressed word saves that verdict (the current one is replaced), the pressed one takes the person's own open verdict
// back (as [판정 취소]), and a pressed one that is not theirs or is handled says why it is not taken back here. The
// word a save is for (SAVING) keeps its box's words but gives a screen reader none (an empty aria-description, which
// platform/tooltip.ts leaves as the drawing code's): the line's status (.pv-busy, role=status) says the save, once. A
// click presses the word and focuses it at the same moment, and a screen reader reads a description that changes then
// twice, with the focus and as a change, before the status. Off: a composer's button is disabled; a page line's waits
// (aria-disabled, verdictPress ignores it) before the first list, and right after its word was taken back
// (TAKEN_BACK_HOLD) - it keeps the focus a keyboard press left on it, which a disabled button would drop to the page.
// keyNumber: on the line of the page the keys act on (KEYED_PAGE), the word's key 1-5 - drawn after the word as a key
// hint (data-kn, generated text on a mouse screen only, so the button's text stays the word) and, on that screen only
// (KEY_MARK_SCREEN), said in its description and as aria-keyshortcuts; 0 elsewhere. quiet: drawn without its
// description (data-tip) - a page line whose save chip stands (pageLineHtml) - so no description box comes over the
// chip; the name and the keys are still said. A page line's armed word ('삭제 확정') has no description either: its box
// would cover the line's figure name while the word waits for its second press, the button already reads what the box
// would say, and the line says how long it waits beside it (.pv-arm). Either keeps it for a long press (data-tip-press,
// platform/tooltip.ts): hover and focus raise no box, but a long press shows it and its release presses nothing, as on
// a word at rest - so a long press never takes the pressed word's verdict back while a chip or the reason popover is
// up, nor saves the armed word. The screen that draws the key marks (components.css .vd-b[data-kn]::after): a mouse's.
// Only there does a word's description end in '단축키 1' and its button carry aria-keyshortcuts, so a phone's long
// press never names a key it has none of. The lines are drawn again when that changes (a tablet's keyboard cover with
// its touchpad taken off), so the description follows the marks.
const KEY_MARK_SCREEN = matchMedia('(hover:hover) and (pointer:fine)');
KEY_MARK_SCREEN.addEventListener('change', () => {
  if (META) drawPageVerdicts();
});
function verdictButton(
  choice: VerdictChoice,
  where: string,
  page: number,
  target: string,
  off: boolean,
  keyNumber?: number,
  quiet?: boolean,
  pressed?: number,
) {
  const armed = isArmedHere(choice.key, where, page),
    line = where !== VERDICT_PLACE.COMPOSER,
    on = line && !!pressed && !armed;
  const said = !!keyNumber && KEY_MARK_SCREEN.matches; // the key said as well as drawn
  const name = armed
    ? translateTemplate('{word} 확정 — {sec}초 안에 한 번 더 누르면 저장합니다', {
        word: choice.label,
        sec: VERDICT_ARM_MS / 1000,
      })
    : line
      ? translateTemplate('{word} 판정 — {target}', { word: choice.label, target })
      : translateTemplate('{word} 판정으로 저장 — {target}', { word: choice.label, target });
  const forFigure = where === VERDICT_PLACE.COMPOSER && !!figureVerdictRoot(COMPOSE.current);
  let tip = armed
    ? name
    : forFigure
      ? translateTemplate('누르면 메모와 함께 이 그림 전체({target})의 {word} 판정 핀으로 바로 저장합니다', {
          word: choice.label,
          target,
        })
      : where === VERDICT_PLACE.COMPOSER
        ? translateTemplate('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다', { word: choice.label })
        : pressed === PRESSED_AS.MINE
          ? translate('지금 판정입니다 · 다시 누르면 이 판정을 거둡니다(판정 취소)')
          : pressed === PRESSED_AS.OTHER
            ? translate('지금 판정입니다 · 다른 사람의 판정이라 여기서 거두지 않습니다')
            : pressed === PRESSED_AS.HANDLED
              ? translate('지금 판정입니다 · 처리된 판정이라 카드의 [지우기]로 거둡니다')
              : pressed === PRESSED_AS.SAVING
                ? translate('이 판정을 저장하는 중입니다')
                : translate('누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다');
  if (said)
    tip += ' · ' + translateTemplate(choice.confirm ? '단축키 {key} (두 번)' : '단축키 {key}', { key: keyNumber });
  return html`<button type="button" class="vd-b hit${choice.confirm ? ' vd-confirm' : ''}${armed ? ' armed' : ''}" translate="no" data-act="${where === VERDICT_PLACE.COMPOSER ? 'verdict-save' : 'pv-save'}" \
data-key="${choice.key}" data-page="${page}" aria-label="${name}"${line ? html` aria-pressed="${on ? 'true' : 'false'}"` : ''}${on && pressed !== PRESSED_AS.SAVING ? html` aria-describedby="pv-on-${page}"` : ''}${on && pressed === PRESSED_AS.SAVING ? html` aria-description=""` : ''}\
${quiet || (armed && line) ? html` data-tip-press="${tip}"` : html` data-tip="${tip}"`}${keyNumber ? html` data-kn="${keyNumber}"` : ''}${said ? html` aria-keyshortcuts="${keyNumber}"` : ''}${off ? (line ? html` aria-disabled="true"` : html` disabled`) : ''}>\
${on ? lucideIcon('check') : ''}<span class="lbl">${armed ? translateTemplate('{word} 확정', { word: choice.label }) : choice.label}</span></button>`;
}
// A page line's word state (verdictButton's `pressed`): not pressed, or pressed as the person's own open verdict (a
// press takes it back), someone else's, a handled one (neither is taken back from the line), or the word a save on the
// line is for (SAVING). A pressed word carries a check before its word and is described by the line's state line
// (pressedWordHint, aria-describedby).
const PRESSED_AS = Object.freeze({ NONE: 0, MINE: 1, OTHER: 2, HANDLED: 3, SAVING: 4 });
// Gives the focus back to the button it was on after a redraw (an armed press redraws its buttons).
function refocusVerdictButton(focused: HTMLElement | null) {
  if (!focused || document.contains(focused) || !focused.dataset || !focused.dataset.act) return;
  const selector = focused.dataset.ref
    ? // a line's '#N' link or its earlier link
      '#doc .pv [data-act="' + focused.dataset.act + '"][data-ref="' + CSS.escape(focused.dataset.ref) + '"]'
    : '[data-act="' +
      focused.dataset.act +
      '"][data-key="' +
      CSS.escape(focused.dataset.key || '') +
      '"][data-page="' +
      (focused.dataset.page || '0') +
      '"]';
  const button = document.querySelector(selector) as HTMLElement | null;
  if (button) button.focus({ preventScroll: true });
}
// A press on a verdict button: a confirm word arms on the first press and saves on the second while what it is bound to
// holds; any other word saves at once - the composer's through savePin, a page line's through pressPageVerdict. how:
// 'key' for a digit key (verdictKey, or one in an empty reason field), 'kb' for a click the keyboard made (Enter or
// Space on the button); a page line's save from either opens its reason popover with the focus.
function verdictPress(button: HTMLElement, how?: string) {
  const key = button.dataset.key || '',
    where = whereOfButton(button),
    page = Number(button.dataset.page) || 0,
    verdicts = docVerdicts(),
    choice = verdicts && verdicts.choices.find((x) => x.key === key);
  if (!choice || button.getAttribute('aria-disabled') === 'true' || viewerBlocked()) return;
  if (where !== VERDICT_PLACE.COMPOSER) {
    pressPageVerdict(choice, page, how);
    return;
  }
  if (choice.confirm && !(isArmedHere(key, where, page) && ARMED_VERDICT && armStillHolds(ARMED_VERDICT))) {
    const focused = document.activeElement as HTMLElement | null;
    armVerdict(key, where, page, choice.label, how === 'key');
    refocusVerdictButton(focused && focused.closest && focused.closest('.vd-btns') ? focused : null);
    return;
  }
  disarmVerdict(false);
  hideTip();
  renderVerdictRow();
  if (COMPOSE.current) savePin(key);
} // while the pick runs the row is off (composer.css): nothing is queued
// A press of word `choice` on page `page`'s line, a toggle:
// - While a save on the line is out (SAVING_LINES) the press is the line's next intent: the last press wins
//   (NEXT_PRESS) and is applied when the save is done - a word already current then does nothing. Nothing is dropped
//   and nothing is toggled off meanwhile: the line ends on the last word pressed.
// - The pressed word (the line's current verdict): the person's own open verdict is taken back as [판정 취소] does
//   (cancelVerdictPin, with its [되돌리기]); anyone else's, or a handled one, is not - the status line says why.
//   Pressing a word never makes a second pin of the word that is current. Right after it was taken back the same word
//   waits CANCEL_HOLD_MS (TAKEN_BACK_HOLD): a double press takes back one verdict and does not save it again.
// - Any other word saves (savePageVerdict), a confirm word on its second press.
function pressPageVerdict(choice: VerdictChoice, page: number, how?: string) {
  const key = choice.key,
    where = VERDICT_PLACE.PAGE,
    armed = isArmedHere(key, where, page) && !!ARMED_VERDICT && armStillHolds(ARMED_VERDICT);
  const arm = () => {
    const focused = document.activeElement as HTMLElement | null;
    hideTip(); // no box over the armed word (it says its wait beside it)
    armVerdict(key, where, page, choice.label, how === 'key');
    refocusVerdictButton(focused && focused.closest && focused.closest('.vd-btns') ? focused : null);
  };
  if (SAVING_LINES.has(pageLineSlot(page))) {
    if (choice.confirm && !armed) {
      arm();
      return;
    }
    disarmVerdict(false);
    hideTip();
    NEXT_PRESS.set(pageLineSlot(page), { key, how: how || '' });
    drawPageVerdicts();
    return;
  }
  const cur = (pageVerdictPins().get(page) || [])[0];
  if (cur && verdictOf(cur) === key) {
    const hold = TAKEN_BACK_HOLD.get(pageLineSlot(page));
    if (hold && hold.key === key && hold.until > Date.now()) return;
    disarmVerdict(false);
    hideTip();
    if (canCancelVerdict(cur)) {
      TAKEN_BACK_HOLD.set(pageLineSlot(page), { key, until: Date.now() + CANCEL_HOLD_MS });
      setTimeout(() => drawPageVerdicts(), CANCEL_HOLD_MS + 20);
      cancelVerdictPin(cur.id, page, !!how, how === 'key');
      return;
    } // by a key: the focus goes to the line's [되돌리기]
    lineNote(
      translateTemplate('지금 판정 #{id} {word} 그대로 · {why} — {target}', {
        id: cur.id,
        word: choice.label,
        target: pageTargetShort(page),
        why:
          pressedAsOf(cur) === PRESSED_AS.HANDLED
            ? translate('처리된 판정은 카드의 [지우기]로 거둡니다')
            : translate('다른 사람의 판정은 여기서 거두지 않습니다'),
      }),
      NOTICE_KIND.INFO,
      null,
      { source: 'pv-press', life: NOTICE_LIFE.TIMER, literal: true },
    );
    return;
  }
  if (choice.confirm && !armed) {
    arm();
    return;
  }
  disarmVerdict(false);
  hideTip(); // the box the press's focus armed: the save chip comes over the line (CHIP_WATCH)
  if (how === 'key') KEY_SAVE_OUT.add(pageLineSlot(page));
  savePageVerdict(page, key, !!how);
}
// What a line's current verdict is to this person, as a pressed word (PRESSED_AS): their own open one, someone else's,
// or a handled one (검토 대기, 처리됨, or one whose [확인] waits for its undo).
function pressedAsOf(pin: Pin) {
  return canCancelVerdict(pin)
    ? PRESSED_AS.MINE
    : pinState(pin) !== PIN_STATE.OPEN || CONFIRMING.has(pin.id)
      ? PRESSED_AS.HANDLED
      : PRESSED_AS.OTHER;
}

// ---------------- The composer's verdict row
// What the selection is, for a button's name: on a figure document the figure it is saved for (figureName), else its
// page's region, else its file and lines.
function selectionTargetName(selection: Selection) {
  const figureRoot = figureVerdictRoot(selection);
  if (figureRoot) return figureName(selection.page, figureRoot);
  return isRegion(selection)
    ? translateTemplate('{page}쪽 영역', { page: selection.page })
    : selection.name + ' ' + lineRange(selection.lo, selection.hi);
}
// A figure's name for a person: its title in the map (meta pages[].title, '[후보] PL26 · …'), else '그림 <id>', with
// its page: '5쪽 · [후보] PL26 · …'. The title is only taken while that page still shows the figure.
function figureName(page: number, root: string) {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null,
    title = facts && facts.figure === root && facts.title ? facts.title : '';
  return translateTemplate('{page}쪽', { page }) + ' · ' + (title || translateTemplate('그림 {id}', { id: root }));
}
// A figure's short name: its map title ('[후보] PL26 · …') while page `page` still shows it, else its id. For the
// composer's lead, the floating line and the status line's undo, which say which figure a verdict is for before and
// after the press.
function figureShort(page: number, root: string) {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null;
  return facts && facts.figure === root && facts.title ? facts.title : root;
}
// What page `page`'s verdict is about, by a short name: on a figure document its figure (figureShort of the map's
// figure), else the page ('7쪽').
function pageTargetShort(page: number) {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null;
  return META && isFigureKind(META.kind) && facts && typeof facts.figure === 'string'
    ? figureShort(page, facts.figure)
    : translateTemplate('{page}쪽', { page });
}
// The figure a figure document's selection is about - the root of its element's path - or null: not a figure document,
// or a pick without an element (a map it could not read).
function figureVerdictRoot(selection: Selection | null): string | null {
  if (!selection || !isFigureKind(docKindOf(selection.doc || DOC || ''))) return null;
  const element = selection.elSel || selection.el;
  const root = element && Array.isArray(element.path) ? element.path[0] : null;
  return typeof root === 'string' && root ? root : null;
}
// The pin body of a verdict saved from the composer on a figure document (ADR-0022 D2): a verdict is about the figure,
// so whatever element the selection names, it is saved as the verdict of the figure - the root of the element's path,
// the page's whole target, as a page line's press saves it. The root's rung of the pick's ladder when it has one (its
// lines, element and kind), else a region over the whole page naming the root (an element drawn without code, whose
// answer has no ladder). null when the selection is not about a figure (figureVerdictRoot): it is saved as it is.
function figureVerdictBody(selection: Selection): Record<string, unknown> | null {
  const root = figureVerdictRoot(selection);
  if (!root) return null;
  const rung = isRegion(selection)
    ? null
    : (selection.levels || []).find(
        (candidate) =>
          !!candidate.el &&
          Array.isArray(candidate.el.path) &&
          candidate.el.path.length === 1 &&
          candidate.el.path[0] === root &&
          candidate.el.id === root,
      );
  if (rung)
    return figureFields(
      {
        file: selection.file,
        name: selection.name,
        page: selection.page,
        lo: rung.lo,
        hi: rung.hi,
        raw_lo: selection.raw_lo,
        raw_hi: selection.raw_hi,
        via: selection.via,
        score: selection.score,
        frac: selection.frac,
        quote: selection.quote,
        pdf_build: selection.pdf_build || undefined,
        scope: rung.level,
      },
      rung.el,
      rung,
    );
  return figureFields(
    { page: selection.page, frac: WHOLE_PAGE.slice(), quote: '', pdf_build: selection.pdf_build || undefined },
    { id: root, path: [root], frac: WHOLE_PAGE.slice() },
    null,
  );
}
// The composer's verdict row (#c-verdict-row, after the note and its lines, before the kind row): '판정 바로 저장' and
// one button per word in file order. Shown for a document with words to a person who may make a verdict pin; its
// buttons are off, with the reason under them, while the kind is a question or [제안 수정] is on (a verdict pin is a
// fix request with no suggestion) and while the selection is still being found - really disabled, with the reason, also
// during a second pick over a selection (pick redraws the row when it starts).
function renderVerdictRow() {
  const row = $('#c-verdict-row'),
    verdicts = docVerdicts(),
    selection = COMPOSE.current;
  dropStaleRetry();
  // A figure page that takes no verdict (its map says verdict: false - a list or a question page) offers no word
  // either.
  const show =
    !!verdicts &&
    canVerdict() &&
    !$('#composer').hidden &&
    !(selection && isFigureKind(docKindOf(selection.doc || DOC || '')) && !pageTakesVerdict(selection.page));
  row.hidden = !show;
  if (ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.COMPOSER && (!show || !armStillHolds(ARMED_VERDICT)))
    disarmVerdict(false);
  if (!verdicts || !show) return;
  const why =
    COMPOSE.picking && !selection
      ? translate('위치를 찾는 중입니다')
      : KIND_NEW === REQUEST_KIND.QUESTION
        ? translate('질문에는 판정을 붙이지 않습니다 — 아래에서 [수정 요청]을 고릅니다')
        : SUGGEST_DRAFT.on
          ? translate('판정을 저장하려면 [제안 수정]을 끕니다')
          : '';
  const focused = document.activeElement as HTMLElement | null,
    inRow = !!focused && row.contains(focused);
  // On a figure document the lead says whose verdict it is - the selected element's figure, by name ('· PL35 … 전체') -
  // whatever element is selected: a panel that shows another figure is still this page's figure's verdict.
  const figureRoot = selection ? figureVerdictRoot(selection) : null,
    mark = '\u0001',
    parts = translateTemplate('{name} 전체', { name: mark }).split(mark);
  const scope =
    figureRoot && selection
      ? html`<span class="vd-scope"> · ${parts[0]}<span class="vd-fig" translate="no">${figureShort(selection.page, figureRoot)}</span>${parts[1] || ''}</span>`
      : isFigureKind(docKindOf((selection && selection.doc) || DOC || '')) && !selection
        ? html`<span class="vd-scope"> · ${translate('그림 전체')}</span>`
        : '';
  setHtml(
    row,
    html`<span id="c-verdict-l" class="vd-l">${translate('판정 바로 저장')}${scope}</span><span class="vd-btns">${verdicts.choices.map((choice) => verdictButton(choice, VERDICT_PLACE.COMPOSER, 0, selection ? selectionTargetName(selection) : '', !!why || !selection || COMPOSE.saving))}</span>\
${why ? html`<span class="vd-why" id="c-verdict-why">${why}</span>` : ''}`,
  );
  if (why) row.setAttribute('aria-describedby', 'c-verdict-why');
  else row.removeAttribute('aria-describedby');
  fitWrappedWords(row.querySelector('.vd-btns'));
  if (inRow) refocusVerdictButton(focused);
}
// A word group that wraps (the 280px panel in English with a word armed) keeps every button at its own width,
// left-aligned (.wrapped): stretched to share the row, a lone last word would run across the whole second row. Measured
// after drawing and when the row's width changes; the class changes how the buttons grow, never where they wrap, so it
// never measures itself again.
function fitWrappedWords(group: Element | null) {
  if (!group) return;
  const tops = new Set([...group.children].map((button) => Math.round(button.getBoundingClientRect().top)));
  group.classList.toggle('wrapped', tops.size > 1);
}
if (typeof ResizeObserver !== 'undefined') {
  const row = document.getElementById('c-verdict-row');
  if (row) new ResizeObserver(() => fitWrappedWords(row.querySelector('.vd-btns'))).observe(row);
}
// A failed verdict save's retry that the composer stopped asking for (COMPOSE.intent moved since its press): it goes,
// and the failure's banner says so (verdictDropped). Run on every redraw of the verdict row, which every such change
// makes.
function dropStaleRetry() {
  const retry = COMPOSE.retryVerdict;
  if (!retry || retry.gen === COMPOSE.intent) return;
  setComposeRetryVerdict(null);
  verdictDropped();
}
// The composer's failed-save banner when the verdict it was for is not asked for any more - dropped after the failure,
// or the intent changed while the request was out (savePin): '핀 저장 실패 — 선택했던 판정은 해제됐습니다 — ...'. [다시
// 저장] saves the selection as the composer has it, without the verdict; pressing the word again saves the verdict.
function verdictDropped() {
  const banner = BANNERS.get(NOTICE_HOST.COMPOSER);
  if (!banner || !banner.save || $('#composer').hidden) return;
  bannerNote(
    NOTICE_HOST.COMPOSER,
    translateTemplate('{what} 실패', { what: translate('핀 저장') }) +
      ' — ' +
      translate('선택했던 판정은 해제됐습니다 — 판정으로 저장하려면 판정 버튼을 다시 누릅니다'),
    NOTICE_KIND.ERR,
    null,
    { save: true, source: banner.source },
  );
}
// The undo of a verdict pin's save (D10): the pin goes again - a withdrawn request - and the composer does not come
// back. When an agent claimed or closed it meanwhile it still goes, and the status line says its run may have started -
// one sentence with no ' — ', so the folded line shows all of it. A reason draft typed for it is not written to the
// withdrawn pin; it stays kept, and the status line offers [되돌리기], which brings the verdict back with it ('판정 #42
// 채택 저장 되돌림 · 쓰던 이유 보관 — <대상>'). Without one the undo says nothing - pressing the word again is the
// same.
function verdictUndo(id: number): () => Promise<boolean> {
  const undo = async () => {
    let was = null;
    try {
      was = (await api('/api/pins/' + id, { what: '핀 읽기', silent: true })).data.pin;
    } catch (error) {}
    const session = REASON_SESSION && REASON_SESSION.id === id ? REASON_SESSION : null;
    if (session && hasUnsavedReason(session))
      putDraft(session.doc, id, session.text, session.base, session.rev, {
        mode: session.mode,
        tried: session.tried,
        from: session.via,
      });
    WITHDRAWN_PINS.add(id);
    const ok = await dropPin(id, true, undo);
    if (!ok) WITHDRAWN_PINS.delete(id);
    if (ok && REASON_SESSION && REASON_SESSION.id === id) {
      setReasonSession(null);
      drawPageVerdicts();
    } // a withdrawn verdict takes no reason
    const draft = ok ? getDraft(DOC, id) : null,
      key = was && verdictOf(was),
      target = was ? pageTargetOf(was, META ? META.kind : undefined) : null;
    if (draft && key)
      lineNote(
        translateTemplate('판정 #{id} {word} 저장 되돌림 · 쓰던 이유 보관 — {target}', {
          id,
          word: verdictLabel(key),
          target: target ? pageTargetShort(target.page) : '#' + id,
        }),
        NOTICE_KIND.OK,
        {
          label: '되돌리기',
          tip: TIP_TEXT.undo,
          wait: true,
          fn: async () => {
            WITHDRAWN_PINS.delete(id);
            const back = await restorePin(id);
            if (back) afterVerdictRestore(id);
            return back;
          },
        },
        { life: NOTICE_LIFE.TIMER, undo: true, literal: true },
      );
    if (ok && was && (claimActive(was) || pinState(was) !== PIN_STATE.OPEN))
      lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다', NOTICE_KIND.WARN);
    return ok;
  };
  return undo;
}

// ---------------- The page verdict line (figure documents and view-only PDFs, page: true)
// The pin body a page verdict saves from the whole page's pick answer (D7): on a figure document the rung whose element
// is the page's figure (el.path == [el.id]) - its lines and element - else a region answer whose element is that
// figure, else
// - the pick chose an element inside the figure: one covering 40% of the page wins a whole-page drag (pick_element) - a
// region over the whole page naming the figure, the root of that element's path, as the composer's verdict saves it
// (figureVerdictBody, ADR-0022 D2); on a view-only PDF the region answer as it is. null when a figure page's answer
// names no element (its map could not be read). Pure but for the figure helpers.
function pageVerdictBody(answer: any, kind: string | undefined): Record<string, unknown> | null {
  const root = (element) =>
    !!element && Array.isArray(element.path) && element.path.length === 1 && element.path[0] === element.id;
  if (isFigureKind(kind)) {
    const rung = isRegion(answer) ? null : (answer.levels || []).find((candidate) => root(candidate.el));
    if (rung)
      return figureFields(
        {
          file: answer.file,
          name: answer.name,
          page: answer.page,
          lo: rung.lo,
          hi: rung.hi,
          raw_lo: answer.raw_lo,
          raw_hi: answer.raw_hi,
          via: answer.via,
          score: answer.score,
          frac: answer.frac,
          quote: answer.quote,
          pdf_build: answer.pdf_build || undefined,
          scope: rung.level,
        },
        rung.el,
        rung,
      );
    if (isRegion(answer) && root(answer.el))
      return figureFields(
        { page: answer.page, frac: answer.frac, quote: answer.quote, pdf_build: answer.pdf_build || undefined },
        answer.el,
        null,
      );
    const figure = answer.el && Array.isArray(answer.el.path) ? answer.el.path[0] : null;
    if (typeof figure === 'string' && figure)
      return figureFields(
        { page: answer.page, frac: WHOLE_PAGE.slice(), quote: '', pdf_build: answer.pdf_build || undefined },
        { id: figure, path: [figure], frac: WHOLE_PAGE.slice() },
        null,
      );
    return null;
  }
  return isRegion(answer)
    ? { page: answer.page, frac: answer.frac, quote: answer.quote, pdf_build: answer.pdf_build || undefined }
    : null;
}
// A page line's pending state is keyed by its document and page (pageLineSlot): a save held on one document's page must
// not hold, queue or end the same page number's line of another document.
/** @param [doc] - default: the document on screen */
function pageLineSlot(page: number, doc?: string | null) {
  return (doc === undefined ? DOC || '' : doc || '') + '\u0001' + page;
}
// the page lines whose verdict is being saved (pageLineSlot), with the word it saves
const SAVING_LINES = new Map() as Map<string, string>;
// The press made on a line while its save was out, by line (pageLineSlot) - the last one: applied when that save is
// done (pressPageVerdict).
const NEXT_PRESS = new Map() as Map<string, { key: string; how: string }>;
// The lines whose save out was a digit key's (pageLineSlot): Enter on any control of that line then means the reason,
// one intent with the key (openReasonOnEnter). On the word the focus rests on it pressed that word: a second verdict,
// over the one being saved.
const KEY_SAVE_OUT = new Set() as Set<string>;
// A line whose word was just taken back by pressing it again (pageLineSlot): that word waits until then (a double press
// takes back one).
const TAKEN_BACK_HOLD = new Map() as Map<string, { key: string; until: number }>;
// A page line's last failed save, by page: said on the line that was pressed (pageLineHtml) as well as on the status
// line, until the next press on that line or another document or build. The document and build it was for come with it.
const LINE_SAVE_ERROR = new Map() as Map<number, { text: string; doc: string | null; build: string }>;
// The reason after a page line's save - its popover, drafts kept per pin, its writes - is verdict/flow-reason.ts
// (REASON_SESSION). The key marks follow the focus: off on every line while a text field has it - digits typed there
// are text, the reason field's included (keyedPageFor). (Another document closes the popover through syncReasonSession
// - or drawPageVerdicts when it has no lines - whose leave saves what was typed.)
document.addEventListener('focusin', () => stickSoon());
document.addEventListener('focusout', () => stickSoon());
// body.pv-typing while a text field in a page line has the focus (the reason): on a touch screen the keyboard is up,
// and the line drops its figure's name, its save chip folds to [되돌리기] and the status line over the sheet steps
// aside (components.css, responsive.css), so line, field, chip and sheet fit in what the keyboard leaves on a foldable.
// That line's row is measured again. Read on every focus move and after every drawing of the lines (drawPageVerdicts):
// a rebuild or a pin deleted elsewhere takes the focused field out of the page, and Chromium sends no focusout for
// that, so without the redraw the class would stay and hide the status line. Once on, it stays while the reason popover
// is being used - the focus on one of its buttons, or a press that started in it until that press's click has run
// (POPOVER_PRESS): a tap on [저장], [접기] or [지우기] takes the focus out of the field, and if the status line came
// back and a phone's line stacked again, the button would move between the touch and its click and the click would fall
// on the popover itself. So does a press on the rest of the line while the field folds it: the figure's name coming
// back would move the words down under the finger before the click. The fold goes once that press is done: its click
// has run, the browser took it for a scroll (pointercancel), or 500ms after it let go without a click - a long press
// keeps it as long as it is held, so the words stay under the finger while its description shows. Only the press that
// holds the fold lets it go (FOLD_PRESS_HOLD): a new press on the line takes it over and the earlier one's wait goes,
// so a long press's swallowed click never lets the fold go under the next press, between that press's focus and its
// click. A press whose window loses the focus or is hidden (another app, a tab switch) lets it go at once: let go
// outside the window, it has no pointerup or pointercancel here.
let POPOVER_PRESS = false;
let FOLD_PRESS_HOLD = null as (() => void) | null; // the press holding the fold: drops its own wait without letting go
function syncTypingFold() {
  const active = document.activeElement as HTMLElement | null,
    focusLine = active && active.closest ? (active.closest('#doc .pv') as HTMLElement | null) : null,
    body = document.body;
  const pop = !!active && !!active.closest && !!active.closest('#doc .pv>.pv-pop'),
    on = (!!focusLine && typingNow()) || (body.classList.contains('pv-typing') && (pop || POPOVER_PRESS));
  if (body.classList.contains('pv-typing') === on) return;
  body.classList.toggle('pv-typing', on);
  const line = focusLine || (document.querySelector('#doc .pv.reading') as HTMLElement | null);
  if (line) fitPageLines([line]);
}
document.addEventListener('focusin', syncTypingFold);
document.addEventListener('focusout', () => setTimeout(syncTypingFold, 0));
document.addEventListener(
  'pointerdown',
  (event) => {
    const target = event.target as HTMLElement | null;
    if (!(
      target &&
      target.closest &&
      (target.closest('#doc .pv>.pv-pop') ||
        (document.body.classList.contains('pv-typing') && target.closest('#doc .pv')))
    ))
      return;
    if (FOLD_PRESS_HOLD) FOLD_PRESS_HOLD(); // an earlier press still waiting: this one holds the fold now
    POPOVER_PRESS = true;
    let timer = undefined as ReturnType<typeof setTimeout> | undefined;
    const drop = () => {
      clearTimeout(timer);
      window.removeEventListener('click', late);
      window.removeEventListener('pointercancel', late);
      window.removeEventListener('pointerup', up, true);
      window.removeEventListener('blur', late);
      document.removeEventListener('visibilitychange', hid);
      if (FOLD_PRESS_HOLD === drop) FOLD_PRESS_HOLD = null;
    };
    const end = () => {
      if (FOLD_PRESS_HOLD !== drop) return;
      drop();
      setTimeout(() => {
        if (FOLD_PRESS_HOLD) return;
        POPOVER_PRESS = false;
        syncTypingFold();
      }, 0);
    };
    const late = () => end(),
      up = () => {
        clearTimeout(timer);
        timer = setTimeout(end, 500);
      },
      hid = () => {
        if (document.visibilityState === 'hidden') end();
      }; // late: after the press's own click (window, bubbling: after the viewer's handlers)
    FOLD_PRESS_HOLD = drop;
    window.addEventListener('click', late);
    window.addEventListener('pointercancel', late);
    window.addEventListener('pointerup', up, true);
    window.addEventListener('blur', late);
    document.addEventListener('visibilitychange', hid);
  },
  true,
);
// What a press on page `page` of the document on screen saves against: its document, kind, build and page size and its
// target's name, with the visit it was made in. A save runs on these - not on the document on screen when it runs - so
// a press made before switching documents is saved, and one queued meanwhile is too (pressPageVerdict,
// savePageVerdict). null when the page is not there.
function pageSaveContext(page: number): {
  doc: string | null;
  kind: string | undefined;
  build: string;
  w: number;
  h: number;
  target: string;
  visit: any;
} | null {
  const facts = META && META.pages[page - 1];
  if (!META || !facts) return null;
  return {
    doc: DOC,
    kind: META.kind,
    build: META.pages_build || '',
    w: facts.pt_w,
    h: facts.pt_h,
    target: pageTargetShort(page),
    visit: captureVisit(),
  };
}
// The current verdict of page `page` on document doc - one not on screen too: the verdict order holds every document's.
function currentVerdictOn(doc: string | null, page: number): Pin | null {
  if (doc === DOC || (!doc && !DOC)) return (pageVerdictPins().get(page) || [])[0] || null;
  let best = null as Pin | null;
  verdictOrder(doc || DEFAULT_DOC).groups.forEach((group) => {
    if (group.whole && group.page === page && (!best || best.id < group.pins[0].id)) best = group.pins[0];
  });
  return best;
}
// The largest pin number the lists hold: a verdict whose answer was lost is looked for above it (findLandedVerdict).
function topPinId() {
  return OPEN_ALL.concat(REVIEW_ALL, DONE_ALL).reduce((highest, pin) => Math.max(highest, pin.id), 0);
}
// A verdict pin this person saved with word key about page `page` of document doc since pin number top - a save whose
// answer was lost may have landed: it is read again before the press is called a failure, or pressed again (a
// duplicate).
function findLandedVerdict(
  doc: string | null,
  page: number,
  key: string,
  top: number,
  kind: string | undefined,
): Pin | null {
  return (
    OPEN_ALL.find(
      (pin) =>
        pin.id > top &&
        pdoc(pin) === (doc || DEFAULT_DOC) &&
        verdictOf(pin) === key &&
        isMe(pin.author) &&
        (() => {
          const target = pageTargetOf(pin, kind);
          return !!target && target.page === page;
        })(),
    ) || null
  );
}
// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build it was pressed
// on, the body pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's
// selection and draft stay as they are. The word becomes the page's current verdict - a new pin (the agent runs the
// newest, D4 and D5); pressing the current word takes it back instead (pressPageVerdict). It runs on its press's
// context (pageSaveContext): leaving the document while it runs does not drop it - it completes, and its undo is
// offered on the status line. Saved: '#42 저장됨 [되돌리기]' on the line for NOTICE_MS. An answer lost on the network -
// or a 5xx, which a server may send after writing - is checked against the list before anything is said
// (findLandedVerdict): a verdict that landed is a save, not a failure a second press would duplicate. A refusal or a
// failure is said on the status line, result first ('판정 저장 실패 · <까닭> — <대상>'), and under the pressed line.
// While it is out the line says what it saves ('보류 저장 중…') and presses wait in NEXT_PRESS; the last of them is
// applied after it - also after a switch away and back, on the document it was pressed on - unless that word is the
// page's verdict by then. No save opens the reason popover: the line offers [이유 추가], and 'Enter 이유 쓰기' while
// the keys act on it.
/** @param [byKeyboard] - pressed from the keyboard: the focus goes to the line's way to the reason */
async function savePageVerdict(
  page: number,
  key: string,
  byKeyboard?: boolean,
  givenContext?: ReturnType<typeof pageSaveContext>,
) {
  const context = givenContext || pageSaveContext(page);
  if (!context) return;
  const slot = pageLineSlot(page, context.doc);
  if (SAVING_LINES.has(slot)) return;
  const visit = context.visit,
    here = () => DOC === context.doc;
  const fail = (text: string) => {
    if (here()) LINE_SAVE_ERROR.set(page, { text, doc: context.doc, build: context.build });
  };
  // Said on the status line with what it was for, result first, and under the pressed line.
  const failed = (why: string) => {
    lineNote(
      translateTemplate('판정 저장 실패 · {why} — {target}', { why, target: context.target }),
      NOTICE_KIND.ERR,
      null,
      {
        source: 'page-verdict',
        literal: true,
      },
    );
    fail(translateTemplate('{what} 실패', { what: translate('판정 저장') }) + ' — ' + why);
  };
  let saved = false,
    got = 0;
  if (here()) LINE_SAVE_ERROR.delete(page);
  // A key save (a digit, Enter or Space on a word) hands the focus to the line's way to the reason ('Enter 이유 쓰기'),
  // so Enter there opens it - on the pressed word Enter would take the verdict back - unless the person put the focus
  // anywhere else meanwhile (another page's word, a '#N' link, the panel): a redraw that puts it back on the same
  // word's button is no move.
  let away = false;
  const moved = (event) => {
    const target = event.target as HTMLElement;
    if (!(
      target &&
      target.dataset &&
      target.dataset.act === 'pv-save' &&
      target.dataset.key === key &&
      target.dataset.page === String(page)
    ))
      away = true;
  };
  document.addEventListener('focusin', moved);
  const before = currentVerdictOn(context.doc, page),
    previousId = before ? before.id : 0,
    top = topPinId(); // the verdict a save replaces: a draft kept for it moves on
  // A new verdict on the line ends the line's offer of a take-back's [되돌리기] (the status line keeps its own): the
  // line is about the new verdict, and while the offer lasts its [이유 추가] steps out (components.css), so the focus a
  // key save hands it would go nowhere.
  const focusedBefore = document.activeElement,
    // it goes with the offer: the focus goes to the word being saved
    onUndo = !!focusedBefore && !!focusedBefore.closest && !!focusedBefore.closest('#doc .pv-undo');
  LINE_UNDO_OFFERS.delete(slot);
  SAVING_LINES.set(slot, key);
  drawPageVerdicts();
  if (onUndo) refocusLineWord(page, key);
  try {
    const answer = (
      await api('/api/pick', {
        method: 'POST',
        body: {
          page,
          x0: 0,
          y0: 0,
          x1: context.w,
          y1: context.h,
          frac: WHOLE_PAGE.slice(),
          pdf_build: context.build || undefined,
          doc: context.doc || undefined,
        },
        what: '판정 저장',
        silent: true,
      })
    ).data;
    if (answer.error) {
      failed(errText(answer));
      if (answer.pdf_build_gone && here()) refreshDoc().catch(() => {});
      return;
    }
    const body = pageVerdictBody(answer, context.kind);
    if (!body) {
      lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다', NOTICE_KIND.WARN, null, {
        source: 'page-verdict',
      });
      fail(translate('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다'));
      return;
    }
    Object.assign(body, {
      note: '',
      doc: context.doc || undefined,
      kind_req: REQUEST_KIND.FIX,
      assignee: ASSIGNEE_AGENT,
      verdict: key,
    });
    let id = 0;
    try {
      id = (await api('/api/pin', { method: 'POST', body, what: '판정 저장', silent: true })).data.id;
    } catch (error) {
      const x = error as ApiError;
      // no answer, or a 5xx (it may have been written first): the list says whether it landed
      if (x && x.status && x.status < 500) throw error;
      await loadPins();
      const got = findLandedVerdict(context.doc, page, key, top, context.kind);
      if (!got) throw error;
      id = got.id;
    }
    saved = true;
    got = id;
    sourceOk('page-verdict');
    if (SECTION_SEEN.open) SECTION_SEEN.open.add(id); // my own new pin is never 'new' on a collapsed header
    const chip = undoNote(
      NOTICE_PLACE.CHIP,
      translateTemplate('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다', {
        id,
        word: verdictLabel(key, context.doc),
        target: context.target,
      }),
      { label: '되돌리기', wait: true, fn: verdictUndo(id) },
      {
        pin: id,
        pending: true,
        label: translateTemplate('#{id} 저장됨 · {word}', { id, word: verdictLabel(key, context.doc) }),
      },
    );
    // the reason popover: a draft on this line moves to the new verdict
    if (here()) followSaveWithReason(page, id, key, !!byKeyboard, previousId);
    await loadPins();
    settleChip(chip);
    if (here()) showPressedHint(page);
  } catch (error) {
    const x = error as ApiError;
    if (!saved)
      failed(x && x.status ? (x.data && errText(x.data)) || 'HTTP ' + x.status : translate('서버에 닿지 않습니다'));
  } finally {
    document.removeEventListener('focusin', moved);
    SAVING_LINES.delete(slot);
    KEY_SAVE_OUT.delete(slot);
    // A popover opened by Enter while this save was out: bound to it now if its Enter came after the number was known
    // (the list still being read), else, the save failed, its text kept as the page's draft.
    const waitingPopover =
      here() &&
      REASON_SESSION &&
      !REASON_SESSION.id &&
      REASON_SESSION.page === page &&
      REASON_SESSION.doc === context.doc;
    if (waitingPopover && saved) followSaveWithReason(page, got, key, !!byKeyboard, previousId);
    else if (!saved && here()) keepUnboundReason(page);
    // one moved away from meanwhile: written on this verdict wherever the person is now
    settleDetachedReason(slot, saved ? got : 0, key);
    drawPageVerdicts();
    if (currentVisit(visit) && byKeyboard && !away) {
      const reasonOpen = document.querySelector(
        '#doc .pv[data-page="' + page + '"] [data-act="pv-reason-open"]',
      ) as HTMLElement | null;
      if (reasonOpen && saved) reasonOpen.focus({ preventScroll: true });
      else refocusLineWord(page, key);
      // never left on nothing: the line's own control
      if (saved && document.activeElement === document.body) focusLine(page);
      // The focus the save moved there raises no description box: the press's own description of the pressed word
      // stands over the words for a few seconds (showPressedHint), and on a one-row line the two boxes would overlap. A
      // focus the person moves raises it.
      if (saved) hideTip();
    }
    const next = NEXT_PRESS.get(slot);
    NEXT_PRESS.delete(slot);
    if (next) {
      const cur = currentVerdictOn(context.doc, page); // the last press made meanwhile, on the document it was made on
      if (!(cur && verdictOf(cur) === next.key)) {
        const fresh = here() ? pageSaveContext(page) : null;
        if (next.how === 'key') KEY_SAVE_OUT.add(slot);
        savePageVerdict(page, next.key, !!next.how, fresh || context);
      }
    }
    settleFailedCancelDraft(slot);
  }
} // a failed take-back's draft that waited for this save (a next save started just now waits on)
// The reading line's name for page `page`, in two parts: a short identifier that is never cut - the page and the
// figure's code, '6쪽 · PL17' (the map title's head before its first ' · ', a leading tag such as '[후보]' moved to the
// rest; else the figure id) - and the rest of the title, cut first ('[후보] 다섯 비교 쌍의 월별 효과 — …'), so the name
// next to the buttons always says which figure a press decides. A view-only PDF's page is its page alone.
function pageLineName(page: number): { id: string; rest: string } {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null,
    at = translateTemplate('{page}쪽', { page });
  if (!META || !isFigureKind(META.kind) || !facts || typeof facts.figure !== 'string') return { id: at, rest: '' };
  const title = facts.title ? String(facts.title) : '';
  if (!title) return { id: at + ' · ' + facts.figure, rest: '' };
  const index = title.indexOf(' · '),
    head = index > 0 ? title.slice(0, index) : '',
    match = /^(\[[^\]]*\])\s*(\S.*)$/.exec(head);
  if (!head) return { id: at, rest: title };
  return match
    ? { id: at + ' · ' + match[2], rest: match[1] + ' ' + title.slice(index + 3) }
    : { id: at + ' · ' + head, rest: title.slice(index + 3) };
}
// Gives the focus back to word key's button on page `page`'s line after its save: the pressed button was disabled and
// redrawn while the request ran, which dropped the focus. Not when the person put the focus somewhere else meanwhile
// (savePageVerdict watches for that) or it is on something now.
function refocusLineWord(page: number, key: string) {
  const active = document.activeElement;
  if (active && active !== document.body && document.contains(active)) return;
  const button = document.querySelector(
    '#doc .pv[data-page="' + page + '"] [data-act="pv-save"][data-key="' + CSS.escape(key) + '"]',
  ) as HTMLButtonElement | null;
  if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true')
    button.focus({ preventScroll: true });
}
// ---------------- Taking one's verdict back
// Whether the line offers [판정 취소] on a verdict pin, its page's current verdict: the person's own (isMe), still open
// - not yet handled; a handled one's card still offers [지우기] - to a person who may make a verdict (no agent, D16,
// nor a viewer). A pin whose [확인] waits for its undo is not open.
function canCancelVerdict(pin: Pin) {
  return (
    !!verdictOf(pin) && canVerdict() && isMe(pin.author) && pinState(pin) === PIN_STATE.OPEN && !CONFIRMING.has(pin.id)
  );
}
// after a cancel on a page, how long that page's next [판정 취소] waits (a double press never takes two)
const CANCEL_HOLD_MS = 800;
const CANCEL_HOLD = new Map() as Map<string, number>; // line (pageLineSlot) -> until when its [판정 취소] waits
// The lines whose take-back is out: Enter and Space on them do nothing until it answers (stopOffPageKey). What the
// focus rests on is what the line shows meanwhile, the verdict before it: Enter there would open a reason for it, or
// take that one back too. An answer that does not come must not leave the line deaf: past CANCEL_ANSWER_WAIT the keys
// are back and the status line says so; the late answer is still taken (its message, its [되돌리기]), but the focus has
// moved on by then and stays. The value says whose wait it is.
const CANCEL_OUT = new Map() as Map<string, number>;
// the bound a status-line action's request has (platform/notices.ts noticeAct)
let CANCEL_ANSWER_WAIT = NOTICE_ACT_WAIT;
// A verdict a [되돌리기] brought back (a take-back's, the save chip's): when it is its line's current verdict again its
// kept reason draft opens (reviveReason); when a newer verdict came meanwhile - someone else's - it is restored but
// superseded, the status line says so ('판정 #21 채택 되살림 · 지금 판정은 Bob의 #34 보류 — <대상>') and no popover
// opens over that line - its kept draft, which no line would mark on a verdict that is not current, becomes the page's
// draft, said with [보기] (placeFailedCancelDraft).
function afterVerdictRestore(id: number) {
  const pin = findAnyPin(id),
    target = pin ? pageTargetOf(pin, META ? META.kind : undefined) : null,
    cur = target ? (pageVerdictPins().get(target.page) || [])[0] : null;
  if (pin && target && cur && cur.id !== id) {
    const currentKey = verdictOf(cur) || '',
      key = verdictOf(pin) || '';
    lineNote(
      translateTemplate('판정 #{id} {word} 되살림 · 지금 판정은 {owner} #{cur} {now} — {target}', {
        id,
        word: verdictLabel(key),
        owner: isMe(cur.author) ? translate('내') : translateTemplate('{name}의', { name: who(cur.author) }),
        cur: cur.id,
        now: verdictLabel(currentKey),
        target: pageTargetShort(target.page),
      }),
      NOTICE_KIND.INFO,
      null,
      { literal: true, life: NOTICE_LIFE.TIMER },
    );
    placeFailedCancelDraft(id, target.page, DOC, true);
    return;
  }
  reviveReason(id);
}
// The take-backs whose [되돌리기] the line offers too, by line (pageLineSlot): the pin and its status-line message -
// the offer lasts as long as that message (its window, or its action).
const LINE_UNDO_OFFERS = new Map() as Map<string, { id: number; n: number }>;
// The line's [되돌리기]: the status line's action runs (noticeAct), as if pressed there.
function undoFromLine(control: HTMLElement) {
  const line = control.closest('.pv'),
    page = Number(line && line.getAttribute('data-page')) || 0,
    offer = LINE_UNDO_OFFERS.get(pageLineSlot(page));
  if (!offer) return;
  LINE_UNDO_OFFERS.delete(pageLineSlot(page));
  if (NOTICES.has(offer.n)) noticeAct(offer.n);
  drawPageVerdicts();
  focusLine(page);
}
// [판정 취소] on page `page`'s line - or its pressed word pressed again (pressPageVerdict): verdict pin id goes to the
// Trash as the card's [지우기] sends it (dropPin) - a withdrawn request - and the line shows at once what is current
// now: the newest earlier verdict about the same target (D4) or '판정 없음'. The status line says so result first
// ('판정 #17 채택 취소 · 지금 판정 #12 보류 — <대상>', or '… · 남은 판정 없음 — …') with [되돌리기], which restores it
// (restorePin) and its kept reason draft (reviveReason); one an agent had claimed still goes, and the status line says
// its run may have started (as the save's undo, verdictUndo). Its reason popover closes with it; what was typed is not
// written, and stays kept for that [되돌리기]. A failure is said on the status line and the line shows the verdict
// again, its popover too - or, when something took its place meanwhile, what was typed as a draft its line marks, said
// with [보기] (bringBackReason). The page's next [판정 취소] waits CANCEL_HOLD_MS: the same place may now cancel the
// earlier verdict, which a double press must not reach. A keyboard press leaves the focus on the PDF area, as Esc in
// the reason field does.
function cancelLineVerdict(button: HTMLElement) {
  const id = Number(button.dataset.ref),
    page = Number((button.closest('.pv') || button).getAttribute('data-page')) || 0;
  if (button.getAttribute('aria-disabled') === 'true') return;
  cancelVerdictPin(id, page, document.activeElement === button);
}
/** @param had - the focus was on what was pressed */
/** @param [byKey] - a digit key: the focus goes to the line from wherever it was */
async function cancelVerdictPin(id: number, page: number, had: boolean, byKey?: boolean) {
  const pin = OPEN_ALL.find((x) => x.id === id),
    from = document.activeElement,
    doc = DOC;
  if (!pin || !canCancelVerdict(pin) || viewerBlocked()) return;
  const key = verdictOf(pin) as string,
    claimed = claimActive(pin),
    target = pageTargetShort(page);
  const inField = isReasonField(document.activeElement) && !!REASON_SESSION && REASON_SESSION.id === id;
  CANCEL_HOLD.set(pageLineSlot(page), Date.now() + CANCEL_HOLD_MS);
  setTimeout(() => drawPageVerdicts(), CANCEL_HOLD_MS + 20);
  // Its reason popover leaves with the line's verdict, but the session is kept until the server answers: a failed
  // cancel brings the verdict back and its unsent reason with it, or keeps that as a draft its line marks when
  // something took its place (bringBackReason); a done one drops it - its draft stays kept (putDraft) for the
  // [되돌리기].
  const kept = REASON_SESSION && REASON_SESSION.id === id ? REASON_SESSION : null;
  if (kept) {
    setReasonSession(null);
    if (hasUnsavedReason(kept))
      putDraft(kept.doc, id, kept.text, kept.base, kept.rev, { mode: kept.mode, tried: kept.tried, from: kept.via });
  }
  WITHDRAWN_PINS.add(id);
  // The take-back is said on the status line with its [되돌리기], which the line itself also offers for as long
  // (LINE_UNDO_OFFERS): the status line is far away by Tab.
  const say = () => {
    const now = (pageVerdictPins().get(page) || [])[0],
      nowKey = now && verdictOf(now);
    const rest =
      now && nowKey
        ? translateTemplate('지금 판정 #{id} {word}', { id: now.id, word: verdictLabel(nowKey) })
        : translate('남은 판정 없음');
    const notice = lineNote(
      translateTemplate('판정 #{id} {word} 취소 · {rest} — {target}', { id, word: verdictLabel(key), rest, target }),
      NOTICE_KIND.OK,
      {
        label: '되돌리기',
        tip: TIP_TEXT.undo,
        wait: true,
        fn: async () => {
          WITHDRAWN_PINS.delete(id);
          const ok = await restorePin(id);
          if (ok) afterVerdictRestore(id);
          return ok;
        },
      },
      { life: NOTICE_LIFE.TIMER, undo: true, literal: true },
    );
    // [이유 추가] steps out while the line offers the undo (components.css): a focus on it goes to the [되돌리기]
    // beside it.
    const focused = document.activeElement as HTMLElement | null,
      onAdd = !!focused && !!focused.closest && !!focused.closest('#doc .pv[data-page="' + page + '"] .pv-ra>.pv-add');
    if (notice) {
      LINE_UNDO_OFFERS.set(pageLineSlot(page), { id, n: notice.n });
      drawPageVerdicts();
      setTimeout(() => drawPageVerdicts(), NOTICE_MS + NOTICE_HOLD_MAX + 50);
      const active = document.activeElement,
        undoButton = document.querySelector(
          '#doc .pv[data-page="' + page + '"] [data-act="pv-undo"]',
        ) as HTMLElement | null;
      if (onAdd && undoButton && (active === focused || active === document.body || !active))
        undoButton.focus({ preventScroll: true });
    }
  };
  hideTip();
  const again = () => {
    CANCEL_HOLD.delete(pageLineSlot(page));
    drawPageVerdicts();
    cancelVerdictPin(id, page, false);
  }; // [다시 시도] is a new press: no hold
  const out = pageLineSlot(page);
  CANCEL_OUT.set(out, id);
  let ok = false,
    slow = false;
  const wait = setTimeout(() => {
    slow = true;
    if (CANCEL_OUT.get(out) === id) CANCEL_OUT.delete(out);
    lineNote('판정 취소의 답이 늦습니다 — 이 줄의 키를 다시 받습니다', NOTICE_KIND.WARN, null, {
      source: 'pv-drop-wait',
      life: NOTICE_LIFE.TIMER,
    });
  }, CANCEL_ANSWER_WAIT);
  try {
    ok = await dropPin(id, false, again, { say, where: NOTICE_HOST.LINE, what: '판정 취소' });
  } finally {
    clearTimeout(wait);
    if (CANCEL_OUT.get(out) === id) CANCEL_OUT.delete(out);
  }
  if (!ok) {
    WITHDRAWN_PINS.delete(id);
    bringBackReason(id, page, kept ? kept.doc : doc, kept);
  }
  // A keyboard press stays on its own page: the line's [되돌리기], else its line (never the PDF area, from which Tab
  // would go to the first page's line). A digit key's take-back takes the focus there from wherever it was - the
  // outline, a card - as a key save does, unless the person moved it meanwhile: left in the outline, Enter would press
  // the outline again instead of undoing. A reason popover that has the focus now is a newer one (the verdict's own
  // left with it): it keeps it - on this line too (a new verdict's, saved while the take-back was out), where moving
  // the focus to the line would make the next digit a verdict key.
  const at = document.activeElement as HTMLElement | null,
    pop = !!at && !!at.closest && !!at.closest('#doc .pv-pop');
  const lost =
    !pop &&
    (!at ||
      at === document.body ||
      at === $('#left') ||
      !!(at.closest && at.closest('#doc .pv[data-page="' + page + '"]')) ||
      (!!byKey && at === from));
  if ((had || inField) && lost && !slow) {
    const undoButton = document.querySelector(
      '#doc .pv[data-page="' + page + '"] [data-act="pv-undo"]',
    ) as HTMLElement | null;
    if (undoButton) undoButton.focus({ preventScroll: true });
    else if (!focusLine(page)) searchToPage();
  }
  if (ok && claimed) lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다', NOTICE_KIND.WARN);
}
// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and
// word, and who made it and when if that was someone else - its reason (inlineReason: a check and its first line, a
// kept draft, [이유 추가]), [판정 취소] on the person's own while it is open (canCancelVerdict), the earlier open
// verdicts as a link ('이전 판정 N건 · 새 판정으로 대체됨'), and, for a person who may make one, a button per word. The
// current verdict's word is pressed (a toggle, pressPageVerdict); while a save on the line is out, the word it saves -
// or the last one pressed meanwhile (NEXT_PRESS) - is pressed instead and the state says '보류 저장 중…'. The reason
// popover (reasonPopoverHtml) is the line's last child, laid above it.
/**
 * @param [chip] - the line holds a save chip or its reason popover: it draws no descriptions @param [panel] - the panel
 * beside the pages (verdict/view-panel.ts)
 */
function pageLineHtml(page: number, list: Pin[] | undefined, verdicts: DocVerdicts, chip?: boolean, panel?: boolean) {
  const cur = list && list[0],
    earlier = list ? list.slice(1).filter((pin) => pinState(pin) === PIN_STATE.OPEN) : [];
  // Before the first pin list is applied (PINS_APPLIED_SEQ) the line knows no verdict yet: '판정 읽는 중…', buttons
  // waiting.
  const loading = !PINS_APPLIED_SEQ;
  const key = cur && verdictOf(cur),
    other = !!cur && !!cur.author && !isMe(cur.author);
  // One order for every state: '판정 #4 채택 · 처리 대기', then who made it and when if someone else did. The number is
  // a link to the card (the viewer's link style), the word is bold. A claimed one names who has it: '처리 중(Agent B)'
  // - the name after it is the pin's author.
  const mark = '\u0001',
    by = cur && pinState(cur) === PIN_STATE.OPEN && claimActive(cur) && cur.claimed_by ? who(cur.claimed_by) : '',
    state = cur ? verdictStateWord(cur) : '',
    parts = by ? translateTemplate('처리 중({name})', { name: mark }).split(mark) : [state];
  const text =
    cur && key
      ? html`<span class="pv-s">${translate('판정')} <span class="pin-ref pv-ref hit" role="link" tabindex="0" data-act="pin-ref" data-ref="${cur.id}" \
aria-label="${translateTemplate('지금 판정 #{id} 카드로 갑니다', { id: cur.id })}" data-tip="${translateTemplate('핀 #{id} 로 갑니다', { id: cur.id })}">#${cur.id}</span> <b class="vd-w" translate="no">${verdictLabel(key)}</b></span>\
<span class="pv-sep" aria-hidden="true">·</span><span class="pv-st">${parts[0]}${by ? html`<span class="pv-by" translate="no">${by}</span>${parts[1] || ''}` : ''}</span>\
${other ? html`<span class="pv-sep" aria-hidden="true">·</span><span class="pv-au" translate="no">${who(cur.author)}</span> ${relSpan(cur.at, 'pv-at', '')}` : ''}\
${inlineReason(page, cur)}`
      : html`<span class="pv-s pv-none">${translate(loading ? '판정 읽는 중…' : '판정 없음')}</span>${loading ? '' : inlineReason(page, undefined)}`;
  // A save on the line that is out: what it saves - or the last word pressed meanwhile, which comes after it.
  const slot = pageLineSlot(page),
    next = NEXT_PRESS.get(slot),
    savingKey = SAVING_LINES.get(slot),
    want = next ? next.key : savingKey !== undefined ? savingKey : key || null;
  const saving =
    savingKey !== undefined
      ? html`<span class="pv-busy" role="status"><span class="pv-sep" aria-hidden="true">·</span> ${translateTemplate('{word} 저장 중…', { word: verdictLabel(want || savingKey) })}</span>`
      : '';
  // A confirm word armed on this line says how long it waits, beside it.
  const armed =
    !!ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page === page ? ARMED_VERDICT : null;
  const armSay = armed
    ? html`<span class="pv-arm"><span class="pv-sep" aria-hidden="true">·</span> ${translateTemplate('{sec}초 안에 한 번 더 누르면 저장', { sec: VERDICT_ARM_MS / 1000 })}</span>`
    : '';
  // [판정 취소]: a text action in the row (the viewer's link look, as the earlier link), after the state. It is its
  // verdict's own element (data-id): once that verdict goes the next one's is a new one, which a keyboard focus does
  // not carry over. It waits (aria-disabled) while the page's save is out, the first list is not in, or a cancel on
  // this page just ran.
  const canCancel = !!cur && canCancelVerdict(cur),
    cancelWaits = SAVING_LINES.has(slot) || loading || (CANCEL_HOLD.get(slot) || 0) > Date.now();
  const cancel =
    canCancel && cur
      ? html`<span class="pv-sep pv-cn" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" data-act="pv-cancel" \
data-ref="${cur.id}" data-id="${cur.id}" aria-label="${translateTemplate('판정 취소 — 내 판정 #{id}', { id: cur.id })}" \
${lineTipAttribute(!!chip, translate('이 판정을 거둡니다. 핀은 휴지통으로 가고, 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 상태 줄의 [되돌리기]가 되살립니다'))}${cancelWaits ? html` aria-disabled="true"` : ''}>${translate('판정 취소')}</button>`
      : '';
  // The earlier link is short - '이전 2건' ('+2 earlier') - and never cut: where its line is tight (.pv-tight,
  // fitPageLines) it is its count alone, '+2' (data-n, components.css). Its name says it whole ('이전 판정 2건 · 새
  // 판정으로 대체됨'), and so does its tooltip before what it is; the whole words would stand in the row and be cut to
  // fit. A dot sets it off from what comes before it, as the state's other parts are (.pv-ea, gone whenever the link
  // is): right after [✓ 채택 1]'s key digit on a stacked line, or after [판정 취소], a bare '+2' would read as a count
  // of that button's.
  const earlierCount = earlier.length,
    earlierName = translateTemplate('이전 판정 {n}건 · 새 판정으로 대체됨', { n: earlierCount });
  const early = earlierCount
    ? html`<span class="pv-sep pv-ea" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" data-n="${earlierCount}" aria-label="${earlierName}" \
${lineTipAttribute(!!chip, earlierName + ' — ' + translate('이 쪽의 더 새 판정으로 대체되어 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다'))}><span class="pv-early-w">${translateTemplate('이전 {n}건', { n: earlierCount })}</span></button>`
    : '';
  // The reading page's line - the one that floats - names what it decides: '7쪽 · [후보] PL18 · …' (figureName), cut to
  // fit. Its two spans are on every line, hidden but on the reading one: the line's children keep their places when the
  // reading page moves, so the morph (morphNode) never takes a focused button out of the page. A hidden one holds the
  // identifier, so every line is fitted as the reading line it may become (fitPageLines). The panel beside the pages
  // (verdict/view-panel.ts) names its page and figure whole: the title on rows of its own under the identifier, kept
  // even when empty, so the words below stand at one height for every page. A view-only PDF has no titles.
  const isReadingLine = READING_LINE_PAGE === page || !!panel,
    lineName = isReadingLine ? pageLineName(page) : { id: pageLineName(page).id, rest: '' };
  const name = panel
    ? html`<span class="pv-fig" translate="no"><span class="pv-fig-id">${lineName.id}</span>${isFigureKind(META ? META.kind : undefined) ? html`<span class="pv-fig-t">${lineName.rest}</span>` : ''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true">·</span>`
    : html`<span class="pv-fig" translate="no"${isReadingLine ? '' : html` hidden`}><span class="pv-fig-id">${lineName.id}</span>${lineName.rest ? html`<span class="pv-fig-t">${' · ' + lineName.rest}</span>` : ''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true"${isReadingLine ? '' : html` hidden`}>·</span>`;
  const keys = KEYED_PAGE === page,
    target = translateTemplate('{page}쪽', { page }),
    held = TAKEN_BACK_HOLD.get(slot),
    hold = held && held.until > Date.now() ? held.key : null;
  const pressedFor = (key: string) =>
    key !== want
      ? PRESSED_AS.NONE
      : next || savingKey !== undefined
        ? PRESSED_AS.SAVING
        : cur
          ? pressedAsOf(cur)
          : PRESSED_AS.NONE;
  // In the panel the pressed word's description is its context under the panel (pressedWordHint): a hover box over it
  // as well would cover the page's name above the words and say the same again. Only a long press shows it
  // (verdictButton's quiet).
  const said = (key: string) => !!panel && pressedFor(key) !== PRESSED_AS.NONE && pressedFor(key) !== PRESSED_AS.SAVING;
  const buttons = canVerdict()
    ? html`<span class="vd-btns">${verdicts.choices.map((choice, index) => verdictButton(choice, VERDICT_PLACE.PAGE, page, target, loading || choice.key === hold, keys ? index + 1 : 0, !!chip || said(choice.key), pressedFor(choice.key)))}</span>`
    : '';
  // The line's last failed save, said where it was pressed (LINE_SAVE_ERROR) - for the document and build on screen
  // only.
  const failure = LINE_SAVE_ERROR.get(page),
    failureShown = !!failure && failure.doc === DOC && !!META && failure.build === (META.pages_build || '');
  // always there, so the reason field after it keeps its place
  const err = html`<span class="pv-err"${failureShown ? '' : html` hidden`}>${failureShown && failure ? failure.text : ''}</span>`;
  // A take-back of this line's, while its status-line [되돌리기] lasts: the line offers it too (LINE_UNDO_OFFERS).
  const lineUndo = LINE_UNDO_OFFERS.get(slot),
    undo =
      lineUndo && NOTICES.has(lineUndo.n) && canVerdict()
        ? html`<span class="pv-sep pv-un" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-undo pv-un hit" \
data-act="pv-undo" data-id="u${lineUndo.id}" aria-label="${translateTemplate('되돌리기 — 거둔 판정 #{id}', { id: lineUndo.id })}">${translate('되돌리기')}</button>`
        : '';
  if (lineUndo && !undo) LINE_UNDO_OFFERS.delete(slot);
  const hint = pressedWordHint(
    page,
    verdicts,
    want,
    next || savingKey !== undefined ? PRESSED_AS.SAVING : cur ? pressedAsOf(cur) : PRESSED_AS.NONE,
  );
  // In the panel the words come right under the name - one place on the screen for every page, whatever the state under
  // them says - and the Tab order follows the rows: the words, then the state's links and actions.
  if (panel)
    return html`${name}${buttons}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${err}${hint}${reasonPopoverHtml(page)}`;
  return html`${name}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${buttons}${err}${hint}${reasonPopoverHtml(page)}`;
}
// A line control's description: data-tip, or - on a line that holds a save chip or its reason popover (pageLineHtml
// chip) - data-tip-press, which only a long press shows (platform/tooltip.ts): no box over either, and a long press
// still presses nothing.
function lineTipAttribute(quiet: boolean, tip: string) {
  return quiet ? html`data-tip-press="${tip}"` : html`data-tip="${tip}"`;
}
// The pressed word's context (taking a verdict back by pressing its word again must be found without a hover - a line
// holding a save chip or a popover draws no descriptions, and touch has none): one short sentence, the pressed word's
// description for assistive technology (aria-describedby="pv-on-<page>") and shown over the word group - never in the
// line's flow, so the line keeps its height - while the pressed word is hovered or has the keyboard's focus, and for a
// few seconds after a press made it the line's verdict (.pv-onshow, showPressedHint). '지금 삭제 판정 · 다시 누르면
// 판정 취소' on the person's own open verdict; someone else's or a handled one says it stays.
function pressedWordHint(page: number, verdicts: DocVerdicts, key: string | null, pressed: number) {
  const choice = key ? verdicts.choices.find((x) => x.key === key) : null;
  if (!choice || !pressed || pressed === PRESSED_AS.SAVING || !canVerdict()) return '';
  const say =
    pressed === PRESSED_AS.MINE
      ? translateTemplate('지금 {word} 판정 · 다시 누르면 판정 취소', { word: choice.label })
      : pressed === PRESSED_AS.OTHER
        ? translateTemplate('지금 {word} 판정 · 다른 사람의 판정이라 그대로 둡니다', { word: choice.label })
        : translateTemplate('지금 {word} 판정 · 처리된 판정이라 그대로 둡니다', { word: choice.label });
  return html`<span class="pv-onhint" id="pv-on-${page}" translate="no">${say}</span>`;
}
// A press made word key page `page`'s verdict: its line shows the pressed word's context for PRESSED_HINT_MS.
const PRESSED_HINT_MS = 4000;
function showPressedHint(page: number) {
  const line = document.querySelector('#doc .pv[data-page="' + page + '"]') as HTMLElement | null;
  if (!line) return;
  line.classList.add('pv-onshow');
  clearTimeout(line._onT);
  line._onT = setTimeout(() => line.classList.remove('pv-onshow'), PRESSED_HINT_MS);
}
// Draws page `page`'s line. The list redraws on every poll and many other changes, so a line is never rewritten: what
// changed is changed in place (morphNode) - its words and links, a button's state - and every button, the '#N' link and
// the earlier link stay the same elements. A press whose down and up straddle a redraw still lands on its button (a
// rewritten one would send the click to the line), and the focus stays where it was, also on a '#N' whose number just
// changed. A line whose words are what it shows is left alone. Every verdict pin the line accounts for - the current
// one and the earlier ones - draws no page-size mark.
const LINE_TEXT = new WeakMap() as WeakMap<HTMLElement, string>; // what fillPageLine last wrote into each line
function fillPageLine(line: HTMLElement, page: number, list: Pin[] | undefined, verdicts: DocVerdicts) {
  line.dataset.page = String(page);
  line.classList.toggle('reading', READING_LINE_PAGE === page);
  const cur = list && list[0];
  if (cur) line.dataset.pin = String(cur.id);
  else delete line.dataset.pin;
  (list || []).forEach((pin) => SHOWN_ON_PAGE_LINES.add(pin.id));
  line.setAttribute('role', 'group');
  line.setAttribute('aria-label', translateTemplate('{page}쪽 판정', { page }));
  // a save's undo chip (drawChips) stays on its line; drawChips moves it if it is another pin's
  const chip = line.querySelector(':scope>.nt-chip');
  // While its save chip stands or its reason popover is open the line draws no descriptions: no box over either.
  const markup = pageLineHtml(page, list, verdicts, !!chip || isReasonOpenOn(page), line.id === 'pv-panel');
  if (LINE_TEXT.get(line) === markup.text) return;
  LINE_TEXT.set(line, markup.text);
  // The focused reason field keeps the focus and the caret when the line around it changes shape (its verdict's save
  // landing while it is typed in: a morph by place can replace it), so what is typed next stays text - never a verdict
  // key.
  const active = document.activeElement,
    field = isReasonField(active) && line.contains(active) ? (active as HTMLTextAreaElement) : null,
    caret = field ? [field.selectionStart, field.selectionEnd] : null;
  if (chip) chip.remove();
  const next = document.createElement('div');
  setHtml(next, markup);
  morphChildren(line, next);
  if (chip) line.appendChild(chip);
  line.classList.toggle('pv-pop-open', !!line.querySelector(':scope>.pv-pop'));
  fillReasonField(line);
  if (field && caret && !field.isConnected) {
    const redrawn = line.querySelector(
      '.pv-pop .pv-reason[data-id="' + field.dataset.id + '"]',
    ) as HTMLTextAreaElement | null;
    if (redrawn) {
      redrawn.focus({ preventScroll: true });
      redrawn.setSelectionRange(caret[0], caret[1]);
    }
  }
}
// Makes the target's children the source's, keeping every node that is the same kind in the same place (morphNode). The
// child that is or holds the reason field stays where it is when the source has the same one anywhere: the nodes before
// and after it are made the source's on either side of it. By place alone a node new before it (the pressed word's
// context, once the save the popover waited for lands) would take its place and the field would be drawn again, which
// ends an input method's composition in it and loses the typed reason.
function morphChildren(target: Node, source: Node) {
  const targetChildren = [...target.childNodes],
    sourceChildren = [...source.childNodes],
    fieldAt = targetChildren.findIndex(holdsReasonField),
    sourceFieldAt = fieldAt < 0 ? -1 : sourceChildren.findIndex((node) => canMorph(targetChildren[fieldAt], node));
  if (sourceFieldAt < 0) {
    morphChildRun(target, targetChildren, sourceChildren, null);
    return;
  }
  morphChildRun(
    target,
    targetChildren.slice(0, fieldAt),
    sourceChildren.slice(0, sourceFieldAt),
    targetChildren[fieldAt],
  );
  morphNode(targetChildren[fieldAt], sourceChildren[sourceFieldAt]);
  morphChildRun(target, targetChildren.slice(fieldAt + 1), sourceChildren.slice(sourceFieldAt + 1), null);
}
// Makes a run of the parent's children (targetRun) read as sourceRun, by place: the new nodes past its end go in before
// `at` (null: at the end), and the old ones past the source run's end go.
function morphChildRun(parent: Node, targetRun: ChildNode[], sourceRun: ChildNode[], at: Node | null) {
  sourceRun.forEach((node, index) => {
    if (index < targetRun.length) morphNode(targetRun[index], node);
    else parent.insertBefore(node, at);
  });
  targetRun.slice(sourceRun.length).forEach((node) => node.remove());
}
// Whether a node is the reason field or holds it.
function holdsReasonField(node: Node) {
  return node instanceof Element && (isReasonField(node) || !!node.querySelector('.pv-reason'));
}
// Whether morphNode keeps a target node to read as the source node: the same kind of node - for an element the same
// tag, data-act and data-id (a reason field of another pin is another field, never one keeping the first pin's typed
// text).
function canMorph(target: Node, source: Node) {
  return (
    target.nodeType === source.nodeType &&
    target.nodeName === source.nodeName &&
    !(
      target instanceof Element &&
      source instanceof Element &&
      (target.getAttribute('data-act') !== source.getAttribute('data-act') ||
        target.getAttribute('data-id') !== source.getAttribute('data-id'))
    )
  );
}
// Makes a target node read as the source node: the same text, or the same element (canMorph) with the source's
// attributes and children; another kind of node takes the target's place.
function morphNode(target: Node, source: Node) {
  if (!canMorph(target, source)) {
    (target as ChildNode).replaceWith(source);
    return;
  }
  if (!(target instanceof Element && source instanceof Element)) {
    if (target.nodeValue !== source.nodeValue) target.nodeValue = source.nodeValue;
    return;
  }
  [...target.attributes].forEach((x) => {
    if (!source.hasAttribute(x.name)) target.removeAttribute(x.name);
  });
  [...source.attributes].forEach((x) => {
    if (target.getAttribute(x.name) !== x.value) target.setAttribute(x.name, x.value);
  });
  morphChildren(target, source);
}
// The width of each line and whether it is one row or stacked - per line. A line is its own page's width, never past
// what the PDF area shows; a page narrower than the widest has a line as narrow, under it. Where the pages are fitted
// (no sideways scroll) a line also ends before what lies over the area's right side (measureInsetRight: an overlay
// panel, the closed panel's status box) and still starts where its page does: centred with the room cut on one side,
// the sticky line would be pushed past the page's left edge. A zoomed page's line keeps the room the area shows and
// stays in view as the page scrolls sideways (sticky). Then each line on its own (fitPageLines). Measured only while
// the pages are laid out (the changes view hides them); read and written in batches. a cut line narrower than this
// keeps its page's width and lets the sticky edge push it instead
const MIN_CUT_LINE_WIDTH = 320;
function sizePageLines() {
  const insetRight = measureInsetRight(),
    area = $('#left'),
    lines = $$('#doc .pv');
  area.style.setProperty('--pv-inset-r', insetRight + 'px');
  INSET_RIGHT = insetRight;
  $('#doc').classList.remove('pv-stack');
  if (!lines.length || !lines[0].getClientRects().length) return;
  // A zoom or a new width took the room across its bar: the lines move at the next frame (stickReadingLine), never
  // here. A zoom restores its place after this call, and the reading page read before that is not the one being read
  // (verdict/view-panel.ts).
  if (shouldStandBeside() !== IS_BESIDE_PAGES) stickSoon();
  if (IS_BESIDE_PAGES) {
    fitPageLines(lines);
    return;
  } // the panel keeps its own width
  const room = pdfAreaInnerWidth() - insetRight,
    areaRect = area.getBoundingClientRect(),
    fitted = area.scrollWidth <= area.clientWidth + 1;
  const end =
    // the room's right edge on screen
    areaRect.left + area.clientLeft + area.clientWidth - parseFloat(getComputedStyle(area).paddingRight) - insetRight;
  const at = lines.map((line) => {
    const pageElement = document.getElementById('p' + line.dataset.page),
      block = line.parentElement;
    if (!pageElement || !block) return null;
    const rect = pageElement.getBoundingClientRect();
    return {
      w: parseFloat(pageElement.style.width) || rect.width,
      left: rect.left,
      off: rect.left - block.getBoundingClientRect().left,
    };
  });
  lines.forEach((line, index) => {
    const place = at[index];
    let width = place ? Math.min(place.w, room) : room,
      marginLeft = '';
    if (place && fitted && end - place.left < width && end - place.left >= MIN_CUT_LINE_WIDTH) {
      width = end - place.left;
      marginLeft = Math.round(place.off) + 'px';
    }
    line.style.width = Math.round(width) + 'px';
    line.style.marginLeft = marginLeft;
  });
  fitPageLines(lines);
}
// The verdict pins saved by a key on this screen (LAST_KEY_SAVE, each in turn): their lines (.pv-kw) are fitted at
// either look of the way to the reason (fitPageLines). The last key save's alone says 'Enter 이유 쓰기', and fitting
// one again on [이유 추가] alone when it stops being the last would move the pages under the next key save.
const KEY_SAVED_PINS = new Set() as Set<number>;
// One row or stacked, decided per line (.pv-stack), so one line with an earlier verdict or a reason never stacks every
// line of the document over the plot. Each line is laid out as one row - the figure's title cut first, down to its
// identifier ('6쪽 · PL17', pageLineName; --pv-fig-min), then the reason and the earlier link (components.css) - and
// stacks only when its state's own words, [판정 취소] and its buttons still cannot share the row: the state runs past
// its share, or the buttons went to a row of their own (a narrow page). On the wide band a line that does not fit first
// lets the reason go further and the earlier link say its count alone (.pv-tight): a desktop keeps one row, since a
// second row covers the plot. A line narrower than a verdict's state beside its words stacks whatever it shows, so a
// press never stacks it. A line whose confirm word waits for its second press, or whose save is out, keeps the rows it
// has (holdsRows): its words must not move between the two presses, or the second press lands elsewhere. The save chip
// is placed after (placeLineChips). Read and written in batches. The PDF area does not anchor its scroll for the pass
// (holdPageView): the pass grows every line above the reading page and shrinks it back (#doc.pv-measure). Anchoring
// that follows part of it would move the pages down when a reason opens, and while pinch-zoomed Chromium carries the
// anchoring of the shrink - the area is the page's root scroller there - into the zoomed view, which would jump to the
// page's top at every drawing of the lines. The pass moves nothing below a line it measures either (keepLineBlocks):
// WebKit anchors the growth on the next page's block and not the shrink, which would move a phone's pages at a key
// save.
function fitPageLines(lines: HTMLElement[]) {
  const panel = lines.find((line) => line.id === 'pv-panel');
  if (panel) {
    fitPanel(panel);
    lines = lines.filter((line) => line !== panel);
    if (!lines.length) return;
  } // the panel: rows down it, never one row (verdict/view-panel.ts)
  const held = lines.map(holdsRows),
    docElement = $('#doc'),
    hold = holdPageView(true),
    kept = keepLineBlocks(lines);
  try {
    // a line skipped far from the view is laid out to be measured, and keeps its height after (letFarLinesGo)
    holdFarLines(lines);
    if (LAST_KEY_SAVE) KEY_SAVED_PINS.add(LAST_KEY_SAVE);
    lines.forEach((line, index) => {
      line.classList.toggle('pv-kw', KEY_SAVED_PINS.has(Number(line.dataset.pin)));
      if (!held[index]) {
        line.classList.remove('pv-stack', 'pv-tight', 'pv-early-out');
        line.style.removeProperty('--pv-t-h');
      }
    });
    // Every line is measured as the reading line (#doc.pv-measure shows each hidden identifier, components.css):
    // otherwise a line that stacks only while it is read would shrink when the reading page leaves, and move the pages.
    docElement.classList.add('pv-measure');
    // The figure's least width is its identifier's (--pv-fig-min): its title's own text would otherwise count in it.
    const ids = lines.map((line) => {
      const identifier = line.querySelector(':scope>.pv-fig>.pv-fig-id');
      return identifier && identifier.getClientRects().length ? Math.ceil(identifier.getBoundingClientRect().width) : 0;
    });
    lines.forEach((line, index) => {
      const width = ids[index] + 'px';
      if (line.style.getPropertyValue('--pv-fig-min') !== width) line.style.setProperty('--pv-fig-min', width);
    });
    // How far a line's state runs past its share, in px (its parts, also those inside a display: contents span - the
    // reason and [이유 추가]; 0 or less where it holds), less keySaveStateCut - a key save's way to the reason is drawn
    // at the wider of its two looks (--pv-add-w, set below) with the earlier link beside it, which it never shows at
    // once -, or Infinity where the buttons went to a row of their own. Its row does not hold (tight) past 1px.
    const past = (line: HTMLElement) => {
      const state = line.querySelector(':scope>.pv-t'),
        group = line.querySelector(':scope>.vd-btns');
      if (!state) return -Infinity;
      const stateRect = state.getBoundingClientRect();
      if (group && group.getClientRects().length > 0 && group.getBoundingClientRect().top >= stateRect.bottom - 1)
        return Infinity;
      const right = [...state.querySelectorAll(':scope>*,:scope>*>*')].reduce(
        (most, child) =>
          child.getClientRects().length > 0 ? Math.max(most, child.getBoundingClientRect().right) : most,
        -Infinity,
      );
      return right - stateRect.right - keySaveStateCut(line, state, addDifference);
    };
    const tight = (line: HTMLElement) => past(line) > 1;
    // A line too narrow for the state a press brings beside its words stacks whatever it shows now, so a press that
    // turns '판정 없음' into '판정 #26 보류 · 처리 대기 · 이유 추가 · 판정 취소' never stacks it then and moves every
    // word under the finger. That state's width is measured, not guessed (measureStateNeed), and so is all that shares
    // its row: the words as they are drawn, with the check a press puts on one of them (STATE_NEED.check) where none is
    // pressed yet; the identifier and the dot after it; and the row's gaps between the four (its column gap). The sum
    // is the row the press brings, to the subpixel: a fixed allowance is too much for a resting line or too little for
    // a press (the English words are sized for a 620px line, ui_en.json).
    const need = lines.length ? measureStateNeed(lines[0]) : 0,
      gap = lines.length ? parseFloat(getComputedStyle(lines[0]).columnGap) || 0 : 0;
    // A key save's line - read, it says 'Enter 이유 쓰기'; at rest, [이유 추가] - lays its way to the reason out at the
    // wider of the two (the probe's, STATE_NEED.add; .pv-kw, components.css #doc.pv-measure), so it is fitted the same
    // whichever page is read. Fitted on the look it shows, a line within the difference between them would stack only
    // while it is read.
    const addWidths = STATE_NEED.add,
      addDifference = Math.max(0, addWidths[1] - addWidths[0]),
      addWidth = Math.max(addWidths[0], addWidths[1]) + 'px';
    if (docElement.style.getPropertyValue('--pv-add-w') !== addWidth)
      docElement.style.setProperty('--pv-add-w', addWidth);
    const widthOf = (element: Element | null) =>
      element && element.getClientRects().length ? element.getBoundingClientRect().width : 0;
    const narrow = lines.map((line, index) => {
      if (held[index]) return false;
      const group = line.querySelector(':scope>.vd-btns'),
        identifierWidth = widthOf(line.querySelector(':scope>.pv-fig>.pv-fig-id'));
      if (!group || !group.getClientRects().length) return false;
      const press = group.querySelector(':scope>.vd-b[aria-pressed="true"]') ? 0 : STATE_NEED.check,
        id = identifierWidth ? identifierWidth + widthOf(line.querySelector(':scope>.pv-fig-sep')) + 2 * gap : 0;
      return line.getBoundingClientRect().width < widthOf(group) + press + id + gap + need;
    });
    let over = lines.map((line, index) => !held[index] && (narrow[index] || tight(line)));
    // A tight line whose row holds all but its earlier link's count lets that step out too (.pv-early-out) rather than
    // stack: the last thing a desktop row gives way, at its bar - a line the person saved by a key over an earlier
    // verdict there ('+1' beside [이유 추가] at rest, which 'Enter 이유 쓰기' takes the place of while it is read:
    // components.css).
    const out = lines.map(() => false);
    if (LAYOUT === LAYOUT_MODE.WIDE && over.some((isOver) => isOver)) {
      lines.forEach((line, index) => {
        if (over[index]) line.classList.add('pv-tight');
      });
      over = lines.map((line, index) => {
        if (!over[index] || narrow[index]) return over[index];
        const overflow = past(line);
        if (overflow <= 1) return false;
        const state = line.querySelector(':scope>.pv-t') as HTMLElement;
        out[index] = overflow - earlierLinkRoom(state) + keySaveStateCut(line, state, addDifference) <= 1;
        return !out[index];
      });
      lines.forEach((line, index) => {
        if (out[index]) line.classList.add('pv-early-out');
      });
    }
    lines.forEach((line, index) => {
      if (over[index]) line.classList.add('pv-stack');
    });
    // A stacked line's state rows are the reading line's too: their height, measured here with what only the reading
    // line shows ([이유 추가], laid out unseen), is the least the state takes (--pv-t-h, components.css), so a line
    // whose state wraps to a second row only while it is read (beside an earlier link) does not grow when it is read.
    // Where that is more than the state takes now (.pv-t-kept), its rows stand at the top and the room is kept under
    // them: centred in it, a resting line's state would stand off its identifier's row.
    const keptHeights = lines.map((line, index) => {
      const state = over[index] ? line.querySelector(':scope>.pv-t') : null;
      return state ? state.getBoundingClientRect().height : 0;
    });
    docElement.classList.remove('pv-measure');
    const nat = lines.map((line, index) =>
      keptHeights[index] ? (line.querySelector(':scope>.pv-t') as HTMLElement).getBoundingClientRect().height : 0,
    );
    lines.forEach((line, index) => {
      if (held[index]) return;
      const isKept = keptHeights[index] > nat[index] + 0.5;
      line.classList.toggle('pv-t-kept', isKept);
      if (isKept) line.style.setProperty('--pv-t-h', keptHeights[index] + 'px');
    });
    // The lines' fitted heights, their kept rows included: what moves now is real, and letLineBlocks keeps the reading
    // page where it stood. Let go before the rows are kept again, a stacked line above the reading page would shrink
    // there and grow back after the correction, and with the area not anchoring for the pass (holdPageView) the reading
    // page would go down by the rows.
    letLineBlocks(kept);
    placeLineChips(lines);
    // A word group that wraps keeps every button at its own width (fitWrappedWords), read for every line before any is
    // written.
    const groups = lines.map((line) => line.querySelector('.vd-btns')),
      wrap = groups.map(
        (group) =>
          !!group &&
          new Set([...group.children].map((button) => Math.round(button.getBoundingClientRect().top))).size > 1,
      );
    groups.forEach((group, index) => {
      if (group) group.classList.toggle('wrapped', wrap[index]);
    });
    keepFocusOnLine(lines);
  } finally {
    // Also when a step throws: never left measuring, every line keeps the height it is drawn at and may be skipped
    // again (letFarLinesGo, read once the measure is gone), and the view anchors again only after that - whatever
    // letFarLinesGo does.
    docElement.classList.remove('pv-measure');
    letLineBlocks(kept);
    try {
      letFarLinesGo(lines);
    } finally {
      holdPageView(false, hold);
    }
  }
}
// Keeps the block of each line fitPageLines is about to measure at the height it is drawn at, until letLineBlocks: the
// pass takes a line's rows off and measures it as the reading line (#doc.pv-measure), and the line may grow inside its
// block, but the block, and the pages after it, stand still. So the area's scroll anchoring - WebKit's too, which
// carries the growth and not the shrink - has nothing to follow, while a line whose fitted height does change moves the
// pages after the pass. A block's height set, its last line's bottom margin does not collapse through it: the block
// carries the space to the next block itself. The last block, with nothing after it, is left alone. Read before any is
// written; what each had inline is put back.
function keepLineBlocks(lines: HTMLElement[]): [HTMLElement, string, string][] {
  const set: Set<HTMLElement> = new Set();
  lines.forEach((line) => {
    const block = line.parentElement;
    if (block && block.classList.contains('pgw') && block.nextElementSibling) set.add(block);
  });
  const blocks = [...set],
    at = blocks.map((block) => {
      const rect = block.getBoundingClientRect(),
        next = block.nextElementSibling as Element;
      return [rect.height, next.getBoundingClientRect().top - rect.bottom];
    });
  const kept: [HTMLElement, string, string][] = [];
  blocks.forEach((block, index) => {
    const [height, gap] = at[index];
    if (!height) return;
    kept.push([block, block.style.height, block.style.marginBottom]);
    block.style.height = height + 'px';
    block.style.marginBottom = gap + 'px';
  });
  return kept;
}
// Lets the blocks keepLineBlocks held go to their lines' fitted heights, keeping the view by hand: the page under the
// reading line stands where it stood. A block's height on the anchor's path - the reading page's own block is held too
// - suppresses the PDF area's scroll anchoring, so every line above that changes its height would move the view with
// nothing to follow. The area's own anchoring is off for the step, so it adds no correction of its own, and is put back
// as it was (a pinch-zoom hold's included). A touch screen at its very top stays there, as restoreAnchor keeps it: the
// space above page 1 is not scrolled away. A jump on its way (JUMP_TARGET) is left to go on: a script's write ends a
// smooth scroll where it stands, so fitting a line as a far jump passes it would stop the jump there, short of its
// figure. Every glide has the settling, which measures its place again when it rests and glides what moved
// (arrivalWatch, arrivalSettle) - unless the person has acted meanwhile, which lets it go.
function letLineBlocks(kept: [HTMLElement, string, string][]) {
  if (!kept.length) return;
  const area = $('#left'),
    anchor = area.getClientRects().length ? topAnchor(readingDepth(area)) : null;
  const pageElement = anchor ? document.getElementById('p' + anchor.page) : null,
    y = pageElement ? pageElement.getBoundingClientRect().top : 0,
    was = area.style.getPropertyValue('overflow-anchor');
  if (pageElement) area.style.setProperty('overflow-anchor', 'none');
  kept.forEach(([block, height, margin]) => {
    block.style.height = height;
    block.style.marginBottom = margin;
  });
  kept.length = 0;
  if (!pageElement || !anchor) return;
  const drift = pageElement.getBoundingClientRect().top - y;
  // a touch screen's top stays the top (restoreAnchor)
  if (Math.abs(drift) > 0.5 && !anchor.atTop && JUMP_TARGET === null) area.scrollTop += drift;
  void area.offsetHeight;
  if (was) area.style.setProperty('overflow-anchor', was);
  else area.style.removeProperty('overflow-anchor');
}
// Holds the view where it is across fitPageLines's pass (on) and lets go after it (off, given what on returned): the
// PDF area does not anchor its scroll (overflow-anchor), and its layout is brought up to date before it anchors again,
// so the anchor it then takes is where the pass left the pages - never a measure's grown lines. The pass holds the
// blocks of the lines it measures (keepLineBlocks), but #doc.pv-measure lays out every line in the document as the
// reading line, those it does not hold too: a stacked line above the reading page measures a row taller (the key marks
// on its words) and pushes the reading page down and back within the pass. Anchoring that follows part of that would
// move the pages when a reason opens or closes, and while the page is pinch-zoomed Chromium carries a shrink's
// anchoring into the zoomed view. Nothing the pass does is to move the pages: what moves after it is the lines' fitted
// heights, which letLineBlocks lets go with the reading page kept where it stood. On returns the area's own value it
// replaced, which off puts back (a pass inside a pass leaves the outer one's hold), or null where it held nothing (no
// PDF area). No scroll of its own, ever.
function holdPageView(on: boolean, was?: string | null): string | null {
  const area = $('#left');
  if (!on) {
    if (typeof was !== 'string') return null;
    void area.offsetHeight;
    if (was) area.style.setProperty('overflow-anchor', was);
    else area.style.removeProperty('overflow-anchor');
    return null;
  }
  if (!area) return null;
  const previous = area.style.getPropertyValue('overflow-anchor');
  area.style.setProperty('overflow-anchor', 'none');
  return previous;
}
// The width the state of a person's fresh verdict takes on a line in a row, drawn in a hidden line like the given one
// (its text size, the screen's language and pointer) and kept until those or the next pin number's digits change. Two
// states follow a press: after a click '판정 #0 <the longest word> · 처리 대기 · 이유 추가 · 판정 취소', and on a mouse
// screen after a key 'Enter 이유 쓰기' in place of [이유 추가] - the wider of the two is the need, with one more gap of
// the state's row for a save's words ('· 보류 저장 중…', .pv-busy), which give way down to nothing while the save is
// out (components.css). The pin number is drawn with as many digits as the next pin's (topPinId), each a 0. A line
// narrower than that beside its words and identifier is stacked before any press (fitPageLines). Measuring the click
// state alone would let a key save near the bar stack the line under the press, and a second save's words push [판정
// 취소] out of the held row. The probe then draws the longest word pressed and not (its check before it, its weight;
// one key mark on both): what a press adds to the words, kept as STATE_NEED.check, which a line with no pressed word
// counts so its first press does not stack it. STATE_NEED.add: the way to the reason's own width as [이유 추가] and as
// 'Enter 이유 쓰기' (a mouse screen's; [이유 추가]'s again on a touch one), which every line is fitted at the wider of
// (fitPageLines).
let STATE_NEED = { key: '', w: 0, check: 0, add: [0, 0] };
function measureStateNeed(line: HTMLElement) {
  const verdicts = pageVerdictsOn();
  if (!verdicts) return 0;
  const word = verdicts.choices
      .map((choice) => choice.label)
      .reduce((longest, label) => (label.length > longest.length ? label : longest), ''),
    fine = matchMedia('(pointer:fine)').matches,
    number = '#' + '0'.repeat(String(topPinId() + 1).length);
  const key = [
    getComputedStyle(line).fontSize,
    translate('판정'),
    word,
    COARSE_POINTER_QUERY.matches,
    fine,
    number,
  ].join('|');
  if (STATE_NEED.key === key) return STATE_NEED.w;
  const probe = document.createElement('div');
  probe.className = 'pv';
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText =
    // its own width, not the lines' (fitPageLines)
    'position:absolute;left:0;top:0;width:max-content;visibility:hidden;pointer-events:none;--pv-add-w:0px';
  $('#doc').appendChild(probe);
  const state = (byKey: boolean) => {
    setHtml(
      probe,
      html`<span class="pv-t"><span class="pv-s">${translate('판정')} <span class="pin-ref pv-ref hit">${number}</span> <b class="vd-w">${word}</b></span><span class="pv-sep">·</span>\
<span class="pv-st">${translate('처리 대기')}</span><span class="pv-ra"><span class="pv-sep">·</span><button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">\
${byKey ? html`<kbd class="pv-kbd">Enter</kbd> ${translate('이유 쓰기')}` : translate('이유 추가')}</button></span>\
<span class="pv-sep pv-cn">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" tabindex="-1">${translate('판정 취소')}</button></span>`,
    );
    const stateRow = probe.firstElementChild as HTMLElement,
      addButton = stateRow.querySelector('.pv-add') as HTMLElement;
    return [
      stateRow.getBoundingClientRect().width + (parseFloat(getComputedStyle(stateRow).columnGap) || 0),
      addButton.getBoundingClientRect().width,
    ];
  };
  const clickState = state(false),
    keyState = fine ? state(true) : clickState,
    width = Math.ceil(Math.max(clickState[0], keyState[0]));
  setHtml(
    probe,
    html`<span class="vd-btns"><button type="button" class="vd-b" aria-pressed="true" data-kn="1" tabindex="-1">${lucideIcon('check')}<span class="lbl">${word}</span></button>\
<button type="button" class="vd-b" aria-pressed="false" data-kn="1" tabindex="-1"><span class="lbl">${word}</span></button></span>`,
  );
  const widths = [...probe.querySelectorAll('.vd-b')].map((x) => x.getBoundingClientRect().width),
    check = Math.max(0, widths[0] - widths[1]);
  probe.remove();
  STATE_NEED = { key, w: width, check, add: [clickState[1], keyState[1]] };
  return width;
}
// A web font that arrives after the lines were measured - the bundled Pretendard after the fallback face - changes
// every width: the state's width is measured again and every line fits itself again (sizePageLines), once each font
// load is done and when the fonts are ready after boot. Kept from the fallback face, a width near the stacking
// threshold would let the first save still move the words.
function refitForFonts() {
  STATE_NEED = { key: '', w: 0, check: 0, add: [0, 0] };
  if ($$('#doc .pv').length) sizePageLines();
}
if (document.fonts) {
  document.fonts.addEventListener('loadingdone', refitForFonts);
  document.fonts.addEventListener('loadingerror', refitForFonts);
  document.fonts.ready.then(refitForFonts);
}
// How much less than drawn a key save's line's state takes at most in a row, while it is fitted (fitPageLines): with
// its way to the reason drawn at the wider of its looks (`difference` px more than [이유 추가]: 'Enter 이유 쓰기') and
// the earlier link beside it - which a tight line shows beside [이유 추가] but not beside 'Enter 이유 쓰기'
// (components.css) - the more of the two looks takes `difference` less, or the link and its gap less, whichever is
// less. 0 for any other line, and for one that is not tight: it shows the link beside both.
function keySaveStateCut(line: HTMLElement, state: Element, difference: number): number {
  if (
    !difference ||
    !line.classList.contains('pv-kw') ||
    !line.classList.contains('pv-tight') ||
    !state.querySelector(':scope>.pv-ra>.pv-add')
  )
    return 0;
  const earlierRoom = earlierLinkRoom(state);
  return earlierRoom ? Math.min(difference, earlierRoom) : 0;
}
// A focus on a control of one of these lines that its fitting just took out - the earlier link stepping out at a tight
// row's bar (.pv-early-out), or beside 'Enter 이유 쓰기' or [되돌리기] on a row that turned tight (components.css),
// after a resize, a zoom of the browser or of the pages, or a redraw - moves at once, without a scroll, to the control
// before it on its line ([판정 취소], 'Enter 이유 쓰기', the '#N' link), else to the line's first. Hidden with the
// focus on it, the link would take the focus away to nothing and the next Tab would start from the top (Chromium lets a
// hidden focus go a moment later: the move is made before that). Every way the fitting hides a control comes through
// here, and so does a phone's floating line holding [판정 취소] back (leanFloatingLine).
function keepFocusOnLine(lines: HTMLElement[]) {
  const active = document.activeElement as HTMLElement | null,
    line = active && active.closest ? (active.closest('#doc .pv') as HTMLElement | null) : null;
  if (
    !active ||
    !line ||
    !lines.includes(line) ||
    (active.getClientRects().length && getComputedStyle(active).visibility !== 'hidden')
  )
    return;
  const controls = [...line.querySelectorAll(TABBABLE)].filter(isTabStop),
    before = controls.filter((x) => !!(x.compareDocumentPosition(active) & Node.DOCUMENT_POSITION_FOLLOWING));
  const to = before.length ? before[before.length - 1] : controls[0];
  if (to) to.focus({ preventScroll: true });
}
// The room a state's earlier link takes in its row as drawn - its width, the dot before it and the gap before each - or
// 0 where it shows none.
function earlierLinkRoom(state: Element): number {
  const link = state.querySelector(':scope>.pv-early');
  if (!link || !link.getClientRects().length) return 0;
  const gap = parseFloat(getComputedStyle(state).columnGap) || 0,
    dot = link.previousElementSibling,
    dotWidth =
      dot && dot.classList.contains('pv-ea') && dot.getClientRects().length
        ? dot.getBoundingClientRect().width + gap
        : 0;
  return link.getBoundingClientRect().width + gap + dotWidth;
}
// Whether a line keeps the rows it has now: its confirm word waits for the second press, or its save is out.
function holdsRows(line: HTMLElement) {
  const page = Number(line.dataset.page) || 0;
  return (
    (!!ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page === page) ||
    SAVING_LINES.has(pageLineSlot(page))
  );
}
// The save chip on a line ('#42 저장됨 · 채택 [되돌리기]') never changes the line: it is laid over it (notices.css), in
// room no control or state word of the line takes - never over the figure's identifier, the state, a text action, a
// word or a focus ring (8px clear of each), nor over the reason popover. The first room that holds it: in a row,
// between everything before the words and the words; in a stacked line, after the end of the state's last row; then
// over the figure's title after its identifier (its own row on a stacked line) - words that only describe; its words
// shown where any room holds them. Its words fold first (.pv-chip-short: its icon and [되돌리기]), then its icon
// (.pv-chip-bare); where not even [되돌리기] fits anywhere, the undo goes to the status line (chipAway). In the line's
// flow the chip would add a row on a phone and move the words under a waiting finger, and laid over them it would take
// presses meant for [이유 추가] and [판정 취소]. --pv-chip-r and --pv-chip-y place it from the line's right edge and
// top. how long a chip with no room waits for its line to settle before its undo goes to the status line
const CHIP_WAIT_MS = 3000;
const CHIP_WAIT_TIMERS = new WeakMap() as WeakMap<HTMLElement, number>;
function placeLineChips(lines: HTMLElement[]) {
  const chips = lines.map((line) => line.querySelector(':scope>.nt-chip') as HTMLElement | null);
  lines.forEach((line, index) => {
    if (chips[index]) {
      line.classList.toggle('pv-chip-short', false);
      line.classList.toggle('pv-chip-bare', false);
    } else line.classList.remove('pv-chip-wait');
  });
  const got = lines.map((line, index) => {
    const chip = chips[index];
    if (!chip) return null;
    const lineRect = line.getBoundingClientRect(),
      rectOf = (element: Element) => element.getBoundingClientRect(),
      shown = (element: Element) => element.getClientRects().length > 0;
    const words = [...line.querySelectorAll(':scope>.vd-btns>*')].filter(shown).map(rectOf);
    const parts = [
      ...line.querySelectorAll(':scope>.pv-fig>.pv-fig-id,:scope>.pv-fig-sep,:scope>.pv-t *,:scope>.pv-err'),
    ]
      .filter((element) => shown(element) && !element.closest('.pv-pop'))
      .map(rectOf);
    const pop = line.querySelector(':scope>.pv-pop'),
      keep = parts.concat(words, pop && shown(pop) ? [rectOf(pop)] : []),
      chipRect = rectOf(chip),
      gap = parseFloat(getComputedStyle(chip).columnGap) || 0,
      partWidth = (selector: string) => {
        const element = chip.querySelector(selector);
        return element && shown(element) ? rectOf(element).width + gap : 0;
      }; // a part and the chip's own gap beside it, as measured: the folded chip is placed at its real width
    const sizes = [
      chipRect.width,
      chipRect.width - partWidth('.nt-t'),
      chipRect.width - partWidth('.nt-t') - partWidth('.nt-ic'),
    ];
    // A room on the row through y (a box's middle) from left to right: the room less 8px off every part in that row's
    // height.
    const room = (y: number, left: number, right: number) => {
      const top = y - chipRect.height / 2,
        bot = y + chipRect.height / 2;
      let start = left,
        end = right;
      keep
        .filter((box) => box.top < bot && box.bottom > top)
        .forEach((box) => {
          if (box.right <= (start + end) / 2) start = Math.max(start, box.right + 8);
          else end = Math.min(end, box.left - 8);
        });
      return { a: start, z: end, y };
    };
    const rooms: { a: number; z: number; y: number }[] = [];
    const stack = line.classList.contains('pv-stack');
    if (!stack && words.length) {
      const y = (Math.min(...words.map((box) => box.top)) + Math.max(...words.map((box) => box.bottom))) / 2;
      rooms.push(
        room(
          y,
          parts
            .filter((box) => box.top < y && box.bottom > y)
            .reduce((most, box) => Math.max(most, box.right), lineRect.left) + 8,
          Math.min(...words.map((box) => box.left)) - 8,
        ),
      );
    } else {
      const stateBoxes = [...line.querySelectorAll(':scope>.pv-t *')]
        .filter((element) => shown(element) && !element.closest('.pv-pop'))
        .map(rectOf)
        .filter((box) => box.height > 0);
      if (stateBoxes.length) {
        const last = Math.max(...stateBoxes.map((box) => box.top)),
          row = stateBoxes.filter((box) => box.bottom > last + 1),
          y = (Math.min(...row.map((box) => box.top)) + Math.max(...row.map((box) => box.bottom))) / 2;
        rooms.push(room(y, row.reduce((most, box) => Math.max(most, box.right), lineRect.left) + 8, lineRect.right));
      }
    }
    const id = line.querySelector(':scope>.pv-fig>.pv-fig-id'),
      title = line.querySelector(':scope>.pv-fig>.pv-fig-t');
    if (id && title && shown(title)) {
      const idRect = rectOf(id);
      rooms.push(
        room((idRect.top + idRect.bottom) / 2, idRect.right + 8, stack ? lineRect.right : rectOf(title).right),
      );
    }
    for (let k = 0; k < 3; k++)
      for (const candidate of rooms)
        if (sizes[k] <= candidate.z - candidate.a)
          return {
            r: Math.round(lineRect.right - candidate.z),
            y: Math.round(candidate.y - lineRect.top),
            short: k > 0,
            bare: k > 1,
          }; // its words where any room holds them
    return { away: true };
  });
  // Going to the status line is for good (chipAway), so it is never decided on a line that is about to change: while
  // its save is out or a confirm word waits (holdsRows - the chip comes before the save's end, and the line then shows
  // the new verdict and still '· 보류 저장 중…', so its room is about to grow), or while a web font loads (a fresh
  // state's new characters are drawn in a fallback face until their Pretendard slice arrives). It waits unseen
  // (.pv-chip-wait) and is placed when the line settles - the save's end redraws the lines (drawPageVerdicts), the
  // fonts' load fits them (refitForFonts) - or goes once CHIP_WAIT_MS have passed since it first had no room.
  lines.forEach((line, index) => {
    const placed = got[index],
      chip = chips[index];
    if (!placed || !chip) return;
    if (placed.away) {
      const firstMiss = Number(chip.dataset.noRoom) || Date.now();
      chip.dataset.noRoom = String(firstMiss);
      if (
        (holdsRows(line) || (document.fonts && document.fonts.status === 'loading')) &&
        Date.now() - firstMiss < CHIP_WAIT_MS
      ) {
        line.classList.add('pv-chip-wait');
        clearTimeout(CHIP_WAIT_TIMERS.get(chip));
        CHIP_WAIT_TIMERS.set(
          chip,
          setTimeout(() => {
            if (chip.isConnected && chip.parentElement === line) fitPageLines([line]);
          }, CHIP_WAIT_MS + 20),
        );
        return;
      }
      line.classList.remove('pv-chip-wait');
      chipAway(chip);
      return;
    }
    delete chip.dataset.noRoom;
    line.classList.remove('pv-chip-wait');
    line.style.setProperty('--pv-chip-r', placed.r + 'px');
    line.style.setProperty('--pv-chip-y', placed.y + 'px');
    line.classList.toggle('pv-chip-short', !!placed.short);
    line.classList.toggle('pv-chip-bare', !!placed.bare);
  });
}
// The reason popover's side (placePopover): above its line, as drawn - unless the room above inside what the PDF area
// shows (under the section strip) is too short for it while the room below holds it: then under the line
// (.pv-pop-below). Where neither holds it, the larger side, the popover no taller than that (--pv-pop-max; it scrolls).
// So near the top an in-place line's popover never opens under the strip and the top bar.
function placePopover() {
  const pop = document.querySelector('#doc .pv>.pv-pop') as HTMLElement | null;
  $$('#doc .pv.pv-pop-below').forEach((line) => {
    if (!pop || line !== pop.parentElement) line.classList.remove('pv-pop-below');
  });
  if (!pop) return;
  const line = pop.parentElement as HTMLElement,
    area = $('#left'),
    areaRect = area.getBoundingClientRect();
  if (line.id === 'pv-panel') {
    line.classList.remove('pv-pop-below');
    line.style.removeProperty('--pv-pop-max');
    return;
  } // in the panel's flow, under its state
  let top = Math.max(areaRect.top, 0);
  const strip = document.getElementById('section-strip');
  if (strip && strip.getClientRects().length) {
    const stripRect = strip.getBoundingClientRect();
    if (stripRect.bottom > top && stripRect.top <= top + 1) top = stripRect.bottom;
  }
  const cover =
    (parseFloat(getComputedStyle(document.body).getPropertyValue('--pv-inset')) || 0) +
    (parseFloat(area.style.getPropertyValue('--pv-kb-over')) || 0);
  const bottom = areaRect.top + area.clientHeight - cover;
  if (line.style.getPropertyValue('--pv-pop-max')) line.style.removeProperty('--pv-pop-max');
  const lineRect = line.getBoundingClientRect(),
    height = pop.offsetHeight,
    above = lineRect.top - 8 - top,
    below = bottom - (lineRect.bottom + 8);
  const under = height > above && (height <= below || below > above);
  line.classList.toggle('pv-pop-below', under);
  if (height > Math.max(above, below))
    line.style.setProperty('--pv-pop-max', Math.max(0, Math.floor(under ? below : above)) + 'px');
}
// No description box over a line's save chip. The chip ('#42 저장됨 · 채택 [되돌리기]') stands at the line's end above
// it, where a word's box stands too: the press's own focus arms the box again (platform/tooltip.ts armTip), and a
// resting hand's slight move would bring it back after anything hid it. While a chip is on a line (drawChips puts it
// there, its window takes it away) the line's words are drawn without their descriptions (verdictButton quiet), so
// neither hover nor focus has a box to show; a chip that comes closes the box that is up. Its leaving draws the
// descriptions back. Watched per line (childList only: the chip is a child of the line).
const CHIP_WATCH =
  typeof MutationObserver !== 'undefined'
    ? new MutationObserver((recs) => {
        // Whether a line now holds a chip it did not, or lost one: a chip taken out and put back on the same line
        // (fillPageLine's morph) is no change; one moved to another line is a change on both.
        const had = new Map();
        recs.forEach((record) => {
          const countChips = (nodes: NodeList, step) =>
            [...nodes].forEach((node) => {
              if (node instanceof Element && node.classList.contains('nt-chip')) {
                const counts = had.get(record.target) || new Map();
                counts.set(node, (counts.get(node) || 0) + step);
                had.set(record.target, counts);
              }
            });
          countChips(record.addedNodes, 1);
          countChips(record.removedNodes, -1);
        });
        let came = false,
          went = false;
        had.forEach((counts) =>
          counts.forEach((change) => {
            if (change > 0) came = true;
            else if (change < 0) went = true;
          }),
        );
        if (!came && !went) return;
        if (came) hideTip();
        drawPageVerdicts();
      })
    : null;
// Draws the page verdict line under every page after the pages, the pin lists or the build change. Without page
// verdicts every line goes and the marks draw every pin.
function drawPageVerdicts() {
  const verdicts = pageVerdictsOn(),
    focused = document.activeElement as HTMLElement | null;
  const on = !!focused && !!focused.closest ? (focused.closest('.pv') as HTMLElement | null) : null,
    had = !!on,
    onPage = on ? Number(on.dataset.page) || 0 : 0;
  if (ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && (!verdicts || !armStillHolds(ARMED_VERDICT)))
    disarmVerdict(false);
  SHOWN_ON_PAGE_LINES = new Set();
  // A document with no page lines has no reason field either: a session left from the one before (or from this one
  // before its words went) closes here, its text saved - syncReasonSession, after this, is never reached for it.
  if (!verdicts || !META) {
    if (REASON_SESSION) leaveReason();
    $$('#doc .pv,#doc .pv-sum').forEach((element) => element.remove());
    removePanel();
    if (IS_BESIDE_PAGES) applyBeside(false);
    syncTypingFold();
    return;
  }
  // beside the pages or under them (verdict/view-panel.ts): the reading page holds until the spot is back
  const turn = startBesideTurn();
  try {
    syncReasonSession();
    const map = pageVerdictPins();
    READING_LINE_PAGE = heldReadingPage();
    KEYED_PAGE = keyedPageFor(READING_LINE_PAGE);
    // Beside the pages: one panel for the reading page, and every page's verdicts are its - none draws a page-size
    // mark.
    if (IS_BESIDE_PAGES) {
      $$('#doc .pgw>.pv').forEach((element) => element.remove());
      map.forEach((list) => list.forEach((pin) => SHOWN_ON_PAGE_LINES.add(pin.id)));
      fillPanel(map, verdicts);
    } else {
      removePanel();
      $$('#doc .pg').forEach((pageElement) => {
        const page = +pageElement.dataset.page;
        let line = pageElement.nextElementSibling as HTMLElement | null;
        if (!pageTakesVerdict(page)) {
          if (line && line.classList.contains('pv')) line.remove();
          return;
        } // the map says this page takes none
        if (!line || !line.classList.contains('pv')) {
          line = document.createElement('div');
          line.className = 'pv';
          pageElement.after(line);
          if (CHIP_WATCH) CHIP_WATCH.observe(line, { childList: true });
        }
        fillPageLine(line, page, map.get(page), verdicts);
      });
    }
    drawSummaries(map);
    sizePageLines();
  } finally {
    if (turn) settleBesideTurn(turn);
  }
  stickReadingLine();
  if (had) refocusVerdictButton(focused);
  refocusAfterLines(); // a reason field that went from under the focus hands it to its line
  if (turn) finishBesideTurn(turn); // the lines moved: the reading spot, a save chip and the focus come along
  // The control the focus was on went with this drawing (a take-back shows the verdict before it): its line's, never
  // nothing.
  if (had) {
    const active = document.activeElement;
    if ((!active || active === document.body) && !focusLine(onPage)) searchToPage();
  }
  syncTypingFold();
} // a redraw or a rebuild can take the focused reason field away without a focusout
// Whether a pin's page verdict line shows it, so its page-size mark is not drawn (marks).
function isShownOnLine(pin: Pin) {
  return SHOWN_ON_PAGE_LINES.has(pin.id);
}
// A card's [보기] for a pin a line shows: its page comes into view with the line and the line flashes. A figure page
// arrives at its figure (arrivePage, §그림 쪽 도착). Any other page and its line are one block (.pgw): centred when it
// fits the PDF area, else from the page's top - the line then floats at the area's bottom (scrolling to the sticky line
// itself would follow where it floats, not where it is). Returns whether it did.
function jumpToPageLine(id: number) {
  if (!SHOWN_ON_PAGE_LINES.has(id)) return false;
  const pin = PINS.find((x) => x.id === id) || REVIEW_ALL.find((x) => x.id === id) || DONE.find((x) => x.id === id);
  const target = pin && pageTargetOf(pin, META ? META.kind : undefined);
  if (!target) return false;
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
  const flash = (element) => {
    element.classList.remove('flash');
    void element.offsetWidth;
    element.classList.add('flash');
    clearTimeout(element._flT);
    element._flT = setTimeout(() => element.classList.remove('flash'), 1200);
  };
  const isFigure = figureTop(target.page) !== null;
  if (IS_BESIDE_PAGES) {
    if (!document.getElementById('p' + target.page)) return false;
    if (isFigure) arrivePage(target.page);
    else bringPage(target.page, true);
    flashPanelOn(target.page);
    return true;
  } // the panel flashes where the page lands (verdict/view-panel.ts)
  const line = document.querySelector('#doc .pv[data-page="' + target.page + '"]') as HTMLElement | null;
  if (!line) return false;
  const block = line.parentElement as HTMLElement,
    area = $('#left'),
    how = block.getBoundingClientRect().height <= area.clientHeight ? 'center' : 'start';
  if (isFigure) arrivePage(target.page);
  else {
    glideInto(block, how);
    arrivalWatch(() => (block.isConnected ? scrollTopFor(block, how) : null));
  }
  flash(line);
  return true;
}

// ---------------- Lines far from the view (docs/handbook/viewer.md §판정 핀)
// A line more than a view's height above or below what the PDF area shows is left for the browser to skip (.pv-far:
// content-visibility:auto, components.css): it is not laid out or painted until it comes near. Each page PDF.js draws
// for the first time adds its embedded fonts to document.fonts, and every font added makes the browser lay out all the
// text in the page again: skipped like the far cards (pins/flow-list.ts lazyCards), the lines far from the view are not
// laid out at each of those. A skipped line breaks none of the line's rules, because it is never another size than the
// one it is drawn at:
// - It stands at its drawn height: --pv-h (the contain-intrinsic-block-size; the line has no padding or border, so its
//   box is its content box), or the size the browser last drew it at (content-visibility:auto keeps it:
//   contain-intrinsic-size auto), which is the same. Whatever changes what a line shows or its width fits it again
//   (fillPageLine, sizePageLines: fitPageLines), and fitPageLines lays out every line it measures - a skipped one too
//   (holdFarLines) - and keeps its height as it lets go of it (letFarLinesGo); a line that goes far keeps the height
//   the observer saw instead, where that is the later one. So a skip never moves the pages and nothing scrolls to make
//   up for one; and every line is still measured as the reading line (#doc.pv-measure).
// - Skipping contains a line (paint containment): it draws its parts on whole pixels and clips what reaches past its
//   box (a focus ring, the pressed word's hint, the reason popover, a save chip). So no line in or near the view is
//   skipped (the observer's margin), and - whatever the observer said last - neither is the reading line, which floats,
//   a line holding the focus, its reason popover or a save chip, or a line fitPageLines is measuring (components.css).
//   A script's measure inside a skipped line lays it out for the answer (the keys' Tab stops), but the innerText of
//   what is skipped is empty.
// Without IntersectionObserver no line is skipped.
let FAR_OBSERVER = null as IntersectionObserver | null,
  FAR_HEIGHT = -1;
const FAR_WATCHED = new Set() as Set<HTMLElement>; // the lines the observer watches
// when fitPageLines last kept each line's height (performance.now())
const FITTED_AT = new WeakMap() as WeakMap<HTMLElement, number>;
// The lines fitPageLines is about to measure are laid out, skipped or not (.pv-fitting).
function holdFarLines(lines: HTMLElement[]) {
  if (typeof IntersectionObserver === 'undefined') return;
  lines.forEach((line) => line.classList.add('pv-fitting'));
}
// fitPageLines is done with lines: each keeps the height it is drawn at now (one not laid out - the changes view -
// keeps the one it had), may be skipped again, and is watched - a new line too; a line no longer in the page (another
// document, a rebuild) is no longer watched. Read before any is written.
function letFarLinesGo(lines: HTMLElement[]) {
  if (typeof IntersectionObserver === 'undefined') return;
  const heights = lines.map((line) => line.getBoundingClientRect().height),
    at = performance.now();
  const area = $('#left'),
    viewHeight = area.clientHeight;
  lines.forEach((line, index) => {
    if (heights[index]) {
      line.style.setProperty('--pv-h', heights[index] + 'px');
      FITTED_AT.set(line, at);
    }
    line.classList.remove('pv-fitting');
  });
  watchFarLines(lines, viewHeight);
}
// Watches lines (new ones; one no longer in the page is let go) with an observer whose margin is the PDF area's height,
// in px above and below its view (a percentage would be of its width): it is made again, watching every line, when that
// height changes.
function watchFarLines(lines: HTMLElement[], viewHeight: number) {
  if (!FAR_OBSERVER || FAR_HEIGHT !== viewHeight) {
    if (FAR_OBSERVER) FAR_OBSERVER.disconnect();
    FAR_WATCHED.clear();
    FAR_HEIGHT = viewHeight;
    FAR_OBSERVER = new IntersectionObserver(sortFarLines, { root: $('#left'), rootMargin: viewHeight + 'px 0px' });
    lines = $$('#doc .pgw>.pv,#doc .pv-sum');
  } // a line or a summary under a page; never the panel
  const io = FAR_OBSERVER;
  FAR_WATCHED.forEach((line) => {
    if (!line.isConnected) {
      io.unobserve(line);
      FAR_WATCHED.delete(line);
    }
  });
  lines.forEach((line) => {
    if (!FAR_WATCHED.has(line) && line.isConnected) {
      io.observe(line);
      FAR_WATCHED.add(line);
    }
  });
}
// The PDF area's height can change with no line fitted again - a window made only shorter while a scale is saved keeps
// that scale (autoFitWidth), so sizePageLines does not run: the margin follows it here, so far still means a view's
// height away.
if (window.ResizeObserver && window.IntersectionObserver)
  new ResizeObserver(() => {
    const viewHeight = $('#left').clientHeight;
    if (FAR_OBSERVER && viewHeight && viewHeight !== FAR_HEIGHT) watchFarLines([], viewHeight);
  }).observe($('#left'));
// The observer's reports: a line that came within a view's height of the PDF area's view is drawn as it is; one that
// went further is skipped, at the height the observer saw when that is later than fitPageLines's - not one not laid out
// (no height to stand at) or no longer in the page.
function sortFarLines(entries: IntersectionObserverEntry[]) {
  for (const entry of entries) {
    const line = entry.target as HTMLElement;
    if (!line.isConnected) continue;
    if (entry.isIntersecting) {
      line.classList.remove('pv-far');
      continue;
    }
    if (line.classList.contains('pv-far') || !entry.boundingClientRect.height) continue;
    if (entry.time > (FITTED_AT.get(line) || -1))
      line.style.setProperty('--pv-h', entry.boundingClientRect.height + 'px');
    line.classList.add('pv-far');
  }
}

// ---------------- The line that floats, and the keys (docs/handbook/viewer.md §판정 핀)
// Only the reading page's line floats: the page under the reading line, the one the section strip names and the keys
// act on (READING_LINE_PAGE). Its line (.reading) is sticky to the PDF area's bottom within its page's block (.pgw,
// pdf/view-pages.ts buildDoc): while its own place is below the area it floats there over the page (.stuck: an edge
// that sets it off the page), and it names the figure it decides; at the page's end it settles under it. Every other
// line stays in its place - a next page's line floating as soon as that page's top edge comes in would show a second
// '판정 없음' for a figure not yet in view, and put another figure's buttons under a resting mouse or thumb. It does
// not float while a selection is being written (the composer has its own verdict row, and the line would cover the
// selection - or on a phone the sheet) nor over an open phone sheet (CSS). stickReadingLine follows the reading page
// and marks the floating line; run once a frame while the area scrolls.
function stickReadingLine() {
  // the room crossed its bar: drawn again beside or under the pages (verdict/view-panel.ts), which ran this
  if (pageVerdictsOn() && redrawOnBesideChange()) return;
  const lines = $$('#doc .pv');
  if (!lines.length) return;
  const area = $('#left'),
    areaRect = area.getBoundingClientRect();
  if (!areaRect.height) return;
  const pad = getComputedStyle(area).paddingBottom;
  // the end padding a sticky line keeps clear of (components.css)
  if (area.style.getPropertyValue('--pv-pad-b') !== pad) area.style.setProperty('--pv-pad-b', pad);
  // A keyboard laid over the page without the layout giving way (the visual viewport shorter than the PDF area reaches
  // - an iPad's Safari, or a band whose PDF area does not follow --kb): the floating line and its popover rise by what
  // it hides.
  const viewport = window.visualViewport,
    keyboardOver =
      viewport && COARSE_POINTER_QUERY.matches
        ? Math.max(0, Math.round(areaRect.top + area.clientHeight - (viewport.offsetTop + viewport.height)))
        : 0;
  if (area.style.getPropertyValue('--pv-kb-over') !== keyboardOver + 'px')
    area.style.setProperty('--pv-kb-over', keyboardOver + 'px');
  if (measureInsetRight() !== INSET_RIGHT) sizePageLines(); // a panel came over the area, went, or changed its width
  const at = heldPanelPage() || pageUnderReadingLine(),
    readingPage = at && pageTakesVerdict(at) ? at : 0,
    keyedPage = keyedPageFor(readingPage); // a jump's glide: the panel's page held (verdict/view-panel.ts)
  if (REASON_SESSION && REASON_SESSION.page === readingPage) REASON_SESSION.seen = true;
  else if (REASON_SESSION && REASON_SESSION.seen) leaveReason(); // the reading page left the field's page: moving on
  // A key's armed confirm word belongs to the page it was read on: another reading page lets it go.
  if (
    ARMED_VERDICT &&
    ARMED_VERDICT.kbd &&
    ARMED_VERDICT.where === VERDICT_PLACE.PAGE &&
    ARMED_VERDICT.page !== readingPage
  )
    disarmVerdict(false, true);
  // The new reading page stays where it is on screen without a scroll: a stacked line keeps the row of the figure's
  // name it shows while it is the reading line (components.css), so the line the reading page leaves keeps its height.
  // Scrolling the area by what a line's change moved a page would end a jump's smooth scroll where it is, and on a
  // phone a slow scroll down would never pass a page's end: the page above would come back under the reading line and
  // the reading page would flip back and forth. Two pages in a row that take no verdict read 0 here, one after the
  // other: the panel names the page, so it asks too.
  if (readingPage !== READING_LINE_PAGE || keyedPage !== KEYED_PAGE || isPanelStale(at)) {
    // the person moved on: they are not typing on into a field that went
    if (readingPage !== READING_LINE_PAGE) setKeyGuard(false);
    const was = [READING_LINE_PAGE, KEYED_PAGE];
    READING_LINE_PAGE = readingPage;
    KEYED_PAGE = keyedPage;
    const map = pageVerdictPins(),
      verdicts = pageVerdictsOn();
    const refit = [] as HTMLElement[];
    if (verdicts && IS_BESIDE_PAGES) {
      fillPanel(map, verdicts);
      refit.push(ensurePanel());
    } // the panel shows the new reading page
    else if (verdicts)
      new Set([...was, readingPage, keyedPage]).forEach((page) => {
        const line = (page ? document.querySelector('#doc .pv[data-page="' + page + '"]') : null) as HTMLElement | null;
        if (line) {
          fillPageLine(line, page, map.get(page), verdicts);
          refit.push(line);
        }
      });
    if (refit.length) fitPageLines(refit); // the reading line names its figure: its row is measured again
    moveFocusOffPage(readingPage, was[0]);
  }
  placePanel();
  markReadingSummary();
  lines.forEach((line) => {
    if (line.id === 'pv-panel') return; // the panel stands sticky beside the pages: it never floats at their foot
    const pageElement = line.previousElementSibling as HTMLElement | null;
    if (!pageElement) return;
    const rect = line.getBoundingClientRect(),
      pageBottom = pageElement.getBoundingClientRect().bottom;
    // In its own place it stands 8px under the page; held lower by a reason's room (placePopoverRoom) it floats over
    // the gap and the next page's top, and is set off as a floating line is - with an edge under it too while it lies
    // over that page (.pv-over), since its band would read as the next page's head.
    const low = isHeldLow(line, pageElement, rect.top, pageBottom),
      stuck =
        (line.classList.contains('reading') &&
          rect.bottom > areaRect.top &&
          rect.top < areaRect.bottom &&
          rect.top < pageBottom + 4) ||
        low;
    line.classList.toggle('stuck', stuck);
    line.classList.toggle('pv-over', low && reachesNextPage(line, rect));
    leanFloatingLine(line, pageElement, rect, stuck, area, areaRect);
  });
  placePopover();
  if (placePopoverRoom(area, areaRect)) placePopover();
} // a held line its floating place lifted: the popover's side again
// Room to read a page's end under its open reason popover. The popover stands above its line, so where the line stands
// in its place under the page the popover covers the page's end - a figure's caption, written under the plot - and no
// scroll would uncover it, since the line and the popover with it go on with the page. While a popover is open above a
// line in the pages, that line's block holds a room as tall as what the popover covers there (.pv-roomy, --pv-room: an
// empty box after the line whose negative margin gives its height back, so no page and no block moves), and the line's
// top edge is sticky where it stands (its own top). Scrolling on, the line and the popover stay while the page's end
// comes up from under them by the room, then go on with the page. The line only ever stands lower than its own place,
// never higher; scrolled back, it goes down with the page, and wherever it then stands unheld - lower, or floating - is
// where it holds next (also when the field's focus folds the line and the page moves on a phone). Held lower it floats
// over the gap and the next page's top, set off as a floating line is (isHeldLow). A sticky top wins over the floating
// bottom, so the top is never lower than the floating place (a keyboard laid over the page raises that). Opening and
// closing move nothing and nothing scrolls: closed, the room stays while the line stands lower than its place in view -
// dropping it would lift the line under the eye - and goes once the line is back in its place or out of view. The
// panel's popover is in the panel's flow, beside the page: it covers nothing. line -> the room its block holds (px) and
// that block
const POPOVER_ROOM = new Map() as Map<HTMLElement, { room: number; blk: HTMLElement }>;
// The gap between a page and its line in its own place: the page's bottom margin and the line's top margin, collapsed.
function lineOwnGap(line: HTMLElement, pageElement: HTMLElement) {
  const pageMargin = parseFloat(getComputedStyle(pageElement).marginBottom) || 0,
    lineMargin = parseFloat(getComputedStyle(line).marginTop) || 0;
  return Math.max(pageMargin, lineMargin, 0) + Math.min(pageMargin, lineMargin, 0);
}
// Whether a line (its top edge at `top`, its page's bottom at `pageBottom`) stands lower than its own place, held there
// by a reason's room.
function isHeldLow(line: HTMLElement, pageElement: HTMLElement, top: number, pageBottom: number) {
  return POPOVER_ROOM.has(line) && top > pageBottom + lineOwnGap(line, pageElement) + 0.5;
}
// Whether a line (its box `rect`), with the ring its floating look paints around it, reaches over the next page's top.
function reachesNextPage(line: HTMLElement, rect: DOMRect) {
  const block = line.parentElement,
    nextBlock = block && block.nextElementSibling,
    nextPage = nextBlock && nextBlock.querySelector(':scope>.pg');
  if (!nextPage) return false;
  return (
    nextPage.getBoundingClientRect().top <
    rect.bottom + (parseFloat(getComputedStyle(line).getPropertyValue('--pv-ring')) || 0)
  );
}
function dropPopoverRoom(line: HTMLElement) {
  const room = POPOVER_ROOM.get(line);
  POPOVER_ROOM.delete(line);
  line.style.removeProperty('top');
  line.classList.remove('pv-over');
  if (room) {
    room.blk.classList.remove('pv-roomy');
    room.blk.style.removeProperty('--pv-room');
  }
} // its block, also once the line is gone from it (the side panel took it)
// Whether it lifted a held line (its floating place rose above it): the popover's side is chosen again then
// (stickReadingLine).
function placePopoverRoom(area: HTMLElement, areaRect: DOMRect): boolean {
  const pop = document.querySelector('#doc .pv>.pv-pop') as HTMLElement | null;
  const open =
    pop && pop.parentElement && pop.parentElement.id !== 'pv-panel' ? (pop.parentElement as HTMLElement) : null;
  if (!open && !POPOVER_ROOM.size) return false;
  const style = getComputedStyle(area),
    top0 = areaRect.top + area.clientTop + (parseFloat(style.paddingTop) || 0),
    // what a sticky line keeps within
    end = areaRect.top + area.clientTop + area.clientHeight - (parseFloat(style.paddingBottom) || 0);
  POPOVER_ROOM.forEach((room, line) => {
    if (line === open) return;
    const pageElement = line.previousElementSibling as HTMLElement | null;
    if (!line.isConnected || !pageElement || line.parentElement !== room.blk) {
      dropPopoverRoom(line);
      return;
    }
    const rect = line.getBoundingClientRect();
    if (
      !isHeldLow(line, pageElement, rect.top, pageElement.getBoundingClientRect().bottom) ||
      rect.bottom <= areaRect.top ||
      rect.top >= areaRect.top + area.clientHeight
    )
      dropPopoverRoom(line);
  });
  if (open) {
    const pageElement = open.previousElementSibling as HTMLElement | null,
      block = open.parentElement;
    const want =
      pop && pageElement && block && block.classList.contains('pgw')
        ? Math.ceil(-pop.offsetTop - lineOwnGap(open, pageElement))
        : 0; // under its line: 0 or less
    let had = POPOVER_ROOM.get(open);
    if (had && had.blk !== block) {
      dropPopoverRoom(open);
      had = undefined;
    }
    if (!had && want > 0 && block) {
      had = { room: 0, blk: block };
      POPOVER_ROOM.set(open, had);
      block.classList.add('pv-roomy');
    }
    if (had && pageElement) {
      if (want > had.room) {
        had.room = want;
        had.blk.style.setProperty('--pv-room', want + 'px');
      } // a taller popover: more room, never less while it is open
      // Its top is sticky where it stands - and lower where it comes to stand without being held (the page moved down:
      // a scroll back, or the line growing or shrinking as the field takes the focus), so the room is under it wherever
      // the person turns to read on.
      const rect = open.getBoundingClientRect(),
        stickyTop = rect.top - top0;
      if (
        !isHeldLow(open, pageElement, rect.top, pageElement.getBoundingClientRect().bottom) &&
        !(parseFloat(open.style.top) >= stickyTop)
      )
        open.style.top = stickyTop + 'px';
    }
  }
  let lifted = false;
  POPOVER_ROOM.forEach((_, line) => {
    const bottom = getComputedStyle(line).bottom;
    if (bottom === 'auto') return; // a floating line: its top stays above where it floats
    const most = end - (parseFloat(bottom) || 0) - line.getBoundingClientRect().height - top0;
    if ((parseFloat(line.style.top) || 0) > most) {
      line.style.top = most + 'px';
      lifted = true;
    }
  });
  return lifted;
}
// A phone's floating line holds [판정 취소] back (.pv-lean, components.css): unseen, not pressed, focused or heard -
// and in its place, so the line keeps its rows whether it floats or stands in its place. Taken out of the row, it would
// let the short earlier link ('이전 1건') rise into its row while the line floats, and the next page would jump under
// the finger as the line crosses its page's end. The in-place line and the card still offer it, with its 44px.
// Hysteresis keeps it from flipping at a page's end: shown, it leans once the line floats; leaning, it is shown again
// only when the line (its full height, measured when it was last shown) fits in its place under the page. Desktop and
// every other band: never.
const FULL_LINE_HEIGHT = new WeakMap() as WeakMap<HTMLElement, { h: number; gap: number }>;
function leanFloatingLine(
  line: HTMLElement,
  pageElement: HTMLElement,
  rect: DOMRect,
  stuck: boolean,
  area: HTMLElement,
  areaRect: DOMRect,
) {
  if (
    !document.body.classList.contains('band-phone') ||
    !line.classList.contains('reading') ||
    !line.querySelector('.pv-cancel')
  ) {
    line.classList.remove('pv-lean');
    return;
  }
  const full = FULL_LINE_HEIGHT.get(line) || { h: 0, gap: 8 },
    pageBottom = pageElement.getBoundingClientRect().bottom;
  FULL_LINE_HEIGHT.set(line, full);
  if (!stuck) full.gap = Math.max(0, rect.top - pageBottom);
  if (!line.classList.contains('pv-lean')) {
    full.h = rect.height;
    if (stuck) {
      line.classList.add('pv-lean');
      keepFocusOnLine([line]);
    }
    return;
  }
  // Where a floating line's bottom stands: the area's bottom less its end padding and the line's sticky inset.
  const style = getComputedStyle(area),
    limit =
      areaRect.top +
      area.clientHeight -
      parseFloat(style.paddingBottom) -
      (parseFloat(getComputedStyle(line).bottom) || 0);
  if (pageBottom + full.gap + (full.h || rect.height + 64) <= limit) line.classList.remove('pv-lean');
}
// What lies over the PDF area's right side, in px in from the area's content edge: a panel laid over it - the unfolded
// foldable's overlay panel, beside which the pages run on underneath - and its handle's touch area, as for a save chip
// (chipInRoom). 0 where the panel stands beside the area or at its bottom (a sheet). A line is never wider than the
// room left of them, and keeps out of them as it floats (sticky right, --pv-inset-r): its words would lie under the
// panel.
let INSET_RIGHT = 0;
function measureInsetRight() {
  const area = $('#left'),
    panel = $('#right'),
    grip = $('#grip');
  if (!area.getClientRects().length) return 0;
  const areaRect = area.getBoundingClientRect(),
    edge = areaRect.left + area.clientWidth - parseFloat(getComputedStyle(area).paddingRight);
  let right = edge;
  if (panel && panel.getClientRects().length) {
    const panelRect = panel.getBoundingClientRect();
    if (panelRect.left > areaRect.left + 40 && panelRect.top < areaRect.bottom - 40)
      right = Math.min(right, panelRect.left - 4);
  }
  if (grip && grip.getClientRects().length) {
    const gripRect = grip.getBoundingClientRect(),
      reach = Math.max(gripRect.width, parseFloat(getComputedStyle(grip, '::after').width) || 0);
    if (gripRect.left > areaRect.left + 40) right = Math.min(right, gripRect.right - reach - 4);
  }
  return Math.max(0, Math.round(edge - right));
}
// The page under the reading line - the one the section strip and the page count name, readingDepth under the PDF
// area's top - while the pages are shown and the document has page lines; 0 otherwise. Read from the layout as it is
// now.
function pageUnderReadingLine() {
  // the lines are moving beside or under the pages (verdict/view-panel.ts)
  if (HELD_READING_PAGE) return HELD_READING_PAGE;
  if (BUILD_READING_PAGE) return BUILD_READING_PAGE; // the pages are being built again (refreshDoc)
  if (!pageVerdictsOn() || document.body.classList.contains('revision-open') || !$('#left').getClientRects().length)
    return 0;
  const anchor = topAnchor(readingDepth($('#left')));
  return anchor ? anchor.page : 0;
}
// The reading page when it has a line (pageTakesVerdict), else 0: its line floats and names its figure
// (READING_LINE_PAGE).
function readingPageWithLine() {
  const page = pageUnderReadingLine();
  return page && pageTakesVerdict(page) ? page : 0;
}
// The page the keys 1-5 act on: the reading page while this screen may make a verdict, no selection is being written
// and no text field has the focus (its digits are text).
function keyedPageFor(readingPage: number) {
  return readingPage && canVerdict() && $('#composer').hidden && !typingNow() ? readingPage : 0;
}
let READING_LINE_PAGE = 0; // the reading page with a line: its line floats and names its figure
let STICK_FRAME = 0;
// Whether an element shows in the PDF area now (any part of it).
function isInAreaView(element: Element) {
  const area = $('#left'),
    areaRect = area.getBoundingClientRect(),
    rect = element.getBoundingClientRect();
  return (
    rect.bottom > areaRect.top &&
    rect.top < areaRect.top + area.clientHeight &&
    rect.right > areaRect.left &&
    rect.left < areaRect.right
  );
}
// The reading page moved from page `was` to readingPage while the focus stays on a control of another page's line - the
// left page's own line (still in view after a PageDown) or one now out of view (the saved reason's pencil, a word): the
// focus goes to the PDF area, where Enter opens the reading page's reason and Tab goes to its line. Left there, the
// next Enter or Space would act on the page the person left - its reason would open off-screen and the text meant for
// this page would go into that page's note. A focus put on a third page's line in view stays: the person went there.
function moveFocusOffPage(readingPage: number, was: number) {
  const active = document.activeElement as HTMLElement | null,
    line = active && active.closest ? active.closest('#doc .pv') : null;
  if (!active || !line || (active.closest && active.closest('.pv-pop'))) return;
  const page = Number((line as HTMLElement).dataset.page);
  if (page !== readingPage && (page === was || !isInAreaView(active))) searchToPage();
}
// The line control the focus went to and the reading page then: one focused on the reading page's line that is no
// longer it is the page the person left (stopOffPageKey), even before the frame that moves the focus
// (moveFocusOffPage).
let LINE_FOCUS = null as { el: Element; read: number } | null;
document.addEventListener('focusin', (event) => {
  const target = event.target as HTMLElement | null;
  LINE_FOCUS = target && target.closest && target.closest('#doc .pv') ? { el: target, read: READING_LINE_PAGE } : null;
});
// Enter or Space on a control of a line that is not the reading page's - out of view, or the line of the page the
// person left (focused while it was the reading page) - does not act there (a press read before the focus moved,
// moveFocusOffPage): the focus goes to the PDF area, and Enter is taken as on the pages - the reading page's reason
// (openReasonOnEnter) - while Space is only said.
function stopOffPageKey(event: KeyboardEvent) {
  if ((event.key !== 'Enter' && event.key !== ' ') || event.ctrlKey || event.metaKey || event.altKey || imeKey(event))
    return;
  const target = event.target as HTMLElement | null;
  const line = target && target.closest ? target.closest('#doc .pv') : null;
  if (!target || !line || (target.closest && target.closest('.pv-pop')) || typingNow()) return;
  const readingPage = pageUnderReadingLine(),
    page = Number((line as HTMLElement).dataset.page),
    left = !!LINE_FOCUS && LINE_FOCUS.el === target && LINE_FOCUS.read === page;
  if (CANCEL_OUT.has(pageLineSlot(page))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  } // its take-back is out
  if (!readingPage || page === readingPage || (isInAreaView(target) && !left)) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  searchToPage();
  if (event.type !== 'keydown') return;
  if (event.key === 'Enter') {
    openReadingReason(event);
    return;
  }
  lineNote('보이지 않는 쪽의 단추라 누르지 않았습니다 — 읽는 쪽에서 다시 누릅니다', NOTICE_KIND.INFO, null, {
    source: 'pv-offpage',
    life: NOTICE_LIFE.TIMER,
  });
}
addEventListener('keydown', stopOffPageKey, true);
addEventListener('keyup', stopOffPageKey, true); // keyup: a button's Space acts on its keyup
function stickSoon() {
  if (!STICK_FRAME)
    STICK_FRAME = requestAnimationFrame(() => {
      STICK_FRAME = 0;
      stickReadingLine();
    });
}
$('#left').addEventListener('scroll', stickSoon, { passive: true });
addEventListener('resize', stickSoon);
{
  const viewport = window.visualViewport;
  if (viewport) {
    viewport.addEventListener('resize', stickSoon);
    viewport.addEventListener('scroll', stickSoon);
  }
} // a keyboard over the page
$('#doc').addEventListener('input', (event) => {
  const target = event.target as HTMLElement;
  if (target.closest && target.closest('.pv-pop')) stickSoon();
}); // the reason field grows: its side again
// composing, the sheet, the band
new MutationObserver(stickSoon).observe(document.body, { attributes: true, attributeFilter: ['class'] });
if (typeof ResizeObserver !== 'undefined') {
  const panel = document.getElementById('right');
  if (panel) new ResizeObserver(stickSoon).observe(panel);
} // the panel's width
// The keys: 1-5 press the document's verdict words in file order on the line of the page under the reading line, as a
// press on that button does - a confirm word arms on the first press and saves on the second while its page, document
// and build hold (verdictPress). The page is read from the layout at the key, not from the last frame: a key right
// after a scroll across a page's end would otherwise go to the page before - and confirm its armed word. A confirm word
// armed for another page is let go first. Not in a text field, not while a dialog or a popover is open, not while a
// selection is being written (the composer is open) or the changes view is shown, not with Ctrl, Alt or Meta (Alt+digit
// switches documents). On a page that takes no verdict a key says so on the status line, once. The button and its line
// say the key (verdictButton's keyNumber).
function verdictKey(event: KeyboardEvent) {
  if (
    event.defaultPrevented ||
    event.repeat ||
    imeKey(event) ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    !/^[1-5]$/.test(event.key)
  )
    return;
  const target = event.target as HTMLElement | null;
  if (
    target &&
    (target.tagName === 'TEXTAREA' ||
      target.tagName === 'INPUT' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable)
  )
    return;
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden
  )
    return;
  // A card's editor or reply open with the focus outside the pages (on its [저장], say): its keys, not the pages' - a
  // digit would take the focus from it, and the Enter after it would open nothing (openReadingReason waits for the
  // editor).
  if ((EDITOR.current || REPLY) && !$('#left').contains(document.activeElement)) return;
  const verdicts = pageVerdictsOn(),
    digit = +event.key,
    choice = verdicts && verdicts.choices[digit - 1],
    at = pageUnderReadingLine();
  if (!choice || !at || !canVerdict()) return;
  if (isKeyGuarded(event)) return; // a reason field went from under the typing: its digits are not verdict keys
  if (isAutoScrolling()) {
    event.preventDefault();
    sayGliding();
    return;
  } // a jump still gliding: the reading page is not yet the one asked for
  if (!pageTakesVerdict(at)) {
    event.preventDefault();
    lineNote('이 쪽은 판정을 받지 않습니다', NOTICE_KIND.INFO, null, {
      source: 'verdict-key',
      life: NOTICE_LIFE.TIMER,
    });
    return;
  }
  if (ARMED_VERDICT && ARMED_VERDICT.kbd && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page !== at)
    disarmVerdict(true, true);
  // The panel shows the page under the reading line at the key, also before the frame that would show it
  // (verdict/view-panel.ts).
  if (IS_BESIDE_PAGES && ensurePanel().dataset.page !== String(at)) stickReadingLine();
  const button = document.querySelector(
    '#doc .pv[data-page="' + at + '"] button[data-act="pv-save"][data-key="' + CSS.escape(choice.key) + '"]',
  ) as HTMLElement | null;
  if (!button) return;
  event.preventDefault();
  // A digit pressed with the focus outside the pages (an outline entry, the page list's or the section strip's button,
  // a document tab, a card) brings the focus to the PDF area at once, as the save's end brings it to the line: left on
  // that control while the save is out, the Enter typed after the digit would press it again instead of opening the
  // reason. The area is a named region (index.html), so a screen reader says 'PDF 쪽' for the moment it has the focus,
  // not every page's text one after the other. Where the focus came from is kept: Shift+Tab from the line goes back
  // there (CAME_FROM).
  const active = document.activeElement as HTMLElement | null,
    area = $('#left');
  if (active && active !== document.body && active !== area && !area.contains(active)) {
    noteCameFrom(active);
    searchToPage();
  }
  verdictPress(button, 'key');
}
addEventListener('keydown', verdictKey);
for (const eventType of ['wheel', 'touchstart', 'touchmove', 'pointerdown'])
  $('#left').addEventListener(eventType, HAND_ON_PAGES, { passive: true, capture: true });
$('#left').addEventListener(
  'pointermove',
  (event) => {
    if (event.buttons) HAND_ON_PAGES();
  },
  { passive: true, capture: true },
); // a scroll bar dragged
// A scrolling key is the person's hand on the pages only where it scrolls them: on the PDF area, on a control in it (a
// line's word lets the arrows through) or on nothing - not in a text field, and not Space on a button, which it
// presses. ↓ in the outline's filter or list moves to a result, and the Enter after it starts a jump the guard must not
// take for the person's own scroll, or a digit pressed while it glides would save on a page passed.
addEventListener(
  'keydown',
  (event) => {
    if (!SCROLL_KEYS.has(event.key)) return;
    const target = event.target;
    if (!(
      target === document.body ||
      target === document.documentElement ||
      (target instanceof Element && !!target.closest('#left'))
    ))
      return;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)))
      return;
    if (event.key === ' ' && target instanceof Element && target.closest('button,[role=button],summary')) return;
    HAND_ON_PAGES();
  },
  true,
);
$('#left').addEventListener(
  'scroll',
  () => {
    const now = performance.now();
    if (JUMP_TARGET !== null && now - LAST_SCROLL_AT > 1000) setJumpTarget(null); // a jump that never got there
    if (JUMP_TARGET === null && now - LAST_SCROLL_AT > 200) setGliding(now - HAND_SCROLL_AT > 500);
    setLastScrollAt(now);
  },
  { passive: true },
); // a new run of scrolling decides, unless a jump said what it is
// The end of a jump is at its place: a manual scroll's own end, coming after the jump began, must not end the guard in
// its first frames.
$('#left').addEventListener('scrollend', () => {
  if (JUMP_TARGET !== null && Math.abs($('#left').scrollTop - JUMP_TARGET) > 2) return;
  setJumpTarget(null);
  setGliding(false);
});
// Said once while the pages glide: the key was not taken, press it again once they rest.
function sayGliding() {
  lineNote('쪽으로 가는 중이라 판정 키를 받지 않았습니다 — 멈춘 뒤 다시 누릅니다', NOTICE_KIND.INFO, null, {
    source: 'verdict-key',
    life: NOTICE_LIFE.TIMER,
  });
}
// Tab from the PDF area (where Esc, a moved-on popover or a search leaves the focus) goes to the reading page's line -
// its first control - not to the first page's line, whose focus would scroll the document there. The focus on nothing
// (body) counts as on the PDF area after a press there: a press on a page leaves the focus where it was, and Chromium's
// next Tab starts from the pressed node - which a redrawn canvas may have taken away, so it would start from the
// document's first line. A reading page with no line (a figure document's list pages, which take no verdict -
// pageTakesVerdict) or with none of its controls to stop on (a viewer who may not make a verdict, '판정 없음') keeps
// the pages where they are as well: the Tab goes to the next stop in the pages from that page on - a mark, the next
// page's line - while it shows whole in the area's view, else on past the pages (findEdgeStop: the status line's
// action, the panel's grip), else nowhere (the focus stays). Left to the DOM's order it would go to the first line
// after the pages' start and scroll them there, also on first open.
let PRESSED_ON_PAGES = false;
addEventListener(
  'pointerdown',
  (event) => {
    const target = event.target as HTMLElement | null;
    PRESSED_ON_PAGES = !!target && !!target.closest && !!target.closest('#left') && !target.closest('#doc .pv');
  },
  true,
);
document.addEventListener('focusin', (event) => {
  const target = event.target as HTMLElement | null;
  if (target && target !== $('#left')) PRESSED_ON_PAGES = false;
});
// So does Tab with nothing focused where no stop is drawn before the pages - a phone, whose nav bar, outline and
// section strip are not, whose first Tab after opening would otherwise go to a later page's line and scroll there.
addEventListener('keydown', (event) => {
  const active = document.activeElement;
  if (event.key !== 'Tab' || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented)
    return;
  if (!(active === $('#left') || ((!active || active === document.body) && (PRESSED_ON_PAGES || !findEdgeStop(false)))))
    return;
  const at = pageUnderReadingLine();
  if (!at) return; // no page lines, or the pages are not shown: the DOM's order scrolls nothing to a line
  const readingPage = readingPageWithLine(),
    line = readingPage ? document.querySelector('#doc .pv[data-page="' + readingPage + '"]') : null;
  const control = (
    line
      ? [...line.querySelectorAll('a,button,[tabindex="0"]')].find(
          (x) => x instanceof HTMLElement && x.getClientRects().length > 0 && !(x as HTMLButtonElement).disabled,
        )
      : undefined
  ) as HTMLElement | undefined;
  event.preventDefault();
  const stopInView = control ? null : findStopInView(at),
    to = control || stopInView || findEdgeStop(true);
  STOP_IN_VIEW = stopInView ? { el: stopInView, visit: captureVisit(), build: (META && META.pages_build) || '' } : null;
  if (to) to.focus({ preventScroll: true });
});
// The stop in the pages that Tab from the PDF area went to in view, while the reading page had no line to go to
// (above): a mark, or a later page's line. Shift+Tab from it leaves the pages the way the reading line's first stop
// does (findOutStop, below) - the DOM's stop before it is a page above, off the screen, and the focus would scroll the
// pages there. Let go when the focus leaves the pages, on another document or build, and by the next Tab from the area.
let STOP_IN_VIEW = null as { el: HTMLElement; visit: { doc: string | null; seq: number }; build: string } | null;
// The first Tab stop in the pages from page `at` on - its own marks, then the next pages' marks and lines in the DOM's
// order - when that stop shows whole in the PDF area's view (its client box, within the window) and nothing lies over
// any of it (the status line or the sheet over the area's bottom, a panel laid over its side: what its middle and four
// points 4px in from its corners hit is it), else null. Hit at its middle alone, a line half under the status line
// would be taken. Reads the page blocks from `at` down to the area's bottom only.
function findStopInView(at: number): HTMLElement | null {
  const area = $('#left'),
    areaRect = area.getBoundingClientRect(),
    top = Math.max(0, areaRect.top + area.clientTop),
    left = Math.max(0, areaRect.left + area.clientLeft);
  const bot = Math.min(innerHeight, areaRect.top + area.clientTop + area.clientHeight),
    right = Math.min(innerWidth, areaRect.left + area.clientLeft + area.clientWidth);
  for (
    let page = at, block = document.querySelector('#doc .pgw[data-page="' + page + '"]');
    block;
    block = document.querySelector('#doc .pgw[data-page="' + ++page + '"]')
  ) {
    if (block.getBoundingClientRect().top >= bot) return null;
    const x = [...block.querySelectorAll(TABBABLE)].find(isTabStop);
    if (!x) continue;
    const rect = x.getBoundingClientRect();
    if (rect.top < top || rect.bottom > bot || rect.left < left || rect.right > right) return null;
    const insetX = Math.min(4, rect.width / 4),
      insetY = Math.min(4, rect.height / 4),
      xPoints = [rect.left + insetX, (rect.left + rect.right) / 2, rect.right - insetX],
      yPoints = [rect.top + insetY, (rect.top + rect.bottom) / 2, rect.bottom - insetY];
    const points = [
      [xPoints[1], yPoints[1]],
      [xPoints[0], yPoints[0]],
      [xPoints[2], yPoints[0]],
      [xPoints[0], yPoints[2]],
      [xPoints[2], yPoints[2]],
    ];
    return points.every(([pointX, pointY]) => {
      const hit = document.elementFromPoint(pointX, pointY);
      return !!hit && (hit === x || (!!hit.closest && hit.closest(TABBABLE) === x));
    })
      ? x
      : null;
  }
  return null;
}
// Tab into the pages from outside them - the outline, the section strip, the panel by Shift+Tab - goes to the reading
// page's line too (its first control; its last by Shift+Tab), else to the PDF area: the DOM's next stop is the first
// page's line (or the last page's), whose focus would scroll the document there. Only a Tab across the pages' edge is
// taken - from the last stop before the PDF area (the section strip's page button, where it shows) or, by Shift+Tab,
// from the first after it (the panel's) - and that stop is found by walking out from the area to the nearest one
// (findEdgeStop), a few elements, so a Tab outside the pages never reads every focusable element of the document and
// whether it shows.
const TABBABLE = 'a[href],button,input,select,textarea,summary,[tabindex]';
// Whether an element is a stop of the Tab order now: focusable by Tab, enabled, drawn, not hidden and not in an inert
// or hidden part.
function isTabStop(x: Element | null): x is HTMLElement {
  return (
    x instanceof HTMLElement &&
    x.matches(TABBABLE) &&
    x.tabIndex >= 0 &&
    !(x as HTMLButtonElement).disabled &&
    x.getClientRects().length > 0 &&
    !x.closest('[inert],[hidden]') &&
    getComputedStyle(x).visibility !== 'hidden'
  );
}
// The nearest Tab stop outside the PDF area on one side of it - the last before it, or (after) the first after it - or
// null. Walks out from the area element by element and passes a part that is not drawn (display: none, hidden, inert)
// whole.
function findEdgeStop(after: boolean): HTMLElement | null {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) => {
      const x = node as Element;
      if (
        x.hasAttribute('hidden') ||
        x.hasAttribute('inert') ||
        (!x.getClientRects().length && getComputedStyle(x).display === 'none')
      )
        return NodeFilter.FILTER_REJECT;
      return isTabStop(x) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
    },
  });
  let node = $('#left') as Node;
  if (after) while (node.lastChild) node = node.lastChild; // from the area's last node the next one is past the area
  walker.currentNode = node;
  return (after ? walker.nextNode() : walker.previousNode()) as HTMLElement | null;
}
// Where the focus came into the pages from, while it is in them: the stop a Tab into the pages was pressed on, or the
// control a digit key was pressed on (verdictKey) - an outline entry, a document tab, the section strip, the phone's
// tool bar - with the visit (captureVisit: the document and its switch) and build it was pressed on: a switch - also
// away and back - or a new build lets it go (findOutStop), as any focus outside the pages does. Shift+Tab from the
// reading line goes back there (below).
let CAME_FROM = null as { el: HTMLElement; visit: { doc: string | null; seq: number }; build: string } | null;
function noteCameFrom(element: HTMLElement) {
  CAME_FROM = { el: element, visit: captureVisit(), build: (META && META.pages_build) || '' };
}
document.addEventListener('focusin', (event) => {
  const target = event.target;
  if (target instanceof Element && !target.closest('#left')) {
    CAME_FROM = null;
    STOP_IN_VIEW = null;
  }
});
// Where Shift+Tab leaves the pages to: where the focus came from (CAME_FROM) while it is still a stop of this document
// and build before the pages - or, where nothing comes before them (a phone: the nav bar, the outline and the section
// strip are not drawn), one in the tool bar over the sheet (#bar1) -, else the last stop before the pages
// (findEdgeStop: the section strip's or the nav bar's page button), else the phone's position button (#btn-pos, which
// opens its pages as those do). null for none.
function findOutStop() {
  const came = CAME_FROM;
  if (came && !(currentVisit(came.visit) && came.build === ((META && META.pages_build) || ''))) CAME_FROM = null;
  const area = $('#left'),
    edge = findEdgeStop(false),
    control = CAME_FROM ? CAME_FROM.el : null;
  // the summary whose press brought the focus to the panel (goToSummaryPage)
  if (control && control.isConnected && control.classList.contains('pv-sum')) return control;
  if (
    control &&
    control.isConnected &&
    !area.contains(control) &&
    isTabStop(control) &&
    (control.compareDocumentPosition(area) & Node.DOCUMENT_POSITION_FOLLOWING || (!edge && control.closest('#bar1')))
  )
    return control;
  const positionButton = $('#btn-pos');
  return edge || (isTabStop(positionButton) ? positionButton : null);
}
addEventListener('keydown', (event) => {
  const active = document.activeElement as HTMLElement | null,
    area = $('#left');
  if (
    event.key !== 'Tab' ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.defaultPrevented ||
    !active ||
    active === document.body ||
    !active.closest ||
    active.closest('#left')
  )
    return;
  // The focus on the side of the area this Tab leaves from, the area shown with page lines, and the focus on the edge's
  // stop.
  if (
    !(
      active.compareDocumentPosition(area) &
      (event.shiftKey ? Node.DOCUMENT_POSITION_PRECEDING : Node.DOCUMENT_POSITION_FOLLOWING)
    ) ||
    !area.getClientRects().length ||
    !document.querySelector('#doc .pv') ||
    findEdgeStop(event.shiftKey) !== active
  )
    return;
  const readingPage = readingPageWithLine(),
    line = readingPage ? document.querySelector('#doc .pv[data-page="' + readingPage + '"]') : null,
    controls = line ? [...line.querySelectorAll('a,button,textarea,[tabindex="0"]')].filter(isTabStop) : [];
  event.preventDefault();
  const control = event.shiftKey ? controls[controls.length - 1] : controls[0];
  noteCameFrom(active);
  if (control) control.focus({ preventScroll: true });
  else searchToPage();
});
// Shift+Tab from the reading page's first stop leaves the pages the way the focus came in (findOutStop): back to where
// it came from while that is still a stop before the pages - the outline entry or the document tab a digit key was
// pressed on, the section strip's page button Tab came from - else to the last stop before them, the section strip's
// page button (a phone's position button). The pages do not move. The reading page's first stop is its line's first
// control, or - when pins are marked on that page - its first mark's badge, which Shift+Tab from the line reaches first
// in the DOM's order. The DOM's stop before it is the page before's line: each Shift+Tab would scroll the document a
// page up and never reach the outline. The earlier pages' lines are reached by PageUp, which makes each the reading
// page in turn. A line with its reason popover open keeps Tab to itself first (verdict/flow-reason.ts, on #doc), and
// another page's line or mark is left to the DOM's order - but for the stop Tab from the PDF area went to in view while
// the reading page had no line (STOP_IN_VIEW), which leaves the same way.
addEventListener('keydown', (event) => {
  if (
    event.key !== 'Tab' ||
    !event.shiftKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.defaultPrevented
  )
    return;
  // Beside the pages the panel is the reading line, and it stands after the pages in the DOM (verdict/view-panel.ts):
  // from its first stop the reading page's marks come next, as they do from a line, and from the first of those the way
  // out.
  const active = document.activeElement as HTMLElement | null,
    panel = active && active.closest ? (active.closest('#pv-panel') as HTMLElement | null) : null;
  const block = panel || (active && active.closest ? (active.closest('#doc .pgw') as HTMLElement | null) : null),
    line = panel || (block && (block.querySelector(':scope>.pv') || document.getElementById('pv-panel')));
  const inView = STOP_IN_VIEW;
  if (inView && !(currentVisit(inView.visit) && inView.build === ((META && META.pages_build) || '')))
    STOP_IN_VIEW = null;
  if (!(active && STOP_IN_VIEW && STOP_IN_VIEW.el === active)) {
    // the stop Tab went to in view (above), on a page with a line or none
    if (!active || !block || !line || Number(block.dataset.page) !== readingPageWithLine()) return;
    const first = [...block.querySelectorAll(TABBABLE)].find(isTabStop);
    if (first !== active) return;
    const marks = panel ? markStops(Number(panel.dataset.page)) : [];
    if (marks.length) {
      event.preventDefault();
      marks[marks.length - 1].focus();
      return;
    }
  }
  const to = findOutStop();
  if (!to) return;
  event.preventDefault();
  to.focus({ preventScroll: true });
  if (to.closest('#outline') || to.classList.contains('pv-sum')) {
    endJumpForScroll();
    to.scrollIntoView({ block: 'nearest' });
  }
}); // an outline entry comes into the outline's view; the pages stay
export {
  SAVING_LINES,
  CHIP_WATCH,
  KEYED_PAGE,
  KEY_SAVE_OUT,
  READING_LINE_PAGE,
  TABBABLE,
  LINE_TEXT,
  canVerdict,
  drawPageVerdicts,
  figureShort,
  figureVerdictBody,
  figureVerdictRoot,
  fillPageLine,
  jumpToPageLine,
  pageTakesVerdict,
  pageTargetOf,
  pageTargetShort,
  pageVerdictPins,
  noteCameFrom,
  canCancelVerdict,
  cancelLineVerdict,
  currentVerdictOn,
  watchFarLines,
  pageLineName,
  keepFocusOnLine,
  undoFromLine,
  dropPageLineOverlaps,
  pageUnderReadingLine,
  readingPageWithLine,
  sayGliding,
  isShownOnLine,
  pageLineSlot,
  verdictStateWord,
  stickReadingLine,
  stickSoon,
  isTabStop,
  topPinId,
  renderVerdictRow,
  sizePageLines,
  fitWrappedWords,
  verdictBadge,
  verdictDropped,
  verdictOldMarker,
  verdictPress,
  verdictTarget,
  verdictUndo,
};
