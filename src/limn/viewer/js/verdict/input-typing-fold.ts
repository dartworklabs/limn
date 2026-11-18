import { focusedElement, findClosest, typingNow, findMaybe, eventElement } from '../platform/dom.ts';
import { stickSoon } from './state-line-renderer.ts';
import { fitPageLines } from './view-line-fit.ts';

// Digits typed into a focused field are text. Update the reading line's key marks after focus moves.
document.addEventListener('focusin', () => stickSoon());

document.addEventListener('focusout', () => stickSoon());

// body.pv-typing while a text field in a page line has the focus (the reason): on a touch screen the keyboard is up,
// and the line drops its figure's name, its save chip folds to [되돌리기] and the status line over the sheet steps
// aside (components.css, responsive.css), so line, field, chip and sheet fit in what the keyboard leaves on a foldable.
// That line's row is measured again. Read on every focus move and after every drawing of the lines (drawPageVerdicts):
// a rebuild or a pin deleted elsewhere takes the focused field out of the page, and Chromium sends no focusout for
// that, so without the redraw the class would stay and hide the status line. Once on, it stays while the reason popover
// is being used - the focus on one of its buttons, or a press that started in it until that press's click has run
// (POPOVER_PRESS): a tap on [저장], [접기] or [지우기] takes the focus out of the field, and if the status line came
// back and a phone's line stacked again, the button would move between the touch and its click and the click would fall
// on the popover itself. So does a press on the rest of the line while the field folds it: the figure's name coming
// back would move the words down under the finger before the click. The fold goes once that press is done: its click
// has run, the browser took it for a scroll (pointercancel), or 500ms after it let go without a click - a long press
// keeps it as long as it is held, so the words stay under the finger while its description shows. Only the press that
// holds the fold lets it go (FOLD_PRESS_HOLD): a new press on the line takes it over and the earlier one's wait goes,
// so a long press's swallowed click never lets the fold go under the next press, between that press's focus and its
// click. A press whose window loses the focus or is hidden (another app, a tab switch) lets it go at once: let go
// outside the window, it has no pointerup or pointercancel here.
let POPOVER_PRESS = false;

let FOLD_PRESS_HOLD: (() => void) | null = null; // the press holding the fold: drops its own wait without letting go

function syncTypingFold() {
  const active = focusedElement(),
    focusLine = active ? findClosest(active, '#doc .pv', HTMLElement) : null,
    body = document.body;
  const pop = !!active && !!active.closest('#doc .pv>.pv-pop'),
    on = (!!focusLine && typingNow()) || (body.classList.contains('pv-typing') && (pop || POPOVER_PRESS));
  if (body.classList.contains('pv-typing') === on) return;
  body.classList.toggle('pv-typing', on);
  const line = focusLine || findMaybe(document, '#doc .pv.reading', HTMLElement);
  if (line) fitPageLines([line]);
}

document.addEventListener('focusin', syncTypingFold);

document.addEventListener('focusout', () => setTimeout(syncTypingFold, 0));

function watchVerdictFold() {
  document.addEventListener(
    'pointerdown',
    (event) => {
      const target = eventElement(event);
      if (!(
        target &&
        (target.closest('#doc .pv>.pv-pop') ||
          (document.body.classList.contains('pv-typing') && target.closest('#doc .pv')))
      ))
        return;
      if (FOLD_PRESS_HOLD) FOLD_PRESS_HOLD(); // an earlier press still waiting: this one holds the fold now
      POPOVER_PRESS = true;
      let timer: ReturnType<typeof setTimeout> | undefined = undefined;
      const drop = () => {
        clearTimeout(timer);
        window.removeEventListener('click', late);
        window.removeEventListener('pointercancel', late);
        window.removeEventListener('pointerup', up, true);
        window.removeEventListener('blur', late);
        document.removeEventListener('visibilitychange', hid);
        if (FOLD_PRESS_HOLD === drop) FOLD_PRESS_HOLD = null;
      };
      const end = () => {
        if (FOLD_PRESS_HOLD !== drop) return;
        drop();
        setTimeout(() => {
          if (FOLD_PRESS_HOLD) return;
          POPOVER_PRESS = false;
          syncTypingFold();
        }, 0);
      };
      const late = () => end(),
        up = () => {
          clearTimeout(timer);
          timer = setTimeout(end, 500);
        },
        hid = () => {
          if (document.visibilityState === 'hidden') end();
        }; // late: after the press's own click (window, bubbling: after the viewer's handlers)
      FOLD_PRESS_HOLD = drop;
      window.addEventListener('click', late);
      window.addEventListener('pointercancel', late);
      window.addEventListener('pointerup', up, true);
      window.addEventListener('blur', late);
      document.addEventListener('visibilitychange', hid);
    },
    true,
  );
}

export { syncTypingFold, watchVerdictFold };
