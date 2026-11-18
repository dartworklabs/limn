/** Keep the reading position in sync with scrolling and interrupt heading jumps on user input. */
import { $ } from '../platform/dom.ts';
import { isMarkdownDoc } from '../documents/state.ts';
import { endLandedJump, readSpot, stopHeadingJump } from './view-reading.ts';
import { updateMarkdownStrip } from './view-outline.ts';
import { SCROLL_KEYS } from '../pdf/view-outline.ts';

/** Track scroll position and cancel a heading jump when the reader takes control. */
function listenToMarkdownNavigation() {
  for (const eventType of ['wheel', 'touchstart', 'pointerdown'])
    $('#left').addEventListener(eventType, stopHeadingJump, { passive: true });
  // A key scrolls the pane when nothing else has the focus or something in the pane has it - pdf/view-outline.ts's scope
  // (SCROLL_KEYS): with the focus on the page's body, Home or PageDown scrolls the pane without a key event on it.
  window.addEventListener('keydown', (event) => {
    const active = document.activeElement;
    if (SCROLL_KEYS.has(event.key) && (!active || active === document.body || $('#left').contains(active)))
      stopHeadingJump();
  });
}

function watchReadingScroll() {
  let stripFrame = 0;
  $('#left').addEventListener(
    'scroll',
    () => {
      if (!isMarkdownDoc() || stripFrame) return;
      stripFrame = requestAnimationFrame(() => {
        stripFrame = 0;
        endLandedJump();
        updateMarkdownStrip();
        readSpot();
      });
    },
    { passive: true },
  );
}

export { listenToMarkdownNavigation, watchReadingScroll };
