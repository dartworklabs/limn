"""CI supply chain: every action a workflow runs is pinned to a commit, and checkout leaves no token behind.

1. A `uses:` names a local action (`./...`) or `owner/repo[/path]@<40-hex commit SHA>`. A tag or branch can be moved
   to other code after review; a commit cannot. Dependabot (.github/dependabot.yml) bumps the pins.
2. Every `actions/checkout` step sets `persist-credentials: false`, so no later step finds the job token in
   .git/config.
3. Every setup-uv step selects an exact uv release, and the isolated build requires an exact Hatchling release.
   Pinning the action alone does not pin the executable it downloads or the backend that builds the package.

The rules are pure functions over a workflow's text, so the tests feed them violating text as well as the real files.
"""

import re
from pathlib import Path

from hypothesis import given, strategies as st

try:
    import tomllib
except ModuleNotFoundError:
    # Python 3.10 uses the same parser already locked through pytest and mypy's development dependencies.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^'\"\s#]+)")
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}$")
STEP_START = re.compile(r"^(\s*)-\s")
EXACT_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


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


def unpinned_uv_versions(text: str) -> list[str]:
    """Report setup-uv steps without one literal release in their own version input.

    Reject absent inputs, moving aliases, ranges and expressions even if a later step supplies a version.
    The workflow's ordinary step indentation bounds the input search; comments grant no pin.
    """
    lines = text.splitlines()
    found = []
    for n, line in enumerate(lines):
        action = USES.match(line)
        if not (action and action.group(1).startswith("astral-sh/setup-uv@")):
            continue
        start = STEP_START.match(line)
        indent = len(start.group(1)) if start else len(line) - len(line.lstrip()) - 2
        versions = []
        in_inputs = False
        for later in lines[n + 1 :]:
            content = later.split("#", 1)[0].rstrip()
            if not content.strip():
                continue
            nesting = len(content) - len(content.lstrip())
            if nesting <= indent:
                break
            if nesting == indent + 2:
                in_inputs = content.strip() == "with:"
            version = re.fullmatch(r"\s*version:\s*(.*?)\s*", content)
            if in_inputs and nesting == indent + 4 and version:
                versions.append(version.group(1).strip().strip("\"'"))
        if len(versions) != 1 or EXACT_VERSION.fullmatch(versions[0]) is None:
            found.append("line %d" % (n + 1))
    return found


def hatchling_is_pinned(text: str) -> bool:
    """Require one exact Hatchling release in the package's build-system requirement array.

    Parse the same TOML that the package builder reads, so comments and multiline prose cannot impersonate
    requirements. Refuse malformed documents, unexpected shapes and differently constrained backends.
    """
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False
    section = document.get("build-system")
    if not isinstance(section, dict):
        return False
    requirements = section.get("requires")
    if not isinstance(requirements, list) or not all(isinstance(item, str) for item in requirements):
        return False
    hatchling = [item for item in requirements if re.match(r"hatchling\b", item, re.IGNORECASE)]
    return len(hatchling) == 1 and re.fullmatch(r"hatchling==[0-9]+\.[0-9]+\.[0-9]+", hatchling[0]) is not None


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


def test_every_uv_install_selects_an_exact_release():
    """A SHA-pinned setup action cannot silently download a moving uv release."""
    bad = {p.name: unpinned_uv_versions(p.read_text(encoding="utf-8")) for p in workflow_files()}
    assert {k: v for k, v in bad.items() if v} == {}


def test_package_build_requires_an_exact_hatchling_release():
    """Fresh isolated wheel and sdist builds use the same reviewed build backend."""
    assert hatchling_is_pinned((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_uv_version_rule_rejects_missing_and_moving_inputs():
    """Each setup step needs its own pin; comments and the following step's pin cannot satisfy it."""
    action = "      - uses: astral-sh/setup-uv@" + "a" * 40
    for value in (None, "latest", "latest-known", "0.12", "0.12.*", ">=0.12.23", "${{ matrix.uv }}"):
        body = "" if value is None else f'        with:\n          version: "{value}"\n'
        text = action + "\n" + body + action + '\n        with:\n          version: "0.12.23"\n'
        assert unpinned_uv_versions(text) == ["line 1"], value
    assert unpinned_uv_versions(action + '\n        # version: "0.12.23"\n') == ["line 1"]


def test_uv_pin_must_be_an_immediate_with_input():
    """A version in env or a nested unrelated input must not promise a pinned download."""
    action = "      - uses: astral-sh/setup-uv@" + "a" * 40
    for body in (
        '        env:\n          version: "0.12.23"\n',
        '        with:\n          nested:\n            version: "0.12.23"\n',
    ):
        assert unpinned_uv_versions(action + "\n" + body) == ["line 1"]
    named = "      - name: Install uv\n        uses: astral-sh/setup-uv@" + "a" * 40
    assert unpinned_uv_versions(named + '\n        with:\n          version: "0.12.23"\n') == []


@given(st.tuples(*(st.integers(min_value=0, max_value=999) for _ in range(3))))
def test_literal_uv_releases_are_accepted_and_ranges_are_rejected(parts):
    """Every generated numeric release is stable; broadening that same release to a range loses the pin."""
    version = ".".join(map(str, parts))
    action = "      - uses: astral-sh/setup-uv@" + "a" * 40
    assert unpinned_uv_versions(action + f'\n        with:\n          version: "{version}"\n') == []
    assert unpinned_uv_versions(action + f'\n        with:\n          version: ">={version}"\n') == ["line 1"]


def test_hatchling_pin_rule_rejects_ranges_missing_backend_and_foreign_section_pins():
    """Only the build-system requirement pins builds; a dev pin or a broad backend constraint leaves drift."""
    for value in ("hatchling", "hatchling>=1.27", "hatchling==1.32.*", "hatchling~=1.32.4"):
        assert not hatchling_is_pinned(f'[build-system]\nrequires = ["{value}"]\n'), value
    assert not hatchling_is_pinned('[dependency-groups]\ndev = ["hatchling==1.32.4"]\n')
    assert not hatchling_is_pinned('[build-system]\nrequires = ["other==1.32.4"]\n')
    assert hatchling_is_pinned('[build-system]\nrequires = ["hatchling==1.32.4"]\n')


def test_commented_hatchling_requirement_does_not_pin_the_backend():
    """A reviewed-looking pin in an array comment leaves the real range unconstrained."""
    assert not hatchling_is_pinned('[build-system]\nrequires = [\n  # "hatchling==1.32.4"\n]\n')


def test_hatchling_pin_in_a_multiline_string_cannot_hide_the_real_range():
    """Only parsed TOML requirements govern the build, even when a prose string imitates a pinned section."""
    text = '''description = """
[build-system]
requires = ["hatchling==1.32.4"]
"""
[build-system]
requires = ["hatchling>=1.27"]
'''
    assert not hatchling_is_pinned(text)


@given(st.tuples(*(st.integers(min_value=0, max_value=999) for _ in range(3))))
def test_hatchling_releases_require_exact_equality(parts):
    """Generated backend releases pin builds only with exact equality; allowing a newer backend introduces drift."""
    version = ".".join(map(str, parts))
    assert hatchling_is_pinned(f'[build-system]\nrequires = ["hatchling=={version}"]\n')
    assert not hatchling_is_pinned(f'[build-system]\nrequires = ["hatchling>={version}"]\n')


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
