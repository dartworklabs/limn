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
// Rules of Limn's own are added (mdParser, ADR-0032 제안): YAML front matter (mdFrontMatter) and TeX math kept as written
// (mdMathBlock, mdMathInline).
import markdownit from '/vendor/markdown-it/markdown-it.esm.min.mjs?v=__MARKDOWN_IT_VERSION__';

// The parser as the viewer configures it: raw HTML as tokens, no linkify, no typographer, nesting cut at `nesting`, the
// front matter rule before every other block rule (it answers on the first line only), the display math rule where a
// fence would be read (it may end a paragraph, as a fence may) and the inline math rule before the backslash escapes (it
// reads '\(' first; '\$' it leaves to them, a dollar sign).
function mdParser(nesting) {
  const md = markdownit({html: true, linkify: false, typographer: false, maxNesting: nesting});
  md.block.ruler.before('table', 'front_matter', mdFrontMatter, {alt: []});
  md.block.ruler.before('fence', 'math_block', mdMathBlock, {alt: ['paragraph', 'reference', 'blockquote', 'list']});
  md.inline.ruler.before('escape', 'math_inline', mdMathInline);
  return md;
}
// TeX math is kept as written (ADR-0032 제안, docs/superpowers/specs/2026-11-05-more-line-formats.md §수식): nothing is
// rendered, but no emphasis, link or escape takes a character inside it. The delimiters are Pandoc's tex_math_dollars and
// tex_math_single_backslash: each opening one and the one that closes it.
const MD_MATH = Object.freeze({'$$': '$$', '$': '$', '\\(': '\\)', '\\[': '\\]'});
// The index in s, from i up to max, of the first closing delimiter close that neither a backslash nor a code span takes, or
// -1. In TeX '\$' is a dollar sign and '\\' a backslash, so a backslash and the character after it are passed over; a code
// span binds tighter than anything but HTML and autolinks (CommonMark), so one is passed over whole (mdTickEnd) - '$10, and
// `$x$` on the next line' is no math. A scan that found none is kept on memo (one per inline token: its state): a later
// scan for the same delimiter from that point on, within no more text, finds none either, so ten thousand '\(' without a
// '\)' are read once, not once each.
function mdMathEnd(s, i, max, close, memo) {
  const no = memo && memo[close];
  if (no && i >= no[0] && max <= no[1]) return -1;
  for (let k = i; k < max; k++) {
    if (s.startsWith(close, k)) return k;
    const c = s.charCodeAt(k);
    if (c === 0x5c) k++;
    else if (c === 0x60) k = mdTickEnd(s, k, max) - 1;
  }
  if (memo) memo[close] = [i, max];
  return -1;
}
// The index just past the code span whose opening backtick run starts at k - closed by the next run of as many backticks -
// or just past that run when none follows before max (CommonMark: then the backticks are text).
function mdTickEnd(s, k, max) {
  let n = k;
  while (n < max && s.charCodeAt(n) === 0x60) n++;
  for (let j = n; j < max;) {
    if (s.charCodeAt(j) !== 0x60) { j++; continue; }
    let e = j;
    while (e < max && s.charCodeAt(e) === 0x60) e++;
    if (e - j === n - k) return e;
    j = e;
  }
  return n;
}
// A markdown-it inline rule: math within a block's text - '$$…$$' and '\(…\)', and '$…$' when a non-space follows the opening
// '$' and the first '$' after it has a non-space before it and no digit after it (Pandoc's rule: '$5 and $10' is text). The
// first closing delimiter ends the math; something but blanks must lie between, or there is no math at that delimiter.
// '\[…\]' is display math only on lines of its own (mdMathBlock): in a line it is two escaped brackets, as before. The math
// may run over line ends (a paragraph's): it becomes one math_inline token per source line, its text as written, delimiters
// included, with a softbreak between them, so the inline token's line breaks still match its source's line ends and its lines
// can be told (md-surface.js mdInlineLines, ADR-0025 D7). A code span, a link or raw HTML that starts before the delimiter has
// taken its text already; one inside the math is math, but no delimiter inside a code span closes it (mdMathEnd).
function mdMathInline(state, silent) {
  const s = state.src, at = state.pos, c = s.charCodeAt(at);
  if (c !== 0x24 && c !== 0x5c) return false;
  const open = s.startsWith('$$', at) ? '$$' : c === 0x24 ? '$' : s.startsWith('\\(', at) ? '\\(' : '';
  if (!open) return false;
  const close = MD_MATH[open], end = mdMathEnd(s, at + open.length, state.posMax, close, state.mdMath || (state.mdMath = {}));
  if (end < 0) return false;
  const tex = s.slice(at + open.length, end);
  if (!tex.trim()) return false;
  if (open === '$' && (/\s/.test(tex[0]) || /\s/.test(tex[tex.length - 1]) || /[0-9]/.test(s[end + 1] || ''))) return false;
  if (!silent) {
    s.slice(at, end + close.length).split('\n').forEach((piece, i) => {
      if (i) state.push('softbreak', 'br', 0);
      const t = state.push('math_inline', 'code', 0);
      t.content = piece; t.markup = open;
    });
  }
  state.pos = end + close.length;
  return true;
}
// A markdown-it block rule: display math - '$$' or '\[' opening a line (indented less than code) whose first closing '$$' or
// '\]' ends a line, with no blank line and no line of an outer block between (TeX allows no paragraph break in math either):
// a block of its own, math_block, map [first, closing + 1], content its lines as written - indentation and quote markers
// left out, as a fence's - one per source line. A closing delimiter with text after it is left to the paragraph and its
// inline rule. The first closing delimiter is the one the inline rule would find in the paragraph those lines make: a code
// span binds tighter (D6), also one that runs over a line end, so the search carries it from line to line (mdMathBlockEnd).
function mdMathBlock(state, start, end, silent) {
  if (state.sCount[start] - state.blkIndent >= 4) return false;
  const s = state.src, b = state.bMarks[start] + state.tShift[start];
  const open = s.startsWith('$$', b) ? '$$' : s.startsWith('\\[', b) ? '\\[' : '';
  if (!open) return false;
  const [close, n] = mdMathBlockEnd(state, start, b + 2, end, MD_MATH[open]);
  if (close < 0 || s.slice(close + 2, state.eMarks[n]).trim() || !s.slice(b + 2, close).trim()) return false;
  if (silent) return true;
  const t = state.push('math_block', 'math', 0);
  t.block = true; t.map = [start, n + 1]; t.markup = open;
  t.content = state.getLines(start, n + 1, state.sCount[start], false);
  state.line = n + 1;
  return true;
}
// Where display math opened on line start closes: [the index of the first closing delimiter close from `from` on, its line],
// or [-1, -1] when a blank line, a line of an outer block (indented less than the block) or end comes first. Each line is
// read from its content start (bMarks + tShift: indentation and quote markers left out), as the paragraph's inline text
// would have it; a backslash and the character after it are passed over, and so is a code span, whose closing backticks
// may lie on a later line (mdTickClose). The search from a line start it reaches outside a code span goes on the same way
// whichever line it began on, so what it found from there is kept (mdMathMemo): a later search that reaches that line start
// - from a later opening line, or the paragraph asking each of its lines whether math ends it - stops there, and eight
// thousand '\[' lines without a '\]' are read once, not once each.
function mdMathBlockEnd(state, start, from, end, close) {
  const s = state.src, memo = mdMathMemo(state, end, close), seen = [];
  let n = start, k = from, found = null;
  while (!found) {
    const le = state.eMarks[n];
    if (k >= le) {
      n++;
      if (mdMathStop(state, n, end)) found = [-1, -1];
      else if (memo.lines.has(n)) found = memo.lines.get(n);
      else { seen.push(n); k = state.bMarks[n] + state.tShift[n]; }
      continue;
    }
    const c = s.charCodeAt(k);
    if (s.startsWith(close, k)) found = [k, n];
    else if (c === 0x5c) k += 2;
    else if (c !== 0x60) k++;
    else {
      let r = k;
      while (r < le && s.charCodeAt(r) === 0x60) r++;
      const after = mdTickClose(state, r - k, r, n, end);
      if (after) [n, k] = after;
      else k = r;
    }
  }
  for (const m of seen) memo.lines.set(m, found);
  return found;
}
// What mdMathBlockEnd keeps for one search range (state.mdMathBlock, which lives as long as the parse): one entry per
// container - the range's end line, the container's indentation and nesting level - and closing delimiter, since a quote or
// a list item reads the same lines from another content start. lines: line -> what a search from its start found.
function mdMathMemo(state, end, close) {
  const all = state.mdMathBlock || (state.mdMathBlock = new Map()), key = close + ' ' + end + ' ' + state.blkIndent + ' ' + state.level;
  let memo = all.get(key);
  if (!memo) all.set(key, memo = {lines: new Map()});
  return memo;
}
// Where the code span whose opening run of len backticks ends at r on line n closes: [its line, the index just past its
// closing run] - the next run of exactly len backticks, on this line or a later one before a blank line or a line of an
// outer block (a code span runs over line ends, CommonMark) - or null when there is none: then the backticks are text. The
// run is looked up (mdTickRuns), not searched for: a thousand '\[' lines that each end in a run of a length of its own
// would otherwise read the rest of the document once per line. Only the lines up to the one it lies on are asked whether
// they end the search, as they stand now: a quote or a list item reads the same lines otherwise.
function mdTickClose(state, len, r, n, end) {
  const at = mdTickRuns(state).get(len);
  if (!at) return null;
  let lo = 0, hi = at.pos.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (at.pos[mid] < r) lo = mid + 1;
    else hi = mid;
  }
  if (lo === at.pos.length) return null;
  for (let m = n + 1; m <= at.line[lo]; m++) if (mdMathStop(state, m, end)) return null;
  return [at.line[lo], at.pos[lo] + len];
}
// The source's backtick runs by length, read once per parse (state.mdTick): len -> {pos, line}, each run's start and line
// in source order. A line's runs are the same whichever container reads it: a content start (bMarks + tShift) passes over
// blanks, quote markers and a list marker, never a backtick, so the runs of a line read from it are the runs of the line.
function mdTickRuns(state) {
  if (state.mdTick) return state.mdTick;
  const s = state.src, runs = new Map();
  for (let j = 0, line = 0; j < s.length;) {
    const c = s.charCodeAt(j);
    if (c !== 0x60) { if (c === 0x0a) line++; j++; continue; }
    let e = j;
    while (e < s.length && s.charCodeAt(e) === 0x60) e++;
    let at = runs.get(e - j);
    if (!at) runs.set(e - j, at = {pos: [], line: []});
    at.pos.push(j); at.line.push(line);
    j = e;
  }
  return state.mdTick = runs;
}
// Whether line n ends the search: past end, blank, or a line of an outer block (indented less than the block; a lazy line,
// which a quote marks -1).
function mdMathStop(state, n, end) {
  return n >= end || state.bMarks[n] + state.tShift[n] >= state.eMarks[n] || state.sCount[n] < state.blkIndent;
}
// A markdown-it block rule: YAML front matter at the very top of the document (ADR-0032 제안, docs/superpowers/specs/
// 2026-11-05-more-line-formats.md). Pandoc's yaml_metadata_block start and end, made a little stricter so that ordinary
// Markdown is never taken for it: the first line is '---' (after a byte order mark, if any; trailing blanks allowed), the
// next line is not blank and opens a YAML mapping - a key and its colon, or a '#' comment - and a later line is '---' or
// '...'. Anything else is left to the other rules, which read it as before (a rule, a setext heading, a paragraph). The
// token is front_matter with map [0, the closing line + 1] and info the closing marker; its lines are shown as the server's
// lines (md-surface.js), never parsed as YAML - nothing in them is a link, an image or markup. Line 0 of a quote or a list
// item is no proof of the top: their rules call this one with start 0 and the line read from after their marker ('> ---'),
// so the rule also asks for the document itself - the root, no container open - and the line's content at the source's
// very first character.
function mdFrontMatter(state, start, end, silent) {
  if (start !== 0 || state.parentType !== 'root' || state.level !== 0 || state.bMarks[0] + state.tShift[0] !== 0) return false;
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
