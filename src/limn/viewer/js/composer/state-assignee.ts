import { ASSIGNEE_AGENT } from '../app/rules-tables.ts';

// The composer panel's assignee: the author's pick (touched) or, until there is one, the default re-chosen every time
// the note changes. A pick whose person left the note is dropped. Both assignee rows read the note with the hints the
// save carries (mentionHints), so they offer exactly whom the server tags.
const ASSIGN_NEW = { v: ASSIGNEE_AGENT, touched: false };
// Each sets one field of ASSIGN_NEW for another module that changes it (ADR-0042 D1): the assignment, nothing more.
function setAssignNewValue(value: typeof ASSIGN_NEW.v) {
  ASSIGN_NEW.v = value;
}
function setAssignNewTouched(value: boolean) {
  ASSIGN_NEW.touched = value;
}

export { ASSIGN_NEW, setAssignNewValue, setAssignNewTouched };
