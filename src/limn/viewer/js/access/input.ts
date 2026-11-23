// ------------------------------------------------ Access management: keeping Tab inside the open dialog
import { $, TABBABLE, isTabStop } from '../platform/dom.ts';

// Tab stays in the open access dialog, a modal: from its last control it comes back to its first, and Shift+Tab from
// its first (or from the dialog itself) goes to its last. Left to the browser, Tab would leave it for the browser's own
// toolbar and the page's focus would fall to <body> while the dialog stays open - and a draw of the screen, which makes
// its controls anew, leaves the focus there more often than not (the same as the Trash, pins/view-cards.ts).
$('#access').addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
  const dialog = $('#access');
  const all = [...dialog.querySelectorAll(TABBABLE)].filter(isTabStop),
    focused = document.activeElement,
    index = focused instanceof HTMLElement ? all.indexOf(focused) : -1;
  const to = !all.length
    ? null
    : event.shiftKey
      ? index === 0 || focused === dialog
        ? all[all.length - 1]
        : null
      : index === all.length - 1
        ? all[0]
        : null;
  if (to) {
    event.preventDefault();
    to.focus();
  }
});
