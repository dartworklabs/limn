// ------------------------------------------------ Access management: drawing the owner's screen
// The owner sees who may come in and who could be let in: an entry in [더보기], and a dialog of its own with two
// sections (this instance's members, and the tailnet's people who could be let in) and, while the instance still runs
// on --allow, a transition view of two columns. Drawn only for an owner (access/flow.ts): a control that a row, or a
// role, may not use is not drawn at all - it is not hidden, since a hidden button would stay in the document.
// Everything is drawn from the last GET /api/access answer (access/state.ts ACCESS); nothing here sends a request.
import { Html, html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { $, findMaybe } from '../platform/dom.ts';
import { META } from '../app/state.ts';
import { ROLE } from '../app/rules-tables.ts';
import { ACCESS, CHECKED, NOTE, RESULT, TRANSITION_OPEN, TYPED_LOGIN, TYPED_ROLE, pickedRole } from './state.ts';
import { admittedRows, keptCount, newlyAdmitted, sameLogins, seenText } from './rules.ts';

/** The two roles a screen may give (access_service.SETTABLE_ROLES); every other role is drawn, never offered. */
const SETTABLE: readonly string[] = [ROLE.VIEWER, ROLE.EDITOR];
/** The word each role reads as. */
const ROLE_WORD: Record<string, string> = {
  [ROLE.OWNER]: '소유자',
  [ROLE.EDITOR]: '편집',
  [ROLE.VIEWER]: '보기',
  [ROLE.AGENT]: '에이전트',
};
/** Whether a member row may be changed from this screen: a settable role, and not the reader's own row. The server
 * decides in the end (access_service); this keeps the control it would refuse out of the page. */
function rowChangeable(member: AccessMember, myLogin: string) {
  return SETTABLE.includes(member.role) && member.login !== myLogin;
}
/** The login of whoever is reading, or '' before the meta is in. */
function myLogin() {
  return (META && META.me && META.me.login) || '';
}

// ---------------------------------------------------------------- the entry and the dialog's frame

/** The entry in [더보기], shaped like the Trash's: an icon, the label, how many members and a chevron. */
function entryButton(view: AccessView) {
  return html`<button
    id="m-access"
    data-act="access-open"
    data-close="1"
    data-tip="${translate('이 인스턴스에 들어올 수 있는 사람을 봅니다. 소유자만 볼 수 있습니다')}"
  >
    ${lucideIcon('lock-open')}<span class="lbl">${translate('접근 관리')}</span
    ><span class="m-n" id="m-access-n">${view.members.length}</span>${lucideIcon('chevron-right')}
  </button>`;
}
/** The dialog's head and the body the screen is drawn into. */
function dialogFrame() {
  return html`<div class="ns-head">
      <span class="ns-grab" aria-hidden="true"></span>
      <div class="row">
        <h2 id="access-h">${translate('접근 관리')}</h2>
        <span class="sp"></span>
        <button class="btn-sm" data-act="access-close" data-tip="${translate('접근 관리 닫기 (Esc)')}">
          <span class="lbl">${translate('닫기')}</span>
        </button>
      </div>
    </div>
    <div id="access-body"></div>`;
}

// ---------------------------------------------------------------- the pieces the screen shares

/** Who a row is about: the name over the login (the login is the user's text, never translated). */
function personCell(name: string, login: string) {
  return html`<span class="acc-who"
    ><b class="acc-name" translate="no">${name || login}</b><span class="acc-login" translate="no">${login}</span></span
  >`;
}
/** A role segmented control: `act` is what pressing a word does ('access-role' asks the server, 'access-pick' only
 * remembers the choice for a candidate who is not a member yet). */
function roleControl(login: string, role: string, act: string) {
  return html`<div class="acc-roles seg" role="radiogroup" aria-label="${translate('역할')}">
    ${SETTABLE.map(
      (value) =>
        html`<button
          role="radio"
          class="${value === role ? 'on' : ''}"
          aria-checked="${value === role}"
          data-act="${act}"
          data-login="${login}"
          data-role="${value}"
        >
          ${translate(ROLE_WORD[value] || value)}
        </button>`,
    )}
  </div>`;
}
/** One member row. A row this screen may change draws a role control and [빼기]; any other (the reader's own row, an
 * owner's, an agent's) draws the role as a word and no control. */
function memberRow(member: AccessMember) {
  const changeable = rowChangeable(member, myLogin());
  return html`<div class="acc-row" data-login="${member.login}">
    ${personCell(member.name, member.login)}
    ${
      changeable
        ? roleControl(member.login, member.role, 'access-role')
        : html`<span class="acc-role-fixed">${translate(ROLE_WORD[member.role] || member.role)}</span>`
    }
    <span class="acc-seen" translate="no">${seenText(member)}</span>
    ${
      changeable
        ? html`<button class="acc-act btn-sm btn-destructive" data-act="access-remove" data-login="${member.login}">
            ${translate('빼기')}
          </button>`
        : html`<span class="acc-act"></span>`
    }
  </div>`;
}
/** One tailnet candidate's row: who, the role to give and [들이기]. */
function candidateRow(user: TailnetUser) {
  return html`<div class="acc-row" data-login="${user.login}">
    ${personCell(user.name || '', user.login)} ${roleControl(user.login, pickedRole(user.login), 'access-pick')}
    <span class="acc-seen"></span>
    <button class="acc-act btn-sm" data-act="access-admit" data-login="${user.login}">${translate('들이기')}</button>
  </div>`;
}
/** The row for someone the tailnet list does not show: a login, a role and [들이기]. */
function addRow() {
  return html`<div class="acc-add">
    <label class="acc-add-l" for="acc-login">${translate('목록에 없는 사람')}</label>
    <input
      id="acc-login"
      type="text"
      inputmode="email"
      autocomplete="off"
      autocapitalize="off"
      spellcheck="false"
      placeholder="name@example.com"
      value="${TYPED_LOGIN}"
      aria-label="${translate('들일 사람의 로그인')}"
    />
    ${roleControl('', TYPED_ROLE, 'access-typed-role')}
    <button class="acc-act btn-sm btn-default" data-act="access-add">${translate('들이기')}</button>
  </div>`;
}
/** The band an unmanaged instance carries: the screen cannot change admission yet, and the switch that changes that. */
function unmanagedBand(view: AccessView) {
  const allow = view.args.allow;
  return html`<div class="acc-band" role="status">
    <span class="acc-band-ic">${lucideIcon('info')}</span>
    <p class="acc-band-t">
      ${translate('이 인스턴스는 --allow 로 돌고 있어 화면에서 바꿀 수 없습니다')}
      ${
        allow.length
          ? html`<small class="acc-band-s" translate="no">--allow ${allow.join(', ')}</small>`
          : view.args.members_only
            ? html`<small class="acc-band-s">${translate('--members-only 로 멤버만 들어옵니다')}</small>`
            : html`<small class="acc-band-s">${translate('지금은 테일넷의 누구나 들어옵니다')}</small>`
      }
    </p>
    <button class="btn-sm btn-default acc-band-b" data-act="access-manage">${translate('화면 관리로 전환')}</button>
  </div>`;
}
/** Why the last change was refused, inside the screen: a banner would stand behind the modal dialog. */
function noteLine() {
  return NOTE ? html`<p class="acc-err errline flush" role="alert">${NOTE}</p>` : null;
}
/** The line that says how the instance decides admission now. */
function statusLine(view: AccessView) {
  return translateTemplate('화면에서 관리 중 · 멤버 {n}명', { n: view.members.length });
}
/** The note at the head of the tailnet list: it holds only the people this server can see - or, when the daemon could
 * not be read, says why there is none. */
function tailnetNote(view: AccessView) {
  const reason = view.tailnet.reason;
  if (reason)
    return html`<p class="acc-note">
      ${translate('테일넷 목록을 읽지 못했습니다 — 아래 칸에 로그인을 직접 적어 들이세요')}
      <small translate="no">(${reason})</small>
    </p>`;
  return html`<p class="acc-note">
    ${translate('이 목록에는 이 서버가 볼 수 있는 사람만 있습니다 — 없는 사람은 아래 칸에 로그인을 적으세요')}
  </p>`;
}

// ---------------------------------------------------------------- the transition view

/** One checkbox line of the transition: the box, who, and the role it keeps. */
function checkLine(member: AccessMember) {
  // checked is a bare attribute, so the two states are two templates: a value may only sit in element content or a
  // quoted attribute (platform/markup.ts).
  const box = CHECKED.has(member.login)
    ? html`<input type="checkbox" data-acc-check="${member.login}" checked />`
    : html`<input type="checkbox" data-acc-check="${member.login}" />`;
  return html`<label class="acc-check">
    <span class="ck">${box}${lucideIcon('check')}</span>
    ${personCell(member.name, member.login)}
    <span class="acc-seen">${translate(ROLE_WORD[member.role] || member.role)}</span>
  </label>`;
}
/** One line of the transition that stays whatever is checked: an owner's row or an agent's. It has no box. */
function fixedLine(member: AccessFixedMember) {
  return html`<div class="acc-check acc-fixed">
    <span class="acc-fix-ic">${lucideIcon('lock-open')}</span>
    ${personCell(member.name, member.login)}
    <span class="acc-seen">${translate(ROLE_WORD[member.role] || member.role)} · ${translate('고정')}</span>
  </div>`;
}
/** The line naming whoever would newly get in, or nothing when the switch admits no one new. */
function newlyLine(transition: AccessTransition) {
  const rows = newlyAdmitted(transition, CHECKED);
  if (!rows.length) return null;
  return html`<p class="acc-new">
    ${translate('새로 들어오게 되는 사람')}:
    <b translate="no">${rows.map((member) => member.name || member.login).join(', ')}</b>
  </p>`;
}
/** What the switch would do, in one line: how many keep coming in and how many newly do. */
function summaryLine(transition: AccessTransition) {
  return html`<p class="acc-sum">
    ${translateTemplate('{n}명 유지', { n: keptCount(transition, CHECKED) })} ·
    ${translateTemplate('{n}명 새로 들어옴', { n: newlyAdmitted(transition, CHECKED).length })}
  </p>`;
}
/** The transition view: two columns side by side (stacked in compact), the checkboxes in the right one. */
function transitionColumns(transition: AccessTransition) {
  return html`<div class="acc-tr">
    ${noteLine()}<h3 class="acc-h">${translate('화면 관리로 전환')}</h3>
    <p class="acc-note">
      ${translate('전환하면 이 목록이 입장을 정합니다 — [전환 뒤 들어오는 사람]에서 계속 들어올 사람을 고르세요')}
    </p>
    <div class="acc-cols">
      <div class="acc-col">
        <h4 class="acc-col-h">${translate('지금 들어오는 사람')}</h4>
        <div class="acc-col-rows">
          ${admittedRows(transition).map(
            (member) => html`<div class="acc-check acc-plain">
              ${personCell(member.name, member.login)}
              <span class="acc-seen">${translate(ROLE_WORD[member.role] || member.role)}</span>
            </div>`,
          )}
        </div>
      </div>
      <div class="acc-col acc-col-pick">
        <h4 class="acc-col-h">${translate('전환 뒤 들어오는 사람')}</h4>
        <div class="acc-col-rows">${transition.fixed.map(fixedLine)} ${transition.settable.map(checkLine)}</div>
      </div>
    </div>
    ${newlyLine(transition)}
    <div class="acc-tr-foot">
      ${summaryLine(transition)}
      <span class="sp"></span>
      <button class="btn-sm btn-secondary" data-act="access-manage-cancel">${translate('취소')}</button>
      <button class="btn-sm btn-default" data-act="access-manage-apply">${translate('화면 관리로 전환')}</button>
    </div>
  </div>`;
}

// ---------------------------------------------------------------- what the switch did

/** One line of the outcome: what the server counted and, when there are any, whose logins. */
function resultLine(label: string, logins: readonly string[]) {
  return html`<li>
    <span class="acc-res-l">${translate(label)}</span>
    <b class="acc-res-n" translate="no">${logins.length}</b>
    ${logins.length ? html`<span class="acc-res-w" translate="no">${logins.join(', ')}</span>` : null}
  </li>`;
}
/** The outcome of the switch, from the server's own answer (POST /api/access/managed): who was added, removed, given
 * another role, which owner and agent rows were kept, and - by login - who was newly let in. Not the preview's count:
 * if the two differ the screen says so. */
function resultBlock() {
  if (!RESULT) return null;
  const { done, previewed } = RESULT;
  return html`<div class="acc-result" role="status">
    <h3 class="acc-h">${translate('화면 관리로 전환했습니다')}</h3>
    <ul class="acc-res">
      ${resultLine('추가됨', done.added)} ${resultLine('빠짐', done.removed)} ${resultLine('역할이 바뀜', done.changed)}
      ${resultLine('그대로 둔 소유자·에이전트', done.kept)}
    </ul>
    ${
      done.newly_admitted.length
        ? html`<p class="acc-new">
            ${translate('서버가 새로 들어오게 한 사람')}: <b translate="no">${done.newly_admitted.join(', ')}</b>
          </p>`
        : html`<p class="acc-new">${translate('새로 들어오게 한 사람은 없습니다')}</p>`
    }
    ${
      sameLogins(previewed, done.newly_admitted)
        ? null
        : html`<p class="acc-new">${translate('미리 본 결과와 다릅니다 — 서버가 말한 결과가 맞습니다')}</p>`
    }
  </div>`;
}

// ---------------------------------------------------------------- the two sections

/** The dialog's body: the band or the status line, the members and the tailnet's people who could be let in - or, when
 * the owner pressed [화면 관리로 전환], the transition. */
function screenBody(view: AccessView): Html {
  if (!view.managed && TRANSITION_OPEN && view.transition) return transitionColumns(view.transition);
  return html`${noteLine()}${resultBlock()}${view.managed ? html`<p class="acc-status">${statusLine(view)}</p>` : unmanagedBand(view)}
    <section class="acc-sec">
      <h3 class="acc-h">
        ${translate('이 인스턴스의 멤버')}
        <span class="badge badge-secondary" translate="no">${view.members.length}</span>
      </h3>
      <div class="acc-rows">${view.members.map(memberRow)}</div>
    </section>
    <section class="acc-sec">
      <h3 class="acc-h">${translate('테일넷에서 들이기')}</h3>
      ${tailnetNote(view)}
      <div class="acc-rows">
        ${
          view.tailnet.users.length
            ? view.tailnet.users.map(candidateRow)
            : html`<p class="acc-note">${translate('들일 사람이 없습니다')}</p>`
        }
      </div>
      ${addRow()}
    </section>`;
}

/** Draws the entry in [더보기] and, the first time, the dialog's frame - once the first answer is in, for an owner only. */
function drawShell(view: AccessView) {
  setHtml($('#m-access-host'), entryButton(view));
  if (!findMaybe(document, '#access-body', HTMLElement)) setHtml($('#access'), dialogFrame());
}
/** Draws the screen from the last answer; nothing to draw before the first read. */
function drawAccess() {
  const view = ACCESS;
  if (!view) return;
  drawShell(view);
  const body = findMaybe(document, '#access-body', HTMLElement);
  if (body) setHtml(body, screenBody(view));
}

export { drawAccess };
