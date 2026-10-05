"""What the document reads need supplied from outside the slice: pin counts and build facts.

GET /api/meta, /api/docs and /api/outline-labels report facts that the pins and the builds own. This module states,
as structural types, exactly the answers the document reads ask for. The slice imports no other capability: the
composition root (server.py) passes the suppliers' objects to assemble_documents, and the type checker proves there
that they match. Every member is read-only, so a frozen value satisfies it and nothing here can write back.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from limn.runtime.documents import Doc


class PinCounts(Protocol):
    """The pin counts and the pins' change token the document reads report; where the pins are stored and how a pin
    reaches its state stay with the supplier."""

    @property
    def counts_by_document(self) -> Callable[[set[str]], tuple[dict[str, int], int]]:
        """Given the keys of the documents served: the open-pin count of every document key that has open pins, and
        how many open pins belong to a key outside the given ones. Called from polling, so it must not
        resynchronize the pins."""
        ...

    @property
    def state_counts(self) -> Callable[[], dict[str, int]]:
        """The full /api/meta's n_open, n_done and n_review, in that order, as the supplier counts them after its
        own resynchronization."""
        ...

    @property
    def change_token(self) -> Callable[[], str]:
        """A string that differs whenever the stored pins changed, "0" before any pin was written; reported as
        pins_rev. Called from the light poll, so it must not write."""
        ...


class BuildSummary(Protocol):
    """The build-owned part of one document's /api/docs entry and /api/meta body, already complete: the reads copy
    these keys into their responses and never look at a page directory or a build marker themselves."""

    @property
    def brief(self) -> dict[str, Any]:
        """The document's /api/docs entry without its open-pin count, keys in contract order."""
        ...

    @property
    def meta(self) -> dict[str, Any]:
        """The build facts of /api/meta: pages, built_at, head, building, stale_build, src_mtime, build_src_mtime,
        pages_build, build_seq, last_build and build."""
        ...


class PublishedOutline(Protocol):
    """The outline input one build published: the text the outline parser reads, tied to the build it came from."""

    @property
    def build(self) -> str:
        """The name of the page directory on screen."""
        ...

    @property
    def text(self) -> str:
        """The .aux text published with that build, "" when there is none worth parsing."""
        ...


class BuildFacts(Protocol):
    """The two build questions the document reads ask. Both are called from polling and must not write."""

    @property
    def summary(self) -> Callable[[Doc, Path, int], BuildSummary]:
        """The build summary of a document, given the state folder and the dpi its page sizes are reported at."""
        ...

    @property
    def outline(self) -> Callable[[Doc], PublishedOutline]:
        """The outline input of the build a document has on screen."""
        ...
