"""Token file placement, Git work tree refusal and atomic file writes."""

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

from limn.features.administration.targets import check_instance_name, config_dir
from limn.gitrun import run_git

TOKEN_LINE_RE = re.compile(r"limn_[A-Za-z0-9_-]+")


def token_file_path(name: str) -> Path:
    """Where agents on this machine read instance <name>'s token: <config dir>/<name>.token, next to <name>.env.

    Never the LIMN_SOURCE_DIR copy of the config - that folder is often a dotfiles repository, and a token file must
    not land in one. instances.sh's token_file_of gives the same path."""
    check_instance_name(name)
    return config_dir() / ("%s.token" % name)


class SaveTarget(NamedTuple):
    """What is at a token file path before `limn token create --save` writes it (gathered by inspect_save_target)."""

    occupied: bool  # something is already at the path - a dangling symlink too
    repo: str | None  # the git work tree that would hold the file without ignoring it; None if there is none
    unknown: str | None = None  # why git could not tell whether a work tree holds it; None when it could


def save_refusal(target: SaveTarget, path: Path, force: bool) -> str | None:
    """Why --save must not write the token file at path, or None when it may. A work tree that would hold the file
    refuses even with --force (a token never goes into a repository), and so does not being able to tell; an existing
    file needs --force."""
    if target.unknown:
        return (
            "could not tell whether %s is inside a git work tree (%s) - a token file never goes into a repository. "
            "Fix git, or set LIMN_CONFIG_DIR to a folder outside any repository" % (path.parent, target.unknown)
        )
    if target.repo:
        return (
            "%s would be inside the git work tree %s, which does not ignore it - a token file never goes into a "
            "repository. Ignore it there (e.g. '*.token' in its .gitignore) or set LIMN_CONFIG_DIR to a folder "
            "outside any repository" % (path, target.repo)
        )
    if target.occupied and not force:
        return (
            "%s already exists - pass --force to replace it (the token in it stays valid until you revoke it: "
            "limn token list, limn token revoke)" % path
        )
    return None


def git_tree_holding(path: Path) -> tuple[str | None, str | None]:
    """(work tree, None) when a git work tree holds path's folder and does not ignore path; (None, None) when none
    does, git is not installed, or it is macOS's stub without developer tools; (None, why) when git fails otherwise
    (dubious ownership, a broken repository), so the caller can refuse rather than guess.

    Symlinks are resolved first, so a config folder linked into a repository is judged by that repository. The folder
    may not exist yet: its nearest existing parent is asked. git runs through limn.gitrun, which drops the caller's
    GIT_* variables (GIT_DIR, GIT_WORK_TREE would point git at another repository) and never prompts; messages are
    read in the C locale."""
    if not shutil.which("git"):
        return None, None
    folder = path.parent
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    real = folder.resolve() / path.parent.relative_to(folder) / path.name

    def git_in(*args: str) -> subprocess.CompletedProcess[str]:
        """One git command in the resolved folder (limn.gitrun.run_git, LC_ALL=C); never raises on git's status."""
        return run_git(["-C", str(folder.resolve()), *args], folder.resolve(), 30, extra_env={"LC_ALL": "C"})

    top = git_in("rev-parse", "--show-toplevel")
    if top.returncode != 0:
        err = top.stderr.strip()
        if "not a git repository" in err or "xcode-select" in err or "developer tools" in err.lower():
            return None, None
        return None, (err.splitlines() or ["git rev-parse failed"])[-1]
    ignored = git_in("check-ignore", "-q", str(real))
    if ignored.returncode == 0:
        return None, None
    if ignored.returncode == 1:
        return top.stdout.strip(), None
    return None, (ignored.stderr.strip().splitlines() or ["git check-ignore failed"])[-1]


def inspect_save_target(path: Path) -> SaveTarget:
    """The facts save_refusal() decides on, read from the file system and git."""
    repo, unknown = git_tree_holding(path)
    return SaveTarget(occupied=os.path.lexists(path), repo=repo, unknown=unknown)


def write_token_file(path: Path, token: str, replace: bool) -> None:
    """Write token as the only line of path, mode 0600; a missing folder is created with mode 0700.

    Without replace the file must not exist: O_EXCL never follows a symlink and fails if another writer got there
    first (FileExistsError). With replace the new file is swapped in atomically (a 0600 temp file in the same folder,
    then os.replace, which replaces a symlink itself and never writes through it). A half-written new file or temp
    file - both hold the token - is removed. Raises OSError."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = token + "\n"
    if replace:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".%s." % path.name)
        try:
            with os.fdopen(fd, "w", encoding="ascii") as fh:
                os.fchmod(fh.fileno(), 0o600)
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, data.encode("ascii"))
        os.fsync(fd)
    except OSError:
        os.close(fd)
        path.unlink()
        raise
    os.close(fd)


def read_token_file(path: Path) -> str | None:
    """The token a token file holds, or None: no regular file there (a symlink is not followed), unreadable, or not
    one token line."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text if TOKEN_LINE_RE.fullmatch(text) else None


def forget_saved_token(path: Path, revoked: Mapping[str, Any], token_hash: Callable[[str], str]) -> str | None:
    """After a revoke: remove the token file if it held the revoked token (an agent would only get 401 from it) and
    say so; say that a file holding another token, or one it cannot read, was kept; None when there is no token file."""
    if not os.path.lexists(path):
        return None
    saved = read_token_file(path)
    if saved is None:
        return "kept %s - could not read one token from it (unreadable, a symlink, or not one token line)" % path
    if token_hash(saved) == revoked["hash"]:
        path.unlink()
        return "removed %s (it held this token)" % path
    return "kept %s - it holds another token" % path
