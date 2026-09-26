"""How an agent on this machine authenticates: the texts that name the instance's token file (ADR-0007).

Two places say it: the 401 for a headerless local request when the loopback agent is off (limn.access.identify) and
the agent-auth line of pins.md. Both must name the file the same way, so the wording lives here once. Pure: strings
and paths in, strings out - whether the file exists and where home is are read by the caller (limn.access.file_present,
home_or_none) and passed in. Nothing here touches the file system; tests/test_access_module.py checks the imports.
"""
from __future__ import annotations

import re
import shlex
from pathlib import PurePath

UNAUTHENTICATED = "신원을 확인할 수 없습니다 — 에이전트는 `Authorization: Bearer <토큰>` 을 보내세요(`limn token create <인스턴스>`)."
TOKEN_FILE_EXAMPLE = "~/.config/limn/<인스턴스>.token"   # the convention, shown when this server does not know its own file


def shell_path(path: PurePath, home: PurePath | None) -> str:
    """path as one word an agent's shell on this machine reads back: `~/<rest>` when it is under home and the rest has
    only plain characters (the tilde still expands inside `$(cat ...)`), else the absolute path, shell-quoted."""
    if home is not None:
        try:
            rest = path.relative_to(home)
        except ValueError:
            rest = None
        if rest is not None and re.fullmatch(r"[A-Za-z0-9._/-]+", str(rest)):
            return "~/%s" % rest
    return shlex.quote(str(path))


def token_file_curl(shown: str) -> str:
    """The curl form an agent on this machine uses with the instance's token file (ADR-0007): the shell reads the
    file at call time, so the text names the file and never carries the token."""
    return "`curl -H \"Authorization: Bearer $(cat %s)\" …`" % shown


def loopback_refused_text(token_file: PurePath | None, exists: bool, home: PurePath | None) -> str:
    """The 401 text for a headerless request from this machine when the loopback agent is off (--no-agent-loopback,
    AGENT_LOOPBACK=0). The v0.2 text comes first, unchanged; then where this machine's agents get their token: the
    instance's token file when the server knows it (token_file, and whether it exists), else the convention.
    Pure: the caller stats the file and passes the home folder."""
    shown = shell_path(token_file, home) if token_file is not None else TOKEN_FILE_EXAMPLE
    text = ("%s 이 인스턴스는 헤더 없는 로컬 요청을 받지 않습니다(AGENT_LOOPBACK=0). 이 기기의 에이전트는 토큰 파일을 "
            "붙이세요: %s" % (UNAUTHENTICATED, token_file_curl(shown)))
    if not exists:
        name = token_file.stem if token_file is not None and token_file.suffix == ".token" else "<인스턴스>"
        text += " 파일이 없으면 소유자가 `limn token create %s --save` 로 만듭니다." % name
    return text
