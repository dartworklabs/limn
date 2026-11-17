// ------------------------------------------------ The text fields a pin is written in
// The composer's note, an edit card's note and a reply share these: the field's height follows its text, and a card's
// quote line stays open across redraws.
import { findElement } from '../platform/dom.ts';
// The cards whose quote line is open ('<doc>:<id>', toggleQuote), kept across redraws.
const QUOTE_OPEN = new Set<string>();
// The note field of an edit card (openEdit puts exactly one in every card).
function editNote(card: EditCard): HTMLTextAreaElement {
  return findElement(card.el, '.e-note', HTMLTextAreaElement);
}
// Grows a note or reply field with its text, from three lines to twelve.
function autoGrow(field: HTMLElement) {
  field.style.height = 'auto';
  const lineHeight = 20;
  field.style.height = Math.min(12 * lineHeight, Math.max(3 * lineHeight, field.scrollHeight + 2)) + 'px';
}

export { QUOTE_OPEN, editNote, autoGrow };
