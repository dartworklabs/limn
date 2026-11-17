// ------------------------------------------------ A Markdown link's allowlist (docs/handbook/viewer.md §링크와 관문)
// What a link in the document may do (pure; origin is the viewer page's location.origin). Every link token comes here -
// an ordinary link, an autolink, a reference link - and this allowlist is the gate. markdown-it's own validateLink is a
// denylist (javascript:, vbscript:, file:, data: but data:image/gif|png|jpeg|webp) and lets ftp:, any custom scheme and
// those images through, so it is not relied on.
// - '#…' is an in-document heading: {open:'anchor', id}.
// - mailto: is {open:'mail', href}.
// - An absolute http(s) URL is {open:'web', href} when it names an origin other than the viewer's, no loopback host and
//   no user or password. href is the URL as parsed here, so what the browser follows is what was checked: a raw
//   'https:/api/meta' would resolve against the page to the viewer's own origin, while parsed alone it is
//   https://api/meta.
// - Anything else is {open:null}, inert text with its target in the tip: a relative path, a scheme-relative '//host',
//   another scheme, the viewer's own origin (Limn's API answers GETs with the reader's identity and some of them write
//   - a full /api/meta re-syncs pins, / records the visit), a loopback host (on the server's machine that is Limn
//   again, as the local agent).
// Both checks compare hosts by one spelling (hostKey), the destination's and the viewer's alike: 'localhost.:18920' and
// 'x.ts.net.:18020' are Limn again (its Host check reads a name with its trailing dots dropped), not another origin.
function linkHref(raw: unknown, origin: string): { open: 'web' | 'mail' | 'anchor' | null; href: string; id?: string } {
  const text = String(raw == null ? '' : raw).trim();
  if (/^#[^#]*$/.test(text)) return { open: 'anchor', href: text, id: text.slice(1) };
  if (!/^(https?|mailto):/i.test(text)) return { open: null, href: text };
  let url;
  try {
    url = new URL(text);
  } catch (error) {
    return { open: null, href: text };
  }
  if (url.protocol === 'mailto:') return { open: 'mail', href: url.href };
  if (url.username || url.password || isSameOrigin(url, origin) || isLoopbackHost(url.hostname))
    return { open: null, href: text };
  return { open: 'web', href: url.href };
}
// A host's one spelling (URL.hostname, or a Host header's name): lower case, without IPv6 brackets or trailing dots.
// The URL parser already folds case, full-width letters, percent escapes and every IPv4 spelling (127.1, 0x7f.1,
// 017700000001, 2130706433, '127.0.0.1.') into dotted form, and IPv6 into its short hex form; the trailing dot of a
// name ('localhost.', also from 'localhost%2e' or 'localhost。') it keeps. DNS reads 'name.' as 'name', and so does
// Limn's Host and Origin check (security/access.py split_host, origin_ok: name.rstrip('.')): this rule is that one.
// Pure.
function hostKey(host: string) {
  return String(host == null ? '' : host)
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.+$/, '');
}
// Whether url has the viewer page's origin (location.origin): scheme, host by one spelling (hostKey) and port (the URL
// parser leaves a default port out of both). An origin that does not parse ('null') counts as the same: every link is
// inert rather than one let through unchecked. Pure.
function isSameOrigin(url: URL, origin: string) {
  let page;
  try {
    page = new URL(origin);
  } catch (error) {
    return true;
  }
  return url.protocol === page.protocol && hostKey(url.hostname) === hostKey(page.hostname) && url.port === page.port;
}
// Whether a URL's host (URL.hostname) is this machine: localhost and *.localhost, 0.0.0.0/8 and 127.0.0.0/8, and in
// IPv6 :: and ::1 and an IPv4-mapped (::ffff:a.b.c.d) or -compatible (::a.b.c.d) address of those. Hosts are compared
// by hostKey's spelling; the URL parser has put every address in one form (hostKey). A name a hosts file maps to
// loopback (ip6-localhost, the machine's own name) is not listed: Limn's Host check admits only localhost, 127.0.0.1
// and ::1 as loopback and answers any other such name 403. Pure.
function isLoopbackHost(host: string) {
  const key = hostKey(host);
  if (key === 'localhost' || key.endsWith('.localhost')) return true;
  if (/^(127|0)\.\d+\.\d+\.\d+$/.test(key)) return true;
  const groups = ipv6Groups(key);
  if (!groups) return false;
  if (groups.slice(0, 5).every((group) => group === 0) && (groups[5] === 0xffff || groups[5] === 0)) {
    const highByte = groups[6] >> 8;
    return highByte === 127 || highByte === 0;
  } // also :: and ::1
  return false;
}
// An IPv6 address in the URL parser's form (hex groups, one '::' at most, no brackets) -> its eight 16-bit groups; null
// for anything else. Pure.
function ipv6Groups(host: string): number[] | null {
  if (!/^[0-9a-f:]+$/.test(host) || !host.includes(':')) return null;
  const parts = host.split('::');
  if (parts.length > 2) return null;
  const head = parts[0] ? parts[0].split(':') : [],
    tail = parts.length === 2 && parts[1] ? parts[1].split(':') : [];
  const fill = parts.length === 2 ? 8 - head.length - tail.length : 0;
  if (fill < 0 || (parts.length === 1 && head.length !== 8)) return null;
  const groups = [...head, ...Array(fill).fill('0'), ...tail];
  if (groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return null;
  return groups.map((group) => parseInt(group, 16));
}
export { linkHref };
