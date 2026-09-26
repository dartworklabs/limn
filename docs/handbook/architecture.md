# 구조와 불변식

이 topic은 Limn이 지금 어떤 구조로 짜여 있는지, 모듈이 어느 방향으로 의존하는지, 그리고 구조가 바뀌어도 반드시 지켜야 하는 규칙이 무엇인지를 설명한다. 코드를 새로 놓을 자리를 고르거나, 모듈을 나누거나, 의존성·저장 파일·보안 경계를 건드리기 전에 읽는다. 구조 단위나 불변식이 바뀌면 같은 변경에서 이 파일을 고친다.

> **한눈에**
>
> - 요청 하나가 서버를 지나가는 흐름: §한 요청이 지나가는 길
> - 모듈의 층과 서로 상태를 주고받는 방식: §현재 구조
> - 모듈 사이에 허용되는 import 방향: §의존 방향
> - 채택한 설계 축 값: §채택한 설계 축
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

상태 디렉터리를 옮기거나 복제해서 SyncTeX가 옛 빌드 경로를 가리키는 경우도 있다. 이때는 경로 꼬리가 원고 트리 안의 파일과 맞을 때만 경로를 고쳐 쓴다. 원고 체크아웃을 옮겨 핀에 저장된 절대 경로가 낡은 경우도 같은 규칙에 원고 폴더 기준 상대 경로 `file_rel` 을 더해 읽을 때 찾는다([api.md](api.md) §핀 파일의 위치, [ADR-0006](../adr/0006-relative-pin-paths.md)). 원고 트리 밖의 파일은 절대 읽지 않는다. 원고 트리는 `--manuscript` 아래에서 점으로 시작하는 이름(`.git`·`.env` 등) 아래를 뺀 곳이고, 규칙은 `limn/files.py`의 `tree_part` 하나다. 역변환·범위 사다리·줄 맞춤의 규칙은 [domain.md](domain.md)에 있다.

## 현재 구조

Limn은 **하나의 배포 단위(`dartwork-limn` 패키지) 안에서 표준 라이브러리만 쓰는 책임별 모듈**로 나뉜다. 모듈은 네 층을 이루고, 안쪽 층은 바깥 층을 모른다. 경로마다의 책임과 함께 볼 topic은 [index.md](index.md) §파일 지도가 정본이다. 이 절은 층과 그 사이의 약속만 설명한다.

| 층 | 모듈 | 하는 일 | 모르는 것 |
| --- | --- | --- | --- |
| 순수 도메인 | `pins/`(상태 타입·레코드 검사·전이·편집·위치 규칙·API 모양·`pins.md` 렌더), `mapping.py`, `scope.py`, `pull.py`, `mentions.py`, `outline.py`, `guidance.py`, `mark.py` | 핀 수명 주기와 위치 계산의 규칙. 입력 값에서 결과 값이나 거절 값을 낸다 | 파일, subprocess, 시계, HTTP. 모듈마다 import 검사가 지킨다 |
| 부수효과 셸 | `service/`(핀 서비스), `store.py`, `build.py`, `locate.py`, `revisions.py`, `gitsync.py`, `gitrun.py`, `documents.py`, `meta.py`, `people.py`, `events.py`, `audit.py`, `files.py`, `access.py`, `startup.py`·`args.py`·`config.py` | 파일·git·SyncTeX·빌드 도구를 다루고, 순수 규칙에 묻고, 결과를 쓴다. 문서·설정·협력자를 인자로 받는다 | 실행 설정 `C`, `server.py`, HTTP 층 |
| HTTP 층 | `web/`(`handler.py`·`parse.py`·`answers.py`·`errors.py`·`app.py`) | 요청을 읽고 파싱하고, 서비스를 부르고, 결과마다 상태 코드와 본문으로 답한다 | `server.py`. 서비스 목록은 `web/app.py`의 `App` 프로토콜로만 안다 |
| 조립 지점 | `server.py` | 실행 설정 `C`와 문서 목록 `DOCS`, 프로세스에 하나인 자원(잠금·캐시·작업 목록·감시 상태)을 만들고, 옮긴 모듈에 이 인스턴스의 설정과 협력자를 묶는 한 줄 연결을 두고, 시작 단계를 차례로 부른다 | — |

층 밖에 나란히 있는 것이 둘이다.

- **뷰어** `viewer/`: 빌드 단계 없는 정적 파일(`index.html`, 스타일 조각 `css/`, 스크립트 조각 `js/`, 순서 목록 `parts.txt`, 서비스 워커 `sw.js`)과 그것을 한 장의 HTML로 잇는 `assemble.py`. 규칙은 [viewer.md](viewer.md)에 있다.
- **명령과 인스턴스 관리자** `cli.py`·`instances.sh`·`migrate.py`: `limn` 명령의 입구다. `serve`는 `server.main`으로, `token`·`member`는 `limn/access.py`의 상태 도우미로, 나머지는 `instances.sh`로 간다. `token`·`member`는 `server.py`를 가져오지 않는다. 감사 기록 싱크(`cli_audit`)도 `cli.py`에 있어서, 뷰어 조각이 깨져 서버가 뜨지 못해도 토큰을 취소할 수 있다. 규칙은 [instances.md](instances.md)에 있다.

`server.py`는 `limn serve`로는 패키지 모듈(`limn.server`)로, 인스턴스(`limn run` → `instances.sh`)에서는 파일 경로(`python …/limn/server.py`)로 실행된다. 파일로 실행될 때도 옆 모듈을 `limn.*`으로 가져올 수 있도록, `server.py`는 시작할 때 자기 폴더의 부모를 `sys.path` 앞에 넣는다. 그래서 `limn.*` import가 그 준비 뒤에 온다(Ruff `E402`를 이 파일에서만 끈다).

서버와 모듈은 Python 3.10 이상에서만 돈다. 3.9 이하는 `server.py`가 가져오는 `limn.*` 모듈(`match` 문, `typing.TypeAlias`)을 읽지 못해 시작하자마자 `ImportError`나 `SyntaxError`로 멈춘다. 인스턴스 경로가 안전한 이유는 두 가지다. `limn run`(systemd 유닛이 부르는 명령)은 자기가 도는 도구 가상환경의 파이썬을 `LIMN_PYTHON`으로 넘기고, 그 파이썬은 설치 때 `requires-python >= 3.10`을 이미 통과했다. `limn`을 거치지 않고 `instances.sh`를 직접 부르면 PATH에서 3.10 이상인 파이썬을 찾는다. 없으면 `help`를 뺀 모든 명령이 무엇이든 시작하기 전에 멈추고, 그 파이썬의 경로·버전·고치는 법을 한 줄로 알린다([instances.md](instances.md) §환경 변수).

### 상태를 주고받는 방식

1. **실행 설정 `C = Cfg()`는 조립 지점에만 있다.** 타입은 `limn/config.py`에 있고, 시작할 때 `limn/startup.py`의 규칙이 낸 값을 `server.py`가 채운다. 옮긴 모듈은 `C`를 읽지 않고, 필요한 값을 작은 설정 값(`BuildConfig`, `AccessSettings`, `MetaSettings`, `PickContext` 등)으로 받는다. HTTP 처리기는 `app.C`로 몇 개의 설정(Origin 검사 여부, 강조색, 원고 폴더)을 읽는다.
2. **문서는 인자다.** 처리기가 요청의 문서를 찾아(`request_doc`) 서비스마다 넘기고, 빌드 스레드는 자기 문서를 갖고 시작하며, 기동은 문서 목록을 돈다. "지금 문서" 같은 스레드 지역 값은 없다.
3. **잠금과 상태는 주인이 하나다.** 핀 잠금 `PIN_LOCK`은 `server.py`가 프로세스에 하나 만들어 `pin_store()`로 저장소(`limn/store.py`)에 넘긴다. 저장소 자신은 잠금을 만들지 않는다. 문서마다의 빌드 잠금과 빌드 상태는 문서 객체(`limn/documents.py`의 `Doc`)가 갖는다.

핀 레코드는 저장소와 셸에서 파이썬 `dict` 그대로 다닌다. 전이 앞에서 [`limn/pins/model.py`](../../src/limn/pins/model.py)가 레코드를 상태 타입(`OpenPin`·`ReviewPin`·`DonePin`)으로 파싱하고, 그 상태에만 있는 필드(열림의 처리 중 표시, 닫힘의 닫은 기록, 완료의 확인)를 타입의 속성으로 올린다. 나머지 필드는 저장된 그대로 순서까지 지켜 다시 쓴다. 상태를 정하는 규칙은 `state_of` 하나이고, API의 `state` 이름은 그 상태 타입의 이름이다. 전이는 그 타입을 받아 결과를 반환값으로 돌려준다. 잠금 아래 레코드를 읽어 파싱하고 전이를 부르고 결과를 다시 쓰는 셸은 [`limn/service/`](../../src/limn/service/context.py)에 있다.

> **참고**
>
> 이 구조의 장점은 배포가 `uv tool install` 한 번으로 끝나고, 테스트가 포트를 열지 않고 처리기를 소켓 쌍으로 직접 몰 수 있다는 것이다. 코드를 쓸 때 지키는 규칙과 아직 남은 구조 작업은 [code-style-roadmap.md](code-style-roadmap.md)에 있다.

## 의존 방향

층의 이름보다 지켜야 하는 것은 import 방향이다. 방향이 깨지면 순수 규칙을 서버 없이 테스트할 수 없고, 한 프로세스에 여러 벌 올라온 서버 사본이 서로의 설정과 잠금에 닿는다.

- **순수 도메인은 부수효과를 가져오지 않는다.** `pins/`·`mapping.py` 등은 파일·subprocess·HTTP 타입을 가져오지 않는다. `store`·`service`·`build`·`web`이 그 순수 모듈을 불러 쓴다. `service`는 `store`를 쓴다.
- **`web/`은 `server.py`를 가져오지 않는다.** `server.py`는 한 프로세스에 여러 벌 올라올 수 있다(`limn.server`, 파일로 실행한 `__main__`, 테스트가 경로로 올린 사본). 가져오면 지금 요청을 받는 사본이 아닌 다른 사본의 설정·문서·잠금에 닿는다. 그래서 조립 지점이 자기 처리기 하위 클래스를 자기 서비스에 묶고(`server.Handler.app`), 처리기는 요청 때마다 그 이름을 읽는다. 처리기는 서비스를 직접 가져오지 않고 조립 지점이 묶은 `App`을 거친다. `tests/test_web.py`가 이 방향을 검사한다.
- **안쪽은 HTTP를 모른다.** 요청 파싱은 처리기 쪽(`web/parse.py`)이라 서비스는 파싱된 값만 받는다. 서비스와 원고 이력·문서 조회는 결과 값(`CommitNotRecent`·`DocNotFound` 등)을 돌려주고 `web/answers.py`가 답한다. 조립 지점은 비교 PDF 워커에 실패 문구 함수(`web/errors.py`의 `revision_failure_text`)를 넘기려고 `web/errors.py`를 가져온다. 이 문구는 HTTP 응답과 같은 표에서 나와야 하고 서비스는 `web/`을 가져오지 않기 때문이다.
- **접근 제어는 거절을 던진다(fail closed).** 신원·입장·역할 판단(`limn/access.py`)은 거절로 `HTTPError`를 던지고 확인 거절 문구(`CONFIRM_BY_HUMAN`)를 `web/`에서 가져온다. 새로 짠 호출자가 거절을 놓쳐도 요청이 통과하지 않게 하려는 것으로, "거절은 값"이라는 코딩 규칙의 유일한 예외다([code-style-roadmap.md](code-style-roadmap.md) §R10). `server.py`를 가져오지 않으므로 처리기와 같은 방향이다.
- **HTTP 층의 이름은 `http/`가 아니라 `web/`이다.** 파일로 실행될 때 `limn/` 폴더 자체도 `sys.path` 맨 앞에 온다. 표준 라이브러리 모듈과 이름이 같은 패키지(`limn/http/` 등)를 두면 표준 모듈(`http.server`)이 가려져 서버가 뜨지 않는다.
- **조립 지점만 전역 자원을 만들고 끝낸다.**

## 채택한 설계 축

설계 축은 프로젝트가 기본 청사진에서 어디가 달라지는지를 묻는 질문 목록이다. 아래 값이 **현재 채택값**이고, 채택한 이유와 버린 대안은 [ADR-0001](../adr/0001-blueprint.md)에 남긴다. 표에 없는 축(경제·비용 게이트, 외부 검수 권위)은 Limn에서 달라지지 않아 따로 정하지 않았다.

| 축 | 채택값 | 근거와 적용 |
| --- | --- | --- |
| 1차 구조 | **작은 단일 배포 + 책임별 모듈.** 순수 도메인·부수효과 셸·HTTP 층·조립 지점(§현재 구조) | 배포 단위·런타임이 하나다. 서버·인스턴스 관리자·migrate의 수명 주기만 다르다 |
| 도메인 정체 | **핀의 수명 주기와 위치 규칙.** 상태 전이, 역변환·범위 사다리·anchor 재동기화 | [domain.md](domain.md) |
| 함수형 DDD 범위 | **실용적 함수형.** 판단은 순수 함수, 부수효과(파일·git·subprocess·HTTP)는 가장자리. 의미 있는 수명 주기(핀 상태)에만 상태별 타입과 전이 함수를 쓰고, 계산·파싱은 평범한 함수로 둔다. 예상된 거절은 예외가 아니라 반환 타입의 거절 값으로 돌려준다(`confirm() -> DonePin \| AlreadyDone \| PinStillOpen`, `confirmer() -> Person \| AgentCannotConfirm`) | 우리 코딩 스킬 `code-implement`의 기본값. 규칙과 예는 [code-style-roadmap.md](code-style-roadmap.md) |
| 검수 진실원 | **자동 테스트 녹색 + 에이전트 계약 불변 + 화면 실측.** pytest·셸 테스트·Playwright 레이아웃 테스트가 통과하고, `pins.md`·HTTP API가 호환을 지키며, 화면 규칙은 실측 스크린샷으로 확인한다 | [verification.md](verification.md) |
| 검수 시점 | **머지 전 게이트.** CI가 막는다 | [verification.md](verification.md) |
| HARD-GATE | **행동 계약 변경 전.** 에이전트 계약·보안 경계·저장 형식을 바꾸는 변경은 설계 승인 뒤 구현한다 | [workflow.md](workflow.md) |
| 정본 매체 | 동작은 **코드**, 에이전트 계약은 **[api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)**, 데이터는 **상태 디렉터리 파일**. Handbook은 설계 교과서이자 안내판 | [purpose.md](purpose.md) §진실 소스 |
| Handbook 책임 구성 | 목적·구조·도메인·뷰어·빌드·API·운영 두 편·검증·변경 흐름·코딩 규칙으로 나눈다 | [index.md](index.md) |
| 시간축 호환 | **옛 상태 디렉터리와 옛 에이전트를 깨지 않는다.** 옛 레코드는 읽을 때 해석하고 쓰기 마이그레이션을 하지 않는다 | §불변식 3, 6 |

## 불변식

아래 규칙은 구조를 어떻게 바꾸든 유지한다. 각 규칙이 언제 적용되는지, 누가 지키는지, 어기면 무엇이 깨지는지를 함께 적는다.

### 1. 신원 방식 없이 loopback 밖에 열지 않는다

기본 바인드 주소는 `127.0.0.1`이다. `--bind`로 다른 주소를 줄 수 있지만, loopback이 아닌 주소는 신원을 프록시가 보증하는 `--auth trusted-proxy`일 때만 받는다. 그 밖에는 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수는 있지만 크게 경고한다. 테일넷 노출은 `tailscale serve`, 그 밖의 노출은 인증 리버스 프록시가 맡고, `tailscale funnel`은 쓰지 않는다. 이 규칙이 깨지면 포트에 닿는 누구나 원고를 읽고 핀을 바꿀 수 있다. 근거와 위협 모델은 [SECURITY.md](../../SECURITY.md), 운영 상세는 [operations.md](operations.md) §보안 제약, 설계와 이후 단계는 [ADR-0002](../adr/0002-access-control.md)에 있다.

신원은 인스턴스마다 방식 하나(`tailscale`·`local`·`trusted-proxy`)로 정하고, 에이전트는 API 토큰으로 인증한다. 서버 머신의 에이전트는 토큰 원문을 설정 폴더의 토큰 파일(`<이름>.token`, `0600`, 저장소 밖)에서 읽고, 서버는 그 파일을 읽지 않는다([ADR-0007](../adr/0007-agent-token-file.md)). 권한은 `people.json`의 역할(owner·editor·viewer·agent)이 정하고, 처리기 한 곳에서 집행한다. 신원·입장·역할 판단과 Host/Origin 규칙의 코드는 [`limn/access.py`](../../src/limn/access.py) 한 곳에 있다. 이 모듈은 실행 설정(`C`)을 읽지 않는다. 조립 지점(`server.py`)이 요청마다 실행 설정 값(`AccessSettings`)과 파일 사실(`AccessLookups`: `tokens.json`·`people.json`을 파일이 바뀔 때만 다시 읽는 캐시, 프로세스에 하나씩)을 넘긴다. 이 경계의 거절은 값으로 돌려주지 않고 `HTTPError`를 던진다(§의존 방향). 파일 사실도 같은 쪽으로 닫는다. 쓸 수 없는 `tokens.json`은 토큰을 하나도 받지 않고, 쓸 수 없는 `people.json`은 헤더로 들어온 모든 사람을 `viewer`로 두고 멤버 자격을 주지 않으며 다시 쓰이지 않는다. 헤더 없는 요청을 에이전트로 보는 것은 이 기기를 부른 요청(루프백 `Host`)뿐이고, 모든 핀을 지우는 일은 소유자만 한다([ADR-0003](../adr/0003-tailnet-headerless-and-owner-clear.md)). 상세는 [api.md](api.md) §인증이다.

### 2. 서버 런타임은 표준 라이브러리만 쓴다

`pyproject.toml`의 `dependencies = []`가 이 규칙의 실행 정본이다. Python 3.10 이상에서 돈다. 뷰어도 React·Tailwind·빌드 단계·CDN 없이 번들한 PDF.js와 Lucide만 쓴다. 뷰어의 CSS·JS가 여러 조각 파일이어도 번들러나 모듈 로더를 들이지 않는다. 서버가 `parts.txt` 순서대로 조각을 이어 인라인 `<style>`·`<script>` 하나씩으로 내보낸다. 배포가 패키지 설치 하나로 끝나야 연구실 머신에서 유지할 수 있기 때문이다. 개발 의존성(pytest, Playwright, Ruff, ShellCheck, mypy)은 이 규칙과 무관하다.

### 3. 에이전트 계약은 호환을 깨지 않는다

`pins.md`의 열·표시어·한국어 머리말과 HTTP API의 경로·JSON 필드 이름·상태 이름은 다른 저장소의 에이전트가 읽는다. 새 필드와 경로를 더하는 것은 되지만, 바꾸거나 빼려면 버전이 붙은 이전 계획이 먼저 있어야 한다. UI 언어가 바뀌어도 계약은 번역하지 않는다. 계약의 본문은 [api.md](api.md)다.

### 4. 핀 파일은 한 잠금 아래 정해진 순서로만 쓴다

핀 파일을 만지는 모든 경로는 `PIN_LOCK` 하나 아래에서 **읽기 → 재동기화 → 요청한 변경 적용 → 임시 파일에 쓰고 `os.replace` → `pins.md` 재생성** 순서를 지킨다. [`limn/store.py`](../../src/limn/store.py)의 `PinStore.transact()`가 이 순서를 강제하고, 핀 파일(`pins.jsonl`·`pins.md`·`pins.dropped.jsonl`·`pins.seq`)을 쓰는 코드는 모두 `store.py`에 있다. 잠금 없이 동시에 저장하면 앞선 쓰기가 사라진다(핀 30개를 동시에 저장해 2개만 남은 결함이 이 규칙의 근거다). 핀 번호는 `pins.seq`에서 발급하고 삭제 뒤에도 다시 쓰지 않는다. 상세는 [domain.md](domain.md) §저장소 안전성이다.

### 5. 원본 원고는 서버가 고치지 않는다

빌드는 사본에서 하고, `--git-pull`은 `main`에서 `--ff-only`만 한다. rebase나 merge 커밋을 대신 만들지 않는다. git 호출은 모두 `limn/gitrun.py`를 거친다. 셸 없이 인자 목록으로, stdin과 제어 터미널 없이, `GIT_TERMINAL_PROMPT=0`과 서버의 `GIT_*` 변수를 뺀 환경에서, 시간 제한을 두고 돈다. 사용자 입력은 인자에 끼워 넣지 않는다. 상세는 [build-sync.md](build-sync.md) §git 프로세스다.

### 6. 옛 상태 디렉터리는 쓰기 마이그레이션 없이 읽는다

`doc` 필드가 없는 옛 레코드는 첫 문서로 읽고, `review` 필드가 없는 옛 `done:true` 레코드는 그냥 완료로 읽는다. `file_rel` 이 없는 옛 레코드는 저장된 `file` 로 지금 원고 폴더에서 파일을 찾는다. 읽는 쪽이 해석할 뿐 파일을 고쳐 쓰지 않는다. 그래서 옛 버전으로 되돌려도 상태 디렉터리가 그대로 동작한다.

### 7. 앱 이름은 Limn 하나이고 개인정보를 넣지 않는다

옛 이름은 README 역사 절, `limn migrate`, CHANGELOG에만 남는다. 실제 이메일·홈 경로·호스트 이름·논문 이름을 코드와 문서에 넣지 않는다. [`tests/test_naming.py`](../../tests/test_naming.py)가 이를 검사한다.

### 8. 사람에게 보이는 문자열과 계약 문자열을 구분한다

뷰어 UI 문자열의 원본은 템플릿 안 한국어이고, 영어 모드는 [`ui_en.json`](../../src/limn/ui_en.json) 대응표로 바꾼다. `pins.md`와 API 오류 문자열(`{"error": "<한국어>", "reason": "<코드>"}`)은 계약이라 번역하지 않는다. 뷰어의 영어 화면은 오류 문장을 옮기지 않고 안정 코드 `reason`으로 표의 영어 문장을 찾는다([api.md](api.md) §오류 응답). 코드·주석·docstring·테스트 이름·커밋 메시지·CLI 도움말은 영어로 쓴다.

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
| 도메인이 부수효과를 부름 | 순수 모듈이 파일·subprocess·HTTP 타입을 가져온다 | §의존 방향 |
