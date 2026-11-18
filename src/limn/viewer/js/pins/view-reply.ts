// The reply box, its predicted outcome and the draft kept as it closes.
import { PEOPLE, REPLY, REPLY_DRAFT, setReply, findAnyPin } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { findElement, findMaybe } from '../platform/dom.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { mentionHints, mentionScan } from '../composer/input-mentions.ts';
import { REQUEST_KIND, PIN_STATE, ROLE } from '../app/rules-tables.ts';
import { pinState } from '../app/rules-pins.ts';
import { meLogin, peopleName, isHuman } from '../app/state-people.ts';

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
// The post's @-tags that count as asking a person: without me and without agent-role accounts (as the server's rule).
// Resolved with exactly the hints the request will carry (mentionHints) - the server resolves the same text with the
// same hints, so an autocompleted '@Robin Lee' later edited down to an ambiguous '@Robin' previews what the server will
// do.
function replyMentioned(field: HTMLTextAreaElement) {
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
  return findElement(replyBox.el, 'textarea', HTMLTextAreaElement);
}
function renderReplyOutcome() {
  const replyBox = REPLY;
  if (!replyBox) return;
  const box = findMaybe(replyBox.el, '.r-outcome', HTMLElement),
    field = replyNote(replyBox);
  if (!box || !field) return;
  const pin = findAnyPin(replyBox.id),
    mentioned = replyMentioned(field);
  let preview = pin && replyPreview(pin, isHuman(), mentioned, !!replyBox.flip);
  field.placeholder = replyPlaceholder(pin, isHuman(), !!replyBox.flip);
  if (!preview || !pin) {
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
  findElement(box, '.r-out-t', Element).textContent = preview.text;
  box.classList.toggle(
    'reopen',
    replyReopens(pin, isHuman(), mentioned, replyBox.flip ? preview.toggle === 'reopen' : undefined),
  );
  const flipButton = findElement(box, '[data-act=reply-flip]', HTMLElement),
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
 * Keep a nonblank reply's text and only the recipient hints its remaining tags carry.
 */
function parkReply() {
  if (!REPLY) return;
  const field = replyNote(REPLY);
  if (field && field.value.trim())
    REPLY_DRAFT.set('reply:' + REPLY.id, { text: field.value, mentions: mentionHints(field) });
  else REPLY_DRAFT.delete('reply:' + REPLY.id);
  setReply(null);
}

export { replyReopens, replyMentioned, createReplyBox, renderReplyOutcome, replyNote, parkReply };
