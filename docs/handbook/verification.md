# 검증 — 무엇을 재고 언제 합격인가

이 topic은 Limn의 변경이 합격인지 판단하는 게이트를 모은다. 각 게이트마다 무엇을 재는지, 어떤 변경에서 돌리는지, 어떻게 돌리는지, 무엇이면 통과인지, 그리고 통과가 무엇까지 보장하는지를 적는다. PR을 올리기 전, 리뷰할 때, 새 테스트나 CI 단계를 더할 때 읽는다. 게이트를 더하거나 합격 기준을 바꾸면 이 파일을 같은 변경에서 고친다.

> **한눈에**
>
> - 자동 게이트: §1 파이썬 테스트, §2 인스턴스 관리자 테스트, §3 설치 스모크
> - 사람이 확인하는 게이트: §4 에이전트 계약 호환, §5 화면 실측
> - 아직 없는 게이트: §6 정량 게이트가 없는 영역
> - 문서 출판: §7 Handbook 출판
> - 정적 검사: §8 Ruff·ShellCheck, §9 타입 검사
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
| 측정 대상 | 서버 동작(저장소·역변환·빌드·API 경계·보안 검사·접근 제어), CLI, migrate, 뷰어 정적 구조와 JS 순수 함수, 디자인 토큰 가드, UI 영어 대응표, 이름·개인정보 위생 |
| 적용 조건 | `src/`, `tests/`, `docs/`, `skill/`, `README*.md`를 건드리는 모든 변경 |
| 실행 | `uv sync --group dev` 뒤 `uv run pytest -q -rs`. 브라우저 레이아웃 테스트까지 돌리려면 먼저 `uv run playwright install chromium` |
| 합격 기준 | 실패 0. CI에서는 `LIMN_TEST_REQUIRE_BROWSER=1`이라 Chromium을 못 띄우면 건너뛰지 않고 **실패**다. Python 3.10과 3.12 두 행렬 모두 통과해야 한다. CI `macos` 작업(0.3.3)이 macOS에서도 같은 테스트를 돌린다. 거기서는 TeX·Chromium 테스트가 건너뛰어지고, `/bin/bash` 3.2가 PATH 맨 앞이다 |
| 보장 범위 | 테스트가 고정한 동작만 보장한다. CI의 테스트 작업은 전체 이력(`fetch-depth: 0`)을 받아, 옛 릴리스를 `git show` 로 불러 비교하는 테스트(v0.1.0 이관, v0.2.2 이벤트 대조)도 돈다. 얕은 클론에서는 건너뛴다. CI에는 TeX(`latexmk`)와 Poppler가 없어서 실제 빌드가 필요한 테스트는 CI에서 `skipped`로 남는다. `-rs`가 건너뛴 이유를 출력하니 확인한다 |

테스트 파일마다 맡은 범위가 다르다.

| 파일 | 맡은 범위 |
| --- | --- |
| [`tests/test_server.py`](../../tests/test_server.py) | 서버 전반. 처리기를 소켓 쌍으로 직접 몰아 포트를 열지 않는다. `Frontend*` 클래스는 뷰어 HTML·CSS·JS 규칙을 지킨다 (예: `FrontendDesignTokens`, `FrontendNoNestedOutlines`) |
| [`tests/test_cli.py`](../../tests/test_cli.py) | `limn` 명령 표면: version, serve 전달, 도움말 |
| [`tests/test_migrate.py`](../../tests/test_migrate.py) | 옛 설치에서 옮기기 (systemctl 스텁) |
| [`tests/test_access.py`](../../tests/test_access.py) | 접근 제어: 신원 방식, 토큰, 역할별 허용 범위, 바인드 규칙, 0.1 상태 디렉터리 호환 |
| [`tests/test_i18n.py`](../../tests/test_i18n.py) | UI 영어 대응표와 `tl()` 틀 배선, 영어 화면에 한글이 남지 않는지(브라우저), 계약 문자열은 번역하지 않는지 |
| [`tests/test_naming.py`](../../tests/test_naming.py) | 앱 이름은 Limn 하나, 개인정보 없음, README 두 벌이 서로 링크하는지 |
| [`tests/test_qa_021.py`](../../tests/test_qa_021.py) | 0.2.0 E2E QA에서 나온 결함의 회귀 테스트: @태그 알림 규칙, `/api/clear` 소유자 전용, 주체×진입 경로×동작 행렬(루프백·테일넷·토큰·trusted-proxy × 읽기·핀·답글·닫기·확인·지우기), `pins.md` claim 줄, CLI 로그인 검증·바쁜 포트, 403 안내 페이지, 절 표시, 역할별 화면(브라우저) |
| [`tests/test_pins_lifecycle.py`](../../tests/test_pins_lifecycle.py) | `limn.pins`가 순수한지(import 검사), 레코드가 `pin_state()`와 같은 규칙으로 상태 타입이 되는지, 확인·닫기·다시 열기·답글·claim·휴지통 전이가 상태마다 맞는 결과를 돌려주고 필드 순서·모르는 필드·입력 레코드를 지키는지, 스레드 id 규칙 |
| [`tests/test_mapping.py`](../../tests/test_mapping.py) | `limn.mapping`이 순수한지(표준 라이브러리 순수 모듈만 가져오고 `C.`·`cur_doc()`을 읽지 않음), 떠 있는 환경 목록을 인자로 받아 그대로 따르는지 |
| [`tests/test_viewer_files.py`](../../tests/test_viewer_files.py) | 뷰어 파일 세 개가 패키지에 있고, `index.html`의 CSS·JS 표식이 한 번씩이며, 서버가 조립한 HTML에 두 파일이 그대로 들어가는지. 표식이 틀리면 시작 단계에서 실패하는지 |
| [`tests/test_build.py`](../../tests/test_build.py) | `limn.build`가 서버 전역(`C`, `cur_doc()`, 문서 목록, 옛 전역 잠금·상태)을 읽지 않고 서버를 가져오지 않는지, `latex_errors`, 두 문서가 인자만으로 동시에 빌드되고(가짜 latexmk가 서로를 기다림) 결과·이력·빌드 폴더가 섞이지 않는지. TeX 없이 가짜 `latexmk`·`pdftoppm`을 PATH에 둔다 |
| [`tests/test_build_copy.py`](../../tests/test_build_copy.py) | 빌드 첫 단계인 원고 복사가 실패하면(`rsync` 비정상 종료) 사본을 컴파일하지 않고 빌드를 실패로 끝내는지 |
| [`tests/test_v03.py`](../../tests/test_v03.py) | 0.3(이슈 #9, [ADR-0005](../adr/0005-pin-scoped-changes.md)): hunk 블록 파싱과 귀속(겹침, 줄 밀림을 거친 대응, 한 커밋의 핀 셋, 이름 바꾸기, 지운 범위, 기록한 `changes` 가 추정을 이기는 순서), 핀 hunk의 실제 줄 번호와 맥락, 합성 적용(실제 git으로 만든 무작위 편집 왕복·`git apply` 대조), `changes` 검사·저장·다시 열기, `pins.md` 닫기 줄, 핀 단위 소스 diff·비교 PDF HTTP와 캐시 키, 실제 격리 빌드(TeX가 있을 때만, CI는 건너뜀), 뷰어(데스크톱 1400×850·폴드 842×758·폰 384×832 × 한국어·영어: 다른 변경 접기·펴기, [커밋 전체 비교] 토글, 컴파일 실패 시 커밋 전체로 넘어감), 순수 판단의 직접 테스트(`ScopeDecisions`: `changes_at` 규칙, 합성 판에 쓸 파일, 거부 이유 표), 새 거부마다의 상태 코드·본문(`ScopedErrorBodies`), 스쿼시 커밋 하나가 핀 셋을 고치고 머지 뒤 `changes`·`PR #N (해시)`로 닫는 흐름, 다시 여는 답글의 이벤트가 0.2.2와 같은지(v0.2.2 모듈과 대조, 얕은 클론이면 건너뜀), viewer 휴지통에 [되살리기]·[영구 삭제]가 없는지(브라우저) |
| [`tests/test_v031.py`](../../tests/test_v031.py) | 0.3.1(이슈 #10): 메모 mention 재알림 간격의 순수 판단(`note_mention_targets`: 키 세 부분, 10분 경계, 답글 mention 제외, 시각 없는·먼 기록)과 핀 조작을 거친 흐름(가짜 시계로 태그 껐다 켜기 세 번 = 알림 하나, 10분 뒤 다시, `note_append`, 답글·다시 연 이유는 매번), `audit.jsonl`(`EVENTS_KEEP`+1건 회전 뒤에도 `cleared` 가 남음, 영구 삭제, 거부된 요청은 적지 않음, 권한 0600, 덧붙이기만, 쓰기 실패는 경고, 스레드 동시 쓰기, `limn token`·`limn member` 가 OS 계정으로 적고 토큰 원문·해시는 적지 않음) |
| [`tests/test_token_file.py`](../../tests/test_token_file.py) | 0.3.3([ADR-0007](../adr/0007-agent-token-file.md)): `limn token create --save`(파일 `0600`·폴더 `0700`, 토큰을 찍지 않음, `--print`·`--force`, 기존 파일·git 작업 트리·인스턴스 없음 거부는 토큰을 만들기 전에, 쓰기 실패면 새 토큰을 폐기), `limn token path`, `token list` 가 파일의 토큰을 밝힘, `token revoke` 가 그 토큰의 파일만 지움. 서버: 파일이 생기면 `pins.md` 인증 안내 줄에 구절 하나(토큰은 없음, 원격 `GET /pins.md` 에는 없음, 파일을 읽지 않음), loopback 에이전트를 끈 인스턴스의 헤더 없는 로컬 요청 `401` 메시지, 프록시를 거친 요청은 옛 문구, 폐기된 토큰 `401`, `LIMN_AGENT_TOKEN_FILE`. 인스턴스 관리자와 실제 서버(보기 전용 PDF, TeX 없이): loopback 에이전트 켬·끔에서 `limn status`·`start` 가 토큰 파일을 curl 표준 입력으로 보냄(명령줄에 없음), `401` 안내, 심링크·남의 권한·형식이 틀린 파일 거부 |
| [`tests/test_v032.py`](../../tests/test_v032.py) | 0.3.2(이슈 #7, [ADR-0006](../adr/0006-relative-pin-paths.md)): 핀 파일 위치의 순수 판단(`pin_rel_path`: 원고 안의 `file` 우선, 꼬리가 맞는 `file_rel`, 넓힌 원고 폴더의 더 긴 꼬리, 가장 긴 꼬리, `..`·절대·빈 값 거부), 두 서버 실행 사이에 원고 폴더를 옮긴 흐름(응답의 지금 `file`·`rel_path`, `pins.md` 하위 폴더와 인용, anchor 줄 맞춤, `lo`/`hi` 수정, 겹침, 휴지통·되살리기, 그대로 옮긴 뒤 읽기는 다시 쓰지 않음, mtime 이 오래된 다른 내용의 사본도 다시 맞춤, 옛 체크아웃으로 돌아가면 그 줄로 돌아감, 옮긴 파일에서 anchor 를 채우지 않음, 넘친 `note_append` 의 `400` 은 아무것도 바꾸지 않음), 클론한 저장소에서 핀 단위 [변경 보기], 원고 밖으로 남아야 하는 경우(꼬리가 맞지 않음, `..`·절대 `file_rel`, 바깥을 가리키는 심볼릭 링크 — 바깥 줄이 새지 않는지), v0.3.0·v0.3.1 모듈이 이 상태를 읽고 그 버전의 위치 다시 잡기가 낡은 `file_rel` 을 이기는지(얕은 클론이면 건너뜀) |
| [`tests/test_v022.py`](../../tests/test_v022.py) | 0.2.2(이슈 #8): 답글 규칙표의 모든 행(서버 `reply_reopens`와 뷰어 `replyReopens`가 같은지), 답글 API(`reopen`·`reopened`·`state`, 이벤트, `pins.md`의 다시 연 이유), 휴지통(작성자 알림, 30일 숨김·삭제, 소유자 전용 영구 삭제), 뷰어 순수 함수(결과 한 줄, 구획 상태, 남은 날, 삭제된 `#N`), 브라우저 흐름을 데스크톱 1400×850·폴드 842×758(터치)·폰 384×832(터치) × 한국어·영어로(답글·되돌리기·상태 유지, 완료 행 답글, 삭제·휴지통 되살리기, 소유자 영구 삭제, 구획 머리의 접기·기억·`새 N`) |

> **주의**
>
> 일부 테스트는 문서 문장을 직접 확인한다. 예를 들어 [api.md](api.md)의 claim 한도 행(`eta_min` 1..240, `ttl_min` 1..120)과 [SKILL.ko.md](../../skill/SKILL.ko.md)의 견적 표가 그렇다. 이 문장을 고치면 테스트도 함께 고친다.

## 2. 인스턴스 관리자 테스트

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `limn add`·`start`·`stop`·`update`·`list`·`status`·`url`·`snippet`·`doc`·`remove`·`run`의 동작과 출력 |
| 적용 조건 | [`src/limn/instances.sh`](../../src/limn/instances.sh), [`src/limn/cli.py`](../../src/limn/cli.py), systemd 유닛 템플릿을 바꿀 때. CI는 항상 돌린다 |
| 실행 | `bash tests/test_instances.sh`. 파이썬은 `LIMN_TEST_PYTHON`, 그다음 PATH의 3.10 이상 `python3`·`python3.1x`, 그다음 이 체크아웃의 `.venv`를 쓴다(macOS의 `/usr/bin/python3`은 3.9라 건너뛴다) |
| 합격 기준 | 스크립트가 0으로 끝난다. CI는 Linux(bash 5)와 macOS(`/bin/bash` 3.2, BSD 명령) 두 곳에서 돌린다 |
| 보장 범위 | systemctl·tailscale·ss·uv를 가짜로 바꿔 호스트를 건드리지 않고 확인한다. 실제 systemd·tailscale과의 상호작용은 보장하지 않는다. BSD `stat`은 가짜 명령으로도 한 번 흉내 낸다(§15). 토큰 파일과 실제 서버의 상호작용은 [`tests/test_token_file.py`](../../tests/test_token_file.py)가 맡는다 |

## 3. 설치 스모크

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 패키지가 `uv tool install`로 설치되고, 실행 파일과 번들 자산이 들어가는지 |
| 적용 조건 | `pyproject.toml`, 패키지 데이터(`vendor/`, `systemd/`, `instances.sh`, `ui_en.json`)를 바꿀 때. CI `install` 작업이 항상 돈다 |
| 실행 | `uv tool install .` 뒤 `limn version`, `limn serve --help`, `limn serve --version`, `limn help` |
| 합격 기준 | 명령이 모두 성공하고 PDF.js 번들, `limn@.service` 템플릿, `instances.sh`, 뷰어 `viewer/app.js`가 설치 경로에 있다 |
| 보장 범위 | 설치와 실행 입구까지다. 실제 원고 빌드는 확인하지 않는다 |

## 4. 에이전트 계약 호환

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `pins.md` 형식(열·표시어·한국어 머리말)과 HTTP API(경로·JSON 필드·상태 이름)가 옛 에이전트를 깨지 않는지 |
| 적용 조건 | 핀 렌더링, 요청 처리, 레코드 필드, 상태 계산을 건드리는 변경 |
| 실행 | 사람이 diff를 [api.md](api.md)와 대조한다. PR 템플릿의 계약 체크 항목에 표시한다. `PinsMdV2` 같은 기존 테스트가 형식 일부를 고정한다 |
| 합격 기준 | 경로·필드·상태 이름의 삭제나 의미 변경이 없다. 추가만 있다면 [api.md](api.md)가 같은 변경에서 갱신됐다. 바꿔야 한다면 이슈에서 버전이 붙은 이전 계획이 먼저 합의됐다 |
| 보장 범위 | 사람 확인이다. 계약 전체를 자동으로 비교하는 테스트는 아직 없다 (§6) |

## 5. 화면 실측

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | 뷰어 레이아웃·간격·상태 표시가 [viewer.md](viewer.md)의 규칙대로 보이는지 |
| 적용 조건 | `src/limn/viewer/`의 CSS·마크업·레이아웃 JS를 바꿀 때 |
| 실행 | Playwright로 세 너비(`wide`·`mid`·`narrow`)와 두 테마에서 바꾸기 전후 스크린샷을 짝지어 비교한다. 바꾼 규칙에 해당하는 수치(버튼 높이, 위치 이동량 등)를 잰다 |
| 합격 기준 | 바꾼 규칙이 측정값으로 확인되고, 바꾸지 않은 화면에 회귀가 없다. 수치는 [viewer.md](viewer.md)의 해당 절에 날짜와 함께 남긴다 |
| 보장 범위 | 헤드리스 Chrome 에뮬레이션이다. 실제 기기(Galaxy Z Fold 7, iOS)의 가상 키보드·관성 핀치는 보장하지 않는다 |

## 6. 정량 게이트가 없는 영역

아래는 아직 자동 게이트가 없다. 통과라고 추정하지 말고 "확인하지 않음"으로 보고한다.

| 영역 | 현재 상태 | 계획 |
| --- | --- | --- |
| 포매터·스타일 규칙 | 정량 게이트 없음. Ruff는 버그 후보 규칙만 켰다 (§8) | [code-style-roadmap.md](code-style-roadmap.md) R4: 전체 포매팅 커밋과 함께 넓힌다 |
| 타입 검사 (옮기지 않은 모듈) | `server.py`·`cli.py`·`migrate.py`는 검사하지 않는다. 옮긴 모듈만 §9가 검사한다 | [code-style-roadmap.md](code-style-roadmap.md) R8·7단계: 모듈을 옮기는 대로 `[tool.mypy]`의 `files`에 더한다 |
| 실제 LaTeX 빌드 | CI에 TeX가 없어 로컬에서만 돈다 | 필요해지면 TeX 설치 작업을 CI에 더하는 것을 검토 |
| Handbook 링크·형식 | §7 출판기 `check`가 검사하지만 CI에서는 돌리지 않는다 | 폰트를 CI에 준비할 방법을 정한 뒤 CI에 추가 검토 |
| 에이전트 계약 전체 비교 | 정량 게이트 없음 (§4는 사람 확인) | 계약 스냅숏 테스트 검토 |

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
| 측정 대상 | 파이썬: 문법 오류, 쓰지 않는 import, 정의되지 않은 이름, 흔한 버그 패턴(`B`), 종료 코드를 정하지 않은 `subprocess.run`(`PLW1510`). 셸: `instances.sh`와 `test_instances.sh`의 ShellCheck 경고 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다 |
| 실행 | `uv sync --group dev` 뒤 `uv run ruff check`, `uv run shellcheck src/limn/instances.sh tests/test_instances.sh`. 두 도구 모두 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 두 명령이 0으로 끝난다. 규칙을 끄려면 그 줄에 이유를 적은 주석과 함께 끈다 (예: `# shellcheck disable=SC2016` 위에 이유 한 줄) |
| 보장 범위 | 켠 규칙만이다. 규칙 목록은 `pyproject.toml`의 `[tool.ruff.lint]`가 정본이다. 포매팅·스타일·docstring은 아직 검사하지 않는다 (§6). 타입은 §9가 본다. `src/limn/vendor/`와 플러그인에서 복사한 `tools/handbook-publish/`는 검사에서 뺀다 |

## 9. 타입 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `server.py`에서 옮겨 낸 모듈(`src/limn/pins/`, `src/limn/mapping.py`, `src/limn/build.py`, `src/limn/files.py`)의 타입 오류. strict 모드라 표기 누락, 타입 인자 없는 `list`·`dict`, `Any` 반환, `None` 가능성을 좁히지 않은 사용도 오류다. 합 타입에 대한 `match`가 경우 하나를 빠뜨리면 `exhaustive-match`로 실패한다 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다. 모듈을 새로 옮기면 같은 PR에서 `[tool.mypy]`의 `files`에 더한다 |
| 실행 | `uv sync --group dev` 뒤 `uv run mypy`. 검사할 파일과 설정(`strict`, `python_version = "3.10"`, `exhaustive-match`)은 `pyproject.toml`의 `[tool.mypy]`가 정본이다. mypy는 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 명령이 0으로 끝난다. `# type: ignore`는 쓰지 않는 것이 기본이고, 꼭 필요하면 오류 코드를 적고(`# type: ignore[arg-type]`) 그 줄에 이유를 단다. `cast`도 같다 |
| 보장 범위 | 목록에 든 파일의 정적 타입뿐이다. 이 모듈을 부르는 `server.py`는 검사하지 않으므로, 호출하는 쪽이 잘못된 값을 넘기는 것은 잡지 못한다. 저장된 JSON 레코드는 `Mapping[str, Any]`라 필드 값의 타입도 보지 않는다 |

**mypy를 고른 이유.** 순수 파이썬 휠이라 `uv run`만으로 돌고, CI에 Node 같은 다른 런타임을 준비할 필요가 없다. pyright의 PyPI 배포판은 Node 런타임이 필요해서, 없으면 처음 돌 때 내려받거나 Node 바이너리 패키지를 따로 설치해야 한다. mypy도 `match`의 빠진 경우를 잡는다 (`exhaustive-match`, 반환값이 있는 함수는 `Missing return statement`까지). 2026-09-26 `limn/pins/lifecycle.py`의 `confirm()`에서 `case DonePin():`을 지워 보았을 때 `uv run mypy`가 두 오류로 실패했다.

```text
src/limn/pins/lifecycle.py:49: error: Missing return statement  [return]
src/limn/pins/lifecycle.py:51: error: Match statement has unhandled case for values of type "DonePin"  [exhaustive-match]
```

## 결과를 보고하는 법

- 실제로 돌린 명령과 결과만 적는다. 돌리지 않은 게이트는 "돌리지 않음"이라고 쓴다.
- 건너뛴 테스트(`skipped`)는 개수와 이유를 함께 적는다. 건너뜀은 통과가 아니다.
- 화면 변경은 어느 너비·테마에서 무엇을 쟀는지 적는다.
- 실패를 재시도로 통과시켰다면 그 사실을 숨기지 않는다. 재시도는 원인 해결의 증거가 아니다.
