import { isMe } from '../app/state-people.ts';
import { translateTemplate } from '../platform/i18n.ts';
import type { ReasonTry } from './state-drafts.ts';
import type { ReasonSession } from './state-reason.ts';

// Whether a reason session writes the whole note against its rev (a change of a saved reason, or over a newer note
// seen).
function replacesWholeNote(session: ReasonSession) {
  return session.mode === 'replace';
}

// Where a lost write's text sits in `note` when the note is what the write made of the one it was sent against - its
// pre, its stamp, its text, its post - with nothing after but lines added under it since (a later note_append's
// '\n(추가 …', or an agent's '\r\n' one), or nothing at all when `exact` (no change came after it): the text's [start,
// end], else null.
function lostWriteAt(attempt: ReasonTry, note: string, exact?: boolean): number[] | null {
  if (!note.startsWith(attempt.pre)) return null;
  let start = attempt.pre.length;
  if (attempt.stamp) {
    const match = /^\(추가 \d{1,2}:\d{2}\) /.exec(note.slice(start));
    if (!match) return null;
    start += match[0].length;
  }
  const end = start + attempt.text.length;
  if (note.slice(start, end) !== attempt.text || note.slice(end, end + attempt.post.length) !== attempt.post)
    return null;
  const rest = note.slice(end + attempt.post.length);
  return !rest || (!exact && /^\r?\n/.test(rest)) ? [start, end] : null;
}

// Whether a lost write landed, from the pin as the server reads it now. Every reason write is sent against the rev it
// read (base_rev), so a write lands only as the change right after that rev, or never - a copy still on its way meets a
// 409 once anything else changed the pin. So: the pin's rev not past the write's rev - it has not landed (a write to
// try again, against that same rev: one of the two lands at most); past it, it landed when the note is what it made
// (lostWriteAt) and, when that was the only change since, the change was this person's (edited_by) and the note is
// exactly what it made, with no line under it - that change was it, or another one: someone's note that happens to read
// the same, or a fence that wrote the note back as it was (fenceLostWrites), is not this write. Text the note held
// already - someone's, or the person's own earlier line - is no sign of it: a reason repeated is a new one. (Two or
// more changes since leave the note to say it: someone writing the very same text under the same note in that window
// would read as this write.)
function hasLanded(attempt: ReasonTry, pin: Pin) {
  const revision = typeof pin.rev === 'number' ? pin.rev : 0,
    one = revision === attempt.rev + 1;
  return revision > attempt.rev && !!lostWriteAt(attempt, String(pin.note || ''), one) && (!one || isMe(pin.edited_by));
}

// The edit that writes text into the pin's note for a session, with what it makes of the note (kept as a lost write
// when its answer is lost) - or null when the pin holds it already; the pin is read from the server just before.
// Replace mode is the whole note against the rev it was read at (the session's rev) - never the pin's later one, which
// would write over a note changed meanwhile without the server's 409 - also over an empty note the person chose to
// write over. A new one is sent against the pin's rev, a note_append too (hasLanded). After a write whose answer was
// lost (the session's tried) the newest one that landed is the reason: its very text is saved already, and a corrected
// draft takes its place (a corrected reason, not a second one); lost writes that can no longer land (sent against an
// older rev, not landed) are let go. Otherwise the text goes into an empty note, or under the note someone wrote
// (note_append).
function reasonEditBody(
  session: ReasonSession,
  text: string,
  pin: Pin,
): { body: Record<string, unknown>; sent: ReasonTry | null } | null {
  const note = String(pin.note || ''),
    revision = typeof pin.rev === 'number' ? pin.rev : 0;
  if (replacesWholeNote(session)) {
    const at = session.rev >= 0 ? session.rev : revision;
    return note.trim() === text
      ? null
      : { body: { note: text, base_rev: at }, sent: { text, rev: at, pre: '', stamp: false, post: '' } };
  }
  const got = [...session.tried].reverse().find((attempt) => hasLanded(attempt, pin));
  session.tried = session.tried.filter((attempt) => attempt === got || attempt.rev >= revision);
  const at = got ? lostWriteAt(got, note) : null;
  if (got && at) {
    if (got.text === text) return null;
    const pre = note.slice(0, at[0]),
      post = note.slice(at[1]);
    return {
      body: { note: pre + text + post, base_rev: revision },
      sent: { text, rev: revision, pre, stamp: false, post },
    };
  }
  if (!note.trim())
    return { body: { note: text, base_rev: revision }, sent: { text, rev: revision, pre: '', stamp: false, post: '' } };
  return {
    body: { note_append: text, base_rev: revision },
    sent: { text, rev: revision, pre: note + '\n', stamp: true, post: '' },
  };
}

const NOTE_APPEND_LIMIT = 2000,
  NOTE_LIMIT = 4000; // the server's (pins/editing): a note_append, a whole note

// Why an edit body would be refused for its length - said instead of sending it, the draft kept - or ''.
function tooLongReason(body: Record<string, unknown>) {
  const append = body.note_append,
    note = body.note,
    format = (x: number) => x.toLocaleString('en-US');
  if (typeof append === 'string' && append.length > NOTE_APPEND_LIMIT)
    return translateTemplate('덧붙일 이유는 {max}자까지입니다(지금 {len}자)', {
      max: format(NOTE_APPEND_LIMIT),
      len: format(append.length),
    });
  if (typeof note === 'string' && note.length > NOTE_LIMIT)
    return translateTemplate('메모는 {max}자까지입니다(지금 {len}자)', {
      max: format(NOTE_LIMIT),
      len: format(note.length),
    });
  return '';
}

// A change of a saved reason whose write landed though its answer was lost - the pin's rev past the one it was sent
// against and its note exactly what it wrote (hasLanded): the note the session changes is that one now, at the pin's
// rev. The person's own text is never shown back as a note changed elsewhere ('지금 메모'), and the next Enter writes
// over it at once. Returns whether it did.
function rebaseOnLanded(session: ReasonSession, pin: Pin) {
  if (!replacesWholeNote(session) || !session.tried.length) return false;
  const note = String(pin.note || '');
  const got = [...session.tried]
    .reverse()
    .find((attempt) => note === attempt.pre + attempt.text + attempt.post && hasLanded(attempt, pin));
  if (!got) return false;
  session.base = note;
  session.rev = typeof pin.rev === 'number' ? pin.rev : session.rev;
  session.tried = [];
  session.conflict = null;
  return true;
}

export { hasLanded, reasonEditBody, rebaseOnLanded, replacesWholeNote, tooLongReason };
