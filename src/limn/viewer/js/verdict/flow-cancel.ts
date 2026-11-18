import { verdictOf, pinState } from '../app/rules-pins.ts';
import { PIN_STATE } from '../app/rules-tables.ts';
import { isMe, who } from '../app/state-people.ts';
import { DOC, META, findAnyPin, OPEN_ALL } from '../app/state.ts';
import { verdictLabel, viewerBlocked } from '../documents/state.ts';
import { dropPin, restorePin } from '../pins/flow-actions.ts';
import { claimActive } from '../pins/view-card-parts.ts';
import { api } from '../platform/api.ts';
import { findMaybe, $, searchToPage } from '../platform/dom.ts';
import { translateTemplate, TIP_TEXT, translate } from '../platform/i18n.ts';
import { lineNote, NOTICE_ACT_WAIT, NOTICES, noticeAct, NOTICE_MS, NOTICE_HOLD_MAX } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE, NOTICE_HOST } from '../platform/tables.ts';
import { hideTip } from '../platform/tooltip.ts';
import { drawPageVerdicts } from './flow-line.ts';
import { placeFailedCancelDraft, reviveReason, bringBackReason } from './flow-reason-transfer.ts';
import { putDraft, getDraft } from './state-drafts.ts';
import { LINE_UNDO_OFFERS, pageLineSlot, CANCEL_HOLD, CANCEL_OUT } from './state-lines.ts';
import { REASON_SESSION, hasUnsavedReason, WITHDRAWN_PINS, setReasonSession } from './state-reason.ts';
import { pageTargetOf, pageTargetShort, pageVerdictPins, canCancelVerdict } from './view-pins.ts';
import { isReasonField } from './view-reason-field.ts';
import { focusLine } from './view-reason.ts';

// The undo of a verdict pin's save (D10): the pin goes again - a withdrawn request - and the composer does not come
// back. When an agent claimed or closed it meanwhile it still goes, and the status line says its run may have started -
// one sentence with no ' — ', so the folded line shows all of it. A reason draft typed for it is not written to the
// withdrawn pin; it stays kept, and the status line offers [되돌리기], which brings the verdict back with it ('판정 #42
// 채택 저장 되돌림 · 쓰던 이유 보관 — <대상>'). Without one the undo says nothing - pressing the word again is the
// same.
function verdictUndo(id: number): () => Promise<boolean> {
  const undo = async () => {
    let was = null;
    try {
      was = (await api('GET /api/pins/{id}', { id, what: '핀 읽기', silent: true })).data.pin;
    } catch (error) {}
    const session = REASON_SESSION && REASON_SESSION.id === id ? REASON_SESSION : null;
    if (session && hasUnsavedReason(session))
      putDraft(session.doc, id, session.text, session.base, session.rev, {
        mode: session.mode,
        tried: session.tried,
        from: session.via,
      });
    WITHDRAWN_PINS.add(id);
    const ok = await dropPin(id, true, undo);
    if (!ok) WITHDRAWN_PINS.delete(id);
    if (ok && REASON_SESSION && REASON_SESSION.id === id) {
      setReasonSession(null);
      drawPageVerdicts();
    } // a withdrawn verdict takes no reason
    const draft = ok ? getDraft(DOC, id) : null,
      key = was && verdictOf(was),
      target = was ? pageTargetOf(was, META ? META.kind : undefined) : null;
    if (draft && key)
      lineNote(
        translateTemplate('판정 #{id} {word} 저장 되돌림 · 쓰던 이유 보관 — {target}', {
          id,
          word: verdictLabel(key),
          target: target ? pageTargetShort(target.page) : '#' + id,
        }),
        NOTICE_KIND.OK,
        {
          label: '되돌리기',
          tip: TIP_TEXT.undo,
          wait: true,
          fn: async () => {
            WITHDRAWN_PINS.delete(id);
            const back = await restorePin(id);
            if (back) afterVerdictRestore(id);
            return back;
          },
        },
        { life: NOTICE_LIFE.TIMER, undo: true, literal: true },
      );
    if (ok && was && (claimActive(was) || pinState(was) !== PIN_STATE.OPEN))
      lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다', NOTICE_KIND.WARN);
    return ok;
  };
  return undo;
}

// ---------------- Taking one's verdict back
// after a cancel on a page, how long that page's next [판정 취소] waits (a double press never takes two)
const CANCEL_HOLD_MS = 800;

// the bound a status-line action's request has (platform/notices.ts noticeAct)
let CANCEL_ANSWER_WAIT = NOTICE_ACT_WAIT;

// A verdict a [되돌리기] brought back (a take-back's, the save chip's): when it is its line's current verdict again its
// kept reason draft opens (reviveReason); when a newer verdict came meanwhile - someone else's - it is restored but
// superseded, the status line says so ('판정 #21 채택 되살림 · 지금 판정은 Bob의 #34 보류 — <대상>') and no popover
// opens over that line - its kept draft, which no line would mark on a verdict that is not current, becomes the page's
// draft, said with [보기] (placeFailedCancelDraft).
function afterVerdictRestore(id: number) {
  const pin = findAnyPin(id),
    target = pin ? pageTargetOf(pin, META ? META.kind : undefined) : null,
    cur = target ? (pageVerdictPins().get(target.page) || [])[0] : null;
  if (pin && target && cur && cur.id !== id) {
    const currentKey = verdictOf(cur) || '',
      key = verdictOf(pin) || '';
    lineNote(
      translateTemplate('판정 #{id} {word} 되살림 · 지금 판정은 {owner} #{cur} {now} — {target}', {
        id,
        word: verdictLabel(key),
        owner: isMe(cur.author) ? translate('내') : translateTemplate('{name}의', { name: who(cur.author) }),
        cur: cur.id,
        now: verdictLabel(currentKey),
        target: pageTargetShort(target.page),
      }),
      NOTICE_KIND.INFO,
      null,
      { literal: true, life: NOTICE_LIFE.TIMER },
    );
    placeFailedCancelDraft(id, target.page, DOC, true);
    return;
  }
  reviveReason(id);
}

// The line's [되돌리기]: the status line's action runs (noticeAct), as if pressed there.
function undoFromLine(control: HTMLElement) {
  const line = control.closest('.pv'),
    page = Number(line && line.getAttribute('data-page')) || 0,
    offer = LINE_UNDO_OFFERS.get(pageLineSlot(page));
  if (!offer) return;
  LINE_UNDO_OFFERS.delete(pageLineSlot(page));
  if (NOTICES.has(offer.n)) noticeAct(offer.n);
  drawPageVerdicts();
  focusLine(page);
}

// [판정 취소] on page `page`'s line - or its pressed word pressed again (pressPageVerdict): verdict pin id goes to the
// Trash as the card's [지우기] sends it (dropPin) - a withdrawn request - and the line shows at once what is current
// now: the newest earlier verdict about the same target (D4) or '판정 없음'. The status line says so result first
// ('판정 #17 채택 취소 · 지금 판정 #12 보류 — <대상>', or '… · 남은 판정 없음 — …') with [되돌리기], which restores it
// (restorePin) and its kept reason draft (reviveReason); one an agent had claimed still goes, and the status line says
// its run may have started (as the save's undo, verdictUndo). Its reason popover closes with it; what was typed is not
// written, and stays kept for that [되돌리기]. A failure is said on the status line and the line shows the verdict
// again, its popover too - or, when something took its place meanwhile, what was typed as a draft its line marks, said
// with [보기] (bringBackReason). The page's next [판정 취소] waits CANCEL_HOLD_MS: the same place may now cancel the
// earlier verdict, which a double press must not reach. A keyboard press leaves the focus on the PDF area, as Esc in
// the reason field does.
function cancelLineVerdict(button: HTMLElement) {
  const id = Number(button.dataset.ref),
    page = Number((button.closest('.pv') || button).getAttribute('data-page')) || 0;
  if (button.getAttribute('aria-disabled') === 'true') return;
  cancelVerdictPin(id, page, document.activeElement === button);
}

/** @param had - the focus was on what was pressed */
/** @param [byKey] - a digit key: the focus goes to the line from wherever it was */
async function cancelVerdictPin(id: number, page: number, had: boolean, byKey?: boolean) {
  const pin = OPEN_ALL.find((x) => x.id === id),
    from = document.activeElement,
    doc = DOC,
    key = verdictOf(pin);
  // canCancelVerdict holds only for a pin with a verdict
  if (!pin || !canCancelVerdict(pin) || viewerBlocked() || !key) return;
  const claimed = claimActive(pin),
    target = pageTargetShort(page);
  const inField = isReasonField(document.activeElement) && !!REASON_SESSION && REASON_SESSION.id === id;
  CANCEL_HOLD.set(pageLineSlot(page), Date.now() + CANCEL_HOLD_MS);
  setTimeout(() => drawPageVerdicts(), CANCEL_HOLD_MS + 20);
  // Its reason popover leaves with the line's verdict, but the session is kept until the server answers: a failed
  // cancel brings the verdict back and its unsent reason with it, or keeps that as a draft its line marks when
  // something took its place (bringBackReason); a done one drops it - its draft stays kept (putDraft) for the
  // [되돌리기].
  const kept = REASON_SESSION && REASON_SESSION.id === id ? REASON_SESSION : null;
  if (kept) {
    setReasonSession(null);
    if (hasUnsavedReason(kept))
      putDraft(kept.doc, id, kept.text, kept.base, kept.rev, { mode: kept.mode, tried: kept.tried, from: kept.via });
  }
  WITHDRAWN_PINS.add(id);
  // The take-back is said on the status line with its [되돌리기], which the line itself also offers for as long
  // (LINE_UNDO_OFFERS): the status line is far away by Tab.
  const say = () => {
    const now = (pageVerdictPins().get(page) || [])[0],
      nowKey = now && verdictOf(now);
    const rest =
      now && nowKey
        ? translateTemplate('지금 판정 #{id} {word}', { id: now.id, word: verdictLabel(nowKey) })
        : translate('남은 판정 없음');
    const notice = lineNote(
      translateTemplate('판정 #{id} {word} 취소 · {rest} — {target}', { id, word: verdictLabel(key), rest, target }),
      NOTICE_KIND.OK,
      {
        label: '되돌리기',
        tip: TIP_TEXT.undo,
        wait: true,
        fn: async () => {
          WITHDRAWN_PINS.delete(id);
          const ok = await restorePin(id);
          if (ok) afterVerdictRestore(id);
          return ok;
        },
      },
      { life: NOTICE_LIFE.TIMER, undo: true, literal: true },
    );
    // [이유 추가] steps out while the line offers the undo (components.css): a focus on it goes to the [되돌리기]
    // beside it.
    const focused = document.activeElement,
      onAdd = !!focused && !!focused.closest('#doc .pv[data-page="' + page + '"] .pv-ra>.pv-add');
    if (notice) {
      LINE_UNDO_OFFERS.set(pageLineSlot(page), { id, n: notice.n });
      drawPageVerdicts();
      setTimeout(() => drawPageVerdicts(), NOTICE_MS + NOTICE_HOLD_MAX + 50);
      const active = document.activeElement,
        undoButton = findMaybe(document, '#doc .pv[data-page="' + page + '"] [data-act="pv-undo"]', HTMLElement);
      if (onAdd && undoButton && (active === focused || active === document.body || !active))
        undoButton.focus({ preventScroll: true });
    }
  };
  hideTip();
  const again = () => {
    CANCEL_HOLD.delete(pageLineSlot(page));
    drawPageVerdicts();
    cancelVerdictPin(id, page, false);
  }; // [다시 시도] is a new press: no hold
  const out = pageLineSlot(page);
  CANCEL_OUT.set(out, id);
  let ok = false,
    slow = false;
  const wait = setTimeout(() => {
    slow = true;
    if (CANCEL_OUT.get(out) === id) CANCEL_OUT.delete(out);
    lineNote('판정 취소의 답이 늦습니다 — 이 줄의 키를 다시 받습니다', NOTICE_KIND.WARN, null, {
      source: 'pv-drop-wait',
      life: NOTICE_LIFE.TIMER,
    });
  }, CANCEL_ANSWER_WAIT);
  try {
    ok = await dropPin(id, false, again, { say, where: NOTICE_HOST.LINE, what: '판정 취소' });
  } finally {
    clearTimeout(wait);
    if (CANCEL_OUT.get(out) === id) CANCEL_OUT.delete(out);
  }
  if (!ok) {
    WITHDRAWN_PINS.delete(id);
    bringBackReason(id, page, kept ? kept.doc : doc, kept);
  }
  // A keyboard press stays on its own page: the line's [되돌리기], else its line (never the PDF area, from which Tab
  // would go to the first page's line). A digit key's take-back takes the focus there from wherever it was - the
  // outline, a card - as a key save does, unless the person moved it meanwhile: left in the outline, Enter would press
  // the outline again instead of undoing. A reason popover that has the focus now is a newer one (the verdict's own
  // left with it): it keeps it - on this line too (a new verdict's, saved while the take-back was out), where moving
  // the focus to the line would make the next digit a verdict key.
  const at = document.activeElement,
    pop = !!at && !!at.closest('#doc .pv-pop');
  const lost =
    !pop &&
    (!at ||
      at === document.body ||
      at === $('#left') ||
      !!at.closest('#doc .pv[data-page="' + page + '"]') ||
      (!!byKey && at === from));
  if ((had || inField) && lost && !slow) {
    const undoButton = findMaybe(document, '#doc .pv[data-page="' + page + '"] [data-act="pv-undo"]', HTMLElement);
    if (undoButton) undoButton.focus({ preventScroll: true });
    else if (!focusLine(page)) searchToPage();
  }
  if (ok && claimed) lineNote('처리 중이던 판정이라 이미 실행됐을 수 있습니다', NOTICE_KIND.WARN);
}

export { CANCEL_HOLD_MS, cancelLineVerdict, cancelVerdictPin, undoFromLine, verdictUndo };
