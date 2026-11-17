// ------------------------------------------------ The changes view (docs/handbook/viewer.md §변경 보기)
// REVISION_VIEW: one changes-view visit owns the selected commit, source text and request sequence (seq). overlay is a
// figure document's two builds from /api/revisions (null for any other document), side the one its overlay shows,
// history whether it has commits. base is a range's old side ('' for one commit against its first parent); rows the
// loaded commits (newest first, REVISION_PAGE a page) of rowsDoc, more whether older ones remain; range the quick range
// and its ends (RevRange); seen this browser's last-seen commit of the document, seenState what the server said of it
// (SEEN_STATE), seenN how many commits it compares with the newest and seenIds which (the server's count, never the
// list's positions); rangeIds the commits the shown range compares (the server's commit_ids; null until it answers),
// rangeBase its old side; listOpen whether the phone shows every loaded row; rangeLine the range's summary for the
// status line, and rangeN its commit and file counts (the rendered compare's status line takes them,
// revisions/view-rendered-compare.ts sayCompareStatus).
import { DOC, DONE_ALL, LAYOUT, OPEN_ALL, REVIEW_ALL, SWITCHSEQ } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { markHiddenHtml } from '../platform/hidden-chars.ts';
import { errText, translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { drawNavigationView, drawPos, switchDoc } from '../documents/flow-switch.ts';
import { canConfirmReview, confirmAccessText } from '../documents/view-meta.ts';
import { POINT_PX, boundScale } from '../pdf/view-pages.ts';
import { PDFJS_VERSION, VECTOR_PDF } from '../pdf/flow-open.ts';
import { updateSectionStrip } from '../pdf/view-outline.ts';
import { scheduleVectorDraw } from '../pdf/view-draw.ts';
import { searchOffer } from '../pdf/flow.ts';
import {
  REVISION_ZOOM,
  disposeRevisionZoom,
  drawRevisionZoom,
  mountRevisionPdf,
  resizeRevisionPdf,
  revisionPdfActive,
} from './input.ts';
import { setSide } from '../layout/flow.ts';
import { pinPlace } from '../pdf/view-figure.ts';
import {
  RENDERED_COMPARE,
  clearRenderedCompare,
  drawCompareNavigator,
  isDrawnFromMarkdown,
  restateCompareStatus,
  showRenderedCompare,
} from './view-rendered-compare.ts';
import { keepSpot, returnToSpot } from '../documents/flow-rebuild.ts';
import { $, $$, findElement } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import {
  DIFF_FORMAT,
  LAYOUT_MODE,
  OVERLAY_SIDE,
  PIN_STATE,
  RANGE_MODE,
  REVISION_STATE,
  SCOPE_MODE,
  SCOPE_SOURCE,
  SEEN_STATE,
  VIEW_MODE,
} from '../app/rules-tables.ts';
import { pinState, lineRange } from '../app/rules-pins.ts';
import { isMe } from '../app/state-people.ts';
import { isMarkdownDoc, docInfo, withDocQuery, isRegion, pdoc, REVISION_PAGE } from '../documents/state.ts';
import { markHitSides } from '../pdf/view-badges.ts';
// A file's part of a source diff: its path and its patch text.
interface RevisionFile {
  name: string;
  text: string;
}
// What rangeSummary reads of GET /api/revision-diff with a base: the two ends, the commits and files between them, the
// merge base when the base was on another line, and whether the diff was cut.
interface RevisionDiffAnswer {
  id?: string;
  base?: string;
  merge_base?: string;
  commits?: number;
  files?: unknown[];
  truncated?: boolean;
}
const REVISION_VIEW = {
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
// the commits [변경 보기] picks a pin's commit among - the server resolves a close_ref among the same
const REVISION_RECENT = 12;
const REVISION_PHONE_ROWS = 5; // rows the phone's list shows before [더 보기]
// A pin's view of a commit (docs/handbook/viewer.md §변경 보기). REVISION_VIEW.scope is the source diff's scope object
// ({mode:'pin'|'commit', source, hunks, other, ...}). COMPARISON_SCOPE is the comparison PDF's toggle - the whole
// commit or only this pin's hunks (whole), whether the pin owns only part of the commit (partial), whether the pin-only
// build failed and the whole commit is shown instead (fallback). COMPARISON_PDF holds the loaded comparison PDF, its
// loading task, its observer and its render tasks.
const COMPARISON_SCOPE = { whole: false, partial: false, fallback: false };
const COMPARISON_PDF = {
  doc: null as any,
  loading: null as any,
  observer: null as IntersectionObserver | null,
  tasks: new Set<{ cancel(): void }>(),
};
function revisionFiles(patch: string) {
  const starts: { at: number; head: string }[] = [];
  const fileHeader = /^diff --git .+$/gm;
  let match;
  while ((match = fileHeader.exec(patch)) !== null) starts.push({ at: match.index, head: match[0] });
  return starts.map((start, index) => {
    const pathAt = start.head.lastIndexOf(' b/');
    return {
      name: pathAt >= 0 ? start.head.slice(pathAt + 3) : translateTemplate('파일 {n}', { n: index + 1 }),
      text: patch.slice(start.at, index + 1 < starts.length ? starts[index + 1].at : undefined),
    };
  });
}
// A patch as Html of numbered lines (file, hunk, add, del, context, meta). The code itself is the manuscript's text, so
// it is translate="no"; the lines are text, each character that would hide or reorder a line in its box
// (markHiddenHtml) - a change a person reviews never reads as another text. The CR a CRLF file's line ends in is that
// line end, not text: it is left out.
function renderRevisionDiff(patch: string) {
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
    return html`<span class="rd-line rd-${kind}"><span class="rd-no" aria-hidden="true">${number}</span><span class="rd-code" translate="no">${markHiddenHtml(line.endsWith('\r') ? line.slice(0, -1) : line)}</span></span>`;
  })}`;
}
function renderRevisionFile() {
  const choice = $('#revision-file').value,
    index = Number(choice);
  setHtml(
    $('#revision-diff'),
    renderRevisionDiff(
      choice === 'all'
        ? REVISION_VIEW.whole
        : (REVISION_VIEW.files[index] && REVISION_VIEW.files[index].text) || REVISION_VIEW.whole,
    ),
  );
}
// The fields of GET /api/revision-diff?pin='s scope (limn.revisions.scope scope_payload) the rest of the commit is drawn
// from; the patch and its truncation come only in mode pin.
type RevisionOtherScope = { mode: string; other: number; other_diff?: string; other_truncated?: boolean };
// The rest of the commit, folded under one control. Hidden when the pin owns the whole commit or the view is not a
// pin's.
function drawRevisionOther(scope: RevisionOtherScope | null) {
  const toggle = $('#revision-other-toggle'),
    rest = $('#revision-other');
  rest.hidden = true;
  rest.replaceChildren();
  toggle.setAttribute('aria-expanded', 'false');
  REVISION_VIEW.other =
    scope && scope.mode === SCOPE_MODE.PIN
      ? String(scope.other_diff || '') +
        (scope.other_truncated
          ? '\n\n' + translate('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.')
          : '')
      : '';
  toggle.hidden = !REVISION_VIEW.other;
  if (scope && REVISION_VIEW.other)
    findElement(toggle, 'span', HTMLSpanElement).textContent = translateTemplate('이 커밋의 다른 변경 {n}곳', {
      n: scope.other,
    });
}
function toggleRevisionOther() {
  const toggle = $('#revision-other-toggle'),
    rest = $('#revision-other'),
    open = toggle.getAttribute('aria-expanded') !== 'true';
  toggle.setAttribute('aria-expanded', String(open));
  rest.hidden = !open;
  if (open && !rest.firstChild) setHtml(rest, renderRevisionDiff(REVISION_VIEW.other));
}
// [커밋 전체 비교]: shown only for the PDF of a pin that owns part of the commit, and not after a fallback (there is
// nothing to switch to).
function syncRevisionWhole() {
  const button = $('#revision-whole');
  button.hidden = !(
    REVISION_VIEW.format === DIFF_FORMAT.PDF &&
    revisionPinFor(REVISION_VIEW.commit) &&
    COMPARISON_SCOPE.partial &&
    !COMPARISON_SCOPE.fallback
  );
  button.setAttribute('aria-pressed', String(COMPARISON_SCOPE.whole));
}
// The pin whose hunks a commit's view is scoped to: only the commit picked for the pin ([변경 보기]); any other commit
// chosen in the list is shown whole (another commit's lines are not this pin's), and so is a range (pin scoping and
// ranges do not combine; the server refuses pin with base).
function revisionPinFor(id: string) {
  const target = REVISION_VIEW.target;
  return target && !target.region && target.commit && id === target.commit && !REVISION_VIEW.base ? target : null;
}
function setRevisionWhole(on: boolean) {
  COMPARISON_SCOPE.whole = !!on;
  ++REVISION_VIEW.seq;
  REVISION_VIEW.pdfCommit = '';
  clearRevisionPdf();
  $('#revision-warning').hidden = true;
  setRevisionFormat(DIFF_FORMAT.PDF);
}
function revisionCurrent(seq: number, docKey: string | null, id: string) {
  return (
    seq === REVISION_VIEW.seq &&
    docKey === DOC &&
    id === REVISION_VIEW.commit &&
    document.body.classList.contains('revision-open')
  );
}
// Releases the comparison's rendering and PDF.js resources on a new visit or a change of scope.
function clearRevisionPdf() {
  disposeRevisionZoom();
  if (COMPARISON_PDF.observer) {
    COMPARISON_PDF.observer.disconnect();
    COMPARISON_PDF.observer = null;
  }
  COMPARISON_PDF.tasks.forEach((task) => {
    try {
      task.cancel();
    } catch (error) {}
  });
  COMPARISON_PDF.tasks.clear();
  if (COMPARISON_PDF.loading) {
    try {
      void COMPARISON_PDF.loading.destroy().catch(() => {});
    } catch (error) {}
    COMPARISON_PDF.loading = null;
  }
  COMPARISON_PDF.doc = null;
  $('#revision-pdf').replaceChildren();
}
// The format a document's changes show for the one asked (docs/handbook/viewer.md §변경 보기): the source diff when
// asked; a document drawn from Markdown (drawn) its rendered compare otherwise; the source diff always for another
// document with no comparison PDF (source: one the browser draws, a text document); otherwise a figure document's
// overlay of two builds, and a LaTeX document's comparison PDF - never the overlay. Pure.
function revisionFormatFor(asked: string | undefined, figure: boolean, source: boolean, drawn: boolean) {
  if (asked === DIFF_FORMAT.SOURCE) return DIFF_FORMAT.SOURCE;
  if (drawn && !figure) return DIFF_FORMAT.RENDERED;
  return source && !figure ? DIFF_FORMAT.SOURCE : figure ? DIFF_FORMAT.OVERLAY : DIFF_FORMAT.PDF;
}
// Shows REVISION_VIEW.format: the pressed tab, the pane, [이전 | 지금] with the overlay, and the overlay's status line
// on a figure document (its source diff has none). Loads nothing.
function drawRevisionFormat() {
  $('#revision-pdf-tab').setAttribute('aria-pressed', String(REVISION_VIEW.format === DIFF_FORMAT.PDF));
  $('#revision-overlay-tab').setAttribute('aria-pressed', String(REVISION_VIEW.format === DIFF_FORMAT.OVERLAY));
  $('#revision-source-tab').setAttribute('aria-pressed', String(REVISION_VIEW.format === DIFF_FORMAT.SOURCE));
  $('#revision-rendered-tab').setAttribute('aria-pressed', String(REVISION_VIEW.format === DIFF_FORMAT.RENDERED));
  $('#revision-rendered').hidden = REVISION_VIEW.format !== DIFF_FORMAT.RENDERED;
  drawCompareNavigator();
  $('#revision-view').dataset.format = REVISION_VIEW.format;
  $('#revision-pdf').hidden = REVISION_VIEW.format !== DIFF_FORMAT.PDF;
  $('#revision-source').hidden = REVISION_VIEW.format !== DIFF_FORMAT.SOURCE;
  $('#revision-overlay').hidden = $('#revision-side').hidden = REVISION_VIEW.format !== DIFF_FORMAT.OVERLAY;
  if (REVISION_VIEW.overlay)
    $('#revision-status').textContent =
      REVISION_VIEW.format === DIFF_FORMAT.OVERLAY ? overlayStatus(REVISION_VIEW.overlay) : '';
}
// Switches the format shown, keeping the comparison's scale for the selected commit.
function setRevisionFormat(format: string | undefined) {
  REVISION_VIEW.format = revisionFormatFor(format, !!REVISION_VIEW.overlay, isMarkdownDoc(), isDrawnFromMarkdown());
  drawRevisionFormat();
  if (REVISION_VIEW.format === DIFF_FORMAT.RENDERED && REVISION_VIEW.commit) {
    if (RENDERED_COMPARE.key !== revisionKey())
      showRenderedCompare(REVISION_VIEW.commit, REVISION_VIEW.base, REVISION_VIEW.seq, DOC);
    else $('#revision-status').textContent = RENDERED_COMPARE.line;
    // a range's list painting and its last-seen count come with its source diff's answer: read it beside the compare
    if (REVISION_VIEW.base && REVISION_VIEW.sourceCommit !== revisionKey())
      loadRevisionSource(REVISION_VIEW.commit, REVISION_VIEW.seq, DOC);
  }
  if (REVISION_VIEW.format === DIFF_FORMAT.SOURCE && !REVISION_VIEW.base && isDrawnFromMarkdown())
    $('#revision-status').textContent = '';
  if (
    REVISION_VIEW.format === DIFF_FORMAT.SOURCE &&
    REVISION_VIEW.commit &&
    REVISION_VIEW.sourceCommit !== revisionKey()
  )
    loadRevisionSource(REVISION_VIEW.commit, REVISION_VIEW.seq, DOC);
  if (REVISION_VIEW.format === DIFF_FORMAT.SOURCE && REVISION_VIEW.base && REVISION_VIEW.sourceCommit === revisionKey())
    $('#revision-status').textContent = REVISION_VIEW.rangeLine;
  // The comparison PDF is built only when that format is viewed - [변경 보기] and a range go straight to the source
  // diff, so neither spends a latexdiff build.
  if (REVISION_VIEW.format === DIFF_FORMAT.PDF && REVISION_VIEW.commit && REVISION_VIEW.pdfCommit !== revisionKey()) {
    REVISION_VIEW.pdfCommit = revisionKey();
    $('#revision-status').textContent = '비교 PDF 상태를 확인하는 중입니다.';
    loadRevisionPdf(REVISION_VIEW.commit, REVISION_VIEW.seq, DOC);
  }
  syncRevisionWhole();
  drawRevisionZoom();
  if (revisionPdfActive()) resizeRevisionPdf();
  if (REVISION_VIEW.format === DIFF_FORMAT.OVERLAY && REVISION_VIEW.target) scrollOverlayTo(REVISION_VIEW.target.page);
  if (REVISION_VIEW.target) drawPinGuide();
}
// Shows the manuscript or the changes view: the nav bar's tabs, the navigation sheet's switch and the phone's position
// button ([변경사항 ▾] in the changes view) follow; leaving the changes view forgets the pin it was opened for and
// redraws the pages. The mark badges' press areas are measured again as the pages show (markHitSides: marks drawn
// meanwhile had no boxes).
function setViewMode(mode: string | undefined) {
  const revisions = mode === VIEW_MODE.REVISIONS;
  if (!revisions && document.body.classList.contains('revision-open')) leaveRevisions();
  // the pages are still drawn: keep the spot the way back returns to
  if (revisions && !document.body.classList.contains('revision-open')) keepSpot();
  document.body.classList.toggle('revision-open', revisions);
  $('#view-manuscript').setAttribute('aria-pressed', String(!revisions));
  $('#view-revisions').setAttribute('aria-pressed', String(revisions));
  if (!revisions) {
    REVISION_VIEW.target = null;
    clearRenderedCompare();
  }
  if (revisions) loadRevisions();
  else {
    ++REVISION_VIEW.seq;
    clearRevisionPdf();
    setRevisionOverlay(null);
    $('#revision-pin').hidden = true;
    drawPinGuideActions();
    boundScale();
    returnToSpot();
    if (VECTOR_PDF.doc) scheduleVectorDraw(0);
    updateSectionStrip();
    markHitSides();
  }
  drawNavigationView();
  drawPos();
  searchOffer(); // the changes view has no search
}
// Reads the document's recent commits into the changes view. Without history (not Git, a view-only PDF, no recent
// commit, or more history files than the server names one by one: reason too_many_files) the one reason line stays and
// the unusable [변경 PDF] [소스 diff] and the comparison note are hidden; a pin's guide line stays. A figure document's
// answer carries its two builds (overlay): its [겹쳐 보기] takes the place of [변경 PDF] and opens first, with or
// without history; its [소스 diff] shows only with history.
async function loadRevisions() {
  const seq = ++REVISION_VIEW.seq,
    docKey = DOC,
    list = $('#revision-list'),
    out = $('#revision-diff'),
    target = REVISION_VIEW.target,
    again = !target && REVISION_VIEW.rowsDoc === docKey && REVISION_VIEW.rows.length > 0;
  clearRevisionPdf();
  list.hidden = false;
  list.textContent = '최근 변경사항을 읽는 중입니다.';
  out.textContent = '';
  $('#revision-pin').hidden = !target;
  if (target) drawPinGuide('변경사항을 읽는 중입니다.');
  else drawPinGuideActions();
  let data;
  try {
    data = (
      await api(withDocQuery('/api/revisions?limit=' + REVISION_PAGE, docKey), { what: '변경사항 읽기', silent: true })
    ).data;
  } catch (error) {
    if (seq === REVISION_VIEW.seq) list.textContent = '변경사항을 읽지 못했습니다.';
    return;
  }
  if (seq !== REVISION_VIEW.seq || docKey !== DOC) return;
  const rows = (data.available ? data.revisions : []) as RevisionRow[],
    kept = REVISION_VIEW.range;
  REVISION_VIEW.rows = rows;
  REVISION_VIEW.rowsDoc = docKey || '';
  REVISION_VIEW.more = !!data.more;
  if (!again) REVISION_VIEW.listOpen = false;
  if (!again || !REVISION_VIEW.seen || REVISION_VIEW.seenState !== SEEN_STATE.OK)
    openSeen(seenRecordOf(docKey || ''), rows);
  REVISION_VIEW.history = !!data.available && rows.length > 0;
  setRevisionOverlay(data.overlay || null);
  const isFigure = !!REVISION_VIEW.overlay;
  REVISION_VIEW.format = revisionFormatFor(REVISION_VIEW.format, isFigure, isMarkdownDoc(), isDrawnFromMarkdown());
  // a LaTeX document after a figure leaves the overlay; a Markdown one opens its rendered compare, a text one its
  // source diff
  drawRevisionFormat();
  $('#revision-controls').hidden = !REVISION_VIEW.history && !isFigure;
  $('#revision-note').hidden = !REVISION_VIEW.history;
  $('#revision-pdf-tab').hidden = isFigure || isMarkdownDoc();
  $('#revision-overlay-tab').hidden = !isFigure;
  $('#revision-source-tab').hidden = !REVISION_VIEW.history;
  $('#revision-rendered-tab').hidden = !REVISION_VIEW.history || !isDrawnFromMarkdown();
  if (!data.available) {
    list.textContent =
      data.reason === 'too_many_files'
        ? translateTemplate('이 문서는 이력 파일이 {n}개를 넘어 Git 변경사항을 볼 수 없습니다.', { n: data.limit })
        : '이 문서의 Git 변경사항을 볼 수 없습니다.';
    drawRange();
    if (isFigure) {
      setRevisionFormat(DIFF_FORMAT.OVERLAY);
      return;
    }
    if (target)
      drawPinGuide(
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
    else if (target) drawPinGuide('이 문서의 최근 12개 커밋에 변경이 없습니다.');
    return;
  }
  list.hidden = true;
  list.textContent = '';
  // A pin's commit is picked by the server's rule over the same window (api.md §두 커밋 사이): a hash anywhere in it, a
  // PR number or the lines in its first rows.
  if (target) {
    if (REVISION_VIEW.seenState === SEEN_STATE.PENDING) resolveSeen(docKey || '', rows[0].id);
    const pick = await pickRevisionFor(target, seq, docKey);
    if (seq !== REVISION_VIEW.seq || docKey !== DOC || REVISION_VIEW.target !== target) return;
    target.commit = pick.id;
    target.via = pick.via;
    target.hit = pick.hit;
    REVISION_VIEW.range = { mode: RANGE_MODE.ONE, start: pick.id, end: pick.id, endSet: false };
    // a figure's lines and pictures are both exact: its overlay opens first; a LaTeX pin's lines exist only in the
    // source diff, and a Markdown pin's own hunks too - its [그린 비교] beside it compares the whole commit (ADR-0031
    // D6)
    if (isFigure) showRevision(pick.id, DIFF_FORMAT.OVERLAY);
    else showRevision(pick.id, DIFF_FORMAT.SOURCE);
    drawRange();
    return;
  }
  // Opened by a document's update message (documents/flow-updates.ts openUpdateRange): the commits it named - after the
  // last seen one (base) up to the newest it named (top; the newest row without one) - as a range in the source diff,
  // the list painting what the server says the range holds. Commits above top (the checkout ahead of the shown build,
  // one come since) stay out, also when the list is read again for a new build: the range keeps the message's base and
  // its end (endSet).
  const want = REVISION_VIEW.want;
  REVISION_VIEW.want = null;
  if (want && want.base && !isFigure) {
    const at = (id: string) => rows.findIndex((row) => row.id === id || row.id.startsWith(id)),
      baseAt = at(want.base),
      topAt = want.top ? at(want.top) : 0;
    const top = topAt >= 0 ? rows[topAt].id : want.top,
      base = baseAt >= 0 ? rows[baseAt].id : want.base;
    if (top !== base && !(baseAt >= 0 && topAt > baseAt)) {
      REVISION_VIEW.range = {
        mode: RANGE_MODE.FROM,
        start: baseAt > 0 && baseAt > topAt ? rows[baseAt - 1].id : top,
        end: top,
        endSet: true,
        base,
      };
      showRange(REVISION_VIEW.range);
      return;
    }
  }
  // The same document read again while the view is open (a new build) keeps the range shown, moved to the newest commit
  // unless its end was chosen (endSet: pressed, or named by an update message); a range comes back in its source diff,
  // so a new build never starts its comparison PDF (only [변경 PDF] does). A message's range is its base and end,
  // whatever page of rows is read: thirty newer commits push its start off the first page, and the server still
  // compares them while they are in its history window (else its refusal shows).
  const held = !!kept && kept.mode === RANGE_MODE.FROM && !!kept.base && kept.endSet;
  if (again && (held || rows.some((row) => row.id === kept.start))) {
    if (REVISION_VIEW.seenState === SEEN_STATE.OK && kept.mode !== RANGE_MODE.LAST)
      resolveSeen(docKey || '', rows[0].id);
    showRange(
      kept.mode === RANGE_MODE.ONE ? kept : { ...kept, end: kept.endSet ? kept.end : rows[0].id },
      REVISION_VIEW.format,
    );
    return;
  }
  if (REVISION_VIEW.seenState === SEEN_STATE.PENDING && !isFigure) {
    showRange(rangeMode(rows, REVISION_VIEW.range, RANGE_MODE.LAST, REVISION_VIEW.seen));
    return;
  }
  if (REVISION_VIEW.seenState === SEEN_STATE.PENDING) resolveSeen(docKey || '', rows[0].id);
  const id = rows.some((row) => row.id === REVISION_VIEW.commit) ? REVISION_VIEW.commit : rows[0].id;
  REVISION_VIEW.range = { mode: RANGE_MODE.ONE, start: id, end: id, endSet: false };
  showRevision(id, isFigure ? DIFF_FORMAT.OVERLAY : undefined);
  drawRange();
}
// ------------------------------------------------ Comparing two commits (docs/handbook/viewer.md §변경 보기)
// The quick range [마지막으로 본 뒤 N | 이 커밋부터 | 이 커밋만] (#revision-range) and the commit list that stays on
// screen (#revision-commits). The rules below are pure functions of the loaded rows (newest first); showRange() shows
// their request. What is painted and counted comes from the server's range answer (commit_ids, commits): a range
// follows ancestry, which the list's positions do not show (a merged line, a base on another line, a pull that merged
// older commits).

// The range after a row press (id): in [이 커밋만] that commit alone; otherwise that commit to the newest - except
// that, right after such a press, a newer row ends the range there, and the start pressed again is that commit alone.
// Pure.
function rangePress(rows: { id: string }[], range: RevRange, id: string): RevRange {
  const at = (commit: string) => rows.findIndex((row) => row.id === commit),
    newest = rows.length ? rows[0].id : id;
  if (range.mode === RANGE_MODE.ONE) return { mode: RANGE_MODE.ONE, start: id, end: id, endSet: false };
  if (range.mode === RANGE_MODE.FROM && id === range.start)
    return { mode: RANGE_MODE.FROM, start: id, end: id, endSet: true };
  if (range.mode === RANGE_MODE.FROM && !range.endSet && at(id) >= 0 && at(id) < at(range.start))
    return { mode: RANGE_MODE.FROM, start: range.start, end: id, endSet: true };
  return { mode: RANGE_MODE.FROM, start: id, end: newest, endSet: false };
}
// The range after a segment press: [마지막으로 본 뒤] the last-seen commit to the newest; [이 커밋부터] the commit in
// focus to the newest; [이 커밋만] the commit in focus alone (the newest after [마지막으로 본 뒤]). Pure.
function rangeMode(rows: { id: string }[], range: RevRange, mode: string, seen: RevSeen | null): RevRange {
  const newest = rows.length ? rows[0].id : range.end;
  if (mode === RANGE_MODE.LAST) return { mode, start: newest, end: newest, endSet: false };
  const focus = range.mode === RANGE_MODE.LAST && mode === RANGE_MODE.ONE ? range.end : range.start;
  return { mode, start: focus, end: mode === RANGE_MODE.FROM ? newest : focus, endSet: false };
}
// What a range asks the server: {commit, base}, base '' for one commit against its first parent. [마지막으로 본 뒤]
// compares the last-seen commit with the newest; [이 커밋부터] the start's first parent with the end - a start that is
// the end, or a root commit (no parent), is that commit alone - or, for the range an update message opened, its base
// (the last seen commit, range.base) with the end. Pure.
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
// The commits the list paints for a request: one commit itself; a range the commits the server's answer names (ids, its
// commit_ids), none while that answer is unknown. Pure.
function paintedIds(request: { commit: string; base: string }, ids: string[] | null): string[] {
  return request.base ? (ids || []).slice() : [request.commit];
}
// The rows of merged lines: those between a merge and its first parent, when that parent is loaded. Pages come in
// ancestry order (the server's --topo-order), so a merged line's commits sit right below their merge; a merge whose
// first parent is not loaded marks nothing. Pure.
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
function revisionKey() {
  return REVISION_VIEW.base ? REVISION_VIEW.base + '..' + REVISION_VIEW.commit : REVISION_VIEW.commit;
}
// Shows a range: opens what it asks, then draws the picker - a range always in its source diff (its comparison PDF is
// built only when [변경 PDF] is pressed, whatever format was shown), one commit as a list choice always opened (format
// undefined: the comparison PDF of a LaTeX document, the format shown of a figure document). A Markdown document keeps
// the tab shown, for a range too: its rendered compare builds nothing (revisions/view-rendered-compare.ts).
function showRange(range: RevRange, format?: string) {
  REVISION_VIEW.range = range;
  const request = rangeRequest(REVISION_VIEW.rows, range, REVISION_VIEW.seen);
  const drawn = isDrawnFromMarkdown()
    ? REVISION_VIEW.format === DIFF_FORMAT.SOURCE
      ? DIFF_FORMAT.SOURCE
      : DIFF_FORMAT.RENDERED
    : '';
  showRevision(
    request.commit,
    drawn || (request.base ? (format === DIFF_FORMAT.OVERLAY ? format : DIFF_FORMAT.SOURCE) : format),
    request.base,
  );
  drawRange();
}
// A row of the list pressed (rangePress) and a quick-range segment pressed (rangeMode).
function pressRevisionRow(id: string | undefined) {
  if (id) showRange(rangePress(REVISION_VIEW.rows, REVISION_VIEW.range, id));
}
function setRevisionRange(mode: string | undefined) {
  if (mode === undefined || !REVISION_VIEW.rows.length || mode === REVISION_VIEW.range.mode) return;
  showRange(rangeMode(REVISION_VIEW.rows, REVISION_VIEW.range, mode, REVISION_VIEW.seen));
}
// Draws the quick range: the pressed segment, and [마지막으로 본 뒤 N] - hidden without a record of this document in
// this browser; N is the server's count ('…' while it is asked); not pressable when nothing is new (N = 0) or the
// record could not be read; a record the history no longer has says so (SEEN_STATE.GONE). Then the list.
function drawRange() {
  const rows = REVISION_VIEW.rows,
    range = REVISION_VIEW.range,
    seenState = REVISION_VIEW.seenState;
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
      (seenState === SEEN_STATE.OK && REVISION_VIEW.seenN === 0);
    if (label)
      label.textContent = translate(
        seenState === SEEN_STATE.GONE
          ? '기록한 커밋을 찾을 수 없음'
          : seenState === SEEN_STATE.OLD
            ? '기록한 커밋이 최근 500개보다 오래됨'
            : '마지막으로 본 뒤',
      );
    if (count)
      count.textContent =
        seenState === SEEN_STATE.OK ? String(REVISION_VIEW.seenN) : seenState === SEEN_STATE.PENDING ? '…' : '';
  }
  roveSegment($('#revision-range')); // the group's one Tab stop is the range now chosen (platform/segments.ts)
  renderCommitList();
}
// A commit's time as the list shows it: MM-DD HH:MM of its ISO commit time (the committer's own clock), else its date.
function rowWhen(row: RevisionRow) {
  const time = String(row.time || '');
  return /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(time)
    ? time.slice(5, 10) + ' ' + time.slice(11, 16)
    : String(row.date || '');
}
// The commit list (#revision-commits): a row per loaded commit with its subject, author, time and short hash; a merged
// line's rows indented under their merge (sideRows). The commits the shown comparison covers (paintedIds - the
// server's, never the rows' positions) ride the rail, the first and last of them bold, its old side (left out) a hollow
// dot; the commits the server counts since the last-seen one are marked new, with a line above the last-seen row saying
// where reading stopped. The phone shows REVISION_PHONE_ROWS rows until [더 보기]; [더 보기] then reads the next page
// while the server has more.
function renderCommitList() {
  const box = $('#revision-commits'),
    rows = REVISION_VIEW.rows,
    seen = REVISION_VIEW.seen;
  box.hidden = !rows.length;
  if (!rows.length) {
    box.replaceChildren();
    return;
  }
  const focused = document.activeElement as HTMLElement | null,
    refocus = focused && focused.classList.contains('rc-row') ? focused.dataset.commit : null;
  const inside = new Set(
      paintedIds({ commit: REVISION_VIEW.commit, base: REVISION_VIEW.base }, REVISION_VIEW.rangeIds),
    ),
    side = sideRows(rows),
    fresh = REVISION_VIEW.seenState === SEEN_STATE.OK ? REVISION_VIEW.seenIds : new Set();
  const order = rows.filter((row) => inside.has(row.id)).map((row) => row.id),
    ends = new Set([order[0], order[order.length - 1]]),
    base = REVISION_VIEW.base ? REVISION_VIEW.rangeBase || REVISION_VIEW.base : '';
  const seenAt = REVISION_VIEW.seenState === SEEN_STATE.OK && seen ? rows.findIndex((row) => row.id === seen.id) : -1;
  const cut =
    LAYOUT === LAYOUT_MODE.NARROW && !REVISION_VIEW.listOpen ? Math.min(REVISION_PHONE_ROWS, rows.length) : rows.length;
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
        ? html`<div class="rc-seen" data-i="${index}">${seen && seen.at ? translateTemplate('{when} 여기까지 봄', { when: seen.at }) : translate('여기까지 봄')}</div>`
        : '';
    return html`${line}<button class="${classes.join(' ')}" data-act="revision-row" data-commit="${row.id}" data-i="${index}" aria-pressed="${inside.has(row.id)}">\
<span class="rc-rail" aria-hidden="true"><span class="rc-dot"></span></span><span class="rc-txt"><span class="rc-t" translate="no">${row.subject}</span>\
<span class="rc-m"><span translate="no">${row.author || ''}</span> · ${rowWhen(row)} · <span class="rc-code" translate="no">${row.id.slice(0, 7)}</span></span></span>\
${fresh.has(row.id) ? html`<span class="rc-tag">새로</span>` : ''}</button>`;
  });
  const more =
    cut < rows.length
      ? translateTemplate('이전 커밋 {n}개 더 보기', { n: rows.length - cut })
      : REVISION_VIEW.more
        ? translate('이전 커밋 더 보기')
        : '';
  const hint =
    REVISION_VIEW.range.mode === RANGE_MODE.ONE
      ? '최신이 위 · 누르면 그 커밋 하나'
      : '최신이 위 · 누르면 그 커밋부터 지금까지';
  setHtml(
    box,
    html`<div class="rc-head">${translate(hint)}</div><div class="rc-list">${items}</div>\
${more ? html`<button id="revision-more" class="btn-ghost" data-act="revision-more">${lucideIcon('chevron-down')}<span>${more}</span></button>` : ''}`,
  );
  for (const element of $$('#revision-commits [data-i]') as HTMLElement[])
    element.hidden = Number(element.dataset.i) >= cut;
  if (refocus) {
    const again = box.querySelector('.rc-row[data-commit="' + refocus + '"]') as HTMLElement | null;
    if (again) again.focus();
  }
}
// [더 보기]: the phone's first press shows every loaded row; after that (and on a wide screen) the next page of the
// history.
async function moreRevisions() {
  if (LAYOUT === LAYOUT_MODE.NARROW && !REVISION_VIEW.listOpen && REVISION_VIEW.rows.length > REVISION_PHONE_ROWS) {
    REVISION_VIEW.listOpen = true;
    renderCommitList();
    return;
  }
  if (!REVISION_VIEW.more || !REVISION_VIEW.rows.length) return;
  REVISION_VIEW.listOpen = true;
  if (await moreRows(DOC || '', REVISION_PAGE)) renderCommitList();
}
// Reads the next page (up to limit rows) of document docKey's window onto REVISION_VIEW.rows; whether it did. Nothing
// when the list is another document's or was replaced meanwhile.
async function moreRows(docKey: string | null, limit: number) {
  if (!REVISION_VIEW.more || !REVISION_VIEW.rows.length) return false;
  const last = REVISION_VIEW.rows[REVISION_VIEW.rows.length - 1].id;
  let data;
  try {
    data = (
      await api(withDocQuery('/api/revisions?before=' + encodeURIComponent(last) + '&limit=' + limit, docKey), {
        what: '변경사항 읽기',
        silent: true,
      })
    ).data;
  } catch (error) {
    return false;
  }
  if (
    docKey !== DOC ||
    REVISION_VIEW.rowsDoc !== docKey ||
    !REVISION_VIEW.rows.length ||
    REVISION_VIEW.rows[REVISION_VIEW.rows.length - 1].id !== last
  )
    return false;
  REVISION_VIEW.rows = REVISION_VIEW.rows.concat(data.revisions || []);
  REVISION_VIEW.more = !!data.more;
  return true;
}
// ------------------------------------------------ The last-seen commit (docs/handbook/viewer.md §변경 보기)
// This browser's last-seen commit per document (localStorage limnRevSeen: {<doc>:{id, at}}). No server state: another
// browser or device keeps its own. The server says what it is (resolveSeen): how many commits it compares with the
// newest, or that it is no longer in the history. A record is never overwritten until the server has answered for it.
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
// Takes the document's record for this visit: none, the newest commit itself (0 new, nothing to ask), or one to ask
// about.
function openSeen(seen: RevSeen | null, rows: RevisionRow[]) {
  REVISION_VIEW.seen = seen;
  REVISION_VIEW.seenIds = new Set();
  REVISION_VIEW.seenN = 0;
  REVISION_VIEW.seenState = !seen
    ? SEEN_STATE.NONE
    : rows.length && rows[0].id === seen.id
      ? SEEN_STATE.OK
      : SEEN_STATE.PENDING;
}
// The server's answer for the last-seen range (seen..newest): its count and commits, or why it has none. A refusal that
// says the commit is not in this document's history (or shares none with it) is a record the history no longer has;
// base_too_old is a record still in the history but older than the window (SEEN_STATE.OLD, kept); any other failure
// leaves the record unread, and so kept.
/** @param answer the /api/revision-diff answer with base */
function seenAnswered(answer: any) {
  REVISION_VIEW.seenState = SEEN_STATE.OK;
  REVISION_VIEW.seenN = Number(answer.commits) || 0;
  REVISION_VIEW.seenIds = new Set(answer.commit_ids || []);
}
function seenFailed(error: unknown) {
  const data = (error && (error as ApiError).data) as any,
    why = data && data.reason;
  REVISION_VIEW.seenState =
    why === 'base_too_old'
      ? SEEN_STATE.OLD
      : why === 'commit_not_recent' || why === 'no_merge_base' || why === 'base_after_head'
        ? SEEN_STATE.GONE
        : SEEN_STATE.ERROR;
}
// Asks the server about the last-seen commit when the view does not open on its range (a pin's [변경 보기], a figure's
// overlay).
async function resolveSeen(docKey: string, newest: string) {
  const seen = REVISION_VIEW.seen;
  if (!seen) return;
  try {
    const answer = (
      await api(
        withDocQuery(
          '/api/revision-diff?commit=' + encodeURIComponent(newest) + '&base=' + encodeURIComponent(seen.id),
          docKey,
        ),
        { what: '변경사항 읽기', silent: true },
      )
    ).data;
    if (docKey === DOC && REVISION_VIEW.seen === seen) seenAnswered(answer);
  } catch (error) {
    if (docKey === DOC && REVISION_VIEW.seen === seen) seenFailed(error);
  }
  if (docKey === DOC && REVISION_VIEW.seen === seen) drawRange();
}
// Leaving the changes view (to the manuscript, another document, or closing the page): once the server has answered for
// the record (or there was none), the document's newest loaded commit becomes its last-seen one, with this moment as
// MM-DD HH:MM. A record still being asked about, one the server could not answer for, or one older than the window
// (still in the history, so not to be lost) is kept. The list is forgotten, so coming back starts afresh.
function leaveRevisions() {
  const docKey = REVISION_VIEW.rowsDoc,
    top = REVISION_VIEW.rows[0];
  REVISION_VIEW.rowsDoc = '';
  if (!docKey || !top) return;
  if (
    REVISION_VIEW.seenState === SEEN_STATE.PENDING ||
    REVISION_VIEW.seenState === SEEN_STATE.ERROR ||
    REVISION_VIEW.seenState === SEEN_STATE.OLD
  )
    return;
  const now = new Date(),
    pad = (value: number) => String(value).padStart(2, '0'),
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
// A newly selected commit (or range, from base) starts with fit width. Without a format a LaTeX document shows its
// comparison PDF and a figure document stays in the format it shows (choosing a commit in its source diff keeps the
// source diff).
async function showRevision(id: string, format?: string, base?: string) {
  REVISION_ZOOM.ratio = 1;
  ++REVISION_VIEW.seq;
  REVISION_VIEW.commit = id;
  REVISION_VIEW.base = base || '';
  REVISION_VIEW.rangeLine = '';
  REVISION_VIEW.rangeN = null;
  REVISION_VIEW.rangeIds = null;
  REVISION_VIEW.rangeBase = '';
  REVISION_VIEW.sourceCommit = '';
  REVISION_VIEW.pdfCommit = '';
  clearRevisionPdf();
  clearRenderedCompare();
  $('#revision-note').textContent = REVISION_VIEW.base
    ? '두 커밋 사이의 누적 변경 · 이 문서의 Git 이력 · 미커밋 수정 제외'
    : '선택 커밋의 첫 부모와 비교 · 이 문서의 Git 이력 · 미커밋 수정 제외';
  REVISION_VIEW.scope = null;
  COMPARISON_SCOPE.whole = COMPARISON_SCOPE.partial = COMPARISON_SCOPE.fallback = false;
  drawRevisionOther(null);
  $('#revision-diff').textContent = '';
  $('#revision-file-row').hidden = true;
  $('#revision-warning').hidden = true;
  $('#revision-status').textContent = '';
  setRevisionFormat(format || (REVISION_VIEW.overlay ? REVISION_VIEW.format : DIFF_FORMAT.PDF));
}
// ------------------------------------------------ A figure document's overlay (docs/handbook/viewer.md §변경 보기)
// A figure has no comparison PDF: its changes view lays the previous build's page images over the current ones, page by
// page in one box, and [이전 | 지금] (#revision-side) shows one of the two at a time. The images are the page routes'
// own (/pages/<build>/<file>); the two builds come with /api/revisions.

// The overlay's pages: each page of the build on screen paired with the same page of the previous build, as the box
// that holds both ({page, ratio, pt} - pt its width in points) and each image's name and share of that box in percent
// ({name, w, h}; null when that build has no such page). The box is as wide and as tall as the larger of the two, and
// each image keeps its own size from the top left, so a figure that grew or shrank is never stretched to the other.
// Pure.
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
    const share = (image: PageImage | undefined) =>
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
// A build as a person reads it: a page folder name pages-<YYYYmmddHHMMSS>[-<n>] as 'MM-DD HH:MM:SS', with ' (n)' for a
// second build in the same second; any other name as it is. Pure.
function buildStamp(name: string | null | undefined) {
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
  if (!overlay.prev_build)
    return translate('이전 빌드가 없습니다 — 그림을 다시 가져오면 직전 빌드와 겹쳐 볼 수 있습니다.');
  return translateTemplate('직전 빌드 {prev} → 지금 {cur} · {n}쪽 · [이전]·[지금]으로 같은 자리를 바꿔 봅니다', {
    prev: buildStamp(overlay.prev_build),
    cur: buildStamp(overlay.build),
    n: Math.max(overlay.pages.length, overlay.prev_pages.length),
  });
}
// Takes a document's two builds from /api/revisions (null: not a figure document) and draws them anew, the current one
// shown.
function setRevisionOverlay(overlay: RevisionOverlay | null) {
  REVISION_VIEW.overlay = overlay;
  REVISION_VIEW.side = OVERLAY_SIDE.CUR;
  renderRevisionOverlay();
  drawRevisionSide();
}
// Draws the overlay's pages (overlayPages) into #revision-overlay: per page a box holding the current build's image and
// the previous build's, each at its share of the box; a build without that page has a line saying so in its place. The
// boxes keep their sizes on paper relative to each other (--ov-share) and the widest is at most its print size
// (--ov-cap).
function renderRevisionOverlay() {
  const overlay = REVISION_VIEW.overlay,
    box = $('#revision-overlay');
  box.replaceChildren();
  if (!overlay) return;
  const pages = overlayPages(overlay),
    widest = Math.max(1, ...pages.map((page) => page.pt));
  box.style.setProperty('--ov-cap', Math.round(widest * POINT_PX) + 'px');
  const side = (image: { name: string } | null, build: string | null, className: string, alt: string, none: string) =>
    image && build
      ? html`<img class="${className}" loading="lazy" draggable="false" alt="${alt}" src="${withDocQuery('/pages/' + encodeURIComponent(build) + '/' + encodeURIComponent(image.name))}">`
      : html`<span class="ov-none ${className}">${none}</span>`;
  for (const page of pages) {
    const pageBox = document.createElement('div');
    pageBox.className = 'ov-page';
    pageBox.dataset.page = String(page.page);
    pageBox.style.aspectRatio = page.ratio;
    pageBox.style.setProperty('--ov-share', String(page.pt / widest));
    setHtml(
      pageBox,
      html`${side(page.cur, overlay.build, 'ov-cur', translateTemplate('지금 {page}쪽', { page: page.page }), translate('지금 빌드에 없는 쪽'))}\
${side(page.prev, overlay.prev_build, 'ov-prev', translateTemplate('이전 {page}쪽', { page: page.page }), translate('이전 빌드에 없는 쪽'))}<span class="ov-no">${page.page}</span>`,
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
  const overlay = REVISION_VIEW.overlay,
    none = !overlay || !overlay.prev_build;
  for (const button of $$('#revision-side [role=radio]') as HTMLButtonElement[]) {
    const on = button.dataset.side === REVISION_VIEW.side;
    button.setAttribute('aria-checked', String(on));
    button.classList.toggle('on', on);
    button.disabled = none && button.dataset.side === OVERLAY_SIDE.PREV;
  }
  roveSegment($('#revision-side')); // the group's one Tab stop is the side now chosen (platform/segments.ts)
  $('#revision-overlay').dataset.side = REVISION_VIEW.side;
}
// Shows the previous build's pages (side PREV, when there is one) or the current build's.
function setRevisionSide(side: string | undefined) {
  REVISION_VIEW.side =
    side === OVERLAY_SIDE.PREV && REVISION_VIEW.overlay && REVISION_VIEW.overlay.prev_build
      ? OVERLAY_SIDE.PREV
      : OVERLAY_SIDE.CUR;
  drawRevisionSide();
}
// Brings that page of the overlay to the top of its view, once it is laid out ([변경 보기] of a pin on that page).
function scrollOverlayTo(page: number) {
  requestAnimationFrame(() => {
    const box = $('#revision-overlay'),
      pageBox = box.querySelector('.ov-page[data-page="' + page + '"]');
    if (pageBox) box.scrollTop += pageBox.getBoundingClientRect().top - box.getBoundingClientRect().top;
  });
}
async function loadRevisionSource(id: string, seq: number, docKey: string | null) {
  const out = $('#revision-diff');
  out.textContent = '소스 변경 내용을 읽는 중입니다.';
  $('#revision-file-row').hidden = true;
  const pinTarget = revisionPinFor(id),
    base = REVISION_VIEW.base,
    query = pinTarget ? '&pin=' + pinTarget.id : base ? '&base=' + encodeURIComponent(base) : '';
  try {
    const answer = (
      await api(withDocQuery('/api/revision-diff?commit=' + encodeURIComponent(id) + query, docKey), {
        what: '변경 내용 읽기',
        silent: true,
      })
    ).data;
    if (!revisionCurrent(seq, docKey, id)) return;
    if (base) {
      REVISION_VIEW.rangeLine = rangeSummary(answer);
      if (REVISION_VIEW.format === DIFF_FORMAT.SOURCE) $('#revision-status').textContent = REVISION_VIEW.rangeLine;
      REVISION_VIEW.rangeN = {
        commits: Number(answer.commits) || 0,
        files: Array.isArray(answer.files) ? answer.files.length : 0,
      };
      restateCompareStatus();
      REVISION_VIEW.rangeIds = Array.isArray(answer.commit_ids) ? answer.commit_ids : [];
      REVISION_VIEW.rangeBase = String(answer.base || '');
      if (REVISION_VIEW.range.mode === RANGE_MODE.LAST && REVISION_VIEW.seen && base === REVISION_VIEW.seen.id)
        seenAnswered(answer);
      drawRange();
    }
    // a pin's own hunks when it owns part of the commit; otherwise the whole commit
    const pinScope = answer.scope && answer.scope.mode === SCOPE_MODE.PIN ? answer.scope : null;
    REVISION_VIEW.scope = answer.scope || null;
    if (pinScope) {
      COMPARISON_SCOPE.partial = true;
      syncRevisionWhole();
    }
    const cut = '\n\n' + translate('변경 내용이 커서 앞부분만 표시했습니다. 저장소에서 전체 diff를 확인하세요.');
    REVISION_VIEW.whole = pinScope
      ? pinScope.diff + (pinScope.truncated ? cut : '')
      : (answer.diff ||
          translate(
            base
              ? '이 범위에서 표시할 원고 텍스트 변경이 없습니다.'
              : '이 커밋에서 표시할 원고 텍스트 변경이 없습니다.',
          )) + (answer.truncated ? cut : '');
    REVISION_VIEW.files = revisionFiles(pinScope ? pinScope.diff : answer.diff || '');
    drawRevisionOther(pinScope);
    const select = $('#revision-file');
    setHtml(
      select,
      html`<option value="all">전체 파일</option>${REVISION_VIEW.files.map((file, index) => html`<option value="${index}">${file.name}</option>`)}`,
    );
    select.value = 'all';
    $('#revision-file-row').hidden = REVISION_VIEW.files.length < 2;
    REVISION_VIEW.sourceCommit = revisionKey();
    const target = REVISION_VIEW.target,
      fileIndex = target ? pinFileIndex(REVISION_VIEW.files, target.file) : -1;
    if (fileIndex >= 0 && REVISION_VIEW.files.length > 1) select.value = String(fileIndex);
    renderRevisionFile();
    if (target) highlightPinLines(target);
  } catch (error) {
    if (revisionCurrent(seq, docKey, id)) {
      const why = error && (error as ApiError).data ? errText((error as ApiError).data) : '';
      out.textContent = why
        ? translateTemplate('소스 변경 내용을 읽지 못했습니다: {error}', { error: why })
        : translate('소스 변경 내용을 읽지 못했습니다.');
      // the last-seen range could not be compared: say why on its segment, and show the newest commit alone instead
      if (
        base &&
        REVISION_VIEW.range.mode === RANGE_MODE.LAST &&
        REVISION_VIEW.seen &&
        base === REVISION_VIEW.seen.id
      ) {
        seenFailed(error);
        if (
          (REVISION_VIEW.seenState === SEEN_STATE.GONE || REVISION_VIEW.seenState === SEEN_STATE.OLD) &&
          REVISION_VIEW.rows.length
        ) {
          const top = REVISION_VIEW.rows[0].id;
          showRange({ mode: RANGE_MODE.ONE, start: top, end: top, endSet: false });
        } else drawRange();
      }
    }
  }
}
// A range's summary on the status line (its source diff): the two ends, the commits and files in it, the merge base
// when the base was on another line, and a warning when the range is wide enough for its comparison PDF to fail (more
// than 60 manuscript files, or a diff cut at the server's limit). answer: the /api/revision-diff answer with base.
function rangeSummary(answer: RevisionDiffAnswer) {
  const files = Array.isArray(answer.files) ? answer.files : [];
  let summary = translateTemplate('{base} → {head} · 커밋 {commits}개 · 파일 {files}개', {
    base: String(answer.base || '').slice(0, 8),
    head: String(answer.id || '').slice(0, 8),
    commits: answer.commits,
    files: files.length,
  });
  if (answer.merge_base)
    summary += ' · ' + translateTemplate('공통 조상 {mb}부터 비교', { mb: String(answer.merge_base).slice(0, 8) });
  if (files.length > 60 || answer.truncated) summary += ' · ' + translate('범위가 넓어 비교 PDF가 실패할 수 있습니다');
  return summary;
}
// ------------------------------------------------ [변경 보기] (docs/handbook/viewer.md §변경 보기)
// Opens the changes tab from a pin awaiting review or done. The commit chosen: the commit hash (7+ characters) in the
// close-time reference (ref) > a commit whose subject holds the reference's PR number ('(#236)'/'pull request #236') >
// among the last REVISION_RECENT commits, the most recent one that touched the pin's file and lines (+-5 lines) > the
// most recent commit. Line matching exists only for the source diff - a line whose new-side line number falls within
// the pin's range is highlighted and scrolled to. The comparison PDF (latexdiff) has no SyncTeX mapping, so it only
// moves to near the pin's page. The commit a close reference names among rows (the window's rows, in order) - the
// server's _ref_commit rule: a 7-40 digit hash in every row, a PR number only in the first `recent` rows
// (REVISION_RECENT; a '#N' deeper is another PR's). Pure.
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
function pinFileIndex(files: RevisionFile[], file: string) {
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
function hunkRanges(text: string) {
  const out: number[][] = [];
  for (const match of String(text || '').matchAll(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/gm)) {
    const start = +match[1],
      count = match[2] === undefined ? 1 : +match[2];
    out.push([start, start + Math.max(count, 1) - 1]);
  }
  return out;
}
// A target without lines (a region pin's) touches none.
function touchesPin(files: RevisionFile[], target: RevTarget, slack?: number) {
  const index = pinFileIndex(files, target.file),
    { lo: first, hi: last } = target;
  if (index < 0 || first == null || last == null) return false;
  const reach = slack == null ? 5 : slack;
  return hunkRanges(files[index].text).some(([start, end]) => end >= first - reach && start <= last + reach);
}
// A pin's commit: the one its close_ref names (matchRevision over the whole window - a hash not among the loaded rows
// reads further pages until found or the window ends, as the server resolves it), else the most recent of the first
// REVISION_RECENT rows that touched the pin's lines, else the newest.
async function pickRevisionFor(
  target: RevTarget,
  seq: number,
  docKey: string | null,
): Promise<{ id: string; via: string; tok?: string; hit?: boolean }> {
  let match = matchRevision(target.ref, REVISION_VIEW.rows, REVISION_RECENT);
  while (
    !match &&
    /\b[0-9a-f]{7,40}\b/.test(String(target.ref || '')) &&
    REVISION_VIEW.more &&
    seq === REVISION_VIEW.seq &&
    docKey === DOC
  ) {
    if (!(await moreRows(docKey, 50))) break;
    match = matchRevision(target.ref, REVISION_VIEW.rows, REVISION_RECENT);
  }
  if (match) return match;
  const recent = REVISION_VIEW.rows.slice(0, REVISION_RECENT);
  if (!target.region && target.file) {
    for (const row of recent) {
      if (seq !== REVISION_VIEW.seq || docKey !== DOC) break;
      try {
        const answer = (
          await api(withDocQuery('/api/revision-diff?commit=' + encodeURIComponent(row.id), docKey), {
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
// The guide line (#revision-pin) for the pin the view was opened for: which commit it shows and why, what the format
// shown can say of the pin's lines (message, when given, in their place), and the review access this person lacks.
function drawPinGuide(message?: string) {
  const target = REVISION_VIEW.target,
    box = $('#revision-pin');
  if (!target) {
    box.hidden = true;
    return;
  }
  const via =
    {
      sha: translateTemplate('참조의 커밋 {tok}', { tok: target.tokOf || '' }),
      pr: translate('참조의 PR'),
      lines: translate('이 줄을 바꾼 가장 최근 커밋'),
      latest: translate('참조로 커밋을 찾지 못해 가장 최근 커밋'),
    }[target.via as string] || '';
  const where = target.region
    ? translateTemplate('쪽 {page} 영역', { page: target.page })
    : target.name + ' ' + lineRange(target.lo, target.hi);
  const pinScope =
    REVISION_VIEW.format === DIFF_FORMAT.SOURCE && REVISION_VIEW.scope && REVISION_VIEW.scope.mode === SCOPE_MODE.PIN
      ? REVISION_VIEW.scope
      : null;
  const scopeText = pinScope
    ? translateTemplate('이 핀의 변경 {n}곳만 보입니다', { n: pinScope.hunks }) +
      ' (' +
      translate(pinScope.source === SCOPE_SOURCE.CHANGES ? '에이전트가 기록한 줄' : '핀 자리로 추정') +
      ') · '
    : '';
  let text = message
    ? translate(message)
    : REVISION_VIEW.format === DIFF_FORMAT.RENDERED
      ? target.mdcMsg || translate('두 판을 그려 견주는 중입니다.')
      : REVISION_VIEW.format === DIFF_FORMAT.OVERLAY
        ? translateTemplate('직전 빌드와 지금 빌드의 {page}쪽을 겹쳐 보입니다 — [이전]·[지금]으로 바꿔 보세요', {
            page: target.page,
          }) + (REVISION_VIEW.history ? ' · ' + translate('고친 줄은 [소스 diff]') : '')
        : scopeText +
          (REVISION_VIEW.format === DIFF_FORMAT.PDF
            ? translateTemplate(
                '비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',
                { page: target.page },
              )
            : translate(
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
    html`<span><b>${translateTemplate('핀 #{id}', { id: target.id })}</b> · ${where}${target.ref ? ' · ' + translateTemplate('참조 {ref}', { ref: target.ref }) : ''}${via ? ' · ' + via : ''}</span><span class="rp-msg">${text}${access ? html` <span class="review-access">${access}</span>` : ''}</span>`,
  );
  box.dataset.id = String(target.id);
  box.hidden = false;
  drawPinGuideActions();
}
// The guide line's buttons (docs/handbook/viewer.md §변경 보기): [원고로] and, for a pin awaiting review that this
// person may confirm (a person with write access, not a view-only region pin), the card's [확인] - the same
// data-act="confirm" and confirmPin(), soft for the author as on the card. On the phone and tablet sheet they sit in
// the thumb row (#revision-acts) right above the status line and the tool bar; in the other bands at the guide line's
// right. Redrawn on a band change and whenever the pin lists change.
function drawPinGuideActions() {
  const target = REVISION_VIEW.target,
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
  const backDoc = REVISION_VIEW.back && REVISION_VIEW.back !== DOC ? docInfo(REVISION_VIEW.back) : null,
    back = backDoc ? backDoc.name : null,
    actionBox = document.createElement('span');
  actionBox.className = 'rp-acts';
  const confirmButton = confirm
    ? html`<button class="btn-sm b-confirm ${isMe(pin.author) ? 'btn-soft' : 'btn-secondary'}" data-act="confirm" data-tip="${TIP_TEXT.confirm}">확인</button>`
    : '';
  setHtml(
    actionBox,
    html`<button class="btn-sm" data-act="rev-back" data-tip="${back ? translateTemplate('{name} 원고 보기로 돌아갑니다', { name: back }) : translate('원고 보기로 돌아갑니다')}">${back ? translateTemplate('{name}(으)로', { name: back }) : translate('원고로')}</button>${confirmButton}`,
  );
  (narrow ? row : $('#revision-pin')).appendChild(actionBox);
  row.dataset.id = String(target.id);
  row.hidden = !narrow;
  document.body.classList.toggle('rev-thumb', narrow);
}
// A target without lines (a region pin's) marks none and neither hits nor comes near.
function highlightPinLines(target: RevTarget) {
  const { lo: firstLine, hi: lastLine } = target;
  if (firstLine == null || lastLine == null) {
    target.hit = false;
    target.near = false;
    drawPinGuide();
    return;
  }
  const rows = $$('#revision-diff .rd-line');
  let first = null as Element | null;
  rows.forEach((line) => {
    if (!(line.classList.contains('rd-add') || line.classList.contains('rd-context'))) return;
    const lineNumber = +findElement(line, '.rd-no', HTMLElement).textContent;
    if (lineNumber >= firstLine && lineNumber <= lastLine) {
      line.classList.add('rd-pin');
      if (!first) first = line;
    }
  });
  target.hit = !!first || touchesPin(REVISION_VIEW.files, target, 5);
  // when only a neighbouring line changed, the guide never speaks of "the highlighted line": there is none
  target.near = !first && target.hit;
  if (!first) {
    const fileIndex = pinFileIndex(REVISION_VIEW.files, target.file);
    if (fileIndex < 0) target.hit = false;
    else {
      let best = null as Element | null,
        bestDistance = Infinity;
      rows.forEach((line) => {
        const lineNumber = +findElement(line, '.rd-no', HTMLElement).textContent;
        if (!lineNumber) return;
        const distance = Math.min(Math.abs(lineNumber - firstLine), Math.abs(lineNumber - lastLine));
        if (distance < bestDistance) {
          bestDistance = distance;
          best = line;
        }
      });
      first = best;
    }
  }
  drawPinGuide();
  const top = first;
  if (top) requestAnimationFrame(() => top.scrollIntoView({ block: 'center' }));
}
function findAnyPin(id: number | null) {
  return (
    OPEN_ALL.find((pin) => pin.id === id) ||
    REVIEW_ALL.find((pin) => pin.id === id) ||
    DONE_ALL.find((pin) => pin.id === id) ||
    null
  );
}
// REVISION_VIEW.back remembers the manuscript document that opened [변경 보기], so [원고로] returns there.
// [원고로] and Esc in the changes view: back to the manuscript view, and to the document it was opened from.
function returnToManuscript() {
  const back = REVISION_VIEW.back;
  REVISION_VIEW.back = null;
  setViewMode(VIEW_MODE.MANUSCRIPT);
  if (back && back !== DOC && docInfo(back)) switchDoc(back);
}
// Opens a pin's changes view, only for the document visit that started the switch to its document.
async function showChange(id: number) {
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
  if (fromManuscript) REVISION_VIEW.back = back;
  REVISION_VIEW.target = {
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
  const match = /\b[0-9a-f]{7,40}\b/.exec(REVISION_VIEW.target.ref);
  REVISION_VIEW.target.tokOf = match ? match[0] : '';
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
  if (document.body.classList.contains('revision-open')) loadRevisions();
  else setViewMode(VIEW_MODE.REVISIONS);
}
// times a comparison asks again, a second apart, for the one before it: past latexdiff's and latexmk's limits together
const REVISION_BUSY_WAITS = 240;
// Asks for the comparison. A document builds one at a time, and opening this view starts the newest commit's: a press
// on another commit while it runs is answered busy, and waits for it here, saying so, instead of stopping on that
// answer. Null: the view moved on while it waited; leaving for the source diff stops the waiting too, and coming back
// asks again (REVISION_VIEW.pdfCommit). The waiting line is cleared only while it still says this wait's words, never
// another comparison's.
async function revisionStart(body: Record<string, unknown>, seq: number, docKey: string | null, id: string) {
  const box = $('#revision-status'),
    waiting = translate('앞선 비교 PDF가 끝나는 대로 이 비교 PDF를 만듭니다. 원고와 핀은 그대로 사용할 수 있습니다.');
  const left = () => {
    if (!revisionCurrent(seq, docKey, id)) return true;
    if (REVISION_VIEW.format === DIFF_FORMAT.PDF) return false;
    REVISION_VIEW.pdfCommit = '';
    if (box.textContent === waiting) box.textContent = '';
    return true;
  };
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
// Starts or reads the comparison PDF of commit id for one visit: a late answer or module import never attaches to
// another view (revisionCurrent after every wait). mountRevisionPdf then owns the zoomable page geometry.
async function loadRevisionPdf(id: string, seq: number, docKey: string | null) {
  const statusBox = $('#revision-status'),
    warningBox = $('#revision-warning'),
    target = REVISION_VIEW.target;
  // for a pin, the comparison is the old side plus only that pin's hunks, unless [커밋 전체 비교] is on or that build
  // already failed
  const pin = target && revisionPinFor(id) && !COMPARISON_SCOPE.whole && !COMPARISON_SCOPE.fallback ? target.id : null,
    base = REVISION_VIEW.base,
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
      COMPARISON_SCOPE.partial = status.scope === SCOPE_MODE.PIN;
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
        await api(withDocQuery('/api/revision-build?commit=' + encodeURIComponent(id) + query, docKey), {
          what: '비교 PDF 상태',
          silent: true,
        })
      ).data;
    }
    if (!revisionCurrent(seq, docKey, id)) return;
    if (pin && status.scope === SCOPE_MODE.PIN && status.state === REVISION_STATE.ERROR) {
      // the pin's hunks alone did not compile: show the whole commit, say so in one line
      COMPARISON_SCOPE.fallback = true;
      syncRevisionWhole();
      return loadRevisionPdf(id, seq, docKey);
    }
    if (status.state !== REVISION_STATE.READY)
      throw new Error(
        errText(status) ||
          translate(
            status.state === REVISION_STATE.RUNNING
              ? '비교 PDF 대기 시간이 지났습니다. 다시 열어 재시도하세요.'
              : '비교 PDF를 만들지 못했습니다.',
          ),
      );
    if (status.head && status.head !== id) throw new Error(translate('요청한 커밋과 비교 PDF의 커밋이 다릅니다.'));
    const warnings = Array.isArray(status.warnings) ? status.warnings : [];
    warningBox.hidden = !warnings.length;
    findElement(warningBox, 'summary', HTMLElement).textContent = translateTemplate('빌드 경고 {n}건 보기', {
      n: warnings.length,
    });
    findElement(warningBox, 'pre', HTMLPreElement).textContent = warnings.join('\n');
    warningBox.open = false;
    statusBox.textContent = '비교 PDF를 읽는 중입니다.';
    const response = await fetch(withDocQuery('/api/revision-pdf?commit=' + encodeURIComponent(id) + query, docKey));
    if (!response.ok)
      throw new Error(translateTemplate('비교 PDF를 열지 못했습니다 (HTTP {status}).', { status: response.status }));
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!revisionCurrent(seq, docKey, id)) return;
    const lib = VECTOR_PDF.lib || (await import('/vendor/pdfjs/pdf.min.mjs?v=' + PDFJS_VERSION));
    if (!revisionCurrent(seq, docKey, id)) return;
    lib.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs?v=' + PDFJS_VERSION;
    const loading = lib.getDocument({ data: bytes, isEvalSupported: false, useWasm: false, enableXfa: false });
    COMPARISON_PDF.loading = loading;
    const pdf = await loading.promise;
    if (!revisionCurrent(seq, docKey, id)) {
      try {
        void loading.destroy().catch(() => {});
      } catch (error) {}
      return;
    }
    COMPARISON_PDF.doc = pdf;
    const lead =
      pin && status.scope === SCOPE_MODE.PIN
        ? translateTemplate('핀 #{id}의 변경만', { id: pin }) + ' · '
        : COMPARISON_SCOPE.fallback && target
          ? translate('이 핀의 변경만으로는 비교 PDF를 만들지 못해 커밋 전체를 비교합니다') + ' · '
          : '';
    const sides = { base: String(status.base || '').slice(0, 8), head: id.slice(0, 8), n: pdf.numPages };
    statusBox.textContent =
      lead +
      (base
        ? translateTemplate('기준 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가', sides) +
          (status.merge_base
            ? ' · ' + translateTemplate('공통 조상 {mb}부터 비교', { mb: String(status.merge_base).slice(0, 8) })
            : '')
        : translateTemplate('첫 부모 {base} → {head} · {n}쪽 · 읽기 전용 · 빨강 삭제 / 파랑 추가', sides));
    await mountRevisionPdf(pdf, seq, docKey, id);
  } catch (error) {
    if (revisionCurrent(seq, docKey, id)) {
      clearRevisionPdf();
      const data = (error && (error as ApiError).data) as any;
      statusBox.textContent = translateTemplate('비교 PDF: {error} 소스 diff에서 변경 내용을 확인할 수 있습니다.', {
        error:
          data && data.error
            ? errText(data)
            : error && (error as Error).message
              ? (error as Error).message
              : translate('표시하지 못했습니다.'),
      });
    }
  }
}
export {
  REVISION_VIEW,
  COMPARISON_PDF,
  COMPARISON_SCOPE,
  findAnyPin,
  hunkRanges,
  loadRevisions,
  moreRevisions,
  pressRevisionRow,
  renderCommitList,
  renderRevisionFile,
  returnToManuscript,
  revisionKey,
  drawPinGuideActions,
  drawPinGuide,
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
