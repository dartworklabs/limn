import { BUILD_ERR_BY, DOC, META, knownMeta, SWITCHSEQ, DOC_SEQ, buildsFromSource } from '../app/state.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { lineNote } from '../platform/notices.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { BUILD_STATE, PULL_STATE } from '../app/rules-tables.ts';
import { withDocQuery } from './state.ts';
import { hideBuildErr, refreshDoc, showBuildErr } from './flow-rebuild.ts';
import { SHOWN_BUILD, setBuildUnchanged, setBuildError, setCurrentBuild } from './state-build.ts';
import { checkDocUpdate } from './flow-updates.ts';
import { buildChipText, pullSuffix } from './view-build-chip.ts';
import { buildUnchanged } from './view-status.ts';
// ---------------------------------------------- Async build-progress chip (docs/handbook/build-sync.md §비동기 재빌드)
// BUILD.timer only exists while a build is actually running - /api/build is never hit every second once there's nothing
// to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot. A
// finished build is counted via build_seq (the server bumps it by 1 per build). BUILD.lastSeq is the value this tab has
// already processed - processing (swapping the screen, saying so) happens exactly once per seq. Neither the started_at
// string nor "was running ever seen" can count: they miss a build that finishes within a 5-second gap, and process one
// completion twice when a hidden tab comes back through two paths at once. The active document visit owns one poll
// timer, request and completion baseline; the error panel follows that visit. SHOWN_BUILD.cur is the running build's last
// /api/build answer (null when none runs): the status line reads its phase and seconds. SHOWN_BUILD.unchanged is {pull} while
// the status line answers an unchanged rebuild of this tab (buildUnchanged), else null.
interface BuildState {
  timer: ReturnType<typeof setInterval> | null;
  lastSeq: number | null;
  booted: boolean;
  inflight: Promise<void> | null;
  asked: boolean;
}
const BUILD: BuildState = {
  timer: null,
  lastSeq: null,
  booted: false,
  inflight: null,
  asked: false,
};
function setBuildLastSeq(value: typeof BUILD.lastSeq) {
  BUILD.lastSeq = value;
}
// Reset the visible build controls and baseline when a different document takes the screen.
function resetBuildForDoc() {
  if (BUILD.timer) {
    clearInterval(BUILD.timer);
    BUILD.timer = null;
  }
  setCurrentBuild(null);
  setBuildUnchanged(null);
  $('#build-chip').hidden = true;
  $('#btn-rebuild').disabled = false;
  const meta = knownMeta();
  BUILD.lastSeq = typeof meta.build_seq === 'number' ? meta.build_seq : 0;
  BUILD.asked = false;
  setBuildError(BUILD_ERR_BY.get(DOC) || null);
  if (SHOWN_BUILD.error) hideBuildErr();
  else {
    $('#build-err').hidden = true;
    $('#build-err-chip').hidden = true;
  }
  BUILD.booted = true;
  if (BUILD.inflight) BUILD.inflight.then(() => pollBuild());
  else pollBuild();
}
// Single-flight: if a request is already in flight, that same promise is returned instead of sending a new one (even if
// the 1-second timer, visibilitychange, focus, and pollLight all call it together, /api/build only goes out once and
// completion is only processed once).
function pollBuild() {
  if (document.hidden) return Promise.resolve(); // the request is never even sent while the tab is hidden
  if (BUILD.inflight) return BUILD.inflight;
  BUILD.inflight = pollBuildOnce().finally(() => {
    BUILD.inflight = null;
  });
  return BUILD.inflight;
}
// One /api/build poll for the document on screen: shows or hides the progress chip and the 1-second timer, and
// processes a finished build exactly once per `seq` (refresh the pages; a success says so on the status line for
// NOTICE_MS, a failure or LaTeX errors open the error panel, and the line's failure item and the chips keep it). A
// rebuild this tab asked for that kept the pages (unchanged: true, the same seq) gets one "no changes" answer on the
// status line whose [그래도 빌드] forces a cold rebuild (buildUnchanged). A reply that arrives after a document switch
// is dropped. Resolves with nothing and never throws; a failed request is ignored (the next poll retries).
async function pollBuildOnce() {
  let build;
  const visitDoc = DOC,
    visit = SWITCHSEQ;
  try {
    build = (await api('GET /api/build', { query: withDocQuery('?log=1'), what: '빌드 상태', silent: true })).data;
  } catch (error) {
    return;
  }
  // showDoc queries again after a switch, including a return to this key
  if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
  const chip = $('#build-chip');
  if (build.state === BUILD_STATE.RUNNING) {
    setCurrentBuild(build);
    setBuildUnchanged(null);
    chip.hidden = false;
    chip.textContent = buildChipText(build);
    $('#btn-rebuild').disabled = true;
    if (!BUILD.timer) BUILD.timer = setInterval(pollBuild, 1000);
    BUILD.booted = true;
    return;
  }
  setCurrentBuild(null);
  chip.hidden = true;
  $('#btn-rebuild').disabled = false;
  if (BUILD.timer) {
    clearInterval(BUILD.timer);
    BUILD.timer = null;
  } // polling stops once there's nothing left to watch
  const seq = typeof build.seq === 'number' ? build.seq : 0;
  const booted = BUILD.booted;
  BUILD.booted = true;
  if (BUILD.lastSeq === null) BUILD.lastSeq = seq;
  if (seq === BUILD.lastSeq && BUILD.asked && build.unchanged === true) {
    BUILD.asked = false;
    buildUnchanged(build);
  } else if (seq !== BUILD.lastSeq) {
    // This tab's own rebuild that pulled nothing new is an answer to it (the 6 s line below); any other new build on
    // screen - a merge pulled, another session's rebuild, a figure or PDF that came again - is the document's update
    // (documents/flow-updates.ts).
    const mine = BUILD.asked && !(build.pull && build.pull.state === PULL_STATE.OK);
    BUILD.lastSeq = seq;
    BUILD.asked = false; // claimed before the await - so the same completion is never processed twice
    DOC_SEQ.set(visitDoc, seq);
    try {
      await refreshDoc();
    } catch (error) {}
    if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
    const seconds = Math.round(build.elapsed_s || 0);
    if (build.state === BUILD_STATE.OK) {
      // This tab's rebuild asked for before the first meta came, whose refresh failed too, has no document to word its
      // end by: it ends here and says nothing, as the build's next poll finds it already seen.
      if (mine && !META) return;
      if (mine)
        lineNote(
          translate(!buildsFromSource(knownMeta().kind) ? 'PDF가 바뀌어 쪽을 새로 그렸습니다' : 'PDF 재빌드 완료') +
            ' · ' +
            translateTemplate('{n}쪽', { n: knownMeta().pages.length }) +
            ' · ' +
            translateTemplate('{s}초', { s: seconds }) +
            pullSuffix(build),
          NOTICE_KIND.OK,
          null,
          { life: NOTICE_LIFE.TIMER },
        );
      setBuildError(null);
      BUILD_ERR_BY.delete(visitDoc);
      hideBuildErr();
      // its panel opens and it is read out; the line and the chips keep the failure
    } else if (build.state === BUILD_STATE.OK_ERRORS || build.state === BUILD_STATE.FAIL) showBuildErr(build, true);
    // a failed build left the pages as they were
    if (build.state !== BUILD_STATE.FAIL) checkDocUpdate(visitDoc || '', { mine });
  } else if (!booted && (build.state === BUILD_STATE.FAIL || build.state === BUILD_STATE.OK_ERRORS)) {
    // a freshly opened tab - a build that already failed just opens the panel/chip (leaves a way to look at it again)
    showBuildErr(build);
  }
}
function startBuildPolling() {
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) pollBuild();
  });
  window.addEventListener('focus', () => pollBuild());
  // once at boot - if a build is already running (started by another session), this turns on the 1-second poll
  pollBuild();
}

// docs/handbook/build-sync.md §비동기 재빌드: rebuild is async - the POST returns immediately, and the #build-chip
// poller (startBuildPolling) shows progress, then does the in-place swap and says so once it finishes. A build started
// by someone else is caught by the same poller. Its completion may update controls or start polling only while the
// initiating document visit remains active. BUILD.asked marks that this tab asked, so an unchanged rebuild (no new seq)
// still gets its answer; it is set only after any older in-flight poll settled, since that one may carry the previous
// rebuild's unchanged mark. force (only the status line's [그래도 빌드] of an unchanged rebuild passes it) asks for
// ?force=1: a cold build that never ends unchanged. A rebuild already running elsewhere (409) is a warning on the
// status line; a failed request an error there, with [다시 시도].
async function rebuild(force?: boolean) {
  const visitDoc = DOC,
    visit = SWITCHSEQ;
  try {
    const { status } = await api('POST /api/rebuild', {
      query: withDocQuery('?async=1' + (force === true ? '&force=1' : '')),
      what: 'PDF 재빌드',
      where: NOTICE_HOST.LINE,
      retry: () => rebuild(force),
      expect: [409],
    });
    if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
    if (status === 409) {
      lineNote('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요', NOTICE_KIND.WARN);
      return;
    }
    $('#build-err').hidden = true;
    // If a request already went out before this POST, its completion is awaited before asking again - that request
    // carries a stale state (ok) and would never turn on 1-second polling. Completion is distinguished by build_seq, so
    // this tab has nothing separate to remember.
    if (BUILD.inflight) {
      try {
        await BUILD.inflight;
      } catch (error) {}
    }
    if (visitDoc !== DOC || visit !== SWITCHSEQ) return;
    BUILD.asked = true;
    await pollBuild();
  } catch (error) {}
}
export { BUILD, setBuildLastSeq, pollBuild, resetBuildForDoc, startBuildPolling, rebuild };
