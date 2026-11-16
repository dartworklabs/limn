// ------------------------------------------------ What the pin list asks the verdicts
// A verdict is a pin and is drawn as one; what only a verdict adds to a card, a result row and the marks on the pages -
// its badge, its figure, the mark of a verdict a newer one replaced, the page line that shows it - is the verdict
// feature's (verdict/flow-line.ts), which the pin list may not import (docs/handbook/viewer.md §모듈 경계). So it is a
// seam here: an interface for what the pin list asks, a registration function and an accessor. js/main.ts registers
// it once, at its top level before boot() runs (no code that runs while the script loads reaches it), and the pin list
// calls the registered function at the point, with the arguments and in the order it called the verdict function
// directly. The accessor called before its registration throws, naming the seam.
import type { Html } from '../platform/markup.ts';

// What a verdict pin adds to the pin list's drawing and jumping.
interface PinVerdicts {
  /** A verdict pin's badge ('판정 채택'), or null for a pin that is no verdict. */
  badge(pin: Pin): Html | null;
  /** The figure a verdict pin on a figure document is about, as a tag, or null. */
  target(pin: Pin): Html | null;
  /** The mark of a verdict a newer verdict of the same target replaced, or null. */
  oldMarker(pin: Pin): Html | null;
  /** The pin without the overlaps of verdicts about the same page target the page lines show. */
  dropOverlaps(pin: Pin): Pin;
  /** Draws the page verdict lines under the pages. */
  drawLines(): void;
  /** Whether a page verdict line shows the pin, so it draws no page-size box. */
  shownOnLine(pin: Pin): boolean;
  /** Brings the page verdict line that shows pin `id` into view; false when no line shows it. */
  jumpToLine(id: number): boolean;
}
let PIN_VERDICTS: PinVerdicts | null = null;
// Registers what a verdict adds to the pin list; js/main.ts calls it once.
function setPinVerdicts(verdicts: PinVerdicts) {
  PIN_VERDICTS = verdicts;
}
// The registered verdict part; throws before setPinVerdicts() has run.
function pinVerdicts(): PinVerdicts {
  if (!PIN_VERDICTS) throw new Error('setPinVerdicts() has not run: the pin list has no verdicts to draw');
  return PIN_VERDICTS;
}

export { pinVerdicts, setPinVerdicts };
