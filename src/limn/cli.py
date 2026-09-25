"""`limn` 명령 — 서버 실행(serve)·판 번호(version)·인스턴스 관리(add·start·…)를 한 곳에서 받는다.

인스턴스 관리는 같은 패키지의 instances.sh 가 한다. 여기서는 그 스크립트가 쓸 경로(파이썬·서버·유닛
템플릿·실행 파일)와 판 번호를 환경 변수로 넘겨 bash 로 넘긴다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from limn import __version__

HERE = Path(__file__).resolve().parent

HELP = """\
limn {version} — 원고 PDF에 핀을 찍으면 그 자리의 소스 줄로 이어 주는 퇴고 도구

  limn serve --manuscript <폴더> [서버 인자…]   서버 하나를 바로 띄운다(limn serve --help)
  limn version                                  설치된 판
  limn migrate [--dry-run] [--move-state] …     이전 이름의 설정·상태를 Limn 으로 옮긴다(limn migrate --help)

인스턴스(원고마다 systemd 유닛 limn@<이름> 하나):
"""


def limn_bin() -> str:
    """systemd 유닛의 ExecStart 에 적을 limn 실행 파일 — 지금 부른 그 파일을 우선한다."""
    argv0 = Path(sys.argv[0])
    if argv0.name == "limn" and argv0.exists():
        # 심링크를 풀지 않는다 — uv 의 bin 폴더(~/.local/bin/limn)가 판을 바꿔도 그대로인 경로다.
        return os.path.abspath(argv0)
    return shutil.which("limn") or str(Path.home() / ".local" / "bin" / "limn")


def instances_env() -> dict:
    env = dict(os.environ)
    env.setdefault("LIMN_PYTHON", sys.executable)
    env.setdefault("LIMN_SERVER", str(HERE / "server.py"))
    env.setdefault("LIMN_UNIT_TEMPLATE", str(HERE / "systemd" / "limn@.service"))
    env.setdefault("LIMN_BIN", limn_bin())
    env["LIMN_VERSION"] = __version__
    return env


def run_instances(args: list) -> int:
    bash = shutil.which("bash")
    if not bash:
        print("limn: bash 가 필요합니다", file=sys.stderr)
        return 1
    argv = [bash, str(HERE / "instances.sh"), *args]
    os.execve(bash, argv, instances_env())
    return 1  # 닿지 않는다


def main(argv: list | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else ""
    if cmd in ("version", "--version", "-V"):
        print("limn %s" % __version__)
        return 0
    if cmd == "serve":
        from limn import server
        sys.argv = ["limn serve", *args[1:]]
        server.main()
        return 0
    if cmd == "migrate":
        from limn import migrate
        return migrate.main(args[1:])
    if cmd in ("", "-h", "--help", "help"):
        sys.stdout.write(HELP.format(version=__version__))
        sys.stdout.flush()
    return run_instances(args)


if __name__ == "__main__":
    raise SystemExit(main())
