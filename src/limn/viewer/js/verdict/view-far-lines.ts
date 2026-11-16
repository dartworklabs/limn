// ------------------------------------------------ Page verdict lines far from the view (docs/handbook/viewer.md §판정 핀)
// A line more than a view's height above or below what the PDF area shows is left for the browser to skip (.pv-far:
// content-visibility:auto, components.css): it is not laid out or painted until it comes near. Each page PDF.js draws
// for the first time adds its embedded fonts to document.fonts, and every font added makes the browser lay out all the
// text in the page again: skipped like the far cards (pins/view-list-scroll.ts lazyCards), the lines far from the view are not
// laid out at each of those. A skipped line breaks none of the line's rules, because it is never another size than the
// one it is drawn at:
// - It stands at its drawn height: --pv-h (the contain-intrinsic-block-size; the line has no padding or border, so its
//   box is its content box), or the size the browser last drew it at (content-visibility:auto keeps it:
//   contain-intrinsic-size auto), which is the same. Whatever changes what a line shows or its width fits it again
//   (fillPageLine, sizePageLines: fitPageLines), and fitPageLines lays out every line it measures - a skipped one too
//   (holdFarLines) - and keeps its height as it lets go of it (letFarLinesGo); a line that goes far keeps the height
//   the observer saw instead, where that is the later one. So a skip never moves the pages and nothing scrolls to make
//   up for one; and every line is still measured as the reading line (#doc.pv-measure).
// - Skipping contains a line (paint containment): it draws its parts on whole pixels and clips what reaches past its
//   box (a focus ring, the pressed word's hint, the reason popover, a save chip). So no line in or near the view is
//   skipped (the observer's margin), and - whatever the observer said last - neither is the reading line, which floats,
//   a line holding the focus, its reason popover or a save chip, or a line fitPageLines is measuring (components.css).
//   A script's measure inside a skipped line lays it out for the answer (the keys' Tab stops), but the innerText of
//   what is skipped is empty.
// Without IntersectionObserver no line is skipped.
import { $, $$ } from '../platform/dom.ts';
let FAR_OBSERVER = null as IntersectionObserver | null,
  FAR_HEIGHT = -1;
const FAR_WATCHED = new Set() as Set<HTMLElement>; // the lines the observer watches
// when fitPageLines last kept each line's height (performance.now())
const FITTED_AT = new WeakMap() as WeakMap<HTMLElement, number>;
// The lines fitPageLines is about to measure are laid out, skipped or not (.pv-fitting).
function holdFarLines(lines: HTMLElement[]) {
  if (typeof IntersectionObserver === 'undefined') return;
  lines.forEach((line) => line.classList.add('pv-fitting'));
}
// fitPageLines is done with lines: each keeps the height it is drawn at now (one not laid out - the changes view -
// keeps the one it had), may be skipped again, and is watched - a new line too; a line no longer in the page (another
// document, a rebuild) is no longer watched. Read before any is written.
function letFarLinesGo(lines: HTMLElement[]) {
  if (typeof IntersectionObserver === 'undefined') return;
  const heights = lines.map((line) => line.getBoundingClientRect().height),
    at = performance.now();
  const area = $('#left'),
    viewHeight = area.clientHeight;
  lines.forEach((line, index) => {
    if (heights[index]) {
      line.style.setProperty('--pv-h', heights[index] + 'px');
      FITTED_AT.set(line, at);
    }
    line.classList.remove('pv-fitting');
  });
  watchFarLines(lines, viewHeight);
}
// Watches lines (new ones; one no longer in the page is let go) with an observer whose margin is the PDF area's height,
// in px above and below its view (a percentage would be of its width): it is made again, watching every line, when that
// height changes.
function watchFarLines(lines: HTMLElement[], viewHeight: number) {
  if (!FAR_OBSERVER || FAR_HEIGHT !== viewHeight) {
    if (FAR_OBSERVER) FAR_OBSERVER.disconnect();
    FAR_WATCHED.clear();
    FAR_HEIGHT = viewHeight;
    FAR_OBSERVER = new IntersectionObserver(sortFarLines, { root: $('#left'), rootMargin: viewHeight + 'px 0px' });
    lines = $$('#doc .pgw>.pv,#doc .pv-sum');
  } // a line or a summary under a page; never the panel
  const io = FAR_OBSERVER;
  FAR_WATCHED.forEach((line) => {
    if (!line.isConnected) {
      io.unobserve(line);
      FAR_WATCHED.delete(line);
    }
  });
  lines.forEach((line) => {
    if (!FAR_WATCHED.has(line) && line.isConnected) {
      io.observe(line);
      FAR_WATCHED.add(line);
    }
  });
}
// The observer's reports: a line that came within a view's height of the PDF area's view is drawn as it is; one that
// went further is skipped, at the height the observer saw when that is later than fitPageLines's - not one not laid out
// (no height to stand at) or no longer in the page.
function sortFarLines(entries: IntersectionObserverEntry[]) {
  for (const entry of entries) {
    const line = entry.target as HTMLElement;
    if (!line.isConnected) continue;
    if (entry.isIntersecting) {
      line.classList.remove('pv-far');
      continue;
    }
    if (line.classList.contains('pv-far') || !entry.boundingClientRect.height) continue;
    if (entry.time > (FITTED_AT.get(line) || -1))
      line.style.setProperty('--pv-h', entry.boundingClientRect.height + 'px');
    line.classList.add('pv-far');
  }
}
export { FAR_OBSERVER, FAR_HEIGHT, holdFarLines, letFarLinesGo, watchFarLines };
