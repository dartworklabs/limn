# 코드 소유권과 테스트 배치 정리

사용자 요청에 따라 코딩 스킬의 기능 소유권·공개 경계·테스트 동거 규칙을 실제 배치와 Handbook에 맞췄다. 테스트와 도우미 87개를 재배치했다. 기능 테스트는 슬라이스의 `tests/`, 공통 코드와 통합 계약은 루트 `tests/`의 책임별 폴더, 공용 도우미는 `tests/support/`가 소유한다.

## 코드와 의존성

13개 슬라이스의 `__init__.py`에 공개 값·동작과 `__all__`를 선언했다. `server.py`·`cli.py`는 내부 모듈 대신 이 표면을 통해 조립한다. 비교 기능의 코어만 읽을 때 HTTP를 불러오지 않도록 `revisions/__init__.py`의 표면은 지연 로딩한다. 타입 검사와 import 그래프가 볼 수 있는 정적 import 선언은 유지한다.

| 소유 슬라이스 | 변경 파일과 공개 조립 대상 |
| --- | --- |
| `administration` | `__init__.py`, `tests/`: 명령·문서 선택·시작 거절 값 |
| `builds` | `__init__.py`, `tests/`: 빌드 요청·시작 판단·경로 등록 |
| `collaboration` | `__init__.py`: 사람 목록 서비스·알림·조회 경로 |
| `document_views` | `__init__.py`, `tests/`: 문서 조회·meta 설정·경로 |
| `pins/claims` | `__init__.py`, `tests/`: 처리 중 표시 서비스·동작 등록 |
| `pins/editing` | `__init__.py`, `tests/`: 편집 서비스·요청 문맥·동작 등록 |
| `pins/lifecycle` | `__init__.py`, `tests/`: 수명 주기 서비스·동작 등록 |
| `pins/listing` | `__init__.py`: 조회 서비스·Markdown 조립·경로 |
| `pins/location` | `__init__.py`: 위치 서비스·실행 문맥·캐시 자원·경로 |
| `pins/trash` | `__init__.py`, `tests/`: 휴지통 서비스·동작 등록 |
| `revisions` | `__init__.py`, `answer.py`, `core.py`, `tests/`: 비교 요청·실행 자원·응답·경로 |
| `sync` | `__init__.py`, `tests/`: 동기화 서비스·실행 자원·지문 |
| `viewer_shell` | `__init__.py`: 화면 제공 경로 |

슬라이스 사이의 새 import는 없다. 공통 HTTP의 기능 의존 두 곳을 제거했다. `web/errors.py`의 비교 실패 표와 응답 함수는 소유자인 `features/revisions/answer.py`로 옮겼다. `web/app.py`는 구체 `PeopleDirectory` 대신 처리기가 필요한 `PeopleRecorder` 계약을 선언한다. 이 계약은 모킹용 추상화가 아니라 공통 처리기의 의존 방향을 지킨다.

휴지통 재시작 검사 네 곳은 내부 `build_run` 모킹 대신 실제 캐시 PDF와 PNG를 갖춘 상태를 사용한다. 시작 시 휴지통 읽기 실패도 실제 읽을 수 없는 디렉터리로 재현한다. 기존 상태·API·권한·저장 순서는 유지했고 계약 스냅샷이 통과했다. 나머지 기존 테스트 대역 전체를 다시 설계한 변경은 아니다.

## 게이트와 실행 설정

`tools/check_boundaries.py`는 모든 기능의 공개 표면, 비공개 import, 공통 코드에서 기능으로 이어지는 경로, 슬라이스 순환을 검사한다. 패키지 초기화와 상대 import도 그래프에 포함한다. `uv run python tools/check_boundaries.py`가 CI `lint`를 막고, 검사기 검증은 `tests/architecture/test_boundaries.py`가 맡는다. 동적 import 문자열과 런타임 속성 접근 일반은 정적 검사 범위 밖이다.

`pyproject.toml`의 기본 pytest 설정은 `--import-mode=importlib -n 4 --dist loadscope`다. `-n 0`으로 직렬 디버깅할 수 있다. CI의 일반 검사와 Chromium 검사를 Python 3.10·3.12별 독립 작업으로 분리했다. 실제 TeX와 Linux·macOS 인스턴스 셸 검사도 독립 작업이다. wheel은 테스트 디렉터리를 제외하고 sdist는 테스트 도우미와 검증 도구를 포함한다. 기존 런타임 의존성과 CI 권한은 추가하지 않았다.

Handbook의 architecture·code-style·verification·purpose·index와 이동 경로를 참조하는 topic, `AGENTS.md`, `CONTRIBUTING.md`, PR 템플릿을 동기화했다. 뷰어 자산의 변경은 이동한 테스트를 가리키는 주석뿐이다.

## 검증 결과

| 검사 | 결과 |
| --- | --- |
| 이동 전 전체, Python 3.14 | 2028 passed, 11 skipped, 1046 subtests passed; 191.74초 |
| 수정 후 전체, Python 3.14 | 2038 passed, 11 skipped, 1046 subtests passed; 215.88초 |
| Python 3.10 일반 검사, CI와 같은 marker 선택 | 1899 passed, 1 skipped, 927 subtests passed; 113.26초 |
| 인스턴스 셸 검사 | 190 passed, 0 failed |
| 수집 목록·이동표 | 기존 2039개 보존, 새 경계 검사 10개, 누락·중복 node ID 없음. `test_id_map.py`: unmapped differences 0 |
| Ruff·포매팅·ShellCheck | 오류·경고 0건, 포매팅 통과 |
| mypy | 생산 모듈 134개 통과 |
| 패키징 | wheel·sdist 빌드, 테스트 제외·검증 도구 포함 확인, 격리 환경 도움말·버전 실행 통과 |
| Handbook | check·HTML build 통과 |

수정 후 전체와 Python 3.10 검사를 동시에 실행했으므로 이동 전후 시간은 속도 향상의 근거로 비교하지 않는다. CI 병렬 작업의 실제 소요 시간은 아직 측정하지 않았다. 원격 CI는 실행하지 않았고 PR·배포도 수행하지 않았다.

전체 스킵 11개는 TeX·SyncTeX·bwrap·latexdiff가 없는 검사와 실제 상태 복사본을 요구하는 검사다. 실제 systemd·tailscale은 기존 셸 테스트 정책대로 소유 어댑터에서 대체한다. 이 작업에서 인증·권한 입력이나 위험한 실행 싱크는 바꾸지 않았다.

## 실패 검증과 적용 스킬

새 검사기는 기존 소스의 공개 선언 누락·기능 의존을 실제로 거부했다. 위반 반환을 비우면 비공개 import·간접 shared 경로·순환·생성한 길이의 경로 성질 검사가 실패했다. 내부 상대 import를 금지한 변이, 빈 소스 발견을 허용한 변이, 동거 테스트 도우미를 생산 코드로 읽는 변이도 각각 해당 assertion에서 실패했다. 패키지 초기화 경로를 빼면 순환 검사가 실패하는 red 단계도 확인했다. 모두 복구한 최종 검사 10개가 통과했다.

구조 이행 중 휴지통 테스트 네 곳의 사라진 내부 모듈 참조와 비교 코어의 HTTP 초기화가 실패했다. 원인을 고친 뒤 관련 검사 84개와 전체 게이트를 통과했다.

적용한 참조는 `code-implement`의 Python·structure·format·integration, `code-testing`의 Python이다. `code-security`는 CI·기존 신뢰 경계 보존을 확인하는 데 읽었다. 늦게 추가한 언어·데이터 참조나 새 도구·런타임 의존성은 없다. Handbook 책임 읽기·경계 검사·동기화·검수와 실패 분석·완료 전 검증 스킬도 적용했다. 새 import 그래프의 전이 경로 성질은 Hypothesis로 검증하며, 이동 자체에 새 도메인 성질을 만들어 붙이지 않았다.
