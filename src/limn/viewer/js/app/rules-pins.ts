// ------------------------------------------------ A pin record read as values
// Pure readers of a pin as the API sends it: its state, its verdict key, its line range, how a range overlaps it.
import { PIN_STATE, RANGE_REL } from './rules-tables.ts';
// A pin's state: its `state`, else what its done and review flags say.
function pinState(pin: Pin) {
  return (pin && pin.state) || (pin && pin.done ? (pin.review ? PIN_STATE.REVIEW : PIN_STATE.DONE) : PIN_STATE.OPEN);
}
// A pin's verdict key, or null: a stored value counts only when it is key-shaped, as the server reads it
// (pins/verdict.py verdict_of: 1-16 letters, digits, '-' or '_'). Pure.
function verdictOf(pin: Pin | null | undefined): string | null {
  const value = pin && pin.verdict;
  return typeof value === 'string' && /^[\p{L}\p{N}_-]{1,16}$/u.test(value) ? value : null;
}
// Line-range notation: 'L159' for a single line, 'L155-L173' for multiple (the copy/pins.md format 'L159-L159' is left
// as-is).
function lineRange(first: number | undefined, last: number | undefined) {
  return 'L' + first + (last !== first ? '-L' + last : '');
}
// docs/handbook/api.md §겹친 핀과 덧붙이기: if the pre-save selection (COMPOSE.current) overlaps an open pin, one
// representative is chosen and a "append" banner is drawn. Never auto-merged - the user picks between [메모에
// 덧붙이기]/[별도 핀으로 저장]. Overlap is recomputed against this tab's PINS every time the range changes (drag/level
// switch/up-down). Counted only once at pick time, a level switch to the exact range of an existing pin would show no
// banner and save a duplicate pin. The rule matches the server's selection_rel (a test compares them): equal (same
// range) - inside (selection is inside the pin) - contains (selection wraps the pin) - partial.
function rangeRelation(first: number, last: number, pinFirst: number, pinLast: number) {
  if (last < pinFirst || pinLast < first) return null;
  if (first === pinFirst && last === pinLast) return RANGE_REL.EQUAL;
  if (pinFirst <= first && last <= pinLast) return RANGE_REL.INSIDE;
  if (first <= pinFirst && pinLast <= last) return RANGE_REL.CONTAINS;
  return RANGE_REL.PARTIAL;
}
// Only lines overlap: a selection on a view-only PDF has none, and a pin record without its lines (a broken stored
// record that keeps its file) has none to compare.
function overlapsFor(selection: ComposerSelection, pins: Pin[] | null | undefined) {
  const out: PickOverlap[] = [];
  if (!selection || !selection.file || selection.lo == null || selection.hi == null) return out;
  const { file, lo: first, hi: last } = selection;
  (pins || []).forEach((pin) => {
    if (pinState(pin) !== PIN_STATE.OPEN || pin.file !== file || pin.lo == null || pin.hi == null) return;
    const rel = rangeRelation(first, last, pin.lo, pin.hi);
    if (rel) out.push({ id: pin.id, lo: pin.lo, hi: pin.hi, rel: rel });
  });
  return out;
}

export { pinState, verdictOf, lineRange, overlapsFor };
