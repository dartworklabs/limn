/** Read and display the current Markdown or text document in the shared column (ADR-0025).
 * The server supplies the numbered source lines. Markdown parsing and drawing can yield or fall back to plain lines.
 * A draw publishes only during the visit that requested it, and waits while an input method owns a field in the column.
 */
import { listenToMarkdownNavigation } from './input-navigation.ts';
import { listenToMarkdownSelection } from './input-selection.ts';
import { imeHeldIn, IME_ON_FREE, DOC } from '../app/state.ts';
import { $ } from '../platform/dom.ts';
import {
  beginMarkdownDraw,
  setShownDocument,
  forgetSourceStamp,
  recordOversizeSource,
  recordMarkdownSource,
  clearMarkdownHeadings,
  prepareMarkdownColumn,
  MARKDOWN_VIEW,
  MARKDOWN_LIMITS,
} from './state.ts';
import { isMarkdownDoc, withDocQuery, isTextDoc } from '../documents/state.ts';
import { waitLine, documentNotice, formatMebibytes, formatCount, lineView } from './view-source.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { api, isRefusal } from '../platform/api.ts';
import { MARKDOWN_LIMIT } from '../app/rules-tables.ts';
import { textSurface, lineMarks } from './state-seams.ts';
import { compareRedrawnSource, tintChangedLines } from '../documents/flow-updates.ts';
import { parseMarkdown } from './flow-parse.ts';
import type { MarkdownParse } from './flow-parse.ts';
import { hasMath, loadTexRenderer, fitWideFormulas } from './view-math.ts';
import { renderDocument } from './view-blocks.ts';
import { isColumnShown, readingAnchor, restoreReadingAnchor, readSpot, keepReadingSpot } from './view-reading.ts';
import { drawOutline, updateMarkdownStrip } from './view-outline.ts';
import { relevelForLineView } from './flow-pick.ts';
import { markChosenLines, shownChoice, finishPendingPinJump, drawPinMarks } from './view-marks.ts';
import { finishPendingHeading } from './flow-links.ts';

let MARKDOWN_DRAW_WAITING = false;
// Whether a redraw would take a text field from under the person typing in it: a field inside #doc that is composing,
// or held by the key that ended its composition (imeHeldIn, app/state.ts §조합을 끝내는 키).
function isFieldBusy() {
  const active = document.activeElement,
    held = imeHeldIn();
  const doc = $('#doc'),
    inDoc = (node: unknown) => node instanceof Node && doc.contains(node);
  return inDoc(held) || (!!active && inDoc(active) && active !== doc && COMPOSING_FIELDS.has(active));
}
const COMPOSING_FIELDS = new Set<EventTarget | null>();
document.addEventListener(
  'compositionstart',
  (event) => {
    COMPOSING_FIELDS.add(event.target);
  },
  true,
);
document.addEventListener(
  'compositionend',
  (event) => {
    COMPOSING_FIELDS.delete(event.target);
  },
  true,
);
// Once that key lets its field go (IME_ON_FREE), a redraw that waited for it runs.
IME_ON_FREE.push(() => {
  if (MARKDOWN_DRAW_WAITING && !isFieldBusy()) {
    MARKDOWN_DRAW_WAITING = false;
    if (isMarkdownDoc()) buildMarkdownDoc();
  }
});
document.addEventListener('compositionend', () => {
  if (MARKDOWN_DRAW_WAITING)
    setTimeout(() => {
      if (MARKDOWN_DRAW_WAITING && !isFieldBusy()) {
        MARKDOWN_DRAW_WAITING = false;
        if (isMarkdownDoc()) buildMarkdownDoc();
      }
    }, 0);
});
// Draws the document on screen into #doc (buildDoc's branch for a browser-drawn document): its source, parsed in the
// worker and built here, or the line view or a notice when a limit is hit. A newer draw (another document, newer
// source) drops an older one at each wait. A redraw that would take a field being typed in waits until the field is let
// go (isFieldBusy).
async function buildMarkdownDoc() {
  if (isFieldBusy()) {
    MARKDOWN_DRAW_WAITING = true;
    return;
  }
  const generation = beginMarkdownDraw(),
    docKey = DOC,
    stale = () => generation !== MARKDOWN_VIEW.gen || docKey !== DOC || !isMarkdownDoc();
  document.body.classList.add('md-surface');
  const doc = $('#doc');
  if (MARKDOWN_VIEW.shown !== docKey || !doc.querySelector('#md')) {
    setShownDocument('');
    doc.replaceChildren(waitLine(translate('원문을 읽는 중입니다.')));
  }
  let answer;
  try {
    answer = await api('GET /api/source', { query: withDocQuery(''), what: '원문 읽기', silent: true, expect: [413] });
  } catch (error) {
    if (!stale()) {
      forgetSourceStamp();
      showDocumentNode(documentNotice(translate('원문을 읽지 못했습니다'), ''));
    }
    return;
  }
  if (stale()) return;
  if (isRefusal(answer.data)) {
    recordOversizeSource();
    showDocumentNode(
      documentNotice(
        translateTemplate('이 문서는 {size}라 그리지 않습니다(한도 {limit})', {
          size: formatMebibytes(answer.data.bytes),
          limit: formatMebibytes(answer.data.limit),
        }),
        MARKDOWN_LIMIT.BYTES,
      ),
    );
    return;
  }
  const source = answer.data,
    before = recordMarkdownSource(docKey, source);
  if (isTextDoc()) {
    clearMarkdownHeadings(); // a text document is never parsed: its lines are its view (text/view.ts)
    if (MARKDOWN_VIEW.lines.length > MARKDOWN_LIMITS.lines) {
      showDocumentNode(
        documentNotice(
          translateTemplate('이 문서는 원문이 {lines}줄이라 그리지 않습니다(한도 {limit}줄)', {
            lines: formatCount(MARKDOWN_VIEW.lines.length),
            limit: formatCount(MARKDOWN_LIMITS.lines),
          }),
          MARKDOWN_LIMIT.LINES,
        ),
      );
      return;
    }
    const view = await textSurface().build(stale, source.line_ends);
    if (view && !stale()) {
      showDocumentNode(view);
      compareRedrawnSource(docKey || '', before, MARKDOWN_VIEW.lines);
    }
    return;
  }
  // A NUL (U+0000) is not parsed: markdown-it turns it into U+FFFD (CommonMark's rule) and its tokens keep no column to
  // put it back by, so the document would read another character than its source has. The line view keeps it, in its
  // box.
  const parsed: MarkdownParse | null = MARKDOWN_VIEW.lines.some((line) => line.includes('\0'))
    ? { ok: false, limit: MARKDOWN_LIMIT.NUL }
    : await parseMarkdown(MARKDOWN_VIEW.lines.join('\n'));
  if (stale() || !parsed) return;
  let root: HTMLElement | null = null,
    limit = parsed.ok ? null : String(parsed.limit || MARKDOWN_LIMIT.ERROR);
  // The TeX renderer is fetched before the build, which is synchronous once it starts (drawTexBox): only a document
  // whose tokens hold math asks for it, and a document that does not get it draws its math as characters (ADR-0036 D1,
  // D2).
  if (parsed.ok && hasMath(parsed.tokens)) {
    await loadTexRenderer();
    if (stale()) return;
  }
  if (parsed.ok) {
    root = await renderDocument(parsed.tokens, stale);
    if (stale()) return;
    if (!root) limit = MARKDOWN_LIMIT.ELEMENTS;
  }
  if (!root) {
    clearMarkdownHeadings();
    if (MARKDOWN_VIEW.lines.length > MARKDOWN_LIMITS.lines) {
      showDocumentNode(
        documentNotice(
          translateTemplate('이 문서는 원문이 {lines}줄이라 그리지 않습니다(한도 {limit}줄)', {
            lines: formatCount(MARKDOWN_VIEW.lines.length),
            limit: formatCount(MARKDOWN_LIMITS.lines),
          }),
          MARKDOWN_LIMIT.LINES,
        ),
      );
      return;
    }
    root = await lineView(limit ?? MARKDOWN_LIMIT.ERROR, stale); // limit is set whenever no root was drawn
    if (!root || stale()) return;
  }
  showDocumentNode(root);
  compareRedrawnSource(docKey || '', before, MARKDOWN_VIEW.lines);
}
// Puts node in #doc, keeping the reading spot (the source line at the pane's top, and how far down it), then the marks,
// the outline, the strip and the chosen lines. While the column is hidden (under the changes view) nothing can be
// measured: the spot read before it was hidden (MARKDOWN_VIEW.spot, or the view a return asks for) is kept as its line
// and marked to be put back on that line's new element once the column is shown, at whatever width (keepReadingSpot).
function showDocumentNode(node: HTMLElement) {
  const shown = isColumnShown(),
    want = prepareMarkdownColumn(DOC, node.dataset.limit || null, shown),
    anchor = shown ? want || (MARKDOWN_VIEW.shown === DOC ? readingAnchor() : null) : null;
  $('#doc').replaceChildren(node);
  setShownDocument(DOC);
  fitWideFormulas();
  restoreReadingAnchor(anchor);
  if (COLUMN_OBSERVER) COLUMN_OBSERVER.observe(node);
  drawOutline();
  lineMarks().draw();
  relevelForLineView();
  markChosenLines(shownChoice());
  updateMarkdownStrip();
  readSpot(true);
  tintChangedLines();
  finishPendingPinJump();
  finishPendingHeading();
}
// The column reflows when its width changes (a panel, a rotation): the reading spot comes back at once, before the
// paint (keepReadingSpot), and the badges follow their lines.
let MARK_REDRAW_TIMER = 0;
const COLUMN_OBSERVER = window.ResizeObserver
  ? new ResizeObserver(() => {
      keepReadingSpot();
      clearTimeout(MARK_REDRAW_TIMER);
      MARK_REDRAW_TIMER = setTimeout(() => {
        if (isMarkdownDoc()) {
          fitWideFormulas();
          drawPinMarks();
        }
      }, 120);
    })
  : null;

listenToMarkdownNavigation();
listenToMarkdownSelection();

export { buildMarkdownDoc };
