"""How every git process Limn starts is run (docs/handbook/build-sync.md §git 프로세스).

A git call must never wait for a person and never act on a repository other than the one it names. So each git
process gets:

- an argument list, never a shell string, and a timeout the caller must choose;
- no stdin (/dev/null) and a new session, so it has no controlling terminal: neither git nor the ssh it runs for a
  fetch can open /dev/tty to ask for a password, a passphrase or a host key;
- GIT_TERMINAL_PROMPT=0, so git fails at once where it would have asked for HTTPS credentials;
- the server's environment without its GIT_* variables. GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
  GIT_CONFIG_* and the rest would point git at another repository or add configuration the manuscript does not have,
  and GIT_ASKPASS would start a prompt. Kept are the ssh transport settings (GIT_SSH_COMMAND, GIT_SSH,
  GIT_SSH_VARIANT): the systemd unit sets GIT_SSH_COMMAND to make ssh fail instead of prompting, and an operator may
  name a deploy key there. Everything else - HOME, PATH, SSH_AUTH_SOCK, the locale, proxy settings - passes unchanged.

run_git() is the one call for commands whose whole output is read; open_git() starts one whose output is streamed;
git_command() and git_env() are for limn.features.revisions.core' bounded reader, which runs git and the comparison-build sandbox
through the same pipe loop. Credential helpers configured in git keep working; only prompts are off.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

GIT_TIMEOUT = 30  # seconds - one git call (a history read, a diff, a --git-pull fetch)

# GIT_* variables of the server's environment that reach git: the ssh transport the operator chose.
KEPT_GIT_VARS = frozenset({"GIT_SSH_COMMAND", "GIT_SSH", "GIT_SSH_VARIANT"})


def git_env(environ: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment of a git process: environ (default os.environ) without GIT_* variables other than
    KEPT_GIT_VARS, with GIT_TERMINAL_PROMPT=0, then extra (e.g. LC_ALL=C for a caller that reads git's messages)."""
    source = os.environ if environ is None else environ
    env = {k: v for k, v in source.items() if not k.startswith("GIT_") or k in KEPT_GIT_VARS}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra or {})
    return env


def git_command(args: Sequence[str]) -> list[str]:
    """["git", *args]. Raises TypeError for a single string: a command line is a list, never parsed by a shell or
    split on spaces (a str is a Sequence[str] of its characters, so the type alone does not stop it)."""
    if isinstance(args, str):
        raise TypeError("git arguments are a list, not a string: %r" % args)
    return ["git", *args]


def run_git(
    args: Sequence[str], cwd: Path | str, timeout: float, extra_env: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run `git <args>` in cwd and wait at most timeout seconds; stdout and stderr are captured as text. The exit
    status is the caller's to read (never raises for it). Raises subprocess.TimeoutExpired (git is killed) and OSError
    (git missing, cwd missing), as subprocess.run does."""
    return subprocess.run(
        git_command(args),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        env=git_env(extra=extra_env),
        timeout=timeout,
        start_new_session=True,
        check=False,
    )


def git(args: Sequence[str], cwd: Path | str, timeout: float = GIT_TIMEOUT) -> tuple[int | None, str, str]:
    """Run trusted Git arguments without a shell or prompt and return (returncode, stdout, stderr).

    Preserve output for any exit status; normalize timeout and startup failure to (None, "", "").
    Callers own argument construction and repository scope; invalid argument types still raise TypeError.
    """
    try:
        r = run_git(args, cwd, timeout)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, OSError):
        return None, "", ""


def open_git(args: Sequence[str], cwd: Path | str) -> subprocess.Popen[bytes]:
    """Start `git <args>` in cwd with stdout as a byte pipe and stderr discarded, for a caller that reads the output
    itself and bounds its size and time (it owns the process: read, then wait or kill). Raises OSError when git cannot
    start."""
    return subprocess.Popen(
        git_command(args),
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=git_env(),
        start_new_session=True,
    )
