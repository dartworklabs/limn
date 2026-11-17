// ------------------------------------------------ Server calls
// Calls the server (JSON in and out) and returns {status, data}; a network failure or an unexpected status >= 400
// throws. Unless options.silent it is said first (apiFailed): options.what names the request ('핀 저장'), options.where
// the place (a NOTICE_HOST), options.retry the action a network failure offers, options.save that it was a pin's save.
// options.quietUnreached leaves a failure to reach the server to the caller to say (a refusal is still said).
// options.expect lists the statuses the caller handles itself; options.keepalive lets the request outlive the page;
// options.signal (an AbortSignal) ends it unanswered, as a network failure - also while its body is read. options.wait
// (ms) is the longest it waits for an answer, body included; past it the request is ended and is a network failure like
// any other (API_WAIT). Its error is keyed by its source - options.source, else its method and URL (which name its pin
// and document) with options.intent, what it asks of a URL several actions share (a pin's edit: 'edit', 'loc',
// 'append', 'append-undo'): a repeat replaces it, and an answer from the same source - the same intent - clears it
// (sourceOk). How long a request waits for an answer (ms). A server that cannot be reached does not always refuse: on a
// tailnet with no internet behind it the name still resolves and the request goes into the tunnel, and nothing comes
// back for as long as the system lets a connection wait - a minute and more. Everything that tells "cut off" from
// "connected" hangs on a request failing, so a request that only waited would leave the viewer connected and busy: the
// light poll would count no failure, a drag's composer would not open, a save would not end and nothing would reach the
// queue. A request that carries a wait is ended at it and fails as an unreached server does. POLL the light poll, and
// the question a send of the queue starts with READ a document read that has a stored answer to fall back on
// (offline/flow.ts OFF_READS) PICK finding a selection's lines SAVE writing a new pin SEND a request of the queue's
// send Requests without one (a rebuild, a revision's diff or build) may take as long as the server needs. API_OUT says
// the last request that ended got no answer (or the worker answered this page from its copy because the network did
// not, offlineAskDown). While it stands and a stored answer may serve (offlineMayServe), a document read with a stored
// answer is answered from it without asking: a visit's first reads are made one after another, and each waiting out its
// own request would draw the page a read's wait later, every time. The light poll always asks, and its answer - any
// answer - takes API_OUT down.
import { html, lucideIcon, setHtml } from './markup.ts';
import { errText, translateTemplate, translate } from './i18n.ts';
import { bannerNote, lineNote, quietNote, sourceOk } from './notices.ts';
import { NOTICE_HOST, NOTICE_KIND } from './tables.ts';
// The copies kept for reading while cut off (offline/flow.ts): a document read's key, whether a stored answer may
// serve, the stored answer, saying once how old it is, the connection back, keeping an answer. Platform knows no
// feature, so this is a seam: js/main.ts registers it once, before boot() runs (no code that runs while the script loads
// sends a request), and api() calls it at the point, with the arguments and in the order it calls the offline code. A
// request before the registration throws, naming the seam.
// url and options are api()'s own, as its caller gave them.
interface RequestFallback {
  /** The key a read of url is kept under, null for a request that is not kept. */
  readKey(url: unknown, options: unknown): string | null;
  /** Whether a stored answer may serve a read now (this visit's first reads, or a connection known to be gone). */
  mayServe(): boolean;
  /** The stored answer for url, or null. */
  stashed(url: unknown, options: unknown): Promise<{ data: unknown; status: number; at: number } | null>;
  /** Says once per visit that the screen was read at `at`, before the connection went. */
  staleSaid(at: number): void;
  /** The connection answered again. */
  back(): void;
  /** Keeps a read's answer for a later visit with no network. */
  stash(url: unknown, data: unknown, status: number, options: unknown): void;
}
let REQUEST_FALLBACK: RequestFallback | null = null;
// Registers the copies kept for reading while cut off; js/main.ts calls it once.
function setRequestFallback(fallback: RequestFallback) {
  REQUEST_FALLBACK = fallback;
}
// The registered fallback; throws before setRequestFallback() has run.
function requestFallback(): RequestFallback {
  if (!REQUEST_FALLBACK) throw new Error('setRequestFallback() has not run: api() has no copies to fall back on');
  return REQUEST_FALLBACK;
}
const API_WAIT = { POLL: 8000, READ: 8000, PICK: 8000, SAVE: 10000, SEND: 30000 };
let API_OUT = false;
/** What a caller tells api() about a request (the header above says what each field does). */
interface RequestOptions {
  method?: string;
  body?: unknown;
  what?: string;
  where?: string;
  retry?: () => unknown;
  save?: boolean;
  source?: string;
  intent?: string;
  quietUnreached?: boolean;
  expect?: number[];
  keepalive?: boolean;
  signal?: AbortSignal;
  wait?: number;
  silent?: boolean;
}
async function api(url: string, options?: RequestOptions): Promise<{ status: number; data: any }> {
  options = { ...(options || {}) };
  options.source =
    options.source || (options.method || 'GET') + ' ' + url + (options.intent ? ' ' + options.intent : '');
  const init = { method: options.method || 'GET', headers: {} } as RequestInit & { headers: Record<string, string> };
  if (options.keepalive) init.keepalive = true;
  if (options.signal) init.signal = options.signal;
  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
    init.headers['Content-Type'] = 'application/json';
  }
  const read = !!requestFallback().readKey(url, options);
  if (read && API_OUT && requestFallback().mayServe()) {
    const kept = await requestFallback().stashed(url, options);
    if (kept) {
      requestFallback().staleSaid(kept.at);
      sourceOk(options.source);
      return { status: kept.status, data: kept.data };
    }
  }
  const wait = options.wait || (read ? API_WAIT.READ : 0);
  let timer = undefined as ReturnType<typeof setTimeout> | undefined;
  const controller = wait ? new AbortController() : null;
  if (controller) {
    const end = () => controller.abort();
    timer = setTimeout(end, wait);
    init.signal = controller.signal;
    if (options.signal) {
      if (options.signal.aborted) end();
      else options.signal.addEventListener('abort', end, { once: true });
    }
  } // the caller's signal still ends it
  let response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    clearTimeout(timer);
    return apiUnanswered(url, options, error);
  }
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    if (options.signal && options.signal.aborted) {
      clearTimeout(timer);
      throw error;
    } // a body the caller's signal cut off is no answer, not an empty one
    if (controller && controller.signal.aborted) return apiUnanswered(url, options, error);
  } // nor is one the wait ran out on
  clearTimeout(timer);
  API_OUT = false;
  if (response.status >= 400 && !(options.expect || []).includes(response.status)) {
    if (!options.silent) apiFailed(options, errText(body) || 'HTTP ' + response.status, false);
    const err = new Error('HTTP ' + response.status) as ApiError;
    err.status = response.status;
    err.data = body;
    throw err;
  }
  sourceOk(options.source);
  requestFallback().back();
  // a document read the server answered is kept for a later visit with no network
  requestFallback().stash(url, body, response.status, options);
  return { status: response.status, data: body };
}
// A request that got no answer - refused by the network, or ended at its wait.
// A document read is answered from the last answer stored for it, where there is one and only where that is meant
// (offlineMayServe: this visit's first reads, or a connection known to be gone): a tab opened again with no network is
// drawn from it instead of staying empty. Writes, every other read, and a read that fails while the viewer is
// connected fail.
async function apiUnanswered(url: string, options: any, error: unknown): Promise<{ status: number; data: any }> {
  if (!(options.signal && options.signal.aborted)) API_OUT = true; // ended by its caller is not unanswered
  const kept = requestFallback().mayServe() ? await requestFallback().stashed(url, options) : null;
  if (kept) {
    requestFallback().staleSaid(kept.at);
    sourceOk(options.source);
    return { status: kept.status, data: kept.data };
  }
  if (!options.silent && !options.quietUnreached) apiFailed(options, translate('서버에 닿지 않습니다'), true);
  throw error;
}
// Says that a request failed ('{what} 실패 — {why}'): on the status line when options.where is NOTICE_HOST.LINE, else
// in a banner at that host (bannerNote), keyed by its source. [다시 시도] (options.retry) only when the server could
// not be reached - a refusal would refuse again.
function apiFailed(
  options: { what?: string; where?: string; retry?: () => void; save?: boolean; source?: string },
  why: string,
  unreachable: boolean,
) {
  const message =
    translateTemplate('{what} 실패', { what: translate(options.what || '요청').replace(/…$/, '') }) + ' — ' + why;
  const act = unreachable && options.retry ? { label: '다시 시도', fn: options.retry } : null,
    source = options.source || '';
  if (options.where === NOTICE_HOST.LINE) lineNote(message, NOTICE_KIND.ERR, act, { source });
  else bannerNote(options.where, message, NOTICE_KIND.ERR, act, { save: !!options.save, source });
}
// Copies text to the clipboard (a textarea and execCommand where the Clipboard API is refused). Said where it happened:
// the control that copied reads '복사됨' with a check for a moment (copiedMark), and it is read out politely.
async function copyText(text: string, control?: HTMLElement | null) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
    } catch (commandError) {}
    textarea.remove();
  }
  quietNote(translateTemplate('복사함: {text}', { text: text }));
  if (control) copiedMark(control);
}
const COPIED_MS = 1500; // how long a copy control says it copied
// A control says it copied: a check and '복사됨' in place of what it shows, never narrower than it was, for COPIED_MS;
// then what it showed comes back. A second copy meanwhile starts the moment again. Its name (aria-label) stays: the
// copy is read out by copyText.
function copiedMark(control: HTMLElement) {
  if (control._copiedT) clearTimeout(control._copiedT);
  else {
    control._copied = [...control.childNodes];
    control.style.minWidth = Math.ceil(control.getBoundingClientRect().width) + 'px';
  }
  control.classList.add('copied');
  setHtml(control, html`${lucideIcon('check')}<span class="lbl">${translate('복사됨')}</span>`);
  control._copiedT = setTimeout(() => {
    control.classList.remove('copied');
    control.replaceChildren(...(control._copied || []));
    control._copied = undefined;
    control._copiedT = undefined;
    control.style.minWidth = '';
  }, COPIED_MS);
}

// Sets API_OUT, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setApiOut<Value extends typeof API_OUT>(value: Value): Value {
  API_OUT = value;
  return value;
}
export { API_OUT, API_WAIT, api, apiFailed, copyText, setApiOut, setRequestFallback };
