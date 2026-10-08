# Backend workload limits

Status: **PROPOSED — owner approval pending.** Tracking: issue #222.

This is a reviewable recommendation, not an adopted contract or an implementation plan. No workload policy in this document is implemented. The formal brainstorming/approved-plan workflow remains pending; the available `arch-design` skill references `superpowers:brainstorming`, which is absent from this session's skill catalog. The owner must approve the limits and changed refusal behavior before production code or canonical Handbook changes adopt them.

## Current authority and constraints

| Role | Path | Current authority |
| --- | --- | --- |
| Purpose | `docs/handbook/purpose.md` | Private authenticated review service; no public deployment or runtime package dependencies |
| Architecture | `docs/handbook/architecture.md` | Complete mediation, default denial, request-bound authority; new asynchronous flows/permissions/API contracts require design approval |
| API | `docs/handbook/api.md` §인증, §요청 형식과 경계, §엔드포인트, §비교 PDF 실행과 캐시 | Viewer can pick and request comparisons; editor/agent/owner can rebuild; roles and successful response meanings remain unchanged |
| Verification | `docs/handbook/verification.md` | HTTP boundary tests, real managed files/processes, TeX-required CI, failure evidence |
| Security coverage | `docs/handbook/code-style-roadmap.md` §경계 집행과 검증의 한계 | Principal limits are absent; comparisons share process slots; HTTP connections have no active limit |

Resources remain owned by the server run and wired at `server.py`; decision code remains free of I/O. No new runtime dependency, persistent state file, role, public endpoint, job queue, deployment change or viewer/UX change is proposed. Independent server processes remain independent admission domains; the existing per-document filesystem lock protects a comparison cache shared across processes.

## Observed safeguards and concrete risks

| Work | Existing safeguards | Remaining risk |
| --- | --- | --- |
| HTTP transport | Listen backlog 128; socket inactivity timeout 30 seconds; 1 MiB body limit; invalid framing/auth failures close the connection | Backlog limits pending accepts, not accepted connections. A diagnostic using the real server opened 140 idle unauthenticated sockets and observed 140 handler threads. Drip-fed input can reset the inactivity timeout; each connection allocates a thread before authentication. |
| Manuscript pick | Page-valid finite/clamped coordinates; 2–5 by 2–6 sample grid; each SyncTeX subprocess times out after 10 seconds; one `pdftotext` step after 15 seconds | Up to 30 sequential SyncTeX subprocesses plus text extraction: 315 seconds of subprocess timeout allowances per request, excluding file/token scanning. Neither principal nor global admission bounds are present. `capture_output` buffers output without a byte limit. Source/token work also lacks an end-to-end deadline. |
| Comparison | Two process-wide build slots; a nonblocking per-document filesystem lock; same-key running-job deduplication; cache retention 6 whole/6 scoped/4 ranged entries per document, TTL 24 hours; snapshot limits 4,000 files, 256 MiB per tree and 64 MiB per file; PDF 32 MiB; bounded stdout/stderr runner, default 8 MiB; isolated filesystem/network and process-group cleanup | One principal can occupy both slots across documents. Admission currently follows history/spec/scoping computation. Snapshot listing permits 30 seconds then each side's blob copy permits 60 seconds; latexdiff permits 60 seconds and latexmk up to 180 seconds per attempt. A text-command fallback can repeat those last steps. This is not one total deadline, and scoped reads may add more time. Failed whole comparisons can be retried immediately. |
| Rebuild | Nonblocking document lock; configured compiler timeout; cleanup on failures | Existing rebuild rules stay unchanged in this proposal; HTTP transport admission also bounds its connection usage. |

The timing figures describe code-level allowances, not a measured worst-case performance guarantee. The connection reproduction and collected source excerpts live outside the product repository under the security worker's runtime evidence directory. No production service was exercised.

## Proposed policy to approve

| Resource | Proposed default | Rationale and cost |
| --- | --- | --- |
| Pick concurrency | **1 active pick per principal, 2 globally per server run**; no waiting queue | One interactive selection per person is normal; two principals can compute concurrently. Overlapping agent calls and rapid repeated selections can now receive a refusal. |
| Pick total execution | **30 seconds** from admission to result; **1 MiB combined stdout/stderr per subprocess**, retain existing shorter 10/15-second step limits | Replace the accumulated 315-second allowance with a single budget. A large selection that cannot finish within the budget receives a named refusal instead of holding a worker indefinitely. |
| Comparison concurrency | **1 newly initiated active comparison per principal** while retaining the existing **2 global slots** and per-document lock; no waiting queue | A principal cannot fill both execution slots. This provides isolation against one principal, not strict FIFO fairness or protection against many separately authenticated principals. |
| Comparison total execution | **180 seconds** from a claimed admission slot through validation/history/scoping/snapshots/latexdiff/latexmk/fallback/publication | Every step gets the smaller of its existing limit and the remaining monotonic budget. `--build-timeout` continues to constrain latexmk within that budget; it cannot extend the overall comparison deadline. Large/slow jobs that formerly succeeded after several minutes may now time out. |
| HTTP active connections | **64 per server run**, including idle keep-alive, in-flight requests and event streams; preserve backlog 128 | Bound unauthenticated threads before spawning. Long-lived event streams consume capacity; 64 is intended for small private collaboration, not hundreds of simultaneous tabs. Raising it later requires a reviewed configuration design. |
| HTTP time | Retain **30-second keep-alive/socket inactivity**; add **10-second absolute header deadline** and **30-second absolute body-read deadline**, reset only for a new request | Slow progress no longer extends incomplete request parsing indefinitely. These are input deadlines, not a 30-second deadline for already admitted builds or event streams. |

These defaults are fixed proposed policy values, not new configuration flags. They should be documented together with their reason if approved. Tuning/CLI/environment keys require a separate explicit configuration design.

## Identity, admission and cleanup invariants

1. A principal key comes only from the verified `Principal.actor.login`, scoped to the current server run; display names, roles, unverified headers, request fields and caller-supplied IDs never choose a budget. A person's role change does not create a fresh budget. Tokens with the same verified agent login share a budget conservatively; the headerless loopback agent has one shared budget. The limit is per existing verified identity, not per real human across different identities.
2. Preserve Host/Origin, authentication, membership, role, input parsing and object-bound authority checks. Claim pick slots only after that boundary passes and before subprocesses or source reads. Comparisons require their existing `PostAuthority`; claim principal/global admission before expensive history/spec/scoping. HTTP capacity is a transport-level limit before identity exists and returns only a fixed non-sensitive overload response.
3. A bounded registry stores only active principal leases and removes empty entries when the last lease exits; arbitrarily many attempted logins cannot create an unbounded historical map. Atomic nonblocking claims cannot exceed either bound. No handler waits holding one lease for another resource.
4. Deduplicated joins and cached comparison hits do not create a new execution lease or transfer job ownership. They still pass authentication and authorization. Read/cache/spec work preceding discovery of a hit uses a short-lived principal admission lease so bypassing the build gate cannot create unbounded expensive lookups. Release a temporary lease before returning a hit or join; reject a distinct miss from an already occupied principal. Implementation planning must preserve same-key join behavior even at capacity.
5. Every acquired lease and HTTP connection slot releases exactly once on all success, refusal, disconnect, timeout, thread-start failure, worker crash and shutdown paths. A comparison worker retains its lease after the requesting socket closes and releases it when actual work ends. Releasing capacity must not leave children still consuming resources.
6. All executable work runs without a shell, with bounded pipe reads and a monotonic remaining budget. On timeout, output overflow, disconnect cancellation where supported, or shutdown, terminate/reap the complete owned process group before releasing execution capacity. Source scanning is incrementally deadline checked; a blocking operation is bounded by its remaining deadline. A single final check after work is insufficient.
7. HTTP capacity is claimed before `ThreadingHTTPServer` spawns a thread. On saturation, send a fixed response of at most 1 KiB from the accept path with a write timeout of at most 250 ms, then close; do not spawn an overload-response thread or let slow readers block acceptance indefinitely. Connection cleanup releases the slot in `finally`; server close/startup failure is idempotent. Header/body deadlines do not kill valid streaming responses.

## Proposed refusals and compatibility

| Condition | Proposed response | Compatibility impact |
| --- | --- | --- |
| Principal pick/comparison concurrency exhausted | `429`, `{"error":"이 계정에서 계산을 실행 중입니다. 잠시 뒤 다시 시도하세요.","reason":"work_limit"}`, `Retry-After: 1`, connection closes | New status/reason for existing endpoints. Retrying is safe only when the client explicitly chooses; one second is advisory, not a reserved slot. |
| Global pick slots exhausted | `503`, `{"error":"다른 계산을 실행 중입니다. 잠시 뒤 다시 시도하세요.","reason":"busy"}`, `Retry-After: 1`, connection closes | New pick refusal; no partial source result or new persistent state. |
| Comparison global slots/document lock exhausted | Existing `409 busy` response | Preserve existing comparison refusal contract and running/cached deduplication. |
| Pick deadline/output cap | `503`, fixed error with existing `timeout`/`size_limit` reason | New non-200 pick failure modes; keep existing ordinary `200 {error,reason}` location refusals intact. No partial result is returned. |
| Comparison deadline/output cap | Existing asynchronous `state:"error"`, `reason:"timeout"`/`"size_limit"`; no partial PDF publication | Preserve asynchronous status structure; a previously longer successful build may now fail sooner. |
| HTTP active cap exhausted | Fixed `503`, `reason:"busy"`, `Retry-After: 1`, connection closes | Transport overload can precede Host/auth checks and any method; it exposes no resource, identity or exception details. |
| Incomplete headers/body exceed absolute deadline | Close incomplete headers without dispatch; body timeout follows existing framing/error-and-close convention | Prevent partial content from becoming a subsequent request. No feature effects or people-record writes occur. |

Existing successful bodies, request fields, role grants, cached PDFs, pin contracts and viewer rules stay unchanged. Known consumers include external agents documented in `skill/SKILL.md`/`SKILL.ko.md`, HTTP contract snapshots and the shipped request-handling code. New 429/503 and reason values are an API contract change requiring owner approval and then canonical API documentation, consumer compatibility checks and generated API declarations where applicable. The implementation scope remains backend; discovering a required viewer behavior change must return for separate scope approval because UX/UI work is stopped.

## Acceptance tests after approval

- All existing HTTP role cells still pass: viewer can pick/start comparisons, owner/editor/agent can rebuild; denied identity/membership/roles leave source, state files and build publication unchanged.
- Real simultaneous picks prove principal max 1/global max 2, two distinct identities can progress, forged login/body keys cannot obtain capacity, and overload starts no subprocess/file scan. Generated operation sequences against the pure lease decision prove counts never exceed bounds and inactive principal entries are removed.
- Real comparisons across documents show one identity cannot occupy both global slots, two identities each obtain one slot, same-key joins/cached responses remain possible at capacity, distinct jobs from a saturated principal are refused, and revoked tokens cannot join/status-read.
- Real delayed/verbose child processes show pick combined deadline, output cap, comparison deadline spanning snapshots and fallback, descendant termination/reaping, bounded captured memory, and no publication of partial artifacts. TeX-required CI proves successful real sandbox/rebuild PDFs within the new budgets.
- Every lease release path is observed by a subsequent request acquiring freed capacity: parse/spec refusal, thread creation failure, compile failure, output overflow, deadline, disconnect, worker crash and shutdown. No fake managed file/database/compiler dependency replaces the effect being tested.
- A real HTTP server with 64 accepted sockets refuses the 65th without spawning another handler; freeing one permits a new connection. Incomplete headers/body with periodic progress hit absolute deadlines; ordinary keep-alive and event streams obey their separate lifecycles. Saturated sockets cannot leak identifying response fields or block accept cleanup.
- Contract checks compare old successful responses and new refusal fixtures; documented retry behavior is exercised without automatic retry loops. Boundary/type/lint checks enforce ownership, authority issuance and standard-library runtime dependencies.

## Approval and follow-through

Approve or revise the numeric limits, principal grouping, end-to-end deadlines, pre-authentication transport refusal and 429/503 compatibility together. After approval: formalize the design/implementation plan; determine whether the changed API/async admission trade-offs warrant an ADR; update `api.md`, `build-sync.md`, `architecture.md`, `code-style-roadmap.md` and `verification.md` alongside the actual implementation; implement and run the acceptance gates. Until then, canonical Handbook descriptions must continue to report existing safeguards and gaps.

## Bounded fixture evidence and proposal clarification

**Unapproved diagnostic evidence; no policy adopted.** The numerical defaults above remain hypotheses. The owner asking why limits are needed does not approve them. The original single temporary/execution-lease description in invariant 4 is incomplete; the separate lookup/execution model below is a proposal to resolve that conflict before approval.

The sample used the existing production handler and application assembly through real socketpairs, existing synthetic Alice/Bob identity fixtures, real subprocesses and a freshly compiled copy of `tests/support/helpers.py`'s `TEX`. The corpus is one 20-line, 384-byte article with one tiny table and two synthetic Git revisions. At most two requests ran concurrently; no real manuscript, production service, browser or UI validation was used. Raw measurements, request results, command audit entries, generated artifacts, source evidence and configuration provenance are outside the repository under `$HOME/Library/Logs/limn-non-ui-workload-evidence/sample-20261008T211334/`; the replay script is in its parent directory. The repository HEAD was `b1487ecd` with ongoing non-UI changes, Python 3.14.7 on macOS arm64, actual TeX/Poppler tools available, and no `bwrap`.

| Observed sample | Elapsed time | CPU, process starts and response size |
| --- | --- | --- |
| Small pick, first/warm sample | 0.059 / 0.069 seconds | 0.056 / 0.065 CPU seconds across handler process and reaped children; 16 child starts each; 1,846-byte successful JSON |
| Larger pick, maximum SyncTeX grid | 0.099 seconds | 0.094 CPU seconds; 31 child starts; 2,316-byte successful JSON |
| Two small picks, same identity | 0.059 seconds for the batch | 0.106 CPU seconds; 32 starts; both HTTP 200 |
| Two small picks, different identities | 0.057 seconds for the batch | 0.103 CPU seconds; 32 starts; both HTTP 200 |
| Comparison status, cold/warm | 0.059 / 0.052 seconds | 4 / 3 Git starts; 268-byte `idle` JSON |
| Comparison status after attempted build; concurrent pair | 0.064 / 0.065 seconds for the batch | 3 / 6 Git starts; 343-byte `error` JSON per request |
| Comparison cached POST / cached status | 0.050 / 0.050 seconds | 3 Git starts each; 269-byte `ready` JSON |

The cached-read samples used a genuinely compiled fixture PDF plus explicitly synthetic `ready` metadata to exercise cache lookup only. They do **not** demonstrate a successful comparison compiler or valid comparison content. Actual comparison initiation returned HTTP 202 `running`, then the genuine worker reported `tool_unavailable` because this host cannot run the required sandbox. Its request elapsed time is not a job execution measurement. Running-job joins, saturated execution capacity, pin-scoped/ranged history, successful sandbox builds and their timing remain unmeasured.

Process starts were observed by Python audit events without replacing the compiler, files, subprocess library or handler. They count launches during each request batch, not peak resident child processes. CPU is a whole-batch `getrusage` delta, not attribution to an individual concurrent request. A separate replay of the larger pick's 31 real commands observed 10,322 combined stdout/stderr bytes in total and at most 337 bytes from one child, all exits successful. That replay informs ordinary fixture output size only. The 1 MiB proposal does not follow from it. These tiny samples cannot justify timeouts, hard defaults, percentiles, hardware capacity or timings across papers.

### Selection ownership risk, from source inspection only

`viewer/js/composer.js:pick()` increments `PICKSEQ`, starts `/api/pick` and discards a stale reply. `cancelSelection()` and `viewer/js/repick.js:cancelRepick()` increment the sequence again. `viewer/js/api.js:api()` calls `fetch()` without an abort signal. `pins/location/resolve.py:pick()` and `pins/location/source.py` synchronously run the text and SyncTeX work, with no request-cancellation value reaching that work; the common handler catches disconnects at the HTTP boundary. Thus replacing or cancelling a visible selection does not establish that the old computation ended.

Consequently, a new per-principal execution limit of one with immediate refusal can reject a normal rapid reselection while the old response would simply have been ignored. The small paired sample confirms overlap is currently accepted, not that every real selection has the same latency. Multiple tools using one verified agent login, or headerless loopback tools sharing `local`, would also share that limit. Backend-only implementation must not silently assume clients serialize, cancel or automatically retry; any change to those client behaviors needs separate scope approval while UX/UI work is stopped.

### Separate lookup and execution admission, for review

1. Define two independently bounded lanes: lookup leases with per-principal/global counts and an absolute lookup deadline, and execution leases with per-principal/global counts and an execution deadline. Their numerical capacities/deadlines are **unresolved**. A running execution must not consume that principal's lookup allowance. A transport connection bound covers both lanes but does not replace either.
2. After existing identity, membership, role, body/query and object-scope checks, nonblockingly claim lookup capacity **before** Git/history/spec/scoping/cache reads. Status polling and cached POST requests use this lane too: a warm fixture still spawned three Git commands. Lookup authorization is rechecked every request; do not shortcut it using an untrusted caller-supplied job key. Bound expensive pin/history work within that deadline as well.
3. Discover an authorized ready cache entry or same-key active job, return its existing response and release the lookup lease. Do not claim or transfer an execution lease, alter job ownership, or restart its clock. This remains possible while execution counts are full, provided lookup capacity is available; it is not an unlimited bypass. Exact refusal behavior when the lookup lane is full remains an API decision requiring approval.
4. On a miss, atomically recheck the active/cache entry and nonblockingly claim per-principal/global execution capacity under the admission/jobs coordination lock. A racing same-key job becomes a join; a distinct miss with no execution capacity is refused and releases lookup capacity. Release the lookup lease immediately after successful promotion, without waiting while holding either lease for another resource. Acquire the document lock nonblockingly, preserve the cross-process cache lock, and unwind all acquired capacity if preparation or thread start fails.
5. The worker owns execution capacity until actual work and child cleanup end. Its execution clock starts at the successful execution claim and covers snapshots, diff, compilation, fallback and publication; the lookup clock starts at the lookup claim and never resets while resolving a miss. The resulting total bound is lookup plus execution, so the original wording that starts the proposed 180-second budget before history must be revised or explicitly retained as an additional total deadline before adoption. Joins, fallback and cache rechecks do not restart a worker's execution clock. Comparisons started by another process remain subject to the existing document/cache locking semantics.

The safest immediate backend step is evidence and a separately reviewed telemetry design that records operation kind, elapsed time, child/output counts, result class and active counts without manuscript text, source paths, tokens or identity payloads. No telemetry implementation is authorized by this diagnostic. A conservative HTTP connection cap can address the independently demonstrated thread exhaustion without selecting paper execution budgets, but its count, event-stream/keep-alive capacity, accept-path refusal and compatibility still need their own review and explicit approval. This fixture establishes neither 64 connections nor the proposed 10/30-second transport deadlines.
