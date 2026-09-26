"""The `limn serve` command line: every option, its default and its help text.

The parser is the CLI's contract (`limn serve --help`, the flags instances.sh passes, the error for a bad value), so it
changes when an option is added or reworded - not when a startup rule changes (those are limn/startup.py's). What
depends on the server - its one-line description, its version string and the default --float-envs - is passed in by
the composition root (server.build_arg_parser). Building the parser reads one environment variable,
LIMN_AGENT_TOKEN_FILE (the default of --agent-token-file), and nothing else.
"""
from __future__ import annotations

import argparse
import os

from limn.access import AUTH_PROVIDERS
from limn.startup import LABEL_MAX


def serve_parser(description: str, version: str, default_envs: str) -> argparse.ArgumentParser:
    """The `limn serve` argument parser: description is the help's first line, version what --version prints,
    default_envs the --float-envs default. Defaults that come from the environment (LIMN_AGENT_TOKEN_FILE) are read
    here, i.e. when the parser is built at startup."""
    ap = argparse.ArgumentParser(prog="limn serve", description=description)
    ap.add_argument("--version", action="version", version=version)
    ap.add_argument("--manuscript", required=True, help="LaTeX source root directory")
    ap.add_argument("--main", help="Top-level .tex filename (auto-detected if omitted). Not used together with --doc")
    ap.add_argument("--doc", action="append", default=[], metavar="KEY=NAME:PATH",
                    help="A document the viewer can switch to (repeatable). PATH is relative to --manuscript. "
                         ".tex = LaTeX (build root is that folder), "
                         "<build root>::<main.tex> = build root given separately, .pdf = view-only. The first document is the default. "
                         "If omitted, a single document (key main) built from --manuscript/--main")
    ap.add_argument("--port", type=int, help="Picks a free port in 18300-18400 if omitted")
    ap.add_argument("--state-dir", help="Location of pins and build artifacts")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--float-envs", default=default_envs)
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--no-build", action="store_true", help="Don't rebuild on startup")
    ap.add_argument("--allow", default="",
                    help="Allowed logins (comma-separated). Everyone is allowed if empty. A loopback "
                         "request with no identity header (curl/agent) is always allowed; a request to *.ts.net with no "
                         "identity header (a tag device) is denied (with or without this option, unless --tailnet-agent)")
    ap.add_argument("--no-origin-check", action="store_true",
                    help="Turns off Host/Origin checking (DNS rebinding/CSRF defense). Use only when tailscale "
                         "serve passes an unexpected Host/Origin and the UI gets a 403")
    ap.add_argument("--git-pull", action="store_true",
                    help="Checks remote main right after startup and every 60 seconds, rebuilding the PDF on a "
                         "new commit. A manual rebuild also does an --ff-only pull of upstream before the copy. Skipped with a screen notice if there are local changes or a divergence")
    ap.add_argument("--pdfjs-dir",
                    help="The PDF.js directory the viewer uses for vector rendering (pdf.min.mjs/pdf.worker.min.mjs). "
                         "Defaults to the limn/vendor/pdfjs bundled with the package. Falls back to PNG in the viewer if absent")
    ap.add_argument("--label",
                    help="A label distinguishing tabs/the tool bar when multiple manuscript viewers are open at once "
                         "(%d characters or fewer). Defaults to --manuscript's git origin repo name, or the folder name if not a git repo" % LABEL_MAX)
    ap.add_argument("--accent",
                    help="The label's accent color (#rrggbb). If omitted, one is picked from a fixed palette by "
                         "hashing the label string (the same label always gets the same color)")
    acc = ap.add_argument_group("access control (docs/adr/0002-access-control.md)")
    acc.add_argument("--auth", choices=AUTH_PROVIDERS,
                     help="Identity provider. tailscale (default): Tailscale-User-* headers from a loopback peer "
                          "(tailscale serve). local: a single user on this machine - every loopback request is the "
                          "owner; agents use a token. trusted-proxy: identity headers set by an authenticating reverse "
                          "proxy, trusted only from --trusted-proxies. Every provider accepts 'Authorization: Bearer "
                          "<token>' (limn token create)")
    lb = acc.add_mutually_exclusive_group()
    lb.add_argument("--no-agent-loopback", dest="agent_loopback", action="store_const", const=False, default=None,
                    help="Refuse (401) loopback requests with no identity header or token instead of treating them "
                         "as the agent (the deprecated v0.1 behaviour, on by default under --auth tailscale)")
    lb.add_argument("--agent-loopback", dest="agent_loopback", action="store_const", const=True,
                    help="Explicitly keep the deprecated headerless loopback agent. Refuses to start where it cannot "
                         "apply (--auth local or trusted-proxy, or a non-loopback --bind)")
    acc.add_argument("--tailnet-agent", action="store_true",
                     help="Also treat a headerless request that arrives through tailscale serve (Host *.ts.net or a "
                          "--public-host, e.g. from a tagged device) as the agent, as v0.2.0 did. Off by default: such "
                          "requests get 403 and remote agents use a token. Needs the loopback agent (deprecated)")
    acc.add_argument("--bind", default="127.0.0.1",
                     help="Listen address (default 127.0.0.1). A non-loopback address needs --auth trusted-proxy or "
                          "--i-know-this-is-insecure")
    acc.add_argument("--i-know-this-is-insecure", action="store_true",
                     help="Allow a non-loopback --bind without --auth trusted-proxy (prints a loud warning)")
    acc.add_argument("--public-host", action="append", default=[], metavar="NAME[:PORT]",
                     help="A public host name the server is reached under (repeatable or comma-separated): accepted as "
                          "Host and as https Origin (port 443 unless given), and used as the pins.md base URL")
    acc.add_argument("--trusted-proxies", default="127.0.0.1,::1", metavar="IP/CIDR,...",
                     help="Peers whose identity headers --auth trusted-proxy trusts (default 127.0.0.1,::1)")
    acc.add_argument("--proxy-user-header", default="X-Forwarded-User",
                     help="Header carrying the user under --auth trusted-proxy (default X-Forwarded-User)")
    acc.add_argument("--proxy-name-header", default="X-Forwarded-Preferred-Username",
                     help="Header carrying the display name (default X-Forwarded-Preferred-Username)")
    acc.add_argument("--proxy-email-header",
                     help="Optional header carrying the e-mail; when present it is used as the login")
    acc.add_argument("--members-only", action="store_true",
                     help="Admit only people listed in people.json (limn member add) or --allow; others get 403 and are not recorded")
    acc.add_argument("--local-user",
                     help="The owner's login under --auth local (default $USER, then 'owner')")
    acc.add_argument("--agent-token-file", default=os.environ.get("LIMN_AGENT_TOKEN_FILE") or None, metavar="PATH",
                     help="Where agents on this machine keep this instance's token (limn token create <instance> "
                          "--save; default $LIMN_AGENT_TOKEN_FILE, which limn run sets). Never read: once the file "
                          "exists, pins.md and the 401 for a headerless local request tell agents to send it")
    return ap
