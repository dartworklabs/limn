// ------------------------------------------------ Tooltip
import { $, typingNow } from './dom.ts';
let LAST_POINTER = 'mouse',
  LAST_TOUCH_AT = 0;
// Sets LAST_POINTER, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLastPointer<Value extends typeof LAST_POINTER>(value: Value): Value {
  LAST_POINTER = value;
  return value;
}
// Sets LAST_TOUCH_AT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setLastTouchAt<Value extends typeof LAST_TOUCH_AT>(value: Value): Value {
  LAST_TOUCH_AT = value;
  return value;
}
// The elements whose tooltip does not show: pin mark badges a cover is over (pins/flow-list.ts markCoverSkip keeps it).
const MARK_HIDDEN = new WeakSet() as WeakSet<Element>;

// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sends a simulated
// mouseover, which would leave the description stuck over the list. Only long-press is used.
const NO_HOVER_QUERY = matchMedia('(hover:none)');

const TIP = $('#tip');
let tipTimer = undefined as ReturnType<typeof setTimeout> | undefined,
  armedTipElement = null as HTMLElement | null,
  MOUSE_AT = null as number[] | null;
document.addEventListener(
  'mousemove',
  (event) => {
    MOUSE_AT = [event.clientX, event.clientY];
  },
  { passive: true },
);
// The element the showing box was placed on and where it stood then (showTipText), for tipFollow.
let TIP_AT = null as { el: Element; x: number; y: number } | null;
// The tooltip box is a manual popover, so it is drawn in the top layer: a modal sheet (the navigation sheet, [더보기])
// is in the top layer too and would cover a box that only has a z-index. A browser without popovers draws it with its
// z-index.
function tipShown(on) {
  TIP.hidden = !on;
  if (!on) document.documentElement.classList.remove('tip-press');
  if (typeof TIP.showPopover !== 'function') return;
  try {
    const open = TIP.matches(':popover-open');
    if (on && !open) TIP.showPopover();
    else if (!on && open) TIP.hidePopover();
  } catch (error) {}
}
function hideTip() {
  clearTimeout(tipTimer);
  tipTimer = undefined;
  armedTipElement = null;
  TIP_AT = null;
  tipShown(false);
}
// Content came or went above a showing box's element (a banner over the Trash's list - its late notice, a failure - or
// the list drawn again): a box whose element moved or left the page goes. Left where it was, it would stand over the
// row before.
function tipFollow() {
  if (TIP.hidden || !TIP_AT) return;
  const shownOn = TIP_AT.el;
  if (!shownOn.isConnected) {
    hideTip();
    return;
  }
  const rect = shownOn.getBoundingClientRect();
  if (Math.abs(rect.left - TIP_AT.x) > 0.5 || Math.abs(rect.top - TIP_AT.y) > 0.5) hideTip();
}
// Shows an element's description over it. The box is translate="no": a description is already in the UI language (the
// translator rewrote the attribute, or the code drew it with translate()), and one that quotes a note ('#38 · 완료')
// must not be rewritten again. A mark badge a cover is over now (MARK_HIDDEN, pins/flow-list.ts markCoverSkip) shows
// none: it would float over the cover.
function showTip(element) {
  if (MARK_HIDDEN.has(element)) return;
  showTipText(element, element.dataset.tip || '');
}
// Shows `text` over an element as its description box (showTip's drawing; statusWhy shows [이유]'s sentence at the line
// this way). Nothing without a text or for an element no longer in the page. Inside a box marked data-tip-at="left"
// (the page verdict panel) the description stands left of that box, level with the element, so it covers none of the
// box's own rows
// - over a word it would cover the panel's name above it, and under it the controls - unless there is no room there.
// Standing there it lies over the page beside the box (the gap is narrower than any description), so it draws an edge
// (.tip-beside, overlays.css): without one it reads as a box cut off at the page's edge, in the dark theme most. A
// description that ends in a URL the element names (data-tip-url: a link or an image of a Markdown document) has that
// URL in a span of its own (.tip-url), the one part that may break anywhere.
function showTipText(element: HTMLElement, text: string) {
  if (!text || !document.contains(element)) return;
  const box = element.closest('[data-tip-at="left"]') as HTMLElement | null,
    url = element.dataset.tipUrl || '';
  if (url && text.endsWith(url)) {
    const urlSpan = document.createElement('span');
    urlSpan.className = 'tip-url';
    urlSpan.textContent = url;
    TIP.replaceChildren(text.slice(0, text.length - url.length), urlSpan);
  } else TIP.textContent = text;
  TIP.classList.toggle('tip-beside', !!box);
  tipShown(true); // measured with its edge
  const rect = element.getBoundingClientRect(),
    tipWidth = TIP.offsetWidth,
    tipHeight = TIP.offsetHeight,
    besideLeft = box ? box.getBoundingClientRect().left - tipWidth - 8 : -1;
  // where the element stood, for tipFollow - the box beside the panel too
  TIP_AT = { el: element, x: rect.left, y: rect.top };
  if (box && besideLeft >= 4) {
    TIP.style.left = besideLeft + 'px';
    TIP.style.top =
      Math.max(4, Math.min(rect.top + rect.height / 2 - tipHeight / 2, innerHeight - tipHeight - 4)) + 'px';
    return;
  }
  TIP.classList.remove('tip-beside');
  let top = rect.top - tipHeight - 8,
    centerX = rect.left + rect.width / 2;
  // A control in a Trash row has its box beside the row's controls, inside that row: over it the box would cover the
  // row before's note line and buttons (under it, the next row's). Where the row leaves it no room, it goes over as
  // anywhere.
  const row = element.closest('#trash-list .arc-row') as HTMLElement | null,
    actions = row && row.querySelector('.arc-acts');
  if (row && actions) {
    const rowRect = row.getBoundingClientRect(),
      x = actions.getBoundingClientRect().left - tipWidth - 8;
    if (x >= rowRect.left && tipHeight <= rowRect.height) {
      TIP.style.left = x + 'px';
      TIP.style.top =
        Math.max(rowRect.top, Math.min(rect.top + rect.height / 2 - tipHeight / 2, rowRect.bottom - tipHeight)) + 'px';
      return;
    }
  }
  if (top < 4) top = rect.bottom + 8;
  if (top > innerHeight - tipHeight - 4 && MOUSE_AT) {
    top = MOUSE_AT[1] + 18;
    centerX = MOUSE_AT[0];
  } // an element taller than the window (#grip/a long card) anchors to the pointer instead
  top = Math.max(4, Math.min(top, innerHeight - tipHeight - 4));
  const left = Math.min(Math.max(4, centerX - tipWidth / 2), innerWidth - tipWidth - 4);
  TIP.style.left = left + 'px';
  TIP.style.top = top + 'px';
}
function armTip(element) {
  if (element === armedTipElement) return;
  hideTip();
  if (!element) return;
  armedTipElement = element;
  tipTimer = setTimeout(() => showTip(element), 300);
}
// Hover/focus tooltips are never shown right after a touch: mobile Chrome simulates mouseover/focusin on every tap,
// which would pop a description up at every press of a button. Touch relies on long-press instead (below).
const touchRecent = () => Date.now() - LAST_TOUCH_AT < 1500;
document.addEventListener(
  'pointerdown',
  (event) => {
    setLastPointer(event.pointerType || 'mouse');
    if (LAST_POINTER !== 'mouse') setLastTouchAt(Date.now());
  },
  true,
);
// Whether a key press makes the keyboard the input the focus ring answers: any key outside a text field (Tab, a
// shortcut such as '?'), and in a field only a key that leaves it or acts (Tab, Escape, or with Ctrl/⌘/Alt) - typing is
// not, nor a touch keyboard's 'Unidentified' key or an IME's composing one. Pure.
function keyNavigates(key, inField, hasModifier) {
  if (!key || key === 'Unidentified' || key === 'Process') return false;
  return !inField || key === 'Tab' || key === 'Escape' || !!hasModifier;
}
// The input the focus ring answers (docs/handbook/viewer.md §뜻과 모양): html[data-input] is 'pointer' after a press
// and 'key' after a key that navigates, and components.css draws the ring only outside 'pointer'. A sheet takes the
// first focus itself, but closing one gives the focus back by script ([본문 1/2 ▾], help's opener), and Chrome rings a
// script focus whenever the last input it counted was a key - and on Android a tap on a bar button does not reset that.
document.addEventListener(
  'pointerdown',
  () => {
    document.documentElement.dataset.input = 'pointer';
  },
  true,
);
// Makes the keyboard the input the ring answers when a key press navigates (keyNavigates); a press makes it the pointer
// (above).
function inputFromKey(event) {
  if (keyNavigates(event.key, typingNow(), event.ctrlKey || event.metaKey || event.altKey))
    document.documentElement.dataset.input = 'key';
}
document.addEventListener('keydown', inputFromKey, true);
// Whether the last input was a key that navigates (inputFromKey): a focus that follows it is the keyboard's.
const keyInput = () => document.documentElement.dataset.input === 'key';
document.addEventListener('mouseover', (event) => {
  if (touchRecent() || NO_HOVER_QUERY.matches) return;
  const target = event.target as HTMLElement;
  armTip(target.closest ? target.closest('[data-tip]') : null);
});
// Puts the focus back on an element the page drew again in place of the control that had it (keepSegmentFocus,
// main.ts). It is no new focus: after a key it shows the element's description as the keyboard's focus does, after a
// press it shows none. A rung chosen with the mouse is drawn again once more when the excerpt's lines come back
// (excerptFetch); by then the pointer has gone elsewhere, and a box the focus given back armed would stand over the
// range caption and the overlap's buttons.
let FOCUS_GIVEN_BACK = false;
function focusGivenBack(element: HTMLElement) {
  FOCUS_GIVEN_BACK = true;
  try {
    element.focus();
  } finally {
    FOCUS_GIVEN_BACK = false;
  }
}
// A focus tooltip is never shown on an input field (textarea): it would cover the snippet while typing, and the tooltip
// would swallow the first Esc, so "Esc to cancel -> Ctrl+Enter" would save a pin that was meant to be discarded. The
// keyboard's focus shows the description on every device (the WAI-ARIA tooltip pattern): a tablet with a keyboard has
// no hover, and Tab there reaches controls whose explanation nothing else can show. A focus that follows a tap stays
// without one. A focus the page gives back itself (focusGivenBack) arms the box only when the keyboard had the focus
// there.
document.addEventListener('focusin', (event) => {
  const target = event.target as HTMLElement;
  if (FOCUS_GIVEN_BACK && !keyInput()) return;
  if ((target && target.tagName === 'TEXTAREA') || (!keyInput() && (touchRecent() || NO_HOVER_QUERY.matches))) {
    if (Date.now() >= SWALLOW_CLICK) hideTip();
    return;
  }
  armTip(target.closest ? target.closest('[data-tip]') : null);
});
// Esc closes a showing box first (the key dispatch, main.ts); one still waiting to show (armTip's 300ms) goes with
// any Esc, so it never opens after the key that dismissed it. A box over a control in an open sheet, menu or help (a
// modal dialog) takes its Esc here, before the dialog: the key dispatch leaves an open dialog's Esc to the browser,
// whose close request would take the box, the sheet and the focused control at once. Its default is prevented so the
// dialog stays; the next Esc closes it. While typing in a field the Esc goes on, as the key dispatch lets a field's Esc
// go on past the box.
function tipEscKey(event: KeyboardEvent) {
  if (event.key !== 'Escape') return;
  if (TIP.hidden) {
    hideTip();
    return;
  }
  const at = TIP_AT && TIP_AT.el;
  if (!at || !at.closest('dialog[open]') || typingNow()) return;
  hideTip();
  event.preventDefault();
  event.stopImmediatePropagation();
}
document.addEventListener('keydown', tipEscKey, true);
// Long-press tooltip (touch/pen): holding for 500ms shows the description, and the one click after release is swallowed
// (so the button doesn't fire). Over a page image, quick selection (long-press = that paragraph) takes priority, so
// only badges (.mark [data-act=mark-jump]) apply. Input fields keep their paste menu. A control that holds its hover
// and focus box back for a while - a page verdict line's words, [판정 취소] and earlier link while its save chip stands
// or its reason popover is open, its armed word (verdict/flow-line.ts) - carries the same description as
// data-tip-press, which only a long press shows. Without it a long press there would find no description, so nothing
// would swallow its release and the click would take the line's verdict back. A long press is the same press in every
// state. While a long press's description is up the page is html.tip-press: a verdict line's context over its words,
// which says the same, steps aside for it (verdict-reason.css).
let PRESS = null as { el: HTMLElement; x: number; y: number; t: ReturnType<typeof setTimeout>; shown?: boolean } | null,
  SWALLOW_CLICK = 0,
  TIP_HOLD = 0; // TIP_HOLD: the SWALLOW_CLICK a long press's release armed (0 for none)
/** Find a touch tooltip target while preserving native input menus and paragraph selection outside pin badges. */
function pressTarget(target) {
  const element = target && target.closest ? target.closest('[data-tip],[data-tip-press]') : null;
  if (!element) return null;
  if (element.tagName === 'TEXTAREA' || element.tagName === 'INPUT') return null;
  if (element.closest('.pg') && !element.closest('.mark [data-act=mark-jump]')) return null;
  return element;
}
document.addEventListener(
  'pointerdown',
  (event) => {
    if (SWALLOW_CLICK === TIP_HOLD) SWALLOW_CLICK = 0;
    // The click a long press's release held off comes before the next press: one that never came (a cancelled press)
    // must not take this tap's.
    TIP_HOLD = 0;
    if (event.pointerType === 'mouse') return;
    if (!TIP.hidden) hideTip();
    const element = pressTarget(event.target);
    if (!element) return;
    PRESS = {
      el: element,
      x: event.clientX,
      y: event.clientY,
      t: setTimeout(() => {
        const text = element.dataset.tip || element.dataset.tipPress || '';
        showTipText(element, text);
        if (!TIP.hidden) document.documentElement.classList.add('tip-press');
        if (PRESS) PRESS.shown = true;
        SWALLOW_CLICK = TIP_HOLD = Date.now() + 900;
        setTimeout(() => {
          if (!TIP.hidden && TIP.textContent === text) hideTip();
        }, 4000);
      }, 500),
    };
  },
  true,
);
function endPress() {
  if (PRESS) {
    clearTimeout(PRESS.t);
    PRESS = null;
  }
}
document.addEventListener(
  'pointermove',
  (event) => {
    if (PRESS && Math.hypot(event.clientX - PRESS.x, event.clientY - PRESS.y) > 10) endPress();
  },
  true,
);
// The release of the press that opened the description is when the click it ends with is swallowed: the window set when
// the box opened (900ms) is over for a finger held longer (1.6s), whose release would reach the button. Re-armed at the
// release, the swallowing is as long as the press. (A cancelled press ends without a click, so it re-arms nothing.)
document.addEventListener(
  'pointerup',
  () => {
    if (PRESS && PRESS.shown) SWALLOW_CLICK = TIP_HOLD = Date.now() + 900;
    endPress();
  },
  true,
);
// A cancelled press (the browser took the touch for a scroll or a gesture) ends without a click: the hold its
// description armed goes with it, or a tap in the next 900ms would be the one swallowed.
document.addEventListener(
  'pointercancel',
  () => {
    if (SWALLOW_CLICK === TIP_HOLD) SWALLOW_CLICK = 0;
    TIP_HOLD = 0;
    endPress();
  },
  true,
);
document.addEventListener(
  'click',
  (event) => {
    if (Date.now() < SWALLOW_CLICK) {
      SWALLOW_CLICK = 0;
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  },
  true,
);
// Inside that window a touch's compatibility mousedown must not move focus either: after a quick pick opens the sheet
// under the finger it would focus the note field and raise the virtual keyboard.
document.addEventListener(
  'mousedown',
  (event) => {
    if (Date.now() < SWALLOW_CLICK && LAST_POINTER !== 'mouse') event.preventDefault();
  },
  true,
);
document.addEventListener('contextmenu', (event) => {
  if (LAST_POINTER === 'mouse') return;
  const target = event.target as HTMLElement;
  if (target && target.closest && (target.closest('.pg') || pressTarget(target))) event.preventDefault();
});
document.addEventListener('input', hideTip, true);
document.addEventListener('focusout', hideTip);
// A scroll moves what a box stands by, so the box goes. A description still waiting for the keyboard's focus waits
// again instead: Tab scrolls the control it reaches into view, and that scroll would take the description the focus
// asked for.
document.addEventListener(
  'scroll',
  () => {
    const element = TIP.hidden ? armedTipElement : null;
    hideTip();
    if (element && element.contains(document.activeElement) && keyInput()) armTip(element);
  },
  true,
);
// Releasing right after a long-press opens it, Chrome sends a simulated mousedown - that alone must never close it.
document.addEventListener(
  'mousedown',
  () => {
    if (Date.now() >= SWALLOW_CLICK) hideTip();
  },
  true,
);
// Explanations for screen readers: an explanation (data-tip, else data-tip-press) reaches a screen reader as well as
// the box (docs/handbook/viewer.md §설명과 접근성). A control that takes focus carries it as its description
// (aria-description), read with its name when it is focused. A badge takes no focus, so it carries it as words after
// its own that only a screen reader reads: data-tip-sr, drawn as clipped generated content (components.css
// [data-tip-sr]::after). The card is read with them, and nothing on screen or in the Tab order changes; being generated
// content they are neither copied with a selection nor found by the browser's find, as a hidden text node would be (an
// invisible find result, a pasted explanation). A label that marks itself .tip-read does the same (the composer's
// reason where [제안 수정] cannot go). Each copy is made from the attribute as it stands whenever it changes - after
// the English observer rewrites it too, so it speaks the screen's language and is never translated again
// (aria-description and data-tip-sr are not I18N_ATTRS). What repeats the name adds nothing: a tip that is the name
// gives no description, and one that starts with the name and a separator ('폭 맞춤: …') gives what follows. A control
// whose drawing code sets its own description (aria-describedby, or an aria-description it wrote - the composer's
// element path) keeps that one. A badge named by its own aria-label (an old verdict's marker) is read by that label,
// and one inside a control adds nothing to that control's name. A card's fact line (its assignee chip, .as-chip) is
// read as one line of its own words (종류 · 담당 · 상태, cards.css): its explanation is the general rule that a
// person's pin is skipped, which on every such card would only repeat; the chip that can be pressed carries it as its
// description. A badge whose card says its explanation in a visible line (.tip-shown: a [제안 수정] warning badge,
// whose card says the agent will not apply it) adds nothing either: that line is read with the card.
const TIP_FOCUS = 'button,a[href],input,select,textarea,summary,[tabindex]',
  TIP_SELECTOR = '[data-tip],[data-tip-press]',
  TIP_READ = '.badge:not(.as-chip,.tip-shown),.tip-read';
// The descriptions this part wrote, so one the drawing code wrote is told apart and left alone.
const TIP_WROTE = new WeakMap() as WeakMap<Element, string>;
/** What `tip` says beyond `name`: '' when it is the name, the rest after the name and a separator when it starts with
 * them, else `tip` (whitespace collapsed). The name's words may be set apart by a colon in the tip ('담당 Bob Park' in
 * '담당: Bob Park — …'). Pure. */
function descriptionBeyondName(tip: string, name: string) {
  const tipText = String(tip || '')
      .replace(/\s+/g, ' ')
      .trim(),
    words = String(name || '')
      .replace(/\s+/g, ' ')
      .trim()
      .split(' ');
  if (!tipText) return '';
  if (!words[0]) return tipText;
  const head = '^' + words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[: ]+');
  if (new RegExp(head + ':?$').test(tipText)) return '';
  const match = new RegExp(head + ' ?[:\u2014\u00b7] (.+)$').exec(tipText);
  return match ? match[1] : tipText;
}
/** An element's own name as a screen reader hears it: its aria-label, else its words. */
function tipOwnName(element: Element) {
  const label = element.getAttribute('aria-label');
  return label && label.trim() ? label : element.textContent || '';
}
/** Puts an element's explanation where a screen reader finds it (above), or takes away the copy of one that went. */
function tipDescribe(element: Element) {
  const tip = element.getAttribute('data-tip') || element.getAttribute('data-tip-press') || '';
  if (element.matches(TIP_FOCUS)) {
    element.removeAttribute('data-tip-sr');
    if (element.hasAttribute('aria-describedby')) return;
    const current = element.getAttribute('aria-description');
    if (current !== null && TIP_WROTE.get(element) !== current) return; // the drawing code's own
    const description = descriptionBeyondName(tip, tipOwnName(element));
    if (description) {
      if (description !== current) {
        element.setAttribute('aria-description', description);
        TIP_WROTE.set(element, description);
      }
    } else if (current !== null) {
      element.removeAttribute('aria-description');
      TIP_WROTE.delete(element);
    }
    return;
  }
  if (!element.matches(TIP_READ)) return;
  // its words are a control's name: no more in it
  const inside = !!element.parentElement && !!element.parentElement.closest(TIP_FOCUS);
  const description =
    inside || element.hasAttribute('aria-label') ? '' : descriptionBeyondName(tip, tipOwnName(element));
  if (!description) {
    element.removeAttribute('data-tip-sr');
    return;
  }
  if (element.getAttribute('data-tip-sr') !== ': ' + description)
    element.setAttribute('data-tip-sr', ': ' + description);
}
/** tipDescribe for node and everything under it that has an explanation. */
function tipDescribeTree(node: Node) {
  if (node.nodeType !== 1) return;
  const element = node as Element;
  if (element.matches(TIP_SELECTOR)) tipDescribe(element);
  for (const descendant of element.querySelectorAll(TIP_SELECTOR)) tipDescribe(descendant);
}
// Kept in step with every drawing: an element drawn, an explanation, a name or a tab stop changed, or the words of an
// element with an explanation (its name) rewritten.
new MutationObserver((mutations) => {
  for (const mutation of mutations) {
    const target = mutation.target;
    if (mutation.type === 'attributes') {
      tipDescribe(target as Element);
      continue;
    }
    if (mutation.type === 'childList') mutation.addedNodes.forEach(tipDescribeTree);
    const host = target.nodeType === 1 ? (target as Element) : target.parentElement;
    const owner = host && host.closest(TIP_SELECTOR);
    if (owner) tipDescribe(owner);
  }
}).observe(document.body, {
  childList: true,
  subtree: true,
  characterData: true,
  attributes: true,
  attributeFilter: ['data-tip', 'data-tip-press', 'aria-label', 'aria-describedby', 'tabindex'],
});
tipDescribeTree(document.body);
// Sets SWALLOW_CLICK, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setSwallowClick<Value extends typeof SWALLOW_CLICK>(value: Value): Value {
  SWALLOW_CLICK = value;
  return value;
}
export {
  SWALLOW_CLICK,
  TIP,
  TIP_AT,
  endPress,
  focusGivenBack,
  hideTip,
  keyInput,
  setSwallowClick,
  showTip,
  showTipText,
  armedTipElement,
  tipFollow,
  NO_HOVER_QUERY,
  LAST_POINTER,
  LAST_TOUCH_AT,
  setLastPointer,
  setLastTouchAt,
  MARK_HIDDEN,
};
