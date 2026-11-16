"""Check that each production module's file name gives it a role and that the module keeps that role's rules.

A module's role comes from its path below src/limn, never from a list of modules: the three entry points by path,
every `__init__.py` as its package's surface, then the basename (`rules.py`, or `<anything>_rules.py`) through
ROLE_WORDS, then the boundary package it sits in (PATH_ROLES). A module none of these name has no role, and that is a
violation. Each role in ROLES says which roles' modules it may import, whether it may perform I/O, use isinstance or
import limn.web, and whether its public signatures and fields are checked for primitive types. Three rules hold in
every role: no typing.cast, no `# type: ignore` or `# pyright:` comment, and no irrefutable `case` (`case _`, a bare
capture) unless its body is `assert_never(...)`.

Counts per module and rule are held to tools/fitness-baseline/<slice>.json, one file per top-level package of
src/limn (root.json for the files directly under it), so work on different slices edits different files. A count above
its baseline fails (new code meets the rules); a count below it fails too until --update lowers the baseline, and
--update refuses to raise one. --rename OLD=NEW carries a moved module's counts to its new path within one --update.

Run: uv run python tools/check_fitness.py [--update [--rename OLD=NEW ...]]
"""

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "limn"
BASELINE_DIR = ROOT / "tools" / "fitness-baseline"


IoRule = Literal["allowed", "delegated", "none"]


@dataclass(frozen=True)
class Role:
    """What a module of one role may do.

    imports: the roles whose modules it may import (None: any module). io: "allowed" may do I/O itself; "delegated"
    may not import an I/O module or call open/print/input or a clock itself, but may import modules that do; "none"
    reaches no I/O by any runtime import path. isinstance: it may call isinstance or issubclass (boundary parsing).
    web: it may import limn.web. primitives: its public signatures and class fields are checked for str, int and dict.
    """

    description: str
    imports: frozenset[str] | None
    io: IoRule
    isinstance: bool
    web: bool
    primitives: bool


# The roles every role may import: values, decisions, declarations and business-agnostic mechanisms. A role whose io
# is "none" still may not reach a platform module that performs I/O.
INNER = frozenset({"decision", "model", "protocol", "platform"})
MODEL = frozenset({"model", "protocol", "platform"})

ROLES: dict[str, Role] = {
    "entry": Role(
        "process entry point: creates resources, wires the slices",
        imports=None,
        io="allowed",
        isinstance=False,
        web=True,
        primitives=False,
    ),
    "surface": Role(
        "a package's declared surface: __all__ and lazy exports",
        imports=None,
        io="delegated",
        isinstance=False,
        web=True,
        primitives=False,
    ),
    "assembly": Role(
        "one slice's composition: services and routes wired",
        imports=None,
        io="allowed",
        isinstance=False,
        web=True,
        primitives=False,
    ),
    "decision": Role(
        "pure decisions, transitions and calculations",
        imports=INNER,
        io="none",
        isinstance=False,
        web=False,
        primitives=True,
    ),
    "model": Role(
        "domain values and state types",
        imports=MODEL,
        io="none",
        isinstance=False,
        web=False,
        primitives=True,
    ),
    "protocol": Role(
        "what a slice receives: Protocols and their values",
        imports=MODEL,
        io="none",
        isinstance=False,
        web=False,
        primitives=True,
    ),
    "parse": Role(
        "untrusted or stored data into typed values or refusals",
        imports=INNER | {"parse", "transport"},
        io="none",
        isinstance=True,
        web=True,
        primitives=False,
    ),
    "http": Role(
        "HTTP adapter: routes, request handling, response bodies",
        imports=INNER | {"http", "parse", "service", "transport", "runtime"},
        io="delegated",
        isinstance=False,
        web=True,
        primitives=False,
    ),
    "service": Role(
        "imperative shell: loads facts, decides, performs effects",
        imports=INNER | {"service", "persistence", "parse", "runtime"},
        io="allowed",
        isinstance=False,
        web=False,
        primitives=False,
    ),
    "persistence": Role(
        "reads and writes stored state",
        imports=INNER | {"persistence", "parse", "runtime"},
        io="allowed",
        isinstance=False,
        web=False,
        primitives=False,
    ),
    "platform": Role(
        "business-agnostic mechanism (src/limn/platform)",
        imports=MODEL | {"parse"},
        io="allowed",
        isinstance=False,
        web=False,
        primitives=False,
    ),
    "transport": Role(
        "the HTTP transport (src/limn/web)",
        imports=INNER | {"transport", "http", "parse", "runtime", "persistence"},
        io="allowed",
        isinstance=False,
        web=True,
        primitives=False,
    ),
    "runtime": Role(
        "run settings and per-run resources (src/limn/runtime)",
        imports=INNER | {"runtime", "parse", "persistence"},
        io="allowed",
        isinstance=False,
        web=False,
        primitives=False,
    ),
}

ENTRY_POINTS = {"server.py", "cli.py", "__main__.py"}
# Basename word -> role; `<word>.py` and `<anything>_<word>.py` both take the role.
ROLE_WORDS = {
    "rules": "decision",
    "values": "model",
    "model": "model",
    "needs": "protocol",
    "contracts": "protocol",
    "input": "parse",
    "parse": "parse",
    "http": "http",
    "routes": "http",
    "answer": "http",
    "service": "service",
    "run": "service",
    "store": "persistence",
    "queries": "persistence",
    "application": "assembly",
}
# Boundary package -> the role of a module in it whose basename names no role.
PATH_ROLES = {"platform": "platform", "web": "transport", "runtime": "runtime"}

# Standard-library modules whose import means I/O, a clock, randomness or process state.
IO_MODULES = frozenset(
    {
        "asyncio",
        "concurrent",
        "fcntl",
        "glob",
        "gzip",
        "http.client",
        "http.server",
        "io",
        "logging",
        "mmap",
        "multiprocessing",
        "os",
        "queue",
        "random",
        "secrets",
        "select",
        "selectors",
        "shutil",
        "signal",
        "socket",
        "socketserver",
        "sqlite3",
        "subprocess",
        "sys",
        "tarfile",
        "tempfile",
        "threading",
        "time",
        "urllib.request",
        "uuid",
        "zipfile",
    }
)
IO_CALLS = frozenset({"open", "print", "input"})
CLOCK_METHODS = frozenset({"now", "utcnow", "today"})  # datetime.now(), date.today()
CLOCKS = frozenset({"datetime", "date"})

# The primitive types a decision, model or protocol module may not name for a domain concept. Any is not here:
# basedpyright's reportExplicitAny owns it in every module.
PRIMITIVES = frozenset({"str", "int", "dict", "Dict"})
# The reviewed aliases that say "this str is not a domain concept", qualified name -> why. Each entry is a design
# decision; an alias defined anywhere else is expanded, so it does not hide its primitive.
PRIMITIVE_ALIASES = {
    "limn.platform.text.FreeText": "text people write that no code reads for meaning: notes, replies, reasons",
}

RULES = (
    "role-unknown",
    "role-imports",
    "io",
    "web-import",
    "isinstance",
    "cast",
    "ignore-comment",
    "wildcard-case",
    "primitive",
)
IGNORE_COMMENT = re.compile(r"#\s*(?:type:\s*ignore|pyright\s*:)")


@dataclass(frozen=True)
class Violation:
    """One broken rule: the module's path below src/limn, the rule, the line, and what broke it."""

    path: str
    rule: str
    line: int
    detail: str

    def __str__(self) -> str:
        """The `path:line: rule: detail` form the command prints."""
        return f"src/limn/{self.path}:{self.line}: {self.rule}: {self.detail}"


def role_of(path: str) -> str | None:
    """The role a module's path below src/limn gives it, or None when its name and place give none.

    Precedence: an entry point by path, any `__init__.py` as a surface, the basename's role word, the boundary package.
    """
    parts = path.split("/")
    name = parts[-1]
    if len(parts) == 1 and name in ENTRY_POINTS:
        return "entry"
    if name == "__init__.py":
        return "surface"
    stem = name.removesuffix(".py")
    for word, role in ROLE_WORDS.items():
        if stem == word or stem.endswith("_" + word):
            return role
    if len(parts) > 1 and parts[0] in PATH_ROLES:
        return PATH_ROLES[parts[0]]
    return None


def slice_of(path: str) -> str:
    """The baseline file a module's counts live in: its top-level package, or root for files directly in src/limn."""
    return path.split("/")[0] if "/" in path else "root"


def dotted(path: str) -> str:
    """The import name of a module path below src/limn."""
    parts = ["limn", *path.removesuffix(".py").split("/")]
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass(frozen=True)
class Import:
    """One import of a limn module or a standard-library module: its target, line, and whether it runs at runtime."""

    target: str
    line: int
    runtime: bool


def type_checking_lines(tree: ast.Module) -> set[int]:
    """The line numbers of statements under `if TYPE_CHECKING:` (or `typing.TYPE_CHECKING`), which never run."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = test.id if isinstance(test, ast.Name) else test.attr if isinstance(test, ast.Attribute) else ""
            if name == "TYPE_CHECKING":
                for child in node.body:
                    lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    return lines


def imports_of(module: str, tree: ast.Module, is_package: bool, known: set[str]) -> list[Import]:
    """Every import in tree resolved to a module: a limn module in known (the deepest one the statement names), or the
    full dotted name of any other module. Relative imports resolve against module."""
    hidden = type_checking_lines(tree)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append(Import(_deepest(alias.name, known), node.lineno, node.lineno not in hidden))
        elif isinstance(node, ast.ImportFrom):
            base = absolute(module, is_package, node)
            for alias in node.names:
                full = f"{base}.{alias.name}"
                target = full if full in known else _deepest(base, known)
                found.append(Import(target, node.lineno, node.lineno not in hidden))
    return found


def absolute(module: str, is_package: bool, node: ast.ImportFrom) -> str:
    """The absolute module a `from ... import` in module names, resolving a relative one against its package."""
    base = node.module or ""
    if not node.level:
        return base
    package = module if is_package else module.rpartition(".")[0]
    parent = package.split(".")[: len(package.split(".")) - node.level + 1]
    return ".".join((*parent, *base.split("."))).rstrip(".")


def _deepest(name: str, known: set[str]) -> str:
    """The longest prefix of a dotted name that is a known limn module, else the name itself."""
    parts = name.split(".")
    for end in range(len(parts), 0, -1):
        if ".".join(parts[:end]) in known:
            return ".".join(parts[:end])
    return name


def is_io_module(name: str) -> bool:
    """Whether importing a standard-library module (or a name from it) means I/O: the module or a parent is listed."""
    return any(name == listed or name.startswith(listed + ".") for listed in IO_MODULES)


def parents(module: str) -> Iterator[str]:
    """The packages Python initializes before module: limn, limn.pins, ... (module itself excluded)."""
    parts = module.split(".")
    for end in range(1, len(parts)):
        yield ".".join(parts[:end])


def effectful(graph: Mapping[str, Sequence[Import]]) -> dict[str, tuple[str, str]]:
    """Each limn module whose import performs I/O, mapped to the module that does it and the I/O module it imports: a
    runtime import of an I/O module, directly or through other limn modules and the package initializers they run.
    Imports under TYPE_CHECKING do not count."""
    causes: dict[str, tuple[str, str]] = {}
    for module, found in graph.items():
        direct = [imp.target for imp in found if imp.runtime and is_io_module(imp.target)]
        if direct:
            causes[module] = (module, direct[0])
    changed = True
    while changed:
        changed = False
        for module, found in graph.items():
            if module in causes:
                continue
            reached = [
                target
                for imp in found
                if imp.runtime
                for target in (*parents(imp.target), imp.target)
                if target in causes and target != module
            ]
            if reached:
                causes[module] = causes[reached[0]]
                changed = True
    return causes


def _effect(target: str, cause: tuple[str, str]) -> str:
    """Say why importing target performs I/O."""
    owner, io_module = cause
    return (
        f"imports {target}, which imports {io_module}"
        if owner == target
        else f"imports {target}, which reaches {owner} (imports {io_module})"
    )


class Aliases:
    """The module-level type aliases of every module, so a primitive behind an alias is still seen.

    An alias is `X: TypeAlias = ...`, or `X = ...` where X is CapWords and the value is a type expression (a
    subscript, a `|` union, or a bare primitive). NewType makes a distinct type and is not an alias. trees maps module
    names to their syntax; packages names those that are packages, for relative imports.
    """

    def __init__(self, trees: Mapping[str, ast.Module], packages: set[str]) -> None:
        """Collect each module's aliases and the names it imports from other modules."""
        self.values: dict[str, tuple[str, ast.expr]] = {}
        self.imported: dict[str, dict[str, str]] = {}
        for module, tree in trees.items():
            names: dict[str, str] = {}
            for node in tree.body:
                if isinstance(node, ast.ImportFrom):
                    base = absolute(module, module in packages, node)
                    for alias in node.names:
                        names[alias.asname or alias.name] = f"{base}.{alias.name}"
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                    if _names(node.annotation) & {"TypeAlias"}:
                        self.values[f"{module}.{node.target.id}"] = (module, node.value)
                elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    target = node.targets[0].id
                    if _capwords(target) and _type_expression(node.value):
                        self.values[f"{module}.{target}"] = (module, node.value)
            self.imported[module] = names

    def qualify(self, module: str, name: str) -> str:
        """The qualified name a bare name in module refers to, following imports and re-imports to where it is
        defined: an import, else a definition in module itself."""
        qualified = self.imported.get(module, {}).get(name, f"{module}.{name}")
        for _ in range(8):  # a re-export chain; a cycle or a deeper chain stops at the last name reached
            owner, _sep, symbol = qualified.rpartition(".")
            following = self.imported.get(owner, {}).get(symbol)
            if following is None or qualified in self.values:
                break
            qualified = following
        return qualified

    def primitives(self, module: str, node: ast.expr, seen: frozenset[str] = frozenset()) -> set[str]:
        """The primitive type names node mentions, read in module, through aliases (a reviewed alias stops there)."""
        found: set[str] = set()
        for name, inner in _annotation_names(node):
            if inner in PRIMITIVES:
                found.add(inner)
                continue
            if name is None:
                continue
            qualified = self.qualify(module, name)
            if qualified in PRIMITIVE_ALIASES or qualified in seen:
                continue
            if qualified in self.values:
                home, value = self.values[qualified]
                found |= {f"{p} (via {name})" for p in self.primitives(home, value, seen | {qualified})}
        return found


def _capwords(name: str) -> bool:
    """A CapWords name (an alias candidate), not an ALL_CAPS constant."""
    return name[:1].isupper() and not name.isupper()


def _type_expression(node: ast.expr) -> bool:
    """Whether an assigned value reads as a type: a subscript, a `|` union, or a bare primitive name."""
    if isinstance(node, ast.Subscript):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return True
    return isinstance(node, ast.Name) and node.id in PRIMITIVES


def _names(node: ast.expr) -> set[str]:
    """Every Name id and Attribute attr in an expression."""
    return {
        n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(node) if isinstance(n, ast.Name | ast.Attribute)
    }


def _annotation_names(node: ast.expr) -> Iterator[tuple[str | None, str]]:
    """The type names an annotation uses, as (name to resolve, the name itself); Literal values and Annotated metadata
    are skipped, and a string annotation is parsed."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            parsed = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return
        yield from _annotation_names(parsed)
    elif isinstance(node, ast.Name):
        yield node.id, node.id
    elif isinstance(node, ast.Attribute):
        yield None, node.attr
    elif isinstance(node, ast.Subscript):
        head = node.value.id if isinstance(node.value, ast.Name) else getattr(node.value, "attr", "")
        if head == "Literal":
            return
        yield from _annotation_names(node.value)
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        for arg in args[:1] if head == "Annotated" else args:
            yield from _annotation_names(arg)
    elif isinstance(node, ast.BinOp):
        yield from _annotation_names(node.left)
        yield from _annotation_names(node.right)
    elif isinstance(node, ast.Tuple | ast.List):
        for element in node.elts:
            yield from _annotation_names(element)


def annotation_slots(tree: ast.Module) -> Iterator[tuple[str, ast.expr]]:
    """The annotations of a module's public surface, as (where, annotation): parameters and returns of public
    functions, and of public methods (and __init__, __call__, __new__) of public classes, and the fields of public
    classes. Names starting with an underscore are private; other dunder methods have fixed signatures."""

    def function(where: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[tuple[str, ast.expr]]:
        """The annotated parameters and return of one function."""
        arguments = node.args
        for arg in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, arguments.vararg, arguments.kwarg):
            if arg is not None and arg.annotation is not None:
                yield f"{where} parameter {arg.arg}", arg.annotation
        if node.returns is not None:
            yield f"{where} return", node.returns

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
            yield from function(node.name, node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for child in node.body:
                if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                    if not child.target.id.startswith("_"):
                        yield f"{node.name}.{child.target.id}", child.annotation
                elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    public = not child.name.startswith("_") or child.name in {"__init__", "__call__", "__new__"}
                    if public:
                        yield from function(f"{node.name}.{child.name}", child)


def _irrefutable(pattern: ast.pattern) -> bool:
    """Whether a case pattern matches every subject: `_`, a bare capture, or an or-pattern holding one."""
    if isinstance(pattern, ast.MatchAs):
        return pattern.pattern is None or _irrefutable(pattern.pattern)
    if isinstance(pattern, ast.MatchOr):
        return any(_irrefutable(p) for p in pattern.patterns)
    return False


def _asserts_never(body: Sequence[ast.stmt]) -> bool:
    """Whether a case body is exactly one `assert_never(...)` call."""
    if len(body) != 1 or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Call):
        return False
    func = body[0].value.func
    return (func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")) == "assert_never"


def scan(sources: Mapping[str, str]) -> list[Violation]:
    """Every violation in a set of production modules, keyed by path below src/limn (`pins/model.py`)."""
    trees = {path: ast.parse(text, filename=path) for path, text in sources.items()}
    modules = {dotted(path): path for path in sources}
    known = set(modules)
    graph = {
        dotted(path): imports_of(dotted(path), tree, path.endswith("__init__.py"), known)
        for path, tree in trees.items()
    }
    effects = effectful(graph)
    packages = {dotted(path) for path in sources if path.endswith("__init__.py")}
    aliases = Aliases({dotted(path): tree for path, tree in trees.items()}, packages)
    found: list[Violation] = []
    for path, tree in trees.items():
        module = dotted(path)
        name = role_of(path)
        role = ROLES[name] if name else None
        if role is None:
            found.append(Violation(path, "role-unknown", 1, "the file name and place name no role (ROLE_WORDS)"))
        for imp in dict.fromkeys(graph[module]):  # one statement naming several names counts once
            if imp.target in modules:
                target_role = role_of(modules[imp.target])
                if role is not None and role.imports is not None and target_role not in role.imports:
                    found.append(
                        Violation(
                            path, "role-imports", imp.line, f"{name} imports {imp.target} ({target_role or 'no role'})"
                        )
                    )
                if imp.target.startswith("limn.web") and (role is None or not role.web):
                    found.append(Violation(path, "web-import", imp.line, f"{name or 'no role'} imports {imp.target}"))
                if role is not None and role.io == "none" and imp.runtime and imp.target in effects:
                    found.append(Violation(path, "io", imp.line, _effect(imp.target, effects[imp.target])))
            elif role is not None and role.io != "allowed" and imp.runtime and is_io_module(imp.target):
                found.append(Violation(path, "io", imp.line, f"imports {imp.target}"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
                if called in {"isinstance", "issubclass"} and isinstance(func, ast.Name):
                    if role is None or not role.isinstance:
                        found.append(Violation(path, "isinstance", node.lineno, f"{called}() outside a parse module"))
                elif called == "cast" and (
                    isinstance(func, ast.Name) or (isinstance(func.value, ast.Name) and func.value.id == "typing")
                ):
                    found.append(Violation(path, "cast", node.lineno, "typing.cast"))
                elif role is not None and role.io != "allowed":
                    if isinstance(func, ast.Name) and called in IO_CALLS:
                        found.append(Violation(path, "io", node.lineno, f"calls {called}()"))
                    elif isinstance(func, ast.Attribute) and called in CLOCK_METHODS and _names(func.value) & CLOCKS:
                        found.append(Violation(path, "io", node.lineno, f"reads the clock ({called}())"))
            elif isinstance(node, ast.match_case) and node.guard is None and _irrefutable(node.pattern):
                if not _asserts_never(node.body):
                    line = node.pattern.lineno
                    found.append(Violation(path, "wildcard-case", line, "an irrefutable case without assert_never"))
        for token in tokenize.generate_tokens(io.StringIO(sources[path]).readline):
            if token.type == tokenize.COMMENT and IGNORE_COMMENT.search(token.string):
                found.append(Violation(path, "ignore-comment", token.start[0], token.string.strip()))
        if role is not None and role.primitives:
            for where, annotation in annotation_slots(tree):
                hits = aliases.primitives(module, annotation)
                if hits:
                    found.append(Violation(path, "primitive", annotation.lineno, f"{where}: {', '.join(sorted(hits))}"))
    return sorted(found, key=lambda v: (v.path, v.line, v.rule, v.detail))


def stale_aliases(sources: Mapping[str, str]) -> list[str]:
    """Each PRIMITIVE_ALIASES entry that names no module-level alias of a primitive type in sources."""
    packages = {dotted(path) for path in sources if path.endswith("__init__.py")}
    aliases = Aliases({dotted(path): ast.parse(text, filename=path) for path, text in sources.items()}, packages)
    return [
        f"PRIMITIVE_ALIASES lists {name}, which is not an alias of a primitive type"
        for name in sorted(PRIMITIVE_ALIASES)
        if name not in aliases.values or not _names(aliases.values[name][1]) & PRIMITIVES
    ]


Counts = dict[str, dict[str, int]]


def count(violations: Sequence[Violation]) -> Counts:
    """Violations per module path and rule, without zero entries."""
    tally = Counter((v.path, v.rule) for v in violations)
    result: Counts = {}
    for (path, rule), n in sorted(tally.items()):
        result.setdefault(path, {})[rule] = n
    return result


def compare(counts: Counts, baseline: Counts) -> list[str]:
    """Each module and rule whose count differs from its baseline (0 when unlisted), saying which way; empty when equal."""
    out = []
    for path in sorted(set(counts) | set(baseline)):
        for rule in RULES:
            now, base = counts.get(path, {}).get(rule, 0), baseline.get(path, {}).get(rule, 0)
            if now > base:
                out.append(f"src/limn/{path}: {rule} {now}, baseline {base} - new code must keep its role's rules")
            elif now < base:
                out.append(f"src/limn/{path}: {rule} {now}, baseline {base} - lower the baseline (--update)")
    return out


def renamed(baseline: Counts, renames: Mapping[str, str]) -> tuple[Counts, list[str]]:
    """The baseline with each OLD path's counts moved to NEW, and the refusals: an OLD that the baseline lacks or a NEW
    it already holds."""
    moved = {path: dict(rules) for path, rules in baseline.items()}
    problems = []
    for old, new in renames.items():
        if old not in moved:
            problems.append(f"--rename {old}={new}: the baseline lists no {old}")
        elif new in moved:
            problems.append(f"--rename {old}={new}: the baseline already lists {new}")
        else:
            moved[new] = moved.pop(old)
    return moved, problems


def _raised(counts: Counts, baseline: Counts) -> list[tuple[str, str]]:
    """The (module path, rule) pairs whose count is above the baseline."""
    return [
        (path, rule)
        for path in sorted(counts)
        for rule in RULES
        if counts[path].get(rule, 0) > baseline.get(path, {}).get(rule, 0)
    ]


def lowered(counts: Counts, baseline: Counts) -> list[str]:
    """The refusals of writing counts as the new baseline: one for every module and rule whose count is above its
    baseline. Empty means counts only lower it."""
    return [
        f"src/limn/{path}: {rule} {counts[path][rule]}, baseline {baseline.get(path, {}).get(rule, 0)} - cannot raise"
        for path, rule in _raised(counts, baseline)
    ]


def read_baseline(directory: Path) -> Counts:
    """Every slice file in directory merged into one map of module path -> rule -> count."""
    merged: Counts = {}
    for file in sorted(directory.glob("*.json")):
        merged.update(json.loads(file.read_text(encoding="utf-8")))
    return merged


def write_baseline(directory: Path, counts: Counts) -> list[Path]:
    """Write counts as one file per slice, removing slice files that hold no count; returns the files written."""
    directory.mkdir(parents=True, exist_ok=True)
    slices: dict[str, Counts] = {}
    for path, rules in sorted(counts.items()):
        slices.setdefault(slice_of(path), {})[path] = dict(sorted(rules.items(), key=lambda item: RULES.index(item[0])))
    written = []
    for file in directory.glob("*.json"):
        if file.stem not in slices:
            file.unlink()
    for name, content in sorted(slices.items()):
        file = directory / f"{name}.json"
        text = json.dumps(content, indent=2) + "\n"
        if not file.exists() or file.read_text(encoding="utf-8") != text:
            file.write_text(text, encoding="utf-8")
            written.append(file)
    return written


def production_sources(root: Path) -> dict[str, str]:
    """The production modules below root by relative path: colocated tests and vendored code are not production."""
    result = {}
    for file in sorted(root.rglob("*.py")):
        rel = file.relative_to(root)
        if "vendor" in rel.parts or "tests" in rel.parts or rel.name.startswith("test_"):
            continue
        result[rel.as_posix()] = file.read_text(encoding="utf-8")
    return result


def parse_renames(pairs: Sequence[str]) -> dict[str, str]:
    """The OLD=NEW values of --rename as paths below src/limn; a malformed value exits with a message."""
    renames = {}
    for value in pairs:
        old, sep, new = value.partition("=")
        if not sep or not old or not new:
            raise SystemExit(f"--rename takes OLD=NEW, got {value!r}")
        renames[old.removeprefix("src/limn/")] = new.removeprefix("src/limn/")
    return renames


def main(argv: Sequence[str]) -> int:
    """Compare the counts with the baseline (exit 1 on any difference); with --update lower the baseline to them."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true", help="lower the baseline to the current counts")
    parser.add_argument(
        "--rename", action="append", default=[], metavar="OLD=NEW", help="carry a moved module's counts"
    )
    args = parser.parse_args(argv)
    sources = production_sources(SOURCE)
    if not sources:
        print(f"no production modules found under {SOURCE}", file=sys.stderr)
        return 1
    stale = stale_aliases(sources)
    for line in stale:
        print(line, file=sys.stderr)
    if stale:
        return 1
    violations = scan(sources)
    counts = count(violations)
    baseline = read_baseline(BASELINE_DIR)
    if args.update:
        baseline, problems = renamed(baseline, parse_renames(args.rename))
        if not problems:
            problems = lowered(counts, baseline)
        for line in problems:
            print(line, file=sys.stderr)
        if problems:
            print("baseline not written: --update only lowers counts", file=sys.stderr)
            return 1
        written = write_baseline(BASELINE_DIR, counts)
        print(f"lowered {len(written)} baseline file(s): {sum(sum(r.values()) for r in counts.values())} violations")
        return 0
    if args.rename:
        print("--rename only applies with --update", file=sys.stderr)
        return 1
    problems = compare(counts, baseline)
    for line in problems:
        print(line, file=sys.stderr)
    raised = {(path, rule) for path, rule in _raised(counts, baseline)}
    for v in violations:
        if (v.path, v.rule) in raised:
            print(f"  {v}", file=sys.stderr)
    if problems:
        return 1
    unknown = sorted(path for path in sources if role_of(path) is None)
    total = sum(sum(rules.values()) for rules in counts.values())
    print(
        f"Fitness: {len(sources)} modules, {len(sources) - len(unknown)} with a role; "
        f"{total} recorded violations, as the baseline says"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
