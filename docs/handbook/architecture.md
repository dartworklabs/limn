# 구조와 불변식

이 topic은 Limn이 지금 어떤 구조로 짜여 있는지, 어느 방향으로 옮겨 가기로 했는지, 그리고 구조가 바뀌어도 반드시 지켜야 하는 규칙이 무엇인지를 설명한다. 코드를 새로 놓을 자리를 고르거나, 모듈을 나누거나, 의존성·저장 파일·보안 경계를 건드리기 전에 읽는다. 구조 단위나 불변식이 바뀌면 같은 변경에서 이 파일을 고친다.

> **한눈에**
>
> - 요청 하나가 서버를 지나가는 흐름: §한 요청이 지나가는 길
> - 지금 코드가 놓인 모양과 그 근거: §현재 구조
> - 채택한 설계 축 값과 목표 구조: §채택한 설계 축, §목표 구조
> - 어기면 안 되는 규칙: §불변식
> - 멈추고 설계 판단을 받아야 하는 변경: §멈춤 신호

## 한 요청이 지나가는 길

Limn은 원고 PDF에서 드래그한 영역을 `.tex` 파일과 줄 범위로 되돌려 주는 서버다. 사용자는 브라우저 뷰어에서 영역을 고르고 메모를 붙여 **핀**으로 저장한다. 에이전트는 `pins.md`나 HTTP API로 핀을 읽고 원고를 고친다.

```text
브라우저 (영역 드래그)
   │  좌표
   ▼
limn serve  ──(1)──▶  <manuscript_dir> 사본을 별도 빌드 디렉터리에서
  127.0.0.1:<port>      latexmk -synctex=1 로 빌드 (원본 체크아웃은 건드리지 않는다)
   │
   ├─(2) 역변환 두 경로를 경쟁시킨 뒤 범위 사다리(드래그 줄·문단·환경)를 계산 → 스니펫
   ├─(3) 사용자가 메모를 붙여 핀으로 저장 → <state_dir>/pins.jsonl (잠금 + 원자적 교체)
   └─(4) <state_dir>/pins.md 재생성 — 에이전트가 읽는 단 하나의 파일
```

빌드를 원본 체크아웃이 아니라 rsync 사본에서 하는 이유는 동시에 편집 중인 원고를 빌드가 중간 상태로 붙잡지 않게 하려는 것이다. 빌드 사본 경로를 원본 경로로 되돌리는 일(`build_dir → manuscript_dir`)은 서버가 안에서 처리한다. 그래서 에이전트는 언제나 원본 경로만 받는다.

상태 디렉터리를 옮기거나 복제해서 SyncTeX가 옛 빌드 경로를 가리키는 경우도 있다. 이때는 경로 꼬리가 원고 트리 안의 파일과 맞을 때만 경로를 고쳐 쓴다. 원고 체크아웃을 옮겨 핀에 저장된 절대 경로가 낡은 경우도 같은 규칙에 원고 폴더 기준 상대 경로 `file_rel` 을 더해 읽을 때 찾는다([api.md](api.md) §핀 파일의 위치, [ADR-0006](../adr/0006-relative-pin-paths.md)). 원고 트리 밖의 파일은 절대 읽지 않는다. 역변환·범위 사다리·줄 맞춤의 규칙은 [domain.md](domain.md)에 있다.

## 현재 구조

지금 Limn은 **하나의 배포 단위(`dartwork-limn` 패키지) 안에서 표준 라이브러리만 쓰는 책임별 모듈**로 나뉘어 있고, `server.py`는 그 모듈들을 한 인스턴스에 묶는 조립 지점이다(2026-09-26 [code-style-roadmap.md](code-style-roadmap.md) 6단계 완료). 한때 1만 행을 넘던 `server.py`가 대부분의 일을 하던 모양에서 단계마다 옮겨 왔다. 아래 줄 수는 2026-09-26에 잰 값이다.

| 파일 | 줄 수 | 맡은 일 |
| --- | --- | --- |
| [`src/limn/server.py`](../../src/limn/server.py) | 1,151 | 조립 지점(2026-09-26 6단계 완료): 실행 설정 `C = Cfg()`(타입은 `limn/config.py`), 문서 목록(`DOCS`)과 그 목록·설정을 문서 조회와 meta 읽기에 넘기는 연결(`request_doc`·`meta`·`docs_payload`), 빌드 연결(`build_all`·`build_async`: `BuildConfig`·`--git-pull`·보기 전용 그리기를 묶는다), `--git-pull`·원격 main 감시를 이 인스턴스에 묶는 연결(`repo_pull`·`sync_status`·`sync_main_once`: 프로세스에 하나인 pull 나눠 쓰기 `PULL_SHARE`와 감시 상태 `SYNC_WATCH`의 주인이고, 감시 스레드는 `prepare()`가 시작한다), 원고 이력·비교 PDF 서비스를 이 인스턴스에 묶는 연결(`revision_context`), 핀 위치 서비스를 이 인스턴스에 묶는 연결(`pin_location`·`sync_all`·`overlaps_by_id`·`pick_context`: 문서 목록·원고 루트·`--float-envs`·토큰 가중치 캐시·저장소의 핀을 `limn/locate.py`에 넘긴다), `GET /api/pins`·`GET /api/pins/dropped`의 계산 필드를 이 인스턴스에 묶는 연결(`pins_payload`·`dropped_payload`: 레코드를 보이는 `public`, 핀의 문서, 문서마다의 빌드 이력, 겹침, 시계를 `limn/pins/view.py`에 넘긴다), 핀 저장소 조립(`pin_store`, `PIN_LOCK`, 레코드 검사 `valid_rec`: 규칙은 `limn/pins/record.py`의 것이고, 여기서는 그 규칙에 문서 키 규칙 `DOC_KEY_RE`와 행위자 모양 `limn.people.is_actor`를 묶기만 한다), 핀 서비스 연결(`pin_context`: 저장소·시계·알림과 감사 기록·@태그 조회·파일 위치·`THREAD_MAX`·`TRASH_DAYS`와 휴지통 점검 시각을 `limn/service/`에 넘기고, 처리기가 부르는 옛 이름 `add_pin`·`set_done`·`drop_pin` 등은 한 줄 연결로 남는다), `pins.md` 렌더가 읽는 값의 조립(`pins_md_input`: 실행 설정·문서와 빌드 도장·시계·토큰 파일·`people.json`·핀마다의 파일 위치와 긴 줄 길이·겹침 배지·@태그·스레드 회차), 사람·이벤트 연결(`people_book`·`event_log`: 프로세스의 잠금·캐시·시계를 `people.py`·`events.py`에 묶는다), 접근 제어를 이 인스턴스에 묶는 연결(`access_settings`·`access_lookups`: 실행 설정과 `tokens.json`·`people.json` 캐시를 `limn/access.py`에 넘긴다. 두 캐시와 한 번만 내는 경고의 주인이다. CLI에 넘기는 감사 기록 `cli_audit`), 뷰어 페이지(`HTML`: 메시지 표 `UI_EN`과 함께 `limn/viewer/assemble.py`의 `viewer_html`에 넘긴 결과. 실행 인자의 라벨·색은 `build_html`이 채운다)와 서비스 워커(`SW_JS`: `viewer/sw.js`를 `service_worker`로 읽은 그대로), HTTP 처리기를 이 모듈의 서비스에 묶는 연결(`_ModuleApp`. 이 모듈이 `web/app.py`의 `App`을 만족하는지는 `if TYPE_CHECKING:` 대입으로 mypy가 본다), 조립 지점(`main()` → `start()`: 접근 설정·`--port` 확인·실행 설정과 문서·저장소와 빌드·요약·서버. 2026-09-26부터 각 단계의 규칙은 `limn/startup.py`에 묻고 이 모듈은 그 답을 `C`에 적용하기만 한다 — `configure_access`는 `AccessOptions`의 필드를 같은 이름으로 `C`에 옮기고, `configure_run`은 거절 순서와 상태 폴더를 만드는 시점을 지킨다. 시작 거절은 `StartupRefused` 값이고 `sys.exit`은 `main()`에만 있다). 요청 파서는 2026-09-26부터 `web/parse.py`에 있고, 서비스는 파싱된 값을 받는다. 파서가 원고와 맞춰 보는 사실(파일의 줄, 빌드의 쪽)은 `document_facts()`가 문서마다 건넨다. 2026-09-26 조립이 아닌 것을 마저 옮겼다: 레코드 검사 → `limn/pins/record.py`, 빌드 응답의 로그 다이어트 → `web/answers.py`, `pins.md`의 다시 열림 판단 → `limn/pins/lifecycle.py`, 서비스 워커 → `viewer/sw.js`, 레코드를 API에 보이는 모양 → `limn/pins/view.py`의 `public_record`, 알림·감사가 적는 행위자 `who` → `limn/service/context.py`, 패키지 버전 → `limn/startup.py`, 처리기만 쓰는 상수 → `web/handler.py`. 남은 것은 실행 설정 `C`와 `DOCS`, 프로세스에 하나인 자원(잠금·캐시·작업 목록·감시 상태), 옮긴 모듈에 이 인스턴스를 묶는 한 줄 연결, 시작 단계다 |
| [`src/limn/web/`](../../src/limn/web/handler.py) | 1,886 | HTTP 층(2026-09-26 옮김): 처리기와 서버 클래스·본문 읽기와 한도·GET/POST 경로 분기와 경로만 쓰는 상수(`CLEAR_CONFIRM`·`PAGE_FILE_RE`·`VENDOR_MIME`)(`handler.py`), 요청 본문·쿼리의 파서(`parse.py`: 값이나 `InputRejected`를 돌려주고 처리기가 400으로 답한다), 핀 조작과 원고 이력 결과마다의 응답과 빌드 응답의 로그 다이어트(`diet_log`)(`answers.py`), `HTTPError`·`InputRejected`·핀 단위 변경 거절 표·비교 PDF 실패 문구 표·거부된 첫 화면(`errors.py`), 처리기가 부르는 서비스 목록(`app.py`의 `App` 프로토콜). `server.py`를 가져오지 않는다 (`tests/test_web.py`가 검사) |
| [`src/limn/build.py`](../../src/limn/build.py) | 942 | 빌드: 원고 복사, latexmk, pdftoppm, 쪽 디렉토리 교체와 쪽 목록(`page_list`), 빌드 상태, 빌드 이력, 원고 지문과 `src_mtime`, 보기 전용 PDF 다시 그리기(`render_pdf_doc`·`pdf_changed`, 2026-09-26 옮김)와 PDF가 바뀌면 부르는 쪽이 준 시작 함수로 다시 그리기를 거는 `refresh_pdf_doc`(같은 날 옮김). 문서(`BuildDoc`)와 설정(`BuildConfig`)을 인자로 받고 `C`·`cur_doc()`을 읽지 않는다 (`tests/test_build.py`가 검사). 문서별 잠금·상태는 문서 객체가 갖는다 |
| [`src/limn/revisions.py`](../../src/limn/revisions.py) | 936 | 원고 이력의 git 쪽(2026-09-26 옮김): 최근 커밋, 한 커밋의 소스 diff(핀 단위 포함), 비교 PDF 빌드(스냅숏·격리 실행·캐시·작업 스레드). 문서와 `RevisionContext`(핀 목록, 옮긴 경로 찾기, 프로세스의 범위 캐시와 작업 목록, 실패 문구)를 인자로 받고, 거절과 실패를 값으로 돌려준다. `C`·`cur_doc()`·서버·HTTP 층을 모른다 (`tests/test_scope.py`가 검사) |
| [`src/limn/gitsync.py`](../../src/limn/gitsync.py) | 251 | `--git-pull`과 원격 main 감시의 셸(2026-09-26 옮김): git 호출 순서(`pull`, 기대하는 실패는 결과 값), 빌드의 pull과 여러 문서의 나눠 쓰기(`PullShare`·`repo_pull`), 감시 한 바퀴·상태·루프(`SyncWatch`: 문서 잠금을 모두 쥔 채 당기고, 뒤처진 LaTeX 문서의 빌드를 넘겨받은 함수로 건다). 원고 폴더·문서 목록·`--git-pull`·git 실행기(`limn.revisions.git`)·시계를 인자로 받는다. `C`·서버·HTTP 층을 모른다 (`tests/test_gitsync.py`가 검사) |
| [`src/limn/pull.py`](../../src/limn/pull.py) | 209 | `--git-pull`과 원격 main 감시의 순수 규칙(2026-09-26 옮김): pull 결과 값(`Pulled`·`UpToDate`·거절 `PullRefusal = PullSkipped \| PullFailed`)과 빌드의 `pull` 기록(`pull_record`), git 답 읽기, 감시 상태·다시 빌드할 문서·`updating`이 끝나는 조건. git·파일·시계·스레드를 모른다 (`tests/test_pull.py`가 import를 검사) |
| [`src/limn/scope.py`](../../src/limn/scope.py) | 560 | 핀 단위 변경의 순수 판단(ADR-0005, 2026-09-26 옮김): 블록 파싱, 핀에 블록 귀속, 핀 hunk diff, 합성 판 계획. 거절은 경우마다 한 값(`ScopeRefusal`)이다. 파일·프로세스·시계·HTTP를 모른다 (`tests/test_scope.py`가 import를 검사) |
| [`src/limn/documents.py`](../../src/limn/documents.py) | 288 | 문서(`Doc`, 2026-09-26 옮김): 문서마다 빌드 루트·메인·상태 폴더와 빌드 잠금·상태를 갖고, 실행 경로는 만들 때 받은 `RunPaths`(조립 지점의 `C`)에서 읽는다. 문서 키 규칙과 조회 결과 값(`DocNotFound`)도 여기 있다. 문서 목록을 인자로 받는 조회(키·파일·핀의 문서, 요청의 문서 `request_doc`), 파서가 읽는 원고 사실(`DocumentFacts`), SyncTeX 경로를 원고로 되돌리는 `to_source`도 같은 날 옮겼다. `C`·`cur_doc()`·서버를 모른다 (`tests/test_meta.py`가 검사) |
| [`src/limn/files.py`](../../src/limn/files.py) | 124 | 원자적 파일 교체 `atomic_write`. 핀·사람·토큰·빌드 이력의 모든 쓰기가 공유한다. 상태 파일 하나의 읽고-고치고-쓰기를 프로세스 사이에서 묶는 잠금 `store_lock`(서버와 `limn member`·`limn token`, 감사 기록이 쓴다)도 여기 있다. 요청이나 SyncTeX가 가리키는 경로가 원고 트리 안의 파일인지 보는 규칙 하나(`file_in_tree`, 거절은 이유별 값)도 여기 있다. 원고 파일의 줄을 세는 방식 하나(`tex_lines`)와 번들한 PDF.js 파일 이름 검사(`vendor_file`)도 있다 |
| [`src/limn/meta.py`](../../src/limn/meta.py) | 144 | 뷰어가 폴링하는 읽기(2026-09-26 옮김): `GET /api/meta`의 라이트 본문(`meta`)과 핀 개수(`pin_counts`), `GET /api/docs`(`docs_payload`·`doc_brief`), `pins_rev`, 화면 빌드의 `.aux`에서 읽는 목차 라벨(`outline_labels`). 문서·문서 목록·설정(`MetaSettings`)·`--git-pull` 상태를 인자로 받고 아무것도 쓰지 않는다. `C`·서버를 모른다 (`tests/test_meta.py`가 검사) |
| [`src/limn/outline.py`](../../src/limn/outline.py) | 140 | `.aux` 목차 줄의 순수 파서(2026-09-26 옮김): 중괄호 묶음, 제목의 표시용 변환(TeX 평가기가 아니다, 못 바꾸면 자리표시 줄), 목차 줄 → `{number,title,page,level,anchor}`. 파일·시계를 모른다 (`tests/test_outline.py`가 import를 검사) |
| [`src/limn/access.py`](../../src/limn/access.py) | 730 | 접근 제어(2026-09-26 옮김, [ADR-0002](../adr/0002-access-control.md)): 신원(`identify`: 신원 방식 셋과 API 토큰), 입장(`admit`: `--allow`·`--members-only`), 역할(`check_role`), Host/Origin 판단(`host_ok`·`origin_ok`)과 `pins.md` 기준 주소(`remote_base_for`), 파일이 바뀔 때만 다시 읽는 캐시(`FileCache`), `limn token`·`limn member`의 상태 도우미. 실행 설정은 `AccessSettings`, 요청 때 읽는 파일 사실(토큰 목록·역할)은 `AccessLookups`로 조립 지점이 넘긴다. 감사 기록도 인자(`AuditSink`)로 받는다. `people.json`의 항목 검사와 저장 형식은 `limn/people.py`의 것(`valid_people`·`people_text`)을 직접 가져온다(2026-09-26, 실행 중 서버와 `limn member`가 한 형식을 쓴다. `people.py`는 표준 라이브러리와 `limn/files.py`만 가져온다). `C`·서버·감사 기록 모듈을 모른다 (`tests/test_access_module.py`가 검사). 거절은 값이 아니라 `HTTPError`를 던진다 (§불변식 1) |
| [`src/limn/startup.py`](../../src/limn/startup.py) | 492 | `limn serve` 시작 규칙(2026-09-26 옮김): 접근 설정 판단(`access_options` → `AccessOptions` 또는 거절 — 기본은 loopback 바인드, loopback 밖은 `--auth trusted-proxy`나 `--i-know-this-is-insecure`일 때만, 헤더 없는 loopback 에이전트는 tailscale·loopback 바인드일 때만)과 그 시작 로그(`access_log_lines`), 포트(`free_port`·`probe_port`·`listen_refusal`), `--doc` 해석과 메인 파일·상태 폴더(`parse_doc_arg`·`make_docs`·`detect_main`·`pick_documents`·`state_dir`), `people.json` 권한 조이기, 인스턴스 라벨·색(`run_label`·`run_accent`), 시작 요약 줄(`summary_lines`), `--version`과 `GET /api/version`의 패키지 버전(`app_version`). 거절은 `StartupRefused` 값이다. `C`·서버를 모르고 `sys.exit`을 부르지 않는다 (`tests/test_startup.py`가 검사) |
| [`src/limn/args.py`](../../src/limn/args.py) | 98 | `limn serve` 명령줄 파서(`serve_parser`, 2026-09-26 옮김): 옵션·기본값·도움말. 서버의 한 줄 설명·버전·`--float-envs` 기본값은 조립 지점(`server.build_arg_parser`)이 넘긴다 |
| [`src/limn/config.py`](../../src/limn/config.py) | 110 | 실행 설정의 타입 `Cfg`와 강조색 표 `ACCENT_PALETTE`(2026-09-26 옮김). 인스턴스 하나(`C = Cfg()`)는 `server.py`가 만든다. 명령줄·환경·디스크를 읽지 않는다 |
| [`src/limn/store.py`](../../src/limn/store.py) | 236 | 핀 저장소 `PinStore`: 잠금 아래 쓰기 순서(`transact`), `pins.jsonl`·`pins.md`·휴지통(`pins.dropped.jsonl`) 쓰기, 손상 줄의 원본 보존, 핀 번호(`pins.seq`), clear 보관. 서버를 가져오지 않는다. 파일 위치(`PinFiles`)·잠금·레코드 검사·줄 맞춤·`pins.md` 렌더·거절 예외를 `server.pin_store()`가 호출마다 인자로 넘긴다 (`tests/test_store.py`가 import를 검사) |
| [`src/limn/service/`](../../src/limn/service/context.py) | 718 | 핀 서비스, 곧 가장자리 셸(2026-09-26 옮김): 핀 잠금 아래 핀을 읽고(`PinStore.transact`) `limn/pins/`의 규칙에 묻고, 받아들일 때만 쓰고, 쓴 뒤에 알림과 감사 기록을 남긴다. 추가·편집(`add_edit.py`), 답글·닫기·다시 열기·확인(`transitions.py`), 처리 중 표시(`claim.py`), 휴지통·만료·영구 삭제·clear(`trash.py`). 결과는 타입 값(`Pin \| 거절 \| PinNotFound`)으로 돌려주고 HTTP로 바꾸는 일은 `web/answers.py`의 `match`만 한다. 협력자(저장소, 시계, 알림·감사 싱크, @태그 조회, 파일 위치, 설정 값)는 `PinContext`(`context.py`)로 받고, 행위자 판단 `is_agent`·`typed_actor`와 알림·감사가 적는 행위자 `who`도 여기 있다. `server.py`·`C`·시계 모듈을 모른다 (`tests/test_service.py`가 검사) |
| [`src/limn/people.py`](../../src/limn/people.py) | 143 | `people.json`(2026-09-26 옮김): 항목 검사(`valid_people`·`is_actor`), 저장 형식(`people_text`), 읽기, 실행 중 서버의 기록(`record_person`, 상태 폴더·잠금·마지막 기록 메모를 담은 `PeopleBook`을 받는다), @태그 후보(`known_people`, 에이전트 판단은 인자로 받는 순수 함수). 서버를 가져오지 않는다 (`tests/test_people.py`가 import를 검사) |
| [`src/limn/mentions.py`](../../src/limn/mentions.py) | 179 | @태그의 순수 규칙(2026-09-26 옮김): `@이름` 풀기, 지금 차례(`thread_round`), `addressed`·`fyi`, 메모 저장이 새로 부른 사람(`tag_note`)과 재알림 간격(`note_mention_targets`). 파일·시계·HTTP를 모른다 (`tests/test_mentions.py`가 import를 검사) |
| [`src/limn/events.py`](../../src/limn/events.py) | 168 | 알림(2026-09-26 옮김): 이벤트 한 건과 받는 사람(`make_event`, 문서 키·행위자 기록은 인자로 받는 조회. `excerpt`는 `pins.md`가 스레드 글을 한 줄로 줄이는 규칙 `limn.pins.render.flat` 하나를 쓴다), 폴링이 고르는 이벤트(`events_since`) — 둘은 순수 — 와 `events.jsonl` 쓰기·읽기(`EventLog`: 경로·잠금·읽기 캐시·시계를 받는다). 서버를 가져오지 않는다 (`tests/test_events.py`) |
| [`src/limn/audit.py`](../../src/limn/audit.py) | 80 | 감사 기록 `audit.jsonl`(2026-09-26 옮김): 한 줄 만들기(`audit_entry`, 시계는 인자), 프로세스 간 잠금 아래 덧붙이기(`append_audit`, 심볼릭 링크 거부), CLI의 행위자(`os_actor`). 서버와 CLI가 함께 쓴다 (`tests/test_audit.py`) |
| [`src/limn/pins/`](../../src/limn/pins/model.py) | 2,113 | 핀 도메인의 순수 코드: 상태 타입과 그 상태에만 있는 필드(`Claim`·`Close`·`Confirmation`·`Dropped`), 행위자 타입(`model.py`), 저장소가 믿는 레코드 모양 검사(`record.py`, 2026-09-26 옮김: `valid_rec`. 문서 키 규칙과 행위자 모양은 순수하지 않은 모듈의 것이라 인자로 받는다), 전이(`lifecycle.py`: 확인, 닫기·다시 열기, 답글, claim, 휴지통. `pins.md`의 다시 열림 판단 `pin_reopened_in_round`도 여기 있다), 편집 판단과 새 핀 레코드(`edit.py`), `pins.md` 렌더(`render.py`, 2026-09-26 옮김: 입력 값 `PinsMdInput` → 문자열. 겹침 배지 `rel_badge`와 한 줄 줄이기 `flat`도 여기 있다), 핀 위치 규칙(`position.py`, 2026-09-26 옮김: 위치 추정 `pin_est`, 겹침 `overlaps_by_id`·`selection_rel`, anchor 재동기화 `follow_anchor`·`resync`), API가 핀을 보이는 모양과 계산 필드(`view.py`, 2026-09-26 옮김: 레코드를 보이는 `public_record`, `state`를 내는 `pin_state` — 상태 타입의 이름이라 `parse_pin`과 규칙이 하나다 — 와 `GET /api/pins`·`GET /api/pins/dropped` 본문 `pins_payload`·`dropped_payload`. 레코드를 보이는 법, 문서, 빌드 이력, 시계는 인자다). 파일·시계·HTTP를 모른다 (`tests/test_pins_lifecycle.py`가 import를 검사, `render.py`가 가져오는 `guidance.py`·`mapping.py`까지. `view.py`가 가져오는 `mentions.py`는 `tests/test_mentions.py`가 검사) |
| [`src/limn/guidance.py`](../../src/limn/guidance.py) | 50 | 에이전트가 읽는 토큰 파일 문구(2026-09-26 옮김): 401 문구 `UNAUTHENTICATED`, 셸 경로 `shell_path`, 토큰 파일 curl 형태, 헤더 없는 로컬 요청을 막을 때의 401 문구. `pins.md` 인증 줄과 접근 검사가 같이 쓴다. 문자열만 다루고, 파일이 있는지와 홈 폴더는 부르는 쪽이 넘긴다 |
| [`src/limn/mapping.py`](../../src/limn/mapping.py) | 387 | 위치 계산의 순수한 절반: 범위 사다리, 블록 확장, 점수, anchor 찾기, 옮긴 원고에서 핀 파일 찾기(0.3.2, 있는지 확인은 인자로 받는다). 파일·subprocess·전역을 모른다 (`tests/test_mapping.py`가 import를 검사) |
| [`src/limn/locate.py`](../../src/limn/locate.py) | 488 | 핀 위치의 부수효과 쪽(2026-09-26 옮김): SyncTeX·pdftotext 실행, `.tex` 읽기, 토큰 가중치 캐시(`TokenCache`), 옮긴 체크아웃에서 핀 파일 찾기(`locate_file`·`pin_location`, ADR-0006), 저장된 핀 재동기화(`sync_all`), 겹침을 지금 찾은 파일로 세기(`overlaps_by_id`·`overlaps_for_range`, 찾기 함수 `Locator`를 인자로 받는다)와 `GET /api/overlaps` 본문(`overlaps_api`), 문서의 빌드 이력 읽기(`est_context`), 선택 해석(`pick`)과 snippet. 문서와 설정(`PickContext`: 원고 루트, `--float-envs`, 상태 폴더, 캐시, 겹침 조회)을 인자로 받는다. `C`·서버·HTTP 층을 모른다 (`tests/test_locate.py`가 검사) |
| [`src/limn/mark.py`](../../src/limn/mark.py) | 125 | Limn 마크(점에서 시작해 줄로 이어지는 한 획)의 기하 하나와 세 모양: 뷰어 인라인 SVG, 파비콘 SVG, 표준 라이브러리만으로 그리는 PNG. 순수하다 (`tests/test_brand.py`) |
| [`src/limn/viewer/`](../../src/limn/viewer/parts.txt) | 4,348 | 뷰어 화면: `index.html`(175), 스타일 조각 `css/` 10개(902), 스크립트 조각 `js/` 35개(2,989), 조각 순서 `parts.txt`(61), 서비스 워커 `sw.js`(10, 2026-09-26 `server.py`의 문자열에서 옮김: `GET /sw.js`가 따로 내주고 페이지에 끼우지 않는다). 조립(`assemble.py`(206), 2026-09-26 옮김): `parts.txt` 순서대로 조각을 이어 `index.html`에 끼우고 빌드 때 정해지는 자리 표시자(PDF.js 버전, 마크, Lucide 아이콘 표 `LUCIDE`와 `{{ic:…}}` 토큰, 영어 메시지 표)를 인자로 받은 값으로 채우는 `viewer_html(directory, messages, …)`, 메시지 표 읽기 `load_ui_messages(path)`, 서비스 워커 읽기 `service_worker(directory)`. 같은 폴더와 인자면 같은 문자열이고, 설정·`C`·서버·HTTP 층을 모른다 (`tests/test_viewer_assemble.py`가 import를 검사). 폴더는 2026-09-26부터 파이썬 패키지(`__init__.py`)이고, 데이터 파일은 그대로 휠에 든다. 빌드 단계·모듈 로더는 없다 ([viewer.md](viewer.md) §뷰어 규칙을 바꿀 때) |
| [`src/limn/instances.sh`](../../src/limn/instances.sh) | 1,628 | 원고별 인스턴스 관리자 (`limn add` 등, systemd·tailscale 호출). GNU(Linux)와 BSD(macOS) 명령, bash 3.2에서 돈다 |
| [`src/limn/migrate.py`](../../src/limn/migrate.py) | 271 | 이전 이름으로 설치된 인스턴스를 옮겨 오는 일회성 도구 |
| [`src/limn/cli.py`](../../src/limn/cli.py) | 496 | `limn` 명령 입구. `serve`는 `server.main`, `migrate`는 `migrate.main`, `token`·`member`는 `limn/access.py`의 상태 도우미로 상태 디렉터리의 `tokens.json`·`people.json`을 직접 고치고(감사 기록은 `server.py`가 묶어 준다. `token create --save`는 설정 폴더의 토큰 파일도 쓴다), 나머지는 `instances.sh`로 넘긴다 |
| [`src/limn/ui_en.json`](../../src/limn/ui_en.json) | 954 | 뷰어의 한국어 UI 문자열 → 영어 대응표 |
| `src/limn/vendor/` | — | 번들한 PDF.js와 Lucide 아이콘 (외부 CDN 없음) |

`server.py` 안은 `# ------` 배너 주석으로 관심사별 구역이 나뉘어 있다. 순서대로 문서(Doc)·쪽 디렉토리·빌드·빌드 이력(이 셋은 2026-09-26부터 `limn/build.py`를 부르는 얇은 셸이다)·원고 이력 연결(2026-09-26부터 `limn/revisions.py`·`limn/scope.py`)·`--git-pull`과 원격 main 감시 연결(2026-09-26부터 `limn/gitsync.py`·`limn/pull.py`에 프로세스의 pull 나눠 쓰기·감시 상태와 문서 목록·설정을 넘긴다. 보기 전용 PDF 다시 그리기는 `limn/build.py`로 옮겼다)·문서 목록과 meta 연결(2026-09-26부터 `limn/documents.py`·`limn/meta.py`·`limn/outline.py`를 부른다)·핀 저장소(2026-09-26부터 `limn/store.py`를 조립하고 옛 이름으로 넘기는 셸. 핀 파일 찾기·줄 맞춤 연결도 여기 있다)·`GET /api/pins`의 계산 필드와 겹침 연결(2026-09-26부터 `limn/pins/view.py`·`limn/locate.py`에 이 인스턴스의 협력자를 넘기는 한 줄짜리 연결)·요청 문서와 파싱 사실(`limn.documents`에 문서 목록과 설정을 넘기는 연결)·핀 조작(2026-09-26부터 `limn/service/`에 `PinContext`를 넘기는 `pin_context`와 옛 이름의 한 줄 연결)·사람과 이벤트(2026-09-26부터 `limn/people.py`·`mentions.py`·`events.py`·`audit.py`에 잠금·캐시·시계를 묶어 옛 이름으로 넘기는 셸)·휴지통과 처리 중 표시(같은 날부터 `limn/service/`를 부르는 한 줄 연결)·선택 해석 연결(원문 접근·역변환·위치 추정·겹침·선택 해석은 2026-09-26부터 `limn/locate.py`·`limn/pins/position.py`를 부르는 얇은 셸이다)·접근 제어 연결(2026-09-26부터 `limn/access.py`를 이 인스턴스에 묶는다)·뷰어(2026-09-26부터 `limn/viewer/assemble.py`의 `viewer_html`·`service_worker`를 부르는 두 줄)·HTTP 처리기 연결·입구다. 입구는 2026-09-26부터 시작 단계를 차례로 부르고 그 답을 `C`에 적용하는 조립만 남았고, 시작 규칙은 `limn/startup.py`, 명령줄 파서는 `limn/args.py`, 실행 설정의 타입은 `limn/config.py`에 있다. 뷰어 화면 자체는 2026-09-26부터 `src/limn/viewer/`에 있다 ([code-style-roadmap.md](code-style-roadmap.md) 3단계). 같은 날 스크립트와 스타일을 책임별 조각 파일로 나눴고, 서버는 조각을 정해진 순서로 이어 붙이기만 한다 (R6).

`server.py`는 `limn serve`로는 패키지 모듈(`limn.server`)로, 인스턴스(`limn run` → `instances.sh`)에서는 파일 경로(`python …/limn/server.py`)로 실행된다. 파일로 실행될 때도 옆 모듈을 `limn.*`으로 가져올 수 있도록, `server.py`는 시작할 때 자기 폴더의 부모를 `sys.path` 앞에 넣는다. 새로 꺼내는 모듈은 이 방식으로 가져온다. 이때 `limn/` 폴더 자체도 `sys.path` 맨 앞에 오므로, 표준 라이브러리 모듈과 이름이 같은 패키지(`limn/http/` 등)를 두면 표준 모듈(`http.server`)이 가려져 서버가 뜨지 않는다. HTTP 층을 `http/`가 아니라 `web/`에 둔 이유다. 서버와 옮긴 모듈은 Python 3.10 이상에서만 돈다. `server.py`가 `match` 문을 쓰므로 3.9는 파일을 읽는 단계에서 `SyntaxError`로 멈춘다. 옮긴 모듈이 `from __future__ import annotations`로 시작하는 것은 옆 모듈과 모양을 맞춘 것이지, 오래된 파이썬을 위한 장치가 아니다. 인스턴스 경로가 안전한 이유는 두 가지다. `limn run`(systemd 유닛이 부르는 명령)은 자기가 도는 도구 가상환경의 파이썬을 `LIMN_PYTHON`으로 넘기고, 그 파이썬은 설치 때 `requires-python >= 3.10`을 이미 통과했다. `limn`을 거치지 않고 `instances.sh`를 직접 부르면 PATH에서 3.10 이상인 파이썬을 찾는다. 없으면 `help`를 뺀 모든 명령이 무엇이든 시작하기 전에 멈추고, 그 파이썬의 경로·버전·고치는 법을 한 줄로 알린다([instances.md](instances.md) §환경 변수).

구역 사이에서 상태를 주고받는 방식은 세 가지다.

1. **모듈 전역 설정** `C = Cfg()` — 실행 인자를 담는다. 타입은 2026-09-26부터 `limn/config.py`에 있고, 시작할 때 `limn/startup.py`의 규칙이 낸 값을 `server.py`가 채운다. `server.py` 안에서 `C.` 참조는 106곳이고(2026-09-26), 모두 시작 단계가 `C`를 채우는 줄이거나 요청마다 설정 값을 옮긴 모듈에 넘기는 연결이다. HTTP 처리기(`limn/web/handler.py`)는 `app.C`로 세 곳을 읽는다(그중 하나는 닫기의 `changes`를 원고 폴더에 맞춰 파싱할 때다).
2. **문서는 인자다.** 2026-09-26까지는 스레드 지역 "현재 문서"(`using_doc(D)` / `cur_doc()`)를 요청 처리 코드가 인자 없이 읽었다. 이제 처리기가 요청의 문서를 찾아(`request_doc`) 서비스마다 넘기고, 빌드 스레드는 자기 문서를 갖고 시작하며, 기동은 문서 목록을 돈다. `cur_doc()`·`using_doc()`은 없다. 빌드의 옛 이름 셸(`cur_pages()`·`src_mtime()` 등)도 없어졌고, 부르는 쪽이 `limn.build` 함수에 문서를 넘긴다.
3. **모듈 전역 잠금과 상태 사전** — `PIN_LOCK`, `BUILD_LOCK`, `BUILD_STATE` 등. `PIN_LOCK`은 2026-09-26부터 `server.py`가 프로세스에 하나 만들어 `pin_store()`로 저장소(`limn/store.py`)에 넘긴다. 저장소 자신은 잠금을 만들지 않는다.

핀 레코드는 대부분의 코드에서 파이썬 `dict` 그대로 다닌다. 핀의 상태(열림·검토 대기·완료)는 `done`·`review` 같은 독립 필드의 조합에서 계산한다. 규칙은 `limn/pins/model.py`의 `state_of` 하나이고, API의 `state` 이름은 그 상태 타입의 이름이다(`limn/pins/view.py`의 `pin_state`). 2026-09-26부터 [`limn/pins/`](../../src/limn/pins/model.py)가 상태를 타입(`OpenPin`·`ReviewPin`·`DonePin`)으로 파싱하면서 그 상태에만 있는 필드(열림의 처리 중 표시, 닫힘의 닫은 기록, 완료의 확인)를 타입의 속성으로 올리고, 나머지 필드는 저장된 그대로 순서까지 지켜 다시 쓴다. 옮겨진 전이(확인, 닫기·다시 열기, 답글, claim, 휴지통, 편집)는 그 타입을 받아 결과를 반환값으로 돌려준다. 새 핀의 레코드도 `limn.pins.edit`이 만든다. 잠금 아래 레코드를 읽어 타입으로 파싱하고 전이를 부르고 결과를 다시 쓰는 셸은 2026-09-26부터 [`limn/service/`](../../src/limn/service/context.py)에 있다.

> **참고**
>
> 이 구조는 한 사람이 빠르게 기능을 쌓으며 자연스럽게 생긴 모양이다. 배포가 `uv tool install` 한 번으로 끝나고, 테스트가 소켓 없이 처리기를 직접 몰 수 있다는 장점이 있다. 우리 코딩 규칙과 어디가 다르고 어떤 순서로 맞춰 가는지는 [code-style-roadmap.md](code-style-roadmap.md)에 친절하게 정리했다.

## 채택한 설계 축

설계 축은 프로젝트가 기본 청사진에서 어디가 달라지는지를 묻는 질문 목록이다. 아래 값이 **현재 채택값**이고, 채택한 이유와 버린 대안은 [ADR-0001](../adr/0001-blueprint.md)에 남긴다. 표에 없는 축(경제·비용 게이트, 외부 검수 권위)은 Limn에서 달라지지 않아 따로 정하지 않았다.

| 축 | 채택값 | 근거와 적용 |
| --- | --- | --- |
| 1차 구조 | **작은 단일 배포 + 책임별 모듈.** 2026-09-26 §목표 구조대로 옮겼다([code-style-roadmap.md](code-style-roadmap.md) 3~6단계, `server.py`는 조립 지점). 옮기는 동안은 구조 이동 PR이 열린 기능 PR보다 우선했다 | 배포 단위·런타임이 하나다. 서버·인스턴스 관리자·migrate의 수명 주기만 다르다 |
| 도메인 정체 | **핀의 수명 주기와 위치 규칙.** 상태 전이, 역변환·범위 사다리·anchor 재동기화 | [domain.md](domain.md) |
| 함수형 DDD 범위 | **실용적 함수형.** 판단은 순수 함수, 부수효과(파일·git·subprocess·HTTP)는 가장자리. 의미 있는 수명 주기(핀 상태)에만 상태별 타입과 전이 함수를 쓰고, 계산·파싱은 평범한 함수로 둔다. 예상된 거절은 예외가 아니라 반환 타입의 거절 값(`Pin \| ConfirmRejected`)으로 돌려준다 | 우리 코딩 스킬 `code-implement`의 기본값. 현재 코드와의 차이는 [code-style-roadmap.md](code-style-roadmap.md) |
| 검수 진실원 | **자동 테스트 녹색 + 에이전트 계약 불변 + 화면 실측.** pytest·셸 테스트·Playwright 레이아웃 테스트가 통과하고, `pins.md`·HTTP API가 호환을 지키며, 화면 규칙은 실측 스크린샷으로 확인한다 | [verification.md](verification.md) |
| 검수 시점 | **머지 전 게이트.** CI가 막는다 | [verification.md](verification.md) |
| HARD-GATE | **행동 계약 변경 전.** 에이전트 계약·보안 경계·저장 형식을 바꾸는 변경은 설계 승인 뒤 구현한다 | [workflow.md](workflow.md) |
| 정본 매체 | 동작은 **코드**, 에이전트 계약은 **[api.md](api.md)와 [SKILL.ko.md](../../skill/SKILL.ko.md)**, 데이터는 **상태 디렉터리 파일**. Handbook은 설계 교과서이자 안내판 | [purpose.md](purpose.md) §진실 소스 |
| Handbook 책임 구성 | 목적·구조·도메인·뷰어·빌드·API·운영 두 편·검증·변경 흐름·코딩 로드맵으로 나눈다 | [index.md](index.md) |
| 시간축 호환 | **옛 상태 디렉터리와 옛 에이전트를 깨지 않는다.** 옛 레코드는 읽을 때 해석하고 쓰기 마이그레이션을 하지 않는다 | §불변식 3, 6 |

## 목표 구조

목표는 새 프레임워크나 계층을 들이는 것이 아니다. 지금 `server.py` 안에 배너로만 나뉜 책임을 **책임별 모듈**로 꺼내고, 판단과 부수효과를 갈라놓는 것이다. 한 번에 옮기지 않고 [code-style-roadmap.md](code-style-roadmap.md)의 단계대로 옮긴다.

```text
src/limn/
├── cli.py               limn 명령 입구 (지금과 같음)
├── pins/                핀 도메인 — 순수
│   ├── model.py         상태별 타입, 명령 값, 예상 실패
│   ├── record.py        저장소가 믿는 레코드 모양 검사 (2026-09-26 옮김)
│   ├── lifecycle.py     열기·닫기·확인·다시 열기·claim 전이 함수
│   ├── edit.py          편집 판단(거절은 값), 새 핀 레코드
│   ├── position.py      위치 추정·겹침·anchor 재동기화 규칙 (2026-09-26 옮김)
│   ├── view.py          GET /api/pins·휴지통 본문의 계산 필드 (입력 → 값, 2026-09-26 옮김)
│   └── render.py        pins.md 렌더링 (입력 → 문자열, 2026-09-26 옮김)
├── mapping.py           역변환·범위 사다리·anchor — 순수 계산 (2026-09-26 옮김)
├── locate.py            SyncTeX·pdftotext·.tex 읽기·핀 파일 찾기·재동기화·선택 해석 (부수효과, 2026-09-26 옮김)
├── mark.py              Limn 마크의 SVG·PNG — 순수 (0.3.4)
├── guidance.py          토큰 파일 안내 문구 — 순수 (pins.md 인증 줄과 401이 같이 쓴다, 2026-09-26)
├── store.py             핀 저장소: 잠금 아래 쓰기 순서·원자적 쓰기·손상 레코드 보존 (부수효과, 2026-09-26 옮김)
├── service/             핀 서비스 셸: 잠금 아래 읽고 규칙에 묻고 받아들일 때만 쓴 뒤 알림·감사 (부수효과, 2026-09-26 옮김)
├── build.py             원고 복사·latexmk·pdftoppm·쪽 디렉토리·빌드 이력·원고 지문 (부수효과, 2026-09-26 옮김)
├── files.py             원자적 파일 교체·상태 파일의 프로세스 간 잠금 (모든 저장 쓰기가 공유, 2026-09-26 옮김)
├── people.py            people.json 읽기·기록, @태그 후보 (부수효과 + 순수 후보 계산, 2026-09-26 옮김)
├── mentions.py          @태그 풀기·지금 차례·addressed/fyi·메모 태그와 재알림 간격 — 순수 (2026-09-26 옮김)
├── events.py            알림 한 건과 받는 사람·폴링 고르기(순수), events.jsonl 쓰기·읽기 (2026-09-26 옮김)
├── audit.py             audit.jsonl 한 줄과 추가 전용 쓰기 (부수효과, 2026-09-26 옮김)
├── access.py            신원·입장·역할·Host/Origin 판단, 토큰·멤버 상태 도우미 — 보안 경계 (부수효과, 2026-09-26 옮김)
├── web/                 HTTP 층 (부수효과). 표준 모듈 http를 가리지 않도록 web이다 (§현재 구조)
│   ├── handler.py       처리기·서버 클래스, 본문 읽기와 한도, 경로 분기 (2026-09-26 옮김)
│   ├── answers.py       핀 조작 결과 → 상태 코드·본문 (2026-09-26 옮김)
│   ├── errors.py        HTTPError·InputRejected·거절 표·거부된 첫 화면 (2026-09-26 옮김)
│   ├── app.py           처리기가 부르는 서비스 목록(App) — 지금은 server.py의 셸 이름 그대로
│   └── parse.py         요청 본문·쿼리 파서 — 값이나 InputRejected (2026-09-26 옮김)
├── viewer/              index.html · parts.txt(조각 순서) · css/ · js/ · sw.js(서비스 워커) — 패키지 데이터 파일, assemble.py가 한 장으로 잇는다 (2026-09-26 옮김)
├── config.py            실행 설정의 타입 Cfg (2026-09-26 옮김)
├── startup.py           시작 규칙: 접근 설정·포트·--doc·상태 폴더·라벨·요약, 거절은 StartupRefused 값 (2026-09-26 옮김)
├── args.py              limn serve 명령줄 파서 (2026-09-26 옮김)
├── server.py            조립 지점: 설정 적용, 자원 생성, 한 줄 연결, 스레드 시작·종료 (2026-09-26 조립 코드만 남음)
├── instances.sh
└── migrate.py
```

이름은 확정값이 아니다. 지켜야 하는 것은 **의존 방향**이다. `pins/`와 `mapping/`은 파일·subprocess·HTTP 타입을 가져오지 않는다. `store`·`service`·`build`·`web`은 그 순수 모듈을 불러 쓴다. `service`는 `store`를 쓰고, `web`은 `service`를 직접 부르지 않고 조립 지점이 묶은 `App`을 거친다. 조립 지점(`server.py`)만 전역 자원을 만들고 끝낸다.

`web/`은 `server.py`를 가져오지 않는다. `server.py`는 한 프로세스에 여러 벌 올라올 수 있어서(`limn.server`, 파일로 실행한 `__main__`, 테스트가 경로로 올린 사본) 가져오면 지금 요청을 받는 사본이 아닌 다른 사본의 설정·문서·잠금에 닿는다. 그래서 조립 지점이 자기 처리기 하위 클래스를 자기 서비스에 묶고(`server.Handler.app`), 처리기는 요청 때마다 그 이름을 읽는다. 반대 방향은 줄었다. 요청 파싱은 처리기 쪽(`web/parse.py`)이라 서비스는 파싱된 값만 받는다. 원고 이력·비교 PDF(`limn/revisions.py`)와 문서 조회는 결과 값(`CommitNotRecent`·`DocNotFound` 등)을 돌려주고 `web/answers.py`가 답한다. 신원·입장·역할 판단(`identify`·`admit`·`check_role`, 보안 경계)은 2026-09-26부터 `limn/access.py`에 있다. 이 모듈은 거절로 `HTTPError`를 던지고 확인 거절 문구(`CONFIRM_BY_HUMAN`)를 `web/`에서 가져온다. `server.py`를 가져오지 않으므로 처리기와 같은 방향이다. 조립 지점은 비교 PDF 워커에 실패 문구 함수(`web/errors.py`의 `revision_failure_text`)를 넘기려고 `web/errors.py`를 가져온다. 이 문구는 HTTP 응답과 같은 표에서 나와야 하고 서비스는 `web/`을 가져오지 않기 때문이다.

## 불변식

아래 규칙은 구조를 어떻게 바꾸든 유지한다. 각 규칙이 언제 적용되는지, 누가 지키는지, 어기면 무엇이 깨지는지를 함께 적는다.

### 1. 신원 방식 없이 loopback 밖에 열지 않는다

기본 바인드 주소는 `127.0.0.1`이다. 0.2.0부터 `--bind`로 다른 주소를 줄 수 있지만, loopback이 아닌 주소는 신원을 프록시가 보증하는 `--auth trusted-proxy`일 때만 받는다. 그 밖에는 서버가 시작을 거부한다. `--i-know-this-is-insecure`로 넘길 수는 있지만 크게 경고한다. 테일넷 노출은 `tailscale serve`, 그 밖의 노출은 인증 리버스 프록시가 맡고, `tailscale funnel`은 쓰지 않는다. 이 규칙이 깨지면 포트에 닿는 누구나 원고를 읽고 핀을 바꿀 수 있다. 근거와 위협 모델은 [SECURITY.md](../../SECURITY.md), 운영 상세는 [operations.md](operations.md) §보안 제약, 설계와 이후 단계는 [ADR-0002](../adr/0002-access-control.md)에 있다.

신원은 인스턴스마다 방식 하나(`tailscale`·`local`·`trusted-proxy`)로 정하고, 에이전트는 API 토큰으로 인증한다. 서버 머신의 에이전트는 토큰 원문을 설정 폴더의 토큰 파일(`<이름>.token`, `0600`, 저장소 밖)에서 읽고, 서버는 그 파일을 읽지 않는다([ADR-0007](../adr/0007-agent-token-file.md)). 권한은 `people.json`의 역할(owner·editor·viewer·agent)이 정하고, 처리기 한 곳에서 집행한다. 신원·입장·역할 판단과 Host/Origin 규칙의 코드는 [`limn/access.py`](../../src/limn/access.py) 한 곳에 있다. 이 모듈은 실행 설정(`C`)을 읽지 않는다. 조립 지점(`server.py`)이 요청마다 실행 설정 값(`AccessSettings`)과 파일 사실(`AccessLookups`: `tokens.json`·`people.json`을 파일이 바뀔 때만 다시 읽는 캐시, 프로세스에 하나씩)을 넘긴다. 이 경계의 거절은 값으로 돌려주지 않고 `HTTPError`를 던진다. 새로 짠 호출자가 거절을 놓쳐도 요청이 통과하지 않게 하기 위해서다(fail closed). 헤더 없는 요청을 에이전트로 보는 것은 이 기기를 부른 요청(루프백 `Host`)뿐이고, 모든 핀을 지우는 일은 소유자만 한다([ADR-0003](../adr/0003-tailnet-headerless-and-owner-clear.md)). 상세는 [api.md](api.md) §인증이다.

### 2. 서버 런타임은 표준 라이브러리만 쓴다

`pyproject.toml`의 `dependencies = []`가 이 규칙의 실행 정본이다. Python 3.10 이상에서 돈다. 뷰어도 React·Tailwind·빌드 단계·CDN 없이 번들한 PDF.js와 Lucide만 쓴다. 뷰어의 CSS·JS를 여러 조각 파일로 나눈 뒤에도 번들러나 모듈 로더를 들이지 않는다. 서버가 `parts.txt` 순서대로 조각을 이어 인라인 `<style>`·`<script>` 하나씩으로 내보낸다. 배포가 패키지 설치 하나로 끝나야 연구실 머신에서 유지할 수 있기 때문이다. 개발 의존성(pytest, Playwright, Ruff, ShellCheck, mypy)은 이 규칙과 무관하다.

### 3. 에이전트 계약은 호환을 깨지 않는다

`pins.md`의 열·표시어·한국어 머리말과 HTTP API의 경로·JSON 필드 이름·상태 이름은 다른 저장소의 에이전트가 읽는다. 새 필드와 경로를 더하는 것은 되지만, 바꾸거나 빼려면 버전이 붙은 이전 계획이 먼저 있어야 한다. UI 언어가 바뀌어도 계약은 번역하지 않는다. 계약의 본문은 [api.md](api.md)다.

### 4. 핀 파일은 한 잠금 아래 정해진 순서로만 쓴다

핀 파일을 만지는 모든 경로는 `PIN_LOCK` 하나 아래에서 **읽기 → 재동기화 → 요청한 변경 적용 → 임시 파일에 쓰고 `os.replace` → `pins.md` 재생성** 순서를 지킨다. 지금은 [`limn/store.py`](../../src/limn/store.py)의 `PinStore.transact()`가 이 순서를 강제하고, `server.py`의 `transact()`는 `pin_store()`로 만든 저장소에 그대로 넘긴다. 핀 파일(`pins.jsonl`·`pins.md`·`pins.dropped.jsonl`·`pins.seq`)을 쓰는 코드는 모두 `store.py`에 있다. 잠금이 없던 시절 핀 30개를 동시에 저장하면 2개만 남았다. 핀 번호는 `pins.seq`에서 발급하고 삭제 뒤에도 다시 쓰지 않는다. 상세는 [domain.md](domain.md) §저장소 안전성이다.

### 5. 원본 원고는 서버가 고치지 않는다

빌드는 사본에서 하고, `--git-pull`은 `main`에서 `--ff-only`만 한다. rebase나 merge 커밋을 대신 만들지 않는다. git 호출은 셸 없이 `subprocess.run([...])`로 하고 사용자 입력을 인자에 끼워 넣지 않는다. 상세는 [build-sync.md](build-sync.md)다.

### 6. 옛 상태 디렉터리는 쓰기 마이그레이션 없이 읽는다

`doc` 필드가 없는 옛 레코드는 첫 문서로 읽고, `review` 필드가 없는 옛 `done:true` 레코드는 그냥 완료로 읽는다. `file_rel` 이 없는 옛 레코드는 저장된 `file` 로 지금 원고 폴더에서 파일을 찾는다(0.3.2). 읽는 쪽이 해석할 뿐 파일을 고쳐 쓰지 않는다. 그래서 옛 버전으로 되돌려도 상태 디렉터리가 그대로 동작한다.

### 7. 앱 이름은 Limn 하나이고 개인정보를 넣지 않는다

옛 이름은 README 역사 절, `limn migrate`, CHANGELOG에만 남는다. 실제 이메일·홈 경로·호스트 이름·논문 이름을 코드와 문서에 넣지 않는다. [`tests/test_naming.py`](../../tests/test_naming.py)가 이를 검사한다.

### 8. 사람에게 보이는 문자열과 계약 문자열을 구분한다

뷰어 UI 문자열의 원본은 템플릿 안 한국어이고, 영어 모드는 [`ui_en.json`](../../src/limn/ui_en.json) 대응표로 바꾼다. `pins.md`와 API 오류 문자열(`{"error": "<한국어>", "reason": "<코드>"}`)은 계약이라 번역하지 않는다. 뷰어의 영어 화면은 오류 문장을 옮기지 않고 안정 코드 `reason`으로 표의 영어 문장을 찾는다([api.md](api.md) §오류 응답). 코드·주석·docstring·테스트 이름·커밋 메시지·CLI 도움말은 영어로 쓴다.

## 멈춤 신호

아래 변경은 코드부터 쓰지 말고 멈춘다. 설계를 먼저 정하고 필요하면 ADR을 남긴 뒤 구현한다. 절차는 [workflow.md](workflow.md)에 있다.

| 신호 | 예 | 왜 멈추나 |
| --- | --- | --- |
| 런타임 의존성 추가 | `dependencies`에 패키지를 넣는다 | 불변식 2 |
| 새 저장 파일이나 저장 형식 변경 | 상태 디렉터리에 새 파일, 레코드 필드 의미 변경 | 불변식 4, 6. 옛 상태와의 호환을 설계해야 한다 |
| 새 상태 기계·권한·비동기 흐름 | 핀 상태 추가, 역할 기반 권한, 새 백그라운드 스레드 | 수명 주기와 동시성 규칙이 바뀐다 |
| 에이전트 계약 변경 | `pins.md` 열, API 필드·경로·상태 이름 | 불변식 3 |
| 보안 경계 변경 | 바인드 규칙, 신원 방식, 토큰, 역할별 허용 범위, Host·Origin 검사, 신원 헤더 신뢰 범위 | 불변식 1, [SECURITY.md](../../SECURITY.md) |
| 공유 모듈로 승격 | 두 곳에서 쓰는 코드를 공용 모듈로 뺀다 | 소비자가 실제로 둘 이상인지 먼저 확인한다 |
| 도메인이 부수효과를 부름 | 순수 모듈이 파일·subprocess·HTTP 타입을 가져온다 | §목표 구조의 의존 방향 |
