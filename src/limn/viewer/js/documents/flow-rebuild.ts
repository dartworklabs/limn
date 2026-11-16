// ------------------------------------------------ PDF rebuild
// The reading spot: the page at the PDF scroller's top edge (or `offset` px below it) and how far down that page the
// edge is (frac, 0-1), with whether the scroller is at its very top on a touch screen (atTop); null with no pages. At
// the top edge a page's last pixel does not count; a line below it (offset: the reading line) is exact, so the strip,
// the keys and the panel name the page that line is on while any of it is. gap: with the edge in the space above that
// page (frac 0), how far under it the page's top stands. y and h: where that page's top stood under the scroller's top
// and its height, so restoreAnchor can tell a re-fit that moved nothing.
import {
  BUILD_ERR_BY,
  DOC,
  META,
  META_BY,
  COARSE_POINTER_QUERY,
  SIDE_OPEN,
  SWITCHSEQ,
  rendersInBrowser,
  setMeta,
} from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { announce, lineNote, sourceOk } from '../platform/notices.ts';
import { loadRevisions } from '../revisions/flow.ts';
import { drawMeta } from './view-meta.ts';
import { BUILD, pollBuild, pullSuffix } from './view-build-chip.ts';
import { buildDoc, pageSrc, reapplyScale } from '../pdf/view-pages.ts';
import { openVectorDocument } from '../pdf/flow-open.ts';
import { releaseAllVectorPages } from '../pdf/view-draw.ts';
import { buildMarkdownDoc } from '../markdown/view.ts';
import { pageUnderReadingLine } from '../verdict/flow-line.ts';
import { isComposingNow, afterComposition } from '../verdict/flow-reason.ts';
import { setBuildReadingPage } from '../verdict/view-panel.ts';
import { loadPins } from '../pins/flow-list.ts';
import { NOTICE_HOST, NOTICE_KIND } from '../platform/tables.ts';
import { $, $$ } from '../platform/dom.ts';
import { BUILD_STATE } from '../app/rules-tables.ts';
import { withDocQuery } from './state.ts';
function topAnchor(offset?) {
  const scroller = $('#left'),
    scrollerTop = scroller.getBoundingClientRect().top,
    top = scrollerTop + (offset || 0),
    atTop = COARSE_POINTER_QUERY.matches && scroller.scrollTop <= 0,
    edge = offset ? 0 : 1;
  for (const pageElement of $$('.pg')) {
    const rect = pageElement.getBoundingClientRect();
    if (rect.bottom > top + edge)
      return {
        page: +pageElement.dataset.page,
        frac: Math.max(0, (top - rect.top) / rect.height),
        gap: Math.max(0, rect.top - top),
        atTop,
        y: rect.top - scrollerTop,
        h: rect.height,
      };
  }
  return null;
}
// Scrolls the PDF back to a reading spot from topAnchor() after a re-fit, with the space above its page (gap): without
// it a spot between two pages would put the page's top on the edge, as much as that space off. On a touch screen -
// where the select mode lives - a spot taken at the very top stays at the top, so the space above page 1 (its margin,
// or the select mode's reserve that keeps the mode bar off its first line) is kept at whatever height it has. Nothing
// is written when the spot's page stands where it stood at the same height: Chromium ends a smooth scroll at any write
// of the offset, the same one too, so the band settling 200ms into a jump from the phone's sheet (the keyboard held it)
// would stop a long glide part way.
function restoreAnchor(anchor) {
  if (!anchor) return;
  const scroller = $('#left');
  if (anchor.atTop) {
    if (scroller.scrollTop > 0) scroller.scrollTop = 0;
    return;
  }
  const pageElement = document.getElementById('p' + anchor.page);
  if (!pageElement) return;
  const rect = pageElement.getBoundingClientRect(),
    scrollerTop = scroller.getBoundingClientRect().top;
  if (Math.abs(rect.top - scrollerTop - anchor.y) < 0.5 && Math.abs(rect.height - anchor.h) < 0.5) return;
  scroller.scrollTop += rect.top - scrollerTop + anchor.frac * rect.height - (anchor.gap || 0);
}
// The manuscript's reading spot (topAnchor) at the moment the changes view hid it, with its document, kept for the way
// back: while it is hidden there is no spot to read, and a build that changes the pages' sizes meanwhile (refreshDoc)
// moves the scroll offset the column keeps to another place. keepSpot() takes it as the view opens; returnToSpot() puts
// the column back on it when the pages show again - only if the offset left it by a pixel or more, so a visit that
// changed nothing leaves the column exactly where it was.
let SPOT = null as { a: NonNullable<ReturnType<typeof topAnchor>>; doc: string | null } | null;
function keepSpot() {
  const anchor = topAnchor();
  SPOT = anchor ? { a: anchor, doc: DOC } : null;
}
function returnToSpot() {
  const spot = SPOT;
  SPOT = null;
  if (!spot || spot.doc !== DOC || !$('#left').getClientRects().length) return;
  const now = topAnchor(),
    pageElement = document.getElementById('p' + spot.a.page);
  if (
    now &&
    pageElement &&
    now.page === spot.a.page &&
    now.atTop === spot.a.atTop &&
    Math.abs(now.frac - spot.a.frac) * pageElement.getBoundingClientRect().height < 1
  )
    return;
  restoreAnchor(spot.a);
}
// Apply a supplied meta snapshot, or fetch one for the current document. A switch away and back invalidates an
// in-flight refresh even when the document key matches again; its old pages must not replace the new visit. A failed
// read is said on the status line (api, NOTICE_HOST.LINE) and throws. A refresh means a new build of the document is
// here (a completed build, one met on returning to the document or on a pick): a failed request to rebuild it is over
// (rebuildSources). the meta snapshots refreshDoc has had to apply, counted (a waiting one is dropped once a newer one
// came)
let REFRESH_GEN = 0;
async function refreshDoc(meta?) {
  let anchor = topAnchor();
  const visitDoc = DOC,
    seq = SWITCHSEQ;
  const snapshot =
    meta === undefined
      ? (await api(withDocQuery('/api/meta'), { what: '화면 정보 읽기', where: NOTICE_HOST.LINE })).data
      : meta;
  if (visitDoc !== DOC || seq !== SWITCHSEQ) return;
  const gen = ++REFRESH_GEN;
  if (rendersInBrowser(snapshot.kind)) {
    META_BY.set(visitDoc, snapshot);
    setMeta(snapshot);
    drawMeta();
    buildMarkdownDoc();
    await loadPins();
    return;
  } // no pages: the source is drawn again
  // Building the pages again takes the reason field with them: a syllable being composed in it ends first, and the key
  // that ended it lets the field go (isComposingNow), and the spot is read again after the wait. A newer snapshot that
  // came meanwhile wins - applied at once (the same page count) or waiting too: this one is dropped, never put back
  // over it, which would roll the newer build back for good.
  if (!(META && snapshot.pages.length === META.pages.length) && isComposingNow()) {
    await afterComposition();
    if (visitDoc !== DOC || seq !== SWITCHSEQ || gen !== REFRESH_GEN) return;
    anchor = topAnchor();
  }
  rebuildSources(visitDoc).forEach(sourceOk);
  META_BY.set(visitDoc, snapshot);
  const same = META && snapshot.pages.length === META.pages.length;
  setMeta(snapshot);
  drawMeta();
  // The canvas was drawn from the old PDF - it's torn down to show the new PNG first, then redrawn once the new build's
  // PDF is opened. A page whose paper size changed (a figure drawn again larger) takes its new width at the same scale
  // (reapplyScale - which leaves the scale alone while the changes view hides the PDF area).
  if (same) {
    releaseAllVectorPages();
    $$('.pg').forEach((pageElement, index) => {
      const page = META.pages[index];
      pageElement.dataset.ptw = String(page.pt_w);
      pageElement.style.aspectRatio = page.pt_w + ' / ' + page.pt_h;
      pageElement.querySelector('img').src = pageSrc(page);
    });
    reapplyScale();
  } else {
    setBuildReadingPage(pageUnderReadingLine());
    try {
      buildDoc();
      restoreAnchor(anchor);
    } finally {
      setBuildReadingPage(0);
    }
  } // the reading page held until its spot is back
  restoreAnchor(anchor);
  openVectorDocument();
  if (document.body.classList.contains('revision-open')) loadRevisions();
  await loadPins();
}
// On ok_errors|fail, the panel itself is opened right away: it is where a failed build is said (with the pull's line,
// pullSuffix), and the status line's failure item (compact) and #build-err-chip (the desktop's chips, while the panel
// is not on screen: syncBuildErrChip) keep a way to open it again as long as BUILD.error exists. say = a build this
// visit watched has just failed: its title is read out as an alert too (rule 1) - the desktop's panel and chip are no
// live region.
function showBuildErr(build: any, say?: boolean) {
  BUILD.error = build;
  if (DOC) BUILD_ERR_BY.set(DOC, build);
  const panel = $('#build-err');
  const title = buildErrTitle(build);
  if (say) announce(title, true);
  const log = String(build.log_tail || build.log || '')
    .split('\n')
    .slice(-20)
    .join('\n');
  const close = html`<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button>`;
  const errors = (build.errors || []).map(
    (error) => html`<div class="dim">${error.line ? 'L' + error.line + ' · ' : ''}${error.msg}</div>`,
  );
  setHtml(
    panel,
    html`<div class="row"><b>${title}</b><span class="sp"></span>${close}</div>${errors}<pre class="nowrap">${log}</pre>`,
  );
  panel.hidden = false;
  syncBuildErrChip();
}
// The error sources of a document's rebuild (platform/notices.ts sourceEntry): the requests rebuild() sends, plain and
// forced (api's source is the method and URL). A failed [PDF 재빌드] says itself under its own; an answered one clears
// it, and so does a later build of that document, which refreshDoc shows.
function rebuildSources(doc: string | null): string[] {
  return ['/api/rebuild?async=1', '/api/rebuild?async=1&force=1'].map(
    (url) => 'POST ' + withDocQuery(url, doc || undefined),
  );
}
// The title of a build's failure (fail) or its LaTeX errors (ok_errors), with the pull's line: the error panel's, and
// what showBuildErr reads out.
function buildErrTitle(build: any): string {
  return (
    translate(
      build.state === BUILD_STATE.FAIL
        ? '빌드 실패 — 화면은 이전 PDF입니다'
        : 'PDF를 재빌드했지만 LaTeX 오류가 있습니다',
    ) + pullSuffix(build)
  );
}
// Closes the build error panel; its chip stays while the error does (syncBuildErrChip).
function hideBuildErr() {
  $('#build-err').hidden = true;
  syncBuildErrChip();
}
// #build-err-chip ('빌드 오류 · 다시 보기') shows while there is a build error whose panel is not on screen: closed, or
// inside a collapsed panel - where only the status chips float, so it is the one sign of a failed build on a collapsed
// desktop.
function syncBuildErrChip() {
  $('#build-err-chip').hidden = !BUILD.error || (SIDE_OPEN && !$('#build-err').hidden);
}
// docs/handbook/build-sync.md §비동기 재빌드: rebuild is async - the POST returns immediately, and the #build-chip
// poller (startBuildPolling) shows progress, then does the in-place swap and says so once it finishes. A build started
// by someone else is caught by the same poller. Its completion may update controls or start polling only while the
// initiating document visit remains active. BUILD.asked marks that this tab asked, so an unchanged rebuild (no new seq)
// still gets its answer; it is set only after any older in-flight poll settled, since that one may carry the previous
// rebuild's unchanged mark. force (only the status line's [그래도 빌드] of an unchanged rebuild passes it) asks for
// ?force=1: a cold build that never ends unchanged. A rebuild already running elsewhere (409) is a warning on the
// status line; a failed request an error there, with [다시 시도].
async function rebuild(force?) {
  const visitDoc = DOC,
    visit = SWITCHSEQ;
  try {
    const { status } = await api(withDocQuery('/api/rebuild?async=1' + (force === true ? '&force=1' : '')), {
      method: 'POST',
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

// [더보기]'s [PDF 내려받기]: saves the PDF of the build on screen (META.pages_build) of this document as a file. The
// server names it after the document (GET /pdf?download=1 adds Content-Disposition: attachment, docs/handbook/api.md);
// a click on a link that carries the download attribute is the browser's own save, so the page stays where it is.
// Nothing is sent when no build is on screen.
function downloadPdf() {
  if (!META || !META.pages_build) return;
  const link = document.createElement('a');
  link.href = withDocQuery('/pdf?build=' + encodeURIComponent(META.pages_build) + '&download=1');
  link.download = '';
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
export {
  downloadPdf,
  hideBuildErr,
  keepSpot,
  rebuild,
  refreshDoc,
  restoreAnchor,
  returnToSpot,
  showBuildErr,
  syncBuildErrChip,
  topAnchor,
};
