// ------------------------------------------------ Access management: the screen's own state
// The owner's access screen draws from the last answer of GET /api/access; nothing else is kept between draws except
// what the owner has chosen and not sent yet.
import { ROLE } from '../app/rules-tables.ts';

/** The last answer of GET /api/access, or null before the first read (and for anyone who is not the owner). */
let ACCESS: AccessView | null = null;
function setAccess(view: AccessView | null) {
  ACCESS = view;
}
/** Whether the screen shows the transition view (what the switch to managed admission would do) rather than the list. */
let TRANSITION_OPEN = false;
function setTransitionOpen(open: boolean) {
  TRANSITION_OPEN = open;
}
/** Whether the screen shows what turning management off would do (the same comparison, the other way) rather than the
 * list. Turning off widens admission, so it is shown and only then sent. */
let OFF_OPEN = false;
function setOffOpen(open: boolean) {
  OFF_OPEN = open;
}
/** The logins of the transition's settable rows the owner has checked - who keeps getting in after the switch. */
const CHECKED = new Set<string>();
/** The logins the owner has checked or unchecked by hand on the transition screen since it was last set up. A read
 * that lands while they are choosing fills in rows the screen did not offer before, and this is what keeps it from
 * touching a row they have already decided: their answer is theirs until the screen is set up again. */
const TOUCHED = new Set<string>();
/** The role picked for a tailnet candidate that is not a member yet, by login ('viewer' unless the owner changed it). */
const PICKED_ROLE = new Map<string, string>();
/** The role picked for a tailnet candidate who is not a member yet. */
function pickedRole(login: string) {
  return PICKED_ROLE.get(login) || ROLE.VIEWER;
}
/** What the "someone the list does not show" row holds, kept across draws so a role pressed beside it keeps the login. */
let TYPED_LOGIN = '';
function setTypedLogin(text: string) {
  TYPED_LOGIN = text;
}
/** The role picked in the "someone the list does not show" row. */
let TYPED_ROLE: string = ROLE.VIEWER;
function setTypedRole(role: string) {
  TYPED_ROLE = role;
}
/** What the server said the last press of POST /api/access/managed did - the switch to managed admission or the turn
 * back off - with the logins the preview had counted as newly let in; null until a press went through, and again once
 * the owner changes anything or reopens the screen. */
let RESULT: { done: ManagedChanged; previewed: string[] } | null = null;
function setResult(result: { done: ManagedChanged; previewed: string[] } | null) {
  RESULT = result;
}
/** Whether the screen on show is older than the server: a write went through and the read that should have followed it
 * failed. While it is, the lists are not drawn - only what the server said and why they are missing. */
let STALE = false;
function setStale(stale: boolean) {
  STALE = stale;
}
/** Why the last change was refused, drawn at the top of the screen; '' when the last one went through. A banner would
 * stand behind the modal dialog (and under a phone's sheet), where the owner cannot read it. */
let NOTE = '';
function setNote(text: string) {
  NOTE = text;
}
export {
  ACCESS,
  CHECKED,
  NOTE,
  OFF_OPEN,
  PICKED_ROLE,
  RESULT,
  STALE,
  TOUCHED,
  TRANSITION_OPEN,
  TYPED_LOGIN,
  TYPED_ROLE,
  pickedRole,
};
export { setAccess, setNote, setOffOpen, setResult, setStale, setTransitionOpen, setTypedLogin, setTypedRole };
