// ------------------------------------------------ The bar's pin and review counts
// The panel toggles' and the sheet bar's counts of open pins and of pins awaiting review, and the bar's words fitted to
// its width (the select button's width held while the bar is measured).
import { $, findElement, findAll } from '../platform/dom.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { LAYOUT, REVIEW_ALL, SIDE_OPEN } from '../app/state.ts';
import { LAYOUT_MODE } from '../app/rules-tables.ts';
import { setHtml, html, lucideIcon } from '../platform/markup.ts';
import { multiDoc } from '../documents/view-tabs.ts';
import { listReview } from './view-list-sections.ts';
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next
// to [핀 N] (compact) / the tool bar chip (wide). [⬚ 선택] keeps the width of its pressed face [⬚ 선택 중] wherever it
// shows its label (docs/handbook/viewer.md §모바일 레이아웃 선택 모드), so pressing it moves neither it nor its
// neighbours - on the landscape phone's top row a wider face would move the button itself under the finger. Effect:
// --sel-w on the button, measured with the pressed face drawn for a moment (in the interface language), or removed
// where the label is hidden (the portrait phone's 36px icon, a stepped-down sheet bar).
function holdSelectWidth() {
  const button = $('#btn-select'),
    label = button.querySelector('.lbl') as HTMLElement;
  button.style.removeProperty('--sel-w');
  if (!button.getClientRects().length || getComputedStyle(label).display === 'none') return;
  const pressed = button.getAttribute('aria-pressed') || 'false',
    text = label.textContent;
  button.setAttribute('aria-pressed', 'true');
  label.textContent = translate('선택 중');
  const width = button.getBoundingClientRect().width;
  button.setAttribute('aria-pressed', pressed);
  label.textContent = text;
  button.style.setProperty('--sel-w', Math.ceil(width) + 'px');
}
// The phone and tablet sheet bar's left cell steps down until [핀 N | 검토 M] and [⬚] fit it (English, three-digit
// counts, a folded cover): first [⬚ 선택] drops its label for the 36px icon the phone has (#bar1.bar-sel-icon) - the
// chip never shrinks for it; then the chip's halves pad one 4px step less and the cell's gap is 4px (#bar1.bar-snug);
// then the words '핀' and '검토' give way to a dot each - green for the open pins, purple for those awaiting review
// (#bar1.bar-tight) - so a count never stands alone. Measured each time a count or the band changes, after [⬚ 선택] has
// its width (holdSelectWidth, every band); decoration only - nothing moves.
function fitBarWords() {
  const bar = $('#bar1');
  bar.classList.remove('bar-sel-icon', 'bar-snug', 'bar-tight');
  holdSelectWidth();
  if (LAYOUT !== LAYOUT_MODE.NARROW) return;
  const leftCell = findElement(bar, '.bar-l', HTMLElement);
  const over = () => {
    // the last control's edge, not scrollWidth: the hits overflow too
    const shown = [...leftCell.children].filter((child) => child.getClientRects().length);
    return (
      shown.length > 0 &&
      shown[shown.length - 1].getBoundingClientRect().right > leftCell.getBoundingClientRect().right + 0.05
    );
  }; // past the cell, [⬚]'s hit reaches the grabber's column
  for (const step of ['bar-sel-icon', 'bar-snug', 'bar-tight']) {
    if (!over()) return;
    bar.classList.add(step);
    if (step === 'bar-sel-icon') holdSelectWidth();
  }
}
// The pill rides on both [핀 N] toggles (the tool bar's and the collapsed wide nav bar's); the phone and tablet sheet's
// bar shows the count as its own half [검토 M] (#btn-rv) instead; the chip is the open wide panel's. The pill is the
// eye icon and the count, so it never reads as part of the open count beside it ('11 1').
function updateReviewCount() {
  const count = REVIEW_ALL.length,
    chip = $('#rv-chip');
  for (const pill of findAll(document, '#btn-side .rv-n,#nav-side .rv-n', HTMLElement)) {
    pill.hidden = !count;
    setHtml(pill, html`${lucideIcon('eye')}${count}`);
    pill.setAttribute('aria-label', translateTemplate('검토 대기 {n}', { n: count }));
  }
  const reviewButton = $('#btn-rv');
  reviewButton.hidden = !count;
  findElement(reviewButton, '.rv-c', HTMLElement).textContent = String(count);
  // the sheet bar's [검토 M] half: its name starts with what it shows
  reviewButton.setAttribute('aria-label', translateTemplate('검토 {n} · 검토 대기 핀으로 가기', { n: count }));
  fitBarWords();
  const here = listReview().length;
  chip.hidden = !count || LAYOUT !== LAYOUT_MODE.WIDE || !SIDE_OPEN;
  chip.textContent =
    translateTemplate('검토 대기 {n}', { n: count }) +
    (multiDoc() && here !== count ? ' ' + translateTemplate('(이 문서 {n})', { n: here }) : '');
}
export { fitBarWords, updateReviewCount };
