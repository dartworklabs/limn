// ------------------------------------------------ What the page surface asks the features above it
// pdf draws a document's pages, sizes them, takes a selection on them and goes to a page; the pins' marks on them, the
// verdict's page lines and reason field, the composer that takes a selection, the Markdown surface a document drawn in
// the browser hands to, and the changes view the pages leave are the features above (pins, verdict, composer,
// markdown, revisions). pdf may not import them (docs/handbook/viewer.md §모듈 경계), so each need is a seam here: an
// interface for what pdf asks, a registration function and an accessor. js/main.ts registers every seam once, at its
// top level before boot() runs (no code that runs while the script loads reaches one), and pdf calls the registered
// function at the point, with the arguments and in the order it called the feature function directly. An accessor
// called before its registration throws, naming the seam.

// The pins' marks on the pages (pins/flow-list.ts): drawing them, and their badges' sides for the pages' width now.
interface PageMarks {
  /** Draws the pins' marks on the document. */
  draw(): void;
  /** Places every page number, mark badge and pending box badge for the pages' width and margin now. */
  placeBadges(): void;
}
let PAGE_MARKS: PageMarks | null = null;
// Registers the pins' marks; js/main.ts calls it once.
function setPageMarks(marks: PageMarks) {
  PAGE_MARKS = marks;
}
// The registered marks; throws before setPageMarks() has run.
function pageMarks(): PageMarks {
  if (!PAGE_MARKS) throw new Error('setPageMarks() has not run: the pages have no pin marks to draw');
  return PAGE_MARKS;
}

// The verdict on the pages (verdict/flow-reason.ts, verdict/flow-line.ts): a focus in the reason popover kept across a
// rebuild of the pages, the page lines' size, and each page's verdict pins for the page list.
interface PageVerdicts {
  /** What has the focus in the reason popover, to come back once the pages are drawn (null: nothing). */
  holdReasonFocus(): unknown;
  /** Gives the focus back to what holdReasonFocus kept. */
  restoreReasonFocus(held: unknown): void;
  /** Sizes the page verdict lines for the pages' width now. */
  sizeLines(): void;
  /** The verdict pins of each page, the newest first. */
  pagePins(): Map<number, Pin[]>;
}
let PAGE_VERDICTS: PageVerdicts | null = null;
// Registers the verdict on the pages; js/main.ts calls it once.
function setPageVerdicts(verdicts: PageVerdicts) {
  PAGE_VERDICTS = verdicts;
}
// The registered verdict on the pages; throws before setPageVerdicts() has run.
function pageVerdicts(): PageVerdicts {
  if (!PAGE_VERDICTS) throw new Error('setPageVerdicts() has not run: the pages have no verdict lines');
  return PAGE_VERDICTS;
}

// The composer a selection on the pages goes to (composer/flow-pick.ts, composer/view-selection-popover.ts): the pick
// of a dragged region, dropping it, the note popover by the selection box, and the re-place a drag on a pin's number
// badge places the pin again with (composer/flow-repick.ts, docs/adr/0050-pin-badge-drag-reposition.md).
interface PageSelection {
  /** Turns a dragged region into the composer's place. */
  pick(region: unknown): void;
  /**
   * Where pin `id` stands now and whether it is a region pin, for a press on its number badge, or null when that
   * press places nothing (see composer/flow-repick.ts badgeMovePin). `mouse` tells a mouse press, which may place a
   * pin without the re-place mode, from a finger, which may not.
   */
  badgeMove(id: number, mouse: boolean): { frac: number[]; region: boolean } | null;
  /** Turns the re-place mode on for pin `id` from a drag on its badge that is already moving. */
  repickFromBadge(id: number): void;
  /** Ends the re-place a badge drag turned on, for a gesture that ended without a drop. */
  cancelRepick(): void;
  /** Drops the selection and closes the composer. */
  discard(): void;
  /** Opens the note popover by a selection box. */
  openPopover(box: HTMLElement): void;
  /** Whether the note popover shows. */
  popoverOpen(): boolean;
  /** The note popover's element. */
  popover(): HTMLElement;
  /** The selection box the note popover stands by, or null. */
  popoverBox(): HTMLElement | null;
  /** Places the note popover by its box again. */
  placePopover(): void;
}
let PAGE_SELECTION: PageSelection | null = null;
// Registers the composer a selection goes to; js/main.ts calls it once.
function setPageSelection(selection: PageSelection) {
  PAGE_SELECTION = selection;
}
// The registered composer; throws before setPageSelection() has run.
function pageSelection(): PageSelection {
  if (!PAGE_SELECTION) throw new Error('setPageSelection() has not run: a selection on the pages has no composer');
  return PAGE_SELECTION;
}

// What pdf writes into the Markdown surface's state when it draws pages (markdown/state.ts MARKDOWN_VIEW): the draw
// generation, which a draw still on its way checks, and the document it shows.
interface MarkdownDrawn {
  gen: number;
  shown: string | null;
}
// A document the browser draws from its source (markdown/view.ts), which the page surface hands to.
interface PageMarkdown {
  /** The surface's draw state, written in place. */
  drawn(): MarkdownDrawn;
  /** Reads the source and draws the document. */
  build(): void;
  /** Goes to a heading of the drawn document. */
  goToHeading(index: number): void;
  /** Draws the drawn document's section strip and position button. */
  updateStrip(): void;
}
let PAGE_MARKDOWN: PageMarkdown | null = null;
// Registers the Markdown surface; js/main.ts calls it once.
function setPageMarkdown(markdown: PageMarkdown) {
  PAGE_MARKDOWN = markdown;
}
// The registered Markdown surface; throws before setPageMarkdown() has run.
function pageMarkdown(): PageMarkdown {
  if (!PAGE_MARKDOWN) throw new Error('setPageMarkdown() has not run: the page surface has no Markdown surface');
  return PAGE_MARKDOWN;
}

// The changes view the pages leave when one is gone to (revisions/flow.ts).
interface PageChanges {
  /** Shows the manuscript or the changes view. */
  setMode(mode: string): void;
}
let PAGE_CHANGES: PageChanges | null = null;
// Registers the changes view; js/main.ts calls it once.
function setPageChanges(changes: PageChanges) {
  PAGE_CHANGES = changes;
}
// The registered changes view; throws before setPageChanges() has run.
function pageChanges(): PageChanges {
  if (!PAGE_CHANGES) throw new Error('setPageChanges() has not run: the pages cannot leave the changes view');
  return PAGE_CHANGES;
}
export {
  pageChanges,
  pageMarkdown,
  pageMarks,
  pageSelection,
  pageVerdicts,
  setPageChanges,
  setPageMarkdown,
  setPageMarks,
  setPageSelection,
  setPageVerdicts,
};
