// ------------------ Auto sync - lightweight meta polling (docs/handbook/build-sync.md §자동 동기화 (가벼운 meta 폴링))
import {
  $,
  BUILD_STATE,
  DOC,
  DOC_SEQ,
  ELEMENT_SYNC,
  EVENT_TYPE,
  META_BY,
  NOTICE_DOT,
  NOTICE_KIND,
  NOTICE_LIFE,
  PIN_STATE,
  SWITCHSEQ,
  SYNC_STATE,
  rendersInBrowser,
} from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { API_WAIT, api } from '../platform/api.ts';
import { announce, digestBegin, digestSoon, groupNote, lineNote } from '../platform/notices.ts';
import { docInfo, withDocQuery, drawDocTabs } from './view-tabs.ts';
import { switchDoc } from './flow-switch.ts';
import { updateStaleBadge, updateSyncBadge } from './flow-boot.ts';
import { notifyHandle, notifyOn, notifyQuery } from './flow-notification.ts';
import { BUILD, pollBuild } from './view-build-chip.ts';
import {
  DIGEST_TAIL_MS,
  awayTitle,
  checkDocUpdate,
  checkVersion,
  expectUpdate,
  countPinMove,
  versionDue,
} from './flow-updates.ts';
import { MARKDOWN_VIEW, isMarkdownDoc, buildMarkdownDoc, checkTreeImages } from '../markdown/view.ts';
import { OFF, offlineFlush } from '../offline/api.ts';
import { josa, josaName, who } from '../pins/view-card-parts.ts';
import { openTrash } from '../pins/view-cards.ts';
import { gotoReview, loadPins } from '../pins/flow-list.ts';
import { restorePin } from '../pins/api.ts';
let LAST_PINS_REVISION = null as string | null,
  LAST_SRC_MTIME = null as string | number | null,
  POLL_FAILS = 0,
  LIGHT_TIMER = undefined as ReturnType<typeof setInterval> | undefined,
  LIGHT_INFLIGHT = null as Promise<void> | null;
// Single-flight, the same pattern as pollBuild: when visibilitychange, focus and the 5-second timer call this together
// (focus returning at the same moment as a tab switch), /api/meta and loadPins go out once - overlapping calls would
// fire loadPins three times.
function pollLight() {
  // a heavy refresh (including redrawing the list) is never sent while the tab is hidden
  if (document.hidden) return Promise.resolve();
  if (LIGHT_INFLIGHT) return LIGHT_INFLIGHT;
  LIGHT_INFLIGHT = pollLightOnce().finally(() => {
    LIGHT_INFLIGHT = null;
  });
  return LIGHT_INFLIGHT;
}
// While the tab is hidden the list is never redrawn, but if notifications are on (notifyOn) a light /api/meta?light=1
// call (slow - the browser throttles it anyway) is still made just to surface events as notifications, so a hidden tab
// still gets them. This notification-only branch splits off at the same point as pollLight's document.hidden bailout -
// it never touches the screen.
let NOTIFY_HIDDEN_TIMER = undefined as ReturnType<typeof setInterval> | undefined,
  NOTIFY_HIDDEN_INFLIGHT = null as Promise<void> | null;
const NOTIFY_HIDDEN_INTERVAL_MS = 20000;
function pollHiddenNotify() {
  if (!document.hidden || !notifyOn()) return Promise.resolve();
  if (NOTIFY_HIDDEN_INFLIGHT) return NOTIFY_HIDDEN_INFLIGHT;
  NOTIFY_HIDDEN_INFLIGHT = pollHiddenNotifyOnce().finally(() => {
    NOTIFY_HIDDEN_INFLIGHT = null;
  });
  return NOTIFY_HIDDEN_INFLIGHT;
}
async function pollHiddenNotifyOnce() {
  let meta;
  try {
    meta = (
      await api(withDocQuery('/api/meta?light=1') + notifyQuery(), {
        what: '알림 확인',
        silent: true,
        wait: API_WAIT.POLL,
      })
    ).data;
  } catch (error) {
    return;
  }
  if (document.hidden) notifyHandle(meta); // if the tab came back while waiting, normal polling has already handled it
}
// If the tab hides while notifications are on, the slow timer is started; it's stopped when the tab returns or
// notifications are turned off (no duplicate polling).
function syncHiddenNotifyTimer() {
  clearInterval(NOTIFY_HIDDEN_TIMER);
  NOTIFY_HIDDEN_TIMER = undefined;
  if (document.hidden && notifyOn()) {
    pollHiddenNotify();
    NOTIFY_HIDDEN_TIMER = setInterval(pollHiddenNotify, NOTIFY_HIDDEN_INTERVAL_MS);
  }
}
// Applies connection and document status only to the visit that sent the request; notifications remain independent of
// document visits. Back after AWAY_MS without an answer (the tab hidden, the device asleep, the connection lost), what
// this poll and the build it may set going say is gathered into one message (notices.ts digestBegin,
// docs/handbook/viewer.md §새 소식); a poll back from that, or one every VERSION_EVERY_MS, asks which Limn the server
// runs (updates.ts checkVersion).
let LIGHT_OK_AT = 0;
const AWAY_MS = 120000;
async function pollLightOnce() {
  let meta;
  const visitDoc = DOC,
    visit = SWITCHSEQ,
    gap = LIGHT_OK_AT ? Date.now() - LIGHT_OK_AT : 0,
    back = gap >= AWAY_MS,
    lost = POLL_FAILS >= 2;
  if (back) digestBegin(awayTitle(gap, lost));
  // The poll is what says the connection is gone, so it never waits on a server that does not answer (API_WAIT): one
  // poll is out at a time, and a poll left waiting would count no failure for as long as the system let it wait.
  try {
    meta = (
      await api(withDocQuery('/api/meta?light=1') + notifyQuery(), {
        what: '상태 확인',
        silent: true,
        wait: API_WAIT.POLL,
      })
    ).data;
  } catch (error) {
    if (back) digestSoon();
    if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
    POLL_FAILS++;
    // read out once, as it is lost (rule 1)
    if (POLL_FAILS === 2) announce(translate('연결 끊김 · 다시 잇는 중'), true);
    if (POLL_FAILS >= 2) $('#conn-lost').hidden = false;
    return;
  }
  const was = POLL_FAILS;
  LIGHT_OK_AT = Date.now();
  notifyHandle(meta); // browser notifications - independent of the document (handled first even mid document-switch)
  if (visitDoc !== DOC || visit !== SWITCHSEQ) {
    if (back) digestSoon(DIGEST_TAIL_MS);
    return;
  } // a return to the same document is a new visit too
  POLL_FAILS = 0;
  $('#conn-lost').hidden = true;
  if (back || was > 0 || versionDue()) checkVersion();
  // the connection is back: the pins kept while it was gone are written (offline.ts)
  if (was > 0 && OFF.n) void offlineFlush();
  updateStaleBadge(meta);
  updateSyncBadge(meta.sync);
  noteOtherDocs(meta.docs);
  // With multiple documents, re-read even if src_sig (per-document src_mtime) changed - another document's manuscript
  // changing shifts that document's pins' lines too.
  const sig = meta.src_sig || meta.src_mtime;
  // A failed or superseded pin refresh has not observed this revision; retry it on the next light poll.
  const needsPins = LAST_PINS_REVISION === null || meta.pins_rev !== LAST_PINS_REVISION || sig !== LAST_SRC_MTIME;
  if (sig !== LAST_SRC_MTIME || meta.building || (meta.sync && meta.sync.state === SYNC_STATE.UPDATING))
    expectUpdate(sig !== LAST_SRC_MTIME); // its pins' moves wait for its update message
  const applied = !needsPins || (await loadPins());
  if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
  // Its source changed since the last read that answered: the Markdown surface reads and draws it again, asked once per
  // change while that read is on its way (MARKDOWN_VIEW.asked), and again on the next poll if it failed
  // (buildMarkdownDoc clears MARKDOWN_VIEW.asked).
  if (isMarkdownDoc() && meta.src_mtime !== MARKDOWN_VIEW.mtime && meta.src_mtime !== MARKDOWN_VIEW.asked) {
    MARKDOWN_VIEW.asked = meta.src_mtime;
    buildMarkdownDoc();
    // a tree image rewritten on disk shows without a reload (md-surface.ts)
  } else if (isMarkdownDoc()) void checkTreeImages();
  if (applied) {
    LAST_PINS_REVISION = meta.pins_rev;
    LAST_SRC_MTIME = sig;
  }
  // A build started via curl by another session/agent is also caught through light meta's build.state - the 1-second
  // poll only runs during that (or when this tab itself pressed rebuild()).
  if (meta.build && meta.build.state === BUILD_STATE.RUNNING && !BUILD.timer) pollBuild();
  // If build_seq (number of finished builds) differs from what this tab has seen, it means a build started and finished
  // entirely within a 5-second polling gap, never seen as "running" - the details are fetched to sync up the
  // screen/banner/chip.
  else if (typeof meta.build_seq === 'number' && meta.build_seq !== BUILD.lastSeq) pollBuild();
  if (back) digestSoon(DIGEST_TAIL_MS);
}
// Reflects another document's staleness/in-progress build on its tab, and if that document's build finished in the
// background, says so on the status line with [열기] - a success for NOTICE_MS, a failure until [x] - and drops the
// meta cache (a fresh page when you switch back). A finished build of another document - or a new source of another
// Markdown or text document - is its update: said as that document's update message with [열기] (updates.ts
// checkDocUpdate, docs/handbook/viewer.md §새 소식).
function noteOtherDocs(list) {
  if (!Array.isArray(list) || !list.length) return;
  let redraw = false;
  list.forEach((fresh) => {
    const stored = docInfo(fresh.key);
    if (!stored) return;
    if (stored.stale_build !== fresh.stale_build || stored.building !== fresh.building) {
      stored.stale_build = fresh.stale_build;
      stored.building = fresh.building;
      redraw = true;
    }
    const src = stored.src_mtime;
    stored.src_mtime = fresh.src_mtime;
    stored.pages_build = fresh.pages_build;
    if (fresh.key !== DOC && rendersInBrowser(stored.kind) && src !== undefined && src !== fresh.src_mtime)
      checkDocUpdate(fresh.key, {});
    const was = DOC_SEQ.get(fresh.key);
    DOC_SEQ.set(fresh.key, fresh.build_seq);
    if (fresh.key === DOC || was === undefined || was === fresh.build_seq) return;
    META_BY.delete(fresh.key);
    redraw = true;
    if (fresh.last_state === BUILD_STATE.OK) checkDocUpdate(fresh.key, {});
    else if (fresh.last_state === BUILD_STATE.OK_ERRORS || fresh.last_state === BUILD_STATE.FAIL)
      lineNote(
        translateTemplate(fresh.last_state === BUILD_STATE.FAIL ? '{name} 빌드 실패' : '{name} 빌드에 LaTeX 오류', {
          name: stored.name,
        }),
        fresh.last_state === BUILD_STATE.FAIL ? NOTICE_KIND.ERR : NOTICE_KIND.WARN,
        { label: '열기', tip: '그 문서로 바꿔 오류를 봅니다', fn: () => switchDoc(fresh.key) },
        { literal: true },
      );
  });
  if (redraw) drawDocTabs();
}
function startLightPolling() {
  clearInterval(LIGHT_TIMER);
  LIGHT_TIMER = setInterval(pollLight, 5000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollLight();
    syncHiddenNotifyTimer();
  });
  window.addEventListener('focus', () => pollLight());
  syncHiddenNotifyTimer(); // catches it right away if already hidden at boot (a rare case) and notifications are on
}
// A list comparison's group without the pins whose events a message of a higher rank says (groupNote's less): the pins
// named '<type>:<id>' leave group[field] - numbers or pins - and each of `also` beside them, or null when none is left.
// Pure.
function newsWithout(type: string, field: string, ...also: string[]): (group: any, keys: string[]) => any {
  return (group, keys) => {
    const keep = group[field].map((x: any) => !keys.includes(type + ':' + (typeof x === 'number' ? x : x.id)));
    if (!keep.some(Boolean)) return null;
    const out = { ...group };
    [field, ...also].forEach((key) => {
      out[key] = group[key].filter((_: any, index: number) => keep[index]);
    });
    return out;
  };
}
// This tab's own close/drop/reopen/restore already said so where it happened, so the next loadPins()'s notePinChanges
// never announces the same transition again: only the first notePinChanges judgment right after markMine(id) is
// swallowed (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (a
// lost response), it's given up on and later values are announced normally. An action from another tab isn't in this
// map, so it's shown as usual.
const MY_ACTIONS = new Map();
function markMine(id) {
  MY_ACTIONS.set(id, Date.now() + 10000);
}
function consumeMine(id) {
  const until = MY_ACTIONS.get(id);
  if (until === undefined) return false;
  MY_ACTIONS.delete(id);
  return Date.now() <= until;
}
// Says on the status line what changed between two list refreshes (docs/handbook/viewer.md §알림 자리): pins sent to
// review ([보기], a dot on [검토 M]), dropped ([되살리기]) or closed by someone else, and an open pin whose location or
// figure element was lost or whose lines moved. What needs a look stays until [x] or its action and dots [핀 N];
// passing news (closed elsewhere, lines moved) goes after NOTICE_MS. An action this tab performed is swallowed
// (markMine).
function notePinChanges(previous, listed, dropped) {
  // previous is only the "open pins" this tab saw last time (PINS never holds done ones); listed is every open+closed
  // pin (all=1) from this GET. An id of previous that is in listed with done=true was completed; one not in listed at
  // all (neither open nor closed) was dropped. The two are told apart, so a pin a co-author deleted is never announced
  // to its author as "#N 이 완료되었습니다".
  if (!previous || !previous.length) return;
  const byId = new Map<number, Pin>(previous.map((pin) => [pin.id, pin]));
  const known = new Map<number, Pin>((listed || []).map((pin) => [pin.id, pin]));
  const dropById = new Map<number, Pin>((dropped || []).map((pin) => [pin.id, pin]));
  const closed: number[] = [],
    droppedIds: number[] = [],
    reviewed: number[] = [];
  byId.forEach((_, id) => {
    const current = known.get(id),
      state = current && pinState(current);
    if (current && state !== PIN_STATE.OPEN) {
      if (!consumeMine(id)) (state === PIN_STATE.REVIEW ? reviewed : closed).push(id);
    } else if (!current) {
      if (!consumeMine(id)) droppedIds.push(id);
    }
  });
  // Each kind of change is one message however many pins and polls it spans (groupNote): up to three pins by number,
  // more as a count with the first numbers after it ('핀 12개가 완료되었습니다 — #3, #5, #8 외 9개').
  const ids = (numbers: number[]) =>
    numbers
      .slice(0, 3)
      .map((id) => '#' + id)
      .join(', ') + (numbers.length > 3 ? ' ' + translateTemplate('외 {n}개', { n: numbers.length - 3 }) : '');
  const some = (numbers: number[], one, many) =>
    numbers.length <= 3
      ? translateTemplate(one, { ids: numbers.join(', #'), n: numbers.length })
      : translateTemplate(many, { n: numbers.length }) + ' — ' + ids(numbers);
  const merge = (older: any, newer: any) => ({ ...newer, ids: [...new Set([...older.ids, ...newer.ids])] });
  if (closed.length)
    groupNote(
      'done',
      { ids: closed },
      (group) => ({
        msg: some(group.ids, '#{ids} 이 완료되었습니다', '핀 {n}개가 완료되었습니다'),
        kind: NOTICE_KIND.OK,
        act: null,
        o: {
          life: NOTICE_LIFE.TIMER,
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('완료 {n}', { n: group.ids.length }),
        },
      }),
      merge,
    );
  if (reviewed.length)
    groupNote(
      'review',
      { ids: reviewed },
      (group) => ({
        msg:
          group.ids.length <= 3
            ? translateTemplate('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요', {
                ids: group.ids.join(', #'),
                n: group.ids.length,
              })
            : translateTemplate('핀 {n}개가 검토 대기로 넘어왔습니다', { n: group.ids.length }) +
              ' — ' +
              ids(group.ids),
        kind: NOTICE_KIND.OK,
        act: { label: '보기', tip: '검토 대기 핀으로 갑니다', fn: gotoReview },
        o: {
          keys: group.ids.map((id) => EVENT_TYPE.REVIEW_REQUESTED + ':' + id),
          dot: NOTICE_DOT.RV,
          literal: true,
          brief: translateTemplate('검토 대기 {n}', { n: group.ids.length }),
        },
      }),
      merge,
      newsWithout(EVENT_TYPE.REVIEW_REQUESTED, 'ids'),
    );
  // One dropped pin offers [되살리기]; several, the Trash they are in.
  if (droppedIds.length)
    groupNote(
      'drop',
      {
        ids: droppedIds,
        names: droppedIds.map((id) => {
          const rec = dropById.get(id);
          return (rec && who(rec.dropped_by)) || translate('다른 세션');
        }),
      },
      (group) => {
        const name = [...new Set(group.names)].join(', '),
          one = group.ids.length === 1,
          id = group.ids[0];
        return {
          msg: one
            ? translateTemplate('#{id}{o} {name}{p} 삭제함', {
                id,
                o: josa(id, '을', '를'),
                name,
                p: josaName(name, '이', '가'),
              })
            : translateTemplate('핀 {n}개를 {name}{p} 삭제함', {
                n: group.ids.length,
                name,
                p: josaName(name, '이', '가'),
              }) +
              ' — ' +
              ids(group.ids),
          kind: NOTICE_KIND.WARN,
          act: one
            ? { label: '되살리기', wait: true, fn: () => restorePin(id) }
            : { label: '휴지통', tip: '지운 핀을 휴지통에서 봅니다', fn: () => openTrash(id) },
          o: {
            keys: group.ids.map((id) => EVENT_TYPE.DROPPED + ':' + id),
            dot: NOTICE_DOT.SIDE,
            literal: true,
            brief: translateTemplate('삭제됨 {n}', { n: group.ids.length }),
          },
        };
      }, // translateTemplate() spoke the UI language; the name is as written
      (older, newer) => {
        // names stay beside their ids
        const add = newer.ids.map((id, index) => index).filter((index) => !older.ids.includes(newer.ids[index]));
        return {
          ids: [...older.ids, ...add.map((index) => newer.ids[index])],
          names: [...older.names, ...add.map((index) => newer.names[index])],
        };
      },
      newsWithout(EVENT_TYPE.DROPPED, 'ids', 'names'),
    );
  const lost: Pin[] = [],
    gone: Pin[] = [],
    moved: { id: number; delta: string; p: Pin }[] = [];
  (listed || [])
    .filter((pin) => pinState(pin) === PIN_STATE.OPEN)
    .forEach((pin) => {
      const was = byId.get(pin.id);
      if (!was) return;
      if (!was.stale && pin.stale) {
        lost.push(pin);
        return;
      }
      if (was.el_sync !== ELEMENT_SYNC.LOST && pin.el_sync === ELEMENT_SYNC.LOST) {
        gone.push(pin);
        return;
      } // a re-render lost a figure pin's element
      const move = /^moved ([+-]\d+)$/.exec(pin.sync || ''),
        earlierMove = /^moved ([+-]\d+)$/.exec(was.sync || '');
      if (move && pin.el_sync !== ELEMENT_SYNC.OK && (!earlierMove || earlierMove[1] !== move[1]))
        moved.push({ id: pin.id, delta: move[1], p: pin });
    });
  // A pin that lost its place asks for a new one: said on its own, and counted in its document's update message.
  lost.forEach((pin) => countPinMove(pin, true));
  gone.forEach((pin) => countPinMove(pin, true));
  const each = (numbers: number[], one, many) =>
    numbers.length === 1
      ? translateTemplate(one, { id: numbers[0] })
      : translateTemplate(many, { n: numbers.length }) + ' — ' + ids(numbers);
  if (lost.length)
    groupNote(
      'lost',
      { ids: lost.map((pin) => pin.id) },
      (group) => ({
        msg: each(group.ids, '#{id} 위치를 잃었습니다', '핀 {n}개가 위치를 잃었습니다'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: { dot: NOTICE_DOT.SIDE, literal: true, brief: translateTemplate('위치 잃음 {n}', { n: group.ids.length }) },
      }),
      merge,
    );
  if (gone.length)
    groupNote(
      'el-lost',
      { ids: gone.map((pin) => pin.id) },
      (group) => ({
        msg: each(group.ids, '#{id} 요소를 잃었습니다', '핀 {n}개가 요소를 잃었습니다'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: { dot: NOTICE_DOT.SIDE, literal: true, brief: translateTemplate('요소 잃음 {n}', { n: group.ids.length }) },
      }),
      merge,
    );
  // Lines that moved with a document's update are said in its update message; others pass by as one message.
  const said = moved.filter((x) => !countPinMove(x.p, false));
  if (said.length)
    groupNote(
      'moved',
      { moves: said.map((x) => ({ id: x.id, delta: x.delta })) },
      (group) => {
        const ms = group.moves.slice(-12);
        return {
          msg:
            ms.length === 1
              ? translateTemplate('#{id} 줄 {delta} 이동', { id: ms[0].id, delta: ms[0].delta })
              : translateTemplate('핀 {n}개 줄 이동', { n: group.moves.length }) +
                ' — ' +
                ms.map((x: any) => '#' + x.id + ' ' + x.delta).join(', '),
          kind: NOTICE_KIND.OK,
          act: null,
          o: { life: NOTICE_LIFE.TIMER, literal: true },
        };
      },
      (older, newer) => ({
        moves: [...older.moves.filter((x: any) => !newer.moves.some((y: any) => y.id === x.id)), ...newer.moves],
      }),
    );
}

// A pin's state: its `state`, else what its done and review flags say.
function pinState(pin: Pin) {
  return (pin && pin.state) || (pin && pin.done ? (pin.review ? PIN_STATE.REVIEW : PIN_STATE.DONE) : PIN_STATE.OPEN);
}
// Says on the status line when a pin that was awaiting review gets confirmed (done; passing news) or reopened (until
// [x], with a dot on [핀 N]) elsewhere. An action this tab performed (markMine) is swallowed.
function noteReviewChanges(previous, listed) {
  if (!previous || !previous.length) return;
  const known = new Map<number, Pin>((listed || []).map((pin) => [pin.id, pin]));
  const ok: { id: number; by: string }[] = [],
    back: { id: number; by: string }[] = [];
  previous.forEach((pin) => {
    const current = known.get(pin.id);
    if (!current) return;
    const state = pinState(current);
    if (state === PIN_STATE.REVIEW) return;
    if (consumeMine(pin.id)) return;
    (state === PIN_STATE.DONE ? ok : back).push({
      id: pin.id,
      by: who(state === PIN_STATE.DONE ? current.confirmed_by : current.reopened_by),
    });
  });
  // Each is one message however many pins (groupNote): one pin with who did it, more as a count.
  const text = (entries: { id: number; by: string }[], one, many) =>
    entries.length === 1
      ? translateTemplate(one, { id: entries[0].id }) + (entries[0].by ? ' · ' + entries[0].by : '')
      : translateTemplate(many, { n: entries.length }) +
        ' — ' +
        entries
          .slice(0, 3)
          .map((x) => '#' + x.id)
          .join(', ') +
        (entries.length > 3 ? ' ' + translateTemplate('외 {n}개', { n: entries.length - 3 }) : '');
  const merge = (older: any, newer: any) => ({
    pins: [...older.pins, ...newer.pins.filter((x) => !older.pins.some((y) => y.id === x.id))],
  });
  if (ok.length)
    groupNote(
      'confirmed',
      { pins: ok },
      (group) => ({
        msg: text(group.pins, '#{id} 확인됨', '핀 {n}개 확인됨'),
        kind: NOTICE_KIND.OK,
        act: null,
        o: {
          life: NOTICE_LIFE.TIMER,
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('확인됨 {n}', { n: group.pins.length }),
        },
      }),
      merge,
    );
  if (back.length)
    groupNote(
      'reopened',
      { pins: back },
      (group) => ({
        msg: text(group.pins, '#{id} 다시 열림', '핀 {n}개 다시 열림'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: {
          keys: group.pins.map((x) => EVENT_TYPE.REOPENED + ':' + x.id),
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('다시 열림 {n}', { n: group.pins.length }),
        },
      }),
      merge,
      newsWithout(EVENT_TYPE.REOPENED, 'pins'),
    );
}
// Sets LAST_PINS_REVISION, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setLastPinsRevision<Value extends typeof LAST_PINS_REVISION>(value: Value): Value {
  LAST_PINS_REVISION = value;
  return value;
}
// Sets LAST_SRC_MTIME, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLastSrcMtime<Value extends typeof LAST_SRC_MTIME>(value: Value): Value {
  LAST_SRC_MTIME = value;
  return value;
}
export {
  POLL_FAILS,
  markMine,
  notePinChanges,
  noteReviewChanges,
  pinState,
  pollLight,
  setLastPinsRevision,
  setLastSrcMtime,
  startLightPolling,
  syncHiddenNotifyTimer,
};
