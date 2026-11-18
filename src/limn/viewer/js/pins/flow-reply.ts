// ------------------------------------------------ Reply input field (docs/handbook/viewer.md §스레드와 검토)
// Only one input field is ever open. Its DOM is held on REPLY.el, and when drawPins() redraws cards, it's re-inserted
// into .reply-slot - so the 5-second auto-sync redrawing the list never loses the draft text or cursor (focus is
// restored too). There is one [답글] for every state: on a closed pin (awaiting review or done) the server decides
// whether the reply reopens it (reopens_on_reply), and the line under the box (.r-outcome) previews that decision with
// the same rule (replyReopens) - [상태 유지] (REPLY.flip with REPLY.toggle 'keep') overrides it with reopen:false.
// Sending is deferred behind an undo in the card, where the box was (deferredNote).
import {
  OPEN_CARDS,
  REPLY,
  setReplyFlip,
  REPLY_DRAFT,
  REPLY_VISITS,
  SIDE_OPEN,
  setReply,
  findAnyPin,
} from '../app/state.ts';
import {
  replyReopens,
  replyMentioned,
  createReplyBox,
  renderReplyOutcome,
  replyNote,
  parkReply,
} from './view-reply.ts';
import { findElement, findMaybe } from '../platform/dom.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { api, isApiError } from '../platform/api.ts';
import { bannerNote, deferred, deferredNote, lineNote } from '../platform/notices.ts';
import { setSide } from '../layout/flow.ts';
import { drawPins, loadPins } from './flow-list.ts';
import { mentionHints, mentionPreview } from '../composer/input-mentions.ts';
import { NOTICE_DOT, NOTICE_HOST, NOTICE_KIND, NOTICE_PLACE } from '../platform/tables.ts';
import { PIN_STATE } from '../app/rules-tables.ts';
import { pinState } from '../app/rules-pins.ts';
import { isHuman } from '../app/state-people.ts';
import { viewerBlocked } from '../documents/state.ts';
import { autoGrow } from '../composer/view-text.ts';
import { markMine } from './state.ts';
// The answer to a reply (POST /api/pins/{id}/reply): whether the pin was found, whether the reply reopened it, and its state.
interface ReplyAnswer {
  ok?: boolean;
  reopened?: boolean;
  state?: string | null;
}
// After the deferred send: a note only when the server's decision differs from the preview (the pin changed state while
// the undo was up, e.g. someone else's reply reopened it first). Worded from the response, not from the guess.
function replyServerNote(id: number, predicted: boolean, data: ReplyAnswer | null | undefined) {
  if (!data || !data.ok || !!data.reopened === !!predicted) return null;
  if (data.reopened) return translateTemplate('#{id} 은 그사이 닫혀서 이 답글이 다시 열었습니다', { id });
  return data.state === PIN_STATE.OPEN
    ? translateTemplate('#{id} 은 그사이 이미 열려 있어 답글로만 남았습니다', { id })
    : translateTemplate('#{id} 은 다시 열리지 않고 답글로만 남았습니다', { id });
}
/**
 * Focus the existing box, or open pin id with copied draft hints and a reset override; expand the panel for a new box.
 */
function openReply(id: number) {
  if (REPLY && REPLY.id === id) {
    const field = replyNote(REPLY);
    if (field) field.focus();
    return;
  }
  if (REPLY) parkReply();
  const pin = findAnyPin(id);
  REPLY_VISITS.set(id, (REPLY_VISITS.get(id) || 0) + 1);
  const replyBox: ReplyBox = { id, flip: false, toggle: null, el: createReplyBox(pin) };
  setReply(replyBox);
  OPEN_CARDS.add(id);
  setSide(true);
  drawPins();
  const field = replyNote(replyBox),
    draft = REPLY_DRAFT.get('reply:' + id);
  field.value = draft ? draft.text : '';
  field._mentions = new Set(draft ? draft.mentions : []);
  autoGrow(field);
  mentionPreview(field);
  renderReplyOutcome();
  field.focus();
  replyBox.el.scrollIntoView({ block: 'nearest' });
}
// Close the reply field at the user's request and redraw the list with the draft parked.
function closeReply() {
  if (!REPLY) return;
  parkReply();
  drawPins();
}
/** Defer a nonblank reply; recover its input only before a newer visit, reporting a late failure on the status line. */
function sendReply() {
  const replyBox = REPLY;
  if (!replyBox || viewerBlocked()) return;
  const field = replyNote(replyBox),
    text = field.value.trim();
  const errorLine = findElement(replyBox.el, '.r-err', HTMLElement);
  if (!text) {
    errorLine.textContent = translate('답글이 비어 있습니다');
    errorLine.hidden = false;
    field.focus();
    return;
  }
  const id = replyBox.id,
    visit = REPLY_VISITS.get(id),
    pin = findAnyPin(id),
    body: { text: string; mentions?: ReturnType<typeof mentionHints>; reopen?: boolean } = { text },
    hints = mentionHints(field),
    flip = !!replyBox.flip;
  if (hints.length) body.mentions = hints;
  if (flip && pin && pinState(pin) !== PIN_STATE.OPEN && replyBox.toggle) body.reopen = replyBox.toggle === 'reopen';
  const reopens = !!pin && replyReopens(pin, isHuman(), replyMentioned(field), body.reopen);
  // Back into the box - after [되돌리기], or with an inline error when sending failed, so the draft is visibly kept.
  // That error line (an alert) is the one place a failed send is said; with the box off screen (the panel closed) the
  // status line says it instead (rule 1).
  const back = (err: string | null) => {
    if (REPLY_VISITS.get(id) !== visit) {
      if (err)
        lineNote(translate('보내지 못했습니다') + ' — #' + id, NOTICE_KIND.ERR, null, {
          dot: NOTICE_DOT.SIDE,
          literal: true,
        });
      return;
    }
    REPLY_DRAFT.set('reply:' + id, { text, mentions: hints });
    openReply(id);
    const boxErrorLine = REPLY && REPLY.id === id ? findMaybe(REPLY.el, '.r-err', HTMLElement) : null;
    if (REPLY && REPLY.id === id) {
      const field = replyNote(REPLY);
      field._mentions = new Set(hints);
      setReplyFlip(REPLY, flip);
      mentionPreview(field);
      renderReplyOutcome();
      if (boxErrorLine) {
        boxErrorLine.textContent = err || '';
        boxErrorLine.hidden = !err;
      }
    }
    if (err && !(SIDE_OPEN && boxErrorLine && boxErrorLine.getClientRects().length))
      lineNote(err, NOTICE_KIND.ERR, null, { dot: NOTICE_DOT.SIDE, literal: true });
  };
  REPLY_DRAFT.delete('reply:' + id);
  setReply(null);
  drawPins(); // the box closes at once; the post waits for its undo
  const section = !pin
    ? 'open'
    : pinState(pin) === PIN_STATE.REVIEW
      ? 'review'
      : pinState(pin) === PIN_STATE.DONE
        ? 'done'
        : 'open';
  const pendingSend = deferred(
    async () => {
      markMine(id);
      try {
        const { data } = await api('POST /api/pins/{id}/reply', {
          id,
          body,
          what: '답글',
          silent: true,
          keepalive: true,
        });
        if (!data.ok) bannerNote(NOTICE_HOST.LIST, translateTemplate('핀 #{id} 이 없습니다', { id }), NOTICE_KIND.ERR);
        else {
          const note = replyServerNote(id, reopens, data);
          if (note) bannerNote(NOTICE_HOST.LIST, note, NOTICE_KIND.WARN);
        }
      } catch (error) {
        const err = isApiError(error) ? error : null; // silent above: the box's own line says it, once
        back(
          err && err.status
            ? translate('보내지 못했습니다') + ' — ' + (errText(err.data) || 'HTTP ' + err.status)
            : translate('보내지 못했습니다 — 글은 그대로 두었습니다. 연결을 확인하고 다시 보내세요'),
        );
      }
      await loadPins();
    },
    () => back(null),
  );
  const note = deferredNote(
    pendingSend,
    NOTICE_PLACE.CARD,
    translateTemplate(reopens ? '핀 #{id} 다시 열어 에이전트에게 보냄' : '#{id} 에 답글을 남겼습니다', { id }),
    { pin: id, sec: section },
  );
  // Keyboard users (Ctrl+Enter) land on [되돌리기], so Enter undoes; the reply still goes when its undo does.
  const undoButton = document.querySelector('[data-act="notice-act"][data-n="' + note.n + '"]');
  if (undoButton instanceof HTMLElement) undoButton.focus({ preventScroll: true });
}
export { closeReply, openReply, sendReply };
