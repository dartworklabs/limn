# ADR-0012: 테스트 동거의 실제 경로와 루트 `tests/`의 끝 상태

| | |
|---|---|
| **번호** | ADR-0012 |
| **제목** | 테스트 동거의 실제 경로와 루트 `tests/`의 끝 상태 |
| **상태** | 제안 |
| **결정일** | 2026-10-03 |
| **결정자** | 프로젝트 소유자 |
| **명료화** | ADR-0010 결정 1(동거 기본값과 테스트 동거)의 슬라이스 경로와 루트 `tests/`의 끝 상태, 결과·현재 상태 투영의 갱신 대상 |
| **출처** | [ADR-0010](0010-coding-stances-and-test-colocation.md), [verification.md](../handbook/verification.md) §테스트 파일의 배치 |

## 맥락

ADR-0010은 세로 슬라이스가 테스트를 함께 소유한다고 정했다. 그 원문에는 지금 저장소와 맞지 않는 표현이 셋 있다. 승인된 ADR은 고치지 않으므로([workflow.md](../handbook/workflow.md) §결정 기록) 해석을 이 기록에서 확정한다.

1. 슬라이스 경로를 `src/limn/features/`로 적었다. 그런 폴더는 없다. 기능 패키지는 `src/limn/` 바로 아래(`pins`, `builds`, `revisions`, `sync`, `documents`, `collaboration`, `administration`)에 있고, 공통 경계(`security`, `web`, `runtime`, `platform`, `viewer`)도 같은 층에 있다.
2. 루트 `tests/`의 레거시 테스트를 "점진적으로 이관·해체"한다고 적었다. 이관이 끝난 지금 루트에는 여러 기능을 가로지르는 계약·구조 검사와 공용 도우미가 남는다. 이것들은 어느 한 슬라이스의 것이 아니다.
3. 결과 절이 ADR 목록을 "`docs/handbook/index.md`의 결정 기록 표"에 둔다고 적었다. ADR 목록은 [`docs/adr/index.md`](index.md)에 있다. 또 결과 절의 `architecture.md` 링크는 `docs/adr/` 기준으로 풀리지 않는다.

## 결정

ADR-0010 결정 1을 다음 뜻으로 읽는다.

- **슬라이스 경로.** "`src/limn/features/<기능>`"은 `src/limn/<기능>/`이다. 기능의 테스트는 `src/limn/<기능>/tests/`(핀의 동작별 슬라이스는 `src/limn/pins/<동작>/tests/`)에 둔다. 공통 경계 패키지도 자기 `tests/`를 가진다.
- **루트 `tests/`의 끝 상태.** 루트 `tests/`는 해체하지 않는다. 여러 기능을 함께 관찰하는 계약 검사(`tests/contracts/`), 저장소 전체의 구조·문서 검사(`tests/architecture/`), 도구 검사(`tests/tools/`), 수집하지 않는 공용 도우미와 고정 입력(`tests/support/`, `tests/data/`)을 둔다. 한 슬라이스만 관찰하는 테스트는 그 슬라이스로 간다. 이 배치로 ADR-0010의 테스트 동거 이관은 끝난 것으로 본다.
- **갱신 대상.** ADR-0010 결과 절의 "결정 기록 표"는 `docs/adr/index.md`이고, `architecture.md`는 [`docs/handbook/architecture.md`](../handbook/architecture.md)다.

ADR-0010의 나머지 결정(code-testing·code-security 원칙 채택, 설계 결정 트리거)은 그대로다.

## Trade-off

**장점:**
- 원문의 없는 경로와 "해체"라는 끝 상태 때문에 루트 `tests/`의 계약 검사를 슬라이스로 쪼개려는 오해가 생기지 않는다.
- 동거 이관의 완료 조건이 정해진다.

**단점·포기한 것:**
- 루트 `tests/`가 남으므로 "모든 테스트가 슬라이스 안"이라는 단순한 규칙은 아니다. 여러 기능을 함께 보는 검사의 자리를 따로 판단해야 한다.

## 대안

| 대안 | 선택하지 않은 이유 |
| --- | --- |
| 루트 계약 검사를 관련 슬라이스마다 나눠 옮긴다 | 계약 스냅샷과 구조 검사는 여러 기능을 함께 관찰해야 뜻이 있다. 나누면 같은 계약을 여러 곳에서 부분적으로 지키게 된다 |
| `src/limn/features/` 폴더를 만들어 원문에 맞춘다 | import 경로와 경계 검사기(`tools/check_boundaries.py`)의 허용목록을 모두 바꾸는 이동인데, 얻는 것이 원문과의 글자 일치뿐이다 |

## 결과

- 배치 규칙의 현재 설명은 [verification.md](../handbook/verification.md) §테스트 파일의 배치와 [code-style-roadmap.md](../handbook/code-style-roadmap.md) §R6이 맡는다. 두 topic은 이미 이 해석대로 적혀 있다.
- [`docs/adr/index.md`](index.md)에 이 기록과 ADR-0010과의 관계를 더한다.
