import type { Visit } from '../app/state.ts';
import { DOC, currentVisit, OPEN_ALL, REVIEW_ALL, DONE_ALL } from '../app/state.ts';
import type { ReasonPart, ReasonTry } from './state-drafts.ts';
import { putDraft } from './state-drafts.ts';

// ---------------- The session
// sid: the popover's own number - its field stays the same element while its draft moves to another verdict, so the
// focus and an input method's composition stay with it. base: the reason the field opened on ('' for a new one). mode:
// 'replace' (it changes the saved reason, or puts its text over a newer note the person has seen: the whole note,
// against rev) or 'add' (a new reason: into an empty note, or under the note someone wrote, read fresh before writing).
// rev: the pin's rev when the replaced note was read - the change and [지우기] are written against it, so a note
// changed meanwhile elsewhere is never written over. conflict: that newer note and its rev, once a write found it (the
// popover shows it whole and offers [그 위에 쓰기], writeOverNewer). from: the verdict the draft moved from (0 when it
// did not), said in the popover. escArm: the first Esc (or [닫기]) with text was pressed - 'key' or 'btn' - and the
// next one drops the draft. saved: the text the session has written; tried: its writes that failed without an answer
// that says they did not land (they may have), each with the rev it was sent against and what it made of the note
// (ReasonTry, hasLanded); clearTried: a [지우기] whose answer was lost (the next one reads the note first). id 0: the
// popover was opened by Enter while its verdict's save was still out (openPendingReason) - the text waits for the
// verdict's number (followSaveWithReason binds it), and an Enter in it meanwhile saves once it has one (saveWhenBound).
// onto: the verdict its line changed to while its write was out - that write's outcome is said and settled by
// settleWriteOnto. via: the parts of its text moved off pins whose reason may still be written there (its draft's from,
// kept with it by keepDraft and placed again on every input, placeParts): a write of a part's text there takes that
// part out of this one (takeWrittenText). hist: the texts its field held since its text or parts were last set from
// elsewhere, with their parts (placeParts).
type ReasonSession = {
  sid: number;
  page: number;
  id: number;
  key: string;
  doc: string | null;
  visit: Visit;
  text: string;
  base: string;
  mode: string;
  rev: number;
  conflict: { note: string; rev: number } | null;
  from: number;
  via: ReasonPart[];
  seen: boolean;
  listed: boolean;
  writing: Promise<boolean> | null;
  saved: string | null;
  tried: ReasonTry[];
  clearTried: boolean;
  escArm: string;
  saveWhenBound?: boolean;
  onto?: number;
  hist?: ReasonHist;
};

// What a session's field held, for its undo and redo (placeParts).
type ReasonHist = {
  last: { text: string; via: ReasonPart[] };
  seen: Map<string, ReasonPart[]>;
  size: number;
  landed: { doc: string | null; id: number; word: string; text: string }[];
};

let REASON_SESSION: ReasonSession | null = null;

// Marks whether the reading line has been on a session's page (ReasonSession.seen), for another module that sees it
// (ADR-0042 D1).
function setReasonSeen(session: ReasonSession, seen: boolean) {
  session.seen = seen;
}

// The popovers moved away from (another page, another document, another popover) before their verdict's save answered,
// by line (pageLineSlot of the document they were typed on): each stays bound to that save, not to the screen.
const DETACHED_SESSIONS: Map<string, ReasonSession> = new Map();

// the verdict pin the last save on a page line made: its line offers the way to its reason wherever it is
let LAST_LINE_SAVE = 0;

let LAST_KEY_SAVE = 0; // ...when that save was a key's: its line says 'Enter 이유 쓰기'

// The pins this person withdrew (the save's undo, [판정 취소], a pressed word pressed again) while a reason for them
// may still be on its way: its failure, or its finding the pin gone, is no news to them - nothing is said. A failed
// withdrawal or a restore takes the pin out again.
const WITHDRAWN_PINS: Set<number> = new Set();

function isReasonOpenOn(page: number) {
  const session = REASON_SESSION;
  return !!session && session.page === page && session.doc === DOC && currentVisit(session.visit);
}

// The pin a reason session is for, from the lists, or undefined.
function findReasonPin(id: number) {
  return OPEN_ALL.concat(REVIEW_ALL, DONE_ALL).find((pin) => pin.id === id);
}

// Whether the session's text is something not yet written: not empty, not the reason it opened on, not what it wrote.
function hasUnsavedReason(session: ReasonSession) {
  const text = session.text.trim();
  return !!text && text !== session.base.trim() && text !== session.saved;
}

// After a focused reason field went from under the person (its verdict taken back elsewhere), the keys they go on
// typing are not verdict keys: one would save a verdict they never chose (and the text is in its page's draft). It
// lasts until they press something on purpose - a press of the pointer, Esc, or opening the popover again.
let KEY_GUARD = false;

// Sets KEY_GUARD, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setKeyGuard<Value extends typeof KEY_GUARD>(value: Value): Value {
  KEY_GUARD = value;
  return value;
}

// Sets REASON_SESSION, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setReasonSession<Value extends typeof REASON_SESSION>(value: Value): Value {
  REASON_SESSION = value;
  return value;
}

// Keeps a reason session's text as its pin's draft (open, not folded), with its lost writes and the parts it came from.
function keepDraft(session: ReasonSession, folded?: boolean) {
  putDraft(session.doc, session.id || 'p' + session.page, session.text, session.base, session.rev, {
    mode: session.mode,
    folded: !!folded,
    tried: session.tried,
    from: session.via,
  });
} // not bound yet: the page's

// Resuming input disarms the second Escape that would discard the draft.
function disarmReasonEscape(session: ReasonSession) {
  session.escArm = '';
}

// Only the last keyboard save offers Enter to open its reason.
function rememberReasonSave(id: number, byKey: boolean) {
  LAST_LINE_SAVE = id;
  LAST_KEY_SAVE = byKey ? id : 0;
}

export {
  DETACHED_SESSIONS,
  KEY_GUARD,
  LAST_KEY_SAVE,
  LAST_LINE_SAVE,
  REASON_SESSION,
  WITHDRAWN_PINS,
  findReasonPin,
  hasUnsavedReason,
  disarmReasonEscape,
  keepDraft,
  isReasonOpenOn,
  rememberReasonSave,
  setKeyGuard,
  setReasonSeen,
  setReasonSession,
};
export type { ReasonHist, ReasonSession };
