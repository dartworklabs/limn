/** Load KaTeX and render formulas within the document budget while retaining their source TeX. */
import type { MarkdownToken } from './flow-parse.ts';
import { isRecord } from '../platform/tables.ts';
import { MARKDOWN_LIMITS, MARKDOWN_VIEW } from './state.ts';
import type { RenderContext } from './state.ts';
import { ANY_HIDDEN } from '../platform/hidden-chars.ts';
import { OVER_ELEMENT_LIMIT, mapLines, countedElement, isPlainText, drawText, isPauseDue } from './view-elements.ts';
import { $, findAll } from '../platform/dom.ts';

// ---------------- The TeX renderer (ADR-0036, docs/handbook/viewer.md §수식)
const KATEX_VERSION = '__KATEX_VERSION__';
// TEX_RENDERER: the vendored KaTeX module once the page has it (lib) and how far the one load got (state) - 'none'
// before it is asked for, 'ready' with both the module and its stylesheet in, 'off' when either did not come. 'off' is
// final: the math of every document then stays as its source characters (ADR-0036 D2), and nothing is asked for twice.
const TEX_RENDERER: { state: 'none' | 'ready' | 'off'; lib: KatexLibrary | null } = { state: 'none', lib: null };
// The closing delimiter of each opening one the worker's math rules read (MD_MATH in md-parse.mjs).
const TEX_CLOSE: Record<string, string> = { $: '$', $$: '$$', '\\(': '\\)', '\\[': '\\]' };
// Whether the worker's tokens hold any math at all - whether this document needs the renderer. A document without math
// (and a PDF or text document) asks for nothing.
function hasMath(tokens: MarkdownToken[]) {
  for (const token of tokens) {
    if (token.type === 'math_block') return true;
    for (const child of token.children || []) if (child.type === 'math_inline') return true;
  }
  return false;
}
// The renderer, or null when it is not to be had. One attempt per page: the module from this origin (the page imports
// it, never the parse worker - that one returns tokens and touches no DOM, architecture.md 불변식 9) and its
// stylesheet, both with the bundle's version, so a cached copy never needs revalidating. Unstyled KaTeX markup is
// unreadable, so a stylesheet that does not arrive counts as no renderer.
async function loadTexRenderer(): Promise<KatexLibrary | null> {
  if (TEX_RENDERER.state !== 'none') return TEX_RENDERER.lib;
  TEX_RENDERER.state = 'off';
  let katexModule: unknown = null;
  try {
    katexModule = await import('/vendor/katex/katex.mjs?v=' + KATEX_VERSION);
  } catch (error) {
    return null;
  }
  const lib = texLibraryOf(katexModule);
  if (!lib) return null;
  if (!(await loadTexStyle())) return null;
  TEX_RENDERER.lib = lib;
  TEX_RENDERER.state = 'ready';
  return lib;
}
// Whether a value is the KaTeX library the viewer draws with (types/katex.d.ts): an object with a render function. Pure.
function isKatexLibrary(value: unknown): value is KatexLibrary {
  return isRecord(value) && typeof value.render === 'function';
}
// The KaTeX library in what the import loaded: its default export, else the module itself - whichever is there - when
// it is the library (isKatexLibrary); null for anything else, which is no renderer. Pure.
function texLibraryOf(loaded: unknown): KatexLibrary | null {
  const library = isRecord(loaded) && loaded.default ? loaded.default : loaded;
  return isKatexLibrary(library) ? library : null;
}
// The stylesheet, added once; true once the browser has it. A link element pointing at this origin - never an inline
// style element and never a style attribute, which the page policy admits neither of (viewer.md §페이지 정책).
function loadTexStyle(): Promise<boolean> {
  return new Promise((resolve) => {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/vendor/katex/katex.css?v=' + KATEX_VERSION;
    link.onload = () => resolve(true);
    link.onerror = () => {
      link.remove();
      resolve(false);
    };
    document.head.appendChild(link);
  });
}
// The TeX of an inline formula, without its delimiters, or null when what is given is no formula. source is the text to
// read: a token's own for a formula that fits one source line (the worker marks it info 'whole'), and the pieces put
// back together for one it cut at a line end (info 'head' on the first piece, inlineTexRun). A 'tail' piece is no TeX
// on its own and is never read alone - its head draws the whole formula and passes it over (drawInline). Pure.
function inlineTexBody(piece: MarkdownToken, source?: string): string | null {
  const open = String(piece.markup || ''),
    close = TEX_CLOSE[open] || '';
  const text = source === undefined ? String(piece.content || '') : source;
  if ((piece.info !== 'whole' && piece.info !== 'head') || !close || text.length < open.length + close.length + 1)
    return null;
  if (!text.startsWith(open) || !text.endsWith(close)) return null;
  return text.slice(open.length, text.length - close.length);
}
// One formula's source as written, starting at child `at` of an inline token: that piece, and - when the worker cut the
// formula at a line end ('head') - every piece after it, joined by the line ends it was cut at. last is the index of
// the formula's final piece, so the caller knows which children the one formula covers (at itself when nothing was
// cut). Pure.
function inlineTexRun(children: MarkdownToken[], at: number): { src: string; last: number } {
  const parts = [String(children[at].content || '')];
  let next = at + 1;
  while (
    children[at].info === 'head' &&
    next + 1 < children.length &&
    children[next].type === 'softbreak' &&
    children[next + 1].type === 'math_inline' &&
    children[next + 1].info === 'tail'
  ) {
    parts.push(String(children[next + 1].content || ''));
    next += 2;
  }
  return { src: parts.join('\n'), last: next - 1 };
}
// The TeX of a display math block, without its delimiters, or null when its lines do not open and close one. Pure.
function blockTexBody(lines: string[]): string | null {
  const text = lines.join('\n').replace(/\n+$/, '');
  const open = text.startsWith('$$') ? '$$' : text.startsWith('\\[') ? '\\[' : '',
    close = open ? TEX_CLOSE[open] : '';
  if (!open || !text.endsWith(close) || text.length < open.length + close.length + 1) return null;
  return text.slice(open.length, text.length - close.length);
}
// A <tag class=className> with the TeX of source drawn into it (tex: source without its delimiters) and source on
// data-tex, or null when it is not drawn - then the caller shows source as characters (ADR-0036 D2). Not drawn when:
// there is no renderer; the context does not draw math (context.tex null - the rendered compare keeps the source
// characters, ADR-0036 D3); the TeX is not whole (tex null); the TeX is longer than MARKDOWN_LIMITS.tex characters -
// KaTeX lays a formula out in one call that cannot pause or be stopped, and past that length its time grows much faster
// than the formula, which would hold the page still as no other part of the build may (ADR-0039); source holds a
// character that hides or reorders text (ANY_HIDDEN, ADR-0029 D5) - drawn glyphs could show neither it nor its box, so
// such a formula stays as its characters, each in its box; or KaTeX refuses it (throwOnError, so a refusal never draws
// its own red markup and the style attribute that would carry its colour). The element is built outside countedElement
// and counted
// - with everything KaTeX put in it - only once it is used, so a refusal leaves the count where it was (ADR-0036 D6).
// trust false leaves \href, \url and \includegraphics as characters, so no link or image of KaTeX's own gets past the
// viewer's allowlists; strict false draws a Korean word in math mode instead of refusing it.
function drawTexBox(
  tag: string,
  className: string,
  source: string,
  tex: string | null,
  display: boolean,
  context: RenderContext,
): HTMLElement | null {
  const library = TEX_RENDERER.lib;
  if (
    context.tex === null ||
    TEX_RENDERER.state !== 'ready' ||
    !library ||
    tex === null ||
    !tex.trim() ||
    tex.length > MARKDOWN_LIMITS.tex ||
    ANY_HIDDEN.test(source)
  )
    return null;
  const box = document.createElement(tag);
  try {
    library.render(tex, box, { displayMode: display, throwOnError: true, strict: false, trust: false });
  } catch (error) {
    return null;
  }
  box.className = className;
  box.dataset.tex = source;
  context.els += 1 + box.querySelectorAll('*').length;
  context.tex++;
  if (context.els > MARKDOWN_LIMITS.elements) throw OVER_ELEMENT_LIMIT;
  return box;
}
// A drawn formula cannot be broken over lines: KaTeX lays it out as one inline-block. One wider than the column reaches
// past the screen's edge, where the page's own rule (`body` does not scroll sideways) puts it out of reach - characters
// the reader cannot get to, which is the one thing drawing must not cost. So after a build and after the column changes
// width, the drawn inline formulas are measured and only those too wide are told to scroll inside themselves, as a
// display block already does. The others are left alone: a box that scrolls sits on its bottom edge instead of the
// sentence's baseline, which would lift every formula off its line. The measuring is batched - every class off, then
// every width read, then the classes on - so the whole document costs two layouts, not two per formula. The width read
// is the drawn formula's own (.katex, an inline-block), which does not change when the box around it starts scrolling:
// the pass settles at once.
function fitWideFormulas() {
  const column = $('#md');
  if (!column || !MARKDOWN_VIEW.tex) return;
  const boxes = findAll(column, 'code.md-math.md-tex', HTMLElement);
  if (!boxes.length) return;
  for (const box of boxes) box.classList.remove('md-tex-wide');
  const wide = boxes.filter((box) => {
    const block = box.closest('p,li,td,th,blockquote') || column,
      style = getComputedStyle(block);
    // where the block's own text goes, not the column's padding box
    const room = block.clientWidth - parseFloat(style.paddingLeft || '0') - parseFloat(style.paddingRight || '0');
    return room > 0 && (box.querySelector('.katex') || box).getBoundingClientRect().width > room + 0.5;
  });
  for (const box of wide) box.classList.add('md-tex-wide');
}
// Display math (the worker's math_block token, mdMathBlock in md-parse.mjs; ADR-0032, ADR-0036): the block's lines
// (data-lo..hi, kind math - a block of its own, md:math) either drawn by KaTeX in one box (drawTexBox, with the source
// TeX on data-tex so a pin's quote is still the TeX, rangeText) or, when it is not drawn, its TeX as written in a code
// box with each line, its delimiters included, one span (data-line), as a code block's. Drawn, the block is the
// smallest thing that can be chosen in it - none of its lines can be chosen alone (ADR-0036 D3). The lines are the
// token's (indentation and quote markers left out).
function* drawMathBlock(
  token: MarkdownToken,
  top: HTMLElement,
  work: { n: number },
  context: RenderContext,
): Generator<void, void, void> {
  const first = token.map ? token.map[0] + 1 : 0,
    lines = String(token.content || '').split('\n');
  const box = drawTexBox(
    'div',
    'md-math-block md-tex',
    String(token.content || ''),
    blockTexBody(lines),
    true,
    context,
  );
  if (box) {
    mapLines(box, token, 'math', context);
    top.appendChild(box);
    return;
  }
  const pre = countedElement('pre', context),
    code = countedElement('code', context);
  pre.className = 'md-math-block';
  mapLines(pre, token, 'math', context);
  pre.appendChild(code);
  top.appendChild(pre);
  for (let i = 0; i < lines.length; i++) {
    const span = countedElement('span', context),
      text = lines[i];
    span.className = 'ln';
    if (first) span.dataset.line = String(first + i);
    if (isPlainText(text, context)) span.textContent = text + '\n';
    else {
      yield* drawText(span, text, work, context);
      span.appendChild(document.createTextNode('\n'));
    } // hidden characters in their boxes, as a code line's
    code.appendChild(span);
    if (isPauseDue(work)) yield;
  }
}

export { hasMath, loadTexRenderer, fitWideFormulas, drawMathBlock, inlineTexRun, drawTexBox, inlineTexBody };
