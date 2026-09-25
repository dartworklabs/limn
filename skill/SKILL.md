---
name: limn
description: "Work with Limn, a browser viewer that turns a region picked on a LaTeX manuscript PDF into a .tex file:line range plus a request note (a pin). Use it when the user gives a Limn URL, when the paper repo's AGENTS.md points to a Limn instance, when asked to process the open pins in pins.md (\"check the pins\", session start), or when the user wants to point at a spot in the manuscript PDF instead of pasting a screenshot."
---

# Limn

English | [한국어](SKILL.ko.md)

Limn (림, "to depict clearly") shows the manuscript PDF in a browser. A person drags over a region; SyncTeX maps it back to the `.tex` file and line range; Limn stores it with a note as a **pin** (a TODO with a location attached). Instead of a screenshot (1,000–1,600 tokens, no location) the agent receives one line such as `sections/method.tex L493-L501` (≈35 tokens) and reads and edits the source directly. Co-authors on the same tailnet leave pins through the same address, and Limn records who left each one.

## Glossary

Terms are defined once here and used with exactly this meaning below.

| Term | Meaning |
| --- | --- |
| **Limn** | The app: a stdlib-only Python server plus its browser viewer. |
| **instance** | One served manuscript: a name, a local port and a tailnet port, a state directory. A long-running instance is the systemd user unit `limn@<name>`. |
| **pin** | A picked PDF region, mapped to a file and line range, plus the request note. |
| **`pins.md`** | The agent work list: a Markdown table of open pins that Limn rewrites as pins change. |
| **open pin** | A pin that is neither closed nor dropped. Only open pins appear in the main table. |
| **question pin** | A pin marked `질문` ("question"): it asks something rather than requesting an edit. |
| **awaiting review** | A pin an agent has closed; a human must confirm it. Listed under `## 검토 대기` ("awaiting review") at the bottom of `pins.md`. |
| **assignee** | Who a pin is for: `agent` (the default) or a person. A person-assigned pin shows `→ @이름` ("→ @name"). |
| **claim** | A short-lived "in progress" lock with an ETA, shown as `처리 중(<이름>, 약 N분)` ("in progress (<name>, about N min)"). |
| **view-only document** | A PDF served without sources (e.g. reviewer comments). Its pins have a page and region, but no line numbers. |

## When to use, when not

Use it when the user wants to point at a place in the manuscript PDF (instead of pasting a screenshot), or when open pins are waiting to be processed.

Do not use it when:

- the manuscript has no working SyncTeX build: fix the build first;
- you already know the file and line: just edit;
- the manuscript is Typst: out of scope (SyncTeX is LaTeX-only).

## Agent contract

### Base URL

`<base>` is `https://<host>.<tailnet>.ts.net:<ts_port>` when you reach the instance remotely, and `http://127.0.0.1:<port>` on the machine that runs the server. `GET <base>/api/version` returns `{"name":"limn","version":...}`; use it to confirm that the address is a Limn instance.

### What you read

- `pins.md`: `curl -s <base>/pins.md` remotely, or `Read` `<state_dir>/pins.md` on the server machine.
- `GET <base>/api/pins`: open pins as JSON, with current line numbers and each pin's `rev`. `GET <base>/api/pins/{id}` returns one pin with its whole thread.

### What you may do

- Claim one pin, right before you edit it, with an `eta_min` estimate (step 4).
- Reply to a pin (`/reply`).
- Close a pin with `reply` and `ref` (step 6). When you close through the tailnet address, send `"review": true`.
- Rebuild the PDF after editing (§Rules).

### What you must not do

- **Never confirm.** `POST /api/pins/{id}/confirm` is for humans only and returns 403 without a tailnet identity. Awaiting review exists so that a human has looked at what an agent closed; an agent confirming its own work defeats it.
- Do not process, unless the user explicitly asks for that pin: pins claimed by someone else, pins in `## 검토 대기`, or pins whose number cell shows `→ @이름` (assigned to a person).
- Do not edit the manuscript for a question pin unless the question implies an edit.
- Do not process pins from a different repository: if the `pins.md` repo header does not match `git remote get-url origin`, stop and report.
- Do not call `/api/clear`.

### Processing pins

1. **Read.** Remotely: `curl -s <base>/pins.md`. On the server machine: `Read` `<state_dir>/pins.md`.
   - The table is `| # | 쪽 | 위치 | 범위 | 메모 |` (# · page · location · range · note). `위치` (location) is a path relative to `--manuscript` plus `L<lo>-L<hi>`.
   - **Several documents**: pins are grouped in subsections `## <document name> · \`<key>\` · \`<path>\`` (manuscript, response letter, cover letter, …). Pin numbers are unique across documents.
   - **View-only document subsections** (`— 보기 전용 PDF(줄 번호 없음)`, "view-only PDF (no line numbers)") have no lines. The location cell reads `쪽 N, 영역 …` (page N, region …), and the `«…»` before the note is the text inside that region. Work out what the pin points at from the page, the region text and the note, then find the place to edit in the LaTeX document. If you cannot find it, do not close the pin; report it.
   - **Check the repository (mandatory).** If the header line `논문: <label> · 저장소: <url>` (paper: … · repository: …) is present, compare `<url>` with `git remote get-url origin` in your checkout. If they differ, these are another paper's pins: do not process them; stop and report. This is the safeguard when several instances run at once.
2. **Match the base commit.** If there is a line `기준: <head> · 빌드 <built_at>` (base: … · built …) — in the header for a single document, per subsection for several — and you work in a different checkout, first check that `git rev-parse --short HEAD` matches `<head>`.
3. **Decide the scope.**
   - Whoever is asked processes **all** pins open at that moment, regardless of who left them (author decision, 2026-09-22).
   - If the user named pin numbers, only those.
   - **Skip**: `처리 중(<이름>, …)` (someone else holds a claim; do not take it over); pins in the `## 검토 대기` subsection at the bottom (already processed, waiting for a human); pins whose number cell has `→ @이름` — **skip person-assigned pins** (process one only when the user explicitly asks). `참고 @이름` ("FYI @name") is a notify-only tag; do not skip for it.
   - `질문` in the number cell marks a question, not a place to edit (step 6). `다시 열림` ("reopened") is a pin sent back from review: edit again according to `다시 연 이유` ("reason for reopening") in the note cell.
4. **Claim just in time.** Always claim only that pin, right before you edit it. Never claim several pins at once: pins you have not touched yet get locked and others cannot take them (observed 2026-09-23: 23 pins claimed in one go). Put your estimate in minutes in `eta_min`; the viewer shows it as `처리 중 · 약 15분 · 20:40쯤` (in progress · about 15 min · around 20:40).

   ```bash
   curl -s -X POST <base>/api/pins/<id>/claim -H 'Content-Type: application/json' -d '{"eta_min": 10}'
   ```

   | Edit | `eta_min` |
   | --- | --- |
   | Typo or single word | 5 |
   | One sentence | 5–10 |
   | Rewrite a paragraph | 10–20 |
   | Restructure / several places | 20–40 |
   | Needs a rebuild to check | +5 on top |

   - On `409 claimed`, skip the pin.
   - If you run late, claim again with the same identity and a new estimate (an extension). Otherwise the viewer shows `예상보다 늦어짐 (+5분)` ("later than expected (+5 min)").
   - The lock releases itself after `ttl_min` (default: twice the estimate, clamped to 30–120 minutes). It is a safety net; do not use it in place of an estimate.
5. **Edit.** `Read` `L<lo>-L<hi>` to see the context and edit as the note asks. If an earlier edit may have shifted lines, fetch the realigned values from `GET <base>/api/pins`.
6. **Close.** A pin closed by an agent does not become done; it goes to **awaiting review**. When a human clicks [확인] (confirm) in the viewer it is done; [다시 열기] (reopen) sends it back as an open pin with a reason.
   - **Edit-request pin**: after editing, close it with what you changed (`reply`, ≤500 chars) and the PR number or commit (`ref`, ≤80 chars). The viewer's [변경 보기] (view changes) uses `ref` to find the commit.
   - **Question pin**: do not edit the manuscript (only if the question implies an edit). Post the answer as a reply, then close.
   - When closing through the tailnet address (`https://…ts.net`), the request carries a human identity and would be marked done immediately, so put `"review": true` in the body. Through local `127.0.0.1` it goes to awaiting review without it.
   - **Agents never confirm.** `POST /api/pins/{id}/confirm` returns 403 without a human identity (tailnet header).

   ```bash
   curl -s -X POST <base>/api/pins/3/close \
     -H 'Content-Type: application/json' \
     -d '{"reply": "Retitled the section to …", "ref": "PR #227", "review": true}'
   curl -s -X POST <base>/api/pins/4/reply \
     -H 'Content-Type: application/json' \
     -d '{"text": "The interval is the 95% confidence interval; if it contains 0 the effect is not significant."}'
   ```

7. **Verify.** If you processed several pins, read the pin table again as in step 1. Confirm that the number of open pins is 0 (or all are claimed) and report to the user.

### Markers in the number column

After the number, the number cell carries short plain-word markers joined by ` · ` (they replaced the older symbols; see [api.md](../docs/api.md) §pins.md format). Example: `7 · #6 범위 안 · 처리 중(에이전트 B, 약 10분)`. The markers are Korean literals; match them verbatim.

| Marker | Meaning | What to do |
| --- | --- | --- |
| `#N 범위 안` | Lies entirely inside pin `#N`'s range ("inside #N") | Fix together with `#N` and close both |
| `#N과 같은 범위` | Same line range as `#N` (the same place picked twice) | Fix together with `#N` and close both |
| `#N과 일부 겹침` | Partially overlaps `#N` | For reference only; they may be processed separately |
| `처리 중(<이름>, 약 N분)` | Someone else holds a valid claim ("in progress (<name>, about N min)"; `예상 초과` means past the estimate) | Skip |
| `수정됨` | The note or range was edited after saving ("edited") | — |
| `위치 잃음` | The location was lost (stale) | See the stale rules below |
| `«…»` | Quote of the rendered text (≤60 chars, `…` if truncated) | Use only as a search hint; never as `Edit`'s `old_string` |
| `[<작성자>]` | Author name in front of the note, when there are two or more authors | Not an assignment rule; for reports and `reply` only |
| `질문` | A question pin, not a place to edit | Answer with a reply and close (edit the manuscript only if the question implies it) |
| `다시 열림` | Sent back from review ("reopened") | Edit again per `[스레드 N건] 다시 연 이유(…)` in the note cell |
| `→ @이름` | Assigned to a person (an old pin without an assignee is a question addressed to a person) | Skip unless the user explicitly asks |
| `참고 @이름` | Notify-only @tag ("FYI @name"); the assignee is still the agent | Process as usual |

### Rules

- Stale (`위치 잃음`): if you have just edited that range yourself, check the source and you may close it. Otherwise do not close by guessing; report it.
- If the location is gone (file deleted, section moved) or the context does not match the note, do not close; report it.
- No `/api/clear`: it wipes unprocessed pins too. Close pins one by one.
- Closing an already closed pin changes nothing (the `reply` is discarded as well). To change the reason, `/reopen` and then `/close` again.
- `close` and `drop` clear the claim. Call `/unclaim` only when you give up a pin or hand it over.
- To edit a pin's note or range, send the `rev` from `GET /api/pins` as `base_rev` to `/edit`. On `409 conflict`, look at the latest `pin` in the response and resend. To only append, use `note_append` (no `base_rev` needed).
- After editing the manuscript, rebuild that document's PDF (`POST /api/rebuild?async=1&doc=<key>`; omit `doc` for a single document). Picks on an old PDF map to wrong line numbers. View-only documents have no rebuild.

## Starting a viewer for the user

1. **Install** (once): `uv tool install git+ssh://git@github.com/dartworklabs/limn@v0.1.0`, then check with `limn version`.
2. **Check the port (mandatory).** Never bind without checking.

   ```bash
   ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
   ```

   - If it is an existing instance for the same `--manuscript`, reuse it; do not start another.
   - Without `--port` the server picks a free port and prints it in the startup log.
   - To stop a one-off server, do not `pkill -f limn`; use `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
3. **Run.**
   - One-off: `limn serve --manuscript <dir> [--main main.tex | --doc KEY=NAME:PATH ...] [--port N] [--state-dir DIR]`. `--doc` (repeatable) serves several documents from one paper repo on one address: `.tex` is LaTeX, `.pdf` is view-only. When starting servers by hand, give **each manuscript its own `--state-dir` and port**, or pins get mixed. Other arguments (`--git-pull`, `--label`, `--accent`, …): `limn serve --help` and [operations.md](../docs/operations.md).
   - Long-running, one per manuscript: `limn add <name> --manuscript <dir> ...` assigns ports, writes the config, enables `limn@<name>` and sets up `tailscale serve`. Then `limn list`, `limn status <name>`, `limn url <name>`. `limn snippet <name>` prints the block to paste into the paper repo's AGENTS.md so that agents find the instance. Operator guide: [instances.md](../docs/instances.md).
4. **Expose — hard rules.**

| Item | Rule |
| --- | --- |
| Binding | `127.0.0.1` only. Never `0.0.0.0`, and no flag to change it |
| Exposure | `tailscale serve` only. Never `tailscale funnel` (public internet) |
| Before announcing the address | A `curl` from inside the tailnet returns `200`, and `tailscale serve status` shows tailnet only |
| Host / Origin check | Unknown `Host` or cross-origin `Origin` gets `403`. `--no-origin-check` is an escape hatch only |
| Authentication | None (the tailnet is the boundary). To restrict, `--allow <login>,…` |
| Shutdown | `tailscale serve --https=<port> off` |

## Common API

| Route | Meaning |
| --- | --- |
| `GET /api/version` | `{"name":"limn","version":...}` |
| `GET /pins.md` | The agent pin table (remote entry point) |
| `GET /api/pins` | Open pins as JSON (with `rev`). `?all=1` includes closed pins |
| `POST /api/pins/{id}/claim` | Mark in progress. Body `{"eta_min": 1..240, "ttl_min": 1..120}` (both optional; values above the cap are clamped): estimate and lock |
| `POST /api/pins/{id}/unclaim` | Release the claim |
| `POST /api/pins/{id}/close` | Close. Body `{"reply", "ref", "review"}`; closed by an agent → awaiting review |
| `POST /api/pins/{id}/reply` | Reply `{"text"}` (≤1000 chars). State unchanged |
| `GET /api/pins/{id}` | One pin with its whole thread (`pins.md` carries at most 3 thread entries) |
| `POST /api/pins/{id}/confirm` | Awaiting review → done (**humans only**; 403 without an identity header) |
| `POST /api/pins/{id}/reopen` | Reopen (clears the old `reply` and `ref`). Optional `{"reason"}` stays in the thread |
| `POST /api/pins/{id}/edit` | Edit note or range (`base_rev` required), or `note_append` |
| `POST /api/pins/{id}/drop` | Remove a mistaken pin (`/restore` brings it back) |
| `POST /api/rebuild?async=1` | Rebuild the PDF; progress at `GET /api/build`. With several documents add `&doc=<key>` to both |
| `GET /api/docs` | Document list (key, name, kind, open pin count, build state) |
| `GET /api/meta?light=1` | Read-only state (`stale_build`, …). `&ev=<seq>` returns events addressed to you (for browser notifications) |

## Reference files

| For | Open |
| --- | --- |
| All endpoints, request limits, edit/close/claim/overlap details, threads, awaiting review, @tags, events, pin schema, `pins.md` format | [api.md](../docs/api.md) |
| Rebuild (sync and async), `--git-pull`, auto-sync, position estimate (`est`) | [build-sync.md](../docs/build-sync.md) |
| Architecture, the two reverse-mapping paths, range ladder, line realignment (`anchor`), storage safety, author attribution, viewer states, several documents and view-only PDFs, known limits | [design.md](../docs/design.md) |
| All server arguments, `--doc`, port avoidance, security details (why Host/Origin), systemd, `tailscale serve`, state files, using the viewer | [operations.md](../docs/operations.md) |
| Per-manuscript instances: `limn add`, config keys, ports, updates, removal | [instances.md](../docs/instances.md) |

## Related

- If your runtime has a manuscript-editing skill (e.g. `manuscript-revision`), apply its editing discipline when closing pins with edits; for a broken LaTeX build, use its build-fixing skill (e.g. `latex-editing`).
- General "serve results to the user" guidance may allow other bindings; Limn is the exception and is fixed to `127.0.0.1` + `tailscale serve` ([operations.md](../docs/operations.md) §security).
