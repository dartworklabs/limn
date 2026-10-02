"""The run settings of one `limn serve` process: RunConfig, the access options it holds, and the accent palette.

The startup steps (server.start over the rules in limn/runtime/startup.py) make one RunConfig from the command line, and the
composition root binds it once, as `C`, before the server listens. It is frozen: no setting changes while the server
runs, and a test that needs other settings makes another value (dataclasses.replace) and binds that. The modules the
composition root wires receive what they read as values - a document the frozen RunPaths (RunConfig.paths), identify()
and admit() the AccessSettings (RunConfig.access_settings). Nothing here reads the command line, the environment or
the disk.
"""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Literal

from limn.runtime.documents import RunPaths
from limn.runtime.paths import AUDIT_FILE, EVENTS_FILE, PEOPLE_FILE, PinFiles
from limn.security.access import AccessSettings, AuthProvider, HostEntry, IPNetwork

# A high-saturation "700-level" palette with enough contrast on both the dark and light theme backgrounds
# (--bg #14161a / #e9ebef) and under white text (chip text). One is chosen by hashing the label string -
# the same label always gets the same color.
ACCENT_PALETTE = ("#1d4ed8", "#047857", "#be123c", "#6d28d9", "#0e7490", "#c2410c", "#a21caf", "#4d7c0f")

# The viewer's interface languages, the values --ui-lang takes (docs/handbook/operations.md §실행 인자).
UiLang = Literal["ko", "en"]
UI_LANGS: tuple[UiLang, ...] = ("ko", "en")


@dataclass(frozen=True)
class AccessOptions:
    """The access settings a command line starts with (limn.runtime.startup.access_options decides them; a security boundary,
    docs/adr/0002-access-control.md). RunConfig holds them as one value, and the startup log (access_log_lines) reads
    the same value."""

    auth: AuthProvider  # identity provider
    bind: str  # the listen address
    agent_loopback: bool  # a headerless loopback request is the agent (deprecated)
    tailnet_agent: bool  # ...also one through tailscale serve (opt-in, deprecated)
    public_hosts: tuple[HostEntry, ...]  # --public-host entries
    trusted_proxies: tuple[IPNetwork, ...]  # --trusted-proxies networks
    proxy_user_header: str  # the header carrying the user under --auth trusted-proxy
    proxy_name_header: str  # ...the display name
    proxy_email_header: str | None  # ...the e-mail (None = not configured)
    members_only: bool  # admit only logins in people.json or --allow
    local_user: str | None  # the owner's login under --auth local (None = $USER, then "owner")
    insecure: bool  # a non-loopback bind allowed only by --i-know-this-is-insecure
    agent_token_file: Path | None  # where this machine's agents keep the token (ADR-0007); never read


@dataclass(frozen=True)
class RunConfig:
    """The settings of one run, fixed at startup. Every project-specific value passes through here.

    No field has a default: the startup steps state every one (server.configure_run), so a setting added later can
    never fall back silently at a place that did not think about it."""

    src: Path  # --manuscript: the manuscript tree
    main: Path  # the main .tex (the first LaTeX --doc document's, else --main's or the detected one)
    state: Path  # the instance state folder
    port: int
    dpi: int
    envs: tuple[str, ...]  # --float-envs
    timeout: int  # --build-timeout, seconds
    allow: frozenset[str]  # --allow: the logins admitted when set
    origin_check: bool  # False under --no-origin-check
    git_pull: bool
    pdfjs_dir: Path | None  # None = server.default_pdfjs_dir()
    label: str  # label distinguishing multiple instances (§Running multiple manuscript instances at once)
    accent: str  # the label's accent color (#rrggbb)
    repo: str | None  # git origin URL of --manuscript. None if absent
    access: AccessOptions  # --auth, --bind and the other access options
    ui_lang: UiLang | None  # --ui-lang: the viewer's default interface language (None = the browser's decides)

    @property
    def paths(self) -> RunPaths:
        """The run paths a document reads (limn.runtime.documents.RunPaths): a frozen value, like this one."""
        return RunPaths(self.src, self.main, self.state)

    @cached_property
    def access_settings(self) -> AccessSettings:
        """What identify() and admit() read of this run: the access options and --allow as limn.security.access's value. Made
        once per RunConfig (never per request); a replaced RunConfig makes its own."""
        a = self.access
        return AccessSettings(
            auth=a.auth,
            agent_loopback=a.agent_loopback,
            tailnet_agent=a.tailnet_agent,
            trusted_proxies=a.trusted_proxies,
            proxy_user_header=a.proxy_user_header,
            proxy_name_header=a.proxy_name_header,
            proxy_email_header=a.proxy_email_header,
            members_only=a.members_only,
            allow=self.allow,
            local_user=a.local_user,
            agent_token_file=a.agent_token_file,
        )

    @property
    def build(self) -> Path:
        """The build copy of an instance started without --doc."""
        return self.paths.build

    @property
    def pins_jsonl(self) -> Path:
        """The live pins (the file names are the pin store's, limn.pins.store.PinFiles)."""
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
        return self.state / PEOPLE_FILE

    @property
    def events_file(self) -> Path:
        """events.jsonl: the @-tag and state-change notices."""
        return self.state / EVENTS_FILE

    @property
    def tokens_file(self) -> Path:
        """tokens.json: the hashed agent API tokens."""
        return self.state / "tokens.json"

    @property
    def audit_file(self) -> Path:
        """The append-only audit log of destructive and owner actions (see append_audit)."""
        return self.state / AUDIT_FILE
