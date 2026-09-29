"""Shared pure pin limits, identities and range scope vocabulary."""

from typing import Literal, TypeAlias, TypeGuard, get_args

# The assignee value that hands a pin to the agent rather than to a person (docs/handbook/api.md §담당).
ASSIGNEE_AGENT = "agent"
# The headerless loopback agent's login (server.LOCAL_ACTOR). It is never a person, so never an assignee.
LOCAL_LOGIN = "local"
# A pin's note, in characters: the limit a new or replaced note must fit, and a note_append merged into it.
NOTE_MAX = 4000
# scope: which rung of the range ladder a line pin was placed at (limn.mapping.compute_levels: raw drag, paragraph,
# the innermost environment and up to two outer ones, or plain lines).
Scope: TypeAlias = Literal["raw", "para", "env", "env2", "env3", "lines"]
SCOPES: tuple[Scope, ...] = get_args(Scope)
# The region text a view-only PDF pin keeps as its quote - longer than a line pin's 60 characters, since the text is
# all an agent has to find the place by.
PDF_QUOTE_MAX = 160


def is_scope(v: object) -> TypeGuard[Scope]:
    """Is v one of SCOPES? The check the add and edit parsers share."""
    return v in SCOPES
