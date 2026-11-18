/** Draw a link according to the action allowed for its destination. */
import { documentTreePath } from '../documents/state.ts';
import { DOC, DOCS } from '../app/state.ts';
import type { RenderContext } from './state.ts';
import { linkAction, assetUrl } from './rules-tree.ts';
import { countedElement } from './view-elements.ts';
import { markHiddenPlain } from '../platform/hidden-chars.ts';
import { translateTemplate } from '../platform/i18n.ts';

// Every tip of an image or a link below names the hidden characters of the source text it shows again - a path or a
// '#…' decoded once, a document's name (markHiddenPlain, platform/hidden-chars.ts, ADR-0029 D5); the drawn text, an alt
// text too, is the document's. A link element for href (linkAction): a web or mail link opens in a new tab without a
// referrer or opener; an in-document '#…' goes to the heading it names (data-act md-anchor: a click or Enter, the
// global key handler asking imeKey first); another registered document is data-act md-doc (goToDocLink), the same way;
// an image of the tree opens in a new tab from GET /api/asset; anything else is inert text with its target, and why, in
// the tip.
function drawLink(href: unknown, context: RenderContext): HTMLElement {
  const target = linkAction(href, window.location.origin, documentTreePath(), DOCS);
  if (target.open === 'web' || target.open === 'mail') {
    const link = countedElement('a', context);
    link.href = target.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.dataset.tip = link.dataset.tipUrl = markHiddenPlain(target.href);
    return link;
  }
  if (target.open === 'anchor') {
    const link = countedElement('a', context);
    link.className = 'md-anchor';
    link.dataset.act = 'md-anchor';
    link.dataset.anchor = target.id || '';
    link.setAttribute('role', 'link');
    link.tabIndex = 0;
    return link;
  }
  if (target.open === 'doc') {
    const link = countedElement('a', context);
    link.className = 'md-doclink';
    link.dataset.act = 'md-doc';
    link.dataset.doc = target.key || '';
    link.dataset.anchor = target.id || '';
    link.setAttribute('role', 'link');
    link.tabIndex = 0;
    link.dataset.tip =
      translateTemplate('문서로 이동 · {name}', { name: markHiddenPlain(target.name || '') }) +
      (target.id ? ' #' + markHiddenPlain(target.id) : '');
    link.dataset.tipUrl = markHiddenPlain(target.href);
    return link;
  }
  if (target.open === 'asset') {
    const link = countedElement('a', context),
      url = assetUrl(DOC, target.href);
    link.className = 'md-asset';
    link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    const path = markHiddenPlain(target.href);
    link.dataset.tip = translateTemplate('그림을 새 탭에서 엽니다 · {path}', { path });
    link.dataset.tipUrl = path;
    return link;
  }
  // A link that does not open: a disabled link to assistive technology, reachable by Tab (the focus shows its
  // description, as a hover does), and a tap shows the description instead of picking the block (pickSelection).
  const shown = markHiddenPlain(target.href),
    inert = countedElement('span', context),
    tip =
      target.why === 'out'
        ? translateTemplate('원고 밖을 가리켜 열지 않습니다 · {href}', { href: shown })
        : target.why === 'unregistered'
          ? translateTemplate('등록된 문서가 아니라 열지 않습니다 · {href}', { href: shown })
          : translateTemplate('이 링크는 열지 않습니다 · {href}', { href: shown });
  inert.className = 'md-rel';
  inert.dataset.tip = tip;
  inert.dataset.tipUrl = shown;
  inert.tabIndex = 0;
  inert.setAttribute('role', 'link');
  inert.setAttribute('aria-disabled', 'true');
  inert.setAttribute('aria-description', tip);
  return inert;
}

export { drawLink };
