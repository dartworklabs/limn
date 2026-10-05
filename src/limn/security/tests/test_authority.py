"""Authorization values constrain every request to its approved effect and instance."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from limn.pins.claims.service import PinClaims
from limn.security import access
from limn.web.errors import HTTPError

from helpers_authority import post_authority
from helpers_pin_service import ServiceBase

ACTOR = {"login": "alice@example.com", "name": "Alice"}
OPERATIONS = (
    "/api/pick",
    "/api/revision-build",
    "/api/pin",
    "/api/rebuild",
    *(
        f"/api/pins/7/{action}"
        for action in ("reply", "close", "reopen", "edit", "claim", "unclaim", "drop", "restore", "confirm", "purge")
    ),
    "/api/clear",
)


@pytest.mark.parametrize("role", access.ROLES)
@pytest.mark.parametrize("path", OPERATIONS)
def test_current_role_operation_matrix(role, path):
    """Every current operation retains its explicit role permission and refusal reason."""
    principal = access.Principal(dict(ACTOR), role, "header")
    reason = None
    if role == "viewer" and path not in ("/api/pick", "/api/revision-build"):
        reason = "viewer_only"
    elif role == "agent" and path.endswith("/confirm"):
        reason = "confirm_by_human"
    elif role != "owner" and (path == "/api/clear" or path.endswith("/purge")):
        reason = "owner_only"
    if reason:
        with pytest.raises(HTTPError) as error:
            access.check_role(principal, path, 30)
        assert error.value.code == 403
        assert error.value.body["reason"] == reason
    else:
        access.check_role(principal, path, 30)


@pytest.mark.parametrize("role", access.ROLES)
@pytest.mark.parametrize("path", ("/api/new-operation", "/api/pins/7/newaction", "/api/rebuild/extra"))
def test_new_operations_never_acquire_authority(role, path):
    """Adding a dispatcher entry cannot silently grant any role a new action."""
    with pytest.raises(HTTPError) as error:
        access.check_role(access.Principal(dict(ACTOR), role, "header"), path, 30)
    assert error.value.code in (403, 404)


def test_new_read_registration_is_denied():
    """Admitted identity alone does not authorize a newly registered read path."""
    with pytest.raises(HTTPError) as error:
        access.check_read("/api/new-read")
    assert error.value.code == 404


@pytest.mark.parametrize("path", ("/vendor/pdfjs/pdf.min.mjs", "/vendor/pretendard/pretendard.css"))
def test_the_bundled_library_families_are_declared_reads(path):
    """The PDF.js and Pretendard folders are the two bundled-file families an admitted identity reads; their routes
    validate the leaf name."""
    access.check_read(path)


@pytest.mark.parametrize(
    "path",
    ("/vendor/lucide/LICENSE", "/vendor/", "/vendor/pretendardx/a.css", "/vendor/pretendard", "/vendor/x/y.woff2"),
)
def test_other_vendor_paths_are_denied(path):
    """A folder of vendor/ that is not a served family (Lucide is inlined, never served), the bare prefixes and a
    look-alike family name are not reads."""
    with pytest.raises(HTTPError) as error:
        access.check_read(path)
    assert error.value.code == 404


@pytest.fixture
def store_context():
    """Use the same real transactional store and files as the service contract tests."""
    case = ServiceBase()
    case.setUp()
    try:
        yield case
    finally:
        case.tearDown()


@pytest.mark.parametrize("mismatch", ("actor", "operation", "target", "instance", "state"))
def test_claim_boundary_refuses_wrong_authority_without_writing(store_context, mismatch):
    """Raw attribution and authority for another effect cannot reach a store mutation."""
    case = store_context
    pid = case.add()
    before = case.pins_bytes()
    scope = case.ctx.authority_scope
    authority = post_authority(scope, ACTOR, "claim", pid)
    if mismatch == "actor":
        authority = dict(ACTOR)
    elif mismatch == "operation":
        authority = post_authority(scope, ACTOR, "unclaim", pid)
    elif mismatch == "target":
        authority = post_authority(scope, ACTOR, "claim", pid + 1)
    elif mismatch == "instance":
        authority = post_authority(access.AuthorityScope(object(), scope.namespace), ACTOR, "claim", pid)
    else:
        authority = post_authority(access.AuthorityScope(scope.owner, scope.namespace + "/other"), ACTOR, "claim", pid)
    with pytest.raises(HTTPError) as error:
        PinClaims(lambda: case.ctx).claim_pin(pid, authority, 15)
    assert (error.value.code, error.value.body["reason"]) == (403, "invalid_authority")
    assert case.pins_bytes() == before


def test_immutable_identity_is_used_in_saved_claim(store_context):
    """Mutation after authorization cannot replace the principal recorded by the effect."""
    case = store_context
    pid = case.add()
    actor = dict(ACTOR)
    authority = post_authority(case.store, actor, "claim", pid)
    actor["login"] = "mallory@example.com"
    detached = authority.principal
    detached.actor["login"] = "mallory@example.com"
    with pytest.raises(FrozenInstanceError):
        authority._target = pid + 1
    PinClaims(lambda: case.ctx).claim_pin(pid, authority, 15)
    assert case.pin(pid)["claimed_by"]["login"] == ACTOR["login"]


def test_direct_constructor_requires_private_issuer():
    """An ordinary attribution mapping cannot create a valid authority by calling its type."""
    with pytest.raises(HTTPError):
        access.PostAuthority(object(), object(), "clear", None, access.Principal(ACTOR, "owner", "header"))


def test_production_authority_issuance_stays_at_the_boundary():
    """Python's private issuer is backed by an independent production source guard."""
    root = Path(__file__).resolve().parents[4] / "src" / "limn"
    violations = []
    for path in root.rglob("*.py"):
        if "tests" in path.relative_to(root).parts or path.relative_to(root).as_posix() == "security/access.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            name = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
            if name in ("_AUTHORITY_KEY", "_authorize_post") and not (
                path.relative_to(root).as_posix() == "security/application.py" and name == "_authorize_post"
            ):
                violations.append((str(path.relative_to(root)), node.lineno, name))
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in ("_AUTHORITY_KEY", "_authorize_post"):
                        violations.append((str(path.relative_to(root)), node.lineno, alias.name))
            if isinstance(node, ast.Call):
                called = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else None
                )
                if called in ("PostAuthority", "Principal"):
                    violations.append((str(path.relative_to(root)), node.lineno, called))
    assert violations == []


@pytest.mark.parametrize(
    "operation", ("add", "edit", "close", "reopen", "confirm", "reply", "unclaim", "drop", "restore", "purge", "clear")
)
def test_all_pin_mutation_entries_refuse_raw_attribution(store_context, operation):
    """Every public mutation boundary refuses a forged actor before its transaction."""
    from limn.pins.editing.service import PinEditing
    from limn.pins.lifecycle.rules import CloseRequest
    from limn.pins.lifecycle.service import PinLifecycle
    from limn.pins.trash.service import PinTrash

    case = store_context
    pid = case.add()
    before = case.pins_bytes()
    lifecycle = PinLifecycle(lambda: case.ctx)
    editing = PinEditing(lambda: case.ctx)
    trash = PinTrash(lambda: case.ctx)
    calls = {
        "add": lambda: editing.add_pin(case.doc, object(), dict(ACTOR)),
        "edit": lambda: editing.edit_pin(pid, object(), dict(ACTOR)),
        "close": lambda: lifecycle.close_pin(pid, dict(ACTOR), CloseRequest()),
        "reopen": lambda: lifecycle.reopen_pin(pid, dict(ACTOR)),
        "confirm": lambda: lifecycle.confirm_pin(pid, dict(ACTOR)),
        "reply": lambda: lifecycle.reply_pin(pid, "reply", dict(ACTOR)),
        "unclaim": lambda: PinClaims(lambda: case.ctx).unclaim_pin(pid, dict(ACTOR)),
        "drop": lambda: trash.drop_pin(pid, dict(ACTOR)),
        "restore": lambda: trash.restore_pin(pid, dict(ACTOR)),
        "purge": lambda: trash.purge_pin(pid, dict(ACTOR)),
        "clear": lambda: trash.clear_pins(dict(ACTOR)),
    }
    with pytest.raises(HTTPError) as error:
        calls[operation]()
    assert error.value.body["reason"] == "invalid_authority"
    assert case.pins_bytes() == before


@pytest.mark.parametrize("operation", ("rebuild", "revision-build"))
@pytest.mark.parametrize("mismatch", ("actor", "instance", "target", "operation"))
def test_build_entry_refuses_unrelated_authority(operation, mismatch, tmp_path):
    """Job scheduling requires authority for this service and selected document."""
    from types import SimpleNamespace

    from limn.builds.service import BuildRequests
    from limn.revisions.service import RevisionRequests
    from limn.runtime.documents import Doc, RunPaths

    doc = Doc("main", "Main", paths=RunPaths(tmp_path, tmp_path / "main.tex", tmp_path / "state"), legacy=True)
    if operation == "rebuild":
        service = BuildRequests(
            lambda: SimpleNamespace(state=tmp_path), lambda: {}, lambda: [doc], lambda: "now", lambda: ""
        )
    else:
        context = SimpleNamespace(jobs=object(), cache=object())
        service = RevisionRequests(lambda: context)
    authority = post_authority(
        object() if mismatch == "instance" else service,
        ACTOR,
        "pick" if mismatch == "operation" else operation,
        Doc("main", "Other", paths=doc.paths, legacy=True) if mismatch == "target" else doc,
    )
    if mismatch == "actor":
        authority = dict(ACTOR)
    with pytest.raises(HTTPError) as error:
        if operation == "rebuild":
            service.rebuild_async(doc, authority)
        else:
            service.start(doc, "a" * 40, authority=authority)
    assert error.value.body["reason"] == "invalid_authority"


@pytest.fixture
def request_context():
    """Drive the real handler with an owner identity and isolated instance state."""
    from helpers_access import AccessBase

    case = AccessBase()
    case.setUp()
    case.set_people([{**ACTOR, "role": "owner"}])
    try:
        yield case
    finally:
        case.tearDown()


@pytest.mark.parametrize("kind", ("read", "document", "pin", "other"))
def test_new_registered_routes_cannot_execute(request_context, monkeypatch, kind):
    """New route registration alone cannot execute a handler, even for an owner."""
    from dataclasses import replace

    from limn.web.app import RouteRegistry
    from limn.web.routes import PostDocRoute

    from helpers import ps
    from helpers_access import ALICE

    case = request_context
    marker = ps.APP.C.state / "unexpected-effect"

    def effect(_request):
        """Expose any accidental dispatch as a persisted effect."""
        marker.write_text("executed")
        return {}

    path = "/api/future"
    method = "POST"
    routes = ps.Handler.app.routes.bundle
    if kind == "read":
        routes = replace(routes, get=(effect,))
        method = "GET"
    elif kind == "document":
        routes = replace(routes, post_documents=(*routes.post_documents, PostDocRoute(path, effect)))
    elif kind == "pin":
        path = "/api/pins/7/future"
        routes = replace(routes, pin_actions={**routes.pin_actions, "future": effect})
    else:
        routes = replace(routes, other_posts={**routes.other_posts, path: effect})
    monkeypatch.setattr(ps.Handler, "app", replace(ps.Handler.app, routes=RouteRegistry(routes)))
    code, body = case.call(method, path, headers=ALICE)
    assert (code, body["reason"]) == (404, "not_found")
    assert not marker.exists()


def test_issuer_refuses_an_unserved_document_with_the_same_key(request_context):
    """The composition root cannot authorize a replacement resource selected by its key alone."""
    from limn.runtime.documents import Doc

    from helpers import ps

    selected = ps.APP.docs[0]
    other = Doc(selected.key, "Other", paths=selected.paths)
    principal = access.Principal(dict(ACTOR), "owner", "header")
    with pytest.raises(HTTPError) as error:
        ps.APP.authorize_post(principal, "/api/rebuild", other)
    assert error.value.body["reason"] == "invalid_authority"


@pytest.mark.parametrize("changed", ("document_paths", "document_key", "build_state", "revision_resources"))
def test_authority_refuses_resources_changed_after_issuance(tmp_path, changed):
    """Previously issued requests cannot follow mutable resources into a different namespace."""
    from types import SimpleNamespace

    from limn.builds.service import BuildRequests
    from limn.revisions.service import RevisionRequests
    from limn.runtime.documents import Doc, RunPaths

    original = RunPaths(tmp_path, tmp_path / "main.tex", tmp_path / "state")
    doc = Doc("main", "Main", paths=original, legacy=True)
    settings = SimpleNamespace(state=original.state)
    context = SimpleNamespace(jobs=object(), cache=object())
    if changed == "revision_resources":
        service = RevisionRequests(lambda: context)
        authority = post_authority(service, ACTOR, "revision-build", doc)
        context.jobs = object()
    else:
        service = BuildRequests(lambda: settings, lambda: {}, lambda: [doc], lambda: "now", lambda: "")
        authority = post_authority(service, ACTOR, "rebuild", doc)
        if changed == "document_paths":
            doc.paths = RunPaths(tmp_path / "other", tmp_path / "other/main.tex", original.state)
        elif changed == "document_key":
            doc.key = "other"
        else:
            settings.state = tmp_path / "other-state"
    with pytest.raises(HTTPError) as error:
        if changed == "revision_resources":
            service.start(doc, "a" * 40, authority=authority)
        else:
            service.rebuild_async(doc, authority)
    assert error.value.body["reason"] == "invalid_authority"


@pytest.mark.parametrize("resource", ("jobs", "cache"))
def test_revision_authority_compares_resource_identity_not_equality(tmp_path, resource):
    """Equal-looking replacement resources cannot inherit a previous request's authority."""
    from types import SimpleNamespace

    from limn.revisions.service import RevisionRequests
    from limn.runtime.documents import Doc, RunPaths

    doc = Doc("main", "Main", paths=RunPaths(tmp_path, tmp_path / "main.tex", tmp_path / "state"), legacy=True)
    context = SimpleNamespace(jobs=SimpleNamespace(slots=2), cache=SimpleNamespace(slots=2))
    service = RevisionRequests(lambda: context)
    authority = post_authority(service, ACTOR, "revision-build", doc)
    original = getattr(context, resource)
    replacement = SimpleNamespace(slots=2)
    assert replacement == original and replacement is not original
    setattr(context, resource, replacement)
    with pytest.raises(HTTPError) as error:
        service.start(doc, "a" * 40, authority=authority)
    assert error.value.body["reason"] == "invalid_authority"


def test_unknown_document_does_not_record_the_person(request_context):
    """Document selection fails before person persistence or mutation authority is issued."""
    from helpers import ps
    from helpers_access import BOB

    before = ps.APP.C.people_file.read_bytes()
    code, body = request_context.call("POST", "/api/pin?doc=unknown", {}, BOB)
    assert (code, body["reason"]) == (404, "unknown_doc")
    assert ps.APP.C.people_file.read_bytes() == before


def undeclared_posts(bundle):
    """The POST entry points of a route bundle that the access table does not declare as an operation.

    A declared operation is one access.post_operation names, which is what check_role and authorize_post decide on; a
    registered route outside that table could only ever answer 404, so it is a registration nobody authorized.
    """
    paths = [route.path for route in bundle.post_documents]
    paths += ["/api/pins/7/%s" % name for name in bundle.pin_actions]
    paths += list(bundle.other_posts)
    undeclared = []
    for path in paths:
        try:
            access.post_operation(path)
        except HTTPError:
            undeclared.append(path)
    return undeclared


def test_every_registered_post_declares_an_operation(request_context):
    """Each POST the running application registers has an authorization decision in the access table.

    GET handlers are closures that declare no path, so they cannot be listed here; check_read's path table and
    test_new_registered_routes_cannot_execute cover them instead.
    """
    from helpers import ps

    bundle = ps.Handler.app.routes.bundle
    assert bundle.post_documents and bundle.pin_actions and bundle.other_posts
    assert undeclared_posts(bundle) == []


def test_undeclared_post_registrations_are_listed(request_context):
    """A document, pin and exact-path POST registered without a declared operation is each reported."""
    from dataclasses import replace

    from limn.web.routes import PostDocRoute

    from helpers import ps

    bundle = ps.Handler.app.routes.bundle
    added = replace(
        bundle,
        post_documents=(*bundle.post_documents, PostDocRoute("/api/future", lambda _request: {})),
        pin_actions={**bundle.pin_actions, "future": lambda _request: {}},
        other_posts={**bundle.other_posts, "/api/also-future": lambda _request: {}},
    )
    assert undeclared_posts(added) == ["/api/future", "/api/pins/7/future", "/api/also-future"]
