// ------------------------------------------------ DOM lookups, escaping, icons
// $ and $$ look up the page's elements, esc() escapes text for markup (platform/markup.ts builds on it), ICONS is the
// bundled Lucide table, and typingNow() says whether a text field has the focus.
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));
// Lucide icons (vendor/lucide/README.md), drawn by lucideIcon() in platform/markup.ts.
const ICONS = __LUCIDE_JSON__;
const esc = (text) =>
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

export { $, $$, ICONS, esc, typingNow, searchToPage };
