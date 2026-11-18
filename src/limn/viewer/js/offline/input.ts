import { OFFUI, offUiDraw, offUiReveal, toggleQueueSection, type OffUiUndo } from './view.ts';
import { DEFAULT_DOC, DOC, LAYOUT } from '../app/state.ts';
import { translate } from '../platform/i18n.ts';
import { NOTICE_HOLD_MAX, NOTICE_MS, announce, lineNote } from '../platform/notices.ts';
import { switchDoc } from '../documents/flow-switch.ts';
import { setSide } from '../layout/flow.ts';
import { setKind } from '../composer/flow-selection.ts';
import { saveDraftSoon } from '../composer/flow-draft.ts';
import { OFF, offDel, offPut, offlineSync, type QueuedPin } from './flow.ts';
import { marksShow } from '../pins/input-hide-marks.ts';
import { setAssignNewValue, setAssignNewTouched } from '../composer/state-assignee.ts';
import { renderAssignNew } from '../composer/input-mentions.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $, eventClosest, eventElement, findMaybe } from '../platform/dom.ts';
import { REQUEST_KIND, LAYOUT_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc, docInfo } from '../documents/state.ts';
import { autoGrow } from '../composer/view-text.ts';
import { arrivePage } from '../pdf/view-page-jump.ts';

// The queued record with this id, or null.
function offUiRec(id: number): QueuedPin | null {
  return OFFUI.all.find((record) => record && record.id === id) || null;
}
// A row's place: this document's page (and its mark, flashed), or another document, switched to.
function offUiGo(rec: QueuedPin) {
  const docName = rec.doc || DEFAULT_DOC;
  if (docName !== (DOC || DEFAULT_DOC)) {
    void switchDoc(docName);
    return;
  }
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false); // the sheet folds first so the page is not under it
  marksShow();
  // A record with no page (a line pin) has no page to go to.
  if (typeof rec.page === 'number') arrivePage(rec.page);
  const mark = findMaybe(document, '.qmark[data-qid="' + rec.id + '"]', HTMLElement);
  if (mark) {
    mark.classList.remove('flash');
    void mark.offsetWidth;
    mark.classList.add('flash');
  }
}
// [버리기]: the record goes now and is never sent. Its undo row stands in its place (offUiUndoRow) and puts the record
// back as it was - its key is its id, so it takes its place in the order again.
async function offUiDrop(rec: QueuedPin, button: HTMLElement) {
  if (offUiBusy()) return;
  const had = document.activeElement === button;
  await offDel(rec.id);
  offUiUndoStart(rec, false, '');
  await offlineSync();
  announce(translate('쌓인 핀을 버렸습니다'));
  if (had) offUiFocusUndo(rec.id);
}
// [다시 찍기]: the record leaves the queue and its note, @-tags, kind and assignee go into the composer, where they
// wait for the next drag (or join the selection already open). A note already being written is not overwritten: the
// person saves or discards it first. Another document's record switches to that document first - its draft is that
// document's. A record that may already be a pin on the server (sent, no answer) is not taken back.
async function offUiRedo(rec: QueuedPin, button: HTMLElement) {
  if (offUiBusy()) return;
  const docName = rec.doc || DEFAULT_DOC,
    had = document.activeElement === button;
  // A record whose write was attempted and never answered may be a pin on the server already: taken back and drawn
  // again it would be made twice. The next send asks the server by its key and either ends the record or takes the
  // mark off (offline/flow.ts offlineFlush), so this is refused only until then.
  if (rec.sent) {
    lineNote(
      '보낸 적이 있어 서버에 이미 있을 수 있습니다 — 연결된 뒤 [지금 반영]으로 확인하세요',
      NOTICE_KIND.WARN,
      null,
      { life: NOTICE_LIFE.CLICK },
    );
    return;
  }
  if (docName !== (DOC || DEFAULT_DOC)) {
    if (!docInfo(docName)) return;
    await switchDoc(docName);
    if ((DOC || DEFAULT_DOC) !== docName) return;
  }
  const note = $('#note'),
    text = String(rec.note || '');
  if (note.value.trim() && note.value.trim() !== text.trim()) {
    lineNote('작성 중인 메모가 있습니다 — 저장하거나 버린 뒤 다시 찍으세요', NOTICE_KIND.WARN, null, {
      life: NOTICE_LIFE.CLICK,
    });
    return;
  }
  await offDel(rec.id);
  note.value = text;
  note._mentions = (rec.mentions || []).length ? new Set(rec.mentions) : null;
  setKind(rec.kind_req === REQUEST_KIND.QUESTION ? REQUEST_KIND.QUESTION : REQUEST_KIND.FIX);
  if (rec.assignee) {
    setAssignNewValue(rec.assignee);
    setAssignNewTouched(true);
  }
  renderAssignNew();
  autoGrow(note);
  saveDraftSoon();
  offUiUndoStart(rec, true, text);
  await offlineSync();
  announce(translate('메모를 작성 칸에 두었습니다') + ' · ' + translate('자리를 다시 끌어 고르세요'));
  if (!$('#composer').hidden) note.focus({ preventScroll: true });
  else if (had) offUiFocusUndo(rec.id);
  // The page it was on, beside the panel.
  if (LAYOUT === LAYOUT_MODE.WIDE && typeof rec.page === 'number' && Number.isInteger(rec.page) && !isMarkdownDoc())
    arrivePage(rec.page);
}
// While the queue is being sent a record may be on its way: it is neither dropped nor taken back until that is over.
function offUiBusy() {
  if (!OFF.flushing) return false;
  lineNote('쌓인 핀을 반영하는 중입니다 — 끝난 뒤 다시 누르세요', NOTICE_KIND.INFO, null, { life: NOTICE_LIFE.TIMER });
  return true;
}

// ---------------- The undo rows' windows
// Stands a record's undo row (replacing one it already has) and starts its window.
function offUiUndoStart(rec: QueuedPin, redo: boolean, text: string) {
  const old = OFFUI.undos.get(rec.id);
  if (old) clearTimeout(old.t);
  const now = Date.now(),
    undo: OffUiUndo = { rec, redo, text, at: now, from: now, t: undefined, busy: false, hover: false };
  OFFUI.undos.set(rec.id, undo);
  offUiArm(undo);
}
// The row's window: NOTICE_MS, or - while a mouse is on it - until it leaves, but never past NOTICE_HOLD_MAX beyond the
// first window (platform/notices.ts armNotice, the same rule for every undo). Stopped while its record is being put
// back.
function offUiArm(undo: OffUiUndo) {
  clearTimeout(undo.t);
  undo.t = undefined;
  if (undo.busy) return;
  const now = Date.now(),
    left = undo.at + NOTICE_MS + NOTICE_HOLD_MAX - now;
  undo.t = setTimeout(
    () => offUiUndoEnd(undo.rec.id),
    Math.max(0, undo.hover ? left : Math.min(undo.from + NOTICE_MS - now, left)),
  );
}
// The window is over (or [x]): the row goes. A focus on it goes to the row now in its place's neighbourhood, else the
// head.
function offUiUndoEnd(id: number) {
  const undo = OFFUI.undos.get(id);
  if (!undo) return;
  clearTimeout(undo.t);
  OFFUI.undos.delete(id);
  const active = document.activeElement,
    row = active && active.closest ? active.closest('#queue-rows>[data-undo]') : null,
    isInRow = !!row && row.getAttribute('data-qid') === String(id);
  const sibling = isInRow && row ? row.nextElementSibling || row.previousElementSibling : null;
  offUiDraw();
  if (isInRow) {
    const button =
      (sibling && sibling.isConnected && sibling.querySelector('button')) ||
      (!$('#sec-queue').hidden && $('#queue-toggle')) ||
      null;
    if (button) button.focus({ preventScroll: true });
  }
}
// [되돌리기]: the record goes back into the queue as it was. A take-back's note leaves the composer with it - unless it
// is no longer the same note there (written on, or already saved with a drag): then the record would make a second pin,
// so it is not put back and the line says why.
async function offUiUndo(id: number) {
  const undo = OFFUI.undos.get(id);
  if (!undo || undo.busy) return;
  const note = $('#note'),
    isInRow =
      !!document.activeElement &&
      !!document.activeElement.closest &&
      !!document.activeElement.closest('#queue-rows>[data-undo]');
  // The composer's note is the document on screen's draft: on another document it is that document's, and clearing it
  // (and saving the draft) would take a note this record never put there. The take-back is undone only where it was
  // made.
  if (undo.redo && (DOC || DEFAULT_DOC) !== (undo.rec.doc || DEFAULT_DOC)) {
    offUiUndoEnd(id);
    lineNote('다른 문서로 옮겨 되돌리지 않았습니다 — 그 문서에서 메모를 지우세요', NOTICE_KIND.INFO, null, {
      life: NOTICE_LIFE.TIMER,
    });
    return;
  }
  if (undo.redo && note.value !== undo.text) {
    offUiUndoEnd(id);
    lineNote('메모가 이미 바뀌어 되돌리지 않았습니다', NOTICE_KIND.INFO, null, { life: NOTICE_LIFE.TIMER });
    return;
  }
  undo.busy = true;
  clearTimeout(undo.t);
  offUiDraw();
  const ok = (await offPut(undo.rec)) !== null;
  if (ok && undo.redo) {
    note.value = '';
    note._mentions = null;
    autoGrow(note);
    saveDraftSoon();
  }
  clearTimeout(undo.t);
  OFFUI.undos.delete(id);
  await offlineSync();
  if (!ok) {
    lineNote('되돌리지 못했습니다 — 이 브라우저가 오프라인 보관을 막고 있습니다', NOTICE_KIND.ERR, null, {});
    return;
  }
  if (isInRow) {
    const button = findMaybe(
      $('#sec-queue'),
      '.qrow[data-qid="' + id + '"] [data-q="' + (undo.redo ? 'redo' : 'drop') + '"]',
      HTMLElement,
    );
    if (button) button.focus({ preventScroll: true });
  }
}
// Puts the focus on a record's undo row's [되돌리기].
function offUiFocusUndo(id: number) {
  const button = findMaybe($('#sec-queue'), '[data-undo][data-qid="' + id + '"] [data-q="undo"]', HTMLElement);
  if (button) button.focus({ preventScroll: true });
}

$('#sec-queue').addEventListener('click', (event: MouseEvent) => {
  const target = eventElement(event),
    button = target && target.closest('button');
  if (!button) return;
  if (button.id === 'queue-toggle') {
    toggleQueueSection();
    return;
  }
  const id = Number(button.dataset.qid),
    action = button.dataset.q;
  if (action === 'undo') {
    void offUiUndo(id);
    return;
  }
  if (action === 'undo-x') {
    offUiUndoEnd(id);
    return;
  }
  const rec = offUiRec(id);
  if (!rec) return;
  if (action === 'go') offUiGo(rec);
  else if (action === 'drop') void offUiDrop(rec, button);
  else if (action === 'redo') void offUiRedo(rec, button);
});
// A mouse on an undo row holds its window; leaving it starts the window again (the status line's undos do the same).
$('#queue-rows').addEventListener(
  'pointermove',
  (event: PointerEvent) => {
    if (event.pointerType !== 'mouse') return;
    const row = eventClosest(event, '[data-undo]', HTMLElement);
    const undo = row ? OFFUI.undos.get(Number(row.dataset.qid)) : undefined;
    if (undo && !undo.hover) {
      undo.hover = true;
      offUiArm(undo);
    }
  },
  { passive: true },
);
$('#queue-rows').addEventListener('pointerout', (event: PointerEvent) => {
  const row = eventClosest(event, '[data-undo]', HTMLElement);
  if (!row) return;
  const to = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (to && row.contains(to)) return;
  const undo = OFFUI.undos.get(Number(row.dataset.qid));
  if (undo && undo.hover) {
    undo.hover = false;
    undo.from = Date.now();
    offUiArm(undo);
  }
});
// A mark's badge takes its press away from the page: a press on it never starts a selection, a long press or a tap's
// selection there (pdf/input-selection.ts reads presses on #doc, and the frame itself lets them through). Its click
// shows the row.
$('#doc').addEventListener(
  'pointerdown',
  (event: PointerEvent) => {
    if (eventClosest(event, '.qmark-jump', Element)) event.stopPropagation();
  },
  true,
);
$('#doc').addEventListener(
  'mousedown',
  (event: MouseEvent) => {
    if (eventClosest(event, '.qmark-jump', Element)) {
      event.stopPropagation();
      event.preventDefault();
    }
  },
  true,
);
$('#doc').addEventListener('click', (event: MouseEvent) => {
  const button = eventClosest(event, '.qmark-jump', HTMLElement);
  if (!button) return;
  offUiReveal(Number(button.dataset.qid));
});
// The pages are drawn again (a new build, a zoom that rebuilds them, another document): the marks go with the old
// pages, and which records this document and build draw has changed - both are drawn again.
new MutationObserver(() => offUiDraw()).observe($('#doc'), { childList: true });
