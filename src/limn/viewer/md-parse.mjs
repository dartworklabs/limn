// The Markdown parse worker (docs/handbook/viewer.md §Markdown 화면, ADR-0025 D7): GET /md-parse.mjs, a module worker of
// its own, never a part of the page. The page's md-surface.js starts it from this origin (no blob: worker, ADR-0026) the
// first time a Markdown document opens, sends it the source lines joined with "\n" and the limits, and builds the DOM
// itself from what comes back; the page stops it (terminate) when the time limit passes or newer source comes.
// It parses with the vendored markdown-it - raw HTML as its own tokens, no linkify, no typographer - and answers
//   {id, ok:true, tokens}  the token stream as plain objects (a Token's prototype does not survive postMessage): per
//                          token its type, tag, nesting, map, content, info, hidden, level, attrs and children;
//   {id, ok:false, limit, count, max}  when a limit is hit, and no tokens: 'nesting' when a block token or an inline
//                          child reaches level max-1 (markdown-it drops what lies deeper without a word, so reaching it
//                          counts as over), 'blocks' or 'inlines' when there are more tokens than max;
//   {id, ok:false, limit:'error'}  when parsing throws.
import markdownit from '/vendor/markdown-it/markdown-it.esm.min.mjs?v=__MARKDOWN_IT_VERSION__';

let md = null, nesting = 0;
function plain(t) {
  return {type: t.type, tag: t.tag, nesting: t.nesting, map: t.map, content: t.content, info: t.info, hidden: t.hidden,
    level: t.level, attrs: t.attrs, children: t.children ? t.children.map(plain) : null};
}
self.onmessage = e => {
  const {id, text, limits} = e.data;
  try {
    if (!md || nesting !== limits.nesting) {
      md = markdownit({html: true, linkify: false, typographer: false, maxNesting: limits.nesting});
      nesting = limits.nesting;
    }
    const tokens = md.parse(text, {});
    let inlines = 0, deepest = 0;
    for (const t of tokens) {
      deepest = Math.max(deepest, t.level);
      if (t.children) { inlines += t.children.length; for (const c of t.children) deepest = Math.max(deepest, c.level); }
    }
    if (deepest >= limits.nesting - 1) return postMessage({id, ok: false, limit: 'nesting', count: deepest + 1, max: limits.nesting});
    if (tokens.length > limits.blocks) return postMessage({id, ok: false, limit: 'blocks', count: tokens.length, max: limits.blocks});
    if (inlines > limits.inlines) return postMessage({id, ok: false, limit: 'inlines', count: inlines, max: limits.inlines});
    postMessage({id, ok: true, tokens: tokens.map(plain)});
  } catch (err) {
    postMessage({id, ok: false, limit: 'error', message: String(err && err.message || err)});
  }
};
