// ---------------------------------------------- Async build-progress chip (docs/handbook/build-sync.md §비동기 재빌드)
// BUILD.timer only exists while a build is actually running - /api/build is never hit every second once there's nothing
// to do (already settled into idle/ok/fail). There are only three places it starts: this tab pressing rebuild(),
// pollLight (the 5-second poll) seeing build.state==='running', and catching an already-running build at boot. A
// finished build is counted via build_seq (the server bumps it by 1 per build). BUILD.lastSeq is the value this tab has
// already processed - processing (swapping the screen, saying so) happens exactly once per seq. Neither the started_at
// string nor "was running ever seen" can count: they miss a build that finishes within a 5-second gap, and process one
// completion twice when a hidden tab comes back through two paths at once. The active document visit owns one poll
// timer, request and completion baseline; the error panel follows that visit. BUILD.cur is the running build's last
// /api/build answer (null when none runs): the status line reads its phase and seconds. BUILD.unchanged is {pull} while
// the status line answers an unchanged rebuild of this tab (buildUnchanged), else null.
import { BUILD_ERR_BY, DOC, DOC_SEQ, META, knownMeta, SWITCHSEQ, buildsFromSource } from '../app/state.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { lineNote } from '../platform/notices.ts';
import { checkDocUpdate } from './flow-updates.ts';
import { buildUnchanged } from './view-status.ts';
import { hideBuildErr, refreshDoc, showBuildErr } from './flow-rebuild.ts';
import { NOTICE_KIND, NOTICE_LIFE, tableEntry } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { BUILD_STATE, PULL_STATE } from '../app/rules-tables.ts';
import { withDocQuery } from './state.ts';
interface BuildState {
  timer: ReturnType<typeof setInterval> | null;
  error: BuildStatus | null;
  lastSeq: number | null;
  booted: boolean;
  inflight: Promise<void> | null;
  asked: boolean;
  cur: BuildStatus | null;
  unchanged: { pull: string } | null;
}
const BUILD: BuildState = {
  timer: null,
  error: null,
  lastSeq: null,
  booted: false,
  inflight: null,
  asked: false,
  cur: null,
  unchanged: null,
};
// Each sets one field of BUILD for another module that changes it (ADR-0042 D1): the assignment, nothing more.
function setBuildError(value: typeof BUILD.error) {
  BUILD.error = value;
}
function setBuildLastSeq(value: typeof BUILD.lastSeq) {
  BUILD.lastSeq = value;
}
function setBuildAsked(value: boolean) {
  BUILD.asked = value;
}
function setBuildUnchanged(value: typeof BUILD.unchanged) {
  BUILD.unchanged = value;
}
// Reset the visible build controls and baseline when a different document takes the screen.
function resetBuildForDoc() {
  if (BUILD.timer) {
    clearInterval(BUILD.timer);
    BUILD.timer = null;
  }
  BUILD.cur = null;
  BUILD.unchanged = null;
  $('#build-chip').hidden = true;
  $('#btn-rebuild').disabled = false;
  const meta = knownMeta();
  BUILD.lastSeq = typeof meta.build_seq === 'number' ? meta.build_seq : 0;
  BUILD.asked = false;
  BUILD.error = BUILD_ERR_BY.get(DOC) || null;
  if (BUILD.error) hideBuildErr();
  else {
    $('#build-err').hidden = true;
    $('#build-err-chip').hidden = true;
  }
  BUILD.booted = true;
  if (BUILD.inflight) BUILD.inflight.then(() => pollBuild());
  else pollBuild();
}
function buildChipText(build: BuildStatus) {
  const label =
    tableEntry(
      { pull: '원격 main 당겨오는 중', copy: '원고 복사 중', latex: 'LaTeX 컴파일 중', render: '쪽 그리는 중' },
      build.phase,
    ) || '재빌드 중';
  const elapsed = Math.round(build.elapsed_s || 0),
    last = build.last_s ? ' ' + translateTemplate('(지난번 {s}초)', { s: Math.round(build.last_s) }) : '';
  return translate(label) + ' · ' + translateTemplate('{s}초', { s: elapsed }) + last;
}
// --git-pull (docs/handbook/build-sync.md §재빌드 전 원격 main 당겨오기): appends one line about the pull result to the
// build's completion (the status line's message, or the error panel's title). ok gets the applied commit range,
// skipped/error just the reason - up_to_date has nothing worth reporting, so nothing is appended.
function pullSuffix(build: BuildStatus) {
  const pull = build && build.pull;
  if (!pull || !pull.state) return '';
  if (pull.state === PULL_STATE.OK)
    return (
      ' · ' +
      translateTemplate('원격 반영 {range}', {
        range: String(pull.head_before || '?').slice(0, 7) + '..' + String(pull.head_after || '?').slice(0, 7),
      })
    );
  if (pull.state === PULL_STATE.SKIPPED || pull.state === PULL_STATE.ERROR)
    return (
      ' · ' +
      translateTemplate(pull.state === PULL_STATE.ERROR ? 'git pull 실패({reason})' : 'git pull 건너뜀({reason})', {
        reason: pull.reason || '?',
      })
    );
  return '';
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
    BUILD.cur = build;
    BUILD.unchanged = null;
    chip.hidden = false;
    chip.textContent = buildChipText(build);
    $('#btn-rebuild').disabled = true;
    if (!BUILD.timer) BUILD.timer = setInterval(pollBuild, 1000);
    BUILD.booted = true;
    return;
  }
  BUILD.cur = null;
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
      BUILD.error = null;
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
export {
  BUILD,
  setBuildError,
  setBuildLastSeq,
  setBuildAsked,
  setBuildUnchanged,
  pollBuild,
  pullSuffix,
  resetBuildForDoc,
  startBuildPolling,
};
