// ------------------------------------------------ DOM lookups, escaping, icons
// $ and $$ look up the page's elements, esc() escapes text for markup (platform/markup.ts builds on it), ICONS is the
// bundled Lucide table, and typingNow() says whether a text field has the focus.
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
// Lucide icons (vendor/lucide/README.md), drawn by lucideIcon() in platform/markup.ts.
const ICONS = __LUCIDE_JSON__;
const esc = (text: unknown) =>
  String(text == null ? '' : text).replace(
    /[&<>"']/g,
    (character) =>
      (({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }) as Record<string, string>)[character],
  );
// Whether a text field has focus - a textarea, a text input or editable content - which on a touch screen means the
// keyboard is up.
function typingNow() {
  const focused = document.activeElement as HTMLInputElement;
  if (!focused || focused === document.body) return false;
  if (focused.isContentEditable || focused.tagName === 'TEXTAREA') return true;
  return (
    focused.tagName === 'INPUT' &&
    !/^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/i.test(focused.type || '')
  );
}
// Puts the focus on the PDF's scroller - where the keys then scroll - for as long as it stays there: it is not a tab
// stop and draws no ring (search.css).
function searchToPage() {
  const pdfArea = $('#left');
  pdfArea.tabIndex = -1;
  pdfArea.addEventListener('blur', () => pdfArea.removeAttribute('tabindex'), { once: true });
  pdfArea.focus({ preventScroll: true });
}
function focusFell() {
  const focused = document.activeElement;
  return !focused || focused === document.body || $('#composer').contains(focused) || $('#sel-pop').contains(focused);
}
// Focuses target without scrolling; an element that takes no focus of its own takes it for as long as it has it
// (tabindex -1, dropped on blur), as the PDF area does for a search (searchToPage).
function focusHold(target: HTMLElement) {
  if (!target.hasAttribute('tabindex')) {
    target.tabIndex = -1;
    target.addEventListener('blur', () => target.removeAttribute('tabindex'), { once: true });
  }
  target.focus({ preventScroll: true });
}
// Tab into the pages from outside them - the outline, the section strip, the panel by Shift+Tab - goes to the reading
// page's line too (its first control; its last by Shift+Tab), else to the PDF area: the DOM's next stop is the first
// page's line (or the last page's), whose focus would scroll the document there. Only a Tab across the pages' edge is
// taken - from the last stop before the PDF area (the section strip's page button, where it shows) or, by Shift+Tab,
// from the first after it (the panel's) - and that stop is found by walking out from the area to the nearest one
// (findEdgeStop), a few elements, so a Tab outside the pages never reads every focusable element of the document and
// whether it shows.
const TABBABLE = 'a[href],button,input,select,textarea,summary,[tabindex]';
// Whether an element is a stop of the Tab order now: focusable by Tab, enabled, drawn, not hidden and not in an inert
// or hidden part.
function isTabStop(x: Element | null): x is HTMLElement {
  return (
    x instanceof HTMLElement &&
    x.matches(TABBABLE) &&
    x.tabIndex >= 0 &&
    !(x as HTMLButtonElement).disabled &&
    x.getClientRects().length > 0 &&
    !x.closest('[inert],[hidden]') &&
    getComputedStyle(x).visibility !== 'hidden'
  );
}

export { $, $$, ICONS, esc, typingNow, searchToPage, focusFell, focusHold, TABBABLE, isTabStop };
