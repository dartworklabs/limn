import { focusedElement, findClosest, TABBABLE, isTabStop } from '../platform/dom.ts';

const LINE_TEXT: WeakMap<HTMLElement, string> = new WeakMap(); // what fillPageLine last wrote into each line

// A word group that wraps (the 280px panel in English with a word armed) keeps every button at its own width,
// left-aligned (.wrapped): stretched to share the row, a lone last word would run across the whole second row. Measured
// after drawing and when the row's width changes; the class changes how the buttons grow, never where they wrap, so it
// never measures itself again.
function fitWrappedWords(group: Element | null) {
  if (!group) return;
  const tops = new Set([...group.children].map((button) => Math.round(button.getBoundingClientRect().top)));
  group.classList.toggle('wrapped', tops.size > 1);
}

// A focus on a control of one of these lines that its fitting just took out - the earlier link stepping out at a tight
// row's bar (.pv-early-out), or beside 'Enter 이유 쓰기' or [되돌리기] on a row that turned tight (components.css),
// after a resize, a zoom of the browser or of the pages, or a redraw - moves at once, without a scroll, to the control
// before it on its line ([판정 취소], 'Enter 이유 쓰기', the '#N' link), else to the line's first. Hidden with the
// focus on it, the link would take the focus away to nothing and the next Tab would start from the top (Chromium lets a
// hidden focus go a moment later: the move is made before that). Every way the fitting hides a control comes through
// here, and so does a phone's floating line holding [판정 취소] back (leanFloatingLine).
function keepFocusOnLine(lines: HTMLElement[]) {
  const active = focusedElement(),
    line = active ? findClosest(active, '#doc .pv', HTMLElement) : null;
  if (
    !active ||
    !line ||
    !lines.includes(line) ||
    (active.getClientRects().length && getComputedStyle(active).visibility !== 'hidden')
  )
    return;
  const controls = [...line.querySelectorAll(TABBABLE)].filter(isTabStop),
    before = controls.filter((x) => !!(x.compareDocumentPosition(active) & Node.DOCUMENT_POSITION_FOLLOWING));
  const to = before.length ? before[before.length - 1] : controls[0];
  if (to) to.focus({ preventScroll: true });
}

export { LINE_TEXT, fitWrappedWords, keepFocusOnLine };
