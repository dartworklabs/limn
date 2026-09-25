# Rebuild, auto-sync, and position estimation

Details on PDF rebuilds, viewer polling, and how the dotted-outline (`est`) marker is decided. The endpoint list is in [api.md](api.md); viewer controls are in [operations.md](operations.md) §Using the viewer.

## Auto-sync (lightweight meta polling)

`GET /api/pins`·`GET /api/meta` (the non-light variant) have **write side effects** (`sync_all` resyncs line numbers against anchors and writes to disk), so they can't be polled directly. Polling instead uses `GET /api/meta?light=1` — it drops `n_open`·`n_done` and never calls `live_pins` (sync). The viewer only refetches the list via `GET /api/pins` (which does sync) when the response's `pins_rev` (`f"{mtime_ns}:{size}"` for `pins.jsonl`, or `"0"` if absent) or `src_mtime` (below) **has changed** — so an agent closing a pin or editing the manuscript over `curl` shows up on screen within a few seconds, while `pins.jsonl` is left untouched whenever nothing has changed.

- `src_mtime`: the maximum mtime across `*.tex`·`*.bib`·`*.sty`·`*.cls`·`*.bst` and figure extensions (`png`·`jpg`·`jpeg`·`pdf`·`eps`·`svg`) under `--manuscript`. Excludes dot-directories, build-output directories (`build/`·`out/`), **directories the build's rsync excludes (`diff/`·`diff_temporary/`)**, and the main PDF (`<main>.pdf`) (2-second cache, skippable with `force=True`). The build fingerprint (§Position estimation) looks at the same file list.
- `build_src_mtime`: the actually-measured `src_mtime` at the moment a build **starts** (bypassing the cache). Only committed to `<state_dir>/built_src_mtime.txt` once a build finishes `ok`·`ok_errors` — if a build fails, the screen still shows the old PDF, so this value and the "manuscript edited" badge both need to stay as they were (an old instance has no such file, so it's `null` — the viewer then compares against the `built_at` timestamp instead).
- While a tab is visible, the viewer polls light meta every 5 seconds, plus on `visibilitychange` (visible) and `focus`. Hidden tabs send no requests at all. Two consecutive failures show a disconnected badge.
- Once the server determines `stale_build` (the manuscript is more than 2 seconds newer than `src_mtime` at the start of the on-screen build) and `src_age_s`, a "manuscript edited · N minutes ago" badge appears, and only then is the [PDF rebuild] button highlighted. The browser's own clock is never used.
- **Position estimation (`.est`) marker** — §Position estimation.
- **Distinguishing done vs. dropped**: when a redraw finds that a pin that was open a moment ago has vanished, `GET /api/pins?all=1` (open + closed) is checked — if it's still there with `done:true`, the notification says "done"; if it's gone entirely (someone called `/drop`), `GET /api/pins/dropped` is checked to find who dropped it, and the notification reads "#N was dropped by 〈name〉". An earlier implementation didn't distinguish the two and reported everything as "done" — so a pin a co-author dropped showed as "done" on the author's screen too (observed).
- A pin changed by someone else (an agent) is picked up automatically by this polling (5 seconds) within a few seconds. [Re-read pins] still exists to sync immediately without waiting for that cycle.

## Position estimation (`est`, server-decided)

A pin's mark is fixed to the `frac` (page-relative fraction) captured at drag time. When that coordinate might no longer line up with the current on-screen PDF, it's drawn dotted (`.est`). **The server decides this**, and carries it as the `est` boolean on `GET /api/pins`. The viewer just draws whatever value it receives.

- Build identity: every build appends `{build, src_hash, src_mtime, finished_at, seq}` to `<state_dir>/builds.json` (the most recent 200 successful builds). `build` is the page-directory name (the `pages.cur` value). `src_hash` hashes the build copy's manuscript files (the same list as `src_mtime` — excluding `diff/`·`diff_temporary/`, dot-directories, and the main PDF) as (relative path, content). mtime is never included — if the content is the same, the layout is the same.
- A pin's `pdf_build`: recorded when a pin is created and when its location is relocated (`loc` with `frac`) — the build id shown on screen at drag time (the pick response's `pdf_build`). Editing the note or the range text doesn't change it.
- `est = (pin.pdf_build ≠ the current build AND the two builds' src_hash differ) OR sync is moved/lost`. If there's no hash, it falls back to comparing against the build-start `src_mtime`; if that build can't be found in history, it's treated as an estimate (drawing it solid without knowing is worse).
- An old pin with no `pdf_build` (the legacy field name `frac_build` is read the same way) is judged by the server using epoch numbers instead — an estimate if the capture time `at` < `built_at` and the current build's start-time `src_mtime` > `at`. `edited_at` is never consulted.
- Why server-side: back when the viewer judged this by wall-clock time (`at`/`edited_at` vs. `built_at`/`build_src_mtime`), it was wrong in three distinct ways (confirmed by independent verification). The timezone-less `at` was interpreted by the browser as local time, so in America/New_York a mismatched mark was drawn solid, while in Pacific/Kiritimati a pin picked just moments ago was drawn dotted. Editing just the note turned it off. A pin picked on the old PDF after the manuscript was edited never entered the judgment at all. Now the same mark gets the same result across Asia/Seoul, America/New_York, and Pacific/Kiritimati.
- On startup, the current build (which may have been created by an older instance and isn't yet in history) is registered once. If the manuscript hasn't changed since that build (`src_mtime` ≤ the build's reference time), the current manuscript's fingerprint is adopted as that build's fingerprint — so the first pin after startup isn't falsely flagged by a rebuild that didn't actually change the manuscript.

## Asynchronous rebuild (`/api/rebuild?async=1` + `GET /api/build`)

The synchronous `/api/rebuild` ties up the request for tens of seconds. With `?async=1`, as soon as the build lock is acquired it returns `202 {"state":"running"}`, and the actual build runs in a daemon thread (the locking and decision logic are identical to the synchronous path). Already running: `409`.

A finished build is counted by `build_seq` (a server-side counter incremented per build, persisting across restarts). The viewer remembers the last seq it processed, so if light meta's `build_seq` differs, it notices — and fetches the details for — a build that started and finished entirely within a single 5-second polling gap (one it never saw `running` for). Completion handling (swapping in the new page, showing a toast) happens exactly once per seq. `GET /api/build` polling is **single-flight** — even if the 1-second timer, `visibilitychange`, `focus`, and light polling all fire at once, only one request goes out (before the fix: a returning hidden tab could show the toast twice). A newly opened tab opens the error panel directly, without a toast, if the last build was `ok_errors`·`fail`.

Progress is watched by polling `GET /api/build` every second — but **only while a build is actually running**. It doesn't poll unconditionally every second: the 1-second poller only turns on (a) when this tab clicked [PDF rebuild], (b) when the 5-second light meta poll sees `build.state==='running'` (a build another session/agent started via `curl`), or (c) once at boot to check whether a build is already running — and it stops itself once `state` is no longer `running`. A hidden tab sends no polling requests at all (resumes on focus/`visibilitychange`).

- `phase` runs (only with `--git-pull`) `pull` (pulling upstream) → `copy` (copying the manuscript) → `latex` (latexmk) → `render` (pdftoppm), in order. No percentage is computed (it isn't known).
- `elapsed_s` is time elapsed so far; `last_s` is how long the previous build took (a reference while one is in progress).
- Once finished (`state` is `ok`·`ok_errors`·`fail`), the viewer swaps things in place the same way the synchronous path does. On `ok_errors`·`fail` the error panel (`#build-err`) **opens automatically** — not relying on the toast alone (a toast disappears after 6 seconds with no way to see it again after that). Even with the panel closed, a "build error · view again" chip stays on the status bar as long as `LAST_BUILD_ERR` is set (until the next successful build).
- A build started by someone else is picked up the same way, so reopening the page shows the progress chip continuing if a build is already running.
- Picking is never blocked during a build (`phase=latex`); the response's `warn` gets "a build is in progress, results may shift" appended.

## Rebuild (`/api/rebuild`, synchronous)

One lock, one build at a time. If a build is already running, it doesn't wait — `409 {"ok": false, "busy": true}`. With multiple documents (`--doc`), the lock, build state (`GET /api/build?doc=`), build history, and `build_seq` are all kept **per document** — different documents build concurrently (each has its own build folder, so they never step on each other's `.aux`). `--git-pull` runs once per repository (§`--git-pull`).

| `state` | Condition | On screen |
| --- | --- | --- |
| `ok` | A new PDF came out and the LaTeX log has no `! ` line | Swapped to the new pages |
| `ok_errors` | A new PDF came out but there's a `! ` line (e.g. `\undefinedmacro` under nonstopmode) | Swapped to the new pages + error notice |
| `fail` | No new PDF (PDF mtime < start time) or a timeout | **The previous pages stay** |

Response: `{"ok": <state≠fail>, "state", "errors": [{"line", "msg"}], "log", "elapsed_s", "head", "pull"}`, plus `pages` (new page count) on success. `errors` is up to 5 `! ` lines and their following `l.<n>` line. `head` is the short hash of the commit this build compiled (only on success; matches `<state_dir>/head.txt`). `pull` is only filled in with `--git-pull` — §`--git-pull`, below. `log` follows §Trimming agent responses.

Page images are drawn first into a new directory `pages-<build_id>/`, then the pointer file `pages.cur` is atomically swapped — pages keep loading without interruption during the build, and for a moment through the old URL right after the swap. The viewer swaps in the new images without a page reload, keeping whatever page and note you were on.

## `--git-pull`: pulling remote main before a rebuild

Even after a co-author merged a PR, the server's manuscript checkout stayed put — the viewer kept showing the old manuscript. With `--git-pull` on, the remote main is checked right after startup and then every 60 seconds. When it fast-forwards to a new commit, a PDF rebuild is scheduled for each LaTeX document. If the current commit differs from the commit the PDF was built from, it also rebuilds at startup (even with `--no-build`). If another build is already in progress, it re-checks 3 seconds later. Being dirty, diverged, missing an upstream, or a remote error shows the reason on a status chip at the top and keeps the previous PDF. A manual rebuild (sync or async) also runs the same `pull` phase before copying.

The automatic check only fast-forwards when the current branch is `main` and its upstream is also `*/main`. Any other branch shows `blocked:not_main`. A view-only PDF document is never a target for a rebuild after a Git pull. The manuscript checkout the server uses needs to stay clean on its own.

1. Find the git repository root that `--manuscript` belongs to (`git -C <ms> rev-parse --show-toplevel`). If none, `skipped:not_git`.
2. `git fetch --quiet` (the upstream remote, 30-second timeout). A failure or timeout gives `error:fetch_failed`/`error:fetch_timeout`.
3. If the current branch has no upstream (`@{u}`), `skipped:no_upstream`.
4. If `git status --porcelain --untracked-files=no` is non-empty, `skipped:dirty`.
5. `git merge --ff-only @{u}` — a failure (diverged) gives `skipped:diverged`. Never creates a rebase or merge commit as a substitute.
6. The result `{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}` is attached to the build result's `pull` field (`/api/rebuild` response·`/api/build`·`builds.json`'s last result). `ok` means the commit changed via fast-forward; `up_to_date` means the repository is fine but there was no new commit.

With multiple documents, pulls are serialized behind a single lock; if another document's build already pulled within the last 20 seconds, this one reuses that result with `shared: true` attached, rather than pulling again — so two simultaneous rebuilds never race on fetch/merge (`.git/index.lock`), and one document's copy step never sees the tree change mid-copy. A single-document instance pulls on every build as before.

**A `skipped`·`error` pull still lets the build continue against the current checkout** — a pull is a nice-to-have, not a build prerequisite. Every git call runs via `subprocess.run([...])` with no shell, and user input is never interpolated into the arguments. When pull is `skipped`/`error`, the viewer appends one line with the reason to the build-complete toast (e.g. `git pull 건너뜀(dirty)`, "git pull skipped (dirty)"); when `ok`, it appends `원격 반영 <head_before>→<head_after>` ("pulled remote: … → …"). `up_to_date` has nothing new to announce, so nothing is appended.

## Trimming agent responses

Even on success, the synchronous `/api/rebuild` used to carry several KB in `log` (font paths, etc.), wasting agent tokens. Now `log` (`/api/rebuild`)·`log_tail` (`GET /api/build`) are dropped from the response entirely when `state=="ok"`. On `ok_errors`·`fail`, they're trimmed to the last 40 lines. `?log=1` (on either) turns the trimming off and returns the full tail (4000 characters) — the viewer's error panel always sends this flag, so its behavior is unaffected. Internal state (`BUILD_STATE`·`builds.json`) always keeps the full log regardless of trimming.

## View-only PDF documents

A `.pdf` document under `--doc` has no LaTeX build. A watcher thread checks that PDF's `mtime:size` every 3 seconds, and if it differs from when the pages were last drawn (`docs/<key>/pdf_sig.txt`), redraws the pages in the background — through the same build path (`_build_tracked`), so `GET /api/build?doc=<key>`'s `state`·`phase:"render"`·`build_seq`·build history all behave exactly like a LaTeX document, and the viewer updates the screen as if a rebuild had finished. Because the fingerprint is a hash of the PDF's content, an old pin on a changed PDF is drawn dotted (an estimate, §Position estimation). A failed draw doesn't retry against the same file (it only retries once the file changes). `stale_build` is always `false`. `POST /api/rebuild?doc=<key>` is `400`.
