// ------------------------------------------------ composer
import {
  LAYOUT,
  MID_OVERLAY,
  PICKSEQ,
  PINS,
  REPICK,
  setPickseq,
  setSnipOpen,
  COMPOSE,
  setComposeBox,
  setComposeCurrent,
  setComposeDismissedOverlap,
  setComposeIntent,
  setComposePicking,
} from '../app/state.ts';
import { setBusy, renderComposer } from './flow-selection.ts';
import { html } from '../platform/markup.ts';
import { errText } from '../platform/i18n.ts';
import { API_OUT, API_WAIT, api, isApiError, isRefusal } from '../platform/api.ts';
import { endTopic } from '../platform/notices.ts';
import { LAST_POINTER } from '../platform/tooltip.ts';
import { applySide, relayout, setSide } from '../layout/flow.ts';
import { clearSelectionParts, revealBox } from '../pdf/input-selection.ts';
import { clearPendingSave } from './view-save.ts';
import { savePin } from './flow-save.ts';
import { SELECTION_POPOVER_FIELD, drawSelectionPopover, isSelectionPopoverOpen } from './view-selection-popover.ts';
import { refreshDoc } from '../documents/flow-rebuild.ts';
import { NOTICE_TOPIC } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { overlapsFor } from '../app/rules-pins.ts';
import { isMarkdownDoc, isRegion } from '../documents/state.ts';
import { offlineNow } from '../documents/flow-polling.ts';
import { useLevel } from '../documents/rules.ts';
import { composerPins, composerQueue, composerVerdict } from './state-seams.ts';
import type { PickDrag } from './state-seams.ts';
import { banner, bannerCompare, bannerRepick } from './flow-repick-banner.ts';

// Turns a dragged PDF region into source lines (/api/pick) and fills the composer - or, while relocating, the banner. A
// new selection opens a collapsed panel; stale responses (PICKSEQ) are dropped; a save queued meanwhile runs after it.
// The first-visit hint on how to pick goes (endTopic): it has been done.
async function pick(region: PickDrag) {
  const seq = setPickseq(PICKSEQ + 1),
    repick = REPICK;
  endTopic(NOTICE_TOPIC.PICK); // the first-visit hint on how to pick has been done
  // When a new selection (not a re-place) starts, the previous COMPOSE.current is cleared at once, so a [핀 저장] while
  // the pick runs never saves the stale COMPOSE.current - the old place - and instead goes through the
  // COMPOSE.pendingSave queue (docs/handbook/viewer.md §패널 정리) to save the place just chosen.
  if (repick) {
    banner(html`<span>되짚는 중…</span>`);
  } else {
    setComposeCurrent(null);
    setComposeIntent(COMPOSE.intent + 1);
    $('#composer').hidden = false;
    setBusy(true);
    setComposePicking(true);
    $('#c-err').hidden = true;
    $('#c-body').hidden = false;
    // a second pick over a selection: its verdict buttons go off, with the reason, until the place is found
    composerVerdict().drawRow();
    setSide(true);
    applySide(); // a collapsed panel opens for a new selection in every layout (wide included)
    // composing in the overlay pads the PDF by the panel width (CSS): re-fit now, then reveal the box
    if (MID_OVERLAY) relayout();
    if (LAYOUT !== LAYOUT_MODE.WIDE) {
      $('#right').scrollTop = 0;
      revealBox(COMPOSE.box);
    }
  }
  let answer;
  // A new selection the server cannot be reached for is not a failure: offlinePick opens the composer on it and says
  // what happens next, so the call does not say '위치 찾기 실패' over that. A re-place and a Markdown or text
  // document have no such way on, and say it.
  // While the connection is known to be gone, or the last request to end got no answer (API_OUT - the poll has not
  // counted its two failures yet), the server is not asked at all: each drag would wait out a request that cannot be
  // answered before its composer opened. And a request that is asked waits no longer than API_WAIT.PICK.
  try {
    if (!repick && !isMarkdownDoc() && (offlineNow() || API_OUT)) throw new Error('cut off');
    answer = (
      await api('POST /api/pick', {
        body: region,
        what: '위치 찾기',
        quietUnreached: !repick && !isMarkdownDoc(),
        wait: API_WAIT.PICK,
      })
    ).data;
  } catch (error) {
    if (seq !== PICKSEQ) return;
    setBusy(false);
    if (!repick) {
      setComposePicking(false);
      clearPendingSave();
    }
    // The server could not be reached (a refusal carries a status): the drag is not lost. Its box stays and the
    // composer opens on a selection with no lines, which [핀 저장] keeps in the queue until the connection is back
    // (offline/flow.ts).
    if (!repick && !isApiError(error) && !isMarkdownDoc()) {
      void composerQueue().pick(region);
      return;
    }
    if (repick) {
      bannerRepick();
    } else {
      clearSelectionParts('compose');
      if (COMPOSE.box) {
        COMPOSE.box.remove();
        setComposeBox(null);
      }
      if (!COMPOSE.current) {
        $('#composer').hidden = true;
        applySide();
      }
      drawSelectionPopover();
    }
    return;
  }
  if (seq !== PICKSEQ) return;
  setBusy(false);
  if (!repick) setComposePicking(false);
  if (isRefusal(answer)) {
    if (answer.pdf_build_gone) {
      try {
        await refreshDoc();
      } catch (error) {}
      if (seq !== PICKSEQ) return;
      if (repick && repick.box) {
        clearSelectionParts('repick');
        repick.box.remove();
        repick.box = null;
      } else if (!repick && COMPOSE.box) {
        clearSelectionParts('compose');
        COMPOSE.box.remove();
        setComposeBox(null);
      }
    }
    if (repick) {
      bannerRepick(errText(answer));
      return;
    }
    // A failed pick never carries out a pending save - only the error panel is shown, so a save never fails silently.
    setComposeCurrent(null);
    setComposeIntent(COMPOSE.intent + 1);
    clearPendingSave();
    $('#c-err').textContent = errText(answer);
    $('#c-err').hidden = false;
    $('#c-body').hidden = true;
    drawSelectionPopover();
    return;
  }
  if (repick) {
    repick.cand = answer;
    bannerCompare();
    return;
  }
  const selection: ComposerSelection = answer;
  setComposeCurrent(selection);
  setComposeIntent(COMPOSE.intent + 1);
  selection.scope = null;
  selection.elSel = answer.el || null;
  if (!isRegion(answer)) {
    useLevel(selection, answer.default_level);
    if (!selection.scope) {
      selection.lo = answer.lo;
      selection.hi = answer.hi;
    }
  }
  // a freshly chosen selection - re-notified even if [별도 핀으로 저장] was pressed for a previous selection
  setComposeDismissedOverlap(null);
  selection.overlaps = overlapsFor(selection, PINS);
  // If a pin the server saw as overlapping isn't in this tab's PINS (someone else just saved it), the list is
  // re-fetched - loadPins recomputes overlap too.
  if ((answer.overlaps || []).some((overlap: PickOverlap) => !PINS.some((pin) => pin.id === overlap.id)))
    composerPins().load();
  setSnipOpen(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  renderComposer();
  // so a second drag's new location/ladder never hides above the scroll (the note stays as-is)
  $('#composer').scrollTop = 0;
  if (LAYOUT !== LAYOUT_MODE.WIDE) $('#right').scrollTop = 0;
  // Drag -> straight into the note field - the popover's by the box while it is open
  // (composer/view-selection-popover.ts), else the composer's. Never focused on touch - the virtual keyboard would pop
  // up immediately and cover the range ladder and page.
  if (LAST_POINTER === 'mouse')
    (isSelectionPopoverOpen() ? SELECTION_POPOVER_FIELD : $('#note')).focus({ preventScroll: true });
  // If [핀 저장] was pressed while the pick was still running, the queued save runs here (COMPOSE.current has just been
  // filled in).
  if (COMPOSE.pendingSave) {
    clearPendingSave();
    savePin();
  }
}
export { pick };
