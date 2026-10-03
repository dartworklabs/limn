// The HTTP API's pin answers as the viewer reads them (docs/handbook/api.md; viewer.md §타입 검사). Types only.
// src/limn/viewer/tests/test_viewer_types.py holds these to the recorded answers in tests/data/contract_snapshot*.json:
// every field an answer carries is declared here with its JSON type, and a declared field the recorded flows never
// show must be one the server's record table (limn.pins.model.CORE_SHAPES) or thread entries define.

// Who did something: a person or the agent, as a pin, thread entry or person list names them.
interface Person {
  login: string;
  name?: string;
}

// One entry of a pin's thread: a reply (text) or a state record (ev: close, reopen, confirm, assign).
interface ThreadEntry {
  id: number;
  by: Person;
  at: string;
  text?: string;
  ev?: string;
  ref?: string;
  mentions?: string[];
}

// A figure pin's element (POST /api/pin `el`, docs/handbook/domain.md).
interface PinElement {
  id: string;
  path: string[];
  label?: string;
  part?: string;
  impl?: { file: string; lo: number; hi: number };
  frac?: number[];
}

// What a pin's text was anchored on when it was placed, to find it again after an edit.
interface PinAnchor {
  head: string;
  tail: string;
  head_off: number;
  tail_off: number;
}

// One line range a close says it changed (POST /close `changes`).
interface PinChange {
  file: string;
  lo: number;
  hi: number;
}

// Another open pin this one overlaps (`rel`), and how.
interface PinRelation {
  id: number;
  rel: string;
}

// A pin as GET /api/pins, /api/pins/<id> and /api/pins/dropped answer it. Which fields are present depends on the
// pin's kind (lines, region, figure) and state; read the state with pinState(p).
interface Pin {
  id: number;
  doc?: string;
  file?: string;
  name?: string;
  rel_path?: string;
  pdf?: string;
  page: number;
  lo?: number;
  hi?: number;
  raw_lo?: number;
  raw_hi?: number;
  frac?: number[];
  mark?: number[];
  mark_page?: number;
  kind?: string;
  scope?: string;
  via?: string;
  score?: number;
  quote?: string;
  pdf_build?: string;
  el?: PinElement;
  el_sync?: string;
  anchor?: PinAnchor;
  synced_at?: number;
  stale?: boolean;
  sync?: string;
  est?: boolean;
  note?: string;
  mentions?: string[];
  kind_req?: string;
  assignee?: string;
  addressed?: string[];
  fyi?: string[];
  rel?: PinRelation[];
  at?: string;
  author?: Person;
  rev?: number;
  edited_at?: string;
  edited_by?: Person;
  state?: string;
  done?: boolean;
  review?: boolean;
  done_at?: string;
  closed_by?: Person;
  close_reply?: string;
  close_ref?: string;
  changes?: PinChange[];
  changes_at?: string;
  confirmed_at?: string;
  confirmed_by?: Person;
  reopened_at?: string;
  reopened_by?: Person;
  claimed_at?: string;
  claimed_by?: Person;
  claim_ts?: number;
  claim_until?: number;
  eta_ts?: number;
  dropped_at?: string;
  dropped_by?: Person;
  expires_ts?: number;
  restored_at?: string;
  restored_by?: Person;
  thread?: ThreadEntry[];
}
