# Identity and SourceRange repair plan

**Goal:** Preserve verified identity values and enforce immutable source-range bounds.

**Design:** [Approved scope and design](../specs/2026-10-03-identity-source-range-design.md).

**Architecture:** Keep identity parsing in `security/access.py` and range invariants in `pins/location/range.py`. Use the standard library and the existing platform integer predicate.

**Tech stack:** Python, pytest/Hypothesis, Ruff, mypy, existing repository verification tools.

## Task 1: Reproduce the failures

Add regression tests alongside identity and location code. Run them against unchanged production code and confirm malformed identities inherit roles and invalid or mutable ranges are accepted.

## Task 2: Repair the two boundaries

Decode login headers separately from display text, validate the complete decoded login, and raise the existing authentication refusal. Freeze source lines and validate integer endpoints in the constructor. Adjust existing parser tests for refusals and immutable snapshots.

Run the new tests with the identity, location and web parser suites. Confirm normal Unicode identity decoding and normal snippet output remain compatible.

## Task 3: Synchronize and verify

Update the authentication and coding-rule Handbook topics. Review the diff for API, storage, dependency and security-policy drift. Run the repository's pytest, instance shell tests, Ruff, ShellCheck, boundary checker, mypy (default and Darwin), TypeScript and strict-ratchet checks.

Snippet resource limits, deployment and commits are outside this plan.

## Verification record

- Initial regression run against unchanged production code: 19 failed, 2 passed. Additional encoded-header tests exposed 6 failures in the first repair and 2 failures for raw folded controls; all were repaired before completion.
- Final affected suites (`security/tests`, `pins/location/tests`, `web/tests/test_web_parse.py`, serial): 429 passed, 1 skipped, 73 subtests passed in 6.58s.
- Final core suite (`pytest -q -rs -m 'not browser and not tex'`): 2722 passed, 1 skipped, 1584 subtests passed in 60.83s. The skip needs a real state-directory copy.
- Full suite before the last decoder refinement: 3027 passed, 8 failed, 29 skipped, 2031 subtests passed in 195.88s. Six failures were stale installed package metadata (0.4.9 versus source 0.4.10); reinstalling the development package resolved them, and the CLI suite then passed all 9 tests. Two viewer alignment subtests at width 908 measured a 0.55px offset against a 0.5px tolerance; both also failed in an archived, unchanged HEAD. TeX tools and the real-state fixture account for the skips.
- Instance shell tests: 202 passed, 0 failed. Ruff check/format, ShellCheck, feature boundaries, mypy (default/Darwin), TypeScript and strict ratchet passed. Final Python static checks followed the decoder refinement. `git diff --check` passed. Remote main matched the starting HEAD.
- Handbook publication check failed on five existing links in `purpose.md`, `viewer.md` and `workflow.md`. The unchanged HEAD reproduced the same failures; publication build was not run after the failed check. Separate installation smoke and live Tailscale/proxy checks were not run.

Review applied the Python, modeling and structure references of `code-implement`, Python testing guidance, and `code-security`: constructor invariants, immutable snapshots, complete identity parsing, closed authentication failures, compatible response fields, colocated regression/property tests and accurate docstrings. No runtime dependency, cross-feature import, permission grant, route or storage-format change was added. The range module uses the existing platform integer predicate. Token priority, peer trust, admission and role matrices were exercised by the security suites. Size limits remain explicitly deferred; these checks do not establish whole-system security.
