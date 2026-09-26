# 검증 — 무엇을 재고 언제 합격인가

이 topic은 Limn의 변경이 합격인지 판단하는 게이트를 모은다. 각 게이트마다 무엇을 재는지, 어떤 변경에서 돌리는지, 어떻게 돌리는지, 무엇이면 통과인지, 그리고 통과가 무엇까지 보장하는지를 적는다. PR을 올리기 전, 리뷰할 때, 새 테스트나 CI 단계를 더할 때 읽는다. 게이트를 더하거나 합격 기준을 바꾸면 이 파일을 같은 변경에서 고친다.

> **한눈에**
>
> - 자동 게이트: §1 파이썬 테스트, §2 인스턴스 관리자 테스트, §3 설치 스모크
> - 사람이 확인하는 게이트: §4 에이전트 계약 호환, §5 화면 실측
> - 아직 없는 게이트: §6 정량 게이트가 없는 영역
> - 문서 출판: §7 Handbook 출판
> - 정적 검사: §8 Ruff(린트·포매팅)·ShellCheck, §9 타입 검사
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
| 합격 기준 | 실패 0. CI에서는 `LIMN_TEST_REQUIRE_BROWSER=1`이라 Chromium을 못 띄우면 건너뛰지 않고 **실패**다. 같은 작업에 `LIMN_TEST_REQUIRE_NODE=1`도 있어서, node가 없으면 뷰어 스크립트 문법 검사(`test_viewer_files`)도 **실패**다. Python 3.10과 3.12 두 행렬 모두 통과해야 한다. CI `macos` 작업(0.3.3)이 macOS에서도 같은 테스트를 돌린다. 거기서는 TeX·Chromium 테스트가 건너뛰어지고, `/bin/bash` 3.2가 PATH 맨 앞이다 |
| 보장 범위 | 테스트가 고정한 동작만 보장한다. CI의 테스트 작업은 전체 이력(`fetch-depth: 0`)을 받아, 옛 릴리스를 `git show` 로 불러 비교하는 테스트(v0.1.0 이관, v0.2.2 이벤트 대조)도 돈다. 얕은 클론에서는 건너뛴다. CI에는 TeX(`latexmk`)와 Poppler가 없어서 실제 빌드가 필요한 테스트는 CI에서 `skipped`로 남는다. `-rs`가 건너뛴 이유를 출력하니 확인한다 |

테스트 파일마다 맡은 범위가 다르다.

| 파일 | 맡은 범위 |
| --- | --- |
| [`tests/test_server.py`](../../tests/test_server.py) | `server.py` 자체. 조립 루트의 함수와 연결(`app_version`, `build_html`·`favicon_href`, 저장소에 넘기는 `valid_rec`, `default_pdfjs_dir`, 프로세스를 끝내는 곳은 `main()` 하나인지)과 처리기가 쓰는 빌드 응답의 로그 다이어트(`limn.web.answers.diet_log`), 처리기를 소켓 쌍으로 직접 몰아(포트를 열지 않는다) 요청이 처리기와 서버 배선을 끝까지 지나는 동작: 요청 밀수·Host/Origin 검사(`Smuggling`, `CrossOrigin`), 정적 경로(`ApiVersion`, `VendorPdfjs`, `PdfRoute`), `GET /pins.md`의 기준 주소(`RemotePinsMd`), 빌드 응답 줄이기(`ResponseDiet`, `RebuildLogDiet`), 여러 문서(`MultiDoc`), 소켓 도우미(`SocketHarness`). API·`pins.md`·뷰어를 함께 건너는 기능 클래스도 여기 둔다: 겹침과 메모 덧붙이기(`Overlaps`), 처리 중 표시의 견적(`ClaimEta`, `ClaimEtaDocs`), 겹침 배지 문구(`BadgeWording`), 핀 종류와 스레드(`KindAndThread`), 검토 대기(`ReviewState`), @태그·사람·이벤트(`MentionsPeopleEvents`), 브라우저 알림(`NotifyServer`). 한 모듈이 주제인 테스트는 그 모듈의 파일(`tests/test_<모듈>.py`)에, 뷰어 화면은 `test_viewer.py`에 있다 |
| [`tests/helpers.py`](../../tests/helpers.py) | 테스트가 아니라 공용 도구. `server.py`를 파일에서 한 번 읽은 사본(`ps`)과 그것을 임시 원고·상태 폴더에 맞추는 `Base`, 원고 픽스처(`TEX`, `MINI_PDF`), 소켓 쌍 요청 도우미(`req`·`jreq`·`split_resp`·`shut_wr`), 처리기 아래의 핀 추가·편집·선택(`add_pin`·`edit_pin`·`pick`·`revision_spec`), 뷰어 스크립트를 node로 돌리는 `extract_js_fn`·`run_node`. 서버 사본이 둘이면 `C`·문서 목록·잠금도 둘이 되므로, 서버를 부르는 테스트 파일은 모두 여기서 가져온다 |
| [`tests/test_viewer.py`](../../tests/test_viewer.py) | 뷰어 화면(`src/limn/viewer/`)의 `Frontend*` 가드. 배포되는 `ps.HTML`의 HTML·CSS 구조(예: `FrontendDesignTokens`, `FrontendNoNestedOutlines`, `FrontendIcons`, `HtmlTemplateStructure`, `PinNumberJump`), node로 떼어 돌리는 JS 순수 함수(`...Logic`, `FrontendDocs`, `FrontendArchive`, `FrontendMentions` 등, node가 없으면 건너뜀), 실제 Chromium의 레이아웃·키보드 회귀(`FrontendResponsiveBrowser`) |
| [`tests/test_revisions.py`](../../tests/test_revisions.py) | 원고 이력과 비교(`limn.revisions`)를 서버의 배선(`revision_context`)과 HTTP 경로로, 실제 임시 git 저장소에서: 최신 변경의 diff와 핀 단위 범위, 임의 커밋·잘못된 id 거절, 빌드 루트를 나눠 쓰는 문서마다 따로인 이력, 큰 diff 자르기, 첫 부모 규칙, 스냅숏의 심볼릭 링크·gitlink 거절, 스냅숏 목차, 비동기 비교 빌드의 중복 제거·캐시·실패 뒤 재시도, 출처·필드 검사, 작업 수 한도와 캐시 만료, 격리 실행 필수·출력과 시간 한도, 실제 격리 빌드(TeX가 있을 때만) |
| [`tests/test_cli.py`](../../tests/test_cli.py) | `limn` 명령 표면: version, serve 전달, 도움말 |
| [`tests/test_migrate.py`](../../tests/test_migrate.py) | 옛 설치에서 옮기기 (systemctl 스텁) |
| [`tests/test_access.py`](../../tests/test_access.py) | 접근 제어: 신원 방식, 토큰, 역할별 허용 범위, 바인드 규칙, 0.1 상태 디렉터리 호환 |
| [`tests/test_startup.py`](../../tests/test_startup.py) | `limn serve` 시작 규칙(`limn.startup`·`limn.args`·`limn.config`)을 서버 없이 직접: 세 모듈이 서버를 가져오지 않고 `C`를 읽지 않고 `sys.exit`을 부르지 않는지, `AccessOptions` 필드가 같은 이름의 `Cfg` 설정이고 접근 인자 없는 명령줄이 `Cfg` 기본값(v0.1과 같은 동작)으로 시작하는지, 접근 거절마다의 정확한 문구와 먼저 걸리는 거절의 순서(보안 경계), 받아들인 값(loopback 에이전트·`insecure`), 시작 로그 줄, 포트 확인과 거절 한 줄, 문서·메인 파일 거절 순서와 상태 폴더, 라벨·색, 시작 요약 줄, 파서가 넘겨받은 설명·버전·기본값. 저장소 URL의 이름, 기본 라벨, `--label` 다듬기와 길이 거절, 색 형식과 라벨별 색(`RepoNameFromUrl`·`DefaultLabel`·`LabelValidation`·`AccentValidation`), `--doc` 해석과 `make_docs`(`DocArgs`, 서버 사본의 `C`를 문서 경로로 넘긴다), 패키지 버전(`Version`) |
| [`tests/test_access_module.py`](../../tests/test_access_module.py) | `limn.access`·`limn.guidance`를 서버 없이 직접: `access.py`가 `C`·서버·감사 기록 모듈을 읽지 않는지, `people.json` 형식을 가져오는 `limn.people`이 표준 라이브러리와 `limn.files`만 가져오는지(서버·저장소·알림·HTTP 없음), `limn member`가 쓰는 `people.json`이 `people_text` 그대로인지, `guidance.py`가 순수한지(import 검사), 모든 거절이 같은 상태·`reason`·안내 페이지로 던져지는지(잘못된·폐기된·빈·두 번 온 토큰, 원격 피어의 신원 헤더, 사람이 아닌 로그인, 프록시를 거친 헤더 없는 요청, 로컬 에이전트 끔, 신뢰하지 않는 프록시, 멤버 아님, `--allow` 밖, 역할별 POST), `AccessSettings`에 기본값이 없어 빠진 설정이 옛 허용 값으로 채워지지 않는지, IP가 아닌 피어는 신뢰하는 프록시도 루프백도 아닌지(`::ffff:127.0.0.1`은 루프백), 캐시가 파일이 바뀔 때만 다시 읽고 상태 폴더마다 따로인지(다른 폴더를 읽고 돌아와도), stat할 수 없는 파일은 옛 값 대신 다시 읽어 토큰을 받지 않는지, 경고가 한 번만 나는지, 토큰·멤버 상태 도우미가 거절 때 아무것도 쓰지 않고 감사 기록을 순서대로 남기는지 |
| [`tests/test_i18n.py`](../../tests/test_i18n.py) | UI 영어 대응표와 `tl()` 틀 배선, 영어 화면에 한글이 남지 않는지(브라우저, 흔한 거절의 오류 알림 포함), 계약 문자열은 번역하지 않는지 |
| [`tests/test_moved_paths.py`](../../tests/test_moved_paths.py) | ADR-0006 후속(이슈 #24): 꼬리를 핀의 문서 폴더에 이어 찾는 순수 규칙(다른 문서의 파일은 고르지 않음, 이름을 바꾼 문서 폴더, 1·2는 좁히지 않음, `..` 범위는 아무것도 못 찾음), 여러 문서 인스턴스를 옮긴 흐름, 읽기가 `file_rel` 을 채우지 않음, 클론한 저장소에서 `changes` 로 닫은 핀이 `source:"changes"` 로 남고 저장값은 그대로인지, 맞지 않는 경로·바깥을 가리키는 링크는 버리는지 |
| [`tests/test_brand.py`](../../tests/test_brand.py) | Limn 마크: PNG가 올바른 RGBA이고 타일은 인스턴스 색·글리프는 흰색이며 16px에서 점과 줄이 따로 읽히는지, 파비콘 SVG·인라인 SVG(색 리터럴 없음)·세 자리(탐색 줄·[더보기] 칩·도움말 머리)·`<head>` 링크, PNG 경로가 인스턴스 색으로 그리는지, 브라우저에서 16px·토큰 색으로 그려지는지(밝게·어둡게) |
| [`tests/test_errors.py`](../../tests/test_errors.py) | 모든 오류 본문에 안정 코드 `reason` 이 있는지(`HTTPError` 는 `reason` 없이 만들 수 없고, 오류 사전 글자에도 있다. 정적 검사는 `server.py`, 거절 본문을 만드는 옮긴 모듈(`revisions.py`·`scope.py`·`documents.py`·`locate.py`), 접근 경계 `limn/access.py`와 `limn/web/`의 모든 모듈을 읽는다), 흔한 거절의 한국어 `error` 문장·상태가 그대로인지, 서버가 내는 코드마다 영어 문장이 있고 낡은 문장이 없는지, 뷰어 `errText()` 가 영어에서는 코드로·한국어에서는 서버 문장 그대로 보이는지 |
| [`tests/test_naming.py`](../../tests/test_naming.py) | 앱 이름은 Limn 하나, 개인정보 없음, README 두 벌이 서로 링크하는지 |
| [`tests/test_qa_021.py`](../../tests/test_qa_021.py) | 0.2.0 E2E QA에서 나온 결함의 회귀 테스트: @태그 알림 규칙, `/api/clear` 소유자 전용, 주체×진입 경로×동작 행렬(루프백·테일넷·토큰·trusted-proxy × 읽기·핀·답글·닫기·확인·지우기), `pins.md` claim 줄, CLI 로그인 검증·바쁜 포트, 403 안내 페이지, 절 표시, 역할별 화면(브라우저). 브라우저 테스트 공용 `BrowserBase`도 여기 있다 — `open()`은 뷰어 `boot()`가 핀 목록(열림·검토·완료)을 다 읽고 폴링을 시작한 뒤(`LIGHT_TIMER`)에 돌려준다. `META`만 기다리면 핀 목록이 늦게 오는 CI에서 완료 핀을 모르는 채 `showChange()`가 아무 일도 안 해 멈췄다(`BrowserOpenWaitsForPins`가 목록을 1.5초 늦춰 고정한다) |
| [`tests/test_pins_lifecycle.py`](../../tests/test_pins_lifecycle.py) | `limn.pins`가 순수한지(import 검사, `render.py`가 가져오는 `limn.guidance`·`limn.mapping`도 문자열 모듈만 가져오고 `pathlib`에서는 `PurePath`만 쓰는지), 레코드가 `state_of()` 규칙으로 상태 타입이 되는지, 확인·닫기·다시 열기·답글·claim·휴지통 전이가 상태마다 맞는 결과를 돌려주고 필드 순서·모르는 필드·입력 레코드를 지키는지, 스레드 id 규칙, `pins.md`의 다시 열림 판단(`ReopenedInRound`: 마지막 닫기 뒤의 다시 열기, 확인이 끼어도) |
| [`tests/test_pins_model.py`](../../tests/test_pins_model.py) | 레코드 왕복: 테스트 전체가 읽고 쓴 레코드 모양 147건([`tests/data/pin_records.jsonl`](../../tests/data/pin_records.jsonl))과 옛 모양·어긋난 값 24건을 상태 타입으로 파싱해 다시 쓰면 저장소의 `json.dumps` 설정으로 바이트가 같은지, 상태마다 어떤 필드를 속성으로 올리는지(열림의 claim, 닫힘의 닫은 기록, 완료의 확인, 휴지통의 삭제 기록), 없거나 종류가 틀린 값이 어떻게 남는지, 상태와 어긋난 `done`·`review`를 생성자가 거절하는지 |
| [`tests/test_pins_edit.py`](../../tests/test_pins_edit.py) | `limn.pins.edit`의 순수 판단: 닫힌 핀의 위치 변경·낡은 `base_rev`·덧붙인 메모 길이·파일 밖 줄 범위를 거절 값으로 돌려주는지와 그 순서, 줄 범위가 바뀐 것으로 치는 조건, 편집이 쓰는 필드와 그 순서(위치 다시 잡기의 page·frac 유지, `via`·`score` 지우기, anchor, 담당 스레드 줄), 새 줄 핀·영역 핀 레코드의 필드 순서 |
| [`tests/test_pins_render.py`](../../tests/test_pins_render.py) | `pins.md` 렌더(`limn.pins.render`)를 서버 없이 입력 값(`PinsMdInput`)만으로: `C`·서버·시계를 읽지 않고 같은 입력에 같은 글자를 내며 레코드를 고치지 않는지, 머리줄 건수·빌드 도장 줄·저장소 줄, 토큰 파일 구절은 로컬 독자에게만 붙는지, 번호 칸 표시의 순서와 사람 이름, claim이 입력 시계로 재지는지, 칸 이스케이프, 작성자 2명부터의 `[이름]`, 스레드 마지막 3건, 긴 줄 인용의 600자 경계와 범위 종류, 영역 핀, 여러 문서·설정에 없는 문서의 소절, 검토 대기 표. 옛 코드와 바이트가 같은지는 처리기를 거치는 다른 파일과 옮길 때의 차등 비교가 지킨다. 끝의 `PinsMdV2`·`BuildHeadInPinsMd`·`AuthorPrefixInPinsMd`·`InstanceIdInPinsMd`는 `server.py`를 거쳐 핀을 쓴 뒤 디스크의 `pins.md`를 본다(포함 파일의 상대 경로, 닫힌 핀은 늘리지 않음, 칸 이스케이프, 인용 자르기, 기준 커밋 줄, 작성자 접두, 논문·저장소 줄과 원격 확인 안내) |
| [`tests/test_guidance.py`](../../tests/test_guidance.py) | 토큰 파일 문구(`limn.guidance`): `shell_path`의 `~/`·따옴표 규칙, 헤더 없는 로컬 요청의 401 문구가 파일이 있을 때·없을 때·모를 때 무엇을 붙이는지, curl 형태가 토큰 대신 파일을 가리키는지 |
| [`tests/test_mapping.py`](../../tests/test_mapping.py) | `limn.mapping`이 순수한지(표준 라이브러리 순수 모듈만 가져오고 `C.`·`cur_doc()`을 읽지 않음), 떠 있는 환경 목록을 인자로 받아 그대로 따르는지. 끝의 `Ladder`는 서버의 기본 떠 있는 환경으로 픽스처 원고의 범위 사다리(표 안 문단, 소절 앞에서 멈춤)를 본다 |
| [`tests/test_pins_record.py`](../../tests/test_pins_record.py) | 저장소의 레코드 검사(`limn.pins.record.valid_rec`)를 문서 키 규칙과 행위자 모양을 대역으로 넘겨 직접: 줄 핀·영역 핀의 위치(절대 경로, 정수 범위, 쪽과 네 수), 선택 필드마다 저장된 모양이 아닐 때 깨진 줄로 보는지, 모르는 필드는 지나가는지, 스레드 항목과 `ev` 표시, 넘겨받은 두 규칙에 `doc`·`author`·`*_by`를 묻는지 |
| [`tests/test_contract_snapshot.py`](../../tests/test_contract_snapshot.py) | 에이전트 계약의 스냅숏: 정해진 핀 흐름(사람·에이전트의 새 핀, 질문, claim, 답글, `reply`·`ref`·`changes`를 단 닫기, 확인, 다시 열기, 편집, 휴지통과 되살리기, 에이전트가 만나는 거절)을 처리기로 몰아 응답마다의 상태·본문, 쓰기마다의 `pins.md`, 끝의 `GET /pins.md`·`GET /api/pins`·`GET /api/pins/N`·`GET /api/pins/dropped`를 [`tests/data/contract_snapshot.json`](../../tests/data/contract_snapshot.json)과 바이트 단위로 비교한다. 시계·시간대·경로를 고정한다. 스냅숏은 6단계를 마치기 전 `main`의 서버로 기록했다. 계약을 일부러 바꿀 때만(설계 승인 뒤) `LIMN_RECORD_SNAPSHOT=1`로 다시 기록하고, JSON의 차이가 곧 계약의 변경이다 |
| [`tests/test_pins_view.py`](../../tests/test_pins_view.py) | `limn.pins.view`를 협력자를 인자로 넘겨 직접: 레코드를 API에 보이는 모양(`public_record`: `rev` 기본값, 저장된 `file_rel`·`rel_path`를 빼고 찾은 위치로 `file`·`rel_path`), `pin_state`가 모든 레코드 모양에서 `parse_pin`이 고르는 상태 타입의 이름인지, `GET /api/pins` 레코드의 계산 필드 순서와 저장된 같은 이름 필드를 제자리에서 덮는지, 옛 claim의 `claim_ts`를 언제 붙이는지, 열린 핀만(또는 전부) 싣고 문서의 빌드 이력을 문서마다 한 번, 목록에 핀이 있는 문서만 묻는지, 휴지통의 순서와 `expires_ts`. 끝의 `DroppedList`는 `server.py`를 거친 휴지통 목록(`dropped_at`·`dropped_by`, 되살린 핀 제외)과 `GET /api/pins/dropped`의 본문·출처 검사 |
| [`tests/test_pins_position.py`](../../tests/test_pins_position.py) | `limn.pins.position`의 순수 규칙을 값으로 직접: 순수한지(import 검사), 위치 추정(줄이 움직였거나 잃은 핀, 빌드 신원과 지문, 옛 `frac_build`, 빌드가 없는 핀의 찍은 시각 규칙, 이력에 없는 지금 빌드), 겹침(핀 쌍의 관계와 같은 범위는 id가 작은 쪽이 바깥, 호출자가 찾은 파일로 묶기, 저장 전 선택의 `equal`), anchor 재동기화(위로 줄이 늘면 따라감, 머리 줄을 잃으면 `lost`, 파일이 새롭지 않으면 그대로, rev 올림과 필드 순서, 옛 핀의 anchor 채우기는 자기 파일에서만, 옮긴 레코드는 anchor가 어긋날 때만 다시 맞추고 `file`을 고침) |
| [`tests/test_locate.py`](../../tests/test_locate.py) | `limn.locate`가 서버 전역(`C`, 문서 목록, 핀 목록)을 읽지 않고 서버·HTTP 층을 가져오지 않는지, `sync_all`이 넘겨받은 찾기 함수로 파일을 읽어 바뀐 핀만 새 레코드로 바꾸는지(닫힌 핀·보기 전용 핀·못 찾은 핀은 그대로), 토큰 가중치 캐시가 흔한 단어를 빼고 파일 판마다 다시 세는지, 겹침이 찾기 함수가 지금 찾은 파일로 세는지(옮기기 전후의 핀이 한 파일, 닫힌 핀 제외)와 `overlaps_api` 본문. 끝의 `Anchor`·`Estimate`는 `server.py`를 거쳐 원고를 고친 뒤의 anchor 재동기화(앞뒤 주석 줄 유지, 옛 anchor)와 `GET /api/pins`의 `est` 판단(빌드 신원과 원고 지문, 줄이 움직였거나 잃은 핀, 옛 핀의 시각 규칙, 빌드 이력과 `build_seq`, 재시작 뒤 `seed_builds`, 가벼운 meta는 이력 파일을 쓰지 않음)을 본다. 선택 해석·겹침의 HTTP 동작은 `test_server.py`(`Overlaps`)·`test_v032.py`·`test_moved_paths.py`가 지킨다 |
| [`tests/test_viewer_assemble.py`](../../tests/test_viewer_assemble.py) | 뷰어 조립(`limn/viewer/assemble.py`): 작은 뷰어 폴더로 `viewer_html()`이 조각을 순서대로 잇고 빌드 때의 자리 표시자(PDF.js 버전·마크·아이콘 표·메시지 표·`{{ic:…}}`)를 인자로만 채우는지, JSON이 키 순서로 정렬되고 메시지의 `</`가 이스케이프되는지, 표에 없는 아이콘과 틀린 폴더가 예외인지, 실제 폴더에서는 실행 때의 자리 표시자 넷만 남는지. 메시지 표 읽기가 잘못된 항목을 버리고 없는 파일을 빈 표로 읽는지. 모듈이 표준 라이브러리만 가져오고 `C`·`cur_doc`·서버를 모르는지. 서비스 워커 읽기(`service_worker`)가 폴더의 `sw.js`를 그대로 돌려주고 없으면 예외인지 |
| [`tests/test_viewer_files.py`](../../tests/test_viewer_files.py) | 뷰어 조각과 순서 목록(`parts.txt`): 목록의 조각이 패키지에 있고 `css/`·`js/`의 파일이 목록에 한 번씩 있는지, 조각이 줄 단위로 끝나는지, `index.html`의 CSS·JS 표식이 한 번씩이고 조각에는 없는지, 서버가 조립한 HTML이 조각을 목록 순서대로 이은 것과 같은지. 표식이나 목록이 틀리면 시작 단계에서 실패하는지. 내보내는 페이지의 인라인 스크립트마다 `node --check`가 통과하는지와, 조각 하나에 심은 문법 오류를 그 조각 파일·줄로 잡는지, `GET /sw.js`가 내주는 서비스 워커(`viewer/sw.js`)가 파일 그대로이고 `node --check`를 통과하는지(node가 없으면 건너뜀, `LIMN_TEST_REQUIRE_NODE=1`이면 실패) |
| [`tests/test_build.py`](../../tests/test_build.py) | `limn.build`가 서버 전역(`C`, `cur_doc()`, 문서 목록, 옛 전역 잠금·상태)을 읽지 않고 서버를 가져오지 않는지, `latex_errors`, 두 문서가 인자만으로 동시에 빌드되고(가짜 latexmk가 서로를 기다림) 결과·이력·빌드 폴더가 섞이지 않는지. TeX 없이 가짜 `latexmk`·`pdftoppm`을 PATH에 둔다. 끝의 `AsyncBuild`·`Legacy`는 `server.py`의 추적 빌드(`_build`를 바꿔 끼운 `build_all`·`build_async`: 바쁘면 `busy`와 409, `copy` 단계, `ok_errors`, 실패는 `built_src_mtime`을 남기지 않음, 작업 스레드 예외는 `fail`, 실제 빌드의 단계 순서와 `.aux`)와 단일 문서의 옛 쪽 폴더 이전을 본다 |
| [`tests/test_store.py`](../../tests/test_store.py) | `limn.store`를 서버 없이 직접 몬다: 서버·HTTP를 가져오지 않는지(import 검사), `pins.jsonl` 뒤에 `pins.md`를 쓰고 렌더가 실패하면 아무것도 쓰지 않는지, 바꾼 것 없는 읽기는 줄 맞춤이 바꿨을 때만 쓰는지, 거절은 줄 맞춤을 쓰고 결함은 아무것도 쓰지 않는지, 손상 줄을 건너뛰고 원본을 `.corrupt-*.bak`로 보존하는지(휴지통 포함), 잠금을 쥔 채 겹쳐 쓸 수 있고 다른 스레드는 기다리는지, 30건 동시 저장이 모두 남는지, 핀 번호·`init_seq`·clear 보관. 끝의 `Store`는 같은 불변식을 `server.py`를 거쳐 본다(30건 동시 추가, 형식이 틀린 줄의 격리, 원고 밖 파일을 읽지 않음, 렌더 실패는 커밋하지 않음, 같은 초의 clear 두 번, 되살리기의 쓰기 실패)와 추가·편집이 `pdf_build`를 찍는 규칙 |
| [`tests/test_service.py`](../../tests/test_service.py) | `limn.service`(핀 서비스 셸)를 서버 없이, 임시 폴더의 실제 `PinStore`와 기록하는 알림·감사 싱크로 직접: 서버·HTTP·시계를 가져오지 않고 `C`·`PIN_LOCK`·`now_str`을 읽지 않는지(import 검사), 추가가 쓴 뒤에 알림을 한 번에 내는지, 거절(낡은 `base_rev`, 이미 닫힘, 스레드 가득 참, 다른 사람의 claim, claim 없음, 휴지통에 없음, 이미 살아 있음)은 파일을 그대로 두고 알림이 없는지, 에이전트의 확인은 저장소를 읽지 않는지, 사람의 답글이 닫힌 핀을 다시 여는지, 휴지통 만료·드롭·되살리기·정리, 영구 삭제와 clear의 감사 줄이 핀 잠금 밖에서 쓰이는지. 끝의 `Claim`·`CloseReplyRef`·`CloseIdempotent`는 `server.py`의 핀 문맥으로 claim(충돌·연장·만료·해제, 닫기·드롭이 claim을 지움, `pins.md` 모래시계, HTTP)과 이유를 단 닫기, 다시 닫기가 아무것도 바꾸지 않음을 본다. 알림·감사가 적는 행위자(`who`: login과 name만, 기본값은 로컬 에이전트)도 여기서 본다 |
| [`tests/test_people.py`](../../tests/test_people.py) | `limn.people`을 서버 없이: 서버·시계를 가져오지 않는지(import 검사), `people.json` 항목 검사와 저장 형식, 없는·깨진 파일, @태그 후보(people.json 먼저, 핀의 작성자·`*_by`·스레드 글쓴이, 에이전트 제외), 기록이 역할을 기본값일 때 적지 않는지·10분 안에는 다시 쓰지 않는지·`limn member` 가 정한 역할을 지키는지·실패는 `False` 이고 메모하지 않는지 |
| [`tests/test_mentions.py`](../../tests/test_mentions.py) | `limn.mentions`가 순수한지(import 검사), `@이름` 풀기(이름 전체·로그인·로그인 앞부분, 겹치는 첫 이름과 힌트, 메일 주소·붙은 영문·밑줄, 한글 조사, 자기 태그 제외, 반복 세기), 지금 차례와 `addressed`·`fyi`, 메모 태그가 새로 부른 사람과 재알림 간격 |
| [`tests/test_events.py`](../../tests/test_events.py) | `limn.events`를 서버 없이: import 검사, 이벤트 한 건의 받는 사람(행위자·`local`·빈 값·중복 제외, 아무도 없으면 조회 없이 `None`)·`msg`·`excerpt`(`pins.md`와 같은 한 줄 규칙 `limn.pins.render.flat`, 140자), 폴링이 고르는 이벤트(종류·받는 사람·행위자·커서·20건·`doc_name`), `events.jsonl`의 `seq` 이어 붙이기·보관 건수·읽기 캐시·못 읽는 줄·쓰기 실패는 경고 |
| [`tests/test_audit.py`](../../tests/test_audit.py) | `limn.audit`이 서버 없이 서는지: import 검사, 상태 폴더만으로 줄을 차례로 덧붙이는지, CLI 행위자. 서버·CLI를 거친 감사 기록은 `test_v031.py`가 지킨다 |
| [`tests/test_pull.py`](../../tests/test_pull.py) | `--git-pull`·원격 main 감시의 순수 규칙(`limn.pull`)이 아무것도 실행하지 않는지(import 검사), 결과 값마다 빌드의 `pull` 기록(`state`·`reason`·`head_before`·`head_after`, 옛 키 순서), git 답 읽기(저장소 루트, HEAD, fetch 실패의 시간 초과·오류 구분, main 추적, 더러운 트리, fast-forward 뒤 HEAD), 감시 상태(`updated`·`current`·`blocked`·`error`, 미룸과 예기치 않은 오류는 이전 커밋을 남긴 채 덧씀), 다시 빌드할 문서, `updating`이 끝나는 조건 |
| [`tests/test_gitsync.py`](../../tests/test_gitsync.py) | `limn.gitsync`를 서버 없이: 서버·HTTP를 가져오지 않고 서버 전역을 읽지 않는지, 임시 bare 저장소와 클론에서 pull의 모든 결과(`not_git`·`ok`·`up_to_date`·`not_main`·`dirty`·`diverged`·`no_upstream`·하위 폴더·원격이 사라진 `fetch_failed`), 흉내 낸 git으로 시간 초과와 `status_failed`, git이 없어도 던지지 않는지, 여러 문서의 pull 나눠 쓰기(창 안에서 `shared`), 감시 한 바퀴(미룸과 잠금 풀기, 뒤처진 LaTeX 문서만 빌드, 보기 전용 PDF 제외), 상태가 `current`·`build_failed`로 끝나는지, 감시 루프가 예외를 기록하고 살아남는지. 끝의 `GitPullBuildIntegration`·`AutomaticMainSync`는 `server.py`의 배선: 빌드 응답·상태의 `pull`, pull이 밀어 올린 mtime이 '원고 바뀜'을 잘못 켜지 않음, 감시 한 바퀴가 LaTeX 문서마다 빌드를 한 번 거는지, `GET /api/meta`의 `sync` |
| [`tests/test_scope.py`](../../tests/test_scope.py) | `limn.scope`가 순수한지(import 검사), `limn.scope`·`limn.revisions`·`limn.documents`가 `C`·`cur_doc()`을 읽지 않고 `limn.revisions`가 서버·HTTP 층 없이 올라오는지, 핀 단위 변경의 거절이 경우마다 한 값인지. 귀속 규칙과 경로별 본문은 `test_v03.py`·`test_revisions.py`가 지킨다 |
| [`tests/test_meta.py`](../../tests/test_meta.py) | `limn.meta`·`limn.documents`·`limn.outline`이 서버 전역(`C`, 문서 목록)을 읽지 않고 서버·HTTP 층을 가져오지 않는지, 인자만으로: 목차 라벨이 화면 빌드의 `.aux`만 읽는지(빌드 사본·심볼릭 링크·4 MiB 초과·보기 전용 문서는 빈 목록), 라이트 meta 본문의 키 순서와 값, 여러 문서의 `docs`·`src_sig`, 핀 개수, `pins_rev`, `/api/docs`의 문서별 열린 핀과 `other_open`, 요청·파일·핀 기록이 가리키는 문서, `DocumentFacts`, `to_source`. 끝의 `LightMeta`·`InstanceMeta`는 `server.py`를 거친 가벼운 폴링(쓰기 없음, `pins_rev`, `src_mtime` 캐시와 빼는 폴더, `?light=1`)과 인스턴스 라벨·색·저장소 |
| [`tests/test_outline.py`](../../tests/test_outline.py) | `.aux` 목차 파서(`limn.outline`)가 순수한지(import 검사), 중괄호 묶음, 제목 표시 변환과 그 거절, 목차 줄 → 행(번호 있는·없는 항목, `\protect\numberline`, 다른 목록·계층·깨진 줄 건너뜀, 못 바꾼 제목의 자리표시 줄, anchor 200자·행 200개 한도) |
| [`tests/test_web_parse.py`](../../tests/test_web_parse.py) | 요청 파서(`limn.web.parse`)를 서버 없이 직접: 필드마다 값이나 첫 거절(400 문장·`reason` 그대로), 서버가 늘 보던 순서(새 핀은 위치가 메모보다 먼저, 선택은 빌드 이름 → 지워진 빌드 → 쪽 → x0·x1·y0·y1), 원고 트리 경로 규칙(`limn.files.file_in_tree`), 보기 전용 문서의 영역 핀과 편집 위치. 원고 사실은 가짜 `DocumentFacts`로 준다. 끝의 `EditAddParsing`은 서버의 `document_facts`로 같은 파서를 부르고 처리기가 답하는 상태 코드를 본다 |
| [`tests/test_web.py`](../../tests/test_web.py) | HTTP 층(`limn.web`): `server.py`가 `App`에 적힌 이름을 모두 갖는지, 처리기가 서버 모듈에서 다시 묶은 이름(테스트의 `patch.object`, `main()`의 `HTML`)을 요청 때 읽는지, `limn.web`이 `server.py`를 가져오지 않는지, `server.py`가 파일로 실행되는지(표준 모듈 `http`를 가리지 않음), 결과별 응답(`answers`)과 거부된 첫 화면의 언어·이스케이프를 직접. 경로마다의 상태 코드·본문은 처리기를 거치는 다른 파일이 지킨다 |
| [`tests/test_build_copy.py`](../../tests/test_build_copy.py) | 빌드 첫 단계인 원고 복사가 실패하면(`rsync` 비정상 종료) 사본을 컴파일하지 않고 빌드를 실패로 끝내는지 |
| [`tests/test_v03.py`](../../tests/test_v03.py) | 0.3(이슈 #9, [ADR-0005](../adr/0005-pin-scoped-changes.md)): hunk 블록 파싱과 귀속(겹침, 줄 밀림을 거친 대응, 한 커밋의 핀 셋, 이름 바꾸기, 지운 범위, 기록한 `changes` 가 추정을 이기는 순서), 핀 hunk의 실제 줄 번호와 맥락, 합성 적용(실제 git으로 만든 무작위 편집 왕복·`git apply` 대조), `changes` 검사·저장·다시 열기, `pins.md` 닫기 줄, 핀 단위 소스 diff·비교 PDF HTTP와 캐시 키, 실제 격리 빌드(TeX가 있을 때만, CI는 건너뜀), 뷰어(데스크톱 1400×850·폴드 842×758·폰 384×832 × 한국어·영어: 다른 변경 접기·펴기, [커밋 전체 비교] 토글, 컴파일 실패 시 커밋 전체로 넘어감), 순수 판단의 직접 테스트(`ScopeDecisions`: `changes_at` 규칙, 합성 판에 쓸 파일, 거부 이유 표), 새 거부마다의 상태 코드·본문(`ScopedErrorBodies`), 스쿼시 커밋 하나가 핀 셋을 고치고 머지 뒤 `changes`·`PR #N (해시)`로 닫는 흐름, 다시 여는 답글의 이벤트가 0.2.2와 같은지(v0.2.2 모듈과 대조, 얕은 클론이면 건너뜀), viewer 휴지통에 [되살리기]·[영구 삭제]가 없는지(브라우저) |
| [`tests/test_v031.py`](../../tests/test_v031.py) | 0.3.1(이슈 #10): 메모 mention 재알림 간격의 순수 판단(`note_mention_targets`: 키 세 부분, 10분 경계, 답글 mention 제외, 시각 없는·먼 기록)과 핀 조작을 거친 흐름(가짜 시계로 태그 껐다 켜기 세 번 = 알림 하나, 10분 뒤 다시, `note_append`, 답글·다시 연 이유는 매번), `audit.jsonl`(`EVENTS_KEEP`+1건 회전 뒤에도 `cleared` 가 남음, 영구 삭제, 거부된 요청은 적지 않음, 권한 0600, 덧붙이기만, 쓰기 실패는 경고, 스레드 동시 쓰기, `limn token`·`limn member` 가 OS 계정으로 적고 토큰 원문·해시는 적지 않음) |
| [`tests/test_token_file.py`](../../tests/test_token_file.py) | 0.3.3([ADR-0007](../adr/0007-agent-token-file.md)): `limn token create --save`(파일 `0600`·폴더 `0700`, 토큰을 찍지 않음, `--print`·`--force`, 기존 파일·git 작업 트리·인스턴스 없음 거부는 토큰을 만들기 전에, 쓰기 실패면 새 토큰을 폐기), `limn token path`, `token list` 가 파일의 토큰을 밝힘, `token revoke` 가 그 토큰의 파일만 지움. 서버: 파일이 생기면 `pins.md` 인증 안내 줄에 구절 하나(토큰은 없음, 원격 `GET /pins.md` 에는 없음, 파일을 읽지 않음), loopback 에이전트를 끈 인스턴스의 헤더 없는 로컬 요청 `401` 메시지, 프록시를 거친 요청은 옛 문구, 폐기된 토큰 `401`, `LIMN_AGENT_TOKEN_FILE`. 인스턴스 관리자와 실제 서버(보기 전용 PDF, TeX 없이): loopback 에이전트 켬·끔에서 `limn status`·`start` 가 토큰 파일을 curl 표준 입력으로 보냄(명령줄에 없음), `401` 안내, 심링크·남의 권한·형식이 틀린 파일 거부 |
| [`tests/test_v032.py`](../../tests/test_v032.py) | 0.3.2(이슈 #7, [ADR-0006](../adr/0006-relative-pin-paths.md)): 핀 파일 위치의 순수 판단(`pin_rel_path`: 원고 안의 `file` 우선, 꼬리가 맞는 `file_rel`, 넓힌 원고 폴더의 더 긴 꼬리, 가장 긴 꼬리, `..`·절대·빈 값 거부), 두 서버 실행 사이에 원고 폴더를 옮긴 흐름(응답의 지금 `file`·`rel_path`, `pins.md` 하위 폴더와 인용, anchor 줄 맞춤, `lo`/`hi` 수정, 겹침, 휴지통·되살리기, 그대로 옮긴 뒤 읽기는 다시 쓰지 않음, mtime 이 오래된 다른 내용의 사본도 다시 맞춤, 옛 체크아웃으로 돌아가면 그 줄로 돌아감, 옮긴 파일에서 anchor 를 채우지 않음, 넘친 `note_append` 의 `400` 은 아무것도 바꾸지 않음), 클론한 저장소에서 핀 단위 [변경 보기], 원고 밖으로 남아야 하는 경우(꼬리가 맞지 않음, `..`·절대 `file_rel`, 바깥을 가리키는 심볼릭 링크 — 바깥 줄이 새지 않는지), v0.3.0·v0.3.1 모듈이 이 상태를 읽고 그 버전의 위치 다시 잡기가 낡은 `file_rel` 을 이기는지(얕은 클론이면 건너뜀) |
| [`tests/test_viewer_input.py`](../../tests/test_viewer_input.py) | 뷰어의 마우스·터치 입력(입력 점검 2026-09-26): 순수 판단(`snapSide` 접는 문턱, `gripKey` 창 분할 키, 밀기 방향·고무줄·닫힘 판정, 시트 놓기, 두 번 탭, 뒤로 가기 층)과 브라우저 흐름을 데스크톱 1400×850·1280×720(마우스)·폴드 842×758·폰 384×832(CDP 터치) × 한국어·영어 × 밝게·어둡게 × 줄인 움직임으로(끌어 접기·레일·`[핀 N]`·Ctrl+\·키보드, 접힌 넓은 패널의 칩·알림, 기억, 밀어 닫기, 시트 끌기, 뒤로 가기, 유령 클릭, 가로 밀기, 선택 되돌리기, 탭에 남는 초안(새로고침·떠났다 돌아오기·[버리기]·저장·빌드가 바뀐 경우), 누르는 넓이 24px) |
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
| 적용 조건 | `pyproject.toml`, 패키지 데이터(`vendor/`, `systemd/`, `instances.sh`, `ui_en.json`, `viewer/`)를 바꿀 때. CI `install` 작업이 항상 돈다 |
| 실행 | `uv tool install .` 뒤 `limn version`, `limn serve --help`, `limn serve --version`, `limn help` |
| 합격 기준 | 명령이 모두 성공하고 PDF.js 번들, `limn@.service` 템플릿, `instances.sh`, 뷰어 `viewer/index.html`·`viewer/parts.txt`와 조각 `viewer/css/tokens.css`·`viewer/js/events.js`가 설치 경로에 있다. 파일 하나라도 없으면 그 자리에서 실패한다 (예전 `find … && echo` 줄은 마지막 줄이 아니면 없어도 통과했다) |
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
| docstring | 정량 게이트 없음. Ruff의 `D` 규칙은 켜지 않았다 (§8) | [code-style-roadmap.md](code-style-roadmap.md) R4·R7: 새 모듈부터 켜고, 옮겨지는 모듈마다 넓힌다 |
| 테스트 파일의 타입 | `tests/`는 타입 검사 목록에 없다. 패키지(`src/limn/`)는 전부 §9가 검사한다 | 테스트가 타입으로 잡을 결함을 놓치는 일이 생기면 목록에 더하는 것을 검토 |
| 실제 LaTeX 빌드 | CI에 TeX가 없어 로컬에서만 돈다 | 필요해지면 TeX 설치 작업을 CI에 더하는 것을 검토 |
| Handbook 링크·형식 | §7 출판기 `check`가 검사하지만 CI에서는 돌리지 않는다 | 폰트를 CI에 준비할 방법을 정한 뒤 CI에 추가 검토 |
| 에이전트 계약 전체 비교 | 고정된 핀 흐름 하나는 `tests/test_contract_snapshot.py`가 응답과 `pins.md`를 기록된 스냅숏과 바이트 단위로 비교한다(2026-09-26). 그 흐름 밖의 경로·필드는 정량 게이트가 없다 (§4는 사람 확인) | 계약을 더하는 PR이 스냅숏 흐름에도 그 경로를 더한다 |

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
| 보장 범위 | 켠 규칙만이다. 규칙 목록과 끈 규칙은 `pyproject.toml`의 `[tool.ruff.lint]`가 정본이다. 꺼 둔 것: 줄 길이 `E501`(코드 줄은 포매터가 접고, 긴 주석·docstring 줄은 검사하지 않는다), 문자열 포매팅을 바꾸는 `UP030`·`UP031`·`UP032`(메시지는 에이전트 계약 바이트다), `UP042`. docstring(`D`)은 아직 검사하지 않는다 (§6). 타입은 §9가 본다. `src/limn/vendor/`와 플러그인에서 복사한 `tools/handbook-publish/`는 검사와 포매팅에서 뺀다. 뷰어 JS에는 린터가 없고, §1의 `test_viewer_files`가 node로 문법만 본다 |

## 9. 타입 검사

| 항목 | 내용 |
| --- | --- |
| 측정 대상 | `src/limn/` 아래의 모든 파이썬 파일(`[tool.mypy]`의 `files = ["src/limn"]` — 새 모듈은 만들면 바로 검사된다)의 타입 오류. strict 모드라 표기 누락, 타입 인자 없는 `list`·`dict`, `Any` 반환, `None` 가능성을 좁히지 않은 사용도 오류다. 합 타입에 대한 `match`가 경우 하나를 빠뜨리면 `exhaustive-match`로 실패한다 |
| 적용 조건 | 모든 변경. CI `lint` 작업이 항상 돈다. `src/limn/` 아래에 새 파일을 만들면 따로 등록하지 않아도 검사된다 |
| 실행 | `uv sync --group dev` 뒤 `uv run mypy`. 검사할 파일과 설정(`strict`, `python_version = "3.10"`, `exhaustive-match`)은 `pyproject.toml`의 `[tool.mypy]`가 정본이다. mypy는 개발 의존성이라 로컬과 CI가 `uv.lock`의 같은 버전을 쓴다 |
| 합격 기준 | 명령이 0으로 끝난다. `# type: ignore`는 쓰지 않는 것이 기본이고, 꼭 필요하면 오류 코드를 적고(`# type: ignore[arg-type]`) 그 줄에 이유를 단다. `cast`도 같다 |
| 보장 범위 | 목록에 든 파일의 정적 타입이다. 2026-09-26부터 패키지의 모든 파이썬 파일이 목록에 들어, 조립 지점 `server.py`가 옮긴 모듈에 넘기는 값과 협력자(`PinContext`의 `make_event`·`note_tags` 등, `RevisionContext`, 저장소의 레코드 검사)의 서명도 검사한다. HTTP 처리기는 `_ModuleApp`(모든 속성이 `Any`)으로 `server.py`에 닿지만, `server.py` 끝의 `if TYPE_CHECKING:` 대입이 모듈 자체를 `web/app.py`의 `App`과 맞춰 보므로 빠진 연결과 서명이 틀린 연결도 mypy 오류다. `tests/test_web.py`는 실행 때 이름이 모두 있는지를 따로 확인한다. 보지 못하는 것: 저장된 JSON 레코드와 응답은 `Mapping[str, Any]`·`dict[str, Any]`라 필드 값의 타입을 보지 않는다(모양은 계약 스냅숏·레코드 왕복 테스트가 지킨다). 테스트 파일은 목록에 없다 |

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
