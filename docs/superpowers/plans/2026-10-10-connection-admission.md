# Optional Connection Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. AGENTS.md already selects delegated execution; the root orchestrator dispatches implementation and independent review. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional per-listener cap on admitted TCP connections with exactly-once socket ownership and fatal handling of uncertain request-worker startup.

**Architecture:** Keep existing `Server`/`Server6` untouched for omitted-option behavior. Add pure lease transitions and bounded transport subclasses inside `web/`; parse the option in `runtime/` and select the listener in `server.listen()`. The cap owns neither authentication nor business work quotas, and post-start uncertainty stops admission and exits nonzero after existing cleanup.

**Tech Stack:** Python >=3.10, standard-library runtime only, pytest, Hypothesis, existing uv/Ruff/mypy/ShellCheck/node/Playwright/TeX CI.

**Spec:** [approved spec](../specs/2026-10-10-connection-admission.md); [ADR-0016](../../adr/0016-optional-connection-admission.md) D1–D5. The [owner approval record](https://github.com/dartworklabs/limn/issues/222#issuecomment-6085831493) approves the exact V2 design and implementation. No same-scope reapproval or method choice is pending. This plan does not claim that formal brainstorming ran during the earlier scoped research.

## Global Constraints

- Omission preserves existing unbounded admission and existing thread-start/failure behavior.
- A supplied value must be a positive integer.
- Runtime dependencies remain `dependencies = []`; supported Python remains `>=3.10`.
- Code, comments, docstrings, CLI help, and logs use English; Handbook prose uses Korean; README and skill documentation stay paired in English and Korean when changed.
- Public artifacts contain no personal paths, real email addresses, or machine host names.
- No HTTP `503` or `429`, JSON error/reason, UI message, or translation is added.
- No numeric production default and no production activation in this change.
- No generic constructor parameters or interfaces solely to permit test substitution. Faults use concrete owned lifecycle adapter overrides; managed sockets, files and native thread launches remain real.
- Keep `Server.request_queue_size = 128`, daemon request workers, the production handler timeout of 30 seconds, and runtime joins of five seconds each. None is a total process-exit SLA.
- No global counter, persistent state, per-user/IP quota, auth change, service/manager rollout, child-process policy, graceful drain, or self-restart.
- Do not edit historical numbered ADRs. New ADR-0016 remains `제안` during review; promote its status only at merge.

## Review Focus

The following five conditions were easy to miss in a basic saturation test; each is mapped to a task below.

1. A zero-exit interruption after actual `Thread.start()` must still stop admission and exit nonzero, including secondary logging/close failures (Task 2).
2. Parent socket closure must not release a possible worker's lease while a claimed worker waits behind a cleanup barrier; a pending worker must not instantiate a handler after stop (Task 2).
3. Reused socket FD integers and foreign listener tokens cannot release a new connection's lease; lifetime memory must not grow with completed connections (Task 1).
4. One HTTP connection carrying changed identities must keep one transport lease while the second request's authority is checked again (Task 3).
5. Fatal exit during real pin/build work preserves only existing atomic-write/publication guarantees; executor interpreter joins can exceed watcher join times (Task 3).

## Current source map and ownership

Base inspected: `5abde98648ebd524c05959f8dae95916a9dbad6c`. Root has created the isolated worktree and synced only the existing locked dev dependencies. Before any production edit, root ran `uv run pytest -q -rs src/limn/runtime/tests/test_server.py src/limn/web/tests/test_web.py tests/contracts/test_contract_snapshot.py`: 145 tests and 159 subtests passed in 4.25 seconds. That baseline is evidence for existing behavior, not new admission tests or full CI.

| Path | Responsibility in this change |
| --- | --- |
| Create `src/limn/web/connection_policy.py` | Pure listener-local lease reservation, claim, irreversible stop and release; no I/O imports |
| Create `src/limn/web/connections.py` | Bounded IPv4/IPv6 `Server` subclasses; atomic shell transitions, real worker start, socket cleanup and fatal escape |
| Keep `src/limn/web/handler.py` | Existing `Server`, `Server6`, HTTP/1.1 `Handler`, body/error/auth behavior; no unrelated transport move |
| Modify `src/limn/runtime/args.py` | `--max-connections` parsing and English help |
| Modify `src/limn/runtime/config.py` | Explicit frozen `RunConfig.max_connections: int | None` without a default |
| Modify `src/limn/server.py` | `configure_run()` carries parsed value; `listen()` chooses transport; `main()` preserves fatal cause/nonzero through cleanup |
| Modify `tests/support/helpers.py` | Explicit `max_connections=None` in the existing `run_config()` fixture constructor |
| Create `src/limn/web/tests/test_connection_policy.py`, `test_connections.py`, `connection_support.py` | Pure properties and real TCP/lifecycle/fatal process tests colocated with transport |
| Create `src/limn/runtime/tests/test_connection_admission.py` | CLI/listen/main integration with real isolated assembly and process boundaries |
| Create `tests/contracts/test_connection_admission_work.py` | Narrow active pin/build cross-feature contract at process exit |
| Modify existing runtime constructors found by `rg 'RunConfig\('` | Supply the explicit default; do not change their existing assertions or move tests |
| Modify Handbook and bilingual README | Current optional-control behavior, why, cost, remaining gaps, and test observation limits |

There is no new capability slice or cross-feature import. The existing boundary checker permits `web/` and `runtime/` boundary dependencies and forbids imports into features. New web modules import only stdlib, their own owner, and existing boundary values. Keep feature export surfaces and `ENTRYPOINT_IMPORTS`/`TEST_EXPORTS` unchanged unless the checker demonstrates a required declaration; any proposed change needs root review before adoption.

## Interface agreement

These names make task handoffs concrete. They are internal modules, not HTTP or public feature APIs. A worker may improve internal representation during root review while preserving these semantics and updating all plan consumers together; no speculative infrastructure abstraction is needed.

```python
# connection_policy.py: frozen values, pure transitions; owner is an opaque object.
@dataclass(frozen=True)
class LeaseToken:
    owner: object
    generation: int


@dataclass(frozen=True)
class AdmissionState:
    limit: int
    owner: object
    next_generation: int = 0
    stopped: bool = False
    pending: frozenset[LeaseToken] = frozenset()
    claimed: frozenset[LeaseToken] = frozenset()


@dataclass(frozen=True)
class Reserved:
    state: AdmissionState
    token: LeaseToken


@dataclass(frozen=True)
class Full:
    pass


@dataclass(frozen=True)
class Stopped:
    pass


@dataclass(frozen=True)
class Claimed:
    state: AdmissionState


@dataclass(frozen=True)
class Cancelled:
    pass


# Signatures; full implementations belong to Task 1.
# reserve(state: AdmissionState) -> Reserved | Full | Stopped
# claim(state: AdmissionState, token: LeaseToken) -> Claimed | Cancelled
# stop(state: AdmissionState) -> AdmissionState
# release(state: AdmissionState, token: LeaseToken) -> AdmissionState
# admitted(state: AdmissionState) -> int
```

`AdmissionState.__post_init__()` guards positive non-bool `limit`, nonnegative generation, disjoint pending/claimed sets, ownership, allocated-generation range and capacity. Each release removes a token from live sets, is absorbing on repeat/stale/foreign tokens, and never decrements the generation. No retired-token list remains. `claim` succeeds only for a current pending token while admission is open. Stop fences pending entry but retains both sets; cancelled possible workers release only from their own cleanup/finally.

`BoundedServer(address, handler, *, max_connections: int)` and `BoundedServer6` in `connections.py` inherit the existing real transport's binding/backlog/daemon behavior. `server.listen()` still returns `Server | StartupRefused`, since bounded types subclass `Server`. Owned lifecycle methods are `_make_worker(request, client_address, token) -> threading.Thread`, `_start_worker(worker) -> None`, `_run_connection(request, client_address, token) -> None`, and `_cleanup_connection(request) -> None`. These signatures describe concrete responsibilities, not a configurable worker factory. `_start_worker`'s invocation is always treated as uncertain on failure; recovery is confined to construction before that invocation. Cleanup success means the actual socket is closed, not merely that an attempted close returned.

`FatalConnectionStart` is a nonzero `SystemExit` subtype carrying `original: BaseException`. It is a serving failure marker consumed by `server.main()` so secondary cleanup failures cannot turn it into zero. The transport publishes its listener-local fatal fuse before fallible stop coordination; both reservation and claim honor that fuse under the admission lock. `_fence_fatal(original: BaseException) -> BaseException` retains the first cause under that lock, with guarded fallback publication if the coordination itself fails. `_record_fatal(original: BaseException) -> None` then stops the pure admission state under its lock and retains the first cause. A failed coordination may leave pure stop incomplete, but the published fuse permanently denies both entry gates. `_fail_start(original: BaseException) -> NoReturn` best-effort closes the listener using real close/fallback operations and unconditionally raises the marker with the original as cause. Safe cause-type diagnostics (and numeric `SystemExit` codes) are best-effort stderr effects; payload text and traceback delivery are not promised. The public bounded `serve_forever()` shell protects that marker when stdlib parent cleanup replaces a dispatch error. `service_actions() -> None` observes worker-published fatal state and escapes the accepting loop. It must never call `BaseServer.shutdown()` from its own serving thread because that method waits for the serve loop to exit. Worker cleanup faults that cannot attest physical closure retain their lease and publish fatal state to the existing accepting loop, without adding a monitor thread or returning uncertain ownership. The accepting loop must observe that fatal state and escape nonzero even if the error occurred in a daemon worker.

### Task 1: Own bounded connections and pure lease invariants

**Files:** create `connection_policy.py`, `connections.py`, `web/tests/test_connection_policy.py`, `web/tests/test_connections.py`, and `web/tests/connection_support.py`. Existing listener classes remain unchanged and the new classes are not yet selected by CLI.

**Consumes:** real `web.handler.Server`, `Server6` and stdlib socketserver handler construction/cleanup. **Produces:** the pure values/functions and bounded listener signatures above, `FatalConnectionStart`, a functional minimal fatal recorder/escape, and narrow owned worker/cleanup methods for Task 2. This deliverable is independently exercised through direct bounded listeners; default production behavior is unchanged.

- [ ] **Step 1: Write direct pure tests and generated sequence properties.** Use `AdmissionState(2, object())`, reserve two tokens, assert the third result is `Full`, claim one, stop, assert new reserve is `Stopped`, assert pending claim is `Cancelled`, and assert both tokens remain until explicit cleanup release. Add constructor-invalid combinations, duplicate release, foreign owner with identical generation, and old generation after a new reserve. Generate sequences with Hypothesis over `reserve`, `claim`, `release`, `duplicate_release`, `stale_release`, and `stop`; retain returned tokens in the test harness, never duplicate the production transition algorithm.

```python
def test_old_cleanup_cannot_release_a_new_lease():
    """A retired generation cannot free a newly owned connection."""
    first = reserve(AdmissionState(1, object()))
    assert isinstance(first, Reserved)
    second = reserve(release(first.state, first.token))
    assert isinstance(second, Reserved)
    unchanged = release(second.state, first.token)
    assert admitted(unchanged) == 1
    assert unchanged == second.state


@given(st.lists(st.sampled_from(("reserve", "claim", "release", "stop")), max_size=80))
def test_generated_lifecycle_never_exceeds_capacity(events):
    """Any generated lifecycle keeps the cap and never reopens stopped admission."""
    state = AdmissionState(3, object())
    tokens = []
    ever_stopped = False
    for event in events:
        if event == "reserve":
            result = reserve(state)
            if isinstance(result, Reserved):
                state = result.state
                tokens.append(result.token)
            elif ever_stopped:
                assert isinstance(result, Stopped)
        elif event == "claim" and tokens:
            result = claim(state, tokens[-1])
            if isinstance(result, Claimed):
                state = result.state
        elif event == "release" and tokens:
            state = release(state, tokens[0])
        elif event == "stop":
            state = stop(state)
            ever_stopped = True
        assert 0 <= admitted(state) <= 3
        assert not ever_stopped or state.stopped
```

Add separate generated duplicate/stale/foreign and cancelled/claimed sequences; this short example does not replace those properties. Assertions compare outputs and ownership, never callback order.

- [ ] **Step 2: Observe the initial red run.** Run `uv run pytest -q -n 0 src/limn/web/tests/test_connection_policy.py`. An import failure alone establishes scaffolding absence; after exposing the module, require an actual capacity/stale/stop assertion failure before accepting the oracle. Store each original failure log outside the product tree.

- [ ] **Step 3: Implement immutable pure transitions with docstrings.** Under the shell's single lock, state assignment is atomic. Implement the following core regions and constructor invariants exactly; no socket/thread import belongs in this module.

```python
def reserve(state: AdmissionState) -> Reserved | Full | Stopped:
    """Reserve a new generation or return capacity/stopped refusal without I/O."""
    if state.stopped:
        return Stopped()
    if admitted(state) >= state.limit:
        return Full()
    token = LeaseToken(state.owner, state.next_generation)
    updated = replace(state, next_generation=state.next_generation + 1, pending=state.pending | {token})
    return Reserved(updated, token)


def claim(state: AdmissionState, token: LeaseToken) -> Claimed | Cancelled:
    """Claim only a live pending lease while admission is open."""
    if state.stopped or token not in state.pending:
        return Cancelled()
    return Claimed(replace(state, pending=state.pending - {token}, claimed=state.claimed | {token}))


def stop(state: AdmissionState) -> AdmissionState:
    """Fence future entry while retaining pending and claimed ownership."""
    return replace(state, stopped=True)


def release(state: AdmissionState, token: LeaseToken) -> AdmissionState:
    """Retire only the matching lease after the adapter attests physical cleanup."""
    return replace(state, pending=state.pending - {token}, claimed=state.claimed - {token})


def admitted(state: AdmissionState) -> int:
    """Count pending and claimed live connections without tracking retired identities."""
    return len(state.pending) + len(state.claimed)
```

- [ ] **Step 4: Add a real TCP fixture and failing saturation/recovery tests.** Use loopback port 0, real `socket.socket`, a real handler, and actual serve thread; `finally` closes clients, calls shutdown from the controller thread, closes server, and joins boundedly. A local probe handler uses HTTP/1.1, `Content-Length: 2`, and body `b"ok"`. `connection_support.open_listener(limit, family, handler)` is a context manager yielding the bounded listener, and `connection_support.assert_transport_closed(client)` reads with a two-second observation deadline and accepts EOF or `ConnectionResetError`, asserting no HTTP bytes. IPv6 uses `::1`; skip only an actual bind unavailable error with its errno, never a failed assertion. Include two simultaneous independent listeners. No fixed port, production service, global library patch, or timing sleep.

```python
def test_full_listener_refuses_before_headers(open_bounded_listener):
    """An admitted partial-header holder denies a new socket without an HTTP response."""
    with open_bounded_listener(1) as address:
        with socket.create_connection(address, timeout=2) as holder:
            holder.sendall(b"GET / HTTP/1.1\r\n")
            # A handler-owned event confirms the holder entered; do not infer from a sleep.
            assert open_bounded_listener.holder_entered.wait(2)
            with socket.create_connection(address, timeout=2) as refused:
                assert_transport_closed(refused)
        # An owned cleanup acknowledgement precedes this recovery assertion.
        assert open_bounded_listener.holder_cleaned.wait(2)
        with http.client.HTTPConnection(*address, timeout=2) as recovered:
            recovered.request("GET", "/")
            assert recovered.getresponse().read() == b"ok"
```

Define the fixture function and its events in the test module, using the concrete probe handler's `setup`/`finish` and transport cleanup hook; those are synchronization points, not private-call-count or order oracles. Add idle keep-alive reuse, actively blocked handler, immediate EOF, and short-timeout subclass scenarios. Check the refused handler has no externally visible marker (e.g. no response or file effect); do not assert how many private factory calls occurred.

- [ ] **Step 5: Implement bounded transport's success and proven pre-call cleanup paths.** Reserve under one listener-local lock before `_make_worker`. On `Full`/`Stopped`, perform immediate physical socket cleanup with no request worker. `_make_worker` creates one real daemon `threading.Thread` targeting `_run_connection`. The worker claims under the same lock before `finish_request()`, uses stdlib error reporting for ordinary handler faults, and always cleans the socket before release. An outer `finally` covers setup failure, where handler `finish()` itself may never run. `_cleanup_connection` uses stdlib `shutdown_request` and actual-close fallback and attests `fileno() == -1`; do not release on unsuccessful attestation. Pre-call construction failure is recoverable only after that success; start invocation failures are delegated to Task 2's fatal helper and never handled as ordinary recoveries.

```python
# Critical worker-finally region; retain the token if physical cleanup fails.
try:
    self._cleanup_connection(request)
except BaseException as cleanup_error:
    self._record_fatal(cleanup_error)
else:
    with self._admission_lock:
        self._admission = release(self._admission, token)
```

Implement the `FatalConnectionStart` class shown in Task 2, `_record_fatal`, `_fail_start`, and the accepting-loop fatal-state check in this task so the direct adapter has no missing collaborator or continued-admission path. Both invoked-start failure and unconfirmed cleanup use that explicit nonzero marker, with permanent stopped state and retained uncertain ownership. Task 2 hardens secondary-effect races and the composition root's cleanup protection, and proves the full fatal contract. Until Task 2 is complete, tests and root review must treat the new classes as internal and unreachable from CLI.

- [ ] **Step 6: Exercise physical cleanup faults and run the green gate.** Concrete owned cleanup overrides produce a pre-close failure with successful fallback, an error after actual close, and failure to attest either close. Successful physical cleanup releases once; unclosed/uncertain ownership is retained and fatal state is recorded. Add handler subclasses whose `setup`, `handle`, and `finish` fail and assert fresh TCP success after actual cleanup. Run `uv run pytest -q -n 0 src/limn/web/tests/test_connection_policy.py src/limn/web/tests/test_connections.py`, `uv run ruff check`, `uv run mypy`, and `uv run python tools/check_boundaries.py`. Record admitted peak, closed sockets, retired listener/thread cleanup and test counts; no lifetime tombstones.

- [ ] **Step 7: Mutate and review this unit.** Temporarily permit `admitted == N` reservation, release an old generation by integer/FD alone, or allow claim after stop. Run the associated tests and require assertion failures; restore mutations and show green. If a mutant survives, fail the experiment and repair the oracle. Root independently reviews the pure shell boundary and exact ownership before task commit. Commit only reviewed files with the repository's signed-off/CLA convention and an English message such as `feat: own bounded HTTP connection leases`.

### Task 2: Stop admission on uncertain native worker startup

**Files:** complete `src/limn/web/connections.py`; create colocated fatal/race cases in `web/tests/test_connection_fatal.py`, with real-process support in `fatal_process_support.py` and `cleanup_race_child.py`; modify `src/limn/server.py:main`; create fatal-process cases in `runtime/tests/test_connection_admission.py`. Keep the existing 535-line `test_connections.py` focused on success/pre-call cleanup and reuse its existing transport evidence. This internal test-layout refinement separates fatal supervision and the deterministic two-worker cleanup race without adding a capability or dependency; root approved the refinement during Task 2.

**Consumes:** Task 1's bounded classes, opaque lease tokens, atomic reserve/claim/stop/release, `FatalConnectionStart`, minimal fatal recorder/escape, and owned worker/cleanup adapters. **Produces:** hardened unconditional accepting-loop failure escape, pending-entry fencing, and cause-preserving runtime cleanup. It remains opt-in through direct bounded listeners until Task 3 wires CLI.

- [ ] **Step 1: Add bounded child-process tests before implementing fatal escape.** Child accepting loop runs on child MainThread, not an auxiliary thread that can die while the process survives. Supervisor uses `subprocess.Popen` with pipes and bounded `communicate(timeout=10)`, then terminate/kill/reap in `finally`; it records listener address, cause type, ownership observation and cleanup milestones through a pipe. Real connections drive actual stdlib `serve_forever()` dispatch. Child creates at most two listeners/eight sockets and starts no production service. Assert positive nonzero exit, retired port cannot serve, and original cause remains observable. Process deadlines are test safety limits only.

```python
class StartedThenFailed(BoundedServer):
    """Exercise an owned failure after real native worker start."""

    def _start_worker(self, worker):
        """Launch the real worker before reporting startup uncertainty."""
        super()._start_worker(worker)
        raise RuntimeError("owned startup failure after native launch")


class ZeroExitAfterStart(BoundedServer):
    """A start-boundary zero-exit interruption is still a failed instance."""

    def _start_worker(self, worker):
        """Launch real work, then exercise the dangerous successful-exit input."""
        super()._start_worker(worker)
        raise SystemExit(0)
```

Add `KeyboardInterrupt` and ordinary failure before real launch *inside the invoked start seam*; that seam's exception is still uncertain, not a recoverable pre-call failure. Construction failure belongs in `_make_worker` and must recover after physical cleanup. Tests must cover both ordinary stdlib-caught failure and zero exit with actual assertions; record red results.

- [ ] **Step 2: Harden the existing explicit fatal type and start boundary.** Task 1 already supplies the class below and a functional nonzero escape. Ensure this precise critical path and secondary-effect protection; do not inspect exception names/messages, `_started`, `ident`, or `is_alive` to decide no-launch. The pre-call construction catch and invoked-start catch are disjoint. `_fail_start` permanently stops state under the admission lock, tries real listener close and fallback, and raises `FatalConnectionStart` from its original cause in an outer `finally`, regardless of close/logging/coordination errors. Never release the uncertain token in that helper or parent dispatch cleanup.

```python
class FatalConnectionStart(SystemExit):
    """A bounded listener cannot safely continue after uncertain worker startup."""

    def __init__(self, original: BaseException):
        """Retain the initiating failure and force a nonzero serving result."""
        super().__init__(1)
        self.original = original


# process_request's actual invocation boundary:
try:
    self._start_worker(worker)
except BaseException as original:
    self._fail_start(original)
```

`socketserver._handle_request_noblock()` may call parent `shutdown_request()` while propagating a `BaseException`. Wrap the bounded serving shell as needed so even secondary parent-close failure cannot replace the stored fatal cause or suppress escape. `service_actions()` observes fatal state published by a cleanup failure; use the existing poll cycle or concrete wakeup rather than a new daemon. Stop/fencing must happen before close or warning effects. If the main listener cannot physically close, preserve failure and exit nonzero; do not claim that OS closure succeeded.

- [ ] **Step 3: Protect the composition root's nonzero result through current cleanup.** Keep `main()`'s normal `serve_forever`, listener-close, runtime-stop ordering and ordinary error semantics. For this explicit fatal type, execute cleanup even if close fails and guarantee nonzero rethrow in the outermost `finally`. Logging failure must not prevent runtime stop or change the fatal result. No broad refactor of application startup, runtime registry, signals, or process manager is needed.

```python
# Outer protection after existing cleanup attempts, including warning output:
finally:
    if isinstance(serving_error, FatalConnectionStart):
        raise serving_error from serving_error.original
```

Put this protection around the cleanup body, not merely after potentially raising print/close calls. For ordinary serving failures retain current behavior. Build the needed `FatalConnectionStart` import from the owned transport module without widening feature exports.

- [ ] **Step 4: Gate pending/claimed/no-worker ownership deterministically.** An owned worker-entry barrier holds the target before claim; after the start fault, assert it never creates a handler or writes a handler marker. A claimed worker confirms entry, then an owned cleanup-permission event blocks physical cleanup; observe one held lease despite parent socket closure and reject new TCP. Only then permit worker cleanup and observe zero. A start seam that raises without launching models an ambiguous no-worker state; record one retained lease through child teardown and nonzero exit. This state is intentional, not successful reclamation. No sleeps or polling `Thread._started` constitute proof. Repeat shutdown/stop and test partial startup without leaking listeners/watchers.

- [ ] **Step 5: Exercise fatal secondary effects.** Owned overrides inject close failure before physical close, error after physical close, unsuccessful fallback-close attestation, warning sink failure, and coordination failure. Each child observes admission stopped and exits nonzero with the original start cause. Couple any simulated pre-physical close error to the actual fallback/OS socket and record whether it closed; a failed native close cannot be declared successful from a stub. Ensure cleanup-induced `SystemExit(0)` is also subordinate to original failure. Supervisor kills/reaps only as test cleanup and fails on deadline, never counts forced cleanup as a product success.

- [ ] **Step 6: Run targeted green, mutation, and independent review.** Run `uv run pytest -q -n 0 src/limn/web/tests/test_connections.py src/limn/runtime/tests/test_connection_admission.py src/limn/runtime/tests/test_server.py`; then Ruff, both `uv run mypy` and `uv run mypy --platform darwin`, and boundaries. Mutate fatal handling into ordinary `RuntimeError`, return the uncertain token in parent cleanup, or permit `SystemExit(0)`; require process/ownership assertion failures and an explicit mutant-survived failure branch, then restore green. Root reviews cause preservation and actual stdlib control flow before signed-off logical commit `fix: fail closed on uncertain connection worker startup`.

### Task 3: Wire the opt-in CLI and preserve user contracts

**Files:** `runtime/args.py`, `runtime/config.py`, `server.py:configure_run/listen`, explicit fixture constructors in `tests/support/helpers.py` and current tests found by `rg`; `runtime/tests/test_connection_admission.py`; `web/tests/test_connections.py`; `tests/contracts/test_connection_admission_work.py`; `docs/handbook/architecture.md`, `operations.md`, `api.md`, `verification.md`, `code-style-roadmap.md`; `README.md`, `README.ko.md`, `CHANGELOG.md`; paired `skill/SKILL.md`/`SKILL.ko.md` only if their user guidance changes. No viewer assets, manager scripts, service templates or CI settings change.

**Consumes:** Task 2's complete bounded listener and fatal escape, existing `serve_parser`, `RunConfig`, `configure_run`, `listen`, `assemble_application` and `new_runtime`. **Produces:** optional direct CLI behavior, unchanged omitted-option path, production contract tests, and current Handbook explanation. This is the first task that selects bounded listeners from production settings.

- [ ] **Step 1: Write parsing/default/wiring red tests.** Parse `--manuscript <temporary root>` with omitted option and with `--max-connections 1`/`7`; assert `None` and positive int values. Parameterize zero, negative, missing value, empty string, `1.5` and alphabetic input: argparse exits nonzero and no listener/state is started. Test very long digit input according to that interpreter's actual `int(raw)` contract: if conversion rejects it, expose a nonzero argparse error; if conversion accepts a positive integer (including Python 3.10 environments without a conversion ceiling), accept it. Do not invent a numeric maximum. Standard positive integer textual syntax is sufficient. Construct a real minimal temporary manuscript and existing view-only artifact where startup integration requires it. Use real isolated assembly and `listen(app.web)` at port 0; do not replace global parser/socket imports.

```python
@pytest.mark.parametrize("raw", ["0", "-1", "", "1.5", "many"])
def test_invalid_connection_cap_is_a_usage_error(raw):
    """Invalid caps stop at parsing before startup can listen."""
    parser = ps.build_arg_parser()
    with pytest.raises(SystemExit) as result:
        parser.parse_args(["--manuscript", ".", "--max-connections", raw])
    assert result.value.code != 0


def test_omitted_cap_remains_explicitly_disabled():
    """Existing serve commands do not enable the new transport policy."""
    parsed = ps.build_arg_parser().parse_args(["--manuscript", "."])
    assert parsed.max_connections is None
```

- [ ] **Step 2: Implement positive parsing and explicit configuration wiring.** Add a documented `positive_connections(raw: str) -> int` in `runtime/args.py`; use `int(raw)` with `ValueError`/overflow conversion to `argparse.ArgumentTypeError`, reject `<=0`, and give a stable English usage message. `argparse` owns the expected startup error at this boundary. Add the parser argument and explicit `RunConfig` field; update every real constructor found by `rg -n 'RunConfig\(' src tests`. Pass `a.max_connections` from `configure_run`, no environment key or implicit field default.

```python
ap.add_argument(
    "--max-connections",
    type=positive_connections,
    default=None,
    metavar="N",
    help="Maximum admitted live connections for this listener (positive integer; omitted: unlimited). "
    "Counts active and idle keep-alive connections; excess sockets close before HTTP parsing",
)

# In listen(), inside its existing OSError-to-listen_refusal boundary:
if config.max_connections is None:
    return (Server6 if ":" in config.access.bind else Server)((config.access.bind, config.port), handler)
listener = BoundedServer6 if ":" in config.access.bind else BoundedServer
return listener((config.access.bind, config.port), handler, max_connections=config.max_connections)
```

Keep the existing bound-handler application wiring. All default `RunConfig` fixture calls explicitly pass `max_connections=None`; setting the cap selects only transport and does not affect security settings.

- [ ] **Step 3: Gate default-off real TCP and admitted HTTP compatibility.** With omitted option hold more connections than the test's small bounded cap and observe legitimate requests succeed; prove default start-failure handling with a concrete legacy `Server` subclass fault and continued successful TCP, without touching bounded behavior. For bounded mode run the same live IPv4/IPv6 saturation/recovery and two-listener isolation tests through `server.listen` and full Limn application.

Use `tests/support/helpers.py:run_config`, `ApplicationFixture`/`assemble_application`, `new_runtime` and isolated temporary state directories. Use `helpers_access` identity header constants and real members/tokens. One keep-alive connection carries an editor GET then viewer POST: second response must be the existing `403 viewer_only`, its body fully framed, the socket closes, and pin files are unchanged. Exercise bad/missing/revoked bearer, malformed/duplicate body/query/header, truncated/oversized body, Host/Origin refusal, normal route response and existing 500 viewer/privileged detail rules. Run existing `web/tests/test_request_boundary.py`, `security/tests/test_access_paths.py`, `security/tests/test_identity_integrity.py`, `security/tests/test_build_access.py` and `tests/contracts/test_contract_snapshot.py` without modifying expected messages/fields. A socketpair-only test cannot stand in for bounded listener coverage.

- [ ] **Step 4: Test interrupted real pin/build work at the existing guarantee.** Use a bounded child process, real temporary files and an actual pin HTTP POST. An owned pin-write barrier at `PinStore`'s atomic replacement holds work; another socket induces actual-start uncertainty. Supervisor observes nonzero child result and retired listener, then parses complete old-or-new JSONL. If exit falls after JSONL replacement but before Markdown/notice effects, allow stale `pins.md` and absent notices; verify startup repair through the existing pin-store startup path rather than inventing rollback. Source authority is `pins/store.py:transact()` and `domain.md` §저장소 안전성.

For builds, hold an actual owned prepublication subprocess/input barrier before `builds/engine.py:draw_pages` starts its `ThreadPoolExecutor`; old published page pointer and bytes remain the publication oracle. A tool-present `tex` case may use real TeX plus `helpers.BuildGate`; tool absence is reported under existing require-TeX behavior. Release bounded test subprocess gates in supervisor `finally`, and record cleanup. Do not require async job completion, complete descendant reaping, or a fixed total fatal-exit duration. `ThreadPoolExecutor` interpreter shutdown joins can exceed runtime watch joins; rendering has its existing 600-second timeout. No executor-policy change is authorized.

- [ ] **Step 5: Synchronize current documentation in both languages.** Update the operations argument table and a complete optional-control paragraph: default off, positive N, pending/active/idle ownership, immediate transport close, no HTTP response, actual-start fatal behavior, existing cleanup/availability cost, later operator budget and configuration rollback. Update API's broad “every error is JSON” language narrowly to apply to admitted HTTP requests; say cap refusal happens before HTTP and does not add an error code. Preserve every existing response sentence and reason. Architecture records web ownership and per-listener opaque generation with D2/D4 source; verification records actual tests as existing CI gates with native-exhaustion/OS-close/proxy/total-SLA limits. Code-style-roadmap narrows the current “HTTP connection cap absent” gap to optional/default-off control while preserving per-principal work-cost gaps. Handbook paragraphs cite ADR-0016 D1–D5 and remain complete without its link. README pairs describe opt-in control and cost without recommending N; CHANGELOG records the new option without a release/version bump. Root reviews ADR/spec/plan and all public text for scope/privacy. No visible UI is changed, so no UI PoC is added.

- [ ] **Step 6: Run required integration gates once and retain exact results.** Run the commands below after targeted tests pass; report counts, skips and reasons, assertion-bearing red/mutation runs, missing managed tools and limits. Preserve `.github/workflows/ci.yml` and all ten verification areas. Local success alone does not claim remote Linux/macOS/browser/TeX/install jobs ran.

```bash
uv sync --group dev --locked
uv run pytest -q -rs
bash src/limn/administration/tests/test_instances.sh
uv run ruff check
uv run ruff format --check
uv run shellcheck src/limn/administration/instances.sh src/limn/administration/instance_*.sh src/limn/administration/tests/test_instances.sh
uv run python tools/check_boundaries.py
uv run mypy
uv run mypy --platform darwin
npm ci --ignore-scripts
npm run typecheck
uv run python tools/strict_ratchet.py
```

CI retains `test` Linux Python 3.10/3.12 core/browser, `macos` Python 3.12 core, required Chromium/Firefox/WebKit and node, required real TeX/bwrap in `tex`, Linux/macOS `instances`, installation/package smoke in `install`, and `lint` gates. Confirm wheel omits colocated test files; the existing CI install smoke checks this. No new managed dependency is faked or new gate setting is introduced. If a full required environment cannot run locally, record it and wait for its existing CI job before calling merge-ready.

- [ ] **Step 7: Finish independent branch review and documentation projection.** Root reconciles refreshed upstream without losing concurrent changes, reruns affected checks only if there is new code/drift/failure, and verifies spec-to-test coverage, physical cleanup, fatal exit cause, default-off separation and no UI/config/service rollout. Review Handbook current-state claims against actual code, including remaining gaps. Keep ADR proposal status until approved final merge. Commit the reviewed task with signed-off/CLA English message `feat: expose optional connection admission control`. Publication, merge, deployment and production activation follow the user's authorized scope separately; no worker performs them from this plan.

## Handbook-read 결과

### 현재 권위와 상태

- **질문 종류:** 현재 실재 / 현재 계약 / 결정 이유 / 변경 의도.
- **role / path:** purpose / `docs/handbook/purpose.md`. **실제 정본:** 동작은 `src/limn` 코드·테스트, API 계약은 `docs/handbook/api.md`, 구조는 `architecture.md`, 검증은 `verification.md`, 코딩은 팀 스킬. **확인한 현재값:** 이 분리를 유지한다.
- **role / path:** architecture / `docs/handbook/architecture.md`. **실제 정본:** `web/handler.py:Server/Server6/Handler`, `server.py:listen/main`, `runtime/resources.py:stop`. **확인한 현재값:** daemon HTTP 스레드, backlog 128, cap 없음, handler timeout 30초, 실행별 stop event와 등록 thread별 5초 join. 새 cap·fatal 정책은 승인된 목표이고 아직 실제 구현은 아니다.
- **role / path:** 일반 주제 / `docs/handbook/operations.md`, `api.md`, `code-style-roadmap.md`, `workflow.md`. **실제 정본:** `runtime/args.py:serve_parser`, `runtime/config.py:RunConfig`, `security/access.py`, `pins/store.py`, 팀 스킬. **확인한 현재값:** 옵션 없음, 설정 필드에 기본값 없음, 매 요청 신원/역할 검증, API 오류 JSON·30초 timeout, 핀 잠금·원자적 교체와 시작 시 파생 Markdown 복구, 승인 후 구현·변경과 같은 Handbook 동기화.
- **role / path:** verification / `docs/handbook/verification.md`. **실제 정본:** `.github/workflows/ci.yml`, `pyproject.toml`, `tests/contracts/test_contract_snapshot.py`, `tools/check_boundaries.py`. **확인한 현재값:** 기존 열 개 검증 영역, Python/OS matrix와 required tool 환경, colocated 테스트 수집/휠 제외, pure Hypothesis·실패 관찰 계약을 유지한다.

### 지켜야 할 현재 불변식

1. architecture / `docs/handbook/architecture.md`: loopback 기본값과 신원·권한 경계, 표준 라이브러리 런타임, 실행별 격리, feature import 금지, entry point 조립 책임을 유지한다.
2. 일반 주제 / `docs/handbook/api.md`: admitted 요청의 body/framing·신원·입장·역할 순서, 오류 문장·reason·경로·필드·pins.md 호환을 보존한다. transport close는 HTTP 응답으로 만들지 않는다.
3. 일반 주제 / `docs/handbook/code-style-roadmap.md`: pure 판단과 I/O shell, 명시적 상태·constructor 불변식, private까지 계약 docstring, 테스트 동거·real managed dependencies·생성 성질·실제 red를 지킨다.
4. verification / `docs/handbook/verification.md`: 기존 게이트와 CI 환경을 줄이지 않고 실행 결과·미실행 도구·보장 한계를 측정해 보고한다.
5. 일반 주제 / `docs/handbook/workflow.md`: 승인 범위에서 구현하며 역사 ADR 동결을 보존하고 구현과 같은 변경에서 현재 Handbook·두 언어 문서를 정렬한다.

### 설계 이유와 제약

- **role / path:** architecture / `docs/handbook/architecture.md`. **이유·감수한 비용·적용 조건:** 단일 배포/stdlib은 설치를 단순하게 하고 실행별 자원은 인스턴스 누수를 막는다. 전송 cap은 `web/` 소유로 기능 권한과 분리하며 기존 코드 이동/새 배포가 필요 없다.
- **role / path:** 일반 주제 / `docs/handbook/api.md`, `code-style-roadmap.md`. **이유·감수한 비용·적용 조건:** proxy backend 재사용 때문에 응답마다 연결 lease를 반환하지 않고 신원은 매 요청 새로 검증한다. 오류 후 close/body 완독은 다음 요청의 권한 우회를 막는다. cap은 사용자 공정성/작업 비용을 해결하지 않는다.
- **role / path:** 일반 주제 / `docs/handbook/workflow.md`, `operations.md`. **이유·감수한 비용·적용 조건:** 새 수명/동시성 정책은 승인하고 기록한 뒤 구현한다. 명시적 opt-in은 운영 숫자 근거 없이 기존 설치에 비용을 강요하지 않는다. fatal 시작은 안전한 소유권을 위해 다른 in-flight 작업 가용성을 포기한다.
- **role / path:** verification / `docs/handbook/verification.md`. **이유·감수한 비용·적용 조건:** 관찰 가능한 TCP/process/file 결과와 pure 성질을 gate로 삼고 속도·자원 표본/버린 spike는 정보로만 쓴다. 테스트 deadline은 제품 SLA가 아니다.

### 충돌·미확인

- cap과 fatal 시작 처리는 승인된 목표이며 현재 HEAD에 없다. 이 계획과 구현 검수 전 Handbook에 구현된 현재값으로 쓰지 않는다.
- 이전 spike의 native exhaustion, 모든 OS-close 실패, 임의 신호, proxy 오류 변환·backend user correspondence, 운영 N·host limits와 실제 수요는 미확인이다. 구현 테스트가 확인하는 owned seam과 구별한다.
- runtime 5초 join은 총 종료 시간 상한이 아니다. `builds/engine.py:draw_pages`의 executor와 interpreter exit join이 더 오래 걸릴 수 있다. 이를 변경하지 않고 실험 gate를 prepublication에서 제한한다.
- corporate 업무 여부는 미확정이므로 chat/email을 보내지 않는다. 외부 연구 원문·실행 로그는 저장소 밖에 보존한다.

## 현재 상태 투영

- **영향받는 현재 권위:** `runtime/args.py`, `runtime/config.py`, `web/connections.py`, `web/connection_policy.py`, `server.py`와 실제 테스트·bilingual README.
- **갱신할 Handbook role/path:** architecture / `architecture.md`; verification / `verification.md`; 일반 주제 / `operations.md`, `api.md`, `code-style-roadmap.md`.
- **Handbook에 풀어 쓸 내용:** D1–D5의 optional default, lease 수명·원자성·식별자, HTTP 전 close, start 불확실성 실패 종료, 기존 정리 비용·활성화/공정성 한계를 출처와 함께 완결한다.
- **효력 형태:** 구현 뒤 현실 변경.
- **완료 증거:** 새 코드에서 opt-in/default separation을 관찰하고 TCP·process·pure/fault·active-work 테스트 및 기존 CI gates/독립 리뷰와 Handbook diff를 대조한다. 승인이나 ADR만으로 완료를 선언하지 않는다.
