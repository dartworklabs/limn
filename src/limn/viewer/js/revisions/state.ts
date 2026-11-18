import { isRecord } from '../platform/tables.ts';
import { isApiError } from '../platform/api.ts';
import { DIFF_FORMAT, OVERLAY_SIDE, RANGE_MODE, SEEN_STATE } from '../app/rules-tables.ts';
import { DOC } from '../app/state.ts';

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

// What the revision view shows and where it stands (REVISION_VIEW): the request counter, the source diff's files and
// whole text, the commit shown and the one its source diff is of, the format, the commit's scope a pin's diff read
// answers (GET /api/revision-diff?pin=; null before such a read), the rest of the commit's diff beside a pin's hunks,
// the pin's target, the commit of the PDF shown, the document to go back to, the overlay and its side, whether the
// history is open, its base, rows, their document and whether more are listed, the range and what was seen of it, the
// range's commits, base, summary line and counts, whether the list is open, and the range the list is to paint.
interface RevisionViewState {
  seq: number;
  files: { name: string; text: string }[];
  whole: string;
  commit: string;
  sourceCommit: string;
  format: string;
  scope: RevisionPinScope | RevisionCommitScope | null;
  other: string;
  target: RevTarget | null;
  pdfCommit: string;
  back: string | null;
  overlay: RevisionOverlay | null;
  side: string;
  history: boolean;
  base: string;
  rows: RevisionRow[];
  rowsDoc: string;
  more: boolean;
  range: RevRange;
  seen: RevSeen | null;
  seenState: string;
  seenN: number;
  seenIds: Set<string>;
  rangeIds: string[] | null;
  rangeBase: string;
  listOpen: boolean;
  rangeLine: string;
  rangeN: { commits: number; files: number } | null;
  want: { base: string; top: string } | null;
}
const REVISION_VIEW: RevisionViewState = {
  seq: 0,
  files: [],
  whole: '',
  commit: '',
  sourceCommit: '',
  format: DIFF_FORMAT.PDF,
  scope: null,
  other: '',
  target: null,
  pdfCommit: '',
  back: null,
  overlay: null,
  side: OVERLAY_SIDE.CUR,
  history: false,
  base: '',
  rows: [],
  rowsDoc: '',
  more: false,
  range: { mode: RANGE_MODE.ONE, start: '', end: '', endSet: false },
  seen: null,
  seenState: SEEN_STATE.NONE,
  seenN: 0,
  seenIds: new Set(),
  rangeIds: null,
  rangeBase: '',
  listOpen: false,
  rangeLine: '',
  rangeN: null,
  want: null,
};
// Sets the line the guide says for a revision view's pin (RevTarget.mdcMsg), for another module that changes it
// (ADR-0042 D1).
function setTargetGuideLine(target: RevTarget, line: string) {
  target.mdcMsg = line;
}

// The pin whose hunks a commit's view is scoped to: only the commit picked for the pin ([변경 보기]); any other commit
// chosen in the list is shown whole (another commit's lines are not this pin's), and so is a range (pin scoping and
// ranges do not combine; the server refuses pin with base).
function revisionPinFor(id: string) {
  const target = REVISION_VIEW.target;
  return target && !target.region && target.commit && id === target.commit && !REVISION_VIEW.base ? target : null;
}

function revisionCurrent(seq: number, docKey: string | null, id: string) {
  return (
    seq === REVISION_VIEW.seq &&
    docKey === DOC &&
    id === REVISION_VIEW.commit &&
    document.body.classList.contains('revision-open')
  );
}

// The key a source diff or comparison PDF was loaded for: the commit, or base..commit for a range.
function revisionKey() {
  return REVISION_VIEW.base ? REVISION_VIEW.base + '..' + REVISION_VIEW.commit : REVISION_VIEW.commit;
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
// answer is the /api/revision-diff answer with base.
function seenAnswered(answer: RevisionDiff) {
  REVISION_VIEW.seenState = SEEN_STATE.OK;
  REVISION_VIEW.seenN = Number(answer.commits) || 0;
  REVISION_VIEW.seenIds = new Set(answer.commit_ids || []);
}
function seenFailed(error: unknown) {
  const data = isApiError(error) ? error.data : undefined,
    why = isRecord(data) ? data.reason : undefined;
  REVISION_VIEW.seenState =
    why === 'base_too_old'
      ? SEEN_STATE.OLD
      : why === 'commit_not_recent' || why === 'no_merge_base' || why === 'base_after_head'
        ? SEEN_STATE.GONE
        : SEEN_STATE.ERROR;
}

/** Start a new commit or range and invalidate results from the previous comparison. */
function beginRevisionComparison(id: string, base?: string) {
  ++REVISION_VIEW.seq;
  REVISION_VIEW.commit = id;
  REVISION_VIEW.base = base || '';
  REVISION_VIEW.rangeLine = '';
  REVISION_VIEW.rangeN = null;
  REVISION_VIEW.rangeIds = null;
  REVISION_VIEW.rangeBase = '';
  REVISION_VIEW.sourceCommit = '';
  REVISION_VIEW.pdfCommit = '';
}

/** Replace the history page, retaining the expanded list on a repeat visit. */
function setRevisionRows(rows: RevisionRow[], docKey: string | null, more: boolean, again: boolean) {
  REVISION_VIEW.rows = rows;
  REVISION_VIEW.rowsDoc = docKey || '';
  REVISION_VIEW.more = more;
  if (!again) REVISION_VIEW.listOpen = false;
}

/** Append the next page of history and remember whether there is another. */
function appendRevisionRows(rows: RevisionRow[], more: boolean) {
  REVISION_VIEW.rows = REVISION_VIEW.rows.concat(rows);
  REVISION_VIEW.more = more;
}

/** Install the pair of builds and select the current build. */
function replaceRevisionOverlay(overlay: RevisionOverlay | null) {
  REVISION_VIEW.overlay = overlay;
  REVISION_VIEW.side = OVERLAY_SIDE.CUR;
}

/** Select the previous build only when the overlay includes it. */
function chooseRevisionSide(side: string | undefined) {
  REVISION_VIEW.side =
    side === OVERLAY_SIDE.PREV && REVISION_VIEW.overlay && REVISION_VIEW.overlay.prev_build
      ? OVERLAY_SIDE.PREV
      : OVERLAY_SIDE.CUR;
}

/** Remember the commits and base that the server actually compared. */
function rememberRangeCommits(answer: RevisionDiff) {
  REVISION_VIEW.rangeIds = Array.isArray(answer.commit_ids) ? answer.commit_ids : [];
  REVISION_VIEW.rangeBase = String(answer.base || '');
}

/** Keep the server counts used by the rendered comparison status. */
function countRevisionRange(answer: RevisionDiff) {
  REVISION_VIEW.rangeN = {
    commits: Number(answer.commits) || 0,
    files: Array.isArray(answer.files) ? answer.files.length : 0,
  };
}

/** Consume the range requested by a document update. */
function takeWantedRange() {
  const want = REVISION_VIEW.want;
  REVISION_VIEW.want = null;
  return want;
}

/** Consume the document to reopen after leaving a pin comparison. */
function takeReturnDocument() {
  const back = REVISION_VIEW.back;
  REVISION_VIEW.back = null;
  return back;
}

/** Invalidate outstanding requests and return the new visit sequence. */
function advanceRevisionVisit() {
  return ++REVISION_VIEW.seq;
}

/** Choose a single commit against its parent. */
function chooseSingleRevision(id: string) {
  REVISION_VIEW.range = { mode: RANGE_MODE.ONE, start: id, end: id, endSet: false };
}

/** Remember the pin and its reference, preserving the return document on subsequent pin comparisons. */
function openRevisionTarget(fromManuscript: boolean, back: string | null, target: RevTarget) {
  if (fromManuscript) REVISION_VIEW.back = back;
  REVISION_VIEW.target = target;
  const match = /\b[0-9a-f]{7,40}\b/.exec(target.ref);
  target.tokOf = match ? match[0] : '';
}

/** Store the whole patch and its file choices from the same diff. */
function keepRevisionSource(whole: string, files: RevisionViewState['files']) {
  REVISION_VIEW.whole = whole;
  REVISION_VIEW.files = files;
}

/** Forget the pin when returning to the manuscript. */
function clearRevisionTarget() {
  REVISION_VIEW.target = null;
}

/** Invalidate the history list so the next visit reloads its document. */
function forgetRevisionRows() {
  REVISION_VIEW.rowsDoc = '';
}

/** Show all loaded history rows on a narrow screen. */
function expandRevisionRows() {
  REVISION_VIEW.listOpen = true;
}

/** Record which commit or range the source pane shows. */
function markRevisionSourceLoaded() {
  REVISION_VIEW.sourceCommit = revisionKey();
}

/** Select the format displayed by all comparison panes. */
function chooseRevisionFormat(value: string) {
  REVISION_VIEW.format = value;
}

/** Keep the remainder of a pin-scoped diff for its disclosure control. */
function setRevisionOther(value: string) {
  REVISION_VIEW.other = value;
}

/** Record the PDF request key, or clear it to allow another request. */
function setRevisionPdfKey(value: string) {
  REVISION_VIEW.pdfCommit = value;
}

/** Remember whether the loaded history offers commits to compare. */
function setRevisionHistoryAvailable(value: boolean) {
  REVISION_VIEW.history = value;
}

/** Keep the range chosen in the revision picker. */
function chooseRevisionRange(value: RevRange) {
  REVISION_VIEW.range = value;
}

/** Store the summary for the source and rendered status lines. */
function setRevisionRangeSummary(value: string) {
  REVISION_VIEW.rangeLine = value;
}

/** Record which part of the commit the pin-scoped source request returned. */
function setRevisionPinScope(value: RevisionViewState['scope']) {
  REVISION_VIEW.scope = value;
}

export {
  openSeen,
  seenFailed,
  seenAnswered,
  beginRevisionComparison,
  setRevisionRows,
  appendRevisionRows,
  replaceRevisionOverlay,
  chooseRevisionSide,
  rememberRangeCommits,
  countRevisionRange,
  takeWantedRange,
  takeReturnDocument,
  advanceRevisionVisit,
  chooseSingleRevision,
  openRevisionTarget,
  keepRevisionSource,
  clearRevisionTarget,
  forgetRevisionRows,
  expandRevisionRows,
  markRevisionSourceLoaded,
  chooseRevisionFormat,
  setRevisionOther,
  setRevisionPdfKey,
  setRevisionHistoryAvailable,
  chooseRevisionRange,
  setRevisionRangeSummary,
  setRevisionPinScope,
  REVISION_VIEW,
  setTargetGuideLine,
  revisionPinFor,
  revisionCurrent,
  revisionKey,
};
