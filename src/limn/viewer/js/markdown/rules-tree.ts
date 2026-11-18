/** Resolve manuscript-relative references and classify the actions allowed for images and links. */
import { linkHref } from './rules-links.ts';

// ---------------- Relative references: the manuscript tree (ADR-0030)
// A relative reference of the document whose file is at tree path base ('docs/guide.md'), resolved in the manuscript
// tree (pure): {path, frag} - path tree-relative and normalized, frag the part after '#', both percent-decoded once
// (markdown-it encodes a link's destination) - or {out:true} for one that climbs above the tree's root or a document
// outside the tree (base null), {bad:true} for a dot-named part ('.git', '.env'), a backslash, a control character or
// an escape that does not decode; null for no relative reference at all (a scheme, '//host', '#…' alone, nothing). A
// leading '/' is the tree's root, as GitHub reads it in a repository; '?…' is dropped. The server checks again what it
// is asked (GET /api/asset).
function treePath(
  reference: unknown,
  base: string | null,
):
  | { path: string; frag: string; out?: undefined; bad?: undefined }
  | { out: true; bad?: undefined; path?: undefined }
  | { bad: true; out?: undefined; path?: undefined }
  | null {
  const text = String(reference == null ? '' : reference).trim();
  if (!text || text.startsWith('#') || text.startsWith('//') || /^[a-z][a-z0-9+.-]*:/i.test(text)) return null;
  const hash = text.indexOf('#'),
    query = text.indexOf('?'),
    end = Math.min(query < 0 ? text.length : query, hash < 0 ? text.length : hash);
  let path = text.slice(0, end),
    fragment = hash < 0 ? '' : text.slice(hash + 1);
  try {
    path = decodeURIComponent(path);
    fragment = decodeURIComponent(fragment);
  } catch (error) {
    return { bad: true };
  }
  if (!path) return null;
  if (/[\\\x00-\x1f\x7f]/.test(path)) return { bad: true };
  if (base == null) return { out: true };
  const parts = path.startsWith('/') ? [] : String(base).split('/').slice(0, -1);
  for (const part of path.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (!parts.length) return { out: true };
      parts.pop();
      continue;
    }
    if (part.startsWith('.')) return { bad: true };
    parts.push(part);
  }
  return parts.length ? { path: parts.join('/'), frag: fragment } : null;
}
// The image suffixes GET /api/asset serves (limn.documents.assets.ASSET_TYPES), and whether a tree path has one. Pure.
const IMAGE_SUFFIXES = Object.freeze(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']);
function isImagePath(path: string) {
  const match = /\.([A-Za-z0-9]+)$/.exec(path);
  return !!match && IMAGE_SUFFIXES.includes(match[1].toLowerCase());
}
// The address an image of the tree loads from: this origin's read-only GET /api/asset, built here from the checked path
// and never from the document's text. Pure.
function assetUrl(doc: string | null, path: string) {
  return '/api/asset?doc=' + encodeURIComponent(String(doc || '')) + '&path=' + encodeURIComponent(path);
}
// What an image's source loads (pure, base as treePath's): {path} for a file of the tree with an image suffix, or {why}
// - 'remote' (http(s) or '//host': the third party would learn who opened the document, and when, from where), 'data'
// (the page policy has no data: images), 'out' (above the tree's root, a dot-named part), 'type' (no image suffix),
// 'other' (any other scheme, nothing).
function imageSource(
  raw: unknown,
  base: string | null,
): { path: string; why?: undefined } | { why: 'remote' | 'data' | 'out' | 'type' | 'other'; path?: undefined } {
  const text = String(raw == null ? '' : raw).trim();
  if (/^(https?:)?\/\//i.test(text)) return { why: 'remote' };
  if (/^data:/i.test(text)) return { why: 'data' };
  const relative = treePath(text, base);
  if (!relative) return { why: 'other' };
  if (relative.out || relative.bad) return { why: 'out' };
  return isImagePath(relative.path) ? { path: relative.path } : { why: 'type' };
}
// What a link may do (pure): linkHref's answer when it opens; else, for a relative reference that stays in the tree,
// another registered document whose path it names ({open:'doc', key, id: its '#…', name}) or an image of the tree
// ({open:'asset', href: its tree path, opened in a new tab through GET /api/asset); else inert ({open:null}) with why:
// 'out' (it leaves the tree) or 'unregistered' (a file of the tree that is no document here) or '' (linkHref's own
// refusals).
function linkAction(
  raw: unknown,
  origin: string,
  base: string | null,
  docs: { key: string; path?: string; name?: string }[],
): {
  open: 'web' | 'mail' | 'anchor' | 'doc' | 'asset' | null;
  href: string;
  id?: string;
  key?: string;
  name?: string;
  why?: string;
} {
  const plain = linkHref(raw, origin);
  if (plain.open) return plain;
  const reference = treePath(raw, base);
  if (!reference) return { open: null, href: plain.href, why: '' };
  if (reference.out || reference.bad) return { open: null, href: plain.href, why: 'out' };
  const document = docs.find((entry) => String(entry.path || '') === reference.path);
  if (document)
    return {
      open: 'doc',
      href: reference.path,
      key: document.key,
      id: reference.frag,
      name: String(document.name || document.key),
    };
  if (isImagePath(reference.path)) return { open: 'asset', href: reference.path };
  return { open: null, href: plain.href, why: 'unregistered' };
}

export { linkAction, assetUrl, imageSource };
