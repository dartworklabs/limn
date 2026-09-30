"""Audited token issuance and revocation for the `limn token` command.

The request authentication boundary reads tokens through limn.security.access. This module owns
CLI writes under the tokens store lock and never persists or audits a plaintext token.
"""

import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from limn.administration.targets import AuditSink
from limn.platform.files import atomic_write, store_lock
from limn.security.access import Json, load_tokens, token_hash

TOKEN_PREFIX = "limn_"
TOKEN_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")


def _write_tokens(state: Path, rows: list[Json]) -> None:
    """Replace <state>/tokens.json with rows (atomically, mode 0600)."""
    atomic_write(
        Path(state) / "tokens.json",
        json.dumps({"version": 1, "tokens": rows}, ensure_ascii=False, indent=1) + "\n",
        mode=0o600,
    )


def now_str() -> str:
    """The local wall-clock time as every *_at / created field records it ('YYYY-MM-DD HH:MM:SS')."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def token_create(state: Path, name: str | None, audit: AuditSink) -> tuple[Json, str]:
    """Creates a token -> (entry, plaintext). Only the hash is stored; the plaintext is returned once and never again.
    Records `token_created` {id, name} through audit - never the token or its hash. Raises ValueError for a bad or
    taken name, or an unreadable tokens.json (nothing is written then)."""
    state = Path(state)
    if name is not None and not TOKEN_NAME_RE.fullmatch(name):
        raise ValueError("token name must match [A-Za-z0-9][A-Za-z0-9._-]{0,39}: %r" % name)
    state.mkdir(parents=True, exist_ok=True)
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        names = {t["name"] for t in rows}
        if name is None:
            name, n = "agent", 1
            while name in names:
                n += 1
                name = "agent-%d" % n
        elif name in names:
            raise ValueError("a token named %r already exists (revoke it first, or pick another --name)" % name)
        ids = {t["id"] for t in rows}
        tid = secrets.token_hex(4)
        while tid in ids:
            tid = secrets.token_hex(4)
        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        entry = {"id": tid, "name": name, "hash": token_hash(plain), "created": now_str()}
        _write_tokens(state, rows + [entry])
        audit("token_created", {"id": tid, "name": name})
    return entry, plain


def token_revoke(state: Path, ref: str, audit: AuditSink) -> Json | None:
    """Removes the token whose id or name is ref -> the removed entry, or None if there is none. A removal records
    `token_revoked` {id, name} through audit; None writes nothing."""
    state = Path(state)
    if not (state / "tokens.json").exists():
        return None
    with store_lock(state, "tokens"):
        rows = load_tokens(state, strict=True)
        hit = [t for t in rows if t["id"] == ref] or [t for t in rows if t["name"] == ref]
        if not hit:
            return None
        _write_tokens(state, [t for t in rows if t is not hit[0]])
        audit("token_revoked", {"id": hit[0]["id"], "name": hit[0]["name"]})
    return hit[0]
