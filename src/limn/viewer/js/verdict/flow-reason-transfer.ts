import { verdictOf } from '../app/rules-pins.ts';
import { DOC, currentVisit, META } from '../app/state.ts';
import { loadPins } from '../pins/flow-list.ts';
import { api, isApiError } from '../platform/api.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { lineNote, sourceOk } from '../platform/notices.ts';
import { NOTICE_KIND } from '../platform/tables.ts';
import { REASON_WRITES, saySavedOn, RETRY_NOTICES, takeWrittenText } from './flow-reason-write.ts';
import { saveReason, leaveReason, currentLineVerdict, createReasonSession, noteReasonConflict } from './flow-reason.ts';
import {
  movedPart,
  reasonDraftKey,
  dropDraft,
  putDraft,
  moveDraft,
  ownText,
  getDraft,
  draftMovedOff,
  joinDrafts,
} from './state-drafts.ts';
import { verdictLineRenderer } from './state-line-renderer.ts';
import { pageLineSlot, SAVING_LINES, READING_LINE_PAGE } from './state-lines.ts';
import { hasLanded } from './state-reason-edit.ts';
import type { ReasonSession } from './state-reason.ts';
import {
  REASON_SESSION,
  isReasonOpenOn,
  hasUnsavedReason,
  DETACHED_SESSIONS,
  rememberReasonSave,
  setReasonSession,
  findReasonPin,
} from './state-reason.ts';
import { IS_BESIDE_PAGES } from './view-panel.ts';
import { currentVerdictOn, pageTargetOf } from './view-pins.ts';
import { findReasonField } from './view-reason-field.ts';
import { targetNameOn, showDraftLine } from './view-reason.ts';

// A save on page `page`'s line made verdict pin id (savePageVerdict) in place of verdict pin previousId (the line's
// current one before it, 0 for none). A popover open on that line follows it: its draft moves to the new verdict -
// never written on the one it replaced - and says where it goes now, keeping its field, focus and composition; an empty
// one stays open for the new verdict. A draft kept for the previous verdict without a popover (a failed write, a folded
// one) or for the page (a verdict taken back elsewhere) moves too, and the line marks it on the new verdict. A popover
// elsewhere, or one whose write is out, moves on. No save opens one: after a click the line offers [이유 추가]; after a
// key, 'Enter 이유 쓰기'. A change of a saved reason moves only the person's own text: the lines others added under it
// ('(추가 HH:MM) …', as the note held them) stay on the verdict they were written on and are not copied as the person's
// reason (ownReasonText); a change that leaves nothing of the person's own is no draft, and an unchanged one moves
// nothing. A reason ends on one verdict: while the previous verdict's reason write is out (REASON_WRITES) its draft
// does not move - that write settles first (settleWriteOnto: written, or found landed, it stays the previous verdict's
// and the status line says so; not landed, the draft moves to the new verdict and its [다시 시도] goes). Moved at once,
// a write that lands or a [다시 시도] afterwards would put the reason on both verdicts.
function followSaveWithReason(page: number, id: number, key: string, byKey: boolean, previousId: number) {
  const session = REASON_SESSION;
  rememberReasonSave(id, byKey);
  if (session && isReasonOpenOn(page) && !session.writing) {
    const own = ownReasonText(session),
      dirty = hasUnsavedReason(session) && !!own.trim(),
      from = session.id;
    // The draft it moves is a part moved off the verdict it leaves, with that verdict's lost writes, as moveDraft makes
    // it - another session's write of it may still land there (moving on, then the draft opened again on that verdict
    // and moved here) - and keeps the parts it came with (not when others' lines were left out of it: their places
    // changed).
    if (dirty) {
      const fromKey = from || 'p' + page;
      session.via = [
        ...(own === session.text ? session.via : []),
        ...(from ? [movedPart(reasonDraftKey(session.doc, from), { text: own, tried: session.tried })] : []),
      ];
      session.text = own;
      dropDraft(session.doc, fromKey);
      putDraft(DOC, id, own, '', -1, { mode: 'add', from: session.via });
    } else if (from) {
      session.text = '';
      session.via = [];
    } // an unbound popover keeps what is typed
    Object.assign(session, {
      id,
      key,
      base: '',
      mode: 'add',
      rev: -1,
      conflict: null,
      from: dirty ? from : 0,
      saved: null,
      tried: [],
      clearTried: false,
      listed: false,
      escArm: '',
    });
    if (session.saveWhenBound) {
      session.saveWhenBound = false;
      const field = findReasonField();
      if (field) setTimeout(() => saveReason(field), 0);
    } // its Enter came before the number
    return;
  }
  // its popover was moved away from: settleDetachedReason writes it; the open one stays
  if (DETACHED_SESSIONS.has(pageLineSlot(page))) return;
  const outWrite = previousId ? REASON_WRITES.get(reasonDraftKey(DOC, previousId)) : null;
  if (outWrite) {
    const writer = outWrite.r;
    writer.onto = id;
    outWrite.w.then((ok) => settleWriteOnto(writer, ok, page));
  } // its write settles first
  else if (!(previousId && moveDraft(DOC, previousId, id))) moveDraft(DOC, 'p' + page, id);
  leaveReason();
}

// The text of a reason session that is the person's own: the field's text, less - when it changes a saved reason - the
// stamped lines others added under it ('(추가 HH:MM) …') as the saved note held them. (A new reason's text is the
// field's, as typed.)
function ownReasonText(session: ReasonSession) {
  return ownText(session.mode, session.text, session.base);
}

// The write of a reason session, out while its line's verdict changed to its `onto` (followSaveWithReason), settled -
// ok: it was written. Its reason ends on one verdict. Written - or, its answer lost or a 5xx, found landed when the pin
// is read again (hasLanded) - it stays on the session's verdict, now an earlier one, and the status line says so
// ('이유는 이전 판정 #15 채택에 저장됨 · 지금 판정은 #16 보류'). Not landed (also refused, or the pin gone), its draft
// moves to the new verdict - or to the page's draft, when that verdict is no longer the line's or already has a draft
// or a popover - its failure and that [다시 시도] go, and the status line says where it went with [보기] - remembering
// the pins the draft came from before (from), as every move does, and this verdict while its write may land yet. A read
// that fails decides nothing: the status line says so with [다시 시도], which reads again. (writeReason and
// sayReasonFailed say nothing of such a write themselves.)
async function settleWriteOnto(session: ReasonSession, ok: boolean, page: number) {
  const to = session.onto,
    doc = session.doc,
    src = 'POST /api/pins/' + session.id + '/edit reason';
  if (!to) return;
  const target = targetNameOn(doc, page, session.id),
    saved = () => {
      session.onto = 0;
      saySavedOn(doc, page, session.id, session.key);
    };
  if (ok) {
    if (session.text.trim()) saved();
    else session.onto = 0;
    return;
  } // nothing of it was left to write: a pin it came from had it (commitReason)
  let pin: Pin | null | undefined = undefined;
  try {
    pin = (await api('GET /api/pins/{id}', { id: session.id, what: '핀 읽기', silent: true })).data.pin;
  } catch (error) {
    const x = isApiError(error) ? error : null;
    if (!x || !x.status || x.status >= 500) {
      lineNote(
        translateTemplate('이유 저장 실패 · {why} — {target}', { why: translate('서버에 닿지 않습니다'), target }),
        NOTICE_KIND.ERR,
        { label: '다시 시도', fn: () => settleWriteOnto(session, false, page) },
        { source: src, literal: true },
      );
      return;
    }
    pin = null;
  }
  const live = pin && !pin.dropped_at ? pin : null,
    got = live ? [...session.tried].reverse().find((attempt) => hasLanded(attempt, live)) : null;
  RETRY_NOTICES.delete(session); // its [다시 시도] goes either way (sourceOk)
  if (got) {
    session.saved = got.text;
    session.tried = [];
    dropDraft(doc, session.id);
    sourceOk(src);
    takeWrittenText(doc, session.id, session.key, got.text, session);
    saved();
    if (doc === DOC) loadPins().catch(() => {});
    return;
  }
  // Not landed - yet: one sent against the rev the pin still has may still be on its way. The draft keeps it as a part
  // moved off this verdict with that evidence, so a write of it on the new verdict fences it off first
  // (checkLostWrites).
  const can =
    pin && !pin.dropped_at
      ? session.tried.filter((attempt) => attempt.rev >= (typeof pin.rev === 'number' ? pin.rev : 0))
      : [];
  session.onto = 0;
  session.tried = [];
  sourceOk(src);
  const x = getDraft(doc, session.id) || {
    text: session.text,
    base: session.base,
    mode: session.mode,
    tried: [],
    from: session.via,
  };
  const moved = draftMovedOff(can.length ? reasonDraftKey(doc, session.id) : '', { ...x, tried: can }),
    text = moved.text,
    via = moved.from;
  dropDraft(doc, session.id);
  if (!text.trim()) return;
  const open = !!REASON_SESSION && REASON_SESSION.doc === doc && REASON_SESSION.page === page,
    cur = currentVerdictOn(doc, page); // it moves with the pins it came from
  if (cur && cur.id === to && !open && !getDraft(doc, to))
    putDraft(doc, to, text, '', -1, { mode: 'add', folded: true, from: via });
  else {
    const joined = joinDrafts(getDraft(doc, 'p' + page), { text, from: via });
    putDraft(doc, 'p' + page, joined.text, '', -1, { mode: 'add', folded: true, from: joined.from });
  }
  lineNote(
    translateTemplate(
      '판정 #{id} 이유는 저장되지 않아 지금 판정의 초안으로 옮겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}',
      {
        id: session.id,
        target,
      },
    ),
    NOTICE_KIND.WARN,
    doc === DOC ? { label: '보기', fn: () => showDraftLine(page) } : null,
    { literal: true, source: 'reason-onto' },
  );
  if (doc === DOC) verdictLineRenderer().drawPageVerdicts();
}

// A take-back of verdict pin id about page `page` of document doc failed (cancelVerdictPin): the verdict is back. Its
// reason popover left with it (kept: that session, or null) and comes back with its text while nothing took its place:
// no other popover open (a newer session: another page's, the earlier verdict's the line showed meanwhile, a new
// verdict's, also one still waiting for its verdict's number), the same document and visit, and the verdict is its
// line's current one again (a save out on the line then moves it to the new verdict, followSaveWithReason - unless its
// own write is out too). Otherwise what was typed - kept as the verdict's draft when it left (cancelVerdictPin) - is
// never let go without a word (placeFailedCancelDraft).
function bringBackReason(id: number, page: number, doc: string | null, kept: ReasonSession | null) {
  const cur = currentVerdictOn(doc, page),
    back = !!cur && cur.id === id;
  // opened again meanwhile (its line's '초안 있음' came back with it)
  if (REASON_SESSION && REASON_SESSION.id === id) return;
  if (
    kept &&
    back &&
    !REASON_SESSION &&
    doc === DOC &&
    currentVisit(kept.visit) &&
    !(kept.writing && SAVING_LINES.has(pageLineSlot(page, doc)))
  ) {
    setReasonSession(kept);
    verdictLineRenderer().drawPageVerdicts();
    return;
  }
  placeFailedCancelDraft(id, page, doc, !!kept);
}

// Where the draft of verdict pin id, back but perhaps no longer current (its take-back failed, or a [되돌리기] restored
// it under a newer verdict), waits - decided once nothing can still change it: a write of its reason that is out
// settles first (REASON_WRITES: written, there is nothing left to keep; failed, it is the draft again), and a save out
// on its line answers first (FAILED_CANCEL_WAITS, settleFailedCancelDraft: that save decides whether the verdict is
// still its line's current one). When the verdict is its line's current one it waits there as its draft; when a newer
// verdict was saved on the line it would wait on no line (a line marks its current verdict's draft only), so it becomes
// the page's draft, which goes to the verdict it is opened on (openReason; joined under a page's draft waiting there
// already), and remembers that all of it was moved off that verdict, with the verdict's lost writes, and the parts it
// came with (from): a [다시 시도] of the old write that lands later takes it away, also after it moved on again
// (takeWrittenText), and a write of it elsewhere first settles those lost writes (checkLostWrites). Either way the line
// marks it '초안 있음' and the status line says so with [보기] (its line in view, the focus on the mark, showDraftLine)
// - a warning after the take-back's own failure, which stands first with its [다시 시도]. shown: a popover was
// displaced. A draft kept for the verdict without one (folded, or a failed write) moves the same way and is said too;
// one that stays on its verdict's line, where it was before, is not.
const FAILED_CANCEL_WAITS: Map<string, { id: number; page: number; doc: string | null; shown: boolean }> = new Map();

function placeFailedCancelDraft(id: number, page: number, doc: string | null, shown: boolean) {
  const outWrite = REASON_WRITES.get(reasonDraftKey(doc, id));
  if (outWrite) {
    outWrite.w.then(() => placeFailedCancelDraft(id, page, doc, shown));
    return;
  }
  const slot = pageLineSlot(page, doc);
  if (SAVING_LINES.has(slot)) {
    const waiting = FAILED_CANCEL_WAITS.get(slot);
    FAILED_CANCEL_WAITS.set(slot, { id, page, doc, shown: shown || (!!waiting && waiting.id === id && waiting.shown) });
    return;
  }
  if (REASON_SESSION && REASON_SESSION.id === id) return;
  const cur = currentVerdictOn(doc, page),
    back = !!cur && cur.id === id,
    draft = getDraft(doc, id);
  if (!draft || (back && !shown)) return;
  if (!back) {
    const moved = draftMovedOff(reasonDraftKey(doc, id), draft);
    dropDraft(doc, id);
    if (!moved.text.trim()) return;
    const joined = joinDrafts(getDraft(doc, 'p' + page), moved);
    putDraft(doc, 'p' + page, joined.text, '', -1, { mode: 'add', folded: true, from: joined.from });
  }
  const target = targetNameOn(doc, page, id);
  lineNote(
    back
      ? translateTemplate('판정 #{id} 이유는 초안으로 남겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}', {
          id,
          target,
        })
      : translateTemplate('판정 #{id} 이유는 이 쪽의 초안으로 남겼습니다 · 줄의 [초안 있음]이 엽니다 — {target}', {
          id,
          target,
        }),
    NOTICE_KIND.WARN,
    doc === DOC ? { label: '보기', fn: () => showDraftLine(page) } : null,
    { literal: true, source: 'reason-uncancel' },
  );
  if (doc === DOC) verdictLineRenderer().drawPageVerdicts();
}

// The save on line `slot` answered (savePageVerdict, after it bound or kept a popover waiting for it): a failed
// take-back's draft that waited for it is placed now.
function settleFailedCancelDraft(slot: string) {
  const waiting = FAILED_CANCEL_WAITS.get(slot);
  if (!waiting) return;
  FAILED_CANCEL_WAITS.delete(slot);
  placeFailedCancelDraft(waiting.id, waiting.page, waiting.doc, waiting.shown);
}

// [되돌리기] brought verdict pin id back (a cancel's, the save chip's): its kept draft opens again on its line, without
// the focus - only while it is that line's current verdict (a newer verdict of someone else's keeps the line;
// afterVerdictRestore announces it).
function reviveReason(id: number) {
  const draft = getDraft(DOC, id),
    pin = findReasonPin(id);
  if (!draft || !pin || (REASON_SESSION && REASON_SESSION.id === id)) return;
  const target = pageTargetOf(pin, META ? META.kind : undefined);
  if (!target) return;
  const cur = currentLineVerdict(target.page);
  if (!cur || cur.id !== id) return;
  // A reason being written on another page stays as it is, and where the popover cannot show (the panel beside the
  // pages shows the reading page alone) none opens: the draft stays this verdict's, marked on its line or summary.
  // Opened, it would write the other page's half text and take its field, and its own session would write on the next
  // verdict saved anywhere.
  if (
    (REASON_SESSION && REASON_SESSION.page !== target.page) ||
    (IS_BESIDE_PAGES && target.page !== READING_LINE_PAGE)
  ) {
    verdictLineRenderer().drawPageVerdicts();
    return;
  }
  leaveReason();
  const session = createReasonSession(
    target.page,
    id,
    verdictOf(pin) || '',
    draft.text,
    draft.base,
    draft.rev,
    draft.mode,
  );
  session.tried = draft.tried;
  session.via = draft.from;
  session.listed = true;
  noteReasonConflict(session, pin);
  setReasonSession(session);
  verdictLineRenderer().drawPageVerdicts();
}

export { bringBackReason, followSaveWithReason, placeFailedCancelDraft, reviveReason, settleFailedCancelDraft };
