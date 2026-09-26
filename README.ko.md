[English](README.md) | 한국어

# Limn (림)

**Limn**(림, "또렷이 그려 내다")은 LaTeX 원고를 사람과 에이전트가 함께 퇴고하는 사이클을 닫는다.
PDF 에서 고칠 곳을 드래그하고 메모를 남기면 Limn 이 그것을 **핀**으로 만든다 — SyncTeX 로 되찾고
본문 글자로 교차 확인한 `.tex` 파일·줄 범위와 메모다. 에이전트는 핀을 짧은 작업 목록(`pins.md`, 핀 하나에
약 35 토큰 — 스크린샷 한 장은 1,500 토큰)으로 읽어 소스를 고치고, 무엇을 고쳤는지 남기며 핀을 닫는다.
사람이 확인하면 끝난다. 같은 사설망의 공저자도 핀을 남기고, 누가 남겼는지 기록된다.

- 표준 라이브러리만 쓰는 Python 서버 하나, PDF 를 벡터로 그리는 브라우저 뷰어(PDF.js 동봉)
- 원고 하나에 여러 문서(본문·답변서·보기 전용 리뷰어 PDF)를 탭으로
- 요청하거나 업스트림 브랜치가 움직이면 재빌드(`--git-pull`)
- 스레드·질문·@태그·담당·완료 전 검토·핀별 변경 보기
- 닫힌 핀에는 [답글] 하나: 사람이 단 답글은 핀을 에이전트에게 되돌린다(보내기 전 한 줄로 알리고, 보낸 뒤 되돌릴 수 있다). 삭제한 핀은 30일 동안 휴지통에
- 원고마다 오래 도는 **인스턴스** 하나(systemd 사용자 유닛), `tailscale serve` 로 노출

## 설치

Python 3.10 이상, [uv](https://docs.astral.sh/uv/), SyncTeX 가 되는 TeX 배포판(`latexmk`/`pdflatex`),
Poppler(`pdftoppm`)가 필요하다.

```bash
uv tool install git+https://github.com/dartworklabs/limn@v0.2.2
limn version
```

GitHub SSH 접근이 있으면 `git+ssh://git@github.com/dartworklabs/limn@v0.2.2` 도 된다.

## 서버 하나 띄우기

```bash
limn serve --manuscript ~/papers/paper2 --main main.tex --port 18300
# 여러 문서를 탭으로:
limn serve --manuscript ~/papers/paper2 \
  --doc 'ms=본문:manuscript/main.tex' --doc 'rr=답변서:submission/review_response/review_response.tex'
```

기본으로 `127.0.0.1` 에만 붙는다. `http://127.0.0.1:18300/` 을 연다. 테일넷에 나누려면
`tailscale serve --bg --https=18200 http://127.0.0.1:18300`. 옵션은 `limn serve --help`. 상태(핀·빌드)는
`--state-dir` 또는 `~/.local/share/limn/serve/<원고>-<해시>` 에 쌓인다.

> **보안:** 신원 방식(identity provider) 없이 Limn 을 밖에 열지 않는다. 기본값(`--auth tailscale`)은
> `127.0.0.1` 에 붙고 `tailscale serve` 가 붙여 주는 신원 헤더를 믿는다. 포트에 닿는 테일넷 사람은 누구나
> 공동 작업자이며, 좁히려면 `--members-only` 와 `limn member` 역할을 쓴다. `--auth local` 은 자기 머신의 한
> 사람용이고, `--auth trusted-proxy` 는 인증 리버스 프록시 뒤에서 쓰며 loopback 이 아닌 주소에 `--bind` 할 수
> 있는 유일한 방식이다. 에이전트는 API 토큰(`limn token create`)을 쓴다. 프록시 없는 공개 주소도,
> `tailscale funnel` 도 안 된다. [SECURITY.md](SECURITY.md) 참고.

## 인스턴스 (원고마다 하나)

```bash
limn add paper2 --manuscript ~/papers/paper2 --git-pull   # 포트·설정·systemd 유닛 limn@paper2·tailscale serve
limn list                                                  # 이름표·포트·상태·열린 핀·문서 수
limn status paper2 · limn url paper2 · limn snippet paper2 # 자세히 · 테일넷 주소 · AGENTS.md 조각
limn update [--dry-run] [--ref vX.Y.Z]                     # uv tool 로 다시 설치, 켜진 인스턴스 재시작
limn stop paper2 · limn start paper2 · limn remove paper2
limn token create paper2 · limn member add paper2 <login> --role viewer   # 에이전트 토큰(한 번만 보임) · 역할
limn token create paper2 --save                            # 이 머신 에이전트의 토큰 파일 ~/.config/limn/paper2.token
```

설정은 `~/.config/limn/<이름>.env`, 상태는 기본 `~/.local/share/limn/<이름>`.
자세히: [docs/handbook/instances.md](docs/handbook/instances.md).

## 에이전트에게

에이전트는 `pins.md`(`curl -s <base>/pins.md`) 또는 `GET /api/pins` 를 읽고, 고치기 직전에 그 핀 하나만
claim 한 뒤, `reply`(무엇을 고쳤는지)와 `ref`(커밋·PR)를 남겨 닫는다. 사람이 확인하거나, 틀린 점을
답글로 달면 핀이 다시 열려 열린 표로 돌아온다. 인증은
`limn token create <인스턴스>` 로 받은 토큰(`Authorization: Bearer …`)으로 한다. 인스턴스를 띄운 머신의
에이전트는 토큰을 `~/.config/limn/<인스턴스>.token`(`limn token create <인스턴스> --save`)에서 읽는다. 에이전트는
확인(confirm)하지 않고, 남이 claim 한 핀·검토 대기 핀·담당이 사람인 핀은 건너뛴다. 전체 절차는
[skill/SKILL.ko.md](skill/SKILL.ko.md), API 계약은 [docs/handbook/api.md](docs/handbook/api.md). `pins.md` 형식과 HTTP API 는
고정된 계약이라 UI 언어와 상관없이 바뀌지 않는다.

## 문서

| | |
|---|---|
| [skill/SKILL.ko.md](skill/SKILL.ko.md) | 에이전트 절차(에이전트 런타임에 스킬로 설치) |
| [docs/handbook/](docs/handbook/index.md) | System Handbook: 목적·구조·핀 도메인·뷰어·빌드와 동기화·HTTP API 와 `pins.md` 형식·운영·인스턴스·검증·변경 흐름·코딩 로드맵 |
| [docs/adr/](docs/adr/) | 설계 결정 기록(ADR) |
| [SECURITY.md](SECURITY.md) · [CONTRIBUTING.md](CONTRIBUTING.md) · [CHANGELOG.md](CHANGELOG.md) | |

접근 제어 계획: [ADR-0002 접근 제어·협업 경계·동기화](docs/adr/0002-access-control.md) (제안).

## 라이선스

Limn is licensed under AGPL-3.0-only. Commercial licenses are available from Dartwork (contact via GitHub issues for now).
동봉한 제3자 구성 요소: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). 이름과 로고: [TRADEMARKS.md](TRADEMARKS.md).

## 출처와 이전

Limn 은 2026-09-21 writing-agent-playbook 저장소의 `manuscript-pin-picker` 스킬(서버
`scripts/pin_server.py`)로 시작했고, 논문별 인스턴스 관리 도구 `bin/pin-viewer.sh`(systemd 유닛
`pin-viewer@<이름>`, 2026-09-23부터)는 dotfiles 저장소에 있었다. 2026-09-25 둘을 이력째 이 저장소로
옮기고(`git filter-repo`, `--allow-unrelated-histories` 로 합침) 이름을 Limn 으로 바꿨다. 가져온 이력의
개인 정보는 자리표시자로 바꿨다.

### `pin-viewer@<이름>` 에서 옮기기

아무 것도 지우지 않는다. 포트·테일넷 주소·핀이 그대로 이어진다.

```bash
uv tool install git+https://github.com/dartworklabs/limn@v0.2.2
limn migrate --dry-run            # 계획: ~/.config/pin-viewer/<이름>.env -> ~/.config/limn/<이름>.env
limn migrate                      # 설정 복사(여러 번 불러도 같다, 옛 파일은 남는다)
# 인스턴스마다:
systemctl --user disable --now pin-viewer@<이름>.service
limn start <이름>                 # limn@.service 를 쓰고 limn@<이름> 기동, 200 대기. serve 항목은 그대로
limn status <이름>                # active, 로컬 200, 테일넷 주소, 열린 핀 수가 같은지
```

상태 폴더는 제자리에 둔다(새 설정이 그 경로를 가리킨다). `~/.local/share/pin-viewer/<이름>` 의 상태를
`~/.local/share/limn/<이름>` 으로 옮기려면 옛 유닛을 끈 뒤, `limn start` 전에
`limn migrate --move-state <이름>` 을 실행한다. 모든 인스턴스가 `limn@` 으로 돌면
`~/.config/systemd/user/pin-viewer@.service`·`~/.config/pin-viewer/`·옛 `~/.local/bin/pin-viewer` 는 지워도 된다.
