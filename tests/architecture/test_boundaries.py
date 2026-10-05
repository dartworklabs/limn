"""Feature boundaries reject private access, indirect dependency leaks and cycles."""

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


def test_repository_respects_all_feature_surfaces():
    """Every production slice has exports and every dependency respects ownership."""
    assert checker.check(ROOT / "src" / "limn") == []


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


@pytest.mark.parametrize(
    "provider,name",
    [
        ("builds", "BuildView"),
        ("builds", "FigureMap"),
        ("builds", "MapPage"),
        ("builds", "MapElement"),
        ("pins", "PinReadView"),
    ],
)
def test_storage_shaped_public_contracts_cannot_return(provider, name):
    """Re-exporting a retired broad contract must not let document consumers use it again."""
    code = {
        "limn.documents": '__all__ = ["act"]',
        "limn.documents.reads": f"from limn.{provider} import {name}",
        f"limn.{provider}": f'__all__ = ["{name}"]',
    }
    errors = checker.violations(code, {"limn.documents", f"limn.{provider}"}, checker.CROSSING_NAMES)
    assert any("unapproved crossing" in error for error in errors)


def test_server_has_no_application_service_locator():
    """The entrypoint composes ports and does not own a mega application class."""
    tree = ast.parse((ROOT / "src" / "limn" / "server.py").read_text(encoding="utf-8"))
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert classes == {"Handler", "RunStart", "RunEnvironment", "ServerAssembly", "StartedServer"}
    assert not any(
        isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        for child in node.body
    ), "Composition values cannot hide capability workflows in a renamed application class"


def test_production_crossings_are_the_reviewed_query_contracts():
    """Public helpers cannot silently widen any current cross-capability dependency."""
    assert {
        ("limn.pins", "limn.builds"): {
            "PinBuildQueries",
            "ElementFollower",
            "ElementFact",
            "ElementSelection",
            "SelectionUnavailable",
            "Publication",
        },
    } == checker.CROSSING_NAMES


def test_revisions_imports_no_other_feature():
    """Revision code names no other feature, its public surface included: the pin facts it reads are Protocols of its
    own (limn.revisions.needs) and the composition root injects the supplier."""
    code = checker.sources(ROOT / "src" / "limn")
    packages = {name for name in code if (ROOT / "src" / "limn" / Path(*name.split(".")[1:]) / "__init__.py").is_file()}
    imported = {
        (name, base, symbol)
        for name, source in code.items()
        if checker.owner(name) == "limn.revisions"
        for base, symbol in checker.imports(name, checker.ast.parse(source), packages)
        if checker.owner(base) not in (None, "limn.revisions")
    }

    assert imported == set()


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


def test_slice_cycle_is_rejected_even_through_shared_modules():
    """Public imports and a shared intermediate module cannot conceal a feature cycle."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": "from limn.bridge import helper",
        "limn.bridge.helper": "from limn.builds import act",
        "limn.builds": '__all__ = ["act"]\n',
        "limn.builds.act": "from limn.pins import act",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds"})
    assert any("slice cycle" in error for error in errors)


def test_package_initialization_counts_toward_slice_cycles():
    """Importing a child executes its shared package initializer and must count that path."""
    code = {
        "limn.pins": '__all__ = ["act"]\n',
        "limn.pins.act": "import limn.bridge.helper",
        "limn.bridge": "from limn.builds import act",
        "limn.bridge.helper": "",
        "limn.builds": '__all__ = ["act"]\n',
        "limn.builds.act": "from limn.pins import act",
    }
    errors = checker.violations(code, {"limn.pins", "limn.builds", "limn.bridge"})
    assert any("slice cycle" in error for error in errors)


def test_relative_import_inside_a_slice_is_allowed():
    """Private helpers remain usable by their owner, including relative imports."""
    code = {
        "limn.pins": '__all__ = ["act"]\nfrom .act import act',
        "limn.pins.act": "from .private import helper",
        "limn.pins.private": "",
    }
    assert checker.violations(code, {"limn.pins"}) == []


def test_crossing_allowlist_rejects_an_unapproved_public_name():
    """A public export cannot cross a capability boundary without explicit approval."""
    code = {
        "limn.pins": '__all__ = ["PinReadView", "PinStore"]\n',
        "limn.pins.application": "class PinReadView: ...\n",
        "limn.pins.store": "class PinStore: ...\n",
        "limn.documents": '__all__ = ["DocumentViews"]\n',
        "limn.documents.reads": "from limn.pins import PinStore\n",
    }

    errors = checker.violations(
        code,
        {"limn.pins", "limn.documents"},
        {("limn.documents", "limn.pins"): {"PinReadView"}},
    )

    assert "limn.documents.reads: unapproved crossing limn.pins.PinStore" in errors


def test_crossing_allowlist_accepts_the_approved_public_name():
    """The exact public contract named for a capability pair remains importable."""
    code = {
        "limn.pins": '__all__ = ["PinReadView"]\n',
        "limn.pins.application": "class PinReadView: ...\n",
        "limn.documents": '__all__ = ["DocumentViews"]\n',
        "limn.documents.reads": "from limn.pins import PinReadView\n",
    }

    assert (
        checker.violations(
            code,
            {"limn.pins", "limn.documents"},
            {("limn.documents", "limn.pins"): {"PinReadView"}},
        )
        == []
    )


def test_composition_import_allowlist_rejects_a_domain_helper():
    """An entry point may import only the approved capability assembly names."""
    code = {
        "limn.pins": '__all__ = ["assemble_pins", "PinStore"]\n',
        "limn.pins.application": "def assemble_pins(): ...\n",
        "limn.pins.store": "class PinStore: ...\n",
        "limn.server": "from limn.pins import PinStore\n",
    }

    errors = checker.violations(
        code,
        {"limn.pins"},
        None,
        {"limn.server": {"assemble_pins"}},
    )

    assert "limn.server: unapproved composition import limn.pins.PinStore" in errors


def test_empty_discovery_fails(tmp_path):
    """A misconfigured source root must not pass without checking any modules."""
    assert checker.check(tmp_path) != []


@pytest.mark.parametrize("relative", ["store.py", "pins2/model.py", "common/helper.py"])
def test_unowned_production_files_are_rejected(tmp_path, relative):
    """Loose business modules and undeclared duplicate capabilities cannot escape the graph."""
    (tmp_path / "__init__.py").write_text('"""Application package."""\n')
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('"""Unowned production module."""\n')
    assert any("unowned production module" in error for error in checker.check(tmp_path))


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
