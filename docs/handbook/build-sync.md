# 빌드·자동 동기화·위치 추정

Limn은 원고를 PDF로 빌드해 쪽 이미지로 보여 주고, 그 위에 핀을 찍는다. 원고와 핀은 사람과 에이전트가 동시에 바꾼다. 그래서 세 가지를 맞춰야 한다. 화면의 PDF가 언제 새로 빌드되는지, 다른 사람이 바꾼 핀과 원고가 화면에 어떻게 들어오는지, 옛 PDF 위에서 찍은 핀 좌표를 믿어도 되는지다. 이 문서는 그 세 가지를 다룬다.

재빌드 흐름, 빌드 상태, 폴링 주기, 점선 마크(`est`) 판정을 바꿀 때 이 문서를 읽고 같은 diff에서 고친다. 엔드포인트 목록과 응답 필드 전체는 [api.md](api.md) 에 있다. 뷰어 조작 요약은 [viewer.md](viewer.md) §조작 한눈에가 맡는다.

빌드의 순수 결과 타입·상태 이름은 [`builds/values.py`](../../src/limn/builds/values.py), 공통 상태·이력·지문은 [`builds/artifacts.py`](../../src/limn/builds/artifacts.py)가 소유한다. `builds/artifacts.py`의 결과 타입 import도 같은 타입을 가리킨다. 요청 경로와 HTTP 응답은 [`builds/routes.py`](../../src/limn/builds/routes.py)·[`http.py`](../../src/limn/builds/http.py)가, 실행 연결은 [`service.py`](../../src/limn/builds/service.py)가 맡는다. 같은 기능의 [`completion.py`](../../src/limn/builds/completion.py)는 주어진 결과·시각·원본 기준에서 이력과 화면 상태를 계산한다. [`run.py`](../../src/limn/builds/run.py)는 문서별 잠금·추적·이력을, [`engine.py`](../../src/limn/builds/engine.py)는 원고 복사·컴파일·쪽 교체·보기 전용 PDF 렌더를 맡는다. 잠금·상태·mtime 캐시는 `Doc`이 갖고, 실행 설정은 서비스가 호출 시점에 받는다. 그림 문서의 가져오기는 같은 기능의 [`figure.py`](../../src/limn/builds/figure.py)가, 빌드마다 보관한 지도 사본 읽기와 지도 경로 검사는 공통 `builds/artifacts.py`가 맡는다(§그림 문서).

`--git-pull`의 판단은 순수 [`sync/rules.py`](../../src/limn/sync/rules.py)가, git 호출과 원격 감시는 [`run.py`](../../src/limn/sync/run.py)가 맡는다. 규칙은 pull 결과와 다시 빌드할 문서를 정하고, 실행은 원고 경로·문서·Git 실행기·시계를 인자로 받는다.

[`sync/service.py`](../../src/limn/sync/service.py)는 실행별 pull·감시 상태를 받아 빌드와 meta에 연결한다. [`server.py`](../../src/limn/server.py)는 동기화와 PDF 감시를 런타임 스레드로 시작하고 `RT.stop()`으로 끝낸다. `--git-pull`과 보기 전용 렌더는 빌드 단계로 넘긴다.

폴링 응답(`GET /api/meta`·`/api/docs`·`/api/outline-labels`)은 [`documents/`](../../src/limn/documents/http.py)가 소유한다. 순수 읽기는 문서·설정·동기화 상태를 인자로 받는다. 라이트 meta는 핀 동기화 쓰기를 건너뛰고, 전체 meta의 핀 개수만 `snapshot_pins()`를 거친다.

> **한눈에**
>
> 재빌드는 동기(`POST /api/rebuild`)와 비동기(`?async=1` + `GET /api/build`) 두 경로가 같은 빌드 함수를 쓴다. `--git-pull` 을 켜면 빌드 전에 원격 main을 fast-forward로 당긴다. 에이전트용 응답은 로그를 줄여 보낸다. 뷰어는 쓰기가 없는 라이트 meta를 5초마다 폴링해 변화가 있을 때만 핀을 다시 읽는다. 핀 마크를 실선으로 그릴지 점선으로 그릴지는 서버가 빌드 지문으로 판정한다. 보기 전용 PDF는 빌드 대신 파일 변화를 감시하고, 그림 문서는 지도와 PDF가 서로 맞을 때만 가져온다.

`src_mtime` 의 2초 캐시와 그 잠금은 각 `Doc` 이 함께 소유한다. 한 문서의 캐시를 읽거나 채우는 동안 다른 문서의 캐시를 막지 않는다. 추적 빌드에서 원고 mtime을 재는 단계가 실패하면 컴파일 단계의 예상 밖 실패와 같이 `BuildAborted("crashed")` 를 기록하고 빌드 상태를 `fail` 로 끝낸다.

새 쪽을 만든 뒤 원고 mtime 기준값이나 빌드 결과를 기록하는 단계가 예상 밖으로 실패하면 원래 오류를 호출자에게 전달하고, 메모리 상태의 `running`·진행 단계·시작 시각은 실패 상태로 정리한다. 이미 공개된 쪽 디렉터리와 `pages.cur` 는 되돌리지 않아 실제로 공개된 빌드의 증거를 남긴다. 정상적인 결과의 기록 순서와 응답은 그대로다.

## 신뢰 가정 — 원고 저장소는 믿는 코드다

본 빌드는 원고를 믿는 코드로 다룬다. 서버는 원고 사본에서 `latexmk -pdf -synctex=1 -interaction=nonstopmode <main>` 을 서버 계정의 권한으로 돌린다. `-norc` 를 주지 않고 격리(bwrap)도 없으므로, 원고 저장소에 든 `latexmkrc`·`.latexmkrc`(Perl)가 그 계정으로 그대로 실행되고, TeX은 배포판 기본값의 shell escape 설정으로 돈다. 원고 사본은 점 폴더도 함께 복사한다(§재빌드 (동기)). 그래서 **원고 저장소에 푸시할 수 있는 사람은 서버에서 코드를 돌릴 수 있다.** `--git-pull` 을 켜면 원격 `main` 에 푸시만 해도 1분 안에 자동 재빌드가 그것을 실행한다(§자동 확인). 끄더라도 editor·agent 의 재빌드 요청이나 다음 빌드에서 실행된다.

- Limn은 푸시하는 사람을 모두 믿는 원고 저장소만 가리키게 한다. 자동 확인은 `main` 만 fast-forward 하므로 남의 PR 브랜치가 저절로 빌드되지는 않지만, `main` 에 머지되면 빌드된다.
- 서버 계정에는 원고 빌드에 필요한 것만 둔다. 같은 계정의 다른 저장소 자격 증명이나 토큰 파일은 원고 쪽 코드가 읽을 수 있다.
- 비교 PDF 빌드(`/api/revision-build`)는 다르다. 과거 커밋의 스냅샷을 `bwrap` 격리 안에서 `latexmk -norc -no-shell-escape` 로 돌려 원고의 `latexmkrc` 를 읽지 않고, 홈 디렉토리·원본 저장소·네트워크도 보이지 않는다([api.md](api.md) §실행 환경과 격리).
- 본 빌드도 같은 방식(`-norc`, 격리)으로 돌리는 선택 인자는 나중의 후보다. 약속이 아니고 지금 동작은 그대로다. `latexmkrc` 에 기대는 원고가 있어서 기본값으로 켜면 그런 빌드가 깨진다.

이 가정은 [SECURITY.md](../../SECURITY.md) §The manuscript repository is trusted code 와 [operations.md](operations.md) §보안 제약에도 적었다.

## 재빌드 (동기)

`POST /api/rebuild` 는 원고를 다시 빌드하고 끝날 때까지 기다린다. 잠금 하나로 한 번에 하나만 돈다. 이미 빌드 중이면 기다리지 않고 `409 {"ok": false, "busy": true}` 를 준다.

여러 문서(`--doc`)면 잠금, 빌드 상태(`GET /api/build?doc=`), 빌드 이력, `build_seq` 가 **문서마다** 따로다. 그래서 서로 다른 문서는 동시에 빌드된다. 빌드 폴더가 문서마다 따로라 서로의 `.aux` 를 밟지 않는다. `--git-pull` 은 저장소 단위로 한 번이다(§재빌드 전 원격 main 당겨오기 (`--git-pull`)).

### 빌드 상태

| `state` | 조건 | 화면 |
| --- | --- | --- |
| `ok` | 새 PDF가 나왔고 LaTeX 로그에 `! ` 줄이 없다. 또는 원고가 화면 빌드와 같아 아무것도 돌리지 않았다(`unchanged: true`, §따뜻한 LaTeX와 변경 없는 재빌드) | 새 쪽으로 교체. 변경 없음이면 그대로 |
| `ok_errors` | 새 PDF는 나왔지만 `! ` 줄이 있다(nonstopmode의 `\undefinedmacro` 등) | 새 쪽으로 교체 + 오류 알림 |
| `fail` | 원고 사본을 못 믿거나, 새 PDF가 없거나(이번 실행이 PDF를 쓰지 않았다. 실행 전후의 (mtime_ns, 크기, inode)가 같고, latexmk가 남긴 PDF를 믿을 조건(§따뜻한 LaTeX와 변경 없는 재빌드)도 맞지 않는다), 시간 초과, SyncTeX 파일이 없거나, 쪽을 못 그렸다 | **이전 쪽 그대로** |

비동기 조회(`GET /api/build`)에는 빌드 전의 `idle` 과 진행 중인 `running` 이 더 있다(§비동기 재빌드). 다섯 이름은 `limn/builds/values.py` 의 `BuildState`(`BUILD_STATES`)다.

### 빌드 결과

빌드 한 번은 값 하나로 끝난다. 상태 문자열이 든 dict를 돌려주지 않는다. 경우마다 frozen dataclass가 따로 있고, 코드는 `match` 로 타입을 가른다(mypy `exhaustive-match` 가 빠진 경우를 잡는다). 모두 [`src/limn/builds/values.py`](../../src/limn/builds/values.py)에 있다.

| 값 | 뜻 | `state` |
| --- | --- | --- |
| `BuildOk` | 새 쪽, LaTeX 오류 없음 | `ok` |
| `BuildUnchanged` | 원고 사본이 화면 빌드와 같아 latexmk·쪽 그리기를 하지 않았다. 새 쪽도 `build_seq` 도 없다(§따뜻한 LaTeX와 변경 없는 재빌드) | `ok` |
| `BuildOkWithErrors` | 새 쪽, `! ` 줄 있음(`errors`) | `ok_errors` |
| `CopyFailed` | 원고 사본을 못 믿어 컴파일하지 않았다 | `fail` |
| `BuildFailed(kind)` | 컴파일했지만 새 쪽이 없다. `kind` 는 `timeout`·`no_pdf`·`no_synctex`·`render`(pdftoppm)·`pdf_copy`(PDF 사본을 쪽 옆에 못 둠) | `fail` |
| `BuildAborted(kind)` | 아무것도 재기 전에 멈췄다. `kind` 는 `pdf_missing`(보기 전용 PDF가 없다)·`figure_unready`(감시 밖에서 가져오기를 불렀는데 그림 문서의 지도와 PDF가 맞지 않는다. 감시는 여기까지 오지 않고 기다린다)·`crashed`(추적 빌드의 예상 밖 예외)·`worker_crashed`(백그라운드 스레드의 예상 밖 예외) | `fail` |

실패 셋의 이름은 `FailedBuild`, 끝난 빌드 전체는 `FinishedBuild` 다. 빌드를 시작하는 쪽의 값은 따로다. 이미 빌드 중이면 `BuildBusy`, 백그라운드 빌드를 걸었으면 `BuildStarted`, 기동 때 쪽이 이미 맞아 빌드하지 않았으면 `BuildSkipped` 다. 쪽 그리기(`render_pages`)는 새 디렉토리나 `PagesNotRendered(kind)` 를 돌려준다.

실패 로그의 첫 문장은 빌드의 응답 모듈이 소유한다. [`src/limn/builds/answer.py`](../../src/limn/builds/answer.py)의 `BUILD_FAILURES` 표가 `kind` 마다 한국어 문장 하나를 갖고, `build_failure_log` 가 그 문장에 세부(사본 오류, `OSError`, PDF 경로, 예외의 repr)를 채운 뒤 latexmk가 돌았으면 줄바꿈과 latexmk 마지막 줄을 붙인다. 조립 지점(`server.py`)이 이 함수를 추적 빌드(`run_tracked`)와 백그라운드 빌드(`build_in_background`)에 넘기므로, 응답의 `log`, `GET /api/build` 의 `log_tail`, `builds.json` 의 `last.log_tail`, 기동 거절 문구가 모두 같은 글이다. 비교 PDF는 `revisions/answer.py`의 `REVISION_FAILURES`가 같은 역할을 맡는다.

원격 main 감시(`sync/run.py`)는 문서의 마지막 빌드가 실패했는지를 공통 `builds/artifacts.py`의 `last_build_failed` 로 읽는다. 빌드 상태 dict를 직접 들여다보지 않는다.

### 응답

`POST /api/rebuild` 의 본문은 한 곳, [`builds/answer.py`](../../src/limn/builds/answer.py) 의 `finished_build_body` 가 만든다. 키 순서는 `ok`(state≠fail), `state`, `errors: [{"line", "msg"}]`, `log`, `elapsed_s` 이고, 그 뒤로 빌드가 간 데까지만 붙는다. `pull`(`--git-pull` 일 때), `src_mtime`(LaTeX 빌드가 컴파일한 원고의 mtime), `src_hash`(사본의 지문을 잰 뒤. 못 읽었으면 `null`), 새 쪽이 나왔으면 `head`·`build`(새 쪽 디렉토리 이름)·`pages`(새 쪽 수)다. 변경 없는 재빌드는 `ok` 빌드와 같은 키에 `build`(화면에 남은 쪽 디렉토리)와 맨 뒤 `unchanged: true` 가 붙고, `log` 는 빈 글이다. 원고 사본에서 멈춘 실패에는 `src_hash` 가 없고, `BuildAborted` 는 앞의 다섯 키만 있다(`elapsed_s` 0.0). 상태 코드와 다이어트는 `rebuild_answer`(동기)와 `rebuild_started_answer`(비동기)가 정한다.

| 필드 | 뜻 |
| --- | --- |
| `errors` | `! ` 줄과 그 뒤 `l.<n>` 줄을 최대 5건 |
| `head` | 그 빌드가 컴파일한 커밋의 짧은 해시. 성공 때만 있고 `<state_dir>/head.txt` 와 같은 값이다 |
| `pull` | `--git-pull` 일 때만 채워진다(§재빌드 전 원격 main 당겨오기 (`--git-pull`)) |
| `log` | §에이전트 응답 다이어트를 따른다 |

### 쪽 교체

쪽 이미지는 새 디렉토리 `pages-<build_id>/` 에 먼저 그린다. 그다음 포인터 파일 `pages.cur` 를 원자적으로 바꾼다. 그래서 빌드 중에도, 전환 직후 옛 URL로도 쪽 요청이 끊기지 않는다. 뷰어는 새로고침 없이 이미지만 바꾼다. 보던 쪽과 쓰던 메모는 그대로 유지한다.

쪽 그리기(`engine.render_pages`, phase `render`)는 쪽마다 `pdftoppm` 을 따로 돌린다.

- 쪽 수는 `pdfinfo` 로 읽는다. 쪽마다 `pdftoppm -r <dpi> -f <n> -l <n> -singlefile` 이 PPM을 표준 출력으로 내고, 서버가 그것을 표준 라이브러리(`zlib`)로 PNG로 바꾼다(`builds/png.py`). 모든 줄을 필터 0(None)으로 두고 zlib 수준 1로 압축한다. `pdftoppm -png` 는 시간의 절반을 PNG 압축에 쓰기 때문이다. 픽셀은 `pdftoppm -png` 가 저장하던 것과 같고 바이트만 다르다. 파일 이름도 같은 규칙이다. `page-<n>.png` 의 `n` 은 전체 쪽 수의 자릿수만큼 0을 채운다(9쪽이면 `page-1`, 10쪽이면 `page-01`). `page_list` 의 정렬과 쪽 크기 계산은 그대로다.
- 동시에 도는 `pdftoppm` 은 `min(8, CPU 수)` 개까지다. 1쪽부터 차례로 맡긴다. 한 쪽의 PPM은 150 dpi A4에서 약 6.5 MB라, 순간 메모리는 그 몇 배다.
- 렌더 전체의 시간 한도는 600초다. 쪽마다 남은 시간을 넘겨받는다.
- 한 쪽이라도 못 그리면 빌드는 `BuildFailed("render")` 다. 로그 첫 줄의 세부가 그 쪽 번호와 `pdftoppm`(또는 `pdfinfo`)의 마지막 메시지를 알린다. 아직 시작하지 않은 쪽은 그리지 않는다.
- 그리는 동안의 폴더는 `.pages-<build_id>.part` 다. 이 이름은 클라이언트가 보낼 수 있는 빌드 이름(`valid_build_name`)이 아니므로, 반쯤 그린 폴더를 아무도 요청할 수 없다. 쪽과 PDF·SyncTeX 사본이 모두 들어간 뒤에야 한 번의 rename으로 `pages-<build_id>` 가 된다. 실패하면 이 폴더를 지운다. 프로세스가 죽어 남은 폴더는 그 문서의 다음 렌더가 지운다.
- 빌드 이름은 초 단위 시각이다. 같은 초에 이미 있는 폴더나 `builds.json` 이력에 남은 이름이면 `-<n>` 을 붙인다. 지워진 빌드의 이름도 다시 쓰지 않으므로, 빌드 이름이 들어간 URL은 언제나 같은 이미지를 가리킨다. 그래서 그 URL(`/pages/<빌드>/<쪽>`, `/pdf?build=<빌드>`)은 1년 동안 캐시한다([api.md](api.md) §화면·PDF·정적 파일).

## 따뜻한 LaTeX와 변경 없는 재빌드

빌드 시간의 나머지 절반은 매번 처음부터 도는 LaTeX다. 그래서 사본은 latexmk의 부산물을 빌드 사이에 남기고, 원고가 화면 빌드와 같으면 아무것도 돌리지 않는다. 판단은 순수 [`builds/warm.py`](../../src/limn/builds/warm.py)가, 파일 일은 `engine.compile_tex` 가 맡는다.

부산물은 언제 지워도 다음 빌드가 처음부터 다시 만드는 캐시다.

### 남기는 부산물

- 사본은 메인 파일의 부산물과 PDF를 남긴다. 부산물은 latexmk를 돌리는 폴더의 `<main>` 에 `.aux`·`.bbl`·`.bcf`·`.blg`·`.fdb_latexmk`·`.fls`·`.idx`·`.ilg`·`.ind`·`.lof`·`.log`·`.lot`·`.nav`·`.out`·`.run.xml`·`.snm`·`.spl`·`.toc`·`.vrb` 를 붙인 이름이다(`warm.kept_paths`). 복사(`copy_manuscript`)는 이 경로를 rsync에 고정 제외로 넘기므로 지우지도 덮지도 않는다. rsync가 없을 때의 복사도 이 경로를 비워 두고 나머지만 새로 복사한다. 그래서 latexmk는 바뀐 단계만 돈다. 한 문단을 고치면 pdflatex가 한 번 돈다.
- 원고에 커밋된 같은 이름의 PDF(`<main>.pdf`)는 사본으로 오지 않는다. 그래서 빌드가 쓴 PDF를 덮지 못한다.
- 메인 파일 폴더에 부산물 이름의 파일이 원고로 들어 있으면(arXiv용 `main.bbl` 등) 아무것도 남기지 않는다. 그 파일은 다른 원고 파일과 같이 사본으로 복사되어 쓰이고, 빌드는 매번 처음부터 돈다.
- 복사는 `rsync -a --checksum --delete` 다. 사본을 빌드 사이에 남기므로 크기와 mtime(초)이 같은 편집, 곧 직전 복사와 같은 초에 한 글자를 바꾼 편집도 내용으로 가려 사본에 넣는다.
- 강제 재빌드(`POST /api/rebuild?force=1`)는 시작 전에 부산물과 PDF·SyncTeX를 지운다. `ok` 로 끝나지 않은 빌드(`ok_errors`·`fail`)와 예상 밖 예외로 죽은 빌드도 끝난 뒤 지운다. 다음 빌드는 처음부터 돈다. 그래서 옛 `.aux`·`.bbl` 이 실패한 빌드를 넘어 남지 않는다.
- 빌드 방식이 바뀐 빌드도 latexmk를 돌리기 전에 지운다(§빌드 방식이 바뀌면 처음부터).

파일이 이번 실행에서 쓰였는지는 실행 전후의 (mtime_ns, 크기, inode)로 가른다. 직전 빌드의 1초 안에 실패한 빌드가 남은 PDF를 새 PDF로 내놓지 않게 하기 위해서다.

latexmk가 아무것도 컴파일하지 않아도 빌드가 남은 파일로 쪽을 그려야 할 때가 있다. dpi만 바꾼 재빌드, 인용하지 않는 `.bib` 항목을 고친 재빌드, 업그레이드 뒤 첫 재빌드다. 이때 사본에 남은 PDF·SyncTeX·`.aux` 를 이번 빌드의 것으로 믿는 조건은 아래가 **모두** 맞을 때뿐이다(`warm.vouched`).

1. 부산물을 남긴 사본이고, latexmk가 종료 코드 0으로 끝났고, 시간 초과가 아니다.
2. 이번 실행이 PDF를 쓰지 않았다. 실행 전에 있던 PDF의 (mtime_ns, 크기, inode)가 그대로다.
3. latexmk 출력의 마지막 `Latexmk: All targets (X) are up-to-date` 줄의 `X` 가 정확히 `<main>.pdf` 다.

latexmk 4.87은 오류 없이 끝난 모든 실행 뒤에 이 줄을 찍는다. 컴파일한 실행도 그렇다. 그래서 줄만으로는 아무것도 증명하지 않고, 2가 있어야 한다. 3은 latexmkrc의 `$out_dir` 과 `-jobname` 을 잡는다. 이런 설정이면 latexmk의 대상이 다른 이름이고, 사본의 `<main>.pdf` 는 latexmk가 만든 PDF가 아니다. 이때 빌드는 `no_pdf` 로 실패하고 화면은 이전 쪽 그대로다. `$aux_dir` 만 둔 설정은 대상이 여전히 `<main>.pdf` 라 3이 잡지 못한다. 그래도 안전하다. 그 폴더는 원고에 없으므로 사본 복사(`rsync --delete`)가 빌드마다 지우고, 그 안의 `.fdb_latexmk` 가 사라진 latexmk는 매번 PDF를 다시 쓴다. 그러면 2가 맞지 않는다.

조건이 맞아도 사본에 남은 `.fls` 는 그 바이트가 화면 빌드의 쪽 폴더에 있는 `.fls` 와 같을 때만 이번 빌드의 것으로 둔다. 다르면(recorder를 껐거나, 원고에 딸려 온 옛 `main.fls`) `.fls` 를 두지 않고, 빌드 방식 파일에도 읽은 파일을 적지 않는다. 그러면 다음 재빌드는 변경 없음으로 끝나지 않는다.

### 빌드 방식이 바뀌면 처음부터

latexmk는 원고 파일의 변화만 따진다. latexmkrc, 어떤 프로그램이 도는지, 곁도구의 스타일 파일은 보지 않는다. 그래서 이런 것이 바뀐 사본을 그대로 넘기면 latexmk는 대상이 최신이라고 보고 옛 PDF를 둔다. 예를 들어 latexmkrc에 `$pdflatex = 'xelatex %O %S';` 를 넣으면 옛 pdfTeX PDF가, makeindex 스타일(`-s style.ist`)을 고치면 옛 색인이 남는다.

빌드는 latexmk를 돌리기 전에 빌드 방식 다이제스트(`warm.cold_digest`)를 지금 상태로 잰다. 화면 빌드의 `recipe.json` 에 적힌 값과 다르거나, 화면 빌드에 `recipe.json` 이 없으면 부산물을 지우고 처음부터 돈다. 다이제스트는 세 묶음이다.

- **latexmkrc.** latexmk 4.87이 실제로 읽는 rc 파일을 latexmk와 같은 규칙으로 고른다(`engine._rc_paths`). 각 목록에서 처음으로 있는 파일 하나만 읽는다.
  - 시스템 파일: `$LATEXMKRCSYS` 가 있으면 그것만 본다. 없으면 `LatexMk`, 그다음 `latexmkrc` 의 순서로 `/etc`, `/opt/local/share/latexmk`, `/usr/local/share/latexmk`, `/usr/local/lib/latexmk` 를 차례로 본다.
  - 사용자 파일: `$XDG_CONFIG_HOME/latexmk/latexmkrc`(없으면 `~/.config/latexmk/latexmkrc`), 그다음 `~/.latexmkrc` 다.
  - 프로젝트 파일: latexmk를 돌리는 폴더의 `.latexmkrc`, 그다음 `latexmkrc` 다. 사본이 그대로 두므로 빌드 루트에서도 같은 규칙으로 하나를 고른다.

  고른 파일의 경로가 다이제스트에 든다. 그래서 앞 순위의 파일이 새로 생겨도 바뀐 것이다. 내용은 1 MiB 이하의 일반 파일일 때만 읽고, 그 내용을 센다. 심볼릭 링크는 따라가지 않고, 장치·FIFO도 읽지 않는다. 이런 파일은 종류, 링크 대상, stat 결과로 센다. `/dev/zero` 를 가리키는 rc가 빌드를 멈추게 하지 않는다. 도구 이름(아래)도 읽은 일반 파일에서만 찾는다.
- **도구.** `latexmk` 와 rc가 정한 `$pdflatex`·`$bibtex`·`$biber`·`$makeindex` 의 프로그램(기본은 같은 이름, 따옴표로 둘러싼 단순 대입의 첫 낱말만 읽는다, `warm.tool_names`)을 PATH로 찾아 실제 경로(`os.path.realpath`)와 그 파일의 mtime_ns·크기를 센다. 새 해의 TeX Live를 옛것 옆에 깔고 PATH를 바꾸면 경로가 달라진다. 제자리 업데이트로 프로그램이 바뀌어도 크기나 mtime이 달라진다.
- **곁도구의 스타일 파일.** makeindex의 `.ilg`(`Scanning style file …`)와 bibtex의 `.blg`(`The style file: …`)가 적은 스타일 파일(`warm.log_styles`)이다. latexmk를 돌리는 폴더 기준으로 찾아 있는 파일만, 사본 안이면 내용으로, 밖이면 mtime·크기로 센다. 이름만 적혀 TeX 배포판에서 찾은 `.bst` 는 `.fdb_latexmk` 의 bibtex 원본으로 이미 비교된다. 사본 안의 파일이라도 그 빌드가 읽은 파일 목록(`.fdb_latexmk` 원본 포함)에 있으면 뺀다. latexmk가 스스로 따라가므로 원고에 든 `.bst` 를 고쳐도 사본은 따뜻하다. `.ilg`·`.blg` 는 1 MiB 이하의 일반 파일일 때만 읽고(링크는 따라가지 않는다), 줄 단위로 훑는다. 정규식을 쓰지 않으므로 긴 줄에도 시간이 선형이다.

이 다이제스트는 빌드가 끝날 때 `recipe.json` 의 `cold` 와 스타일 파일 목록 `styles` 로 남는다. `.fls` 가 없는 빌드(recorder를 끈 문서)도 이 값은 남긴다. 그래서 그런 문서도 `.tex` 만 고치면 따뜻하게 돈다. 다만 읽은 파일을 모르므로 변경 없음으로 끝나지는 않는다. 변경 없는 재빌드도 이 값이 같아야 한다. 한 문단을 고친 것처럼 원고만 바뀌면 다이제스트는 그대로이고 사본은 따뜻하다.

### 변경 없는 재빌드

재빌드(동기·비동기, 원격 main 감시와 기동 빌드 포함)는 사본을 만든 뒤 지문을 잰다. 지문은 화면 빌드의 `.fls` 가 알려 준 읽은 파일로 고른다(§원고 변화 감지). 아래가 모두 맞으면 `BuildUnchanged` 로 끝난다(`warm.keeps_pages`).

- 강제 재빌드가 아니다.
- 화면 빌드의 쪽 폴더에 `.fls` 가 있고, 빌드 방식 파일 `recipe.json` 이 읽은 파일을 적고 있다. 어느 하나라도 없으면(recorder를 끈 빌드, 이 규칙 이전의 빌드, 업그레이드 뒤 첫 재빌드) 그 빌드가 무엇을 읽었는지 모르므로 늘 빌드한다.
- 지문이 화면 빌드의 이력 항목 `src_hash` 와 같다.
- `recipe.json` 이 지금도 맞는다(`warm.recipe_matches`). 이 파일에는 쪽 dpi, 메인 파일 경로, latexmk 스위치, 그 빌드가 읽은 파일 목록, 빌드가 끝날 때 잰 두 다이제스트가 들어 있다. 하나는 위의 빌드 방식 다이제스트(`cold`)다. 다른 하나는 읽은 파일의 다이제스트(`digest`)다. 재빌드는 같은 목록으로 둘을 지금 다시 재서 비교한다. 읽은 파일의 다이제스트는 두 묶음이다.
  - 사본 안에서 읽은 파일. 내용을 비교한다. 목록은 그 빌드의 `.fls` 가 읽었다고 적은 파일(`warm.fls_reads`, 같은 `.fls` 가 쓴 `OUTPUT` 파일은 뺀다)에 `.fdb_latexmk` 가 적은 각 규칙의 원본(`warm.fdb_sources`)을 더한 것이다. `.fdb_latexmk` 가 bibtex·biber·makeindex가 읽은 `.bib`·`.bst`·`.ist` 를 알려 준다. 이 파일들은 `.fls` 에 없고, `out/` 아래의 `.bib` 은 지문에도 없다. 확장자를 가리지 않으므로 `\input` 한 파일, pgfplots가 읽는 `.csv`·`.dat` 도 든다. 원고 폴더에 실제로 있는 파일만 센다. latexmk나 도구가 사본에서 만든 파일(epstopdf 변환본 등)은 원고가 아니기 때문이다.
  - 사본 밖에서 읽은 파일(TeX 배포판의 `.cls`·`.sty`·글꼴·서식 파일, `TEXINPUTS` 로 찾은 패키지). mtime_ns와 크기를 비교한다. 읽지 않고 stat만 하므로 수백 개여도 몇 밀리초다. TeX 배포판을 업데이트하면 다시 빌드한다.
- 마지막으로 끝난 빌드가 `ok` 이고, 그 빌드가 화면 빌드다. `ok_errors`·`fail` 뒤에는 늘 빌드한다.

변경 없는 재빌드는 latexmk와 쪽 그리기를 하지 않는다. 새 쪽 폴더, `build_seq`, 이력 항목, 이력의 `last` 를 만들지 않는다. 하는 일은 셋이다.

- 화면 빌드 이력 항목의 `src_mtime` 과 `built_src_mtime.txt` 를 이번에 잰 원고 mtime으로 옮긴다. 내용이 같으므로 화면 빌드가 지금 원고를 나타낸다. mtime만 바뀐 원고의 "원고 수정됨" 배지가 이것으로 꺼진다.
- `head.txt` 를 지금 체크아웃한 커밋으로 쓴다. 원고 밖 파일만 바꾼 커밋을 fast-forward 했을 때 원격 main 감시가 그 커밋을 반영한 것으로 본다.
- 빌드 상태를 `state:"ok"`, `unchanged:true` 로 둔다. `phase`·`start_ts` 는 비우고, `last_s` 와 `last` 는 마지막으로 센 빌드의 값 그대로다. 다음 빌드가 시작하면 `unchanged` 는 빠진다.

뷰어는 이 탭이 누른 재빌드가 같은 `build_seq` 에서 `unchanged:true` 로 끝나면 "변경 없음"을 한 번 알리고 화면은 바꾸지 않는다. 데스크톱은 토스트이고, compact 대역은 재빌드가 있는 상태 줄의 항목이며 토스트와 같은 6초 동안 보인다([viewer.md](viewer.md) §모바일 레이아웃). 둘의 [그래도 빌드]는 `POST /api/rebuild?async=1&force=1` 을 보낸다. 늘 보이는 강제 빌드 버튼은 두지 않는다. 다른 탭과 에이전트의 변경 없는 재빌드는 알리지 않는다. 바뀐 것이 없기 때문이다.

`recipe.json` 은 `builds.json` 이 아니라 쪽 폴더에 `.fls` 와 함께 둔다. 쪽을 다 그린 뒤 폴더 이름을 붙이기 전에 써서 폴더와 함께 한 번에 공개되고, 폴더와 함께 지워진다. `.fls` 를 두지 않는 빌드는 이 파일에 읽은 파일을 적지 않고(`digest` 가 `null`) 빌드 방식 다이제스트만 남긴다. 그래서 `builds.json` 에는 새 필드가 없고, 옛 Limn으로 되돌려도 모르는 파일이 하나 남을 뿐이다. 이 파일이 없는 화면 빌드(업그레이드 직후)는 변경 없음으로 끝나지 않는다.

TeX 패키지를 제자리에서 업데이트한 경우(같은 경로의 `.sty` 를 덮어쓴 경우)는 사본 밖 파일의 mtime·크기 비교가 잡는다. 그래서 변경 없음으로 끝나지 않고 빌드하며, latexmk도 `.fdb_latexmk` 의 체크섬으로 그 변화를 알아본다.

그 밖의 것은 `POST /api/rebuild?force=1`(뷰어에서는 변경 없음 알림이나 상태 줄의 [그래도 빌드])로 처음부터 빌드한다. 화면 빌드가 읽지 않았던 파일이 새로 생겨 원고가 조건부로 그것을 읽게 되는 경우(`\IfFileExists`)가 그렇다. 셸 탈출(`\write18`)로 돈 외부 프로그램이나 위 네 변수 밖의 latexmk 규칙이 읽은 파일도 그렇다. 이런 파일은 `.fls` 에도 `.fdb_latexmk` 에도 없을 수 있다.

## 비동기 재빌드

동기 `/api/rebuild` 는 수십 초 동안 요청을 묶는다. `POST /api/rebuild?async=1` 은 빌드 잠금을 얻고 진행 상태를 준비해 데몬 스레드를 시작하면 `202 {"state":"running"}` 을 돌려준다. 잠금과 판정 로직은 동기 경로와 완전히 같다. 이미 도는 중이면 `409` 다. 상태 준비나 스레드 시작이 실패하면 잠금을 풀고 `running` 을 남기지 않는다. 실행 중 스레드가 예상 밖으로 끝나거나 실패 기록까지 실패해도 메모리의 빌드 상태는 `fail` 로 돌아간다.

### 끝난 빌드 세기 (`build_seq`)

끝난 빌드는 `build_seq` 로 센다. 서버가 빌드마다 1씩 올리는 수이고, 재기동 뒤에도 이어진다.

- 뷰어는 자기가 처리한 seq를 기억한다. 라이트 meta의 `build_seq` 가 그와 다르면 상세를 받는다. 그래서 5초 폴링 틈새에 시작부터 끝까지 끝나 `running` 을 한 번도 못 본 빌드도 알아챈다.
- 완료 처리(화면 교체, 토스트)는 seq 하나당 한 번이다.
- `GET /api/build` 조회는 **단일 비행**이다. 1초 타이머, `visibilitychange`, `focus`, 라이트 폴링이 한꺼번에 불러도 요청은 하나만 나간다. 겹친 조회가 같은 완료를 중복 처리하지 않게 하기 위해서다.
- 새로 연 탭은 마지막 빌드가 `ok_errors`·`fail` 이면 토스트 없이 오류 패널을 연다.

### 진행 폴링

진행 상황은 `GET /api/build` 를 1초마다 폴링해서 본다. 단 **실제로 빌드가 도는 동안만** 돈다. 1초 폴러는 다음 세 경우에만 켜진다.

1. 이 탭에서 재빌드를 눌렀을 때(데스크톱 도구 줄의 [PDF 재빌드], 상태 줄의 [재빌드], [⋯]의 `PDF 재빌드` 행)
2. 5초 라이트 meta 폴링이 `build.state==='running'` 을 봤을 때. 다른 세션이나 에이전트가 `curl` 로 시작한 빌드다.
3. 부팅 때 이미 도는 빌드가 있는지 한 번 확인할 때

`state` 가 더 이상 `running` 이 아니면 폴러는 스스로 멈춘다. 탭이 숨어 있으면 폴링 요청 자체를 보내지 않고, 포커스나 `visibilitychange` 로 다시 켠다.

`GET /api/build` 응답의 진행 필드는 다음과 같다.

- `phase` 는 `pull`(업스트림 당겨오는 중, `--git-pull` 일 때만) → `copy`(원고 사본을 만드는 중) → `latex`(latexmk) → `render`(pdftoppm) 순서다. 변경 없는 재빌드는 `copy` 에서 끝난다.
- `progress` 는 셀 수 있는 일의 진행이다. 셀 수 있는 일은 쪽 그리기 하나뿐이다(§쪽 교체). `pdfinfo` 가 쪽 수를 세면 `{done: 0, total: N}` 이 되고, 쪽 하나의 PNG를 다 쓸 때마다 `done` 이 1씩 는다. 쪽은 `pdftoppm` 여럿이 동시에 그려 순서 없이 끝나지만, `done` 은 쪽 번호가 아니라 끝난 쪽의 수라 줄지 않는다. `N/N` 뒤에는 PDF 사본을 두고 폴더 이름을 붙이는 짧은 마무리만 남는다. 쪽을 못 그려 실패하면 `N` 에 닿지 않고 끝난다. 그 밖에는 `null` 이다. `pull`·`copy`·`latex` 단계, 쪽 수를 세기 전, 끝난 빌드다. TeX 단계에 퍼센트를 만들지 않는 것은 latexmk가 pdflatex·bibtex를 몇 번 돌릴지 미리 알 수 없어서다. 지난번 걸린 시간으로 채우면 진행이 아니라 예측이 된다. 그래서 그 단계의 막대는 끝을 모르는 막대다. 보기 전용 PDF와 그림 문서의 다시 그리기도 같은 쪽 그리기라 같은 숫자를 준다. 계산은 순수 `completion.render_progress` 이고, 셈은 `engine.draw_pages` 가 쪽마다 알려 빌드 상태에 둔다.
- 뷰어는 단계 이름과 `elapsed_s`, `last_s`가 있으면 지난번 걸린 시간을 보인다. 데스크톱은 진행 칩, 그 밖의 대역은 상태 줄이다([viewer.md](viewer.md) §모바일 레이아웃). 상태 줄의 진행 막대는 `progress` 가 있으면 `done/total` 만큼 차고 글이 `쪽 그리는 중 · 3/9쪽` 이 된다. 없으면(`null`, 또는 이 필드가 없는 옛 서버) 끝을 모르는 막대와 초다. 지난번 시간은 예측이 아니라서 막대를 채우는 데 쓰지 않는다.
- `elapsed_s` 는 지금까지 걸린 시간, `last_s` 는 지난 빌드가 걸린 시간이다. `last_s` 는 진행 중에 참고용으로 쓴다.
- 서버를 다시 띄워도 마지막 빌드 결과(`state`, `errors`, `log_tail`, `seq`, `head`, `pull`)는 `builds.json` 에서 되살린다. 마지막 결과의 개별 필드가 손상됐으면 쓸 수 없는 표시 값만 빈 값으로 두고, 유효한 상태와 순번은 복원한다.

### 끝났을 때

- `state` 가 `ok`·`ok_errors`·`fail` 이 되면 뷰어는 동기 경로와 같은 방식으로 제자리 교체를 한다.
- `ok_errors`·`fail` 이면 오류 패널(`#build-err`)이 **자동으로 열린다.** 토스트에만 의존하지 않는다. 토스트는 6초면 사라지고, 그 뒤에는 다시 볼 길이 없었다.
- 패널을 닫아도 다시 여는 길이 남는다. 데스크톱은 상태 칩 줄의 "빌드 오류 · 다시 보기" 칩, 그 밖의 대역은 상태 줄의 `빌드 실패 [보기]`(오류가 있는 성공 빌드는 `LaTeX 오류 N건 [보기]`)다. `BUILD.error` 가 있는 동안, 즉 다음 성공 빌드 전까지 언제든 다시 열 수 있다.
- 다른 사람이 시작한 빌드도 같은 방식으로 잡아낸다. 그래서 페이지를 새로 열었을 때 빌드가 돌고 있으면 진행 표시(데스크톱은 진행 칩, 그 밖의 대역은 상태 줄)가 이어서 보인다.
- 빌드 중(`phase=latex`)에도 pick은 막지 않는다. 대신 응답 `warn` 에 "빌드 중이라 결과가 흔들릴 수 있습니다"를 붙인다.

## 재빌드 전 원격 main 당겨오기 (`--git-pull`)

공저자가 PR을 머지해도 서버 쪽 원고 체크아웃은 저절로 바뀌지 않는다. 그대로 두면 뷰어가 옛 원고를 계속 보여 준다. `--git-pull` 은 이 틈을 메운다.

### 자동 확인

`--git-pull` 을 켜면 기동 직후와 이후 60초마다 원격 main을 확인한다.

- 새 커밋을 fast-forward 하면 각 LaTeX 문서의 PDF 재빌드를 예약한다.
- 현재 커밋과 PDF 기준 커밋이 다르면 기동 때도 재빌드한다. `--no-build` 를 줬어도 그렇다.
- 다른 빌드가 진행 중이면 3초 뒤 다시 확인한다.
- 작업 트리가 더럽거나, 분기했거나, 업스트림이 없거나, 원격 오류가 나면 상단 상태 칩에 사유를 보이고 이전 PDF를 유지한다.
- 자동 확인은 현재 브랜치가 `main` 이고 업스트림도 `*/main` 일 때만 fast-forward 한다. 다른 브랜치는 `blocked:not_main` 으로 보인다.
- 보기 전용 PDF 문서와 그림 문서는 Git pull 뒤 재빌드 대상이 아니다. 당긴 체크아웃에서 바뀐 그 파일들은 문서의 감시가 몇 초 안에 다시 그리거나 가져온다(§보기 전용 PDF 문서, §그림 문서). 그래서 머지된 그림 변경은 다음 라운드의 fast-forward와 그다음 감시 차례로 화면에 온다. 그림 문서만 있는 인스턴스도 같은 라운드로 당기고, 빌드는 시작하지 않는다. 에이전트가 그림 핀을 `ref` 와 함께 닫으면 이 라운드를 그 자리에서 한 번 더 돌린다(§그림 문서).
- 당기는 저장소는 `--manuscript` 를 품은 저장소 하나다. 원고 폴더 안에 그림 저장소를 따로 클론했거나 서브모듈로 두었으면 그 저장소는 당기지 않는다.

수동 재빌드(동기·비동기)도 copy 전에 같은 `pull` phase를 돈다.

> **주의**
>
> 서버가 쓰는 원고 체크아웃은 별도로 깨끗하게 유지해야 한다. 그 체크아웃에서 직접 작업하면 `skipped:dirty` 로 pull이 멈춘다.

### pull 단계

1. `--manuscript` 가 속한 git 저장소 루트를 찾는다(`git -C <ms> rev-parse --show-toplevel`). 저장소가 아니면 `skipped:not_git`.
2. `git fetch --quiet` 로 업스트림 원격을 받는다(timeout 30초). 실패하면 `error:fetch_failed`, 시간을 넘기면 `error:fetch_timeout`.
3. 현재 브랜치에 upstream(`@{u}`)이 없으면 `skipped:no_upstream`.
4. `git status --porcelain --untracked-files=no` 가 비어 있지 않으면 `skipped:dirty`. 이 명령 자체가 실패하면 `error:status_failed`. 자동 확인은 이 앞에서 브랜치를 본다(`skipped:not_main`, §자동 확인).
5. `git merge --ff-only @{u}` 를 한다. 분기해서 실패하면 `skipped:diverged`. 리베이스나 머지 커밋을 대신 만들지 않는다.
6. 결과 `{"state": "ok"|"up_to_date"|"skipped"|"error", "reason", "head_before", "head_after"}` 를 빌드 결과의 `pull` 필드에 싣는다. 빌드 결과란 `/api/rebuild` 응답, `/api/build`, `builds.json` 의 마지막 결과다.

`state` 가 `ok` 면 fast-forward로 커밋이 바뀐 것이다. `up_to_date` 는 저장소는 정상이지만 새 커밋이 없었다는 뜻이다.
`git rev-parse HEAD`가 성공 상태로 끝나도 해시를 출력하지 않으면 HEAD를 읽지 못한 것으로 보고 빈 해시를 결과에 싣지 않는다.

### 여러 문서에서의 pull

여러 문서면 pull을 잠금 하나로 줄 세운다. 20초 안에 다른 문서의 빌드가 이미 당겼으면 다시 당기지 않는다. 그 결과를 재사용하고 `shared: true` 를 붙인다. 그래서 두 문서를 동시에 재빌드해도 fetch·merge가 겹치지 않는다(`.git/index.lock`). 한 문서가 복사하는 중에 트리가 바뀌지도 않는다. 단일 문서는 빌드마다 당긴다.

### pull이 실패해도 빌드는 계속한다

pull이 `skipped`·`error` 여도 빌드는 지금 체크아웃으로 계속한다. pull은 있으면 좋은 것이지 빌드의 전제조건이 아니다.

git 호출이 어떤 환경에서 도는지는 §git 프로세스에 있다.

뷰어는 pull 결과를 빌드 완료 토스트에 한 줄 덧붙인다.

| pull `state` | 토스트에 붙는 줄 |
| --- | --- |
| `skipped`·`error` | 사유(`git pull 건너뜀(dirty)` 등) |
| `ok` | `원격 반영 <head_before>→<head_after>` |
| `up_to_date` | 없음. 알릴 변화가 없다 |

### git 프로세스

Limn이 띄우는 git은 모두 [`src/limn/platform/git.py`](../../src/limn/platform/git.py)를 거친다. `--git-pull`의 fetch·merge, 변경 보기의 이력·diff·스냅샷, 빌드의 `head`, 시작 때 라벨을 정하는 origin URL, `limn token create --save`의 저장소 확인이 모두 그렇다. git 명령줄을 다른 모듈이 직접 만들지 않는다(`src/limn/platform/tests/test_gitrun.py`가 검사). 동기화와 비교 기능은 같은 모듈의 `git()` 어댑터를 공유한다. 이 어댑터는 종료 코드·표준 출력·표준 오류를 돌려주고, 시간 초과와 실행 실패는 `(None, "", "")`로 돌려준다.

- 인자는 목록으로만 넘기고 셸을 쓰지 않는다. 사용자 입력은 인자에 넣지 않는다. 호출마다 시간 제한이 있다.
- stdin은 `/dev/null`이고 새 세션에서 돈다. 제어 터미널이 없으므로 git도, fetch가 부르는 ssh도 `/dev/tty`로 비밀번호·암호 문구·호스트 키를 묻지 못한다.
- `GIT_TERMINAL_PROMPT=0`을 준다. HTTPS 자격 증명이 필요하면 묻지 않고 바로 실패한다(`error:fetch_failed`).
- 서버 환경의 `GIT_*` 변수는 넘기지 않는다. `GIT_DIR`·`GIT_WORK_TREE`·`GIT_INDEX_FILE`·`GIT_CONFIG_*` 같은 변수는 git을 다른 저장소로 보내거나 원고에 없는 설정을 더하고, `GIT_ASKPASS`는 묻는 프로그램을 띄운다. ssh 전송 설정(`GIT_SSH_COMMAND`·`GIT_SSH`·`GIT_SSH_VARIANT`)만 남긴다. systemd 유닛이 `GIT_SSH_COMMAND`로 ssh를 BatchMode로 돌리고([instances.md](instances.md)), 운영자가 배포 키를 거기서 고를 수 있어서다. `HOME`·`PATH`·`SSH_AUTH_SOCK`·로케일·프록시 설정은 그대로 넘긴다.
- git에 설정한 자격 증명 도우미(credential helper)와 ssh 에이전트는 그대로 쓴다. 꺼지는 것은 사람에게 묻는 일뿐이다.

비교 PDF의 샌드박스 빌드(latexdiff·latexmk)는 이 규칙이 아니라 샌드박스 규칙을 따른다([api.md](api.md) §변경 보기와 비교 PDF).

## 에이전트 응답 다이어트

동기 `/api/rebuild` 는 성공 때도 `log` 에 폰트 경로 등 수 KB를 실어 에이전트 토큰을 낭비했다. 지금은 빌드 상태에 따라 로그를 줄인다. 대상은 `/api/rebuild` 의 `log` 와 `GET /api/build` 의 `log_tail` 이다.

| 상태 | 응답의 로그 |
| --- | --- |
| `ok` | 빠진다 |
| `ok_errors`·`fail` | 마지막 40줄 |
| `?log=1` 을 붙인 요청(두 경로 모두) | 다이어트 없이 전체 꼬리(4000자) |

뷰어의 오류 패널은 `?log=1` 을 항상 붙인다. 그래서 뷰어 동작은 그대로다. 내부 상태(문서의 빌드 상태 `Doc.bstate`, `builds.json`)는 다이어트와 무관하게 전체 로그를 보관한다. 다이어트는 응답을 보내기 직전의 HTTP 층 일이라 [`builds/answer.py`](../../src/limn/builds/answer.py)에 있다. [`builds/http.py`](../../src/limn/builds/http.py)의 `GET /api/build` 입구는 빌드 상태 dict에 `diet_log` 를 적용하고, `/api/rebuild` 는 결과 타입에 `rebuild_answer` 를 쓴다(`BuildOk` 면 `log` 를 빼고 나머지는 자른다). 줄 수는 둘 다 `LOG_TAIL_LINES` 다.

## 자동 동기화 (가벼운 meta 폴링)

에이전트가 `curl` 로 핀을 닫거나 원고를 고치면 몇 초 안에 뷰어 화면에 반영돼야 한다. 그런데 `GET /api/pins` 와 라이트가 아닌 `GET /api/meta` 는 **쓰기 부작용**이 있다. `sync_all` 이 앵커로 줄을 다시 맞추고 파일에 쓰기 때문이다. 그래서 이 둘을 그대로 폴링할 수는 없다.

폴링에는 `GET /api/meta?light=1` 을 쓴다. 라이트 meta는 `n_open`·`n_done` 이 빠지고 `snapshot_pins()`(sync 쓰기)를 부르지 않는다. 뷰어는 응답의 두 값이 **바뀌었을 때만** `GET /api/pins`(sync 있음)를 불러 목록을 다시 그린다. 첫 핀 읽기가 실패했거나 이후 핀·휴지통 읽기가 실패·무효화됐으면 읽은 기준값을 갱신하지 않아 다음 폴링에서 재시도한다.

- `pins_rev`: `pins.jsonl` 의 `f"{mtime_ns}:{size}:{inode}"`. 파일이 없으면 `"0"`(`pins/application.py`의 `change_token`). 뷰어는 이 값을 직전 값과 같은지만 비교한다. 핀 파일은 원자적 교체로만 쓰이고 새 파일은 옛 파일이 inode를 쥔 동안 만들어지므로, 같은 시각 틱 안에 같은 크기로 다시 써도 연속한 두 값은 inode가 달라 항상 다르다.
- `src_mtime`: 아래에서 설명한다.

그래서 변화는 몇 초 안에 화면에 들어오고, 아무 변화가 없는 동안은 `pins.jsonl` 을 건드리지 않는다.

### 원고 변화 감지

- **`src_mtime`** 은 LaTeX 문서의 빌드 루트(`Doc.src`) 아래 원고 파일의 최대 mtime이다. 대상은 `*.tex`·`*.bib`·`*.sty`·`*.cls`·`*.bst` 와 그림 확장자(`png`·`jpg`·`jpeg`·`pdf`·`eps`·`svg`)다. 제외하는 것은 다음과 같다.
  - 점(`.`)으로 시작하는 디렉토리
  - 빌드 산출물 디렉토리(`build/`·`out/`)
  - **빌드 rsync가 빼는 디렉토리(`diff/`·`diff_temporary/`)**
  - 원고 안에 둔 상태 폴더(`--state-dir`, [operations.md](operations.md) §상태 파일 배치). 빌드 사본도 이 폴더를 복사하지 않는다
  - 메인 PDF(`<main>.pdf`)
  - **같은 빌드 루트 안에 있는 다른 문서의 파일.** 폴더가 빌드 루트 안에 있는 그림 문서는 그 폴더 아래의 그림 확장자 파일이고, 보기 전용 PDF 문서는 그 PDF 파일 한 개다. 그 PDF를 담은 폴더는 빼지 않는다. `.tex`·`.bib`·`.sty`·`.cls`·`.bst` 는 어디에 있든 센다. 문서 폴더가 빌드 루트와 같거나, 빌드 루트를 품거나, 이 LaTeX 문서의 메인 `.tex` 를 품으면 아무것도 빼지 않는다. 다른 LaTeX 문서의 폴더도 빼지 않는다. 무엇을 뺄지는 기동 때 `--doc` 목록으로 정해 `Doc.apart` 에 둔다(`runtime/documents.py` 의 `apart_paths`). 경로는 심볼릭 링크를 푼 뒤 빌드 루트 기준 상대 조각으로 비교하므로, 같은 규칙이 `D.src`(`src_mtime`)와 빌드 사본(지문)에 똑같이 적용된다.

  **그 빌드가 실제로 읽은 파일은 위에서 뺐어도 센다.** 그림 세트의 파일이라도 LaTeX가 읽는 것은 다시 렌더하면 LaTeX 출력이 바뀌기 때문이다. 폴더 단위가 아니라 파일 단위로 본다.
  - 읽은 파일은 latexmk가 사본의 실행 폴더에 남기는 `.fls`(recorder 파일)의 `INPUT` 줄이 알려 준다. 빌드는 이 `.fls` 를 쪽 폴더 `<문서 상태 폴더>/pages-<빌드>/<main>.fls` 에 `.synctex.gz`·`.aux` 와 함께 둔다. 사본의 `.fls` 는 다음 빌드가 다시 쓰거나, 강제·실패 빌드가 지우기 때문이다(§따뜻한 LaTeX와 변경 없는 재빌드). 질의는 화면 빌드의 `.fls`(pick은 그 pick이 난 빌드의 것)를 읽는다. 그래서 읽은 파일을 적는 저장 필드는 `builds.json` 에도 다른 상태 파일에도 없다. 쪽 폴더의 `.fls` 는 옛 Limn 이 모르는 파일이라 되돌려도 안전하고, 쪽 폴더와 함께 지워지며, 밖으로 서빙하지 않는다.
  - 이 실행이 쓴 `.fls` 만 읽고 둔다. 실행 전후의 (mtime_ns, 크기, inode)가 달라진 일반 파일이어야 하고, 원고와 함께 사본에 딸려 온 `main.fls`(recorder를 껐을 때 남는 옛 파일)는 읽지도 두지도 않는다. 하나의 예외는 latexmk가 사본에 남은 파일을 그대로 믿게 해 준 빌드다(조건은 §따뜻한 LaTeX와 변경 없는 재빌드). 그때도 남은 `.fls` 는 그 바이트가 화면 빌드의 쪽 폴더에 있는 `.fls` 와 같을 때만 그 빌드의 것으로 읽고 둔다.
  - `INPUT` 줄에서는 빌드 사본 안의 그림 확장자 파일만 고른다. 상대 경로는 latexmk를 돌린 폴더 기준으로 푼다. 읽은 이름에 NUL 바이트가 있으면 그 줄은 버린다. 파싱한 결과는 (경로, mtime_ns, 크기, 실행 폴더, 빌드 사본 폴더)를 키로 `Doc` 마다 둔 캐시에 담는다(`Doc.input_sets`, 최대 32개, 잠금으로 보호). 문서끼리, 서버끼리 이 캐시를 나누지 않는다.
  - `.fls` 는 pdflatex가 연 파일만 적는다. bibtex가 읽는 `.bib` 은 없으므로 `.bib` 은 이 규칙이 아니라 확장자로 센다.
  - `.fls` 가 없거나(이 규칙 이전의 빌드, 지워진 쪽 폴더, `.latexmkrc` 로 recorder를 끈 경우), 일반 파일이 아니거나, 8 MiB를 넘으면 읽은 파일이 없는 것으로 본다. 제외만 적용된다. 그 빌드가 읽은 그림 세트 파일의 재렌더는 다음 빌드까지 알리지 않는다(한 번의 재빌드로 사라진다).

  값은 2초 캐시한다. 캐시 키에 어느 빌드 기준인지가 들어 있다(원고 안에 다른 문서가 없는 문서는 빌드와 무관해 키가 하나다). 캐시에 맞으면 쪽 포인터도 `.fls` 도 읽지 않는다. 새 쪽을 화면에 올리는 빌드는 `pages.cur` 를 바꾼 직후(오래된 쪽 폴더를 지우거나 git에 묻기 전에) 캐시를 비운다. 캐시를 비우는 횟수는 문서마다 세어 두고(세대), 비우기 전에 재기 시작한 값은 호출자에게는 돌려주되 저장하지 않는다. 그래서 캐시를 비운 뒤에 시작하는 읽기는 모두 새 빌드 기준이다. `force=True` 로 캐시를 건너뛸 수 있다. 빌드 지문(§위치 추정 (`est`))도 같은 파일 목록을 본다.
- **`build_src_mtime`** 은 빌드를 **시작할 때** 캐시를 건너뛰고 실측한 `src_mtime` 이다. 빌드가 그림 세트 파일을 읽었으면 그 파일들의 mtime까지 이 값에 반영한다. 읽은 파일은 컴파일이 끝나야 알기 때문에, 빌드는 컴파일 전에 사본을 한 번 훑어 파일마다 해시와 mtime을 적어 두고 컴파일 뒤에 `.fls` 로 고른다. 이 값에 넣는 mtime은 그 훑기에서 잰 값이다. 해시는 사본에서 구하지만 mtime은 원고 트리(`Doc.src`)의 같은 파일에서 읽는다. 사본 도구가 mtime을 초 단위로만 남길 수 있고(macOS의 rsync), 사본의 값으로 기준을 삼으면 원고가 자기 빌드보다 그 소수부만큼 새롭게 보이기 때문이다. 원고 쪽 값이 사본의 값과 1초 넘게 다르거나 심볼릭 링크면, 복사한 뒤 원고가 바뀐 것이므로 사본의 값을 쓴다. 훑기에 없던 파일(latexmk가 만든 `…-eps-converted-to.pdf` 같은 것)은 읽은 파일로 치지 않는다. 컴파일 중에 건드려진 파일이 기준을 컴파일 중의 원고 편집 뒤로 밀어, 그 편집을 가리는 일이 없게 하려는 것이다. 빌드가 `ok`·`ok_errors` 로 끝났을 때만 `<state_dir>/built_src_mtime.txt` 에 확정해 기록한다. 빌드가 실패하면 화면은 옛 PDF 그대로이므로, 이 값과 "원고 수정됨" 배지도 그대로 남아야 하기 때문이다. 옛 인스턴스는 이 파일이 없어 값이 `null` 이다. 이때 뷰어는 `built_at` 시각과 비교한다.
- **`stale_build`·`src_age_s`** 는 서버가 판정한다. `stale_build` 는 원고가 화면 빌드의 시작 시점 `src_mtime` 보다 2초 넘게 새로운지다. 원고는 위의 파일 목록이다. 같은 빌드 루트 안의 그림 문서나 보기 전용 PDF를 다시 렌더해도 그 LaTeX 문서의 `stale_build` 는 켜지지 않고, 그 빌드가 읽은 파일일 때만 켜진다. 판정이 참이면 "원고 수정됨 · N분 전" 배지가 뜨고, 이때만 [PDF 재빌드] 버튼이 강조된다. 브라우저 시계는 쓰지 않는다.

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
- **`src_hash`** 는 빌드 사본의 원고 파일을 (상대경로, 내용)으로 해시한 값이다. 파일 목록은 `src_mtime` 과 같다. 즉 `diff/`·`diff_temporary/`, 점 디렉토리, 메인 PDF, 같은 빌드 루트 안의 다른 문서의 파일을 뺀다. 그 빌드가 읽은 그림 세트 파일은 넣는다. 읽은 파일은 컴파일 뒤에야 알 수 있으므로, 빌드는 사본의 모든 파일을 컴파일 전에 해시해 두고 컴파일 뒤에 `.fls` 로 고른다(위의 훑기와 같은 훑기다). 그래서 빌드 직후의 `src_hash` 는 같은 원고를 질의 때 다시 잰 지문과 같다. mtime은 넣지 않는다. 내용이 같으면 레이아웃도 같기 때문이다.
- **핀의 `pdf_build`.** 드래그할 때 화면에 있던 빌드 id다(pick 응답의 `pdf_build`). 핀을 만들 때와 위치를 다시 잡을 때(`loc` 에 `frac` 이 있을 때) 남긴다. 메모나 범위 텍스트 편집은 바꾸지 않는다.

### 판정 규칙

```text
est = (pin.pdf_build ≠ 지금 빌드 그리고 두 빌드의 src_hash 가 다름) 또는 sync 가 moved/lost
```

- 해시가 없으면 빌드 시작 `src_mtime` 으로 비교한다.
- 그 빌드를 이력에서 못 찾으면 추정(점선)으로 본다. 모르는 채 실선으로 그리는 편이 더 해롭기 때문이다.
- `pdf_build` 가 없는 옛 핀은 서버가 epoch 수치로 판정한다. 옛 필드명 `frac_build` 는 `pdf_build` 와 같은 뜻으로 읽는다. 찍은 시각 `at` < `built_at` 이고, 지금 빌드를 시작할 때의 `src_mtime` > `at` 이면 추정이다. `edited_at` 은 보지 않는다.

실행 정본은 [`src/limn/pins/location/position.py`](../../src/limn/pins/location/position.py)의 `pin_est`·`same_source`·`legacy_est`·`est_basis`(순수 판정, 시계를 읽지 않는다)와 문서의 빌드 이력을 한 번 읽어 그 재료(`EstContext`)를 만드는 [`src/limn/pins/location/lookup.py`](../../src/limn/pins/location/lookup.py)의 `est_context`다. `GET /api/pins`가 문서마다 이력을 한 번만, 목록에 핀이 있는 문서만 읽는 것은 [`src/limn/pins/listing/projection.py`](../../src/limn/pins/listing/projection.py)의 `pins_payload`가 정한다.

### 기동 때 지금 빌드 등록

옛 인스턴스가 만든 지금 빌드는 이력에 없을 수 있다. 기동 때 이 빌드를 이력에 한 번 올린다. 원고가 그 빌드 뒤로 안 바뀌었으면(`src_mtime` ≤ 빌드 기준 시각) 지금 원고의 지문을 그 빌드의 지문으로 삼는다. 그래야 기동 뒤 첫 핀이 원고를 안 바꾼 재빌드에서 점선으로 오탐되지 않는다.

### 왜 서버가 판정하는가

뷰어가 벽시계로 판정하면(`at`·`edited_at` 을 `built_at`·`build_src_mtime` 과 비교) 세 갈래로 틀린다.

1. 시간대 없는 `at` 을 브라우저가 현지 시각으로 푼다. 시간대에 따라 어긋난 마크가 실선으로, 방금 찍은 핀이 점선으로 그려진다.
2. 메모만 고쳐도 점선이 꺼진다.
3. 원고를 고친 뒤 옛 PDF 위에서 찍은 핀은 판정에 들어가지 못한다.

서버가 판정하므로 브라우저의 시간대와 관계없이 같은 마크가 같은 결과를 낸다.

## 보기 전용 PDF 문서

`--doc` 으로 연 `.pdf` 문서는 LaTeX 빌드가 없다. 대신 감시 스레드가 3초마다 그 PDF의 서명 `<mtime_ns>:<크기>:<inode>` 를 본다. 쪽을 그린 때의 값(`docs/<키>/pdf_sig.txt`)과 다르면 백그라운드로 쪽을 다시 그린다.

- 서명에 inode가 들어 있는 이유는 같은 크기의 두 번째 버전이 첫 버전과 같은 시각 틱 안에 떨어질 수 있어서다. 커널은 수정시각을 거친 시계 틱(수 ms) 단위로 올리므로 `mtime_ns:크기` 만으로는 두 버전이 같은 값이 되고, 감시가 첫 버전을 그려 서명을 적은 뒤에 온 두 번째 버전은 파일이 다시 바뀔 때까지 화면에 오르지 못한다. 저장·내보내기 도구는 대개 새 파일을 쓰고 이름을 바꿔 덮어쓴다(원자적 교체). 새 파일은 옛 파일이 inode를 쥔 동안 만들어지므로 연속한 두 버전은 inode가 달라 서명이 다르다. 핀 목록의 변경 표시값 `pins_rev`(§자동 동기화)가 같은 이유로 같은 형식이다.
- **알려진 한계.** 같은 파일을 제자리에서 덮어쓰는 도구(`cp` 로 덮어쓰기 등)가 같은 시각 틱 안에 같은 크기로 두 번 쓰면 세 값이 모두 같아 두 번째 버전을 놓친다. 막으려면 서명을 적을 때 수정시각이 지금과 한 틱 이내인 파일을 불확실로 표시하고 다음 차례에 내용 해시로 다시 확인해야 한다(git이 racy-git 문제를 다루는 방식). 보기 전용 PDF에는 크기 상한이 없어 그 해시가 큰 파일을 되풀이해 읽게 되고, 걸리는 경우는 드물어서 두지 않는다. 제자리 쓰기를 하는 도구가 실제로 걸리면 그때 정한다.
- 서명 형식이 바뀐 버전으로 올리면 `pdf_sig.txt` 의 옛 값은 새 값과 달라 보인다. 첫 감시 차례에 한 번 다시 그리고 새 형식을 적은 뒤로는 조용하다.
- 다시 그리기(`builds/engine.py` 의 `render_pdf_doc`)는 LaTeX 문서와 같은 빌드 경로(`run_tracked`)를 탄다. 그래서 `GET /api/build?doc=<키>` 의 `state`, `phase:"render"`, `build_seq`, 빌드 이력이 LaTeX 문서와 똑같이 움직인다. 뷰어도 재빌드가 끝난 것처럼 화면을 바꾼다.
- 지문은 PDF 내용의 해시다. 그래서 바뀐 PDF 위의 옛 핀은 점선(추정)이 된다(§위치 추정 (`est`)).
- 그리기가 실패해도 같은 파일로 되풀이하지 않는다. 파일이 바뀌면 다시 시도한다.
- `stale_build` 는 늘 `false` 다. 이 PDF가 LaTeX 문서의 빌드 루트 안에 있어도 그 LaTeX 문서의 `stale_build` 는 이 PDF의 재저장으로 켜지지 않는다. 그 LaTeX 문서가 이 PDF를 읽었을 때만 켜진다(§원고 변화 감지).
- `POST /api/rebuild?doc=<키>` 는 `400` 이다.

보기 전용 문서의 pick과 핀 규칙은 [api.md](api.md) §보기 전용 PDF 문서의 pick·핀에 있다.

## 그림 문서

`--doc` 의 경로가 `.limnmap.json` 인 문서는 그림 저장소가 낸 PDF와 요소 지도를 가져온다. Limn은 그림 저장소의 코드를 실행하지 않는다. 지도 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`), 문서 폴더의 뜻은 [domain.md](domain.md) §그림 문서에 있다.

감시 스레드는 보기 전용 PDF와 같다. 3초마다 지문을 재고, 가져온 뒤나 미룬 뒤에는 그 지문을 `docs/<키>/pdf_sig.txt` 에 적는다.

```text
지문 = <지도 mtime_ns>:<지도 크기>:<지도 inode>:<지도 해시>|<PDF mtime_ns>:<PDF 크기>:<PDF inode>
```

- 지도 쪽은 `mtime_ns:크기:inode` 에 지도 바이트의 SHA-256 앞 32자(`<지도 해시>`)를 붙인 것이다. 지도는 4 MiB 상한이라 매 차례 읽어도 길어야 몇 ms다. 내보내기 도구가 지도를 쓴 바로 뒤 같은 파일을 제자리에서 고쳐 쓰면(`pdf_sha256` 만 바꾸면 16진 문자열의 길이가 같아 크기도 같다) 두 번째 쓰기가 같은 시각 틱에 떨어져도 바이트가 다르므로 지문이 다르다. 해시가 없으면 지문이 같아, 그림 문서는 `pdf_mismatch` 로 미룬 채 다음 변경까지 멈춘다. 지도를 해석하는 일은 지문의 지도 쪽이 바뀐 차례에만 한다.
- PDF는 지도가 가리키는 파일이고 `stat` 만 본다(`mtime_ns:크기:inode`). 원자적 교체는 inode가 달라 보이지만, 같은 시각 틱 안의 같은 크기 제자리 덮어쓰기는 보기 전용 PDF와 같은 한계로 놓친다(§보기 전용 PDF 문서). 지도를 받지 않았거나, 지도가 가리키는 PDF가 문서 폴더 밖이거나 없으면 PDF 쪽은 `-` 다.
- 지도를 받을지는 지도 바이트만으로 정해지므로 지도 파일마다 하나만 기억한다. `src.file` 이 문서 폴더 밖으로 이어지는 스크립트를 가리켜도 지도는 받는다. 그 스크립트는 pick이 읽을 때 따로 판정한다([domain.md](domain.md) §그림 문서). `impl.file` 은 열리지 않는 데이터라 모양만 본다. 같은 지도를 폴더가 다른 두 문서로 등록하면 지도 판정은 같고, 문서마다 다른 것은 지도의 `pdf` 가 그 문서 폴더 안인지뿐이다.
- 가져오는 중인 문서(빌드 잠금을 쥔 동안)는 그 차례에 아무 파일도 보지 않는다. 가져오기는 잠금을 놓기 전에 지문을 적으므로, 다음 차례는 그 지문에서 이어 본다.
- 지문이 적힌 값과 다르면 지도와 PDF를 한 번씩 읽어 검사한다. 아래 순서로 보고, 처음 어긋난 것이 서버 로그의 이유 코드가 된다. 지도가 검사를 통과하는지(`map_rejected`, 지도의 모양만 본다), 지도의 `pdf` 가 문서 폴더 안인지(`pdf_outside`), 그 PDF가 있고 열리는 일반 파일인지(`pdf_missing`), 64 MiB를 넘지 않는지(`pdf_too_large`), PDF 바이트의 SHA-256이 `pdf_sha256` 과 같은지(`pdf_mismatch`) 본다.
- 하나라도 어긋나면 이번 차례는 빌드하지 않고 실패도 기록하지 않는다. 화면은 앞 빌드 그대로다. 그때 본 지문만 적고 이유를 서버 로그에 한 줄 남긴다. 적는 지문은 다음 차례의 감시가 재는 값과 같은 규칙으로 만든다. PDF는 잴 수 있지만 열리지 않으면 잰 값을 적고, 다음 차례는 방금 읽은 지도의 판정을 쓴다. 그래서 두 파일 중 하나가 다시 바뀌어야 다시 본다. 생산자가 PDF를 먼저 쓰고 지도를 나중에 쓰는 사이의 틈이 여기에 걸린다. 쓰는 순서가 거꾸로여도 두 파일이 맞는 차례에 가져온다. PDF가 64 MiB를 넘어도 같다 — 지도가 가리키는 파일이므로 해시를 보기 전에 크기부터 보고, 넘으면 그 바이트를 끝까지 읽지 않은 채 미룬다.
- 맞으면 검사한 바이트 그대로 쪽을 그린다. 그래서 검사한 PDF와 화면의 PDF가 어긋날 수 없다. 새 `pages-<build>/` 에는 쪽 이미지, PDF 사본(지도 이름에서 `.limnmap.json` 을 뺀 `<이름>.pdf`), 지도 사본 `figmap.json` 이 함께 있다. 쪽 폴더는 지금 것과 바로 앞 것을 남기므로, 옛 빌드 화면에서 한 드래그는 그 빌드의 지도로 읽는다. 변경 보기의 겹쳐 보기도 이 두 폴더를 쓴다. 바로 앞 빌드는 화면 빌드보다 이름(시각, 같은 초면 `-<n>`)이 앞선 쪽 폴더 가운데 가장 늦은 것이다. 그래서 쪽을 다 그렸지만 아직 `pages.cur` 를 옮기지 않은 새 폴더는 앞 빌드가 되지 않는다([viewer.md](viewer.md) §변경 보기).
- 빌드 경로는 보기 전용 PDF와 같은 `run_tracked` 다. 그래서 `build_seq`, 빌드 이력, 뷰어의 쪽 교체가 LaTeX 빌드와 똑같이 돈다. 이력의 `src_hash` 는 PDF 바이트의 SHA-256과 지도 바이트의 SHA-256을 이어 다시 해시한 값(앞 32자)이다. 둘 중 하나가 바뀌면 옛 핀은 점선(추정)이 된다(§위치 추정 (`est`)).
- 쪽 그리기가 실패하면 보기 전용 PDF처럼 같은 파일로 되풀이하지 않는다.
- 새 빌드가 화면에 오르면(쪽 폴더가 바뀐 뒤, 그 빌드를 기록하기 전에) 디스크의 `pins.md` 를 한 번 다시 쓴다. 그림 핀의 `요소 잃음` 은 저장하지 않는 읽기 시점 계산이라, 핀을 쓰지 않으면 디스크 파일이 옛 지도 기준으로 남기 때문이다. 쓰는 것은 `pins.md` 하나뿐이고 `pins.jsonl` 과 `rev` 는 그대로다. 다시 쓰기가 실패하면 옛 파일이 남고 가져오기는 그대로 성공한다(오류는 서버 로그에 남는다). 기동 때 가져오기도 같은 경로다. LaTeX 빌드와 보기 전용 PDF 렌더는 이 경로를 타지 않는다([api.md](api.md) §그림 핀의 행).
- 지도의 쪽 수가 PDF의 쪽 수와 달라도 가져온다. PDF에 없는 쪽의 지도 항목은 쓰이지 않는다.
- 지도 파일이 사라지면 아무것도 하지 않는다. 화면은 마지막으로 가져온 그림이다. 지도가 없는 채로는 서버가 뜨지 않는다([instances.md](instances.md) §여러 문서 (`DOCS=`)).
- 지도는 등록할 때 심볼릭 링크를 모두 푼 경로에서 읽는다. 그 자리가 나중에 심볼릭 링크로 바뀌면 따라가지 않고, 지도가 없을 때처럼 아무것도 하지 않는다. PDF는 지도의 `pdf` 를 마지막 조각까지 심볼릭 링크를 모두 푼 뒤, 그 대상이 문서 폴더 안이고 점으로 시작하는 이름 아래가 아닐 때만 받는다([domain.md](domain.md) §그림 문서). 그래서 폴더 안의 링크를 거친 PDF는 읽고, 폴더 밖으로 이어지는 링크는 `pdf_outside` 다. 읽을 때는 푼 경로를 링크를 따라가지 않고 연다. 검사한 뒤 그 자리가 링크로 바뀌었으면 이번 차례는 읽지 않는다(`pdf_missing`). 지도는 4 MiB까지만 읽는다. PDF는 64 MiB까지만 읽는다.
- 기동 때는 지문이 바뀌었거나 쪽 이미지가 없을 때 가져온다. `--no-build` 는 그림 문서에 적용하지 않는다.
- `stale_build` 는 늘 `false` 다. 이 문서의 폴더가 LaTeX 문서의 빌드 루트 안에 있어도 그 LaTeX 문서의 `stale_build` 는 이 문서의 재렌더로 켜지지 않는다. 그 LaTeX 문서가 그 파일을 읽었을 때만 켜진다(§원고 변화 감지). `POST /api/rebuild?doc=<키>` 는 보기 전용 문서처럼 `400` 이다. 그림을 고쳤으면 그림 저장소에서 다시 렌더한다.
- 감시가 아닌 경로로 추적 빌드가 그림 문서를 가져오다 두 파일이 맞지 않으면, 실패를 `BuildAborted("figure_unready")` 로 기록한다(§빌드 결과).
- 에이전트가 이 문서의 핀을 `ref` 와 함께 검토 대기로 닫으면, 닫기를 쓰기 전에 원격 main을 한 번 당기고(`--git-pull` 일 때, §자동 확인의 라운드 그대로) 감시의 한 차례를 요청 스레드에서 돌린다(`refresh_watched_now`). 감시 스레드가 이미 가져오는 중이면 그 빌드 잠금을 60초까지 기다린 뒤 본다. 지도와 PDF가 맞으면 감시와 같은 추적 빌드로 가져오고, 맞지 않거나 바뀐 것이 없으면 아무것도 하지 않는다. 그래서 "처리됨" 알림이 60초 자동 확인과 3초 감시를 기다리지 않는다([api.md](api.md) §닫을 때 사유 남기기). 보기 전용 PDF도 같다(바뀌었으면 다시 그린다).
