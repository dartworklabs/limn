// ------------------ Auto sync - lightweight meta polling (docs/handbook/build-sync.md §자동 동기화 (가벼운 meta 폴링))
import { DOC, DOC_SEQ, META_BY, SWITCHSEQ, rendersInBrowser } from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { API_WAIT, api } from '../platform/api.ts';
import { announce, digestBegin, digestSoon, lineNote } from '../platform/notices.ts';
import { drawDocTabs } from './view-tabs.ts';
import { switchDoc } from './flow-switch.ts';
import { updateStaleBadge, updateSyncBadge } from './view-meta.ts';
import { notifyHandle, notifyOn, notifyQuery } from '../pins/flow-notification.ts';
import { BUILD, pollBuild } from './view-build-chip.ts';
import { DIGEST_TAIL_MS, awayTitle, checkDocUpdate, checkVersion, expectUpdate, versionDue } from './flow-updates.ts';
import { MARKDOWN_VIEW, buildMarkdownDoc, checkTreeImages } from '../markdown/view.ts';
import { OFF, offlineFlush } from '../offline/flow.ts';
import { loadPins } from '../pins/flow-list.ts';
import { NOTICE_KIND } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { BUILD_STATE, SYNC_STATE } from '../app/rules-tables.ts';
import { isMarkdownDoc, docInfo, withDocQuery } from './state.ts';
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
// this poll and the build it may set going say is gathered into one message (platform/notices.ts digestBegin,
// docs/handbook/viewer.md §새 소식); a poll back from that, or one every VERSION_EVERY_MS, asks which Limn the server
// runs (documents/flow-updates.ts checkVersion).
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
  // the connection is back: the pins kept while it was gone are written (offline/flow.ts)
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
    // a tree image rewritten on disk shows without a reload (markdown/view.ts)
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
// Markdown or text document - is its update: said as that document's update message with [열기]
// (documents/flow-updates.ts checkDocUpdate, docs/handbook/viewer.md §새 소식).
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
// Whether this tab should keep a pin instead of sending it: the light poll has lost the server (POLL_FAILS, the same
// judgment the status line's '연결 끊김' uses) or the browser says there is no network at all.
function offlineNow() {
  return POLL_FAILS >= 2 || navigator.onLine === false;
}

export {
  POLL_FAILS,
  pollLight,
  setLastPinsRevision,
  setLastSrcMtime,
  startLightPolling,
  syncHiddenNotifyTimer,
  offlineNow,
};
