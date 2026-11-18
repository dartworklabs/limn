import { findMaybe } from '../platform/dom.ts';
import { imeHeldIn } from '../app/state.ts';

function isReasonField(target: unknown): target is HTMLTextAreaElement {
  return target instanceof HTMLTextAreaElement && target.classList.contains('pv-reason');
}
// The open popover's field, or null.
function findReasonField() {
  return findMaybe(document, '#doc .pv-pop .pv-reason', HTMLTextAreaElement);
}

// ---------------- Input
// The reason field an input method is composing in: its value is not put back. The composition ends with its field: a
// field drawn anew in its place (the pages built again) holds the session's text - left empty, the next input would
// write what it holds over the reason.
let COMPOSING_FIELD: HTMLTextAreaElement | null = null;

// Whether an input method is composing a syllable in a reason field in the document, or the key that ended it there
// still holds it (app/state.ts imeHeldIn). Nothing takes that field away meanwhile: the lines do not move beside or
// under the pages (shouldStandBeside) and the pages are not built again (refreshDoc, afterComposition) until it ends
// and that key lets go. Moved or rebuilt, the field would be a new one: the old one's composition would end with it,
// the input method's commit would land on top of the text carried over (its last syllable doubled), and the Enter
// ibus-hangul hands on after the commit, with its repeats, would reach the new field as the viewer's - writing the
// reason and closing the popover.
function isComposingNow() {
  if (COMPOSING_FIELD && COMPOSING_FIELD.isConnected) return true;
  const field = imeHeldIn();
  return isReasonField(field) && field.isConnected;
}

// Sets COMPOSING_FIELD, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setComposingField<Value extends typeof COMPOSING_FIELD>(value: Value): Value {
  COMPOSING_FIELD = value;
  return value;
}

export { COMPOSING_FIELD, setComposingField, isComposingNow, isReasonField, findReasonField };
