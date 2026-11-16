// One changes-view visit owns the selected commit, source text and request sequence. overlay is a figure document's two
// builds from /api/revisions (null for any other document), side the one its overlay shows, history whether it has commits.
// Issue #188: base is a range's old side ('' for one commit against its first parent); rows the loaded commits (newest
// first, REVISION_PAGE a page) of rowsDoc, more whether older ones remain; range the quick range and its ends (RevRange);
// seen this browser's last-seen commit of the document, seenState what the server said of it (SEEN_STATE), seenN how many
// commits it compares with the newest and seenIds which (the server's count, never the list's positions); rangeIds the
// commits the shown range compares (the server's commit_ids; null until it answers), rangeBase its old side; listOpen
// whether the phone shows every loaded row; rangeLine the range's summary for the status line, and rangeN its commit and file
// counts (the rendered compare's status line takes them, md-compare.js sayCompareStatus).
import {
  $,
  $$,
  DIFF_FORMAT,
  DOC,
  DONE_ALL,
  LAYOUT,
  LAYOUT_MODE,
  OPEN_ALL,
  OVERLAY_SIDE,
  PIN_STATE,
  RANGE_MODE,
  REVIEW_ALL,
  REVISION_STATE,
  SCOPE_MODE,
  SCOPE_SOURCE,
  SEEN_STATE,
  SWITCHSEQ,
  T,
  VIEW_MODE,
} from './core.ts';
import { html, ic, setHtml } from './markup.ts';
import { ccHtml } from './hidden-chars.ts';
import { errText, tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { docInfo, dq, isRegion, pdoc } from './doc-tabs.ts';
import { drawNavView, drawPos, switchDoc } from './doc-switch.ts';
import { canConfirmReview, confirmAccessText } from './boot.ts';
import { pinState } from './polling.ts';
import { PT_PX, boundK } from './pages.ts';
import { PDFJS_V, VEC } from './pdf-open.ts';
import { updateSectionStrip } from './outline.ts';
import { vecSchedule } from './pdf-draw.ts';
import { searchOffer } from './search.ts';
import {
  RZ,
  disposeRevisionZoom,
  drawRevisionZoom,
  mountRevisionPdf,
  resizeRevisionPdf,
  revisionPdfActive,
} from './revision-zoom.ts';
import { setSide } from './layout.ts';
import { rng } from './levels.ts';
import { pinPlace } from './figure.ts';
import { isMdDoc } from './md-surface.ts';
import { MDC, mdcClear, mdcDrawNav, mdcDrawn, mdcRestatus, mdcShow } from './md-compare.ts';
import { isMe, markHitSides } from './list.ts';
import { keepSpot, returnToSpot } from './rebuild.ts';
import { segRove } from './events.ts';
const REV = {
  seq: 0,
  files: [] as { name: string; text: string }[],
  whole: '',
  commit: '',
  sourceCommit: '',
  format: DIFF_FORMAT.PDF as string,
  scope: null as any,
  other: '',
  target: null as RevTarget | null,
  pdfCommit: '',
  back: null as string | null,
  overlay: null as RevisionOverlay | null,
  side: OVERLAY_SIDE.CUR as string,
  history: false,
  base: '',
  rows: [] as RevisionRow[],
  rowsDoc: '',
  more: false,
  range: { mode: RANGE_MODE.ONE, start: '', end: '', endSet: false } as RevRange,
  seen: null as RevSeen | null,
  seenState: SEEN_STATE.NONE as string,
  seenN: 0,
  seenIds: new Set() as Set<string>,
  rangeIds: null as string[] | null,
  rangeBase: '',
  listOpen: false,
  rangeLine: '',
  rangeN: null as { commits: number; files: number } | null,
  want: null as { base: string; top: string } | null,
};
const REVISION_PAGE = 30; // rows of one /api/revisions page (the server's history window is 500, api.md)
const REVISION_RECENT = 12; // the commits [변경 보기] picks a pin's commit among - the server resolves a close_ref among the same
const REVISION_PHONE_ROWS = 5; // rows the phone's list shows before [더 보기]
// v0.3 (docs/handbook/viewer.md §변경 보기): a pin's view of a commit. REV.scope is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}); REV_PDF holds the comparison PDF's toggle - whole commit or only this pin.
const REV_SCOPE = { whole: false, partial: false, fallback: false };
const REV_PDF = {
  doc: null as any,
  loading: null as any,
  observer: null as IntersectionObserver | null,
  tasks: new Set<{ cancel(): void }>(),
};
function revisionFiles(patch) {
  const starts: { at: number; head: string }[] = [];
  const fileHeader = /^diff --git .+$/gm;
  let match;
  while ((match = fileHeader.exec(patch)) !== null) starts.push({ at: match.index, head: match[0] });
  return starts.map((start, index) => {
    const pathAt = start.head.lastIndexOf(' b/');
    return {
      name: pathAt >= 0 ? start.head.slice(pathAt + 3) : tl('파일 {n}', { n: index + 1 }),
      text: patch.slice(start.at, index + 1 < starts.length ? starts[index + 1].at : undefined),
    };
  });
}
// A patch as Html of numbered lines (file, hunk, add, del, context, meta). The code itself is the manuscript's text, so
// it is translate="no"; the lines are text, each character that would hide or reorder a line in its box (ccHtml) - a
// change a person reviews never reads as another text. The CR a CRLF file's line ends in is that line end, not text: left out.
function renderRevisionDiff(patch) {
  const lines = String(patch || '').split('\n');
  if (lines[lines.length - 1] === '') lines.pop();
  let oldLine = null as number | null,
    newLine = null as number | null,
    inHunk = false;
  return html`${lines.map((line) => {
    let kind = 'meta',
      number = '' as number | string;
    if (line.startsWith('diff --git ')) {
      kind = 'file';
      inHunk = false;
      oldLine = newLine = null;
    } else if (line.startsWith('@@ ')) {
      kind = 'hunk';
      inHunk = true;
      const at = /^@@ -(\d+)(?:,\d+)? \+(\d+)/.exec(line);
      oldLine = at ? Number(at[1]) : null;
      newLine = at ? Number(at[2]) : null;
    } else if (!inHunk && (line.startsWith('--- ') || line.startsWith('+++ '))) {
      kind = 'meta';
    } else if (line.startsWith('+')) {
      kind = 'add';
      if (newLine !== null) number = newLine++;
    } else if (line.startsWith('-')) {
      kind = 'del';
      if (oldLine !== null) number = oldLine++;
    } else if (line.startsWith(' ')) {
      kind = 'context';
      if (newLine !== null) {
        number = newLine++;
        if (oldLine !== null) oldLine++;
      }
    }
    return html`<span class="rd-line rd-${kind}"><span class="rd-no" aria-hidden="true">${number}</span><span class="rd-code" translate="no">${ccHtml(line.endsWith('\r') ? line.slice(0, -1) : line)}</span></span>`;
  })}`;
}
function renderRevisionFile() {
  const choice = $('#revision-file').value,
    index = Number(choice);
  setHtml(
    $('#revision-diff'),
    renderRevisionDiff(choice === 'all' ? REV.whole : (REV.files[index] && REV.files[index].text) || REV.whole),
  );
}
// The rest of the commit, folded under one control (v0.3). Hidden when the pin owns the whole commit or the view is not a pin's.
function drawRevisionOther(scope) {
  const toggle = $('#revision-other-toggle'),
    rest = $('#revision-other');
  rest.hidden = true;
  rest.replaceChildren();
  toggle.setAttribute('aria-expanded', 'false');
  REV.other =
    scope && scope.mode === SCOPE_MODE.PIN
      ? String(scope.other_diff || '') +
        (scope.other_truncated
          ? '\n\n' + tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.')
          : '')
      : '';
  toggle.hidden = !REV.other;
  if (REV.other) toggle.querySelector('span').textContent = tl('이 커밋의 다른 변경 {n}곳', { n: scope.other });
}
function toggleRevisionOther() {
  const toggle = $('#revision-other-toggle'),
    rest = $('#revision-other'),
    open = toggle.getAttribute('aria-expanded') !== 'true';
  toggle.setAttribute('aria-expanded', String(open));
  rest.hidden = !open;
  if (open && !rest.firstChild) setHtml(rest, renderRevisionDiff(REV.other));
}
// [커밋 전체 비교]: shown only for the PDF of a pin that owns part of the commit, and not after a fallback (there is nothing to switch to).
function syncRevisionWhole() {
  const button = $('#revision-whole');
  button.hidden = !(
    REV.format === DIFF_FORMAT.PDF &&
    revisionPinFor(REV.commit) &&
    REV_SCOPE.partial &&
    !REV_SCOPE.fallback
  );
  button.setAttribute('aria-pressed', String(REV_SCOPE.whole));
}
// The pin whose hunks a commit's view is scoped to: only the commit picked for the pin ([변경 보기]); any other commit
// chosen in the list is shown whole (review M1 - another commit's lines are not this pin's), and so is a range (#188:
// pin scoping and ranges do not combine yet; the server refuses pin with base).
function revisionPinFor(id) {
  const target = REV.target;
  return target && !target.region && target.commit && id === target.commit && !REV.base ? target : null;
}
function setRevisionWhole(on) {
  REV_SCOPE.whole = !!on;
  ++REV.seq;
  REV.pdfCommit = '';
  clearRevisionPdf();
  $('#revision-warning').hidden = true;
  setRevisionFormat(DIFF_FORMAT.PDF);
}
function revisionCurrent(seq, docKey, id) {
  return seq === REV.seq && docKey === DOC && id === REV.commit && document.body.classList.contains('revision-open');
}
/** Release comparison rendering and PDF.js resources on visit or scope change. */
function clearRevisionPdf() {
  disposeRevisionZoom();
  if (REV_PDF.observer) {
    REV_PDF.observer.disconnect();
    REV_PDF.observer = null;
  }
  REV_PDF.tasks.forEach((task) => {
    try {
      task.cancel();
    } catch (error) {}
  });
  REV_PDF.tasks.clear();
  if (REV_PDF.loading) {
    try {
      void REV_PDF.loading.destroy().catch(() => {});
    } catch (error) {}
    REV_PDF.loading = null;
  }
  REV_PDF.doc = null;
  $('#revision-pdf').replaceChildren();
}
// The format a document's changes show for the one asked (docs/handbook/viewer.md §변경 보기): the source diff when asked; a
// document drawn from Markdown (drawn) its rendered compare otherwise; the source diff always for another document with no
// comparison PDF (source: one the browser draws, a text document); otherwise a figure document's overlay of two builds, and a
// LaTeX document's comparison PDF - never the overlay. Pure.
function revisionFormatFor(asked, figure, source, drawn) {
  if (asked === DIFF_FORMAT.SOURCE) return DIFF_FORMAT.SOURCE;
  if (drawn && !figure) return DIFF_FORMAT.RENDERED;
  return source && !figure ? DIFF_FORMAT.SOURCE : figure ? DIFF_FORMAT.OVERLAY : DIFF_FORMAT.PDF;
}
// Shows REV.format: the pressed tab, the pane, [이전 | 지금] with the overlay, and the overlay's status line on a figure
// document (its source diff has none). Loads nothing.
function drawRevisionFormat() {
  $('#revision-pdf-tab').setAttribute('aria-pressed', String(REV.format === DIFF_FORMAT.PDF));
  $('#revision-overlay-tab').setAttribute('aria-pressed', String(REV.format === DIFF_FORMAT.OVERLAY));
  $('#revision-source-tab').setAttribute('aria-pressed', String(REV.format === DIFF_FORMAT.SOURCE));
  $('#revision-rendered-tab').setAttribute('aria-pressed', String(REV.format === DIFF_FORMAT.RENDERED));
  $('#revision-rendered').hidden = REV.format !== DIFF_FORMAT.RENDERED;
  mdcDrawNav();
  $('#revision-view').dataset.format = REV.format;
  $('#revision-pdf').hidden = REV.format !== DIFF_FORMAT.PDF;
  $('#revision-source').hidden = REV.format !== DIFF_FORMAT.SOURCE;
  $('#revision-overlay').hidden = $('#revision-side').hidden = REV.format !== DIFF_FORMAT.OVERLAY;
  if (REV.overlay)
    $('#revision-status').textContent = REV.format === DIFF_FORMAT.OVERLAY ? overlayStatus(REV.overlay) : '';
}
/** Switch formats while retaining comparison scale for the selected commit. */
function setRevisionFormat(format) {
  REV.format = revisionFormatFor(format, !!REV.overlay, isMdDoc(), mdcDrawn());
  drawRevisionFormat();
  if (REV.format === DIFF_FORMAT.RENDERED && REV.commit) {
    if (MDC.key !== revKey()) mdcShow(REV.commit, REV.base, REV.seq, DOC);
    else $('#revision-status').textContent = MDC.line;
    // a range's list painting and its last-seen count come with its source diff's answer: read it beside the compare
    if (REV.base && REV.sourceCommit !== revKey()) loadRevisionSource(REV.commit, REV.seq, DOC);
  }
  if (REV.format === DIFF_FORMAT.SOURCE && !REV.base && mdcDrawn()) $('#revision-status').textContent = '';
  if (REV.format === DIFF_FORMAT.SOURCE && REV.commit && REV.sourceCommit !== revKey())
    loadRevisionSource(REV.commit, REV.seq, DOC);
  if (REV.format === DIFF_FORMAT.SOURCE && REV.base && REV.sourceCommit === revKey())
    $('#revision-status').textContent = REV.rangeLine;
  // The comparison PDF is only built when that format is actually viewed - [변경 보기] and a range go straight to the source diff, so neither wastes a latexdiff build.
  if (REV.format === DIFF_FORMAT.PDF && REV.commit && REV.pdfCommit !== revKey()) {
    REV.pdfCommit = revKey();
    $('#revision-status').textContent = '비교 PDF 상태를 확인하는 중입니다.';
    loadRevisionPdf(REV.commit, REV.seq, DOC);
  }
  syncRevisionWhole();
  drawRevisionZoom();
  if (revisionPdfActive()) resizeRevisionPdf();
  if (REV.format === DIFF_FORMAT.OVERLAY && REV.target) scrollOverlayTo(REV.target.page);
  if (REV.target) revTargetNote();
}
// Shows the manuscript or the changes view: the nav bar's tabs, the navigation sheet's switch and the phone's position button
// ([변경사항 ▾] in the changes view) follow; leaving the changes view forgets the pin it was opened for and redraws the pages.
// The mark badges' press areas are measured again as the pages show (markHitSides: marks drawn meanwhile had no boxes).
function setViewMode(mode) {
  const revisions = mode === VIEW_MODE.REVISIONS;
  if (!revisions && document.body.classList.contains('revision-open')) leaveRevisions();
  if (revisions && !document.body.classList.contains('revision-open')) keepSpot(); // the pages are still drawn: the spot the way back returns to
  document.body.classList.toggle('revision-open', revisions);
  $('#view-manuscript').setAttribute('aria-pressed', String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed', String(revisions));
  if (!revisions) {
    REV.target = null;
    mdcClear();
  }
  if (revisions) loadRevisions();
  else {
    ++REV.seq;
    clearRevisionPdf();
    setRevisionOverlay(null);
    $('#revision-pin').hidden = true;
    revTargetActs();
    boundK();
    returnToSpot();
    if (VEC.doc) vecSchedule(0);
    updateSectionStrip();
    markHitSides();
  }
  drawNavView();
  drawPos();
  searchOffer(); // the changes view has no search
}
// Reads the document's recent commits into the changes view. Without history (not Git, a view-only PDF, no recent commit, or
// more history files than the server names one by one: reason too_many_files) the one reason line stays and the unusable
// [변경 PDF] [소스 diff] and the comparison note are hidden; a pin's guide line stays.
// A figure document's answer carries its two builds (overlay): its [겹쳐 보기] takes the place of [변경 PDF] and opens first,
// with or without history; its [소스 diff] shows only with history.
async function loadRevisions() {
  const seq = ++REV.seq,
    docKey = DOC,
    list = $('#revision-list'),
    out = $('#revision-diff'),
    target = REV.target,
    again = !target && REV.rowsDoc === docKey && REV.rows.length > 0;
  clearRevisionPdf();
  list.hidden = false;
  list.textContent = '최근 변경사항을 읽는 중입니다.';
  out.textContent = '';
  $('#revision-pin').hidden = !target;
  if (target) revTargetNote('변경사항을 읽는 중입니다.');
  else revTargetActs();
  let data;
  try {
    data = (await api(dq('/api/revisions?limit=' + REVISION_PAGE, docKey), { what: '변경사항 읽기', silent: true }))
      .data;
  } catch (error) {
    if (seq === REV.seq) list.textContent = '변경사항을 읽지 못했습니다.';
    return;
  }
  if (seq !== REV.seq || docKey !== DOC) return;
  const rows = (data.available ? data.revisions : []) as RevisionRow[],
    kept = REV.range;
  REV.rows = rows;
  REV.rowsDoc = docKey || '';
  REV.more = !!data.more;
  if (!again) REV.listOpen = false;
  if (!again || !REV.seen || REV.seenState !== SEEN_STATE.OK) openSeen(seenRecordOf(docKey || ''), rows);
  REV.history = !!data.available && rows.length > 0;
  setRevisionOverlay(data.overlay || null);
  const isFigure = !!REV.overlay;
  REV.format = revisionFormatFor(REV.format, isFigure, isMdDoc(), mdcDrawn());
  drawRevisionFormat(); // a LaTeX document after a figure leaves the overlay; a Markdown one opens its rendered compare, a text one its source diff
  $('#revision-controls').hidden = !REV.history && !isFigure;
  $('#revision-note').hidden = !REV.history;
  $('#revision-pdf-tab').hidden = isFigure || isMdDoc();
  $('#revision-overlay-tab').hidden = !isFigure;
  $('#revision-source-tab').hidden = !REV.history;
  $('#revision-rendered-tab').hidden = !REV.history || !mdcDrawn();
  if (!data.available) {
    list.textContent =
      data.reason === 'too_many_files'
        ? tl('이 문서는 이력 파일이 {n}개를 넘어 Git 변경사항을 볼 수 없습니다.', { n: data.limit })
        : '이 문서의 Git 변경사항을 볼 수 없습니다.';
    drawRange();
    if (isFigure) {
      setRevisionFormat(DIFF_FORMAT.OVERLAY);
      return;
    }
    if (target)
      revTargetNote(
        target.region
          ? '보기 전용 PDF 문서의 핀이라 Git 변경사항이 없습니다 — 고친 곳은 LaTeX 문서(본문 등)의 변경사항에서 찾으세요.'
          : '이 문서는 Git 이력을 읽을 수 없어(Git 저장소가 아니거나 경로가 밖) 핀 자리를 변경과 맞출 수 없습니다.',
      );
    return;
  }
  if (!rows.length) {
    list.textContent = '이 문서의 최근 변경사항이 없습니다.';
    drawRange();
    if (isFigure) setRevisionFormat(DIFF_FORMAT.OVERLAY);
    else if (target) revTargetNote('이 문서의 최근 12개 커밋에 변경이 없습니다.');
    return;
  }
  list.hidden = true;
  list.textContent = '';
  // A pin's commit is picked by the server's rule over the same window (api.md §두 커밋 사이): a hash anywhere in it, a PR
  // number or the lines in its first rows.
  if (target) {
    if (REV.seenState === SEEN_STATE.PENDING) resolveSeen(docKey || '', rows[0].id);
    const pick = await pickRevisionFor(target, seq, docKey);
    if (seq !== REV.seq || docKey !== DOC || REV.target !== target) return;
    target.commit = pick.id;
    target.via = pick.via;
    target.hit = pick.hit;
    REV.range = { mode: RANGE_MODE.ONE, start: pick.id, end: pick.id, endSet: false };
    // a figure's lines and pictures are both exact: its overlay opens first; a LaTeX pin's lines exist only in the source
    // diff, and a Markdown pin's own hunks too - its [그린 비교] beside it compares the whole commit (ADR-0031 D6)
    if (isFigure) showRevision(pick.id, DIFF_FORMAT.OVERLAY);
    else showRevision(pick.id, DIFF_FORMAT.SOURCE);
    drawRange();
    return;
  }
  // Opened by a document's update message (updates.js openUpdateRange): the commits it named - after the last seen one (base)
  // up to the newest it named (top; the newest row without one) - as a range in the source diff, the list painting what the
  // server says the range holds. Commits above top (the checkout ahead of the shown build, one come since) stay out, also
  // when the list is read again for a new build: the range keeps the message's base and its end (endSet).
  const want = REV.want;
  REV.want = null;
  if (want && want.base && !isFigure) {
    const at = (id: string) => rows.findIndex((row) => row.id === id || row.id.startsWith(id)),
      baseAt = at(want.base),
      topAt = want.top ? at(want.top) : 0;
    const top = topAt >= 0 ? rows[topAt].id : want.top,
      base = baseAt >= 0 ? rows[baseAt].id : want.base;
    if (top !== base && !(baseAt >= 0 && topAt > baseAt)) {
      REV.range = {
        mode: RANGE_MODE.FROM,
        start: baseAt > 0 && baseAt > topAt ? rows[baseAt - 1].id : top,
        end: top,
        endSet: true,
        base,
      };
      showRange(REV.range);
      return;
    }
  }
  // The same document read again while the view is open (a new build) keeps the range shown, moved to the newest commit
  // unless its end was chosen (endSet: pressed, or named by an update message); a range comes back in its source diff, so a
  // new build never starts its comparison PDF (only [변경 PDF] does).
  // A message's range is its base and end, whatever page of rows is read: thirty newer commits push its start off the
  // first page, and the server still compares them while they are in its history window (else its refusal shows).
  const held = !!kept && kept.mode === RANGE_MODE.FROM && !!kept.base && kept.endSet;
  if (again && (held || rows.some((row) => row.id === kept.start))) {
    if (REV.seenState === SEEN_STATE.OK && kept.mode !== RANGE_MODE.LAST) resolveSeen(docKey || '', rows[0].id);
    showRange(kept.mode === RANGE_MODE.ONE ? kept : { ...kept, end: kept.endSet ? kept.end : rows[0].id }, REV.format);
    return;
  }
  if (REV.seenState === SEEN_STATE.PENDING && !isFigure) {
    showRange(rangeMode(rows, REV.range, RANGE_MODE.LAST, REV.seen));
    return;
  }
  if (REV.seenState === SEEN_STATE.PENDING) resolveSeen(docKey || '', rows[0].id);
  const id = rows.some((row) => row.id === REV.commit) ? REV.commit : rows[0].id;
  REV.range = { mode: RANGE_MODE.ONE, start: id, end: id, endSet: false };
  showRevision(id, isFigure ? DIFF_FORMAT.OVERLAY : undefined);
  drawRange();
}
// ------------------------------------------------ Comparing two commits (issue #188, docs/handbook/viewer.md §변경 보기)
// The quick range [마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만] (#revision-range) and the commit list that stays on screen
// (#revision-commits). The rules below are pure functions of the loaded rows (newest first); showRange() shows their request.
// What is painted and counted comes from the server's range answer (commit_ids, commits): a range follows ancestry, which the
// list's positions do not show (a merged line, a base on another line, a pull that merged older commits).

/** The range after a row press (id): in [이 커밋만] that commit alone; otherwise that commit to the newest - except that, right
 * after such a press, a newer row ends the range there, and the start pressed again is that commit alone. Pure. */
function rangePress(rows: { id: string }[], range: RevRange, id: string): RevRange {
  const at = (commit) => rows.findIndex((row) => row.id === commit),
    newest = rows.length ? rows[0].id : id;
  if (range.mode === RANGE_MODE.ONE) return { mode: RANGE_MODE.ONE, start: id, end: id, endSet: false };
  if (range.mode === RANGE_MODE.FROM && id === range.start)
    return { mode: RANGE_MODE.FROM, start: id, end: id, endSet: true };
  if (range.mode === RANGE_MODE.FROM && !range.endSet && at(id) >= 0 && at(id) < at(range.start))
    return { mode: RANGE_MODE.FROM, start: range.start, end: id, endSet: true };
  return { mode: RANGE_MODE.FROM, start: id, end: newest, endSet: false };
}
/** The range after a segment press: [마지막으로 본 뒤] the last-seen commit to the newest; [이 커밋부터] the commit in focus to
 * the newest; [이 커밋만] the commit in focus alone (the newest after [마지막으로 본 뒤]). Pure. */
function rangeMode(rows: { id: string }[], range: RevRange, mode: string, seen: RevSeen | null): RevRange {
  const newest = rows.length ? rows[0].id : range.end;
  if (mode === RANGE_MODE.LAST) return { mode, start: newest, end: newest, endSet: false };
  const focus = range.mode === RANGE_MODE.LAST && mode === RANGE_MODE.ONE ? range.end : range.start;
  return { mode, start: focus, end: mode === RANGE_MODE.FROM ? newest : focus, endSet: false };
}
/** What a range asks the server: {commit, base}, base '' for one commit against its first parent. [마지막으로 본 뒤] compares
 * the last-seen commit with the newest; [이 커밋부터] the start's first parent with the end - a start that is the end, or a
 * root commit (no parent), is that commit alone - or, for the range an update message opened, its base (the last seen
 * commit, rg.base) with the end. Pure. */
function rangeRequest(
  rows: { id: string; parents: string[] }[],
  range: RevRange,
  seen: RevSeen | null,
): { commit: string; base: string } {
  if (range.mode === RANGE_MODE.LAST && seen) return { commit: range.end, base: seen.id };
  if (range.mode === RANGE_MODE.FROM && range.base) return { commit: range.end, base: range.base };
  if (range.mode !== RANGE_MODE.FROM || range.start === range.end) return { commit: range.start, base: '' };
  const start = rows.find((row) => row.id === range.start);
  return start && start.parents.length
    ? { commit: range.end, base: start.parents[0] }
    : { commit: range.start, base: '' };
}
/** The commits the list paints for request req: one commit itself; a range the commits the server's answer names (ids,
 * its commit_ids), none while that answer is unknown. Pure. */
function paintedIds(request: { commit: string; base: string }, ids: string[] | null): string[] {
  return request.base ? (ids || []).slice() : [request.commit];
}
/** The rows of merged lines: those between a merge and its first parent, when that parent is loaded. Pages come in ancestry
 * order (the server's --topo-order), so a merged line's commits sit right below their merge; a merge whose first parent is
 * not loaded marks nothing. Pure. */
function sideRows(rows: { id: string; parents: string[] }[]): Set<string> {
  const out = new Set<string>();
  rows.forEach((row, index) => {
    if (row.parents.length < 2) return;
    const parentAt = rows.findIndex((other) => other.id === row.parents[0]);
    for (let k = index + 1; k < parentAt; k++) out.add(rows[k].id);
  });
  return out;
}
// The key a source diff or comparison PDF was loaded for: the commit, or base..commit for a range.
function revKey() {
  return REV.base ? REV.base + '..' + REV.commit : REV.commit;
}
// Shows range rg: opens what it asks, then draws the picker - a range always in its source diff (its comparison PDF is built
// only when [변경 PDF] is pressed, whatever format was shown), one commit as a list choice always opened (format undefined:
// the comparison PDF of a LaTeX document, the format shown of a figure document). A Markdown document keeps the tab shown,
// for a range too: its rendered compare builds nothing (md-compare.js).
function showRange(range: RevRange, format?: string) {
  REV.range = range;
  const request = rangeRequest(REV.rows, range, REV.seen);
  const drawn = mdcDrawn() ? (REV.format === DIFF_FORMAT.SOURCE ? DIFF_FORMAT.SOURCE : DIFF_FORMAT.RENDERED) : '';
  showRevision(
    request.commit,
    drawn || (request.base ? (format === DIFF_FORMAT.OVERLAY ? format : DIFF_FORMAT.SOURCE) : format),
    request.base,
  );
  drawRange();
}
// A row of the list pressed (rangePress) and a quick-range segment pressed (rangeMode).
function pressRevisionRow(id) {
  if (id) showRange(rangePress(REV.rows, REV.range, id));
}
function setRevisionRange(mode) {
  if (!REV.rows.length || mode === REV.range.mode) return;
  showRange(rangeMode(REV.rows, REV.range, mode, REV.seen));
}
// Draws the quick range: the pressed segment, and [마지막으로 본 뒤 N] - hidden without a record of this document in this
// browser; N is the server's count ('…' while it is asked); not pressable when nothing is new (N = 0) or the record could not
// be read; a record the history no longer has says so (SEEN_STATE.GONE). Then the list.
function drawRange() {
  const rows = REV.rows,
    range = REV.range,
    seenState = REV.seenState;
  $('#revision-range').hidden = !rows.length;
  for (const button of $$('#revision-range [role=radio]') as HTMLButtonElement[]) {
    const on = button.dataset.range === range.mode;
    button.setAttribute('aria-checked', String(on));
    button.classList.toggle('on', on);
    if (button.dataset.range !== RANGE_MODE.LAST) continue;
    const label = button.querySelector('.lbl'),
      count = button.querySelector('.k');
    button.hidden = seenState === SEEN_STATE.NONE;
    button.disabled =
      (seenState !== SEEN_STATE.OK && seenState !== SEEN_STATE.PENDING) ||
      (seenState === SEEN_STATE.OK && REV.seenN === 0);
    if (label)
      label.textContent = tr(
        seenState === SEEN_STATE.GONE
          ? '기록한 커밋을 찾을 수 없음'
          : seenState === SEEN_STATE.OLD
            ? '기록한 커밋이 최근 500개보다 오래됨'
            : '마지막으로 본 뒤',
      );
    if (count)
      count.textContent = seenState === SEEN_STATE.OK ? String(REV.seenN) : seenState === SEEN_STATE.PENDING ? '…' : '';
  }
  segRove($('#revision-range')); // the group's one Tab stop is the range now chosen (events.js)
  renderCommitList();
}
// A commit's time as the list shows it: MM-DD HH:MM of its ISO commit time (the committer's own clock), else its date.
function rowWhen(row: RevisionRow) {
  const time = String(row.time || '');
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(time)
    ? time.slice(5, 10) + ' ' + time.slice(11, 16)
    : String(row.date || '');
}
// The commit list (#revision-commits): a row per loaded commit with its subject, author, time and short hash; a merged line's
// rows indented under their merge (sideRows). The commits the shown comparison covers (paintedIds - the server's, never the
// rows' positions) ride the rail, the first and last of them bold, its old side (left out) a hollow dot; the commits the
// server counts since the last-seen one are marked new, with a line above the last-seen row saying where reading stopped.
// The phone shows REVISION_PHONE_ROWS rows until [더 보기]; [더 보기] then reads the next page while the server has more.
function renderCommitList() {
  const box = $('#revision-commits'),
    rows = REV.rows,
    seen = REV.seen;
  box.hidden = !rows.length;
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  const focused = document.activeElement as HTMLElement | null,
    refocus = focused && focused.classList.contains('rc-row') ? focused.dataset.commit : null;
  const inside = new Set(paintedIds({ commit: REV.commit, base: REV.base }, REV.rangeIds)),
    side = sideRows(rows),
    fresh = REV.seenState === SEEN_STATE.OK ? REV.seenIds : new Set();
  const order = rows.filter((row) => inside.has(row.id)).map((row) => row.id),
    ends = new Set([order[0], order[order.length - 1]]),
    base = REV.base ? REV.rangeBase || REV.base : '';
  const seenAt = REV.seenState === SEEN_STATE.OK && seen ? rows.findIndex((row) => row.id === seen.id) : -1;
  const cut = LAYOUT === LAYOUT_MODE.NARROW && !REV.listOpen ? Math.min(REVISION_PHONE_ROWS, rows.length) : rows.length;
  const items = rows.map((row, index) => {
    const classes = ['rc-row'];
    if (inside.has(row.id)) classes.push('in');
    if (ends.has(row.id)) classes.push('end');
    if (row.parents.length > 1) classes.push('merge');
    if (side.has(row.id)) classes.push('side');
    if (row.id === base) classes.push('base');
    if (fresh.has(row.id)) classes.push('new');
    if (index === 0) classes.push('first');
    if (index === rows.length - 1) classes.push('last');
    const line =
      index === seenAt && index > 0
        ? html`<div class="rc-seen" data-i="${index}">${seen && seen.at ? tl('{when} 여기까지 봄', { when: seen.at }) : tr('여기까지 봄')}</div>`
        : '';
    return html`${line}<button class="${classes.join(' ')}" data-act="revision-row" data-commit="${row.id}" data-i="${index}" aria-pressed="${inside.has(row.id)}">\
<span class="rc-rail" aria-hidden="true"><span class="rc-dot"></span></span><span class="rc-txt"><span class="rc-t" translate="no">${row.subject}</span>\
<span class="rc-m"><span translate="no">${row.author || ''}</span> · ${rowWhen(row)} · <span class="rc-code" translate="no">${row.id.slice(0, 7)}</span></span></span>\
${fresh.has(row.id) ? html`<span class="rc-tag">새로</span>` : ''}</button>`;
  });
  const more =
    cut < rows.length
      ? tl('이전 커밋 {n}개 더 보기', { n: rows.length - cut })
      : REV.more
        ? tr('이전 커밋 더 보기')
        : '';
  const hint =
    REV.range.mode === RANGE_MODE.ONE ? '최신이 위 · 누르면 그 커밋 하나' : '최신이 위 · 누르면 그 커밋부터 지금까지';
  setHtml(
    box,
    html`<div class="rc-head">${tr(hint)}</div><div class="rc-list">${items}</div>\
${more ? html`<button id="revision-more" class="btn-ghost" data-act="revision-more">${ic('chevron-down')}<span>${more}</span></button>` : ''}`,
  );
  for (const element of $$('#revision-commits [data-i]') as HTMLElement[])
    element.hidden = Number(element.dataset.i) >= cut;
  if (refocus) {
    const again = box.querySelector('.rc-row[data-commit="' + refocus + '"]') as HTMLElement | null;
    if (again) again.focus();
  }
}
// [더 보기]: the phone's first press shows every loaded row; after that (and on a wide screen) the next page of the history.
async function moreRevisions() {
  if (LAYOUT === LAYOUT_MODE.NARROW && !REV.listOpen && REV.rows.length > REVISION_PHONE_ROWS) {
    REV.listOpen = true;
    renderCommitList();
    return;
  }
  if (!REV.more || !REV.rows.length) return;
  REV.listOpen = true;
  if (await moreRows(DOC || '', REVISION_PAGE)) renderCommitList();
}
// Reads the next page (up to limit rows) of document k's window onto REV.rows; whether it did. Nothing when the list is
// another document's or was replaced meanwhile.
async function moreRows(docKey: string, limit: number) {
  if (!REV.more || !REV.rows.length) return false;
  const last = REV.rows[REV.rows.length - 1].id;
  let data;
  try {
    data = (
      await api(dq('/api/revisions?before=' + encodeURIComponent(last) + '&limit=' + limit, docKey), {
        what: '변경사항 읽기',
        silent: true,
      })
    ).data;
  } catch (error) {
    return false;
  }
  if (docKey !== DOC || REV.rowsDoc !== docKey || !REV.rows.length || REV.rows[REV.rows.length - 1].id !== last)
    return false;
  REV.rows = REV.rows.concat(data.revisions || []);
  REV.more = !!data.more;
  return true;
}
// ------------------------------------------------ The last-seen commit (docs/handbook/viewer.md §변경 보기)
// This browser's last-seen commit per document (localStorage limnRevSeen: {<doc>:{id, at}}). No server state: another
// browser or device keeps its own. The server says what it is (resolveSeen): how many commits it compares with the newest,
// or that it is no longer in the history. A record is never overwritten until the server has answered for it.
function readSeenRecords(): Record<string, RevSeen> {
  try {
    const stored = JSON.parse(localStorage.getItem('limnRevSeen') || '{}');
    return stored && typeof stored === 'object' ? stored : {};
  } catch (error) {
    return {};
  }
}
function seenRecordOf(docKey: string): RevSeen | null {
  const record = readSeenRecords()[docKey];
  return record && typeof record.id === 'string' ? { id: record.id, at: String(record.at || '') } : null;
}
// Takes the document's record for this visit: none, the newest commit itself (0 new, nothing to ask), or one to ask about.
function openSeen(seen: RevSeen | null, rows: RevisionRow[]) {
  REV.seen = seen;
  REV.seenIds = new Set();
  REV.seenN = 0;
  REV.seenState = !seen ? SEEN_STATE.NONE : rows.length && rows[0].id === seen.id ? SEEN_STATE.OK : SEEN_STATE.PENDING;
}
// The server's answer for the last-seen range (seen..newest): its count and commits, or why it has none. A refusal that says
// the commit is not in this document's history (or shares none with it) is a record the history no longer has; base_too_old
// is a record still in the history but older than the window (SEEN_STATE.OLD, kept); any other failure leaves the record
// unread, and so kept.
/** @param answer the /api/revision-diff answer with base */
function seenAnswered(answer: any) {
  REV.seenState = SEEN_STATE.OK;
  REV.seenN = Number(answer.commits) || 0;
  REV.seenIds = new Set(answer.commit_ids || []);
}
function seenFailed(error: unknown) {
  const data = (error && (error as ApiError).data) as any,
    why = data && data.reason;
  REV.seenState =
    why === 'base_too_old'
      ? SEEN_STATE.OLD
      : why === 'commit_not_recent' || why === 'no_merge_base' || why === 'base_after_head'
        ? SEEN_STATE.GONE
        : SEEN_STATE.ERROR;
}
// Asks the server about the last-seen commit when the view does not open on its range (a pin's [변경 보기], a figure's overlay).
async function resolveSeen(docKey: string, newest: string) {
  const seen = REV.seen;
  if (!seen) return;
  try {
    const answer = (
      await api(
        dq('/api/revision-diff?commit=' + encodeURIComponent(newest) + '&base=' + encodeURIComponent(seen.id), docKey),
        { what: '변경사항 읽기', silent: true },
      )
    ).data;
    if (docKey === DOC && REV.seen === seen) seenAnswered(answer);
  } catch (error) {
    if (docKey === DOC && REV.seen === seen) seenFailed(error);
  }
  if (docKey === DOC && REV.seen === seen) drawRange();
}
// Leaving the changes view (to the manuscript, another document, or closing the page): once the server has answered for the
// record (or there was none), the document's newest loaded commit becomes its last-seen one, with this moment as MM-DD HH:MM.
// A record still being asked about, one the server could not answer for, or one older than the window (still in the
// history, so not to be lost) is kept. The list is forgotten, so coming back
// starts afresh.
function leaveRevisions() {
  const docKey = REV.rowsDoc,
    top = REV.rows[0];
  REV.rowsDoc = '';
  if (!docKey || !top) return;
  if (REV.seenState === SEEN_STATE.PENDING || REV.seenState === SEEN_STATE.ERROR || REV.seenState === SEEN_STATE.OLD)
    return;
  const now = new Date(),
    pad = (value) => String(value).padStart(2, '0'),
    all = readSeenRecords();
  all[docKey] = {
    id: top.id,
    at: pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + ' ' + pad(now.getHours()) + ':' + pad(now.getMinutes()),
  };
  try {
    localStorage.setItem('limnRevSeen', JSON.stringify(all));
  } catch (error) {}
}
addEventListener('pagehide', () => {
  if (document.body.classList.contains('revision-open')) leaveRevisions();
});
/** A newly selected commit (or range, from base) starts with fit width. Without a format a LaTeX document shows its
 * comparison PDF and a figure document stays in the format it shows (choosing a commit in its source diff keeps the source
 * diff). */
async function showRevision(id: string, format?: string, base?: string) {
  RZ.ratio = 1;
  ++REV.seq;
  REV.commit = id;
  REV.base = base || '';
  REV.rangeLine = '';
  REV.rangeN = null;
  REV.rangeIds = null;
  REV.rangeBase = '';
  REV.sourceCommit = '';
  REV.pdfCommit = '';
  clearRevisionPdf();
  mdcClear();
  $('#revision-note').textContent = REV.base
    ? '두 커밋 사이의 누적 변경 · 이 문서의 Git 이력 · 미커밋 수정 제외'
    : '선택 커밋의 첫 부모와 비교 · 이 문서의 Git 이력 · 미커밋 수정 제외';
  REV.scope = null;
  REV_SCOPE.whole = REV_SCOPE.partial = REV_SCOPE.fallback = false;
  drawRevisionOther(null);
  $('#revision-diff').textContent = '';
  $('#revision-file-row').hidden = true;
  $('#revision-warning').hidden = true;
  $('#revision-status').textContent = '';
  setRevisionFormat(format || (REV.overlay ? REV.format : DIFF_FORMAT.PDF));
}
// ------------------------------------------------ A figure document's overlay (docs/handbook/viewer.md §변경 보기)
// A figure has no comparison PDF: its changes view lays the previous build's page images over the current ones, page by page in
// one box, and [이전 | 지금] (#revision-side) shows one of the two at a time. The images are the page routes' own
// (/pages/<build>/<file>); the two builds come with /api/revisions.

/** The overlay's pages: each page of the build on screen paired with the same page of the previous build, as the box that
 * holds both ({page, ratio, pt} - pt its width in points) and each image's name and share of that box in percent ({name, w,
 * h}; null when that build has no such page). The box is as wide and as tall as the larger of the two, and each image keeps
 * its own size from the top left, so a figure that grew or shrank is never stretched to the other. Pure. */
function overlayPages(overlay: RevisionOverlay) {
  const current = overlay.pages || [],
    previous = overlay.prev_pages || [],
    out: {
      page: number;
      ratio: string;
      pt: number;
      cur: { name: string; w: number; h: number } | null;
      prev: { name: string; w: number; h: number } | null;
    }[] = [];
  for (let i = 0; i < Math.max(current.length, previous.length); i++) {
    const currentPage = current[i],
      previousPage = previous[i];
    const width = Math.max(currentPage ? currentPage.pt_w : 0, previousPage ? previousPage.pt_w : 0),
      height = Math.max(currentPage ? currentPage.pt_h : 0, previousPage ? previousPage.pt_h : 0);
    const share = (image) =>
      image
        ? {
            name: image.name,
            w: Math.round((image.pt_w / width) * 1e4) / 100,
            h: Math.round((image.pt_h / height) * 1e4) / 100,
          }
        : null;
    out.push({
      page: i + 1,
      ratio: width + ' / ' + height,
      pt: width,
      cur: share(currentPage),
      prev: share(previousPage),
    });
  }
  return out;
}
// A build as a person reads it: a page folder name pages-<YYYYmmddHHMMSS>[-<n>] as 'MM-DD HH:MM:SS', with ' (n)' for a second
// build in the same second; any other name as it is. Pure.
function buildStamp(name) {
  const text = String(name || ''),
    match = /^pages-\d{4}(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:-(\d+))?$/.exec(text);
  return match
    ? match[1] +
        '-' +
        match[2] +
        ' ' +
        match[3] +
        ':' +
        match[4] +
        ':' +
        match[5] +
        (match[6] ? ' (' + match[6] + ')' : '')
    : text;
}
/** The overlay's status line: which two builds it lays one over the other, or that there is no previous build. */
function overlayStatus(overlay: RevisionOverlay) {
  if (!overlay.prev_build) return tr('이전 빌드가 없습니다 — 그림을 다시 가져오면 직전 빌드와 겹쳐 볼 수 있습니다.');
  return tl('직전 빌드 {prev} → 지금 {cur} · {n}쪽 · [이전]·[지금]으로 같은 자리를 바꿔 봅니다', {
    prev: buildStamp(overlay.prev_build),
    cur: buildStamp(overlay.build),
    n: Math.max(overlay.pages.length, overlay.prev_pages.length),
  });
}
// Takes a document's two builds from /api/revisions (null: not a figure document) and draws them anew, the current one shown.
function setRevisionOverlay(overlay: RevisionOverlay | null) {
  REV.overlay = overlay;
  REV.side = OVERLAY_SIDE.CUR;
  renderRevisionOverlay();
  drawRevisionSide();
}
// Draws the overlay's pages (overlayPages) into #revision-overlay: per page a box holding the current build's image and the
// previous build's, each at its share of the box; a build without that page has a line saying so in its place. The boxes
// keep their sizes on paper relative to each other (--ov-share) and the widest is at most its print size (--ov-cap).
function renderRevisionOverlay() {
  const overlay = REV.overlay,
    box = $('#revision-overlay');
  box.replaceChildren();
  if (!overlay) return;
  const pages = overlayPages(overlay),
    widest = Math.max(1, ...pages.map((page) => page.pt));
  box.style.setProperty('--ov-cap', Math.round(widest * PT_PX) + 'px');
  const side = (image, build, className, alt, none) =>
    image && build
      ? html`<img class="${className}" loading="lazy" draggable="false" alt="${alt}" src="${dq('/pages/' + encodeURIComponent(build) + '/' + encodeURIComponent(image.name))}">`
      : html`<span class="ov-none ${className}">${none}</span>`;
  for (const page of pages) {
    const pageBox = document.createElement('div');
    pageBox.className = 'ov-page';
    pageBox.dataset.page = String(page.page);
    pageBox.style.aspectRatio = page.ratio;
    pageBox.style.setProperty('--ov-share', String(page.pt / widest));
    setHtml(
      pageBox,
      html`${side(page.cur, overlay.build, 'ov-cur', tl('지금 {page}쪽', { page: page.page }), tr('지금 빌드에 없는 쪽'))}\
${side(page.prev, overlay.prev_build, 'ov-prev', tl('이전 {page}쪽', { page: page.page }), tr('이전 빌드에 없는 쪽'))}<span class="ov-no">${page.page}</span>`,
    );
    for (const [selector, image] of [
      ['img.ov-cur', page.cur],
      ['img.ov-prev', page.prev],
    ] as const) {
      const img = pageBox.querySelector(selector) as HTMLElement | null;
      if (img && image) {
        img.style.width = image.w + '%';
        img.style.height = image.h + '%';
      }
    }
    box.appendChild(pageBox);
  }
}
// [이전 | 지금]: the side the overlay shows. [이전] cannot be pressed when there is no previous build.
function drawRevisionSide() {
  const overlay = REV.overlay,
    none = !overlay || !overlay.prev_build;
  for (const button of $$('#revision-side [role=radio]') as HTMLButtonElement[]) {
    const on = button.dataset.side === REV.side;
    button.setAttribute('aria-checked', String(on));
    button.classList.toggle('on', on);
    button.disabled = none && button.dataset.side === OVERLAY_SIDE.PREV;
  }
  segRove($('#revision-side')); // the group's one Tab stop is the side now chosen (events.js)
  $('#revision-overlay').dataset.side = REV.side;
}
// Shows the previous build's pages (side PREV, when there is one) or the current build's.
function setRevisionSide(side) {
  REV.side = side === OVERLAY_SIDE.PREV && REV.overlay && REV.overlay.prev_build ? OVERLAY_SIDE.PREV : OVERLAY_SIDE.CUR;
  drawRevisionSide();
}
// Brings page n of the overlay to the top of its view, once it is laid out ([변경 보기] of a pin on that page).
function scrollOverlayTo(page) {
  requestAnimationFrame(() => {
    const box = $('#revision-overlay'),
      pageBox = box.querySelector('.ov-page[data-page="' + page + '"]');
    if (pageBox) box.scrollTop += pageBox.getBoundingClientRect().top - box.getBoundingClientRect().top;
  });
}
async function loadRevisionSource(id, seq, docKey) {
  const out = $('#revision-diff');
  out.textContent = '소스 변경 내용을 읽는 중입니다.';
  $('#revision-file-row').hidden = true;
  const pinTarget = revisionPinFor(id),
    base = REV.base,
    query = pinTarget ? '&pin=' + pinTarget.id : base ? '&base=' + encodeURIComponent(base) : '';
  try {
    const answer = (
      await api(dq('/api/revision-diff?commit=' + encodeURIComponent(id) + query, docKey), {
        what: '변경 내용 읽기',
        silent: true,
      })
    ).data;
    if (!revisionCurrent(seq, docKey, id)) return;
    if (base) {
      REV.rangeLine = rangeSummary(answer);
      if (REV.format === DIFF_FORMAT.SOURCE) $('#revision-status').textContent = REV.rangeLine;
      REV.rangeN = {
        commits: Number(answer.commits) || 0,
        files: Array.isArray(answer.files) ? answer.files.length : 0,
      };
      mdcRestatus();
      REV.rangeIds = Array.isArray(answer.commit_ids) ? answer.commit_ids : [];
      REV.rangeBase = String(answer.base || '');
      if (REV.range.mode === RANGE_MODE.LAST && REV.seen && base === REV.seen.id) seenAnswered(answer);
      drawRange();
    }
    // v0.3: a pin's own hunks when it owns part of the commit; otherwise the whole commit exactly as before
    const pinScope = answer.scope && answer.scope.mode === SCOPE_MODE.PIN ? answer.scope : null;
    REV.scope = answer.scope || null;
    if (pinScope) {
      REV_SCOPE.partial = true;
      syncRevisionWhole();
    }
    const cut = '\n\n' + tr('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REV.whole = pinScope
      ? pinScope.diff + (pinScope.truncated ? cut : '')
      : (answer.diff ||
          tr(
            base
              ? '이 범위에서 표시할 원고 텍스트 변경이 없습니다.'
              : '이 커밋에서 표시할 원고 텍스트 변경이 없습니다.',
          )) + (answer.truncated ? cut : '');
    REV.files = revisionFiles(pinScope ? pinScope.diff : answer.diff || '');
    drawRevisionOther(pinScope);
    const select = $('#revision-file');
    setHtml(
      select,
      html`<option value="all">전체 파일</option>${REV.files.map((file, index) => html`<option value="${index}">${file.name}</option>`)}`,
    );
    select.value = 'all';
    $('#revision-file-row').hidden = REV.files.length < 2;
    REV.sourceCommit = revKey();
    const target = REV.target,
      fileIndex = target ? pinFileIndex(REV.files, target.file) : -1;
    if (fileIndex >= 0 && REV.files.length > 1) select.value = String(fileIndex);
    renderRevisionFile();
    if (target) highlightPinLines(target);
  } catch (error) {
    if (revisionCurrent(seq, docKey, id)) {
      const why = error && (error as ApiError).data ? errText((error as ApiError).data) : '';
      out.textContent = why
        ? tl('소스 변경 내용을 읽지 못했습니다: {error}', { error: why })
        : tr('소스 변경 내용을 읽지 못했습니다.');
      // the last-seen range could not be compared: say why on its segment, and show the newest commit alone instead
      if (base && REV.range.mode === RANGE_MODE.LAST && REV.seen && base === REV.seen.id) {
        seenFailed(error);
        if ((REV.seenState === SEEN_STATE.GONE || REV.seenState === SEEN_STATE.OLD) && REV.rows.length) {
          const top = REV.rows[0].id;
          showRange({ mode: RANGE_MODE.ONE, start: top, end: top, endSet: false });
        } else drawRange();
      }
    }
  }
}
// A range's summary on the status line (its source diff): the two ends, the commits and files in it, the merge base when the
// base was on another line, and a warning when the range is wide enough for its comparison PDF to fail (more than 60
// manuscript files, or a diff cut at the server's limit). @param r the /api/revision-diff answer with base
function rangeSummary(answer) {
  const files = Array.isArray(answer.files) ? answer.files : [];
  let summary = tl('{base} → {head} · 커밋 {commits}개 · 파일 {files}개', {
    base: String(answer.base || '').slice(0, 8),
    head: String(answer.id || '').slice(0, 8),
    commits: answer.commits,
    files: files.length,
  });
  if (answer.merge_base)
    summary += ' · ' + tl('공통 조상 {mb}부터 비교', { mb: String(answer.merge_base).slice(0, 8) });
  if (files.length > 60 || answer.truncated) summary += ' · ' + tr('범위가 넓어 비교 PDF가 실패할 수 있습니다');
  return summary;
}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기): opens the changes tab from an awaiting-review/done pin.
// Commit selection: the commit hash (7+ characters) in the close-time reference (ref) > a commit whose subject contains the reference's PR number
// ('(#236)'/'pull request #236') > among the last 12 commits, the most recent one that touched the pin's file/lines (+-5 lines) > the most recent commit.
// Line matching exists only for the source diff - a line whose new-side line number falls within the pin's range is highlighted and scrolled to.
// The comparison PDF (latexdiff) has no SyncTeX mapping, so it only moves to roughly the pin's page.
// The commit a close reference names among revs (the window's rows, in order) - the server's _ref_commit rule: a 7-40 digit
// hash in every row, a PR number only in the first `recent` rows (REVISION_RECENT; a #N deeper is another PR's). Pure.
function matchRevision(ref: unknown, rows: { id: string; subject?: string }[], recent?: number) {
  const text = String(ref || '');
  for (const match of text.matchAll(/\b[0-9a-f]{7,40}\b/g)) {
    const row = rows.find((candidate) => candidate.id.startsWith(match[0]));
    if (row) return { id: row.id, via: 'sha', tok: match[0] };
  }
  for (const match of text.matchAll(/#(\d+)/g)) {
    const number = match[1],
      pattern = new RegExp('\\(#' + number + '\\)|pull request #' + number + '\\b|#' + number + '\\b');
    const row = rows.slice(0, recent).find((candidate) => pattern.test(candidate.subject || ''));
    if (row) return { id: row.id, via: 'pr', tok: '#' + number };
  }
  return null;
}
function pinFileIndex(files, file) {
  file = String(file || '');
  let best = -1,
    bestLength = 0;
  files.forEach((entry, index) => {
    const name = entry.name;
    if (name && (file === name || file.endsWith('/' + name)) && name.length > bestLength) {
      best = index;
      bestLength = name.length;
    }
  });
  return best;
}
function hunkRanges(text) {
  const out: number[][] = [];
  for (const match of String(text || '').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)) {
    const start = +match[1],
      count = match[2] === undefined ? 1 : +match[2];
    out.push([start, start + Math.max(count, 1) - 1]);
  }
  return out;
}
function touchesPin(files, target, slack?) {
  const index = pinFileIndex(files, target.file);
  if (index < 0) return false;
  slack = slack == null ? 5 : slack;
  return hunkRanges(files[index].text).some(([start, end]) => end >= target.lo - slack && start <= target.hi + slack);
}
// A pin's commit: the one its close_ref names (matchRevision over the whole window - a hash not among the loaded rows reads
// further pages until found or the window ends, as the server resolves it), else the most recent of the first REVISION_RECENT
// rows that touched the pin's lines, else the newest.
async function pickRevisionFor(target, seq, docKey): Promise<{ id: string; via: string; tok?: string; hit?: boolean }> {
  let match = matchRevision(target.ref, REV.rows, REVISION_RECENT);
  while (
    !match &&
    /\b[0-9a-f]{7,40}\b/.test(String(target.ref || '')) &&
    REV.more &&
    seq === REV.seq &&
    docKey === DOC
  ) {
    if (!(await moreRows(docKey, 50))) break;
    match = matchRevision(target.ref, REV.rows, REVISION_RECENT);
  }
  if (match) return match;
  const recent = REV.rows.slice(0, REVISION_RECENT);
  if (!target.region && target.file) {
    for (const row of recent) {
      if (seq !== REV.seq || docKey !== DOC) break;
      try {
        const answer = (
          await api(dq('/api/revision-diff?commit=' + encodeURIComponent(row.id), docKey), {
            what: '변경 내용 읽기',
            silent: true,
          })
        ).data;
        if (touchesPin(revisionFiles(answer.diff || ''), target)) return { id: row.id, via: 'lines' };
      } catch (error) {}
    }
  }
  return { id: recent[0].id, via: 'latest' };
}
/** Explain the shown change and review access for the current pin, retaining the existing source/PDF scope guidance. */
function revTargetNote(message?) {
  const target = REV.target,
    box = $('#revision-pin');
  if (!target) {
    box.hidden = true;
    return;
  }
  const via =
    {
      sha: tl('참조의 커밋 {tok}', { tok: target.tokOf || '' }),
      pr: tr('참조의 PR'),
      lines: tr('이 줄을 바꾼 가장 최근 커밋'),
      latest: tr('참조로 커밋을 찾지 못해 가장 최근 커밋'),
    }[target.via as string] || '';
  const where = target.region
    ? tl('쪽 {page} 영역', { page: target.page })
    : target.name + ' ' + rng(target.lo, target.hi);
  const pinScope =
    REV.format === DIFF_FORMAT.SOURCE && REV.scope && REV.scope.mode === SCOPE_MODE.PIN ? REV.scope : null;
  const scopeText = pinScope
    ? tl('이 핀의 변경 {n}곳만 보입니다', { n: pinScope.hunks }) +
      ' (' +
      tr(pinScope.source === SCOPE_SOURCE.CHANGES ? '에이전트가 기록한 줄' : '핀 자리로 추정') +
      ') · '
    : '';
  let text = message
    ? tr(message)
    : REV.format === DIFF_FORMAT.RENDERED
      ? target.mdcMsg || tr('두 판을 그려 견주는 중입니다.')
      : REV.format === DIFF_FORMAT.OVERLAY
        ? tl('직전 빌드와 지금 빌드의 {page}쪽을 겹쳐 보입니다 — [이전]·[지금]으로 바꿔 보세요', {
            page: target.page,
          }) + (REV.history ? ' · ' + tr('고친 줄은 [소스 diff]') : '')
        : scopeText +
          (REV.format === DIFF_FORMAT.PDF
            ? tl(
                '비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',
                { page: target.page },
              )
            : tr(
                target.hit === false
                  ? '이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다'
                  : target.near
                    ? '핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다'
                    : '강조한 줄이 핀 범위입니다',
              ));
  const pin = findAnyPin(target.id),
    access = pin && pinState(pin) === PIN_STATE.REVIEW && !canConfirmReview() ? confirmAccessText() : '';
  setHtml(
    box,
    html`<span><b>${tl('핀 #{id}', { id: target.id })}</b> · ${where}${target.ref ? ' · ' + tl('참조 {ref}', { ref: target.ref }) : ''}${via ? ' · ' + via : ''}</span><span class="rp-msg">${text}${access ? html` <span class="review-access">${access}</span>` : ''}</span>`,
  );
  box.dataset.id = target.id;
  box.hidden = false;
  revTargetActs();
}
// The guide line's buttons (docs/handbook/viewer.md §변경 보기): [원고로] and, for a pin awaiting review that this person may confirm
// (a person with write access, not a view-only region pin), the card's [확인] - the same data-act="confirm" and confirmPin(), soft for the
// author as on the card. On the phone and tablet sheet they sit in the thumb row (#revision-acts) right above the status line
// and the tool bar; in the other bands at the guide line's right. Redrawn on a band change and whenever the pin lists change.
/** Draw the current pin's navigation and human-only confirmation controls in the changes guide or compact action row. */
function revTargetActs() {
  const target = REV.target,
    row = $('#revision-acts'),
    narrow = LAYOUT === LAYOUT_MODE.NARROW;
  $$('.rp-acts').forEach((element) => element.remove());
  if (!target || $('#revision-pin').hidden) {
    row.hidden = true;
    document.body.classList.remove('rev-thumb');
    return;
  }
  const pin = findAnyPin(target.id),
    confirm = !!pin && pinState(pin) === PIN_STATE.REVIEW && !target.region && canConfirmReview();
  const backDoc = REV.back && REV.back !== DOC ? docInfo(REV.back) : null,
    back = backDoc ? backDoc.name : null,
    actionBox = document.createElement('span');
  actionBox.className = 'rp-acts';
  const confirmButton = confirm
    ? html`<button class="btn-sm b-confirm ${isMe(pin.author) ? 'btn-soft' : 'btn-secondary'}" data-act="confirm" data-tip="${T.confirm}">확인</button>`
    : '';
  setHtml(
    actionBox,
    html`<button class="btn-sm" data-act="rev-back" data-tip="${back ? tl('{name} 원고 보기로 돌아갑니다', { name: back }) : tr('원고 보기로 돌아갑니다')}">${back ? tl('{name}(으)로', { name: back }) : tr('원고로')}</button>${confirmButton}`,
  );
  (narrow ? row : $('#revision-pin')).appendChild(actionBox);
  row.dataset.id = target.id;
  row.hidden = !narrow;
  document.body.classList.toggle('rev-thumb', narrow);
}
function highlightPinLines(target) {
  const rows = $$('#revision-diff .rd-line');
  let first = null as Element | null;
  rows.forEach((line) => {
    if (!(line.classList.contains('rd-add') || line.classList.contains('rd-context'))) return;
    const lineNumber = +line.querySelector('.rd-no').textContent;
    if (lineNumber >= target.lo && lineNumber <= target.hi) {
      line.classList.add('rd-pin');
      if (!first) first = line;
    }
  });
  target.hit = !!first || touchesPin(REV.files, target, 5);
  target.near = !first && target.hit; // when only a neighboring line changed, it's never described as "the highlighted line" (there is none)
  if (!first) {
    const fileIndex = pinFileIndex(REV.files, target.file);
    if (fileIndex < 0) target.hit = false;
    else {
      let best = null as Element | null,
        bestDistance = Infinity;
      rows.forEach((line) => {
        const lineNumber = +line.querySelector('.rd-no').textContent;
        if (!lineNumber) return;
        const distance = Math.min(Math.abs(lineNumber - target.lo), Math.abs(lineNumber - target.hi));
        if (distance < bestDistance) {
          bestDistance = distance;
          best = line;
        }
      });
      first = best;
    }
  }
  revTargetNote();
  const top = first;
  if (top) requestAnimationFrame(() => top.scrollIntoView({ block: 'center' }));
}
function findAnyPin(id) {
  return (
    OPEN_ALL.find((pin) => pin.id === id) ||
    REVIEW_ALL.find((pin) => pin.id === id) ||
    DONE_ALL.find((pin) => pin.id === id) ||
    null
  );
}
// REV.back remembers the manuscript document that opened [변경 보기], so [원고로] returns there.
// [원고로] and Esc in the changes view: back to the manuscript view, and to the document it was opened from.
function revBack() {
  const back = REV.back;
  REV.back = null;
  setViewMode(VIEW_MODE.MANUSCRIPT);
  if (back && back !== DOC && docInfo(back)) switchDoc(back);
}
// Opens a pin's change view only for the document visit that initiated the switch.
async function showChange(id) {
  const pin = findAnyPin(id);
  if (!pin) return;
  const docKey = pdoc(pin),
    back = DOC,
    fromManuscript = !document.body.classList.contains('revision-open');
  if (docKey !== DOC && docInfo(docKey)) {
    const opening = switchDoc(docKey),
      visit = SWITCHSEQ;
    await opening;
    if (DOC !== docKey || visit !== SWITCHSEQ) return;
  }
  if (fromManuscript) REV.back = back;
  REV.target = {
    id: pin.id,
    file: pin.file || pin.pdf || '',
    name:
      pin.name ||
      String(pin.file || pin.pdf || '')
        .split('/')
        .pop() ||
      '',
    lo: pin.lo,
    hi: pin.hi,
    page: pinPlace(pin).page,
    ref: pin.close_ref || '',
    region: isRegion(pin),
  };
  const match = /\b[0-9a-f]{7,40}\b/.exec(REV.target.ref);
  REV.target.tokOf = match ? match[0] : '';
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
  if (document.body.classList.contains('revision-open')) loadRevisions();
  else setViewMode(VIEW_MODE.REVISIONS);
}
const REVISION_BUSY_WAITS = 240; // times a comparison asks again, a second apart, for the one before it: past latexdiff's and latexmk's limits together
// Asks for the comparison. A document builds one at a time, and opening this view starts the newest commit's: a press on another
// commit while it runs is answered busy, and waits for it here, saying so, instead of stopping on that answer. Null: the view
// moved on while it waited; leaving for the source diff stops the waiting too, and coming back asks again (REV.pdfCommit).
async function revisionStart(body: Record<string, unknown>, seq: number, docKey: string, id: string) {
  const box = $('#revision-status'),
    waiting = tr('앞선 비교 PDF가 끝나는 대로 이 비교 PDF를 만듭니다. 원고와 핀은 그대로 사용할 수 있습니다.');
  const left = () => {
    if (!revisionCurrent(seq, docKey, id)) return true;
    if (REV.format === DIFF_FORMAT.PDF) return false;
    REV.pdfCommit = '';
    if (box.textContent === waiting) box.textContent = '';
    return true;
  }; // its own line, not this one's promise
  for (let waits = 0; ; waits++) {
    try {
      return (await api('/api/revision-build', { method: 'POST', body, what: '비교 PDF 만들기', silent: true })).data;
    } catch (error) {
      const answer = (error as ApiError).data as { reason?: string } | undefined;
      if (!answer || answer.reason !== 'busy' || waits >= REVISION_BUSY_WAITS) throw error;
      if (left()) return null;
      box.textContent = waiting;
      await new Promise((resolve) => setTimeout(resolve, 1000));
      if (left()) return null;
    }
  }
}
// Start or read the comparison PDF for this revision; late responses and module imports cannot attach to another view.
/** Load one comparison visit; mounting owns zoomable page geometry. */
async function loadRevisionPdf(id, seq, docKey) {
  const statusBox = $('#revision-status'),
    warningBox = $('#revision-warning'),
    target = REV.target;
  // v0.3: for a pin, the comparison is old + only that pin's hunks unless [커밋 전체 비교] is on or that build already failed
  const pin = target && revisionPinFor(id) && !REV_SCOPE.whole && !REV_SCOPE.fallback ? target.id : null,
    base = REV.base,
    query = pin ? '&pin=' + pin : base ? '&base=' + encodeURIComponent(base) : '';
  try {
    const first = await revisionStart(
      pin ? { commit: id, doc: docKey, pin } : base ? { commit: id, doc: docKey, base } : { commit: id, doc: docKey },
      seq,
      docKey,
      id,
    );
    if (first === null || !revisionCurrent(seq, docKey, id)) return;
    let status = first;
    if (pin && status.scope) {
      REV_SCOPE.partial = status.scope === SCOPE_MODE.PIN;
      syncRevisionWhole();
    }
    for (let tries = 0; status.state === REVISION_STATE.RUNNING && tries < 180; tries++) {
      if (!revisionCurrent(seq, docKey, id)) return;
      statusBox.textContent = base
        ? '두 커밋 사이의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.'
        : '선택 커밋의 비교 PDF를 만드는 중입니다. 원고와 핀은 그대로 사용할 수 있습니다.';
      await new Promise((resolve) => setTimeout(resolve, 1000));
      if (!revisionCurrent(seq, docKey, id)) return;
      status = (
        await api(dq('/api/revision-build?commit=' + encodeURIComponent(id) + query, docKey), {
          what: '비교 PDF 상태',
          silent: true,
        })
      ).data;
    }
    if (!revisionCurrent(seq, docKey, id)) return;
    if (pin && status.scope === SCOPE_MODE.PIN && status.state === REVISION_STATE.ERROR) {
      // the pin's hunks alone did not compile: show the whole commit, say so in one line
      REV_SCOPE.fallback = true;
      syncRevisionWhole();
      return loadRevisionPdf(id, seq, docKey);
    }
    if (status.state !== REVISION_STATE.READY)
      throw new Error(
        errText(status) ||
          tr(
            status.state === REVISION_STATE.RUNNING
              ? '비교 PDF 대기 시간이 지났습니다. 다시 열어 재시도하세요.'
              : '비교 PDF를 만들지 못했습니다.',
          ),
      );
    if (status.head && status.head !== id) throw new Error(tr('요청한 커밋과 비교 PDF의 커밋이 다릅니다.'));
    const warnings = Array.isArray(status.warnings) ? status.warnings : [];
    warningBox.hidden = !warnings.length;
    warningBox.querySelector('summary').textContent = tl('빌드 경고 {n}건 보기', { n: warnings.length });
    warningBox.querySelector('pre').textContent = warnings.join('\n');
    warningBox.open = false;
    statusBox.textContent = '비교 PDF를 읽는 중입니다.';
    const response = await fetch(dq('/api/revision-pdf?commit=' + encodeURIComponent(id) + query, docKey));
    if (!response.ok) throw new Error(tl('비교 PDF를 열지 못했습니다 (HTTP {status}).', { status: response.status }));
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!revisionCurrent(seq, docKey, id)) return;
    const lib = VEC.lib || (await import('/vendor/pdfjs/pdf.min.mjs?v=' + PDFJS_V));
    if (!revisionCurrent(seq, docKey, id)) return;
    lib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs?v=' + PDFJS_V;
    const loading = lib.getDocument({ data: bytes, isEvalSupported: false, useWasm: false, enableXfa: false });
    REV_PDF.loading = loading;
    const pdf = await loading.promise;
    if (!revisionCurrent(seq, docKey, id)) {
      try {
        void loading.destroy().catch(() => {});
      } catch (error) {}
      return;
    }
    REV_PDF.doc = pdf;
    const lead =
      pin && status.scope === SCOPE_MODE.PIN
        ? tl('핀 #{id}의 변경만', { id: pin }) + ' · '
        : REV_SCOPE.fallback && target
          ? tr('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다') + ' · '
          : '';
    const sides = { base: String(status.base || '').slice(0, 8), head: id.slice(0, 8), n: pdf.numPages };
    statusBox.textContent =
      lead +
      (base
        ? tl('기준 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가', sides) +
          (status.merge_base
            ? ' · ' + tl('공통 조상 {mb}부터 비교', { mb: String(status.merge_base).slice(0, 8) })
            : '')
        : tl('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가', sides));
    await mountRevisionPdf(pdf, seq, docKey, id);
  } catch (error) {
    if (revisionCurrent(seq, docKey, id)) {
      clearRevisionPdf();
      const data = (error && (error as ApiError).data) as any;
      statusBox.textContent = tl('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.', {
        error:
          data && data.error
            ? errText(data)
            : error && (error as Error).message
              ? (error as Error).message
              : tr('표시하지 못했습니다.'),
      });
    }
  }
}
export {
  REV,
  REVISION_PAGE,
  REV_PDF,
  REV_SCOPE,
  findAnyPin,
  hunkRanges,
  loadRevisions,
  moreRevisions,
  pressRevisionRow,
  renderCommitList,
  renderRevisionFile,
  revBack,
  revKey,
  revTargetActs,
  revTargetNote,
  revisionCurrent,
  revisionPinFor,
  setRevisionFormat,
  setRevisionRange,
  setRevisionSide,
  setRevisionWhole,
  setViewMode,
  showChange,
  showRevision,
  toggleRevisionOther,
};
