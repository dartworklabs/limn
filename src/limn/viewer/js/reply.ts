// ------------------------------------------------ Reply input field (docs/handbook/viewer.md §스레드와 검토)
// Only one input field is ever open. Its DOM is held on REPLY.el, and when drawPins() redraws cards, it's re-inserted
// into .reply-slot - so the 5-second auto-sync redrawing the list never loses the draft text or cursor (focus is
// restored too). There is one [답글] for every state: on a closed pin (awaiting review or done) the server decides whether the
// reply reopens it (reopens_on_reply), and the line under the box (.r-outcome) previews that decision with the same rule
// (replyReopens) - [상태 유지] (REPLY.flip with REPLY.toggle 'keep') overrides it with reopen:false. Sending is deferred behind an
// undo in the card, where the box was (deferredNote).
import {
  KIND_REQ,
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
} from './core.ts';
import { html, setHtml } from './markup.ts';
import { errText, tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { bannerNote, deferred, deferredNote, lineNote } from './notices.ts';
import { findAnyPin } from './revisions.ts';
import { viewerBlocked } from './boot.ts';
import { markMine, pinState } from './polling.ts';
import { setSide } from './layout.ts';
import { meLogin, peopleName } from './card-parts.ts';
import { drawPins, loadPins } from './list.ts';
import { mentionHints, mentionPreview, mentionScan } from './mentions.ts';
import { autoGrow } from './edit.ts';
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
// Mirrors limn.pins.lifecycle.rules.reopens_on_reply(): an open pin never changes; an explicit override (true/false) wins; otherwise a person's reply
// on a closed pin reopens it unless it tags a person or the pin is a question. mentioned = the post's resolved @-tags without me.
function replyReopens(p: Pin, human: boolean, mentioned: string[], override?: boolean | null) {
  if (pinState(p) === PIN_STATE.OPEN) return false;
  if (override !== undefined && override !== null) return !!override;
  if (p.kind_req === KIND_REQ.QUESTION || !human) return false;
  return !(mentioned && mentioned.length);
}
// The outcome line: {text, toggle}, or null for an open pin (a reply never changes it). toggle names the one rare override the box
// offers: 'keep' ([상태 유지], reopen:false) where the rule would reopen, 'reopen' ([다시 열기], reopen:true) where it keeps a closed pin
// as it is. flip = that toggle is pressed.
function replyPreview(p: Pin | null, human: boolean, mentioned: string[], flip: boolean) {
  if (!p || pinState(p) === PIN_STATE.OPEN) return null;
  const m = mentioned || [];
  const reopens = replyReopens(p, human, m),
    toggle = reopens ? 'keep' : 'reopen',
    names = m.map(peopleName).join(', ');
  if (flip && !reopens)
    return {
      text: m.length
        ? tl('보내면 이 핀이 다시 열려 에이전트에게 가고, {names}에게 알림이 갑니다', { names })
        : tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'),
      toggle,
    };
  if (flip) return { text: tr('보내도 상태는 그대로입니다'), toggle };
  if (reopens) return { text: tr('보내면 이 핀이 다시 열려 에이전트에게 갑니다'), toggle };
  if (p.kind_req === KIND_REQ.QUESTION) return { text: tr('답으로 남고 상태는 그대로입니다'), toggle };
  if (!human) return { text: tr('이 화면은 에이전트로 보내므로 상태는 그대로입니다'), toggle };
  return { text: tl('보내면 {names}에게 알림이 가고 상태는 그대로입니다', { names }), toggle };
}
// The empty box's placeholder says the same outcome as the line under it would for a reply without @-tags.
function replyPlaceholder(p: Pin | null, human: boolean, flip: boolean) {
  const closed = !!p && pinState(p) !== PIN_STATE.OPEN,
    def = closed && replyReopens(p, human, []);
  return tr(
    closed && (flip ? !def : def)
      ? '무엇이 틀렸는지 적으면 다시 열려 에이전트에게 갑니다 (⌘/Ctrl+Enter 보내기)'
      : '답글 (⌘/Ctrl+Enter 보내기)',
  );
}
// After the deferred send: a note only when the server's decision differs from the preview (the pin changed state while the
// undo was up, e.g. someone else's reply reopened it first). Worded from the response, not from the guess.
function replyServerNote(id, predicted, data) {
  if (!data || !data.ok || !!data.reopened === !!predicted) return null;
  if (data.reopened) return tl('#{id} 은 그사이 닫혀서 이 답글이 다시 열었습니다', { id });
  return data.state === PIN_STATE.OPEN
    ? tl('#{id} 은 그사이 이미 열려 있어 답글로만 남았습니다', { id })
    : tl('#{id} 은 다시 열리지 않고 답글로만 남았습니다', { id });
}
// The post's @-tags that count as asking a person: without me and without agent-role accounts (as the server's rule).
// Resolved with exactly the hints the request will carry (mentionHints) - the server resolves the same text with the same hints,
// so an autocompleted '@Robin Lee' later edited down to an ambiguous '@Robin' previews what the server will do (PR #11 review).
function replyMentioned(ta) {
  const me = meLogin();
  return mentionScan(ta.value, new Set(mentionHints(ta))).hit.filter(
    (l) => l !== me && (PEOPLE.find((x) => x.login === l) || {}).role !== ROLE.AGENT,
  );
}
function replyEl(p: Pin | null) {
  const el = document.createElement('div');
  el.className = 'reply-box';
  setHtml(
    el,
    html`<textarea class="r-text" rows="2" maxlength="1000" aria-label="답글" placeholder="${replyPlaceholder(p, isHuman(), false)}"></textarea><div class="m-preview" aria-live="polite" hidden></div>\
<div class="r-outcome" aria-live="polite" hidden><span class="r-out-t"></span><button type="button" class="btn-sm r-keep" role="switch" data-act="reply-flip" aria-checked="false"></button></div>\
<div class="r-err errline" role="alert" hidden></div>\
<div class="r-acts"><button class="btn-sm" data-act="reply-cancel" data-tip="입력 칸을 닫습니다 (Esc). 쓰던 글은 남겨 둡니다">취소</button>\
<button class="btn-sm btn-default" data-act="reply-send" data-tip="답글을 보냅니다. 카드에 남는 [되돌리기]를 누르면 보내기 전에 취소됩니다">보내기</button></div>`,
  );
  return el;
}
// The text field of reply box R (replyEl puts exactly one in every box).
function replyNote(R: ReplyBox): HTMLTextAreaElement {
  return R.el.querySelector('textarea') as HTMLTextAreaElement;
}
function renderReplyOutcome() {
  const R = REPLY;
  if (!R) return;
  const box = R.el.querySelector('.r-outcome') as HTMLElement,
    ta = replyNote(R);
  if (!box || !ta) return;
  const p = findAnyPin(R.id),
    ment = replyMentioned(ta);
  let pv = p && replyPreview(p, isHuman(), ment, !!R.flip);
  ta.placeholder = replyPlaceholder(p, isHuman(), !!R.flip);
  if (!pv) {
    box.hidden = true;
    R.flip = false;
    R.toggle = null;
    return;
  }
  if (R.toggle && R.toggle !== pv.toggle && R.flip) {
    R.flip = false;
    pv = replyPreview(p, isHuman(), ment, false);
    if (!pv) return;
  } // the rule changed direction (a tag added/removed): the override resets
  R.toggle = pv.toggle;
  box.hidden = false;
  (box.querySelector('.r-out-t') as HTMLElement).textContent = pv.text;
  box.classList.toggle('reopen', replyReopens(p as Pin, isHuman(), ment, R.flip ? pv.toggle === 'reopen' : undefined));
  const k = box.querySelector('[data-act=reply-flip]') as HTMLElement,
    keep = pv.toggle === 'keep';
  k.textContent = tr(keep ? '상태 유지' : '다시 열기');
  k.dataset.tip = tr(
    keep
      ? '보내도 핀을 다시 열지 않고 답글만 남깁니다(드물게 씁니다)'
      : '보내면서 핀을 다시 열어 에이전트에게 보냅니다(드물게 씁니다)',
  );
  k.setAttribute('aria-checked', String(!!R.flip));
}
/** Focus the existing box, or open pin id with copied draft hints and a reset override; expand the panel for a new box. */
function openReply(id) {
  if (REPLY && REPLY.id === id) {
    const t = replyNote(REPLY);
    if (t) t.focus();
    return;
  }
  if (REPLY) closeReply(false);
  const p = findAnyPin(id);
  REPLY_VISITS.set(id, (REPLY_VISITS.get(id) || 0) + 1);
  setReply({ id, flip: false, toggle: null, el: replyEl(p) });
  OPEN_CARDS.add(id);
  setSide(true);
  drawPins();
  const ta = replyNote(REPLY as ReplyBox),
    draft = REPLY_DRAFT.get('reply:' + id);
  ta.value = draft ? draft.text : '';
  ta._mentions = new Set(draft ? draft.mentions : []);
  autoGrow(ta);
  mentionPreview(ta);
  renderReplyOutcome();
  ta.focus();
  (REPLY as ReplyBox).el.scrollIntoView({ block: 'nearest' });
}
/** Keep a nonblank reply's text and only the recipient hints its remaining tags carry; optionally redraw after closing. */
function closeReply(redraw?) {
  if (!REPLY) return;
  const ta = replyNote(REPLY);
  if (ta && ta.value.trim()) REPLY_DRAFT.set('reply:' + REPLY.id, { text: ta.value, mentions: mentionHints(ta) });
  else REPLY_DRAFT.delete('reply:' + REPLY.id);
  setReply(null);
  if (redraw !== false) drawPins();
}
/** Defer a nonblank reply; recover its input only before a newer visit, reporting a late failure on the status line. */
function sendReply() {
  const R = REPLY;
  if (!R || viewerBlocked()) return;
  const ta = replyNote(R),
    text = ta.value.trim();
  const rerr = R.el.querySelector('.r-err') as HTMLElement;
  if (!text) {
    rerr.textContent = tr('답글이 비어 있습니다');
    rerr.hidden = false;
    ta.focus();
    return;
  }
  const id = R.id,
    visit = REPLY_VISITS.get(id),
    p = findAnyPin(id),
    body: { text: string; mentions?: ReturnType<typeof mentionHints>; reopen?: boolean } = { text },
    mh = mentionHints(ta),
    flip = !!R.flip;
  if (mh.length) body.mentions = mh;
  if (flip && p && pinState(p) !== PIN_STATE.OPEN && R.toggle) body.reopen = R.toggle === 'reopen';
  const reopens = !!p && replyReopens(p, isHuman(), replyMentioned(ta), body.reopen);
  // Back into the box - after [되돌리기], or with an inline error when sending failed, so the draft is visibly kept. That
  // error line (an alert) is the one place a failed send is said; with the box off screen (the panel closed) the status line
  // says it instead (rule 1).
  const back = (err) => {
    if (REPLY_VISITS.get(id) !== visit) {
      if (err)
        lineNote(tr('보내지 못했습니다') + ' — #' + id, NOTICE_KIND.ERR, null, { dot: NOTICE_DOT.SIDE, literal: true });
      return;
    }
    REPLY_DRAFT.set('reply:' + id, { text, mentions: mh });
    openReply(id);
    const e = REPLY && REPLY.id === id ? (REPLY.el.querySelector('.r-err') as HTMLElement) : null;
    if (REPLY && REPLY.id === id) {
      const t = replyNote(REPLY);
      t._mentions = new Set(mh);
      REPLY.flip = flip;
      mentionPreview(t);
      renderReplyOutcome();
      if (e) {
        e.textContent = err || '';
        e.hidden = !err;
      }
    }
    if (err && !(SIDE_OPEN && e && e.getClientRects().length))
      lineNote(err, NOTICE_KIND.ERR, null, { dot: NOTICE_DOT.SIDE, literal: true });
  };
  REPLY_DRAFT.delete('reply:' + id);
  setReply(null);
  drawPins(); // the box closes at once; the post waits for its undo
  const sec = !p
    ? 'open'
    : pinState(p) === PIN_STATE.REVIEW
      ? 'review'
      : pinState(p) === PIN_STATE.DONE
        ? 'done'
        : 'open';
  const d = deferred(
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
        if (!data.ok) bannerNote(NOTICE_HOST.LIST, tl('핀 #{id} 이 없습니다', { id }), NOTICE_KIND.ERR);
        else {
          const note = replyServerNote(id, reopens, data);
          if (note) bannerNote(NOTICE_HOST.LIST, note, NOTICE_KIND.WARN);
        }
      } catch (e) {
        const err = e as ApiError; // silent above: the box's own line says it, once
        back(
          err.status
            ? tr('보내지 못했습니다') + ' — ' + (errText(err.data) || 'HTTP ' + err.status)
            : tr('보내지 못했습니다 — 글은 그대로 두었습니다. 연결을 확인하고 다시 보내세요'),
        );
      }
      await loadPins();
    },
    () => back(null),
  );
  const n = deferredNote(
    d,
    NOTICE_PLACE.CARD,
    tl(reopens ? '핀 #{id} 다시 열어 에이전트에게 보냄' : '#{id} 에 답글을 남겼습니다', { id }),
    { pin: id, sec },
  );
  // Keyboard users (Ctrl+Enter) land on [되돌리기], so Enter undoes; the reply still goes when its undo does.
  const b = document.querySelector('[data-act="notice-act"][data-n="' + n.n + '"]');
  if (b) (b as HTMLElement).focus({ preventScroll: true });
}
export { closeReply, isHuman, openReply, renderReplyOutcome, replyNote, sendReply };
