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
  const editor = $('#c-sg-text') as HTMLTextAreaElement;
  editor.value = '';
  editor.style.height = '';
}
export { SUGGEST_DRAFT, suggestDraft, suggestCopy, suggestClear };
