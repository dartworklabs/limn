// ------------------------------------------------ The open document's facts
// Read from the page's shared state: the document entries and their kinds, the document a pin belongs to, the query
// that names a document, its verdict words, and the viewer role.
import { META, rendersInBrowser, showsSourceLines, DOCS, DEFAULT_DOC, DOC } from '../app/state.ts';
import { ROLE } from '../app/rules-tables.ts';
import { bannerNote } from '../platform/notices.ts';
import { NOTICE_KIND } from '../platform/tables.ts';
// Whether the document on screen is drawn here (no pages), and whether a pin belongs to such a document of this
// instance.
function isMarkdownDoc() {
  return !!META && rendersInBrowser(META.kind);
}
// Whether the document on screen is a text document (shown line for line, never parsed).
function isTextDoc() {
  return !!META && showsSourceLines(META.kind);
}
function docInfo(doc) {
  return DOCS.find((entry) => entry.key === doc) || null;
}
function pdoc(pin: Pin) {
  return (pin && pin.doc) || DEFAULT_DOC;
}
function isRegion(pin) {
  return !!pin && (pin.kind === 'region' || (!pin.file && !!pin.pdf));
}
// Appends ?doc=<key> to a document-scoped path (the server treats it as the first document if absent).
function withDocQuery(path, doc?) {
  doc = doc || DOC;
  if (!doc) return path;
  return path + (path.indexOf('?') < 0 ? '?' : '&') + 'doc=' + encodeURIComponent(doc);
}
// The verdict words of document doc (default: the one on screen): the full meta's for the document on screen (it is
// read with the document), else its /api/docs entry's; null without usable words.
function docVerdicts(doc?: string | null): DocVerdicts | null {
  const docName = doc === undefined ? DOC : doc,
    metaVerdicts = META && (!docName || META.doc === docName) ? META.verdicts : undefined,
    entry = docInfo(docName),
    verdicts = metaVerdicts || (entry && entry.verdicts);
  return verdicts && Array.isArray(verdicts.choices) && verdicts.choices.length ? verdicts : null;
}
// The name a verdict key is shown by: its word's label in the word file of document doc (default: the one on screen) -
// a card of another document under [모든 문서] names its own document's word - else the key itself (a word the file no
// longer declares stays the pin's verdict).
function verdictLabel(key: string, doc?: string | null): string {
  const verdicts = docVerdicts(doc),
    choice = verdicts && verdicts.choices.find((x) => x.key === key);
  return choice ? choice.label : key;
}
// The kind of document doc: the meta's for the document on screen, else its /api/docs entry's.
function docKindOf(doc: string): string | undefined {
  return (!DOC || doc === DOC) && META ? META.kind : (docInfo(doc) || {}).kind;
}
function isViewer() {
  return !!(typeof META !== 'undefined' && META && META.me && META.me.role === ROLE.VIEWER);
}
// A state change the viewer role cannot make (the server answers 403 anyway): say so once instead of sending it, in a
// banner over the composer while one is open, else on top of the panel (bannerHost).
function viewerBlocked() {
  if (!isViewer()) return false;
  bannerNote(undefined, '보기 권한(viewer)만 있는 계정이라 바꿀 수 없습니다', NOTICE_KIND.WARN);
  return true;
}
const REVISION_PAGE = 30; // rows of one /api/revisions page (the server's history window is 500, api.md)

export {
  isMarkdownDoc,
  isTextDoc,
  docInfo,
  pdoc,
  isRegion,
  withDocQuery,
  docVerdicts,
  verdictLabel,
  docKindOf,
  isViewer,
  viewerBlocked,
  REVISION_PAGE,
};
