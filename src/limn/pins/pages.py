"""What a line pin keeps of a page: nothing, on a document without pages (docs/adr/0025-html-document-surface.md D2).

A document the browser draws from its source (Doc.renders_in_browser, a Markdown or text document) has no pages, so its line
pins hold no page, frac or pdf_build, nor the legacy frac_build. The parsers drop the ones a request sends; values a
record still carries - a hand edit, a pin moved in from a generated .tex tab - go the next time that pin is written,
whatever writes it: an edit, a claim, a reply, a close, a confirmation, a reopen, a drop into the Trash, a restore, or
the anchor re-sync. Each writer asks its document whether it has pages and passes the answer here. A region pin keeps
its page and frac (they are its place), and a pin of a document with pages keeps everything.
"""

from typing import Any

from limn.pins.model import Record, is_region_pin
from limn.pins.thread import PinT

# Where on a page a line pin was picked, and on which build; frac_build is the legacy name of pdf_build.
PAGE_FIELDS = ("page", "frac", "pdf_build", "frac_build")


def page_fields_kept(record: Record, pages: bool) -> dict[str, Any]:
    """record's fields as a write keeps them, a new dict in the stored order: all of them when its document has pages
    (pages) or it is a region pin; otherwise a line pin's without PAGE_FIELDS."""
    if pages or is_region_pin(record):
        return dict(record)
    return {key: value for key, value in record.items() if key not in PAGE_FIELDS}


def keep_pages(pin: PinT, pages: bool) -> PinT:
    """pin as it is written on a document with pages or without (page_fields_kept), in its state; the same pin when
    nothing is dropped, so its stored line keeps its bytes."""
    kept = page_fields_kept(pin.record, pages)
    if len(kept) == len(pin.record):
        return pin
    return type(pin).from_record(kept)
