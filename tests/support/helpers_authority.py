"""Explicit authorization fixtures for direct mutation-service tests."""

from limn.pins.store import PinStore
from limn.runtime.documents import Doc, document_authority_target
from limn.security.access import AuthorityScope, Principal, _authorize_post, is_agent_actor


def post_authority(scope, actor, operation, target=None, *, role=None):
    """Authorize a test principal for exactly one instance, operation and target.

    Human fixtures default to owner so tests about storage can exercise destructive
    operations; role-policy tests pass the intended role explicitly.
    """
    if isinstance(scope, PinStore):
        scope = AuthorityScope(scope.lock, str(scope.files.state.resolve()))
    elif hasattr(scope, "authority_scope"):
        scope = scope.authority_scope
    if isinstance(target, Doc):
        target = document_authority_target(target)
    principal = Principal(dict(actor), role or ("agent" if is_agent_actor(actor) else "owner"), "header")
    paths = {"add": "/api/pin", "pick": "/api/pick", "rebuild": "/api/rebuild", "revision-build": "/api/revision-build"}
    path = paths.get(operation, "/api/clear" if operation == "clear" else f"/api/pins/{target}/{operation}")
    return _authorize_post(principal, path, scope, target if operation in paths else None, 30)
