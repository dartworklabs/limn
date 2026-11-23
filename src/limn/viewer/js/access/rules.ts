// ------------------------------------------------ Access management: what the screen may offer, as pure decisions
// The server decides who may change what (security/access.py, access_service.py); this only keeps the controls it
// would refuse out of the page (which roles it offers is access/view.ts: the role table is the app's).
/** A member's last visit, short ('11-22 18:02'), or '—' when none was recorded. Pure. */
function seenText(member: AccessMember) {
  const seen = String(member.last_seen || '');
  return seen ? seen.slice(5, 16) : '—';
}
/** The transition rows the owner has checked, among the rows that may be checked. Pure. */
function checkedOf(transition: AccessTransition, checked: ReadonlySet<string>) {
  return transition.settable.filter((member) => checked.has(member.login));
}
/** Who gets in after the switch: the checked rows and the fixed ones (an owner's, an agent's), which the switch keeps.
 * Pure. */
function admittedAfter(transition: AccessTransition, checked: ReadonlySet<string>): AccessMember[] {
  return [...transition.fixed, ...checkedOf(transition, checked)];
}
/** Who the switch would let in who does not get in today - the prediction of the server's `newly_admitted`, which
 * counts the same way (a fixed row --allow refuses today is let in too). Pure. */
function newlyAdmitted(transition: AccessTransition, checked: ReadonlySet<string>) {
  const today = new Set(transition.admitted_today);
  return admittedAfter(transition, checked).filter((member) => !today.has(member.login));
}
/** How many people keep coming in after the switch. Pure. */
function keptCount(transition: AccessTransition, checked: ReadonlySet<string>) {
  const today = new Set(transition.admitted_today);
  return admittedAfter(transition, checked).filter((member) => today.has(member.login)).length;
}
/** Who gets in today, as rows to read: the settable and fixed rows the server says the run's arguments admit. Pure. */
function admittedRows(transition: AccessTransition): AccessMember[] {
  const today = new Set(transition.admitted_today);
  return [...transition.settable, ...transition.fixed].filter((member) => today.has(member.login));
}

/** These logins as rows to read: the member row where the instance has one, and the login alone where it does not (a
 * login only --allow names, which has no row until the switch makes one). A row with no role shows none. Pure. */
function loginRows(logins: readonly string[], members: readonly AccessMember[]): AccessMember[] {
  const byLogin = new Map(members.map((member) => [member.login, member]));
  return logins.map((login) => byLogin.get(login) || { login, name: '', role: '' });
}
/** How many people keep coming in after management is turned off: those who get in now and still would. The server
 * counted the two columns, so this only subtracts. Pure. */
function offKeptCount(preview: AccessOffPreview) {
  return preview.admitted_now.length - preview.no_longer_admitted.length;
}

/** Whether two lists name the same logins, in any order. Pure. */
function sameLogins(first: readonly string[], second: readonly string[]) {
  return first.length === second.length && [...first].sort().join('\n') === [...second].sort().join('\n');
}

export {
  sameLogins,
  admittedAfter,
  admittedRows,
  checkedOf,
  keptCount,
  loginRows,
  newlyAdmitted,
  offKeptCount,
  seenText,
};
