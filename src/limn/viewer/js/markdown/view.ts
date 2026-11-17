// --------------------------------------------- The Markdown surface (docs/handbook/viewer.md §Markdown 화면, ADR-0025)
// A document the browser draws from its source (rendersInBrowser: kind "markdown") has no pages. #doc holds one flowing
// column, article#md, drawn here; the panel, the list, the composer and the cards are the same as on the PDF surface.
// - GET /api/source answers the file as the server numbers it (str.splitlines(), already split, 1 MiB at most - over it
//   413 source_too_large and no lines). The lines this screen shows are the server's lines by construction: they are
//   joined with "\n" for the parser and never split again from raw bytes.
// - markdown-it parses in a worker of its own (GET /md-parse.mjs, this origin - no blob: worker, ADR-0026), within
//   MARKDOWN_LIMITS: nesting, block and inline tokens there; elements while the DOM is built here, with a yield to the
//   browser after every MARKDOWN_LIMITS.chunk units of work (a token, an inline child, a code line) wherever they fall;
//   the time the worker takes. Over any of them the screen is the plain source-line view (lineView), over
//   MARKDOWN_LIMITS.lines lines not even that, but a notice with the count and the limit (documentNotice). Pins, cards
//   and the agent's paths stay as they are. One formula's TeX is drawn only up to MARKDOWN_LIMITS.tex characters
//   (drawTexBox): past it that formula alone stays as its characters.
// - The DOM is built with createElement and textContent only: markdown-it's HTML renderer is never used, so the one
//   innerHTML sink (platform/markup.ts setHtml) stays the only one. Raw HTML is never drawn: a block is a placeholder
//   that keeps its lines, an inline tag shows as code. A character that would hide or reorder text
//   (platform/hidden-chars.ts) stays in the drawn text inside its box (drawText), as on the text surface, and a notice
//   above the document counts them. An image loads only when its source is a file of the manuscript tree with an image
//   suffix, resolved against the document's own path (imageSource) and fetched from this origin's GET /api/asset (asked
//   again on the light poll, checkTreeImages: one rewritten on disk shows without a reload); a remote or data: image,
//   or one that leaves the tree, is its alt text (ADR-0030). A link opens only through the allowlist (linkAction) -
//   another origin's http(s), mailto, an in-document #heading, another registered document of this instance (by its
//   path, with its #heading), an image of the tree in a new tab; anything else is inert text.
// - Every block token's map becomes data-lo/data-hi on the element drawn for it. Inside a paragraph or heading each
//   source line gets its own span (data-line) only when the inline token's line breaks match its source's line ends
//   (inlineLines); otherwise the whole run is one span with its range. A code block's content lines are its source
//   lines one for one.
// - A text selection (a mouse drag, a phone's long-press handles) becomes lines lo..hi; a tap or click on a block picks
//   that block. The ladder is: the chosen lines -> the block -> the heading's section (markdownLevels). Saving is the
//   ordinary POST /api/pin, with no page, frac or pdf_build (the server drops them for this document anyway, ADR-0025
//   D2).
import {
  DOC,
  DOCS,
  IME_ON_FREE,
  LAYOUT,
  META,
  COARSE_POINTER_QUERY,
  PICKSEQ,
  PINS,
  REPICK,
  REVIEW_ALL,
  SWITCHSEQ,
  imeHeldIn,
  rendersInBrowser,
  scrollMotion,
  setPickseq,
  setSnipOpen,
  showsSourceLines,
  COMPOSE,
  setComposeCurrent,
  setComposeDismissedOverlap,
  setComposeIntent,
  setComposePicking,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import {
  ANY_HIDDEN,
  hiddenBox,
  clipMarkedText,
  findHidden,
  markHiddenPlain,
  scanHidden,
  hiddenName,
} from '../platform/hidden-chars.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { api, isRefusal } from '../platform/api.ts';
import { endTopic } from '../platform/notices.ts';
import { TIP, hideTip, showTip, LAST_POINTER } from '../platform/tooltip.ts';
import { drawPos, switchDoc, switchPending } from '../documents/flow-switch.ts';
import { tintChangedLines, compareRedrawnSource } from '../documents/flow-updates.ts';
import {
  OUTLINE_SELECTED,
  SCROLL_KEYS,
  markOutline,
  renderOutline,
  setOutlineBuild,
  setOutlineCut,
  setOutlineDoc,
  setOutlineEntries,
  setOutlineSelected,
} from '../pdf/view-outline.ts';
import { applySide, setSide } from '../layout/flow.ts';
import { BACK } from '../layout/input.ts';
import { revealBox, selectionRoom } from '../pdf/input-selection.ts';
import { imeOpen } from '../platform/composition.ts';
import { NOTICE_TOPIC } from '../platform/tables.ts';
import { $, $$, focusFell, focusHold } from '../platform/dom.ts';
import { LAYOUT_MODE, MARKDOWN_LIMIT, PIN_STATE } from '../app/rules-tables.ts';
import { pinState, lineRange, overlapsFor } from '../app/rules-pins.ts';
import { isMarkdownDoc, isTextDoc, docInfo, withDocQuery, isRegion, pdoc } from '../documents/state.ts';
import { levelOf, useLevel } from '../documents/rules.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
import { lineMarks, linePick, textSurface } from './state-seams.ts';
import { readingDepth } from '../pdf/view-page-jump.ts';
import { linkHref } from './rules-links.ts';
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
// MARKDOWN_VIEW: the document drawn (doc, file, name), its source lines and the src_mtime they were read at (mtime: set
// only by a read that answered, so the light poll, documents/flow-polling.ts, sees a failed read as not done), the
// src_mtime a redraw was last asked for (asked: the light poll asks once per change while that read is on its way, and
// a failed read clears it), the reading line (at), the limit hit (limit), its headings, the worker and its parse in
// flight, whether a redraw waits for a field (waiting), the elements built so far (els), the characters drawn in their
// boxes (marked) and whether the next text drawn may be the file's first, its byte-order mark kept (bom, drawText), the
// document #doc shows now (shown: '' for none - a PDF document's pages, the wait line), the reading spot a kept view
// asks for once it is drawn (want) and the reading spot as last read at the column's width and the pane's scroll offset
// then (spot, readSpot: kept across a reflow and a redraw while hidden, keepReadingSpot; top tells a pane moved since,
// refreshMovedSpot).
const MARKDOWN_VIEW = {
  gen: 0,
  doc: '' as string | null,
  file: '',
  name: '',
  lines: [] as string[],
  mtime: null as number | null,
  asked: null as number | null,
  at: 0,
  limit: null as string | null,
  heads: [] as { level: number; lo: number; el: HTMLElement; title: string; slug: string }[],
  worker: null as Worker | null,
  job: null as { id: number; resolve: (answer: any) => void; t: ReturnType<typeof setTimeout> } | null,
  seq: 0,
  waiting: false,
  els: 0,
  marked: 0,
  bom: false,
  tex: 0 as number | null,
  shown: '' as string | null,
  want: null as { line: number; off: number; top: number } | null,
  jumpTo: null as { id: number; doc: string | null; seq: number } | null,
  spot: null as {
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
  } | null,
  // a heading a link from another document asked for, gone to once this document is drawn in that visit (goToDocLink),
  // and the heading a jump in flight is going to (goToHeading: an image that gets its size moves the destination, not
  // the reading spot)
  headTo: null as { doc: string; id: string; seq: number } | null,
  goTo: null as { el: HTMLElement; doc: string | null } | null,
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
const ROOT_CONTEXTS = new WeakMap() as WeakMap<Element, RenderContext>;
function keepRenderContext(root: Element, context: RenderContext) {
  ROOT_CONTEXTS.set(root, context);
}
function renderContextOf(element: Element | null): RenderContext {
  const root = element && element.closest('.md');
  return (root && ROOT_CONTEXTS.get(root)) || MARKDOWN_VIEW;
}
function isMarkdownPin(pin: Pin) {
  const entry = docInfo(pdoc(pin));
  return !!entry && rendersInBrowser(entry.kind);
}
// ---------------- The parse worker
// Parses text in the worker within MARKDOWN_LIMITS -> {ok:true,tokens} or {ok:false,limit} (MARKDOWN_LIMIT), or null
// when a newer parse took the worker over. The worker is started the first time and kept; one that runs past
// MARKDOWN_LIMITS.ms, fails to load or is taken over is stopped (terminate) and a new one starts next time.
function parseMarkdown(text: string): Promise<any> {
  stopMarkdownParse(null);
  return new Promise((resolve) => {
    let worker = MARKDOWN_VIEW.worker;
    try {
      if (!worker) {
        worker = new Worker('/md-parse.mjs', { type: 'module' });
        MARKDOWN_VIEW.worker = worker;
        worker.onmessage = (message) => {
          const job = MARKDOWN_VIEW.job;
          if (!job || !message.data || message.data.id !== job.id) return;
          clearTimeout(job.t);
          MARKDOWN_VIEW.job = null;
          job.resolve(message.data);
        };
        worker.onerror = (event) => {
          event.preventDefault();
          stopMarkdownParse({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
        };
      }
    } catch (error) {
      resolve({ ok: false, limit: MARKDOWN_LIMIT.LOAD });
      return;
    }
    const id = ++MARKDOWN_VIEW.seq;
    MARKDOWN_VIEW.job = {
      id,
      resolve,
      t: setTimeout(() => stopMarkdownParse({ ok: false, limit: MARKDOWN_LIMIT.TIME }), MARKDOWN_LIMITS.ms),
    };
    worker.postMessage({
      id,
      text,
      limits: { nesting: MARKDOWN_LIMITS.nesting, blocks: MARKDOWN_LIMITS.blocks, inlines: MARKDOWN_LIMITS.inlines },
    });
  });
}
// Ends the parse in flight, if any, with answer (null: taken over), and stops its worker.
function stopMarkdownParse(answer: { ok: boolean; limit: string } | null) {
  const job = MARKDOWN_VIEW.job;
  if (!job) return;
  MARKDOWN_VIEW.job = null;
  clearTimeout(job.t);
  if (MARKDOWN_VIEW.worker) {
    MARKDOWN_VIEW.worker.terminate();
    MARKDOWN_VIEW.worker = null;
  }
  job.resolve(answer);
}
// ---------------- The TeX renderer (ADR-0036, docs/handbook/viewer.md §수식)
const KATEX_VERSION = '__KATEX_VERSION__';
// TEX_RENDERER: the vendored KaTeX module once the page has it (lib) and how far the one load got (state) - 'none'
// before it is asked for, 'ready' with both the module and its stylesheet in, 'off' when either did not come. 'off' is
// final: the math of every document then stays as its source characters (ADR-0036 D2), and nothing is asked for twice.
const TEX_RENDERER = { state: 'none' as 'none' | 'ready' | 'off', lib: null as any };
// The closing delimiter of each opening one the worker's math rules read (MD_MATH in md-parse.mjs).
const TEX_CLOSE = { $: '$', $$: '$$', '\\(': '\\)', '\\[': '\\]' } as Record<string, string>;
// Whether the worker's tokens hold any math at all - whether this document needs the renderer. A document without math
// (and a PDF or text document) asks for nothing.
function hasMath(tokens: any[]) {
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
async function loadTexRenderer(): Promise<any> {
  if (TEX_RENDERER.state !== 'none') return TEX_RENDERER.lib;
  TEX_RENDERER.state = 'off';
  let katexModule = null as any;
  try {
    katexModule = await import('/vendor/katex/katex.mjs?v=' + KATEX_VERSION);
  } catch (error) {
    return null;
  }
  const lib = katexModule && (katexModule.default || katexModule);
  if (!lib || typeof lib.render !== 'function') return null;
  if (!(await loadTexStyle())) return null;
  TEX_RENDERER.lib = lib;
  TEX_RENDERER.state = 'ready';
  return lib;
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
function inlineTexBody(piece: any, source?: string): string | null {
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
function inlineTexRun(children: any[], at: number): { src: string; last: number } {
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
  if (
    context.tex === null ||
    TEX_RENDERER.state !== 'ready' ||
    tex === null ||
    !tex.trim() ||
    tex.length > MARKDOWN_LIMITS.tex ||
    ANY_HIDDEN.test(source)
  )
    return null;
  const box = document.createElement(tag);
  try {
    TEX_RENDERER.lib.render(tex, box, { displayMode: display, throwOnError: true, strict: false, trust: false });
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
  const boxes = [...column.querySelectorAll('code.md-math.md-tex')] as HTMLElement[];
  if (!boxes.length) return;
  for (const box of boxes) box.classList.remove('md-tex-wide');
  const wide = boxes.filter((box) => {
    const block = (box.closest('p,li,td,th,blockquote') || column) as HTMLElement,
      style = getComputedStyle(block);
    // where the block's own text goes, not the column's padding box
    const room = block.clientWidth - parseFloat(style.paddingLeft || '0') - parseFloat(style.paddingRight || '0');
    return room > 0 && (box.querySelector('.katex') || box).getBoundingClientRect().width > room + 0.5;
  });
  for (const box of wide) box.classList.add('md-tex-wide');
}
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
// Whether a redraw would take a text field from under the person typing in it: a field inside #doc that is composing,
// or held by the key that ended its composition (imeHeldIn, app/state.ts §조합을 끝내는 키).
function isFieldBusy() {
  const active = document.activeElement as HTMLElement | null,
    held = imeHeldIn();
  const doc = $('#doc'),
    inDoc = (node: any) => node instanceof Node && doc.contains(node);
  return inDoc(held) || (!!active && inDoc(active) && active !== doc && COMPOSING_FIELDS.has(active));
}
const COMPOSING_FIELDS = new Set();
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
  if (MARKDOWN_VIEW.waiting && !isFieldBusy()) {
    MARKDOWN_VIEW.waiting = false;
    if (isMarkdownDoc()) buildMarkdownDoc();
  }
});
document.addEventListener('compositionend', () => {
  if (MARKDOWN_VIEW.waiting)
    setTimeout(() => {
      if (MARKDOWN_VIEW.waiting && !isFieldBusy()) {
        MARKDOWN_VIEW.waiting = false;
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
    MARKDOWN_VIEW.waiting = true;
    return;
  }
  const generation = ++MARKDOWN_VIEW.gen,
    docKey = DOC,
    stale = () => generation !== MARKDOWN_VIEW.gen || docKey !== DOC || !isMarkdownDoc();
  document.body.classList.add('md-surface');
  const doc = $('#doc');
  if (MARKDOWN_VIEW.shown !== docKey || !doc.querySelector('#md')) {
    MARKDOWN_VIEW.shown = '';
    doc.replaceChildren(waitLine(translate('원문을 읽는 중입니다.')));
  }
  let answer;
  try {
    answer = await api('GET /api/source', { query: withDocQuery(''), what: '원문 읽기', silent: true, expect: [413] });
  } catch (error) {
    if (!stale()) {
      MARKDOWN_VIEW.asked = null;
      MARKDOWN_VIEW.mtime = null;
      showDocumentNode(documentNotice(translate('원문을 읽지 못했습니다'), ''));
    }
    return;
    // not read: no read answers for this source now (MARKDOWN_VIEW.mtime too, or an unchanged source on a return to the
    // document never matches again), so the next light poll asks again
  }
  if (stale()) return;
  if (isRefusal(answer.data)) {
    MARKDOWN_VIEW.lines = []; // 413: too large to send
    MARKDOWN_VIEW.heads = [];
    MARKDOWN_VIEW.mtime = MARKDOWN_VIEW.asked;
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
    // the lines this source replaces (documents/flow-updates.ts)
    before =
      MARKDOWN_VIEW.doc === docKey && MARKDOWN_VIEW.mtime !== null && MARKDOWN_VIEW.mtime !== source.src_mtime
        ? MARKDOWN_VIEW.lines
        : null;
  MARKDOWN_VIEW.doc = docKey;
  MARKDOWN_VIEW.mtime = source.src_mtime;
  MARKDOWN_VIEW.file = String(source.file || '');
  MARKDOWN_VIEW.name = MARKDOWN_VIEW.file.split('/').pop() || MARKDOWN_VIEW.file;
  MARKDOWN_VIEW.lines = Array.isArray(source.lines) ? source.lines.map(String) : [];
  if (isTextDoc()) {
    MARKDOWN_VIEW.heads = []; // a text document is never parsed: its lines are its view (text/view.ts)
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
  const parsed = MARKDOWN_VIEW.lines.some((line) => line.includes('\0'))
    ? { ok: false, limit: MARKDOWN_LIMIT.NUL }
    : await parseMarkdown(MARKDOWN_VIEW.lines.join('\n'));
  if (stale() || !parsed) return;
  let root = null as HTMLElement | null,
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
    MARKDOWN_VIEW.heads = [];
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
    root = await lineView(limit as string, stale);
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
  const want = MARKDOWN_VIEW.want,
    shown = isColumnShown();
  MARKDOWN_VIEW.want = null;
  MARKDOWN_VIEW.limit = node.dataset.limit || null;
  const anchor = shown ? want || (MARKDOWN_VIEW.shown === DOC ? readingAnchor() : null) : null;
  if (!shown) {
    const spot = MARKDOWN_VIEW.spot;
    if (want)
      MARKDOWN_VIEW.spot = {
        doc: DOC,
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
    else if (spot && spot.doc === DOC && MARKDOWN_VIEW.shown === DOC) {
      spot.el = null;
      spot.again = true;
    } else MARKDOWN_VIEW.spot = null;
  }
  $('#doc').replaceChildren(node);
  MARKDOWN_VIEW.shown = DOC;
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
  const jump = MARKDOWN_VIEW.jumpTo;
  MARKDOWN_VIEW.jumpTo = null;
  // a jump asked before the draw (jumpToPinLines)
  if (jump && jump.doc === DOC && jump.seq === SWITCHSEQ) jumpToPinLines(jump.id);
  const heading = MARKDOWN_VIEW.headTo;
  if (heading && heading.doc === DOC) {
    MARKDOWN_VIEW.headTo = null;
    if (heading.seq === SWITCHSEQ) goToLinkHeading(heading.id);
  }
} // a link from another document (goToDocLink)
// The line view offers the chosen lines alone (lineView): a pick of this document whose ladder came from the drawn
// document (a draft kept from before the parser failed) keeps its lines but takes the ladder a pick there gives - those
// lines, as lines.
function relevelForLineView() {
  const selection = COMPOSE.current;
  if (
    !selection ||
    REPICK ||
    isRegion(selection) ||
    selection.doc !== DOC ||
    selection.file !== MARKDOWN_VIEW.file ||
    !$('#md.md-lines')
  )
    return;
  if (
    (selection.levels || []).every(
      (level) => level.level === 'raw' && level.lo === selection.lo && level.hi === selection.hi,
    )
  )
    return;
  const range = { lo: selection.lo as number, hi: selection.hi as number };
  selection.levels = markdownLevels(range, null, null);
  selection.raw_lo = range.lo;
  selection.raw_hi = range.hi;
  selection.default_level = 'raw';
  useLevel(selection, 'raw');
  linePick().renderComposer();
}
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
  MARKDOWN_VIEW.marked = drawn.marked;
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
// The elements that carry lines, in document order (line spans and blocks). Their tops never decrease in that order - a
// block precedes what it holds and stands no lower - so the one at a height is found by halving (lineElementAt), never
// by measuring them all.
function lineElements() {
  const column = $('#md');
  return column ? ([...column.querySelectorAll('[data-line],[data-lo]')] as HTMLElement[]) : [];
}
// The last of elements whose top is at or above y (viewport px), or null before the first. O(log n) measures.
function lineElementAt(elements: HTMLElement[], y: number) {
  let low = 0,
    high = elements.length - 1,
    at = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (elements[middle].getBoundingClientRect().top <= y) {
      at = middle;
      low = middle + 1;
    } else high = middle - 1;
  }
  return at < 0 ? null : elements[at];
}
// The reading spot: the line span or block at the pane's top (lineElementAt), its first line and the px of it above
// that top.
function readingAnchor() {
  const pane = $('#left');
  if (!$('#md') || !MARKDOWN_VIEW.lines.length) return null;
  const top = pane.getBoundingClientRect().top,
    element = lineElementAt(lineElements(), top);
  return element
    ? {
        line: +(element.dataset.line || element.dataset.lo || 0),
        off: top - element.getBoundingClientRect().top,
        top: pane.scrollTop,
      }
    : null;
}
function restoreReadingAnchor(anchor: { line: number; off: number; top: number } | null) {
  const pane = $('#left');
  if (!anchor) {
    return;
  }
  const element = lineLeaves(anchor.line, anchor.line)[0];
  if (!element) {
    pane.scrollTop = anchor.top;
    return;
  }
  pane.scrollTop += element.getBoundingClientRect().top + anchor.off - pane.getBoundingClientRect().top;
}
// ---------------- The reading spot across a reflow (docs/handbook/viewer.md §그리기)
// The column reflows the moment its width changes - a rotation, the panel collapsing beside it, a window resized, the
// outline opening - and the scroll offset alone then stands on other lines (the top line moves by tens of lines). So
// the spot is read while the width stands - on each scroll's frame and after each draw (readSpot) - and put back once
// the width has moved (keepReadingSpot): from relayout, and from the column's ResizeObserver, which runs after the
// layout and before the paint. A scroll the reflow itself makes (an offset cut back to the new height) reads only after
// the spot is back. Reads the spot now: the line element at the document area's top (lineElementAt) and how far down it
// the top is (frac, 0-1, and past: the px below the element's end when the top falls in the room after it - the rest of
// a line's leading, a block's margin, which no reflow changes; el null at the very top), the column's width and the
// pane's scroll offset (top), and whether the chosen lines (.md-sel) are on screen. A read at a width that is not the
// spot's is left for keepReadingSpot - the reflow moved what it would read - unless force (a new draw: nothing to
// keep). While the column is not laid out (hidden under the changes view, or 0 wide) nothing is read: the spot read
// before stays - a redraw there too (showDocumentNode) - for keepReadingSpot to put back once the column is shown
// again. A spot a hidden redraw left to be put back (again) is not read over before that, even at its width: the scroll
// the column's showing makes is not the person's.
function readSpot(force?: boolean) {
  const column = $('#md'),
    pane = $('#left');
  if (!isMarkdownDoc() || !column || MARKDOWN_VIEW.shown !== DOC) {
    MARKDOWN_VIEW.spot = null;
    return;
  }
  const spot = MARKDOWN_VIEW.spot,
    width = column.getBoundingClientRect().width;
  if (!isColumnLaidOut(width)) return;
  if (!force && spot && spot.doc === DOC && (spot.w !== width || spot.again)) return;
  const top = pane.getBoundingClientRect().top,
    element = pane.scrollTop > 0 ? lineElementAt(lineElements(), top) : null,
    rect = element && element.getBoundingClientRect(),
    into = rect ? top - rect.top : 0;
  MARKDOWN_VIEW.spot = {
    doc: DOC,
    w: width,
    top: pane.scrollTop,
    el: element,
    line: element ? +(element.dataset.line || element.dataset.lo || 0) : 0,
    key: element ? (element.dataset.line ? 'line' : 'lo') : '',
    frac: rect && rect.height ? Math.min(1, Math.max(0, into / rect.height)) : 0,
    past: rect ? Math.max(0, into - rect.height) : 0,
    off: null,
    sel: isChosenSeen(),
    again: false,
  };
}
// The element that stands for the spot's line now: its element if still drawn, else the one a redraw drew for that line
// - the same kind (a line span, a block starting there), else the first that carries the line (lineLeaves), else - the
// line is gone, the source got shorter - the nearest line kept before it (nearestLineElement). null: the very top.
function spotElement(spot: NonNullable<typeof MARKDOWN_VIEW.spot>) {
  if (spot.el && spot.el.isConnected) return spot.el;
  if (!spot.line) return null;
  const column = $('#md'),
    attribute = spot.key === 'lo' ? 'data-lo' : 'data-line',
    element = (column && column.querySelector('[' + attribute + '="' + spot.line + '"]')) as HTMLElement | null;
  return element || lineLeaves(spot.line, spot.line)[0] || nearestLineElement(spot.line);
}
// The last line element that starts at or before line (lineElements are in document order, their first lines never
// going back), or null when none does.
function nearestLineElement(line: number) {
  const elements = lineElements();
  let at = -1;
  for (let i = 0; i < elements.length; i++) {
    if (+(elements[i].dataset.line || elements[i].dataset.lo || 0) > line) break;
    at = i;
  }
  return at < 0 ? null : elements[at];
}
// Whether element carries line: a line span of it, or a block whose lines first..last hold it.
function carriesLine(element: HTMLElement, line: number) {
  if (element.dataset.line) return +element.dataset.line === line;
  const first = +(element.dataset.lo || 0),
    last = +(element.dataset.hi || element.dataset.lo || 0);
  return first <= line && line <= last;
}
// Puts the spot back after the column's width moved: the same point of the same line element at the area's top (as far
// into it, as far past its end; the very top stays the top), then - when the chosen lines were on screen - those lines
// back into view (revealBox, every layout), and reads the spot at the new width. Nothing moves while the width is the
// spot's - unless the document was drawn again while the column was hidden (again: the scroll offset then stands on
// other lines even at the same width) - nor while the column is not laid out (isColumnLaidOut): the spot waits for the
// column's next width. A write is held under half a pixel. During a jump to a heading (MARKDOWN_VIEW.goTo) the spot is
// only a point the scroll passes: the jump is aimed again at its heading instead (goOnToHeading).
function keepReadingSpot() {
  const spot = MARKDOWN_VIEW.spot,
    column = $('#md'),
    pane = $('#left');
  if (!spot || spot.doc !== DOC || !column || !isMarkdownDoc() || MARKDOWN_VIEW.shown !== DOC) return;
  const width = column.getBoundingClientRect().width;
  if ((width === spot.w && !spot.again) || !isColumnLaidOut(width)) return;
  if (goOnToHeading()) {
    readSpot(true);
    return;
  } // a jump in flight goes on to its heading's new place: the spot is a point it passes
  const element = spotElement(spot);
  if (!element) {
    if (pane.scrollTop > 0) pane.scrollTop = 0;
  } else {
    const rect = element.getBoundingClientRect(),
      into =
        !spot.line || carriesLine(element, spot.line)
          ? spot.off !== null
            ? spot.off
            : spot.frac * rect.height + spot.past
          : 0; // a nearer line kept: its top
    const drift = rect.top + into - pane.getBoundingClientRect().top;
    if (Math.abs(drift) >= 0.5) pane.scrollTop += drift;
  }
  if (spot.sel) revealBox(document.querySelector('#md .md-sel') as HTMLElement | null, true);
  readSpot(true);
}
// Something above the reading spot changed its height while the width stood - an image that got its size or gave way to
// its alt text (onImageLoad, onImageError): the spot is put back as after a reflow (keepReadingSpot), one model for
// both. While the column is hidden (under the changes view) nothing can be measured: the spot waits, marked again, for
// the column to be shown. The spot put back is the one refreshMovedSpot made sure of just before the change.
function putSpotBack() {
  const spot = MARKDOWN_VIEW.spot;
  if (!spot || spot.doc !== DOC) return;
  spot.again = true;
  keepReadingSpot();
}
// Just before the page changes the column's layout (an image's new size, onImageLoad, onImageError): when the pane
// stands elsewhere than where the spot was read (top, to 1px), something has moved the pane since - a scroll whose
// frame has not come (the pane's scroll listener reads on the frame, and on a renderer too busy to paint an image's
// load comes first), the browser's find, a focus or another script, the browser's scroll anchoring after another change
// - and the spot is read where the pane stands, so putSpotBack does not undo that move. The image's own change comes
// after this check (an image's box changes nowhere but in those handlers, sizeImage), but a reflow at the same width
// may have come before it - a web font swapped in, a run of HTML blocks opened or closed - and one that shortened the
// document may have moved the offset itself: the browser cuts an offset the pane can no longer scroll to back to its
// new end. That one cut, and no other offset, is not taken for a move: the offset read before beyond what the pane can
// scroll now (its end, scrollHeight - clientHeight) and the pane standing at that end, to 1px. The spot read before is
// then kept for putSpotBack to put back across the reflow, as after a width's (keepReadingSpot); a move to the end made
// before the same frame - End, or a scroll the cut then ate - goes back with it. Any other offset is a move, the cut's
// too once a move took the pane from that end (Home after a font's reflow), whatever reflowed the column: told by the
// offset and the scroll range alone, the check asks nothing of the page's other changes - whether they read the spot
// again after them. An image's own change reads it after (putSpotBack, or afterImageChange during a heading jump), so
// the next image's check starts from the layout this one left, and an End after a failed image shortened the document
// is not taken for a cut. Not while the width moved (a reflow is keepReadingSpot's), nor while a redraw or a load under
// the hidden column waits (again), nor while the column is not laid out (a hidden pane's offset reads 0).
function refreshMovedSpot() {
  const spot = MARKDOWN_VIEW.spot,
    column = $('#md'),
    pane = $('#left');
  if (!spot || spot.doc !== DOC || spot.again || !column || !isMarkdownDoc() || MARKDOWN_VIEW.shown !== DOC) return;
  const width = column.getBoundingClientRect().width;
  if (width !== spot.w || !isColumnLaidOut(width)) return;
  const end = pane.scrollHeight - pane.clientHeight;
  if (spot.top > end && pane.scrollTop >= end - 1) return; // cut back to a shorter end
  if (Math.abs(pane.scrollTop - spot.top) >= 1) readSpot(true);
}
// Whether the document column is laid out at width (#md's): shown (#left has boxes - not under the changes view) and
// wider than 0.
function isColumnLaidOut(width: number) {
  return width > 0 && isColumnShown();
}
function isColumnShown() {
  return $('#left').getClientRects().length > 0;
}
// Whether any of the chosen lines (.md-sel) stands in the part of the document area they can be seen in
// (selectionRoom).
function isChosenSeen() {
  const chosen = document.querySelector('#md .md-sel');
  if (!chosen) return false;
  const rect = chosen.getBoundingClientRect(),
    room = selectionRoom();
  return rect.bottom > room.top && rect.top < room.bottom - 8;
}
// Builds article#md from the worker's tokens (renderTokens, with MARKDOWN_VIEW as its render context), with a yield to
// the browser and a check for a newer draw whenever renderTokens pauses, or null when the elements built pass
// MARKDOWN_LIMITS.elements (stale(): a newer draw - then whatever was built is dropped too).
async function renderDocument(tokens: any[], stale: () => boolean): Promise<HTMLElement | null> {
  const root = document.createElement('article');
  root.className = 'md';
  root.id = 'md';
  root.setAttribute('translate', 'no');
  // the document's language is not known (docs/handbook/viewer.md §그리기): not the screen's (<html lang>)
  root.lang = '';
  MARKDOWN_VIEW.els = 0;
  MARKDOWN_VIEW.marked = 0;
  MARKDOWN_VIEW.tex = 0;
  MARKDOWN_VIEW.bom = String(MARKDOWN_VIEW.lines[0] || '').charCodeAt(0) === 0xfeff;
  MARKDOWN_VIEW.heads = [];
  const work = renderTokens(root, tokens, MARKDOWN_VIEW);
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
  if (MARKDOWN_VIEW.marked) root.prepend(textNotice('marks', markedCharactersText(MARKDOWN_VIEW.marked)));
  return root;
}
// The DOM build as a generator that pauses after every MARKDOWN_LIMITS.chunk units of work - a token, an inline child,
// a code line, one block of a raw HTML run - counted on one counter (work, isPauseDue) wherever they fall: one
// paragraph of 120,000 inline tokens or one code block of 30,000 lines pauses inside itself. Two or more raw HTML
// blocks in a row are one run (htmlRunElement). context is the draw's render context (RenderContext): its lines, its
// element count, its marked characters and its headings.
function* renderTokens(root: HTMLElement, tokens: any[], context: RenderContext): Generator<void, void, void> {
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
// One unit of work on counter work: true when MARKDOWN_LIMITS.chunk of them have been done since the last pause (and
// the count restarts).
function isPauseDue(work: { n: number }) {
  if (++work.n < MARKDOWN_LIMITS.chunk) return false;
  work.n = 0;
  return true;
}
const OVER_ELEMENT_LIMIT = { over: true }; // thrown by countedElement past MARKDOWN_LIMITS.elements
// One element of the drawn document, counted against MARKDOWN_LIMITS.elements on the draw's render context.
function countedElement(tag: string, context: RenderContext): HTMLElement {
  if (++context.els > MARKDOWN_LIMITS.elements) throw OVER_ELEMENT_LIMIT;
  return document.createElement(tag);
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
function tokenAttribute(token: any, name: string): string | null {
  const attributes = (token && token.attrs) || [];
  for (const pair of attributes) if (pair[0] === name) return String(pair[1]);
  return null;
}
// The lines first..last of a block token's map, its trailing blank lines (of the render context's lines) left out (a
// loose list item's map runs over them).
function tokenLines(token: any, context: RenderContext): { lo: number; hi: number } | null {
  if (!token.map) return null;
  let first = token.map[0] + 1,
    last = Math.max(first, token.map[1]);
  while (last > first && !String(context.lines[last - 1] || '').trim()) last--;
  return { lo: first, hi: last };
}
function mapLines(element: HTMLElement, token: any, kind: string, context: RenderContext) {
  const lines = tokenLines(token, context);
  if (!lines) return;
  element.dataset.lo = String(lines.lo);
  element.dataset.hi = String(lines.hi);
  element.dataset.kind = kind;
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
  function* token(markdownToken: any, work: { n: number }): Generator<void, void, void> {
    const top = stack[stack.length - 1];
    if (markdownToken.nesting === 1) {
      if (markdownToken.hidden) {
        stack.push(top);
        return;
      }
      const tag = /^[a-z][a-z0-9]*$/.test(markdownToken.tag || '') ? markdownToken.tag : 'div',
        element = countedElement(tag, context),
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
  function* run(tokens: any[], work: { n: number }): Generator<void, void, void> {
    const spans = tokens.map((htmlToken) => tokenLines(htmlToken, context));
    if (spans.some((span) => !span)) {
      for (const htmlToken of tokens) {
        yield* token(htmlToken, work);
        if (isPauseDue(work)) yield;
      }
      return;
    }
    const runElement = htmlRunElement(
        tokens.length,
        (spans[0] as { lo: number; hi: number }).lo,
        (spans[spans.length - 1] as { lo: number; hi: number }).hi,
        context,
      ),
      body = runElement.lastChild as HTMLElement;
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
  token: any,
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
// Display math (the worker's math_block token, mdMathBlock in md-parse.mjs; ADR-0032, ADR-0036): the block's lines
// (data-lo..hi, kind math - a block of its own, md:math) either drawn by KaTeX in one box (drawTexBox, with the source
// TeX on data-tex so a pin's quote is still the TeX, rangeText) or, when it is not drawn, its TeX as written in a code
// box with each line, its delimiters included, one span (data-line), as a code block's. Drawn, the block is the
// smallest thing that can be chosen in it - none of its lines can be chosen alone (ADR-0036 D3). The lines are the
// token's (indentation and quote markers left out).
function* drawMathBlock(
  token: any,
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
// A raw HTML block's placeholder: its lines (it takes a pin), their count and its first line as code, never the HTML
// itself.
function htmlPlaceholder(token: any, context: RenderContext): HTMLElement {
  const box = countedElement('div', context);
  mapLines(box, token, 'html', context);
  box.className = 'md-html';
  const lines = tokenLines(token, context),
    count = lines ? lines.hi - lines.lo + 1 : 0,
    first =
      String(token.content || '')
        .split('\n')
        .find((line) => line.trim()) || '';
  const label = countedElement('span', context);
  label.className = 'md-html-l';
  label.textContent = translateTemplate('HTML {lines}줄 · 그리지 않습니다', { lines: count });
  let head = '';
  let taken = 0;
  for (const character of first.trim()) {
    if (++taken > 120) break;
    head += character;
  } // 120 characters at most, never half of one
  const code = countedElement('code', context);
  drawTextNow(code, head, context);
  box.append(label, code);
  return box;
}
// Two or more raw HTML blocks in a row (a README's head of badges and pictures) are one placeholder, closed: a button
// naming the blocks and their lines (HTML 블록 N개 · M줄) that opens it (toggleHtmlRun), each block then its own
// placeholder that takes a pin. Only what is on screen carries lines (data-lo/hi): closed, the run stands for all its
// lines as one HTML block; open, each block for its own (holdHtmlLines keeps the other's in data-r-lo/hi). So the
// marks, the picks, the ladder and the reading line read whatever is shown and nothing hidden.
function htmlRunElement(count: number, first: number, last: number, context: RenderContext): HTMLElement {
  const run = countedElement('div', context);
  run.className = 'md-html-run';
  run.dataset.rLo = String(first);
  run.dataset.rHi = String(last);
  run.dataset.kind = 'html';
  holdHtmlLines(run, true);
  const button = countedElement('button', context) as HTMLButtonElement;
  button.type = 'button';
  button.className = 'md-html-sum';
  button.dataset.act = 'md-html-run';
  button.setAttribute('aria-expanded', 'false');
  setHtml(
    button,
    html`${lucideIcon('chevron-right')}<span>${translateTemplate('HTML 블록 {n}개 · {lines}줄 · 그리지 않습니다', { n: count, lines: last - first + 1 })}</span>`,
  ); // the chevron turns down when open (CSS)
  const body = countedElement('div', context);
  body.className = 'md-html-body';
  body.hidden = true;
  run.append(button, body);
  return run;
}
// Shows (on) or hides (off) the element's lines: data-lo/hi from its kept data-r-lo/hi, or none.
function holdHtmlLines(element: HTMLElement, on: boolean) {
  if (!element.dataset.rLo) {
    element.dataset.rLo = element.dataset.lo || '';
    element.dataset.rHi = element.dataset.hi || '';
  }
  if (on) {
    element.dataset.lo = element.dataset.rLo;
    element.dataset.hi = element.dataset.rHi || '';
  } else {
    delete element.dataset.lo;
    delete element.dataset.hi;
  }
}
// Opens or closes the run of raw HTML blocks whose button is button (data-act md-html-run), then draws the marks, the
// chosen lines and the strip again over what is shown.
function toggleHtmlRun(button: HTMLElement) {
  const run = button.closest('.md-html-run') as HTMLElement | null,
    body = run && (run.querySelector('.md-html-body') as HTMLElement | null);
  if (!run || !body) return;
  const open = button.getAttribute('aria-expanded') !== 'true';
  holdHtmlLines(run, !open);
  body.querySelectorAll('.md-html').forEach((placeholder) => holdHtmlLines(placeholder as HTMLElement, open));
  body.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  drawPinMarks();
  markChosenLines(shownChoice());
  updateMarkdownStrip();
}
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
  token: any,
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
  let stack = [makeLineSpan(lineInfo.lo)] as HTMLElement[];
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
            const copy = open.cloneNode(false) as HTMLElement;
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
// ---------------- Relative references: the manuscript tree (ADR-0030)
// A relative reference of the document whose file is at tree path base ('docs/guide.md'), resolved in the manuscript
// tree (pure): {path, frag} - path tree-relative and normalized, frag the part after '#', both percent-decoded once
// (markdown-it encodes a link's destination) - or {out:true} for one that climbs above the tree's root or a document
// outside the tree (base null), {bad:true} for a dot-named part ('.git', '.env'), a backslash, a control character or
// an escape that does not decode; null for no relative reference at all (a scheme, '//host', '#…' alone, nothing). A
// leading '/' is the tree's root, as GitHub reads it in a repository; '?…' is dropped. The server checks again what it
// is asked (GET /api/asset).
function treePath(
  reference: unknown,
  base: string | null,
):
  | { path: string; frag: string; out?: undefined; bad?: undefined }
  | { out: true; bad?: undefined; path?: undefined }
  | { bad: true; out?: undefined; path?: undefined }
  | null {
  const text = String(reference == null ? '' : reference).trim();
  if (!text || text.startsWith('#') || text.startsWith('//') || /^[a-z][a-z0-9+.-]*:/i.test(text)) return null;
  const hash = text.indexOf('#'),
    query = text.indexOf('?'),
    end = Math.min(query < 0 ? text.length : query, hash < 0 ? text.length : hash);
  let path = text.slice(0, end),
    fragment = hash < 0 ? '' : text.slice(hash + 1);
  try {
    path = decodeURIComponent(path);
    fragment = decodeURIComponent(fragment);
  } catch (error) {
    return { bad: true };
  }
  if (!path) return null;
  if (/[\\\x00-\x1f\x7f]/.test(path)) return { bad: true };
  if (base == null) return { out: true };
  const parts = path.startsWith('/') ? [] : String(base).split('/').slice(0, -1);
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (!parts.length) return { out: true };
      parts.pop();
      continue;
    }
    if (part.startsWith('.')) return { bad: true };
    parts.push(part);
  }
  return parts.length ? { path: parts.join('/'), frag: fragment } : null;
}
// The image suffixes GET /api/asset serves (limn.documents.assets.ASSET_TYPES), and whether a tree path has one. Pure.
const IMAGE_SUFFIXES = Object.freeze(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']);
function isImagePath(path: string) {
  const match = /\.([A-Za-z0-9]+)$/.exec(path);
  return !!match && IMAGE_SUFFIXES.includes(match[1].toLowerCase());
}
// The tree path of the document on screen (its /api/docs path), or null when it lies outside the tree (the path is
// absolute).
function documentTreePath() {
  const entry = docInfo(DOC),
    path = entry ? String(entry.path || '') : '';
  return path && !path.startsWith('/') ? path : null;
}
// The address an image of the tree loads from: this origin's read-only GET /api/asset, built here from the checked path
// and never from the document's text. Pure.
function assetUrl(doc: string | null, path: string) {
  return '/api/asset?doc=' + encodeURIComponent(String(doc || '')) + '&path=' + encodeURIComponent(path);
}
// What an image's source loads (pure, base as treePath's): {path} for a file of the tree with an image suffix, or {why}
// - 'remote' (http(s) or '//host': the third party would learn who opened the document, and when, from where), 'data'
// (the page policy has no data: images), 'out' (above the tree's root, a dot-named part), 'type' (no image suffix),
// 'other' (any other scheme, nothing).
function imageSource(
  raw: unknown,
  base: string | null,
): { path: string; why?: undefined } | { why: 'remote' | 'data' | 'out' | 'type' | 'other'; path?: undefined } {
  const text = String(raw == null ? '' : raw).trim();
  if (/^(https?:)?\/\//i.test(text)) return { why: 'remote' };
  if (/^data:/i.test(text)) return { why: 'data' };
  const relative = treePath(text, base);
  if (!relative) return { why: 'other' };
  if (relative.out || relative.bad) return { why: 'out' };
  return isImagePath(relative.path) ? { path: relative.path } : { why: 'type' };
}
// What a link may do (pure): linkHref's answer when it opens; else, for a relative reference that stays in the tree,
// another registered document whose path it names ({open:'doc', key, id: its '#…', name}) or an image of the tree
// ({open:'asset', href: its tree path, opened in a new tab through GET /api/asset); else inert ({open:null}) with why:
// 'out' (it leaves the tree) or 'unregistered' (a file of the tree that is no document here) or '' (linkHref's own
// refusals).
function linkAction(
  raw: unknown,
  origin: string,
  base: string | null,
  docs: { key: string; path?: string; name?: string }[],
): {
  open: 'web' | 'mail' | 'anchor' | 'doc' | 'asset' | null;
  href: string;
  id?: string;
  key?: string;
  name?: string;
  why?: string;
} {
  const plain = linkHref(raw, origin);
  if (plain.open) return plain;
  const reference = treePath(raw, base);
  if (!reference) return { open: null, href: plain.href, why: '' };
  if (reference.out || reference.bad) return { open: null, href: plain.href, why: 'out' };
  const document = docs.find((entry) => String(entry.path || '') === reference.path);
  if (document)
    return {
      open: 'doc',
      href: reference.path,
      key: document.key,
      id: reference.frag,
      name: String(document.name || document.key),
    };
  if (isImagePath(reference.path)) return { open: 'asset', href: reference.path };
  return { open: null, href: plain.href, why: 'unregistered' };
}
// An image of the document (an inline image token): a file of the tree is an <img> from GET /api/asset, lazily loaded,
// in a box that keeps a place for it (12rem x 8rem, CSS) until its size is known - at once when an earlier draw learned
// it (IMAGE_SIZES) - and once it loads the reading spot is put back (onImageLoad), so an image above the reading line
// never moves the text being read. Anything else is the image's alt text, with why it is not loaded in the tip.
function* drawImage(token: any, work: { n: number }, context: RenderContext): Generator<void, HTMLElement, void> {
  const raw = String(tokenAttribute(token, 'src') || ''),
    alt = String(token.content || tokenAttribute(token, 'alt') || ''),
    place = imageSource(raw, documentTreePath());
  if (place.path) {
    const box = countedElement('span', context),
      img = countedElement('img', context) as HTMLImageElement;
    box.className = 'md-pic';
    box.dataset.path = place.path;
    img.alt = alt;
    img.loading = 'lazy';
    img.decoding = 'async';
    img.draggable = false;
    const known = IMAGE_SIZES.get(place.path);
    if (known) {
      sizeImage(img, known.w, known.h);
      box.classList.add('md-pic-ok');
    }
    img.addEventListener('load', onImageLoad);
    img.addEventListener('error', onImageError);
    img.src = imageUrl(DOC, place.path);
    box.appendChild(img);
    return box;
  }
  const fallback = countedElement('span', context),
    shownSource = markHiddenPlain(raw);
  fallback.className = 'md-img';
  fallback.append(translate('그림') + ': ');
  // the alt text is drawn text, as the paragraph's, its marked characters in their boxes, pausing as it does
  yield* drawText(fallback, alt || raw, work, context);
  fallback.dataset.tip =
    place.why === 'remote'
      ? translateTemplate('원격 그림은 불러오지 않습니다 · {src}', { src: shownSource })
      : place.why === 'out'
        ? translateTemplate('원고 밖의 그림은 불러오지 않습니다 · {src}', { src: shownSource })
        : translateTemplate('이 그림은 불러오지 않습니다 · {src}', { src: shownSource });
  fallback.dataset.tipUrl = shownSource;
  return fallback;
}
// The natural size of each tree image this tab has loaded, by tree path: a redraw or a return to the document keeps
// their places.
const IMAGE_SIZES = new Map() as Map<string, { w: number; h: number }>;
// An image has loaded: its size is kept (IMAGE_SIZES) and given to its box, and the reading spot (MARKDOWN_VIEW.spot,
// as readSpot last read it, or read again just before the change when the pane was moved since: refreshMovedSpot) is
// put back (putSpotBack) - only an image above it moves anything. During a jump to a heading (goToHeading) the spot is
// a point the scroll passes on its way: the jump goes on to its heading's new place instead (goOnToHeading,
// afterImageChange). A box drawn at a size an earlier load learned is checked too: the file may have changed since (a
// new size under the same path), and then it is resized and the spot put back as for a first load. Only a size that
// held changes nothing. The marks follow through the column's ResizeObserver (COLUMN_OBSERVER).
function onImageLoad(event: Event) {
  const img = event.target as HTMLImageElement,
    box = img.parentElement;
  if (!box) return;
  void noteShownTag(img.getAttribute('src') || '');
  const width = img.naturalWidth,
    height = img.naturalHeight,
    path = box.dataset.path || '';
  if (width && height) IMAGE_SIZES.set(path, { w: width, h: height });
  else IMAGE_SIZES.delete(path);
  if (
    box.classList.contains('md-pic-ok') &&
    +(img.getAttribute('width') || 0) === width &&
    +(img.getAttribute('height') || 0) === height
  )
    return;
  const here = box.isConnected && isMarkdownDoc();
  if (here) refreshMovedSpot();
  sizeImage(img, width, height);
  box.classList.add('md-pic-ok');
  if (here) afterImageChange();
}
// After an image's box changed (onImageLoad, onImageError): the reading spot put back (putSpotBack), or - during a jump
// to a heading - the jump aimed again at its heading's new place (goOnToHeading) and the spot read where the pane
// stands, in the layout the change left. The spot's offset (top) is then the page's own after the change: an End or a
// scroll after it is not taken for the browser's cut (refreshMovedSpot) when the change shortened the document - a
// failed image's alt text in place of its box - and the next image's check reads it where it stands.
function afterImageChange() {
  if (goOnToHeading()) readSpot(true);
  else putSpotBack();
}
// Gives image img the size width x height (its natural size, from a load): its width and height attributes, and the
// aspect ratio its box keeps (CSSOM --md-pic-r, md-surface.css). With height:auto the attributes alone give way to the
// ratio of whatever picture the element shows (aspect-ratio: auto width / height), and the browser takes a new
// picture's ratio as soon as it knows its size, before the load event: a box drawn at a size an earlier load learned,
// or given a new address by a check (checkTreeImages), would change shape outside onImageLoad - a document's end cut
// back before refreshMovedSpot, which takes that cut for the layout's and undoes with it a move to that end made before
// (End). Held to width / height, the box changes only here, after the check. 0 x 0 (no natural size): none of the
// three.
function sizeImage(img: HTMLImageElement, width: number, height: number) {
  if (width && height) {
    img.width = width;
    img.height = height;
    img.style.setProperty('--md-pic-r', width + ' / ' + height);
    return;
  }
  img.removeAttribute('width');
  img.removeAttribute('height');
  img.style.removeProperty('--md-pic-r');
}
// ---------------- A tree image changed on disk (docs/handbook/viewer.md §그림)
// The page keeps the picture it decoded for an address as long as it lives (HTML's list of available images), so
// without a check an image rewritten on disk would show only after a reload: a redraw draws the same address again. On
// the light poll (documents/flow-polling.ts), the tree images that have loaded on screen or within one document area's
// height of it - the nearest IMAGE_CHECK.max of them (among as near, the one asked longest ago first: more than that
// many on screen take turns), at most once every IMAGE_CHECK.gap ms, one request at a time - are asked again: fetch(…,
// {cache:'no-cache'}) revalidates with the tag the browser holds (an unchanged image is a stat and a 304 on the server,
// AssetTags) and reads the ETag. An image whose tag moved on gets its address with &v=<the new tag> (the server reads
// only doc and path): one the page has not decoded, so the browser loads the new picture, and the box keeps the reading
// spot as for any image that loads (onImageLoad -> putSpotBack). The tag of the picture an address shows is read once
// that picture has loaded, from the answer the <img> left in the browser's cache (noteShownTag, cache:'only-if-cached':
// never the server). Without one - the cache was cleared or is off, or the entry is gone - the shown tag is unknown,
// and the check does not take the server's tag for it (that one may be of a newer file, and then no later check would
// differ): it moves the image once to the address of the tag now, so what it shows is known from then on. The version
// is kept per document and path (IMAGE_VERSIONS), so a redraw or a return to the document draws the new picture too. No
// route, no field: only GET /api/asset. at: for each document, tree path -> when a check last asked it, for the paths
// the document shows now (no other bound, so no image's turn is ever forgotten while it is on the page).
const IMAGE_CHECK = {
  max: 6,
  gap: 4000,
  last: -Infinity,
  busy: false,
  asked: 0,
  at: new Map() as Map<string, Map<string, number>>,
};
const IMAGE_TAGS = new Map() as Map<string, string>; // an address -> the ETag of the picture an image at it shows
const IMAGE_VERSIONS = new Map() as Map<string, string>; // doc + '\n' + tree path -> the version its address carries
const IMAGE_MAP_LIMIT = 256; // the most entries either map keeps, the oldest dropped first
// The address the tree image at path loads from now: assetUrl's, with the version a check found (IMAGE_VERSIONS).
function imageUrl(doc: string | null, path: string) {
  const version = IMAGE_VERSIONS.get(String(doc || '') + '\n' + path);
  return assetUrl(doc, path) + (version ? '&v=' + encodeURIComponent(version) : '');
}
function keepRecent(map: Map<string, string>, key: string, value: string) {
  map.delete(key);
  map.set(key, value);
  while (map.size > IMAGE_MAP_LIMIT) {
    const first = map.keys().next().value;
    if (first === undefined) break;
    map.delete(first);
  }
}
// The ETag GET url answers with (cache: the fetch's cache mode), or '' for none - a refusal, no answer, nothing cached
// for 'only-if-cached'. Its body is not read.
async function fetchImageTag(url: string, cache: RequestCache): Promise<string> {
  try {
    const response = await fetch(url, { cache, credentials: 'same-origin', mode: 'same-origin' }),
      tag = response.ok ? response.headers.get('ETag') || '' : '';
    if (response.body) response.body.cancel().catch(() => {});
    return tag;
  } catch (error) {
    return '';
  }
}
// A tree image has loaded from address url: the tag of the picture it shows, from the answer the <img> left in the
// cache, unless a check already knows it (IMAGE_TAGS). Nothing cached: it stays unknown (checkTreeImages).
async function noteShownTag(url: string) {
  if (!url || IMAGE_TAGS.has(url)) return;
  const tag = await fetchImageTag(url, 'only-if-cached');
  if (tag && !IMAGE_TAGS.has(url)) keepRecent(IMAGE_TAGS, url, tag);
}
// One check of the tree images near the document area (the header above): how many were given a new address.
async function checkTreeImages(): Promise<number> {
  const now = performance.now(),
    docKey = DOC;
  if (
    IMAGE_CHECK.busy ||
    now - IMAGE_CHECK.last < IMAGE_CHECK.gap ||
    !isMarkdownDoc() ||
    isTextDoc() ||
    MARKDOWN_VIEW.shown !== docKey ||
    !isColumnShown() ||
    document.hidden
  )
    return 0;
  const paneRect = $('#left').getBoundingClientRect(),
    near = [] as { img: HTMLImageElement; d: number }[],
    shown = new Set();
  for (const img of [...document.querySelectorAll('#md .md-pic img')] as HTMLImageElement[]) {
    const path = img.parentElement && img.parentElement.dataset.path;
    if (path) shown.add(path);
    if (!img.complete || !img.naturalWidth) continue;
    const rect = img.getBoundingClientRect(),
      distance =
        rect.bottom < paneRect.top
          ? paneRect.top - rect.bottom
          : rect.top > paneRect.bottom
            ? rect.top - paneRect.bottom
            : 0;
    if (distance <= paneRect.height) near.push({ img, d: distance });
  }
  let at = IMAGE_CHECK.at.get(docKey || '');
  if (!at) {
    at = new Map();
    IMAGE_CHECK.at.set(docKey || '', at);
  }
  // an image no longer in the document has no turn to keep
  for (const path of [...at.keys()]) if (!shown.has(path)) at.delete(path);
  if (!near.length) return 0;
  // Nearest first; among images as near (every visible one is at 0) the one asked longest ago first, a never-asked one
  // before all, so past six visible images the checks take turns instead of asking the same six every time.
  const asked = (image: HTMLImageElement) =>
    at.get((image.parentElement && image.parentElement.dataset.path) || '') || 0;
  near.sort((left, right) => left.d - right.d || asked(left.img) - asked(right.img));
  IMAGE_CHECK.busy = true;
  IMAGE_CHECK.last = now;
  let count = 0,
    moved = 0;
  const seen = new Set();
  try {
    for (const { img } of near) {
      const box = img.parentElement,
        path = box && box.dataset.path,
        url = img.getAttribute('src') || '';
      if (count >= IMAGE_CHECK.max) break;
      if (!path || !url || seen.has(path)) continue;
      seen.add(path);
      count++;
      at.set(path, now);
      const was = IMAGE_TAGS.get(url) || '';
      IMAGE_CHECK.asked++;
      const tag = await fetchImageTag(url, 'no-cache');
      if (docKey !== DOC || MARKDOWN_VIEW.shown !== docKey) break; // another document since: its images are its own
      if (!tag) continue;
      if (tag === was) {
        keepRecent(IMAGE_TAGS, url, was);
        continue;
      } // was '': what it shows is unknown, so it moves to the address of the tag now
      keepRecent(IMAGE_VERSIONS, docKey + '\n' + path, tag.replace(/^W\//, '').replace(/"/g, ''));
      const next = imageUrl(docKey, path);
      keepRecent(IMAGE_TAGS, next, tag);
      if (next === url) continue; // unknown, but already at that tag's address: taken as showing it
      for (const box of [...document.querySelectorAll('#md .md-pic')] as HTMLElement[])
        if (box.dataset.path === path) {
          const image = box.querySelector('img');
          if (image && image.getAttribute('src') !== next) image.src = next;
        }
      moved++;
    }
  } finally {
    IMAGE_CHECK.busy = false;
  }
  return moved;
}
// An image the server would not give (not there, not that format, outside the tree behind a link, too large): its alt
// text, as for an image that is never loaded, saying so in the tip.
function onImageError(event: Event) {
  const img = event.target as HTMLImageElement,
    box = img.parentElement;
  if (!box || !box.isConnected) return;
  const fallback = document.createElement('span'),
    path = box.dataset.path || '';
  fallback.className = 'md-img';
  fallback.append(translate('그림') + ': ');
  drawTextLate(fallback, img.alt || path, renderContextOf(box));
  const plainPath = markHiddenPlain(path);
  fallback.dataset.tip = translateTemplate('그림을 불러오지 못했습니다 · {src}', { src: plainPath });
  fallback.dataset.tipUrl = plainPath;
  const here = isMarkdownDoc();
  if (here) refreshMovedSpot(); // the spot where the pane stands, before the alt text takes the box's place
  box.replaceWith(fallback);
  if (here) afterImageChange();
}
// Every tip of an image or a link below names the hidden characters of the source text it shows again - a path or a
// '#…' decoded once, a document's name (markHiddenPlain, platform/hidden-chars.ts, ADR-0029 D5); the drawn text, an alt
// text too, is the document's. A link element for href (linkAction): a web or mail link opens in a new tab without a
// referrer or opener; an in-document '#…' goes to the heading it names (data-act md-anchor: a click or Enter, the
// global key handler asking imeKey first); another registered document is data-act md-doc (goToDocLink), the same way;
// an image of the tree opens in a new tab from GET /api/asset; anything else is inert text with its target, and why, in
// the tip.
function drawLink(href: unknown, context: RenderContext): HTMLElement {
  const target = linkAction(href, location.origin, documentTreePath(), DOCS);
  if (target.open === 'web' || target.open === 'mail') {
    const link = countedElement('a', context) as HTMLAnchorElement;
    link.href = target.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.dataset.tip = link.dataset.tipUrl = markHiddenPlain(target.href);
    return link;
  }
  if (target.open === 'anchor') {
    const link = countedElement('a', context);
    link.className = 'md-anchor';
    link.dataset.act = 'md-anchor';
    link.dataset.anchor = target.id || '';
    link.setAttribute('role', 'link');
    link.tabIndex = 0;
    return link;
  }
  if (target.open === 'doc') {
    const link = countedElement('a', context);
    link.className = 'md-doclink';
    link.dataset.act = 'md-doc';
    link.dataset.doc = target.key || '';
    link.dataset.anchor = target.id || '';
    link.setAttribute('role', 'link');
    link.tabIndex = 0;
    link.dataset.tip =
      translateTemplate('문서로 이동 · {name}', { name: markHiddenPlain(target.name || '') }) +
      (target.id ? ' #' + markHiddenPlain(target.id) : '');
    link.dataset.tipUrl = markHiddenPlain(target.href);
    return link;
  }
  if (target.open === 'asset') {
    const link = countedElement('a', context) as HTMLAnchorElement,
      url = assetUrl(DOC, target.href);
    link.className = 'md-asset';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    const path = markHiddenPlain(target.href);
    link.dataset.tip = translateTemplate('그림을 새 탭에서 엽니다 · {path}', { path });
    link.dataset.tipUrl = path;
    return link;
  }
  // A link that does not open: a disabled link to assistive technology, reachable by Tab (the focus shows its
  // description, as a hover does), and a tap shows the description instead of picking the block (pickSelection).
  const shown = markHiddenPlain(target.href),
    inert = countedElement('span', context),
    tip =
      target.why === 'out'
        ? translateTemplate('원고 밖을 가리켜 열지 않습니다 · {href}', { href: shown })
        : target.why === 'unregistered'
          ? translateTemplate('등록된 문서가 아니라 열지 않습니다 · {href}', { href: shown })
          : translateTemplate('이 링크는 열지 않습니다 · {href}', { href: shown });
  inert.className = 'md-rel';
  inert.dataset.tip = tip;
  inert.dataset.tipUrl = shown;
  inert.tabIndex = 0;
  inert.setAttribute('role', 'link');
  inert.setAttribute('aria-disabled', 'true');
  inert.setAttribute('aria-description', tip);
  return inert;
}
// A link to another registered document (data-act md-doc): that document, at its '#heading' once it is drawn here
// (MARKDOWN_VIEW.headTo, showDocumentNode), with a history entry of its own - the browser's back returns to the
// document left through the hashchange switch (documents/flow-switch.ts), and a back before the document has opened
// ends that switch (NAVGEN). While a back layer holds the entry on top (a sheet on a phone, layout/input.ts) no entry
// is added, as a tab switch adds none; the layer's entry must stay the top one. Followed again while the switch it
// started still waits for that document (a double click, switchPending), it adds no second entry and starts no second
// switch: it only names the heading to go to.
function goToDocLink(link: HTMLElement) {
  const docKey = String(link.dataset.doc || ''),
    id = String(link.dataset.anchor || ''),
    entry = docInfo(docKey);
  if (!entry) return;
  if (docKey === DOC) {
    if (id) goToSlug(id);
    return;
  }
  if (!switchPending(docKey)) {
    if (!BACK) history.pushState(null, '', location.pathname + location.search + '#doc=' + docKey);
    void switchDoc(docKey);
  }
  MARKDOWN_VIEW.headTo = rendersInBrowser(entry.kind)
    ? { doc: docKey, id: showsSourceLines(entry.kind) ? '' : id, seq: SWITCHSEQ }
    : null;
} // a text document has no headings
// The document a link of another one switched to is drawn (showDocumentNode): it goes to the link's heading (goToSlug),
// and the focus, which the link took away with the document it was in, goes there too - from the document area or the
// page's body (focusFell), as a browser moves it to the fragment a link names - so a screen reader reads that heading
// and the next Tab goes on from it, not from the document's first link. A focus put anywhere else since stays; so does
// one in a composer that is open or being opened (a draft the switch brought back, typed into while the source was on
// its way), a pick on its way, or an input method's composition - focusPlace's guards; a link without a heading (a text
// document has none) leaves the focus on the document area.
function goToLinkHeading(id: string) {
  const index = id ? goToSlug(id) : -1,
    pane = $('#left');
  if (COMPOSE.current || COMPOSE.picking || !$('#composer').hidden || imeOpen()) return;
  if (document.activeElement !== pane && !focusFell()) return;
  const heading = MARKDOWN_VIEW.heads[index];
  focusHold(heading ? heading.el : pane);
}
// GitHub's heading slug: lower case, punctuation dropped, spaces to '-'. Pure.
function headingSlug(title: string) {
  return String(title)
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}
// An in-document link to '#id': the first heading whose slug is id (or id percent-decoded), as GitHub numbers repeats
// (slug, slug-1, ...). Nothing when no heading has it.
function goToAnchor(link: HTMLElement) {
  goToSlug(String(link.dataset.anchor || ''));
}
function goToSlug(id: string): number {
  let want = id;
  try {
    want = decodeURIComponent(want);
  } catch (error) {}
  want = want.toLowerCase();
  const seen = new Map();
  let at = -1;
  MARKDOWN_VIEW.heads.forEach((heading, index) => {
    if (at >= 0) return;
    const repeats = seen.get(heading.slug) || 0;
    seen.set(heading.slug, repeats + 1);
    if ((repeats ? heading.slug + '-' + repeats : heading.slug) === want) at = index;
  });
  if (at >= 0) goToHeading(at);
  return at;
}
// ---------------- Picking: selection -> lines, and the ladder
// The lines a DOM point is on: its line span's, else its nearest block's range, else null (outside the document).
function linesAt(node: Node | null) {
  const element = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
  if (!element) return null;
  const column = $('#md');
  if (!column || !column.contains(element)) return null;
  // The nearest carrier wins. A drawn formula that was cut at a line end sits inside the span of the line it starts in
  // and carries the lines it covers itself (drawInline): those are the point's lines, not that one line's.
  const near = element.closest('[data-line],[data-lo]') as HTMLElement | null;
  if (near && column.contains(near)) {
    const line = +(near.dataset.line || 0);
    if (line) return { lo: line, hi: line };
    if (near.dataset.lo !== undefined) return { lo: +(near.dataset.lo || 0), hi: +(near.dataset.hi || 0) };
  }
  const block = element.closest('[data-lo]') as HTMLElement | null;
  return block && column.contains(block) ? { lo: +(block.dataset.lo || 0), hi: +(block.dataset.hi || 0) } : null;
}
// The block a point belongs to for the ladder's second rung: a table row's table, a list item's or a quote's
// paragraph's item or quote, else its nearest block (a run of text whose lines could not be told - kind 'lines',
// drawInline - stands for the block it is in).
function blockAt(node: Node | null) {
  const element = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
  if (!element) return null;
  let block = element.closest('#md [data-lo]') as HTMLElement | null;
  if (block && block.dataset.kind === 'lines' && block.parentElement)
    block = block.parentElement.closest('#md [data-lo]') as HTMLElement | null;
  if (!block) return null;
  if (block.dataset.kind === 'row') block = (block.closest('table[data-lo]') as HTMLElement | null) || block;
  else if (
    block.dataset.kind === 'paragraph' &&
    block.parentElement &&
    /^(item|quote)$/.test(block.parentElement.dataset.kind || '')
  )
    block = block.parentElement; // a list item's or a quote's own paragraph is that block
  // A heading or a rule is no block of its own (ADR-0025 D3's block kinds): the block it stands in, if any, is.
  while (block && !BLOCK_KINDS.includes(block.dataset.kind || ''))
    block = block.parentElement ? (block.parentElement.closest('#md [data-lo]') as HTMLElement | null) : null;
  return block;
}
// The block kinds a block rung takes (its pin kind is md:<kind>, ADR-0025 D3; front, math: ADR-0032) and their names on
// the ladder.
const BLOCK_KINDS = ['paragraph', 'item', 'table', 'code', 'quote', 'html', 'front', 'math'];
const BLOCK_SELECTOR = BLOCK_KINDS.map((kind) => '[data-lo][data-kind="' + kind + '"]').join(',');
// The blocks lines first..last meet, outermost: each element of a block kind on screen whose lines meet first..last and
// that no other such element meeting them holds (a quote's paragraphs are the quote; a list's items are each a block).
function blocksMeeting(first: number, last: number) {
  const column = $('#md');
  if (!column) return [];
  const meets = (element: HTMLElement) => +(element.dataset.lo || 0) <= last && +(element.dataset.hi || 0) >= first;
  return ([...column.querySelectorAll(BLOCK_SELECTOR)] as HTMLElement[]).filter((element) => {
    if (!meets(element)) return false;
    const up = (element.parentElement && element.parentElement.closest(BLOCK_SELECTOR)) as HTMLElement | null;
    return !(up && column.contains(up) && meets(up));
  });
}
const BLOCK_LABEL: Record<string, string> = {
  paragraph: '문단',
  item: '목록 항목',
  table: '표',
  code: '코드 블록',
  quote: '인용',
  html: 'HTML 블록',
  front: '머리 정보',
  math: '수식',
};
function lineSnippet(first: number, last: number) {
  const out: string[] = [];
  for (let line = first; line <= Math.min(last, first + 79); line++)
    out.push(String(line).padStart(5, ' ') + '  ' + (MARKDOWN_VIEW.lines[line - 1] || ''));
  if (last - first + 1 > 80) out.push('      … ' + translateTemplate('{n}줄 더', { n: last - first + 1 - 80 }));
  return out.join('\n');
}
// The section around lines first..last: from the nearest heading at or above first to the line before the next heading
// of the same or a higher level (the file's end when none), its trailing blank lines left out. null above the first
// heading, or when last is past it.
function sectionAround(first: number, last: number) {
  let heading = null as { level: number; lo: number; title: string } | null;
  for (const head of MARKDOWN_VIEW.heads) {
    if (head.lo <= first) heading = head;
    else break;
  }
  if (!heading) return null;
  let end = MARKDOWN_VIEW.lines.length;
  for (const head of MARKDOWN_VIEW.heads) {
    if (head.lo > heading.lo && head.level <= heading.level) {
      end = head.lo - 1;
      break;
    }
  }
  while (end > heading.lo && !String(MARKDOWN_VIEW.lines[end - 1] || '').trim()) end--;
  if (end < last) return null;
  return { lo: heading.lo, hi: end, title: heading.title };
}
// The ladder for lines range (a drag or a tap) and the blocks its start and end are in (startBlock, endBlock: blockAt):
// the chosen lines, the block when both ends are in one - else, when they meet two or more blocks (blocksMeeting),
// those blocks whole ('블록 N개', level blocks: saved as lines, kindFor) - and the heading's section; a rung with the
// range of one before it merges into that one. A block rung carries its block kind as env (kindFor: md:<kind>). A tap
// (tapped) picks its block: when the block is no more than the tapped lines (an HTML block, a one-line paragraph) its
// rung stands first and the chosen lines merge into it, so the pin is md:<kind> as any other tapped block's - merged
// the other way, the tap's block would be saved as lines.
function markdownLevels(
  range: { lo: number; hi: number },
  startBlock: HTMLElement | null,
  endBlock: HTMLElement | null,
  tapped?: boolean,
) {
  if (isTextDoc()) return textSurface().levels(range); // a text document's rungs come from its lines alone
  const rungs = [] as any[];
  const add = (level: string, label: string, first: number, last: number, env: string | null) => {
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
      env: env || null,
    });
  };
  const kind = startBlock && startBlock === endBlock ? startBlock.dataset.kind || 'paragraph' : '',
    blockStart = startBlock ? Math.min(+(startBlock.dataset.lo || 0), range.lo) : 0,
    blockEnd = startBlock ? Math.max(+(startBlock.dataset.hi || 0), range.hi) : 0;
  const blockFirst = !!(tapped && kind && blockStart === range.lo && blockEnd === range.hi);
  if (blockFirst) add('block', BLOCK_LABEL[kind] || '블록', blockStart, blockEnd, kind);
  add('raw', '고른 줄', range.lo, range.hi, null);
  if (kind) {
    if (!blockFirst) add('block', BLOCK_LABEL[kind] || '블록', blockStart, blockEnd, kind);
  } else {
    const blocks = blocksMeeting(range.lo, range.hi);
    if (blocks.length > 1)
      add(
        'blocks',
        translateTemplate('블록 {n}개', { n: blocks.length }),
        Math.min(range.lo, ...blocks.map((block) => +(block.dataset.lo || 0))),
        Math.max(range.hi, ...blocks.map((block) => +(block.dataset.hi || 0))),
        null,
      );
  }
  const section = sectionAround(range.lo, range.hi);
  // the heading's hidden characters by name (clipMarkedText, ADR-0029 D5)
  if (section)
    add('section', translate('절') + ' · ' + clipMarkedText(section.title, 18), section.lo, section.hi, null);
  return rungs;
}
// Fills the composer with lines range of the document on screen, as pick() does with a /api/pick answer; tapped: a tap
// picked a block, so the block rung is the default (the section rung on a heading). During a re-place it is the
// candidate instead (bannerCompare), with nothing else changed.
function pickLines(
  range: { lo: number; hi: number },
  startBlock: HTMLElement | null,
  endBlock: HTMLElement | null,
  quote: string,
  tapped: boolean,
) {
  const levels = markdownLevels(range, startBlock, endBlock, tapped),
    quoted = String(quote || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 160);
  const head = tapped && MARKDOWN_VIEW.heads.some((heading) => heading.lo === range.lo && heading.lo === range.hi);
  const defaultLevel =
    // a tap on a text document picks its line
    tapped && !isTextDoc() && levelOf({ levels }, head ? 'section' : 'block') ? (head ? 'section' : 'block') : 'raw';
  const selection = {
    doc: DOC,
    file: MARKDOWN_VIEW.file,
    name: MARKDOWN_VIEW.name,
    lo: range.lo,
    hi: range.hi,
    raw_lo: range.lo,
    raw_hi: range.hi,
    kind: 'lines',
    score: null,
    warn: null,
    snippet: lineSnippet(range.lo, range.hi),
    levels,
    default_level: defaultLevel,
    n_lines: MARKDOWN_VIEW.lines.length,
    quote: quoted,
    overlaps: [],
  } as unknown as Selection;
  if (REPICK) {
    REPICK.cand = selection;
    linePick().compare();
    return;
  }
  endTopic(NOTICE_TOPIC.PICK);
  setPickseq(PICKSEQ + 1);
  setComposeCurrent(selection);
  setComposeIntent(COMPOSE.intent + 1);
  setComposePicking(false);
  selection.scope = null;
  selection.elSel = null;
  useLevel(selection, defaultLevel);
  $('#composer').hidden = false;
  linePick().setBusy(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  setSide(true);
  applySide();
  setComposeDismissedOverlap(null);
  selection.overlaps = overlapsFor(selection, PINS);
  setSnipOpen(false);
  linePick().renderComposer();
  linePick().renderVerdictRow();
  $('#composer').scrollTop = 0;
  if (LAYOUT !== LAYOUT_MODE.WIDE) $('#right').scrollTop = 0;
  // the chosen lines out from under the sheet (compact), as a PDF box is
  revealBox(document.querySelector('#md .md-sel') as HTMLElement | null);
  if (LAST_POINTER === 'mouse') $('#note').focus({ preventScroll: true });
}
// The ladder of an edit card on a pin of this document: its lines' rungs from the drawn document (markdownLevels), or
// none when the document on screen is another or is not drawn (the line view, a notice) - the card then keeps the lines
// it has.
function editCardLevels(edit: { doc?: string | null; lo?: number | null; hi?: number | null }) {
  if (!isMarkdownDoc() || edit.doc !== DOC || typeof edit.lo !== 'number' || typeof edit.hi !== 'number') return null;
  const first = lineLeaves(edit.lo, edit.lo)[0],
    last = lineLeaves(edit.hi, edit.hi)[0];
  if (!first && !last) return null;
  const rungs = markdownLevels(
    { lo: edit.lo, hi: edit.hi },
    first ? blockAt(first) : null,
    last ? blockAt(last) : null,
  );
  return rungs.length > 1 ? rungs : null;
}
// What the document marks as chosen: a re-place's candidate while there is one - the lines of the rung its banner names
// (bannerCompare), as the PDF surface draws its box - else the composer's selection (null: nothing).
function shownChoice(): { file?: string; lo?: number | null; hi?: number | null; kind?: string } | null {
  const candidate = REPICK && REPICK.cand;
  if (!candidate) return COMPOSE.current;
  const level = levelOf(candidate, candidate.default_level) || candidate;
  return { file: candidate.file, lo: level.lo, hi: level.hi, kind: candidate.kind };
}
// The chosen lines drawn on the document: their line spans and blocks get .md-sel (null clears), and the reading spot
// learns whether they are on screen (keepReadingSpot brings them back after a reflow only then).
function markChosenLines(
  chosen: { file?: string; lo?: number | null; hi?: number | null; kind?: string; pdf?: string } | null,
) {
  $$('#md .md-sel').forEach((element) => element.classList.remove('md-sel'));
  if (chosen && isMarkdownDoc() && chosen.file === MARKDOWN_VIEW.file && !isRegion(chosen))
    lineLeaves(chosen.lo as number, chosen.hi as number).forEach((element) => element.classList.add('md-sel'));
  if (MARKDOWN_VIEW.spot && MARKDOWN_VIEW.spot.doc === DOC && isColumnShown()) MARKDOWN_VIEW.spot.sel = isChosenSeen();
} // hidden, nothing is on screen: what was stays
// The elements that stand for lines first..last: each line span in range, and each block in range that has no line
// spans of its own and no smaller block in range (a rule, an HTML block) - the smallest things on screen that carry
// those lines. A table cell's line stands for its row: the row is what is tinted, so a pinned row reads as one band.
function lineLeaves(first: number, last: number) {
  const column = $('#md');
  if (!column) return [];
  const lines = [...column.querySelectorAll('[data-line]')].filter((element) => {
    const line = +((element as HTMLElement).dataset.line || 0);
    return line >= first && line <= last;
  });
  const blocks = [...column.querySelectorAll('[data-lo]')].filter((element) => {
    const block = element as HTMLElement,
      start = +(block.dataset.lo || 0),
      end = +(block.dataset.hi || 0);
    return start <= last && end >= first && !block.querySelector('[data-line],[data-lo]');
  });
  const out = new Set();
  for (const element of [...lines, ...blocks]) {
    const row = element.closest('tr[data-lo]');
    out.add(row && column.contains(row) ? row : element);
  }
  return [...out] as HTMLElement[];
}
// ---------------- Pins on the document
// The marks of the pins on screen (marks()' branch): each pin's lines get .md-pin (review .rv, lost .st), and the first
// of them a number badge in the left gutter that jumps to the card (data-act mark-jump, as on a PDF page). The badges
// are drawn in line order, each layer just before the block of #md its line is in: Tab and a screen reader meet a badge
// where its line is - appended at the column's end they would come after the last link, in pin order (#1 L3, #2 L55, #4
// L9). The badge's name and description (its tip: '#1 · L3-L5 · <note>') are what marks the pinned lines for them,
// colour aside.
function drawPinMarks() {
  const column = $('#md');
  if (!column) return;
  column.querySelectorAll('.md-badges').forEach((element: Element) => element.remove());
  column.querySelectorAll('.md-pin').forEach((element: Element) => element.classList.remove('md-pin', 'rv', 'st'));
  const pins = PINS.concat(REVIEW_ALL.filter((pin) => pdoc(pin) === DOC))
    .filter((pin) => !isRegion(pin) && typeof pin.lo === 'number' && typeof pin.hi === 'number')
    .sort((left, right) => (left.lo as number) - (right.lo as number) || left.id - right.id);
  const rows = new Map() as Map<number, HTMLElement>,
    top = column.getBoundingClientRect().top;
  for (const pin of pins) {
    const leaves = lineLeaves(pin.lo as number, pin.hi as number);
    if (!leaves.length) continue;
    const inReview = pinState(pin) === PIN_STATE.REVIEW,
      lost = !!pin.stale;
    leaves.forEach((element) => {
      element.classList.add('md-pin');
      if (inReview) element.classList.add('rv');
      if (lost) element.classList.add('st');
    });
    // The badge stands in the column's left gutter at the height of the pin's first line (a layer of #md, never inside
    // a paragraph, list or table, so it moves no text). Pins whose first lines share a height stack down.
    const y = Math.round(leaves[0].getBoundingClientRect().top - top);
    let box = rows.get(y);
    if (!box) {
      box = document.createElement('span');
      box.className = 'md-badges';
      box.setAttribute('translate', 'no');
      box.style.top = y + 'px';
      const at = topBlockOf(column, leaves[0]);
      ((at && at.parentElement) || column).insertBefore(box, at);
      rows.set(y, box);
    }
    const badge = document.createElement('button');
    badge.type = 'button';
    badge.className = 'md-badge' + (inReview ? ' rv' : '') + (lost ? ' st' : '');
    badge.dataset.act = 'mark-jump';
    badge.dataset.id = String(pin.id);
    badge.dataset.pin = String(pin.id);
    badge.textContent = String(pin.id);
    badge.setAttribute('aria-label', translateTemplate('핀 #{id} 카드로 이동', { id: pin.id }));
    const note = String(pin.note || '')
      .replace(/\s+/g, ' ')
      .trim();
    badge.dataset.tip =
      '#' +
      pin.id +
      ' · ' +
      lineRange(pin.lo as number, pin.hi as number) +
      ' · ' +
      (note ? (note.length > 60 ? note.slice(0, 60) + '…' : note) : translate('(메모 없음)'));
    box.appendChild(badge);
  }
}
// The child of column (#md) that holds element (null: element is not inside it) - where a badge layer goes in the
// document's order, a child of #md still, so it stands in the gutter and no block's text (a quote, a tap's block) takes
// its number. A text document's lines are all one block (.tx-src, text/view.ts), so there the layer goes before
// element's line span itself, a
// sibling of the lines and in no line's text: before the whole text, every badge would be read before the first line.
function topBlockOf(column: HTMLElement, element: Element): Element | null {
  let child = element as Element | null;
  const isText = column.classList.contains('tx');
  while (
    child &&
    child.parentElement !== column &&
    !(isText && child.parentElement && child.parentElement.classList.contains('tx-src'))
  )
    child = child.parentElement;
  return child;
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
// Scrolls pin id's first line to the reading depth and flashes its lines (jumpPin's branch, showLines). A jump asked
// before this document is on screen - [보기] on a pin of another document: switchDoc settles before the source is read
// and drawn - waits for the draw (showDocumentNode) of this visit; another switch drops it.
function jumpToPinLines(id: number) {
  if (MARKDOWN_VIEW.shown !== DOC || !$('#md')) {
    MARKDOWN_VIEW.jumpTo = { id, doc: DOC, seq: SWITCHSEQ };
    return;
  }
  const pin = PINS.find((candidate) => candidate.id === id) || REVIEW_ALL.find((candidate) => candidate.id === id);
  if (!pin || typeof pin.lo !== 'number' || typeof pin.hi !== 'number') return;
  const leaves = lineLeaves(pin.lo, pin.hi);
  if (leaves.length) showLines(leaves);
}
// Scrolls the first of the line elements to the reading depth (30% down the document area) and flashes them - a pin's
// [보기] (jumpToPinLines) and [바뀐 곳] (goToNextChange, documents/flow-updates.ts) - and reads the reading spot where
// that put the pane: the page's own jump is over at once, so its place is the spot before the scroll's frame reads it
// (as a heading jump's once it lands, endLandedJump). A width that changes before that frame puts back the jump's place
// (keepReadingSpot), not the one read before it.
function showLines(elements: HTMLElement[]) {
  const pane = $('#left'),
    paneRect = pane.getBoundingClientRect(),
    rect = elements[0].getBoundingClientRect();
  endJumpForScroll();
  pane.scrollTop += rect.top - (paneRect.top + paneRect.height * 0.3);
  readSpot(true);
  elements.forEach((element) => {
    element.classList.remove('md-flash');
    void element.offsetWidth;
    element.classList.add('md-flash');
  });
  setTimeout(() => elements.forEach((element) => element.classList.remove('md-flash')), 1200);
}
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
  MARKDOWN_VIEW.at = readingLine();
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
let STRIP_FRAME = 0;
$('#left').addEventListener(
  'scroll',
  () => {
    if (!isMarkdownDoc() || STRIP_FRAME) return;
    STRIP_FRAME = requestAnimationFrame(() => {
      STRIP_FRAME = 0;
      endLandedJump();
      updateMarkdownStrip();
      readSpot();
    });
  },
  { passive: true },
);
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
let PDF_HINT_NODES = null as Node[] | null;
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
// Goes to heading index: the pane scrolls (smoothly unless reduced motion is asked for) until the heading stands 8px
// under its top. The jump is kept in flight (MARKDOWN_VIEW.goTo) until it lands there (endLandedJump) or the person
// scrolls: an image that gets its size on the way - a lazy one the scroll passes - moves the heading, and the jump goes
// on to its new place (goOnToHeading).
function goToHeading(index: number) {
  const heading = MARKDOWN_VIEW.heads[index];
  if (!heading) return;
  setOutlineSelected(index);
  markOutline();
  MARKDOWN_VIEW.goTo = { el: heading.el, doc: DOC };
  goOnToHeading();
  endLandedJump();
}
// The scroll top that puts element 8px under the pane's top, within what the pane can scroll.
function headingScrollTop(element: HTMLElement) {
  const pane = $('#left'),
    top = pane.scrollTop + element.getBoundingClientRect().top - pane.getBoundingClientRect().top - 8;
  return Math.max(0, Math.min(top, pane.scrollHeight - pane.clientHeight));
}
// Scrolls on to the destination of the jump in flight, measured again; false when there is none (or its heading is
// gone).
function goOnToHeading() {
  const jump = MARKDOWN_VIEW.goTo;
  if (!jump) return false;
  if (jump.doc !== DOC || !jump.el.isConnected) {
    MARKDOWN_VIEW.goTo = null;
    return false;
  }
  endJumpForScroll();
  $('#left').scrollTo({ top: headingScrollTop(jump.el), behavior: scrollMotion() });
  return true;
}
// The jump in flight has landed when the pane stands at its destination: it ends, and that is the reading spot.
function endLandedJump() {
  const jump = MARKDOWN_VIEW.goTo;
  if (!jump) return;
  if (jump.doc !== DOC || !jump.el.isConnected) {
    MARKDOWN_VIEW.goTo = null;
    return;
  }
  if (Math.abs($('#left').scrollTop - headingScrollTop(jump.el)) <= 1) {
    MARKDOWN_VIEW.goTo = null;
    readSpot(true);
  }
}
// The person scrolls (a wheel, a touch, a press on the pane or its scroll bar, a key): a jump in flight ends where it
// is - its smooth scroll too, running or only asked for, so what the person's input does next starts from here. The
// pane's offset is written a pixel off and back, in one task (nothing is drawn between) - down at the very top, up
// elsewhere, so the first write moves at either end (Home's place, End's): a write of the offset it already has does
// not end the scroll in Firefox, whose compositor (APZ) runs it - once that scroll has moved the pane, such a write
// sends the compositor nothing, and the scroll would go on to the heading with the key's or the wheel's own step added.
// A write that moves the offset ends it there, in every engine.
function stopHeadingJump() {
  if (!MARKDOWN_VIEW.goTo) return;
  MARKDOWN_VIEW.goTo = null;
  const pane = $('#left'),
    top = pane.scrollTop;
  pane.scrollTo({ top: top > 0 ? top - 1 : top + 1, behavior: 'instant' });
  pane.scrollTo({ top: top, behavior: 'instant' });
}
for (const eventType of ['wheel', 'touchstart', 'pointerdown'])
  $('#left').addEventListener(eventType, stopHeadingJump, { passive: true });
// A key scrolls the pane when nothing else has the focus or something in the pane has it - pdf/view-outline.ts's scope
// (SCROLL_KEYS): with the focus on the page's body, Home or PageDown scrolls the pane without a key event on it.
addEventListener('keydown', (event) => {
  const active = document.activeElement;
  if (SCROLL_KEYS.has(event.key) && (!active || active === document.body || $('#left').contains(active)))
    stopHeadingJump();
});
// ---------------- Input on the document
// A mouse drag ends: the part of its text selection inside the document (documentPart) is the pick. A press without a
// selection (a click, a tap) picks the block under it - not on a link, a badge or another control.
function pickSelection(tapTarget: EventTarget | null) {
  const selection = window.getSelection(),
    column = $('#md');
  if (!column || !column.matches('article')) return false;
  if (selection && !selection.isCollapsed && selection.rangeCount) {
    const selected = selection.getRangeAt(0),
      range = documentPart(selected, column);
    if (!range) return false;
    let startLines = linesAt(range.startContainer),
      endLines = linesAt(range.endContainer);
    if (!startLines || !endLines) return false;
    // A selection that ends before any character of its last line (a triple click ends at the start of the next block)
    // does not take that line: nothing of it is selected. An end documentPart cut back to the document's last element
    // is no such end - the selection ran past that element, which may have no character of its own (a closing rule, an
    // empty code block).
    const cut = range !== selected && !column.contains(selected.endContainer);
    if (endLines.lo > startLines.hi && !cut && takesNothingOfEnd(range)) {
      const before = endLines.lo - 1;
      endLines = { lo: Math.max(startLines.lo, before), hi: Math.max(startLines.lo, before) };
    }
    let first = Math.min(startLines.lo, endLines.lo),
      last = Math.max(startLines.hi, endLines.hi);
    while (last > first && !String(MARKDOWN_VIEW.lines[last - 1] || '').trim()) last--;
    // A document that drew math reads its quote through rangeText, where each drawn formula gives back its source TeX;
    // one that drew none reads the selection's own text (ADR-0036 D4).
    pickLines(
      { lo: first, hi: last },
      blockAt(range.startContainer),
      blockAt(range.endContainer),
      range === selected && !MARKDOWN_VIEW.tex ? selection.toString() : rangeText(widenToFormulas(range)),
      false,
    );
    return true;
  }
  if (tapTarget) {
    const target = tapTarget as Element;
    const inertLink = target.closest('#md .md-rel') as HTMLElement | null;
    if (inertLink && LAST_POINTER !== 'mouse') {
      showInertTip(inertLink);
      return true;
    } // a finger has no hover
    if (target.closest('a,button,[data-act],.md-badges,.md-limit')) return false;
    const carrier = target.closest('#md [data-lo],#md [data-line]') as HTMLElement | null;
    if (!carrier) return false;
    const head = MARKDOWN_VIEW.heads.find(
      (heading) => heading.el === target.closest('#md h1,#md h2,#md h3,#md h4,#md h5,#md h6'),
    );
    const lines = head
        ? { lo: head.lo, hi: head.lo }
        : linesAt(target) || { lo: +(carrier.dataset.lo || 0), hi: +(carrier.dataset.hi || 0) },
      block = blockAt(target);
    // the front matter's head line is the viewer's words, not the source's
    const said = block && block.dataset.kind === 'front' ? block.querySelector('pre') : null;
    pickLines(lines, block, block, elementText(said || block || carrier), true);
    return true;
  }
  return false;
}
// The part of a selection's range inside the document column: the range itself when it lies inside; else the range cut
// back to the document's first and last line elements where it runs past them - a triple click on the last paragraph
// ends after the article, there being no next block inside it to end at, and a drag may start above it. One end must be
// in the document: a selection with both ends outside it (select-all, one made in the side panel) is no pick - null, as
// for one that does not reach it or one that, cut back, takes nothing of it (from above the document to its very
// start).
function documentPart(range: Range, column: HTMLElement) {
  if (column.contains(range.commonAncestorContainer)) return range;
  if (!column.contains(range.startContainer) && !column.contains(range.endContainer)) return null;
  const elements = lineElements();
  if (!elements.length) return null;
  // The start goes to the first element that carries lines and holds none of its own (a paragraph's first line span,
  // not the paragraph: that would read as all its lines); the last element in document order is always such a leaf.
  const first = elements.find((element) => !element.querySelector('[data-line],[data-lo]')) || elements[0];
  const part = range.cloneRange();
  if (!column.contains(range.startContainer)) part.setStart(first, 0);
  if (!column.contains(range.endContainer)) {
    const last = elements[elements.length - 1];
    part.setEnd(last, last.childNodes.length);
  }
  return part.collapsed ? null : part;
}
// The text a range shows, as the selection's own toString gives it: its contents laid out once off screen, under the
// document's own .md rules (an HTML placeholder's label and code stack as on screen), and read as innerText. A range's
// toString runs blocks together ('First.Last.'), the renderer putting no whitespace between them; the selection itself
// is not touched, as changing it would set off the touch screen's resting-selection pick again. The pin badges standing
// between blocks (drawPinMarks) are the viewer's, not the document's text: they are left out. A marked character's box
// (hiddenBox) gives its character, where it stands. innerText does not: Chromium reads the box's hidden child, out of
// the line's flow, as a block of its own ('x\n\u202e\ny'), and Firefox drops a bidirectional control from innerText
// altogether. So each box stands in the copy as U+FFF0 - a character of the repertoire, which the document's own text
// therefore never holds raw - and gets its character back after. A drawn formula (data-tex, ADR-0036 D4) goes the same
// way, as U+FFF1, and gets its source TeX back: innerText would read the glyphs KaTeX drew (and the MathML copy beside
// them), and an agent looks for the TeX the manuscript holds. A formula stands in a block or an inline slot as it did
// on screen, so the blocks around it still read apart.
function rangeText(range: Range) {
  const box = document.createElement('div'),
    copy = document.createElement('div');
  box.className = 'sr-only';
  box.setAttribute('aria-hidden', 'true');
  copy.className = 'md';
  copy.append(range.cloneContents());
  copy.querySelectorAll('.md-badges').forEach((element) => element.remove());
  const tex = [] as string[];
  copy.querySelectorAll('[data-tex]').forEach((element) => {
    tex.push(element.getAttribute('data-tex') || '');
    const slot = document.createElement(element.classList.contains('md-math-block') ? 'div' : 'span');
    slot.textContent = '\ufff1';
    element.replaceWith(slot);
  });
  const kept = [] as string[];
  copy.querySelectorAll('.cc').forEach((element) => {
    kept.push(element.textContent || '');
    element.replaceWith('\ufff0');
  });
  box.append(copy);
  document.body.append(box);
  try {
    let boxAt = 0,
      texAt = 0;
    return copy.innerText.replace(/[\ufff0\ufff1]/g, (found) =>
      found === '\ufff0' ? kept[boxAt++] || '' : tex[texAt++] || '',
    );
  } finally {
    box.remove();
  }
}
// The range with either end inside a drawn formula moved out to that formula's edge - a clone, the selection itself is
// never touched - so a selection that cuts into drawn math reads that formula whole, by its source TeX. The range
// itself when neither end is in one.
function widenToFormulas(range: Range): Range {
  const formulaAt = (node: Node | null) => {
    const element = node && (node.nodeType === 1 ? (node as Element) : node.parentElement);
    return element ? (element.closest('#md [data-tex]') as HTMLElement | null) : null;
  };
  const startFormula = formulaAt(range.startContainer),
    endFormula = formulaAt(range.endContainer);
  if (!startFormula && !endFormula) return range;
  const widened = range.cloneRange();
  if (startFormula) widened.setStartBefore(startFormula);
  if (endFormula) widened.setEndAfter(endFormula);
  return widened;
}
// The text an element shows, as rangeText reads a range: a tap's quote. A drawn formula tapped whole is its source TeX
// - selectNodeContents would leave the element itself, which carries data-tex, outside the range.
function elementText(element: Element) {
  const tex = element instanceof HTMLElement ? element.dataset.tex : undefined;
  if (tex !== undefined) return tex;
  const range = document.createRange();
  range.selectNodeContents(element);
  return rangeText(range);
}
// Shows a link's description that does not open (a tap on it), until 4s pass or the next press.
function showInertTip(element: HTMLElement) {
  showTip(element);
  const shown = TIP.textContent;
  setTimeout(() => {
    if (!TIP.hidden && TIP.textContent === shown) hideTip();
  }, 4000);
}
// Whether the range takes no visible character of the line (or block) its end is in.
function takesNothingOfEnd(range: Range) {
  const element =
    range.endContainer.nodeType === 1 ? (range.endContainer as Element) : range.endContainer.parentElement;
  if (!element) return false;
  const host = element.closest('[data-line]') || element.closest('[data-lo]');
  if (!host) return false;
  const head = document.createRange();
  head.setStart(host, 0);
  head.setEnd(range.endContainer, range.endOffset);
  return !head.toString().trim();
}
// A release's pick waits one task, for the selection its press made, and it is that press's alone: once the next press
// is down (a double or triple click's next press, which a busy page takes ahead of the timer) it does nothing - that
// press picks at its own release. Run then, it would take the new press's selection, the note field's focus would take
// that selection away, and the click that follows would count as a tap and choose the block. PRESS_COUNT counts the
// document's primary presses.
let PRESS_COUNT = 0;
$('#doc').addEventListener('mousedown', (event: MouseEvent) => {
  if (event.button === 0) PRESS_COUNT++;
});
$('#doc').addEventListener('mouseup', (event: MouseEvent) => {
  if (!isMarkdownDoc() || event.button !== 0) return;
  const press = PRESS_COUNT;
  setTimeout(() => {
    if (press === PRESS_COUNT) pickSelection(null);
  }, 0);
});
$('#doc').addEventListener('click', (event: MouseEvent) => {
  if (!isMarkdownDoc()) return;
  const selection = window.getSelection();
  if (selection && !selection.isCollapsed) return;
  pickSelection(event.target);
});
// A finger: the long-press handles make a selection with no mouseup; it is picked once it rests.
let SELECTION_TIMER = 0;
document.addEventListener('selectionchange', () => {
  if (!isMarkdownDoc() || !COARSE_POINTER_QUERY.matches) return;
  clearTimeout(SELECTION_TIMER);
  SELECTION_TIMER = setTimeout(() => {
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed) pickSelection(null);
  }, 500);
});
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
  MARKDOWN_VIEW,
  MARKDOWN_LIMITS,
  OVER_ELEMENT_LIMIT,
  isMarkdownPin,
  readingAnchor,
  buildMarkdownDoc,
  formatCount,
  isPauseDue,
  editCardLevels,
  goToAnchor,
  goToDocLink,
  goToHeading,
  showMarkdownHint,
  toggleHtmlRun,
  jumpToPinLines,
  lineLeaves,
  limitText,
  drawPinMarks,
  formatMebibytes,
  checkTreeImages,
  markdownPositionLabel,
  relevelForLineView,
  renderTokens,
  newRenderContext,
  keepRenderContext,
  markChosenLines,
  shownChoice,
  showLines,
  lineSnippet,
  keepReadingSpot,
  updateMarkdownStrip,
  waitLine,
  yieldToBrowser,
  srcLines,
  textNotice,
  namesViewText,
  markedCharactersText,
  showTextHint,
};
