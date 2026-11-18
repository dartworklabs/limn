/** Poll displayed tree images for changed ETags and update their versioned URLs. */
import { assetUrl } from './rules-tree.ts';
import { DOC } from '../app/state.ts';
import { isMarkdownDoc, isTextDoc } from '../documents/state.ts';
import { MARKDOWN_VIEW } from './state.ts';
import { isColumnShown } from './view-reading.ts';
import { $, findAll } from '../platform/dom.ts';

interface ImageCheckState {
  max: number;
  gap: number;
  last: number;
  busy: boolean;
  asked: number;
  at: Map<string, Map<string, number>>;
}
// ---------------- A tree image changed on disk (docs/handbook/viewer.md §그림)
// The page keeps the picture it decoded for an address as long as it lives (HTML's list of available images), so
// without a check an image rewritten on disk would show only after a reload: a redraw draws the same address again. On
// the light poll (documents/flow-polling.ts), the tree images that have loaded on screen or within one document area's
// height of it - the nearest IMAGE_CHECK.max of them (among as near, the one asked longest ago first: more than that
// many on screen take turns), at most once every IMAGE_CHECK.gap ms, one request at a time - are asked again: fetch(…,
// {cache:'no-cache'}) revalidates with the tag the browser holds (an unchanged image is a stat and a 304 on the server,
// AssetTags) and reads the ETag. An image whose tag moved on gets its address with &v=<the new tag> (the server reads
// only doc and path): one the page has not decoded, so the browser loads the new picture, and the box keeps the reading
// spot as for any image that loads (onImageLoad -> putSpotBack). The tag of the picture an address shows is read once
// that picture has loaded, from the answer the <img> left in the browser's cache (noteShownTag, cache:'only-if-cached':
// never the server). Without one - the cache was cleared or is off, or the entry is gone - the shown tag is unknown,
// and the check does not take the server's tag for it (that one may be of a newer file, and then no later check would
// differ): it moves the image once to the address of the tag now, so what it shows is known from then on. The version
// is kept per document and path (IMAGE_VERSIONS), so a redraw or a return to the document draws the new picture too. No
// route, no field: only GET /api/asset. at: for each document, tree path -> when a check last asked it, for the paths
// the document shows now (no other bound, so no image's turn is ever forgotten while it is on the page).
const IMAGE_CHECK: ImageCheckState = {
  max: 6,
  gap: 4000,
  last: -Infinity,
  busy: false,
  asked: 0,
  at: new Map(),
};
const IMAGE_TAGS: Map<string, string> = new Map(); // an address -> the ETag of the picture an image at it shows
const IMAGE_VERSIONS: Map<string, string> = new Map(); // doc + '\n' + tree path -> the version its address carries
const IMAGE_MAP_LIMIT = 256; // the most entries either map keeps, the oldest dropped first
// The address the tree image at path loads from now: assetUrl's, with the version a check found (IMAGE_VERSIONS).
function imageUrl(doc: string | null, path: string) {
  const version = IMAGE_VERSIONS.get(String(doc || '') + '\n' + path);
  return assetUrl(doc, path) + (version ? '&v=' + encodeURIComponent(version) : '');
}
function keepRecent(map: Map<string, string>, key: string, value: string) {
  map.delete(key);
  map.set(key, value);
  while (map.size > IMAGE_MAP_LIMIT) {
    const first = map.keys().next().value;
    if (first === undefined) break;
    map.delete(first);
  }
}
// The ETag GET url answers with (cache: the fetch's cache mode), or '' for none - a refusal, no answer, nothing cached
// for 'only-if-cached'. Its body is not read.
async function fetchImageTag(url: string, cache: RequestCache): Promise<string> {
  try {
    const response = await fetch(url, { cache, credentials: 'same-origin', mode: 'same-origin' }),
      tag = response.ok ? response.headers.get('ETag') || '' : '';
    if (response.body) response.body.cancel().catch(() => {});
    return tag;
  } catch (error) {
    return '';
  }
}
// A tree image has loaded from address url: the tag of the picture it shows, from the answer the <img> left in the
// cache, unless a check already knows it (IMAGE_TAGS). Nothing cached: it stays unknown (checkTreeImages).
async function noteShownTag(url: string) {
  if (!url || IMAGE_TAGS.has(url)) return;
  const tag = await fetchImageTag(url, 'only-if-cached');
  if (tag && !IMAGE_TAGS.has(url)) keepRecent(IMAGE_TAGS, url, tag);
}
// One check of the tree images near the document area (the header above): how many were given a new address.
async function checkTreeImages(): Promise<number> {
  const now = performance.now(),
    docKey = DOC;
  if (
    IMAGE_CHECK.busy ||
    now - IMAGE_CHECK.last < IMAGE_CHECK.gap ||
    !isMarkdownDoc() ||
    isTextDoc() ||
    MARKDOWN_VIEW.shown !== docKey ||
    !isColumnShown() ||
    document.hidden
  )
    return 0;
  const paneRect = $('#left').getBoundingClientRect(),
    near: { img: HTMLImageElement; d: number }[] = [],
    shown = new Set<string>();
  for (const img of findAll(document, '#md .md-pic img', HTMLImageElement)) {
    const path = img.parentElement && img.parentElement.dataset.path;
    if (path) shown.add(path);
    if (!img.complete || !img.naturalWidth) continue;
    const rect = img.getBoundingClientRect(),
      distance =
        rect.bottom < paneRect.top
          ? paneRect.top - rect.bottom
          : rect.top > paneRect.bottom
            ? rect.top - paneRect.bottom
            : 0;
    if (distance <= paneRect.height) near.push({ img, d: distance });
  }
  let at = IMAGE_CHECK.at.get(docKey || '');
  if (!at) {
    at = new Map();
    IMAGE_CHECK.at.set(docKey || '', at);
  }
  // an image no longer in the document has no turn to keep
  for (const path of [...at.keys()]) if (!shown.has(path)) at.delete(path);
  if (!near.length) return 0;
  // Nearest first; among images as near (every visible one is at 0) the one asked longest ago first, a never-asked one
  // before all, so past six visible images the checks take turns instead of asking the same six every time.
  const asked = (image: HTMLImageElement) =>
    at.get((image.parentElement && image.parentElement.dataset.path) || '') || 0;
  near.sort((left, right) => left.d - right.d || asked(left.img) - asked(right.img));
  IMAGE_CHECK.busy = true;
  IMAGE_CHECK.last = now;
  let count = 0,
    moved = 0;
  const seen = new Set<string>();
  try {
    for (const { img } of near) {
      const box = img.parentElement,
        path = box && box.dataset.path,
        url = img.getAttribute('src') || '';
      if (count >= IMAGE_CHECK.max) break;
      if (!path || !url || seen.has(path)) continue;
      seen.add(path);
      count++;
      at.set(path, now);
      const was = IMAGE_TAGS.get(url) || '';
      IMAGE_CHECK.asked++;
      const tag = await fetchImageTag(url, 'no-cache');
      if (docKey !== DOC || MARKDOWN_VIEW.shown !== docKey) break; // another document since: its images are its own
      if (!tag) continue;
      if (tag === was) {
        keepRecent(IMAGE_TAGS, url, was);
        continue;
      } // was '': what it shows is unknown, so it moves to the address of the tag now
      keepRecent(IMAGE_VERSIONS, docKey + '\n' + path, tag.replace(/^W\//, '').replace(/"/g, ''));
      const next = imageUrl(docKey, path);
      keepRecent(IMAGE_TAGS, next, tag);
      if (next === url) continue; // unknown, but already at that tag's address: taken as showing it
      for (const box of findAll(document, '#md .md-pic', HTMLElement))
        if (box.dataset.path === path) {
          const image = box.querySelector('img');
          if (image && image.getAttribute('src') !== next) image.src = next;
        }
      moved++;
    }
  } finally {
    IMAGE_CHECK.busy = false;
  }
  return moved;
}

export { imageUrl, noteShownTag, checkTreeImages };
