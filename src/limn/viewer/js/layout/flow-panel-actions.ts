import { showSideWidth } from './view-panel-grip.ts';
import {
  sideKey,
  clampSide,
  nextPreset,
  sideBounds,
  renderSizeSegment,
  showOutlineWidth,
  currentSideWidth,
  SHEET_MIN_FRACTION,
  SHEET_FRACTIONS,
  SHEET_COMPOSE_FRACTION,
  sheetPref,
  keepSheet,
  applySheet,
  sheetFraction,
} from './flow-panel-size.ts';
import { BAND, LAYOUT, SIDE_OPEN } from '../app/state.ts';
import { savePrefs } from '../platform/prefs.ts';
import { relayout, setSide } from './flow.ts';
import { LAYOUT_BAND, LAYOUT_MODE } from '../app/rules-tables.ts';

// Sets and remembers the outline width (pinPrefs.outlineWidth), then re-fits; the phone has no outline.
function setOutlineWidth(width: number) {
  if (BAND === LAYOUT_BAND.PHONE) return;
  width = showOutlineWidth(width);
  savePrefs({ outlineWidth: width });
  relayout();
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
// Applies the size row's preset at index: a sheet height on narrow, else a panel width.
function sizePreset(index: number) {
  if (LAYOUT === LAYOUT_MODE.NARROW) {
    setSheetFraction(SHEET_FRACTIONS[index]);
    return;
  }
  setSideWidth(sideBounds(LAYOUT, window.innerWidth).presets[index]);
}
export { setOutlineWidth, setSideWidth, cycleSideWidth, setSheetFraction, cycleSheet, sizePreset };
