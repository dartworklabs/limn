// ------------------------------------------------ What documents asks the features above it
// documents decides which document is open and when it is drawn, saved, left and refreshed; drawing it, its outline
// and page list, its search, its Markdown lines and the changes view are the features above (pdf, markdown,
// revisions). documents may not import them (docs/handbook/viewer.md §모듈 경계), so each need is a seam here: an
// interface for what documents asks, a registration function and an accessor. js/main.ts registers every seam once, at
// its top level before boot() runs (no code that runs while the script loads reaches one), and documents calls the
// registered function at the point, with the arguments and in the order it called the feature function directly. An
// accessor called before its registration throws, naming the seam.

// The pages of a PDF document (pdf/view-pages.ts, pdf/flow-open.ts, pdf/view-draw.ts): drawing them, their scale and
// the PDF.js document behind them.
interface PageSurface {
  /** Draws the open document's page elements (or hands a drawn document to its surface). */
  build(): void;
  /** Fits the page width to the room, once the pages are drawn. */
  fitWidth(): void;
  /** The widest page's width in points. */
  widestPoints(): number;
  /** The scale a document opens at without a kept view. */
  startScale(): number;
  /** Sizes the drawn pages again at the current scale. */
  reapplyScale(): void;
  /** The address of a page's picture. */
  pageSource(page: unknown): string;
  /** Opens the current build's PDF.js document. */
  openVector(): void;
  /** Lets go of every page drawn from the PDF.js document. */
  releaseVector(): void;
}
let PAGE_SURFACE: PageSurface | null = null;
// Registers the pages of a PDF document; js/main.ts calls it once.
function setPageSurface(surface: PageSurface) {
  PAGE_SURFACE = surface;
}
// The registered pages; throws before setPageSurface() has run.
function pageSurface(): PageSurface {
  if (!PAGE_SURFACE) throw new Error('setPageSurface() has not run: documents has no pages to draw');
  return PAGE_SURFACE;
}

// The ways around a PDF document (pdf/view-outline.ts, pdf/view-page-list.ts, pdf/flow.ts): its outline, its page
// list and its search, which the navigation sheet, the document menu and a switch use.
interface PageNavigation {
  /** Ends the search of the document being left. */
  leaveSearch(): void;
  /** Fits the search field to the nav bar's room. */
  fitSearch(): void;
  /** Closes the page list's popover; back gives the focus back to its button. */
  closePageList(back: boolean): void;
  /** The page of the outline's current section, 0 before one is known. */
  outlinePage(): number;
  /** Marks the outline's current section. */
  markOutline(): void;
  /** Draws the navigation sheet's page rows. */
  drawSheetPages(): void;
  /** Scrolls a page list (an element) to its current page's row. */
  revealPageRow(list: unknown): void;
  /** Gives a page list's (an element's) cut titles their whole text as a tip. */
  tipCutTitles(list: unknown): void;
}
let PAGE_NAVIGATION: PageNavigation | null = null;
// Registers the outline, the page list and the search; js/main.ts calls it once.
function setPageNavigation(navigation: PageNavigation) {
  PAGE_NAVIGATION = navigation;
}
// The registered outline, page list and search; throws before setPageNavigation() has run.
function pageNavigation(): PageNavigation {
  if (!PAGE_NAVIGATION) throw new Error('setPageNavigation() has not run: documents has no outline or page list');
  return PAGE_NAVIGATION;
}

// What documents reads of the Markdown surface's drawn document and writes into it (markdown/view.ts MARKDOWN_VIEW):
// which document is drawn and from which source, the line read now and the line count, the source asked for and the
// line to come back to once it is drawn.
interface MarkdownReading {
  readonly doc: string | null;
  readonly shown: string | null;
  readonly mtime: number | null;
  asked: number | null;
  readonly at: number;
  readonly lines: readonly string[];
  want: { line: number; off: number; top: number } | null;
}
// A document drawn in the browser from its source (markdown/view.ts; a text document uses the same machinery).
interface MarkdownSurface {
  /** The drawn document's state, read and written in place. */
  reading(): MarkdownReading;
  /** Reads the source and draws the document again. */
  build(): void;
  /** Shows a tree image rewritten on disk. */
  checkTreeImages(): Promise<number>;
  /** The line at the reading area's top and how far it stands below it, or null. */
  readingAnchor(): { line: number; off: number; top: number } | null;
  /** The phone's position button for a drawn document: its name, lines and accessible name. */
  positionLabel(
    doc: string,
    line: number,
    lineCount: number,
    multi: boolean,
    wide: boolean,
  ): { name: string; pages: string; label: string };
  /** Hides the page-only controls for a drawn document, and says why. */
  showHint(): void;
  /** The line elements of the source lines first to last. */
  lineLeaves(first: number, last: number): HTMLElement[];
  /** Brings line elements into view. */
  showLines(elements: HTMLElement[]): void;
}
let MARKDOWN_SURFACE: MarkdownSurface | null = null;
// Registers the Markdown surface; js/main.ts calls it once.
function setMarkdownSurface(surface: MarkdownSurface) {
  MARKDOWN_SURFACE = surface;
}
// The registered Markdown surface; throws before setMarkdownSurface() has run.
function markdownSurface(): MarkdownSurface {
  if (!MARKDOWN_SURFACE) throw new Error('setMarkdownSurface() has not run: documents has no Markdown surface');
  return MARKDOWN_SURFACE;
}

// What documents writes into the changes view before it opens (revisions/flow.ts REVISION_VIEW): the range to paint
// and the pin it was opened for.
interface ChangesWanted {
  want: { base: string; top: string } | null;
  target: RevTarget | null;
}
// The changes view ([변경 보기], revisions/flow.ts): which view shows, and its commit list.
interface ChangesView {
  /** The view's wanted range and pin, written in place. */
  wanted(): ChangesWanted;
  /** Shows the manuscript or the changes view. */
  setMode(mode: string): void;
  /** Reads the open document's commits again. */
  load(): void;
}
let CHANGES_VIEW: ChangesView | null = null;
// Registers the changes view; js/main.ts calls it once.
function setChangesView(view: ChangesView) {
  CHANGES_VIEW = view;
}
// The registered changes view; throws before setChangesView() has run.
function changesView(): ChangesView {
  if (!CHANGES_VIEW) throw new Error('setChangesView() has not run: documents has no changes view');
  return CHANGES_VIEW;
}
export {
  changesView,
  markdownSurface,
  pageNavigation,
  pageSurface,
  setChangesView,
  setMarkdownSurface,
  setPageNavigation,
  setPageSurface,
};
