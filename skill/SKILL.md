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
- 리뷰어 코멘트나 공동저자 피드백을 원고 PDF 위에 markup하듯 쌓아두고 싶을 때 (핀 = 위치가 붙은 TODO).
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
   ├─(2) 역변환 두 경로를 겨루게 한 뒤 환경/문단 경계로 확장 → 스니펫
   ├─(3) 사용자가 메모를 달아 "핀"으로 저장 → <state_dir>/pins.jsonl (append-only)
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
`score` 가 낮으면 서버가 경고 문구를 함께 돌려준다.

원본 체크아웃을 직접 열지 않고 rsync 사본에서 빌드하는 이유: 원고가 동시에 편집 중이어도 빌드가 중간 상태를 물지 않게 하기 위함이다. 빌드 사본의 경로를 원본 경로로 되돌리는 매핑(`build_dir → manuscript_dir`)은 서버가 내부적으로 처리하며, 에이전트에게는 항상 원본 경로가 보고된다.

## 인터페이스 (오케스트레이터가 구현 — 아래는 호출 계약)

스크립트 파일은 이 skill 디렉토리에 아직 없다. 아래는 오케스트레이터가 채워 넣을 **호출 인터페이스**다.

### `scripts/pin_server.py`

```bash
uv run python3 .agents/skills/manuscript-pin-picker/scripts/pin_server.py \
  --manuscript <manuscript_dir> \
  [--main <main-file>.tex] \
  [--port <port>] \
  [--state-dir <state_dir>] \
  [--dpi 150] \
  [--float-envs figure,table,algorithm,equation,align,itemize,enumerate] \
  [--build-timeout 900] \
  [--no-build]
```

| 인자 | 필수 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `--manuscript` | 예 | — | LaTeX 소스 루트 디렉토리(`<manuscript_dir>`). 프로젝트마다 다르므로 하드코딩 금지 |
| `--main` | 아니오 | 자동 탐지 | 빌드할 최상위 `.tex` 파일명. 생략 시 `--manuscript` 안에서 `\documentclass`를 포함한 `.tex` 파일을 찾는다. 0개 또는 2개 이상이면 후보 목록을 출력하고 종료(에러) — 추측하지 않는다 |
| `--port` | 아니오 | 자동 선택 | 미지정 시 §"포트 충돌 회피"에 따라 빈 포트를 탐색해 사용하고, 실제 선택된 포트를 기동 로그 첫 줄에 출력한다 |
| `--state-dir` | 아니오 | `${XDG_DATA_HOME:-~/.local/share}/manuscript-pin-picker/<slug>` | `<slug>`는 `--manuscript`의 절대경로를 정규화·해시한 값. 같은 머신에서 원고 A·B를 동시에 열어도 상태가 섞이지 않게 하기 위함(멀티 원고·멀티 worktree 안전) |
| `--dpi` | 아니오 | `150` | 페이지 PNG 렌더 해상도 |
| `--float-envs` | 아니오 | `figure,table,algorithm,equation,align,itemize,enumerate` | 드래그 선택을 감싸는 환경으로 인정할 `\begin{...}` 이름 목록 |
| `--build-timeout` | 아니오 | `900` | `latexmk` 빌드 subprocess 타임아웃(초) |
| `--no-build` | 아니오 | (끔) | 기동 시 재빌드를 건너뛴다. 산출물이 이미 있을 때 서버만 빨리 올리는 용도 — PDF 가 없으면 이 플래그와 무관하게 빌드한다 |

**바인딩은 `127.0.0.1` 고정이다 — 이 값을 바꾸는 플래그를 만들지 않는다.** (§보안 제약)

내부적으로 rebuild를 트리거하는 엔드포인트(`POST /api/rebuild`)는 위 `--manuscript`/`--main`/`--state-dir`를 그대로 재사용해 사본을 다시 rsync + `latexmk -pdf -synctex=1`로 빌드한다.

### 핀 CRUD 엔드포인트 (HTTP API, 서버 내부)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/meta` | 페이지 수, 빌드 시각, 원고 head, 열린 핀 수 |
| `POST` | `/api/pick` | 드래그 좌표(page, x0, y0, x1, y1) → `{file, lo, hi, kind, snippet}` |
| `GET` | `/api/pins` | 열린 핀 목록(JSON) |
| `POST` | `/api/pin` | 새 핀 추가 |
| `POST` | `/api/pins/{id}/close` | 핀 1건을 처리 완료로 표시(`done: true`). 레코드는 남고 `<state_dir>/pins.md` 의 접힌 목록으로 내려간다 |
| `POST` | `/api/pins/{id}/reopen` | 닫은 핀을 되돌린다 |
| `POST` | `/api/pins/{id}/drop` | 핀 1건을 아예 지운다(잘못 찍은 것) |
| `POST` | `/api/clear` | 전체를 아카이브(`pins_<timestamp>.jsonl.bak`)하고 비움 — 일괄 리셋 |
| `POST` | `/api/rebuild` | 원고 재빌드 + 페이지 재렌더 |

> `pins.jsonl` 은 append-only 가 아니라 **전체를 다시 쓴다.** 상태 갱신 레코드를 덧붙이는 방식은
> 읽는 쪽이 매번 이벤트를 접어야 해서, 파일 하나가 곧 현재 상태인 편이 단순하고 틀릴 여지가 적다.
> 크기도 수십 건 규모라 다시 쓰는 비용이 문제되지 않는다.

### 핀 레코드 스키마 (`pins.jsonl`, 한 줄 = 한 레코드)

```json
{"id": 3, "at": "2026-09-21 20:10:00", "page": 4, "file": "<절대경로>/introduction.tex",
 "lo": 120, "hi": 134, "raw_lo": 122, "raw_hi": 131, "kind": "paragraph", "via": "synctex",
 "score": 0.93, "note": "이 문단 톤을 낮춰줘", "frac": [0.12, 0.30, 0.55, 0.18],
 "anchor": {"head": "이 절에서는 소스 재선정 주기를...", "tail": "...효과가 관측된다."},
 "synced_at": 1758450000.0, "sync": "moved +3", "done": false}
```

### 줄 번호 재동기화 (`anchor`)

**이 스킬을 쓰는 이유가 "에이전트가 원고를 고친다"인데, 고치면 핀이 죽는 구조는 쓸 수 없다.**
핀 하나를 처리해 세 줄을 넣는 순간 아래 핀이 전부 어긋난다.

그래서 핀을 저장할 때 블록의 **머리·꼬리 줄 텍스트**를 함께 떠 둔다(`anchor`). `GET /api/pins`
는 대상 파일의 mtime 이 `synced_at` 보다 새로우면 그 텍스트를 다시 찾아 `lo`/`hi` 를 갱신한다.

| 결과 | `sync` | 표시 |
| --- | --- | --- |
| 그대로 | `ok` | — |
| 밀림 | `moved +3` | 새 줄 번호로 갱신 |
| 머리 줄이 원문에서 사라짐 | `lost` | `stale: true` — UI 와 `<state_dir>/pins.md` 에 경고 |

`stale` 핀은 추측해서 닫지 않는다. 사용자에게 보고한다.

## 시작 전 — 포트 충돌 회피 (강제)

기존에 그 포트를 쓰는 프로세스가 있는지 먼저 확인한다. 확인 없이 바로 바인딩을 시도하지 않는다.

```bash
ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
```

- 점유돼 있으면: (a) `--port`를 지정하지 않았다면 서버가 자동으로 다음 빈 포트를 시도하게 하거나, (b) 점유 프로세스가 이 스킬의 이전 인스턴스인지 확인 후 재사용(같은 `--manuscript`면 기존 서버를 그대로 쓰고 새로 띄우지 않는다).
- 서버를 내릴 때 `pkill -f pin_server.py`로 죽이지 않는다 — 자기 자신의 명령줄까지 매칭해 무관한 세션을 죽일 위험이 있다. 포트로 PID를 찾아 종료한다: `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.

## 보안 제약 (Hard Rule)

| 항목 | 규칙 |
| --- | --- |
| 바인딩 주소 | `127.0.0.1` 고정. `0.0.0.0`·와일드카드 바인딩 금지 — 인자로도 노출하지 않는다 |
| 외부 노출 | `tailscale serve`만 사용. **`tailscale funnel` 금지** — funnel은 공인 인터넷에 노출한다 |
| 노출 후 검증 | (1) 테일넷 안에서 그 URL에 `curl`하면 `200` 확인. (2) 공인 IP·테일넷 밖 경로로는 연결이 실패하는지 확인(즉 `tailscale serve status`가 "Funnel"이 아니라 "tailnet only"로 뜨는지) — 이 둘을 확인해야 "노출됐다"고 보고한다 |
| 인증 | 없음(테일넷 자체가 경계). 핀 데이터에 민감정보를 적지 않는다는 전제 |
| 종료 | 세션 종료 시 `tailscale serve --https=<port> off` 등으로 노출을 내린다. 서버 프로세스 자체를 계속 띄워둘지는 사용자 판단(재사용 이점과 유휴 리소스 비용의 트레이드오프) |

## 핀 소비 절차 (에이전트)

1. `<state_dir>/pins.md` 한 장을 읽는다. 스니펫은 일부러 넣지 않는다 — 줄 범위만 있으면 에이전트가 원본을 `Read`로 직접 읽는 편이 항상 더 싸고 정확하다(스니펫은 그 시점의 스냅샷이라 원본과 어긋날 수 있다).
2. 표의 각 행에서 `파일 L<lo>-L<hi>`를 `Read`로 열어 문맥을 확인하고, `메모` 열의 지시대로 고친다.
3. 처리한 핀은 개별 종료한다. 전체를 `/api/clear` 로 비우지 않는다 — 아직 처리 안 한 다른 핀까지 날아간다.

   ```bash
   curl -s -X POST http://127.0.0.1:<port>/api/pins/3/close
   ```
4. 한 세션에서 여러 핀을 처리했으면, 마지막에 `<state_dir>/pins.md`를 다시 읽어 열린 핀이 0인지 확인하고 사용자에게 보고한다.
5. 핀의 위치가 이미 존재하지 않거나(파일 삭제·섹션 이동) 문맥이 메모와 안 맞으면, 추측해서 닫지 않고 사용자에게 보고한다.

## 상태 파일 레이아웃

```
<state_dir>/
├── build/            # rsync 사본 + latexmk 산출물 (원본 체크아웃 아님)
├── pages/             # page-*.png (DPI별 재렌더)
├── pins.jsonl         # append-only 레코드
├── pins.md            # 에이전트 진입점 — 이 한 장만 읽는다
├── built_at.txt
└── head.txt           # 빌드 시점 커밋(짧은 해시) — 원고 repo가 git이면
```

## 알려진 제약

- SyncTeX 좌표 조회가 선택 영역 바로 바깥의 float를 잘못 물 수 있어(가장 가까운 노드 기준), 밀집 클러스터링 + 환경 경계 확장으로 보정한다. 완전히 안전하지는 않다 — 결과의 `kind`가 `float`인데 사용자가 기대한 대상과 다르면 `raw_lo`/`raw_hi`(보정 전 원시 범위)를 참고해 재시도.
- 여러 `.tex` 파일이 `\input`/`\include`로 쪼개져 있으면 SyncTeX이 빌드 사본 안의 개별 파일 경로를 반환한다 — 서버가 이를 `<manuscript_dir>` 기준 원본 경로로 되돌린다(§아키텍처 개요). 이 매핑이 깨지면(예: 빌드 사본과 원본의 디렉토리 구조가 다르면) 경로가 어긋난다.
- 앵커 재동기화는 **머리 줄이 원문에 남아 있을 때만** 작동한다. 그 문장 자체를 갈아엎으면
  `stale` 로 떨어진다 — 자동 복구가 아니라 표시가 목적이다.
- 같은 문장이 원고에 여러 번 나오면 원래 줄 번호에 가장 가까운 것을 고른다. 반복 구조가 많은
  원고에서는 틀릴 수 있다.
- 참고문헌 영역을 고르면 SyncTeX 이 `.bbl`(생성 파일)을 가리킨다. 서버가 이를 감지해 편집하지
  말라고 안내하고 선택을 거부한다.
- 렌더 텍스트 경로는 `pdftotext` 가 글자를 뽑을 수 있어야 한다. 그림 안에 래스터로 박힌 글자는
  잡히지 않으므로 그 영역은 SyncTeX 경로에만 의존한다.

## 연관 자산

- [`latex-build-fix`](../latex-build-fix/SKILL.md) — SyncTeX 빌드가 실패할 때 먼저 여기로.
- [`manuscript-revision`](../manuscript-revision/SKILL.md) — 핀을 닫으며 실제 원고를 고칠 때의 편집 규율.
- [`agent-operations.md`](../../rules/agent-operations.md) §4.1 — 원격 세션에서 결과물을 도달 가능한 주소로 서빙하는 일반 원칙(이 skill은 그 원칙의 예외다 — 여기는 `127.0.0.1` + `tailscale serve` 조합을 고정한다. 이유: PDF 뷰어가 즉석 markup 상태를 담고 있어 임의 바인딩보다 테일넷 경계 하나로 통제하는 편이 안전하다).
