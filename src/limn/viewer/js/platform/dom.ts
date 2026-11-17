// ------------------------------------------------ DOM lookups, escaping, icons
// $ and $$ look up the page's elements, esc() escapes text for markup (platform/markup.ts builds on it), ICONS is the
// bundled Lucide table, and typingNow() says whether a text field has the focus.
const $: PageLookup = (selector: string) => document.querySelector(selector);
const $$ = (selector: string) => Array.from(document.querySelectorAll(selector));
// Lucide icons (vendor/lucide/README.md), drawn by lucideIcon() in platform/markup.ts.
const ICONS = __LUCIDE_JSON__;
const esc = (text: unknown) =>
  String(text == null ? '' : text).replace(
    /[&<>"']/g,
    (character) =>
      (({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }) as Record<string, string>)[character],
  );
// The element an event is aimed at, or null when its target is not an element (the window, the document): a handler
// that looks for the controls around the target finds none there.
function eventElement(event: Event) {
  return event.target instanceof Element ? event.target : null;
}
// A DOM class as instanceof takes it (HTMLElement, HTMLInputElement, ...): what findElement, findMaybe and findAll check the
// elements they give against.
interface ElementClass<Found extends Element> {
  new (): Found;
  prototype: Found;
}
// The first element under scope that matches selector, which the code needs there and of that class: none, or one of
// another class, is a fault of the page, thrown as an Error that names the selector and the class.
function findElement<Found extends Element>(scope: ParentNode, selector: string, type: ElementClass<Found>): Found {
  const found = scope.querySelector(selector);
  if (found instanceof type) return found;
  throw new Error(selector + ': ' + (found ? 'a ' + found.tagName + ', not a ' : 'no ') + type.name);
}
// The first element under scope that matches selector when it is of that class, else null - for an element that is
// there only in some states (a card being edited, the drawn pages).
function findMaybe<Found extends Element>(scope: ParentNode, selector: string, type: ElementClass<Found>) {
  const found = scope.querySelector(selector);
  return found instanceof type ? found : null;
}
// Every element under scope that matches selector and is of that class, in document order; the others are left out.
function findAll<Found extends Element>(scope: ParentNode, selector: string, type: ElementClass<Found>) {
  return Array.from(scope.querySelectorAll(selector)).filter((found): found is Found => found instanceof type);
}
// The nearest of element and its ancestors that matches selector, when it is of that class, else null - the control or
// row around an event's target (eventElement).
function findClosest<Found extends Element>(element: Element, selector: string, type: ElementClass<Found>) {
  const found = element.closest(selector);
  return found instanceof type ? found : null;
}
// The nearest of an event's target and its ancestors that matches selector, when it is of that class, else null (as for
// a target that is no element, eventElement).
function eventClosest<Found extends Element>(event: Event, selector: string, type: ElementClass<Found>) {
  const target = eventElement(event);
  return target ? findClosest(target, selector, type) : null;
}
// Whether a text field has focus - a textarea, a text input or editable content - which on a touch screen means the
// keyboard is up.
function typingNow() {
  const focused = document.activeElement;
  if (!focused || focused === document.body) return false;
  if ((focused instanceof HTMLElement && focused.isContentEditable) || focused.tagName === 'TEXTAREA') return true;
  return (
    focused instanceof HTMLInputElement &&
    !/^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/i.test(focused.type || '')
  );
}
// The HTML element that has the focus, or null when none has it or it is on something else (an SVG element): what the
// code focuses again later or reads as a control.
function focusedElement() {
  const focused = document.activeElement;
  return focused instanceof HTMLElement ? focused : null;
}
// Whether an element is a control that is disabled now; an element that cannot be disabled (a link, a span) is not.
function isDisabled(element: Element) {
  return 'disabled' in element && element.disabled === true;
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
    !isDisabled(x) &&
    x.getClientRects().length > 0 &&
    !x.closest('[inert],[hidden]') &&
    getComputedStyle(x).visibility !== 'hidden'
  );
}

export {
  $,
  $$,
  ICONS,
  esc,
  eventElement,
  findElement,
  findMaybe,
  findAll,
  findClosest,
  eventClosest,
  typingNow,
  focusedElement,
  isDisabled,
  searchToPage,
  focusFell,
  focusHold,
  TABBABLE,
  isTabStop,
};
