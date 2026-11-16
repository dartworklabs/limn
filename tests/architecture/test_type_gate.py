"""The type gate (tools/check_types.py, [tool.basedpyright]) keeps what it guarantees: docs/handbook/verification.md §9.

The gate replaced mypy --strict. These tests run basedpyright with the repository's own settings on a small package that
breaks each guarantee mypy enforced here - an inexhaustive match over a closed Literal and over a union, a comparison
or containment test with a value outside a closed Literal, a wrong argument type, an unchecked None, a supplier that
does not meet a Protocol, an implicit re-export, a name only Linux declares - and check that each is reported, that a
`# type: ignore` silences nothing, and that the legal module next to them passes.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    # Python 3.10 uses the same parser already locked through pytest's development dependency.
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["basedpyright"]
SPEC = importlib.util.spec_from_file_location("check_types", ROOT / "tools" / "check_types.py")
assert SPEC is not None and SPEC.loader is not None
check_types = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_types)

# The rules the gate's guarantees rest on; turning one off would drop a guarantee the Handbook states.
GUARANTEES = (
    "reportMatchNotExhaustive",
    "reportUnnecessaryComparison",
    "reportUnnecessaryContains",
    "reportArgumentType",
    "reportReturnType",
    "reportOptionalMemberAccess",
    "reportAttributeAccessIssue",
    "reportPrivateLocalImportUsage",
    "reportExplicitAny",
)

ROLE = 'from typing import Literal\n\nRole = Literal["owner", "editor", "viewer", "agent"]\n'
REEXPORT = "from pkg.roles import Role\n\nKEEP: Role = 'owner'\n"
VIOLATIONS = {
    "match_literal": "from pkg.roles import Role\n\n\ndef label(role: Role) -> int:\n    match role:\n"
    "        case 'owner' | 'editor':\n            return 1\n        case 'viewer':\n            return 2\n",
    "match_union": "class A: ...\n\n\nclass B: ...\n\n\ndef value(v: A | B) -> int:\n    match v:\n"
    "        case A():\n            return 1\n",
    "equality": "from pkg.roles import Role\n\n\ndef owner(role: Role) -> bool:\n    return role == 'ownr'\n",
    "contains": "from pkg.roles import Role\n\n\ndef writer(role: Role) -> bool:\n    return role in ('ownr', 'edtor')\n",
    "argument": "def double(n: int) -> int:\n    return n * 2\n\n\ndef call() -> int:\n    return double('2')\n",
    "ignored": "def double(n: int) -> int:\n    return n * 2\n\n\ndef call() -> int:\n"
    "    return double('2')  # type: ignore[arg-type]\n",
    "optional": "def lines(s: str | None) -> list[str]:\n    return s.splitlines()\n",
    "protocol": "from typing import Protocol\n\n\nclass Counts(Protocol):\n    def open_count(self) -> int: ...\n\n\n"
    "class Supplier:\n    def closed_count(self) -> int:\n        return 0\n\n\n"
    "def use(c: Counts) -> int:\n    return c.open_count()\n\n\nwire = use(Supplier())\n",
    "reexport_user": "from pkg.reexport import Role\n\nVALUE: Role = 'owner'\n",
    "any": "from typing import Any\n\n\ndef loose(x: Any) -> None: ...\n",
}
EXPECTED = {
    "match_literal": "reportMatchNotExhaustive",
    "match_union": "reportMatchNotExhaustive",
    "equality": "reportUnnecessaryComparison",
    "contains": "reportUnnecessaryContains",
    "argument": "reportArgumentType",
    "ignored": "reportArgumentType",
    "optional": "reportOptionalMemberAccess",
    "protocol": "reportArgumentType",
    "reexport_user": "reportPrivateLocalImportUsage",
    "any": "reportExplicitAny",
}
LEGAL = (
    "from typing import NoReturn\n\nfrom pkg.roles import Role\n\n\n"
    "def assert_never(value: NoReturn) -> NoReturn:\n    raise AssertionError(value)\n\n\n"
    "def label(role: Role) -> int:\n    match role:\n        case 'owner' | 'editor':\n            return 1\n"
    "        case 'viewer' | 'agent':\n            return 2\n\n\n"
    "def writes(role: Role) -> bool:\n    match role:\n        case 'owner' | 'editor':\n            return True\n"
    "        case 'viewer':\n            return False\n        case 'agent':\n            return False\n        case _:\n"
    "            assert_never(role)\n\n\n"
    "def owner(role: Role) -> bool:\n    return role == 'owner'\n"
)
PLATFORM = "import os\n\n\ndef cpus() -> int:\n    return len(os.sched_getaffinity(0))\n"


def toml_value(value: object) -> str:
    """One [tool.basedpyright] value written back as TOML: a string, a bool or a list of strings."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(value)


def run(project: Path, modules: dict[str, str], platform: str) -> list[tuple[str, str]]:
    """basedpyright's (module, rule) diagnostics for a package named pkg under the repository's settings, as Linux or
    as macOS. Paths are the package's, not src/limn; everything else is the repository's configuration."""
    settings = {**SETTINGS, "include": ["pkg"], "exclude": []}
    lines = ["[tool.basedpyright]", *(f"{key} = {toml_value(value)}" for key, value in settings.items())]
    (project / "pyproject.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    package = project / "pkg"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, source in {"roles": ROLE, "reexport": REEXPORT, **modules}.items():
        (package / f"{name}.py").write_text(source, encoding="utf-8")
    command = Path(sys.executable).with_name("basedpyright")
    proc = subprocess.run(
        [
            str(command),
            "-p",
            str(project),
            "--pythonpath",
            sys.executable,
            "--pythonplatform",
            platform,
            "--outputjson",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    report = json.loads(proc.stdout)
    return [(Path(d["file"]).stem, d.get("rule", "")) for d in report["generalDiagnostics"]]


def test_the_gate_checks_every_rule_and_honours_no_ignore_comment():
    """typeCheckingMode is "all", `# type: ignore` silences nothing, and no guarantee rule is turned off."""
    assert SETTINGS["typeCheckingMode"] == "all"
    assert SETTINGS["enableTypeIgnoreComments"] is False
    assert SETTINGS["pythonVersion"] == "3.10"
    assert not {rule for rule in GUARANTEES if rule in SETTINGS}


def test_every_rule_turned_off_says_why():
    """Each rule the project turns off has a comment directly above it in pyproject.toml."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8").split("[tool.basedpyright]", 1)[1].splitlines()
    for previous, line in zip(text, text[1:], strict=False):
        if line.startswith("report") and line.rstrip().endswith("= false"):
            assert previous.startswith("#"), line


def test_each_guarantee_is_reported_and_the_legal_module_passes(tmp_path):
    """Every injected violation is reported under its rule; the exhaustive, assert_never-closed module has none."""
    found = run(tmp_path, {**VIOLATIONS, "legal": LEGAL}, "Linux")
    for module, rule in EXPECTED.items():
        assert (module, rule) in found, (module, found)
    assert [entry for entry in found if entry[0] in {"legal", "roles", "reexport"}] == []


@pytest.mark.parametrize(("platform", "reported"), [("Linux", False), ("Darwin", True)])
def test_a_name_only_linux_declares_fails_the_macos_run(tmp_path, platform, reported):
    """os.sched_getaffinity exists in Linux's standard library only, so the macOS run of the gate reports it."""
    found = run(tmp_path, {"cpus": PLATFORM}, platform)
    assert (("cpus", "reportAttributeAccessIssue") in found) is reported


def test_a_rewritten_baseline_fails_the_gate():
    """basedpyright lowers its baseline silently; any change of the file's bytes, or its creation, is a failure."""
    assert check_types.baseline_changed(b"{}", b"{}") is False
    assert check_types.baseline_changed(b'{"files": {"a": []}}', b'{"files": {}}') is True
    assert check_types.baseline_changed(None, b"{}") is True
