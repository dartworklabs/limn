// ------------------------------------------------ PDF pages: their boxes, scale and zoom, and arriving at one
import {
  PAGE_SCALE,
  LAYOUT,
  META,
  ZOOMED,
  imeKey,
  isFigureKind,
  setPageScale,
  setZoomed,
  setComposeBox,
} from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { prefs, savePrefs } from '../platform/prefs.ts';
import { placeChips } from '../platform/notices.ts';
import { invalidateVectorDraws, observeVectorPages } from './view-draw.ts';
import { $, $$, findAll } from '../platform/dom.ts';
import { LAYOUT_MODE, VIEW_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc, withDocQuery } from '../documents/state.ts';
import { restoreAnchor, topAnchor } from '../layout/flow.ts';
import { ARRIVAL, arrivalSoon, arrivalLetGo } from '../layout/flow-scroll.ts';
import { pageChanges, pageMarkdown, pageMarks, pageVerdicts } from './state-seams.ts';
import { clampPage, goPage } from './view-page-jump.ts';

// The URL of a page's image in the build on screen: /pages/<META.pages_build>/<name>, which the server caches for a
// year because a build's images never change (docs/handbook/api.md). Without a build name, /pages/<name>?v=<built_at>.
function pageSrc(page: PageImage) {
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
function commonWidth(widths: number[]) {
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
function pageWidth(ptw: number, scale: number) {
  return Math.max(1, Math.round(ptw * scale));
}
// Every page box sits in a block of its own (.pgw) that a page verdict line (verdict/flow-line.ts) joins under it: the
// line is sticky to the bottom of the PDF area within that block, so it floats while its page is in view and settles
// under the page at its end - in one block with every page it would float over the next pages' lines.
function buildDoc() {
  // A document the browser draws from its source has no pages (markdown/view.ts).
  if (isMarkdownDoc()) {
    setComposeBox(null);
    pageMarkdown().build();
    return;
  }
  pageMarkdown().drawn().gen++;
  pageMarkdown().drawn().shown = '';
  // A draw of the Markdown surface still on its way stops here.
  document.body.classList.remove('md-surface');
  // A focus in the reason popover comes back with the pages (restoreReasonFocus).
  const doc = $('#doc'),
    focus = pageVerdicts().holdReasonFocus();
  doc.replaceChildren();
  setComposeBox(null);
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
  pageMarks().draw();
  observeVectorPages();
  drawZoom();
  pageVerdicts().restoreReasonFocus(focus);
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
function widthBounds(fit: number, actual: number) {
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
function setScale(scale: number, save?: boolean) {
  const widest = widestPagePoints(),
    bounds = widthBounds(fitWidth(), widest * POINT_PX);
  setPageScale(Math.min(bounds[1], Math.max(bounds[0], scale * widest)) / widest);
  SCALE_UNBOUNDED = false;
  sizePages();
  pageMarks().placeBadges();
  pageVerdicts().sizeLines();
  placeChips();
  if (save !== false && LAYOUT === LAYOUT_MODE.WIDE) saveScale();
  invalidateVectorDraws();
  drawZoom();
}
// Gives every page box its width at the scale PAGE_SCALE, bounded or not (setScale bounds the scale first).
function sizePages() {
  const widest = widestPagePoints();
  findAll(document, '.pg', HTMLElement).forEach((pageBox) => {
    pageBox.style.width = pageWidth(Number(pageBox.dataset.ptw) || widest, PAGE_SCALE) + 'px';
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
function zoomPercent(scale: number) {
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
function openScale(isFigure: boolean, common: number, widest: number, fit: number, wide: boolean) {
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
  else pageMarks().placeBadges();
}
// The page number stands outside a page (.no-out) where a wider page leaves room left of it - a page centred under one
// at least the number's width and 8px wider on each side - and in the page's corner otherwise: on the widest pages, and
// on every page of a document whose pages are all one size, wherever the column puts them (a manuscript keeps its
// numbers in the corners).
function pageNoSides() {
  const pageBoxes = findAll(document, '#doc .pg', HTMLElement);
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
// The page a zoom is anchored on and the point in it that stays under the pointer (zoomAnchor): the page box, the screen
// point and its fractions within the page.
type ZoomAnchor = { pg: HTMLElement; cx: number; cy: number; fx: number; fy: number };
// Zoom anchor: the page under screen coordinates (clientX, clientY) and its fraction within that page. If the point
// falls in the gap between pages, the vertically nearest page is used. Without coordinates, the center of the PDF area
// is used (keyboard/button), as it is for a point given by half.
function zoomAnchor(clientX?: number, clientY?: number): ZoomAnchor | null {
  const pdfArea = $('#left'),
    areaRect = pdfArea.getBoundingClientRect();
  const centre = clientX == null || clientY == null,
    pointX = centre ? areaRect.left + pdfArea.clientWidth / 2 : clientX,
    pointY = centre ? areaRect.top + pdfArea.clientHeight / 2 : clientY;
  let best = null as { pg: HTMLElement; r: DOMRect } | null,
    bestDistance = Infinity;
  for (const pageBox of findAll(document, '.pg', HTMLElement)) {
    const rect = pageBox.getBoundingClientRect(),
      distance = pointY < rect.top ? rect.top - pointY : pointY > rect.bottom ? pointY - rect.bottom : 0;
    if (distance < bestDistance) {
      bestDistance = distance;
      best = { pg: pageBox, r: rect };
    }
    if (distance === 0) break;
  }
  return best
    ? {
        pg: best.pg,
        cx: pointX,
        cy: pointY,
        fx: (pointX - best.r.left) / best.r.width,
        fy: (pointY - best.r.top) / best.r.height,
      }
    : null;
}
// Restores the anchor's in-page fractional position back to screen coordinates (clientX, clientY) - so the text under
// the pointer stays put even after zooming.
function zoomRestore(anchor: ZoomAnchor | null, clientX?: number, clientY?: number) {
  if (!anchor) return;
  const pdfArea = $('#left'),
    pageRect = anchor.pg.getBoundingClientRect();
  pdfArea.scrollLeft += pageRect.left + anchor.fx * pageRect.width - (clientX == null ? anchor.cx : clientX);
  pdfArea.scrollTop += pageRect.top + anchor.fy * pageRect.height - (clientY == null ? anchor.cy : clientY);
}
// Zooms to a scale around a screen point (default: the PDF area's centre). A zoom keeps its own anchor: no arrival
// pulls it back.
function zoomTo(scale: number, clientX?: number, clientY?: number) {
  arrivalLetGo();
  const anchor = zoomAnchor(clientX, clientY);
  setScale(scale);
  markZoomed();
  zoomRestore(anchor);
}
// Zooms by a number of ZOOM_STEPs (negative: out).
function zoom(steps: number) {
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
for (const eventType of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'gesturestart'])
  addEventListener(eventType, arrivalLetGo, { capture: true, passive: true }); // gesturestart: Safari's trackpad pinch
addEventListener('resize', arrivalLetGo);
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
$('#jump').addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !imeKey(event)) goPage();
});
// The navigation sheet's page field (Enter or [이동]): goes to the clamped page and closes the sheet; nothing typed
// does nothing.
function goSheetPage() {
  const page = clampPage($('#ns-page-in').value, META && META.pages ? META.pages.length : 0);
  if (page === null) return;
  $('#nav-sheet').close();
  if (document.body.classList.contains('revision-open')) pageChanges().setMode(VIEW_MODE.MANUSCRIPT);
  goPage(page);
}
$('#ns-page-in').addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key === 'Enter' && !imeKey(event)) {
    event.preventDefault();
    goSheetPage();
  }
});

export {
  POINT_PX,
  ZOOM_STEP,
  actualSize,
  autoFitWidth,
  boundScale,
  buildDoc,
  drawZoom,
  fitScale,
  fitToWidth,
  pdfAreaInnerWidth,
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
