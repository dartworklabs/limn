# 검증 — 무엇을 재고 언제 합격인가

이 topic은 Limn의 변경이 합격인지 판단하는 게이트를 모은다. 각 게이트마다 무엇을 재는지, 어떤 변경에서 돌리는지, 어떻게 돌리는지, 무엇이면 통과인지, 그리고 통과가 무엇까지 보장하는지를 적는다. PR을 올리기 전, 리뷰할 때, 새 테스트나 CI 단계를 더할 때 읽는다. 게이트를 더하거나 합격 기준을 바꾸면 이 파일을 같은 변경에서 고친다.

> **한눈에**
>
> - 자동 게이트: §1 파이썬 테스트, §2 인스턴스 관리자 테스트, §3 설치 스모크
> - 사람이 확인하는 게이트: §4 에이전트 계약 호환, §5 화면 실측
> - 아직 없는 게이트: §6 정량 게이트가 없는 영역
> - 문서 출판: §7 Handbook 출판
> - 정적 검사: §8 Ruff(린트·포매팅)·ShellCheck, §9 타입 검사
> - 동작을 바꾸지 않는 구조 변경의 증명: §구조 이동의 동작 불변 증명(차등 비교)
> - 결과 보고 규칙: §결과를 보고하는 법

## 합격의 뜻

Limn에서 "테스트가 녹색"은 합격의 필요조건이지 충분조건이 아니다. [architecture.md](architecture.md) §채택한 설계 축에서 정한 검수 진실원은 세 겹이다.

1. 자동 테스트가 녹색이다.
2. 에이전트 계약(`pins.md`, HTTP API)이 호환을 지킨다.
3. 화면을 바꿨다면 실제 화면에서 규칙대로 보이는지 실측했다.

게이트는 머지 전에 막는다. CI([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml))가 `main` 푸시, `v*` 태그, 모든 PR에서 돈다.

## 1. 파이썬 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 서버 동작(저장소·역변환·빌드·API 경계·보안 검사·접근 제어), CLI, migrate, 뷰어 정적 구조와 JS 순수 함수, 디자인 토큰 가드, UI 영어 대응표, 이름·개인정보 위생, Handbook 참조 |
| 적용 조건 | `src/`, `tests/`, `docs/`, `skill/`, `README*.md`를 건드리는 모든 변경 |
| 실행 | `uv sync --group dev` 뒤 `uv run pytest -q -rs`. 브라우저 레이아웃 테스트까지 돌리려면 먼저 `uv run playwright install chromium` |
| 합격 기준 | 실패 0. CI에서는 `LIMN_TEST_REQUIRE_BROWSER=1`이라 Chromium을 못 띄우면 건너뛰지 않고 **실패**다. 같은 작업에 `LIMN_TEST_REQUIRE_NODE=1`도 있어서, node가 없으면 뷰어 스크립트 문법 검사(`test_viewer_files`)도 **실패**다. Python 3.10과 3.12 두 행렬 모두 통과해야 한다. CI `macos` 작업이 macOS에서도 같은 테스트를 돌린다. 거기서는 TeX·Chromium 테스트가 건너뛰어지고, `/bin/bash` 3.2가 PATH 맨 앞이다. 실제 TeX 도구가 필요한 테스트(`tex` 마커)는 CI `tex` 작업이 따로 돌린다. 그 작업에서는 `LIMN_TEST_REQUIRE_TEX=1`이라 도구가 없으면 **실패**다 |
| 보장 범위 | 테스트가 고정한 동작만 보장한다. CI의 테스트 작업은 전체 이력(`fetch-depth: 0`)을 받아, 옛 릴리스를 `git show` 로 불러 비교하는 테스트(v0.1.0 이관, v0.2.2 이벤트 대조)도 돈다. 얕은 클론에서는 건너뛴다. `test`·`macos` 작업에는 TeX와 Poppler가 없어서 실제 빌드가 필요한 테스트는 거기서 `skipped`로 남는다. `-rs`가 건너뛴 이유를 출력하니 확인한다. 그 테스트는 CI `tex` 작업이 돌린다(아래) |

**TeX 테스트와 CI `tex` 작업.** 실제 `latexmk` 빌드·쪽 렌더, pick 끝까지, `--git-pull` 빌드, 보기 전용 PDF 렌더, bwrap 격리 비교 빌드를 돌리는 테스트는 [`tests/helpers.py`](../../tests/helpers.py)의 `needs_tex(*도구)` 데코레이터를 단다. 데코레이터는 도구가 PATH에 없으면 무엇이 없는지 적고 건너뛰고(`LIMN_TEST_REQUIRE_TEX=1`이면 실패), pytest 마커 `tex`를 붙인다. 새 TeX 테스트도 이 데코레이터를 쓴다. 그래야 `tex` 작업이 고른다. 비교 빌드가 부르는 bwrap 명령 두 개(latexdiff, latexmk)의 인자 목록 전체는 TeX 없이 도는 `test_revisions.py`의 `test_comparison_build_runs_exactly_these_sandbox_commands`가 바이트 단위로 고정한다. 격리 인자를 바꾸는 변경은 이 테스트의 기대값을 함께 고치고, 그 차이가 곧 격리의 변경이다.

| 항목 | 내용 |
| --- | --- |
| 실행 | CI `tex` 작업(Ubuntu 24.04, Python 3.12)이 apt로 `latexmk`, `texlive-latex-base`, `texlive-plain-generic`(latexdiff 출력이 쓰는 `ulem`), `latexdiff`, `poppler-utils`, `bubblewrap`을 `--no-install-recommends`로 설치하고 `uv run pytest -q -rs -m tex`를 돌린다. 로컬에서는 같은 도구가 있으면 `uv run pytest -q -rs -m tex` |
| 격리 준비 | 러너는 AppArmor가 권한 없는 사용자 네임스페이스를 막는다(`kernel.apparmor_restrict_unprivileged_userns=1`). 작업은 `/usr/bin/bwrap`에만 `userns`를 허용하는 AppArmor 프로필을 설치한다. sysctl과 bwrap 인자는 그대로다 |
| 합격 기준 | 실패 0, 건너뜀 0 |
| 보장 범위 | Ubuntu 패키지 TeX Live의 pdfLaTeX로 짧은 픽스처 원고를 빌드하는 경로만 본다. macOS·MacTeX, 다른 엔진, 큰 원고, 원고 패키지는 보지 않는다 |

테스트 파일은 아래 규칙으로 놓인다. 파일마다의 자세한 범위는 각 테스트 모듈의 docstring에 있다. 새 테스트는 이 규칙에 맞는 파일에 둔다.

| 파일 | 맡은 범위 |
| --- | --- |
| `tests/test_<모듈>.py` | 그 모듈을 지킨다(`test_pins_lifecycle.py`는 `limn/pins/lifecycle.py`, `test_web_parse.py`는 `limn/web/parse.py`). 순수 모듈은 서버 없이 값으로 직접 테스트하고, 순수하지 않은 것을 가져오지 않는지 import 검사로 지킨다. 옮긴 모듈은 서버 전역(`C`, 문서 목록)을 읽지 않는지도 본다. 파일 끝의 클래스가 `server.py`를 거쳐 그 모듈의 연결을 보기도 한다 |
| [`tests/test_access_module.py`](../../tests/test_access_module.py), [`tests/test_access.py`](../../tests/test_access.py), [`tests/test_security.py`](../../tests/test_security.py) | 접근 제어와 보안 강화(보안 경계). 첫째는 `limn/access.py`를 서버 없이, 둘째는 처리기를 거쳐 신원 방식·토큰·역할·바인드 규칙과 옛 상태 디렉터리 호환을 본다. 셋째는 처리기 끝까지(소켓 쌍) 점으로 시작하는 이름 아래 파일과 원고 안에 둔 상태 폴더의 거절(그런 상태 폴더의 기동 경고·거절 포함), 쓸 수 없는 `people.json`이 권한을 주지 않고 다시 쓰이지 않는지, 모든 응답의 프레이밍 금지 헤더를 본다 |
| [`tests/test_server.py`](../../tests/test_server.py) | `server.py` 자신의 함수와, 요청이 처리기와 서버 배선을 끝까지 지나는 동작. 처리기를 소켓 쌍으로 직접 몬다(포트를 열지 않는다). 기능의 HTTP 경로(claim·종류와 스레드·검토·겹침)는 여기 두고, 그 규칙·저장 필드·`pins.md` 줄은 지키는 모듈의 파일에 둔다 |
| [`tests/test_reply.py`](../../tests/test_reply.py), [`tests/test_trash.py`](../../tests/test_trash.py), [`tests/test_notifications.py`](../../tests/test_notifications.py), [`tests/test_access_paths.py`](../../tests/test_access_paths.py), [`tests/test_moved_paths.py`](../../tests/test_moved_paths.py), [`tests/test_token_file.py`](../../tests/test_token_file.py), [`tests/test_build_copy.py`](../../tests/test_build_copy.py) | 여러 모듈을 건너는 기능 하나. 답글 규칙의 경로, 휴지통과 전체 비우기, 알림, 주체×진입 경로, 옮긴 원고, 에이전트 토큰 파일, 빌드의 원고 복사. 파일 이름은 기능 이름이다 |
| [`tests/helpers.py`](../../tests/helpers.py) | 테스트가 아니라 공용 도구. `server.py`를 파일에서 한 번 읽은 사본(`ps`)과 그것을 임시 원고·상태 폴더에 맞추는 `Base`, 원고 픽스처, 소켓 쌍 요청 도우미, 뷰어 스크립트를 node로 돌리는 도우미, TeX 도구 검사 `needs_tex`. 서버 사본이 둘이면 `C`·문서 목록·잠금도 둘이 되므로, 서버를 부르는 테스트 파일은 모두 여기서 가져온다 |
| [`tests/test_contract_snapshot.py`](../../tests/test_contract_snapshot.py) | 에이전트 계약의 스냅숏. 정해진 핀 흐름을 처리기로 몰아 응답마다의 상태·본문, 쓰기마다의 `pins.md`, 끝의 핀 목록 응답을 [`tests/data/contract_snapshot.json`](../../tests/data/contract_snapshot.json)과 바이트 단위로 비교한다. 계약을 일부러 바꿀 때만(설계 승인 뒤) `LIMN_RECORD_SNAPSHOT=1`로 다시 기록하고, JSON의 차이가 곧 계약의 변경이다 |
| [`tests/test_pins_model.py`](../../tests/test_pins_model.py) | 레코드 왕복. 레코드 모양 말뭉치 [`tests/data/pin_records.jsonl`](../../tests/data/pin_records.jsonl)을 상태 타입으로 파싱해 다시 쓰면 바이트가 같은지 보고, 공통 필드(`PinCore`)와 상태 필드가 어떤 값을 올리고 어떤 값을 저장된 그대로 두는지 본다. 새 레코드 모양을 쓰는 코드를 더하면 말뭉치에도 더한다 |
| `tests/test_viewer*.py` | 뷰어. `test_viewer.py`는 배포되는 HTML·CSS 구조와 JS 순수 함수, 실제 Chromium의 레이아웃 회귀(`Frontend*` 가드), `test_viewer_files.py`는 조각과 순서 목록·`node --check`, `test_viewer_source.py`는 토큰으로 읽은 JS(정확한 함수 떼어 내기, 아무도 부르지 않거나 두 번 선언한 함수, `//` 주석 끝에 붙어 돌지 않는 코드 문장, 닫힌 값 표와 서버 값의 대조), `test_viewer_assemble.py`는 조립, `test_viewer_input.py`는 마우스·터치 입력, `test_viewer_browser.py`는 실제 Chromium에서 기능 흐름(답글·휴지통·딥 링크·핀 단위 변경 보기·보기 역할). 뷰어 JS가 서버 규칙을 따라 하는 곳은 같은 말뭉치를 양쪽에 돌려 결과를 대조한다(`test_mentions_parity.py`: 뷰어 `mentionScan()`과 서버 `resolve_mentions()`) |
| [`tests/test_errors.py`](../../tests/test_errors.py), [`tests/test_i18n.py`](../../tests/test_i18n.py), [`tests/test_naming.py`](../../tests/test_naming.py) | 여러 모듈에 걸친 위생. 모든 거절 본문의 안정 코드 `reason`과 영어 문장, UI 영어 대응표와 계약 문자열의 비번역, 앱 이름과 개인정보 |
| [`tests/test_handbook_refs.py`](../../tests/test_handbook_refs.py) | Handbook 참조. `§절 제목` 참조가 실제 절을 가리키는지, topic이 적은 `src/`·`tests/` 경로가 있는지, topic 산문에 날짜가 없는지 |
| [`tests/test_instances.sh`](../../tests/test_instances.sh) | 인스턴스 관리자(§2) |

테스트 파일 이름에 릴리스·이슈 번호를 쓰지 않는다. 릴리스나 결함의 회귀 테스트도 지키는 모듈이나 기능의 파일에 두고, 그 출처(릴리스·이슈·QA 결함)는 절 주석과 클래스 docstring에 남긴다. 옛 릴리스와의 호환을 보는 테스트는 이름에 그 릴리스를 적는다(`RollbackToV030`, `test_reopening_reply_events_equal_the_released_v0_2_2`).

테스트 파일은 서로를 픽스처로 가져오지 않는다. 공용 도구는 [`tests/helpers.py`](../../tests/helpers.py)(서버 사본, `Base`, 뷰어 원문 `viewer_text`, 쪽 그림 `blank_png`, 뷰어의 `esc`를 그대로 꺼내는 `js_esc`, 뷰어 함수를 떼어 내는 `extract_js_fn`, 답글 규칙 표 `RULE_CASES`, 비교 보기용 `minimal_pdf`), [`tests/helpers_js.py`](../../tests/helpers_js.py)(JS 토크나이저와 최상위 함수·닫힌 값 표 찾기), [`tests/helpers_access.py`](../../tests/helpers_access.py)(신원 `ALICE`·`BOB`·`CAROL`·`DAVE`, `AccessBase`, 토큰·멤버 도우미, `ScopedRepo`, `MovedManuscriptBase`), [`tests/helpers_browser.py`](../../tests/helpers_browser.py)(Chromium 실행기 `ChromiumTestCase`, `BrowserBase`)에만 둔다. 테스트를 파일 사이로 옮기거나 클래스 이름을 바꾸는 변경은 [`tools/test_id_map.py`](../../tools/test_id_map.py)로 잃은 테스트가 없음을 보인다: `uv run python tools/test_id_map.py --ref origin/main --map <이름표>`가 수집한 테스트 ID를 파일을 뺀 (클래스, 테스트) 키로 맞춰 보고, 이름표(옛 이름 -> 새 이름, `+` 새 테스트)에 없는 잃음·중복·새 테스트가 하나라도 있으면 0이 아닌 값으로 끝난다. `--results`에 두 실행의 JUnit XML과 `-rA` 출력을 주면 통과·건너뜀·subtest 수도 맞춰 본다.

> **주의**
>
> 일부 테스트는 문서 문장을 직접 확인한다. [api.md](api.md)의 claim 한도 행(`eta_min` 1..240, `ttl_min` 1..120)과 답글 예시, [instances.md](instances.md)의 한 문장, [SKILL.ko.md](../../skill/SKILL.ko.md)의 견적 표가 그렇다. `test_viewer.py`는 모든 topic에서 옛 버튼 이름을 찾는다. 문서만 고쳐도 §1을 돌리고, 걸린 테스트는 함께 고친다.

## 2. 인스턴스 관리자 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `limn add`·`start`·`stop`·`update`·`list`·`status`·`url`·`snippet`·`doc`·`remove`·`run`의 동작과 출력 |
| 적용 조건 | [`src/limn/instances.sh`](../../src/limn/instances.sh), [`src/limn/cli.py`](../../src/limn/cli.py), systemd 유닛 템플릿을 바꿀 때. CI는 항상 돌린다 |
| 실행 | `bash tests/test_instances.sh`. 파이썬은 `LIMN_TEST_PYTHON`, 그다음 PATH의 3.10 이상 `python3`·`python3.1x`, 그다음 이 체크아웃의 `.venv`를 쓴다(macOS의 `/usr/bin/python3`은 3.9라 건너뛴다) |
| 합격 기준 | 스크립트가 0으로 끝난다. CI는 Linux(bash 5)와 macOS(`/bin/bash` 3.2, BSD 명령) 두 곳에서 돌린다 |
| 보장 범위 | systemctl·tailscale·ss·uv를 가짜로 바꿔 호스트를 건드리지 않고 확인한다. 실제 systemd·tailscale과의 상호작용은 보장하지 않는다. BSD `stat`은 가짜 명령으로도 한 번 흉내 낸다. 토큰 파일과 실제 서버의 상호작용은 [`tests/test_token_file.py`](../../tests/test_token_file.py)가 맡는다 |

## 3. 설치 스모크

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 패키지가 `uv tool install`로 설치되고, 실행 파일과 번들 자산이 들어가는지 |
| 적용 조건 | `pyproject.toml`, 패키지 데이터(`vendor/`, `systemd/`, `instances.sh`, `ui_en.json`, `viewer/`)를 바꿀 때. CI `install` 작업이 항상 돈다 |
| 실행 | `uv tool install .` 뒤 `limn version`, `limn serve --help`, `limn serve --version`, `limn help` |
| 합격 기준 | 명령이 모두 성공하고 PDF.js 번들, `limn@.service` 템플릿, `instances.sh`, 뷰어 `viewer/index.html`·`viewer/parts.txt`와 조각 `viewer/css/tokens.css`·`viewer/js/events.js`가 설치 경로에 있다. 파일 하나라도 없으면 그 자리에서 실패한다 |
| 보장 범위 | 설치와 실행 입구까지다. 실제 원고 빌드는 확인하지 않는다 |

## 4. 에이전트 계약 호환

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `pins.md` 형식(열·표시어·한국어 머리말)과 HTTP API(경로·JSON 필드·상태 이름)가 옛 에이전트를 깨지 않는지 |
| 적용 조건 | 핀 렌더링, 요청 처리, 레코드 필드, 상태 계산을 건드리는 변경 |
| 실행 | 자동: [`tests/test_contract_snapshot.py`](../../tests/test_contract_snapshot.py)가 고정된 핀 흐름 하나의 응답과 `pins.md`를 기록된 스냅숏과 바이트 단위로 비교한다. 사람: diff를 [api.md](api.md)와 대조하고 PR 템플릿의 계약 체크 항목에 표시한다 |
| 합격 기준 | 스냅숏 테스트가 녹색이다. 경로·필드·상태 이름의 삭제나 의미 변경이 없다. 추가만 있다면 [api.md](api.md)가 같은 변경에서 갱신됐고, 스냅숏 흐름에도 그 경로를 더했다. 바꿔야 한다면 이슈에서 버전이 붙은 이전 계획이 먼저 합의됐다 |
| 보장 범위 | 스냅숏은 그 흐름이 지나는 경로와 필드만 바이트 단위로 지킨다. 흐름 밖의 경로·필드는 경로별 테스트와 사람 확인에 기댄다 (§6) |

## 5. 화면 실측

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 뷰어 레이아웃·간격·상태 표시가 [viewer.md](viewer.md)의 규칙대로 보이는지 |
| 적용 조건 | `src/limn/viewer/`의 CSS·마크업·레이아웃 JS를 바꿀 때 |
| 실행 | Playwright로 세 너비(`wide`·`mid`·`narrow`)와 두 테마에서 바꾸기 전후 스크린샷을 짝지어 비교한다. 바꾼 규칙에 해당하는 수치(버튼 높이, 위치 이동량 등)를 잰다 |
| 합격 기준 | 바꾼 규칙이 측정값으로 확인되고, 바꾸지 않은 화면에 회귀가 없다. 잰 값과 스크린샷은 PR 설명에 남긴다. [viewer.md](viewer.md)에는 채택한 값과 그 이유만 적는다 |
| 보장 범위 | 헤드리스 Chrome 에뮬레이션이다. 실제 기기(Galaxy Z Fold 7, iOS)의 가상 키보드·관성 핀치는 보장하지 않는다 |

## 6. 정량 게이트가 없는 영역

아래는 자동 게이트가 없거나 일부만 있다. 통과라고 추정하지 말고 "확인하지 않음"으로 보고한다.

| 영역 | 현재 상태 | 계획 |
| --- | --- | --- |
| docstring | 정량 게이트 없음. Ruff의 `D` 규칙은 켜지 않았다 (§8) | [code-style-roadmap.md](code-style-roadmap.md) §다음: 새 모듈부터 켜고, 손대는 모듈마다 넓힌다 |
| 테스트 파일의 타입 | `tests/`는 타입 검사 대상이 아니다. 패키지(`src/limn/`)는 전부 §9가 검사한다 | 테스트가 타입으로 잡을 결함을 놓치는 일이 생기면 대상에 더하는 것을 검토 |
| 실제 LaTeX 빌드 | CI `tex` 작업이 Ubuntu 패키지 TeX Live의 pdfLaTeX로 픽스처 원고만 빌드한다 (§1). macOS·MacTeX와 다른 엔진은 로컬에서만 돈다 | 그 환경의 결함이 나오면 해당 러너·엔진을 `tex` 작업에 더하는 것을 검토 |
| Handbook 형식 | §7 출판기 `check`가 검사하지만 CI에서는 돌리지 않는다. 파일 사이의 `§절 제목` 참조, topic이 적은 경로, topic 산문의 날짜는 §1의 `tests/test_handbook_refs.py`가 CI에서 본다 | 폰트를 CI에 준비할 방법을 정한 뒤 출판 검사를 CI에 추가 검토 |
| 스냅숏 흐름 밖의 계약 | 경로별 테스트가 필드 일부를 고정하지만, 응답 전체를 바이트 단위로 비교하지는 않는다 (§4) | 계약을 더하는 PR이 스냅숏 흐름에도 그 경로를 더한다 |

## 7. Handbook 출판

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | Handbook이 작성 표준(목록·role 배정·H1 하나·강조 상자 label·코드 언어·단순 표·내부 링크와 절 대상)을 지키고 한 장짜리 HTML로 묶이는지 |
| 적용 조건 | `docs/handbook/`, `docs/adr/`, `docs/handbook/book.json`, `tools/handbook-publish/`를 바꿀 때 |
| 실행 | 폰트를 `.handbook/fonts/Pretendard-Regular.otf`에 둔 뒤 `uv run python tools/handbook-publish/publish.py check docs/handbook/index.md`, 이어서 `uv run python tools/handbook-publish/publish.py build docs/handbook/index.md --output .handbook/out/index.html` |
| 합격 기준 | 두 명령이 0으로 끝난다. 폰트 SHA-256과 Pandoc 버전은 `book.json`의 값과 정확히 같아야 한다 |
| 보장 범위 | 형식과 링크 대상까지다. 내용이 코드와 맞는지는 보장하지 않는다. PDF 출판은 `book.json`에 고정한 Playwright·Chromium이 따로 필요하다 |

## 8. 정적 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 파이썬: 문법 오류, 쓰지 않는 import, 정의되지 않은 이름, 흔한 버그 패턴(`B`), 종료 코드를 정하지 않은 `subprocess.run`(`PLW1510`), 스타일 규칙(`E`·`W`, import 순서 `I`, 옛 문법 `UP`, 단순화 `SIM`), 그리고 코드 모양이 `ruff format`의 출력과 같은지. 셸: `instances.sh`와 `test_instances.sh`의 ShellCheck 경고 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다 |
| 실행 | `uv sync --group dev` 뒤 `uv run ruff check`, `uv run ruff format --check`, `uv run shellcheck src/limn/instances.sh tests/test_instances.sh`. 포매팅이 어긋나면 `uv run ruff format`이 고친다. 두 도구 모두 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 세 명령이 0으로 끝난다. 규칙을 끄려면 그 줄에 이유를 적은 주석과 함께 끈다 (예: `# shellcheck disable=SC2016` 위에 이유 한 줄). 포매터를 `# fmt: off`로 끄는 것은 정말 표 모양인 데이터에만 쓴다 |
| 보장 범위 | 켠 규칙만이다. 규칙 목록과 끈 규칙은 `pyproject.toml`의 `[tool.ruff.lint]`가 정본이고, 끈 이유는 [code-style-roadmap.md](code-style-roadmap.md) §R4에 있다. docstring(`D`)은 아직 검사하지 않는다 (§6). 타입은 §9가 본다. 뷰어 JS에는 린터가 없고, §1의 `test_viewer_files`가 node로 문법을, `test_viewer_source`가 토큰으로 죽은 함수·주석에 삼켜진 문장·닫힌 값 표를 본다 |

## 9. 타입 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `src/limn/` 아래의 모든 파이썬 파일(`[tool.mypy]`의 `files = ["src/limn"]`)의 타입 오류. strict 모드라 표기 누락, 타입 인자 없는 `list`·`dict`, `Any` 반환, `None` 가능성을 좁히지 않은 사용도 오류다. 합 타입에 대한 `match`가 경우 하나를 빠뜨리면 `exhaustive-match`로 실패한다 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다. `src/limn/` 아래에 새 파일을 만들면 따로 등록하지 않아도 검사된다 |
| 실행 | `uv sync --group dev` 뒤 `uv run mypy`. 설정(`strict`, `python_version = "3.10"`, `exhaustive-match`)은 `pyproject.toml`의 `[tool.mypy]`가 정본이다. mypy는 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 명령이 0으로 끝난다. `# type: ignore`는 쓰지 않는 것이 기본이고, 꼭 필요하면 오류 코드를 적고(`# type: ignore[arg-type]`) 그 줄에 이유를 단다. `cast`도 같다 |
| 보장 범위 | 패키지의 정적 타입이다. 조립 지점 `server.py`가 옮긴 모듈에 넘기는 값과 협력자(`PinContext`, `RevisionContext`, 저장소의 레코드 검사)의 서명도 검사한다. HTTP 처리기는 `_ModuleApp`(모든 속성이 `Any`)으로 `server.py`에 닿지만, `server.py` 끝의 `if TYPE_CHECKING:` 대입이 모듈 자체를 `web/app.py`의 `App`과 맞춰 보므로 빠진 연결과 서명이 틀린 연결도 mypy 오류다. `tests/test_web.py`는 실행 때 이름이 모두 있는지를 따로 확인한다. 보지 못하는 것: 저장된 JSON 레코드와 응답은 `Mapping[str, Any]`·`dict[str, Any]`라 필드 값의 타입을 보지 않는다(모양은 계약 스냅숏·레코드 왕복 테스트가 지킨다). 테스트 파일은 대상이 아니다 |

**mypy를 고른 이유.** 순수 파이썬 휠이라 `uv run`만으로 돌고, CI에 Node 같은 다른 런타임을 준비할 필요가 없다. pyright의 PyPI 배포판은 Node 런타임이 필요해서, 없으면 처음 돌 때 내려받거나 Node 바이너리 패키지를 따로 설치해야 한다. mypy도 `match`의 빠진 경우를 잡는다. `limn/pins/lifecycle.py`의 `confirm()`에서 `case DonePin():`을 지우면 `uv run mypy`가 두 오류로 실패한다(줄 번호는 생략).

```text
src/limn/pins/lifecycle.py: error: Missing return statement  [return]
src/limn/pins/lifecycle.py: error: Match statement has unhandled case for values of type "DonePin"  [exhaustive-match]
```

## 구조 이동의 동작 불변 증명(차등 비교)

코드를 다른 모듈로 옮기거나 셸을 바꾸는 변경은 동작을 바꾸지 않는다고 약속한다. 전체 테스트 녹색은 테스트가 고정한 동작만 보장하므로, 옮긴 가지를 모두 지나는 **차등 비교**로 그 약속을 증명한다.

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 같은 입력에 대해 기준 커밋과 이 변경이 같은 응답과 같은 저장 바이트를 내는지 |
| 적용 조건 | 동작 불변을 약속하는 구조 변경(모듈 이동, 셸·연결 정리, 결과 타입으로 바꾸기). 동작을 바꾸는 변경에는 쓰지 않는다 |
| 실행 | 아래 절차 |
| 합격 기준 | 모든 경우가 같다. 차이를 맞춰 비교한 값(벽시계에서 오는 값 등)은 무엇을 왜 맞췄는지 PR에 적는다 |
| 보장 범위 | 돌린 경우만이다. 경우 목록이 옮긴 가지와 거절을 모두 지나는지는 리뷰가 확인한다 |

절차는 이렇다.

1. 기준 커밋의 소스를 따로 꺼낸다(`git archive <기준> src | tar -x -C <기준 폴더>`).
2. 기준과 이 변경을 **따로 된 프로세스**에서 돌린다. 한 프로세스에 둘을 올리면 `sys.modules`의 `limn.*`을 함께 써서, `limn/` 안의 변경이 자기 자신과 비교된다.
3. 입력을 고정한다. 시계(`now_str`, `time.time`), 원고 파일의 mtime, 같은 고정 임시 경로, 환경 변수를 두 쪽에 똑같이 준다. 상태 폴더 경로는 다른 작업과 겹치지 않게 고른다.
4. 같은 요청(또는 같은 `limn` 명령)을 차례로 보낸다. 옮긴 가지마다, 그리고 거절마다 적어도 한 경우를 넣는다.
5. 비교한다. 요청은 상태 코드, `Date`·`Server`를 뺀 헤더, 본문을 본다. 단계마다 상태 폴더의 모든 파일의 바이트와 권한을 본다. 명령은 stdout·stderr·종료 코드를 본다.
6. 비교가 차이를 잡는지 한 번 증명한다. 이 변경 쪽에 일부러 차이(문구 한 글자, 필드 순서)를 심고 비교가 실패하는지 확인한 뒤 되돌린다.
7. 경우 수와 결과, 맞춘 값은 PR 설명에 남긴다. Handbook에는 적지 않는다([workflow.md](workflow.md) §문서 동기화).

## 결과를 보고하는 법

- 실제로 돌린 명령과 결과만 적는다. 돌리지 않은 게이트는 "돌리지 않음"이라고 쓴다.
- 건너뛴 테스트(`skipped`)는 개수와 이유를 함께 적는다. 건너뜀은 통과가 아니다.
- 화면 변경은 어느 너비·테마에서 무엇을 쟀는지 적는다.
- 실패를 재시도로 통과시켰다면 그 사실을 숨기지 않는다. 재시도는 원인 해결의 증거가 아니다.
