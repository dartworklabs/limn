import { $, $$ } from '../platform/dom.ts';
import { DIFF_FORMAT, SCOPE_MODE, SCOPE_SOURCE, PIN_STATE, LAYOUT_MODE } from '../app/rules-tables.ts';
import { REVISION_VIEW } from './state.ts';
import { canConfirmReview, confirmAccessText } from '../documents/view-meta.ts';
import { docInfo } from '../documents/state.ts';
import { findAnyPin, LAYOUT, DOC } from '../app/state.ts';
import { isMe } from '../app/state-people.ts';
import { lineRange, pinState } from '../app/rules-pins.ts';
import { setHtml, html } from '../platform/markup.ts';
import { tableEntry } from '../platform/tables.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';

// The guide line (#revision-pin) for the pin the view was opened for: which commit it shows and why, what the format
// shown can say of the pin's lines (message, when given, in their place), and the review access this person lacks.
function drawPinGuide(message?: string) {
  const target = REVISION_VIEW.target,
    box = $('#revision-pin');
  if (!target) {
    box.hidden = true;
    return;
  }
  const via =
    tableEntry(
      {
        sha: translateTemplate('참조의 커밋 {tok}', { tok: target.tokOf || '' }),
        pr: translate('참조의 PR'),
        lines: translate('이 줄을 바꾼 가장 최근 커밋'),
        latest: translate('참조로 커밋을 찾지 못해 가장 최근 커밋'),
      },
      target.via,
    ) || '';
  const where = target.region
    ? translateTemplate('쪽 {page} 영역', { page: target.page })
    : target.name + ' ' + lineRange(target.lo, target.hi);
  const pinScope =
    REVISION_VIEW.format === DIFF_FORMAT.SOURCE && REVISION_VIEW.scope && REVISION_VIEW.scope.mode === SCOPE_MODE.PIN
      ? REVISION_VIEW.scope
      : null;
  const scopeText = pinScope
    ? translateTemplate('이 핀의 변경 {n}곳만 보입니다', { n: pinScope.hunks }) +
      ' (' +
      translate(pinScope.source === SCOPE_SOURCE.CHANGES ? '에이전트가 기록한 줄' : '핀 자리로 추정') +
      ') · '
    : '';
  let text = message
    ? translate(message)
    : REVISION_VIEW.format === DIFF_FORMAT.RENDERED
      ? target.mdcMsg || translate('두 판을 그려 견주는 중입니다.')
      : REVISION_VIEW.format === DIFF_FORMAT.OVERLAY
        ? translateTemplate('직전 빌드와 지금 빌드의 {page}쪽을 겹쳐 보입니다 — [이전]·[지금]으로 바꿔 보세요', {
            page: target.page,
          }) + (REVISION_VIEW.history ? ' · ' + translate('고친 줄은 [소스 diff]') : '')
        : scopeText +
          (REVISION_VIEW.format === DIFF_FORMAT.PDF
            ? translateTemplate(
                '비교 PDF에는 줄 대응이 없어 원고 {page}쪽 근처로만 옮겼습니다(삭제 문장이 끼어 쪽이 밀릴 수 있음). 정확한 줄은 [소스 diff]',
                { page: target.page },
              )
            : translate(
                target.hit === false
                  ? '이 커밋의 diff에서 핀 범위를 찾지 못했습니다 — 가장 가까운 줄을 보입니다'
                  : target.near
                    ? '핀 범위 줄 자체는 바뀌지 않았고 바로 곁(±5줄)이 바뀌었습니다 — 가장 가까운 줄을 보입니다'
                    : '강조한 줄이 핀 범위입니다',
              ));
  const pin = findAnyPin(target.id),
    access = pin && pinState(pin) === PIN_STATE.REVIEW && !canConfirmReview() ? confirmAccessText() : '';
  setHtml(
    box,
    html`<span><b>${translateTemplate('핀 #{id}', { id: target.id })}</b> · ${where}${target.ref ? ' · ' + translateTemplate('참조 {ref}', { ref: target.ref }) : ''}${via ? ' · ' + via : ''}</span><span class="rp-msg">${text}${access ? html` <span class="review-access">${access}</span>` : ''}</span>`,
  );
  box.dataset.id = String(target.id);
  box.hidden = false;
  drawPinGuideActions();
}
// The guide line's buttons (docs/handbook/viewer.md §변경 보기): [원고로] and, for a pin awaiting review that this
// person may confirm (a person with write access, not a view-only region pin), the card's [확인] - the same
// data-act="confirm" and confirmPin(), soft for the author as on the card. On the phone and tablet sheet they sit in
// the thumb row (#revision-acts) right above the status line and the tool bar; in the other bands at the guide line's
// right. Redrawn on a band change and whenever the pin lists change.
function drawPinGuideActions() {
  const target = REVISION_VIEW.target,
    row = $('#revision-acts'),
    narrow = LAYOUT === LAYOUT_MODE.NARROW;
  $$('.rp-acts').forEach((element) => element.remove());
  if (!target || $('#revision-pin').hidden) {
    row.hidden = true;
    document.body.classList.remove('rev-thumb');
    return;
  }
  const pin = findAnyPin(target.id),
    confirm = !!pin && pinState(pin) === PIN_STATE.REVIEW && !target.region && canConfirmReview();
  const backDoc = REVISION_VIEW.back && REVISION_VIEW.back !== DOC ? docInfo(REVISION_VIEW.back) : null,
    back = backDoc ? backDoc.name : null,
    actionBox = document.createElement('span');
  actionBox.className = 'rp-acts';
  const confirmButton = confirm
    ? html`<button class="btn-sm b-confirm ${isMe(pin.author) ? 'btn-soft' : 'btn-secondary'}" data-act="confirm" data-tip="${TIP_TEXT.confirm}">확인</button>`
    : '';
  setHtml(
    actionBox,
    html`<button class="btn-sm" data-act="rev-back" data-tip="${back ? translateTemplate('{name} 원고 보기로 돌아갑니다', { name: back }) : translate('원고 보기로 돌아갑니다')}">${back ? translateTemplate('{name}(으)로', { name: back }) : translate('원고로')}</button>${confirmButton}`,
  );
  (narrow ? row : $('#revision-pin')).appendChild(actionBox);
  row.dataset.id = String(target.id);
  row.hidden = !narrow;
  document.body.classList.toggle('rev-thumb', narrow);
}

export { drawPinGuide, drawPinGuideActions };
