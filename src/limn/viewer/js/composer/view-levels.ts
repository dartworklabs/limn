// ------------------------------------------------ Range levels
import { captureVisit, currentVisit, isFigureKind, COMPOSE, EDITOR, META, REPICK } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import type { Html } from '../platform/markup.ts';
import { LANG, translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { elementName, isFrac, isPiece, rungHasElement, rungTip } from '../pdf/view-figure.ts';
import { snapSelectionBox } from '../pdf/input-selection.ts';
import { UI_LANG, tableEntry } from '../platform/tables.ts';
import { segmentFocusAt, keepSegmentFocus, roveSegment } from '../platform/segments.ts';
import { VIA } from '../app/rules-tables.ts';
import { lineRange } from '../app/rules-pins.ts';
import { isMarkdownDoc, withDocQuery } from '../documents/state.ts';
import { levelOf } from '../documents/rules.ts';
/** What a range ladder and its excerpt belong to: the composer's selection or an open edit card. */
type RangeOwner = ComposerSelection | EditCard;
// Which of the three a range belongs to. The composing selection and a re-place's candidate both have a box that
// follows the range (followRange), so both ask for the ladder and for where its rungs print; an open edit card asks
// for neither - its box is the saved pin's mark, which the pin list answers
// (docs/adr/0051-pin-badge-drag-reposition.md D5).
type RangeRole = 'compose' | 'edit' | 'repick';
function rangeRole(owner: RangeOwner): RangeRole {
  if (owner === COMPOSE.current) return 'compose';
  if (REPICK && REPICK.cand === owner) return 'repick';
  return 'edit';
}
// Whether the owner a range refresh went out for is still the one holding that role, so its answer may be taken.
function stillOwns(owner: RangeOwner, role: RangeRole, visit: ReturnType<typeof captureVisit>) {
  if (role === 'edit') return owner === EDITOR.current;
  if (role === 'repick') return !!REPICK && REPICK.cand === owner && currentVisit(visit);
  return owner === COMPOSE.current && currentVisit(visit);
}
/** A range owner on lines: its file and both end lines are there, as on every owner that is not a region. */
type LineOwner = RangeOwner & { file: string; lo: number; hi: number };
function onLines(owner: RangeOwner): owner is LineOwner {
  return typeof owner.file === 'string' && typeof owner.lo === 'number' && typeof owner.hi === 'number';
}
// A Markdown document's rungs (markdown/view-levels.ts markdownLevels, ADR-0025 D3): a block is md:<its kind> (the rung's
// env), a section md:section, and several blocks whole (level blocks) are lines - a pin's scope is one of the server's
// (wireScope), and blocks is none of them.
function wireScope(scope: string) {
  return scope === 'blocks' ? 'lines' : scope;
}
function kindFor(scope: string | null | undefined, env: string | null | undefined) {
  if (!scope) return null;
  if (scope.startsWith('env')) return 'env:' + (env || '?');
  if (scope === 'block') return 'md:' + (env || 'paragraph');
  if (scope === 'section') return 'md:section';
  if (scope === 'indent') return 'indent'; // a text document's indented block (ADR-0029 D3)
  return scope === 'para' ? 'paragraph' : 'lines';
}
// The name of the owner's range kind for a description: its rung's, else its kind's; '' for lines set one by one (scope
// 'lines'), whose lines alone say what they are.
// A re-place candidate (a pick's answer) has no scope of its own.
function scopeLabel(owner: RangeOwner | PickAnswer) {
  const scope = 'scope' in owner ? owner.scope : undefined;
  const rung = scope && levelOf(owner, scope);
  if (rung) return levelLabel(rung.label);
  if (scope === 'lines') return '';
  return translate(
    tableEntry(
      { float: '그림/표', block: '환경 블록', paragraph: '문단', none: '생성 파일', lines: '줄' },
      owner.kind,
    ) ||
      owner.kind ||
      '',
  );
}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(label: string | undefined) {
  label = String(label || '');
  if (LANG !== UI_LANG.EN) return label;
  const match = /^환경 (.+?)( \(바깥( 2)?\))?$/.exec(label);
  return match
    ? translateTemplate(match[3] ? '환경 {env} (바깥 2)' : match[2] ? '환경 {env} (바깥)' : '환경 {env}', {
        env: match[1],
      })
    : translate(label);
}
// The rung matching the owner's range, shown as pressed: with a scope, that scope's rung (when the range matches it
// too); otherwise the first rung whose lo/hi match (shown as '지금 범위' on an edit card).
function currentRung(owner: RangeOwner) {
  const rungs = owner.levels || [];
  const scopeRung = owner.scope && levelOf(owner, owner.scope);
  if (scopeRung && scopeRung.lo === owner.lo && scopeRung.hi === owner.hi) return scopeRung;
  return rungs.find((rung) => rung.lo === owner.lo && rung.hi === owner.hi) || null;
}
// Segment-control labels are kept short - '환경 abstract' -> 'abstract'. When the same environment name appears more
// than once, '(바깥)' is kept to distinguish them. The line range is left out of the label, going instead into the
// description (data-tip)/aria-label and the location line. A figure rung is named by its element as the server labelled
// it (a person's words, not run through levelLabel).
function levelName(rung: Rung, all: Rung[]) {
  if (rung.el) return String(rung.label || elementName(rung.el));
  if (!rung.env || rung.level === 'block') return levelLabel(rung.label);
  const dup = (all || []).filter((other) => other.env === rung.env).length > 1;
  return dup ? levelLabel(rung.label).replace(/^(환경|Environment) /, '') : rung.env;
}
// The range ladder's segments (composer and edit card) as Html, one radio button per rung, the rung matching the range
// checked. A figure rung (it carries an element) gets the element's tooltip; its line count comes from lo-hi when the
// rung has no n. A Markdown document's rungs have descriptions of their own (TIP_TEXT.mdraw: no drag area there, a tap
// chose the line too).
function rungButtons(owner: RangeOwner, isEdit: boolean) {
  const current = currentRung(owner),
    rungs = owner.levels || [];
  return rungs.map((rung) => {
    const on = rung === current,
      lineCount = rungLines(rung);
    const tip = rungHasElement(rung)
      ? rungTip(rung)
      : isEdit && rung.level === 'raw'
        ? TIP_TEXT.cur
        : rung.level.startsWith('env')
          ? TIP_TEXT.env
          : rung.level === 'raw' && isMarkdownDoc()
            ? TIP_TEXT.mdraw
            : // a rung may name its own description (a text document's paragraphs, textLevels)
              TIP_TEXT[('tip' in rung && typeof rung.tip === 'string' && rung.tip) || rung.level] || '';
    const label = isEdit && rung.level === 'raw' ? translate('지금 범위') : levelName(rung, rungs),
      linesText = translateTemplate('{n}줄', { n: lineCount });
    return html`<button class="${on ? 'on' : ''}" data-act="level" data-level="${rung.level}" role="radio" aria-checked="${on}" aria-label="${label + ' ' + lineRange(rung.lo, rung.hi) + ' · ' + linesText}" \
data-tip="${lineRange(rung.lo, rung.hi) + (tip ? ' · ' + translate(tip) : '')}">${label} <span class="k${lineCount > 50 ? ' wn' : ''}">· ${linesText}</span></button>`;
  });
}
// A rung's line count: the server's n, else its lo-hi span (a figure rung may come without n).
function rungLines(rung: Rung) {
  return typeof rung.n === 'number' ? rung.n : rung.hi - rung.lo + 1;
}
// Draws the owner's range ladder into box (#c-levels or an edit card's .e-levels): its segments, shown only when there
// are two or more rungs - one segment is no choice, and '문단 · 1줄' alone reads as noise; the caption then names that
// rung (rangeCap). data-rungs keeps the count for the CSS and the tests. The box is a scroll box and carries
// tabindex="-1" in its markup: Firefox makes a box that overflows a Tab stop of its own, so an overflowing ladder would
// take two stops - the box, then the chosen rung. The chosen rung shows itself as the focus or the range moves
// (revealSegment).
function drawLadder(box: HTMLElement, owner: RangeOwner, isEdit: boolean) {
  const rungCount = (owner.levels || []).length,
    at = segmentFocusAt(box);
  box.dataset.rungs = String(rungCount);
  box.hidden = rungCount < 2;
  setHtml(box, rungCount < 2 ? html`` : html`<div class="lad-t">${rungButtons(owner, isEdit)}</div>`);
  if (rungCount >= 2) revealSegment(box); // .lad-t: the drawn track inside the scroll box
  roveSegment(box);
  keepSegmentFocus(box, at);
} // one Tab stop, the rung matching the range (else the first), and the focus kept (main.ts)
// The range caption over the ladder (composer and edit card): '범위 L5-L6 · 2줄' - the lines a save will hand over and
// their count, whatever set them (a rung or the excerpt). When the ladder is hidden (one rung) and the range is that
// rung, its name follows ('범위 L5 · 1줄 · 문단'); with a ladder, its checked segment names it. An edit card's own
// lines (its 'raw' rung) get no name. A range matching no rung has none either: the lines say what it is. In an edit
// card the range copies as 'file Llo-Lhi' (the composer's location line has its copy). Writes the caption markup (Html)
// into its element only when its text changed: the caption is a polite live region (a screen reader hears the new range
// after a rung or an excerpt press, not every redraw), and its copyable range keeps its focus.
function setCap(caption: HTMLElement, markup: Html) {
  if (caption._cap !== markup.text) {
    caption._cap = markup.text;
    setHtml(caption, markup);
  }
}
// An owner without its lines has no range to name.
function rangeCap(owner: RangeOwner, isEdit: boolean) {
  if (!onLines(owner)) return html``;
  const rungs = owner.levels || [],
    current = currentRung(owner),
    range = lineRange(owner.lo, owner.hi);
  const named =
    rungs.length < 2 && current && !(isEdit && current.level === 'raw') ? ' · ' + levelName(current, rungs) : '';
  const rangeHtml = isEdit
    ? html`<span class="e-range loc" tabindex="0" data-copy="${owner.name + ' L' + owner.lo + '-L' + owner.hi}" data-tip="${translate('저장하면 핀이 가리킬 원문 줄. 누르면 복사')}">${range}</span>`
    : html`<span class="rg-v">${range}</span>`;
  return html`<b class="rg-l">${translate('범위')}</b> ${rangeHtml} · ${translateTemplate('{n}줄', { n: owner.hi - owner.lo + 1 })}${named}`;
}
const SEGMENT_FADE = 32; // how wide a scrolling segment control's edge fade is at most (composer.css)
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left
// untouched). A control that asks for the whole segment (data-reveal="whole": the assignee row, whose segments are
// names nearly as long as the row) brings it clear of the edge fades too - a fade's width in from an edge that has more
// to scroll to, or centred when it is too long for that; fadeSegmentEdges then keeps each fade off it.
function revealSegment(control: Element | null) {
  if (!(control instanceof HTMLElement)) return;
  const on = control.querySelector('.on');
  if (!(on instanceof HTMLElement)) {
    fadeSegmentEdges(control);
    return;
  }
  const left = on.offsetLeft,
    right = left + on.offsetWidth,
    width = control.clientWidth;
  if (control.dataset.reveal === 'whole')
    control.scrollLeft = wholeSegmentAt(left, right, width, control.scrollWidth, control.scrollLeft);
  else if (left < control.scrollLeft) control.scrollLeft = Math.max(0, left - 4);
  else if (right > control.scrollLeft + width) control.scrollLeft = right - width + 4;
  fadeSegmentEdges(control);
}
// Where a scroll box `width` wide over content `full` wide, now at `at`, stands to show the segment from `left` to
// `right` whole and clear of the edge fades: the nearest place that leaves SEGMENT_FADE on each side of it, or the
// segment centred when the box has no room for both; never past either end. Pure.
function wholeSegmentAt(left: number, right: number, width: number, full: number, at: number): number {
  const end = Math.max(0, full - width),
    fits = right - left + 2 * SEGMENT_FADE <= width;
  return Math.max(
    0,
    Math.min(
      end,
      fits
        ? Math.max(right - width + SEGMENT_FADE, Math.min(left - SEGMENT_FADE, at))
        : left - (width - (right - left)) / 2,
    ),
  );
}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, a
// segment cut off at the edge would give no sign that there is more. A control that shows its selected segment whole
// (data-reveal="whole") narrows each fade to the room between that segment and the edge (--fade-l, --fade-r), so the
// fade lies on what there is more of and never on the selected segment.
function fadeSegmentEdges(control: HTMLElement) {
  if (!control) return;
  const over = control.scrollWidth - control.clientWidth;
  control.classList.toggle('fade-l', over > 1 && control.scrollLeft > 1);
  control.classList.toggle('fade-r', over > 1 && over - control.scrollLeft > 1);
  const on = control.dataset.reveal === 'whole' ? control.querySelector('.on') : null;
  if (!on) return;
  const controlRect = control.getBoundingClientRect(),
    segmentRect = on.getBoundingClientRect(),
    room = (px: number) => Math.max(0, Math.min(SEGMENT_FADE, Math.floor(px))) + 'px';
  control.style.setProperty('--fade-l', room(segmentRect.left - controlRect.left));
  control.style.setProperty('--fade-r', room(controlRect.right - segmentRect.right));
}
document.addEventListener(
  'scroll',
  (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.classList.contains('seg')) fadeSegmentEdges(target);
  },
  true,
);
// ---------------- Where the chosen lines print (docs/adr/0049-pin-marks-follow-the-range.md)
// What snippets have answered about where a range owner's lines print, kept beside the owner rather than on it: the
// composer's selection is written to the tab's draft as JSON (composer/flow-draft.ts), and boxes measured against the
// build now on screen are not a draft's to keep. One answer carries the whole ladder round the range it was asked
// about, so every rung of it is held, each under its own lines: a rung moved to later is drawn from what is already
// here rather than asked about again.
//
// An answer is held under the build its pieces were measured against as well as under its lines, because its pieces
// are places on that build's pages. A build that finishes while the composer stands open and leaves the page count
// alone swaps every page image under the selection without replacing the selection itself (documents/flow-rebuild.ts
// refreshDoc takes that branch rather than building the pages again, which is the only thing that lets the composing
// box go), so an answer measured against the build before it would be drawn over the new pages for as long as the
// panel stays open. Held under the build it was measured against, it is simply not found again, which reads as
// nothing having answered about these lines yet: the box keeps the shape it has and the new build is asked
// (followRange), rather than falling back to the rectangle that was dragged while that request is out.
//
// The build an answer was measured against is the one the answer names (`boxes_build`), not the one this page
// believed when it sent the request. The server measures against the build on screen as it answers, so a build that
// finishes inside that round trip is measured against while this page still shows the one before it and its meta has
// not caught up; held under what was believed, those pieces would be found at once and drawn over pages they are not
// on. Held under the build the answer names, they are held under the build they are places on: they are found when
// the pages become that build, and until then these lines read as unanswered, which keeps the box where it stands.
// They are not asked again in the meantime - the answer in hand already says which build it is about, and that is
// enough to know the question has been put (RANGE_ELSEWHERE, just below).
const RANGE_BOXES = new WeakMap<LineOwner, Map<string, MarkPiece[]>>();
// The ranges whose answer says outright that it was measured against another build than the one whose pages are up,
// each noted under the build that was up when it said so - so a note stops applying the moment the pages move, with
// nothing to clear. Kept beside the owner like the pieces, so it goes when the selection goes.
//
// Asking such a range again cannot answer it. The server measures against the build it has when it answers, which is
// the build that answer already named; what is behind is this page's META, and a request does not move META. So the
// only thing another request produces is the same answer, and one request per redraw for as long as the poll takes to
// catch up (a build poll runs every second while a build runs, the light poll every five, and neither runs while the
// tab is hidden). followRange therefore draws nothing and sends nothing while a note applies: the box keeps its last
// good shape, and when the pages do become that build the answer already held for it is simply found.
//
// Only an answer about a build this page had not shown when it asked is noted. A range nothing has answered about is
// not in here, nor one whose held answer the pages have moved past - whether they moved after the answer came or
// while it was coming - because there it is the build now shown that has not answered, and asking is how its pieces
// arrive (answeredElsewhere, takeRangeBoxes).
const RANGE_ELSEWHERE = new WeakMap<LineOwner, Set<string>>();
// What build and lines an answer is held under. Pure.
function rangeKey(build: string, first: number, last: number) {
  return build + ' ' + first + ':' + last;
}
// The build whose pages are on screen: the one every box drawn on them is a place in. '' before the first meta answer
// has come, which no page and so no box can be drawn before - META is Meta | null (ADR-0048) and this file reads it as
// it finds it rather than through knownMeta(), which throws.
function shownBuild() {
  return (META && META.pages_build) || '';
}
// The build an owner's own rungs were measured against: the one the pick that answered them named, else the build on
// screen - the pair composer/flow-draft.ts writes a draft's build from. Lines picked on a document drawn in the
// browser name no build, and neither do they print on a page.
function answeredBuild(owner: LineOwner, shown: string) {
  const own = 'pdf_build' in owner ? owner.pdf_build : undefined;
  return own || shown;
}
// The rung whose range is exactly the owner's chosen lines and that carries where they print: a pick answers this for
// its default rung, a snippet for every rung of the ladder it builds. Once the pages on screen are another build's,
// the pick's own answer is no answer about them: it is left out, so those lines read as unanswered and are asked about
// again. The pick keeps its pdf_build - it is the build the saved pin's coordinates belong to (composer/flow-save.ts).
function boxedRung(owner: LineOwner, shown: string) {
  if (answeredBuild(owner, shown) !== shown) return undefined;
  return (owner.levels || []).find((rung) => rung.lo === owner.lo && rung.hi === owner.hi && !!rung.boxes);
}
// Where the owner's chosen lines print on the build `shown`, as far as anything has said about that build - the rung's
// own answer, else a snippet's for exactly those lines - and undefined when nothing has answered about them yet.
//
// The caller must tell those two apart, because they ask for opposite things: an answer of no pieces means these lines
// have no mark, so the box belongs back on the rectangle that was dragged, while no answer yet means the box must wait
// where it is. A piece the server could not answer well is left out rather than taking the rest of the box with it.
// What an answer put under `boxes` is read as a list only when it is one, the way pinPieces (pdf/view-figure.ts)
// reads a pin's: an answer from a server this page does not share a version with can hold anything there, and
// `.filter` on it would throw inside renderComposer and take the whole composer's render with it. Not a list reads as
// "no mark for this range", which puts the box back on the drag. What is held is screened the same way on the way in
// (takeRangeBoxes), so the second branch has a list already.
function rangeBoxes(owner: LineOwner, shown: string): MarkPiece[] | undefined {
  const rung = boxedRung(owner, shown);
  if (rung && rung.boxes) return (Array.isArray(rung.boxes) ? rung.boxes : []).filter(isPiece);
  const held = RANGE_BOXES.get(owner),
    answered = held && held.get(rangeKey(shown, owner.lo, owner.hi));
  return answered && answered.filter(isPiece);
}
// The build a snippet's pieces were measured against: the one its answer names, else the build the request was sent
// about. An answer names none when the server had no build with pages to measure against - it then carries no piece
// either - and so does one from a server older than this field; for both, the build this page showed as the request
// went out is as near as anything says, and it is what every answer was held under before the name travelled.
function measuredBuild(answer: SnippetAnswer, asked: string) {
  return (typeof answer.boxes_build === 'string' && answer.boxes_build) || asked;
}
// Records what a snippet answered, under the build its pieces were measured against (measuredBuild): first the range
// it was asked about, so lines with no mark are asked about once and a ladder that came without rungs cannot be asked
// about forever, then every rung the ladder carries under that rung's own lines. One press on the ladder therefore
// answers the rungs around it as well. `asked` is the build that was on screen when the request went out, which is
// only what an answer naming no build is held under: a build that finished in between is the one the server measured
// against, and holding its pieces under the build before it would put the places of the pages after on the pages
// before. `shown` is the build whose pages are up as the answer is taken, which with `asked` says whether this is an
// answer about a build this page has yet to show - the one kind that is not asked again (noteElsewhere).
function takeRangeBoxes(owner: LineOwner, answer: SnippetAnswer, asked: string, shown: string) {
  let held = RANGE_BOXES.get(owner);
  if (!held) RANGE_BOXES.set(owner, (held = new Map<string, MarkPiece[]>()));
  const build = measuredBuild(answer, asked);
  held.set(rangeKey(build, answer.lo, answer.hi), []);
  for (const rung of answer.levels || [])
    held.set(rangeKey(build, rung.lo, rung.hi), Array.isArray(rung.boxes) ? rung.boxes : []);
  // Noted only when the pages have not moved since the request went out (`asked` is still what is shown). Then the
  // build the answer names is one this page has never shown, so it is this page's META that is behind and asking
  // again cannot help. If the pages did move while the answer was on its way, it is this page that moved on: the
  // build it shows now is the one that has not answered, and that is asked as it always was. measuredBuild's fallback
  // is `shown` here, so an answer that named no build is no answer about another one and is never noted.
  if (asked === shown && measuredBuild(answer, shown) !== shown) noteElsewhere(owner, answer, shown);
}
// Notes every range an answer about another build covers - the range it answered and each rung of its ladder - under
// the build whose pages are up, so none of them is asked again while they are (RANGE_ELSEWHERE). The whole ladder
// goes in because one answer measured all of it against that one build, so moving to a rung beside the range would
// otherwise ask the same question again and be answered the same way.
function noteElsewhere(owner: LineOwner, answer: SnippetAnswer, shown: string) {
  let noted = RANGE_ELSEWHERE.get(owner);
  if (!noted) RANGE_ELSEWHERE.set(owner, (noted = new Set<string>()));
  noted.add(rangeKey(shown, answer.lo, answer.hi));
  for (const rung of answer.levels || []) noted.add(rangeKey(shown, rung.lo, rung.hi));
}
// Whether what this page holds about the owner's chosen lines is an answer about another build than the one whose
// pages are up, which is the one case where asking again cannot help (RANGE_ELSEWHERE). Lines nothing has answered
// about, and lines whose answer the pages have moved past, are not noted and so are asked as they always were.
function answeredElsewhere(owner: LineOwner, shown: string) {
  const noted = RANGE_ELSEWHERE.get(owner);
  return !!noted && noted.has(rangeKey(shown, owner.lo, owner.hi));
}
// A pending box follows the lines its owner has chosen, and moves only onto an answer. Lines nothing has
// answered about are asked of the snippet route - which answers every rung of the ladder round them at once - and the
// box is left as it stands until that comes: putting it back on the dragged rectangle for the length of a request
// would show the person the span they dragged as the pin's range, which is the one thing this is here to stop. A
// document whose marks come from its element map (a figure's) is left to renderElement, which puts the box on that
// element, and a document drawn in the browser has no page to draw a box on.
//
// Lines whose answer names another build are the one kind that is not asked: the box stays where it is and nothing is
// sent until the pages move, because a request cannot bring this page's meta forward and would be answered exactly as
// before (RANGE_ELSEWHERE). This draw happens on every redraw of the panel, so without that the panel would send a
// request on each of them for as long as the meta took to catch up.
function followRange(selection: ComposerSelection, box: HTMLElement | null, after: () => void) {
  if (!box || isFigureKind(META ? META.kind : undefined) || !onLines(selection)) return;
  const shown = shownBuild(),
    pieces = rangeBoxes(selection, shown);
  if (!pieces) {
    if (!answeredElsewhere(selection, shown)) refetchSnip(selection, after);
    return;
  }
  snapSelectionBox(box, pieces, draggedPlace(selection), rangeRole(selection) === 'repick' ? 'repick' : 'compose');
}
// Where the drag that began the selection was made - its page and its rectangle as it was sent - which a range with no
// pieces puts the box back on; null when the answer carries neither.
function draggedPlace(selection: ComposerSelection) {
  return typeof selection.page === 'number' && isFrac(selection.frac)
    ? { page: selection.page, frac: selection.frac }
    : null;
}
// The wait a range's text refresh is held for, one per role. They are separate timers because a box waits on its own
// answer (followRange) while two of these are open together, and a request another one's wait cancelled would leave
// that box on the range it last showed with nothing to say so.
const SNIPPET_TIMERS = new Map<RangeRole, ReturnType<typeof setTimeout>>();
// Refreshes the text of a range set in the excerpt only while the owner still holds its role (stillOwns). An owner
// whose box follows the range - the composing selection, a re-place's candidate - also asks for the ladder round those
// lines and for where each of its rungs prints (?levels=1&boxes=1). An edit card asks for neither: its box is the
// saved pin's mark, which the pin list answers, and its ladder reads the rungs' lines alone. Marks are asked for and
// not implied because the server runs a process per line of every rung to answer them - about half a second for a
// ladder round a pin inside a 40-line float (docs/adr/0049-pin-marks-follow-the-range.md D4).
function refetchSnip(owner: LineOwner, after: () => void) {
  const visit = captureVisit(),
    role = rangeRole(owner),
    composing = role !== 'edit';
  clearTimeout(SNIPPET_TIMERS.get(role));
  const wait = setTimeout(async () => {
    const asked = shownBuild(); // the build the pages show as this goes out, which an answer naming none is held under
    try {
      const { data } = await api('GET /api/snippet', {
        query: withDocQuery(
          '?file=' +
            encodeURIComponent(owner.file) +
            '&lo=' +
            owner.lo +
            '&hi=' +
            owner.hi +
            (composing ? '&levels=1&boxes=1' : ''),
          owner.doc,
        ),
        what: '원문 읽기',
      });
      if (stillOwns(owner, role, visit) && data.lo === owner.lo && data.hi === owner.hi) {
        owner.snippet = data.snippet;
        if (composing) takeRangeBoxes(owner, data, asked, shownBuild());
        after();
      }
    } catch (error) {}
  }, 250);
  SNIPPET_TIMERS.set(role, wait);
}
function snipText(text: string | undefined, open: boolean) {
  const rungs = String(text || '').split('\n');
  return open || rungs.length <= 8
    ? rungs.join('\n')
    : rungs.slice(0, 8).join('\n') + '\n      … ' + translateTemplate('{n}줄 접힘', { n: rungs.length - 8 });
}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that,
// '위치 불확실'; below 30%, the warning color. The description is whole sentences in this order: how the place was
// found (coordinates, text, the figure map, or a method this page does not know, named as it came), how much of the
// drag it matches (the line paths: the dragged words in these lines, rarer words weighing more; the map: the dragged
// area inside the chosen element), that it may be far off (only below 30%), and what to check. Shared by the composer
// panel and cards. No score is no measure, so no badge: there was nothing to weigh (a picture, or words too common to
// name a place). A SyncTeX pin with a score of 0 and no quote is read as one with no score. A map pick also hides -
// below 90% - when the pick answer says nothing is in doubt (mapSure): the element's share of the drag is at least
// VIA_SURE_SCORE, the drag covers at least VIA_SURE_FILL of the element (`fill`, the element side: a drag with a margin
// all round a small element, which never reaches 90% of the drag), and no other element competes for the drag (`rival`
// false: not an ancestor or descendant, a candidate within 0.1 of the score or one the drag holds nearly whole -
// docs/handbook/domain.md §그림 문서의 요소 pick). A pick is not taken for sure on its share alone: a drag round a
// small element can leave it out of the candidates and choose the big box behind it with a large share of the drag,
// while the drag covers little of that box. The two limits are the lowest that hide no wrong pick over a figure set's
// real map and held-out drags. A pin without fill and rival keeps 90%.
const VIA_HIDE = 90,
  VIA_WARN = 30,
  VIA_SURE_SCORE = 75,
  VIA_SURE_FILL = 95;
/** Whether a map pick that is under VIA_HIDE is surely the element the drag meant (see above). */
function mapSure(pick: ComposerSelection | Pin, percent: number) {
  return (
    pick.via === VIA.MAP &&
    pick.rival === false &&
    typeof pick.fill === 'number' &&
    percent >= VIA_SURE_SCORE &&
    Math.round(pick.fill * 100) >= VIA_SURE_FILL
  );
}
function viaTag(pick: ComposerSelection | Pin) {
  if (!pick.via || pick.score == null || (pick.via === VIA.SYNCTEX && !pick.score && !pick.quote)) return null;
  const percent = Math.round((+pick.score || 0) * 100);
  if (percent >= VIA_HIDE || mapSure(pick, percent)) return null;
  const low = percent < VIA_WARN;
  const lines = pick.via === VIA.SYNCTEX || pick.via === VIA.TEXT,
    map = pick.via === VIA.MAP;
  const how =
    pick.via === VIA.SYNCTEX
      ? translate(TIP_TEXT.synctex)
      : pick.via === VIA.TEXT
        ? translate(TIP_TEXT.text)
        : map
          ? translate(TIP_TEXT.map)
          : translateTemplate('이 화면이 모르는 방법({via})으로 찾은 위치입니다.', { via: pick.via });
  const match = lines
    ? translateTemplate('드래그한 글자 중 {pct}%가 이 줄들에 있습니다(드문 낱말일수록 크게 셉니다).', { pct: percent })
    : map
      ? translateTemplate('드래그한 영역 중 {pct}%가 이 요소 안에 있습니다.', { pct: percent })
      : translateTemplate('드래그와 맞는 정도는 {pct}%입니다.', { pct: percent });
  const check = lines
    ? translate('원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.')
    : map
      ? translate('고른 상자가 고칠 곳을 덮는지 확인하세요.')
      : translate('고칠 곳이 이 범위에 들어 있는지 확인하세요.');
  return {
    t: translate('위치 불확실'),
    tip: [how, match, ...(low ? [translate('위치가 많이 어긋났을 수 있습니다.')] : []), check].join(' '),
    low,
  };
}
export type { LineOwner, RangeOwner };
export {
  drawLadder,
  followRange,
  kindFor,
  levelLabel,
  onLines,
  rangeCap,
  refetchSnip,
  scopeLabel,
  revealSegment,
  setCap,
  snipText,
  viaTag,
  wireScope,
};
