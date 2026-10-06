"""Feature boundaries reject imports between features, indirect dependency leaks and exports nobody imports."""

import ast
import importlib.util
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_boundaries", ROOT / "tools" / "check_boundaries.py")
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

# A feature whose one exported name the server imports with approval: the legal case the surface tests start from.
COMPOSED = {
    "limn.pins": '__all__ = ["assemble_pins"]\n',
    "limn.pins.application": "def assemble_pins(): ...\n",
    "limn.server": "from limn.pins import assemble_pins\n",
}
APPROVED = {"limn.server": {"assemble_pins"}}


def test_repository_respects_all_feature_surfaces():
    """No production feature imports another, and every exported name has the importer its approval names."""
    assert checker.check(ROOT / "src" / "limn", ROOT / "tests") == []


@pytest.mark.parametrize("consumer", ["sync", "documents", "pins", "collaboration", "revisions"])
@pytest.mark.parametrize("marker", ["head.txt", "built_at.txt", "built_src_mtime.txt", "pages.cur", "builds.json"])
def test_foreign_build_marker_access_is_rejected(consumer, marker):
    """Feature consumers cannot bypass the build owner by naming its marker or history files."""
    code = {
        f"limn.{consumer}": "__all__ = []",
        f"limn.{consumer}.reads": f'answer = (doc.dir / "{marker}").read_text()',
    }
    errors = checker.violations(code, {f"limn.{consumer}"})
    assert any("build storage leak" in error for error in errors)


def test_build_owner_may_read_its_markers():
    """The provider remains free to interpret its own publication layout."""
    code = {"limn.builds": "__all__ = []", "limn.builds.queries": 'answer = (doc.dir / "head.txt").read_text()'}
    assert checker.violations(code, {"limn.builds"}) == []


def test_server_has_no_application_service_locator():
    """The entrypoint composes collaborators and does not own a mega application class."""
    tree = ast.parse((ROOT / "src" / "limn" / "server.py").read_text(encoding="utf-8"))
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert classes == {"Handler", "RunStart", "RunEnvironment", "ServerAssembly", "StartedServer"}
    assert not any(
        isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for child in node.body
    ), "Composition values cannot hide capability workflows in a renamed application class"


@pytest.mark.parametrize("statement", ["import limn.builds.private", "from limn.builds import private"])
def test_private_import_is_rejected(statement):
    """Both Python import forms must reject another feature's internal module."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": statement,
        "limn.builds": '__all__ = ["act"]\n',
        "limn.builds.private": "",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds"})
    assert any("private import" in error for error in errors)


@pytest.mark.parametrize(
    "statement",
    [
        "from limn.builds import PinBuildQueries",
        "from ..builds import PinBuildQueries",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from limn.builds import PinBuildQueries",
        "def act():\n    from limn.builds import PinBuildQueries",
    ],
)
def test_exported_name_of_another_feature_is_rejected(statement):
    """A name on another feature's surface is still not importable from a feature: no place in the module, relative
    form or type-checking guard makes it legal."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": statement,
        "limn.builds": '__all__ = ["PinBuildQueries"]\n',
        "limn.builds.contracts": "class PinBuildQueries: ...\n",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds"})
    assert errors == ["limn.pins.act: feature import limn.builds.PinBuildQueries"]


def test_entry_point_reaches_a_feature_only_through_its_package():
    """Composition imports exported names from the feature package; a module inside the feature stays private."""
    code = {**COMPOSED, "limn.pins.store": "class PinStore: ...\n"}
    assert checker.violations(code, {"limn.pins"}) == []

    code["limn.server"] = "from limn.pins.store import PinStore\n"
    assert checker.violations(code, {"limn.pins"}) == ["limn.server: private import limn.pins.store.PinStore"]


def test_shared_path_to_a_feature_is_rejected():
    """A shared module cannot hide a feature dependency behind another shared module."""
    code = {
        "limn.shared": "from limn.platform import helper",
        "limn.platform.helper": "from limn.pins import act",
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": "",
    }
    errors = checker.violations(code, {"limn.pins"})
    assert any("limn.shared -> limn.platform.helper -> limn.pins" in error for error in errors)


def test_shared_package_initializer_counts_toward_the_path():
    """Importing a child executes its package initializer, so a feature import there is on the importer's path."""
    code = {
        "limn.shared": "import limn.bridge.helper",
        "limn.bridge": "from limn.builds import act",
        "limn.bridge.helper": "",
        "limn.builds": '__all__ = ["act"]\n',
    }
    errors = checker.violations(code, {"limn.builds", "limn.bridge"})
    assert "shared reaches feature: limn.shared -> limn.bridge -> limn.builds" in errors


def test_features_importing_each_other_are_both_rejected():
    """Two features that name each other's exports need no cycle search: each import is a violation on its own."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": "from limn.builds import act",
        "limn.builds": '__all__ = ["act"]\n',
        "limn.builds.act": "from limn.pins import act",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds"})
    assert errors == [
        "limn.builds.act: feature import limn.pins.act",
        "limn.pins.act: feature import limn.builds.act",
    ]


def test_features_depending_on_each_other_through_a_shared_module_are_rejected():
    """A shared module between two features cannot conceal their mutual dependency: the shared module that reaches a
    feature is reported, and so is the direct import coming back."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": "from limn.bridge import helper",
        "limn.bridge.helper": "from limn.builds import act",
        "limn.builds": '__all__ = ["act"]\n',
        "limn.builds.act": "from limn.pins import act",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds"})
    assert "shared reaches feature: limn.bridge.helper -> limn.builds" in errors
    assert "limn.builds.act: feature import limn.pins.act" in errors


@pytest.mark.parametrize("statement", ["from limn import server", "import limn.server", "from limn.cli import main"])
def test_only_an_entry_point_imports_an_entry_point(statement):
    """An entry point imports every feature, so a feature importing one would depend on all of them unseen."""
    code = {"limn.pins": "__all__ = []\n", "limn.pins.act": statement, "limn.server": "", "limn.cli": ""}
    errors = checker.violations(code, {"limn.pins"})
    assert len(errors) == 1 and errors[0].startswith("limn.pins.act: entry point import limn.")


def test_entry_points_may_import_each_other():
    """The command entry starts the server entry; that chain stays legal."""
    code = {"limn.__main__": "from limn.cli import main", "limn.cli": "from limn import server", "limn.server": ""}
    assert checker.violations(code, set()) == []


def test_relative_import_inside_a_slice_is_allowed():
    """Private helpers remain usable by their owner, including relative imports."""
    code = {
        "limn.pins": '__all__ = ["act"]\nfrom .act import act',
        "limn.pins.act": "from .private import helper",
        "limn.pins.private": "",
    }
    assert checker.violations(code, {"limn.pins"}) == []


def test_export_imported_by_an_approved_entry_point_passes():
    """A surface that holds exactly what the entry point imports with approval has nothing to report."""
    assert checker.surface_violations(COMPOSED, {"limn.pins"}, {}, APPROVED, {}) == []


def test_export_without_an_approved_importer_is_rejected():
    """A name added to __all__ that no entry point imports and no test export lists is named in the failure."""
    code = {**COMPOSED, "limn.pins": '__all__ = ["assemble_pins", "PinStore"]\n'}

    errors = checker.surface_violations(code, {"limn.pins"}, {}, APPROVED, {})

    assert errors == ["limn.pins: export PinStore has no approved importer"]


def test_stale_entry_point_approval_is_rejected():
    """An approved name the entry point does not import is reported, so the approvals equal the real imports."""
    approvals = {"limn.server": {"assemble_pins", "PinStore"}}

    errors = checker.surface_violations(COMPOSED, {"limn.pins"}, {}, approvals, {})

    assert errors == ["limn.server: stale composition approval PinStore"]


def test_unapproved_entry_point_import_is_rejected():
    """An entry point may import only the approved names, even from a feature's exported surface."""
    code = {
        **COMPOSED,
        "limn.pins": '__all__ = ["assemble_pins", "PinStore"]\n',
        "limn.server": "from limn.pins import PinStore, assemble_pins\n",
    }

    errors = checker.surface_violations(code, {"limn.pins"}, {}, APPROVED, {})

    assert "limn.server: unapproved composition import limn.pins.PinStore" in errors


def test_test_export_imported_by_a_test_of_another_slice_passes():
    """A name no entry point imports may stay exported when it is listed and a test outside the feature imports it."""
    code = {**COMPOSED, "limn.builds": '__all__ = ["pin_build_queries"]\n'}
    tests = {"limn.pins.tests.test_locate": "from limn.builds import pin_build_queries\n"}
    kept = {"limn.builds": {"pin_build_queries"}}

    assert checker.surface_violations(code, {"limn.pins", "limn.builds"}, tests, APPROVED, kept) == []


@pytest.mark.parametrize(
    "tests",
    [
        {},
        {"limn.builds.tests.test_build": "from limn.builds import pin_build_queries\n"},
        {"tests.support.helpers": "from limn.builds.queries import pin_build_queries\n"},
    ],
)
def test_test_export_without_an_outside_test_is_rejected(tests):
    """A listed test export is stale unless a test of another slice imports it from the package: no test at all, the
    feature's own test, and an import that goes around the package do not count."""
    code = {**COMPOSED, "limn.builds": '__all__ = ["pin_build_queries"]\n'}
    kept = {"limn.builds": {"pin_build_queries"}}

    errors = checker.surface_violations(code, {"limn.pins", "limn.builds"}, tests, APPROVED, kept)

    assert errors == ["limn.builds: stale test export pin_build_queries has no importing test outside the feature"]


def test_test_export_missing_from_the_surface_is_rejected():
    """A listed test export the feature no longer exports is reported instead of lingering as an approval."""
    kept = {"limn.pins": {"PinStore"}}
    tests = {"tests.support.helpers": "from limn.pins import PinStore\n"}

    errors = checker.surface_violations(COMPOSED, {"limn.pins"}, tests, APPROVED, kept)

    assert errors == ["limn.pins: stale test export PinStore is not in __all__"]


def test_empty_discovery_fails(tmp_path):
    """A misconfigured source root must not pass without checking any modules."""
    assert checker.check(tmp_path, tmp_path / "tests") != []


@pytest.mark.parametrize("relative", ["store.py", "pins2/model.py", "common/helper.py"])
def test_unowned_production_files_are_rejected(tmp_path, relative):
    """Loose business modules and undeclared duplicate capabilities cannot escape the graph."""
    (tmp_path / "__init__.py").write_text('"""Application package."""\n')
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('"""Unowned production module."""\n')
    assert any("unowned production module" in error for error in checker.check(tmp_path, tmp_path / "tests"))


@given(st.integers(min_value=1, max_value=12))
def test_every_shared_module_in_a_chain_is_rejected(depth):
    """Any length of indirection preserves the prohibition on shared feature dependencies."""
    code = {f"limn.shared{i}": f"import limn.shared{i + 1}" for i in range(depth - 1)}
    code[f"limn.shared{depth - 1}"] = "from limn.pins import act"
    code["limn.pins"] = '__all__ = ["act"]\n'
    errors = checker.violations(code, {"limn.pins"})
    for i in range(depth):
        assert any(error.startswith(f"shared reaches feature: limn.shared{i} ->") for error in errors)


def test_discovery_excludes_colocated_tests(tmp_path):
    """Test-only feature imports must neither enter the graph nor create production slices."""
    (tmp_path / "__init__.py").write_text('"""Application package."""\n')
    tests = tmp_path / "alpha" / "tests"
    tests.mkdir(parents=True)
    (tests / "support.py").write_text("import limn.builds.private\n")
    assert checker.sources(tmp_path) == {"limn": '"""Application package."""\n'}


def test_test_discovery_names_colocated_and_shared_tests(tmp_path):
    """A colocated test keeps its slice's module name and a shared test has none, which is how the checker tells a
    feature's own test from a test of another slice; production modules are not read as tests."""
    source = tmp_path / "src"
    (source / "pins" / "tests").mkdir(parents=True)
    (source / "pins" / "store.py").write_text("production\n")
    (source / "pins" / "tests" / "test_locate.py").write_text("colocated\n")
    shared = tmp_path / "tests"
    (shared / "support").mkdir(parents=True)
    (shared / "support" / "helpers.py").write_text("shared\n")

    assert checker.read_tests(source, shared) == {
        "limn.pins.tests.test_locate": "colocated\n",
        "tests.support.helpers": "shared\n",
    }
