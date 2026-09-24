---
name: manuscript-pin-picker
description: "LaTeX 원고 PDF를 브라우저에 띄우고 드래그로 고른 영역을 SyncTeX 역변환으로 .tex 파일·줄 번호로 되찾는다. 스크린샷 대신 파일:줄범위를 주고받아 토큰과 왕복을 줄인다. 원고 특정 위치를 지목해 수정을 요청하거나, 쌓인 핀을 에이전트가 처리할 때 활성화."
---

# Manuscript Pin Picker

> **Activation**: 원고 PDF 의 특정 위치를 가리켜 수정을 요청할 때(스크린샷을 붙이려 할 때). 쌓인 핀을 처리할 때("핀 확인해줘", 세션 시작).

원고 PDF 위에서 영역을 드래그하면 SyncTeX 역변환으로 그 자리의 `.tex` 파일·줄 번호를 되찾아 메모와 함께 "핀"으로 쌓는다(핀 = 위치가 붙은 TODO). 스크린샷 한 장(1,000~1,600 토큰, 위치 불명) 대신 `manuscript_kr.tex L493-L501`(≈35 토큰) 한 줄을 받아 바로 읽고 고친다. 공저자도 같은 테일넷 주소로 핀을 남기고, 누가 남겼는지 기록된다.

쓰지 않는 경우: SyncTeX 빌드가 안 되면 `latex-editing`으로 먼저 빌드를 고친다. 파일:줄을 이미 알면 바로 `manuscript-revision`으로 간다. Typst 원고는 범위 밖이다(SyncTeX 은 LaTeX 전용).

## 핀 처리 (에이전트)

`<base>` 는 원격이면 `https://<기기>.<tailnet>.ts.net:<port>`, 서버 머신이면 `http://127.0.0.1:<port>`.

1. **읽는다.** 원격: `curl -s <base>/pins.md`. 서버 머신: `<state_dir>/pins.md` 를 `Read`.
   - 표는 `| # | 쪽 | 위치 | 범위 | 메모 |`. `위치` 는 `--manuscript` 기준 상대경로 + `L<lo>-L<hi>`.
   - **문서가 여럿이면** 핀이 `## <문서 이름> · \`<키>\` · \`<경로>\`` 소절로 묶인다(본문·답변서·커버레터 등). 핀 번호는 문서를 가로질러 유일하다.
   - **보기 전용 PDF 소절**(`— 보기 전용 PDF(줄 번호 없음)`)의 핀은 줄이 없다. 위치 칸은 `쪽 N, 영역 …`, 메모 앞 `«…»` 는 그 영역의 글자다. 쪽·영역 글자·메모로 무엇을 가리키는지 판단하고 고칠 곳은 LaTeX 문서에서 찾는다. 못 찾으면 닫지 말고 보고한다.
   - **저장소를 확인한다(강제).** 머리줄 `논문: <이름표> · 저장소: <url>` 이 있으면 자기 체크아웃의 `git remote get-url origin` 과 같은지 본다. 다르면 다른 논문의 핀이니 처리하지 말고 멈추고 보고한다(여러 인스턴스가 동시에 돌 때의 안전판).
2. **기준 커밋을 맞춘다.** `기준: <head> · 빌드 <built_at>` 줄(단일 문서는 머리, 여러 문서는 소절마다)이 있고 다른 체크아웃에서 처리하면, `git rev-parse --short HEAD` 가 같은지 먼저 본다.
3. **처리 범위를 정한다.**
   - 부탁받은 쪽이 그 시점 열린 핀을 **전부** 처리한다. 누가 남겼는지와 무관하다(저자 결정 2026-09-22).
   - 사용자가 번호를 지목했으면 그 핀만.
   - **건너뛴다**: `처리 중(<이름>, …)`(다른 쪽이 claim — 뺏지 않는다), 맨 아래 `## 검토 대기` 소절의 핀(이미 처리했고 사람의 확인을 기다린다), 번호 칸에 `→ @이름` 이 붙은 핀(사람을 부른 핀 — 사용자가 그 핀을 명시적으로 시킬 때만 처리).
   - 번호 칸의 `질문` 은 고칠 곳이 아니라 물음이다(6단계). `다시 열림` 은 검토에서 되돌아온 핀이다 — 메모 칸의 `다시 연 이유` 대로 다시 고친다.
4. **고치기 직전에 그 핀만 claim 한다.** 여러 핀을 한꺼번에 잡지 않는다 — 아직 손대지 않은 핀까지 잠겨 다른 쪽이 못 가져간다(실측 2026-09-23: 23건을 한꺼번에 잡았다). 견적(분)을 `eta_min` 에 넣는다. 뷰어에 `처리 중 · 약 15분 · 20:40쯤` 으로 보인다.

   ```bash
   curl -s -X POST <base>/api/pins/<id>/claim -H 'Content-Type: application/json' -d '{"eta_min": 10}'
   ```

   | 고칠 것 | `eta_min` |
   | --- | --- |
   | 오타·단어 | 5 |
   | 문장 하나 | 5–10 |
   | 문단 다시 쓰기 | 10–20 |
   | 구조 변경·여러 곳 | 20–40 |
   | 재빌드로 확인해야 함 | 위에 +5 |

   - `409 claimed` 면 건너뛴다.
   - 늦어지면 같은 신원으로 다시 claim 해 새 견적을 넣는다(연장). 안 그러면 뷰어에 `예상보다 늦어짐 (+5분)` 이 뜬다.
   - 잠금은 `ttl_min`(생략하면 견적의 두 배, 30–120분)이 지나면 저절로 풀린다. 안전장치일 뿐이니 견적 대신 쓰지 않는다.
5. **고친다.** `L<lo>-L<hi>` 를 `Read` 로 열어 문맥을 확인하고 메모대로 고친다. 앞 핀을 고쳐 줄이 밀렸을 수 있으면 `GET <base>/api/pins` 로 맞춘 값을 다시 받는다.
6. **닫는다.** 에이전트가 닫은 핀은 완료가 아니라 **검토 대기**로 간다 — 사람이 뷰어에서 [확인]하면 완료, [다시 열기]면 이유와 함께 열린 핀으로 돌아온다.
   - **수정 요청 핀**: 고친 뒤 무엇을 고쳤는지(`reply` ≤500자)와 PR 번호·커밋(`ref` ≤80자)을 남겨 닫는다. `ref` 는 뷰어의 [변경 보기]가 그 커밋을 찾는 단서다.
   - **질문 핀**: 원고는 고치지 않는다(질문이 수정을 뜻할 때만). 답을 답글로 남긴 뒤 닫는다.
   - 테일넷 주소(`https://…ts.net`)로 닫으면 요청이 사람 신원을 달고 가 바로 완료가 된다 — 본문에 `"review": true` 를 넣는다(로컬 `127.0.0.1` 은 넣지 않아도 검토 대기).

   ```bash
   curl -s -X POST <base>/api/pins/3/close \
     -H 'Content-Type: application/json' \
     -d '{"reply": "제목을 …로 바꿈", "ref": "PR #227", "review": true}'
   curl -s -X POST <base>/api/pins/4/reply \
     -H 'Content-Type: application/json' \
     -d '{"text": "구간은 95% 신뢰구간이다. 0 을 포함하면 효과가 유의하지 않다는 뜻"}'
   ```

7. **확인한다.** 여러 핀을 처리했으면 1단계처럼 핀 표를 다시 읽는다. 열린 핀이 0(또는 전부 처리 중)인지 확인해 사용자에게 보고한다.

### 번호 칸의 표시

번호 칸에는 번호 뒤에 ` · ` 로 이어 뜻이 드러나는 짧은 말이 붙는다(예전 기호를 말로 바꿨다, [api.md](references/api.md) §pins.md 형식). 예: `7 · #6 범위 안 · 처리 중(에이전트 B, 약 10분)`.

| 표시 | 뜻 | 할 일 |
| --- | --- | --- |
| `#N 범위 안` | `#N` 범위 안에 통째로 든다 | `#N` 과 한 번에 고치고 둘 다 닫는다 |
| `#N과 같은 범위` | `#N` 과 줄 범위가 똑같다(같은 곳을 두 번 찍음) | `#N` 과 한 번에 고치고 둘 다 닫는다 |
| `#N과 일부 겹침` | 일부만 겹친다 | 참고만 한다. 각자 처리해도 된다 |
| `처리 중(<이름>, 약 N분)` | 다른 쪽이 유효한 claim 을 쥐었다(`예상 초과` 면 견적을 넘겼다) | 건너뛴다 |
| `수정됨` | 저장 뒤 메모·범위가 수정됐다 | — |
| `위치 잃음` | 위치를 잃었다(stale) | 아래 stale 규칙 |
| `«…»` | 렌더된 글자 인용(≤60자, 잘리면 `…`) | 검색 힌트로만 쓴다. `Edit` 의 `old_string` 으로 쓰지 않는다 |
| `@작성자:` | 작성자가 2명 이상일 때 메모 앞에 붙는다 | 배정 기준이 아니다. 보고·`reply` 참고용 |
| `질문` | 고칠 곳이 아니라 물음 | 답글로 답하고 닫는다(원고는 질문이 수정을 뜻할 때만) |
| `다시 열림` | 검토에서 되돌아왔다 | 메모 칸 `[스레드 N건] 다시 연 이유(…)` 대로 다시 고친다 |
| `→ @이름` | 사람을 부른 핀(@태그) | 사용자가 명시적으로 시키지 않으면 건너뛴다 |

### 규칙

- stale(`위치 잃음`): 방금 자신이 그 범위를 고쳤으면 원문을 확인하고 닫아도 된다. 아니면 추측해서 닫지 말고 보고한다.
- 위치가 사라졌거나(파일 삭제·섹션 이동) 문맥이 메모와 안 맞으면 닫지 말고 보고한다.
- `/api/clear` 금지. 처리 안 한 핀까지 날아간다. 하나씩 닫는다.
- 이미 닫힌 핀을 다시 닫으면 아무것도 안 바뀐다(`reply` 도 버려진다). 사유를 고치려면 `/reopen` 뒤 다시 `/close`.
- `close`·`drop` 이 claim 을 지운다. 처리를 포기하거나 넘길 때만 `/unclaim`.
- 메모·범위를 고칠 때는 `GET /api/pins` 의 `rev` 를 `/edit` 의 `base_rev` 로 보낸다. `409 conflict` 면 응답의 최신 `pin` 을 보고 다시 보낸다. 덧붙이기만 하면 `note_append`(`base_rev` 불필요).
- 원고를 고쳤으면 그 문서의 PDF 를 재빌드한다(`POST /api/rebuild?async=1&doc=<키>`, 단일 문서는 `doc` 생략). 옛 PDF 위의 pick 은 줄 번호가 어긋난다. 보기 전용 문서는 재빌드가 없다.

## 서버 띄우기

1. **포트를 확인한다(강제).** 확인 없이 바인딩하지 않는다.

   ```bash
   ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
   ```

   - 같은 `--manuscript` 의 이전 인스턴스면 그대로 쓴다. 새로 띄우지 않는다.
   - `--port` 를 빼면 서버가 빈 포트를 골라 기동 로그에 찍는다.
   - 내릴 때 `pkill -f pin_server.py` 금지. `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
   - **논문마다 뷰어 인스턴스가 따로 도는 머신**(dotfiles 의 `pin-viewer@<이름>` 템플릿 유닛이 있는 곳)에서는 직접 띄우지 말고 `pin-viewer add <이름> --manuscript <manuscript_dir>` 를 먼저 쓴다 — 포트를 자동 배정하고 상태 디렉토리를 논문별로 분리한다.
2. **실행한다.**

   ```bash
   uv run python3 .agents/skills/manuscript-pin-picker/scripts/pin_server.py \
     --manuscript <manuscript_dir> [--main <main>.tex] [--port <port>] [--git-pull] \
     [--label <이름표>] [--accent <#rrggbb>] [--doc <키>=<이름>:<경로> ...]
   ```

   - `--doc`(반복): 논문 저장소 하나의 문서 여럿을 한 뷰어·한 주소에서 선택한다. 데스크톱은 PDF 영역 위 문서 선택기, 모바일은 기존 도구 줄의 문서 버튼을 쓴다. `.tex` 는 LaTeX(빌드 루트는 그 폴더), `<빌드 루트>::<메인.tex>` 는 빌드 루트를 따로, `.pdf` 는 보기 전용. 경로는 `--manuscript` 기준. 없으면 `--main` 문서 하나(예전 그대로). 예시·규칙은 [operations.md](references/operations.md) §여러 문서.
   - `--git-pull`: 기동 직후와 60초마다 원격 main 을 확인하고 새 커밋이면 PDF를 다시 만든다. 수동 재빌드도 업스트림을 `--ff-only` 로 당긴다. 자동 동기화가 dirty·분기 등으로 막히면 화면에 사유를 표시한다.
   - `--label`·`--accent`: 여러 논문 뷰어를 동시에 열었을 때 탭·이름표 칩·파비콘으로 구분한다(§동시 인스턴스, [operations.md](references/operations.md)). 생략하면 `--manuscript` 의 git 저장소 이름 → 폴더 이름 순으로 기본값을 정한다.
   - 직접 띄울 때(위 `pin-viewer` 없이) **논문마다 `--state-dir` 과 포트를 따로 둔다** — 같은 값을 공유하면 핀이 섞인다.
   - 다른 인자·systemd 유닛·배포 사본은 [operations.md](references/operations.md).
3. **노출한다 — Hard Rule.**

| 항목 | 규칙 |
| --- | --- |
| 바인딩 | `127.0.0.1` 고정. `0.0.0.0` 금지. 바꾸는 플래그도 만들지 않는다 |
| 외부 노출 | `tailscale serve` 만. `tailscale funnel` 금지(공인 인터넷 노출) |
| 노출 보고 전 | 테일넷 안 `curl` 이 `200`, `tailscale serve status` 가 tailnet only |
| Host·Origin 검사 | 낯선 `Host`·교차 출처 `Origin` 은 `403`. `--no-origin-check` 는 탈출구 전용 |
| 인증 | 없다(테일넷이 경계). 막아야 하면 `--allow <login>,…` |
| 종료 | `tailscale serve --https=<port> off` |

## 자주 쓰는 API

| 경로 | 뜻 |
| --- | --- |
| `GET /pins.md` | 에이전트용 핀 표(원격 진입점) |
| `GET /api/pins` | 열린 핀 JSON(`rev` 포함). `?all=1` 이면 닫힌 핀까지 |
| `POST /api/pins/{id}/claim` | 처리 중 표시. 본문 `{"eta_min": 1..240, "ttl_min": 1..120}`(둘 다 선택, 상한을 넘으면 깎는다) — 견적과 잠금 |
| `POST /api/pins/{id}/unclaim` | 처리 중 표시를 푼다 |
| `POST /api/pins/{id}/close` | 닫는다. 본문 `{"reply", "ref", "review"}` — 에이전트가 닫으면 검토 대기 |
| `POST /api/pins/{id}/reply` | 답글 `{"text"}`(≤1000자). 상태는 그대로 |
| `GET /api/pins/{id}` | 핀 한 건(스레드 전부) — pins.md 가 스레드를 3건까지만 실을 때 |
| `POST /api/pins/{id}/confirm` | 검토 대기 → 완료(사람이 누른다) |
| `POST /api/pins/{id}/reopen` | 다시 연다(옛 `reply`·`ref` 삭제). 선택 `{"reason"}` 은 스레드에 남는다 |
| `POST /api/pins/{id}/edit` | 메모·범위 수정(`base_rev` 필수) 또는 `note_append` |
| `POST /api/pins/{id}/drop` | 잘못 찍은 핀을 뺀다(`/restore` 로 되살림) |
| `POST /api/rebuild?async=1` | PDF 재빌드. 진행은 `GET /api/build`. 여러 문서면 둘 다 `&doc=<키>` |
| `GET /api/docs` | 문서 목록(키·이름·종류·열린 핀 수·빌드 상태) |
| `GET /api/meta?light=1` | 쓰기 없는 상태 조회(`stale_build` 등). `&ev=<seq>` 면 나에게 온 이벤트(브라우저 알림용) |

## 참고 파일

| 할 일 | 열 파일 |
| --- | --- |
| 엔드포인트 전체, 요청 경계, edit·close·claim·겹침 상세, 스레드·검토 대기·@태그·이벤트, 핀 스키마, `<state_dir>/pins.md` 형식 | [`references/api.md`](references/api.md) |
| 재빌드(동기·비동기), `--git-pull`, 응답 다이어트, 자동 동기화, 위치 추정(`est`) | [`references/build-sync.md`](references/build-sync.md) |
| 스레드·검토 대기 화면, [변경 보기], @태그, 브라우저 알림(https 테일넷·127.0.0.1 에서만) | [`references/design.md`](references/design.md) |
| 아키텍처, 역변환 두 경로, 범위 사다리, 줄 맞춤(`anchor`), 저장 안전성, 작성자 귀속, 상태 표현(점·배지)·보관함·아이콘(Lucide), 여러 문서·보기 전용 PDF, 벡터 렌더링(PDF.js), PDF 영역 전용 확대, 알려진 제약 | [`references/design.md`](references/design.md) |
| 실행 인자 전체, `--doc` 여러 문서, 포트 회피, 보안 상세(Host·Origin 이유), systemd, `tailscale serve` 실측, 상태 파일, 뷰어 사용법 | [`references/operations.md`](references/operations.md) |

## 연관 자산

- `manuscript-revision` — 핀을 닫으며 원고를 고칠 때의 편집 규율.
- `writing-agent-ops` — 결과물 서빙 일반 원칙. 이 스킬은 그 예외로 `127.0.0.1` + `tailscale serve`를 고정한다([operations.md](references/operations.md) §보안 제약).
