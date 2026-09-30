"""Public operations and values owned by the pins capability."""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application import (
        PinReadView as PinReadView,
        PinStartup as PinStartup,
        PinSubsystem as PinSubsystem,
        assemble_pins as assemble_pins,
        pin_route_bundle as pin_route_bundle,
    )
    from .claims import PinClaims as PinClaims, pin_actions as claims_actions
    from .context import Json as Json, PinContext as PinContext, is_agent as is_agent, who as who
    from .editing import (
        PIN_PATH as PIN_PATH,
        POST_NEW_PIN as POST_NEW_PIN,
        EditingRequests as EditingRequests,
        EditScope as EditScope,
        PinEditing as PinEditing,
        pin_actions as editing_actions,
        post_route as editing_post,
    )
    from .lifecycle import PinLifecycle as PinLifecycle, pin_actions as lifecycle_actions
    from .listing import PinListing as PinListing, PinMarkdown as PinMarkdown, get_route as listing_get
    from .listing.projection import pin_state as pin_state, public_record as public_record
    from .location import (
        PICK_PATH as PICK_PATH,
        PickContext as PickContext,
        PinLocationService as PinLocationService,
        TokenCache as TokenCache,
        get_route as location_get,
        post_route as location_post,
    )
    from .location.lookup import (
        Locator as Locator,
        PinLocation as PinLocation,
        est_context as est_context,
        locate_file as locate_file,
        overlaps_by_id as overlaps_by_id,
        overlaps_for_range as overlaps_for_range,
        pin_file as pin_file,
        pin_location as pin_location,
        stamp_location as stamp_location,
        sync_all as sync_all,
    )
    from .location.position import EstContext as EstContext
    from .mentions import (
        NoteTags as NoteTags,
        note_mention_targets as note_mention_targets,
        note_tags as note_tags,
        tag_note as tag_note,
    )
    from .model import (
        EventType as EventType,
        OpenPin as OpenPin,
        Pin as Pin,
        Record as Record,
        TrashedPin as TrashedPin,
        is_region_pin as is_region_pin,
        state_of as state_of,
    )
    from .record import Broken as Broken, parse_record as parse_record, parse_trashed as parse_trashed
    from .revision import RevisionPin as RevisionPin, revision_pin as revision_pin
    from .runtime import PinCommands as PinCommands
    from .store import PinFiles as PinFiles, PinStore as PinStore, Row as Row, find_pin as find_pin
    from .trash import PinTrash as PinTrash, other_posts as trash_posts, pin_actions as trash_actions

__all__ = [
    "assemble_pins",
    "Broken",
    "EditScope",
    "EditingRequests",
    "EstContext",
    "EventType",
    "Json",
    "Locator",
    "NoteTags",
    "OpenPin",
    "PICK_PATH",
    "PIN_PATH",
    "POST_NEW_PIN",
    "PickContext",
    "Pin",
    "PinClaims",
    "PinCommands",
    "PinContext",
    "PinEditing",
    "PinFiles",
    "PinLifecycle",
    "PinListing",
    "PinLocation",
    "PinLocationService",
    "PinMarkdown",
    "PinReadView",
    "PinStartup",
    "PinStore",
    "PinSubsystem",
    "PinTrash",
    "Record",
    "Row",
    "TokenCache",
    "TrashedPin",
    "RevisionPin",
    "claims_actions",
    "editing_actions",
    "editing_post",
    "est_context",
    "find_pin",
    "is_agent",
    "is_region_pin",
    "lifecycle_actions",
    "listing_get",
    "locate_file",
    "location_get",
    "location_post",
    "note_mention_targets",
    "note_tags",
    "overlaps_by_id",
    "overlaps_for_range",
    "parse_record",
    "parse_trashed",
    "pin_file",
    "pin_location",
    "pin_route_bundle",
    "pin_state",
    "public_record",
    "revision_pin",
    "stamp_location",
    "state_of",
    "sync_all",
    "tag_note",
    "trash_actions",
    "trash_posts",
    "who",
]

_EXPORTS = {
    "assemble_pins": ("application", "assemble_pins"),
    "Broken": ("record", "Broken"),
    "EditScope": ("editing", "EditScope"),
    "EditingRequests": ("editing", "EditingRequests"),
    "EstContext": ("location.position", "EstContext"),
    "EventType": ("model", "EventType"),
    "Json": ("context", "Json"),
    "Locator": ("location.lookup", "Locator"),
    "NoteTags": ("mentions", "NoteTags"),
    "OpenPin": ("model", "OpenPin"),
    "PICK_PATH": ("location", "PICK_PATH"),
    "PIN_PATH": ("editing", "PIN_PATH"),
    "POST_NEW_PIN": ("editing", "POST_NEW_PIN"),
    "PickContext": ("location", "PickContext"),
    "Pin": ("model", "Pin"),
    "PinClaims": ("claims", "PinClaims"),
    "PinCommands": ("runtime", "PinCommands"),
    "PinContext": ("context", "PinContext"),
    "PinEditing": ("editing", "PinEditing"),
    "PinFiles": ("store", "PinFiles"),
    "PinLifecycle": ("lifecycle", "PinLifecycle"),
    "PinListing": ("listing", "PinListing"),
    "PinLocation": ("location.lookup", "PinLocation"),
    "PinLocationService": ("location", "PinLocationService"),
    "PinMarkdown": ("listing", "PinMarkdown"),
    "PinReadView": ("application", "PinReadView"),
    "PinStartup": ("application", "PinStartup"),
    "PinStore": ("store", "PinStore"),
    "PinSubsystem": ("application", "PinSubsystem"),
    "PinTrash": ("trash", "PinTrash"),
    "Record": ("model", "Record"),
    "Row": ("store", "Row"),
    "TokenCache": ("location", "TokenCache"),
    "TrashedPin": ("model", "TrashedPin"),
    "RevisionPin": ("revision", "RevisionPin"),
    "claims_actions": ("claims", "pin_actions"),
    "editing_actions": ("editing", "pin_actions"),
    "editing_post": ("editing", "post_route"),
    "est_context": ("location.lookup", "est_context"),
    "find_pin": ("store", "find_pin"),
    "is_agent": ("context", "is_agent"),
    "is_region_pin": ("model", "is_region_pin"),
    "lifecycle_actions": ("lifecycle", "pin_actions"),
    "listing_get": ("listing", "get_route"),
    "locate_file": ("location.lookup", "locate_file"),
    "location_get": ("location", "get_route"),
    "location_post": ("location", "post_route"),
    "note_mention_targets": ("mentions", "note_mention_targets"),
    "note_tags": ("mentions", "note_tags"),
    "overlaps_by_id": ("location.lookup", "overlaps_by_id"),
    "overlaps_for_range": ("location.lookup", "overlaps_for_range"),
    "parse_record": ("record", "parse_record"),
    "parse_trashed": ("record", "parse_trashed"),
    "pin_file": ("location.lookup", "pin_file"),
    "pin_location": ("location.lookup", "pin_location"),
    "pin_route_bundle": ("application", "pin_route_bundle"),
    "pin_state": ("listing.projection", "pin_state"),
    "public_record": ("listing.projection", "public_record"),
    "revision_pin": ("revision", "revision_pin"),
    "stamp_location": ("location.lookup", "stamp_location"),
    "state_of": ("model", "state_of"),
    "sync_all": ("location.lookup", "sync_all"),
    "tag_note": ("mentions", "tag_note"),
    "trash_actions": ("trash", "pin_actions"),
    "trash_posts": ("trash", "other_posts"),
    "who": ("context", "who"),
}


def __getattr__(name: str) -> object:
    """Load only the requested public operation without initializing unrelated adapters."""
    if name not in _EXPORTS:
        raise AttributeError(name)
    module, symbol = _EXPORTS[name]
    return getattr(import_module(f".{module}", __name__), symbol)
