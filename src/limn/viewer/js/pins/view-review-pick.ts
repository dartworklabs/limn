// The review section's result rows and their selected revisions.
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { ORDER, SECTION_OPEN } from '../platform/prefs.ts';
import { canConfirmReview } from '../documents/view-meta.ts';
import { pinPlace } from '../pdf/view-figure.ts';
import { isMarkdownPin } from '../markdown/view.ts';
import { suggestBadge } from '../composer/flow-suggest.ts';
import { docChip, fmtText, isQuestion, locText, messageBody } from './view-card-parts.ts';
import type { Html } from '../platform/markup.ts';
import { $, findElement, focusedElement, findClosest } from '../platform/dom.ts';
import { verdictOf, lineRange } from '../app/rules-pins.ts';
import { pdoc } from '../documents/state.ts';
import { pinVerdicts } from './state-seams.ts';
import { orderPins } from './view-list-sections.ts';

// The ticked rows while the review section picks: pin id -> the done_at its row showed when it was ticked ('' for a
// close with none). null while the section shows cards.
let REVIEW_PICK: Map<number, string> | null = null;
function setReviewPick(value: Map<number, string> | null) {
  REVIEW_PICK = value;
}

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
    pinVerdicts().badge(pin),
    pinVerdicts().oldMarker(pin),
    pinVerdicts().target(pin),
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
    : html`${reply ? messageBody({ text: reply, mentions: pin.mentions }, 'rv:' + pin.id) : html`<div class="dim">${translate('설명 없음')}</div>`}\
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
  findElement(document, '#rv-all', HTMLInputElement).indeterminate = tickedCount > 0 && !all;
}

// What has the focus in the picking section, as a redraw can find it again: a row's box, or a control of the row by its
// data-act and its place among the row's controls of that act (two #N in an explanation are both 'pin-ref'), or one of
// the bar's controls by its id. null when the focus is elsewhere.
function findPickFocus(): { sel: string; i: number } | null {
  const focused = focusedElement();
  if (!focused) return null;
  const row = findClosest(focused, '.rv-row[data-id]', HTMLElement),
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
    found = all[Math.max(0, kept.i)] || all[0] || null,
    target = found instanceof HTMLElement ? found : null,
    pick = $('#review-pick');
  const to = target && !('disabled' in target && target.disabled) ? target : !pick.hidden ? pick : $('#review-toggle');
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
    if (keep) $('#review-toggle').focus({ preventScroll: true });
  } // the cards drawn next hold no focus
  if (REVIEW_PICK) {
    const listed = new Map(list.map((pin) => [pin.id, pin]));
    for (const id of [...REVIEW_PICK.keys()]) {
      const pin = listed.get(id);
      if (!pin || !showsResult(pin)) REVIEW_PICK.delete(id);
    }
  }
  // The head's toggle keeps its name, as [모든 문서] does: pressed, it is filled and leads with a check.
  const pickButton = $('#review-pick');
  pickButton.hidden = !can;
  pickButton.setAttribute('aria-pressed', String(!!REVIEW_PICK));
  setHtml(pickButton, html`${REVIEW_PICK ? lucideIcon('check') : ''}${translate('골라서 확인')}`);
  $('#sec-review').classList.toggle('rv-picking', !!REVIEW_PICK);
  drawPickBar(list);
  if (REVIEW_PICK) setHtml($('#review-pins'), html`${orderPins(list, ORDER).map(resultRow)}`);
  restorePickFocus(keep);
  return !!REVIEW_PICK;
}

export { REVIEW_PICK, drawReviewPick, showsResult, setReviewPick };
