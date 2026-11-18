// ------------------------------------------------ The suggested edit's draft
// The composer's suggested edit (SUGGEST_DRAFT): an empty one, a copy to keep, and clearing it with its editor.
// composer/flow-suggest.ts draws and saves it.
import { $ } from '../platform/dom.ts';
/** A draft with nothing in it: off, empty, never filled. */
function suggestDraft(): SuggestDraft {
  return {
    on: false,
    text: '',
    base: null,
    file: null,
    lo: 0,
    hi: 0,
    had: null,
    current: null,
    reading: '',
    fail: null,
  };
}
const SUGGEST_DRAFT = suggestDraft(); // the composer's draft; an open edit card keeps its own (EditCard.sg)
// Sets the composer's draft's current text and place, for another module that changes it (ADR-0042 D1).
function setSuggestCurrent(value: SuggestDraft['current']) {
  SUGGEST_DRAFT.current = value;
}
/** A copy of a draft to keep (a discard's undo, the tab's stored draft): what it holds, without a read under way or its
 * failure. */
function suggestCopy(draft: SuggestDraft): SuggestDraft {
  return {
    ...draft,
    had: draft.had && { ...draft.had },
    current: draft.current && { ...draft.current },
    reading: '',
    fail: null,
  };
}
// Empties the composer's draft (a save, a discard without undo, another document) and its editor.
function suggestClear() {
  Object.assign(SUGGEST_DRAFT, suggestDraft());
  const editor = $('#c-sg-text');
  editor.value = '';
  editor.style.height = '';
}
/** Whether a draft holds a text other than the one it was filled from (a draft never filled is not edited). Pure. */
function suggestEdited(draft: SuggestDraft): boolean {
  return draft.base != null && draft.text !== draft.base;
}
// Whether the composer's draft is a suggestion a save would send, so its note may not join an overlapped pin instead
// ([덧붙이기] appends a note; the suggestion belongs to this selection's lines).
function suggestPending() {
  return SUGGEST_DRAFT.on && suggestEdited(SUGGEST_DRAFT);
}

export { suggestEdited, suggestPending, SUGGEST_DRAFT, suggestDraft, suggestCopy, suggestClear, setSuggestCurrent };
