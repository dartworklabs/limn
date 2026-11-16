// ----------------------------------------------- The app's closed value tables (platform/tables.ts has the platform's)
// Closed sets (docs/handbook/viewer.md §닫힌 값 표): every value the viewer compares a state, status or mode against is
// a member of one frozen table here, never a string literal at the comparison. The first group comes from the server
// and must equal its strings exactly (src/limn/viewer/tests/test_viewer_source.py compares each table with the server's
// Literal or producer); the second is the viewer's own. Free text (messages, reasons, DOM and key names) is not tabled.
// a pin's `state` (pins.model.StateName); read it with pinState()
const PIN_STATE = Object.freeze({ OPEN: 'open', REVIEW: 'review', DONE: 'done' });
// GET /api/build `state`, meta `last_state`
const BUILD_STATE = Object.freeze({ IDLE: 'idle', RUNNING: 'running', OK: 'ok', OK_ERRORS: 'ok_errors', FAIL: 'fail' });
// a build's `pull.state` (pull.pull_record)
const PULL_STATE = Object.freeze({ OK: 'ok', UP_TO_DATE: 'up_to_date', SKIPPED: 'skipped', ERROR: 'error' });
const SYNC_STATE = Object.freeze({
  DISABLED: 'disabled',
  CHECKING: 'checking',
  DEFERRED: 'deferred',
  UPDATING: 'updating',
  UPDATED: 'updated',
  CURRENT: 'current',
  BLOCKED: 'blocked',
  ERROR: 'error',
}); // meta `sync.state`
// a comparison PDF's status `state`
const REVISION_STATE = Object.freeze({ IDLE: 'idle', RUNNING: 'running', READY: 'ready', ERROR: 'error' });
// a pin's change scope `mode` / a comparison's `scope` (scope.ScopeMode)
const SCOPE_MODE = Object.freeze({ PIN: 'pin', COMMIT: 'commit' });
// where a pin's change scope came from (scope.ScopeSource)
const SCOPE_SOURCE = Object.freeze({ CHANGES: 'changes', INFERRED: 'inferred', NONE: 'none' });
// a thread record's `ev` (pins.model.ThreadEv)
const THREAD_EVENT = Object.freeze({ CLOSE: 'close', REOPEN: 'reopen', CONFIRM: 'confirm', ASSIGN: 'assign' });
// how two line ranges overlap (pins.position.selection_rel)
const RANGE_REL = Object.freeze({ EQUAL: 'equal', INSIDE: 'inside', CONTAINS: 'contains', PARTIAL: 'partial' });
const REQUEST_KIND = Object.freeze({ FIX: 'fix', QUESTION: 'question' }); // a pin's `kind_req` (pins.model.KindReq)
// a person's `role` (access.ROLES)
const ROLE = Object.freeze({ OWNER: 'owner', EDITOR: 'editor', VIEWER: 'viewer', AGENT: 'agent' });
// how a pick traced its range: a pick's and a pin's `via` (limn.pins.location.mapping.Via)
const VIA = Object.freeze({ SYNCTEX: 'synctex', TEXT: 'text', MAP: 'map' });
// a document's `kind` in /api/docs and /api/meta (limn.runtime.documents.DocKind)
const DOC_KIND = Object.freeze({ TEX: 'tex', PDF: 'pdf', FIGURE: 'figure', MARKDOWN: 'markdown', TEXT: 'text' });
// where a figure pin's element is in the current build: a pin's `el_sync` (limn.builds.figure_map.ElSync)
const ELEMENT_SYNC = Object.freeze({ OK: 'ok', MOVED: 'moved', LOST: 'lost' });
// whether a pin's suggested edit still fits its lines: a pin's `suggest_state` (limn.pins.suggestion.SuggestState)
const SUGGEST_STATE = Object.freeze({ READY: 'ready', CHANGED: 'changed', UNKNOWN: 'unknown' });
// what a save of the composer's note does: a new pin, or the note joins the open pin the selection overlaps
// (assignOutcome)
const SAVE_MODE = Object.freeze({ NEW: 'new', APPEND: 'append' });
const LOCAL_LOGIN = 'local',
  // the identity-less local login (access.LOCAL_LOGIN); the assignee meaning "the agent" (pins.edit.ASSIGNEE_AGENT)
  ASSIGNEE_AGENT = 'agent';
// LAYOUT, the band's mode (BAND_MODE)
const LAYOUT_MODE = Object.freeze({ WIDE: 'wide', MID: 'mid', NARROW: 'narrow' });
const LAYOUT_BAND = Object.freeze({
  PHONE: 'phone',
  TABLET_SHEET: 'tablet-sheet',
  SHORT: 'short',
  MID_OVERLAY: 'mid-overlay',
  MID_SIDE: 'mid-side',
  WIDE: 'wide',
}); // BAND, by window width, height and primary pointer (layoutFor)
// what a new window observation does to the band (settleBand)
const BAND_STEP = Object.freeze({ KEEP: 'keep', WAIT: 'wait', SETTLE: 'settle' });
// a card's status dot (stateDot); also its CSS class
const CARD_DOT = Object.freeze({ OPEN: 'open', CLAIMED: 'claimed', REVIEW: 'review', LOST: 'lost' });
// why a selection or an edit card's range can carry no suggested edit (suggestOff)
const SUGGEST_OFF = Object.freeze({ PDF: 'pdf', FIGURE: 'figure', REGION: 'region', LONG: 'long' });
// the changes view's tab (REVISION_FORMAT); index.html data-format
const DIFF_FORMAT = Object.freeze({ PDF: 'pdf', SOURCE: 'source', OVERLAY: 'overlay', RENDERED: 'rendered' });
// which build a figure's overlay shows: the previous or the current one; index.html data-side
const OVERLAY_SIDE = Object.freeze({ PREV: 'prev', CUR: 'cur' });
// the changes view's quick range: since last seen, from this commit, this commit only; index.html data-range
const RANGE_MODE = Object.freeze({ LAST: 'last', FROM: 'from', ONE: 'one' });
const SEEN_STATE = Object.freeze({
  NONE: 'none',
  PENDING: 'pending',
  OK: 'ok',
  GONE: 'gone',
  OLD: 'old',
  ERROR: 'error',
  // what the server said of this browser's last-seen commit: no record, asking, counted, not in the history, older than
  // the window, could not answer
});
// the manuscript or the changes view; index.html data-mode
const VIEW_MODE = Object.freeze({ MANUSCRIPT: 'manuscript', REVISIONS: 'revisions' });
const NOTIFY_STATE = Object.freeze({
  ON: 'on',
  OFF: 'off',
  BLOCKED: 'blocked',
  UNSUPPORTED: 'unsupported',
  LOCAL: 'local',
}); // browser notifications on this device (notifyState)
const STATUS_KIND = Object.freeze({
  NOTICE: 'notice',
  FAILED: 'failed',
  ERRORS: 'errors',
  OFFLINE: 'offline',
  QUEUED: 'queued',
  OUTDATED: 'outdated',
  BUILDING: 'building',
  RENDERING: 'rendering',
  SYNC_BLOCKED: 'sync-blocked',
  UNCHANGED: 'unchanged',
  STALE: 'stale',
  SYNC: 'sync',
  PNG: 'png',
}); // an item of the status line (statusList)
// where a verdict button is (verdict/flow-line.ts): the composer's verdict row or a page verdict line
const VERDICT_PLACE = Object.freeze({ COMPOSER: 'composer', PAGE: 'page' });
// what a comment's time says (stampText); a .rt's data-form
const STAMP_FORM = Object.freeze({ BOTH: 'both', SHORT: 'short', EDITED: 'edited' });
const MARKDOWN_LIMIT = Object.freeze({
  BYTES: 'bytes',
  LINES: 'lines',
  NESTING: 'nesting',
  BLOCKS: 'blocks',
  INLINES: 'inlines',
  ELEMENTS: 'elements',
  TIME: 'time',
  LOAD: 'load',
  ERROR: 'error',
  NUL: 'nul',
}); // the limit a Markdown document's drawing hit (markdown/view.ts, MARKDOWN_LIMITS): #md's data-limit
export {
  PIN_STATE,
  BUILD_STATE,
  PULL_STATE,
  SYNC_STATE,
  REVISION_STATE,
  SCOPE_MODE,
  SCOPE_SOURCE,
  THREAD_EVENT,
  RANGE_REL,
  REQUEST_KIND,
  ROLE,
  VIA,
  DOC_KIND,
  ELEMENT_SYNC,
  SUGGEST_STATE,
  SAVE_MODE,
  LOCAL_LOGIN,
  ASSIGNEE_AGENT,
  LAYOUT_MODE,
  LAYOUT_BAND,
  BAND_STEP,
  CARD_DOT,
  SUGGEST_OFF,
  DIFF_FORMAT,
  OVERLAY_SIDE,
  RANGE_MODE,
  SEEN_STATE,
  VIEW_MODE,
  NOTIFY_STATE,
  STATUS_KIND,
  VERDICT_PLACE,
  STAMP_FORM,
  MARKDOWN_LIMIT,
};
