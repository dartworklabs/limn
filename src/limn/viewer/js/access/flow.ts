// ------------------------------------------------ Access management: reading the screen and sending its changes
// Only an owner has this screen: /api/access is owner-only, and nothing of it (the entry in [더보기], the dialog's
// contents) is drawn for anyone else - not hidden, not there (docs/handbook/viewer.md §접근 관리).
import { api, isRefusal } from '../platform/api.ts';
import { NOTICE_HOST } from '../platform/tables.ts';
import { errText, translate } from '../platform/i18n.ts';
import { $, findMaybe } from '../platform/dom.ts';
import { isOwner } from '../app/state-people.ts';
import { showSheet } from '../layout/flow.ts';
import {
  ACCESS,
  CHECKED,
  STALE,
  PICKED_ROLE,
  TYPED_ROLE,
  pickedRole,
  setAccess,
  setNote,
  setResult,
  setStale,
  setTransitionOpen,
  setTypedLogin,
  setTypedRole,
} from './state.ts';
import { drawAccess } from './view.ts';
import { newlyAdmitted } from './rules.ts';
import './input.ts'; // Tab stays inside the open dialog

/** The text a confirmation of POST /api/access/managed must carry (security/http.py CONFIRM_MANAGED). */
const CONFIRM_MANAGED = 'manage access from the viewer';
/** The control the owner is on, by what it does and to whom: a draw makes its elements anew, so the focus is found
 * again by this. */
function controlKey(control: Element | null) {
  if (!(control instanceof HTMLElement) || !control.closest('#access-body')) return '';
  const { act, login, role, accCheck } = control.dataset;
  if (accCheck !== undefined) return 'check|' + accCheck;
  return act ? [act, login || '', role || ''].join('|') : control.id;
}
/** Draws the screen again and puts the focus back on the same control; when that control is gone (a row that was
 * pressed to leave, a transition that closed) the focus rests on the dialog, as when it opened. */
function redraw() {
  const key = controlKey(document.activeElement);
  const wasInside = !!key;
  const typed = findMaybe(document, '#acc-login', HTMLInputElement);
  if (typed) setTypedLogin(typed.value); // the login being typed survives the draw
  drawAccess();
  if (!wasInside) return;
  const again = [...document.querySelectorAll('#access-body [data-act],#access-body input')].find(
    (element) => controlKey(element) === key,
  );
  if (again instanceof HTMLInputElement && again.type === 'text') {
    again.focus();
    again.setSelectionRange(again.value.length, again.value.length);
  } else if (again instanceof HTMLElement) again.focus();
  else $('#access').focus({ preventScroll: true });
}
/** Says why a request failed inside the open dialog, where the owner can read it: a banner on the status line would stand
 * under the modal dialog (and under a phone's sheet). A refusal carries the server's words; an unreached server and any
 * other failure say so. */
function failed(what: string, error: unknown) {
  const body = error instanceof Error && 'data' in error ? error.data : null;
  const status = error instanceof Error && 'status' in error ? error.status : null;
  const why = errText(body) || (status ? 'HTTP ' + String(status) : translate('서버에 닿지 않습니다'));
  setNote(what + ' — ' + why);
  redraw();
}
/** Reads GET /api/access and draws the screen; the entry stays away until it answers, and for anyone but an owner
 * nothing is read. While the dialog is open a failed read is told inside it (and the screen is marked stale); before
 * that it is the status line's. Answers whether the read went through. */
async function loadAccess() {
  if (!isOwner()) return false;
  const dialogOpen = $('#access').open;
  const what = translate('접근 정보 읽기');
  try {
    const answer = await api('GET /api/access', { what, where: NOTICE_HOST.LINE, silent: dialogOpen });
    setAccess(answer.data);
  } catch (error) {
    if (dialogOpen) {
      setStale(true);
      failed(what, error);
    }
    return false;
  }
  const view = ACCESS;
  if (!view) return false;
  setStale(false);
  // The transition's checks start as the state the owner would keep: whoever gets in today.
  CHECKED.clear();
  const transition = view.transition;
  if (transition) for (const login of transition.admitted_today) CHECKED.add(login);
  redraw();
  return true;
}
/** Opens the access dialog, on the list. */
function openAccess() {
  if (!ACCESS) return;
  setTransitionOpen(false);
  setNote('');
  setResult(null);
  redraw();
  showSheet($('#access'));
  if (STALE) void loadAccess(); // the last read failed after a write: read again now that the owner is looking
}
/** Says why a write was refused, inside the screen itself: a banner over the panel would stand behind the modal dialog,
 * and under a phone's sheet, where the owner cannot read it. */
function refused(what: string, body: unknown) {
  setNote(what + ' — ' + (errText(body) || translate('바꾸지 못했습니다')));
  redraw();
}
/** A write went through and the read after it did not: the lists on show are the old ones, so they are taken off the
 * screen and the owner is told the change was made. */
function afterWriteUnread(what: string) {
  setStale(true);
  setNote(what + ' — ' + translate('바뀌었지만 목록을 다시 읽지 못했습니다'));
  redraw();
}
/** Sends one member change and reads the screen again, so the rows show what the store now holds. */
async function sendMember(
  endpoint: 'POST /api/members/add' | 'POST /api/members/role' | 'POST /api/members/remove',
  body: Record<string, unknown>,
  what: string,
  done?: () => void,
) {
  setNote('');
  setResult(null);
  try {
    const answer = await api(endpoint, { body, what, silent: true, expect: [400, 409] as const });
    if (isRefusal(answer.data)) {
      refused(what, answer.data);
      return;
    }
  } catch (error) {
    failed(what, error);
    return;
  }
  if (done) done(); // what a change that went through leaves behind (the typed login) is cleared
  if (!(await loadAccess())) afterWriteUnread(what);
}
/** [들이기] under the list: the login typed in and the role beside it. */
function addTyped() {
  const field = findMaybe(document, '#acc-login', HTMLInputElement);
  const login = field ? field.value.trim() : '';
  if (!login) {
    if (field) field.focus();
    return;
  }
  void sendMember('POST /api/members/add', { login, role: TYPED_ROLE }, translate('멤버 들이기'), () => {
    if (field) field.value = ''; // the draw that follows reads the field, so it is emptied first
    setTypedLogin('');
  });
}
/** Sends the transition: the checked settable rows become the member list, and the flag goes on. */
async function applyManaged() {
  const view = ACCESS,
    transition = view && view.transition;
  if (!transition) return;
  const members = transition.settable
    .filter((member) => CHECKED.has(member.login))
    .map((member) => ({ login: member.login, role: member.role }));
  const what = translate('화면 관리로 전환');
  const previewed = newlyAdmitted(transition, CHECKED).map((member) => member.login);
  setNote('');
  setResult(null);
  try {
    const answer = await api('POST /api/access/managed', {
      body: { managed: true, members, confirm: CONFIRM_MANAGED },
      what,
      silent: true,
      expect: [400, 409] as const,
    });
    if (isRefusal(answer.data)) {
      refused(what, answer.data);
      return;
    }
    setResult({ done: answer.data, previewed }); // what the screen says next is the server's count, not the preview's
  } catch (error) {
    failed(what, error);
    return;
  }
  setTransitionOpen(false);
  if (!(await loadAccess())) afterWriteUnread(what);
}
/** Every action of the access screen, by its data-act; answers whether it was one of them. */
function accessAction(act: string | undefined, control: HTMLElement) {
  const login = control.dataset.login || '',
    role = control.dataset.role || '';
  switch (act) {
    case 'access-open':
      openAccess();
      return true;
    case 'access-close':
      $('#access').close();
      return true;
    case 'access-role':
      void sendMember('POST /api/members/role', { login, role }, translate('역할 바꾸기'));
      return true;
    case 'access-pick':
      PICKED_ROLE.set(login, role);
      redraw();
      return true;
    case 'access-typed-role':
      setTypedRole(role);
      redraw();
      return true;
    case 'access-remove':
      void sendMember('POST /api/members/remove', { login }, translate('멤버 빼기'));
      return true;
    case 'access-admit': {
      // the name the tailnet gave (none when it gave none), so the member row reads it; the role is the one its own
      // chooser holds
      const user = ACCESS && ACCESS.tailnet.users.find((one) => one.login === login);
      void sendMember(
        'POST /api/members/add',
        { login, role: pickedRole(login), ...(user && user.name ? { name: user.name } : {}) },
        translate('멤버 들이기'),
      );
      return true;
    }
    case 'access-add':
      addTyped();
      return true;
    case 'access-manage':
      setTransitionOpen(true);
      redraw();
      return true;
    case 'access-manage-cancel':
      setTransitionOpen(false);
      redraw();
      return true;
    case 'access-manage-apply':
      void applyManaged();
      return true;
    case undefined: // the control matched [data-act], so the attribute is there
    default:
      return false;
  }
}
// The transition's checkboxes: they change the drawn summary, and they are not buttons.
document.addEventListener('change', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const login = target.dataset.accCheck;
  if (login === undefined) return;
  if (target.checked) CHECKED.add(login);
  else CHECKED.delete(login);
  redraw();
});

export { accessAction, loadAccess, openAccess };
