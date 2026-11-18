/** Build source-mapped elements and draw hidden characters within the render budget. */
import { MARKDOWN_LIMITS } from './state.ts';
import type { RenderContext } from './state.ts';
import { hiddenBox, ANY_HIDDEN, scanHidden, findHidden, markHiddenPlain } from '../platform/hidden-chars.ts';
import type { MarkdownToken } from './flow-parse.ts';

// ---------------- Drawing the document
// A yield to the browser between chunks of the DOM build: a message, not a timer, so a test's frozen clock does not
// stop it.
function yieldToBrowser() {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => resolve(undefined);
    channel.port2.postMessage(0);
  });
}
// One unit of work on counter work: true when MARKDOWN_LIMITS.chunk of them have been done since the last pause (and
// the count restarts).
function isPauseDue(work: { n: number }) {
  if (++work.n < MARKDOWN_LIMITS.chunk) return false;
  work.n = 0;
  return true;
}
const OVER_ELEMENT_LIMIT = { over: true }; // thrown by countedElement past MARKDOWN_LIMITS.elements
// One element of the drawn document, counted against MARKDOWN_LIMITS.elements on the draw's render context: the DOM
// class of its tag (countedElement('a', context) is an HTMLAnchorElement).
function countedElement<Tag extends keyof HTMLElementTagNameMap>(
  tag: Tag,
  context: RenderContext,
): HTMLElementTagNameMap[Tag] {
  if (++context.els > MARKDOWN_LIMITS.elements) throw OVER_ELEMENT_LIMIT;
  return document.createElement(tag);
}
// The same for a tag the source names (a block token's tag, any lowercase name): an HTML element, of its tag's class
// or HTMLUnknownElement; throws an Error for a name the document makes no HTML element of.
function countedTagElement(tag: string, context: RenderContext): HTMLElement {
  if (++context.els > MARKDOWN_LIMITS.elements) throw OVER_ELEMENT_LIMIT;
  const element: Element = document.createElement(tag);
  if (!(element instanceof HTMLElement)) throw new Error('countedTagElement: <' + tag + '> is no HTML element');
  return element;
}
// ---------------- Hidden characters in the drawn document (ADR-0029 D5, docs/handbook/viewer.md §숨은 문자)
// Every piece of the source's text the document draws - a paragraph's, a heading's, a list item's, a table cell's, a
// link's, inline and block code, a raw HTML placeholder's first line, an image's alt text - goes in through drawText,
// pausing with the rest of the build (drawTextNow only for the placeholder's first line, 120 characters at most): a
// character of platform/hidden-chars.ts's repertoire stays in the text - a selection, a copy and a pin's quote keep it
// - inside its box (hiddenBox), so no line reads in another order than its source; a box is two elements against
// MARKDOWN_LIMITS.elements (markedBox) and one unit of work (isPauseDue). A string with none of them, nearly every one,
// is one text node after one native test (isPlainText). The byte-order mark that starts the file is kept as on the text
// surface (isKeptInSequence's first): line 1 is then a paragraph (the mark is no indent, no '#', no '<'), so the mark
// is the first text drawn (the render context's bom). A marked character's box, counted on the draw's render context.
function markedBox(character: string, context: RenderContext): HTMLElement {
  if ((context.els += 2) > MARKDOWN_LIMITS.elements) throw OVER_ELEMENT_LIMIT;
  context.marked++;
  return hiddenBox(character);
}
// Whether text goes in as one text node: no character of the repertoire, nor a draw whose first text is still to come
// (context.bom).
function isPlainText(text: string, context: RenderContext) {
  return !context.bom && !ANY_HIDDEN.test(text);
}
// Text piece into parent, each marked character in its box, pausing (work: renderTokens's counter) after every
// MARKDOWN_LIMITS.chunk units; work null: no pause. context is the draw's render context.
function* drawText(
  parent: Node,
  piece: string,
  work: { n: number } | null,
  context: RenderContext,
): Generator<void, void, void> {
  const text = String(piece),
    first = context.bom && text.charCodeAt(0) === 0xfeff;
  context.bom = false;
  if (!ANY_HIDDEN.test(text)) {
    if (text) parent.appendChild(document.createTextNode(text));
    return;
  }
  let at = 0;
  for (const hidden of scanHidden(text, first)) {
    if (work && isPauseDue(work)) yield;
    if (!hidden) continue;
    if (hidden.at > at) parent.appendChild(document.createTextNode(text.slice(at, hidden.at)));
    parent.appendChild(markedBox(hidden.ch, context));
    at = hidden.at + hidden.ch.length;
  }
  if (at < text.length) parent.appendChild(document.createTextNode(text.slice(at)));
}
function drawTextNow(parent: Node, piece: string, context: RenderContext) {
  for (const pause of drawText(parent, piece, null, context)) void pause;
} // work null: it never pauses
// Text piece into parent once the document is drawn (an image's alt text when it fails), counted on the render context
// of the draw it is in (renderContextOf): boxes while MARKDOWN_LIMITS.elements holds them, else the names as plain text
// (markHiddenPlain).
function drawTextLate(parent: Node, piece: string, context: RenderContext) {
  if (context.els + 2 * findHidden(piece).length > MARKDOWN_LIMITS.elements) {
    parent.appendChild(document.createTextNode(markHiddenPlain(piece)));
    return;
  }
  drawTextNow(parent, piece, context);
}
function tokenAttribute(token: MarkdownToken, name: string): string | null {
  const attributes = (token && token.attrs) || [];
  for (const pair of attributes) if (pair[0] === name) return String(pair[1]);
  return null;
}
// The lines first..last of a block token's map, its trailing blank lines (of the render context's lines) left out (a
// loose list item's map runs over them).
function tokenLines(token: MarkdownToken, context: RenderContext): { lo: number; hi: number } | null {
  if (!token.map) return null;
  let first = token.map[0] + 1,
    last = Math.max(first, token.map[1]);
  while (last > first && !String(context.lines[last - 1] || '').trim()) last--;
  return { lo: first, hi: last };
}
function mapLines(element: HTMLElement, token: MarkdownToken, kind: string, context: RenderContext) {
  const lines = tokenLines(token, context);
  if (!lines) return;
  element.dataset.lo = String(lines.lo);
  element.dataset.hi = String(lines.hi);
  element.dataset.kind = kind;
}

export {
  OVER_ELEMENT_LIMIT,
  mapLines,
  countedElement,
  isPlainText,
  drawText,
  isPauseDue,
  yieldToBrowser,
  countedTagElement,
  tokenAttribute,
  tokenLines,
  drawTextNow,
  drawTextLate,
};
