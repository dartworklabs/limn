// ------------------------------------------------ Marks a badge or card covers
// A pin's mark on the page sits under its badge, the open composer or the panel: where the badge stands (markBadgeSides),
// which marks something covers, and bringing a covered mark into view; the mark Tab stops among them.
import { pageNoSides } from '../pdf/view-pages.ts';
import { $$, $, findAll } from '../platform/dom.ts';
import { markBadgeRoom, markBadgeIn, markHitSides } from '../pdf/view-badges.ts';
import { pendingBadgeSide } from '../pdf/input-selection.ts';
import { MARK_HIDDEN, TIP_AT, armedTipElement, hideTip, keyInput } from '../platform/tooltip.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
// Re-decides every page number's place (pageNoSides) and every drawn mark's badge side for its page's width and margin
// now (a zoom, a re-fit or a band change moves both), then how far each badge's press area reaches (markHitSides: the
// badges' distances follow the same width). A mark on a page that is not laid out keeps its side until the page shows
// again.
function markBadgeSides() {
  pageNoSides();
  const rooms = new Map();
  findAll(document, '.mark', HTMLElement).forEach((mark) => {
    const page = mark.parentElement;
    if (!rooms.has(page)) rooms.set(page, markBadgeRoom(page));
    const room = rooms.get(page);
    if (room) mark.classList.toggle('in', markBadgeIn(Number(mark.dataset.fx), room.w, room.pad, room.reach));
  });
  findAll(document, '.sel.pending', HTMLElement).forEach(pendingBadgeSide);
  markHitSides();
  markCoverSkip();
} // the pending boxes' '+' badges follow the same rule
// A badge no scroll can show is no stop for the keyboard (docs/handbook/viewer.md §모바일 레이아웃): otherwise Tab
// would put the ring on a mark the person cannot see, and its tooltip would float over the box that hides it. The
// covers are the boxes drawn over the pages, each where it is laid out (MARK_COVERS): the panel (#right: the sheet, the
// overlay panel, the closed sheet's bar) and the status line standing on the sheet's top edge (#status-dock, outside
// the panel so its action can reach up over the pages). The bars that also stand over the pages do so inside the
// panel's box: the tool bar is the sheet's head, and the phone's search row (#doc-nav at its foot) lies over the closed
// bar. A badge is a stop while the pages can scroll it, up or down within their ends, to where it stands whole in the
// pages' view (#left's box within the window) clear of every cover in its columns (markShift) - wherever it stands now,
// so Tab meets the badges under the sheet in turn and brings each out (markReveal). Were the badges a cover is over at
// that moment passed over, Tab from #3 would go past #4 and #5 to #6, whose scroll then shows the two it passed. No
// stop: a badge under the overlay panel (it runs the pages' height), one at the last page's foot the pages end before
// bringing above the sheet, every badge with the sheet pulled up to the document bar. A scroll moves a badge and the
// room it can go to alike, so it moves no stop. A badge whose centre a cover is over now (or one out of view with
// nowhere to show) is hidden (MARK_HIDDEN): a script's focus or the person's scroll can leave the focus on it, and its
// description does not show (platform/tooltip.ts showTip) - one standing over it goes. The boxes are compared, not
// hit-tested: a hit test per badge is too slow for a pass that a scroll pays every frame with many badges on screen;
// the comparison is cheap. Every box is read before any stop is written, and only a stop that changes is written.
const MARK_COVERS = ['#right', '#status-dock'],
  MARK_EDGE = 8; // MARK_EDGE: px a revealed badge keeps clear of a cover or the view's edge
/** The pages' view: #left's box within the window. */
function markView(): { left: number; top: number; right: number; bottom: number } {
  const rect = $('#left').getBoundingClientRect();
  return {
    left: Math.max(rect.left, 0),
    top: Math.max(rect.top, 0),
    right: Math.min(rect.right, innerWidth),
    bottom: Math.min(rect.bottom, innerHeight),
  };
}
/** The covers' boxes laid out over the view, each cut to it. */
function markCoverBoxes(view: { left: number; top: number; right: number; bottom: number }) {
  const out: { left: number; top: number; right: number; bottom: number }[] = [];
  for (const selector of MARK_COVERS) {
    const cover = $(selector);
    if (!cover || !cover.getClientRects().length) continue;
    const rect = cover.getBoundingClientRect();
    const x0 = Math.max(rect.left, view.left),
      y0 = Math.max(rect.top, view.top),
      x1 = Math.min(rect.right, view.right),
      y1 = Math.min(rect.bottom, view.bottom);
    if (x1 > x0 && y1 > y0) out.push({ left: x0, top: y0, right: x1, bottom: y1 });
  }
  return out;
}
// How far the pages scroll down (px, up negative) to bring the badge's box into a part of the view that none of the
// covers is over in the badge's columns, the scroll kept within [minScroll, maxScroll] (what the pages can still scroll
// up and down): the least such distance, null where no part can hold it. A badge wholly in such a part already is 0 -
// it is not moved, as the browser leaves a control in view - and one brought in stands MARK_EDGE px clear of that
// part's ends where the part has the room. Pure.
function markShift(
  badge: { left: number; top: number; right: number; bottom: number },
  view: { left: number; top: number; right: number; bottom: number },
  covers: { left: number; top: number; right: number; bottom: number }[],
  minScroll: number,
  maxScroll: number,
): number | null {
  let spans = [[view.top, view.bottom]];
  for (const cover of covers) {
    if (cover.right <= badge.left || cover.left >= badge.right) continue;
    spans = spans.flatMap(([top, bottom]) =>
      cover.bottom <= top || cover.top >= bottom
        ? [[top, bottom]]
        : [...(cover.top > top ? [[top, cover.top]] : []), ...(cover.bottom < bottom ? [[cover.bottom, bottom]] : [])],
    );
  }
  const height = badge.bottom - badge.top;
  let best = null as number | null;
  for (const [top, bottom] of spans) {
    if (bottom - top < height) continue;
    const margin = badge.top >= top && badge.bottom <= bottom ? 0 : Math.min(MARK_EDGE, (bottom - top - height) / 2);
    const shift = Math.min(
      maxScroll,
      Math.max(
        minScroll,
        badge.top < top + margin
          ? badge.top - top - margin
          : badge.bottom > bottom - margin
            ? badge.bottom - bottom + margin
            : 0,
      ),
    );
    // the pages end before the badge gets there
    if (badge.top - shift < top - 0.5 || badge.bottom - shift > bottom + 0.5) continue;
    if (best === null || Math.abs(shift) < Math.abs(best)) best = shift;
  }
  return best;
}
function markCoverSkip() {
  const pane = $('#left');
  if (!pane) return;
  const view = markView(),
    covers = markCoverBoxes(view),
    minScroll = -pane.scrollTop,
    maxScroll = pane.scrollHeight - pane.clientHeight - pane.scrollTop;
  const badges = $$('.mark button.mark-jump') as HTMLElement[];
  const at = badges.map((badge) => {
    const rect = badge.getBoundingClientRect();
    if (!rect.width) return { stop: 0, hid: false };
    const centerX = rect.left + rect.width / 2,
      centerY = rect.top + rect.height / 2;
    // a stop while the pages can bring it to where it shows, whether in view or not
    const stop = markShift(rect, view, covers, minScroll, maxScroll) === null ? -1 : 0;
    return {
      stop,
      hid:
        centerX >= view.left && centerX < view.right && centerY >= view.top && centerY < view.bottom
          ? covers.some(
              (cover) =>
                centerX >= cover.left && centerX < cover.right && centerY >= cover.top && centerY < cover.bottom,
            )
          : stop < 0,
    };
  });
  badges.forEach((badge, index) => {
    const state = at[index];
    if (badge.tabIndex !== state.stop) badge.tabIndex = state.stop;
    if (state.hid) MARK_HIDDEN.add(badge);
    else MARK_HIDDEN.delete(badge);
  });
  for (const tipTarget of [TIP_AT && TIP_AT.el, armedTipElement])
    if (tipTarget && MARK_HIDDEN.has(tipTarget)) {
      hideTip();
      break;
    }
}
// Scrolls the pages to bring a badge to where it shows (markShift), when they can. It shows something, so a jump on its
// way ends first (endJumpForScroll): its settling would glide the pages back.
function markReveal(badge: HTMLElement) {
  const pane = $('#left'),
    view = markView(),
    rect = badge.getBoundingClientRect();
  if (!rect.width) return;
  const shift = markShift(
    rect,
    view,
    markCoverBoxes(view),
    -pane.scrollTop,
    pane.scrollHeight - pane.clientHeight - pane.scrollTop,
  );
  if (!shift) return;
  endJumpForScroll();
  pane.scrollBy({ top: shift, behavior: 'instant' });
}
// Tab and Shift+Tab bring the badge they reach to where it shows. The browser scrolls a focused control into the pages'
// box only, and on the tablet's or the phone's sheet, under its status line or its closed bar, that can be out of
// sight: the focus would stay under the cover and its description over it. The key moves the focus as its default
// action, in its own task, so a focus that arrives while MARK_TAB is set is the walk's; a focus a script puts on a
// badge (focusPlace, without a scroll) is left where it is. The focus events come before the browser's own scroll for
// the focus, which then finds the badge in view.
let MARK_TAB = false;
function markTabKey(event: KeyboardEvent) {
  if (event.key !== 'Tab') return;
  MARK_TAB = true;
  setTimeout(() => {
    MARK_TAB = false;
  }, 0);
}
// What the covers cover changes without the marks being drawn again: the sheet opens, closes or is dragged to another
// height, the status line comes or goes, the overlay panel slides in, the window is resized, or the pages scroll under
// them. The covers' sizes are watched (the sheet's open and closed heights differ, a status line goes from none to its
// line); a scroll asks again at most once a frame. The keyboard's focus on a badge a cover has come over (the sheet a
// press of Enter on it opened, Ctrl+\ or a height chosen) is brought out again, as the keyboard's focus in a field is
// kept above the touch keyboard; a badge the person scrolls under a cover keeps the focus where it is, as a control
// scrolled out of the window does, and only its description goes - scrolling the pages back would undo the person's own
// scroll, and moving the focus would lose their place in the Tab order. The next Tab goes on from it.
function markCoversMoved() {
  markCoverSkip();
  const focused = document.activeElement;
  if (focused instanceof HTMLElement && MARK_HIDDEN.has(focused) && keyInput()) markReveal(focused);
}
export { markBadgeSides, MARK_COVERS, markCoverSkip, markReveal, MARK_TAB, markTabKey, markCoversMoved };
