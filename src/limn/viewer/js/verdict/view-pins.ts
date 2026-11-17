// ------------------------------------------------ A verdict pin, as the lists draw it (domain.md §판정 핀)
// Who may make a verdict, what a verdict pin is about - its page's whole target, or a figure - and where it stands
// among the verdicts of one target (the current one, the ones it replaced), with the badges and marks that say so.
// verdict/flow-line.ts draws the composer's verdict row and the page verdict lines from these.
import {
  META,
  isFigureKind,
  DOC,
  isViewOnlyKind,
  OPEN_ALL,
  REVIEW_ALL,
  DONE_ALL,
  DOCS,
  DEFAULT_DOC,
} from '../app/state.ts';
import { ROLE, PIN_STATE } from '../app/rules-tables.ts';
import { verdictOf, pinState } from '../app/rules-pins.ts';
import { html } from '../platform/markup.ts';
import { translate, translateTemplate, josa } from '../platform/i18n.ts';
import { verdictLabel, pdoc, docKindOf, pageVerdictsOn, isRegion } from '../documents/state.ts';
import { isElementLost, pinPlace, isFrac } from '../pdf/view-figure.ts';
import { CONFIRMING_PIN, CONFIRMING } from '../pins/state.ts';
import { josaToward, claimActive } from '../pins/view-card-parts.ts';
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
    groups: Map<string, { t: VerdictTarget; all: { p: Pin; t: VerdictTarget }[] }> = new Map(),
    seen = new Set<number>();
  for (const pin of OPEN_ALL.concat(REVIEW_ALL, DONE_ALL, [...CONFIRMING_PIN.values()])) {
    if (seen.has(pin.id) || pdoc(pin) !== doc || !verdictOf(pin)) continue;
    seen.add(pin.id);
    const target = verdictTargetOf(pin, kind);
    if (!target) continue;
    const group = groups.get(target.key) || { t: target, all: [] };
    group.all.push({ p: pin, t: target });
    groups.set(target.key, group);
  }
  const out: VerdictOrder = { groups: new Map(), cur: new Map() };
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
  const out: Map<number, Pin[]> = new Map();
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
// A pin's state on the line: what the dot would say, in the line's words. The pin is the page target's newest verdict.
function verdictStateWord(pin: Pin) {
  const state = pinState(pin);
  if (state === PIN_STATE.REVIEW || CONFIRMING.has(pin.id)) return translate('검토 대기');
  if (state === PIN_STATE.DONE) return translate('처리됨');
  return claimActive(pin) ? translate('처리 중') : translate('처리 대기');
}
export {
  VERDICT_ARM_MS,
  canVerdict,
  verdictBadge,
  verdictTarget,
  dropPageLineOverlaps,
  WHOLE_PAGE,
  pageTakesVerdict,
  pageTargetOf,
  verdictOrder,
  pageVerdictPins,
  verdictOldMarker,
  verdictStateWord,
};
