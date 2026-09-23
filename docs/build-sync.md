# 재빌드·자동 동기화·위치 추정

PDF 재빌드, 뷰어 폴링, 점선 마크(`est`) 판정의 상세다. 엔드포인트 목록은 [api.md](api.md), 뷰어 조작은 [operations.md](operations.md) §뷰어 사용법.

## 자동 동기화 (가벼운 meta 폴링)

`GET /api/pins`·`GET /api/meta`(라이트 아닌 쪽)는 **쓰기 부작용**(`sync_all` 이 앵커로 줄을 다시 맞추고 파일에 쓴다)이 있어 그대로 폴링할 수 없다. 그래서 폴링 전용으로 `GET /api/meta?light=1` 을 쓴다 — `n_open`·`n_done` 이 빠지고 `live_pins`(sync) 를 부르지 않는다. 응답의 `pins_rev`(`pins.jsonl` 의 `f"{mtime_ns}:{size}"`, 없으면 `"0"`)와 `src_mtime`(§아래) 이 **바뀌었을 때만** 뷰어가 `GET /api/pins`(sync 있음)를 불러 목록을 다시 그린다 — 그래서 에이전트가 `curl` 로 핀을 닫거나 원고를 고쳐도 몇 초 안에 화면에 반영되면서도, 아무 변화가 없는 동안은 `pins.jsonl` 을 건드리지 않는다.

- `src_mtime`: `--manuscript` 아래 `*.tex`·`*.bib`·`*.sty`·`*.cls`·`*.bst`와 그림 확장자(`png`·`jpg`·`jpeg`·`pdf`·`eps`·`svg`)의 최대 mtime. 점(`.`)으로 시작하는 디렉토리, 빌드 산출물 디렉토리(`build/`·`out/`), **빌드 rsync 가 빼는 디렉토리(`diff/`·`diff_temporary/`)**, 메인 PDF(`<main>.pdf`)는 뺀다(2초 캐시, `force=True` 로 건너뛸 수 있다). 빌드 지문(§위치 추정)도 같은 파일 목록을 본다.
- `build_src_mtime`: 빌드를 **시작할 때** 캐시를 건너뛰고 실측한 `src_mtime` 값. 빌드가 `ok`·`ok_errors` 로 끝났을 때만 `<state_dir>/built_src_mtime.txt` 에 확정해 기록한다 — 빌드가 실패하면 화면은 옛 PDF 그대로이므로 이 값도, "원고 수정됨" 배지도 그대로 남아야 한다(옛 인스턴스는 파일이 없어 `null` — 이때 뷰어는 `built_at` 시각과 비교한다).
- 뷰어는 탭이 보이는 동안 5초마다, 그리고 `visibilitychange`(visible)·`focus` 때 라이트 meta 를 부른다. 탭을 숨기면 요청 자체를 보내지 않는다. 두 번 연속 실패하면 연결 끊김 배지를 띄운다.
- 서버가 `stale_build`(원고가 화면 빌드의 시작 시점 `src_mtime` 보다 2초 넘게 새로움)와 `src_age_s` 로 판정해 주면 "원고 수정됨 · N분 전" 배지가 뜨고, 이때만 [PDF 재빌드] 버튼이 강조된다. 브라우저 시계는 쓰지 않는다.
- **위치 추정(`.est`) 마크** — §위치 추정.
- **완료·삭제 알림 구분** — 목록이 다시 그려질 때 직전에 열려 있던 핀이 사라졌으면, `GET /api/pins?all=1` 응답(열림+닫힘)에 `done:true` 로 남아 있으면 "완료"로, 아예 없으면(다른 사람이 `/drop` 함) `GET /api/pins/dropped` 로 누가 지웠는지 찾아 "#N 을 〈이름〉 가 삭제함"으로 알린다. 옛 구현은 이 둘을 가리지 않고 전부 "완료"로 알려 공저자가 지운 핀도 작성자 화면에 "완료"로 떴다(실측).
- 다른 사람(에이전트)이 바꾼 핀은 이 폴링(5초)으로 몇 초 안에 저절로 반영된다. [핀 다시 읽기] 는 그 주기를 기다리지 않고 즉시 맞추는 용도로 남아 있다.

## 위치 추정 (`est`, 서버 판정)

핀 마크는 드래그 당시의 `frac`(쪽 대비 비율)에 고정된다. 그 좌표가 지금 화면의 PDF 와 안 맞을 수 있으면 점선(`.est`)으로 그린다. **판정은 서버가 하고** `GET /api/pins` 의 `est` 불리언으로 싣는다. 뷰어는 받은 값을 그대로 그린다.

- 빌드 신원: 빌드마다 `<state_dir>/builds.json` 에 `{build, src_hash, src_mtime, finished_at, seq}` 를 남긴다(성공 빌드 최근 200개). `build` 는 쪽 디렉토리 이름(`pages.cur` 값)이다. `src_hash` 는 빌드 사본의 원고 파일(`src_mtime` 과 같은 목록 — `diff/`·`diff_temporary/`·점 디렉토리·메인 PDF 제외)을 (상대경로, 내용)으로 해시한 값이다. mtime 은 넣지 않는다 — 내용이 같으면 레이아웃도 같다.
- 핀의 `pdf_build`: 핀을 만들 때와 위치를 다시 잡을 때(`loc` 에 `frac`), 드래그할 때 화면에 있던 빌드 id 를 남긴다(pick 응답의 `pdf_build`). 메모·범위 텍스트 편집은 바꾸지 않는다.
- `est = (pin.pdf_build ≠ 지금 빌드 그리고 두 빌드의 src_hash 가 다름) 또는 sync 가 moved/lost`. 해시가 없으면 빌드 시작 `src_mtime` 으로 비교하고, 그 빌드를 이력에서 못 찾으면 추정으로 본다(모르는 채 실선으로 그리는 편이 더 해롭다).
- `pdf_build` 가 없는 옛 핀(옛 필드명 `frac_build` 는 같은 뜻으로 읽는다)은 서버가 epoch 수치로 판정한다 — 찍은 시각 `at` < `built_at` 이고 지금 빌드를 시작할 때의 `src_mtime` > `at` 이면 추정. `edited_at` 은 보지 않는다.
- 왜 서버 판정인가: 뷰어가 벽시계(`at`/`edited_at` 대 `built_at`/`build_src_mtime`)로 판정하던 때 세 갈래로 틀렸다(독립 검증 실측). 시간대 없는 `at` 을 브라우저가 현지 시각으로 풀어 America/New_York 에서는 어긋난 마크가 실선으로, Pacific/Kiritimati 에서는 방금 찍은 핀이 점선으로 그려졌다. 메모만 고쳐도 꺼졌다. 원고를 고친 뒤 옛 PDF 위에서 찍은 핀은 판정에 들어가지 못했다. 지금은 Asia/Seoul·America/New_York·Pacific/Kiritimati 세 컨텍스트에서 같은 마크가 같은 결과다.
- 기동 때 이력에 없는 지금 빌드(옛 인스턴스가 만든 것)를 한 번 올린다. 원고가 그 빌드 뒤로 안 바뀌었으면(`src_mtime` ≤ 빌드 기준 시각) 지금 원고의 지문을 그 빌드의 지문으로 삼는다. 그래야 기동 뒤 첫 핀이 원고를 안 바꾼 재빌드에서 오탐되지 않는다.

## 비동기 재빌드 (`/api/rebuild?async=1` + `GET /api/build`)

동기 `/api/rebuild` 는 수십 초 동안 요청을 묶는다. `?async=1` 을 주면 빌드 잠금을 얻은 즉시 `202 {"state":"running"}` 을 돌려주고, 실제 빌드는 데몬 스레드에서 돈다(잠금·판정 로직은 동기 경로와 완전히 같다). 이미 도는 중이면 `409`.

끝난 빌드는 `build_seq`(서버가 빌드마다 1씩 올리는 수, 재기동 뒤에도 이어짐)로 센다. 뷰어는 자기가 처리한 seq 를 기억해, 라이트 meta 의 `build_seq` 가 다르면 5초 틈새에 시작~종료까지 끝나 `running` 을 한 번도 못 본 빌드도 알아채고 상세를 받는다. 완료 처리(화면 교체·토스트)는 seq 하나당 한 번이다. `GET /api/build` 조회는 **단일 비행**이다 — 1초 타이머·`visibilitychange`·`focus`·라이트 폴링이 한꺼번에 불러도 요청은 하나다(고치기 전: 숨은 탭이 돌아올 때 토스트 ×2). 새로 연 탭은 마지막 빌드가 `ok_errors`·`fail` 이면 토스트 없이 오류 패널을 연다.

진행 상황은 `GET /api/build` 를 1초마다 폴링해서 본다 — 단, **실제로 빌드가 도는 동안만** 돈다. 무조건 매초 때리지 않는다: (a) 이 탭에서 [PDF 재빌드]를 눌렀을 때, (b) 5초 라이트 meta 폴링이 `build.state==='running'`(다른 세션·에이전트가 `curl` 로 시작한 빌드)을 봤을 때, (c) 부팅 시 이미 도는 빌드가 있는지 한 번 확인할 때만 1초 폴러가 켜지고, `state` 가 더 이상 `running` 이 아니면 스스로 멈춘다. 탭이 숨어 있으면 폴링 요청 자체를 보내지 않는다(포커스·`visibilitychange` 로 다시 켠다).

- `phase` 는 (`--git-pull` 일 때만) `pull`(업스트림 당겨오는 중) → `copy`(원고 사본을 만드는 중) → `latex`(latexmk) → `render`(pdftoppm) 순서다. 퍼센트는 만들지 않는다(모른다).
- `elapsed_s` 는 지금까지 걸린 시간, `last_s` 는 지난 빌드가 걸린 시간(진행 중 참고용)이다.
- 끝나면(`state` 가 `ok`·`ok_errors`·`fail`) 뷰어가 동기 경로와 같은 방식으로 제자리 교체를 한다. `ok_errors`·`fail` 이면 오류 패널(`#build-err`)이 **자동으로 열린다** — 토스트에만 의존하지 않는다(토스트는 6초면 사라지고, 그 뒤엔 다시 볼 길이 없었다). 패널을 닫아도 상태줄에 "빌드 오류 · 다시 보기" 칩이 남아, `LAST_BUILD_ERR` 이 있는 동안(다음 성공 빌드 전까지) 언제든 다시 열 수 있다.
- 다른 사람이 시작한 빌드도 같은 방식으로 잡아내므로, 페이지를 새로 열었을 때 빌드가 돌고 있으면 진행 칩이 이어서 보인다.
- 빌드 중(`phase=latex`)에도 pick 은 막지 않고, 응답 `warn` 에 "빌드 중이라 결과가 흔들릴 수 있습니다"를 붙인다.

## 재빌드 (`/api/rebuild`, 동기)

잠금 하나로 한 번에 하나만 돈다. 이미 빌드 중이면 기다리지 않고 `409 {"ok": false, "busy": true}`.

| `state` | 조건 | 화면 |
| --- | --- | --- |
| `ok` | 새 PDF 가 나왔고 LaTeX 로그에 `! ` 줄이 없음 | 새 쪽으로 교체 |
| `ok_errors` | 새 PDF 는 나왔지만 `! ` 줄이 있음(nonstopmode 의 `\undefinedmacro` 등) | 새 쪽으로 교체 + 오류 알림 |
| `fail` | 새 PDF 가 없거나(PDF mtime < 시작 시각) 시간 초과 | **이전 쪽 그대로** |

응답: `{"ok": <state≠fail>, "state", "errors": [{"line", "msg"}], "log", "elapsed_s", "head", "pull"}`, 성공하면 `pages`(새 쪽 수)도. `errors` 는 `! ` 줄과 그 뒤 `l.<n>` 줄을 최대 5건. `head` 는 그 빌드가 컴파일한 커밋의 짧은 해시(성공 때만, `<state_dir>/head.txt` 와 같은 값). `pull` 은 `--git-pull` 일 때만 채워진다 — 아래 §`--git-pull`. `log` 는 §에이전트 응답 다이어트를 따른다.

쪽 이미지는 새 디렉토리 `pages-<build_id>/` 에 먼저 그린 뒤 포인터 파일 `pages.cur` 를 원자적으로 바꾼다 — 빌드 중에도, 전환 직후 옛 URL 로도 쪽 요청이 끊기지 않는다. 뷰어는 새로고침 없이 보던 쪽과 쓰던 메모를 유지한 채 이미지만 바꾼다.

## `--git-pull`: 재빌드 전에 원격 main 당겨오기

공저자가 PR 을 머지해도 서버 쪽 원고 체크아웃은 그대로였다 — 뷰어가 옛 원고를 계속 보여줬다. `--git-pull` 을 켜면 모든 재빌드(동기·비동기 모두)가 copy 단계 전에 `pull` phase 를 돈다.

1. `--manuscript` 가 속한 git 저장소 루트를 찾는다(`git -C <ms> rev-parse --show-toplevel`). 아니면 `skipped:not_git`.
2. `git fetch --quiet`(업스트림 원격, timeout 30초). 실패·시간 초과면 `error:fetch_failed`/`error:fetch_timeout`.
3. 현재 브랜치에 upstream(`@{u}`)이 없으면 `skipped:no_upstream`.
4. `git status --porcelain --untracked-files=no` 가 비어 있지 않으면 `skipped:dirty`.
5. `git merge --ff-only @{u}` — 분기했으면(실패) `skipped:diverged`. 리베이스·머지 커밋을 대신 만들지 않는다.
6. 결과 `{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}` 가 빌드 결과(`/api/rebuild` 응답·`/api/build`·`builds.json` 마지막 결과)의 `pull` 필드에 실린다. `ok` 는 fast-forward 로 커밋이 바뀜, `up_to_date` 는 저장소는 정상이지만 새 커밋이 없었음이다.

**pull 이 `skipped`·`error` 여도 빌드는 지금 체크아웃으로 계속한다** — pull 은 있으면 좋은 것이지 빌드의 전제조건이 아니다. 모든 git 호출은 `subprocess.run([...])` 로 쉘 없이 돌고, 인자에 사용자 입력을 넣지 않는다. 뷰어는 pull 이 `skipped`/`error` 면 빌드 완료 토스트에 사유를 한 줄 붙이고(`git pull 건너뜀(dirty)` 등), `ok` 면 `원격 반영 <head_before>→<head_after>` 를 붙인다. `up_to_date` 는 알릴 변화가 없으므로 덧붙이지 않는다.

## 에이전트 응답 다이어트

동기 `/api/rebuild` 는 성공 때도 `log` 에 폰트 경로 등으로 수 KB가 실려 에이전트 토큰을 낭비했다. 지금은 `state=="ok"` 면 `log`(`/api/rebuild`)·`log_tail`(`GET /api/build`)을 응답에서 뺀다. `ok_errors`·`fail` 이면 마지막 40줄로 줄인다. `?log=1` 을 붙이면(둘 다) 다이어트를 끄고 전체 꼬리(4000자)를 그대로 받는다 — 뷰어의 오류 패널은 이 플래그를 항상 붙여 동작이 그대로다. 내부 상태(`BUILD_STATE`·`builds.json`)는 다이어트와 무관하게 풀 로그를 보관한다.
