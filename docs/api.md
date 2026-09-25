# HTTP API details

Open this when the short table in [`SKILL.md`](../skill/SKILL.md) isn't enough. It covers the full endpoint list, editing/closing/claiming/overlapping pins, record schemas, and the `<state_dir>/pins.md` format. Rebuilds, auto-sync, and position estimation are in [build-sync.md](build-sync.md); Host/Origin checks are in [operations.md](operations.md) §Host/Origin checks.

## Request format and boundaries

The body must be a JSON object of at most 1 MiB with `Content-Type: application/json` (otherwise `400`/`413`/`415`). A POST with no body (an agent's `curl -X POST …/close`) is fine without headers. Error responses are always `{"error": "<Korean message>"}` JSON, and unexpected exceptions also come back as `500` JSON. Existing paths keep their contract; new fields and paths were only ever added, not changed.

- The server **always reads the body to the full Content-Length before sending any response**, and closes the connection after an error (`4xx`/`5xx`). A request with `Transfer-Encoding` gets `400`. If the body is cut off shorter than Content-Length, the request gets `400` and nothing happens (including `/api/clear`). This matters because an unread body would otherwise be interpreted as the next request on the same keep-alive connection, which would bypass `--allow` and author attribution — `tailscale serve` reuses backend connections.
- A cross-origin `Origin` or an unrecognized `Host` gets `403` — see [operations.md](operations.md) §Host/Origin checks for the rules and the reasoning.
- The socket timeout is 30 seconds — this closes connections that stall mid-body and idle keep-alives (it is unrelated to how long an actual long-running operation such as a rebuild takes).

## Document parameter (`doc=`)

An instance started with multiple documents (`--doc`, see [operations.md](operations.md) §Multiple documents) accepts `doc=<key>` on the paths that touch a document — `GET /api/meta`·`/api/build`·`/pdf`·`/pages/<page>`·`/api/snippet`·`/api/overlaps`·`/api/pins` (filters to that document's pins), `POST /api/pick`·`/api/pin`·`/api/rebuild`. POST accepts `doc` in the query string or the JSON body; if both are present and disagree, `400`. If omitted, it means the first document. One exception: `POST /api/pin` with `file` but no `doc` (an agent's `curl`) infers the document as whichever configured LaTeX document's build root most deeply contains that file. An unknown key gets `404 {error, docs:[key…]}` — it never silently falls back to the first document (that would attach the pin to the wrong document). Paths that address a pin by id (`/api/pins/{id}/…`) don't need `doc` — the pin's document is already in its record. A single-document instance can ignore `doc` entirely (the key is `main`).

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/version` | `{"name":"limn","version":<string>}` — matches `limn serve --version`. Useful for confirming which installed version an instance is running |
| `GET` | `/api/meta` | `pages` (page list), `built_at`, `head` (manuscript commit), `main` (top-level `.tex` filename), `label`·`accent`·`repo` (this instance's label, accent color, and git origin URL — see operations.md §Running multiple manuscript instances at once), `n_open`·`n_done`, `pins_md`·`state_dir` (absolute path), `me` (the current requester), `building` (a rebuild is in progress), `stale_build` (has the manuscript `.tex` changed since this PDF was built), `src_mtime`·`build_src_mtime`·`src_age_s`·`pins_rev` (build-sync §Auto-sync), `pages_build` (the build id shown right now = the `pages.cur` value), `build_seq` (count of finished builds)·`last_build:{state,errors,finished_at,seq}`·`build:{state,phase,started_at}` (build-sync §Asynchronous rebuild), `doc`·`doc_name`·`kind`·`view_only`·`multi` (§Document parameter). With multiple documents it also carries `docs` (the `/api/docs` entries minus `n_open`) and `src_sig` (each document's `src_mtime` concatenated into one string — so the viewer re-reads the list even when a *different* document's manuscript changed) — included in the light variant too |
| `GET` | `/api/docs` | Document list: `{docs:[{key,name,kind:"tex"\|"pdf",view_only,path,main,n_open,stale_build,building,build:{state,phase},build_seq,last_state,pages_build,n_pages,src_mtime}], default, multi, other_open}`. Read-only for pins (no sync write). `other_open` = open-pin count for document keys not present in the current configuration |
| `GET` | `/api/revisions?doc=<key>` | The last 12 Git commits that touched `.tex`·`.bib`·`.sty`·`.cls`·`.bst` files under the selected main `.tex`'s folder → `{available,revisions:[{id,date,subject}]}`. `available:false` if it's not a Git repository or the document is a view-only PDF |
| `GET` | `/api/revision-diff?doc=<key>&commit=<40-char SHA-1>` | The actual unified diff for a commit from the list above → `{id,diff,truncated}`. Only includes manuscript extensions inside the selected main file's folder, capped at 256 KiB. A malformed id gets `400`; an id outside the list, or a view-only PDF, gets `404` |
| `GET` | `/api/outline-labels?doc=<key>` | The table of contents preserved alongside the `.aux` for the current PDF → `{build,labels:[{number,title,page,level,anchor}]}`. Numbers are only attached when they line up with the PDF.js outline's title, hierarchy, and order. `page` is the printed page-number string (roman numerals possible), not the physical PDF page index. An existing build without a `.aux` returns an empty array; unsupported complex TeX titles get empty `number`/`title` placeholders |
| `POST` | `/api/revision-build` | `{commit,doc?}`. Starts an asynchronous build of the parent-of-selected-commit → selected-commit comparison PDF. `202 {state:"running",job_id,base,head,engine,warnings,error,reason}`; a cached success returns `200 {state:"ready",…}`. `doc` also accepted in the query string. Any other field is `400` |
| `GET` | `/api/revision-build?doc=<key>&commit=<40-char SHA-1>` | Polls the same state schema. `state` is `idle` (never run / expired), `running`, `ready`, or `error`. `error` is a description, `reason` is an error classification. Rechecks the current document's recent commit list every call |
| `GET` | `/api/revision-pdf?doc=<key>&commit=<40-char SHA-1>` | The PDF for a successful comparison of the same pair. Unfinished, failed, or expired gets `404` — it is never replaced with the current manuscript PDF. A read-only result, independent of the current page/SyncTeX/pin coordinates |
| `GET` | `/api/meta?light=1` | Same as above but without `n_open`·`n_done` and **no write side effects** (does not call `sync`/`live_pins`) — polling only. build-sync §Auto-sync |
| `GET` | `/api/build` | `{state:"idle\|running\|ok\|ok_errors\|fail", phase:"pull\|copy\|latex\|render"\|null, started_at, finished_at, seq, last, elapsed_s, last_s, pages, errors:[{line,msg}], log_tail, built_at, head, pull}` — build-sync §Asynchronous rebuild. Even after a server restart, the last build result (`state`·`errors`·`log_tail`·`seq`·`head`·`pull`) is restored from `builds.json`. `log_tail` follows build-sync §Trimming agent responses (dropped entirely when `state=="ok"`, otherwise 40 lines, or the full tail with `?log=1`) |
| `GET` | `/pins.md` | The remote agent entry point — returns the same content as `<state_dir>/pins.md` as `text/markdown; charset=utf-8` (goes through the same sync path as `GET /api/pins` before rendering). Only the base URL in the instructions line changes to match the request `Host`: `https://<Host as sent>` if `Host` is `*.ts.net`, otherwise the usual `http://127.0.0.1:<port>` for loopback. The on-disk `<state_dir>/pins.md` always uses the loopback base. Host/Origin checks are the same as any other `GET` — §Remote agent entry point |
| `POST` | `/api/pick` | Drag coordinates (`page`, `x0`, `y0`, `x1`, `y1`, optional `frac` = a list of 4 numbers `[x, y, w, h]` as a fraction of the page — any other shape is `400`; optional `pdf_build` = the build id shown on screen when the drag happened — reverse-maps against that build's PDF. If that build was already removed: `200 {error, pdf_build_gone:true}`; a malformed shape is `400`) → `{file, name, lo, hi, raw_lo, raw_hi, kind, via, score, warn, snippet, frac, levels, default_level, n_lines, quote, overlaps, pdf_build}`. `quote` is the selected text, whitespace-normalized and cut to 60 characters; `overlaps` is the overlap with the same file's open pins (§Overlapping pins). A bad input gets `400`; a failed reverse mapping gets `200 {error}`. `levels`·`via`·`score` are explained in [design.md](design.md) §Scope ladder and §Why reverse mapping uses two paths |
| `GET` | `/api/pins` | The list of open pins (JSON). Each record gets `rev`·`rel` (§Overlapping pins) and `est` (boolean, build-sync §Position estimation) filled in — `rel`·`est` are computed fields and are not stored. `?all=1` includes closed pins too |
| `GET` | `/api/pins/{id}` | A single pin `{pin}` — same shape as one item from `GET /api/pins?all=1` (full thread, computed fields included). `404` if it doesn't exist |
| `POST` | `/api/pins/{id}/reply` | Adds a reply `{"text", "mentions"?}` → `{ok, pin, msg}` — §Threads |
| `POST` | `/api/pins/{id}/confirm` | Pending review → done (people only, otherwise `403`) → `{ok, pin, state}` — §Pending review |
| `GET` | `/sw.js` | The service worker for browser notifications (`text/javascript; charset=utf-8`, `Cache-Control: no-cache`, scope `/`). Has no `fetch` handler — it never caches app data |
| `GET` | `/api/people` | @mention candidates: `{people:[{login,name,pic?,last_seen?}], me}` — §@mentions, people, and events. Read-only |
| `GET` | `/api/pins/dropped` | The list of dropped pins → `{dropped: [...]}`, dumping `pins.dropped.jsonl` as-is, ordered by `dropped_at` (no computed fields, no write side effects). Used by the viewer's collapsed "N dropped pins" list, and by the notification logic that distinguishes "done" from "dropped" when a pin vanishes from the open list (build-sync §Auto-sync) |
| `GET` | `/pdf?build=<pages_build>` | Returns the PDF that matches that build's page images (`pages-<build>/<main>.pdf`) as `application/pdf` (`Cache-Control: private, max-age=600`). Used by the viewer's vector rendering ([design.md](design.md) §Vector rendering). Omitting `build` means the current build. A malformed name, an already-removed build, or a directory with no PDF gets `404 {error, pdf_build_gone, pages_build}` — it never falls back to `build/` or another build (a mismatch with the on-screen page images would break the coordinates). `Range` requests are not honored (the whole file is always sent). Host/Origin checks are the same as any other `GET` |
| `GET` | `/vendor/pdfjs/<file>.mjs` | Serves the PDF.js bundle used by the viewer (`pdf.min.mjs`·`pdf.worker.min.mjs`) as `text/javascript; charset=utf-8` (`Cache-Control: public, max-age=86400`; the viewer appends `?v=<version>` to bust the cache). Only accepts a single-segment `.mjs` filename — subpaths, `..`, dotfiles, `%`-encoding, symlinks pointing outside the directory, and non-`.mjs` files (`LICENSE`·`README.md`) all get `404`. The vendored PDF.js ships inside the package at `src/limn/vendor/pdfjs/` and is served by default; `--pdfjs-dir` ([operations.md](operations.md) §Command-line arguments) overrides the directory. Provenance and version are in [`vendor/pdfjs/README.md`](../src/limn/vendor/pdfjs/README.md). Host/Origin checks are the same as any other `GET` |
| `GET` | `/api/snippet?file=&lo=&hi=` | A source-line snippet (capped at 80 lines). `&levels=1` also returns the scope ladder anchored on that range. Outside the manuscript tree or a malformed range gets `400` |
| `GET` | `/api/overlaps?file=&lo=&hi=` | Overlap between that range (a pre-save selection) and open pins: `{overlaps}` — the viewer no longer calls this (§Overlapping pins), it is kept for agents and older viewer builds |
| `POST` | `/api/pin` | Creates a new pin → `{id}`. The stored-field allowlist is: `file, name, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, note, scope, quote, pdf_build`. Optional `kind_req`·`mentions` (hint)·`assignee` (owner, §@mentions, people, and events). If `pdf_build` is omitted (an agent's `curl`), it is stamped with the current build |
| `POST` | `/api/pins/{id}/edit` | In-place edit — §Editing a pin, below |
| `POST` | `/api/pins/{id}/close` | Closes one pin (`done: true`, `closed_by`). If an agent closes it, it goes to pending review (`review: true`); if a tailnet person closes it, it's done — §Pending review. Optional body `{"reply", "ref", "review"}` — §Leaving a reason when closing, below. The record stays around (it drops out of the open table in `<state_dir>/pins.md` and only shows up in the header count — §pins.md format) → `{ok, pin}`. If the id doesn't exist: `200 {"ok": false, "pin": null}` (same for reopen). **Closing an already-closed pin again returns `{ok: true, pin}` unchanged, without touching any field** (not even `rev`) — §Leaving a reason when closing |
| `POST` | `/api/pins/{id}/reopen` | Reverts a closed pin (`reopened_by`). Clears `close_reply`/`close_ref`·`review`·`confirmed_*` if present (a new close will fill them in again). Optional body `{"reason"}` is recorded in the thread → `{ok, pin, state}` |
| `POST` | `/api/pins/{id}/drop` | Removes a pin from the list into `pins.dropped.jsonl` (a mis-placed pin, `dropped_by`) → `{ok}`. A missing id gets `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/restore` | Restores a dropped pin under the same id (works even after a server restart, `restored_by`) → `200 {ok, pin}` / `404` (no drop record) / `409` (an id collision) |
| `POST` | `/api/pins/{id}/claim` | Sets or extends the in-progress marker (if the same identity) — §In-progress marker. Optional body `{"eta_min": 1..240, "ttl_min": 1..120}` (non-integer or below 1 is `400`; above the cap is clamped to the cap) → `{ok, pin, ttl_min_applied, eta_min_applied?}`. If another identity already holds a valid claim: `409 {"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}`. A closed pin: `409 {"error":"done","pin":...}`. A missing id: `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/unclaim` | Clears the in-progress marker — independent of the requester's identity (no permission check, an attribution-only trust model). → `{ok, pin}`. A missing id: `200 {"ok": false}` |
| `POST` | `/api/clear` | Archives everything (`pins_<timestamp>.jsonl.bak`; a second clear in the same second gets `pins_<timestamp>-1.jsonl.bak`, and so on) and empties the store — a bulk reset. Id numbering continues from where it left off. **Agents must never call this** |
| `POST` | `/api/rebuild` | Rebuilds the PDF (synchronous) — build-sync §Rebuild. The response includes `head` (the short hash of the built commit, on success only) and `pull` (only with `--git-pull`, build-sync §`--git-pull`). `log` follows build-sync §Trimming agent responses |
| `POST` | `/api/rebuild?async=1` | Rebuilds the PDF (asynchronous) — once the build lock is acquired, the actual build runs in a daemon thread and this returns `202 {"state":"running"}` immediately. Already running: `409 {"state":"running","busy":true}`. Poll `GET /api/build` for progress (build-sync §Asynchronous rebuild) |
| `POST` | `/api/rebuild?log=1` / `GET /api/build?log=1` | Turns off build-sync §Trimming agent responses and returns the full log tail (4000 characters) either way. The viewer always sends this flag for its error panel |

## Comparison PDF runs and caching

The comparison is **the selected commit's first parent → the selected commit**. A merge commit also uses its first parent. The first commit in the repository is `422 reason:no_parent`. Both snapshots are built from Git objects at the build root; uncommitted changes are never included. If the current main path didn't exist at a past commit, it fails with `missing_main`. Renamed-file paths are never guessed at.

Requires `bwrap`, `latexdiff`, and `latexmk` on Linux. Only system-installed executables under `/usr` are allowed. `latexdiff --flatten --math-markup=off` and `latexmk -norc -pdf -no-shell-escape -interaction=nonstopmode -halt-on-error` run inside a bwrap sandbox that exposes neither the home directory, the original repository, nor the network. If sandboxed execution isn't available, it fails — there is no unsandboxed retry. The current comparison engine is pdfLaTeX; XeLaTeX/LuaLaTeX-only manuscripts are confirmed against source changes. Manuscript packages such as kotex are never stripped arbitrarily.

`input`/`include`/`subfile` and similar are flattened within each Git snapshot. If an included file is missing, the comparison PDF is not treated as a success. Limits: 64 MiB per file, 256 MiB and 4,000 files per snapshot, 32 MiB per PDF. Symlinks, gitlinks, and path escapes are rejected. The combined output of both process pipes is capped at 8 MiB by default; Git checkouts get 60 seconds each, latexdiff gets 60 seconds, and latexmk gets the smaller of the server's `--timeout` and 180 seconds. Timing out or exceeding the output cap kills the whole process group.

Comparison state is kept per document under `<state>/revisions/`. The cache key includes the repository, build root, main path, both full SHAs, the engine, and the implementation version. A successful PDF and its state are committed only once the run finishes; the manuscript's `pages.cur`, `builds.json`, and pins are never touched. At most two comparisons run at once process-wide, and at most one per document's state folder. A duplicate request for the same job returns the existing state; if another job already holds the slot, it's `409 reason:busy`. Each document's cache holds at most six comparisons, for 24 hours, cleaned up on the next request. A job interrupted mid-run is rebuilt on the next request. A failed job can be retried with a new POST.

Warnings are distinguished from failures. A deleted sentence that referenced an old label can produce `??`; changes inside math, or to a figure binary with the same filename, may not be highlighted. Bibliography-, style-, or comment-only changes may show no highlighting in the body text. `warnings` is surfaced alongside the plain source-diff path as a fallback. The server-side `build.log` keeps only the last 8,000 characters and the HTTP response never exposes the full log.

## Editing a pin (`/api/pins/{id}/edit`)

```json
{"note": "revised note", "lo": 185, "hi": 262, "scope": "env2", "kind": "env:minipage", "base_rev": 3}
```

- `base_rev` is required — the `rev` you got when you read the pin you're about to edit. If it doesn't match, `409 {"error":"conflict","pin":<latest>}` and nothing changes. This exists so an agent can't silently overwrite a pin that another agent already closed, or that line-resync already moved, using stale `lo`/`hi`. On `409`, look at the latest `pin` in the response and resend.
- To replace the location wholesale, send `loc: {file, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, scope, pdf_build}` (relocating). `pdf_build` only changes when `loc` includes `frac` (otherwise it's the pick response's value, or failing that, the current build). An edit that only touches the note·`note_append`·`lo`/`hi` leaves `pdf_build` alone. `file`·`lo`·`hi` are required. `page`·`frac` missing from `loc` keep their existing values; a missing `kind` becomes `lines` (the remaining location fields are cleared). The id, note, and author are untouched.
- When the range changes, `anchor` is recomputed and `stale`/`sync` are cleared — this is also how a `stale` pin gets fixed.
- A closed pin can only have its note edited. Sending a range or location change gets `409 {"error":"done"}`.
- On success, `edited_at`·`edited_by` are recorded and `rev` increments by 1.
- `note_append` (empty or whitespace-only is `400`; each chunk is capped at 2000 characters) is accepted without `base_rev` — `note += "\n(added HH:MM) " + note_append`. If the combined length exceeds the note cap (`NOTE_MAX`, 4000 characters), it's `400` and nothing changes (individual chunks under 2000 characters can still overflow once merged with the existing note). This exists so an agent "appending" to an overlapping pin doesn't have to fetch the latest `rev` every time (§Overlapping pins and appending). To undo it, resend `{"note": <previous note>}` using the response's `pin.rev` as `base_rev`.

## Leaving a reason when closing (`/api/pins/{id}/close`)

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/close \
  -H 'Content-Type: application/json' \
  -d '{"reply": "Changed the title to …", "ref": "PR #227"}'
```

- Both are optional. **Agents should leave what they changed and a PR number** — `reply` for what was fixed (≤500 characters), `ref` for a reference (a PR number, etc., ≤80 characters). This means a co-author looking at a closed pin later doesn't have to dig back through the manuscript to see why it was closed. An empty or missing body (empty string, or whitespace-only) behaves exactly as before — an old agent's bodyless `curl -X POST …/close` still goes through unchanged.
- A non-string value, or one over the cap, is `400` and nothing changes. Like every other field, the value is rendered through `esc()` in the viewer (escaped).
- On success, it's stored on the pin as `close_reply`/`close_ref` and shown on the closed card. Closed pins that share a `ref` may be grouped visually by the UI.
- **Closing an already-closed pin again changes nothing** — `done_at`·`closed_by`·`rev`·`close_reply`·`close_ref` all keep their first-close values, and the second call's `reply`/`ref` are discarded (never applied). This exists because a second close used to overwrite `done_at`·`closed_by`, erasing who closed it first (an observed defect). **To leave a new reply, reopen once via `/reopen` and close again** — `reopen` clears the old `close_reply`/`close_ref`, so the next close fills in a fresh reason.
- An agent's `curl` has no identity headers, so `closed_by` is recorded as `local/agent` (`로컬/에이전트`).

## Threads (`/api/pins/{id}/reply`)

10 of 42 pins (24%) in an early pilot manuscript were questions rather than things to fix (e.g. #30, "what does it mean for the interval to include zero?"), and the only place to answer was the single close-reason field, with no way to ask back. Each pin has an optional `thread` field, and people and agents both post to it the same way.

```bash
curl -s -X POST <base>/api/pins/12/reply -H 'Content-Type: application/json' -d '{"text": "it is the 95% confidence interval"}'
```

- `text` is a string of 1..1000 characters (leading/trailing whitespace trimmed, CRLF→LF, control characters other than newline/tab stripped). Invalid input is `400`, a missing id is `200 {"ok": false}`, and a 200th reply is `409 {"error":"full"}`.
- A message looks like `{id, by:{login,name,pic?}, at, text, mentions?, ev?, ref?}`. `id` counts up from 1 within the pin. State transitions also leave a line in the thread — `ev` is `close` (text = close reason, `ref`), `reopen` (text = reopen reason), or `confirm`. The close reason is still mirrored into the legacy `close_reply`/`close_ref` fields (for older viewers/agents).
- A reply never changes state. A question pin is closed separately, after a reply is added.
- The pin kind is `kind_req` (`fix`|`question`, defaults to `fix`). Accepted by `POST /api/pin` and `/edit` (`/edit` accepts it even on a closed pin). This is a different field from the old `kind` (scope kind).

## Pending review (`close` → `review` → `confirm`)

In an early pilot, 2 of 42 pins (#28, #42) that an agent closed were later reopened by their author, with no record that a person had actually looked at the outcome.

| Transition | Condition | Result |
| --- | --- | --- |
| Close | No identity header (local curl · agent · a tagged device with no header) | `done:true` + `review:true` = **pending review** |
| Close | A tailnet person (header present) | `done:true` = done (that person is the reviewer) |
| Close | Body has `"review": true`/`false` | Follows that value — a remote agent closing over a tailnet address sends `true` |
| `POST /confirm` | Pending review | Clears `review` and records `confirmed_by`·`confirmed_at` (thread `ev:confirm`). **People only** — a request with no identity header (agent, local curl) gets `403 {"error":"확인은 사람이 합니다"}` ("confirmation is done by a person" — the viewer only suggests the author, but any tailnet person can press it) |
| `POST /confirm` | Done / open / missing (person identity) | Idempotent `{ok:true}` / `409 {"error":"open"}` / `200 {"ok":false}` |
| `POST /reopen` | A closed pin (pending review or done) | Reopens. Clears `review`·`confirmed_*`·`close_reply`·`close_ref` and adds `ev:reopen` to the thread (optional `{"reason"}` ≤1000 characters as the text) |

- **Backward compatibility**: pending review is still `done:true`, so the old contract holds — it's absent from `GET /api/pins` (open pins only), `claim` returns `409 done`, resync and overlap calculations are skipped, and old servers/tabs treat it as done. An old `done:true` with no `review` field is done. Reading never triggers a migration write.
- Responses and `GET /api/pins` items carry a computed `state` field (`open`|`review`|`done`; not stored). `/api/meta` has `n_open`·`n_review`·`n_done` (done only).
- A second close still changes nothing, as before — an agent re-closing a pending-review pin leaves it unchanged.

## @mentions, people, and events

Only invoked inside the viewer. No outbound notifications (GitHub·Telegram·email) are sent; they're written to `events.jsonl` for later use.

- **People** (`<state_dir>/people.json`, `{"version":1,"people":[{login,name,pic?,first_seen,last_seen}]}`): a tailnet person who opened this viewer (`GET /`, full `/api/meta`) or sent a write request. Local/agent requests are never recorded. The same value is only rewritten once every 10 minutes (`/api/meta?light=1` polling never writes). `GET /api/people` merges this with pin authors, actors, and thread posters.
- **Resolution**: the server resolves `@name` in text to a login — full name, login, the part of a login before `@`, or the first word of a name if it doesn't collide with another. Case-insensitive, and Korean particles attached to a name (`@Bob님`) are fine. If the character right after `@` is a letter (an email address), it's not a mention; if a Latin name is immediately followed by more Latin letters (`@Alicex`), it's something else. The login the viewer resolves is sent as `mentions` (≤10) in the body, but that's only a disambiguation hint for when the first word matches more than one person. The raw text keeps `@name` as typed; resolved logins go in the pin's `mentions` (note) and the message's `mentions`. A self-mention (mentioning your own author) is always dropped — you never end up on your own "addressed to me" list.
- **Pins that ask a person something** (inferred for old pins with no `assignee`): the computed field `addressed` = the note's `mentions` + the current turn's thread-message `mentions` (since the last close, or since the last reopen if it was reopened — [`design.md`](design.md) §Threads and review) — filled in **only for question pins** (`kind_req=question`). This is what produces `→ @name` in the pins.md number column, and agents skip it. The same material on a `fix` pin instead lands in the `fyi` field and only shows as `참고 @name` ("for reference") in pins.md — never skipped (observed bug: an FYI mention on a fix pin was read as `→ @name` and permanently skipped).
- **Assignee** (`assignee`): an explicit value for who handles this pin — `"agent"` or a person's login. Guessing this from mention text used to be ambiguous (from an early pilot, #43: a fix pin reading "does this call actually work, @Bob Park please confirm" was meant for Bob, but showed as `참고 @Bob Park` and the agent read it as its own job). Accepted by `POST /api/pin`·`/edit` — must be `"agent"` or a login this instance knows (`GET /api/people`), otherwise `400` (Korean message). `/edit` accepts it even on a closed pin, and a change adds `ev:"assign"` to the thread (text `담당: @name` / `담당: 에이전트` — "assigned to: …"). The assignee at creation time is not recorded. The viewer always sets an assignee on a new pin (`agent` if no one is @-mentioned).
  - Assignee = a person → `addressed = [that person]`, pins.md `→ @name`, agents skip it. That person's "pins addressed to me" list · `나를 부름` ("addressed to me"). An `assigned` event goes to the new assignee.
  - Assignee = `agent` → `addressed = []`, all @-mentions in the note and current turn become `fyi` (pins.md `참고 @name`) — the agent handles it.
  - An old pin with neither field → falls back to the inference above (a question pin's @-mention = `addressed`, a fix pin's = `fyi`). Reading never triggers a migration write.
  - Either way, an @-mentioned person gets a `mention` notification.
- **Events** (`<state_dir>/events.jsonl`, one record per line, append-only): `{seq, type, pin, doc, to:[login], by:{login,name}, at, ts, kind_req?, msg?, excerpt?}`.

  | `type` | When | `to` |
  | --- | --- | --- |
  | `mention` | A note (save/edit)·reply·reopen reason newly mentions someone | The newly mentioned person |
  | `review_requested` | A pin goes to pending review | The author |
  | `replied` | A reply is added | The author + anyone previously mentioned on this pin (someone newly mentioned by this text only gets `mention`) |
  | `reopened` | A closed pin is reopened | The author |
  | `assigned` | A pin's assignee is set to a person, on creation or edit (only when it changes) | The new assignee |

  The actor themself and `local` are always dropped from `to`; an empty `to` means nothing is recorded. Once a pin write is committed, the whole file is atomically rewritten under the lock (the earlier part is untouched — append-only). Only the most recent 5000 entries are kept, but `seq` keeps counting up — consumers should follow `seq`, not byte offsets.

## Browser notification cursor (`/api/meta?ev=<seq>`)

`/api/meta` (light variant included) always carries `ev_seq` (the last `seq` in `events.jsonl`). Appending `ev=<last seen seq>` returns, as `events` (up to 20, each with `doc_name` added), any subsequent event that is `mention`·`review_requested`·`replied`·`reopened`, has the **current requester** (a tailnet login) in `to`, and wasn't triggered by the requester themself. Local/agent requests always get an empty list; a non-integer value is `400`. Read-only — the light-polling no-write contract still holds. Viewer-side rules are in [design.md](design.md) §Browser notifications.

## Remote agent entry point (`GET /pins.md`)

A co-author's agent never logs into the server machine — it only reaches the instance over a tailnet address. `GET /pins.md` serves the same content as the on-disk `<state_dir>/pins.md`, over HTTP, with instructions matched to the `Host` the request arrived on — no need to open the file on disk.

```bash
curl -s https://<device>.<tailnet>.ts.net:<port>/pins.md
```

- Goes through the same sync path as `GET /api/pins` (`snapshot_pins()`) before rendering — line numbers are current.
- Only the base URL in the close example changes: `https://<Host as sent, port included>` if `Host` is `*.ts.net`, otherwise (loopback) the usual `http://127.0.0.1:<port>`. When remote, the instructions paragraph gets one extra line: `원격: curl -s <base>/pins.md` (missing on loopback, since it's already reading that file directly).
- The on-disk `<state_dir>/pins.md` always uses the loopback base, regardless of this request — a different session reading the file directly sees the same instructions.
- Host/Origin checks are the same as any other `GET` ([operations.md](operations.md) §Host/Origin checks) — an unrecognized Host gets `403`.

## In-progress marker (`/api/pins/{id}/claim`, `/api/pins/{id}/unclaim`)

Two agents (the author's side and a co-author's side) can end up working the same pin at the same time. `claim` is a **TTL-bound, optimistic marker — not a lock**. It doesn't stop someone else from closing that pin or force-reclaiming it. Collaboration relies on the convention of claiming right before you start, and skipping anything showing `처리 중(…)` ("in progress …") (SKILL.md's pin-processing procedure). **Claim only the pin you're about to fix, right before you fix it** — claiming a batch locks pins you haven't touched yet (observed 2026-09-23: 23 pins were claimed at once with `ttl_min` 480, and the viewer's `~04:02` read like an ETA for all of them).

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/claim -H 'Content-Type: application/json' -d '{"eta_min": 15}'
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/unclaim
```

- Two optional body fields. Non-integer or below 1 is `400` and nothing changes. **A value above the cap is clamped, not rejected** (`ttl_min` 480 → 120, `eta_min` 300 → 240) — this exists so an agent following the old convention of claiming with `ttl_min` 480 doesn't get a `400` and break its run when it tries to extend with the same value. `ttl_min_applied` (always)·`eta_min_applied` (when `eta_min` was sent) in the response are the values actually applied.

  | Field | Range | Meaning |
  | --- | --- | --- |
  | `eta_min` | 1..240 | **Estimated time to fix**. Stored on the record as `eta_ts = now + eta_min×60` (epoch seconds). See SKILL.md's pin-processing step 4 for how to estimate |
  | `ttl_min` | 1..120 | Time until the **lock auto-releases** (a safety net). If omitted: `min(120, max(30, eta_min×2))` when `eta_min` is given, otherwise 120. The cap was lowered from 480 to 120 — so a stalled agent can't hold a pin for half a day |

- Identity is resolved the same way as author attribution (`Tailscale-User-Login`, or `local/agent` (`로컬/에이전트`) with no header). **The same identity claiming again extends it** — `claim_until` is recomputed from now, and if `eta_min` is given, `eta_ts` is recomputed from now with the new estimate (kept as-is if not given). The start time (`claimed_at`·`claim_ts`) is unchanged, `rev`+1. **A different identity holding a valid (non-expired) claim gets `409`** — `{"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}`. A fresh claim (including reclaiming someone else's expired one) clears any old `eta_ts`.
- `claim_until`·`claim_ts`·`eta_ts` are epoch seconds — compared independent of the browser's time zone (same reasoning as build-sync §Position estimation). The names deliberately avoid `*_at`: record validation (`valid_rec`) treats `*_at` as a string timestamp, so a numeric `*_at` field would make an old server that doesn't know about it discard the record as corrupt. An expired claim is treated as absent everywhere it's shown (`<state_dir>/pins.md`, viewer cards, conflict checks). The stored value itself is only cleaned up on the next write.
- An old claim with no `claim_ts` has `GET /api/pins` parse `claimed_at` (a server-local time string) into epoch and expose it as the computed field `claim_ts` (not stored).
- Claiming a closed pin gets `409 {"error":"done","pin":...}`. A missing id follows the existing convention, `200 {"ok": false}`.
- `unclaim` clears it regardless of the requester's identity — this skill's trust model doesn't restrict tailnet members, it only records attribution ([design.md](design.md) §Author attribution), so the in-progress marker can also be cleared without a permission check.
- `close`·`drop` also clear the claim fields — a closed or dropped pin never keeps an in-progress marker. Closing a pin someone else has claimed is not itself blocked. This is why an agent only calls `unclaim` when it's giving up on a pin or handing it off.
- `<state_dir>/pins.md`'s number column shows `처리 중(<name>, 약 15분)` ("in progress (name, ~15 min)") when there's a valid claim — the remaining estimate rounded up to 5 minutes, `예상 초과` ("over estimate") if it's past due, or just `처리 중(<name>)` if claimed with no estimate (§pins.md format).
- The viewer card shows an amber dot in the header and a badge like this. Minutes and times are always rounded up to 5 minutes (estimates are approximate). The time shown is the viewing device's local time, recomputed every 30 seconds.

  | State | Badge |
  | --- | --- |
  | Has an estimate | `처리 중 · 약 15분 · 20:40쯤` ("in progress · ~15 min · around 20:40") |
  | Past the estimate | `예상보다 늦어짐 (+5분)` ("later than expected (+5 min)") (minutes over) |
  | Claimed with no estimate | `처리 중 · 20:02부터 (23분째)` ("in progress · since 20:02 (23 min so far)") |

  The lock auto-release time (`claim_until`) is never shown on the badge, only in the tooltip — it used to read as the expected completion time. An [Unclaim] button appears alongside — **the viewer has no button to set a claim** (that's agent-only).

## Overlapping pins and appending (no automatic merging)

When two open pins on the same file overlap (one falls inside the other's range, or they partially overlap), `GET /api/pins` and `POST /api/pick` responses carry the computed fields `rel`/`overlaps` — **never stored**, recomputed on every request.

- `rel: [{"id", "rel": "inside"|"contains"|"partial"}]` — that pin's relationship to other pins (both already saved). If the ranges are exactly equal, the lower id is treated as `contains` (the outer one).
- `overlaps` (pick·`/api/overlaps` response): `[{"id","lo","hi","rel": "equal"|"inside"|"contains"|"partial"}]` — the relationship of a pre-save selection to existing pins (`selection_rel`). `equal` = identical range (the most common form of duplicate — re-picking the same paragraph or environment), `inside` = the selection is inside an existing pin, `contains` = the selection wraps an existing pin, `partial` = they overlap partway.
- **Recomputed every time the range changes.** The viewer runs the same rule (`overlapsFor`/`selRel`, checked against the server implementation by a regression test) against this tab's open-pin list on every drag, level change, and one-line-step button. Computing it only once at pick time meant switching to the [paragraph] level to reproduce an existing pin's exact range didn't trigger the banner, and a duplicate pin got saved silently (observed). If a pin the server sees isn't in this tab's list (someone else just saved it), the list is refetched.
- All four relationships trigger the banner. One representative is chosen: same range > inside (narrowest containing pin) > contains (widest contained pin) > partial (lowest id). The wording states the relationship — `열린 핀 #4와 같은 범위입니다 (L405-L406)` ("same range as open pin #4") / `… #4 범위 안입니다` ("… inside #4's range") / `… #4를 감쌉니다` ("… contains #4") / `… #4와 일부 겹칩니다` ("… partially overlaps #4"), with `[#4 메모에 덧붙이기] [별도 핀으로 저장]` ("[append to #4's note] [save as a separate pin]").
- The viewer never merges automatically. "Append" uses `note_append` on the existing pin, and the current selection is never turned into a new pin. "Save as a separate pin" only silences **that relationship with that pin** — if the range changes and the relationship changes, it warns again, and it resets on the next drag.
- `<state_dir>/pins.md`'s number column shows `#N 범위 안` ("inside #N's range") · `#N과 같은 범위` ("same range as #N", fixed and closed together with N) · `#N과 일부 겹침` ("partially overlaps #N", for reference only) as the representative value of this same computation (§pins.md format). The viewer card badge uses the same wording and the same rule.
- The composer panel's overlap banner wording: `열린 핀 #4와 같은 범위입니다` / `… #4 범위 안입니다` / `… #4를 감쌉니다` / `… #4와 일부 겹칩니다` (the particle is chosen based on how the number is read aloud).

## Pick and pins for view-only PDF documents

A `kind:"pdf"` document has no SyncTeX. `POST /api/pick` (with `doc` set to a view-only document) takes coordinates and returns `{doc, kind:"region", view_only:true, page, frac, pdf, name, quote, n_chars, warn, overlaps:[], pdf_build}` — `quote` is the text under the region (pdftotext, whitespace-normalized, 160 characters); `frac` is derived from the coordinates if not sent. There is no line range (`lo`·`hi`·`levels`).

`POST /api/pin` takes `{doc, page, frac, note?, quote?, pdf_build?}`. `frac` is required and stricter than for a LaTeX pin (4 numbers, within 0..1 on the page, positive area). `page` is 1..page count. Sending `file`·`lo`·`hi`·`scope` gets `400`. The stored record is `{id, doc, pdf:<absolute path>, name, kind:"region", page, frac, quote?, note, at, author, rev, pdf_build}` — no `file`·`lo`·`hi`·`anchor`. `/edit` only accepts the note (`note`·`note_append`) and relocating the region (`loc:{page, frac, quote?}`); `lo`/`hi`/`scope`/`kind` all get `400`. Close·claim·drop work the same as LaTeX pins. `POST /api/rebuild` on a view-only document gets `400` (there is nothing to rebuild — the pages redraw themselves automatically when the file changes, build-sync §View-only PDF documents), and so does `/api/snippet`.

## Pin record schema (`pins.jsonl`, one line = one record)

```json
{"id": 3, "at": "2026-09-21 20:10:00", "page": 4, "file": "<absolute path>/introduction.tex",
 "lo": 120, "hi": 134, "raw_lo": 122, "raw_hi": 131, "kind": "env:minipage", "scope": "env",
 "via": "synctex", "score": 0.93, "note": "tone this paragraph down", "frac": [0.12, 0.30, 0.55, 0.18],
 "pdf_build": "pages-20260921200500",
 "anchor": {"head": "This section describes...", "tail": "...effect is observed."},
 "synced_at": 1758450000.0, "sync": "moved +3", "rev": 2, "done": false,
 "author": {"login": "bob@example.com", "name": "Bob Park", "pic": "https://..."},
 "edited_at": "2026-09-21 21:00:00", "edited_by": {"login": "local", "name": "로컬/에이전트"}}
```

All new fields are optional — an old record without them is still read fine.

| Field | Meaning |
| --- | --- |
| `doc` | The document key this pin belongs to (§Document parameter). An old record without one is **read** as the first document — never migrated on write. `GET /api/pins` always fills it in (computed) |
| `pdf` | Only for view-only PDF pins — the absolute path to that PDF. If this field is present and `file` is absent, it's validated as a view-only pin (`page`·`frac` required, no `lo`/`hi`). A document key that's no longer in the current configuration doesn't make it a corrupt line |
| `rev` | +1 on every write that changes the record's content (line move/stale, edit, close, reopen, restore). Absent = 0 |
| `scope` | `raw\|para\|env\|env2\|env3\|lines` — the scope-ladder level chosen at save time |
| `quote` | Optional — a short quote attached by the caller (cut to 60 characters) |
| `pdf_build` | The build id (page-directory name) `frac` was picked against. Absent = an old pin — the legacy field name `frac_build` is read the same way (build-sync §Position estimation) |
| `anchor` | `{head, tail, head_off, tail_off}` — the basis for line resync. An old anchor with no `*_off` is treated as 0 ([design.md](design.md) §Line renumbering resync) |
| `kind` | `paragraph\|float\|block\|none` (legacy values) or `env:<name>`, `lines`. An unknown value is left as-is |
| `author` | The creator, `{login, name, pic?}` |
| `edited_at`, `edited_by` | The time and person of the last edit after saving |
| `closed_by` / `reopened_by` | Who closed/reopened it (alongside `done_at`·`reopened_at`) |
| `close_reply` / `close_ref` | Optional reason left at close time — what was fixed (≤500 characters) · a reference like a PR number (≤80 characters). Only written on the first close; re-closing an already-closed pin never changes it (§Leaving a reason when closing). Cleared by `reopen` |
| `dropped_by` / `restored_by` | Who dropped it (in `pins.dropped.jsonl`) and who restored it |
| `kind_req` | `fix`\|`question` — the pin kind (§Threads). Absent = fix |
| `thread` | Replies and state-transition log, `[{id, by, at, text, mentions?, ev?, ref?}]` (§Threads) |
| `mentions` | Logins mentioned in the note (§@mentions, people, and events) |
| `assignee` | Owner — `agent` or a person's login (§@mentions, people, and events, Assignee). Absent = an old pin (inference rules apply) |
| `review` | `true` = pending review (only meaningful together with `done:true`, §Pending review) |
| `confirmed_by` / `confirmed_at` | Who confirmed the pending review, and when |
| `claimed_by` / `claimed_at` / `claim_ts` / `claim_until` / `eta_ts` | The in-progress marker (§In-progress marker) — `claimed_by` is the same `{login,name}` shape as author attribution, `claimed_at` is a start-time string, `claim_ts` (start)·`claim_until` (lock auto-release)·`eta_ts` (expected completion) are epoch seconds. A past `claim_until` is treated as absent. `close`·`drop`·`unclaim` all clear these |

`snippet`, `warn`, `levels`, `default_level`, `rel`, `overlaps`, `est`, `state`, `addressed` only appear in responses and are never stored (§Overlapping pins and appending, build-sync §Position estimation).

## pins.md format

`<state_dir>/pins.md` is a 5-column table: `| # | 쪽 | 위치 | 범위 | 메모 |` ("# / page / location / scope / note" — the old `종류` ("kind") column became `범위` ("scope"). The `작성` ("author") column was dropped in v2 — author is only visible through `GET /api/pins` and the viewer card. Same for closed pins). Snippets are deliberately left out — given just a line range, an agent `Read`-ing the source directly is always cheaper and more accurate (a snippet is a point-in-time copy that can drift from the source).

**Note on stability**: this pins.md table format and the HTTP API described throughout this document are a contract other agents depend on. The wording of the Korean literals below (column headers, in-line markers, state names, header lines) never changes even when this documentation is translated — the browser-facing viewer UI may be localized, but pins.md and the API's field and state names are not.

- **Header lines**: right after `원고: <path>` ("manuscript: …") comes `논문: <label> · 저장소: <git origin URL or (없음)>` ("paper: … · repository: … or (none)", operations.md §Running multiple manuscript instances at once) — so that with several instances open at once, an agent doesn't process the wrong paper's pins. When `저장소` is present, the instructions paragraph adds `처리 전 자기 체크아웃의 git remote get-url origin 이 위 저장소와 같은지 확인. 다르면 다른 논문의 핀이니 멈춘다` ("before processing, confirm your own checkout's `git remote get-url origin` matches the repository above; if it differs, these are another paper's pins — stop"). Next, if both `head.txt`·`built_at.txt` exist, two more lines: `기준: <head short hash> · 빌드 <built_at>` ("baseline: … · built …") and `다른 체크아웃에서 처리하면 먼저 git rev-parse --short HEAD 가 같은지 확인` ("if processing from a different checkout, first confirm `git rev-parse --short HEAD` matches"). If neither file exists (not a git repository, or not built yet), those two lines are simply omitted.
- **Location**: a **relative path** against `--manuscript` (`C.src`). A root file equals its basename, so a single-file manuscript's rows look as before. A sub-file split off via `\input`/`\include` is shown like `sections/intro.tex L12-L18`. A `|` in a filename is escaped as `\|` (see the escaping rule below).
- **Scope**: if `scope` is set — `env*`→`env:<name>`, `para`→`paragraph`, `raw`/`lines`→`lines`; otherwise the legacy `kind` value as-is.
- **Line-number timing**: as of the last time `<state_dir>/pins.md` was regenerated. If an earlier pin's fix may have shifted line numbers, fetch the resynced values from `GET /api/pins`.
- **Markers in the number column** — appended after the number with ` · ` (e.g. `7 · #6 범위 안 · 처리 중(에이전트 B, 약 10분) · 수정됨`, "7 · inside #6's range · in progress (Agent B, ~10 min) · edited"). The old symbols (`⊂#N` `∩#N` `⏳` `✎` `⚠`) were replaced with short words because they weren't self-explanatory. Only one overlap marker per pin (same range > inside > partial overlap):
  - `#N과 같은 범위` ("same range as #N") — matches open pin `#N`'s line range exactly (the same spot picked twice; if there are several such matches, the lowest id). Appears on both pins. Fix and close both together.
  - `#N 범위 안` ("inside #N's range") — this pin falls entirely inside open pin `#N`'s range (only the single narrowest containing pin is shown — the viewer card's tag follows the same rule, so this file and the screen never disagree). **Fixing and closing it together with `#N` is recommended** — fixing them separately risks touching the same paragraph twice or missing `#N`'s constraint.
  - `#N과 일부 겹침` ("partially overlaps #N") — only when neither of the above applies (the lowest-id partial match). For reference only; each can be handled independently. The particle is chosen based on how the number reads aloud (`#20과`, `#2와`).
  - `처리 중(<name>, 약 N분)` ("in progress (name, ~N min)") — another agent holds a valid claim (§In-progress marker). The name is `claimed_by.name`, or `로컬/에이전트` ("local/agent") for a headerless request. `약 N분` is the remaining estimate (rounded up to 5 minutes), `예상 초과` ("over estimate") if it's past due, or just the name with no estimate. **Skip this pin** — so as not to collide with whoever's already on it.
  - `수정됨` ("edited") — the note or range was edited after saving (`edited_at` present).
  - `위치 잃음` ("position lost") — the pin went `stale`. **If you just fixed that range yourself**, the change may already be reflected — check the source and it's fine to close (this doesn't have to be reported to the user unconditionally — only when the cause is a change you just made yourself).
  - The legend line (`표시: '#N 범위 안'·'#N과 같은 범위' = … · '#N과 일부 겹침' = … · '처리 중(이름, 약 N분)' = … · '수정됨' = … · '위치 잃음' = … · «…» = …`) is only included when at least one open pin has a marker.
- **`«…»` quotes**: a conditional exception attaching up to 60 characters of quoted text before the note — only when a pin's range is **a single line**, that line is **over 600 characters** (in a manuscript where one paragraph is one unbroken line, line numbers alone can't locate the target), and `scope` is `raw`/`para`/unset. If cut at 60 characters, the quote ends in `…` (e.g. `«only the start of the sentence…»`) — so a truncated quote isn't mistaken for a complete one. This quote is **text rendered by `pdftotext`** — a search hint, not a literal string to hand to `Edit`'s `old_string` (ligatures, hyphenation, and whitespace can differ from the raw LaTeX source). Read the file by line range, then search for the quote to pin down the exact spot.
- **`[author]` before the note**: when an open pin set has 2+ distinct authors (by `author.login`; pins with no author count as one group), `[<author.name>] ` is prepended to the note (never starting with `@`, so it isn't misread as a mention — observed: `@Alice Kim: …` looked like a mention). With only one author, this is skipped to save tokens — it's there to help attribute a result report or a `close`'s `reply` to the right pin ([design.md](design.md) §Author attribution). Not an assignment rule.
- **Question, reopened, and person-addressed pins**: the number column also gets `질문` ("question"), `다시 열림` ("reopened", the current turn starts from the reopen if it's been reopened since it was last done), `→ @name` (assignee is a person — an old pin with no assignee falls back to being a person-addressed question pin, §@mentions, people, and events; agents skip it unless the user explicitly asks), `참고 @name` ("for reference @name", a notify-only mention — never skipped, even on a pin whose assignee is a person, for any mention that isn't the assignment itself). Display priority order: `다시 열림` > `→ @이름`/`참고 @이름` > `질문`. After the note, the current turn's thread is appended as `[스레드 N건] 이름: … ⏎ 다시 연 이유(이름): …` ("[N thread messages] name: … / reopen reason (name): …", last 3, 200 characters each — the rest via `GET /api/pins/{id}`). If there are any person-addressed pins, the instructions paragraph gets the skip rule appended.
- **Pending review**: dropped from the open table and listed at the bottom in a section `## 검토 대기 N건 — …처리하지 않는다` ("## N pending review — do not process") with a 4-column table `| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |` ("# / location / reviewer / reply left at close", with the document key prefixed to location for multiple documents). The header line only gains `검토 대기 N건(맨 아래, 처리하지 않는다)` ("N pending review (at the bottom, do not process)") when there are any; otherwise the header looks exactly as before.
- **Closed pins**: dropped from the table, kept only as a count in the header (`닫힌 핀 N건(뷰어의 '닫힌 핀'에서 확인)`, "N closed pins (see 'closed pins' in the viewer)"). `<state_dir>/pins.md` never grows with accumulated closed pins — the old `<details>`-expand approach is gone.
- **Multiple documents** (two or more `--doc`, or any open pin under a non-first document's key): still a single file, but the header gains one line `문서: 본문(\`ms\`) 3건 · … · 리뷰어 코멘트(\`rv\`, 보기 전용) 1건` ("documents: body (`ms`) 3 · … · reviewer comments (`rv`, view-only) 1") plus a note on the sections, then for each document with open pins a section `## <name> · \`<key>\` · \`<path relative to --manuscript>\`` (with `— 보기 전용 PDF(줄 번호 없음)`, "view-only PDF, no line numbers", if applicable) and that document's `기준: <head> · 빌드 <built_at>` line (`그림` for view-only), then a 5-column table. The single top-level `기준:` line moves into each section instead. Pins under a document key that's no longer configured show up under a `## 설정에 없는 문서 · \`<key>\`` ("## document not in configuration · …") section. A single document looks exactly as before.
- **View-only pin rows**: the location column reads `쪽 3, 영역 가로 10–60% 세로 20–30%` ("page 3, region x 10–60% y 20–30%"), the scope column is `영역` ("region"), and the note is preceded by the region's text as `«…»` — always (no single-line or 600-character condition, since there's no line number as an alternate hint). If there are any view-only pins, the instructions paragraph gets: "there are no line numbers — judge by page, region text, and the note; find where to fix it in the LaTeX document."
- **Escaping is uniform across every column** (`md_cell`): `|` becomes `\|`; a newline becomes `⏎` in the note column and a space in every other column (number, page, location, scope, quote). A missing `env` branch in the scope column once produced an 8-column row for `kind` values like `env:x|y` (observed in independent verification) — so this isn't handled per-column, it's all routed through one function.
