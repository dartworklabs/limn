"""Immutable resource identity shared by authorization and document selection."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorityScope:
    """A run resource identity plus its immutable storage namespace.

    A pin store is reconstructed per call; its runtime lock and resolved state
    directory identify the same resource without caching mutable settings. Additional
    resource references are retained and compared by identity, never mutable equality.
    """

    owner: object
    namespace: object
    resources: tuple[object, ...] = ()
