// What `tsc` (tsconfig.json) needs to know about the viewer's page that its ES modules cannot say themselves
// (docs/handbook/viewer.md §타입 검사). Types only: nothing here reaches the served page.

// Placeholders the server fills in the built script (limn/viewer/assemble.py viewer_script).
declare const __LUCIDE_JSON__: Record<string, string>;
declare const __UI_EN_JSON__: Record<string, string | { one: string; other: string }>;
declare const __PDFJS_VERSION__: string;

// The head scripts set LIMN_LANG; the modules leave the boot time and the PDF.js state for tests that read them from outside.
interface Window {
  LIMN_LANG?: string;
  __pinViewerBoot: number;
  __pinVec: unknown;
  CloseWatcher?: typeof CloseWatcher;
}

// Safari's trackpad pinch events (gesturestart, gesturechange, gestureend), which the DOM library does not have: the
// pinch's scale since it began and where it is. An element's listener for one of them gets this event
// (pdf/input-zoom.ts, revisions/input.ts).
interface SafariGestureEvent extends UIEvent {
  scale: number;
  clientX: number;
  clientY: number;
}
interface HTMLElementEventMap {
  gesturestart: SafariGestureEvent;
  gesturechange: SafariGestureEvent;
  gestureend: SafariGestureEvent;
}

// The back-gesture hook of Chromium (layout/input.ts); the DOM library does not have it yet.
declare class CloseWatcher {
  onclose: (() => void) | null;
  destroy(): void;
}

// Fields the viewer keeps on its own elements: a card's flash timers (pins/flow-list.ts), a note field's @-tags picked from the @-list
// (composer/input-mentions.ts: the logins, and each one's place in the text with the text and the logins it was worked out for), the field
// whose text a field mirrors and which keeps its @-tags (composer/view-selection-popover.ts: the note popover's field mirrors the composer's
// note; composer/input-mentions.ts mentionModel), a copy control's own content and timer while it says '복사됨' (platform/api.ts copiedMark), a page
// verdict line's timer for its pressed word's context (verdict/flow-line.ts showPressedHint).
interface HTMLElement {
  _curT?: ReturnType<typeof setTimeout>;
  _flT?: ReturnType<typeof setTimeout>;
  _onT?: ReturnType<typeof setTimeout>;
  _mentions?: Set<string> | null;
  _tags?: MentionTag[];
  _tagsFor?: string;
  _tagsFrom?: Set<string> | null;
  _mirrorOf?: HTMLTextAreaElement;
  _copied?: ChildNode[];
  _copiedT?: ReturnType<typeof setTimeout>;
  _cap?: string;
}

// An @-tag picked from the @-list (composer/input-mentions.ts): whom it names, where its '@name' starts in the text, and that '@name'.
interface MentionTag {
  login: string;
  at: number;
  tok: string;
}

// A notification's buttons (pins/flow-notification.ts), which the DOM library leaves out of NotificationOptions though the service
// worker's showNotification() takes them.
interface NotificationOptions {
  actions?: { action: string; title: string }[];
}

// An api() refusal (platform/api.ts apiError): the HTTP status and the parsed body ride on the Error; isApiError tells
// it from any other value a request throws.
interface ApiError extends Error {
  status: number;
  data: unknown;
}
