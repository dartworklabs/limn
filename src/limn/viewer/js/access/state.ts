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
/** The logins of the transition's settable rows the owner has checked - who keeps getting in after the switch. */
const CHECKED = new Set<string>();
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
/** What the server said the last switch to managed admission did (POST /api/access/managed), with the logins the
 * preview had counted as newly let in; null until a switch went through, and again once the owner changes anything or
 * reopens the screen. */
let RESULT: { done: ManagedChanged; previewed: string[] } | null = null;
function setResult(result: { done: ManagedChanged; previewed: string[] } | null) {
  RESULT = result;
}
/** Why the last change was refused, drawn at the top of the screen; '' when the last one went through. A banner would
 * stand behind the modal dialog (and under a phone's sheet), where the owner cannot read it. */
let NOTE = '';
function setNote(text: string) {
  NOTE = text;
}
export { ACCESS, CHECKED, NOTE, PICKED_ROLE, RESULT, TRANSITION_OPEN, TYPED_LOGIN, TYPED_ROLE, pickedRole };
export { setAccess, setNote, setResult, setTransitionOpen, setTypedLogin, setTypedRole };
