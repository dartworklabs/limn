// ------------------------ Browser notifications (docs/handbook/viewer.md §브라우저 알림) - only while the tab is alive
// Turned on per device (pinPrefs.notify). Notification.requestPermission() is only ever called from the [알림 켜기]
// click. The server carries "events addressed to the current identity" in the 5-second poll
// (/api/meta?light=1&ev=<cursor>) - asked for by every tab of a person, the switch on or off - and a tab says them on
// its status line; only with the switch on does a tab that is not in front show them as system notifications
// (docs/handbook/viewer.md §새 소식). The cursor (pinNotifyCursor) is kept in this browser's localStorage, so a reload
// or two tabs never announce the same event twice, and a visit days later says what came since the last (at most the
// server's 20 newest). Display always goes through the service worker's showNotification() (Chrome on Android blocks
// new Notification()); tag is the pin number, so the same pin collapses into one slot. If the tab is visible and
// focused, the status line says it instead. This only works in a secure context (an https tailnet address, or
// http://127.0.0.1/localhost) - the browser blocks plain http on other hosts.
import { DOC, DROPPED, META, OPEN_CARDS, SWITCHSEQ } from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { SECTION_OPEN, prefs, savePrefs } from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import { announce, groupNote, quietNote } from '../platform/notices.ts';
import { hashDoc } from '../documents/view-tabs.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { switchDoc } from '../documents/flow-switch.ts';
import { syncHiddenNotifyTimer } from '../documents/flow-polling.ts';
import { setSide } from '../layout/flow.ts';
import { openTrash } from './view-cards.ts';
import { drawPins, gotoReview, jumpPin, jumpToCard, loadPinsNow } from './flow-list.ts';
import { restorePin } from './flow-actions.ts';
import { EVENT_TYPE, NOTICE_DOT, NOTICE_KIND } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { LOCAL_LOGIN, NOTIFY_STATE, PIN_STATE } from '../app/rules-tables.ts';
import { pinState } from '../app/rules-pins.ts';
import { who } from '../app/state-people.ts';
import { docInfo, withDocQuery, isViewer } from '../documents/state.ts';
// An event of the light poll that is addressed to me (limn/collaboration/events.py events_since): its type is one of the
// notified ones, doc_name is its document's name, and to holds the logins it is for.
interface PinEvent {
  seq: number;
  type: (typeof EVENT_TYPE)[keyof typeof EVENT_TYPE];
  pin: number;
  doc?: string;
  doc_name?: string;
  to?: string[];
  by?: Person;
  excerpt?: string;
}
// What notifyHandle reads of a light poll's answer: the latest event number, and with a cursor the events after it.
interface PinEventsMeta {
  ev_seq?: number;
  events?: PinEvent[];
}
const NOTIFY_RANK = { dropped: 6, assigned: 5, mention: 4, reopened: 3, review_requested: 2, replied: 1 };
let WORKER_REGISTRATION = null as ServiceWorkerRegistration | null;
function notifySupported() {
  return !!(window.isSecureContext && 'serviceWorker' in navigator && 'Notification' in window);
}
function notifyPerm() {
  return 'Notification' in window ? Notification.permission : 'unsupported';
}
function notifyOn() {
  return !!prefs().notify && notifySupported() && notifyPerm() === 'granted';
}
// The cursor this tab last set, kept in memory too: a browser whose storage refuses (a SecurityError on reading it, a
// full quota on writing) still has one for this visit - the boot goes on, and an event is said once - and the newer of
// the two is the cursor, so another tab's advance in storage counts as well.
let NOTIFY_CURSOR_MEM = null as number | null;
function notifyCursor(): number | null {
  let stored = NaN;
  try {
    stored = parseInt(localStorage.getItem('pinNotifyCursor') || '', 10);
  } catch (error) {}
  const remembered = NOTIFY_CURSOR_MEM;
  return isNaN(stored) ? remembered : remembered !== null && remembered > stored ? remembered : stored;
}
function setNotifyCursor(cursor: number) {
  const current = notifyCursor();
  if (current == null || cursor > current) putNotifyCursor(cursor);
}
// Puts the cursor at `cursor`, backwards too (the server's events started again): in memory and, where it may, in
// storage.
function putNotifyCursor(cursor: number) {
  NOTIFY_CURSOR_MEM = cursor;
  try {
    localStorage.setItem('pinNotifyCursor', String(cursor));
  } catch (error) {}
}
function notifyQuery() {
  if (isLocalIdentity()) return '';
  const cursor = notifyCursor();
  return cursor == null ? '' : '&ev=' + cursor;
}
// Picks what to notify about (a pure function): after the cursor, addressed to me (to), not my own doing. One per pin -
// mention > reopen > awaiting review > reply, ties go to the later one.
function pickNotifications(events: PinEvent[] | null | undefined, me: Me | null | undefined, cursor: number | null) {
  const login = me && me.login;
  if (!login || login === LOCAL_LOGIN) return [];
  const by = new Map<number, PinEvent>();
  (events || []).forEach((event) => {
    if (!(event.seq > (cursor == null ? -1 : cursor))) return;
    if (!NOTIFY_RANK[event.type]) return;
    if (!(event.to || []).includes(login) || (event.by && event.by.login === login)) return;
    const chosen = by.get(event.pin);
    if (
      !chosen ||
      NOTIFY_RANK[event.type] > NOTIFY_RANK[chosen.type] ||
      (NOTIFY_RANK[event.type] === NOTIFY_RANK[chosen.type] && event.seq > chosen.seq)
    )
      by.set(event.pin, event);
  });
  return Array.from(by.values()).sort((earlier, later) => earlier.seq - later.seq);
}
function notifyText(event: PinEvent) {
  const name = who(event.by) || translate('누군가'),
    excerpt = String(event.excerpt || '')
      .split('\n')[0]
      .slice(0, 80),
    values = { name: name, text: excerpt };
  const body =
    {
      mention: translateTemplate('{name}님이 불렀습니다: {text}', values),
      review_requested: translateTemplate('검토 대기: {text}', { text: excerpt || translate('설명 없이 닫힘') }),
      replied: translateTemplate('{name}님 답글: {text}', values),
      reopened: excerpt
        ? translateTemplate('{name}님이 다시 열었습니다: {text}', values)
        : translateTemplate('{name}님이 다시 열었습니다', values),
      assigned: translateTemplate('{name}님이 담당으로 지정했습니다: {text}', values),
      dropped: translateTemplate('{name}님이 삭제했습니다: {text}', values),
    }[event.type] || excerpt;
  return {
    title:
      translateTemplate('핀 #{id}', { id: event.pin }) +
      ' · ' +
      (event.doc_name || event.doc || (META && META.label) || ''),
    body,
  };
}
// Shows one event: a status-line message while this tab has focus, or with the switch off (the message waits on the
// line for the person to come back), else a system notification. notifyText() already speaks the UI language and quotes
// the document's name and the post, so the message is literal (a document named '그림' stays '그림'). It marks [검토 M]
// for a review request and [핀 N] for the rest on this document (notifyDot).
const NOTIFY_BRIEF: Record<string, string> = {
  mention: '나를 부름',
  review_requested: '검토 대기',
  replied: '답글',
  reopened: '다시 열림',
  assigned: '담당 지정',
  dropped: '삭제됨',
};
async function notifyShow(event: PinEvent) {
  const shown = notifyText(event);
  if (!notifyOn() || (document.visibilityState === 'visible' && document.hasFocus())) {
    notifyLine(event);
    return;
  }
  try {
    const registration = WORKER_REGISTRATION || (await navigator.serviceWorker.ready);
    await registration.showNotification(shown.title, {
      body: shown.body,
      tag: 'pin-' + event.pin,
      icon: (
        (document.querySelector('link[rel=apple-touch-icon]') ||
          document.querySelector('link[rel=icon]') || {
            href: undefined,
          }) as HTMLLinkElement
      ).href,
      // [되살리기] on "X deleted your pin" (the service worker hands it to this tab)
      actions:
        event.type === EVENT_TYPE.DROPPED && !isViewer() ? [{ action: 'restore', title: translate('되살리기') }] : [],
      data: {
        pin: event.pin,
        doc: event.doc,
        url: '/#doc=' + encodeURIComponent(event.doc || '') + '&pin=' + event.pin,
      },
    });
  } catch (err) {}
}
// An event on the status line: one message per kind of event however many pins it reaches (groupNote 'ev:<type>'), so
// an agent closing twelve of my pins one by one is one message that grows. One pin says what its notification says,
// with [열기] (a deleted one [되살리기], a viewer's [열기]); more say how many, their numbers and who, with [보기] for
// review requests (the review section), the Trash for deleted ones, else [열기] on the newest.
function notifyLine(event: any) {
  groupNote('ev:' + event.type, { evs: [event] }, notifyLineView, (older, newer) => ({
    evs: [...older.evs.filter((x: any) => x.pin !== newer.evs[0].pin), ...newer.evs],
  }));
}
function notifyLineView(group: { evs: any[] }) {
  const events = group.evs,
    latest = events[events.length - 1],
    count = events.length,
    one = count === 1,
    shown = notifyText(latest),
    drop = latest.type === EVENT_TYPE.DROPPED;
  const act = drop
    ? isViewer()
      ? { label: '열기', tip: '휴지통에서 봅니다', fn: () => openPinFromLink(latest.doc, latest.pin) }
      : one
        ? { label: '되살리기', tip: '휴지통에서 같은 번호로 되살립니다', wait: true, fn: () => restorePin(latest.pin) }
        : { label: '휴지통', tip: '지운 핀을 휴지통에서 봅니다', fn: () => openTrash(latest.pin) }
    : latest.type === EVENT_TYPE.REVIEW_REQUESTED && !one
      ? { label: '보기', tip: '검토 대기 핀으로 갑니다', fn: gotoReview }
      : { label: '열기', tip: '그 핀으로 갑니다', fn: () => openPinFromLink(latest.doc, latest.pin) };
  const many =
    (
      {
        mention: '나를 부른 핀 {n}개',
        review_requested: '핀 {n}개가 검토 대기로 넘어왔습니다',
        replied: '답글이 달린 핀 {n}개',
        reopened: '핀 {n}개 다시 열림',
        assigned: '나에게 맡긴 핀 {n}개',
        dropped: '핀 {n}개가 삭제됨',
      } as Record<string, string>
    )[latest.type] || '소식 {n}개';
  const ids =
      events
        .slice(0, 3)
        .map((x) => '#' + x.pin)
        .join(', ') + (count > 3 ? ' ' + translateTemplate('외 {n}개', { n: count - 3 }) : ''),
    names = [...new Set(events.map((x) => who(x.by)).filter(Boolean))].slice(0, 2).join(', ');
  return {
    msg: one
      ? shown.title + ' — ' + shown.body
      : translateTemplate(many, { n: count }) + ' — ' + ids + (names ? ' · ' + names : ''),
    kind: drop ? NOTICE_KIND.WARN : NOTICE_KIND.OK,
    act,
    o: {
      keys: events.map((x) => x.type + ':' + x.pin),
      rank: 2,
      literal: true,
      dot: notifyDot(
        latest.type,
        events.some((x) => !x.doc || x.doc === DOC),
      ),
      brief: translate(NOTIFY_BRIEF[latest.type] || '소식') + (one ? '' : ' ' + count),
    },
  };
}
// The chip an event's message marks (a NOTICE_DOT, or ''): a review request [검토 M], which counts every document;
// anything else on this document (here) [핀 N]; another document's nothing - its pins are not in this panel. Pure.
function notifyDot(type: string, here: boolean): string {
  return type === EVENT_TYPE.REVIEW_REQUESTED ? NOTICE_DOT.RV : here ? NOTICE_DOT.SIDE : '';
}
function notifyHandle(meta: PinEventsMeta | null | undefined) {
  if (!meta || typeof meta.ev_seq !== 'number') return;
  if (isLocalIdentity()) return; // no event is ever addressed to a local identity
  const cursor = notifyCursor();
  if (cursor == null) {
    setNotifyCursor(meta.ev_seq);
    return;
  } // first time enabled in this browser - never floods with a backlog of past events
  if (!Array.isArray(meta.events)) {
    if (meta.ev_seq < cursor) putNotifyCursor(meta.ev_seq);
    return;
  }
  // only what's after it, if another tab just advanced the cursor
  const list = pickNotifications(meta.events, META && META.me, notifyCursor());
  const top = meta.events.reduce((highest, event) => Math.max(highest, event.seq || 0), cursor);
  setNotifyCursor(top);
  list.forEach(notifyShow);
}
async function notifyRegister() {
  if (!notifySupported()) return null;
  try {
    WORKER_REGISTRATION = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    return WORKER_REGISTRATION;
  } catch (error) {
    return null;
  }
}
// A local identity (no tailnet login) never gets events from the server's events_since() at all (§@태그·사람·이벤트),
// so notifications would never arrive - since getting browser permission wouldn't help, turning it on is blocked
// outright and the reason is shown.
function isLocalIdentity() {
  const me = META && META.me;
  return !me || !me.login || me.login === LOCAL_LOGIN;
}
function notifyState() {
  if (isLocalIdentity()) return NOTIFY_STATE.LOCAL;
  if (!notifySupported()) return NOTIFY_STATE.UNSUPPORTED;
  const permission = notifyPerm();
  if (permission === 'denied') return NOTIFY_STATE.BLOCKED;
  return prefs().notify && permission === 'granted' ? NOTIFY_STATE.ON : NOTIFY_STATE.OFF;
}
// Draws the notification control for this device's state (notifyState): [더보기]'s switch, the one notification control
// on every layout - on only when on, and off and disabled where it cannot turn on (blocked, unsupported, a local
// identity) with the reason on a line under it. The state is never in the switch's name ('브라우저 알림').
function drawNotify() {
  const state = notifyState(),
    toggle = $('#m-notify');
  const tip = {
    on: '이 기기에서 켜져 있습니다. 누르면 끕니다',
    off: '누르면 이 기기에서 켭니다(브라우저가 허용을 묻습니다)',
    blocked:
      '브라우저가 이 사이트의 알림을 막았습니다. 주소창 왼쪽 자물쇠(사이트 설정) → 알림 → 허용으로 바꾼 뒤 다시 누르세요',
    unsupported: '브라우저 알림은 https(테일넷 주소)나 http://127.0.0.1·localhost 에서만 됩니다',
    local: '테일넷 주소로 열면 켤 수 있습니다',
  }[state];
  const why =
    state === NOTIFY_STATE.BLOCKED
      ? translate('브라우저가 막았습니다 — 주소창 자물쇠 → 알림 → 허용')
      : state === NOTIFY_STATE.UNSUPPORTED
        ? translate('https 테일넷 주소나 http://127.0.0.1에서만 됩니다')
        : state === NOTIFY_STATE.LOCAL
          ? translate('테일넷 주소로 열면 켤 수 있습니다')
          : '';
  toggle.setAttribute('aria-checked', String(state === NOTIFY_STATE.ON));
  toggle.disabled = !!why;
  toggle.dataset.tip = tip;
  const whyLine = $('#m-notify-why');
  whyLine.textContent = why;
  whyLine.hidden = !why;
}
// [더보기]'s notification switch: off when on; on (asking the browser's permission from within this press) when off.
// Where it cannot turn on, the switch is disabled and the line under it (#m-notify-why) says why (drawNotify), so a
// press there changes nothing; a permission not given says so on that line too (blocked: drawNotify's reason; no choice
// made: notifyWhy). Turning it on or off is silent - the switch shows it - and read out.
async function notifyToggle() {
  const state = notifyState();
  if (state === NOTIFY_STATE.LOCAL || state === NOTIFY_STATE.UNSUPPORTED || state === NOTIFY_STATE.BLOCKED) {
    drawNotify();
    return;
  }
  if (state === NOTIFY_STATE.ON) {
    savePrefs({ notify: false });
    drawNotify();
    syncHiddenNotifyTimer();
    quietNote('이 기기의 브라우저 알림을 껐습니다');
    return;
  }
  let permission = notifyPerm();
  if (permission !== 'granted') {
    try {
      permission = await Notification.requestPermission();
    } catch (error) {
      permission = 'denied';
    }
  } // only ever asked from within this click
  if (permission !== 'granted') {
    drawNotify();
    notifyWhy(permission === 'denied' ? $('#m-notify-why').textContent : translate('알림 허용을 고르지 않았습니다'));
    return;
  }
  await notifyRegister();
  savePrefs({ notify: true });
  try {
    const meta = (await api(withDocQuery('/api/meta?light=1'), { silent: true })).data;
    if (notifyCursor() == null) setNotifyCursor(meta.ev_seq);
  } catch (error) {}
  drawNotify();
  syncHiddenNotifyTimer();
  quietNote('이 기기에서 브라우저 알림을 켰습니다 — 나를 부르거나 내 핀에 일이 생기면 알립니다');
}
// Says text on the line under the notification switch until it is drawn again (drawNotify), and reads it out.
function notifyWhy(text: string) {
  const whyLine = $('#m-notify-why');
  whyLine.textContent = text;
  whyLine.hidden = false;
  announce(text);
}
// Clicking a notification (service worker -> postMessage, or a new tab's #doc=<key>&pin=<number>) switches to that
// document and opens that pin.
function hashPin() {
  const match = /(?:^#|[#&])pin=(\d{1,9})(?:&|$)/.exec(location.hash || '');
  return match ? +match[1] : null;
}
// Reads a one-shot pin link (#doc=<key>&pin=<n>[&act=restore]) and removes pin=/act= from the address right away, so a
// reload never repeats it (a reload of an &act=restore link would restore again a pin someone has since deleted).
function takeLinkHash() {
  const link = { pin: hashPin(), doc: hashDoc(), restore: /(?:^#|[#&])act=restore(?:&|$)/.test(location.hash || '') };
  if (link.pin)
    history.replaceState(history.state, '', location.pathname + location.search + (link.doc ? '#doc=' + link.doc : ''));
  return link;
}
// restore = the [되살리기] action of a 'dropped' notification: bring the pin back from the Trash first (never for a
// viewer). The list is read again first and the link goes on once it shows a snapshot asked for since then - its own
// read's, or a newer read's that overtook it (the light poll the tab's return sets off) - and stops only when the read
// failed: an earlier list could restore a pin from a Trash that no longer holds it.
async function openPinFromLink(doc: string | null | undefined, pin: number, restore?: boolean) {
  if (!pin) return;
  if (doc && doc !== DOC && docInfo(doc)) {
    const opening = switchDoc(doc),
      visit = SWITCHSEQ;
    await opening;
    if (DOC !== doc || visit !== SWITCHSEQ) return;
  }
  const visit = SWITCHSEQ,
    visitDoc = DOC;
  const now = await loadPinsNow();
  if (!now || DOC !== visitDoc || visit !== SWITCHSEQ) return;
  if (restore && !isViewer() && !findAnyPin(pin) && DROPPED.some((x) => x.id === pin)) {
    await restorePin(pin);
    if (DOC !== visitDoc || visit !== SWITCHSEQ) return;
  }
  const found = findAnyPin(pin);
  if (!found) {
    if (DROPPED.some((x) => x.id === pin)) openTrash(pin);
    return;
  }
  if (pinState(found) === PIN_STATE.DONE) {
    SECTION_OPEN.done = true;
  }
  OPEN_CARDS.add(pin);
  setSide(true);
  drawPins();
  if (pinState(found) !== PIN_STATE.DONE) jumpPin(pin);
  requestAnimationFrame(() => {
    if (DOC === visitDoc && visit === SWITCHSEQ) jumpToCard(pin);
  });
}
if ('serviceWorker' in navigator)
  navigator.serviceWorker.addEventListener('message', (event) => {
    const message = event.data || {};
    if (message.type === 'open-pin') openPinFromLink(message.doc, +message.pin);
    else if (message.type === 'restore-pin' && !isViewer()) restorePin(+message.pin);
  });
window.addEventListener('hashchange', () => {
  const link = takeLinkHash();
  if (link.pin) openPinFromLink(link.doc, link.pin, link.restore);
});
// Sets WORKER_REGISTRATION, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setWorkerRegistration<Value extends typeof WORKER_REGISTRATION>(value: Value): Value {
  WORKER_REGISTRATION = value;
  return value;
}
export {
  WORKER_REGISTRATION,
  drawNotify,
  notifyCursor,
  notifyHandle,
  notifyOn,
  notifyPerm,
  notifyQuery,
  notifyRegister,
  notifySupported,
  notifyToggle,
  openPinFromLink,
  setWorkerRegistration,
  takeLinkHash,
};
