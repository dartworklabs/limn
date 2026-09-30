"""Assemble the run-specific facts that the pure pins.md renderer consumes."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from limn.builds import FigureMap, read_built_at as build_read_built_at, read_head as build_read_head
from limn.pins.element import element_of
from limn.pins.listing.projection import element_marks
from limn.pins.listing.render import (
    DocHeading,
    PinFacts,
    PinsMdInput,
    pins_md_text as render_pins_md_text,
    rel_badge,
    shared_part_path,
)
from limn.pins.location.lookup import PinLocation, doc_scope
from limn.pins.mentions import addressed_to, fyi_mentions_to, thread_round
from limn.pins.model import DonePin, OpenPin, Pin, Record, is_region_pin, state_of
from limn.pins.thread import pin_reopened_in_round
from limn.platform.files import tex_lines
from limn.platform.values import is_int
from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc, doc_by_key
from limn.security.access import file_present, home_or_none
from limn.security.guidance import shell_path

Json = dict[str, Any]


class MarkdownDeps(Protocol):
    """The run-specific facts and lookups needed to render pins.md."""

    C: RunConfig
    docs: list[Doc]

    def snapshot_pins(self) -> list[Pin]:
        """The live pins after their usual resynchronization."""
        ...

    def overlaps_by_id(self, pins: Sequence[Pin]) -> dict[int, list[Json]]:
        """The overlap relationships for the full live set."""
        ...

    def pin_location(self, r: Record, root: Path, state: Path) -> PinLocation | None:
        """Where this pin's source file lives under the manuscript root now."""
        ...

    def pin_doc_key(self, r: Record) -> str:
        """The document that owns this pin."""
        ...

    def doc_figure_map(self, key: str) -> FigureMap | None:
        """The loadable map of the build on screen of the figure document key names, or None."""
        ...


@dataclass
class PinMarkdown:
    """One run's pins.md input assembly and rendering."""

    deps: MarkdownDeps
    known_people: Callable[[Sequence[Pin] | None], dict[str, Json]]

    def current_text(self, base: str) -> str:
        """GET /pins.md after its shared guards and remote base calculation."""
        return self.pins_md_text(self.deps.snapshot_pins(), base=base)

    def pins_md_text(self, pins: Sequence[Pin], base: str | None = None) -> str:
        """pins.md's text for pins: limn.pins.listing.render.pins_md_text over pins_md_input(pins, base). The store renders with
        this after every write (base None: the file on disk) and GET /pins.md with the request's base."""
        return render_pins_md_text(self.pins_md_input(pins, base))

    def pins_md_input(self, pins: Sequence[Pin], base: str | None = None) -> PinsMdInput:
        """Everything one rendering of pins.md reads, gathered at the edge: this application's run settings, the documents and their
        build stamps, the clock, this machine's token file, people.json, and per pin what the overlap, @-tag, thread and
        file-location rules decide. base is GET /pins.md's request base, None for the file written to disk.

        The rules a pin's row follows are the overlap, @-tag, thread, file-location and figure-element ones - a figure
        pin's element is followed on its document's current map, read at most once per document per call (through
        the run's map cache, as GET /api/pins does), and its shared part is placed under its document's folder as
        text.

        Reads files (people.json, the build stamps, whether the token file exists, the source file of each open
        one-line pin that carries a quote - each file read at most once per call - and each figure document's
        current map) but writes nothing."""
        rows = [pin.record for pin in pins]
        rel = self.deps.overlaps_by_id(pins)
        by_id = {r["id"]: r for r in rows}
        sources: dict[Path, list[str]] = {}
        maps: dict[str, FigureMap | None] = {}
        facts: dict[int, PinFacts] = {}
        for pin in pins:
            r = pin.record
            if state_of(r) is DonePin:
                continue
            location, line_len = self._location_and_line_len(pin, sources)
            doc_key = self.deps.pin_doc_key(r)
            el_sync, impl_location = self._element_facts(r, doc_key, maps)
            facts[r["id"]] = PinFacts(
                doc_key=doc_key,
                location=location,
                line_len=line_len,
                badge=rel_badge(rel.get(r["id"], []), by_id, r),
                reopened=pin_reopened_in_round(pin.core.thread),
                addressed=tuple(addressed_to(pin)),
                fyi=tuple(fyi_mentions_to(pin)),
                round=tuple(thread_round(pin.core.thread)),
                el_sync=el_sync,
                impl_location=impl_location,
            )
        docs = tuple(
            DocHeading(
                d.key,
                d.name,
                d.rel_path(),
                view_only=d.view_only,
                builds_from_source=d.builds_from_source,
                head=build_read_head(d),
                built_at=build_read_built_at(d),
                has_element_map=d.has_element_map,
            )
            for d in self.deps.docs
        )
        return PinsMdInput(
            rows=rows,
            facts=facts,
            base=base,
            port=self.deps.C.port,
            manuscript=str(self.deps.C.src),
            label=self.deps.C.label,
            repo=self.deps.C.repo,
            docs=docs,
            people=self.known_people(pins),
            now=time.time(),
            updated=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
            token_file=self.existing_token_file_shown(self.deps.C.access.agent_token_file),
        )

    def _element_facts(
        self, r: Record, doc_key: str, maps: dict[str, FigureMap | None]
    ) -> tuple[str | None, str | None]:
        """A figure pin's facts for its row: el_sync on its document's current map (asked at most once per document per
        render, kept in maps) and the shared part's file relative to --manuscript (impl.file joined as text under the
        document's folder, doc_scope - never opened), or None for it when the pin's document is no longer served or
        impl.file may not be shown (limn.pins.listing.render.shared_part_path). (None, None) for a pin without a well-formed
        el. Total: a hostile stored el gives facts, never an error."""
        el = element_of(r.get("el"))
        if el is None:
            return None, None
        if doc_key not in maps:
            maps[doc_key] = self.deps.doc_figure_map(doc_key)
        sync = element_marks(r, maps[doc_key]).get("el_sync")
        doc = doc_by_key(self.deps.docs, doc_key)
        if el.impl is None or doc is None:
            return sync, None
        return sync, shared_part_path(doc_scope(doc, self.deps.C.src), el.impl.file)

    def _location_and_line_len(self, pin: Pin, sources: dict[Path, list[str]]) -> tuple[str, int | None]:
        """The pin's current display path and quoted line length, reading each source path at most once."""
        r = pin.record
        if is_region_pin(r):
            return "", None
        loc = self.deps.pin_location(r, self.deps.C.src, self.deps.C.state)
        location = loc.rel if loc is not None else (Path(str(r.get("file", ""))).name or str(r.get("name") or ""))
        lo, hi = r.get("lo"), r.get("hi")
        if not (
            loc is not None and state_of(r) is OpenPin and r.get("quote") and is_int(lo) and is_int(hi) and lo == hi
        ):
            return location, None
        if loc.path not in sources:  # outside the tree (loc None) is never read
            sources[loc.path] = tex_lines(loc.source)
        lines = sources[loc.path]
        return location, len(lines[lo - 1]) if 1 <= lo <= len(lines) else None

    def existing_token_file_shown(self, f: Path | None) -> str | None:
        """The shell path of token file f when it exists, else None - the edge half of
        limn.pins.listing.render.token_guidance_line(): one stat per render, never a read of the file."""
        return shell_path(f, home_or_none()) if file_present(f) else None
