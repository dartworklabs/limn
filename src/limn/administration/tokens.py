"""The `limn token` command and saved-token transaction."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from limn.administration import token_files, token_state
from limn.administration.targets import CliError, cli_audit, split_target


def create_saved_token(state: Path, ns: argparse.Namespace) -> int:
    """`limn token create <instance> --save`: check the target, create the token, write it to the token file.

    Every check runs before the token exists, and a failed write revokes the new token again, so a failure never
    leaves a valid token nobody holds. The token is printed only with --print."""
    from limn.security import access

    if ns.instance is None:
        raise CliError(
            "--save needs an instance name: the token file is <config dir>/<instance>.token "
            "(see limn token path <instance>)"
        )
    path = token_files.token_file_path(ns.instance)
    previous = token_files.read_token_file(path) if ns.force else None
    refusal = token_files.save_refusal(token_files.inspect_save_target(path), path, ns.force)
    if refusal:
        raise CliError(refusal)
    entry, plain = token_state.token_create(state, ns.name, cli_audit(state))
    try:
        token_files.write_token_file(path, plain, replace=ns.force)
    except OSError as e:
        try:
            token_state.token_revoke(state, entry["id"], cli_audit(state))
        except (OSError, ValueError) as undo:
            raise CliError(
                "could not write %s: %s - and could not revoke the new token (%s), so it is still valid; "
                "revoke it: limn token revoke %s %s" % (path, e, undo, ns.instance, entry["id"])
            ) from e
        raise CliError("could not write %s: %s - the new token %s was revoked again" % (path, e, entry["id"])) from e
    if ns.print:
        print(plain)
        sys.stdout.flush()
    print(
        "limn: created token %s (name %s) in %s" % (entry["id"], entry["name"], state / "tokens.json"), file=sys.stderr
    )
    print(
        "limn: saved it to %s (mode 0600)%s. Agents on this machine send it with\n"
        '        curl -H "Authorization: Bearer $(cat %s)" <base>/pins.md\n'
        "      A running server accepts it on the next request." % (path, "" if ns.print else ", not printed", path),
        file=sys.stderr,
    )
    if previous:
        old = [t for t in access.load_tokens(state) if t["hash"] == access.token_hash(previous)]
        if old:
            print(
                "limn: the token that was in the file (id %s, name %s) is still valid - revoke it if nothing else "
                "uses it: limn token revoke %s %s" % (old[0]["id"], old[0]["name"], ns.instance, old[0]["id"]),
                file=sys.stderr,
            )
    return 0


def cmd_token(argv: Sequence[str]) -> int:
    """`limn token create|path|list|revoke ...` -> exit status.

    Edit <state>/tokens.json through token_state, with cli_audit, and an instance's
    token file as specified by ADR-0007. Refusals raise CliError for main() to print.
    """
    sub = argv[0] if argv else ""
    rest = argv[1:]
    from limn.security import access

    if sub == "create":
        state, _, ns = split_target(
            "limn token create",
            rest,
            0,
            [
                (("--name",), {"help": "token name (default agent, agent-2, ...)"}),
                (
                    ("--save",),
                    {
                        "action": "store_true",
                        "help": "write the token to the instance's token file (limn token path) instead of printing it",
                    },
                ),
                (("--force",), {"action": "store_true", "help": "with --save: replace an existing token file"}),
                (("--print",), {"action": "store_true", "help": "with --save: print the token as well"}),
            ],
        )
        if ns.save:
            return create_saved_token(state, ns)
        if ns.force or ns.print:
            raise CliError("--force and --print only go with --save")
        entry, plain = token_state.token_create(state, ns.name, cli_audit(state))
        print(plain)
        sys.stdout.flush()
        print(
            "limn: created token %s (name %s) in %s" % (entry["id"], entry["name"], state / "tokens.json"),
            file=sys.stderr,
        )
        print(
            "limn: this is the only time the token is shown; only its hash is stored. Give it to the agent, e.g.\n"
            "        export LIMN_TOKEN=<the token above>\n"
            '        curl -s -H "Authorization: Bearer $LIMN_TOKEN" <base>/pins.md\n'
            "      A running server accepts it on the next request.",
            file=sys.stderr,
        )
        return 0
    if sub == "path":
        ap = argparse.ArgumentParser(
            prog="limn token path", description="Print the token file agents on this machine read (it is not read here)"
        )
        ap.add_argument("instance")
        print(token_files.token_file_path(ap.parse_args(rest).instance))
        return 0
    if sub == "list":
        state, _, ns = split_target("limn token list", rest, 0)
        rows = access.load_tokens(state, strict=True)
        if not rows:
            print("no tokens in %s" % state)
            return 0
        print("%-10s %-24s %s" % ("ID", "NAME", "CREATED"))
        for t in rows:
            print("%-10s %-24s %s" % (t["id"], t["name"], t.get("created", "")))
        saved = token_files.read_token_file(token_files.token_file_path(ns.instance)) if ns.instance else None
        held = [t for t in rows if saved is not None and t["hash"] == access.token_hash(saved)]
        if held:
            print(
                "token file %s holds %s (name %s)"
                % (token_files.token_file_path(ns.instance), held[0]["id"], held[0]["name"])
            )
        return 0
    if sub in ("revoke", "rm"):
        state, pos, ns = split_target("limn token revoke", rest, 1)
        revoked = token_state.token_revoke(state, pos[0], cli_audit(state))
        if revoked is None:
            raise CliError("no token with id or name %r in %s" % (pos[0], state))
        print(
            "revoked token %s (name %s) — the running server refuses it from the next request"
            % (revoked["id"], revoked["name"])
        )
        note = (
            token_files.forget_saved_token(token_files.token_file_path(ns.instance), revoked, access.token_hash)
            if ns.instance
            else None
        )
        if note:
            print(note)
        return 0
    raise CliError("limn token create|path|list|revoke <instance> ... (unknown subcommand: '%s')" % sub)
