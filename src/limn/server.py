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
바꾸는 플래그는 의도적으로 두지 않았다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

TOKEN_RE = re.compile(r"[가-힣]{2,}|[A-Za-z]{4,}|\d+\.\d+")
FLOAT_KINDS = ("figure", "table", "algorithm")
DEFAULT_ENVS = "figure,table,algorithm,equation,align,itemize,enumerate,minipage"


class Cfg:
    """실행 인자를 담는다. 프로젝트 고유값은 전부 여기를 거친다."""
    src: Path
    main: Path
    state: Path
    build: Path
    pages: Path
    pdf: Path
    port: int
    dpi: int
    envs: tuple
    timeout: int

    @property
    def pins_jsonl(self) -> Path:
        return self.state / "pins.jsonl"

    @property
    def pins_md(self) -> Path:
        return self.state / "pins.md"


C = Cfg()


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


def build_all() -> tuple[bool, str]:
    """원본을 건드리지 않고 사본에서 -synctex=1 로 빌드하고 페이지를 렌더한다."""
    C.build.mkdir(parents=True, exist_ok=True)
    C.pages.mkdir(parents=True, exist_ok=True)
    log = []

    rs = shutil.which("rsync")
    if rs:
        subprocess.run([rs, "-a", "--delete", "--exclude", "diff/", "--exclude", "*.synctex.gz",
                        str(C.src) + "/", str(C.build) + "/"], capture_output=True, timeout=300)
    else:                                            # rsync 없이도 돌아가야 한다
        shutil.rmtree(C.build, ignore_errors=True)
        shutil.copytree(C.src, C.build, ignore=shutil.ignore_patterns("diff", "*.synctex.gz"))

    r = subprocess.run(["latexmk", "-pdf", "-synctex=1", "-interaction=nonstopmode", C.main.name],
                       cwd=C.build, capture_output=True, text=True, timeout=C.timeout)
    (C.state / "build.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    log.append(r.stdout[-1500:])

    if not C.pdf.exists():
        return False, "PDF 가 나오지 않았습니다.\n" + "\n".join(log)
    if not C.pdf.with_suffix(".synctex.gz").exists():
        return False, "synctex.gz 가 없습니다 — latexmk 가 -synctex=1 을 받았는지 확인하세요."

    for old in C.pages.glob("page-*.png"):
        old.unlink()
    subprocess.run(["pdftoppm", "-r", str(C.dpi), "-png", str(C.pdf), str(C.pages / "page")],
                   capture_output=True, timeout=600)

    (C.state / "built_at.txt").write_text(datetime.now().astimezone().isoformat(timespec="seconds"))
    head = subprocess.run(["git", "-C", str(C.src), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True)
    (C.state / "head.txt").write_text(head.stdout.strip() or "-")
    return True, "ok"


# ---------------------------------------------------------------- 메타

def png_size(path: Path) -> tuple:
    with path.open("rb") as fh:
        return struct.unpack(">II", fh.read(24)[16:24])


def meta() -> dict:
    pages = []
    for p in sorted(C.pages.glob("page-*.png")):
        w, h = png_size(p)
        pages.append({"name": p.name, "pt_w": w * 72.0 / C.dpi, "pt_h": h * 72.0 / C.dpi})
    read = lambda f: (C.state / f).read_text().strip() if (C.state / f).exists() else "?"
    return {"pages": pages, "built_at": read("built_at.txt"), "head": read("head.txt"),
            "main": C.main.name, "n_open": len(live_pins())}


# ---------------------------------------------------------------- 원문 접근

def norm(line: str) -> str:
    return " ".join(line.split())


def tex_lines(path: Path) -> list:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def to_source(path: str) -> Path:
    """빌드 사본 경로를 원본 체크아웃 경로로 되돌린다."""
    p = Path(path)
    try:
        return C.src / p.relative_to(C.build)
    except ValueError:
        return p


# ---------------------------------------------------------------- 역변환 1: SyncTeX

def synctex_edit(page: int, x: float, y: float):
    try:
        out = subprocess.run(["synctex", "edit", "-o", "%d:%.2f:%.2f:%s" % (page, x, y, C.pdf)],
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


def by_synctex(page: int, x0: float, y0: float, x1: float, y1: float):
    w, h = x1 - x0, y1 - y0
    nx = max(2, min(5, int(w / 40) + 2))
    ny = max(2, min(6, int(h / 14) + 2))
    hits = []
    for i in range(nx):
        for j in range(ny):
            r = synctex_edit(page, x0 + w * (i + 0.5) / nx, y0 + h * (j + 0.5) / ny)
            if r:
                hits.append(r)
    if not hits:
        return None
    best = max({f for f, _ in hits}, key=lambda f: sum(1 for g, _ in hits if g == f))
    ls = densest(sorted(l for f, l in hits if f == best))
    return best, ls[0], ls[-1]


# ---------------------------------------------------------------- 역변환 2: 렌더 텍스트

def region_text(page: int, x0: float, y0: float, x1: float, y1: float) -> str:
    """선택 사각형 안에 실제로 찍힌 글자를 뽑는다(-r 72 이므로 1px = 1pt)."""
    try:
        return subprocess.run(
            ["pdftotext", "-f", str(page), "-l", str(page), "-r", "72",
             "-x", str(int(x0)), "-y", str(int(y0)),
             "-W", str(max(1, int(x1 - x0))), "-H", str(max(1, int(y1 - y0))), str(C.pdf), "-"],
            capture_output=True, text=True, timeout=15).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


_DF_CACHE: dict = {}


def token_weights(text: str, lines: list) -> list:
    """영역 텍스트의 어절에 희귀도 가중을 준다.

    가중이 없으면 '타겟'·'데이터'·'학습' 같은 흔한 말이 점수를 지배해, 실제로는
    Nomenclature 를 고른 선택이 본문 문단과도 높게 겹친다고 나온다(실측). 드문
    어절일수록 위치를 특정하는 힘이 크다."""
    key = (id(lines), len(lines))
    df = _DF_CACHE.get(key)
    if df is None:
        df = {}
        for ln in lines:
            for t in set(TOKEN_RE.findall(ln)):
                df[t] = df.get(t, 0) + 1
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


# ---------------------------------------------------------------- 블록 확장

def expand_block(lines: list, lo: int, hi: int):
    """선택 줄을 감싸는 환경 또는 문단 경계까지 넓힌다.

    환경은 반드시 같은 이름의 \\end 로 닫는다 — 이름을 안 맞추면 선택이 인접한 다른
    float 로 새어 나간다(실측: 표 하나를 골랐는데 109줄이 잡혔다)."""
    n = len(lines)
    if not n:
        return lo, hi, "none"
    lo, hi = max(1, min(lo, n)), max(lo, min(hi, n))
    alt = "|".join(C.envs)
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

    a, b = lo, hi
    while a > 1 and lines[a - 2].strip() and not lines[a - 2].lstrip().startswith("\\section"):
        a -= 1
    while b < n and lines[b].strip():
        b += 1
    return a, b, "paragraph"


def snippet(lines: list, lo: int, hi: int, cap: int = 80) -> str:
    chunk = lines[lo - 1:hi]
    extra = len(chunk) - cap
    if extra > 0:
        chunk = chunk[:cap]
    out = "\n".join("%5d  %s" % (lo + k, t) for k, t in enumerate(chunk))
    return out + ("\n      ... (%d줄 더)" % extra if extra > 0 else "")


# ---------------------------------------------------------------- 앵커와 재동기화

def anchor_of(lines: list, lo: int, hi: int) -> dict:
    """핀이 가리키는 블록의 머리·꼬리 텍스트를 떠 둔다.

    줄 번호만 저장하면 원고를 한 번 고치는 순간 모든 핀이 어긋난다. 이 도구를 쓰는
    이유가 '에이전트가 원고를 고친다'인데, 고치면 핀이 죽는 구조는 쓸 수 없다."""
    body = [norm(t) for t in lines[lo - 1:hi] if t.strip()]
    return {"head": body[0], "tail": body[-1]} if body else {}


def find_line(nlines: list, needle: str, near: int):
    if not needle:
        return None
    cands = [i for i, t in enumerate(nlines) if t == needle]
    if not cands and len(needle) >= 12:
        key = needle[:40]
        cands = [i for i, t in enumerate(nlines) if key in t]
    if not cands:
        return None
    return min(cands, key=lambda i: abs(i + 1 - near)) + 1


def sync_all(rows: list) -> bool:
    """원고가 핀보다 새로우면 앵커로 줄 번호를 다시 맞춘다."""
    changed = False
    cache: dict = {}
    for r in rows:
        if r.get("done"):
            continue
        f = Path(r["file"])
        if not f.exists():
            continue
        if f not in cache:
            ls = tex_lines(f)
            cache[f] = (ls, [norm(t) for t in ls], f.stat().st_mtime)
        lines, nlines, mtime = cache[f]
        if not r.get("anchor"):                      # 앵커 없이 저장된 옛 핀을 채운다
            r["anchor"] = anchor_of(lines, r["lo"], r["hi"])
            r["synced_at"] = mtime
            changed = True
            continue
        if r.get("synced_at", 0) >= mtime:
            continue
        anc = r["anchor"]
        lo = find_line(nlines, anc.get("head", ""), r["lo"])
        if lo is None:
            r["stale"], r["sync"] = True, "lost"
        else:
            hi = find_line(nlines, anc.get("tail", ""), lo + (r["hi"] - r["lo"]))
            if hi is None or hi < lo:
                hi = min(len(lines), lo + (r["hi"] - r["lo"]))
            r["sync"] = "ok" if (lo, hi) == (r["lo"], r["hi"]) else "moved %+d" % (lo - r["lo"])
            r["lo"], r["hi"] = lo, hi
            r.pop("stale", None)
        r["synced_at"] = mtime
        changed = True
    return changed


# ---------------------------------------------------------------- pins

def read_pins() -> list:
    if not C.pins_jsonl.exists():
        return []
    return [json.loads(t) for t in C.pins_jsonl.read_text(encoding="utf-8").splitlines() if t.strip()]


def write_pins(rows: list) -> None:
    C.pins_jsonl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                            encoding="utf-8")
    render_pins_md(rows)


def live_pins() -> list:
    rows = read_pins()
    if sync_all(rows):
        write_pins(rows)
    return [r for r in rows if not r.get("done")]


def add_pin(rec: dict) -> int:
    rows = read_pins()
    rec["at"] = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    rec["id"] = max((r["id"] for r in rows), default=0) + 1
    f = Path(rec["file"])
    rec["anchor"] = anchor_of(tex_lines(f), rec["lo"], rec["hi"])
    rec["synced_at"] = f.stat().st_mtime if f.exists() else 0
    rows.append(rec)
    write_pins(rows)
    return rec["id"]


def set_pin(pin_id: int, **fields) -> bool:
    rows = read_pins()
    hit = [r for r in rows if r["id"] == pin_id]
    for r in hit:
        r.update(fields)
    if hit:
        write_pins(rows)
    return bool(hit)


def drop_pin(pin_id: int) -> bool:
    rows = read_pins()
    kept = [r for r in rows if r["id"] != pin_id]
    if len(kept) == len(rows):
        return False
    write_pins(kept)
    return True


def render_pins_md(rows: list) -> None:
    """에이전트가 한 번에 읽을 요약. 스니펫은 일부러 넣지 않는다 —
    줄 범위만 있으면 에이전트가 원본을 직접 읽는 편이 항상 더 싸고 정확하다."""
    openn = [r for r in rows if not r.get("done")]
    out = ["# 수정 요청 핀", "",
           "원고: `%s`" % C.src,
           "갱신: %s  ·  열린 핀 %d건" % (datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"), len(openn)),
           "",
           "처리한 핀은 닫는다 — `curl -s -X POST http://127.0.0.1:%d/api/pins/N/close`" % C.port,
           "", "| # | 쪽 | 위치 | 종류 | 메모 |", "|---|---|---|---|---|"]
    for r in openn:
        flag = " ⚠원문에서 사라짐" if r.get("stale") else ""
        loc = "`%s L%d-L%d`%s" % (Path(r["file"]).name, r["lo"], r["hi"], flag)
        note = (r.get("note") or "").replace("|", "\\|").replace("\n", " ")
        out.append("| %d | %d | %s | %s | %s |" % (r["id"], r["page"], loc, r.get("kind", ""), note))
    if not openn:
        out.append("| — | — | 열린 핀 없음 | | |")
    done = [r for r in rows if r.get("done")]
    if done:
        out += ["", "<details><summary>닫힌 핀 %d건</summary>" % len(done), ""]
        out += ["- #%d p.%d `L%d-L%d` %s" % (r["id"], r["page"], r["lo"], r["hi"],
                                             (r.get("note") or "").replace("\n", " ")[:80]) for r in done]
        out += ["", "</details>"]
    C.pins_md.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 선택 해석

def pick(d: dict) -> dict:
    """드래그 영역 → 원문 줄 범위.

    SyncTeX 후보와 텍스트 후보를 같은 척도로 겨루게 한다. 어느 한쪽을 조건부
    폴백으로 두면, SyncTeX 가 조용히 틀렸을 때(minipage·tabular 안) 그 오답을
    걸러낼 방법이 없다."""
    page = int(d["page"])
    x0, y0, x1, y1 = d["x0"], d["y0"], d["x1"], d["y1"]
    rtext = region_text(page, x0, y0, x1, y1)
    sy = by_synctex(page, x0, y0, x1, y1)

    src = to_source(sy[0]) if sy else C.main
    if src.suffix in (".bbl", ".bib"):
        return {"error": "여기는 생성 파일(%s)입니다. 참고문헌은 .bib 나 본문 \\cite 를 고쳐야 합니다."
                         % src.suffix}

    lines = tex_lines(src)
    if not lines:
        return {"error": "원문 파일을 읽지 못했습니다: %s" % src}
    tw = token_weights(rtext, lines)

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

    lo, hi, kind = expand_block(lines, raw_lo, raw_hi)
    if not warn and len(cands) == 2 and abs(cands[0][3] - cands[1][3]) < 0.12:
        # 같은 블록으로 확장되면 두 경로가 갈린 것이 아니다 — 경고하지 않는다.
        if not (lo <= cands[1][1] <= hi):
            warn = "두 경로가 다른 곳을 가리킵니다(L%d / L%d). 확인이 필요합니다." % (cands[0][1], cands[1][1])

    return {"file": str(src), "name": src.name, "page": page, "lo": lo, "hi": hi,
            "raw_lo": raw_lo, "raw_hi": raw_hi, "kind": kind, "via": via,
            "score": round(best, 2), "warn": warn,
            "snippet": snippet(lines, lo, hi), "frac": d.get("frac")}


# ---------------------------------------------------------------- 뷰어

HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>원고 핀</title>
<style>
:root{--bg:#14161a;--pane:#1c1f25;--line:#2c313a;--fg:#e6e8ec;--dim:#98a0ad;--acc:#6ea8fe;--ok:#4ec9a0;--warn:#e0a458}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 -apple-system,"Pretendard","Noto Sans KR",sans-serif;
  display:flex;height:100vh;overflow:hidden}
#left{flex:1;overflow:auto;padding:16px 16px 60vh;min-width:240px}
#grip{width:6px;cursor:col-resize;background:var(--line);flex:none}
#grip:hover,#grip.on{background:var(--acc)}
#right{width:430px;min-width:280px;max-width:80vw;border-left:1px solid var(--line);background:var(--pane);
  display:flex;flex-direction:column;flex:none}
.bar{padding:8px 12px;border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;flex-wrap:wrap}
button{background:#2a2f38;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 10px;
  cursor:pointer;font-size:12.5px}
button:hover{background:#343b46}
button.p{background:var(--acc);color:#0b1220;border-color:var(--acc);font-weight:600}
button.x{padding:2px 7px;font-size:11px}
input,textarea{background:#12151a;color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 8px;
  font:inherit;width:100%}
input.n{width:58px;text-align:center}
.pg{position:relative;margin:0 auto 18px;box-shadow:0 2px 18px #0008}
.pg img{width:100%;display:block}
.pg .no{position:absolute;top:4px;left:-34px;color:var(--dim);font-size:12px}
.sel{position:absolute;border:2px solid var(--acc);background:#6ea8fe22;pointer-events:none}
.mark{position:absolute;border:2px solid var(--ok);background:#4ec9a01a;pointer-events:none}
.mark.st{border-color:var(--warn);background:#e0a4581a}
.mark b{position:absolute;top:-11px;left:-11px;background:var(--ok);color:#06231b;border-radius:50%;
  width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:12px}
.mark.st b{background:var(--warn);color:#2a1a04}
#res{flex:1;overflow:auto;padding:12px 14px}
pre{background:#0f1216;border:1px solid var(--line);border-radius:6px;padding:9px;overflow:auto;font-size:11.5px;
  line-height:1.5;max-height:44vh;font-family:"JetBrains Mono",ui-monospace,monospace;tab-size:2}
pre.wrap{white-space:pre-wrap;word-break:break-word}
pre.nowrap{white-space:pre}
.loc{font-family:ui-monospace,monospace;color:var(--acc);font-size:13px}
.dim{color:var(--dim);font-size:12px}
.pin{border:1px solid var(--line);border-radius:7px;padding:7px 9px;margin-bottom:6px;background:#181b21}
.pin.st{border-color:var(--warn)}
.pin .n{color:var(--ok);font-weight:700;margin-right:5px}
.pin .row{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.pin .sp{flex:1}
h3{margin:0 0 7px;font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em}
.hint{padding:22px 10px;color:var(--dim);font-size:13px;text-align:center;line-height:1.85}
kbd{background:#2a2f38;border:1px solid var(--line);border-radius:4px;padding:1px 5px;font-size:11px}
.tag{font-size:10.5px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--dim)}
.tag.t{border-color:var(--warn);color:var(--warn)}
</style></head><body>
<div id="left"><div id="doc"></div></div>
<div id="grip"></div>
<div id="right">
  <div class="bar">
    <button class="p" onclick="rebuild()">재빌드</button>
    <button onclick="loadPins()">새로고침</button>
    <span style="flex:1"></span>
    <input class="n" id="jump" placeholder="쪽" onkeydown="if(event.key==='Enter')goPage()">
    <button onclick="zoom(-1)">−</button><button onclick="zoom(1)">＋</button>
  </div>
  <div class="bar" style="padding-top:4px"><span class="dim" id="meta"></span></div>
  <div id="res"></div>
</div>
<script>
let META=null,PINS=[],CUR=null,W=900,WRAP=true;
const $=s=>document.querySelector(s);
const esc=t=>(t||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

// 사이드바 너비·본문 배율·줄바꿈은 세션을 넘겨 기억한다.
try{ const p=JSON.parse(localStorage.pinPrefs||'{}');
  if(p.side) $('#right').style.width=p.side+'px'; if(p.w) W=p.w; if(p.wrap!==undefined) WRAP=p.wrap; }catch(e){}
const savePrefs=()=>localStorage.pinPrefs=JSON.stringify(
  {side:parseInt(getComputedStyle($('#right')).width),w:W,wrap:WRAP});

(function(){ let on=false;
  $('#grip').addEventListener('mousedown',e=>{on=true;$('#grip').classList.add('on');
    document.body.style.userSelect='none';e.preventDefault();});
  window.addEventListener('mousemove',e=>{ if(!on)return;
    const w=Math.min(Math.max(280,window.innerWidth-e.clientX),window.innerWidth*0.8);
    $('#right').style.width=w+'px'; });
  window.addEventListener('mouseup',()=>{ if(!on)return;
    on=false;$('#grip').classList.remove('on');document.body.style.userSelect='';savePrefs(); });
})();

function zoom(d){ W=Math.min(2200,Math.max(420,W+d*140));
  document.querySelectorAll('.pg').forEach(e=>e.style.width=W+'px'); savePrefs(); }
function goPage(){ const el=document.getElementById('p'+parseInt($('#jump').value));
  if(el) el.scrollIntoView({behavior:'smooth'}); }

async function boot(){
  META=await (await fetch('/api/meta')).json();
  $('#meta').textContent=`${META.main} · ${META.pages.length}쪽 · ${META.head} · ${META.built_at.slice(0,16).replace('T',' ')}`;
  const doc=$('#doc'); doc.innerHTML='';
  META.pages.forEach((p,i)=>{
    const d=document.createElement('div'); d.className='pg'; d.id='p'+(i+1); d.style.width=W+'px';
    d.innerHTML=`<span class="no">${i+1}</span><img loading="lazy" src="/pages/${p.name}?v=${encodeURIComponent(META.built_at)}">`;
    doc.appendChild(d); wire(d,i+1,p);
  });
  idle(); loadPins();
}

function wire(el,page,pg){
  let sx,sy,box=null,drag=false;
  const rel=e=>{const r=el.getBoundingClientRect();return[(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height];};
  el.addEventListener('mousedown',e=>{ if(e.button!==0)return; drag=true; [sx,sy]=rel(e);
    box=document.createElement('div'); box.className='sel'; el.appendChild(box); e.preventDefault(); });
  window.addEventListener('mousemove',e=>{ if(!drag)return; const[x,y]=rel(e);
    Object.assign(box.style,{left:Math.min(sx,x)*100+'%',top:Math.min(sy,y)*100+'%',
      width:Math.abs(x-sx)*100+'%',height:Math.abs(y-sy)*100+'%'}); });
  window.addEventListener('mouseup',async e=>{ if(!drag)return; drag=false; const[x,y]=rel(e);
    const w=Math.abs(x-sx),h=Math.abs(y-sy); box.remove(); box=null;
    if(w<0.004&&h<0.004) return;
    await pick({page,x0:Math.min(sx,x)*pg.pt_w,y0:Math.min(sy,y)*pg.pt_h,
      x1:Math.max(sx,x)*pg.pt_w,y1:Math.max(sy,y)*pg.pt_h,frac:[Math.min(sx,x),Math.min(sy,y),w,h]}); });
}

function idle(){ $('#res').innerHTML=`<div class="hint">PDF 위에서 <b>드래그</b>해 영역을 고르면<br>
  그 자리의 <b>.tex 줄 번호</b>를 찾아 줍니다.<br><br>문장·문단·그림·표 무엇이든 됩니다.<br>
  메모를 달아 <kbd>핀</kbd> 으로 쌓으면<br>에이전트가 <code>pins.md</code> 한 장만 읽고 작업합니다.</div>
  <h3 style="margin-top:14px">쌓인 핀</h3><div id="pins"></div>`; drawPins(); }

async function pick(r){
  $('#res').innerHTML='<div class="hint">되짚는 중…</div>';
  const d=await (await fetch('/api/pick',{method:'POST',body:JSON.stringify(r)})).json();
  if(d.error){ $('#res').innerHTML=`<div class="hint">${esc(d.error)}</div>
    <h3 style="margin-top:14px">쌓인 핀</h3><div id="pins"></div>`; drawPins(); return; }
  CUR=d;
  const via={synctex:'SyncTeX',text:'렌더 텍스트'}[d.via]||d.via;
  $('#res').innerHTML=`
    <h3>선택한 자리</h3>
    <div class="loc">${esc(d.name)} L${d.lo}-L${d.hi}</div>
    <div class="dim">${d.page}쪽 · ${({float:'그림/표',block:'환경 블록',paragraph:'문단',none:'생성 파일'})[d.kind]||d.kind}
      · ${d.hi-d.lo+1}줄 · 정확매칭 L${d.raw_lo}-L${d.raw_hi} · <span class="tag">${via} ${d.score}</span></div>
    ${d.warn?`<div class="dim" style="color:var(--warn);margin-top:6px">${esc(d.warn)}</div>`:''}
    <div style="display:flex;gap:6px;margin:8px 0 4px">
      <button class="x" onclick="WRAP=!WRAP;savePrefs();document.querySelector('#res pre').className=WRAP?'wrap':'nowrap'">줄바꿈 토글</button>
      <button class="x" onclick="navigator.clipboard.writeText('${d.name} L${d.lo}-L${d.hi}')">줄범위 복사</button>
    </div>
    <pre class="${WRAP?'wrap':'nowrap'}">${esc(d.snippet)}</pre>
    <h3 style="margin-top:12px">메모</h3>
    <textarea id="note" rows="3" placeholder="여기를 어떻게 고칠지 (비워도 됩니다)"
      onkeydown="if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))savePin()"></textarea>
    <div style="margin-top:7px"><button class="p" onclick="savePin()">핀으로 쌓기 (⌘↵)</button></div>
    <h3 style="margin-top:16px">쌓인 핀</h3><div id="pins"></div>`;
  drawPins();
}

async function savePin(){
  if(!CUR)return; const d=Object.assign({},CUR); delete d.snippet; delete d.warn;
  d.note=($('#note')?.value||'').trim();
  await fetch('/api/pin',{method:'POST',body:JSON.stringify(d)});
  if($('#note')) $('#note').value=''; await loadPins();
}
async function loadPins(){ PINS=await (await fetch('/api/pins')).json(); drawPins(); marks(); }
function drawPins(){
  const el=$('#pins'); if(!el)return;
  el.innerHTML=PINS.length?PINS.map(p=>`<div class="pin ${p.stale?'st':''}">
    <div class="row"><span class="n">#${p.id}</span>
      <span class="loc">L${p.lo}-L${p.hi}</span><span class="dim">${p.page}쪽</span>
      ${p.stale?'<span class="tag t">원문에서 사라짐</span>':(p.sync&&p.sync!=='ok'?`<span class="tag">${esc(p.sync)}</span>`:'')}
      <span class="sp"></span>
      <button class="x" onclick="jumpPin(${p.id})">보기</button>
      <button class="x" onclick="closePin(${p.id})">완료</button>
      <button class="x" onclick="dropPin(${p.id})">삭제</button></div>
    ${p.note?`<div style="margin-top:4px">${esc(p.note)}</div>`:''}</div>`).join('')
    :'<div class="dim">아직 없습니다.</div>';
}
function marks(){
  document.querySelectorAll('.mark').forEach(m=>m.remove());
  PINS.forEach(p=>{ const el=document.getElementById('p'+p.page); if(!el||!p.frac)return;
    const m=document.createElement('div'); m.className='mark'+(p.stale?' st':'');
    Object.assign(m.style,{left:p.frac[0]*100+'%',top:p.frac[1]*100+'%',
      width:p.frac[2]*100+'%',height:p.frac[3]*100+'%'});
    m.innerHTML=`<b>${p.id}</b>`; el.appendChild(m); });
}
function jumpPin(id){ const p=PINS.find(x=>x.id===id);
  if(p) document.getElementById('p'+p.page)?.scrollIntoView({behavior:'smooth'}); }
async function closePin(id){ await fetch('/api/pins/'+id+'/close',{method:'POST'}); loadPins(); }
async function dropPin(id){ if(!confirm(`핀 #${id} 를 지웁니다.`))return;
  await fetch('/api/pins/'+id+'/drop',{method:'POST'}); loadPins(); }
async function rebuild(){ $('#meta').textContent='재빌드 중…';
  const r=await (await fetch('/api/rebuild',{method:'POST'})).json();
  if(r.ok) location.reload(); else { $('#meta').textContent='빌드 실패'; alert(r.log||'실패'); } }
boot();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=600" if ctype == "image/png" else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, HTML.encode(), "text/html; charset=utf-8")
        if path == "/api/meta":
            return self._json(meta())
        if path == "/api/pins":
            return self._json(live_pins())
        if path.startswith("/pages/"):
            f = C.pages / os.path.basename(path)
            if f.exists() and f.suffix == ".png":
                return self._send(200, f.read_bytes(), "image/png")
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        d = json.loads(self.rfile.read(n) or b"{}") if n else {}

        m = re.fullmatch(r"/api/pins/(\d+)/(close|reopen|drop)", path)
        if m:
            pid, act = int(m.group(1)), m.group(2)
            if act == "drop":
                return self._json({"ok": drop_pin(pid)})
            if act == "reopen":
                return self._json({"ok": set_pin(pid, done=False)})
            return self._json({"ok": set_pin(
                pid, done=True, done_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"))})
        if path == "/api/pick":
            return self._json(pick(d))
        if path == "/api/pin":
            return self._json({"id": add_pin(d)})
        if path == "/api/clear":
            if C.pins_jsonl.exists():
                C.pins_jsonl.rename(C.state / ("pins_%s.jsonl.bak" % time.strftime("%y%m%d_%H%M%S")))
            render_pins_md([])
            return self._json({"ok": True})
        if path == "/api/rebuild":
            ok, log = build_all()
            return self._json({"ok": ok, "log": log})
        return self._send(404, b"not found", "text/plain")


# ---------------------------------------------------------------- 진입점

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manuscript", required=True, help="LaTeX 소스 루트 디렉토리")
    ap.add_argument("--main", help="최상위 .tex 파일명 (생략 시 자동 탐지)")
    ap.add_argument("--port", type=int, help="생략 시 18300-18400 에서 빈 포트를 고른다")
    ap.add_argument("--state-dir", help="핀·빌드 산출물 위치")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--float-envs", default=DEFAULT_ENVS)
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--no-build", action="store_true", help="기동 시 재빌드하지 않는다")
    a = ap.parse_args()

    C.src = Path(a.manuscript).expanduser().resolve()
    if not C.src.is_dir():
        sys.exit("원고 디렉토리가 없습니다: %s" % C.src)
    C.main = (C.src / a.main) if a.main else detect_main(C.src)
    if not C.main.exists():
        sys.exit("최상위 .tex 가 없습니다: %s" % C.main)

    default_state = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    C.state = Path(a.state_dir).expanduser().resolve() if a.state_dir \
        else default_state / "manuscript-pin-picker" / state_slug(C.src)
    C.state.mkdir(parents=True, exist_ok=True)
    C.build = C.state / "build"
    C.pages = C.state / "pages"
    C.pdf = C.build / (C.main.stem + ".pdf")
    C.dpi = a.dpi
    C.envs = tuple(e.strip() for e in a.float_envs.split(",") if e.strip())
    C.timeout = a.build_timeout
    C.port = a.port or free_port()

    if not a.no_build or not C.pdf.exists():
        ok, log = build_all()
        if not ok:
            sys.exit("빌드 실패:\n" + log)

    render_pins_md(read_pins())
    print("원고   %s" % C.main)
    print("상태   %s" % C.state)
    print("주소   http://127.0.0.1:%d/   (외부 노출은 tailscale serve 로만)" % C.port)
    ThreadingHTTPServer(("127.0.0.1", C.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
