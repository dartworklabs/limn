---
name: Manuscript Pin Picker
description: "LaTeX 원고 PDF를 브라우저에 띄우고 드래그로 고른 영역을 SyncTeX 역변환으로 .tex 파일·줄 번호로 되찾는다. 스크린샷 대신 파일:줄범위를 주고받아 토큰과 왕복을 줄인다. 원고 특정 위치를 지목해 수정을 요청하거나, 쌓인 핀을 에이전트가 처리할 때 활성화."
slash_command: true
---

# Manuscript Pin Picker

> **Activation**: 원고 PDF 의 특정 위치를 가리켜 수정을 요청할 때(스크린샷을 붙이려 할 때). 쌓인 핀을 처리할 때("핀 확인해줘", 세션 시작).

원고 PDF 위에서 영역을 드래그하면 SyncTeX 역변환으로 그 자리의 `.tex` 파일·줄 번호를 되찾아 메모와 함께 "핀"으로 쌓는다(핀 = 위치가 붙은 TODO). 스크린샷 한 장(1,000~1,600 토큰, 위치 불명) 대신 `manuscript_kr.tex L493-L501`(≈35 토큰) 한 줄을 받아 바로 읽고 고친다. 공저자도 같은 테일넷 주소로 핀을 남기고, 누가 남겼는지 기록된다.

쓰지 않는 경우: SyncTeX 빌드가 안 되면 [`latex-build-fix`](../latex-build-fix/SKILL.md) 먼저. 파일:줄을 이미 알면 바로 [`manuscript-revision`](../manuscript-revision/SKILL.md). Typst 원고는 범위 밖이다(SyncTeX 은 LaTeX 전용).

## 핀 처리 (에이전트)

`<base>` 는 원격이면 `https://<기기>.<tailnet>.ts.net:<port>`, 서버 머신이면 `http://127.0.0.1:<port>`.

1. **읽는다.** 원격: `curl -s <base>/pins.md`. 서버 머신: `<state_dir>/pins.md` 를 `Read`.
   - 표는 `| # | 쪽 | 위치 | 범위 | 메모 |`. `위치` 는 `--manuscript` 기준 상대경로 + `L<lo>-L<hi>`.
2. **기준 커밋을 맞춘다.** 머리줄 `기준: <head> · 빌드 <built_at>` 이 있고 다른 체크아웃에서 처리하면, `git rev-parse --short HEAD` 가 같은지 먼저 본다.
3. **처리 범위를 정한다.**
   - 부탁받은 쪽이 그 시점 열린 핀을 **전부** 처리한다. 누가 남겼는지와 무관하다(저자 결정 2026-09-22).
   - 사용자가 번호를 지목했으면 그 핀만.
   - `⏳<이름>`(다른 쪽이 claim)은 건너뛴다. 뺏지 않는다.
4. **claim 한다.** `curl -s -X POST <base>/api/pins/<id>/claim`. `409 claimed` 면 건너뛴다.
5. **고친다.** `L<lo>-L<hi>` 를 `Read` 로 열어 문맥을 확인하고 메모대로 고친다. 앞 핀을 고쳐 줄이 밀렸을 수 있으면 `GET <base>/api/pins` 로 맞춘 값을 다시 받는다.
6. **닫는다.** 무엇을 고쳤는지(`reply` ≤500자)와 PR 번호(`ref` ≤80자)를 남긴다.

   ```bash
   curl -s -X POST <base>/api/pins/3/close \
     -H 'Content-Type: application/json' \
     -d '{"reply": "제목을 …로 바꿈", "ref": "PR #227"}'
   ```

7. **확인한다.** 여러 핀을 처리했으면 1단계처럼 핀 표를 다시 읽는다. 열린 핀이 0(또는 전부 `⏳`)인지 확인해 사용자에게 보고한다.

### 기호

| 표시 | 뜻 | 할 일 |
| --- | --- | --- |
| `⊂#N` | `#N` 범위 안에 통째로 든다 | `#N` 과 한 번에 고치고 둘 다 닫는다 |
| `∩#N` | 일부만 겹친다 | 참고만 한다. 각자 처리해도 된다 |
| `⏳<이름>` | 다른 쪽이 유효한 claim 을 쥐었다 | 건너뛴다 |
| `✎` | 저장 뒤 메모·범위가 수정됐다 | — |
| `⚠` | 위치를 잃었다(stale) | 아래 stale 규칙 |
| `«…»` | 렌더된 글자 인용(≤60자, 잘리면 `…`) | 검색 힌트로만 쓴다. `Edit` 의 `old_string` 으로 쓰지 않는다 |
| `@작성자:` | 작성자가 2명 이상일 때 메모 앞에 붙는다 | 배정 기준이 아니다. 보고·`reply` 참고용 |

### 규칙

- stale(`⚠`): 방금 자신이 그 범위를 고쳤으면 원문을 확인하고 닫아도 된다. 아니면 추측해서 닫지 말고 보고한다.
- 위치가 사라졌거나(파일 삭제·섹션 이동) 문맥이 메모와 안 맞으면 닫지 말고 보고한다.
- `/api/clear` 금지. 처리 안 한 핀까지 날아간다. 하나씩 닫는다.
- 이미 닫힌 핀을 다시 닫으면 아무것도 안 바뀐다(`reply` 도 버려진다). 사유를 고치려면 `/reopen` 뒤 다시 `/close`.
- `close`·`drop` 이 claim 을 지운다. 처리를 포기하거나 넘길 때만 `/unclaim`.
- 메모·범위를 고칠 때는 `GET /api/pins` 의 `rev` 를 `/edit` 의 `base_rev` 로 보낸다. `409 conflict` 면 응답의 최신 `pin` 을 보고 다시 보낸다. 덧붙이기만 하면 `note_append`(`base_rev` 불필요).
- 원고를 고쳤으면 PDF 를 재빌드한다(`POST /api/rebuild?async=1`). 옛 PDF 위의 pick 은 줄 번호가 어긋난다.

## 서버 띄우기

1. **포트를 확인한다(강제).** 확인 없이 바인딩하지 않는다.

   ```bash
   ss -ltnp 2>/dev/null | grep ":<port> " || lsof -i tcp:<port>
   ```

   - 같은 `--manuscript` 의 이전 인스턴스면 그대로 쓴다. 새로 띄우지 않는다.
   - `--port` 를 빼면 서버가 빈 포트를 골라 기동 로그에 찍는다.
   - 내릴 때 `pkill -f pin_server.py` 금지. `pid=$(lsof -ti tcp:<port>); [ -n "$pid" ] && kill $pid`.
2. **실행한다.**

   ```bash
   uv run python3 .agents/skills/manuscript-pin-picker/scripts/pin_server.py \
     --manuscript <manuscript_dir> [--main <main>.tex] [--port <port>] [--git-pull]
   ```

   - `--git-pull`: 재빌드마다 업스트림을 `--ff-only` 로 당긴다. dirty·분기면 건너뛰고 빌드는 계속한다.
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
| `POST /api/pins/{id}/claim` | 처리 중 표시. 본문 `{"ttl_min": 1..480}`(기본 120) |
| `POST /api/pins/{id}/unclaim` | 처리 중 표시를 푼다 |
| `POST /api/pins/{id}/close` | 닫는다. 본문 `{"reply", "ref"}` |
| `POST /api/pins/{id}/reopen` | 다시 연다(옛 `reply`·`ref` 삭제) |
| `POST /api/pins/{id}/edit` | 메모·범위 수정(`base_rev` 필수) 또는 `note_append` |
| `POST /api/pins/{id}/drop` | 잘못 찍은 핀을 뺀다(`/restore` 로 되살림) |
| `POST /api/rebuild?async=1` | PDF 재빌드. 진행은 `GET /api/build` |
| `GET /api/meta?light=1` | 쓰기 없는 상태 조회(`stale_build` 등) |

## 참고 파일

| 할 일 | 열 파일 |
| --- | --- |
| 엔드포인트 전체, 요청 경계, edit·close·claim·겹침 상세, 핀 스키마, `<state_dir>/pins.md` 형식 | [`references/api.md`](references/api.md) |
| 재빌드(동기·비동기), `--git-pull`, 응답 다이어트, 자동 동기화, 위치 추정(`est`) | [`references/build-sync.md`](references/build-sync.md) |
| 아키텍처, 역변환 두 경로, 범위 사다리, 줄 맞춤(`anchor`), 저장 안전성, 작성자 귀속, 벡터 렌더링(PDF.js), PDF 영역 전용 확대, 알려진 제약 | [`references/design.md`](references/design.md) |
| 실행 인자 전체, 포트 회피, 보안 상세(Host·Origin 이유), systemd, `tailscale serve` 실측, 상태 파일, 뷰어 사용법 | [`references/operations.md`](references/operations.md) |

## 연관 자산

- [`manuscript-revision`](../manuscript-revision/SKILL.md) — 핀을 닫으며 원고를 고칠 때의 편집 규율.
- [`agent-operations.md`](../../rules/agent-operations.md) §4.1 — 결과물 서빙 일반 원칙. 이 스킬은 그 예외로 `127.0.0.1` + `tailscale serve` 를 고정한다([operations.md](references/operations.md) §보안 제약).
