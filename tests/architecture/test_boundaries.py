"""Feature boundaries reject private access, indirect dependency leaks and cycles."""

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
