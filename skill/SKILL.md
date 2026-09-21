---
name: Manuscript Pin Picker
description: "LaTeX 원고 PDF를 브라우저에 띄우고 드래그로 고른 영역을 SyncTeX 역변환으로 .tex 파일·줄 번호로 되찾는다. 스크린샷 대신 파일:줄범위를 주고받아 토큰과 왕복을 줄인다. 원고 특정 위치를 지목해 수정을 요청하거나, 쌓인 핀을 에이전트가 처리할 때 활성화."
slash_command: true
---

# Manuscript Pin Picker

> **Activation**: 사용자가 "이 부분 고쳐줘" 하면서 스크린샷을 붙여넣으려 하거나, 원고 PDF에서 특정 위치를 가리키며 수정을 요청할 때. 이미 쌓인 핀(`<state_dir>/pins.md`)을 처리할 때도 활성화.

원고 PDF 위에서 영역을 드래그하면 SyncTeX(`synctex edit`)로 그 자리의 `.tex` 파일·줄 번호를 되찾아 메모와 함께 "핀"으로 쌓는다. 목적은 정확도와 토큰 절약이다 — 스크린샷 한 장(1,000~1,600 토큰, 위치 불명)을 읽고 다시 원고에서 그 자리를 찾는 왕복 대신, `manuscript_kr.tex L493-L501`(≈35 토큰) 한 줄을 받아 에이전트가 그 줄을 바로 읽고 고친다.

## 사용 시점

- 사용자가 원고의 특정 문단·표·그림·수식을 화면으로 보면서 "여기를 이렇게 고쳐줘"라고 지목하고 싶을 때.
- 리뷰어 코멘트나 공동저자 피드백을 원고 PDF 위에 markup하듯 쌓아두고 싶을 때 (핀 = 위치가 붙은 TODO). 공저자가 같은 테일넷 주소로 들어와 핀을 남길 수 있고, 누가 남겼는지 기록된다(§작성자 귀속).
- 에이전트가 세션 시작 시 또는 사용자가 "핀 확인해줘"라고 할 때, 열린 핀을 일괄 처리.

## 쓰지 말아야 할 때

- 원고가 아직 SyncTeX 빌드가 안 되는 상태(구조적 컴파일 에러)면 먼저 [`latex-build-fix`](../latex-build-fix/SKILL.md)로 빌드부터 고친다.
- 위치가 이미 명확한 수정(예: 사용자가 이미 파일:줄 번호를 알고 있음)에는 이 스킬을 거치지 않고 바로 [`manuscript-revision`](../manuscript-revision/SKILL.md)으로 간다 — 서버를 띄우는 오버헤드가 낭비다.
- Typst 원고에는 적용되지 않는다 (SyncTeX은 LaTeX 전용). Typst 위치 대응은 이 스킬의 범위 밖.

## 아키텍처 개요

```
브라우저 (드래그로 영역 선택)
   │  좌표
   ▼
pin_server.py  ──(1)──▶  <manuscript_dir>의 사본을 별도 빌드 디렉토리에서
  127.0.0.1:<port>         latexmk -synctex=1 빌드 (원본 체크아웃은 건드리지 않음)
   │
   ├─(2) 역변환 두 경로를 겨루게 한 뒤 범위 사다리(드래그한 줄/문단/환경) 계산 → 스니펫
   ├─(3) 사용자가 메모를 달아 "핀"으로 저장 → <state_dir>/pins.jsonl (잠금 + 원자적 교체)
   └─(4) <state_dir>/pins.md 재생성 — 에이전트가 이 한 장만 읽는다
```

### 역변환이 두 경로인 이유

`synctex edit` 만으로는 부족하다. `minipage`·`tabular` 안(전형적으로 Nomenclature 기호표)은
SyncTeX 노드가 희박해서, 그 영역을 골라도 **조용히 엉뚱한 본문 줄이 잡힌다** — 실측으로 확인했다.
그래서 선택 사각형에 실제로 찍힌 글자를 `pdftotext` 로 뽑아 원문에서 되찾는 두 번째 경로를 둔다.
한글 어절은 마크업을 거의 타지 않아서(`타겟--소스 $i$ 간 코사인 거리`) 원문에 그대로 남는다.

두 경로는 **조건부 폴백이 아니라 같은 척도로 경쟁한다.** 어느 한쪽을 1차로 고정하면 그쪽이
조용히 틀렸을 때 걸러낼 방법이 없다. 채점은 영역 텍스트의 어절이 후보 줄 범위에 얼마나 들어
있는지로 하되, **어절마다 희귀도 가중**을 준다 — 가중이 없으면 `데이터`·`학습` 같은 흔한 말이
점수를 지배해 본문 문단이 기호표만큼 잘 맞는다고 나온다(이것도 실측이다). 동점이면 SyncTeX 를
남긴다. 글자가 없는 영역(그림)에서는 그쪽만 맞기 때문이다.

응답의 `via`(`synctex`/`text`)와 `score`(0~1)가 어느 경로로 얼마나 확신하는지 알려 준다.
UI 는 이를 '좌표로 찾음 · 일치 93%' / '글자로 찾음 · 일치 100%' 로 보여 준다.
`score` 가 낮으면 서버가 경고 문구를 함께 돌려준다.

### 범위 사다리

`POST /api/pick` 은 줄 범위 하나가 아니라 단계 목록(`levels`)을 준다. 클라이언트는 서버 왕복 없이 단계를 바꾼다.

| `level` | 뜻 |
| --- | --- |
| `raw` | 드래그 영역이 직접 가리킨 줄 |
| `para` | 그 줄을 감싸는 문단. 앞뒤 순수 `%` 주석 줄은 뺀다 — 한 줄이 한 문단인 원고에서 TODO 주석이 범위와 앵커 꼬리가 되던 것을 막는다. 절 제목 줄을 넘지 않고, 감싸는 가장 안쪽 환경 밖으로 나가지 않으며(환경 안쪽이면 `\begin`/`\end` 줄도 뺀다), 드래그 밖 환경에 반쯤 걸치지도 않는다 |
| `env`, `env2`, `env3` | 감싸는 `\begin{X}…\end{X}` 를 안쪽부터 최대 3단(이름 무관, `document` 제외). 바깥 환경이 안쪽을 앞뒤 한 줄로만 감싸면 같은 블록으로 보고 합친다 |
| `lines` | 사용자가 ▲▼ 로 줄을 직접 조정한 범위 |

범위가 같은 단계는 하나로 합치고(`merged`), 기본 단계(`default_level`)는 `--float-envs` 환경 안이면 그 `env` 단계, 아니면 `para` 다. 응답의 `lo`/`hi`/`kind` 는 기본 단계의 값이다. section 단계는 두지 않는다(수백 줄 범위가 쉽게 생긴다).

원본 체크아웃을 직접 열지 않고 rsync 사본에서 빌드하는 이유: 원고가 동시에 편집 중이어도 빌드가 중간 상태를 물지 않게 하기 위함이다. 빌드 사본의 경로를 원본 경로로 되돌리는 매핑(`build_dir → manuscript_dir`)은 서버가 내부적으로 처리하며, 에이전트에게는 항상 원본 경로가 보고된다. 상태 디렉토리를 옮기거나 복제해 synctex 가 옛 build 경로를 가리키면, 경로 꼬리가 원고 트리 안 파일과 맞을 때만 되돌리고 트리 밖은 읽지 않는다.

## 인터페이스

### `scripts/pin_server.py`

Python 3.10 이상 표준 라이브러리만 쓴다(외부 패키지·CDN·빌드 단계 없음) — 가상환경 없이 시스템 Python 3.10 으로도 돈다. 외부 도구는 `latexmk`, `synctex`, `pdftoppm`, `pdftotext`, (있으면) `rsync`.

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
  [--no-origin-check]
```

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `--manuscript` | 예 | — | LaTeX 소스 루트 디렉토리(`<manuscript_dir>`). 프로젝트마다 다르므로 하드코딩 금지. 핀이 가리킬 수 있는 파일은 이 트리 안으로 제한된다 |
| `--main` | 아니오 | 자동 탐지 | 빌드할 최상위 `.tex` 파일명. 생략 시 `--manuscript` 안에서 `\documentclass`를 포함한 `.tex` 파일을 찾는다. 0개 또는 2개 이상이면 후보 목록을 출력하고 종료(에러) — 추측하지 않는다 |
| `--port` | 아니오 | 자동 선택 | 미지정 시 §"포트 충돌 회피"에 따라 빈 포트를 탐색해 사용하고, 실제 선택된 포트를 기동 로그에 출력한다 |
| `--state-dir` | 아니오 | `${XDG_DATA_HOME:-~/.local/share}/manuscript-pin-picker/<slug>` | `<slug>`는 `--manuscript`의 절대경로를 정규화·해시한 값. 같은 머신에서 원고 A·B를 동시에 열어도 상태가 섞이지 않게 하기 위함(멀티 원고·멀티 worktree 안전) |
| `--dpi` | 아니오 | `150` | 페이지 PNG 렌더 해상도 |
| `--float-envs` | 아니오 | `figure,table,algorithm,equation,align,itemize,enumerate,minipage` | 기본 범위 단계를 '환경'으로 둘 `\begin{...}` 이름 목록(사다리 자체는 모든 환경을 본다) |
| `--build-timeout` | 아니오 | `900` | `latexmk` 빌드 타임아웃(초). 넘으면 프로세스 그룹째 종료하고 `fail` 로 판정 |
| `--no-build` | 아니오 | (끔) | 기동 시 재빌드를 건너뛴다. 산출물이 이미 있을 때 서버만 빨리 올리는 용도 — PDF·쪽 이미지가 없으면 이 플래그와 무관하게 빌드한다 |
| `--allow` | 아니오 | (비움 = 전원 허용) | 허용할 tailscale 로그인 목록(쉼표 구분). 지정하면 `Tailscale-User-Login` 헤더가 **있는데** 목록 밖이면 `403`. 신원 헤더 없이 루프백 `Host` 로 온 요청(에이전트 `curl`)은 항상 허용. 신원 헤더 없이 `*.ts.net` `Host` 로 온 요청은 `403` — tailscale 은 **태그 장치**(와 funnel)에는 신원 헤더를 붙이지 않으므로, 이를 로컬로 치면 목록을 우회한다. `--allow` 를 비우면 태그 장치 요청도 `로컬/에이전트` 로 기록된다 |
| `--no-origin-check` | 아니오 | (끔) | `Host`·`Origin` 검사(DNS rebinding·CSRF 방어, §HTTP API)를 끈다. **탈출구 전용** — 실제 `tailscale serve` 가 예상 밖의 `Host`/`Origin`(MagicDNS 짧은 이름, `*.ts.net` 이 아닌 사용자 도메인 등)을 넘겨 UI 요청이 전부 `403` 일 때만 쓴다. 켜면 기동 로그에 경고가 찍힌다 |

**바인딩은 `127.0.0.1` 고정이다 — 이 값을 바꾸는 플래그를 만들지 않는다.** (§보안 제약)

회귀 테스트는 포트를 열지 않고(socketpair) 돈다: `uv run python3 -m unittest discover -s tests` (이 스킬 디렉토리에서).

### HTTP API

바디는 1 MiB 이하 JSON 객체이고 `Content-Type: application/json` 이어야 한다(아니면 `400`/`413`/`415`). 본문 없는 POST(에이전트의 `curl -X POST …/close`)는 헤더 없이 그대로 된다. 오류 응답은 항상 `{"error": "<한국어 메시지>"}` JSON 이며 예상 밖 예외도 `500` JSON 으로 돌려준다. 기존 경로는 계약을 유지하고 새 필드·경로는 덧붙이기만 했다.

요청 경계(§보안 제약과 함께 본다):

- 서버는 **어떤 응답보다 먼저 본문을 Content-Length 만큼 끝까지 읽고**, 오류(`4xx`/`5xx`) 뒤에는 연결을 닫는다. `Transfer-Encoding` 요청은 `400`. 본문이 Content-Length 보다 짧게 끊기면 `400` 이고 동작하지 않는다(`/api/clear` 포함). 읽지 않은 본문이 같은 keep-alive 연결의 다음 요청으로 해석되면 `--allow` 와 작성자 기록을 우회하기 때문이다 — tailscale serve 는 백엔드 연결을 재사용한다.
- 교차 출처 요청: `Origin` 이 있으면 이 서버 자신(`http://127.0.0.1:<port>`·`localhost:<port>`) 또는 Host 와 같은 `*.ts.net` 이어야 한다(아니면 `403`). **모든 요청**의 `Host` 는 루프백 이름(포트 일치) 또는 `*.ts.net` 이어야 한다 — DNS rebinding 으로 핀 메모·원고 스니펫이 새지 않게. `Tailscale-User-*` 헤더가 있어도 면제하지 않는다: rebinding 페이지는 같은 출처 GET 에 그 헤더를 preflight 없이 실을 수 있다. tailscale serve 는 원래 `Host`(`<기기>.<tailnet>.ts.net`)를 보존해 넘기므로 정상 테일넷 요청은 통과한다. 첫 배포 때 공저자 브라우저에서 저장이 `403`("허용되지 않은 Host"/"다른 출처")이면 그 메시지의 값을 기록하고 `--no-origin-check` 로 임시 우회한다.
- 소켓 타임아웃 30초 — 본문을 보내다 멈춘 연결과 유휴 keep-alive 가 닫힌다(재빌드처럼 오래 걸리는 처리 자체와는 무관).

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/meta` | `pages`(쪽 목록), `built_at`, `head`(원고 커밋), `main`(최상위 .tex 이름), `n_open`·`n_done`, `pins_md`·`state_dir`(절대경로), `me`(지금 요청자), `building`(재빌드 진행 중) |
| `POST` | `/api/pick` | 드래그 좌표(`page`, `x0`, `y0`, `x1`, `y1`, 선택 `frac` = 숫자 4개 목록 `[x, y, w, h]`(쪽 대비 비율) — 다른 모양이면 `400`) → `{file, lo, hi, raw_lo, raw_hi, kind, via, score, warn, snippet, levels, default_level, n_lines}`. 입력 오류는 `400`, 되짚기 실패는 `200 {error}` |
| `GET` | `/api/pins` | 열린 핀 목록(JSON). 레코드마다 `rev` 가 채워진다. `?all=1` 이면 닫힌 핀까지 |
| `GET` | `/api/snippet?file=&lo=&hi=` | 원문 줄 스니펫(80줄 캡). `&levels=1` 이면 그 범위를 기준으로 한 사다리도. 원고 트리 밖이거나 범위가 틀리면 `400` |
| `POST` | `/api/pin` | 새 핀 추가 → `{id}`. 저장 필드 화이트리스트: `file, name, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, note, scope, quote` |
| `POST` | `/api/pins/{id}/edit` | 제자리 수정 — 아래 §핀 수정 |
| `POST` | `/api/pins/{id}/close` | 핀 1건을 처리 완료로 표시(`done: true`, `closed_by`). 레코드는 남고 `<state_dir>/pins.md` 의 접힌 목록으로 내려간다 → `{ok, pin}`. 그 id 가 없으면 `200 {"ok": false, "pin": null}`(reopen 도 같다) |
| `POST` | `/api/pins/{id}/reopen` | 닫은 핀을 되돌린다(`reopened_by`) → `{ok, pin}` |
| `POST` | `/api/pins/{id}/drop` | 핀을 목록에서 빼 `pins.dropped.jsonl` 로 옮긴다(잘못 찍은 것, `dropped_by`) → `{ok}`. 없는 id 면 `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/restore` | 삭제한 핀을 같은 id 로 되살린다(서버 재시작 뒤에도, `restored_by`) → `200 {ok, pin}` / `404`(삭제 기록 없음) / `409`(같은 id 가 이미 있음) |
| `POST` | `/api/clear` | 전체를 아카이브(`pins_<timestamp>.jsonl.bak`, 같은 초에 또 비우면 `pins_<timestamp>-1.jsonl.bak` …)하고 비움 — 일괄 리셋. id 발급 번호는 이어진다 |
| `POST` | `/api/rebuild` | PDF 다시 만들기(동기) — 아래 §재빌드 |

#### 핀 수정 (`/api/pins/{id}/edit`)

```json
{"note": "고친 메모", "lo": 185, "hi": 262, "scope": "env2", "kind": "env:minipage", "base_rev": 3}
```

- `base_rev` 는 필수다 — 수정하려는 핀을 읽을 때 받은 `rev`. 다르면 `409 {"error":"conflict","pin":<최신>}` 이고 아무것도 바뀌지 않는다. 에이전트가 먼저 닫았거나 자동 줄 맞춤이 옮긴 핀을 옛 `lo`/`hi` 로 조용히 덮어쓰지 않기 위해서다. `409` 를 받으면 최신 `pin` 을 보고 다시 보낸다.
- 위치를 통째로 바꿀 때는 `loc: {file, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, scope}` 를 보낸다(위치 다시 잡기). 필수는 `file`·`lo`·`hi` 다. `loc` 에 없는 `page`·`frac` 은 기존 값을 두고, `kind` 가 없으면 `lines` 가 된다(나머지 위치 필드는 지워진다). id·메모·작성자는 그대로다.
- 범위가 바뀌면 `anchor` 를 새로 떠고 `stale`/`sync` 를 지운다 — `stale` 핀도 이 경로로 고친다.
- 닫힌 핀은 메모만 고칠 수 있다. 범위·위치를 보내면 `409 {"error":"done"}`.
- 성공하면 `edited_at`·`edited_by` 가 기록되고 `rev` 가 1 오른다.

#### 재빌드 (`/api/rebuild`)

잠금 하나로 한 번에 하나만 돈다. 이미 빌드 중이면 기다리지 않고 `409 {"ok": false, "busy": true}`.

| `state` | 조건 | 화면 |
| --- | --- | --- |
| `ok` | 새 PDF 가 나왔고 LaTeX 로그에 `! ` 줄이 없음 | 새 쪽으로 교체 |
| `ok_errors` | 새 PDF 는 나왔지만 `! ` 줄이 있음(nonstopmode 의 `\undefinedmacro` 등) | 새 쪽으로 교체 + 오류 알림 |
| `fail` | 새 PDF 가 없거나(PDF mtime < 시작 시각) 시간 초과 | **이전 쪽 그대로** |

응답: `{"ok": <state≠fail>, "state", "errors": [{"line", "msg"}], "log", "elapsed_s"}`, 성공하면 `pages`(새 쪽 수)도. `errors` 는 `! ` 줄과 그 뒤 `l.<n>` 줄을 최대 5건. 쪽 이미지는 새 디렉토리 `pages-<build_id>/` 에 먼저 그린 뒤 포인터 파일 `pages.cur` 를 원자적으로 바꾼다 — 빌드 중에도, 전환 직후 옛 URL 로도 쪽 요청이 끊기지 않는다. 뷰어는 새로고침 없이 보던 쪽과 쓰던 메모를 유지한 채 이미지만 바꾼다.

### 핀 레코드 스키마 (`pins.jsonl`, 한 줄 = 한 레코드)

```json
{"id": 3, "at": "2026-09-21 20:10:00", "page": 4, "file": "<절대경로>/introduction.tex",
 "lo": 120, "hi": 134, "raw_lo": 122, "raw_hi": 131, "kind": "env:minipage", "scope": "env",
 "via": "synctex", "score": 0.93, "note": "이 문단 톤을 낮춰줘", "frac": [0.12, 0.30, 0.55, 0.18],
 "anchor": {"head": "이 절에서는 소스 재선정 주기를...", "tail": "...효과가 관측된다."},
 "synced_at": 1758450000.0, "sync": "moved +3", "rev": 2, "done": false,
 "author": {"login": "bob@example.com", "name": "Bob Park", "pic": "https://..."},
 "edited_at": "2026-09-21 21:00:00", "edited_by": {"login": "local", "name": "로컬/에이전트"}}
```

새 필드는 모두 선택이다 — 없는 옛 레코드도 그대로 읽힌다.

| 필드 | 뜻 |
| --- | --- |
| `rev` | 레코드 내용이 바뀌는 모든 쓰기(줄 이동·stale, 수정, 닫기, 다시 열기, 되살리기)에서 +1. 없으면 0 |
| `scope` | `raw\|para\|env\|env2\|env3\|lines` — 저장할 때 고른 사다리 단계 |
| `quote` | 선택 — 호출자가 붙인 짧은 인용(60자에서 자른다) |
| `anchor` | `{head, tail, head_off, tail_off}` — 줄 맞춤 기준. `*_off` 가 없는 옛 앵커는 0 으로 본다 |
| `kind` | `paragraph\|float\|block\|none`(옛 값) 또는 `env:<이름>`, `lines`. 모르는 값은 원문 그대로 둔다 |
| `author` | 만든 사람 `{login, name, pic?}` |
| `edited_at`, `edited_by` | 저장 뒤 마지막 수정 시각·사람 |
| `closed_by` / `reopened_by` | 닫은·다시 연 사람(`done_at`·`reopened_at` 과 함께) |
| `dropped_by` / `restored_by` | 삭제 기록(`pins.dropped.jsonl`)의 삭제자, 되살린 레코드의 복원자 |

`snippet`, `warn`, `levels`, `default_level` 은 응답에만 있고 저장하지 않는다.

### 작성자 귀속

공저자가 자기 컴퓨터에서 같은 테일넷 주소로 들어와 핀을 남긴다. 테일넷 구성원은 신뢰하는 동료이므로 **접근은 막지 않고 누가 무엇을 했는지만 구분한다.**

- `tailscale serve` 는 요청마다 `Tailscale-User-Login`, `Tailscale-User-Name`, `Tailscale-User-Profile-Pic` 헤더를 붙인다. 비 ASCII 이름은 RFC 2047 로 인코딩되어 오므로 서버가 풀어 저장한다. 서버는 `127.0.0.1` 에만 바인딩되므로 이 헤더는 tailscale 을 거쳐서만 온다(같은 머신의 로컬 프로세스는 흉내 낼 수 있다 — 인증이 아니라 구분이다).
- 헤더가 없는 요청(로컬 `curl`, 에이전트)은 `{"login": "local", "name": "로컬/에이전트"}` 로 기록된다.
- 핀 카드에 작성자 이름과 22px 원형 아바타(사진이 없거나 못 불러오면 이름 첫 글자)가 붙고, 카드 툴팁에 '작성: 이름 · 시각 / 수정: 이름 · 시각' 이 뜬다. 기록이 생기기 전의 옛 핀은 '기록 전' 으로 보인다.
- `<state_dir>/pins.md` 의 `작성` 열에 짧은 이름이 실린다(로컬은 `로컬`, 옛 핀은 `—`).
- 권한 제한은 없다. 막아야 하면 `--allow` 로 로그인 목록을 준다. 태그 장치처럼 신원 헤더가 없는 테일넷 요청은 `--allow` 가 있을 때 거부되고, 없을 때는 `로컬/에이전트` 로 기록된다(§실행 인자).

### 저장소 안전성

- 핀 파일을 만지는 모든 경로는 잠금 하나 아래에서 **읽기 → 줄 맞춤(sync) → 요청 변경 → 임시 파일에 쓰고 `os.replace` → `<state_dir>/pins.md` 재생성** 순서를 지킨다. 잠금이 없던 때는 핀 30건을 동시에 저장하면 2건만 남았다(실측).
- `pins.jsonl` 은 append-only 가 아니라 **전체를 다시 쓴다.** 상태 갱신 레코드를 덧붙이는 방식은 읽는 쪽이 매번 이벤트를 접어야 해서, 파일 하나가 곧 현재 상태인 편이 단순하고 틀릴 여지가 적다.
- id 는 `pins.seq` 로 발급하며 삭제·`clear` 뒤에도 다시 쓰지 않는다 — 채팅 속 '#2' 가 다른 핀을 가리키면 안 된다. 파일이 없으면 기동 때 한 번 기존 최대 id 로 채운다.
- 파싱할 수 없는 줄, 또는 JSON 이어도 `id`(정수)·`file`(문자열)·`lo`/`hi`(정수, `1 ≤ lo ≤ hi`)·`page`(있으면 정수)가 틀린 레코드는 건너뛰고 경고하며, 그 상태에서 처음 쓰기 전에 원본을 `pins.jsonl.corrupt-<시각>.bak` 으로 보존한다. 레코드 하나 때문에 GET 이 `500` 이 되지 않는다.
- `<state_dir>/pins.md` 를 메모리에서 먼저 만든 뒤 `pins.jsonl` → `<state_dir>/pins.md` 순으로 쓴다. 렌더가 실패하면 아무것도 쓰지 않는다 — 커밋한 뒤 `500` 을 주면 재시도가 중복 핀을 만든다.
- 되살리기(`restore`)는 `pins.jsonl` 쓰기가 성공한 뒤에만 삭제 기록에서 뺀다. 중간에 죽으면 최악이 '양쪽에 다 있음'(복구 가능)이지 '양쪽에 다 없음'이 아니다.

### 줄 번호 재동기화 (`anchor`)

**이 스킬을 쓰는 이유가 "에이전트가 원고를 고친다"인데, 고치면 핀이 죽는 구조는 쓸 수 없다.**
핀 하나를 처리해 세 줄을 넣는 순간 아래 핀이 전부 어긋난다.

그래서 핀을 저장할 때 블록의 **머리·꼬리 줄 텍스트**를 함께 떠 둔다(`anchor`, 순수 주석 줄은 건너뜀). 건너뛴 주석 줄 수는 `head_off`·`tail_off` 로 남겨, 앞뒤에 주석 줄을 일부러 넣은 핀도 줄 맞춤 뒤 범위가 줄지 않는다. 핀을 읽거나 쓰는 모든 요청은 대상 파일의 mtime 이 `synced_at` 보다 새로우면 그 텍스트를 다시 찾아 `lo`/`hi` 를 갱신한다. 줄이 움직이면 `rev` 가 오르므로, 옛 화면에서 보낸 수정은 `409` 로 걸러진다.

| 결과 | `sync` | 표시 |
| --- | --- | --- |
| 그대로 | `ok` | — |
| 밀림 | `moved +3` | 새 줄 번호로 갱신('줄 +3 이동') |
| 머리 줄이 원문에서 사라짐 | `lost` | `stale: true` — UI('위치 잃음')와 `<state_dir>/pins.md` 에 경고 |

`stale` 핀은 추측해서 닫지 않는다. 사용자에게 보고한다(사용자는 [수정] → 위치 다시 잡기로 고칠 수 있다).

## 뷰어 사용법 (사용자)

| 동작 | 방법 |
| --- | --- |
| 위치 고르기 | PDF 위 드래그 → 점선 '새 핀' 상자가 저장·취소 때까지 남는다. 다시 드래그해도 메모는 지워지지 않는다 |
| 범위 맞추기 | 사이드바의 단계 버튼(드래그한 줄 / 문단 / 환경 …)과 ▲+ ▲− ▼+ ▼− |
| 저장 | [핀 저장] 또는 메모 칸에서 ⌘↵ / Ctrl+Enter(한글 조합 중엔 무시). 알림의 [되돌리기] |
| 수정 | 카드의 메모를 누르거나 [수정] → 메모·범위 편집, [위치 다시 잡기] 로 PDF 에서 새 위치 지정 |
| 완료·삭제 | [완료]·[삭제] — 둘 다 알림의 [되돌리기]로 즉시 되돌린다. 닫힌 핀은 목록 아래 '닫힌 핀 N' 에서 [다시 열기] |
| PDF 다시 만들기 | 원고를 컴파일해 화면을 바꾼다(수십 초). '핀 다시 읽기' 는 핀 목록만 다시 읽는다 |
| 테마 | [◐] 시스템 → [☀] 밝게 → [☾] 어둡게. 설정은 브라우저에 저장된다 |
| 폭 | [폭] 이 쪽 폭을 왼쪽 화면에 맞춘다. 저장된 폭이 없는 첫 방문에서 화면보다 넓으면 자동으로 맞춘다 |
| 도움말 | `?` 키 또는 [?] — 흐름·단축키·용어·`<state_dir>/pins.md` 경로 |
| Esc | 열린 것부터 닫는다: 도움말 → 툴팁 → 위치 다시 잡기 → 편집 → 선택. 입력 칸에 있을 때는 툴팁을 닫는 데 한 번을 쓰지 않는다(메모 칸에서 Esc 한 번이면 선택이 취소된다) |

## 시작 전 — 포트 충돌 회피 (강제)

기존에 그 포트를 쓰는 프로세스가 있는지 먼저 확인한다. 확인 없이 바로 바인딩을 시도하지 않는다.

```bash
ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
```

- 점유돼 있으면: (a) `--port`를 지정하지 않았다면 서버가 자동으로 다음 빈 포트를 시도하게 하거나, (b) 점유 프로세스가 이 스킬의 이전 인스턴스인지 확인 후 재사용(같은 `--manuscript`면 기존 서버를 그대로 쓰고 새로 띄우지 않는다).
- 서버를 내릴 때 `pkill -f pin_server.py`로 죽이지 않는다 — 자기 자신의 명령줄까지 매칭해 무관한 세션을 죽일 위험이 있다. 포트로 PID를 찾아 종료한다: `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
- 새 버전 서버로 바꿔 띄울 때 상태 디렉토리는 그대로 둔다. 옛 레이아웃(`pages/`, `pins.jsonl`, `built_at.txt`, `head.txt`)을 `--no-build` 로도 재빌드 없이 읽는다. 기동 때 `pages.cur`(내용 `pages`)와 `pins.seq`(기존 최대 id)를 만들고 `<state_dir>/pins.md` 를 다시 그린다. 옛 `pages/` 는 다음 재빌드가 `pages-<build_id>/` 로 교체한 뒤 직전 1개로 남았다가 그다음 재빌드에서 지워진다.

## 보안 제약 (Hard Rule)

| 항목 | 규칙 |
| --- | --- |
| 바인딩 주소 | `127.0.0.1` 고정. `0.0.0.0`·와일드카드 바인딩 금지 — 인자로도 노출하지 않는다 |
| 외부 노출 | `tailscale serve`만 사용. **`tailscale funnel` 금지** — funnel은 공인 인터넷에 노출한다 |
| 노출 후 검증 | (1) 테일넷 안에서 그 URL에 `curl`하면 `200` 확인. (2) 공인 IP·테일넷 밖 경로로는 연결이 실패하는지 확인(즉 `tailscale serve status`가 "Funnel"이 아니라 "tailnet only"로 뜨는지) — 이 둘을 확인해야 "노출됐다"고 보고한다 |
| 인증 | 없음(테일넷 자체가 경계). 신원 헤더는 기록용이고, 필요하면 `--allow` 로 로그인 목록을 제한한다. 핀 데이터에 민감정보를 적지 않는다는 전제 |
| 요청 경계 | 응답 전에 본문을 끝까지 읽고 오류 뒤 연결을 닫는다(요청 밀반입 차단), `Transfer-Encoding` 거부, 교차 출처 `Origin`·낯선 `Host` 는 `403`, 본문 있는 POST 는 JSON 만 — §HTTP API |
| 경로 | 핀·스니펫이 가리킬 수 있는 파일은 `--manuscript` 트리 안뿐이다(밖이면 `400`) |
| 종료 | 세션 종료 시 `tailscale serve --https=<port> off` 등으로 노출을 내린다. 서버 프로세스 자체를 계속 띄워둘지는 사용자 판단(재사용 이점과 유휴 리소스 비용의 트레이드오프) |

## 핀 소비 절차 (에이전트)

1. `<state_dir>/pins.md` 한 장을 읽는다. 스니펫은 일부러 넣지 않는다 — 줄 범위만 있으면 에이전트가 원본을 `Read`로 직접 읽는 편이 항상 더 싸고 정확하다(스니펫은 그 시점의 스냅샷이라 원본과 어긋날 수 있다). `작성` 열로 누가 남긴 요청인지 구분한다.
2. 표의 각 행에서 `파일 L<lo>-L<hi>`를 `Read`로 열어 문맥을 확인하고, `메모` 열의 지시대로 고친다. 줄 번호는 `<state_dir>/pins.md` 갱신 시각 기준이므로, 앞선 핀을 고쳐 줄이 밀렸을 수 있으면 `GET /api/pins` 로 다시 맞춘 값을 받는다.
3. 처리한 핀은 개별 종료한다. 전체를 `/api/clear` 로 비우지 않는다 — 아직 처리 안 한 다른 핀까지 날아간다. 에이전트의 `curl` 은 헤더가 없으므로 `closed_by` 가 `로컬/에이전트` 로 남는다.

   ```bash
   curl -s -X POST http://127.0.0.1:<port>/api/pins/3/close
   ```
4. 한 세션에서 여러 핀을 처리했으면, 마지막에 `<state_dir>/pins.md`를 다시 읽어 열린 핀이 0인지 확인하고 사용자에게 보고한다.
5. 핀의 위치가 이미 존재하지 않거나(파일 삭제·섹션 이동, `stale`) 문맥이 메모와 안 맞으면, 추측해서 닫지 않고 사용자에게 보고한다.
6. 에이전트가 핀 메모·범위를 고쳐야 하면 `GET /api/pins` 로 `rev` 를 받아 `/edit` 에 `base_rev` 로 넣는다. `409` 면 최신 값을 다시 읽는다.

## 상태 파일 레이아웃

```
<state_dir>/
├── build/                    # rsync 사본 + latexmk 산출물 (원본 체크아웃 아님)
├── pages.cur                 # 지금 쪽 이미지 디렉토리 이름(포인터, 원자적 교체)
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
└── head.txt                  # 빌드 시점 커밋(짧은 해시) — 원고 repo가 git이면
```

## 알려진 제약

- SyncTeX 좌표 조회가 선택 영역 바로 바깥의 float를 잘못 물 수 있어(가장 가까운 노드 기준), 밀집 클러스터링 + 범위 사다리로 보정한다. 완전히 안전하지는 않다 — 결과의 `kind`가 `float`·`env:*`인데 사용자가 기대한 대상과 다르면 `raw_lo`/`raw_hi`(보정 전 원시 범위)를 참고해 재시도.
- 원고를 고친 뒤 PDF 를 다시 만들지 않으면, 화면(옛 PDF)과 원문 줄 번호가 어긋난 채로 pick 이 된다. 에이전트가 원고를 고쳤으면 먼저 PDF 다시 만들기.
- 여러 `.tex` 파일이 `\input`/`\include`로 쪼개져 있으면 SyncTeX이 빌드 사본 안의 개별 파일 경로를 반환한다 — 서버가 이를 `<manuscript_dir>` 기준 원본 경로로 되돌린다(§아키텍처 개요). 이 매핑이 깨지면(예: 빌드 사본과 원본의 디렉토리 구조가 다르면) 경로가 어긋난다.
- 앵커 재동기화는 **머리 줄이 원문에 남아 있을 때만** 작동한다. 그 문장 자체를 갈아엎으면
  `stale` 로 떨어진다 — 자동 복구가 아니라 표시가 목적이다. 빈 줄만 고른 핀은 앵커가 없어 따라가지 않는다.
- 같은 문장이 원고에 여러 번 나오면 원래 줄 번호에 가장 가까운 것을 고른다. 반복 구조가 많은
  원고에서는 틀릴 수 있다.
- 참고문헌 영역을 고르면 SyncTeX 이 `.bbl`(생성 파일)을 가리킨다. 서버가 이를 감지해 편집하지
  말라고 안내하고 선택을 거부한다.
- 렌더 텍스트 경로는 `pdftotext` 가 글자를 뽑을 수 있어야 한다. 그림 안에 래스터로 박힌 글자는
  잡히지 않으므로 그 영역은 SyncTeX 경로에만 의존한다.
- 다른 사람(에이전트)이 바꾼 핀은 [핀 다시 읽기] 를 눌러야 화면에 반영된다(자동 반영은 아직 없다).

## 연관 자산

- [`latex-build-fix`](../latex-build-fix/SKILL.md) — SyncTeX 빌드가 실패할 때 먼저 여기로.
- [`manuscript-revision`](../manuscript-revision/SKILL.md) — 핀을 닫으며 실제 원고를 고칠 때의 편집 규율.
- [`agent-operations.md`](../../rules/agent-operations.md) §4.1 — 원격 세션에서 결과물을 도달 가능한 주소로 서빙하는 일반 원칙(이 skill은 그 원칙의 예외다 — 여기는 `127.0.0.1` + `tailscale serve` 조합을 고정한다. 이유: PDF 뷰어가 즉석 markup 상태를 담고 있어 임의 바인딩보다 테일넷 경계 하나로 통제하는 편이 안전하다).
