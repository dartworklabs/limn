/** Draw inline tokens and associate their rendered text with source lines. */
import type { MarkdownToken } from './flow-parse.ts';
import type { RenderContext } from './state.ts';
import { countedElement, isPlainText, drawText, tokenAttribute, isPauseDue } from './view-elements.ts';
import { drawLink } from './view-links.ts';
import { inlineTexRun, drawTexBox, inlineTexBody } from './view-math.ts';
import { drawImage } from './view-images.ts';

// ---------------- Rendered text -> source lines
// The source line each child of an inline token starts on (pure): the token's first line plus the line breaks
// (softbreak, hardbreak) before the child. The children are flat - emphasis and links are open/close tokens among them
// - so a break inside one is counted too. That names the right line only when every line end in the token's source
// became such a break. A code span (it turns the line end into a space), a raw HTML tag, a link's destination or title,
// a reference label or an image's alt text that runs over a line end swallows it, and every child after it would be
// labelled one line early; markdown-it gives inline children no source offsets to recover from that. So exact is true
// only when the breaks and the line ends of token.content are as many, and then lines[i] is child i's line; otherwise
// the caller gives the whole token one range, lo..hi (its first to last line).
function inlineLines(token: { map?: number[] | null; content?: string; children?: { type: string }[] | null }): {
  exact: boolean;
  lo: number;
  hi: number;
  lines: number[];
} {
  const first = token.map ? token.map[0] + 1 : 0,
    ends = (String(token.content || '').match(/\n/g) || []).length;
  let breaks = 0;
  const lines = (token.children || []).map((child) => {
    const at = first + breaks;
    if (child.type === 'softbreak' || child.type === 'hardbreak') breaks++;
    return at;
  });
  return { exact: first > 0 && breaks === ends, lo: first, hi: first ? first + ends : 0, lines };
}
// An inline token's children into parent, its lines as inlineLines tells them. Exact: one span per source line
// (data-line); a break inside emphasis or a link ends the open elements in the old line's span and opens shallow copies
// of them in the new one, so the text after the break is under its own line. Not exact: one span with the token's whole
// range (data-lo/data-hi, kind 'lines'), so a selection inside it takes all of those lines - never a wrong one, and
// never a suggestion's wrong base. A table cell's inline token has no map: its span carries nothing and the row's range
// stands for it.
function* drawInline(
  token: MarkdownToken,
  parent: HTMLElement,
  work: { n: number },
  context: RenderContext,
): Generator<void, void, void> {
  const lineInfo = inlineLines(token),
    children = token.children || [];
  const makeLineSpan = (line: number) => {
    const span = countedElement('span', context);
    span.className = 'ln';
    if (lineInfo.exact) span.dataset.line = String(line);
    else if (lineInfo.lo) {
      span.dataset.lo = String(lineInfo.lo);
      span.dataset.hi = String(lineInfo.hi);
      span.dataset.kind = 'lines';
    }
    parent.appendChild(span);
    return span;
  };
  let stack: HTMLElement[] = [makeLineSpan(lineInfo.lo)];
  // The pieces of a drawn formula still to pass over: its head drew all of them at once (inlineTexRun), so they add
  // nothing here.
  let skip = 0;
  for (let i = 0; i < children.length; i++) {
    const child = children[i],
      top = stack[stack.length - 1];
    switch (child.type) {
      case 'text':
        if (isPlainText(child.content, context)) top.appendChild(document.createTextNode(child.content));
        else yield* drawText(top, child.content, work, context);
        break;
      case 'code_inline': {
        const element = countedElement('code', context);
        top.appendChild(element);
        yield* drawText(element, child.content, work, context);
        break;
      }
      case 'softbreak':
      case 'hardbreak':
        // Inside a drawn formula the line end is already in the box's data-tex (drawInline's math_inline): writing it
        // again would put it in the quote twice. The line still starts its own span, so what follows the formula is
        // under it.
        if (!skip)
          top.appendChild(child.type === 'hardbreak' ? countedElement('br', context) : document.createTextNode('\n'));
        if (lineInfo.exact) {
          const next = [makeLineSpan(lineInfo.lines[i] + 1)];
          for (const open of stack.slice(1)) {
            const copy = open.cloneNode(false);
            if (!(copy instanceof HTMLElement)) continue;
            ++context.els;
            next[next.length - 1].appendChild(copy);
            next.push(copy);
          }
          stack = next;
        }
        break;
      case 'strong_open':
      case 'em_open':
      case 's_open': {
        const element = countedElement(
          child.type === 'strong_open' ? 'strong' : child.type === 'em_open' ? 'em' : 's',
          context,
        );
        top.appendChild(element);
        stack.push(element);
        break;
      }
      case 'link_open': {
        const element = drawLink(tokenAttribute(child, 'href'), context);
        top.appendChild(element);
        stack.push(element);
        break;
      }
      // Drawn by KaTeX in a box of its own (drawTexBox, its source TeX on data-tex for the quote), or its TeX as
      // written, delimiters included (mdMathInline), hidden characters in their boxes; one token per source line when
      // it is not drawn. A formula the worker cut at a line end is put back together (inlineTexRun) and drawn once, in
      // the line it starts in, and the pieces after it are passed over. Such a box carries the lines it covers itself
      // (data-lo..hi, kind 'lines' - the formula is the run those lines could not be told apart in), so a pin on it
      // keeps the source TeX for its quote and gets the formula's own lines for its range (ADR-0036 D3). Undrawn, every
      // piece stays in the line it was written on.
      case 'math_inline': {
        if (skip) {
          skip--;
          break;
        }
        const run = inlineTexRun(children, i),
          drawn = drawTexBox('code', 'md-math md-tex', run.src, inlineTexBody(child, run.src), false, context);
        if (drawn) {
          top.appendChild(drawn);
          if (run.last > i) {
            skip = (run.last - i) / 2;
            if (lineInfo.exact) {
              drawn.dataset.lo = String(lineInfo.lines[i]);
              drawn.dataset.hi = String(lineInfo.lines[run.last]);
              drawn.dataset.kind = 'lines';
            }
          }
          break;
        }
        const element = countedElement('code', context);
        element.className = 'md-math';
        top.appendChild(element);
        yield* drawText(element, child.content, work, context);
        break;
      }
      case 'strong_close':
      case 'em_close':
      case 's_close':
      case 'link_close':
        if (stack.length > 1) stack.pop();
        break;
      case 'image':
        top.appendChild(yield* drawImage(child, work, context));
        break;
      case 'html_inline': {
        const element = countedElement('code', context);
        element.className = 'md-html-in';
        top.appendChild(element);
        yield* drawText(element, child.content, work, context);
        break;
      }
      default:
        if (child.content) yield* drawText(top, child.content, work, context);
    }
    if (isPauseDue(work)) yield;
  }
}

export { drawInline };
