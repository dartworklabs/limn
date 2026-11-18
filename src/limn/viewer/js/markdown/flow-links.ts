/** Follow document links and resolve heading fragments in the intended document visit. */
import { docInfo } from '../documents/state.ts';
import { DOC, rendersInBrowser, showsSourceLines, SWITCHSEQ, COMPOSE } from '../app/state.ts';
import { switchPending, switchDoc } from '../documents/flow-switch.ts';
import { BACK } from '../layout/flow-back.ts';
import { MARKDOWN_VIEW } from './state.ts';
import { $, focusFell, focusHold } from '../platform/dom.ts';
import { imeOpen } from '../platform/composition.ts';
import { goToHeading } from './view-reading.ts';

let PENDING_HEADING: { doc: string; id: string; seq: number } | null = null;
// A link to another registered document (data-act md-doc): that document, at its '#heading' once it is drawn here
// (PENDING_HEADING, showDocumentNode), with a history entry of its own - the browser's back returns to the
// document left through the hashchange switch (documents/flow-switch.ts), and a back before the document has opened
// ends that switch (NAVGEN). While a back layer holds the entry on top (a sheet on a phone, layout/input.ts) no entry
// is added, as a tab switch adds none; the layer's entry must stay the top one. Followed again while the switch it
// started still waits for that document (a double click, switchPending), it adds no second entry and starts no second
// switch: it only names the heading to go to.
function goToDocLink(link: HTMLElement) {
  const docKey = String(link.dataset.doc || ''),
    id = String(link.dataset.anchor || ''),
    entry = docInfo(docKey);
  if (!entry) return;
  if (docKey === DOC) {
    if (id) goToSlug(id);
    return;
  }
  if (!switchPending(docKey)) {
    if (!BACK) window.history.pushState(null, '', window.location.pathname + window.location.search + '#doc=' + docKey);
    void switchDoc(docKey);
  }
  PENDING_HEADING = rendersInBrowser(entry.kind)
    ? { doc: docKey, id: showsSourceLines(entry.kind) ? '' : id, seq: SWITCHSEQ }
    : null;
} // a text document has no headings
// The document a link of another one switched to is drawn (showDocumentNode): it goes to the link's heading (goToSlug),
// and the focus, which the link took away with the document it was in, goes there too - from the document area or the
// page's body (focusFell), as a browser moves it to the fragment a link names - so a screen reader reads that heading
// and the next Tab goes on from it, not from the document's first link. A focus put anywhere else since stays; so does
// one in a composer that is open or being opened (a draft the switch brought back, typed into while the source was on
// its way), a pick on its way, or an input method's composition - focusPlace's guards; a link without a heading (a text
// document has none) leaves the focus on the document area.
function goToLinkHeading(id: string) {
  const index = id ? goToSlug(id) : -1,
    pane = $('#left');
  if (COMPOSE.current || COMPOSE.picking || !$('#composer').hidden || imeOpen()) return;
  if (document.activeElement !== pane && !focusFell()) return;
  const heading = MARKDOWN_VIEW.heads[index];
  focusHold(heading ? heading.el : pane);
}
// An in-document link to '#id': the first heading whose slug is id (or id percent-decoded), as GitHub numbers repeats
// (slug, slug-1, ...). Nothing when no heading has it.
function goToAnchor(link: HTMLElement) {
  goToSlug(String(link.dataset.anchor || ''));
}
function goToSlug(id: string): number {
  let want = id;
  try {
    want = decodeURIComponent(want);
  } catch (error) {}
  want = want.toLowerCase();
  const seen = new Map<string, number>();
  let at = -1;
  MARKDOWN_VIEW.heads.forEach((heading, index) => {
    if (at >= 0) return;
    const repeats = seen.get(heading.slug) || 0;
    seen.set(heading.slug, repeats + 1);
    if ((repeats ? heading.slug + '-' + repeats : heading.slug) === want) at = index;
  });
  if (at >= 0) goToHeading(at);
  return at;
}

/** Follow the link once its destination is drawn during the same visit. */
function finishPendingHeading() {
  const heading = PENDING_HEADING;
  if (heading && heading.doc === DOC) {
    PENDING_HEADING = null;
    if (heading.seq === SWITCHSEQ) goToLinkHeading(heading.id);
  }
}

export { goToAnchor, goToDocLink, finishPendingHeading };
