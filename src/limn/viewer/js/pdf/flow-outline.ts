// Read the opened PDF's outline and update both the outline and page lists.
import { DOC, META, knownMeta } from '../app/state.ts';
import { translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { withDocQuery } from '../documents/state.ts';
import { VECTOR_PDF } from './state-vector.ts';
import { refreshPageLists } from './view-page-list.ts';
import {
  OUTLINE_MAX_ENTRIES,
  OUTLINE_MAX_DEPTH,
  applyPdfOutline,
  destinationFraction,
  destinationLeft,
  mergeOutlineLabels,
  type OutlineEntry,
} from './view-outline.ts';
// Sibling entries whose destinations are resolved at once (each is a round trip to the PDF.js worker).
const OUTLINE_BATCH = 100;
// How many entries that name a place (a destination) lie in item and below it. Counts without resolving anything, and
// with a stack of its own: an outline can nest deeper than the call stack.
function outlineCount(item: PdfOutlineItem) {
  let count = 0;
  const todo = [item];
  for (let node = todo.pop(); node; node = todo.pop()) {
    if (node.dest != null) count++;
    for (const child of node.items || []) todo.push(child);
  }
  return count;
}
// Reads the outline of the PDF document opened as generation gen (VECTOR_PDF.gen) into OUTLINE_ENTRIES, with the
// numbers and printed page labels the server reads for the build (mergeOutlineLabels), and draws it. A newer open drops
// it.
async function loadOutline(doc: PdfDocument, gen: number) {
  const docName = DOC,
    build = (META && META.pages_build) || '',
    // a newer open (another document or build) took over
    stale = () => gen !== VECTOR_PDF.gen || doc !== VECTOR_PDF.doc;
  let entries: OutlineEntry[] = [],
    cut = 0;
  try {
    const items = await doc.getOutline();
    // One outline item as an entry (without its depth), or null when it names no page of this PDF - or when its
    // destination cannot be resolved: one broken link leaves out that entry only, not the outline.
    async function entryOf(item: PdfOutlineItem) {
      try {
        let destination = item.dest;
        if (typeof destination === 'string') destination = await doc.getDestination(destination);
        if (!Array.isArray(destination) || destination[0] == null) return null;
        const page =
          typeof destination[0] === 'number' ? destination[0] + 1 : (await doc.getPageIndex(destination[0])) + 1;
        const pageHeight = META && META.pages && META.pages[page - 1] ? +META.pages[page - 1].pt_h : 0;
        if (!(Number.isInteger(page) && page >= 1 && page <= doc.numPages)) return null;
        return {
          title: item.title || translate('제목 없음'),
          page,
          depth: 0,
          up: -1,
          frac: destinationFraction(destination, pageHeight),
          x: destinationLeft(destination),
        };
      } catch (error) {
        return null;
      }
    }
    // up: the index in entries of the nearest entry above these rows (-1 at the top, or when every row above has no
    // entry of its own).
    async function walk(rows: PdfOutlineItem[], depth: number, up: number) {
      for (let i = 0; i < rows.length; i += OUTLINE_BATCH) {
        // Between batches: a document left behind does not go on asking the worker.
        if (stale()) return;
        if (entries.length >= OUTLINE_MAX_ENTRIES) {
          for (let j = i; j < rows.length; j++) cut += outlineCount(rows[j]);
          return;
        }
        const batch = rows.slice(i, i + OUTLINE_BATCH),
          got = await Promise.all(batch.map(entryOf));
        if (stale()) return;
        for (let j = 0; j < batch.length; j++) {
          if (entries.length >= OUTLINE_MAX_ENTRIES) {
            cut += outlineCount(batch[j]);
            continue;
          }
          const at = entries.length,
            entry = got[j];
          if (entry) entries.push(Object.assign(entry, { depth, up }));
          if (depth < OUTLINE_MAX_DEPTH) {
            await walk(batch[j].items, depth + 1, entry ? at : up);
            if (stale()) return;
          } else for (const child of batch[j].items || []) cut += outlineCount(child);
        }
      }
    }
    await walk(items || [], 0, -1);
  } catch (error) {
    entries = [];
    cut = 0;
  }
  if (stale()) return;
  // The PDF's own outline is still usable when the numbering service cannot be reached.
  if (entries.length) {
    try {
      const answer = (
        await api('GET /api/outline-labels', { query: withDocQuery('', docName), what: '목차 번호 읽기', silent: true })
      ).data;
      if (!stale() && docName === DOC && build === knownMeta().pages_build && answer.build === build)
        entries = mergeOutlineLabels(entries, answer.labels || []);
    } catch (error) {}
  }
  if (stale()) return;
  applyPdfOutline(entries, cut, docName, build);
  // A page list opened while this was read names its pages now.
  refreshPageLists();
}
export { loadOutline };
