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
import { ASSIGN_NEW, renderAssignNew } from './input-mentions.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
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
function draftRestore(record: ReturnType<typeof draftRecord>, doc: string | null, build: string) {
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
  ASSIGN_NEW.v = ASSIGNEE_AGENT;
  ASSIGN_NEW.touched = false;
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
  let record = null as any,
    raw: string | null = null;
  const key = META ? draftKey(META.label, DOC) : null;
  DRAFT.origin = null;
  try {
    raw = key ? sessionStorage.getItem(key) : null;
    record = JSON.parse(raw || 'null');
  } catch (error) {
    record = null;
  }
  const kept = draftRestore(record, DOC, META && META.pages_build),
    picked = !!COMPOSE.current && COMPOSE.current.doc === DOC;
  const how = kept && picked ? (String(record.note || '').trim() && !$('#note').value.trim() ? 'note' : null) : kept;
  DRAFT.key = record ? key : null;
  DRAFT.ready = true;
  if (!how) {
    syncDraft();
    return;
  }
  const noteField = $('#note');
  noteField.value = record.note || '';
  noteField._mentions = record.mentions && record.mentions.length ? new Set(record.mentions) : null;
  setKind(record.kind);
  Object.assign(ASSIGN_NEW, record.assign || {});
  if (record.sg && !picked) Object.assign(SUGGEST_DRAFT, suggestCopy(record.sg));
  renderAssignNew();
  autoGrow(noteField);
  if (picked) saveDraftSoon();
  if (how === 'full') {
    const keptPick: ComposerSelection = record.cur,
      page = document.getElementById('p' + keptPick.page);
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
