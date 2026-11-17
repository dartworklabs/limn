// ---------------------------------- Seeing and pinning while cut off (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기)
// Before leaving the network, [오프라인으로 받기] keeps this build's page (the shell), its PDF and its page images in
// the service worker's cache and asks the server to hold that build's reverse-mapping material (POST /api/hold). While
// cut off, a drag keeps its box: pick cannot run, so the selection carries only its page, box, and the words PDF.js
// reads inside it, and [핀 저장] puts the pin in a queue (IndexedDB limnOffline) instead of on the server. The queue
// survives a reload, the tab closing and the browser restarting - only this browser sees it. Back on the network the
// queue is replayed in the order it was written: each record's own coordinates go to POST /api/pick with the build they
// were drawn on, and its answer to POST /api/pin. A record whose place cannot be found again is kept and counted, never
// dropped.
import {
  DEFAULT_DOC,
  DOC,
  DOCS,
  META,
  OPEN_ALL,
  PICKSEQ,
  rendersInBrowser,
  setSnipOpen,
  COMPOSE,
  setComposeCurrent,
  setComposeDismissedOverlap,
  setComposeIntent,
  setComposePicking,
  topPinId,
} from '../app/state.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { API_WAIT, api, setApiOut } from '../platform/api.ts';
import { NOTICES, bannerNote, endNotice, lineNote, undoNote } from '../platform/notices.ts';
import { setLastPinsRevision, offlineNow } from '../documents/flow-polling.ts';
import { WORKER_REGISTRATION, setWorkerRegistration } from '../pins/flow-notification.ts';
import { drawStatus } from '../documents/view-status.ts';
import { VECTOR_PDF } from '../pdf/flow-open.ts';
import { pageText } from '../pdf/flow.ts';
import { kindFor, wireScope } from '../composer/view-levels.ts';
import { figureFields } from '../pdf/view-figure.ts';
import { MARKDOWN_VIEW } from '../markdown/view.ts';
import { renderComposer } from '../composer/flow-pick.ts';
import { offlineUiSync } from './view.ts';
import { SELECTION_POPOVER_FIELD, isSelectionPopoverOpen } from '../composer/view-selection-popover.ts';
import { loadPins } from '../pins/flow-list.ts';
import { NOTICE_HOST, NOTICE_KIND, NOTICE_LIFE, NOTICE_PLACE, NOTICE_TOPIC } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { isMe } from '../app/state-people.ts';
import { docInfo, withDocQuery, isRegion, pdoc, viewerBlocked } from '../documents/state.ts';
import { levelOf } from '../documents/rules.ts';
import { LAST_POINTER } from '../platform/tooltip.ts';
const OFF_DB = 'limnOffline',
  OFF_STORE = 'pins',
  OFF_STATE = 'state',
  OFF_MAX = 200;
// The state key holding the pin numbers this queue wrote while a record still waits.
const OFF_WROTE = 'wrote';
// The document reads a reopened tab needs before it can draw anything, and whose last answer is therefore stored. It is
// every read the boot path makes: the document's meta and the document list, the pin list AND the dropped one (loadPins
// applies neither snapshot unless both answered - without the second the stored list would be fetched and thrown away),
// the people, the outline labels, and the source a Markdown or text document is drawn from. A light poll (light=1) is
// not among them - that one has to fail, so the status line says the connection is gone. Nothing else is ever stored,
// and no answer to a write ever is.
const OFF_READS = [
  '/api/meta',
  '/api/docs',
  '/api/pins',
  '/api/pins/dropped',
  '/api/people',
  '/api/outline-labels',
  '/api/source',
];
// idem: the server said it knows a write by its key (meta's pin_idem, offStash). boot: this visit's first reads are
// still under way (cleared by offlineBoot, which boot() calls last). staleNote: the status line's message that the
// screen was drawn from stored reads, while it stands. The rest is a kept copy keeping itself current (§Keeping a kept
// copy current below): following - a follow is running in this tab; kept - the kept record as last read (undefined
// until read, null for an instance never kept) and keptAt when; seen - what each document is on as the server last
// said; timer - the follow set to run once things stand still; fails, after - follows that failed in a row and the time
// before which none is tried again; failSaid - that failure was said this visit. holder: the server said it counts a
// build's hold per holder (meta's hold_holder); me: this browser's name among those holders, once read or made
// (offHolderId).
const OFF = {
  n: 0,
  held: 0,
  flushing: false,
  prep: false,
  saidStale: false,
  boot: true,
  idem: false,
  staleNote: null as Notice | null | undefined,
  db: null as IDBDatabase | null,
  following: false,
  kept: undefined as any,
  keptAt: 0,
  seen: {} as Record<string, { build: string; src: any; kind: any }>,
  timer: undefined as ReturnType<typeof setTimeout> | undefined,
  fails: 0,
  after: 0,
  failSaid: false,
  holder: false,
  me: '',
};
// This browser's queue, opened once per page. A browser that refuses IndexedDB (a private window) answers null, and
// every caller below falls back to saying the pin could not be kept rather than losing it quietly.
function offDb(): Promise<IDBDatabase | null> {
  if (OFF.db) return Promise.resolve(OFF.db);
  return new Promise((resolve) => {
    let request;
    try {
      request = indexedDB.open(OFF_DB, 2);
    } catch (error) {
      resolve(null);
      return;
    }
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(OFF_STORE))
        db.createObjectStore(OFF_STORE, { keyPath: 'id', autoIncrement: true });
      if (!db.objectStoreNames.contains(OFF_STATE)) db.createObjectStore(OFF_STATE, { keyPath: 'key' });
    };
    // A tab left open on an older Limn holds the previous version and would block this one's upgrade, which stops the
    // queue in both. Each tab lets go when another needs the newer version, and opens again on its next call.
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => {
        try {
          db.close();
        } catch (error) {}
        if (OFF.db === db) OFF.db = null;
      };
      OFF.db = db;
      resolve(db);
    };
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
}
/** One operation on a store as a promise; `operation` gets the store and returns its request. */
// A write is done when its transaction has committed, not when its request succeeded: a transaction can still abort
// after that (the browser out of room at the commit), and the write is rolled back. Answered at the request, a queued
// pin would read as kept, the composer would close on it, and the note would be gone. So a write answers null unless
// it committed.
function offIn<Result>(
  store: string,
  mode: 'readonly' | 'readwrite',
  operation: (store: IDBObjectStore) => IDBRequest<Result>,
): Promise<any> {
  return offDb().then(
    (db) =>
      new Promise((resolve) => {
        if (!db) {
          resolve(null);
          return;
        }
        let request, transaction;
        try {
          transaction = db.transaction(store, mode);
          request = operation(transaction.objectStore(store));
        } catch (error) {
          resolve(null);
          return;
        }
        if (mode === 'readwrite') {
          transaction.oncomplete = () => resolve(request.result);
          transaction.onabort = () => resolve(null);
          transaction.onerror = () => resolve(null);
        } else {
          request.onsuccess = () => resolve(request.result);
          request.onerror = () => resolve(null);
        }
      }),
  );
}
/** One operation on the queue. */
function offQueue<Result>(
  mode: 'readonly' | 'readwrite',
  operation: (store: IDBObjectStore) => IDBRequest<Result>,
): Promise<any> {
  return offIn(OFF_STORE, mode, operation);
}
/** Every queued record, oldest first - the order they were written is the order they are sent. */
function offAll(): Promise<any[]> {
  return offQueue('readonly', (store) => store.getAll()).then((records) => (Array.isArray(records) ? records : []));
}
// A pin queued while the connection was gone: what its send needs to place it again and write it. id is its key in the
// queue, set once it is stored.
interface QueuedPin {
  id?: number;
  v: number;
  label: string;
  doc: string | null;
  build: string;
  page: number;
  rect: { x0: number; y0: number; x1: number; y1: number } | null;
  frac: number[];
  pt: { w: number; h: number } | null;
  quote: string;
  note: string;
  kind_req: string | null;
  assignee: string | null;
  mentions: string[];
  at: string;
  held: boolean;
  why: string;
  sent: boolean;
  top?: number;
  place: { file?: string; name: string; lo?: number; hi?: number } | null;
  lines: {
    file?: string;
    name: string;
    lo: number;
    hi: number;
    text: string;
    kind: string | null;
    scope: string | null;
  } | null;
  idem: string;
}
// Adds a record to the queue; answers its key, or null when it was not kept.
function offAdd(rec: QueuedPin) {
  return offQueue('readwrite', (store) => store.add(rec));
}
// The pins this browser's queue has written, kept in the state store (OFF_WROTE, newest last, OFF_WROTE_MAX of them).
// A record whose answer never came is looked for in the pin list, and a pin that is in here was written by a different
// record of this queue - it is not this one's, however alike the two are. Without that, a record that lost its answer
// while a twin of it was written (the same place, the same note) would match the twin's pin and be deleted unwritten.
function offWrote(): Promise<number[]> {
  return offIn(OFF_STATE, 'readonly', (store) => store.get(OFF_WROTE)).then((stored) =>
    Array.isArray(stored && stored.ids) ? stored.ids : [],
  );
}
// Notes a pin this queue wrote (offWrote).
async function offWroteAdd(id: number) {
  if (typeof id !== 'number') return;
  const ids = await offWrote();
  if (ids.includes(id)) return;
  ids.push(id);
  await offIn(OFF_STATE, 'readwrite', (store) => store.put({ key: OFF_WROTE, ids }));
}
// Keeps only what some waiting record can still be confused by. A record is matched only against pins newer than the
// one it was attempted after (its `top`), so every number at or below the smallest of those tops is past being
// needed; an empty queue needs none of them. Capping the list by its length instead would drop the very number a
// record that waited through many writes still needs.
async function offWroteKeep(rest: any[]) {
  const ids = await offWrote();
  if (!ids.length) return;
  const tops = rest.map((record) => (typeof record.top === 'number' ? record.top : 0));
  const floor = tops.length ? Math.min(...tops) : Infinity;
  const kept = rest.length ? ids.filter((id) => id > floor) : [];
  if (kept.length !== ids.length)
    await offIn(OFF_STATE, 'readwrite', (store) => store.put({ key: OFF_WROTE, ids: kept }));
}
/** Whether this record is still queued - another tab of this browser may have written and dropped it. */
function offHas(id: number): Promise<boolean> {
  return offQueue('readonly', (store) => store.getKey(id)).then((key) => key !== null && key !== undefined);
}
// Writes a record back into the queue, under its own key.
function offPut(rec: QueuedPin) {
  return offQueue('readwrite', (store) => store.put(rec));
}
// Drops a record from the queue.
function offDel(id: number) {
  return offQueue('readwrite', (store) => store.delete(id));
}
// Reads the queue and lets the status line say how many wait and how many of those lost their place.
async function offlineSync() {
  const all = await offAll();
  OFF.n = all.length;
  OFF.held = all.filter((record) => record && record.held).length;
  drawStatus();
  // The queued pins on the page and in the panel (offline/view.ts).
  offlineUiSync(all);
}

// ---------------- The last answer to a document read
// A tab the phone discarded during a flight is opened again with no network. The worker answers with the page, but the
// document reads are API calls, which are never cached: without them there is no page list, no PDF build and no pin
// list, so nothing is drawn and nothing can be dragged. So the last answer to each read of OFF_READS is stored, and a
// read the network refuses is answered from that store instead of failing - said once on the status line, with when it
// was read, so a stored list is never taken for the current one.
/** The store key of a read: its path and query without the cache-busting bits. */
function offReadKey(url: string, options: { method?: string } | null | undefined): string | null {
  if (options && options.method && options.method !== 'GET') return null;
  const address = String(url);
  if (address.indexOf('light=1') >= 0) return null;
  const path = address.split('?')[0];
  if (!OFF_READS.includes(path)) return null;
  return address;
}
// Stores the answer to a document read, so a later visit with no network can be drawn from it. Only an answer the
// server gave as a success, with a body of its own: a read may hand its caller an error it expects to handle (a
// Markdown document past the drawing limit answers 413 with its reason, markdown/view.ts), and that answer is not the
// document. Stored, it would come back on the next visit as a document that opens empty.
function offStash(url: string, data: any, status: number, options?: { method?: string } | null) {
  // Every answer the network gives passes here, so this is also where the server says what it can do: a meta answer,
  // the light poll's included, carries pin_idem when a write is known by its key (api.md POST /api/pin).
  // A meta answer also says which build each document is on now, which is what keeps a kept copy current
  // (offlineFollowSeen). And hold_holder when a build's hold is counted per holder, which is what lets this browser let
  // go of its own (offFollowTidy).
  if (status === 200 && data && String(url).split('?')[0] === '/api/meta') {
    OFF.idem = data.pin_idem === true;
    OFF.holder = data.hold_holder === true;
    offlineFollowSeen(data);
  }
  const key = offReadKey(url, options || null);
  if (!key) return;
  if (!(status >= 200 && status < 300) || data === null || data === undefined) return;
  void offIn(OFF_STATE, 'readwrite', (store) => store.put({ key, data, status, at: Date.now() }));
}
/** The stored answer to a read, or null - never one the server refused. */
function offStashed(
  url: string,
  options: { method?: string } | null | undefined,
): Promise<{ data: any; status: number; at: number } | null> {
  const key = offReadKey(url, options);
  if (!key) return Promise.resolve(null);
  return offIn(OFF_STATE, 'readonly', (store) => store.get(key)).then(async (stored) => {
    if (!stored || !('data' in stored)) return null;
    // The record has to say for itself that the server answered it with a success. A record that does not say so is
    // not trusted and is dropped: a record written by another build of this viewer may hold a refusal, and read as a
    // success it opens a document that is simply empty. A read that finds nothing asks the network, which is the right
    // answer.
    if (typeof stored.status !== 'number' || stored.status < 200 || stored.status >= 300) {
      void offIn(OFF_STATE, 'readwrite', (store) => store.delete(key));
      return null;
    }
    if (key.split('?')[0] === '/api/meta') {
      const whole = offKeptMeta(await offKept(), key, stored.data);
      if (whole) return whole;
    }
    return { data: stored.data, status: stored.status, at: stored.at };
  });
}
// The meta a stored meta read is answered with when the last one read is not of the build this browser keeps whole. The
// last meta read is of whatever the server showed last - a build the screen was only starting to draw, or one a follow
// had not finished fetching - and a tab opened again with no network would be drawn from it with pages missing. The
// build recorded as kept has every file here (offKeptWith is written only then) and carries the meta it was read with.
// null when there is nothing to put in its place: an instance never kept, a document not kept, a Markdown or text
// document (it has no build), a record from before the meta was carried, or the same build. Pure.
/** @param kept the kept record @param key the read's address @param last the last meta read */
function offKeptMeta(kept: any, key: string, last: any): { data: any; status: number; at: number } | null {
  if (!kept || !kept.docs || !last || typeof last !== 'object') return null;
  const query = key.indexOf('?') >= 0 ? key.slice(key.indexOf('?') + 1) : '';
  const docName = last.doc || new URLSearchParams(query).get('doc') || '',
    keptDoc = kept.docs[docName];
  if (
    !keptDoc ||
    !keptDoc.build ||
    !keptDoc.meta ||
    keptDoc.meta.pages_build !== keptDoc.build ||
    last.pages_build === keptDoc.build
  )
    return null;
  return { data: keptDoc.meta, status: 200, at: keptDoc.seen || 0 };
}
// When a read the network refused may be answered from the store: while this visit is still making its first reads
// (a tab opened again with no network has nothing else to draw from), or while the connection is known to be gone
// (offlineNow - switching documents during a flight). Never for a read that fails while the viewer is connected: that
// failure is said and asked again (a failed pin read's '핀 읽기 실패 [다시 시도]', a Markdown source's note and its
// re-ask on the next poll). Answered from the store there, it would read as a success - the list would stay stale and
// nothing would ask again.
function offlineMayServe() {
  return OFF.boot || offlineNow();
}
// Says once per visit that what is on screen was read before the connection went, and when. The pins and the pages
// are that moment's, not this one's: the status line already says the connection is gone, and this says how old the
// screen is.
function offStaleSaid(at: number) {
  if (OFF.saidStale) return;
  OFF.saidStale = true;
  const readAt = new Date(at),
    two = (value: number) => String(value).padStart(2, '0');
  OFF.staleNote = lineNote(
    translateTemplate('연결이 없어 {time}에 읽어 둔 화면입니다 — 핀을 찍으면 쌓였다가 연결되면 반영됩니다', {
      time: two(readAt.getHours()) + ':' + two(readAt.getMinutes()),
    }),
    NOTICE_KIND.WARN,
    null,
    { literal: true },
  );
}
// The server answered again after a screen drawn from stored reads: its message goes, and the pin list is read again
// whatever revision it was last read at - the stored list is that old moment's, and the light poll compares revisions,
// so a stored list whose revision happens to equal the server's would otherwise stand unread. Called for every answer
// the network gives (api); nothing happens unless a stored screen was said.
function offlineBack() {
  if (!OFF.saidStale) return;
  OFF.saidStale = false;
  if (OFF.staleNote) {
    endNotice(OFF.staleNote, false);
    OFF.staleNote = null;
  }
  setLastPinsRevision(null);
}

// ---------------- The service worker
// The worker is registered for every visit, not only where notifications are allowed (pins/flow-notification.ts
// asks it for those): it is what answers when the network does not. A browser without one still works online, and says
// so when asked to prepare.
async function offlineWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null;
  try {
    return (
      WORKER_REGISTRATION || setWorkerRegistration(await navigator.serviceWorker.register('/sw.js', { scope: '/' }))
    );
  } catch (error) {
    return null;
  }
}
// One question to the worker, answered on its own port so a replaced worker never leaves this waiting. The wait fits
// the question: a count comes back at once (3s), files have to be fetched first - over a tailnet from a phone that is
// not 3s, and a wait that short would call a keep that is still going a failure.
async function offlineAsk(message: { type: string; urls?: string[] }, ms?: number): Promise<any> {
  const reg = await offlineWorker();
  if (!reg) return null;
  let worker = navigator.serviceWorker.controller;
  if (!worker) {
    try {
      await navigator.serviceWorker.ready;
    } catch (error) {}
    worker = navigator.serviceWorker.controller;
  }
  if (!worker) return null;
  return new Promise((resolve) => {
    const channel = new MessageChannel(),
      timer = setTimeout(() => resolve(null), ms || 3000);
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve(event.data);
    };
    try {
      worker.postMessage(message, [channel.port2]);
    } catch (error) {
      clearTimeout(timer);
      resolve(null);
    }
  });
}
// Asks the worker that controls this page whether it is answering from its copies because the network did not (sw.js
// 'down'), before the visit's first read: this page was then one of those answers, and its reads need not each wait out
// a request (platform/api.ts API_OUT). Only a worker already in control is asked, and for a moment - a first visit, or
// a browser with no worker, reads as usual.
async function offlineAskDown() {
  const worker = 'serviceWorker' in navigator ? navigator.serviceWorker.controller : null;
  if (!worker) return;
  const answer = await new Promise<{ down?: unknown } | null>((resolve) => {
    const channel = new MessageChannel(),
      timer = setTimeout(() => resolve(null), 300);
    channel.port1.onmessage = (event) => {
      clearTimeout(timer);
      resolve(event.data);
    };
    try {
      worker.postMessage({ type: 'down' }, [channel.port2]);
    } catch (error) {
      clearTimeout(timer);
      resolve(null);
    }
  });
  if (answer && answer.down === true) setApiOut(true);
}
// What the page needs to open with no network: the page itself and everything it has already loaded from this origin
// (its script /viewer.js, the vendored PDF.js, fonts, KaTeX and the Markdown worker). Nothing is hardcoded, so a
// change to the vendored files follows along.
function offlineUrls(): string[] {
  const out = new Set([location.pathname + location.search]);
  try {
    performance.getEntriesByType('resource').forEach((entry) => {
      const address = new URL(entry.name, location.href);
      if (address.origin === location.origin && !address.pathname.startsWith('/api/') && address.pathname !== '/sw.js')
        out.add(address.href);
    });
  } catch (error) {}
  return Array.from(out);
}
// The PDF and the page images of a document as its meta names them - the very addresses the viewer asks for when that
// document is on screen (pdf/flow-open.ts openVectorDocument, pdf/view-pages.ts pageSrc), since a copy is found again
// by its address. Pure.
function offlineDocFiles(docName: string | null, meta: any): string[] {
  const build = (meta && meta.pages_build) || '',
    out = [] as string[];
  if (!build) return out;
  out.push(
    withDocQuery('/pdf?build=' + encodeURIComponent(build) + '&v=' + encodeURIComponent(meta.built_at || ''), docName),
  );
  (meta.pages || []).forEach((page: any) =>
    out.push(withDocQuery('/pages/' + encodeURIComponent(build) + '/' + encodeURIComponent(page.name), docName)),
  );
  return out;
}
// Files asked of the worker at a time, and how long one such ask may take.
const OFF_KEEP_CHUNK = 12,
  OFF_KEEP_MS = 180000;
// [오프라인으로 받기]: keeps every document of this instance for reading with no network - a person on a flight moves
// between them - and asks the server to hold each build its pins will point at. Each document's reads go through
// api(), which stores their answers (offStash): its meta, its outline labels, and for a Markdown or text document the
// source it is drawn from. The files go to the worker a few at a time, so the line can say how far it is. The hold is
// what lets the queue land on exact lines later; a server without that route (an older Limn) is not a failure - the
// pins are kept all the same, and said to need their place chosen again if the build is gone by then. Pressing it once
// also turns on following for this instance (offlineFollow): each document kept whole is recorded, and from then on
// its copy keeps itself current while connected.
async function offlinePrepare() {
  if (OFF.prep) return;
  OFF.prep = true;
  const note = lineNote('오프라인용으로 받는 중…', NOTICE_KIND.INFO, null, { life: NOTICE_LIFE.CLICK });
  const say = (title: string) => {
    if (note && NOTICES.has(note.n)) {
      note.title = title;
      note.desc = '';
      drawStatus();
    }
  };
  try {
    const reg = await offlineWorker();
    if (!reg) {
      if (note) endNotice(note, false);
      lineNote('이 브라우저는 오프라인 보기를 지원하지 않습니다', NOTICE_KIND.WARN, null, {});
      return;
    }
    // The person chose this instance: it follows from now on.
    await offKeptSet((record) => record || { key: OFF_KEPT, docs: {}, old: [] });
    const urls = new Set(offlineUrls()),
      keys = DOCS.length ? DOCS.map((docEntry) => docEntry.key) : [DOC];
    // Each document's entry for the kept record, once its files are known whole.
    const got = [] as { k: string; entry: any }[];
    let docs = 0,
      held = 0,
      lost = 0;
    for (const docName of keys) {
      let meta = null as any;
      const seen = Date.now();
      try {
        meta = (await api(withDocQuery('/api/meta', docName), { what: '화면 정보 읽기', silent: true })).data;
      } catch (error) {
        lost++;
        continue;
      }
      docs++;
      const info = docName ? docInfo(docName) : null,
        kind = (meta && meta.kind) || (info && info.kind),
        key = (meta && meta.doc) || docName || '';
      if (rendersInBrowser(kind)) {
        try {
          await api(withDocQuery('/api/source', docName), { what: '원문 읽기', silent: true, expect: [413] });
          got.push({ k: key, entry: { build: '', files: [], at: 0, src: (meta && meta.src_mtime) ?? null, seen } });
        } catch (error) {
          lost++;
        }
        continue;
      }
      const files = offlineDocFiles(docName, meta);
      files.forEach((address) => urls.add(address));
      try {
        await api(withDocQuery('/api/outline-labels', docName), { what: '목차 번호 읽기', silent: true });
      } catch (error) {}
      if (meta && meta.pages_build) {
        // Held only when the server says until when. A 404 is handed back, not thrown (expect), and it is not a hold:
        // an older Limn has no such route, and a build that left while this ran answers pdf_build_gone.
        const hold = await offHold(docName, meta.pages_build, 7);
        if (hold && hold.held) held++;
        got.push({ k: key, entry: { build: meta.pages_build, files, at: hold ? hold.at : 0, seen, meta: meta } });
      }
    }
    // The lists every document shares, as they stand now.
    for (const address of ['/api/docs', '/api/pins?all=1', '/api/pins/dropped', '/api/people']) {
      try {
        await api(address, { what: '핀 읽기', silent: true });
      } catch (error) {
        lost++;
      }
    }
    const all = Array.from(urls),
      missed = new Set();
    let kept = 0,
      failed = 0;
    for (let i = 0; i < all.length; i += OFF_KEEP_CHUNK) {
      say(translateTemplate('오프라인용으로 받는 중… {n}/{m}', { n: i, m: all.length }));
      const answer = await offlineAsk({ type: 'keep', urls: all.slice(i, i + OFF_KEEP_CHUNK) }, OFF_KEEP_MS);
      if (!answer) {
        if (note) endNotice(note, false);
        lineNote(
          '오프라인용 받기를 마치지 못했습니다 — 다시 시도하세요',
          NOTICE_KIND.ERR,
          {
            label: '다시 시도',
            fn: () => {
              OFF.prep = false;
              offlinePrepare();
            },
          },
          {},
        );
        return;
      }
      kept += answer.kept || 0;
      failed += (answer.failed || []).length;
      (answer.failed || []).forEach((address: string) => missed.add(address));
    }
    // A document is recorded as kept only with every one of its files: a build half kept is not one to follow from.
    // What it kept before then goes to the old builds, which the next follow drops unless a queued pin was drawn on it.
    // The meta answers above have already set a follow going (offStash), which drops those old builds.
    for (const keptDoc of got)
      if (keptDoc.k && !keptDoc.entry.files.some((address: string) => missed.has(address)))
        await offKeptSet((record) => offKeptWith(record, keptDoc.k, keptDoc.entry));
    if (note) endNotice(note, false);
    const bad = failed + lost;
    lineNote(
      bad
        ? translateTemplate('오프라인용 {n}개 중 {m}개를 받지 못했습니다 — 연결을 확인하고 다시 받으세요', {
            n: all.length + lost,
            m: bad,
          })
        : held
          ? translateTemplate('오프라인 준비됨 · 문서 {d}개 · 파일 {n}개 · PDF의 자리를 7일간 지킵니다', {
              d: docs,
              n: kept,
            })
          : translateTemplate('오프라인 준비됨 · 문서 {d}개 · 파일 {n}개', { d: docs, n: kept }),
      bad ? NOTICE_KIND.WARN : NOTICE_KIND.OK,
      null,
      { life: bad ? NOTICE_LIFE.CLICK : NOTICE_LIFE.TIMER },
    );
  } finally {
    OFF.prep = false;
  }
}

// ---------------- Keeping a kept copy current
// [오프라인으로 받기] pressed once turns this on for the instance - this origin, whose store is this browser's: the
// state store's OFF_KEPT record says so, with what each document keeps (docs: its build, that build's file addresses,
// when its hold was last answered and when that build was asked for; a Markdown or text document's source time instead)
// and the old builds not dropped yet (old). While connected, every meta answer says which build each document is on now
// (offStash -> offlineFollowSeen). A document whose copy is behind is followed: its reads are stored, its new files
// fetched whole, its new build held - the same as pressing does, for one document, quietly - and only then is it
// recorded and the old build's copies dropped from this device. Of its hold on the server this browser lets go only its
// own share, where the server counts a hold per holder (meta's hold_holder): another device - the same person's tablet,
// cut off - may have pins queued on that build which this one cannot see, and its share keeps the build. On a server
// with one hold per build nothing is let go; the hold simply is not asked again, and lapses in 7 days. An old build a
// queued pin of this browser was drawn on stays, copies and all, and its hold goes on being asked (offFree): that pin
// lands by that build. Holds last 7 days and are asked again once a day while the instance is used. Nothing is said on
// success; failing again and again is said once. An instance never kept fetches nothing - what stays on a device is
// what its person chose (ADR-0040 D7). OFF_RENEW_MS: a hold asked again after this long. OFF_SETTLE_MS: a change has to
// stand this long before it is followed, so a run of builds is followed once, to the last. OFF_RETRY_*: the wait after
// a failed follow, doubling to the cap. OFF_SAY_AFTER: failures in a row before it is said. OFF_LOCK: the name tabs of
// this browser follow under, one at a time.
const OFF_KEPT = 'kept',
  OFF_HOLDER = 'holder',
  OFF_RENEW_MS = 86400000,
  OFF_SETTLE_MS = 10000,
  OFF_RETRY_MS = 30000,
  OFF_RETRY_MAX = 1800000,
  OFF_SAY_AFTER = 3,
  OFF_LOCK = 'limn-offline-follow';
/** The kept record, or null for an instance never kept. */
function offKept(): Promise<any> {
  return offIn(OFF_STATE, 'readonly', (store) => store.get(OFF_KEPT)).then((record) =>
    record && record.docs ? record : null,
  );
}
// Changes the kept record in one transaction, read and written together: two tabs of this browser share it, and a
// change made between another tab's read and its write would be lost. change gets the record (or null) and answers
// the new one, or null to leave it. Answers what was written, or null.
function offKeptUpdate(change: (record: any) => any): Promise<any> {
  return offDb().then(
    (db) =>
      new Promise((resolve) => {
        if (!db) {
          resolve(null);
          return;
        }
        let out = null as any;
        try {
          const transaction = db.transaction(OFF_STATE, 'readwrite'),
            store = transaction.objectStore(OFF_STATE),
            request = store.get(OFF_KEPT);
          request.onsuccess = () => {
            try {
              out = change(request.result && request.result.docs ? request.result : null);
              if (out) store.put(out);
            } catch (error) {
              out = null;
            }
          };
          transaction.oncomplete = () => resolve(out);
          transaction.onerror = () => resolve(null);
          transaction.onabort = () => resolve(null);
        } catch (error) {
          resolve(null);
        }
      }),
  );
}
/** offKeptUpdate, and this tab's copy of the record follows. */
async function offKeptSet(change: (record: any) => any): Promise<any> {
  const written = await offKeptUpdate(change);
  if (written) {
    OFF.kept = written;
    offKeptShow();
  }
  return written;
}
// [더보기]'s [오프라인으로 받기] says whether this instance is kept: '받아 둠' at the row's end once it is. Following
// is silent, so this is the one place a person can see that it is on - and that an instance was never kept.
function offKeptShow() {
  const keptMark = document.getElementById('m-offline-n');
  if (!keptMark) return;
  keptMark.hidden = !OFF.kept;
  keptMark.textContent = OFF.kept ? translate('받아 둠') : '';
}
// What a meta answer says each document is on: the document it answers for and, with several documents, each one's
// summary - the page build, the source time, the kind. Pure.
function offSeenIn(meta: any): Record<string, { build: string; src: any; kind: any }> {
  const out = {} as Record<string, { build: string; src: any; kind: any }>;
  if (!meta || typeof meta !== 'object') return out;
  const put = (summary: any, key: any) => {
    if (typeof key === 'string' && key)
      out[key] = { build: summary.pages_build || '', src: summary.src_mtime ?? null, kind: summary.kind || null };
  };
  put(meta, meta.doc);
  (Array.isArray(meta.docs) ? meta.docs : []).forEach((summary: any) => {
    if (summary && typeof summary === 'object') put(summary, summary.key);
  });
  return out;
}
// The documents whose kept copy is behind what the server shows: a page document on another build (or one not kept yet
// - a document added to a kept instance is part of it), a Markdown or text document whose source changed. A document
// with no build has nothing to keep; one the server no longer lists is not looked at. Pure.
function offBehind(kept: any, seen: Record<string, { build: string; src: any; kind: any }>): string[] {
  const docs = (kept && kept.docs) || {};
  return Object.keys(seen).filter((docName) => {
    const shown = seen[docName],
      keptDoc = docs[docName];
    if (rendersInBrowser(shown.kind)) return !keptDoc || keptDoc.src !== shown.src;
    return !!shown.build && (!keptDoc || keptDoc.build !== shown.build);
  });
}
// The old builds no queued pin was drawn on: those whose copies may be dropped and whose hold need not be asked again.
// A record names its document and the build it was drawn on; a record with no document is taken to be drawn on that
// build in any document - keeping a build too long costs space, dropping it loses the pin's place. Pure.
function offFree(old: any[], queue: any[]): any[] {
  const drawn = (queue || []).filter((record) => record && record.build);
  return (old || []).filter(
    (oldBuild) =>
      !drawn.some((record) => record.build === oldBuild.build && (!record.doc || record.doc === oldBuild.doc)),
  );
}
// The holds to ask again: of each document's build and each old build still kept, those last answered OFF_RENEW_MS
// ago or never. Pure.
function offRenewDue(kept: any, now: number): { doc: string; build: string }[] {
  const out = [] as { doc: string; build: string }[];
  if (!kept) return out;
  const due = (entry: any) => !!entry && !!entry.build && !entry.unheld && !(now - (entry.at || 0) < OFF_RENEW_MS);
  Object.keys(kept.docs || {}).forEach((docName) => {
    if (due(kept.docs[docName])) out.push({ doc: docName, build: kept.docs[docName].build });
  });
  (kept.old || []).forEach((oldBuild: any) => {
    if (due(oldBuild)) out.push({ doc: oldBuild.doc, build: oldBuild.build });
  });
  return out;
}
// The kept record once a document keeps an entry. The newer reading wins: entry.seen is when the server was asked for
// its build, and a follow and a press - or two tabs of a browser without Web Locks - may each bring one; asked later,
// it saw the server later. The losing build, if it is a different one, goes to the old builds with its files, so
// whatever a tab fetched is accounted for and dropped in turn - never the build that won, whichever tab fetched it.
// (Asked in the same millisecond, the later write wins; the next follow sees the server's build and puts it right.) A
// build kept again leaves the old ones. Pure.
function offKeptWith(kept: any, docName: string, entry: any): any {
  const out = { key: OFF_KEPT, docs: { ...((kept && kept.docs) || {}) }, old: ((kept && kept.old) || []).slice() };
  const current = out.docs[docName] || null;
  const toOld = (retired: any) => {
    if (
      !retired ||
      !retired.build ||
      out.old.some((oldBuild: any) => oldBuild.doc === docName && oldBuild.build === retired.build)
    )
      return;
    out.old.push({ doc: docName, build: retired.build, files: retired.files || [], at: retired.at || 0 });
  };
  if (current && (current.seen || 0) > (entry.seen || 0)) {
    if (current.build !== entry.build) toOld(entry);
    return out;
  }
  if (current && current.build !== entry.build) toOld(current);
  out.docs[docName] = entry;
  out.old = out.old.filter((oldBuild: any) => !(oldBuild.doc === docName && oldBuild.build === entry.build));
  return out;
}
// The kept record once a follow of a document to a build stopped before that build was kept: the files it asked for
// are noted with the old builds, never held by this browser (unheld - its hold is not asked again), so they are dropped
// in turn and do not stay on the device unaccounted for. null when there is nothing to note - the build is what the
// document keeps. Pure.
function offKeptPart(kept: any, docName: string, build: string, files: string[]): any {
  if (!kept || (kept.docs && kept.docs[docName] && kept.docs[docName].build === build)) return null;
  const old = (kept.old || []).slice(),
    oldIndex = old.findIndex((oldBuild: any) => oldBuild.doc === docName && oldBuild.build === build);
  if (oldIndex >= 0)
    old[oldIndex] = { ...old[oldIndex], files: Array.from(new Set([...(old[oldIndex].files || []), ...files])) };
  else old.push({ doc: docName, build: build, files: files.slice(), at: 0, unheld: true });
  return { ...kept, old };
}
// The kept record with the hold of a document's build answered at `at`. Pure.
function offKeptHeld(kept: any, docName: string, build: string, at: number): any {
  if (!kept) return null;
  const out = {
    ...kept,
    docs: { ...(kept.docs || {}) },
    old: (kept.old || []).map((oldBuild: any) =>
      oldBuild.doc === docName && oldBuild.build === build ? { ...oldBuild, at } : oldBuild,
    ),
  };
  if (out.docs[docName] && out.docs[docName].build === build) out.docs[docName] = { ...out.docs[docName], at };
  return out;
}
// Asks the server to hold a document's build for days (0 lets it go) -> {at, held}: when it answered, and whether it
// holds the build. A refusal is an answer with nothing held: an older Limn without the route or a build already gone
// (404), a role that may not hold (403). null when there was no answer.
async function offHold(
  docName: string | null,
  build: string,
  days: number,
): Promise<{ at: number; held: boolean } | null> {
  const holder = (await offHolderId()) || undefined;
  try {
    const answer = await api(withDocQuery('/api/hold', docName), {
      method: 'POST',
      body: { build: build, days, holder },
      what: '빌드 보류',
      silent: true,
      wait: API_WAIT.SEND,
    });
    return { at: Date.now(), held: answer.status === 200 && !!answer.data && !!answer.data.until };
  } catch (error) {
    const apiError = error as ApiError,
      status = (apiError && apiError.status) || 0;
    return status >= 400 && status < 500 ? { at: Date.now(), held: false } : null;
  }
}
// This browser's name among the holders of a build: made once and kept in the state store, so every tab and every
// visit of this browser holds and lets go as one holder, and another device - which has its own - is never let go by
// this one. Read and made in one transaction: two tabs starting together must end with one name. '' when the store
// is refused; a hold is then asked with no name, as an older viewer asked it.
function offHolderId(): Promise<string> {
  if (OFF.me) return Promise.resolve(OFF.me);
  return offDb().then(
    (db) =>
      new Promise((resolve) => {
        if (!db) {
          resolve('');
          return;
        }
        let id = '';
        try {
          const transaction = db.transaction(OFF_STATE, 'readwrite'),
            store = transaction.objectStore(OFF_STATE),
            request = store.get(OFF_HOLDER);
          request.onsuccess = () => {
            const stored = request.result;
            id = stored && typeof stored.id === 'string' && /^[A-Za-z0-9_-]{16,64}$/.test(stored.id) ? stored.id : '';
            if (!id) {
              id = offlineKey();
              store.put({ key: OFF_HOLDER, id });
            }
          };
          transaction.oncomplete = () => {
            OFF.me = id;
            resolve(id);
          };
          transaction.onerror = () => resolve('');
          transaction.onabort = () => resolve('');
        } catch (error) {
          resolve('');
        }
      }),
  );
}
// A meta answer seen: what each document is on is noted, and a follow is set going when one is due.
function offlineFollowSeen(meta: any) {
  const now = offSeenIn(meta);
  let moved = false;
  Object.keys(now).forEach((docName) => {
    const was = OFF.seen[docName],
      current = now[docName];
    if (!was || was.build !== current.build || was.src !== current.src) moved = true;
    OFF.seen[docName] = current;
  });
  offFollowCheck(moved);
}
// Sets a follow going when the kept copy is behind, a hold is due, or old builds wait to go with no queued pin left.
// Nothing at all for an instance never kept, and neither a request nor a store read when nothing is due - this runs on
// every light poll. moved: something new was seen, which restarts the wait for things to stand still and is a new
// chance after a failure. A sighting with nothing new leaves a follow already set as it is.
function offFollowCheck(moved: boolean) {
  const kept = OFF.kept;
  // Not read yet: offlineBoot checks once it is.
  if (kept === undefined) return;
  // Another tab of this browser may turn following on; this one reads the record again now and then (no request).
  if (kept === null) {
    if (Date.now() - OFF.keptAt >= 60000) {
      OFF.keptAt = Date.now();
      void offKept().then((record) => {
        if (record) {
          OFF.kept = record;
          offKeptShow();
          offFollowCheck(true);
        }
      });
    }
    return;
  }
  const due =
    offBehind(kept, OFF.seen).length > 0 ||
    offRenewDue(kept, Date.now()).length > 0 ||
    ((kept.old || []).length > 0 && OFF.n === 0);
  if (!due) return;
  if (moved) OFF.after = 0;
  if (Date.now() < OFF.after) return;
  if (OFF.timer !== undefined && !moved) return;
  clearTimeout(OFF.timer);
  OFF.timer = setTimeout(() => {
    OFF.timer = undefined;
    void offlineFollow();
  }, OFF_SETTLE_MS);
}
// Follows the kept copy to what the server shows. One at a time in this tab - the flag is taken before anything is
// awaited, as offlineFlush takes its own, since one meta answer can set it going from several places - and one at a
// time among this browser's tabs, which share the cache and the store (a Web Lock; a browser without one relies on
// offKeptWith, which lets two tabs' follows end as one would). Not while cut off or while a pressed keep runs: each
// document is begun only while neither is so, and nothing is dropped then.
async function offlineFollow() {
  if (OFF.following) return;
  OFF.following = true;
  try {
    const locks = typeof navigator !== 'undefined' && navigator.locks;
    if (locks && typeof locks.request === 'function')
      await locks.request(OFF_LOCK, { ifAvailable: true }, (lock) => (lock ? offFollowRun() : undefined));
    else await offFollowRun();
  } catch (error) {
  } finally {
    OFF.following = false;
  }
}
// One follow: each document whose copy is behind, then the old builds and the holds (offFollowTidy).
async function offFollowRun() {
  let ok = true;
  const kept = await offKept();
  OFF.kept = kept;
  OFF.keptAt = Date.now();
  if (!kept) return;
  for (const docName of offBehind(kept, OFF.seen)) {
    if (OFF.prep || offlineNow()) break;
    if (!(await offFollowDoc(docName))) ok = false;
  }
  if (!OFF.prep && !offlineNow() && !(await offFollowTidy())) ok = false;
  offFollowDone(ok);
}
// Follows a document: its meta and outline labels read (and so stored), the files of the build it is on fetched, and
// that build held - all of it before it is recorded, so the build it kept stays whole until this one is. A Markdown or
// text document reads its source again. Answers whether it is done.
async function offFollowDoc(docName: string): Promise<boolean> {
  let meta;
  // When the server was asked: a reading asked later is the newer one (offKeptWith).
  const seen = Date.now();
  try {
    meta = (await api(withDocQuery('/api/meta', docName), { what: '화면 정보 읽기', silent: true })).data;
  } catch (error) {
    return false;
  }
  if (!meta) return false;
  if (rendersInBrowser(meta.kind)) {
    try {
      await api(withDocQuery('/api/source', docName), { what: '원문 읽기', silent: true, expect: [413] });
    } catch (error) {
      return false;
    }
    await offKeptSet((record) =>
      offKeptWith(record, docName, { build: '', files: [], at: 0, src: meta.src_mtime ?? null, seen }),
    );
    return true;
  }
  const build = meta.pages_build;
  // Nothing to keep.
  if (!build) return true;
  try {
    await api(withDocQuery('/api/outline-labels', docName), { what: '목차 번호 읽기', silent: true });
  } catch (error) {}
  const files = offlineDocFiles(docName, meta);
  // Half a build is not kept: the one before stays whole, and what was fetched of this one is noted to go in turn.
  const half = async () => {
    await offKeptSet((record) => offKeptPart(record, docName, build, files));
    return false;
  };
  for (let i = 0; i < files.length; i += OFF_KEEP_CHUNK) {
    const answer = await offlineAsk({ type: 'keep', urls: files.slice(i, i + OFF_KEEP_CHUNK) }, OFF_KEEP_MS);
    if (!answer || (answer.failed || []).length) return half();
  }
  const hold = await offHold(docName, build, 7);
  // Not held, it may be gone before its pins are sent.
  if (!hold) return half();
  await offKeptSet((record) => offKeptWith(record, docName, { build: build, files, at: hold.at, seen, meta: meta }));
  return true;
}
// Drops the copies of the old builds no queued pin was drawn on, and asks again the holds that are due. Of a dropped
// build's hold only this browser's own share is let go, and only where the server counts shares - another device's
// queue may need that build. A queue that cannot be read drops nothing: read as empty, it would drop the build a
// waiting pin needs. Nor does a build the server still shows go (one half fetched waits for the next try, the screen
// may be drawn from it). Answers whether everything went.
async function offFollowTidy(): Promise<boolean> {
  let ok = true;
  const kept = await offKept();
  if (!kept) return true;
  const queue = await offQueue('readonly', (store) => store.getAll());
  if (!Array.isArray(queue)) return false;
  const shown = (oldBuild: any) => !!OFF.seen[oldBuild.doc] && OFF.seen[oldBuild.doc].build === oldBuild.build;
  for (const oldBuild of offFree(kept.old, queue).filter((oldBuild: any) => !shown(oldBuild))) {
    if (offlineNow()) return false;
    const urls = oldBuild.files || [];
    if (urls.length && !(await offlineAsk({ type: 'drop', urls }))) {
      ok = false;
      continue;
    }
    // Its hold: this browser's own share is let go, where the server counts a hold per holder and this browser has a
    // name there - the build stays held for as long as another device holds it. On a server that knows one hold per
    // build nothing is let go: the hold may be another device's, whose queue this one cannot see, so it lapses.
    // No answer keeps the build in the list, and it is let go on the next try.
    if (OFF.holder && !oldBuild.unheld && (await offHolderId()) && !(await offHold(oldBuild.doc, oldBuild.build, 0))) {
      ok = false;
      continue;
    }
    await offKeptSet(
      (record) =>
        record && {
          ...record,
          old: (record.old || []).filter(
            (other: any) => !(other.doc === oldBuild.doc && other.build === oldBuild.build),
          ),
        },
    );
  }
  for (const dueHold of offRenewDue(await offKept(), Date.now())) {
    if (offlineNow()) return false;
    const answer = await offHold(dueHold.doc, dueHold.build, 7);
    if (!answer) {
      ok = false;
      continue;
    }
    await offKeptSet((record) => offKeptHeld(record, dueHold.doc, dueHold.build, answer.at));
  }
  return ok;
}
// After a follow: a success clears the failures; a follow the connection cut short is not a failure of its own. A
// failure waits longer each time before the next try, and is said once a visit when it keeps failing.
function offFollowDone(ok: boolean) {
  if (ok) {
    OFF.fails = 0;
    OFF.after = 0;
    return;
  }
  if (OFF.prep || offlineNow()) return;
  OFF.fails++;
  OFF.after = Date.now() + Math.min(OFF_RETRY_MAX, OFF_RETRY_MS * 2 ** (OFF.fails - 1));
  if (OFF.fails >= OFF_SAY_AFTER && !OFF.failSaid) {
    OFF.failSaid = true;
    lineNote(
      '오프라인용 받기를 마치지 못했습니다 — 다시 시도하세요',
      NOTICE_KIND.WARN,
      {
        label: '다시 시도',
        fn: () => {
          void offlinePrepare();
        },
      },
      {},
    );
  }
}

// ---------------- Pinning while cut off
// The words inside the dragged box, read from the PDF this tab already has open (PDF.js, the same text the search
// reads). The server's own quote comes from pdftotext at pick time; this one only has to say what was pinned while the
// answer is still hours away, and the pick's quote replaces it when the pin is written.
async function offlineQuote(page: number, rect: { x0: number; y0: number; x1: number; y1: number }): Promise<string> {
  if (!VECTOR_PDF.doc) return '';
  try {
    // The one reader of a page's text (pdf/flow.ts).
    const { items, vp: viewport } = await pageText(VECTOR_PDF.doc, page);
    return quoteIn(items, viewport.height, rect);
  } catch (error) {
    return '';
  }
}
// The words of a page's text items that a box lies on. The box is in PDF points measured from the page's top, as a
// drag's is; PDF.js gives each item where its baseline starts, measured from the bottom, and how wide and tall it is.
// An item counts when its run crosses the box and the middle of its line is inside it. Judged by where the item
// starts alone, a line that begins at the margin and runs through the box would be left out - which is most lines, so
// the quote would come back empty. Cut at 160 characters the way the server cuts its own (159 and an ellipsis). Pure.
function quoteIn(items: any[], pageHeight: number, rect: { x0: number; y0: number; x1: number; y1: number }): string {
  const out = [] as string[];
  (items || []).forEach((item) => {
    const matrix = item && item.transform;
    if (!matrix || typeof item.str !== 'string' || !item.str.trim()) return;
    const x = matrix[4],
      width = Number(item.width) || 0,
      height = Number(item.height) || Math.hypot(matrix[2], matrix[3]) || 0,
      middle = pageHeight - matrix[5] - height / 2;
    if (x + width >= rect.x0 && x <= rect.x1 && middle >= rect.y0 && middle <= rect.y1) out.push(item.str);
  });
  const quote = out.join(' ').replace(/\s+/g, ' ').trim();
  return quote.length > 160 ? quote.slice(0, 159) + '…' : quote;
}
// A drag whose pick could not be sent: the box stays and the composer opens on a selection with no lines - the same
// shape a view-only PDF's region selection has (isRegion), so the range ladder, the source snippet, a suggested edit
// and a verdict are all off, and [핀 저장] has only the page, the box and the words to keep. Its lines are found when
// the queue is sent.
async function offlinePick(drag: {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  frac: number[];
  pdf_build?: string;
  doc?: string;
}) {
  const seq = PICKSEQ,
    rect = { x0: drag.x0, y0: drag.y0, x1: drag.x1, y1: drag.y1 },
    quote = await offlineQuote(drag.page, rect);
  // A newer drag or a cancel owns the composer now.
  if (seq !== PICKSEQ) return;
  const selection = {
    kind: 'region',
    page: drag.page,
    frac: drag.frac,
    quote,
    file: null,
    name: null,
    lo: null,
    hi: null,
    pdf: META ? META.pages_build : null,
    pdf_build: drag.pdf_build,
    doc: drag.doc || DOC,
    offline: true,
    rect,
    levels: [],
    overlaps: [],
    scope: null,
    env: null,
    elSel: null,
    el: null,
    via: null,
    score: null,
    warn: '',
    snippet: '',
    n_lines: 0,
    default_level: null,
  } as any;
  setComposeCurrent(selection as Selection);
  setComposeIntent(COMPOSE.intent + 1);
  setComposePicking(false);
  setComposeDismissedOverlap(null);
  setSnipOpen(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  $('#composer').hidden = false;
  renderComposer();
  $('#composer').scrollTop = 0;
  lineNote('연결이 끊겨 줄은 뒤에 찾습니다 — 메모를 쓰고 저장하면 쌓아 둡니다', NOTICE_KIND.INFO, null, {
    life: NOTICE_LIFE.CLICK,
    topic: NOTICE_TOPIC.OFFLINE,
  });
  if (LAST_POINTER === 'mouse')
    (isSelectionPopoverOpen() ? SELECTION_POPOVER_FIELD : $('#note')).focus({ preventScroll: true });
}
// [핀 저장] with no server: the pin goes to the queue with everything needed to write it later - where it was drawn, on
// which build, its words, and what the composer asked (the note, its kind, its assignee and the @-tags). Answers
// whether it was kept; a browser that refuses the queue answers false and the caller says the save failed, so no pin is
// lost silently. tried is given for a save that was sent and got no answer (composer/flow-save.ts): the record is kept
// as one whose write was attempted - under the key the save went with, if it had one, and with the newest pin that
// stood before it - so the send asks for it before it writes it.
async function offlineQueueSave(
  selection: Selection,
  note: string,
  out: { kind: string | null; assignee: string | null },
  mentions: string[],
  tried?: { idem?: string; top: number },
): Promise<boolean> {
  if (OFF.n >= OFF_MAX) {
    bannerNote(
      NOTICE_HOST.COMPOSER,
      translateTemplate('쌓아 둘 수 있는 핀은 {n}개까지입니다 — 연결되면 먼저 반영하세요', { n: OFF_MAX }),
      NOTICE_KIND.ERR,
      null,
      { save: true, source: 'offline-queue' },
    );
    return false;
  }
  // What the send needs is the drag itself, never the lines a pick once answered: hours pass, the manuscript is edited
  // while the person is away, and those line numbers would be written against text that has moved - a pin that reads
  // as placed and points elsewhere. So the record carries the box as page fractions (frac, which every drag has) and
  // the page's size in points on the build it was drawn on, which together rebuild that pick request exactly. The
  // lines a pick already found are kept only to tell the person what the pin used to point at if its place is lost.
  const pageFacts = META && META.pages && META.pages[selection.page - 1];
  const found =
    !selection.offline &&
    !isRegion(selection) &&
    !!selection.file &&
    typeof selection.lo === 'number' &&
    typeof selection.hi === 'number';
  // A Markdown or text document has no page: its lines are the place, and the browser drew them from the source it
  // holds. The record keeps those lines' own text, so the send can tell whether they still read the same - and find
  // them again when lines were only added or removed above them.
  const lined = found && typeof selection.page !== 'number' && MARKDOWN_VIEW.doc === (selection.doc || DOC);
  const firstLine = selection.lo as number,
    lastLine = selection.hi as number;
  const rec = {
    v: 1,
    label: META ? META.label : '',
    doc: selection.doc || DOC,
    build: selection.pdf_build || (META ? META.pages_build : '') || '',
    page: selection.page,
    rect: selection.rect || null,
    frac: selection.frac,
    pt: pageFacts ? { w: pageFacts.pt_w, h: pageFacts.pt_h } : null,
    quote: selection.quote || '',
    note,
    kind_req: out.kind,
    assignee: out.assignee,
    mentions: mentions.slice(),
    at: new Date().toISOString(),
    held: false,
    why: '',
    sent: !!tried,
    top: tried ? tried.top : undefined,
    place: found ? { file: selection.file, name: selection.name, lo: selection.lo, hi: selection.hi } : null,
    lines: lined
      ? {
          file: selection.file,
          name: selection.name,
          lo: firstLine,
          hi: lastLine,
          text: MARKDOWN_VIEW.lines.slice(firstLine - 1, lastLine).join('\n'),
          kind: selection.scope ? kindFor(selection.scope, selection.env) : selection.kind,
          scope: selection.scope ? wireScope(selection.scope) : null,
        }
      : null,
    idem: (tried && tried.idem) || offlineKey(),
  };
  if (found && typeof selection.page !== 'number' && !lined) {
    // A line selection whose source this tab no longer holds: nothing to check it against later.
    bannerNote(
      NOTICE_HOST.COMPOSER,
      translate('핀 저장 실패 — 이 문서의 원문을 다시 읽은 뒤 저장하세요'),
      NOTICE_KIND.ERR,
      null,
      { save: true, source: 'offline-queue' },
    );
    return false;
  }
  const id = await offAdd(rec);
  if (id === null) {
    bannerNote(
      NOTICE_HOST.COMPOSER,
      translate('핀 저장 실패 — 이 브라우저가 오프라인 보관을 막고 있습니다'),
      NOTICE_KIND.ERR,
      null,
      { save: true, source: 'offline-queue' },
    );
    return false;
  }
  await offlineSync();
  undoNote(
    NOTICE_PLACE.LINE,
    translateTemplate('쌓아 둠 · 오프라인 핀 {n}개 — 연결되면 반영합니다', { n: OFF.n }),
    {
      label: '되돌리기',
      wait: true,
      fn: async () => {
        await offDel(id);
        await offlineSync();
        return true;
      },
    },
    { literal: true },
  );
  // A selection picked while cut off is kept even once the connection is back (it still has no lines). Then there is
  // nothing to wait for: it goes out now, rather than sitting in the queue until the next reconnect or reload.
  if (!offlineNow()) void offlineFlush();
  return true;
}

// ---------------- Sending the queue
// A key for one write, made when the pin is kept and sent with every attempt at it: the server answers a second attempt
// with the pin the first one made (api.md POST /api/pin, idem). 16 to 64 characters of [A-Za-z0-9_-]; a UUID where the
// browser gives one, else time and random digits (a page that is not a secure context has no randomUUID).
function offlineKey() {
  try {
    if (crypto && typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  } catch (error) {}
  const randomHex = () =>
    Math.floor(Math.random() * 0x100000000)
      .toString(16)
      .padStart(8, '0');
  return 'k' + Date.now().toString(16) + '-' + randomHex() + randomHex() + randomHex();
}
// Where the kept lines of a Markdown or text document stand in its source now, or null when they no longer do. The
// same lines at the same numbers are that place. Else the one place in the source where those very lines stand
// together - text was added or removed above them, the common change - is. Lines that changed, or that stand in two
// places, have no place this can vouch for. Pure.
/** @param lines the source now @param want the kept lines */
function linesWhere(lines: string[], want: { lo: number; text: string }): { lo: number; hi: number } | null {
  const text = String(want.text).split('\n'),
    lineCount = text.length;
  const same = (start: number) => {
    for (let i = 0; i < lineCount; i++) if (lines[start - 1 + i] !== text[i]) return false;
    return true;
  };
  if (want.lo >= 1 && want.lo - 1 + lineCount <= lines.length && same(want.lo))
    return { lo: want.lo, hi: want.lo + lineCount - 1 };
  let hit = 0,
    count = 0;
  for (let start = 1; start + lineCount - 1 <= lines.length; start++)
    if (same(start)) {
      count++;
      hit = start;
      if (count > 1) return null;
    }
  return count === 1 ? { lo: hit, hi: hit + lineCount - 1 } : null;
}
// The place a kept Markdown or text record is written at: its lines as the source reads now (linesWhere), in the shape
// offlineBody takes. 'net' when the source could not be asked for (the record waits), null when the lines are gone.
async function offlinePlaceLines(rec: any): Promise<any> {
  let answer;
  try {
    answer = await api(withDocQuery('/api/source', rec.doc), { what: '원문 읽기', silent: true, expect: [413] });
  } catch (error) {
    const apiError = error as ApiError,
      status = (apiError && apiError.status) || 0;
    return status >= 400 && status < 500 ? null : 'net';
  }
  const lines =
    answer.status === 200 && answer.data && Array.isArray(answer.data.lines) ? answer.data.lines.map(String) : null;
  const at = lines ? linesWhere(lines, rec.lines) : null;
  if (!at) return null;
  return {
    file: rec.lines.file,
    name: rec.lines.name,
    lo: at.lo,
    hi: at.hi,
    raw_lo: at.lo,
    raw_hi: at.hi,
    kind: rec.lines.kind,
    scope: rec.lines.scope || undefined,
    quote: rec.quote,
  };
}
// The drag a record holds, in the PDF points pick reads: the box kept with it, or the one its page fractions and that
// page's size on the build make - the same product pdf/input-selection.ts sends when the drag happens. Null when the
// record has neither, which is the one case nothing can be placed from (a box of zeros would resolve to the page's
// corner). Pure.
function offlineBox(rec: any): { x0: number; y0: number; x1: number; y1: number } | null {
  if (rec.rect) return rec.rect;
  const frac = rec.frac,
    pagePoints = rec.pt;
  if (!Array.isArray(frac) || frac.length < 4 || !pagePoints || !(pagePoints.w > 0) || !(pagePoints.h > 0)) return null;
  return {
    x0: frac[0] * pagePoints.w,
    y0: frac[1] * pagePoints.h,
    x1: (frac[0] + frac[2]) * pagePoints.w,
    y1: (frac[1] + frac[3]) * pagePoints.h,
  };
}
// The pin body a found place and a kept record make, the same whitelist POST /api/pin takes (api.md §핀 추가). A pick
// that answered with no file is a region answer - a view-only PDF, or a figure element with no code behind it - and
// that pin is its page and box, as savePin sends one.
function offlineBody(rec: any, place: any): Record<string, unknown> {
  if (!place.file) {
    const region = {
      page: place.page,
      frac: place.frac || rec.frac,
      note: rec.note,
      quote: place.quote || rec.quote || '',
      pdf_build: place.pdf_build || rec.build || undefined,
      doc: rec.doc || undefined,
      kind_req: rec.kind_req,
      assignee: rec.assignee,
    } as Record<string, unknown>;
    if ((rec.mentions || []).length) region.mentions = rec.mentions;
    if (rec.idem) region.idem = rec.idem;
    // A figure pick: its element, and the element's box as the pin's (as savePin sends one).
    if (place.el) figureFields(region, place.el, null);
    return region;
  }
  const body = {
    file: place.file,
    name: place.name,
    page: place.page,
    lo: place.lo,
    hi: place.hi,
    raw_lo: place.raw_lo,
    raw_hi: place.raw_hi,
    kind: place.kind,
    via: place.via,
    score: place.score,
    fill: place.fill,
    rival: place.rival,
    frac: place.frac,
    note: rec.note,
    quote: place.quote || rec.quote || '',
    pdf_build: place.pdf_build || rec.build || undefined,
    doc: rec.doc || undefined,
    kind_req: rec.kind_req,
    assignee: rec.assignee,
  } as Record<string, unknown>;
  if (place.scope) body.scope = place.scope;
  if ((rec.mentions || []).length) body.mentions = rec.mentions;
  if (rec.idem) body.idem = rec.idem;
  // A figure pick names its element. Without it the pin has no element to follow: its mark stays where it was drawn
  // when the element moves, and is never reported lost (pins/listing/projection.py element_marks). The rung is the
  // answer's default one, the rung an online save of an untouched selection is on.
  if (place.el) {
    const level = place.default_level ? levelOf(place, place.default_level) : null;
    figureFields(body, place.el, level && level.el ? level : null);
  }
  return body;
}
// Two boxes are the same box: every number within a millionth of the page, the tolerance a whole-page verdict target
// is read with (domain.md §판정 대상). Pure.
function fracSame(first: unknown, second: unknown) {
  if (!Array.isArray(first) || !Array.isArray(second) || first.length < 4 || second.length < 4) return false;
  for (let i = 0; i < 4; i++) if (!(Math.abs(first[i] - second[i]) <= 1e-6)) return false;
  return true;
}
// The pin this record already is on the server, or 0: mine, on its document, at the same place, with the same note.
// A send whose answer was lost is found here instead of written twice - the judgment savePin makes for its own lost
// answer. A line answer stands on its lines; a region answer stands on its page AND its box, because two region pins
// on one page are told apart by nothing else, and a page-only judgment would delete a second pin that was never
// written.
// A pin this queue has already written - in this send or any earlier one (offWrote) - is not offered again: two
// deliberate pins may be alike in every field this reads, and only one of them is that pin. Nor is a pin that was
// already there when this record was attempted (rec.top, as findLandedVerdict reads its own lost answer): whatever that
// pin is, it is not the write this record made afterwards.
function offlineLanded(rec: any, place: any, claimed: Set<number>): number {
  // A figure pin's box is its element's (offlineBody).
  const frac = place.el && Array.isArray(place.el.frac) ? place.el.frac : place.frac || rec.frac;
  const top = typeof rec.top === 'number' ? rec.top : 0;
  const hit = OPEN_ALL.find(
    (pin) =>
      pin.id > top &&
      !claimed.has(pin.id) &&
      isMe(pin.author) &&
      pdoc(pin) === (rec.doc || DEFAULT_DOC) &&
      String(pin.note || '') === String(rec.note || '') &&
      (place.file
        ? pin.file === place.file && pin.lo === place.lo && pin.hi === place.hi
        : !pin.file && pin.page === place.page && fracSame(pin.frac, frac)),
  );
  return hit ? hit.id : 0;
}
// Sends the queue, oldest first: each record's own coordinates and build go to pick, its answer to the pin. A record is
// dropped only once its pin is on the server. One whose place cannot be found again (the build is gone, or the drag no
// longer reads as text) is kept and marked, so the count never hides it and the next send tries again.
async function offlineFlush() {
  // The flag is taken before anything is awaited. Reconnecting fires several triggers within the same tick (the
  // 'online' event, the light poll's recovery, boot, the status line's [지금 반영]); a flag set after the first await
  // would let two of them read the same records and write every pin twice, since each reads the list before the other
  // writes.
  if (OFF.flushing || offlineNow() || viewerBlocked()) return;
  OFF.flushing = true;
  const all = await offAll();
  if (!all.length) {
    OFF.flushing = false;
    await offlineSync();
    return;
  }
  // The server is asked what it can do before a way of sending is chosen. What it could do when it was last heard
  // from is not that: a tab drawn from stored reads has heard nothing this visit and starts sending on the 'online'
  // event, and a server may have been rolled back to a Limn that drops the key it does not know. The answer sets
  // OFF.idem on its way through api() (offStash). No answer means the connection is not there after all.
  try {
    await api(withDocQuery('/api/meta?light=1'), { what: '상태 확인', silent: true, wait: API_WAIT.POLL });
  } catch (error) {
    OFF.flushing = false;
    return;
  }
  const saved = [] as number[],
    claimed = new Set(await offWrote());
  let held = 0,
    failed = 0;
  try {
    // What is already there - a lost answer from an earlier send is found, not written twice.
    await loadPins();
    for (const rec of all) {
      if (offlineNow()) break;
      // A record whose write was already attempted on a server that knows a write by its key is asked about by the key
      // alone, before anything is placed. The earlier attempt may have made the pin and lost only its answer - and by
      // now its place may be gone (the held build expired; the lines were edited, perhaps by the agent that handled
      // that very pin). Placed first, such a record would be held and its key never tried: the pin would stand on the
      // server while the record stays in the queue, a [다시 찍기] away from being made twice. The question writes
      // nothing whichever way it is answered (api.md POST /api/pin, replay_only).
      const keyed = OFF.idem && !!rec.idem;
      if (keyed && rec.sent) {
        try {
          const answer = await api('/api/pin', {
            method: 'POST',
            body: { idem: rec.idem, replay_only: true, doc: rec.doc || undefined },
            what: '핀 저장',
            silent: true,
            expect: [409],
            wait: API_WAIT.SEND,
          });
          if (answer.status === 200 && answer.data && typeof answer.data.id === 'number') {
            claimed.add(answer.data.id);
            await offWroteAdd(answer.data.id);
            saved.push(answer.data.id);
            await offDel(rec.id);
            continue;
          }
          // The server knows no pin by this key: the attempt never arrived, so its mark comes off. A record then held
          // for its place is one [다시 찍기] may take back - offline/view.ts refuses a record that may be on the
          // server.
          if (answer.status === 409 && (await offHas(rec.id))) {
            rec.sent = false;
            await offPut(rec);
          }
        } catch (error) {
          // No answer to the question either: the record waits, unplaced and unheld.
          failed++;
          continue;
        }
      }
      // Every record is placed afresh. A drag is asked of pick, on the build it was drawn on; the lines of a Markdown
      // or text document are looked for in its source as it reads now. The lines a pick once answered are never
      // written: the manuscript moves while a person is away, and writing them would anchor the pin to whatever
      // stands at those numbers now.
      let place = null as any;
      if (rec.lines) {
        place = await offlinePlaceLines(rec);
        if (place === 'net') {
          failed++;
          continue;
        }
        if (!place) {
          rec.held = true;
          rec.why = translate('그사이 그 줄들의 글이 바뀌었습니다');
          await offPut(rec);
          held++;
          continue;
        }
      } else {
        const box = offlineBox(rec);
        if (!box) {
          rec.held = true;
          rec.why = translate('위치를 찾지 못했습니다');
          await offPut(rec);
          held++;
          continue;
        }
        const pickRequest = {
          page: rec.page,
          x0: box.x0,
          y0: box.y0,
          x1: box.x1,
          y1: box.y1,
          frac: rec.frac,
          pdf_build: rec.build || undefined,
          doc: rec.doc || undefined,
        };
        try {
          place = (
            await api('/api/pick', {
              method: 'POST',
              body: pickRequest,
              what: '위치 찾기',
              silent: true,
              wait: API_WAIT.SEND,
            })
          ).data;
        } catch (error) {
          // No answer or a refusal: the record stays for the next send.
          failed++;
          continue;
        }
        if (!place || place.error) {
          rec.held = true;
          rec.why = errText(place) || translate('위치를 찾지 못했습니다');
          await offPut(rec);
          held++;
          continue;
        }
      }
      // A server that knows a write by its key needs none of the looking below: the same key is the same pin, so the
      // record is sent with it until an answer comes, and an answer to a second attempt names the pin the first made.
      // The attempt is recorded before it is made (a tab closed mid-request never reaches the lines after it), which is
      // what sends the next visit to the question above. A refusal of the request itself (4xx) says nothing was
      // written: the mark comes off and the record is kept with what the server said. Both ways of sending keep what
      // the other needs. This one notes the pins that existed before the attempt (top) and records the pin it writes
      // (offWroteAdd), although it reads neither: a server rolled back to a Limn without the key sends the next visit
      // to the looking below, and an attempt marked here with no boundary would let any older look-alike answer for it,
      // as a pin written here but not recorded would let a twin's pin do.
      if (keyed) {
        if (!(await offHas(rec.id))) continue;
        rec.sent = true;
        rec.top = topPinId();
        await offPut(rec);
        try {
          const { data } = await api('/api/pin', {
            method: 'POST',
            body: offlineBody(rec, place),
            what: '핀 저장',
            silent: true,
            wait: API_WAIT.SEND,
          });
          if (data && typeof data.id === 'number') {
            claimed.add(data.id);
            await offWroteAdd(data.id);
          }
          saved.push(data && data.id);
          await offDel(rec.id);
        } catch (error) {
          const apiError = error as ApiError,
            status = (apiError && apiError.status) || 0;
          if (status >= 400 && status < 500) {
            rec.sent = false;
            rec.held = true;
            rec.why = errText(apiError.data) || 'HTTP ' + status;
            await offPut(rec);
            held++;
          } else failed++;
        }
        continue;
      }
      // Only a record whose write was already attempted can be a pin on the server. A record that has never been
      // sent is written, whatever is there: two pins alike in document, place and note are told apart by nothing this
      // can read, and matching a fresh record against one of them would delete a pin that was never written.
      if (rec.sent) {
        // Its pin number, not the record's.
        const was = offlineLanded(rec, place, claimed);
        if (was) {
          claimed.add(was);
          await offWroteAdd(was);
          saved.push(was);
          await offDel(rec.id);
          continue;
        }
      }
      // Another tab of this browser shares the queue and may have written this one while the pick was out: a record
      // that is no longer there has been dealt with, and writing it again would make the pin twice.
      if (!(await offHas(rec.id))) continue;
      // The attempt is recorded before it is made: a tab closed mid-request never reaches the lines below, and the
      // record has to stay matchable or its pin is written twice. The mark comes off again only for an answer that
      // says the request was turned away before anything was written - a refusal of the request itself (4xx: a field
      // the server would not take, a role that may not write, a conflict). Everything else may be on the server: no
      // answer at all, a 5xx the server returned after its write went through, a gateway's 502 or 504 over a request
      // that did reach it. Those keep the mark and are looked for in the list instead.
      rec.sent = true;
      rec.top = topPinId();
      // The pins that existed before this write, as savePin notes for its own.
      await offPut(rec);
      try {
        const { data } = await api('/api/pin', {
          method: 'POST',
          body: offlineBody(rec, place),
          what: '핀 저장',
          silent: true,
          wait: API_WAIT.SEND,
        });
        if (data && typeof data.id === 'number') {
          claimed.add(data.id);
          await offWroteAdd(data.id);
        }
        saved.push(data && data.id);
        await offDel(rec.id);
      } catch (error) {
        const apiError = error as ApiError;
        const status = (apiError && apiError.status) || 0;
        // Turned away: nothing is on the server.
        if (status >= 400 && status < 500) {
          rec.sent = false;
          rec.held = true;
          rec.why = errText(apiError.data) || 'HTTP ' + status;
          await offPut(rec);
          held++;
          continue;
        }
        await loadPins();
        const late = offlineLanded(rec, place, claimed);
        if (late) {
          claimed.add(late);
          await offWroteAdd(late);
          saved.push(late);
          await offDel(rec.id);
          continue;
        }
        failed++;
      }
    }
  } finally {
    OFF.flushing = false;
    try {
      await offWroteKeep(await offAll());
    } catch (error) {}
    await offlineSync();
    await loadPins();
  }
  const ids = saved.filter((savedId) => typeof savedId === 'number');
  if (ids.length)
    lineNote(
      ids.length <= 3
        ? translateTemplate('오프라인 핀 저장됨 · #{ids}', { ids: ids.join(', #') })
        : translateTemplate('오프라인 핀 {n}개 저장됨', { n: ids.length }),
      NOTICE_KIND.OK,
      null,
      { life: NOTICE_LIFE.TIMER, literal: true },
    );
  if (held)
    lineNote(
      translateTemplate('오프라인 핀 {n}개는 반영하지 못했습니다 — 쌓인 핀 목록에서 까닭을 보고 다시 찍거나 버리세요', {
        n: held,
      }),
      NOTICE_KIND.WARN,
      null,
      { literal: true },
    );
  if (failed)
    lineNote(
      translateTemplate('오프라인 핀 {n}개를 아직 보내지 못했습니다 — 연결되면 다시 보냅니다', { n: failed }),
      NOTICE_KIND.WARN,
      {
        label: '지금 반영',
        fn: () => {
          void offlineFlush();
        },
      },
      { literal: true },
    );
}

// Boot: the worker is registered, the queue is counted, and a queue waiting on a live connection is sent right away.
// The light poll calls offlineFlush() again whenever the connection comes back (documents/flow-polling.ts).
function offlineBoot() {
  // The first reads are done: from here a read that fails while connected is a failure again.
  OFF.boot = false;
  void offlineWorker();
  void offlineSync().then(() => {
    if (OFF.n && !offlineNow()) void offlineFlush();
  });
  // A visit starts by comparing the kept copy with what the server shows, once the kept record is read.
  void offKept().then((record) => {
    OFF.kept = record;
    OFF.keptAt = Date.now();
    offKeptShow();
    offFollowCheck(true);
  });
}
addEventListener('online', () => {
  void offlineFlush();
});
export {
  OFF,
  offDel,
  offPut,
  offReadKey,
  offStaleSaid,
  offStash,
  offStashed,
  offlineAskDown,
  offlineBack,
  offlineBoot,
  offlineFlush,
  offlineKey,
  offlineMayServe,
  offlinePick,
  offlinePrepare,
  offlineQueueSave,
  offlineSync,
};
