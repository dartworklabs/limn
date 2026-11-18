// ------------------------------------------------ A verdict reason's drafts, kept per pin (sessionStorage)
import { META } from '../app/state.ts';
import { isRecord } from '../platform/tables.ts';
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
// A new reason's write whose answer was lost: text, sent against the pin's rev `rev`, would have made the note pre,
// then the stamp a note_append puts first when stamp ('(추가 12:30) ', the time the server's), then text, then post.
type ReasonTry = { text: string; rev: number; pre: string; stamp: boolean; post: string };

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
function draftStorageKey() {
  return 'limnReason:' + encodeURIComponent((META && META.label) || '');
}
// Every draft kept for this label, by key, as stored: each is read with parseDraft, and one it cannot read is kept as it
// is when the others are written back.
function readAllDrafts(): Record<string, unknown> {
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(draftStorageKey()) || 'null');
    return isRecord(stored) && stored.v === DRAFT_VERSION && isRecord(stored.d) ? stored.d : {};
  } catch (error) {
    return {};
  }
}
function saveAllDrafts(drafts: Record<string, unknown>) {
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
function parseDraft(x: unknown): ReasonDraft | null {
  if (!isRecord(x)) return null;
  const { text, base } = x;
  return typeof text === 'string' && text.trim()
    ? {
        text,
        base: typeof base === 'string' ? base : '',
        rev: typeof x.rev === 'number' ? x.rev : -1,
        mode:
          x.mode === 'replace' || (x.mode !== 'add' && typeof base === 'string' && !!base.trim()) ? 'replace' : 'add',
        folded: !!x.folded,
        at: Number(x.at) || 0,
        tried: Array.isArray(x.tried) ? x.tried.filter(isReasonTry) : [],
        from: parseDraftParts(x.from, text),
      }
    : null;
}
// A kept draft's from as its parts that still fit its text (a string is one key whose part is the whole text).
function parseDraftParts(x: unknown, text: string): ReasonPart[] {
  if (typeof x === 'string') return x ? [{ k: x, s: 0, e: text.length, tried: [] }] : [];
  if (!Array.isArray(x)) return [];
  return x.flatMap((part: unknown) => {
    if (!isRecord(part)) return [];
    const { k: key, s: start, e: end } = part;
    return typeof key === 'string' &&
      !!key &&
      typeof start === 'number' &&
      Number.isInteger(start) &&
      typeof end === 'number' &&
      Number.isInteger(end) &&
      start >= 0 &&
      start < end &&
      end <= text.length
      ? [{ k: key, s: start, e: end, tried: Array.isArray(part.tried) ? part.tried.filter(isReasonTry) : [] }]
      : [];
  });
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
function isReasonTry(value: unknown): value is ReasonTry {
  return (
    isRecord(value) &&
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
export {
  readAllDrafts,
  saveAllDrafts,
  reasonDraftKey,
  parseDraft,
  normalizeReason,
  editParts,
  joinDrafts,
  cutWrittenParts,
  getDraft,
  putDraft,
  dropDraft,
  movedPart,
  ownText,
  draftMovedOff,
  moveDraft,
  draftsMovedOff,
  cutWrittenDrafts,
};
export type { ReasonDraft, ReasonPart, ReasonTry };
