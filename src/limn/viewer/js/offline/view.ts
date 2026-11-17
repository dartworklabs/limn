// ----------------------------------------- The queued pins on screen (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기)
// offline/flow.ts reads the queue (offlineSync) on boot, after every pin kept, dropped or sent, and calls
// offlineUiSync(all) with every record each time. This part draws them: where they stand on the page and in the pin
// panel. A queued pin is not on the server yet, so it is drawn apart from a saved pin's mark: a dotted frame with no
// number (it has none yet), its badge a clock - or, held back because its place could not be found again, a warning
// triangle in the warning colour. The panel's section lists every record with its place, words, note and state, and two
// actions: [버리기] (its undo on the status line, since the row is gone) and [다시 찍기] (the record leaves the queue
// and its note waits in the composer for the next drag, the draft's own behaviour, composer/flow-draft.ts). Nothing
// here writes to the server.
import { DEFAULT_DOC, DOC, LAYOUT, META, scrollMotion } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { NOTICE_HOLD_MAX, NOTICE_MS, announce, lineNote, noticeIcon } from '../platform/notices.ts';
import { switchDoc } from '../documents/flow-switch.ts';
import { setSide } from '../layout/flow.ts';
import { setKind } from '../composer/flow-pick.ts';
import { saveDraftSoon } from '../composer/flow-draft.ts';
import { OFF, offDel, offPut, offlineSync, type QueuedPin } from './flow.ts';
import { marksShow } from '../pins/input-hide-marks.ts';
import { ASSIGN_NEW, renderAssignNew } from '../composer/input-mentions.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $, $$ } from '../platform/dom.ts';
import { REQUEST_KIND, LAYOUT_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc, docInfo } from '../documents/state.ts';
import { autoGrow } from '../composer/view-text.ts';
import { arrivePage } from '../pdf/view-page-jump.ts';
/** A record just dropped ([버리기]) or taken back ([다시 찍기], redo: its note text is in the composer), standing as
 * its undo row until its window ends: NOTICE_MS from `from` (its start, again when a mouse leaves it), held while a
 * mouse is on the row (hover), never past NOTICE_HOLD_MAX beyond its first window (`at`).
 */
type OffUiUndo = {
  rec: QueuedPin;
  redo: boolean;
  text: string;
  at: number;
  from: number;
  t: ReturnType<typeof setTimeout> | undefined;
  busy: boolean;
  hover: boolean;
};
// The queue's panel and page marks (OFFUI): the queued pins last drawn, whether the panel is open, the undo row of each
// record just dropped or taken back, by its key, and the timer that ends a panel row's flash (0 before the first).
interface OfflineUiState {
  all: QueuedPin[];
  open: boolean;
  undos: Map<number, OffUiUndo>;
  flashT: ReturnType<typeof setTimeout> | 0;
}
const OFFUI: OfflineUiState = {
  all: [],
  open: true,
  undos: new Map(),
  flashT: 0,
};

// Whether frac is a box on the page: four finite numbers, the box inside the page with some size. A record from
// another version of this viewer, or one written by hand, must not draw a frame off the page. Pure.
function offUiFrac(frac: unknown): boolean {
  if (!Array.isArray(frac) || frac.length < 4) return false;
  if (!frac.slice(0, 4).every((value) => typeof value === 'number' && Number.isFinite(value))) return false;
  return (
    frac[0] >= 0 &&
    frac[1] >= 0 &&
    frac[2] > 0 &&
    frac[3] > 0 &&
    frac[0] + frac[2] <= 1 + 1e-6 &&
    frac[1] + frac[3] <= 1 + 1e-6
  );
}
// The rows the panel lists and the marks the page draws, from every queued record (oldest first): this document's
// records first, then the others', each in the order they were written - the order they are sent. A row says what it
// is: `here` (on the document on screen), `lines` (a Markdown or text document's line pin, which has no page), `mark`
// (drawn on the page: here, on the build on screen - its box is that build's - and on a page this document has), `old`
// (here, drawn on another build: listed, not drawn). doc is the document on screen, defaultDoc the one a record with no
// document belongs to, build the build on screen, pageCount its page count. Pure.
function offUiRows(all: QueuedPin[], doc: string, defaultDoc: string, build: string, pageCount: number) {
  const rows = (Array.isArray(all) ? all : [])
    .filter((record) => record && typeof record === 'object')
    .map((rec) => {
      const here = (rec.doc || defaultDoc) === (doc || defaultDoc),
        lines = rec.page == null && !!rec.lines && typeof rec.lines === 'object';
      const page = typeof rec.page === 'number' && Number.isInteger(rec.page) && rec.page >= 1 ? rec.page : null,
        onDoc = page !== null && page <= pageCount;
      const mark = here && !lines && onDoc && !!build && rec.build === build && offUiFrac(rec.frac);
      return {
        rec,
        here,
        lines,
        page,
        mark,
        old: here && !lines && !!rec.build && rec.build !== build,
        held: !!rec.held,
      };
    });
  return rows.filter((row) => row.here).concat(rows.filter((row) => !row.here));
}
// Why a held record is held: the reason it carries, or - an empty one - the reason a held record always has
// (offline/flow.ts writes this one when it has no other). '' for a record that waits. Pure but for translate.
function offUiWhy(rec: QueuedPin | null): string {
  if (!rec || !rec.held) return '';
  const reason = String(rec.why || '').trim();
  return reason || translate('위치를 찾지 못했습니다');
}
// Where a record was pinned, as the row and the mark's tip say it: '3쪽', a line pin's 'intro.md 12–14줄' (one line:
// '12줄'), '' when it says neither. Pure but for translateTemplate.
function offUiPlace(rec: QueuedPin | null): string {
  const lines = rec && rec.lines;
  if (rec && rec.page == null && lines && typeof lines === 'object') {
    const name =
      String(lines.file || '')
        .split('/')
        .pop() || '';
    const firstLine = Number(lines.lo),
      lastLine = Number(lines.hi);
    if (!Number.isFinite(firstLine)) return name;
    return (
      (name ? name + ' ' : '') +
      (Number.isFinite(lastLine) && lastLine !== firstLine
        ? translateTemplate('{lo}–{hi}줄', { lo: firstLine, hi: lastLine })
        : translateTemplate('{lo}줄', { lo: firstLine }))
    );
  }
  return rec && typeof rec.page === 'number' && Number.isInteger(rec.page) && rec.page >= 1
    ? translateTemplate('{page}쪽', { page: rec.page })
    : '';
}
// A one-line excerpt of text: its white space folded, cut at limit characters with an ellipsis. Pure.
function offUiClip(text: unknown, limit: number): string {
  const folded = String(text == null ? '' : text)
    .replace(/\s+/g, ' ')
    .trim();
  return folded.length > limit ? folded.slice(0, limit - 1) + '…' : folded;
}

/** Draws the queue anew from every queued record.
 * @param all every queued record, oldest first (offline/flow.ts offAll) */
function offlineUiSync(all: QueuedPin[]) {
  OFFUI.all = Array.isArray(all) ? all : [];
  offUiDraw();
}
// The view of the queue for the document and build on screen.
function offUiView() {
  const pages = META && !isMarkdownDoc() && Array.isArray(META.pages) ? META.pages.length : 0;
  return offUiRows(OFFUI.all, DOC || DEFAULT_DOC, DEFAULT_DOC, (META && META.pages_build) || '', pages);
}
// Draws the marks and the panel's section for the document and build on screen.
function offUiDraw() {
  const rows = offUiView();
  offUiMarks(rows);
  offUiList(rows);
}

// The marks: one dotted frame per queued record drawn on the page on screen, under the saved pins' marks' own layer
// (they are drawn into the same page box, after them). The frame lets every press through to the page, as a saved mark
// does - a drag over it is a new selection; only its badge takes a press, which brings the panel's row into view.
function offUiMarks(rows: ReturnType<typeof offUiRows>) {
  $$('.qmark').forEach((mark) => mark.remove());
  rows.forEach((row) => {
    if (!row.mark) return;
    const pageBox = document.getElementById('p' + row.page);
    // A mark's frac is a box on the page (offUiFrac).
    const frac = row.rec.frac;
    if (!pageBox || !frac) return;
    const mark = document.createElement('div');
    mark.className = 'qmark' + (row.held ? ' held' : '');
    mark.dataset.qid = String(row.rec.id);
    Object.assign(mark.style, {
      left: frac[0] * 100 + '%',
      top: frac[1] * 100 + '%',
      width: frac[2] * 100 + '%',
      height: frac[3] * 100 + '%',
    });
    const note = offUiClip(row.rec.note, 60) || translate('(메모 없음)'),
      why = offUiWhy(row.rec);
    const tip =
      (row.held ? translate('보류된 핀') + ' · ' + why : translate('쌓인 핀 · 연결되면 반영합니다')) + ' — ' + note;
    // A badge too close to the page's left edge to stand outside the box stands in its corner, as a saved one does.
    const inner = frac[0] * pageBox.clientWidth < 28;
    if (inner) mark.classList.add('in');
    setHtml(
      mark,
      html`<button type="button" class="qmark-jump" translate="no" data-qid="${row.rec.id}" aria-label="${row.held ? translate('보류된 핀 — 목록에서 보기') : translate('쌓인 핀 — 목록에서 보기')}" data-tip="${tip}">${lucideIcon(row.held ? 'triangle-alert' : 'clock')}</button>`,
    );
    pageBox.appendChild(mark);
  });
}

// The section in the pin panel (#sec-queue): hidden while the queue is empty, else a head with its count (and how many
// are held), a line saying what these are, and one row per record. Sending them now is the status line's [지금 반영],
// shown whenever there is a connection to send on.
// A record dropped or taken back a moment ago keeps its place in the order as its undo row (offUiUndoRow) while that
// lasts, so the section stays while one stands even with the queue empty.
function offUiList(rows: ReturnType<typeof offUiRows>) {
  const section = $('#sec-queue');
  if (!section) return;
  const focused = offUiFocus(),
    undos = [...OFFUI.undos.values()];
  section.hidden = !rows.length && !undos.length;
  if (section.hidden) {
    $('#queue-rows').replaceChildren();
    return;
  }
  const held = rows.filter((row) => row.held).length;
  setHtml(
    $('#queue-toggle'),
    html`${lucideIcon(OFFUI.open ? 'chevron-down' : 'chevron-right')}<span class="sec-name" id="queue-h">${translate('쌓인 핀')} <span class="badge badge-secondary sec-n">${rows.length}</span></span>${held ? html`<span class="badge q-held-n">${lucideIcon('triangle-alert')}${translateTemplate('보류 {n}', { n: held })}</span>` : ''}`,
  );
  $('#queue-toggle').setAttribute('aria-expanded', String(OFFUI.open));
  $('#queue-body').hidden = !OFFUI.open;
  const here = (rec: QueuedPin) => ((rec.doc || DEFAULT_DOC) === (DOC || DEFAULT_DOC) ? 0 : 1);
  const items = rows
    .map((row) => ({ rec: row.rec, h: offUiRow(row) }))
    .concat(undos.map((undo) => ({ rec: undo.rec, h: offUiUndoRow(undo) })))
    .sort(
      (first, second) =>
        here(first.rec) - here(second.rec) || (Number(first.rec.id) || 0) - (Number(second.rec.id) || 0),
    );
  setHtml($('#queue-rows'), html`${items.map((x) => x.h)}`);
  offUiFocusBack(focused);
}
// One row: its state (a clock and '대기', or a triangle and '보류' with its reason - words, never the colour alone),
// where it was pinned (a link to that page; another document's row names that document and goes there), the words it
// was drawn over, its note, and its two actions. A long note is folded to three lines by CSS; the whole of it stays in
// the row.
function offUiRow(row: ReturnType<typeof offUiRows>[number]) {
  const rec = row.rec,
    id = rec.id,
    place = offUiPlace(rec),
    why = offUiWhy(rec),
    quoteText = offUiClip(rec.quote, 160),
    note = String(rec.note || '').trim();
  const info = row.here ? null : docInfo(rec.doc || DEFAULT_DOC),
    docLabel = row.here ? '' : (info && info.name) || rec.doc || '';
  const goes = !row.here
    ? !!info
    : row.page !== null && !row.lines && row.page <= (META && META.pages ? META.pages.length : 0);
  const at = html`${docLabel ? html`<span class="q-doc" translate="no">${docLabel}</span>` : ''}${place ? html`<span class="q-place">${place}</span>` : ''}`;
  const where = goes
    ? html`<button type="button" class="q-go" data-q="go" data-qid="${id}" data-tip="${row.here ? translate('이 쪽으로 갑니다') : translate('이 문서로 바꿉니다')}">${at}</button>`
    : docLabel || place
      ? html`<span class="q-at">${at}</span>`
      : '';
  const name =
    (row.held ? translate('보류') : translate('대기')) +
    (place ? ' · ' + place : '') +
    (docLabel ? ' · ' + docLabel : '');
  return html`<div class="qrow${row.held ? ' held' : ''}" role="group" aria-label="${translateTemplate('쌓인 핀: {what}', { what: name })}" data-qid="${id}">\
<div class="q-head"><span class="q-st">${lucideIcon(row.held ? 'triangle-alert' : 'clock')}<span>${row.held ? translate('보류') : translate('대기')}</span></span>${where}</div>\
${row.held ? html`<p class="q-why">${why}</p>` : ''}\
${row.old ? html`<p class="q-old">${translate('다른 PDF에서 찍어 쪽 위에 그리지 않았습니다')}</p>` : ''}\
${quoteText ? html`<p class="q-quote" translate="no">${quoteText}</p>` : ''}\
<p class="q-note${note ? '' : ' dim'}" translate="no">${note || translate('(메모 없음)')}</p>\
<div class="q-acts"><button type="button" class="btn-sm btn-secondary" data-q="redo" data-qid="${id}" data-tip="${translate('이 핀을 쌓인 목록에서 빼고 메모를 작성 칸에 둡니다. 다음에 끈 자리가 이 메모로 새 핀이 됩니다')}">${translate('다시 찍기')}</button>\
<button type="button" class="btn-sm btn-ghost q-drop" data-q="drop" data-qid="${id}" data-tip="${translate('이 핀을 보내지 않고 버립니다. 그 자리에 남는 [되돌리기]로 되살립니다')}">${translate('버리기')}</button></div></div>`;
}
// The undo of a drop or a take-back, in the row's place (docs/handbook/viewer.md §알림 자리, an undo stays where the
// action was): the dashed undo row of the list, its words, [되돌리기] (busy while the record is put back) and [x]. The
// status line is not its place: there the kept pins' own count comes before every message, so the undo would stand
// behind '+N'.
function offUiUndoRow(undo: OffUiUndo) {
  const id = undo.rec.id,
    place = offUiPlace(undo.rec),
    title = undo.redo ? translate('메모를 작성 칸에 두었습니다') : translate('쌓인 핀을 버렸습니다');
  const detail = undo.redo ? translate('자리를 다시 끌어 고르세요') : place;
  return html`<div class="nt nt-row nk-${NOTICE_KIND.OK}" role="group" aria-label="${title}" data-qid="${id}" data-undo="1"><span class="nt-ic">${noticeIcon(NOTICE_KIND.OK)}</span>\
<span class="nt-t" translate="no"><span class="nt-ti">${title}</span>${detail ? html`<span class="nt-d">${detail}</span>` : ''}</span>\
<span class="nt-acts"><button type="button" class="btn-sm btn-secondary nt-act" data-q="undo" data-qid="${id}" data-tip="${TIP_TEXT.undo}"${undo.busy ? html` aria-busy="true"` : ''}><span class="lbl">${translate('되돌리기')}</span></button>\
<button type="button" class="btn-icon btn-sm btn-ghost nt-x" data-q="undo-x" data-qid="${id}" aria-label="${translate('알림 닫기')}">${lucideIcon('x')}</button></span></div>`;
}

// The keyboard focus on one of the section's buttons, as its action and record, so a redraw gives it back (a redraw
// comes whenever the queue is read, which another tab or a send may cause at any time).
function offUiFocus(): { q: string; id: string } | null {
  const active = document.activeElement as HTMLElement | null;
  return active && active.closest && active.closest('#sec-queue') && active.dataset.q
    ? { q: active.dataset.q, id: active.dataset.qid || '' }
    : null;
}
// Gives the focus back to the button offUiFocus noted, when the redraw left it nowhere.
function offUiFocusBack(focused: { q: string; id: string } | null) {
  if (!focused) return;
  const active = document.activeElement;
  if (active && active !== document.body && document.contains(active)) return;
  const button = $('#sec-queue').querySelector(
    '[data-q="' + focused.q + '"]' + (focused.id ? '[data-qid="' + focused.id + '"]' : ''),
  ) as HTMLElement | null;
  if (button) button.focus({ preventScroll: true });
}

// The queued record with this id, or null.
function offUiRec(id: number): QueuedPin | null {
  return OFFUI.all.find((record) => record && record.id === id) || null;
}
// Shows the row of record id in the panel: opens the panel and the section, scrolls the row into view and flashes it.
function offUiReveal(id: number) {
  setSide(true);
  if (!OFFUI.open) {
    OFFUI.open = true;
    offUiDraw();
  }
  requestAnimationFrame(() => {
    const row = document.querySelector('.qrow[data-qid="' + id + '"]') as HTMLElement | null;
    if (!row) return;
    row.scrollIntoView({ behavior: scrollMotion(), block: 'nearest' });
    row.classList.remove('flash');
    void row.offsetWidth;
    row.classList.add('flash');
    clearTimeout(OFFUI.flashT);
    OFFUI.flashT = setTimeout(() => row.classList.remove('flash'), 1200);
  });
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
  const mark = document.querySelector('.qmark[data-qid="' + rec.id + '"]') as HTMLElement | null;
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
    ASSIGN_NEW.v = rec.assignee;
    ASSIGN_NEW.touched = true;
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
  const sibling =
    isInRow && row ? ((row.nextElementSibling || row.previousElementSibling) as HTMLElement | null) : null;
  offUiDraw();
  if (isInRow) {
    const button = ((sibling && sibling.isConnected && sibling.querySelector('button')) ||
      (!$('#sec-queue').hidden && $('#queue-toggle')) ||
      null) as HTMLElement | null;
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
    const button = $('#sec-queue').querySelector(
      '.qrow[data-qid="' + id + '"] [data-q="' + (undo.redo ? 'redo' : 'drop') + '"]',
    ) as HTMLElement | null;
    if (button) button.focus({ preventScroll: true });
  }
}
// Puts the focus on a record's undo row's [되돌리기].
function offUiFocusUndo(id: number) {
  const button = $('#sec-queue').querySelector(
    '[data-undo][data-qid="' + id + '"] [data-q="undo"]',
  ) as HTMLElement | null;
  if (button) button.focus({ preventScroll: true });
}

$('#sec-queue').addEventListener('click', (event: MouseEvent) => {
  const button = (event.target as HTMLElement).closest('button') as HTMLElement | null;
  if (!button) return;
  if (button.id === 'queue-toggle') {
    OFFUI.open = !OFFUI.open;
    offUiDraw();
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
    const row = (event.target as HTMLElement).closest('[data-undo]') as HTMLElement | null;
    const undo = row ? OFFUI.undos.get(Number(row.dataset.qid)) : undefined;
    if (undo && !undo.hover) {
      undo.hover = true;
      offUiArm(undo);
    }
  },
  { passive: true },
);
$('#queue-rows').addEventListener('pointerout', (event: PointerEvent) => {
  const row = (event.target as HTMLElement).closest('[data-undo]') as HTMLElement | null;
  if (!row) return;
  const to = event.relatedTarget as Node | null;
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
    if ((event.target as HTMLElement).closest('.qmark-jump')) event.stopPropagation();
  },
  true,
);
$('#doc').addEventListener(
  'mousedown',
  (event: MouseEvent) => {
    if ((event.target as HTMLElement).closest('.qmark-jump')) {
      event.stopPropagation();
      event.preventDefault();
    }
  },
  true,
);
$('#doc').addEventListener('click', (event: MouseEvent) => {
  const button = (event.target as HTMLElement).closest('.qmark-jump') as HTMLElement | null;
  if (!button) return;
  offUiReveal(Number(button.dataset.qid));
});
// The pages are drawn again (a new build, a zoom that rebuilds them, another document): the marks go with the old
// pages, and which records this document and build draw has changed - both are drawn again.
new MutationObserver(() => offUiDraw()).observe($('#doc'), { childList: true });
export { offlineUiSync };
