// ------------------------------------------------ What the note's hints read
// The pin a selection would add to (its overlap, unless dismissed) and whether a note reads like a question: the
// composer's append row and question hint, and the edit card's and the popover's, draw from these.
import { RANGE_REL, REQUEST_KIND } from '../app/rules-tables.ts';
import { COMPOSE } from '../app/state.ts';
// One representative: same range > inside (the narrowest enclosing pin) > contains (the widest inner pin) > overlap
// (the smallest id).
function pickOverlap(overlaps) {
  if (!overlaps || !overlaps.length) return null;
  const equal = overlaps.filter((overlap) => overlap.rel === RANGE_REL.EQUAL);
  if (equal.length) return equal.reduce((best, candidate) => (candidate.id < best.id ? candidate : best));
  const insides = overlaps.filter((overlap) => overlap.rel === RANGE_REL.INSIDE);
  if (insides.length)
    return insides.reduce((best, candidate) => (candidate.hi - candidate.lo < best.hi - best.lo ? candidate : best));
  const contains = overlaps.filter((overlap) => overlap.rel === RANGE_REL.CONTAINS);
  if (contains.length)
    return contains.reduce((best, candidate) => (candidate.hi - candidate.lo > best.hi - best.lo ? candidate : best));
  const partials = overlaps.filter((overlap) => overlap.rel === RANGE_REL.PARTIAL);
  if (partials.length) return partials.reduce((best, candidate) => (candidate.id < best.id ? candidate : best));
  return null;
}
// The open pin the composer's note may join instead of becoming a pin: the overlap its notice offers [덧붙이기] for -
// or null without one, and once the author chose [따로 저장] for it.
function appendTarget(): { id: number; lo: number; hi: number; rel: string } | null {
  const selection = COMPOSE.current,
    overlap = selection ? pickOverlap(selection.overlaps) : null;
  return overlap && COMPOSE.dismissedOverlap !== overlap.id + ':' + overlap.rel ? overlap : null;
}
// A note that reads like a question (docs/handbook/viewer.md §스레드와 검토 - suggesting the kind). True if it ends in
// ?/? or a Korean interrogative ending (는가/나요/까요/인가/건가/니/냐/까). A trailing period/ellipsis/closing
// bracket/quote and a trailing @-tag (e.g. '맞나요? @Bob Park') are ignored. Only judges - never changes the kind
// itself.
function looksQuestion(text) {
  let trimmed = String(text || '').trim();
  for (let i = 0; i < 3; i++)
    trimmed = trimmed
      .replace(/[\s.…~!。)\]"'”’]+$/, '')
      .replace(/(?:\s*@[^\s@?？]+(?:\s+[A-Za-z][A-Za-z.'-]*)?)+$/, '');
  return /[?？]$/.test(trimmed) || /(는가|나요|까요|인가|건가|니|냐|까)$/.test(trimmed);
}
// If it's a fix request but the note reads like a question, a one-line suggestion appears next to the kind control. It
// never changes the kind itself - only a click does. It goes once the kind is a question or the text does not read like
// one.
function syncQuestionHint(box, text, kind) {
  if (box) box.hidden = kind === REQUEST_KIND.QUESTION || !looksQuestion(text);
}
export { syncQuestionHint, appendTarget };
