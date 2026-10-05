"""Check feature exports and dependency paths without importing application code."""

import ast
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import TypeAlias

ENTRY_POINTS = {"limn.server", "limn.cli", "limn.__main__"}
CAPABILITIES = {"administration", "builds", "collaboration", "documents", "pins", "revisions", "sync", "viewer"}
BOUNDARIES = {"runtime", "security", "platform", "web"}
BUILD_STORAGE_NAMES = {"head.txt", "built_at.txt", "built_src_mtime.txt", "pages.cur", "builds.json"}

CrossingKey: TypeAlias = tuple[str, str]
CrossingNames: TypeAlias = Mapping[CrossingKey, set[str]]
EntrypointImports: TypeAlias = Mapping[str, set[str]]

CROSSING_NAMES: CrossingNames = {
    ("limn.documents", "limn.builds"): {"DocumentBuildQueries", "document_build_queries"},
    ("limn.documents", "limn.pins"): {"PinCountQueries"},
    ("limn.pins", "limn.builds"): {
        "PinBuildQueries",
        "ElementFollower",
        "ElementFact",
        "ElementSelection",
        "SelectionUnavailable",
        "Publication",
    },
    ("limn.pins", "limn.collaboration"): {"Notice"},
    ("limn.revisions", "limn.pins"): {"RevisionPinQuery", "RevisionPin"},
}
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


def owner(module: str) -> str | None:
    """Return the capability owning a module, excluding namespace packages."""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "limn" or parts[1] not in CAPABILITIES:
        return None
    return ".".join(parts[:2])


def sources(root: Path) -> dict[str, str]:
    """Read production modules only; colocated tests and vendor code are excluded."""
    result = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if "tests" in rel.parts or "vendor" in rel.parts or path.name.startswith("test_"):
            continue
        parts = rel.with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        result[".".join(("limn", *parts))] = path.read_text(encoding="utf-8")
    return result


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


def violations(
    code: Mapping[str, str],
    packages: set[str],
    crossings: CrossingNames | None = None,
    entrypoint_imports: EntrypointImports | None = None,
) -> list[str]:
    """Report private imports, shared-to-feature paths and cycles across every slice.

    Entry points may compose public operations. Within a slice, modules may use
    its private implementation. Paths through shared modules still count.
    """
    trees = {name: ast.parse(source, filename=name) for name, source in code.items()}
    slices = {slice_name for name in code if (slice_name := owner(name))}
    surfaces = {name: exports(trees[name]) if name in trees else None for name in slices}
    errors = [f"{name}: missing literal __all__" for name, surface in sorted(surfaces.items()) if surface is None]
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
            target_owner = owner(target)
            if target_owner and source_owner != target_owner:
                surface = surfaces.get(target_owner) or set()
                if base != target_owner or symbol not in surface:
                    errors.append(f"{name}: private import {base}" + (f".{symbol}" if symbol else ""))
                elif source_owner and crossings is not None:
                    approved = crossings.get((source_owner, target_owner), set())
                    if symbol not in approved:
                        errors.append(f"{name}: unapproved crossing {target_owner}.{symbol}")
                elif name in ENTRY_POINTS and entrypoint_imports is not None:
                    approved = entrypoint_imports.get(name, set())
                    if symbol not in approved:
                        errors.append(f"{name}: unapproved composition import {target_owner}.{symbol}")

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

    slice_graph: dict[str, set[str]] = {name: set() for name in slices}
    for name in code:
        origin = owner(name)
        for target, path in paths(name).items():
            destination = owner(target)
            if destination and destination != origin:
                if origin:
                    slice_graph[origin].add(destination)
                elif name not in ENTRY_POINTS:
                    errors.append("shared reaches feature: " + " -> ".join(path))

    def cycles(start: str, node: str, path: tuple[str, ...]) -> None:
        """Report a cycle once at its lexicographically first slice."""
        for target in sorted(slice_graph[node]):
            if target == start:
                errors.append("slice cycle: " + " -> ".join((*path, target)))
            elif target not in path and target > start:
                cycles(start, target, (*path, target))

    for name in sorted(slices):
        cycles(name, name, (name,))
    return sorted(set(errors))


def check(root: Path) -> list[str]:
    """Check exports and layout; empty discovery and unowned source files fail closed."""
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
    return sorted([*unowned, *violations(code, packages, CROSSING_NAMES, ENTRYPOINT_IMPORTS)])


def main() -> int:
    """Print boundary violations and return nonzero when the repository fails."""
    root = Path(__file__).resolve().parents[1] / "src" / "limn"
    errors = check(root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Feature boundaries: public exports, shared dependencies and slice cycles passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
