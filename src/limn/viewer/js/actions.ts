// [완료] on an open card. Done (or sent to review, for a screen without identity): a row in the card's place with
// [되돌리기] (reopenPin) for NOTICE_MS - other presses never end it (docs/handbook/viewer.md §알림 자리). A refusal: a
// banner on top of the panel.
import {
  $,
  DOC,
  DONE_ALL,
  DROPPED,
  NOTICE_HOST,
  NOTICE_KIND,
  NOTICE_PLACE,
  OPEN_ALL,
  PINS,
  PIN_STATE,
  REVIEW_ALL,
  T,
  setOpenAll,
  setPins,
  setReviewAll,
} from './core.ts';
import { tl, tr } from './i18n.ts';
import { api } from './api.ts';
import {
  NOTICE_ACT_WAIT,
  NOTICE_LATE_SRC,
  bannerNote,
  deferred,
  deferredNote,
  drawnBefore,
  endNotice,
  lineNote,
  quietNote,
  sourceEntry,
  sourceOk,
  undoNote,
} from './notices.ts';
import { pdoc } from './doc-tabs.ts';
import { findAnyPin, showChange } from './revisions.ts';
import { markMine, pinState } from './polling.ts';
import { drawStatus } from './status.ts';
import { searchToPage } from './search.ts';
import { drawTrash } from './cards.ts';
import { PINS_APPLIED_SEQ, drawPins, loadPins, marks } from './list.ts';
import { EDITOR } from './edit.ts';
async function closePin(id) {
  const cardBefore = drawnBefore($('#pins'), '.pin.card', id),
    record = OPEN_ALL.find((pin) => pin.id === id) || null;
  try {
    const { data } = await api('/api/pins/' + id + '/close', {
      method: 'POST',
      what: '완료',
      where: NOTICE_HOST.LIST,
      retry: () => closePin(id),
    });
    if (!data.ok) {
      bannerNote(NOTICE_HOST.LIST, tl('완료 실패 — 핀 #{id} 이 없습니다', { id }), NOTICE_KIND.ERR);
    } else {
      markMine(id);
      undoNote(
        NOTICE_PLACE.ROW,
        tl(
          data.state === PIN_STATE.REVIEW
            ? '핀 #{id} 검토 대기로 보냄 — 이 화면에 신원이 없어(로컬) 에이전트가 닫은 것으로 칩니다'
            : '핀 #{id} 완료',
          { id },
        ),
        { label: '되돌리기', wait: true, fn: () => reopenPin(id) },
        { pin: id, sec: 'open', prev: cardBefore, rec: record },
      );
    }
  } catch (error) {}
  await loadPins();
}
// Awaiting review -> done; the person who confirmed (confirmed_by) is recorded. The card's [확인] and the changes
// view's guide line call this one function. Like a reply it is a deferred send: the card leaves the review section at
// once (CONFIRMING keeps it out of every pin snapshot meanwhile, derivePinLists), a row in its place offers [되돌리기]
// for NOTICE_MS and the request goes when that row does; the undo puts the card back with nothing sent. The request
// names the close the card showed (done_at), so a pin reopened and closed again in between answers 409 'conflict'
// instead of confirming a result nobody looked at; a 409 'open' means it was reopened and is still open
// (docs/handbook/api.md §검토 대기). Both are banners on top of the review section (confirmConflict).
const CONFIRMING = new Set();
// The pins whose [확인] waits for its undo, by id: off the review list meanwhile, but a page verdict line still counts
// them (verdict.ts).
const CONFIRMING_PIN = new Map() as Map<number, Pin>;
// The warning for a confirm answered 409 'conflict', chosen by the pin that 409 carries: still awaiting review means it
// was closed again - look at the new result, then confirm; any other state (a person closed it straight to done) has
// nothing to confirm. A body without the pin (an older server) keeps the closed-again warning.
function confirmConflictText(id, pin) {
  return pin && pinState(pin) !== PIN_STATE.REVIEW
    ? tl('핀 #{id} 은 이미 완료로 닫혔습니다 — 확인할 것이 없습니다', { id })
    : tl('핀 #{id} 은 다시 닫혔습니다 — 새 결과를 보고 확인하세요', { id });
}
// What kind of banner that 409 conflict is, by the same rule as its text: closed again is a WARN that still asks for a
// look ([변경 보기]); already done by a person is INFO with nothing to do. Pure.
function confirmConflictKind(pin: Pin | null | undefined): string {
  return pin && pinState(pin) !== PIN_STATE.REVIEW ? NOTICE_KIND.INFO : NOTICE_KIND.WARN;
}
// Says a confirm answered 409 'conflict' in a banner on top of the review section (confirmConflictText,
// confirmConflictKind).
function confirmConflict(id: number, pin: Pin | null | undefined) {
  const kind = confirmConflictKind(pin);
  bannerNote(
    NOTICE_HOST.REVIEW,
    confirmConflictText(id, pin),
    kind,
    kind === NOTICE_KIND.WARN ? { label: '변경 보기', tip: T.change, fn: () => showChange(id) } : null,
  );
}
function confirmPin(id) {
  if (CONFIRMING.has(id)) return;
  const at = REVIEW_ALL.findIndex((listed) => listed.id === id),
    pin = at < 0 ? null : REVIEW_ALL[at];
  const cardBefore = drawnBefore($('#review-pins'), '.pin.card', id);
  CONFIRMING.add(id);
  if (pin) CONFIRMING_PIN.set(id, pin);
  setReviewAll(REVIEW_ALL.filter((listed) => listed.id !== id));
  drawPins();
  marks();
  const pendingConfirm = deferred(
    async () => {
      try {
        const { data } = await api('/api/pins/' + id + '/confirm', {
          method: 'POST',
          what: '확인',
          where: NOTICE_HOST.REVIEW,
          expect: [409],
          keepalive: true,
          body: pin && pin.done_at ? { done_at: pin.done_at } : {},
        });
        if (data && data.error === PIN_STATE.OPEN)
          bannerNote(NOTICE_HOST.REVIEW, tl('핀 #{id} 은 이미 다시 열렸습니다', { id }), NOTICE_KIND.WARN);
        else if (data && data.error === 'conflict') confirmConflict(id, data.pin);
        else if (!data.ok)
          bannerNote(NOTICE_HOST.REVIEW, tl('확인 실패 — 핀 #{id} 이 없습니다', { id }), NOTICE_KIND.ERR);
        else markMine(id);
      } catch (error) {}
      CONFIRMING.delete(id);
      CONFIRMING_PIN.delete(id);
      await loadPins();
    },
    // The undo puts the pin back as the latest list has it (CONFIRMING_PIN, which applyPinLists keeps or drops): still
    // awaiting review, it goes back where it was; gone from that list it is not brought back - the order stays as the
    // server has it - and a pin deleted elsewhere is said so (a reopened or confirmed one is on its own list already).
    () => {
      const now = CONFIRMING_PIN.get(id);
      CONFIRMING.delete(id);
      CONFIRMING_PIN.delete(id);
      if (now && !REVIEW_ALL.some((listed) => listed.id === id)) {
        const index = Math.min(at, REVIEW_ALL.length);
        setReviewAll([...REVIEW_ALL.slice(0, index), now, ...REVIEW_ALL.slice(index)]);
      } else if (
        pin &&
        !now &&
        ![OPEN_ALL, REVIEW_ALL, DONE_ALL].some((list) => list.some((listed) => listed.id === id))
      )
        lineNote(tl('핀 #{id} 은 그사이 다른 곳에서 지워졌습니다', { id }), NOTICE_KIND.WARN);
      drawPins();
      marks();
    },
  );
  deferredNote(pendingConfirm, NOTICE_PLACE.ROW, tl('핀 #{id} 확인 · 완료로 옮겼습니다', { id }), {
    pin: id,
    sec: 'review',
    prev: cardBefore,
    rec: pin,
  });
}
// Undo of [완료] (its row's [되돌리기]). The viewer has no [다시 열기] button: a reply reopens by the server rule.
// Silent: the card comes back. Resolves with whether the pin was reopened (the row waits for it, noticeAct).
async function reopenPin(id: number): Promise<boolean> {
  let ok = false;
  try {
    await api('/api/pins/' + id + '/reopen', { method: 'POST', what: '다시 열기', where: NOTICE_HOST.LIST });
    ok = true;
    markMine(id);
    quietNote(tl('핀 #{id} 완료를 되돌렸습니다', { id }));
  } catch (error) {}
  await loadPins();
  return ok;
}
// [삭제] (a verdict pin's card: [지우기]) takes the pin off the list at once (no confirmation) and leaves a row in its
// place with [되돌리기] for NOTICE_MS; it waits in the Trash. A failure puts the card back. undoSave = the save chip's
// [되돌리기]: silent, as the composer comes back with the selection - and again = what that failure's [다시 시도] runs
// (the whole undo, so the composer comes back too). options.say: the caller says the drop and offers its undo where it
// was pressed (a page line's [판정 취소], verdict.ts cancelLineVerdict), options.where is where a failure is said and
// options.what what it names. Resolves with whether the pin was deleted.
async function dropPin(
  id: number | null,
  undoSave: boolean,
  again?: () => unknown,
  options?: { say?: () => void; where?: string; what?: string },
): Promise<boolean> {
  const was = OPEN_ALL,
    applied = PINS_APPLIED_SEQ,
    cardBefore = drawnBefore($('#pins'), '.pin.card', id),
    record = was.find((pin) => pin.id === id) || null;
  let ok = false,
    lost = false;
  setOpenAll(OPEN_ALL.filter((pin) => pin.id !== id));
  setPins(PINS.filter((pin) => pin.id !== id));
  if (EDITOR.current && EDITOR.current.id === id) EDITOR.current = null;
  drawPins();
  marks();
  // this person's own drop: the next list never says someone else deleted it, also when the answer is lost
  markMine(id);
  const source = 'POST /api/pins/' + id + '/drop';
  try {
    await api('/api/pins/' + id + '/drop', {
      method: 'POST',
      what: (options && options.what) || '삭제',
      where: (options && options.where) || NOTICE_HOST.LIST,
      retry:
        again ||
        (() => {
          dropPin(id, undoSave, undefined, options);
        }),
    });
    ok = true;
  } catch (error) {
    const failure = error as ApiError;
    lost = !failure || !failure.status;
    if (PINS_APPLIED_SEQ === applied) {
      const old = was.find((pin) => pin.id === id);
      if (old && !OPEN_ALL.some((pin) => pin.id === id)) {
        const next = was.slice(was.indexOf(old) + 1).find((pin) => OPEN_ALL.some((listed) => listed.id === pin.id));
        const at = next ? OPEN_ALL.findIndex((pin) => pin.id === next.id) : OPEN_ALL.length;
        setOpenAll([...OPEN_ALL.slice(0, at), old, ...OPEN_ALL.slice(at)]);
        setPins(OPEN_ALL.filter((pin) => pdoc(pin) === DOC));
        drawPins();
        marks();
      }
    }
  }
  await loadPins();
  // An answer lost on the way back: the list says whether the pin went. If it did the drop is done - its failure and
  // its [다시 시도] (which would find nothing to drop) go, and it is said as done.
  if (!ok && lost && !findAnyPin(id) && DROPPED.some((dropped) => dropped.id === id)) {
    ok = true;
    sourceOk(source);
  }
  if (ok) {
    markMine(id);
    if (undoSave) quietNote(tl('핀 #{id} 저장을 되돌렸습니다', { id }));
    else if (options && options.say) options.say();
    else
      undoNote(
        NOTICE_PLACE.ROW,
        tl('핀 #{id} 삭제됨 · 휴지통에 30일 보관', { id }),
        { label: '되돌리기', wait: true, fn: () => restorePin(id) },
        { pin: id, sec: 'open', prev: cardBefore, rec: record },
      );
  }
  return ok;
}
// [영구 삭제] (owner): the row leaves the Trash at once and a row in its place offers [되돌리기]; the request goes out
// when that row does (deferred, NOTICE_MS).
const PURGING = new Set();
function purgePin(id) {
  const cardBefore = drawnBefore($('#trash-list'), '.arc-row', id);
  PURGING.add(id);
  drawTrash();
  drawPins();
  const pendingPurge = deferred(
    async () => {
      try {
        await api('/api/pins/' + id + '/purge', {
          method: 'POST',
          what: '영구 삭제',
          where: NOTICE_HOST.TRASH,
          keepalive: true,
        });
      } catch (error) {}
      PURGING.delete(id);
      await loadPins();
    },
    () => {
      PURGING.delete(id);
      drawTrash();
      drawPins();
    },
  );
  deferredNote(pendingPurge, NOTICE_PLACE.TRASH, tl('핀 #{id} 영구 삭제', { id }), { pin: id, prev: cardBefore });
}
// [되살리기] (the Trash, a deleted pin's row, a background message): the pin is back as it was. Silent - its card is
// there. Resolves with whether it was restored: a message whose action this is stays until then (noticeAct); a failure
// says itself where it can be seen (bannerNote: the status line while the panel is closed). settled runs once the
// request is answered, before the list reload (trashRestore's bound is the request's).
async function restorePin(id: number | null, settled?: () => void): Promise<boolean> {
  let ok = false;
  try {
    await api('/api/pins/' + id + '/restore', {
      method: 'POST',
      what: '되살리기',
      where: NOTICE_HOST.LIST,
      retry: () => {
        restorePin(id);
      },
    });
    ok = true;
    markMine(id);
    quietNote(tl('핀 #{id} 되살림', { id }));
  } catch (error) {}
  if (settled) settled();
  await loadPins();
  return ok;
}
// [되살리기] on a Trash row: restorePin with the bound an undo's request has (noticeAct, NOTICE_ACT_WAIT). Past it
// without an answer '되살리기의 답이 늦습니다 · 핀 #N' is said where a failure of it would be (bannerNote: the Trash
// while it is open, else the list, else the status line - one title there, as noticeLate's), once per pin (its source).
// Closing the Trash takes it out to where it can be seen, as the Trash's undo rows go to the status line. It goes when
// the request is answered - not after the list reload, so a failure's banner, which takes its place, is never taken
// with it - and a focus on it (its [x]) goes to the row's [되살리기] (the reload then moves it on, trashRefocus), else
// into the Trash, else to the pages.
async function trashRestore(id: number | null) {
  const source = NOTICE_LATE_SRC + 'restore:' + id,
    trash = $('#trash') as HTMLDialogElement;
  const say = () => {
    const text = tr('되살리기의 답이 늦습니다') + ' · ' + tl('핀 #{id}', { id });
    const message = bannerNote(NOTICE_HOST.LIST, text, NOTICE_KIND.WARN, null, { literal: true, source: source });
    if (message && message.place === NOTICE_PLACE.LINE) {
      message.title = text;
      message.desc = '';
      drawStatus();
    }
  };
  const out = () => {
    const notice = sourceEntry(source);
    if (notice && notice.place === NOTICE_PLACE.BANNER && notice.host === NOTICE_HOST.TRASH) {
      endNotice(notice, true);
      say();
    }
  };
  const wait = setTimeout(say, NOTICE_ACT_WAIT);
  trash.addEventListener('close', out);
  await restorePin(id, () => {
    clearTimeout(wait);
    trash.removeEventListener('close', out);
    const notice = sourceEntry(source),
      had = !!notice && !!notice.el && notice.el.contains(document.activeElement);
    sourceOk(source);
    if (!had) return;
    const trashList = $('#trash-list'),
      target = trash.open
        ? ((trashList.querySelector('.arc-row[data-id="' + id + '"] [data-act="restore"]') ||
            trashList.querySelector('[data-act="restore"]') ||
            trash.querySelector('[data-act="trash-close"]')) as HTMLElement | null)
        : null;
    if (target) target.focus();
    else searchToPage();
  });
}
// [풀기]: the in-progress mark goes. Silent - the badge goes with it.
async function unclaimPin(id) {
  try {
    await api('/api/pins/' + id + '/unclaim', {
      method: 'POST',
      what: '처리 중 풀기',
      where: NOTICE_HOST.LIST,
      retry: () => unclaimPin(id),
    });
    markMine(id);
    quietNote(tl('핀 #{id} 처리 중 표시를 풀었습니다', { id }));
  } catch (error) {}
  await loadPins();
}
export {
  CONFIRMING,
  CONFIRMING_PIN,
  PURGING,
  closePin,
  confirmPin,
  dropPin,
  purgePin,
  restorePin,
  trashRestore,
  unclaimPin,
};
