# Limn — 에이전트 안내

Limn은 LaTeX 원고 PDF에서 드래그한 영역을 `.tex` 파일·줄 범위로 되돌려 주고, 사람과 에이전트가 함께 처리하는 **핀**으로 관리하는 서버다. 이 파일은 이 저장소에서 일하는 에이전트의 입구다.

## 먼저 읽을 것

설계의 정본은 System Handbook [`docs/handbook/`](docs/handbook/index.md)이다. 작업과 관련된 topic만 골라 읽는다.

| 할 일 | 읽을 topic |
| --- | --- |
| 무엇이든 처음 | [purpose.md](docs/handbook/purpose.md) — 목적과 영역별 진실 소스 |
| 코드를 놓을 자리, 의존성·저장·보안 경계 | [architecture.md](docs/handbook/architecture.md) — 불변식과 멈춤 신호 |
| 코드를 쓰거나 리뷰 | [code-style-roadmap.md](docs/handbook/code-style-roadmap.md) — 코딩 규칙 우선순위와 단계 |
| 핀 규칙·위치 계산 | [domain.md](docs/handbook/domain.md) |
| 뷰어 화면 | [viewer.md](docs/handbook/viewer.md) |
| 빌드·동기화 | [build-sync.md](docs/handbook/build-sync.md) |
| HTTP API·`pins.md` | [api.md](docs/handbook/api.md) — 에이전트 계약, 호환을 깨지 않는다 |
| 테스트·합격 기준 | [verification.md](docs/handbook/verification.md) |
| 변경 절차·ADR·릴리스 | [workflow.md](docs/handbook/workflow.md) |

결정 이유는 [`docs/adr/`](docs/adr/)에 있다.

## 반드시 지킬 것

- 서버는 기본 `127.0.0.1`에 묶고, loopback 밖 바인드는 `--auth trusted-proxy`일 때만 허용한다. 신원·토큰·역할 코드는 보안 경계다. 서버 런타임은 표준 라이브러리만 쓴다 (`dependencies = []`).
- `pins.md` 형식과 HTTP API(경로·필드·상태 이름)는 다른 저장소의 에이전트가 읽는 계약이다. 더하기만 하고, 바꾸려면 먼저 설계 승인을 받는다.
- 핀 파일은 `transact()`의 잠금·순서를 거쳐서만 쓴다.
- 코딩 규칙은 팀 스킬(`code-implement`, `code-testing`, `code-security`)이 기존 코드 관례보다 우선한다.
- 코드·주석·docstring·커밋 메시지는 영어, Handbook은 한국어. `README`와 `skill/SKILL`은 영어·한국어 두 벌을 함께 고친다.
- 앱 이름은 Limn 하나. 실제 이메일·홈 경로·호스트 이름을 넣지 않는다 (`alice@example.com` 형식을 쓴다).
- [architecture.md](docs/handbook/architecture.md) §멈춤 신호에 걸리면 코드를 쓰기 전에 멈추고 묻는다.

## 검증

```bash
uv sync --group dev
uv run pytest -q -rs
bash tests/test_instances.sh
uv run ruff check
uv run ruff format --check
uv run shellcheck src/limn/instances.sh tests/test_instances.sh
uv run mypy
```

현재 상태를 바꾼 변경은 해당 Handbook topic을 같은 변경에서 고친다.

## 스킬

이 저장소는 skm으로 프로젝트 스킬을 관리한다 (`.agents/skills.toml`). `.agents/skills/` 안의 심링크는 머신 전역 스킬이라 여기서 고치지 않는다.
