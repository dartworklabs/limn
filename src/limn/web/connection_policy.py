"""Immutable listener-local admission decisions; effects and cleanup attestations belong to the adapter."""

from dataclasses import dataclass, replace


@dataclass(frozen=True, eq=False)
class LeaseToken:
    """An opaque listener identity and nonnegative, never-reused allocation generation."""

    owner: object
    generation: int

    def __post_init__(self) -> None:
        """Reject invalid generations before they can enter any listener's live sets."""
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("Lease generation must be a nonnegative integer")

    def __eq__(self, other: object) -> bool:
        """Compare owner identity, independent of user-defined equality on an opaque owner."""
        if not isinstance(other, LeaseToken):
            return NotImplemented
        return self.owner is other.owner and self.generation == other.generation

    def __hash__(self) -> int:
        """Hash the same identity and generation used by equality for immutable live sets."""
        return hash((id(self.owner), self.generation))


@dataclass(frozen=True)
class AdmissionState:
    """Valid bounded ownership; stopping fences entry without discarding pending or claimed leases."""

    limit: int
    owner: object
    next_generation: int = 0
    stopped: bool = False
    pending: frozenset[LeaseToken] = frozenset()
    claimed: frozenset[LeaseToken] = frozenset()

    def __post_init__(self) -> None:
        """Reject mutable, foreign, unissued, overlapping or over-capacity live ownership."""
        if isinstance(self.limit, bool) or not isinstance(self.limit, int) or self.limit <= 0:
            raise ValueError("Connection limit must be a positive integer")
        if (
            isinstance(self.next_generation, bool)
            or not isinstance(self.next_generation, int)
            or self.next_generation < 0
        ):
            raise ValueError("Next lease generation must be a nonnegative integer")
        if not isinstance(self.stopped, bool):
            raise ValueError("Stopped admission must be a boolean")
        if not isinstance(self.pending, frozenset) or not isinstance(self.claimed, frozenset):
            raise ValueError("Live leases must be immutable sets")
        if self.pending & self.claimed:
            raise ValueError("Pending and claimed leases must be disjoint")
        for token in self.pending | self.claimed:
            if not isinstance(token, LeaseToken) or token.owner is not self.owner:
                raise ValueError("Live leases must belong to this listener")
            if token.generation >= self.next_generation:
                raise ValueError("Live lease generation must already be allocated")
        if len(self.pending) + len(self.claimed) > self.limit:
            raise ValueError("Live leases must not exceed connection capacity")


@dataclass(frozen=True)
class Reserved:
    """A newly allocated pending token and the immutable state that owns it."""

    state: AdmissionState
    token: LeaseToken


@dataclass(frozen=True)
class Full:
    """Capacity refuses a new lease without changing state or performing effects."""


@dataclass(frozen=True)
class Stopped:
    """Permanently fenced admission refuses a new lease regardless of free capacity."""


@dataclass(frozen=True)
class Claimed:
    """The updated state grants the pending worker permission to construct its handler."""

    state: AdmissionState


@dataclass(frozen=True)
class Cancelled:
    """An absent or stopped pending token grants no entry and retains cleanup ownership."""


def reserve(state: AdmissionState) -> Reserved | Full | Stopped:
    """Allocate a pending generation, or return capacity/stopped refusal without I/O."""
    if state.stopped:
        return Stopped()
    if admitted(state) >= state.limit:
        return Full()
    token = LeaseToken(state.owner, state.next_generation)
    updated = replace(state, next_generation=state.next_generation + 1, pending=state.pending | {token})
    return Reserved(updated, token)


def claim(state: AdmissionState, token: LeaseToken) -> Claimed | Cancelled:
    """Move only a live pending lease to claimed while entry remains open; perform no I/O."""
    if state.stopped or token not in state.pending:
        return Cancelled()
    return Claimed(replace(state, pending=state.pending - {token}, claimed=state.claimed | {token}))


def stop(state: AdmissionState) -> AdmissionState:
    """Permanently fence future entry while preserving pending and claimed cleanup ownership."""
    return replace(state, stopped=True)


def release(state: AdmissionState, token: LeaseToken) -> AdmissionState:
    """Retire an exact token after caller-attested cleanup; stale/foreign repeats leave state unchanged."""
    return replace(state, pending=state.pending - {token}, claimed=state.claimed - {token})


def admitted(state: AdmissionState) -> int:
    """Count live pending and claimed leases without retaining any retired identities."""
    return len(state.pending) + len(state.claimed)
