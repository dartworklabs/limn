// ------------------------ Hiding the pin marks for a look at the page itself (docs/handbook/viewer.md §핀 표시 숨기기)
// A pin's mark lies over what it marks - a box and a badge on a PDF page, a tinted line and a gutter badge on the
// Markdown and text surfaces - so a pinned figure is seen through the mark. To judge how it was fixed the marks can be
// taken off:
// - H, pressed and let go, turns them off, and on again; held, it flips them only for as long as it is down
//   (MARKS_HOLD_MS).
// - [더보기]'s switch [핀 표시] does the same on a touch screen; it closes the sheet so the page shows.
// While they are off the status line says so and offers [다시 보이기]. A card's [보기], which goes to a pin's mark,
// brings them back. A save's or an append's undo chip sits on its mark and stays on show there, the marks still off
// (components.css). Off is this page's state only (never stored): a reload shows every mark. Only the marks go. The
// pins, the cards, the page verdict lines and the selection box are as they were.
import { lineNote, quietNote, sourceOk } from '../platform/notices.ts';
import { searchToPage } from '../pdf/flow.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
const MARKS = { off: false, held: null as { code: string; at: number } | null };
const MARKS_HOLD_MS = 350; // a press this long is a look, not a switch
const MARKS_SOURCE = 'marks-off'; // the status line's one reminder (sourceEntry)
// Whether a keydown is the marks key: the key that types h, alone, whatever its place on the layout. A key that types
// no Latin letter (a Hangul jamo, an input method's 'Process') counts by its place: the physical H key. Pure.
function marksKey(event: {
  key?: string;
  code?: string;
  ctrlKey?: boolean;
  metaKey?: boolean;
  altKey?: boolean;
  shiftKey?: boolean;
}): boolean {
  if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return false;
  const key = event.key || '';
  return /^[a-z]$/i.test(key) ? key.toLowerCase() === 'h' : event.code === 'KeyH';
}
// What a press of the marks key that lasted ms does to the marks, off or not before it: a short one switches them, a
// long one was only a look and leaves them as they were. Returns whether they are off after it. Pure.
function marksAfterPress(off: boolean, ms: number): boolean {
  return ms >= MARKS_HOLD_MS ? off : !off;
}
// Shows the page with or without its marks, for now: the class the styles read (components.css, md-surface.css). The
// state itself (MARKS.off), the switch and the reminder are marksSet's. A hidden badge gives up the focus.
function marksLook(off: boolean) {
  const focused = document.activeElement as HTMLElement | null;
  // A badge with the focus would keep it unseen: the focus goes to the document area, as after a search (searchToPage).
  if (off && focused && focused.closest && focused.closest('.mark,.md-badges') && !focused.closest('.nt-chip'))
    searchToPage();
  document.body.classList.toggle('marks-off', off);
}
// Paints [더보기]'s switch from the state: on while the marks show.
function drawMarksSwitch() {
  const marksSwitch = $('#m-marks');
  marksSwitch.setAttribute('aria-checked', String(!MARKS.off));
  marksSwitch.dataset.tip = MARKS.off
    ? '핀 표시가 숨겨져 있습니다. 누르면 다시 보입니다 (H)'
    : '누르면 쪽 위의 핀 표시를 숨깁니다. 핀과 카드는 그대로입니다 (H)';
}
// Turns the marks off or on for good: the look, the switch, and the status line's reminder - put there when they go
// off, taken away when they come back; the line's cap never pushes it off (keep), and closed with its [x] it leaves the
// marks off with the switch as their trace. Says the change to a screen reader (the reminder reads itself). No request
// is sent.
function marksSet(off: boolean) {
  const was = MARKS.off;
  MARKS.off = off;
  MARKS.held = null;
  marksLook(off);
  drawMarksSwitch();
  if (off)
    lineNote(
      '핀 표시를 숨겼습니다',
      NOTICE_KIND.INFO,
      { label: '다시 보이기', tip: '쪽 위의 핀 표시를 다시 보입니다 (H)', fn: () => marksSet(false) },
      { life: NOTICE_LIFE.STICKY, source: MARKS_SOURCE, keep: true },
    );
  else {
    sourceOk(MARKS_SOURCE);
    if (was) quietNote('핀 표시를 다시 보입니다');
  }
}
// The marks come back because the way leads to one of them (a card's [보기]). Nothing when they already show.
function marksShow() {
  if (MARKS.off || MARKS.held) marksSet(false);
}
// The marks key goes down: the marks flip at once, so a look starts with the press. Not in a text field, under a dialog
// or in the changes view (no marks there), and a repeat of a held key is the same press.
function marksKeyDown(event: KeyboardEvent) {
  if (event.isComposing || !marksKey(event)) return;
  const target = event.target as HTMLElement | null,
    inField =
      !!target &&
      (target.tagName === 'TEXTAREA' ||
        target.tagName === 'INPUT' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable);
  if (inField || document.querySelector('dialog[open]') || document.body.classList.contains('revision-open')) return;
  event.preventDefault();
  if (event.repeat || MARKS.held) return;
  MARKS.held = { code: event.code, at: event.timeStamp };
  marksLook(!MARKS.off);
}
// The marks key comes up: a short press was a switch, a long one a look (marksAfterPress).
function marksKeyUp(event: KeyboardEvent) {
  const held = MARKS.held;
  if (!held || event.code !== held.code) return;
  const off = marksAfterPress(MARKS.off, event.timeStamp - held.at);
  if (off === MARKS.off) {
    MARKS.held = null;
    marksLook(off);
  } else marksSet(off);
}
// A press whose key never comes up here (the window lost the focus, the tab was hidden) was a look: the marks are as
// before.
function marksPressLost() {
  if (!MARKS.held) return;
  MARKS.held = null;
  marksLook(MARKS.off);
}
addEventListener('keydown', marksKeyDown);
addEventListener('keyup', marksKeyUp);
addEventListener('blur', marksPressLost);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) marksPressLost();
});
drawMarksSwitch();
export { MARKS, marksSet, marksShow };
