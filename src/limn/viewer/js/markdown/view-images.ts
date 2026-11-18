/** Draw manuscript images and preserve the reading position as their size changes. */
import type { MarkdownToken } from './flow-parse.ts';
import { renderContextOf } from './state.ts';
import type { RenderContext } from './state.ts';
import { tokenAttribute, countedElement, drawText, drawTextLate } from './view-elements.ts';
import { imageSource } from './rules-tree.ts';
import { documentTreePath, isMarkdownDoc } from '../documents/state.ts';
import { imageUrl, noteShownTag } from './flow-image-refresh.ts';
import { DOC } from '../app/state.ts';
import { markHiddenPlain } from '../platform/hidden-chars.ts';
import { translate, translateTemplate } from '../platform/i18n.ts';
import { refreshMovedSpot, goOnToHeading, readSpot, putSpotBack } from './view-reading.ts';

// An image of the document (an inline image token): a file of the tree is an <img> from GET /api/asset, lazily loaded,
// in a box that keeps a place for it (12rem x 8rem, CSS) until its size is known - at once when an earlier draw learned
// it (IMAGE_SIZES) - and once it loads the reading spot is put back (onImageLoad), so an image above the reading line
// never moves the text being read. Anything else is the image's alt text, with why it is not loaded in the tip.
function* drawImage(
  token: MarkdownToken,
  work: { n: number },
  context: RenderContext,
): Generator<void, HTMLElement, void> {
  const raw = String(tokenAttribute(token, 'src') || ''),
    alt = String(token.content || tokenAttribute(token, 'alt') || ''),
    place = imageSource(raw, documentTreePath());
  if (place.path) {
    const box = countedElement('span', context),
      img = countedElement('img', context);
    box.className = 'md-pic';
    box.dataset.path = place.path;
    img.alt = alt;
    img.loading = 'lazy';
    img.decoding = 'async';
    img.draggable = false;
    const known = IMAGE_SIZES.get(place.path);
    if (known) {
      sizeImage(img, known.w, known.h);
      box.classList.add('md-pic-ok');
    }
    img.addEventListener('load', onImageLoad);
    img.addEventListener('error', onImageError);
    img.src = imageUrl(DOC, place.path);
    box.appendChild(img);
    return box;
  }
  const fallback = countedElement('span', context),
    shownSource = markHiddenPlain(raw);
  fallback.className = 'md-img';
  fallback.append(translate('그림') + ': ');
  // the alt text is drawn text, as the paragraph's, its marked characters in their boxes, pausing as it does
  yield* drawText(fallback, alt || raw, work, context);
  fallback.dataset.tip =
    place.why === 'remote'
      ? translateTemplate('원격 그림은 불러오지 않습니다 · {src}', { src: shownSource })
      : place.why === 'out'
        ? translateTemplate('원고 밖의 그림은 불러오지 않습니다 · {src}', { src: shownSource })
        : translateTemplate('이 그림은 불러오지 않습니다 · {src}', { src: shownSource });
  fallback.dataset.tipUrl = shownSource;
  return fallback;
}
// The natural size of each tree image this tab has loaded, by tree path: a redraw or a return to the document keeps
// their places.
const IMAGE_SIZES: Map<string, { w: number; h: number }> = new Map();
// An image has loaded: its size is kept (IMAGE_SIZES) and given to its box, and the reading spot (MARKDOWN_VIEW.spot,
// as readSpot last read it, or read again just before the change when the pane was moved since: refreshMovedSpot) is
// put back (putSpotBack) - only an image above it moves anything. During a jump to a heading (goToHeading) the spot is
// a point the scroll passes on its way: the jump goes on to its heading's new place instead (goOnToHeading,
// afterImageChange). A box drawn at a size an earlier load learned is checked too: the file may have changed since (a
// new size under the same path), and then it is resized and the spot put back as for a first load. Only a size that
// held changes nothing. The marks follow through the column's ResizeObserver (COLUMN_OBSERVER).
function onImageLoad(event: Event) {
  const img = event.target;
  if (!(img instanceof HTMLImageElement)) return;
  const box = img.parentElement;
  if (!box) return;
  void noteShownTag(img.getAttribute('src') || '');
  const width = img.naturalWidth,
    height = img.naturalHeight,
    path = box.dataset.path || '';
  if (width && height) IMAGE_SIZES.set(path, { w: width, h: height });
  else IMAGE_SIZES.delete(path);
  if (
    box.classList.contains('md-pic-ok') &&
    +(img.getAttribute('width') || 0) === width &&
    +(img.getAttribute('height') || 0) === height
  )
    return;
  const here = box.isConnected && isMarkdownDoc();
  if (here) refreshMovedSpot();
  sizeImage(img, width, height);
  box.classList.add('md-pic-ok');
  if (here) afterImageChange();
}
// After an image's box changed (onImageLoad, onImageError): the reading spot put back (putSpotBack), or - during a jump
// to a heading - the jump aimed again at its heading's new place (goOnToHeading) and the spot read where the pane
// stands, in the layout the change left. The spot's offset (top) is then the page's own after the change: an End or a
// scroll after it is not taken for the browser's cut (refreshMovedSpot) when the change shortened the document - a
// failed image's alt text in place of its box - and the next image's check reads it where it stands.
function afterImageChange() {
  if (goOnToHeading()) readSpot(true);
  else putSpotBack();
}
// Gives image img the size width x height (its natural size, from a load): its width and height attributes, and the
// aspect ratio its box keeps (CSSOM --md-pic-r, md-surface.css). With height:auto the attributes alone give way to the
// ratio of whatever picture the element shows (aspect-ratio: auto width / height), and the browser takes a new
// picture's ratio as soon as it knows its size, before the load event: a box drawn at a size an earlier load learned,
// or given a new address by a check (checkTreeImages), would change shape outside onImageLoad - a document's end cut
// back before refreshMovedSpot, which takes that cut for the layout's and undoes with it a move to that end made before
// (End). Held to width / height, the box changes only here, after the check. 0 x 0 (no natural size): none of the
// three.
function sizeImage(img: HTMLImageElement, width: number, height: number) {
  if (width && height) {
    img.width = width;
    img.height = height;
    img.style.setProperty('--md-pic-r', width + ' / ' + height);
    return;
  }
  img.removeAttribute('width');
  img.removeAttribute('height');
  img.style.removeProperty('--md-pic-r');
}
// An image the server would not give (not there, not that format, outside the tree behind a link, too large): its alt
// text, as for an image that is never loaded, saying so in the tip.
function onImageError(event: Event) {
  const img = event.target;
  if (!(img instanceof HTMLImageElement)) return;
  const box = img.parentElement;
  if (!box || !box.isConnected) return;
  const fallback = document.createElement('span'),
    path = box.dataset.path || '';
  fallback.className = 'md-img';
  fallback.append(translate('그림') + ': ');
  drawTextLate(fallback, img.alt || path, renderContextOf(box));
  const plainPath = markHiddenPlain(path);
  fallback.dataset.tip = translateTemplate('그림을 불러오지 못했습니다 · {src}', { src: plainPath });
  fallback.dataset.tipUrl = plainPath;
  const here = isMarkdownDoc();
  if (here) refreshMovedSpot(); // the spot where the pane stands, before the alt text takes the box's place
  box.replaceWith(fallback);
  if (here) afterImageChange();
}

export { drawImage };
