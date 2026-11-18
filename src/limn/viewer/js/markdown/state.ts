/** Own the source and reading state shared by the document surfaces, and the contexts used to render tokens. */
const MARKDOWN_LIMITS = Object.freeze({
  nesting: 20,
  blocks: 30000,
  inlines: 150000,
  elements: 60000,
  ms: 2000,
  lines: 50000,
  chunk: 2000,
  tex: 10000,
});
// The source that was read (doc, file, lines, mtime) and the stamp the light poll requested (asked).
// shown names the document currently mounted in #doc. During a switch it can differ from the source being rendered.
// want is the reading anchor requested for a return visit; spot preserves the position across width changes or a
// redraw while hidden. The drawing context is shared with renderTokens so it can count elements and collect headings.
interface MarkdownViewState extends RenderContext {
  gen: number;
  doc: string | null;
  file: string;
  name: string;
  mtime: number | null;
  asked: number | null;
  at: number;
  limit: string | null;
  shown: string | null;
  want: { line: number; off: number; top: number } | null;
  spot: {
    doc: string | null;
    w: number;
    top: number;
    el: HTMLElement | null;
    line: number;
    key: string;
    frac: number;
    past: number;
    off: number | null;
    sel: boolean;
    again: boolean;
  } | null;
}
const MARKDOWN_VIEW: MarkdownViewState = {
  gen: 0,
  doc: '',
  file: '',
  name: '',
  lines: [],
  mtime: null,
  asked: null,
  at: 0,
  limit: null,
  heads: [],
  els: 0,
  marked: 0,
  bom: false,
  tex: 0,
  shown: '',
  want: null,
  spot: null,
};
// A draw's render context (RenderContext): the source lines it numbers its blocks from (lines), the elements built so
// far (els), the characters drawn in their boxes (marked), whether the next text drawn may be the file's first, its
// byte-order mark kept (bom, drawText), the headings (heads), and how many formulas were drawn - a count to draw them
// on, null not to draw them at all (tex, ADR-0036 D3: the rendered compare keeps the source characters, which its block
// keys and its word diff read). The renderer reads and writes only these; the document view's context is MARKDOWN_VIEW
// itself (renderDocument), and the rendered compare (revisions/view-rendered-compare.ts) builds each side with a
// context of its own (newRenderContext).
type DrawnHeading = { level: number; lo: number; el: HTMLElement; title: string; slug: string };
type RenderContext = {
  lines: string[];
  els: number;
  marked: number;
  bom: boolean;
  heads: DrawnHeading[];
  tex: number | null;
};
// A fresh render context for lines: nothing built, its first text the file's first, its math kept as characters.
function newRenderContext(lines: string[]): RenderContext {
  return { lines, els: 0, marked: 0, bom: String(lines[0] || '').charCodeAt(0) === 0xfeff, heads: [], tex: null };
}
// The render context a drawn root was built with (the compare's sides, keepRenderContext); any other root is the
// document view's, MARKDOWN_VIEW.
const ROOT_CONTEXTS: WeakMap<Element, RenderContext> = new WeakMap();
function keepRenderContext(root: Element, context: RenderContext) {
  ROOT_CONTEXTS.set(root, context);
}
function renderContextOf(element: Element | null): RenderContext {
  const root = element && element.closest('.md');
  return (root && ROOT_CONTEXTS.get(root)) || MARKDOWN_VIEW;
}

/** Invalidate earlier requests and identify the draw that may publish its result. */
function beginMarkdownDraw() {
  return ++MARKDOWN_VIEW.gen;
}

/** Record which document owns the column, or an empty key while it is loading. */
function setShownDocument(doc: string | null) {
  MARKDOWN_VIEW.shown = doc;
}

/** Let the next poll retry a read that failed. */
function forgetSourceStamp() {
  MARKDOWN_VIEW.asked = null;
  MARKDOWN_VIEW.mtime = null;
}

/** Remember a size refusal for the requested stamp, with no source or headings. */
function recordOversizeSource() {
  MARKDOWN_VIEW.lines = []; // 413: too large to send
  MARKDOWN_VIEW.heads = [];
  MARKDOWN_VIEW.mtime = MARKDOWN_VIEW.asked;
}

/** Install the source and return the previous lines when a new stamp replaces them on the same document. */
function recordMarkdownSource(docKey: string | null, source: SourceAnswer) {
  const before =
    MARKDOWN_VIEW.doc === docKey && MARKDOWN_VIEW.mtime !== null && MARKDOWN_VIEW.mtime !== source.src_mtime
      ? MARKDOWN_VIEW.lines
      : null;
  MARKDOWN_VIEW.doc = docKey;
  MARKDOWN_VIEW.mtime = source.src_mtime;
  MARKDOWN_VIEW.file = String(source.file || '');
  MARKDOWN_VIEW.name = MARKDOWN_VIEW.file.split('/').pop() || MARKDOWN_VIEW.file;
  MARKDOWN_VIEW.lines = Array.isArray(source.lines) ? source.lines.map(String) : [];
  return before;
}

/** Line views and notices have no outline to restore. */
function clearMarkdownHeadings() {
  MARKDOWN_VIEW.heads = [];
}

/** Consume the requested reading anchor and preserve it across a redraw of a hidden column. */
function prepareMarkdownColumn(doc: string | null, limit: string | null, shown: boolean) {
  const want = MARKDOWN_VIEW.want;
  MARKDOWN_VIEW.want = null;
  MARKDOWN_VIEW.limit = limit;
  if (!shown) {
    const spot = MARKDOWN_VIEW.spot;
    if (want)
      MARKDOWN_VIEW.spot = {
        doc,
        w: 0,
        top: 0,
        el: null,
        line: want.line,
        key: '',
        frac: 0,
        past: 0,
        off: want.off,
        sel: false,
        again: true,
      };
    else if (spot && spot.doc === doc && MARKDOWN_VIEW.shown === doc) {
      spot.el = null;
      spot.again = true;
    } else MARKDOWN_VIEW.spot = null;
  }
  return want;
}

/** Reset the live render context for its source, enabling math and counting elements from zero. */
function beginDocumentRender(): RenderContext {
  MARKDOWN_VIEW.els = 0;
  MARKDOWN_VIEW.marked = 0;
  MARKDOWN_VIEW.tex = 0;
  MARKDOWN_VIEW.bom = String(MARKDOWN_VIEW.lines[0] || '').charCodeAt(0) === 0xfeff;
  MARKDOWN_VIEW.heads = [];
  return MARKDOWN_VIEW;
}

/** Record the source line for the section strip and position button. */
function setReadingLine(line: number) {
  MARKDOWN_VIEW.at = line;
}

/** Record the hidden-character count in the source-line fallback. */
function setMarkedCharacterCount(count: number) {
  MARKDOWN_VIEW.marked = count;
}

/** Store the measured position for reflow, or clear it when the source is absent. */
function setReadingSpot(spot: MarkdownViewState['spot']) {
  MARKDOWN_VIEW.spot = spot;
}

/** Remember whether reflow should keep the selected lines in view. */
function setSpotSelectionVisible(visible: boolean) {
  if (MARKDOWN_VIEW.spot) MARKDOWN_VIEW.spot.sel = visible;
}

export {
  MARKDOWN_VIEW,
  MARKDOWN_LIMITS,
  renderContextOf,
  newRenderContext,
  keepRenderContext,
  beginMarkdownDraw,
  setShownDocument,
  forgetSourceStamp,
  recordOversizeSource,
  recordMarkdownSource,
  clearMarkdownHeadings,
  prepareMarkdownColumn,
  beginDocumentRender,
  setReadingLine,
  setMarkedCharacterCount,
  setReadingSpot,
  setSpotSelectionVisible,
};
export type { RenderContext };
