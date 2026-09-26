# 운영 — 서버 하나 띄우기, 보안, 배포, 뷰어

이 문서는 연구실 머신에서 Limn 서버를 띄우고 테일넷에 노출하고 상시로 돌리는 운영자가 읽는다. 실행 인자 전체, 접근 제어(신원 방식·토큰·역할), 포트 충돌 회피, 보안 제약, `tailscale serve`, systemd 사용자 유닛, 상태 파일 배치, 사용자용 뷰어 사용법을 다룬다. 서버 CLI 플래그, 인스턴스 설정 키, 유닛 템플릿, 상태 파일 배치 가운데 하나라도 바뀌면 이 문서를 같은 변경에서 고친다.

원고마다 상시 인스턴스를 두고 관리하는 절차(`limn add` 등)는 [instances.md](instances.md)가 맡는다. 이 문서는 그 인스턴스 안에서 도는 서버 프로세스 하나의 계약이다.

> **한눈에**
>
> 먼저 요구 환경과 실행 인자를 보고, 여러 문서와 포트 충돌 회피로 서버를 올린다. 누가 들어오고 무엇을 바꿀 수 있는지는 실행 인자 절 아래 '접근 제어 인자' 소절이 정한다. 여러 원고를 동시에 띄우면 동시 실행 절을 본다. 노출 전에는 보안 제약, Host·Origin 검사, `tailscale serve` 실측 절을 읽는다. 상시 운영은 systemd 절과 상태 파일 배치 절, 사용자 안내는 마지막 뷰어 사용법 절이다.

## 요구 환경

서버는 Python 3.10 이상의 표준 라이브러리만 쓴다. 외부 패키지, CDN, 빌드 단계가 없다. 뷰어가 PDF를 벡터로 그릴 때 쓰는 PDF.js는 패키지 안 `src/limn/vendor/pdfjs/`에 담겨 기본으로 제공된다. 그래서 가상환경 없이 시스템 Python 3.10으로도 돈다. 3.10은 하한이다. 3.9 이하는 `server.py`의 `match` 문을 읽지 못해 시작하자마자 `SyntaxError`로 멈춘다. macOS의 `/usr/bin/python3`이 3.9다.

재빌드에는 외부 도구가 필요하다.

- `latexmk`
- `synctex`
- `pdftoppm`
- `pdftotext`
- `rsync` (있으면 쓴다)

회귀 테스트는 포트를 열지 않고 socketpair로 돈다. 저장소 루트에서 다음처럼 실행한다.

```bash
uv run python3 -m unittest discover -s tests
```

## 실행 인자

```bash
limn serve \
  --manuscript <manuscript_dir> \
  [--main <main-file>.tex] \
  [--port <port>] \
  [--state-dir <state_dir>] \
  [--dpi 150] \
  [--float-envs figure,table,algorithm,equation,align,itemize,enumerate,minipage] \
  [--build-timeout 900] \
  [--no-build] \
  [--allow <login>,<login>] \
  [--no-origin-check] \
  [--git-pull] \
  [--pdfjs-dir <dir>] \
  [--label <이름표>] \
  [--accent <#rrggbb>] \
  [--doc <키>=<표시 이름>:<경로> ...] \
  [--auth tailscale|local|trusted-proxy] [--no-agent-loopback | --agent-loopback] [--tailnet-agent] \
  [--bind <주소>] [--i-know-this-is-insecure] [--public-host <이름[:포트]>,...] \
  [--trusted-proxies <ip/cidr>,...] [--proxy-user-header <h>] [--proxy-name-header <h>] [--proxy-email-header <h>] \
  [--members-only] [--local-user <로그인>] \
  [--version]
```

실행 인자의 정본은 [`src/limn/server.py`](../../src/limn/server.py)의 `main` 함수 안 argparse 정의다.

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `--manuscript` | 예 | — | LaTeX 소스 루트 디렉토리(`<manuscript_dir>`). 프로젝트마다 다르므로 하드코딩하지 않는다. 핀이 가리킬 수 있는 파일은 이 트리 안으로 제한된다 |
| `--main` | 아니오 | 자동 탐지 | 빌드할 최상위 `.tex` 파일명. 생략하면 `--manuscript` 안에서 `\documentclass`를 포함한 `.tex` 파일을 찾는다. 후보가 0개나 2개 이상이면 후보 목록을 출력하고 에러로 끝난다. 추측하지 않는다. `--doc`과 함께 쓰면 기동에 실패한다 |
| `--doc` | 아니오 | 없음(= 단일 문서) | 뷰어에서 고를 문서. 여러 번 줄 수 있고 첫 문서가 기본이다. 형식과 규칙은 아래 '여러 문서' 절 |
| `--port` | 아니오 | 자동 선택 | 생략하면 `127.0.0.1`의 18300–18399에서 비어 있는 첫 포트를 골라 쓰고, 고른 포트를 기동 로그에 출력한다. 그 대역이 다 차 있으면 `--port`를 달라며 멈춘다. 절차는 아래 '포트 충돌 회피' 절 |
| `--state-dir` | 아니오 | `${XDG_DATA_HOME:-~/.local/share}/limn/serve/<slug>` | `<slug>`는 `<원고 폴더 이름>-<원고 절대경로의 SHA-1 앞 8자>`다. 같은 머신에서 원고 A와 B를 동시에 열어도 상태가 섞이지 않게 하려는 것이다(여러 원고·여러 worktree에 안전). 상시(systemd) 인스턴스는 `limn add`가 대신 `~/.local/share/limn/<이름>`을 기본으로 쓴다([instances.md](instances.md)) |
| `--dpi` | 아니오 | `150` | 페이지 PNG 렌더 해상도. 뷰어는 PDF를 벡터로 그리므로(아래 '뷰어 사용법' 절) PNG는 첫 화면과 폴백에만 쓴다 |
| `--float-envs` | 아니오 | `figure,table,algorithm,equation,align,itemize,enumerate,minipage` | 기본 범위 단계를 '환경'으로 둘 `\begin{...}` 이름 목록. 범위 사다리 자체는 모든 환경을 본다([domain.md](domain.md) §범위 사다리) |
| `--build-timeout` | 아니오 | `900` | `latexmk` 빌드 타임아웃(초). 넘으면 프로세스 그룹째 종료하고 `fail`로 판정한다 |
| `--no-build` | 아니오 | 꺼짐 | 기동 때 재빌드를 건너뛴다. 산출물이 이미 있을 때 서버만 빨리 올리는 용도다. PDF나 쪽 이미지가 없으면 이 플래그와 무관하게 빌드한다 |
| `--allow` | 아니오 | 비움(= 전원 허용) | 허용할 tailscale 로그인 목록(쉼표 구분). 자세한 규칙은 표 아래 설명 |
| `--no-origin-check` | 아니오 | 꺼짐 | `Host`·`Origin` 검사(DNS rebinding·CSRF 방어, 아래 'Host·Origin 검사' 절)를 끈다. 탈출구 전용이다. 켜면 기동 로그에 경고가 찍힌다 |
| `--git-pull` | 아니오 | 꺼짐 | 기동 직후와 60초마다 원격 main을 확인해 fast-forward하고, 새 커밋이면 LaTeX PDF를 다시 빌드한다. 수동 재빌드도 복사 전에 업스트림을 `--ff-only`로 pull한다. 자세한 규칙은 [build-sync.md](build-sync.md) §재빌드 전 원격 main 당겨오기 (`--git-pull`) |
| `--pdfjs-dir` | 아니오 | 패키지 내장 `src/limn/vendor/pdfjs/` | 뷰어가 벡터로 그릴 때 받는 PDF.js 디렉토리(`pdf.min.mjs`·`pdf.worker.min.mjs`)를 다른 경로로 바꿀 때만 쓴다. 지정한 경로에 파일이 없으면 기동 로그에 경고가 찍히고 뷰어는 PNG로 보인다. 그 밖의 동작은 같다 |
| `--label` | 아니오 | `--manuscript`의 git origin 저장소 이름. git 저장소가 아니면 폴더 이름 | 여러 논문 뷰어를 동시에 열었을 때 구분할 이름표. 기본 이름표는 40자를 넘으면 잘라 `…`를 붙인다. 직접 줄 때는 40자 이하여야 하고, 넘으면 기동에 실패한다. HTML 이스케이프된다. 쓰이는 자리는 아래 '`--label`·`--accent`' 절 |
| `--accent` | 아니오 | 이름표 문자열의 해시로 고른 고정 팔레트 색 | 이름표의 강조색. `#rrggbb` 형식만 받고, 형식이 아니면 기동에 실패한다. 직접 지정하지 않으면 같은 `--label`은 항상 같은 기본색이 된다 |
| `--version` | 아니오 | — | 설치된 버전을 출력하고 끝난다. `GET /api/version`과 같은 값이다 |

`--allow`를 지정하면 `Tailscale-User-Login` 헤더가 **있는데** 목록 밖인 요청은 `403`을 받는다. 신원 헤더 없이 루프백 `Host`로 온 요청(에이전트의 `curl`)은 목록과 무관하게 허용된다. 단 v0.2부터 이 요청이 들어오는 것은 loopback 에이전트가 켜져 있을 때뿐이다(아래 '접근 제어 인자' 소절). 토큰을 단 요청은 목록을 거치지 않는다. 신원 헤더 없이 `*.ts.net` `Host`로 온 요청은 `403`이다. tailscale은 **태그 장치**와 funnel 요청에는 신원 헤더를 붙이지 않는다. 이런 요청을 로컬로 치면 목록을 우회할 수 있어서 막는다. `--members-only`를 켰을 때도 같은 이유로 막는다. 0.2.1부터는 `--allow`와 `--members-only`를 모두 비워도 이런 요청은 `403`이다. 0.2.0은 이때 태그 장치 요청을 `로컬/에이전트`로 받았다. `--tailnet-agent`로 그 동작을 되살릴 수 있지만 목록이 있으면 여전히 막힌다.

`--no-origin-check`는 실제 `tailscale serve`가 예상 밖의 `Host`나 `Origin`을 넘겨 UI 요청이 전부 `403`일 때만 쓴다. MagicDNS 짧은 이름이나 `*.ts.net`이 아닌 사용자 도메인이 그런 경우다.

`--git-pull`의 자동 동기화가 더러운 작업 트리, 분기, 업스트림 없음 같은 이유로 막히면 뷰어 화면에 사유를 표시한다.

### 접근 제어 인자 (v0.2)

Limn 0.2.0부터 서버는 요청한 사람이 누구인지 가리는 방법을 인스턴스마다 하나 고른다. 이 방법을 **신원 방식**이라 부른다. 에이전트는 API 토큰으로 자신을 밝히고, 사람은 멤버 목록과 역할로 들어올 수 있는 범위와 바꿀 수 있는 일을 좁힌다. 아래 인자를 하나도 주지 않으면 서버는 v0.1과 똑같이 동작한다. 결정 근거는 [ADR-0002](../adr/0002-access-control.md)에 있고, 실행 정본은 [`src/limn/server.py`](../../src/limn/server.py)의 argparse 정의와 `configure_access`·`identify`·`admit`·`check_role` 함수다.

| 인자 | 기본값 | 설명 |
| --- | --- | --- |
| `--auth` | `tailscale` | 신원 방식. `tailscale`·`local`·`trusted-proxy` 가운데 하나다. 방식별 동작은 바로 아래 표 |
| `--no-agent-loopback` / `--agent-loopback` | `tailscale`에서 켜짐 | 신원 헤더도 토큰도 없는 loopback 요청을 에이전트(`로컬/에이전트`)로 볼지 정한다. 폐지 예정인 v0.1 동작이라 서버가 시작 때와 첫 요청 때 경고를 남긴다. `--no-agent-loopback`이면 끄고 그런 요청은 `401`이다. `local`·`trusted-proxy`·loopback이 아닌 `--bind`에서는 늘 꺼져 있고, 거기서 `--agent-loopback`을 주면 시작을 거부한다. 이 기기를 부른 요청(루프백 `Host`)에만 해당한다 |
| `--tailnet-agent` | 끔 | `tailscale serve`를 거쳐 온 신원 헤더 **없는** 요청(`Host`가 `*.ts.net`이나 `--public-host`, 예: 태그 장치)도 에이전트로 본다. 0.2.0 동작이다. 끄면(기본, 0.2.1부터) 그런 요청은 토큰을 쓰라는 안내와 함께 `403`이다. 켜 두면 신원 없이 테일넷 주소에 닿는 누구나(태그 장치, 공용 CI 노드) 핀을 바꿀 수 있다. loopback 에이전트가 켜져 있어야 하고, `--no-agent-loopback`·`--auth local`·`--auth trusted-proxy`·loopback이 아닌 `--bind`와 함께 주면 시작을 거부한다. 기동 로그에 폐지 예정 경고가 남는다. 인스턴스 설정 키는 `TAILNET_AGENT=1`이다 |
| `--bind` | `127.0.0.1` | 들을 주소(IPv4·IPv6·`localhost`). loopback이 아니면 `--auth trusted-proxy`나 `--i-know-this-is-insecure` 없이는 시작을 거부한다. loopback이 아닌 바인드는 신원 방식을 밝힌 `warning` 줄을 기동 로그에 찍는다 |
| `--i-know-this-is-insecure` | 꺼짐 | `tailscale`·`local`인데도 loopback이 아닌 `--bind`로 띄운다. 큰 경고가 찍힌다. 완전히 믿는 망에서만 쓴다 |
| `--public-host` | 없음 | 인스턴스에 닿는 공개 호스트 이름 `이름[:포트]`. 여러 번 주거나 쉼표로 잇는다. 이 이름을 `Host`로, 같은 출처의 `Origin`(`https`, 포트를 안 주면 443)으로 받는다. `GET /pins.md`의 기준 주소로도 쓴다 |
| `--trusted-proxies` | `127.0.0.1,::1` | `trusted-proxy` 방식이 신원 헤더를 믿는 요청 상대의 IP·CIDR 목록(쉼표) |
| `--proxy-user-header` / `--proxy-name-header` / `--proxy-email-header` | `X-Forwarded-User` / `X-Forwarded-Preferred-Username` / 없음 | `trusted-proxy` 방식이 읽는 헤더 이름. 사용자 헤더는 필수다. 이메일 헤더를 주면 값이 있을 때 이메일이 로그인이 된다 |
| `--members-only` | 꺼짐 | `people.json`(`limn member add`)이나 `--allow`에 있는 사람만 들인다. 나머지는 `403`이고 `people.json`에 기록하지 않는다. 토큰과 로컬 소유자는 늘 들어온다 |
| `--local-user` | `$USER`, 없으면 `owner` | `--auth local`에서 소유자의 로그인 |
| `--agent-token-file` | `$LIMN_AGENT_TOKEN_FILE`, 없으면 없음 | 0.3.3. 이 머신의 에이전트가 이 인스턴스의 토큰을 두는 파일. `limn run`이 `<설정 폴더>/<이름>.token`을 환경 변수로 넘긴다. 서버는 **읽지 않고** 있는지만 본다. 파일이 있으면 `pins.md` 인증 안내 줄과, 헤더 없는 loopback 에이전트가 꺼졌을 때 이 기기의 헤더 없는 요청이 받는 `401` 메시지가 그 파일을 쓰라고 알려 준다([api.md](api.md) §인증, [ADR-0007](../adr/0007-agent-token-file.md)). 기동 로그의 `auth` 줄에 경로와 `present`·`absent`가 찍힌다 |

세 신원 방식은 신원을 읽는 곳과 그 밖의 요청을 다루는 방식이 다르다.

| 방식 | 신원을 읽는 곳 | 신원이 없는 요청 |
| --- | --- | --- |
| `tailscale` | `Tailscale-User-*` 헤더. TCP 상대가 loopback일 때만 믿는다. `tailscale serve`가 loopback에서 붙기 때문이다 | loopback 에이전트가 켜져 있으면 헤더 없는 loopback 요청은 에이전트다. 그 밖은 `401` |
| `local` | 자기 머신을 쓰는 한 사람. loopback 요청은 모두 소유자이고, 사람이므로 확인(confirm)도 할 수 있다. Tailscale 헤더는 무시한다 | loopback이 아닌 상대는 `401`. 에이전트는 토큰을 써야 한다 |
| `trusted-proxy` | `--proxy-*-header` 헤더. 요청이 `--trusted-proxies`에서 왔을 때만 믿는다 | 유효한 토큰이 없으면 `401` |

어느 방식이든 `Authorization: Bearer <토큰>`을 받는다. 토큰은 `limn token create`로 만든다. 유효한 토큰은 신원 헤더보다 앞선다. 틀리거나 폐기된 토큰은 다른 신원으로 넘어가지 않고 곧바로 `401`이다.

> **핵심**
>
> 바인딩 기본값은 `127.0.0.1`이다. loopback이 아닌 `--bind`(예: `0.0.0.0`)는 인증 리버스 프록시 뒤에서 `--auth trusted-proxy`로 띄울 때만 받는다. 그 밖에는 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수 있지만 크게 경고한다. 근거는 아래 '보안 제약' 절이다.

기동 로그에는 `auth` 줄이 찍힌다. 신원 방식, 토큰 수, loopback 에이전트 켬·끔, (loopback 에이전트가 켜져 있으면) tailnet 에이전트 켬·끔, members-only 여부가 이 한 줄에 모인다.

역할은 `people.json`에 사람마다 적는다. 역할별로 할 수 있는 일은 다음과 같다.

- `viewer`: 읽기와 `/api/pick`·`/api/revision-build`만 한다.
- `agent`: 확인(confirm)과 전체 지우기(`/api/clear`)를 빼고 전부 한다. 토큰으로 들어온 주체는 늘 이 역할이다.
- `editor`: 전체 지우기를 빼고 전부 한다. 역할이 적히지 않은 사람의 기본값이다.
- `owner`: 전부 한다.

소유자 전용 HTTP 엔드포인트는 `POST /api/clear`(0.2.1부터, 확인 본문 필요)와 휴지통의 영구 삭제 `POST /api/pins/{id}/purge`(0.2.2부터) 둘이다. 나머지 소유자 작업(멤버·토큰·설정)은 CLI와 파일 수준이다(`limn member`, `limn token`). 명령과 역할 표는 [instances.md](instances.md) §접근: 토큰과 멤버, HTTP 쪽 계약은 [api.md](api.md) §인증에 있다.

### 설계 초안과의 차이

설계 초안에는 세 플래그가 따로 있었다.

- `--allow-host HOST`(여러 번 가능): `*.ts.net` 외의 도메인을 하나씩 허용한다.
- `--no-host-check`: `Host`/`Origin` 검사를 따로 끈다.
- `--log-headers`: 요청 헤더를 로깅한다.

실제 구현은 이 세 개를 만들지 않았다. 대신 위의 `--allow`(로그인 기반 허용 목록)와 `--no-origin-check`(Host·Origin 검사를 한 번에 끔)로 갈음했다. 허용 호스트 집합은 하드코딩된 `127.0.0.1`·`localhost`·`::1`·`*.ts.net`이고, v0.2부터 `--public-host`로 준 이름이 여기에 더해진다. 커스텀 도메인을 하나씩 허용하려던 `--allow-host`의 일을 `--public-host`가 맡는다.

## 여러 문서 (`--doc`)

논문 저장소 하나에 문서가 여럿일 수 있다. 본문, 답변서, 커버레터, 하이라이트, 보기 전용 리뷰어 코멘트 PDF가 그런 예다. 이때 뷰어 하나와 주소 하나로 띄우고 문서를 골라 본다. 데스크톱은 PDF 영역 위 선택기를 쓰고, 좁은 모바일 화면은 기존 도구 줄의 문서 버튼을 쓴다. 설계와 근거는 [domain.md](domain.md) §여러 문서다.

> **예시**
>
> 두 번째 논문 저장소(이름표 DEMO-B)의 실제 문서 목록이다.
>
> ```bash
> limn serve \
>   --manuscript <저장소 루트> --state-dir <state_dir> --port <port> --git-pull --label DEMO-B \
>   --doc 'ms=본문:manuscript::2nd/2nd_manuscript_en.tex' \
>   --doc 'rr=답변서:submission/review_response/review_response.tex' \
>   --doc 'cl=커버레터:submission/cover_letter/cover_letter.tex' \
>   --doc 'hl=하이라이트:submission/highlights/highlights.tex' \
>   --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf'
> ```
>
> 본문은 `\graphicspath{{./images/}{../1st/images/}}`로 옆 폴더의 그림을 읽는다. 그래서 빌드 루트를 `manuscript/`로 넓히고(`::`) 빌드는 `2nd/`에서 돈다. 나머지 문서는 `.tex`가 있는 폴더 하나로 충분하다.
>
> 2026-09-23에 이 구성의 머신에서 TeX Live 2025로 네 LaTeX 문서가 모두 오류 0으로 빌드됐다. 본문 43쪽은 24초, 답변서 111쪽은 44초, 커버레터 1쪽은 4초가 걸렸고, 제출본 PDF 27쪽은 그리는 데 10초가 걸렸다.

| 항목 | 규칙 |
| --- | --- |
| 형식 | `<키>=<표시 이름>:<경로>`. 첫 `=` 앞이 키, 그 뒤 첫 `:` 앞이 이름, 나머지가 경로 |
| 키 | `[a-z0-9-]{1,24}`, 중복 금지. URL 해시(`#doc=<키>`), API(`doc=<키>`), pins.md 소절에 쓰인다. 핀 레코드에 남으므로 **한 번 정한 키는 바꾸지 않는다** |
| 이름 | 탭, 목록, pins.md 소절 머리에 보인다. 40자 이하, `:` 없이 |
| 경로 | `--manuscript` 기준 상대(권장) 또는 절대. 어느 쪽이든 `--manuscript` 안이어야 한다. 밖이면 기동에 실패한다. 핀이 가리킬 수 있는 파일은 원고 트리 안뿐이기 때문이다 |
| `x/main.tex` | LaTeX 문서. 빌드 루트(사본으로 복사하는 범위)는 `x/`, 빌드도 `x/`에서 돈다 |
| `root::sub/main.tex` | LaTeX 문서. 빌드 루트는 `root/`, 메인은 `root/sub/main.tex`, 빌드는 `root/sub/`에서 돈다. 메인이 `../`로 빌드 루트 안의 다른 폴더를 읽을 때 쓴다. `::`는 한 번만 쓰고, 메인은 빌드 루트 안에 있어야 한다 |
| `x/file.pdf` | 보기 전용. 재빌드가 없고, 파일이 바뀌면(3초마다 확인) 쪽을 다시 그린다. 핀은 쪽과 영역으로 찍는다 |
| 개수 | 12개까지. Alt+1…9는 앞의 아홉 개에 대응한다 |
| `--doc` 없음 | 예전 그대로 `--manuscript`·`--main`의 문서 하나(키 `main`)를 띄운다. 상태 폴더 배치도 그대로다(아래 '상태 파일 배치' 절) |
| 기동 빌드 | 여러 문서면 문서마다 백그라운드로 빌드하고 서버는 바로 뜬다. 한 문서가 실패해도 기동은 계속되고, 그 탭이 오류 패널을 보여 준다. `--no-build`는 쪽이 이미 있는 문서만 건너뛴다 |
| `--git-pull` | 저장소 단위로 한 번 돈다. 두 문서를 동시에 재빌드해도 fetch·merge는 한 번이고, 다른 쪽은 그 결과(`pull.shared: true`)를 쓴다 |

### 단일 문서 인스턴스에 문서를 더할 때

본문을 첫 번째 `--doc main=<이름>:<본문 경로>`로 둔다. 키가 `main`인 LaTeX 문서는 상태 폴더 루트(옛 자리)를 그대로 쓴다. 그래서 빌드 이력과 쪽 이미지가 이어지고, `doc` 필드가 없는 옛 핀도 첫 문서(= 본문)로 읽힌다.

> **주의**
>
> 본문에 `main`이 아닌 키를 주면 본문이 `docs/<키>/`에서 새로 빌드된다. 이때 옛 핀의 마크는 한 번 점선(추정)이 된다.

### 인스턴스 관리자와의 계약

여러 논문을 상시로 띄우고 관리할 때는 이 문서가 아니라 **인스턴스 관리자**를 쓴다. 인스턴스 관리자는 `limn add|start|stop|update|list|status|url|snippet|doc|remove` 명령과 systemd 사용자 유닛 `limn@<이름>`으로 이루어지며, 포트·상태 디렉토리·유닛 배선을 자동으로 맞춘다.

다음 내용의 정본은 [instances.md](instances.md)다.

- 논문별 설정 키(`MANUSCRIPT`·`MAIN`·`DOCS`·`PORT`·`STATE_DIR`·`LABEL`·`ACCENT`·`GIT_PULL`·`EXTRA_ARGS`, 파일 `~/.config/limn/<이름>.env`)
- 접근 설정 키(`AUTH`·`AGENT_LOOPBACK`·`TAILNET_AGENT`·`BIND`·`PUBLIC_HOSTS`·`TRUSTED_PROXIES`·`PROXY_*_HEADER`·`MEMBERS_ONLY`·`LOCAL_USER`)
- 서버 머신 에이전트의 토큰 파일(`~/.config/limn/<이름>.token`, `limn token create <이름> --save`)과 `limn run`이 넘기는 `LIMN_AGENT_TOKEN_FILE`
- 설정 키와 서버 인자의 대응
- 새 논문 추가·업데이트·제거 절차

서버 쪽 `--doc`/`--main` 인자 자체의 계약(형식, 키 규칙, 경로 규칙)은 위 표가 정본이며 인스턴스 관리자를 써도 바뀌지 않는다.

## 포트 충돌 회피 (강제)

포트에 바인딩하기 전에 그 포트를 쓰는 프로세스가 있는지 먼저 확인한다. 확인 없이 바로 바인딩을 시도하지 않는다.

```bash
ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
```

포트가 점유돼 있으면 둘 중 하나를 한다.

1. `--port`를 지정하지 않았다면 서버가 자동으로 다음 빈 포트를 고르게 둔다.
2. 점유 프로세스가 이 도구의 이전 인스턴스인지 확인하고 재사용한다. 같은 `--manuscript`면 기존 서버를 그대로 쓰고 새로 띄우지 않는다.

> **주의**
>
> 서버를 내릴 때 `pkill -f "limn serve"`로 죽이지 않는다. 이 패턴은 자기 자신의 명령줄까지 매칭해 무관한 세션을 죽일 수 있다. 포트로 PID를 찾아 종료한다.
>
> ```bash
> pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid
> ```

## 설치와 버전 교체

`limn`은 `uv tool install git+https://github.com/dartworklabs/limn@v0.2.2`처럼 설치해 쓰는 독립 패키지다. 레포를 체크아웃해 스크립트를 직접 실행하지 않는다. `vendor/pdfjs/`는 패키지 안에 같이 설치되므로 옆에 따로 둘 필요가 없다.

새 버전으로 올리려면 그 버전을 다시 설치하고 상시 인스턴스를 재시작한다. `limn update`가 이 두 단계를 한 번에 한다([instances.md](instances.md) §업데이트와 되돌리기).

> **주의**
>
> 레포만 새로 받고 설치를 갱신하지 않으면 옛 버전이 계속 돈다.

버전을 바꿀 때 상태 디렉토리는 그대로 둔다. 새 버전은 옛 배치(`pages/`, `pins.jsonl`, `built_at.txt`, `head.txt`)를 `--no-build`로도 재빌드 없이 읽는다. 기동 때 다음 일이 일어난다.

1. `pages.cur`(내용 `pages`)를 만든다.
2. `pins.seq`를 기존 최대 id로 만든다.
3. `<state_dir>/pins.md`를 다시 그린다.

옛 `pages/`는 다음 재빌드가 `pages-<build_id>/`로 교체한다. 교체된 뒤에는 직전 1개로 남았다가 그다음 재빌드에서 지워진다.

## 여러 논문 인스턴스를 동시에 띄울 때

논문마다 인스턴스가 따로 도는 것이 전제다. 논문마다 저장소, 포트, 테일넷 주소가 다르다. 서버 프로세스 하나는 `--manuscript` 하나만 다루므로, 논문 N개를 동시에 보려면 프로세스도 N개다.

### 동시 실행 조건 — 겹치면 안 되는 세 가지

| 자원 | 규칙 |
| --- | --- |
| 포트 | 인스턴스마다 다른 `--port`를 쓴다. 비우면 자동 배정된다(위 '포트 충돌 회피' 절). 같은 포트를 두 인스턴스가 쓸 수 없다 |
| 상태 디렉토리(`--state-dir`) | 인스턴스마다 다른 경로를 쓴다. 기본값의 `<slug>`는 원고 경로에서 나오므로 `--manuscript`가 다르면 자동으로 갈린다. 같은 원고를 다른 브랜치나 worktree로 두 번 열면 슬러그가 같아져 핀이 섞인다. 그때는 `--state-dir`을 명시해 분리한다 |
| 빌드 폴더(`<state_dir>/build/`) | `--state-dir`을 분리하면 자동으로 따라 갈린다. `latexmk` 두 개가 같은 `build/`를 밟으면 서로의 `.aux`를 덮어쓴다([build-sync.md](build-sync.md) §재빌드 (동기)) |

`limn add <이름> --manuscript <dir>`(인스턴스 관리자, [instances.md](instances.md))를 쓰면 포트와 상태 디렉토리를 논문별로 자동 분리한다. 위 표는 `limn serve`를 직접 띄울 때만 손으로 맞춘다.

### `--label`·`--accent` — 탭을 헷갈리지 않게

인스턴스가 여러 개 뜨면 화면이 똑같아 탭을 헷갈리기 쉽다. 그래서 두 값이 화면 여러 자리에 나타난다.

- `--label`: 이름표. 기본은 `--manuscript`의 git origin 저장소 이름이고, 없으면 폴더 이름이다.
- `--accent`: 강조색 `#rrggbb`. 기본은 이름표 해시로 고른 고정 팔레트 색이다. 같은 이름표는 항상 같은 색이 된다.

| 자리 | 무엇이 보이나 |
| --- | --- |
| 도구 줄(데스크톱 사이드바 머리, 펼친·접은 폴드 공통 `#bar1`) | 맨 앞에 강조색 배경의 이름표 칩. 좁은 화면에서는 폭이 줄지만 사라지지 않는다 |
| 화면 맨 위 | 강조색 얇은 띠(4px) |
| 브라우저 탭 제목 | `<이름표> · 원고 핀 · 열린 N` |
| 파비콘 | 강조색 원 안에 이름표 첫 글자 |
| `GET /api/meta` | `label`·`accent`·`repo`(git origin URL, 없으면 `null`) 필드 |
| `<state_dir>/pins.md` 머리(디스크와 `GET /pins.md` 둘 다) | `원고:` 줄 다음에 `논문: <이름표> · 저장소: <repo 또는 (없음)>` 한 줄. `저장소`가 있으면 안내 문단에 "처리 전 `git remote get-url origin` 확인, 다르면 멈춘다"가 붙는다. 다른 논문의 핀을 잘못 처리하는 사고를 막기 위해서다 |

기본 이름표는 40자에서 잘리고, 직접 준 `--label`이 40자를 넘으면 기동을 멈춘다. 둘 다 HTML 이스케이프한다. `--accent`는 `#` 뒤 6자리 16진수만 받고, 그 외 형식이면 기동을 멈춘다.

## 보안 제약

Limn은 미공개 원고와 공저자의 메모를 다룬다. 그래서 기본은 노출 범위를 테일넷 안으로 묶고, 테일넷 자체를 인증 경계로 쓴다. v0.2부터는 인증 리버스 프록시 뒤에 두는 길(`--auth trusted-proxy`)이 하나 더 있다. 아래 규칙 가운데 바인딩 주소 규칙만 `--i-know-this-is-insecure`로 넘길 수 있고, 나머지는 실행 인자로도 풀 수 없다.

| 항목 | 규칙 |
| --- | --- |
| 바인딩 주소 | 기본 `127.0.0.1`. loopback이 아닌 `--bind`(예: `0.0.0.0`)는 인증 프록시 뒤의 `--auth trusted-proxy`일 때만 받는다. 아니면 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수 있지만 크게 경고한다 |
| 외부 노출 | `tailscale serve`(`tailscale` 방식)나 인증 리버스 프록시(`--auth trusted-proxy`)를 쓴다. **`tailscale funnel`은 금지**다. funnel은 공인 인터넷에 노출한다 |
| 노출 후 검증 | 두 가지를 확인해야 "노출됐다"고 보고한다. (1) 테일넷 안에서 그 URL에 `curl`하면 `200`이다. (2) 공인 IP나 테일넷 밖 경로로는 연결이 실패한다. 즉 `tailscale serve status`가 "Funnel"이 아니라 "tailnet only"로 뜬다 |
| 인증 | 인스턴스마다 신원 방식 하나(`--auth`). 기본 `tailscale`은 테일넷이 경계이고 헤더로 누가 했는지 기록한다. 에이전트는 API 토큰(`limn token create`)을 쓴다. 서버 머신의 에이전트는 토큰 파일(`limn token create <이름> --save`)을 쓰고, 그 뒤 인스턴스마다 `AGENT_LOOPBACK=0`을 둔다([instances.md](instances.md) §서버 머신의 에이전트: 토큰 파일). 들어올 사람은 `--allow`·`--members-only`로, 바꿀 수 있는 일은 역할(`limn member`)로 좁힌다 |
| 요청 경계 | 응답 전에 본문을 끝까지 읽고 오류 뒤에는 연결을 닫는다(요청 밀반입 차단). `Transfer-Encoding`은 거부한다. 교차 출처 `Origin`과 낯선 `Host`는 `403`이다. 본문 있는 POST는 JSON만 받는다. 상세는 [api.md](api.md) §요청 형식과 경계와 아래 'Host·Origin 검사' 절 |
| 경로 | 핀과 스니펫이 가리킬 수 있는 파일은 `--manuscript` 트리 안뿐이다. 밖이면 `400`이다 |
| 종료 | 세션을 끝낼 때 `tailscale serve --https=<port> off` 등으로 노출을 내린다. 서버 프로세스를 계속 띄워 둘지는 사용자가 판단한다. 재사용 이점과 유휴 자원 비용의 트레이드오프다 |

보안 제보 절차와 지원 범위는 [SECURITY.md](../../SECURITY.md)에 있다.

## Host·Origin 검사

이 검사는 두 공격을 막는다. 하나는 다른 사이트가 사용자 브라우저를 통해 요청을 보내는 교차 출처 요청(CSRF)이다. 다른 하나는 공격자 도메인이 `127.0.0.1`을 가리키게 바꿔 로컬 서버를 읽는 DNS rebinding이다.

### 교차 출처 요청

`Origin`이 있으면 **Host 종류에 따라** 검사를 가른다. 조건을 못 맞추면 `403`이다.

| Host | Origin 조건 |
| --- | --- |
| 루프백 | Origin도 루프백 이름(`127.0.0.1`·`localhost`·`::1`)이어야 한다. **포트는 보지 않는다** |
| 루프백 | `*.ts.net` Origin은 받지 않는다 |
| `*.ts.net` | Origin이 그 호스트와 이름·포트가 같아야 한다. 생략된 포트는 scheme 기본값으로 정규화한다(`https://h.ts.net` = `https://h.ts.net:443`) |

루프백 Host에서 포트를 보지 않는 이유는 SSH `-L` 때문이다. 포워딩 뒤에서는 Origin과 Host의 포트가 서버 포트와 다르다. 실측에서 포워더 18110→18106을 거친 `/api/pick`·`/api/pin`·`/close`가 `200`이었다.

루프백 Host에 `*.ts.net` Origin을 받지 않는 이유는 이렇다. `tailscale serve`는 Host를 보존하므로 이 조합은 정상 경로가 아니다. 받으면 다른 tailnet의 Funnel 공개 페이지가 로컬 사용자 브라우저를 통해 `close`·`clear` 같은 본문 없는 POST를 preflight 없이 보낼 수 있다. 실측에서 고치기 전에는 `200`이었고 지금은 `403`이다.

### 모든 요청의 Host

**모든 요청**의 `Host`는 루프백 이름(`127.0.0.1`·`localhost`·`::1`, **포트는 보지 않는다**)이거나 `*.ts.net`이어야 한다. v0.2부터는 `--public-host`로 준 이름도 받고, 그 이름의 `https` Origin도 같은 출처로 본다. DNS rebinding으로 핀 메모나 원고 스니펫이 새지 않게 하려는 것이다.

`Tailscale-User-*` 헤더가 있어도 이 검사를 면제하지 않는다. rebinding 페이지는 같은 출처 GET에 그 헤더를 preflight 없이 실을 수 있기 때문이다. `tailscale serve`는 원래 `Host`(`<기기>.<tailnet>.ts.net`)를 보존해 넘기므로 정상 테일넷 요청은 통과한다.

Host에서 포트를 보지 않는 이유도 SSH `-L`이다. `-L 9000:127.0.0.1:<port>`로 다른 로컬 포트에 포워딩하면 브라우저가 보내는 `Host`는 `localhost:9000`처럼 포워딩 쪽 포트가 된다. 포트까지 요구하면 이런 요청이 전부 `403`이었다. DNS rebinding 방어의 핵심은 Host 이름이 루프백 이름인가이고, 포트와는 무관하다. rebinding 공격의 `Host`는 애초에 루프백 이름이 아니라 공격자 도메인이다. 그래서 포트를 빼도 방어는 약해지지 않는다. 교차 출처 방어는 `Origin` 검사가 맡는다.

### 첫 배포와 알려진 한계

첫 배포 때 공저자 브라우저에서 저장이 `403`("허용되지 않은 Host" 또는 "다른 출처")이면 그 메시지에 찍힌 값을 기록한다. 그리고 `--no-origin-check`로 임시 우회한다.

> **주의**
>
> 루프백 Origin의 포트를 보지 않으므로, 같은 기기의 다른 로컬 웹앱(`http://localhost:3000` 등)이 사용자 브라우저를 통해 보내는 POST는 막지 못한다. SSH `-L` 지원과 맞바꾼 선택이다.

## `tailscale serve` 뒤에서 (실측)

`tailscale serve`는 요청마다 신원 헤더를 붙이고 `*.ts.net` Host를 그대로 넘긴다. 아래는 2026-09-21에 잰 값이다.

| 요청 | 결과 |
| --- | --- |
| 테일넷에서 `GET /` | `200`. `GET /api/meta`의 `me`가 `{login, name, pic}`로 채워진다 |
| 브라우저처럼 `Origin: https://<host>.ts.net:<port>`를 붙인 `POST` | `200` |
| 다른 출처(`Origin: https://evil.example`)의 `POST` | `403` |
| 신원 헤더를 위조하고 낯선 `Host`로 보낸 `POST` | `403`. 헤더가 Host 검사를 건너뛰게 하지 않는다 |
| 공인 IP로 접근 | 연결 실패 |

> **핵심**
>
> `--auth tailscale`에서 신원 헤더는 **TCP 상대가 loopback일 때만 믿는다.**

`tailscale serve`는 loopback에서 서버에 붙는다. 그래서 다른 상대가 보낸 신원 헤더는 무시한다. 다른 상대는 loopback이 아닌 `--bind`에서만 생긴다.

`127.0.0.1`에 직접 붙은 요청이 `Tailscale-User-Login`을 달면 여전히 그 사람으로 기록된다(2026-09-24 실측, `/api/meta`의 `me`). 회귀·브라우저 검증은 이 성질로 두 사람을 흉내 낸다(Playwright `extra_http_headers`).

같은 기기의 로컬 프로세스는 헤더를 스스로 붙일 수 있다. 또 loopback 에이전트가 켜져 있으면 헤더 없는 로컬 요청(루프백 `Host`)은 에이전트로 처리된다. `tailscale serve`를 거친 헤더 없는 요청(`*.ts.net` `Host`)은 그렇지 않다. `--tailnet-agent`가 아니면 `403`이다. 여럿이 쓰는 머신이라면 에이전트에게 토큰을 주고 `--no-agent-loopback`을 켠다. 그리고 `--members-only`와 역할로 들어올 사람과 할 일을 좁힌다. 기본 바인딩에서는 테일넷을 거치지 않은 요청이 그 기기 안에서만 온다.

## 상시로 띄울 때 — systemd 사용자 유닛

상시 인스턴스는 systemd 사용자 유닛 `limn@<이름>`으로 관리한다. 유닛 생성, 설정(`~/.config/limn/<이름>.env`), 시작, 정지, 재시작은 인스턴스 관리자의 `limn add|start|stop|update`가 맡는다. 유닛 파일의 정확한 형식과 TeX 배포판 PATH 설정 같은 상세 절차는 [instances.md](instances.md) §유닛 템플릿이 정본이다.

서버 자체는 표준 라이브러리만 쓰지만 **재빌드는 외부 명령에 의존한다.** `latexmk`·`pdftoppm`·`pdftotext`·`synctex`가 그 명령이다. systemd는 로그인 셸의 rc를 거치지 않는다. 그래서 TeX 배포판이 `/usr/local/texlive/...`처럼 기본 PATH 밖에 있으면 유닛이 그 경로를 명시해야 한다. 인스턴스 관리자가 이 일을 처리한다.

> **주의**
>
> 유닛에 TeX 경로가 빠지면 **뷰어는 멀쩡히 뜨는데 재빌드만 실패한다.**

확인은 두 줄이면 된다.

```bash
tr '\0' '\n' < /proc/$(pgrep -f 'limn serve' | head -1)/environ | grep ^PATH=
curl -s -X POST http://127.0.0.1:<port>/api/rebuild | head -c 200   # state 가 ok 여야 한다
```

## 상태 파일 배치

상태 폴더(`<state_dir>`)는 핀, 빌드 산출물, 로그를 담는다. 원고 체크아웃은 건드리지 않는다.

### 단일 문서

`--doc` 없이 띄우면 다음처럼 둔다. 옛 상태 폴더와 같은 배치다.

```text
<state_dir>/
├── build/                    # rsync 사본 + latexmk 산출물 (원본 체크아웃 아님)
├── pages.cur                 # 지금 쪽 이미지 디렉토리 이름(포인터, 원자적 교체)
├── builds.json               # 빌드 이력(build id·원고 지문·seq·마지막 결과) — 위치 추정·build_seq 원천
├── pages-<build_id>/         # page-*.png + 짝이 맞는 PDF·synctex 사본 (현재와 직전 1개만 유지)
├── pages/                    # 옛 배치 — pages.cur 가 없으면 이것을 그대로 쓴다
├── pins.jsonl                # 현재 핀 전체(매번 원자적으로 다시 씀)
├── pins.seq                  # 마지막으로 발급한 id
├── pins.dropped.jsonl        # 휴지통: 삭제한 핀(restore 원천). 30일 지난 항목은 기동·삭제·되살리기 때 빠진다
├── pins.jsonl.corrupt-*.bak  # 깨진 줄이 있을 때 첫 쓰기 전 원본 보존(조건부)
├── pins_<ts>.jsonl.bak       # /api/clear 보관본
├── pins.md                   # 에이전트 진입점 — 이 한 장만 읽는다
├── people.json               # @태그 후보이자 멤버 — 이 뷰어를 연 사람과 `limn member` 로 넣은 사람(선택 `role`, 에이전트 제외, 원자적 교체, 권한 0600)
├── tokens.json               # 에이전트 API 토큰 — SHA-256 해시만, 권한 0600, `limn token` 이 쓴다(첫 토큰 전에는 없다)
├── .people.lock · .tokens.lock   # 위 두 파일의 프로세스 간 잠금(서버와 CLI 가 동시에 쓸 수 있다)
├── events.jsonl              # mention·review_requested·replied·reopened·assigned·dropped·cleared·purged 기록(추가 전용, 최근 5000건, 바깥으로 보내지 않는다)
├── audit.jsonl · .audit.lock # 0.3.1: 감사 기록 — clear·purge·토큰 발급/폐기·멤버 추가/역할/제거(덧붙이기만, 자르지 않음, 권한 0600, 첫 기록 전에는 없다)
├── build.log
├── built_at.txt
├── built_src_mtime.txt       # 빌드 시작 시각의 src_mtime — 자동 동기화 배지 기준(없어도 동작)
└── head.txt                  # 빌드 시점 커밋(짧은 해시) — 원고 repo 가 git 이면
```

`built_src_mtime.txt`가 쓰이는 자동 동기화 배지는 [build-sync.md](build-sync.md) §자동 동기화에서 설명한다.

`people.json`과 `tokens.json`은 접근 제어의 상태다. `people.json`의 각 사람에게는 `role` 필드가 있을 수 있고(`owner`·`editor`·`viewer`·`agent`), 없으면 editor다. `tokens.json`에는 토큰 원문이 아니라 해시만 남으므로 토큰을 잃으면 새로 만든다. 두 파일 모두 권한 `0600` 으로 쓴다. 0.2.1 이전에 만든 `people.json` 을 남이 쓸 수 있으면 서버가 기동 때 `0600` 으로 좁히고 한 번 기록한다. 서버와 `limn token`·`limn member` 명령이 두 파일을 동시에 고칠 수 있어서 `.people.lock`·`.tokens.lock`으로 프로세스 사이 쓰기를 잠근다. 돌고 있는 서버는 다음 요청부터 바뀐 내용을 읽으므로 재시작이 필요 없다.

`audit.jsonl`(0.3.1)은 누가 되돌릴 수 없는 일을 했는지 남기는 감사 기록이다. 서버는 `/api/clear`·영구 삭제를, `limn token`·`limn member` 명령은 토큰 발급·폐기와 멤버 추가·역할 변경·제거를 명령을 돌린 OS 계정 이름으로 덧붙인다. `events.jsonl` 과 달리 회전하지 않으므로 오래 운영한 인스턴스에서는 필요할 때 옮겨 보관한다. 옛 버전은 이 파일을 읽지 않으므로 되돌려도 된다. 레코드 모양은 [api.md](api.md) §감사 기록 (`audit.jsonl`)에 있다.

### 여러 문서

`--doc`으로 띄우면 핀 파일은 루트에 하나 두고, 문서별 빌드 산출물은 `docs/<키>/`에 둔다. 키가 `main`인 LaTeX 문서만 위 단일 문서 자리(루트)를 쓴다.

```text
<state_dir>/
├── pins.jsonl · pins.seq · pins.dropped.jsonl · pins.md   # 문서 전체에 하나(핀 번호가 문서를 가로질러 유일)
└── docs/
    ├── rr/                   # build/ · pages.cur · pages-<build_id>/ · builds.json · built_at.txt · head.txt …(위와 같은 이름)
    └── rv/                   # 보기 전용: pages.cur · pages-<id>/(쪽 PNG + PDF 사본) · builds.json · pdf_sig.txt(그린 PDF 의 mtime:크기)
```

## 뷰어 사용법 (사용자)

운영자가 공저자에게 안내할 사용법이다. 화면 설계와 근거는 [viewer.md](viewer.md)에 있다.

### 데스크톱

| 동작 | 방법 |
| --- | --- |
| 위치 고르기 | PDF 위를 드래그한다. 점선 '새 핀' 상자가 저장이나 취소 때까지 남는다. 다시 드래그해도 메모는 지워지지 않는다 |
| 범위 맞추기 | 패널의 한 줄 단계 컨트롤(드래그한 줄 / 문단 / 환경 이름 · 줄 수)과 한 줄씩 움직이는 스테퍼 `위 [+][−] 아래 [+][−]`를 쓴다. 원문은 4줄로 접혀 있고 [원문 펼치기]로 연다 |
| 저장 | 패널 바닥에 고정된 [핀 저장]을 누르거나 메모 칸에서 ⌘↵ / Ctrl+Enter를 누른다(한글 조합 중에는 무시). 알림의 [되돌리기]로 되돌린다 |
| 수정 | 카드의 메모를 누르거나 [수정]을 눌러 메모와 범위를 편집한다. [위치 다시 잡기]로 PDF에서 새 위치를 지정한다 |
| 질문 · 답글 | 저장 전에 `[수정 요청 \| 질문]`을 고른다. 카드의 [답글]로 스레드에 글을 단다(⌘/Ctrl+Enter). `@`로 사람을 부른다. 부른 핀은 에이전트가 건너뛰고, 불린 사람은 목록 머리 [나를 부른 핀 N]으로 모아 본다 |
| 검토 대기 | 에이전트가 닫은 핀은 `검토 대기` 구획으로 온다. [변경 보기]로 고친 곳을 본 뒤 [확인]을 눌러 완료로 보내거나, [답글]에 무엇이 틀렸는지 적는다. 사람이 단 답글은 핀을 다시 열어 에이전트에게 보낸다(사람을 @태그하면 대화로 남고 상태는 그대로). 답글 칸 아래 한 줄이 결과를 미리 알려 주고, 보낸 뒤 알림의 [되돌리기]로 취소한다 |
| 완료·삭제 | [완료]와 [삭제]는 둘 다 알림의 [되돌리기]로 즉시 되돌린다. 닫힌 핀은 열린 목록 아래 구획 `완료 N`(기본 접힘)에서 [답글]로 다시 연다. 삭제한 핀은 휴지통에 30일 있다. [더보기] → 휴지통(데스크톱은 목록 아래 링크)에서 [되살리기]로 되살리고, 소유자는 [영구 삭제]할 수 있다([viewer.md](viewer.md) §휴지통). 구획 머리는 눌러 접고 펴며 기기마다 기억한다([viewer.md](viewer.md) §목록 구획). 다른 사람(공저자·에이전트)이 내 핀을 지우면 알림이 '#N 이 완료되었습니다'가 아니라 '#N 을 〈이름〉 가 삭제함 [되살리기]'로 구분해 뜬다 |
| 마크 배지 클릭 | PDF 위 초록 번호 배지를 누르면 해당 카드로 스크롤하고 `.cur`(강조 테두리)와 `.flash`(1.2초 깜빡임)를 준다. 새 선택은 만들지 않는다. 강조는 1.2초 뒤 저절로 풀린다. 정적 스타일이라 다음 클릭 전까지 남아 있지 않는다. 마크 상자 자체(배지 밖)를 드래그하면 평소처럼 새 위치를 고른다 |
| 카드의 [보기] | 그 핀의 마크를 화면 위에서 30% 지점으로 맞추고 테두리를 잠깐 반짝인다. 점선 테두리(`.est`)는 좌표가 추정치라는 뜻이다. 핀을 찍은 PDF와 지금 PDF가 다른 원고에서 만들어졌거나 줄이 이동한 경우이고, 서버가 판정한다([build-sync.md](build-sync.md) §위치 추정) |
| PDF 재빌드 | 원고를 비동기로 컴파일한다(수십 초). 누른 즉시 돌아오고, 진행 칩이 단계와 경과 시간을 보여 준다. 단계는 원고 복사 중 → LaTeX 컴파일 중 → 쪽 그리는 중이고, `--git-pull`이면 맨 앞에 원격 main 당겨오는 중이 붙는다. 다른 사람이 이미 누른 빌드도 같은 칩에 보인다. `--git-pull`일 때는 완료 알림에 pull 결과(원격 반영 범위 또는 건너뛴 사유)가 한 줄 붙는다 |
| 처리 중 배지 | 에이전트가 `claim`한 핀은 카드 머리에 호박색 점이 서고 `처리 중 · 약 15분 · 20:40쯤` 배지가 뜬다. 견적을 넘기면 `예상보다 늦어짐 (+5분)`, 견적 없는 claim은 `처리 중 · 20:02부터 (23분째)`로 보인다. 누가 잡았는지와 잠금 자동 해제 시각은 배지 설명에 있다([api.md](api.md) §처리 중 표시). 뷰어에서 claim을 걸 수는 없다. [풀기]로 표시만 지울 수 있다(예: 그 에이전트가 멈췄을 때) |
| 테마 | [◐] 시스템 → [☀] 밝게 → [☾] 어둡게. 설정은 브라우저에 저장된다 |
| 폭 | [폭] 버튼(Ctrl/⌘ 0)이 쪽 폭을 왼쪽 화면에 맞춘다. 저장된 폭이 없는 첫 방문에서 쪽이 화면보다 넓으면 자동으로 맞춘다 |
| 확대·축소 | PDF 위에서 Ctrl/⌘+휠이나 트랙패드 핀치(포인터 자리 기준), Ctrl/⌘ + `=`·`−`, [＋]·[−]를 쓴다. PDF 쪽만 커지고 패널과 도구 줄은 그대로다. 범위는 폭 맞춤의 0.5–5배다. 넘치면 PDF 영역 안에서만 가로로 스크롤된다. 입력 칸에 포커스가 있을 때와 패널 위에서의 Ctrl+휠은 브라우저 확대다([viewer.md](viewer.md) §PDF 영역 전용 확대) |
| 선명도 | 쪽은 PDF.js로 화면 해상도에 맞춰 벡터로 그린다. 그래서 확대해도 글자가 선명하다. 처음 몇 백 ms는 PNG가 먼저 보인다. 벡터로 못 그리면 도구 줄 옆에 'PNG 보기' 칩이 뜨고 PNG로 보인다 |
| 패널 폭 | 본문과 패널 사이 손잡이를 끈다. 범위는 280px부터 본문 480px를 남기는 폭까지다. 두 번 클릭하면 좁게 → 보통 → 넓게로 바뀌고, 포커스한 뒤 ←/→로도 바꾼다. 폭은 브라우저에 기억된다([viewer.md](viewer.md) §패널 정리와 폭 조절) |
| 문서 전환(여러 문서) | PDF 위 탭을 누른다. 접은 폴드는 도구 줄의 [문서 이름 ▾] → 목록을 쓴다. 입력 칸 밖에서는 Ctrl+PgUp/PgDn과 Alt+1…9도 된다. 문서마다 보던 자리와 확대가 남고, 주소 `#doc=<키>`로 링크와 새로고침이 된다. 탭의 점은 원고 수정됨(재빌드 필요), 스피너는 빌드 중, `PDF`는 보기 전용을 뜻한다 |
| 핀 다시 읽기 | 열린 핀 목록 머리의 [다시 읽기]를 누르면 핀 파일을 곧바로 다시 읽는다. 자동 동기화 주기 5초를 기다리지 않는다. 보통은 자동 동기화가 몇 초 안에 대신 해 준다([build-sync.md](build-sync.md) §자동 동기화). 접은·편 폴더블에서는 [더보기] 안에 있다 |
| 모든 문서 | 핀 목록 머리의 [모든 문서]를 켜면 다른 문서의 열린 핀도 보이고 카드에 문서 칩이 붙는다. 그 카드의 `#번호`·[보기]·[수정]은 그 문서로 바꾼 뒤 그 자리로 간다 |
| 보기 전용 PDF | 드래그나 길게 누르기로 영역을 고르면 '쪽 N 영역'과 영역 글자가 보인다(범위 단계 없음). 메모를 달아 저장한다. [PDF 재빌드]는 숨고, 파일이 바뀌면 저절로 다시 그린다 |
| 도움말 | `?` 키나 [?]. 흐름, 단축키, 용어, `<state_dir>/pins.md` 경로를 보여 준다 |
| Esc | 열린 것부터 닫는다. 순서는 도움말 → 툴팁 → 위치 다시 잡기 → 편집 → 선택이다. 입력 칸에 있을 때는 툴팁을 닫는 데 한 번을 쓰지 않는다. 그래서 메모 칸에서 Esc 한 번이면 선택이 취소된다 |

### 휴대폰·태블릿(터치)

폭이 700px 이하(접은 폴더블, 휴대폰)면 사이드바가 **하단 시트**가 된다. 700~1100px 터치 화면(편 폴더블, 태블릿)이면 **좁은 패널**이 된다. 설계와 근거는 [viewer.md](viewer.md) §모바일 레이아웃이다.

| 동작 | 방법 |
| --- | --- |
| 패널·시트 펴고 접기 | 도구 줄의 [핀 N ▴/▾] 버튼(시트)이나 [핀 N ▸/◂] 버튼(패널)을 누른다. N은 열린 핀 수다. 처음에 시트는 접혀 있고 도구 줄만 보인다. 편 화면에서 접은 상태는 기억된다 |
| 문단 하나 고르기 | PDF를 **길게 누른다**. 스크롤은 평소대로 된다 |
| 확대 | PDF 위에서 **두 손가락으로 벌리고 오므린다**. PDF 쪽만 커지고 시트·패널·도구 줄은 그대로다. 확대하면서 두 손가락을 옮기면 그쪽으로 끌려 간다 |
| 영역 고르기 | [선택]을 켜고(버튼이 파랗게 '선택 중') 한 손가락으로 끈다. 탭하면 그 자리 문단을 고른다. 켜 둔 동안에도 두 손가락 확대(PDF만)는 된다. 핀을 저장하거나 취소하면 저절로 꺼져 다시 스크롤된다 |
| 저장 | 고르면 시트가 펴지고 메모 칸이 원문 스니펫보다 위에 온다. [취소]와 [핀 저장]은 시트 바닥에 고정돼 있다. 키보드는 메모 칸을 눌러야 뜬다. 자동으로 띄우지 않는다 |
| 핀 카드 | 요약(번호·줄·쪽 한 줄과 메모 미리보기 두 줄)으로 접혀 있다. 누르면 펼쳐져 [보기]·[수정]·[완료]·[삭제]가 보인다. PDF 위 번호 배지를 눌러도 그 카드가 펼쳐진다 |
| [더보기] | 핀 다시 읽기, 테마, 축소·확대, 폭 맞춤, 패널 폭(시트에서는 시트 높이), 쪽 이동, 닫힌 핀, 휴지통, 도움말이 들어 있다. 맨 위에 파일, 쪽 수, 커밋, 빌드 시각, 작성자가 보인다 |
| 패널 폭(편 화면) | 패널 왼쪽 가장자리 손잡이를 끈다(300px ~ 화면 60%). 탭하면 좁게 → 보통 → 넓게로 바뀐다. 편 화면 폭은 데스크톱 폭과 따로 기억된다 |
| 시트 높이(접은 화면) | 시트 윗가장자리 손잡이를 끈다. 끝까지 내리면 접히고, 탭하면 낮게 → 보통 → 높게로 바뀐다. 높이는 기억된다 |
| 설명 보기 | 버튼을 길게 누르면 설명이 뜬다. 그 버튼은 눌리지 않는다 |
| 위치 다시 잡기 | [수정] → [위치 다시 잡기]를 누르면 선택 모드가 켜지고 시트가 접힌다. 끌거나 탭한 뒤 접힌 도구 줄 위 배너에서 [이 위치로 바꾸기]를 누른다 |
