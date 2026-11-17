// ------------------------------------------------ Layout bands (docs/handbook/viewer.md §모바일 레이아웃)
// The window's width, height and primary pointer pick a band (layoutFor), and the band a layout mode (BAND_MODE): wide
// - a right sidebar (width-adjustable); mid - the panel between the nav bar and the action row (an overlay up to 900px,
// else beside the document; the short band of a landscape phone folds both rows into one top row); narrow - a bottom
// sheet, collapsed by default. If the band changes partway through a collapse/expand or a rotation, the page width is
// re-fit while preserving the viewed position (topAnchor). Marks and the selection box are % coordinates within the
// page, so they fall back into place automatically once the page width is fit.
import {
  BAND,
  BAND_IN,
  BAND_MODE,
  IS_MAC,
  LAYOUT,
  META,
  MID_OVERLAY,
  COARSE_POINTER_QUERY,
  REDUCED_MOTION_QUERY,
  PINS,
  REPICK,
  REPLY,
  REVIEW_ALL,
  SELMODE,
  SIDE_OPEN,
  scrollMotion,
  setBand,
  setBandIn,
  setLayout,
  setMidOverlay,
  setOutlineMidOpen,
  setSelmodeState,
  setSideOpen,
  setZoomed,
  COMPOSE,
  EDITOR,
} from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { prefs, savePrefs } from '../platform/prefs.ts';
import { lineNote, noticeSeen } from '../platform/notices.ts';
import { hideTip } from '../platform/tooltip.ts';
import {
  SHEET_KEPT,
  SIDE_SHOWN,
  applyOutlineState,
  applySheet,
  applySideWidth,
  renderSizeSegment,
  setSheetKept,
} from './flow-panel-size.ts';
import { syncBackLayer } from './input.ts';
import { NOTICE_DOT, NOTICE_KIND, NOTICE_TOPIC } from '../platform/tables.ts';
import { $, find, typingNow, $$ } from '../platform/dom.ts';
import { BAND_STEP, LAYOUT_BAND, LAYOUT_MODE } from '../app/rules-tables.ts';

// What the frame tells the features, and what it asks them. The frame knows no feature, so these are seams: js/main.ts
// registers them before boot() runs (no code that runs while the script loads lays out the page), and the frame calls
// each at the point, with the arguments and in the order it called the feature code directly. A call before the
// registration throws, naming the seam.
// The steps of a relayout a feature acts on, in the order relayout() takes them. Several features hear of a relayout,
// so this is a list: at each step every listener that has the step is called, in the order they were registered.
interface RelayoutListener {
  /** applyLayout() changed the layout, and a document is open. */
  layoutChanged?(): void;
  /** The panel's and the outline's widths are applied. */
  widthsApplied?(): void;
  /** The reading area is back at its anchor. */
  anchorRestored?(): void;
  /** The tooltip is down, and the composer holds a selection. */
  selectionHeld?(): void;
  /** The top bar is stuck to its place. */
  barStuck?(): void;
  /** The field with the focus is kept in view; the last step. */
  fieldKeptInView?(): void;
}
const RELAYOUT_LISTENERS: RelayoutListener[] = [];
// Adds a listener to the steps of a relayout; js/main.ts calls it, in the order the steps' feature calls ran.
function onRelayout(listener: RelayoutListener) {
  RELAYOUT_LISTENERS.push(listener);
}
// The registered listeners; throws before onRelayout() has run.
function relayoutListeners(): RelayoutListener[] {
  if (!RELAYOUT_LISTENERS.length) throw new Error('onRelayout() has not run: no feature hears of a relayout');
  return RELAYOUT_LISTENERS;
}
// The parts of the frame features draw or know: the status line's place and the build error chip (documents), the
// changes view's guide and commit list (revisions), the pin counts and the bar's words (pins), the reading line's stick
// (verdict), the zoom in [더보기] and the search (pdf), the address's #doc= (documents).
interface FrameHost {
  /** Puts the status line in its place for the band. */
  placeStatus(): void;
  /** Draws the changes view's pin guide and commit list again, those it shows. */
  drawChangesView(): void;
  /** Draws the pin and review counts on the panel's toggles. */
  updateReviewCount(): void;
  /** Shows or hides the build error chip. */
  syncBuildErrorChip(): void;
  /** Sticks the page verdict line again soon. */
  stickSoon(): void;
  /** Draws the zoom percent in [더보기]. */
  drawZoom(): void;
  /** Fits the bar's words to its room. */
  fitBarWords(): void;
  /** Whether the search is open. */
  searchOpen(): boolean;
  /** Puts #doc=<doc> in the address. */
  setHash(doc: string): void;
}
let FRAME_HOST: FrameHost | null = null;
// Registers the frame's host; js/main.ts calls it once.
function setFrameHost(host: FrameHost) {
  FRAME_HOST = host;
}
// The registered host; throws before setFrameHost() has run.
function frameHost(): FrameHost {
  if (!FRAME_HOST) throw new Error('setFrameHost() has not run: the frame has no features to ask');
  return FRAME_HOST;
}
// The band for a width x height CSS px window whose primary pointer is coarse (touch) or not. Pure. A mouse reads the
// width only: phone up to 700px, the overlay panel up to 900px, the side panel up to 1099px, wide from 1100px. Touch
// reads the height and the orientation too, first match wins: under 600px wide a phone at any height; under 480px high
// the short band (a landscape phone); up to 839px, or up to 900px in portrait (height > width; a square window is
// landscape), the tablet sheet; up to 900px the overlay panel (an unfolded foldable); up to 1366px the side panel;
// wider, the desktop.
function layoutFor(width: number, height: number, coarse: boolean) {
  if (!coarse) {
    if (width <= 700) return LAYOUT_BAND.PHONE;
    if (width <= 900) return LAYOUT_BAND.MID_OVERLAY;
    if (width <= 1099) return LAYOUT_BAND.MID_SIDE;
    return LAYOUT_BAND.WIDE;
  }
  if (width < 600) return LAYOUT_BAND.PHONE;
  if (height < 480) return LAYOUT_BAND.SHORT;
  if (width <= 839 || (width <= 900 && height > width)) return LAYOUT_BAND.TABLET_SHEET;
  if (width <= 900) return LAYOUT_BAND.MID_OVERLAY;
  if (width <= 1366) return LAYOUT_BAND.MID_SIDE;
  return LAYOUT_BAND.WIDE;
}
// What layoutFor reads from the window now: {w, h, coarse}.
function bandInput() {
  return { w: innerWidth, h: innerHeight, coarse: COARSE_POINTER_QUERY.matches };
}
type BandInput = ReturnType<typeof bandInput>;
// Keeping the band steady on touch (docs/handbook/viewer.md §모바일 레이아웃): a height change under BAND_HOLD_PX from
// the settled one is the address bar, and a new size or pointer must stay BAND_SETTLE_MS before the band follows it.
// The values are chosen by emulation; a real device may move them.
const BAND_HOLD_PX = 96,
  BAND_SETTLE_MS = 200;
// What a new observation does to the settled input ({w,h,coarse}, null before the first): settle at once with no
// settled input yet or for a mouse (both fine pointers); keep the band while a text field has focus (typing - the
// keyboard shrinks the layout) or when only the height moved less than BAND_HOLD_PX from the settled input (which
// stays, so slow steps add up); otherwise wait for the observation to hold. Pure.
function settleBand(settled: BandInput | null, observed: BandInput, typing: boolean) {
  if (!settled || (!settled.coarse && !observed.coarse)) return BAND_STEP.SETTLE;
  if (typing) return BAND_STEP.KEEP;
  if (observed.w === settled.w && observed.coarse === settled.coarse && Math.abs(observed.h - settled.h) < BAND_HOLD_PX)
    return BAND_STEP.KEEP;
  return BAND_STEP.WAIT;
}
// Picks the band for the settled input (BAND_IN; the window's at the first call) and its panel state: the body classes
// (lay-*, band-*, mid-overlay, compact), then wide follows the per-device pinPrefs.sideClosed (open by default), mid
// its midClosed (else open beside the document, collapsed as an overlay), narrow starts collapsed - except between the
// phone and the tablet sheet, both sheets, which keep it as it was. An open draft keeps it open. The tool bar's markup
// takes the band's order (placeBarTools) and the status line the band's place (placeStatus); the phone's navigation
// sheet closes when the band is no longer the phone (the nav bar does its job there); an open [더보기] stays open and
// redraws its sheet-height or panel-width row; the changes view's guide-line buttons move to the thumb row or back
// (drawPinGuideActions). Returns whether the band or its overlay changed.
function applyLayout() {
  const input = BAND_IN || setBandIn(bandInput()),
    band = layoutFor(input.w, input.h, input.coarse),
    mode = BAND_MODE[band],
    overlay = mode === LAYOUT_MODE.MID && input.w <= 900;
  if (band === BAND && overlay === MID_OVERLAY) return false;
  const sheetToSheet = mode === LAYOUT_MODE.NARROW && LAYOUT === LAYOUT_MODE.NARROW,
    wasOpen = SIDE_OPEN;
  setBand(band);
  setLayout(mode);
  setMidOverlay(overlay);
  setOutlineMidOpen(false);
  const body = document.body,
    preferences = prefs();
  setZoomed(false);
  endSideSlide();
  Object.values(LAYOUT_MODE).forEach((eachMode) => body.classList.toggle('lay-' + eachMode, eachMode === mode));
  Object.values(LAYOUT_BAND).forEach((eachBand) => body.classList.toggle('band-' + eachBand, eachBand === band));
  body.classList.toggle('mid-overlay', overlay);
  body.classList.toggle('compact', mode !== LAYOUT_MODE.WIDE);
  setSideOpen(
    mode === LAYOUT_MODE.WIDE
      ? preferences.sideClosed !== true
      : mode === LAYOUT_MODE.MID
        ? typeof preferences.midClosed === 'boolean'
          ? !preferences.midClosed
          : !overlay
        : sheetToSheet && wasOpen,
  );
  // An in-progress note, edit or reply is never left hidden in a collapsed panel.
  if (!REPICK && (COMPOSE.current || EDITOR.current || REPLY || !$('#composer').hidden)) setSideOpen(true);
  if (band !== LAYOUT_BAND.PHONE && $('#nav-sheet').open) $('#nav-sheet').close();
  const keep = placeBarTools();
  applySide();
  stickTop();
  frameHost().placeStatus();
  if ($('#more').open) {
    renderSizeSegment();
    placeMore();
  }
  frameHost().drawChangesView();
  // From the sheet straight to wide the bar shows only once applySide has drawn the panel: the focus goes back now.
  if (keep && document.activeElement !== keep) keep.focus({ preventScroll: true });
  return true;
}
// Puts the tool bar's markup (#bar1) in the order the band draws it, so Tab crosses the bar from left to right. The
// markup is the sheet's, whose grid draws it as it stands: [핀 N | 검토 M] [⬚] (.bar-l), the grabber, [본문 ▾] [⋯]
// (.bar-r), then the wide row's tools. The wide row ends on [⋯] (CSS order), so .bar-r goes last; the mid and short
// rows read [⬚] ··· [⋯] [핀 N | 검토 M] (CSS order, for the thumbs), so [⬚] also leaves its group for the bar's start
// and the chip's two halves, still one group, follow [⋯]. A control that has the focus keeps it; a focus that cannot go
// back yet (its bar not shown before applySide) is returned, and applyLayout tries again.
function placeBarTools() {
  const bar = $('#bar1'),
    leftGroup = bar.querySelector('.bar-l') as HTMLElement,
    rightGroup = bar.querySelector('.bar-r') as HTMLElement;
  const selectButton = $('#btn-select'),
    focused = document.activeElement as HTMLElement | null,
    had = !!focused && bar.contains(focused);
  if (LAYOUT === LAYOUT_MODE.MID) {
    if (bar.firstElementChild !== selectButton) bar.prepend(selectButton);
    if (bar.lastElementChild !== leftGroup || leftGroup.previousElementSibling !== rightGroup)
      bar.append(rightGroup, leftGroup);
  } else {
    if (leftGroup.lastElementChild !== selectButton) leftGroup.append(selectButton);
    if (bar.firstElementChild !== leftGroup) bar.prepend(leftGroup);
    if (LAYOUT === LAYOUT_MODE.WIDE) {
      if (bar.lastElementChild !== rightGroup) bar.append(rightGroup);
    } else if (leftGroup.nextElementSibling !== $('#sheet-grip') || $('#sheet-grip').nextElementSibling !== rightGroup)
      $('#sheet-grip').after(rightGroup);
  }
  if (had && focused && document.activeElement !== focused) focused.focus({ preventScroll: true });
  return had && focused && document.activeElement !== focused ? focused : null;
}
// Whether the outline is an overlay over the document that opens one at a time with the pin panel (OUTLINE_MID_OPEN,
// never saved): in the mid bands and on the tablet sheet. The phone has no outline; wide keeps it beside the
// document.
function outlineOverlay() {
  return LAYOUT === LAYOUT_MODE.MID || BAND === LAYOUT_BAND.TABLET_SHEET;
}
// A draft the panel is holding: the composer (a selection being noted), an open edit or reply, or a relocation.
// Collapsing by a drag stops short of it, a swipe only rubber-bands, and a collapsed [핀 N] shows a dot for it.
function draftOpen() {
  return !$('#composer').hidden || !!EDITOR.current || !!REPLY || !!REPICK;
}
// Draws the panel state (docs/handbook/viewer.md §패널 폭과 시트 높이): the body classes (with the phone sheet's
// composing lift, the phone only), both [핀 N] toggles - the tool bar's and, for a collapsed wide panel, the nav bar's
// - with the open count and the draft dot, the handle's ARIA and the back-gesture layer. Their name says what they
// show: the nav bar's icon and pill '패널 펴기 · 열린 핀 11 · 검토 대기 1', every compact bar's chip half '핀 11 · 패널
// 펴기' (+ ' · 작성 중' for a draft). No arrow: the open state is the panel itself and aria-expanded. Also the build
// error chip, which shows while the panel holding the error is collapsed (syncBuildErrChip). Idempotent and cheap:
// drawPins() calls it on every redraw. The panel keeps its open layout while it slides out.
function applySide() {
  const open = SIDE_OPEN,
    body = document.body,
    dot = !open && draftOpen(),
    pinCount = PINS.length,
    reviewCount = REVIEW_ALL.length,
    composing = !$('#composer').hidden;
  body.classList.toggle('side-open', open || !!(SIDE_SLIDE && SIDE_SLIDE.kind === 'closing'));
  body.classList.toggle('composing', composing);
  if (!composing) setSheetKept(false);
  // The phone sheet's composing lift; the tablet sheet's is tabletLift (layout/flow-panel-size.ts).
  body.classList.toggle('sheet-up', composing && !SHEET_KEPT && BAND === LAYOUT_BAND.PHONE);
  // The toggles' names: the review count only where its pill sits inside them (the wide nav bar); every compact bar's
  // [핀 N] names what it shows first and leaves the count to its own half [검토 M].
  const label =
      translate(open ? '패널 접기' : '패널 펴기') +
      ' · ' +
      translateTemplate('열린 핀 {n}', { n: pinCount }) +
      (reviewCount ? ' · ' + translateTemplate('검토 대기 {n}', { n: reviewCount }) : '') +
      (dot ? ' · ' + translate('작성 중') : ''),
    sheet =
      translateTemplate('핀 {n}', { n: pinCount }) +
      ' · ' +
      translate(open ? '패널 접기' : '패널 펴기') +
      (dot ? ' · ' + translate('작성 중') : '');
  for (const toggle of [$('#btn-side'), $('#nav-side')]) {
    toggle.setAttribute('aria-expanded', String(open));
    toggle.setAttribute('aria-label', toggle.id === 'btn-side' && LAYOUT !== LAYOUT_MODE.WIDE ? sheet : label);
    toggle.querySelector('.side-n').textContent = pinCount;
    toggle.querySelector('.c-dot').hidden = !dot;
  }
  $('#nav-side').hidden = !(LAYOUT === LAYOUT_MODE.WIDE && !open);
  gripAria();
  frameHost().updateReviewCount();
  syncBackLayer();
  frameHost().syncBuildErrorChip();
}
// The open handle's hint (the markup's, translated by translate()).
const GRIP_TIP = $('#grip').dataset.tip;
// The handle's ARIA as a window splitter: the panel width, or 0 (named '패널 폭 · 접힘') while collapsed - a collapsed
// wide panel's handle is the rail at the right edge, and its hint says how to bring the panel back.
function gripAria() {
  const grip = $('#grip'),
    shown = SIDE_SHOWN;
  if (!SIDE_OPEN) {
    grip.setAttribute('aria-valuenow', '0');
    grip.setAttribute('aria-valuemin', '0');
    grip.setAttribute('aria-label', translate('패널 폭') + ' · ' + translate('접힘'));
    grip.dataset.tip = translate(
      '끌어서 핀 패널을 폅니다. 두 번 클릭(터치는 탭)하거나 Enter 를 누르면 전에 쓰던 폭으로 폅니다',
    );
    return;
  }
  grip.setAttribute('aria-label', translate('패널 폭'));
  grip.dataset.tip = translate(GRIP_TIP);
  if (shown) {
    grip.setAttribute('aria-valuenow', shown.w);
    grip.setAttribute('aria-valuemin', shown.min);
    grip.setAttribute('aria-valuemax', shown.max);
  }
}
// Opens or collapses the pin panel in every layout (the wide side panel, the mid side or overlay panel, the narrow
// sheet). remember = the user did it (a toggle, Ctrl+\, a handle drag or key, a swipe): wide keeps it per device in
// pinPrefs.sideClosed, mid in midClosed; narrow always starts collapsed. slide = move with the 0.18s slide where the
// layout has one (wide, and the 701-900px overlay, whose opening slide is CSS's own); things that merely need the panel
// (a pick, a link) open it at once. Opening the mid panel or the tablet sheet closes the outline overlay (one at a
// time). Collapsing never touches the saved width - once collapsed, the panel's width is put back to it for the next
// opening. Opening counts as seeing the list (noticeSeen).
function setSide(open: boolean, remember?: boolean, slide?: boolean) {
  open = !!open;
  // The panel is on screen: [핀 N]'s dot and the hint on how to open it go.
  if (open) noticeSeen(NOTICE_DOT.SIDE);
  if (open && outlineOverlay()) {
    setOutlineMidOpen(false);
    applyOutlineState();
  }
  if (remember && LAYOUT === LAYOUT_MODE.MID) savePrefs({ midClosed: !open });
  if (remember && LAYOUT === LAYOUT_MODE.WIDE) savePrefs({ sideClosed: !open });
  if (SIDE_OPEN === open) return;
  setSideOpen(open);
  const cut = !!SIDE_SLIDE && SIDE_SLIDE.kind === 'closing';
  endSideSlide();
  // Never reopen an overlay still offset by a swipe.
  if (open) document.documentElement.style.setProperty('--swipe-x', '0px');
  const ms = slideMs();
  if (ms && slide) startSideSlide(open ? 'opening' : 'closing', ms);
  applySide();
  hideTip();
  // A collapse without a slide gets the saved width back now, and so does a panel reopened mid-slide (back from a
  // drag's minimum).
  if ((!open && !SIDE_SLIDE) || (open && cut)) applySideWidth();
}
// The panel's slide (0.18s; none with reduced motion, and none beside the document at 901-1099px, where the page
// re-fits instead). While it slides out the body keeps side-open, so the layout does not jump until it is gone.
const SLIDE_MS = 180;
let SIDE_SLIDE = null as { kind: string; t: ReturnType<typeof setTimeout> } | null;
// The slide's length for this layout in ms: 0 with reduced motion, beside the document (901-1099px) and for the narrow
// sheet.
function slideMs() {
  return REDUCED_MOTION_QUERY.matches || !(LAYOUT === LAYOUT_MODE.WIDE || MID_OVERLAY) ? 0 : SLIDE_MS;
}
// Starts the 'opening'/'closing' slide; when it ends the panel settles (a collapsed one gets its saved width back).
function startSideSlide(kind: string, ms: number) {
  document.body.classList.add('side-' + kind);
  SIDE_SLIDE = { kind, t: setTimeout(finishSideSlide, ms) };
}
// Ends a running slide now and settles the panel as the slide's end would (a collapsed one gets its saved width back) -
// a handle pressed mid-slide starts from the settled state, not from a half-slid one.
function finishSideSlide() {
  if (!SIDE_SLIDE) return;
  endSideSlide();
  applySide();
  if (!SIDE_OPEN) applySideWidth();
}
// Stops a running slide at once without settling anything - the caller re-applies the panel (setSide, applyLayout); a
// handle drag uses finishSideSlide() instead.
function endSideSlide() {
  if (!SIDE_SLIDE) return;
  clearTimeout(SIDE_SLIDE.t);
  SIDE_SLIDE = null;
  document.body.classList.remove('side-closing', 'side-opening');
}
// After a collapse, a focus left inside the hidden panel (or on the mid handle, which hides with it) moves to the [핀
// N] that reopens it. Compact keeps its tool bar and status chips visible, so a focus there stays.
function focusSideToggle() {
  const focused = document.activeElement;
  if (SIDE_OPEN || !focused) return;
  const hidden =
    (focused === $('#grip') && LAYOUT !== LAYOUT_MODE.WIDE) ||
    ($('#right').contains(focused) &&
      !$('#bar2').contains(focused) &&
      !(LAYOUT !== LAYOUT_MODE.WIDE && $('#bar1').contains(focused)));
  if (hidden) (LAYOUT === LAYOUT_MODE.WIDE ? $('#nav-side') : $('#btn-side')).focus({ preventScroll: true });
}
// [핀 N], Ctrl/⌘+\ and the handle's Enter: collapse with the slide, or open. Collapsing moves a focus out of the hidden
// panel; opening from the nav bar's [핀 N] (which hides as the panel opens) moves the focus to the handle beside the
// panel.
function toggleSide() {
  const open = !SIDE_OPEN,
    focused = document.activeElement;
  setSide(open, true, true);
  if (!open) focusSideToggle();
  else if (focused === $('#nav-side')) $('#grip').focus({ preventScroll: true });
}
// The first drag-collapse on a wide screen says once how to bring the panel back (it leaves only a 6px rail behind).
function coachSideCollapsed() {
  if (LAYOUT === LAYOUT_MODE.WIDE && !SIDE_OPEN)
    coach('side', '핀 패널은 오른쪽 위 [핀 N] 또는 Ctrl+\\ 로 다시 엽니다');
}
// Re-fits everything to the window: the layout (a changed one redraws the cards, whose action row is ordered per
// layout), the panel and outline widths, the page width at the same reading spot (a Markdown column, reflowed by the
// browser, at its own: keepReadingSpot), the composer, the stuck heads and the section strip - and keeps a panel text
// field that has focus in view (the keyboard or the short band's hidden top row moves it).
function relayout() {
  const listeners = relayoutListeners();
  const anchor = topAnchor(),
    changed = applyLayout();
  if (changed && META) for (const listener of listeners) listener.layoutChanged?.();
  applySideWidth();
  applyOutlineState();
  for (const listener of listeners) listener.widthsApplied?.();
  restoreAnchor(anchor);
  for (const listener of listeners) listener.anchorRestored?.();
  hideTip();
  if (COMPOSE.current) for (const listener of listeners) listener.selectionHeld?.();
  stickTop();
  for (const listener of listeners) listener.barStuck?.();
  keepFieldInView();
  for (const listener of listeners) listener.fieldKeptInView?.();
}
// The height a list section header (sticky) sticks below. In compact, #right is the scroll box and the tool bar (#bar1,
// which holds the sheet handle in narrow) is already stuck above it, so the header sticks below that. In wide, #list
// itself is the scroll box, so this is 0.
function stickTop() {
  let offset = 0;
  const bar = $('#bar1');
  if (LAYOUT !== LAYOUT_MODE.WIDE && bar) {
    const barStyle = getComputedStyle(bar);
    if (barStyle.position === 'sticky') offset = Math.round((parseFloat(barStyle.top) || 0) + bar.offsetHeight);
  }
  document.documentElement.style.setProperty('--stick-top', offset + 'px');
}
// The tool bar's width (--bar1-w): the short band draws the tool bar over the right end of its one top row, and the nav
// bar's links end where it begins - exactly there, unrounded: a width rounded up ends the nav bar up to a pixel short,
// and the PDF shows through.
function barWidth() {
  document.documentElement.style.setProperty('--bar1-w', $('#bar1').getBoundingClientRect().width + 'px');
}
// The bar's border box: padding-only changes (the collapsed sheet) count.
if (window.ResizeObserver)
  new ResizeObserver(() => {
    stickTop();
    barWidth();
  }).observe($('#bar1'), { box: 'border-box' });
// The composer's location line height (--loc-h): on a touch sheet the line sticks under the tool bar while a composer
// text field has focus, and the scroller's scroll padding keeps a field scrolled into view below it (responsive.css). A
// long file name wraps the line past its 44px, so it is measured; 0 while the composer is hidden.
if (window.ResizeObserver) {
  const row = find(document, '#composer .c-loc-row', HTMLElement);
  new ResizeObserver(() => {
    document.documentElement.style.setProperty('--loc-h', row.offsetHeight + 'px');
  }).observe(row, { box: 'border-box' });
}
let RELAYOUT_FRAME = 0,
  BAND_TIMER = 0;
// Re-fits on the next frame after a resize, a pointer change or a panel/keyboard change - unless the band input is
// waiting to settle (bandSettle), in which case the band and the page width stay as they are until it does.
function scheduleRelayout() {
  if (RELAYOUT_FRAME) return;
  RELAYOUT_FRAME = requestAnimationFrame(() => {
    RELAYOUT_FRAME = 0;
    if (bandSettle()) refit();
  });
}
// The re-fit itself: relayout once the document is open, else only the layout.
function refit() {
  if (META) relayout();
  else applyLayout();
}
// Applies settleBand to the window now. Settle: BAND_IN takes the new input. Keep: BAND_IN stays (a pending wait is
// dropped - the window came back). Wait: (re)starts BAND_SETTLE_MS; when it runs out with no text field focused,
// BAND_IN takes the window's input, the page re-fits once and the page lines follow (shouldStandBeside holds them
// meanwhile). Returns whether the caller may re-fit now.
function bandSettle() {
  const observed = bandInput(),
    step = settleBand(BAND_IN, observed, typingNow());
  clearTimeout(BAND_TIMER);
  BAND_TIMER = 0;
  if (step === BAND_STEP.WAIT) {
    BAND_TIMER = setTimeout(() => {
      BAND_TIMER = 0;
      frameHost().stickSoon();
      if (typingNow()) return;
      setBandIn(bandInput());
      refit();
    }, BAND_SETTLE_MS);
    return false;
  }
  if (step === BAND_STEP.SETTLE) setBandIn(observed);
  return true;
}
// Whether the window differs from the settled band input (a band change may be due).
function bandStale() {
  const input = bandInput();
  return !!BAND_IN && (input.w !== BAND_IN.w || input.h !== BAND_IN.h || input.coarse !== BAND_IN.coarse);
}
window.addEventListener('resize', scheduleRelayout);
COARSE_POINTER_QUERY.addEventListener('change', scheduleRelayout);
// Even a mere #left width change from expanding/collapsing the panel (compact) re-fits the page width. The layout is
// never changed directly in the callback - it is deferred to the next frame (avoids a ResizeObserver loop warning).
// wide reacts only to window-size changes. Never re-fit while the handle is being dragged (body.resizing) -
// setSideWidth fits it once on release.
if (window.ResizeObserver)
  new ResizeObserver(() => {
    if (LAYOUT && LAYOUT !== LAYOUT_MODE.WIDE && !document.body.classList.contains('resizing')) scheduleRelayout();
  }).observe($('#left'));

// Virtual keyboard: on Chrome Android, the layout itself shrinks via the viewport meta's
// interactive-widget=resizes-content. A browser that does not understand that value instead measures the keyboard
// height (--kb) via visualViewport and raises the whole screen by that amount. A visualViewport shrunk by pinch zoom is
// not the keyboard (undone by multiplying by scale). If an input field has focus, it is scrolled into view.
function onViewport() {
  const viewport = window.visualViewport;
  if (!viewport) return;
  const layoutHeight = document.documentElement.clientHeight;
  let keyboardHeight = Math.round(layoutHeight - viewport.height * viewport.scale);
  if (!(keyboardHeight >= 80) || !COARSE_POINTER_QUERY.matches) keyboardHeight = 0;
  const rootStyle = document.documentElement.style,
    previousKeyboard = rootStyle.getPropertyValue('--kb');
  rootStyle.setProperty('--kb', keyboardHeight + 'px');
  rootStyle.setProperty('--vvh', layoutHeight - keyboardHeight + 'px');
  const focused = document.activeElement;
  if (
    previousKeyboard !== keyboardHeight + 'px' &&
    focused &&
    (focused.tagName === 'TEXTAREA' || focused.tagName === 'INPUT') &&
    $('#right').contains(focused)
  )
    requestAnimationFrame(() => focused.scrollIntoView({ block: 'center' }));
}
{
  const viewport = window.visualViewport;
  if (viewport) {
    viewport.addEventListener('resize', onViewport);
    viewport.addEventListener('scroll', onViewport);
  }
}
document.addEventListener('focusin', (event) => {
  const target = event.target as HTMLElement;
  if (LAYOUT !== LAYOUT_MODE.WIDE && target && target.tagName === 'TEXTAREA' && $('#right').contains(target))
    setTimeout(() => {
      if (BAND === LAYOUT_BAND.TABLET_SHEET) keepFieldInView();
      else {
        target.scrollIntoView({ block: 'center' });
        if (target === $('#note')) noteRowInView();
      }
    }, 350);
});
// The first key of a field puts the caret back where it already stands, which takes the document's selection in with
// it. Leaving a field is a press on static text (the range caption: the composer's leave), which puts the document's
// selection in that text; a tap back into the field moves the focus but leaves the selection there, and until
// something moves it the browser turns no key into an edit - the keys reach the field, no beforeinput follows and
// nothing is inserted. On macOS Chromium at the tablet sheet only the sheet's keepFieldInView above, 350ms later, would
// end that, and a note typed right after the tap would lose everything up to then; a mouse press takes the selection
// into the field with the focus. It is done on the key and not on the focus because a tap's own caret lands after
// focusin - and once per turn in the field, before that key is handled, so the key itself lands.
// The field whose caret has been put since it took the focus.
let CARET_HELD = null as EventTarget | null;
function holdCaret(event: KeyboardEvent) {
  const field = event.target as HTMLInputElement;
  if (!field || field === CARET_HELD || typeof field.setSelectionRange !== 'function') return;
  CARET_HELD = field;
  const at = field.selectionStart;
  // A selection is the person's.
  if (at == null || at !== field.selectionEnd) return;
  // A field whose kind has no caret (email, number) refuses it.
  try {
    field.setSelectionRange(at, at);
  } catch (error) {}
}
document.addEventListener(
  'focusin',
  () => {
    CARET_HELD = null;
  },
  true,
);
document.addEventListener('keydown', holdCaret, true);
// A field's scroll keys are the field's, not the pages' (docs/handbook/viewer.md §키와 초점). A key that the host does
// not give a field goes to the scroller outside it instead: in the reason field the pane would scroll, the reading page
// change, the panel redraw for it and the open field go, with what was being written in it. Which keys those are is
// the host's answer, and it differs. PageUp and PageDown are no field's keys anywhere: they move the pane on every
// host, from the panel's note too. Home and End are the field's on Linux and Windows, where they move the caret, and
// are not on macOS, where the pane scrolls instead. So the page keys are dropped on every host and Home and End only on
// macOS, where dropping them costs no caret move. Only the default is dropped, so the caret stays where it stands, as
// it does in every other application on that host.
// A key pressed while a syllable is composing is dropped too. The browser marks it composing (isComposing, keyCode
// 229) and still scrolls with it: Home in the reason field with '나' composing would take the pane to its top, the
// field gone, and PageUp and PageDown move it on Linux as well. The composition is the input method's and is not
// touched - no text, no commit, no caret: dropping the default leaves it open, and the syllable committed after it and
// the next one land in place ('가나다'). A key the input method took itself comes as 'Process' and is none of these.
// A field that is read-only for a while - the reason field while its save is out, the suggestion's editor until the
// range's text is read - takes no caret key at all, so in Chromium the arrows, Space and Home and End on every host go
// to the scroller outside it as well: the arrows move the pane (sideways when the PDF is zoomed wider than the area),
// Space and Shift+Space a page, Home and End to its ends with the field gone, and in the tablet sheet the panel slides
// under it. There those keys and Space are dropped on every host, Shift+Space with them; Firefox moves only the caret,
// which the read-only field keeps as well. Three cases are left alone: a modifier makes them the field's again
// (Shift+Home selects to the line's start, Meta+Arrow is the host's own caret key; in a read-only field Shift with a
// moving key moves nothing outside - Firefox extends the selection, Chromium keeps it - and Ctrl, Alt or Meta make a
// host's own chord); a field with more than it shows that can still scroll the key's way scrolls itself, which is the
// field's own doing; and anything outside a field, where these keys move the pages.
// That field is left the key only while it has room that way. At its end Chromium hands the key on to the scroller
// outside: PageDown, a read-only ArrowDown, Space and End move the pane down (a page on, the field gone), and at its
// top PageUp, Shift+Space and Home move it up the same way; sideways keys in a read-only field move a zoomed pane at
// any height, as the field has no width to scroll. With room the field scrolls and the pane stays. A writable field's
// PageUp and PageDown are no field's keys even then: Chromium moves the caret a page and lines it up with each
// scroller's top, so they move the pane from anywhere in the field, beside the pages or under them. Firefox moves
// nothing outside in any of these.
// A read-only field's PageUp and PageDown with room are scrolled here, a page of the field. Chrome from 157 moves the
// caret there as in a writable field - five lines a page - and lines it up with the scrollers outside as well, so the
// pane would move from the middle of the field on either key. So their default is dropped there too, and the field
// scrolls by Chromium's own page step (7/8 of what it shows), the caret where it stands.
// pdf/view-outline.ts's SCROLL_KEYS also holds the arrows and Space, which stay a field's keys on every host.
const PAGE_KEYS = new Set(['PageUp', 'PageDown']);
// Chromium's page scroll: 7/8 of what the scroller shows, in whole pixels.
const PAGE_STEP = 0.875;
// A read-only field's scroll keys: none moves a caret there.
const READ_ONLY_KEYS = new Set([
  'ArrowUp',
  'ArrowDown',
  'ArrowLeft',
  'ArrowRight',
  'Home',
  'End',
  'PageUp',
  'PageDown',
  ' ',
]);
// The keys that scroll a field up; Shift+Space too, and the rest of READ_ONLY_KEYS down or sideways.
const FIELD_UP_KEYS = new Set(['ArrowUp', 'PageUp', 'Home']);
// Whether a field can still scroll the way a key (with Shift: shift) scrolls it, short of that end.
function fieldRoom(field: HTMLElement, key: string, shift: boolean) {
  if (key === 'ArrowLeft') return field.scrollLeft > 0;
  if (key === 'ArrowRight') return field.scrollLeft + field.clientWidth < field.scrollWidth - 1;
  return FIELD_UP_KEYS.has(key) || (key === ' ' && shift)
    ? field.scrollTop > 0
    : field.scrollTop + field.clientHeight < field.scrollHeight - 1;
}
// The keydown rule above, for the text field that has focus: drops the key's default where it would move a scroller
// outside the field, and scrolls a read-only field's page itself.
function fieldScrollKey(event: KeyboardEvent) {
  const key = event.key;
  if (!READ_ONLY_KEYS.has(key) || event.metaKey || event.ctrlKey || event.altKey || !typingNow()) return;
  const field = document.activeElement as HTMLInputElement,
    isReadOnly = field.readOnly === true;
  if (isReadOnly) {
    // Shift with a moving key moves nothing outside (Firefox selects, Chromium keeps the selection).
    if (event.shiftKey && key !== ' ') return;
  } else if (event.shiftKey || !(PAGE_KEYS.has(key) || (IS_MAC && (key === 'Home' || key === 'End')))) return;
  if (
    (isReadOnly || !PAGE_KEYS.has(key)) &&
    field.scrollHeight > field.clientHeight &&
    fieldRoom(field, key, event.shiftKey)
  ) {
    if (!isReadOnly || !PAGE_KEYS.has(key)) return;
    // A read-only field's page key scrolls the field's page, not the caret's.
    field.scrollBy({
      top: (key === 'PageUp' ? -1 : 1) * Math.floor(field.clientHeight * PAGE_STEP),
      behavior: scrollMotion(),
    });
  }
  event.preventDefault();
}
document.addEventListener('keydown', fieldScrollKey, true);
// The panel's text field that has focus (a note, an edit or a reply), or null.
function panelField() {
  const focused = document.activeElement;
  return typingNow() && $('#right').contains(focused) ? focused : null;
}
// performance.now() of the last pointerup: a focus change that soon after is that press's.
let TYPING_PRESS = -1e9;
document.addEventListener(
  'pointerup',
  () => {
    TYPING_PRESS = performance.now();
  },
  true,
);
// body.typing while a panel text field has focus: the short band hides its top row then, leaving the keyboard's ~200px
// to the panel; the tablet sheet re-measures its keyboard lift (applySheet, tabletLift). When a press takes the focus
// from the field, the class waits for that press's click (or 350ms): taking the short band's top row back at once
// would move the panel 48px under the finger between the touch's end and its click, and the click would hit what is
// there then - a first tap on an edit card's dimmed line would do nothing.
// Whether syncTyping() is waiting for the press that took the focus (its click or 350ms).
let TYPING_HELD = false;
function syncTyping() {
  const on = !!panelField(),
    body = document.body;
  if (!on && body.classList.contains('typing') && performance.now() - TYPING_PRESS < 300) {
    if (TYPING_HELD) return;
    TYPING_HELD = true;
    const go = () => {
      if (!TYPING_HELD) return;
      TYPING_HELD = false;
      document.removeEventListener('click', go);
      syncTyping();
    };
    document.addEventListener('click', go);
    setTimeout(go, 350);
    return;
  }
  body.classList.toggle('typing', on);
  if (BAND === LAYOUT_BAND.TABLET_SHEET) applySheet();
}
document.addEventListener('focusin', syncTyping);
// After the focus has moved on: the typing class, and a band held while a text field had focus gets its turn
// (settleBand).
document.addEventListener('focusout', () =>
  setTimeout(() => {
    syncTyping();
    if (bandStale()) scheduleRelayout();
  }, 0),
);
// Scrolls a panel text field that has focus back into view after a re-fit; the scroller's scroll-padding keeps it clear
// of the save row and, on a sheet, of the tool bar stuck above - and of the composer's location line, which sticks
// under the tool bar while the note or the suggestion editor has focus (responsive.css), so the line stays above
// either. On the tablet sheet the location line comes to the top first, so the note shows under it.
function keepFieldInView() {
  const field = panelField();
  // Touch only: a mouse window keeps its own scroll.
  if (!field || !COARSE_POINTER_QUERY.matches) return;
  if (field === $('#note') && BAND === LAYOUT_BAND.TABLET_SHEET)
    find(document, '#composer .c-loc-row', HTMLElement).scrollIntoView({ block: 'start' });
  field.scrollIntoView({ block: 'nearest' });
  if (field === $('#note')) noteRowInView();
}
// The composer's verdict row (verdict/flow-line.ts) sits right under the note: with the note focused on a touch screen
// the panel scrolls on until the row clears the save row too - only as far as the field being typed in stays whole
// under what is above it: the location line stuck at the top (a compact sheet or panel), else the panel's own top with
// the location line itself in view. A row that cannot fit beside the note stays where it is.
function noteRowInView() {
  const row = $('#c-verdict-row');
  if (row.hidden || !row.getClientRects().length) return;
  const panel = $('#right'),
    loc = find(document, '#composer .c-loc-row', HTMLElement),
    stuck = getComputedStyle(loc).position === 'sticky';
  const save = $('#c-actions').getBoundingClientRect().top - 8;
  const top = stuck
    ? loc.getBoundingClientRect().bottom + 8
    : panel.getBoundingClientRect().top + (parseFloat(getComputedStyle(panel).scrollPaddingTop) || 0);
  const first = stuck ? $('#note') : loc,
    need = row.getBoundingClientRect().bottom - save,
    room = first.getBoundingClientRect().top - top;
  if (need > 0 && room > 0) panel.scrollTop += Math.min(need, room);
}

// A first-visit hint (docs/handbook/viewer.md §알림 자리): shown once per device and key (pinPrefs.coach remembers it),
// on the status line until [x] or until the person does what it says - picks ('touch', 'mouse') or opens the panel
// ('side').
function coach(key: string, text: string) {
  const seen = Object.assign({}, prefs().coach || {});
  if (seen[key]) return;
  seen[key] = 1;
  savePrefs({ coach: seen });
  lineNote(text, NOTICE_KIND.INFO, null, { topic: key === 'side' ? NOTICE_TOPIC.SIDE : NOTICE_TOPIC.PICK });
}
// The touch select mode (docs/handbook/viewer.md §모바일 레이아웃 선택 모드), on or off. Effects: body.selmode (the
// pages take one-finger drags, the PDF area gets its accent frame and the mode bar), the toggle's aria-pressed and its
// label ('선택' / '선택 중' where the bar shows one), the live region's words (the bar's, said once as it turns on;
// empty when off), and the mode bar's height for the reserve above page 1 (--sel-bar-h). The reserve comes and goes
// with the mode: scrolled to the top, page 1 moves below the bar; anywhere else the pages keep their place
// (selectModeScrollTop). A focus left on the hidden bar's [끝내기] goes to the toggle. Idempotent; no coach mark - the
// bar says what a drag and a tap do.
function setSelectMode(on: boolean) {
  const was = SELMODE,
    pdfArea = $('#left'),
    doc = $('#doc'),
    top0 = pdfArea.scrollTop,
    y0 = doc.getBoundingClientRect().top;
  setSelmodeState(!!on);
  document.body.classList.toggle('selmode', SELMODE);
  const button = $('#btn-select');
  button.setAttribute('aria-pressed', String(SELMODE));
  (button.querySelector('.lbl') as HTMLElement).textContent = translate(SELMODE ? '선택 중' : '선택');
  $('#sel-sr').textContent = SELMODE ? $('#sel-bar-t').textContent : '';
  if (SELMODE) fitSelectModeBar();
  else if ($('#sel-bar').contains(document.activeElement)) button.focus({ preventScroll: true });
  if (was !== SELMODE)
    pdfArea.scrollTop = selectModeScrollTop(top0, pdfArea.scrollTop, doc.getBoundingClientRect().top - y0);
}
// Where the PDF scroller goes (px) when the select mode's reserve above page 1 comes or goes and the pages move by
// moved px (down positive): at the very top (top0, the position before, at 0 or above) it stays at 0, so the reserve
// uncovers page 1's first line rather than the bar covering it; anywhere else the pages keep their place on screen -
// from now (the position after, which a browser's scroll anchoring may already have moved, then moved is 0) by as far
// as they moved, never above the top. Pure.
function selectModeScrollTop(top0: number, now: number, moved: number) {
  return top0 <= 0 ? 0 : Math.max(0, now + moved);
}
// Fits the mode bar to what is around it: its width as --sel-bar-w (selectModeBarWidth, from its natural width and the
// PDF area's) and its drawn height as --sel-bar-h, which the reserve above page 1 adds up (responsive.css). Once as the
// mode turns on (setSelectMode reads the height in the same task) and whenever the bar or the PDF area changes size
// (words wrapping anew, a rotation, the overlay panel). A hidden bar (0 high) leaves the last values.
function fitSelectModeBar() {
  const bar = $('#sel-bar');
  if (!bar.offsetHeight) return;
  bar.style.removeProperty('--sel-bar-w');
  bar.style.setProperty(
    '--sel-bar-w',
    selectModeBarWidth(bar.getBoundingClientRect().width, $('#sel-mode').clientWidth) + 'px',
  );
  document.documentElement.style.setProperty('--sel-bar-h', bar.offsetHeight + 'px');
}
// The mode bar's width (px) for its natural width in a PDF area areaWidth px wide: the next whole pixel up, and one
// more when that leaves the two sides an odd remainder, so the centred bar's edges - and the icon tile and [끝내기] 4px
// inside them - fall on whole pixels. Icons are drawn at whole pixels: a bar centred between pixels draws its icon half
// a pixel off its tile. Pure.
function selectModeBarWidth(naturalWidth: number, areaWidth: number) {
  let width = Math.ceil(naturalWidth - 0.01);
  if ((Math.round(areaWidth) - width) % 2) width++;
  return width;
}
if (window.ResizeObserver) {
  const barObserver = new ResizeObserver(fitSelectModeBar);
  barObserver.observe($('#sel-bar'));
  barObserver.observe($('#sel-mode'));
}
// Opens a dialog (a sheet in compact: [더보기], the navigation sheet, the help, the Trash) as a modal with the focus on
// the dialog itself (tabindex=-1, drawn without a ring), not on its first control: a phone's browser would draw the
// focus ring on [닫기] each time a tap opens one. Tab goes on to [닫기], the first control.
function showSheet(dialog: HTMLDialogElement) {
  dialog.showModal();
  dialog.focus({ preventScroll: true });
}
// Opens [더보기] with its view group drawn for now: the sheet-height or panel-width segment and the zoom figure, and
// its foot on one ink line (footInk); on the wide desktop it is a menu under [⋯] (placeMore), which says it is open
// (aria-expanded).
function openMore() {
  const sheet = $('#more');
  if (sheet.open) return;
  hideTip();
  frameHost().drawZoom();
  renderSizeSegment();
  placeMore();
  showSheet(sheet);
  footInk();
  $('#btn-more').setAttribute('aria-expanded', 'true');
}
$('#more').addEventListener('close', () => $('#btn-more').setAttribute('aria-expanded', 'false'));
// The wide desktop's [더보기] as a menu under [⋯]: its top 4px under the button and its right edge on the button's -
// the --more-top and --more-right that body.lay-wide #more reads (the compact sheets ignore them). Again on a relayout
// while open.
function placeMore() {
  const button = $('#btn-more');
  if (LAYOUT !== LAYOUT_MODE.WIDE || !button.getClientRects().length) return;
  const rect = button.getBoundingClientRect(),
    menu = $('#more');
  menu.style.setProperty('--more-top', rect.bottom + 4 + 'px');
  menu.style.setProperty('--more-right', document.documentElement.clientWidth - rect.right + 'px');
}
// How far the foot's wordmark and version drop so their ink bottoms meet [도움말]'s: from the label's Hangul ink
// descent below the shared baseline and the version's (px, positive = below). The wordmark has none ("limn" ends on the
// baseline); a label without Hangul ('Help', whose 'p' hangs below by design) counts as none. Pure.
function inkDrops(labelDescent: number, versionDescent: number) {
  return { word: labelDescent, ver: labelDescent - versionDescent };
}
// [더보기]'s foot on one ink line (docs/handbook/viewer.md §모바일 레이아웃): Hangul reaches below the Latin baseline
// the row shares, so on one baseline [도움말] reads lower than "limn" and the version. From the fonts in use - canvas
// metrics of the very strings, read at 64 times the size because the canvas rounds them to whole pixels - the wordmark
// and the version drop until their ink bottoms meet the label's Hangul (inkDrops), and the chevron moves to the centre
// of the label's ink.
function footInk() {
  const foot = $('#more-foot'),
    help = foot && foot.querySelector('[data-act=help]'),
    version = foot && foot.querySelector('.m-ver');
  if (!help || !version) return;
  const labelText = [...help.childNodes].find((node) => node.nodeType === 3 && node.nodeValue.trim()),
    chevron = help.querySelector('svg');
  if (!labelText) return;
  const label = labelText.nodeValue.trim(),
    hangul = hangulOf(label),
    labelInk = inkMetrics(help, label);
  const drops = inkDrops(hangul ? inkMetrics(help, hangul).d : 0, inkMetrics(version, version.textContent.trim()).d);
  foot.style.setProperty('--ink-word', drops.word + 'px');
  foot.style.setProperty('--ink-ver', drops.ver + 'px');
  foot.style.setProperty('--help-chev', '0px');
  if (!chevron) return;
  const wrapper = document.createElement('span'),
    // The label's baseline: an empty inline-block on it.
    marker = document.createElement('span');
  marker.style.cssText = 'display:inline-block;width:0;height:0';
  help.insertBefore(wrapper, labelText);
  wrapper.append(labelText, marker);
  const base = marker.getBoundingClientRect().bottom;
  help.insertBefore(labelText, wrapper);
  wrapper.remove();
  const inkMiddle = base - (labelInk.a - labelInk.d) / 2,
    chevronRect = chevron.getBoundingClientRect();
  foot.style.setProperty('--help-chev', inkMiddle - (chevronRect.top + chevronRect.height / 2) + 'px');
}
// inkMetrics()'s canvas context, made on first use.
let INK_CONTEXT = null as CanvasRenderingContext2D | null;
// The ink of a text in an element's font as {a, d}: how far it rises above and reaches below the baseline (px), from
// the canvas's text metrics read at 64 times the size, because the canvas rounds them to whole pixels.
function inkMetrics(element: Element, text: string) {
  const context = (INK_CONTEXT ||
      (INK_CONTEXT = document.createElement('canvas').getContext('2d'))) as CanvasRenderingContext2D,
    scale = 64,
    barStyle = getComputedStyle(element);
  context.font =
    barStyle.fontStyle +
    ' ' +
    barStyle.fontWeight +
    ' ' +
    parseFloat(barStyle.fontSize) * scale +
    'px ' +
    barStyle.fontFamily;
  const measured = context.measureText(text);
  return { a: measured.actualBoundingBoxAscent / scale, d: measured.actualBoundingBoxDescent / scale };
}
// The Hangul letters of a text (syllables and jamo) - the glyphs that reach below the Latin baseline. Pure.
function hangulOf(text: string | null) {
  return String(text).replace(/[^ᄀ-ᇿ㄰-㆏가-힣]/g, '');
}
// Help's head on one ink line (docs/handbook/viewer.md §마크와 파비콘), the foot's rule: the wordmark ("limn" ends on
// the baseline) drops by the title's Hangul ink descent ('— 사용법'), so their ink bottoms meet; centred in its 20px
// box on the row, "limn" would stand below the title's foot. English ('— How to use') has no Hangul and no drop.
function headInk() {
  const head = $('#help-h'),
    title = head && head.querySelector(':scope>span');
  if (!title) return;
  const hangul = hangulOf(title.textContent);
  head.style.setProperty('--ink-word', inkDrops(hangul ? inkMetrics(title, hangul).d : 0, 0).word + 'px');
}
// The interface font arrives after the first layout (docs/handbook/viewer.md §글꼴): font-display: swap draws a text in
// a fallback until its slice of Pretendard has loaded, and a slice loads when a character of its range first shows.
// What was measured from text in the meantime - the sheet bar's steps (fitBarWords) and an open sheet's ink line
// (footInk, headInk) - is measured again each time a load finishes.
document.fonts.addEventListener('loadingdone', () => {
  frameHost().fitBarWords();
  if ($('#more').open) footInk();
  if ($('#help').open) headInk();
});
// Clicking outside a dialog (the backdrop) closes it - only for a click whose target is the dialog itself and that
// falls outside its box rectangle. The same for [더보기], help, the navigation sheet and the status line's list (and
// the Trash, in pins/view-cards.ts).
for (const dialogSelector of ['#more', '#help', '#nav-sheet', '#status-list'])
  $(dialogSelector).addEventListener('click', (event: MouseEvent) => {
    const dialog = event.currentTarget;
    if (!(dialog instanceof HTMLDialogElement) || event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    )
      dialog.close();
  });
// However the navigation sheet closes, the focus goes back to the button that opens it - unless it closed for the
// search.
$('#nav-sheet').addEventListener('close', () => {
  const button = $('#btn-pos');
  // Its search row has put the focus in the search field.
  if (frameHost().searchOpen()) return;
  if (button.getClientRects().length) button.focus({ preventScroll: true });
});
function topAnchor(offset?: number) {
  const scroller = $('#left'),
    scrollerTop = scroller.getBoundingClientRect().top,
    top = scrollerTop + (offset || 0),
    atTop = COARSE_POINTER_QUERY.matches && scroller.scrollTop <= 0,
    edge = offset ? 0 : 1;
  for (const pageElement of $$('.pg')) {
    const rect = pageElement.getBoundingClientRect();
    if (rect.bottom > top + edge)
      return {
        page: +pageElement.dataset.page,
        frac: Math.max(0, (top - rect.top) / rect.height),
        gap: Math.max(0, rect.top - top),
        atTop,
        y: rect.top - scrollerTop,
        h: rect.height,
      };
  }
  return null;
}
// Scrolls the PDF back to a reading spot from topAnchor() after a re-fit, with the space above its page (gap): without
// it a spot between two pages would put the page's top on the edge, as much as that space off. On a touch screen -
// where the select mode lives - a spot taken at the very top stays at the top, so the space above page 1 (its margin,
// or the select mode's reserve that keeps the mode bar off its first line) is kept at whatever height it has. Nothing
// is written when the spot's page stands where it stood at the same height: Chromium ends a smooth scroll at any write
// of the offset, the same one too, so the band settling 200ms into a jump from the phone's sheet (the keyboard held it)
// would stop a long glide part way. A kept view's spot (page and frac alone) has no place on screen to compare, so it is
// always scrolled to.
function restoreAnchor(anchor: ReturnType<typeof topAnchor> | { page: number; frac: number }) {
  if (!anchor) return;
  const scroller = $('#left');
  if ('atTop' in anchor && anchor.atTop) {
    if (scroller.scrollTop > 0) scroller.scrollTop = 0;
    return;
  }
  const pageElement = document.getElementById('p' + anchor.page);
  if (!pageElement) return;
  const rect = pageElement.getBoundingClientRect(),
    scrollerTop = scroller.getBoundingClientRect().top;
  if ('y' in anchor && Math.abs(rect.top - scrollerTop - anchor.y) < 0.5 && Math.abs(rect.height - anchor.h) < 0.5)
    return;
  scroller.scrollTop += rect.top - scrollerTop + anchor.frac * rect.height - (('gap' in anchor && anchor.gap) || 0);
}

export {
  onRelayout,
  setFrameHost,
  frameHost,
  BAND_TIMER,
  SLIDE_MS,
  applyLayout,
  applySide,
  coach,
  coachSideCollapsed,
  draftOpen,
  finishSideSlide,
  focusSideToggle,
  gripAria,
  headInk,
  openMore,
  outlineOverlay,
  panelField,
  relayout,
  setSelectMode,
  setSide,
  showSheet,
  toggleSide,
  topAnchor,
  restoreAnchor,
};
