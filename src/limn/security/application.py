"""Request-boundary security assembled from explicit run facts."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from email.message import Message
from typing import Any

from limn.runtime.config import RunConfig
from limn.runtime.documents import Doc, document_authority_target
from limn.runtime.resources import RuntimeResources
from limn.security import access, people
from limn.security.access import AuthorityScope
from limn.security.audit import AuditAction, append_audit, audit_entry
from limn.web.errors import HTTPError


@dataclass(frozen=True)
class RequestGuards:
    """Identity, admission and route authorization at the HTTP boundary."""

    settings: Callable[[], RunConfig]
    lookups: Callable[[], access.AccessLookups]
    roles: Callable[[], access.PeopleRoles]
    documents: Callable[[], Sequence[Doc]]
    authority_scope: Callable[[str], AuthorityScope]
    trash_days: int

    @property
    def config(self) -> RunConfig:
        """Read current run settings at the request boundary."""
        return self.settings()

    def host_ok(self, host: str) -> bool:
        """Return whether ``Host`` is admitted by this run."""
        return access.host_ok(host, self.config.access.public_hosts)

    def origin_ok(self, origin: str, host: str | None) -> bool:
        """Return whether ``Origin`` is on the admitted side of ``Host``."""
        return access.origin_ok(origin, host, self.config.access.public_hosts)

    def identify(self, headers: Message, peer: str) -> access.Principal:
        """Identify one request from headers, peer and current file-backed facts."""
        return access.identify(headers, peer, self.config.access_settings, self.lookups())

    def admit(self, principal: access.Principal, host: str | None, headers: Message | None = None) -> None:
        """Apply membership and provider admission rules."""
        access.admit(principal, host, headers, self.config.access_settings, self.roles)

    def check_role(self, principal: access.Principal, path: str) -> None:
        """Apply the role rule for a mutation path."""
        access.check_role(principal, path, self.trash_days)

    def authorize_post(self, principal: access.Principal, path: str, doc: Doc | None = None) -> access.PostAuthority:
        """Bind an admitted mutation to its service resources and optional document."""
        operation, _ = access.post_operation(path)
        if doc is not None and not any(doc is served for served in self.documents()):
            raise HTTPError(403, "요청 권한이 올바르지 않습니다.", reason="invalid_authority")
        return access._authorize_post(
            principal,
            path,
            self.authority_scope(operation),
            None if doc is None else document_authority_target(doc),
            self.trash_days,
        )

    def check_read(self, path: str) -> None:
        """Reject a read path absent from the declared access table."""
        access.check_read(path)


@dataclass(frozen=True)
class SecurityApplication:
    """Current file-backed identity facts and audit persistence for one run."""

    settings: Callable[[], RunConfig]
    resources: Callable[[], RuntimeResources[object, object, object, object, object, object]]
    load_people: Callable[[], list[people.Row] | people.PeopleUnreadable]

    def current_tokens(self) -> list[dict[str, Any]]:
        """Refresh token facts whenever the file signature changes."""
        config = self.settings()
        return self.resources().tokens_cache.get(config.tokens_file, lambda: access.load_tokens(config.state), [])

    def people_roles(self) -> access.PeopleRoles:
        """Refresh role facts fail-closed after people-file edits or repairs."""
        return self.resources().roles_cache.get(
            self.settings().people_file, lambda: access.people_roles_of(self.load_people()), {}
        )

    def role_of(self, login: str) -> access.Role:
        """Return the current role of one person, including unreadable-file policy."""
        return access.person_role(self.people_roles(), login)

    def access_lookups(self) -> access.AccessLookups:
        """Provide identity with current token and role reads and this run's warning memo."""
        return access.AccessLookups(self.current_tokens, self.people_roles, self.resources().loopback_warning)

    def http_audit(self, action: AuditAction, by: dict[str, Any], details: dict[str, Any]) -> bool:
        """Append one audit entry outside the pin transaction lock."""
        return append_audit(self.settings().state, audit_entry(action, by, "http", details, time.time()))

    def guards(
        self,
        docs: Callable[[], Sequence[Doc]],
        authority_scope: Callable[[str], AuthorityScope],
        trash_days: int,
    ) -> RequestGuards:
        """Assemble guards from current security facts and effect-owner bindings."""
        return RequestGuards(self.settings, self.access_lookups, self.people_roles, docs, authority_scope, trash_days)
