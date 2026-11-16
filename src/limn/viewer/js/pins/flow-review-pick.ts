// ------------------------------------------- Confirming several pins awaiting review from their result rows (ADR-0035)
// The review section's [골라서 확인] (#review-pick) turns its cards into result rows: a box with #N and the place, the
// badges, what was asked, what the agent said (its explanation, reference and changed lines) and [변경 보기]. A person
// ticks the rows whose result they have read and confirms them together with [N건 확인] in the section head's second
// line (#rv-bar). Each confirm is the one-pin route with the done_at the row showed when it was ticked, so a pin closed
// again since is refused (409 conflict) instead of confirmed (ADR-0013). docs/handbook/viewer.md §스레드와 검토 has the
// rules.
import { DONE_ALL, MENTION_ONLY, OPEN_ALL, OPEN_CARDS, PIN_STATE, REVIEW_ALL, setReviewAll } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { errText, translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { ORDER, SECTION_OPEN, savePrefs } from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import { bannerNote, deferred, deferredNote, lineNote, quietNote } from '../platform/notices.ts';
import { pdoc } from '../documents/view-tabs.ts';
import { showChange } from '../revisions/flow.ts';
import { canConfirmReview } from '../documents/flow-boot.ts';
import { markMine, pinState } from '../documents/flow-polling.ts';
import { lineRange } from '../composer/view-levels.ts';
import { pinPlace } from '../pdf/view-figure.ts';
import { isMarkdownPin } from '../markdown/view.ts';
import { suggestBadge } from '../composer/flow-suggest.ts';
import { verdictBadge, verdictOf, verdictOldMarker, verdictTarget } from '../verdict/flow-line.ts';
import { docChip, fmtText, isQuestion, locText, mentionsMe, messageBody } from './view-card-parts.ts';
import { drawPins, jumpToCard, listReview, loadPins, marks, orderPins } from './flow-list.ts';
import { CONFIRMING, CONFIRMING_PIN } from './flow-actions.ts';
import type { Html } from '../platform/markup.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_PLACE } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';

// The ticked rows while the review section picks: pin id -> the done_at its row showed when it was ticked ('' for a
// close with none). null while the section shows cards.
let REVIEW_PICK = null as Map<number, string> | null;

// Whether a pin's row shows a result a person can have read: the agent's explanation or the lines it changed. A row
// without one cannot be ticked - that pin is confirmed from its card (ADR-0035 D2). Pure.
function showsResult(pin: Pin): boolean {
  return !!String(pin.close_reply || '').trim() || (Array.isArray(pin.changes) && pin.changes.length > 0);
}

// The changed lines of a pin's close, short: '바뀐 줄 L33-L35', with the file's name first when the first range is in
// another file than the pin's, and '+N' for the ranges after it. '' when the close names none. Pure.
function changedLinesText(pin: Pin): string {
  const changes = Array.isArray(pin.changes) ? pin.changes : [];
  if (!changes.length) return '';
  const firstChange = changes[0],
    own = String(pin.file || ''),
    other =
      own && firstChange.file !== own
        ? String(firstChange.file || '')
            .split('/')
            .pop() + ' '
        : '';
  return (
    translateTemplate('바뀐 줄 {at}', { at: other + lineRange(firstChange.lo, firstChange.hi) }) +
    (changes.length > 1 ? ' +' + (changes.length - 1) : '')
  );
}

// Whether the review section may pick now: a person who may confirm, two or more listed pins and one row with a result.
/** @param list the review pins the section lists */
function canPickReviews(list: Pin[]): boolean {
  return canConfirmReview() && list.length >= 2 && list.some(showsResult);
}

// One result row of a pin (the review section while it picks). Its box is named by its first line (#N · place · page)
// and described by its explanation. The explanation folds at six lines as a thread post does (messageBody, [더 보기]);
// the reference and the changed lines are a line under it, each kept whole. A row with no result has its box disabled
// and offers [카드에서 확인] on its first line, beside [변경 보기].
function resultRow(pin: Pin): Html {
  const ok = showsResult(pin),
    on = !!REVIEW_PICK && REVIEW_PICK.has(pin.id),
    first = String(pin.note || '')
      .split('\n')[0]
      .trim();
  const at = pinPlace(pin).page,
    page = typeof at === 'number' && !isMarkdownPin(pin) ? translateTemplate('{page}쪽', { page: at }) : '';
  const tags = [
    verdictBadge(pin),
    verdictOldMarker(pin),
    verdictTarget(pin),
    isQuestion(pin)
      ? html`<span class="badge badge-question" data-tip="${TIP_TEXT.question}">${lucideIcon('circle-question-mark')}${translate('질문')}</span>`
      : null,
    suggestBadge(pin, true),
  ].filter((tag) => !!tag && String(tag) !== '');
  const ask = first
    ? fmtText(first, pin.mentions)
    : html`<span class="dim">${translate(pin.suggest ? '(제안 문안만)' : verdictOf(pin) ? '(판정만)' : '(메모 없음)')}</span>`;
  const facts = [pin.close_ref ? String(pin.close_ref) : '', changedLinesText(pin)].filter(Boolean),
    reply = String(pin.close_reply || '').trim();
  const card = ok
    ? ''
    : html`<button type="button" class="arc-orig-t rv-act hit" data-act="rv-card" data-tip="${translate('고르기를 끝내고 이 핀의 카드로 갑니다. 카드에서 결과를 보고 확인하세요')}">${translate('카드에서 확인')}</button>`;
  const said = !ok
    ? html`<span class="dim">${translate('설명 없이 닫힘')}</span>`
    : html`${reply ? messageBody({ text: reply, mentions: pin.mentions } as ThreadEntry, 'rv:' + pin.id) : html`<div class="dim">${translate('설명 없음')}</div>`}\
${facts.length ? html`<div class="rv-facts" translate="no">${facts.map((fact, index) => html`${index ? ' · ' : ''}<span>${fact}</span>`)}</div>` : ''}`;
  return html`<div class="rv-row${on ? ' on' : ''}${ok ? '' : ' off'}" data-id="${pin.id}" data-doc="${pdoc(pin)}">\
<div class="rv-l1"><label class="rv-ck hit"><span class="ck"><input type="checkbox" data-pick="${pin.id}"${on ? ' checked' : ''}${ok ? '' : ' disabled'} aria-describedby="rv-a-${pin.id}">\
${lucideIcon('check')}${lucideIcon('minus')}</span><span class="rv-h"><span class="rv-no">#${pin.id}</span> · ${locText(pin)}${page ? ' · ' + page : ''}</span>${docChip(pin)}</label>\
${card}<button type="button" class="arc-orig-t rv-act rv-chg hit" data-act="change" data-tip="${TIP_TEXT.change}">${translate('변경 보기')}</button></div>\
<div class="rv-body">${tags.length ? html`<div class="rv-tags">${tags}</div>` : ''}\
<span class="rv-k">${translate('요청')}</span><span class="rv-ask" translate="no">${ask}</span>\
<span class="rv-k">${translate('설명')}</span><div class="rv-ans" id="rv-a-${pin.id}">${said}</div></div></div>`;
}

// The head's second line while the section picks: [모두 고르기 (N)] (half-ticked while some are) and [N건 확인]. Hidden
// while it does not pick.
/** @param list the review pins the section lists */
function drawPickBar(list: Pin[]) {
  const bar = $('#rv-bar');
  bar.hidden = !REVIEW_PICK;
  if (!REVIEW_PICK) {
    bar.replaceChildren();
    return;
  }
  const can = list.filter(showsResult),
    tickedCount = can.filter((pin) => !!REVIEW_PICK && REVIEW_PICK.has(pin.id)).length,
    all = tickedCount > 0 && tickedCount === can.length;
  setHtml(
    bar,
    html`<label class="rv-all"><span class="ck"><input type="checkbox" id="rv-all"${all ? ' checked' : ''}>${lucideIcon('check')}${lucideIcon('minus')}</span>\
<span class="lbl">${translateTemplate('모두 고르기 ({n})', { n: can.length })}</span></label><span class="sp"></span>\
<button type="button" class="btn-sm btn-soft rv-go" id="rv-go" data-act="rv-go"${tickedCount ? '' : ' disabled'} data-tip="${translate('고른 핀을 확인해 완료로 옮깁니다. 6초 안에 되돌릴 수 있습니다')}">${tickedCount ? translateTemplate('{n}건 확인', { n: tickedCount }) : translate('확인')}</button>`,
  );
  ($('#rv-all') as HTMLInputElement).indeterminate = tickedCount > 0 && !all;
}

// What has the focus in the picking section, as a redraw can find it again: a row's box, or a control of the row by its
// data-act and its place among the row's controls of that act (two #N in an explanation are both 'pin-ref'), or one of
// the bar's controls by its id. null when the focus is elsewhere.
function findPickFocus(): { sel: string; i: number } | null {
  const focused = document.activeElement as HTMLElement | null;
  if (!focused || !focused.closest) return null;
  const row = focused.closest('.rv-row[data-id]') as HTMLElement | null,
    at = row ? '.rv-row[data-id="' + row.dataset.id + '"] ' : '';
  if (row && focused.matches('input[data-pick]')) return { sel: at + 'input[data-pick]', i: 0 };
  if (row && focused.dataset.act) {
    const selector = at + '[data-act="' + CSS.escape(focused.dataset.act) + '"]';
    return { sel: selector, i: [...document.querySelectorAll(selector)].indexOf(focused) };
  }
  return focused.closest('#rv-bar') && focused.id ? { sel: '#' + CSS.escape(focused.id), i: 0 } : null;
}
// Gives the focus back after a redraw to what findPickFocus found (the same place among its kind, else the first), or -
// that gone or disabled - to [골라서 확인], else to the section's toggle. Only when the redraw dropped the focus to the
// page.
function restorePickFocus(kept: { sel: string; i: number } | null) {
  const focused = document.activeElement;
  if (!kept || (focused && focused !== document.body)) return;
  const all = document.querySelectorAll(kept.sel),
    target = (all[Math.max(0, kept.i)] || all[0] || null) as HTMLElement | null,
    pick = $('#review-pick') as HTMLElement;
  const to =
    target && !(target as HTMLInputElement).disabled
      ? target
      : !pick.hidden
        ? pick
        : ($('#review-toggle') as HTMLElement);
  to.focus({ preventScroll: true });
}

// Draws the review section's rows while it picks, and its head's button and bar either way; drawPins calls it with the
// pins the section lists. A pick that cannot go on (one pin left, no row with a result, no right to confirm) or whose
// rows are folded away (the section collapsed) ends here, and a tick on a pin that left the list or lost its result
// goes. Returns whether it drew rows (else drawPins draws the cards).
function drawReviewPick(list: Pin[]): boolean {
  const can = canPickReviews(list),
    keep = REVIEW_PICK ? findPickFocus() : null;
  if (REVIEW_PICK && (!can || !SECTION_OPEN.review)) {
    REVIEW_PICK = null;
    if (keep) ($('#review-toggle') as HTMLElement).focus({ preventScroll: true });
  } // the cards drawn next hold no focus
  if (REVIEW_PICK) {
    const listed = new Map(list.map((pin) => [pin.id, pin]));
    for (const id of [...REVIEW_PICK.keys()]) {
      const pin = listed.get(id);
      if (!pin || !showsResult(pin)) REVIEW_PICK.delete(id);
    }
  }
  // The head's toggle keeps its name, as [모든 문서] does: pressed, it is filled and leads with a check.
  const pickButton = $('#review-pick') as HTMLElement;
  pickButton.hidden = !can;
  pickButton.setAttribute('aria-pressed', String(!!REVIEW_PICK));
  setHtml(pickButton, html`${REVIEW_PICK ? lucideIcon('check') : ''}${translate('골라서 확인')}`);
  $('#sec-review').classList.toggle('rv-picking', !!REVIEW_PICK);
  drawPickBar(list);
  if (REVIEW_PICK) setHtml($('#review-pins'), html`${orderPins(list, ORDER).map(resultRow)}`);
  restorePickFocus(keep);
  return !!REVIEW_PICK;
}

// Starts (on) or ends picking. Starting opens a collapsed section (and keeps it open, as [검토 M] does), brings the
// section to the top of the list and gives the focus to [모두 고르기]; ending gives it back to [골라서 확인].
function setReviewPicking(on: boolean) {
  REVIEW_PICK = on ? new Map() : null;
  if (on && !SECTION_OPEN.review) {
    SECTION_OPEN.review = true;
    savePrefs({ sec: SECTION_OPEN });
  }
  drawPins();
  // the section, not its head: a stuck head is where it is shown already and would not scroll
  if (on) $('#sec-review').scrollIntoView({ block: 'start' });
  const target = (on ? $('#rv-all') : $('#review-pick')) as HTMLElement | null;
  if (target && target.getClientRects().length) target.focus({ preventScroll: true });
}

// [카드에서 확인] on a row with no result: the pick ends and the list goes to that pin's card, unfolded, the focus on
// its [확인].
function goToReviewCard(id: number) {
  setReviewPicking(false);
  OPEN_CARDS.add(id);
  drawPins();
  jumpToCard(id);
  const confirmButton = document.querySelector(
    '#review-pins .pin[data-id="' + id + '"] [data-act=confirm]',
  ) as HTMLElement | null;
  if (confirmButton) confirmButton.focus({ preventScroll: true });
}

// A box was ticked or cleared: a row's records the done_at its row shows now (ADR-0035 D3); [모두 고르기] ticks every
// row with a result the section lists, or clears them.
function tickResultBox(box: HTMLInputElement) {
  if (!REVIEW_PICK) return;
  const list = listReviewShown();
  if (box.id === 'rv-all') {
    REVIEW_PICK = new Map(
      box.checked ? list.filter(showsResult).map((pin) => [pin.id, String(pin.done_at || '')]) : [],
    );
  } else {
    const id = Number(box.dataset.pick),
      pin = list.find((listed) => listed.id === id);
    if (!pin) return;
    if (box.checked) REVIEW_PICK.set(id, String(pin.done_at || ''));
    else REVIEW_PICK.delete(id);
  }
  drawPins();
}

// The review pins the section lists now - the same filter drawPins uses ([나를 부른 핀], else the document or [모든
// 문서]).
function listReviewShown(): Pin[] {
  return MENTION_ONLY ? REVIEW_ALL.filter(mentionsMe) : listReview();
}

// [N건 확인]: the ticked pins leave the section at once and the rest stay picking; one undo row stands at the section's
// top for NOTICE_MS - the section is brought to the top of the list so it shows - and gets the focus. When it goes (or
// the page is hidden) every confirm is sent at once (sendConfirms); its [되돌리기] sends nothing and puts the pins back
// (undoConfirms).
function confirmTicked() {
  if (!REVIEW_PICK) return;
  const items = [...REVIEW_PICK]
    .map(([id, at]) => {
      const pin = REVIEW_ALL.find((reviewed) => reviewed.id === id);
      return pin && !CONFIRMING.has(id) ? { pin, at } : null;
    })
    .filter((item) => !!item)
    .map((item) => item as { pin: Pin; at: string });
  if (!items.length) return;
  const where = new Map(items.map((item) => [item.pin.id, REVIEW_ALL.indexOf(item.pin)])),
    ticks = new Map(items.map((item) => [item.pin.id, item.at]));
  for (const { pin } of items) {
    CONFIRMING.add(pin.id);
    CONFIRMING_PIN.set(pin.id, pin);
    REVIEW_PICK.delete(pin.id);
  }
  setReviewAll(REVIEW_ALL.filter((pin) => !where.has(pin.id)));
  drawPins();
  marks();
  const pendingConfirm = deferred(
    () => {
      sendConfirms(items);
    },
    () => undoConfirms(items, where, ticks),
  );
  const note = deferredNote(
    pendingConfirm,
    NOTICE_PLACE.ROW,
    translateTemplate('핀 {n}건 확인 · 완료로 옮겼습니다', { n: items.length }),
    {
      sec: 'review',
      prev: null,
      rec: null,
    },
  );
  const section = $('#sec-review');
  if (!section.hidden) section.scrollIntoView({ block: 'start' }); // the undo row is the section's first
  const undoButton = (note.el && note.el.querySelector('.nt-act')) as HTMLElement | null;
  if (undoButton && document.contains(undoButton)) undoButton.focus({ preventScroll: true });
  else ($('#review-toggle') as HTMLElement).focus({ preventScroll: true });
}

// The undo of [N건 확인]: each pin comes back as the latest list has it (CONFIRMING_PIN) at the place it had. While the
// section picks - also a new pick started meanwhile - their ticks join the ticks it has, and the focus goes to [N건
// 확인]; otherwise they come back as cards and the focus goes to [골라서 확인]. A pin gone from that list meanwhile is
// not brought back; one deleted elsewhere is said so.
function undoConfirms(items: { pin: Pin; at: string }[], where: Map<number, number>, ticks: Map<number, string>) {
  const back: Pin[] = [],
    lost: number[] = [];
  for (const { pin } of items) {
    const now = CONFIRMING_PIN.get(pin.id);
    CONFIRMING.delete(pin.id);
    CONFIRMING_PIN.delete(pin.id);
    if (now && !REVIEW_ALL.some((listed) => listed.id === pin.id)) back.push(now);
    else if (!now && ![OPEN_ALL, REVIEW_ALL, DONE_ALL].some((list) => list.some((listed) => listed.id === pin.id)))
      lost.push(pin.id);
  }
  back.sort((left, right) => (where.get(left.id) || 0) - (where.get(right.id) || 0));
  for (const pin of back) {
    const index = Math.min(where.get(pin.id) || 0, REVIEW_ALL.length);
    setReviewAll([...REVIEW_ALL.slice(0, index), pin, ...REVIEW_ALL.slice(index)]);
  }
  if (REVIEW_PICK) for (const pin of back) REVIEW_PICK.set(pin.id, ticks.get(pin.id) || '');
  drawPins();
  marks();
  // the undo row that had the focus is gone
  const to = (REVIEW_PICK ? $('#rv-go') : $('#review-pick')) as HTMLElement | null;
  if (to && to.getClientRects().length && !(to as HTMLButtonElement).disabled) to.focus({ preventScroll: true });
  if (lost.length)
    lineNote(
      translateTemplate('핀 {ids} 은 그사이 다른 곳에서 지워졌습니다', { ids: lost.map((id) => '#' + id).join(', ') }),
      NOTICE_KIND.WARN,
    );
}

// What the server did with one confirm. CLOSED_AGAIN: closed again since the row was ticked (409 conflict, still
// awaiting review); DONE_BY_PERSON: closed straight to done meanwhile (409 conflict, done); REOPENED: reopened (409
// open); GONE: no such pin (200 ok:false); REFUSED: any other refusal (its text); UNREACHED: no answer, or one that
// cannot be read - the only one [다시 시도] sends again.
const CONFIRM_OUTCOME = Object.freeze({
  OK: 'ok',
  CLOSED_AGAIN: 'closed-again',
  DONE_BY_PERSON: 'done',
  REOPENED: 'reopened',
  GONE: 'gone',
  REFUSED: 'refused',
  UNREACHED: 'unreached',
});
// The outcome of one confirm from its answer: status and body of an answered request (409 expected), or the error api()
// threw (an ApiError with a status for a refusal, none when the server was not reached). Pure.
function confirmOutcome(
  answer: { status: number; data: any } | null,
  err?: ApiError | null,
): { out: string; why?: string } {
  if (err)
    return err.status
      ? { out: CONFIRM_OUTCOME.REFUSED, why: errText(err.data) || 'HTTP ' + err.status }
      : { out: CONFIRM_OUTCOME.UNREACHED };
  const body = answer && answer.data;
  if (body && body.error === PIN_STATE.OPEN) return { out: CONFIRM_OUTCOME.REOPENED };
  if (body && body.error === 'conflict')
    return {
      out:
        body.pin && pinState(body.pin) !== PIN_STATE.REVIEW
          ? CONFIRM_OUTCOME.DONE_BY_PERSON
          : CONFIRM_OUTCOME.CLOSED_AGAIN,
    };
  return body && body.ok
    ? { out: CONFIRM_OUTCOME.OK }
    : body && body.ok === false
      ? { out: CONFIRM_OUTCOME.GONE }
      : { out: CONFIRM_OUTCOME.UNREACHED };
}

// How long one confirm may go unanswered before it is said as not sent (and offered to [다시 시도]); a confirm takes
// some milliseconds. Without it one request the network holds would keep every pin of the send out of the list and the
// banner unsaid.
const CONFIRM_SEND_MS = 15000;
// Sends the confirm of one pin with the done_at its row showed when ticked (keepalive, so a page being closed sends it)
// and lets the pin go back to the lists as soon as it is answered, whatever the others do: off CONFIRMING, the next
// list read shows it where the server has it. No answer within CONFIRM_SEND_MS ends the request as unreached - a retry
// of one that did reach the server answers as already done, with the same done_at. Resolves with its outcome
// (confirmOutcome).
function sendOneConfirm(pin: Pin, at: string): Promise<{ out: string; why?: string }> {
  const stop = new AbortController(),
    bound = setTimeout(() => stop.abort(), CONFIRM_SEND_MS);
  return api('/api/pins/' + pin.id + '/confirm', {
    method: 'POST',
    silent: true,
    expect: [409],
    keepalive: true,
    signal: stop.signal,
    body: at ? { done_at: at } : {},
  })
    .then(
      (answer) => confirmOutcome(answer),
      (error) => confirmOutcome(null, error as ApiError),
    )
    .then((outcome) => {
      clearTimeout(bound);
      CONFIRMING.delete(pin.id);
      CONFIRMING_PIN.delete(pin.id);
      if (outcome.out === CONFIRM_OUTCOME.OK) markMine(pin.id);
      return outcome;
    });
}
// Sends the confirms of items all at once (sendOneConfirm: every request starts in this call, so a page being closed
// sends them all) and, once each is answered or given up, says what came of them: all done is said quietly; anything
// refused is one banner on top of the review section that names each pin with why (confirmsBanner). The list is read
// again alongside, not before: a read the network holds would keep the banner and its [다시 시도] unsaid.
async function sendConfirms(items: { pin: Pin; at: string }[]) {
  const outs = await Promise.all(items.map(({ pin, at }) => sendOneConfirm(pin, at)));
  loadPins();
  const said = confirmsBanner(items.map((item, index) => ({ id: item.pin.id, ...outs[index] })));
  if (!said) {
    quietNote(translateTemplate('핀 {n}건 확인했습니다', { n: items.length }));
    return;
  }
  const again = items.filter((item, index) => outs[index].out === CONFIRM_OUTCOME.UNREACHED),
    first = items.find((item, index) => outs[index].out === CONFIRM_OUTCOME.CLOSED_AGAIN);
  const act = again.length
    ? {
        label: '다시 시도',
        tip: translate('서버에 닿지 않은 핀만 같은 결과로 다시 보냅니다'),
        wait: true,
        fn: () => retryConfirms(again),
      } // the banner stays, busy, until they are answered
    : first
      ? { label: '변경 보기', tip: TIP_TEXT.change, fn: () => showChange(first.pin.id) }
      : null;
  bannerNote(NOTICE_HOST.REVIEW, said.msg, said.kind, act, { literal: true });
}

// The banner for a send whose confirms did not all go through, or null when they did: 'N건 중 K건 확인 — ' and, per
// kind, the pins and why, joined by ' · ' (one dash: the banner shows what is before it as its title and the rest as
// its description). ERR when a pin did not reach the server, WARN when one was closed again, reopened, gone or refused,
// INFO when the rest were only done by a person meanwhile. Pure.
function confirmsBanner(outcomes: { id: number; out: string; why?: string }[]): { msg: string; kind: string } | null {
  const of = (outcome: string) => outcomes.filter((result) => result.out === outcome),
    ids = (list: { id: number }[]) => list.map((result) => '#' + result.id).join(', ');
  const ok = of(CONFIRM_OUTCOME.OK).length;
  if (ok === outcomes.length) return null;
  const refused = of(CONFIRM_OUTCOME.REFUSED),
    why = [
      [CONFIRM_OUTCOME.CLOSED_AGAIN, '{ids} 다시 닫힘(새 결과를 보고 확인)'],
      [CONFIRM_OUTCOME.REOPENED, '{ids} 그사이 다시 열림'],
      [CONFIRM_OUTCOME.DONE_BY_PERSON, '{ids} 이미 완료로 닫힘'],
      [CONFIRM_OUTCOME.GONE, '{ids} 지워짐'],
      [CONFIRM_OUTCOME.UNREACHED, '{ids} 서버에 닿지 않아 보내지 못함'],
    ]
      .map(([outcome, template]) => {
        const list = of(outcome);
        return list.length ? translateTemplate(template, { ids: ids(list) }) : '';
      })
      .filter(Boolean);
  for (const refusal of refused)
    why.push(translateTemplate('#{id} 거절됨: {why}', { id: refusal.id, why: refusal.why || '' }));
  const kind = of(CONFIRM_OUTCOME.UNREACHED).length
    ? NOTICE_KIND.ERR
    : outcomes.every((result) => result.out === CONFIRM_OUTCOME.OK || result.out === CONFIRM_OUTCOME.DONE_BY_PERSON)
      ? NOTICE_KIND.INFO
      : NOTICE_KIND.WARN;
  return {
    msg: translateTemplate('{n}건 중 {k}건 확인', { n: outcomes.length, k: ok }) + ' — ' + why.join(' · '),
    kind,
  };
}

// [다시 시도]: the pins that did not reach the server, sent again at once with the same done_at - no second undo. A pin
// being sent again, or one the lists read since show done or open, is left out; one the lists have not shown again yet
// (their read still out) is sent, and the server answers by the done_at as it would have. Resolves once they are
// answered and said, so the banner's button stays busy until then (noticeAct).
function retryConfirms(items: { pin: Pin; at: string }[]): Promise<void> {
  const moved = (id: number) => [DONE_ALL, OPEN_ALL].some((list) => list.some((pin) => pin.id === id));
  const still = items.filter((item) => !CONFIRMING.has(item.pin.id) && !moved(item.pin.id));
  if (!still.length) return Promise.resolve();
  for (const { pin } of still) {
    CONFIRMING.add(pin.id);
    CONFIRMING_PIN.set(pin.id, pin);
    if (REVIEW_PICK) REVIEW_PICK.delete(pin.id);
  }
  setReviewAll(REVIEW_ALL.filter((pin) => !CONFIRMING.has(pin.id)));
  drawPins();
  marks();
  return sendConfirms(still);
}

// A box's change (a click on it or its label, Space on it) ticks or clears it.
function tickChangedBox(event: Event) {
  const box = event.target as HTMLInputElement;
  if (box && box.type === 'checkbox' && box.closest && box.closest('#sec-review')) tickResultBox(box);
}
document.addEventListener('change', tickChangedBox);
export { REVIEW_PICK, confirmTicked, drawReviewPick, setReviewPicking, goToReviewCard };
