import { IME_ON_FREE, imeKey, imeTail, EDITOR, REPLY } from '../app/state.ts';
import { pageVerdictsOn } from '../documents/state.ts';
import { isAutoScrolling } from '../layout/flow-scroll.ts';
import { gotoPinRef } from '../pins/flow-list.ts';
import { $, eventElement, isDisabled, findAll, eventClosest, typingNow, findClosest } from '../platform/dom.ts';
import { lineNote } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { hideTip } from '../platform/tooltip.ts';
import { followLanded } from './flow-reason-write.ts';
import {
  escapeReason,
  saveReason,
  openPendingReason,
  currentLineVerdict,
  openReason,
  clearReason,
  foldReason,
  writeOverNewer,
  hasUnsavedDrafts,
} from './flow-reason.ts';
import type { ReasonPart } from './state-drafts.ts';
import { editParts } from './state-drafts.ts';
import { KEY_SAVE_OUT, pageLineSlot, SAVING_LINES } from './state-lines.ts';
import type { ReasonSession, ReasonHist } from './state-reason.ts';
import { REASON_SESSION, KEY_GUARD, setKeyGuard, disarmReasonEscape, keepDraft } from './state-reason.ts';
import { redrawOnBesideChange, pageUnderReadingLine, sayGliding } from './view-panel.ts';
import { canVerdict, pageTakesVerdict, canCancelVerdict } from './view-pins.ts';
import {
  isReasonField,
  setComposingField,
  isComposingNow,
  COMPOSING_FIELD,
  findReasonField,
} from './view-reason-field.ts';
import { growReasonField, refillLine, closeReasonPopover } from './view-reason.ts';

$('#doc').addEventListener('compositionstart', (event: CompositionEvent) => {
  if (isReasonField(event.target)) setComposingField(event.target);
});

// The composition's end settles what it brought back (followLanded, which waits for it), and what waited for it goes on
// (runComposedWaits).
$('#doc').addEventListener('compositionend', (event: CompositionEvent) => {
  const field = event.target;
  if (!isReasonField(field)) return;
  setComposingField(null);
  const session = REASON_SESSION;
  if (session && field.dataset.id === 's' + session.sid) {
    followLanded(session);
    if (REASON_SESSION === session) keepDraft(session);
  }
  setTimeout(runComposedWaits, 0);
});

const COMPOSED_WAITS: (() => void)[] = []; // what waits for the composition's end (afterComposition)

// how often a wait looks again: a field taken out of the document ends its composition without the event
const COMPOSED_POLL_MS = 200;

// Resolves once no syllable is being composed in a reason field and the key that ended one has let it go
// (isComposingNow) - at once when none is.
function afterComposition(): Promise<void> {
  return new Promise((resolve) => {
    if (!isComposingNow()) {
      resolve();
      return;
    }
    const go = () => {
        clearInterval(timer);
        resolve();
      },
      timer = setInterval(() => {
        if (!isComposingNow()) go();
      }, COMPOSED_POLL_MS);
    COMPOSED_WAITS.push(go);
  });
}

// After a composition ended, unless another began meanwhile or the key that ended it still holds the field: the
// rebuilds that waited go on, and the lines move if the room crossed its bar while it lasted. Held, it looks again once
// that key lets the field go (app/state.ts IME_ON_FREE): up, another key, forgotten, or IME_HOLD_MS with no event of
// its own.
function runComposedWaits() {
  if (isComposingNow()) return;
  COMPOSED_WAITS.splice(0).forEach((go) => go());
  if (pageVerdictsOn()) redrawOnBesideChange();
}

IME_ON_FREE.push(runComposedWaits);

// The parts of a session's text once an input made it its text from `was`, the caret at `caret`. A text the field held
// before - back by an undo or a redo, a paste or a typed letter taken back, a composition given up - has the parts it
// had then: an edit inside a part lets it go (editParts), so without these records the undo that puts the text back
// would leave it with none, the text would not be known as moved off its pin, and a write that lands there would leave
// it in the copy, to be written twice. The undo and redo records are the texts kept (hist.seen, the newest parts for
// each text), with their parts - their lost writes kept up to date (updateEvidence) and the writes that landed
// meanwhile on the pins they came from (hist.landed, followLanded) -, since the session's text or parts were last set
// from elsewhere: opened, moved to a new verdict, a part taken out. What the field held before that is not this
// session's to come back to with those parts - a part taken out because its text landed on its pin and typed back is a
// new reason, as it is when it is typed again (and the browser lets the field's own undo records go when its text is
// set). Any other text is placed by editParts. Texts with parts are kept until then, however many: letting one go, the
// undo past it would bring the text back without its part again. Texts without one go oldest first past HISTORY_CHARS
// characters - one missed is placed by editParts, which may keep a part the text had meanwhile, never invents one.
const HISTORY_CHARS = 200000;

function placeParts(session: ReasonSession, was: string, caret: number): ReasonPart[] {
  const same = (x: ReasonPart[], y: ReasonPart[]) =>
    x.length === y.length &&
    x.every((part, index) => part.k === y[index].k && part.s === y[index].s && part.e === y[index].e);
  let history = session.hist;
  if (!history || history.last.text !== was || !same(history.last.via, session.via)) {
    history = { last: { text: was, via: session.via }, seen: new Map(), size: 0, landed: [] };
    keepHistory(history, was, session.via);
  }
  const back = history.seen.get(session.text),
    via = back !== undefined ? back : editParts(session.via, was, session.text, caret);
  keepHistory(history, session.text, via);
  history.last = { text: session.text, via };
  session.hist = history;
  return via;
}

// A history keeps text with its parts, as the newest; past HISTORY_CHARS it lets the oldest texts without a part go.
function keepHistory(history: ReasonHist, text: string, via: ReasonPart[]) {
  if (history.seen.has(text)) {
    history.size -= text.length;
    history.seen.delete(text);
  }
  history.seen.set(text, via);
  history.size += text.length;
  for (const [keptText, keptParts] of history.seen) {
    if (history.size <= HISTORY_CHARS) break;
    if (keptParts.length || keptText === text) continue;
    history.seen.delete(keptText);
    history.size -= keptText.length;
  }
}

// Keys in the field: Enter saves (Shift+Enter is a new line), Esc closes or takes two presses with text. Every other
// key is the field's own - digits included. Nothing while an input method composes. Esc on the popover's buttons
// ([접기], [닫기], [저장], [지우기]) is the field's Esc.
$('#doc').addEventListener('keydown', (event: KeyboardEvent) => {
  const target = eventElement(event);
  if (
    event.key === 'Escape' &&
    !isReasonField(target) &&
    REASON_SESSION &&
    target &&
    target.closest('#doc .pv-pop') &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey
  ) {
    event.preventDefault();
    event.stopPropagation();
    hideTip();
    escapeReason('key');
    return;
  }
});

$('#doc').addEventListener('keydown', (event: KeyboardEvent) => {
  const field = event.target;
  if (!isReasonField(field)) return;
  if (imeKey(event)) {
    if (imeTail(event)) event.preventDefault();
    return;
  } // the Enter that ended a composition adds no new line either
  if (event.key === 'Enter' && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
    event.preventDefault();
    event.stopPropagation();
    saveReason(field);
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    escapeReason('key');
  }
});

// While a popover is open, Tab and Shift+Tab keep to it and its line, from anywhere in either: past the last control
// (the popover's) the focus goes to the line's first, and before the first (the line's) to the popover's last. The
// DOM's next or previous stop is another page's line, whose focus would scroll the reading page away and close the
// popover, writing what is being edited.
$('#doc').addEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return;
  const target = eventElement(event),
    line = target ? target.closest('#doc .pv') : null;
  const pop = line && line.querySelector(':scope>.pv-pop');
  if (!line || !pop) return;
  const vis = (x: HTMLElement) => x.getClientRects().length > 0 && !isDisabled(x);
  const all = findAll(line, 'a,button,textarea,[tabindex="0"]', HTMLElement).filter(vis);
  if (all.length < 2) return;
  if (!event.shiftKey && target === all[all.length - 1]) {
    event.preventDefault();
    all[0].focus({ preventScroll: true });
  } else if (event.shiftKey && target === all[0]) {
    event.preventDefault();
    all[all.length - 1].focus({ preventScroll: true });
  }
});

// The field's focus changes what it says (the keys). The popover stays open while the focus is anywhere inside it - Tab
// from the field to its buttons included - and an empty one closes when the focus leaves it for somewhere else (a press
// on its own buttons never closes it, even where a press does not move the focus).
let POPOVER_PRESS_AT = 0; // performance.now() of the last press inside a popover

$('#doc').addEventListener(
  'pointerdown',
  (event: PointerEvent) => {
    if (eventClosest(event, '.pv-pop', Element)) POPOVER_PRESS_AT = performance.now();
  },
  true,
);

$('#doc').addEventListener('focusin', (event: FocusEvent) => {
  if (!isReasonField(event.target) || !REASON_SESSION) return;
  disarmReasonEscape(REASON_SESSION);
  refillLine(REASON_SESSION.page);
});

$('#doc').addEventListener('focusout', (event: FocusEvent) => {
  const pop = eventClosest(event, '.pv-pop', Element);
  if (!pop) return;
  const rel = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (rel && pop.contains(rel)) return;
  setTimeout(() => {
    const session = REASON_SESSION;
    if (
      !session ||
      pop.getAttribute('data-id') !== 's' + session.sid ||
      !pop.isConnected ||
      pop.contains(document.activeElement)
    )
      return;
    const field = findReasonField();
    if (
      field &&
      !field.disabled &&
      !field.value.trim() &&
      !session.writing &&
      performance.now() - POPOVER_PRESS_AT > 600
    ) {
      closeReasonPopover(false);
      return;
    }
    refillLine(session.page);
  }, 0);
});

// The second Esc after a first one from the field (the focus is then on the PDF area): it drops the draft - unless
// something on top answers Esc first (a dialog, a popover, the composer, an edit or a reply).
function dropOnSecondEsc(event: KeyboardEvent) {
  if (
    event.key !== 'Escape' ||
    event.defaultPrevented ||
    !REASON_SESSION ||
    REASON_SESSION.escArm !== 'key' ||
    typingNow()
  )
    return;
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden ||
    EDITOR.current ||
    REPLY
  )
    return;
  event.preventDefault();
  event.stopImmediatePropagation();
  escapeReason('key');
}

document.addEventListener('keydown', dropOnSecondEsc);

// Enter on the pages - the focus on the PDF area, the page itself or nothing - opens the reading page's reason popover
// with the focus, for the person's own open current verdict there ('Enter 이유 쓰기' on its line). A control's own
// Enter stays its own, and so does anything on top (a dialog, a popover, the composer, an edit or a reply). Not while
// the pages are still gliding to where a jump sends them (isAutoScrolling): the reading page is not yet the one asked
// for. While that page's save is still out the popover opens bound to it (openPendingReason) - a key and Enter at once
// is one intent.
function openReasonOnEnter(event: KeyboardEvent) {
  if (
    event.key !== 'Enter' ||
    event.defaultPrevented ||
    imeKey(event) ||
    event.ctrlKey ||
    event.metaKey ||
    event.altKey ||
    event.shiftKey ||
    event.repeat
  )
    return;
  const target = eventElement(event),
    area = $('#left');
  // On a control of the line whose digit key's save is out the Enter is that intent too: the focus may rest on any of
  // them.
  const line = !!target && !target.closest('.pv-pop') ? findClosest(target, '#doc .pv', HTMLElement) : null,
    page = line ? Number(line.dataset.page) || 0 : 0;
  if (page && KEY_SAVE_OUT.has(pageLineSlot(page)) && page === pageUnderReadingLine()) {
    event.preventDefault();
    event.stopImmediatePropagation();
    openPendingReason(page);
    return;
  }
  if (!(
    target === document.body ||
    target === area ||
    target === $('#doc') ||
    (!!target && !!target.closest('#doc .pg'))
  ))
    return;
  openReadingReason(event);
}

// Enter taken as pressed on the pages (openReasonOnEnter, or one on an off-screen line's control, stopOffPageKey): the
// reading page's reason - its popover, or a pending one while its save is out.
function openReadingReason(event: KeyboardEvent) {
  if (
    document.querySelector('dialog[open]') ||
    !$('#page-pop').hidden ||
    !$('#doc-pop').hidden ||
    !$('#composer').hidden ||
    EDITOR.current ||
    REPLY ||
    !canVerdict()
  )
    return;
  const page = pageUnderReadingLine();
  if (!page || !pageTakesVerdict(page)) return;
  if (SAVING_LINES.has(pageLineSlot(page))) {
    event.preventDefault();
    event.stopImmediatePropagation();
    openPendingReason(page);
    return;
  } // the save is out: the Enter is the intent to write
  const cur = currentLineVerdict(page);
  if (!cur || !canCancelVerdict(cur)) return;
  event.preventDefault();
  event.stopImmediatePropagation();
  if (isAutoScrolling()) {
    sayGliding();
    return;
  }
  openReason(page, true);
}

document.addEventListener('keydown', openReasonOnEnter);

// Whether a verdict key falls under that guard - said once on the status line when it does.
function isKeyGuarded(event: KeyboardEvent) {
  if (!KEY_GUARD) return false;
  event.preventDefault();
  lineNote(
    '이유 칸이 닫혀 숫자를 판정으로 받지 않았습니다 — Esc를 누르거나 쪽을 누른 뒤 다시 누릅니다',
    NOTICE_KIND.INFO,
    null,
    { source: 'verdict-key-guard', life: NOTICE_LIFE.TIMER },
  );
  return true;
}

// A popover's buttons and the line's reason (main.ts).
function actOnReason(control: HTMLElement) {
  const act = control.dataset.act,
    line = control.closest('.pv'),
    page = Number(line && line.getAttribute('data-page')) || 0;
  if (act === 'pv-reason-open') {
    openReason(page, true);
    return;
  }
  if (act === 'pv-reason-close') {
    escapeReason('btn');
    return;
  }
  if (act === 'pv-reason-clear') {
    clearReason();
    return;
  }
  if (act === 'pv-reason-fold') {
    foldReason();
    return;
  }
  if (act === 'pv-reason-reapply') {
    writeOverNewer();
    return;
  }
  if (act === 'pv-reason-see') {
    if (REASON_SESSION) gotoPinRef(REASON_SESSION.id, true);
    return;
  }
  const field = findReasonField();
  if (act === 'pv-reason-save' && field) saveReason(field);
}

// Leaving the page (a reload, closing the tab, another address) with a reason not written yet asks first. The draft is
// kept either way for this tab: a reload brings it back.
window.addEventListener('beforeunload', (event) => {
  if (!hasUnsavedDrafts()) return;
  event.preventDefault();
  event.returnValue = '';
});

function watchReasonInput() {
  // Every input keeps the draft (putDraft), with the parts moved into it placed where they are now (placeParts) - a part
  // brought back whose text has landed on its pin meanwhile leaves at once (followLanded), or once an input method's
  // composition ends - and lets a first Esc go; the line follows its emptiness (the state).
  $('#doc').addEventListener('input', (event: InputEvent) => {
    const field = event.target;
    if (!isReasonField(field)) return;
    const session = REASON_SESSION;
    if (!session || field.dataset.id !== 's' + session.sid) return;
    const was = session.text;
    session.text = field.value;
    session.via = placeParts(session, was, field.selectionEnd);
    disarmReasonEscape(session);
    if (COMPOSING_FIELD !== field) followLanded(session);
    keepDraft(session);
    growReasonField(field);
    refillLine(session.page);
  });
  window.addEventListener(
    'pointerdown',
    () => {
      setKeyGuard(false);
    },
    true,
  );
  window.addEventListener(
    'keydown',
    (event) => {
      if (event.key === 'Escape') setKeyGuard(false);
    },
    true,
  );
}

export { actOnReason, afterComposition, isKeyGuarded, openReadingReason, watchReasonInput };
