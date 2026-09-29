"""Parse and select the documents served by one Limn instance at startup."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias, TypedDict

from limn.documents import (
    DEFAULT_DOC_KEY,
    DOC_KEY_RE,
    DOC_NAME_MAX,
    DOCS_MAX,
    Doc,
    DocKind,
    RunPaths,
    kind_builds_from_source,
)
from limn.figmap import MAP_SUFFIX
from limn.startup import APP_NAME, StartupRefused

# ---------------------------------------------------------------- document selection (§Multiple documents)


class DocSpec(TypedDict):
    """One parsed --doc: key, display name, kind (the DocKind its path's suffix names: .tex, .pdf or
    limn.figmap.MAP_SUFFIX), build root (src - for a figure document the base of its map's source paths) and main
    file, both resolved."""

    key: str
    name: str
    kind: DocKind
    src: Path
    main: Path


@dataclass(frozen=True)
class DocNotKeyed:
    """The --doc value is not a string of the form <key>=<name>:<path> (it has no '=')."""

    spec: object


@dataclass(frozen=True)
class DocKeyInvalid:
    """The key before '=' is not [a-z0-9-]{1,24} (DOC_KEY_RE)."""

    key: str


@dataclass(frozen=True)
class DocNameUnseparated:
    """No ':' separates the display name from the path; spec is the whole --doc value."""

    key: str
    spec: str


@dataclass(frozen=True)
class DocNameEmpty:
    """The display name is empty once its whitespace is collapsed."""

    key: str


@dataclass(frozen=True)
class DocNameTooLong:
    """The display name (whitespace collapsed) is longer than DOC_NAME_MAX characters."""

    key: str
    name: str


@dataclass(frozen=True)
class DocPathEmpty:
    """Nothing but whitespace follows the ':' after the display name."""

    key: str


@dataclass(frozen=True)
class DocOutsideManuscript:
    """A path resolves outside --manuscript (a security constraint: pins only point at files inside it). part says
    which one - the build root of the '::' form or the plain path; manuscript and path are both resolved."""

    key: str
    part: Literal["root", "path"]
    manuscript: Path
    path: Path


@dataclass(frozen=True)
class DocExtendedMalformed:
    """The '::' form is not exactly one <build root>::<main.tex> with both sides non-empty; path is the path part."""

    key: str
    path: str


@dataclass(frozen=True)
class DocRootMissing:
    """The build root of the '::' form is not an existing folder."""

    key: str
    root: Path


@dataclass(frozen=True)
class DocMainAbsolute:
    """The main file after '::' is absolute; it must be relative to the build root."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocMainOutsideRoot:
    """The main file after '::' resolves outside its build root."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocExtendedWrongKind:
    """The '::' form names a main file that is neither .tex nor a figure map (MAP_SUFFIX) - the form gives a LaTeX or
    a figure document a folder of its own, and a view-only PDF has none."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocFileMissing:
    """The resolved main file is not an existing regular file."""

    key: str
    main: Path


@dataclass(frozen=True)
class DocKindUnknown:
    """The main file is neither .tex (LaTeX), .pdf (view-only) nor a figure map (MAP_SUFFIX, exact case)."""

    key: str
    main: Path


@dataclass(frozen=True)
class TooManyDocs:
    """More --doc values than DOCS_MAX; count is how many were given."""

    count: int


@dataclass(frozen=True)
class DocKeyRepeated:
    """Two --doc values share a key."""

    key: str


# Why one --doc value cannot be served (parse_doc_arg), and why the --doc list cannot (make_docs adds its own two). All
# are answered the same way: pick_documents() refuses to start with doc_refusal_message()'s text.
DocSpecRefusal: TypeAlias = (
    DocNotKeyed
    | DocKeyInvalid
    | DocNameUnseparated
    | DocNameEmpty
    | DocNameTooLong
    | DocPathEmpty
    | DocOutsideManuscript
    | DocExtendedMalformed
    | DocRootMissing
    | DocMainAbsolute
    | DocMainOutsideRoot
    | DocExtendedWrongKind
    | DocFileMissing
    | DocKindUnknown
)
DocsRefusal: TypeAlias = DocSpecRefusal | TooManyDocs | DocKeyRepeated


def parse_doc_arg(spec: str, ms: Path) -> DocSpec | DocSpecRefusal:
    """Parses one --doc <key>=<display name>:<path>. The path is relative to --manuscript (recommended) or absolute.

    - `<key>=<name>:a/b/main.tex` - LaTeX. The build root is the folder holding that .tex (a/b).
    - `<key>=<name>:a::b/main.tex` - LaTeX. The build root is a (the scope copied into the build copy), and
      main is a/b/main.tex. The build runs in the folder holding main (a/b) - used when main reads another
      folder inside the build root via ../.
    - `<key>=<name>:x/review.pdf` - a view-only PDF (no rebuild, page/region pins).
    - `<key>=<name>:x/figures.limnmap.json` - a figure document (limn.figmap.MAP_SUFFIX, exact case): its PDF and
      element map are imported, never built; its folder, the base of the map's source paths, is x.
    - `<key>=<name>:a::b/figures.limnmap.json` - a figure document whose folder is a; the map is a/b/figures.limnmap.json.
    key must be [a-z0-9-]{1,24}; name must be 40 characters or fewer with no ':'. The path must be inside
    --manuscript (a security constraint: a pin can only ever point at a file inside the manuscript tree).
    Returns the DocSpec, or the first rule the value breaks (DocSpecRefusal), checked in this order: form, key, name,
    path, then the files. Reads the file system only to resolve the paths and check that they exist."""
    if not isinstance(spec, str) or "=" not in spec:
        return DocNotKeyed(spec)
    key, rest = spec.split("=", 1)
    key = key.strip()
    if not DOC_KEY_RE.fullmatch(key):
        return DocKeyInvalid(key)
    if ":" not in rest:
        return DocNameUnseparated(key, spec)
    name, path = rest.split(":", 1)
    name = " ".join(name.split())
    if not name:
        return DocNameEmpty(key)
    if len(name) > DOC_NAME_MAX:
        return DocNameTooLong(key, name)
    path = path.strip()
    if not path:
        return DocPathEmpty(key)
    ms = ms.resolve()

    def inside(p: Path, part: Literal["root", "path"]) -> Path | DocOutsideManuscript:
        """p resolved against --manuscript, or the refusal when it lands outside the manuscript tree."""
        p = (p if p.is_absolute() else ms / p).resolve()
        try:
            p.relative_to(ms)
        except ValueError:
            return DocOutsideManuscript(key, part, ms, p)
        return p

    if "::" in path:
        root_s, main_s = path.split("::", 1)
        if "::" in main_s or not root_s.strip() or not main_s.strip():
            return DocExtendedMalformed(key, path)
        root = inside(Path(root_s.strip()), "root")
        if isinstance(root, DocOutsideManuscript):
            return root
        if not root.is_dir():
            return DocRootMissing(key, root)
        mp = Path(main_s.strip())
        if mp.is_absolute():
            return DocMainAbsolute(key, mp)
        main = (root / mp).resolve()
        try:
            main.relative_to(root)
        except ValueError:
            return DocMainOutsideRoot(key, main)
        if main.suffix.lower() != ".tex" and not main.name.endswith(MAP_SUFFIX):
            return DocExtendedWrongKind(key, main)
    else:
        found = inside(Path(path), "path")
        if isinstance(found, DocOutsideManuscript):
            return found
        main, root = found, found.parent
    if not main.is_file():
        return DocFileMissing(key, main)
    suf = main.suffix.lower()
    kind: DocKind
    if main.name.endswith(MAP_SUFFIX):
        kind = "figure"
    elif suf == ".tex":
        kind = "tex"
    elif suf == ".pdf":
        kind = "pdf"
    else:
        return DocKindUnknown(key, main)
    return DocSpec(key=key, name=name, kind=kind, src=root, main=main)


def doc_refusal_message(r: DocsRefusal) -> str:
    """The text the server refuses to start with for each --doc refusal (Korean, worded as it always was)."""
    match r:
        case DocNotKeyed(spec=spec):
            return "--doc 는 <키>=<표시 이름>:<경로> 형식입니다: %r" % (spec,)
        case DocKeyInvalid(key=key):
            return "--doc 키는 영문 소문자·숫자·'-' 1–24자여야 합니다: %r" % key
        case DocNameUnseparated(key=key, spec=spec):
            return "--doc %s: 표시 이름과 경로 사이에 ':' 가 없습니다: %r" % (key, spec)
        case DocNameEmpty(key=key):
            return "--doc %s: 표시 이름이 비었습니다" % key
        case DocNameTooLong(key=key, name=name):
            return "--doc %s: 표시 이름은 %d자 이하여야 합니다: %r" % (key, DOC_NAME_MAX, name)
        case DocPathEmpty(key=key):
            return "--doc %s: 경로가 비었습니다" % key
        case DocOutsideManuscript(key=key, part=part, manuscript=ms, path=path):
            what = "빌드 루트" if part == "root" else "경로"
            return "--doc %s: %s 가 --manuscript(%s) 밖입니다: %s" % (key, what, ms, path)
        case DocExtendedMalformed(key=key, path=text):
            return "--doc %s: 확장 표기는 <빌드 루트>::<메인.tex> 하나입니다: %r" % (key, text)
        case DocRootMissing(key=key, root=root):
            return "--doc %s: 빌드 루트 폴더가 없습니다: %s" % (key, root)
        case DocMainAbsolute(key=key, main=main):
            return "--doc %s: '::' 뒤 메인은 빌드 루트 기준 상대경로입니다: %s" % (key, main)
        case DocMainOutsideRoot(key=key, main=main):
            return "--doc %s: 메인 .tex 가 빌드 루트 밖입니다: %s" % (key, main)
        case DocExtendedWrongKind(key=key, main=main):
            return "--doc %s: '::' 표기는 LaTeX 문서(.tex)와 그림 지도(%s)에만 씁니다: %s" % (key, MAP_SUFFIX, main)
        case DocFileMissing(key=key, main=main):
            return "--doc %s: 파일이 없습니다: %s" % (key, main)
        case DocKindUnknown(key=key, main=main):
            return "--doc %s: .tex(LaTeX), .pdf(보기 전용), %s(그림)만 받습니다: %s" % (key, MAP_SUFFIX, main)
        case TooManyDocs(count=count):
            return "--doc 는 %d개까지입니다(지금 %d개)" % (DOCS_MAX, count)
        case DocKeyRepeated(key=key):
            return "--doc 키가 겹칩니다: %s" % key


def parse_docs(specs: Sequence[str], ms: Path) -> list[DocSpec] | DocsRefusal:
    """--doc list -> the parsed documents in order, or the first refusal: more than DOCS_MAX values (checked before any
    is parsed), a value parse_doc_arg refuses, or a key used twice."""
    if len(specs) > DOCS_MAX:
        return TooManyDocs(len(specs))
    out: list[DocSpec] = []
    seen: set[str] = set()
    for spec in specs:
        p = parse_doc_arg(spec, ms)
        if not isinstance(p, dict):
            return p
        if p["key"] in seen:
            return DocKeyRepeated(p["key"])
        seen.add(p["key"])
        out.append(p)
    return out


def docs_of(specs: Sequence[DocSpec], paths: RunPaths) -> list[Doc]:
    """The documents of parsed --doc specs over the run's paths (the frozen value the composition root made once the
    state folder was known). A document keyed main whose kind builds from source (kind_builds_from_source) uses the
    state-folder-root layout (root), so it continues a single-document instance's build history."""
    return [
        Doc(
            p["key"],
            p["name"],
            p["kind"],
            src=p["src"],
            main=p["main"],
            root=(p["key"] == DEFAULT_DOC_KEY and kind_builds_from_source(p["kind"])),
            paths=paths,
        )
        for p in specs
    ]


def make_docs(specs: Sequence[str], ms: Path, paths: RunPaths) -> list[Doc] | DocsRefusal:
    """--doc list -> Doc list over the run paths it is given (parse_docs, then docs_of), or parse_docs' refusal."""
    parsed = parse_docs(specs, ms)
    return docs_of(parsed, paths) if isinstance(parsed, list) else parsed


def doc_start_line(key: str, kind: DocKind, path: str, build_started: bool) -> str:
    """The startup line naming one --doc document: its key padded to ten, its kind's label, its path relative to
    --manuscript and, when startup began its build, "  (build started)". The label is chosen by an exhaustive match on
    kind, so a new DocKind fails the type check until it has a label (mypy exhaustive-match)."""
    match kind:
        case "tex":
            label = "LaTeX   "
        case "pdf":
            label = "view-only"
        case "figure":
            label = "figure   "
    return "doc    %-10s %s %s%s" % (key, label, path, "  (build started)" if build_started else "")


def detect_main(src: Path) -> Path | StartupRefused:
    """Find the top-level .tex. If it's ambiguous, don't guess - refuse with the candidates."""
    cands = [
        p
        for p in sorted(src.glob("*.tex"))
        if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")[:20000]
    ]
    if len(cands) == 1:
        return cands[0]
    how = "found none" if not cands else "found several"
    listing = "\n".join("  - %s" % p.name for p in cands) or "  (none)"
    return StartupRefused(
        "%s: %s top-level .tex files under %s. Specify one with --main.\n%s" % (APP_NAME, how, src, listing)
    )


@dataclass(frozen=True)
class RunDocuments:
    """What the command line serves: the parsed --doc documents (None without --doc: the single document of --main) and
    the main .tex of the run (the first --doc document whose kind builds from source, else the first document's; else
    --main's or the detected one). The documents are made over the run's paths (docs_of) once the state folder is
    known."""

    docs: list[DocSpec] | None
    main: Path


def pick_documents(src: Path, specs: Sequence[str], main: str | None) -> RunDocuments | StartupRefused:
    """The documents of a command line with manuscript folder src (already resolved), or the refusal, in this order: a
    missing manuscript folder, --doc together with --main, a bad --doc, no or several top-level .tex files, a --main
    that does not exist. The run's main file is the first --doc document whose kind builds from source, else the
    first document's."""
    if not src.is_dir():
        return StartupRefused("Manuscript directory does not exist: %s" % src)
    if specs:
        if main:
            return StartupRefused("--doc and --main are not used together - the main file is set via the --doc path.")
        docs = parse_docs(specs, src)
        if not isinstance(docs, list):
            return StartupRefused(doc_refusal_message(docs))
        first_built = next((d for d in docs if kind_builds_from_source(d["kind"])), docs[0])
        return RunDocuments(docs, first_built["main"])
    main_file = (src / main) if main else detect_main(src)
    if isinstance(main_file, StartupRefused):
        return main_file
    if not main_file.exists():
        return StartupRefused("Top-level .tex does not exist: %s" % main_file)
    return RunDocuments(None, main_file)
