// ----------------------------------------------- The composer draft, kept per tab (docs/handbook/viewer.md §패널 정리)
// A draft - the composer's selection, box, note, kind, assignee and suggested edit, or a note waiting for the next pick
// - is written to sessionStorage on every edit (debounced 300ms, flushed when the page hides) under draftKey(label,
// document), so leaving the page - a reload, the back gesture past the sheet - never loses it, and this tab's next boot
// restores it (restoreDraft). Saving clears it; a discard clears it once its undo window is over (DRAFT.holds has that
// document's undo). Only this tab sees it. The tab owns the debounce timer and the active document's draft key; a
// discard's undo holds its own document's key.
import {
  DOC,
  KIND_NEW,
  LAYOUT,
  META,
  setSnipOpen,
  COMPOSE,
  setComposeBox,
  setComposeCurrent,
  setComposeIntent,
} from '../app/state.ts';
import { NOTICES, lineNote } from '../platform/notices.ts';
import { applySide, setSide } from '../layout/flow.ts';
import { drawBox, newBox, pendingBadge, revealBox } from '../pdf/input-selection.ts';
import { relevelForLineView } from '../markdown/view.ts';
import { cancelSelection, discardSelection, recomputeOverlap, renderComposer, setKind } from './flow-pick.ts';
import { ASSIGN_NEW, setAssignNewValue, setAssignNewTouched, renderAssignNew } from './input-mentions.ts';
import { NOTICE_KIND, NOTICE_LIFE, isRecord } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { ASSIGNEE_AGENT, REQUEST_KIND, LAYOUT_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { autoGrow } from './view-text.ts';
import { SUGGEST_DRAFT, suggestClear, suggestCopy } from './state-suggest.ts';
// A discarded draft kept until its undo note leaves: the note, the stored draft's key and the bytes it held.
interface HeldDraft {
  note: Notice;
  key: string | null;
  value: string | null;
}
interface DraftState {
  timer: ReturnType<typeof setTimeout> | 0;
  ready: boolean;
  holds: Map<string | null, HeldDraft>;
  key: string | null;
  origin: { key: string | null; value: string | null; current: ComposerSelection | null } | null;
}
const DRAFT: DraftState = {
  timer: 0,
  ready: false,
  holds: new Map(),
  key: null,
  origin: null,
};
// Keep a discarded draft until its undo (note, on the status line) leaves, unless a newer draft replaced it first.
function holdDraftUntil(note: Notice) {
  let value: string | null = null;
  try {
    if (DRAFT.key) value = sessionStorage.getItem(DRAFT.key);
  } catch (error) {}
  const held = { note, key: DRAFT.key, value };
  if (held.key) DRAFT.holds.set(held.key, held);
  note.gone = () => {
    if (!held.key || DRAFT.holds.get(held.key) !== held) return;
    DRAFT.holds.delete(held.key);
    if (DRAFT.key === held.key && DRAFT.ready && draftRecord()) {
      syncDraft();
      return;
    } // a restored or newer active draft wins, even with identical bytes
    if (held.key && held.value) {
      try {
        if (sessionStorage.getItem(held.key) === held.value) {
          sessionStorage.removeItem(held.key);
          if (DRAFT.key === held.key) DRAFT.key = null;
        }
      } catch (error) {}
    }
  };
}
// The storage key of a draft: one per instance label and document.
function draftKey(label: string, doc: string | null) {
  return 'limnDraft:' + encodeURIComponent(label || '') + ':' + doc;
}
// What a stored draft brings back on this document and build: 'full' (selection, box, note) when its box was drawn on
// this build, 'note' (the note waits for the next pick) when the build changed or no selection had come back yet, null
// for nothing to keep, another document, or another record version.
function draftRestore(record: StoredDraft | null, doc: string | null, build: string | null) {
  if (!record || record.v !== 1 || record.doc !== doc) return null;
  if (record.cur && record.build === build) return 'full';
  return String(record.note || '').trim() ? 'note' : null;
}
// The draft on screen now, or null: the open composer (with its pick, or a note while the pick is still running) or a
// note kept in the hidden composer for the next pick.
function draftRecord() {
  const noteField = $('#note'),
    open = !$('#composer').hidden,
    note = noteField.value,
    current = open ? COMPOSE.current : null;
  if (!current && !note.trim()) return null;
  return {
    v: 1,
    doc: (current && current.doc) || DOC,
    build: (current && current.pdf_build) || (META && META.pages_build) || '',
    cur: current,
    note,
    mentions: noteField._mentions ? Array.from(noteField._mentions) : [],
    kind: KIND_NEW,
    assign: { v: ASSIGN_NEW.v, touched: ASSIGN_NEW.touched },
    sg: suggestCopy(SUGGEST_DRAFT),
  };
}
// A draft as draftRecord writes it, read back from sessionStorage (storedDraft), its selection (cur) read by
// draftSelection.
interface StoredDraft {
  v: 1;
  doc: string | null;
  build: string;
  cur: ComposerSelection | null;
  note: string;
  mentions: string[];
  kind: string | undefined;
  assign: { v: string; touched: boolean } | null;
  sg: SuggestDraft | null;
}
// The stored draft in value (parsed from sessionStorage), or null for a value that is no draft of this record version,
// of no document, or without its note. The record's form has not changed since drafts were first kept, so every draft a
// tab can hold is read; sg is absent from drafts written before suggested edits. What is not as draftRecord writes it
// is left out and the note still comes back: a selection or build (the note then waits for the next pick, as after a
// rebuild), @-tag hints (none), kind (the default), assignee (as it is), suggested edit (none). Pure.
function storedDraft(value: unknown): StoredDraft | null {
  if (!isRecord(value) || value.v !== 1) return null;
  const { doc, build, cur, note, mentions, kind, assign } = value;
  if ((typeof doc !== 'string' && doc !== null) || typeof note !== 'string') return null;
  // a selection that cannot be placed again leaves the note to wait for the next pick
  const selection = typeof build === 'string' ? draftSelection(cur) : null;
  return {
    v: 1,
    doc,
    build: selection && typeof build === 'string' ? build : '',
    cur: selection,
    note,
    mentions: Array.isArray(mentions) ? mentions.filter((login) => typeof login === 'string') : [],
    kind: typeof kind === 'string' ? kind : undefined,
    assign:
      isRecord(assign) && typeof assign.v === 'string' && typeof assign.touched === 'boolean'
        ? { v: assign.v, touched: assign.touched }
        : null,
    sg: isSuggestDraft(value.sg) ? value.sg : null,
  };
}
// Whether a stored value is a suggested edit's draft as suggestCopy writes it. Pure.
function isSuggestDraft(value: unknown): value is SuggestDraft {
  if (!isRecord(value)) return false;
  const { on, text, base, file, had, current, reading, fail } = value;
  return (
    typeof on === 'boolean' &&
    typeof text === 'string' &&
    (typeof base === 'string' || base === null) &&
    (typeof file === 'string' || file === null) &&
    typeof value.lo === 'number' &&
    typeof value.hi === 'number' &&
    (had === null || (isRecord(had) && typeof had.base === 'string' && typeof had.text === 'string')) &&
    (current === null ||
      (isRecord(current) &&
        typeof current.text === 'string' &&
        (typeof current.file === 'string' || current.file === null) &&
        typeof current.lo === 'number' &&
        typeof current.hi === 'number')) &&
    typeof reading === 'string' &&
    fail === null
  );
}
// Whether value is a list of what each item's guard accepts. Pure.
function isListOf<Item>(value: unknown, isItem: (item: unknown) => item is Item): value is Item[] {
  return Array.isArray(value) && value.every(isItem);
}
// Whether value is a string, a number: the item guards of isListOf. Pure.
function isString(value: unknown): value is string {
  return typeof value === 'string';
}
function isNumber(value: unknown): value is number {
  return typeof value === 'number';
}
// Whether a stored field is absent or what guard accepts. Pure.
function absentOr<Field>(value: unknown, guard: (value: unknown) => value is Field): value is Field | undefined {
  return value === undefined || guard(value);
}
// Whether a stored field is absent, null or what guard accepts. Pure.
function absentNullOr<Field>(
  value: unknown,
  guard: (value: unknown) => value is Field,
): value is Field | null | undefined {
  return value === undefined || value === null || guard(value);
}
// Whether value is a figure element as a pick names it (el, a rung's el, the composer's elSel). Pure.
function isPinElement(value: unknown): value is PinElement {
  if (!isRecord(value)) return false;
  const { impl } = value;
  return (
    typeof value.id === 'string' &&
    isListOf(value.path, isString) &&
    absentOr(value.label, isString) &&
    absentOr(value.part, isString) &&
    (impl === undefined ||
      (isRecord(impl) &&
        typeof impl.file === 'string' &&
        typeof impl.lo === 'number' &&
        typeof impl.hi === 'number')) &&
    absentOr(value.frac, (frac) => isListOf(frac, isNumber))
  );
}
// Whether value is a ladder rung as a pick's answer, a drawn document's ladder or a text document's writes it. Pure.
function isRung(value: unknown): value is Rung {
  if (!isRecord(value)) return false;
  return (
    typeof value.level === 'string' &&
    typeof value.lo === 'number' &&
    typeof value.hi === 'number' &&
    typeof value.n === 'number' &&
    typeof value.label === 'string' &&
    typeof value.snippet === 'string' &&
    absentNullOr(value.env, isString) &&
    absentOr(value.el, isPinElement) &&
    absentOr(value.merged, (merged) => isListOf(merged, isString)) &&
    absentNullOr(value.score, isNumber)
  );
}
// Whether value is an open pin a selection overlaps, as a pick's answer and overlapsFor write it. Pure.
function isPickOverlap(value: unknown): value is PickOverlap {
  return (
    isRecord(value) &&
    typeof value.id === 'number' &&
    typeof value.lo === 'number' &&
    typeof value.hi === 'number' &&
    typeof value.rel === 'string'
  );
}
// Whether value holds what the composer chooses on a selection as it writes it (scope, env, elSel, rel). Pure.
function hasComposerChoice(value: Record<string, unknown>) {
  return (
    absentNullOr(value.scope, isString) &&
    absentNullOr(value.env, isString) &&
    absentNullOr(value.elSel, isPinElement) &&
    absentOr(value.rel, (rel) => isListOf(rel, isPickOverlap))
  );
}
// Whether value is lines picked on a drawn Markdown or text document as markdown/view.ts pickLines writes them,
// with the rung, lines and snippet the composer chose since. Pure.
function isLinePick(value: unknown): value is LinePick {
  if (!isRecord(value)) return false;
  return (
    value.kind === 'lines' &&
    value.page === undefined &&
    (value.doc === null || typeof value.doc === 'string') &&
    typeof value.file === 'string' &&
    typeof value.name === 'string' &&
    typeof value.lo === 'number' &&
    typeof value.hi === 'number' &&
    typeof value.raw_lo === 'number' &&
    typeof value.raw_hi === 'number' &&
    value.score === null &&
    value.warn === null &&
    typeof value.snippet === 'string' &&
    isListOf(value.levels, isRung) &&
    typeof value.default_level === 'string' &&
    typeof value.n_lines === 'number' &&
    typeof value.quote === 'string' &&
    isListOf(value.overlaps, isPickOverlap) &&
    hasComposerChoice(value)
  );
}
// Whether value is a box in PDF points (an offline drag's rect). Pure.
function isPointBox(value: unknown): value is { x0: number; y0: number; x1: number; y1: number } {
  return (
    isRecord(value) &&
    typeof value.x0 === 'number' &&
    typeof value.y0 === 'number' &&
    typeof value.x1 === 'number' &&
    typeof value.y1 === 'number'
  );
}
// Whether value is a drag on the PDF as the composer keeps it: POST /api/pick's answer (every release has sent name,
// page, kind, warn, frac, quote, overlaps and pdf_build), or offlinePick's region, with what the composer chose since.
// Pure.
function isPagePick(value: unknown): value is PagePick {
  if (!isRecord(value)) return false;
  return (
    typeof value.name === 'string' &&
    typeof value.page === 'number' &&
    typeof value.kind === 'string' &&
    typeof value.warn === 'string' &&
    isListOf(value.frac, isNumber) &&
    typeof value.quote === 'string' &&
    isListOf(value.overlaps, isPickOverlap) &&
    typeof value.pdf_build === 'string' &&
    absentOr(value.file, isString) &&
    absentOr(value.lo, isNumber) &&
    absentOr(value.hi, isNumber) &&
    absentOr(value.raw_lo, isNumber) &&
    absentOr(value.raw_hi, isNumber) &&
    absentOr(value.via, isString) &&
    absentNullOr(value.score, isNumber) &&
    absentOr(value.fill, isNumber) &&
    absentOr(value.rival, (rival) => typeof rival === 'boolean') &&
    absentOr(value.n_lines, isNumber) &&
    absentOr(value.snippet, isString) &&
    absentOr(value.levels, (levels) => isListOf(levels, isRung)) &&
    absentOr(value.default_level, isString) &&
    absentOr(value.el, isPinElement) &&
    absentOr(value.path_names, (names) => isListOf(names, isString)) &&
    absentOr(value.doc, isString) &&
    absentOr(value.view_only, (only) => typeof only === 'boolean') &&
    absentOr(value.pdf, isString) &&
    absentOr(value.n_chars, isNumber) &&
    absentOr(value.offline, (offline) => typeof offline === 'boolean') &&
    absentNullOr(value.rect, isPointBox) &&
    hasComposerChoice(value)
  );
}
// An offline drag's region as the releases before offlinePick took the region answer's shape wrote it (null for
// the lines, the name and the element it has none of, pdf_build absent when the drag named none), as offlinePick
// writes it now, field for field in its order; null for anything else. Pure.
function earlierOfflinePick(value: unknown): PagePick | null {
  if (!isRecord(value) || value.offline !== true || value.kind !== 'region') return null;
  const { page, frac, quote, name, pdf, pdf_build: build, doc, rect, overlaps, scope, env, warn, snippet } = value;
  if (
    typeof page !== 'number' ||
    !isListOf(frac, isNumber) ||
    typeof quote !== 'string' ||
    !absentNullOr(name, isString) ||
    !absentNullOr(pdf, isString) ||
    !absentNullOr(build, isString) ||
    !absentNullOr(doc, isString) ||
    !isPointBox(rect) ||
    !isListOf(overlaps, isPickOverlap) ||
    !absentNullOr(scope, isString) ||
    !absentNullOr(env, isString) ||
    !absentNullOr(warn, isString) ||
    !absentNullOr(snippet, isString)
  )
    return null;
  return {
    kind: 'region',
    page,
    frac,
    quote,
    name: name || '',
    pdf: pdf || undefined,
    pdf_build: build || '',
    doc: doc || undefined,
    offline: true,
    rect,
    levels: [],
    overlaps,
    scope: scope || null,
    env: env || null,
    elSel: null,
    warn: warn || '',
    snippet: snippet || '',
    n_lines: 0,
  };
}
// The selection a stored draft keeps (draftRecord's cur, COMPOSE.current when it was written): lines of a drawn
// document or a drag on the PDF as the composer wrote it, the same value, or an earlier release's offline drag in
// today's form; null for anything else (the note then waits for the next pick). Pure.
function draftSelection(value: unknown): ComposerSelection | null {
  if (isLinePick(value) || isPagePick(value)) return value;
  return earlierOfflinePick(value);
}
// Every edit schedules a write (no-op until the boot restore has run, so booting never overwrites the stored draft).
function saveDraftSoon() {
  if (!DRAFT.ready) return;
  clearTimeout(DRAFT.timer);
  DRAFT.timer = setTimeout(syncDraft, 300);
}
// Writes the draft now, or removes it when there is nothing to keep - unless a discard's undo still holds it.
function syncDraft() {
  clearTimeout(DRAFT.timer);
  DRAFT.timer = 0;
  if (!DRAFT.ready || !META) return;
  const record = draftRecord();
  try {
    if (record) {
      const key = draftKey(META.label, record.doc);
      DRAFT.holds.delete(key); // a newer draft replaces a discarded one
      sessionStorage.setItem(key, JSON.stringify(record));
      DRAFT.key = key;
      return;
    }
    const held = DRAFT.holds.get(DRAFT.key);
    if (held && NOTICES.has(held.note.n)) return;
    if (DRAFT.key) sessionStorage.removeItem(DRAFT.key);
    DRAFT.key = null;
  } catch (error) {}
}
// Bind an in-flight pin save to the exact stored draft it sent; later documents and selections own their own records.
function savedDraftSnapshot() {
  syncDraft();
  if (!DRAFT.key) return null;
  try {
    return { doc: DOC, key: DRAFT.key, value: sessionStorage.getItem(DRAFT.key) };
  } catch (error) {
    return null;
  }
}
// A returned visit may clear the original draft only while its restored selection and every unsaved field still match
// the submitted record.
function restoredDraftOwns(snapshot: ReturnType<typeof savedDraftSnapshot>) {
  const origin = DRAFT.origin;
  if (
    !snapshot ||
    !snapshot.value ||
    !origin ||
    DOC !== snapshot.doc ||
    DRAFT.key !== snapshot.key ||
    origin.key !== snapshot.key ||
    origin.value !== snapshot.value ||
    origin.current !== COMPOSE.current
  )
    return false;
  const record = draftRecord();
  if (!record || JSON.stringify(record) !== snapshot.value) return false;
  try {
    return sessionStorage.getItem(snapshot.key) === snapshot.value;
  } catch (error) {
    return false;
  }
}
// A successful save may discard its parked draft only while that record is unchanged and its document is away.
function clearSavedDraft(snapshot: ReturnType<typeof savedDraftSnapshot>) {
  if (!snapshot || !snapshot.value || DOC === snapshot.doc) return;
  try {
    if (sessionStorage.getItem(snapshot.key) === snapshot.value) sessionStorage.removeItem(snapshot.key);
  } catch (error) {}
}
// Finish one document's draft before a switch; later debounce and pagehide callbacks must not write it under the next
// document.
function parkDraft() {
  syncDraft();
  clearTimeout(DRAFT.timer);
  DRAFT.timer = 0;
  DRAFT.ready = false;
  DRAFT.key = null;
  DRAFT.origin = null;
}
// Start the next document with its own note and assignment before restoring any stored draft for it.
function openDraftDoc() {
  const noteField = $('#note');
  noteField.value = '';
  noteField._mentions = null;
  setAssignNewValue(ASSIGNEE_AGENT);
  setAssignNewTouched(false);
  setKind(REQUEST_KIND.FIX);
  suggestClear();
  renderAssignNew();
  autoGrow(noteField);
  restoreDraft();
}
window.addEventListener('pagehide', syncDraft);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) syncDraft();
});
// Boot: brings back this tab's draft for the document on screen and says so on the status line with [버리기], until the
// next press elsewhere. A full restore redraws the box and opens a collapsed panel or sheet (not remembered); a
// note-only one leaves the note in the note field for the next pick. [버리기] is the usual discard (a full draft gets
// its undo; the draft goes once that window is over). A pick the person made on this document while the boot was still
// reading the pins (a Markdown document is drawn before they come) is newer than the kept one and stays: only the kept
// note comes into it, when its field is still empty, and the kept selection and suggested edit are dropped.
function restoreDraft() {
  let stored: unknown = null,
    raw: string | null = null;
  const key = META ? draftKey(META.label, DOC) : null;
  DRAFT.origin = null;
  try {
    raw = key ? sessionStorage.getItem(key) : null;
    stored = JSON.parse(raw || 'null');
  } catch (error) {
    stored = null;
  }
  const record = storedDraft(stored);
  const kept = draftRestore(record, DOC, META && META.pages_build),
    picked = !!COMPOSE.current && COMPOSE.current.doc === DOC;
  const how = kept && picked ? (record && record.note.trim() && !$('#note').value.trim() ? 'note' : null) : kept;
  DRAFT.key = stored ? key : null;
  DRAFT.ready = true;
  if (!how || !record) {
    syncDraft();
    return;
  }
  const noteField = $('#note');
  noteField.value = record.note;
  noteField._mentions = record.mentions.length ? new Set(record.mentions) : null;
  setKind(record.kind);
  if (record.assign) Object.assign(ASSIGN_NEW, record.assign);
  if (record.sg && !picked) Object.assign(SUGGEST_DRAFT, suggestCopy(record.sg));
  renderAssignNew();
  autoGrow(noteField);
  if (picked) saveDraftSoon();
  const keptPick = how === 'full' ? record.cur : null;
  if (keptPick) {
    const page = document.getElementById('p' + keptPick.page);
    if (page && Array.isArray(keptPick.frac)) {
      const box = newBox(page),
        frac = keptPick.frac;
      drawBox(box, frac[0], frac[1], frac[0] + frac[2], frac[1] + frac[3]);
      box.classList.add('pending');
      pendingBadge(box, '새 핀');
      setComposeBox(box);
    }
    setComposeCurrent(keptPick);
    setComposeIntent(COMPOSE.intent + 1);
    recomputeOverlap();
    setSnipOpen(false);
    $('#c-err').hidden = true;
    $('#c-body').hidden = false;
    $('#composer').hidden = false;
    renderComposer();
    DRAFT.origin = { key: key, value: raw, current: keptPick };
    setSide(true);
    applySide();
    if (LAYOUT !== LAYOUT_MODE.WIDE) revealBox(COMPOSE.box);
    if (isMarkdownDoc()) relevelForLineView();
  } // the Markdown surface's line view takes the kept lines as lines
  lineNote(
    how === 'full' || picked
      ? '작성 중이던 메모를 되살렸습니다'
      : '작성 중이던 메모를 되살렸습니다 — PDF가 바뀌어 자리를 다시 골라야 합니다',
    NOTICE_KIND.INFO,
    {
      label: '버리기',
      tip: '되살린 선택과 메모를 버립니다',
      fn: () => {
        if (!$('#composer').hidden) discardSelection();
        else {
          cancelSelection(true);
          syncDraft();
        }
      },
    },
    { life: NOTICE_LIFE.CLICK },
  );
}
export {
  clearSavedDraft,
  holdDraftUntil,
  openDraftDoc,
  parkDraft,
  restoreDraft,
  restoredDraftOwns,
  saveDraftSoon,
  savedDraftSnapshot,
  syncDraft,
};
