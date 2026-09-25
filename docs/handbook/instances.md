# 인스턴스 — 원고마다 Limn 하나

이 문서는 연구실 머신에서 여러 원고의 Limn을 상시로 띄우고 관리하는 운영자가 읽는다. 인스턴스 관리자(`limn add|start|stop|update|list|status|url|snippet|doc|remove|run`)의 명령, 설정 키, 기본 문서 탭, `DOCS=`, 업데이트와 되돌리기, 포트, 접근 토큰과 멤버, 보안 규칙, 환경 변수를 다룬다. 인스턴스 관리자의 CLI 플래그, 설정 키, 유닛 템플릿, 상태 폴더 배치 가운데 하나라도 바뀌면 이 문서를 같은 변경에서 고친다.

`limn serve`는 서버 하나를 앞(foreground)에서 띄운다. 몇 주씩 다루는 원고는 **인스턴스**로 띄운다. 인스턴스는 systemd 사용자 유닛 `limn@<이름>` 하나이고, 포트·상태 폴더·journal이 인스턴스마다 따로다. 논문마다 저장소가 따로이고 동시에 작업하는 일이 잦아서 원고마다 인스턴스를 하나씩 둔다. 설치된 `limn` 패키지 하나를 모든 인스턴스가 함께 쓴다.

서버 프로세스 하나의 계약(실행 인자, `--doc` 규칙, Host·Origin 검사, 상태 파일 배치)은 [operations.md](operations.md)가 맡는다. 인스턴스 관리자의 동작 정본은 [`src/limn/instances.sh`](../../src/limn/instances.sh)이고, `limn` 명령이 이 스크립트로 넘기는 부분은 [`src/limn/cli.py`](../../src/limn/cli.py)다.

> **한눈에**
>
> 먼저 아래 '무엇이 어디에 있나' 표와 명령 목록을 본다. 새 원고는 '새 원고 추가'와 기본 문서 탭 절, 문서를 여럿 띄우려면 `DOCS=` 절을 본다. 버전을 바꿀 때는 '업데이트와 되돌리기', 포트나 노출이 막히면 포트 절과 보안 규칙 절을 본다. 에이전트에게 토큰을 주거나 사람의 역할을 정하려면 '접근: 토큰과 멤버' 절을 본다.

| 무엇 | 어디 |
| --- | --- |
| 유닛 템플릿 | `limn add`·`limn start`가 패키지의 템플릿을 채워 `~/.config/systemd/user/limn@.service`에 쓴다(인스턴스 이름 = 논문 슬러그) |
| 인스턴스 설정 | `~/.config/limn/<이름>.env` (`LIMN_CONFIG_DIR`) |
| CLI | `limn` (`uv tool install`로 설치) |
| 앱 | 설치된 `limn` 패키지. 올리기와 되돌리기는 `limn update` |
| 상태(인스턴스별) | 설정의 `STATE_DIR`, 기본 `~/.local/share/limn/<이름>`. 핀, `build/`, `build.log`, `pins.md`가 여기 있다 |
| 로그(인스턴스별) | `journalctl --user -u limn@<이름>` · `<STATE_DIR>/build.log` |

## 명령

`limn`은 `serve`·`version`·`migrate`와 접근 명령 `token`·`member`를 직접 처리하고, 나머지 명령은 인스턴스 관리자로 넘긴다. 인스턴스 이름은 `[a-z0-9-]+`이고 영문 소문자나 숫자로 시작해야 한다. `serve`는 예약어라 쓸 수 없다. `limn serve`의 상태 폴더 `<데이터 루트>/serve`와 겹치기 때문이다.

| 명령 | 하는 일 |
| --- | --- |
| `limn add <이름> --manuscript <dir> [...]` | 포트 배정, 설정 작성, 유닛 enable·start, `tailscale serve`, AGENTS.md 조각 출력까지 한 번에 한다. 옵션은 아래 '새 원고 추가' 절 |
| `limn start <이름> [--no-serve]` | 설정이 이미 있는 인스턴스를 켠다(재부팅 뒤, 새 머신, 전환). 유닛이 꺼져 있는데 로컬 포트가 LISTEN 중이면 멈춘다 |
| `limn stop <이름>` | 유닛만 끄고 비활성화한다. 설정·포트·serve 항목은 남는다 |
| `limn update [--ref <tag\|branch>] [--from <설치 원본>] [--dry-run] [--force] [--no-restart]` | `limn`을 다시 설치하고 켜진 인스턴스를 재시작한다. 아래 '업데이트와 되돌리기' 절 |
| `limn list` (`ls`) | 인스턴스 표. 이름, 이름표, 로컬 포트, 테일넷 포트, 상태, 열린 핀 수, 문서 수, 원고 폴더를 보여 준다 |
| `limn status [<이름>]` | 상세 상태. 유닛 상태·enable 여부·PID, 로컬 주소 응답 코드, 테일넷 주소와 serve 항목, 문서 목록, 상태 폴더와 열린 핀 수, 설정 파일, 로그 위치를 보여 준다 |
| `limn url [<이름>]` | 테일넷 주소 |
| `limn snippet <이름>` | 그 논문 저장소의 AGENTS.md에 붙일 조각을 출력한다(출력만) |
| `limn doc list <이름>` | 문서 키·이름·경로 표 |
| `limn doc add <이름> --doc '<키>=<이름>:<경로>' [--doc …] [--restart]` | 기존 인스턴스에 문서를 더한다 |
| `limn doc remove` (`rm`) `<이름> <키> [--restart]` | `DOCS`에서 문서 하나를 뺀다. 마지막 문서는 뺄 수 없다 |
| `limn doc suggest --manuscript <dir> [--stage auto\|initial\|revision]` | 자동 탐지될 `DOCS` 문자열만 출력한다(읽기 전용) |
| `limn remove` (`rm`) `<이름>` | 유닛 중지·비활성, serve 해제, 설정 삭제. 상태 폴더는 지우지 않는다 |
| `limn run <이름>` | 유닛 전용. 설정을 읽고 검증한 뒤 서버로 exec한다 |
| `limn token create`·`list`·`revoke <이름> …` | 에이전트 API 토큰을 만들고 보고 폐기한다. 아래 '접근: 토큰과 멤버' 절 |
| `limn member add`·`list`·`role`·`remove <이름> …` | `people.json`의 멤버와 역할을 고친다. 아래 '접근: 토큰과 멤버' 절 |

## 설정 키

설정 파일은 `KEY=VALUE`를 한 줄씩 쓴다. systemd `EnvironmentFile` 형식의 부분집합이고, `limn`이 직접 읽는다.

> **주의**
>
> 설정 파일은 **셸로 source하지 않는다.** 설정 한 줄이 코드가 되면 안 되기 때문이다. 그러니 값에 셸 문법을 쓰지 않는다. 따옴표, 역슬래시, `$`, 백틱, 줄바꿈은 `limn add`가 거부한다.

| 키 | 뜻 |
| --- | --- |
| `MANUSCRIPT` | 원고 폴더(LaTeX 소스 루트, 절대경로) |
| `MAIN` | 최상위 `.tex` 파일 이름(원고 폴더 맨 위) |
| `PORT` / `TS_PORT` | 로컬 포트(`BIND`가 없으면 `127.0.0.1`)와 테일넷 `https` 포트. **실행 때 자동으로 고르지 않는다.** 알린 주소가 바뀌면 안 되기 때문이다 |
| `STATE_DIR` | 상태 폴더. 다른 인스턴스와 겹치면 `limn add`가 거부한다. 비어 있으면 `<데이터 루트>/<이름>`을 쓴다 |
| `GIT_PULL` | `1`이면 재빌드마다 원고 체크아웃을 `--ff-only`로 당긴다 |
| `LABEL` / `ACCENT` | 뷰어 이름표와 강조색(`#rrggbb`) |
| `EXTRA_ARGS` | 그 밖의 서버 인자(공백으로 나눔). `limn add`의 기본값은 `--no-build`다. 산출물이 없으면 서버가 어차피 빌드한다 |
| `DOCS` | 여러 문서(본문, 답변서, 보기 전용 PDF 등)를 탭으로 전환한다. `MAIN`과 함께 쓰지 않는다. 아래 '여러 문서 (`DOCS=`)' 절 |

값에 공백이나 `#`이 있으면 `limn`이 큰따옴표로 감싸 쓴다. `#`을 주석으로 읽는 파서가 있기 때문이다.

### 접근 설정 키 (v0.2)

접근 제어 키는 모두 선택이다. 없는 키는 서버 플래그를 하나도 더하지 않는다. 그래서 이 키가 없는 설정은 v0.1과 똑같이 돈다. 각 플래그의 뜻과 신원 방식별 동작은 [operations.md](operations.md) §접근 제어 인자 (v0.2)가 정본이고, 토큰과 역할을 다루는 명령은 아래 '접근: 토큰과 멤버' 절에 있다.

| 키 | 서버 플래그 | 뜻 |
| --- | --- | --- |
| `AUTH` | `--auth` | 신원 방식. `tailscale`(없을 때 기본)·`local`·`trusted-proxy`. `limn add --auth <방식>`이 적는다 |
| `AGENT_LOOPBACK` | `0`이면 `--no-agent-loopback`, `1`이면 `--agent-loopback` | `0`이면 헤더 없는 loopback 요청을 거부한다. 에이전트는 토큰을 써야 한다. `1`은 `tailscale` 방식과 loopback `BIND`에서만 된다 |
| `BIND` | `--bind` | 들을 주소. 기본 `127.0.0.1`. loopback이 아니면 `AUTH=trusted-proxy`가 있어야 한다. `EXTRA_ARGS`에 `--i-know-this-is-insecure`가 있으면 예외다 |
| `PUBLIC_HOSTS` | `--public-host` | 인스턴스에 닿는 공개 이름 `이름[:포트]`을 쉼표로 잇는다. Host·Origin으로 받고 `pins.md`의 기준 주소로 쓴다 |
| `TRUSTED_PROXIES` | `--trusted-proxies` | `trusted-proxy` 방식이 신원 헤더를 믿는 IP·CIDR 목록(쉼표, 기본 `127.0.0.1,::1`) |
| `PROXY_USER_HEADER` / `PROXY_NAME_HEADER` / `PROXY_EMAIL_HEADER` | `--proxy-user-header` / `--proxy-name-header` / `--proxy-email-header` | `trusted-proxy` 방식의 헤더 이름. 기본은 차례로 `X-Forwarded-User`, `X-Forwarded-Preferred-Username`, 없음 |
| `MEMBERS_ONLY` | `1`이면 `--members-only` | `people.json`(또는 `--allow`)에 있는 사람만 들인다 |
| `LOCAL_USER` | `--local-user` | `AUTH=local`에서 소유자의 로그인(기본 `$USER`) |

`limn run`은 서버를 띄우기 전에 이 값들을 검사한다. 서버가 거부할 값이면 유닛이 같은 오류로 재시작을 되풀이하는 대신 분명한 오류로 멈춘다.

## 새 원고 추가

```bash
# 1. 추가 — 포트 배정·설정 작성·유닛 enable·start·tailscale serve·AGENTS.md 조각 출력
limn add paper2 --manuscript ~/papers/paper2 --git-pull --label Paper2
# 2. 출력된 조각을 그 논문 저장소의 AGENTS.md 에 붙인다(다시 보기: limn snippet paper2)
```

`--main`과 `--doc`을 생략하면 문서를 자동 탐지한다(다음 절). 표준 구조가 아니면 원고 폴더 맨 위에서 `\documentclass`가 있는 `.tex` 하나를 찾는다. 두 개 이상이면 추측하지 않고 멈춘다. `--label`을 생략하면 원고 저장소 이름(`origin` URL 끝)을 쓴다.

`limn add`가 받는 옵션은 다음과 같다.

| 옵션 | 뜻 |
| --- | --- |
| `--manuscript <dir>` | 원고 폴더. 필수 |
| `--main <file.tex>` | 최상위 `.tex`. 원고 폴더 맨 위에 있어야 한다. `--doc`과 함께 쓰지 않는다 |
| `--doc <키>=<표시 이름>:<경로>` | 문서. 여러 번 준다. `--main`과 함께 쓰지 않는다 |
| `--stage auto\|initial\|revision` | 기본 문서 탭 자동 탐지에만 쓴다. `--doc`·`--main`과 함께 주면 거부한다 |
| `--port N` / `--ts-port N` | 로컬 포트와 테일넷 포트를 직접 준다. 하나만 주면 나머지는 짝 간격(`LIMN_LOCAL_OFFSET`, 기본 `100`)으로 계산한다 |
| `--git-pull` | 설정에 `GIT_PULL=1`을 쓴다 |
| `--label <이름표>` | 40자 이하. 생략하면 저장소 이름, 그것도 없으면 인스턴스 이름 |
| `--accent <#rrggbb>` | 강조색 |
| `--state-dir <dir>` | 상태 폴더. 절대경로여야 한다 |
| `--extra "<서버 인자>"` | `EXTRA_ARGS`에 들어간다. 기본은 `--no-build` |
| `--no-serve` | `tailscale serve`를 걸지 않고 로컬에서만 띄운다 |
| `--auth tailscale`·`local`·`trusted-proxy` | 설정에 `AUTH`를 쓴다. `local`과 `trusted-proxy`는 `--no-serve`와 함께만 받는다(아래 '보안 규칙' 절) |
| `--no-start` | 설정만 쓰고 켜지 않는다. 나중에 `limn start <이름>`으로 켠다 |

같은 이름의 설정이 이미 있으면 `limn add`는 멈춘다. 다시 켜려면 `limn start <이름>`을 쓰고, 새로 만들려면 먼저 `limn remove`한다. 동시에 여러 `add`가 돌 때 포트 선택과 설정 쓰기가 겹치지 않도록 `<설정 폴더>/.lock`에 잠금을 건다(`flock`이 있으면, 최대 30초 대기).

시작 뒤에는 `127.0.0.1:<PORT>`의 `/api/meta`가 HTTP 200을 돌려줄 때까지 기다린다. 첫 기동은 빌드를 기다리므로 최대 `LIMN_WAIT`초(기본 240)까지 걸린다.

설정을 다른 저장소(예: dotfiles)에서 관리한다면 `LIMN_SOURCE_DIR`로 그 폴더를 가리킨다. 그러면 `limn add`가 설정 원본을 거기에 쓰고 `~/.config/limn/`에 링크를 건다. 원본 쪽 변경은 그 저장소에서 커밋하라고 `limn`이 알려 준다.

## 기본 문서 탭 자동 탐지

`--doc`과 `--main` 없이 추가할 때 원고 폴더가 표준 논문 저장소 구조면 탭을 자동으로 만든다.

| 탭 | 키 | 경로 | 포함 조건 |
| --- | --- | --- | --- |
| 본문 | `ms` | `manuscript/<최신 라운드>/<본문>.tex` | 구조가 맞으면 항상 |
| 답변서 | `rr` | `submission/review_response/review_response.tex` | revision 단계이고 파일이 있을 때 |
| 하이라이트 | `hl` | `submission/highlights/highlights.tex` | 파일이 있을 때 |
| 커버레터 | `cl` | `submission/cover_letter/cover_letter.tex` | 파일이 있을 때 |

본문은 다음 순서로 고른다.

1. 라운드는 `manuscript/` 아래에서 맨 앞 숫자가 가장 큰 폴더다(`1st`·`2nd`…). 숫자로 시작하지 않는 폴더는 무시한다.
2. 라운드 폴더에서 `\documentclass`가 있는 `.tex`가 하나면 그 파일이다.
3. 후보가 여럿이면 가장 최근에 커밋된 파일을 고른다. git 밖이거나 추적되지 않은 파일은 수정 시각으로 비교한다.
4. 시각까지 같으면 추측하지 않고 오류로 멈춘다. 그때는 `--doc`으로 직접 준다.

본문 항목은 빌드 루트를 `manuscript/`로 넓힌 `ms=본문:manuscript::<라운드>/<본문>.tex` 형식으로 기록된다. 라운드 폴더가 옆 라운드의 그림을 읽을 수 있게 하려는 것이다.

순서는 `ms` → `rr` → `hl` → `cl`로 고정이다. 단계는 `--stage auto|initial|revision`으로 정한다. 기본 `auto`는 `<원고 폴더>/reviews/`가 있으면 revision이다. 탭 이름은 위 표의 한국어 이름 그대로 설정에 저장된다. 이름을 바꾸려면 `DOCS`를 고친다.

```bash
limn doc suggest --manuscript ~/papers/paper2      # 읽기 전용 — 자동 탐지될 DOCS 미리 보기
limn add paper2 --manuscript ~/papers/paper2        # 같은 결과를 설정에 쓴다
```

## 여러 문서 (`DOCS=`)

> **예시**
>
> ```bash
> limn add paper2 --manuscript ~/papers/paper2 --label Paper2 \
>   --doc 'ms=본문:manuscript::2nd/main.tex' \
>   --doc 'rr=답변서:submission/review_response/review_response.tex' \
>   --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf'
>
> limn doc add paper2 --doc 'cl=커버레터:submission/cover_letter/cover_letter.tex' --restart
> limn doc list paper2
> limn doc remove paper2 cl
> ```

| 항목 | 규칙 |
| --- | --- |
| `--doc` 형식 | `<키>=<표시 이름>:<경로>`. 첫 `=` 앞이 키, 다음 `:`까지가 이름, 나머지가 경로 |
| 키 | `[a-z0-9-]{1,24}`, 중복 금지. 핀에 남으므로 한 번 정하면 바꾸지 않는다 |
| 이름 | 비어 있으면 안 되고 40자 이하 |
| 경로 | `--manuscript` 기준 상대(권장) 또는 절대. 반드시 `--manuscript` 안. `.tex`(LaTeX)나 `.pdf`(보기 전용)만 받는다 |
| `x/main.tex` | LaTeX, 빌드 루트 `x/` |
| `root::sub/main.tex` | LaTeX, 빌드 루트 `root/`(복사 범위를 넓힌다), 메인 `root/sub/main.tex` |
| `x/file.pdf` | 보기 전용(재빌드 없음, 쪽·영역 핀) |
| 개수 | 12개까지 |
| `MAIN`과의 관계 | 함께 쓰지 않는다. `add`와 `run`이 거부한다 |
| 설정 파일 형식 | `DOCS="<키1>=<이름1>:<경로1>;<키2>=…"`. `;`로 나누고, 이름에 공백이 있을 수 있어 따옴표로 싼다 |

`limn`은 설정에 쓰기 전에 이 규칙을 먼저 검사한다. 서버도 기동 때 다시 검사하지만, 앞에서 걸러 두면 systemd 재시작 반복 대신 `limn add`나 `limn doc add` 시점에 분명한 오류가 난다.

단일 문서(`MAIN`) 인스턴스에 `limn doc add`를 하면 본문이 첫 항목 `main=본문:<MAIN>`으로 옮겨지고 설정이 `DOCS`로 바뀐다. 키 `main`은 옛 상태 배치를 그대로 쓰므로 빌드 이력과 옛 핀이 이어진다. 서버 쪽 계약은 [operations.md](operations.md) §여러 문서 (`--doc`)에 있다.

`limn doc add`와 `limn doc remove`는 `--restart`를 주면 유닛을 재시작하고 HTTP 200을 기다린다. 주지 않으면 재시작 방법(`limn stop <이름> && limn start <이름>` 또는 `--restart`)만 알려 준다.

## 동시 실행

인스턴스마다 포트, 상태 폴더, 빌드 폴더(`<STATE_DIR>/build`), journal이 따로다. 서버는 원고를 `<STATE_DIR>/build`로 복사해 거기서 빌드한다. 그래서 동시에 재빌드해도 서로 건드리지 않는다.

두 인스턴스가 같은 원고 폴더를 보면 `limn add`가 경고한다. 빌드는 따로 돌지만 `--git-pull`이 겹치기 때문이다.

## 유닛 템플릿

유닛 파일은 패키지 안 템플릿 [`src/limn/systemd/limn@.service`](../../src/limn/systemd/limn@.service)를 채워 만든다. `limn add`, `limn start`, `limn update`가 `~/.config/systemd/user/limn@.service`(`LIMN_USER_UNIT_DIR`)에 쓴다. 심링크가 아니라 사본이다. uv가 도구를 다시 설치하면 패키지 경로가 바뀔 수 있기 때문이다.

채우는 자리는 셋이다.

| 자리 | 채우는 값 |
| --- | --- |
| `@LIMN_BIN@` | 지금 실행 중인 `limn` 실행 파일. uv의 bin 폴더(`~/.local/bin/limn`) 경로를 심링크 해석 없이 쓴다. 업그레이드 뒤에도 살아남는 경로라서다 |
| `@LIMN_CONFIG_DIR@` | 설정 폴더 |
| `@LIMN_PATH@` | 유닛 안의 `PATH`. 유닛을 쓰는 셸에서 찾은 `pdflatex`의 폴더를 맨 앞에 두고 `/usr/local/bin:/usr/bin:/bin`을 붙인다. `LIMN_UNIT_PATH`로 바꾼다 |

`PATH`를 채우는 이유는 systemd 유닛이 셸 rc 파일을 읽지 않아 대화형 셸의 `PATH`를 물려받지 못하기 때문이다. 이 값이 없으면 재빌드가 배포판의 `pdflatex`를 잡아 저널 클래스(`.cls`)를 못 찾는다.

템플릿의 나머지 설정은 다음과 같다.

- `ExecStart`는 서버를 직접 부르지 않고 `limn run <이름>`을 거친다. `--git-pull`은 `GIT_PULL=1`일 때만, `LABEL`·`ACCENT`·`DOCS`는 값이 있을 때만 붙는 조건부 인자를 systemd가 표현하지 못하기 때문이다. `limn run`은 설정을 검증한 뒤 서버로 exec한다.
- `ConditionPathExists=<설정 폴더>/<이름>.env`: 설정이 없는 이름을 켜면 실패 반복 대신 여기서 멈춘다.
- `Environment=GIT_TERMINAL_PROMPT=0`과 `GIT_SSH_COMMAND=ssh -o BatchMode=yes`: 유닛 안에는 SSH 에이전트도 tty도 없으므로, 프롬프트를 기다리지 않고 바로 실패한다.
- `Environment=PYTHONUNBUFFERED=1`: 기동 로그(원고, 상태, 주소)가 곧바로 journal에 간다.
- `Restart=on-failure`, `RestartSec=3`, `NoNewPrivileges=true`, `WantedBy=default.target`.

`limn run`은 서버를 띄우기 전에 다음을 검사하고, 하나라도 어긋나면 멈춘다.

- `MANUSCRIPT` 폴더가 있다.
- `MAIN`과 `DOCS`가 함께 있지 않다.
- `MAIN` 파일이 있다.
- `PORT`가 1024–65535 안의 값이다. 비어 있어도 자동으로 고르지 않는다.
- `ACCENT`가 `#rrggbb` 형식이다.
- 접근 설정 키가 위 '접근 설정 키 (v0.2)' 표의 규칙을 지킨다. 예를 들어 loopback이 아닌 `BIND`에는 `AUTH=trusted-proxy`가 있고, `AGENT_LOOPBACK=1`은 `tailscale` 방식과 loopback `BIND`에서만 쓴다.

> **주의**
>
> 유닛 파일을 손으로 고치지 않는다. 다음 `start`나 `update`가 덮어쓴다. 같은 자리에 심링크가 있거나 `# limn:generated` 표시 줄이 없는 파일이 있으면, `limn`은 덮어쓰지 않고 손으로 확인하라며 멈춘다.

## 업데이트와 되돌리기

```bash
limn update --dry-run          # 무엇을 설치하고 재시작할지 보기만
limn update                    # 가장 최근 v* 태그를 설치하고 켜진 인스턴스를 재시작
limn update --ref v0.1.1       # 특정 태그·브랜치
limn update --from ~/src/limn  # 로컬 체크아웃(개발용)
```

`limn update`는 다음 순서로 돈다.

1. `--ref`가 없으면 원격에서 가장 높은 `v*` 태그를 읽는다.
2. `uv tool install --force git+https://github.com/dartworklabs/limn@<ref>`를 실행한다. `LIMN_REPO`로 원본을, `LIMN_UV`로 쓸 `uv`를 바꾼다. SSH로 받으려면 `LIMN_REPO=git+ssh://git@github.com/dartworklabs/limn`을 준다.
3. 유닛 템플릿을 다시 쓴다.
4. 켜진 `limn@*` 인스턴스를 모두 재시작하고 HTTP 200을 기다린다.

설치하는 동안 도는 서버는 그대로이고, 재시작할 때 새 판으로 바뀐다. **상태 폴더는 건드리지 않는다.**

옵션 규칙은 다음과 같다.

- `--ref`와 `--from`은 함께 쓰지 않는다.
- 이미 그 태그가 설치돼 있으면 다시 설치하지 않는다. `--force`를 주면 다시 설치한다.
- `--no-restart`를 주면 설치만 하고 인스턴스를 재시작하지 않는다.
- 설치가 실패하면 현재 판에 머문다.

되돌리기는 이전 태그를 다시 설치하는 것이다. `limn update --ref v<이전 판>`을 실행한다. 업데이트할 때마다 이 명령을 찍어 준다. 따로 두는 앱 사본은 더 없다. 설치된 태그가 곧 판이다.

## 끄기·제거

- `limn stop <이름>`은 유닛을 끄고 비활성화한다. 설정, 포트, serve 항목은 남는다. `limn start <이름>`으로 다시 켠다.
- `limn remove <이름>`은 유닛을 중지·비활성하고, tailscale serve를 해제하고, 설정을 삭제한다. 설정 삭제가 곧 포트 예약 해제다. serve 해제는 **그 포트가 이 인스턴스의 로컬 포트를 가리킬 때만** 한다. **상태 폴더는 지우지 않고** 경로만 알린다.

설정이 `LIMN_SOURCE_DIR`의 원본을 가리키는 링크면 `remove`는 링크와 원본을 함께 지운다. 둘 다 지워야 포트 장부에서도 빠지기 때문이다. 원본 쪽 삭제는 그 저장소에서 커밋하라고 알려 준다.

## 포트

- 설정 파일이 곧 예약이다. `limn add`는 다음 포트를 거부한다. 포트를 명시해도 같다.
  - 다른 인스턴스 설정이 쓰는 포트
  - 어느 주소에서든 LISTEN 중인 포트
  - `tailscale serve`가 이미 쓰는 포트
- 포트는 1024–65535 안이어야 하고, 로컬 포트와 테일넷 포트가 같으면 안 된다.
- 자동 배정은 테일넷 `18005–18099`(`LIMN_TS_MIN`/`LIMN_TS_MAX`)에서 첫 빈 포트를 고르고, 로컬 포트는 `+100`(`LIMN_LOCAL_OFFSET`)을 짝짓는다(18004 ↔ 18104). 어느 한쪽 번호만 봐도 짝을 알아볼 수 있게 하려는 것이다. 대역이 다 차면 `--port`/`--ts-port`로 직접 달라며 멈춘다.
- 기기 공용 포트 장부(선택): `~/.config/served/reserved-ports.txt`(`LIMN_LEDGER`)가 있으면 그 `<포트> <주인>` 줄도 피한다.
- `LIMN_LEDGER_GEN=<스크립트>`를 주면 `add`와 `remove`가 장부를 다시 만든다. 스크립트는 `<스크립트> <유닛 폴더> <설정 폴더>`로 불리고 `<포트> <주인>` 줄을 찍는다. 생성기가 없으면 장부를 읽기만 한다. 남의 파일을 반쯤 덮어쓰지 않으려는 것이다.

## 접근: 토큰과 멤버

v0.2부터 에이전트는 API 토큰으로 자신을 밝히고, 사람은 멤버 목록과 역할로 권한을 좁힐 수 있다. 두 가지 모두 `limn` 명령으로 다룬다.

```bash
limn token create paper2 [--name ci]     # 새 에이전트 토큰을 한 번만 찍는다(stdout). 저장되는 건 해시뿐
limn token list paper2                   # id·이름·만든 시각 — 토큰 자체는 절대 안 보인다
limn token revoke paper2 <id 또는 이름>  # 돌고 있는 서버가 다음 요청부터 거부한다
limn member add paper2 <로그인> [--role editor] [--name "<표시 이름>"]
limn member list paper2                  # 로그인·역할·이름·마지막 방문
limn member role paper2 <로그인> viewer
limn member remove paper2 <로그인>
```

두 명령 모두 인스턴스의 `STATE_DIR`에 있는 `tokens.json`과 `people.json`을 고친다. 인스턴스 없이 `limn serve`만 쓴다면 인스턴스 이름 대신 `--state-dir <폴더>`를 준다. 돌고 있는 서버는 다음 요청부터 바뀐 내용을 쓰므로 재시작이 필요 없다.

토큰은 에이전트에게 건넨다(예: `export LIMN_TOKEN=…`). 에이전트는 요청마다 `Authorization: Bearer $LIMN_TOKEN`을 보낸다. 토큰 원문은 만들 때 한 번만 보이고 해시만 저장되므로, 잃어버리면 폐기하고 새로 만든다. HTTP 쪽 계약은 [api.md](api.md) §인증에 있다.

| 역할 | 할 수 있는 일 |
| --- | --- |
| `owner` | editor가 하는 모든 일. 소유자 전용 작업(멤버·토큰·설정)은 v0.2에서 CLI와 파일 수준이다. 소유자 전용 HTTP 엔드포인트는 아직 없다 |
| `editor` | v0.1에서 사람이 하던 모든 일: 핀, 답글, 수정, 닫기, 확인, 다시 열기, 재빌드. **역할이 없는 사람은 editor다** |
| `viewer` | 읽기만 한다. `/api/pick`과 비교 빌드(`/api/revision-build`)는 된다. 그 밖의 변경은 모두 `403`이다 |
| `agent` | 에이전트 계약대로 claim, 답글, 검토 대기로 닫기를 한다. 확인(confirm)은 못 한다. 토큰으로 들어온 주체는 늘 이 역할이다 |

결정 근거는 [ADR-0002](../adr/0002-access-control.md)에 있다.

## 보안 규칙

이 규칙은 바꾸지 않는다. 근거와 서버 쪽 검사는 [operations.md](operations.md) §보안 제약에 있다.

> **핵심**
>
> 기본 정책(테일넷 인스턴스): `AUTH`가 없거나 `AUTH=tailscale`이고 허용 목록도 없으면, 인스턴스는 닿는 테일넷 사람 모두에게 열려 있고 누가 했는지만 기록한다.

처음 보는 테일넷 로그인도 들어올 수 있다. 그 사람은 첫 방문 때 `people.json`에 **`role` 필드 없이** 기록되고, 역할이 없으므로 editor다. v0.1과 똑같이 뷰어를 열고 핀·답글·닫기·확인을 할 수 있다. 지금 되는 일은 하나도 막히지 않는다. 역할과 허용 목록(`MEMBERS_ONLY=1`, `--allow`, `limn member`로 준 역할)은 켜야만 적용된다.

- 서버는 `BIND`가 없으면 `127.0.0.1`에 바인드한다. loopback이 아닌 `BIND`는 `AUTH=trusted-proxy`일 때만 받는다. `EXTRA_ARGS`에 `--i-know-this-is-insecure`가 있으면 큰 경고와 함께 뜬다. 테일넷 노출은 `tailscale serve --bg --https=<TS_PORT> http://127.0.0.1:<PORT>` 뿐이다.
- `tailscale serve`는 `tailscale` 방식에서만 쓴다. `add`와 `start`는 `AUTH=local`·`AUTH=trusted-proxy` 인스턴스에 serve를 거부한다. `AUTH=local`은 loopback 요청이 모두 소유자라서, serve로 열면 테일넷 사람 모두가 소유자가 된다. `AUTH=trusted-proxy`는 테일넷 사람이 프록시 헤더를 직접 보낼 수 있다. 이런 인스턴스는 `--no-serve`로 두고 자체 프록시 뒤에 둔다.
- 에이전트는 토큰으로 인증한다. "헤더 없는 loopback 요청 = 에이전트"라는 v0.1 규칙은 `tailscale` 방식에서 아직 되지만 폐지 예정이고, 서버 로그에 경고가 남는다. 에이전트가 토큰을 쓰게 되면 `AGENT_LOOPBACK=0`을 둔다.
- **funnel은 쓰지 않는다.** 미공개 원고이기 때문이다. `add`와 `start`는 serve 설정을 되읽어, 그 포트가 funnel이면 멈춘다.
- **sudo를 부르지 않는다.** tailscale operator 설정도 바꾸지 않는다. sudo 없이 serve를 걸려면 이 사용자가 tailscale operator여야 한다. 권한이 없어 serve가 안 걸리면 오류로 멈춘다.
- 남의 serve 항목을 덮거나 내리지 않는다. `serve reset`은 기기 전체 설정이라 쓰지 않는다.

## 환경 변수

| 변수 | 기본값 | 뜻 |
| --- | --- | --- |
| `LIMN_CONFIG_DIR` | `$XDG_CONFIG_HOME/limn` | 인스턴스 설정 |
| `LIMN_DATA_ROOT` | `$XDG_DATA_HOME/limn` | 상태 폴더 기본 위치 |
| `LIMN_SOURCE_DIR` | = 설정 폴더 | `add`가 설정 원본을 쓰는 곳(설정 폴더에 링크) |
| `LIMN_USER_UNIT_DIR` | `$XDG_CONFIG_HOME/systemd/user` | 유닛 템플릿을 쓰는 곳 |
| `LIMN_UNIT_PATH` | `pdflatex` 폴더 + `/usr/local/bin:/usr/bin:/bin` | 유닛 안의 `PATH` |
| `LIMN_LEDGER`, `LIMN_LEDGER_GEN` | 위 '포트' 절 참고 | 포트 장부(선택) |
| `LIMN_TS_MIN`, `LIMN_TS_MAX`, `LIMN_LOCAL_OFFSET` | `18005`, `18099`, `100` | 자동 배정 대역 |
| `LIMN_REPO`, `LIMN_UV` | `git+https://github.com/dartworklabs/limn`, `uv` | `limn update`가 설치할 원본과 쓸 `uv`. SSH로 받으려면 `LIMN_REPO`에 `git+ssh://git@github.com/dartworklabs/limn`을 준다 |
| `LIMN_WAIT` | `240` | 기동·재시작 뒤 HTTP 200을 기다리는 초 |

`XDG_CONFIG_HOME`이 없으면 `~/.config`, `XDG_DATA_HOME`이 없으면 `~/.local/share`를 쓴다.

## 예전 설치에서 옮겨 오기

예전 이름으로 설치해 쓰던 환경에서 옮겨 오는 경우는 [README](../../README.ko.md)의 '출처와 이전' 절과 `limn migrate --help`를 본다.
