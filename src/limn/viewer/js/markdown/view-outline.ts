/** Present the drawn document in the outline, section strip, position button and empty-list hint. */
import {
  setOutlineDoc,
  setOutlineBuild,
  setOutlineCut,
  setOutlineEntries,
  setOutlineSelected,
  renderOutline,
  OUTLINE_SELECTED,
  markOutline,
} from '../pdf/view-outline.ts';
import { DOC, META } from '../app/state.ts';
import { setReadingLine, MARKDOWN_VIEW } from './state.ts';
import { clipMarkedText } from '../platform/hidden-chars.ts';
import { $ } from '../platform/dom.ts';
import { lineElementAt, lineElements } from './view-reading.ts';
import { readingDepth } from '../pdf/view-page-jump.ts';
import { isMarkdownDoc, isTextDoc } from '../documents/state.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { drawPos } from '../documents/view-tabs.ts';
import { setHtml, html } from '../platform/markup.ts';

// ---------------- Outline from headings, the strip and the position button
// A heading as its outline row and the strip name it: plain text, its marked characters by name (clipMarkedText,
// platform/hidden-chars.ts), at most HEADING_CLIP characters - the row and the strip cut it to one line anyway, and the
// name never reads in another order.
const HEADING_CLIP = 120;
function drawOutline() {
  setOutlineDoc(DOC);
  setOutlineBuild((META && META.pages_build) || '');
  setOutlineCut(0);
  setOutlineEntries(
    MARKDOWN_VIEW.heads.map((heading, index) => ({
      title: clipMarkedText(heading.title, HEADING_CLIP),
      number: '',
      depth: Math.max(0, heading.level - 1),
      page: index + 1,
      pageLabel: 'L' + heading.lo,
      frac: 0,
      up: -1,
    })),
  );
  setOutlineSelected(-1);
  renderOutline();
}
// The source line at the reading line (readingDepth under the pane's top): the last line span or block, in document
// order, whose top is at or above it. 0 before the document is drawn.
function readingLine() {
  const pane = $('#left');
  if (!$('#md')) return 0;
  const element = lineElementAt(lineElements(), pane.getBoundingClientRect().top + readingDepth(pane));
  return element ? +(element.dataset.line || element.dataset.lo || 0) : 0;
}
// The section strip and the phone's position button (updateSectionStrip's branch): the heading above the reading line
// is the outline's current entry and the strip's title; the button reads [L<line>/<lines>].
function updateMarkdownStrip() {
  if (!isMarkdownDoc()) return;
  setReadingLine(readingLine());
  let index = -1;
  MARKDOWN_VIEW.heads.forEach((heading, at) => {
    if (heading.lo <= MARKDOWN_VIEW.at) index = at;
  });
  if (index !== OUTLINE_SELECTED) {
    setOutlineSelected(index);
    markOutline();
  }
  const heading = MARKDOWN_VIEW.heads[index];
  // the heading's title; a text document, which has no headings, its file name; above the first heading, the start
  $('#section-current').textContent = heading
    ? clipMarkedText(heading.title, HEADING_CLIP)
    : isTextDoc()
      ? clipMarkedText(MARKDOWN_VIEW.name, HEADING_CLIP)
      : translate('문서 처음');
  drawPos();
}
// posLabel's shape for this document: [L37/164 ▾] - the reading line's source line of the file's lines, '–' for what is
// not known yet - with the document's name as posLabel puts it. Pure but for translateTemplate.
function markdownPositionLabel(doc: string, line: number, lineCount: number, multi: boolean, wide: boolean) {
  const name = multi && wide ? doc : '',
    shownLine = line || '–',
    shownCount = lineCount || '–';
  return {
    name,
    pages: 'L' + shownLine + '/' + shownCount,
    label: name
      ? translateTemplate('이동 · {doc} · {line} / {lines}줄', { doc: name, line: shownLine, lines: shownCount })
      : translateTemplate('이동 · {line} / {lines}줄', { line: shownLine, lines: shownCount }),
  };
}
// The empty list's help (#empty) speaks of dragging on the PDF; this document gets its own words, and a PDF document
// the page's own back (kept as served).
let PDF_HINT_NODES: Node[] | null = null;
function showMarkdownHint() {
  const help = $('#empty');
  if (!help) return;
  if (!PDF_HINT_NODES) PDF_HINT_NODES = [...help.childNodes].map((node) => node.cloneNode(true));
  if (!isMarkdownDoc()) {
    if (help.dataset.md) {
      help.replaceChildren(...PDF_HINT_NODES.map((node) => node.cloneNode(true)));
      delete help.dataset.md;
    }
    return;
  }
  const want = isTextDoc() ? 'tx' : '1';
  if (help.dataset.md === want) return;
  help.dataset.md = want;
  if (want === 'tx') {
    showTextHint();
    return;
  } // a text document's own words (text/view.ts)
  setHtml(
    help,
    html`<span class="t-mouse">${translate('글을')} <b>${translate('끌어')}</b> ${translate('고르면 그 줄을,')} <b>${translate('블록을 누르면')}</b> ${translate('그 블록을 고르고')}</span><span class="t-touch"><b>${translate('블록을 누르면')}</b> ${translate('그 블록을,')} <b>${translate('길게 눌러')}</b> ${translate('글을 고르면 그 줄을 고르고')}</span> ${translate('그 자리의')} <b>${translate('원문 줄 번호')}</b>${translate('가 핀의 위치가 됩니다.')}<br>
    ${translate('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${translate('를 누르면 도움말.')}</span><span class="t-touch">${translate('도움말은 [더보기]에 있습니다.')}</span>`,
  );
}
// The empty list's help (#empty) for a text document: a line is picked by a press, lines by a drag.
function showTextHint() {
  const help = $('#empty');
  if (!help) return;
  setHtml(
    help,
    html`<span class="t-mouse"><b>${translate('줄을 누르면')}</b> ${translate('그 줄을,')} ${translate('글을')} <b>${translate('끌어')}</b> ${translate('고르면 그 줄들을 고르고')}</span><span class="t-touch"><b>${translate('줄을 누르면')}</b> ${translate('그 줄을,')} <b>${translate('길게 눌러')}</b> ${translate('글을 고르면 그 줄들을 고르고')}</span> ${translate('그 자리의')} <b>${translate('원문 줄 번호')}</b>${translate('가 핀의 위치가 됩니다.')}<br>
    ${translate('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${translate('를 누르면 도움말.')}</span><span class="t-touch">${translate('도움말은 [더보기]에 있습니다.')}</span>`,
  );
}

export { drawOutline, updateMarkdownStrip, markdownPositionLabel, showMarkdownHint };
