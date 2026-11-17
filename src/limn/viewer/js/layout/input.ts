// Panel width handle - mouse, touch and pen all share one Pointer Events path. The handle has touch-action:none, so
// dragging it never fights browser scrolling, and setPointerCapture keeps tracking it even outside the handle. While
// dragging, only the width changes (the body's page width stays put); relayout runs once on release. Where the drag
// lands is snapSide(): the width follows, stops at the minimum (the handle turns primary), or - past half the minimum -
// previews a collapse (the panel's contents at 40%, a w-resize cursor) that a release carries out; a draft blocks that
// zone (not-allowed cursor, release = minimum).
// A collapsed wide panel leaves the handle as a 6px rail at the right edge: dragging it left past half the minimum
// opens the panel at the minimum and then follows; a double-click (a tap on touch) opens it at the saved width. A tap
// on an open handle (double-click with a mouse) cycles the presets. Keys follow gripKey() (WAI-ARIA window splitter).
import {
  BAND,
  DOC,
  LAYOUT,
  MID_OVERLAY,
  COARSE_POINTER_QUERY,
  REDUCED_MOTION_QUERY,
  OUTLINE_MID_OPEN,
  SIDE_OPEN,
} from '../app/state.ts';
import { SWALLOW_CLICK, endPress, hideTip, setSwallowClick } from '../platform/tooltip.ts';
import {
  SHEET_CLOSE_FRACTION,
  SHEET_FRACTIONS,
  SHEET_MIN_FRACTION,
  applyOutlineState,
  applySheet,
  applySideWidth,
  currentSideWidth,
  cycleSheet,
  cycleSideWidth,
  gripKey,
  keepSheet,
  outlineBounds,
  setOutlineWidth,
  setSheetFraction,
  setSideWidth,
  sheetFraction,
  showOutlineWidth,
  showSideWidth,
  sideBounds,
  snapSide,
  toggleOutline,
} from './flow-panel-size.ts';
import {
  SLIDE_MS,
  applySide,
  coachSideCollapsed,
  draftOpen,
  finishSideSlide,
  focusSideToggle,
  relayout,
  setSide,
  toggleSide,
  frameHost,
} from './flow.ts';
import { $, $$, eventElement, findMaybe } from '../platform/dom.ts';
import { LAYOUT_BAND, LAYOUT_MODE } from '../app/rules-tables.ts';
const LONGPRESS_MS = 450;

(function () {
  const grip = $('#grip');
  let drag: {
    id: number;
    x: number;
    w: number;
    rail: boolean;
    moved: boolean;
    mouse: boolean;
    zone: string | null;
  } | null = null;
  // The drag's cues: the handle turns primary once it stops at the minimum; the collapse preview fades the panel's
  // contents (never #right itself - see §펼친 화면 레이아웃) and the blocked zone shows not-allowed.
  const cue = (zone: string | null, rail?: boolean) => {
    const body = document.body;
    grip.classList.toggle(
      'snap-min',
      !!zone && zone !== 'follow' && !(rail && (zone === 'collapse' || zone === 'blocked')),
    );
    body.classList.toggle('side-snap-collapse', zone === 'collapse' && !rail);
    body.classList.toggle('side-snap-blocked', zone === 'blocked' && !rail);
  };
  // A drag from the rail shows the panel without deciding anything yet (the release does).
  const preview = (on: boolean) => {
    document.body.classList.toggle('side-open', on);
  };
  grip.addEventListener('pointerdown', (event: PointerEvent) => {
    if (LAYOUT === LAYOUT_MODE.NARROW || (event.pointerType === 'mouse' && event.button !== 0)) return;
    event.preventDefault();
    hideTip();
    finishSideSlide();
    drag = {
      id: event.pointerId,
      x: event.clientX,
      w: SIDE_OPEN ? currentSideWidth() : 0,
      rail: !SIDE_OPEN,
      moved: false,
      mouse: event.pointerType === 'mouse',
      zone: null,
    };
    try {
      grip.setPointerCapture(event.pointerId);
    } catch (_) {}
    grip.classList.add('on');
    document.body.classList.add('resizing');
  });
  grip.addEventListener('pointermove', (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.id) return;
    const deltaX = drag.x - event.clientX;
    if (!drag.moved && Math.abs(deltaX) < 4) return;
    drag.moved = true;
    const bounds = sideBounds(LAYOUT, innerWidth),
      snap = snapSide(drag.w + deltaX, bounds, draftOpen());
    drag.zone = snap.zone;
    if (drag.rail) preview(snap.zone === 'follow' || snap.zone === 'min');
    showSideWidth(snap.w, bounds);
    cue(snap.zone, drag.rail);
  });
  // The release: a cancel restores the state before the drag; a tap opens the rail or cycles the presets; a rail drag
  // opens past half the minimum; an open drag collapses in the collapse zone and otherwise saves the width (the minimum
  // in the min and blocked zones).
  const end = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.id) return;
    const released = drag;
    drag = null;
    grip.classList.remove('on');
    document.body.classList.remove('resizing');
    cue(null);
    // A cancel goes back to exactly how it was before the drag.
    if (event.type === 'pointercancel') {
      applySide();
      applySideWidth();
      relayout();
      return;
    }
    if (!released.moved) {
      if (released.mouse || Date.now() < SWALLOW_CLICK) return;
      if (released.rail) setSide(true, true, true);
      else cycleSideWidth();
      // The tap moved the panel: the click that follows would land on whatever is under the finger now.
      setSwallowClick(Date.now() + 400);
      return;
    }
    if (released.rail) {
      if (released.zone === 'collapse' || released.zone === 'blocked') {
        applySide();
        applySideWidth();
        return;
      }
      setSide(true, true);
      setSideWidth(currentSideWidth());
      return;
    }
    if (released.zone === 'collapse') {
      setSwallowClick(Date.now() + 400);
      setSide(false, true, true);
      focusSideToggle();
      coachSideCollapsed();
      return;
    }
    setSideWidth(currentSideWidth());
  };
  grip.addEventListener('pointerup', end);
  grip.addEventListener('pointercancel', end);
  grip.addEventListener('dblclick', () => {
    if (SIDE_OPEN) cycleSideWidth();
    else setSide(true, true, true);
  });
  grip.addEventListener('keydown', (event: KeyboardEvent) => {
    if (LAYOUT === LAYOUT_MODE.NARROW) return;
    const action = gripKey(event.key, currentSideWidth(), sideBounds(LAYOUT, innerWidth), !SIDE_OPEN);
    if (!action) return;
    event.preventDefault();
    if (action.act === 'collapse' || action.act === 'open') toggleSide();
    else if (action.act === 'cycle') cycleSideWidth();
    else {
      if (!SIDE_OPEN) setSide(true, true, true);
      setSideWidth(action.w);
    }
  });
})();
// Outline width is independent of the right work panel's handle. While dragging, only the width changes; the PDF
// position is restored when it ends.
(function () {
  const grip = $('#outline-grip');
  let drag: { id: number; x: number; w: number } | null = null;
  grip.addEventListener('pointerdown', (event: PointerEvent) => {
    if (
      LAYOUT === LAYOUT_MODE.NARROW ||
      document.body.classList.contains('outline-collapsed') ||
      (event.pointerType === 'mouse' && event.button !== 0)
    )
      return;
    event.preventDefault();
    drag = { id: event.pointerId, x: event.clientX, w: Math.round($('#outline').getBoundingClientRect().width) };
    try {
      grip.setPointerCapture(event.pointerId);
    } catch (_) {}
    grip.classList.add('on');
    document.body.classList.add('resizing');
  });
  grip.addEventListener('pointermove', (event: PointerEvent) => {
    if (drag && event.pointerId === drag.id) showOutlineWidth(drag.w + event.clientX - drag.x);
  });
  const end = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.id) return;
    drag = null;
    grip.classList.remove('on');
    document.body.classList.remove('resizing');
    if (event.type === 'pointercancel') {
      applyOutlineState();
      relayout();
    } else setOutlineWidth($('#outline').getBoundingClientRect().width);
  };
  grip.addEventListener('pointerup', end);
  grip.addEventListener('pointercancel', end);
  grip.addEventListener('keydown', (event: KeyboardEvent) => {
    if (LAYOUT === LAYOUT_MODE.NARROW) return;
    const bounds = outlineBounds(),
      width = Math.round($('#outline').getBoundingClientRect().width);
    const next = { ArrowLeft: width - 16, ArrowRight: width + 16, Home: bounds.min, End: bounds.max }[event.key];
    if (next !== undefined) {
      event.preventDefault();
      setOutlineWidth(next);
    }
  });
})();
type DragSample = [time: number, position: number];
// The release speed of a drag from its last 100ms of samples [[t, pos], ...], in px/ms (positive = toward larger pos).
function dragSpeed(samples: DragSample[]) {
  if (samples.length < 2) return 0;
  const first = samples[0],
    last = samples[samples.length - 1];
  return (last[1] - first[1]) / Math.max(1, last[0] - first[0]);
}
// Adds one [time, position] sample to a drag, keeping only the last 100ms (dragSpeed's window).
function dragSample(samples: DragSample[], time: number, pos: number) {
  samples.push([time, pos]);
  while (samples.length > 2 && time - samples[0][0] > 100) samples.shift();
}
type SheetRelease = { f: number; close?: undefined } | { close: true; f?: undefined };
// Where the phone sheet settles when a drag ends (docs/handbook/viewer.md §패널 폭과 시트 높이). fraction = the sheet
// height as a fraction of the screen, deltaY = the whole move (down positive), speed = the release speed (px/ms, down
// positive), keep = the height to save when it stays (shownSheetFraction). Below 25% or a downward fling (more than
// 24px at 0.5px/ms or faster) collapses it - or, while a draft is open, stops it at 30% (a drag never hides a draft);
// an upward fling goes to the next height stop; otherwise it stays where it was let go. Returns {close:true} or {f}.
function sheetRelease(
  fraction: number,
  deltaY: number,
  speed: number,
  composing: boolean,
  keep: number | undefined,
): SheetRelease {
  if (fraction < SHEET_CLOSE_FRACTION || (deltaY > 24 && speed >= 0.5))
    return composing ? { f: SHEET_MIN_FRACTION } : { close: true };
  if (deltaY < -24 && speed <= -0.5) {
    const nextStop = SHEET_FRACTIONS.find((stop) => stop > fraction + 0.02);
    return { f: nextStop === undefined ? 1 : nextStop };
  }
  return { f: Math.max(SHEET_MIN_FRACTION, Math.min(1, keep === undefined ? fraction : keep)) };
}
// A released sheet's height for sheetRelease: f, the height it shows over the screen, which the close and fling
// thresholds are judged on; keep, the height it stays at when it stays - 1 when it is held at its highest (max-height,
// the visible height less --sheet-gap: under the document bar, the keyboard up or down), else the shown height plus
// half a pixel, which saved at 1/10000 (setSheetFraction) CSS redraws on the same whole pixel (it rounds down).
function shownSheetFraction() {
  const panel = $('#right'),
    height = panel.getBoundingClientRect().height,
    maxHeight = parseFloat(getComputedStyle(panel).maxHeight);
  return { f: height / innerHeight, keep: height >= maxHeight - 1 ? 1 : (height + 0.5) / innerHeight };
}
// Carries out sheetRelease() for the height the sheet shows (shownSheetFraction) and the draft state now: collapse the
// sheet (remembered) or set its height.
function settleSheet(shown: ReturnType<typeof shownSheetFraction>, deltaY: number, speed: number) {
  const outcome = sheetRelease(shown.f, deltaY, speed, draftOpen(), shown.keep);
  if (outcome.close) {
    applySheet();
    setSide(false, true);
  } else setSheetFraction(outcome.f);
}
// The height a dragged sheet shows: never below 12% - or 30% while a draft is open, where it will stop anyway. A drag
// ends the composing lift (keepSheet): from here the finger sets the height.
function dragSheetTo(height: number) {
  keepSheet();
  document.documentElement.style.setProperty(
    '--sheet-f',
    String(Math.max(draftOpen() ? SHEET_MIN_FRACTION : 0.12, height / innerHeight)),
  );
}
// Sheet height (narrow): the handle in the tool bar's row and the whole tool bar move the sheet. On the handle a drag
// starts at once (6px); on the tool bar a vertical move of more than 8px on a button turns into a sheet drag and
// swallows that button's click. Dragging up opens a collapsed sheet; the release is sheetRelease(). A tap on the handle
// opens it or cycles the heights, and swallows the ghost click that would otherwise land on whatever moved under the
// finger.
(function () {
  const grip = $('#sheet-grip'),
    bar = $('#bar1');
  let drag: {
    id: number;
    x: number;
    y: number;
    h: number;
    moved: boolean;
    lazy: boolean;
    el: HTMLElement;
    pts: DragSample[];
  } | null = null;
  // grab = the drag owns the pointer (capture, cues); down = the handle grabs at once, the tool bar only once the move
  // is vertical (lazy - its buttons keep their taps); end = settle by sheetRelease(), or a handle tap.
  const grab = (event: PointerEvent) => {
    if (!drag) return;
    try {
      drag.el.setPointerCapture(event.pointerId);
    } catch (_) {}
    drag.el.classList.add('on');
    document.body.classList.add('resizing');
  };
  const down = (event: PointerEvent, lazy: boolean) => {
    if (LAYOUT !== LAYOUT_MODE.NARROW || !event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0))
      return;
    // A field keeps its press, and the handle (inside the bar) has already grabbed.
    if (lazy && eventElement(event)?.closest('input,textarea,select,#sheet-grip')) return;
    drag = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      h: $('#right').getBoundingClientRect().height,
      moved: false,
      lazy,
      el: lazy ? bar : grip,
      pts: [],
    };
    if (!lazy) {
      event.preventDefault();
      grab(event);
    }
  };
  grip.addEventListener('pointerdown', (event: PointerEvent) => down(event, false));
  bar.addEventListener('pointerdown', (event: PointerEvent) => down(event, true));
  window.addEventListener('pointermove', (event) => {
    if (!drag || event.pointerId !== drag.id) return;
    const deltaY = drag.y - event.clientY;
    if (!drag.moved) {
      if (Math.abs(deltaY) < (drag.lazy ? 8 : 6)) return;
      if (drag.lazy && Math.abs(event.clientX - drag.x) > Math.abs(deltaY)) {
        drag = null;
        return;
      }
      drag.moved = true;
      if (drag.lazy) {
        grab(event);
        hideTip();
        endPress();
      }
    }
    dragSample(drag.pts, performance.now(), event.clientY);
    if (!SIDE_OPEN && deltaY > 0) setSide(true);
    if (SIDE_OPEN) dragSheetTo(drag.h + deltaY);
  });
  const end = (event: PointerEvent) => {
    if (!drag || event.pointerId !== drag.id) return;
    const released = drag;
    drag = null;
    released.el.classList.remove('on');
    document.body.classList.remove('resizing');
    if (event.type === 'pointercancel') {
      if (released.moved) applySheet();
      return;
    }
    if (!released.moved) {
      if (released.lazy || Date.now() < SWALLOW_CLICK) return;
      if (!SIDE_OPEN) setSide(true, true);
      else cycleSheet();
      setSwallowClick(Date.now() + 400);
      return;
    }
    setSwallowClick(Date.now() + 400); // a drag that started on a tool-bar button never also presses it
    if (!SIDE_OPEN) {
      applySheet();
      return;
    }
    settleSheet(shownSheetFraction(), event.clientY - released.y, dragSpeed(released.pts));
  };
  window.addEventListener('pointerup', end);
  window.addEventListener('pointercancel', end);
  grip.addEventListener('keydown', (event: KeyboardEvent) => {
    if (LAYOUT !== LAYOUT_MODE.NARROW) return;
    const fraction = sheetFraction();
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSheetFraction(fraction + 0.05);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSheetFraction(fraction - 0.05);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      cycleSheet();
    }
  });
})();
// A pull-down that a scroll box at its top hands to its sheet (the phone sheet's content, the documents sheet): touch
// events, because the browser cancels a pointer stream as soon as it starts its own scroll. The first move decides -
// down, mostly vertical, the box at scrollTop 0, not in a text field or a nested scroller - and from then on the move
// is the sheet's (preventDefault). ok(event) filters the touchstart; onMove(deltaY) follows; onEnd(deltaY, speed)
// settles (deltaY null = cancelled; speed in px/ms, down positive).
function pullDown(
  box: HTMLElement,
  ok: (event: TouchEvent) => boolean,
  onStart: () => void,
  onMove: (deltaY: number) => void,
  onEnd: (deltaY: number | null, speed: number) => void,
) {
  let pull: { x: number; y: number; on: boolean; pts: DragSample[] } | null = null;
  box.addEventListener(
    'touchstart',
    (event: TouchEvent) => {
      if (pull && pull.on) onEnd(null, 0);
      pull = null;
      const touch = event.touches[0];
      // A second finger cancels a pull. The order control does not scroll and heads the list, where a pull starts, so
      // it is not skipped like the other segment controls.
      if (
        event.touches.length !== 1 ||
        !ok(event) ||
        eventElement(event)?.closest('textarea,input,select,pre,.seg:not(#list-order)')
      )
        return;
      pull = { x: touch.clientX, y: touch.clientY, on: false, pts: [] };
    },
    { passive: true },
  );
  box.addEventListener(
    'touchmove',
    (event: TouchEvent) => {
      if (!pull) return;
      const touch = event.touches[0],
        deltaX = touch.clientX - pull.x,
        deltaY = touch.clientY - pull.y;
      if (!pull.on) {
        if (Math.hypot(deltaX, deltaY) < 8) return;
        if (!(deltaY > 0 && deltaY > Math.abs(deltaX) && box.scrollTop <= 0 && event.cancelable)) {
          pull = null;
          return;
        }
        pull.on = true;
        onStart();
      }
      event.preventDefault();
      dragSample(pull.pts, performance.now(), touch.clientY);
      onMove(deltaY);
    },
    { passive: false },
  );
  const end = (event: TouchEvent) => {
    if (!pull) return;
    const released = pull;
    pull = null;
    if (!released.on) return;
    onEnd(event.type === 'touchcancel' ? null : event.changedTouches[0].clientY - released.y, dragSpeed(released.pts));
  };
  box.addEventListener('touchend', end);
  box.addEventListener('touchcancel', end);
}
// The phone sheet: pulling its content down at the top lowers the sheet (nested scroll hand-off); the release is
// sheetRelease().
(function () {
  let startHeight = 0;
  pullDown(
    $('#right'),
    (event) => {
      const element = eventElement(event);
      return LAYOUT === LAYOUT_MODE.NARROW && SIDE_OPEN && element !== null && !element.closest('#bar1,#sheet-grip');
    },
    () => {
      startHeight = $('#right').getBoundingClientRect().height;
      document.body.classList.add('resizing');
      hideTip();
      endPress();
    },
    (deltaY) => dragSheetTo(startHeight - deltaY),
    (deltaY, speed) => {
      document.body.classList.remove('resizing');
      if (deltaY === null) {
        applySheet();
        return;
      }
      setSwallowClick(Date.now() + 400);
      settleSheet(shownSheetFraction(), deltaY, speed);
    },
  );
})();
// The bottom sheets follow a pull-down and close on a release past 35% of their height or a flick (dismissOutcome):
// [더보기] and the documents sheet always, help and the Trash where they are bottom sheets too (compact; the desktop
// centres them).
function sheetPull(sheet: HTMLDialogElement, always: boolean) {
  pullDown(
    sheet,
    () => sheet.open && (always || LAYOUT !== LAYOUT_MODE.WIDE),
    () => {},
    (deltaY) => {
      sheet.style.transform = 'translateY(' + Math.max(0, Math.round(deltaY)) + 'px)';
    },
    (deltaY, speed) => {
      const close = deltaY !== null && dismissOutcome(deltaY, sheet.getBoundingClientRect().height, speed) === 'close';
      sheet.style.transform = '';
      if (close) sheet.close();
    },
  );
}
sheetPull($('#nav-sheet'), true);
sheetPull($('#more'), true);
sheetPull($('#help'), false);
sheetPull($('#trash'), false);

// ------------------------------------------------ The overlay panel's swipe (701-900px, touch)
// The overlay panel is dismissed by a rightward swipe (docs/handbook/viewer.md §펼친 화면 레이아웃). swipeAxis() waits
// for 10px and then takes only a mostly horizontal, rightward drag; the panel follows the finger through right (never a
// transform, which would move the fixed tool bar with it), and dismissOutcome() decides the release: slide out
// (remembered like [핀]) or spring back, 0.18s each. A draft only rubber-bands (swipeFollow). Gestures that start in a
// horizontal scroller (.seg, pre.nowrap), a text field, the handle or the tool bar are theirs, and a press held still
// for 450ms is a text selection. 901-1099px (beside the document) has no swipe - only the handle - and outside taps
// never close the overlay (it is not modal, and a long-press re-pick needs the PDF).
function swipeAxis(deltaX: number, deltaY: number) {
  if (Math.hypot(deltaX, deltaY) < 10) return null;
  return deltaX > 0 && Math.abs(deltaX) > 1.5 * Math.abs(deltaY) ? 'x' : 'none';
}
// How far the panel follows a rightward drag: the finger itself, or while a draft is open a rubber band (a quarter, at
// most 24px).
function swipeFollow(deltaX: number, composing: boolean) {
  deltaX = Math.max(0, deltaX);
  return composing ? Math.min(24, deltaX * 0.25) : deltaX;
}
// A dismiss gesture's release (the panel swipe, the documents sheet): distance = the distance moved toward closing,
// size = the panel's size along it, speed = the release speed toward closing in px/ms. Past 35% of the size, or a fling
// (more than 24px at 0.5px/ms or faster), closes.
function dismissOutcome(distance: number, size: number, speed: number) {
  return distance >= 0.35 * size || (distance > 24 && speed >= 0.5) ? 'close' : 'back';
}
(function () {
  const panel = $('#right'),
    SKIP = '.seg,pre.nowrap,textarea,input,select,#grip,#bar1';
  let swipe: {
    id: number;
    x: number;
    y: number;
    t: number;
    axis: string | null;
    w: number;
    pts: DragSample[];
  } | null = null;
  // setX moves the panel (and handle) by px through --swipe-x; settle ends a swipe - 'close' slides it out and
  // collapses it (remembered), 'back' springs it back - and always leaves --swipe-x at 0.
  const setX = (px: number) => document.documentElement.style.setProperty('--swipe-x', Math.round(px) + 'px');
  const settle = (out: 'close' | 'back') => {
    const body = document.body,
      ms = REDUCED_MOTION_QUERY.matches ? 0 : SLIDE_MS;
    body.classList.remove('side-swiping');
    const done = () => {
      body.classList.remove('side-settling');
      if (out === 'close') {
        setSide(false, true);
        focusSideToggle();
      }
      setX(0);
    };
    if (!ms) {
      done();
      return;
    }
    body.classList.add('side-settling');
    setX(out === 'close' ? currentSideWidth() : 0);
    setTimeout(done, ms);
  };
  panel.addEventListener('pointerdown', (event: PointerEvent) => {
    // A second finger ends the swipe.
    if (!event.isPrimary) {
      if (swipe && swipe.axis === 'x') settle('back');
      swipe = null;
      return;
    }
    swipe = null;
    if (event.pointerType === 'mouse' || !(LAYOUT === LAYOUT_MODE.MID && MID_OVERLAY && SIDE_OPEN)) return;
    if (eventElement(event)?.closest(SKIP)) return;
    swipe = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      t: performance.now(),
      axis: null,
      w: 0,
      pts: [],
    };
  });
  window.addEventListener('pointermove', (event) => {
    if (!swipe || event.pointerId !== swipe.id) return;
    const deltaX = event.clientX - swipe.x,
      deltaY = event.clientY - swipe.y,
      now = performance.now();
    if (!swipe.axis) {
      const axis = swipeAxis(deltaX, deltaY);
      if (axis === null) return;
      // A scroll, a leftward drag, or a still press that selects text.
      if (axis !== 'x' || now - swipe.t >= LONGPRESS_MS) {
        swipe = null;
        return;
      }
      swipe.axis = axis;
      swipe.w = currentSideWidth();
      document.body.classList.add('side-swiping');
      hideTip();
      endPress();
    }
    dragSample(swipe.pts, now, event.clientX);
    setX(swipeFollow(deltaX, draftOpen()));
  });
  const end = (event: PointerEvent) => {
    if (!swipe || event.pointerId !== swipe.id) return;
    const released = swipe;
    swipe = null;
    if (released.axis !== 'x') return;
    if (event.type === 'pointercancel' || draftOpen()) {
      settle('back');
      return;
    }
    settle(dismissOutcome(Math.max(0, event.clientX - released.x), released.w, dragSpeed(released.pts)));
  };
  window.addEventListener('pointerup', end);
  window.addEventListener('pointercancel', end);
})();

// ------------------------------------------------ The back gesture closes the top layer (touch)
// On a phone or tablet the system back gesture closes the top layer first (docs/handbook/viewer.md §모바일 레이아웃)
// instead of leaving Limn with a draft on screen. While a sheet, the overlay panel or the outline overlay is open, one
// CloseWatcher stands for it (Chrome on Android routes back there; modal dialogs have their own); without CloseWatcher,
// one history entry does (popstate). Closing the layer any other way removes it again, so back never has a dead press,
// and document switches never add entries (they replace the hash). Mouse devices have no system back, so nothing is
// registered there.
let BACK: { kind: string; w?: CloseWatcher } | null = null,
  BACK_SKIP = false;
// Which layer covers the document for a band (overlay = MID_OVERLAY): an open bottom-sheet dialog on top (dialogOpen -
// the caller passes it only without CloseWatcher, where a modal dialog takes the back gesture itself), then the outline
// overlay (the mid bands and the tablet sheet), then a sheet (phone, tablet) or the overlay panel (mid-overlay, a short
// band up to 900px). The desktop has none. 'dialog'|'side'|'outline'|null.
function backLayer(
  band: string | null,
  overlay: boolean,
  sideOpen: boolean,
  outlineOpen: boolean,
  dialogOpen: boolean,
) {
  if (band === LAYOUT_BAND.WIDE) return null;
  if (dialogOpen) return 'dialog';
  if (band === LAYOUT_BAND.PHONE) return sideOpen ? 'side' : null;
  if (outlineOpen) return 'outline';
  return sideOpen && (band === LAYOUT_BAND.TABLET_SHEET || overlay) ? 'side' : null;
}
// The open bottom-sheet dialog the back gesture closes first, or null: the navigation sheet, [더보기], help, the Trash,
// the status line's list.
function sheetDialog() {
  return findMaybe(
    document,
    '#nav-sheet[open],#more[open],#help[open],#trash[open],#status-list[open]',
    HTMLDialogElement,
  );
}
// Registers or removes the back layer to match the screen (called by applySide, applyOutlineState and a sheet dialog
// opening or closing; idempotent).
function syncBackLayer() {
  const want =
    COARSE_POINTER_QUERY.matches &&
    !!backLayer(BAND, MID_OVERLAY, SIDE_OPEN, OUTLINE_MID_OPEN, !window.CloseWatcher && !!sheetDialog());
  if (want && !BACK) armBack();
  else if (!want && BACK) disarmBack();
}
for (const dialog of $$('#nav-sheet,#more,#help,#trash,#status-list'))
  new MutationObserver(() => syncBackLayer()).observe(dialog, { attributes: true, attributeFilter: ['open'] });
// Stands one CloseWatcher for the open layer, or pushes one history entry (same URL) where CloseWatcher is missing.
function armBack() {
  if (window.CloseWatcher) {
    try {
      const watcher = new window.CloseWatcher();
      BACK = { kind: 'watcher', w: watcher };
      watcher.onclose = () => {
        if (BACK && BACK.w === watcher) {
          BACK = null;
          closeTopLayer();
        }
      };
      return;
    } catch (error) {}
  }
  history.pushState({ limnLayer: 1 }, '', location.href);
  BACK = { kind: 'history' };
}
// Removes the layer without closing anything: destroys the watcher, or pops our entry (that popstate is skipped).
function disarmBack() {
  const layer = BACK;
  BACK = null;
  if (!layer) return;
  if (layer.kind === 'watcher') {
    if (layer.w) layer.w.destroy();
    return;
  }
  if (history.state && history.state.limnLayer) {
    BACK_SKIP = true;
    history.back();
  }
}
// The back gesture's action: close the open sheet dialog or the outline overlay, or collapse the sheet or overlay panel
// (remembered, with the slide).
function closeTopLayer() {
  const dialog = sheetDialog(),
    layer = backLayer(BAND, MID_OVERLAY, SIDE_OPEN, OUTLINE_MID_OPEN, !!dialog);
  if (layer === 'dialog') dialog?.close();
  else if (layer === 'outline') toggleOutline();
  else if (layer === 'side') {
    setSide(false, true, true);
    focusSideToggle();
  }
}
window.addEventListener('popstate', () => {
  const ours = BACK_SKIP || (BACK && BACK.kind === 'history');
  if (!ours) return;
  if (DOC) frameHost().setHash(DOC); // the entry below may carry an older #doc= - the document on screen stays
  if (BACK_SKIP) {
    BACK_SKIP = false;
    return;
  }
  BACK = null;
  // A dialog over the sheet closes first.
  const dialog = findMaybe(document, 'dialog[open]', HTMLDialogElement);
  if (dialog) {
    dialog.close();
    syncBackLayer();
    return;
  }
  closeTopLayer();
});

export { BACK, BACK_SKIP, syncBackLayer, LONGPRESS_MS };
