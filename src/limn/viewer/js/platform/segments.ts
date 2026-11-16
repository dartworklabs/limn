// ------------------------------------------------ Segmented controls
// A radio group of words (role=radio): the words on offer, its one Tab stop, and the focus kept on the same word when a
// draw replaces the words.
import { focusGivenBack } from './tooltip.ts';
/** The words of a radio group that can take the focus: neither disabled nor hidden. */
function offeredWords(group: Element) {
  return ([...group.querySelectorAll('[role=radio]')] as HTMLButtonElement[]).filter(
    (word) => !word.disabled && !word.hidden,
  );
}
/** The words of a group on offer that are laid out - the ones a key walks. */
function shownWords(group: Element) {
  return offeredWords(group).filter((word) => word.getClientRects().length);
}
/** Where the focus is among the words a group shows (shownWords), -1 when it is not on one of them. */
function segmentFocusAt(group: Element) {
  return shownWords(group).indexOf(document.activeElement as HTMLButtonElement);
}
// Three groups draw their words again: the assignee row on every pick and every change of the note
// (pins/input-mentions.ts assigneeRowHtml), the range ladder with every range (composer/view-levels.ts drawLadder - a
// pick that leaves the excerpt short of lines draws it again once more when they come back, composer/view-excerpt.ts
// excerptFetch) and [더보기]'s size on every pick and relayout (layout/flow-panel-size.ts renderSizeSegment). The word
// with the focus goes with the old words, and the focus would land on the body: an arrow's walk would end there, as
// would Enter or Space on the chosen word, and the next Tab would begin again from the page's start. So each draw notes
// where the focus was (segmentFocusAt) and gives it back to the word now at `index` - the last when there are fewer -
// as no new focus: a description shows only after a key (platform/tooltip.ts focusGivenBack). A group drawn away (no
// people left to assign) has none, and the focus stays.
function keepSegmentFocus(group: Element, index: number) {
  if (index < 0) return;
  const words = shownWords(group),
    word = words[Math.min(index, words.length - 1)];
  if (word) focusGivenBack(word);
}
/** Keep one Tab stop in a radio group: the chosen word, else the first one on offer. It reads the markup only, not the
 * layout, so a group drawn while its panel is closed holds its one stop before it shows. */
function roveSegment(group: Element | null) {
  if (!group) return;
  const words = offeredWords(group),
    on = words.find((word) => word.getAttribute('aria-checked') === 'true') || words[0];
  for (const word of words) word.tabIndex = word === on ? 0 : -1;
}
export { offeredWords, shownWords, roveSegment, segmentFocusAt, keepSegmentFocus };
