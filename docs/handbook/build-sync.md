# 빌드·자동 동기화·위치 추정

Limn은 원고를 PDF로 빌드해 쪽 이미지로 보여 주고, 그 위에 핀을 찍는다. 원고와 핀은 사람과 에이전트가 동시에 바꾼다. 그래서 세 가지를 맞춰야 한다. 화면의 PDF가 언제 새로 빌드되는지, 다른 사람이 바꾼 핀과 원고가 화면에 어떻게 들어오는지, 옛 PDF 위에서 찍은 핀 좌표를 믿어도 되는지다. 이 문서는 그 세 가지를 다룬다.

재빌드 흐름, 빌드 상태, 폴링 주기, 점선 마크(`est`) 판정을 바꿀 때 이 문서를 읽고 같은 diff에서 고친다. 엔드포인트 목록과 응답 필드 전체는 [api.md](api.md) 에 있다. 뷰어 조작은 [operations.md](operations.md) §뷰어 사용법에 있다.

구현은 두 곳이다. 빌드 자체(원고 복사, latexmk, pdftoppm, 쪽 디렉토리 교체, 빌드 상태, 빌드 이력 `builds.json`, 원고 지문과 `src_mtime`)는 [`src/limn/build.py`](../../src/limn/build.py) 가 맡는다. 이 모듈은 문서와 설정(`BuildConfig`: 상태 폴더, dpi, 시간 제한)을 인자로 받고, 실행 인자 `C` 나 "지금 요청의 문서"(`cur_doc()`)를 읽지 않는다. 문서별 잠금·빌드 상태·이력 잠금·`src_mtime` 캐시는 문서 객체(`Doc`)가 갖고 있다. [`src/limn/server.py`](../../src/limn/server.py) 는 문서를 받아 이 인스턴스의 설정으로 빌드를 묶는 연결(`build_all(D)`, `build_async(D)`, `_build(D)`; 2026-09-26부터 셸 없이 문서를 인자로 받는다), `--git-pull`(`git_pull_phase`, 저장소 단위로 나눠 쓰는 `repo_pull`), 원격 main 감시(`sync_main_once`), 보기 전용 PDF 다시 그리기(`_render_pdf_doc`)를 맡는다. `--git-pull` 과 보기 전용 그리기는 빌드에 단계로 넘겨진다.

> **한눈에**
>
> 재빌드는 동기(`POST /api/rebuild`)와 비동기(`?async=1` + `GET /api/build`) 두 경로가 같은 빌드 함수를 쓴다. `--git-pull` 을 켜면 빌드 전에 원격 main을 fast-forward로 당긴다. 에이전트용 응답은 로그를 줄여 보낸다. 뷰어는 쓰기가 없는 라이트 meta를 5초마다 폴링해 변화가 있을 때만 핀을 다시 읽는다. 핀 마크를 실선으로 그릴지 점선으로 그릴지는 서버가 빌드 지문으로 판정한다. 보기 전용 PDF는 빌드 대신 파일 변화를 감시한다.

## 재빌드 (동기)

`POST /api/rebuild` 는 원고를 다시 빌드하고 끝날 때까지 기다린다. 잠금 하나로 한 번에 하나만 돈다. 이미 빌드 중이면 기다리지 않고 `409 {"ok": false, "busy": true}` 를 준다.

여러 문서(`--doc`)면 잠금, 빌드 상태(`GET /api/build?doc=`), 빌드 이력, `build_seq` 가 **문서마다** 따로다. 그래서 서로 다른 문서는 동시에 빌드된다. 빌드 폴더가 문서마다 따로라 서로의 `.aux` 를 밟지 않는다. `--git-pull` 은 저장소 단위로 한 번이다(§재빌드 전 원격 main 당겨오기 (`--git-pull`)).

### 빌드 상태

| `state` | 조건 | 화면 |
| --- | --- | --- |
| `ok` | 새 PDF가 나왔고 LaTeX 로그에 `! ` 줄이 없다 | 새 쪽으로 교체 |
| `ok_errors` | 새 PDF는 나왔지만 `! ` 줄이 있다(nonstopmode의 `\undefinedmacro` 등) | 새 쪽으로 교체 + 오류 알림 |
| `fail` | 새 PDF가 없거나(PDF mtime < 시작 시각) 시간 초과 | **이전 쪽 그대로** |

비동기 조회(`GET /api/build`)에는 빌드 전의 `idle` 과 진행 중인 `running` 이 더 있다(§비동기 재빌드).

### 응답

응답은 `{"ok": <state≠fail>, "state", "errors": [{"line", "msg"}], "log", "elapsed_s", "head", "pull"}` 이다. 성공하면 `pages`(새 쪽 수)도 붙는다.

| 필드 | 뜻 |
| --- | --- |
| `errors` | `! ` 줄과 그 뒤 `l.<n>` 줄을 최대 5건 |
| `head` | 그 빌드가 컴파일한 커밋의 짧은 해시. 성공 때만 있고 `<state_dir>/head.txt` 와 같은 값이다 |
| `pull` | `--git-pull` 일 때만 채워진다(§재빌드 전 원격 main 당겨오기 (`--git-pull`)) |
| `log` | §에이전트 응답 다이어트를 따른다 |

### 쪽 교체

쪽 이미지는 새 디렉토리 `pages-<build_id>/` 에 먼저 그린다. 그다음 포인터 파일 `pages.cur` 를 원자적으로 바꾼다. 그래서 빌드 중에도, 전환 직후 옛 URL로도 쪽 요청이 끊기지 않는다. 뷰어는 새로고침 없이 이미지만 바꾼다. 보던 쪽과 쓰던 메모는 그대로 유지한다.

## 비동기 재빌드

동기 `/api/rebuild` 는 수십 초 동안 요청을 묶는다. `POST /api/rebuild?async=1` 을 주면 빌드 잠금을 얻은 즉시 `202 {"state":"running"}` 을 돌려준다. 실제 빌드는 데몬 스레드에서 돈다. 잠금과 판정 로직은 동기 경로와 완전히 같다. 이미 도는 중이면 `409` 다.

### 끝난 빌드 세기 (`build_seq`)

끝난 빌드는 `build_seq` 로 센다. 서버가 빌드마다 1씩 올리는 수이고, 재기동 뒤에도 이어진다.

- 뷰어는 자기가 처리한 seq를 기억한다. 라이트 meta의 `build_seq` 가 그와 다르면 상세를 받는다. 그래서 5초 폴링 틈새에 시작부터 끝까지 끝나 `running` 을 한 번도 못 본 빌드도 알아챈다.
- 완료 처리(화면 교체, 토스트)는 seq 하나당 한 번이다.
- `GET /api/build` 조회는 **단일 비행**이다. 1초 타이머, `visibilitychange`, `focus`, 라이트 폴링이 한꺼번에 불러도 요청은 하나만 나간다. 고치기 전에는 숨은 탭이 돌아올 때 토스트가 두 번 떴다.
- 새로 연 탭은 마지막 빌드가 `ok_errors`·`fail` 이면 토스트 없이 오류 패널을 연다.

### 진행 폴링

진행 상황은 `GET /api/build` 를 1초마다 폴링해서 본다. 단 **실제로 빌드가 도는 동안만** 돈다. 1초 폴러는 다음 세 경우에만 켜진다.

1. 이 탭에서 [PDF 재빌드]를 눌렀을 때
2. 5초 라이트 meta 폴링이 `build.state==='running'` 을 봤을 때. 다른 세션이나 에이전트가 `curl` 로 시작한 빌드다.
3. 부팅 때 이미 도는 빌드가 있는지 한 번 확인할 때

`state` 가 더 이상 `running` 이 아니면 폴러는 스스로 멈춘다. 탭이 숨어 있으면 폴링 요청 자체를 보내지 않고, 포커스나 `visibilitychange` 로 다시 켠다.

`GET /api/build` 응답의 진행 필드는 다음과 같다.

- `phase` 는 `pull`(업스트림 당겨오는 중, `--git-pull` 일 때만) → `copy`(원고 사본을 만드는 중) → `latex`(latexmk) → `render`(pdftoppm) 순서다. 퍼센트는 만들지 않는다. 알 수 없기 때문이다.
- `elapsed_s` 는 지금까지 걸린 시간, `last_s` 는 지난 빌드가 걸린 시간이다. `last_s` 는 진행 중에 참고용으로 쓴다.
- 서버를 다시 띄워도 마지막 빌드 결과(`state`, `errors`, `log_tail`, `seq`, `head`, `pull`)는 `builds.json` 에서 되살린다.

### 끝났을 때

- `state` 가 `ok`·`ok_errors`·`fail` 이 되면 뷰어는 동기 경로와 같은 방식으로 제자리 교체를 한다.
- `ok_errors`·`fail` 이면 오류 패널(`#build-err`)이 **자동으로 열린다.** 토스트에만 의존하지 않는다. 토스트는 6초면 사라지고, 그 뒤에는 다시 볼 길이 없었다.
- 패널을 닫아도 상태줄에 "빌드 오류 · 다시 보기" 칩이 남는다. `LAST_BUILD_ERR` 이 있는 동안, 즉 다음 성공 빌드 전까지 언제든 다시 열 수 있다.
- 다른 사람이 시작한 빌드도 같은 방식으로 잡아낸다. 그래서 페이지를 새로 열었을 때 빌드가 돌고 있으면 진행 칩이 이어서 보인다.
- 빌드 중(`phase=latex`)에도 pick은 막지 않는다. 대신 응답 `warn` 에 "빌드 중이라 결과가 흔들릴 수 있습니다"를 붙인다.

## 재빌드 전 원격 main 당겨오기 (`--git-pull`)

공저자가 PR을 머지해도 서버 쪽 원고 체크아웃은 그대로였다. 그래서 뷰어가 옛 원고를 계속 보여 줬다. `--git-pull` 은 이 틈을 메운다.

### 자동 확인

`--git-pull` 을 켜면 기동 직후와 이후 60초마다 원격 main을 확인한다.

- 새 커밋을 fast-forward 하면 각 LaTeX 문서의 PDF 재빌드를 예약한다.
- 현재 커밋과 PDF 기준 커밋이 다르면 기동 때도 재빌드한다. `--no-build` 를 줬어도 그렇다.
- 다른 빌드가 진행 중이면 3초 뒤 다시 확인한다.
- 작업 트리가 더럽거나, 분기했거나, 업스트림이 없거나, 원격 오류가 나면 상단 상태 칩에 사유를 보이고 이전 PDF를 유지한다.
- 자동 확인은 현재 브랜치가 `main` 이고 업스트림도 `*/main` 일 때만 fast-forward 한다. 다른 브랜치는 `blocked:not_main` 으로 보인다.
- 보기 전용 PDF 문서는 Git pull 뒤 LaTeX 재빌드 대상이 아니다.

수동 재빌드(동기·비동기)도 copy 전에 같은 `pull` phase를 돈다.

> **주의**
>
> 서버가 쓰는 원고 체크아웃은 별도로 깨끗하게 유지해야 한다. 그 체크아웃에서 직접 작업하면 `skipped:dirty` 로 pull이 멈춘다.

### pull 단계

1. `--manuscript` 가 속한 git 저장소 루트를 찾는다(`git -C <ms> rev-parse --show-toplevel`). 저장소가 아니면 `skipped:not_git`.
2. `git fetch --quiet` 로 업스트림 원격을 받는다(timeout 30초). 실패하면 `error:fetch_failed`, 시간을 넘기면 `error:fetch_timeout`.
3. 현재 브랜치에 upstream(`@{u}`)이 없으면 `skipped:no_upstream`.
4. `git status --porcelain --untracked-files=no` 가 비어 있지 않으면 `skipped:dirty`.
5. `git merge --ff-only @{u}` 를 한다. 분기해서 실패하면 `skipped:diverged`. 리베이스나 머지 커밋을 대신 만들지 않는다.
6. 결과 `{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}` 를 빌드 결과의 `pull` 필드에 싣는다. 빌드 결과란 `/api/rebuild` 응답, `/api/build`, `builds.json` 의 마지막 결과다.

`state` 가 `ok` 면 fast-forward로 커밋이 바뀐 것이다. `up_to_date` 는 저장소는 정상이지만 새 커밋이 없었다는 뜻이다.

### 여러 문서에서의 pull

여러 문서면 pull을 잠금 하나로 줄 세운다. 20초 안에 다른 문서의 빌드가 이미 당겼으면 다시 당기지 않는다. 그 결과를 재사용하고 `shared: true` 를 붙인다. 그래서 두 문서를 동시에 재빌드해도 fetch·merge가 겹치지 않는다(`.git/index.lock`). 한 문서가 복사하는 중에 트리가 바뀌지도 않는다. 단일 문서는 예전처럼 빌드마다 당긴다.

### pull이 실패해도 빌드는 계속한다

pull이 `skipped`·`error` 여도 빌드는 지금 체크아웃으로 계속한다. pull은 있으면 좋은 것이지 빌드의 전제조건이 아니다.

모든 git 호출은 `subprocess.run([...])` 으로 쉘 없이 돈다. 인자에 사용자 입력을 넣지 않는다.

뷰어는 pull 결과를 빌드 완료 토스트에 한 줄 덧붙인다.

| pull `state` | 토스트에 붙는 줄 |
| --- | --- |
| `skipped`·`error` | 사유(`git pull 건너뜀(dirty)` 등) |
| `ok` | `원격 반영 <head_before>→<head_after>` |
| `up_to_date` | 없음. 알릴 변화가 없다 |

## 에이전트 응답 다이어트

동기 `/api/rebuild` 는 성공 때도 `log` 에 폰트 경로 등 수 KB를 실어 에이전트 토큰을 낭비했다. 지금은 빌드 상태에 따라 로그를 줄인다. 대상은 `/api/rebuild` 의 `log` 와 `GET /api/build` 의 `log_tail` 이다.

| 상태 | 응답의 로그 |
| --- | --- |
| `ok` | 빠진다 |
| `ok_errors`·`fail` | 마지막 40줄 |
| `?log=1` 을 붙인 요청(두 경로 모두) | 다이어트 없이 전체 꼬리(4000자) |

뷰어의 오류 패널은 `?log=1` 을 항상 붙인다. 그래서 뷰어 동작은 그대로다. 내부 상태(`BUILD_STATE`, `builds.json`)는 다이어트와 무관하게 전체 로그를 보관한다.

## 자동 동기화 (가벼운 meta 폴링)

에이전트가 `curl` 로 핀을 닫거나 원고를 고치면 몇 초 안에 뷰어 화면에 반영돼야 한다. 그런데 `GET /api/pins` 와 라이트가 아닌 `GET /api/meta` 는 **쓰기 부작용**이 있다. `sync_all` 이 앵커로 줄을 다시 맞추고 파일에 쓰기 때문이다. 그래서 이 둘을 그대로 폴링할 수는 없다.

폴링에는 `GET /api/meta?light=1` 을 쓴다. 라이트 meta는 `n_open`·`n_done` 이 빠지고 `snapshot_pins()`(sync 쓰기)를 부르지 않는다. 뷰어는 응답의 두 값이 **바뀌었을 때만** `GET /api/pins`(sync 있음)를 불러 목록을 다시 그린다.

- `pins_rev`: `pins.jsonl` 의 `f"{mtime_ns}:{size}"`. 파일이 없으면 `"0"`.
- `src_mtime`: 아래에서 설명한다.

그래서 변화는 몇 초 안에 화면에 들어오고, 아무 변화가 없는 동안은 `pins.jsonl` 을 건드리지 않는다.

### 원고 변화 감지

- **`src_mtime`** 은 `--manuscript` 아래 원고 파일의 최대 mtime이다. 대상은 `*.tex`·`*.bib`·`*.sty`·`*.cls`·`*.bst` 와 그림 확장자(`png`·`jpg`·`jpeg`·`pdf`·`eps`·`svg`)다. 제외하는 것은 다음과 같다.
  - 점(`.`)으로 시작하는 디렉토리
  - 빌드 산출물 디렉토리(`build/`·`out/`)
  - **빌드 rsync가 빼는 디렉토리(`diff/`·`diff_temporary/`)**
  - 메인 PDF(`<main>.pdf`)

  값은 2초 캐시하고, `force=True` 로 캐시를 건너뛸 수 있다. 빌드 지문(§위치 추정 (`est`))도 같은 파일 목록을 본다.
- **`build_src_mtime`** 은 빌드를 **시작할 때** 캐시를 건너뛰고 실측한 `src_mtime` 이다. 빌드가 `ok`·`ok_errors` 로 끝났을 때만 `<state_dir>/built_src_mtime.txt` 에 확정해 기록한다. 빌드가 실패하면 화면은 옛 PDF 그대로이므로, 이 값과 "원고 수정됨" 배지도 그대로 남아야 하기 때문이다. 옛 인스턴스는 이 파일이 없어 값이 `null` 이다. 이때 뷰어는 `built_at` 시각과 비교한다.
- **`stale_build`·`src_age_s`** 는 서버가 판정한다. `stale_build` 는 원고가 화면 빌드의 시작 시점 `src_mtime` 보다 2초 넘게 새로운지다. 판정이 참이면 "원고 수정됨 · N분 전" 배지가 뜨고, 이때만 [PDF 재빌드] 버튼이 강조된다. 브라우저 시계는 쓰지 않는다.

### 폴링 주기와 연결 끊김

- 뷰어는 탭이 보이는 동안 5초마다 라이트 meta를 부른다. `visibilitychange`(visible)와 `focus` 때도 부른다.
- 탭을 숨기면 요청 자체를 보내지 않는다.
- 두 번 연속 실패하면 연결 끊김 배지를 띄운다.
- 다른 사람이나 에이전트가 바꾼 핀은 이 5초 폴링으로 몇 초 안에 저절로 반영된다. [핀 다시 읽기]는 그 주기를 기다리지 않고 즉시 맞추는 용도로 남아 있다.
- 점선 마크(`.est`)의 판정은 §위치 추정 (`est`)에 있다.

### 완료와 삭제 알림 구분

목록을 다시 그릴 때 직전에 열려 있던 핀이 사라졌으면, 뷰어는 사라진 이유를 가려 알린다.

1. `GET /api/pins?all=1`(열림+닫힘) 응답에 `done:true` 로 남아 있으면 "완료"로 알린다.
2. 아예 없으면 다른 사람이 `/drop` 한 것이다. `GET /api/pins/dropped` 로 누가 지웠는지 찾아 "#N 을 〈이름〉 가 삭제함"으로 알린다.

옛 구현은 이 둘을 가리지 않고 전부 "완료"로 알렸다. 그래서 공저자가 지운 핀도 작성자 화면에 "완료"로 떴다(실측).

## 위치 추정 (`est`)

핀 마크는 드래그 당시의 `frac`(쪽 대비 비율)에 고정된다. 원고가 바뀌어 PDF가 다시 빌드되면 그 좌표가 지금 화면의 PDF와 안 맞을 수 있다. 그럴 가능성이 있으면 마크를 점선(`.est`)으로 그린다. **판정은 서버가 하고** `GET /api/pins` 의 `est` 불리언으로 싣는다. 뷰어는 받은 값을 그대로 그린다.

### 빌드 신원과 핀의 빌드

- **빌드 신원.** 빌드마다 `<state_dir>/builds.json` 에 `{build, src_hash, src_mtime, finished_at, seq}` 를 남긴다. 성공한 빌드를 최근 200개까지 보관한다. `build` 는 쪽 디렉토리 이름(`pages.cur` 값)이다.
- **`src_hash`** 는 빌드 사본의 원고 파일을 (상대경로, 내용)으로 해시한 값이다. 파일 목록은 `src_mtime` 과 같다. 즉 `diff/`·`diff_temporary/`, 점 디렉토리, 메인 PDF를 뺀다. mtime은 넣지 않는다. 내용이 같으면 레이아웃도 같기 때문이다.
- **핀의 `pdf_build`.** 드래그할 때 화면에 있던 빌드 id다(pick 응답의 `pdf_build`). 핀을 만들 때와 위치를 다시 잡을 때(`loc` 에 `frac` 이 있을 때) 남긴다. 메모나 범위 텍스트 편집은 바꾸지 않는다.

### 판정 규칙

```text
est = (pin.pdf_build ≠ 지금 빌드 그리고 두 빌드의 src_hash 가 다름) 또는 sync 가 moved/lost
```

- 해시가 없으면 빌드 시작 `src_mtime` 으로 비교한다.
- 그 빌드를 이력에서 못 찾으면 추정(점선)으로 본다. 모르는 채 실선으로 그리는 편이 더 해롭기 때문이다.
- `pdf_build` 가 없는 옛 핀은 서버가 epoch 수치로 판정한다. 옛 필드명 `frac_build` 는 `pdf_build` 와 같은 뜻으로 읽는다. 찍은 시각 `at` < `built_at` 이고, 지금 빌드를 시작할 때의 `src_mtime` > `at` 이면 추정이다. `edited_at` 은 보지 않는다.

실행 정본은 [`src/limn/pins/position.py`](../../src/limn/pins/position.py)의 `pin_est`·`same_source`·`legacy_est`·`est_basis`(순수 판정, 시계를 읽지 않는다)와 문서의 빌드 이력을 한 번 읽어 그 재료(`EstContext`)를 만드는 [`src/limn/locate.py`](../../src/limn/locate.py)의 `est_context`다.

### 기동 때 지금 빌드 등록

옛 인스턴스가 만든 지금 빌드는 이력에 없을 수 있다. 기동 때 이 빌드를 이력에 한 번 올린다. 원고가 그 빌드 뒤로 안 바뀌었으면(`src_mtime` ≤ 빌드 기준 시각) 지금 원고의 지문을 그 빌드의 지문으로 삼는다. 그래야 기동 뒤 첫 핀이 원고를 안 바꾼 재빌드에서 점선으로 오탐되지 않는다.

### 왜 서버가 판정하는가

예전에는 뷰어가 벽시계로 판정했다. `at`·`edited_at` 을 `built_at`·`build_src_mtime` 과 비교하는 방식이다. 이 방식은 세 갈래로 틀렸다(독립 검증 실측).

1. 시간대 없는 `at` 을 브라우저가 현지 시각으로 풀었다. 그래서 America/New_York에서는 어긋난 마크가 실선으로, Pacific/Kiritimati에서는 방금 찍은 핀이 점선으로 그려졌다.
2. 메모만 고쳐도 점선이 꺼졌다.
3. 원고를 고친 뒤 옛 PDF 위에서 찍은 핀은 판정에 들어가지 못했다.

지금은 Asia/Seoul, America/New_York, Pacific/Kiritimati 세 컨텍스트에서 같은 마크가 같은 결과를 낸다.

## 보기 전용 PDF 문서

`--doc` 으로 연 `.pdf` 문서는 LaTeX 빌드가 없다. 대신 감시 스레드가 3초마다 그 PDF의 `mtime:크기` 를 본다. 쪽을 그린 때의 값(`docs/<키>/pdf_sig.txt`)과 다르면 백그라운드로 쪽을 다시 그린다.

- 다시 그리기는 LaTeX 문서와 같은 빌드 경로(`limn/build.py` 의 `run_tracked`)를 탄다. 그래서 `GET /api/build?doc=<키>` 의 `state`, `phase:"render"`, `build_seq`, 빌드 이력이 LaTeX 문서와 똑같이 움직인다. 뷰어도 재빌드가 끝난 것처럼 화면을 바꾼다.
- 지문은 PDF 내용의 해시다. 그래서 바뀐 PDF 위의 옛 핀은 점선(추정)이 된다(§위치 추정 (`est`)).
- 그리기가 실패해도 같은 파일로 되풀이하지 않는다. 파일이 바뀌면 다시 시도한다.
- `stale_build` 는 늘 `false` 다.
- `POST /api/rebuild?doc=<키>` 는 `400` 이다.

보기 전용 문서의 pick과 핀 규칙은 [api.md](api.md) §보기 전용 PDF 문서의 pick·핀에 있다.
