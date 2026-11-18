import { verdictOf } from '../app/rules-pins.ts';
import { DOC } from '../app/state.ts';
import { verdictLabel, viewerBlocked } from '../documents/state.ts';
import { loadPins, gotoPinRef } from '../pins/flow-list.ts';
import { api, isApiError } from '../platform/api.ts';
import { findMaybe, searchToPage } from '../platform/dom.ts';
import { translateTemplate, translate, errText } from '../platform/i18n.ts';
import { endNotice, lineNote, sourceOk, quietNote } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import type { ReasonTry, ReasonPart } from './state-drafts.ts';
import {
  readAllDrafts,
  reasonDraftKey,
  parseDraft,
  saveAllDrafts,
  getDraft,
  dropDraft,
  normalizeReason,
  cutWrittenDrafts,
  cutWrittenParts,
  draftsMovedOff,
  putDraft,
} from './state-drafts.ts';
import { verdictLineRenderer } from './state-line-renderer.ts';
import { hasLanded, rebaseOnLanded, replacesWholeNote, reasonEditBody, tooLongReason } from './state-reason-edit.ts';
import type { ReasonSession } from './state-reason.ts';
import { REASON_SESSION, DETACHED_SESSIONS, setReasonSession, setKeyGuard, WITHDRAWN_PINS } from './state-reason.ts';
import { currentVerdictOn } from './view-pins.ts';
import {
  refillLine,
  fillReasonField,
  reasonTargetName,
  focusLine,
  targetNameOn,
  closeReasonPopover,
} from './view-reason.ts';

// A pin's write lost its answer (`attempt`): every part moved off its key keeps it as evidence, stored and in a session
// - also in the texts a session's field may come back to (updateEvidence).
function addLostWrite(doc: string | null, id: number, attempt: ReasonTry) {
  const drafts = readAllDrafts(),
    key = reasonDraftKey(doc, id),
    add = (parts: ReasonPart[]) =>
      parts.map((part) => (part.k === key ? { ...part, tried: [...part.tried, attempt] } : part));
  let changed = false;
  for (const x of Object.keys(drafts)) {
    const draft = parseDraft(drafts[x]);
    if (draft && draft.from.some((part) => part.k === key)) {
      drafts[x] = { ...draft, from: add(draft.from) };
      changed = true;
    }
  }
  if (changed) saveAllDrafts(drafts);
  for (const session of liveSessions())
    if (session.id !== id || session.doc !== doc) updateEvidence(session, key, (tries) => [...tries, attempt]);
}

// ---------------- Writing
// The one write of a reason session: text as its pin's note (writeReason). While a write is out it is that write -
// Enter and then moving on, another save or another document before the answer start no second one - and text the
// session has written is not written again. A failed write may be tried again. Resolves with whether the reason is
// written; once it is, its kept draft goes (unless more was typed meanwhile), so does every other place the text waits
// to be written - a part moved off the pin's key, the pins it was moved off (takeWrittenText) - and its lost writes are
// settled. The write is listed while it is out (REASON_WRITES, with its session): a draft is not moved off the key it
// may still be written for (placeFailedCancelDraft, followSaveWithReason). A reason ends on one verdict, so before text
// moved off other pins is written here, whatever may still put it there is settled first: a write out from one of those
// pins, or from a copy moved off this one, answers first (waitForKinWrites), and the lost writes of those pins are read
// from the server (checkLostWrites) - what landed leaves this text (takeWrittenText), what may still land is fenced off
// (fenceLostWrites), and only what is left is written, nothing when nothing is. A pin that cannot be read or fenced
// leaves it unsure: nothing is written, the draft stays and the status line says the write failed, with [다시 시도]. So
// the reason never lands on both verdicts - also when the moved copy is opened and Enter pressed before the old
// verdict's [다시 시도] answers, when that answer was lost after it landed, or after a reload.
const REASON_WRITES: Map<string, { r: ReasonSession; w: Promise<boolean> }> = new Map();

// The sessions whose failure the status line offers [다시 시도] for (sayReasonFailed), with that message: a write
// elsewhere of their text takes it out of them and the message goes (takeWrittenText) - the [다시 시도] would write it
// a second time.
const RETRY_NOTICES: Map<ReasonSession, Notice> = new Map();

function commitReason(session: ReasonSession, text: string, said: boolean): Promise<boolean> {
  if (session.saved === text) return Promise.resolve(true);
  if (!session.writing) {
    const key = reasonDraftKey(session.doc, session.id),
      kin = waitForKinWrites(session);
    let sent = text;
    const go =
      kin || session.via.some((part) => part.tried.length)
        ? (kin || Promise.resolve())
            .then(() => checkLostWrites(session))
            .then((sure) => {
              sent = session.text.trim();
              if (!sent) return true;
              if (sure !== true) {
                sayReasonFailed(session, sent, sure);
                return false;
              } // whether it is, or will be, on a pin it came from is not known: kept, not written
              return writeReason(session, sent, said);
            })
        : writeReason(session, text, said);
    const writing = go.then((ok) => {
      session.writing = null;
      const outWrite = REASON_WRITES.get(key);
      if (outWrite && outWrite.w === writing) REASON_WRITES.delete(key);
      if (ok && sent) {
        session.saved = sent;
        session.tried = [];
        RETRY_NOTICES.delete(session);
        const draft = getDraft(session.doc, session.id);
        if (draft && draft.text.trim() === sent) dropDraft(session.doc, session.id);
        takeWrittenText(session.doc, session.id, session.key, sent, session);
      }
      return ok;
    });
    session.writing = writing;
    REASON_WRITES.set(key, { r: session, w: writing });
  }
  return session.writing;
}

// The writes out (REASON_WRITES) that may put a reason session's text on another verdict - those of the pins it was
// moved off (its via) and of the copies moved off its own pin -, all answered (failed ones too), or null when none is
// out.
function waitForKinWrites(session: ReasonSession): Promise<unknown> | null {
  const key = reasonDraftKey(session.doc, session.id);
  const writes = [...REASON_WRITES]
    .filter(
      ([x, outWrite]) =>
        outWrite.r !== session &&
        (session.via.some((part) => part.k === x) || outWrite.r.via.some((part) => part.k === key)),
    )
    .map(([, outWrite]) => outWrite.w.catch(() => false));
  return writes.length ? Promise.all(writes) : null;
}

// Before a session writes text moved off other pins: each of those pins whose writes lost their answer (its parts'
// tried) is read as the server has it now, and every such write is judged by the pin's rev (hasLanded). One that landed
// with a part's very text put it on that pin: the part leaves this session and every other copy, and its failure goes
// (takeWrittenText); one the pin's rev is past and that did not land never will, and is let go. One sent against the
// rev the pin still has may land yet - a request that lost its answer may still be on its way to the server -, so it is
// fenced off first (fenceLostWrites): then it never lands, or it landed first and is judged so, and only then is the
// copy written - the old request never lands after it. Resolves true when every pin is settled, else with what left one
// unknown - a read or a fence without an answer, a 5xx, a refusal (null: no answer at all): nothing is decided for it.
async function checkLostWrites(session: ReasonSession): Promise<true | ApiError | null> {
  let sure: true | ApiError | null = true;
  for (const k of new Set(session.via.filter((part) => part.tried.length).map((part) => part.k))) {
    const id = Number(k.slice(k.lastIndexOf(':') + 1));
    let fetched: Pin | null = null;
    try {
      fetched = (await api('GET /api/pins/{id}', { id, what: '핀 읽기', silent: true })).data.pin || null;
    } catch (error) {
      const x = isApiError(error) ? error : null;
      if (!x || !x.status || x.status >= 500) {
        sure = x;
        continue;
      }
    }
    for (let fenced = false; ; fenced = true) {
      const pin = fetched && !fetched.dropped_at ? fetched : null,
        revision = pin && typeof pin.rev === 'number' ? pin.rev : Infinity;
      for (;;) {
        const found = pin
          ? session.via.find(
              (part) =>
                part.k === k &&
                part.tried.some(
                  (attempt) =>
                    normalizeReason(attempt.text) === normalizeReason(session.text.slice(part.s, part.e)) &&
                    hasLanded(attempt, pin),
                ),
            )
          : null;
        if (!found || !pin) break;
        const landed = found.tried.find(
          (attempt) =>
            normalizeReason(attempt.text) === normalizeReason(session.text.slice(found.s, found.e)) &&
            hasLanded(attempt, pin),
        );
        if (!landed) break; // found holds such an attempt
        takeWrittenText(session.doc, id, verdictOf(pin) || '', landed.text, null);
        if (session.via.includes(found)) break;
      } // not taken out (cannot be): stop
      updateEvidence(session, k, (tries) => tries.filter((attempt) => attempt.rev >= revision));
      if (!pin || !session.via.some((part) => part.k === k && part.tried.length)) break; // none may land now
      if (fenced) {
        sure = null;
        break;
      } // a fence's 409 brings a newer pin, past them all: never here
      const fence = await fenceLostWrites(id, pin);
      if ('fenced' in fence) {
        updateEvidence(session, k, () => []);
        break;
      } // none landed, and none can now
      if ('unknown' in fence) {
        sure = fence.unknown;
        break;
      }
      fetched = fence.pin;
    }
  } // something changed the pin first - one of them landing, perhaps: judged again on the pin as it is
  return sure;
}

// Fences off what may still land on pin id - read just now as `pin` - of the reason writes that lost their answer:
// those sent against the rev it has. Its note is written back as it is, against that rev. Accepted, the pin's rev is
// past every such write, so its request is refused with a 409 when it arrives (an edit's base_rev,
// docs/handbook/api.md), and none had landed (the rev would not have been the one read). Refused with a 409, something
// changed the pin first - perhaps one of them, landing -, and the answer brings the pin as it is. A pin gone takes none
// of them. Anything else - no answer, a 5xx, another refusal - decides nothing; a fence whose answer was lost may land
// later, and is then no lost write's landing unless the note is exactly what that write made (hasLanded). Nothing of
// the note changes: the pin's edited_at and rev do.
async function fenceLostWrites(
  id: number,
  pin: Pin,
): Promise<{ fenced: true } | { pin: Pin | null } | { unknown: ApiError | null }> {
  try {
    const { status, data } = await api('POST /api/pins/{id}/edit', {
      id,
      intent: 'reason-fence',
      silent: true,
      expect: [409],
      body: { note: String(pin.note || ''), base_rev: typeof pin.rev === 'number' ? pin.rev : 0 },
    });
    if (status !== 409) return { fenced: true };
    const answered = data && data.pin;
    return answered ? { pin: answered } : { unknown: null };
  } catch (error) {
    const x = isApiError(error) ? error : null;
    return x && x.status === 404 ? { pin: null } : { unknown: x };
  }
}

// A session's evidence of pin `key`'s lost writes (ReasonPart.tried) made update(tried): in its text's parts and in
// those of the texts its field may come back to (hist, placeParts).
function updateEvidence(session: ReasonSession, key: string, update: (tries: ReasonTry[]) => ReasonTry[]) {
  const mapParts = (parts: ReasonPart[]) =>
    parts.map((part) => (part.k === key ? { ...part, tried: update(part.tried) } : part));
  session.via = mapParts(session.via);
  const history = session.hist;
  if (!history) return;
  history.last = { text: history.last.text, via: mapParts(history.last.via) };
  for (const [text, parts] of history.seen) history.seen.set(text, mapParts(parts));
}

// The sessions that may still write: the open popover, those moved away from while their save is out, those writing,
// and those whose failure offers [다시 시도].
function liveSessions() {
  return new Set(
    [
      REASON_SESSION,
      ...DETACHED_SESSIONS.values(),
      ...[...REASON_WRITES.values()].map((outWrite) => outWrite.r),
      ...RETRY_NOTICES.keys(),
    ].filter((session): session is ReasonSession => !!session),
  );
}

// Pin id (verdict word `word`) of document doc has text as its reason now - session `writer` wrote it, or (writer null)
// a write that lost its answer is found landed. A reason ends on one verdict, so the text leaves every other place it
// waits to be written: the parts moved off that pin with that text (cutWrittenParts) - in the drafts kept
// (cutWrittenDrafts) and in the sessions holding one (liveSessions), each keeping what else it holds: lines typed
// around it, another draft joined to it, the same sentence typed again -; and, the writer's text holding parts moved
// off other pins (its via), the sessions of those pins whose text is such a part. The sessions of pin id with that text
// have it saved. A session left with nothing has nothing to write: its [다시 시도] goes, and the open popover closes
// (closeTakenReason).
function takeWrittenText(doc: string | null, id: number, word: string, text: string, writer: ReasonSession | null) {
  const key = reasonDraftKey(doc, id),
    normalized = normalizeReason(text);
  cutWrittenDrafts(doc, id, text);
  for (const session of liveSessions()) {
    if (session === writer) continue;
    // an undo may bring such a part back (followLanded)
    if (session.hist) session.hist.landed.push({ doc, id, word, text });
    const cut = cutWrittenParts(session.text, session.via, key, text);
    if (cut) {
      session.text = cut.text.trim() ? cut.text : '';
      session.via = session.text ? cut.from : [];
      if (!session.text) emptySession(session);
      if (session === REASON_SESSION) closeTakenReason(session, doc, id, word, !!session.text);
      continue;
    }
    if (session === REASON_SESSION || !session.id || !session.text.trim()) continue;
    if (reasonDraftKey(session.doc, session.id) === key && normalizeReason(session.text) === normalized) {
      session.saved = session.text.trim();
      session.tried = [];
      emptySession(session);
    } // its own lost write, found landed
    else if (writer && cameFrom(writer, session)) emptySession(session);
  }
}

// A session left with nothing to write: its text goes and so does its [다시 시도].
function emptySession(session: ReasonSession) {
  session.text = '';
  session.via = [];
  const notice = RETRY_NOTICES.get(session);
  RETRY_NOTICES.delete(session);
  if (notice) endNotice(notice, true);
}

// Whether a session - a verdict's, with text - holds what the copy session came from: a part of the copy's text moved
// off the session's pin is the session's very text.
function cameFrom(copy: ReasonSession, session: ReasonSession) {
  const sessionKey = reasonDraftKey(session.doc, session.id),
    text = normalizeReason(session.text);
  return copy.via.some((part) => part.k === sessionKey && normalizeReason(copy.text.slice(part.s, part.e)) === text);
}

// The write of a copy session lost its answer (or met a 5xx): it may have landed on the copy's verdict, and its [다시
// 시도] or a later write there settles that (reasonEditBody). The sessions its copy came from have nothing left to
// write: their [다시 시도] goes - pressed, it would put the reason on their verdict too while the copy's request, the
// one that may still land, lands as well. The open popover is never such a session.
function handOnCopy(copy: ReasonSession) {
  for (const session of liveSessions())
    if (session !== copy && session !== REASON_SESSION && session.id && session.text.trim() && cameFrom(copy, session))
      emptySession(session);
}

// The open popover's session held a reason that pin id (verdict word `word`) of document doc has just been given, on a
// verdict its draft was moved off (takeWrittenText). With something left - lines typed around it, a draft joined to it
// - it stays with that, and the status line says the rest went. With nothing left it closes, and the status line says
// where the reason is, as when a write out at a verdict change lands ('이유는 이전 판정 #15 채택에 저장됨 · 지금 판정은
// #16 보류', saySavedOn): left open, its Enter or moving on would write the reason on this verdict as well. When the
// popover had the focus - typed in, or waiting on its Enter (the field disabled, the focus nowhere) - the line's reason
// control takes it and the keys pressed next are not verdict keys (KEY_GUARD): the person was typing text, or about to.
function closeTakenReason(session: ReasonSession, doc: string | null, id: number, word: string, part: boolean) {
  if (part) {
    refillLine(session.page);
    const line = findMaybe(document, '#doc .pv[data-page="' + session.page + '"]', HTMLElement);
    if (line) fillReasonField(line);
    lineNote(
      translateTemplate('이유 일부는 이전 판정 #{id} {word}에 저장됨 · 초안에는 나머지를 남겼습니다 — {target}', {
        id,
        word: verdictLabel(word, doc),
        target: reasonTargetName(session),
      }),
      NOTICE_KIND.INFO,
      null,
      { literal: true, life: NOTICE_LIFE.TIMER },
    );
    return;
  }
  const active = document.activeElement,
    pop = document.querySelector('#doc .pv-pop'),
    had = (!!pop && !!active && pop.contains(active)) || (!!session.writing && (!active || active === document.body));
  setReasonSession(null);
  verdictLineRenderer().drawPageVerdicts();
  if (had) {
    setKeyGuard(true);
    if (!focusLine(session.page)) searchToPage();
  }
  saySavedOn(doc, session.page, id, word);
}

// Says that pin id's reason (verdict word key) was saved, about page `page` of document doc - on an earlier verdict
// when the line's current verdict is another one now.
function saySavedOn(doc: string | null, page: number, id: number, key: string) {
  const target = targetNameOn(doc, page, id),
    word = verdictLabel(key, doc),
    now = currentVerdictOn(doc, page),
    nowKey = now ? verdictOf(now) : null;
  lineNote(
    now && nowKey && now.id !== id
      ? translateTemplate('이유는 이전 판정 #{id} {word}에 저장됨 · 지금 판정은 #{cur} {now} — {target}', {
          id,
          word,
          cur: now.id,
          now: verdictLabel(nowKey, doc),
          target,
        })
      : translateTemplate('이유 저장됨 · 판정 #{id} {word} — {target}', { id, word, target }),
    NOTICE_KIND.OK,
    null,
    { literal: true, life: NOTICE_LIFE.TIMER },
  );
}

// [다시 시도] on a failed reason: the session's draft as it is now (after a failed Enter the field stays open and may
// have been corrected) written as its one write. A field still open for it waits while it writes, and closes only when
// what was written is what it holds.
function retryReason(session: ReasonSession) {
  const text = session.text.trim();
  if (!text || session.writing) return;
  const writing = commitReason(session, text, true);
  if (REASON_SESSION === session) verdictLineRenderer().drawPageVerdicts();
  writing.then((ok) => {
    if (REASON_SESSION !== session) return;
    if (ok && session.text.trim() === session.saved) closeReasonPopover(false);
    else verdictLineRenderer().drawPageVerdicts();
  });
}

// Writes text as a reason session's pin's note. The pin is read from the server first (a list read a while ago may hold
// a note someone has emptied, which would add a stamped line to an empty note, or not hold one written since); a note
// someone wrote meanwhile is kept and a new reason is added to it (note_append), while a replace that finds the note
// changed since it was read is not written over theirs (keepConflict). A pin that is gone takes nothing. said: the
// status line says it was saved (moving on, a draft that moved to a new verdict), with the verdict it went to. Each 409
// - the pin changed since it was read - brings the pin as it is, and the edit is made again from it, up to
// CONFLICT_RETRIES times. A write whose answer is lost (or a 5xx) is kept with what it made of the note (the session's
// tried): the next write knows from the pin whether it landed. A failure is said by sayReasonFailed. Returns whether it
// was written.
const CONFLICT_RETRIES = 3;

async function writeReason(session: ReasonSession, text: string, said: boolean): Promise<boolean> {
  if (viewerBlocked()) return false;
  let pin;
  try {
    pin = (await api('GET /api/pins/{id}', { id: session.id, what: '핀 읽기', silent: true })).data.pin;
  } catch (error) {
    const x = isApiError(error) ? error : null;
    if (!x || !x.status || x.status >= 500) {
      sayReasonFailed(session, text, x);
      return false;
    }
    pin = undefined;
  }
  if (!pin || pin.dropped_at) {
    if (!WITHDRAWN_PINS.has(session.id))
      lineNote(translateTemplate('핀 #{id} 은 그사이 다른 곳에서 지워졌습니다', { id: session.id }), NOTICE_KIND.WARN);
    return false;
  }
  rebaseOnLanded(session, pin); // its own lost write, landed, is the note it changes now
  if (
    replacesWholeNote(session) &&
    String(pin.note || '').trim() !== session.base.trim() &&
    String(pin.note || '').trim() !== text
  ) {
    keepConflict(session, text, pin);
    return false;
  } // changed since it was read: never sent
  // silent: sayReasonFailed says a failure, with its target
  const options = { id: session.id, intent: 'reason', silent: true };
  let sent: ReasonTry | null = null; // the write out now, while its answer is awaited
  try {
    for (let round = 1; ; round++) {
      const edit = reasonEditBody(session, text, pin);
      if (!edit) break;
      const long = tooLongReason(edit.body);
      if (long) {
        sayReasonFailed(session, text, null, long);
        return false;
      }
      sent = edit.sent;
      const { status, data } = await api('POST /api/pins/{id}/edit', {
        ...options,
        body: edit.body,
        expect: round < CONFLICT_RETRIES ? [409] : [],
      });
      sent = null;
      if (status !== 409) break;
      const answered = data && data.pin; // someone changed the pin meanwhile: their note stays
      if (!answered) {
        sayReasonFailed(session, text, null, translate('그사이 다른 곳에서 메모가 바뀌었습니다'));
        return false;
      }
      if (replacesWholeNote(session)) {
        rebaseOnLanded(session, answered);
        if (String(answered.note || '').trim() !== session.base.trim()) {
          keepConflict(session, text, answered);
          return false;
        }
        session.rev = typeof answered.rev === 'number' ? answered.rev : session.rev;
      } // only something else changed (a claim, the assignee): the note is the one it was read at
      pin = answered;
    }
  } catch (error) {
    const x = isApiError(error) ? error : null;
    if (sent && (!x || !x.status || x.status >= 500)) {
      session.tried.push(sent);
      addLostWrite(session.doc, session.id, sent);
      handOnCopy(session);
    } // it may have landed - so may the copies moved off it know, and what it was copied from lets it be
    sayReasonFailed(session, text, x);
    return false;
  }
  session.conflict = null;
  // a failure this write answers goes (also when nothing had to be sent)
  sourceOk('POST /api/pins/' + session.id + '/edit reason');
  if (session.onto) {
    /* its line's verdict changed meanwhile: settleWriteOnto says where it is */
  } else if (said)
    lineNote(
      translateTemplate('이유 저장됨 · 판정 #{id} {word} — {target}', {
        id: session.id,
        word: verdictLabel(session.key, session.doc),
        target: reasonTargetName(session),
      }),
      NOTICE_KIND.OK,
      null,
      { life: NOTICE_LIFE.TIMER, literal: true },
    ); // result first: the folded line shows it
  else quietNote(translateTemplate('판정 #{id} 이유를 저장했습니다', { id: session.id }));
  if (session.doc === DOC) loadPins().catch(() => {});
  return true;
}

// A reason that could not be written, said on the status line result first ('이유 저장 실패 · 서버에 닿지 않습니다 —
// PL16') in place of api()'s line, keyed by the request as api() keys it (a later answer from it clears it). The draft
// is kept whatever failed (putDraft, with its lost writes) and the line marks it - or the copy moved off the pin's key
// meanwhile is (draftsMovedOff); unless the server refused it (a 4xx would refuse again) or it is too long (why: said
// before sending) the message offers [다시 시도], which writes the session's draft (retryReason). Stays until [x] or
// its action (STICKY), or until a write elsewhere puts its text on another verdict (RETRY_NOTICES, takeWrittenText). (A
// write without an answer is remembered by writeReason, in the session's tried: it may have landed.) The reason for a
// pin this person has withdrawn meanwhile goes quietly (WITHDRAWN_PINS).
function sayReasonFailed(session: ReasonSession, text: string, error: ApiError | null, why0?: string) {
  const statusCode = error && typeof error.status === 'number' ? error.status : 0,
    again = !why0 && (!statusCode || statusCode >= 500);
  if (!draftsMovedOff(session.doc, session.id).length)
    putDraft(session.doc, session.id, session.text.trim() ? session.text : text, session.base, session.rev, {
      mode: session.mode,
      tried: session.tried,
      from: session.via,
    }); // moved off meanwhile: that copy is the draft
  // withdrawn, or its line's verdict changed meanwhile (settleWriteOnto decides)
  if (WITHDRAWN_PINS.has(session.id) || session.onto) return;
  const why =
    why0 ||
    (statusCode
      ? (error && error.data && errText(error.data)) || 'HTTP ' + statusCode
      : translate('서버에 닿지 않습니다'));
  const notice = lineNote(
    translateTemplate('이유 저장 실패 · {why} — {target}', { why, target: reasonTargetName(session) }),
    NOTICE_KIND.ERR,
    again ? { label: '다시 시도', fn: () => retryReason(session) } : null,
    { source: 'POST /api/pins/' + session.id + '/edit reason', literal: true },
  );
  if (again && notice) RETRY_NOTICES.set(session, notice);
  else RETRY_NOTICES.delete(session);
  if (REASON_SESSION !== session && session.doc === DOC) verdictLineRenderer().drawPageVerdicts();
} // the line marks the draft it keeps

// A replace found the note changed elsewhere since it was read (the newer pin): nothing is written over it. The draft
// is kept, the popover - when open - shows the newer note whole and offers [그 위에 쓰기] (writeOverNewer); every
// further 409 shows the note it found. The status line says so, result first, with [메모 보기] (the pin's card), and
// the line is read again so it shows the newer note too.
function keepConflict(session: ReasonSession, text: string, newer: Pin) {
  session.conflict = { note: String(newer.note || ''), rev: typeof newer.rev === 'number' ? newer.rev : -1 };
  if (!draftsMovedOff(session.doc, session.id).length)
    putDraft(session.doc, session.id, session.text.trim() ? session.text : text, session.base, session.rev, {
      mode: session.mode,
      tried: session.tried,
      from: session.via,
    });
  if (!session.onto)
    lineNote(
      translateTemplate('이유 저장 안 함 · 그사이 다른 곳에서 메모가 바뀌었습니다 — {target}', {
        target: reasonTargetName(session),
      }),
      NOTICE_KIND.WARN,
      { label: '메모 보기', fn: () => gotoPinRef(session.id) },
      { source: 'POST /api/pins/' + session.id + '/edit reason', literal: true },
    );
  if (session.doc === DOC) {
    if (REASON_SESSION === session) refillLine(session.page);
    loadPins().catch(() => {});
  }
}

// After an input, a session's text holds a part whose very text landed on the pin it was moved off while the part was
// not in the text (an edit inside it had let it go, and an undo brought it back, placeParts): the part leaves now, as
// it would have then (takeWrittenText) - with something left the popover keeps that and says the rest went, with
// nothing left it closes and says where the reason is (closeTakenReason). Left in, Enter would write it on this verdict
// as well. Never while an input method composes (its composition passing through that text would close the popover
// under it): at its end, on the text it committed.
function followLanded(session: ReasonSession) {
  const history = session.hist;
  if (!history || !history.landed.length) return;
  for (const landedWrite of history.landed) {
    const cut = cutWrittenParts(
      session.text,
      session.via,
      reasonDraftKey(landedWrite.doc, landedWrite.id),
      landedWrite.text,
    );
    if (!cut) continue;
    session.text = cut.text.trim() ? cut.text : '';
    session.via = session.text ? cut.from : [];
    if (!session.text) emptySession(session);
    if (session === REASON_SESSION)
      closeTakenReason(session, landedWrite.doc, landedWrite.id, landedWrite.word, !!session.text);
    return;
  }
}

export { REASON_WRITES, RETRY_NOTICES, commitReason, followLanded, keepConflict, saySavedOn, takeWrittenText };
