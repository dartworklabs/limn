// ------------------------------------------------ The text surface (docs/handbook/viewer.md §텍스트 화면, ADR-0029)
// A text document (showsSourceLines: kind "text" - plain text or source code) is drawn in the browser as the Markdown
// surface's documents are (md-surface.ts: GET /api/source, the reading spot, marks, badges, picks, the composer), but
// it is never parsed: every server line is one line span (data-line), numbered in the gutter by CSS, in a monospace
// column that wraps.
// - The DOM is built with createElement and textContent only, within the Markdown surface's limits (MARKDOWN_LIMITS):
//   over MARKDOWN_LIMITS.lines lines there is no view but its notice; the elements drawn - one per line, two per marked
//   character - stay under MARKDOWN_LIMITS.elements, and past it the view is the names view (each marked character's
//   name as plain text, one element per line); a yield to the browser after every MARKDOWN_LIMITS.chunk units of work
//   (a line, a character of the repertoire), within a long line too, and a newer draw (stale) drops the build at each
//   yield.
// - Nothing in the text is a link, an image or markup: it is only ever text.
// - A character that would hide or reorder text (the repertoire of hidden-chars.ts) stays in the text, so a copy keeps
//   it, inside an isolating span that shows its name (hiddenBox); a line of the view never reads in another order than
//   its source. A notice above the lines counts them. Another notice names the line ends the server split on that are
//   not LF or CRLF (/api/source line_ends): Limn numbers lines past them as str.splitlines() does, an editor that
//   counts LF alone does not.
// - A wrapped line's continuation hangs under its indentation, rounded down to a tab stop (hangColumns), so a tab lands
//   on the same stop as in an editor whose tabs are TAB_COLUMNS columns wide.
// - The ladder is: the chosen lines -> the paragraph between blank lines (para, or the paragraphs the lines meet:
//   blocks, saved as lines) -> the indented block the lines head or stand in (indent). textLevels reads the server's
//   lines alone.
import { MARKDOWN_LIMIT, META, showsSourceLines } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { hiddenBox, clipMarkedText, hiddenName, scanHidden } from '../platform/hidden-chars.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import {
  MARKDOWN_VIEW,
  MARKDOWN_LIMITS,
  formatCount,
  isPauseDue,
  lineSnippet,
  yieldToBrowser,
} from '../markdown/view.ts';
import { $ } from '../platform/dom.ts';
const TAB_COLUMNS = 4; // the columns a tab spans (CSS tab-size of the view, and indentColumns)
const MAX_HANG_COLUMNS = 16; // the most columns a wrapped line's continuation hangs: a phone keeps room for the text
const BLOCK_LABEL_CHARS = 12; // the most characters of a block's header its rung's label shows
// Whether the document on screen is a text document (shown line for line, never parsed).
function isTextDoc() {
  return !!META && showsSourceLines(META.kind);
}
// ---------------- Lines, columns and blocks: pure but for translateTemplate/translate
// The columns a line's leading whitespace spans, a tab to the next multiple of tab, or -1 for a blank line (only
// whitespace).
function indentColumns(line: string, tab?: number) {
  const tabWidth = tab || TAB_COLUMNS;
  let columns = 0;
  for (const character of String(line)) {
    if (character === ' ') columns++;
    else if (character === '\t') columns += tabWidth - (columns % tabWidth);
    else return columns;
  }
  return -1;
}
// How far a wrapped line's continuation hangs, in columns, at most MAX_HANG_COLUMNS: its indentation, rounded down to a
// tab stop when the line holds a tab - the first line then starts on a stop, so each tab lands where it does in an
// editor.
function hangColumns(line: string) {
  const columns = indentColumns(line);
  if (columns <= 0) return 0;
  return Math.min(MAX_HANG_COLUMNS, String(line).includes('\t') ? columns - (columns % TAB_COLUMNS) : columns);
}
// The paragraph of lines first..last (1-based, inclusive): the lines widened to the blank lines around them, and how
// many paragraphs - runs of non-blank lines - they meet. null when first..last holds only blank lines.
function paragraphAround(lines: string[], first: number, last: number) {
  const blank = (line: number) => !String(lines[line - 1] || '').trim();
  let start = first,
    end = last;
  while (start <= end && blank(start)) start++;
  while (end >= start && blank(end)) end--;
  if (start > end) return null;
  while (start > 1 && !blank(start - 1)) start--;
  while (end < lines.length && !blank(end + 1)) end++;
  let count = 0,
    inside = false;
  for (let k = start; k <= end; k++) {
    const isFilled = !blank(k);
    if (isFilled && !inside) count++;
    inside = isFilled;
  }
  return { lo: start, hi: end, n: count };
}
// A line that closes the block above it at the header's own depth, and so belongs to it: one that starts with a closing
// bracket ('}', ')', ']', as '} else {' or '});'), or whose statement is a closing word alone - a shell's fi, done or
// esac, Ruby's, Lua's, Julia's or MATLAB's end - followed by nothing, ';', ',', ')', a shell redirection or pipe ('done
// < list'), or a comment. A call or an assignment of a name spelt so ('done()', 'end = 3', 'done.append(x)') is no
// closer.
const BLOCK_CLOSER = /^(?:[\]\)}]|(?:end|fi|done|esac)\s*(?:$|[;,)<>|&]|#|--|%|\/\/))/;
// The indented block of lines first..last: the block they head when the next non-blank line below is deeper than they
// are, else the block they stand in, under the nearest line above that is shallower than they are. It runs from its
// header to the last line before the next non-blank line no deeper than the header, taking that line too when it closes
// the block (BLOCK_CLOSER), less trailing blank lines. {lo,hi,title} - title is the header's text - or null when no
// such header is found (an unindented paragraph of prose, a file's top level).
function indentBlockAround(lines: string[], first: number, last: number) {
  const indentOf = (line: number) => indentColumns(String(lines[line - 1] || ''));
  let shallowest = Infinity;
  for (let k = first; k <= last; k++) {
    const columns = indentOf(k);
    if (columns >= 0 && columns < shallowest) shallowest = columns;
  }
  if (shallowest === Infinity) return null;
  let next = last + 1;
  while (next <= lines.length && indentOf(next) < 0) next++;
  let header = -1;
  if (next <= lines.length && indentOf(next) > shallowest && indentOf(first) === shallowest)
    header = first; // the lines head a deeper body
  else
    for (let k = first - 1; k >= 1; k--) {
      const columns = indentOf(k);
      if (columns >= 0 && columns < shallowest) {
        header = k;
        break;
      }
    } // the lines stand in the block of a shallower line above
  if (header < 0) return null;
  const headerColumns = indentOf(header);
  let end = lines.length;
  for (let k = Math.max(last, header) + 1; k <= lines.length; k++) {
    const columns = indentOf(k);
    if (columns >= 0 && columns <= headerColumns) {
      end = columns === headerColumns && BLOCK_CLOSER.test(String(lines[k - 1]).trim()) ? k : k - 1;
      break;
    }
  }
  while (end > header && indentOf(end) < 0) end--;
  if (end < last) end = last;
  return { lo: header, hi: end, title: String(lines[header - 1] || '').trim() };
}
// The ladder for lines range of the text on screen: the chosen lines, then their paragraph (or the paragraphs they
// meet, saved as lines) and their indented block, the shorter of the two first; a rung with the range of one before it
// merges into that one (as markdownLevels does). Array.prototype.sort is stable, so rungs of one length keep that
// order.
function textLevels(range: { lo: number; hi: number }) {
  const rungs = [] as any[],
    lines = MARKDOWN_VIEW.lines;
  const add = (level: string, label: string, first: number, last: number, tip: string | null) => {
    const same = rungs.find((rung) => rung.lo === first && rung.hi === last);
    if (same) {
      (same.merged = same.merged || []).push(level);
      return;
    }
    rungs.push({
      level,
      label,
      lo: first,
      hi: last,
      n: last - first + 1,
      snippet: lineSnippet(first, last),
      env: null,
      tip,
    });
  };
  add('raw', '고른 줄', range.lo, range.hi, null);
  const paragraph = paragraphAround(lines, range.lo, range.hi);
  if (paragraph && paragraph.n > 1)
    add('blocks', translateTemplate('문단 {n}개', { n: paragraph.n }), paragraph.lo, paragraph.hi, 'txparas');
  // TIP_TEXT.txpara: a text document's paragraph has no % comment rule
  else if (paragraph) add('para', '문단', paragraph.lo, paragraph.hi, 'txpara');
  const block = indentBlockAround(lines, range.lo, range.hi);
  // the header's hidden characters by name (clipMarkedText)
  if (block)
    add(
      'indent',
      translate('블록') + ' · ' + clipMarkedText(block.title, BLOCK_LABEL_CHARS),
      Math.min(block.lo, range.lo),
      Math.max(block.hi, range.hi),
      null,
    );
  const [raw, ...wider] = rungs;
  wider.sort((left, right) => left.n - right.n);
  return [raw, ...wider];
}
// ---------------- Drawing
// The span of line number line (text its text): the hang of its continuation (hangColumns) through CSSOM, no text yet.
function textLineSpan(text: string, line: number) {
  const span = document.createElement('span');
  span.className = 'ln';
  span.dataset.line = String(line);
  const hang = hangColumns(text);
  if (hang) span.style.setProperty('--hang', String(hang));
  return span;
}
// Builds article#md for the text document on screen from MARKDOWN_VIEW.lines (srcLines): each line's text, each marked
// character in its box (hiddenBox), the text ending in "\n" so that a selection's text keeps its line ends. Within
// MARKDOWN_LIMITS (the header above): past MARKDOWN_LIMITS.elements it gives the names view instead; null when a newer
// draw came (stale) at a yield. ends: /api/source's line_ends.
async function buildTextView(
  stale: () => boolean,
  ends: Record<string, number> | undefined,
): Promise<HTMLElement | null> {
  const drawn = await srcLines(textLineSpan, 'tx-src', stale);
  if (!drawn) return null;
  if (drawn.names) return textArticle(drawn.body, ends, namesViewText(drawn.marked), MARKDOWN_LIMIT.ELEMENTS);
  return textArticle(drawn.body, ends, drawn.marked ? markedCharactersText(drawn.marked) : '', null);
}
// The source lines on screen (MARKDOWN_VIEW.lines) as line spans in a new div of class className - span(text, line)
// makes the empty span of line number line - for the text surface (buildTextView) and the Markdown surface's line view
// (lineView). Each marked character (hidden-chars.ts) is its box (hiddenBox) while the elements drawn stay within
// MARKDOWN_LIMITS.elements: one a line, two a box, counted on every line, not only on a box (plain lines after a line
// of boxes). Past it, the names form: each line one span whose text has every marked character as its name in angle
// brackets ('⟨U+200B⟩', markHiddenPlain's form) - one element a line, never a raw character that reorders the line; a
// copy of it gives the names, not the characters (namesViewText says so). A yield to the browser after every
// MARKDOWN_LIMITS.chunk units of work (a line, a character of the repertoire), within a long line too. -> {body, marked
// (how many characters it marked), names (the names form)}, or null when a newer draw came (stale) at a yield. The
// names form has no limit to pass, so the loop always returns from it.
async function srcLines(
  span: (text: string, line: number) => HTMLElement,
  className: string,
  stale: () => boolean,
): Promise<{ body: HTMLElement; marked: number; names: boolean } | null> {
  const lines = MARKDOWN_VIEW.lines,
    work = { n: 0 };
  for (const names of [false, true]) {
    const body = document.createElement('div');
    body.className = className;
    let elements = 0,
      marked = 0,
      over = false;
    for (let i = 0; i < lines.length && !over; i++) {
      const text = lines[i],
        lineSpan = span(text, i + 1);
      let at = 0,
        out = '';
      if (!names && ++elements > MARKDOWN_LIMITS.elements) {
        over = true;
        break;
      }
      for (const hidden of scanHidden(text, i === 0)) {
        if (isPauseDue(work)) {
          await yieldToBrowser();
          if (stale()) return null;
        }
        if (!hidden) continue;
        if (names) out += text.slice(at, hidden.at) + '\u27e8' + hiddenName(hidden.ch.codePointAt(0) || 0) + '\u27e9';
        else {
          if ((elements += 2) > MARKDOWN_LIMITS.elements) {
            over = true;
            break;
          }
          if (hidden.at > at) lineSpan.append(text.slice(at, hidden.at));
          lineSpan.append(hiddenBox(hidden.ch));
        }
        at = hidden.at + hidden.ch.length;
        marked++;
      }
      if (over) break;
      if (names) lineSpan.textContent = out + text.slice(at) + '\n';
      else lineSpan.append(text.slice(at) + '\n');
      body.appendChild(lineSpan);
      if (isPauseDue(work)) {
        await yieldToBrowser();
        if (stale()) return null;
      }
    }
    if (!over) return { body, marked, names };
  }
  return null;
}
// What the notice above the lines says of the characters marked: count boxes, or the names form for count of them.
function markedCharactersText(count: number) {
  return translateTemplate('보이지 않거나 글 순서를 바꾸는 문자 {n}개를 이름으로 표시했습니다', {
    n: formatCount(count),
  });
}
function namesViewText(count: number) {
  return translateTemplate(
    '보이지 않거나 글 순서를 바꾸는 문자가 {n}개라 이름을 글자로 보입니다(그릴 요소 한도 {max}개). 이 보기에서 복사하면 그 문자 대신 이름이 복사됩니다',
    { n: formatCount(count), max: formatCount(MARKDOWN_LIMITS.elements) },
  );
}
// A notice above a document's text (kind: its data-note - 'marks', 'ends'): out of the text, never selected or copied
// with it, in the viewer's words and so in the screen's language. A Markdown document's notice is the same element
// (renderDocument, lineView).
function textNotice(kind: string, text: string) {
  const notice = document.createElement('div');
  notice.className = 'md-limit tx-note';
  notice.dataset.note = kind;
  notice.setAttribute('role', 'status');
  notice.textContent = text;
  notice.lang = document.documentElement.lang;
  return notice;
}
// article#md round the lines (body): the notices above them - what was marked (marks, '' for none) and the line ends
// that are not LF or CRLF (lineEndsText) - and the limit the view hit (limit, its data-limit; null for none).
function textArticle(body: HTMLElement, ends: Record<string, number> | undefined, marks: string, limit: string | null) {
  const root = document.createElement('article');
  root.className = 'md tx';
  root.id = 'md';
  root.setAttribute('translate', 'no');
  root.lang = ''; // the text's language is not known, as for renderDocument's article
  if (limit) root.dataset.limit = limit;
  root.style.setProperty('--gut', String(String(MARKDOWN_VIEW.lines.length).length + 1));
  for (const [kind, text] of [
    ['marks', marks],
    ['ends', lineEndsText(ends)],
  ])
    if (text) root.appendChild(textNotice(kind, text));
  root.appendChild(body);
  return root;
}
// The notice for the line ends of the source that are not LF or CRLF (ends: {name: count}, /api/source line_ends -
// 'U+000C', 'U+2028', a lone CR as 'U+000D'), or '' when there are none. Limn numbers lines past them; an editor or git
// that counts LF alone does not, and a copy joins the lines with LF.
function lineEndsText(ends: Record<string, number> | undefined) {
  const oddEnds = Object.entries(ends || {}).filter(
    ([name, count]) => /^U\+[0-9A-F]{4,6}$/.test(name) && Number(count) > 0,
  );
  if (!oddEnds.length) return '';
  const total = oddEnds.reduce((sum, [, count]) => sum + Number(count), 0);
  return translateTemplate(
    '줄 끝 {n}곳이 LF가 아닙니다({kinds}). Limn은 거기서 줄을 나누므로, 줄 번호가 LF만 세는 편집기·git과 다를 수 있고 복사하면 LF로 바뀝니다',
    { n: formatCount(total), kinds: oddEnds.map(([name, count]) => name + ' ' + formatCount(count)).join(', ') },
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
export {
  isTextDoc,
  srcLines,
  showTextHint,
  textLevels,
  markedCharactersText,
  namesViewText,
  textNotice,
  buildTextView,
};
