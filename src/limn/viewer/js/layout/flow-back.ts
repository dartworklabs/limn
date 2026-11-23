import { BAND, DOC, MID_OVERLAY, COARSE_POINTER_QUERY, OUTLINE_MID_OPEN, SIDE_OPEN } from '../app/state.ts';
import { $$, findMaybe } from '../platform/dom.ts';
import { LAYOUT_BAND } from '../app/rules-tables.ts';
import { isRecord } from '../platform/tables.ts';

// On a phone or tablet the system back gesture closes the top layer first (docs/handbook/viewer.md §모바일 레이아웃)
// instead of leaving Limn with a draft on screen. While a sheet, the overlay panel or the outline overlay is open, one
// CloseWatcher stands for it (Chrome on Android routes back there; modal dialogs have their own); without CloseWatcher,
// one history entry does (popstate). Closing the layer any other way removes it again, so back never has a dead press,
// and document switches never add entries (they replace the hash). Mouse devices have no system back, so nothing is
// registered there.
let BACK: { kind: string; w?: CloseWatcher } | null = null,
  BACK_SKIP = false;
// Which layer covers the document for a band (overlay = MID_OVERLAY): an open bottom-sheet dialog on top (dialogOpen -
// the caller passes it only without CloseWatcher, where a modal dialog takes the back gesture itself), then the outline
// overlay (the mid bands and the tablet sheet), then a sheet (phone, tablet) or the overlay panel (mid-overlay, a short
// band up to 900px). The desktop has none. 'dialog'|'side'|'outline'|null.
function backLayer(
  band: string | null,
  overlay: boolean,
  sideOpen: boolean,
  outlineOpen: boolean,
  dialogOpen: boolean,
) {
  if (band === LAYOUT_BAND.WIDE) return null;
  if (dialogOpen) return 'dialog';
  if (band === LAYOUT_BAND.PHONE) return sideOpen ? 'side' : null;
  if (outlineOpen) return 'outline';
  return sideOpen && (band === LAYOUT_BAND.TABLET_SHEET || overlay) ? 'side' : null;
}
// The open bottom-sheet dialog the back gesture closes first, or null: the navigation sheet, [더보기], help, the Trash,
// the status line's list.
function sheetDialog() {
  return findMaybe(
    document,
    '#nav-sheet[open],#more[open],#help[open],#trash[open],#status-list[open],#access[open]',
    HTMLDialogElement,
  );
}
// Registers or removes the back layer to match the screen (called by applySide, applyOutlineState and a sheet dialog
// opening or closing; idempotent).
function syncBackLayer(closeTopLayer: () => void) {
  const want =
    COARSE_POINTER_QUERY.matches &&
    !!backLayer(BAND, MID_OVERLAY, SIDE_OPEN, OUTLINE_MID_OPEN, !window.CloseWatcher && !!sheetDialog());
  if (want && !BACK) armBack(closeTopLayer);
  else if (!want && BACK) disarmBack();
}
// Stands one CloseWatcher for the open layer, or pushes one history entry (same URL) where CloseWatcher is missing.
function armBack(closeTopLayer: () => void) {
  if (window.CloseWatcher) {
    try {
      const watcher = new window.CloseWatcher();
      BACK = { kind: 'watcher', w: watcher };
      watcher.onclose = () => {
        if (BACK && BACK.w === watcher) {
          BACK = null;
          closeTopLayer();
        }
      };
      return;
    } catch (error) {}
  }
  window.history.pushState({ limnLayer: 1 }, '', window.location.href);
  BACK = { kind: 'history' };
}
// Removes the layer without closing anything: destroys the watcher, or pops our entry (that popstate is skipped).
function disarmBack() {
  const layer = BACK;
  BACK = null;
  if (!layer) return;
  if (layer.kind === 'watcher') {
    if (layer.w) layer.w.destroy();
    return;
  }
  const state: unknown = window.history.state;
  if (isRecord(state) && state.limnLayer) {
    BACK_SKIP = true;
    window.history.back();
  }
}
// Listen after document navigation, which reads the back entry before it is consumed.
function watchBackLayer(closeTopLayer: () => void, setHash: (doc: string) => void) {
  for (const dialog of $$('#nav-sheet,#more,#help,#trash,#status-list,#access'))
    new MutationObserver(() => syncBackLayer(closeTopLayer)).observe(dialog, {
      attributes: true,
      attributeFilter: ['open'],
    });
  window.addEventListener('popstate', () => {
    const ours = BACK_SKIP || (BACK && BACK.kind === 'history');
    if (!ours) return;
    if (DOC) setHash(DOC); // the entry below may carry an older #doc= - the document on screen stays
    if (BACK_SKIP) {
      BACK_SKIP = false;
      return;
    }
    BACK = null;
    // A dialog over the sheet closes first.
    const dialog = findMaybe(document, 'dialog[open]', HTMLDialogElement);
    if (dialog) {
      dialog.close();
      syncBackLayer(closeTopLayer);
      return;
    }
    closeTopLayer();
  });
}
export { BACK, BACK_SKIP, syncBackLayer, sheetDialog, backLayer, watchBackLayer };
