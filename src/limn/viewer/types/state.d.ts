// Shapes of the viewer's own screen state (docs/handbook/viewer.md §여러 문서 전환, 화면 상태의 소유자). Types only;
// none of this is stored or sent as it is.

// The open edit card (edit.js EDITOR.current): the pin it edits, its card element, the request's base revision, the
// range being edited with its ladder and snippet, the values it opened with (orig) to tell what changed.
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
  orig: { lo?: number; hi?: number; scope: string | null; note: string; kind_req: string; assignee: string };
  assignee: string;
  doc: string;
  region: boolean;
  pinEl: PinElement | null;
  page: number;
  quote: string;
  kind_req: string;
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
  fn: () => unknown;
}

// A message in context (notices.js, docs/handbook/viewer.md §알림 자리): what it says and how (a chip shows its short label),
// where it is drawn (place, and the banner host, the pin, list section and pin before it for an undo; away once a row's card
// has left), how long it lives, the chip it marks (dot), the hint topic, the duplicate keys of the status line, whether it is
// read out as an alert and comes first on the line (alert), whether its action's request is out (busy), and what runs when it
// leaves (gone). el is made once and moved.
interface Notice {
  n: number;
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
