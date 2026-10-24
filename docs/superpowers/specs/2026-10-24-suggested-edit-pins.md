# Suggested-edit pins

## Request and approval status

The owner asked for a way to write the exact replacement text while pinning, instead of describing the change in a memo and waiting for an agent to reword it: “좋아 그렇게 가자 기능 개발해줘”. That answer chose the *suggested edit* option over direct source editing, after being told that direct editing would break the read-only manuscript invariant and pull branch, commit, push and PR handling into the server.

**Owner approval.** After reading this design and its three open questions, the owner replied **“승인. 림 수정도 실시”** (approve; carry out the Limn change). That approves the design, the ADR-0020 record, and the defaults proposed for the open questions: the `pins.md` strings as written, `SUGGEST_MAX` 16,000 characters, and the 80-line range cap. It authorizes implementation, Handbook and skill updates, and a pull request. The viewer part still needs the four-device-group PoC shown to the owner before it reaches `main` ([workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다); the approval does not cover a release, a version tag, or updating running instances.

The superpowers brainstorming delegation is unavailable in this session; the design below was written directly against the current Handbook and code.

## 현재 권위와 상태

- **role / path**: purpose / `docs/handbook/purpose.md`. Pins are located TODOs; the server reads the manuscript and never writes it.
- **role / path**: architecture / `docs/handbook/architecture.md`. Manuscript reads go only through checked `ManuscriptFile` handles; builds run on an rsync copy; pin files are written only through `PinStore.transact()`; the runtime is stdlib-only. Stop signals that this design hits: *agent contract change* (new `pins.md` marker and section, new API fields) and *storage format change* (new optional record field).
- **role / path**: 일반 주제 / `docs/handbook/api.md`. `POST /api/pin` stores a whitelisted field set; `POST /api/pins/{id}/edit` requires `base_rev`; valid unknown fields are read and written back unchanged, so an older server keeps a new field it does not understand; `pins.md` deliberately carries no snippets; the Korean strings of `pins.md` are part of the contract.
- **role / path**: 일반 주제 / `docs/handbook/domain.md`. Line pins follow their text through anchor re-sync; a closed pin accepts only memo-level edits.
- **role / path**: 일반 주제 / `docs/handbook/viewer.md` §패널 정리. Composer order is location → quote → memo → kind → overlap → range group (caption, ladder, excerpt); the edit card reuses the excerpt.
- **실제 정본**: `src/limn/pins/` (model, editing rules, listing/render), `src/limn/pins/location/range.py` (`snippet_api`), `src/limn/viewer/`.

## 지켜야 할 현재 불변식

1. Limn never writes manuscript files. A suggestion is stored on the pin; applying it is the agent's normal edit → commit → PR → close cycle.
2. Existing API paths, fields, status names and `pins.md` strings keep their meaning. Everything in this design is additive.
3. Old records without the new field read exactly as before; an older server (0.4.x) keeps the field on rewrite as a valid unknown field, so rolling back loses nothing.
4. Pin writes go through `transact()`; the suggestion is validated and stored in the same transaction as the rest of the pin.
5. Stdlib-only runtime; no new state file.

## 설계

### What a suggestion is

A suggestion replaces **exactly the pin's line range** `lo..hi` of a LaTeX document with new text. It is stored with the text the author saw, so anyone can tell whether the source still matches.

```json
"suggest": {"base": "원래 줄들\n두 번째 줄", "text": "고친 줄들\n두 번째 줄"}
```

| Field | Meaning |
| --- | --- |
| `suggest.base` | The source lines `lo..hi` when the suggestion was written, joined with `\n`, no trailing newline. Line terminators are compared without `\r`. |
| `suggest.text` | The replacement for those lines, same joining. An empty string means "delete these lines". |

Rules:

- Only line pins of LaTeX documents (`kind: "tex"`). View-only PDF and figure documents refuse it (`400 suggest_unsupported`). Figure line pins are out of scope for now (their scripts have the common-part and re-render rules).
- `hi - lo + 1 ≤ 80` (the snippet cap) and each string ≤ 16,000 characters (`SUGGEST_MAX`, well under the 1 MiB body). Longer ranges cannot carry a suggestion (`400 suggest_too_long`).
- `text == base` is refused (`400 suggest_noop`).
- A pin may carry a memo, a suggestion, or both. The memo then explains *why*.
- The server checks `base` against the file **at write time**: if the current lines `lo..hi` differ, `409 {"reason": "suggest_base_changed", "current": "<current text>"}` and nothing is written. This stops a suggestion from being saved against text the author never saw.

### Computed state (response only, not stored)

`GET /api/pins`, `GET /api/pins/{id}` and every response `pin` add `suggest_state` to pins with a suggestion:

| `suggest_state` | When | Agent action |
| --- | --- | --- |
| `ready` | The current lines `lo..hi` (after anchor re-sync) equal `base` | Replace the lines with `text` verbatim |
| `changed` | They differ (someone edited the passage, or the range was edited) | Do not apply. Reply on the pin with what changed and leave it open |
| `unknown` | The file cannot be read, is outside the tree, or the pin is `stale` | Do not apply; report |

A range edit (`lo`/`hi` or `loc`) without a new `suggest` keeps the stored suggestion; its state then becomes `changed`. The suggestion is never dropped silently.

### API (additive)

| Path | Addition |
| --- | --- |
| `GET /api/snippet?file=&lo=&hi=` | `&text=1` adds `text`: the exact lines `lo..hi` joined with `\n`, unnumbered, only when the range is ≤ 80 lines. The viewer prefills the editor from it |
| `POST /api/pin` | Optional `suggest: {base, text}` in the whitelist. Validated as above |
| `POST /api/pins/{id}/edit` | `suggest: {base, text}` sets or replaces; `suggest: null` removes. Still needs `base_rev`. Checked against the lines at the pin's range *after* this edit's own range change. A closed pin refuses it (`409 done`) like other non-memo edits |
| `POST /api/pins/{id}/close` | Unchanged. The agent sends `changes` covering the replaced lines and `ref` as usual |

### `pins.md` (additive)

- Number cell marker, joined with ` · ` like the others: `제안 수정`, or `제안 수정(원문 바뀜)` / `제안 수정(확인 불가)` for `changed` / `unknown`.
- A pin with a suggestion and no memo shows `(제안 문안만)` in the memo cell.
- A new section after the open tables and before the review section, present only when an open pin carries a suggestion:

  ````text
  ## 제안 문안

  정확한 바이트의 정본은 GET <base>/api/pins/N 의 suggest.text 다. 아래 블록은 같은 글이다.

  ### #7 · main.tex L120-L123 · 바꿀 준비됨
  ```
  고친 줄들
  두 번째 줄
  ```
  ````

  The fence is one backtick longer than the longest backtick run in the text (minimum three), so the block holds any text without escaping. An empty `text` shows `(이 줄 범위를 지운다)` instead of a block. Multi-document instances prefix the doc key, as the location column does.
- The guidance paragraph gains one contract line when such a pin exists: *제안 수정 핀은 메모를 다시 쓰지 말고 `suggest.text` 를 위치 칸의 줄 범위에 글자 그대로 넣는다 · `원문 바뀜`·`확인 불가` 면 넣지 말고 답글로 알린다.*

### Viewer

- **Composer.** For a line selection in a LaTeX document whose range is ≤ 80 lines, a `[제안 수정]` toggle appears beside the kind control. Turning it on opens a monospace textarea below the memo, prefilled from `/api/snippet?…&text=1` for the current range. While the text is untouched it follows range changes; once edited, a range change keeps the text and shows `범위가 바뀌었습니다 · [원문 다시 불러오기]`. Save sends `suggest` with the `base` the author saw; a `409 suggest_base_changed` shows the current text and keeps the draft.
- **Card.** A `제안 수정` badge (with `원문 바뀜` / `확인 불가` when so). The body shows a line diff of `base` → `text` using the existing source-diff styling, collapsed like the excerpt beyond five lines.
- **Edit card.** The same textarea edits or removes the suggestion.
- **Undo and drafts.** Discarding a selection with a suggestion restores it through the existing `[되돌리기]` path, like the memo.
- The exact layout, sizes and touch behaviour are decided by the four-device-group PoC, not by this document.

### Agent skill

`skill/SKILL.md` and `skill/SKILL.ko.md` gain a short *suggested-edit pins* section: read `suggest.text` from `GET /api/pins/{id}`, check `suggest_state == "ready"`, replace lines `lo..hi` verbatim (no rewording, keep the file's line terminator), commit through the normal PR flow, close with `changes` = the new line range. On `changed`/`unknown`, reply and leave the pin open.

## 설계 이유와 제약

- **Why not direct editing.** Writing the manuscript would reverse invariant 1 and force the server to own branches, commits, pushes and PR creation with credentials on the serving account; a local write would also leave the checkout dirty and stop `--git-pull`. A suggestion gives the author the exact wording while review, CI and history stay where they are.
- **Why store `base`.** Pins move by anchors, and other people edit the same passage. Without the text the author saw, an agent cannot tell a stale suggestion from a current one and might overwrite someone else's change. Storing it costs at most ~16 KB per pin.
- **Why a section instead of the memo cell.** Table cells escape `|` and turn newlines into `⏎`, which is lossy for exact text. A fenced block is exact and still readable; JSON stays the authority.
- **Why only LaTeX line pins.** Those are the pins whose range is plain source lines. Figure scripts and view-only PDFs need rules of their own and are left for a later design.

## 비범위

- Limn applying suggestions, writing files, committing or opening PRs.
- Multiple ranges or multiple alternative suggestions per pin.
- Suggestions on figure documents and view-only PDFs.
- Mapping generated sources back to their origin (for example a `.tex` file generated from Markdown); the agent handles that.
- Automatic re-basing of a `changed` suggestion.

## 검증

- Rules: validation (shape, limits, no-op, unsupported document), `base` check at create/edit including CRLF, state computation after re-sync and range edits, closed-pin refusal. Pure tests next to `pins/editing` and `pins/listing`.
- Storage: round-trip through `transact()`; an old record without `suggest`; a record with `suggest` read by the current code path for unknown fields.
- `pins.md`: marker, `(제안 문안만)`, section ordering, fence length with backtick runs, empty text, multi-document prefix, guidance line only when needed.
- API: `snippet&text=1`, create/edit/remove, `409 suggest_base_changed` writes nothing.
- Viewer: existing guards stay green; new behaviour tests for the toggle, prefill, range change, save, 409, card diff and edit; the four-device-group PoC before merge.
- All gates in AGENTS.md §검증.

## ADR

This design adds to the agent contract and the stored record, so [workflow.md](../../handbook/workflow.md) §결정 기록 calls for an ADR. Proposed: **ADR-0020 제안 수정 핀**, written as `제안` once the owner approves this design and confirms the ADR, and raised to `승인됨` at merge. Handbook topics to update in the same change: `api.md` (fields, `pins.md` section), `domain.md` (state rule), `viewer.md` (composer, card), `architecture.md` only if a new module boundary appears, and the two `skill/SKILL` files.

## Open questions for the owner

Answered by the approval above: the design and ADR-0020 are approved, the `pins.md` strings stay as written, and the limits are `SUGGEST_MAX` = 16,000 characters and 80 lines.
