// Append a note to an existing pin; a late response must leave any newer selection on screen. Its undo is a chip on
// that pin's mark ('덧붙임 [되돌리기]', docs/handbook/viewer.md §알림 자리), and a failure a banner over the composer's
// save row. A focus the closed composer took goes to that pin's mark (focusPlace).
import {
  DEFAULT_DOC,
  DOC,
  KIND_NEW,
  META,
  OPEN_ALL,
  PINS,
  captureVisit,
  COMPOSE,
  setComposeBox,
  setComposeRetryVerdict,
  setComposeSaving,
  topPinId,
} from '../app/state.ts';
import { togglePendingSave, syncComposeSaveButtons } from './view-save.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { SECTION_SEEN } from '../platform/prefs.ts';
import { API_WAIT, api, apiFailed, isApiError, isRefusal } from '../platform/api.ts';
import {
  BANNERS,
  bannerNote,
  endNotice,
  focusRun,
  quietNote,
  settleChip,
  sourceOk,
  undoNote,
} from '../platform/notices.ts';
import { kindFor, wireScope } from './view-levels.ts';
import { figureRung, figureFields } from '../pdf/view-figure.ts';
import { renderSuggest, suggestForSave, suggestOff, suggestRebase } from './flow-suggest.ts';
import { SUGGEST_DRAFT, setSuggestCurrent } from './state-suggest.ts';
import {
  cancelSelection,
  composeFields,
  composeOwns,
  focusClosed,
  focusPlace,
  restoreSelection,
  selectionSnapshot,
} from './flow-selection.ts';
import { renderOverlapBanner } from './view-overlap.ts';
import { clearSavedDraft, restoredDraftOwns, saveDraftSoon, savedDraftSnapshot, syncDraft } from './flow-draft.ts';
import { assignOutcome, composeAsk, mentionHints } from './input-mentions.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_PLACE } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { REQUEST_KIND, SAVE_MODE } from '../app/rules-tables.ts';
import { verdictOf } from '../app/rules-pins.ts';
import { isMe } from '../app/state-people.ts';
import { isRegion, pdoc, verdictLabel, viewerBlocked } from '../documents/state.ts';
import { offlineNow } from '../documents/flow-polling.ts';
import { composerPins, composerQueue, composerVerdict } from './state-seams.ts';
/**
 * Append once to the displayed pin revision; conflicts keep the draft, and undo can restore only that verified prior
 * note.
 */
async function appendToPin(id: number, text: string) {
  if (COMPOSE.saving || viewerBlocked()) return;
  const prior = PINS.find((pin) => pin.id === id);
  if (!prior) {
    await composerPins().load();
    return;
  }
  setComposeSaving(true);
  syncComposeSaveButtons();
  const visit = captureVisit(),
    selection = COMPOSE.current,
    box = COMPOSE.box,
    priorNote = prior.note || '',
    fields = composeFields();
  const draft = savedDraftSnapshot();
  // The hints go along, as on a new pin and an edit: the pin's own first (its note's tags), then the ones picked for
  // this text - without them a name two people share would tag nobody, while the preview line names whom it tells.
  const hints = [...new Set((prior.mentions || []).concat(mentionHints($('#note'))))],
    body: Record<string, unknown> = { note_append: text, base_rev: prior.rev || 0 };
  if (hints.length) body.mentions = hints;
  try {
    const { status, data } = await api('POST /api/pins/{id}/edit', {
      id,
      body,
      what: '메모 덧붙이기',
      where: NOTICE_HOST.COMPOSER,
      intent: 'append',
      expect: [409],
    });
    if (status === 409) {
      bannerNote(
        NOTICE_HOST.COMPOSER,
        '다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 메모를 확인하고 다시 덧붙이세요',
        NOTICE_KIND.WARN,
        null,
        { source: 'POST /api/pins/' + id + '/edit append' },
      );
      await composerPins().load();
      return;
    }
    const closed = composeOwns(selection, box, visit, fields) || restoredDraftOwns(draft);
    if (composeOwns(selection, box, visit, fields)) {
      setComposeBox(null);
      cancelSelection(true);
      if (box) box.remove();
      syncDraft();
    } else if (restoredDraftOwns(draft)) {
      cancelSelection(true);
      syncDraft();
    } else clearSavedDraft(draft);
    const after = closed ? focusClosed() : null; // a composer opened while the pins reload keeps the focus (focusPlace)
    const chip = undoNote(
      NOTICE_PLACE.CHIP,
      translateTemplate('#{id} 에 덧붙였습니다', { id }),
      { label: '되돌리기', wait: true, fn: () => undoAppend(id, priorNote, data.pin.rev) },
      { pin: id, pending: true, label: translate('덧붙임') },
    );
    await composerPins().load();
    settleChip(chip);
    if (after) focusPlace(selection, id, after); // a focus the closed composer took goes to that pin's mark
  } catch (error) {
  } finally {
    setComposeSaving(false);
    syncComposeSaveButtons();
  }
}
// Undo of an append: the note goes back to what it was before (base_rev = the append's revision). Silent - the card
// shows it. Resolves with whether it went back (its chip waits for it, noticeAct).
async function undoAppend(id: number, note: string, revision: number | undefined): Promise<boolean> {
  let ok = false;
  try {
    await api('POST /api/pins/{id}/edit', {
      id,
      body: { note: note, base_rev: revision },
      what: '되돌리기',
      where: NOTICE_HOST.LIST,
      intent: 'append-undo',
    });
    ok = true;
    quietNote(translateTemplate('#{id} 메모를 되돌렸습니다', { id }));
  } catch (error) {}
  await composerPins().load();
  return ok;
}
// Saves the selection as a pin (or queues the save while pick runs). Saved: a chip '저장됨 [되돌리기]' on the new pin's
// mark for NOTICE_MS, visible with the phone's sheet folded; its [되돌리기] drops the pin again and - only once that
// delete went through - reopens the composer with the same selection and note. A failed undo keeps the pin and no
// composer (a second save would duplicate it); its failure's [다시 시도] runs the whole undo again. Failed save: a
// banner over the save row, whose button then reads [다시 저장] (api's save flag). A focus the closed composer took
// goes to the new pin's mark once it is drawn (focusPlace). A suggested edit goes along (suggestForSave); when the
// lines' text differs from its base (409 suggest_base_changed) nothing is saved, the draft stays, the editor shows the
// current text against it and the failure's banner offers [지금 원문으로 맞추기]. With verdict (a word of the
// document's, the composer's verdict row - which calls it only with a found selection: its buttons are off while the
// pick runs) the pin is a verdict pin: a fix request with no suggestion; its undo withdraws it and does not bring the
// composer back (verdictUndo, D10). Whether a stored pin stands where the selection was saved: on the same page - or,
// for a selection with no page (a Markdown document's lines, ADR-0025 D2), on the same lines of the same file with no
// page either. Pure.
function samePlace(
  pin: Pin,
  selection: { page?: number | null; file?: string | null; lo?: number | null; hi?: number | null },
) {
  if (typeof selection.page === 'number') return pin.page === selection.page;
  return pin.page == null && pin.file === selection.file && pin.lo === selection.lo && pin.hi === selection.hi;
}
/** Save the submitted selection once, preserving any later edits as a draft and offering undo for the created pin. */
async function savePin(verdict?: string) {
  if (COMPOSE.saving) return;
  if (!COMPOSE.current) {
    if (COMPOSE.picking) togglePendingSave();
    return;
  } // pick hasn't finished yet - queue it (toggle) or cancel the pending save
  setComposeSaving(true);
  const visit = captureVisit();
  syncComposeSaveButtons();
  const selection = COMPOSE.current,
    box = COMPOSE.box,
    note = $('#note').value.trim();
  // [다시 저장] after a verdict's failed save carries that verdict again only while nothing the composer asks has
  // changed since that press (COMPOSE.intent: no new, cleared or restored selection, no rung or lines, kind or [제안
  // 수정] change - also one made back to where it was) and it still asks for a verdict pin: a fix request with [제안
  // 수정] off. Anything else is a plain pin's save. A change made while the failed request was still out leaves no
  // retry at all (the catch).
  const intent = COMPOSE.intent,
    retry = COMPOSE.retryVerdict;
  setComposeRetryVerdict(null);
  if (
    verdict === undefined &&
    retry &&
    retry.gen === intent &&
    retry.sel === selection &&
    KIND_NEW === REQUEST_KIND.FIX &&
    !SUGGEST_DRAFT.on
  )
    verdict = retry.key;
  let body: Record<string, unknown> = {
    file: selection.file,
    name: selection.name,
    page: selection.page,
    lo: selection.lo,
    hi: selection.hi,
    raw_lo: selection.raw_lo,
    raw_hi: selection.raw_hi,
    via: selection.via,
    score: selection.score,
    fill: selection.fill,
    rival: selection.rival,
    frac: selection.frac,
    note: note,
    quote: selection.quote,
    pdf_build: selection.pdf_build || undefined,
  };
  if (selection.scope) {
    body.scope = wireScope(selection.scope);
    body.kind = kindFor(selection.scope, selection.env);
  } else body.kind = selection.kind;
  if (isRegion(selection))
    body = {
      page: selection.page,
      frac: selection.frac,
      note: note,
      quote: selection.quote,
      pdf_build: selection.pdf_build || undefined,
    }; // view-only: page/region only
  // a figure pick: its element as el, the element's box as frac, its kind
  figureFields(body, selection.elSel, isRegion(selection) ? null : figureRung(selection));
  body.doc = selection.doc || DOC || undefined;
  // The kind and the assignee are assignOutcome's answer for the note as it is at this moment - the answer the preview
  // line and the assignee row draw - never a value an earlier drawing left behind: a restored pick whose person cannot
  // be looked up yet is not sent. A pin created by the viewer always records an assignee (otherwise a legacy pin's
  // inference applies).
  const out = assignOutcome(composeAsk(SAVE_MODE.NEW));
  body.kind_req = out.kind;
  body.assignee = out.assignee;
  const hints = mentionHints($('#note'));
  if (hints.length) body.mentions = hints;
  // Cut off, or a selection whose lines were never found (offlinePick): the pin goes into this browser's queue and is
  // written when the connection is back (offline/flow.ts §Sending the queue). The composer closes as a save does, so
  // the next pin can be drawn straight away. A verdict is not kept this way - it is a word of the document's that only
  // the server's found place can carry - so it says so and keeps the selection for a retry. The save stays marked as
  // going until the queue has answered: let go before that, a second press while the store is still opening would keep
  // the same selection twice, under two keys, and reconnecting would write two pins.
  if (selection.offline || offlineNow()) {
    const done = () => {
      setComposeSaving(false);
      syncComposeSaveButtons();
    };
    if (verdict) {
      done();
      bannerNote(
        NOTICE_HOST.COMPOSER,
        translate('연결이 끊겨 판정은 쌓아 둘 수 없습니다 — 연결되면 판정 버튼을 다시 누릅니다'),
        NOTICE_KIND.ERR,
        null,
        { save: true, source: 'POST /api/pin' },
      );
      return;
    }
    // A suggested edit is checked against the source when it is written, and the source may not be the one it was
    // written against by then. It is not kept either: the note alone can be, with the switch off.
    if (!isRegion(selection) && suggestForSave(SUGGEST_DRAFT, suggestOff(selection, META ? META.kind : undefined))) {
      done();
      bannerNote(
        NOTICE_HOST.COMPOSER,
        translate('연결이 끊겨 제안 수정은 쌓아 둘 수 없습니다 — [제안 수정]을 끄면 메모만 쌓아 둡니다'),
        NOTICE_KIND.ERR,
        null,
        { save: true, source: 'POST /api/pin' },
      );
      return;
    }
    let kept = false;
    try {
      kept = await composerQueue().save(selection, note, out, hints);
    } finally {
      done();
    }
    if (kept) {
      setComposeBox(null);
      cancelSelection(true);
      if (box) box.remove();
      syncDraft();
      focusClosed();
    }
    return;
  }
  const suggestion =
    isRegion(selection) || verdict
      ? null
      : suggestForSave(SUGGEST_DRAFT, suggestOff(selection, META ? META.kind : undefined));
  if (suggestion) body.suggest = suggestion;
  // A plain pin - no verdict, no suggested edit - is one the queue can keep. It goes with a key where the server knows
  // a write by its key, so that a save left without an answer can be kept and asked about by that key later instead
  // of failing here (below).
  const plain = !verdict && !suggestion,
    idem = plain && composerQueue().keyed() ? composerQueue().key() : undefined;
  if (idem !== undefined) body.idem = idem;
  if (verdict) {
    body.verdict = verdict;
    body.kind_req = REQUEST_KIND.FIX;
    // On a figure document the verdict is the figure's, whatever element the selection names (verdict/flow-line.ts
    // figureVerdictBody).
    const figureBody = composerVerdict().figureBody(selection);
    if (figureBody)
      body = Object.assign(
        figureBody,
        { note, doc: body.doc, kind_req: REQUEST_KIND.FIX, assignee: body.assignee },
        hints.length ? { mentions: hints } : {},
        { verdict },
      );
  }
  const snapshot = selectionSnapshot(),
    fields = composeFields(); // [되돌리기] takes the pin back and hands this selection and note back for another try
  const draft = savedDraftSnapshot();
  const question = out.kind === REQUEST_KIND.QUESTION;
  const top = topPinId(); // a save whose answer is lost is looked for above it before it is called a failure
  try {
    let status = 0,
      data: PinSaved | SaveConflict | null = null;
    const ask = {
      body,
      what: verdict ? '판정 저장' : '핀 저장',
      where: NOTICE_HOST.COMPOSER,
      save: true,
      expect: suggestion ? ([409] as const) : [],
      wait: API_WAIT.SAVE,
      quietUnreached: plain,
    };
    try {
      ({ status, data } = await api('POST /api/pin', ask));
    } catch (error) {
      if (isApiError(error) && error.status) throw error;
      // No answer: the pin may be on the server - this person's, on this document and place, this note and verdict,
      // newer than any before the press. Then it is a save (its failure banner goes below), not a failure whose [다시
      // 저장] would make it twice.
      await composerPins().load();
      const got = OPEN_ALL.find(
        (pin) =>
          pin.id > top &&
          isMe(pin.author) &&
          pdoc(pin) === (body.doc || DEFAULT_DOC) &&
          samePlace(pin, selection) &&
          String(pin.note || '') === note &&
          (verdictOf(pin) || '') === (verdict || ''),
      );
      if (!got) {
        // Not there, or the list could not be read either. A save that waited out its time (ended at API_WAIT.SAVE,
        // an AbortError) met a server that does not answer: the connection went before the poll could say so. A
        // plain pin is then kept in the queue as one whose write was tried - with the key it went with and the pins
        // that stood before it - so the send asks whether it arrived before writing it (offline/flow.ts §Sending the
        // queue), and the composer closes as a save does. A save the network refuses at once is a failure,
        // said above the save row with [다시 저장]; so is a pin the queue will not take.
        if (
          plain &&
          error instanceof Error &&
          error.name === 'AbortError' &&
          (await composerQueue().save(selection, note, out, hints, { idem, top }))
        ) {
          const failed = BANNERS.get(NOTICE_HOST.COMPOSER);
          if (failed && failed.save) endNotice(failed, false);
          const cleared = composeOwns(selection, box, visit, fields),
            restored = restoredDraftOwns(draft);
          if (cleared) {
            setComposeBox(null);
            cancelSelection(true);
            if (box) box.remove();
            syncDraft();
          } else if (restored) {
            cancelSelection(true);
            syncDraft();
          } else clearSavedDraft(draft);
          if (cleared || restored) focusClosed();
          return;
        }
        if (plain && !BANNERS.get(NOTICE_HOST.COMPOSER))
          // the queue said why it would not take it, if it did
          apiFailed({ ...ask, source: 'POST /api/pin' }, translate('서버에 닿지 않습니다'), true);
        throw error;
      }
      status = 200;
      data = { id: got.id };
      sourceOk('POST /api/pin');
    }
    // the expected 409 (a suggested edit's lines changed meanwhile) is a refusal's body (isRefusal); a pin saved is not
    if (status === 409 || isRefusal(data)) {
      suggestSaveRefused(selection, isRefusal(data) ? data : null);
      return;
    }
    // a 2xx whose body was no JSON names no pin: the save ends as one that failed, unsaid (below)
    if (!data) throw new Error('POST /api/pin answered no pin');
    const id = data.id,
      failed = BANNERS.get(NOTICE_HOST.COMPOSER);
    if (failed && failed.save) endNotice(failed, false); // this save went through: its earlier failure is over
    const cleared = composeOwns(selection, box, visit, fields),
      restored = restoredDraftOwns(draft);
    if (cleared) {
      setComposeBox(null);
      cancelSelection(true);
      if (box) box.remove();
      syncDraft();
    } // a saved pin leaves no draft
    else if (restored) {
      cancelSelection(true);
      syncDraft();
    } else clearSavedDraft(draft);
    // a composer opened while the pins reload keeps the focus (focusPlace)
    const after = cleared || restored ? focusClosed() : null;
    if (SECTION_SEEN.open) SECTION_SEEN.open.add(id); // my own new pin is never 'new' on a collapsed header
    const undo: (run?: NoticeRun) => Promise<boolean> = verdict
      ? composerVerdict().undo(id)
      : async (run) => {
          const mine = run ? null : focusRun(),
            ok = await composerPins().drop(id, true, undo);
          if (mine) mine.stop();
          // A late answer whose person has moved on brings the composer back without the focus: noticeAct's run for the
          // chip's [되돌리기], this run's own watch for a failure's [다시 시도].
          const away = run ? run.away() : !!mine && mine.away();
          if (
            ok &&
            (cleared || restored) &&
            DOC === visit.doc &&
            !COMPOSE.current &&
            !COMPOSE.box &&
            !COMPOSE.picking &&
            !$('#note').value
          )
            restoreSelection(snapshot, !away);
          return ok;
        };
    const word = verdict ? verdictLabel(verdict) : '',
      figureRoot = verdict ? composerVerdict().figureRoot(selection) : null; // a figure's verdict names the figure
    const said =
      figureRoot && selection.page !== undefined
        ? translateTemplate('#{id} {word} 판정 저장됨 · {target} — 되돌리면 판정을 거둡니다', {
            id,
            word: word,
            target: composerVerdict().figureShort(selection.page, figureRoot),
          })
        : translateTemplate('#{id} 저장됨 · {word} 판정', { id, word: word });
    const chip = verdict
      ? undoNote(
          NOTICE_PLACE.CHIP,
          said,
          { label: '되돌리기', wait: true, fn: undo },
          {
            pin: id,
            pending: true,
            label: translateTemplate('#{id} 저장됨 · {word}', { id, word: verdictLabel(verdict) }),
          },
        )
      : undoNote(
          NOTICE_PLACE.CHIP,
          translateTemplate(question ? '질문 #{id} 저장됨 · pins.md 갱신' : '핀 #{id} 저장됨 · pins.md 갱신', { id }),
          { label: '되돌리기', wait: true, fn: undo },
          { pin: id, pending: true, label: translate('저장됨') },
        );
    await composerPins().load();
    settleChip(chip);
    if (after) focusPlace(selection, id, after); // a focus the closed composer took goes to the new pin's mark
  } catch (error) {
    if (verdict) {
      if (COMPOSE.intent === intent) setComposeRetryVerdict({ key: verdict, sel: selection, gen: intent });
      else composerVerdict().dropped();
    }
  } finally {
    // [다시 저장] saves this verdict again, or the banner says it was dropped
    setComposeSaving(false);
    syncComposeSaveButtons();
  }
}
// A new pin's save the server answered 409 while it carried a suggested edit: nothing was saved and the draft stays.
// When the selection's lines differ from the suggestion's base (suggest_base_changed), the editor shows the lines'
// current text against the draft and the banner over the save row offers [지금 원문으로 맞추기] (the draft keeps its
// text and takes that text as its base); any other 409 is said as the failure it is. Either way the save row reads
// [다시 저장].
function suggestSaveRefused(selection: ComposerSelection, data: SaveConflict | null) {
  const source = 'POST /api/pin',
    head = translateTemplate('{what} 실패', { what: translate('핀 저장') });
  if (!(data && data.reason === 'suggest_base_changed')) {
    bannerNote(NOTICE_HOST.COMPOSER, head + ' — ' + (errText(data) || 'HTTP 409'), NOTICE_KIND.ERR, null, {
      save: true,
      source,
    });
    return;
  }
  if (COMPOSE.current === selection && typeof selection.lo === 'number' && typeof selection.hi === 'number') {
    setSuggestCurrent({
      text: String(data.current || ''),
      file: selection.file || null,
      lo: selection.lo,
      hi: selection.hi,
    });
    renderSuggest(selection);
  }
  bannerNote(
    NOTICE_HOST.COMPOSER,
    head + ' — ' + translate('그사이 그 줄들의 원문이 바뀌었습니다'),
    NOTICE_KIND.ERR,
    {
      label: '지금 원문으로 맞추기',
      tip: '쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다. 그다음 다시 저장합니다',
      fn: () => {
        const current = COMPOSE.current;
        if (!current) return;
        suggestRebase(
          SUGGEST_DRAFT,
          current,
          () => COMPOSE.current === current,
          () => {
            if (COMPOSE.current !== current) return;
            renderSuggest(current);
            renderOverlapBanner();
            saveDraftSoon();
          },
        );
      },
    },
    { save: true, source },
  );
}
export { appendToPin, savePin };
