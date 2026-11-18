// The overlap notice for the current selection.
import { LAYOUT, PINS, COMPOSE, setSelectionOverlaps } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate, josa } from '../platform/i18n.ts';
import { suggestPending } from './state-suggest.ts';
import { renderAssignNew } from './input-mentions.ts';
import { $ } from '../platform/dom.ts';
import { LAYOUT_MODE, RANGE_REL } from '../app/rules-tables.ts';
import { overlapsFor } from '../app/rules-pins.ts';
import { appendTarget } from './view-note-hints.ts';

// Overlap-banner wording: what relationship the selection has to that pin - '#4와 같은 범위' - '#4 범위 안' - '#4를
// 감쌈' - '#4와 일부 겹침'. The whole banner sentence in the UI language: '열린 핀 #4와 같은 범위입니다' / 'Same range
// as open pin #4'.
function overlapText(rel: string, id: number) {
  const template =
    {
      equal: '열린 핀 #{id}{p} 같은 범위입니다',
      inside: '열린 핀 #{id} 범위 안입니다',
      contains: '열린 핀 #{id}{p} 감쌉니다',
      partial: '열린 핀 #{id}{p} 일부 겹칩니다',
    }[rel] || '열린 핀 #{id}{p} 겹칩니다';
  return translateTemplate(template, {
    id,
    p: rel === RANGE_REL.CONTAINS ? josa(id, '을', '를') : josa(id, '과', '와'),
  });
}
// [별도 핀으로 저장] turns off "that relationship with that pin" (id:rel). Re-announced if changing the range changes
// the relationship, and reset on a fresh drag (pick), so one press never silences it for every later selection.

function recomputeOverlap() {
  if (COMPOSE.current) setSelectionOverlaps(COMPOSE.current, overlapsFor(COMPOSE.current, PINS));
}
// Draws the overlap notice for the current selection, or hides it. On the phone sheet it is one line (three lines would
// take too much room above the note): the short relation ('#4와 같은 범위', the full sentence and the lines in its
// tooltip) and the two actions with short names; elsewhere the sentence with the lines and the two full-named buttons.
/** Render the current overlap choice; its append control shares the composer's in-flight submission lock. The assignee
 *  row and the preview line follow it (renderAssignNew): while an append is on offer they say what it does. */
function renderOverlapBanner() {
  const box = $('#c-overlap'),
    overlap = appendTarget();
  if (!overlap) {
    box.hidden = true;
    renderAssignNew();
    return;
  }
  box.hidden = false;
  box.dataset.rel = overlap.rel;
  const one = LAYOUT === LAYOUT_MODE.NARROW,
    full = overlapText(overlap.rel, overlap.id) + ' (L' + overlap.lo + '-L' + overlap.hi + ')';
  box.classList.toggle('one', one);
  const text = one
    ? html`<span class="ov-t" data-tip="${full}">${overlapShort(overlap.rel, overlap.id)}</span>`
    : html`<span>${overlapText(overlap.rel, overlap.id)} <span class="dim">(L${overlap.lo}-L${overlap.hi})</span></span>`;
  // A suggested edit belongs to this selection's lines and is saved with a new pin only: while one is written,
  // [덧붙이기] waits.
  const isSuggesting = suggestPending(),
    appendTip = isSuggesting
      ? translate('제안 수정은 새 핀으로만 저장합니다 — 덧붙이려면 제안 수정을 끄세요')
      : translateTemplate('이 선택의 메모를 #{id} 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다', {
          id: overlap.id,
        });
  setHtml(
    box,
    html`${text}\
<button class="btn-sm btn-secondary hit" data-act="overlap-append" data-oid="${overlap.id}" data-tip="${appendTip}"${COMPOSE.saving || isSuggesting ? html` disabled` : ''}>${one ? translate('덧붙이기') : translateTemplate('#{id} 메모에 덧붙이기', { id: overlap.id })}</button>\
<button class="btn-sm btn-secondary hit" data-act="overlap-separate" data-key="${overlap.id + ':' + overlap.rel}" data-tip="겹쳐도 별도 핀으로 저장합니다">${one ? translate('따로 저장') : '별도 핀으로 저장'}</button>`,
  );
  renderAssignNew();
}
// The overlap in a few words for the one-line notice: '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침'
// (the card badges' wording).
function overlapShort(rel: string, id: number) {
  const template =
    { equal: '#{id}{p} 같은 범위', inside: '#{id} 범위 안', contains: '#{id}{p} 감쌈', partial: '#{id}{p} 일부 겹침' }[
      rel
    ] || '#{id}{p} 일부 겹침';
  return translateTemplate(template, {
    id,
    p: rel === RANGE_REL.CONTAINS ? josa(id, '을', '를') : josa(id, '과', '와'),
  });
}

export { recomputeOverlap, renderOverlapBanner };
