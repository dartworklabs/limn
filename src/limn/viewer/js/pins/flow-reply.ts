// ------------------------------------------------ Reply input field (docs/handbook/viewer.md §스레드와 검토)
// Only one input field is ever open. Its DOM is held on REPLY.el, and when drawPins() redraws cards, it's re-inserted
// into .reply-slot - so the 5-second auto-sync redrawing the list never loses the draft text or cursor (focus is
// restored too). There is one [답글] for every state: on a closed pin (awaiting review or done) the server decides
// whether the reply reopens it (reopens_on_reply), and the line under the box (.r-outcome) previews that decision with
// the same rule (replyReopens) - [상태 유지] (REPLY.flip with REPLY.toggle 'keep') overrides it with reopen:false.
// Sending is deferred behind an undo in the card, where the box was (deferredNote).
import {
  REQUEST_KIND,
  LOCAL_LOGIN,
  META,
  NOTICE_DOT,
  NOTICE_HOST,
  NOTICE_KIND,
  NOTICE_PLACE,
  OPEN_CARDS,
  PEOPLE,
  PIN_STATE,
  REPLY,
  REPLY_DRAFT,
  REPLY_VISITS,
  ROLE,
  SIDE_OPEN,
  setReply,
} from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { bannerNote, deferred, deferredNote, lineNote } from '../platform/notices.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { viewerBlocked } from '../documents/flow-boot.ts';
import { markMine, pinState } from '../documents/api.ts';
import { setSide } from '../layout/flow.ts';
import { meLogin, peopleName } from './view-card-parts.ts';
import { drawPins, loadPins } from './flow-list.ts';
import { mentionHints, mentionPreview, mentionScan } from './input-mentions.ts';
import { autoGrow } from './flow-edit.ts';
function isHuman() {
  const me = typeof META !== 'undefined' && META && META.me;
  return !!(
    me &&
    me.login &&
    me.login !== LOCAL_LOGIN &&
    !String(me.login).startsWith('agent:') &&
    me.role !== ROLE.AGENT
  );
}
// Mirrors limn.pins.lifecycle.rules.reopens_on_reply(): an open pin never changes; an explicit override (true/false)
// wins; otherwise a person's reply on a closed pin reopens it unless it tags a person or the pin is a question.
// mentioned = the post's resolved @-tags without me.
function replyReopens(pin: Pin, human: boolean, mentioned: string[], override?: boolean | null) {
  if (pinState(pin) === PIN_STATE.OPEN) return false;
  if (override !== undefined && override !== null) return !!override;
  if (pin.kind_req === REQUEST_KIND.QUESTION || !human) return false;
  return !(mentioned && mentioned.length);
}
// The outcome line: {text, toggle}, or null for an open pin (a reply never changes it). toggle names the one rare
// override the box offers: 'keep' ([상태 유지], reopen:false) where the rule would reopen, 'reopen' ([다시 열기],
// reopen:true) where it keeps a closed pin as it is. flip = that toggle is pressed.
function replyPreview(pin: Pin | null, human: boolean, mentioned: string[], flip: boolean) {
  if (!pin || pinState(pin) === PIN_STATE.OPEN) return null;
  const mentions = mentioned || [];
  const reopens = replyReopens(pin, human, mentions),
    toggle = reopens ? 'keep' : 'reopen',
    names = mentions.map(peopleName).join(', ');
  if (flip && !reopens)
    return {
      text: mentions.length
        ? translateTemplate('보내면 이 핀이 다시 열려 에이전트에게 가고, {names}에게 알림이 갑니다', { names })
        : translate('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),
      toggle,
    };
  if (flip) return { text: translate('보내도 상태는 그대로입니다'), toggle };
  if (reopens) return { text: translate('보내면 이 핀이 다시 열려 에이전트에게 갑니다'), toggle };
  if (pin.kind_req === REQUEST_KIND.QUESTION) return { text: translate('답으로 남고 상태는 그대로입니다'), toggle };
  if (!human) return { text: translate('이 화면은 에이전트로 보내므로 상태는 그대로입니다'), toggle };
  return { text: translateTemplate('보내면 {names}에게 알림이 가고 상태는 그대로입니다', { names }), toggle };
}
// The empty box's placeholder says the same outcome as the line under it would for a reply without @-tags.
function replyPlaceholder(pin: Pin | null, human: boolean, flip: boolean) {
  const closed = !!pin && pinState(pin) !== PIN_STATE.OPEN,
    reopensByDefault = closed && replyReopens(pin, human, []);
  return translate(
    closed && (flip ? !reopensByDefault : reopensByDefault)
      ? '무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)'
      : '답글 (⌘/Ctrl+Enter 보내기)',
  );
}
// After the deferred send: a note only when the server's decision differs from the preview (the pin changed state while
// the undo was up, e.g. someone else's reply reopened it first). Worded from the response, not from the guess.
function replyServerNote(id, predicted, data) {
  if (!data || !data.ok || !!data.reopened === !!predicted) return null;
  if (data.reopened) return translateTemplate('#{id} 은 그사이 닫혀서 이 답글이 다시 열었습니다', { id });
  return data.state === PIN_STATE.OPEN
    ? translateTemplate('#{id} 은 그사이 이미 열려 있어 답글로만 남았습니다', { id })
    : translateTemplate('#{id} 은 다시 열리지 않고 답글로만 남았습니다', { id });
}
// The post's @-tags that count as asking a person: without me and without agent-role accounts (as the server's rule).
// Resolved with exactly the hints the request will carry (mentionHints) - the server resolves the same text with the
// same hints, so an autocompleted '@Robin Lee' later edited down to an ambiguous '@Robin' previews what the server will
// do.
function replyMentioned(field) {
  const me = meLogin();
  return mentionScan(field.value, new Set(mentionHints(field))).hit.filter(
    (login) => login !== me && (PEOPLE.find((x) => x.login === login) || {}).role !== ROLE.AGENT,
  );
}
function createReplyBox(pin: Pin | null) {
  const box = document.createElement('div');
  box.className = 'reply-box';
  setHtml(
    box,
    html`<textarea class="r-text" rows="2" maxlength="1000" aria-label="답글" placeholder="${replyPlaceholder(pin, isHuman(), false)}"></textarea><div class="m-preview" aria-live="polite" hidden></div>\
<div class="r-outcome" aria-live="polite" hidden><span class="r-out-t"></span><button type="button" class="btn-sm r-keep" role="switch" data-act="reply-flip" aria-checked="false"></button></div>\
<div class="r-err errline" role="alert" hidden></div>\
<div class="r-acts"><button class="btn-sm" data-act="reply-cancel" data-tip="입력 칸을 닫습니다 (Esc). 쓰던 글은 남겨 둡니다">취소</button>\
<button class="btn-sm btn-default" data-act="reply-send" data-tip="답글을 보냅니다. 카드에 남는 [되돌리기]를 누르면 보내기 전에 취소됩니다">보내기</button></div>`,
  );
  return box;
}
// The text field of a reply box (createReplyBox puts exactly one in every box).
function replyNote(replyBox: ReplyBox): HTMLTextAreaElement {
  return replyBox.el.querySelector('textarea') as HTMLTextAreaElement;
}
function renderReplyOutcome() {
  const replyBox = REPLY;
  if (!replyBox) return;
  const box = replyBox.el.querySelector('.r-outcome') as HTMLElement,
    field = replyNote(replyBox);
  if (!box || !field) return;
  const pin = findAnyPin(replyBox.id),
    mentioned = replyMentioned(field);
  let preview = pin && replyPreview(pin, isHuman(), mentioned, !!replyBox.flip);
  field.placeholder = replyPlaceholder(pin, isHuman(), !!replyBox.flip);
  if (!preview) {
    box.hidden = true;
    replyBox.flip = false;
    replyBox.toggle = null;
    return;
  }
  if (replyBox.toggle && replyBox.toggle !== preview.toggle && replyBox.flip) {
    replyBox.flip = false;
    preview = replyPreview(pin, isHuman(), mentioned, false);
    if (!preview) return;
  } // the rule changed direction (a tag added/removed): the override resets
  replyBox.toggle = preview.toggle;
  box.hidden = false;
  (box.querySelector('.r-out-t') as HTMLElement).textContent = preview.text;
  box.classList.toggle(
    'reopen',
    replyReopens(pin as Pin, isHuman(), mentioned, replyBox.flip ? preview.toggle === 'reopen' : undefined),
  );
  const flipButton = box.querySelector('[data-act=reply-flip]') as HTMLElement,
    keep = preview.toggle === 'keep';
  flipButton.textContent = translate(keep ? '상태 유지' : '다시 열기');
  flipButton.dataset.tip = translate(
    keep
      ? '보내도 핀을 다시 열지 않고 답글만 남깁니다(드물게 씁니다)'
      : '보내면서 핀을 다시 열어 에이전트에게 보냅니다(드물게 씁니다)',
  );
  flipButton.setAttribute('aria-checked', String(!!replyBox.flip));
}
/**
 * Focus the existing box, or open pin id with copied draft hints and a reset override; expand the panel for a new box.
 */
function openReply(id) {
  if (REPLY && REPLY.id === id) {
    const field = replyNote(REPLY);
    if (field) field.focus();
    return;
  }
  if (REPLY) closeReply(false);
  const pin = findAnyPin(id);
  REPLY_VISITS.set(id, (REPLY_VISITS.get(id) || 0) + 1);
  setReply({ id, flip: false, toggle: null, el: createReplyBox(pin) });
  OPEN_CARDS.add(id);
  setSide(true);
  drawPins();
  const field = replyNote(REPLY as ReplyBox),
    draft = REPLY_DRAFT.get('reply:' + id);
  field.value = draft ? draft.text : '';
  field._mentions = new Set(draft ? draft.mentions : []);
  autoGrow(field);
  mentionPreview(field);
  renderReplyOutcome();
  field.focus();
  (REPLY as ReplyBox).el.scrollIntoView({ block: 'nearest' });
}
/**
 * Keep a nonblank reply's text and only the recipient hints its remaining tags carry; optionally redraw after closing.
 */
function closeReply(redraw?) {
  if (!REPLY) return;
  const field = replyNote(REPLY);
  if (field && field.value.trim())
    REPLY_DRAFT.set('reply:' + REPLY.id, { text: field.value, mentions: mentionHints(field) });
  else REPLY_DRAFT.delete('reply:' + REPLY.id);
  setReply(null);
  if (redraw !== false) drawPins();
}
/** Defer a nonblank reply; recover its input only before a newer visit, reporting a late failure on the status line. */
function sendReply() {
  const replyBox = REPLY;
  if (!replyBox || viewerBlocked()) return;
  const field = replyNote(replyBox),
    text = field.value.trim();
  const errorLine = replyBox.el.querySelector('.r-err') as HTMLElement;
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
  const back = (err) => {
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
    const boxErrorLine = REPLY && REPLY.id === id ? (REPLY.el.querySelector('.r-err') as HTMLElement) : null;
    if (REPLY && REPLY.id === id) {
      const field = replyNote(REPLY);
      field._mentions = new Set(hints);
      REPLY.flip = flip;
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
        const { data } = await api('/api/pins/' + id + '/reply', {
          method: 'POST',
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
        const err = error as ApiError; // silent above: the box's own line says it, once
        back(
          err.status
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
  if (undoButton) (undoButton as HTMLElement).focus({ preventScroll: true });
}
export { closeReply, isHuman, openReply, renderReplyOutcome, replyNote, sendReply };
