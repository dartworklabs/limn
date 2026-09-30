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


LOCAL_LOGIN = "local"
CONFIRM_BY_HUMAN = "확인은 사람이 합니다 — 테일넷 신원으로 접속해 뷰어에서 [확인]을 누르세요."
