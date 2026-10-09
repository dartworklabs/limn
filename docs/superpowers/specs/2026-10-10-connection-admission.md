# Optional connection admission

Status: the owner approved the exact written V2 design and its implementation on 2026-10-10. Implementation is pending. This document records that approval; it does not claim implementation, activation, or passing CI.

Approval: [issue #222 owner approval record](https://github.com/dartworklabs/limn/issues/222#issuecomment-6085831493). The approved written candidate is [V2 owner review](https://github.com/dartworklabs/limn/issues/222#issuecomment-6077481343), bound to SHA-256 `6ef1913b6fd40626e47a61fe6bbfb8a1376921aa79923bb5f5c1585776e5e53d`. The owner answered `승인` after being asked to approve implementation of that design. The earlier bounded research used an explicitly scoped disposable spike. Formal Superpowers brainstorming was unavailable at that time; this record does not claim that its formal chain previously ran. The actual brainstorming and writing-plans instructions are now available and were read for this handoff. The unchanged approved scope proceeds through a written implementation plan and the delegated execution selected by AGENTS.md, without another approval or execution-method selection.

## Purpose and scope

Provide an optional operator-selected bound on admitted live TCP connections independently for each listener. A cap can limit admitted sockets and request workers; it cannot establish a safe machine budget, user fairness, a request rate, or a complete denial-of-service defense. Connections can exist before identity, and a proxy connection can carry requests for different users.

The CLI is `limn serve --max-connections N`. Omission preserves existing unbounded admission and existing thread-start/failure behavior. A supplied value must be a positive integer. Zero, negative, missing-value, and malformed values fail startup before listening. There is no numeric production default and no production activation in this change.

Runtime dependencies remain `dependencies = []`; supported Python remains `>=3.10`. Preserve default loopback binding and all existing identity, Host/Origin, authorization, body, response, timeout, and pin-storage contracts. Code, comments, docstrings, CLI help, and logs use English; Handbook prose uses Korean; README and skill documentation stay paired in English and Korean when changed. Public artifacts contain no personal paths, real email addresses, or machine host names.

## Admission and ownership

The `web/` HTTP transport boundary owns this mechanism. Runtime owns parsed startup configuration; `server.py` wires the chosen listener. Pure admission/lifecycle decisions contain no socket, thread, clock, filesystem, or feature imports. Effects remain in the transport adapter. No global mutable admission state exists.

1. After accepting a socket, atomically reserve its lease before constructing or starting a request worker.
2. Count pending starts, active request handlers, and idle HTTP/1.1 keep-alive connections. A completed response does not release a lease.
3. At capacity, promptly close the new socket without waiting for a lease or creating its request worker. No HTTP parsing precedes refusal.
4. Release an owned lease exactly once after physical socket cleanup completes and is attested. A closed socket and lease ownership are separate facts.
5. Bind cleanup to an opaque listener identity and a never-reused generation identity. FD integers are not ownership identities. Duplicate or stale cleanup cannot release a newer or foreign lease.

The admitted count satisfies `0 <= admitted <= N`. The kernel backlog and accepted sockets being immediately refused are outside that count. This is not a total FD bound. Retired lease identities must not create an ever-growing tombstone collection.

## Refusal and HTTP compatibility

Saturation produces a transport close before HTTP parsing. A direct client may observe EOF or reset. No HTTP `503` or `429`, JSON error/reason, UI message, or translation is added. A proxy may synthesize its own error or retry; its mapping has not been measured and is not part of Limn's HTTP contract.

Admitted requests keep the existing body/framing checks and authorization on every request. Idle keep-alive and incomplete-body sockets retain the existing 30-second timeout. Long request execution is not an idle socket deadline. There is no absolute header deadline. Existing error responses still close their connection; successful keep-alive requests remain reusable and may change identities between requests.

## Worker start failure

Only an owned failure proved to precede invocation of `Thread.start()` may recover: physically clean up its socket, attest cleanup, return its lease exactly once, then continue admission. Construction is one such pre-call boundary. If that cleanup cannot complete or be attested, terminate rather than reclaim uncertain ownership.

Once the actual `Thread.start()` call is invoked, any exception from that call is fatal in enabled mode. This includes ordinary exceptions, `KeyboardInterrupt`, and `SystemExit(0)`. Exception type, message, thread identifier, or an unset startup event proves neither successful nor absent native launch. Captured CPython 3.10–3.14 implementations launch native execution before their later bootstrap acknowledgement; the public call's failure is therefore insufficient proof of no worker.

Atomically stop admission and fence pending worker entry before it constructs a handler. Already-claimed work keeps ownership through its cleanup/finally. Close the listener and escape the accepting loop with a nonzero process result after existing runtime cleanup. Standard `socketserver` catches ordinary `Exception` from dispatch and continues, so returning or throwing an ordinary exception is insufficient. The transport must make the fatal escape explicit.

The parent never returns an uncertain lease, redispatches the socket, or resumes admission. Standard-library dispatch may physically close the accepted socket while propagating a fatal error; this must not return the worker's lease. A possible worker owns that lease until its own cleanup/finally or process exit. An ambiguous no-worker outcome deliberately retains the lease until exit.

Fatal close, fallback-close, cleanup, logging, and coordination errors preserve the original start failure as the cause. They cannot allow continued acceptance or turn failure into a successful exit. Repeated close/stop and partial startup remain safe. No generic recovery based on catching `Exception`, no exception-message matching, and no inference from `_started` is permitted.

## Shutdown costs and limits

Use existing runtime cleanup: listener closure followed by `RuntimeResources.stop()`, which sets its stop event and joins each registered watcher once, for five seconds each. The existing page-render `ThreadPoolExecutor` may wait for executor threads during interpreter exit, beyond those watcher joins. This is not a new total shutdown SLA. No self-restart, graceful drain, new child-process policy, process manager rollout, or installation change is included.

Existing HTTP, asynchronous rebuild, and comparison workers are daemon work and may be interrupted by process exit. Other in-flight requests and jobs in the same instance may therefore be cut short after an uncertain start. This availability cost is deliberate. It does not add transaction rollback or promise that an interrupted build completes, every subprocess descendant is reaped, or all derived files are mutually consistent at every process-exit point. An external service manager may apply its existing restart policy; direct CLI execution remains failed.

## Exclusions and activation

No per-principal/IP quota, fairness, request/work-cost limit, shared state, persistent counter, access-statistics endpoint, new auth behavior, manager configuration key, service template change, deployment, production cap selection, UI/CSS/JS/translation change, or dependency is authorized by this scope. Existing work-cost gaps remain separately documented.

Activation is a later operator decision using that host's actual FD/thread limits, memory and other-process reserve, legitimate concurrent demand, proxy behavior, and rollback budget. Current samples and RAM totals cannot select N. Removing the option restores existing unbounded behavior; this is a configuration rollback, not an activation performed here.

## Acceptance evidence

Gate the following with colocated production tests collected by the existing CI Python jobs, and retain every existing CI gate:

| Requirement | Observable evidence |
| --- | --- |
| Default off and startup | Omitted option has existing admission/start behavior; positive N reaches chosen listener; invalid input exits before listening |
| Bound and recovery | Real IPv4/IPv6 TCP: partial-header, active, and idle keep-alive holders saturate N; extra sockets close without HTTP bytes; after real cleanup a legitimate request succeeds |
| Isolation and reuse | Two listeners have independent slots; successive requests on one connection retain one slot and recheck identity/role |
| Normal and fault cleanup | EOF, timeout, setup/handle/finish faults and cleanup faults obey physical-cleanup and exactly-once ownership rules |
| Start uncertainty | Owned pre-call construction failure recovers only after cleanup; post-call ordinary/interruption/zero-exit failures stop admission and produce nonzero child-process exit |
| Entry races | Deterministic pending and claimed worker barriers; pending never creates a handler after stop; claimed worker retains lease while cleanup is withheld; ambiguous no-worker lease survives until exit |
| Fatal secondary faults | Close before/after physical cleanup, fallback close, logging and coordination failures cannot replace the original cause with successful exit or ordinary recovery |
| Pure invariants | Hypothesis-generated lifecycle sequences preserve capacity, exactly-once release, stale/foreign generation rejection, and irreversible stop |
| Actual oracle failure | Record assertion-bearing red runs or plausible production mutations, including explicit failure if a mutant survives |
| Active work | Real pin files remain complete old/new JSONL under interrupted atomic replacement; stale derived pins.md is allowed between replacements. A build paused before publication leaves old published pages; no terminal completion or general child-reaping claim |

Use real sockets, files, owned process boundaries, bounded deadlines, and deterministic barriers. Do not patch `threading`, `socket`, `time`, or `os` globals in callers, or assert private call ordering. Shortened timeout subclasses are test observations, not changed production policy. Fault seams are narrow owned lifecycle overrides that invoke real startup/close where the scenario requires it; they do not prove actual native resource exhaustion or arbitrary asynchronous signals.

The bounded spikes inform the design but are not production tests, benchmarks, production budget evidence, or proof of CI completion. The implementation plan owns the concrete task/test mapping and Handbook synchronization. [ADR-0016](../../adr/0016-optional-connection-admission.md) records the approved choice and its availability trade-off. The four-part [Handbook-read context](../plans/2026-10-10-connection-admission.md#handbook-read-결과) records current authority, current invariants, reasons/constraints, and unresolved limits supplied to this spec and writing-plans.
