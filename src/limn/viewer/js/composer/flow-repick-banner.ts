// ------------------------------------------------ A re-place's banner, and its end
// While a pin's place is being chosen again (REPICK, composer/flow-repick.ts) the banner over the pages says so and
// compares the old place with the new one; ending the re-place takes its box and banner away.
import { $ } from '../platform/dom.ts';
import { setHtml, html } from '../platform/markup.ts';
import type { Html } from '../platform/markup.ts';
import { REPICK, setPickseq, PICKSEQ, setRepick, COMPOSE, EDITOR, LAYOUT } from '../app/state.ts';
import { isMarkdownDoc, isRegion } from '../documents/state.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { levelOf } from '../documents/rules.ts';
import { lineRange } from '../app/rules-pins.ts';
import { followRange, levelLabel, scopeLabel } from './view-levels.ts';
import { snapBox, repickElement } from '../pdf/view-figure.ts';
import { clearSelectionParts, revealBox } from '../pdf/input-selection.ts';
import { markChosenLines, shownChoice } from '../markdown/view-marks.ts';
import { setSelectMode, setSide } from '../layout/flow.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
function banner(markup: Html) {
  const bannerBox = $('#banner');
  setHtml(bannerBox, markup);
  bannerBox.hidden = false;
}
function bannerRepick(err?: string) {
  if (!REPICK) return;
  const line = err ? html`<span class="errline flush">${err}</span>` : '';
  banner(
    html`<span>${isMarkdownDoc() ? translateTemplate('핀 #{id} 의 새 위치를 문서에서 고르세요 · Esc 취소', { id: REPICK.id }) : translateTemplate('핀 #{id} 의 새 위치를 PDF에서 드래그하세요 · Esc 취소', { id: REPICK.id })}</span>${line}<span class="sp"></span><button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>`,
  );
}
// The re-place banner compares the current and the new place (lines as the composer writes them, lineRange: L9, L3-L5);
// on a figure the '새 위치' box snaps to the new element, and on the Markdown surface the candidate's lines are marked
// (shownChoice). A candidate of the other shape (a region for a line pin, lines for a region pin) is dropped and the
// banner asks for another drag: /edit never changes a pin's shape, so no request it would refuse is offered.
//
// On a LaTeX document the box then stands on the pieces the candidate's lines print as, the same way the composing
// selection's does (followRange, docs/adr/0051-pin-badge-drag-reposition.md D5): the place being confirmed is the one
// the pin will carry, not the rectangle that was dragged or dropped. A range that prints on another page is brought
// into view, since a place nobody can see is not one to confirm; a box already in view is left where it is.
function bannerCompare() {
  const repick = REPICK,
    candidate = repick && repick.cand;
  if (!repick || !candidate) return;
  const rung = levelOf(candidate, candidate.default_level),
    level = rung || candidate,
    isRegionPick = isRegion(candidate);
  if (isRegionPick !== !!repick.from.region) {
    repick.cand = null;
    bannerRepick(translate(TIP_TEXT.shape));
    return;
  }
  const where = isRegionPick
    ? translateTemplate('지금 쪽 {from} · 새 쪽 {to} 영역', { from: repick.from.page, to: candidate.page })
    : translateTemplate('지금 {from} · 새 {to}', {
        from: lineRange(repick.from.lo, repick.from.hi),
        to: lineRange(level.lo, level.hi),
      });
  const what = isRegionPick
    ? candidate.quote
      ? String(candidate.quote).slice(0, 40)
      : translate('글자 없는 영역')
    : rung && rung.label
      ? levelLabel(rung.label)
      : scopeLabel(candidate);
  const acts = html`<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button><button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>`;
  banner(
    html`<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">${where}</span><span class="dim">(${what})</span><span class="sp"></span>${acts}`,
  );
  snapBox(repick.box, repickElement(candidate));
  followRange(candidate, repick.box, bannerCompare);
  revealBox(repick.box, true);
  markChosenLines(shownChoice());
} // the Markdown surface marks the candidate's lines as its box
// Cancelling also invalidates an in-flight /api/pick; its continuation must not render a banner for the cleared
// re-place. The Markdown surface's mark goes back to the composer's selection, if any.
function cancelRepick() {
  const was = !!REPICK;
  if (was) setPickseq(PICKSEQ + 1);
  clearSelectionParts('repick');
  if (REPICK && REPICK.box) REPICK.box.remove();
  setRepick(null);
  $('#banner').hidden = true;
  if (was) markChosenLines(shownChoice());
  if (was) {
    if (!COMPOSE.current) setSelectMode(false);
    if (EDITOR.current && LAYOUT !== LAYOUT_MODE.WIDE) setSide(true);
  }
}
export { banner, bannerRepick, bannerCompare, cancelRepick };
