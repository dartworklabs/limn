// ---------------- Switching documents - the navigation sheet, remembered view positions
// (docs/handbook/domain.md §여러 문서)
// Draws the navigation sheet's document rows: the name and path are user text (translate="no"), the badges UI. One
// document leaves the section out - there is nothing to switch to.
import {
  DOC,
  DOCS,
  DONE_ALL,
  PAGE_SCALE,
  LAYOUT,
  META,
  META_BY,
  NAVGEN,
  OPEN_ALL,
  PINS,
  REVIEW_ALL,
  SWITCHSEQ,
  VIEW_BY,
  ZOOMED,
  setDoc,
  setDone,
  setPageScale,
  setMeta,
  setNavgen,
  setPins,
  setSwitchseq,
  setZoomed,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { savePrefs } from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import { hideTip } from '../platform/tooltip.ts';
import { docBadge, drawDocTabs, hashDoc, multiDoc, setHash } from './view-tabs.ts';
import { drawMeta } from './view-meta.ts';
import { resetBuildForDoc } from './view-build-chip.ts';
import { checkDocUpdate } from './flow-updates.ts';
import { showSheet } from '../layout/flow.ts';
import { BACK, BACK_SKIP } from '../layout/input.ts';
import { cancelSelection, COMPOSE } from '../composer/flow-pick.ts';
import { openDraftDoc, parkDraft, restoreDraft } from '../composer/flow-draft.ts';
import { endJumpForScroll } from '../verdict/flow-line.ts';
import { drawPins, marks } from '../pins/flow-list.ts';
import { cancelEdit, editDirty, EDITOR } from '../pins/flow-edit.ts';
import { cancelRepick } from '../composer/flow-repick.ts';
import { refreshDoc, restoreAnchor, topAnchor } from './flow-rebuild.ts';
import { NOTICE_HOST } from '../platform/tables.ts';
import { $, $$, searchToPage } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import { LAYOUT_MODE, VIEW_MODE } from '../app/rules-tables.ts';
import { isMarkdownDoc, docInfo, withDocQuery, pdoc } from './state.ts';
import { changesView, markdownSurface, pageNavigation, pageSurface } from './state-seams.ts';
function drawDocsMenu() {
  $('#ns-docs').hidden = !multiDoc();
  setHtml(
    $('#ns-docs-list'),
    html`${DOCS.map((entry) => {
      const on = entry.key === DOC;
      return html`<button class="dm-item${on ? ' on' : ''}" role="option" aria-selected="${on}" data-act="doc" data-doc="${entry.key}" data-close="1"><span class="tx"><span class="nm" translate="no">${entry.name}${on ? lucideIcon('check') : ''}</span><span class="ph" translate="no">${entry.path}</span></span>${docBadge(entry)}</button>`;
    })}`,
  );
}
// The phone's navigation sheet (docs/handbook/viewer.md §모바일 레이아웃): documents, [원고 | 변경사항], the page field
// with the page rows under it (drawSheetPages, scrolled to the current page) and the outline, each a destination -
// picking one goes there and closes the sheet. The focus is the sheet itself (showSheet) and the outline's current
// section shows in the outline's own scroll while the rest keeps its place (revealSheetOutline); the page field gets no
// focus, so no keyboard covers the sheet.
function openNavigationSheet() {
  const sheet = $('#nav-sheet');
  if (sheet.open) return;
  hideTip();
  drawDocsMenu();
  drawNavigationView();
  pageNavigation().markOutline(); // its rows are drawn already (renderOutline when the outline was read): only the mark moves
  const pageCount = META && META.pages ? META.pages.length : 0,
    pageField = $('#ns-page-in');
  pageField.value = '';
  pageField.placeholder = String(pageNavigation().outlinePage() || 1);
  $('#ns-page-n').textContent = translateTemplate('/ {n}쪽', { n: pageCount });
  pageNavigation().drawSheetPages();
  showSheet(sheet);
  pageNavigation().revealPageRow($('#ns-pages'));
  pageNavigation().tipCutTitles($('#ns-pages'));
  revealSheetOutline(sheet);
}
// The outline's current section in the open sheet (docs/handbook/viewer.md §모바일 레이아웃): the sheet's outline is
// fitted around its current row (fitNavigationSheet). Nothing but the sheet and its list scroll, and the focus stays on
// the sheet.
function revealSheetOutline(sheet) {
  const rows = sheetOutlineRows(),
    current = $('#ns-outline-items').querySelector(':scope>.ol-active');
  fitNavigationSheet(sheet, current ? rows.indexOf(current as HTMLElement) : 0, true);
}
/** @returns the rows of the sheet's outline (the unread entries' note is not one) */
function sheetOutlineRows(): HTMLElement[] {
  return [...$('#ns-outline-items').querySelectorAll(':scope>button')] as HTMLElement[];
}
// the open sheet's height as last fitted to the screen: a filter's fewer results keep it, so the top does not move
let NAVIGATION_SHEET_HEIGHT = 0;
/** Fits the open sheet to its outline's row `at` (docs/handbook/viewer.md §모바일 레이아웃). The open sheet is a column
 * whose top part - the head with the search, the documents, the view and the page field - keeps its place: the page
 * list and the outline's rows share what is left, each showing whole rows (rowsAround, outlineWindow) in a box exactly
 * as tall as they are, so no row is cut at a list's edge, under the outline's filter or at the foot. The page list
 * keeps five rows around the current page while the outline has three; short of that it gives up rows down to the
 * current page's alone, then the outline down to one row, then the page list goes (shareSheetRoom). The sheet takes its
 * whole height once the outline is cut short, the rest under the list, so its top stands where it stood on any page; a
 * filter's results keep the height the sheet had (refit). Only where the documents leave not even that (many documents
 * on a small screen) does the sheet itself scroll, by whole parts, with the current row of the documents (else the
 * view) pinned under the head over what the step brought there (sheetScrollStep). Fitted again after a filter's results
 * (from the first, or the current section when the filter is emptied) and when the sheet's height changes. */
function fitNavigationSheet(sheet: HTMLElement, at: number, centre: boolean, refit: boolean = false) {
  const list = $('#ns-outline-items') as HTMLElement,
    outlineSection = $('#ns-outline') as HTMLElement;
  const pages = $('#ns-pages') as HTMLElement,
    head = sheet.querySelector('.ns-head') as HTMLElement,
    rectOf = (element: Element) => element.getBoundingClientRect();
  list.style.maxHeight =
    list.style.minHeight =
    outlineSection.style.flex =
    outlineSection.style.paddingBottom =
    pages.style.maxHeight =
    pages.style.display =
    sheet.style.minHeight =
      '';
  sheet.scrollTop = 0;
  sheet.style.setProperty('--ns-head-h', head.offsetHeight + 'px');
  // rows in their list's content: [{top, bottom}], measured with the lists at their own size
  const geoOf = (box: HTMLElement, rows: Element[]) => {
    const origin = rectOf(box).top - box.scrollTop;
    return rows.map((row) => {
      const rect = rectOf(row);
      return { top: rect.top - origin, bottom: rect.bottom - origin };
    });
  };
  const pageRows = pages.hidden ? [] : [...pages.querySelectorAll(':scope>[data-act]')],
    pageGeometry = geoOf(pages, pageRows);
  const currentPage = Math.max(
      0,
      pageRows.findIndex((row) => row.getAttribute('aria-selected') === 'true'),
    ),
    maxHeight = parseFloat(getComputedStyle(sheet).maxHeight) || Infinity;
  const rows = sheetOutlineRows(),
    show = !outlineSection.hidden && rows.length > 0,
    current = Math.min(rows.length - 1, Math.max(0, at));
  const reach = Math.ceil(maxHeight / 44) + 3,
    from = Math.max(0, current - reach),
    geometry = show ? geoOf(list, rows.slice(from, current + reach + 1)) : [],
    index = current - from,
    last = geometry.length - 1;
  // no row to show - a filter found nothing: its note takes the outline's place
  const note = outlineSection.hidden || show ? 0 : list.offsetHeight;
  // what the fixed part takes: the sheet with both lists folded away
  list.style.maxHeight = '0px';
  pages.style.display = 'none';
  const room = maxHeight - sheet.offsetHeight;
  list.style.maxHeight = pages.style.display = '';
  const span = (range: [number, number] | null, geometry: { top: number; bottom: number }[]) =>
    range ? geometry[range[1]].bottom - geometry[range[0]].top : 0;
  const least = (count: number) =>
    (centre
      ? [Math.max(0, index - Math.floor((count - 1) / 2)), Math.min(last, index + Math.ceil((count - 1) / 2))]
      : [index, Math.min(last, index + count - 1)]) as [number, number];
  const pagesOf = (count: number) => span(rowsAround(pageGeometry, currentPage, count), pageGeometry),
    most = Math.min(5, pageRows.length);
  const plan = show
    ? shareSheetRoom(room, pagesOf, most, span(least(3), geometry), span(least(1), geometry))
    : shareSheetRoom(room, pagesOf, most, note, note);
  if (plan) {
    const pageRange = rowsAround(pageGeometry, currentPage, plan.pages);
    if (pageRange) {
      pages.style.maxHeight = span(pageRange, pageGeometry) + 'px';
      pages.scrollTop = pageGeometry[pageRange[0]].top;
    } else if (pageRows.length) pages.style.display = 'none';
    if (show) {
      const left = room - span(pageRange, pageGeometry),
        outlineRange = outlineWindow(geometry, index, left, !centre),
        height = span(outlineRange, geometry);
      list.style.maxHeight = height + 'px';
      list.scrollTop = geometry[outlineRange[0]].top;
      if (from > 0 || outlineRange[0] > 0 || from + outlineRange[1] < rows.length - 1)
        outlineSection.style.paddingBottom =
          parseFloat(getComputedStyle(outlineSection).paddingBottom) + Math.max(0, left - height) + 'px';
    } // cut short: the sheet keeps its height
    if (refit && NAVIGATION_SHEET_HEIGHT) sheet.style.minHeight = Math.min(NAVIGATION_SHEET_HEIGHT, maxHeight) + 'px';
    else NAVIGATION_SHEET_HEIGHT = sheet.offsetHeight;
    return;
  }
  if (!refit) NAVIGATION_SHEET_HEIGHT = 0;
  if (!show) return;
  // not even one outline row fits under the fixed part: the sheet scrolls as well, by whole parts, keeping the current
  // page's row and the current outline row
  const pageRange = rowsAround(pageGeometry, currentPage, 1);
  if (pageRange) {
    pages.style.maxHeight = span(pageRange, pageGeometry) + 'px';
    pages.scrollTop = pageGeometry[pageRange[0]].top;
  }
  const leastRange = least(1),
    height = span(leastRange, geometry);
  list.style.maxHeight = list.style.minHeight = height + 'px';
  list.scrollTop = geometry[leastRange[0]].top;
  outlineSection.style.flex = 'none';
  const need = sheet.scrollHeight - sheet.clientHeight;
  if (need <= 0) return;
  const top = rectOf(head).bottom,
    keep = (sheet.querySelector('#ns-docs:not([hidden]) .dm-item.on') ||
      sheet.querySelector('#ns-view')) as HTMLElement,
    keepRect = rectOf(keep);
  const parts = [
    ...sheet.querySelectorAll('#ns-docs,#ns-docs .dm-item,#ns-view,#ns-page,#ns-pages,#ns-outline,#ns-outline>.ns-oh'),
  ]
    .filter((part) => part.getClientRects().length)
    .map((part) => rectOf(part).top - top)
    .sort((x, y) => x - y);
  const by = sheetScrollStep(parts, need, {
    top: keepRect.top - top,
    height: keepRect.height,
    end: keep.matches('.dm-item') && keep.parentElement ? rectOf(keep.parentElement).bottom - top : Infinity,
  });
  if (by > need)
    // padding: a margin collapses through the sheet's end
    outlineSection.style.paddingBottom = parseFloat(getComputedStyle(outlineSection).paddingBottom) + by - need + 'px';
  sheet.scrollTop = by;
}
/** How the page list and the outline share the room under the sheet's fixed part (all heights in px): the most page
 * rows, up to `most`, that leave the outline three rows (three), then - short of that - one page row and the outline
 * one (one), then no page row; null when not even one outline row fits. pagesOf(count) is the height of that many page
 * rows around the current one. Pure. */
function shareSheetRoom(
  room: number,
  pagesOf: (count: number) => number,
  most: number,
  three: number,
  one: number,
): { pages: number } | null {
  for (let count = most; count >= Math.min(1, most); count--)
    if (room - pagesOf(count) >= three - 0.5) return { pages: count };
  for (const count of [Math.min(1, most), 0]) if (room - pagesOf(count) >= one - 0.5) return { pages: count };
  return null;
}
/** The `count` rows of a list of equal rows around `current` (rows: their tops and bottoms, in order), as near the
 * middle as the ends allow; null for none. Pure. */
function rowsAround(rows: { top: number; bottom: number }[], current: number, count: number): [number, number] | null {
  if (count <= 0 || !rows.length) return null;
  const first = Math.max(0, Math.min(current - Math.floor((count - 1) / 2), rows.length - count));
  return [first, Math.min(rows.length - 1, first + count - 1)];
}
// The keyboard coming up or going changes the sheet's height (--vvh, layout/flow.ts, which runs first): the sheet is
// fitted again - at the current section, or under a filter from the result at the top of the list - so no row is left
// cut at the new edges.
for (const target of [window.visualViewport, window])
  if (target)
    target.addEventListener('resize', () => {
      const sheet = $('#nav-sheet') as HTMLDialogElement;
      if (sheet.open)
        requestAnimationFrame(() => {
          if (!sheet.open) return;
          if (!$('#ns-outline-search').value.trim()) {
            revealSheetOutline(sheet);
            return;
          }
          const listTop = $('#ns-outline-items').getBoundingClientRect().top;
          fitNavigationSheet(
            sheet,
            Math.max(
              0,
              sheetOutlineRows().findIndex((row) => row.getBoundingClientRect().bottom > listTop + 0.5),
            ),
            false,
          );
        });
    });
// The sheet's filter has drawn its list again (pdf/view-outline.ts): fitted from the first result, keeping the sheet's
// height - or, emptied, back at the current section.
function refitFilteredSheet() {
  const sheet = $('#nav-sheet') as HTMLDialogElement;
  if (!sheet.open) return;
  if ($('#ns-outline-search').value.trim()) fitNavigationSheet(sheet, 0, false, true);
  else revealSheetOutline(sheet);
}
/** The outline rows the sheet shows (rows: their tops and bottoms in the list, in order; current: the row to show): the
 * most whole rows around `current` that fit in room, taken one at a time on the side that has fewer, so it stands near
 * the middle - or, down, below it first and above only when the list ends; it alone when no more fit. Pure. */
function outlineWindow(
  rows: { top: number; bottom: number }[],
  current: number,
  room: number,
  down: boolean = false,
): [number, number] {
  let first = current,
    last = current;
  for (;;) {
    const canUp = first > 0 && rows[last].bottom - rows[first - 1].top <= room,
      canDown = last < rows.length - 1 && rows[last + 1].bottom - rows[first].top <= room;
    if (!canUp && !canDown) return [first, last];
    if (canDown && (down || !canUp || last - current < current - first)) last++;
    else first--;
  }
}
/** How far the sheet scrolls when its top part leaves the outline too little (parts: their tops under the head with the
 * sheet at its top, ascending; need: how far it must go at least). Before the pinned row (pin: its top and height, and
 * the end of what holds it) reaches the head, a step stops on a part's top, so the head cuts none. Once it is pinned, a
 * step stops where a part starts right under it, and the parts between lie wholly behind it or the head; past what
 * holds it, the pinned row has gone under the head and a step stops on a part's top again. The least such step, in
 * whole px since the sheet scrolls in them; the last part when there is none. Pure. */
function sheetScrollStep(
  parts: number[],
  need: number,
  pin: { top: number; height: number; end: number } | null = null,
) {
  let best = Infinity;
  const ok = (step: number) => step >= need - 0.5 && step < best;
  for (const part of parts) {
    if (!pin || part <= pin.top + 0.5 || pin.end - part <= 0.5) {
      if (ok(part)) best = part;
      continue;
    }
    const step = part - pin.height;
    if (step >= pin.top - 0.5 && pin.end - step >= pin.height - 0.5 && ok(step)) best = step;
  }
  return Math.ceil(best < Infinity ? best : parts.length ? parts[parts.length - 1] : 0);
}
// The navigation sheet's view switch: the view on screen is the checked radio.
function drawNavigationView() {
  const isRevisions = document.body.classList.contains('revision-open');
  for (const radio of $$('#ns-view [role=radio]')) {
    const on = (radio.dataset.mode === VIEW_MODE.REVISIONS) === isRevisions;
    radio.setAttribute('aria-checked', String(on));
    radio.classList.toggle('on', on);
  }
  roveSegment($('#ns-view')); // the group's one Tab stop is the view now chosen (platform/segments.ts)
}
// The phone's position button (docs/handbook/viewer.md §모바일 레이아웃): [본문 3/25 ▾] - the document's name only with
// several documents on a 400px-or-wider phone, the reading line's page of the pages, '–/–' before they are known, and
// '변경사항' in the changes view - as {name, pages, label}; label is its accessible name. Pure but for
// translate/translateTemplate.
function posLabel(doc, page, pageCount, multi, wide, mode) {
  if (mode === VIEW_MODE.REVISIONS)
    return { name: '', pages: translate('변경사항'), label: translate('이동') + ' · ' + translate('변경사항') };
  const name = multi && wide ? doc : '',
    pageShown = pageCount ? page : '–',
    countShown = pageCount ? pageCount : '–';
  return {
    name,
    pages: pageShown + '/' + countShown,
    label: name
      ? translateTemplate('이동 · {doc} · {page} / {n}쪽', { doc: name, page: pageShown, n: countShown })
      : translateTemplate('이동 · {page} / {n}쪽', { page: pageShown, n: countShown }),
  };
}
// Draws [본문 3/25 ▾] from the document on screen, the reading line's page and the view (posLabel), with a dot when
// another document's manuscript is newer or building. The button is translate="no" (a document name), so its UI words
// are translate()'d here.
function drawPos() {
  const button = $('#btn-pos');
  if (!button) return;
  const shown = docInfo(DOC),
    pageCount = META && META.pages ? META.pages.length : 0,
    isRevisions = document.body.classList.contains('revision-open');
  const label =
    isMarkdownDoc() && !isRevisions
      ? // a Markdown document has lines, not pages
        markdownSurface().positionLabel(
          shown ? shown.name : '',
          markdownSurface().reading().at,
          markdownSurface().reading().lines.length,
          multiDoc(),
          innerWidth >= 400,
        )
      : posLabel(
          shown ? shown.name : '',
          pageNavigation().outlinePage() || 1,
          pageCount,
          multiDoc(),
          innerWidth >= 400,
          isRevisions ? VIEW_MODE.REVISIONS : VIEW_MODE.MANUSCRIPT,
        );
  const nameSpan = $('#btn-pos-n');
  nameSpan.textContent = label.name;
  nameSpan.hidden = !label.name;
  $('#btn-pos-p').textContent = label.pages;
  button.setAttribute('aria-label', label.label);
  button.dataset.tip = translate('문서·보기·쪽·목차로 갑니다');
  $('#btn-pos-dot').hidden = !DOCS.some((other) => other.key !== DOC && (other.stale_build || other.building));
}
// Viewed position: page/fraction anchored at the top, page scale (PAGE_SCALE), whether zoomed manually in compact,
// horizontal scroll. Kept in sessionStorage so it survives a reload.
function saveView() {
  if (!DOC || !META) return;
  if (isMarkdownDoc()) {
    const anchor = markdownSurface().reading().shown === DOC ? markdownSurface().readingAnchor() : null;
    if (anchor) VIEW_BY.set(DOC, { line: anchor.line, off: anchor.off, lay: LAYOUT });
    saveViews();
    return;
  } // its reading line
  if (!$('#doc .pg')) return;
  const anchor = topAnchor();
  VIEW_BY.set(DOC, {
    page: anchor ? anchor.page : 1,
    frac: anchor ? anchor.frac : 0,
    k: PAGE_SCALE,
    zoomed: ZOOMED,
    sl: $('#left').scrollLeft,
    lay: LAYOUT,
  });
  saveViews();
}
function saveViews() {
  if (multiDoc()) {
    try {
      sessionStorage.setItem('pinDocView', JSON.stringify(Array.from(VIEW_BY.entries())));
    } catch (error) {}
  }
}
function loadViews() {
  if (!multiDoc()) return;
  try {
    const kept = JSON.parse(sessionStorage.getItem('pinDocView') || '[]');
    if (Array.isArray(kept))
      kept.forEach((x) => {
        if (Array.isArray(x) && docInfo(x[0]) && x[1] && typeof x[1] === 'object') VIEW_BY.set(x[0], x[1]);
      });
  } catch (error) {}
}
// A kept view's scale: its k, or - for a view kept with the page width (w) instead - that width over the widest page
// (points); 0 when it has neither. Pure.
function viewScale(view, widest) {
  return typeof view.k === 'number' && view.k > 0
    ? view.k
    : typeof view.w === 'number' && view.w > 0 && widest > 0
      ? view.w / widest
      : 0;
}
// The page scale is decided first (buildDoc sizes pages by PAGE_SCALE). Only a scale viewed in the same layout is
// restored - so a width fit for a folded screen is never applied on desktop; without one the document starts at its
// saved or default scale (startScale). Returns whether a kept view decided it.
function applyViewWidth(view) {
  if (view && view.lay === LAYOUT && (LAYOUT === LAYOUT_MODE.WIDE || view.zoomed)) {
    const scale = viewScale(view, pageSurface().widestPoints());
    if (scale) {
      setPageScale(scale);
      setZoomed(LAYOUT !== LAYOUT_MODE.WIDE && !!view.zoomed);
      return true;
    }
  }
  setZoomed(false);
  setPageScale(pageSurface().startScale());
  return false;
}
function restoreView(view) {
  if (!view) return;
  if (isMarkdownDoc()) {
    markdownSurface().reading().want =
      typeof view.line === 'number' ? { line: view.line, off: +view.off || 0, top: 0 } : null;
    return;
  } // once it is drawn (showDocumentNode)
  restoreAnchor({ page: view.page, frac: view.frac });
  if (typeof view.sl === 'number') $('#left').scrollLeft = view.sl;
}
addEventListener('pagehide', saveView);
// Switches documents. Remembers the current view and draft, then opens only the destination document's draft. If a meta
// cache exists, that document is drawn immediately without waiting, then the latest meta is fetched in the background,
// and pages are swapped only if the build changed. A document that cannot be opened says so on the status line, with
// [다시 시도] when the server could not be reached. A focus in the pages (a line's control, the PDF area) stays on the
// PDF area: the new pages take the focused element away, and from nothing (body) the next Tab would go to the first
// page's line and scroll there. A history traversal (the browser's back or forward) ends a switch still waiting for its
// document's meta (NAVGEN): the address already names where the traversal went, so the late answer neither opens its
// document nor puts its hash on that entry, and the document left keeps its draft. While it waits, SWITCH_TO names it
// (switchPending).
async function switchDoc(doc) {
  if (!doc || doc === DOC || !docInfo(doc)) return;
  const seq = setSwitchseq(SWITCHSEQ + 1),
    navigation = NAVGEN;
  pageNavigation().leaveSearch(); // the search belongs to the document left (pdf/flow.ts)
  const active = document.activeElement,
    inPages = !!active && !!active.closest && !!active.closest('#left');
  if (document.body.classList.contains('revision-open')) changesView().setMode(VIEW_MODE.MANUSCRIPT);
  saveView();
  parkDraft();
  cancelRepick();
  if (COMPOSE.current || !$('#composer').hidden) cancelSelection(false);
  if (EDITOR.current && !editDirty()) cancelEdit();
  let meta = META_BY.get(doc),
    cached = !!meta;
  if (!meta) {
    SWITCH_TO = { k: doc, seq, nav: navigation };
    try {
      meta = (
        await api(withDocQuery('/api/meta', doc), {
          what: '문서 열기',
          where: NOTICE_HOST.LINE,
          retry: () => {
            switchDoc(doc);
          },
        })
      ).data;
    } catch (error) {
      if (seq === SWITCHSEQ) restoreDraft();
      return;
    } finally {
      if (SWITCH_TO && SWITCH_TO.seq === seq) SWITCH_TO = null;
    }
    if (seq !== SWITCHSEQ) return;
    if (navigation !== NAVGEN) {
      restoreDraft();
      return;
    }
  }
  setDoc(doc);
  setMeta(meta);
  META_BY.set(doc, meta);
  savePrefs({ lastDoc: doc });
  setHash(doc);
  hideTip();
  showDoc(VIEW_BY.get(doc));
  openDraftDoc();
  checkDocUpdate(doc, {}); // changed since this device last saw it (documents/flow-updates.ts)
  if (inPages && (!document.activeElement || document.activeElement === document.body)) searchToPage();
  if (cached) {
    try {
      const fresh = (await api(withDocQuery('/api/meta', doc), { what: '문서 열기', silent: true })).data;
      if (seq === SWITCHSEQ && DOC === doc) {
        const changed = fresh.pages_build !== META.pages_build || fresh.pages.length !== META.pages.length;
        META_BY.set(doc, fresh);
        if (changed) await refreshDoc(fresh);
        else {
          setMeta(fresh);
          drawMeta();
        }
      }
    } catch (error) {}
  }
}
// The switch waiting for its document's meta (switchDoc), or null.
let SWITCH_TO = null as { k: string; seq: number; nav: number } | null;
// Whether a switch to `doc` is on its way and still the one that will open: the newest switch, no history traversal
// since.
function switchPending(doc: string) {
  const pending = SWITCH_TO;
  return !!pending && pending.k === doc && pending.seq === SWITCHSEQ && pending.nav === NAVGEN;
}
// Redraws the screen from the current META (tab switching), including open and done rows from this document before the
// background refresh. The build chip, error panel, and auto-polling baseline are switched to that document's values
// too.
function showDoc(view) {
  endJumpForScroll();
  drawMeta();
  const hadWidth = applyViewWidth(view);
  pageSurface().build();
  if (!hadWidth) pageSurface().fitWidth();
  restoreView(view);
  if (!view && $('#left')) $('#left').scrollTop = 0;
  setPins(OPEN_ALL.filter((pin) => pdoc(pin) === DOC));
  setDone(DONE_ALL.filter((pin) => pdoc(pin) === DOC));
  drawPins();
  marks();
  drawDocTabs();
  $('#outline-items').textContent = translate('PDF 목차를 읽는 중입니다.');
  if (document.body.classList.contains('revision-open')) changesView().load();
  pageSurface().openVector();
  resetBuildForDoc(); // if a previous document's request is still in flight, queue after it
  docTitle(false);
}
// The tab title: 'Limn · <label> · <document> · 열린 N' (+ ' · 검토 N' once the pin list knows the review count).
function docTitle(review) {
  if (!META) return;
  document.title =
    'Limn · ' +
    (META.label ? META.label + ' · ' : '') +
    (multiDoc() ? META.doc_name || META.main : META.main) +
    ' · ' +
    translateTemplate('열린 {n}', { n: PINS.length }) +
    (review && REVIEW_ALL.length ? ' · ' + translateTemplate('검토 {n}', { n: REVIEW_ALL.length }) : '');
}
function cycleDoc(step) {
  if (!multiDoc()) return;
  const index = DOCS.findIndex((entry) => entry.key === DOC);
  switchDoc(DOCS[(index + step + DOCS.length) % DOCS.length].key);
}
// Each history traversal is a new navigation generation (NAVGEN), also one back to the document on screen - except the
// back layer's own entry (layout/input.ts: a back that closes a sheet, or the entry it pops itself), which leaves the
// documents alone. This listener runs before the layer's, so BACK and BACK_SKIP still say whose entry it was. A
// traversal then shows the document its address names (followHash): between two entries of the same address no
// hashchange comes, and the switch it just ended must not leave the address naming one document over another on screen.
window.addEventListener('popstate', () => {
  if (BACK_SKIP || (BACK && BACK.kind === 'history')) return;
  setNavgen(NAVGEN + 1);
  followHash();
});
window.addEventListener('hashchange', followHash);
// Opens the document the address names (#doc=), unless it is on screen or a switch to it is on its way already.
function followHash() {
  const doc = hashDoc();
  if (doc && doc !== DOC && docInfo(doc) && !switchPending(doc)) switchDoc(doc);
}
// A #number/[보기]/[수정] on another document's pin: switches to that document, then calls `then` again (used by
// jumpPin/openEdit at the very top). Returns true if it switched.
function viaDoc(id, then) {
  const pin = OPEN_ALL.find((x) => x.id === id);
  if (!pin || pdoc(pin) === DOC || !docInfo(pdoc(pin))) return false;
  const doc = pdoc(pin),
    opening = switchDoc(doc),
    visit = SWITCHSEQ;
  opening.then(() => {
    if (DOC === doc && visit === SWITCHSEQ) then(id);
  });
  return true;
}
export {
  applyViewWidth,
  cycleDoc,
  docTitle,
  drawDocsMenu,
  drawNavigationView,
  drawPos,
  loadViews,
  refitFilteredSheet,
  openNavigationSheet,
  restoreView,
  switchDoc,
  switchPending,
  viaDoc,
};
