// ------------------------------------------------ PDF pages: their boxes, scale and zoom, and arriving at one
import {
  DOC,
  PAGE_SCALE,
  LAYOUT,
  LAYOUT_MODE,
  META,
  VIEW_MODE,
  ZOOMED,
  imeKey,
  isFigureKind,
  setPageScale,
  setZoomed,
} from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { prefs, savePrefs } from '../platform/prefs.ts';
import { placeChips } from '../platform/notices.ts';
import { withDocQuery } from '../documents/view-tabs.ts';
import { setViewMode } from '../revisions/flow.ts';
import { OUTLINE_PICK_GAP, spotTop } from './view-outline.ts';
import { invalidateVectorDraws, observeVectorPages } from './view-draw.ts';
import { MARKDOWN_VIEW, isMarkdownDoc, buildMarkdownDoc } from '../markdown/view.ts';
import { COMPOSE } from '../composer/flow-pick.ts';
import {
  JUMP_TARGET,
  HAND_SCROLL_AT,
  isAutoScrolling,
  glideInto,
  glideTo,
  scrollTopFor,
  sizePageLines,
} from '../verdict/flow-line.ts';
import { restoreReasonFocus, holdReasonFocus } from '../verdict/flow-reason.ts';
import { markBadgeSides, marks } from '../pins/flow-list.ts';
import { restoreAnchor, topAnchor } from '../documents/flow-rebuild.ts';
import { $, $$ } from '../platform/dom.ts';
// The URL of a page's image in the build on screen: /pages/<META.pages_build>/<name>, which the server caches for a
// year because a build's images never change (docs/handbook/api.md). Without a build name, /pages/<name>?v=<built_at>.
function pageSrc(page) {
  const build = META.pages_build;
  return withDocQuery(
    build
      ? '/pages/' + encodeURIComponent(build) + '/' + encodeURIComponent(page.name)
      : '/pages/' + encodeURIComponent(page.name) + '?v=' + encodeURIComponent(META.built_at),
  );
}
// Page sizes (docs/handbook/viewer.md §PDF 영역 전용 확대): every page box is its own paper width (pt_w, in points)
// times one scale (PAGE_SCALE) for the document on screen (CSS px per point), so the pages keep the sizes they have on
// paper relative to each other - a one-column figure is half as wide as a two-column one, as in print. PAGE_SCALE =
// POINT_PX is the print size (1pt = 1/72in, the CSS inch 96px), which the zoom figure reads as 100%. Fit-width fits the
// widest page.
const POINT_PX = 96 / 72;
// The widest page's width in points: fit-width fits it and the limits count it. 612 (a letter page) before there are
// pages, only so that the arithmetic never divides by zero - nothing is drawn then.
function widestPagePoints() {
  const widest =
    META && META.pages ? META.pages.reduce((widestSeen, page) => Math.max(widestSeen, page.pt_w || 0), 0) : 0;
  return widest > 0 ? widest : 612;
}
// The most common of the page widths (points): the mode, the wider on a tie; 0 for none. A figure document opens by it
// (openScale): its one wide outlier (a graphical abstract) scrolls sideways instead of shrinking every figure. Pure.
function commonWidth(widths) {
  const counts = new Map();
  let best = 0,
    most = 0;
  for (const width of widths) {
    if (!(width > 0)) continue;
    const count = (counts.get(width) || 0) + 1;
    counts.set(width, count);
    if (count > most || (count === most && width > best)) {
      most = count;
      best = width;
    }
  }
  return best;
}
// The document's most common page width in points (commonWidth), else its widest.
function commonPageWidth() {
  const common = META && META.pages ? commonWidth(META.pages.map((page) => page.pt_w)) : 0;
  return common > 0 ? common : widestPagePoints();
}
// A page box's CSS width for a page ptw points wide at a scale: whole px, at least 1. Pure.
function pageWidth(ptw, scale) {
  return Math.max(1, Math.round(ptw * scale));
}
// Every page box sits in a block of its own (.pgw) that a page verdict line (verdict.ts) joins under it: the line is
// sticky to the bottom of the PDF area within that block, so it floats while its page is in view and settles under the
// page at its end - in one block with every page it would float over the next pages' lines.
function buildDoc() {
  // A document the browser draws from its source has no pages (md-surface.ts).
  if (isMarkdownDoc()) {
    COMPOSE.box = null;
    buildMarkdownDoc();
    return;
  }
  MARKDOWN_VIEW.gen++;
  MARKDOWN_VIEW.shown = '';
  // A draw of the Markdown surface still on its way stops here.
  document.body.classList.remove('md-surface');
  // A focus in the reason popover comes back with the pages (restoreReasonFocus).
  const doc = $('#doc'),
    focus = holdReasonFocus();
  doc.replaceChildren();
  COMPOSE.box = null;
  META.pages.forEach((page, index) => {
    const pageBox = document.createElement('div');
    pageBox.className = 'pg';
    pageBox.id = 'p' + (index + 1);
    pageBox.dataset.page = String(index + 1);
    pageBox.dataset.ptw = String(page.pt_w);
    pageBox.style.width = pageWidth(page.pt_w, PAGE_SCALE) + 'px';
    pageBox.style.aspectRatio = page.pt_w + ' / ' + page.pt_h;
    setHtml(
      pageBox,
      html`<span class="no">${index + 1}</span><img loading="lazy" draggable="false" alt="${translateTemplate('{page}쪽', { page: index + 1 })}" src="${pageSrc(page)}">`,
    );
    const wrapper = document.createElement('div');
    wrapper.className = 'pgw';
    wrapper.dataset.page = String(index + 1);
    wrapper.appendChild(pageBox);
    doc.appendChild(wrapper);
  });
  pageWidthVars();
  marks();
  observeVectorPages();
  drawZoom();
  restoreReasonFocus(focus);
}
// save=false is auto-fit - never saved. If a width fit for a narrow first window persisted into a wider window, the
// pages would look too small. The scale is never saved in compact (mid/narrow) - so a width fit for a folded screen
// never overrides the spread/desktop setting. The widest page's width stays within ZOOM_MIN-ZOOM_MAX times the
// fit-width (minimum 160px), widened to hold the print size so [100%] is always in reach - also for a page smaller than
// 160px. Overflow scrolls horizontally only within the PDF area (#left).
const ZOOM_MIN = 0.5,
  ZOOM_MAX = 5,
  ZOOM_STEP = 1.2;
// The widest page's width limits [low, high] in px, for the fitted width fit and the print-size width actual. Not
// rounded: a rounded limit would put the print size a fraction of a pixel out of reach. Pure.
function widthBounds(fit, actual) {
  const fitted = Math.max(160, fit),
    low = Math.min(actual, Math.max(160, fitted * ZOOM_MIN));
  return [low, Math.max(low, fitted * ZOOM_MAX, actual)];
}
// The scale that fits the widest page to the PDF area (fitWidth).
function fitScale() {
  return fitWidth() / widestPagePoints();
}
// Sets the scale PAGE_SCALE within widthBounds and gives every page box its own width (pageWidth); saved in wide unless
// save is false (saveScale). The marks' badges follow the new widths (markBadgeSides), and so do the page verdict lines
// (sizePageLines), the save chips (placeChips) and [더보기]'s zoom figure (drawZoom).
function setScale(scale, save?) {
  const widest = widestPagePoints(),
    bounds = widthBounds(fitWidth(), widest * POINT_PX);
  setPageScale(Math.min(bounds[1], Math.max(bounds[0], scale * widest)) / widest);
  SCALE_UNBOUNDED = false;
  sizePages();
  markBadgeSides();
  sizePageLines();
  placeChips();
  if (save !== false && LAYOUT === LAYOUT_MODE.WIDE) saveScale();
  invalidateVectorDraws();
  drawZoom();
}
// Gives every page box its width at the scale PAGE_SCALE, bounded or not (setScale bounds the scale first).
function sizePages() {
  const widest = widestPagePoints();
  $$('.pg').forEach((pageBox) => {
    pageBox.style.width = pageWidth(+pageBox.dataset.ptw || widest, PAGE_SCALE) + 'px';
  });
  pageWidthVars();
}
// The page widths as the side column of the page verdict panel lays the blocks out (verdict-panel.css): each block's
// page width (--pg-w) and the widest page's (--pg-max, on #doc), so that pages of different widths stand on one axis.
function pageWidthVars() {
  const widest = widestPagePoints();
  $('#doc').style.setProperty('--pg-max', pageWidth(widest, PAGE_SCALE) + 'px');
  $$('#doc .pgw>.pg').forEach((pageBox) => {
    (pageBox.parentElement as HTMLElement).style.setProperty('--pg-w', (pageBox as HTMLElement).style.width);
  });
}
// Whether the pages stand at a scale PAGE_SCALE that no PDF-area width has bounded since their sizes changed
// (reapplyScale). Only the changes view brings it about: it hides the PDF area, and a scroller that is not drawn
// measures 0 wide, so bounding the scale by that width would cut an 1800px page to the least it allows (816px, the
// print size of a letter page).
let SCALE_UNBOUNDED = false;
// Applies PAGE_SCALE again after the pages' paper sizes changed (a new build with the same page count). A drawn PDF
// area bounds the scale (setScale). A hidden one has no width to bound it by: the boxes take their new widths at
// PAGE_SCALE as it is, and the bounds follow when the area shows again (boundScale).
function reapplyScale() {
  if ($('#left').getClientRects().length) {
    setScale(PAGE_SCALE, false);
    return;
  }
  sizePages();
  SCALE_UNBOUNDED = true;
}
// The PDF area shows again: bounds a scale reapplyScale left alone by the width it has now, keeping the reading spot.
function boundScale() {
  if (!SCALE_UNBOUNDED || !$('#left').getClientRects().length) return;
  const anchor = topAnchor();
  setScale(PAGE_SCALE, false);
  restoreAnchor(anchor);
}
// The zoom as [더보기] and the tool bar's zoom button show it: a scale against the print size, in percent, rounded; 100
// before a scale is known. Pure.
function zoomPercent(scale) {
  return scale > 0 ? Math.round((scale / POINT_PX) * 100) : 100;
}
// Writes the zoom figure: [더보기]'s (a live region: it is read out as it changes) and the desktop tool bar's zoom
// button, which shows the zoom now and goes to 100% - pressed (aria-pressed) while the figure is 100%. Its name and tip
// say both.
function drawZoom() {
  const figure = zoomPercent(PAGE_SCALE) + '%',
    moreFigure = $('#m-zoom');
  if (moreFigure) moreFigure.textContent = figure;
  const button = $('#btn-actual');
  if (!button) return;
  const buttonFigure = button.querySelector('.z');
  if (buttonFigure) buttonFigure.textContent = figure;
  button.setAttribute('aria-pressed', String(figure === '100%'));
  button.setAttribute('aria-label', translateTemplate('실제 크기(100%)로 · 지금 {pct}', { pct: figure }));
  button.dataset.tip = translateTemplate('실제 크기(100%)로: PDF 쪽을 인쇄한 지면 크기로 봅니다 · 지금 {pct}', {
    pct: figure,
  });
}
// The saved scale of the document on screen (wide only), or null: a figure document keeps its zoom against the print
// size (pinPrefs.figZoom), since print size is what a figure is checked at; any other document the widest page's width
// in px (pinPrefs.w) - one value for every LaTeX and view-only document. That page width is a manuscript's: a figure
// document never takes it, and opens at its own default (openScale) until a zoom is chosen on it.
function savedScale() {
  const preferences = prefs();
  if (isFigureKind(META.kind))
    return typeof preferences.figZoom === 'number' && preferences.figZoom > 0 ? preferences.figZoom * POINT_PX : null;
  return typeof preferences.w === 'number' && preferences.w > 0 ? preferences.w / widestPagePoints() : null;
}
// Saves the scale on screen as savedScale reads it back.
function saveScale() {
  if (isFigureKind(META.kind)) savePrefs({ figZoom: Math.round((PAGE_SCALE / POINT_PX) * 1e4) / 1e4 });
  else savePrefs({ w: pageWidth(widestPagePoints(), PAGE_SCALE) });
}
// The scale a document opens at with nothing saved, for its most common and its widest page width (points) and the
// fitted width fit (px): a figure document at print size when its common page fits the PDF area - a wider outlier
// scrolls sideways - else with the common page fitted; any other document with its widest page fitted - in wide (wide
// true) at most 900px. Pure.
function openScale(isFigure, common, widest, fit, wide) {
  return isFigure ? Math.min(POINT_PX, fit / common) : (wide ? Math.min(fit, 900) : fit) / widest;
}
// The scale the screen picks for the document on screen (openScale).
function defaultScale() {
  return openScale(
    isFigureKind(META.kind),
    commonPageWidth(),
    widestPagePoints(),
    fitWidth(),
    LAYOUT === LAYOUT_MODE.WIDE,
  );
}
// In compact, whether the scale on screen is one the user chose rather than the one the screen picks (defaultScale):
// only a chosen one survives a re-fit (ZOOMED). Pressing [↔] on a figure that opened at print size is a choice; landing
// back on it is not.
function markZoomed() {
  if (LAYOUT !== LAYOUT_MODE.WIDE) setZoomed(Math.abs(PAGE_SCALE - defaultScale()) > PAGE_SCALE * 1e-3);
}
// The PDF area's width inside its padding (px).
function pdfAreaInnerWidth() {
  const pdfArea = $('#left'),
    style = getComputedStyle(pdfArea);
  return pdfArea.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
}
// Fit-width: the scroller's inner width in whole px (pdfAreaInnerWidth: its padding is the gap, which on touch keeps
// the page off the handles' hit areas), on every band. It is measured inside the padding, not as clientWidth less a
// fixed allowance, which would miss the padding and scroll a fitted page sideways.
function fitWidth() {
  return Math.floor(pdfAreaInnerWidth());
}
// compact always takes the screen's scale (defaultScale) unless the user chose another (ZOOMED). wide takes it too
// unless a scale is saved. A scroller that is not drawn - the changes view hides it - has no width to fit: fitted to it
// the pages would shrink to the smallest width while the changes view is open, and the re-fit on the way back would
// take the reading spot from those small pages, bringing the manuscript back somewhere else (docs/handbook/viewer.md
// §변경 보기). A scale it leaves alone still meets a new column width: the badges and page numbers are placed again
// (markBadgeSides).
function autoFitWidth() {
  if (!$('#left').getClientRects().length) return;
  if (LAYOUT !== LAYOUT_MODE.WIDE ? !ZOOMED : savedScale() === null) setScale(defaultScale(), false);
  else markBadgeSides();
}
// The page number stands outside a page (.no-out) where a wider page leaves room left of it - a page centred under one
// at least the number's width and 8px wider on each side - and in the page's corner otherwise: on the widest pages, and
// on every page of a document whose pages are all one size, wherever the column puts them (a manuscript keeps its
// numbers in the corners).
function pageNoSides() {
  const pageBoxes = $$('#doc .pg');
  if (!pageBoxes.length || !pageBoxes[0].getClientRects().length) return;
  const widths = pageBoxes.map((pageBox) => pageBox.getBoundingClientRect().width),
    widest = Math.max(...widths);
  pageBoxes.forEach((pageBox, index) => {
    const no = pageBox.querySelector('.no') as HTMLElement | null;
    if (no) pageBox.classList.toggle('no-out', (widest - widths[index]) / 2 >= no.offsetWidth + 8);
  });
}
// The scale to build a document's pages at before autoFitWidth looks again: a saved one in wide, else the screen's,
// else the one on screen (a scroller that is not drawn has no width to take it from).
function startScale() {
  const saved = LAYOUT === LAYOUT_MODE.WIDE ? savedScale() : null;
  if (saved !== null) return saved;
  const screenScale = $('#left').getClientRects().length ? defaultScale() : 0;
  return screenScale > 0 ? screenScale : PAGE_SCALE > 0 ? PAGE_SCALE : POINT_PX;
}
// Zoom anchor: the page under screen coordinates (clientX, clientY) and its fraction within that page. If the point
// falls in the gap between pages, the vertically nearest page is used. Without coordinates, the center of the PDF area
// is used (keyboard/button).
function zoomAnchor(clientX, clientY) {
  const pdfArea = $('#left'),
    areaRect = pdfArea.getBoundingClientRect();
  if (clientX == null) {
    clientX = areaRect.left + pdfArea.clientWidth / 2;
    clientY = areaRect.top + pdfArea.clientHeight / 2;
  }
  let best = null as { pg: HTMLElement; r: DOMRect } | null,
    bestDistance = Infinity;
  for (const pageBox of $$('.pg')) {
    const rect = pageBox.getBoundingClientRect(),
      distance = clientY < rect.top ? rect.top - clientY : clientY > rect.bottom ? clientY - rect.bottom : 0;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = { pg: pageBox, r: rect };
    }
    if (distance === 0) break;
  }
  return best
    ? {
        pg: best.pg,
        cx: clientX,
        cy: clientY,
        fx: (clientX - best.r.left) / best.r.width,
        fy: (clientY - best.r.top) / best.r.height,
      }
    : null;
}
// Restores the anchor's in-page fractional position back to screen coordinates (clientX, clientY) - so the text under
// the pointer stays put even after zooming.
function zoomRestore(anchor, clientX?, clientY?) {
  if (!anchor) return;
  const pdfArea = $('#left'),
    pageRect = anchor.pg.getBoundingClientRect();
  pdfArea.scrollLeft += pageRect.left + anchor.fx * pageRect.width - (clientX == null ? anchor.cx : clientX);
  pdfArea.scrollTop += pageRect.top + anchor.fy * pageRect.height - (clientY == null ? anchor.cy : clientY);
}
// Zooms to a scale around a screen point (default: the PDF area's centre). A zoom keeps its own anchor: no arrival
// pulls it back.
function zoomTo(scale, clientX?, clientY?) {
  arrivalLetGo();
  const anchor = zoomAnchor(clientX, clientY);
  setScale(scale);
  markZoomed();
  zoomRestore(anchor);
}
// Zooms by a number of ZOOM_STEPs (negative: out).
function zoom(steps) {
  zoomTo(PAGE_SCALE * Math.pow(ZOOM_STEP, steps));
}
// [100%]: the print size, around the middle of the PDF area as the zoom buttons.
function actualSize() {
  zoomTo(POINT_PX);
}
// Fit width (fitScale): keeps the viewed page/position (anchored at the top) and resets horizontal scroll to the start.
function fitToWidth() {
  const anchor = topAnchor(),
    pdfArea = $('#left');
  setScale(fitScale(), LAYOUT === LAYOUT_MODE.WIDE);
  markZoomed();
  restoreAnchor(anchor);
  pdfArea.scrollLeft = 0;
}
// Arriving at a page - from the outline, a page field or the page list (goPage) and from a card's [보기] (jumpPin,
// jumpToPageLine): a figure page, one whose map names its figure body (meta figure_top), at its figure (figureTop); any
// other page at its top.
// The same arrival again while the pages rest on that figure goes to the page's top, and once more to the figure
// (docs/handbook/viewer.md §그림 쪽 도착). Each is a glide (glideTo, glideInto), so the keys wait for it to end.
function arrivePage(pageNumber: number) {
  const pageBox = document.getElementById('p' + pageNumber);
  if (!pageBox) return;
  const to = figureTop(pageNumber),
    pdfArea = $('#left');
  const pageTop = () => {
    const currentBox = document.getElementById('p' + pageNumber);
    return currentBox ? scrollTopFor(currentBox) : null;
  };
  if (to === null) {
    glideInto(pageBox);
    arrivalWatch(pageTop);
    return;
  }
  const top = !isAutoScrolling() && Math.abs(pdfArea.scrollTop - to) <= FIGURE_REST_PX;
  if (top) glideInto(pageBox);
  else glideTo(to);
  arrivalWatch(top ? pageTop : () => figureTop(pageNumber));
}
// The points of the page kept above an arrived figure at most: its label line ('PL18 · 지금 판') has no element.
const FIGURE_ROOM_POINTS = 24;
// The pages rest on a jump's place within this (a glide ends on or next to its pixel).
const FIGURE_REST_PX = 2;
// Every jump of the PDF area - a page, an outline entry's place, a card's [보기]; each glide starts this watch with its
// place, a function that measures it now - lands where it says once the pages rest. The glide's place is reckoned at
// its start, and the layout can still move under it: a save's list reload redraws hundreds of lines and stalls the
// glide past its guard (JUMP_TARGET lapses after a second), which gives scroll anchoring back, and the anchoring's
// adjustment can leave the figure tens to hundreds of pixels off; a line fitted on the way moves the pages after it,
// and a glide may not be written to (letLineBlocks). So each time the pages come to rest - after ARRIVAL_REST_MS
// without a scroll, the glide guard down - it measures the place again and glides the rest (glideTo: the guard and the
// held anchoring again), at most ARRIVAL_FIXES times, until ARRIVAL_SETTLE_MS after the rest that found nothing to do:
// each correction counts the window again from its own rest, which is always measured. A window counted from the first
// rest would close on a correction stopped on its way, whose guard lapses up to two seconds later, and leave the figure
// short by what remains. It only settles what nobody asked for: anything the person does meanwhile - a press, a key, a
// wheel or a touch anywhere, a window resize - lets it go (arrivalLetGo), for that starts a move of its own (a card's
// mark, a search hit, a zoom, another page) the watch must not undo; so do the person's scroll (HAND_ON_PAGES), another
// document and the pages not shown. A script that scrolls to show something lets it go too, with no input before it
// (endJumpForScroll: a search hit landing as the PDF's text is read, in the middle of a jump); a script that only keeps
// what is on screen does not, and may stop the glide: the place moved with it, and the settling goes on. A scroll by
// anything else, once the pages have rested at the place, lets it go at that rest: the place stayed and the pages left
// it, which is no layout's doing (at). A new jump replaces it. An instant jump needs no watch: nothing is on its way
// when a pass comes, and the pass keeps the view itself.
const ARRIVAL_REST_MS = 120,
  ARRIVAL_SETTLE_MS = 2000,
  ARRIVAL_FIXES = 3;
let ARRIVAL = null as {
    place: () => number | null;
    hand: number;
    doc: string | null;
    fixes: number;
    until: number;
    at: number | null;
  } | null,
  ARRIVAL_TIMER = 0;
/** @param place - the scrollTop the jump goes to, measured now; null once it is gone */
function arrivalWatch(place: () => number | null) {
  ARRIVAL = { place, hand: HAND_SCROLL_AT, doc: DOC, fixes: 0, until: 0, at: null };
  arrivalSoon();
}
// Measures again at the next rest: ARRIVAL_REST_MS from now, unless another scroll comes first.
function arrivalSoon() {
  clearTimeout(ARRIVAL_TIMER);
  ARRIVAL_TIMER = setTimeout(arrivalSettle, ARRIVAL_REST_MS);
}
// Ends the watch: the person or a script has started a move of its own.
function arrivalLetGo() {
  if (!ARRIVAL) return;
  ARRIVAL = null;
  clearTimeout(ARRIVAL_TIMER);
}
for (const eventType of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'gesturestart'])
  addEventListener(eventType, arrivalLetGo, { capture: true, passive: true }); // gesturestart: Safari's trackpad pinch
addEventListener('resize', arrivalLetGo);
// The watch at a rest: lets go, waits for the glide, records the pages at the place, or glides the rest.
function arrivalSettle() {
  const arrival = ARRIVAL,
    pdfArea = $('#left');
  if (!arrival) return;
  if (arrival.hand !== HAND_SCROLL_AT || arrival.doc !== DOC || !pdfArea.getClientRects().length) {
    ARRIVAL = null;
    return;
  }
  // Still on its way.
  if (JUMP_TARGET !== null || isAutoScrolling()) {
    arrivalSoon();
    return;
  }
  const now = performance.now();
  if (!arrival.until) arrival.until = now + ARRIVAL_SETTLE_MS;
  else if (now > arrival.until) {
    ARRIVAL = null;
    return;
  }
  const place = arrival.place();
  if (place === null) {
    ARRIVAL = null;
    return;
  }
  const to = Math.max(0, Math.min(pdfArea.scrollHeight - pdfArea.clientHeight, place));
  if (Math.abs(pdfArea.scrollTop - to) <= FIGURE_REST_PX) {
    arrival.at = to;
    return;
  }
  if (arrival.fixes >= ARRIVAL_FIXES || (arrival.at !== null && Math.abs(arrival.at - to) <= FIGURE_REST_PX)) {
    ARRIVAL = null;
    return;
  }
  arrival.fixes++;
  arrival.until = 0;
  arrival.at = null;
  glideTo(to);
  arrivalSoon();
}
// Whether the last jump is still on its way to its place: gliding (the guard, as above) or owed its settling - its
// watch has neither found the pages at the place nor let it go, and may glide the rest. A stop between scrolls is no
// rest while either holds, however long: a busy machine's frames come late. An outline pick waits on this before it
// lets go (outlinePickRest).
function jumpOnItsWay() {
  return JUMP_TARGET !== null || isAutoScrolling() || (ARRIVAL !== null && ARRIVAL.at === null);
}
// A scroll while it watches - the glide's own, an anchoring adjustment, a correction - waits for the next rest; a
// person's scroll (HAND_ON_PAGES) lets it go at that rest. So does a change of the pages' column's height, with no
// scroll at all: a line pass that holds anchoring off (holdPageView) or a far line drawn at its new height moves what
// is below it and says nothing to the scroller - the settling must not hang on anchoring to notice.
$('#left').addEventListener(
  'scroll',
  () => {
    if (ARRIVAL) arrivalSoon();
  },
  { passive: true },
);
new ResizeObserver(() => {
  if (ARRIVAL) arrivalSoon();
}).observe($('#doc'));
// #left's scrollTop of a page's figure arrival - its figure's top edge under the free PDF area's top (spotTop) with up
// to FIGURE_ROOM_POINTS of the page above it, down to the element above (figure_above) or else the page's top, and at
// least OUTLINE_PICK_GAP px - or null for a page without a figure body. In page points, so the room is the label line's
// at every zoom. Room past the page's top would stand the page below the reading line at a large zoom: the line would
// read the page before it.
function figureTop(pageNumber: number) {
  const pageBox = document.getElementById('p' + pageNumber),
    pageFacts = META && META.pages ? META.pages[pageNumber - 1] : null;
  if (!pageBox || !pageFacts || typeof pageFacts.figure_top !== 'number' || !(pageFacts.pt_h > 0)) return null;
  const height = pageBox.getBoundingClientRect().height,
    free = (pageFacts.figure_top - (typeof pageFacts.figure_above === 'number' ? pageFacts.figure_above : 0)) * height;
  return spotTop(
    pageBox,
    pageFacts.figure_top,
    Math.max(OUTLINE_PICK_GAP, Math.min((FIGURE_ROOM_POINTS * height) / pageFacts.pt_h, free)),
  );
}
// Goes to the page typed in the tool bar's [쪽 이동] field, or to the page given.
function goPage(entry?) {
  arrivePage(parseInt(entry === undefined ? $('#jump').value : entry, 10));
}
$('#jump').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !imeKey(event)) goPage();
});
// The page a typed entry goes to in a document of pageCount pages: a whole number clamped to 1..pageCount; null for an
// empty or non-number entry, which goes nowhere. Pure.
function clampPage(entry, pageCount) {
  const text = String(entry == null ? '' : entry).trim();
  if (!/^-?\d+$/.test(text) || !(pageCount >= 1)) return null;
  return Math.min(pageCount, Math.max(1, parseInt(text, 10)));
}
// The navigation sheet's page field (Enter or [이동]): goes to the clamped page and closes the sheet; nothing typed
// does nothing.
function goSheetPage() {
  const page = clampPage($('#ns-page-in').value, META && META.pages ? META.pages.length : 0);
  if (page === null) return;
  $('#nav-sheet').close();
  if (document.body.classList.contains('revision-open')) setViewMode(VIEW_MODE.MANUSCRIPT);
  goPage(page);
}
$('#ns-page-in').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !imeKey(event)) {
    event.preventDefault();
    goSheetPage();
  }
});

export {
  POINT_PX,
  ZOOM_STEP,
  actualSize,
  arrivalLetGo,
  arrivalWatch,
  arrivePage,
  autoFitWidth,
  boundScale,
  buildDoc,
  clampPage,
  drawZoom,
  figureTop,
  fitScale,
  fitToWidth,
  goPage,
  pdfAreaInnerWidth,
  jumpOnItsWay,
  markZoomed,
  goSheetPage,
  pageNoSides,
  pageSrc,
  pageWidth,
  widestPagePoints,
  reapplyScale,
  setScale,
  startScale,
  zoom,
  zoomAnchor,
  zoomRestore,
  zoomTo,
};
