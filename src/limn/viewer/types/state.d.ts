// Shapes of the viewer's own screen state (docs/handbook/viewer.md §여러 문서 전환, 화면 상태의 소유자). Types only;
// none of this is stored or sent as it is.

// The open edit card (edit.js EDITOR.current): the pin it edits, its card element, the request's base revision, the
// range being edited with its ladder and snippet, the values it opened with (orig) to tell what changed.
/** An active card keeps original values and copied mention hints so later changes can be saved against its baseline. */
interface EditCard {
  id: number;
  el: HTMLElement;
  base_rev: number;
  file?: string;
  name: string;
  lo?: number;
  hi?: number;
  scope: string | null;
  kind?: string;
  env: string | null;
  levels: Rung[];
  n_lines: number | null;
  snippet: string;
  orig: { lo?: number; hi?: number; scope: string | null; note: string; mentions: readonly string[]; kind_req: string; assignee: string };
  assignee: string;
  doc: string;
  region: boolean;
  pinEl: PinElement | null;
  page: number;
  quote: string;
  kind_req: string;
  sg: SuggestDraft;
  theirs?: string | null; // the note a rival edit wrote meanwhile (a 409): the card's note is not saved over it unless overwrite
  overwrite?: boolean; // the person chose [내 메모로 덮어쓰기] after seeing theirs
}

// A suggested edit being written (suggest.js; the composer's SG, an edit card's sg): whether its editor is on, the text it
// holds, the text it was filled from (base, null before the first fill) and the lines that base is (file, lo, hi), the
// suggestion the pin had when its edit card opened (had), the current text a 409 answered with and the lines it is
// (current), the lines being read now ('file:lo-hi', reading) and the last read that failed: its lines, whether it was
// a fill and why (fail).
interface SuggestDraft {
  on: boolean;
  text: string;
  base: string | null;
  file: string | null;
  lo: number;
  hi: number;
  had: PinSuggest | null;
  current: { text: string; file: string | null; lo: number; hi: number } | null;
  reading: string;
  fail: { key: string; fill: boolean; why: string } | null;
}

// The composer's selection (composer.js COMPOSE.current): the pick's answer plus what the composer chose on it - the
// ladder rung (scope) and its environment, the element the range follows (elSel), and the overlap it reports (rel).
interface Selection extends PickAnswer {
  scope?: string | null;
  env?: string | null;
  elSel?: PinElement | null;
  rel?: PickOverlap[];
}

// A pin's location being placed again (repick.js REPICK): the pin, where it was, the drawn box and the new candidate.
interface Repick {
  id: number;
  from: { lo?: number; hi?: number; page: number; region: boolean };
  box: HTMLElement | null;
  cand: PickAnswer | null;
}

/** A closed nonblank reply keeps its text and the recipient logins selected for tags that remain in that text. */
interface ReplyDraft {
  readonly text: string;
  readonly mentions: readonly string[];
}

// The open reply box (reply.js REPLY): its pin, its element, and whether the outcome toggle is flipped and which way.
interface ReplyBox {
  id: number;
  flip: boolean;
  toggle: string | null;
  el: HTMLElement;
}

// A message's one action (notices.js): its button's label (Korean, translated when drawn), its description and what it does;
// wait = it sends a request, and the message stays (busy) until that is answered (noticeAct).
interface NoticeAct {
  label: string;
  tip?: string;
  wait?: boolean;
  fn: (run?: NoticeRun) => unknown;
}

// What noticeAct tells an action that waits while it runs: away() = its answer is late (NOTICE_ACT_WAIT) and the person has
// put the focus somewhere since the press - the action then takes no focus.
interface NoticeRun {
  away(): boolean;
}

// A message in context (notices.js, docs/handbook/viewer.md §알림 자리): what it says and how (a chip shows its short label),
// where it is drawn (place, and the banner host, the pin, list section and pin before it for an undo; away once a row's card
// has left), how long it lives, the chip it marks (dot), the hint topic, the duplicate keys of the status line, whether it is
// read out as an alert and comes first on the line (alert), whether its action's request is out (busy), the error source it
// stands for (one entry each), whether it offers an undo (never evicted), whether a mouse is on it (hover) and its window is
// held (held), and what runs when it leaves (gone). el is made once and moved.
interface Notice {
  n: number;
  quiet: boolean; // said when it came (a save chip's undo moved to the line): not read out again
  place: string;
  host: string;
  pin: number | null;
  sec: string;
  prev: number | null;
  kind: string;
  title: string;
  desc: string;
  label: string;
  away: boolean;
  act: NoticeAct | null;
  literal: boolean;
  keys: string[];
  rank: number;
  at: number;
  life: string;
  dot: string;
  topic: string;
  save: boolean;
  pending: boolean;
  alert: boolean;
  busy: boolean;
  source: string;
  undo: boolean;
  hover: boolean;
  held: boolean;
  timer: ReturnType<typeof setTimeout> | undefined;
  gone: (() => void) | null;
  el: HTMLElement | null;
}

// A send held back behind its undo (notices.js deferred()): run sends it now, cancel takes it back unsent; note is its undo.
interface Deferred {
  note: Notice | null;
  run: () => void;
  cancel: () => void;
}

// The pin the changes view was opened for (revisions.js REV.target), and how the commit was chosen for it (via, and
// tokOf, the commit id its close reference names).
interface RevTarget {
  id: number;
  file: string;
  name: string;
  lo?: number;
  hi?: number;
  page: number;
  ref: string;
  region: boolean;
  commit?: string;
  via?: string;
  hit?: boolean;
  near?: boolean;
  tokOf?: string;
}

// The changes view's quick range (revisions.js REV.range, issue #188): mode is a RANGE_MODE value, start and end the
// commits it spans (start the older; equal for one commit), endSet whether the end was pressed after the start.
interface RevRange {
  mode: string;
  start: string;
  end: string;
  endSet: boolean;
}

// The last-seen commit of a document in this browser (localStorage limnRevSeen): its id and when, as MM-DD HH:MM.
interface RevSeen {
  id: string;
  at: string;
}

// The target a verdict pin is about (verdict.js verdictTargetOf): a key pins about one thing share, whether it is a page's
// whole target and its page, and for exact lines whether the pin is open (its lines matched to the text now) and its anchor.
interface VerdictTarget {
  key: string;
  whole: boolean;
  page: number;
  lines: { open: boolean; anchor: string | null } | null;
}

// A document's verdict order (verdict.js verdictOrder): its resolved targets' pins, newest first, and every resolved pin's
// current verdict by pin id.
interface VerdictOrder {
  groups: Map<string, { whole: boolean; page: number; pins: Pin[] }>;
  cur: Map<number, Pin>;
}
