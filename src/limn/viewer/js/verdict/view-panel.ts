// ---------------------------------------- The page verdict panel beside the pages (docs/handbook/viewer.md §판정 패널)
// On a wide desktop whose PDF area leaves room right of the pages, the page verdict line is one panel in that margin
// (#pv-panel, --pv-panel-w wide, --pv-panel-gap off the page) instead of a line under every page: the reading page's
// line (READING_LINE_PAGE, the page under the 160px reading line that the section strip and the keys name), drawn again
// (fillPageLine) when the reading page changes, its parts in rows down the panel (the name, the words, the state, the
// reason) - the words stand at one place on the screen for every page. Under each page a one-row summary (.pv-sum: '6쪽
// · PL17 · 판정 #7 채택 · 처리 대기') says its verdict, the reading page's in bold, and a press brings that page to the
// panel. Every block (.pgw) is a grid [margin | page | margin] whose right margin holds the panel: the page stays
// centred while both margins hold it and moves left only by what the right one lacks. Where the room is short (a
// narrower window, the pin panel opened, a zoomed page) the lines go back under the pages, with hysteresis
// (PANEL_ENTER_ROOM, PANEL_EXIT_ROOM) so a width at the bar does not flip it. The wide band only: the foldable and
// phone bands never take it. The line's words, keys, focus, save chip and reason are the line's own
// (verdict/flow-line.ts, verdict/flow-reason.ts); this part decides when, places the panel and draws the summaries.
import { DOC, PAGE_SCALE, LAYOUT, META, isFigureKind } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { NOTICES, chipAway, drawChips } from '../platform/notices.ts';
import { pdfAreaInnerWidth, pageWidth, widestPagePoints } from '../pdf/view-pages.ts';
import { BAND_TIMER, topAnchor } from '../layout/flow.ts';
import {
  CHIP_WATCH,
  READING_LINE_PAGE,
  LINE_TEXT,
  drawPageVerdicts,
  fillPageLine,
  noteCameFrom,
  canCancelVerdict,
  pageLineName,
  keepFocusOnLine,
  pageUnderReadingLine,
  readingPageWithLine,
  stickReadingLine,
  stickSoon,
  fitWrappedWords,
} from './flow-line.ts';
import {
  REASON_SESSION,
  isComposingNow,
  focusLine,
  isReasonField,
  findReasonField,
  leaveReason,
  setComposingField,
} from './flow-reason.ts';
import { $, $$, searchToPage, TABBABLE, isTabStop } from '../platform/dom.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { verdictOf } from '../app/rules-pins.ts';
import { verdictLabel, pageVerdictsOn } from '../documents/state.ts';
import {
  arrivalWatch,
  LAST_SCROLL_AT,
  HAS_SCROLLEND,
  isAutoScrolling,
  glideTo,
  endJumpForScroll,
} from '../layout/flow-scroll.ts';
import { readingDepth } from '../pdf/view-page-jump.ts';
import { pageTakesVerdict, verdictStateWord } from './view-pins.ts';
import { watchFarLines } from './view-far-lines.ts';
import { getDraft } from './state-drafts.ts';

// The panel's room in px, as the CSS draws it (verdict-panel.css --pv-panel-w, --pv-panel-gap): the margin right of a
// page holds the panel and its gap, and the left margin keeps at least PANEL_LEFT_MARGIN. The lines go beside the pages
// when the PDF area's inner width less the page's is PANEL_ENTER_ROOM or more, and back under them below
// PANEL_EXIT_ROOM; in between they stay as they are.
const PANEL_WIDTH = 280,
  PANEL_GAP = 24,
  PANEL_LEFT_MARGIN = 24,
  PANEL_HYSTERESIS = 32;
const PANEL_EXIT_ROOM = PANEL_WIDTH + PANEL_GAP + PANEL_LEFT_MARGIN,
  PANEL_ENTER_ROOM = PANEL_EXIT_ROOM + PANEL_HYSTERESIS;
let IS_BESIDE_PAGES = false; // the lines stand beside the pages now: one panel, a summary under each page
// The room the PDF area leaves beside the pages: its inner width less the widest page's width at the scale on screen -
// below 0 for a page wider than the area - or null while the area is not drawn (the changes view): the lines then stay
// as they are. One width for the whole document, so the reading page never decides it and scrolling never turns the
// panel on or off. The widest, not the most common: a wider page's block would take the panel's margin past the area,
// the column would grow with it, and every page would move right under the panel. With it every page stands beside the
// panel, on one axis (verdict-panel.css).
function measureBesideRoom(): number | null {
  const area = $('#left');
  if (!META || !Array.isArray(META.pages) || !META.pages.length || !area.getClientRects().length) return null;
  return pdfAreaInnerWidth() - pageWidth(widestPagePoints(), PAGE_SCALE);
}
// Whether the lines should stand beside the pages: the wide band, a document with page lines, and the room - with
// hysteresis around the bar. They stay as they are while the band settles (BAND_TIMER): moved at the old band's new
// width they would stack, the space under a page would grow, and the re-fit that follows would take its spot from there
// and leave the page read off its place. bandSettle looks again once the band has settled.
function shouldStandBeside() {
  // a syllable being composed in the reason keeps the lines where they are until it ends and its key lets the field go
  if (isComposingNow() || BAND_TIMER) return IS_BESIDE_PAGES;
  if (LAYOUT !== LAYOUT_MODE.WIDE || !pageVerdictsOn()) return false;
  const room = measureBesideRoom();
  if (room === null) return IS_BESIDE_PAGES;
  return IS_BESIDE_PAGES ? room >= PANEL_EXIT_ROOM : room >= PANEL_ENTER_ROOM;
}
// Sets IS_BESIDE_PAGES and the body's class for it (body.pv-beside). No drawing.
function applyBeside(on: boolean) {
  IS_BESIDE_PAGES = on;
  document.body.classList.toggle('pv-beside', on);
}
// Whether the room crossed its bar since the lines were drawn (stickReadingLine: a resize, the pin panel, a zoom, the
// frame after it): they are drawn again, beside or under the pages. Whether it did.
function redrawOnBesideChange() {
  if (shouldStandBeside() === IS_BESIDE_PAGES) return false;
  drawPageVerdicts();
  return true;
}
// The reading page held while the lines move (startBesideTurn to settleBesideTurn), 0 otherwise: read from the layout
// between the two it would be another page - the blocks change their height, and only the settling puts the spot back -
// and a reason being typed would move on, its half text written and the digits after it taken as verdict keys. A var:
// pageUnderReadingLine reads it.
var HELD_READING_PAGE = 0;
// The reading page held while the pages are built again (refreshDoc), until the reading spot is back: read from the new
// column before that, it would be a neighbour, and the reason being typed on the panel would be moved on from - written
// and closed.
var BUILD_READING_PAGE = 0;
// Before the lines are drawn (drawPageVerdicts): follows the room. When it crossed its bar every line goes and new ones
// come, so what the person has must be carried over: the reading page, the point of it under the reading line, and the
// focus. Null when the lines stay where they are. A composition cannot cross: its field goes, and with it its end.
function startBesideTurn() {
  const on = shouldStandBeside();
  if (on === IS_BESIDE_PAGES) return null;
  const area = $('#left'),
    active = document.activeElement as HTMLElement | null,
    field = isReasonField(active) ? (active as HTMLTextAreaElement) : null,
    at = pageUnderReadingLine();
  const keep = {
    spot: area.scrollTop > 0 ? topAnchor(readingDepth(area)) : null,
    inLine: !!active && !!active.closest && !!active.closest('#doc .pv'),
    caret: field ? [field.selectionStart, field.selectionEnd] : null,
    popAct: (!!active && !!active.closest && !!active.closest('#doc .pv-pop') && !field && active.dataset.act) || '',
    ctl: describeControl(active),
  };
  if (field) setComposingField(null);
  HELD_READING_PAGE = at;
  applyBeside(on);
  return keep;
}
// The lines have moved and are fitted: the point that was under the reading line is there again, so the page in view
// does not shift and the reading page is the one held (a rounded scroll position may fall a pixel off a page's edge:
// taken back). A reading line in the space above the page (the spot's gap) stands that far above it again, as far as
// the new space keeps it past the page before, or that page would be the one read. The space changes with the lines, so
// the page before moves by the difference: the page read is the one held.
function settleBesideTurn(kept: NonNullable<ReturnType<typeof startBesideTurn>>) {
  HELD_READING_PAGE = 0;
  const spot = kept.spot,
    pageElement = spot ? document.getElementById('p' + spot.page) : null;
  if (!spot || !pageElement) return;
  const area = $('#left'),
    y = () => area.getBoundingClientRect().top + readingDepth(area),
    rect = pageElement.getBoundingClientRect(),
    up = document.getElementById('p' + (spot.page - 1)),
    room = up ? rect.top - up.getBoundingClientRect().bottom : Infinity,
    gap = Math.min(spot.gap, Math.max(0, room - 2));
  area.scrollTop += rect.top + spot.frac * rect.height - gap - y();
  const settled = pageElement.getBoundingClientRect();
  if (settled.bottom <= y()) area.scrollTop -= 2;
  else if (!gap && settled.top > y()) area.scrollTop += 2;
}
// After the lines moved: a save chip stands on its pin's new line (drawChips, else its undo goes to the status line),
// and the reason field that had the focus has it again with its caret, or the popover's button its focus - what is
// typed next stays text, never a verdict key. Any other control focused on a line has the focus on the same control of
// its moved line (findControlAgain). A focus on another page's line, which the panel does not show, goes to the PDF
// area, not to nothing.
function finishBesideTurn(kept: NonNullable<ReturnType<typeof startBesideTurn>>) {
  drawChips();
  const field = kept.caret ? findReasonField() : null;
  if (field && kept.caret) {
    field.focus({ preventScroll: true });
    field.setSelectionRange(kept.caret[0], kept.caret[1]);
    return;
  }
  const button = (
    kept.popAct ? document.querySelector('#doc .pv-pop [data-act="' + kept.popAct + '"]') : null
  ) as HTMLElement | null;
  if (button) {
    button.focus({ preventScroll: true });
    return;
  }
  const active = document.activeElement;
  if (!kept.inLine || (active && active !== document.body)) return;
  const control = findControlAgain(kept.ctl);
  if (control) {
    control.focus({ preventScroll: true });
    return;
  }
  searchToPage();
}
// A control focused on a line, as the lines move (startBesideTurn): its line's page and what names it among that line's
// controls - its action and, where several share one, its word (data-key), the pin it leads to (data-ref), its id or
// its message (a save chip's button, data-n). null for none, the reason field and the popover's buttons (carried on
// their own).
function describeControl(
  element: Element | null,
): { page: string; act: string; key: string; ref: string; id: string; n: string } | null {
  if (!(element instanceof HTMLElement) || !element.closest || element.closest('.pv-pop') || isReasonField(element))
    return null;
  const line = element.closest('#doc .pv') as HTMLElement | null;
  const act = element.dataset.act || '';
  if (!line || !act) return null;
  return {
    page: line.dataset.page || '',
    act,
    key: element.dataset.key || '',
    ref: element.dataset.ref || '',
    id: element.dataset.id || '',
    n: element.dataset.n || '',
  };
}
// The same control on the moved line of that page - beside the pages or under one - shown, or null (the panel shows
// another page now). The focus lands there: on the PDF area it would lose its place, and Enter on [이유 추가] would not
// write the reason.
function findControlAgain(described: ReturnType<typeof describeControl>): HTMLElement | null {
  const line = described ? document.querySelector('#doc .pv[data-page="' + CSS.escape(described.page) + '"]') : null;
  if (!described || !line) return null;
  return (
    ([...line.querySelectorAll('[data-act="' + CSS.escape(described.act) + '"]')].find(
      (element) =>
        element instanceof HTMLElement &&
        (element.dataset.key || '') === described.key &&
        (element.dataset.ref || '') === described.ref &&
        (element.dataset.id || '') === described.id &&
        (element.dataset.n || '') === described.n &&
        element.getClientRects().length > 0,
    ) as HTMLElement | undefined) || null
  );
}

// ---------------- The panel
// The panel (#pv-panel): a page verdict line of its own, in the last child of the pages' column (#pv-panel-at) - so
// every '#doc .pv[data-page]' look-up of the reading page's line finds it, the DOM's Tab from its last control leaves
// the pages (to the pin panel), and a rebuild of the column (buildDoc) takes it away with the pages. #pv-panel-at has
// no height and is sticky to the PDF area's top, so the panel stays in view while it stays in the area's scroll chain:
// PageDown, the arrows, Home and End on one of its controls and a wheel over it move the pages, by the browser's own
// steps, as on a line under a page. Fixed to the window it would be out of that chain: after a key save the keys and
// the wheel would move nothing, and the next digit would change the same page's verdict.
function ensurePanel() {
  let panel = document.getElementById('pv-panel') as HTMLElement | null;
  if (!panel) {
    const at = document.createElement('div');
    at.id = 'pv-panel-at';
    panel = document.createElement('div');
    panel.id = 'pv-panel';
    panel.className = 'pv pv-panel pv-stack';
    panel.dataset.tipAt = 'left'; // its descriptions stand left of it (platform/tooltip.ts)
    at.appendChild(panel);
    $('#doc').appendChild(at);
    if (CHIP_WATCH) CHIP_WATCH.observe(panel, { childList: true });
  }
  return panel;
}
function removePanel() {
  const at = document.getElementById('pv-panel-at');
  if (at) at.remove();
}
// Fills the panel with the reading page's line (READING_LINE_PAGE). A page that takes no verdict (a list page, a
// comparison board) names itself in one form whatever its title looks like - the page ('2쪽') on the name's row and the
// map's whole title, if it has one, on the title's row (quietPageTitle) - and says it takes none, without words. The
// verdict pages' split of a title at its first ' · ' (pageLineName) would put a board's '비교판' beside its page and
// leave a list page's title out. A save chip on the panel for a pin of another page goes to the status line with its
// undo (chipAway), as a chip whose mark is not drawn does: the panel does not show the verdict it undoes.
function fillPanel(map: Map<number, Pin[]>, verdicts: DocVerdicts) {
  const panel = ensurePanel(),
    readingPage = READING_LINE_PAGE,
    at = heldPanelPage() || pageUnderReadingLine(),
    list = readingPage ? map.get(readingPage) || [] : [];
  leavePanelPage(panel, at);
  const chip = panel.querySelector(':scope>.nt-chip') as HTMLElement | null;
  if (chip && !list.some((x) => x.id === pinOfChip(chip))) chipAway(chip);
  if (readingPage) {
    panel.classList.remove('pv-quiet');
    fillPageLine(panel, readingPage, map.get(readingPage), verdicts);
    placePanel();
    flashOnArrival(readingPage);
    return;
  }
  LINE_TEXT.delete(panel);
  panel.classList.add('pv-quiet');
  panel.classList.remove('reading');
  panel.dataset.page = String(at || 0);
  delete panel.dataset.pin;
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', at ? translateTemplate('{page}쪽 판정', { page: at }) : translate('판정'));
  const title = at ? quietPageTitle(at) : '';
  setHtml(
    panel,
    html`<span class="pv-fig" translate="no"><span class="pv-fig-id">${at ? translateTemplate('{page}쪽', { page: at }) : ''}</span>${title ? html`<span class="pv-fig-t">${title}</span>` : ''}</span>\
<span class="pv-t"><span class="pv-s pv-none">${translate('이 쪽은 판정을 받지 않습니다')}</span></span>`,
  );
  placePanel();
  flashOnArrival(at);
}
// The title the map gives page `page` of a figure document, whole ('' for none, or for a view-only PDF, which has no
// map).
function quietPageTitle(page: number): string {
  const facts = META && isFigureKind(META.kind) && Array.isArray(META.pages) ? META.pages[page - 1] : null;
  return facts && facts.title ? String(facts.title) : '';
}
// Whether the panel shows another page than the one under the reading line (at, verdict or none). Under the pages:
// never.
function isPanelStale(at: number) {
  const panel = document.getElementById('pv-panel');
  return IS_BESIDE_PAGES && !!panel && panel.dataset.page !== String(at);
}
// The panel is about to show another page than the one it shows: what the person has on it stays with the page they
// left. An open reason is moved on from as the reading page leaves it (leaveReason), and a focus on a control goes to
// the PDF area, as one on a left line's does (moveFocusOffPage). This must come before the filling: the morph keeps the
// element and hands it to the new page, so Enter or Space on '채택' would press the next page's word, and a control
// that goes would leave the focus on nothing.
function leavePanelPage(panel: HTMLElement, at: number) {
  if (panel.dataset.page === String(at)) return;
  if (REASON_SESSION && REASON_SESSION.seen && REASON_SESSION.page !== at) leaveReason();
  const active = document.activeElement;
  if (!!active && panel.contains(active)) searchToPage();
}
// The pin a save chip is for (its notice's), 0 for none.
function pinOfChip(chip: HTMLElement): number {
  let pin = 0;
  NOTICES.forEach((notice) => {
    if (notice.el === chip) pin = notice.pin || 0;
  });
  return pin;
}
// The panel's place: --pv-panel-gap right of the widest page on the reading page's axis (page 1 before there is one) -
// one place for pages of every width - its top at the PDF area's top padding, where #pv-panel-at sticks: it stands at
// the column's end, and the inset from the bottom of what a sticky box may use (the area less its padding) to that top
// pulls it up, so its height stays nothing. Taller than the area shows (a short window, a long conflict note in the
// popover) - or reaching down to a card over the area (findPanelFoot) - the panel scrolls inside (.pv-tall). Only then:
// a scroller clips what stands outside it, the pressed word's context under the panel, and that context's box would
// bring a scroll bar with it. Once a frame with stickReadingLine.
function placePanel() {
  const panel = document.getElementById('pv-panel'),
    at = document.getElementById('pv-panel-at');
  if (!panel || !at || !IS_BESIDE_PAGES) return;
  const area = $('#left'),
    areaRect = area.getBoundingClientRect(),
    style = getComputedStyle(area);
  const page = Number(panel.dataset.page) || pageUnderReadingLine() || 1,
    pageElement = document.getElementById('p' + page) || document.getElementById('p1');
  if (!pageElement) return;
  const paddingTop = parseFloat(style.paddingTop),
    inset = Math.max(0, area.clientHeight - paddingTop - parseFloat(style.paddingBottom)) + 'px';
  if (at.style.bottom !== inset) at.style.bottom = inset;
  const rect = pageElement.getBoundingClientRect(),
    right = rect.left + (rect.width + pageWidth(widestPagePoints(), PAGE_SCALE)) / 2;
  const x =
    Math.round(
      Math.min(right + PANEL_GAP, areaRect.left + area.clientWidth - PANEL_WIDTH) - at.getBoundingClientRect().left,
    ) + 'px';
  if (panel.style.left !== x) panel.style.left = x;
  const foot = findPanelFoot(
    areaRect.top + paddingTop,
    areaRect.top + area.clientHeight,
    at.getBoundingClientRect().left + parseFloat(x),
  );
  const room = Math.max(0, Math.floor(foot - areaRect.top - paddingTop - PANEL_GAP)),
    was = panel.classList.contains('pv-tall'),
    tall = (was ? panel.scrollHeight + 2 : panel.offsetHeight) > room,
    height = tall ? room + 'px' : '';
  if (tall !== was) panel.classList.toggle('pv-tall', tall);
  if (panel.style.maxHeight !== height) panel.style.maxHeight = height;
}
// How far down the panel may reach, in the window's px: the PDF area's bottom (bottom), or the top of a card laid over
// the area's right side under the panel - with the pin panel closed its tool bar, a banner and the status line float at
// the area's bottom right (side-panel.css) - whichever is higher, so a tall panel scrolls above them. Over its bottom,
// the status line's hint would cover the reason field's last line and its focus ring. top: the panel's top; left: its
// left edge.
const OVER_AREA_IDS = ['bar2', 'banner', 'status-wide'];
function findPanelFoot(top: number, bottom: number, left: number): number {
  let foot = bottom;
  for (const id of OVER_AREA_IDS) {
    const element = document.getElementById(id);
    if (!element || !element.getClientRects().length) continue;
    const rect = element.getBoundingClientRect();
    if (rect.height && rect.left < left + PANEL_WIDTH && rect.right > left && rect.top > top && rect.top < foot)
      foot = rect.top;
  }
  return foot;
}
// The panel's line is laid out in rows (.pv-stack: the name, the words, the state, the reason) and never measured for
// one row: there is room for each part's whole width, so nothing gives way. Its save chip and the reason popover stand
// in its flow under the state (verdict-panel.css): the words above never move.
function fitPanel(panel: HTMLElement) {
  panel.classList.remove(
    'pv-tight',
    'pv-early-out',
    'pv-t-kept',
    'pv-chip-short',
    'pv-chip-bare',
    'pv-chip-wait',
    'pv-kw',
  );
  panel.classList.add('pv-stack');
  panel.style.removeProperty('--pv-t-h');
  panel.style.removeProperty('--pv-chip-r');
  panel.style.removeProperty('--pv-chip-y');
  panel.style.width = '';
  panel.style.marginLeft = '';
  const group = panel.querySelector(':scope>.vd-btns');
  if (group) fitWrappedWords(group);
  keepFocusOnLine([panel]);
}
// Brings page `page` to the reading place: its top at the PDF area's top padding when the page reaches past the reading
// line (readingDepth), else centred on that line - so the reading page is that page. smooth: a glide (a card's [보기]).
function bringPage(page: number, smooth?: boolean) {
  const at = bringScrollTop(page);
  if (at === null) return;
  if (smooth) {
    glideTo(at);
    arrivalWatch(() => bringScrollTop(page));
  } else {
    endJumpForScroll();
    $('#left').scrollTop = at;
  }
}
/** The scrollTop of that reading place, or null without the page. */
function bringScrollTop(page: number): number | null {
  const area = $('#left'),
    pageElement = document.getElementById('p' + page);
  if (!pageElement) return null;
  const areaRect = area.getBoundingClientRect(),
    rect = pageElement.getBoundingClientRect(),
    pad = parseFloat(getComputedStyle(area).paddingTop),
    depth = readingDepth(area);
  const top = rect.height > depth - pad + 24 ? pad : depth - rect.height / 2;
  return area.scrollTop + rect.top - areaRect.top - top;
}

// ---------------- The summary under each page
// The summary's words: what its row says, for its name.
function summaryLabel(page: number, list: Pin[] | undefined) {
  const cur = list && list[0],
    key = cur && verdictOf(cur);
  return (
    pageLineName(page).id +
    ' · ' +
    (cur && key
      ? translate('판정') + ' #' + cur.id + ' ' + verdictLabel(key) + ' · ' + verdictStateWord(cur)
      : translate('판정 없음'))
  );
}
// '6쪽 · PL17 · 판정 #7 채택 · 처리 대기' (or '판정 없음') under every page that takes a verdict, and '초안 있음' where
// a reason draft waits for that page - a line would mark it, and the panel shows only the reading page: one row of one
// height whatever it says, so neither a verdict changing it nor the reading page changing moves the pages. A press
// brings that page to the panel (goToSummaryPage). Not a Tab stop - the keyboard has the panel, and PageDown brings the
// next page to it.
function summaryHtml(page: number, list: Pin[] | undefined) {
  const cur = list && list[0],
    key = cur && verdictOf(cur),
    sep = html`<span class="pv-sep" aria-hidden="true">·</span>`;
  const state =
    cur && key
      ? html`${translate('판정')} #${cur.id} <b class="vd-w" translate="no">${verdictLabel(key)}</b>${sep}${verdictStateWord(cur)}`
      : html`<span class="pv-none">${translate('판정 없음')}</span>`;
  const ownDraft = cur && canCancelVerdict(cur) ? getDraft(DOC, cur.id) : null,
    draft =
      !!getDraft(DOC, 'p' + page) || (!!ownDraft && !!cur && ownDraft.text.trim() !== String(cur.note || '').trim());
  return html`<span class="pv-sum-id" translate="no">${pageLineName(page).id}</span>${sep}<span class="pv-sum-s">${state}${draft ? html`${sep}<span class="pv-sum-draft">${translate('초안 있음')}</span>` : ''}</span>`;
}
// Draws (beside the pages) or takes away (under them) every page's summary, after its page. New rows are watched for
// being far from the view (watchFarLines: a far row is skipped like a far line).
function drawSummaries(map: Map<number, Pin[]>) {
  const made: HTMLElement[] = [];
  $$('#doc .pgw').forEach((block) => {
    const page = Number((block as HTMLElement).dataset.page) || 0;
    let summary = block.querySelector(':scope>.pv-sum') as HTMLElement | null;
    if (!IS_BESIDE_PAGES || !pageTakesVerdict(page)) {
      if (summary) summary.remove();
      return;
    }
    if (!summary) {
      summary = document.createElement('button');
      summary.setAttribute('type', 'button');
      summary.className = 'pv-sum';
      summary.tabIndex = -1;
      summary.dataset.act = 'pv-sum';
      summary.dataset.page = String(page);
      block.appendChild(summary);
      made.push(summary);
    }
    const markup = summaryHtml(page, map.get(page));
    if (summary.dataset.t !== markup.text) {
      summary.dataset.t = markup.text;
      setHtml(summary, markup);
    }
    const say = translateTemplate('{state} · 판정 패널로', { state: summaryLabel(page, map.get(page)) });
    summary.setAttribute('aria-label', say);
    summary.dataset.tipPress = say;
  });
  if (made.length && typeof IntersectionObserver !== 'undefined') watchFarLines(made, $('#left').clientHeight);
  markReadingSummary();
}
// The reading page's summary is bold (.on): the page the panel shows - a weight, never a height.
function markReadingSummary() {
  const readingPage = String(IS_BESIDE_PAGES ? READING_LINE_PAGE || 0 : 0);
  $$('#doc .pv-sum.on').forEach((element) => {
    if ((element as HTMLElement).dataset.page !== readingPage) element.classList.remove('on');
  });
  const summary = document.querySelector('#doc .pv-sum[data-page="' + readingPage + '"]');
  if (summary) summary.classList.add('on');
}
// A press on page `page`'s summary: the page comes to the reading place, the panel shows it at once, and the focus goes
// to the panel's pressed word, else its first (focusLine); the panel flashes.
function goToSummaryPage(summary: HTMLElement) {
  const page = Number(summary.dataset.page) || 0;
  if (!document.getElementById('p' + page)) return;
  noteCameFrom(summary);
  bringPage(page);
  stickReadingLine();
  const panel = document.getElementById('pv-panel');
  if (!panel || panel.dataset.page !== String(page)) return;
  focusLine(page);
  flashPanel(panel);
}
// ---------------- A jump's glide
// A jump to a far page (the outline, the page list, a card's [보기]) glides past every page between, and the digits and
// Enter wait meanwhile (isAutoScrolling). The panel keeps the page it shows and is filled once, where the jump lands:
// filled for every page passed it would change many times a second. The reading page it shows (READING_LINE_PAGE), the
// bold summary, an open reason and the keys' page wait with it; the section strip names the pages passed.
// stickReadingLine asks: the page held, or 0 when nothing is (under the pages, at rest, a panel that names no page).
// The glide's end - its scrollend, else the guard's own end - draws the panel again, so at rest the panel, the section
// strip and the keys name one page.
let HOLD_TIMER: ReturnType<typeof setTimeout> | undefined = undefined;
function heldPanelPage() {
  if (!IS_BESIDE_PAGES || !isAutoScrolling()) return 0;
  const panel = document.getElementById('pv-panel'),
    page = panel ? Number(panel.dataset.page) || 0 : 0;
  if (!page) return 0;
  clearTimeout(HOLD_TIMER);
  HOLD_TIMER = setTimeout(
    stickSoon,
    Math.min(1000, Math.max(0, (HAS_SCROLLEND ? 1000 : 160) - (performance.now() - LAST_SCROLL_AT)) + 16),
  );
  return page;
}
$('#left').addEventListener('scrollend', () => {
  if (IS_BESIDE_PAGES) stickSoon();
}); // after verdict/flow-line.ts's, which ends the guard
// The reading page with a line as the lines are drawn (drawPageVerdicts): the held one while a glide holds the panel -
// a list read again on the way would fill it with a page passed - else the page under the reading line
// (readingPageWithLine).
function heldReadingPage() {
  const held = heldPanelPage();
  return held ? (pageTakesVerdict(held) ? held : 0) : readingPageWithLine();
}
// The panel flashes for a card's [보기] once it shows page `page`: at once when it does, else when a glide lands and
// fills it (flashOnArrival) - flashed as the glide begins, it would light the page being left and be over before the
// landing. The wait is bounded (FLASH_WAIT_MS): a hand that takes the pages over and stays on the page shown fills
// nothing, and a later visit to the card's page must not flash.
let FLASH_WAIT = { page: 0, until: 0 };
const FLASH_WAIT_MS = 3000;
function flashPanelOn(page: number) {
  const panel = document.getElementById('pv-panel');
  FLASH_WAIT = { page: 0, until: 0 };
  if (panel && panel.dataset.page === String(page)) {
    flashPanel(panel);
    return;
  }
  FLASH_WAIT = { page, until: performance.now() + FLASH_WAIT_MS };
}
// The panel was filled with page `page` (fillPanel): the first filling at rest after a flash was asked for ends the
// wait, and flashes if it is that page (a hand that took the pages elsewhere lands on another).
function flashOnArrival(page: number) {
  const waiting = FLASH_WAIT;
  if (!waiting.page || isAutoScrolling()) return;
  FLASH_WAIT = { page: 0, until: 0 };
  const panel = document.getElementById('pv-panel');
  if (waiting.page === page && performance.now() < waiting.until && panel) flashPanel(panel);
}
function flashPanel(panel: HTMLElement) {
  panel.classList.remove('flash');
  void panel.offsetWidth;
  panel.classList.add('flash');
  clearTimeout(panel._flT);
  panel._flT = setTimeout(() => panel.classList.remove('flash'), 1200);
}
// ---------------- Keys the panel needs of its own
// The panel stands after the pages in the DOM, so what stands on the reading page comes by hand. Its Tab stops: its
// marks.
function markStops(page: number): HTMLElement[] {
  const block = document.querySelector('#doc .pgw[data-page="' + page + '"]');
  return block ? ([...block.querySelectorAll(TABBABLE)].filter(isTabStop) as HTMLElement[]) : [];
}
// Tab from the reading page's last mark, or from a summary a person went back to, goes to the panel: the DOM's next
// stop is a later page's mark, whose focus would scroll the pages there.
window.addEventListener('keydown', (event) => {
  if (
    event.key !== 'Tab' ||
    event.shiftKey ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.defaultPrevented ||
    !IS_BESIDE_PAGES
  )
    return;
  const active = document.activeElement as HTMLElement | null,
    readingPage = readingPageWithLine(),
    marks = readingPage ? markStops(readingPage) : [];
  if (!active || !(active === marks[marks.length - 1] || active.classList.contains('pv-sum'))) return;
  const first = [...ensurePanel().querySelectorAll(TABBABLE)].find(isTabStop) as HTMLElement | undefined;
  if (first) {
    event.preventDefault();
    first.focus({ preventScroll: true });
  }
});
// Esc on a control of the panel hands the focus to the PDF area: from there the page keys and Tab work as anywhere on
// the pages. A confirm word's Esc lets it go first, and the reason popover's Esc is its own.
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || event.defaultPrevented || !IS_BESIDE_PAGES) return;
  const active = document.activeElement;
  if (!active || !active.closest || !active.closest('#pv-panel') || active.closest('.pv-pop')) return;
  event.preventDefault();
  searchToPage();
});
// A tall panel (.pv-tall) scrolls inside. A control the keyboard focuses there comes whole into its view, focus ring
// and all: the reason popover's Tab loop focuses without scrolling (verdict/flow-reason.ts), which would leave its
// first word and last control out of sight; the browser's own Tab scrolls only the control's edge to the panel's, which
// cuts the ring; and the popover's rows change as the focus moves (the field's keys row), after the browser scrolled. A
// press is left where it is: it is in view, and moving the panel under the pointer would put the caret of a click in
// the field somewhere else.
function revealFocused() {
  const panel = document.getElementById('pv-panel'),
    active = document.activeElement;
  if (
    !panel ||
    !IS_BESIDE_PAGES ||
    !panel.classList.contains('pv-tall') ||
    !(active instanceof HTMLElement) ||
    !panel.contains(active) ||
    !active.matches(':focus-visible') ||
    document.documentElement.dataset.input === 'pointer'
  )
    return;
  const style = getComputedStyle(active),
    margin = (parseFloat(style.outlineWidth) || 0) + Math.max(0, parseFloat(style.outlineOffset) || 0) + RING_ROOM,
    panelRect = panel.getBoundingClientRect(),
    rect = active.getBoundingClientRect();
  const top = panelRect.top + panel.clientTop,
    bottom = top + panel.clientHeight;
  if (rect.top - margin < top || rect.height + 2 * margin > panel.clientHeight)
    panel.scrollTop -= top - (rect.top - margin);
  else if (rect.bottom + margin > bottom) panel.scrollTop += rect.bottom + margin - bottom;
}
const RING_ROOM = 2; // px kept clear past a revealed control's focus ring
$('#doc').addEventListener('focusin', (event: FocusEvent) => {
  const target = event.target as HTMLElement | null;
  if (target && target.closest && target.closest('#pv-panel.pv-tall')) requestAnimationFrame(revealFocused);
});
// The PDF area's width changes with no window resize (the outline folded or dragged): the room is read again.
if (typeof ResizeObserver !== 'undefined')
  new ResizeObserver(() => {
    if (LAYOUT === LAYOUT_MODE.WIDE && pageVerdictsOn()) stickSoon();
  }).observe($('#left'));
// Sets BUILD_READING_PAGE, which this module declares, for another module that changes it (ADR-0042 D1); answers the
// value.
function setBuildReadingPage<Value extends typeof BUILD_READING_PAGE>(value: Value): Value {
  BUILD_READING_PAGE = value;
  return value;
}
export {
  HELD_READING_PAGE,
  BUILD_READING_PAGE,
  IS_BESIDE_PAGES,
  bringPage,
  flashPanelOn,
  heldReadingPage,
  markStops,
  ensurePanel,
  fillPanel,
  fitPanel,
  removePanel,
  heldPanelPage,
  placePanel,
  isPanelStale,
  applyBeside,
  redrawOnBesideChange,
  settleBesideTurn,
  startBesideTurn,
  finishBesideTurn,
  shouldStandBeside,
  goToSummaryPage,
  markReadingSummary,
  drawSummaries,
  setBuildReadingPage,
};
