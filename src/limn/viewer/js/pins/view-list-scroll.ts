// ------------------------------------------------ The pin list's scroll
// What the list keeps of its scroll across a redraw (the row at its top, the section it is in), and the cards far from
// its view, which the browser skips until they come near.
import { $, $$, findAll, findMaybe } from '../platform/dom.ts';
// Cards far from the list's view are left for the browser to skip (.lazy: content-visibility:auto, list.css): it does
// not lay them out or paint them until they come near the view. Their markup stays whole and current all the while - a
// card coming back is drawn from what it holds then - and a focus, a find or a selection reaching into one draws it at
// once; a script's measure inside one lays it out for the answer, but the innerText of what is skipped is empty. What
// it saves: each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added
// makes the browser lay out all the text in the page again - every card in the open panel with it, so the first wheel
// scroll through a figure document of many pages stalls on those layouts. Only a card more than a view's height above
// or below the list's view is skipped (lazyWatch): skipping contains a card (paint containment), which draws its parts
// on whole pixels and clips what reaches past its edge (a focus ring, a 44px touch target's hit area), so a card in
// view, or scrolled to, is never held and draws as it is. A card being edited or holding the reply box is never
// skipped: containment would hold the fixed action row (compact) inside the card. A skipped card stands at the height
// it had when it went (--card-h, from the observer's own measure: no extra layout). With a guessed height instead the
// list would move under a person scrolled down it at every draw, by the guess's error over every card above, and a jump
// to a card (a mark's badge, [검토 M]) would aim by guesses. The height goes stale when the list's width or its font
// changes, so then every card is drawn again and sorted anew (lazyAgain), as at each draw - which makes new cards, all
// drawn once. A height that goes stale otherwise (a card changed in place while skipped) comes right as the card comes
// near: the browser's scroll anchoring keeps the view where it stands as it grows or shrinks. A draw makes new
// elements, which that anchoring cannot hold, so a row in the view before it (listKeep) is put back where it stood: its
// cards may stand at other heights than the ones they replace.
let LAZY_IO: IntersectionObserver | null = null,
  LAZY_ROOT: HTMLElement | null = null,
  LAZY_WIDTH = 0,
  LAZY_HEIGHT = -1;
// After a draw: the first row kept (listKeep) that is still drawn in the section it was in is put back where it stood -
// a row whose pin a poll moved to another section (검토 대기, 완료) or deleted gives way to the next, and with none
// left nothing is put back: followed into its new section, the view would jump past every card still open. Then every
// new card is sorted.
function lazyCards(keep: { sel: string; sec: string; top: number }[]) {
  const scroller = listScroller();
  for (const kept of keep) {
    const row = findMaybe(document, kept.sel, HTMLElement);
    if (!row || !row.getClientRects().length || listSection(row) !== kept.sec) continue;
    const moved = row.getBoundingClientRect().top - kept.top;
    if (Math.abs(moved) >= 0.5) scroller.scrollTop += moved;
    break;
  }
  const list = $('#list');
  LAZY_WIDTH = list.getClientRects().length ? list.clientWidth : 0;
  lazyWatch();
}
// Has every card sorted from its first report, by an observer whose margin is the scroller's height now, in px above
// and below its view (a percentage would be of the root's width): it is made again when that height or the scroller
// changes.
function lazyWatch() {
  if (!window.IntersectionObserver) return;
  const scroller = listScroller(),
    height = scroller.clientHeight;
  if (LAZY_IO) LAZY_IO.disconnect();
  if (!LAZY_IO || LAZY_ROOT !== scroller || LAZY_HEIGHT !== height) {
    LAZY_ROOT = scroller;
    LAZY_HEIGHT = height;
    LAZY_IO = new IntersectionObserver(lazySort, { root: scroller, rootMargin: height + 'px 0px' });
  }
  for (const card of $$('#list .pin.card')) LAZY_IO.observe(card);
}
// The observer's reports: a card that came within a view's height of the list's view is drawn as it is; one that went
// further is skipped at the height it has now - not a card that is not laid out (the panel folded: no height to stand
// at), being edited or holding the reply box.
function lazySort(entries: IntersectionObserverEntry[]) {
  for (const entry of entries) {
    const card = entry.target;
    // LAZY_IO observes the list's cards (lazyWatch), all HTML.
    if (!(card instanceof HTMLElement)) continue;
    if (entry.isIntersecting) {
      card.classList.remove('lazy');
      continue;
    }
    if (
      card.classList.contains('lazy') ||
      !entry.boundingClientRect.height ||
      card.classList.contains('editing') ||
      card.querySelector('.reply-box')
    )
      continue;
    const style = getComputedStyle(card); // the content box: what contain-intrinsic-size sets
    card.style.setProperty(
      '--card-h',
      entry.boundingClientRect.height -
        parseFloat(style.paddingTop) -
        parseFloat(style.paddingBottom) -
        parseFloat(style.borderTopWidth) -
        parseFloat(style.borderBottomWidth) +
        'px',
    );
    card.classList.add('lazy');
  }
}
// Every card drawn once more and sorted anew, a row in the view kept in place: the skipped cards' heights are stale. So
// they are when the list's width changes or it is shown (a card not laid out was not skipped), and when a font the list
// is set in comes in (a slice of the bundled Pretendard for letters not drawn before): their heights were read in the
// fallback face. The fonts PDF.js adds are not the list's, and fire no loadingdone besides.
function lazyAgain() {
  const keep = listKeep();
  $$('#list .pin.card.lazy').forEach((card) => card.classList.remove('lazy'));
  lazyCards(keep);
}
// The box the list scrolls in: the list itself, or in compact the panel (#right), which holds the tool bar above it.
function listScroller() {
  return document.body.classList.contains('compact') ? $('#right') : $('#list');
}
// The cards and archive rows in the list's view, top first, each with its section and its top: the rows lazyCards may
// put back. None while the list is at its top (the browser does not anchor there either: what a draw adds above it
// shows) or is not laid out.
function listKeep(): { sel: string; sec: string; top: number }[] {
  const scroller = listScroller(),
    out: { sel: string; sec: string; top: number }[] = [];
  if (!scroller.scrollTop || !scroller.getClientRects().length) return out;
  const viewRect = scroller.getBoundingClientRect();
  for (const row of findAll(
    document,
    '#list .pin[data-id],#list .arc-row[data-id],#list .rv-row[data-id]',
    HTMLElement,
  )) {
    if (!row.getClientRects().length) continue;
    const rect = row.getBoundingClientRect();
    if (rect.bottom <= viewRect.top) continue;
    if (rect.top >= viewRect.bottom) break;
    out.push({
      sel:
        '#list ' +
        (row.classList.contains('arc-row') ? '.arc-row' : row.classList.contains('rv-row') ? '.rv-row' : '.pin') +
        '[data-id="' +
        CSS.escape(row.dataset.id || '') +
        '"]',
      sec: listSection(row),
      top: rect.top,
    });
  }
  return out;
}
// The section a row is drawn in: open (#pins), awaiting review (#review-pins) or done (#done-list).
function listSection(row: Element) {
  const section = row.closest('#pins,#review-pins,#done-list');
  return section ? section.id : '';
}
export { LAZY_IO, LAZY_WIDTH, LAZY_HEIGHT, lazyCards, lazyWatch, lazyAgain, listScroller, listKeep };
