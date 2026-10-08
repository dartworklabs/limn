# Non-UI measurement and adoption audit

## Scope and authority

This audit recovers measurement evidence and checks installed and running versions. It changes no picker,
viewer, manuscript, pin, credentials, service, or Tailnet configuration. UX/UI work remains stopped under
[issue #220](https://github.com/dartworklabs/limn/issues/220). Machine-specific inventory, diagnostic scripts,
raw map bytes, and the operation plan remain outside the product repository in the worker's operator evidence
directory; this review records conclusions and acceptance limits only.

Handbook authority: `purpose.md` owns source-of-truth routing; `architecture.md` preserves feature ownership,
empty runtime dependencies, security boundaries, and transaction writes; `domain.md` owns real element
geometry and selection ladders; `verification.md` separates measured checks from their limits;
`instances.md` and `workflow.md` distinguish installed packages, live `/api/version`, and released tags.
Historical ADR-0015 is frozen. The original issue acceptance is authoritative until explicitly changed.

## Issue #209 acceptance reconciliation

[Issue #209](https://github.com/dartworklabs/limn/issues/209) requires a meaningful reduction in unrelated
choices **with the same measurement harness**, and additive map-contract changes. The picker repair and
`tools/measure_figure_pick.py` are merged in [PR #218](https://github.com/dartworklabs/limn/pull/218).
The map format remains `limn-figure-map/1`; the repair adds no required map field.

The producer map was recovered directly from the historical producer head
`e4770c63e8cd64b6f27703ffaca63d54f20b1289`, Git blob
`70297b1f7037da5334279531a9be36e265543675`. Its SHA-256 is
`a380fef5f7afd92535abd03d99416250bb3eb5b6322f32bb801a2c19abec46e6`, matching the merged review.
No producer code was executed and no source manuscript was opened.

The element counts reconcile exactly rather than establishing different corpora:

| Count convention | Recovered map | ADR-0015 |
| --- | --- | --- |
| All pages, including two root-only pages | 24 pages, 7,855 total elements | 24 pages, 7,855 elements |
| Drawable pages, excluding the two root-only pages | 22 pages, 7,853 total elements | 22 pages, 7,853 elements |
| Non-root elements only | 7,831 | Not the ADR's counting convention |

The original 59,492-drag harness remains unrecovered. A nontruncated historical Git tree, producer PR #257's
files and measurement references, the available relevant branches, and the producer's measurement-period
commit filenames yielded no harness. A completed bounded search of 27 Limn/concept temporary directories on
the operator host inspected 10,852 filenames; remaining measurement candidates concerned fonts rather than
the figure experiment. Surviving D6 commit-message files describe the experiment but give no script path.
These searches do not prove that a deleted or differently named untracked script cannot exist elsewhere.

An additional narrowly scoped recovery searched the October 5–6 saved-session records: 333 local Codex files,
two relevant local Claude project files, and 432 operator-host Codex/relevant Claude files. Only exact drag-count
or producer-branch matches were inspected for measurement tool commands; no original generator was recovered.
An unrelated numeric substring match was excluded and its extracted command discarded. No unrelated session
messages or credentials were retained as measurement evidence.

The checked-in reconstruction ran twice with byte-identical JSON output:

```sh
uv run python tools/measure_figure_pick.py "$MAP" --seed 2090015 --per-page 150 --per-parent 20
```

It generates 15,790 single-target and 3,113 sibling drags. Its frozen legacy rule was separately compared
with the actual pre-repair picker from commit `38dc0d7f728ce1194db7ab87d926da46a5b95816`: zero chosen-element
mismatches across all 18,903 reconstructed samples. This establishes the before/after algorithm comparison,
not equivalence to the unavailable original drag generator or measured human accuracy.

| Cohort | Legacy exact | Current exact | Legacy unrelated | Current unrelated |
| --- | --- | --- | --- | --- |
| All single-target drags | 74.44% | 79.06% | 12.24% | 8.85% |
| Absolute padding | 45.28% | 65.26% | 31.38% | 17.67% |
| Thin elements with padding | 6.83% | 63.57% | 66.60% | 35.48% |
| Tiny elements with padding | 10.03% | 54.76% | 79.08% | 39.80% |
| Siblings, direct parent | 38.48% | 42.82% | 13.52% | 6.49% |
| Large tight targets | 58.57% | 58.37% | 22.31% | 23.31% |
| Large partial targets | 52.99% | 52.39% | 25.30% | 26.69% |

Large tight targets lose one exact match out of 502; large partial targets lose three. Relative to ancestor
pruning alone, hit expansion lowers direct-parent sibling matches from 45.33% to 42.82%. These trade-offs
remain visible. Existing picker and measurement tests pass: **43 tests, two subtests, 3.16 seconds**.

**Closure assessment: keep #209 open.** The additive-contract condition and reproducible reconstructed
improvement are evidenced; the same-original-harness condition is not. A faithful completion route is to
recover and replay the original generator. An approval-ready alternative is to explicitly replace that
condition with: "Run the checked-in reconstruction against the recovered map hash, seed 2090015, 150 targets
per page, and 20 sibling samples per parent; compare the verified pre-repair picker with the current picker on
identical samples, retain cohort regressions and ladder trade-offs, and state that the original experiment is
not reproduced." That alternative is a proposed acceptance change, not an accomplished task or silent waiver.

## Functional adoption and release assessment

Read-only Tailnet HTTPS `/api/version` probes returned **200 and version 0.4.20 for all 11 known manuscript
services**: two managed by systemd and nine by launchd. The remote installed package is a noneditable uv tool
pinned to `v0.4.20`, commit `d21f51819de0ac62edeecc2a739fba50c8455a34`. Local services use the baseline source
checkout at `38dc0d7f728ce1194db7ab87d926da46a5b95816`, also version 0.4.20; no Limn uv tool is installed there.
Three local services correctly reject unauthenticated loopback probes with 401 but return 200 over Tailnet.
Tokens, manuscript content, and pin data were not needed for this inventory.

Consequently, merged functional repairs are not deployed to these services. The current main commit
`b1487ecd6ea7cdb3e424df1f7e662f7e49049bee` declares **0.4.21 Unreleased**. Its
[main CI run](https://github.com/dartworklabs/limn/actions/runs/37730632511) completed successfully; this is
separate from the draft UX PR's failed CI and from release or live adoption evidence.

A whole-package upgrade to current main would also change the running viewer: PR #218 includes previously
approved, merged appearance and interaction changes that the 0.4.20 services do not yet have. Although those
changes predate the current stop, a non-UI-only follow-up does not authorize their first live adoption.
[PR #219](https://github.com/dartworklabs/limn/pull/219) is a separate open draft at
`12137ed495768c3319377ae72ef9c3ba488fe696`; its mobile search, page navigation, and inline assignment candidate
must remain excluded from any artifact. An upgrade from that checkout is especially disallowed.

The concrete operation plan remains outside this repository. It gives two alternatives: a separately reviewed
functional-only artifact based on v0.4.20 whose viewer bytes remain identical, or an explicitly authorized
future mixed-package release. Either affects two remote systemd services and nine local launchd services;
updating the remote uv tool alone cannot update the local source-backed services. The plan pins the artifact,
requires the corresponding CI and contract checks, records exact previous refs, stages restart verification,
and restores those refs if adoption fails. Neither deployment nor a v0.4.21 release was performed.

## Documentation gate repair

The pinned publisher rejected two `workflow.md` links to the ADR directory. The existing tracked
`docs/adr/index.md` already catalogs the numbered records, so the repair changes only those two targets
to that explicit file. The catalog and frozen numbered ADRs remain unchanged. Pinned publisher checking
and HTML building both exit successfully; the Handbook reference tests pass (four tests). Raw logs are
retained as `handbook-navigation-check.log`, `handbook-navigation-build.log` and
`handbook-navigation-refs.log` in the external evidence directory.
