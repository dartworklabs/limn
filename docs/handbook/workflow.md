# 변경 흐름 — 설계에서 릴리스까지

이 topic은 Limn에 변경이 들어오는 순서를 설명한다. 설계와 승인, 구현, 검수, 문서 동기화, 릴리스가 어떤 순서로 이어지는지, 그리고 경로가 달라지는 경우(설계 이탈, 탐색, 긴급 수정)를 적는다. 작업을 시작하기 전과 PR을 올리기 전에 읽는다. 절차나 기여 조건이 바뀌면 이 파일과 [CONTRIBUTING.md](../../CONTRIBUTING.md)를 같이 고친다.

## 기본 경로

변경은 다음 순서로 흐른다. 작은 변경은 단계를 짧게 거치지만 순서를 건너뛰지는 않는다.

1. **관련 규칙 읽기.** [index.md](index.md) 목록에서 작업과 관련된 topic만 골라 읽는다. 구조를 건드리면 [architecture.md](architecture.md), 핀 규칙이면 [domain.md](domain.md), 화면이면 [viewer.md](viewer.md)다.
2. **설계.** 새 기능이나 동작 변경이면 요구사항·범위·비범위를 먼저 정리한다. 무엇을 만들지 합의되기 전에는 구현하지 않는다.
3. **계획.** 설계가 승인되면 검증 지점이 붙은 작업 단위로 나눈다.
4. **구현.** 우리 코딩 스킬(`code-implement`, 테스트는 `code-testing`, 신뢰 경계는 `code-security`)을 따른다. 기존 코드의 관례와 스킬이 부딪히면 **스킬이 우선**이다. 적용 순서는 [code-style-roadmap.md](code-style-roadmap.md)에 있다.
5. **위반 검사.** 구현 중이나 직후에 diff가 [architecture.md](architecture.md) §멈춤 신호에 걸리는지 본다. 걸리면 멈추고 설계 판단을 받는다.
6. **검수.** [verification.md](verification.md)의 해당 게이트를 돌리고, 설계 의도대로 됐는지 확인한다. 테스트 녹색만으로 합격이 아니다.
7. **문서 동기화.** 시스템의 현재 상태가 바뀌었으면 해당 Handbook topic을 같은 PR에서 고친다. 무엇을 고칠지는 [index.md](index.md)의 "read or update when" 열이 알려 준다.
8. **머지와 릴리스.** CI가 녹색이고 리뷰가 끝나면 `main`에 머지한다. 릴리스는 §릴리스를 따른다.

> **핵심**
>
> 행동 계약을 바꾸는 변경은 **설계 승인 뒤에만** 구현한다. 여기서 행동 계약은 에이전트 계약(`pins.md`, HTTP API), 보안 경계(바인드 주소, Host·Origin 검사, 신원 신뢰), 저장 형식(상태 디렉터리 파일과 레코드 필드)이다. 이 세 가지는 한번 퍼지면 되돌리기 어렵다.

## 경로가 달라지는 경우

| 상황 | 경로 |
| --- | --- |
| 기본 청사진이나 채택한 설계 축에서 벗어나야 한다 | 멈추고 ADR 초안을 쓴다. ADR이 승인되면 [architecture.md](architecture.md)의 채택값을 같은 변경에서 고친다 |
| 해 보기 전에는 설계를 정할 수 없다 (탐색) | 버릴 수 있는 브랜치에서 짧게 시도한다. 결과를 바탕으로 설계를 사후에 적고 승인받은 뒤 정식으로 구현한다. 탐색 코드를 그대로 머지하지 않는다 |
| 운영 중인 인스턴스가 망가졌다 (긴급) | 먼저 `limn update --ref <이전 태그>`로 되돌린다 ([instances.md](instances.md) §업데이트와 되돌리기). 원인을 고치는 변경은 기본 경로로 들어온다 |
| 문서만 고친다 | 설계 단계는 없다. [verification.md](verification.md) §1을 돌린다. 일부 테스트가 문서 문장을 확인하기 때문이다 |

## ADR을 쓰는 때

ADR(Architecture Decision Record)은 되돌리기 어렵거나 대가가 있는 결정을, 그 이유와 버린 대안과 함께 남기는 짧은 기록이다. `docs/adr/`에 번호순으로 둔다.

- 새 ADR은 `제안` 상태로 시작한다. 승인되면 `확정`이 되고, 확정된 ADR의 본문은 고치지 않는다. 결정이 바뀌면 새 ADR을 쓰고 옛 ADR의 상태 행만 "ADR-NNNN으로 대체"로 바꾼다.
- ADR은 이유를 보존하는 기록이지 현재값의 정본이 아니다. 현재값은 [purpose.md](purpose.md) §진실 소스가 가리키는 곳에 있다.

현재 ADR:

| 번호 | 제목 | 상태 |
| --- | --- | --- |
| [0001](../adr/0001-blueprint.md) | Limn 청사진 결정 | 확정 (2026-09-26) |
| [0002](../adr/0002-access-control.md) | 접근 제어·협업 경계·동기화 | v0.2 확정·구현, 이후 제안 |
| [0003](../adr/0003-tailnet-headerless-and-owner-clear.md) | 테일넷의 헤더 없는 요청 거부와 소유자 전용 전체 지우기 | 확정·구현 (0.2.1) |
| [0004](../adr/0004-one-reply-trash-sections.md) | 답글 하나와 서버 규칙, 휴지통, 접는 목록 구획 | 확정·구현 (0.2.2) |
| [0005](../adr/0005-pin-scoped-changes.md) | 핀 단위 [변경 보기] | 확정·구현 (0.3.0) |
| [0006](../adr/0006-relative-pin-paths.md) | 핀의 상대 경로 `file_rel`과 옮긴 원고 | 제안 |

## PR과 기여 조건

- 변경은 작게 유지하고, 동작이 바뀌면 테스트를 더하거나 고친다.
- PR 템플릿의 체크 항목을 채운다. 테스트 통과, 에이전트 계약 불변(또는 이슈에서 먼저 논의), CLA 동의다.
- 기여는 [CLA.md](../../CLA.md) 조건에서만 받는다. 커밋마다 `git commit -s`로 서명하고, CLA 동의 줄을 덧붙인다. 정확한 문구는 [CONTRIBUTING.md](../../CONTRIBUTING.md)에 있다.
- 코드·주석·docstring·테스트 이름·커밋 메시지·CLI 도움말·로그는 영어로 쓴다. Handbook과 [README.ko.md](../../README.ko.md)는 한국어, [README.md](../../README.md)와 [SKILL.md](../../skill/SKILL.md)는 영어다. SKILL은 영어·한국어 두 벌을 함께 고친다.

## 릴리스

버전의 정본은 [`src/limn/__init__.py`](../../src/limn/__init__.py)의 `__version__`이다. `pyproject.toml`은 hatch로 이 값을 읽는다.

1. `__version__`을 올리고 [CHANGELOG.md](../../CHANGELOG.md)에 날짜와 변경 요약을 적는다. 에이전트 계약이 바뀌지 않았다면 그 사실도 적는다.
2. `main`에 머지한 뒤 `vX.Y.Z` 태그를 단다. 태그 푸시에서도 CI가 돈다.
3. 각 머신의 운영자는 `limn update`로 최신 태그를 설치하고 실행 중인 인스턴스를 재시작한다. `--dry-run`으로 계획을 먼저 볼 수 있다. 상세는 [instances.md](instances.md)다.

> **참고**
>
> 배포 상태의 정본은 머신마다 `uv tool`로 설치된 패키지 버전이다. 인스턴스가 실제로 돌리는 버전은 `limn version` 또는 `GET /api/version`으로 확인한다.
