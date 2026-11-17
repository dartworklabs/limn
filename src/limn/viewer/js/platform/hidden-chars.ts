// ------------------------------------------------ Characters that hide or reorder text
// (ADR-0029 D5, docs/superpowers/specs/2026-11-05-text-documents.md §결정 5) A bidirectional control can make a line
// read in another order than its source, and a zero-width, filler or control character can make two texts look the same
// (Trojan Source, CVE-2021-42574). Every place that shows a source's or a suggestion's text as it is - the text
// surface's lines, the excerpt under the ladder, a suggestion's diff, a rung's label - marks them, for every document
// kind, with this one repertoire, in one of two forms:
// - hiddenBox, markHiddenHtml: the character stays in the text (a copy keeps it) inside an isolating span (.cc) that
//   shows its name.
// - markHiddenPlain: its name in angle brackets ('⟨U+202E⟩'), where only plain text can go (a label, a tooltip, a
//   fallback view).
// The repertoire (HIDDEN_RANGES), by code point: Unicode's Default_Ignorable_Code_Point (the soft hyphen, the combining
// grapheme joiner, the Hangul fillers, the Khmer inherent vowels, the Mongolian variation selectors and vowel
// separator, the zero-width characters and bidirectional marks, the bidirectional embeddings, overrides and isolates,
// the word joiner and invisible operators, the deprecated format characters, the variation selectors, the byte-order
// mark, the shorthand and musical format controls, the tags), every C0 and C1 control but the tab and the line feed,
// the line and paragraph separators and the interlinear annotation characters. limn.pins.suggestion.HIDDEN_RANGES holds
// the same table for pins.md; a test ties the two and checks this one against the engine's own Unicode properties. A
// character a legitimate sequence needs is left as it is (isKeptInSequence). Nothing else is: a tag sequence (a
// subdivision flag) shows its tags by name.
import { html } from './markup.ts';
import type { Html } from './markup.ts';

const HIDDEN_RANGES: ReadonlyArray<readonly [number, number]> = Object.freeze(
  [
    [0x00, 0x08],
    [0x0b, 0x1f],
    [0x7f, 0x9f],
    [0xad, 0xad],
    [0x34f, 0x34f],
    [0x61c, 0x61c],
    [0x115f, 0x1160],
    [0x17b4, 0x17b5],
    [0x180b, 0x180f],
    [0x200b, 0x200f],
    [0x2028, 0x202e],
    [0x2060, 0x206f],
    [0x3164, 0x3164],
    [0xfe00, 0xfe0f],
    [0xfeff, 0xfeff],
    [0xffa0, 0xffa0],
    [0xfff0, 0xfffb],
    [0x1bca0, 0x1bca3],
    [0x1d173, 0x1d17a],
    [0xe0000, 0xe0fff],
  ].map((range) => Object.freeze(range as [number, number])),
);
// The repertoire as one regular expression over code points (a supplementary character is one match, never two halves).
const HIDDEN_PATTERN = new RegExp(
  '[' +
    HIDDEN_RANGES.map(
      ([first, last]) => '\\u{' + first.toString(16) + '}' + (last > first ? '-\\u{' + last.toString(16) + '}' : ''),
    ).join('') +
    ']',
  'gu',
);
const ANY_HIDDEN = new RegExp(HIDDEN_PATTERN.source, 'u'); // the same, for a test that keeps no state
// The scripts whose ordinary text puts a zero-width joiner or non-joiner between two of its letters (Persian, Indic
// conjuncts and half forms, Syriac, Mongolian), an emoji's pictograph, a Han ideograph and a Mongolian letter.
const JOINING_SCRIPT =
  /[\p{sc=Arabic}\p{sc=Syriac}\p{sc=Mongolian}\p{sc=Devanagari}\p{sc=Bengali}\p{sc=Gurmukhi}\p{sc=Gujarati}\p{sc=Oriya}\p{sc=Tamil}\p{sc=Telugu}\p{sc=Kannada}\p{sc=Malayalam}\p{sc=Sinhala}]/u;
const PICTOGRAPH = /\p{Extended_Pictographic}/u,
  HAN_IDEOGRAPH = /\p{sc=Han}/u,
  MONGOLIAN_LETTER = /\p{sc=Mongolian}/u;
// The name a marked character shows: a C0 control's picture (the U+2400 block), DEL's, else its code point (U+202E,
// U+E0041). Pure.
function hiddenName(codePoint: number) {
  if (codePoint < 0x20) return String.fromCodePoint(0x2400 + codePoint);
  if (codePoint === 0x7f) return '␡';
  return 'U+' + codePoint.toString(16).toUpperCase().padStart(4, '0');
}
// The code point just before `index` of the text (a surrogate pair whole), or -1 at its start; and the one at `index`,
// or -1 past it.
function codePointBefore(text: string, index: number) {
  if (index <= 0) return -1;
  const low = text.charCodeAt(index - 1);
  if (index >= 2 && low >= 0xdc00 && low <= 0xdfff) {
    const high = text.charCodeAt(index - 2);
    if (high >= 0xd800 && high <= 0xdbff) return text.codePointAt(index - 2) ?? -1;
  }
  return low;
}
function codePointAtIndex(text: string, index: number) {
  return index < text.length ? (text.codePointAt(index) ?? -1) : -1;
}
function codePointMatches(codePoint: number, pattern: RegExp) {
  return codePoint >= 0 && pattern.test(String.fromCodePoint(codePoint));
}
// Whether a marked character (codePoint) at `index` of the text is one a legitimate sequence needs, and so is left as
// it is - the exceptions, each tested:
// - a byte-order mark at the very start of a file (first: the text is its line 1): the encoding's mark, not text;
// - a zero-width non-joiner or joiner between two letters or marks of a script that joins with them (JOINING_SCRIPT);
// - a zero-width joiner inside an emoji sequence: after a pictograph, a skin-tone modifier or VS16, before a
//   pictograph;
// - VS15 or VS16 after a pictograph, and VS16 in a keycap ([#*0-9] U+FE0F U+20E3);
// - a variation selector after a Han ideograph (an ideographic variation sequence, as in a Japanese name);
// - a Mongolian free variation selector after a Mongolian letter;
// - the Hangul choseong filler before a real jungseong, the jungseong filler after a real choseong (old Hangul written
//   in conjoining jamo). The two fillers together, U+3164 and U+FFA0 are always marked: they draw nothing at all.
// Pure.
function isKeptInSequence(text: string, index: number, codePoint: number, first: boolean) {
  const before = codePointBefore(text, index),
    after = codePointAtIndex(text, index + (codePoint > 0xffff ? 2 : 1));
  if (codePoint === 0xfeff) return first && index === 0;
  if (codePoint === 0x200c || codePoint === 0x200d) {
    if (codePointMatches(before, JOINING_SCRIPT) && codePointMatches(after, JOINING_SCRIPT)) return true;
    return (
      codePoint === 0x200d &&
      (codePointMatches(before, PICTOGRAPH) || (before >= 0x1f3fb && before <= 0x1f3ff) || before === 0xfe0f) &&
      codePointMatches(after, PICTOGRAPH)
    );
  }
  if (codePoint === 0xfe0e || codePoint === 0xfe0f) {
    if (codePointMatches(before, PICTOGRAPH)) return true;
    if (
      codePoint === 0xfe0f &&
      after === 0x20e3 &&
      (before === 0x23 || before === 0x2a || (before >= 0x30 && before <= 0x39))
    )
      return true;
  }
  if ((codePoint >= 0xfe00 && codePoint <= 0xfe0f) || (codePoint >= 0xe0100 && codePoint <= 0xe01ef))
    return codePointMatches(before, HAN_IDEOGRAPH);
  if ((codePoint >= 0x180b && codePoint <= 0x180d) || codePoint === 0x180f)
    return codePointMatches(before, MONGOLIAN_LETTER);
  if (codePoint === 0x115f) return (after > 0x1160 && after <= 0x11a7) || (after >= 0xd7b0 && after <= 0xd7c6);
  if (codePoint === 0x1160) return (before >= 0x1100 && before < 0x115f) || (before >= 0xa960 && before <= 0xa97c);
  return false;
}
// Every character of the input in the repertoire, in order: {at, ch} for one that is marked, null for one that is kept
// (isKeptInSequence) - so a caller can count the work either costs and pause within a long line. first: the input is
// line 1 of a file. A generator.
function* scanHidden(input: string, first?: boolean): Generator<{ at: number; ch: string } | null> {
  const text = String(input);
  if (!ANY_HIDDEN.test(text)) return; // most lines hold none: one native test
  const pattern = new RegExp(HIDDEN_PATTERN.source, 'gu');
  let match;
  while ((match = pattern.exec(text))) {
    const codePoint = match[0].codePointAt(0) || 0;
    yield isKeptInSequence(text, match.index, codePoint, !!first) ? null : { at: match.index, ch: match[0] };
  }
}
// The marked characters of the text, in order: [{at, ch}]. Pure.
function findHidden(text: string, first?: boolean) {
  const out: { at: number; ch: string }[] = [];
  for (const marked of scanHidden(text, first)) if (marked) out.push(marked);
  return out;
}
// The input with each marked character as its name in angle brackets: plain text that never reads in another order than
// the input. Pure.
function markHiddenPlain(input: string, first?: boolean) {
  const text = String(input);
  let out = '',
    at = 0;
  for (const marked of findHidden(text, first)) {
    out += text.slice(at, marked.at) + '⟨' + hiddenName(marked.ch.codePointAt(0) || 0) + '⟩';
    at = marked.at + marked.ch.length;
  }
  return out + text.slice(at);
}
// The text as plain text cut to at most max characters of what it shows, a marked character's name counted whole and
// never cut, with '…' when it was cut. Reads no more of the text than max + 2 characters (one past the cut keeps a
// joiner's context). Pure.
function clipMarkedText(text: string, max: number) {
  let head = '',
    read = 0;
  for (const character of String(text)) {
    if (++read > max + 2) break;
    head += character;
  }
  const pieces: string[] = [];
  let at = 0;
  for (const marked of findHidden(head)) {
    pieces.push(...head.slice(at, marked.at), '\u27e8' + hiddenName(marked.ch.codePointAt(0) || 0) + '\u27e9');
    at = marked.at + marked.ch.length;
  }
  pieces.push(...head.slice(at));
  let out = '',
    shown = 0;
  for (const piece of pieces) {
    const width = [...piece].length;
    if (shown + width > max) return out + '…';
    out += piece;
    shown += width;
  }
  return out;
}
// How many marked characters of each name `text` holds more than `base`: [[name, count]] by first appearance in `text`,
// [] when it adds none - what a suggestion's draft puts in that its lines do not have. Each line is read on its own, as
// a diff shows it. Pure.
function countAddedHidden(text: string, base: string): [string, number][] {
  const count = (text: string) => {
    const counts = new Map<string, number>();
    for (const line of String(text).split('\n'))
      for (const marked of findHidden(line)) {
        const name = hiddenName(marked.ch.codePointAt(0) || 0);
        counts.set(name, (counts.get(name) || 0) + 1);
      }
    return counts;
  };
  const textCounts = count(text),
    baseCounts = count(base),
    out: [string, number][] = [];
  for (const [name, count] of textCounts) {
    const extra = count - (baseCounts.get(name) || 0);
    if (extra > 0) out.push([name, extra]);
  }
  return out;
}
// A marked character as its box: an isolating span showing its name, the character itself in a .sr-only child - it
// takes no room, and a copy of the text keeps it.
function hiddenBox(character: string): HTMLElement {
  const box = document.createElement('span');
  box.className = 'cc';
  box.dataset.cc = hiddenName(character.codePointAt(0) || 0);
  const characterSpan = document.createElement('span');
  characterSpan.className = 'sr-only';
  characterSpan.textContent = character;
  box.append(characterSpan);
  return box;
}
// The input as Html: its text, each marked character as its box (hiddenBox's markup) with the character not in the
// markup but as its code point (data-cp), which setHtml puts in as text - the HTML parser drops a NUL and turns a CR
// into a line feed, so a box built from markup would show ␀ and copy nothing. Pure.
function markHiddenHtml(input: string): Html {
  const text = String(input),
    out: (string | Html)[] = [];
  let at = 0;
  for (const marked of findHidden(text)) {
    const codePoint = marked.ch.codePointAt(0) || 0;
    out.push(
      text.slice(at, marked.at),
      html`<span class="cc" data-cc="${hiddenName(codePoint)}"><span class="sr-only" data-cp="${codePoint.toString(16)}"></span></span>`,
    );
    at = marked.at + marked.ch.length;
  }
  out.push(text.slice(at));
  return html`${out}`;
}
export {
  ANY_HIDDEN,
  countAddedHidden,
  hiddenBox,
  clipMarkedText,
  findHidden,
  markHiddenHtml,
  hiddenName,
  markHiddenPlain,
  scanHidden,
};
