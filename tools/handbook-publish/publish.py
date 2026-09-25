#!/usr/bin/env python3
# publisher-schema: 1; plugin-commit: e3aeedd68a6317df6abaff8bdb7a7cc6ae91c764
"""Publish a constrained Markdown System Handbook through Pandoc and Chromium."""

import argparse
import base64
import copy
import glob
import hashlib
import html
import importlib.metadata
import json
import mimetypes
import os
import re
import signal
import struct
import string
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, unquote, urlsplit, urlunsplit


CATALOG_START = "<!-- handbook-catalog:start -->"
CATALOG_END = "<!-- handbook-catalog:end -->"
FILEMAP_START = "<!-- handbook-filemap:start -->"
FILEMAP_END = "<!-- handbook-filemap:end -->"
CATALOG_HEADER = ("role", "file", "responsibility", "read or update when")
FILEMAP_HEADER = ("경로 패턴", "책임", "수정 trigger", "갱신 주체")
REQUIRED_ROLES = ("purpose", "architecture", "verification")
CALLOUT_LABELS = {"한눈에", "핵심", "참고", "주의", "예시"}
CONFIG_KEYS = {
    "project_root",
    "title",
    "author",
    "language",
    "source_url",
    "font",
    "tools",
}
FONT_KEYS = {"family", "path", "sha256"}
TOOL_KEYS = {"python_min", "pandoc", "playwright", "chromium"}
IMAGE_EXTENSIONS = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
FONT_ALIAS = "HandbookPinnedFont"
PDF_WORKER_TIMEOUT = 90
PDF_WORKER_GRACE = 2
SHORT_INLINE_CODE_MAX = 20
TABLE_ALIGNMENT_CLASSES = {
    "AlignDefault": "table-align-default",
    "AlignLeft": "table-align-left",
    "AlignCenter": "table-align-center",
    "AlignRight": "table-align-right",
}


class Diagnostic:
    def __init__(self, path, location, kind, hint):
        # type: (Optional[Path], Optional[str], str, str) -> None
        self.path = path
        self.location = location
        self.kind = kind
        self.hint = hint

    def format(self):
        # type: () -> str
        prefix = str(self.path) if self.path is not None else "publisher"
        if self.location:
            prefix += ":" + self.location
        return "{}: {}: {}".format(prefix, self.kind, self.hint)


class PublisherError(Exception):
    def __init__(self, diagnostics):
        # type: (Sequence[Diagnostic]) -> None
        super().__init__("; ".join(item.format() for item in diagnostics))
        self.diagnostics = list(diagnostics)


class StaticCheckError(PublisherError):
    pass


class RenderError(PublisherError):
    pass


class UnsafeIOError(PublisherError):
    pass


class ToolFailure(Exception):
    pass


class Config:
    def __init__(
        self,
        project_root,
        title,
        author,
        language,
        source_url,
        font_family,
        font_path,
        font_sha256,
        python_min,
        pandoc_version,
        playwright_version,
        chromium_version,
    ):
        self.project_root = project_root
        self.title = title
        self.author = author
        self.language = language
        self.source_url = source_url
        self.font_family = font_family
        self.font_path = font_path
        self.font_sha256 = font_sha256
        self.python_min = python_min
        self.pandoc_version = pandoc_version
        self.playwright_version = playwright_version
        self.chromium_version = chromium_version


class Chapter:
    def __init__(self, path, roles, ast, headings, images):
        self.path = path
        self.roles = roles
        self.ast = ast
        self.headings = headings
        self.images = images


class CheckedBook:
    def __init__(self, index_path, config_path, config, chapters, role_paths):
        self.index_path = index_path
        self.config_path = config_path
        self.config = config
        self.chapters = chapters
        self.role_paths = role_paths


def _diagnostic(path, kind, hint, location=None):
    return Diagnostic(path, location, kind, hint)


def _run(args, input_bytes=None, cwd=None):
    # type: (Sequence[str], Optional[bytes], Optional[Path]) -> subprocess.CompletedProcess
    command = [str(item) for item in args]
    try:
        result = subprocess.run(
            command,
            input=input_bytes,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as error:
        raise ToolFailure("{}: {}".format(command[0], error)) from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ToolFailure(message or "{} exited {}".format(command[0], result.returncode))
    return result


def _walk(value):
    if isinstance(value, dict):
        if "t" in value:
            yield value
        for child in value.values():
            for node in _walk(child):
                yield node
    elif isinstance(value, list):
        for child in value:
            for node in _walk(child):
                yield node


def _within(path, root):
    # type: (Path, Path) -> bool
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_within(base, raw, root):
    # type: (Path, str, Path) -> Path
    candidate = Path(unquote(raw))
    if candidate.is_absolute():
        raise ValueError("absolute path is not allowed")
    resolved = (base / candidate).resolve()
    if not _within(resolved, root.resolve()):
        raise ValueError("path escapes project root")
    return resolved


def _case_exact(base, raw):
    # type: (Path, str) -> bool
    current = base
    for part in Path(unquote(raw)).parts:
        if part in (".", ""):
            continue
        if part == "..":
            current = current.parent
            continue
        try:
            names = {entry.name for entry in current.iterdir()}
        except OSError:
            return True
        if part not in names:
            return False
        current = current / part
    return True


def _marker_body(lines, start, end, path, label, diagnostics):
    starts = [position for position, line in enumerate(lines) if line == start]
    ends = [position for position, line in enumerate(lines) if line == end]
    if len(starts) != 1 or len(ends) != 1 or (starts and ends and starts[0] >= ends[0]):
        diagnostics.append(
            _diagnostic(path, "{} marker".format(label), "use exactly one ordered start/end marker pair")
        )
        return []
    return [(position + 1, lines[position]) for position in range(starts[0] + 1, ends[0]) if lines[position].strip()]


def _pipe_table(body, expected_header, path, label, diagnostics):
    if len(body) < 3:
        diagnostics.append(_diagnostic(path, "{} table".format(label), "add a header, separator, and at least one row"))
        return []

    parsed = []
    for line_number, line in body:
        if not line.startswith("|") or not line.endswith("|"):
            diagnostics.append(_diagnostic(path, "{} row".format(label), "each row must begin and end with |", str(line_number)))
            continue
        cells = tuple(cell.strip() for cell in line[1:-1].split("|"))
        if len(cells) != 4:
            diagnostics.append(_diagnostic(path, "{} row".format(label), "each row must have exactly four simple cells", str(line_number)))
            continue
        parsed.append((line_number, cells))
    if not parsed:
        return []
    if parsed[0][1] != expected_header:
        diagnostics.append(_diagnostic(path, "{} header".format(label), "expected: {}".format(" | ".join(expected_header)), str(parsed[0][0])))
    separator = parsed[1][1] if len(parsed) > 1 else ()
    if len(separator) != 4 or any(re.fullmatch(r":?-{3,}:?", cell) is None for cell in separator):
        diagnostics.append(_diagnostic(path, "{} separator".format(label), "use four Markdown separator cells", str(parsed[1][0]) if len(parsed) > 1 else None))
    return parsed[2:]


def _parse_frontmatter(lines, path, diagnostics):
    if not lines or lines[0] != "---":
        diagnostics.append(_diagnostic(path, "frontmatter", "start with the closed Markdown frontmatter"))
        return
    try:
        end = lines.index("---", 1)
    except ValueError:
        diagnostics.append(_diagnostic(path, "frontmatter", "close frontmatter with ---"))
        return
    values = {}
    for line_number, line in enumerate(lines[1:end], 2):
        match = re.fullmatch(r"([a-z_]+): (.+)", line)
        if match is None or match.group(1) in values:
            diagnostics.append(_diagnostic(path, "frontmatter", "use each supported scalar key exactly once", str(line_number)))
            continue
        values[match.group(1)] = match.group(2)
    if set(values) != {"handbook_format", "catalog_schema"}:
        diagnostics.append(_diagnostic(path, "frontmatter keys", "only handbook_format and catalog_schema are allowed"))
    if values.get("handbook_format") != "markdown":
        diagnostics.append(_diagnostic(path, "handbook_format", "set handbook_format: markdown"))
    if values.get("catalog_schema") != "1":
        diagnostics.append(_diagnostic(path, "catalog_schema", "set catalog_schema: 1"))


def _parse_config(path, diagnostics):
    # type: (Path, List[Diagnostic]) -> Optional[Config]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        diagnostics.append(_diagnostic(path, "book.json JSON", "write valid UTF-8 JSON ({})".format(error)))
        return None
    if not isinstance(raw, dict):
        diagnostics.append(_diagnostic(path, "config type", "book.json must be an object"))
        return None
    missing = CONFIG_KEYS - set(raw)
    unknown = set(raw) - CONFIG_KEYS
    if missing:
        diagnostics.append(_diagnostic(path, "missing config key", ", ".join(sorted(missing))))
    if unknown:
        diagnostics.append(_diagnostic(path, "unknown config key", ", ".join(sorted(unknown))))
    font = raw.get("font")
    tools = raw.get("tools")
    if not isinstance(font, dict):
        diagnostics.append(_diagnostic(path, "font config", "font must be an object"))
        font = {}
    if not isinstance(tools, dict):
        diagnostics.append(_diagnostic(path, "tools config", "tools must be an object"))
        tools = {}
    for value, expected, label in ((font, FONT_KEYS, "font"), (tools, TOOL_KEYS, "tools")):
        missing_nested = expected - set(value)
        unknown_nested = set(value) - expected
        if missing_nested:
            diagnostics.append(_diagnostic(path, "missing {} key".format(label), ", ".join(sorted(missing_nested))))
        if unknown_nested:
            diagnostics.append(_diagnostic(path, "unknown {} key".format(label), ", ".join(sorted(unknown_nested))))
    scalar_names = ("project_root", "title", "author", "language", "source_url")
    for name in scalar_names:
        if name in raw and (not isinstance(raw[name], str) or not raw[name]):
            diagnostics.append(_diagnostic(path, "config field", "{} must be a non-empty string".format(name)))
    for name in FONT_KEYS:
        if name in font and (not isinstance(font[name], str) or not font[name]):
            diagnostics.append(_diagnostic(path, "font field", "{} must be a non-empty string".format(name)))
    for name in TOOL_KEYS:
        if name in tools and (not isinstance(tools[name], str) or not tools[name]):
            diagnostics.append(_diagnostic(path, "tool field", "{} must be a non-empty string".format(name)))
    if missing or unknown or set(font) != FONT_KEYS or set(tools) != TOOL_KEYS:
        return None
    if any(not isinstance(raw.get(name), str) or not raw.get(name) for name in scalar_names):
        return None
    if any(not isinstance(font.get(name), str) or not font.get(name) for name in FONT_KEYS):
        return None
    if any(not isinstance(tools.get(name), str) or not tools.get(name) for name in TOOL_KEYS):
        return None
    if re.fullmatch(r"[0-9a-f]{64}", font["sha256"]) is None:
        diagnostics.append(_diagnostic(path, "font SHA-256", "use 64 lowercase hexadecimal characters"))
    source = urlsplit(raw["source_url"])
    if source.scheme != "https" or not source.netloc or source.query or source.fragment:
        diagnostics.append(_diagnostic(path, "source URL", "use an HTTPS repository base URL without query or fragment"))
    if re.fullmatch(r"[0-9]+\.[0-9]+", tools["python_min"]) is None:
        diagnostics.append(_diagnostic(path, "Python version", "python_min must be major.minor"))
    project_root = (path.parent / raw["project_root"]).resolve()
    font_path = (path.parent / font["path"]).resolve()
    if not project_root.is_dir():
        diagnostics.append(_diagnostic(path, "project root", "project_root must resolve to an existing directory"))
    if not _within(font_path, project_root):
        diagnostics.append(_diagnostic(path, "font path", "font path escapes project root"))
    return Config(
        project_root,
        raw["title"],
        raw["author"],
        raw["language"],
        raw["source_url"],
        font["family"],
        font_path,
        font["sha256"],
        tools["python_min"],
        tools["pandoc"],
        tools["playwright"],
        tools["chromium"],
    )


def _tool_version(command):
    result = _run([command, "--version"])
    first = result.stdout.decode("utf-8", errors="replace").splitlines()
    if not first:
        raise ToolFailure("{} --version returned no output".format(command))
    match = re.search(r"(?:^|\s)([0-9]+(?:\.[0-9]+)+)(?:\s|$)", first[0])
    if match is None:
        raise ToolFailure("cannot parse {} version from {!r}".format(command, first[0]))
    return match.group(1)


def _inline_text(inlines):
    pieces = []
    for node in inlines:
        kind = node.get("t")
        if kind in ("Str", "Code", "Math"):
            content = node.get("c", "")
            if isinstance(content, list):
                content = content[-1]
            pieces.append(str(content))
        elif kind in ("Space", "SoftBreak", "LineBreak"):
            pieces.append(" ")
        elif isinstance(node.get("c"), list):
            pieces.append(_inline_text([item for item in node["c"] if isinstance(item, dict)]))
    return "".join(pieces)


def _github_slug(inlines):
    text = _inline_text(inlines).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return re.sub(r" +", "-", text)


def _callout_label(node):
    if node.get("t") != "BlockQuote" or not node.get("c"):
        return None
    first = node["c"][0]
    if first.get("t") != "Para" or len(first.get("c", [])) != 1:
        return None
    strong = first["c"][0]
    if strong.get("t") != "Strong" or len(strong.get("c", [])) != 1:
        return None
    label = strong["c"][0]
    if label.get("t") == "Str" and label.get("c") in CALLOUT_LABELS:
        return label["c"]
    return None


def _looks_like_callout(node):
    if node.get("t") != "BlockQuote" or not node.get("c"):
        return False
    first = node["c"][0]
    if first.get("t") not in ("Para", "Plain"):
        return False
    inlines = first.get("c", [])
    if not inlines or inlines[0].get("t") != "Strong":
        return False
    return _inline_text(inlines[0].get("c", [])) in CALLOUT_LABELS


def _table_is_simple(node):
    try:
        _attr, _caption, _colspec, head, bodies, foot = node["c"]
        head_rows = head[1]
        foot_rows = foot[1]
        rows = list(head_rows) + list(foot_rows)
        for body in bodies:
            rows.extend(body[2])
            rows.extend(body[3])
        if len(head_rows) != 1 or foot_rows:
            return False
        for row in rows:
            for cell in row[1]:
                if cell[2] != 1 or cell[3] != 1 or len(cell[4]) != 1:
                    return False
                if cell[4][0].get("t") not in ("Plain", "Para"):
                    return False
                if any(child.get("t") in ("RawInline", "LineBreak", "Image") for child in _walk(cell[4])):
                    return False
    except (IndexError, TypeError, ValueError):
        return False
    return True


def _parse_chapter(path, diagnostics):
    try:
        result = _run(["pandoc", "-f", "gfm", "-t", "json", "--", str(path)])
    except ToolFailure as error:
        diagnostics.append(_diagnostic(path, "Pandoc parse", "fix GFM input ({})".format(error)))
        return None
    try:
        ast = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        diagnostics.append(_diagnostic(path, "Pandoc JSON", "Pandoc returned invalid JSON ({})".format(error)))
        return None
    headers = [node for node in _walk(ast) if node.get("t") == "Header"]
    h1 = [node for node in headers if node["c"][0] == 1]
    if not ast.get("blocks") or ast["blocks"][0].get("t") != "Header" or ast["blocks"][0]["c"][0] != 1 or len(h1) != 1:
        diagnostics.append(_diagnostic(path, "chapter H1", "start with exactly one H1"))
    heading_map = {}
    heading_case = {}
    for node in headers:
        slug = _github_slug(node["c"][2])
        if not slug:
            diagnostics.append(_diagnostic(path, "heading ID", "heading must produce a non-empty GitHub-compatible ID"))
        elif slug in heading_map:
            diagnostics.append(_diagnostic(path, "ambiguous heading", "rename duplicate heading ID #{}".format(slug)))
        else:
            heading_map[slug] = node
            heading_case[slug.casefold()] = slug
    images = []
    for node in _walk(ast):
        kind = node.get("t")
        if kind in ("RawBlock", "RawInline"):
            raw_format = node.get("c", [""])[0]
            label = "raw HTML" if raw_format == "html" else "raw {}".format(raw_format)
            diagnostics.append(_diagnostic(path, label, "remove raw markup from Handbook Markdown"))
        elif kind == "CodeBlock":
            attributes = node["c"][0]
            classes = set(attributes[1])
            key_values = {key: value for key, value in attributes[2]}
            if not classes:
                diagnostics.append(_diagnostic(path, "code fence language", "add a language class to every fenced block"))
            if any(value.startswith("{=typst") for value in classes):
                diagnostics.append(_diagnostic(path, "raw Typst", "remove executable Typst source"))
            elif classes.intersection({"exec", "execute", "cell-code"}) or any(value.startswith("{") for value in classes) or key_values.get("execute") in ("true", "1"):
                diagnostics.append(_diagnostic(path, "executable code cell", "remove execution attributes"))
        elif kind == "BlockQuote" and _looks_like_callout(node) and _callout_label(node) is None:
            diagnostics.append(_diagnostic(path, "callout syntax", "put the bold label in a standalone first blockquote paragraph"))
        elif kind == "Table" and not _table_is_simple(node):
            diagnostics.append(_diagnostic(path, "table cell", "use one simple header row and single-paragraph cells without spans or raw markup"))
        elif kind == "Image":
            images.append(node["c"][2][0])
    return ast, heading_map, heading_case, images


def _validate_target(source, raw_target, project_root, chapter_paths, heading_maps, heading_cases, diagnostics, image=False):
    target = urlsplit(raw_target)
    if image and (target.scheme or target.netloc):
        diagnostics.append(_diagnostic(source, "remote image", "use a repository-relative image path"))
        return
    if target.scheme or target.netloc:
        if target.scheme not in ("http", "https"):
            diagnostics.append(_diagnostic(source, "link scheme", "use a relative, HTTP, or HTTPS link"))
        return
    if image and (target.query or target.fragment):
        diagnostics.append(_diagnostic(source, "image target", "image paths cannot contain a query or fragment"))
    if not target.path:
        resolved = source
    else:
        try:
            resolved = _resolve_within(source.parent, target.path, project_root)
        except ValueError as error:
            diagnostics.append(_diagnostic(source, "path", str(error)))
            return
        if resolved.exists() and not _case_exact(source.parent, target.path):
            diagnostics.append(_diagnostic(source, "path case mismatch", "use the exact on-disk path spelling"))
        if not resolved.is_file():
            diagnostics.append(_diagnostic(source, "image does not exist" if image else "link does not exist", str(resolved)))
            return
    if image:
        if resolved.suffix.lower() not in IMAGE_EXTENSIONS:
            diagnostics.append(_diagnostic(source, "image extension", "use a supported static image format"))
        return
    if resolved in chapter_paths:
        fragment = unquote(target.fragment)
        if target.fragment:
            headings = heading_maps.get(resolved, {})
            if fragment not in headings:
                actual = heading_cases.get(resolved, {}).get(fragment.casefold())
                if actual is not None:
                    diagnostics.append(_diagnostic(source, "fragment case mismatch", "use #{}".format(actual)))
                else:
                    diagnostics.append(_diagnostic(source, "fragment does not exist", "fix #{}".format(fragment)))


def check(index_path, config_path=None):
    # type: (Path, Optional[Path]) -> CheckedBook
    diagnostics = []  # type: List[Diagnostic]
    index_path = Path(index_path).resolve()
    config_path = Path(config_path).resolve() if config_path is not None else index_path.parent / "book.json"
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise StaticCheckError([_diagnostic(index_path, "index", "read UTF-8 index ({})".format(error))])
    _parse_frontmatter(lines, index_path, diagnostics)
    config = _parse_config(config_path, diagnostics)
    catalog_body = _marker_body(lines, CATALOG_START, CATALOG_END, index_path, "catalog", diagnostics)
    filemap_body = _marker_body(lines, FILEMAP_START, FILEMAP_END, index_path, "filemap", diagnostics)
    catalog_rows = _pipe_table(catalog_body, CATALOG_HEADER, index_path, "catalog", diagnostics)
    filemap_rows = _pipe_table(filemap_body, FILEMAP_HEADER, index_path, "filemap", diagnostics)

    if config is None:
        if diagnostics:
            raise StaticCheckError(diagnostics)
        raise StaticCheckError([_diagnostic(config_path, "config", "invalid configuration")])
    if not _within(index_path, config.project_root):
        diagnostics.append(_diagnostic(index_path, "index path", "index escapes project root"))
    if not _within(config_path, config.project_root):
        diagnostics.append(_diagnostic(config_path, "config path", "config escapes project root"))

    catalog_entries = []
    seen_paths = set()
    role_paths = {}  # type: Dict[str, Path]
    for line_number, cells in catalog_rows:
        role_cell, file_cell, responsibility, trigger = cells
        if any("<" in cell or ">" in cell for cell in cells) or not responsibility or not trigger:
            diagnostics.append(_diagnostic(index_path, "catalog cell", "cells must be non-HTML single-line text", str(line_number)))
        link = re.fullmatch(r"\[[^\[\]\n]+\]\(([^()\s]+\.md)\)", file_cell)
        if link is None:
            diagnostics.append(_diagnostic(index_path, "catalog file cell", "use exactly one relative Markdown link", str(line_number)))
            continue
        raw_path = link.group(1)
        target_url = urlsplit(raw_path)
        if target_url.scheme or target_url.netloc or target_url.query or target_url.fragment:
            diagnostics.append(_diagnostic(index_path, "catalog file cell", "chapter link cannot contain URL components", str(line_number)))
            continue
        try:
            chapter_path = _resolve_within(index_path.parent, target_url.path, config.project_root)
        except ValueError as error:
            diagnostics.append(_diagnostic(index_path, "catalog path", str(error), str(line_number)))
            continue
        if chapter_path.parent != index_path.parent.resolve():
            diagnostics.append(_diagnostic(index_path, "flat chapter", "catalog chapters must be direct siblings of index.md", str(line_number)))
        if chapter_path in seen_paths:
            diagnostics.append(_diagnostic(index_path, "duplicate catalog file", str(chapter_path), str(line_number)))
        seen_paths.add(chapter_path)
        if chapter_path.exists() and not _case_exact(index_path.parent, target_url.path):
            diagnostics.append(_diagnostic(index_path, "catalog path case mismatch", "use exact on-disk spelling", str(line_number)))
        if not chapter_path.is_file():
            diagnostics.append(_diagnostic(index_path, "catalog file does not exist", str(chapter_path), str(line_number)))
        roles = []
        if role_cell:
            if " " in role_cell or role_cell.startswith(",") or role_cell.endswith(",") or ",," in role_cell:
                diagnostics.append(_diagnostic(index_path, "role syntax", "use comma-separated roles without whitespace or empty items", str(line_number)))
            else:
                roles = role_cell.split(",")
                for role in roles:
                    if role not in REQUIRED_ROLES:
                        diagnostics.append(_diagnostic(index_path, "unknown role", role, str(line_number)))
                    elif role in role_paths:
                        diagnostics.append(_diagnostic(index_path, "duplicate required role", role, str(line_number)))
                    else:
                        role_paths[role] = chapter_path
        catalog_entries.append((chapter_path, roles))
    for role in REQUIRED_ROLES:
        if role not in role_paths:
            diagnostics.append(_diagnostic(index_path, "required role", "assign {} exactly once".format(role)))

    actual_markdown = {
        path.resolve()
        for path in index_path.parent.rglob("*.md")
        if path.resolve() != index_path and path.is_file()
    }
    for path in sorted(actual_markdown - seen_paths):
        diagnostics.append(_diagnostic(path, "not cataloged", "add every Handbook Markdown body to the catalog"))

    for line_number, cells in filemap_rows:
        path_cell, responsibility, trigger, owner = cells
        if not responsibility or not trigger or not owner:
            diagnostics.append(_diagnostic(index_path, "filemap cell", "all four cells are required", str(line_number)))
        patterns = re.fullmatch(r"`([^`]+)`(?:, `([^`]+)`)*", path_cell)
        extracted = re.findall(r"`([^`]+)`", path_cell)
        if patterns is None or ", ".join("`{}`".format(value) for value in extracted) != path_cell:
            diagnostics.append(_diagnostic(index_path, "filemap path cell", "use backtick paths separated by comma-space", str(line_number)))
            continue
        for pattern in extracted:
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                diagnostics.append(_diagnostic(index_path, "filemap pattern", "patterns must stay under project root", str(line_number)))
                continue
            matches = [Path(item).resolve() for item in glob.glob(str(config.project_root / pattern), recursive=True)]
            if not any(_within(match, config.project_root) for match in matches):
                diagnostics.append(_diagnostic(index_path, "filemap pattern", "pattern has no project-root match: {}".format(pattern), str(line_number)))

    if not diagnostics:
        try:
            python_parts = tuple(int(item) for item in config.python_min.split("."))
        except ValueError:
            raise StaticCheckError([_diagnostic(config_path, "Python version", "python_min must be numeric major.minor")])
        if sys.version_info[:2] < python_parts:
            raise RenderError([_diagnostic(config_path, "Python version", "requires Python {}, running {}.{}".format(config.python_min, *sys.version_info[:2]))])
        try:
            actual_pandoc = _tool_version("pandoc")
        except ToolFailure as error:
            raise RenderError([_diagnostic(config_path, "Pandoc tool", str(error))])
        if actual_pandoc != config.pandoc_version:
            raise RenderError([_diagnostic(config_path, "Pandoc version", "expected {}, found {}".format(config.pandoc_version, actual_pandoc))])

    chapter_data = []
    ast_diagnostics = []  # type: List[Diagnostic]
    preliminary = {}
    for chapter_path, roles in catalog_entries:
        parsed = _parse_chapter(chapter_path, ast_diagnostics)
        if parsed is not None:
            ast, headings, heading_case, images = parsed
            preliminary[chapter_path] = (roles, ast, headings, heading_case, images)
    chapter_paths = set(preliminary)
    heading_maps = {path: value[2] for path, value in preliminary.items()}
    heading_cases = {path: value[3] for path, value in preliminary.items()}
    for chapter_path, (roles, ast, headings, _heading_case, images) in preliminary.items():
        for node in _walk(ast):
            if node.get("t") == "Link":
                _validate_target(chapter_path, node["c"][2][0], config.project_root, chapter_paths, heading_maps, heading_cases, ast_diagnostics)
            elif node.get("t") == "Image":
                _validate_target(chapter_path, node["c"][2][0], config.project_root, chapter_paths, heading_maps, heading_cases, ast_diagnostics, image=True)
        chapter_data.append(Chapter(chapter_path, roles, ast, headings, images))
    if diagnostics or ast_diagnostics:
        raise StaticCheckError(diagnostics + ast_diagnostics)
    return CheckedBook(index_path, config_path, config, chapter_data, role_paths)


def _chapter_key(path, project_root):
    relative = path.resolve().relative_to(project_root.resolve()).as_posix()
    return "".join("%{:02X}".format(byte) for byte in relative.encode("utf-8"))


def _published_anchor(logical_key):
    return "hb-" + hashlib.sha256(logical_key.encode("utf-8")).hexdigest()


def _meta_string(value):
    return {"t": "MetaString", "c": value}


def _rewrite_callouts(value):
    callout_classes = {
        "한눈에": "callout-overview",
        "핵심": "callout-key",
        "참고": "callout-note",
        "주의": "callout-warning",
        "예시": "callout-example",
    }
    if isinstance(value, list):
        rewritten = []
        for child in value:
            label = _callout_label(child) if isinstance(child, dict) else None
            if label is None:
                rewritten.append(_rewrite_callouts(child))
                continue
            label_block = {
                "t": "Div",
                "c": [["", ["callout-label"], []], [copy.deepcopy(child["c"][0])]],
            }
            body = [label_block] + _rewrite_callouts(child["c"][1:])
            rewritten.append(
                {
                    "t": "Div",
                    "c": [["", ["callout", callout_classes[label]], []], body],
                }
            )
        return rewritten
    if isinstance(value, dict):
        return {key: _rewrite_callouts(child) for key, child in value.items()}
    return value


def _add_class(attributes, class_name):
    if class_name not in attributes[1]:
        attributes[1].append(class_name)


def _rewrite_table_alignments(table):
    column_alignments = [column[0]["t"] for column in table["c"][2]]
    for column in table["c"][2]:
        column[0] = {"t": "AlignDefault"}

    head_rows = table["c"][3][1]
    body_rows = []
    for body in table["c"][4]:
        body_rows.extend(body[2])
        body_rows.extend(body[3])
    foot_rows = table["c"][5][1]
    for row in head_rows + body_rows + foot_rows:
        column_index = 0
        for cell in row[1]:
            alignment = cell[1]["t"]
            if alignment == "AlignDefault" and column_index < len(column_alignments):
                alignment = column_alignments[column_index]
            _add_class(cell[0], TABLE_ALIGNMENT_CLASSES[alignment])
            cell[1] = {"t": "AlignDefault"}
            column_index += cell[3]


def _rewrite_layout_classes(document):
    for node in _walk(document):
        if node.get("t") == "Table":
            _rewrite_table_alignments(node)
        elif node.get("t") == "Code":
            literal = node["c"][1]
            if len(literal) <= SHORT_INLINE_CODE_MAX and not any(character.isspace() for character in literal):
                _add_class(node["c"][0], "code-short")


def _rewrite_ast(checked):
    chapter_destinations = {}
    heading_destinations = {}
    for chapter in checked.chapters:
        chapter_key = _chapter_key(chapter.path, checked.config.project_root)
        chapter_destinations[chapter.path] = _published_anchor(chapter_key)
        prefix = chapter_key + "--"
        destinations = {slug: _published_anchor(prefix + slug) for slug in chapter.headings}
        heading_destinations[chapter.path] = destinations
    combined = {
        "pandoc-api-version": checked.chapters[0].ast["pandoc-api-version"],
        "meta": {"title": _meta_string(checked.config.title), "author": _meta_string(checked.config.author)},
        "blocks": [],
    }
    toc_items = []
    for number, chapter in enumerate(checked.chapters, 1):
        first_heading = next(iter(chapter.headings.values()))
        destination = chapter_destinations[chapter.path]
        toc_items.append(
            [
                {
                    "t": "Plain",
                    "c": [
                        {
                            "t": "Link",
                            "c": [
                                ["", [], []],
                                [{"t": "Str", "c": "{}. ".format(number)}] + copy.deepcopy(first_heading["c"][2]),
                                ["#" + quote(destination, safe="-._~"), ""],
                            ],
                        }
                    ],
                }
            ]
        )
    combined["blocks"].append(
        {
            "t": "Div",
            "c": [
                ["handbook-toc", ["handbook-toc"], []],
                [
                    {"t": "Header", "c": [1, ["", [], []], [{"t": "Str", "c": "Contents"}]]},
                    {"t": "BulletList", "c": toc_items},
                ],
            ],
        }
    )
    chapter_paths = {chapter.path for chapter in checked.chapters}
    for chapter in checked.chapters:
        document = copy.deepcopy(chapter.ast)
        _rewrite_layout_classes(document)
        for node in _walk(document):
            kind = node.get("t")
            if kind == "Header":
                slug = _github_slug(node["c"][2])
                node["c"][1][0] = heading_destinations[chapter.path][slug]
            elif kind == "Link":
                raw = node["c"][2][0]
                target = urlsplit(raw)
                if target.scheme or target.netloc:
                    continue
                resolved = chapter.path if not target.path else _resolve_within(chapter.path.parent, target.path, checked.config.project_root)
                if resolved in chapter_paths:
                    destination = heading_destinations[resolved][unquote(target.fragment)] if target.fragment else chapter_destinations[resolved]
                    node["c"][2][0] = "#" + quote(destination, safe="-._~")
                else:
                    relative = resolved.relative_to(checked.config.project_root)
                    encoded = "/".join(quote(part, safe="") for part in relative.parts)
                    base = checked.config.source_url.rstrip("/") + "/" + encoded
                    node["c"][2][0] = urlunsplit(("https", urlsplit(base).netloc, urlsplit(base).path, target.query, target.fragment))
            elif kind == "Image":
                target = urlsplit(node["c"][2][0])
                resolved = _resolve_within(chapter.path.parent, target.path, checked.config.project_root)
                mime = mimetypes.guess_type(resolved.name)[0]
                if mime is None:
                    mime = "application/octet-stream"
                encoded = base64.b64encode(resolved.read_bytes()).decode("ascii")
                node["c"][2][0] = "data:{};base64,{}".format(mime, encoded)
        combined["blocks"].append(
            {
                "t": "Div",
                "c": [
                    [
                        chapter_destinations[chapter.path],
                        ["chapter"],
                        [["data-kicker", "Chapter {}".format(len(combined["blocks"]))]],
                    ],
                    _rewrite_callouts(document["blocks"]),
                ],
            }
        )
    return combined


def _write_html(checked):
    template = Path(__file__).resolve().with_name("template.html")
    stylesheet = Path(__file__).resolve().with_name("styles.css")
    combined = _rewrite_ast(checked)
    try:
        result = _run(
            [
                "pandoc",
                "-f",
                "json",
                "-t",
                "html5",
            ],
            input_bytes=json.dumps(combined, ensure_ascii=False).encode("utf-8"),
        )
    except ToolFailure as error:
        raise RenderError([_diagnostic(template, "Pandoc writer", str(error))])
    try:
        template_text = template.read_text(encoding="utf-8")
        css = stylesheet.read_text(encoding="utf-8")
        font_data = base64.b64encode(checked.config.font_path.read_bytes()).decode("ascii")
    except (OSError, UnicodeError) as error:
        raise RenderError([_diagnostic(template, "HTML asset", str(error))])
    css = css.replace("@@FONT_DATA@@", font_data)
    style_hash = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
    csp = (
        "default-src 'none'; img-src data:; font-src data:; "
        "style-src 'sha256-{}'; script-src 'none'; connect-src 'none'; "
        "object-src 'none'; base-uri 'none'; frame-src 'none'; form-action 'none'; worker-src 'none'"
    ).format(style_hash)
    try:
        rendered = string.Template(template_text).substitute(
            language=html.escape(checked.config.language, quote=True),
            title=html.escape(checked.config.title, quote=True),
            author=html.escape(checked.config.author, quote=True),
            csp=html.escape(csp, quote=True),
            styles=css,
            body=result.stdout.decode("utf-8"),
        )
    except (KeyError, ValueError) as error:
        raise RenderError([_diagnostic(template, "HTML template", "invalid placeholder ({})".format(error))])
    return rendered.encode("utf-8")


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _font_family_names(path):
    data = path.read_bytes()

    def require(start, size, label):
        if start < 0 or size < 0 or start + size > len(data):
            raise ValueError("{} exceeds file bounds".format(label))

    require(0, 12, "SFNT header")
    if data[:4] not in (b"OTTO", b"\x00\x01\x00\x00", b"true"):
        raise ValueError("unsupported SFNT signature")
    table_count = struct.unpack_from(">H", data, 4)[0]
    require(12, table_count * 16, "SFNT table directory")
    name_offset = name_length = None
    for index in range(table_count):
        offset = 12 + index * 16
        tag, _checksum, table_offset, table_length = struct.unpack_from(">4sIII", data, offset)
        require(table_offset, table_length, "SFNT table {}".format(tag.decode("latin1")))
        if tag == b"name":
            name_offset, name_length = table_offset, table_length
    if name_offset is None or name_length is None:
        raise ValueError("SFNT has no name table")
    require(name_offset, 6, "name table header")
    _format, record_count, storage_relative = struct.unpack_from(">HHH", data, name_offset)
    records_offset = name_offset + 6
    require(records_offset, record_count * 12, "name records")
    storage_offset = name_offset + storage_relative
    require(storage_offset, 0, "name string storage")
    names = {16: set(), 1: set()}
    for index in range(record_count):
        record_offset = records_offset + index * 12
        platform, _encoding, _language, name_id, length, relative = struct.unpack_from(">HHHHHH", data, record_offset)
        if name_id not in names:
            continue
        start = storage_offset + relative
        require(start, length, "name string")
        raw = data[start : start + length]
        try:
            value = raw.decode("utf-16-be" if platform in (0, 3) else "mac_roman")
        except UnicodeError as error:
            raise ValueError("invalid encoded name string ({})".format(error)) from error
        value = value.strip("\x00 ")
        if value:
            names[name_id].add(value)
    selected = names[16] or names[1]
    if not selected:
        raise ValueError("SFNT has no family name")
    return selected


def _validate_font(config):
    if not config.font_path.is_file():
        raise RenderError([_diagnostic(config.font_path, "font file", "provision the configured font")])
    if _sha256(config.font_path) != config.font_sha256:
        raise RenderError([_diagnostic(config.font_path, "font SHA-256", "configured checksum does not match")])
    try:
        families = _font_family_names(config.font_path)
    except (OSError, ValueError, struct.error) as error:
        raise RenderError([_diagnostic(config.font_path, "font SFNT", str(error))])
    if config.font_family not in families:
        raise RenderError(
            [_diagnostic(config.font_path, "font family", "{} is not the pinned font's internal family".format(config.font_family))]
        )


def _protected_paths(checked):
    paths = {
        checked.index_path.resolve(),
        checked.config_path.resolve(),
        checked.config.font_path.resolve(),
        Path(__file__).resolve(),
        Path(__file__).resolve().with_name("template.html"),
        Path(__file__).resolve().with_name("styles.css"),
    }
    for chapter in checked.chapters:
        paths.add(chapter.path.resolve())
        for raw in chapter.images:
            target = urlsplit(raw)
            if not target.scheme and not target.netloc:
                paths.add(_resolve_within(chapter.path.parent, target.path, checked.config.project_root))
    return paths


def _playwright_package_version():
    try:
        return importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError as error:
        raise ToolFailure("Playwright package is not installed") from error


def _render_pdf_with_playwright(html_path, pdf_path, config):
    if _playwright_package_version() != config.playwright_version:
        raise ToolFailure(
            "Playwright version expected {}, found {}".format(config.playwright_version, _playwright_package_version())
        )
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise ToolFailure("Playwright import failed: {}".format(error)) from error
    requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chromium", chromium_sandbox=True)
        try:
            if browser.version != config.chromium_version:
                raise ToolFailure(
                    "Chromium version expected {}, found {}".format(config.chromium_version, browser.version)
                )
            context = browser.new_context(service_workers="block", accept_downloads=False)
            try:
                def deny_request(route, request):
                    requests.append(request.url)
                    route.abort()

                context.route("**/*", deny_request)
                page = context.new_page()
                page.emulate_media(media="print")
                page.set_content(html_path.read_text(encoding="utf-8"), wait_until="load")
                readiness = page.evaluate(
                    """async () => {
                      await document.fonts.ready;
                      const imageFailures = [];
                      for (const [index, image] of [...document.images].entries()) {
                        try { await image.decode(); }
                        catch (error) { imageFailures.push(image.alt || String(index)); }
                      }
                      return {
                        font_status: document.fonts.status,
                        font_check: document.fonts.check('10px "HandbookPinnedFont"'),
                        image_failures: imageFailures,
                      };
                    }"""
                )
                readiness["requests"] = requests
                page.pdf(
                    path=str(pdf_path),
                    print_background=True,
                    prefer_css_page_size=True,
                    outline=True,
                    tagged=True,
                )
                return readiness
            finally:
                context.close()
        finally:
            browser.close()


def _pdf_worker(html_path, pdf_path, config):
    report = _render_pdf_with_playwright(html_path, pdf_path, config)
    if report.get("font_status") != "loaded" or report.get("font_check") is not True:
        raise ToolFailure("font readiness failed")
    if report.get("requests"):
        raise ToolFailure("network request denied: {}".format(", ".join(report["requests"])))
    if report.get("image_failures"):
        raise ToolFailure("image readiness failed: {}".format(", ".join(report["image_failures"])))


def _worker_main(request_path):
    try:
        request = json.loads(Path(request_path).read_text(encoding="utf-8"))
        config = Config(
            Path(request["project_root"]),
            request["title"],
            request["author"],
            request["language"],
            request["source_url"],
            request["font_family"],
            Path(request["font_path"]),
            request["font_sha256"],
            request["python_min"],
            request["pandoc_version"],
            request["playwright_version"],
            request["chromium_version"],
        )
        _pdf_worker(Path(request["html_path"]), Path(request["pdf_path"]), config)
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


def _run_pdf_worker(html_path, pdf_path, config):
    request_fd, request_name = tempfile.mkstemp(prefix=".handbook-publish-", suffix=".json", dir=str(pdf_path.parent))
    os.close(request_fd)
    request_path = Path(request_name)
    payload = {
        "project_root": str(config.project_root),
        "title": config.title,
        "author": config.author,
        "language": config.language,
        "source_url": config.source_url,
        "font_family": config.font_family,
        "font_path": str(config.font_path),
        "font_sha256": config.font_sha256,
        "python_min": config.python_min,
        "pandoc_version": config.pandoc_version,
        "playwright_version": config.playwright_version,
        "chromium_version": config.chromium_version,
        "html_path": str(html_path),
        "pdf_path": str(pdf_path),
    }
    try:
        request_path.write_text(json.dumps(payload), encoding="utf-8")
        environment = os.environ.copy()
        environment["HANDBOOK_PUBLISH_PRIVATE_WORKER"] = "1"
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), str(request_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        try:
            _stdout, stderr = process.communicate(timeout=PDF_WORKER_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.communicate(timeout=PDF_WORKER_GRACE)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
            raise ToolFailure("PDF worker timeout after {} seconds".format(PDF_WORKER_TIMEOUT))
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise ToolFailure(detail or "PDF worker exited {}".format(process.returncode))
    finally:
        try:
            request_path.unlink()
        except FileNotFoundError:
            pass


def build(checked, output_path):
    # type: (CheckedBook, Path) -> None
    output = Path(output_path).resolve()
    if output in _protected_paths(checked) or output.is_dir():
        raise UnsafeIOError([_diagnostic(output, "output overlap", "choose an output path distinct from every input and publisher asset")])
    if output.suffix.lower() not in (".pdf", ".html"):
        raise UnsafeIOError([_diagnostic(output, "output extension", "output must end in .pdf or .html")])
    try:
        actual_pandoc = _tool_version("pandoc")
    except ToolFailure as error:
        raise RenderError([_diagnostic(None, "external tool", str(error))])
    if actual_pandoc != checked.config.pandoc_version:
        raise RenderError([_diagnostic(checked.config_path, "Pandoc version", "expected {}, found {}".format(checked.config.pandoc_version, actual_pandoc))])
    _validate_font(checked.config)
    if output.suffix.lower() == ".pdf":
        try:
            actual_playwright = _playwright_package_version()
        except ToolFailure as error:
            raise RenderError([_diagnostic(checked.config_path, "Playwright package", str(error))])
        if actual_playwright != checked.config.playwright_version:
            raise RenderError([_diagnostic(checked.config_path, "Playwright version", "expected {}, found {}".format(checked.config.playwright_version, actual_playwright))])
    html_source = _write_html(checked)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_fd, result_name = tempfile.mkstemp(prefix=".handbook-publish-", suffix=output.suffix.lower(), dir=str(output.parent))
    os.close(result_fd)
    result_path = Path(result_name)
    html_path = None
    try:
        if output.suffix.lower() == ".html":
            result_path.write_bytes(html_source)
        else:
            result_path.unlink()
            html_fd, html_name = tempfile.mkstemp(prefix=".handbook-publish-", suffix=".html", dir=str(output.parent))
            os.close(html_fd)
            html_path = Path(html_name)
            html_path.write_bytes(html_source)
            try:
                _run_pdf_worker(html_path, result_path, checked.config)
            except ToolFailure as error:
                raise RenderError([_diagnostic(output, "PDF worker", str(error))])
        if not result_path.is_file() or result_path.stat().st_size == 0:
            raise RenderError([_diagnostic(result_path, "empty output", "renderer did not produce a non-empty file")])
        if output.suffix.lower() == ".pdf":
            with result_path.open("rb") as rendered:
                if rendered.read(5) != b"%PDF-":
                    raise RenderError([_diagnostic(result_path, "invalid PDF", "browser output lacks a PDF header")])
        os.replace(str(result_path), str(output))
    finally:
        for temporary in (result_path, html_path):
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check_parser = subparsers.add_parser("check")
    check_parser.add_argument("index", type=Path)
    check_parser.add_argument("--config", type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("index", type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.add_argument("--config", type=Path)
    return parser


def main(argv=None):
    # type: (Optional[Sequence[str]]) -> int
    try:
        arguments = _parser().parse_args(argv)
        checked = check(arguments.index, arguments.config)
        if arguments.command == "build":
            build(checked, arguments.output)
        return 0
    except StaticCheckError as caught:
        code, diagnostics = 2, caught.diagnostics
    except RenderError as caught:
        code, diagnostics = 3, caught.diagnostics
    except UnsafeIOError as caught:
        code, diagnostics = 4, caught.diagnostics
    except SystemExit as error:
        return int(error.code) if isinstance(error.code, int) else 2
    for diagnostic in diagnostics:
        print(diagnostic.format(), file=sys.stderr)
    return code


if __name__ == "__main__":
    if os.environ.get("HANDBOOK_PUBLISH_PRIVATE_WORKER") == "1" and len(sys.argv) == 2:
        sys.exit(_worker_main(sys.argv[1]))
    sys.exit(main())
