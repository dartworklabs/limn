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
// One block rule of Limn's own is added (mdParser): YAML front matter (mdFrontMatter, ADR-0032 제안).
import markdownit from '/vendor/markdown-it/markdown-it.esm.min.mjs?v=__MARKDOWN_IT_VERSION__';

// The parser as the viewer configures it: raw HTML as tokens, no linkify, no typographer, nesting cut at `nesting`, and the
// front matter rule before every other block rule (it answers on the first line only).
function mdParser(nesting) {
  const md = markdownit({html: true, linkify: false, typographer: false, maxNesting: nesting});
  md.block.ruler.before('table', 'front_matter', mdFrontMatter, {alt: []});
  return md;
}
// A markdown-it block rule: YAML front matter at the very top of the document (ADR-0032 제안, docs/superpowers/specs/
// 2026-11-05-more-line-formats.md). Pandoc's yaml_metadata_block start and end, made a little stricter so that ordinary
// Markdown is never taken for it: the first line is '---' (after a byte order mark, if any; trailing blanks allowed), the
// next line is not blank and opens a YAML mapping - a key and its colon, or a '#' comment - and a later line is '---' or
// '...'. Anything else is left to the other rules, which read it as before (a rule, a setext heading, a paragraph). The
// token is front_matter with map [0, the closing line + 1] and info the closing marker; its lines are shown as the server's
// lines (md-surface.js), never parsed as YAML - nothing in them is a link, an image or markup.
function mdFrontMatter(state, start, end, silent) {
  if (start !== 0 || state.sCount[0] !== 0) return false;
  const line = n => state.src.slice(state.bMarks[n], state.eMarks[n]);
  if (!/^﻿?---[ \t]*$/.test(line(0)) || end < 3) return false;
  if (!/^[ \t]*(#|[^\s:#][^:\n]*:([ \t]|$))/.test(line(1))) return false;
  let close = -1;
  for (let n = 2; n < end; n++) if (/^(---|\.\.\.)[ \t]*$/.test(line(n))) { close = n; break; }
  if (close < 0) return false;
  if (silent) return true;
  const t = state.push('front_matter', '', 0);
  t.block = true; t.map = [0, close + 1]; t.info = line(close).trim(); t.markup = '---';
  t.content = state.src.slice(state.bMarks[1], state.eMarks[close - 1]);
  state.line = close + 1;
  return true;
}

let md = null, nesting = 0;
function plain(t) {
  return {type: t.type, tag: t.tag, nesting: t.nesting, map: t.map, content: t.content, info: t.info, hidden: t.hidden,
    level: t.level, attrs: t.attrs, children: t.children ? t.children.map(plain) : null};
}
self.onmessage = e => {
  const {id, text, limits} = e.data;
  try {
    if (!md || nesting !== limits.nesting) {
      md = mdParser(limits.nesting);
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
