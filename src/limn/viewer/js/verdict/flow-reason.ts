// Open, save and dismiss the reason editor for a page verdict. A pending verdict can own a draft before it has a pin ID.
import { verdictOf } from '../app/rules-pins.ts';
import { DOC, captureVisit, currentVisit, META } from '../app/state.ts';
import { viewerBlocked, verdictLabel } from '../documents/state.ts';
import { PINS_APPLIED_SEQ, loadPins } from '../pins/flow-list.ts';
import { api, isApiError } from '../platform/api.ts';
import { findMaybe, searchToPage } from '../platform/dom.ts';
import { translateTemplate, josa, translate, errText, TIP_TEXT } from '../platform/i18n.ts';
import { lineNote, announce, sourceOk } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE, NOTICE_HOST } from '../platform/tables.ts';
import { hideTip } from '../platform/tooltip.ts';
import { commitReason, keepConflict } from './flow-reason-write.ts';
import {
  dropDraft,
  putDraft,
  readAllDrafts,
  parseDraft,
  draftMovedOff,
  joinDrafts,
  saveAllDrafts,
  moveDraft,
  getDraft,
} from './state-drafts.ts';
import { verdictLineRenderer } from './state-line-renderer.ts';
import { pageLineSlot, SAVING_LINES } from './state-lines.ts';
import { rebaseOnLanded, replacesWholeNote } from './state-reason-edit.ts';
import type { ReasonSession } from './state-reason.ts';
import {
  REASON_SESSION,
  findReasonPin,
  hasUnsavedReason,
  WITHDRAWN_PINS,
  disarmReasonEscape,
  keepDraft,
  setReasonSession,
  setKeyGuard,
  DETACHED_SESSIONS,
  isReasonOpenOn,
} from './state-reason.ts';
import { readingPageWithLine } from './view-panel.ts';
import { pageVerdictPins, pageTargetOf, canCancelVerdict, pageTargetShort } from './view-pins.ts';
import { findReasonField } from './view-reason-field.ts';
import {
  reasonTargetName,
  showDraftLine,
  closeReasonPopover,
  focusReasonField,
  focusLine,
  refillLine,
} from './view-reason.ts';

let SESSION_SEQUENCE = 0;

function createReasonSession(
  page: number,
  id: number,
  key: string,
  text: string,
  base: string,
  revision?: number,
  mode?: string,
): ReasonSession {
  return {
    sid: ++SESSION_SEQUENCE,
    page,
    id,
    key,
    doc: DOC,
    visit: captureVisit(),
    text,
    base,
    mode: mode || (base.trim() ? 'replace' : 'add'),
    rev: revision === undefined ? -1 : revision,
    conflict: null,
    from: 0,
    via: [],
    seen: readingPageWithLine() === page,
    listed: false,
    writing: null,
    saved: null,
    tried: [],
    clearTried: false,
    escArm: '',
  };
}

// The current verdict of page `page`'s line on the document on screen, or undefined.
function currentLineVerdict(page: number) {
  return (pageVerdictPins().get(page) || [])[0];
}

// Before a line is drawn: a session of another document or visit goes (its text saved, leaveReason); one whose pin left
// the lists (undone or taken back elsewhere) goes - its text kept as its page's draft, said in one line, and the keys
// typed after its field went are not verdict keys (keepLostReason); else it follows its pin to the page that pin's
// target is on now. Without a session, a document's first lines bring back its newest kept draft (restoreKeptDrafts).
function syncReasonSession() {
  const session = REASON_SESSION;
  if (session && (session.doc !== DOC || !currentVisit(session.visit))) {
    leaveReason();
    return;
  }
  if (!PINS_APPLIED_SEQ) return;
  if (!session) {
    restoreKeptDrafts();
    return;
  }
  const pin = findReasonPin(session.id);
  if (!pin) {
    if (session.listed) keepLostReason(session);
    return;
  } // not listed yet right after its save; gone once it was
  session.listed = true;
  const target = pageTargetOf(pin, META ? META.kind : undefined);
  if (target) session.page = target.page;
}

// The verdict a reason session was for left the lists while it was open - taken back in another tab or by another
// person, or its save undone elsewhere. What was typed is not lost: it waits as its page's draft ('초안 있음' on the
// line, moved to the next verdict saved there), the status line says so, and when the field had the focus the line's
// draft mark takes it and the keys pressed next are not taken as verdict keys - the person was typing text (KEY_GUARD).
function keepLostReason(session: ReasonSession) {
  const field = findReasonField(),
    had = !!field && document.activeElement === field;
  setReasonSession(null);
  if (hasUnsavedReason(session) && !WITHDRAWN_PINS.has(session.id)) {
    dropDraft(session.doc, session.id);
    putDraft(session.doc, 'p' + session.page, session.text, '', -1, { mode: 'add', folded: true, from: session.via });
    lineNote(
      translateTemplate('판정 #{id}{p} 다른 곳에서 거둬졌습니다 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}', {
        id: session.id,
        p: josa(session.id, '이', '가'),
        target: reasonTargetName(session),
      }),
      NOTICE_KIND.WARN,
      null,
      { literal: true },
    );
  }
  if (had) {
    setKeyGuard(true);
    PENDING_REFOCUS = { page: session.page, sel: '[data-act="pv-reason-open"]' };
  }
}

// After the lines are drawn (drawPageVerdicts): a focus a session's end owes goes to its line's control
// (PENDING_REFOCUS).
let PENDING_REFOCUS: { page: number; sel: string } | null = null;

function refocusAfterLines() {
  const owed = PENDING_REFOCUS;
  if (!owed) return;
  PENDING_REFOCUS = null;
  const control = findMaybe(document, '#doc .pv[data-page="' + owed.page + '"] ' + owed.sel, HTMLElement);
  if (control) control.focus({ preventScroll: true });
}

// Once per document in this page's life, when its first lines are drawn: the drafts kept for pins that are gone are let
// go, one kept for a verdict that is not its line's current one of the person's becomes its page's draft (only that is
// marked there), and the others wait on their lines ('초안 있음') - none opens by itself: a popover restored on a page
// far from the reading one would open out of sight, said only to a screen reader. The status line says how many came
// back, with [보기], which brings the first one's line into view and puts the focus on its mark.
const RESTORED_DOCS: Set<string> = new Set();

function restoreKeptDrafts() {
  const doc = DOC || '';
  if (RESTORED_DOCS.has(doc) || !META) return;
  RESTORED_DOCS.add(doc);
  const drafts = readAllDrafts(),
    pre = doc + ':',
    kind = META.kind;
  let changed = false;
  const pages: Set<number> = new Set();
  for (const k of Object.keys(drafts)) {
    if (!k.startsWith(pre)) continue;
    const rest = k.slice(pre.length),
      x = parseDraft(drafts[k]);
    if (!x) continue;
    if (rest.startsWith('p')) {
      pages.add(Number(rest.slice(1)) || 0);
      continue;
    } // a page's draft waits on its line
    const pin = findReasonPin(Number(rest));
    if (!pin) {
      delete drafts[k];
      changed = true;
      continue;
    }
    const target = pageTargetOf(pin, kind);
    if (!target) continue;
    pages.add(target.page);
    const cur = currentLineVerdict(target.page);
    if (cur && cur.id === pin.id && canCancelVerdict(cur)) continue;
    // Not its line's current verdict of the person's (a newer one came, or it was handled): no line marks it - the
    // page's draft does, so what this says is true.
    const pageKey = pre + 'p' + target.page,
      pageDraft = parseDraft(drafts[pageKey]);
    delete drafts[k];
    changed = true;
    // It becomes a part moved off its verdict, with that verdict's lost writes: one may have landed, so after a reload
    // the page's draft, opened on the newer verdict, never writes a reason already on the earlier one.
    const moved = draftMovedOff(k, x);
    if (!moved.text.trim()) continue;
    const joined = joinDrafts(pageDraft, moved);
    drafts[pageKey] = {
      ...x,
      text: joined.text,
      base: '',
      rev: -1,
      mode: 'add',
      folded: true,
      tried: [],
      from: joined.from,
    };
  }
  if (changed) saveAllDrafts(drafts);
  const shown = [...pages].filter((page) => page > 0).sort((left, right) => left - right);
  if (!shown.length) return;
  const first = shown[0];
  lineNote(
    translateTemplate('저장 안 된 이유 초안 {n}건 · 줄의 [초안 있음]이 엽니다 — {target}', {
      n: shown.length,
      target: pageTargetShort(first),
    }),
    NOTICE_KIND.INFO,
    { label: '보기', fn: () => showDraftLine(first) },
    { literal: true, source: 'reason-restore' },
  );
}

// A draft that changes a saved reason, opened again after its pin's note changed elsewhere: it knows the newer note at
// once
// - unless that note is its own lost write, landed (rebaseOnLanded).
function noteReasonConflict(session: ReasonSession, pin: Pin) {
  const note = String(pin.note || '');
  rebaseOnLanded(session, pin);
  session.conflict =
    replacesWholeNote(session) && note.trim() !== session.base.trim()
      ? { note, rev: typeof pin.rev === 'number' ? pin.rev : -1 }
      : null;
}

// Moving on: the popover closes and what was typed is written as Enter would, said in one line; nothing unsaved just
// closes. One still waiting for its verdict's number (opened by Enter while the save was out) is kept with that save
// (DETACHED_SESSIONS): its text waits as its page's draft, and the save, when it answers, writes it on the verdict it
// made (settleDetachedReason).
function leaveReason() {
  const session = REASON_SESSION;
  if (!session) return;
  closeReasonPopover(false);
  if (!session.id) {
    const slot = pageLineSlot(session.page, session.doc);
    if (session.text.trim() && SAVING_LINES.has(slot)) {
      disarmReasonEscape(session);
      keepDraft(session, true);
      DETACHED_SESSIONS.set(slot, session);
    }
    return;
  }
  if (hasUnsavedReason(session)) commitReason(session, session.text.trim(), true);
}

// The save on line `slot` answered - verdict pin id, or 0 when it failed: a popover moved away from while it was out is
// bound to that verdict and its text written there, on the document it was typed on, as moving on writes (said in one
// line); a failed save leaves the text as the page's draft ('초안 있음'), said. (Its text written meanwhile on a
// verdict it was moved off, takeWrittenText, leaves nothing to keep or write.)
function settleDetachedReason(slot: string, id: number, key: string) {
  const session = DETACHED_SESSIONS.get(slot);
  if (!session) return;
  DETACHED_SESSIONS.delete(slot);
  if (!session.text.trim()) return;
  if (!id) {
    lineNote(
      translateTemplate('판정 저장 실패 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}', {
        target: reasonTargetName(session),
      }),
      NOTICE_KIND.WARN,
      null,
      { literal: true },
    );
    return;
  }
  moveDraft(session.doc, 'p' + session.page, id);
  Object.assign(session, { id, key, base: '', mode: 'add', rev: -1, saveWhenBound: false, listed: false });
  commitReason(session, session.text.trim(), true);
}

// Opens the popover on page `page`'s line for its current verdict - the person's own open one ([이유 추가], Enter, its
// saved reason, its kept draft): with that draft (unfolded), else the page's draft (moved to this verdict), else the
// saved reason to change. Another popover moves on first. A page's draft with no verdict of the person's to take it
// says so.
function openReason(page: number, focus: boolean) {
  const cur = currentLineVerdict(page);
  if (viewerBlocked()) return;
  // A save out on this line: the reason is the new verdict's, whose number is coming; the list still has the one it
  // replaces.
  if (SAVING_LINES.has(pageLineSlot(page))) {
    openPendingReason(page);
    return;
  }
  if (DETACHED_SESSIONS.has(pageLineSlot(page))) {
    openPendingReason(page);
    return;
  } // its verdict's save is still out: that popover again
  if (!cur || !canCancelVerdict(cur)) {
    if (getDraft(DOC, 'p' + page))
      lineNote(
        translateTemplate('이유를 붙일 내 판정이 없습니다 · 판정을 누르면 이 초안이 그 판정으로 갑니다 — {target}', {
          target: pageTargetShort(page),
        }),
        NOTICE_KIND.INFO,
        null,
        { literal: true, life: NOTICE_LIFE.TIMER },
      );
    return;
  }
  if (!(REASON_SESSION && REASON_SESSION.id === cur.id && isReasonOpenOn(page))) {
    leaveReason();
    if (!getDraft(DOC, cur.id)) moveDraft(DOC, 'p' + page, cur.id); // a page's draft goes to the verdict it now has
    const note = String(cur.note || ''),
      draft = getDraft(DOC, cur.id),
      revision = typeof cur.rev === 'number' ? cur.rev : -1;
    const session = draft
      ? createReasonSession(
          page,
          cur.id,
          verdictOf(cur) || '',
          draft.text,
          draft.base,
          draft.rev >= 0 ? draft.rev : revision,
          draft.mode,
        )
      : createReasonSession(page, cur.id, verdictOf(cur) || '', note, note, revision);
    if (draft) {
      session.tried = draft.tried;
      session.via = draft.from;
    } // its writes whose answer was lost (one may have landed), and the pins it came from
    session.listed = true;
    noteReasonConflict(session, cur);
    setReasonSession(session);
    if (draft && draft.folded) keepDraft(session);
  }
  setKeyGuard(false);
  hideTip();
  verdictLineRenderer().drawPageVerdicts();
  if (focus) focusReasonField();
}

// Enter while page `page`'s save is still out (a fast typist: a key, then Enter at once): the Enter is the intent to
// write, so the popover opens now with the focus, bound to that pending verdict (id 0) - every key after it is text in
// the field, digits included, never a verdict key - and takes the verdict's number when the save answers
// (followSaveWithReason). A save that fails leaves the text as the page's draft (keepUnboundReason).
function openPendingReason(page: number) {
  const slot = pageLineSlot(page),
    key = SAVING_LINES.get(slot) || '';
  if (REASON_SESSION && isReasonOpenOn(page)) {
    focusReasonField();
    return;
  }
  leaveReason();
  const det = DETACHED_SESSIONS.get(slot);
  DETACHED_SESSIONS.delete(slot); // moved away from earlier: the same popover, with its Enter
  const draft = getDraft(DOC, 'p' + page),
    session = det
      ? Object.assign(det, { visit: captureVisit(), seen: readingPageWithLine() === page })
      : createReasonSession(page, 0, key, draft ? draft.text : '', '', -1, 'add');
  if (!det && draft) session.via = draft.from;
  setReasonSession(session);
  setKeyGuard(false);
  hideTip();
  verdictLineRenderer().drawPageVerdicts();
  focusReasonField();
}

// Page `page`'s save failed while a popover waited for its number: what was typed stays as the page's draft ('초안
// 있음'), said in one line, and the popover closes. As when a verdict is taken back while its reason is typed
// (keepLostReason): when the field had the focus its line's draft mark takes it and the keys pressed next are not
// verdict keys (KEY_GUARD) - a digit typed on would save a verdict; a focus elsewhere (the search, the composer) stays
// where it is.
function keepUnboundReason(page: number) {
  const session = REASON_SESSION;
  if (!session || session.id || session.page !== page || session.doc !== DOC) return;
  const pop = document.querySelector('#doc .pv-pop'),
    had = !!pop && pop.contains(document.activeElement);
  setReasonSession(null);
  if (session.text.trim()) {
    putDraft(session.doc, 'p' + page, session.text, '', -1, { mode: 'add', folded: true, from: session.via });
    lineNote(
      translateTemplate('판정 저장 실패 · 쓰던 이유는 이 쪽의 초안으로 남겼습니다 — {target}', {
        target: pageTargetShort(page),
      }),
      NOTICE_KIND.WARN,
      null,
      { literal: true },
    );
  }
  verdictLineRenderer().drawPageVerdicts();
  if (!had) return;
  setKeyGuard(true);
  if (!focusLine(page)) searchToPage();
}

// [그 위에 쓰기] in a popover that shows a newer note: the person has read it and puts their text over it - a replace,
// made from that note and written against its rev (also when it is empty: never an append that needs no rev).
function writeOverNewer() {
  const session = REASON_SESSION,
    field = findReasonField();
  if (!session || !session.conflict || !field || session.writing) return;
  session.base = session.conflict.note;
  session.rev = session.conflict.rev;
  session.mode = 'replace';
  session.conflict = null;
  keepDraft(session);
  if (!hasUnsavedReason(session)) {
    refillLine(session.page);
    return;
  }
  saveReason(field);
}

// Enter (or [저장]): the text written as the note and the popover closed. Empty is a skip - a saved reason stays - and
// the reason as it is saved has nothing to write. While the request is out the field waits (read-only, keeping the
// focus: disabled, it would drop the focus to nothing and the next digit would be a verdict key; the popover says '저장
// 중…'); a failure leaves the text in it for another Enter.
async function saveReason(field: HTMLTextAreaElement) {
  const session = REASON_SESSION;
  if (!session || session.writing || field.readOnly) return;
  session.text = field.value;
  const text = session.text.trim();
  if (!session.id) {
    if (text) {
      session.saveWhenBound = true;
      keepDraft(session);
      refillLine(session.page);
    }
    return;
  } // its verdict has no number yet: saved once it has
  if (!text || text === session.base.trim()) {
    dropDraft(session.doc, session.id || 'p' + session.page);
    closeReasonPopover(true);
    return;
  }
  if (session.conflict) {
    refillLine(session.page);
    focusReasonField();
    return;
  } // the newer note is on screen: [그 위에 쓰기] or [메모 보기] first
  const writing = commitReason(session, text, !!session.from);
  field.readOnly = true;
  refillLine(session.page);
  const ok = await writing;
  // closed meanwhile (moved on, the undo, another document): its one write had the text
  if (REASON_SESSION !== session) return;
  if (ok) {
    closeReasonPopover(true);
    return;
  }
  verdictLineRenderer().drawPageVerdicts();
  focusReasonField();
}

// Esc in the field, or [닫기] (how 'btn'): with nothing unsaved the popover closes. With text the first press lets the
// focus go to the PDF area - the keys then change the verdict, the draft following - and says that the next one drops
// it; the next one drops it (the kept draft too).
function escapeReason(how: string) {
  const session = REASON_SESSION;
  if (!session || (how === 'key' && session.writing)) return;
  if (!hasUnsavedReason(session)) {
    dropDraft(session.doc, session.id || 'p' + session.page);
    closeReasonPopover(true);
    return;
  }
  if (!session.escArm) {
    session.escArm = how;
    if (how === 'key') searchToPage();
    refillLine(session.page);
    announce(
      how === 'key'
        ? translate('Esc 한 번 더 누르면 이 이유를 버립니다')
        : translate('[닫기]를 한 번 더 누르면 이 이유를 버립니다'),
    );
    return;
  }
  dropDraft(session.doc, session.id || 'p' + session.page);
  closeReasonPopover(true);
  announce(translateTemplate('판정 #{id} 이유를 버렸습니다', { id: session.id }));
}

// [접기]: the popover folds away, nothing written - over the plot it hides what the reason is about. The draft stays
// kept, folded (a reload leaves it folded), and the line marks it '초안 있음', which opens it again and takes the
// focus. Moving on writes nothing: a folded draft waits for the person.
function foldReason() {
  const session = REASON_SESSION;
  if (!session || session.writing) return;
  if (hasUnsavedReason(session)) keepDraft(session, true);
  else dropDraft(session.doc, session.id);
  setReasonSession(null);
  verdictLineRenderer().drawPageVerdicts();
  const control = findMaybe(
    document,
    '#doc .pv[data-page="' + session.page + '"] [data-act="pv-reason-open"]',
    HTMLElement,
  );
  if (control) control.focus({ preventScroll: true });
  else focusLine(session.page);
  announce(translate('이유 초안을 접었습니다 — 줄의 [초안 있음]이 다시 엽니다'));
}

// [지우기]: the saved reason goes - the note emptied against the rev the popover read it at - and the status line
// offers [되돌리기], which writes it back. The popover and its draft stay until the server says it is done. A [지우기]
// whose answer was lost may have landed: the next one reads the note first, and an empty note is the clear done. A
// failure keeps both (the status line says it, with [다시 시도] when the server was not reached or failed - 5xx), and a
// note changed elsewhere meanwhile is not cleared (keepConflict).
async function clearReason() {
  const session = REASON_SESSION;
  if (!session || session.writing || viewerBlocked() || !replacesWholeNote(session)) return;
  if (session.conflict) {
    refillLine(session.page);
    return;
  }
  const old = session.base,
    target = reasonTargetName(session),
    word = verdictLabel(session.key),
    url = '/api/pins/' + session.id + '/edit',
    options = { id: session.id, intent: 'reason', silent: true, expect: [409] as const };
  const go = async () => {
    try {
      if (session.clearTried) {
        const pin = (await api('GET /api/pins/{id}', { id: session.id, what: '핀 읽기', silent: true })).data.pin;
        if (pin && !String(pin.note || '').trim()) return 'ok';
      }
      const { status, data } = await api('POST /api/pins/{id}/edit', {
        ...options,
        body: { note: '', base_rev: session.rev },
      });
      if (status !== 409) return 'ok';
      const answered = data && data.pin;
      if (!answered) return 'gone';
      if (!String(answered.note || '').trim()) return 'ok'; // empty already: the clear that lost its answer landed
      if (String(answered.note || '').trim() !== session.base.trim()) {
        keepConflict(session, session.text, answered);
        return 'conflict';
      }
      await api('POST /api/pins/{id}/edit', { ...options, expect: [], body: { note: '', base_rev: answered.rev } });
      return 'ok';
    } catch (error) {
      const x = isApiError(error) ? error : null,
        statusCode = x ? x.status : 0;
      if (!statusCode) session.clearTried = true;
      lineNote(
        translateTemplate('이유 지우기 실패 · {why} — {target}', {
          why: x ? (x.data && errText(x.data)) || 'HTTP ' + statusCode : translate('서버에 닿지 않습니다'),
          target,
        }),
        NOTICE_KIND.ERR,
        !statusCode || statusCode >= 500
          ? {
              label: '다시 시도',
              fn: () => {
                if (REASON_SESSION === session) clearReason();
              },
            }
          : null,
        { source: 'POST ' + url + ' reason', literal: true },
      );
      return 'fail';
    }
  };
  const clearing = go();
  session.writing = clearing.then((x) => x === 'ok');
  keepDraft(session);
  refillLine(session.page);
  const result = await clearing;
  session.writing = null;
  if (result === 'ok') {
    sourceOk('POST ' + url + ' reason');
    dropDraft(session.doc, session.id);
    if (REASON_SESSION === session) closeReasonPopover(true);
    lineNote(
      translateTemplate('판정 #{id} {word} 이유 지움 — {target}', { id: session.id, word, target }),
      NOTICE_KIND.OK,
      { label: '되돌리기', tip: TIP_TEXT.undo, wait: true, fn: () => undoClearReason(session.id, old) },
      { life: NOTICE_LIFE.TIMER, undo: true, literal: true },
    );
  } else if (REASON_SESSION === session) {
    verdictLineRenderer().drawPageVerdicts();
    focusReasonField();
  }
  if (session.doc === DOC) await loadPins();
}

// The undo of [지우기]: the reason written back, unless someone wrote a note meanwhile.
async function undoClearReason(id: number, old: string): Promise<boolean> {
  let ok = false;
  try {
    const pin = (await api('GET /api/pins/{id}', { id, what: '핀 읽기', where: NOTICE_HOST.LINE })).data.pin;
    if (pin && !String(pin.note || '').trim()) {
      await api('POST /api/pins/{id}/edit', {
        id,
        body: { note: old, base_rev: pin.rev },
        intent: 'reason',
        what: '이유 되돌리기',
        where: NOTICE_HOST.LINE,
      });
      ok = true;
    }
  } catch (error) {}
  await loadPins();
  return ok;
}

// Whether this tab holds a reason not written yet that the person can see: the open popover's, a kept draft for the
// current verdict of a line on screen or a page's draft (the line marks either), or one of another document. A
// withdrawn verdict's draft waits for its [되돌리기], and one for a verdict that is no longer current is not on any
// line: neither asks.
function hasUnsavedDrafts() {
  if (REASON_SESSION && hasUnsavedReason(REASON_SESSION)) return true;
  if (!META) return false;
  const drafts = readAllDrafts(),
    kind = META.kind;
  return Object.keys(drafts).some((key) => {
    const colon = key.lastIndexOf(':'),
      doc = key.slice(0, colon),
      rest = key.slice(colon + 1);
    if (doc !== (DOC || '')) return true;
    if (rest.startsWith('p')) return true;
    const id = Number(rest),
      pin = findReasonPin(id),
      target = pin && !WITHDRAWN_PINS.has(id) ? pageTargetOf(pin, kind) : null,
      cur = target ? currentLineVerdict(target.page) : null;
    return !!cur && cur.id === id;
  });
}

// Moving the panel to another page leaves an open reason on the page the reader has seen.
function leaveReasonOffPage(page: number) {
  if (REASON_SESSION && REASON_SESSION.seen && REASON_SESSION.page !== page) leaveReason();
}

export {
  clearReason,
  createReasonSession,
  currentLineVerdict,
  escapeReason,
  foldReason,
  hasUnsavedDrafts,
  keepUnboundReason,
  leaveReason,
  leaveReasonOffPage,
  noteReasonConflict,
  openPendingReason,
  openReason,
  refocusAfterLines,
  saveReason,
  settleDetachedReason,
  syncReasonSession,
  writeOverNewer,
};
