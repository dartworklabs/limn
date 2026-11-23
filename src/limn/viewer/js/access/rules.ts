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

export { admittedAfter, admittedRows, checkedOf, keptCount, newlyAdmitted, seenText };
