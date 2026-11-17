// ------------------------------------------- Multiple documents - list/tabs/links (docs/handbook/domain.md §여러 문서)
import {
  DOC,
  DOCS,
  COARSE_POINTER_QUERY,
  OPEN_ALL,
  imeKey,
  isFigureKind,
  setDefaultDoc,
  setDocs,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { LANG, translateTemplate, translate } from '../platform/i18n.ts';
import { prefs } from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import { hideTip } from '../platform/tooltip.ts';
import { drawDocsMenu, drawPos, switchDoc } from './flow-switch.ts';
import type { Html } from '../platform/markup.ts';
import { $, $$ } from '../platform/dom.ts';
import { docInfo, pdoc } from './state.ts';
import { pageNavigation } from './state-seams.ts';

function multiDoc() {
  return DOCS.length > 1;
}
function hashDoc() {
  const match = /(?:^#|[#&])doc=([a-z0-9-]{1,24})(?:&|$)/.exec(location.hash || '');
  return match ? match[1] : null;
}
// Puts #doc=<key> in the address (several documents only) without a new history entry, keeping the entry's state - the
// back layer's pushed entry must stay recognizable after a document switch.
function setHash(doc: string | null) {
  if (!multiDoc()) return;
  const hash = '#doc=' + doc;
  if (location.hash !== hash) history.replaceState(history.state, '', location.pathname + location.search + hash);
}
// The document shown first: URL hash (link sharing/reload) > the last document viewed on this device > the first
// document.
function initialDoc() {
  const fromHash = hashDoc();
  if (fromHash && docInfo(fromHash)) return fromHash;
  const last = prefs().lastDoc;
  if (last && docInfo(last)) return last;
  return DOCS.length ? DOCS[0].key : null;
}
async function loadDocs() {
  try {
    const answer = (await api('/api/docs', { what: '문서 목록', silent: true })).data;
    setDocs(Array.isArray(answer.docs) ? answer.docs : []);
    setDefaultDoc(answer.default || (DOCS[0] && DOCS[0].key) || 'main');
  } catch (error) {
    setDocs([]);
  }
  document.body.classList.toggle('docs-multi', multiDoc());
  $('#all-docs').hidden = !multiDoc();
}
function docCount(doc: string) {
  return OPEN_ALL.filter((pin) => pdoc(pin) === doc).length;
}
// A document's build state in the documents lists: a spinner while it builds, else a dot when its manuscript is newer
// than its PDF; null for neither.
function docState(entry: DocEntry) {
  return entry.building
    ? html`<span class="spin" aria-label="빌드 중"></span>`
    : entry.stale_build
      ? html`<span class="ddot" aria-label="원고 수정됨"></span>`
      : null;
}
// A document's marks in the documents list: its build state (docState), view-only 'PDF', figure '그림', and its
// open-pin count.
function docBadge(entry: DocEntry) {
  const openCount = docCount(entry.key);
  const pdf = entry.view_only ? html`<span class="badge dvo" aria-label="보기 전용">PDF</span>` : '';
  const figure = isFigureKind(entry.kind)
    ? html`<span class="badge dfig" aria-label="${translate('그림 문서')}">${translate('그림')}</span>`
    : '';
  return html`${docState(entry)}${pdf}${figure}<span class="badge badge-secondary dcnt${openCount ? '' : ' z'}" aria-label="${translateTemplate('열린 핀 {n}', { n: openCount })}">${openCount}</span>`;
}
// A document link's description: name, path, what kind of document it is, and its build state. The link is user text
// (translate="no", the name), so the UI words are translated here.
function docTip(entry: DocEntry) {
  return (
    entry.name +
    ' · ' +
    entry.path +
    (entry.view_only ? translate(' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)') : '') +
    (isFigureKind(entry.kind)
      ? ' · ' + translate('그림 문서(드래그하면 요소와 그 요소를 그린 코드 줄을 찾습니다)')
      : '') +
    (entry.building
      ? translate(' · 빌드 중')
      : entry.stale_build
        ? translate(' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])')
        : '')
  );
}
// The marks of a document link: its name (.lbl, trimmed to its cap height by CSS as the view tabs' words) and page
// count.
function docLinkInner(entry: DocEntry) {
  const count = entry.n_pages
    ? html`<span class="doc-link-count">${translateTemplate('{n}쪽', { n: entry.n_pages })}</span>`
    : '';
  return html`<span class="lbl">${entry.name}</span>${count}`;
}
// What a link's or a popover row's inside was last drawn from, so a redraw that changes nothing writes nothing.
const DOC_DRAWN: WeakMap<Element, string> = new WeakMap();
// Sets the inside of an element to `markup`, drawn from key - unless it was drawn from key already. The element itself
// stays: one that has the focus keeps it, and no focusout or focusin is sent.
function docInner(element: Element, markup: Html, key: string) {
  if (DOC_DRAWN.get(element) === key) return;
  setHtml(element, markup);
  DOC_DRAWN.set(element, key);
}
// Sets attribute `name` of an element to `value` when it is not that already (an unchanged write still reaches the
// MutationObservers).
function setAttributeIfChanged(element: Element, name: string, value: string) {
  if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}
// Draws the document choosers: the select, the nav bar's links, the phone's position button (drawPos), an open
// navigation sheet's rows and an open documents popover's. A document's name is user text (translate="no"); the UI
// words beside it (build state, page count, the description) are translated here. With the same documents in the same
// order (a redraw by polling) each link is updated in place - only what changed - so a link or [+N] (#doc-more, after
// the links) that has the focus keeps the same node; otherwise the links are made again in front of [+N] and a link
// that had the focus gives it to its document's new link. Then the row is fitted (docFit).
function drawDocTabs() {
  const box = $('#doc-select');
  setHtml(
    box,
    html`${DOCS.map((entry) => html`<option translate="no" value="${entry.key}">${entry.name}${entry.building ? translate(' · 빌드 중') : entry.stale_build ? translate(' · 원고 수정됨') : ''}</option>`)}`,
  );
  if (DOC) box.value = DOC;
  const row = $('#doc-links'),
    more = $('#doc-more'),
    had = document.activeElement as HTMLElement | null,
    old = [...row.querySelectorAll(':scope>[data-doc]')] as HTMLElement[];
  const same = old.length === DOCS.length && old.every((link, index) => link.dataset.doc === DOCS[index].key);
  let was: string | null | undefined = null;
  if (!same) {
    was = had && had !== more && row.contains(had) ? had.dataset.doc : null;
    old.forEach((link) => link.remove());
    const links = document.createElement('div');
    setHtml(
      links,
      html`${DOCS.map((entry) => html`<button translate="no" data-act="doc" data-doc="${entry.key}"></button>`)}`,
    );
    more.before(...links.children);
  }
  ([...row.querySelectorAll(':scope>[data-doc]')] as HTMLElement[]).forEach((link, index) => {
    const entry = DOCS[index];
    setAttributeIfChanged(link, 'aria-current', entry.key === DOC ? 'page' : 'false');
    setAttributeIfChanged(link, 'title', docTip(entry));
    docInner(link, docLinkInner(entry), entry.name + '\u0001' + (entry.n_pages || ''));
  });
  drawPos();
  docFit();
  const back = was
    ? ([...row.querySelectorAll(':scope>[data-doc]')] as HTMLElement[]).find(
        (link) => link.dataset.doc === was && !link.hidden,
      )
    : null;
  if (back) back.focus({ preventScroll: true });
  if ($('#nav-sheet').open) drawDocsMenu();
  if (!$('#doc-pop').hidden) drawDocMenu();
}

// ---- The document row's fit (docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Which links the row shows, as indices into `widths` (the links' widths; gap the row's gap): every one when they all
// fit room, else the first shownCount in order with [+N] after them (moreWidth(count): its width saying that count),
// shownCount as large as fits, and the current document's link (index `current`, -1 for none) always among them: when
// it would be hidden it takes the last place shown. None ([]) when not even one link and [+N] fit: the row is then a
// single chooser (docFit). Pure.
function docTabsShown(
  widths: number[],
  gap: number,
  current: number,
  room: number,
  moreWidth: (count: number) => number,
) {
  const count = widths.length,
    all = widths.map((_, index) => index),
    width = (indices: number[]) =>
      indices.reduce((sum, index) => sum + widths[index], 0) + gap * Math.max(0, indices.length - 1),
    fits = (x: number) => x <= room + 0.01;
  if (fits(width(all))) return all;
  for (let shownCount = count - 1; shownCount >= 1; shownCount--) {
    const shown = all.slice(0, shownCount);
    if (current >= shownCount) shown[shownCount - 1] = current;
    if (fits(width(shown) + gap + moreWidth(count - shownCount))) return shown;
  }
  return [];
}
// How the chooser stands when no link and [+N] fit together: 'name' - the current document's name, shortened to an
// ellipsis as room needs - when room holds the whole name or at least the chooser's own width (chrome: padding, gap,
// chevron) and three em of name; else 'icon'. Pure.
function docChooser(room: number, full: number, chrome: number, fontSize: number) {
  return room + 0.01 >= Math.min(full, chrome + 3 * fontSize) ? 'name' : 'icon';
}
let DOC_FIT = ''; // the row's last fit: a measure that changes nothing writes nothing and re-fits nothing
// Fits the nav bar's document row to the room the bar leaves it, down a ladder in which nothing is ever cut: (a) as
// many whole links as fit, in DOCS order, the current one always among them, and [+N] for the N left out (docTabsShown)
// - or every link and no button; (b) when not even the current link and [+N] fit: one chooser, [+N]'s button
// (#doc-more, data-fit="name"), saying the current document's name - ellipsis as needed - and opening the same popover;
// (c) when (b) could not show three em of the name: the same chooser as an icon (data-fit="icon"). The room is the
// bar's content width less every other control at its own width and the gaps between them, three of them counted as
// they would stand: the search at its folded magnifier (the field gives way before the links, as it gives way before
// every neighbour - searchFit takes what the row leaves), and at their whole widths the paper's name (up to its
// max-width: the links give way before it is shortened) and the short band's status line (it gives way last). The row's
// least width is its content's (frame.css), so below (c) the bar's neighbours give way instead, each only after the row
// is down to its icon: the paper's name shortens (it may shrink), and the short band's status line - which never
// shrinks, as the search measures it whole - drops its words, whole or not at all: a stub of one or two letters would
// say less than nothing (its icon and action stay, and its spoken label is its own node). Measured with every link
// shown, then each hidden or shown whole. Nothing that has the focus is hidden to be measured (a hidden control loses
// it): the links are measured all shown, the button where it stands; a link or the button that has the focus and is
// left out gives it to the button or the current link. When the fit changes the search is fitted again; an open popover
// is placed again under its button (which may have moved), or shuts when the button has gone. Where the row is not
// drawn (the phone, one document) nothing is.
function docFit() {
  const row = $('#doc-links'),
    more = $('#doc-more'),
    bar = $('#doc-nav'),
    label = more.querySelector('.lbl') as HTMLElement,
    tabs = [...row.querySelectorAll(':scope>[data-doc]')] as HTMLElement[],
    pixels = (value: string) => parseFloat(value) || 0,
    had = document.activeElement;
  let fit = '',
    drop = false;
  const statusLine = $('#status');
  statusLine.classList.remove('st-words-off'); // measured with its words; dropped again below when they do not fit
  if (row.getClientRects().length && tabs.length > 1) {
    const barStyle = getComputedStyle(bar),
      rowStyle = getComputedStyle(row);
    // its whole width: laid out for the moment as it would stand unshrunk (up to its max-width), to the fraction of a
    // pixel
    const whole = (control: HTMLElement) => {
      control.style.flex = 'none';
      const x = control.getBoundingClientRect().width;
      control.style.flex = '';
      return x;
    };
    let used = 0,
      controls = 0;
    for (const control of [...bar.children] as HTMLElement[]) {
      if (control === row || !control.getClientRects().length) continue;
      const style = getComputedStyle(control);
      controls++;
      if (control.id === 'doc-search') {
        used += pixels(getComputedStyle($('#search-open')).width);
        continue;
      } // its margin is the bar's one flexible gap
      if (control.id === 'paper-identity' || control.id === 'status') used += whole(control);
      else used += control.getBoundingClientRect().width;
      if (!control.matches('#nav-page,#nav-side')) used += pixels(style.marginLeft) + pixels(style.marginRight);
    } // those two stand after the flexible gap
    const room =
      bar.clientWidth -
      pixels(barStyle.paddingLeft) -
      pixels(barStyle.paddingRight) -
      pixels(barStyle.columnGap) * controls -
      used -
      pixels(rowStyle.marginLeft) -
      pixels(rowStyle.marginRight);
    tabs.forEach((link) => {
      link.hidden = false;
    });
    const moreStyle = getComputedStyle(more),
      // the button's width counts its margins (frame.css)
      moreMargins = pixels(moreStyle.marginLeft) + pixels(moreStyle.marginRight);
    const widths = tabs.map((link) => link.getBoundingClientRect().width),
      gap = pixels(rowStyle.columnGap),
      seen = new Map(),
      was = more.hidden;
    const showAs = (mode: string, text: string) => {
      more.dataset.fit = mode;
      label.textContent = text;
      more.style.maxWidth = '';
    };
    const width = (mode: string, text: string) => {
      showAs(mode, text);
      more.hidden = false;
      const x = more.getBoundingClientRect().width + moreMargins;
      more.hidden = was;
      return x;
    };
    const moreWidth = (count: number) => {
      if (!seen.has(count)) seen.set(count, width('more', '+' + count));
      return seen.get(count);
    };
    const currentIndex = Math.max(
        0,
        tabs.findIndex((link) => link.dataset.doc === DOC),
      ),
      currentEntry = docInfo(tabs[currentIndex].dataset.doc || '') || DOCS[currentIndex];
    const shown = docTabsShown(widths, gap, currentIndex, room, moreWidth),
      hiddenCount = tabs.length - shown.length;
    let mode = 'more',
      cap = '';
    if (!shown.length) {
      const full = width('name', currentEntry.name),
        chrome = width('name', '');
      mode = docChooser(room, full, chrome, pixels(getComputedStyle(label).fontSize));
      if (mode === 'name' && full > room) cap = Math.floor(room - moreMargins) + 'px';
      drop = mode === 'icon' && bar.contains(statusLine) && width('icon', '') > room + 0.5;
    } // the short band's status line gives way: all its words
    tabs.forEach((link, index) => {
      link.hidden = !shown.includes(index);
    });
    showAs(mode, mode === 'more' ? '+' + hiddenCount : mode === 'name' ? currentEntry.name : '');
    more.style.maxWidth = cap;
    if (mode === 'more') {
      more.setAttribute('aria-label', translateTemplate('+{n} 문서 더 보기', { n: hiddenCount }));
      more.removeAttribute('title');
    } else {
      more.setAttribute(
        'aria-label',
        currentEntry.name + ' — ' + translateTemplate('문서 {n}개 중 고르기', { n: DOCS.length }),
      );
      more.setAttribute('title', docTip(currentEntry));
    }
    more.hidden = mode === 'more' && !hiddenCount;
    fit = [mode, shown.map((index) => tabs[index].dataset.doc).join(), hiddenCount, cap, currentEntry.name, drop].join(
      '|',
    );
  } else {
    tabs.forEach((link) => {
      link.hidden = false;
    });
    more.hidden = true;
  }
  statusLine.classList.toggle('st-words-off', drop);
  const lost =
    had instanceof HTMLElement && (row.contains(had) ? had.hidden : !more.hidden ? false : $('#doc-pop').contains(had));
  if (more.hidden) closeDocMenu(false);
  if (lost) {
    const to = more.hidden ? tabs.find((link) => link.getAttribute('aria-current') === 'page') : more;
    if (to) to.focus({ preventScroll: true });
  }
  if (fit !== DOC_FIT) {
    DOC_FIT = fit;
    pageNavigation().fitSearch();
  }
  placeDocMenu();
}
// Re-fits once a frame when the bar or a control beside the row changes size (the window, the pin panel, the page
// count, the status line in the short band, the search) - never on the row's own size, which the fit sets - and when a
// font arrives.
let DOC_FIT_FRAME = 0;
function docFitSoon() {
  if (!DOC_FIT_FRAME)
    DOC_FIT_FRAME = requestAnimationFrame(() => {
      DOC_FIT_FRAME = 0;
      docFit();
    });
}
if (window.ResizeObserver) {
  const observer = new ResizeObserver(docFitSoon);
  observer.observe($('#doc-nav'));
  observer.observe($('#status'));
  for (const control of $$('#doc-nav>*')) if (control.id !== 'doc-links') observer.observe(control);
}
document.fonts.addEventListener('loadingdone', docFit);
// The row is a scroll box only for how it is painted (frame.css): it never scrolls. The current link's bar reaches 1px
// under it, which a browser lets keys scroll after a press in the row (moving the links up 1px) - undone at once - and
// for which Firefox gives the row a Tab stop of its own, a ring round all the links (index.html takes it out of the Tab
// order).
$('#doc-links').addEventListener(
  'scroll',
  (event: Event) => {
    const row = event.currentTarget as HTMLElement;
    if (row.scrollTop || row.scrollLeft) {
      row.scrollTop = 0;
      row.scrollLeft = 0;
    }
  },
  { passive: true },
);

// ---- The documents popover ([+N] or the chooser, docs/handbook/viewer.md §문서 링크가 넘칠 때)
// Every document in DOCS order, one row each: the current one's check, the name (user text) with its build state
// (docState), the page count and, for the first nine, the Alt+number that picks it. Choosing a row is a document link's
// click (data-act "doc": switchDoc). With nine documents or more a field on top filters the rows by name or path. Draws
// the popover's rows. A redraw with the same documents in the same order (polling) updates each row in place - only
// what changed - so a focused row keeps its node and the focus, and the filter and the list's scroll stay.
function drawDocMenu() {
  const list = $('#doc-pop-list'),
    old = [...list.children] as HTMLElement[];
  if (!(old.length === DOCS.length && old.every((row, index) => row.dataset.doc === DOCS[index].key)))
    setHtml(
      list,
      html`${DOCS.map((entry) => html`<button class="dp-row" role="option" data-act="doc" data-doc="${entry.key}"></button>`)}`,
    );
  ([...list.children] as HTMLElement[]).forEach((row, index) => {
    const entry = DOCS[index],
      on = entry.key === DOC,
      state = entry.building ? 'spin' : entry.stale_build ? 'dot' : '';
    row.classList.toggle('on', on);
    setAttributeIfChanged(row, 'aria-selected', String(on));
    setAttributeIfChanged(row, 'tabindex', on ? '0' : '-1');
    docInner(
      row,
      html`<span class="dp-c">${on ? lucideIcon('check') : ''}</span><span class="dp-n"><span class="dp-t" translate="no">${entry.name}</span>${docState(entry)}</span><span class="dp-p">${entry.n_pages ? translateTemplate('{n}쪽', { n: entry.n_pages }) : ''}</span><span class="dp-k">${index < 9 ? 'Alt+' + (index + 1) : ''}</span>`,
      [entry.name, entry.n_pages || '', on, state, LANG].join('\u0001'),
    );
  });
  docMenuFilter();
}
// Shows the rows whose document's name or path holds the field's text (case folded, as the outline's search), and says
// so when none does.
function docMenuFilter() {
  const query = $('#doc-pop-in').value.trim().toLowerCase();
  let shown = 0;
  for (const row of [...$('#doc-pop-list').children] as HTMLElement[]) {
    const entry = docInfo(row.dataset.doc || '');
    row.hidden = !!query && !(entry && (entry.name + ' ' + entry.path).toLowerCase().includes(query));
    if (!row.hidden) shown++;
  }
  $('#doc-pop-none').hidden = shown > 0;
}
// Opens the popover under its button. A mouse or a keyboard gets the focus in the filter when there is one; touch - no
// keyboard comes up - and a list without it get the current document's row, scrolled into view.
function openDocMenu() {
  const pop = $('#doc-pop'),
    filter = $('#doc-pop-in');
  hideTip();
  pageNavigation().closePageList(false);
  filter.hidden = DOCS.length < 9;
  filter.value = '';
  $('#doc-more').setAttribute('aria-expanded', 'true');
  pop.hidden = false;
  drawDocMenu();
  placeDocMenu();
  const row = $('#doc-pop-list [aria-selected=true]') as HTMLElement | null;
  if (row) row.scrollIntoView({ block: 'nearest' });
  const to = !filter.hidden && !COARSE_POINTER_QUERY.matches ? filter : row || pop;
  to.focus({ preventScroll: true });
}
// Puts the open popover under its button, its left edge on the button's and inside the window by 8px, and lets it grow
// down to 8px above the window's bottom (--dp-room); its list scrolls inside that. docFit calls it after every fit, so
// the popover follows its button when the bar changes (the window, the pin panel, the outline).
function placeDocMenu() {
  const pop = $('#doc-pop'),
    more = $('#doc-more');
  if (pop.hidden) return;
  if (!more.getClientRects().length) {
    closeDocMenu(false);
    return;
  }
  const rect = more.getBoundingClientRect(),
    top = Math.round(rect.bottom) + 4,
    width = pop.offsetWidth;
  pop.style.left = Math.max(8, Math.min(Math.round(rect.left), innerWidth - 8 - width)) + 'px';
  pop.style.top = top + 'px';
  pop.style.setProperty('--dp-room', Math.max(0, innerHeight - 8 - top) + 'px');
}
// Shuts the popover; back gives the focus back to its button (Esc, a choice, Shift+Tab out of it).
function closeDocMenu(back: boolean) {
  const pop = $('#doc-pop'),
    more = $('#doc-more');
  if (pop.hidden) return;
  pop.hidden = true;
  more.setAttribute('aria-expanded', 'false');
  if (back && more.getClientRects().length) more.focus({ preventScroll: true });
}
// The button's click: opens the popover, or shuts it when it is open.
function toggleDocMenu() {
  if ($('#doc-pop').hidden) openDocMenu();
  else closeDocMenu(false);
}
// The nav bar's next stop after the popover's button, in its order (DOM order, as Tab goes): what Tab out of the
// popover lands on. Null when the button is the bar's last.
function docMenuNext() {
  const more = $('#doc-more'),
    stops = ([...$('#doc-nav').querySelectorAll('button,input,select,a[href],[tabindex]')] as HTMLElement[]).filter(
      (stop) =>
        stop === more ||
        (stop.tabIndex >= 0 &&
          !(stop as HTMLButtonElement).disabled &&
          stop.getClientRects().length > 0 &&
          getComputedStyle(stop).visibility !== 'hidden'),
    );
  return stops[stops.indexOf(more) + 1] || null;
}
// Keys: ↓ on the button opens the popover (Enter and Space are its click). In the filter ↓ goes to the current row (the
// first shown when it is filtered out) and Enter chooses the first row shown; on a row ↓/↑ move one row, Home/End to
// the ends, ↑ on the first goes back to the filter. Alt+1…9 picks that document from anywhere in the popover, the
// filter too (the shortcut is otherwise not taken inside a text field). Tab leaves the popover forward: from the filter
// to the list's row, from a row out - the popover shuts and the focus goes to the bar's next stop after the button;
// Shift+Tab goes back: from a row to the filter, from the filter (or a row with no filter) out to the button, the
// popover shut. Esc is the viewer's (main.ts): it shuts the popover with the focus on the button.
$('#doc-more').addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key === 'ArrowDown' && !event.altKey) {
    event.preventDefault();
    if ($('#doc-pop').hidden) openDocMenu();
  }
});
$('#doc-pop').addEventListener('keydown', (event: KeyboardEvent) => {
  const target = event.target as HTMLElement,
    filter = $('#doc-pop-in');
  if (imeKey(event)) return;
  const rows = ([...$('#doc-pop-list').children] as HTMLElement[]).filter((row) => !row.hidden),
    field = !filter.hidden;
  if (event.altKey && !event.ctrlKey && !event.metaKey && /^Digit[1-9]$/.test(event.code || '')) {
    const entry = DOCS[+event.code.slice(5) - 1];
    event.preventDefault();
    event.stopPropagation();
    if (entry) {
      closeDocMenu(true);
      switchDoc(entry.key);
    }
    return;
  }
  if (event.key === 'Tab' && !event.ctrlKey && !event.altKey && !event.metaKey) {
    event.preventDefault();
    if (event.shiftKey) {
      if (target !== filter && field) filter.focus();
      else closeDocMenu(true);
      return;
    }
    if (target === filter && rows.length) {
      (rows.find((row) => row.classList.contains('on')) || rows[0]).focus();
      return;
    }
    const next = docMenuNext();
    closeDocMenu(!next);
    if (next) next.focus();
    return;
  }
  if (target === filter) {
    if (event.key === 'ArrowDown' && rows.length) {
      event.preventDefault();
      (rows.find((row) => row.classList.contains('on')) || rows[0]).focus();
    } else if (event.key === 'Enter' && rows.length) {
      event.preventDefault();
      rows[0].click();
    }
    return;
  }
  const index = rows.indexOf(target);
  if (index < 0) return;
  if (event.key === 'ArrowUp' && index === 0 && field) {
    event.preventDefault();
    filter.focus();
    return;
  }
  const to = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: rows.length - 1 }[event.key];
  if (to === undefined) return;
  event.preventDefault();
  const row = rows[Math.max(0, Math.min(rows.length - 1, to))];
  row.focus();
  row.scrollIntoView({ block: 'nearest' });
});
$('#doc-pop-in').addEventListener('input', docMenuFilter);
// The focus moving to a control outside the popover and its button (a click on another control, a shortcut that moves
// it) shuts it; a press anywhere outside them shuts it too (the press still does what it does). Focus that goes nowhere
// (the window losing it) leaves it open.
$('#doc-pop').addEventListener('focusout', (event: FocusEvent) => {
  const to = event.relatedTarget as Node | null;
  if (to && !$('#doc-pop').contains(to) && !$('#doc-more').contains(to)) closeDocMenu(false);
});
document.addEventListener(
  'pointerdown',
  (event) => {
    const target = event.target as Node;
    if (!$('#doc-pop').hidden && !$('#doc-pop').contains(target) && !$('#doc-more').contains(target))
      closeDocMenu(false);
  },
  true,
);
addEventListener('resize', placeDocMenu);
export { closeDocMenu, docBadge, drawDocTabs, hashDoc, initialDoc, loadDocs, multiDoc, setHash, toggleDocMenu };
