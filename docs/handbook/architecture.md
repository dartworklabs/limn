# 시스템 아키텍처 — 청사진과 불변식

이 topic은 Limn의 청사진, 현재 구조, 채택한 설계 축, 불변식, 멈춤 신호를 설명한다. 코드를 놓을 자리를 고르거나 의존성·저장·보안 경계를 건드리기 전에 읽는다. 구조 단위·불변식·채택값이 바뀌면 이 파일을 고친다.

## 한눈에 보는 흐름

```text
[브라우저 뷰어] ──(1) 클릭 좌표(x, y, 쪽)──> [서버: SyncTeX 역변환]
                                                   │
   ┌───────────────────────────────────────────────┘
   ├─(2) 역변환 두 경로를 경쟁시킨 뒤 범위 사다리(드래그 줄·문단·환경)를 계산 → 스니펫
   ├─(3) 사용자가 메모를 붙여 핀으로 저장 → <state_dir>/pins.jsonl (잠금 + 원자적 교체)
   └─(4) <state_dir>/pins.md 재생성 — 에이전트가 읽는 단 하나의 파일
```

빌드를 원본 체크아웃이 아니라 rsync 사본에서 하는 이유는 동시에 편집 중인 원고를 빌드가 중간 상태로 붙잡지 않게 하려는 것이다. 빌드 사본 경로를 원본 경로로 되돌리는 일(`build_dir → manuscript_dir`)은 서버가 안에서 처리한다. 그래서 에이전트는 언제나 원본 경로만 받는다.

상태 디렉터리를 옮기거나 복제해서 SyncTeX가 옛 빌드 경로를 가리키는 경우도 있다. 이때는 경로 꼬리가 원고 트리 안의 파일과 맞을 때만 경로를 고쳐 쓴다. 원고 체크아웃을 옮겨 핀에 저장된 절대 경로가 낡은 경우도 같은 규칙에 원고 폴더 기준 상대 경로 `file_rel` 을 더해 읽을 때 찾는다([api.md](api.md) §핀 파일의 위치). 원고 트리 밖의 파일은 절대 읽지 않는다. 원고 트리는 `--manuscript` 아래에서 점으로 시작하는 이름(`.git`·`.env` 등) 아래와, 원고 안에 둔 상태 폴더 아래를 뺀 곳이고, 규칙은 `limn/files.py`의 `tree_part` 하나다. 역변환·범위 사다리·줄 맞춤의 규칙은 [domain.md](domain.md)에 있다.

## 현재 구조

Limn은 **하나의 배포 단위(`dartwork-limn` 패키지) 안에서 표준 라이브러리만 쓰는 모듈**로 나눈다. 핀 수명 주기, 처리 중 표시, 휴지통, 만들기·편집, JSON 조회와 PDF 선택은 `features/pins/`의 각 기능 패키지가 입력·HTTP 응답·실행별 협력자를 소유한다. 빌드 상태·PDF·쪽 이미지 읽기와 재빌드 요청은 `features/builds/`가, 원격 Git 동기화와 감시는 `features/sync/`가, Git 이력·비교 PDF의 요청·응답은 `features/revisions/`가, 사람 파일·멘션 알림의 실행별 연결과 목록 조회는 `features/collaboration/`이, 문서 상태·목차 조회는 `features/document_views/`가 소유한다. 명령줄 사용자 동작은 `features/administration/`이 소유하고, 저장·신원·문서·실행 수명은 여러 기능의 공통 경계에 남는다. 경로마다의 책임과 함께 볼 topic은 [index.md](index.md) §파일 지도가 정본이다.

| 층 | 모듈 | 하는 일 | 모르는 것 |
| --- | --- | --- | --- |
| 순수 도메인 | `pins/`(상태 타입·레코드 검사·전이·편집·위치 규칙·API 모양·`pins.md` 렌더), `mapping.py`, `scope.py`, `mentions.py`, `outline.py`, `guidance.py`, `mark.py` | 핀 수명 주기와 위치 계산의 규칙. 입력 값에서 결과 값이나 거절 값을 낸다 | 파일, subprocess, 시계, HTTP. 모듈마다 import 검사가 지킨다 |
| 기능(세로 슬라이스) | `features/pins/lifecycle/*`, `features/pins/claims/*`, `features/pins/trash/*`, `features/pins/editing/*`, `features/pins/listing/*`, `features/pins/location/*`, `features/builds/*`, `features/sync/*`, `features/collaboration/*`, `features/document_views/*`, `features/revisions/*`, `features/viewer_shell/*`, `features/administration/*` | 각 기능의 입력 검사, HTTP 라우팅·응답 매핑, 실행별 문맥 조립과 서비스 로직 | 다른 슬라이스의 비공개 세부. 공통 도메인 규칙이나 공통 저장소 협력자를 통해서만 소통한다 |
| 서비스 협력자 | `service/context.py`(`PinContext`), `store.py`(`PinStore`), `locate.py`(`est_context`·`sync_all`), `build.py`(`BuildArtifacts`·`BuildHistory`), `documents.py`(`Doc`·`DocumentFacts`), `gitrun.py`, `files.py` | 실행별 자원·잠금·파일 읽기/쓰기를 기능에 주입하기 쉬운 협력자로 감싼다 | HTTP 요청/응답 형식 |
| 인프라 | `files.py`(`atomic_write`·`store_lock`), `gitrun.py`, `people.py`, `events.py`, `audit.py`, `args.py`, `config.py`, `startup.py`, `access.py` | 운영체제·외부 도구와의 경계. 신원 방식·역할·Host 검사 | 핀 수명 주기와 계산 규칙 |
| HTTP | `web/`(`handler.py`, `reply.py`, `routes.py`, `parse.py`, `answers.py`, `errors.py`, `app.py`) | 순수 HTTP 뼈대. 처리기, 디스패치 계약, 공통 오류 형식과 거절 표 | 구체 서비스 구현 세부 |
| 조립 | `server.py`(`Runtime`, `ServerApplication`, `StartedServer`) | 런타임 자원과 문맥을 묶고 각 기능 서비스를 조립해 HTTP 처리기에 바인딩한다 | 뷰어 브라우저 세부 |
| 프론트엔드 | `viewer/` (HTML·CSS·JS 조각, `parts.txt`, SVG 마크, 번들된 PDF.js·Lucide) | 브라우저 화면과 상호작용 | 파이썬 런타임 |
| 관리자 CLI | `cli.py`, `instances.sh`, `systemd/` | 원고별 인스턴스 관리, 포트 배정, 토큰 발급, systemd 서비스 등록 | 논문 원고의 세부 내용 |

## 의존 방향

규칙은 단순하다. **안쪽(도메인)은 바깥쪽(인프라·HTTP·뷰어)을 모른다.**

```text
순수 도메인 (pins/, mapping, scope, mentions, outline, guidance, mark)
   ▲
   │
기능 슬라이스 (features/*) + 서비스 협력자 (service/context, store, locate, build, documents)
   ▲
   │
인프라 (files, gitrun, people, events, audit, access, startup, args, config)
   ▲
   │
HTTP 계층 (web/)
   ▲
   │
조립 지점 (server.py)
```

- `pins/` 아래의 어떤 모듈도 `web/`·`server.py`·`features/`를 import하지 않는다.
- `features/*`는 순수 도메인과 필요한 서비스 협력자/인프라 타입을 가져오되 다른 기능 슬라이스의 내부 구현을 직접 import하지 않는다.
- 기능 서비스는 외부 자원(파일 시스템, git, 시계, 외부 프로세스)에 직접 닿지 않고 협력자(`PinStore`, `Runtime`, `Doc` 등)를 주입받는다.
- 거절은 예외가 아니라 결과 값(합 타입)으로 돌려주고, HTTP 층이 이를 상태 코드로 바꾼다. 단, `access.py`의 인증·인가 실패와 `handler.py`의 요청 크기 초과는 경계에서 바로 `HTTPError`를 던진다.
- **조립 지점이 실행별 자원을 만들고 끝낸다.** `start()`가 실행 설정·런타임·문서 목록을 가진 `ServerApplication`을 만들고 그 실행 전용 처리기 하위 클래스에 묶는다. `StartedServer`가 소켓과 앱을 함께 돌려줘 종료 대상을 보존한다. 같은 모듈에서 다음 실행을 시작해도 앞선 처리기의 앱은 바뀌지 않는다. `web/`은 조립 지점을 가져오지 않는다.

## 채택한 설계 축

설계 축은 프로젝트가 기본 청사진에서 어디가 달라지는지를 묻는 질문 목록이다. 아래 값이 **현재 채택값**이다. 표에 없는 축(경제·비용 게이트, 외부 검수 권위)은 Limn에서 달라지지 않아 따로 정하지 않았다.

| 축 | 채택값 | 근거와 적용 |
| --- | --- | --- |
| 1차 구조 | **작은 단일 배포 + 기능별 세로 슬라이스와 테스트 동거로 점진 이행.** 닫기·다시 열기·확인·답글·claim·unclaim은 이행했고 다른 동작은 책임별 모듈에 있다(§현재 구조) | 배포 단위·런타임은 하나이며, 세로 슬라이스는 코드와 테스트를 함께 소유한다 |
| 도메인 정체 | **핀의 수명 주기와 위치 규칙.** 상태 전이, 역변환·범위 사다리·anchor 재동기화 | [domain.md](domain.md) |
| 함수형 DDD 범위 | **실용적 함수형 + 객체 권한(Object capabilities).** 판단은 순수 함수, 부수효과(파일·git·subprocess·HTTP)는 가장자리. 권한은 검증된 신원에서 값으로 전달하고 신뢰 경계는 닫힌 상태를 유지한다. 의미 있는 수명 주기(핀 상태)에만 상태별 타입과 전이 함수를 쓰고, 계산·파싱은 평범한 함수로 둔다. 예상된 거절은 예외가 아니라 반환 타입의 거절 값으로 돌려준다(`confirm() -> DonePin \| AlreadyDone \| PinStillOpen`, `confirmer() -> Person \| AgentCannotConfirm`) | 우리 코딩 스킬 `code-implement`·`code-security`의 기본값. 규칙과 예는 [code-style-roadmap.md](code-style-roadmap.md) |
| 검수 진실원 | **동작 중심 테스트(리팩토링 내성) + 도메인 불변식 PBT + 에이전트 계약 불변 + 화면 실측.** 자동 테스트 녹색은 필요조건일 뿐이며, 구조가 아닌 관찰 가능한 동작 검증(출력 기반, 성질 기반 PBT, Red 단계)이 진실원이다. pytest·셸 테스트·Playwright 레이아웃 테스트가 통과하고, `pins.md`·HTTP API가 호환을 지키며, 화면 규칙은 실측 스크린샷으로 확인한다 | [verification.md](verification.md) |
| 검수 시점 | **머지 전 게이트.** CI가 막는다 | [verification.md](verification.md) |
| HARD-GATE | **행동 계약 변경 전.** 에이전트 계약·보안 경계·저장 형식을 바꾸는 변경은 설계 승인 뒤 구현한다 | [workflow.md](workflow.md) |
| 정본 매체 | 동작은 **코드**, 에이전트 계약은 **[api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)**, 데이터는 **상태 디렉터리 파일**. Handbook은 설계 교과서이자 안내판 | [purpose.md](purpose.md) §진실 소스 |
| Handbook 책임 구성 | 목적·구조·도메인·뷰어·빌드·API·운영 두 편·검증·변경 흐름·코딩 규칙으로 나눈다 | [index.md](index.md) |
| 시간축 호환 | **옛 상태 디렉터리와 옛 에이전트를 깨지 않는다.** 옛 레코드는 읽을 때 해석하고 쓰기 마이그레이션을 하지 않는다 | §불변식 3, 6 |

## 불변식

아래 규칙은 구조를 어떻게 바꾸든 유지한다. 각 규칙이 언제 적용되는지, 누가 지키는지, 어기면 무엇이 깨지는지를 함께 적는다.

### 1. 신원 방식 없이 loopback 밖에 열지 않는다

기본 바인드 주소는 `127.0.0.1`이다. `--bind`로 다른 주소를 줄 수 있지만, loopback이 아닌 주소는 신원을 프록시가 보증하는 `--auth trusted-proxy`일 때만 받는다. 그 밖에는 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수는 있지만 크게 경고한다. 테일넷 노출은 `tailscale serve`, 그 밖의 노출은 인증 리버스 프록시가 맡고, `tailscale funnel`은 쓰지 않는다. 이 규칙이 깨지면 포트에 닿는 누구나 원고를 읽고 핀을 바꿀 수 있다. 근거와 위협 모델은 [SECURITY.md](../../SECURITY.md), 운영 상세는 [operations.md](operations.md) §보안 제약에 있다.

신원은 인스턴스마다 방식 하나(`tailscale`·`local`·`trusted-proxy`)로 정하고, 에이전트는 API 토큰으로 인증한다. 서버 머신의 에이전트는 토큰 원문을 설정 폴더의 토큰 파일(`<이름>.token`, `0600`, 저장소 밖)에서 읽고, 서버는 그 파일을 읽지 않는다. 권한은 `people.json`의 역할(owner·editor·viewer·agent)이 정하고, 처리기 한 곳에서 집행한다. 접근 제어는 단일 지점 완전 중재(Saltzer & Schroeder Complete Mediation)와 닫힌 기본 상태(closed by default)를 따른다. 모든 경로는 검증된 신원에서 파생된 권한 값(Object capability)으로 처리하며, 외부 입력은 경계에서 완전한 타입으로 파싱(`parse, don't validate`)한다. 역할·신원 방식·신원 경로는 닫힌 `Literal` 타입(`Role`·`AuthProvider`·`Via`)이라 이 값과의 비교에 오타가 있으면 타입 검사(`strict_equality`)에서 실패한다. 밖에서 온 글자(`people.json`의 `role`, 명령줄)는 경계에서 한 번만 이 타입으로 바뀌고, 알 수 없는 역할 값은 `viewer`가 된다. 처리기가 행동마다 묻는 역할 질문(답글이 사람의 것인가, `review` 없는 닫기가 검토 대기로 가는가)도 `Principal`이 답하므로 역할 비교는 `access.py` 밖에 없다. 신원·입장·역할 판단과 Host/Origin 규칙의 코드는 [`limn/access.py`](../../src/limn/access.py) 한 곳에 있다. 이 모듈은 실행 설정(`C`)을 읽지 않는다. 조립 지점(`server.py`)이 요청마다 실행 설정 값(`AccessSettings`)과 파일 사실(`AccessLookups`: `tokens.json`·`people.json`을 파일이 바뀔 때만 다시 읽는 캐시, 실행마다 하나씩)을 넘긴다. 이 경계의 거절은 값으로 돌려주지 않고 `HTTPError`를 던진다(§의존 방향). 파일 사실도 같은 쪽으로 닫는다. 쓸 수 없는 `tokens.json`은 토큰을 하나도 받지 않고, 쓸 수 없는 `people.json`은 헤더로 들어온 모든 사람을 `viewer`로 두고 멤버 자격을 주지 않으며 다시 쓰이지 않는다. 헤더 없는 요청을 에이전트로 보는 것은 이 기기를 부른 요청(루프백 `Host`)뿐이고, 모든 핀을 지우는 일은 소유자만 한다. 상세는 [api.md](api.md) §인증이다.

### 2. 서버 런타임은 표준 라이브러리만 쓴다

`pyproject.toml`의 `dependencies = []`가 이 규칙의 실행 정본이다. Python 3.10 이상에서 돈다. 뷰어도 React·Tailwind·빌드 단계·CDN 없이 번들한 PDF.js와 Lucide만 쓴다. 뷰어의 CSS·JS가 여러 조각 파일이어도 번들러나 모듈 로더를 들이지 않는다. 서버가 `parts.txt` 순서대로 조각을 이어 인라인 `<style>`·`<script>` 하나씩으로 내보낸다. 배포가 패키지 설치 하나로 끝나야 연구실 머신에서 유지할 수 있기 때문이다. 개발 의존성(pytest, pytest-xdist, hypothesis, Playwright, Ruff, ShellCheck, mypy)은 이 규칙과 무관하다.

### 3. 에이전트 계약은 호환을 깨지 않는다

`pins.md`의 열·표시어·한국어 머리말과 HTTP API의 경로·JSON 필드 이름·상태 이름은 다른 저장소의 에이전트가 읽는다. 새 필드와 경로를 더하는 것은 되지만, 바꾸거나 빼려면 버전이 붙은 이전 계획이 먼저 있어야 한다. UI 언어가 바뀌어도 계약은 번역하지 않는다. 계약의 본문은 [api.md](api.md)다.

### 4. 핀 파일은 한 잠금 아래 정해진 순서로만 쓴다

핀 파일을 만지는 모든 경로는 해당 서버 실행의 핀 잠금(`RT.pin_lock`)을 잡는다. 살아 있는 핀을 변경하는 경로는 **읽기 → 재동기화 → 요청한 변경 적용 → 원본 JSONL·`pins.md` 바이트 준비 → 정해진 순서로 파일 교체**를 지키고, [`limn/store.py`](../../src/limn/store.py)의 `PinStore.transact()`가 이 순서를 강제한다. 삭제는 준비 뒤 휴지통 → 원본 → Markdown, 되살리기는 원본 → Markdown → 휴지통 순서다. 휴지통 정리와 전체 지우기도 같은 잠금 아래에서 파일을 읽고 쓰며, 전체 지우기는 빈 Markdown을 렌더하고 살아 있는 핀의 휴지통 사본을 정리한 뒤 원본을 보관한다. 핀 파일(`pins.jsonl`·`pins.md`·`pins.dropped.jsonl`·`pins.seq`)을 쓰는 코드는 모두 `store.py`에 있다. 잠금 없이 동시에 저장하면 앞선 쓰기가 사라진다(핀 30개를 동시에 저장해 2개만 남은 결함이 이 규칙의 근거다). 핀 번호는 `pins.seq`에서 발급하고 삭제 뒤에도 다시 쓰지 않는다. 상세는 [domain.md](domain.md) §저장소 안전성이다.

### 5. 원본 원고는 서버가 고치지 않는다

빌드는 사본에서 하고, `--git-pull`은 `main`에서 `--ff-only`만 한다. rebase나 merge 커밋을 대신 만들지 않는다. git 호출은 모두 `limn/gitrun.py`를 거친다. 셸 없이 인자 목록으로, stdin과 제어 터미널 없이, `GIT_TERMINAL_PROMPT=0`과 서버의 `GIT_*` 변수를 뺀 환경에서, 시간 제한을 두고 돈다. 사용자 입력은 인자에 끼워 넣지 않는다. 상세는 [build-sync.md](build-sync.md) §git 프로세스다.

### 6. 옛 상태 디렉터리는 쓰기 마이그레이션 없이 읽는다

`doc` 필드가 없는 옛 레코드는 첫 문서로 읽고, `review` 필드가 없는 옛 `done:true` 레코드는 그냥 완료로 읽는다. `file_rel` 이 없는 옛 레코드는 저장된 `file` 로 지금 원고 폴더에서 파일을 찾는다. 읽는 쪽이 해석할 뿐 파일을 고쳐 쓰지 않는다. 그래서 옛 버전으로 되돌려도 상태 디렉터리가 그대로 동작한다.

### 7. 앱 이름은 Limn 하나이고 개인정보를 넣지 않는다

옛 이름은 README 역사 절, `limn migrate`, CHANGELOG에만 남는다. 실제 이메일·홈 경로·호스트 이름·논문 이름을 코드와 문서에 넣지 않는다. [`tests/test_naming.py`](../../tests/test_naming.py)가 이를 검사한다.

### 8. 사람에게 보이는 문자열과 계약 문자열을 구분한다

뷰어 UI 문자열의 원본은 템플릿 안 한국어이고, 영어 모드는 [`ui_en.json`](../../src/limn/ui_en.json) 대응표로 바꾼다. `pins.md`와 API 오류 문자열(`{"error": "<한국어>", "reason": "<코드>"}`)은 계약이라 번역하지 않는다. 뷰어의 영어 화면은 오류 문장을 옮기지 않고 안정 코드 `reason`으로 표의 영어 문장을 찾는다([api.md](api.md) §오류 응답). 코드·주석·docstring·테스트 이름·커밋 메시지·CLI 도움말은 영어로 쓴다.

## 멈춤 신호

아래 변경은 코드부터 쓰지 말고 멈춘다. 설계를 먼저 정하고 검토한 뒤 구현한다. 절차는 [workflow.md](workflow.md)에 있다.

| 신호 | 예 | 왜 멈추나 |
| --- | --- | --- |
| 런타임 의존성 추가 | `dependencies`에 패키지를 넣는다 | 불변식 2 |
| 새 저장 파일이나 저장 형식 변경 | 상태 디렉터리에 새 파일, 레코드 필드 의미 변경 | 불변식 4, 6. 옛 상태와의 호환을 설계해야 한다 |
| 새 상태 기계·권한·비동기 흐름 | 핀 상태 추가, 역할 기반 권한, 새 백그라운드 스레드 | 수명 주기와 동시성 규칙이 바뀐다 |
| 에이전트 계약 변경 | `pins.md` 열, API 필드·경로·상태 이름 | 불변식 3 |
| 도메인에서 인프라로의 의존 역전 | `pins/`가 HTTP·파일·소켓·git을 직접 import | 의존 방향 위반 |
| 핵심 값이 코드에만 있음 | 핀 번호 체계, 신원 판단 규칙 | 불변식·설계 축 변경 |
