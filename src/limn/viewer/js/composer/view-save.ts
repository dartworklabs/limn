// The composer's save controls, including a save waiting for an outstanding pick.
import { IS_MAC, COARSE_POINTER_QUERY, COMPOSE, setComposePendingSave } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translate } from '../platform/i18n.ts';
import { BANNERS } from '../platform/notices.ts';
import { suggestPending } from './state-suggest.ts';
import { NOTICE_HOST } from '../platform/tables.ts';
import { $, findAll } from '../platform/dom.ts';
import { composerVerdict } from './state-seams.ts';

/** Keep all create and append controls in step with their shared request lifetime; editable fields remain available. An
 * append also waits while a suggested edit is written (it is saved with a new pin only, renderOverlapBanner). */
function syncComposeSaveButtons() {
  findAll(document, '#btn-save,[data-act="overlap-append"],[data-act="pop-save"]', HTMLButtonElement).forEach(
    (button) => {
      button.disabled = COMPOSE.saving;
    },
  );
  if (suggestPending())
    findAll(document, '[data-act="overlap-append"]', HTMLButtonElement).forEach((button) => {
      button.disabled = true;
    });
  composerVerdict().drawRow();
} // the verdict buttons wait for the request too, and come back when it ends - a selection picked meanwhile included
// The save-pin button's label (boot, clearing the pending state, syncSaveButton): [다시 저장] while the composer's
// banner says a save failed, else [핀 저장]; with the shortcut where there is a keyboard.
function saveButtonLabel() {
  const banner = BANNERS.get(NOTICE_HOST.COMPOSER),
    label = translate(banner && banner.save ? '다시 저장' : '핀 저장');
  return COARSE_POINTER_QUERY.matches
    ? html`${label}`
    : html`${label} <span class="kh">${IS_MAC ? '⌘ Enter' : 'Ctrl+Enter'}</span>`;
}
// docs/handbook/viewer.md §패널 정리 (드래그 직후 저장): [핀 저장] pressed right after a drag, before the pick has
// answered, finds no COMPOSE.current to save, so the press is queued and the save runs once the pick succeeds - the
// note is read from #note at that moment, with whatever was typed meanwhile. A failed pick or a cancelled selection
// clears the queue. Pressing the button again cancels the queued save (a toggle), so it can be undone without a
// separate cancel button.
function togglePendingSave() {
  if (COMPOSE.pendingSave) {
    clearPendingSave();
    return;
  }
  setComposePendingSave(true);
  const button = $('#btn-save');
  button.dataset.pending = '1';
  setHtml(button, html`${translate('위치 찾는 중… 저장 대기')} <span class="spin" aria-hidden="true"></span>`);
}
function clearPendingSave() {
  if (!COMPOSE.pendingSave) return;
  setComposePendingSave(false);
  const button = $('#btn-save');
  delete button.dataset.pending;
  setHtml(button, saveButtonLabel());
}

export { clearPendingSave, togglePendingSave, saveButtonLabel, syncComposeSaveButtons };
