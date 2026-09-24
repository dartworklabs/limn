# HTTP API 상세

[`SKILL.md`](../SKILL.md) 의 짧은 표로 모자랄 때 연다. 엔드포인트 전체, 핀 수정·닫기·claim·겹침, 레코드 스키마, `<state_dir>/pins.md` 형식을 다룬다. 재빌드·자동 동기화·위치 추정은 [build-sync.md](build-sync.md), Host·Origin 검사는 [operations.md](operations.md) §보안 제약에 있다.

## 요청 형식과 경계

바디는 1 MiB 이하 JSON 객체이고 `Content-Type: application/json` 이어야 한다(아니면 `400`/`413`/`415`). 본문 없는 POST(에이전트의 `curl -X POST …/close`)는 헤더 없이 그대로 된다. 오류 응답은 항상 `{"error": "<한국어 메시지>"}` JSON 이며 예상 밖 예외도 `500` JSON 으로 돌려준다. 기존 경로는 계약을 유지하고 새 필드·경로는 덧붙이기만 했다.

- 서버는 **어떤 응답보다 먼저 본문을 Content-Length 만큼 끝까지 읽고**, 오류(`4xx`/`5xx`) 뒤에는 연결을 닫는다. `Transfer-Encoding` 요청은 `400`. 본문이 Content-Length 보다 짧게 끊기면 `400` 이고 동작하지 않는다(`/api/clear` 포함). 읽지 않은 본문이 같은 keep-alive 연결의 다음 요청으로 해석되면 `--allow` 와 작성자 기록을 우회하기 때문이다 — tailscale serve 는 백엔드 연결을 재사용한다.
- 교차 출처 `Origin`·낯선 `Host` 는 `403` — 규칙과 이유는 [operations.md](operations.md) §Host·Origin 검사.
- 소켓 타임아웃 30초 — 본문을 보내다 멈춘 연결과 유휴 keep-alive 가 닫힌다(재빌드처럼 오래 걸리는 처리 자체와는 무관).

## 문서 매개변수 (`doc=`)

여러 문서(`--doc`, [operations.md](operations.md) §여러 문서)로 띄운 뷰어는 문서가 걸리는 경로에 `doc=<키>` 를 받는다 — `GET /api/meta`·`/api/build`·`/pdf`·`/pages/<쪽>`·`/api/snippet`·`/api/overlaps`·`/api/pins`(그 문서의 핀만 거른다), `POST /api/pick`·`/api/pin`·`/api/rebuild`. POST 는 쿼리 또는 JSON 본문의 `doc` 둘 다 받고, 둘이 다르면 `400`. 없으면 첫 문서다. 단 `POST /api/pin` 에 `doc` 없이 `file` 만 오면(에이전트 `curl`) 그 파일을 빌드 루트가 가장 깊게 감싸는 LaTeX 문서로 짐작한다. 없는 키는 `404 {error, docs:[키…]}` — 조용히 첫 문서로 물러서지 않는다(다른 문서에 핀이 붙는다). 핀 id 로 가는 경로(`/api/pins/{id}/…`)는 `doc` 이 필요 없다 — 핀의 문서는 레코드에 있다. 단일 문서 뷰어는 `doc` 을 무시해도 된다(키는 `main`).

## 엔드포인트

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/meta` | `pages`(쪽 목록), `built_at`, `head`(원고 커밋), `main`(최상위 .tex 이름), `label`·`accent`·`repo`(이 인스턴스의 이름표·강조색·git origin URL, operations.md §여러 논문 뷰어를 동시에 띄울 때), `n_open`·`n_done`, `pins_md`·`state_dir`(절대경로), `me`(지금 요청자), `building`(재빌드 진행 중), `stale_build`(이 PDF 를 만든 뒤 원고 `.tex` 가 바뀌었는가), `src_mtime`·`build_src_mtime`·`src_age_s`·`pins_rev`(build-sync §자동 동기화), `pages_build`(지금 화면 빌드 id = `pages.cur` 값), `build_seq`(끝난 빌드 수)·`last_build:{state,errors,finished_at,seq}`·`build:{state,phase,started_at}`(build-sync §비동기 재빌드), `doc`·`doc_name`·`kind`·`view_only`·`multi`(§문서 매개변수). 여러 문서면 `docs`(= `/api/docs` 항목에서 `n_open` 을 뺀 것)와 `src_sig`(문서마다의 `src_mtime` 을 이은 문자열 — 뷰어가 다른 문서의 원고 변화로도 목록을 다시 읽는다)가 붙는다(라이트 포함) |
| `GET` | `/api/docs` | 문서 목록 `{docs:[{key,name,kind:"tex"\|"pdf",view_only,path,main,n_open,stale_build,building,build:{state,phase},build_seq,last_state,pages_build,n_pages,src_mtime}], default, multi, other_open}`. 핀은 읽기만 한다(sync 쓰기 없음). `other_open` = 설정에 없는 문서 키의 열린 핀 수 |
| `GET` | `/api/revisions?doc=<키>` | 선택한 메인 `.tex` 폴더의 `.tex`·`.bib`·`.sty`·`.cls`·`.bst` 파일을 바꾼 최근 Git 커밋 12개 → `{available,revisions:[{id,date,subject}]}`. Git 저장소가 아니거나 보기 전용 PDF면 `available:false` |
| `GET` | `/api/revision-diff?doc=<키>&commit=<40자리 SHA-1>` | 위 최근 목록에 나온 커밋의 실제 unified diff → `{id,diff,truncated}`. 선택한 메인 파일의 폴더 안의 같은 원고 확장자만 포함하고 최대 256 KiB를 보낸다. 잘못된 ID는 `400`, 목록 밖 ID·보기 전용 PDF는 `404` |
| `GET` | `/api/outline-labels?doc=<키>` | 현재 PDF와 함께 보존한 `.aux`의 목차 → `{build,labels:[{number,title,page,level,anchor}]}`. PDF.js outline과 제목·계층·순서가 일치할 때만 번호를 붙인다. `page`는 인쇄 쪽번호 문자열(로마 숫자 가능)이며 물리 PDF 페이지 인덱스가 아니다. `.aux`가 없는 기존 빌드는 빈 배열, 지원하지 않는 복잡한 TeX 제목은 빈 number/title 자리표시자 |
| `POST` | `/api/revision-build` | `{commit,doc?}`. 선택 커밋 첫 부모 → 선택 커밋 비교 PDF를 비동기로 시작한다. `202 {state:"running",job_id,base,head,engine,warnings,error,reason}`, 성공 캐시는 `200 {state:"ready",…}`. `doc`은 쿼리도 지원. 다른 임의 필드는 `400` |
| `GET` | `/api/revision-build?doc=<키>&commit=<40자리 SHA-1>` | 같은 상태 스키마를 조회한다. `state`는 `idle`(미실행·만료), `running`, `ready`, `error`. `error`는 설명, `reason`은 오류 분류. 매번 현재 문서의 최근 커밋 목록을 다시 확인한다 |
| `GET` | `/api/revision-pdf?doc=<키>&commit=<40자리 SHA-1>` | 성공한 동일 비교의 PDF. 미완성·실패·만료는 `404`이며 현재 원고 PDF로 대체하지 않는다. 현재 페이지·SyncTeX·핀 좌표와 별개인 열람 전용 결과 |
| `GET` | `/api/meta?light=1` | 위와 같되 `n_open`·`n_done` 이 없고 **쓰기를 하지 않는다**(`sync`·`live_pins` 를 부르지 않음) — 폴링 전용. build-sync §자동 동기화 |
| `GET` | `/api/build` | `{state:"idle\|running\|ok\|ok_errors\|fail", phase:"pull\|copy\|latex\|render"\|null, started_at, finished_at, seq, last, elapsed_s, last_s, pages, errors:[{line,msg}], log_tail, built_at, head, pull}` — build-sync §비동기 재빌드. 서버를 다시 띄워도 마지막 빌드 결과(`state`·`errors`·`log_tail`·`seq`·`head`·`pull`)는 `builds.json` 에서 되살린다. `log_tail` 은 build-sync §에이전트 응답 다이어트를 따른다(`state=="ok"` 면 빠지고, 아니면 40줄, `?log=1` 이면 전체) |
| `GET` | `/pins.md` | 원격 에이전트 진입점 — `text/markdown; charset=utf-8` 로 `<state_dir>/pins.md` 와 같은 내용을 낸다(`GET /api/pins` 와 같은 sync 경로를 탄 뒤 렌더). 안내 줄의 base URL 만 요청 `Host` 로 바꾼다: `Host` 가 `*.ts.net` 이면 `https://<Host 그대로>`, 루프백이면 기존 `http://127.0.0.1:<port>`. 디스크의 `<state_dir>/pins.md` 는 항상 루프백 base 다. Host/Origin 검사는 다른 `GET` 과 같다 — §원격 에이전트 진입점 |
| `POST` | `/api/pick` | 드래그 좌표(`page`, `x0`, `y0`, `x1`, `y1`, 선택 `frac` = 숫자 4개 목록 `[x, y, w, h]`(쪽 대비 비율) — 다른 모양이면 `400`, 선택 `pdf_build` = 드래그할 때 화면의 빌드 id — 그 빌드의 PDF 로 되짚는다. 이미 지워진 빌드면 `200 {error, pdf_build_gone:true}`, 모양이 틀리면 `400`) → `{file, name, lo, hi, raw_lo, raw_hi, kind, via, score, warn, snippet, frac, levels, default_level, n_lines, quote, overlaps, pdf_build}`. `quote` 는 선택 영역 글자를 공백 정규화해 자른 60자, `overlaps` 는 같은 파일의 열린 핀과의 겹침(§겹친 핀). 입력 오류는 `400`, 되짚기 실패는 `200 {error}`. `levels`·`via`·`score` 는 [design.md](design.md) §범위 사다리·§역변환이 두 경로인 이유 |
| `GET` | `/api/pins` | 열린 핀 목록(JSON). 레코드마다 `rev`·`rel`(§겹친 핀)·`est`(불리언, build-sync §위치 추정) 이 채워진다 — `rel`·`est` 는 계산 필드라 저장하지 않는다. `?all=1` 이면 닫힌 핀까지 |
| `GET` | `/api/pins/{id}` | 핀 한 건 `{pin}` — `GET /api/pins?all=1` 한 항목과 같은 모양(스레드 전부·계산 필드 포함). 없으면 `404` |
| `POST` | `/api/pins/{id}/reply` | 답글 `{"text", "mentions"?}` → `{ok, pin, msg}` — §스레드 |
| `POST` | `/api/pins/{id}/confirm` | 검토 대기 → 완료 → `{ok, pin, state}` — §검토 대기 |
| `GET` | `/sw.js` | 브라우저 알림용 서비스 워커(`text/javascript; charset=utf-8`, `Cache-Control: no-cache`, 범위 `/`). `fetch` 처리기가 없다 — 앱 데이터를 캐시하지 않는다 |
| `GET` | `/api/people` | @태그 후보 `{people:[{login,name,pic?,last_seen?}], me}` — §@태그·사람·이벤트. 쓰기 없음 |
| `GET` | `/api/pins/dropped` | 삭제한 핀 목록 → `{dropped: [...]}`, `pins.dropped.jsonl` 을 `dropped_at` 순으로 그대로 낸다(계산 필드 없음, 쓰기 부작용 없음). 뷰어의 '삭제한 핀 N' 접힌 목록과, 열린 목록에서 사라진 핀이 완료인지 삭제인지 가르는 알림(build-sync §자동 동기화)이 이것을 쓴다 |
| `GET` | `/pdf?build=<pages_build>` | 그 빌드의 쪽 이미지와 짝인 PDF 사본(`pages-<build>/<main>.pdf`)을 `application/pdf` 로 준다(`Cache-Control: private, max-age=600`). 뷰어가 벡터로 그릴 때 쓴다([design.md](design.md) §벡터 렌더링). `build` 를 빼면 지금 빌드. 이름이 틀렸거나 이미 지워졌거나 그 디렉토리에 PDF 가 없으면 `404 {error, pdf_build_gone, pages_build}` — `build/` 나 다른 빌드로 물러서지 않는다(화면의 쪽 이미지와 어긋나면 좌표가 틀린다). `Range` 는 받지 않는다(통째로 준다). Host/Origin 검사는 다른 `GET` 과 같다 |
| `GET` | `/vendor/pdfjs/<파일>.mjs` | 뷰어가 쓰는 PDF.js(`pdf.min.mjs`·`pdf.worker.min.mjs`)를 `text/javascript; charset=utf-8` 로 준다(`Cache-Control: public, max-age=86400`, 뷰어가 `?v=<버전>` 을 붙여 캐시를 가른다). 이름 한 칸의 `.mjs` 만 받는다 — 하위 경로·`..`·점으로 시작하는 이름·`%` 인코딩·디렉토리 밖을 가리키는 심볼릭 링크·`.mjs` 가 아닌 파일(`LICENSE`·`README.md`)은 `404`. 디렉토리는 `--pdfjs-dir`([operations.md](operations.md) §실행 인자), 출처·버전은 [`vendor/pdfjs/README.md`](../vendor/pdfjs/README.md). Host/Origin 검사는 다른 `GET` 과 같다 |
| `GET` | `/api/snippet?file=&lo=&hi=` | 원문 줄 스니펫(80줄 캡). `&levels=1` 이면 그 범위를 기준으로 한 사다리도. 원고 트리 밖이거나 범위가 틀리면 `400` |
| `GET` | `/api/overlaps?file=&lo=&hi=` | 그 범위(저장 전 선택)와 열린 핀의 겹침 `{overlaps}` — 뷰어는 쓰지 않고(§겹친 핀) 에이전트·옛 뷰어 호환용으로 남긴다 |
| `POST` | `/api/pin` | 새 핀 추가 → `{id}`. 저장 필드 화이트리스트: `file, name, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, note, scope, quote, pdf_build`. `pdf_build` 를 안 보내면(에이전트 `curl`) 지금 빌드로 찍는다 |
| `POST` | `/api/pins/{id}/edit` | 제자리 수정 — 아래 §핀 수정 |
| `POST` | `/api/pins/{id}/close` | 핀 1건을 닫는다(`done: true`, `closed_by`). 에이전트가 닫으면 검토 대기(`review: true`), 테일넷 사람이 닫으면 완료 — §검토 대기. 선택 본문 `{"reply", "ref", "review"}` — 아래 §닫을 때 사유 남기기. 레코드는 남고(`<state_dir>/pins.md` 에서는 열린 표에서 빠지고 머리줄 건수로만 남는다 — §pins.md 형식) → `{ok, pin}`. 그 id 가 없으면 `200 {"ok": false, "pin": null}`(reopen 도 같다). **이미 닫힌 핀을 다시 닫으면 `{ok: true, pin}` 을 그대로 돌려주되 아무 필드도 바꾸지 않는다**(rev 도 그대로) — §닫을 때 사유 남기기 |
| `POST` | `/api/pins/{id}/reopen` | 닫은 핀을 되돌린다(`reopened_by`). `close_reply`/`close_ref`·`review`·`confirmed_*` 가 있었으면 지운다(다시 닫을 때 새로 남긴다). 선택 본문 `{"reason"}` 은 스레드에 남는다 → `{ok, pin, state}` |
| `POST` | `/api/pins/{id}/drop` | 핀을 목록에서 빼 `pins.dropped.jsonl` 로 옮긴다(잘못 찍은 것, `dropped_by`) → `{ok}`. 없는 id 면 `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/restore` | 삭제한 핀을 같은 id 로 되살린다(서버 재시작 뒤에도, `restored_by`) → `200 {ok, pin}` / `404`(삭제 기록 없음) / `409`(같은 id 가 이미 있음) |
| `POST` | `/api/pins/{id}/claim` | 처리 중 표시를 걸거나(같은 신원이면) 연장한다 — §처리 중 표시(claim). 선택 본문 `{"eta_min": 1..240, "ttl_min": 1..120}`(정수가 아니거나 1 보다 작으면 `400`, 상한을 넘으면 상한으로 깎는다) → `{ok, pin, ttl_min_applied, eta_min_applied?}`. 다른 신원이 유효한 claim 을 쥐고 있으면 `409 {"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}`. 닫힌 핀이면 `409 {"error":"done","pin":...}`. 없는 id 면 `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/unclaim` | 처리 중 표시를 지운다 — 요청자 신원과 무관하다(권한 제한 없음, 귀속만 기록하는 신뢰 모델). → `{ok, pin}`. 없는 id 면 `200 {"ok": false}` |
| `POST` | `/api/clear` | 전체를 아카이브(`pins_<timestamp>.jsonl.bak`, 같은 초에 또 비우면 `pins_<timestamp>-1.jsonl.bak` …)하고 비움 — 일괄 리셋. id 발급 번호는 이어진다. **에이전트는 쓰지 않는다** |
| `POST` | `/api/rebuild` | PDF 재빌드(동기) — build-sync §재빌드. 응답에 `head`(빌드한 커밋 짧은 해시, 성공 때만)·`pull`(`--git-pull` 일 때만, build-sync §`--git-pull`)이 붙는다. `log` 는 build-sync §에이전트 응답 다이어트를 따른다 |
| `POST` | `/api/rebuild?async=1` | PDF 재빌드(비동기) — 잠금을 얻으면 데몬 스레드로 같은 빌드 함수를 돌리고 바로 `202 {"state":"running"}`. 이미 도는 중이면 `409 {"state":"running","busy":true}`. 진행 상황은 `GET /api/build` 를 폴링한다(build-sync §비동기 재빌드) |
| `POST` | `/api/rebuild?log=1` / `GET /api/build?log=1` | build-sync §에이전트 응답 다이어트의 다이어트를 끄고 전체 로그 꼬리(4000자)를 그대로 받는다. 뷰어는 오류 패널을 위해 이 플래그를 항상 붙인다 |

## 비교 PDF 실행과 캐시

비교는 선택 커밋의 **첫 부모 → 선택 커밋**이다. 합병 커밋도 첫 부모를 쓴다. 첫 커밋은 `422 reason:no_parent`다. Git 객체에서 빌드 루트의 두 스냅샷을 만들며 미커밋 수정은 포함하지 않는다. 과거 커밋에 현재 메인 경로가 없으면 `missing_main`으로 실패한다. 이름 변경 전 경로를 추측하지 않는다.

Linux `bwrap`, `latexdiff`, `latexmk`가 필요하다. 실행 파일은 `/usr` 아래 시스템 설치만 허용한다. 홈·원본 저장소·네트워크를 노출하지 않는 bwrap 격리에서 `latexdiff --flatten --math-markup=off`와 `latexmk -norc -pdf -no-shell-escape -interaction=nonstopmode -halt-on-error`를 실행한다. 격리 실행이 불가능하면 실패하며 격리 없는 재시도는 하지 않는다. 현재 비교 엔진은 pdfLaTeX다. XeLaTeX/LuaLaTeX 전용 원고는 소스 변경사항으로 확인한다. kotex 등 원고 패키지를 임의로 제거하지 않는다.

`input/include/subfile` 등은 각 Git 스냅샷에서 펼친다. 포함 파일이 없으면 비교 PDF를 성공 처리하지 않는다. 파일마다 64 MiB, 스냅샷마다 256 MiB·4,000개, PDF는 32 MiB로 제한한다. 심링크·gitlink·경로 이탈은 거부한다. 두 프로세스 파이프의 합은 기본 8 MiB까지 읽고, Git 사본은 각각 60초, latexdiff는 60초, latexmk는 서버 `--timeout`과 180초 중 작은 값으로 제한한다. 시간 초과·출력 초과 시 프로세스 그룹을 종료한다.

비교 상태는 문서별 `<state>/revisions/`에 보존한다. 키에는 저장소·빌드 루트·메인 경로·두 전체 SHA·엔진·구현 버전이 포함된다. 성공 PDF와 상태를 완료 뒤 확정하고 원고의 `pages.cur`, `builds.json`, 핀은 바꾸지 않는다. 프로세스 전체에서 최대 두 작업, 동일 문서 상태 폴더에서 최대 한 작업을 허용한다. 같은 작업의 중복 요청은 기존 상태를 반환하고 다른 작업으로 자리가 찼으면 `409 reason:busy`다. 문서별 캐시는 최대 여섯 비교, 24시간이며 다음 요청 때 정리한다. 도중 재시작한 작업은 다음 요청에서 다시 만든다. 실패한 작업은 POST로 재시도할 수 있다.

경고는 실패와 구분한다. 삭제 문장이 옛 라벨을 참조해 `??`가 생길 수 있고, 수식 내부·같은 파일명의 그림 바이너리 변경은 강조되지 않을 수 있다. 서지·스타일·주석만 바뀐 경우 본문에 강조가 없을 수 있다. `warnings`를 표시하고 원래 소스 diff 경로를 함께 제공한다. 서버 파일의 `build.log`는 마지막 8,000자만 보존하며 HTTP 응답에는 로그 전체를 노출하지 않는다.

## 핀 수정 (`/api/pins/{id}/edit`)

```json
{"note": "고친 메모", "lo": 185, "hi": 262, "scope": "env2", "kind": "env:minipage", "base_rev": 3}
```

- `base_rev` 는 필수다 — 수정하려는 핀을 읽을 때 받은 `rev`. 다르면 `409 {"error":"conflict","pin":<최신>}` 이고 아무것도 바뀌지 않는다. 에이전트가 먼저 닫았거나 자동 줄 맞춤이 옮긴 핀을 옛 `lo`/`hi` 로 조용히 덮어쓰지 않기 위해서다. `409` 를 받으면 최신 `pin` 을 보고 다시 보낸다.
- 위치를 통째로 바꿀 때는 `loc: {file, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, scope, pdf_build}` 를 보낸다(위치 다시 잡기). `pdf_build` 는 `loc` 에 `frac` 이 있을 때만 바뀐다(없으면 pick 응답 값, 그것도 없으면 지금 빌드). 메모·`note_append`·`lo`/`hi` 만 고치는 편집은 `pdf_build` 를 건드리지 않는다. 필수는 `file`·`lo`·`hi` 다. `loc` 에 없는 `page`·`frac` 은 기존 값을 두고, `kind` 가 없으면 `lines` 가 된다(나머지 위치 필드는 지워진다). id·메모·작성자는 그대로다.
- 범위가 바뀌면 `anchor` 를 새로 떠고 `stale`/`sync` 를 지운다 — `stale` 핀도 이 경로로 고친다.
- 닫힌 핀은 메모만 고칠 수 있다. 범위·위치를 보내면 `409 {"error":"done"}`.
- 성공하면 `edited_at`·`edited_by` 가 기록되고 `rev` 가 1 오른다.
- `note_append`(빈 문자열·공백만은 `400`, 개별 조각은 ≤2000자)는 `base_rev` 없이도 받는다 — `note += "\n(추가 HH:MM) " + note_append`. 합친 뒤 길이가 메모 상한(`NOTE_MAX`, 4000자)을 넘으면 `400` 이고 아무것도 바뀌지 않는다(개별 조각이 2000자 이하여도 기존 메모와 합치면 넘을 수 있다). 겹친 핀에 "덧붙이기"로 쓸 때, 매번 최신 `rev` 를 먼저 조회하지 않아도 되게 하기 위해서다(§겹친 핀). 되돌리려면 응답의 `pin.rev` 를 `base_rev` 로 삼아 `{"note": <이전 note>}` 를 다시 보낸다.

## 닫을 때 사유 남기기 (`/api/pins/{id}/close`)

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/close \
  -H 'Content-Type: application/json' \
  -d '{"reply": "제목을 …로 바꿈", "ref": "PR #227"}'
```

- 둘 다 선택이다. **에이전트는 무엇을 고쳤는지와 PR 번호를 남긴다** — `reply` 에 무엇을 고쳤는지(≤500자), `ref` 에 참조(PR 번호 등, ≤80자). 나중에 공저자가 닫힌 핀을 봤을 때 왜 닫혔는지 다시 원고를 뒤지지 않아도 된다. 본문이 없거나 비어 있으면(빈 문자열·공백만) 기존과 같이 동작한다 — 옛 에이전트의 본문 없는 `curl -X POST …/close` 는 그대로 통과한다.
- 문자열이 아니거나 상한을 넘으면 `400` 이고 아무것도 바뀌지 않는다. 값은 다른 필드와 마찬가지로 뷰어에서 `esc()` 를 거쳐 렌더된다(이스케이프).
- 성공하면 핀에 `close_reply`/`close_ref` 로 저장되고 닫힌 카드에 보인다. 같은 `ref` 를 가진 닫힌 핀은 UI 가 묶어 보일 수 있다.
- **이미 닫힌 핀을 다시 닫으면 아무것도 바꾸지 않는다** — `done_at`·`closed_by`·`rev`·`close_reply`·`close_ref` 모두 첫 닫기 값 그대로고, 두 번째 호출의 `reply`/`ref` 는 버려진다(적용되지 않는다). 두 번째 닫기가 `done_at`·`closed_by` 를 덮어써 처음 닫은 사람이 사라지던 결함(실측)을 막기 위해서다. **reply 를 새로 남기려면 `/reopen` 으로 한 번 열고 다시 `/close` 한다** — `reopen` 이 옛 `close_reply`/`close_ref` 를 지우므로 다음 닫기가 새 사유로 채운다.
- 에이전트의 `curl` 은 신원 헤더가 없으므로 `closed_by` 가 `로컬/에이전트` 로 남는다.

## 스레드 (`/api/pins/{id}/reply`)

A-DEMO 핀 42건 중 10건(24%)이 고칠 곳이 아니라 질문이었는데(#30 '구간이 0을 포함한다는 게 뭐지?' 등) 답을 남길 곳이 닫기 사유 한 칸뿐이라 되물을 수 없었다. 핀마다 선택 필드 `thread` 를 두고 사람·에이전트가 같은 경로로 글을 단다.

```bash
curl -s -X POST <base>/api/pins/12/reply -H 'Content-Type: application/json' -d '{"text": "95% 신뢰구간이다"}'
```

- `text` 는 문자열 1..1000자(앞뒤 공백을 걷은 뒤, CRLF→LF, 줄바꿈·탭 밖의 제어 문자는 뺀다). 틀리면 `400`, 없는 id 는 `200 {"ok": false}`, 답글이 200건이면 `409 {"error":"full"}`.
- 메시지 `{id, by:{login,name,pic?}, at, text, mentions?, ev?, ref?}`. `id` 는 핀 안에서 1부터 오른다. 상태 전환도 한 줄씩 남는다 — `ev` 가 `close`(글 = 닫기 사유, `ref`), `reopen`(글 = 다시 연 이유), `confirm`. 닫기 사유는 옛 `close_reply`/`close_ref` 에도 그대로 적힌다(옛 뷰어·에이전트 호환).
- 답글은 상태를 바꾸지 않는다. 질문 핀은 답글을 단 뒤 따로 닫는다.
- 핀 종류는 `kind_req`(`fix`|`question`, 없으면 fix)다. `POST /api/pin`·`/edit` 이 받는다(`/edit` 는 닫힌 핀에서도 된다). 옛 `kind`(범위 종류)와는 다른 필드다.

## 검토 대기 (`close` → `review` → `confirm`)

에이전트가 닫은 핀을 작성자가 다시 연 일이 42건 중 2건(#28·#42)이었고, 사람이 결과를 봤다는 기록이 없었다.

| 전환 | 조건 | 결과 |
| --- | --- | --- |
| 닫기 | 신원 헤더 없음(로컬 curl·에이전트, 헤더 없는 태그 장치) | `done:true` + `review:true` = **검토 대기** |
| 닫기 | 테일넷 사람(헤더 있음) | `done:true` = 완료(그 사람이 검토자다) |
| 닫기 | 본문 `"review": true`/`false` | 그 값을 따른다 — 테일넷 주소로 닫는 원격 에이전트는 `true` 를 보낸다 |
| `POST /confirm` | 검토 대기 | `review` 를 지우고 `confirmed_by`·`confirmed_at` 을 남긴다(스레드 `ev:confirm`). 누구나 누를 수 있다 — 뷰어는 작성자를 권할 뿐이다 |
| `POST /confirm` | 완료 / 열림 / 없음 | 그대로 `{ok:true}`(멱등) / `409 {"error":"open"}` / `200 {"ok":false}` |
| `POST /reopen` | 닫힌 핀(검토 대기·완료) | 열림. `review`·`confirmed_*`·`close_reply`·`close_ref` 를 지우고 스레드에 `ev:reopen`(선택 `{"reason"}` ≤1000자가 글) |

- **하위 호환**: 검토 대기가 `done:true` 라서 옛 계약이 그대로 선다 — `GET /api/pins`(열린 핀만)에 없고, `claim` 은 `409 done`, 줄 맞춤·겹침 계산은 건너뛰고, 옛 서버·옛 탭은 완료로 본다. `review` 가 없는 옛 `done:true` 는 완료다. 읽을 때 이관 쓰기를 하지 않는다.
- 응답과 `GET /api/pins` 항목에는 계산 필드 `state`(`open`|`review`|`done`)가 붙는다(저장하지 않는다). `/api/meta` 는 `n_open`·`n_review`·`n_done`(완료만).
- 두 번째 닫기는 예전처럼 아무것도 바꾸지 않는다 — 검토 대기 핀을 에이전트가 다시 닫아도 그대로다.

## @태그·사람·이벤트

뷰어 안에서만 부른다. 바깥 알림(GitHub·Telegram·메일)은 보내지 않고, 나중에 붙일 수 있게 `events.jsonl` 에 적어 둔다.

- **사람**(`<state_dir>/people.json`, `{"version":1,"people":[{login,name,pic?,first_seen,last_seen}]}`): 이 뷰어를 연(`GET /`, 전체 `/api/meta`) 또는 쓰기 요청을 보낸 테일넷 사람. 로컬/에이전트는 적지 않는다. 같은 값이면 10분에 한 번만 다시 쓴다(`/api/meta?light=1` 폴링은 쓰지 않는다). `GET /api/people` 은 이것과 핀의 작성자·행위자·스레드 글쓴이를 합친다.
- **풀기**: 서버가 글에서 `@이름` 을 로그인으로 푼다 — 이름 전체, 로그인, 로그인의 `@` 앞, 겹치지 않는 이름 첫 단어. 대소문자는 가리지 않고 한글 조사(`@서준님`)는 붙어도 된다. `@` 앞이 글자면(메일 주소) 태그가 아니고, 영문 이름 뒤에 영문이 이어지면(`@Alicex`) 다른 말이다. 뷰어가 고른 로그인은 본문 `mentions`(≤10개)로 오지만 첫 단어가 여럿과 겹칠 때 가르는 힌트일 뿐이다. 글은 `@이름` 그대로 두고 풀린 로그인은 핀(메모) `mentions`·메시지 `mentions` 에 둔다.
- **사람을 부른 핀**: 계산 필드 `addressed` = 메모의 `mentions` + 지금 차례(마지막 닫기 뒤) 스레드 글의 `mentions`. pins.md 번호 칸의 `→ @이름` 이 이것이다.
- **이벤트**(`<state_dir>/events.jsonl`, 한 줄 한 건, 추가 전용): `{seq, type, pin, doc, to:[login], by:{login,name}, at, ts, kind_req?, msg?, excerpt?}`.

  | `type` | 언제 | `to` |
  | --- | --- | --- |
  | `mention` | 메모(저장·수정)·답글·다시 연 이유가 새로 누군가를 부름 | 새로 불린 사람 |
  | `review_requested` | 핀이 검토 대기로 감 | 작성자 |
  | `replied` | 답글 | 작성자 + 이 핀에서 불린 적 있는 사람(이 글로 새로 불린 사람은 `mention` 하나만) |
  | `reopened` | 닫힌 핀을 다시 엶 | 작성자 |

  `to` 에서 행위자 자신과 `local` 은 빠지고, 비면 적지 않는다. 핀 쓰기가 커밋된 뒤 잠금 아래에서 파일 전체를 원자적으로 바꿔 쓴다(앞부분은 그대로 — 추가 전용). 최근 5000건만 남기되 `seq` 는 계속 오른다 — 소비자는 바이트 위치가 아니라 `seq` 로 따라온다.

## 브라우저 알림 커서 (`/api/meta?ev=<seq>`)

`/api/meta`(라이트 포함)는 늘 `ev_seq`(`events.jsonl` 의 마지막 `seq`)를 싣는다. `ev=<마지막으로 본 seq>` 를 붙이면 그 뒤 이벤트 가운데 `mention`·`review_requested`·`replied`·`reopened` 이고 `to` 에 **지금 요청자**(테일넷 로그인)가 들었으며 행위자가 자기 자신이 아닌 것만 최대 20건을 `events` 로 싣는다(항목에 `doc_name` 을 더한다). 로컬/에이전트 요청은 늘 빈 목록, 정수가 아니면 `400`. 읽기만 한다 — 라이트 폴링의 쓰기 없음 계약 그대로다. 뷰어 쪽 규칙은 [design.md](design.md) §브라우저 알림.

## 원격 에이전트 진입점 (`GET /pins.md`)

공저자의 에이전트는 서버 머신에 로그인하지 않는다 — 테일넷 주소로만 닿는다. `GET /pins.md` 는 디스크의 `<state_dir>/pins.md` 를 파일로 열 필요 없이, 지금 요청이 도착한 `Host` 에 맞춘 안내 줄로 같은 내용을 HTTP 로 낸다.

```bash
curl -s https://<기기>.<tailnet>.ts.net:<port>/pins.md
```

- `GET /api/pins` 와 같은 sync 경로(`snapshot_pins()`)를 탄 뒤 렌더한다 — 줄 번호가 최신이다.
- close 예시의 base URL만 바뀐다: `Host` 가 `*.ts.net` 이면 `https://<Host 그대로, 포트 포함>`, 아니면(루프백) 지금까지의 `http://127.0.0.1:<port>`. 원격일 때는 안내 문단에 `원격: curl -s <base>/pins.md` 한 줄이 더 붙는다(디스크 파일 자체를 읽고 있는 루프백에는 없다 — 이미 그 파일이다).
- 디스크의 `<state_dir>/pins.md` 는 이 요청과 무관하게 항상 루프백 base 로 쓴다 — 다른 세션이 그 파일을 직접 읽어도 안내가 바뀌지 않는다.
- Host/Origin 검사는 다른 `GET` 과 같다([operations.md](operations.md) §Host·Origin 검사) — 낯선 Host 는 `403`.

## 처리 중 표시 (`/api/pins/{id}/claim`, `/api/pins/{id}/unclaim`)

두 에이전트(작성자 쪽·공저자 쪽)가 같은 핀을 동시에 고칠 수 있다. `claim` 은 **잠금이 아니라 TTL 있는 낙관적 표시**다 — 다른 사람이 그 핀을 닫거나 강제로 다시 잡는 것을 막지 않는다. 협업은 claim 먼저·`처리 중(…)` 건너뛰기 관례에 기댄다(SKILL.md 핀 처리 절차). **claim 은 고치기 직전에 그 핀만 건다** — 한꺼번에 잡으면 손대지 않은 핀까지 잠긴다(실측 2026-09-23: 23건을 `ttl_min` 480 으로 한꺼번에 잡았고, 뷰어의 `~04:02` 가 예상 완료처럼 읽혔다).

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/claim -H 'Content-Type: application/json' -d '{"eta_min": 15}'
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/unclaim
```

- 선택 본문 두 칸. 정수가 아니거나 1 보다 작으면 `400` 이고 아무것도 바뀌지 않는다. **상한을 넘는 값은 거부하지 않고 상한으로 깎는다**(`ttl_min` 480 → 120, `eta_min` 300 → 240) — 옛 절차대로 `ttl_min` 480 으로 잡아 둔 에이전트가 같은 값으로 연장하다 `400` 을 받아 작업이 깨지지 않게 하려는 하위 호환이다. 응답의 `ttl_min_applied`(늘)·`eta_min_applied`(`eta_min` 을 보냈을 때)가 실제로 적용한 값이다.

  | 칸 | 범위 | 뜻 |
  | --- | --- | --- |
  | `eta_min` | 1..240 | **처리 예상 시간(견적)**. 레코드에 `eta_ts = 지금 + eta_min×60`(epoch 초)으로 저장한다. 견적 기준은 SKILL.md 핀 처리 4단계 |
  | `ttl_min` | 1..120 | **잠금 자동 해제**까지의 시간(안전장치). 생략하면 `eta_min` 이 있을 때 `min(120, max(30, eta_min×2))`, 없으면 120. 상한은 480 에서 120 으로 낮췄다 — 멈춘 에이전트가 한나절 핀을 쥐지 않게 |

- 신원은 작성자 귀속과 같은 방식(`Tailscale-User-Login` 또는 헤더 없으면 `로컬/에이전트`)으로 정한다. **같은 신원이 다시 걸면 연장**이다 — `claim_until` 을 지금부터 다시 재고, `eta_min` 을 주면 `eta_ts` 도 지금부터 새 견적으로 바꾼다(안 주면 앞 견적을 둔다). 시작 시각(`claimed_at`·`claim_ts`)은 그대로, `rev`+1. **다른 신원이 유효한(만료 안 된) claim 을 쥐고 있으면 `409`** — `{"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}`. 새로 잡으면(만료된 남의 claim 포함) 옛 `eta_ts` 는 지운다.
- `claim_until`·`claim_ts`·`eta_ts` 는 epoch 초다 — 브라우저 시간대와 무관하게 비교한다(build-sync §위치 추정과 같은 이유). 이름이 `*_at` 이 아닌 것은 일부러다: 레코드 검증(`valid_rec`)은 `*_at` 을 문자열 시각으로 보므로, 숫자 `*_at` 을 쓰면 이 필드를 모르는 옛 서버가 그 레코드를 깨진 줄로 버린다. 만료된 claim 은 모든 표시(`<state_dir>/pins.md`·뷰어 카드·충돌 판정)에서 없는 것으로 본다. 저장값 자체는 다음 쓰기 때 정리될 뿐이다.
- `claim_ts` 가 없는 옛 claim 은 `GET /api/pins` 가 `claimed_at`(서버 현지 시각 문자열)을 epoch 로 풀어 계산 필드 `claim_ts` 로 싣는다(저장하지 않는다).
- 닫힌 핀에 `claim` 을 걸면 `409 {"error":"done","pin":...}`. 없는 id 는 기존 관례대로 `200 {"ok": false}`.
- `unclaim` 은 요청자 신원과 무관하게 지운다 — 이 스킬의 신뢰 모델은 테일넷 구성원을 막지 않고 귀속만 기록하므로([design.md](design.md) §작성자 귀속), 처리 중 표시도 권한 검사 없이 풀 수 있다.
- `close`·`drop` 은 claim 필드를 함께 지운다 — 닫힌·삭제된 핀에 처리 중 표시가 남지 않는다. 다른 사람이 claim 한 핀을 닫는 것 자체는 막지 않는다. 그래서 에이전트는 처리를 포기하거나 사용자에게 넘길 때만 `unclaim` 을 부른다.
- `<state_dir>/pins.md` 번호 칸에 유효한 claim 이 있으면 `처리 중(<이름>, 약 15분)` 이 붙는다 — 남은 견적을 5분 단위로 올린 값, 넘겼으면 `예상 초과`, 견적 없이 잡았으면 `처리 중(<이름>)`(§pins.md 형식).
- 뷰어 카드는 머리에 호박색 점을 두고 배지를 이렇게 보인다. 분과 시각은 모두 5분 단위로 올린다(견적은 대략이다). 시각은 보는 기기의 현지 시각이고, 30초마다 다시 센다.

  | 상태 | 배지 |
  | --- | --- |
  | 견적 안 | `처리 중 · 약 15분 · 20:40쯤` |
  | 견적 초과 | `예상보다 늦어짐 (+5분)`(초과 분) |
  | 견적 없는 claim | `처리 중 · 20:02부터 (23분째)` |

  잠금 자동 해제 시각(`claim_until`)은 배지에 쓰지 않고 설명(툴팁)에만 둔다 — 예상 완료로 읽혔다. [풀기] 버튼(unclaim)이 함께 뜬다 — **뷰어에는 claim 을 거는 버튼이 없다**(에이전트 전용 동작이다).

## 겹친 핀과 덧붙이기 (자동 병합 없음)

같은 파일의 열린 핀 두 개가 겹치면(한쪽이 다른 쪽 범위 안에 들거나 일부만 겹치면) `GET /api/pins`·`POST /api/pick` 응답에 계산 필드 `rel`/`overlaps` 가 붙는다 — **저장하지 않는다**, 요청마다 다시 계산한다.

- `rel: [{"id", "rel": "inside"|"contains"|"partial"}]` — 그 핀을 기준으로 다른 핀과의 관계(저장된 핀끼리). 범위가 완전히 같으면 id 가 작은 쪽을 `contains`(바깥)로 본다.
- `overlaps`(pick·`/api/overlaps` 응답): `[{"id","lo","hi","rel": "equal"|"inside"|"contains"|"partial"}]` — 저장 전 선택 기준의 관계(`selection_rel`). `equal` = 범위가 같음(같은 문단·환경을 다시 찍는 가장 흔한 중복), `inside` = 선택이 핀 안, `contains` = 선택이 핀을 감쌈, `partial` = 걸침.
- **범위가 바뀔 때마다 다시 센다.** 뷰어는 드래그·단계 전환·한 줄 버튼 때마다 이 탭의 열린 핀 목록으로 같은 규칙(`overlapsFor`/`selRel`, 회귀 테스트가 서버 구현과 대조)을 돌린다. pick 순간에만 세면 [문단] 단계로 바꿔 기존 핀과 똑같은 범위를 만들어도 배너가 안 떠 중복 핀이 저장됐다(실측). 서버가 본 겹친 핀이 이 탭 목록에 없으면(다른 사람이 방금 저장) 목록을 다시 받는다.
- 네 관계 모두 배너 대상이다. 대표 하나를 고른다: 같은 범위 > 안(가장 좁은 바깥 핀) > 감쌈(가장 넓은 안쪽 핀) > 걸침(id 가 가장 작은 것). 문구로 관계를 밝힌다 — `열린 핀 #4와 같은 범위입니다 (L405-L406)` / `… #4 범위 안입니다` / `… #4를 감쌉니다` / `… #4와 일부 겹칩니다`, 그리고 `[#4 메모에 덧붙이기] [별도 핀으로 저장]`.
- 뷰어는 자동으로 합치지 않는다. "덧붙이기"는 `note_append` 로 기존 핀에 붙이고 지금 선택은 새 핀으로 만들지 않는다. [별도 핀으로 저장]은 **그 핀과의 그 관계**만 끈다 — 범위를 바꿔 관계가 달라지면 다시 알리고, 다음 드래그에서는 초기화한다.
- `<state_dir>/pins.md` 번호 칸의 `#N 범위 안`·`#N과 같은 범위`(N 과 한 번에 고치고 둘 다 닫는다)·`#N과 일부 겹침`(참고만)이 이 계산의 대표값이다(§pins.md 형식). 뷰어 카드 배지도 같은 말·같은 규칙이다.
- 뷰어 작성 패널의 겹침 배너 문구: `열린 핀 #4와 같은 범위입니다` / `… #4 범위 안입니다` / `… #4를 감쌉니다` / `… #4와 일부 겹칩니다`(조사는 숫자 읽기로 가린다).

## 보기 전용 PDF 문서의 pick·핀

`kind:"pdf"` 문서는 SyncTeX 이 없다. `POST /api/pick`(`doc` 이 보기 전용)은 좌표를 받아 `{doc, kind:"region", view_only:true, page, frac, pdf, name, quote, n_chars, warn, overlaps:[], pdf_build}` 를 돌려준다 — `quote` 는 영역 글자(pdftotext, 공백 정규화, 160자), `frac` 을 안 보냈으면 좌표로 만든다. 줄 범위(`lo`·`hi`·`levels`)는 없다.

`POST /api/pin` 은 `{doc, page, frac, note?, quote?, pdf_build?}` 를 받는다. `frac` 은 필수이고 LaTeX 핀보다 엄하다(숫자 4개, 쪽 안 0..1, 넓이 > 0). `page` 는 1..쪽 수. `file`·`lo`·`hi`·`scope` 를 보내면 `400`. 저장 레코드는 `{id, doc, pdf:<절대경로>, name, kind:"region", page, frac, quote?, note, at, author, rev, pdf_build}` — `file`·`lo`·`hi`·`anchor` 가 없다. `/edit` 은 메모(`note`·`note_append`)와 영역 다시 잡기(`loc:{page, frac, quote?}`)만 받고 `lo`/`hi`/`scope`/`kind` 는 `400`. 닫기·claim·drop 은 LaTeX 핀과 같다. 보기 전용 문서의 `POST /api/rebuild` 는 `400`(재빌드가 없다 — 파일이 바뀌면 쪽을 저절로 다시 그린다, build-sync §보기 전용 PDF), `/api/snippet` 도 `400`.

## 핀 레코드 스키마 (`pins.jsonl`, 한 줄 = 한 레코드)

```json
{"id": 3, "at": "2026-09-21 20:10:00", "page": 4, "file": "<절대경로>/introduction.tex",
 "lo": 120, "hi": 134, "raw_lo": 122, "raw_hi": 131, "kind": "env:minipage", "scope": "env",
 "via": "synctex", "score": 0.93, "note": "이 문단 톤을 낮춰줘", "frac": [0.12, 0.30, 0.55, 0.18],
 "pdf_build": "pages-20260921200500",
 "anchor": {"head": "이 절에서는 소스 재선정 주기를...", "tail": "...효과가 관측된다."},
 "synced_at": 1758450000.0, "sync": "moved +3", "rev": 2, "done": false,
 "author": {"login": "bob@example.com", "name": "Bob Park", "pic": "https://..."},
 "edited_at": "2026-09-21 21:00:00", "edited_by": {"login": "local", "name": "로컬/에이전트"}}
```

새 필드는 모두 선택이다 — 없는 옛 레코드도 그대로 읽힌다.

| 필드 | 뜻 |
| --- | --- |
| `doc` | 핀이 속한 문서 키(§문서 매개변수). 없는 옛 레코드는 첫 문서로 **읽는다** — 이관 쓰기를 하지 않는다. `GET /api/pins` 응답에는 늘 채워진다(계산) |
| `pdf` | 보기 전용 PDF 문서의 핀만 — 그 PDF 의 절대경로. 이 필드가 있고 `file` 이 없으면 보기 전용 핀으로 검증한다(`page`·`frac` 필수, `lo`/`hi` 없음). 문서 키가 지금 설정에 없어도 깨진 줄로 치지 않는다 |
| `rev` | 레코드 내용이 바뀌는 모든 쓰기(줄 이동·stale, 수정, 닫기, 다시 열기, 되살리기)에서 +1. 없으면 0 |
| `scope` | `raw\|para\|env\|env2\|env3\|lines` — 저장할 때 고른 사다리 단계 |
| `quote` | 선택 — 호출자가 붙인 짧은 인용(60자에서 자른다) |
| `pdf_build` | `frac` 을 찍은 빌드 id(쪽 디렉토리 이름). 없으면 옛 핀 — 옛 필드명 `frac_build` 도 같은 뜻으로 읽는다(build-sync §위치 추정) |
| `anchor` | `{head, tail, head_off, tail_off}` — 줄 맞춤 기준. `*_off` 가 없는 옛 앵커는 0 으로 본다([design.md](design.md) §줄 번호 재동기화) |
| `kind` | `paragraph\|float\|block\|none`(옛 값) 또는 `env:<이름>`, `lines`. 모르는 값은 원문 그대로 둔다 |
| `author` | 만든 사람 `{login, name, pic?}` |
| `edited_at`, `edited_by` | 저장 뒤 마지막 수정 시각·사람 |
| `closed_by` / `reopened_by` | 닫은·다시 연 사람(`done_at`·`reopened_at` 과 함께) |
| `close_reply` / `close_ref` | 닫을 때 남긴 선택 사유 — 무엇을 고쳤는지(≤500자)·참조(PR 번호 등, ≤80자). 첫 닫기에만 적히고, 이미 닫힌 핀을 다시 닫아도 바뀌지 않는다(§닫을 때 사유 남기기). `reopen` 이 지운다 |
| `dropped_by` / `restored_by` | 삭제 기록(`pins.dropped.jsonl`)의 삭제자, 되살린 레코드의 복원자 |
| `kind_req` | `fix`\|`question` — 핀 종류(§스레드). 없으면 fix |
| `thread` | 답글과 상태 전환 기록 `[{id, by, at, text, mentions?, ev?, ref?}]`(§스레드) |
| `mentions` | 메모가 부른 사람의 로그인 목록(§@태그·사람·이벤트) |
| `review` | `true` = 검토 대기(`done:true` 와 함께만 뜻이 있다, §검토 대기) |
| `confirmed_by` / `confirmed_at` | 검토 대기를 확인한 사람·시각 |
| `claimed_by` / `claimed_at` / `claim_ts` / `claim_until` / `eta_ts` | 처리 중 표시(§처리 중 표시) — `claimed_by`는 작성자 귀속과 같은 `{login,name}` 형식, `claimed_at`은 시작 시각 문자열, `claim_ts`(시작)·`claim_until`(잠금 자동 해제)·`eta_ts`(예상 완료)는 epoch 초. `claim_until`이 지난 값이면 없는 것으로 본다. `close`·`drop`·`unclaim`이 모두 지운다 |

`snippet`, `warn`, `levels`, `default_level`, `rel`, `overlaps`, `est`, `state`, `addressed` 는 응답에만 있고 저장하지 않는다(§겹친 핀·build-sync §위치 추정).

## pins.md 형식

`<state_dir>/pins.md` 는 5열 표다: `| # | 쪽 | 위치 | 범위 | 메모 |`(옛 `종류` 열이 `범위` 로 바뀌었다. `작성` 열은 v2 에서 없앴다 — 작성자는 `GET /api/pins`·뷰어 카드에서만 본다. 닫힌 핀도 마찬가지다). 스니펫은 일부러 넣지 않는다 — 줄 범위만 있으면 에이전트가 원본을 `Read`로 직접 읽는 편이 항상 더 싸고 정확하다(스니펫은 그 시점의 스냅샷이라 원본과 어긋날 수 있다).

- **머리줄**: `원고: <경로>` 바로 다음 줄이 `논문: <이름표> · 저장소: <git origin URL 또는 (없음)>` 다(operations.md §여러 논문 뷰어를 동시에 띄울 때) — 여러 인스턴스를 동시에 열었을 때 다른 논문의 핀을 처리하지 않도록, `저장소` 값이 있으면 안내 문단에 `처리 전 자기 체크아웃의 git remote get-url origin 이 위 저장소와 같은지 확인. 다르면 다른 논문의 핀이니 멈춘다` 가 덧붙는다. 그다음 `head.txt`·`built_at.txt` 가 둘 다 있으면 `기준: <head 짧은 해시> · 빌드 <built_at>` 과 `다른 체크아웃에서 처리하면 먼저 git rev-parse --short HEAD 가 같은지 확인` 두 줄이 온다. 없으면(git 저장소가 아니거나 아직 안 빌드) 그 두 줄만 생략한다.
- **위치**: `--manuscript`(`C.src`) 기준 **상대경로**다. 루트 파일은 basename 과 같아서 단일 파일 원고의 행은 예전과 같다. `\input`/`\include` 로 쪼개진 하위 파일은 `sections/intro.tex L12-L18` 처럼 구분된다. 파일명에 `|` 가 있으면 `\|` 로 이스케이프한다(아래 이스케이프 규칙).
- **범위**: `scope` 가 있으면 `env*`→`env:<이름>`, `para`→`paragraph`, `raw`/`lines`→`lines`, 없으면 옛 `kind` 값을 그대로 쓴다.
- **줄 번호 시점**: `<state_dir>/pins.md` 갱신 시각 기준이다. 앞선 핀을 고쳐 줄이 밀렸을 수 있으면 `GET /api/pins` 로 다시 맞춘 값을 받는다.
- **번호 칸의 표시** — 번호 뒤에 ` · ` 로 이어 쓴다(예: `7 · #6 범위 안 · 처리 중(에이전트 B, 약 10분) · 수정됨`). 예전 기호(`⊂#N` `∩#N` `⏳` `✎` `⚠`)는 뜻이 드러나지 않아 짧은 말로 바꿨다. 겹침 표시는 핀당 하나다(같은 범위 > 범위 안 > 일부 겹침):
  - `#N과 같은 범위` — 열린 핀 `#N` 과 줄 범위가 똑같다(같은 곳을 두 번 찍음, 그런 상대가 여럿이면 id 가 가장 작은 것). 두 핀 모두에 붙는다. 한 번에 고치고 둘 다 닫는다.
  - `#N 범위 안` — 이 핀이 열린 핀 `#N` 범위 **안**에 통째로 든다(범위가 가장 작은 바깥 핀 하나만 표시 — 뷰어 카드의 태그도 같은 규칙이라 이 파일과 화면 표기가 어긋나지 않는다). **`#N` 과 한 번에 고치고 둘 다 닫는 것을 권한다** — 따로 고치면 같은 문단을 두 번 손대거나 `#N` 의 제약을 놓칠 수 있다.
  - `#N과 일부 겹침` — 일부만 겹친다(위 둘이 없을 때만, id 가 가장 작은 상대). 참고만 하고 각자 처리해도 된다. 조사(`과`/`와`)는 숫자 읽기의 끝소리로 가린다(`#20과`, `#2와`).
  - `처리 중(<이름>, 약 N분)` — 다른 에이전트가 유효한 claim 을 쥐고 있다(§처리 중 표시). 이름은 `claimed_by.name`, 헤더 없는 요청이면 `로컬/에이전트`다. `약 N분` 은 남은 견적(5분 단위 올림), 넘겼으면 `예상 초과`, 견적이 없으면 이름만. **이 핀은 건너뛴다** — 처리 중인 사람과 겹치지 않도록.
  - `수정됨` — 저장한 뒤 메모·범위를 수정했다(`edited_at` 있음).
  - `위치 잃음` — 위치를 잃었다(`stale`). **네가 방금 그 범위를 고친 직후라면** 이미 반영됐을 수 있으니 원문을 확인하고 닫아도 된다 — 무조건 사용자에게 보고할 필요는 없다(방금 자기가 만든 변경이 원인일 때에 한한다).
  - 표시 범례 줄(`표시: '#N 범위 안'·'#N과 같은 범위' = … · '#N과 일부 겹침' = … · '처리 중(이름, 약 N분)' = … · '수정됨' = … · '위치 잃음' = … · «…» = …`)은 열린 핀에 표시가 하나라도 있을 때만 실린다.
- **`«…»` 인용**: 메모 앞에 최대 60자 인용이 붙는 조건부 예외다 — 핀 범위가 **한 줄**이고, 그 줄이 **600자를 넘고**(문단 하나가 줄바꿈 없이 이어지는 원고에서 줄 번호만으로는 지목한 부분을 못 찾는다), `scope` 가 `raw`/`para`/없음일 때만 붙는다. 60자를 넘어 잘렸으면 인용 끝에 `…` 를 붙인다(예: `«문장의 앞부분까지만…»`) — 잘린 인용을 완결된 문장으로 오인하지 않도록. 이 인용은 **`pdftotext` 로 렌더된 글자**다 — 검색 힌트이지 `Edit` 의 `old_string` 으로 그대로 쓸 문자열이 아니다(리거처·하이픈·공백이 원문 LaTeX 소스와 다를 수 있다). 줄 범위로 파일을 `Read` 한 뒤 그 인용을 검색해 정확한 위치를 확인한다.
- **메모 앞 `@작성자:`**: 열린 핀의 작성자가 2명 이상이면(`author.login` 기준, 작성자 없는 옛 핀은 한 부류) 메모 앞에 `@<author.name>: ` 이 붙는다. 작성자가 1명뿐이면 토큰을 아끼려고 붙이지 않는다 — 결과 보고나 `close` 의 `reply` 를 쓸 때 누구 핀인지 참고하는 용도다([design.md](design.md) §작성자 귀속). 배정 기준이 아니다.
- **질문·다시 열림·사람을 부른 핀**: 번호 칸에 `질문`, `다시 열림`(지금 차례가 다시 열기로 시작), `→ @이름`(§@태그·사람·이벤트 — 에이전트는 사용자가 시키지 않으면 건너뛴다)이 붙는다. 메모 칸 뒤에는 지금 차례의 스레드가 `[스레드 N건] 이름: … ⏎ 다시 연 이유(이름): …` 로 붙는다(뒤 3건, 한 건 200자 — 나머지는 `GET /api/pins/{id}`). 사람을 부른 핀이 있으면 안내 문단에 건너뛰기 규칙이 붙는다.
- **검토 대기**: 열린 표에서 빠지고 맨 아래 `## 검토 대기 N건 — …처리하지 않는다` 소절의 4열 표 `| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |` 에 실린다(여러 문서면 위치 앞에 문서 키). 있을 때만 머리줄에 `검토 대기 N건(맨 아래, 처리하지 않는다)` 이 끼고, 없으면 머리줄은 예전 모양 그대로다.
- **닫힌 핀**: 표에서 빠지고 머리줄에 건수로만 남는다(`닫힌 핀 N건(뷰어의 '닫힌 핀'에서 확인)`). 쌓여도 `<state_dir>/pins.md` 크기가 늘지 않는다 — `<details>` 로 펼쳐야 했던 예전 방식은 없앴다.
- **여러 문서**(`--doc` 이 둘 이상이거나, 첫 문서가 아닌 키의 열린 핀이 있을 때): 한 장 그대로 두고 머리에 `문서: 본문(\`ms\`) 3건 · … · 리뷰어 코멘트(\`rv\`, 보기 전용) 1건` 한 줄과 소절 안내를 둔 뒤, 열린 핀이 있는 문서마다 소절 `## <이름> · \`<키>\` · \`<--manuscript 기준 경로>\``(보기 전용이면 `— 보기 전용 PDF(줄 번호 없음)`)과 그 문서의 `기준: <head> · 빌드 <built_at>`(보기 전용은 `그림`), 5열 표가 온다. 머리의 단일 `기준:` 줄은 소절로 옮겨 간다. 설정에 없는 문서 키의 핀은 `## 설정에 없는 문서 · \`<키>\`` 소절로 드러난다. 단일 문서는 예전 모양 그대로다.
- **보기 전용 핀의 행**: 위치 칸 `쪽 3, 영역 가로 10–60% 세로 20–30%`, 범위 칸 `영역`, 메모 앞에 영역 글자 `«…»`(한 줄·600자 조건 없이 늘 — 줄 번호가 없어 유일한 원문 단서다). 보기 전용 핀이 있으면 안내 문단에 "줄 번호가 없다 — 쪽·영역 글자·메모로 판단, 고칠 곳은 LaTeX 문서에서" 가 붙는다.
- **이스케이프는 모든 칸에 같다**(`md_cell`): `|` 는 `\|`, 줄바꿈은 메모 칸에서 `⏎`, 나머지 칸(번호·쪽·위치·범위·인용)에서 공백. 범위 칸의 env 분기가 빠져 kind `env:x|y` 가 8열 행을 만든 적이 있어(독립 검증 실측) 칸마다 따로 처리하지 않고 한 함수로 모았다.
