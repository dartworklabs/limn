/** Apply source-line selections to the composer, including drafts restored into the fallback line view. */
import {
  COMPOSE,
  REPICK,
  DOC,
  setRepickCandidate,
  setPickseq,
  PICKSEQ,
  setComposeCurrent,
  setComposeIntent,
  setComposePicking,
  setComposeDismissedOverlap,
  PINS,
  setSnipOpen,
  LAYOUT,
} from '../app/state.ts';
import { isRegion, isTextDoc } from '../documents/state.ts';
import { MARKDOWN_VIEW } from './state.ts';
import { $, findMaybe } from '../platform/dom.ts';
import { markdownLevels, lineSnippet } from './view-levels.ts';
import { useLevel, levelOf } from '../documents/rules.ts';
import { linePick } from './state-seams.ts';
import { endTopic } from '../platform/notices.ts';
import { NOTICE_TOPIC } from '../platform/tables.ts';
import { setSide, applySide } from '../layout/flow.ts';
import { overlapsFor } from '../app/rules-pins.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { revealBox } from '../pdf/input-selection.ts';
import { LAST_POINTER } from '../platform/tooltip.ts';

// The line view offers the chosen lines alone (lineView): a pick of this document whose ladder came from the drawn
// document (a draft kept from before the parser failed) keeps its lines but takes the ladder a pick there gives - those
// lines, as lines.
function relevelForLineView() {
  const selection = COMPOSE.current;
  if (
    !selection ||
    REPICK ||
    isRegion(selection) ||
    selection.doc !== DOC ||
    selection.file !== MARKDOWN_VIEW.file ||
    typeof selection.lo !== 'number' ||
    typeof selection.hi !== 'number' ||
    !$('#md.md-lines')
  )
    return;
  if (
    (selection.levels || []).every(
      (level) => level.level === 'raw' && level.lo === selection.lo && level.hi === selection.hi,
    )
  )
    return;
  const range = { lo: selection.lo, hi: selection.hi };
  selection.levels = markdownLevels(range, null, null);
  selection.raw_lo = range.lo;
  selection.raw_hi = range.hi;
  selection.default_level = 'raw';
  useLevel(selection, 'raw');
  linePick().renderComposer();
}
// Fills the composer with lines range of the document on screen, as pick() does with a /api/pick answer; tapped: a tap
// picked a block, so the block rung is the default (the section rung on a heading). During a re-place it is the
// candidate instead (bannerCompare), with nothing else changed.
function pickLines(
  range: { lo: number; hi: number },
  startBlock: HTMLElement | null,
  endBlock: HTMLElement | null,
  quote: string,
  tapped: boolean,
) {
  const levels = markdownLevels(range, startBlock, endBlock, tapped),
    quoted = String(quote || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 160);
  const head = tapped && MARKDOWN_VIEW.heads.some((heading) => heading.lo === range.lo && heading.lo === range.hi);
  const defaultLevel =
    // a tap on a text document picks its line
    tapped && !isTextDoc() && levelOf({ levels }, head ? 'section' : 'block') ? (head ? 'section' : 'block') : 'raw';
  const selection: LinePick = {
    doc: DOC,
    file: MARKDOWN_VIEW.file,
    name: MARKDOWN_VIEW.name,
    lo: range.lo,
    hi: range.hi,
    raw_lo: range.lo,
    raw_hi: range.hi,
    kind: 'lines',
    score: null,
    warn: null,
    snippet: lineSnippet(range.lo, range.hi),
    levels,
    default_level: defaultLevel,
    n_lines: MARKDOWN_VIEW.lines.length,
    quote: quoted,
    overlaps: [],
  };
  if (REPICK) {
    setRepickCandidate(REPICK, selection);
    linePick().compare();
    return;
  }
  endTopic(NOTICE_TOPIC.PICK);
  setPickseq(PICKSEQ + 1);
  setComposeCurrent(selection);
  setComposeIntent(COMPOSE.intent + 1);
  setComposePicking(false);
  selection.scope = null;
  selection.elSel = null;
  useLevel(selection, defaultLevel);
  $('#composer').hidden = false;
  linePick().setBusy(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  setSide(true);
  applySide();
  setComposeDismissedOverlap(null);
  selection.overlaps = overlapsFor(selection, PINS);
  setSnipOpen(false);
  linePick().renderComposer();
  linePick().renderVerdictRow();
  $('#composer').scrollTop = 0;
  if (LAYOUT !== LAYOUT_MODE.WIDE) $('#right').scrollTop = 0;
  // the chosen lines out from under the sheet (compact), as a PDF box is
  revealBox(findMaybe(document, '#md .md-sel', HTMLElement));
  if (LAST_POINTER === 'mouse') $('#note').focus({ preventScroll: true });
}

export { relevelForLineView, pickLines };
