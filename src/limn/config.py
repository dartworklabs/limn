"""The run settings of one `limn serve` process: the Cfg type and the accent palette its default comes from.

The composition root (server.py) makes the one instance (`C = Cfg()`) and fills it in at startup from the rules in
limn/startup.py; the modules it wires receive the values (or C itself, typed by a Protocol such as
limn.documents.RunPaths) as arguments. Nothing here reads the command line, the environment or the disk.
"""
from __future__ import annotations

import ipaddress
from pathlib import Path

from limn import events, people
from limn.access import HostEntry, IPNetwork
from limn.audit import AUDIT_FILE
from limn.store import PinFiles

# A high-saturation "700-level" palette with enough contrast on both the dark and light theme backgrounds
# (--bg #14161a / #e9ebef) and under white text (chip text). One is chosen by hashing the label string -
# the same label always gets the same color.
ACCENT_PALETTE = ("#1d4ed8", "#047857", "#be123c", "#6d28d9",
                  "#0e7490", "#c2410c", "#a21caf", "#4d7c0f")


class Cfg:
    """Holds the run arguments. Every project-specific value passes through here."""
    src: Path
    main: Path
    state: Path
    build: Path
    port: int
    dpi: int
    envs: tuple[str, ...]
    timeout: int
    allow: frozenset[str]
    origin_check: bool = True
    git_pull: bool = False
    pdfjs_dir: Path | None = None   # None = server.default_pdfjs_dir()
    label: str = "원고"             # label distinguishing multiple instances (§Running multiple manuscript instances at once). Filled in by main()
    accent: str = ACCENT_PALETTE[0]  # the label's accent color (#rrggbb)
    repo: str | None = None         # git origin URL of --manuscript. None if absent
    # Access control (v0.2). The defaults are exactly the v0.1 behaviour: tailscale headers, headerless loopback = agent.
    # The names from auth on are also limn.startup.AccessOptions' fields: configure_access copies them over by name.
    auth: str = "tailscale"         # identity provider: tailscale | local | trusted-proxy
    agent_loopback: bool = True     # headerless loopback request = the agent (deprecated; tailscale + loopback bind only)
    tailnet_agent: bool = False     # ...also when it came through tailscale serve (Host not loopback) - opt-in, deprecated
    bind: str = "127.0.0.1"
    # ((name, port or None), ...) accepted as Host/Origin besides loopback and *.ts.net
    public_hosts: tuple[HostEntry, ...] = ()
    trusted_proxies: tuple[IPNetwork, ...] = (ipaddress.ip_network("127.0.0.1/32"), ipaddress.ip_network("::1/128"))
    proxy_user_header: str = "X-Forwarded-User"
    proxy_name_header: str = "X-Forwarded-Preferred-Username"
    proxy_email_header: str | None = None
    members_only: bool = False      # admit only logins in people.json (or --allow)
    local_user: str | None = None   # the owner's login under --auth local (None = $USER, then "owner")
    insecure: bool = False          # a non-loopback bind allowed by --i-know-this-is-insecure
    # where agents on this machine keep this instance's token (ADR-0007); never read
    agent_token_file: Path | None = None

    @property
    def pins_jsonl(self) -> Path:
        """The live pins (the file names are the pin store's, limn.store.PinFiles)."""
        return PinFiles(self.state).pins_jsonl

    @property
    def pins_md(self) -> Path:
        """The agents' work list."""
        return PinFiles(self.state).pins_md

    @property
    def dropped(self) -> Path:
        """The Trash."""
        return PinFiles(self.state).dropped

    @property
    def seq(self) -> Path:
        """The last pin id handed out."""
        return PinFiles(self.state).seq

    @property
    def pages_ptr(self) -> Path:
        """The pointer to the current page-image directory of the single document."""
        return self.state / "pages.cur"

    @property
    def built_src_mtime_file(self) -> Path:
        """The manuscript mtime the current build was made from."""
        return self.state / "built_src_mtime.txt"

    @property
    def builds_file(self) -> Path:
        """The build history of the single document."""
        return self.state / "builds.json"

    @property
    def people_file(self) -> Path:
        """people.json: the logins, names and roles of the people who used this instance."""
        return self.state / people.PEOPLE_FILE

    @property
    def events_file(self) -> Path:
        """events.jsonl: the @-tag and state-change notices."""
        return self.state / events.EVENTS_FILE

    @property
    def tokens_file(self) -> Path:
        """tokens.json: the hashed agent API tokens."""
        return self.state / "tokens.json"

    @property
    def audit_file(self) -> Path:
        """The append-only audit log of destructive and owner actions (see append_audit)."""
        return self.state / AUDIT_FILE
