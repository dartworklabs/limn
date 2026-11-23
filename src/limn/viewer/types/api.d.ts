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

// A LaTeX line pin's suggested edit (`suggest`, docs/handbook/api.md §제안 수정 (`suggest`)): base, the lines lo..hi the
// author saw, and text, what replaces them - each joined with "\n", no trailing newline; an empty text deletes the lines.
interface PinSuggest {
  base: string;
  text: string;
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
  // Where a line pin's own lines print on the build on screen, the pieces a pick and a snippet answer for the same
  // lines (ADR-0049). Computed on read like mark/mark_page; absent when there is no answer, never empty. A figure
  // pin's mark comes from its element map instead, so the two never meet on one pin.
  boxes?: MarkPiece[];
  kind?: string;
  scope?: string;
  via?: string;
  score?: number | null;
  fill?: number;
  rival?: boolean;
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
  suggest?: PinSuggest;
  suggest_state?: string;
  verdict?: string;
  // A verdict pin a newer verdict pin about the same target supersedes: that pin's number (ADR-0023). Computed on read;
  // the viewer's card marker still counts the order itself.
  superseded_by?: number;
}

// The person this request is answered for (meta and /api/people `me`), with the role the server gives them.
interface Me {
  login: string;
  name?: string;
  pic?: string;
  role: string;
}

// One person recorded on a real change or added as a member, or who wrote on a pin (GET /api/people). The server
// always fills name, with the login when the person has none (limn.security.people_store known_people).
interface PersonSeen {
  login: string;
  name: string;
  pic?: string;
  last_seen?: string;
  role: string;
}

// GET /api/people.
interface PeopleAnswer {
  people: PersonSeen[];
  me: Me;
}

// One commit of GET /api/revisions (newest first): its full id, commit date, subject, author name, ISO 8601 commit time and
// full parent ids (first parent first; none for a root commit). author, time and parents since issue #188.
interface RevisionRow {
  id: string;
  date: string;
  subject: string;
  author: string;
  time: string;
  parents: string[];
}

// One page image of the current build (meta `pages`), with its size in PDF points. On a figure document whose map loads,
// what the map says of the page: its figure (root element id), its title when the map has one, verdict - always
// false - when the page takes no verdict, and on a page with a figure body (<figure>/@figure) the body's top edge and the
// lowest bottom edge of the elements above it, as page fractions (docs/handbook/viewer.md §그림 쪽 도착).
interface PageImage {
  name: string;
  pt_w: number;
  pt_h: number;
  figure?: string;
  title?: string;
  verdict?: boolean;
  figure_top?: number;
  figure_above?: number;
}

// A figure document's two builds in GET /api/revisions (`overlay`): the build on screen and the build before it, with their
// page images; prev_build is null and prev_pages empty when the previous build is not kept.
interface RevisionOverlay {
  build: string;
  pages: PageImage[];
  prev_build: string | null;
  prev_pages: PageImage[];
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

// One verdict word a document declares (`verdicts.choices`, docs/handbook/api.md §판정 낱말 파일): the key a pin stores,
// the button's name and whether it takes two presses.
interface VerdictChoice {
  key: string;
  label: string;
  confirm: boolean;
}

// A document's verdict words (GET /api/docs and the full GET /api/meta `verdicts`): page is whether its pages get a page
// verdict line (a figure document or a view-only PDF whose word file says so; never a LaTeX document).
interface DocVerdicts {
  page: boolean;
  choices: VerdictChoice[];
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
  verdicts?: DocVerdicts;
  verdicts_error?: string;
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
  // The server knows a write by its idempotency key (POST /api/pin idem); absent on an older Limn.
  pin_idem?: boolean;
  // The server counts a build hold per holder (POST /api/hold holder); absent on an older Limn.
  hold_holder?: boolean;
  ev_seq: number;
  // With a cursor (ev=<seq>): the events after it addressed to the identity asking (PinEvent).
  events?: PinEvent[];
  n_open?: number;
  n_done?: number;
  n_review?: number;
  verdicts?: DocVerdicts;
  verdicts_error?: string;
  docs?: DocEntry[];
  src_sig?: string;
}

// An event of the light poll addressed to the identity asking (GET /api/meta?light=1&ev=<seq>,
// limn/collaboration/events.py make_event, EventLog.emit and events_since): its type is one of the notified ones, to
// holds the logins it is for, doc_name is its document's name, kind_req the pin's request kind, msg the thread entry
// it says, seq/at/ts its number and stamps.
interface PinEvent {
  seq: number;
  type: 'mention' | 'review_requested' | 'replied' | 'reopened' | 'assigned' | 'dropped';
  pin: number;
  doc: string;
  doc_name: string;
  to: string[];
  by: Person;
  kind_req?: string;
  msg?: number;
  excerpt?: string;
  at: string;
  ts: number;
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
  unchanged?: boolean;
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
  unchanged?: boolean;
}

// One piece of the mark a rung's lines draw: the page it is on (1-based) and its box as page fractions, [x, y, w, h]
// from the page's top left.
interface MarkPiece {
  page: number;
  frac: number[];
}

// One rung of a range ladder (POST /api/pick `levels`, GET /api/snippet?levels=1): the lines it covers and their
// snippet, the environment for an environment rung, the element for a figure's rung, the rungs it replaced, and on a
// traced pick how much of the drag is in its lines (score, 0-1; null when there was nothing to weigh). boxes is where
// those lines print on the build being read - absent when there is no answer for them, never empty - which a pick
// sends for its default rung alone and a snippet for every rung (docs/adr/0049-pin-marks-follow-the-range.md).
interface Rung {
  level: string;
  lo: number;
  hi: number;
  n: number;
  label: string;
  snippet: string;
  env?: string | null;
  el?: PinElement;
  merged?: string[];
  score?: number | null;
  boxes?: MarkPiece[];
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
  score?: number | null;
  fill?: number;
  rival?: boolean;
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
  path_names?: string[];
  doc?: string;
  view_only?: boolean;
  pdf?: string;
  n_chars?: number;
}

// A refusal's body (limn.web.errors.HTTPError, docs/handbook/api.md §오류 응답): the Korean message and its stable
// reason code. A refusal a caller expects (api() options.expect) is read as its endpoint's ApiRefusals entry.
interface ErrorBody {
  error: string;
  reason: string;
}

// A 409 on one pin that carries the pin as stored (POST /api/pins/{id}/edit and /confirm): reason conflict (someone
// changed it), done or open (its state forbids the change; detail says why), or suggest_base_changed for an edit whose
// suggested edit no longer fits its lines (current: what they read now).
interface PinConflict {
  error: string;
  reason: string;
  pin: Pin;
  detail?: string;
  current?: string;
}

// A 409 of POST /api/pin: idem_unknown (no pin was made with that idempotency key), or suggest_base_changed with the
// lines' current text.
interface SaveConflict {
  error: string;
  reason: string;
  current?: string;
}

// The 413 of GET /api/source (source_too_large): the file's size and the limit, in bytes; no lines.
interface SourceTooLarge {
  error: string;
  reason: string;
  bytes: number;
  limit: number;
}

// The 409 of POST /api/rebuild while the document is building already: busy, with state running for ?async=1 and ok
// false without it.
interface RebuildBusy {
  busy: boolean;
  state?: string;
  ok?: boolean;
}

// POST /api/rebuild?async=1's answer when the build started (202).
interface RebuildStarted {
  state: string;
}

// POST /api/pick's 200 for a selection that is not traced (PICK_REFUSALS) or names a page directory that is gone
// (pdf_build_gone true).
interface PickRefusal {
  error: string;
  reason: string;
  pdf_build_gone?: boolean;
}

// GET /api/snippet: the lines lo..hi of a manuscript file - its path and name, how many lines the range and the file
// have, and the numbered snippet; with ?levels=1 the range ladder and its default rung, every rung carrying where its
// own lines print (Rung.boxes), and with ?text=1 the lines' exact text for a range short enough to take a suggested
// edit. boxes_build is the build those boxes were measured against - the page directory on screen as the server
// answered, which a build finishing inside the round trip makes a later one than this page is showing - and comes
// only for a request that asked for marks (?levels=1&boxes=1) and had a build with pages to measure them against.
interface SnippetAnswer {
  file: string;
  name: string;
  lo: number;
  hi: number;
  n: number;
  n_lines: number;
  snippet: string;
  levels?: Rung[];
  default_level?: string;
  boxes_build?: string;
  text?: string;
}

// GET /api/source: the source of a document the viewer draws itself (Markdown, text) - its document key, the file a
// pin on it stores, the stamp read before the lines, the lines as the server numbers them, and the line ends among them
// that are neither LF nor CRLF, by name with their counts.
interface SourceAnswer {
  doc: string;
  file: string;
  src_mtime: number;
  lines: string[];
  line_ends: Record<string, number>;
}

// One row of GET /api/outline-labels: a heading's LaTeX number, title, printed page, sectioning level and anchor.
interface OutlineLabelRow {
  number: string;
  title: string;
  page: string;
  level: string;
  anchor: string;
}

// GET /api/outline-labels: the page directory on screen and the outline rows of the .aux it published.
interface OutlineLabelsAnswer {
  build: string;
  labels: OutlineLabelRow[];
}

// GET /api/version: the application's name and installed version.
interface VersionAnswer {
  name: string;
  version: string;
}

// POST /api/hold: the build asked about and when it is held to over all its holders, null once none holds it.
interface HoldAnswer {
  build: string;
  until: string | null;
}

// GET /api/pins/{id}.
interface PinAnswer {
  pin: Pin;
}

// GET /api/pins/dropped: the Trash.
interface DroppedAnswer {
  dropped: Pin[];
}

// POST /api/pin: the new pin's number, with replay true when its idempotency key already made it.
interface PinSaved {
  id: number;
  replay?: boolean;
}

// POST /api/pins/{id}/edit, /restore: the pin as stored after the change.
interface PinChanged {
  ok: boolean;
  pin: Pin;
}

// POST /api/pins/{id}/close, /reopen, /confirm: whether the pin was found, and then the pin and its state.
interface PinStateAnswer {
  ok: boolean;
  pin: Pin | null;
  state: string | null;
}

// POST /api/pins/{id}/reply: whether the pin was found, and then the pin, the new thread entry, the pin's state and
// whether the reply reopened it.
interface PinReplyAnswer {
  ok: boolean;
  pin: Pin | null;
  msg: ThreadEntry | null;
  state: string | null;
  reopened: boolean;
}

// POST /api/pins/{id}/unclaim: whether the pin was found, and then the pin.
interface PinUnclaimed {
  ok: boolean;
  pin: Pin | null;
}

// POST /api/pins/{id}/drop: whether the pin was found.
interface PinDropped {
  ok: boolean;
}

// POST /api/pins/{id}/purge: the number of the pin deleted for good.
interface PinPurged {
  ok: boolean;
  purged: number;
}

// GET /api/revisions: the document's manuscript commits, newest first, or available false when it has no history
// (reason too_many_files with the limit when it has too many history files); a page of them (?before=, ?limit=) says
// whether more follow, and a figure document adds its two builds (overlay).
interface RevisionsAnswer {
  available: boolean;
  revisions: RevisionRow[];
  more?: boolean;
  reason?: string;
  limit?: number;
  overlay?: RevisionOverlay;
}

// Which of a commit's hunks belong to one pin (GET /api/revision-diff?pin= `scope`) when the pin owns part of the
// commit: the pin, where its hunks were found (source), how many are the pin's and how many are not, the two patches
// and whether each was cut.
interface RevisionPinScope {
  pin: number;
  mode: 'pin';
  source: string;
  hunks: number;
  other: number;
  diff: string;
  other_diff: string;
  truncated: boolean;
  other_truncated: boolean;
}

// GET /api/revision-diff?pin= `scope` when the pin owns the whole commit or none of it: the counts without patches.
interface RevisionCommitScope {
  pin: number;
  mode: 'commit';
  source: string;
  hunks: number;
  other: number;
}

// One file of a range's diff (GET /api/revision-diff?base= `files`): its path, the path it was renamed from, and the
// lines added and deleted (null for a binary file).
interface RangeFile {
  path: string;
  old_path?: string;
  add: number | null;
  del: number | null;
}

// GET /api/revision-diff: a commit's unified diff and whether it was cut; with ?pin= the pin's scope; with ?base= the
// range's old side, the merge base when that was used, how many commits the range holds and which, and its files.
interface RevisionDiff {
  id: string;
  diff: string;
  truncated: boolean;
  scope?: RevisionPinScope | RevisionCommitScope;
  base?: string;
  merge_base?: string;
  commits?: number;
  commit_ids?: string[];
  files?: RangeFile[];
}

// One side of GET /api/revision-source: the file's lines, and where git's lines start among them when the two count
// lines differently; or, for a side that cannot be drawn, why (with the size and limit for source_too_large).
interface RevisionSide {
  lines?: string[];
  git_line_starts?: number[][];
  reason?: string;
  bytes?: number;
  limit?: number;
}

// GET /api/revision-source: a browser-drawn document's file on the two sides of a commit (or of a range with ?base=):
// the commit, the old side's commit (null for a root commit), the merge base when that was used, the file's path in
// the repository, and each side (null where the file is not there).
interface RevisionSources {
  id: string;
  base: string | null;
  merge_base?: string;
  path: string;
  old: RevisionSide | null;
  new: RevisionSide | null;
}

// GET and POST /api/revision-build: a comparison PDF's job and its state (idle, running, ready, error) with its
// warnings and, failed, the error and its reason; a pin's comparison adds its scope fields, a range compared from its
// merge base adds that.
interface RevisionBuildStatus {
  job_id: string;
  base: string;
  head: string;
  engine: string;
  state: string;
  warnings: string[];
  error: string | null;
  reason: string | null;
  scope?: string;
  pin?: number;
  source?: string;
  hunks?: number;
  other?: number;
  merge_base?: string;
}

// ---------------------------------------------------------------- access management (owner only)
// One row of people.json as GET /api/access shows it: the login, the name to read, the role and, when recorded, when
// the person was last seen.
interface AccessMember {
  login: string;
  name: string;
  role: string;
  last_seen?: string;
}

// A transition row the owner cannot change: an owner's or an agent's. It also says whether --allow lets that login in
// today, so the screen can show what the switch keeps.
interface AccessFixedMember {
  login: string;
  name: string;
  role: string;
  last_seen?: string;
  admitted_today: boolean;
}

// The transition screen GET /api/access carries while the instance is not managed: who gets in today, the rows the
// owner may check (viewer/editor) and the rows that stay whatever is checked.
interface AccessTransition {
  admitted_today: string[];
  settable: AccessMember[];
  fixed: AccessFixedMember[];
}

// One person of the tailnet this server can see who is not a member yet.
interface TailnetUser {
  login: string;
  name?: string;
  pic?: string;
}

// The tailnet directory the local daemon answered with: the people who could be let in, whether the list may be
// incomplete and, when it could not be read, why (tailscaled_not_found and the like).
interface AccessTailnet {
  users: TailnetUser[];
  partial: boolean;
  reason?: string;
}

// GET /api/access: whether the viewer manages admission, who is a member, what the run's arguments say, the transition
// screen while it is unmanaged, and who could be let in.
interface AccessView {
  managed: boolean;
  managed_at?: string;
  managed_by?: string;
  unmanaged_admits_everyone: boolean;
  args: { allow: string[]; members_only: boolean };
  members: AccessMember[];
  transition?: AccessTransition;
  tailnet: AccessTailnet;
}

// POST /api/members/add, /role and /remove: the row as it now stands; null for a remove of a login that was no member.
interface MemberChanged {
  ok: boolean;
  member: AccessMember | null;
}

// POST /api/access/managed: the flag as it now stands and what the one transaction did to the member rows.
interface ManagedChanged {
  ok: boolean;
  managed: boolean;
  added: string[];
  removed: string[];
  changed: string[];
  kept: string[];
  newly_admitted: string[];
}

// The answer each endpoint the viewer calls gives, by its method and path ({id}: a pin's number). api() takes the key,
// builds the request from it and answers this type; the query does not change it, so a field only some queries bring
// is optional. src/limn/viewer/tests/test_viewer_types.py holds each type to the real handler.
interface ApiAnswers {
  'GET /api/meta': Meta;
  'GET /api/docs': DocsAnswer;
  'GET /api/people': PeopleAnswer;
  'GET /api/build': BuildStatus;
  'POST /api/rebuild': RebuildAnswer | RebuildStarted;
  'POST /api/hold': HoldAnswer;
  'GET /api/outline-labels': OutlineLabelsAnswer;
  'GET /api/source': SourceAnswer;
  'GET /api/version': VersionAnswer;
  'GET /api/snippet': SnippetAnswer;
  'POST /api/pick': PickAnswer | PickRefusal;
  'GET /api/pins': Pin[];
  'GET /api/pins/dropped': DroppedAnswer;
  'GET /api/pins/{id}': PinAnswer;
  'POST /api/pin': PinSaved;
  'POST /api/pins/{id}/edit': PinChanged;
  'POST /api/pins/{id}/close': PinStateAnswer;
  'POST /api/pins/{id}/reopen': PinStateAnswer;
  'POST /api/pins/{id}/confirm': PinStateAnswer;
  'POST /api/pins/{id}/reply': PinReplyAnswer;
  'POST /api/pins/{id}/unclaim': PinUnclaimed;
  'POST /api/pins/{id}/drop': PinDropped;
  'POST /api/pins/{id}/restore': PinChanged;
  'POST /api/pins/{id}/purge': PinPurged;
  'GET /api/revisions': RevisionsAnswer;
  'GET /api/revision-diff': RevisionDiff;
  'GET /api/revision-source': RevisionSources;
  'GET /api/revision-build': RevisionBuildStatus;
  'POST /api/revision-build': RevisionBuildStatus;
  'GET /api/access': AccessView;
  'POST /api/members/add': MemberChanged;
  'POST /api/members/role': MemberChanged;
  'POST /api/members/remove': MemberChanged;
  'POST /api/access/managed': ManagedChanged;
}

// The refusals a caller may hand api() in options.expect, by endpoint and status, with the body each answers: api()
// gives such a refusal back as an answer instead of throwing it.
interface ApiRefusals {
  'POST /api/rebuild': { 409: RebuildBusy };
  'GET /api/source': { 413: SourceTooLarge };
  'GET /api/snippet': { 400: ErrorBody };
  'POST /api/pin': { 409: SaveConflict };
  'POST /api/pins/{id}/edit': { 409: PinConflict };
  'POST /api/pins/{id}/confirm': { 409: PinConflict };
  'POST /api/members/add': { 400: ErrorBody; 409: ErrorBody };
  'POST /api/members/role': { 400: ErrorBody; 409: ErrorBody };
  'POST /api/members/remove': { 400: ErrorBody; 409: ErrorBody };
  'POST /api/access/managed': { 400: ErrorBody; 409: ErrorBody };
}

// An endpoint the viewer calls (ApiAnswers).
type ApiEndpoint = keyof ApiAnswers;
