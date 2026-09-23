#!/usr/bin/env python3
"""원고 PDF에서 영역을 드래그하면 그 자리의 .tex 줄 번호를 되찾는 로컬 뷰어.

에이전트에게 스크린샷 대신 "파일:줄범위"를 넘기는 것이 목적이다. 이미지 한 장이
1~2천 토큰인 데 비해 줄 범위는 수십 토큰이고, 무엇보다 에이전트가 그 줄을 바로
읽고 고칠 수 있다 — 스크린샷은 위치를 다시 찾는 왕복을 강제한다.

역변환은 두 경로를 **같은 척도로 겨루게** 한다. SyncTeX 좌표 조회가 1차이고,
선택 영역에 찍힌 글자를 원문에서 되찾는 것이 2차다. 어느 한쪽을 조건부 폴백으로
두면 SyncTeX 가 조용히 틀렸을 때 걸러낼 방법이 없다 — minipage·tabular 안
(예: Nomenclature)에서 실제로 그런 일이 일어난다.

바인딩은 127.0.0.1 고정이다. 외부 노출은 tailscale serve 가 담당하며, 그것을
바꾸는 플래그는 의도적으로 두지 않았다. tailscale serve 는 요청마다
Tailscale-User-Login/Name/Profile-Pic 헤더를 붙이므로, 그 헤더로 누가 핀을
남겼는지 기록한다(막지는 않는다 — 테일넷 구성원은 신뢰하는 동료다).

Python 3.10 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import html
import json
import math
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from email.header import decode_header, make_header
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")
FLOAT_KINDS = ("figure", "table", "algorithm")
DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"
PAGES_DIR_RE = re.compile(r"pages(-\d{14}(-\d+)?)?")
PAGE_FILE_RE = re.compile(r"page-\d+\.png")
ENV_TOK_RE = re.compile(r"\\(begin|end)\{([^{}]+)\}")

# 뷰어가 PDF 를 벡터로 그리는 PDF.js(vendor/pdfjs/README.md). 버전은 브라우저 캐시를 가르는 ?v= 값이기도 하다.
PDFJS_VERSION = "6.3.289"
VENDOR_FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*(\.[A-Za-z0-9_-]+)*\.mjs")
VENDOR_MIME = {".mjs": "text/javascript; charset=utf-8"}

# 뷰어 아이콘 — Lucide(ISC, vendor/lucide/README.md). 쓰는 아이콘의 <svg> 안 요소만 npm 의 lucide-static 원본
# 그대로 옮겼다(공백만 줄임). 이모지·기본 문자 아이콘(⏳ ▾ ☾ ✎ 등)은 기기·글꼴마다 모양이 달라 쓰지 않는다.
LUCIDE_VERSION = "1.47.0"
LUCIDE = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-up": '<path d="m18 15-6-6-6 6"/>',
    "circle-question-mark": '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>'
                            '<path d="M12 17h.01"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/>'
            '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "ellipsis": '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    "minus": '<path d="M5 12h14"/>',
    "moon": '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268'
            'c.344-.215.825-.004.803.401"/>',
    "move-vertical": '<path d="M12 2v20"/><path d="m8 18 4 4 4-4"/><path d="m8 6 4-4 4 4"/>',
    "pencil": '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 '
              '.623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "plus": '<path d="M5 12h14"/><path d="M12 5v14"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/>'
           '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
    "sun-moon": '<path d="M12 2v2"/><path d="M14.837 16.385a6 6 0 1 1-7.223-7.222c.624-.147.97.66.715 1.248a4 4 0 0 0 '
                '5.26 5.259c.589-.255 1.396.09 1.248.715"/><path d="M16 12a4 4 0 0 0-4-4"/>'
                '<path d="m19 5-1.256 1.256"/><path d="M20 12h2"/>',
    "trash-2": '<path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
               '<path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "triangle-alert": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
                      '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
}
ICON_TOKEN_RE = re.compile(r"\{\{ic:([a-z0-9-]+)\}\}")


def icon_svg(name: str) -> str:
    """Lucide 아이콘 하나를 인라인 <svg> 로. 원본 속성 그대로이고 크기는 CSS(.ic)가 정한다.
    뷰어 JS 의 ic() 와 같은 모양을 낸다(회귀 테스트가 대조)."""
    return ('<svg class="ic ic-%s" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">%s</svg>'
            % (name, LUCIDE[name]))

MAX_BODY = 1 << 20
NOTE_MAX = 4000
CLOSE_REPLY_MAX = 500              # 닫을 때 남기는 '무엇을 고쳤는지'(§P0b-보완 C)
CLOSE_REF_MAX = 80                 # 같은 값(PR 번호 등)이면 UI 가 닫힌 핀을 묶어 보일 수 있는 참조
CLAIM_TTL_DEFAULT = 120            # 분 — claim 을 걸 때 ttl_min·eta_min 을 둘 다 안 주면 쓰는 잠금 시간(§P0c-C)
CLAIM_TTL_MIN = 1
CLAIM_TTL_MAX = 120                # 잠금 자동 해제는 안전장치다 — 480 이면 멈춘 에이전트가 한나절 핀을 쥐었다(실측 23건)
CLAIM_ETA_MIN = 1                  # 분 — 처리 예상 시간(eta_min). 화면은 5분 단위로 올려 보인다
CLAIM_ETA_MAX = 240
CLAIM_TTL_FLOOR = 30               # eta_min 만 주면 잠금은 min(상한, max(이 값, eta×2)) — 짧은 견적도 30분은 쥔다
GIT_PULL_TIMEOUT = 30              # 초 — --git-pull 의 fetch 한 번(§P0c-E)
SCOPES = ("raw", "para", "env", "env2", "env3", "lines")
ADD_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score",
              "frac", "note", "scope", "quote", "pdf_build")
LOC_FIELDS = ("file", "name", "page", "lo", "hi", "raw_lo", "raw_hi", "kind", "via", "score",
              "frac", "scope", "quote")
LOCAL_ACTOR = {"login": "local", "name": "로컬/에이전트"}
# 빌드 사본(rsync)이 빼는 디렉토리. 원고 지문·src_mtime 도 같은 목록을 쓴다 — 빌드에 안 들어가는
# latexdiff 산출물이 바뀌었다고 '원고 수정됨'·위치 추정이 켜지면 안 된다(실측: diff/ 에 PDF 17개).
BUILD_EXCLUDE_DIRS = ("diff", "diff_temporary")
BUILDS_KEEP = 200                  # builds.json 에 남길 성공 빌드 수(한 건 200바이트 안팎)

# 여러 논문 뷰어를 동시에 열어도 탭을 헷갈리지 않게 다는 이름표(§동시 인스턴스). 길이 제한은 도구 줄·탭
# 제목이 한 논문 이름으로 끝없이 길어지지 않게 하는 안전판이다.
LABEL_MAX = 40
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# 다크·라이트 테마 배경(--bg #14161a / #e9ebef) 모두에서, 그리고 흰 글자(칩 텍스트) 아래에서도 대비가
# 충분한 채도 높은 "700번대" 팔레트. 이름표 문자열의 해시로 하나를 고른다 — 같은 이름표는 항상 같은 색.
ACCENT_PALETTE = ("#1d4ed8", "#047857", "#be123c", "#6d28d9",
                   "#0e7490", "#c2410c", "#a21caf", "#4d7c0f")

# 핀 파일을 만지는 모든 경로가 이 잠금 하나를 거친다. 잠금 없이 읽고-고치고-쓰면
# 동시에 저장한 핀 30건 중 2건만 남는다(실측) — 나머지는 서로의 쓰기에 덮인다.
PIN_LOCK = threading.RLock()
# latexmk 두 개가 같은 build/ 에서 돌면 서로의 .aux 를 밟는다.
BUILD_LOCK = threading.Lock()
# BUILD_STATE 딕셔너리(진행 칩·오류 패널용)를 보호한다. BUILD_LOCK(한 번에 하나만 빌드)과는
# 별개다 — 이 잠금은 그 상태를 "읽는" GET /api/build 요청과 경합하지 않게 하는 용도다.
BUILD_STATE_LOCK = threading.Lock()
BUILD_STATE = {"state": "idle", "phase": None, "started_at": None, "start_ts": None,
               "last_s": None, "pages": 0, "errors": [], "log_tail": "", "built_at": None,
               "seq": 0, "finished_at": None, "last": None, "head": None, "pull": None}
# builds.json(빌드 이력)의 읽기-고치기-쓰기를 묶는다.
BUILDS_LOCK = threading.Lock()


class Cfg:
    """실행 인자를 담는다. 프로젝트 고유값은 전부 여기를 거친다."""
    src: Path
    main: Path
    state: Path
    build: Path
    port: int
    dpi: int
    envs: tuple
    timeout: int
    allow: frozenset
    origin_check: bool = True
    git_pull: bool = False
    pdfjs_dir: Path = None          # None = default_pdfjs_dir()
    label: str = "원고"             # 여러 인스턴스를 구분하는 이름표(§동시 인스턴스). main() 이 채운다
    accent: str = ACCENT_PALETTE[0]  # 이름표의 강조색(#rrggbb)
    repo: str = None                # --manuscript 의 git origin URL. 없으면 None

    @property
    def pins_jsonl(self) -> Path:
        return self.state / "pins.jsonl"

    @property
    def pins_md(self) -> Path:
        return self.state / "pins.md"

    @property
    def dropped(self) -> Path:
        return self.state / "pins.dropped.jsonl"

    @property
    def seq(self) -> Path:
        return self.state / "pins.seq"

    @property
    def pages_ptr(self) -> Path:
        return self.state / "pages.cur"

    @property
    def built_src_mtime_file(self) -> Path:
        return self.state / "built_src_mtime.txt"

    @property
    def builds_file(self) -> Path:
        return self.state / "builds.json"


C = Cfg()


# ---------------------------------------------------------------- 문서(§여러 문서, references/design.md §여러 문서)
#
# 논문 저장소 하나에는 본문·답변서·커버레터처럼 문서가 여럿 있다. 뷰어 하나(주소 하나)가 그 문서들을 전환한다.
# 핀 저장소(pins.jsonl·pins.seq)는 하나다 — 번호가 문서를 가로질러 유일해야 '#12 처리해줘'가 모호하지 않다.
# 빌드·쪽 이미지·PDF 사본·빌드 이력은 문서별 폴더(Doc.dir)에 둔다. 요청 하나는 문서 하나를 다루고, 그 문서를
# 스레드 지역 값(using_doc)으로 건다 — 빌드·쪽 함수들이 인자 없이 '지금 문서'를 보게 해 기존 경로를 그대로 쓴다.

DOC_KEY_RE = re.compile(r"[a-z0-9-]{1,24}")
DOC_NAME_MAX = 40
DOCS_MAX = 12
DEFAULT_DOC_KEY = "main"


class Doc:
    """문서 하나. kind 는 'tex'(LaTeX, SyncTeX 로 줄을 되짚는다) 또는 'pdf'(보기 전용 — 쪽·영역만).

    legacy=True 는 --doc 없이 띄운 단일 문서다. 원고 경로·상태 폴더를 C 에서 그때그때 읽는다(C.src·C.main·
    C.state·C.build) — 옛 상태 폴더 배치를 그대로 쓰고, C 를 바꿔 끼우는 회귀 테스트도 그대로 돈다.
    root=True 면 빌드 산출물을 상태 폴더 루트에 둔다(단일 문서와 같은 자리). --doc 에서는 키가 main 인
    LaTeX 문서만 그렇다 — 단일 문서 인스턴스에 문서를 더해도 본문의 빌드 이력(위치 추정의 원천)이 이어진다."""

    def __init__(self, key: str, name: str, kind: str = "tex", src: Path = None, main: Path = None,
                 legacy: bool = False, root: bool = None, lock=None, bstate=None, bstate_lock=None,
                 builds_lock=None, mcache=None):
        self.key, self.name, self.kind = key, name, kind
        self._src, self._main, self.legacy = src, main, legacy
        self.root = legacy if root is None else root
        self.lock = lock or threading.Lock()
        self.bstate = bstate if bstate is not None else _fresh_build_state()
        self.bstate_lock = bstate_lock or threading.Lock()
        self.builds_lock = builds_lock or threading.Lock()
        self.mcache = mcache if mcache is not None else [None, 0.0, 0.0]

    @property
    def src(self) -> Path:
        """빌드 루트 — 빌드 사본으로 복사하는 범위. 보기 전용이면 PDF 가 든 폴더."""
        return C.src if self.legacy else self._src

    @property
    def main(self) -> Path:
        """LaTeX 면 메인 .tex, 보기 전용이면 그 PDF 파일."""
        return C.main if self.legacy else self._main

    @property
    def dir(self) -> Path:
        """쪽 이미지·빌드 이력·built_at 등 문서별 상태 폴더."""
        return C.state if self.root else C.state / "docs" / self.key

    @property
    def build(self) -> Path:
        return C.build if self.legacy else self.dir / "build"

    @property
    def main_rel(self) -> Path:
        try:
            return self.main.relative_to(self.src)
        except ValueError:
            return Path(self.main.name)

    @property
    def out(self) -> Path:
        """latexmk 를 돌리고 PDF 가 나오는 폴더. --doc 문서는 메인 .tex 가 있는 폴더에서 돈다(평소 그 폴더에서
        latexmk 하던 그대로 — '::' 앞의 빌드 루트는 복사 범위일 뿐이다). 단일 문서는 예전처럼 빌드 루트다."""
        return self.build if self.legacy else self.build / self.main_rel.parent

    @property
    def pdf_name(self) -> str:
        """쪽 디렉토리 안 PDF 사본 이름."""
        return self.main.stem + ".pdf"

    @property
    def is_pdf(self) -> bool:
        return self.kind == "pdf"

    def rel_path(self) -> str:
        """--manuscript 기준 상대경로(표시·pins.md 머리용). 메인 파일을 가리킨다."""
        try:
            return str(self.main.resolve().relative_to(C.src.resolve()))
        except (ValueError, OSError, RuntimeError):
            return str(self.main)


def _fresh_build_state() -> dict:
    return {"state": "idle", "phase": None, "started_at": None, "start_ts": None,
            "last_s": None, "pages": 0, "errors": [], "log_tail": "", "built_at": None,
            "seq": 0, "finished_at": None, "last": None, "head": None, "pull": None}


class HTTPError(Exception):
    """핸들러가 그대로 JSON 오류 응답으로 바꾼다."""

    def __init__(self, code: int, msg: str, **extra):
        super().__init__(msg)
        self.code = code
        self.body = dict({"error": msg}, **extra)


def now_str() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def atomic_write(path: Path, text: str) -> None:
    """같은 디렉토리의 임시 파일에 쓰고 os.replace 한다 — 읽는 쪽은 옛 파일 아니면 새 파일만 본다."""
    tmp = path.with_name(".%s.tmp%d.%d" % (path.name, os.getpid(), threading.get_ident()))
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- 기동 준비

def detect_main(src: Path) -> Path:
    """최상위 .tex 를 찾는다. 모호하면 추측하지 않고 후보를 보여주고 멈춘다."""
    cands = [p for p in sorted(src.glob("*.tex"))
             if "\\documentclass" in p.read_text(encoding="utf-8", errors="ignore")[:20000]]
    if len(cands) == 1:
        return cands[0]
    how = "찾지 못했습니다" if not cands else "여러 개 찾았습니다"
    listing = "\n".join("  - %s" % p.name for p in cands) or "  (없음)"
    sys.exit("%s 에서 최상위 .tex 를 %s. --main 으로 지정하세요.\n%s" % (src, how, listing))


def free_port(start: int = 18300, end: int = 18400) -> int:
    """비어 있는 포트를 찾는다. 남의 포트를 빼앗지 않는 것이 요점이다."""
    for p in range(start, end):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    sys.exit("%d-%d 구간에 빈 포트가 없습니다. --port 로 지정하세요." % (start, end))


def state_slug(src: Path) -> str:
    """원고마다 상태를 분리한다 — 원고 A·B 를 동시에 열어도 핀이 섞이지 않게."""
    return "%s-%s" % (src.name, hashlib.sha1(str(src).encode()).hexdigest()[:8])


# ---------------------------------------------------------------- 인스턴스 이름표(§동시 인스턴스)

def git_remote_url(src: Path):
    """--manuscript 의 git origin URL. git 저장소가 아니거나 origin 이 없으면 None — 실패해도 기동을 막지 않는다."""
    if not shutil.which("git"):
        return None
    try:
        r = subprocess.run(["git", "-C", str(src), "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    url = r.stdout.strip()
    return url if r.returncode == 0 and url else None


def repo_name_from_url(url: str) -> str:
    """git remote URL 마지막 조각에서 저장소 이름만 뽑는다(.git 접미사·트레일링 슬래시 제거).

    scp 스타일(user@host:name, '/' 없이 ':' 로만 경로를 구분)도 받는다 — '/' 가 있으면 그걸 기준으로
    자르고, 없을 때만 ':' 기준으로 자른다(호스트명의 ':' 를 이름으로 착각하지 않게)."""
    tail = url.rstrip("/")
    tail = tail.rsplit("/", 1)[-1] if "/" in tail else tail.rsplit(":", 1)[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail


def default_label(src: Path, repo_url) -> str:
    """--label 이 없을 때 쓸 기본 이름표: git 저장소 이름, 없으면 원고 폴더 이름."""
    if repo_url:
        name = repo_name_from_url(repo_url)
        if name:
            return name
    return src.name


def clean_label(v) -> str:
    """이름표를 검증한다. 줄바꿈·과도한 길이는 도구 줄·탭 제목을 깨뜨리므로 여기서 막는다."""
    v = "" if v is None else str(v).strip()
    v = " ".join(v.split())         # 줄바꿈·탭·중복 공백을 한 칸으로
    if not v:
        v = "원고"
    if len(v) > LABEL_MAX:
        sys.exit("--label 은 %d자 이하여야 합니다: %r" % (LABEL_MAX, v))
    return v


def pick_accent(label: str) -> str:
    """이름표 문자열의 해시로 팔레트에서 하나를 고른다 — 같은 이름표는 항상 같은 색."""
    idx = int(hashlib.sha1(label.encode("utf-8")).hexdigest(), 16) % len(ACCENT_PALETTE)
    return ACCENT_PALETTE[idx]


def valid_accent(v) -> bool:
    return isinstance(v, str) and ACCENT_RE.fullmatch(v) is not None


def favicon_href(label: str, accent: str) -> str:
    """이름표 첫 글자를 강조색 원 안에 넣은 SVG data URL. data: 안의 특수문자는 quote 로 인코딩한다."""
    ch = (label.strip()[:1] or "?").upper()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<circle cx="16" cy="16" r="16" fill="%s"/>'
           '<text x="16" y="21" text-anchor="middle" font-family="sans-serif" font-size="16" '
           'font-weight="700" fill="#ffffff">%s</text></svg>') % (accent, html.escape(ch, quote=True))
    return "data:image/svg+xml," + quote(svg, safe="")


def build_html(label: str, accent: str) -> str:
    """뷰어 HTML 템플릿의 __LABEL__·__ACCENT__·__FAVICON_HREF__ 자리표시자를 채운다.

    실행 인자(라벨·강조색)에 좌우되므로 argparse 뒤(main())에서 호출한다 — 모듈 로드 시점에 정해지는
    __PDFJS_VERSION__ 과 달리 이건 C 가 채워진 다음에만 값이 있다."""
    out = HTML.replace("__LABEL__", html.escape(label, quote=True))
    out = out.replace("__ACCENT__", accent)
    out = out.replace("__FAVICON_HREF__", favicon_href(label, accent))
    return out


# ---------------------------------------------------------------- 쪽 이미지 버전 디렉토리

def cur_pages() -> Path:
    """지금 보여 줄 쪽 이미지 디렉토리. pages.cur 포인터가 가리킨다.

    포인터가 없으면 옛 레이아웃(<state>/pages/)을 그대로 쓴다 — 재빌드 없이 이관된다.
    문서마다 따로다(cur_doc().dir — 단일 문서는 상태 폴더 루트)."""
    base = cur_doc().dir
    try:
        name = (base / "pages.cur").read_text(encoding="utf-8").strip()
    except OSError:
        name = ""
    if name and PAGES_DIR_RE.fullmatch(name) and (base / name).is_dir():
        return base / name
    return base / "pages"


def valid_build_name(v) -> bool:
    return isinstance(v, str) and PAGES_DIR_RE.fullmatch(v) is not None


def pages_dir_for(name) -> Path:
    """브라우저가 지금 보고 있는 빌드의 쪽 디렉토리. 이름이 틀렸거나 이미 지워졌으면 지금 것을 쓴다.

    재빌드가 끝난 뒤 뷰어가 새 화면으로 바꾸기 전(폴링 틈새)의 드래그는 옛 레이아웃 좌표다 —
    그 좌표를 새 PDF 에 대 보면 다른 줄을 짚는다. 직전 빌드 디렉토리는 한 번 더 남겨 두므로
    (_build 가 현재+직전을 유지) 대개 화면과 같은 PDF 로 되짚을 수 있다."""
    base = cur_doc().dir
    if valid_build_name(name) and (base / name).is_dir():
        return base / name
    return cur_pages()


def default_pdfjs_dir() -> Path:
    """레포 배치(scripts/ 옆의 vendor/pdfjs)를 먼저, 사본을 한 디렉토리에 둔 배치(pin_server.py 옆 vendor/pdfjs)를 다음으로 본다."""
    here = Path(__file__).resolve().parent
    for d in (here.parent / "vendor" / "pdfjs", here / "vendor" / "pdfjs"):
        if d.is_dir():
            return d
    return here.parent / "vendor" / "pdfjs"


def vendor_file(name: str):
    """GET /vendor/pdfjs/<name> 이 줄 파일. 이름 한 칸(.mjs)만 받고 디렉토리 밖은 절대 가리키지 않는다.

    이름 규칙이 '/'·'..'·'%' 를 모두 거르지만, 심볼릭 링크 등으로 밖을 가리키는 경우까지 resolve 로 한 번 더 막는다."""
    if not isinstance(name, str) or not VENDOR_FILE_RE.fullmatch(name) or ".." in name:
        return None
    base = C.pdfjs_dir or default_pdfjs_dir()
    try:
        base = base.resolve()
        f = (base / name).resolve()
    except (OSError, RuntimeError):
        return None
    if f.parent != base or not f.is_file():
        return None
    return f


def build_pdf(name) -> Path:
    """GET /pdf?build=<name> 이 줄 PDF — 그 빌드의 쪽 이미지와 짝인 사본(pages-<build>/<main>.pdf)만 준다.

    cur_pdf 와 달리 build/ 로 물러서지 않는다. build/ 의 것은 재빌드가 제자리에서 덮어써 화면의 쪽 이미지와
    어긋날 수 있다 — 뷰어가 그 위에서 좌표를 재면 PNG 와 다른 자리를 짚는다. 없으면 None."""
    D = cur_doc()
    if name in (None, ""):
        pdir = cur_pages()
    elif valid_build_name(name) and (D.dir / name).is_dir():
        pdir = D.dir / name
    else:
        return None
    f = pdir / D.pdf_name
    return f if f.is_file() else None


def cur_pdf(pdir: Path = None) -> Path:
    """쪽 이미지와 짝이 맞는 PDF. 버전 디렉토리에 사본이 있으면 그것을, 없으면(옛 레이아웃) build/ 의 것을 쓴다.

    짝을 맞추는 이유: 빌드가 실패해도 화면은 옛 PDF 인데, pick 이 새로 깨진 PDF 를 읽으면
    보이는 것과 다른 자리를 짚는다."""
    D = cur_doc()
    f = (pdir or cur_pages()) / D.pdf_name
    if f.exists():
        return f
    if D.is_pdf:                                          # 보기 전용: 아직 쪽을 안 그렸으면 원본 PDF
        return D.main
    return D.out / D.pdf_name


def build_ref_mtime(name: str):
    """그 빌드를 시작할 때의 원고 src_mtime(빌드 이력 → built_src_mtime.txt → PDF 시각 순으로 찾는다)."""
    ent = load_builds()["by"].get(name)
    if ent and _is_num(ent.get("src_mtime")):
        return float(ent["src_mtime"])
    if name == cur_pages().name:
        v = read_built_src_mtime()
        if v is not None:
            return v
    try:
        return cur_pdf(pages_dir_for(name)).stat().st_mtime
    except OSError:
        return None


def source_newer(name: str = None) -> float:
    """원고가 그 빌드(기본: 지금 화면의 빌드)보다 새로우면 그 차이(초)를, 아니면 0.0 을 돌려준다.

    화면이 낡은 PDF 면 드래그한 자리와 원문이 어긋난다. 그런데 텍스트 경로는 그래도
    비슷한 문단을 찾아내 경고선(0.3)을 아슬하게 넘기기도 한다 — 실측에서 노멘클래처를
    골랐는데 서론의 기여 목록이 0.32 로 경고 없이 돌아왔다. 점수로는 이 상황을 못 거르므로
    사실 자체를 알린다. 비교 기준은 '빌드 시작 때의 src_mtime' 이다 — 빌드 도중에 고친 파일도
    잡히고, 빌드에 안 들어가는 diff/ 는 src_mtime 이 이미 뺀다(옛 구현은 *.tex 전부와 PDF 시각을 봤다)."""
    ref = build_ref_mtime(name or cur_pages().name)
    if ref is None:
        return 0.0
    return max(0.0, src_mtime() - ref)


def migrate_pages() -> None:
    """옛 레이아웃(<state>/pages/ + build/<main>.pdf)을 버전 디렉토리처럼 만든다.

    PDF·synctex 사본을 pages/ 에 넣어 두어야 pick 이 화면의 쪽과 같은 PDF 를 읽는다 —
    build/ 의 것은 재빌드가 제자리에서 덮어쓴다(빌드 중이거나 뒤 단계에서 실패하면 어긋난다)."""
    D = cur_doc()
    if D.is_pdf:
        return
    legacy = D.dir / "pages"
    if not legacy.is_dir():
        return
    ptr = D.dir / "pages.cur"
    if not ptr.exists():
        atomic_write(ptr, "pages")
    if cur_pages() != legacy:
        return
    for suf in (".pdf", ".synctex.gz"):
        src, dst = D.out / (D.main.stem + suf), legacy / (D.main.stem + suf)
        if src.is_file() and not dst.exists():
            tmp = dst.with_name(dst.name + ".tmp")
            try:
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
            except OSError as e:
                print("경고: %s 를 쪽 디렉토리로 복사하지 못했습니다: %s" % (src.name, e), file=sys.stderr)


# ---------------------------------------------------------------- 빌드

def latex_errors(text: str) -> list:
    """'! ' 줄과 그 뒤 첫 'l.<n>' 줄을 최대 5건 뽑는다(파일 추정은 하지 않는다)."""
    out = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if not ln.startswith("! "):
            continue
        line_no = None
        for nxt in lines[i + 1:i + 40]:
            m = re.match(r"l\.(\d+)", nxt)
            if m:
                line_no = int(m.group(1))
                break
            if nxt.startswith("! "):
                break
        out.append({"line": line_no, "msg": ln[2:].strip()[:200]})
        if len(out) >= 5:
            break
    return out


def run_logged(cmd: list, cwd: Path, timeout: int):
    """프로세스 그룹째 돌리고, 시간이 넘으면 그룹째 죽인다(latexmk 가 띄운 pdflatex 까지)."""
    try:
        p = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             encoding="utf-8", errors="replace", start_new_session=True)
    except FileNotFoundError:
        return None, "%s 를 찾지 못했습니다." % cmd[0], False
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        out, _ = p.communicate()
        return None, (out or "") + "\n[시간 초과 %d초 — 빌드를 중단했습니다]" % timeout, True


def build_state_update(**kw) -> None:
    D = cur_doc()
    with D.bstate_lock:
        D.bstate.update(kw)


def build_state_snapshot() -> dict:
    """GET /api/build 가 돌려줄 모양. 돌아가는 중이면 elapsed_s 를 지금 시각으로 다시 잰다."""
    D = cur_doc()
    with D.bstate_lock:
        d = dict(D.bstate)
    t0 = d.pop("start_ts", None)
    d["elapsed_s"] = round(time.time() - t0, 1) if d.get("state") == "running" and t0 else d.get("elapsed_s") or 0.0
    if d.get("built_at") is None:
        try:
            d["built_at"] = (D.dir / "built_at.txt").read_text().strip()
        except OSError:
            d["built_at"] = None
    return d


LOG_TAIL_LINES = 40                # 성공하지 않은 빌드에서 다이어트 응답에 남기는 줄 수(§P0c-F)


def diet_log(payload: dict, full: bool) -> dict:
    """에이전트 응답 다이어트: state=='ok' 면 log·log_tail 을 뺀다(성공 때도 폰트 경로로 수 KB였다).
    ok_errors|fail 은 마지막 LOG_TAIL_LINES 줄로 줄인다. full(?log=1)이면 손대지 않는다.
    내부 상태(BUILD_STATE·builds.json)는 그대로 두고 HTTP 응답 직전에만 적용한다."""
    if full:
        return payload
    out = dict(payload)
    state = out.get("state")
    for key in ("log", "log_tail"):
        if key not in out:
            continue
        if state == "ok":
            out.pop(key, None)
        else:
            out[key] = "\n".join(str(out[key] or "").splitlines()[-LOG_TAIL_LINES:])
    return out


def build_all() -> dict:
    """PDF 를 다시 만든다(동기). 이미 빌드 중이면 기다리지 않고 busy 를 돌려준다.
    잠금은 문서마다 하나다 — 서로 다른 문서는 동시에 빌드된다(빌드 폴더가 문서마다 따로다)."""
    lock = cur_doc().lock
    if not lock.acquire(blocking=False):
        return {"ok": False, "busy": True}
    try:
        return _build_tracked()
    finally:
        lock.release()


def build_async() -> dict:
    """POST /api/rebuild?async=1: 잠금을 얻으면 데몬 스레드로 같은 빌드 함수를 돌리고 바로 돌아온다."""
    D = cur_doc()
    if not D.lock.acquire(blocking=False):
        return {"state": "running", "busy": True}
    build_state_update(state="running", phase="copy", started_at=now_str(), start_ts=time.time())

    def worker():
        with using_doc(D):                             # 빌드 스레드도 같은 문서를 본다
            try:
                _build_tracked()
            except Exception as e:                     # noqa: BLE001 — _build_tracked 자체가 죽어도 running 에 멈추지 않는다
                finish_build({"ok": False, "state": "fail", "errors": [],
                              "log": "빌드 스레드에서 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}, None)
            finally:
                D.lock.release()
    threading.Thread(target=worker, daemon=True).start()
    return {"state": "running"}


def _build_tracked() -> dict:
    """_build() 를 감싸 BUILD_STATE(진행 칩·오류 패널용)와 빌드 이력을 채운다. 동기·비동기 양쪽이 같은 경로를 쓴다.

    _build() 가 예상 밖 예외를 내도(예: rsync/latexmk 호출 근처의 OSError) BUILD_STATE 를 running 에
    묶어 두지 않는다 — 비동기 워커에서 이 함수가 죽으면 다음 폴링이 영원히 '만드는 중'을 보여 주게 된다.
    built_src_mtime 은 '이 빌드가 실제로 컴파일한 원고'의 mtime 으로 확정한다 — --git-pull 이면 pull 뒤
    (fast-forward 가 .tex mtime 을 밀어 올릴 수 있다), 아니면 복사 직전 실측한 값을 _build() 가
    res["src_mtime"] 으로 돌려준다(force=True, 2초 캐시를 건너뜀). _build() 가 그 값을 못 돌려줄 때만
    (PDF 문서, 또는 res["src_mtime"] 이 채워지기 전에 실패) 빌드 시작 시각(src_mtime_at_start)으로
    대신한다. ok|ok_errors 로 끝났을 때만 파일에 확정한다 — 실패하면 화면은 옛 PDF 그대로이므로
    '원고 수정됨' 배지가 꺼지면 안 된다."""
    D = cur_doc()
    with D.bstate_lock:
        last_s = D.bstate.get("last_s")
    build_state_update(state="running", phase="copy", started_at=now_str(), start_ts=time.time(),
                        last_s=last_s, errors=[], log_tail="")
    src_mtime_at_start = src_mtime(force=True)
    try:
        res = _render_pdf_doc() if D.is_pdf else _build()
    except Exception as e:                            # noqa: BLE001 — 빌드가 죽어도 running 에 멈추지 않는다
        res = {"ok": False, "state": "fail", "errors": [],
               "log": "빌드 중 예상 밖 예외가 났습니다: %r" % e, "elapsed_s": 0.0}
    src_mtime_for_build = res.get("src_mtime")
    if not _is_num(src_mtime_for_build):
        src_mtime_for_build = src_mtime_at_start          # PDF 문서·복사 전 실패 등 res 에 못 채운 경우의 대체값
    if res.get("state") in ("ok", "ok_errors"):
        write_built_src_mtime(src_mtime_for_build)
    finish_build(res, src_mtime_for_build)
    return res


def finish_build(res: dict, src_mtime_for_build) -> None:
    """빌드 하나가 끝났다(성공·실패 무관) — 이력에 남기고 build_seq 를 올린 뒤 BUILD_STATE 를 바꾼다.

    src_mtime_for_build 는 '이 빌드가 실제로 컴파일한 원고'의 mtime(--git-pull 이면 pull 뒤,
    아니면 복사 직전 실측 — 호출부 _build_tracked() 참조)이다. build_ref_mtime() 이 이 이력
    엔트리를 built_src_mtime.txt 보다 먼저 찾으므로, 여기 기록되는 값이 '원고 수정됨' 배지의
    실질적 기준선이다.

    build_seq 는 '끝난 빌드 수'다. 뷰어는 이 값이 바뀌었는지로 자기가 못 본 빌드를 알아챈다 —
    5초 폴링 틈새에 시작해 끝난 빌드도 running 을 한 번도 못 봤을 뿐 seq 는 올라 있다.
    seq 와 최종 state 는 한 번에 바꾼다(최종 state 인데 seq 는 옛 값인 순간이 보이지 않게)."""
    state = res.get("state", "fail")
    last = {"state": state, "errors": list(res.get("errors") or [])[:5],
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_s": res.get("elapsed_s", 0.0), "log_tail": str(res.get("log") or "")[-4000:],
            "head": res.get("head"), "pull": res.get("pull")}
    D = cur_doc()
    with D.bstate_lock:
        last["started_at"] = D.bstate.get("started_at")
    ent = None
    if state in ("ok", "ok_errors") and res.get("build"):
        ent = {"build": res["build"], "src_mtime": src_mtime_for_build, "src_hash": res.get("src_hash"),
               "finished_at": last["finished_at"]}
    seq = record_build(last, ent)
    build_state_update(state=state, phase=None, start_ts=None, seq=seq, finished_at=last["finished_at"],
                        elapsed_s=last["elapsed_s"], last_s=last["elapsed_s"],
                        pages=res.get("pages", 0), errors=last["errors"], head=last["head"], pull=last["pull"],
                        log_tail=res.get("log", ""), built_at=_read_built_at(),
                        last={"state": state, "errors": last["errors"], "finished_at": last["finished_at"],
                              "seq": seq, "head": last["head"], "pull": last["pull"]})


# ---------------------------------------------------------------- 빌드 이력(builds.json)과 원고 지문
#
# 위치 추정(.est)을 서버가 판정하려면 '핀을 찍을 때 화면에 있던 빌드'와 '지금 빌드'가 같은 원고에서
# 나왔는지를 알아야 한다. 그래서 빌드마다 쪽 디렉토리 이름(build id)과 그 빌드가 컴파일한 원고의
# 지문(내용 해시 + 시작 때 src_mtime)을 남긴다. 벽시계 비교(옛 방식)는 브라우저 시간대·메모 편집·
# 낡은 PDF 위 핀에서 전부 틀렸다(독립 검증 실측).

def _empty_builds() -> dict:
    return {"seq": 0, "builds": [], "last": None}


def _valid_build_entry(b) -> bool:
    return (isinstance(b, dict) and valid_build_name(b.get("build"))
            and (b.get("src_mtime") is None or _is_num(b.get("src_mtime")))
            and (b.get("src_hash") is None or isinstance(b.get("src_hash"), str)))


def load_builds() -> dict:
    """{seq, builds, last, by}. 파일이 없거나 깨졌으면 빈 이력 — 이력이 없어도 서버는 돈다(추정이 보수적일 뿐)."""
    try:
        d = json.loads((cur_doc().dir / "builds.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        d = None
    out = _empty_builds()
    if isinstance(d, dict):
        if _is_int(d.get("seq")) and d["seq"] >= 0:
            out["seq"] = d["seq"]
        if isinstance(d.get("builds"), list):
            out["builds"] = [b for b in d["builds"] if _valid_build_entry(b)]
        if isinstance(d.get("last"), dict):
            out["last"] = d["last"]
    out["by"] = {b["build"]: b for b in out["builds"]}
    return out


def _write_builds(h: dict) -> None:
    body = {"seq": h["seq"], "last": h["last"], "builds": h["builds"][-BUILDS_KEEP:]}
    try:
        atomic_write(cur_doc().dir / "builds.json", json.dumps(body, ensure_ascii=False, indent=1) + "\n")
    except OSError as e:
        print("경고: 빌드 이력을 쓰지 못했습니다: %s" % e, file=sys.stderr)


def record_build(last: dict, ent) -> int:
    """끝난 빌드 하나를 이력에 더하고 새 seq 를 돌려준다. 쓰기가 실패해도 seq 는 오른다(메모리 기준)."""
    D = cur_doc()
    with D.builds_lock:
        h = load_builds()
        with D.bstate_lock:
            seq = max(h["seq"], int(D.bstate.get("seq") or 0)) + 1
        h["seq"] = seq
        h["last"] = dict(last, seq=seq, build=ent["build"] if ent else None)
        if ent:
            ent = dict(ent, seq=seq)
            h["builds"] = [b for b in h["builds"] if b["build"] != ent["build"]] + [ent]
        _write_builds(h)
        return seq


def seed_builds() -> None:
    """이력에 없는 지금 빌드(옛 인스턴스가 만든 것)를 한 번 올리고, 마지막 빌드 결과를 BUILD_STATE 로 되살린다.

    그 빌드가 어떤 원고로 만들어졌는지는 모른다. 다만 지금 원고의 src_mtime 이 그 빌드 기준 시각
    (built_src_mtime.txt, 없으면 PDF 시각) 이하면 그 뒤로 고친 파일이 없다는 뜻이므로 지금 원고의
    지문을 그 빌드의 지문으로 삼는다 — 그래야 기동 뒤 처음 찍은 핀이 '원고를 안 바꾼 재빌드'에서
    추정으로 오탐되지 않는다. 판단이 안 서면 지문을 비워 둔다(그 빌드의 핀은 다음 빌드 뒤 보수적으로 추정)."""
    D = cur_doc()
    with D.builds_lock:
        h = load_builds()
        cur = cur_pages()
        if cur.is_dir() and cur.name not in h["by"] and any(cur.glob("page-*.png")):
            bsm = read_built_src_mtime()
            ref = bsm
            if ref is None:
                try:
                    ref = cur_pdf(cur).stat().st_mtime
                except OSError:
                    ref = None
            ent = {"build": cur.name, "seq": h["seq"], "src_mtime": bsm, "src_hash": None,
                   "finished_at": _read_built_at(), "seeded": True}
            now_m = src_mtime(force=True)
            if ref is not None and now_m <= ref + 1e-6:
                ent["src_hash"] = doc_fingerprint(D)
                if ent["src_mtime"] is None:
                    ent["src_mtime"] = now_m
            h["builds"].append(ent)
            _write_builds(h)
    last = h.get("last") or {}
    kw = {"seq": h["seq"]}
    if last.get("state") in ("ok", "ok_errors", "fail"):
        errs = [e for e in (last.get("errors") or []) if isinstance(e, dict)][:5]
        kw.update(state=last["state"], errors=errs, log_tail=str(last.get("log_tail") or ""),
                  started_at=last.get("started_at"), finished_at=last.get("finished_at"),
                  last_s=last.get("elapsed_s"), elapsed_s=last.get("elapsed_s"),
                  head=last.get("head"), pull=last.get("pull"),
                  last={"state": last["state"], "errors": errs, "finished_at": last.get("finished_at"),
                        "seq": h["seq"], "head": last.get("head"), "pull": last.get("pull")})
    build_state_update(**kw)


def _read_built_at():
    try:
        return (cur_doc().dir / "built_at.txt").read_text().strip()
    except OSError:
        return None


def _read_head():
    try:
        return (cur_doc().dir / "head.txt").read_text().strip()
    except OSError:
        return None


# ---------------------------------------------------------------- --git-pull(§P0c-E)
#
# 재빌드 copy 단계 전에 원고 저장소를 원격 main 으로 fast-forward 한다. 공저자가 PR 을 머지해도
# 서버 쪽 체크아웃은 그대로였다 — 뷰어가 옛 원고를 계속 보여 줬다. 실패해도(더러움·분기·업스트림
# 없음) 빌드 자체는 지금 체크아웃으로 계속한다 — pull 은 있으면 좋은 것이지 빌드의 전제조건이 아니다.

def _git(args: list, cwd, timeout: int = GIT_PULL_TIMEOUT):
    """git 을 쉘 없이 돌린다. 인자에 사용자 입력을 넣지 않는다. (returncode, stdout, stderr).
    시간 초과·실행 실패는 returncode=None 으로 구분한다."""
    try:
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), timeout=timeout, capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr
    except (subprocess.TimeoutExpired, OSError):
        return None, "", ""


def git_pull_phase(manuscript: Path) -> dict:
    """{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}.

    순서: 저장소 루트 탐색(아니면 skipped:not_git) → fetch(실패하면 error) → 업스트림 확인
    (없으면 skipped:no_upstream) → 더러움 확인(있으면 skipped:dirty) → --ff-only 머지
    (분기했으면 skipped:diverged). 어느 단계든 git 호출 자체가 시간 초과·실행 실패면 error."""
    rc, top, _ = _git(["-C", str(manuscript), "rev-parse", "--show-toplevel"], manuscript)
    if rc != 0 or not top.strip():
        return {"state": "skipped", "reason": "not_git", "head_before": None, "head_after": None}
    root = top.strip()

    rc, before, _ = _git(["-C", root, "rev-parse", "HEAD"], root)
    head_before = before.strip() if rc == 0 else None

    rc, _out, _err = _git(["-C", root, "fetch", "--quiet"], root)
    if rc != 0:
        reason = "fetch_timeout" if rc is None else "fetch_failed"
        return {"state": "error", "reason": reason, "head_before": head_before, "head_after": head_before}

    rc, _out, _err = _git(["-C", root, "rev-parse", "--abbrev-ref", "@{u}"], root)
    if rc != 0:
        return {"state": "skipped", "reason": "no_upstream", "head_before": head_before, "head_after": head_before}

    rc, dirty, _err = _git(["-C", root, "status", "--porcelain", "--untracked-files=no"], root)
    if rc != 0:
        return {"state": "error", "reason": "status_failed", "head_before": head_before, "head_after": head_before}
    if dirty.strip():
        return {"state": "skipped", "reason": "dirty", "head_before": head_before, "head_after": head_before}

    rc, _out, _err = _git(["-C", root, "merge", "--ff-only", "@{u}"], root)
    if rc != 0:
        return {"state": "skipped", "reason": "diverged", "head_before": head_before, "head_after": head_before}

    rc, after, _err = _git(["-C", root, "rev-parse", "HEAD"], root)
    head_after = after.strip() if rc == 0 else head_before
    state = "up_to_date" if head_after == head_before else "ok"
    return {"state": state, "reason": None, "head_before": head_before, "head_after": head_after}


_PULL_LOCK = threading.Lock()
_PULL_LAST = {"at": 0.0, "res": None}
PULL_SHARE_S = 20                  # 초 — 이 안에 다른 문서가 이미 당겼으면 그 결과를 같이 쓴다


def repo_pull() -> dict:
    """--git-pull 은 저장소 단위다. 단일 문서는 빌드마다 한 번(예전 그대로). 여러 문서면 잠금 하나로 줄 세우고,
    PULL_SHARE_S 안에 다른 문서의 빌드가 이미 당겼으면 다시 당기지 않고 그 결과(shared=True)를 쓴다 — 두 문서를
    동시에 재빌드해도 git fetch·merge 가 겹치지 않고(.git/index.lock 충돌), 한쪽이 복사하는 중에 트리가 바뀌지 않는다."""
    if not multi_doc():
        return git_pull_phase(C.src)
    with _PULL_LOCK:
        last = _PULL_LAST["res"]
        if last is not None and time.time() - _PULL_LAST["at"] < PULL_SHARE_S:
            return dict(last, shared=True)
        res = git_pull_phase(C.src)
        _PULL_LAST.update(at=time.time(), res=res)
        return res


def _build() -> dict:
    """원본을 건드리지 않고 사본에서 -synctex=1 로 빌드한 뒤, 새 디렉토리에 쪽을 그리고 포인터만 바꾼다.

    판정은 세 가지다. fail = 새 PDF 가 없거나 시간 초과(화면은 옛 PDF 그대로),
    ok_errors = 새 PDF 는 나왔지만 LaTeX 오류('! ' 줄)가 있음, ok = 오류 없음."""
    t0 = time.time()
    D = cur_doc()
    D.build.mkdir(parents=True, exist_ok=True)
    res = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}

    if C.git_pull:                                        # copy 단계 전에 원격 main 으로 fast-forward(§P0c-E)
        build_state_update(phase="pull")
        res["pull"] = repo_pull()
        build_state_update(phase="copy")
    # 이 빌드가 실제로 컴파일할 원고의 mtime — pull 이 있었으면 pull 뒤(fast-forward 가 .tex mtime 을
    # 밀어 올릴 수 있다), 없었으면 지금(복사 직전)을 실측한다. _build_tracked() 가 이 값을
    # built_src_mtime/이력에 확정한다 — 빌드 시작 시각(pull 전)을 쓰면 pull 로 생긴 새 mtime이
    # '아직 안 빌드됨'으로 잘못 잡혀 성공 직후에도 '원고 수정됨' 배지가 계속 떴다.
    res["src_mtime"] = src_mtime(force=True)

    rs = shutil.which("rsync")
    try:
        if rs:
            excl = []
            for d in BUILD_EXCLUDE_DIRS:
                excl += ["--exclude", d + "/"]
            subprocess.run([rs, "-a", "--delete"] + excl + ["--exclude", "*.synctex.gz",
                            str(D.src) + "/", str(D.build) + "/"], capture_output=True, timeout=300)
        else:                                            # rsync 없이도 돌아가야 한다
            shutil.rmtree(D.build, ignore_errors=True)
            shutil.copytree(D.src, D.build, ignore=shutil.ignore_patterns(*BUILD_EXCLUDE_DIRS, "*.synctex.gz"))
    except (subprocess.TimeoutExpired, OSError) as e:
        res["log"] = "원고 사본을 만들지 못했습니다: %s" % e
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    # 지문은 사본에서 뜬다 — 이 빌드가 실제로 컴파일하는 바로 그 파일들이다(원본은 그사이 또 바뀔 수 있다).
    try:
        res["src_hash"] = source_fingerprint(D.build)
    except OSError:
        res["src_hash"] = None

    build_state_update(phase="latex")
    # 단일 문서는 예전처럼 빌드 루트에서, --doc 문서는 메인 .tex 가 있는 폴더에서 돈다(Doc.out).
    _rc, out, timed_out = run_logged(
        ["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", D.main.name], D.out, C.timeout)
    try:
        atomic_write(D.dir / "build.log", out)
    except OSError:
        pass
    tail = "\n".join(out.splitlines()[-40:])[-4000:]
    res["log"] = tail

    pdf = D.out / (D.main.stem + ".pdf")
    syn = D.out / (D.main.stem + ".synctex.gz")
    texlog = D.out / (D.main.stem + ".log")
    try:
        logtxt = texlog.read_text(encoding="utf-8", errors="replace") \
            if texlog.exists() and texlog.stat().st_mtime >= t0 - 1 else out
    except OSError:
        logtxt = out
    res["errors"] = latex_errors(logtxt)

    fresh = (not timed_out) and pdf.exists() and pdf.stat().st_mtime >= t0 - 1
    if not fresh:
        res["log"] = ("시간 초과로 멈췄습니다.\n" if timed_out else "새 PDF 가 나오지 않았습니다.\n") + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    if not syn.exists() or syn.stat().st_mtime < t0 - 1:
        res["log"] = "synctex.gz 가 없습니다 — latexmk 가 -synctex=1 을 받았는지 확인하세요.\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res

    newdir, err = _render_pages(pdf, [syn])
    if newdir is None:
        res["log"] = err + "\n" + tail
        res["elapsed_s"] = round(time.time() - t0, 1)
        return res
    head_short = _commit_pages(newdir)
    res["head"] = head_short

    res["state"] = "ok_errors" if res["errors"] else "ok"
    res["ok"] = True
    res["build"] = newdir.name
    res["pages"] = len(list(newdir.glob("page-*.png")))
    res["elapsed_s"] = round(time.time() - t0, 1)
    return res


def _render_pages(pdf: Path, extra: list):
    """새 디렉토리에 쪽을 그리고 PDF(와 extra — synctex)를 사본으로 넣는다. 끝나기 전까지 화면은 옛 디렉토리를 본다.
    (디렉토리, None) 또는 (None, 오류 문구)."""
    D = cur_doc()
    D.dir.mkdir(parents=True, exist_ok=True)
    bid = time.strftime("%Y%m%d%H%M%S")
    name = "pages-" + bid
    k = 1
    while (D.dir / name).exists():
        name = "pages-%s-%d" % (bid, k)
        k += 1
    newdir = D.dir / name
    newdir.mkdir(parents=True)
    build_state_update(phase="render")
    try:
        r = subprocess.run(["pdftoppm", "-r", str(C.dpi), "-png", str(pdf), str(newdir / "page")],
                           capture_output=True, timeout=600)
        ok_render = r.returncode == 0 and any(newdir.glob("page-*.png"))
    except (subprocess.TimeoutExpired, FileNotFoundError):
        ok_render = False
    if not ok_render:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "쪽 이미지를 그리지 못했습니다(pdftoppm)."
    try:
        shutil.copy2(pdf, newdir / D.pdf_name)
        for f in extra:
            shutil.copy2(f, newdir / f.name)
    except OSError as e:
        shutil.rmtree(newdir, ignore_errors=True)
        return None, "PDF 사본을 쪽 디렉토리에 두지 못했습니다: %s" % e
    return newdir, None


def _commit_pages(newdir: Path) -> str:
    """포인터를 새 쪽 디렉토리로 한 번에 바꾸고(원자적), 현재+직전만 남기고, built_at·head 를 쓴다. head 짧은 해시."""
    D = cur_doc()
    prev = cur_pages().name
    atomic_write(D.dir / "pages.cur", newdir.name)       # 원자적 교체 한 번
    for d in D.dir.iterdir():                            # 현재와 직전 하나만 남긴다
        if d.is_dir() and PAGES_DIR_RE.fullmatch(d.name) and d.name not in (newdir.name, prev):
            shutil.rmtree(d, ignore_errors=True)
    atomic_write(D.dir / "built_at.txt", datetime.now().astimezone().isoformat(timespec="seconds"))
    try:
        head = subprocess.run(["git", "-C", str(D.src), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10)
        head_short = head.stdout.strip() or "-"
    except (OSError, subprocess.SubprocessError):
        head_short = "-"
    atomic_write(D.dir / "head.txt", head_short)
    return head_short


# ---------------------------------------------------------------- 보기 전용 PDF 문서
#
# LaTeX 소스가 없는 PDF(리뷰어 코멘트 등)는 재빌드가 없다. 대신 그 PDF 파일이 바뀌면(mtime·크기) 쪽 이미지를
# 다시 그린다 — 같은 빌드 경로(_build_tracked → 이력·build_seq)를 타므로 뷰어는 LaTeX 재빌드와 똑같이 화면을 바꾼다.

def pdf_signature(D: Doc):
    try:
        st = D.main.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _render_pdf_doc() -> dict:
    """보기 전용 문서의 '빌드' — 원본 PDF 를 쪽 이미지로 그린다. LaTeX·SyncTeX·git pull 은 없다."""
    t0 = time.time()
    D = cur_doc()
    res = {"ok": False, "state": "fail", "errors": [], "log": "", "elapsed_s": 0.0}
    sig = pdf_signature(D)
    if sig is None:
        res["log"] = "PDF 가 없습니다: %s" % D.main
        return res
    try:
        res["src_hash"] = doc_fingerprint(D)
    except OSError:
        res["src_hash"] = None
    newdir, err = _render_pages(D.main, [])
    if newdir is None:
        res["log"] = err
        res["elapsed_s"] = round(time.time() - t0, 1)
        try:                                         # 같은 파일로 3초마다 다시 시도하지 않는다 — 파일이 바뀌면 다시 그린다
            atomic_write(D.dir / "pdf_sig.txt", sig)
        except OSError:
            pass
        return res
    res["head"] = _commit_pages(newdir)
    try:
        atomic_write(D.dir / "pdf_sig.txt", sig)
    except OSError:
        pass
    res.update(state="ok", ok=True, build=newdir.name, pages=len(list(newdir.glob("page-*.png"))),
               elapsed_s=round(time.time() - t0, 1))
    return res


def pdf_changed(D: Doc) -> bool:
    """보기 전용 PDF 가 지금 쪽 이미지를 그린 뒤 바뀌었는가(또는 아직 안 그렸는가)."""
    sig = pdf_signature(D)
    if sig is None:
        return False
    try:
        done = (D.dir / "pdf_sig.txt").read_text().strip()
    except OSError:
        done = ""
    return sig != done


def refresh_pdf_doc(D: Doc) -> bool:
    """PDF 가 바뀌었으면 백그라운드로 다시 그린다(이미 그리는 중이면 아무것도 안 한다). 시작했으면 True."""
    if not D.is_pdf or not pdf_changed(D):
        return False
    with using_doc(D):
        r = build_async()
    return not r.get("busy")


# ---------------------------------------------------------------- 메타

def png_size(path: Path) -> tuple:
    with path.open("rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


def page_list(pdir: Path = None) -> list:
    pages = []
    for p in sorted((pdir or cur_pages()).glob("page-*.png")):
        try:
            w, h = png_size(p)
        except (OSError, struct.error):
            continue
        pages.append({"name": p.name, "pt_w": w * 72.0 / C.dpi, "pt_h": h * 72.0 / C.dpi})
    return pages


SRC_TEX_EXTS = (".tex", ".bib", ".sty", ".cls", ".bst")
SRC_FIG_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg")
SRC_MTIME_EXTS = SRC_TEX_EXTS + SRC_FIG_EXTS
# 빌드 산출물 디렉토리(상태 디렉토리를 원고 안에 둔 배치 대비) + 빌드 rsync 가 빼는 디렉토리.
BUILD_OUTDIRS = ("build", "out") + BUILD_EXCLUDE_DIRS

_SRC_MTIME_CACHE: list = [None, 0.0, 0.0]     # [C.src 문자열, 값, 잰 시각] — 2초 캐시(단일 문서의 것)
_SRC_MTIME_LOCK = threading.Lock()

# 단일 문서(--doc 없음). 모듈 전역 잠금·상태를 그대로 쥐므로 옛 경로·회귀 테스트가 보던 객체가 곧 이 문서의 것이다.
LEGACY_DOC = Doc(DEFAULT_DOC_KEY, "본문", legacy=True, lock=BUILD_LOCK, bstate=BUILD_STATE,
                 bstate_lock=BUILD_STATE_LOCK, builds_lock=BUILDS_LOCK, mcache=_SRC_MTIME_CACHE)
DOCS: list = [LEGACY_DOC]
_TL = threading.local()


def set_docs(docs=None) -> None:
    """문서 목록을 바꾼다(main()·테스트). 비우면 단일 문서로 돌아간다."""
    DOCS[:] = list(docs) if docs else [LEGACY_DOC]


def cur_doc() -> Doc:
    """이 스레드가 다루는 문서. 요청 처리기·빌드 스레드가 using_doc 으로 건다. 없으면 첫 문서."""
    d = getattr(_TL, "doc", None)
    return d if d is not None else DOCS[0]


@contextlib.contextmanager
def using_doc(d):
    prev = getattr(_TL, "doc", None)
    _TL.doc = d
    try:
        yield d
    finally:
        _TL.doc = prev


def multi_doc() -> bool:
    return len(DOCS) > 1


def doc_by_key(key):
    return next((d for d in DOCS if d.key == key), None)


def pin_doc_key(r: dict) -> str:
    """핀이 속한 문서 키. doc 필드가 없는 옛 레코드는 첫 문서로 읽는다(이관 쓰기 없음)."""
    k = r.get("doc")
    return k if isinstance(k, str) and k else DOCS[0].key


def doc_for_file(path) -> Doc:
    """file 로만 온 요청(에이전트 curl)이 어느 LaTeX 문서의 것인지. 빌드 루트가 가장 깊게 감싸는 문서, 없으면 첫 문서."""
    try:
        p = Path(path) if os.path.isabs(str(path)) else C.src / str(path)
        p = p.resolve()
    except (OSError, RuntimeError, ValueError):
        return DOCS[0]
    best, depth = None, -1
    for d in DOCS:
        if d.is_pdf:
            continue
        try:
            p.relative_to(d.src.resolve())
        except (ValueError, OSError, RuntimeError):
            continue
        n = len(d.src.resolve().parts)
        if n > depth:
            best, depth = d, n
    return best or DOCS[0]


def _excluded_dir(name: str) -> bool:
    return name.startswith(".") or name in BUILD_OUTDIRS


def iter_sources(root: Path):
    """root 아래 원고·그림 확장자 파일을 (상대경로 'a/b.tex', os.DirEntry) 로 낸다.

    src_mtime(배지·낡은 PDF 경고)과 source_fingerprint(빌드 지문)가 같은 목록을 본다 — 둘이 다른 파일을
    보면 '배지는 꺼졌는데 추정은 켜짐' 같은 어긋남이 생긴다. 점(.) 디렉토리, 빌드 산출물·빌드 rsync 가
    빼는 디렉토리(BUILD_OUTDIRS), 원고 안에 둔 상태 디렉토리, 루트의 메인 PDF 는 뺀다."""
    D = cur_doc()
    main_pdf = D.pdf_name
    main_at = tuple(D.main_rel.parent.parts)            # 메인 .tex 옆의 PDF(빌드 산출물·커밋된 사본)는 원고가 아니다
    state_in_root = None
    try:
        state_in_root = tuple(C.state.resolve().relative_to(root.resolve()).parts)
    except (ValueError, OSError, RuntimeError):
        pass

    def walk(d: Path, rel_parts: tuple):
        try:
            entries = sorted(os.scandir(d), key=lambda e: e.name)
        except OSError:
            return
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if _excluded_dir(e.name):
                    continue
                parts = rel_parts + (e.name,)
                if state_in_root is not None and parts == state_in_root:
                    continue
                yield from walk(Path(e.path), parts)
            elif e.is_file(follow_symlinks=False):
                if e.name == main_pdf and rel_parts == main_at:
                    continue
                if os.path.splitext(e.name)[1].lower() in SRC_MTIME_EXTS:
                    yield "/".join(rel_parts + (e.name,)), e
    yield from walk(root, ())


def doc_fingerprint(D: Doc) -> str:
    """문서의 원고 지문. 보기 전용이면 그 PDF 파일 내용의 해시다."""
    if D.is_pdf:
        h = hashlib.sha256()
        with open(D.main, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:32]
    with using_doc(D):
        return source_fingerprint(D.src)


def source_fingerprint(root: Path) -> str:
    """원고 지문 — iter_sources 가 내는 파일들의 (상대경로, 내용) 해시. mtime 은 넣지 않는다:
    git checkout 처럼 내용은 같고 시각만 바뀐 파일로 레이아웃이 바뀌지는 않는다."""
    h = hashlib.sha256()
    for rel, e in iter_sources(root):
        try:
            with open(e.path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).digest()
        except OSError:
            continue
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + digest)
    return h.hexdigest()[:32]


def src_mtime(force: bool = False) -> float:
    """C.src 아래 원고·그림 확장자의 최대 mtime(2초 캐시). 빌드 산출물과 메인 PDF 는 뺀다(iter_sources).

    build_all() 이 rsync 로 만드는 C.build 는 보통 C.state 아래(즉 C.src 밖)이지만, 상태 디렉토리를
    원고 트리 안에 둔 드문 배치에서도 빌드 산출물이 '원고가 바뀌었다'는 오탐을 만들지 않게 이름으로도 뺀다.
    캐시 키에 C.src 를 넣는 이유: 같은 프로세스 안에서 원고 경로가 바뀌면(테스트, 또는 드문 재구성)
    옛 경로의 값을 새 경로에 잘못 돌려주지 않기 위해서다.

    force=True 는 캐시를 건너뛰고 실측한다 — write_built_src_mtime() 이 빌드 시작 시각의 mtime 을
    남길 때 2초 캐시 값을 그대로 쓰면, 캐시가 채워진 지 2초 안에 원고를 고치고 바로 재빌드했을 때
    수정 전 mtime 이 '빌드 시작 시각'으로 잘못 기록된다."""
    D = cur_doc()
    cache = D.mcache
    key = str(D.src)
    if not force:
        with _SRC_MTIME_LOCK:
            ckey, val, at = cache
            if ckey == key and time.time() - at < 2.0:
                return val
    newest = 0.0
    if D.is_pdf:                                          # 보기 전용: 그 PDF 파일 하나가 원고다
        try:
            newest = D.main.stat().st_mtime
        except OSError:
            pass
    else:
        for _rel, e in iter_sources(D.src):
            try:
                newest = max(newest, e.stat().st_mtime)
            except OSError:
                pass
    with _SRC_MTIME_LOCK:
        cache[0], cache[1], cache[2] = key, newest, time.time()
    return newest


def read_built_src_mtime():
    try:
        return float((cur_doc().dir / "built_src_mtime.txt").read_text().strip())
    except (OSError, ValueError):
        return None


def write_built_src_mtime(value: float = None) -> None:
    """value 를 안 주면 지금 src_mtime(force=True) 를 실측해 기록한다(2초 캐시를 건너뛴다).

    호출부(_build_tracked)는 '이 빌드가 실제로 컴파일한 원고'의 mtime을 넘긴다 — --git-pull 이면
    pull 뒤(fast-forward 가 .tex mtime 을 밀어 올릴 수 있다), 아니면 복사 직전 실측한 값이다.
    빌드가 ok|ok_errors 로 끝났을 때만 이 함수를 불러 확정한다 — 실패한 빌드는 화면이 옛 PDF
    그대로이므로 '원고 수정됨' 배지가 꺼지면 안 된다."""
    try:
        v = src_mtime(force=True) if value is None else value
        atomic_write(cur_doc().dir / "built_src_mtime.txt", "%f" % v)
    except OSError:
        pass


def pins_rev() -> str:
    try:
        st = C.pins_jsonl.stat()
        return "%d:%d" % (st.st_mtime_ns, st.st_size)
    except OSError:
        return "0"


def doc_brief(D: Doc) -> dict:
    """문서 하나의 요약 — /api/docs 와 (여러 문서일 때) /api/meta 의 docs. 쓰기를 하지 않는다(폴링에서 부른다)."""
    with using_doc(D):
        b = build_state_snapshot()
        stale = (not D.is_pdf) and source_newer() > 2
        pdir = cur_pages()
        n_pages = sum(1 for _ in pdir.glob("page-*.png")) if pdir.is_dir() else 0
        return {"key": D.key, "name": D.name, "kind": D.kind, "view_only": D.is_pdf, "path": D.rel_path(),
                "main": D.main.name, "stale_build": stale, "src_mtime": src_mtime(),
                "building": D.lock.locked(), "build": {"state": b["state"], "phase": b["phase"]},
                "build_seq": b.get("seq", 0), "last_state": (b.get("last") or {}).get("state"),
                "pages_build": pdir.name, "n_pages": n_pages}


def docs_payload() -> dict:
    """GET /api/docs — 문서 목록과 문서별 열린 핀 수. 핀은 읽기만 한다(sync 쓰기 없음)."""
    rows, _ = read_pins()
    counts: dict = {}
    for r in rows:
        if not r.get("done"):
            k = pin_doc_key(r)
            counts[k] = counts.get(k, 0) + 1
    known = {d.key for d in DOCS}
    return {"docs": [dict(doc_brief(d), n_open=counts.get(d.key, 0)) for d in DOCS],
            "default": DOCS[0].key, "multi": multi_doc(),
            "other_open": sum(v for k, v in counts.items() if k not in known)}


def meta(actor: dict, light: bool = False) -> dict:
    D = cur_doc()

    def read(f):
        try:
            return (D.dir / f).read_text().strip()
        except OSError:
            return "?"
    bstate = build_state_snapshot()
    sm = src_mtime()
    newer = 0.0 if D.is_pdf else source_newer()     # 보기 전용은 PDF 가 바뀌면 서버가 알아서 다시 그린다
    out = {"pages": page_list(), "built_at": read("built_at.txt"), "head": read("head.txt"),
           "main": D.main.name, "pins_md": str(C.pins_md), "state_dir": str(C.state), "me": actor,
           "label": C.label, "accent": C.accent, "repo": C.repo,
           "building": D.lock.locked(),
           "doc": D.key, "doc_name": D.name, "kind": D.kind, "view_only": D.is_pdf, "multi": multi_doc(),
           # 원고가 화면의 PDF 보다 새로운가 — 서버가 숫자로 판정한다(브라우저 시계·시간대와 무관).
           "stale_build": newer > 2, "src_age_s": round(max(0.0, time.time() - sm), 1) if sm else None,
           "src_mtime": sm, "build_src_mtime": read_built_src_mtime(),
           "pages_build": cur_pages().name,
           "pins_rev": pins_rev(),
           # build_seq = 끝난 빌드 수, last_build = 가장 최근에 끝난 빌드(진행 중인 빌드와 무관하게 유지).
           "build_seq": bstate.get("seq", 0),
           "last_build": bstate.get("last") or {"state": None, "errors": [], "finished_at": None, "seq": 0},
           "build": {"state": bstate["state"], "phase": bstate["phase"], "started_at": bstate.get("started_at")}}
    if multi_doc():                       # 다른 문서의 낡음·빌드 — 뷰어가 탭에 점·진행 표시를 단다
        out["docs"] = [doc_brief(d) for d in DOCS]
        out["src_sig"] = ",".join("%s=%.3f" % (d["key"], d["src_mtime"]) for d in out["docs"])
    if light:                             # 폴링 전용 — snapshot_pins() 의 sync 쓰기를 부르지 않는다
        return out
    rows = snapshot_pins()
    out["n_open"] = sum(1 for r in rows if not r.get("done"))
    out["n_done"] = sum(1 for r in rows if r.get("done"))
    return out


# ---------------------------------------------------------------- 원문 접근

def norm(line: str) -> str:
    return " ".join(line.split())


def truncate_quote(s, n: int = 60) -> str:
    """인용문을 최대 n 자(말줄임표 포함)로 자른다(«…» 예시와 맞춘다).

    잘린 인용문이 온전한 문장처럼 보이면 원문을 다시 찾을 때 헷갈린다 — 잘렸다는 표시가 있어야
    사용자·에이전트가 이걸 '전체'가 아니라 '검색 힌트'로 읽는다. 잘렸을 때 본문 n-1자 뒤에
    말줄임표를 붙이므로 결과는 항상 n자 이하다(n자+말줄임표로 n+1자가 되지 않게)."""
    s = str(s)
    return s[:n - 1] + "…" if len(s) > n else s


def is_comment(line: str) -> bool:
    return line.lstrip().startswith("%")


def strip_comment(line: str) -> str:
    return re.sub(r"(?<!\\)%.*", "", line)


def tex_lines(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def to_source(path: str) -> Path:
    """빌드 사본 경로를 원본 체크아웃 경로로 되돌린다."""
    D = cur_doc()
    p = Path(path)
    for base in (D.build, D.build.resolve()):
        try:
            return D.src / p.relative_to(base)
        except ValueError:
            pass
    try:
        return D.src / p.resolve().relative_to(D.build.resolve())
    except (ValueError, OSError):
        pass
    # 상태 디렉토리를 옮겼거나 복제하면 synctex 가 옛 build 경로를 가리킨다. 경로 꼬리가
    # 원고 트리 안의 실제 파일과 맞으면 그것으로 되돌린다(가장 긴 꼬리 우선, 트리 밖은 읽지 않는다).
    parts = p.parts
    for k in range(1, len(parts)):
        cand = D.src.joinpath(*parts[k:])
        if cand.is_file():
            return cand
    return p


def safe_src(p) -> Path:
    """원고 트리 안의 실제 파일만 통과시킨다. 밖이면 400 — 첫 줄이 pins.md 에 새어 나간다."""
    if not isinstance(p, str) or not p or "\x00" in p or len(p) > 4096:
        raise HTTPError(400, "file 이 올바르지 않습니다.")
    q = Path(p)
    if not q.is_absolute():
        q = C.src / q
    try:
        rel = q.resolve().relative_to(C.src.resolve())
    except (ValueError, OSError, RuntimeError):
        raise HTTPError(400, "원고 디렉토리 밖의 파일입니다: %s" % p)
    out = C.src / rel
    if not out.is_file():
        raise HTTPError(400, "원고 안에 그런 파일이 없습니다: %s" % p)
    return out


# ---------------------------------------------------------------- 역변환 1: SyncTeX

def synctex_edit(pdf: Path, page: int, x: float, y: float):
    try:
        out = subprocess.run(["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, pdf)],
                             capture_output=True, text=True, timeout=10).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    inp = line = None
    for ln in out.splitlines():
        if ln.startswith("Input:"):
            inp = ln[6:].strip()
        elif ln.startswith("Line:"):
            try:
                line = int(ln[5:].strip())
            except ValueError:
                pass
        if inp and line:
            return inp, line
    return None


def densest(values: list, gap: int = 30) -> list:
    """큰 간격에서 끊고 가장 많이 모인 덩어리만 남긴다.

    synctex 는 질의 좌표에서 *가장 가까운* 노드를 주므로, 선택 사각형 안의 점이라도
    바로 옆 float 의 줄을 물고 온다(실측: 표 하나를 골랐는데 범위가 740-801 로 벌어졌다)."""
    if not values:
        return values
    groups = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return max(groups, key=len)


def by_synctex(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float):
    w, h = x1 - x0, y1 - y0
    nx = max(2, min(5, int(w / 40) + 2))
    ny = max(2, min(6, int(h / 14) + 2))
    hits = []
    for i in range(nx):
        for j in range(ny):
            r = synctex_edit(pdf, page, x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if r:
                hits.append(r)
    if not hits:
        return None
    best = max({f for f, _ in hits}, key=lambda f: sum(1 for g, _ in hits if g == f))
    ls = densest(sorted(l for f, l in hits if f == best))
    return best, ls[0], ls[-1]


# ---------------------------------------------------------------- 역변환 2: 렌더 텍스트

def region_text(pdf: Path, page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """선택 사각형 안에 실제로 찍힌 글자를 뽑는다(-r 72 이므로 1px = 1pt)."""
    try:
        return subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-r", "72",
             "-x", str(int(x0)), "-y", str(int(y0)),
             "-W", str(max(1, int(x1 - x0))), "-H", str(max(1, int(y1 - y0))), str(pdf), "-"],
            capture_output=True, text=True, timeout=15).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


_DF_CACHE: dict = {}
_DF_LOCK = threading.Lock()


def file_key(path: Path) -> tuple:
    try:
        st = path.stat()
        return (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(path), 0, 0)


def token_weights(text: str, lines: list, key: tuple) -> list:
    """영역 텍스트의 어절에 희귀도 가중을 준다.

    가중이 없으면 '타겟'·'데이터'·'학습' 같은 흔한 말이 점수를 지배해, 실제로는
    Nomenclature 를 고른 선택이 본문 문단과도 높게 겹친다고 나온다(실측). 드문
    어절일수록 위치를 특정하는 힘이 크다. 캐시 키는 (경로, mtime_ns, 크기)다 —
    id(lines) 는 목록이 버려지면 재사용되어 다른 파일의 빈도를 물 수 있다."""
    with _DF_LOCK:
        df = _DF_CACHE.get(key)
    if df is None:
        df = {}
        for ln in lines:
            for t in set(TOKEN_RE.findall(ln)):
                df[t] = df.get(t, 0) + 1
        with _DF_LOCK:
            _DF_CACHE.clear()
            _DF_CACHE[key] = df
    n = max(1, len(lines))
    out = []
    for t in {t for t in TOKEN_RE.findall(text) if len(t) >= 2}:
        freq = df.get(t, 0)
        if freq > n * 0.05:            # 원고 전체에 흩뿌려진 말은 위치를 못 짚는다
            continue
        out.append((t, 1.0 / (1.0 + freq)))
    return out


def score_range(tw: list, lines: list, lo: int, hi: int) -> float:
    """후보 줄 범위가 그 영역의 글자를 얼마나 담고 있는지 0~1 로 매긴다."""
    if not tw:
        return 0.0
    blob = " ".join(lines[max(0, lo - 2):hi + 1])
    return sum(w for t, w in tw if t in blob) / sum(w for _, w in tw)


def by_text(tw: list, lines: list, near=None):
    """렌더 텍스트의 어절로 원문 줄을 되찾는다.

    표·수식 영역에서 SyncTeX 가 침묵하거나 엉뚱한 곳을 짚을 때의 경로다. 한글
    어절은 마크업을 거의 타지 않아서(`타겟--소스 $i$ 간 코사인 거리`) 원문에
    그대로 남아 있다."""
    if len(tw) < 2:
        return None
    scores = [sum(w for t, w in tw if t in ln) for ln in lines]
    if max(scores, default=0) <= 0:
        return None
    peak = max(range(len(scores)), key=lambda i: (scores[i], -abs(i + 1 - (near or i + 1))))
    lo = hi = peak
    while lo > 0 and scores[lo - 1] > 0:
        lo -= 1
    while hi < len(scores) - 1 and scores[hi + 1] > 0:
        hi += 1
    return lo + 1, hi + 1, score_range(tw, lines, lo + 1, hi + 1)


# ---------------------------------------------------------------- 블록 확장과 범위 사다리

def expand_block(lines: list, lo: int, hi: int):
    """선택 줄을 감싸는 환경(--float-envs) 또는 문단 경계까지 넓힌다. 기본 단계를 정하는 데 쓴다.

    환경은 반드시 같은 이름의 \\end 로 닫는다 — 이름을 안 맞추면 선택이 인접한 다른
    float 로 새어 나간다(실측: 표 하나를 골랐는데 109줄이 잡혔다)."""
    n = len(lines)
    if not n:
        return lo, hi, "none"
    lo, hi = max(1, min(lo, n)), max(lo, min(hi, n))
    alt = "|".join(re.escape(e) for e in C.envs)
    b_re = re.compile(r"\\begin\{(" + alt + r")(\*?)\}")
    e_re = re.compile(r"\\end\{(" + alt + r")(\*?)\}")

    for i in range(lo - 1, -1, -1):
        if e_re.search(lines[i]) and i < lo - 1:
            break
        m = b_re.search(lines[i])
        if not m:
            continue
        env = m.group(1) + m.group(2)
        close = re.compile(r"\\end\{" + re.escape(env) + r"\}")
        opens = re.compile(r"\\begin\{" + re.escape(env) + r"\}")
        depth = 0
        for j in range(i + 1, n):
            if opens.search(lines[j]):
                depth += 1
            if close.search(lines[j]):
                if depth:
                    depth -= 1
                    continue
                return i + 1, j + 1, "float" if m.group(1) in FLOAT_KINDS else "block"
        break

    a, b = para_bounds(lines, lo, hi)
    return a, b, "paragraph"


SECTION_RE = re.compile(r"\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?[\[{]")


def para_bounds(lines: list, lo: int, hi: int) -> tuple:
    """빈 줄까지 넓힌다. 절 제목 줄(\\section·\\subsection …)은 위아래 어느 쪽으로도 넘어 들이지 않는다."""
    n = len(lines)
    a, b = lo, hi
    while a > 1 and lines[a - 2].strip() and not SECTION_RE.match(lines[a - 2]):
        a -= 1
    while b < n and lines[b].strip() and not SECTION_RE.match(lines[b]):
        b += 1
    return a, b


def trim_comments(lines: list, a: int, b: int) -> tuple:
    """앞뒤의 순수 주석 줄(% 로 시작)을 잘라낸다. 전부 주석이면 자르지 않는다.

    한 줄이 한 문단인 원고에서 문단 뒤에 붙은 TODO 주석이 핀 범위와 앵커 꼬리가 되던 것을 막는다."""
    x, y = a, b
    while x <= y and is_comment(lines[x - 1]):
        x += 1
    while y >= x and is_comment(lines[y - 1]):
        y -= 1
    return (a, b) if x > y else (x, y)


def env_spans(lines: list) -> list:
    """(시작 줄, 끝 줄, 이름) — 이름과 깊이를 맞춰 짝지은 모든 환경. 주석 안의 \\begin 은 무시한다."""
    stack, spans = [], []
    for i, ln in enumerate(lines):
        for m in ENV_TOK_RE.finditer(strip_comment(ln)):
            name = m.group(2).strip()
            if m.group(1) == "begin":
                stack.append((name, i + 1))
                continue
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    spans.append((stack[k][1], i + 1, name))
                    del stack[k:]
                    break
    return spans


def snippet(lines: list, lo: int, hi: int, cap: int = 80) -> str:
    chunk = lines[lo - 1:hi]
    extra = len(chunk) - cap
    if extra > 0:
        chunk = chunk[:cap]
    out = "\n".join("%5d  %s" % (lo + k, t) for k, t in enumerate(chunk))
    return out + ("\n      ... (%d줄 더)" % extra if extra > 0 else "")


def find_level(levels: list, key: str):
    for lv in levels:
        if lv["level"] == key or key in lv.get("merged", ()):
            return lv
    return None


def compute_levels(lines: list, raw_lo: int, raw_hi: int) -> dict:
    """범위 사다리: 드래그한 줄 / 문단(주석 꼬리 제외) / 감싸는 환경 안쪽→바깥 최대 3단.

    클라이언트가 서버 왕복 없이 단계를 바꾸도록 스니펫까지 한 번에 준다. section 단계는
    두지 않는다 — 수백 줄 범위가 쉽게 생겨 '줄 범위만 넘긴다'는 원칙에 반한다."""
    n = len(lines)
    raw_lo = max(1, min(raw_lo, n))
    raw_hi = max(raw_lo, min(raw_hi, n))
    levels: list = []

    def add(level, lo, hi, label, env=None):
        item = {"level": level, "lo": lo, "hi": hi, "label": label, "n": hi - lo + 1,
                "snippet": snippet(lines, lo, hi)}
        if env:
            item["env"] = env
        for i, old in enumerate(levels):              # 범위가 같은 단계는 합친다(뒤쪽 이름으로)
            if (old["lo"], old["hi"]) == (lo, hi):
                item["merged"] = old.get("merged", []) + [old["level"]]
                levels[i] = item
                return
        levels.append(item)

    add("raw", raw_lo, raw_hi, "드래그한 줄")
    spans = env_spans(lines)
    encl = sorted((s for s in spans if s[0] <= raw_lo <= s[1] and s[2] != "document"),
                  key=lambda s: (s[1] - s[0], -s[0]))
    pa, pb = para_bounds(lines, raw_lo, raw_hi)
    if encl:
        # 문단은 감싸는 가장 안쪽 환경을 넘지 않는다. 드래그가 그 환경의 안쪽이면 \begin/\end 줄도 뺀다 —
        # 안 그러면 표 안의 '문단' 이 \end{table*} 와 그 뒤 줄까지 먹어 환경과 엇갈린다(실측: L187-L270).
        ea, eb = encl[0][0], encl[0][1]
        if ea < raw_lo and raw_hi < eb:
            ea, eb = ea + 1, eb - 1
        pa, pb = max(pa, ea), min(pb, eb)
        if pa > pb:
            pa, pb = raw_lo, raw_hi
    # 드래그 밖의 환경에 반쯤 걸치지도 않는다(\end{table*} 바로 뒤 문단이 표 꼬리를 먹던 것).
    # 문단 안에 통째로 든 환경(빈 줄 없이 이어진 equation)은 그대로 둔다.
    for a, b, name in spans:
        if name == "document" or a <= raw_lo <= b:
            continue
        if b < raw_lo and a < pa <= b:
            pa = b + 1
        elif a > raw_hi and a <= pb < b:
            pb = a - 1
    pa, pb = min(pa, raw_lo), max(pb, raw_hi)
    pa, pb = trim_comments(lines, pa, pb)
    add("para", pa, pb, "문단")
    # 바깥 환경이 안쪽 환경을 앞뒤 한 줄로만 감싸면(minipage 안의 tabular 하나) 같은 블록이다 —
    # 안쪽을 따로 세우면 사다리 한 칸이 거의 같은 범위로 낭비된다. 바깥 쪽 이름을 남긴다.
    encl = [s for i, s in enumerate(encl)
            if not any(o[0] == s[0] - 1 and o[1] == s[1] + 1 for o in encl[i + 1:])]
    for k, (a, b, name) in enumerate(encl[:3]):
        key = "env" if k == 0 else "env%d" % (k + 1)
        suffix = "" if k == 0 else (" (바깥)" if k == 1 else " (바깥 2)")
        add(key, a, b, "환경 %s%s" % (name, suffix), env=name)

    ea, eb, kind = expand_block(lines, raw_lo, raw_hi)
    default = None
    if kind in ("float", "block"):
        for lv in levels:
            if lv["level"].startswith("env") and (lv["lo"], lv["hi"]) == (ea, eb):
                default = lv
                break
        if default is None:
            default = next((lv for lv in levels if lv["level"].startswith("env")), None)
    if default is None:
        default = find_level(levels, "para")
        kind = "paragraph"
    if not default["level"].startswith("env") and kind != "paragraph":
        kind = "paragraph"
    return {"levels": levels, "default_level": default["level"], "lo": default["lo"],
            "hi": default["hi"], "kind": kind}


# ---------------------------------------------------------------- 앵커와 재동기화

def anchor_of(lines: list, lo: int, hi: int) -> dict:
    """핀이 가리키는 블록의 머리·꼬리 텍스트를 떠 둔다(순수 주석 줄은 건너뛴다).

    줄 번호만 저장하면 원고를 한 번 고치는 순간 모든 핀이 어긋난다. 이 도구를 쓰는
    이유가 '에이전트가 원고를 고친다'인데, 고치면 핀이 죽는 구조는 쓸 수 없다.
    주석을 건너뛰는 이유: TODO 주석은 곧 지워질 줄이라 앵커로 삼으면 핀이 먼저 죽는다.

    head_off/tail_off 는 lo 에서 머리 줄까지, 꼬리 줄에서 hi 까지의 거리다. 이것이 없으면
    앞뒤에 주석 줄을 일부러 넣은 핀이 첫 줄 맞춤에서 조용히 줄어든다(실측: L7-L9 → L10-L11)."""
    idx = [i for i in range(lo - 1, min(hi, len(lines))) if lines[i].strip()]
    body = [i for i in idx if not is_comment(lines[i])] or idx
    if not body:
        return {}
    return {"head": norm(lines[body[0]]), "tail": norm(lines[body[-1]]),
            "head_off": body[0] - (lo - 1), "tail_off": (hi - 1) - body[-1]}


def _off(v) -> int:
    return v if _is_int(v) and 0 <= v < 10000 else 0


def find_line(nlines: list, needle: str, near: int):
    if not isinstance(needle, str) or not needle:
        return None
    cands = [i for i, t in enumerate(nlines) if t == needle]
    if not cands and len(needle) >= 12:
        key = needle[:40]
        cands = [i for i, t in enumerate(nlines) if key in t]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i + 1 - near)) + 1


def sync_all(rows: list) -> bool:
    """원고가 핀보다 새로우면 앵커로 줄 번호를 다시 맞춘다. 줄이나 stale 이 바뀐 레코드는 rev+1."""
    changed = False
    cache: dict = {}
    for r in rows:
        if r.get("done") or not r.get("file"):         # 보기 전용 PDF 의 핀은 줄이 없다 — 맞출 것도 없다
            continue
        f = Path(r.get("file", ""))
        if not in_tree(str(f)):
            continue
        try:
            if not f.is_file():
                continue
        except OSError:
            continue
        if f not in cache:
            ls = tex_lines(f)
            cache[f] = (ls, [norm(t) for t in ls], f.stat().st_mtime)
        lines, nlines, mtime = cache[f]
        if "anchor" not in r:                        # 앵커 없이 저장된 옛 핀을 한 번만 채운다
            r["anchor"] = anchor_of(lines, r["lo"], r["hi"])
            r["synced_at"] = mtime
            changed = True
            continue
        if not r["anchor"] or r.get("synced_at", 0) >= mtime:   # 빈 줄만 고른 핀은 따라갈 앵커가 없다
            continue
        before = (r["lo"], r["hi"], bool(r.get("stale")))
        anc = r["anchor"]
        ho, to = _off(anc.get("head_off")), _off(anc.get("tail_off"))   # 옛 앵커는 0
        span = r["hi"] - r["lo"]
        head = find_line(nlines, anc.get("head", ""), r["lo"] + ho)
        if head is None:
            r["stale"], r["sync"] = True, "lost"
        else:
            n = max(1, len(lines))
            lo = max(1, head - ho)
            tail = find_line(nlines, anc.get("tail", ""), r["hi"] - to + (lo - r["lo"]))
            hi = tail + to if tail is not None and tail >= head else lo + span
            hi = max(lo, min(n, hi))
            r["sync"] = "ok" if (lo, hi) == (r["lo"], r["hi"]) else "moved %+d" % (lo - r["lo"])
            r["lo"], r["hi"] = lo, hi
            r.pop("stale", None)
        if (r["lo"], r["hi"], bool(r.get("stale"))) != before:
            r["rev"] = int(r.get("rev") or 0) + 1
        r["synced_at"] = mtime
        changed = True
    return changed


# ---------------------------------------------------------------- 핀 저장소

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def valid_rec(r) -> bool:
    """저장소가 믿고 인덱싱하는 필드만 검사한다. 하나라도 틀리면 그 줄은 깨진 줄로 본다.

    id 만 보던 때는 lo 가 문자열이거나 file 이 없는 레코드 하나가 모든 GET·POST 를 500 으로
    만들었고, 그 500 직전에 pins.jsonl 쓰기가 이미 커밋돼 재시도가 중복 핀을 만들었다(실측)."""
    if not isinstance(r, dict) or not _is_int(r.get("id")):
        return False
    if r.get("doc") is not None and not (isinstance(r["doc"], str) and DOC_KEY_RE.fullmatch(r["doc"])):
        return False
    if is_region_pin(r):
        # 보기 전용 PDF 의 핀: file·lo·hi 대신 pdf(절대경로)·쪽·영역(frac)이 위치다(§보기 전용 문서).
        if not os.path.isabs(r["pdf"]) or not (_is_int(r.get("page")) and r["page"] >= 1):
            return False
        if r.get("lo") is not None or r.get("hi") is not None:
            return False
        fr = r.get("frac")
        if not (isinstance(fr, list) and len(fr) == 4 and all(_is_num(x) for x in fr)):
            return False
    else:
        if not isinstance(r.get("file"), str) or not r["file"]:
            return False
        lo, hi = r.get("lo"), r.get("hi")
        if not (_is_int(lo) and _is_int(hi) and 1 <= lo <= hi):
            return False
        if not os.path.isabs(r["file"]):              # 상대 경로는 서버 cwd 에 따라 다른 파일을 가리킨다
            return False
    if "page" in r and not _is_int(r["page"]):
        return False
    if "note" in r and r["note"] is not None and not isinstance(r["note"], str):
        return False
    for k in ("close_reply", "close_ref"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    if "anchor" in r and not isinstance(r["anchor"], dict):
        return False
    for k in ("raw_lo", "raw_hi", "rev"):
        if r.get(k) is not None and not _is_int(r[k]):
            return False
    for k in ("synced_at", "score", "claim_until", "claim_ts", "eta_ts"):   # epoch 초 — '*_at'(문자열 시각)과 이름을 가른다
        if r.get(k) is not None and not _is_num(r[k]):
            return False
    for k in ("done", "stale"):
        if r.get(k) is not None and not isinstance(r[k], bool):
            return False
    for k in ("name", "kind", "via", "scope", "sync", "pdf_build", "frac_build"):
        if r.get(k) is not None and not isinstance(r[k], str):
            return False
    for k, v in r.items():
        if k == "at" or k.endswith("_at") and k != "synced_at":
            if v is not None and not isinstance(v, str):
                return False
        elif k == "author" or k.endswith("_by"):
            if v is not None and not _is_actor(v):
                return False
    fr = r.get("frac")
    if fr is not None and not (isinstance(fr, list) and len(fr) == 4 and all(_is_num(x) for x in fr)):
        return False
    return True


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_region_pin(r: dict) -> bool:
    """보기 전용 PDF 문서의 핀인가 — file 이 없고 pdf 경로가 있다(레코드 모양으로만 가른다: 지금 설정에서 그 문서를
    뺐어도 레코드는 깨진 줄이 아니다 — 깨진 줄로 치면 다음 쓰기가 그 핀을 지운다)."""
    return isinstance(r, dict) and r.get("file") is None and isinstance(r.get("pdf"), str) and bool(r["pdf"])


def _is_actor(v) -> bool:
    """author·*_by 는 {login,name,pic?} 문자열 사전이어야 한다 — UI 가 name.trim() 을 부른다."""
    return isinstance(v, dict) and all(v.get(k) is None or isinstance(v[k], str) for k in ("login", "name", "pic"))


def in_tree(p: str) -> bool:
    """레코드의 file 이 원고 트리 안인가. 밖이면 줄 맞춤·편집이 그 파일을 읽지 않는다
    (읽으면 앵커에 트리 밖 파일의 줄이 담겨 GET /api/pins 로 나간다)."""
    try:
        Path(p).resolve().relative_to(C.src.resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def read_jsonl(path: Path) -> tuple:
    """(레코드, 깨진 줄 번호). 깨진 줄은 건너뛰고 경고한다 — GET 전체가 500 이 되지 않게.

    JSON 으로 읽혀도 필수 필드(file·lo·hi·id)의 형이 틀리면 깨진 줄로 친다(valid_rec)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return [], []
    rows, bad = [], []
    for i, t in enumerate(text.splitlines(), 1):
        if not t.strip():
            continue
        try:
            r = json.loads(t)
        except (ValueError, RecursionError):
            r = None
        if not valid_rec(r):
            bad.append(i)
            continue
        rows.append(r)
    if bad:
        print("경고: %s 의 %d줄을 읽지 못했습니다(줄 %s)." % (path.name, len(bad), bad[:10]),
              file=sys.stderr)
    return rows, bad


def read_pins() -> tuple:
    return read_jsonl(C.pins_jsonl)


def dump_jsonl(rows: list) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def unique_path(stem: str, suffix: str) -> Path:
    """<state>/<stem><suffix> 가 이미 있으면 -1, -2 … 를 붙인다 — 같은 초에 두 번 보관해도 덮지 않게."""
    p = C.state / (stem + suffix)
    k = 1
    while p.exists():
        p = C.state / ("%s-%d%s" % (stem, k, suffix))
        k += 1
    return p


def write_pins(rows: list, bad=None) -> None:
    """pins.md 를 메모리에서 먼저 만든다. 렌더가 실패하면 아무것도 쓰지 않는다 —
    pins.jsonl 을 커밋한 뒤 500 을 돌려주면 클라이언트가 재시도해 중복 핀이 생긴다."""
    md = pins_md_text(rows)
    data = dump_jsonl(rows)
    if bad and C.pins_jsonl.exists():                # 조용한 데이터 손실 방지: 원본 바이트를 남긴다
        shutil.copy2(C.pins_jsonl, unique_path("pins.jsonl.corrupt-%s" % time.strftime("%Y%m%d-%H%M%S"), ".bak"))
    atomic_write(C.pins_jsonl, data)
    atomic_write(C.pins_md, md)


def transact(fn):
    """쓰기 순서 불변식: with PIN_LOCK → read → sync → 요청 변경 → atomic write → pins.md.

    변경을 sync 뒤에 적용하므로 사용자가 준 lo/hi 가 옛 앵커로 되돌아가지 않는다.
    fn(rows) 는 (결과, 바뀌었는지) 를 돌려준다. fn 은 검증을 끝낸 뒤에만 rows 를 고친다."""
    with PIN_LOCK:
        rows, bad = read_pins()
        synced = sync_all(rows)
        try:
            result, mutated = fn(rows)
        except HTTPError:
            if synced:
                write_pins(rows, bad)
            raise
        if synced or mutated:
            write_pins(rows, bad)
        return rows, result


def snapshot_pins() -> list:
    rows, _ = transact(lambda rows: (None, False))
    return rows


def public(r: dict) -> dict:
    out = dict(r)
    out["rev"] = out["rev"] if _is_int(out.get("rev")) else 0
    return out


# ---------------------------------------------------------------- 위치 추정(.est) — 서버가 판정하는 계산 필드
#
# 마크는 핀을 찍을 때의 frac(쪽 대비 비율)에 고정된다. 그 좌표가 지금 화면의 PDF 와 안 맞을 수 있으면
# '추정'(점선)이다. 판정은 빌드 신원으로 한다: 핀이 찍힌 화면의 빌드(pdf_build)가 지금 빌드와 다르고,
# 두 빌드가 컴파일한 원고 지문이 다르면 추정. 또는 앵커 줄 맞춤이 옮겼거나(moved) 잃었으면(lost) 추정.
# 벽시계는 쓰지 않는다 — 브라우저 시간대, 메모만 고친 edited_at, 낡은 PDF 위에서 찍은 핀에서 전부 틀렸다.

def pin_build(r: dict):
    """핀 좌표가 속한 빌드 이름. frac_build 는 같은 뜻의 옛 필드명(83b91a5)이다."""
    for k in ("pdf_build", "frac_build"):
        v = r.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def _epoch(s):
    """'YYYY-MM-DD HH:MM:SS'(서버 현지 시각, now_str 이 쓴 모양) 또는 ISO+오프셋 → epoch 초. 서버에서만 푼다."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        dt = datetime.fromisoformat(s.strip().replace(" ", "T", 1))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()          # 서버 현지 시각으로 쓴 값이다 — 같은 기계에서 되읽는다
    return dt.timestamp()


def est_context() -> dict:
    """요청 하나 동안 쓸 판정 재료(이력 한 번 읽기)."""
    h = load_builds()
    cur = cur_pages().name
    by = dict(h["by"])
    if cur not in by:                                 # seed_builds() 전(테스트·드문 경합) — 알려진 것만으로 판정
        by[cur] = {"build": cur, "src_mtime": read_built_src_mtime(), "src_hash": None}
    bsm = read_built_src_mtime()
    if bsm is None and _is_num(by[cur].get("src_mtime")):
        bsm = float(by[cur]["src_mtime"])
    return {"cur": cur, "by": by, "built_at": _epoch(_read_built_at()), "bsm": bsm}


def same_source(a, b) -> bool:
    """두 빌드가 같은 원고로 만들어졌는가. 해시가 둘 다 있으면 해시로, 아니면 시작 때 src_mtime 으로.
    어느 쪽도 모르면 False(다르다고 본다) — 모르는 채로 '정확한 위치'라고 그리는 편이 더 해롭다."""
    if not a or not b:
        return False
    if a.get("src_hash") and b.get("src_hash"):
        return a["src_hash"] == b["src_hash"]
    ma, mb = a.get("src_mtime"), b.get("src_mtime")
    return _is_num(ma) and _is_num(mb) and abs(float(ma) - float(mb)) < 0.01


def legacy_est(r: dict, ctx: dict) -> bool:
    """pdf_build 가 없는 옛 핀의 대체 휴리스틱(옛 뷰어의 규칙을 서버에서 epoch 수치로): 핀이 지금 PDF 보다
    먼저 찍혔고, 지금 PDF 를 만든 원고(시작 때 src_mtime)가 그 핀보다 나중에 바뀌었으면 추정.

    기준 시각은 찍은 시각(at)뿐이다 — edited_at 을 쓰면 메모만 고쳐도 추정이 꺼진다(독립 검증 실측).
    frac 을 다시 찍는 편집(loc)은 이제 pdf_build 를 남기므로 이 휴리스틱을 더 타지 않는다."""
    ba, pa = ctx["built_at"], _epoch(r.get("at"))
    if ba is None or pa is None or pa >= ba:
        return False
    return ctx["bsm"] is not None and ctx["bsm"] > pa


def pin_est(r: dict, ctx: dict) -> bool:
    sync = r.get("sync")
    if r.get("stale") or (isinstance(sync, str) and sync != "ok"):
        return True                                   # moved ±N / lost — 앵커가 옮기거나 잃었다
    b = pin_build(r)
    if b is None:
        return legacy_est(r, ctx)
    if b == ctx["cur"]:
        return False
    return not same_source(ctx["by"].get(b), ctx["by"].get(ctx["cur"]))


def pins_payload(rows: list, allp: bool) -> list:
    """GET /api/pins 응답: 저장 레코드 + 계산 필드 rel(겹침)·est(위치 추정). 둘 다 저장하지 않는다."""
    rel = overlaps_by_id(rows)
    ctxs: dict = {}
    out = []
    for r in rows:
        if not (allp or not r.get("done")):
            continue
        k = pin_doc_key(r)
        if k not in ctxs:                              # 판정 재료는 문서마다(빌드 이력이 문서마다 따로다)
            D = doc_by_key(k)
            if D is None:
                ctxs[k] = None
            else:
                with using_doc(D):
                    ctxs[k] = est_context()
        ctx = ctxs[k]
        rec = dict(public(r), rel=rel.get(r["id"], []), est=pin_est(r, ctx) if ctx else True, doc=k)
        if claim_active(r) and not _is_num(r.get("claim_ts")):
            ts = _epoch(r.get("claimed_at"))          # eta 이전 claim — 뷰어의 '20:02부터 (23분째)'가 쓸 시작 epoch(계산 필드)
            if ts is not None:
                rec["claim_ts"] = ts
        out.append(rec)
    return out


def dropped_payload() -> list:
    """GET /api/pins/dropped 응답: pins.dropped.jsonl 을 dropped_at 순으로 그대로 낸다(계산 필드 없음).

    읽기 전용이고 잠금 밖이다 — 삭제·되살리기는 이미 PIN_LOCK 을 쥐고 이 파일을 쓴다(drop_pin·restore_pin).
    여기서는 원자적 교체(atomic_write)가 끝난 파일만 읽으므로 별도 잠금이 없어도 반쪽짜리를 보지 않는다."""
    rows, _ = read_jsonl(C.dropped)
    rows.sort(key=lambda r: str(r.get("dropped_at") or ""))
    return [public(r) for r in rows]


# ---------------------------------------------------------------- 겹침(overlap) — 저장하지 않는 계산 필드

def _range_rel(a_lo: int, a_hi: int, b_lo: int, b_hi: int):
    """a 를 기준으로 b 와의 관계. 겹치지 않으면 None."""
    if a_hi < b_lo or b_hi < a_lo:
        return None
    if b_lo <= a_lo and a_hi <= b_hi:
        return "contains" if (a_lo, a_hi) == (b_lo, b_hi) else "inside"
    if a_lo <= b_lo and b_hi <= a_hi:
        return "contains"
    return "partial"


def overlaps_by_id(rows: list) -> dict:
    """같은 file 의 열린 핀 쌍마다 관계를 계산한다(저장하지 않는다). {id: [{"id","rel"}, …]}.

    범위가 완전히 같으면 id 가 작은 쪽을 바깥(contains)으로 본다 — 어느 쪽도 진짜로 안에 든 것이
    아니므로 결정적인 규칙 하나가 필요하다."""
    out: dict = {}
    by_file: dict = {}
    for r in rows:
        if r.get("done"):
            continue
        out.setdefault(r["id"], [])
        if not r.get("file"):                          # 보기 전용 PDF 의 핀 — 줄 범위 겹침이 없다
            continue
        by_file.setdefault(r.get("file"), []).append(r)
    for group in by_file.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if (a["lo"], a["hi"]) == (b["lo"], b["hi"]):
                    outer, inner = (a, b) if a["id"] < b["id"] else (b, a)
                    out[inner["id"]].append({"id": outer["id"], "rel": "inside"})
                    out[outer["id"]].append({"id": inner["id"], "rel": "contains"})
                    continue
                rel_a = _range_rel(a["lo"], a["hi"], b["lo"], b["hi"])   # a 가 b 안에 드는가
                if rel_a == "inside":
                    out[a["id"]].append({"id": b["id"], "rel": "inside"})
                    out[b["id"]].append({"id": a["id"], "rel": "contains"})
                elif rel_a == "contains":
                    out[a["id"]].append({"id": b["id"], "rel": "contains"})
                    out[b["id"]].append({"id": a["id"], "rel": "inside"})
                elif rel_a == "partial":
                    out[a["id"]].append({"id": b["id"], "rel": "partial"})
                    out[b["id"]].append({"id": a["id"], "rel": "partial"})
    return out


def selection_rel(lo: int, hi: int, b_lo: int, b_hi: int):
    """아직 저장 전인 선택(lo..hi)과 저장된 핀(b_lo..b_hi)의 관계 — 선택 기준.

    equal(범위가 같음 — 같은 문단·환경을 두 번 찍는 가장 흔한 중복) · inside(선택이 핀 안) ·
    contains(선택이 핀을 감쌈) · partial(걸침) · None(안 겹침). 뷰어의 overlapsFor() 와 같은 규칙이다
    (범위가 바뀔 때마다 브라우저가 서버 왕복 없이 다시 계산한다 — 회귀 테스트가 두 구현을 대조한다)."""
    if (lo, hi) == (b_lo, b_hi):
        return "equal"
    return _range_rel(lo, hi, b_lo, b_hi)


def overlaps_for_range(file: str, lo: int, hi: int) -> list:
    """pick 이 고른 (아직 저장 전인) 범위가 그 파일의 열린 핀들과 겹치는 관계. 저장은 하지 않는다.

    저장된 핀끼리(overlaps_by_id)는 범위가 같으면 id 로 안팎을 가르지만, 새 선택에는 아직 id 가 없으므로
    같은 범위를 따로 'equal' 로 낸다 — 뷰어는 네 관계 모두 배너로 알리고 문구로 관계를 밝힌다."""
    out = []
    for r in snapshot_pins():
        if r.get("done") or r.get("file") != file:
            continue
        rel = selection_rel(lo, hi, r["lo"], r["hi"])
        if rel:
            out.append({"id": r["id"], "lo": r["lo"], "hi": r["hi"], "rel": rel})
    return out


def josa(n, cons: str, vowel: str) -> str:
    """숫자 뒤 조사 — '#20과'·'#2와', '#20을'·'#2를'. 한자어 읽기의 끝소리로 가른다: 0 으로 끝나면(십·백·천·만·영) 받침,
    아니면 끝자리 1·3·6·7·8(일·삼·육·칠·팔)이 받침이다. 뷰어 josa() 와 같은 규칙."""
    d = str(n)[-1:]
    return cons if d == "0" or d in "13678" else vowel


def rel_badge(rel: list, by_id: dict, me: dict = None) -> str:
    """pins.md·카드 태그용 대표 관계 하나 — 뜻이 드러나는 짧은 말로 쓴다(예전 ⊂#N·∩#N 은 뜻을 알 수 없었다).

    1. 범위가 똑같은 핀이 있으면(같은 곳을 두 번 찍음) id 가 가장 작은 것: '#N과 같은 범위'
    2. inside 가 있으면 범위가 가장 작은 바깥 핀: '#N 범위 안'
    3. partial 중 id 가 가장 작은 것: '#N과 일부 겹침'
    contains(감쌈)는 표기하지 않는다. GET /api/pins 의 rel 항목은 {id,rel} 뿐이라(계약), 범위는 by_id(전체 행)에서
    찾는다. me(이 핀)가 없으면 같은 범위를 가려내지 못하고 예전처럼 안/겹침만 본다."""
    if me is not None:
        same = [x for x in rel if (by_id.get(x["id"]) or {}).get("lo") == me.get("lo")
                and (by_id.get(x["id"]) or {}).get("hi") == me.get("hi")]
        if same:
            n = min(x["id"] for x in same)
            return "#%d%s 같은 범위" % (n, josa(n, "과", "와"))
    insides = [x for x in rel if x["rel"] == "inside"]
    if insides:
        def span(x):
            o = by_id.get(x["id"])
            return ((o["hi"] - o["lo"]) if o else 1 << 30, x["id"])
        best = min(insides, key=span)
        return "#%d 범위 안" % best["id"]
    partials = [x for x in rel if x["rel"] == "partial"]
    if partials:
        n = min(partials, key=lambda x: x["id"])["id"]
        return "#%d%s 일부 겹침" % (n, josa(n, "과", "와"))
    return ""


def max_id_in(path: Path) -> int:
    rows, _ = read_jsonl(path)
    return max((r["id"] for r in rows), default=0)


def init_seq() -> None:
    """pins.seq 가 없으면 한 번만 현재·보관·삭제 기록의 최대 id 로 채운다(1회 이관)."""
    with PIN_LOCK:
        if C.seq.exists():
            return
        m = max_id_in(C.pins_jsonl)
        for p in list(C.state.glob("pins_*.jsonl.bak")) + [C.dropped]:
            m = max(m, max_id_in(p))
        atomic_write(C.seq, str(m))


def next_id(rows: list) -> int:
    """id 는 다시 쓰지 않는다 — 채팅 속 '#2' 가 다른 핀을 가리키게 되면 안 된다."""
    try:
        last = int(C.seq.read_text().strip() or 0)
    except (OSError, ValueError):
        last = 0
    nid = max(last, max((r["id"] for r in rows), default=0)) + 1
    atomic_write(C.seq, str(nid))
    return nid


def find_pin(rows: list, pid: int):
    return next((r for r in rows if r.get("id") == pid), None)


def who(actor: dict) -> dict:
    return {"login": actor.get("login", "local"), "name": actor.get("name", "")}


# ---------------------------------------------------------------- 입력 검증

def _int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        raise HTTPError(400, "%s 는 정수여야 합니다." % what)
    return int(v)


def _num(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise HTTPError(400, "%s 는 유한한 숫자여야 합니다." % what)
    return float(v)


def clean_note(v) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise HTTPError(400, "note 는 문자열이어야 합니다.")
    if len(v) > NOTE_MAX:
        raise HTTPError(400, "메모가 너무 깁니다(%d자 이하)." % NOTE_MAX)
    return v


def clean_close_body(d: dict) -> tuple:
    """close 본문의 선택 필드 {"reply", "ref"} 를 검증한다. 없거나 빈 문자열(공백만 포함)이면
    (None, None) — 기존 '본문 없는 curl POST' 동작을 그대로 둔다(§P0b-보완 C)."""
    reply = d.get("reply")
    if reply is not None:
        if not isinstance(reply, str):
            raise HTTPError(400, "reply 는 문자열이어야 합니다.")
        if len(reply) > CLOSE_REPLY_MAX:
            raise HTTPError(400, "reply 가 너무 깁니다(%d자 이하)." % CLOSE_REPLY_MAX)
        if not reply.strip():
            reply = None
    ref = d.get("ref")
    if ref is not None:
        if not isinstance(ref, str):
            raise HTTPError(400, "ref 는 문자열이어야 합니다.")
        if len(ref) > CLOSE_REF_MAX:
            raise HTTPError(400, "ref 가 너무 깁니다(%d자 이하)." % CLOSE_REF_MAX)
        if not ref.strip():
            ref = None
    return reply, ref


def clean_loc(d: dict) -> dict:
    """위치 필드를 검증해 저장할 모양으로 만든다. file 은 원고 트리 안, 1 ≤ lo ≤ hi ≤ 줄 수."""
    out: dict = {}
    f = safe_src(d.get("file"))
    n = len(tex_lines(f))
    lo, hi = _int(d.get("lo"), "lo"), _int(d.get("hi"), "hi")
    if not 1 <= lo <= hi <= max(n, 1):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, lo, hi))
    out.update(file=str(f), name=f.name, lo=lo, hi=hi)
    page = _int(d.get("page", 1), "page")
    if page < 1:
        raise HTTPError(400, "page 는 1 이상이어야 합니다.")
    out["page"] = page
    for k in ("raw_lo", "raw_hi"):
        if d.get(k) is not None:
            out[k] = _int(d[k], k)
    if d.get("kind") is not None:
        if not isinstance(d["kind"], str) or len(d["kind"]) > 80:
            raise HTTPError(400, "kind 가 올바르지 않습니다.")
        out["kind"] = d["kind"]
    if d.get("via") is not None:
        if d["via"] not in ("synctex", "text"):
            raise HTTPError(400, "via 는 synctex|text 입니다.")
        out["via"] = d["via"]
    if d.get("score") is not None:
        out["score"] = _num(d["score"], "score")
    if d.get("frac") is not None:
        fr = d["frac"]
        if not isinstance(fr, list) or len(fr) != 4:
            raise HTTPError(400, "frac 은 숫자 4개 목록입니다.")
        out["frac"] = [_num(x, "frac") for x in fr]
    if d.get("scope") is not None:
        if d["scope"] not in SCOPES:
            raise HTTPError(400, "scope 는 %s 중 하나입니다." % "|".join(SCOPES))
        out["scope"] = d["scope"]
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            raise HTTPError(400, "quote 는 문자열입니다.")
        out["quote"] = truncate_quote(d["quote"], 60)
    if d.get("pdf_build") is not None:                # 드래그할 때 화면에 있던 빌드(pick 응답의 pdf_build)
        if not valid_build_name(d["pdf_build"]):
            raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
        out["pdf_build"] = d["pdf_build"]
    return out


PDF_QUOTE_MAX = 160               # 보기 전용 핀의 영역 글자 — 줄 번호가 없으니 60자보다 넉넉히(에이전트의 판단 재료)
REGION_FIELDS = ("page", "frac", "note", "quote", "pdf_build")


def clean_frac(fr) -> list:
    """보기 전용 핀의 위치는 영역뿐이라 LaTeX 핀보다 엄하게 본다: 숫자 4개, 쪽 안(0..1), 넓이가 있다."""
    if not isinstance(fr, list) or len(fr) != 4:
        raise HTTPError(400, "frac 은 숫자 4개 목록 [x, y, w, h](쪽 대비 비율)입니다.")
    x, y, w, h = [_num(v, "frac") for v in fr]
    eps = 1e-6
    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 + eps and 0 < h <= 1 + eps
            and x + w <= 1 + eps and y + h <= 1 + eps):
        raise HTTPError(400, "frac 이 쪽 밖입니다(0..1, 넓이 > 0).")
    return [x, y, w, h]


def clean_region(d: dict) -> dict:
    """보기 전용 문서(지금 문서)의 핀 위치 — 쪽·영역. lo/hi·file 은 받지 않는다."""
    D = cur_doc()
    for k in ("file", "lo", "hi", "scope"):
        if d.get(k) is not None:
            raise HTTPError(400, "보기 전용 문서(%s)의 핀에는 %s 가 없습니다 — 쪽(page)과 영역(frac)만 받습니다." % (D.key, k))
    out: dict = {"pdf": str(D.main), "name": D.main.name, "kind": "region"}
    page = _int(d.get("page"), "page")
    want = d.get("pdf_build")
    if want is not None and not valid_build_name(want):
        raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
    n = len(page_list(pages_dir_for(want)))
    if page < 1 or (n and page > n):
        raise HTTPError(400, "page 는 1..%d 이어야 합니다." % max(n, 1))
    out["page"] = page
    out["frac"] = clean_frac(d.get("frac"))
    if d.get("quote") is not None:
        if not isinstance(d["quote"], str):
            raise HTTPError(400, "quote 는 문자열입니다.")
        out["quote"] = truncate_quote(norm(d["quote"]), PDF_QUOTE_MAX)
    if want is not None:
        out["pdf_build"] = want
    return out


def request_doc(q: dict, body: dict = None, file_hint=None) -> Doc:
    """요청이 가리키는 문서: ?doc= 또는 본문 doc. 둘 다 없으면 file 로 짐작하고(에이전트 curl), 그것도 없으면 첫 문서.
    없는 키는 404 — 조용히 첫 문서로 물러서면 다른 문서에 핀이 붙는다."""
    key = (q.get("doc") or [None])[0] if q else None
    bkey = body.get("doc") if isinstance(body, dict) else None
    if bkey is not None and not isinstance(bkey, str):
        raise HTTPError(400, "doc 은 문자열이어야 합니다.")
    if key and bkey and key != bkey:
        raise HTTPError(400, "doc 이 주소(%s)와 본문(%s)에서 다릅니다." % (key, bkey))
    key = key or bkey
    if not key:
        if file_hint and multi_doc():
            return doc_for_file(file_hint)
        return DOCS[0]
    D = doc_by_key(key)
    if D is None:
        raise HTTPError(404, "없는 문서입니다: %s" % hdr_text(key)[:40], docs=[d.key for d in DOCS])
    return D


# ---------------------------------------------------------------- 핀 조작

def add_pin(d: dict, actor: dict) -> int:
    D = cur_doc()
    want = d.get("doc")
    if isinstance(want, str) and want != D.key:        # 본문의 doc 이 지금 문서와 다르면 그 문서로(없는 키면 404)
        other = request_doc({}, {"doc": want})
        with using_doc(other):
            return add_pin(dict(d, doc=other.key), actor)
    if D.is_pdf:
        return _add_region_pin(d, actor)
    body = {k: d[k] for k in ADD_FIELDS if k in d}
    rec = clean_loc(body)
    note = clean_note(body.get("note"))
    if "kind" not in rec:
        rec["kind"] = "lines"
    f = Path(rec["file"])
    lines = tex_lines(f)

    def fn(rows):
        rec["note"] = note
        rec["at"] = now_str()
        rec["id"] = next_id(rows)
        rec["author"] = dict(actor)
        rec["anchor"] = anchor_of(lines, rec["lo"], rec["hi"])
        rec["synced_at"] = f.stat().st_mtime if f.exists() else 0
        # frac 이 어느 빌드의 레이아웃 좌표인지를 빌드 신원으로 못박는다(§위치 추정). 뷰어는 pick 응답의
        # pdf_build(드래그할 때 화면에 있던 빌드)를 그대로 돌려보낸다 — 재빌드 직후 화면을 바꾸기 전의
        # 드래그도 옛 빌드로 남는다. 안 보낸 호출(에이전트 curl)은 지금 빌드다.
        rec.setdefault("pdf_build", cur_pages().name)
        rec["doc"] = D.key
        rec["rev"] = 0
        rows.append(rec)
        return rec["id"], True
    return transact(fn)[1]


def _add_region_pin(d: dict, actor: dict) -> int:
    """보기 전용 문서의 핀: {doc, pdf, name, page, frac, kind:'region', quote?, note, pdf_build}. 줄·앵커가 없다."""
    D = cur_doc()
    rec = clean_region({k: d[k] for k in REGION_FIELDS + ("file", "lo", "hi", "scope") if k in d})
    note = clean_note(d.get("note"))

    def fn(rows):
        rec["note"] = note
        rec["at"] = now_str()
        rec["id"] = next_id(rows)
        rec["author"] = dict(actor)
        rec.setdefault("pdf_build", cur_pages().name)
        rec["doc"] = D.key
        rec["rev"] = 0
        rows.append(rec)
        return rec["id"], True
    return transact(fn)[1]


def edit_pin(pid: int, d: dict, actor: dict) -> dict:
    """메모·범위·위치를 제자리에서 고친다. id·at·done 은 바꾸지 않는다.

    base_rev 가 지금 rev 와 다르면 409 — 에이전트가 닫았거나 자동 줄 맞춤이 옮긴 핀을
    옛 lo/hi 로 조용히 덮어쓰지 않기 위해서다."""
    has_note = "note" in d
    note = clean_note(d.get("note")) if has_note else None
    note_append = d.get("note_append")
    if note_append is not None:
        if not isinstance(note_append, str):
            raise HTTPError(400, "note_append 는 문자열이어야 합니다.")
        if not note_append.strip():
            raise HTTPError(400, "덧붙일 메모가 비어 있습니다.")
        if len(note_append) > 2000:
            raise HTTPError(400, "덧붙일 메모가 너무 깁니다(2000자 이하).")
    loc = d.get("loc")
    if loc is not None and not isinstance(loc, dict):
        raise HTTPError(400, "loc 는 객체여야 합니다.")
    lo = _int(d["lo"], "lo") if d.get("lo") is not None else None
    hi = _int(d["hi"], "hi") if d.get("hi") is not None else None
    scope = d.get("scope")
    if scope is not None and scope not in SCOPES:
        raise HTTPError(400, "scope 는 %s 중 하나입니다." % "|".join(SCOPES))
    kind = d.get("kind")
    if kind is not None and (not isinstance(kind, str) or len(kind) > 80):
        raise HTTPError(400, "kind 가 올바르지 않습니다.")
    base_given = "base_rev" in d
    if not base_given and note_append is None:
        raise HTTPError(400, "base_rev 가 필요합니다(카드를 열 때 받은 rev).")
    base = _int(d["base_rev"], "base_rev") if base_given else None
    moves = loc is not None or lo is not None or hi is not None
    if not (has_note or moves or scope is not None or kind is not None or note_append is not None):
        raise HTTPError(400, "바꿀 필드가 없습니다(note, lo, hi, scope, loc, note_append).")
    # 위치 검증·기본 빌드는 그 핀의 문서 기준이다(요청이 ?doc= 를 안 붙여도). 핀의 종류(LaTeX/보기 전용)는 바뀌지 않는다.
    r0 = find_pin(read_pins()[0], pid)
    region = r0 is not None and is_region_pin(r0)
    pdoc = (doc_by_key(pin_doc_key(r0)) if r0 is not None else None) or cur_doc()
    if region and (lo is not None or hi is not None or scope is not None or kind is not None):
        raise HTTPError(400, "보기 전용 문서의 핀에는 줄 범위가 없습니다 — 메모(note)와 영역(loc: page, frac)만 고칩니다.")
    with using_doc(pdoc):
        if region:
            newloc = clean_region(loc) if loc is not None else None
        else:
            newloc = clean_loc(loc) if loc is not None else None
        if newloc is not None:
            # pdf_build 는 frac 이 어느 빌드의 좌표인지다 — frac 을 새로 찍지 않은 loc 는 그 값을 못 바꾼다.
            if "frac" in loc:
                newloc.setdefault("pdf_build", cur_pages().name)
            else:
                newloc.pop("pdf_build", None)

    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            raise HTTPError(404, "핀 #%d 이 없습니다." % pid)
        if r.get("done") and (moves or scope is not None or kind is not None):
            raise HTTPError(409, "done", pin=public(r), detail="닫힌 핀은 메모만 고칠 수 있습니다.")
        if base_given and int(r.get("rev") or 0) != base:
            raise HTTPError(409, "conflict", pin=public(r))
        range_changed = False
        if region:
            if newloc is not None:                   # 영역 다시 잡기 — 쪽·영역·영역 글자·빌드만 바뀐다
                for k in ("page", "frac", "quote", "pdf_build"):
                    if k in newloc:
                        r[k] = newloc[k]
                    elif k == "quote":
                        r.pop("quote", None)
        elif newloc is not None:
            # loc 에 없는 page·frac 은 그대로 둔다 — 에이전트가 file/lo/hi 만 보내도 쪽이 1로 튀지 않게.
            keep = {k: r[k] for k in ("page", "frac") if k not in loc and k in r}
            for k in LOC_FIELDS:
                r.pop(k, None)
            r.update(newloc)
            r.update(keep)
            if "kind" not in newloc:                 # add 와 같은 기본값
                r["kind"] = kind if kind is not None else "lines"
            if scope is not None and "scope" not in newloc:
                r["scope"] = scope
            if "frac" in loc:                        # frac 을 실제로 다시 찍었을 때만 빌드 신원이 바뀐다
                r.pop("frac_build", None)            # 옛 필드명(83b91a5) — pdf_build 로 대체
            range_changed = True
        elif lo is not None or hi is not None:
            a = lo if lo is not None else r["lo"]
            b = hi if hi is not None else r["hi"]
            if not in_tree(r["file"]):
                raise HTTPError(400, "원고 디렉토리 밖을 가리키는 핀입니다 — 위치 다시 잡기(loc)로 고치세요.")
            f = Path(r["file"])
            n = len(tex_lines(f))
            if not 1 <= a <= b <= max(n, 1):
                raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (n, a, b))
            range_changed = (a, b) != (r["lo"], r["hi"]) or bool(r.get("stale"))
            r["lo"], r["hi"] = a, b
            if range_changed:                        # 손으로 옮긴 범위는 더 이상 좌표·글자 매칭 결과가 아니다
                r.pop("via", None)
                r.pop("score", None)
        if newloc is None:
            if scope is not None:
                r["scope"] = scope
            if kind is not None:
                r["kind"] = kind
        if range_changed and not region and in_tree(r["file"]):
            f = Path(r["file"])
            r["anchor"] = anchor_of(tex_lines(f), r["lo"], r["hi"])
            r["synced_at"] = f.stat().st_mtime if f.exists() else 0
            r.pop("stale", None)
            r.pop("sync", None)
        if has_note:
            r["note"] = note
        if note_append is not None:
            stamp = "(추가 %s) " % datetime.now().astimezone().strftime("%H:%M")
            merged = str(r.get("note") or "") + ("\n" if r.get("note") else "") + stamp + note_append
            if len(merged) > NOTE_MAX:
                raise HTTPError(400, "덧붙이면 메모가 너무 깁니다(%d자, %d자 이하)." % (len(merged), NOTE_MAX))
            r["note"] = merged
        r["edited_at"] = now_str()
        r["edited_by"] = who(actor)
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]


def set_done(pid: int, done: bool, actor: dict, reply: str = None, ref: str = None):
    """열기·닫기. `reply`/`ref`(이미 clean_close_body 로 검증된 값)는 닫을 때만 쓰고 첫 닫기에만 적힌다.

    이미 닫힌 핀을 다시 닫으면 아무것도 바꾸지 않는다(§P0b-보완 D) — 두 번째 닫기가 done_at·closed_by 를
    덮어써 처음 닫은 사람이 사라지던 결함(실측)을 막는다. rev 도 그대로다. reply 를 다시 남기려면
    한 번 열고 닫아야 한다 — 그래서 다시 열 때 옛 close_reply/close_ref 를 지운다(다음 닫기가 새로 채운다)."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        if done:
            if r.get("done"):
                return public(r), False           # 이미 닫힘 — 아무것도 바꾸지 않는다(rev 도 그대로)
            r["done"] = True
            r["done_at"] = now_str()
            r["closed_by"] = who(actor)
            if reply:
                r["close_reply"] = reply
            if ref:
                r["close_ref"] = ref
            _clear_claim(r)                       # 닫으면 처리 중 표시도 함께 지운다(§P0c-C)
        else:
            r["done"] = False
            r["reopened_at"] = now_str()
            r["reopened_by"] = who(actor)
            r.pop("close_reply", None)
            r.pop("close_ref", None)
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]


def drop_pin(pid: int, actor: dict) -> bool:
    """핀을 pins.jsonl 에서 빼 pins.dropped.jsonl 로 옮긴다. restore 로 같은 id 를 되살린다."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return False, False
        rows.remove(r)
        _clear_claim(r)                           # 삭제해도 처리 중 표시를 남기지 않는다(§P0c-C)
        gone = dict(r, dropped_at=now_str(), dropped_by=who(actor))
        old, _ = read_jsonl(C.dropped)
        atomic_write(C.dropped, dump_jsonl(old + [gone]))
        return True, True
    return transact(fn)[1]


# ---------------------------------------------------------------- 처리 중 표시(claim, §P0c-C)
#
# 공저자와 그 에이전트가 같은 핀을 동시에 고칠 수 있다. TTL 있는 낙관적 표시로 충돌을 줄인다 —
# 잠금이 아니라 신호다: 다른 신원이 유효한 claim 을 쥔 핀을 닫거나 강제로 잡는 것을 막지는 않는다.

def claim_active(r: dict) -> bool:
    """이 핀에 만료되지 않은 claim 이 있는가. claim_until 은 epoch 초(시간대와 무관하게 비교)다."""
    cu = r.get("claim_until")
    return _is_num(cu) and float(cu) > time.time()


CLAIM_FIELDS = ("claimed_by", "claimed_at", "claim_ts", "claim_until", "eta_ts")


def _clear_claim(r: dict) -> None:
    for k in CLAIM_FIELDS:
        r.pop(k, None)


def _claim_int(d: dict, key: str, lo: int, hi: int):
    """본문의 선택 정수 하나. 없으면 None. 정수가 아니거나 lo 보다 작으면 400, hi 를 넘으면 hi 로 깎는다.

    깎는 쪽은 하위 호환이다 — 옛 절차대로 ttl_min=480 을 보내던 에이전트가 상한을 120 으로 낮춘 뒤 같은 값으로 연장하다
    400 을 받아 작업이 깨지지 않게 한다. 실제로 적용한 값은 응답의 *_applied 로 돌려준다."""
    if key not in d:
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or int(v) != v:
        raise HTTPError(400, "%s 은 정수여야 합니다." % key)
    v = int(v)
    if v < lo:
        raise HTTPError(400, "%s 은 %d 이상이어야 합니다(상한 %d 를 넘으면 %d 로 깎아 받습니다)." % (key, lo, hi, hi))
    return min(v, hi)


def clean_claim_body(d: dict) -> tuple:
    """claim 본문 → (ttl_min, eta_min 또는 None). 둘 다 선택이다.

    eta_min(1..240)은 처리 예상 시간 — 뷰어에 '처리 중 · 약 15분 · 20:40쯤'으로 보인다. ttl_min(1..120)은 잠금 자동
    해제까지의 시간(안전장치)이다. 상한을 넘는 값은 상한으로 깎는다(옛 ttl_min 480 호환). ttl_min 을 빼면 eta_min 이 있을 때
    min(120, max(30, eta×2)), 없으면 120."""
    eta = _claim_int(d, "eta_min", CLAIM_ETA_MIN, CLAIM_ETA_MAX)
    ttl = _claim_int(d, "ttl_min", CLAIM_TTL_MIN, CLAIM_TTL_MAX)
    if ttl is None:
        ttl = min(CLAIM_TTL_MAX, max(CLAIM_TTL_FLOOR, eta * 2)) if eta is not None else CLAIM_TTL_DEFAULT
    return ttl, eta


def clean_claim_ttl(d: dict) -> int:
    """예전 호출부 호환 — clean_claim_body 의 ttl 만."""
    return clean_claim_body(d)[0]


def claim_pin(pid: int, actor: dict, ttl_min: int, eta_min: int = None):
    """처리 중 표시를 걸거나(같은 신원이면) 연장한다. 없는 id 는 (None, False) — 호출부가
    {"ok": false} 를 낸다. 닫힌 핀이거나 다른 신원이 유효한 claim 을 쥐고 있으면 409.

    연장(같은 신원의 유효한 claim)은 시작 시각(claimed_at·claim_ts)을 그대로 두고 잠금(claim_until)을 지금부터 다시
    잰다. eta_min 을 주면 예상(eta_ts)도 지금부터 다시 잡고, 안 주면 앞서 준 예상을 둔다 — 넘겼으면 화면이
    '예상보다 늦어짐'으로 알린다. 새로 잡을 때 eta_min 이 없으면 eta_ts 도 없다(시작 시각과 경과 분으로 보인다)."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        if r.get("done"):
            raise HTTPError(409, "done", pin=public(r))
        me = who(actor)
        mine = claim_active(r) and (r.get("claimed_by") or {}).get("login") == me["login"]
        if claim_active(r) and not mine:
            raise HTTPError(409, "claimed", claimed_by=r["claimed_by"], claim_until=r["claim_until"],
                            eta_ts=r.get("eta_ts"))
        now = time.time()
        if not mine:
            _clear_claim(r)
            r["claimed_at"] = now_str()
            r["claim_ts"] = now
        elif not _is_num(r.get("claim_ts")):          # 옛 claim 을 연장 — 시작 시각을 epoch 로 채워 둔다
            r["claim_ts"] = _epoch(r.get("claimed_at")) or now
        r["claimed_by"] = me
        r["claim_until"] = now + ttl_min * 60
        if eta_min is not None:
            r["eta_ts"] = now + eta_min * 60
        r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), True
    return transact(fn)[1]


def unclaim_pin(pid: int, actor: dict):
    """처리 중 표시를 지운다 — 요청자 신원과 무관하다(신뢰 모델상 권한 제한을 두지 않는다).
    없는 id 는 (None, False)."""
    def fn(rows):
        r = find_pin(rows, pid)
        if r is None:
            return None, False
        had = "claimed_by" in r
        _clear_claim(r)
        if had:
            r["rev"] = int(r.get("rev") or 0) + 1
        return public(r), had
    return transact(fn)[1]


def restore_pin(pid: int, actor: dict) -> dict:
    """pins.jsonl 에 먼저 쓰고, 그것이 성공한 뒤에만 삭제 기록에서 뺀다.

    순서를 바꾸면 두 쓰기 사이에서 죽었을 때 핀이 양쪽 파일에서 모두 사라진다(실측).
    이 순서면 최악이 '양쪽에 다 있음'이고, 그것은 복구할 수 있다."""
    with PIN_LOCK:                                   # RLock — transact 와 삭제 기록 정리를 한 덩어리로
        rec = transact(lambda rows: _restore(rows, pid, actor))[1]
        old, _ = read_jsonl(C.dropped)
        atomic_write(C.dropped, dump_jsonl([r for r in old if r.get("id") != pid]))
        return rec


def _restore(rows: list, pid: int, actor: dict):
    old, _ = read_jsonl(C.dropped)
    hits = [r for r in old if r.get("id") == pid]
    if not hits:
        raise HTTPError(404, "삭제 기록에 핀 #%d 이 없습니다." % pid)
    if find_pin(rows, pid) is not None:
        raise HTTPError(409, "핀 #%d 이 이미 있습니다." % pid)
    rec = dict(hits[-1])
    rec.pop("dropped_at", None)
    rec.pop("dropped_by", None)
    rec["restored_at"] = now_str()
    rec["restored_by"] = who(actor)
    rec["rev"] = int(rec.get("rev") or 0) + 1
    sync_all([rec])
    rows.append(rec)
    rows.sort(key=lambda r: r["id"])
    return public(rec), True


def clear_pins() -> None:
    """전체를 .bak 으로 보관하고 비운다. pins.seq 는 건드리지 않으므로 id 는 이어진다."""
    with PIN_LOCK:
        if C.pins_jsonl.exists():                    # 같은 초에 두 번 비워도 앞 보관본을 덮지 않는다
            C.pins_jsonl.rename(unique_path("pins_%s" % time.strftime("%y%m%d_%H%M%S"), ".jsonl.bak"))
        render_pins_md([])


def ceil5(minutes: float) -> int:
    """분을 5분 단위로 올린다(최소 5). 뷰어 ceil5() 와 같은 규칙 — 견적은 대략이라 1분 단위로 보이면 거짓 정밀이다."""
    return max(5, int(math.ceil(minutes / 5.0 - 1e-9)) * 5)


def claim_md(r: dict, now: float = None) -> str:
    """pins.md 번호 칸의 처리 중 표시 — '처리 중(이름, 약 15분)'. 남은 예상은 5분 단위로 올리고, 넘겼으면 '예상 초과',
    예상 없이 잡은 옛 claim 은 이름만. 잠금 자동 해제 시각은 쓰지 않는다(예상 완료로 읽혔다)."""
    now = time.time() if now is None else now
    name = md_cell((r.get("claimed_by") or {}).get("name") or "?")
    eta = r.get("eta_ts")
    if not _is_num(eta):
        return "처리 중(%s)" % name
    left = (float(eta) - now) / 60.0
    return "처리 중(%s, %s)" % (name, "약 %d분" % ceil5(left) if left > 0 else "예상 초과")


def render_pins_md(rows: list) -> None:
    atomic_write(C.pins_md, pins_md_text(rows))


def md_cell(v, newline: str = " ") -> str:
    """pins.md 표 칸 하나. '|' 는 열을 늘리고 줄바꿈은 행을 끊는다 — 어느 칸이든 레코드 값이 그대로 들어가면
    표가 깨진다(실측: kind 'env:x|y' 가 8열 행을 만들었다). 모든 칸이 이 함수를 거친다."""
    s = str("" if v is None else v).replace("\r\n", "\n").replace("\r", "\n")
    return s.replace("|", "\\|").replace("\n", newline)


def region_text_of(r: dict) -> str:
    """보기 전용 핀의 위치 글: '쪽 3, 영역 가로 12–55% 세로 30–48%'."""
    fr = r.get("frac") if isinstance(r.get("frac"), list) and len(r["frac"]) == 4 else [0, 0, 0, 0]
    try:
        x, y, w, h = [float(v) * 100 for v in fr]
    except (TypeError, ValueError):
        x = y = w = h = 0.0
    return "쪽 %s, 영역 가로 %d–%d%% 세로 %d–%d%%" % (r.get("page", "?"), round(x), round(x + w), round(y), round(y + h))


def location_col(r: dict) -> str:
    """C.src 기준 상대경로 — 루트 파일은 basename 과 같아서 기존 행이 변하지 않는다.
    보기 전용 PDF 의 핀은 줄이 없으니 '쪽 N, 영역 …' 이다(PDF 경로는 문서 소절 머리에 있다)."""
    if is_region_pin(r):
        return md_cell(region_text_of(r))
    f = Path(str(r.get("file", "")))
    try:
        rel = f.resolve().relative_to(C.src.resolve())
        name = str(rel)
    except (ValueError, OSError, RuntimeError):
        name = f.name or str(r.get("name") or "")
    return "`%s L%s-L%s`" % (md_cell(name),md_cell(r.get("lo")), md_cell(r.get("hi")))


def range_label(r: dict) -> str:
    """범위 칸: scope 가 있으면 env*→env:<이름>, para→paragraph, raw/lines→lines, 없으면 기존 kind.
    어느 분기든 md_cell 로 이스케이프한다(env 분기만 빠져 있던 것이 결함이었다)."""
    if is_region_pin(r):
        return "영역"
    scope = r.get("scope")
    if scope and str(scope).startswith("env"):
        k = str(r.get("kind") or "")
        return md_cell(k if k.startswith("env:") else "env:%s" % (k or "?"))
    if scope == "para":
        return "paragraph"
    if scope in ("raw", "lines"):
        return "lines"
    return md_cell(r.get("kind") or "")


def render_quote(r: dict) -> str:
    """«quote…» 인용 예외: 핀 범위가 한 줄이고, 그 줄이 600자를 넘고, scope 가 raw/para/없음일 때만.
    보기 전용 PDF 의 핀은 늘 붙인다 — 줄 번호가 없어 영역 글자가 에이전트의 유일한 원문 단서다."""
    if is_region_pin(r):
        q = r.get("quote")
        return "«%s» " % md_cell(q) if q else ""
    scope = r.get("scope")
    if scope not in (None, "raw", "para"):
        return ""
    lo, hi = r.get("lo"), r.get("hi")
    if not (_is_int(lo) and _is_int(hi)) or lo != hi:
        return ""
    q = r.get("quote")
    if not q:
        return ""
    f = Path(str(r.get("file", "")))
    if not in_tree(str(f)):
        return ""
    lines = tex_lines(f)
    if not (1 <= lo <= len(lines)) or len(lines[lo - 1]) <= 600:
        return ""
    # q 는 저장될 때 이미 truncate_quote() 로 잘렸다(잘렸으면 …가 붙어 있다) — 여기서 다시 60자로
    # 자르면 이미 붙은 …까지 잘려 이중으로 잘린 것처럼 보인다. 파이프만 이스케이프한다.
    return "«%s» " % md_cell(q)


LEGEND = ("표시: '#N 범위 안'·'#N과 같은 범위' = N과 한 번에 고치고 둘 다 닫는다 · '#N과 일부 겹침' = 참고만, 각자 처리해도 된다 · "
          "'처리 중(이름, 약 N분)' = 다른 에이전트가 잡음, 건너뛴다 · '수정됨' = 저장 뒤 메모·범위가 바뀜 · "
          "'위치 잃음' = 위치를 되찾지 못함(네가 방금 고친 곳이면 확인 후 닫아도 된다) · "
          "«…» = 줄 안에서 가리킨 부분의 렌더 글자(검색 힌트, 원문과 다를 수 있음)")


def pins_md_text(rows: list, base: str = None) -> str:
    """에이전트가 한 번에 읽을 요약. 스니펫은 일부러 넣지 않는다 —
    줄 범위만 있으면 에이전트가 원본을 직접 읽는 편이 항상 더 싸고 정확하다.
    형식 지정자는 %s 만 쓴다 — 레코드 하나의 형이 틀려도 요약 전체가 죽지 않게.
    닫힌 핀은 목록에 내려받지 않는다(머리줄 건수로만) — 쌓여도 pins.md 크기가 늘지 않는다.

    base(§P0c-B): 안내 줄의 close 예시가 쓸 base URL. 안 주면(디스크에 쓰는 기본 경로) 지금처럼
    루프백이다. GET /pins.md 는 요청 Host 로 바꾼 값을 넘긴다 — 원격 base 일 때만 '원격: curl …'
    한 줄을 안내 문단에 덧붙인다(루프백은 이미 그 파일을 읽고 있으므로 생략).

    여러 문서(§여러 문서): 한 장 그대로 두고 문서별 소절(## 이름 · 키 · 경로)로 묶는다. 단일 문서이고 다른 문서
    키의 열린 핀도 없으면 소절 없이 예전 모양 그대로다."""
    loopback_base = "http://127.0.0.1:%d" % C.port
    is_remote = base is not None and base != loopback_base
    base = base or loopback_base
    openn = [r for r in rows if not r.get("done")]
    n_done = len(rows) - len(openn)
    rel = overlaps_by_id(rows)
    by_id = {r["id"]: r for r in rows}

    # §P0c-G: 작성자가 2명 이상(로그인 기준, 작성자 없는 옛 핀은 한 부류)일 때만 메모 앞에 @이름 을 붙인다.
    author_groups = set()
    for r in openn:
        a = r.get("author")
        author_groups.add(a.get("login") if a and a.get("login") else None)
    multi_author = len(author_groups) > 1

    rows_by_doc: dict = {}
    any_symbol = False
    for r in openn:
        syms = []
        badge = rel_badge(rel.get(r["id"], []), by_id, r)
        if badge:
            syms.append(badge)
        if claim_active(r):
            syms.append(claim_md(r))
        if r.get("edited_at"):
            syms.append("수정됨")
        if r.get("stale"):
            syms.append("위치 잃음")
        if syms:
            any_symbol = True
        idcol = md_cell(" · ".join(["%s" % r.get("id")] + syms))
        note = md_cell(r.get("note") or "", newline=" ⏎ ")
        if multi_author:
            an = (r.get("author") or {}).get("name")
            if an:
                note = "@%s: " % md_cell(an) + note
        q = render_quote(r)
        if q:
            any_symbol = True
            note = q + note
        rows_by_doc.setdefault(pin_doc_key(r), []).append(
            "| %s | %s | %s | %s | %s |" % (idcol, md_cell(r.get("page", 0)), location_col(r), range_label(r), note))

    known = [d.key for d in DOCS]
    sectioned = multi_doc() or any(k not in known[:1] for k in rows_by_doc)
    n_region = sum(1 for r in openn if is_region_pin(r))

    out = ["# 수정 요청 핀", "", "원고: `%s`" % C.src,
           "논문: %s · 저장소: %s" % (C.label, C.repo or "(없음)")]
    if not sectioned:
        head_short, built_at = _read_head(), _read_built_at()
        if head_short and head_short != "-" and built_at:           # §P0c-D: 없으면 통째로 생략한다
            out.append("기준: %s · 빌드 %s" % (head_short, built_at))
            out.append("다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    else:
        parts = []
        for d in DOCS:
            parts.append("%s(`%s`%s) %d건" % (md_cell(d.name), d.key, ", 보기 전용" if d.is_pdf else "",
                                              len(rows_by_doc.get(d.key, []))))
        for k in rows_by_doc:
            if k not in known:
                parts.append("설정에 없는 문서(`%s`) %d건" % (md_cell(k), len(rows_by_doc[k])))
        out.append("문서: " + " · ".join(parts))
        out.append("핀은 아래 문서별 소절(`## 이름 · 키 · 경로`)로 묶였다 — 위치 칸의 경로는 `--manuscript` 기준. "
                   "소절의 `기준:` 커밋이 다른 체크아웃에서 처리하면 먼저 `git rev-parse --short HEAD` 가 같은지 확인")
    out.append("갱신: %s  ·  열린 핀 %d건  ·  닫힌 핀 %d건(뷰어의 '닫힌 핀'에서 확인)" %
               (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), len(openn), n_done))
    out.append("")
    guidance = ("처리한 핀은 닫는다 — `curl -X POST -H 'Content-Type: application/json' "
                "-d '{\"reply\":\"무엇을 고쳤는지(≤500자)\",\"ref\":\"커밋/PR(≤80자)\"}' "
                "%s/api/pins/N/close`(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘) · "
                "줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다" % base)
    if is_remote:
        guidance += " · 원격: `curl -s %s/pins.md`" % base
    if C.repo:
        guidance += (" · 처리 전 자기 체크아웃의 `git remote get-url origin` 이 위 저장소와 같은지 확인. "
                      "다르면 다른 논문의 핀이니 멈춘다")
    if n_region:
        guidance += (" · 보기 전용 PDF 의 핀은 줄 번호가 없다 — 쪽·영역 글자(«…»)·메모로 무엇을 가리키는지 판단하고, "
                     "고칠 곳은 LaTeX 문서에서 찾는다(못 찾으면 닫지 말고 보고)")
    out.append(guidance)
    if any_symbol:
        out.append(LEGEND)
    header = ["| # | 쪽 | 위치 | 범위 | 메모 |", "|---|---|---|---|---|"]
    if not sectioned:
        rows_render = rows_by_doc.get(known[0], [])
        out += [""] + header
        out += rows_render if rows_render else ["| — | — | 열린 핀 없음 | | |"]
        return "\n".join(out) + "\n"
    shown = 0
    for d in DOCS:
        rs = rows_by_doc.get(d.key)
        if not rs:
            continue
        shown += 1
        title = "## %s · `%s` · `%s`" % (md_cell(d.name), d.key, md_cell(d.rel_path()))
        if d.is_pdf:
            title += " — 보기 전용 PDF(줄 번호 없음)"
        out += ["", title]
        with using_doc(d):
            head_short, built_at = _read_head(), _read_built_at()
        if head_short and head_short != "-" and built_at:
            out.append("기준: %s · %s %s" % (head_short, "그림" if d.is_pdf else "빌드", built_at))
        out += [""] + header + rs
    for k, rs in rows_by_doc.items():
        if k in known:
            continue
        shown += 1
        out += ["", "## 설정에 없는 문서 · `%s` — 이 뷰어의 --doc 목록에 없다. 처리 전에 사용자에게 확인" % md_cell(k),
                ""] + header + rs
    if not shown:
        out += ["", "열린 핀 없음"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 선택 해석

def pick(d: dict) -> dict:
    """드래그 영역 → 원문 줄 범위 + 범위 사다리.

    SyncTeX 후보와 텍스트 후보를 같은 척도로 겨루게 한다. 어느 한쪽을 조건부
    폴백으로 두면, SyncTeX 가 조용히 틀렸을 때(minipage·tabular 안) 그 오답을
    걸러낼 방법이 없다.

    pdf_build(선택)는 드래그할 때 화면에 있던 빌드다(META.pages_build). 재빌드가 끝난 뒤 뷰어가 쪽을
    바꾸기 전의 드래그는 옛 레이아웃 좌표이므로 그 빌드의 PDF 로 되짚고, 응답의 pdf_build 로 돌려준다 —
    뷰어는 그 값을 핀 저장(/api/pin)에 그대로 실어 '어느 빌드의 좌표인지'를 남긴다(§위치 추정)."""
    want = d.get("pdf_build")
    if want is not None:
        if not valid_build_name(want):
            raise HTTPError(400, "pdf_build 는 쪽 디렉토리 이름(pages 또는 pages-<시각>)이어야 합니다.")
        if not (cur_doc().dir / want).is_dir():
            return {"error": "화면의 PDF 가 이미 지워진 옛 빌드입니다 — 화면을 새 PDF 로 바꿨으니 다시 고르세요.",
                    "pdf_build_gone": True}
    pdir = pages_dir_for(want) if want is not None else cur_pages()
    pages = page_list(pdir)
    page = _int(d.get("page"), "page")
    if not 1 <= page <= len(pages):
        raise HTTPError(400, "page 는 1..%d 이어야 합니다." % len(pages))
    pw, ph = pages[page - 1]["pt_w"], pages[page - 1]["pt_h"]
    xs = sorted(min(max(_num(d.get(k), k), 0.0), pw) for k in ("x0", "x1"))
    ys = sorted(min(max(_num(d.get(k), k), 0.0), ph) for k in ("y0", "y1"))
    x0, x1 = xs
    y0, y1 = ys
    frac = d.get("frac")
    if frac is not None and not (isinstance(frac, list) and len(frac) == 4 and
                                 all(not isinstance(v, bool) and isinstance(v, (int, float))
                                     and math.isfinite(v) for v in frac)):
        raise HTTPError(400, "frac 은 숫자 4개 목록입니다.")

    pdf = cur_pdf(pdir)
    rtext = region_text(pdf, page, x0, y0, x1, y1)
    D = cur_doc()
    if D.is_pdf:
        return _pick_region(D, pdir, page, (x0, y0, x1, y1), (pw, ph), frac, rtext)
    sy = by_synctex(pdf, page, x0, y0, x1, y1)

    src = to_source(sy[0]) if sy else D.main
    if src.suffix in (".bbl", ".bib"):
        return {"error": "여기는 생성 파일(%s)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다."
                         % src.suffix}
    try:
        src = safe_src(str(src))
    except HTTPError:
        return {"error": "SyncTeX 가 원고 밖 파일을 가리킵니다(%s). PDF 재빌드 뒤 다시 골라 보세요." % src}

    lines = tex_lines(src)
    if not lines:
        return {"error": "원문 파일을 읽지 못했습니다: %s" % src}
    tw = token_weights(rtext, lines, file_key(src))

    cands = []
    if sy:
        cands.append(("synctex", sy[1], sy[2], score_range(tw, lines, sy[1], sy[2])))
    alt = by_text(tw, lines, sy[1] if sy else None)
    if alt:
        cands.append(("text", alt[0], alt[1], alt[2]))
    if not cands:
        return {"error": "그 자리에서 원문을 되짚지 못했습니다. 글자가 있는 쪽으로 조금 넓게 잡아 보세요."}

    # 동점이면 SyncTeX 를 남긴다 — 글자가 없는 영역(그림)에서는 그쪽만 맞다.
    cands.sort(key=lambda c: (-c[3], c[0] != "synctex"))
    via, raw_lo, raw_hi, best = cands[0]
    warn = ""
    if tw and best < 0.3:
        warn = "이 영역은 원문 대조가 약합니다(%.0f%%). 줄 범위를 눈으로 확인하세요." % (best * 100)

    lad = compute_levels(lines, raw_lo, raw_hi)
    lo, hi = lad["lo"], lad["hi"]
    if not warn and len(cands) == 2 and abs(cands[0][3] - cands[1][3]) < 0.12:
        # 같은 블록으로 확장되면 두 경로가 갈린 것이 아니다 — 경고하지 않는다.
        if not (lo <= cands[1][1] <= hi):
            warn = "두 경로가 다른 곳을 가리킵니다(L%d / L%d). 확인이 필요합니다." % (cands[0][1], cands[1][1])

    if source_newer(pdir.name) > 2:
        stale_note = "화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요."
        warn = stale_note + (" " + warn if warn else "")
    bstate = build_state_snapshot()
    if bstate["state"] == "running" and bstate["phase"] == "latex":
        warn = (warn + " " if warn else "") + "빌드 중이라 결과가 흔들릴 수 있습니다."

    quote = truncate_quote(norm(rtext), 60)
    return {"file": str(src), "name": src.name, "page": page, "lo": lo, "hi": hi,
            "raw_lo": raw_lo, "raw_hi": raw_hi, "kind": lad["kind"], "via": via,
            "score": round(best, 2), "warn": warn, "n_lines": len(lines),
            "snippet": snippet(lines, lo, hi), "frac": frac, "quote": quote,
            "levels": lad["levels"], "default_level": lad["default_level"],
            "overlaps": overlaps_for_range(str(src), lo, hi), "pdf_build": pdir.name}


def _pick_region(D: Doc, pdir: Path, page: int, box: tuple, size: tuple, frac, rtext: str) -> dict:
    """보기 전용 문서의 pick — SyncTeX 없이 쪽·영역과 영역 글자(pdftotext)만 돌려준다.
    frac 을 안 보냈으면(에이전트 curl) 좌표로 만든다 — 보기 전용 핀은 영역이 위치의 전부다."""
    x0, y0, x1, y1 = box
    pw, ph = size
    if frac is None:
        frac = [x0 / pw, y0 / ph, (x1 - x0) / pw, (y1 - y0) / ph]
    text = norm(rtext)
    warn = ""
    if not text:
        warn = "이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요."
    bstate = build_state_snapshot()
    if bstate["state"] == "running":
        warn = (warn + " " if warn else "") + "PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요."
    return {"doc": D.key, "kind": "region", "view_only": True, "page": page, "frac": frac,
            "pdf": D.rel_path(), "name": D.main.name, "quote": truncate_quote(text, PDF_QUOTE_MAX),
            "n_chars": len(text), "warn": warn, "overlaps": [], "pdf_build": pdir.name}


def snippet_api(q: dict) -> dict:
    if cur_doc().is_pdf:
        raise HTTPError(400, "보기 전용 문서(%s)에는 원문 줄이 없습니다." % cur_doc().key)
    f = safe_src((q.get("file") or [""])[0])
    lines = tex_lines(f)
    try:
        lo = int((q.get("lo") or [""])[0])
        hi = int((q.get("hi") or [""])[0])
    except ValueError:
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.")
    if not 1 <= lo <= hi <= len(lines):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi))
    out = {"file": str(f), "name": f.name, "lo": lo, "hi": hi, "n": hi - lo + 1,
           "n_lines": len(lines), "snippet": snippet(lines, lo, hi)}
    if (q.get("levels") or ["0"])[0] == "1":
        lad = compute_levels(lines, lo, hi)
        out["levels"] = lad["levels"]
        out["default_level"] = lad["default_level"]
    return out


def overlaps_api(q: dict) -> dict:
    """GET /api/overlaps — 파일·범위만으로 저장 전 선택의 겹침을 묻는다(에이전트·옛 뷰어 호환용).

    지금 뷰어는 범위가 바뀔 때마다 자기 PINS 로 같은 규칙(overlapsFor)을 돌려 왕복 없이 센다 — 응답이
    늦게 오는 사이 [핀 저장]을 누르면 배너 없이 중복이 저장될 수 있어서다. 이 경로는 83b91a5 뷰어가 불렀다."""
    f = safe_src((q.get("file") or [""])[0])
    lines = tex_lines(f)
    try:
        lo = int((q.get("lo") or [""])[0])
        hi = int((q.get("hi") or [""])[0])
    except ValueError:
        raise HTTPError(400, "lo·hi 는 정수여야 합니다.")
    if not 1 <= lo <= hi <= len(lines):
        raise HTTPError(400, "줄 범위가 파일(%d줄) 밖입니다: L%d-L%d" % (len(lines), lo, hi))
    return {"overlaps": overlaps_for_range(str(f), lo, hi)}


# ---------------------------------------------------------------- 신원(tailscale serve 헤더)

def hdr_text(v) -> str:
    """tailscale 은 비 ASCII 값을 RFC 2047(=?utf-8?q?…?=)로 싣는다. 날것 UTF-8 이 오면 latin-1 로 풀린 것을 되돌린다."""
    if not v:
        return ""
    v = str(v).strip()
    if "=?" in v:
        try:
            v = str(make_header(decode_header(v)))
        except Exception:                                # noqa: BLE001 — 헤더 하나 때문에 요청을 떨구지 않는다
            pass
    else:
        try:
            v = v.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return "".join(ch for ch in v if ch.isprintable())[:300]


def actor_of(headers) -> tuple:
    """(행위자, 헤더로 왔는지). 서버는 127.0.0.1 에만 바인딩되므로 이 헤더는 tailscale serve 를 거쳐서만 온다."""
    login = hdr_text(headers.get("Tailscale-User-Login"))
    if not login:
        return dict(LOCAL_ACTOR), False
    a = {"login": login[:200], "name": (hdr_text(headers.get("Tailscale-User-Name")) or login.split("@")[0])[:100]}
    pic = hdr_text(headers.get("Tailscale-User-Profile-Pic"))
    if pic.startswith("https://") and len(pic) <= 1000:
        a["pic"] = pic
    return a, True


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def split_host(v: str) -> tuple:
    """'name:port' / '[::1]:port' → (소문자 이름, 포트 또는 None). 형식이 틀리면 ('', None)."""
    v = (v or "").strip().lower()
    if v.startswith("["):
        name, _, rest = v[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    else:
        name, _, port = v.partition(":")
    if port and not re.fullmatch(r"[0-9]{1,5}", port):
        return "", None
    return name.rstrip("."), (int(port) if port else None)


def host_ok(host: str) -> bool:
    """루프백 이름이면 포트는 보지 않는다 — SSH -L 로 다른 로컬 포트에 포워딩해도 Host 가
    'localhost:9000'처럼 실제 서버 포트와 달라질 수 있다. DNS 리바인딩 공격의 Host 는 루프백 이름이
    아니므로(외부 도메인이 127.0.0.1 로 풀리는 것이지 Host 헤더 자체가 'localhost'가 되는 게 아니다)
    여기서 포트를 빼도 그 방어는 약해지지 않는다. 교차 출처(CSRF) 방어는 origin_ok 가 맡는다."""
    name, _ = split_host(host)
    if name in LOOPBACK:
        return True
    return name.endswith(".ts.net")


DEFAULT_PORT = {"http": 80, "https": 443}


def origin_ok(origin: str, host) -> bool:
    """Origin 이 이 요청이 도착한 Host 와 같은 편인가. 규칙은 Host 종류로 갈린다.

    - Host 가 루프백: Origin 도 루프백이어야 한다. 포트는 보지 않는다 — SSH -L 로 포워딩하면 브라우저의
      Origin·Host 포트가 서버 바인딩 포트와 다르다(실측: 18110→18106 POST 가 403). 루프백 Host 로
      *.ts.net Origin 이 오는 정상 경로는 없다(tailscale serve 는 Host 를 보존한다, SKILL.md 실측) —
      받으면 다른 tailnet 의 Funnel 공개 페이지가 로컬 사용자 브라우저로 CSRF 를 한다(실측: 200).
    - Host 가 *.ts.net: Origin 은 그 호스트와 이름·포트가 같아야 한다(생략 포트는 scheme 기본값).
    Origin 이 없는 요청(curl·에이전트·같은 출처 GET)은 이 함수까지 오지 않는다."""
    u = urlparse(origin.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        return False                                   # 'null' 출처(샌드박스 iframe·file://) 포함
    try:
        oport = u.port
    except ValueError:
        return False
    name = u.hostname.lower().rstrip(".")
    hname, hport = split_host(host or "")
    if not hname or hname in LOOPBACK:                 # Host 가 없으면(HTTP/1.0) 루프백으로 친다 — 더 엄한 쪽
        return name in LOOPBACK
    if hname.endswith(".ts.net"):
        dflt = DEFAULT_PORT[u.scheme]
        return name == hname and (oport or dflt) == (hport or dflt)
    return False


def remote_base_for(host_raw: str) -> str:
    """GET /pins.md 안내 줄에 쓸 base URL(§P0c-B). Host 가 *.ts.net 이면 'https://<Host 그대로,
    포트 포함>', 아니면(루프백·Host 없음) 지금까지의 루프백 URL. _check_origin() 이 이미 Host 를
    검증한 뒤(루프백 또는 *.ts.net)이므로 여기서는 종류만 가른다."""
    name, _ = split_host(host_raw or "")
    if name.endswith(".ts.net"):
        return "https://%s" % host_raw.strip()
    return "http://127.0.0.1:%d" % C.port


# ---------------------------------------------------------------- 뷰어

HTML = r"""<!doctype html><html lang="ko" data-theme="dark"><head><meta charset="utf-8">
<script>
(function(){var p=null;try{p=JSON.parse(localStorage.getItem('pinPrefs')||'null');}catch(e){}
 if(!p||typeof p!=='object'){p={theme:'system'};}else if(!p.theme){p.theme='dark';}
 try{localStorage.setItem('pinPrefs',JSON.stringify(p));}catch(e){}
 var t=p.theme,eff=t;if(t==='system'){eff=(window.matchMedia&&matchMedia('(prefers-color-scheme: light)').matches)?'light':'dark';}
 document.documentElement.setAttribute('data-theme',eff==='light'?'light':'dark');})();
</script>
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,interactive-widget=resizes-content">
<title>__LABEL__ · 원고 핀</title>
<link rel="icon" href="__FAVICON_HREF__">
<style>
/* ---------------- 디자인 토큰(references/design.md §디자인 토큰). shadcn/ui 의 체계(이름·역할)만 빌렸다 — 코드는 없다.
   색 리터럴은 이 두 블록(다크 :root · 라이트 :root[data-theme=light]) 안에만 둔다. 규칙은 전부 var(--…) 로 쓴다.
   회귀 테스트(FrontendDesignTokens)가 블록 밖의 색·radius·font-size 리터럴을 막는다. 중립색은 zinc 계열이다. */
:root{color-scheme:dark;
  --background:#09090b;--foreground:#fafafa;
  --sidebar:#18181b;--card:#131316;--card-foreground:#fafafa;--popover:#18181b;--popover-foreground:#fafafa;
  --muted:#27272a;--muted-foreground:#a1a1aa;--subtle-foreground:#8b8b94;
  --secondary:#27272a;--secondary-foreground:#fafafa;--accent:#2e2e33;--accent-foreground:#fafafa;
  --border:#27272a;--border-strong:#52525b;--input:#3f3f46;--field:#0c0c0e;--code:#0c0c0e;--outline-bg:#3f3f4633;
  --primary:#6ea8fe;--primary-foreground:#0b1220;--ring:var(--primary);
  --destructive:#f0787a;--destructive-foreground:#1f0708;
  --success:#4ec9a0;--success-foreground:#06231b;--warning:#e0a458;--warning-foreground:#2a1a04;
  --status-open:var(--success);--status-open-foreground:var(--success-foreground);--status-claimed:#f0b43c;
  --status-closed:var(--success);--status-dropped:#71717a;--status-warning:var(--warning);
  --tooltip:#09090b;--tooltip-foreground:#fafafa;
  --shadow-color:#00000088;--shadow-page:0 2px 18px var(--shadow-color)}
:root[data-theme=light]{color-scheme:light;
  --background:#e4e4e7;--foreground:#09090b;
  --sidebar:#ffffff;--card:#fafafa;--card-foreground:#09090b;--popover:#ffffff;--popover-foreground:#09090b;
  --muted:#f4f4f5;--muted-foreground:#52525b;--subtle-foreground:#71717a;
  --secondary:#f4f4f5;--secondary-foreground:#18181b;--accent:#e4e4e7;--accent-foreground:#09090b;
  --border:#e4e4e7;--border-strong:#a1a1aa;--input:#d4d4d8;--field:#ffffff;--code:#f4f4f5;--outline-bg:#ffffff;
  --primary:#1860cf;--primary-foreground:#ffffff;
  --destructive:#cf222e;--destructive-foreground:#ffffff;
  --success:#1a7f5a;--success-foreground:#ffffff;--warning:#8a5c00;--warning-foreground:#ffffff;
  --status-claimed:#b86e00;--status-dropped:#71717a;
  --tooltip:#18181b;--tooltip-foreground:#fafafa;
  --shadow-color:#00000022;--shadow-page:0 1px 6px var(--shadow-color)}
/* 테마와 무관한 척도: radius 3단(원형 점·아바타만 50%), 글자 5단, 간격 6단, 컨트롤 높이. 이름표 색(--brand)은 인스턴스마다
   서버가 채우고(--accent 인자) 테마가 바뀌어도 그대로다. */
:root{--brand:__ACCENT__;--brand-foreground:#ffffff;
  --radius-sm:4px;--radius:6px;--radius-lg:10px;
  --text-xs:11px;--text-sm:12px;--text-base:13px;--text-lg:14px;--text-xl:16px;
  --space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:20px;--space-6:24px;
  --control-h-sm:24px;--control-h:28px;--control-h-lg:36px;--control-h-touch:44px;
  --shadow-sm:0 1px 4px var(--shadow-color);--shadow:0 4px 16px var(--shadow-color);--shadow-lg:0 6px 24px var(--shadow-color);
  --font-sans:-apple-system,BlinkMacSystemFont,"Pretendard","Noto Sans KR",sans-serif;
  --font-mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--background);color:var(--foreground);font:var(--text-lg)/1.55 var(--font-sans);
  display:flex;height:100vh;height:calc(100dvh - var(--kb,0px));overflow:hidden}
/* PDF 영역: 브라우저 핀치 확대를 막고 스크롤만 넘긴다 — 두 손가락은 앱 확대가 받는다(references/design.md §PDF 영역 전용 확대). */
/* #main = 문서 탭 줄 + PDF 영역(§여러 문서). 폭·높이 규칙은 #main 이 받고 #left 는 그 안에서 스크롤한다. */
#main{flex:1;display:flex;flex-direction:column;min-width:240px;min-height:0;position:relative}
#left{flex:1;overflow:auto;padding:var(--space-4) var(--space-4) 60vh 44px;min-width:240px;min-height:0;touch-action:pan-x pan-y}
/* 패널 폭 손잡이(wide·mid 공통, Pointer Events): 보이는 막대는 6px, 잡는 영역은 ::after 로 넓힌다(터치 24px).
   마우스에서는 왼쪽 본문 스크롤바를 덮지 않게 좌우 3px 만 넓힌다. */
#grip{position:relative;z-index:6;width:6px;cursor:col-resize;background:var(--border);flex:none;touch-action:none}
#grip::after{content:'';position:absolute;top:0;bottom:0;left:-3px;right:-3px}
#grip:hover,#grip.on,#grip:focus-visible{background:var(--border-strong)}
body.resizing{-webkit-user-select:none;user-select:none;cursor:col-resize}
body.resizing #left{pointer-events:none}
#sheet-grip{display:none}
#right{width:430px;min-width:280px;max-width:80vw;border-left:1px solid var(--border);background:var(--sidebar);
  display:flex;flex-direction:column;flex:none;min-height:0}
.bar{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
#bar1{flex-wrap:wrap;gap:var(--space-1);padding:var(--space-2) 10px;--tb-h:var(--control-h)}   /* 좁힌 패널에서는 두 줄로 — 가로로 넘치지 않게 */
/* 도구 줄은 한 높이(--tb-h: 데스크톱 28px, 터치 44px). 쪽 칸도 버튼과 같은 높이·글자 크기다 — 일반 입력 칸 규칙(14px, 6px 여백)을
   그대로 받아 버튼보다 8px 크고 글자도 커서 줄의 조화가 깨졌다(저자 지적 2026-09-23). 아이콘 버튼은 정사각형이다. */
#bar1>button,#bar1>input{height:var(--tb-h)}
#bar1 button{padding:0 var(--space-2);white-space:nowrap}
#bar1 button.btn-icon{padding:0;width:var(--tb-h);min-width:var(--tb-h)}
#bar1 input.n{width:40px;flex:none;padding:0 var(--space-1);font-size:var(--text-base);line-height:normal;border-radius:var(--radius)}
#bar1 .chip{height:var(--control-h-sm);display:block;line-height:var(--control-h-sm);padding:0 var(--space-2);flex:0 1 auto;min-width:40px}
/* ---------------- 컴포넌트(references/design.md §컴포넌트). shadcn/ui 의 변형 이름을 빌린 클래스 — 모든 버튼·배지가 이 한 벌이다.
   버튼 변형: (클래스 없음) = outline · .btn-default(주요 동작, 패널에 하나) · .btn-secondary · .btn-soft([완료]) · .btn-ghost · .btn-destructive
   버튼 크기: (클래스 없음) = default(28px) · .btn-sm(24px 안팎) · .btn-icon(정사각형, .btn-sm 과 겹치면 작은 정사각형)
   배지: .badge(= outline) · .badge-default · .badge-secondary · .badge-destructive · 상태 .badge-claimed · .badge-warning */
button{display:inline-flex;align-items:center;justify-content:center;gap:var(--space-1);
  background:var(--outline-bg);color:var(--foreground);border:1px solid var(--input);border-radius:var(--radius);
  padding:var(--space-1) 10px;cursor:pointer;font:inherit;font-size:var(--text-base);line-height:1.4;
  transition:background-color .12s,border-color .12s,color .12s}
/* 아이콘(Lucide, vendor/lucide/README.md): 글자색을 따르는 선 아이콘. 버튼 안에서는 글자 옆에 4px 틈으로 붙는다. */
.ic{width:16px;height:16px;flex:none;display:inline-block;vertical-align:-3px;pointer-events:none}
.kh{font-weight:400;opacity:.8;font-size:var(--text-sm)}
button:hover{background:var(--accent);color:var(--accent-foreground)}
button:disabled{opacity:.65;cursor:default}
button.btn-default{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary);font-weight:600}
button.btn-default:hover{background:color-mix(in srgb,var(--primary) 88%,var(--background));color:var(--primary-foreground)}
button.btn-secondary{background:var(--secondary);color:var(--secondary-foreground);border-color:transparent}
button.btn-secondary:hover{background:color-mix(in srgb,var(--secondary) 88%,var(--foreground))}
button.btn-ghost{background:transparent;border-color:transparent}
button.btn-ghost:hover{background:var(--accent)}
/* soft: 옅은 강조(주 색 틴트). 카드의 [완료] 전용 — 저자 지정 2026-09-23(옅은 파랑). secondary 토큰은 셈 배지가 쓰므로 건드리지 않는다 */
button.btn-soft{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary);border-color:transparent}
button.btn-soft:hover{background:color-mix(in srgb,var(--primary) 14%,transparent);color:var(--primary);border-color:color-mix(in srgb,var(--primary) 45%,transparent)}   /* 바탕을 더 칠하면 라이트 글자 대비가 4.5 아래로 — 테두리로 표시 */
button.btn-destructive{background:color-mix(in srgb,var(--destructive) 10%,transparent);color:var(--destructive);border-color:transparent}
button.btn-destructive:hover{background:color-mix(in srgb,var(--destructive) 18%,transparent);color:var(--destructive)}
button.btn-sm{padding:2px var(--space-2);font-size:var(--text-sm)}
button.btn-icon{flex:none;padding:0;width:var(--control-h);min-width:var(--control-h);height:var(--control-h)}
button.btn-icon.btn-sm{width:var(--control-h-sm);min-width:var(--control-h-sm);height:var(--control-h-sm)}
:focus-visible{outline:2px solid var(--ring);outline-offset:1px}
.badge{display:inline-flex;align-items:center;gap:3px;padding:1px 6px;border:1px solid var(--border-strong);border-radius:var(--radius-sm);
  background:transparent;color:var(--muted-foreground);font-size:var(--text-xs);font-weight:400;line-height:1.45;white-space:nowrap}
.badge .ic{width:12px;height:12px}
.badge-default{background:var(--primary);border-color:var(--primary);color:var(--primary-foreground)}
.badge-secondary{background:var(--secondary);border-color:transparent;color:var(--secondary-foreground)}
.badge-destructive{border-color:var(--destructive);color:var(--destructive)}
.badge-warning{border-color:var(--status-warning);color:var(--status-warning)}
.badge-claimed{border-color:var(--status-claimed);color:var(--foreground)}
.badge-claimed .ic{color:var(--status-claimed)}
.badge-claimed.late{border-color:var(--status-warning);color:var(--status-warning)}
.badge-claimed.late .ic{color:var(--status-warning)}
button.badge{cursor:pointer;padding:1px 6px;border-radius:var(--radius-sm);font-size:var(--text-xs);line-height:1.45}
button.badge:hover{background:var(--accent)}
.card{background:var(--card);color:var(--card-foreground);border:1px solid var(--border);border-radius:var(--radius-lg)}
input,textarea{background:var(--field);color:var(--foreground);border:1px solid var(--input);border-radius:var(--radius);padding:6px var(--space-2);
  font:inherit;width:100%}
input::placeholder,textarea::placeholder{color:var(--muted-foreground)}
textarea{resize:vertical;min-height:4.8em}
input.n{width:58px;text-align:center}
.sp{flex:1}
.pg{position:relative;margin:0 auto 18px;box-shadow:var(--shadow-page);user-select:none}
:root[data-theme=light] .pg{border:1px solid var(--border)}
.pg img{width:100%;height:100%;display:block}
/* 벡터 렌더링(references/design.md §벡터 렌더링): 쪽 캔버스(.vb)는 쪽 상자를 꽉 채우고, 확대가 픽셀 상한을 넘으면
   보이는 부분만 원래 해상도로 그린 상세 캔버스(.dt)를 쪽 안 % 좌표로 겹친다. 캔버스가 있으면 밑의 PNG 는 숨긴다. */
.pg>canvas{position:absolute;display:block;pointer-events:none}
.pg>canvas.vb{left:0;top:0;width:100%;height:100%}
.pg.drawn>img{visibility:hidden}
.pg .no{position:absolute;top:6px;left:6px;color:var(--muted-foreground);font-size:var(--text-xs);background:var(--card);
  padding:1px 6px;border-radius:var(--radius-sm);box-shadow:var(--shadow-sm);line-height:1.5}
.sel{position:absolute;border:2px solid var(--primary);background:color-mix(in srgb,var(--primary) 13%,transparent);pointer-events:none}
.sel.pending{border-style:dashed}
.sel i{position:absolute;top:-21px;left:-2px;background:var(--primary);color:var(--primary-foreground);font-size:var(--text-xs);font-style:normal;
  padding:1px 6px;border-radius:var(--radius-sm);white-space:nowrap}
.mark{position:absolute;border:2px solid var(--status-open);background:color-mix(in srgb,var(--status-open) 8%,transparent);pointer-events:none}
.mark.st{border-color:var(--warning);background:color-mix(in srgb,var(--status-warning) 8%,transparent)}
.mark.est{border-style:dashed}
.mark.hi{border-width:3px}
.mark b{position:absolute;top:-2px;left:-24px;background:var(--status-open);color:var(--status-open-foreground);border-radius:50%;
  width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:var(--text-sm);pointer-events:auto;cursor:pointer}
.mark.st b{background:var(--warning);color:var(--warning-foreground)}
.mark.flash{animation:flash .6s ease-in-out 3}
@keyframes flash{50%{box-shadow:0 0 0 5px var(--primary)}}
#banner{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);background:var(--card);display:flex;gap:6px;flex-wrap:wrap;
  align-items:center;font-size:var(--text-base)}
#build-err{padding:var(--space-2) var(--space-3);border-bottom:1px solid var(--border);background:var(--card);font-size:var(--text-base)}
#composer{flex:none;max-height:62vh;overflow:auto;padding:var(--space-3);border-bottom:1px solid var(--border);background:var(--card)}
#list{flex:1;overflow:auto;padding:0 var(--space-3) 32px;min-height:0}   /* 위 여백은 구획 머리(.list-head)가 가진다 — sticky 가 여백만큼 내려앉지 않게 */
.busy{opacity:.45}
pre{background:var(--code);border:1px solid var(--border);border-radius:var(--radius);padding:9px;overflow:auto;font-size:var(--text-sm);
  line-height:1.5;max-height:44vh;font-family:var(--font-mono);tab-size:2;margin:6px 0}
pre.wrap{white-space:pre-wrap;word-break:break-word}
pre.nowrap{white-space:pre}
/* ---------------- 작성 패널(references/design.md §패널 정리): 8px 격자, 같은 높이, 강조 색(--acc)은 [핀 저장] 하나.
   위치 한 줄(파일·줄 + 쪽 + 일치 배지 + 복사) → 범위 분절 컨트롤 → 한 줄씩 스테퍼 → 원문 4줄 → 메모 → 아래 고정 동작 줄. */
.c-loc-row{display:flex;align-items:center;gap:var(--space-2)}
.c-loc-main{flex:1;min-width:0;display:flex;flex-wrap:wrap;align-items:center;gap:var(--space-1) var(--space-2)}
.c-loc-main .loc{font-weight:600}
#c-page{color:var(--muted-foreground);font-size:var(--text-sm)}
.c-tools{display:flex;align-items:center;gap:var(--space-2);margin:0 0 8px}
.step{display:inline-flex;flex:none;border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden}
.step{align-items:stretch}
.step button{border:0;border-radius:0;min-width:30px;padding:3px 6px}
.step button+button{border-left:1px solid var(--border)}
.step .sl{display:inline-flex;align-items:center;padding:0 6px;font-size:var(--text-sm);color:var(--muted-foreground);background:var(--field)}
.step .sl+button{border-left:1px solid var(--border)}
.step button+.sl{border-left:1px solid var(--border)}
button.tg[aria-pressed=false]{color:var(--muted-foreground)}
button.tg[aria-pressed=true]{border-color:var(--border-strong)}
#c-snip,.e-snip{margin:0}
#c-snip:not(.open){max-height:calc(6em + 18px);overflow:hidden}   /* 접힌 원문은 4줄 — 넘치면 흐리게 끊고 [펼치기] */
#c-snip.clip:not(.open){-webkit-mask-image:linear-gradient(var(--foreground) 60%,transparent);mask-image:linear-gradient(var(--foreground) 60%,transparent)}
#c-snip.open{max-height:44vh}
.e-snip{max-height:calc(9em + 18px)}
.snip-foot{display:flex;justify-content:flex-end}
.snip-foot button{color:var(--muted-foreground)}
#note{margin-top:8px}
#c-overlap{display:flex;flex-wrap:wrap;gap:var(--space-2);margin:8px 0;padding:var(--space-2);border:1px solid var(--border-strong);border-radius:var(--radius-lg);font-size:var(--text-base)}
#c-overlap>span{flex-basis:100%}
#c-overlap button{flex:1 1 0;min-width:0}
/* 동작 줄은 패널 바닥에 고정한다(목록을 스크롤해도, 가상 키보드가 올라와도 보인다). 작성 패널이 닫히면 함께 숨는다. */
#c-actions{flex:none;display:grid;grid-template-columns:1fr 2fr;gap:var(--space-2);padding:var(--space-2) var(--space-3);border-top:1px solid var(--border);background:var(--sidebar);z-index:3}
#composer[hidden]~#c-actions{display:none}
#c-actions button{min-height:var(--control-h-lg);font-size:var(--text-base)}
#composer:not([hidden])~#list #empty{display:none}   /* 고르는 중에는 첫 화면 안내 문단을 숨긴다 */
.loc{font-family:var(--font-mono);color:var(--primary);font-size:var(--text-base);cursor:copy;overflow-wrap:anywhere}
.dim{color:var(--muted-foreground);font-size:var(--text-sm)}
.row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
/* 분절 컨트롤(범위 사다리·패널 폭): 한 줄, 넘치면 가로 스크롤. 고른 칸은 강조 색이 아니라 한 단계 밝은 면으로 보인다. */
.seg{position:relative;display:flex;flex-wrap:nowrap;overflow-x:auto;gap:2px;margin:8px 0;padding:2px;border:1px solid var(--border);
  border-radius:var(--radius-lg);background:var(--field);scrollbar-width:none;overscroll-behavior-x:contain}
.seg::-webkit-scrollbar{display:none}
.seg button{flex:1 0 auto;background:transparent;border-color:transparent;border-radius:var(--radius);font-size:var(--text-sm);padding:3px 10px;
  white-space:nowrap;color:var(--muted-foreground)}
.seg button.on{background:var(--accent);border-color:var(--border-strong);color:var(--foreground);font-weight:600}
.seg button .k{font-weight:400;color:var(--muted-foreground)}
.seg button .k.wn{color:var(--warning)}
.wn{color:var(--warning)}
.warnline{color:var(--warning);font-size:var(--text-sm);margin-top:6px}
.errline{color:var(--destructive);font-size:var(--text-base);margin-top:6px}
.pin{position:relative;padding:var(--space-2) var(--space-3);margin-bottom:8px}   /* 모양은 .card */
/* 상태 띠(references/design.md §상태 표현): 열림은 띠 없음, 처리 중은 호박색. 닫힘(초록)·삭제(회색) 띠는 아래 보관함 행에 있다.
   테두리 폭을 바꾸면 글자가 밀리므로 카드 안쪽 왼쪽에 겹쳐 그린다. 대비(비텍스트 3:1)는 두 테마 모두 확인했다. */
.pin.claimed::before{content:'';position:absolute;left:-1px;top:-1px;bottom:-1px;width:4px;border-radius:var(--radius-lg) 0 0 var(--radius-lg);background:var(--status-claimed)}
.pin.st{border-color:var(--warning)}
.pin.editing{border-color:var(--primary)}
.pin.cur{box-shadow:0 0 0 2px var(--primary)}
.pin.flash{animation:pinflash 1.2s ease-in-out 1}
@keyframes pinflash{0%,100%{box-shadow:0 0 0 2px var(--primary)}50%{box-shadow:0 0 0 5px var(--primary)}}
.pin .n{color:var(--status-open);font-weight:700}
.pin .n.go{cursor:pointer;border-radius:var(--radius);padding:0 var(--space-1);margin:0 -4px}
.pin .n.go:hover,.pin .n.go:focus-visible{background:var(--accent);text-decoration:underline}
.pin .note{margin-top:4px;white-space:pre-wrap;word-break:break-word;cursor:text}
/* 카드 머리: 왼쪽에 번호·범위·쪽, 오른쪽에 작성자·접기. 배지는 머리 아래 한 줄. 동작은 같은 폭 격자, 완료만 강조·삭제는 위험 색. */
.pin .head{flex-wrap:nowrap;gap:var(--space-2);min-height:28px}
.pin .head .loc{white-space:nowrap}
.pin .head .au{flex:none}
.pin .tags{display:flex;flex-wrap:wrap;gap:var(--space-1);margin-top:4px}
.pin .tags:empty{display:none}
.pin .acts{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:var(--space-2);margin-top:8px}
.pin .acts button{min-width:0;padding-left:var(--space-1);padding-right:var(--space-1)}
button.b-close{font-weight:600}   /* [완료] = soft, [삭제] = destructive — 변형은 마크업의 클래스가 정한다 */
.e-acts{display:grid;grid-template-columns:1.4fr 1fr 1fr;gap:var(--space-2);margin-top:8px}
.edit .c-tools{margin-top:0}
.pg-link{color:var(--muted-foreground);font-size:var(--text-sm);cursor:pointer;text-decoration:underline dotted}
.au{display:inline-flex;align-items:center;gap:5px;font-size:var(--text-sm);color:var(--muted-foreground);max-width:150px}
.au .au-n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.au.old{font-style:italic}
.av{width:22px;height:22px;border-radius:50%;flex:none;object-fit:cover}
.av.i{display:inline-flex;align-items:center;justify-content:center;background:var(--primary);color:var(--primary-foreground);
  font-size:var(--text-xs);font-weight:700;font-style:normal}
.edit{margin-top:6px;border-top:1px dashed var(--border);padding-top:6px}
/* ---------------- 목록 구획(references/design.md §보관함): 열린 핀 · 완료 · 삭제. 구획 머리는 폭 전체를 쓰고 스크롤해도 위에
   붙는다(sticky) — 지금 어느 구획을 보는지 늘 보인다. 구획마다 section 으로 감싸 다음 구획이 오면 앞 머리가 밀려난다.
   --stick-top 은 compact 에서 위에 붙은 도구 줄(#bar1) 높이다(JS 가 잰다). 닫힌·삭제한 핀은 카드가 아니라 납작한 행이다. */
.lsec{position:relative}
.list-head{position:sticky;top:var(--stick-top,0px);z-index:2;background:var(--sidebar);margin:0 -12px 4px;padding:10px var(--space-3) 6px}
.arc{margin-top:12px}
button.arc-head{position:sticky;top:var(--stick-top,0px);z-index:2;display:flex;justify-content:flex-start;gap:var(--space-2);width:calc(100% + 24px);
  margin:0 -12px;padding:var(--space-2) var(--space-3);background:var(--sidebar);border:0;border-top:1px solid var(--border-strong);border-radius:0;color:var(--muted-foreground);
  font-size:var(--text-sm);text-align:left}
button.arc-head:hover{background:var(--accent)}
.arc-h{font-weight:700;color:var(--foreground)}
.arc-n,.dcnt{flex:none;justify-content:center;min-width:20px;padding:0 6px;border-radius:var(--radius-lg);line-height:18px}
.arc-rule{flex:1;height:1px;background:var(--border)}
.arc-fold{flex:none;display:inline-flex;align-items:center;gap:2px}
.arc-list{padding:6px 0 var(--space-1)}
.arc-list>.dim{padding:var(--space-1) var(--space-3)}
.arc-row{position:relative;padding:var(--space-1) var(--space-1) 6px 10px;border-left:3px solid var(--status-closed);color:var(--muted-foreground);font-size:var(--text-base);line-height:1.5}
.arc-row+.arc-row{margin-top:6px}
.arc-row.dropped{border-left-color:var(--status-dropped);color:var(--subtle-foreground)}
.arc-row .ic{width:14px;height:14px}
.arc-row.done .arc-l1>.ic{color:var(--status-closed)}
.arc-l1{display:flex;align-items:center;gap:6px;min-height:26px;white-space:nowrap}
.arc-l1 .n{font-weight:700}
.arc-l1 .loc{color:inherit;font-size:var(--text-sm)}
.arc-ref{flex:none;line-height:16px;padding:0 5px;border-color:var(--border);max-width:120px;overflow:hidden;text-overflow:ellipsis}
.arc-t{font-size:var(--text-xs);min-width:0;overflow:hidden;text-overflow:ellipsis}
button.arc-b{flex:none;color:var(--muted-foreground)}
button.arc-b:hover{color:var(--foreground)}
.arc-l2{display:flex;align-items:baseline;gap:var(--space-2)}
.arc-reply{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.arc-reply.open{white-space:pre-wrap;overflow:visible;word-break:break-word}
.arc-reply.none{font-style:italic;cursor:default}
button.arc-orig-t{flex:none;background:transparent;border-color:transparent;color:var(--muted-foreground);padding:0 2px;font-size:var(--text-sm);
  text-decoration:underline dotted;text-underline-offset:3px}
.arc-orig{margin:4px 0 0;padding:6px var(--space-2);border-radius:var(--radius);background:var(--card);border:1px solid var(--border);white-space:pre-wrap;word-break:break-word}
.arc-orig b{display:block;font-size:var(--text-xs);font-weight:600;margin-bottom:2px}
h3{margin:0 0 7px;font-size:var(--text-sm);color:var(--muted-foreground);text-transform:uppercase;letter-spacing:.06em}
.hint{padding:18px 10px;color:var(--muted-foreground);font-size:var(--text-base);text-align:center;line-height:1.85}
kbd{background:var(--muted);border:1px solid var(--border);border-radius:var(--radius-sm);padding:1px 5px;font-size:var(--text-xs)}
.spin{width:12px;height:12px;border:2px solid var(--border);border-top-color:var(--primary);border-radius:50%;
  animation:rot .8s linear infinite;display:inline-block}
@keyframes rot{to{transform:rotate(360deg)}}
#toasts{position:fixed;left:12px;bottom:12px;display:flex;flex-direction:column;gap:6px;z-index:50;max-width:min(480px,60vw)}
.toast{display:flex;align-items:center;gap:var(--space-2);background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border-strong);
  border-left:4px solid var(--success);border-radius:var(--radius);padding:7px var(--space-2) 7px 10px;box-shadow:var(--shadow);font-size:var(--text-base)}
.toast span{flex:1;min-width:0;overflow-wrap:anywhere}
.toast.warn{border-left-color:var(--warning)}
.toast.err{border-left-color:var(--destructive)}
#tip{position:fixed;z-index:100;max-width:300px;background:var(--tooltip);color:var(--tooltip-foreground);font-size:var(--text-sm);line-height:1.5;
  padding:6px 9px;border-radius:var(--radius);pointer-events:none;box-shadow:var(--shadow);left:0;top:0}
dialog{background:var(--popover);color:var(--popover-foreground);border:1px solid var(--border-strong);border-radius:var(--radius-lg);max-width:680px;
  width:92vw;padding:var(--space-4) 22px;max-height:88vh}
dialog::backdrop{background:var(--shadow-color)}
dialog h2{font-size:var(--text-xl);margin:0 0 8px}
dialog .help-steps{margin:0;padding-left:var(--space-5);font-size:var(--text-base)}
dialog .help-legend{font-size:var(--text-base)}
dialog .help-legend+.help-legend{margin-top:var(--space-1)}
dialog h4{margin:14px 0 4px;font-size:var(--text-base)}
dialog table{border-collapse:collapse;font-size:var(--text-base);width:100%}
dialog td{border-top:1px solid var(--border);padding:3px 6px;vertical-align:top}
dialog code{font-size:var(--text-sm);word-break:break-all}
.sw{display:inline-block;width:14px;height:10px;border:2px solid var(--status-open);vertical-align:middle;margin-right:4px}
.sw.w{border-color:var(--warning)}
.sw.a{border-color:var(--primary);border-style:dashed}
.strip{display:inline-block;width:4px;height:12px;border-radius:var(--radius-sm);vertical-align:middle;margin:0 4px 0 2px}
.strip.c{background:var(--status-claimed)} .strip.d{background:var(--status-closed)} .strip.x{background:var(--status-dropped)}
/* ---------------- 모바일·터치 (references/design.md §모바일 레이아웃)
   레이아웃은 JS 가 body 에 건다: lay-wide(지금 그대로) · lay-mid(700px 초과 1100px 미만 + 터치: 좁은 사이드 패널) ·
   lay-narrow(700px 이하: 하단 시트). compact = mid·narrow. side-open = 패널·시트가 펼쳐짐.
   접힌 상태에는 도구 줄(#bar1)과 상태 칩(#bar2)·위치 다시 잡기 배너만 남는다. */
.cmp,.tch{display:none}
.pin .sum{display:none}
.hint .t-touch{display:none}
.pg{-webkit-touch-callout:none}
#btn-select[aria-pressed=true]{background:var(--primary);color:var(--primary-foreground);border-color:var(--primary);font-weight:600}   /* 켜짐 = btn-default 모양 */
body.selmode .pg{touch-action:none;outline:2px dashed var(--primary);outline-offset:3px}
#coach{position:fixed;left:50%;transform:translateX(-50%);top:calc(10px + env(safe-area-inset-top));z-index:60;background:var(--primary);
  color:var(--primary-foreground);border-radius:var(--radius-lg);padding:6px 6px 6px 14px;display:flex;gap:var(--space-2);align-items:center;
  width:max-content;max-width:calc(100vw - 16px);font-size:var(--text-lg);box-shadow:var(--shadow-lg)}
#coach button{background:transparent;color:inherit;border-color:transparent}
body.lay-mid.side-open #coach{left:calc((100vw - var(--side-w,340px))/2);max-width:calc(100vw - var(--side-w,340px) - 16px)}
#more{max-width:440px}
#more .more-head{flex-wrap:nowrap;gap:var(--space-2);margin-bottom:var(--space-2)}
#more .more-head .chip{background:var(--brand);max-width:min(60%,240px)}
#more .more-info{font-size:var(--text-base);color:var(--muted-foreground);overflow-wrap:anywhere;margin:0 0 10px}
#more .more-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--space-2)}
#more .more-grid .wide{grid-column:1/-1}
#more .jump-row{display:flex;gap:var(--space-2)}
#more .jump-row input{flex:1;min-width:0}
#more .size-row{display:flex;align-items:center;gap:var(--space-2)}
#more .size-row .seg{flex:1;margin:0}
@media (pointer:coarse){
  button.tch{display:inline-flex}
  .hint .t-touch{display:inline}
  .hint .t-mouse{display:none}
  button{min-height:44px;min-width:44px;padding:var(--space-2) var(--space-3);font-size:var(--text-lg);-webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
  button.btn-sm,.seg button{min-height:44px;padding:6px 10px;font-size:var(--text-base)}
  button.badge{min-height:44px;padding:var(--space-1) 10px}
  #bar1{flex-wrap:wrap;--tb-h:var(--control-h-touch)}
  #bar1 button{padding:0 10px}
  input,textarea,select{font-size:var(--text-xl)}
  #bar1 input.n{width:52px;font-size:var(--text-xl)}   /* iOS 는 16px 보다 작은 입력 칸에 포커스하면 화면을 키운다 */
  .loc,.pg-link,.pin .n.go{display:inline-flex;align-items:center;min-height:44px}
  .mark b{width:26px;height:26px;left:-28px;font-size:var(--text-base)}
  .mark b::after{content:'';position:absolute;inset:-9px}
  #tip{max-width:min(300px,calc(100vw - 16px))}
  button.btn-icon,.step button{width:var(--control-h-touch);min-width:var(--control-h-touch)}
  #c-actions button{min-height:48px;font-size:var(--text-lg)}
  .pin .acts button{min-height:44px}
  /* 보관함 행을 납작하게 두려고 [원래 요청]은 28px 로 그리고 누르는 자리만 ::after 로 44px 까지 넓힌다 */
  button.arc-orig-t{min-height:28px;min-width:0;padding:0 var(--space-1);position:relative;font-size:var(--text-base)}
  button.arc-orig-t::after{content:'';position:absolute;left:-4px;right:-4px;top:-8px;bottom:-8px}
  #grip::after{left:-9px;right:-9px}
}
body.lay-narrow #grip,body.lay-mid:not(.side-open) #grip{display:none}
/* mid: 손잡이 가운데에 잡는 막대를 보인다(터치로 찾기 쉽게) */
body.lay-mid #grip{width:8px;background:var(--sidebar);border-left:1px solid var(--border)}
body.lay-mid #grip::before{content:'';position:absolute;left:50%;top:50%;width:4px;height:44px;border-radius:var(--radius-sm);
  background:var(--border-strong);transform:translate(-50%,-50%)}
body.lay-mid #grip.on::before{background:var(--primary)}
body.compact button.cmp{display:inline-flex}
body.compact .sec{display:none}
body.compact #left{padding:12px max(10px,env(safe-area-inset-right)) 60vh max(30px,env(safe-area-inset-left));min-width:0}
body.compact #main{min-width:0}
body.compact #right{overflow-y:auto;overscroll-behavior:contain;min-width:0;max-width:none}
body.compact #right>*{flex:none}
/* compact 도구 줄: 같은 높이의 한 줄 그룹. 빈칸 없이 이어 붙이고 [⋯] 도 그 흐름에 둔다(폭이 모자라면 글자가 먼저 줄어든다). */
body.compact #bar1{flex-wrap:nowrap;gap:var(--space-1);padding:var(--space-2) var(--space-3);position:sticky;top:0;z-index:3;background:var(--sidebar)}
body.compact #bar1 .sp{display:none}
body.compact #bar1 button{flex:1 1 auto;min-width:0;padding:0 var(--space-2);overflow:hidden;text-overflow:ellipsis;font-size:var(--text-base)}
/* 폭이 모자라면 이름표가 먼저 줄어든다(전체 이름은 설명에) — 버튼 글자가 잘려 'DF 재빌드'처럼 보이던 것을 막는다 */
body.compact #bar1 .chip{flex:0 50 auto;min-width:28px}
/* 접은 폴드(narrow): 이름표 글자는 도구 줄에서 빼고 [더보기] 첫 줄에 둔다 — 28px 로 줄어 'C…' 만 남아 읽을 수 없었다(2026-09-23).
   맨 위 이름표 색 띠(#brand-stripe)가 인스턴스를 가른다. [문서] 버튼은 짧은 문서 이름(본문·답변서·커버레터)을 다 보이고 줄어들지 않는다. */
body.lay-narrow #bar1 .chip{display:none}
body.lay-narrow #bar1 #btn-doc{flex:none;overflow:visible}
body.lay-narrow #btn-doc .nm{overflow:visible;text-overflow:clip;max-width:6em}
body.compact #bar1 #btn-more{flex:0 0 44px;padding:0}
body.compact #composer{max-height:none;overflow:visible}
/* narrow 시트: 메모 칸을 원문보다 위로 올린다 — 시트 높이 안에서 메모 칸이 아래 동작 줄 밑에 숨었다(실측, 모바일 개선 때). */
body.lay-narrow #composer{display:flex;flex-direction:column}
body.lay-narrow #c-body{display:contents}
body.lay-narrow #c-snip,body.lay-narrow .snip-foot{order:2}
body.lay-narrow #note{order:1;margin:0 0 8px}
body.compact #list{overflow:visible;padding-bottom:calc(20px + env(safe-area-inset-bottom))}
/* compact 에서는 #right 가 스크롤 상자다 — 동작 줄을 그 바닥에 붙인다. */
body.compact #c-actions{position:sticky;bottom:0;padding:8px 12px calc(8px + env(safe-area-inset-bottom))}
body.compact #meta-txt,body.compact #me{display:none}
body.compact #bar2:not(:has(.badge:not([hidden]))){display:none}
body.compact:not(.side-open) #right>:not(#bar1):not(#bar2):not(#banner):not(#sheet-grip){display:none}
body.compact:not(.side-open) #bar1{order:3;border-bottom:0}
/* 알림: narrow 는 시트·아래 도구 줄과 겹치지 않게 위로, mid 는 패널 도구 줄을 가리지 않게 본문 쪽 왼쪽 아래로. */
body.lay-narrow #toasts{left:8px;right:8px;top:calc(8px + env(safe-area-inset-top));bottom:auto;max-width:none}
body.lay-mid #toasts{left:max(12px,env(safe-area-inset-left));bottom:calc(12px + var(--kb,0px) + env(safe-area-inset-bottom));max-width:calc(100vw - var(--side-w,360px) - 40px)}
body.compact .pin .sum{display:block;flex:1 1 0;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--muted-foreground);cursor:pointer}
body.compact .pin .head{flex-wrap:nowrap}
body.compact .pin.open .sum,body.compact .pin.editing .sum{display:none}
body.compact .pin:not(.open):not(.editing) :is(.tags,.au,.note,.acts,.head>.sp){display:none}
body.compact .pin .au .au-n{display:none}
body.lay-narrow{display:block}
body.lay-narrow #main{height:100%}
body.lay-narrow #left{height:100%}
body.lay-narrow #right{position:fixed;left:0;right:0;bottom:var(--kb,0px);width:auto!important;height:auto;
  max-height:calc(var(--vvh,100dvh) - 48px);border-left:0;border-top:1px solid var(--border-strong);border-radius:var(--radius-lg) var(--radius-lg) 0 0;
  box-shadow:0 -6px 24px var(--shadow-color);z-index:20;padding:0 env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left)}
/* 시트 높이: --sheet-f(화면 높이 비율, 기본 0.64)를 윗가장자리 손잡이(#sheet-grip)로 끌거나 눌러 바꾼다. 키보드가 올라오면 보이는 높이 안으로 줄인다. */
body.lay-narrow.side-open #right{height:min(calc(var(--sheet-f,.64) * 100dvh),calc(var(--vvh,100dvh) - 48px))}
body.lay-narrow #sheet-grip{display:flex;align-items:center;justify-content:center;height:24px;flex:none;position:sticky;top:0;z-index:4;
  background:var(--sidebar);border-radius:var(--radius-lg) var(--radius-lg) 0 0;touch-action:none;cursor:row-resize}
body.lay-narrow #sheet-grip::before{content:'';width:40px;height:4px;border-radius:var(--radius-sm);background:var(--border-strong)}
body.lay-narrow #sheet-grip::after{content:'';position:absolute;left:0;right:0;top:0;bottom:-8px}
body.lay-narrow #sheet-grip.on::before{background:var(--primary)}
body.lay-narrow #bar1{top:24px;padding-top:0}
body.lay-mid.side-open #right{width:var(--side-w,clamp(300px,38vw,360px))!important}
body.lay-mid:not(.side-open) #right{position:fixed;right:max(12px,env(safe-area-inset-right));
  bottom:calc(12px + var(--kb,0px) + env(safe-area-inset-bottom));width:auto!important;height:auto;max-width:calc(100vw - 24px);
  border:1px solid var(--border-strong);border-radius:var(--radius-lg);box-shadow:var(--shadow-lg);z-index:20;overflow:hidden}
body.lay-mid:not(.side-open) #bar1{border-radius:var(--radius-lg)}
/* 문서 탭(§여러 문서, references/design.md §여러 문서): PDF 영역 위 한 줄. 문서가 하나면 숨긴다(지금 화면 그대로).
   지금 탭은 PDF 영역과 같은 바탕(--bg)으로 이어 붙이고 위에 이름표 색 띠를 둔다. 넘치면 가로로 스크롤한다.
   접은 폴드(narrow)는 탭 줄 대신 도구 줄의 [문서 ▾] 버튼 → 아래 시트 목록이다. */
#doc-tabs{display:none;flex:none;gap:2px;align-items:flex-end;overflow-x:auto;overflow-y:hidden;padding:6px var(--space-3) 0 36px;
  background:var(--sidebar);border-bottom:1px solid var(--border);scrollbar-width:none;overscroll-behavior-x:contain}
#doc-tabs::-webkit-scrollbar{display:none}
body.docs-multi:not(.lay-narrow) #doc-tabs{display:flex}
.dtab{flex:none;display:inline-flex;align-items:center;gap:6px;max-width:260px;margin-bottom:-1px;padding:6px var(--space-3);
  background:transparent;border:1px solid transparent;border-bottom:0;border-radius:var(--radius-lg) var(--radius-lg) 0 0;color:var(--muted-foreground);font-size:var(--text-base)}
.dtab:hover{background:var(--accent);color:var(--foreground)}
.dtab[aria-selected=true]{background:var(--background);border-color:var(--border);color:var(--foreground);font-weight:600;box-shadow:inset 0 3px 0 var(--brand)}
.dtab .nm,.dm-item .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dcnt{font-weight:600}
.dcnt.z{color:var(--muted-foreground);font-weight:400;background:transparent;border-color:var(--border)}
.dtab[aria-selected=true] .dcnt:not(.z),.dm-item.on .dcnt:not(.z){background:var(--brand);color:var(--brand-foreground)}
.dvo{flex:none;line-height:14px;padding:0 var(--space-1);letter-spacing:.02em}
.ddot{flex:none;width:7px;height:7px;border-radius:50%;background:var(--warning)}
.dtab .spin,.dm-item .spin,#btn-doc .spin{width:10px;height:10px}
#btn-doc{display:none;align-items:center;gap:var(--space-1)}
#btn-doc .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
body.lay-narrow.docs-multi #btn-doc{display:inline-flex}
body.view-only #btn-rebuild{display:none}
.dchip{flex:none;line-height:16px;border-color:var(--border);max-width:110px;overflow:hidden;text-overflow:ellipsis}
.dchip.other{border-style:dashed}
.list-head{display:flex;align-items:center;gap:var(--space-2);margin:0 0 7px}
.list-head h3{margin:0}
#docs-menu{margin:auto auto 0;width:100%;max-width:560px;border-radius:var(--radius-lg) var(--radius-lg) 0 0;padding:10px 12px calc(12px + env(safe-area-inset-bottom))}
#docs-menu .dm-list{display:flex;flex-direction:column;gap:6px;margin-top:6px}
.dm-item{display:flex;align-items:center;gap:10px;width:100%;text-align:left;padding:10px var(--space-3)}
.dm-item .tx{flex:1;min-width:0;display:flex;flex-direction:column}
.dm-item .ph{font-size:var(--text-sm);color:var(--muted-foreground);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dm-item.on{border-color:var(--brand);box-shadow:inset 3px 0 0 var(--brand)}
/* 보기 전용 PDF 문서의 선택: 범위 사다리·스테퍼·원문 펼치기가 없다(줄이 없다). 원문 칸에는 영역 글자를 보인다. */
#composer.region #c-levels,#composer.region .c-tools,#composer.region .snip-foot,#composer.region #c-copy{display:none}
.edit.region .e-levels,.edit.region .c-tools .step{display:none}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}
/* 이름표 칩·띠(§동시 인스턴스): 여러 논문 뷰어를 동시에 열었을 때 탭을 구분하는 용도라 강조색은
   고정 배경(인라인 style)으로 박는다 — 테마가 바뀌어도 이름표 색은 그대로여야 한다. */
#brand-stripe{position:fixed;top:0;left:0;right:0;height:4px;z-index:50;pointer-events:none}
.chip{flex:none;color:var(--brand-foreground);font-weight:700;font-size:var(--text-sm);line-height:1.4;padding:3px var(--space-2);border-radius:var(--radius);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px}
@media (max-width:480px){.chip{max-width:64px;font-size:var(--text-xs);padding:2px 6px}}
</style></head><body>
<div id="brand-stripe" style="background:__ACCENT__"></div>
<div id="main"><div id="doc-tabs" role="tablist" aria-label="문서" aria-orientation="horizontal"></div><div id="left"><div id="doc"></div></div></div>
<div id="toasts" role="status" aria-live="polite"></div>
<div id="grip" role="separator" aria-orientation="vertical" aria-controls="right" aria-label="패널 폭" tabindex="0" data-tip="끌어서 패널 폭을 바꿉니다. 탭(마우스는 두 번 클릭)하면 좁게 → 보통 → 넓게 순으로 바뀝니다. ←/→ 키로도 바뀝니다"></div>
<div id="right">
  <div id="sheet-grip" role="separator" aria-orientation="horizontal" aria-controls="right" aria-label="시트 높이" tabindex="0" data-tip="끌어서 시트 높이를 바꿉니다. 탭하면 낮게 → 보통 → 높게 순으로 바뀌고, 끝까지 내리면 접힙니다"></div>
  <div class="bar" id="bar1" role="toolbar" aria-label="도구">
    <span id="brand-chip" class="chip" style="background:__ACCENT__" data-tip="__LABEL__ — 이 창이 다루는 논문. 여러 뷰어를 동시에 열었을 때 구분용">__LABEL__</span>
    <button id="btn-doc" data-act="doc-menu" aria-haspopup="dialog" aria-label="문서 바꾸기" data-tip="이 논문의 다른 문서(답변서·커버레터 등)로 바꿉니다"><span class="nm" id="btn-doc-n">문서</span><span id="btn-doc-dot" class="ddot" hidden></span>{{ic:chevron-down}}</button>
    <button id="btn-side" class="cmp" data-act="side" aria-controls="right" aria-expanded="false" data-tip="핀 목록과 선택한 자리 패널을 펴고 접습니다">핀 <b id="side-n">0</b><span id="side-arrow" aria-hidden="true">{{ic:chevron-up}}</span></button>
    <button id="btn-select" class="tch" data-act="selmode" aria-pressed="false" data-tip="켜면 PDF 위를 끌어서 영역을 고르고, 탭하면 그 자리 문단을 고릅니다. 끄면 보통처럼 스크롤·확대됩니다">선택</button>
    <button id="btn-rebuild" data-act="rebuild" data-tip="지금 원고(.tex)로 PDF를 새로 컴파일해 화면을 바꿉니다. 에이전트가 원고를 고친 뒤 결과를 볼 때 누르세요. 30초~1분쯤 걸리며, 끝나면 보던 자리 그대로 화면만 바뀝니다. 원본 폴더는 건드리지 않고 사본에서 빌드합니다.">PDF 재빌드</button>
    <span class="sp"></span>
    <input class="n sec" id="jump" placeholder="쪽" inputmode="numeric" aria-label="쪽 번호로 이동" data-tip="쪽 번호를 넣고 Enter">
    <button id="btn-zoom-out" class="sec btn-icon" data-act="zoom-out" aria-label="축소" data-tip="PDF 쪽만 축소합니다 (Ctrl/⌘ −, PDF 위에서 Ctrl/⌘+휠). 패널은 그대로입니다">{{ic:minus}}</button>
    <button id="btn-zoom-in" class="sec btn-icon" data-act="zoom-in" aria-label="확대" data-tip="PDF 쪽만 확대합니다 (Ctrl/⌘ +, PDF 위에서 Ctrl/⌘+휠·트랙패드 핀치). 패널은 그대로입니다">{{ic:plus}}</button>
    <button id="btn-fit" class="sec" data-act="fit" aria-label="폭 맞춤" data-tip="PDF 쪽 폭을 왼쪽 화면 폭에 맞춥니다 (Ctrl/⌘ 0)">폭</button>
    <button id="btn-theme" class="sec btn-icon" data-act="theme" aria-label="화면 테마: 시스템" data-tip="화면 테마: 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다">{{ic:sun-moon}}</button>
    <button id="btn-help" class="sec btn-icon" data-act="help" aria-label="도움말" data-tip="사용법·단축키·용어 설명, pins.md 위치 (?)">{{ic:circle-question-mark}}</button>
    <button id="btn-more" class="cmp btn-icon" data-act="more" aria-label="더보기" aria-haspopup="dialog" data-tip="핀 다시 읽기·쪽 이동·확대·테마·닫힌 핀·삭제한 핀·도움말">{{ic:ellipsis}}</button>
  </div>
  <div class="bar" id="bar2"><span id="meta" class="dim"><span id="meta-txt"><span id="meta-main" data-tip="PDF를 만든 최상위 원고 파일"></span> · <span id="meta-pages" data-tip="지금 화면에 있는 PDF의 쪽 수"></span> · <span id="meta-head" data-tip="PDF를 만들 때의 원고 Git 커밋. 그 뒤의 커밋이나 저장된 수정은 이 PDF에 없습니다"></span> · <span id="meta-built" data-tip="PDF를 마지막으로 만든 시각"></span></span> <span id="meta-stale" class="badge badge-warning" hidden data-tip="이 PDF를 만든 뒤에 원고(.tex)가 바뀌었습니다. 지금 화면에서 고른 자리는 원문과 어긋날 수 있으니 [PDF 재빌드]를 누르세요">원고가 더 새롭습니다</span> <span id="build-chip" class="badge" hidden data-tip="지금 다른 사람(또는 나)이 PDF를 재빌드하는 중입니다"></span></span><span class="sp"></span>
    <span id="vec-chip" class="badge badge-warning" hidden data-tip="PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다. 확대하면 흐릴 수 있습니다">PNG 보기</span>
    <span id="conn-lost" class="badge badge-warning" hidden data-tip="자동 동기화가 서버에 두 번 연속 닿지 못했습니다. 연결이 끊겼을 수 있습니다">연결 끊김</span>
    <button id="build-err-chip" class="badge badge-warning" hidden data-act="build-err-reopen" data-tip="마지막 빌드에 오류가 있었습니다 — 눌러서 다시 봅니다">빌드 오류 · 다시 보기</button>
    <span id="me" class="au" data-tip="지금 이 화면을 쓰는 사람. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다"></span></div>
  <div id="build-err" hidden></div>
  <div id="banner" hidden></div>
  <div id="composer" hidden role="region" aria-label="선택한 자리">
    <div id="c-err" class="errline" hidden></div>
    <div id="c-body">
      <div class="c-loc-row">
        <div class="c-loc-main"><span id="c-loc" class="loc" tabindex="0" data-tip="핀에 저장될 원문 위치입니다. 에이전트는 이 줄을 직접 열어 고칩니다. 누르면 복사"></span>
          <span id="c-page"></span><span id="c-tag" class="badge" hidden data-tip="원문 줄을 찾은 방법과 일치율"></span><span id="c-spin" class="spin" hidden aria-label="찾는 중"></span></div>
        <button class="btn-icon" id="c-copy" data-act="copy-cur" aria-label="위치 복사" data-tip="'파일 L시작-L끝'을 복사합니다. 채팅창에 붙이면 에이전트가 바로 그 줄을 엽니다">{{ic:copy}}</button>
      </div>
      <div id="c-warn" class="warnline" hidden></div>
      <div id="c-overlap" hidden></div>
      <div id="c-levels" class="seg" role="group" aria-label="범위 단계"></div>
      <div class="c-tools">
        <div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">
          <span class="sl" aria-hidden="true">위</span><button id="c-up-grow" data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">{{ic:plus}}</button><button id="c-up-shrink" data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">{{ic:minus}}</button><span class="sl" aria-hidden="true">아래</span><button id="c-down-grow" data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">{{ic:plus}}</button><button id="c-down-shrink" data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">{{ic:minus}}</button>
        </div>
        <span class="sp"></span>
        <button class="tg" id="c-wrap" data-act="wrap" aria-pressed="true" data-tip="긴 줄을 패널 폭에 맞춰 접어 봅니다. 문단 하나가 한 줄인 원고라면 켜 두세요">줄바꿈</button>
      </div>
      <pre id="c-snip" class="wrap"></pre>
      <div class="snip-foot"><button class="btn-sm btn-ghost" id="c-expand" data-act="expand" data-tip="접어 둔 원문 줄을 모두 보여 줍니다" hidden>원문 펼치기</button></div>
    </div>
    <textarea id="note" rows="3" placeholder="메모: 여기를 어떻게 고칠지 (비워도 됩니다)" aria-label="메모" data-tip="여기를 어떻게 고칠지 적습니다. 다른 곳을 다시 드래그해도 지워지지 않습니다"></textarea>
  </div>
  <div id="list">
    <div id="empty" class="hint" hidden><span class="t-mouse">PDF 위에서 <b>드래그</b>해 영역을 고르면</span><span class="t-touch">PDF를 <b>길게 누르면</b> 그 문단을, <b>[선택]</b>을 켜고 끌면 그 영역을 고르고</span> 그 자리의 <b>.tex 줄 번호</b>를 찾아 줍니다.<br>
      범위를 고르고 메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.<br><span class="t-mouse"><kbd>?</kbd> 를 누르면 도움말.</span><span class="t-touch">도움말은 [더보기]에 있습니다.</span></div>
    <section class="lsec" id="sec-open" aria-labelledby="list-h">
      <div class="list-head"><h3 id="list-h">열린 핀</h3><span class="sp"></span><button id="btn-reload" class="sec btn-sm" data-act="reload" aria-label="핀 다시 읽기" data-tip="핀 파일을 다시 읽어 목록을 맞춥니다. 에이전트가 완료한 핀이 빠지고, 원고 수정으로 밀린 줄 번호가 다시 맞춰집니다. PDF는 바뀌지 않습니다.">다시 읽기</button><button class="btn-sm tg" id="all-docs" data-act="all-docs" aria-pressed="false" hidden data-tip="다른 문서의 열린 핀도 함께 봅니다. 카드에 문서 이름이 붙고, #번호·[보기]를 누르면 그 문서로 바꿔 그 자리로 갑니다">모든 문서</button></div>
      <div id="pins"></div>
    </section>
    <section class="lsec arc" id="sec-done" aria-label="완료한 핀" hidden>
      <button class="arc-head" id="done-toggle" data-act="done-toggle" aria-expanded="false" aria-controls="done-list" data-tip="완료한 핀을 펼치고 접습니다. 에이전트가 닫은 핀도 여기에 있습니다"></button>
      <div id="done-list" class="arc-list" hidden></div>
    </section>
    <section class="lsec arc" id="sec-dropped" aria-label="삭제한 핀" hidden>
      <button class="arc-head" id="dropped-toggle" data-act="dropped-toggle" aria-expanded="false" aria-controls="dropped-list" data-tip="삭제한 핀을 펼치고 접습니다. 되살리기로 같은 번호 그대로 복구합니다"></button>
      <div id="dropped-list" class="arc-list" hidden></div>
    </section>
  </div>
  <div id="c-actions">
    <button id="btn-cancel" data-act="cancel" data-tip="이 선택을 버립니다 (Esc)">취소</button>
    <button class="btn-default" id="btn-save" data-act="save" data-tip="메모와 위치를 핀으로 저장해 pins.md에 올립니다. 에이전트는 이 파일을 읽고 작업합니다 (⌘ Enter / Ctrl+Enter)">핀 저장</button>
  </div>
</div>
<div id="tip" role="tooltip" hidden></div>
<div id="coach" role="status" hidden><span id="coach-t"></span><button class="btn-icon btn-ghost" data-act="coach-close" aria-label="안내 닫기">{{ic:x}}</button></div>
<dialog id="more" aria-label="더보기 · __LABEL__">
  <div class="row more-head"><span id="more-label" class="chip" data-tip="__LABEL__ — 이 창이 다루는 논문. 여러 뷰어를 동시에 열었을 때 구분용">__LABEL__</span><h2 style="margin:0">더보기</h2><span class="sp"></span><button class="btn-sm" data-act="more-close">닫기</button></div>
  <p class="more-info" id="more-info"></p>
  <div class="more-grid">
    <button data-act="reload" data-close="1">핀 다시 읽기</button>
    <button id="m-theme" data-act="theme">테마: 시스템</button>
    <button data-act="zoom-out">축소</button>
    <button data-act="zoom-in">확대</button>
    <button class="wide" data-act="fit" data-close="1">폭 맞춤</button>
    <div class="size-row wide"><span class="dim" id="m-size-l">패널 폭</span><div class="seg" id="m-size" role="group" aria-label="패널 폭"></div></div>
    <div class="jump-row wide"><input id="m-jump" inputmode="numeric" placeholder="쪽" aria-label="쪽 번호로 이동"><button data-act="m-jump">이동</button></div>
    <button id="m-done" data-act="done-toggle" data-close="1">닫힌 핀 0</button>
    <button id="m-dropped" data-act="dropped-toggle" data-close="1">삭제한 핀 0</button>
    <button class="wide" data-act="help">도움말</button>
  </div>
</dialog>
<dialog id="docs-menu" aria-labelledby="docs-menu-h">
  <div class="row"><h2 id="docs-menu-h" style="margin:0">문서</h2><span class="sp"></span><button class="btn-sm" data-act="docs-menu-close">닫기</button></div>
  <div class="dm-list" id="docs-menu-list" role="listbox" aria-labelledby="docs-menu-h"></div>
</dialog>
<dialog id="help" aria-labelledby="help-h">
  <div class="row"><h2 id="help-h">원고 핀 — 사용법</h2><span class="sp"></span><button class="btn-sm" data-act="help-close" data-tip="도움말 닫기 (Esc)">닫기</button></div>
  <h4>한 바퀴</h4>
  <ol class="help-steps">
    <li>PDF 위에서 고칠 곳을 <b>드래그</b>합니다. 점선 상자('새 핀')가 남습니다.</li>
    <li>사이드바의 <b>범위 단계</b>(드래그한 줄 / 문단 / 환경)와 한 줄 버튼(위·아래 +/−)으로 줄 범위를 맞춥니다.</li>
    <li>메모를 쓰고 <b>핀 저장</b>(⌘ Enter / Ctrl+Enter). 알림의 [되돌리기]로 바로 취소할 수 있습니다.</li>
    <li>에이전트에게 "핀 처리해줘"라고 말합니다. 에이전트는 pins.md 한 장을 읽고 원고를 고친 뒤 핀을 닫습니다.</li>
    <li><b>PDF 재빌드</b>로 결과를 봅니다. 보던 쪽과 쓰던 메모는 그대로 남습니다.</li>
  </ol>
  <h4>휴대폰·태블릿(터치)</h4>
  <table><tr><td><kbd>길게 누르기</kbd></td><td>PDF 위를 길게 누르면 그 자리 문단을 고릅니다. 스크롤·확대는 평소처럼 됩니다</td></tr>
    <tr><td><kbd>선택</kbd></td><td>켜면 한 손가락으로 끌어 영역을 고르고, 탭하면 그 자리 문단을 고릅니다. 두 손가락으로 벌리면 PDF 만 커집니다. 핀을 저장하거나 취소하면 저절로 꺼집니다</td></tr>
    <tr><td><kbd>핀 N</kbd></td><td>핀 목록 패널(좁은 화면에서는 아래 시트)을 펴고 접습니다. 카드를 누르면 펼쳐집니다</td></tr>
    <tr><td><kbd>더보기</kbd></td><td>핀 다시 읽기·쪽 이동·확대·테마·닫힌 핀·삭제한 핀·이 도움말</td></tr>
    <tr><td>패널 폭·시트 높이</td><td>패널 왼쪽 가장자리(아래 시트는 윗가장자리) 손잡이를 끌면 바뀌고, 탭하면 단계가 돌아갑니다. [더보기] → 패널 폭 / 시트 높이에서도 고릅니다. 시트는 끝까지 내리면 접힙니다</td></tr>
    <tr><td>설명 보기</td><td>버튼을 길게 누르면 설명이 뜹니다</td></tr></table>
  <h4>단축키</h4>
  <table><tr><td><kbd>드래그</kbd></td><td>영역을 골라 원문 위치를 찾습니다</td></tr>
    <tr><td><kbd>⌘ Enter</kbd> / <kbd>Ctrl+Enter</kbd></td><td>메모 칸에서 핀 저장, 편집 칸에서 수정 저장 (한글 조합 중에는 무시)</td></tr>
    <tr><td><kbd>Esc</kbd></td><td>열린 것부터 닫습니다: 도움말 → 툴팁 → 위치 다시 잡기 → 편집 취소 → 선택 취소</td></tr>
    <tr><td><kbd>Ctrl/⌘ + 휠</kbd> · <kbd>Ctrl/⌘ + = − 0</kbd></td><td>PDF 위에서 확대·축소(포인터 자리 기준), 0 은 폭 맞춤. 트랙패드 핀치도 같습니다. PDF 만 커지고 패널은 그대로입니다 (입력 칸 밖에서)</td></tr>
    <tr><td><kbd>?</kbd></td><td>이 도움말 (입력 칸 밖에서)</td></tr>
    <tr><td><kbd>Ctrl+PgUp</kbd>/<kbd>PgDn</kbd> · <kbd>Alt+1…9</kbd></td><td>문서 전환(문서가 여럿일 때, 입력 칸 밖에서). 브라우저가 이 키를 먼저 가져가면 PDF 위 문서 탭을 누르세요. 문서마다 보던 자리·확대를 기억합니다</td></tr>
    <tr><td>폭 손잡이</td><td>본문과 패널 사이 막대를 끌면 패널 폭이 바뀝니다. 두 번 클릭하면 좁게 → 보통 → 넓게, 포커스한 뒤 ←/→ 로도 바뀝니다. 폭은 브라우저에 기억됩니다</td></tr></table>
  <h4>용어</h4>
  <table>
    <tr><td>핀</td><td>원문 위치(파일·줄 범위)에 붙인 수정 요청 메모. 번호(#N)는 다시 쓰이지 않습니다</td></tr>
    <tr><td>앵커</td><td>핀을 찍을 때 떠 둔 첫·끝 문장. 원고가 고쳐지면 이것으로 새 줄 번호를 찾습니다</td></tr>
    <tr><td>줄 이동</td><td>원고 수정으로 핀 위치가 밀려 다시 맞췄다는 표시('줄 +3 이동')</td></tr>
    <tr><td>위치 잃음</td><td>첫 문장이 바뀌거나 지워져 위치를 되찾지 못함. [수정] → 위치 다시 잡기로 고칩니다</td></tr>
    <tr><td>위치 불확실</td><td>드래그한 글자가 찾은 줄 범위에 90%보다 적게 들어 있을 때 붙는 배지입니다(90% 이상이면 배지가 없습니다). 30% 미만이면 노란색. 설명에 찾은 방법(좌표·글자)과 일치율이 있습니다 — 원문 칸에서 고칠 곳이 그 줄들에 있는지 확인하세요</td></tr>
    <tr><td>#N 범위 안 · #N과 같은 범위 · #N과 일부 겹침</td><td>다른 열린 핀과 줄 범위가 겹친다는 배지. 앞의 둘은 한 번에 고치고 함께 닫는 편이 낫고, 일부 겹침은 참고만 합니다</td></tr>
    <tr><td>작성자</td><td>tailscale 로 들어온 사람은 계정 이름으로, 로컬·에이전트 요청은 '로컬/에이전트'로 기록됩니다. 기록이 생기기 전 핀은 '기록 전'</td></tr>
    <tr><td>PDF 재빌드 vs 핀 다시 읽기</td><td>앞의 것은 원고를 컴파일해 화면을 바꾸고(수십 초), 뒤의 것(구 '새로고침')은 핀 목록만 다시 읽습니다(즉시)</td></tr>
  </table>
  <h4>색</h4>
  <div class="help-legend"><span class="sw"></span>열린 핀 · <span class="sw w"></span>위치 잃음 · <span class="sw a"></span>저장 전 선택</div>
  <div class="help-legend">핀 목록 왼쪽 띠: <span class="strip c"></span>처리 중 · <span class="strip d"></span>완료 · <span class="strip x"></span>삭제 (띠가 없으면 열린 핀)</div>
  <h4>pins.md 위치</h4>
  <code id="help-pins-md"></code>
</dialog>
<script>
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
// Lucide 아이콘(vendor/lucide/README.md). 서버 icon_svg() 와 같은 모양 — 크기는 CSS(.ic)가 정한다.
const ICONS=__LUCIDE_JSON__;
function ic(n){const b=ICONS[n]; return b?'<svg class="ic ic-'+n+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+b+'</svg>':'';}
const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IS_MAC=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
const SMOOTH=matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
const MQ=matchMedia('(prefers-color-scheme: light)');
let META=null,PINS=[],DONE=[],DROPPED=[],CUR=null,SAVING=false,ESAVING=false,EDIT=null,REPICK=null,PICKSEQ=0,PENDING=null;
let SHOW_DONE=false,SHOW_DROPPED=false,SNIP_OPEN=false,W=900,WRAP=true;
// 모바일: LAYOUT 은 'wide'|'mid'|'narrow', SIDE_OPEN 은 패널·시트가 펼쳐졌는가, SELMODE 는 터치 선택 모드,
// ZOOMED 는 compact 에서 사용자가 −/＋ 로 폭을 바꿨는가(그동안은 화면 폭에 자동으로 맞추지 않는다).
const MQ_COARSE=matchMedia('(pointer:coarse)');
let LAYOUT=null,SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // compact 에서 펼친 핀 카드 id
// 여러 문서(§여러 문서, references/design.md §여러 문서): DOCS = /api/docs 목록, DOC = 지금 문서 키, DEFAULT_DOC = doc 필드가
// 없는 옛 핀이 속하는 첫 문서. OPEN_ALL = 모든 문서의 열린 핀(PINS 는 그중 지금 문서의 것 — 마크·겹침·편집은 PINS 만 본다).
// META_BY = 문서별 meta 캐시(탭 전환을 즉시), VIEW_BY = 문서별 보던 자리·확대, BUILD_ERR_BY = 문서별 마지막 빌드 오류,
// DOC_SEQ = 다른 문서의 끝난 빌드 수(배경에서 끝난 빌드를 알린다).
let DOCS=[],DOC=null,DEFAULT_DOC='main',OPEN_ALL=[],DONE_ALL=[],SHOW_ALL=false,SWITCHSEQ=0;
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // reload 여부를 밖에서 확인하는 마커

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n:"누르면 PDF에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc:'핀이 가리키는 원문 줄. 클릭하면 복사',
  view:'PDF에서 이 핀 자리로 가서 깜빡입니다', edit:'메모와 범위를 고칩니다. 번호는 그대로입니다',
  close:"처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop:'잘못 찍은 핀을 지웁니다. 알림의 [되돌리기]로 같은 번호 그대로 되살릴 수 있습니다',
  repick:'번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave:'수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)', ecancel:'수정을 버립니다 (Esc)',
  reopen:'닫힌 핀을 다시 열어 목록과 pins.md에 올립니다',
  restore:'삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  synctex:'PDF 좌표(SyncTeX)로 줄을 찾았지만 드래그한 글자가 이 줄 범위에 다 있지는 않습니다(드문 낱말에 가중한 비율). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  text:'드래그한 글자를 원문에서 직접 찾아 위치를 정했습니다(표·기호표처럼 좌표 조회가 약한 곳). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다'
};

// ------------------------------------------------ 설정(병합 저장)
function prefs(){try{const p=JSON.parse(localStorage.getItem('pinPrefs')||'{}');return p&&typeof p==='object'?p:{};}catch(e){return {};}}
function savePrefs(patch){try{localStorage.setItem('pinPrefs',JSON.stringify(Object.assign(prefs(),patch)));}catch(e){}}
(function(){const p=prefs(); if(p.side)$('#right').style.width=p.side+'px'; if(p.w)W=p.w; if(p.wrap!==undefined)WRAP=!!p.wrap;})();

const THEMES=['system','light','dark'],THEME_ICON={system:'sun-moon',light:'sun',dark:'moon'},THEME_NAME={system:'시스템',light:'밝게',dark:'어둡게'};
function applyTheme(){let t=prefs().theme||'system'; if(!THEME_ICON[t])t='system';
  const eff=t==='system'?(MQ.matches?'light':'dark'):(t==='light'?'light':'dark');
  document.documentElement.setAttribute('data-theme',eff); const b=$('#btn-theme'); b.innerHTML=ic(THEME_ICON[t]);
  b.setAttribute('aria-label','화면 테마: '+THEME_NAME[t]);
  b.dataset.tip='화면 테마: 지금 '+THEME_NAME[t]+'. 누르면 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다';
  const m=$('#m-theme'); if(m)m.textContent='테마: '+THEME_NAME[t];}
MQ.addEventListener('change',applyTheme);
function cycleTheme(){const t=prefs().theme||'system';savePrefs({theme:THEMES[(THEMES.indexOf(t)+1)%3]});applyTheme();}

// ------------------------------------------------ 서버 호출과 알림
async function api(url,o){o=o||{};
  const init={method:o.method||'GET',headers:{}};
  if(o.body!==undefined){init.body=JSON.stringify(o.body);init.headers['Content-Type']='application/json';}
  let r;
  try{r=await fetch(url,init);}catch(e){if(!o.silent)toast((o.what||'요청')+' 실패 — 서버에 닿지 않습니다','err');throw e;}
  let d=null; try{d=await r.json();}catch(e){}
  if(r.status>=400&&!(o.expect||[]).includes(r.status)){
    if(!o.silent)toast((o.what||'요청')+' 실패 — '+((d&&d.error)||('HTTP '+r.status)),'err');
    const err=new Error('HTTP '+r.status); err.status=r.status; err.data=d; throw err;}
  return {status:r.status,data:d};
}
function toast(msg,kind,action){
  const box=$('#toasts'),t=document.createElement('div'); t.className='toast '+(kind||'ok');
  const s=document.createElement('span'); s.textContent=msg; t.appendChild(s);
  let timer=null; const kill=()=>{clearTimeout(timer);t.remove();hideTip();};
  const arm=()=>{clearTimeout(timer);timer=setTimeout(kill,6000);};
  if(action){const b=document.createElement('button');b.className='btn-sm';b.textContent=action.label;b.dataset.tip=action.tip||T.undo;
    b.addEventListener('click',()=>{kill();action.fn();});t.appendChild(b);}
  const c=document.createElement('button');c.className='btn-icon btn-sm btn-ghost';c.innerHTML=ic('x');c.dataset.tip='알림 닫기';
  c.setAttribute('aria-label','알림 닫기');c.addEventListener('click',kill);t.appendChild(c);
  t.addEventListener('mouseenter',()=>clearTimeout(timer)); t.addEventListener('mouseleave',arm);
  box.appendChild(t); arm(); while(box.children.length>5) box.firstChild.remove();
  return t;
}
async function copyText(s){
  try{await navigator.clipboard.writeText(s);}catch(e){
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e2){} ta.remove();}
  toast('복사함: '+s,'ok');
}

// ------------------------------------------------ 툴팁
const TIP=$('#tip'); let tipT=null,tipEl=null,TIPXY=null;
document.addEventListener('mousemove',e=>{TIPXY=[e.clientX,e.clientY];},{passive:true});
function hideTip(){clearTimeout(tipT);tipT=null;tipEl=null;TIP.hidden=true;}
function showTip(el){const txt=el.dataset.tip; if(!txt||!document.contains(el))return;
  TIP.textContent=txt; TIP.hidden=false;
  const r=el.getBoundingClientRect(),tw=TIP.offsetWidth,th=TIP.offsetHeight;
  let top=r.top-th-8, cx=r.left+r.width/2;
  if(top<4) top=r.bottom+8;
  if(top>innerHeight-th-4 && TIPXY){top=TIPXY[1]+18; cx=TIPXY[0];}   // 창보다 긴 요소(#grip·긴 카드)는 포인터에 붙인다
  top=Math.max(4,Math.min(top,innerHeight-th-4));
  const left=Math.min(Math.max(4,cx-tw/2),innerWidth-tw-4);
  TIP.style.left=left+'px'; TIP.style.top=top+'px';}
function armTip(el){if(el===tipEl)return; hideTip(); if(!el)return; tipEl=el; tipT=setTimeout(()=>showTip(el),300);}
// 터치 직후에는 호버·포커스 툴팁을 띄우지 않는다 — 모바일 크롬은 탭마다 mouseover·focusin 을 흉내 내서, 버튼을
// 누를 때마다 설명이 튀어나왔다. 터치에서는 길게 누르기(아래)로 본다.
const touchRecent=()=>Date.now()-LAST_TOUCH_T<1500;
document.addEventListener('pointerdown',e=>{LAST_PTR=e.pointerType||'mouse'; if(LAST_PTR!=='mouse')LAST_TOUCH_T=Date.now();},true);
document.addEventListener('mouseover',e=>{if(touchRecent())return; armTip(e.target.closest?e.target.closest('[data-tip]'):null);});
// 입력 칸(textarea)에는 포커스 툴팁을 띄우지 않는다 — 타이핑 중 스니펫을 가리고, 첫 Esc 를 툴팁이 먹어
// '취소하려고 Esc → Ctrl+Enter' 가 버리려던 핀을 저장했다(실측).
document.addEventListener('focusin',e=>{const t=e.target;
  if((t&&t.tagName==='TEXTAREA')||touchRecent()){if(Date.now()>=SWALLOW_CLICK)hideTip();return;}
  armTip(t.closest?t.closest('[data-tip]'):null);});
// 길게 누르기 툴팁(터치·펜): 500ms 누르고 있으면 설명을 띄우고, 손을 뗀 뒤의 click 한 번은 삼킨다(버튼이 눌리지 않게).
// 쪽 이미지 위는 빠른 선택(길게 누르기 = 그 문단)이 쓰므로 배지(.mark b)만 해당한다. 입력 칸은 붙여넣기 메뉴를 살린다.
let PRESS=null,SWALLOW_CLICK=0;
function pressTarget(t){const el=t&&t.closest?t.closest('[data-tip]'):null; if(!el)return null;
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT')return null;
  if(el.closest('.pg')&&!el.closest('.mark b'))return null; return el;}
document.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse')return; if(!TIP.hidden)hideTip();
  const el=pressTarget(e.target); if(!el)return;
  PRESS={el,x:e.clientX,y:e.clientY,t:setTimeout(()=>{showTip(el); PRESS.shown=true; SWALLOW_CLICK=Date.now()+900;
    setTimeout(()=>{if(!TIP.hidden&&TIP.textContent===el.dataset.tip)hideTip();},4000);},500)};},true);
function endPress(){if(PRESS){clearTimeout(PRESS.t); PRESS=null;}}
document.addEventListener('pointermove',e=>{if(PRESS&&Math.hypot(e.clientX-PRESS.x,e.clientY-PRESS.y)>10)endPress();},true);
document.addEventListener('pointerup',endPress,true);
document.addEventListener('pointercancel',endPress,true);
document.addEventListener('click',e=>{if(Date.now()<SWALLOW_CLICK){SWALLOW_CLICK=0;e.preventDefault();e.stopImmediatePropagation();}},true);
document.addEventListener('contextmenu',e=>{if(LAST_PTR==='mouse')return; const t=e.target;
  if(t&&t.closest&&(t.closest('.pg')||pressTarget(t)))e.preventDefault();});
document.addEventListener('input',hideTip,true);
document.addEventListener('focusout',hideTip);
document.addEventListener('scroll',hideTip,true);
// 길게 누르기로 띄운 직후 손을 떼면 크롬이 흉내 mousedown 을 보낸다 — 그것으로는 닫지 않는다.
document.addEventListener('mousedown',()=>{if(Date.now()>=SWALLOW_CLICK)hideTip();},true);

// ------------------------------------------------ 여러 문서 — 목록·탭·전환(references/design.md §여러 문서)
function multiDoc(){return DOCS.length>1;}
function docInfo(k){return DOCS.find(d=>d.key===k)||null;}
function pdoc(p){return (p&&p.doc)||DEFAULT_DOC;}
function isRegion(p){return !!p&&(p.kind==='region'||(!p.file&&!!p.pdf));}
// 문서가 걸리는 경로에 ?doc=<키> 를 붙인다(서버는 없으면 첫 문서로 본다).
function dq(u,k){k=k||DOC; if(!k)return u; return u+(u.indexOf('?')<0?'?':'&')+'doc='+encodeURIComponent(k);}
function hashDoc(){const m=/(?:^#|[#&])doc=([a-z0-9-]{1,24})(?:&|$)/.exec(location.hash||''); return m?m[1]:null;}
function setHash(k){if(!multiDoc())return; const h='#doc='+k; if(location.hash!==h)history.replaceState(null,'',location.pathname+location.search+h);}
// 처음 볼 문서: URL 해시(링크 공유·새로고침) > 이 기기에서 마지막으로 본 문서 > 첫 문서.
function initialDoc(){const h=hashDoc(); if(h&&docInfo(h))return h; const l=prefs().lastDoc; if(l&&docInfo(l))return l;
  return DOCS.length?DOCS[0].key:null;}
async function loadDocs(){try{const r=(await api('/api/docs',{what:'문서 목록',silent:true})).data;
    DOCS=Array.isArray(r.docs)?r.docs:[]; DEFAULT_DOC=r.default||(DOCS[0]&&DOCS[0].key)||'main';}catch(e){DOCS=[];}
  document.body.classList.toggle('docs-multi',multiDoc()); $('#all-docs').hidden=!multiDoc();}
function docCount(k){return OPEN_ALL.filter(p=>pdoc(p)===k).length;}
function docBadge(d){const n=docCount(d.key);
  return (d.building?'<span class="spin" aria-label="빌드 중"></span>':(d.stale_build?'<span class="ddot" aria-label="원고 수정됨"></span>':''))+
    (d.view_only?'<span class="badge dvo" aria-label="보기 전용">PDF</span>':'')+'<span class="badge badge-secondary dcnt'+(n?'':' z')+'" aria-label="열린 핀 '+n+'">'+n+'</span>';}
function docTip(d){return d.name+' · '+d.path+(d.view_only?' · 보기 전용 PDF(줄 번호 없이 쪽·영역으로 핀을 남깁니다)':'')+
  (d.building?' · 빌드 중':(d.stale_build?' · 원고가 이 PDF보다 새롭습니다(그 탭에서 [PDF 재빌드])':''));}
function drawDocTabs(){
  const box=$('#doc-tabs'); if(!multiDoc()){box.innerHTML=''; return;}
  box.innerHTML=DOCS.map((d,i)=>{const on=d.key===DOC;
    return '<button class="dtab" role="tab" id="dtab-'+esc(d.key)+'" aria-selected="'+on+'" tabindex="'+(on?0:-1)+'" aria-controls="left" data-act="doc" data-doc="'+esc(d.key)+'" data-tip="'+
      esc(docTip(d)+(i<9?' (Alt+'+(i+1)+')':''))+'"><span class="nm">'+esc(d.name)+'</span>'+docBadge(d)+'</button>';}).join('');
  const on=box.querySelector('[aria-selected=true]'); if(on)segReveal(box);
  const cur=docInfo(DOC); $('#btn-doc-n').textContent=cur?cur.name:'문서';
  $('#btn-doc-dot').hidden=!DOCS.some(d=>d.key!==DOC&&(d.stale_build||d.building));
  if($('#docs-menu').open)drawDocsMenu();}
function drawDocsMenu(){
  $('#docs-menu-list').innerHTML=DOCS.map(d=>{const on=d.key===DOC;
    return '<button class="dm-item'+(on?' on':'')+'" role="option" aria-selected="'+on+'" data-act="doc" data-doc="'+esc(d.key)+'" data-close="1">'+
      '<span class="tx"><span class="nm">'+esc(d.name)+(on?ic('check'):'')+'</span><span class="ph">'+esc(d.path)+'</span></span>'+docBadge(d)+'</button>';}).join('');}
function openDocsMenu(){const d=$('#docs-menu'); if(d.open)return; hideTip(); drawDocsMenu(); d.showModal();
  const on=d.querySelector('.dm-item.on'); if(on)on.focus();}
// 보던 자리: 위쪽 기준 쪽·비율, 쪽 폭, compact 에서 손으로 확대했는가, 가로 스크롤. 새로고침에도 남게 sessionStorage 에 둔다.
function saveView(){if(!DOC||!META||!$('#doc .pg'))return; const a=topAnchor();
  VIEW_BY.set(DOC,{page:a?a.page:1,frac:a?a.frac:0,w:W,zoomed:ZOOMED,sl:$('#left').scrollLeft,lay:LAYOUT});
  if(multiDoc()){try{sessionStorage.setItem('pinDocView',JSON.stringify(Array.from(VIEW_BY.entries())));}catch(e){}}}
function loadViews(){if(!multiDoc())return; try{const a=JSON.parse(sessionStorage.getItem('pinDocView')||'[]');
  if(Array.isArray(a))a.forEach(x=>{if(Array.isArray(x)&&docInfo(x[0])&&x[1]&&typeof x[1]==='object')VIEW_BY.set(x[0],x[1]);});}catch(e){}}
// 쪽 폭을 먼저 정한다(buildDoc 이 W 로 쪽을 만든다). 같은 레이아웃에서 본 폭만 되살린다 — 접은 화면에서 맞춘 폭을 데스크톱에 쓰지 않게.
function applyViewWidth(v){if(v&&typeof v.w==='number'&&v.lay===LAYOUT&&(LAYOUT==='wide'||v.zoomed)){W=v.w; ZOOMED=LAYOUT!=='wide'&&!!v.zoomed; return true;}
  ZOOMED=false; return false;}
function restoreView(v){if(!v)return; restoreAnchor({page:v.page,frac:v.frac}); if(typeof v.sl==='number')$('#left').scrollLeft=v.sl;}
addEventListener('pagehide',saveView);
// 문서를 바꾼다. 지금 문서의 보던 자리를 기억하고, 쓰던 선택·위치 다시 잡기는 거둔다(메모 글은 남긴다).
// meta 캐시가 있으면 기다리지 않고 바로 그 문서를 그리고, 뒤에서 최신 meta 를 받아 빌드가 바뀌었으면 쪽만 바꾼다.
async function switchDoc(k){
  if(!k||k===DOC||!docInfo(k))return; const seq=++SWITCHSEQ;
  saveView(); cancelRepick(); if(CUR||!$('#composer').hidden)cancelSelection(false);
  if(EDIT&&!editDirty())cancelEdit();
  let m=META_BY.get(k),cached=!!m;
  if(!m){try{m=(await api(dq('/api/meta',k),{what:'문서 열기'})).data;}catch(e){return;} if(seq!==SWITCHSEQ)return;}
  DOC=k; META=m; META_BY.set(k,m); savePrefs({lastDoc:k}); setHash(k);
  hideTip(); showDoc(VIEW_BY.get(k));
  if(cached){try{const f=(await api(dq('/api/meta',k),{what:'문서 열기',silent:true})).data;
    if(seq===SWITCHSEQ&&DOC===k){const changed=f.pages_build!==META.pages_build||f.pages.length!==META.pages.length;
      META_BY.set(k,f); if(changed)await refreshDoc(); else{META=f; drawMeta();}}}catch(e){}}
}
// 지금 META 로 화면을 새로 그린다(탭 전환). 빌드 칩·오류 패널·자동 폴링 기준값도 그 문서의 것으로 바꾼다.
function showDoc(v){
  drawMeta(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); restoreView(v);
  if(!v&&$('#left'))$('#left').scrollTop=0;
  PINS=OPEN_ALL.filter(p=>pdoc(p)===DOC); drawPins(); marks(); drawDocTabs();
  vecOpen();
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;} $('#build-chip').hidden=true; $('#btn-rebuild').disabled=false;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0; LAST_BUILD_ERR=BUILD_ERR_BY.get(DOC)||null;
  if(LAST_BUILD_ERR)hideBuildErr(); else{$('#build-err').hidden=true; $('#build-err-chip').hidden=true;}
  BUILD_BOOTED=true; if(BUILD_INFLIGHT)BUILD_INFLIGHT.then(()=>pollBuild()); else pollBuild();   // 옛 문서의 조회가 떠 있으면 그 뒤에
  document.title=(META.label?META.label+' · ':'')+'원고 핀 · '+(multiDoc()?META.doc_name||META.main:META.main)+' · 열린 '+PINS.length;
}
function cycleDoc(step){if(!multiDoc())return; const i=DOCS.findIndex(d=>d.key===DOC);
  switchDoc(DOCS[(i+step+DOCS.length)%DOCS.length].key);}
window.addEventListener('hashchange',()=>{const k=hashDoc(); if(k&&k!==DOC&&docInfo(k))switchDoc(k);});
// 다른 문서 핀의 #번호·[보기]·[수정]: 그 문서로 바꾼 뒤 then 을 다시 부른다(jumpPin·openEdit 이 맨 앞에서 쓴다). 바꿨으면 true.
function viaDoc(id,then){const p=OPEN_ALL.find(x=>x.id===id);
  if(!p||pdoc(p)===DOC||!docInfo(pdoc(p)))return false;
  const k=pdoc(p); switchDoc(k).then(()=>{if(DOC===k)then(id);}); return true;}

// ------------------------------------------------ 문서
async function boot(){
  applyTheme(); applyLayout();
  // 터치 기기에는 단축키가 없다 — '핀 저장 Ctrl+Enter' 는 휴대폰 폭에서 잘리기만 한다.
  $('#btn-save').innerHTML=MQ_COARSE.matches?'핀 저장':'핀 저장 <span class="kh">'+(IS_MAC?'⌘ Enter':'Ctrl+Enter')+'</span>';
  await loadDocs(); DOC=initialDoc();
  try{META=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data;}catch(e){return;}
  if(META.doc)DOC=META.doc; META_BY.set(DOC,META); loadViews(); const v=VIEW_BY.get(DOC);
  if(multiDoc()){setHash(DOC); savePrefs({lastDoc:DOC});}
  drawMeta(); applySideWidth(); const hadW=applyViewWidth(v); buildDoc(); if(!hadW)autoW(); vecBoot(); await loadPins();
  restoreView(v); drawDocTabs();
  if(MQ_COARSE.matches)coach('touch','PDF를 길게 누르면 그 문단을 고릅니다 · [선택]을 켜면 끌어서 고릅니다');
  LAST_PINS_REV=META.pins_rev; LAST_SRC_MTIME=META.src_sig||META.src_mtime;
  LAST_BUILD_SEQ=(typeof META.build_seq==='number')?META.build_seq:0;   // 이 탭이 이미 '본' 빌드 수
  (META.docs||[]).forEach(d=>DOC_SEQ.set(d.key,d.build_seq));
  startLightPolling(); startBuildPolling();
}
function builtAtEpoch(s){const t=Date.parse(String(s||'').replace(' ','T')); return isNaN(t)?null:t/1000;}
// 원고 수정됨 배지 — 서버가 준 숫자(stale_build, src_age_s)로만 판정한다. 브라우저 시계·시간대와 무관하다.
// stale_build 가 없는 옛 응답만 src_mtime/build_src_mtime(둘 다 서버 epoch) 비교로 폴백한다.
function updateStaleBadge(m){
  const badge=$('#meta-stale'), btn=$('#btn-rebuild');
  let stale;
  if(typeof m.stale_build==='boolean')stale=m.stale_build;
  else{const ref=(typeof m.build_src_mtime==='number')?m.build_src_mtime:builtAtEpoch(META&&META.built_at);
    stale=ref!=null&&typeof m.src_mtime==='number'&&m.src_mtime>ref+2;}
  if(!stale){badge.hidden=true; btn.classList.remove('btn-default'); return;}
  const age=(typeof m.src_age_s==='number')?m.src_age_s:(Date.now()/1000-m.src_mtime);
  const mins=Math.max(0,Math.round(age/60));
  badge.hidden=false; badge.textContent='원고 수정됨 · '+mins+'분 전';
  btn.classList.add('btn-default');
}
function drawMeta(){
  document.body.classList.toggle('view-only',!!META.view_only);
  $('#meta-main').textContent=META.main; $('#meta-pages').textContent=META.pages.length+'쪽';
  $('#meta-head').textContent=META.head; $('#meta-built').textContent=String(META.built_at||'').slice(0,16).replace('T',' ');
  const me=META.me||{};
  $('#me').innerHTML=avatar(me)+'<span class="au-n">'+esc(me.name||me.login||'')+'</span>';
  $('#me').dataset.tip='지금 이 화면을 쓰는 사람: '+(me.name||'')+(me.login&&me.login!=='local'?' ('+me.login+')':'')+'. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다';
  updateStaleBadge(META);
  $('#help-pins-md').textContent=META.pins_md||'';
  // compact 에서는 #bar2 의 파일·커밋·시각·작성자 줄을 숨기고 [⋯] 안에 한 줄로 보인다(긴 파일 이름이 넘치지 않게).
  $('#more-info').textContent=[META.main,META.pages.length+'쪽',META.head,String(META.built_at||'').slice(0,16).replace('T',' '),
    '나: '+(me.name||me.login||'')].filter(Boolean).join(' · ');
}

// ------------------------------------------------ 자동 동기화(P0b-02) — 가벼운 meta 폴링
let LAST_PINS_REV=null,LAST_SRC_MTIME=null,POLL_FAILS=0,LIGHT_TIMER=null,LIGHT_INFLIGHT=null;
// 단일 비행: pollBuild 와 같은 패턴 — visibilitychange·focus·5초 타이머가 겹쳐 불러도(예: 탭 전환과
// 동시에 포커스가 돌아오면) /api/meta·loadPins 는 한 번만 나간다(결함 실측: 겹치면 loadPins 3회).
function pollLight(){
  if(document.hidden)return Promise.resolve();   // 탭이 숨으면 요청 자체를 보내지 않는다
  if(LIGHT_INFLIGHT)return LIGHT_INFLIGHT;
  LIGHT_INFLIGHT=pollLightOnce().finally(()=>{LIGHT_INFLIGHT=null;});
  return LIGHT_INFLIGHT;
}
async function pollLightOnce(){
  let d; const k=DOC;
  try{d=(await api(dq('/api/meta?light=1'),{what:'상태 확인',silent:true})).data; POLL_FAILS=0;}
  catch(e){POLL_FAILS++; if(POLL_FAILS>=2)$('#conn-lost').hidden=false; return;}
  $('#conn-lost').hidden=true;
  if(k!==DOC)return;                    // 기다리는 사이 문서를 바꿨다 — 옛 문서의 상태로 화면을 칠하지 않는다
  updateStaleBadge(d); noteOtherDocs(d.docs);
  // 여러 문서면 src_sig(문서마다의 src_mtime)가 바뀌어도 다시 읽는다 — 다른 문서의 원고가 바뀌어도 그 핀들의 줄이 밀린다.
  const sig=d.src_sig||d.src_mtime;
  if(LAST_PINS_REV!==null&&(d.pins_rev!==LAST_PINS_REV||sig!==LAST_SRC_MTIME)) await loadPins();
  LAST_PINS_REV=d.pins_rev; LAST_SRC_MTIME=sig;
  // 다른 세션·에이전트가 curl 로 시작한 빌드도 light meta 의 build.state 로 잡아낸다 — 1초 폴링은
  // 그때만(또는 이 탭에서 직접 rebuild() 를 눌렀을 때만) 돈다.
  if(d.build&&d.build.state==='running'&&!BUILD_TIMER)pollBuild();
  // build_seq(끝난 빌드 수)가 이 탭이 본 값과 다르면, 5초 틈새 안에 시작~종료까지 끝나 'running'을 한 번도
  // 못 본 빌드가 있었다는 뜻이다 — 상세를 받아 화면·배너·칩을 맞춘다.
  else if(typeof d.build_seq==='number'&&d.build_seq!==LAST_BUILD_SEQ)pollBuild();
}
// 다른 문서의 낡음·빌드 중을 탭에 반영하고, 그 문서의 빌드가 뒤에서 끝났으면 알린 뒤 meta 캐시를 버린다(돌아가면 새 쪽).
function noteOtherDocs(list){if(!Array.isArray(list)||!list.length)return; let redraw=false;
  list.forEach(n=>{const d=docInfo(n.key); if(!d)return;
    if(d.stale_build!==n.stale_build||d.building!==n.building){d.stale_build=n.stale_build; d.building=n.building; redraw=true;}
    const was=DOC_SEQ.get(n.key); DOC_SEQ.set(n.key,n.build_seq);
    if(n.key===DOC||was===undefined||was===n.build_seq)return;
    META_BY.delete(n.key); redraw=true;
    if(n.last_state==='ok')toast(d.name+' PDF '+(d.view_only?'쪽을 새로 그렸습니다':'재빌드 완료'),'ok',{label:'열기',tip:'그 문서로 바꿉니다',fn:()=>switchDoc(n.key)});
    else if(n.last_state==='ok_errors'||n.last_state==='fail')toast(d.name+(n.last_state==='fail'?' 빌드 실패':' 빌드에 LaTeX 오류'),n.last_state==='fail'?'err':'warn',{label:'열기',tip:'그 문서로 바꿔 오류를 봅니다',fn:()=>switchDoc(n.key)});});
  if(redraw)drawDocTabs();}
function startLightPolling(){
  clearInterval(LIGHT_TIMER); LIGHT_TIMER=setInterval(pollLight,5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollLight();});
  window.addEventListener('focus',()=>pollLight());
}
// 자기 탭이 방금 한 close/drop/reopen/restore 는 로컬 토스트를 이미 띄웠으니 다음 loadPins() 의
// diffToast 에서 같은 전환을 또 알리지 않는다 — markMine(id) 직후 첫 diffToast 판정 한 번만 삼키고
// (consumeMine 이 확인 즉시 지운다) 10초가 지나도록 그 판정이 안 왔으면(예: 응답 유실) 포기하고
// 이후 값은 정상적으로 알린다. 다른 탭이 한 동작은 이 맵에 없으므로 그대로 뜬다.
const MY_ACTIONS=new Map();
function markMine(id){MY_ACTIONS.set(id,Date.now()+10000);}
function consumeMine(id){const until=MY_ACTIONS.get(id); if(until===undefined)return false;
  MY_ACTIONS.delete(id); return Date.now()<=until;}
function diffToast(prev,d,dropped){
  // prev 는 직전에 이 탭이 본 '열린 핀'만이다(PINS 는 done 을 담지 않는다). d 는 이번 GET 의 열린+닫힌
  // 핀(all=1) 전부다 — prev 에 있던 id 가 d 에도 있는데 done=true 면 완료된 것이고, d 에 아예 없으면
  // (열려도 닫혀도 없으면) 삭제된 것이다. 옛 구현은 이 둘을 가리지 않고 전부 '완료'로 알렸다 — 공저자가
  // 핀을 지우면 작성자 화면에 '#N 이 완료되었습니다'가 떴다(실측).
  if(!prev||!prev.length)return;
  const byId=new Map(prev.map(p=>[p.id,p]));
  const known=new Map((d||[]).map(p=>[p.id,p]));
  const dropById=new Map((dropped||[]).map(p=>[p.id,p]));
  const closed=[],droppedIds=[];
  byId.forEach((_,id)=>{const n=known.get(id);
    if(n&&n.done){if(!consumeMine(id))closed.push(id);}
    else if(!n){if(!consumeMine(id))droppedIds.push(id);}});
  if(closed.length)toast('#'+closed.join(', #')+' 이 완료되었습니다','ok');
  droppedIds.forEach(id=>{const rec=dropById.get(id),nm=rec?who(rec.dropped_by):'';
    toast('#'+id+' 을 '+(nm||'다른 세션')+' 가 삭제함','warn',{label:'되살리기',fn:()=>restorePin(id)});});
  (d||[]).filter(p=>!p.done).forEach(p=>{const was=byId.get(p.id); if(!was)return;
    if(!was.stale&&p.stale){toast('#'+p.id+' 위치를 잃었습니다','warn');return;}
    const m=/^moved ([+-]\d+)$/.exec(p.sync||''),wm=/^moved ([+-]\d+)$/.exec(was.sync||'');
    if(m&&(!wm||wm[1]!==m[1]))toast('#'+p.id+' 줄 '+m[1]+' 이동','ok');});
}

// ------------------------------------------------ 비동기 빌드 진행 칩(P0b-01)
// BUILD_TIMER 는 빌드가 실제로 도는 동안만 존재한다 — 할 일이 없을 때(idle/ok/fail 로 이미 안정된
// 뒤)까지 매초 /api/build 를 때리지 않는다. 시작하는 곳은 셋뿐이다: 이 탭에서 rebuild() 를 눌렀을 때,
// pollLight(5초 폴링)가 build.state==='running' 을 봤을 때, 그리고 부팅 시 이미 도는 빌드를 잡을 때.
// 끝난 빌드는 build_seq(서버가 빌드마다 1씩 올림)로 센다. LAST_BUILD_SEQ 는 이 탭이 이미 처리한 값이다 —
// 처리(화면 교체·토스트)는 seq 하나당 한 번이다. started_at 문자열이나 'running 을 봤는가'로 세면 5초 틈새에
// 끝난 빌드를 놓치거나, 숨은 탭이 돌아올 때 두 경로가 같은 완료를 두 번 처리했다(실측: 토스트 ×2).
let BUILD_TIMER=null,LAST_BUILD_ERR=null,LAST_BUILD_SEQ=null,BUILD_BOOTED=false,BUILD_INFLIGHT=null;
function buildChipText(b){
  const label={pull:'원격 main 당겨오는 중',copy:'원고 복사 중',latex:'LaTeX 컴파일 중',render:'쪽 그리는 중'}[b.phase]||'재빌드 중';
  const el=Math.round(b.elapsed_s||0), last=b.last_s?' (지난번 '+Math.round(b.last_s)+'초)':'';
  return label+' · '+el+'초'+last;
}
// §P0c-E: 빌드 완료 토스트에 pull 결과를 한 줄 덧붙인다. ok 는 반영된 커밋 범위, skipped·error 는 사유만 —
// up_to_date 는 알릴 변화가 없으므로 덧붙이지 않는다.
function pullSuffix(b){
  const p=b&&b.pull; if(!p||!p.state)return '';
  if(p.state==='ok')return ' · 원격 반영 '+String(p.head_before||'?').slice(0,7)+'..'+String(p.head_after||'?').slice(0,7);
  if(p.state==='skipped'||p.state==='error')return ' · git pull '+(p.state==='error'?'실패':'건너뜀')+'('+(p.reason||'?')+')';
  return '';
}
// 단일 비행: 이미 도는 조회가 있으면 새로 보내지 않고 그 약속을 돌려준다(1초 타이머·visibilitychange·
// focus·pollLight 가 한꺼번에 불러도 /api/build 는 한 번, 완료 처리도 한 번).
function pollBuild(){
  if(document.hidden)return Promise.resolve();   // 탭이 숨으면 요청 자체를 보내지 않는다
  if(BUILD_INFLIGHT)return BUILD_INFLIGHT;
  BUILD_INFLIGHT=pollBuildOnce().finally(()=>{BUILD_INFLIGHT=null;});
  return BUILD_INFLIGHT;
}
async function pollBuildOnce(){
  let b; const k=DOC;
  try{b=(await api(dq('/api/build?log=1'),{what:'빌드 상태',silent:true})).data;}catch(e){return;}
  if(k!==DOC)return;                    // 문서를 바꿨다 — 새 문서는 showDoc 이 다시 묻는다
  const chip=$('#build-chip');
  if(b.state==='running'){
    chip.hidden=false; chip.textContent=buildChipText(b); $('#btn-rebuild').disabled=true;
    if(!BUILD_TIMER)BUILD_TIMER=setInterval(pollBuild,1000);
    BUILD_BOOTED=true; return;
  }
  chip.hidden=true; $('#btn-rebuild').disabled=false;
  if(BUILD_TIMER){clearInterval(BUILD_TIMER);BUILD_TIMER=null;}    // 더 볼 게 없으면 폴링을 멈춘다
  const seq=(typeof b.seq==='number')?b.seq:0;
  const booted=BUILD_BOOTED; BUILD_BOOTED=true;
  if(LAST_BUILD_SEQ===null)LAST_BUILD_SEQ=seq;
  if(seq!==LAST_BUILD_SEQ){
    LAST_BUILD_SEQ=seq;                 // await 전에 먼저 차지한다 — 같은 완료를 두 번 처리하지 않게
    DOC_SEQ.set(k,seq);
    try{await refreshDoc();}catch(e){}
    if(k!==DOC)return;
    const secs=Math.round(b.elapsed_s||0);
    if(b.state==='ok'){toast((META.view_only?'PDF가 바뀌어 쪽을 새로 그렸습니다 · ':'PDF 재빌드 완료 · ')+META.pages.length+'쪽 · '+secs+'초'+pullSuffix(b),'ok'); LAST_BUILD_ERR=null; BUILD_ERR_BY.delete(k); hideBuildErr();}
    else if(b.state==='ok_errors'){toast('PDF를 재빌드했지만 LaTeX 오류가 있습니다'+pullSuffix(b),'warn'); showBuildErr(b);}
    else if(b.state==='fail'){toast('빌드 실패 — 화면은 이전 PDF입니다'+pullSuffix(b),'err'); showBuildErr(b);}
  }else if(!booted&&(b.state==='fail'||b.state==='ok_errors')){
    showBuildErr(b);   // 새로 연 탭 — 이미 실패해 있던 빌드는 토스트 없이 패널·칩만 연다(다시 볼 길을 남긴다)
  }
}
function startBuildPolling(){
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollBuild();});
  window.addEventListener('focus',()=>pollBuild());
  pollBuild();   // 부팅 시 한 번 — 이미 도는 빌드(다른 세션이 시작)가 있으면 여기서 1초 폴링이 켜진다
}

// ------------------------------------------------ 패널 폭(P0b-06 + references/design.md §패널 폭 조절)
// wide·mid 는 오른쪽 패널의 폭을, narrow 는 하단 시트의 높이를 조절한다. 폭은 화면 종류별로 따로 기억한다
// (pinPrefs.side = wide, pinPrefs.sideMid = mid) — 편 화면에서 맞춘 폭이 데스크톱 폭을 덮지 않게. 저장값이 지금 화면의
// 한계를 넘으면(접기·펴기, 창 줄이기) 저장값은 두고 보이는 폭만 한계 안으로 맞춘다. 한계: 최소는 패널 도구 줄이
// 한 줄에 들어가는 폭, 최대는 본문(PDF) 쪽 최소 폭을 남기는 폭.
function sideBounds(layout,iw){const cl=(w,a,b)=>Math.round(Math.min(b,Math.max(a,w)));
  if(layout==='mid'){const min=300,max=Math.max(min,Math.min(Math.round(iw*0.6),iw-320));
    const def=cl(iw*0.38,300,Math.min(360,max)); return {min,max,def,presets:[min,def,cl(iw*0.5,min,max)]};}
  const min=280,max=Math.max(min,Math.min(Math.round(iw*0.8),iw-486)),def=cl(430,min,max);
  return {min,max,def,presets:[cl(320,min,max),def,cl(iw*0.42,min,max)]};}
function clampSide(w,b){return Math.round(Math.min(b.max,Math.max(b.min,w)));}
// 단계 순환: 지금 폭보다 큰 다음 단계, 가장 넓으면 가장 좁은 단계로. presetIndex 는 ±4px 안에서 맞는 단계(없으면 -1).
function nextPreset(presets,w){const n=presets.find(p=>p>w+4); return n===undefined?presets[0]:n;}
function presetIndex(presets,w){return presets.findIndex(p=>Math.abs(p-w)<=4);}
function sideKey(){return LAYOUT==='mid'?'sideMid':'side';}
function curSideW(){return Math.round($('#right').getBoundingClientRect().width);}
function showSideW(w,b){$('#right').style.width=w+'px'; document.documentElement.style.setProperty('--side-w',w+'px');
  const g=$('#grip'); g.setAttribute('aria-valuenow',w); g.setAttribute('aria-valuemin',b.min); g.setAttribute('aria-valuemax',b.max);}
function applySideWidth(){
  if(LAYOUT==='narrow'){$('#right').style.width=''; applySheet(); return;}
  const b=sideBounds(LAYOUT,innerWidth),p=prefs()[sideKey()];
  showSideW(clampSide(typeof p==='number'?p:b.def,b),b);
}
// 폭을 정하고 기억한 뒤 쪽 폭·마크를 다시 맞춘다(보던 자리 유지 — relayout 이 topAnchor/restoreAnchor 를 쓴다).
function setSideWidth(w){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); w=clampSide(w,b);
  showSideW(w,b); savePrefs({[sideKey()]:w}); relayout(); renderSizeSeg();}
function cycleSideWidth(){if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth); setSideWidth(nextPreset(b.presets,curSideW()));}
// 시트 높이는 화면 높이 비율(--sheet-f)로 둔다 — 키보드가 올라오면 CSS 가 보이는 높이 안으로 줄인다.
const SHEET_F=[0.45,0.64,1],SHEET_MIN_F=0.3,SHEET_CLOSE_F=0.25;
function sheetF(){const f=prefs().sheetF; return typeof f==='number'?Math.min(1,Math.max(SHEET_MIN_F,f)):0.64;}
function applySheet(){document.documentElement.style.setProperty('--sheet-f',String(sheetF()));}
function setSheetF(f){f=Math.min(1,Math.max(SHEET_MIN_F,f)); savePrefs({sheetF:Math.round(f*1000)/1000}); applySheet(); if(!SIDE_OPEN)setSide(true); renderSizeSeg();}
function cycleSheet(){const f=sheetF(),i=SHEET_F.findIndex(x=>x>f+0.02); setSheetF(SHEET_F[i<0?0:i]);}
// [⋯] 안의 '패널 폭'(wide·mid) / '시트 높이'(narrow) 분절 컨트롤.
function renderSizeSeg(){const box=$('#m-size'); if(!box)return; const narrow=LAYOUT==='narrow';
  $('#m-size-l').textContent=narrow?'시트 높이':'패널 폭'; box.setAttribute('aria-label',narrow?'시트 높이':'패널 폭');
  let names,cur;
  if(narrow){names=['낮게','보통','높게']; const f=sheetF(); cur=SHEET_F.findIndex(x=>Math.abs(x-f)<=0.02);}
  else{names=['좁게','보통','넓게']; cur=presetIndex(sideBounds(LAYOUT,innerWidth).presets,curSideW());}
  box.innerHTML=names.map((n,i)=>'<button class="'+(i===cur?'on':'')+'" aria-pressed="'+(i===cur)+'" data-act="size-preset" data-i="'+i+'">'+n+'</button>').join('');}
function sizePreset(i){if(LAYOUT==='narrow'){setSheetF(SHEET_F[i]);return;} setSideWidth(sideBounds(LAYOUT,innerWidth).presets[i]);}
function pageSrc(p){return dq('/pages/'+encodeURIComponent(p.name)+'?v='+encodeURIComponent(META.built_at));}
function buildDoc(){
  const doc=$('#doc'); doc.innerHTML=''; PENDING=null;
  META.pages.forEach((p,i)=>{const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.dataset.page=i+1;
    d.style.width=W+'px'; d.style.aspectRatio=p.pt_w+' / '+p.pt_h;
    d.innerHTML='<span class="no">'+(i+1)+'</span><img loading="lazy" draggable="false" alt="'+(i+1)+'쪽" src="'+esc(pageSrc(p))+'">';
    doc.appendChild(d);});
  marks(); vecObserve();
}
// save=false 는 자동 맞춤 — 저장하지 않는다. 좁은 첫 창에서 맞춘 폭이 넓은 창에서도 남으면 쪽이 작게 보인다.
// compact(mid·narrow)에서는 폭을 저장하지 않는다 — 접은 화면에서 맞춘 폭이 편 화면·데스크톱 설정을 덮지 않게.
// 쪽 폭 한계는 폭 맞춤 폭의 ZOOM_MIN–ZOOM_MAX 배(최소 160px)다. 넘치면 PDF 영역(#left) 안에서만 가로로 스크롤된다.
const ZOOM_MIN=0.5,ZOOM_MAX=5,ZOOM_STEP=1.2;
function wBounds(fit){const f=Math.max(160,fit),lo=Math.max(160,Math.round(f*ZOOM_MIN)); return [lo,Math.max(lo,Math.round(f*ZOOM_MAX))];}
function setW(w,save){const b=wBounds(fitWidth()); W=Math.round(Math.min(b[1],Math.max(b[0],w))); $$('.pg').forEach(e=>e.style.width=W+'px');
  if(save!==false&&LAYOUT==='wide')savePrefs({w:W}); vecInvalidate();}
function innerW(){const L=$('#left'),cs=getComputedStyle(L); return L.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);}
// 폭 맞춤 폭: compact 는 본문 안쪽 폭, wide 는 #left.clientWidth 에서 48px(좌우 여백)을 뺀 값.
function fitWidth(){return LAYOUT!=='wide'?innerW():$('#left').clientWidth-48;}
// compact 는 늘 화면 폭에 맞춘다(사용자가 −/＋ 를 눌렀으면 그 레이아웃 동안은 그대로). wide 는 예전 그대로.
function autoW(){if(LAYOUT!=='wide'){if(!ZOOMED)setW(innerW(),false);return;}
  if(prefs().w!==undefined)return; const f=$('#left').clientWidth-44-16; setW(f<900?f:900,false);}
// 확대 기준점: (cx,cy) 화면 좌표 아래의 쪽과 그 쪽 안 비율. 점이 쪽 사이 여백이면 세로로 가장 가까운 쪽을 쓴다.
// 좌표가 없으면 PDF 영역 가운데를 쓴다(키보드·버튼).
function zoomAnchor(cx,cy){const L=$('#left'),lr=L.getBoundingClientRect();
  if(cx==null){cx=lr.left+L.clientWidth/2; cy=lr.top+L.clientHeight/2;}
  let best=null,bd=Infinity;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(),d=cy<r.top?r.top-cy:(cy>r.bottom?cy-r.bottom:0);
    if(d<bd){bd=d; best={pg,r};} if(d===0)break;}
  return best?{pg:best.pg,cx,cy,fx:(cx-best.r.left)/best.r.width,fy:(cy-best.r.top)/best.r.height}:null;}
// 기준점의 쪽 안 비율 자리를 화면 좌표 (cx,cy) 로 되돌린다 — 확대해도 포인터 밑의 글자가 그 자리에 남는다.
function zoomRestore(a,cx,cy){if(!a)return; const L=$('#left'),r=a.pg.getBoundingClientRect();
  L.scrollLeft+=r.left+a.fx*r.width-(cx==null?a.cx:cx); L.scrollTop+=r.top+a.fy*r.height-(cy==null?a.cy:cy);}
function zoomTo(w,cx,cy){const a=zoomAnchor(cx,cy); setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(a);}
function zoom(k){zoomTo(W*Math.pow(ZOOM_STEP,k));}
// 폭 맞춤: 보던 쪽·자리(위쪽 기준)를 지키고 가로 스크롤을 처음으로 되돌린다.
function fitW(){const a=topAnchor(),L=$('#left');
  if(LAYOUT!=='wide'){ZOOMED=false; setW(innerW(),false);} else setW(L.clientWidth-48);
  restoreAnchor(a); L.scrollLeft=0;}
function goPage(v){const el=document.getElementById('p'+parseInt(v===undefined?$('#jump').value:v,10)); if(el) el.scrollIntoView({behavior:SMOOTH});}
$('#jump').addEventListener('keydown',e=>{if(e.key==='Enter')goPage();});
$('#m-jump').addEventListener('keydown',e=>{if(e.key==='Enter'){$('#more').close(); goPage($('#m-jump').value);}});

// ------------------------------------------------ 벡터 렌더링(PDF.js) — references/design.md §벡터 렌더링
// 쪽마다 캔버스에 PDF 를 직접 그린다. 백킹 크기 = 쪽 CSS 크기 × devicePixelRatio(× 브라우저 핀치 배율)이고, 앱 확대는
// 쪽 CSS 폭(W)에 이미 들어 있다. 쪽 상자·비율·% 좌표는 PNG 때 그대로라 드래그 frac·마크·pdf_build 가 바뀌지 않는다.
// - 가시 영역 근처(VEC_KEEP)의 쪽만 그리고, 멀어진 쪽의 캔버스는 해제한다(IntersectionObserver).
// - 캔버스 한 장은 VEC_PIX_CAP 픽셀을 넘지 않는다. 넘는 확대에서는 쪽 캔버스를 상한까지 낮추고, 화면에 보이는 부분만
//   원래 해상도로 그린 상세 캔버스(.dt)를 겹친다.
// - 확대가 바뀌면 기존 캔버스를 CSS 로 늘려 보인 채 디바운스해 다시 그린다(깜빡임 없음).
// - pdf.js·PDF 를 못 불러오거나 그리다 실패하면 캔버스를 걷고 PNG <img> 로 돌아간 뒤 상태 칩(#vec-chip)에 알린다.
// 글자 선택 레이어는 넣지 않는다 — 드래그가 영역 선택이라 글자 선택과 다툰다.
const PDFJS_V='__PDFJS_VERSION__';
const VEC_PIX_CAP=16777216, VEC_KEEP='150% 0px', VEC_DT_MARGIN=0.25;
const VEC={lib:null,doc:null,build:null,gen:0,failed:null,io:null,near:new Set(),st:new Map(),cur:null,
  pumping:false,timer:0,stats:[],tFirst:null,tDoc:null,cache:new Map()};
// 여러 문서: 연 PDF 문서 객체를 '문서|빌드' 로 최근 VEC_CACHE_MAX 개까지 들고 있다 — 탭을 되돌리면 다시 받지 않고 바로 그린다.
// 넘치면 가장 오래 안 쓴 것부터 닫는다(워커 메모리). 같은 문서의 옛 빌드는 새 빌드를 열 때 닫는다.
const VEC_CACHE_MAX=3;
function vecCacheKey(k,b){return (k||'')+'|'+(b||'');}
function vecCachePut(key,doc){const c=VEC.cache; c.delete(key); c.set(key,doc);
  const pre=key.split('|')[0]+'|';
  Array.from(c.keys()).forEach(x=>{if(x!==key&&x.startsWith(pre)){const d=c.get(x); c.delete(x); if(d!==VEC.doc)vecClose(d);}});
  while(c.size>VEC_CACHE_MAX){const x=c.keys().next().value,d=c.get(x); c.delete(x); if(d!==VEC.doc&&d!==doc)vecClose(d);}}
function vecCached(doc){for(const d of VEC.cache.values())if(d===doc)return true; return false;}
function vecForget(doc){VEC.cache.forEach((d,x)=>{if(d===doc)VEC.cache.delete(x);});}
window.__pinVec=VEC;   // 실측(Playwright)용 — 캔버스 수·렌더 시간
async function vecBoot(){
  if(!window.IntersectionObserver){vecFail('이 브라우저는 IntersectionObserver 가 없습니다');return;}
  try{VEC.lib=await import('/vendor/pdfjs/pdf.min.mjs?v='+PDFJS_V);
    VEC.lib.GlobalWorkerOptions.workerSrc='/vendor/pdfjs/pdf.worker.min.mjs?v='+PDFJS_V;}
  catch(e){VEC.lib=null; vecFail('pdf.js 를 불러오지 못했습니다',e); return;}
  await vecOpen();
}
// 지금 화면 빌드(META.pages_build)의 PDF 를 연다. 쪽 수가 화면과 다르면 쓰지 않는다(좌표가 어긋난다).
async function vecOpen(){
  if(!VEC.lib||!META)return;
  const gen=++VEC.gen, build=META.pages_build||'', n=META.pages.length, key=vecCacheKey(DOC,build); let doc=VEC.cache.get(key);
  vecCancel();
  if(!doc){
    try{const r=await fetch(dq('/pdf?build='+encodeURIComponent(build)+'&v='+encodeURIComponent(META.built_at||'')));
      if(!r.ok)throw new Error('PDF HTTP '+r.status);
      const data=new Uint8Array(await r.arrayBuffer()); if(gen!==VEC.gen)return;
      doc=await VEC.lib.getDocument({data,isEvalSupported:false,useWasm:false,enableXfa:false}).promise;}
    catch(e){if(gen===VEC.gen)vecFail('PDF 를 벡터로 열지 못했습니다',e); return;}
    if(gen!==VEC.gen){vecClose(doc); return;}
    if(doc.numPages!==n){vecClose(doc); vecFail('PDF 쪽 수('+doc.numPages+')가 화면('+n+')과 다릅니다'); return;}
    vecCachePut(key,doc);
  }else vecCachePut(key,doc);           // 최근에 쓴 것으로 올린다
  if(gen!==VEC.gen)return;
  const old=VEC.doc; VEC.doc=doc; VEC.build=build; VEC.failed=null; VEC.tDoc=performance.now(); $('#vec-chip').hidden=true;
  VEC.st.forEach(s=>{s.stale=true;});
  if(old!==doc&&!vecCached(old))vecClose(old);
  vecSchedule(0);
}
// 문서 하나를 닫는다 — PDFDocumentProxy 에는 destroy 가 없고 loadingTask 가 워커 쪽 자원까지 푼다.
function vecClose(doc){if(!doc)return; try{doc.loadingTask.destroy();}catch(e){}}
function vecFail(msg,err){
  VEC.failed=msg; VEC.gen++; vecCancel(); vecReleaseAll();
  vecForget(VEC.doc); vecClose(VEC.doc); VEC.doc=null;
  const c=$('#vec-chip'); c.hidden=false;
  c.dataset.tip='PDF를 벡터로 그리지 못해 이미지(PNG)로 보입니다 — '+msg+(err&&err.message?' ('+String(err.message).slice(0,100)+')':'')+'. 확대하면 흐릴 수 있습니다';
}
function vecState(n){let s=VEC.st.get(n); if(!s){s={base:null,bw:0,bh:0,dt:null,reg:null,dtCw:0,dtK:0,stale:false}; VEC.st.set(n,s);} return s;}
function vecDrop(cv){if(!cv)return; cv.width=0; cv.height=0; cv.remove();}   // 0 으로 줄여야 사파리도 메모리를 바로 돌려준다
function vecRelease(n){if(VEC.cur&&VEC.cur.n===n)vecCancel(); const s=VEC.st.get(n); if(!s)return;
  vecDrop(s.base); vecDrop(s.dt); VEC.st.delete(n);
  const pg=document.getElementById('p'+n); if(pg)pg.classList.remove('drawn');}
function vecReleaseAll(){vecCancel(); Array.from(VEC.st.keys()).forEach(vecRelease);}
function vecCancel(){const c=VEC.cur; VEC.cur=null; if(c&&c.task){try{c.task.cancel();}catch(e){}}}
function vecObserve(){if(VEC.io)VEC.io.disconnect(); vecReleaseAll(); VEC.near.clear(); if(!window.IntersectionObserver)return;
  VEC.io=new IntersectionObserver(es=>{es.forEach(en=>{const n=+en.target.dataset.page;
      if(en.isIntersecting)VEC.near.add(n); else {VEC.near.delete(n); vecRelease(n);}}); vecSchedule(0);},
    {root:$('#left'),rootMargin:VEC_KEEP});
  $$('.pg').forEach(pg=>VEC.io.observe(pg));}
function vecSchedule(ms){clearTimeout(VEC.timer); VEC.timer=setTimeout(vecPump,ms||0);}
// 확대·창 크기·DPR 이 바뀌었다 — 그리던 것은 버리고(옛 크기) 잠시 뒤 다시 그린다. 그동안은 옛 캔버스가 늘어나 보인다.
function vecInvalidate(){if(!VEC.doc)return; vecCancel(); vecSchedule(150);}
function vecK(){const vv=window.visualViewport; return (window.devicePixelRatio||1)*Math.max(1,(vv&&vv.scale)||1);}
// 쪽 캔버스의 백킹 크기. 상한을 넘으면 같은 비율로 줄이고 capped 로 표시한다(상세 캔버스가 보이는 부분을 채운다).
function vecTarget(cw,ch,k,cap){let bw=Math.round(cw*k),bh=Math.round(ch*k),capped=false;
  if(bw*bh>cap){const f=Math.sqrt(cap/(bw*bh)); bw=Math.max(1,Math.floor(bw*f)); bh=Math.max(1,Math.floor(bh*f)); capped=true;}
  return {cw,ch,k,bw,bh,capped};}
function vecTargetOf(pg){const cw=pg.clientWidth,ch=pg.clientHeight; return cw&&ch?vecTarget(cw,ch,vecK(),VEC_PIX_CAP):null;}
// 쪽 안에서 화면에 보이는 부분(쪽 CSS px). margin 은 화면 크기 대비 덧붙일 여유(상세 캔버스를 조금 넓게 그린다).
function vecVisible(pg,margin){const L=$('#left'),lr=L.getBoundingClientRect(),r=pg.getBoundingClientRect();
  const ox=r.left+pg.clientLeft,oy=r.top+pg.clientTop,cw=pg.clientWidth,ch=pg.clientHeight;
  const vx0=lr.left+L.clientLeft,vy0=lr.top+L.clientTop,vw=L.clientWidth,vh=L.clientHeight,mx=vw*margin,my=vh*margin;
  const x0=Math.max(0,vx0-mx-ox),y0=Math.max(0,vy0-my-oy),x1=Math.min(cw,vx0+vw+mx-ox),y1=Math.min(ch,vy0+vh+my-oy);
  return x1>x0&&y1>y0?{x:x0,y:y0,w:x1-x0,h:y1-y0,cw,ch}:null;}
function vecCovers(reg,v){return !!reg&&reg.x<=v.x/v.cw+1e-6&&reg.y<=v.y/v.ch+1e-6&&
  reg.x+reg.w>=(v.x+v.w)/v.cw-1e-6&&reg.y+reg.h>=(v.y+v.h)/v.ch-1e-6;}
// 다음에 그릴 것 하나: 화면 안의 쪽 먼저(가운데에 가까운 순), 쪽 캔버스 → 상세 캔버스 순.
function vecNextJob(){
  if(!VEC.doc)return null;
  const L=$('#left'),lr=L.getBoundingClientRect(),top=lr.top,bot=lr.top+L.clientHeight,cy=(top+bot)/2;
  const list=[];
  VEC.near.forEach(n=>{const pg=document.getElementById('p'+n); if(!pg)return; const r=pg.getBoundingClientRect();
    list.push({n,pg,vis:r.bottom>top&&r.top<bot,d:Math.abs((r.top+r.bottom)/2-cy)});});
  list.sort((a,b)=>(b.vis-a.vis)||(a.d-b.d));
  for(const it of list){const s=vecState(it.n),t=vecTargetOf(it.pg); if(!t)continue;
    if(!s.base||s.stale||s.bw!==t.bw||s.bh!==t.bh)return {n:it.n,kind:'base'};
    if(t.capped&&it.vis){const v=vecVisible(it.pg,0);
      if(v&&(!s.dt||s.dtCw!==t.cw||s.dtK!==t.k||!vecCovers(s.reg,v)))return {n:it.n,kind:'dt'};}
    else if(s.dt){vecDrop(s.dt); s.dt=null; s.reg=null;}}
  return null;
}
async function vecPump(){
  if(VEC.pumping||!VEC.doc)return; VEC.pumping=true;
  try{for(let i=0;i<400;i++){const job=vecNextJob(); if(!job)break; await vecRun(job);}}
  finally{VEC.pumping=false;}
}
async function vecRun(job){
  const n=job.n,pg=document.getElementById('p'+n),doc=VEC.doc,gen=VEC.gen; if(!pg||!doc)return;
  let page; try{page=await doc.getPage(n);}catch(e){if(gen===VEC.gen)vecFail('쪽을 읽지 못했습니다',e); return;}
  if(gen!==VEC.gen||!VEC.near.has(n)||!document.contains(pg))return;
  const t=vecTargetOf(pg); if(!t)return;
  const vp1=page.getViewport({scale:1}),cv=document.createElement('canvas'); let scale,tf,reg=null;
  // 가로·세로를 따로 맞춘다(transform 의 세로 배율) — 쪽 상자 비율은 PNG 픽셀 수에서 왔고 PDF 쪽 비율과 0.1% 안쪽으로 다르다.
  // PNG 도 쪽을 그 상자에 꽉 채워 그렸으므로, 이렇게 해야 캔버스의 글자가 PNG 때와 같은 % 자리에 온다.
  if(job.kind==='base'){cv.width=t.bw; cv.height=t.bh; scale=t.bw/vp1.width; tf=[1,0,0,t.bh/(vp1.height*scale),0,0];}
  else{const v=vecVisible(pg,VEC_DT_MARGIN); if(!v)return; let k=t.k;
    if(v.w*v.h*k*k>VEC_PIX_CAP)k=Math.sqrt(VEC_PIX_CAP/(v.w*v.h));
    scale=t.cw*k/vp1.width; cv.width=Math.max(1,Math.round(v.w*k)); cv.height=Math.max(1,Math.round(v.h*k));
    tf=[1,0,0,t.ch*k/(vp1.height*scale),-v.x*k,-v.y*k];
    reg={x:v.x/t.cw,y:v.y/t.ch,w:v.w/t.cw,h:v.h/t.ch};}
  const ctx=cv.getContext('2d',{alpha:false}),t0=performance.now();
  const task=page.render({canvasContext:ctx,viewport:page.getViewport({scale}),transform:tf});
  VEC.cur={n,task};
  try{await task.promise;}
  catch(e){if(VEC.cur&&VEC.cur.task===task)VEC.cur=null; vecDrop(cv);
    if(e&&e.name==='RenderingCancelledException')return;
    if(gen===VEC.gen)vecFail('쪽을 그리지 못했습니다',e); return;}
  if(VEC.cur&&VEC.cur.task===task)VEC.cur=null;
  const t2=gen===VEC.gen&&VEC.near.has(n)&&document.contains(pg)?vecTargetOf(pg):null;
  if(!t2||t2.cw!==t.cw||t2.ch!==t.ch||t2.k!==t.k){vecDrop(cv); return;}   // 그리는 사이 확대·창 크기가 바뀌었다
  VEC.stats.push({n,kind:job.kind,ms:Math.round(performance.now()-t0),w:cv.width,h:cv.height});
  if(VEC.stats.length>200)VEC.stats.splice(0,VEC.stats.length-200);
  const s=vecState(n);
  if(job.kind==='base'){vecDrop(s.base); s.base=cv; s.bw=t.bw; s.bh=t.bh; s.stale=false; cv.className='vb';
    pg.prepend(cv); pg.classList.add('drawn'); if(VEC.tFirst===null)VEC.tFirst=performance.now();}
  else{vecDrop(s.dt); s.dt=cv; s.reg=reg; s.dtCw=t.cw; s.dtK=t.k; cv.className='dt';
    Object.assign(cv.style,{left:reg.x*100+'%',top:reg.y*100+'%',width:reg.w*100+'%',height:reg.h*100+'%'});
    if(s.base)s.base.after(cv); else pg.prepend(cv);}
}
$('#left').addEventListener('scroll',()=>{if(VEC.doc)vecSchedule(120);},{passive:true});
// 브라우저 확대(PDF 밖의 Ctrl+휠 등)·다른 화면으로 창을 옮기면 devicePixelRatio 가 바뀐다 — 그 배율로 다시 그린다.
(function watchDpr(){if(!window.matchMedia)return;
  matchMedia('(resolution: '+(window.devicePixelRatio||1)+'dppx)').addEventListener('change',()=>{vecInvalidate(); watchDpr();},{once:true});})();
if(window.visualViewport)visualViewport.addEventListener('resize',()=>{if(VEC.doc)vecSchedule(300);});

// ------------------------------------------------ PDF 영역 전용 확대 — references/design.md §PDF 영역 전용 확대
// 브라우저 확대는 사이드바·도구 줄까지 키운다. PDF 영역의 확대 입력을 가로채 쪽 폭(W)만 바꾼다.
// - 데스크톱: #left 위의 Ctrl(⌘)+휠. 트랙패드 핀치도 크롬·파이어폭스에서는 ctrlKey 가 붙은 wheel 로 온다. 포인터 기준.
// - 사파리 트랙패드 핀치: gesturestart/gesturechange(e.scale).
// - 키보드 Ctrl(⌘) + = / + / − / 0 → 확대·축소·폭 맞춤(입력 칸에 포커스가 있으면 가로채지 않는다 — 키 처리기 참고).
// - 터치: #left 는 touch-action:pan-x pan-y 라 브라우저 핀치가 없다. 두 손가락 거리 비율로 W 를 바꾸고, 두 손가락
//   가운데 점 밑의 자리를 손가락을 따라 옮긴다(확대하며 끌기). 선택 모드의 쪽은 touch-action:none 이라 같은 길로 온다.
function zoomKey(e){const k=e.key,c=e.code;
  if(k==='='||k==='+'||c==='Equal'||c==='NumpadAdd')return 'in';
  if(k==='-'||k==='_'||c==='Minus'||c==='NumpadSubtract')return 'out';
  if(k==='0'||c==='Digit0'||c==='Numpad0')return 'fit';
  return null;}
// 휠 한 번의 배율. 마우스 휠 한 칸(|dy|≥50 픽셀 또는 줄 단위)은 버튼 한 번과 같은 ZOOM_STEP, 트랙패드 핀치의 잘게 나뉜 dy 는
// exp(-dy/100) 로 이어 붙인다 — 크롬이 핀치 배율을 휠로 바꿀 때 쓰는 식의 역이라 손가락 벌린 만큼 커진다.
// 한 이벤트가 버튼 한 칸(ZOOM_STEP ≈ exp(0.18))을 넘지 않게 dy 를 ±18 로 자른다.
function wheelFactor(dy,mode){if(!dy)return 1;
  if(mode===1||mode===2||Math.abs(dy)>=50)return dy<0?ZOOM_STEP:1/ZOOM_STEP;
  return Math.exp(-Math.max(-18,Math.min(18,dy))/100);}
(function(){const L=$('#left'); let acc=1,pt=null,raf=0,G=null,TP=null;
  const flush=()=>{raf=0; if(acc===1)return; const f=acc; acc=1; zoomTo(W*f,pt[0],pt[1]);};
  L.addEventListener('wheel',e=>{if(!(e.ctrlKey||e.metaKey))return; e.preventDefault();
    acc*=wheelFactor(e.deltaY,e.deltaMode); pt=[e.clientX,e.clientY]; if(!raf)raf=requestAnimationFrame(flush);},{passive:false});
  L.addEventListener('gesturestart',e=>{e.preventDefault(); if(!TP)G={w:W};},{passive:false});
  L.addEventListener('gesturechange',e=>{e.preventDefault(); if(G&&!TP&&e.scale>0)zoomTo(G.w*e.scale,e.clientX,e.clientY);},{passive:false});
  L.addEventListener('gestureend',e=>{e.preventDefault(); G=null;},{passive:false});
  const mid=(a,b)=>[(a.clientX+b.clientX)/2,(a.clientY+b.clientY)/2];
  const dist=(a,b)=>Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)||1;
  let tr=0,last=null;
  const apply=()=>{tr=0; if(!TP||!last)return; const w=TP.w*last.d/TP.d;
    setW(w); if(LAYOUT!=='wide')ZOOMED=true; zoomRestore(TP.a,last.m[0],last.m[1]);};
  L.addEventListener('touchstart',e=>{if(e.touches.length!==2){if(e.touches.length>2)TP=null; return;}
    if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1],m=mid(a,b); cancelDrag(); cancelLP();
    TP={d:dist(a,b),w:W,a:zoomAnchor(m[0],m[1])}; last={d:TP.d,m};},{passive:false});
  L.addEventListener('touchmove',e=>{if(!TP||e.touches.length!==2)return; if(e.cancelable)e.preventDefault();
    const a=e.touches[0],b=e.touches[1]; last={d:dist(a,b),m:mid(a,b)}; if(!tr)tr=requestAnimationFrame(apply);},{passive:false});
  const end=e=>{if(TP&&e.touches.length<2){if(tr){cancelAnimationFrame(tr); apply();} TP=null; last=null;}};
  L.addEventListener('touchend',end); L.addEventListener('touchcancel',end);
})();

// ------------------------------------------------ 화면 폭별 레이아웃(모바일)
// wide: 지금까지의 오른쪽 사이드바(폭 조절 포함). mid: 700px 초과 1100px 미만의 터치 화면(편 폴더블) — 좁은 사이드
// 패널, 접으면 오른쪽 아래 도구 줄만 남는다. narrow: 700px 이하(접은 폴더블·휴대폰) — 하단 시트, 기본은 접힘.
// 접기·펴기로 폭이 도중에 바뀌면 레이아웃을 다시 고르고, 보던 자리(topAnchor)를 지킨 채 쪽 폭을 다시 맞춘다.
// 마크·선택 상자는 쪽 안의 % 좌표라 쪽 폭만 맞으면 저절로 제자리다.
function layoutFor(){const w=innerWidth; if(w<=700)return 'narrow'; if(w<1100&&MQ_COARSE.matches)return 'mid'; return 'wide';}
function applyLayout(){const L=layoutFor(); if(L===LAYOUT)return false;
  LAYOUT=L; const b=document.body; ZOOMED=false;
  ['wide','mid','narrow'].forEach(k=>b.classList.toggle('lay-'+k,k===L)); b.classList.toggle('compact',L!=='wide');
  SIDE_OPEN=L==='wide'?true:(L==='mid'?!prefs().midClosed:false);
  if(L!=='wide'&&!REPICK&&(CUR||EDIT||!$('#composer').hidden))SIDE_OPEN=true;   // 쓰던 메모·편집은 접힌 채로 숨기지 않는다
  applySide(); stickTop(); return true;}
function applySide(){const open=LAYOUT==='wide'||SIDE_OPEN;
  document.body.classList.toggle('side-open',open);
  const btn=$('#btn-side'); btn.setAttribute('aria-expanded',String(open));
  $('#side-arrow').innerHTML=ic(LAYOUT==='narrow'?(open?'chevron-down':'chevron-up'):(open?'chevron-right':'chevron-left'));
  btn.setAttribute('aria-label',(open?'패널 접기':'패널 펴기')+' · 열린 핀 '+PINS.length);}
// remember: mid 에서 사용자가 직접 접고 편 것만 기억한다(narrow 는 늘 접힌 채 시작).
function setSide(open,remember){if(LAYOUT==='wide')return; open=!!open;
  if(remember&&LAYOUT==='mid')savePrefs({midClosed:!open});
  if(SIDE_OPEN===open)return; SIDE_OPEN=open; applySide(); hideTip();}
function relayout(){const a=topAnchor(); applyLayout(); applySideWidth(); autoW(); restoreAnchor(a); hideTip(); if(CUR)renderComposer(); stickTop();}
// 목록 구획 머리(sticky)가 붙을 높이. compact 에서는 #right 가 스크롤 상자이고 그 위에 도구 줄(#bar1, narrow 는 시트 손잡이 아래)이
// 먼저 붙어 있으니 그 아래에 붙인다. wide 는 #list 자체가 스크롤 상자라 0 이다.
function stickTop(){let t=0; const b=$('#bar1');
  if(LAYOUT!=='wide'&&b){const cs=getComputedStyle(b); if(cs.position==='sticky')t=Math.round((parseFloat(cs.top)||0)+b.offsetHeight);}
  document.documentElement.style.setProperty('--stick-top',t+'px');}
if(window.ResizeObserver)new ResizeObserver(()=>stickTop()).observe($('#bar1'));
let RELAY=0;
function scheduleRelayout(){if(RELAY)return; RELAY=requestAnimationFrame(()=>{RELAY=0; if(META)relayout(); else applyLayout();});}
window.addEventListener('resize',scheduleRelayout);
MQ_COARSE.addEventListener('change',scheduleRelayout);
// 패널을 펴고 접어 #left 폭만 바뀌어도(compact) 쪽 폭을 다시 맞춘다. 콜백에서 바로 레이아웃을 바꾸지 않고
// 다음 프레임으로 미룬다(ResizeObserver 루프 경고 방지). wide 는 예전처럼 창 크기 변화에만 반응한다.
// 손잡이를 끄는 동안(body.resizing)은 다시 맞추지 않는다 — 손을 떼면 setSideWidth 가 한 번 맞춘다.
if(window.ResizeObserver)new ResizeObserver(()=>{if(LAYOUT&&LAYOUT!=='wide'&&!document.body.classList.contains('resizing'))scheduleRelayout();}).observe($('#left'));

// 가상 키보드: 크롬 안드로이드는 viewport meta 의 interactive-widget=resizes-content 로 레이아웃 자체가 줄어든다.
// 그 값을 모르는 브라우저는 visualViewport 로 키보드 높이(--kb)를 재서 화면 전체를 그만큼 올린다. 핀치 확대로 줄어든
// visualViewport 는 키보드가 아니다(scale 을 곱해 되돌린다). 입력 칸이 포커스돼 있으면 보이는 자리로 끌어온다.
function onViewport(){const vv=window.visualViewport; if(!vv)return;
  const lh=document.documentElement.clientHeight;
  let kb=Math.round(lh-vv.height*vv.scale); if(!(kb>=80)||!MQ_COARSE.matches)kb=0;
  const R=document.documentElement.style, prev=R.getPropertyValue('--kb');
  R.setProperty('--kb',kb+'px'); R.setProperty('--vvh',(lh-kb)+'px');
  const a=document.activeElement;
  if(prev!==kb+'px'&&a&&(a.tagName==='TEXTAREA'||a.tagName==='INPUT')&&$('#right').contains(a))
    requestAnimationFrame(()=>a.scrollIntoView({block:'center'}));}
if(window.visualViewport){visualViewport.addEventListener('resize',onViewport); visualViewport.addEventListener('scroll',onViewport);}
document.addEventListener('focusin',e=>{const t=e.target;
  if(LAYOUT!=='wide'&&t&&t.tagName==='TEXTAREA'&&$('#right').contains(t))setTimeout(()=>t.scrollIntoView({block:'center'}),350);});

// 처음 한 번만 뜨는 안내(localStorage pinPrefs.coach 에 본 것을 기억한다).
let COACH_T=null;
function coach(key,text){const seen=Object.assign({},prefs().coach||{}); if(seen[key])return; seen[key]=1; savePrefs({coach:seen});
  $('#coach-t').textContent=text; $('#coach').hidden=false; clearTimeout(COACH_T); COACH_T=setTimeout(()=>{$('#coach').hidden=true;},8000);}
function setSelMode(on){SELMODE=!!on; document.body.classList.toggle('selmode',SELMODE);
  const b=$('#btn-select'); b.setAttribute('aria-pressed',String(SELMODE)); b.textContent=SELMODE?'선택 중':'선택';
  if(SELMODE)coach('sel','끌어서 고칠 곳을 고르세요 · 탭하면 그 문단 · 두 손가락으로 확대');}
function openMore(){const d=$('#more'); if(d.open)return; hideTip(); renderSizeSeg(); d.showModal();}
// [⋯] 에서 닫힌 핀·삭제한 핀을 펼치면 패널을 펴고 그 목록으로 스크롤한다.
function revealList(sel,shown){if(!shown)return; setSide(true); requestAnimationFrame(()=>{const t=$(sel); if(t)t.scrollIntoView({block:'start'});});}
// 대화상자 밖(배경)을 누르면 닫는다 — dialog 자신이 target 인 click 중 상자 사각형 밖인 것만.
$('#more').addEventListener('click',e=>{const d=$('#more'); if(e.target!==d)return; const r=d.getBoundingClientRect();
  if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();});

// 패널 폭 손잡이 — 마우스·터치·펜 모두 Pointer Events 한 경로(데스크톱의 옛 mousedown 구현을 대신한다). 손잡이는
// touch-action:none 이라 끄는 동안 브라우저 스크롤과 다투지 않고, setPointerCapture 로 손잡이 밖까지 따라간다.
// 끄는 동안은 폭만 바꾸고(본문 쪽 폭은 그대로), 손을 떼면 한 번 relayout 한다. 탭(마우스는 두 번 클릭)은 단계 순환,
// ←/→ 는 16px, Home/End 는 한계, Enter/Space 는 단계 순환이다.
(function(){const g=$('#grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT==='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,x:e.clientX,w:curSideW(),moved:false,mouse:e.pointerType==='mouse'};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dx=D.x-e.clientX;
    if(!D.moved&&Math.abs(dx)<4)return; D.moved=true; const b=sideBounds(LAYOUT,innerWidth); showSideW(clampSide(D.w+dx,b),b);});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySideWidth(); relayout(); return;}
    if(d.moved)setSideWidth(curSideW()); else if(!d.mouse&&Date.now()>=SWALLOW_CLICK)cycleSideWidth();};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('dblclick',()=>cycleSideWidth());
  g.addEventListener('keydown',e=>{if(LAYOUT==='narrow')return; const b=sideBounds(LAYOUT,innerWidth),w=curSideW();
    const k={ArrowLeft:w+16,ArrowRight:w-16,Home:b.max,End:b.min}[e.key];
    if(k!==undefined){e.preventDefault(); setSideWidth(k);} else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSideWidth();}});
})();
// 시트 높이 손잡이(narrow) — 위로 끌면 높아지고(접힌 시트는 펴진다), 화면 25% 아래로 내려놓으면 접힌다. 탭은 단계 순환.
(function(){const g=$('#sheet-grip'); let D=null;
  g.addEventListener('pointerdown',e=>{if(LAYOUT!=='narrow'||(e.pointerType==='mouse'&&e.button!==0))return;
    e.preventDefault(); D={id:e.pointerId,y:e.clientY,h:$('#right').getBoundingClientRect().height,moved:false};
    try{g.setPointerCapture(e.pointerId);}catch(_){}
    g.classList.add('on'); document.body.classList.add('resizing');});
  g.addEventListener('pointermove',e=>{if(!D||e.pointerId!==D.id)return; const dy=D.y-e.clientY;
    if(!D.moved&&Math.abs(dy)<6)return; D.moved=true;
    if(!SIDE_OPEN&&dy>0)setSide(true);
    if(SIDE_OPEN)document.documentElement.style.setProperty('--sheet-f',String(Math.max(0.12,(D.h+dy)/innerHeight)));});
  const end=e=>{if(!D||e.pointerId!==D.id)return; const d=D; D=null; g.classList.remove('on'); document.body.classList.remove('resizing');
    if(e.type==='pointercancel'){applySheet(); return;}
    if(!d.moved){if(Date.now()<SWALLOW_CLICK)return; if(!SIDE_OPEN)setSide(true,true); else cycleSheet(); return;}
    if(!SIDE_OPEN){applySheet(); return;}
    const f=$('#right').getBoundingClientRect().height/innerHeight;
    if(f<SHEET_CLOSE_F){applySheet(); setSide(false,true); return;}
    setSheetF(f);};
  g.addEventListener('pointerup',end); g.addEventListener('pointercancel',end);
  g.addEventListener('keydown',e=>{if(LAYOUT!=='narrow')return; const f=sheetF();
    if(e.key==='ArrowUp'){e.preventDefault(); setSheetF(f+0.05);} else if(e.key==='ArrowDown'){e.preventDefault(); setSheetF(f-0.05);}
    else if(e.key==='Enter'||e.key===' '){e.preventDefault(); cycleSheet();}});
})();

// ------------------------------------------------ 드래그 선택(마우스·터치·펜 — Pointer Events 한 경로)
// 마우스: 예전 그대로 누르고 끌면 사각형. 터치·펜: 선택 모드(SELMODE)일 때만 끌면 사각형이고 탭하면 빠른 선택,
// 선택 모드가 아니면 스크롤·핀치 확대가 그대로 되고 길게 누르면 빠른 선택이다. 선택 모드에서는 쪽에만
// touch-action:none 을 건다(한 손가락 끌기는 이 코드가, 두 손가락은 앱 확대 — §PDF 영역 전용 확대 — 가 가진다).
// 좌표는 clientX/Y 와 getBoundingClientRect 를 같은 기준(레이아웃 뷰포트)으로 나눈 쪽 안 비율이라 핀치 확대 중에도 맞다.
let DRAG=null,LP=null;
const c01=v=>Math.min(1,Math.max(0,v));
const LONGPRESS_MS=450,TAP_SLOP=8,QUICK_W=0.07,QUICK_H=0.006;
function fracAt(pg,cx,cy){const r=pg.getBoundingClientRect(); return [c01((cx-r.left)/r.width),c01((cy-r.top)/r.height)];}
function newBox(pg){const b=document.createElement('div'); b.className='sel'; pg.appendChild(b); return b;}
function drawBox(box,sx,sy,x,y){Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
  width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'});}
function cancelDrag(){if(DRAG&&DRAG.box)DRAG.box.remove(); DRAG=null;}
function cancelLP(){if(LP){clearTimeout(LP.t); LP=null;}}
// 예전 mousedown 처럼 쪽 위 마우스 누름의 기본 동작(포커스 이동·이미지 끌기)을 막는다 — 메모 칸 포커스가 유지된다.
$('#doc').addEventListener('mousedown',e=>{if(e.button===0&&e.target.closest('.pg'))e.preventDefault();});
$('#doc').addEventListener('pointerdown',e=>{
  if(e.target.closest('.mark b'))return;
  if(!e.isPrimary){cancelDrag(); cancelLP(); return;}   // 두 번째 손가락 = 핀치 — 그리던 상자를 버린다
  const pg=e.target.closest('.pg'); if(!pg)return;
  const mouse=e.pointerType==='mouse';
  if(mouse&&e.button!==0)return;
  if(mouse||SELMODE){const [sx,sy]=fracAt(pg,e.clientX,e.clientY);
    DRAG={pg,sx,sy,id:e.pointerId,mouse,cx:e.clientX,cy:e.clientY,box:mouse?newBox(pg):null};
    if(!mouse){try{pg.setPointerCapture(e.pointerId);}catch(_){}}
    return;}
  cancelLP();
  LP={id:e.pointerId,pg,cx:e.clientX,cy:e.clientY,t:setTimeout(()=>{const L=LP; LP=null; if(L)quickPick(L.pg,L.cx,L.cy);},LONGPRESS_MS)};
});
window.addEventListener('pointermove',e=>{
  if(LP&&e.pointerId===LP.id&&Math.hypot(e.clientX-LP.cx,e.clientY-LP.cy)>10)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  if(!DRAG.box){if(Math.hypot(e.clientX-DRAG.cx,e.clientY-DRAG.cy)<TAP_SLOP)return; DRAG.box=newBox(DRAG.pg);}
  const [x,y]=fracAt(DRAG.pg,e.clientX,e.clientY); drawBox(DRAG.box,DRAG.sx,DRAG.sy,x,y);});
window.addEventListener('pointerup',e=>{
  if(LP&&e.pointerId===LP.id)cancelLP();
  if(!DRAG||e.pointerId!==DRAG.id)return;
  const D=DRAG; DRAG=null;
  if(!D.box){quickPick(D.pg,e.clientX,e.clientY);return;}   // 선택 모드의 탭 = 빠른 선택
  const [x,y]=fracAt(D.pg,e.clientX,e.clientY); finishRect(D.pg,D.box,D.sx,D.sy,x,y);});
window.addEventListener('pointercancel',e=>{if(LP&&e.pointerId===LP.id)cancelLP(); if(DRAG&&e.pointerId===DRAG.id)cancelDrag();});
// 빠른 선택: 누른 점 둘레의 작은 상자(쪽 폭 ±7%, 높이 ±0.6% ≈ 한 줄)로 기존 /api/pick 을 부른다. 서버의 기본 단계가
// 본문이면 '문단', 그림·표 안이면 '환경'이라 그대로 쓰면 되고, 범위 사다리로 넓히고 좁힌다.
function quickPick(pg,cx,cy){const [x,y]=fracAt(pg,cx,cy);
  finishRect(pg,newBox(pg),c01(x-QUICK_W),c01(y-QUICK_H),c01(x+QUICK_W),c01(y+QUICK_H));}
function finishRect(pg,box,sx,sy,x,y){
  const w=Math.abs(x-sx),h=Math.abs(y-sy);
  if(w<0.004&&h<0.004){box.remove();return;}
  drawBox(box,sx,sy,x,y);
  box.classList.add('pending');
  if(REPICK){ if(REPICK.box)REPICK.box.remove(); REPICK.box=box; box.innerHTML='<i>새 위치</i>'; }
  else { if(PENDING)PENDING.remove(); PENDING=box; box.innerHTML='<i>새 핀</i>'; }
  const page=+pg.dataset.page,p=META.pages[page-1];
  pick({page,x0:Math.min(sx,x)*p.pt_w,y0:Math.min(sy,y)*p.pt_h,x1:Math.max(sx,x)*p.pt_w,y1:Math.max(sy,y)*p.pt_h,
    frac:[Math.min(sx,x),Math.min(sy,y),w,h],pdf_build:META.pages_build||undefined,doc:DOC||undefined});}
// 시트·패널이 선택 상자를 가리면 상자가 보이는 곳까지 본문을 올린다(compact 전용).
function revealBox(box){if(!box||LAYOUT==='wide'||!document.contains(box))return;
  const L=$('#left'),lr=L.getBoundingClientRect(),br=box.getBoundingClientRect();
  let bottom=lr.bottom; if(LAYOUT==='narrow'&&SIDE_OPEN)bottom=Math.min(bottom,$('#right').getBoundingClientRect().top);
  const top=lr.top+28; if(br.top>=top&&br.bottom<=bottom-8)return;
  L.scrollTop+=br.top-top-Math.max(0,(bottom-top-br.height)/3);}

// ------------------------------------------------ 범위 단계
function lvOf(obj,key){return (obj.levels||[]).find(l=>l.level===key||(l.merged||[]).includes(key));}
function kindFor(scope,env){if(!scope)return null; if(scope.startsWith('env'))return 'env:'+(env||'?');
  return scope==='para'?'paragraph':'lines';}
function scopeLabel(o){const lv=o.scope&&lvOf(o,o.scope); if(lv)return lv.label; if(o.scope==='lines')return '줄 직접 지정';
  return ({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일',lines:'줄'})[o.kind]||o.kind||'';}
// 지금 범위와 맞는 단계를 눌린 상태로 보인다. scope 가 있으면 그 단계(범위도 같을 때), 없으면 lo/hi 가 같은 첫 단계
// (편집 카드에서는 '지금 범위').
function curLevel(o){const ls=o.levels||[];
  const s=o.scope&&lvOf(o,o.scope); if(s&&s.lo===o.lo&&s.hi===o.hi)return s;
  return ls.find(l=>l.lo===o.lo&&l.hi===o.hi)||null;}
// 줄 범위 표기: 한 줄이면 'L159', 여러 줄이면 'L155-L173'(복사·pins.md 형식 'L159-L159' 는 그대로 둔다).
function rng(lo,hi){return 'L'+lo+(hi!==lo?'-L'+hi:'');}
// 분절 컨트롤 칸 이름은 짧게 — '환경 abstract' → 'abstract'. 같은 환경 이름이 둘 이상이면 '(바깥)' 을 남겨 가른다.
// 줄 범위는 칸에서 빼고 설명(data-tip)·aria-label 과 위치 한 줄에 둔다.
function levelName(lv,all){if(!lv.env)return lv.label;
  const dup=(all||[]).filter(o=>o.env===lv.env).length>1; return dup?String(lv.label).replace(/^환경 /,''):lv.env;}
function levelBtns(o,isEdit){const cur=curLevel(o),ls=o.levels||[]; return ls.map(lv=>{const on=lv===cur;
  const tip=isEdit&&lv.level==='raw'?T.cur:(lv.level.startsWith('env')?T.env:T[lv.level]);
  const label=isEdit&&lv.level==='raw'?'지금 범위':levelName(lv,ls);
  return '<button class="'+(on?'on':'')+'" data-act="level" data-level="'+esc(lv.level)+'" aria-pressed="'+on+'" aria-label="'+
    esc(label+' '+rng(lv.lo,lv.hi)+' · '+lv.n+'줄')+'" data-tip="'+esc(rng(lv.lo,lv.hi)+' · '+tip)+'">'+
    esc(label)+' <span class="k'+(lv.n>50?' wn':'')+'">· '+lv.n+'줄</span></button>';}).join('');}
// 가로로 넘친 분절 컨트롤에서 고른 칸이 보이게 한다(세로 스크롤은 건드리지 않는다).
function segReveal(seg){const on=seg&&seg.querySelector('.on'); if(!on)return;
  const l=on.offsetLeft,r=l+on.offsetWidth;
  if(l<seg.scrollLeft)seg.scrollLeft=Math.max(0,l-4); else if(r>seg.scrollLeft+seg.clientWidth)seg.scrollLeft=r-seg.clientWidth+4;}
function useLevel(o,key){const lv=lvOf(o,key); if(!lv)return; o.lo=lv.lo;o.hi=lv.hi;o.scope=lv.level;o.env=lv.env||null;o.snippet=lv.snippet;}
function nudge(o,dir){let lo=o.lo,hi=o.hi; const max=o.n_lines||hi+1;
  if(dir==='up-grow')lo=Math.max(1,lo-1); else if(dir==='up-shrink')lo=Math.min(hi,lo+1);
  else if(dir==='down-grow')hi=Math.min(max,hi+1); else if(dir==='down-shrink')hi=Math.max(lo,hi-1);
  if(lo===o.lo&&hi===o.hi)return false; o.lo=lo;o.hi=hi;o.scope='lines';o.env=null;return true;}
let snipT=null;
function refetchSnip(o,after){clearTimeout(snipT); snipT=setTimeout(async()=>{
  try{const {data}=await api(dq('/api/snippet?file='+encodeURIComponent(o.file)+'&lo='+o.lo+'&hi='+o.hi,o.doc),{what:'원문 읽기'});
    if(data.lo===o.lo&&data.hi===o.hi){o.snippet=data.snippet;after();}}catch(e){}},250);}
function snipText(text,open){const ls=String(text||'').split('\n');
  return (open||ls.length<=8)?ls.join('\n'):ls.slice(0,8).join('\n')+'\n      … '+(ls.length-8)+'줄 접힘';}
// 위치 일치율 배지: 90% 이상이면 숨긴다(믿어도 되는 자리에 숫자를 달면 소음이다). 낮으면 '위치 불확실', 30% 미만은 경고 색.
// 찾은 방법·일치율·무엇을 확인할지는 설명에 둔다('일치 100%' 만으로는 뜻을 알 수 없었다). 작성 패널·카드가 같이 쓴다.
const VIA_HIDE=90,VIA_WARN=30;
function viaTag(p){if(!p.via)return null; const pct=Math.round((+p.score||0)*100);
  if(pct>=VIA_HIDE)return null; const low=pct<VIA_WARN;
  const how=p.via==='synctex'?'좌표로 찾음':(p.via==='text'?'글자로 찾음':'찾은 방법: '+p.via);
  const why=p.via==='text'?T.text:T.synctex;
  return {t:'위치 불확실',tip:how+' · 일치 '+pct+'% — '+why+(low?' 많이 어긋났을 수 있습니다.':''),low};}

// ------------------------------------------------ composer
function setBusy(on){$('#c-spin').hidden=!on; $('#c-body').classList.toggle('busy',on);}
async function pick(r){
  const seq=++PICKSEQ,rp=REPICK;
  if(rp){banner('<span>되짚는 중…</span>');} else {$('#composer').hidden=false; setBusy(true); $('#c-err').hidden=true; $('#c-body').hidden=false;
    if(LAYOUT!=='wide'){setSide(true); $('#right').scrollTop=0; revealBox(PENDING);}}
  let d;
  try{d=(await api('/api/pick',{method:'POST',body:r,what:'위치 찾기'})).data;}
  catch(e){if(seq!==PICKSEQ)return; setBusy(false);
    if(rp){bannerRepick();} else {if(PENDING){PENDING.remove();PENDING=null;} if(!CUR)$('#composer').hidden=true;} return;}
  if(seq!==PICKSEQ)return;
  setBusy(false);
  if(d.error){
    if(d.pdf_build_gone){try{await refreshDoc();}catch(e){} if(rp&&rp.box){rp.box.remove();rp.box=null;} else if(!rp&&PENDING){PENDING.remove();PENDING=null;}}
    if(rp){bannerRepick(d.error);return;}
    CUR=null; $('#c-err').textContent=d.error; $('#c-err').hidden=false; $('#c-body').hidden=true; return;}
  if(rp){rp.cand=d; bannerCompare(); return;}
  CUR=d; CUR.scope=null; if(!isRegion(d)){useLevel(CUR,d.default_level); if(!CUR.scope){CUR.lo=d.lo;CUR.hi=d.hi;}}
  OVERLAP_DISMISSED=null;   // 새로 고른 선택이다 — 이전 선택에서 [별도 핀으로 저장]을 눌렀어도 다시 알린다
  CUR.overlaps=overlapsFor(CUR,PINS);
  // 서버가 본 겹친 핀이 이 탭의 PINS 에 없으면(다른 사람이 방금 저장) 목록을 다시 받는다 — loadPins 가 겹침도 다시 센다.
  if((d.overlaps||[]).some(o=>!PINS.some(p=>p.id===o.id)))loadPins();
  SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; renderComposer();
  $('#composer').scrollTop=0;   // 두 번째 드래그에서 새 위치·사다리가 스크롤 위로 숨지 않게(메모는 그대로)
  if(LAYOUT!=='wide')$('#right').scrollTop=0;
  // 드래그 → 바로 메모 입력. 터치에서는 포커스하지 않는다 — 가상 키보드가 곧바로 올라와 범위 사다리와 쪽을 가렸다.
  if(LAST_PTR==='mouse')$('#note').focus({preventScroll:true});
}
// P0b-03: 저장 전 선택(CUR)이 열린 핀과 겹치면 대표 하나를 골라 '덧붙이기' 배너를 그린다. 자동 병합은 하지
// 않는다 — 사용자가 [메모에 덧붙이기]/[별도 핀으로 저장] 중 고른다.
// 겹침은 범위가 바뀔 때마다(드래그·단계 전환·▲▼) 이 탭의 PINS 로 다시 센다. pick 순간 한 번만 세면 단계를
// 바꿔 기존 핀과 똑같은 범위를 만들어도 배너가 안 떠 중복 핀이 저장됐다(실측). 규칙은 서버 selection_rel 과
// 같다(회귀 테스트가 대조한다): equal(같은 범위) · inside(선택이 핀 안) · contains(선택이 핀을 감쌈) · partial.
function selRel(lo,hi,blo,bhi){
  if(hi<blo||bhi<lo)return null;
  if(lo===blo&&hi===bhi)return 'equal';
  if(blo<=lo&&hi<=bhi)return 'inside';
  if(lo<=blo&&bhi<=hi)return 'contains';
  return 'partial';
}
function overlapsFor(o,pins){const out=[]; if(!o||!o.file)return out;   // 보기 전용 PDF 의 선택은 줄이 없다
  (pins||[]).forEach(p=>{if(p.done||p.file!==o.file)return; const rel=selRel(o.lo,o.hi,p.lo,p.hi);
    if(rel)out.push({id:p.id,lo:p.lo,hi:p.hi,rel:rel});});
  return out;}
// 대표 하나: 같은 범위 > 안(가장 좁은 바깥 핀) > 감쌈(가장 넓은 안쪽 핀) > 걸침(id 가 가장 작은 것).
function pickOverlap(ovs){
  if(!ovs||!ovs.length)return null;
  const eq=ovs.filter(o=>o.rel==='equal');
  if(eq.length)return eq.reduce((a,b)=>b.id<a.id?b:a);
  const insides=ovs.filter(o=>o.rel==='inside');
  if(insides.length)return insides.reduce((a,b)=>(b.hi-b.lo)<(a.hi-a.lo)?b:a);
  const contains=ovs.filter(o=>o.rel==='contains');
  if(contains.length)return contains.reduce((a,b)=>(b.hi-b.lo)>(a.hi-a.lo)?b:a);
  const partials=ovs.filter(o=>o.rel==='partial');
  if(partials.length)return partials.reduce((a,b)=>b.id<a.id?b:a);
  return null;
}
// 겹침 배너 문구: 선택이 그 핀과 어떤 관계인지 — '#4와 같은 범위' · '#4 범위 안' · '#4를 감쌈' · '#4와 일부 겹침'.
function overlapVerb(rel,id){const g=(c,v)=>josa(id,c,v);
  return ({equal:g('과','와')+' 같은 범위입니다',inside:' 범위 안입니다',contains:g('을','를')+' 감쌉니다',partial:g('과','와')+' 일부 겹칩니다'})[rel]||g('과','와')+' 겹칩니다';}
// [별도 핀으로 저장]은 '그 핀과의 그 관계'를 끈다(id:rel). 범위를 바꿔 관계가 달라지면 다시 알리고, 새 드래그(pick)
// 에서는 초기화한다 — 한 번 누르면 이후 선택까지 영구히 꺼지던 결함의 재발 방지.
let OVERLAP_DISMISSED=null;
function recomputeOverlap(){if(CUR)CUR.overlaps=overlapsFor(CUR,PINS);}
function renderOverlapBanner(){
  const box=$('#c-overlap'); const d=CUR;
  const ov=d?pickOverlap(d.overlaps):null;
  if(!ov||OVERLAP_DISMISSED===ov.id+':'+ov.rel){box.hidden=true;return;}
  box.hidden=false; box.dataset.rel=ov.rel;
  box.innerHTML='<span>열린 핀 #'+ov.id+overlapVerb(ov.rel,ov.id)+' <span class="dim">(L'+ov.lo+'-L'+ov.hi+')</span></span>'+
    '<button class="btn-sm" data-act="overlap-append" data-oid="'+ov.id+'" data-tip="이 선택의 메모를 #'+ov.id+' 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다">#'+
    ov.id+' 메모에 덧붙이기</button>'+
    '<button class="btn-sm" data-act="overlap-separate" data-key="'+ov.id+':'+ov.rel+'" data-tip="겹쳐도 별도 핀으로 저장합니다">별도 핀으로 저장</button>';
}
// 위치는 한 줄: '파일 L159' + 쪽 + 일치 배지 + [⧉]. 범위 종류·줄 수는 분절 컨트롤의 고른 칸이 이미 보이므로 되풀이하지
// 않는다(▲▼ 로 직접 맞춰 어느 칸에도 안 맞으면 '줄 직접 지정'을 쪽 옆에 붙인다). 드래그한 줄은 설명에 둔다.
// 보기 전용 PDF 의 선택: 위치는 '쪽 N · 영역', 원문 칸에는 영역 글자(pdftotext)를 보인다. 범위 사다리·스테퍼는 숨긴다.
function renderRegionComposer(d){
  $('#composer').classList.add('region');
  $('#c-loc').textContent=d.name+' · 쪽 '+d.page+' 영역'; $('#c-loc').dataset.copy=d.name+' 쪽 '+d.page;
  const pg=$('#c-page'); pg.textContent='보기 전용'; pg.dataset.tip='LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
  $('#c-tag').hidden=true; $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=d.warn||''; $('#c-overlap').hidden=true;
  $('#c-levels').innerHTML='';
  const pre=$('#c-snip'); pre.className='wrap open'; pre.textContent=d.quote?'영역 글자: '+d.quote:'(이 영역에는 글자가 없습니다)';
  $('#c-expand').hidden=true;}
function renderComposer(){const d=CUR; if(!d)return;
  if(isRegion(d)){renderRegionComposer(d); return;}
  $('#composer').classList.remove('region');
  const copy=d.name+' L'+d.lo+'-L'+d.hi;
  $('#c-loc').textContent=d.name+' '+rng(d.lo,d.hi); $('#c-loc').dataset.copy=copy;
  const pg=$('#c-page'); pg.textContent=d.page+'쪽'+(curLevel(d)?'':' · 줄 직접 지정');
  pg.dataset.tip=d.page+'쪽 · '+scopeLabel(d)+' · '+(d.hi-d.lo+1)+'줄 · 드래그한 줄 '+rng(d.raw_lo,d.raw_hi);
  const v=viaTag(d),tg=$('#c-tag'); tg.hidden=!v; if(v){tg.textContent=v.t;tg.dataset.tip=v.tip;tg.classList.toggle('badge-warning',!!v.low);}
  $('#c-warn').hidden=!d.warn; $('#c-warn').textContent=d.warn||'';
  renderOverlapBanner();
  $('#c-levels').innerHTML=levelBtns(d,false);
  segReveal($('#c-levels'));
  const pre=$('#c-snip'); pre.className=(WRAP?'wrap':'nowrap')+(SNIP_OPEN?' open':''); pre.textContent=snipText(d.snippet,SNIP_OPEN);
  // 접힌 원문은 CSS 가 4줄로 자른다. 잘렸는지는 그린 뒤에 잰다(긴 한 줄이 여러 줄로 접히는 원고가 흔하다).
  const over=SNIP_OPEN||pre.scrollHeight>pre.clientHeight+2, nl=String(d.snippet||'').split('\n').length;
  pre.classList.toggle('clip',!SNIP_OPEN&&over);
  $('#c-expand').hidden=!over; $('#c-expand').textContent=SNIP_OPEN?'원문 접기':'원문 펼치기'+(nl>1?' · '+nl+'줄':'');
  $('#c-wrap').setAttribute('aria-pressed',String(WRAP));
}
// 저장·취소·덧붙이기로 선택이 끝나면 선택 모드를 끄고(다시 스크롤되게) narrow 시트를 접는다(다시 본문이 먼저).
function cancelSelection(clearNote){CUR=null; PICKSEQ++; if(PENDING){PENDING.remove();PENDING=null;}
  OVERLAP_DISMISSED=null; setBusy(false); $('#composer').hidden=true; if(clearNote)$('#note').value='';
  if(!REPICK)setSelMode(false); if(LAYOUT==='narrow'&&!EDIT)setSide(false);}
async function appendToPin(id,text){
  const prior=PINS.find(p=>p.id===id); const priorNote=prior?(prior.note||''):'';
  try{const {data}=await api('/api/pins/'+id+'/edit',{method:'POST',body:{note_append:text},what:'메모 덧붙이기'});
    const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    toast('#'+id+' 에 덧붙였습니다','ok',{label:'되돌리기',fn:()=>undoAppend(id,priorNote,data.pin.rev)});
    await loadPins();
  }catch(e){}}
async function undoAppend(id,note,rev){
  try{await api('/api/pins/'+id+'/edit',{method:'POST',body:{note:note,base_rev:rev},what:'되돌리기'});
    toast('#'+id+' 메모를 되돌렸습니다','ok');}catch(e){} await loadPins();}
async function savePin(){
  if(!CUR||SAVING)return; SAVING=true; const btn=$('#btn-save'); btn.disabled=true;
  const d=CUR,note=$('#note').value.trim();
  let body={file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,raw_lo:d.raw_lo,raw_hi:d.raw_hi,via:d.via,score:d.score,
    frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};
  if(d.scope){body.scope=d.scope; body.kind=kindFor(d.scope,d.env);} else body.kind=d.kind;
  if(isRegion(d))body={page:d.page,frac:d.frac,note:note,quote:d.quote,pdf_build:d.pdf_build||undefined};   // 보기 전용: 쪽·영역만
  body.doc=d.doc||DOC||undefined;
  try{const {data}=await api('/api/pin',{method:'POST',body,what:'핀 저장'});
    const id=data.id; const box=PENDING; PENDING=null; cancelSelection(true); if(box)box.remove();
    toast('핀 #'+id+' 저장됨 · pins.md 갱신','ok',{label:'되돌리기',fn:()=>dropPin(id,true)});
    await loadPins();
  }catch(e){} finally{SAVING=false; btn.disabled=false;}
}

// ------------------------------------------------ 핀 목록
function who(a){return (a&&(a.name||a.login))||'';}
const BADPIC=new Set();   // 한 번 실패한 아바타 주소는 다시 요청하지 않는다(재렌더마다 콘솔 오류가 쌓인다)
function avatar(a){if(!a||!(a.name||a.login))return ''; const ini=esc((who(a).trim()[0]||'?').toUpperCase());
  return a.pic&&!BADPIC.has(a.pic)?'<img class="av" src="'+esc(a.pic)+'" alt="" referrerpolicy="no-referrer" data-ini="'+ini+'">'
    :'<span class="av i" aria-hidden="true">'+ini+'</span>';}
document.addEventListener('error',e=>{const t=e.target;
  if(t&&t.tagName==='IMG'&&t.classList.contains('av')){BADPIC.add(t.getAttribute('src')); const s=document.createElement('span');s.className='av i';
    s.textContent=t.dataset.ini||'?';t.replaceWith(s);}},true);
function authorTip(p){let s='작성: '+(p.author?who(p.author):'기록 전')+' · '+(p.at||'?');
  if(p.edited_at)s+=' / 수정: '+(who(p.edited_by)||'기록 전')+' · '+p.edited_at; return s;}
// P0b-03: rel 항목 중 대표 하나 — inside 가 있으면(범위가 가장 작은 바깥 핀), 없으면 partial 중 id 가
// 가장 작은 것. 서버 rel_badge()(pins.md)와 같은 규칙이어야 카드 태그와 pins.md 행이 어긋나지 않는다 —
// rel 항목은 {id,rel}뿐이라 범위는 PINS(현재 로드된 열린 핀 전체)에서 id 로 찾는다.
// 배지 문구는 뜻이 드러나게: '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. 같은 범위는 p(이 핀)의 lo/hi 로 가린다.
function josa(n,c,v){const d=String(n).slice(-1); return d==='0'||'13678'.includes(d)?c:v;}
function relBadge(rel,p){
  if(!rel||!rel.length)return null;
  const byId=new Map(PINS.map(p=>[p.id,p]));
  if(p){const same=rel.filter(x=>{const o=byId.get(x.id); return o&&o.lo===p.lo&&o.hi===p.hi;});
    if(same.length){const n=Math.min.apply(null,same.map(x=>x.id)); return {id:n,rel:'equal',label:'#'+n+josa(n,'과','와')+' 같은 범위'};}}
  const insides=rel.filter(x=>x.rel==='inside');
  if(insides.length){
    const span=x=>{const o=byId.get(x.id); return o?(o.hi-o.lo):Number.MAX_SAFE_INTEGER;};
    const best=insides.reduce((a,b)=>{const sa=span(a),sb=span(b);
      return (sb<sa||(sb===sa&&b.id<a.id))?b:a;});
    return {id:best.id,rel:'inside',label:'#'+best.id+' 범위 안'};
  }
  const partials=rel.filter(x=>x.rel==='partial').sort((a,b)=>a.id-b.id);
  if(partials.length){const n=partials[0].id; return {id:n,rel:'partial',label:'#'+n+josa(n,'과','와')+' 일부 겹침'};}
  return null;
}
// §P0c-C: 처리 중 표시. claim_until 은 epoch 초라 브라우저 시간대와 무관하게 비교한다(§위치 추정과 같은 이유로
// 벽시계 문자열 대신 숫자를 쓴다). 뷰어는 claim 을 걸지 않는다(에이전트 전용) — [풀기]만 둔다.
function claimActive(p){return typeof p.claim_until==='number'&&p.claim_until>Date.now()/1000;}
// 처리 예상 시간(references/api.md §처리 중 표시): 에이전트가 claim 에 eta_min 을 주면 서버가 eta_ts(epoch)을 둔다.
// 배지는 '처리 중 · 약 15분 · 20:40쯤' — 남은 분도 시각도 5분 단위로 올린다(견적은 대략이다). 넘기면 '예상보다 늦어짐 (+5분)'.
// eta 가 없는 옛 claim 은 '처리 중 · 20:02부터 (23분째)'. 잠금 자동 해제(claim_until)는 예상 완료로 읽혀(실측: '~04:02')
// 화면에 쓰지 않고 설명에만 둔다. 시각은 보는 기기의 현지 시각이다. now 는 테스트가 넣는다.
function ceil5(m){return Math.max(5,Math.ceil(m/5-1e-9)*5);}
function hhmm(ms){const d=new Date(ms); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
function claimInfo(p,now){now=now==null?Date.now():now; const w=who(p.claimed_by)||'?',st=typeof p.claim_ts==='number'?p.claim_ts*1000:null;
  const tail=' · 잠금 자동 해제 '+hhmm(p.claim_until*1000)+'(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]';
  const head='처리하는 쪽: '+w+(st?' · 시작 '+hhmm(st):'');
  if(typeof p.eta_ts==='number'){const eta=p.eta_ts*1000;
    if(now<=eta)return {t:'처리 중 · 약 '+ceil5((eta-now)/60000)+'분 · '+hhmm(Math.ceil(eta/300000)*300000)+'쯤',late:false,
      tip:head+' · 예상 완료 '+hhmm(eta)+tail};
    return {t:'예상보다 늦어짐 (+'+ceil5((now-eta)/60000)+'분)',late:true,tip:head+' · 예상 완료 '+hhmm(eta)+'였음'+tail};}
  if(st)return {t:'처리 중 · '+hhmm(st)+'부터 ('+Math.max(1,Math.ceil((now-st)/60000))+'분째)',late:false,tip:head+' · 예상 시간 없음'+tail};
  return {t:'처리 중',late:false,tip:head+tail};}
function claimLabel(p,now){return claimInfo(p,now).t;}
function claimTag(p){const c=claimInfo(p);
  return '<span class="badge badge-claimed'+(c.late?' late':'')+'" data-claim="'+p.id+'" data-tip="'+esc(c.tip)+'">'+ic('clock')+'<span class="ct">'+esc(c.t)+'</span></span>';}
// 남은 분·경과 분은 시간이 가면 바뀐다 — 30초마다 배지 글만 고친다(카드를 다시 그리지 않는다). 잠금이 풀린 핀이 있으면 목록을 다시 그린다.
function tickClaims(){if(document.hidden)return; let gone=false;
  $$('.badge-claimed[data-claim]').forEach(el=>{const p=OPEN_ALL.find(x=>x.id===+el.dataset.claim);
    if(!p||!claimActive(p)){gone=true; return;} const c=claimInfo(p); el.querySelector('.ct').textContent=c.t; el.dataset.tip=c.tip; el.classList.toggle('late',c.late);});
  if(gone)drawPins();}
setInterval(tickClaims,30000);
// 카드의 위치 글: LaTeX 핀은 'L12-L18', 보기 전용 PDF 의 핀은 '영역'(쪽은 옆 칸). 복사 형식은 '파일 L12-L18' / 'x.pdf 쪽 3'.
function locText(p){return isRegion(p)?'영역':rng(p.lo,p.hi);}
function locCopy(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop(); return isRegion(p)?name+' 쪽 '+p.page:name+' L'+p.lo+'-L'+p.hi;}
// 모든 문서 보기에서 카드 머리에 붙는 문서 칩. 다른 문서의 것은 점선 테두리 — 누르면 그 문서로 바뀐다.
function docChip(p){if(!(SHOW_ALL&&multiDoc()))return ''; const d=docInfo(pdoc(p)),other=pdoc(p)!==DOC;
  return '<span class="badge badge-secondary dchip'+(other?' other':'')+'" data-tip="'+esc((d?d.name+' · '+d.path:pdoc(p)+' (설정에 없는 문서)')+(other?' — #번호·[보기]를 누르면 이 문서로 바꿉니다':''))+'">'+esc(d?d.name:pdoc(p))+'</span>';}
function card(p){
  const loc='L'+p.lo+'-L'+p.hi,name=p.name||String(p.file||'').split('/').pop(),tags=[];   // loc 은 복사 형식 그대로
  if(p.stale)tags.push('<span class="badge badge-warning" data-tip="'+esc(T.stale)+'">'+ic('triangle-alert')+'위치 잃음</span>');
  else{const m=/^moved ([+-]\d+)$/.exec(p.sync||''); if(m)tags.push('<span class="badge" data-tip="'+
    esc('원고가 고쳐져 '+m[1].replace('+','')+'줄 밀렸고, 핀을 찍을 때 떠 둔 첫·끝 문장으로 새 위치를 다시 찾았습니다')+'">'+ic('move-vertical')+'줄 '+esc(m[1])+' 이동</span>');}
  const claimed=claimActive(p);
  if(claimed)tags.push(claimTag(p));
  if(p.edited_at)tags.push('<span class="badge" data-tip="'+esc('저장한 뒤 메모나 범위를 고쳤습니다('+p.edited_at.slice(11,16)+
    (p.edited_by?' · '+who(p.edited_by):'')+')')+'">'+ic('pencil')+'수정됨</span>');
  const rb=relBadge(p.rel,p);
  if(rb)tags.push('<span class="badge" data-tip="'+esc(rb.rel==='partial'?'핀 #'+rb.id+josa(rb.id,'과','와')+' 줄 범위가 일부 겹칩니다. 참고만 하고 따로 고쳐도 됩니다':
    '핀 #'+rb.id+josa(rb.id,'과','와')+' 같은 곳을 가리킵니다. 한 번에 고치고 함께 닫는 편이 낫습니다')+'">'+esc(rb.label)+'</span>');
  const v=viaTag(p); if(v)tags.push('<span class="badge'+(v.low?' badge-warning':'')+'" data-tip="'+esc(v.tip)+'">'+esc(v.t)+'</span>');
  const tip=esc(authorTip(p));
  const au=p.author?'<span class="au" data-tip="'+tip+'">'+avatar(p.author)+'<span class="au-n">'+esc(who(p.author))+'</span></span>'
    :'<span class="au old" data-tip="'+tip+'">기록 전</span>';
  const editing=!!(EDIT&&EDIT.id===p.id),open=OPEN_CARDS.has(p.id);
  // 머리 한 줄: 왼쪽에 번호·줄 범위·쪽, 오른쪽에 작성자·접기. 배지(.tags)는 머리 아래 한 줄로 내린다.
  // compact 아코디언: 접힌 카드는 번호·위치·쪽·메모 첫 줄(.sum)만 보이고, 누르면 배지·메모·버튼이 펼쳐진다(CSS).
  // wide 에서는 .sum·접기 버튼이 숨어 늘 펼친 카드다. 동작은 같은 폭 격자이고 [완료]만 강조, [삭제]는 위험 색이다.
  const first=String(p.note||'').split('\n')[0].trim();
  if(isRegion(p))tags.unshift('<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>');
  return '<div class="pin card'+(p.stale?' st':'')+(claimed?' claimed':'')+(editing?' editing':'')+(open?' open':'')+'" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+tip+'">'+
    '<div class="row head"><span class="n go" role="button" tabindex="0" data-act="view" data-tip="'+esc(T.n)+'">#'+p.id+'</span>'+docChip(p)+
    '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' '+loc)+'" data-tip="'+esc(isRegion(p)?'영역이 있는 PDF 쪽. 클릭하면 복사':T.loc)+'">'+locText(p)+'</span>'+
    '<span class="pg-link" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">'+p.page+'쪽</span>'+
    '<span class="sum" data-act="card-toggle">'+(first?esc(first):'(메모 없음)')+'</span>'+
    '<span class="sp"></span>'+au+
    '<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="'+(open||editing)+'" aria-label="'+(open?'카드 접기':'카드 펼치기')+'">'+ic(open||editing?'chevron-down':'chevron-right')+'</button></div>'+
    '<div class="tags">'+tags.join('')+'</div>'+
    (editing?'<div class="edit-slot"></div>':
    '<div class="note" data-act="edit" data-tip="클릭하면 메모와 범위를 고칩니다">'+(p.note?esc(p.note):'<span class="dim">(메모 없음)</span>')+'</div>'+
    '<div class="acts"><button class="btn-sm b-view" data-act="view" data-tip="'+esc(T.view)+'">보기</button>'+
    '<button class="btn-sm b-edit" data-act="edit" data-tip="'+esc(T.edit)+'">수정</button>'+
    (claimed?'<button class="btn-sm b-unclaim" data-act="unclaim" data-tip="'+esc('처리 중 표시를 풉니다(에이전트가 멈췄거나 잘못 잡은 경우)')+'">풀기</button>':'')+
    '<button class="btn-sm btn-destructive b-drop" data-act="drop" data-tip="'+esc(T.drop)+'">삭제</button>'+
    '<button class="btn-sm btn-soft b-close" data-act="close" data-tip="'+esc(T.close)+'">완료</button>'+
    '</div>')+'</div>';
}
// 보관함 행(references/design.md §보관함): 닫힌·삭제한 핀은 카드가 아니라 테두리·바탕 없는 납작한 행이고 글자가 흐리다.
// 첫 줄은 아이콘·#번호·위치·참조·시각·[다시 열기|되살리기], 둘째 줄은 에이전트 답(close_reply) 한 줄 — 넘치면 말줄임, 누르면
// 펼친다. 원래 요청 메모는 [원래 요청]을 눌러야 보인다. 펼친 줄은 ARC_OPEN('r:'|'o:'|'d:' + id)에 두어 다시 그려도 남는다.
const ARC_OPEN=new Set();
function arcTime(s){s=String(s||''); return /^\d{4}-\d\d-\d\d \d\d:\d\d/.test(s)?s.slice(5,16):s;}
function arcLoc(p){const name=p.name||String(p.file||p.pdf||'').split('/').pop();
  return '<span class="loc" tabindex="0" data-copy="'+esc(isRegion(p)?locCopy(p):name+' L'+p.lo+'-L'+p.hi)+'" data-tip="'+esc(T.loc)+'">'+esc(isRegion(p)?'쪽 '+p.page+' 영역':rng(p.lo,p.hi))+'</span>';}
function arcLine(key,text,tip){const open=ARC_OPEN.has(key);
  return '<span class="arc-reply'+(open?' open':'')+'" role="button" tabindex="0" data-act="arc-toggle" data-key="'+esc(key)+'" aria-expanded="'+open+'" data-tip="'+esc(tip)+'">'+esc(text)+'</span>';}
function arcHead(label,n,open){return '<span class="arc-h">'+esc(label)+'</span><span class="badge badge-secondary arc-n">'+n+'</span><span class="arc-rule" aria-hidden="true"></span>'+
  '<span class="arc-fold">'+ic(open?'chevron-down':'chevron-right')+(open?'접기':'펼치기')+'</span>';}
function doneCard(p){
  const ref=p.close_ref?'<span class="badge arc-ref" data-tip="닫을 때 남긴 참조 — 같은 값이면 같은 처리에 딸린 핀입니다">'+esc(p.close_ref)+'</span>':'';
  const reply=p.close_reply?arcLine('r:'+p.id,p.close_reply,'닫으며 남긴 설명 — 누르면 펼치고 접습니다'):'<span class="arc-reply none">설명 없이 닫힘</span>';
  const oo=ARC_OPEN.has('o:'+p.id);
  return '<div class="arc-row done" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('check')+'<span class="n" data-tip="완료한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+ref+
    '<span class="arc-t" data-tip="'+esc('닫은 시각 '+(p.done_at||'?')+' · 닫은 사람 '+(who(p.closed_by)||'기록 전'))+'">'+esc(arcTime(p.done_at))+'</span><span class="sp"></span>'+
    '<button class="btn-sm arc-b b-reopen" data-act="reopen" data-tip="'+esc(T.reopen)+'">다시 열기</button></div>'+
    '<div class="arc-l2">'+reply+(p.note?'<button class="arc-orig-t" data-act="arc-toggle" data-key="o:'+p.id+'" aria-expanded="'+oo+'" data-tip="핀을 남길 때 쓴 메모를 펼치고 접습니다">원래 요청</button>':'')+'</div>'+
    (p.note&&oo?'<div class="arc-orig"><b>원래 요청</b>'+esc(p.note)+'</div>':'')+'</div>';}
function droppedCard(p){
  const line=p.note?arcLine('d:'+p.id,p.note,'삭제한 핀의 메모 — 누르면 펼치고 접습니다'):'<span class="arc-reply none">(메모 없음)</span>';
  return '<div class="arc-row dropped" data-id="'+p.id+'" data-doc="'+esc(pdoc(p))+'" data-tip="'+esc(authorTip(p))+'">'+
    '<div class="arc-l1">'+ic('trash-2')+'<span class="n" data-tip="삭제한 핀 번호">#'+p.id+'</span>'+docChip(p)+arcLoc(p)+
    '<span class="arc-t" data-tip="'+esc('삭제한 시각 '+(p.dropped_at||'?')+' · 삭제한 사람 '+(who(p.dropped_by)||'기록 전'))+'">'+esc(arcTime(p.dropped_at))+'</span><span class="sp"></span>'+
    '<button class="btn-sm arc-b b-restore" data-act="restore" data-tip="'+esc(T.restore)+'">되살리기</button></div>'+
    '<div class="arc-l2">'+line+'</div></div>';}
async function loadPins(){let d;
  try{d=(await api('/api/pins?all=1',{what:'핀 읽기'})).data;}catch(e){return;}
  let dropped=[];
  try{dropped=(await api('/api/pins/dropped',{what:'삭제한 핀',silent:true})).data.dropped||[];}catch(e){}
  // 여러 문서: 목록은 모든 문서의 것(diffToast 도 전부 본다). PINS·DONE 은 지금 문서의 것, SHOW_ALL 이면 목록만 전부 그린다.
  const prevOpen=OPEN_ALL;
  const nextOpen=d.filter(p=>!p.done); DONE_ALL=d.filter(p=>p.done); DROPPED=dropped;
  diffToast(prevOpen,d,dropped);
  OPEN_ALL=nextOpen; PINS=nextOpen.filter(p=>pdoc(p)===DOC||!DOC); DONE=DONE_ALL.filter(p=>pdoc(p)===DOC||!DOC);
  if(EDIT&&!OPEN_ALL.some(p=>p.id===EDIT.id)){toast('편집 중이던 핀 #'+EDIT.id+' 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)','warn'); EDIT=null;}
  drawPins(); marks(); drawDocTabs();
  if(CUR){recomputeOverlap(); renderOverlapBanner();}   // 목록이 바뀌면(다른 사람의 저장·완료) 겹침도 다시 센다
  if(META)document.title=(META.label?META.label+' · ':'')+'원고 핀 · '+(multiDoc()?META.doc_name||META.main:META.main)+' · 열린 '+PINS.length;
}
// 사이드바에 그릴 목록: 기본은 지금 문서, '모든 문서'면 전부. 편집 중인 핀은 다른 문서여도 남긴다(쓰던 글이 사라지지 않게).
function listOpen(){return SHOW_ALL&&multiDoc()?OPEN_ALL:OPEN_ALL.filter(p=>pdoc(p)===DOC||!DOC||(EDIT&&EDIT.id===p.id));}
function listDone(){return SHOW_ALL&&multiDoc()?DONE_ALL:DONE;}
function listDropped(){return SHOW_ALL&&multiDoc()?DROPPED:DROPPED.filter(p=>pdoc(p)===DOC||!DOC);}
function drawPins(){
  const LIST=listOpen(),LDONE=listDone(),LDROP=listDropped();
  $('#list-h').textContent=(SHOW_ALL&&multiDoc()?'모든 문서의 열린 핀 ':'열린 핀 ')+LIST.length;
  const ab=$('#all-docs'); ab.setAttribute('aria-pressed',String(SHOW_ALL)); ab.innerHTML=(SHOW_ALL?ic('check'):'')+'모든 문서';
  $('#side-n').textContent=PINS.length; applySide();
  // compact 에서는 닫힌 핀·삭제한 핀 토글을 [⋯] 로 옮긴다 — 펼쳐 둔 동안만 목록 아래 토글이 보인다(.sec).
  $('#m-done').textContent='닫힌 핀 '+LDONE.length+(SHOW_DONE?' 숨기기':' 보기');
  $('#m-dropped').textContent='삭제한 핀 '+LDROP.length+(SHOW_DROPPED?' 숨기기':' 보기');
  $('#empty').hidden=LIST.length>0||OPEN_ALL.length>0;
  $('#pins').innerHTML=LIST.length?LIST.map(card).join(''):'<div class="dim">'+(multiDoc()&&!SHOW_ALL&&OPEN_ALL.length?'이 문서에는 아직 없습니다 · 다른 문서에 '+OPEN_ALL.length+'건':'아직 없습니다.')+'</div>';
  if(EDIT){const slot=$('#pins .edit-slot'); if(slot)slot.replaceWith(EDIT.el);}
  // 보관함 구획: 비어 있고 접혀 있으면 머리째 숨긴다. 머리는 폭 전체를 쓰는 한 줄('완료 18 ─── 펼치기')이고 스크롤해도 위에 붙는다.
  $('#sec-done').hidden=!LDONE.length&&!SHOW_DONE; $('#sec-dropped').hidden=!LDROP.length&&!SHOW_DROPPED;
  $('#done-toggle').innerHTML=arcHead('완료',LDONE.length,SHOW_DONE);
  $('#done-toggle').setAttribute('aria-expanded',String(SHOW_DONE));
  $('#done-list').hidden=!SHOW_DONE;
  if(SHOW_DONE)$('#done-list').innerHTML=LDONE.length?LDONE.slice().reverse().map(doneCard).join(''):'<div class="dim">없습니다.</div>';
  $('#dropped-toggle').innerHTML=arcHead('삭제',LDROP.length,SHOW_DROPPED);
  $('#dropped-toggle').setAttribute('aria-expanded',String(SHOW_DROPPED));
  $('#dropped-list').hidden=!SHOW_DROPPED;
  if(SHOW_DROPPED)$('#dropped-list').innerHTML=LDROP.length?LDROP.slice().reverse().map(droppedCard).join(''):'<div class="dim">없습니다.</div>';
}
// 위치 추정(.est, 점선)은 서버가 판정해 /api/pins 의 est 로 싣는다(pin_est — 핀을 찍은 빌드와 지금 빌드의
// 원고 지문 비교). 뷰어가 벽시계로 판정하던 때는 브라우저 시간대, 메모만 고친 edited_at, 낡은 PDF 위에서 찍은
// 핀에서 전부 틀렸다(독립 검증 실측). 뷰어는 받은 값을 그대로 그린다.
function isEstimated(p){return p.est===true;}
function marks(){
  $$('.mark').forEach(m=>m.remove());
  PINS.forEach(p=>{const el=document.getElementById('p'+p.page); if(!el||!Array.isArray(p.frac))return;
    const est=isEstimated(p);
    const m=document.createElement('div'); m.className='mark'+(p.stale?' st':'')+(est?' est':''); m.dataset.pin=p.id;
    Object.assign(m.style,{left:p.frac[0]*100+'%',top:p.frac[1]*100+'%',width:p.frac[2]*100+'%',height:p.frac[3]*100+'%'});
    const n=String(p.note||'').replace(/\s+/g,' ').trim();
    const tip='#'+p.id+' · '+(n?(n.length>60?n.slice(0,60)+'…':n):'(메모 없음)')+(est?' (PDF가 새로 만들어져 위치는 추정입니다)':'');
    m.innerHTML='<b data-act="mark-jump" data-id="'+p.id+'" data-tip="'+esc(tip)+'">'+p.id+'</b>'; el.appendChild(m);});
}
// 배지 클릭은 카드로 스크롤·깜빡인다(pick 을 부르지 않는다). 마크 상자 자체는 pointer-events:none 이라
// 그 위 드래그는 그대로 새 선택이 된다 — 배지(<b>)만 mousedown 을 막아야 한다.
$('#doc').addEventListener('mousedown',e=>{
  if(e.target.closest('.mark b')){e.stopPropagation();e.preventDefault();}
},true);
// 배지 클릭 → 카드로 스크롤 + .cur 강조(스펙) + 1.2초 깜빡임. 강조는 그대로 남지 않고 풀린다 —
// 정적 box-shadow 였을 때는 다음 클릭 전까지 카드에 계속 남아 있었다.
// compact: 배지를 누르면 패널·시트를 펴고 그 카드를 펼친 뒤 jumpToCard 로 스크롤한다.
function revealCard(id){if(LAYOUT==='wide')return; setSide(true);
  if(!OPEN_CARDS.has(id)&&PINS.some(p=>p.id===id)){OPEN_CARDS.add(id); drawPins();}}
function jumpToCard(id){
  const el=document.querySelector('.pin[data-id="'+id+'"]'); if(!el)return;
  el.scrollIntoView({behavior:SMOOTH,block:'nearest'});
  $$('.pin.cur').forEach(x=>{if(x!==el)x.classList.remove('cur');});
  clearTimeout(el._curT);
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('cur','flash');
  el._curT=setTimeout(()=>el.classList.remove('cur','flash'),1200);
}
function jumpPin(id){if(viaDoc(id,jumpPin))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(LAYOUT==='narrow')setSide(false);   // 시트가 쪽을 가리지 않게 접고 나서 잰다
  const m=document.querySelector('.mark[data-pin="'+id+'"]');
  if(m){
    const L=$('#left'),lr=L.getBoundingClientRect(),mr=m.getBoundingClientRect();
    L.scrollTop+=(mr.top-(lr.top+lr.height*0.30));
    m.classList.remove('flash');void m.offsetWidth;m.classList.add('flash');
  } else {
    const el=document.getElementById('p'+p.page); if(el)el.scrollIntoView({behavior:SMOOTH});
  }
}
// 카드에 hover 하면 그 마크와, 겹친 상대 마크까지 함께 강조한다.
function markIdsFor(p){return [p.id].concat((p.rel||[]).map(x=>x.id));}
$('#pins').addEventListener('mouseover',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.add('hi');});});
$('#pins').addEventListener('mouseout',e=>{const c=e.target.closest('.pin'); if(!c)return;
  const p=PINS.find(x=>x.id===+c.dataset.id); if(!p)return;
  markIdsFor(p).forEach(id=>{const m=document.querySelector('.mark[data-pin="'+id+'"]'); if(m)m.classList.remove('hi');});});
async function closePin(id){try{const {data}=await api('/api/pins/'+id+'/close',{method:'POST',what:'완료'});
  if(!data.ok){toast('완료 실패 — 핀 #'+id+' 이 없습니다','err');}
  else {markMine(id); toast('핀 #'+id+' 완료','ok',{label:'되돌리기',fn:()=>reopenPin(id,true)});}}catch(e){} await loadPins();}
async function reopenPin(id,undo){try{await api('/api/pins/'+id+'/reopen',{method:'POST',what:'다시 열기'});
  markMine(id); toast(undo?'핀 #'+id+' 완료를 되돌렸습니다':'핀 #'+id+' 다시 열림','ok');}catch(e){} await loadPins();}
async function dropPin(id,undoSave){try{await api('/api/pins/'+id+'/drop',{method:'POST',what:'삭제'});
  if(EDIT&&EDIT.id===id)EDIT=null;
  markMine(id); toast(undoSave?'핀 #'+id+' 저장을 되돌렸습니다':'핀 #'+id+' 삭제됨','ok',{label:'되돌리기',fn:()=>restorePin(id)});}catch(e){} await loadPins();}
async function restorePin(id){try{await api('/api/pins/'+id+'/restore',{method:'POST',what:'되살리기'});
  markMine(id); toast('핀 #'+id+' 되살림','ok');}catch(e){} await loadPins();}
async function unclaimPin(id){try{await api('/api/pins/'+id+'/unclaim',{method:'POST',what:'처리 중 풀기'});
  markMine(id); toast('핀 #'+id+' 처리 중 표시를 풀었습니다','ok');}catch(e){} await loadPins();}

// ------------------------------------------------ 편집
function openEdit(id){if(viaDoc(id,openEdit))return; const p=PINS.find(x=>x.id===id); if(!p)return;
  if(EDIT&&EDIT.id===id)return;
  const el=document.createElement('div'); el.className='edit';
  el.innerHTML='<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea>'+
    '<div class="e-levels seg" role="group" aria-label="범위 단계"></div>'+
    '<div class="c-tools"><div class="step" role="group" aria-label="한 줄씩 넓히고 좁히기">'+
    '<span class="sl" aria-hidden="true">위</span><button data-act="nudge" data-dir="up-grow" aria-label="위로 한 줄 넓히기" data-tip="위로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="up-shrink" aria-label="위에서 한 줄 좁히기" data-tip="위에서 한 줄 좁힙니다">'+ic('minus')+'</button>'+
    '<span class="sl" aria-hidden="true">아래</span><button data-act="nudge" data-dir="down-grow" aria-label="아래로 한 줄 넓히기" data-tip="아래로 한 줄 넓힙니다">'+ic('plus')+'</button>'+
    '<button data-act="nudge" data-dir="down-shrink" aria-label="아래에서 한 줄 좁히기" data-tip="아래에서 한 줄 좁힙니다">'+ic('minus')+'</button></div>'+
    '<span class="e-range loc" tabindex="0" data-tip="저장하면 핀이 가리킬 원문 줄. 누르면 복사"></span></div>'+
    '<pre class="e-snip wrap">원문 읽는 중…</pre>'+
    '<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="'+esc(T.repick)+'">위치 다시 잡기</button>'+
    '<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="'+esc(T.ecancel)+'">취소</button>'+
    '<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="'+esc(T.esave)+'">저장</button></div>';
  const ta=el.querySelector('.e-note'); ta.value=p.note||''; autoGrow(ta);
  EDIT={id,el,base_rev:p.rev||0,file:p.file,name:p.name||String(p.file||p.pdf||'').split('/').pop(),lo:p.lo,hi:p.hi,scope:p.scope||null,
    kind:p.kind,env:null,levels:[],n_lines:null,snippet:'',orig:{lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||''},
    doc:pdoc(p),region:isRegion(p),page:p.page,quote:p.quote||''};
  if(EDIT.region)el.classList.add('region');
  drawPins(); renderEdit(); ta.focus(); editSnip(true);
}
// 편집 칸에 저장 안 한 변경이 있는가(문서를 바꿀 때 편집을 닫아도 되는지).
function editDirty(){const E=EDIT; if(!E)return false; const ta=E.el.querySelector('.e-note');
  return (ta&&ta.value!==E.orig.note)||E.lo!==E.orig.lo||E.hi!==E.orig.hi;}
function autoGrow(ta){ta.style.height='auto'; const lh=20; ta.style.height=Math.min(12*lh,Math.max(3*lh,ta.scrollHeight+2))+'px';}
document.addEventListener('input',e=>{if(e.target.classList&&(e.target.classList.contains('e-note')||e.target.id==='note'))autoGrow(e.target);});
async function editSnip(withLevels){const E=EDIT; if(!E)return;
  if(E.region){E.snippet=E.quote?'영역 글자: '+E.quote:'(영역 글자 없음)'; renderEdit(); return;}   // 보기 전용: 원문 줄이 없다
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(E.file)+'&lo='+E.lo+'&hi='+E.hi+(withLevels?'&levels=1':''),E.doc),
      {what:'원문 읽기',expect:[400]});
    if(EDIT!==E)return;
    if(status===400){E.snippet='원문을 읽지 못했습니다 — '+(data&&data.error||'')+'\n위치 다시 잡기로 고치세요.'; renderEdit(); return;}
    E.snippet=data.snippet; E.n_lines=data.n_lines;
    if(withLevels&&data.levels){E.levels=data.levels; if(!E.scope||!lvOf(E,E.scope)){const cur=E.levels.find(l=>l.lo===E.lo&&l.hi===E.hi);
      if(cur&&!E.scope)E.scope=null;}}
    renderEdit();}catch(e){}}
function renderEdit(){const E=EDIT; if(!E)return; const el=E.el;
  el.querySelector('.e-range').textContent=E.region?'쪽 '+E.page+' · 영역':rng(E.lo,E.hi);
  el.querySelector('.e-range').dataset.copy=E.region?E.name+' 쪽 '+E.page:E.name+' L'+E.lo+'-L'+E.hi;
  el.querySelector('.e-levels').innerHTML=levelBtns(E,true); segReveal(el.querySelector('.e-levels'));
  const pre=el.querySelector('.e-snip'); pre.className='e-snip '+(WRAP?'wrap':'nowrap'); pre.textContent=snipText(E.snippet,false);}
function cancelEdit(){EDIT=null; drawPins();}
async function saveEdit(){const E=EDIT; if(!E||ESAVING)return;
  const note=E.el.querySelector('.e-note').value, body={base_rev:E.base_rev};
  if(note!==E.orig.note)body.note=note;
  if(E.lo!==E.orig.lo||E.hi!==E.orig.hi||(E.scope||null)!==(E.orig.scope||null)){body.lo=E.lo;body.hi=E.hi;
    if(E.scope){body.scope=E.scope; body.kind=kindFor(E.scope,E.env);}}
  if(Object.keys(body).length===1){cancelEdit();return;}
  ESAVING=true;
  try{const {status,data}=await api('/api/pins/'+E.id+'/edit',{method:'POST',body,what:'핀 수정',expect:[409]});
    if(status===409){
      if(data&&data.error==='done'){toast('핀 #'+E.id+' 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다','warn'); EDIT=null; await loadPins(); return;}
      const p=data.pin; toast('다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다','warn');
      E.base_rev=p.rev; E.lo=p.lo; E.hi=p.hi; E.scope=p.scope||null; E.file=p.file;
      E.orig={lo:p.lo,hi:p.hi,scope:p.scope||null,note:p.note||''}; editSnip(true); await loadPins(); return;}
    EDIT=null; toast('핀 #'+E.id+' 수정됨','ok'); await loadPins();
  }catch(e){} finally{ESAVING=false;}
}

// ------------------------------------------------ 위치 다시 잡기
function banner(html){const b=$('#banner'); b.innerHTML=html; b.hidden=false;}
function bannerRepick(err){banner('<span>핀 #'+REPICK.id+' 의 새 위치를 PDF에서 드래그하세요 · Esc 취소</span>'+
  (err?'<span class="errline" style="margin:0">'+esc(err)+'</span>':'')+'<span class="sp"></span>'+
  '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
function bannerCompare(){const c=REPICK.cand,lv=lvOf(c,c.default_level)||c,rg=isRegion(c);
  banner('<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">'+(rg?'지금 쪽 '+REPICK.from.page+' · 새 쪽 '+c.page+' 영역':'지금 L'+REPICK.from.lo+'-L'+REPICK.from.hi+' · 새 L'+lv.lo+'-L'+lv.hi)+'</span>'+
    '<span class="dim">('+esc(rg?(c.quote?String(c.quote).slice(0,40):'글자 없는 영역'):(lv.label||scopeLabel(c)))+')</span><span class="sp"></span>'+
    '<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button>'+
    '<button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>');}
// 터치에서는 위치 다시 잡기 동안 선택 모드를 켜고, narrow 는 시트를 접어 쪽을 드러낸다(배너는 접힌 시트에도 남는다).
async function startRepick(){if(!EDIT)return;
  if(EDIT.doc&&EDIT.doc!==DOC){const E=EDIT; await switchDoc(E.doc); if(DOC!==E.doc||EDIT!==E)return;}   // 그 핀의 문서 위에서 고른다
  REPICK={id:EDIT.id,from:{lo:EDIT.lo,hi:EDIT.hi,page:EDIT.page},box:null,cand:null}; bannerRepick();
  if(MQ_COARSE.matches)setSelMode(true); if(LAYOUT==='narrow')setSide(false);}
function cancelRepick(){const was=!!REPICK; if(REPICK&&REPICK.box)REPICK.box.remove(); REPICK=null; $('#banner').hidden=true;
  if(was){if(!CUR)setSelMode(false); if(EDIT&&LAYOUT!=='wide')setSide(true);}}
async function applyRepick(){const R=REPICK; if(!R||!R.cand)return; const c=R.cand,lv=lvOf(c,c.default_level)||c;
  let loc={file:c.file,page:c.page,lo:lv.lo,hi:lv.hi,raw_lo:c.raw_lo,raw_hi:c.raw_hi,via:c.via,score:c.score,frac:c.frac,pdf_build:c.pdf_build||undefined,
    scope:lv.level||null,kind:lv.level?kindFor(lv.level,lv.env):c.kind};
  if(!loc.scope)delete loc.scope;
  if(isRegion(c))loc={page:c.page,frac:c.frac,quote:c.quote,pdf_build:c.pdf_build||undefined};   // 보기 전용: 영역만 다시 잡는다
  const base=EDIT&&EDIT.id===R.id?EDIT.base_rev:0;
  try{const {status,data}=await api('/api/pins/'+R.id+'/edit',{method:'POST',body:{loc,base_rev:base},what:'위치 바꾸기',expect:[409]});
    if(status===409){toast(data&&data.error==='done'?'닫힌 핀은 위치를 바꿀 수 없습니다':'다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다','warn');
      if(EDIT&&data.pin){EDIT.base_rev=data.pin.rev;} cancelRepick(); await loadPins(); return;}
    const p=data.pin; cancelRepick();
    if(EDIT&&EDIT.id===p.id){Object.assign(EDIT,{base_rev:p.rev,lo:p.lo,hi:p.hi,file:p.file,name:p.name,scope:p.scope||null,page:p.page,quote:p.quote||''});
      EDIT.orig.lo=p.lo;EDIT.orig.hi=p.hi;EDIT.orig.scope=p.scope||null; editSnip(true);}
    toast('핀 #'+p.id+' 위치를 '+(isRegion(p)?'쪽 '+p.page+' 영역':'L'+p.lo+'-L'+p.hi)+' 로 바꿨습니다','ok'); await loadPins();
  }catch(e){}}

// ------------------------------------------------ PDF 재빌드
function topAnchor(){const L=$('#left'),top=L.getBoundingClientRect().top;
  for(const pg of $$('.pg')){const r=pg.getBoundingClientRect(); if(r.bottom>top+1)return {page:+pg.dataset.page,frac:Math.max(0,(top-r.top)/r.height)};}
  return null;}
function restoreAnchor(a){if(!a)return; const pg=document.getElementById('p'+a.page); if(!pg)return; const L=$('#left');
  L.scrollTop+=pg.getBoundingClientRect().top-L.getBoundingClientRect().top+a.frac*pg.getBoundingClientRect().height;}
async function refreshDoc(){const a=topAnchor(),k=DOC;
  const m=(await api(dq('/api/meta'),{what:'화면 정보 읽기'})).data; META_BY.set(k,m);
  if(k!==DOC)return;                    // 기다리는 사이 다른 문서로 바꿨다 — 캐시만 새로 둔다
  const same=META&&m.pages.length===META.pages.length; META=m; drawMeta();
  // 캔버스는 옛 PDF 로 그린 것이다 — 걷어 내 새 PNG 를 먼저 보이고, 새 빌드의 PDF 를 열면 다시 그린다.
  if(same){vecReleaseAll(); $$('.pg').forEach((pg,i)=>{const p=META.pages[i]; pg.style.aspectRatio=p.pt_w+' / '+p.pt_h; pg.querySelector('img').src=pageSrc(p);});}
  else buildDoc();
  restoreAnchor(a); vecOpen(); await loadPins();}
// ok_errors|fail 이면 토스트만이 아니라 패널 자체를 바로 연다 — 토스트는 6초 뒤 사라지고 나면
// 다시 볼 길이 없었다. 닫아도 #build-err-chip 이 남아 다시 열 수 있다(LAST_BUILD_ERR 이 있는 동안).
function showBuildErr(r){LAST_BUILD_ERR=r; if(DOC)BUILD_ERR_BY.set(DOC,r); const b=$('#build-err');
  const title=r.state==='fail'?'빌드 실패 — 화면은 이전 PDF입니다':'PDF를 재빌드했지만 LaTeX 오류가 있습니다';
  b.innerHTML='<div class="row"><b>'+esc(title)+'</b><span class="sp"></span>'+
    '<button class="btn-sm" data-act="err-close" data-tip="이 알림을 닫습니다(다시 보기는 위 배지로)">닫기</button></div>'+
    (r.errors||[]).map(e=>'<div class="dim">'+(e.line?'L'+e.line+' · ':'')+esc(e.msg)+'</div>').join('')+
    '<pre class="nowrap" style="max-height:30vh">'+esc(String(r.log_tail||r.log||'').split('\n').slice(-20).join('\n'))+'</pre>';
  b.hidden=false; $('#build-err-chip').hidden=true;}
function hideBuildErr(){$('#build-err').hidden=true; $('#build-err-chip').hidden=!LAST_BUILD_ERR;}
// P0b-01: 재빌드는 비동기다 — POST 는 바로 돌아오고, #build-chip 폴러(startBuildPolling)가 진행 상황을
// 보여 준 뒤 끝나면 제자리 교체와 알림을 한다. 다른 사람이 시작한 빌드도 같은 폴러가 잡아낸다.
async function rebuild(){
  try{const {status}=await api(dq('/api/rebuild?async=1'),{method:'POST',what:'PDF 재빌드',expect:[409]});
    if(status===409){toast('이미 다른 곳에서 PDF를 재빌드하는 중입니다 — 끝난 뒤 다시 누르세요','warn');return;}
    $('#build-err').hidden=true;
    // POST 전에 떠난 조회가 있으면 끝나길 기다린 뒤 새로 묻는다 — 그 조회는 옛 상태(ok)를 들고 와 1초 폴링을
    // 걸지 않는다. 완료는 build_seq 로 가리므로 이 탭이 따로 기억할 것은 없다.
    if(BUILD_INFLIGHT){try{await BUILD_INFLIGHT;}catch(e){}}
    await pollBuild();
  }catch(e){}}

// ------------------------------------------------ 도움말
let HELP_BACK=null;
function openHelp(){const d=$('#help'); if(d.open)return; HELP_BACK=document.activeElement; hideTip(); d.showModal();}
$('#help').addEventListener('close',()=>{if(HELP_BACK&&HELP_BACK.focus)HELP_BACK.focus(); HELP_BACK=null;});

// ------------------------------------------------ 이벤트 위임(인라인 핸들러 없음)
document.addEventListener('click',e=>{
  const cp=e.target.closest('[data-copy]'); if(cp){copyText(cp.dataset.copy);return;}
  const a=e.target.closest('[data-act]'); if(!a)return;
  const host=a.closest('[data-id]'),id=host?+host.dataset.id:null,inEdit=!!a.closest('.edit');
  const fromMore=!!a.closest('#more');
  if(fromMore&&(a.dataset.close||a.dataset.act==='help'))$('#more').close();
  switch(a.dataset.act){
    case 'side':setSide(!SIDE_OPEN,true);break;
    case 'selmode':setSelMode(!SELMODE);if(SELMODE&&LAYOUT==='narrow'&&!CUR&&!EDIT)setSide(false);break;
    case 'more':openMore();break; case 'more-close':$('#more').close();break;
    case 'size-preset':sizePreset(+a.dataset.i);break;
    case 'm-jump':$('#more').close();goPage($('#m-jump').value);break;
    case 'coach-close':$('#coach').hidden=true;break;
    case 'card-toggle':if(id==null)break; if(OPEN_CARDS.has(id))OPEN_CARDS.delete(id); else OPEN_CARDS.add(id); drawPins();break;
    case 'rebuild':rebuild();break; case 'reload':loadPins();break;
    case 'zoom-in':zoom(1);break; case 'zoom-out':zoom(-1);break; case 'fit':fitW();break;
    case 'theme':cycleTheme();break; case 'help':openHelp();break; case 'help-close':$('#help').close();break;
    case 'save':savePin();break; case 'cancel':cancelSelection(true);break;
    case 'overlap-append':{const text=$('#note').value.trim();
      if(!text){toast('메모를 먼저 써야 덧붙일 수 있습니다','warn');break;}
      appendToPin(+a.dataset.oid,text);break;}
    case 'overlap-separate':OVERLAP_DISMISSED=a.dataset.key||null;renderOverlapBanner();break;
    case 'wrap':WRAP=!WRAP;savePrefs({wrap:WRAP});renderComposer();renderEdit();break;
    case 'copy-cur':if(CUR)copyText(CUR.name+' L'+CUR.lo+'-L'+CUR.hi);break;
    case 'expand':SNIP_OPEN=!SNIP_OPEN;renderComposer();break;
    case 'level':{const o=inEdit?EDIT:CUR; if(!o)break; useLevel(o,a.dataset.level); if(!inEdit)recomputeOverlap(); inEdit?renderEdit():renderComposer(); break;}
    case 'nudge':{const o=inEdit?EDIT:CUR; if(!o||!nudge(o,a.dataset.dir))break; if(!inEdit)recomputeOverlap(); const r=inEdit?renderEdit:renderComposer; r(); refetchSnip(o,r); break;}
    case 'view':jumpPin(id);break; case 'edit':openEdit(id);break;
    case 'doc':switchDoc(a.dataset.doc);if(a.closest('#docs-menu'))$('#docs-menu').close();break;
    case 'doc-menu':openDocsMenu();break; case 'docs-menu-close':$('#docs-menu').close();break;
    case 'all-docs':SHOW_ALL=!SHOW_ALL;drawPins();break;
    case 'mark-jump':revealCard(id);jumpToCard(id);break;
    case 'close':closePin(id);break; case 'drop':dropPin(id,false);break; case 'reopen':reopenPin(id,false);break;
    case 'restore':restorePin(id);break; case 'unclaim':unclaimPin(id);break;
    case 'arc-toggle':{const k=a.dataset.key; if(!k)break; if(ARC_OPEN.has(k))ARC_OPEN.delete(k); else ARC_OPEN.add(k); drawPins(); break;}
    case 'esave':saveEdit();break; case 'ecancel':cancelEdit();break;
    case 'repick':startRepick();break; case 'rp-cancel':cancelRepick();break; case 'rp-apply':applyRepick();break;
    case 'done-toggle':SHOW_DONE=!SHOW_DONE;drawPins();if(fromMore)revealList('#done-toggle',SHOW_DONE);break;
    case 'dropped-toggle':SHOW_DROPPED=!SHOW_DROPPED;drawPins();if(fromMore)revealList('#dropped-toggle',SHOW_DROPPED);break;
    case 'err-close':hideBuildErr();break;
    case 'build-err-reopen':if(LAST_BUILD_ERR)showBuildErr(LAST_BUILD_ERR);break;
  }
});
document.addEventListener('keydown',e=>{
  if(e.isComposing||e.keyCode===229)return;
  const t=e.target,inField=t&&(t.tagName==='TEXTAREA'||t.tagName==='INPUT'||t.tagName==='SELECT'||t.isContentEditable);
  // Ctrl(⌘) + = / − / 0 은 브라우저 확대 대신 PDF 쪽만 확대·축소·폭 맞춤한다. 입력 칸에서는 브라우저에 맡긴다.
  if((e.ctrlKey||e.metaKey)&&!e.altKey&&!inField){const z=zoomKey(e);
    if(z){e.preventDefault(); if(z==='fit')fitW(); else zoom(z==='in'?1:-1); return;}}
  // 문서 전환(여러 문서): Ctrl+PgUp/PgDn 은 이전·다음, Alt+1…9 는 그 번째(e.code — 맥의 Option+숫자는 다른 글자를 낸다).
  // 탭에 포커스가 있으면 ←/→/Home/End 로 옮긴다(ARIA 탭 패턴, 자동 활성화). 입력 칸에서는 하지 않는다.
  if(multiDoc()&&!inField){
    if(e.ctrlKey&&!e.altKey&&!e.metaKey&&(e.key==='PageUp'||e.key==='PageDown')){e.preventDefault(); cycleDoc(e.key==='PageDown'?1:-1); return;}
    if(e.altKey&&!e.ctrlKey&&!e.metaKey&&/^Digit[1-9]$/.test(e.code||'')){const d=DOCS[+e.code.slice(5)-1]; if(d){e.preventDefault(); switchDoc(d.key);} return;}
    if(t&&t.classList&&t.classList.contains('dtab')&&['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();
      const i=DOCS.findIndex(d=>d.key===t.dataset.doc),n=DOCS.length;
      const j=e.key==='Home'?0:e.key==='End'?n-1:(i+(e.key==='ArrowRight'?1:-1)+n)%n;
      switchDoc(DOCS[j].key).then(()=>{const b=document.getElementById('dtab-'+DOCS[j].key); if(b)b.focus();}); return;}
  }
  if(e.key==='Enter'&&(e.metaKey||e.ctrlKey)){
    if(t&&t.id==='note'){e.preventDefault();savePin();}
    else if(t&&t.classList&&t.classList.contains('e-note')){e.preventDefault();saveEdit();}
    return;}
  if(e.key==='Enter'&&t&&t.dataset&&t.dataset.copy!==undefined&&!inField){copyText(t.dataset.copy);return;}
  // role=button 인 span(카드의 #번호)은 Enter·Space 로도 누른다 — 클릭과 같은 data-act 경로로 보낸다.
  if((e.key==='Enter'||e.key===' ')&&t&&t.getAttribute&&t.getAttribute('role')==='button'&&t.dataset&&t.dataset.act&&!inField){e.preventDefault();t.click();return;}
  if(e.key==='Escape'){
    if($('#help').open||$('#more').open||$('#docs-menu').open)return;
    if(!TIP.hidden){hideTip(); if(!inField)return;}
    if(REPICK){cancelRepick();return;}
    if(EDIT){cancelEdit();return;}
    if(CUR||!$('#composer').hidden){cancelSelection(true);return;}
    return;}
  if(e.key==='?'&&!inField&&!e.metaKey&&!e.ctrlKey&&!e.altKey){e.preventDefault();openHelp();}
});
boot();
</script></body></html>"""
HTML = HTML.replace("__PDFJS_VERSION__", PDFJS_VERSION)
HTML = HTML.replace("__LUCIDE_JSON__", json.dumps(LUCIDE, sort_keys=True))
HTML = ICON_TOKEN_RE.sub(lambda m: icon_svg(m.group(1)), HTML)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 128          # 동시 요청 수십 건이 SYN 재전송으로 1초씩 밀리지 않게


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # 본문이 Content-Length 보다 짧게 오고 끊기지 않으면 읽기가 영원히 멈춘다. 유휴 keep-alive 도 이 시간에 닫힌다.
    timeout = 30

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str, cache: str = None):
        if code >= 400:
            # 오류 뒤에는 연결을 끊는다. 요청을 끝까지 못 읽었을 수 있고, 남은 바이트가 다음 요청으로
            # 읽히면 --allow 와 작성자 기록을 우회한다(요청 밀반입).
            self.close_connection = True
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache is None or code >= 400:
            cache = "public, max-age=600" if ctype == "image/png" and code < 400 else "no-store"
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _read_raw(self) -> bytes:
        """어떤 응답보다 먼저 요청 본문을 끝까지 읽는다(GET·403·404 경로 포함).

        읽지 않고 응답하면 같은 연결의 남은 바이트가 '헤더 없는 로컬 요청'으로 해석된다 —
        tailscale serve 는 백엔드 연결을 재사용하므로 테일넷 사용자가 그 틈에 닿을 수 있다."""
        self._raw = b""
        if self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True
            raise HTTPError(400, "Transfer-Encoding 은 받지 않습니다. Content-Length 로 보내세요.")
        cls = self.headers.get_all("Content-Length") or []
        if len(set(v.strip() for v in cls)) > 1:
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 여러 개입니다.")
        cl = cls[0].strip() if cls else ""
        if cl == "":
            return b""
        if not re.fullmatch(r"[0-9]+", cl):          # isdigit() 는 '²' 같은 latin-1 숫자도 받는다
            self.close_connection = True
            raise HTTPError(400, "Content-Length 가 음이 아닌 정수가 아닙니다.")
        n = int(cl)
        if n > MAX_BODY:
            self.close_connection = True
            raise HTTPError(413, "요청 본문이 너무 큽니다(1 MiB 이하).")
        raw = self.rfile.read(n) if n else b""
        if len(raw) != n:                                 # 잘린 요청 — 동작하지 않는다(/api/clear 포함)
            self.close_connection = True
            raise HTTPError(400, "요청 본문이 Content-Length 보다 짧습니다(연결이 끊겼습니다).")
        self._raw = raw
        return raw

    def _check_origin(self) -> None:
        """교차 출처 요청(CSRF)과 DNS rebinding 을 막는다.

        - Host: 모든 요청이 루프백 이름(:이 포트)이나 *.ts.net 이어야 한다.
          DNS rebinding 은 브라우저가 evil.example 로 127.0.0.1 에 닿는 것이라 Host 가 드러난다.
        - Origin: 있으면 Host 가 루프백일 때 루프백(포트 무관 — SSH -L), Host 가 *.ts.net 일 때 그 호스트와
          같은 출처여야 한다(origin_ok).
          브라우저는 교차 출처 POST 에 Origin 을 반드시 싣는다. curl·에이전트는 Origin 이 없어 영향이 없다."""
        if not C.origin_check:                        # --no-origin-check: 실측 경로가 예상과 다를 때의 탈출구
            return
        host = self.headers.get("Host")
        # Tailscale-User-* 헤더 여부와 무관하게 검사한다. 그 헤더는 rebinding 페이지도 같은 출처 GET 에
        # preflight 없이 실을 수 있어, 헤더로 면제하면 방어가 통째로 우회된다(실측).
        if host is not None and not host_ok(host):
            raise HTTPError(403, "허용되지 않은 Host 입니다: %s" % hdr_text(host)[:100])
        origin = self.headers.get("Origin")
        if origin is not None and not origin_ok(origin, host):
            raise HTTPError(403, "다른 출처의 요청은 받지 않습니다: %s" % hdr_text(origin)[:100])

    def _guard(self) -> dict:
        self._read_raw()
        actor, via_header = actor_of(self.headers)
        self._check_origin()
        if C.allow and via_header and actor["login"] not in C.allow:
            raise HTTPError(403, "이 뷰어에 허용되지 않은 계정입니다: %s" % actor["login"])
        if C.allow and not via_header:
            # 신원 헤더 없이 *.ts.net 으로 온 요청 = 태그 장치(또는 funnel). --allow 가 있으면 로컬로 치지 않는다.
            hname, _ = split_host(self.headers.get("Host") or "")
            if hname.endswith(".ts.net"):
                raise HTTPError(403, "신원 헤더 없는 테일넷 요청입니다(태그 장치 등). --allow 목록의 계정으로 접속하세요.")
        return actor

    def _run(self, fn):
        try:
            fn()
        except HTTPError as e:
            self._json(e.body, e.code)
        except (BrokenPipeError, ConnectionResetError, socket.timeout):
            self.close_connection = True
        except Exception as e:                            # noqa: BLE001 — 연결을 끊지 않고 JSON 으로 알린다
            traceback.print_exc(file=sys.stderr)
            try:
                self._json({"error": "서버 내부 오류: %s" % e}, 500)
            except OSError:
                self.close_connection = True

    def do_GET(self):
        self._run(self._get)

    def do_POST(self):
        self._run(self._post)

    def _get(self):
        actor = self._guard()
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        # 문서가 걸리는 경로는 ?doc=<키>(없으면 첫 문서)를 받아 그 문서로 처리한다(§여러 문서).
        with using_doc(request_doc(q)):
            return self._get_doc(actor, path, q)

    def _get_doc(self, actor, path, q):
        if path == "/":
            return self._send(200, HTML.encode(), "text/html; charset=utf-8")
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/api/meta":
            light = (q.get("light") or ["0"])[0] == "1"
            return self._json(meta(actor, light=light))
        if path == "/api/build":
            full = (q.get("log") or ["0"])[0] == "1"
            return self._json(diet_log(build_state_snapshot(), full))
        if path == "/pins.md":                    # §P0c-B: 원격 에이전트 진입점 — GET /api/pins 와 같은 sync 경로
            base = remote_base_for(self.headers.get("Host") or "")
            text = pins_md_text(snapshot_pins(), base=base)
            return self._send(200, text.encode("utf-8"), "text/markdown; charset=utf-8")
        if path == "/api/pins":
            allp = (q.get("all") or ["0"])[0] == "1"
            rows = pins_payload(snapshot_pins(), allp)
            if q.get("doc"):                          # ?doc=<키> 면 그 문서의 핀만(겹침·추정은 전체 기준 그대로)
                rows = [r for r in rows if r["doc"] == cur_doc().key]
            return self._json(rows)
        if path == "/api/docs":
            return self._json(docs_payload())
        if path == "/api/pins/dropped":
            return self._json({"dropped": dropped_payload()})
        if path == "/api/snippet":
            return self._json(snippet_api(q))
        if path == "/api/overlaps":
            return self._json(overlaps_api(q))
        if path.startswith("/pages/"):
            name = os.path.basename(path)
            if PAGE_FILE_RE.fullmatch(name):
                f = cur_pages() / name
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
                if data is not None:
                    return self._send(200, data, "image/png")
        if path.startswith("/vendor/pdfjs/"):
            # 뷰어의 벡터 렌더러(PDF.js). 이름 한 칸만 받는다 — 하위 경로·'..'·인코딩된 문자는 404.
            f = vendor_file(path[len("/vendor/pdfjs/"):])
            if f is not None:
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
                if data is not None:
                    # 파일 이름에 버전이 없으므로 뷰어가 ?v=<PDFJS_VERSION> 를 붙여 캐시를 가른다.
                    return self._send(200, data, VENDOR_MIME[f.suffix], cache="public, max-age=86400")
            raise HTTPError(404, "없는 vendor 파일입니다: %s" % hdr_text(path)[:100])
        if path == "/pdf":
            # 쪽 이미지와 같은 빌드의 PDF(벡터 렌더링용). 빌드 이름이 틀렸거나 이미 지워졌으면 404 — 다른 빌드로
            # 물러서지 않는다(뷰어가 PNG 로 돌아가고 /api/meta 를 다시 읽는다).
            name = (q.get("build") or [""])[0]
            f = build_pdf(name)
            data = None
            if f is not None:
                try:
                    data = f.read_bytes()
                except OSError:
                    data = None
            if data is None:
                raise HTTPError(404, "그 빌드의 PDF 가 없습니다: %s" % hdr_text(name)[:60],
                                pdf_build_gone=bool(name), pages_build=cur_pages().name)
            return self._send(200, data, "application/pdf", cache="private, max-age=600")
        raise HTTPError(404, "없는 경로입니다: %s" % path)

    def _body(self) -> dict:
        raw = self._raw
        if not raw.strip():
            return {}
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            # 교차 출처 '단순 요청'(text/plain 폼)은 preflight 없이 온다 — JSON 만 받아 그 길을 닫는다.
            raise HTTPError(415, "본문은 Content-Type: application/json 으로 보내세요.")
        try:
            d = json.loads(raw)
        except (ValueError, RecursionError):
            raise HTTPError(400, "본문이 올바른 JSON 이 아닙니다.")
        if not isinstance(d, dict):
            raise HTTPError(400, "본문은 JSON 객체여야 합니다.")
        return d

    def _post(self):
        actor = self._guard()
        u = urlparse(self.path)
        path = u.path
        d = self._body()
        if path in ("/api/pick", "/api/pin", "/api/rebuild"):
            q = parse_qs(u.query)
            D = request_doc(q, d, file_hint=d.get("file") if path == "/api/pin" else None)
            with using_doc(D):
                return self._post_doc(actor, path, u, d)
        return self._post_doc(actor, path, u, d)

    def _post_doc(self, actor, path, u, d):
        m = re.fullmatch(r"/api/pins/(\d+)/(close|reopen|drop|restore|edit|claim|unclaim)", path)
        if m:
            pid, act = int(m.group(1)), m.group(2)
            if act == "drop":
                return self._json({"ok": drop_pin(pid, actor)})
            if act == "restore":
                return self._json({"ok": True, "pin": restore_pin(pid, actor)})
            if act == "edit":
                return self._json({"ok": True, "pin": edit_pin(pid, d, actor)})
            if act == "claim":
                ttl, eta = clean_claim_body(d)
                pin = claim_pin(pid, actor, ttl, eta)
                out = {"ok": pin is not None, "pin": pin, "ttl_min_applied": ttl}
                if eta is not None:
                    out["eta_min_applied"] = eta          # 상한(240)을 넘겨 보냈으면 깎인 값
                return self._json(out)
            if act == "unclaim":
                pin = unclaim_pin(pid, actor)
                return self._json({"ok": pin is not None, "pin": pin})
            reply = ref = None
            if act == "close":
                reply, ref = clean_close_body(d)
            pin = set_done(pid, act == "close", actor, reply, ref)
            return self._json({"ok": pin is not None, "pin": pin})
        if path == "/api/pick":
            return self._json(pick(d))
        if path == "/api/pin":
            return self._json({"id": add_pin(d, actor)})
        if path == "/api/clear":
            clear_pins()
            return self._json({"ok": True})
        if path == "/api/rebuild":
            if cur_doc().is_pdf:
                raise HTTPError(400, "보기 전용 문서(%s)는 재빌드하지 않습니다 — PDF 파일이 바뀌면 쪽을 저절로 다시 그립니다."
                                % cur_doc().key)
            full = (parse_qs(u.query).get("log") or ["0"])[0] == "1"
            if (parse_qs(u.query).get("async") or ["0"])[0] == "1":
                r = build_async()
                return self._json(r, 409 if r.get("busy") else 202)
            r = build_all()
            return self._json(diet_log(r, full), 409 if r.get("busy") else 200)
        raise HTTPError(404, "없는 경로입니다: %s" % path)


# ---------------------------------------------------------------- 진입점

def parse_doc_arg(spec: str, ms: Path) -> dict:
    """--doc <키>=<표시 이름>:<경로> 하나를 푼다. 경로는 --manuscript 기준 상대(권장) 또는 절대.

    - `<키>=<이름>:a/b/main.tex` — LaTeX. 빌드 루트는 그 .tex 가 있는 폴더(a/b).
    - `<키>=<이름>:a::b/main.tex` — LaTeX. 빌드 루트는 a(사본으로 복사하는 범위), 메인은 a/b/main.tex.
      빌드는 메인이 있는 폴더(a/b)에서 돈다 — 메인이 ../ 로 빌드 루트 안의 다른 폴더를 읽을 때 쓴다.
    - `<키>=<이름>:x/review.pdf` — 보기 전용 PDF(재빌드 없음, 쪽·영역 핀).
    키는 [a-z0-9-]{1,24}, 이름은 ':' 없이 40자 이하. 경로는 --manuscript 안이어야 한다(핀이 가리킬 수 있는 파일은
    원고 트리 안뿐이라는 보안 제약). 틀리면 ValueError(한국어 사유)."""
    if not isinstance(spec, str) or "=" not in spec:
        raise ValueError("--doc 는 <키>=<표시 이름>:<경로> 형식입니다: %r" % spec)
    key, rest = spec.split("=", 1)
    key = key.strip()
    if not DOC_KEY_RE.fullmatch(key):
        raise ValueError("--doc 키는 영문 소문자·숫자·'-' 1–24자여야 합니다: %r" % key)
    if ":" not in rest:
        raise ValueError("--doc %s: 표시 이름과 경로 사이에 ':' 가 없습니다: %r" % (key, spec))
    name, path = rest.split(":", 1)
    name = " ".join(name.split())
    if not name:
        raise ValueError("--doc %s: 표시 이름이 비었습니다" % key)
    if len(name) > DOC_NAME_MAX:
        raise ValueError("--doc %s: 표시 이름은 %d자 이하여야 합니다: %r" % (key, DOC_NAME_MAX, name))
    path = path.strip()
    if not path:
        raise ValueError("--doc %s: 경로가 비었습니다" % key)
    ms = ms.resolve()

    def inside(p: Path, what: str) -> Path:
        p = (p if p.is_absolute() else ms / p).resolve()
        try:
            p.relative_to(ms)
        except ValueError:
            raise ValueError("--doc %s: %s 가 --manuscript(%s) 밖입니다: %s" % (key, what, ms, p))
        return p

    if "::" in path:
        root_s, main_s = path.split("::", 1)
        if "::" in main_s or not root_s.strip() or not main_s.strip():
            raise ValueError("--doc %s: 확장 표기는 <빌드 루트>::<메인.tex> 하나입니다: %r" % (key, path))
        root = inside(Path(root_s.strip()), "빌드 루트")
        if not root.is_dir():
            raise ValueError("--doc %s: 빌드 루트 폴더가 없습니다: %s" % (key, root))
        mp = Path(main_s.strip())
        if mp.is_absolute():
            raise ValueError("--doc %s: '::' 뒤 메인은 빌드 루트 기준 상대경로입니다: %s" % (key, mp))
        main = (root / mp).resolve()
        try:
            main.relative_to(root)
        except ValueError:
            raise ValueError("--doc %s: 메인 .tex 가 빌드 루트 밖입니다: %s" % (key, main))
        if main.suffix.lower() != ".tex":
            raise ValueError("--doc %s: '::' 표기는 LaTeX 문서(.tex)에만 씁니다: %s" % (key, main))
    else:
        main = inside(Path(path), "경로")
        root = main.parent
    if not main.is_file():
        raise ValueError("--doc %s: 파일이 없습니다: %s" % (key, main))
    suf = main.suffix.lower()
    if suf == ".tex":
        kind = "tex"
    elif suf == ".pdf":
        kind = "pdf"
    else:
        raise ValueError("--doc %s: .tex(LaTeX) 또는 .pdf(보기 전용)만 받습니다: %s" % (key, main))
    return {"key": key, "name": name, "kind": kind, "src": root, "main": main}


def make_docs(specs: list, ms: Path) -> list:
    """--doc 목록 → Doc 목록. 키 중복·개수 상한을 본다. 키가 main 인 LaTeX 문서는 상태 폴더 루트 배치(root)를 쓴다."""
    if len(specs) > DOCS_MAX:
        raise ValueError("--doc 는 %d개까지입니다(지금 %d개)" % (DOCS_MAX, len(specs)))
    out, seen = [], set()
    for spec in specs:
        p = parse_doc_arg(spec, ms)
        if p["key"] in seen:
            raise ValueError("--doc 키가 겹칩니다: %s" % p["key"])
        seen.add(p["key"])
        out.append(Doc(p["key"], p["name"], p["kind"], src=p["src"], main=p["main"],
                       root=(p["key"] == DEFAULT_DOC_KEY and p["kind"] == "tex")))
    return out


def init_doc(D: Doc, no_build: bool, wait: bool) -> dict:
    """기동 준비 한 문서: 옛 배치 이관·빌드 이력 되살리기·(필요하면) 빌드. wait=False 면 백그라운드로 빌드한다."""
    with using_doc(D):
        D.dir.mkdir(parents=True, exist_ok=True)
        if D.root:
            migrate_pages()
        seed_builds()
        need = D.is_pdf and (pdf_changed(D) or not page_list())
        if not D.is_pdf:
            need = not no_build or not cur_pdf().exists() or not page_list()
        if not need:
            return {"state": "skip"}
        return build_all() if wait else build_async()


def watch_pdf_docs(stop: threading.Event, every: float = 3.0) -> None:
    """보기 전용 PDF 가 바뀌면(mtime·크기) 쪽을 다시 그린다. 재빌드 버튼 대신이다."""
    while not stop.wait(every):
        for D in list(DOCS):
            if D.is_pdf:
                try:
                    refresh_pdf_doc(D)
                except Exception:                     # noqa: BLE001 — 감시 스레드는 죽지 않는다
                    traceback.print_exc(file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manuscript", required=True, help="LaTeX 소스 루트 디렉토리")
    ap.add_argument("--main", help="최상위 .tex 파일명 (생략 시 자동 탐지). --doc 과 함께 쓰지 않는다")
    ap.add_argument("--doc", action="append", default=[], metavar="KEY=NAME:PATH",
                    help="뷰어가 전환할 문서(여러 번). PATH 는 --manuscript 기준. .tex = LaTeX(빌드 루트는 그 폴더), "
                         "<빌드 루트>::<메인.tex> = 빌드 루트를 따로 지정, .pdf = 보기 전용. 첫 문서가 기본이다. "
                         "생략하면 --manuscript·--main 의 문서 하나(키 main)")
    ap.add_argument("--port", type=int, help="생략 시 18300-18400 에서 빈 포트를 고른다")
    ap.add_argument("--state-dir", help="핀·빌드 산출물 위치")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--float-envs", default=DEFAULT_ENVS)
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--no-build", action="store_true", help="기동 시 재빌드하지 않는다")
    ap.add_argument("--allow", default="",
                    help="허용할 tailscale 로그인(쉼표 구분). 비우면 전원 허용. 신원 헤더 없는 루프백 요청"
                         "(curl·에이전트)은 항상 허용, 신원 헤더 없이 *.ts.net 으로 온 요청(태그 장치)은 거부")
    ap.add_argument("--no-origin-check", action="store_true",
                    help="Host·Origin 검사(DNS rebinding·CSRF 방어)를 끈다. tailscale serve 가 예상 밖의 "
                         "Host/Origin 을 넘겨 UI 가 403 을 받을 때만 쓴다")
    ap.add_argument("--git-pull", action="store_true",
                    help="재빌드(동기·비동기 모두)마다 copy 단계 전에 --manuscript 의 git 저장소를 "
                         "업스트림으로 --ff-only pull 한다. 더러움·분기·업스트림 없음이면 건너뛰고 "
                         "지금 체크아웃으로 빌드는 계속한다")
    ap.add_argument("--pdfjs-dir",
                    help="뷰어가 벡터로 그릴 때 쓰는 PDF.js 디렉토리(pdf.min.mjs·pdf.worker.min.mjs). 생략 시 "
                         "스크립트 옆 ../vendor/pdfjs 또는 ./vendor/pdfjs. 없으면 뷰어는 PNG 로 보인다")
    ap.add_argument("--label",
                    help="여러 논문 뷰어를 동시에 열었을 때 탭·도구 줄을 구분할 이름표(%d자 이하). 생략 시 "
                         "--manuscript 의 git origin 저장소 이름, git 이 아니면 폴더 이름" % LABEL_MAX)
    ap.add_argument("--accent",
                    help="이름표의 강조색(#rrggbb). 생략 시 이름표 문자열의 해시로 고정 팔레트에서 고른다"
                         "(같은 이름표는 항상 같은 색)")
    a = ap.parse_args()

    C.src = Path(a.manuscript).expanduser().resolve()
    if not C.src.is_dir():
        sys.exit("원고 디렉토리가 없습니다: %s" % C.src)
    if a.doc:
        if a.main:
            sys.exit("--doc 과 --main 은 함께 쓰지 않습니다 — 메인 파일은 --doc 경로로 정합니다.")
        try:
            docs = make_docs(a.doc, C.src)
        except ValueError as e:
            sys.exit(str(e))
        first_tex = next((d for d in docs if not d.is_pdf), docs[0])
        C.main = first_tex.main
    else:
        docs = None
        C.main = (C.src / a.main) if a.main else detect_main(C.src)
        if not C.main.exists():
            sys.exit("최상위 .tex 가 없습니다: %s" % C.main)

    default_state = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    C.state = Path(a.state_dir).expanduser().resolve() if a.state_dir \
        else default_state / "manuscript-pin-picker" / state_slug(C.src)
    C.state.mkdir(parents=True, exist_ok=True)
    C.build = C.state / "build"
    C.dpi = a.dpi
    C.envs = tuple(e.strip() for e in a.float_envs.split(",") if e.strip())
    C.timeout = a.build_timeout
    C.port = a.port or free_port()
    C.allow = frozenset(x.strip() for x in a.allow.split(",") if x.strip())
    C.origin_check = not a.no_origin_check
    C.git_pull = a.git_pull
    C.pdfjs_dir = Path(a.pdfjs_dir).expanduser().resolve() if a.pdfjs_dir else default_pdfjs_dir()
    C.repo = git_remote_url(C.src)
    # 기본 이름표(저장소 이름)는 길면 자른다 — 긴 저장소 이름 때문에 기동이 멈추면 안 된다(실측: 62자 저장소).
    # 직접 준 --label 만 길이 초과로 멈춘다(오타를 조용히 자르지 않게).
    C.label = clean_label(a.label) if a.label else clean_label(truncate_quote(default_label(C.src, C.repo), LABEL_MAX))
    if a.accent:
        if not valid_accent(a.accent):
            sys.exit("--accent 는 #rrggbb 형식이어야 합니다: %s" % a.accent)
        C.accent = a.accent.lower()
    else:
        C.accent = pick_accent(C.label)
    global HTML
    HTML = build_html(C.label, C.accent)

    set_docs(docs)
    init_seq()
    if not docs:
        migrate_pages()
        seed_builds()                # 옛 인스턴스가 만든 지금 빌드를 이력에 올리고 마지막 빌드 결과를 되살린다
        if not a.no_build or not cur_pdf().exists() or not page_list():
            r = build_all()
            if r.get("state") == "fail":
                sys.exit("빌드 실패:\n" + r.get("log", ""))
    else:
        # 여러 문서: 빌드는 문서마다 백그라운드로 돌리고 서버는 바로 뜬다(문서 N개 × 수십 초를 기다리지 않는다).
        # 실패해도 기동을 막지 않는다 — 그 문서 탭이 오류 패널을 연다.
        for D in DOCS:
            r = init_doc(D, a.no_build, wait=False)
            print("문서   %-10s %s %s%s" % (D.key, "보기 전용" if D.is_pdf else "LaTeX   ", D.rel_path(),
                                           "" if r.get("state") == "skip" else "  (빌드 시작)"))
        threading.Thread(target=watch_pdf_docs, args=(threading.Event(),), daemon=True).start()

    with PIN_LOCK:
        render_pins_md(read_pins()[0])
    print("원고   %s" % (C.src if docs else C.main))
    print("이름표 %s (%s)%s" % (C.label, C.accent, "" if C.repo else " — git origin 없음, 폴더 이름 기본값"))
    print("상태   %s" % C.state)
    print("주소   http://127.0.0.1:%d/   (외부 노출은 tailscale serve 로만)" % C.port)
    if C.allow:
        print("허용   %s (헤더 없는 루프백 요청은 허용)" % ", ".join(sorted(C.allow)))
    if not C.origin_check:
        print("경고   --no-origin-check: Host·Origin 검사를 껐습니다(DNS rebinding 방어 없음)")
    if C.git_pull:
        print("git-pull  재빌드마다 업스트림으로 --ff-only pull 합니다(실패해도 지금 체크아웃으로 빌드)")
    if vendor_file("pdf.min.mjs") and vendor_file("pdf.worker.min.mjs"):
        print("pdf.js %s (벡터 렌더링)" % C.pdfjs_dir)
    else:
        print("경고   pdf.js 가 없습니다(%s) — 뷰어는 PNG 로 보입니다" % C.pdfjs_dir)
    sys.stdout.flush()
    Server(("127.0.0.1", C.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
