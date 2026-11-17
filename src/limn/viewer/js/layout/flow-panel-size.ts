// ------------------------------------------------ Panel width (docs/handbook/viewer.md §패널 폭과 시트 높이)
// wide/mid adjusts the right panel's width; narrow adjusts the bottom sheet's height. Width is remembered separately
// per screen kind (pinPrefs.side = wide, pinPrefs.sideMid = mid) - so a width fit for a spread-out screen never covers
// the desktop width. If the saved value exceeds the current screen's limit (collapsing/expanding, shrinking the
// window), the saved value is kept and only the visible width is clamped within the limit. The limit: the minimum is
// the width where the panel's tool bar fits on one line, the maximum is the width that leaves the body (PDF) side its
// minimum width. The outline's width bounds: 220-320px as an overlay; beside the document at most what leaves the PDF
// 290px beside the panel.
import { BAND, LAYOUT, COARSE_POINTER_QUERY, OUTLINE_MID_OPEN, SIDE_OPEN, setOutlineMidOpen } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { prefs, savePrefs } from '../platform/prefs.ts';
import { gripAria, outlineOverlay, panelField, relayout, setSide, restoreAnchor, topAnchor } from './flow.ts';
import { syncBackLayer } from './input.ts';
import { $ } from '../platform/dom.ts';
import { segmentFocusAt, keepSegmentFocus, roveSegment } from '../platform/segments.ts';
import { LAYOUT_BAND, LAYOUT_MODE } from '../app/rules-tables.ts';
// A panel's width range, and with it (the side panel's) the default width and the three presets.
interface PanelBounds {
  min: number;
  max: number;
}
interface SideBounds extends PanelBounds {
  def: number;
  presets: number[];
}
function outlineBounds() {
  if (outlineOverlay()) return { min: 220, max: 320 };
  const max = Math.max(180, Math.min(320, window.innerWidth - currentSideWidth() - 290));
  return { min: Math.min(220, max), max };
}
// Shows an outline width clamped to its bounds (--outline-width and the grip's ARIA) and answers it; nothing is saved.
function showOutlineWidth(width: number) {
  const bounds = outlineBounds();
  width = Math.round(Math.max(bounds.min, Math.min(bounds.max, width)));
  document.documentElement.style.setProperty('--outline-width', width + 'px');
  const grip = $('#outline-grip');
  grip.setAttribute('aria-valuemin', String(bounds.min));
  grip.setAttribute('aria-valuemax', String(bounds.max));
  grip.setAttribute('aria-valuenow', String(width));
  return width;
}
// Draws the outline's open/collapsed state and width for the layout (the overlay of mid and the tablet sheet keeps its
// own, unsaved) and syncs the back layer. The wide outline follows pinPrefs.outlineClosed; until one is saved it starts
// open with a mouse and collapsed on touch. The phone has no outline (CSS), so it draws no width.
function applyOutlineState() {
  const preferences = prefs(),
    closed = outlineOverlay()
      ? !OUTLINE_MID_OPEN
      : typeof preferences.outlineClosed === 'boolean'
        ? preferences.outlineClosed
        : COARSE_POINTER_QUERY.matches;
  document.body.classList.toggle('outline-collapsed', closed);
  const toggle = $('#nav-toc-toggle');
  toggle.setAttribute('aria-expanded', String(!closed));
  toggle.setAttribute('aria-label', closed ? '목차 펼치기' : '목차 접기');
  if (BAND !== LAYOUT_BAND.PHONE)
    showOutlineWidth(typeof preferences.outlineWidth === 'number' ? preferences.outlineWidth : 240);
  syncBackLayer(); // the mid outline overlay is a layer the back gesture closes
}
// Sets and remembers the outline width (pinPrefs.outlineWidth), then re-fits; the phone has no outline.
function setOutlineWidth(width: number) {
  if (BAND === LAYOUT_BAND.PHONE) return;
  width = showOutlineWidth(width);
  savePrefs({ outlineWidth: width });
  relayout();
}
// Opens or closes the outline at the same reading spot: the overlay (mid, tablet sheet) for now, collapsing the pin
// panel as it opens; wide remembers it in pinPrefs.outlineClosed.
function toggleOutline() {
  const anchor = topAnchor(),
    closed = !document.body.classList.contains('outline-collapsed');
  if (outlineOverlay()) {
    setOutlineMidOpen(!closed);
    if (!closed) setSide(false);
  } else savePrefs({ outlineClosed: closed });
  applyOutlineState();
  relayout();
  restoreAnchor(anchor);
  $('#nav-toc-toggle').focus({ preventScroll: true });
}
// The panel's width bounds, default width and the three presets ([좁게] [보통] [넓게]) for a layout at a window
// width.
function sideBounds(layout: string | null, windowWidth: number) {
  const clampRound = (value: number, low: number, high: number) => Math.round(Math.min(high, Math.max(low, value)));
  if (layout === LAYOUT_MODE.MID) {
    const min = 300,
      max = windowWidth <= 900 ? Math.min(440, windowWidth - 240) : Math.max(min, windowWidth - 488);
    const defaultWidth = clampRound(330, min, max);
    return { min, max, def: defaultWidth, presets: [min, defaultWidth, clampRound(windowWidth * 0.5, min, max)] };
  }
  const min = 280,
    max = Math.max(min, Math.min(Math.round(windowWidth * 0.8), windowWidth - 486)),
    defaultWidth = clampRound(348, min, max);
  return {
    min,
    max,
    def: defaultWidth,
    presets: [clampRound(300, min, max), defaultWidth, clampRound(windowWidth * 0.42, min, max)],
  };
}
function clampSide(width: number, bounds: PanelBounds) {
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, width)));
}
// Cycles through preset steps: the next step wider than the current width, wrapping to the narrowest if already at the
// widest. presetIndex is the step within +-4px (or -1 if none matches).
function nextPreset(presets: number[], width: number) {
  const wider = presets.find((preset) => preset > width + 4);
  return wider === undefined ? presets[0] : wider;
}
function presetIndex(presets: number[], width: number) {
  return presets.findIndex((preset) => Math.abs(preset - width) <= 4);
}
// Where a handle drag lands (docs/handbook/viewer.md §패널 폭과 시트 높이). requestedWidth = the width the pointer asks
// for: the drag-start width plus how far it moved left, unclamped (a drag from the collapsed rail starts at 0).
// collapseBelow = half the minimum, rounded down. Returns {w: the width to show, zone}: 'follow' at or above the
// minimum (the width follows, up to the maximum); 'min' from collapseBelow up to the minimum (it stops at the minimum
// and the handle turns primary); 'collapse' below collapseBelow (a release collapses the panel); 'blocked' there while
// a draft is open (composing/editing/replying/relocating - it stops at the minimum instead).
function snapSide(requestedWidth: number, bounds: PanelBounds, composing: boolean) {
  const collapseBelow = Math.floor(bounds.min / 2);
  if (requestedWidth >= bounds.min) return { w: Math.min(bounds.max, Math.round(requestedWidth)), zone: 'follow' };
  if (requestedWidth >= collapseBelow) return { w: bounds.min, zone: 'min' };
  return { w: bounds.min, zone: composing ? 'blocked' : 'collapse' };
}
// The handle's keys as a WAI-ARIA window splitter whose primary pane is the panel (aria-valuenow = its width). Open:
// Enter collapses, Space cycles the presets, Home/End go to the minimum/maximum, ←/→ widen/narrow by 16px within the
// bounds (never below the minimum - collapsing is Enter's job). Collapsed: Enter/Space open to the saved width, Home/←
// open at the minimum, End at the maximum; → does nothing. Returns {act:'collapse'|'cycle'|'open'} or {act:'width', w},
// or null for any other key.
type GripAction = { act: 'open' } | { act: 'collapse' } | { act: 'cycle' } | { act: 'width'; w: number };
function gripKey(key: string, width: number, bounds: PanelBounds, collapsed: boolean): GripAction | null {
  if (collapsed) {
    if (key === 'Enter' || key === ' ') return { act: 'open' };
    if (key === 'Home' || key === 'ArrowLeft') return { act: 'width', w: bounds.min };
    return key === 'End' ? { act: 'width', w: bounds.max } : null;
  }
  if (key === 'Enter') return { act: 'collapse' };
  if (key === ' ') return { act: 'cycle' };
  const to = { Home: bounds.min, End: bounds.max, ArrowLeft: width + 16, ArrowRight: width - 16 }[key];
  return to === undefined ? null : { act: 'width', w: clampSide(to, bounds) };
}
// The preference key of this layout's saved panel width.
function sideKey() {
  return LAYOUT === LAYOUT_MODE.MID ? 'sideMid' : 'side';
}
// The panel's width as drawn now.
function currentSideWidth() {
  return Math.round($('#right').getBoundingClientRect().width);
}
// The width last shown and its bounds - the handle's ARIA value while the panel is open (gripAria).
let SIDE_SHOWN: { w: number; min: number; max: number } | null = null;
// Shows a panel width without saving it: #right, --side-w, and the handle's ARIA while the panel is open.
function showSideWidth(width: number, bounds: PanelBounds) {
  $('#right').style.width = width + 'px';
  document.documentElement.style.setProperty('--side-w', width + 'px');
  SIDE_SHOWN = { w: width, min: bounds.min, max: bounds.max };
  if (SIDE_OPEN) gripAria();
}
// The width the panel has in this layout, open or folded: the layout's saved width (sideKey), else its default, inside
// its bounds. applySideWidth draws it; renderSizeSegment checks it.
function sideWidthFor(bounds: SideBounds) {
  const saved = prefs()[sideKey()];
  return clampSide(typeof saved === 'number' ? saved : bounds.def, bounds);
}
// Draws the layout's panel width; narrow draws the sheet height instead.
function applySideWidth() {
  if (LAYOUT === LAYOUT_MODE.NARROW) {
    $('#right').style.width = '';
    applySheet();
    return;
  }
  const bounds = sideBounds(LAYOUT, window.innerWidth);
  showSideWidth(sideWidthFor(bounds), bounds);
}
// Sets and remembers the width, then re-fits page width/marks (position is preserved - relayout uses
// topAnchor/restoreAnchor).
function setSideWidth(width: number) {
  if (LAYOUT === LAYOUT_MODE.NARROW) return;
  const bounds = sideBounds(LAYOUT, window.innerWidth);
  width = clampSide(width, bounds);
  showSideWidth(width, bounds);
  savePrefs({ [sideKey()]: width });
  relayout();
  renderSizeSegment();
}
// The handle's double click and Space: the next preset width.
function cycleSideWidth() {
  if (LAYOUT === LAYOUT_MODE.NARROW) return;
  const bounds = sideBounds(LAYOUT, window.innerWidth);
  setSideWidth(nextPreset(bounds.presets, currentSideWidth()));
}
// Sheet height is stored as a fraction of screen height (--sheet-f) - CSS shrinks it to fit within the visible height
// when the keyboard is up.
const SHEET_FRACTIONS = [0.45, 0.64, 1],
  SHEET_MIN_FRACTION = 0.3,
  SHEET_CLOSE_FRACTION = 0.25,
  SHEET_COMPOSE_FRACTION = 0.8;
// The tablet sheet's highest keyboard lift (tabletLift).
const SHEET_TAB_LIFT_MAX = 0.6;
// The sheet's own preference key and default height: the phone's 64% in pinPrefs.sheetF, the tablet sheet's 45% in
// sheetFTab - so a height chosen on a folded phone never becomes the unfolded or tablet screen's default.
function sheetPref() {
  return BAND === LAYOUT_BAND.TABLET_SHEET ? { key: 'sheetFTab', def: 0.45 } : { key: 'sheetF', def: 0.64 };
}
// While composing, the phone sheet rises to SHEET_COMPOSE_FRACTION (CSS body.sheet-up, never saved) so the note field
// and the location line above it stay in view; the first height the user sets meanwhile (a drag, a tap, a preset, a
// key) wins until the composer closes. The tablet sheet does not rise: at 45% the location line, the note and the save
// row fit and the page dragged on stays in view. Only when they no longer fit - with the keyboard up, or with the
// suggestion editor open under the note - it rises as far as they need, at most SHEET_TAB_LIFT_MAX (tabletLift).
let SHEET_KEPT = false;
// Marks that the user set the sheet height while composing: the lift stops and their height applies. Outside composing
// it does nothing.
function keepSheet() {
  if ($('#composer').hidden) return;
  SHEET_KEPT = true;
  document.body.classList.remove('sheet-up');
}
// The sheet height in use (a fraction, 30-100%): the band's saved one, else its default.
function sheetFraction() {
  const sheetPreference = sheetPref(),
    saved = prefs()[sheetPreference.key];
  return typeof saved === 'number' ? Math.min(1, Math.max(SHEET_MIN_FRACTION, saved)) : sheetPreference.def;
}
// Draws the sheet height: the band's own (sheetFraction), or on the tablet sheet its composing lift (tabletLift). Never
// saved.
function applySheet() {
  document.documentElement.style.setProperty('--sheet-f', String(tabletLift()));
}
// The tablet sheet's height for need (the fraction of the screen the composer down to its note or open editor and the
// save row take): its own height if they fit, else just what they need, at most SHEET_TAB_LIFT_MAX; a higher chosen
// height stays. Pure.
function sheetLift(fraction: number, need: number) {
  return Math.max(fraction, Math.min(SHEET_TAB_LIFT_MAX, need));
}
// The sheet height to draw now: sheetFraction(), lifted (sheetLift) on the tablet sheet while composing - with the
// keyboard up (a panel text field has focus on a touch screen) or with the suggestion editor open - and the user has
// not set a height meanwhile. Needs the sheet's top down to the bottom of the last block that must show (the open
// editor, else the note), one 8px step and the save row, against the layout height; measured in the sheet's scroll
// space, so the same at any scroll and while the location line sticks.
function tabletLift() {
  const fraction = sheetFraction();
  if (BAND !== LAYOUT_BAND.TABLET_SHEET || SHEET_KEPT || $('#composer').hidden || !COARSE_POINTER_QUERY.matches)
    return fraction;
  const editor = $('#c-sg-text'),
    open = editor.getClientRects().length > 0;
  if (!open && !panelField()) return fraction;
  const verdictRow = $('#c-verdict-row'),
    panel = $('#right'),
    last = open ? editor : verdictRow.getClientRects().length ? verdictRow : $('#note'),
    bottom = last.getBoundingClientRect().bottom - panel.getBoundingClientRect().top + panel.scrollTop;
  return sheetLift(fraction, (bottom + 8 + $('#c-actions').offsetHeight) / window.innerHeight);
}
// Sets and remembers the sheet height (a fraction, clamped to 30-100%, kept to 1/10000: a whole pixel on any screen)
// under the band's key, opens a collapsed sheet, and ends the composing lift.
function setSheetFraction(fraction: number) {
  keepSheet();
  fraction = Math.min(1, Math.max(SHEET_MIN_FRACTION, fraction));
  savePrefs({ [sheetPref().key]: Math.round(fraction * 10000) / 10000 });
  applySheet();
  if (!SIDE_OPEN) setSide(true);
  renderSizeSegment();
}
// The next height stop above the one shown (the composing lift counts as shown); wraps to the lowest.
function cycleSheet() {
  const shown = document.body.classList.contains('sheet-up')
      ? Math.max(sheetFraction(), SHEET_COMPOSE_FRACTION)
      : sheetFraction(),
    nextIndex = SHEET_FRACTIONS.findIndex((stop) => stop > shown + 0.02);
  setSheetFraction(SHEET_FRACTIONS[nextIndex < 0 ? 0 : nextIndex]);
}
// The '패널 폭' (wide/mid) / '시트 높이' (narrow) segment control inside [⋯], the size now chosen checked. The width
// checked is the one the layout gives the panel (sideWidthFor), not one measured or last shown: a folded panel measures
// 0 wide (the tablet's [더보기], its panel folded at first, would check no width at all), and a layout change draws
// this row (applyLayout) before the panel takes the new layout's width (applySideWidth), so a measured width is the old
// layout's - a step checked that the panel does not open at, and Home on the row choosing nothing.
function renderSizeSegment() {
  const box = $('#m-size');
  if (!box) return;
  const narrow = LAYOUT === LAYOUT_MODE.NARROW,
    at = segmentFocusAt(box);
  $('#m-size-l').textContent = narrow ? '시트 높이' : '패널 폭';
  box.setAttribute('aria-label', narrow ? '시트 높이' : '패널 폭');
  let names, checkedIndex;
  if (narrow) {
    names = ['낮게', '보통', '높게'];
    const fraction = sheetFraction();
    checkedIndex = SHEET_FRACTIONS.findIndex((stop) => Math.abs(stop - fraction) <= 0.02);
  } else {
    names = ['좁게', '보통', '넓게'];
    const bounds = sideBounds(LAYOUT, window.innerWidth);
    checkedIndex = presetIndex(bounds.presets, sideWidthFor(bounds));
  }
  setHtml(
    box,
    html`${names.map((name, index) => html`<button class="${index === checkedIndex ? 'on' : ''}" role="radio" aria-checked="${index === checkedIndex}" data-act="size-preset" data-i="${index}">${name}</button>`)}`,
  );
  // One Tab stop, the size chosen (else the first: a dragged width has none), and the focus kept (main.ts).
  roveSegment(box);
  keepSegmentFocus(box, at);
}
// Applies the size row's preset at index: a sheet height on narrow, else a panel width.
function sizePreset(index: number) {
  if (LAYOUT === LAYOUT_MODE.NARROW) {
    setSheetFraction(SHEET_FRACTIONS[index]);
    return;
  }
  setSideWidth(sideBounds(LAYOUT, window.innerWidth).presets[index]);
}
// Sets SHEET_KEPT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSheetKept<Value extends typeof SHEET_KEPT>(value: Value): Value {
  SHEET_KEPT = value;
  return value;
}
export {
  SHEET_CLOSE_FRACTION,
  SHEET_FRACTIONS,
  SHEET_KEPT,
  SHEET_MIN_FRACTION,
  SIDE_SHOWN,
  applyOutlineState,
  applySheet,
  applySideWidth,
  currentSideWidth,
  cycleSheet,
  cycleSideWidth,
  gripKey,
  keepSheet,
  outlineBounds,
  renderSizeSegment,
  setOutlineWidth,
  setSheetFraction,
  setSheetKept,
  setSideWidth,
  sheetFraction,
  showOutlineWidth,
  showSideWidth,
  sideBounds,
  sizePreset,
  snapSide,
  toggleOutline,
};
