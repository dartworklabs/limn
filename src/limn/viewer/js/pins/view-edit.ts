// ------------------------------------------------ The edit card, drawn
// The open edit card (EDITOR.current) drawn from what it holds now - its kind, its range, its suggestion, its save
// button - and whether it holds changes not saved yet. pins/flow-edit.ts opens, saves and closes it.
import { EDITOR } from '../app/state.ts';
import { editNote } from '../composer/view-text.ts';
import { mentionHints, renderAssignEdit } from '../composer/input-mentions.ts';
import { suggestForEdit, suggestOff, editDocKind, renderEditSuggest } from '../composer/flow-suggest.ts';
import { REQUEST_KIND, PIN_STATE } from '../app/rules-tables.ts';
import { roveSegment } from '../platform/segments.ts';
import { setCap, rangeCap, drawLadder, snipText } from '../composer/view-levels.ts';
import { html } from '../platform/markup.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { drawExcerpt } from '../composer/view-excerpt.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { pinState } from '../app/rules-pins.ts';
import { syncQuestionHint } from '../composer/view-note-hints.ts';
/** Reflect the editor's shared request lifetime on whichever card is currently visible. */
function syncEditSaveButton() {
  const button = EDITOR.current && EDITOR.current.el.querySelector('.b-esave');
  if (button) (button as HTMLButtonElement).disabled = EDITOR.saving;
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
/**
 * Report unsaved note, mention hints, range, scope, kind, assignee or suggested-edit changes before a card may close or
 * change documents.
 */
function editDirty() {
  const card = EDITOR.current;
  if (!card) return false;
  const noteField = editNote(card);
  return (
    (noteField && noteField.value !== card.orig.note) ||
    JSON.stringify(mentionHints(noteField)) !== JSON.stringify(card.orig.mentions || []) ||
    card.lo !== card.orig.lo ||
    card.hi !== card.orig.hi ||
    (card.scope || null) !== (card.orig.scope || null) ||
    card.kind_req !== card.orig.kind_req ||
    card.assignee !== card.orig.assignee ||
    suggestForEdit(card.sg, suggestOff(card, editDocKind(card))) !== undefined
  );
}
// Draws the open edit card from EDITOR.current: the kind, the range caption (a region's page and area instead), the
// ladder - shown only with two or more rungs - the range excerpt (a region's text in the plain source) and the assignee
// and question hints.
/**
 * Draw current editable fields and their save availability, including a card opened while an earlier edit is pending.
 */
function renderEdit() {
  const card = EDITOR.current;
  if (!card) return;
  const cardElement = card.el;
  syncEditSaveButton();
  (cardElement.querySelectorAll('.e-kind button') as NodeListOf<HTMLElement>).forEach((button) => {
    const on = button.dataset.kind === (card.kind_req || REQUEST_KIND.FIX);
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  });
  // the group's one Tab stop is the kind now chosen (platform/segments.ts)
  roveSegment(cardElement.querySelector('.e-kind'));
  // the card's markup above has its caption, ladder and excerpt boxes
  const caption = cardElement.querySelector('.e-cap'),
    ladder = cardElement.querySelector('.e-levels'),
    excerpt = cardElement.querySelector('.e-xp');
  if (caption instanceof HTMLElement)
    setCap(
      caption,
      card.region
        ? html`<span class="e-range loc" tabindex="0" data-copy="${card.name + ' 쪽 ' + card.page}">${translateTemplate('쪽 {page} · 영역', { page: card.page })}</span>`
        : rangeCap(card, true),
    );
  if (ladder instanceof HTMLElement) drawLadder(ladder, card, true);
  const pre = cardElement.querySelector('.e-snip') as HTMLElement;
  pre.className = 'e-snip wrap';
  pre.textContent = snipText(card.snippet, false);
  renderAssignEdit();
  if (excerpt instanceof HTMLElement) drawExcerpt(card, excerpt, true);
  // the [제안 수정] switch and its editor (composer/flow-suggest.ts); a closed pin's suggestion read-only
  renderEditSuggest(card);
  syncQuestionHint(cardElement.querySelector('.e-qhint'), editNote(card).value, card.kind_req);
  const pin = findAnyPin(card.id),
    closed = !!pin && pinState(pin) !== PIN_STATE.OPEN;
  (cardElement.querySelector('.b-repick') as HTMLElement).hidden = closed;
  if (closed) {
    (cardElement.querySelector('.e-levels') as HTMLElement).hidden = true;
    (cardElement.querySelector('.e-xp') as HTMLElement).hidden = true;
  }
}
export { syncEditSaveButton, editDirty, renderEdit };
