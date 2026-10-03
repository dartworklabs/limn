"""CI supply chain: every action a workflow runs is pinned to a commit, and checkout leaves no token behind.

1. A `uses:` names a local action (`./...`) or `owner/repo[/path]@<40-hex commit SHA>`. A tag or branch can be moved
   to other code after review; a commit cannot. Dependabot (.github/dependabot.yml) bumps the pins.
2. Every `actions/checkout` step sets `persist-credentials: false`, so no later step finds the job token in
   .git/config.

The rules are pure functions over a workflow's text, so the tests feed them violating text as well as the real files.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^'\"\s#]+)")
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
STEP_START = re.compile(r"^(\s*)-\s")


def unpinned_actions(text: str) -> list[str]:
    """Return `line N: <ref>` for each `uses:` in a workflow's text that is neither local nor pinned to a commit SHA."""
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        m = USES.match(line)
        if m and not m.group(1).startswith("./") and not PINNED.match(m.group(1)):
            found.append("line %d: %s" % (n, m.group(1)))
    return found


def checkouts_keeping_credentials(text: str) -> list[str]:
    """Return `line N` for each actions/checkout step whose own lines lack `persist-credentials: false`.

    A step runs from its `- ` line to the next line at the same or a smaller indent that starts a step or a key.
    """
    lines = text.splitlines()
    found = []
    for n, line in enumerate(lines):
        m = USES.match(line)
        if not (m and m.group(1).startswith("actions/checkout@")):
            continue
        start = STEP_START.match(line)
        indent = len(start.group(1)) if start else len(line) - len(line.lstrip())
        body = []
        for later in lines[n + 1 :]:
            if later.strip() and len(later) - len(later.lstrip()) <= indent:
                break
            body.append(later.strip())
        if "persist-credentials: false" not in body:
            found.append("line %d" % (n + 1))
    return found


def workflow_files() -> list[Path]:
    """The repository's workflow files; the suite fails rather than passing on none."""
    files = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert files, "no workflow files under .github/workflows"
    return files


def test_every_action_is_pinned_to_a_commit():
    """No workflow runs an action by a movable tag or branch."""
    bad = {p.name: unpinned_actions(p.read_text(encoding="utf-8")) for p in workflow_files()}
    assert {k: v for k, v in bad.items() if v} == {}


def test_every_checkout_drops_its_credentials():
    """No workflow's checkout leaves the job token in .git/config."""
    bad = {p.name: checkouts_keeping_credentials(p.read_text(encoding="utf-8")) for p in workflow_files()}
    assert {k: v for k, v in bad.items() if v} == {}


def test_pin_rule_rejects_tags_branches_and_short_shas():
    """A tag, a branch, a short SHA and a quoted tag are each reported; a full SHA and a local action are not."""
    text = "\n".join(
        [
            "      - uses: actions/checkout@v4",
            "      - uses: astral-sh/setup-uv@main",
            "      - uses: actions/setup-node@49933ea",
            "        uses: 'owner/repo/sub@v1'",
            "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0",
            "      - uses: ./.github/actions/local",
        ]
    )
    assert unpinned_actions(text) == [
        "line 1: actions/checkout@v4",
        "line 2: astral-sh/setup-uv@main",
        "line 3: actions/setup-node@49933ea",
        "line 4: owner/repo/sub@v1",
    ]


def test_credentials_rule_reads_only_the_checkout_step():
    """A checkout without the setting is reported even when the next step has it; one with it under `with:` is not."""
    sha = "11d5960a326750d5838078e36cf38b85af677262"
    text = "\n".join(
        [
            "    steps:",
            "      - uses: actions/checkout@%s" % sha,
            "        with:",
            "          fetch-depth: 0",
            "      - uses: actions/checkout@%s" % sha,
            "        with:",
            "          persist-credentials: false",
            "      - name: other",
            "        with:",
            "          persist-credentials: false",
        ]
    )
    assert checkouts_keeping_credentials(text) == ["line 2"]
