# 운영 — 실행·보안·배포·뷰어

서버를 띄우고 노출하고 상시로 돌릴 때 연다. 실행 인자 전체, 포트 회피, 보안 제약, systemd, `tailscale serve`, 상태 파일, 사용자용 뷰어 사용법을 다룬다.

## 요구 환경

Python 3.10 이상 표준 라이브러리만 쓴다(외부 패키지·CDN·빌드 단계 없음) — 가상환경 없이 시스템 Python 3.10 으로도 돈다. 외부 도구는 `latexmk`, `synctex`, `pdftoppm`, `pdftotext`, (있으면) `rsync`.

회귀 테스트는 포트를 열지 않고(socketpair) 돈다: `uv run python3 -m unittest discover -s tests` (이 스킬 디렉토리에서).

## 실행 인자

```bash
uv run python3 .agents/skills/manuscript-pin-picker/scripts/pin_server.py \
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
  [--git-pull]
```

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `--manuscript` | 예 | — | LaTeX 소스 루트 디렉토리(`<manuscript_dir>`). 프로젝트마다 다르므로 하드코딩 금지. 핀이 가리킬 수 있는 파일은 이 트리 안으로 제한된다 |
| `--main` | 아니오 | 자동 탐지 | 빌드할 최상위 `.tex` 파일명. 생략 시 `--manuscript` 안에서 `\documentclass`를 포함한 `.tex` 파일을 찾는다. 0개 또는 2개 이상이면 후보 목록을 출력하고 종료(에러) — 추측하지 않는다 |
| `--port` | 아니오 | 자동 선택 | 미지정 시 §포트 충돌 회피에 따라 빈 포트를 탐색해 사용하고, 실제 선택된 포트를 기동 로그에 출력한다 |
| `--state-dir` | 아니오 | `${XDG_DATA_HOME:-~/.local/share}/manuscript-pin-picker/<slug>` | `<slug>`는 `--manuscript`의 절대경로를 정규화·해시한 값. 같은 머신에서 원고 A·B를 동시에 열어도 상태가 섞이지 않게 하기 위함(멀티 원고·멀티 worktree 안전) |
| `--dpi` | 아니오 | `150` | 페이지 PNG 렌더 해상도 |
| `--float-envs` | 아니오 | `figure,table,algorithm,equation,align,itemize,enumerate,minipage` | 기본 범위 단계를 '환경'으로 둘 `\begin{...}` 이름 목록(사다리 자체는 모든 환경을 본다, [design.md](design.md) §범위 사다리) |
| `--build-timeout` | 아니오 | `900` | `latexmk` 빌드 타임아웃(초). 넘으면 프로세스 그룹째 종료하고 `fail` 로 판정 |
| `--no-build` | 아니오 | (끔) | 기동 시 재빌드를 건너뛴다. 산출물이 이미 있을 때 서버만 빨리 올리는 용도 — PDF·쪽 이미지가 없으면 이 플래그와 무관하게 빌드한다 |
| `--allow` | 아니오 | (비움 = 전원 허용) | 허용할 tailscale 로그인 목록(쉼표 구분). 지정하면 `Tailscale-User-Login` 헤더가 **있는데** 목록 밖이면 `403`. 신원 헤더 없이 루프백 `Host` 로 온 요청(에이전트 `curl`)은 항상 허용. 신원 헤더 없이 `*.ts.net` `Host` 로 온 요청은 `403` — tailscale 은 **태그 장치**(와 funnel)에는 신원 헤더를 붙이지 않으므로, 이를 로컬로 치면 목록을 우회한다. `--allow` 를 비우면 태그 장치 요청도 `로컬/에이전트` 로 기록된다 |
| `--no-origin-check` | 아니오 | (끔) | `Host`·`Origin` 검사(DNS rebinding·CSRF 방어, §Host·Origin 검사)를 끈다. **탈출구 전용** — 실제 `tailscale serve` 가 예상 밖의 `Host`/`Origin`(MagicDNS 짧은 이름, `*.ts.net` 이 아닌 사용자 도메인 등)을 넘겨 UI 요청이 전부 `403` 일 때만 쓴다. 켜면 기동 로그에 경고가 찍힌다 |
| `--git-pull` | 아니오 | (끔) | 모든 재빌드(동기·비동기)가 copy 단계 전에 `--manuscript` 의 git 저장소를 업스트림으로 `--ff-only` pull 한다(공저자가 PR 을 머지해도 서버 체크아웃이 그대로였던 문제, [build-sync.md](build-sync.md) §`--git-pull`). 더러움·분기·업스트림 없음·git 저장소 아님이면 건너뛰고 지금 체크아웃으로 빌드는 계속한다 — 빌드를 막지 않는다 |

**바인딩은 `127.0.0.1` 고정이다 — 이 값을 바꾸는 플래그를 만들지 않는다.** (§보안 제약)

### 설계 초안과의 차이

이 스킬의 설계 초안은 `*.ts.net` 외의 도메인을 개별 허용하는 `--allow-host HOST`(여러 번 가능)와, `Host`/`Origin` 검사를 따로 끄는 `--no-host-check`, 요청 헤더를 로깅하는 `--log-headers` 를 별도로 두는 안이었다. 실제 구현은 그 세 개를 만들지 않고 위 `--allow`(로그인 기반 허용목록)·`--no-origin-check`(Host·Origin 검사를 한 번에 끔) 로 갈음했다 — 허용 호스트 집합 자체(`127.0.0.1`·`localhost`·`::1`·`*.ts.net`)는 하드코딩이고 커스텀 도메인을 추가로 허용할 길이 없다. 커스텀 `--allow-host` 가 필요해지면 별도로 구현해야 한다.

## 포트 충돌 회피 (강제)

기존에 그 포트를 쓰는 프로세스가 있는지 먼저 확인한다. 확인 없이 바로 바인딩을 시도하지 않는다.

```bash
ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
```

- 점유돼 있으면: (a) `--port`를 지정하지 않았다면 서버가 자동으로 다음 빈 포트를 시도하게 하거나, (b) 점유 프로세스가 이 스킬의 이전 인스턴스인지 확인 후 재사용(같은 `--manuscript`면 기존 서버를 그대로 쓰고 새로 띄우지 않는다).
- 서버를 내릴 때 `pkill -f pin_server.py`로 죽이지 않는다 — 자기 자신의 명령줄까지 매칭해 무관한 세션을 죽일 위험이 있다. 포트로 PID를 찾아 종료한다: `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
- 새 버전 서버로 바꿔 띄울 때 상태 디렉토리는 그대로 둔다. 옛 레이아웃(`pages/`, `pins.jsonl`, `built_at.txt`, `head.txt`)을 `--no-build` 로도 재빌드 없이 읽는다. 기동 때 `pages.cur`(내용 `pages`)와 `pins.seq`(기존 최대 id)를 만들고 `<state_dir>/pins.md` 를 다시 그린다. 옛 `pages/` 는 다음 재빌드가 `pages-<build_id>/` 로 교체한 뒤 직전 1개로 남았다가 그다음 재빌드에서 지워진다.
- **배포 경로**: 상시(systemd) 인스턴스는 이 레포의 `scripts/pin_server.py` 를 직접 실행하지 않고, `%h/.local/share/<name>/pin_server.py` 처럼 **`<state_dir>` 안에 둔 사본**을 실행한다(§상시로 띄울 때). 그래서 이 파일을 고친 뒤 실사용 인스턴스에 반영하려면 그 상태 디렉토리의 사본을 새 버전으로 덮어써야 한다 — 레포만 고치고 재시작해도 사본이 그대로면 옛 버전이 계속 돈다.

## 보안 제약 (Hard Rule)

| 항목 | 규칙 |
| --- | --- |
| 바인딩 주소 | `127.0.0.1` 고정. `0.0.0.0`·와일드카드 바인딩 금지 — 인자로도 노출하지 않는다 |
| 외부 노출 | `tailscale serve`만 사용. **`tailscale funnel` 금지** — funnel은 공인 인터넷에 노출한다 |
| 노출 후 검증 | (1) 테일넷 안에서 그 URL에 `curl`하면 `200` 확인. (2) 공인 IP·테일넷 밖 경로로는 연결이 실패하는지 확인(즉 `tailscale serve status`가 "Funnel"이 아니라 "tailnet only"로 뜨는지) — 이 둘을 확인해야 "노출됐다"고 보고한다 |
| 인증 | 없음(테일넷 자체가 경계). 신원 헤더는 기록용이고, 필요하면 `--allow` 로 로그인 목록을 제한한다. 핀 데이터에 민감정보를 적지 않는다는 전제 |
| 요청 경계 | 응답 전에 본문을 끝까지 읽고 오류 뒤 연결을 닫는다(요청 밀반입 차단), `Transfer-Encoding` 거부, 교차 출처 `Origin`·낯선 `Host` 는 `403`, 본문 있는 POST 는 JSON 만 — [api.md](api.md) §요청 형식과 경계, 아래 §Host·Origin 검사 |
| 경로 | 핀·스니펫이 가리킬 수 있는 파일은 `--manuscript` 트리 안뿐이다(밖이면 `400`) |
| 종료 | 세션 종료 시 `tailscale serve --https=<port> off` 등으로 노출을 내린다. 서버 프로세스 자체를 계속 띄워둘지는 사용자 판단(재사용 이점과 유휴 리소스 비용의 트레이드오프) |

이 스킬은 [`agent-operations.md`](../../../rules/agent-operations.md) §4.1(원격 세션에서 결과물을 도달 가능한 주소로 서빙하는 일반 원칙)의 예외다 — 여기는 `127.0.0.1` + `tailscale serve` 조합을 고정한다. 이유: PDF 뷰어가 즉석 markup 상태를 담고 있어 임의 바인딩보다 테일넷 경계 하나로 통제하는 편이 안전하다.

### Host·Origin 검사

- 교차 출처 요청: `Origin` 이 있으면 **Host 종류로 갈라** 검사한다(아니면 `403`).
  - Host 가 루프백이면 Origin 도 루프백 이름(`127.0.0.1`·`localhost`·`::1`)이어야 하고 **포트는 보지 않는다**(SSH `-L` 뒤에서는 Origin·Host 포트가 서버 포트와 다르다 — 실측: 포워더 18110→18106 에서 `/api/pick`·`/api/pin`·`/close` 가 200).
  - 루프백 Host 에 `*.ts.net` Origin 은 받지 않는다 — tailscale serve 는 Host 를 보존하므로 정상 경로가 아니고, 받으면 다른 tailnet 의 Funnel 공개 페이지가 로컬 사용자 브라우저로 `close`·`clear` 같은 본문 없는 POST 를 preflight 없이 보낸다(실측: 고치기 전 200, 지금 403).
  - Host 가 `*.ts.net` 이면 Origin 은 그 호스트와 이름·포트가 같아야 한다(생략 포트는 scheme 기본값으로 정규화 — `https://h.ts.net` = `https://h.ts.net:443`).
- **모든 요청**의 `Host` 는 루프백 이름(`127.0.0.1`·`localhost`·`::1`, **포트는 안 본다**) 또는 `*.ts.net` 이어야 한다 — DNS rebinding 으로 핀 메모·원고 스니펫이 새지 않게. `Tailscale-User-*` 헤더가 있어도 면제하지 않는다: rebinding 페이지는 같은 출처 GET 에 그 헤더를 preflight 없이 실을 수 있다. tailscale serve 는 원래 `Host`(`<기기>.<tailnet>.ts.net`)를 보존해 넘기므로 정상 테일넷 요청은 통과한다.
- 첫 배포 때 공저자 브라우저에서 저장이 `403`("허용되지 않은 Host"/"다른 출처")이면 그 메시지의 값을 기록하고 `--no-origin-check` 로 임시 우회한다.
- Host 는 왜 포트를 안 보는가: SSH `-L 9000:127.0.0.1:<port>` 로 다른 로컬 포트에 포워딩하면 브라우저가 보내는 `Host` 는 `localhost:9000`처럼 포워딩 쪽 포트가 된다. 여기서 포트까지 요구하면 이런 요청이 전부 `403` 이었다. Host 이름 자체(루프백 이름인가)는 DNS rebinding 방어의 핵심이고 포트와 무관하므로, 포트를 빼도 그 방어는 약해지지 않는다 — rebinding 공격의 `Host` 는 애초에 루프백 이름이 아니라 공격자 도메인이다. 교차 출처 방어는 `Origin` 검사가 맡는다.
- 알려진 한계: 루프백 Origin 의 포트를 보지 않으므로, 같은 기기의 다른 로컬 웹앱(`http://localhost:3000`)이 사용자 브라우저로 보내는 POST 는 막지 못한다 — SSH `-L` 지원과 맞바꾼 선택이다.

## `tailscale serve` 뒤에서 (실측)

`tailscale serve` 는 요청마다 신원 헤더를 붙이고 `*.ts.net` Host 를 그대로 넘긴다. 2026-09-21 에 잰 값이다.

| 요청 | 결과 |
| --- | --- |
| 테일넷에서 `GET /` | `200`. `GET /api/meta` 의 `me` 가 `{login, name, pic}` 로 채워진다 |
| 브라우저처럼 `Origin: https://<host>.ts.net:<port>` 를 붙인 `POST` | `200` |
| 다른 출처(`Origin: https://evil.example`)의 `POST` | `403` |
| 신원 헤더를 위조하고 낯선 `Host` 로 보낸 `POST` | `403` — 헤더가 Host 검사를 건너뛰게 하지 않는다 |
| 공인 IP 로 접근 | 연결 실패 |

신원 헤더는 **구분용이지 인증이 아니다.** 같은 기기의 로컬 프로세스는 헤더를 스스로 붙일 수 있다. 바인딩이
`127.0.0.1` 이라 테일넷을 거치지 않은 요청은 그 기기 안에서만 오고, 그 기기는 이미 사용자 것이다.

## 상시로 띄울 때 — systemd 사용자 유닛

서버 자체는 표준 라이브러리만 쓰지만, **재빌드는 외부 명령에 의존한다** — `latexmk`·`pdftoppm`·`pdftotext`·`synctex`.
systemd 는 로그인 셸의 rc 를 거치지 않으므로, TeX 배포판이 `/usr/local/texlive/...` 처럼 기본 PATH 밖에 있으면
유닛이 그 경로를 명시해야 한다. 그러지 않으면 **뷰어는 멀쩡히 뜨는데 재빌드만 실패한다** — 배포판 기본 `pdflatex`
가 잡혀 저널 클래스 파일(`elsarticle.cls` 등)을 못 찾는 형태로 드러난다(2026-09-21 실측).

```ini
[Service]
# 대화형 셸에서 `kpsewhich <클래스>.cls` 가 가리키는 배포판의 bin 을 PATH 맨 앞에 둔다.
Environment=PATH=/usr/local/texlive/2025/bin/x86_64-linux:/usr/local/bin:/usr/bin:/bin
ExecStart=/usr/bin/python3 %h/.local/share/<name>/pin_server.py \
  --manuscript <manuscript_dir> --main <main>.tex --state-dir %h/.local/share/<name> --port <port> --no-build
Restart=on-failure
```

확인은 두 줄이면 된다.

```bash
tr '\0' '\n' < /proc/$(pgrep -f pin_server.py | head -1)/environ | grep ^PATH=
curl -s -X POST http://127.0.0.1:<port>/api/rebuild | head -c 200   # state 가 ok 여야 한다
```

설정 파일을 홈에 직접 두지 않는 dotfiles 규약을 쓰는 기기라면 유닛도 그 저장소에서 관리하고 심링크한다.

## 상태 파일 레이아웃

```
<state_dir>/
├── build/                    # rsync 사본 + latexmk 산출물 (원본 체크아웃 아님)
├── pages.cur                 # 지금 쪽 이미지 디렉토리 이름(포인터, 원자적 교체)
├── builds.json               # 빌드 이력(build id·원고 지문·seq·마지막 결과) — 위치 추정·build_seq 원천
├── pages-<build_id>/         # page-*.png + 짝이 맞는 PDF·synctex 사본 (현재와 직전 1개만 유지)
├── pages/                    # 옛 레이아웃 — pages.cur 가 없으면 이것을 그대로 쓴다
├── pins.jsonl                # 현재 핀 전체(매번 원자적으로 다시 씀)
├── pins.seq                  # 마지막으로 발급한 id
├── pins.dropped.jsonl        # 삭제한 핀(restore 원천)
├── pins.jsonl.corrupt-*.bak  # 깨진 줄이 있을 때 첫 쓰기 전 원본 보존(조건부)
├── pins_<ts>.jsonl.bak       # /api/clear 보관본
├── pins.md                   # 에이전트 진입점 — 이 한 장만 읽는다
├── build.log
├── built_at.txt
├── built_src_mtime.txt       # 빌드 시작 시각의 src_mtime — 자동 동기화 배지 기준(build-sync §자동 동기화, 없어도 동작)
└── head.txt                  # 빌드 시점 커밋(짧은 해시) — 원고 repo가 git이면
```

## 뷰어 사용법 (사용자)

| 동작 | 방법 |
| --- | --- |
| 위치 고르기 | PDF 위 드래그 → 점선 '새 핀' 상자가 저장·취소 때까지 남는다. 다시 드래그해도 메모는 지워지지 않는다 |
| 범위 맞추기 | 패널의 한 줄 단계 컨트롤(드래그한 줄 / 문단 / 환경 이름 · 줄 수)과 한 줄씩 스테퍼 ▲+ ▲− ▼+ ▼−. 원문은 4줄로 접혀 있고 [원문 펼치기] 로 연다 |
| 저장 | 패널 바닥에 고정된 [핀 저장] 또는 메모 칸에서 ⌘↵ / Ctrl+Enter(한글 조합 중엔 무시). 알림의 [되돌리기] |
| 수정 | 카드의 메모를 누르거나 [수정] → 메모·범위 편집, [위치 다시 잡기] 로 PDF 에서 새 위치 지정 |
| 완료·삭제 | [완료]·[삭제] — 둘 다 알림의 [되돌리기]로 즉시 되돌린다. 닫힌 핀은 목록 아래 '닫힌 핀 N' 에서 [다시 열기], 삭제한 핀은 그 아래 '삭제한 핀 N' 에서 [되살리기]. 다른 사람이 자기 핀을 지우면(공저자·에이전트) 알림이 '#N 이 완료되었습니다' 가 아니라 '#N 을 〈이름〉 가 삭제함 [되살리기]' 로 구분해 뜬다 |
| 마크 배지 클릭 | PDF 위 초록 번호 배지를 누르면 해당 카드로 스크롤하고 `.cur`(강조 테두리)와 `.flash`(1.2초 깜빡임)를 준다(새 선택을 만들지 않는다). 1.2초 뒤 강조는 저절로 풀린다 — 정적 스타일이라 다음 클릭 전까지 남아 있지 않는다. 마크 상자 자체(배지 밖)를 드래그하면 평소처럼 새 위치를 고른다 |
| 카드의 [보기] | 그 핀의 마크를 화면 위에서 30% 지점으로 맞추고 테두리가 잠깐 반짝인다. 점선 테두리(`.est`)는 핀을 찍은 PDF 와 지금 PDF 가 다른 원고에서 만들어졌거나 줄이 이동해 좌표가 추정치임을 뜻한다(서버 판정, [build-sync.md](build-sync.md) §위치 추정) |
| PDF 재빌드 | 원고를 비동기로 컴파일한다(수십 초) — 누른 즉시 돌아오고, 진행 칩이 단계(`--git-pull` 이면 원격 main 당겨오는 중 → 원고 복사 중 → LaTeX 컴파일 중 → 쪽 그리는 중)와 경과 시간을 보여 준다. 다른 사람이 이미 누른 빌드도 같은 칩에 보인다. 완료 알림에 pull 결과(원격 반영 범위 또는 건너뛴 사유)가 한 줄 붙는다(`--git-pull` 일 때). '핀 다시 읽기' 는 핀 목록만 즉시 다시 읽는다(자동 동기화가 보통 몇 초 안에 대신 해 준다, build-sync §자동 동기화) |
| 처리 중 배지 | 에이전트가 `claim` 한 핀은 카드에 "처리 중: 이름 · ~시각" 배지가 뜬다([api.md](api.md) §처리 중 표시). 뷰어에서 claim 을 걸 수는 없다 — [풀기]로 표시만 지울 수 있다(예: 그 에이전트가 멈췄을 때) |
| 테마 | [◐] 시스템 → [☀] 밝게 → [☾] 어둡게. 설정은 브라우저에 저장된다 |
| 폭 | [폭] 이 쪽 폭을 왼쪽 화면에 맞춘다. 저장된 폭이 없는 첫 방문에서 화면보다 넓으면 자동으로 맞춘다 |
| 패널 폭 | 본문과 패널 사이 손잡이를 끈다(280px ~ 본문 480px 를 남기는 폭). 두 번 클릭하면 좁게 → 보통 → 넓게, 포커스한 뒤 ←/→. 폭은 브라우저에 기억된다([design.md](design.md) §패널 정리와 폭 조절) |
| 도움말 | `?` 키 또는 [?] — 흐름·단축키·용어·`<state_dir>/pins.md` 경로 |
| Esc | 열린 것부터 닫는다: 도움말 → 툴팁 → 위치 다시 잡기 → 편집 → 선택. 입력 칸에 있을 때는 툴팁을 닫는 데 한 번을 쓰지 않는다(메모 칸에서 Esc 한 번이면 선택이 취소된다) |

### 휴대폰·태블릿(터치)

폭이 700px 이하(접은 폴더블·휴대폰)면 사이드바가 **하단 시트**가 되고, 700~1100px 터치 화면(편 폴더블·태블릿)이면 **좁은 패널**이 된다. 설계와 근거는 [design.md](design.md) §모바일 레이아웃.

| 동작 | 방법 |
| --- | --- |
| 패널·시트 펴고 접기 | 도구 줄의 [핀 N ▴/▾](시트) 또는 [핀 N ▸/◂](패널). N 은 열린 핀 수. 처음에 시트는 접혀 있고 도구 줄만 보인다. 편 화면에서 접은 상태는 기억된다 |
| 문단 하나 고르기 | PDF 를 **길게 누른다**. 스크롤·두 손가락 확대는 평소대로 된다 |
| 영역 고르기 | [선택] 을 켜고(버튼이 파랗게 '선택 중') 한 손가락으로 끈다. 탭하면 그 자리 문단. 켜 둔 동안에도 두 손가락 확대는 된다. 핀을 저장하거나 취소하면 저절로 꺼져 다시 스크롤된다 |
| 저장 | 고르면 시트가 펴지고 메모 칸이 원문 스니펫보다 위에 온다. [취소]·[핀 저장] 은 시트 바닥에 고정돼 있다. 메모 칸을 눌러야 키보드가 뜬다(자동으로 띄우지 않는다) |
| 핀 카드 | 한 줄 요약(번호·줄·쪽·메모 첫 줄)으로 접혀 있다. 누르면 펼쳐져 [보기]·[수정]·[완료]·[삭제] 가 보인다. PDF 위 번호 배지를 누르면 그 카드가 펼쳐진다 |
| [⋯] | 핀 다시 읽기·테마·축소·확대·폭 맞춤·패널 폭(시트는 시트 높이)·쪽 이동·닫힌 핀·삭제한 핀·도움말. 맨 위에 파일·쪽 수·커밋·빌드 시각·작성자 |
| 패널 폭(편 화면) | 패널 왼쪽 가장자리 손잡이를 끈다(300px ~ 화면 60%). 탭하면 좁게 → 보통 → 넓게. 편 화면 폭은 데스크톱 폭과 따로 기억된다 |
| 시트 높이(접은 화면) | 시트 윗가장자리 손잡이를 끈다. 끝까지 내리면 접히고, 탭하면 낮게 → 보통 → 높게. 높이는 기억된다 |
| 설명 보기 | 버튼을 길게 누르면 설명이 뜬다(그 버튼은 눌리지 않는다) |
| 위치 다시 잡기 | [수정] → [위치 다시 잡기] 를 누르면 선택 모드가 켜지고 시트가 접힌다. 끌거나 탭하면 접힌 도구 줄 위 배너에서 [이 위치로 바꾸기] |
