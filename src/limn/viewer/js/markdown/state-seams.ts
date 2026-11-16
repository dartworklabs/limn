// ------------------------------------------------ What the Markdown surface asks the features above it
// markdown draws a document from its source, offers its lines and takes a pick of them; a text document's own view and
// ladder, the composer and the verdict row a line pick fills, and the pins' marks on the lines are the features above
// (text, composer, verdict, pins). markdown may not import them (docs/handbook/viewer.md §모듈 경계), so each need is a
// seam here: an interface for what markdown asks, a registration function and an accessor. js/main.ts registers every
// seam once, at its top level before boot() runs (no code that runs while the script loads reaches one), and markdown
// calls the registered function at the point, with the arguments and in the order it called the feature function
// directly. An accessor called before its registration throws, naming the seam.

// A text document (text/view.ts), drawn with this surface's line machinery: its view and its ladder.
interface TextSurface {
  /** Draws the text document's lines; null when the draw went stale or drew nothing. */
  build(stale: () => boolean, ends: Record<string, number> | undefined): Promise<HTMLElement | null>;
  /** The ladder for a range of the text document's lines. */
  levels(range: { lo: number; hi: number }): Rung[];
}
let TEXT_SURFACE: TextSurface | null = null;
// Registers the text surface; js/main.ts calls it once.
function setTextSurface(surface: TextSurface) {
  TEXT_SURFACE = surface;
}
// The registered text surface; throws before setTextSurface() has run.
function textSurface(): TextSurface {
  if (!TEXT_SURFACE) throw new Error('setTextSurface() has not run: the Markdown surface cannot draw a text document');
  return TEXT_SURFACE;
}

// What a pick of lines fills (composer/flow-pick.ts, composer/flow-repick.ts, verdict/flow-line.ts): the re-placing
// banner's comparison, the composer's busy state and its drawing, and the verdict row.
interface LinePick {
  /** Draws the re-placing banner's comparison of the old and the new place. */
  compare(): void;
  /** Shows the composer as waiting for an answer, or not. */
  setBusy(on: boolean): void;
  /** Draws the composer. */
  renderComposer(): void;
  /** Draws the composer's verdict row. */
  renderVerdictRow(): void;
}
let LINE_PICK: LinePick | null = null;
// Registers what a pick of lines fills; js/main.ts calls it once.
function setLinePick(pick: LinePick) {
  LINE_PICK = pick;
}
// The registered composer and verdict row; throws before setLinePick() has run.
function linePick(): LinePick {
  if (!LINE_PICK) throw new Error('setLinePick() has not run: a pick of lines has no composer');
  return LINE_PICK;
}

// The pins' marks on the drawn document's lines (pins/flow-list.ts).
interface LineMarks {
  /** Draws the pins' marks on the document. */
  draw(): void;
}
let LINE_MARKS: LineMarks | null = null;
// Registers the pins' marks; js/main.ts calls it once.
function setLineMarks(marks: LineMarks) {
  LINE_MARKS = marks;
}
// The registered marks; throws before setLineMarks() has run.
function lineMarks(): LineMarks {
  if (!LINE_MARKS) throw new Error('setLineMarks() has not run: the drawn document has no pin marks to draw');
  return LINE_MARKS;
}
export { lineMarks, linePick, setLineMarks, setLinePick, setTextSurface, textSurface };
