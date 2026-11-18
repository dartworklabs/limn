import { verdictOf } from '../app/rules-pins.ts';
import { VERDICT_PLACE, REQUEST_KIND, ASSIGNEE_AGENT } from '../app/rules-tables.ts';
import { isMe } from '../app/state-people.ts';
import type { Visit } from '../app/state.ts';
import {
  COMPOSE,
  isFigureKind,
  META,
  DOC,
  captureVisit,
  OPEN_ALL,
  DEFAULT_DOC,
  topPinId,
  currentVisit,
} from '../app/state.ts';
import { savePin } from '../composer/flow-save.ts';
import { refreshDoc } from '../documents/flow-rebuild.ts';
import { docVerdicts, viewerBlocked, isRegion, pdoc, verdictLabel } from '../documents/state.ts';
import { figureFields } from '../pdf/view-figure.ts';
import { loadPins } from '../pins/flow-list.ts';
import { api, isRefusal, isApiError } from '../platform/api.ts';
import { focusedElement, findMaybe } from '../platform/dom.ts';
import { translateTemplate, translate, errText } from '../platform/i18n.ts';
import { lineNote, sourceOk, undoNote, settleChip } from '../platform/notices.ts';
import { SECTION_SEEN } from '../platform/prefs.ts';
import { NOTICE_KIND, NOTICE_LIFE, NOTICE_PLACE } from '../platform/tables.ts';
import { hideTip } from '../platform/tooltip.ts';
import { CANCEL_HOLD_MS, cancelVerdictPin, verdictUndo } from './flow-cancel.ts';
import { drawPageVerdicts } from './flow-line.ts';
import { followSaveWithReason, settleFailedCancelDraft } from './flow-reason-transfer.ts';
import { keepUnboundReason, settleDetachedReason } from './flow-reason.ts';
import {
  whereOfButton,
  isArmedHere,
  ARMED_VERDICT,
  armStillHolds,
  armVerdict,
  refocusVerdictButton,
  disarmVerdict,
  renderVerdictRow,
  pressedAsOf,
  PRESSED_AS,
} from './flow-words.ts';
import {
  SAVING_LINES,
  pageLineSlot,
  NEXT_PRESS,
  TAKEN_BACK_HOLD,
  KEY_SAVE_OUT,
  LINE_SAVE_ERROR,
  LINE_UNDO_OFFERS,
} from './state-lines.ts';
import { REASON_SESSION } from './state-reason.ts';
import {
  pageVerdictPins,
  canCancelVerdict,
  pageTargetShort,
  WHOLE_PAGE,
  pageTargetOf,
  currentVerdictOn,
} from './view-pins.ts';
import { focusLine } from './view-reason.ts';

// A press on a verdict button: a confirm word arms on the first press and saves on the second while what it is bound to
// holds; any other word saves at once - the composer's through savePin, a page line's through pressPageVerdict. how:
// 'key' for a digit key (verdictKey, or one in an empty reason field), 'kb' for a click the keyboard made (Enter or
// Space on the button); a page line's save from either opens its reason popover with the focus.
function verdictPress(button: HTMLElement, how?: string) {
  const key = button.dataset.key || '',
    where = whereOfButton(button),
    page = Number(button.dataset.page) || 0,
    verdicts = docVerdicts(),
    choice = verdicts && verdicts.choices.find((x) => x.key === key);
  if (!choice || button.getAttribute('aria-disabled') === 'true' || viewerBlocked()) return;
  if (where !== VERDICT_PLACE.COMPOSER) {
    pressPageVerdict(choice, page, how);
    return;
  }
  if (choice.confirm && !(isArmedHere(key, where, page) && ARMED_VERDICT && armStillHolds(ARMED_VERDICT))) {
    const focused = focusedElement();
    armVerdict(key, where, page, choice.label, how === 'key');
    refocusVerdictButton(focused && focused.closest('.vd-btns') ? focused : null);
    return;
  }
  disarmVerdict(false);
  hideTip();
  renderVerdictRow();
  if (COMPOSE.current) savePin(key);
} // while the pick runs the row is off (composer.css): nothing is queued

// A press of word `choice` on page `page`'s line, a toggle:
// - While a save on the line is out (SAVING_LINES) the press is the line's next intent: the last press wins
//   (NEXT_PRESS) and is applied when the save is done - a word already current then does nothing. Nothing is dropped
//   and nothing is toggled off meanwhile: the line ends on the last word pressed.
// - The pressed word (the line's current verdict): the person's own open verdict is taken back as [판정 취소] does
//   (cancelVerdictPin, with its [되돌리기]); anyone else's, or a handled one, is not - the status line says why.
//   Pressing a word never makes a second pin of the word that is current. Right after it was taken back the same word
//   waits CANCEL_HOLD_MS (TAKEN_BACK_HOLD): a double press takes back one verdict and does not save it again.
// - Any other word saves (savePageVerdict), a confirm word on its second press.
function pressPageVerdict(choice: VerdictChoice, page: number, how?: string) {
  const key = choice.key,
    where = VERDICT_PLACE.PAGE,
    armed = isArmedHere(key, where, page) && !!ARMED_VERDICT && armStillHolds(ARMED_VERDICT);
  const arm = () => {
    const focused = focusedElement();
    hideTip(); // no box over the armed word (it says its wait beside it)
    armVerdict(key, where, page, choice.label, how === 'key');
    refocusVerdictButton(focused && focused.closest('.vd-btns') ? focused : null);
  };
  if (SAVING_LINES.has(pageLineSlot(page))) {
    if (choice.confirm && !armed) {
      arm();
      return;
    }
    disarmVerdict(false);
    hideTip();
    NEXT_PRESS.set(pageLineSlot(page), { key, how: how || '' });
    drawPageVerdicts();
    return;
  }
  const cur = (pageVerdictPins().get(page) || [])[0];
  if (cur && verdictOf(cur) === key) {
    const hold = TAKEN_BACK_HOLD.get(pageLineSlot(page));
    if (hold && hold.key === key && hold.until > Date.now()) return;
    disarmVerdict(false);
    hideTip();
    if (canCancelVerdict(cur)) {
      TAKEN_BACK_HOLD.set(pageLineSlot(page), { key, until: Date.now() + CANCEL_HOLD_MS });
      setTimeout(() => drawPageVerdicts(), CANCEL_HOLD_MS + 20);
      cancelVerdictPin(cur.id, page, !!how, how === 'key');
      return;
    } // by a key: the focus goes to the line's [되돌리기]
    lineNote(
      translateTemplate('지금 판정 #{id} {word} 그대로 · {why} — {target}', {
        id: cur.id,
        word: choice.label,
        target: pageTargetShort(page),
        why:
          pressedAsOf(cur) === PRESSED_AS.HANDLED
            ? translate('처리된 판정은 카드의 [지우기]로 거둡니다')
            : translate('다른 사람의 판정은 여기서 거두지 않습니다'),
      }),
      NOTICE_KIND.INFO,
      null,
      { source: 'pv-press', life: NOTICE_LIFE.TIMER, literal: true },
    );
    return;
  }
  if (choice.confirm && !armed) {
    arm();
    return;
  }
  disarmVerdict(false);
  hideTip(); // the box the press's focus armed: the save chip comes over the line (CHIP_WATCH)
  if (how === 'key') KEY_SAVE_OUT.add(pageLineSlot(page));
  savePageVerdict(page, key, !!how);
}

// ---------------- The page verdict line (figure documents and view-only PDFs, page: true)
// The pin body a page verdict saves from the whole page's pick answer (D7): on a figure document the rung whose element
// is the page's figure (el.path == [el.id]) - its lines and element - else a region answer whose element is that
// figure, else
// - the pick chose an element inside the figure: one covering 40% of the page wins a whole-page drag (pick_element) - a
// region over the whole page naming the figure, the root of that element's path, as the composer's verdict saves it
// (figureVerdictBody, ADR-0022 D2); on a view-only PDF the region answer as it is. null when a figure page's answer
// names no element (its map could not be read). Pure but for the figure helpers.
function pageVerdictBody(answer: PickAnswer, kind: string | undefined): Record<string, unknown> | null {
  const root = (element: PinElement | undefined) =>
    !!element && Array.isArray(element.path) && element.path.length === 1 && element.path[0] === element.id;
  if (isFigureKind(kind)) {
    const rung = isRegion(answer) ? null : (answer.levels || []).find((candidate: Rung) => root(candidate.el));
    if (rung)
      return figureFields(
        {
          file: answer.file,
          name: answer.name,
          page: answer.page,
          lo: rung.lo,
          hi: rung.hi,
          raw_lo: answer.raw_lo,
          raw_hi: answer.raw_hi,
          via: answer.via,
          score: answer.score,
          frac: answer.frac,
          quote: answer.quote,
          pdf_build: answer.pdf_build || undefined,
          scope: rung.level,
        },
        rung.el,
        rung,
      );
    if (isRegion(answer) && root(answer.el))
      return figureFields(
        { page: answer.page, frac: answer.frac, quote: answer.quote, pdf_build: answer.pdf_build || undefined },
        answer.el,
        null,
      );
    const figure = answer.el && Array.isArray(answer.el.path) ? answer.el.path[0] : null;
    if (typeof figure === 'string' && figure)
      return figureFields(
        { page: answer.page, frac: WHOLE_PAGE.slice(), quote: '', pdf_build: answer.pdf_build || undefined },
        { id: figure, path: [figure], frac: WHOLE_PAGE.slice() },
        null,
      );
    return null;
  }
  return isRegion(answer)
    ? { page: answer.page, frac: answer.frac, quote: answer.quote, pdf_build: answer.pdf_build || undefined }
    : null;
}

// What a press on page `page` of the document on screen saves against: its document, kind, build and page size and its
// target's name, with the visit it was made in. A save runs on these - not on the document on screen when it runs - so
// a press made before switching documents is saved, and one queued meanwhile is too (pressPageVerdict,
// savePageVerdict). null when the page is not there.
function pageSaveContext(page: number): {
  doc: string | null;
  kind: string | undefined;
  build: string;
  w: number;
  h: number;
  target: string;
  visit: Visit;
} | null {
  const facts = META && META.pages[page - 1];
  if (!META || !facts) return null;
  return {
    doc: DOC,
    kind: META.kind,
    build: META.pages_build || '',
    w: facts.pt_w,
    h: facts.pt_h,
    target: pageTargetShort(page),
    visit: captureVisit(),
  };
}

// A verdict pin this person saved with word key about page `page` of document doc since pin number top - a save whose
// answer was lost may have landed: it is read again before the press is called a failure, or pressed again (a
// duplicate).
function findLandedVerdict(
  doc: string | null,
  page: number,
  key: string,
  top: number,
  kind: string | undefined,
): Pin | null {
  return (
    OPEN_ALL.find(
      (pin) =>
        pin.id > top &&
        pdoc(pin) === (doc || DEFAULT_DOC) &&
        verdictOf(pin) === key &&
        isMe(pin.author) &&
        (() => {
          const target = pageTargetOf(pin, kind);
          return !!target && target.page === page;
        })(),
    ) || null
  );
}

// Saves word key as a verdict about page `page`'s whole target: a pick of the whole page on the build it was pressed
// on, the body pageVerdictBody makes of it, with no note, saved as a fix request for the agent. The composer's
// selection and draft stay as they are. The word becomes the page's current verdict - a new pin (the agent runs the
// newest, D4 and D5); pressing the current word takes it back instead (pressPageVerdict). It runs on its press's
// context (pageSaveContext): leaving the document while it runs does not drop it - it completes, and its undo is
// offered on the status line. Saved: '#42 저장됨 [되돌리기]' on the line for NOTICE_MS. An answer lost on the network -
// or a 5xx, which a server may send after writing - is checked against the list before anything is said
// (findLandedVerdict): a verdict that landed is a save, not a failure a second press would duplicate. A refusal or a
// failure is said on the status line, result first ('판정 저장 실패 · <까닭> — <대상>'), and under the pressed line.
// While it is out the line says what it saves ('보류 저장 중…') and presses wait in NEXT_PRESS; the last of them is
// applied after it - also after a switch away and back, on the document it was pressed on - unless that word is the
// page's verdict by then. No save opens the reason popover: the line offers [이유 추가], and 'Enter 이유 쓰기' while
// the keys act on it.
/** @param [byKeyboard] - pressed from the keyboard: the focus goes to the line's way to the reason */
async function savePageVerdict(
  page: number,
  key: string,
  byKeyboard?: boolean,
  givenContext?: ReturnType<typeof pageSaveContext>,
) {
  const context = givenContext || pageSaveContext(page);
  if (!context) return;
  const slot = pageLineSlot(page, context.doc);
  if (SAVING_LINES.has(slot)) return;
  const visit = context.visit,
    here = () => DOC === context.doc;
  const fail = (text: string) => {
    if (here()) LINE_SAVE_ERROR.set(page, { text, doc: context.doc, build: context.build });
  };
  // Said on the status line with what it was for, result first, and under the pressed line.
  const failed = (why: string) => {
    lineNote(
      translateTemplate('판정 저장 실패 · {why} — {target}', { why, target: context.target }),
      NOTICE_KIND.ERR,
      null,
      {
        source: 'page-verdict',
        literal: true,
      },
    );
    fail(translateTemplate('{what} 실패', { what: translate('판정 저장') }) + ' — ' + why);
  };
  let saved = false,
    got = 0;
  if (here()) LINE_SAVE_ERROR.delete(page);
  // A key save (a digit, Enter or Space on a word) hands the focus to the line's way to the reason ('Enter 이유 쓰기'),
  // so Enter there opens it - on the pressed word Enter would take the verdict back - unless the person put the focus
  // anywhere else meanwhile (another page's word, a '#N' link, the panel): a redraw that puts it back on the same
  // word's button is no move.
  let away = false;
  const moved = (event: FocusEvent) => {
    const target = event.target;
    if (!(
      target instanceof HTMLElement &&
      target.dataset.act === 'pv-save' &&
      target.dataset.key === key &&
      target.dataset.page === String(page)
    ))
      away = true;
  };
  document.addEventListener('focusin', moved);
  const before = currentVerdictOn(context.doc, page),
    previousId = before ? before.id : 0,
    top = topPinId(); // the verdict a save replaces: a draft kept for it moves on
  // A new verdict on the line ends the line's offer of a take-back's [되돌리기] (the status line keeps its own): the
  // line is about the new verdict, and while the offer lasts its [이유 추가] steps out (components.css), so the focus a
  // key save hands it would go nowhere.
  const focusedBefore = document.activeElement,
    // it goes with the offer: the focus goes to the word being saved
    onUndo = !!focusedBefore && !!focusedBefore.closest && !!focusedBefore.closest('#doc .pv-undo');
  LINE_UNDO_OFFERS.delete(slot);
  SAVING_LINES.set(slot, key);
  drawPageVerdicts();
  if (onUndo) refocusLineWord(page, key);
  try {
    const answer = (
      await api('POST /api/pick', {
        body: {
          page,
          x0: 0,
          y0: 0,
          x1: context.w,
          y1: context.h,
          frac: WHOLE_PAGE.slice(),
          pdf_build: context.build || undefined,
          doc: context.doc || undefined,
        },
        what: '판정 저장',
        silent: true,
      })
    ).data;
    if (isRefusal(answer)) {
      failed(errText(answer));
      if (answer.pdf_build_gone && here()) refreshDoc().catch(() => {});
      return;
    }
    const body = pageVerdictBody(answer, context.kind);
    if (!body) {
      lineNote('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다', NOTICE_KIND.WARN, null, {
        source: 'page-verdict',
      });
      fail(translate('이 그림은 쪽 판정을 받지 못합니다 — 그림 위를 끌어 고른 뒤 판정합니다'));
      return;
    }
    Object.assign(body, {
      note: '',
      doc: context.doc || undefined,
      kind_req: REQUEST_KIND.FIX,
      assignee: ASSIGNEE_AGENT,
      verdict: key,
    });
    let id = 0;
    try {
      id = (await api('POST /api/pin', { body, what: '판정 저장', silent: true })).data.id;
    } catch (error) {
      const x = isApiError(error) ? error : null;
      // no answer, or a 5xx (it may have been written first): the list says whether it landed
      if (x && x.status && x.status < 500) throw error;
      await loadPins();
      const got = findLandedVerdict(context.doc, page, key, top, context.kind);
      if (!got) throw error;
      id = got.id;
    }
    saved = true;
    got = id;
    sourceOk('page-verdict');
    if (SECTION_SEEN.open) SECTION_SEEN.open.add(id); // my own new pin is never 'new' on a collapsed header
    const chip = undoNote(
      NOTICE_PLACE.CHIP,
      translateTemplate('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다', {
        id,
        word: verdictLabel(key, context.doc),
        target: context.target,
      }),
      { label: '되돌리기', wait: true, fn: verdictUndo(id) },
      {
        pin: id,
        pending: true,
        label: translateTemplate('#{id} 저장됨 · {word}', { id, word: verdictLabel(key, context.doc) }),
      },
    );
    // the reason popover: a draft on this line moves to the new verdict
    if (here()) followSaveWithReason(page, id, key, !!byKeyboard, previousId);
    await loadPins();
    settleChip(chip);
    if (here()) showPressedHint(page);
  } catch (error) {
    const x = isApiError(error) ? error : null;
    if (!saved) failed(x && x.status ? errText(x.data) || 'HTTP ' + x.status : translate('서버에 닿지 않습니다'));
  } finally {
    document.removeEventListener('focusin', moved);
    SAVING_LINES.delete(slot);
    KEY_SAVE_OUT.delete(slot);
    // A popover opened by Enter while this save was out: bound to it now if its Enter came after the number was known
    // (the list still being read), else, the save failed, its text kept as the page's draft.
    const waitingPopover =
      here() &&
      REASON_SESSION &&
      !REASON_SESSION.id &&
      REASON_SESSION.page === page &&
      REASON_SESSION.doc === context.doc;
    if (waitingPopover && saved) followSaveWithReason(page, got, key, !!byKeyboard, previousId);
    else if (!saved && here()) keepUnboundReason(page);
    // one moved away from meanwhile: written on this verdict wherever the person is now
    settleDetachedReason(slot, saved ? got : 0, key);
    drawPageVerdicts();
    if (currentVisit(visit) && byKeyboard && !away) {
      const reasonOpen = findMaybe(
        document,
        '#doc .pv[data-page="' + page + '"] [data-act="pv-reason-open"]',
        HTMLElement,
      );
      if (reasonOpen && saved) reasonOpen.focus({ preventScroll: true });
      else refocusLineWord(page, key);
      // never left on nothing: the line's own control
      if (saved && document.activeElement === document.body) focusLine(page);
      // The focus the save moved there raises no description box: the press's own description of the pressed word
      // stands over the words for a few seconds (showPressedHint), and on a one-row line the two boxes would overlap. A
      // focus the person moves raises it.
      if (saved) hideTip();
    }
    const next = NEXT_PRESS.get(slot);
    NEXT_PRESS.delete(slot);
    if (next) {
      const cur = currentVerdictOn(context.doc, page); // the last press made meanwhile, on the document it was made on
      if (!(cur && verdictOf(cur) === next.key)) {
        const fresh = here() ? pageSaveContext(page) : null;
        if (next.how === 'key') KEY_SAVE_OUT.add(slot);
        savePageVerdict(page, next.key, !!next.how, fresh || context);
      }
    }
    settleFailedCancelDraft(slot);
  }
} // a failed take-back's draft that waited for this save (a next save started just now waits on)

// Gives the focus back to word key's button on page `page`'s line after its save: the pressed button was disabled and
// redrawn while the request ran, which dropped the focus. Not when the person put the focus somewhere else meanwhile
// (savePageVerdict watches for that) or it is on something now.
function refocusLineWord(page: number, key: string) {
  const active = document.activeElement;
  if (active && active !== document.body && document.contains(active)) return;
  const button = findMaybe(
    document,
    '#doc .pv[data-page="' + page + '"] [data-act="pv-save"][data-key="' + CSS.escape(key) + '"]',
    HTMLButtonElement,
  );
  if (button && !button.disabled && button.getAttribute('aria-disabled') !== 'true')
    button.focus({ preventScroll: true });
}

// A press made word key page `page`'s verdict: its line shows the pressed word's context for PRESSED_HINT_MS.
const PRESSED_HINT_MS = 4000;

function showPressedHint(page: number) {
  const line = findMaybe(document, '#doc .pv[data-page="' + page + '"]', HTMLElement);
  if (!line) return;
  line.classList.add('pv-onshow');
  clearTimeout(line._onT);
  line._onT = setTimeout(() => line.classList.remove('pv-onshow'), PRESSED_HINT_MS);
}

export { verdictPress };
