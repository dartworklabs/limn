/** Draw numbered source lines and explain drawing limits for Markdown and text documents. */
import { setMarkedCharacterCount, MARKDOWN_VIEW, MARKDOWN_LIMITS } from './state.ts';
import { MARKDOWN_LIMIT } from '../app/rules-tables.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { scanHidden, hiddenName, hiddenBox } from '../platform/hidden-chars.ts';
import { isPauseDue, yieldToBrowser } from './view-elements.ts';

function waitLine(text: string) {
  const line = document.createElement('div');
  line.className = 'md-wait dim';
  line.textContent = text;
  return line;
}
// A notice in the document's place (a limit hit before anything could be drawn, or a source not read): data-limit names
// the limit.
function documentNotice(text: string, limit: string) {
  const notice = document.createElement('div');
  notice.className = 'md-note';
  notice.id = 'md';
  notice.setAttribute('role', 'status');
  notice.textContent = text;
  if (limit) notice.dataset.limit = limit;
  return notice;
}
// A size in MiB as the notices say it: '1.5 MiB', '1 MiB'.
function formatMebibytes(bytes: number) {
  const mebibytes = (+bytes || 0) / 1048576;
  return (Math.round(mebibytes * 10) / 10).toLocaleString('en') + ' MiB';
}
function formatCount(count: number) {
  return Number(count).toLocaleString('en');
}
// The plain source-line view: every server line as a line span (data-line), numbered by CSS, under a line naming the
// limit that was hit - each marked character in its box, or past MARKDOWN_LIMITS.elements every one by its name
// (srcLines, as the text surface draws its lines), with the notice that says which. Pins, the composer and suggested
// edits work as ever; the ladder has the chosen lines only. null when a newer draw came (stale) while it was built.
async function lineView(limit: string, stale: () => boolean): Promise<HTMLElement | null> {
  const drawn = await srcLines(lineViewSpan, 'md-src', stale);
  if (!drawn) return null;
  const root = document.createElement('article');
  root.className = 'md md-lines';
  root.id = 'md';
  root.dataset.limit = limit;
  root.setAttribute('translate', 'no');
  root.lang = ''; // as renderDocument's
  const head = document.createElement('div');
  head.className = 'md-limit';
  head.setAttribute('role', 'status');
  head.textContent = limitText(limit);
  head.lang = document.documentElement.lang;
  root.appendChild(head); // the viewer's words, in the screen's language
  setMarkedCharacterCount(drawn.marked);
  if (drawn.marked)
    root.appendChild(
      textNotice('marks', drawn.names ? namesViewText(drawn.marked) : markedCharactersText(drawn.marked)),
    );
  root.appendChild(drawn.body);
  return root;
}
// The line view's empty span of a line (srcLines fills it).
function lineViewSpan(text: string, line: number) {
  const span = document.createElement('span');
  span.className = 'ln';
  span.dataset.line = String(line);
  return span;
}
// The line view's head line for limit (MARKDOWN_LIMIT).
function limitText(limit: string) {
  switch (limit) {
    case MARKDOWN_LIMIT.NESTING:
      return translateTemplate('중첩이 {max}단을 넘어 원문 줄로 보입니다', { max: MARKDOWN_LIMITS.nesting });
    case MARKDOWN_LIMIT.BLOCKS:
      return translateTemplate('블록이 너무 많아 원문 줄로 보입니다(한도 {max}개)', {
        max: formatCount(MARKDOWN_LIMITS.blocks),
      });
    case MARKDOWN_LIMIT.INLINES:
      return translateTemplate('글 조각이 너무 많아 원문 줄로 보입니다(한도 {max}개)', {
        max: formatCount(MARKDOWN_LIMITS.inlines),
      });
    case MARKDOWN_LIMIT.ELEMENTS:
      return translateTemplate('그릴 요소가 너무 많아 원문 줄로 보입니다(한도 {max}개)', {
        max: formatCount(MARKDOWN_LIMITS.elements),
      });
    case MARKDOWN_LIMIT.TIME:
      return translateTemplate('읽는 데 {s}초가 넘게 걸려 원문 줄로 보입니다', { s: MARKDOWN_LIMITS.ms / 1000 });
    case MARKDOWN_LIMIT.LOAD:
      return translate('Markdown 파서를 불러오지 못해 원문 줄로 보입니다');
    case MARKDOWN_LIMIT.NUL:
      return translate(
        '원문에 NUL 문자(U+0000)가 있어 원문 줄로 보입니다. Markdown으로 그리면 그 문자가 U+FFFD로 바뀝니다',
      );
    default:
      return translate('Markdown을 읽지 못해 원문 줄로 보입니다');
  }
}
// The source lines on screen (MARKDOWN_VIEW.lines) as line spans in a new div of class className - span(text, line)
// makes the empty span of line number line - for the text surface (buildTextView) and the Markdown surface's line view
// (lineView). Each marked character (platform/hidden-chars.ts) is its box (hiddenBox) while the elements drawn stay
// within MARKDOWN_LIMITS.elements: one a line, two a box, counted on every line, not only on a box (plain lines after a
// line of boxes). Past it, the names form: each line one span whose text has every marked character as its name in
// angle brackets ('⟨U+200B⟩', markHiddenPlain's form) - one element a line, never a raw character that reorders the
// line; a copy of it gives the names, not the characters (namesViewText says so). A yield to the browser after every
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

export {
  waitLine,
  documentNotice,
  formatMebibytes,
  formatCount,
  lineView,
  textNotice,
  markedCharactersText,
  limitText,
  srcLines,
  namesViewText,
};
