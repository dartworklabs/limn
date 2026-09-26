"""The documents one viewer serves (docs/handbook/domain.md §여러 문서): what a lookup of a document by key can answer.

One address shows several documents of a paper - the body, the review response, the cover letter - each under a
key (?doc=). A request that names a key the instance does not serve is answered with the keys it does serve, so a
client can correct itself; silently falling back to the first document would attach a pin to the wrong document.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocNotFound:
    """No document of this instance has the key a request named. known lists the keys it serves, in order (the
    404 body's `docs`)."""
    key: str
    known: tuple[str, ...]
