// ------------------------------------------------ The outline: reading it, the section strip, picks and the filter
import { BAND, DOC, META, REDUCED_MOTION_QUERY, imeKey, isFigureKind, scrollMotion } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { drawPos, refitFilteredSheet } from '../documents/flow-switch.ts';
import { VECTOR_PDF } from './flow-open.ts';
import type { PdfDestination, PdfDocument, PdfOutlineItem } from './flow-open.ts';
import { refreshPageLists } from './view-page-list.ts';
import { $ } from '../platform/dom.ts';
import { LAYOUT_BAND } from '../app/rules-tables.ts';
import { isMarkdownDoc, docInfo, withDocQuery } from '../documents/state.ts';
import { topAnchor } from '../layout/flow.ts';
import { arrivalWatch, glideTo } from '../layout/flow-scroll.ts';
import { pageChanges, pageMarkdown } from './state-seams.ts';
import { goPage, jumpOnItsWay, OUTLINE_PICK_GAP, spotTop, readingDepth } from './view-page-jump.ts';

// One row of the outline: a PDF outline item (loadOutline, its number and page label from mergeOutlineLabels) or a
// Markdown heading (markdown/view.ts drawOutline). up is the index of the entry it sits under (-1 at the top).
type OutlineEntry = {
  title: string;
  page: number;
  depth: number;
  up: number;
  frac: number;
  x?: number | null;
  number?: string;
  pageLabel?: string;
};
// One label of GET /api/outline-labels: the LaTeX number, title, printed page, sectioning level and anchor of a heading.
type OutlineLabel = {
  number: string;
  title: string;
  page: string;
  level: string;
  anchor: string;
};
// How much of a PDF's outline the viewer reads (docs/handbook/viewer.md §모바일 레이아웃): the first
// OUTLINE_MAX_ENTRIES entries in outline order, down to level OUTLINE_MAX_DEPTH (0 is the top level, so five levels).
// What is left unread is counted (OUTLINE_CUT) and said at the end of the outline and of its filter's results
// (outlineCutNote) - never dropped without a word.
const OUTLINE_MAX_ENTRIES = 2000,
  OUTLINE_MAX_DEPTH = 4;
// Sibling entries whose destinations are resolved at once (each is a round trip to the PDF.js worker).
const OUTLINE_BATCH = 100;
// How many entries that name a place (a destination) lie in item and below it. Counts without resolving anything, and
// with a stack of its own: an outline can nest deeper than the call stack.
function outlineCount(item: PdfOutlineItem) {
  let count = 0;
  const todo = [item];
  for (let node = todo.pop(); node; node = todo.pop()) {
    if (node.dest != null) count++;
    for (const child of node.items || []) todo.push(child);
  }
  return count;
}
// Which document and build the entries in OUTLINE_ENTRIES were read for (outlineForget drops them when another document
// comes on screen; the page list names a figure's pages by them only while they are those of the build on screen,
// outlineOnScreen).
let OUTLINE_DOC: string | null = null,
  OUTLINE_BUILD = '';
// Reads the outline of the PDF document opened as generation gen (VECTOR_PDF.gen) into OUTLINE_ENTRIES, with the
// numbers and printed page labels the server reads for the build (mergeOutlineLabels), and draws it. A newer open drops
// it.
async function loadOutline(doc: PdfDocument, gen: number) {
  const docName = DOC,
    build = (META && META.pages_build) || '',
    // a newer open (another document or build) took over
    stale = () => gen !== VECTOR_PDF.gen || doc !== VECTOR_PDF.doc;
  let entries: OutlineEntry[] = [],
    cut = 0;
  try {
    const items = await doc.getOutline();
    // One outline item as an entry (without its depth), or null when it names no page of this PDF - or when its
    // destination cannot be resolved: one broken link leaves out that entry only, not the outline.
    async function entryOf(item: PdfOutlineItem) {
      try {
        let destination = item.dest;
        if (typeof destination === 'string') destination = await doc.getDestination(destination);
        if (!Array.isArray(destination) || destination[0] == null) return null;
        const page =
          typeof destination[0] === 'number' ? destination[0] + 1 : (await doc.getPageIndex(destination[0])) + 1;
        const pageHeight = META && META.pages && META.pages[page - 1] ? +META.pages[page - 1].pt_h : 0;
        if (!(Number.isInteger(page) && page >= 1 && page <= doc.numPages)) return null;
        return {
          title: item.title || translate('제목 없음'),
          page,
          depth: 0,
          up: -1,
          frac: destinationFraction(destination, pageHeight),
          x: destinationLeft(destination),
        };
      } catch (error) {
        return null;
      }
    }
    // up: the index in entries of the nearest entry above these rows (-1 at the top, or when every row above has no
    // entry of its own).
    async function walk(rows: PdfOutlineItem[], depth: number, up: number) {
      for (let i = 0; i < rows.length; i += OUTLINE_BATCH) {
        // Between batches: a document left behind does not go on asking the worker.
        if (stale()) return;
        if (entries.length >= OUTLINE_MAX_ENTRIES) {
          for (let j = i; j < rows.length; j++) cut += outlineCount(rows[j]);
          return;
        }
        const batch = rows.slice(i, i + OUTLINE_BATCH),
          got = await Promise.all(batch.map(entryOf));
        if (stale()) return;
        for (let j = 0; j < batch.length; j++) {
          if (entries.length >= OUTLINE_MAX_ENTRIES) {
            cut += outlineCount(batch[j]);
            continue;
          }
          const at = entries.length,
            entry = got[j];
          if (entry) entries.push(Object.assign(entry, { depth, up }));
          if (depth < OUTLINE_MAX_DEPTH) {
            await walk(batch[j].items, depth + 1, entry ? at : up);
            if (stale()) return;
          } else for (const child of batch[j].items || []) cut += outlineCount(child);
        }
      }
    }
    await walk(items || [], 0, -1);
  } catch (error) {
    entries = [];
    cut = 0;
  }
  if (stale()) return;
  // The PDF's own outline is still usable when the numbering service cannot be reached.
  if (entries.length) {
    try {
      const answer = (await api(withDocQuery('/api/outline-labels', docName), { what: '목차 번호 읽기', silent: true }))
        .data;
      if (!stale() && docName === DOC && build === META.pages_build && answer.build === build)
        entries = mergeOutlineLabels(entries, answer.labels || []);
    } catch (error) {}
  }
  if (stale()) return;
  OUTLINE_ENTRIES = entries;
  OUTLINE_CUT = cut;
  OUTLINE_DOC = docName;
  OUTLINE_BUILD = build;
  OUTLINE_SELECTED = -1;
  OUTLINE_ACTIVE_PAGE = 0;
  OUTLINE_PINNED = null;
  renderOutline();
  updateSectionStrip();
  // A page list opened while this was read names its pages now.
  refreshPageLists();
}
// Drops the outline of the document that was on screen before, when another one comes on screen (openVectorDocument):
// the page list and the section strip would otherwise name its pages by the old document's headings until the new
// outline is read. The same document's new build keeps the old build's entries until its own are read - a rebuilt
// manuscript's strip does not blank meanwhile.
function outlineForget() {
  if (OUTLINE_DOC === DOC) return;
  OUTLINE_ENTRIES = [];
  OUTLINE_CUT = 0;
  OUTLINE_DOC = DOC;
  OUTLINE_BUILD = '';
  OUTLINE_SELECTED = -1;
  OUTLINE_ACTIVE_PAGE = 0;
  OUTLINE_PINNED = null;
  OUTLINE_MARKED = -1;
  OUTLINE_SNAP = true;
  OUTLINE_AIM = null;
  // The sheet's outline rows are the old document's.
  $('#ns-outline').hidden = true;
}
// Whether OUTLINE_ENTRIES were read for the build on screen.
function outlineOnScreen() {
  return OUTLINE_DOC === DOC && OUTLINE_BUILD === ((META && META.pages_build) || '');
}
// The entries with their LaTeX numbers and printed page labels (/api/outline-labels): each entry takes the first label,
// after the last one matched, with the same normalised title - on the entry's page where the label names a numeric
// page, and, once a top-level section's title matches, of the sectioning level the entry's depth is.
function mergeOutlineLabels(entries: OutlineEntry[], labels: OutlineLabel[]) {
  const normalize = (text: string) =>
    String(text || '')
      .normalize('NFKC')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  const levels = ['section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph'];
  const depthGuard = labels.some(
    (label) =>
      label.level === 'section' &&
      entries.some((entry) => entry.depth === 0 && normalize(entry.title) === normalize(label.title)),
  );
  let cursor = 0;
  return entries.map((entry) => {
    const title = normalize(entry.title);
    let matched = null as any;
    if (title)
      for (let i = cursor; i < labels.length; i++) {
        const label = labels[i];
        if (normalize(label.title) !== title) continue;
        if (/^\d+$/.test(String(label.page || '')) && Number(label.page) !== entry.page) continue;
        if (depthGuard && levels.includes(label.level) && levels.indexOf(label.level) !== entry.depth) continue;
        matched = label;
        cursor = i + 1;
        break;
      }
    return Object.assign({}, entry, {
      number: matched ? String(matched.number || '') : '',
      pageLabel: matched ? String(matched.page || '') : '',
    });
  });
}
// OUTLINE_CUT: entries the PDF has that were not read.
let OUTLINE_ENTRIES: OutlineEntry[] = [],
  OUTLINE_CUT = 0,
  OUTLINE_SELECTED = -1,
  OUTLINE_ACTIVE_PAGE = 0;
// Draws the outline into both of its lists - the outline panel and the phone's navigation sheet - each filtered by its
// own search field; the sheet leaves its outline section out when the PDF has no outline.
function renderOutline() {
  outlineList($('#outline-items'), $('#outline-search').value);
  outlineList($('#ns-outline-items'), $('#ns-outline-search').value);
  $('#ns-outline').hidden = !(OUTLINE_ENTRIES.length || OUTLINE_CUT);
}
/** Draws one filtered outline with bare printed-page labels and the current section marked, and - when the PDF has more
 * entries than were read (OUTLINE_CUT) - the note on the unread ones as its last line, under a filter's results too
 * (outlineCutNote). Under a filter an entry whose name another entry has under another group says its group first
 * (outlineGrouped), on a line of its own above the row, small, muted and cut to one line: the results are a flat list,
 * and `채택 › PL64` and `본문 그림 › PL64` are two places, and a long group name must not push the names down.
 * Entries keep manuscript wording unchanged; empty-state sentences remain translatable UI text.
 * A row's name is its number and title: the dot that stands in for no number is not read. A Markdown document's line
 * label (L7) is not read either - its row is described as the source line instead ('원문 7번째 줄').
 */
function outlineList(box: HTMLElement, filterText: string) {
  const query = String(filterText || '')
    .trim()
    .toLowerCase();
  if (!OUTLINE_ENTRIES.length) {
    // All of what it has was left unread (destinationless ancestors, entries below the depth limit): say that.
    box.className = 'outline-empty';
    const note = outlineCutNote(false);
    if (note) setHtml(box, note);
    else
      box.textContent = isMarkdownDoc()
        ? '이 문서에는 이동할 수 있는 제목이 없습니다.'
        : '이 PDF에는 이동할 수 있는 목차가 없습니다.';
    return;
  }
  const rows: number[] = [];
  OUTLINE_ENTRIES.forEach((entry, index) => {
    if (!query || (entry.number + ' ' + entry.title).toLowerCase().includes(query)) rows.push(index);
  });
  const note = outlineCutNote(!!query);
  if (!rows.length) {
    box.className = 'outline-empty';
    if (note) setHtml(box, html`${translate('찾은 장·절이 없습니다.')}${note}`);
    else box.textContent = '찾은 장·절이 없습니다.';
    return;
  }
  box.className = '';
  const grouped = query ? outlineGrouped(OUTLINE_ENTRIES) : null;
  setHtml(
    box,
    html`${rows.map((index) => {
      const entry = OUTLINE_ENTRIES[index],
        on = index === OUTLINE_SELECTED;
      const page = entry.pageLabel || String(entry.page),
        groupName = grouped && grouped.has(index) ? outlineGroupName(OUTLINE_ENTRIES[entry.up]) : '';
      const isMarkdown = isMarkdownDoc(),
        line = isMarkdown
          ? translateTemplate('원문 {line}번째 줄', { line: String(entry.pageLabel || '').replace(/^L/, '') })
          : null;
      return html`<button translate="no" class="ol-depth-${Math.min(entry.depth, 4)}${on ? ' ol-active' : ''}${groupName ? ' ol-grouped' : ''}" data-act="outline-page" data-index="${index}" data-page="${entry.page}" data-close="1" aria-current="${on ? 'location' : 'false'}" title="${groupName ? groupName + ' › ' + entry.title : entry.title}"${isMarkdown ? html` aria-description="${line}"` : ''}>${groupName ? html`<span class="ol-grp">${groupName} ›</span>` : ''}<span class="ol-no"${entry.number ? '' : html` aria-hidden="true"`}>${entry.number || '·'}</span><span class="ol-name">${entry.title}</span><span class="ol-page"${isMarkdown ? html` aria-hidden="true"` : ''}>${page}</span></button>`;
    })}${note}`,
  );
}
// The name of an outline entry as a group: its number and title.
function outlineGroupName(entry: OutlineEntry) {
  return entry ? (entry.number ? entry.number + ' ' : '') + entry.title : '';
}
// The indices of the entries that a filter's flat results must say the group of: those under a group (up >= 0) whose
// number and title another entry has too under another group - a figure listed under its status and under the
// manuscript figure that holds it. Entries that differ in number or title tell themselves apart, and a title said twice
// under one group, or at the top, has no group to say. Over all the entries, not the rows found, so a row reads the
// same whatever is typed. Memoised on the entries.
let OUTLINE_GROUPED: { for: object[] | null; set: Set<number> } = { for: null, set: new Set() };
function outlineGrouped(entries: OutlineEntry[]) {
  if (OUTLINE_GROUPED.for === entries) return OUTLINE_GROUPED.set;
  const normalize = (text: string) =>
    String(text || '')
      .normalize('NFKC')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase(); // as mergeOutlineLabels reads a title
  const under = new Map(),
    several = new Set(),
    set: Set<number> = new Set();
  entries.forEach((entry) => {
    const key = normalize((entry.number || '') + ' ' + entry.title),
      up = typeof entry.up === 'number' ? entry.up : -1;
    if (!under.has(key)) under.set(key, up);
    else if (under.get(key) !== up) several.add(key);
  });
  entries.forEach((entry, index) => {
    if (
      typeof entry.up === 'number' &&
      entry.up >= 0 &&
      several.has(normalize((entry.number || '') + ' ' + entry.title))
    )
      set.add(index);
  });
  OUTLINE_GROUPED = { for: entries, set };
  return set;
}
// The outline's last line when the PDF has entries that were not read (OUTLINE_CUT): how many, and what the viewer
// reads at most. Under a filter it says the unread entries were not searched (it does not say they are not there).
// Quiet text, not a row: it names no place. Html, or '' with no cut.
function outlineCutNote(filtered: boolean) {
  if (!OUTLINE_CUT) return '';
  const values = {
    n: OUTLINE_CUT.toLocaleString('en-US'),
    max: OUTLINE_MAX_ENTRIES.toLocaleString('en-US'),
    depth: OUTLINE_MAX_DEPTH + 1,
  };
  return html`<p class="ol-more" role="note">${
    filtered
      ? translateTemplate(
          '생략한 목차 항목 {n}개는 검색하지 않았습니다 — 읽는 한도는 {max}개, {depth}단계입니다',
          values,
        )
      : translateTemplate('목차 항목 {n}개를 생략했습니다 — 읽는 한도는 {max}개, {depth}단계입니다', values)
  }</p>`;
}
// Moves the current-section mark to OUTLINE_SELECTED in both lists without drawing them again. The section strip
// follows the reading line, so scrolling through a long document changes the section at every page, and redrawing
// thousands of rows each time is what a long outline cannot afford. A row is found by its data-index; one the filter
// hides has no row to mark. The panel follows the mark when it moves to another entry (outlineFollow) - not at every
// page of one entry, and not when a new build's list comes with the same entry current: then nothing has moved, and a
// list the person left somewhere stays there.
function markOutline() {
  for (const box of [$('#outline-items'), $('#ns-outline-items')]) {
    for (const button of box.querySelectorAll('.ol-active')) {
      button.classList.remove('ol-active');
      button.setAttribute('aria-current', 'false');
    }
    const on = OUTLINE_SELECTED >= 0 ? box.querySelector('[data-index="' + OUTLINE_SELECTED + '"]') : null;
    if (on) {
      on.classList.add('ol-active');
      on.setAttribute('aria-current', 'location');
    }
  }
  if (OUTLINE_SELECTED !== OUTLINE_MARKED) {
    OUTLINE_MARKED = OUTLINE_SELECTED;
    outlineFollow();
  }
}
// The outline panel keeps the current section in view (docs/handbook/viewer.md §모바일 레이아웃, 목차가 지금 절을
// 따라간다). The panel (#outline: the wide layout's panel, the overlay of mid and the tablet sheet) is its own scroller
// and a figure document's list is many times taller than it, so the mark alone would move out of sight. Only #outline
// scrolls - Element.scrollIntoView moves every scrolling ancestor too, the pages among them - and the focus stays where
// it is. A row clear of the margin moves nothing. The phone has no panel: its sheet is modal, so nothing moves under
// it, and it brings its own row up as it opens (revealSheetOutline).
// The list stays put this long after the person's own wheel, press, key or scroll in it.
const OUTLINE_FOLLOW_HOLD_MS = 3000;
// Px of the list kept between the current row and the panel's edges, at the least.
const OUTLINE_FOLLOW_MARGIN = 48;
// Whole rows kept over the current row on the way up - and over its section's head where that fits.
const OUTLINE_FOLLOW_ROWS_UP = 2;
// How long a smooth follow can still be under way: a next one reckons from where it is heading.
const OUTLINE_FOLLOW_FLIGHT_MS = 600;
// OUTLINE_MARKED: the entry last marked. OUTLINE_SNAP: the next follow jumps (a new document's list), it does not
// glide. OUTLINE_FOLLOW_DUE, OUTLINE_FOLLOW_TIMER: a follow the person held back (or a list the filter drew again) is
// owed when they let go. OUTLINE_OVER: the mouse is over the panel; OUTLINE_HANDLED: when they last handled it;
// OUTLINE_SHOWN: the panel is on screen. OUTLINE_AIM: where a smooth follow is heading, and since when.
let OUTLINE_MARKED = -1,
  OUTLINE_SNAP = true,
  OUTLINE_FOLLOW_DUE = false,
  OUTLINE_FOLLOW_TIMER = 0,
  OUTLINE_OVER = false,
  OUTLINE_HANDLED = -Infinity,
  OUTLINE_SHOWN = false,
  OUTLINE_AIM: { top: number; at: number } | null = null;
// Where the list (scrollTop, view height viewHeight, content height contentHeight) scrolls to bring a row at [top,
// bottom] of its content into view: null when the row stands margin px clear of both edges - else the nearest place
// where it does (less on a view too short for that, and a row taller than the view by its top). The view's top edge is
// cover px down: the filter's band stays there, so a row is only in view below it. The margin holds from the moment a
// row enters it: following only once a row has left the view would bring it in with the margin, let the next rows use
// it up and then move the list by all of it at once. Coming up, the list goes further than the margin: to what starts
// at near (the rows just above the row) where that fits with the row and the margin under it - the margin alone would
// leave the row a row and a half under the band, and from a section's second entry on its head out of sight - and to
// group (the row's section head and the rows above that) where that fits too, so the head shows and the rows up to it
// then move nothing. Only the landing changes: whether the list moves at all is the margin's alone, so two rows next to
// each other cannot send a short panel back and forth. Going up, the very top where only part of the panel's head would
// be left over the row (head: where the rows start), as long as the row keeps the margin over the view's foot there:
// from the section's head the very top lies lower, and on the tablet sheet it would take the row under the folded
// sheet's bar. Within what the list can scroll, so the list's two ends are as near as a row gets. Pure.
function outlineRevealTop(
  scrollTop: number,
  viewHeight: number,
  contentHeight: number,
  top: number,
  bottom: number,
  margin: number,
  head: number,
  cover = 0,
  near = top,
  group = top,
) {
  const room = Math.max(0, Math.min(margin, (viewHeight - cover - (bottom - top)) / 2)),
    edge = scrollTop + cover;
  if (top >= edge + room - 0.5 && bottom <= scrollTop + viewHeight - room + 0.5) return null;
  const fits = (landing: number) => landing < top - room && bottom + room - landing <= viewHeight - cover;
  const up = top < edge + room || bottom - top > viewHeight - cover,
    want = up
      ? Math.min(top - room, fits(near) ? near : top, fits(group) ? group : top) - cover
      : bottom - viewHeight + room;
  const to = Math.round(
    Math.max(
      0,
      Math.min(contentHeight - viewHeight, up && want <= head && bottom + room <= viewHeight + 0.5 ? 0 : want),
    ),
  );
  return to === Math.round(scrollTop) ? null : to;
}
// Whether the filter is narrowing the list: its rows are the results, not the outline, and the current row is likely
// not among them.
function outlineFiltered() {
  return !!$('#outline-search').value.trim();
}
// Whether the person has the list in hand, so it stays where they put it: the filter has text, the mouse is over the
// panel, its width grip is being dragged, they wheeled, pressed, touched, scrolled or typed in it in the last
// OUTLINE_FOLLOW_HOLD_MS, or the keyboard is on a row. Neither a focus left in an empty filter holds anything - a tap
// on the pages does not take it away, so the outline would wait for good - nor a row a mouse pressed, which keeps the
// focus after its pick: reading on must not leave the outline behind.
function outlineHeld() {
  const focused = document.activeElement as HTMLElement | null;
  const onRow = !!focused && !!focused.closest && !!focused.closest('#outline-items');
  return (
    outlineFiltered() ||
    OUTLINE_OVER ||
    $('#outline-grip').classList.contains('on') ||
    performance.now() - OUTLINE_HANDLED < OUTLINE_FOLLOW_HOLD_MS ||
    (onRow && document.documentElement.dataset.input === 'key')
  );
}
/** Brings the current row into the panel's view (outlineRevealTop), gliding unless the reader asked for reduced motion,
 * the list is new or the way is longer than the panel is high - an outline out of page order sends a row a thousand px
 * off, and rows racing past read as noise. One read of the row's place, at a move of the mark. A glide reckons from
 * where a glide under way is heading (OUTLINE_AIM); a jump lands at once, so it reckons from where the list is. Held
 * back (outlineHeld), it is owed until they let go. A panel closed or absent has nothing to show: it starts at the
 * current row when it opens.
 * @param [open] the panel has just come on screen: nobody has the list in hand yet, whatever the pointer rests on */
function outlineFollow(open?: boolean) {
  if (document.body.classList.contains('outline-collapsed') || BAND === LAYOUT_BAND.PHONE) return;
  if (open ? outlineFiltered() : outlineHeld()) {
    OUTLINE_FOLLOW_DUE = true;
    outlineFollowLater();
    return;
  }
  const list = $('#outline-items'),
    row = list.querySelector('.ol-active');
  if (!row) return;
  const jump = !!open || OUTLINE_SNAP || REDUCED_MOTION_QUERY.matches;
  OUTLINE_FOLLOW_DUE = false;
  OUTLINE_SNAP = false;
  const box = $('#outline'),
    panelRect = box.getBoundingClientRect(),
    rowRect = row.getBoundingClientRect(),
    now = performance.now(),
    scrollTop = box.scrollTop;
  const from = panelRect.top + box.clientTop - scrollTop,
    at = !jump && OUTLINE_AIM && now - OUTLINE_AIM.at < OUTLINE_FOLLOW_FLIGHT_MS ? OUTLINE_AIM.top : scrollTop;
  // Where the rows OUTLINE_FOLLOW_ROWS_UP above a row start (the first row's top when there are fewer), and the section
  // head of the current row (its entry's up): read in the same pass as the row, so no further layout.
  const over = (start: Element) => {
    for (let k = 0; k < OUTLINE_FOLLOW_ROWS_UP && start.previousElementSibling; k++)
      start = start.previousElementSibling;
    return start.getBoundingClientRect().top - from;
  };
  const entry = OUTLINE_ENTRIES[Number((row as HTMLElement).dataset.index)],
    sectionHead = entry && entry.up >= 0 ? list.querySelector('[data-index="' + entry.up + '"]') : null;
  // The tablet sheet's bar and the status line on it stand over the overlay's foot (frame.css: the overlay runs to the
  // screen's bottom): what they cover is out of view, so the view is that much shorter and so is what the list can
  // scroll to bring a row up.
  const foot = outlineFoot(panelRect),
    viewHeight = box.clientHeight,
    to = outlineRevealTop(
      at,
      viewHeight - foot,
      box.scrollHeight - foot,
      rowRect.top - from,
      rowRect.bottom - from,
      OUTLINE_FOLLOW_MARGIN,
      list.getBoundingClientRect().top - from,
      $('#outline-find').offsetHeight,
      over(row),
      sectionHead ? over(sectionHead) : undefined,
    );
  if (to === null) return;
  const land = jump || Math.abs(to - scrollTop) > viewHeight;
  OUTLINE_AIM = land ? null : { top: to, at: now };
  box.scrollTo({ top: to, behavior: land ? 'auto' : scrollMotion() });
}
// How many px at the foot of the panel (its box) the bottom chrome covers: the collapsed sheet (#right) and the status
// line over it (#status-dock) where they are drawn across the panel. Only the tablet sheet's overlay has them there,
// and only it pads its foot to match (responsive.css). Elsewhere it is 0: a collapsed #right in mid or short is a
// transparent frame whose floating banner can reach across the panel without covering what lies below it, and nothing
// there pads the list for it.
function outlineFoot(panelRect: DOMRect) {
  if (BAND !== LAYOUT_BAND.TABLET_SHEET) return 0;
  let foot = 0;
  for (const element of [$('#right'), $('#status-dock')]) {
    if (!element || !element.getClientRects().length) continue;
    const rect = element.getBoundingClientRect();
    if (
      rect.height > 0 &&
      rect.left < panelRect.right &&
      rect.right > panelRect.left &&
      rect.top < panelRect.bottom &&
      rect.bottom > panelRect.top
    )
      foot = Math.max(foot, panelRect.bottom - rect.top);
  }
  return foot;
}
// When a timed hold is over: the owed follow is made then. A hover, a keyboard's focus and a grip's drag end with an
// event of their own.
function outlineFollowLater() {
  clearTimeout(OUTLINE_FOLLOW_TIMER);
  const left = OUTLINE_HANDLED + OUTLINE_FOLLOW_HOLD_MS - performance.now();
  if (left > 0) OUTLINE_FOLLOW_TIMER = setTimeout(outlineCatchUp, left + 16);
}
// Makes the follow that is owed, if any.
function outlineCatchUp() {
  if (OUTLINE_FOLLOW_DUE) outlineFollow();
}
// Where a PDF outline destination sits on its page, as a fraction from the top (0 = top). An XYZ destination carries
// the top edge in PDF points from the bottom; anything else (Fit, no top) counts as the top of the page.
function destinationFraction(destination: PdfDestination, pageHeight: number) {
  const top = Array.isArray(destination) && destination[1] && destination[1].name === 'XYZ' ? destination[3] : null;
  if (typeof top !== 'number' || !(pageHeight > 0)) return 0;
  return Math.min(1, Math.max(0, 1 - top / pageHeight));
}
// The left edge of an XYZ destination in PDF points, or null (Fit, no left): two headings at the same height in a
// page's two columns are two spots, not one.
function destinationLeft(destination: PdfDestination) {
  const left = Array.isArray(destination) && destination[1] && destination[1].name === 'XYZ' ? destination[2] : null;
  return typeof left === 'number' ? left : null;
}
// The outline entry the reader is in at (page, frac), from the entries that start at or above that point. The
// outline's order need not be the pages' order - a figure set's outline grouped by status lists page 3 before page 1 -
// so the page decides first: the latest page any of them starts on, which is this page when a heading on it starts
// above the reading line, else the nearest earlier page with an entry. On that page the outline's order is the reading
// order (a two-column page lists its left column's headings first), so the last of them wins; entries that start at
// the same spot - the same height and the same left edge (destinationLeft), as a group heading and its first figure at
// a page's top - have no reading order between them, so of those only the deepest counts, and of equally deep ones the
// first the outline lists. An outline in page order thus gets the last heading that starts at or above the point.
// Before the first heading (a title page, the top of page 1) it is the first entry on the earliest page - never a later
// heading on the same page: at the very top of page 1 it is "1", not "1.2", though 1, 1.1 and 1.2 all start on page 1.
// -1 without entries. Pure.
function outlineIndexAt(entries: OutlineEntry[], page: number, frac: number) {
  const at = (entry: OutlineEntry) => entry.frac || 0,
    deep = (entry: OutlineEntry) => entry.depth || 0,
    above = (entry: OutlineEntry) => entry.page < page || (entry.page === page && at(entry) <= frac + 1e-6);
  // edgeAt reads the left edge of an entry known to have one (those in byLeftEdge) as a number.
  const leftEdge = (entry: OutlineEntry) => (typeof entry.x === 'number' ? entry.x : null),
    edgeAt = (entry: OutlineEntry) => (typeof entry.x === 'number' ? entry.x : NaN),
    sameLeftEdge = (first: OutlineEntry, second: OutlineEntry) => {
      const firstEdge = leftEdge(first),
        secondEdge = leftEdge(second);
      return firstEdge === null || secondEdge === null
        ? firstEdge === secondEdge
        : Math.abs(firstEdge - secondEdge) <= 1e-3;
    };
  let top = 0;
  for (const entry of entries) if (above(entry) && entry.page > top) top = entry.page;
  if (!top) {
    let first = -1;
    entries.forEach((entry, index) => {
      if (first < 0 || entry.page < entries[first].page) first = index;
    });
    return first;
  }
  // Of the entries on that page above the point only the last that nothing at its spot outranks counts. An entry is
  // outranked by one at the same spot (the same height within 1e-6 and the same left edge) that is deeper, or as deep
  // and listed earlier. Comparing every pair would cost a figure document's page with hundreds of distinct entries tens
  // of ms a scroll frame, so: at an exactly equal spot the winner (deepest, the first of them) outranks the rest, and
  // only the winners are compared with one another - and each only with the winners that could share its spot. Those
  // are found in two lists, the winners sorted by height and those with a left edge sorted by it (a finite one): a
  // spot's rivals lie in its height window (+-1e-6) and, if it has a left edge, in its edge window (+-1e-3) too, so the
  // shorter window is walked and the other test made on its members. A page of entries at one height and spread along
  // it (a window of one in the edge list), or at one edge and spread down it (a window of one in the height list), is
  // walked in linear time; only winners crowded into one such box (more distinct spots than there are in a 1e-6 x 1e-3
  // box of a real page) cost a walk of the box each. A winner outranked by a loser of a neighbouring spot is outranked
  // by that spot's winner too (it is as deep and as early or better), so the answer is the one the pairwise rule gives.
  const spotWinner = new Map<string, number>();
  entries.forEach((entry, index) => {
    if (entry.page !== top || !above(entry)) return;
    const key = at(entry) + '|' + (leftEdge(entry) === null ? '-' : leftEdge(entry)),
      winner = spotWinner.get(key);
    if (winner === undefined || deep(entry) > deep(entries[winner])) spotWinner.set(key, index);
  });
  // The last listed first: the first of them nothing outranks is the answer.
  const winners = [...spotWinner.values()].sort((first, second) => second - first);
  const byAt = winners.slice().sort((first, second) => at(entries[first]) - at(entries[second]) || first - second),
    byLeftEdge = winners
      .filter((index) => Number.isFinite(leftEdge(entries[index])))
      .sort((first, second) => edgeAt(entries[first]) - edgeAt(entries[second]) || first - second);
  // [from, to) in list (sorted by key) for the members whose key lies within tolerance of value, a little wider to be
  // safe from the rounding of a difference; each is tested exactly below.
  const near = (list: number[], key: (entry: OutlineEntry) => number, value: number, tolerance: number) => {
    const lower = (target: number) => {
      let low = 0,
        high = list.length;
      while (low < high) {
        const middle = (low + high) >> 1;
        if (key(entries[list[middle]]) < target) low = middle + 1;
        else high = middle;
      }
      return low;
    };
    return [lower(value - tolerance * 1.001), lower(value + tolerance * 1.001)];
  };
  const beats = (other: number, index: number) =>
    deep(entries[other]) > deep(entries[index]) || (deep(entries[other]) === deep(entries[index]) && other < index);
  const outranked = (index: number) => {
    const entry = entries[index];
    let list = byAt,
      [low, high] = near(byAt, at, at(entry), 1e-6);
    if (Number.isFinite(leftEdge(entry))) {
      const [edgeLow, edgeHigh] = near(byLeftEdge, edgeAt, edgeAt(entry), 1e-3);
      if (edgeHigh - edgeLow < high - low) {
        list = byLeftEdge;
        low = edgeLow;
        high = edgeHigh;
      }
    }
    for (let position = low; position < high; position++) {
      const other = list[position];
      if (
        other !== index &&
        Math.abs(at(entry) - at(entries[other])) <= 1e-6 &&
        sameLeftEdge(entry, entries[other]) &&
        beats(other, index)
      )
        return true;
    }
    return false;
  };
  for (const i of winners) if (!outranked(i)) return i;
  // Not reached: the winner of the deepest, first spot is outranked by nothing.
  return -1;
}
// An entry picked in the outline: it wins on its page from when the scroll it starts gets there until the reader leaves
// that page (`reached`); on the way there the strip follows the reading line. A pick whose scroll ends anywhere else is
// let go before it is reached, so that a later visit to its page by hand shows that page's own entry: when the reader
// takes over (a wheel, a touch, a press on the pages or the scroll bar, a scrolling key), when the window changes size,
// when another pick replaces it, and when the pages have come to rest short of its page (outlinePickRest).
let OUTLINE_PINNED: { page: number; index: number; reached: boolean } | null = null,
  OUTLINE_PICK_WAIT = 0;
// A smooth scroll moves the pages every frame; this long without a scroll, the pick looks whether they rest.
const OUTLINE_PICK_SETTLE_MS = 250;
// Picks an entry of the outline: the strip and the highlight name it, and the pages scroll to it (outlinePickTop).
function pickOutline(index: number) {
  // A heading of the Markdown surface.
  if (isMarkdownDoc()) {
    pageMarkdown().goToHeading(index);
    return;
  }
  const entry = OUTLINE_ENTRIES[index];
  if (!entry) return;
  OUTLINE_SELECTED = index;
  OUTLINE_ACTIVE_PAGE = entry.page;
  OUTLINE_PINNED = { index: index, page: entry.page, reached: false };
  outlinePickWait();
  markOutline();
  updateSectionStrip();
  pageChanges().setMode('manuscript');
  const top = outlinePickTop(entry);
  if (top === null) {
    goPage(entry.page);
    return;
  }
  glideTo(top);
  arrivalWatch(() => outlinePickTop(entry));
}
// Where a pick scrolls the pages to, as #left's scrollTop: a heading with a place on its page (an XYZ destination below
// the page's top) OUTLINE_PICK_GAP under the free PDF area's top (spotTop); null - goPage's arrival (arrivePage: the
// page's top, or a figure page's figure) - for an entry that names a whole page (frac 0) and for every entry of a
// figure document, whose pages are its figures.
function outlinePickTop(entry: OutlineEntry) {
  const pageBox = document.getElementById('p' + entry.page),
    docEntry = docInfo(DOC);
  if (!pageBox || !(entry.frac > 0) || (docEntry && isFigureKind(docEntry.kind))) return null;
  return spotTop(pageBox, entry.frac, OUTLINE_PICK_GAP);
}
// (Re)starts the wait after which a pick still on its way looks whether the pages rest (any scroll of the pages
// restarts it).
function outlinePickWait() {
  clearTimeout(OUTLINE_PICK_WAIT);
  if (OUTLINE_PINNED && !OUTLINE_PINNED.reached)
    OUTLINE_PICK_WAIT = setTimeout(outlinePickRest, OUTLINE_PICK_SETTLE_MS);
}
// No scroll was heard for OUTLINE_PICK_SETTLE_MS. That alone is no rest: the viewer hears of a scroll in a frame, and a
// busy machine runs this before the frame that carries the glide's next scroll - even its first, after a slow click -
// and letting go then would leave the strip naming the page's own entry where the pick lands (a figure set's adopted
// entry for a pick of the candidate at the same spot). So while the jump is on its way (jumpOnItsWay) the pick waits
// on; at rest the reading line decides, measured now rather than in a frame still to come: on the pick's page the pick
// has reached it (updateSectionStrip), anywhere else it is let go.
function outlinePickRest() {
  const pin = OUTLINE_PINNED;
  if (!pin || pin.reached) return;
  if (jumpOnItsWay()) {
    outlinePickWait();
    return;
  }
  updateSectionStrip();
  if (!pin.reached) dropOutlinePick();
}
// Lets go of a pick that has not reached its page; one that has keeps to the end of its page.
function dropOutlinePick() {
  clearTimeout(OUTLINE_PICK_WAIT);
  if (!OUTLINE_PINNED || OUTLINE_PINNED.reached) return;
  OUTLINE_PINNED = null;
  updateSectionStrip();
}
// The section strip under the nav bar (the section at the reading line and 'page / pages') and the outline's
// highlight; mid has no strip, so the same page count also goes to the nav bar's right end (#nav-page) and the phone's
// position button (drawPos). Both page counts open the page list (openPageList).
function updateSectionStrip() {
  // The Markdown surface's strip and position button.
  if (isMarkdownDoc()) {
    pageMarkdown().updateStrip();
    return;
  }
  const pdfArea = $('#left'),
    anchor = topAnchor(readingDepth(pdfArea)),
    page = anchor ? anchor.page : 1,
    frac = anchor ? anchor.frac : 0;
  const pin = OUTLINE_PINNED;
  if (pin && pin.page === page) {
    pin.reached = true;
    clearTimeout(OUTLINE_PICK_WAIT);
  } else if (pin && pin.reached) OUTLINE_PINNED = null;
  const selected =
    OUTLINE_PINNED && OUTLINE_PINNED.page === page ? OUTLINE_PINNED.index : outlineIndexAt(OUTLINE_ENTRIES, page, frac);
  if (selected !== OUTLINE_SELECTED || page !== OUTLINE_ACTIVE_PAGE) {
    OUTLINE_ACTIVE_PAGE = page;
    OUTLINE_SELECTED = selected;
    markOutline();
  }
  const entry = OUTLINE_ENTRIES[OUTLINE_SELECTED];
  $('#section-current').textContent = entry
    ? (entry.number ? entry.number + '  ' : '') + entry.title
    : translate('원고');
  const pageCount = META && META.pages ? META.pages.length : 0,
    pageText = translateTemplate('{page} / {n}쪽', { page, n: pageCount });
  $('#section-page-t').textContent = pageText;
  $('#nav-page').textContent = pageText;
  const name = translateTemplate('쪽 번호로 이동 · {page} / {n}쪽', { page, n: pageCount });
  $('#section-page').setAttribute('aria-label', name);
  $('#nav-page').setAttribute('aria-label', name);
  drawPos();
}
// The filter's keys (docs/handbook/viewer.md §모바일 레이아웃), the same in the panel and in the phone sheet, each with
// its own field, list and announcement. In the field, Enter chooses the first result and moves the focus onto it - not
// while nothing is typed: an empty filter lists every entry, and Enter must not pick the first of them - and ↓ moves
// the focus onto it without choosing. On a result, ↑/↓ move between the results (↑ on the first goes back to the
// field), Enter chooses (the row is a button), and Esc goes back to the field - and is not also taken by what Esc
// closes (the overlay panel, the navigation sheet). An Enter or an arrow that an input method is composing with (Korean
// typing commits its last syllable with Enter) is the method's, not ours. A key that moves the focus here makes the
// keyboard the input the focus ring answers (html[data-input], platform/tooltip.ts): a field is clicked with the mouse
// and typed in, and the first ↓ must show where the focus went.
/** @returns the result rows (the unread-entries note is not one) */
function outlineRows(box: HTMLElement): HTMLElement[] {
  return [...box.querySelectorAll('button[data-act="outline-page"]')] as HTMLElement[];
}
// Wires one filter field to its list and its live region (outlineSay).
function outlineFilter(field: HTMLElement, box: HTMLElement, status: HTMLElement) {
  const input = field as HTMLInputElement,
    keyed = () => {
      document.documentElement.dataset.input = 'key';
    },
    mine = (event: KeyboardEvent) =>
      !(imeKey(event) || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey);
  field.addEventListener('input', () => {
    outlineList(box, input.value);
    outlineSay(box, input.value, status);
  });
  field.addEventListener('keydown', (event) => {
    if (!mine(event) || (event.key !== 'Enter' && event.key !== 'ArrowDown')) return;
    // Nothing typed: the whole outline is listed, and none of it was asked for.
    if (event.key === 'Enter' && !input.value.trim()) return;
    const first = outlineRows(box)[0];
    // Nothing found: the key is the field's own.
    if (!first) return;
    event.preventDefault();
    keyed();
    // The focus first: choosing in the sheet closes it and gives the focus back to where it was.
    first.focus();
    if (event.key === 'Enter') first.click();
  });
  box.addEventListener('keydown', (event) => {
    const row = (
      event.target && (event.target as HTMLElement).closest
        ? (event.target as HTMLElement).closest('button[data-act="outline-page"]')
        : null
    ) as HTMLElement | null;
    if (!row || !mine(event)) return;
    const rows = outlineRows(box),
      at = rows.indexOf(row);
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      keyed();
      field.focus();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      keyed();
      if (rows[at + 1]) rows[at + 1].focus();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      keyed();
      if (at > 0) rows[at - 1].focus();
      else field.focus();
    }
  });
}
// What a screen reader is told after each keystroke of a filter (a polite status): how many results, or that there are
// none; nothing while the field is empty. The unread-entries note is not a result.
function outlineSay(box: HTMLElement, filterText: string, status: HTMLElement) {
  const count = outlineRows(box).length,
    words = !String(filterText || '').trim()
      ? ''
      : count
        ? translateTemplate('결과 {n}개', { n: count })
        : translate('찾은 장·절이 없습니다.');
  // The same words are not set again: a live region would read '없습니다' at every keystroke.
  if (status.textContent !== words) status.textContent = words;
}
outlineFilter($('#outline-search'), $('#outline-items'), $('#outline-sr'));
// each filter works on its own list only
outlineFilter($('#ns-outline-search'), $('#ns-outline-items'), $('#ns-outline-sr'));
// The sheet's filter draws its list again with rows of other heights (a group's line): the open sheet is fitted to them
// (refitFilteredSheet), so none is left cut. After the filter's own drawing, which is set up just above.
$('#ns-outline-search').addEventListener('input', () => {
  refitFilteredSheet();
});
// The person's hand on the panel (outlineHeld). A scroll inside a hold is theirs going on - a fling, a smooth wheel -
// and extends it; a follow never runs inside one, so its own scroll does not hold anything. A hand on the panel stops a
// glide, so nothing is heading anywhere any more (OUTLINE_AIM), and so do its end, a filter's new list, a panel closing
// and another document (outlineForget).
(function () {
  const box = $('#outline'),
    grip = $('#outline-grip'),
    handled = () => {
      OUTLINE_HANDLED = performance.now();
      OUTLINE_AIM = null;
    };
  for (const eventType of ['wheel', 'pointerdown', 'touchstart', 'touchmove', 'keydown'])
    box.addEventListener(eventType, handled, { passive: true });
  box.addEventListener(
    'scroll',
    () => {
      if (performance.now() - OUTLINE_HANDLED < OUTLINE_FOLLOW_HOLD_MS) handled();
    },
    { passive: true },
  );
  box.addEventListener(
    'scrollend',
    () => {
      OUTLINE_AIM = null;
    },
    { passive: true },
  );
  box.addEventListener('pointerenter', (event: PointerEvent) => {
    if (event.pointerType !== 'touch') OUTLINE_OVER = true;
  });
  box.addEventListener('pointerleave', (event: PointerEvent) => {
    if (event.pointerType !== 'touch') {
      OUTLINE_OVER = false;
      outlineCatchUp();
    }
  });
  // A task after a focusout, the focus has landed: it may be on another row.
  box.addEventListener('focusout', () => {
    setTimeout(outlineCatchUp, 0);
  });
  // The width grip stands beside the panel, and its press and keys are a hand on the panel all the same. A drag holds
  // until it ends (outlineHeld), whatever its length; the timed hold runs from the release or the cancel, so an owed
  // follow is made after it.
  for (const eventType of ['pointerdown', 'pointerup', 'pointercancel', 'keydown'])
    grip.addEventListener(eventType, () => {
      handled();
      if (OUTLINE_FOLLOW_DUE) outlineFollowLater();
    });
  // A press ends the keyboard's hold (html[data-input], platform/tooltip.ts) without a focusout when it lands where a
  // press takes no focus: the pages leave it on the row. Not at once: this runs first of all, and a press in the panel
  // or on its grip must hold before it looks.
  document.addEventListener(
    'pointerdown',
    () => {
      if (OUTLINE_FOLLOW_DUE) setTimeout(outlineCatchUp, 0);
    },
    true,
  );
  // Typing is a hand on the panel, and the list drawn again owes its row. Emptied, the filter ends with no event of its
  // own: it is made when this hold is over, with the focus left in the field.
  $('#outline-search').addEventListener('input', () => {
    handled();
    OUTLINE_FOLLOW_DUE = true;
    outlineFollowLater();
  });
  // Display none to shown: a panel opening, here and not in its toggle, so that a band change that brings it back
  // counts too.
  if (window.ResizeObserver)
    new ResizeObserver(([event]) => {
      const shown = event.contentRect.height > 0;
      if (!shown) {
        OUTLINE_OVER = false;
        OUTLINE_AIM = null;
      }
      if (shown && !OUTLINE_SHOWN) outlineFollow(true);
      OUTLINE_SHOWN = shown;
    }).observe(box);
  // A row the keyboard walks to stops below the filter's band (frame.css), which the hint makes taller while it shows.
  if (window.ResizeObserver) {
    const find = $('#outline-find');
    new ResizeObserver(() => {
      box.style.scrollPaddingTop = find.offsetHeight + 'px';
    }).observe(find);
  }
})();
$('#left').addEventListener(
  'scroll',
  () => {
    if (OUTLINE_PINNED && !OUTLINE_PINNED.reached) outlinePickWait();
    if (!document.body.classList.contains('revision-open')) requestAnimationFrame(updateSectionStrip);
  },
  { passive: true },
);
// The reader taking over the pages lets go of a pick still on its way (dropOutlinePick); so does a new size of the
// window.
for (const eventType of ['wheel', 'touchstart', 'pointerdown'])
  $('#left').addEventListener(eventType, dropOutlinePick, { passive: true });
// A key scrolls the pages when nothing else has the focus, or something on the pages has it.
const SCROLL_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);
addEventListener('keydown', (event) => {
  const focused = document.activeElement;
  if (SCROLL_KEYS.has(event.key) && (!focused || focused === document.body || $('#left').contains(focused)))
    dropOutlinePick();
});
addEventListener('resize', dropOutlinePick);
// Sets OUTLINE_BUILD, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setOutlineBuild<Value extends typeof OUTLINE_BUILD>(value: Value): Value {
  OUTLINE_BUILD = value;
  return value;
}
// Sets OUTLINE_CUT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setOutlineCut<Value extends typeof OUTLINE_CUT>(value: Value): Value {
  OUTLINE_CUT = value;
  return value;
}
// Sets OUTLINE_DOC, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setOutlineDoc<Value extends typeof OUTLINE_DOC>(value: Value): Value {
  OUTLINE_DOC = value;
  return value;
}
// Sets OUTLINE_ENTRIES, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setOutlineEntries<Value extends typeof OUTLINE_ENTRIES>(value: Value): Value {
  OUTLINE_ENTRIES = value;
  return value;
}
// Sets OUTLINE_SELECTED, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setOutlineSelected<Value extends typeof OUTLINE_SELECTED>(value: Value): Value {
  OUTLINE_SELECTED = value;
  return value;
}
export type { OutlineEntry };
export {
  OUTLINE_ACTIVE_PAGE,
  OUTLINE_ENTRIES,
  OUTLINE_SELECTED,
  SCROLL_KEYS,
  loadOutline,
  markOutline,
  outlineForget,
  outlineOnScreen,
  pickOutline,
  renderOutline,
  setOutlineBuild,
  setOutlineCut,
  setOutlineDoc,
  setOutlineEntries,
  setOutlineSelected,
  updateSectionStrip,
};
