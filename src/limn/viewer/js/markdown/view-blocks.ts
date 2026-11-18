/** Build the block hierarchy from parser tokens, yielding as the document or comparison grows. */
import type { MarkdownToken } from './flow-parse.ts';
import { beginDocumentRender } from './state.ts';
import type { RenderContext } from './state.ts';
import {
  yieldToBrowser,
  OVER_ELEMENT_LIMIT,
  isPauseDue,
  countedTagElement,
  mapLines,
  tokenAttribute,
  countedElement,
  isPlainText,
  drawText,
  tokenLines,
} from './view-elements.ts';
import { textNotice, markedCharactersText } from './view-source.ts';
import { drawInline } from './view-inline.ts';
import { drawMathBlock } from './view-math.ts';
import { htmlPlaceholder, htmlRunElement, holdHtmlLines } from './view-html.ts';
import { findElement } from '../platform/dom.ts';
import { translateTemplate } from '../platform/i18n.ts';

// Builds article#md from the worker's tokens (renderTokens, with MARKDOWN_VIEW as its render context), with a yield to
// the browser and a check for a newer draw whenever renderTokens pauses, or null when the elements built pass
// MARKDOWN_LIMITS.elements (stale(): a newer draw - then whatever was built is dropped too).
async function renderDocument(tokens: MarkdownToken[], stale: () => boolean): Promise<HTMLElement | null> {
  const root = document.createElement('article');
  root.className = 'md';
  root.id = 'md';
  root.setAttribute('translate', 'no');
  // the document's language is not known (docs/handbook/viewer.md §그리기): not the screen's (<html lang>)
  root.lang = '';
  const context = beginDocumentRender(),
    work = renderTokens(root, tokens, context);
  try {
    for (const pause of work) {
      void pause;
      await yieldToBrowser();
      if (stale()) return null;
    }
  } catch (error) {
    if (error === OVER_ELEMENT_LIMIT) return null;
    throw error;
  }
  // the text surface's notice (text/view.ts), above the first block
  if (context.marked) root.prepend(textNotice('marks', markedCharactersText(context.marked)));
  return root;
}
// The DOM build as a generator that pauses after every MARKDOWN_LIMITS.chunk units of work - a token, an inline child,
// a code line, one block of a raw HTML run - counted on one counter (work, isPauseDue) wherever they fall: one
// paragraph of 120,000 inline tokens or one code block of 30,000 lines pauses inside itself. Two or more raw HTML
// blocks in a row are one run (htmlRunElement). context is the draw's render context (RenderContext): its lines, its
// element count, its marked characters and its headings.
function* renderTokens(
  root: HTMLElement,
  tokens: MarkdownToken[],
  context: RenderContext,
): Generator<void, void, void> {
  const renderer = makeRenderer(root, context),
    work = { n: 0 };
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    let last = i;
    while (token.type === 'html_block' && tokens[last + 1] && tokens[last + 1].type === 'html_block') last++;
    if (last > i) {
      yield* renderer.run(tokens.slice(i, last + 1), work);
      i = last;
    } else yield* renderer.token(token, work);
    if (isPauseDue(work)) yield;
  }
}
const BLOCK_KIND: Record<string, string> = {
  paragraph_open: 'paragraph',
  heading_open: 'heading',
  bullet_list_open: 'list',
  ordered_list_open: 'list',
  list_item_open: 'item',
  blockquote_open: 'quote',
  table_open: 'table',
  tr_open: 'row',
};
// A renderer into root for markdown-it's token stream, one token at a time: block tokens nest by `nesting`, an inline
// token's children are drawn by drawInline. A paragraph markdown-it hides (a tight list's) puts its text straight into
// the list item.
function makeRenderer(root: HTMLElement, context: RenderContext) {
  const stack = [root];
  function* token(markdownToken: MarkdownToken, work: { n: number }): Generator<void, void, void> {
    const top = stack[stack.length - 1];
    if (markdownToken.nesting === 1) {
      if (markdownToken.hidden) {
        stack.push(top);
        return;
      }
      const tag = /^[a-z][a-z0-9]*$/.test(markdownToken.tag || '') ? markdownToken.tag : 'div',
        element = countedTagElement(tag, context),
        kind = BLOCK_KIND[markdownToken.type];
      if (kind) mapLines(element, markdownToken, kind, context);
      if (markdownToken.type === 'ordered_list_open') {
        const start = tokenAttribute(markdownToken, 'start');
        if (start && /^\d{1,9}$/.test(start)) element.setAttribute('start', start);
      }
      if (markdownToken.type === 'th_open' || markdownToken.type === 'td_open') {
        const align = /^text-align:(left|right|center)$/.exec(tokenAttribute(markdownToken, 'style') || '');
        if (align) element.classList.add('md-al-' + align[1]);
      }
      if (markdownToken.type === 'heading_open' && markdownToken.map) {
        element.id = 'md-h' + (markdownToken.map[0] + 1);
        context.heads.push({
          level: +tag.slice(1) || 1,
          lo: markdownToken.map[0] + 1,
          el: element,
          title: '',
          slug: '',
        });
      }
      top.appendChild(element);
      stack.push(element);
      return;
    }
    if (markdownToken.nesting === -1) {
      if (stack.length > 1) stack.pop();
      return;
    }
    if (markdownToken.type === 'inline') {
      yield* drawInline(markdownToken, top, work, context);
      const heading = context.heads[context.heads.length - 1];
      if (heading && heading.el === top) {
        heading.title = (top.textContent || '').trim();
        heading.slug = headingSlug(heading.title);
      }
      if (top.tagName === 'P' && top.querySelectorAll('.md-pic').length === 1 && !(top.textContent || '').trim())
        top.classList.add('md-fig'); // a paragraph that is one image
      return;
    }
    if (markdownToken.type === 'fence' || markdownToken.type === 'code_block') {
      const pre = countedElement('pre', context),
        code = countedElement('code', context);
      mapLines(pre, markdownToken, 'code', context);
      const lang = String(markdownToken.info || '')
        .trim()
        .split(/\s+/)[0];
      if (lang) pre.dataset.lang = lang.slice(0, 40);
      const first = markdownToken.map ? markdownToken.map[0] + 1 + (markdownToken.type === 'fence' ? 1 : 0) : 0;
      pre.appendChild(code);
      top.appendChild(pre);
      const lines = markdownToken.content ? String(markdownToken.content).replace(/\n$/, '').split('\n') : [];
      for (let i = 0; i < lines.length; i++) {
        const span = countedElement('span', context),
          text = lines[i];
        span.className = 'ln';
        if (first) span.dataset.line = String(first + i);
        if (isPlainText(text, context)) span.textContent = text + '\n';
        else {
          yield* drawText(span, text, work, context);
          span.appendChild(document.createTextNode('\n'));
        }
        code.appendChild(span);
        if (isPauseDue(work)) yield;
      }
      return;
    }
    if (markdownToken.type === 'hr') {
      const rule = countedElement('hr', context);
      mapLines(rule, markdownToken, 'rule', context);
      top.appendChild(rule);
      return;
    }
    if (markdownToken.type === 'front_matter') {
      yield* drawFrontMatter(markdownToken, top, work, context);
      return;
    }
    if (markdownToken.type === 'math_block') {
      yield* drawMathBlock(markdownToken, top, work, context);
      return;
    }
    if (markdownToken.type === 'html_block') top.appendChild(htmlPlaceholder(markdownToken, context));
  }
  // A run of raw HTML blocks in a row (htmlRunElement), or each block on its own when one has no lines.
  function* run(tokens: MarkdownToken[], work: { n: number }): Generator<void, void, void> {
    const spans = tokens.map((htmlToken) => tokenLines(htmlToken, context)),
      first = spans[0],
      last = spans[spans.length - 1];
    if (!first || !last || spans.some((span) => !span)) {
      for (const htmlToken of tokens) {
        yield* token(htmlToken, work);
        if (isPauseDue(work)) yield;
      }
      return;
    }
    const runElement = htmlRunElement(tokens.length, first.lo, last.hi, context),
      body = findElement(runElement, ':scope>.md-html-body', HTMLElement);
    stack[stack.length - 1].appendChild(runElement);
    for (const htmlToken of tokens) {
      const placeholder = htmlPlaceholder(htmlToken, context);
      holdHtmlLines(placeholder, false);
      body.appendChild(placeholder);
      if (isPauseDue(work)) yield;
    }
  }
  return { token, run };
}
// YAML front matter (the worker's front_matter token, mdFrontMatter in md-parse.mjs; ADR-0032): a box that carries the
// block's lines, both '---' lines included (data-lo..hi, kind front - a block of its own, md:front), a head line in the
// screen's language naming it, and its inner lines one span each (data-line) in a code box. The lines are the server's
// (context.lines), drawn as text: YAML is never parsed, so nothing in it links, loads or is markup. It is no heading:
// the outline, the strip and the sections skip it.
function* drawFrontMatter(
  token: MarkdownToken,
  top: HTMLElement,
  work: { n: number },
  context: RenderContext,
): Generator<void, void, void> {
  const box = countedElement('div', context);
  box.className = 'md-front';
  mapLines(box, token, 'front', context);
  const lines = tokenLines(token, context),
    first = lines ? lines.lo + 1 : 0,
    last = lines ? lines.hi - 1 : -1;
  const head = countedElement('div', context);
  head.className = 'md-front-l';
  head.lang = document.documentElement.lang; // the viewer's words, in the screen's language
  head.textContent = translateTemplate('머리 정보 · YAML {n}줄', { n: Math.max(0, last - first + 1) });
  const pre = countedElement('pre', context),
    code = countedElement('code', context);
  pre.dataset.lang = 'yaml';
  pre.appendChild(code);
  box.append(head, pre);
  top.appendChild(box);
  for (let line = first; line <= last; line++) {
    const span = countedElement('span', context),
      text = String(context.lines[line - 1] || '');
    span.className = 'ln';
    span.dataset.line = String(line);
    if (isPlainText(text, context)) span.textContent = text + '\n';
    else {
      yield* drawText(span, text, work, context);
      span.appendChild(document.createTextNode('\n'));
    } // hidden characters in their boxes, as a code line's
    code.appendChild(span);
    if (isPauseDue(work)) yield;
  }
}
// GitHub's heading slug: lower case, punctuation dropped, spaces to '-'. Pure.
function headingSlug(title: string) {
  return String(title)
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

export { renderDocument, renderTokens };
