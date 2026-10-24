# Suggested-edit pins plan

Scope and approval: [suggested-edit pins](../specs/2026-10-24-suggested-edit-pins.md). The owner replied **“승인. 림 수정도 실시”** to the design and its three open questions, approving the design, ADR-0020 and the proposed defaults. The viewer change reaches `main` only after the owner has seen the four-device-group PoC. No release, tag or instance update is in scope.

## Task 1: Records

- [x] Step 1: Record the owner's approval and the answered questions in the spec. Expected: the spec says what is approved and what is not (release, instances).
- [x] Step 2: Write ADR-0020 as `제안` with its index row. Expected: decisions D1–D4, trade-offs, alternatives and consequences; status rises to `승인됨` only at merge.
- [x] Step 3: Write this plan. Commit point: records commit.

## Task 2: Server — store, validate and report suggestions

- [x] Step 1: Add the limits (`SUGGEST_MAX` 16,000 characters, 80 lines) next to `NOTE_MAX`, and the closed refusal reasons `bad_suggest`, `suggest_unsupported`, `suggest_too_long`, `suggest_noop`, `suggest_base_changed`. Expected: values live with the editing rules that use them; reasons are returned values, not raised exceptions.
- [x] Step 2: Parse `suggest` once at the request boundary for `POST /api/pin` and `POST /api/pins/{id}/edit` (`{base, text}` strings, or `null` on edit to remove). Expected: wrong shapes refuse with `400 bad_suggest` before any rule runs.
- [x] Step 3: Decide in the pure editing rules: LaTeX line pins only; range ≤ 80 lines; lengths; no-op; closed pins refuse non-memo edits as today. The base check compares `base` with the current lines `lo..hi` (after this edit's own range change), ignoring `\r`. Expected: `409 suggest_base_changed` carries the current text and writes nothing.
- [x] Step 4: Store `suggest` inside `transact()` with the rest of the pin; reject a malformed stored `suggest` as a broken line like a malformed `el`. Expected: old records read unchanged; a range edit keeps the stored suggestion.
- [x] Step 5: Compute `suggest_state` (`ready`/`changed`/`unknown`) in the listing projection for every pin response. Expected: computed on read, never stored; `stale` or unreadable files give `unknown`.
- [x] Step 6: `GET /api/snippet?…&text=1` adds the exact unnumbered `text` when the range is ≤ 80 lines. Expected: other snippet fields unchanged.
- [x] Step 7: `pins.md`: the `제안 수정` marker (with `(원문 바뀜)`/`(확인 불가)`), `(제안 문안만)` for an empty memo, the `## 제안 문안` section with fences one backtick longer than the longest run, `(이 줄 범위를 지운다)` for empty text, doc-key prefixes for multi-document instances, and the guidance line only when such a pin is open. Expected: existing `pins.md` output is byte-identical when no pin carries a suggestion.
- [x] Step 8: Tests next to the code they pin (rules, input, store round trip, projection, render, HTTP). Watch each new test fail on a plausible break. Commit point: server commit.

## Task 3: Contract documents

- [x] Step 1: `api.md` (fields, refusals, snippet `text`, `pins.md` marker and section), `domain.md` (suggestion rule and state), `architecture.md` only if a boundary moves. Cite ADR-0020; the topics stay complete without the citation. Expected: `test_handbook_refs.py` passes.
- [x] Step 2: `skill/SKILL.md` and `skill/SKILL.ko.md`: the suggested-edit procedure for agents. `CHANGELOG.md` Unreleased entry. Commit point: docs commit.

## Task 4: Viewer and PoC

- [x] Step 1: Composer: a `[제안 수정]` toggle for LaTeX line selections ≤ 80 lines; a monospace editor prefilled from `snippet&text=1`; follows range changes until edited, then `범위가 바뀌었습니다 · [원문 다시 불러오기]`; sends `suggest`; handles `409 suggest_base_changed` without losing the draft; undo restores it.
- [x] Step 2: Card: `제안 수정` badge with state; line diff of `base` → `text` collapsed past five lines. Edit card: edit or remove the suggestion.
- [x] Step 3: `viewer.md` rules and viewer tests; existing guards stay green; typecheck and strict ratchet pass.
- [ ] Step 4: PoC: before/after renders at the four device groups (1440×900; 390×844, 320×720; 768×1024, 1024×768; 344×882, 673×841, 841×673) with measured sizes, and a live loopback instance of each build exposed to the owner through the tailnet. Expected: the owner sees it before merge. Commit point: viewer commit.

## Task 5: Verification and integration

- [ ] Step 1: All gates in AGENTS.md §검증. Expected: green, with real skips reported.
- [ ] Step 2: Push, open the PR (replacing the design-only draft or extending it), wait for CI. Expected: the PR body states the PoC shown and the owner's choice.
- [ ] Step 3: After the owner has seen the PoC: set ADR-0020 to `승인됨`, merge. Expected: no release, version tag or instance update.
