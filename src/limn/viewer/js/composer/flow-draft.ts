// ----------------------------------------------- The composer draft, kept per tab (docs/handbook/viewer.md §패널 정리)
// A draft - the composer's selection, box, note, kind, assignee and suggested edit, or a note waiting for the next pick
// - is written to sessionStorage on every edit (debounced 300ms, flushed when the page hides) under draftKey(label,
// document), so leaving the page - a reload, the back gesture past the sheet - never loses it, and this tab's next boot
// restores it (restoreDraft). Saving clears it; a discard clears it once its undo window is over (DRAFT.holds has that
// document's undo). Only this tab sees it. The tab owns the debounce timer and the active document's draft key; a
// discard's undo holds its own document's key.
import { DOC, KIND_NEW, META, COMPOSE } from '../app/state.ts';
import { NOTICES } from '../platform/notices.ts';
import { ASSIGN_NEW } from './state-assignee.ts';
import { $ } from '../platform/dom.ts';
import { SUGGEST_DRAFT, suggestCopy } from './state-suggest.ts';
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
// Open the current document's stored record and track subsequent edits under its key.
function openStoredDraft() {
  let stored: unknown = null,
    raw: string | null = null;
  const key = META ? draftKey(META.label, DOC) : null;
  try {
    raw = key ? sessionStorage.getItem(key) : null;
    stored = JSON.parse(raw || 'null');
  } catch (error) {
    stored = null;
  }
  DRAFT.origin = null;
  DRAFT.key = stored ? key : null;
  DRAFT.ready = true;
  return { key, raw, stored };
}
// Keep the identity of a restored selection so a late save can recognize it.
function rememberRestoredDraft(key: string | null, value: string | null, current: ComposerSelection) {
  DRAFT.origin = { key, value, current };
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
document.addEventListener('visibilitychange', () => {
  if (document.hidden) syncDraft();
});
export {
  clearSavedDraft,
  holdDraftUntil,
  parkDraft,
  restoredDraftOwns,
  saveDraftSoon,
  savedDraftSnapshot,
  syncDraft,
  openStoredDraft,
  rememberRestoredDraft,
};
