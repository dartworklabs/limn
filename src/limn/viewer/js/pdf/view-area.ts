// ------------------------------------------------ The PDF area's free part: what nothing covers over the pages
import { $ } from '../platform/dom.ts';
// The part of the PDF area nothing covers (the select mode's frame, #sel-mode: under the section strip, above a sheet,
// left of an overlay panel and its handle), inside #left's scrollbar and under the select mode's bar while it shows.
function popoverFreeArea() {
  const leftPane = $('#left'),
    paneRect = leftPane.getBoundingClientRect(),
    frameRect = $('#sel-mode').getBoundingClientRect(),
    bar = $('#sel-bar');
  const area = {
    left: Math.max(paneRect.left, frameRect.left),
    top: Math.max(paneRect.top, frameRect.top),
    right: Math.min(paneRect.left + leftPane.clientLeft + leftPane.clientWidth, frameRect.right),
    bottom: Math.min(paneRect.top + leftPane.clientTop + leftPane.clientHeight, frameRect.bottom),
  };
  if (bar.getClientRects().length) area.top = Math.max(area.top, bar.getBoundingClientRect().bottom);
  return area;
}
export { popoverFreeArea };
