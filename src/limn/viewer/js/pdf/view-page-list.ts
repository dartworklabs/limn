// ------------------------------------------------ The page list (docs/handbook/viewer.md §조작 한눈에, §쪽 목록)
// Going to a page without typing. The page count above the page (wide: #section-page) or at the nav bar's end (mid,
// short and the tablet sheet: #nav-page) opens a popover (#page-pop): a page field on top and one row per page below
// it, each with the sections that start on that page. The phone's navigation sheet carries the same rows under its page
// field (#ns-pages). Choosing a row goes there at once - there is no confirm step.
import { DOC, META, COARSE_POINTER_QUERY, buildsFromSource, imeKey, isFigureKind } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { hideTip } from '../platform/tooltip.ts';
import { clampPage, goPage } from './view-pages.ts';
import { OUTLINE_ACTIVE_PAGE, OUTLINE_ENTRIES, outlineOnScreen } from './view-outline.ts';
import { $ } from '../platform/dom.ts';
import { VIEW_MODE } from '../app/rules-tables.ts';
import { verdictOf } from '../app/rules-pins.ts';
import { docInfo, verdictLabel, pageVerdictsOn } from '../documents/state.ts';
import { pageChanges, pageVerdicts } from './state-seams.ts';

// The names a row shows for each of pageTotal pages, index 0 for page 1: the top-level headings that start on the page
// joined with ' · ' ('1 Introduction · 2 Related work'), else the one the page continues ('… 2 Related work'); ''
// before the first heading. entries is the outline in document order (OUTLINE_ENTRIES). Pure.
function pageSections(entries, pageTotal) {
  const name = (entry) => (entry.number ? entry.number + ' ' : '') + entry.title,
    topEntries = entries.filter((entry) => entry.depth === 0),
    out: string[] = [];
  let last = '';
  for (let page = 1; page <= pageTotal; page++) {
    const on = topEntries.filter((entry) => entry.page === page);
    if (on.length) {
      out.push(on.map(name).join(' · '));
      last = name(on[on.length - 1]);
    } else out.push(last ? '… ' + last : '');
  }
  return out;
}
// Whether the document on screen names sections in its page list: a LaTeX manuscript does; a figure document names its
// pages by their titles instead (pageTitles) and a view-only PDF lists page numbers only.
function pageListNamed() {
  const docEntry = docInfo(DOC);
  return !docEntry || buildsFromSource(docEntry.kind);
}
// The title each of pageTotal pages shows in the page list of a document that is not a LaTeX manuscript, index 0 for
// page 1: the title the build's meta gives the page (pages[i].title - a figure's title from its element map), else -
// when byOutline, as in a figure document, whose pages are its figures - the entry of the outline that points at the
// page (the deepest of them, of equally deep ones the first the outline lists, as outlineIndexAt picks among entries
// that start at one spot), else ''. pages is META.pages (or null), entries the outline in document order. Pure.
function pageTitles(pages, entries, pageTotal, byOutline) {
  const name = (entry) => (entry.number ? entry.number + ' ' : '') + entry.title,
    named = new Map();
  if (byOutline)
    entries.forEach((entry) => {
      const best = named.get(entry.page);
      if (!best || (entry.depth || 0) > (best.depth || 0)) named.set(entry.page, entry);
    });
  return Array.from({ length: pageTotal }, (_, index) => {
    const title = pages && pages[index] ? pages[index].title : null;
    if (typeof title === 'string' && title.trim()) return title.trim();
    const entry = named.get(index + 1);
    return entry ? name(entry) : '';
  });
}
// The names the page list shows for pages 1..pageTotal: a LaTeX manuscript's sections, a figure document's page titles,
// else none. A figure's pages are named by the outline only while it is the one read for the build on screen
// (outlineOnScreen): while another document's or build's is still being read, a page without a title shows its number,
// and the list is drawn again when it arrives.
function pageNames(pageTotal) {
  if (pageListNamed()) return pageSections(OUTLINE_ENTRIES, pageTotal);
  const docEntry = docInfo(DOC),
    isFigure = !!docEntry && isFigureKind(docEntry.kind);
  return pageTitles(META && META.pages, isFigure && outlineOnScreen() ? OUTLINE_ENTRIES : [], pageTotal, isFigure);
}
// The number of pages of the build on screen; 0 before /api/meta has answered.
function pageCount() {
  return META && META.pages ? META.pages.length : 0;
}
// The rows for pages 1..pageTotal: the page on screen (currentPage) is the selected option, carries the check and is
// the list's one tab stop. The section names are the manuscript's words (translate="no"); the page number is UI.
// A page whose page verdict line shows a verdict carries it at the row's end, before the check ('#42 채택'): the
// verdicts at a glance.
function pageRowsHtml(pageTotal, currentPage) {
  const names = pageNames(pageTotal),
    verdictPins = pageVerdictsOn() ? pageVerdicts().pagePins() : null;
  return html`${Array.from({ length: pageTotal }, (_, index) => {
    const page = index + 1,
      on = page === currentPage,
      verdictPin = verdictPins && (verdictPins.get(page) || [])[0],
      verdictKey = verdictPin && verdictOf(verdictPin);
    return html`<button class="pl-row${on ? ' on' : ''}" role="option" aria-selected="${on}" tabindex="${on ? 0 : -1}" data-act="page-go" data-page="${page}" data-close="1"><span class="pl-n">${translateTemplate('{page}쪽', { page: page })}</span><span class="pl-s" translate="no">${names[index] || ''}</span>${verdictPin && verdictKey ? html`<span class="pl-v">#${verdictPin.id} <span translate="no">${verdictLabel(verdictKey)}</span></span>` : ''}${on ? lucideIcon('check') : ''}</button>`;
  })}`;
}
// Scrolls list so that its selected row sits in the middle of the list's box (as far as the list can scroll).
function revealPageRow(list) {
  const selectedRow = list.querySelector('[aria-selected=true]') as HTMLElement | null;
  if (!selectedRow) return;
  list.scrollTop = selectedRow.offsetTop - (list.clientHeight - selectedRow.offsetHeight) / 2;
}

// The page count that opened the popover; null while it is shut.
let PAGE_LIST_FROM = null as HTMLElement | null;
// Opens the popover under the page count `from`, listing the pages with the current one in view. A mouse or keyboard
// gets the page field focused, so typing a number still works at once; touch gets the current row focused, so no
// keyboard comes up.
function openPageList(from) {
  const popover = $('#page-pop'),
    list = $('#page-pop-list'),
    pageField = $('#page-pop-in'),
    pageTotal = pageCount();
  hideTip();
  PAGE_LIST_FROM = from;
  from.setAttribute('aria-expanded', 'true');
  pageField.value = '';
  pageField.placeholder = '1–' + pageTotal;
  popover.hidden = false;
  drawPopoverRows();
  revealPageRow(list);
  const row = list.querySelector('[aria-selected=true]') as HTMLElement | null;
  (COARSE_POINTER_QUERY.matches && row ? row : pageField).focus({ preventScroll: true });
}
// Draws the popover's rows - for the page on screen, the names and titles as they are now - and what depends on them:
// the wider list that titles need (a figure's), its place under the page count, and the full title of each row that
// cuts its title short. Keeps the focus on the row it was on, so a list redrawn under the finger or the keys (the
// outline arrived) is the one they were in.
function drawPopoverRows() {
  const popover = $('#page-pop'),
    list = $('#page-pop-list');
  keepRowFocus(list, () => setHtml(list, pageRowsHtml(pageCount(), OUTLINE_ACTIVE_PAGE || 1)));
  popover.classList.toggle(
    'pl-titled',
    !pageListNamed() && [...list.querySelectorAll('.pl-s')].some((nameCell) => nameCell.textContent),
  );
  placePageList();
  tipCutTitles(list);
}
// Runs draw (which replaces the rows of list) and gives the focus back to the row of the same page if it was in the
// list.
function keepRowFocus(list, draw) {
  const focused = document.activeElement,
    row = focused && list.contains(focused) ? focused.closest('.pl-row') : null,
    page = row && (row as HTMLElement).dataset.page;
  draw();
  const again = page ? (list.querySelector('.pl-row[data-page="' + page + '"]') as HTMLElement | null) : null;
  if (again) again.focus({ preventScroll: true });
}
// A figure document's row whose title the row cuts short (an ellipsis) carries the whole title as its description:
// hovering shows it, and so does a long press on touch, which has no native tooltip to rely on (the click after a long
// press is swallowed - a tap still goes to the page). A title that fits carries none. Needs the rows laid out.
function tipCutTitles(list) {
  if (pageListNamed()) return;
  for (const nameCell of list.querySelectorAll('.pl-s') as NodeListOf<HTMLElement>) {
    const row = nameCell.closest('.pl-row') as HTMLElement;
    if (nameCell.scrollWidth > nameCell.clientWidth + 0.5) row.dataset.tip = nameCell.textContent || '';
    else delete row.dataset.tip;
  }
}
// Draws the page lists that are open again (the outline of the document on screen has been read): the popover and the
// navigation sheet's.
function refreshPageLists() {
  hideTip();
  if (!$('#page-pop').hidden) drawPopoverRows();
  if ($('#nav-sheet').open) {
    keepRowFocus($('#ns-pages'), drawSheetPages);
    tipCutTitles($('#ns-pages'));
  }
}
// Puts the open popover under its page count, its right edge on the count's and inside the window by 8px, and lets it
// grow only down to 8px above the window's bottom (--pl-room; 480px at most); its list scrolls inside that. A count
// that is no longer shown shuts it.
function placePageList() {
  const popover = $('#page-pop'),
    from = PAGE_LIST_FROM;
  if (popover.hidden || !from) return;
  if (!from.getClientRects().length) {
    closePageList(false);
    return;
  }
  const rect = from.getBoundingClientRect(),
    popoverWidth = popover.offsetWidth,
    top = rect.bottom + 4;
  popover.style.left = Math.max(8, Math.min(rect.right - popoverWidth, innerWidth - 8 - popoverWidth)) + 'px';
  popover.style.top = top + 'px';
  popover.style.setProperty('--pl-room', Math.max(0, innerHeight - 8 - top) + 'px');
}
// Shuts the popover; back gives the focus back to the page count that opened it (Esc, a choice), an outside click
// leaves it.
function closePageList(back) {
  const popover = $('#page-pop');
  if (popover.hidden) return;
  popover.hidden = true;
  const from = PAGE_LIST_FROM;
  PAGE_LIST_FROM = null;
  if (!from) return;
  from.setAttribute('aria-expanded', 'false');
  if (back) from.focus({ preventScroll: true });
}
// The page count's click: opens the popover under it, or shuts it when it is already open from there.
function togglePageList(from) {
  const again = !$('#page-pop').hidden && PAGE_LIST_FROM === from;
  closePageList(again);
  if (!again) openPageList(from);
}
// Goes to a page chosen in the list or typed in its field: shuts the popover (the sheet shuts through its data-close),
// leaves the changes view for the manuscript, and scrolls to the page.
function goListedPage(page) {
  closePageList(true);
  if (document.body.classList.contains('revision-open')) pageChanges().setMode(VIEW_MODE.MANUSCRIPT);
  goPage(page);
}
// The phone's navigation sheet: its page rows under the page field, scrolled to the current page (openNavigationSheet).
function drawSheetPages() {
  const box = $('#ns-pages'),
    pageTotal = pageCount();
  box.hidden = !pageTotal;
  setHtml(box, pageRowsHtml(pageTotal, OUTLINE_ACTIVE_PAGE || 1));
}

// Keys in a page list (the popover's and the sheet's): ↓/↑ move one row, Home/End to the ends - from the page field ↓/↑
// go to the current page's row; Enter on a row is its click, Enter in the field goes to the typed page (clamped to the
// page count).
function pageListKey(event) {
  const target = event.target as HTMLElement;
  if (imeKey(event)) return;
  if (target.id === 'page-pop-in') {
    if (event.key === 'Enter') {
      event.preventDefault();
      const page = clampPage((target as HTMLInputElement).value, pageCount());
      if (page !== null) goListedPage(page);
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      const selectedRow = $('#page-pop-list [aria-selected=true]') as HTMLElement | null;
      if (selectedRow) {
        event.preventDefault();
        selectedRow.focus();
      }
    }
    return;
  }
  const row = target.closest('.pl-row') as HTMLElement | null;
  if (!row) return;
  const rows = [...(row.parentElement as HTMLElement).children] as HTMLElement[],
    rowIndex = rows.indexOf(row);
  const to = { ArrowDown: rowIndex + 1, ArrowUp: rowIndex - 1, Home: 0, End: rows.length - 1 }[event.key];
  if (to === undefined) return;
  event.preventDefault();
  const next = rows[Math.max(0, Math.min(rows.length - 1, to))];
  next.focus();
  next.scrollIntoView({ block: 'nearest' });
}
$('#page-pop').addEventListener('keydown', pageListKey);
$('#ns-pages').addEventListener('keydown', pageListKey);
// A click outside the popover and its page count shuts it (the click still does what it does).
document.addEventListener(
  'click',
  (event) => {
    const target = event.target as Node;
    if (
      !$('#page-pop').hidden &&
      !$('#page-pop').contains(target) &&
      !(PAGE_LIST_FROM && PAGE_LIST_FROM.contains(target))
    )
      closePageList(false);
  },
  true,
);
addEventListener('resize', placePageList);
export { closePageList, drawSheetPages, goListedPage, refreshPageLists, revealPageRow, tipCutTitles, togglePageList };
