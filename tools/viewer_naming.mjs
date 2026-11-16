// The logic of the viewer's two naming-and-prose rules, apart from ESLint: limn/plain-names (a declared name is whole
// words) and limn/no-history-comment (a comment says what the code does and why, not how it came to be). The rules
// themselves are in eslint.config.mjs; docs/handbook/viewer.md §이름과 주석 states the policy.
import { readFileSync } from 'node:fs';

/**
 * The word lists in tools/viewer-names.json.
 * @typedef {{
 *   english: string[],
 *   allow: Record<string, string>,
 *   loopIndex: string[],
 *   deny: Record<string, string>,
 * }} NameLists
 */

/** The shortest word that needs no entry in the lists. */
export const MIN_WORD_LENGTH = 3;

/** @returns {NameLists} the committed word lists. */
export function loadNameLists() {
  return JSON.parse(readFileSync(new URL('./viewer-names.json', import.meta.url), 'utf8'));
}

/**
 * The lowercase words of an identifier: `pvPress` is pv, press; `PV_BUSY` is pv, busy; `parseHTMLDoc` is parse, html,
 * doc; `h264` is h, 264. An underscore or dollar sign only separates words, so `_` and `$` have none. A word of digits
 * only is kept so callers can skip it, never judged.
 * @param {string} name
 * @returns {string[]}
 */
export function wordsOf(name) {
  const found = name.match(/[Ii]18[Nn]|\p{Lu}+(?!\p{Ll})|\p{Lu}?\p{Ll}+|\p{Lo}+|\d+/gu);
  return found ? found.map((word) => word.toLowerCase()) : [];
}

/**
 * Why a word of a declared name is refused, or null when it is a whole word. A word fails when the deny list names it
 * (an abbreviation of a word), or when it is shorter than three letters and neither list allows it. A digit-only word
 * never fails.
 * @param {string} word one lowercase word of wordsOf
 * @param {NameLists} lists
 * @returns {string | null}
 */
export function wordProblem(word, lists) {
  if (/^\d+$/.test(word)) return null;
  const whole = Object.hasOwn(lists.deny, word) ? lists.deny[word] : null;
  if (whole !== null) return `"${word}" abbreviates "${whole}": write the whole word`;
  if (word.length >= MIN_WORD_LENGTH || lists.english.includes(word) || Object.hasOwn(lists.allow, word)) return null;
  return `"${word}" is shorter than ${MIN_WORD_LENGTH} letters and not in the short-word allow-list: write the whole word`;
}

/**
 * The problems with a declared name, one per refused word, in order and without repeats; empty when every word is whole.
 * `i`, `j` and `k` pass only as the whole name of a loop index (loopIndex true).
 * @param {string} name
 * @param {NameLists} lists
 * @param {boolean} loopIndex whether the name is declared by a for loop's head
 * @returns {string[]}
 */
export function nameProblems(name, lists, loopIndex = false) {
  if (loopIndex && lists.loopIndex.includes(name)) return [];
  const problems = [];
  for (const word of wordsOf(name)) {
    const problem = wordProblem(word, lists);
    if (problem && !problems.includes(problem)) problems.push(problem);
  }
  return problems;
}

/**
 * Where a comment quotes text: the [start, end) offsets of every '...', "..." and `...` span. A quote opens when the
 * character before it is not a letter or digit and closes when the character after it is not, so the apostrophe in
 * "pin's" opens nothing, and a quote still open at the end of the text runs to the end; `'s` after a closing quote is a possessive, not an opening one. Text in quotes is an example of
 * what the code handles (a pin number '#12', a timestamp), not history.
 * @param {string} text
 * @returns {Array<[number, number]>}
 */
export function quotedSpans(text) {
  const spans = [];
  let open = -1;
  let mark = '';
  const wordChar = /[\p{L}\p{N}]/u;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (ch !== "'" && ch !== '"' && ch !== '`') continue;
    if (open < 0) {
      const possessive = ch === "'" && /^s(?![\p{L}\p{N}])/u.test(text.slice(i + 1, i + 3)); // `page`'s
      if (!wordChar.test(text[i - 1] ?? '') && text[i - 1] !== ch && !possessive) {
        open = i;
        mark = ch;
      }
    } else if (ch === mark && !wordChar.test(text[i + 1] ?? '')) {
      spans.push([open, i + 1]);
      open = -1;
    }
  }
  if (open >= 0) spans.push([open, text.length]); // a quote the comment leaves open runs to its end
  return spans;
}

// The kinds of history a comment carries. Each is a pattern whose matches are checked against the exemptions below.
const RELEASE = /(?<![\w.])\d+\.\d+\.\d+(?!\d|\.\d)/g;
const ISSUE = /(?<![\w&/#])#\d{2,}(?![\w-])|\b(?:issue|issues|PR|pull request|review)\s+#\d+(?![\w-])/gi;
const DATE = /(?<![\w-])(?:19|20)\d\d-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])(?![\w-])/g;

// A dotted number that is a specification's own: `WCAG 3.2.2`, `RFC 9110`, `§1.2.3` and the like.
const SPEC_BEFORE = /(?:\b(?:WCAG|RFC|ISO|ECMA|ECMAScript|Unicode|ARIA|UAX|HTTP)\s*|§\s*)$/;

/**
 * Whether the match at [start, end) of text sits in a place that is not history: in quotes, in a URL, after a
 * `@version` tag, or (a release-like number) after the name of a specification.
 * @param {string} text
 * @param {number} start
 * @param {number} end
 * @param {Array<[number, number]>} quoted
 * @param {boolean} release whether the match is a dotted number
 */
function exempt(text, start, end, quoted, release) {
  if (quoted.some(([from, to]) => start >= from && end <= to)) return true;
  const lineStart = text.lastIndexOf('\n', start - 1) + 1;
  const head = text.slice(lineStart, start);
  if (/https?:\/\/\S*$/.test(head) || /@version\b[^\n]*$/.test(head)) return true;
  return release && SPEC_BEFORE.test(head);
}

/**
 * The history a comment carries, as the first match of each kind that is not exempt: a release number (`0.4.34`), an
 * issue or pull request number (`#418`, `issue #12`), or an ISO date (`2026-09-24`). A reference to an ADR number, a
 * Handbook file or a `§` section points at a rule that holds now, so it is not history. An IPv4 address, a number
 * after `WCAG`/`RFC`/`§`, anything in a URL or after `@version`, and anything inside quotes (an example of the text
 * the code handles) are not either.
 * @param {string} text the comment's text, without its delimiters; for a run of `//` lines, the lines joined by a
 *   newline, so a quote that spans lines is seen whole
 * @param {number} from the first offset of text to look at (the line being judged); 0 by default
 * @param {number} to the offset the look stops before; the end of text by default
 * @returns {Array<{ kind: 'release' | 'issue' | 'date', text: string }>}
 */
export function historyIn(text, from = 0, to = text.length) {
  const quoted = quotedSpans(text);
  const found = [];
  for (const [kind, pattern] of /** @type {const} */ ([
    ['release', RELEASE],
    ['issue', ISSUE],
    ['date', DATE],
  ])) {
    for (const match of text.matchAll(pattern)) {
      const start = match.index;
      if (start < from || start >= to) continue;
      if (exempt(text, start, start + match[0].length, quoted, kind === 'release')) continue;
      found.push({ kind, text: match[0] });
      break;
    }
  }
  return found;
}
