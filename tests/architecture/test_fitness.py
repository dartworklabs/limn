"""tools/check_fitness.py: a module's file name gives it a role, each role's rules hold, and the baseline only goes down.

The rules are pure functions over module sources keyed by their path below src/limn, so each test feeds the scanner a
small violating tree and the legal tree next to it; the last tests run the command itself against a temporary source
tree and baseline directory.
"""

import importlib.util
import json
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_fitness", ROOT / "tools" / "check_fitness.py")
assert SPEC is not None and SPEC.loader is not None
fitness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fitness)

# Modules every synthetic tree may import: a value, a pure platform helper, a platform module doing I/O, a service.
BASE = {
    "pins/values.py": "PinNo = int\n",
    "pins/reexport_values.py": "from limn.pins.values import PinNo\n",
    "platform/text.py": "from typing import TypeAlias\n\nFreeText: TypeAlias = str\n",
    "platform/files.py": "import os\n",
    "pins/service.py": "import subprocess\n",
}


def rules_of(sources: dict[str, str], path: str) -> list[str]:
    """The rules the module at path breaks, in a tree made of BASE and sources."""
    return [v.rule for v in fitness.scan({**BASE, **sources}) if v.path == path]


def test_repository_matches_its_baseline():
    """Every production module's counts equal the committed baseline, and the reviewed aliases exist."""
    sources = fitness.production_sources(ROOT / "src" / "limn")
    assert fitness.stale_aliases(sources) == []
    counts = fitness.count(fitness.scan(sources))
    assert fitness.compare(counts, fitness.read_baseline(ROOT / "tools" / "fitness-baseline")) == []


def test_each_baseline_file_holds_only_its_own_slice():
    """A slice's file lists only modules of that slice, each with positive counts of known rules."""
    for file in sorted((ROOT / "tools" / "fitness-baseline").glob("*.json")):
        for path, rules in json.loads(file.read_text(encoding="utf-8")).items():
            assert fitness.slice_of(path) == file.stem, path
            assert rules and all(rule in fitness.RULES and n > 0 for rule, n in rules.items()), path


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("server.py", "entry"),
        ("cli.py", "entry"),
        ("__main__.py", "entry"),
        ("__init__.py", "surface"),
        ("pins/__init__.py", "surface"),
        ("pins/editing/rules.py", "decision"),
        ("pins/editing/values.py", "model"),
        ("pins/model.py", "model"),
        ("pins/needs.py", "protocol"),
        ("collaboration/contracts.py", "protocol"),
        ("web/request_input.py", "parse"),
        ("pins/lifecycle/input.py", "parse"),
        ("web/parse.py", "parse"),
        ("pins/lifecycle/http.py", "http"),
        ("pins/lifecycle/routes.py", "http"),
        ("builds/answer.py", "http"),
        ("pins/lifecycle/service.py", "service"),
        ("sync/run.py", "service"),
        ("pins/store.py", "persistence"),
        ("builds/queries.py", "persistence"),
        ("pins/application.py", "assembly"),
        ("platform/files.py", "platform"),
        ("web/handler.py", "transport"),
        ("runtime/config.py", "runtime"),
    ],
)
def test_the_name_and_place_give_the_role(path, role):
    """Entry points by path, __init__ as surface, the basename's word, then the boundary package."""
    assert fitness.role_of(path) == role


@pytest.mark.parametrize("path", ["pins/helpers.py", "builds/engine.py", "security/access.py", "pins/server.py"])
def test_a_name_that_says_no_role_is_rejected(path):
    """A basename outside ROLE_WORDS, outside a boundary package, has no role; an entry-point name below root neither."""
    assert fitness.role_of(path) is None
    assert rules_of({path: ""}, path) == ["role-unknown"]


@given(prefix=st.from_regex(r"[a-z][a-z_]{0,12}", fullmatch=True), word=st.sampled_from(sorted(fitness.ROLE_WORDS)))
def test_a_suffix_word_gives_its_role_anywhere(prefix, word):
    """`<anything>_<word>.py` takes the word's role in any feature package, as `<word>.py` does."""
    assert fitness.role_of(f"pins/{prefix}_{word}.py") == fitness.ROLE_WORDS[word]
    assert fitness.role_of(f"builds/{word}.py") == fitness.ROLE_WORDS[word]


def test_a_decision_importing_a_shell_is_rejected_and_a_value_import_passes():
    """Inner roles import only inner roles (a shell doing I/O is also I/O); a module without a role is not inner."""
    assert rules_of({"pins/rules.py": "from limn.pins.service import run\n"}, "pins/rules.py") == [
        "io",
        "role-imports",
    ]
    assert rules_of({"pins/rules.py": "from limn.pins.helpers import f\n", "pins/helpers.py": ""}, "pins/rules.py") == [
        "role-imports"
    ]
    assert rules_of({"pins/rules.py": "from limn.pins.values import PinNo\n"}, "pins/rules.py") == []


def test_a_type_checking_import_still_counts_for_the_role_but_not_for_io():
    """An import under TYPE_CHECKING never runs, so it performs no I/O, but the dependency between roles is real."""
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from limn.pins.service import run\n"
    assert rules_of({"pins/rules.py": source}, "pins/rules.py") == ["role-imports"]


@pytest.mark.parametrize(
    "source",
    [
        "import os\n",
        "from subprocess import run\n",
        "import urllib.request\n",
        "from limn.platform.files import f\n",  # a platform module that imports os
        "def f():\n    return open('x').read()\n",
        "def f():\n    print('x')\n",
        "from datetime import datetime\n\ndef f():\n    return datetime.now()\n",
    ],
)
def test_a_pure_module_reaching_io_is_rejected(source):
    """Decision, model, protocol and parse modules reach no I/O by any runtime path, clock reads included."""
    assert rules_of({"pins/rules.py": source}, "pins/rules.py") == ["io"]
    assert rules_of({"pins/input.py": source}, "pins/input.py") == ["io"]


def test_a_pure_module_may_use_values_and_pure_helpers():
    """json, pathlib values, a pure platform helper and datetime arithmetic are not I/O."""
    source = (
        "import json\nfrom pathlib import Path\nfrom urllib.parse import quote\nfrom datetime import timedelta\n"
        "from limn.platform.text import FreeText\n"
    )
    assert rules_of({"pins/rules.py": source}, "pins/rules.py") == []


def test_an_adapter_may_reach_io_only_through_other_modules():
    """An HTTP adapter calls a service that does I/O; importing os itself is I/O it does not own."""
    assert rules_of({"pins/http.py": "from limn.pins.service import run\n"}, "pins/http.py") == []
    assert rules_of({"pins/http.py": "import os\n"}, "pins/http.py") == ["io"]
    assert rules_of({"pins/store.py": "import os\n"}, "pins/store.py") == []


def test_limn_web_outside_the_http_roles_is_rejected():
    """A service, a decision or a module without a role importing limn.web fails; an HTTP adapter or parser passes."""
    tree = {"web/errors.py": ""}
    assert rules_of({**tree, "pins/service.py": "from limn.web.errors import E\n"}, "pins/service.py") == [
        "role-imports",
        "web-import",
    ]
    assert "web-import" in rules_of({**tree, "pins/thing.py": "import limn.web.errors\n"}, "pins/thing.py")
    assert rules_of({**tree, "pins/http.py": "from limn.web.errors import E\n"}, "pins/http.py") == []
    assert rules_of({**tree, "pins/input.py": "from limn.web.errors import E\n"}, "pins/input.py") == []


def test_isinstance_outside_a_parse_module_is_rejected():
    """isinstance and issubclass are for boundary parsing only."""
    source = "def f(x: object) -> bool:\n    return isinstance(x, int) or issubclass(type(x), str)\n"
    assert rules_of({"pins/service.py": source}, "pins/service.py") == ["isinstance", "isinstance"]
    assert rules_of({"pins/input.py": source}, "pins/input.py") == []


@pytest.mark.parametrize(
    "source", ["from typing import cast\nx = cast(int, '1')\n", "import typing\nx = typing.cast(int, '1')\n"]
)
def test_cast_is_rejected_in_every_role(source):
    """A cast is not a parse: no role may use typing.cast, the parse role included."""
    assert rules_of({"pins/input.py": source}, "pins/input.py") == ["cast"]
    assert rules_of({"pins/input.py": "x = int('1')\n"}, "pins/input.py") == []


@pytest.mark.parametrize(
    "comment", ["# type: ignore", "# type: ignore[arg-type]", "#type:ignore", "# pyright: ignore", "# pyright: basic"]
)
def test_a_checker_escape_comment_is_rejected(comment):
    """No comment may silence or lower the type checker; the same text inside a string is no comment."""
    assert rules_of({"pins/store.py": f"x = 1  {comment}\n"}, "pins/store.py") == ["ignore-comment"]
    assert rules_of({"pins/store.py": f"x = {comment!r}\n"}, "pins/store.py") == []


@pytest.mark.parametrize(
    "arm",
    [
        "case _:\n            return 0",
        "case other:\n            return 0",
        "case 1 | _:\n            return 0",
        "case _:\n            log(x)",
    ],
)
def test_an_irrefutable_case_without_assert_never_is_rejected(arm):
    """`case _`, a bare capture, or an or-pattern holding one must end in assert_never."""
    source = f"def f(x: int) -> int:\n    match x:\n        case 1:\n            return 1\n        {arm}\n"
    assert rules_of({"pins/store.py": source}, "pins/store.py") == ["wildcard-case"]


@pytest.mark.parametrize(
    "arm",
    [
        "case _:\n            assert_never(x)",
        "case _:\n            limn_never.assert_never(x)",
        "case _ if x > 2:\n            return 0",
        "case 2:\n            return 2",
    ],
)
def test_assert_never_guards_and_refutable_cases_pass(arm):
    """The one legal wildcard ends in assert_never; a guarded wildcard or a refutable case is not a wildcard."""
    source = f"def f(x: int) -> int:\n    match x:\n        case 1:\n            return 1\n        {arm}\n"
    assert rules_of({"pins/store.py": source}, "pins/store.py") == []


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("def close(pin_id: str) -> int: ...\n", 2),
        ("from dataclasses import dataclass\n@dataclass\nclass Pin:\n    login: str\n    line: int | None\n", 2),
        ("class Pin:\n    def __init__(self, fields: dict[str, object]) -> None: ...\n", 1),
        ("from typing import Protocol\nclass Counts(Protocol):\n    def open(self) -> 'int': ...\n", 1),
        ("from typing import TypeAlias\nLogin: TypeAlias = str\ndef f(who: Login) -> None: ...\n", 1),
        ("Login = str\ndef f(who: Login) -> None: ...\n", 1),
        ("from limn.pins.values import PinNo\ndef f(pin: PinNo) -> None: ...\n", 1),
        ("from limn.pins.reexport_values import PinNo\ndef f(pin: PinNo) -> None: ...\n", 1),
        ("from collections.abc import Mapping\ndef f(record: Mapping[str, object]) -> None: ...\n", 1),
    ],
)
def test_a_primitive_in_a_decision_signature_or_field_is_rejected(source, found):
    """str, int and dict in a public signature or field, directly or behind an alias of any module, are rejected."""
    assert rules_of({"pins/rules.py": source}, "pins/rules.py") == ["primitive"] * found
    assert rules_of({"pins/model.py": source}, "pins/model.py") == ["primitive"] * found
    assert rules_of({"pins/needs.py": source}, "pins/needs.py") == ["primitive"] * found


@pytest.mark.parametrize(
    "source",
    [
        "from limn.platform.text import FreeText\ndef reply(note: FreeText) -> None: ...\n",
        "from typing import NewType\nPinId = NewType('PinId', int)\ndef close(pin: PinId) -> bool: ...\n",
        "from typing import Literal\nState = Literal['open', 'done']\ndef move(to: State) -> None: ...\n",
        "def _private(x: str) -> int: ...\n",
        "class Pin:\n    _cache: dict[str, int]\n    def __eq__(self, other: object) -> bool: ...\n"
        "    def __str__(self) -> str: ...\n",
        "LIMIT: int = 4000\n",
    ],
)
def test_reviewed_text_distinct_types_and_private_names_pass(source):
    """FreeText, NewType, Literal, private names, fixed dunder signatures and module constants are not checked."""
    assert rules_of({"pins/rules.py": source}, "pins/rules.py") == []


def test_primitives_are_not_checked_outside_decision_model_and_protocol():
    """A parser, a service or an adapter speaks the wire's strings."""
    source = "def parse(body: dict[str, object]) -> str: ...\n"
    for path in ("pins/input.py", "pins/service.py", "pins/http.py"):
        assert rules_of({path: source}, path) == []


def test_a_reviewed_alias_that_no_longer_exists_is_reported():
    """PRIMITIVE_ALIASES names real aliases of a primitive; a stale entry fails the command."""
    assert fitness.stale_aliases(BASE) == []
    assert fitness.stale_aliases({**BASE, "platform/text.py": "FreeText = 1\n"}) == [
        "PRIMITIVE_ALIASES lists limn.platform.text.FreeText, which is not an alias of a primitive type"
    ]


def test_a_count_above_its_baseline_fails_and_below_asks_for_update():
    """Above (an unlisted module has baseline 0) is new code; below is a stale baseline to lower."""
    assert fitness.compare({"pins/a.py": {"isinstance": 2}}, {"pins/a.py": {"isinstance": 2}}) == []
    assert fitness.compare(
        {"pins/a.py": {"isinstance": 3}, "pins/b.py": {"cast": 1}}, {"pins/a.py": {"isinstance": 2}}
    ) == [
        "src/limn/pins/a.py: isinstance 3, baseline 2 - new code must keep its role's rules",
        "src/limn/pins/b.py: cast 1, baseline 0 - new code must keep its role's rules",
    ]
    assert fitness.compare({}, {"pins/a.py": {"isinstance": 2}}) == [
        "src/limn/pins/a.py: isinstance 0, baseline 2 - lower the baseline (--update)"
    ]


counts_strategy = st.dictionaries(
    st.sampled_from(["pins/a.py", "builds/b.py", "server.py"]),
    st.dictionaries(st.sampled_from(fitness.RULES), st.integers(1, 5), min_size=1),
)


@given(counts=counts_strategy, baseline=counts_strategy)
def test_update_writes_only_when_no_count_rises(counts, baseline):
    """lowered() refuses exactly when some module and rule count is above its baseline, and compare() is empty exactly
    when the counts equal the baseline."""
    rises = any(n > baseline.get(path, {}).get(rule, 0) for path, rules in counts.items() for rule, n in rules.items())
    assert bool(fitness.lowered(counts, baseline)) == rises
    assert (fitness.compare(counts, baseline) == []) == (counts == baseline)


def test_a_rename_carries_the_counts_and_refuses_unknown_paths():
    """--rename OLD=NEW moves OLD's counts to NEW; an OLD the baseline lacks or a NEW it holds is refused."""
    baseline = {"pins/mapping.py": {"role-unknown": 1, "isinstance": 3}, "pins/b.py": {"cast": 1}}
    moved, problems = fitness.renamed(baseline, {"pins/mapping.py": "pins/location_rules.py"})
    assert problems == [] and moved == {
        "pins/location_rules.py": {"role-unknown": 1, "isinstance": 3},
        "pins/b.py": {"cast": 1},
    }
    assert fitness.renamed(baseline, {"pins/none.py": "pins/x.py"})[1] == [
        "--rename pins/none.py=pins/x.py: the baseline lists no pins/none.py"
    ]
    assert fitness.renamed(baseline, {"pins/mapping.py": "pins/b.py"})[1] == [
        "--rename pins/mapping.py=pins/b.py: the baseline already lists pins/b.py"
    ]


def test_the_baseline_is_one_file_per_slice(tmp_path):
    """Counts land in <slice>.json (root.json for files directly under src/limn); a slice with none has no file."""
    (tmp_path / "sync.json").write_text("{}", encoding="utf-8")
    counts = {"pins/a.py": {"cast": 1}, "pins/b/c.py": {"isinstance": 2}, "server.py": {"isinstance": 1}}
    fitness.write_baseline(tmp_path, counts)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["pins.json", "root.json"]
    assert fitness.read_baseline(tmp_path) == counts


@pytest.fixture
def repository(tmp_path, monkeypatch):
    """A source tree with one module holding one isinstance, and its baseline directory, as the command sees them."""
    source, baseline = tmp_path / "src", tmp_path / "baseline"
    (source / "pins").mkdir(parents=True)
    (source / "platform").mkdir()
    (source / "platform" / "text.py").write_text(BASE["platform/text.py"], encoding="utf-8")
    (source / "pins" / "service.py").write_text(
        "def f(x: object) -> bool:\n    return isinstance(x, int)\n", encoding="utf-8"
    )
    monkeypatch.setattr(fitness, "SOURCE", source)
    monkeypatch.setattr(fitness, "BASELINE_DIR", baseline)
    fitness.write_baseline(baseline, {"pins/service.py": {"isinstance": 1}})
    return source, baseline


def test_the_command_passes_on_its_baseline_and_fails_on_a_new_violation(repository, capsys):
    """Equal counts exit 0; one more isinstance exits 1 and names its line."""
    source, _ = repository
    assert fitness.main([]) == 0
    (source / "pins" / "service.py").write_text(
        "def f(x: object) -> bool:\n    return isinstance(x, int) and isinstance(x, bool)\n", encoding="utf-8"
    )
    assert fitness.main([]) == 1
    assert "src/limn/pins/service.py:2: isinstance" in capsys.readouterr().err


def test_update_refuses_to_raise_and_writes_nothing(repository):
    """--update with a count above the baseline exits 1 and leaves the baseline as it was."""
    source, baseline = repository
    before = fitness.read_baseline(baseline)
    (source / "pins" / "thing.py").write_text("", encoding="utf-8")
    assert fitness.main(["--update"]) == 1
    assert fitness.read_baseline(baseline) == before


def test_a_stale_baseline_fails_until_update_lowers_it(repository):
    """A fixed violation fails the check; --update lowers the baseline and the check passes again."""
    source, baseline = repository
    (source / "pins" / "service.py").write_text("def f(x: int) -> bool:\n    return x > 0\n", encoding="utf-8")
    assert fitness.main([]) == 1
    assert fitness.main(["--update"]) == 0
    assert fitness.read_baseline(baseline) == {}
    assert fitness.main([]) == 0


def test_update_with_a_rename_moves_the_counts(repository):
    """A module moved to a new name keeps its counts when --rename names the move, and cannot gain any."""
    source, baseline = repository
    (source / "pins" / "service.py").rename(source / "pins" / "claim_service.py")
    assert fitness.main(["--update"]) == 1
    assert fitness.main(["--update", "--rename", "src/limn/pins/service.py=src/limn/pins/claim_service.py"]) == 0
    assert fitness.read_baseline(baseline) == {"pins/claim_service.py": {"isinstance": 1}}
