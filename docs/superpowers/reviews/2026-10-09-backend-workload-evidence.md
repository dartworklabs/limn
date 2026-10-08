# Backend workload evidence

Research for issue #222. The numerical proposal in [the workload-limit draft](../specs/2026-10-08-backend-workload-limits.md) remains unapproved. This audit records existing behavior at `45bf1a7d3343f4ec179a3b35e253cc232d709485`; it is not a completed brainstorming/spec approval.

**Recommendation:** defer new paper execution quotas and deadlines. Prioritize a separate transport admission design because idle connections already allocate handler threads before authentication. Existing comparison limits and process bounds should remain the baseline. No measurement here selects a connection count, a per-principal allowance, or a new timeout/output budget.

## Question and bounds

The concrete question was whether source lookup and comparison lookup/execution costs, and existing successful overlaps, support the draft's numerical limits on larger manuscripts.

The preflight fixed two generated corpora, at most four simultaneous HTTP requests and two actual comparison workers, 30-second preparation-tool deadlines, a 20-second HTTP client deadline, a 90-second completion observation window and a 300-second supervised run. Production subprocess time/output limits were used unchanged. Linux eligibility required installed tools, successful bwrap isolation, load below half the available CPUs, at least 2 GiB available memory and 1 GiB scratch space. No private manuscripts or production instance files were inputs.

Source selection and comparison requests used the real application assembly, authentication/authorization boundary, framed HTTP socketpairs and actual processes. Comparison completion used the production bwrap/latexdiff/latexmk pipeline in isolated scratch on a shared Linux host. The transport observation below used a separate preserved real TCP-listener probe. No browser measurement was performed.

## Corpus and environment

Both corpora use an article with `amsmath`, five generated paragraphs, an equation and a small table per page, three pages per included section, and 120 synthetic Git commits. Every page image was rendered at 150 dpi because the production parser derives page count from the complete image directory.

| Corpus | Pages | TeX files | Source lines | Source bytes | Original PDF bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Medium synthetic article | 24 | 9 | 1,210 | 60,027 | 85,130 on macOS |
| Larger synthetic article | 72 | 25 | 3,386 | 172,314 | 148,259 on macOS |

Selection coordinates are PDF points: small box `(132,140)-(420,163)` on pages 1 and the last page; large box `(126,110)-(485,600)` on page 12 or 36. Requests used synthetic Alice and Bob identities. All retained final picks returned HTTP 200 with `via: synctex` and no refusal reason.

The macOS arm64 environment used Python 3.14.7, TeX Live 2026/pdfTeX 1.40.29, latexmk 4.88, latexdiff 1.4.0, Poppler 26.10.0 and Git 2.55.0. It had no bwrap. Its actual comparison worker finished with the existing `tool_unavailable` refusal after preparing snapshots; this is not a successful execution timing.

The Linux x86_64 environment used Python 3.10.12, TeX Live 2022/pdfTeX 1.40.22, latexmk 4.76, latexdiff 1.3.1a, Poppler 22.02.0, Git 2.34.1 and bwrap 0.6.1. The eligibility probe saw 64 CPUs, one-minute load 5.73 and approximately 186 GiB available memory. The supervised main run lasted 31.90 seconds, completed normally and observed load below 7.01. This was shared physical hardware, so process isolation does not make the timing a dedicated-host benchmark.

## Measured costs

These are individual bounded samples, not percentiles. CPU is the whole batch's self plus reaped-child `getrusage` delta. It does not attribute concurrent requests or reliably account for every sandbox descendant. Starts count actual Popen launches; peak counts observed active direct leaders, not all descendants. Output is combined returned stdout/stderr, collected through profiling actual return values without replacing tools or caches.

| Existing operation | Wall seconds | CPU seconds | Starts / peak leaders | Combined process output bytes |
| --- | ---: | ---: | ---: | ---: |
| macOS, 24-page warm small pick | 0.195 | 0.183 | 16 / 1 | 5,297 |
| macOS, 72-page warm small pick | 0.284 | 0.279 | 16 / 1 | 5,297 |
| macOS, 72-page large pick | 0.566 | 0.555 | 31 / 1 | 13,759 |
| Linux, 24-page warm small pick | 0.113 | 0.116 | 16 / 1 | 4,577 |
| Linux, 72-page warm small pick | 0.287 | 0.288 | 16 / 1 | 4,577 |
| Linux, 72-page large pick | 0.545 | 0.549 | 31 / 1 | 12,127 |
| Linux, four overlapping 72-page picks, one principal | 0.306 | 1.107 | 64 / 4 | 18,308 |
| Linux, 72-page cold comparison status | 0.0145 | 0.0152 | 4 / 1 | 17,799 |
| Linux, 72-page warm comparison status | 0.0105 | 0.0112 | 3 / 1 | 189 |
| Linux, 72-page genuine cached POST | 0.0115 | 0.0123 | 3 / 1 | 189 |
| Linux, 24-page comparison, including a join and running status read | 0.563 | 0.104 | 32 / 2 | 209,267 |
| Linux, 72-page comparison, including a join and running status read | 0.842 | 0.190 | 63 / 2 | 538,096 |
| Linux, two distinct document range jobs, one principal | 0.849 | 0.243 | 82 / 2 | 728,915 |

The largest retained Linux source-selection child output was 2,192 bytes; a large pick's JSON body was 8,584 bytes. The initial 72-page comparison's largest single child output was 173,827 bytes. These sizes do not establish safe caps for other corpora.

Three sequential small picks completed successfully in 0.453 seconds on the 24-page macOS corpus and 0.840 seconds on the 72-page corpus. Paired and four-way overlapping requests from one identity succeeded on both hosts; different identities also succeeded. The first and last page picks both ran actual lookup work. A per-principal allowance of one with immediate refusal would change these successful overlapping cases.

Profiling-disabled warm picks retained launch auditing and completed in 0.151/0.278 seconds on macOS and 0.110/0.268 seconds on Linux for the 24/72-page corpora. Profiling and synthetic-output preservation add overhead, and uncontrolled host variation remains. The measurements must not be treated as production latency guarantees.

## Execution, joins and occupied capacity

Single-commit comparisons and two-commit ranges genuinely produced 24/72-page PDFs. `pdfinfo` verified page counts and `pdftotext` verified the old and new generated revision-number tokens, including the changed `119` token. Six intended PDFs were independently checked; ready metadata was never fabricated. The main execution samples' same-key POST joins returned HTTP 202 `running`, and status reads returned HTTP 200 `running`, with the original job identifier.

A focused follow-up started two distinct range jobs under one principal in one assembly serving both documents. While both workers remained active:

| Request | Existing result |
| --- | --- |
| Same-key comparison POST | 202 `running`, original job identifier |
| Other-key cached comparison POST | 200 `ready` |
| Other-key cached comparison status | 200 `ready` |
| Distinct uncached comparison request | 409 `busy` |
| Same-principal source selection | 200, `via: synctex` |

Both range jobs completed `ready`. The combined batch lasted 0.917 seconds, used 0.596 recorded CPU seconds, launched 112 children and returned 769,685 process-output bytes. Four concurrent lookup requests plus two existing execution workers reached six direct child leaders. Thus a cached/joined request consumes lookup work, while the existing execution-slot refusal applies only to a new miss. A blanket per-principal execution gate placed before lookup would regress this observed behavior.

## Transport evidence and next decision

The preserved primary TCP probe records **140 idle connections and 140 active unauthenticated request threads**, with listen backlog 128 and handler inactivity timeout 30 seconds. Backlog is not an active-connection bound. This demonstrates thread allocation before authentication; it did not deliberately exhaust the machine or measure an overload threshold. Feature execution quotas cannot prevent this allocation because no feature request has reached authentication or dispatch yet.

Deferring new paper execution caps while addressing this independently observed connection-allocation risk is justified. Viable next choices are:

1. Review transport admission separately: define how accepted connections are bounded before a handler thread starts, how completed/incomplete requests release capacity, and how keep-alive and event traffic remain usable. Measure legitimate connection occupancy and review refusal/framing behavior before selecting a count or absolute deadline. The draft's 64/10/30 values are not approved or supported by this evidence.
2. Retain existing paper execution/process bounds while collecting a broader synthetic corpus: substantially larger trees, asset-heavy documents, broad and pin-scoped diffs, macro fallback and slower hardware. The current sparse text changes do not represent all paper workloads, and the samples do not justify the draft's proposed execution numbers.
3. If later evidence supports workload admission, review lookup and execution separately. Reauthorize every request; preserve authorized cache reads and same-job joins at occupied execution capacity; coordinate distinct misses atomically with existing global/document/cache locks. Any new refusal status, timeout, output budget or principal fairness rule requires concrete design approval and contract review first.

## Reproduction, checks and limitations

Raw generated corpus, scripts, command/output records, HTTP replies, provenance, hashes and supervision logs are preserved outside the repository under `$HOME/Library/Logs/limn-workload-completion-20261009/`. Relevant files are `research-preflight.md`, `measure.py`, `supervise.py`, `probe_capacity.py`, `validate_linux.py`, `macos-final/`, `linux-final/`, `linux-overlap/`, `linux-validation.json`, `evidence-integrity.json`, `linux-cleanup.json` and the copied `prior-connection-probe.log`. The original connection log remains in the preceding security-worker evidence directory. The audit does not require publishing raw machine paths or synthetic manuscript text.

Replay from the pinned source, with the evidence scripts in a local directory and an installed supported TeX/Poppler toolchain:

```sh
git archive 45bf1a7d3343f4ec179a3b35e253cc232d709485 src/limn | tar -x -C "$SCRATCH/source"
python3 "$EVIDENCE/supervise.py" "$SCRATCH/run.log" python3 "$EVIDENCE/measure.py" --repo "$SCRATCH/source" --output "$SCRATCH/sample" --compare
python3 "$EVIDENCE/supervise.py" "$SCRATCH/overlap.log" python3 "$EVIDENCE/probe_capacity.py" "$EVIDENCE/measure.py" "$SCRATCH/source" "$SCRATCH/sample"
```

The last command expects the genuine cache entries created by the preceding Linux run. Run the eligibility check and create the empty scratch/source directory first; omit `--compare` on macOS. CPU/output numbers belong to the first command's instrumented samples, not to an uninstrumented production instance.

Two harness attempts were retained and excluded: rendering only selected page images caused middle/last-page requests to be refused by the production page-count parser, and a follow-up using relative configuration paths failed its synthetic pick assertion. Both were corrected in the harness, with fresh successful observations. No existing-contract defect was reproduced. The Linux supervisor reported no surviving observed groups, SHA-256 verified 1,077 copied files, and cleanup confirmed the isolated scratch directory was removed with no remaining scratch processes.

This documentation-only audit changes no current Handbook responsibility. Its review checks are `git diff --check` and the existing naming/privacy guard. Numerical policy adoption, production telemetry, OS-exhaustion testing, UX/UI behavior, private manuscripts and deployment capacity remain outside this evidence.
