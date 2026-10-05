// What `tsc` (tsconfig.json) needs to know about the viewer's page that the JS parts cannot say themselves
// (docs/handbook/viewer.md §타입 검사). Types only: nothing here reaches the served page.

// Placeholders the server fills when it assembles the page (limn/viewer/assemble.py viewer_html).
declare const __LUCIDE_JSON__: Record<string, string>;
declare const __UI_EN_JSON__: Record<string, string | { one: string; other: string }>;
declare const __PDFJS_VERSION__: string;

// The head scripts set LIMN_LANG; the parts leave the boot time and the PDF.js state for tests that read them from outside.
interface Window {
  LIMN_LANG?: string;
  __pinViewerBoot: number;
  __pinVec: unknown;
  CloseWatcher?: typeof CloseWatcher;
}

// The back-gesture hook of Chromium (gestures.js); the DOM library does not have it yet.
declare class CloseWatcher {
  onclose: (() => void) | null;
  destroy(): void;
}

// Fields the viewer keeps on its own elements: a card's flash timers (list.js), a note field's resolved @-tags (edit.js), a
// copy control's own content and timer while it says '복사됨' (api.js copiedMark).
interface HTMLElement {
  _curT?: ReturnType<typeof setTimeout>;
  _flT?: ReturnType<typeof setTimeout>;
  _mentions?: Set<string>;
  _copied?: ChildNode[];
  _copiedT?: ReturnType<typeof setTimeout>;
}

// A notification's buttons (notify.js), which the DOM library leaves out of NotificationOptions though the service
// worker's showNotification() takes them.
interface NotificationOptions {
  actions?: { action: string; title: string }[];
}

// An api() failure (api.js): the HTTP status and the parsed body ride on the Error.
interface ApiError extends Error {
  status?: number;
  data?: unknown;
}
