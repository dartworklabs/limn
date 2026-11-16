// -------------------------------------------- A verdict's reason (docs/handbook/viewer.md §판정 핀 — 판정과 함께 이유)
// After a save on a page verdict line a person may say why in a short text that becomes the pin's note. It is written
// in a small popover over the line (.pv-pop: inside the line and laid above it, so it never pushes the page down or
// makes the floating line taller). No save opens it by itself: the line offers [이유 추가] after a click and, while the
// keys act on the line, 'Enter 이유 쓰기' - Enter opens it with the focus. Once open, every character typed in it is
// text, digits too (a data plot's reason often starts with one: '12월 값이 튐'); before it opens the digits are the
// line's verdict keys. The verdict's saved reason (a check and its first line, a pencil) opens it again to change it or
// clear it ([지우기]). One popover at a time: the session (REASON_SESSION) belongs to its pin, document and visit and
// keeps what is typed. A draft is never lost without a word:
// - it is kept per pin in this tab (sessionStorage, getDraft and putDraft) and a reload brings it back; leaving the
//   page with one asks first (beforeunload);
// - with text, Esc takes two presses - the first lets the focus go (the keys then change the verdict) and says what the
//   second does, which drops it; [접기] folds it away behind the line's '초안 있음' (and it stays folded after a
//   reload);
// - changing the verdict while it is being typed moves it to the new verdict (followSaveWithReason);
// - [되돌리기] of a cancel or of the save chip brings it back with its verdict (reviveReason);
// - a verdict taken back elsewhere while its reason is being typed leaves the text as its page's draft, said in one
//   line, and the keys typed after the field went are not verdict keys (isKeyGuarded);
// - a write that fails - unreachable, refused, too long, a note changed elsewhere - keeps it, and the line marks it
//   '초안 있음'.
// Moving on - the reading page leaving the popover's page after it was there, another save on another page, another
// document - closes it and writes what was typed, said in one line; a folded draft waits for the person.
import {
  DOC,
  DONE_ALL,
  IME_ON_FREE,
  META,
  OPEN_ALL,
  REPLY,
  REVIEW_ALL,
  captureVisit,
  currentVisit,
  imeHeldIn,
  imeKey,
  imeTail,
} from '../app/state.ts';
import { html, lucideIcon } from '../platform/markup.ts';
import { errText, translateTemplate, translate, TIP_TEXT, josa } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { announce, endNotice, lineNote, quietNote, sourceOk } from '../platform/notices.ts';
import { hideTip } from '../platform/tooltip.ts';
import {
  SAVING_LINES,
  KEYED_PAGE,
  KEY_SAVE_OUT,
  READING_LINE_PAGE,
  canVerdict,
  drawPageVerdicts,
  fillPageLine,
  pageTakesVerdict,
  pageTargetOf,
  pageTargetShort,
  pageVerdictPins,
  isAutoScrolling,
  canCancelVerdict,
  currentVerdictOn,
  pageUnderReadingLine,
  readingPageWithLine,
  sayGliding,
  endJumpForScroll,
  pageLineSlot,
  stickReadingLine,
  pageVerdictsOn,
} from './flow-line.ts';
import { IS_BESIDE_PAGES, bringPage, redrawOnBesideChange } from './view-panel.ts';
import { PINS_APPLIED_SEQ, gotoPinRef, loadPins } from '../pins/flow-list.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $, typingNow, searchToPage } from '../platform/dom.ts';
import { verdictOf } from '../app/rules-pins.ts';
import { isMe } from '../app/state-people.ts';
import { docInfo, verdictLabel, viewerBlocked } from '../documents/state.ts';
import { EDITOR } from '../pins/flow-edit.ts';

// ---------------- Drafts kept per pin (sessionStorage)
// One record per instance label for this tab: {v:1, d:{<key>: {text, base, rev, mode, folded, at, tried, from}}}. The
// key is '<doc>:<pin id>' for a verdict's draft, '<doc>:p<page>' for a page's (the draft of a verdict taken back
// elsewhere, waiting for the next verdict on that page). text: typed and not written yet; base: the reason it was typed
// over ('' for a new reason); rev: the pin's rev when a saved reason was opened (a change is written against that rev,
// never a later one); mode: 'replace' (the whole note, against rev) or 'add' (into an empty note, or under someone's);
// folded: put away with [접기] - it never opens by itself; tried: the session's writes whose answer was lost
// (ReasonTry) - a folded, reopened or reloaded draft still knows them, or its next write would add a reason that had
// landed again; from: the parts of its text that were moved off a pin whose reason may still be written there (a write
// out, a [다시 시도], a write that lost its answer)
// - every such pin, however often the draft moved on ('a → 쪽 → b', 'a → b → c'; a page's draft is no pin and adds
//   none),
// each part with its place in the text and that pin's lost writes (ReasonPart). Kept as the last key alone, a write
// that lands on an earlier pin afterwards would leave the copy, to be written again. A part is a place, not a string: a
// sentence the person typed again elsewhere in the draft is not it, and the place follows every edit (editParts) - an
// edit inside it makes it no longer that text, and it is let go. Once one of those pins' writes lands with the part's
// text, the part leaves the copy (takeWrittenText), its failure does not make the old key again (sayReasonFailed), and
// a write of the copy waits for one that is out (waitForKinWrites) and first settles the lost ones from that pin
// (checkLostWrites). A stored `from` that is a string is one key whose part is the whole text. Written on every input;
// taken out once written, dropped (Esc twice, [지우기]), moved to a new verdict, or when its pin is found gone from the
// lists (restoreKeptDrafts).
const DRAFT_VERSION = 1;
type ReasonDraft = {
  text: string;
  base: string;
  rev: number;
  mode: string;
  folded: boolean;
  at: number;
  tried: ReasonTry[];
  from: ReasonPart[];
};
// A part of a draft's text moved off pin key k: text[s, e) is what k's reason write may put on k, and tried are k's
// writes whose answer was lost - the evidence that one may have put it there already.
type ReasonPart = { k: string; s: number; e: number; tried: ReasonTry[] };
function draftStorageKey() {
  return 'limnReason:' + encodeURIComponent((META && META.label) || '');
}
function readAllDrafts(): Record<string, ReasonDraft> {
  try {
    const stored = JSON.parse(sessionStorage.getItem(draftStorageKey()) || 'null');
    return stored && stored.v === DRAFT_VERSION && stored.d && typeof stored.d === 'object' ? stored.d : {};
  } catch (error) {
    return {};
  }
}
function saveAllDrafts(drafts: Record<string, ReasonDraft>) {
  try {
    if (Object.keys(drafts).length)
      sessionStorage.setItem(draftStorageKey(), JSON.stringify({ v: DRAFT_VERSION, d: drafts }));
    else sessionStorage.removeItem(draftStorageKey());
  } catch (error) {}
}
// A verdict's draft key (id a pin number) or a page's (id 'p<page>').
function reasonDraftKey(doc: string | null, id: number | string) {
  return (doc || '') + ':' + id;
}
function parseDraft(x: any): ReasonDraft | null {
  return x && typeof x.text === 'string' && x.text.trim()
    ? {
        text: x.text,
        base: typeof x.base === 'string' ? x.base : '',
        rev: typeof x.rev === 'number' ? x.rev : -1,
        mode:
          x.mode === 'replace' || (x.mode !== 'add' && typeof x.base === 'string' && !!x.base.trim())
            ? 'replace'
            : 'add',
        folded: !!x.folded,
        at: Number(x.at) || 0,
        tried: Array.isArray(x.tried) ? x.tried.filter(isReasonTry) : [],
        from: parseDraftParts(x.from, x.text),
      }
    : null;
}
// A kept draft's from as its parts that still fit its text (a string is one key whose part is the whole text).
function parseDraftParts(x: unknown, text: string): ReasonPart[] {
  if (typeof x === 'string') return x ? [{ k: x, s: 0, e: text.length, tried: [] }] : [];
  if (!Array.isArray(x)) return [];
  return x
    .filter(
      (part) =>
        !!part &&
        typeof part.k === 'string' &&
        !!part.k &&
        Number.isInteger(part.s) &&
        Number.isInteger(part.e) &&
        part.s >= 0 &&
        part.s < part.e &&
        part.e <= text.length,
    )
    .map((part) => ({
      k: part.k,
      s: part.s,
      e: part.e,
      tried: Array.isArray(part.tried) ? part.tried.filter(isReasonTry) : [],
    }));
}
// Text compared as a reason is written: line breaks as '\n', no space around it (a write sends the draft trimmed).
function normalizeReason(text: string) {
  return text.replace(/\r\n?/g, '\n').trim();
}
// Parts after their text's [start, end) became `length` other characters: one before or after it keeps its text (moved
// by the difference); one it touched inside - typed into, cut, taken away - is no longer that text and goes.
function shiftParts(parts: ReasonPart[], start: number, end: number, length: number): ReasonPart[] {
  const delta = length - (end - start);
  return parts.flatMap((part) =>
    part.e <= start ? [part] : part.s >= end ? [{ ...part, s: part.s + delta, e: part.e + delta }] : [],
  );
}
// Parts of text `was` in `now`, the field's text after one input, the caret at `caret` (the end of what was typed or
// pasted, or where a deletion was): what changed is what lies between their longest common start and end - the end no
// further than the caret, so a letter typed before the same letter is placed where it was typed. (Text typed next to it
// on its own line keeps its place too: whether that changed its sentence is judged when it would leave, isOnOwnLines -
// a line typed above it is typed before its line break.)
function editParts(parts: ReasonPart[], was: string, now: string, caret: number): ReasonPart[] {
  if (!parts.length || was === now) return parts;
  let suf = 0,
    pre = 0;
  const suffixLimit = Math.min(was.length, now.length - Math.min(Math.max(caret, 0), now.length));
  while (suf < suffixLimit && was[was.length - 1 - suf] === now[now.length - 1 - suf]) suf++;
  const prefixLimit = Math.min(was.length, now.length) - suf;
  while (pre < prefixLimit && was[pre] === now[pre]) pre++;
  return shiftParts(parts, pre, was.length - suf, now.length - suf - pre);
}
// Whether a part of the text still has its lines to itself: nothing but spaces between each end and a line break or the
// text's end. Text typed next to it on its line, at either end, or a line break beside it taken away, makes its
// sentence a new one - as an edit inside it does -, which stays whole: a part found written on the earlier verdict
// never leaves only the words added beside it to be written. Spaces typed after it change no sentence.
function isOnOwnLines(text: string, part: ReasonPart) {
  return /(^|\n)[ \t]*$/.test(text.slice(0, part.s)) && /^[ \t]*(\r?\n|$)/.test(text.slice(part.e));
}
// A draft (text and parts) joined under the draft `under` on a new line - `under` null: the draft as it is.
function joinDrafts(
  under: { text: string; from: ReasonPart[] } | null,
  x: { text: string; from: ReasonPart[] },
): { text: string; from: ReasonPart[] } {
  if (!under) return { text: x.text, from: x.from };
  const offset = under.text.length + 1;
  return {
    text: under.text + '\n' + x.text,
    from: [...under.from, ...x.from.map((part) => ({ ...part, s: part.s + offset, e: part.e + offset }))],
  };
}
// The text (with its parts) less every part moved off pin `key` whose text is `written` (normalizeReason) and that
// still has its lines to itself (isOnOwnLines) - with the line break that set it apart, the rest kept as it is - or
// null when none is.
function cutWrittenParts(
  text: string,
  parts: ReasonPart[],
  key: string,
  written: string,
): { text: string; from: ReasonPart[] } | null {
  const normalized = normalizeReason(written);
  if (!normalized) return null;
  let remaining = parts,
    hit = false;
  const at = (candidate: ReasonPart) =>
    candidate.k === key &&
    normalizeReason(text.slice(candidate.s, candidate.e)) === normalized &&
    isOnOwnLines(text, candidate);
  for (let part = remaining.find(at); part; part = remaining.find(at)) {
    hit = true;
    let start = part.s,
      end = part.e;
    const after = /^[ \t]*\r?\n/.exec(text.slice(end)),
      before = after ? null : /\r?\n[ \t]*$/.exec(text.slice(0, start));
    if (after) end += after[0].length;
    else if (before) start -= before[0].length;
    const cutPart = part;
    text = text.slice(0, start) + text.slice(end);
    remaining = shiftParts(
      remaining.filter((x) => x !== cutPart),
      start,
      end,
      0,
    );
  }
  return hit ? { text: text, from: remaining } : null;
}
// Whether a stored lost write is one (ReasonTry).
function isReasonTry(value: any): value is ReasonTry {
  return (
    !!value &&
    typeof value.text === 'string' &&
    typeof value.rev === 'number' &&
    typeof value.pre === 'string' &&
    typeof value.stamp === 'boolean' &&
    typeof value.post === 'string'
  );
}
// The draft kept under id (a pin number, or 'p<page>') on document doc, or null.
function getDraft(doc: string | null, id: number | string): ReasonDraft | null {
  return parseDraft(readAllDrafts()[reasonDraftKey(doc, id)]);
}
// Keeps text under id - or drops it when nothing is unsaved (empty, or the reason as it is saved). The parts the draft
// there had stay unless `options` names others (and its text is the same); a draft never counts its own key.
function putDraft(
  doc: string | null,
  id: number | string,
  text: string,
  base: string,
  revision?: number,
  options?: { mode?: string; folded?: boolean; tried?: ReasonTry[]; from?: ReasonPart[] },
) {
  const drafts = readAllDrafts(),
    key = reasonDraftKey(doc, id),
    mode = (options && options.mode) || (base.trim() ? 'replace' : 'add'),
    was = parseDraft(drafts[key]);
  const from = parseDraftParts(
    options && options.from !== undefined ? options.from : was && was.text === text ? was.from : [],
    text,
  ).filter((part) => part.k !== key);
  if (text.trim() && text.trim() !== base.trim())
    drafts[key] = {
      text,
      base,
      rev: revision === undefined ? -1 : revision,
      mode,
      folded: !!(options && options.folded),
      at: Date.now(),
      tried: (options && options.tried) || [],
      from,
    };
  else delete drafts[key];
  saveAllDrafts(drafts);
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
function dropDraft(doc: string | null, id: number | string) {
  const drafts = readAllDrafts(),
    key = reasonDraftKey(doc, id);
  if (key in drafts) {
    delete drafts[key];
    saveAllDrafts(drafts);
  }
}
// The part a draft (text, lost writes) becomes when it is moved off pin `key`: all of it, with that pin's lost writes.
function movedPart(key: string, x: { text: string; tried: ReasonTry[] }): ReasonPart {
  return { k: key, s: 0, e: x.text.length, tried: x.tried };
}
// The text of a draft that is the person's own: as typed, less - when it changes a saved reason (mode 'replace') - the
// stamped lines others added under it ('(추가 HH:MM) …') as that saved note (base) held them.
function ownText(mode: string, text: string, base: string) {
  if (mode !== 'replace') return text;
  const stamp = /^\(추가 \d{1,2}:\d{2}\) /,
    theirs = new Set(base.split(/\r?\n/).filter((line) => stamp.test(line)));
  return text
    .split('\n')
    .filter((line) => !(stamp.test(line.replace(/\r$/, '')) && theirs.has(line.replace(/\r$/, ''))))
    .join('\n');
}
// What a draft becomes moved off `key` (a pin's, or '' for none) to another verdict, as a new reason: its own text only
// (ownText: the lines others added under a saved reason being changed stay on the verdict they were written on), with
// the parts it came with (while that text is all of it) and, `key` a pin's, all of it as a part moved off that pin with
// its lost writes.
function draftMovedOff(
  key: string,
  x: { text: string; base: string; mode: string; tried: ReasonTry[]; from: ReasonPart[] },
): { text: string; from: ReasonPart[] } {
  const own = ownText(x.mode, x.text, x.base);
  return {
    text: own,
    from: [...(own === x.text ? x.from : []), ...(key ? [movedPart(key, { text: own, tried: x.tried })] : [])],
  };
}
// Moves the draft under from (a pin or a page) to verdict pin id, as a new reason - it was never written on the other -
// remembering where it came from (draftMovedOff, draftsMovedOff). The same whether a popover held it or it was folded
// or kept, so a folded change of a saved reason never carries others' lines into the new verdict's reason. A draft with
// nothing of the person's own stays where it is.
function moveDraft(doc: string | null, from: number | string, id: number): ReasonDraft | null {
  const x = getDraft(doc, from);
  if (!x) return null;
  const moved = draftMovedOff(typeof from === 'number' ? reasonDraftKey(doc, from) : '', x);
  if (!moved.text.trim()) return null;
  dropDraft(doc, from);
  putDraft(doc, id, moved.text, '', -1, { mode: 'add', folded: x.folded, from: moved.from });
  return x;
}
// The drafts moved off pin id's key on document doc (moveDraft, placeFailedCancelDraft) while its reason may still be
// written there, by key.
function draftsMovedOff(doc: string | null, id: number): string[] {
  const drafts = readAllDrafts(),
    key = reasonDraftKey(doc, id);
  return Object.keys(drafts).filter((x) => {
    const draft = parseDraft(drafts[x]);
    return !!draft && draft.from.some((part) => part.k === key);
  });
}
// Pin id's reason text was written there: the drafts moved off its key lose the parts that are that text
// (cutWrittenParts).
function cutWrittenDrafts(doc: string | null, id: number, text: string) {
  const drafts = readAllDrafts(),
    key = reasonDraftKey(doc, id);
  let changed = false;
  for (const x of Object.keys(drafts)) {
    const draft = parseDraft(drafts[x]),
      cut = draft ? cutWrittenParts(draft.text, draft.from, key, text) : null;
    if (!draft || !cut) continue;
    if (cut.text.trim()) drafts[x] = { ...draft, text: cut.text, from: cut.from };
    else delete drafts[x];
    changed = true;
  }
  if (changed) saveAllDrafts(drafts);
}
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
  visit: any;
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
// A new reason's write whose answer was lost: text, sent against the pin's rev `rev`, would have made the note pre,
// then the stamp a note_append puts first when stamp ('(추가 12:30) ', the time the server's), then text, then post.
type ReasonTry = { text: string; rev: number; pre: string; stamp: boolean; post: string };
let REASON_SESSION = null as ReasonSession | null;
let SESSION_SEQUENCE = 0;
// The popovers moved away from (another page, another document, another popover) before their verdict's save answered,
// by line (pageLineSlot of the document they were typed on): each stays bound to that save, not to the screen.
const DETACHED_SESSIONS = new Map() as Map<string, ReasonSession>;
// the verdict pin the last save on a page line made: its line offers the way to its reason wherever it is
let LAST_LINE_SAVE = 0;
let LAST_KEY_SAVE = 0; // ...when that save was a key's: its line says 'Enter 이유 쓰기'
// The pins this person withdrew (the save's undo, [판정 취소], a pressed word pressed again) while a reason for them
// may still be on its way: its failure, or its finding the pin gone, is no news to them - nothing is said. A failed
// withdrawal or a restore takes the pin out again.
const WITHDRAWN_PINS = new Set() as Set<number>;
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
// Whether a reason session writes the whole note against its rev (a change of a saved reason, or over a newer note
// seen).
function replacesWholeNote(session: ReasonSession) {
  return session.mode === 'replace';
}
function isReasonOpenOn(page: number) {
  const session = REASON_SESSION;
  return !!session && session.page === page && session.doc === DOC && currentVisit(session.visit);
}
// The pin a reason session is for, from the lists, or undefined.
function findReasonPin(id: number) {
  return OPEN_ALL.concat(REVIEW_ALL, DONE_ALL).find((pin) => pin.id === id);
}
function isReasonField(target: unknown): target is HTMLTextAreaElement {
  return target instanceof HTMLTextAreaElement && target.classList.contains('pv-reason');
}
// The open popover's field, or null.
function findReasonField() {
  return document.querySelector('#doc .pv-pop .pv-reason') as HTMLTextAreaElement | null;
}
// Whether the session's text is something not yet written: not empty, not the reason it opened on, not what it wrote.
function hasUnsavedReason(session: ReasonSession) {
  const text = session.text.trim();
  return !!text && text !== session.base.trim() && text !== session.saved;
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
  REASON_SESSION = null;
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
    KEY_GUARD = true;
    PENDING_REFOCUS = { page: session.page, sel: '[data-act="pv-reason-open"]' };
  }
}
// After the lines are drawn (drawPageVerdicts): a focus a session's end owes goes to its line's control
// (PENDING_REFOCUS).
let PENDING_REFOCUS = null as { page: number; sel: string } | null;
function refocusAfterLines() {
  const owed = PENDING_REFOCUS;
  if (!owed) return;
  PENDING_REFOCUS = null;
  const control = document.querySelector('#doc .pv[data-page="' + owed.page + '"] ' + owed.sel) as HTMLElement | null;
  if (control) control.focus({ preventScroll: true });
}
// A rebuild of the pages (buildDoc) takes the open popover away with them, and a focus in it would fall to nothing:
// what is typed on would be lost and a digit would save a verdict. Before it, holdReasonFocus notes the focus in the
// session's popover - its field with the selection, or one of its controls; null when the focus is anywhere else, which
// the rebuild leaves alone. After it, restoreReasonFocus gives the focus back to the same place in the popover drawn
// again, beside the pages or under one - while it is still on nothing. An input method's composition ends with the old
// field (the session's text holds what it had composed). A popover not drawn again leaves the keys typed on no verdict
// keys (KEY_GUARD).
type ReasonFocus = { sid: number; sel: [number, number, string] | null; act: string };
function holdReasonFocus(): ReasonFocus | null {
  const session = REASON_SESSION,
    active = document.activeElement as HTMLElement | null,
    pop = active && active.closest ? active.closest('#doc .pv-pop') : null;
  if (!session || !active || !pop || pop.getAttribute('data-id') !== 's' + session.sid) return null;
  if (isReasonField(active))
    return {
      sid: session.sid,
      sel: [active.selectionStart, active.selectionEnd, active.selectionDirection || 'none'],
      act: '',
    };
  return { sid: session.sid, sel: null, act: active.dataset.act || '' };
}
function restoreReasonFocus(held: ReasonFocus | null) {
  const active = document.activeElement;
  if (!held || (active && active !== document.body)) return;
  const session = REASON_SESSION,
    pop =
      session && session.sid === held.sid ? document.querySelector('#doc .pv-pop[data-id="s' + held.sid + '"]') : null;
  const control = (
    !pop
      ? null
      : held.sel
        ? pop.querySelector('.pv-reason')
        : held.act
          ? pop.querySelector('[data-act="' + held.act + '"]')
          : null
  ) as HTMLElement | null;
  if (!control) {
    KEY_GUARD = true;
    return;
  }
  control.focus({ preventScroll: true });
  if (held.sel && isReasonField(control))
    control.setSelectionRange(held.sel[0], held.sel[1], held.sel[2] as 'forward' | 'backward' | 'none');
}
// Once per document in this page's life, when its first lines are drawn: the drafts kept for pins that are gone are let
// go, one kept for a verdict that is not its line's current one of the person's becomes its page's draft (only that is
// marked there), and the others wait on their lines ('초안 있음') - none opens by itself: a popover restored on a page
// far from the reading one would open out of sight, said only to a screen reader. The status line says how many came
// back, with [보기], which brings the first one's line into view and puts the focus on its mark.
const RESTORED_DOCS = new Set() as Set<string>;
function restoreKeptDrafts() {
  const doc = DOC || '';
  if (RESTORED_DOCS.has(doc) || !META) return;
  RESTORED_DOCS.add(doc);
  const drafts = readAllDrafts(),
    pre = doc + ':',
    kind = META.kind;
  let changed = false;
  const pages = new Set() as Set<number>;
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
// Brings page `page`'s line into view and puts the focus on its draft's mark ('초안 있음') - before the saved reason,
// which comes first on the line and opens the popover too - else its reason control (focusLine).
function showDraftLine(page: number) {
  if (IS_BESIDE_PAGES) {
    bringPage(page);
    stickReadingLine();
  } // beside the pages the panel is the line, once the page is read (verdict/view-panel.ts)
  const line = document.querySelector('#doc .pv[data-page="' + page + '"]') as HTMLElement | null;
  if (!line) return;
  if (!IS_BESIDE_PAGES) {
    const block = (line.parentElement || line) as HTMLElement;
    endJumpForScroll();
    block.scrollIntoView({ block: block.getBoundingClientRect().height <= $('#left').clientHeight ? 'center' : 'end' });
  }
  requestAnimationFrame(() => {
    if (isReasonField(document.activeElement)) return; // the mark was already pressed: its field keeps the focus
    const mark = document.querySelector('#doc .pv[data-page="' + page + '"] .pv-draft') as HTMLElement | null;
    if (mark) mark.focus({ preventScroll: true });
    else if (!focusLine(page)) searchToPage();
  });
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
// Closes the popover. Closed on purpose (back: Esc, Enter after its save, [닫기], [지우기], [접기]) the focus stays on
// its own page: on the line's reason control ([이유 추가], the saved reason, '초안 있음' - whichever the line shows
// now), else the pressed word, else the line's first word - never the PDF area, from which the next Tab would go to the
// first page's line and scroll the document there. Closed by moving on with the focus inside, the focus goes to the PDF
// area.
function closeReasonPopover(back: boolean) {
  const session = REASON_SESSION,
    pop = document.querySelector('#doc .pv-pop'),
    had = !!pop && pop.contains(document.activeElement);
  REASON_SESSION = null;
  drawPageVerdicts();
  if (!back) {
    if (had) searchToPage();
    return;
  }
  if (!session || !focusLine(session.page)) searchToPage();
}
// Puts the focus on page `page`'s line: its reason control, else its pressed word, else its first word. Returns whether
// it did.
function focusLine(page: number) {
  const line = document.querySelector('#doc .pv[data-page="' + page + '"]');
  if (!line) return false;
  const control = (line.querySelector('[data-act="pv-reason-open"]') ||
    line.querySelector('.vd-b[aria-pressed="true"]') ||
    line.querySelector('.vd-b')) as HTMLElement | null;
  if (!control) return false;
  control.focus({ preventScroll: true });
  return true;
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
      session.escArm = '';
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
    REASON_SESSION = session;
    if (draft && draft.folded) keepDraft(session);
  }
  KEY_GUARD = false;
  hideTip();
  drawPageVerdicts();
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
  REASON_SESSION = session;
  KEY_GUARD = false;
  hideTip();
  drawPageVerdicts();
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
  REASON_SESSION = null;
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
  drawPageVerdicts();
  if (!had) return;
  KEY_GUARD = true;
  if (!focusLine(page)) searchToPage();
}
// Puts the focus in the open field, its caret at the end.
function focusReasonField() {
  const field = findReasonField();
  if (!field || field.disabled) return;
  field.focus({ preventScroll: true });
  const end = field.value.length;
  field.setSelectionRange(end, end);
}
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
  LAST_LINE_SAVE = id;
  LAST_KEY_SAVE = byKey ? id : 0;
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
  let pin = undefined as Pin | null | undefined;
  try {
    pin = (await api('/api/pins/' + session.id, { what: '핀 읽기', silent: true })).data.pin;
  } catch (error) {
    const x = error as ApiError;
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
  const got =
    pin && !pin.dropped_at ? [...session.tried].reverse().find((attempt) => hasLanded(attempt, pin as Pin)) : null;
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
  if (doc === DOC) drawPageVerdicts();
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
    REASON_SESSION = kept;
    drawPageVerdicts();
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
const FAILED_CANCEL_WAITS = new Map() as Map<string, { id: number; page: number; doc: string | null; shown: boolean }>;
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
  if (doc === DOC) drawPageVerdicts();
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
// verdict/flow-line.ts says so).
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
    drawPageVerdicts();
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
  REASON_SESSION = session;
  drawPageVerdicts();
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
const REASON_WRITES = new Map() as Map<string, { r: ReasonSession; w: Promise<boolean> }>;
// The sessions whose failure the status line offers [다시 시도] for (sayReasonFailed), with that message: a write
// elsewhere of their text takes it out of them and the message goes (takeWrittenText) - the [다시 시도] would write it
// a second time.
const RETRY_NOTICES = new Map() as Map<ReasonSession, Notice>;
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
  let sure = true as true | ApiError | null;
  for (const k of new Set(session.via.filter((part) => part.tried.length).map((part) => part.k))) {
    const id = Number(k.slice(k.lastIndexOf(':') + 1));
    let fetched = null as Pin | null;
    try {
      fetched = (await api('/api/pins/' + id, { what: '핀 읽기', silent: true })).data.pin || null;
    } catch (error) {
      const x = error as ApiError;
      if (!x || !x.status || x.status >= 500) {
        sure = x || null;
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
        ) as ReasonTry;
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
    const { status, data } = await api('/api/pins/' + id + '/edit', {
      method: 'POST',
      intent: 'reason-fence',
      silent: true,
      expect: [409],
      body: { note: String(pin.note || ''), base_rev: typeof pin.rev === 'number' ? pin.rev : 0 },
    });
    if (status !== 409) return { fenced: true };
    const answered = data && data.pin;
    return answered ? { pin: answered } : { unknown: null };
  } catch (error) {
    const x = error as ApiError;
    return x && x.status === 404 ? { pin: null } : { unknown: x || null };
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
    ].filter(Boolean),
  ) as Set<ReasonSession>;
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
    const line = document.querySelector('#doc .pv[data-page="' + session.page + '"]') as HTMLElement | null;
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
  REASON_SESSION = null;
  drawPageVerdicts();
  if (had) {
    KEY_GUARD = true;
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
  if (REASON_SESSION === session) drawPageVerdicts();
  writing.then((ok) => {
    if (REASON_SESSION !== session) return;
    if (ok && session.text.trim() === session.saved) closeReasonPopover(false);
    else drawPageVerdicts();
  });
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
async function writeReason(session: ReasonSession, text: string, said: boolean): Promise<boolean> {
  if (viewerBlocked()) return false;
  let pin;
  try {
    pin = (await api('/api/pins/' + session.id, { what: '핀 읽기', silent: true })).data.pin;
  } catch (error) {
    const x = error as ApiError;
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
  const url = '/api/pins/' + session.id + '/edit',
    // silent: sayReasonFailed says a failure, with its target
    options = { method: 'POST', intent: 'reason', silent: true };
  let sent = null as ReasonTry | null; // the write out now, while its answer is awaited
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
      const { status, data } = await api(url, {
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
    const x = error as ApiError;
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
// What a reason session's verdict is about, by a short name for the status line: its page's target while its document
// is on screen ('PL16'), else its document's name.
function reasonTargetName(session: ReasonSession) {
  return targetNameOn(session.doc, session.page, session.id);
}
// The same for verdict pin id (0 while it has none) about page `page` of document doc.
function targetNameOn(doc: string | null, page: number, id: number) {
  if (doc === DOC) return pageTargetShort(page);
  const entry = doc ? docInfo(doc) : null;
  return (entry && entry.name) || (id ? '#' + id : translateTemplate('{page}쪽', { page }));
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
  if (REASON_SESSION !== session && session.doc === DOC) drawPageVerdicts();
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
  drawPageVerdicts();
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
  REASON_SESSION = null;
  drawPageVerdicts();
  const control = document.querySelector(
    '#doc .pv[data-page="' + session.page + '"] [data-act="pv-reason-open"]',
  ) as HTMLElement | null;
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
    options = { method: 'POST', intent: 'reason', silent: true, expect: [409] };
  const go = async () => {
    try {
      if (session.clearTried) {
        const pin = (await api('/api/pins/' + session.id, { what: '핀 읽기', silent: true })).data.pin;
        if (pin && !String(pin.note || '').trim()) return 'ok';
      }
      const { status, data } = await api(url, { ...options, body: { note: '', base_rev: session.rev } });
      if (status !== 409) return 'ok';
      const answered = data && data.pin;
      if (!answered) return 'gone';
      if (!String(answered.note || '').trim()) return 'ok'; // empty already: the clear that lost its answer landed
      if (String(answered.note || '').trim() !== session.base.trim()) {
        keepConflict(session, session.text, answered);
        return 'conflict';
      }
      await api(url, { ...options, expect: [], body: { note: '', base_rev: answered.rev } });
      return 'ok';
    } catch (error) {
      const x = error as ApiError,
        statusCode = x && typeof x.status === 'number' ? x.status : 0;
      if (!statusCode) session.clearTried = true;
      lineNote(
        translateTemplate('이유 지우기 실패 · {why} — {target}', {
          why: statusCode ? (x.data && errText(x.data)) || 'HTTP ' + statusCode : translate('서버에 닿지 않습니다'),
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
    drawPageVerdicts();
    focusReasonField();
  }
  if (session.doc === DOC) await loadPins();
}
// The undo of [지우기]: the reason written back, unless someone wrote a note meanwhile.
async function undoClearReason(id: number, old: string): Promise<boolean> {
  let ok = false;
  try {
    const pin = (await api('/api/pins/' + id, { what: '핀 읽기', where: NOTICE_HOST.LINE })).data.pin;
    if (pin && !String(pin.note || '').trim()) {
      await api('/api/pins/' + id + '/edit', {
        method: 'POST',
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

// ---------------- The popover and the line's reason
// What the popover says of its draft: '저장 중…' while it writes, '저장됨' with a check when its text is the saved
// reason, '저장 안 됨' when it is not written yet, nothing when empty.
function popoverState(session: ReasonSession): { text: string; cls: string } {
  if (session.writing || session.saveWhenBound) return { text: translate('저장 중…'), cls: 'busy' };
  const text = session.text.trim();
  if (!text) return { text: '', cls: '' };
  return text === session.saved || text === session.base.trim()
    ? { text: translate('저장됨'), cls: 'ok' }
    : { text: translate('저장 안 됨'), cls: 'warn' };
}
// What the keys do now, under the field: with a fine pointer and the focus in it, Enter saves (and with nothing typed
// Esc closes); after a first Esc, what the second does. With touch only the second press of [닫기] is said. The digits
// are not mentioned: in the field they are text.
function popoverHint(session: ReasonSession, focused: boolean) {
  const fine = matchMedia('(pointer:fine)').matches;
  if (session.escArm === 'btn') return translate('[닫기]를 한 번 더 누르면 이 이유를 버립니다');
  if (!fine) return '';
  if (session.escArm) return translate('Esc 한 번 더 누르면 이 이유를 버립니다');
  if (!focused) return '';
  return session.text.trim() ? translate('Enter 저장') : translate('Enter 저장') + ' · ' + translate('Esc 닫기');
}
// The popover on page `page`'s line while its session is open there (a person who may make a verdict): a labelled,
// non-modal group - the field, then one row: whose reason it is ('판정 #16 보류 이유', '판정 #16 보류 · 저장된 이유
// 수정' when it changes a saved one, '#15 채택에서 옮김' after a move), the draft's state, the keys, and [지우기] (a
// saved reason), [접기] (a draft, not while it is being written: the popover folds to the line's '초안 있음'), [닫기],
// [저장]. When a write found the note changed elsewhere, a row above the field shows that note whole (scrolling when
// long) with [메모 보기] and [그 위에 쓰기]. The keys' line is always there (aria-describedby never points at nothing),
// empty when there is nothing to say. The field is drawn empty; its text is put in after drawing (fillReasonField),
// never as markup a redraw could put back under the caret or an input method.
function reasonPopoverHtml(page: number) {
  const session = isReasonOpenOn(page) && canVerdict() ? REASON_SESSION : null;
  if (!session) return '';
  const active = document.activeElement,
    focused = isReasonField(active) && active.dataset.id === 's' + session.sid,
    state = popoverState(session),
    hint = popoverHint(session, focused);
  const word = verdictLabel(session.key),
    who = !session.id
      ? translateTemplate('{word} 판정 이유 · 판정 저장 중', { word })
      : replacesWholeNote(session) && session.base.trim()
        ? translateTemplate('판정 #{id} {word} · 저장된 이유 수정', { id: session.id, word })
        : translateTemplate('판정 #{id} {word} 이유', { id: session.id, word });
  const from = session.from ? findReasonPin(session.from) : null,
    moved = session.from
      ? translateTemplate('#{id} {word}에서 옮김', {
          id: session.from,
          word: verdictLabel((from && verdictOf(from)) || ''),
        })
      : '';
  const conflictRow = session.conflict
    ? html`<div class="pv-pop-cf" role="alert"><span class="pv-pop-cf-t">${translate('그사이 다른 곳에서 메모가 바뀌었습니다 — 지금 메모')}</span>\
<div class="pv-pop-cf-note" translate="no" tabindex="0">${session.conflict.note || translate('(빈 메모)')}</div><span class="pv-pop-acts">\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-see">${translate('메모 보기')}</button>\
<button type="button" class="btn-sm hit" data-act="pv-reason-reapply" data-tip="${translate('바뀐 메모를 이 글로 바꿉니다')}">${translate('그 위에 쓰기')}</button></span></div>`
    : '';
  // never pointing at a line that says nothing (while it writes)
  const describedBy = hint && !session.writing ? html` aria-describedby="pv-pop-h-${session.sid}"` : '';
  return html`<div class="pv-pop" role="group" data-id="s${session.sid}" aria-labelledby="pv-pop-to-${session.sid}"${describedBy}>${conflictRow}\
<textarea class="pv-reason" rows="1" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="s${session.sid}" data-pin="${session.id}"${session.writing ? html` readonly aria-busy="true"` : ''} \
placeholder="${translate('이유 (선택)')}" aria-label="${translateTemplate('{who} (선택)', { who })}"${describedBy}></textarea>\
<div class="pv-pop-f"><span class="pv-pop-to" id="pv-pop-to-${session.sid}" translate="no">${who}${moved ? html`<span class="pv-pop-from"> · ${moved}</span>` : ''}</span>\
<span class="pv-pop-st${state.cls ? ' ' + state.cls : ''}" aria-live="polite">${state.cls === 'ok' ? lucideIcon('check') : ''}${state.text}</span><span class="pv-pop-h" id="pv-pop-h-${session.sid}">${hint}</span>\
<span class="pv-pop-acts">${
    replacesWholeNote(session) && session.base.trim()
      ? html`<button type="button" class="btn-ghost btn-sm pv-pop-clear hit" data-act="pv-reason-clear" \
data-tip="${translate('저장한 이유를 지웁니다. 상태 줄의 [되돌리기]가 되살립니다')}">${translate('지우기')}</button>`
      : ''
  }\
${hasUnsavedReason(session) && !session.writing && session.id ? html`<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-fold" data-tip="${translate('초안을 둔 채 접습니다. 줄의 [초안 있음]이 다시 엽니다')}">${translate('접기')}</button>` : ''}\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-close" data-tip="${translate('닫습니다. 쓰던 이유가 있으면 한 번 더 눌러야 버립니다')}">${translate('닫기')}</button>\
<button type="button" class="btn-sm pv-pop-save hit" data-act="pv-reason-save"${session.writing || session.conflict ? html` aria-disabled="true"` : ''}>${translate('저장')}</button></span></div></div>`;
}
// The reason on page `page`'s line, after its state: the saved reason of its current verdict (a check and its first
// line, .pv-rn) - a button that opens the popover to change it on the person's own open verdict, with a pencil and the
// name '저장된 이유 수정' -, then (.pv-ra) a kept draft not written yet ('초안 있음', which opens it: a folded popover,
// a failed write, a reload's other drafts, a page's draft whose verdict went) on any line, or the way to write one for
// the person's own open verdict without a reason - on the reading line and on the line of the last save
// (LAST_LINE_SAVE): after a key save, while the keys act on the line (a mouse screen), 'Enter 이유 쓰기' (Enter opens
// it, openReasonOnEnter); else [이유 추가] - a click save's. Every other line with such a verdict holds that [이유
// 추가] hidden (the identifier's way, hidden: never shown, focused or heard), which fitPageLines lays out unseen
// (#doc.pv-measure, components.css): every line is fitted as the reading line it may become, so becoming it or leaving
// it never stacks or unstacks a line. Every name holds the words the button shows. Nothing for the reason the open
// popover holds.
function inlineReason(page: number, cur: Pin | undefined) {
  const open = isReasonOpenOn(page) && !!REASON_SESSION && (!cur || REASON_SESSION.id === cur.id || !REASON_SESSION.id),
    pageDraft = open ? null : getDraft(DOC, 'p' + page);
  const sep = html`<span class="pv-sep" aria-hidden="true">·</span>`;
  const mark = html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-draft hit" data-act="pv-reason-open" \
aria-label="${translate('초안 있음 — 저장 안 된 이유 초안, 누르면 이어 씁니다')}" data-tip="${translate('저장 안 된 이유 초안이 있습니다 — 누르면 이어 씁니다')}">${translate('초안 있음')}</button></span>`;
  if (!cur) return pageDraft ? mark : '';
  const mine = canCancelVerdict(cur),
    note = String(cur.note || ''),
    first = note.split('\n')[0];
  const verdictDraft = open ? null : getDraft(DOC, cur.id),
    draft = !!verdictDraft && verdictDraft.text.trim() !== note.trim();
  const ok = html`<span class="pv-ok" aria-hidden="true">${lucideIcon('check')}</span>`;
  const saved = !note
    ? ''
    : mine && !open
      ? html`<span class="pv-rn">${sep}<button type="button" class="btn-ghost btn-sm pv-note hit" data-act="pv-reason-open" translate="no" \
aria-label="${translateTemplate('{note} — 저장된 이유 수정, 판정 #{id}', { id: cur.id, note: first })}" data-tip="${translate('저장된 이유 수정')}">${ok}<span class="pv-note-t">${first}</span>${lucideIcon('pencil')}</button></span>`
      : // open: no box over the popover
        html`<span class="pv-rn">${sep}<span class="pv-note" translate="no"${open ? '' : html` data-tip="${note}"`}>${ok}${first}</span></span>`;
  // a key save: its line says the key
  const keys = KEYED_PAGE === page && LAST_KEY_SAVE === cur.id && matchMedia('(pointer:fine)').matches;
  const act =
    (draft || (pageDraft && !verdictDraft)) && mine && !open
      ? mark
      : pageDraft && !mine
        ? mark
        : !mine || open || note
          ? ''
          : READING_LINE_PAGE === page || LAST_LINE_SAVE === cur.id
            ? keys
              ? html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" aria-keyshortcuts="Enter" \
data-tip="${translate('이 판정의 이유를 씁니다. 메모로 붙습니다')}"><kbd class="pv-kbd">Enter</kbd> ${translate('이유 쓰기')}</button></span>`
              : html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" \
data-tip="${translate('이 판정의 이유를 씁니다. 메모로 붙습니다')}">${translate('이유 추가')}</button></span>`
            : // no data-act: no focus or press finds it
              html`<span class="pv-ra" hidden>${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">${translate('이유 추가')}</button></span>`;
  return html`${saved}${act}`;
}
// After a line is drawn (fillPageLine): the open field holds the session's text - put in only when it differs and no
// input method is composing - and its height follows its lines.
function fillReasonField(line: HTMLElement) {
  const session = REASON_SESSION,
    field = line.querySelector('.pv-pop .pv-reason') as HTMLTextAreaElement | null;
  if (!session || !field) return;
  if (field.value !== session.text && COMPOSING_FIELD !== field) {
    const had = document.activeElement === field;
    field.value = session.text;
    if (had) {
      const end = field.value.length;
      field.setSelectionRange(end, end);
    }
  }
  growReasonField(field);
}
// The field's height: its lines, up to its max-height (CSS), from one line.
function growReasonField(field: HTMLTextAreaElement) {
  field.style.height = 'auto';
  field.style.height = Math.ceil(field.scrollHeight + (field.offsetHeight - field.clientHeight)) + 'px';
}
// Page `page`'s line drawn again now: what its popover says follows the field's text and focus.
function refillLine(page: number) {
  const verdicts = pageVerdictsOn(),
    line = document.querySelector('#doc .pv[data-page="' + page + '"]') as HTMLElement | null;
  if (verdicts && line) fillPageLine(line, page, pageVerdictPins().get(page), verdicts);
}

// ---------------- Input
// The reason field an input method is composing in: its value is not put back. The composition ends with its field: a
// field drawn anew in its place (the pages built again) holds the session's text - left empty, the next input would
// write what it holds over the reason.
let COMPOSING_FIELD = null as HTMLTextAreaElement | null;
$('#doc').addEventListener('compositionstart', (event) => {
  if (isReasonField(event.target)) COMPOSING_FIELD = event.target;
});
// The composition's end settles what it brought back (followLanded, which waits for it), and what waited for it goes on
// (runComposedWaits).
$('#doc').addEventListener('compositionend', (event) => {
  const field = event.target;
  if (!isReasonField(field)) return;
  COMPOSING_FIELD = null;
  const session = REASON_SESSION;
  if (session && field.dataset.id === 's' + session.sid) {
    followLanded(session);
    if (REASON_SESSION === session) keepDraft(session);
  }
  setTimeout(runComposedWaits, 0);
});
// Whether an input method is composing a syllable in a reason field in the document, or the key that ended it there
// still holds it (app/state.ts imeHeldIn). Nothing takes that field away meanwhile: the lines do not move beside or
// under the pages (shouldStandBeside) and the pages are not built again (refreshDoc, afterComposition) until it ends
// and that key lets go. Moved or rebuilt, the field would be a new one: the old one's composition would end with it,
// the input method's commit would land on top of the text carried over (its last syllable doubled), and the Enter
// ibus-hangul hands on after the commit, with its repeats, would reach the new field as the viewer's - writing the
// reason and closing the popover.
function isComposingNow() {
  if (COMPOSING_FIELD && COMPOSING_FIELD.isConnected) return true;
  const field = imeHeldIn();
  return isReasonField(field) && field.isConnected;
}
const COMPOSED_WAITS = [] as (() => void)[]; // what waits for the composition's end (afterComposition)
// how often a wait looks again: a field taken out of the document ends its composition without the event
const COMPOSED_POLL_MS = 200;
// Resolves once no syllable is being composed in a reason field and the key that ended one has let it go
// (isComposingNow) - at once when none is.
function afterComposition(): Promise<void> {
  return new Promise((resolve) => {
    if (!isComposingNow()) {
      resolve();
      return;
    }
    const go = () => {
        clearInterval(timer);
        resolve();
      },
      timer = setInterval(() => {
        if (!isComposingNow()) go();
      }, COMPOSED_POLL_MS);
    COMPOSED_WAITS.push(go);
  });
}
// After a composition ended, unless another began meanwhile or the key that ended it still holds the field: the
// rebuilds that waited go on, and the lines move if the room crossed its bar while it lasted. Held, it looks again once
// that key lets the field go (app/state.ts IME_ON_FREE): up, another key, forgotten, or IME_HOLD_MS with no event of
// its own.
function runComposedWaits() {
  if (isComposingNow()) return;
  COMPOSED_WAITS.splice(0).forEach((go) => go());
  if (pageVerdictsOn()) redrawOnBesideChange();
}
IME_ON_FREE.push(runComposedWaits);
// Every input keeps the draft (putDraft), with the parts moved into it placed where they are now (placeParts) - a part
// brought back whose text has landed on its pin meanwhile leaves at once (followLanded), or once an input method's
// composition ends - and lets a first Esc go; the line follows its emptiness (the state).
$('#doc').addEventListener('input', (event) => {
  const field = event.target;
  if (!isReasonField(field)) return;
  const session = REASON_SESSION;
  if (!session || field.dataset.id !== 's' + session.sid) return;
  const was = session.text;
  session.text = field.value;
  session.via = placeParts(session, was, field.selectionEnd);
  session.escArm = '';
  if (COMPOSING_FIELD !== field) followLanded(session);
  keepDraft(session);
  growReasonField(field);
  refillLine(session.page);
});
// The parts of a session's text once an input made it its text from `was`, the caret at `caret`. A text the field held
// before - back by an undo or a redo, a paste or a typed letter taken back, a composition given up - has the parts it
// had then: an edit inside a part lets it go (editParts), so without these records the undo that puts the text back
// would leave it with none, the text would not be known as moved off its pin, and a write that lands there would leave
// it in the copy, to be written twice. The undo and redo records are the texts kept (hist.seen, the newest parts for
// each text), with their parts - their lost writes kept up to date (updateEvidence) and the writes that landed
// meanwhile on the pins they came from (hist.landed, followLanded) -, since the session's text or parts were last set
// from elsewhere: opened, moved to a new verdict, a part taken out. What the field held before that is not this
// session's to come back to with those parts - a part taken out because its text landed on its pin and typed back is a
// new reason, as it is when it is typed again (and the browser lets the field's own undo records go when its text is
// set). Any other text is placed by editParts. Texts with parts are kept until then, however many: letting one go, the
// undo past it would bring the text back without its part again. Texts without one go oldest first past HISTORY_CHARS
// characters - one missed is placed by editParts, which may keep a part the text had meanwhile, never invents one.
const HISTORY_CHARS = 200000;
function placeParts(session: ReasonSession, was: string, caret: number): ReasonPart[] {
  const same = (x: ReasonPart[], y: ReasonPart[]) =>
    x.length === y.length &&
    x.every((part, index) => part.k === y[index].k && part.s === y[index].s && part.e === y[index].e);
  let history = session.hist;
  if (!history || history.last.text !== was || !same(history.last.via, session.via)) {
    history = { last: { text: was, via: session.via }, seen: new Map(), size: 0, landed: [] };
    keepHistory(history, was, session.via);
  }
  const back = history.seen.get(session.text),
    via = back !== undefined ? back : editParts(session.via, was, session.text, caret);
  keepHistory(history, session.text, via);
  history.last = { text: session.text, via };
  session.hist = history;
  return via;
}
// A history keeps text with its parts, as the newest; past HISTORY_CHARS it lets the oldest texts without a part go.
function keepHistory(history: ReasonHist, text: string, via: ReasonPart[]) {
  if (history.seen.has(text)) {
    history.size -= text.length;
    history.seen.delete(text);
  }
  history.seen.set(text, via);
  history.size += text.length;
  for (const [keptText, keptParts] of history.seen) {
    if (history.size <= HISTORY_CHARS) break;
    if (keptParts.length || keptText === text) continue;
    history.seen.delete(keptText);
    history.size -= keptText.length;
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
// Keys in the field: Enter saves (Shift+Enter is a new line), Esc closes or takes two presses with text. Every other
// key is the field's own - digits included. Nothing while an input method composes. Esc on the popover's buttons
// ([접기], [닫기], [저장], [지우기]) is the field's Esc.
$('#doc').addEventListener('keydown', (event) => {
  const target = event.target as HTMLElement;
  if (
    event.key === 'Escape' &&
    !isReasonField(target) &&
    REASON_SESSION &&
    target &&
    target.closest &&
    target.closest('#doc .pv-pop') &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  ) {
    event.preventDefault();
    event.stopPropagation();
    hideTip();
    escapeReason('key');
    return;
  }
});
$('#doc').addEventListener('keydown', (event) => {
  const field = event.target;
  if (!isReasonField(field)) return;
  if (imeKey(event)) {
    if (imeTail(event)) event.preventDefault();
    return;
  } // the Enter that ended a composition adds no new line either
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault();
    event.stopPropagation();
    saveReason(field);
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    escapeReason('key');
  }
});
// While a popover is open, Tab and Shift+Tab keep to it and its line, from anywhere in either: past the last control
// (the popover's) the focus goes to the line's first, and before the first (the line's) to the popover's last. The
// DOM's next or previous stop is another page's line, whose focus would scroll the reading page away and close the
// popover, writing what is being edited.
$('#doc').addEventListener('keydown', (event) => {
  if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = event.target as HTMLElement,
    line = target && target.closest ? target.closest('#doc .pv') : null;
  const pop = line && line.querySelector(':scope>.pv-pop');
  if (!line || !pop) return;
  const vis = (x: Element) =>
    x instanceof HTMLElement && x.getClientRects().length > 0 && !(x as HTMLButtonElement).disabled;
  const all = [...line.querySelectorAll('a,button,textarea,[tabindex="0"]')].filter(vis);
  if (all.length < 2) return;
  if (!event.shiftKey && target === all[all.length - 1]) {
    event.preventDefault();
    (all[0] as HTMLElement).focus({ preventScroll: true });
  } else if (event.shiftKey && target === all[0]) {
    event.preventDefault();
    (all[all.length - 1] as HTMLElement).focus({ preventScroll: true });
  }
});
// The field's focus changes what it says (the keys). The popover stays open while the focus is anywhere inside it - Tab
// from the field to its buttons included - and an empty one closes when the focus leaves it for somewhere else (a press
// on its own buttons never closes it, even where a press does not move the focus).
let POPOVER_PRESS_AT = 0; // performance.now() of the last press inside a popover
$('#doc').addEventListener(
  'pointerdown',
  (event) => {
    const target = event.target as HTMLElement;
    if (target && target.closest && target.closest('.pv-pop')) POPOVER_PRESS_AT = performance.now();
  },
  true,
);
$('#doc').addEventListener('focusin', (event) => {
  if (!isReasonField(event.target) || !REASON_SESSION) return;
  REASON_SESSION.escArm = '';
  refillLine(REASON_SESSION.page);
});
$('#doc').addEventListener('focusout', (event) => {
  const target = event.target as HTMLElement,
    pop = target && target.closest ? target.closest('.pv-pop') : null;
  if (!pop) return;
  const rel = event.relatedTarget as Node | null;
  if (rel && pop.contains(rel)) return;
  setTimeout(() => {
    const session = REASON_SESSION;
    if (
      !session ||
      pop.getAttribute('data-id') !== 's' + session.sid ||
      !pop.isConnected ||
      pop.contains(document.activeElement)
    )
      return;
    const field = findReasonField();
    if (
      field &&
      !field.disabled &&
      !field.value.trim() &&
      !session.writing &&
      performance.now() - POPOVER_PRESS_AT > 600
    ) {
      closeReasonPopover(false);
      return;
    }
    refillLine(session.page);
  }, 0);
});
// The second Esc after a first one from the field (the focus is then on the PDF area): it drops the draft - unless
// something on top answers Esc first (a dialog, a popover, the composer, an edit or a reply).
function dropOnSecondEsc(event: KeyboardEvent) {
  if (
    event.key !== 'Escape' ||
    event.defaultPrevented ||
    !REASON_SESSION ||
    REASON_SESSION.escArm !== 'key' ||
    typingNow()
  )
    return;
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden ||
    EDITOR.current ||
    REPLY
  )
    return;
  event.preventDefault();
  event.stopImmediatePropagation();
  escapeReason('key');
}
document.addEventListener('keydown', dropOnSecondEsc);
// Enter on the pages - the focus on the PDF area, the page itself or nothing - opens the reading page's reason popover
// with the focus, for the person's own open current verdict there ('Enter 이유 쓰기' on its line). A control's own
// Enter stays its own, and so does anything on top (a dialog, a popover, the composer, an edit or a reply). Not while
// the pages are still gliding to where a jump sends them (isAutoScrolling): the reading page is not yet the one asked
// for. While that page's save is still out the popover opens bound to it (openPendingReason) - a key and Enter at once
// is one intent.
function openReasonOnEnter(event: KeyboardEvent) {
  if (
    event.key !== 'Enter' ||
    event.defaultPrevented ||
    imeKey(event) ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.shiftKey ||
    event.repeat
  )
    return;
  const target = event.target as HTMLElement | null,
    area = $('#left');
  // On a control of the line whose digit key's save is out the Enter is that intent too: the focus may rest on any of
  // them.
  const line =
      !!target && !!target.closest && !target.closest('.pv-pop')
        ? (target.closest('#doc .pv') as HTMLElement | null)
        : null,
    page = line ? Number(line.dataset.page) || 0 : 0;
  if (page && KEY_SAVE_OUT.has(pageLineSlot(page)) && page === pageUnderReadingLine()) {
    event.preventDefault();
    event.stopImmediatePropagation();
    openPendingReason(page);
    return;
  }
  if (!(
    target === document.body ||
    target === area ||
    target === $('#doc') ||
    (!!target && !!target.closest && !!target.closest('#doc .pg'))
  ))
    return;
  openReadingReason(event);
}
// Enter taken as pressed on the pages (openReasonOnEnter, or one on an off-screen line's control, stopOffPageKey): the
// reading page's reason - its popover, or a pending one while its save is out.
function openReadingReason(event: KeyboardEvent) {
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden ||
    EDITOR.current ||
    REPLY ||
    !canVerdict()
  )
    return;
  const page = pageUnderReadingLine();
  if (!page || !pageTakesVerdict(page)) return;
  if (SAVING_LINES.has(pageLineSlot(page))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    openPendingReason(page);
    return;
  } // the save is out: the Enter is the intent to write
  const cur = currentLineVerdict(page);
  if (!cur || !canCancelVerdict(cur)) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (isAutoScrolling()) {
    sayGliding();
    return;
  }
  openReason(page, true);
}
document.addEventListener('keydown', openReasonOnEnter);
// After a focused reason field went from under the person (its verdict taken back elsewhere), the keys they go on
// typing are not verdict keys: one would save a verdict they never chose (and the text is in its page's draft). It
// lasts until they press something on purpose - a press of the pointer, Esc, or opening the popover again.
let KEY_GUARD = false;
// Whether a verdict key falls under that guard - said once on the status line when it does.
function isKeyGuarded(event: KeyboardEvent) {
  if (!KEY_GUARD) return false;
  event.preventDefault();
  lineNote(
    '이유 칸이 닫혀 숫자를 판정으로 받지 않았습니다 — Esc를 누르거나 쪽을 누른 뒤 다시 누릅니다',
    NOTICE_KIND.INFO,
    null,
    { source: 'verdict-key-guard', life: NOTICE_LIFE.TIMER },
  );
  return true;
}
addEventListener(
  'pointerdown',
  () => {
    KEY_GUARD = false;
  },
  true,
);
addEventListener(
  'keydown',
  (event) => {
    if (event.key === 'Escape') KEY_GUARD = false;
  },
  true,
);
// A popover's buttons and the line's reason (main.ts).
function actOnReason(control: HTMLElement) {
  const act = control.dataset.act,
    line = control.closest('.pv'),
    page = Number(line && line.getAttribute('data-page')) || 0;
  if (act === 'pv-reason-open') {
    openReason(page, true);
    return;
  }
  if (act === 'pv-reason-close') {
    escapeReason('btn');
    return;
  }
  if (act === 'pv-reason-clear') {
    clearReason();
    return;
  }
  if (act === 'pv-reason-fold') {
    foldReason();
    return;
  }
  if (act === 'pv-reason-reapply') {
    writeOverNewer();
    return;
  }
  if (act === 'pv-reason-see') {
    if (REASON_SESSION) gotoPinRef(REASON_SESSION.id, true);
    return;
  }
  const field = findReasonField();
  if (act === 'pv-reason-save' && field) saveReason(field);
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
// Leaving the page (a reload, closing the tab, another address) with a reason not written yet asks first. The draft is
// kept either way for this tab: a reload brings it back.
addEventListener('beforeunload', (event) => {
  if (!hasUnsavedDrafts()) return;
  event.preventDefault();
  event.returnValue = '';
});
// Sets COMPOSING_FIELD, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setComposingField<Value extends typeof COMPOSING_FIELD>(value: Value): Value {
  COMPOSING_FIELD = value;
  return value;
}
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
export {
  LAST_KEY_SAVE,
  REASON_SESSION,
  WITHDRAWN_PINS,
  isComposingNow,
  focusLine,
  isReasonField,
  isKeyGuarded,
  actOnReason,
  fillReasonField,
  refocusAfterLines,
  followSaveWithReason,
  afterComposition,
  hasUnsavedReason,
  openReadingReason,
  findReasonField,
  restoreReasonFocus,
  holdReasonFocus,
  inlineReason,
  leaveReason,
  isReasonOpenOn,
  reasonPopoverHtml,
  reviveReason,
  settleDetachedReason,
  syncReasonSession,
  keepUnboundReason,
  bringBackReason,
  placeFailedCancelDraft,
  settleFailedCancelDraft,
  getDraft,
  putDraft,
  setComposingField,
  setKeyGuard,
  setReasonSession,
};
