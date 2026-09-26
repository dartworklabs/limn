# 구조와 불변식

이 topic은 Limn이 지금 어떤 구조로 짜여 있는지, 어느 방향으로 옮겨 가기로 했는지, 그리고 구조가 바뀌어도 반드시 지켜야 하는 규칙이 무엇인지를 설명한다. 코드를 새로 놓을 자리를 고르거나, 모듈을 나누거나, 의존성·저장 파일·보안 경계를 건드리기 전에 읽는다. 구조 단위나 불변식이 바뀌면 같은 변경에서 이 파일을 고친다.

> **한눈에**
>
> - 요청 하나가 서버를 지나가는 흐름: §한 요청이 지나가는 길
> - 지금 코드가 놓인 모양과 그 근거: §현재 구조
> - 채택한 설계 축 값과 목표 구조: §채택한 설계 축, §목표 구조
> - 어기면 안 되는 규칙: §불변식
> - 멈추고 설계 판단을 받아야 하는 변경: §멈춤 신호

## 한 요청이 지나가는 길

Limn은 원고 PDF에서 드래그한 영역을 `.tex` 파일과 줄 범위로 되돌려 주는 서버다. 사용자는 브라우저 뷰어에서 영역을 고르고 메모를 붙여 **핀**으로 저장한다. 에이전트는 `pins.md`나 HTTP API로 핀을 읽고 원고를 고친다.

```text
브라우저 (영역 드래그)
   │  좌표
   ▼
limn serve  ──(1)──▶  <manuscript_dir> 사본을 별도 빌드 디렉터리에서
  127.0.0.1:<port>      latexmk -synctex=1 로 빌드 (원본 체크아웃은 건드리지 않는다)
   │
   ├─(2) 역변환 두 경로를 경쟁시킨 뒤 범위 사다리(드래그 줄·문단·환경)를 계산 → 스니펫
   ├─(3) 사용자가 메모를 붙여 핀으로 저장 → <state_dir>/pins.jsonl (잠금 + 원자적 교체)
   └─(4) <state_dir>/pins.md 재생성 — 에이전트가 읽는 단 하나의 파일
```

빌드를 원본 체크아웃이 아니라 rsync 사본에서 하는 이유는 동시에 편집 중인 원고를 빌드가 중간 상태로 붙잡지 않게 하려는 것이다. 빌드 사본 경로를 원본 경로로 되돌리는 일(`build_dir → manuscript_dir`)은 서버가 안에서 처리한다. 그래서 에이전트는 언제나 원본 경로만 받는다.

상태 디렉터리를 옮기거나 복제해서 SyncTeX가 옛 빌드 경로를 가리키는 경우도 있다. 이때는 경로 꼬리가 원고 트리 안의 파일과 맞을 때만 경로를 고쳐 쓴다. 원고 체크아웃을 옮겨 핀에 저장된 절대 경로가 낡은 경우도 같은 규칙에 원고 폴더 기준 상대 경로 `file_rel` 을 더해 읽을 때 찾는다([api.md](api.md) §핀 파일의 위치, [ADR-0006](../adr/0006-relative-pin-paths.md)). 원고 트리 밖의 파일은 절대 읽지 않는다. 역변환·범위 사다리·줄 맞춤의 규칙은 [domain.md](domain.md)에 있다.

## 현재 구조

지금 Limn은 **하나의 배포 단위(`dartwork-limn` 패키지) 안에 표준 라이브러리만 쓰는 큰 모듈 하나**가 대부분의 일을 한다. 아래는 2026-09-26 Limn 0.3.1 시점의 실측이다.

| 파일 | 줄 수 | 맡은 일 |
| --- | --- | --- |
| [`src/limn/server.py`](../../src/limn/server.py) | 7,224 | 설정, 빌드, 역변환, 핀 저장소, 검증, 사람·이벤트, 감사 기록, 접근 제어, HTTP 처리, 뷰어 조립 |
| [`src/limn/pins/`](../../src/limn/pins/model.py) | 358 | 핀 도메인의 순수 코드: 상태 타입과 행위자 타입(`model.py`), 전이(`lifecycle.py`: 확인, 닫기·다시 열기, 답글). 파일·시계·HTTP를 모른다 (`tests/test_pins_lifecycle.py`가 import를 검사) |
| [`src/limn/mapping.py`](../../src/limn/mapping.py) | 362 | 위치 계산의 순수한 절반: 범위 사다리, 블록 확장, 점수, anchor 찾기, 옮긴 원고에서 핀 파일 찾기(0.3.2, 있는지 확인은 인자로 받는다). 파일·subprocess·전역을 모른다 (`tests/test_mapping.py`가 import를 검사) |
| [`src/limn/viewer/`](../../src/limn/viewer/index.html) | 3,616 | 뷰어 화면: `index.html`(172)·`app.css`(835)·`app.js`(2,609). 서버가 시작할 때 CSS·JS를 `index.html`에 끼워 한 장의 HTML로 내보낸다 |
| [`src/limn/instances.sh`](../../src/limn/instances.sh) | 1,381 | 원고별 인스턴스 관리자 (`limn add` 등, systemd·tailscale 호출) |
| [`src/limn/migrate.py`](../../src/limn/migrate.py) | 242 | 이전 이름으로 설치된 인스턴스를 옮겨 오는 일회성 도구 |
| [`src/limn/cli.py`](../../src/limn/cli.py) | 249 | `limn` 명령 입구. `serve`는 `server.main`, `migrate`는 `migrate.main`, `token`·`member`는 상태 디렉터리의 `tokens.json`·`people.json`을 직접 고치고, 나머지는 `instances.sh`로 넘긴다 |
| [`src/limn/ui_en.json`](../../src/limn/ui_en.json) | 954 | 뷰어의 한국어 UI 문자열 → 영어 대응표 |
| `src/limn/vendor/` | — | 번들한 PDF.js와 Lucide 아이콘 (외부 CDN 없음) |

`server.py` 안은 `# ------` 배너 주석으로 관심사별 구역이 나뉘어 있다. 순서대로 문서(Doc)·빌드·빌드 이력·`--git-pull`·핀 단위 변경(0.3)·리비전 PDF·목차 라벨·보기 전용 PDF·meta·원문 접근·역변환 두 경로·범위 사다리·anchor·핀 저장소·위치 추정·겹침·입력 검증·핀 조작·사람과 이벤트·처리 중 표시·선택 해석·신원·접근 제어·뷰어 조립·HTTP 처리기·입구다. 뷰어 화면 자체는 2026-09-26부터 `src/limn/viewer/`의 파일 세 개에 있다 ([code-style-roadmap.md](code-style-roadmap.md) 3단계).

`server.py`는 `limn serve`로는 패키지 모듈(`limn.server`)로, 인스턴스(`limn run` → `instances.sh`)에서는 파일 경로(`python …/limn/server.py`)로 실행된다. 파일로 실행될 때도 옆 모듈을 `limn.*`으로 가져올 수 있도록, `server.py`는 시작할 때 자기 폴더의 부모를 `sys.path` 앞에 넣는다. 새로 꺼내는 모듈은 이 방식으로 가져온다. 옮긴 모듈은 `server.py`처럼 `from __future__ import annotations`로 시작한다 — 인스턴스 관리자가 시스템 `python3`로 `server.py`를 띄울 때 새 모듈 때문에 먼저 멈추지 않게 하려는 것이다.

구역 사이에서 상태를 주고받는 방식은 세 가지다.

1. **모듈 전역 설정** `C = Cfg()` — 실행 인자를 담는다. 코드 안에서 `C.` 참조가 200곳이다.
2. **스레드 지역 "현재 문서"** `using_doc(D)` / `cur_doc()` — 요청 하나가 문서 하나를 다룬다는 전제로, 빌드·페이지 함수가 인자 없이 현재 문서를 본다. `cur_doc()` 호출이 46곳이다.
3. **모듈 전역 잠금과 상태 사전** — `PIN_LOCK`, `BUILD_LOCK`, `BUILD_STATE` 등.

핀 레코드는 대부분의 코드에서 파이썬 `dict` 그대로 다닌다. 핀의 상태(열림·검토 대기·완료)는 `done`·`review` 같은 독립 필드의 조합에서 `pin_state()`가 계산한다. 2026-09-26부터 [`limn/pins/`](../../src/limn/pins/model.py)가 상태를 타입(`OpenPin`·`ReviewPin`·`DonePin`)으로 파싱하고, 옮겨진 전이(확인, 닫기·다시 열기, 답글)는 그 타입을 받아 결과를 반환값으로 돌려준다.

> **참고**
>
> 이 구조는 한 사람이 빠르게 기능을 쌓으며 자연스럽게 생긴 모양이다. 배포가 `uv tool install` 한 번으로 끝나고, 테스트가 소켓 없이 처리기를 직접 몰 수 있다는 장점이 있다. 우리 코딩 규칙과 어디가 다르고 어떤 순서로 맞춰 가는지는 [code-style-roadmap.md](code-style-roadmap.md)에 친절하게 정리했다.

## 채택한 설계 축

설계 축은 프로젝트가 기본 청사진에서 어디가 달라지는지를 묻는 질문 목록이다. 아래 값이 **현재 채택값**이고, 채택한 이유와 버린 대안은 [ADR-0001](../adr/0001-blueprint.md)에 남긴다. 표에 없는 축(경제·비용 게이트, 외부 검수 권위)은 Limn에서 달라지지 않아 따로 정하지 않았다.

| 축 | 채택값 | 근거와 적용 |
| --- | --- | --- |
| 1차 구조 | **작은 단일 배포 + 책임별 모듈.** 현재는 단일 모듈이고, 목표는 §목표 구조. 2026-09-26부터 옮기는 중이며, 구조 이동 PR이 열린 기능 PR보다 우선한다 | 배포 단위·런타임이 하나다. 서버·인스턴스 관리자·migrate의 수명 주기만 다르다 |
| 도메인 정체 | **핀의 수명 주기와 위치 규칙.** 상태 전이, 역변환·범위 사다리·anchor 재동기화 | [domain.md](domain.md) |
| 함수형 DDD 범위 | **실용적 함수형.** 판단은 순수 함수, 부수효과(파일·git·subprocess·HTTP)는 가장자리. 의미 있는 수명 주기(핀 상태)에만 상태별 타입과 전이 함수를 쓰고, 계산·파싱은 평범한 함수로 둔다. 예상된 거절은 예외가 아니라 반환 타입의 거절 값(`Pin \| ConfirmRejected`)으로 돌려준다 | 우리 코딩 스킬 `code-implement`의 기본값. 현재 코드와의 차이는 [code-style-roadmap.md](code-style-roadmap.md) |
| 검수 진실원 | **자동 테스트 녹색 + 에이전트 계약 불변 + 화면 실측.** pytest·셸 테스트·Playwright 레이아웃 테스트가 통과하고, `pins.md`·HTTP API가 호환을 지키며, 화면 규칙은 실측 스크린샷으로 확인한다 | [verification.md](verification.md) |
| 검수 시점 | **머지 전 게이트.** CI가 막는다 | [verification.md](verification.md) |
| HARD-GATE | **행동 계약 변경 전.** 에이전트 계약·보안 경계·저장 형식을 바꾸는 변경은 설계 승인 뒤 구현한다 | [workflow.md](workflow.md) |
| 정본 매체 | 동작은 **코드**, 에이전트 계약은 **[api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)**, 데이터는 **상태 디렉터리 파일**. Handbook은 설계 교과서이자 안내판 | [purpose.md](purpose.md) §진실 소스 |
| Handbook 책임 구성 | 목적·구조·도메인·뷰어·빌드·API·운영 두 편·검증·변경 흐름·코딩 로드맵으로 나눈다 | [index.md](index.md) |
| 시간축 호환 | **옛 상태 디렉터리와 옛 에이전트를 깨지 않는다.** 옛 레코드는 읽을 때 해석하고 쓰기 마이그레이션을 하지 않는다 | §불변식 3, 6 |

## 목표 구조

목표는 새 프레임워크나 계층을 들이는 것이 아니다. 지금 `server.py` 안에 배너로만 나뉜 책임을 **책임별 모듈**로 꺼내고, 판단과 부수효과를 갈라놓는 것이다. 한 번에 옮기지 않고 [code-style-roadmap.md](code-style-roadmap.md)의 단계대로 옮긴다.

```text
src/limn/
├── cli.py               limn 명령 입구 (지금과 같음)
├── pins/                핀 도메인 — 순수
│   ├── model.py         상태별 타입, 명령 값, 예상 실패
│   ├── lifecycle.py     열기·닫기·확인·다시 열기·claim 전이 함수
│   └── render.py        pins.md 렌더링 (입력 → 문자열)
├── mapping.py           역변환·범위 사다리·anchor — 순수 계산 (2026-09-26 옮김)
├── store.py             pins.jsonl 잠금·원자적 쓰기·손상 레코드 보존 (부수효과)
├── build/               latexmk·pdftoppm·git 호출, 빌드 이력 (부수효과)
├── http/                요청 파싱, 라우팅, 오류 매핑, 신원 헤더 (부수효과)
├── viewer/              index.html · app.css · app.js — 패키지 데이터 파일
├── server.py            조립 지점: 설정 파싱, 자원 생성, 스레드 시작·종료
├── instances.sh
└── migrate.py
```

이름은 확정값이 아니다. 지켜야 하는 것은 **의존 방향**이다. `pins/`와 `mapping/`은 파일·subprocess·HTTP 타입을 가져오지 않는다. `store`·`build`·`http`는 그 순수 모듈을 불러 쓴다. 조립 지점(`server.py`)만 전역 자원을 만들고 끝낸다.

## 불변식

아래 규칙은 구조를 어떻게 바꾸든 유지한다. 각 규칙이 언제 적용되는지, 누가 지키는지, 어기면 무엇이 깨지는지를 함께 적는다.

### 1. 신원 방식 없이 loopback 밖에 열지 않는다

기본 바인드 주소는 `127.0.0.1`이다. 0.2.0부터 `--bind`로 다른 주소를 줄 수 있지만, loopback이 아닌 주소는 신원을 프록시가 보증하는 `--auth trusted-proxy`일 때만 받는다. 그 밖에는 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수는 있지만 크게 경고한다. 테일넷 노출은 `tailscale serve`, 그 밖의 노출은 인증 리버스 프록시가 맡고, `tailscale funnel`은 쓰지 않는다. 이 규칙이 깨지면 포트에 닿는 누구나 원고를 읽고 핀을 바꿀 수 있다. 근거와 위협 모델은 [SECURITY.md](../../SECURITY.md), 운영 상세는 [operations.md](operations.md) §보안 제약, 설계와 이후 단계는 [ADR-0002](../adr/0002-access-control.md)에 있다.

신원은 인스턴스마다 방식 하나(`tailscale`·`local`·`trusted-proxy`)로 정하고, 에이전트는 API 토큰으로 인증한다. 권한은 `people.json`의 역할(owner·editor·viewer·agent)이 정하고, 처리기 한 곳에서 집행한다. 헤더 없는 요청을 에이전트로 보는 것은 이 기기를 부른 요청(루프백 `Host`)뿐이고, 모든 핀을 지우는 일은 소유자만 한다([ADR-0003](../adr/0003-tailnet-headerless-and-owner-clear.md)). 상세는 [api.md](api.md) §인증이다.

### 2. 서버 런타임은 표준 라이브러리만 쓴다

`pyproject.toml`의 `dependencies = []`가 이 규칙의 실행 정본이다. Python 3.10 이상에서 돈다. 뷰어도 React·Tailwind·빌드 단계·CDN 없이 번들한 PDF.js와 Lucide만 쓴다. 배포가 패키지 설치 하나로 끝나야 연구실 머신에서 유지할 수 있기 때문이다. 개발 의존성(pytest, Playwright, 앞으로 들일 Ruff 등)은 이 규칙과 무관하다.

### 3. 에이전트 계약은 호환을 깨지 않는다

`pins.md`의 열·표시어·한국어 머리말과 HTTP API의 경로·JSON 필드 이름·상태 이름은 다른 저장소의 에이전트가 읽는다. 새 필드와 경로를 더하는 것은 되지만, 바꾸거나 빼려면 버전이 붙은 이전 계획이 먼저 있어야 한다. UI 언어가 바뀌어도 계약은 번역하지 않는다. 계약의 본문은 [api.md](api.md)다.

### 4. 핀 파일은 한 잠금 아래 정해진 순서로만 쓴다

핀 파일을 만지는 모든 경로는 `PIN_LOCK` 하나 아래에서 **읽기 → 재동기화 → 요청한 변경 적용 → 임시 파일에 쓰고 `os.replace` → `pins.md` 재생성** 순서를 지킨다. 지금은 `transact()`가 이 순서를 강제한다. 잠금이 없던 시절 핀 30개를 동시에 저장하면 2개만 남았다. 핀 번호는 `pins.seq`에서 발급하고 삭제 뒤에도 다시 쓰지 않는다. 상세는 [domain.md](domain.md) §저장소 안전성이다.

### 5. 원본 원고는 서버가 고치지 않는다

빌드는 사본에서 하고, `--git-pull`은 `main`에서 `--ff-only`만 한다. rebase나 merge 커밋을 대신 만들지 않는다. git 호출은 셸 없이 `subprocess.run([...])`로 하고 사용자 입력을 인자에 끼워 넣지 않는다. 상세는 [build-sync.md](build-sync.md)다.

### 6. 옛 상태 디렉터리는 쓰기 마이그레이션 없이 읽는다

`doc` 필드가 없는 옛 레코드는 첫 문서로 읽고, `review` 필드가 없는 옛 `done:true` 레코드는 그냥 완료로 읽는다. `file_rel` 이 없는 옛 레코드는 저장된 `file` 로 지금 원고 폴더에서 파일을 찾는다(0.3.2). 읽는 쪽이 해석할 뿐 파일을 고쳐 쓰지 않는다. 그래서 옛 버전으로 되돌려도 상태 디렉터리가 그대로 동작한다.

### 7. 앱 이름은 Limn 하나이고 개인정보를 넣지 않는다

옛 이름은 README 역사 절, `limn migrate`, CHANGELOG에만 남는다. 실제 이메일·홈 경로·호스트 이름·논문 이름을 코드와 문서에 넣지 않는다. [`tests/test_naming.py`](../../tests/test_naming.py)가 이를 검사한다.

### 8. 사람에게 보이는 문자열과 계약 문자열을 구분한다

뷰어 UI 문자열의 원본은 템플릿 안 한국어이고, 영어 모드는 [`ui_en.json`](../../src/limn/ui_en.json) 대응표로 바꾼다. `pins.md`와 API 오류 문자열(`{"error": "<한국어>"}`)은 계약이라 번역하지 않는다. 코드·주석·docstring·테스트 이름·커밋 메시지·CLI 도움말은 영어로 쓴다.

## 멈춤 신호

아래 변경은 코드부터 쓰지 말고 멈춘다. 설계를 먼저 정하고 필요하면 ADR을 남긴 뒤 구현한다. 절차는 [workflow.md](workflow.md)에 있다.

| 신호 | 예 | 왜 멈추나 |
| --- | --- | --- |
| 런타임 의존성 추가 | `dependencies`에 패키지를 넣는다 | 불변식 2 |
| 새 저장 파일이나 저장 형식 변경 | 상태 디렉터리에 새 파일, 레코드 필드 의미 변경 | 불변식 4, 6. 옛 상태와의 호환을 설계해야 한다 |
| 새 상태 기계·권한·비동기 흐름 | 핀 상태 추가, 역할 기반 권한, 새 백그라운드 스레드 | 수명 주기와 동시성 규칙이 바뀐다 |
| 에이전트 계약 변경 | `pins.md` 열, API 필드·경로·상태 이름 | 불변식 3 |
| 보안 경계 변경 | 바인드 규칙, 신원 방식, 토큰, 역할별 허용 범위, Host·Origin 검사, 신원 헤더 신뢰 범위 | 불변식 1, [SECURITY.md](../../SECURITY.md) |
| 공유 모듈로 승격 | 두 곳에서 쓰는 코드를 공용 모듈로 뺀다 | 소비자가 실제로 둘 이상인지 먼저 확인한다 |
| 도메인이 부수효과를 부름 | 순수 모듈이 파일·subprocess·HTTP 타입을 가져온다 | §목표 구조의 의존 방향 |
