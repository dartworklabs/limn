'use strict';
// The viewer's service worker: the offline shell and document copies (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기), and
// the clicks on a notification.
//
// Online nothing changes: every request goes to the network first, and a copy of each successful same-origin GET of a
// static file, this build's PDF or its page images is kept. A copy answers only when the network fails, so an online
// visit never reads a stale screen. `/api/*` is neither kept nor answered from a copy - a stale pin list must never
// read as the current one. A navigation the network refuses is answered with the kept page: the viewer is one HTML
// string with every part inlined (viewer/assemble.py), so one entry serves every document and query.
const CACHE = 'limn-offline-v1';
const SHELL = '/';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  const names = await caches.keys();
  await Promise.all(names.filter(n => n !== CACHE).map(n => caches.delete(n)));
  await self.clients.claim();
})()));
// Whether a GET of this URL may be kept: this origin, and not an API call or the worker itself. The manuscript's PDF
// and page images are kept on purpose - that is what reading offline needs - and they already sit in the browser's
// own HTTP cache (immutable, a year) for the same build.
function cacheable(url) {
  if (url.origin !== self.location.origin) return false;
  const p = url.pathname;
  return p !== '/sw.js' && !p.startsWith('/api/');
}
// Whether this URL is a document's own file - its PDF or a page image - the only copies a page may ask to drop one by
// one ('drop'). The page and the static files serve every document and are never dropped that way.
function docFile(url) {
  return url.pathname === '/pdf' || url.pathname.startsWith('/pages/');
}
// Whether this answer is the viewer page itself. The page is one HTML string with every part inlined, and the document
// it is asked for rides in the query (?doc=), so every such answer is kept under the one shell key - a copy taken by
// [오프라인으로 받기] on `/?doc=ms` is then what a later navigation to `/` or to another document is answered with.
function isShell(request, response) {
  if (request.mode === 'navigate') return true;
  const t = (response && response.headers && response.headers.get('content-type')) || '';
  return t.indexOf('text/html') === 0;
}
// The key a response is kept under: the page is the shell whatever its query, everything else its full URL.
function cacheKey(request, url, response) {
  return isShell(request, response) ? new Request(self.location.origin + SHELL) : new Request(url.href);
}
// The copy is taken before anything is awaited: the answer goes to the page at the same moment, and a body it has begun
// reading can no longer be cloned (observed - every copy was refused this way and the cache stayed empty).
async function keep(request, url, response) {
  if (!response || !response.ok || response.type === 'opaque' || response.type === 'error') return;
  let copy; try { copy = response.clone(); } catch (_) { return; }
  try { const c = await caches.open(CACHE); await c.put(cacheKey(request, url, response), copy); } catch (_) {}
}
// How long the network is waited for when a copy could answer instead, and how long copies then answer without asking.
// A server that cannot be reached does not always refuse: on a tailnet with no internet behind it a request goes into
// the tunnel and nothing comes back for a minute and more, so a tab opened again during a flight waited that long for
// the page, and again for every file after it. A request that has a copy waits WAIT_MS for the network; when that runs
// out the copy answers, and for DOWN_MS so does every other copy, at once. A request with no copy waits as it always
// did - there is nothing else to answer it with - and any answer from the network ends the window.
const WAIT_MS = 4000, DOWN_MS = 20000;
let downUntil = 0;
// p's value, or null if it has not settled within ms. A rejection is passed on.
function within(p, ms) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => resolve(null), ms);
    p.then(v => { clearTimeout(t); resolve(v); }, err => { clearTimeout(t); reject(err); });
  });
}
self.addEventListener('fetch', e => {
  const request = e.request;
  if (request.method !== 'GET') return;
  let url; try { url = new URL(request.url); } catch (_) { return; }
  if (!cacheable(url)) return;   // the network answers for itself, failure included
  // waitUntil has to be called while the event is still being dispatched, so the worker is held awake here, before the
  // first await, and let go once the copy is written (an await and then a waitUntil throws, and the request failed).
  let written; e.waitUntil(new Promise(resolve => { written = resolve; }));
  e.respondWith((async () => {
    let copy; try { copy = await caches.match(cacheKey(request, url, null)); } catch (_) {}
    if (copy && Date.now() < downUntil) { written(); return copy; }
    const net = (async () => {
      let r = await fetch(request);
      // A conditional request this worker passed on can be answered 304, which is no body to answer the page with: the
      // kept copy is what 304 says is current. Without one the request is made again for the whole answer.
      if (r.status === 304) {
        const hit = await caches.match(cacheKey(request, url, r));
        if (hit) { written(); return hit; }
        r = await fetch(new Request(request.url, { credentials: 'same-origin' }), { cache: 'reload' });
      }
      keep(request, url, r).then(written, written);   // also when the copy has answered meanwhile: the next visit has this one
      return r;
    })();
    net.then(() => { downUntil = 0; }, () => { written(); });
    try {
      const r = copy ? await within(net, WAIT_MS) : await net;
      if (r) return r;
      downUntil = Date.now() + DOWN_MS;
      return copy;
    } catch (err) {
      if (copy) return copy;
      if (request.mode === 'navigate') {
        const shell = await caches.match(new Request(self.location.origin + SHELL));
        if (shell) return shell;
      }
      throw err;
    }
  })());
});
// What the page asks of this worker (offline.js). Each reply goes back on the port the page sent, so a page never
// waits on a worker that was replaced meanwhile.
//   {type:'keep', urls}   fetch each URL and keep it; replies {kept, failed:[url...]}
//   {type:'held', urls}   how many of these are already kept; replies {held}
//   {type:'drop', urls}   drop the copies kept under exactly these addresses - a document's PDF and page images only,
//                         never the page or a static file; replies {dropped}
//   {type:'forget'}       drop every copy; replies {}
//   {type:'down'}         whether copies are answering because the network did not (downUntil); replies {down}
self.addEventListener('message', e => {
  const d = e.data || {}, port = e.ports && e.ports[0];
  const say = v => { if (port) port.postMessage(v); };
  if (d.type === 'keep') e.waitUntil((async () => {
    const urls = Array.isArray(d.urls) ? d.urls : [], failed = [];
    let kept = 0;
    for (const u of urls) {
      let url; try { url = new URL(u, self.location.origin); } catch (_) { failed.push(u); continue; }
      if (!cacheable(url)) { failed.push(u); continue; }
      const request = new Request(url.href, { credentials: 'same-origin' });
      try {
        const r = await fetch(request, { cache: 'no-store' });
        if (!r.ok) { failed.push(u); continue; }
        await keep(request, url, r); kept++;
      } catch (_) { failed.push(u); }
    }
    say({ kept, failed });
  })());
  else if (d.type === 'held') e.waitUntil((async () => {
    const urls = Array.isArray(d.urls) ? d.urls : []; let held = 0;
    for (const u of urls) {
      let url; try { url = new URL(u, self.location.origin); } catch (_) { continue; }
      if (await caches.match(new Request(url.href))) held++;
    }
    say({ held });
  })());
  else if (d.type === 'drop') e.waitUntil((async () => {
    const urls = Array.isArray(d.urls) ? d.urls : []; let dropped = 0;
    let c; try { c = await caches.open(CACHE); } catch (_) { say({ dropped }); return; }
    for (const u of urls) {
      let url; try { url = new URL(u, self.location.origin); } catch (_) { continue; }
      if (!docFile(url)) continue;
      try { if (await c.delete(new Request(url.href))) dropped++; } catch (_) {}
    }
    say({ dropped });
  })());
  else if (d.type === 'down') say({ down: Date.now() < downUntil });
  else if (d.type === 'forget') e.waitUntil((async () => {
    try { await caches.delete(CACHE); } catch (_) {}
    say({});
  })());
});
self.addEventListener('notificationclick',e=>{e.notification.close();const d=e.notification.data||{};
  const url=new URL(d.url||'/',self.location.origin).href;
  e.waitUntil((async()=>{const cs=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    for(const c of cs){if(new URL(c.url).origin!==self.location.origin)continue;
      try{await c.focus();}catch(_){}
      c.postMessage({type:e.action==='restore'?'restore-pin':'open-pin',pin:d.pin,doc:d.doc});return;}
    if(self.clients.openWindow)await self.clients.openWindow(url+(e.action==='restore'?'&act=restore':''));})());});
