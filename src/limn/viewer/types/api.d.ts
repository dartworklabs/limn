// The HTTP API's answers as the viewer reads them (docs/handbook/api.md; viewer.md §타입 검사). Types only.
// src/limn/viewer/tests/test_viewer_types.py holds these to the server: the pin shapes to the recorded answers in
// tests/data/contract_snapshot*.json (a declared field they never show must be a server record field), the document
// and build answers to what the real handler answers in a few set-up states, and the sync records to what the
// server's own producers return. Every field an answer carries must be declared here with its JSON type.

// Who did something: a person or the agent, as a pin, thread entry or person list names them.
interface Person {
  login: string;
  name?: string;
  pic?: string;
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

// The person this request is answered for (meta and /api/people `me`), with the role the server gives them.
interface Me {
  login: string;
  name?: string;
  pic?: string;
  role: string;
}

// One person who opened this viewer or wrote on a pin (GET /api/people).
interface PersonSeen {
  login: string;
  name?: string;
  pic?: string;
  last_seen?: string;
  role: string;
}

// GET /api/people.
interface PeopleAnswer {
  people: PersonSeen[];
  me: Me;
}

// One page image of the current build (meta `pages`), with its size in PDF points.
interface PageImage {
  name: string;
  pt_w: number;
  pt_h: number;
}

// One LaTeX error of a build: the manuscript line when the log names one.
interface LatexError {
  line: number | null;
  msg: string;
}

// A pull of remote main (a build's `pull`, limn.sync.rules.pull_record).
interface PullRecord {
  state: string;
  reason: string | null;
  head_before: string | null;
  head_after: string | null;
}

// The remote-main watch (meta `sync`): only `state` without --git-pull; the rest once a round has run.
interface SyncStatus {
  state: string;
  reason?: string | null;
  checked_at?: string | null;
  head_before?: string | null;
  head_after?: string | null;
}

// A build in progress or the last one's state (meta `build`, a document's `build`).
interface BuildProgress {
  state: string;
  phase: string | null;
  started_at?: string | null;
}

// The last finished build (meta `last_build`, /api/build `last`).
interface LastBuild {
  state: string | null;
  errors: LatexError[];
  finished_at: string | null;
  seq: number;
  head?: string | null;
  pull?: PullRecord | null;
}

// One document of the run (GET /api/docs `docs`, meta `docs` when there are several).
interface DocEntry {
  key: string;
  name: string;
  kind: string;
  view_only: boolean;
  path: string;
  main: string;
  stale_build: boolean;
  src_mtime: number;
  building: boolean;
  build: BuildProgress;
  build_seq: number;
  last_state: string | null;
  pages_build: string;
  n_pages: number;
  n_open: number;
}

// GET /api/docs.
interface DocsAnswer {
  docs: DocEntry[];
  default: string;
  multi: boolean;
  other_open: number;
}

// GET /api/meta (light=1 leaves the n_* counts out; docs and src_sig come with several documents).
interface Meta {
  pages: PageImage[];
  built_at: string;
  head: string;
  main: string;
  pins_md: string;
  state_dir: string;
  me: Me;
  label: string;
  accent: string;
  repo: string | null;
  building: boolean;
  sync: SyncStatus;
  doc: string;
  doc_name: string;
  kind: string;
  view_only: boolean;
  multi: boolean;
  stale_build: boolean;
  src_age_s: number;
  src_mtime: number;
  build_src_mtime: number | null;
  pages_build: string;
  pins_rev: string;
  build_seq: number;
  last_build: LastBuild;
  build: BuildProgress;
  ev_seq: number;
  n_open?: number;
  n_done?: number;
  n_review?: number;
  docs?: DocEntry[];
  src_sig?: string;
}

// A running render's count: page images written of the PDF's pages (GET /api/build `progress`).
interface PagesDrawn {
  done: number;
  total: number;
}

// GET /api/build (log=1 keeps the whole log tail). progress is null outside a running render and absent from an older
// server.
interface BuildStatus {
  state: string;
  phase: string | null;
  progress?: PagesDrawn | null;
  started_at: string | null;
  last_s: number | null;
  pages: number;
  errors: LatexError[];
  log_tail?: string;
  built_at: string | null;
  seq: number;
  finished_at: string | null;
  last: LastBuild | null;
  head: string | null;
  pull: PullRecord | null;
  elapsed_s: number;
}

// POST /api/rebuild's answer once the build has run (`pull` only when the run pulls remote main first).
interface RebuildAnswer {
  ok: boolean;
  state: string;
  errors: LatexError[];
  log?: string;
  elapsed_s: number;
  src_mtime: number;
  src_hash: string | null;
  head: string;
  build: string;
  pages: number;
  pull?: PullRecord | null;
}

// One rung of a range ladder (POST /api/pick `levels`, GET /api/snippet?levels=1): the lines it covers and their
// snippet, the environment for an environment rung, the element for a figure's rung, and the rungs it replaced.
interface Rung {
  level: string;
  lo: number;
  hi: number;
  n: number;
  label: string;
  snippet: string;
  env?: string;
  el?: PinElement;
  merged?: string[];
}

// An open line pin a not-yet-saved range overlaps (POST /api/pick `overlaps`), and how.
interface PickOverlap {
  id: number;
  lo: number;
  hi: number;
  rel: string;
}

// POST /api/pick's answer for a drag that was placed: lines traced in a LaTeX source (file, lines, ladder), an element
// of a figure's map (the same plus el), or a region of a view-only PDF or a figure that fell back (doc, pdf, n_chars).
interface PickAnswer {
  file?: string;
  name: string;
  page: number;
  lo?: number;
  hi?: number;
  raw_lo?: number;
  raw_hi?: number;
  kind: string;
  via?: string;
  score?: number;
  warn: string;
  n_lines?: number;
  snippet?: string;
  frac: number[];
  quote: string;
  levels?: Rung[];
  default_level?: string;
  overlaps: PickOverlap[];
  pdf_build: string;
  el?: PinElement;
  doc?: string;
  view_only?: boolean;
  pdf?: string;
  n_chars?: number;
}
