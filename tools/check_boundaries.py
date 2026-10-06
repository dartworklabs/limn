"""Check feature surfaces and import paths without importing application code.

A module a feature owns imports nothing another feature owns. Only the entry points import feature packages, by
name and from the package itself, and only the names ENTRYPOINT_IMPORTS approves. A feature's __all__ therefore
holds the names an entry point imports and the names TEST_EXPORTS keeps for tests of other slices, and nothing else.
"""

import ast
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypeAlias

ENTRY_POINTS = {"limn.server", "limn.cli", "limn.__main__"}
CAPABILITIES = {"administration", "builds", "collaboration", "documents", "pins", "revisions", "sync", "viewer"}
BOUNDARIES = {"runtime", "security", "platform", "web"}
BUILD_STORAGE_NAMES = {"head.txt", "built_at.txt", "built_src_mtime.txt", "pages.cur", "builds.json"}

EntrypointImports: TypeAlias = Mapping[str, set[str]]
TestExports: TypeAlias = Mapping[str, set[str]]

# Entry point -> the names it imports from feature packages. An approval the entry point does not use fails.
ENTRYPOINT_IMPORTS: EntrypointImports = {
    "limn.server": {
        "doc_start_line",
        "docs_of",
        "pick_documents",
        "BuildSubsystem",
        "BuildMapCache",
        "assemble_builds",
        "CollaborationSubsystem",
        "assemble_collaboration",
        "DocumentsSubsystem",
        "MetaSettings",
        "assemble_documents",
        "PinSubsystem",
        "TokenCache",
        "assemble_pins",
        "RevisionJobs",
        "RevisionSubsystem",
        "ScopeCache",
        "assemble_revisions",
        "PullShare",
        "SyncContext",
        "SyncSubsystem",
        "SyncWatch",
        "assemble_sync",
        "ServedViewer",
        "assemble_viewer",
        "default_pdfjs_dir",
        "read_viewer",
        "serve_viewer",
    },
    "limn.cli": {"CliError", "cmd_member", "cmd_token", "migrate_main"},
    "limn.__main__": set(),
}

# Feature -> the names it exports although no entry point imports them, so that tests of other slices hand their
# subject the supplier's real value, as server.py does, instead of a look-alike. A name no such test imports fails.
TEST_EXPORTS: TestExports = {
    "limn.builds": {
        "pin_build_queries",  # pin tests give pin services the build answers server.py injects
        "document_build_queries",  # tests of document reads give them the build answers server.py injects
        "ElementFact",  # pin location tests build the element inside a figure-map answer
        "ElementSelection",  # pin location tests build the figure-map answer that selects an element
        "SelectionUnavailable",  # pin location tests build the figure-map answer that selects nothing
    },
}


def owner(module: str) -> str | None:
    """Return the capability owning a module, excluding namespace packages."""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "limn" or parts[1] not in CAPABILITIES:
        return None
    return ".".join(parts[:2])


def is_test(rel: Path) -> bool:
    """Tell whether a path below the source root is a colocated test file rather than production code."""
    return "tests" in rel.parts or rel.name.startswith("test_")


def read_modules(root: Path, package: str, keep: Callable[[Path], bool]) -> dict[str, str]:
    """Read the Python files under root whose relative path keep accepts, keyed by module name below package.

    Vendor code is never read. A root that is not a directory yields nothing.
    """
    result = {}
    for path in sorted(root.rglob("*.py")) if root.is_dir() else ():
        rel = path.relative_to(root)
        if "vendor" in rel.parts or not keep(rel):
            continue
        parts = rel.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        result[".".join((package, *parts))] = path.read_text(encoding="utf-8")
    return result


def sources(root: Path) -> dict[str, str]:
    """Read production modules only; colocated tests and vendor code are excluded."""
    return read_modules(root, "limn", lambda rel: not is_test(rel))


def read_tests(root: Path, shared_tests: Path) -> dict[str, str]:
    """Read the test modules colocated under the source root and every module of the shared test tree.

    A colocated test keeps its limn.<feature>... name, so owner() names the slice it tests; a module of the shared
    tree is named below "tests" and has no owner.
    """
    return {**read_modules(root, "limn", is_test), **read_modules(shared_tests, "tests", lambda rel: True)}


def imports(module: str, tree: ast.Module, packages: set[str]) -> list[tuple[str, str | None]]:
    """Resolve absolute and relative imports to their module and optional symbol."""
    result = []
    package = module if module in packages else module.rpartition(".")[0]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parent = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join((*parent, *base.split("."))).rstrip(".")
            result.extend((base, alias.name) for alias in node.names)
    return result


def exports(tree: ast.Module) -> set[str] | None:
    """Read a literal __all__; dynamic or absent declarations cannot define a surface."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
                return set(value)
    return None


def surfaces(code: Mapping[str, str]) -> dict[str, set[str] | None]:
    """Map every feature that owns a module in code to its literal __all__, or None when it declares none."""
    features = {feature for name in code if (feature := owner(name))}
    return {name: exports(ast.parse(code[name], filename=name)) if name in code else None for name in features}


def violations(code: Mapping[str, str], packages: set[str]) -> list[str]:
    """Report every import that leaves its owner, sorted and without duplicates.

    code maps production module names to source and packages names those that are packages. Inside one feature,
    modules import each other freely. Reported are: a feature without a literal __all__; a feature module importing
    anything another feature owns ("private import" unless the target is a name the owner's package exports, then
    "feature import"); an entry point importing a feature other than by an exported name from its package (also
    "private import"; which exported names it may import is surface_violations' question); a module other than an
    entry point importing an entry point, which would reach every feature; a module no feature owns reaching a
    feature module through any chain of imports, package initializers included; and a feature other than builds
    naming a build storage file.
    """
    trees = {name: ast.parse(source, filename=name) for name, source in code.items()}
    declared = surfaces(code)
    errors = [f"{name}: missing literal __all__" for name, surface in sorted(declared.items()) if surface is None]
    graph: dict[str, set[str]] = {name: set() for name in code}
    for name, tree in trees.items():
        source_owner = owner(name)
        if source_owner and source_owner != "limn.builds":
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in BUILD_STORAGE_NAMES:
                    errors.append(f"{name}:{node.lineno}: build storage leak {node.value}")
        for base, symbol in imports(name, tree, packages):
            target = f"{base}.{symbol}" if symbol and f"{base}.{symbol}" in code else base
            if base in code:
                graph[name].add(base)
            if target in code:
                graph[name].add(target)
            # Python executes package initializers before importing their child.
            for imported in (base, target):
                parts = imported.split(".")
                for end in range(1, len(parts)):
                    parent = ".".join(parts[:end])
                    if parent in packages and parent in code:
                        graph[name].add(parent)
            if name not in ENTRY_POINTS and ENTRY_POINTS & {base, target}:
                errors.append(f"{name}: entry point import {target}")
            target_owner = owner(target)
            if target_owner and source_owner != target_owner:
                imported_name = base + (f".{symbol}" if symbol else "")
                if base != target_owner or symbol not in (declared.get(target_owner) or set()):
                    errors.append(f"{name}: private import {imported_name}")
                elif source_owner:
                    errors.append(f"{name}: feature import {imported_name}")

    def paths(start: str) -> dict[str, tuple[str, ...]]:
        """Find reachable modules with one finite witness per destination."""
        reached = {start: (start,)}
        pending = [start]
        while pending:
            node = pending.pop()
            for target in sorted(graph[node]):
                if target not in reached:
                    reached[target] = (*reached[node], target)
                    pending.append(target)
        return reached

    for name in code:
        if owner(name) is None and name not in ENTRY_POINTS:
            errors.extend(
                "shared reaches feature: " + " -> ".join(path) for target, path in paths(name).items() if owner(target)
            )
    return sorted(set(errors))


def surface_violations(
    code: Mapping[str, str],
    packages: set[str],
    test_code: Mapping[str, str],
    entrypoint_imports: EntrypointImports,
    test_exports: TestExports,
) -> list[str]:
    """Report exported names nobody approved imports and approvals no import backs, sorted and without duplicates.

    code and packages are as in violations(); test_code maps test module names to source. entrypoint_imports maps
    an entry point to the names it may import from feature packages, test_exports a feature to the names it exports
    for tests of other slices. Reported are: an entry point importing an exported name it has no approval for; an
    approval its entry point does not import; a name in a feature's __all__ that no entry point imports with
    approval and test_exports does not list; and a test export that is missing from __all__ or that no test outside
    the owning feature imports from the package by name.
    """
    declared = {feature: surface or set() for feature, surface in surfaces(code).items()}

    def named_imports(module: str, source: str) -> set[tuple[str, str]]:
        """Return the (feature, name) pairs a module imports from feature packages by an exported name."""
        tree = ast.parse(source, filename=module)
        return {(base, symbol) for base, symbol in imports(module, tree, packages) if symbol in declared.get(base, ())}

    errors = []
    composed: set[tuple[str, str]] = set()
    for entry in sorted(ENTRY_POINTS | set(entrypoint_imports)):
        approved = entrypoint_imports.get(entry, set())
        imported = named_imports(entry, code[entry]) if entry in code else set()
        errors.extend(
            f"{entry}: unapproved composition import {feature}.{name}"
            for feature, name in imported
            if name not in approved
        )
        errors.extend(
            f"{entry}: stale composition approval {name}" for name in approved - {name for _, name in imported}
        )
        composed |= {(feature, name) for feature, name in imported if name in approved}
    tested = {
        pair
        for module, source in test_code.items()
        for pair in named_imports(module, source)
        if owner(module) != pair[0]
    }
    for feature in sorted(set(declared) | set(test_exports)):
        kept = test_exports.get(feature, set())
        surface = declared.get(feature, set())
        errors.extend(
            f"{feature}: export {name} has no approved importer"
            for name in surface - kept
            if (feature, name) not in composed
        )
        errors.extend(f"{feature}: stale test export {name} is not in __all__" for name in kept - surface)
        errors.extend(
            f"{feature}: stale test export {name} has no importing test outside the feature"
            for name in kept & surface
            if (feature, name) not in tested
        )
    return sorted(set(errors))


def check(root: Path, shared_tests: Path) -> list[str]:
    """Check the source tree under root; empty discovery and unowned source files fail closed.

    shared_tests is the test tree outside the source root; with the tests colocated under root it supplies the
    importers that justify TEST_EXPORTS.
    """
    code = sources(root)
    if not code:
        return [f"no production modules found under {root}"]
    unowned = [
        f"unowned production module: {name}"
        for name in code
        if name != "limn"
        and name not in ENTRY_POINTS
        and (len(name.split(".")) < 3 or name.split(".")[1] not in CAPABILITIES | BOUNDARIES)
        and name not in {f"limn.{package}" for package in CAPABILITIES | BOUNDARIES}
    ]
    packages = {name for name in code if (root / Path(*name.split(".")[1:]) / "__init__.py").is_file()}
    test_code = read_tests(root, shared_tests)
    return sorted(
        [
            *unowned,
            *violations(code, packages),
            *surface_violations(code, packages, test_code, ENTRYPOINT_IMPORTS, TEST_EXPORTS),
        ]
    )


def main() -> int:
    """Print boundary violations and return nonzero when the repository fails."""
    repository = Path(__file__).resolve().parents[1]
    errors = check(repository / "src" / "limn", repository / "tests")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Feature boundaries: feature imports, shared dependencies and surfaces passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
