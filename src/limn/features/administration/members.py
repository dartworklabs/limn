"""The `limn member` command."""

from collections.abc import Sequence

from limn.features.administration.targets import CliError, cli_audit, split_target


def cmd_member(argv: Sequence[str]) -> int:
    """`limn member add|list|remove|role ...` -> exit status. Edits <state>/people.json through the state helpers in
    limn.access, in limn.people's people.json format and with cli_audit's audit sink; a running server
    applies the change from its next request. A missing member or an unknown subcommand raises CliError; an invalid
    login or role, an existing member, or an unreadable people.json raises ValueError from the store helpers; main()
    prints both."""
    sub = argv[0] if argv else ""
    rest = argv[1:]
    from limn import access

    note = "the running server applies it from the next request"
    if sub == "add":
        state, pos, ns = split_target(
            "limn member add",
            rest,
            1,
            [
                (
                    ("--role",),
                    {"default": access.DEFAULT_ROLE, "choices": access.ROLES, "help": "role (default editor)"},
                ),
                (("--name",), {"help": "display name (default: the part of the login before @)"}),
            ],
        )
        e = access.member_add(state, pos[0], ns.role, ns.name, cli_audit(state))
        print("added %s as %s (%s) — %s" % (e["login"], e["role"], e["name"], note))
        return 0
    if sub in ("list", "ls"):
        state, _, _ = split_target("limn member list", rest, 0)
        rows = access.load_people_file(state)
        if not rows:
            print("no members in %s" % state)
            return 0
        print("%-32s %-7s %-24s %s" % ("LOGIN", "ROLE", "NAME", "LAST SEEN"))
        for x in rows:
            role = access.role_value(x.get("role"))
            print(
                "%-32s %-7s %-24s %s"
                % (x["login"], role + ("" if "role" in x else "*"), x.get("name") or "", x.get("last_seen") or "-")
            )
        if any("role" not in x for x in rows):
            print("* no role recorded — editor by default (set one with `limn member role <instance> <login> <role>`)")
        return 0
    if sub in ("remove", "rm"):
        state, pos, _ = split_target("limn member remove", rest, 1)
        if access.member_remove(state, pos[0], cli_audit(state)) is None:
            raise CliError("%s is not in %s" % (pos[0], state / "people.json"))
        print("removed %s — %s" % (pos[0], note))
        return 0
    if sub == "role":
        state, pos, _ = split_target("limn member role", rest, 2)
        changed = access.member_set_role(state, pos[0], pos[1], cli_audit(state))
        if changed is None:
            raise CliError("%s is not in %s (add it with `limn member add`)" % (pos[0], state / "people.json"))
        print("%s is now %s — %s" % (changed["login"], changed["role"], note))
        return 0
    raise CliError("limn member add|list|remove|role <instance> ... (unknown subcommand: '%s')" % sub)
