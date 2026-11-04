# HTML 문서 화면 — Markdown 등 줄 단위 원문 (보류 제안, 개정 1)

> **상태: 보류. 승인되지 않았고 구현하지 않는다.**
>
> - 2026-10-24: 소유자가 지금은 LaTeX만 유지하기로 했다("일단은 tex 만 하자"). 이 계획을 구체적으로 적어 공동 관리자 검토에 넘기라고 했다([이슈 #255](https://github.com/dartworklabs/limn/issues/255)). 검토 의견은 아직 없다.
> - 2026-11-04 개정 1: 초판은 0.4.23 무렵에 썼다. 그 뒤 들어온 제안 수정·판정 핀·댓글 타임라인 등을 반영해 당시 `main`(0.4.45, b13aa8c0)과 다시 대조했다. 일곱 결정에 추천안을 달고, 소유자가 방향을 만져 볼 수 있는 버리는 PoC(`poc/html-surface` 브랜치)를 만들었다. 결정 초안은 [ADR-0025](../../adr/0025-html-document-surface.md)(`제안`)다.
> - 2026-11-04 개정 1 검토 반영: 1차 검토의 일곱 지적을 코드와 대조해 고쳤다. 블록 안 줄 대응 규칙(§결정 6), `page` 없는 핀을 만드는 길과 고치는 길(§결정 1), 변경 보기의 이력 파일(§새로 지나야 하는 길), 번들 의존성 고지(§결정 4), 읽기·파싱·그리기 한도(§결정 5), 판정 핀의 결함 위치, 링크 허용 목록(§결정 5)이다.
> - 2026-11-04 개정 1 2차 검토 반영: 끝에 점을 붙인 호스트(`localhost.`, 뷰어 호스트 뒤의 `.`)가 링크 관문을 지나던 결함을 고치고, 호스트를 한 철자로 비교하는 규칙과 서버 Host 검사에 대한 권고를 적었다(§결정 5). 번들의 `@oxc-project/runtime` 도우미 밑에 있는 Babel 고지를 더했다(§결정 4). 원문 줄 보기의 줄 한도는 따로 알린다(§결정 5). `main` 0.4.46과 다시 대조했고, 한글 조합을 끝내는 키 규칙을 Markdown 화면에도 건다(§새로 지나야 하는 길).
> - 구현은 다음 세 가지가 모두 끝나야 시작한다. 소유자가 이 문서의 다음 개정을 명시적으로 승인한다([workflow.md](../../handbook/workflow.md) §기본 경로). ADR-0025를 `승인됨`으로 올린다. 뷰어 변경을 `main`에 넣기 전에 네 기기군 PoC를 보인다.

## 문제

Limn은 LaTeX에만 줄 핀을 준다. 보기 전용 PDF에는 쪽과 영역 핀만 있고, 그림 문서는 요소 지도로 코드 줄을 가리킨다. 그런데 사람과 에이전트가 함께 고치는 작업 문서(설계 백본, 노트, 계획, 답변 초안)는 Markdown인 경우가 많다.

지금은 두 길밖에 없다. 하나는 Markdown을 줄 1:1로 LaTeX로 바꾼 생성 파일을 커밋하고 그 `.tex` 를 탭으로 띄우는 것이다. 한 논문 저장소가 원고 백본에 이렇게 하고 있다. 이 길에는 불편이 셋 있다. 생성 파일을 원본과 계속 맞춰야 하고, 제안 수정의 편집 칸에 LaTeX로 이스케이프된 글이 보이며, 휴대폰에서는 A4 쪽을 확대해 읽어야 한다. 다른 하나는 보기 전용 PDF로 띄우는 것인데, 이 길에는 줄 번호가 없다.

## 진단: Limn 안에서 Markdown을 LaTeX로 바꾸는 방식은 피한다

빌드할 때 변환하면 PDF 기계(쪽, `frac` 표시, 확대, 찾기, 쪽 목록, 비교 PDF)를 그대로 쓰므로 뷰어 작업이 가장 적다. 그러나 비용이 크다. 개정 1에서 현재 코드로 다시 확인했다.

| 비용 | 근거 (`main` b13aa8c0) |
| --- | --- |
| Markdown 하나를 띄우는 데 TeX와 한글 글꼴이 필요하다 | latexmk 경로(`builds/engine.py`). 변환기 프리앰블이 `kotex` 등을 요구해 외부 도구 멈춤 신호에 걸린다([architecture.md](../../handbook/architecture.md) §멈춤 신호) |
| Markdown만 고치면 화면이 조용히 옛 쪽에 머문다 | 변경 감지·`stale_build`·지문이 `SRC_TEX_EXTS`(`builds/artifacts.py:64`)를 따르는데 `.md` 가 없다 |
| 흐르는 형식인데 종이 쪽으로 보인다 | 휴대폰에서 확대해야 읽힌다 |
| 변환기를 손으로 만들어야 한다 | 코드 블록·수식 블록·그림·각주·HTML을 다루지 못하고, 수식 안의 `%`·`&` 가 표 행을 깨뜨린다 |
| 형식마다 변환기가 또 필요하다 | 확장 단위가 "그 형식 → LaTeX" 변환기가 된다 |

이렇게 돌아가는 까닭은 뷰어가 PDF밖에 그리지 못하기 때문이다. 이 제안은 그 한계를 우회하지 않고 없앤다.

## 제안: 화면을 둘로 나눈다

문서는 **무엇으로 그리는가**와 **고른 자리를 원문으로 어떻게 되짚는가**로 정해진다.

| 화면 | 그리는 법 | 되짚는 법 | 종류 |
| --- | --- | --- | --- |
| **PDF 화면** (지금 그대로, 주력) | LaTeX → PDF | SyncTeX | `tex` |
| | PDF 그대로 | 없음(쪽과 영역) | `pdf` (보기 전용) |
| | 그림 PDF + 요소 지도 | 요소 지도 | `figure` |
| **HTML 화면** (새로) | 브라우저가 원문에서 바로 그린다 | 그린 블록마다 원문 줄 범위를 붙여 둔다 | `markdown`(`.md`) 먼저. 일반 텍스트와 코드는 나중 |

HTML 화면에는 변환도, 빌드도, 생성 파일도 없다. 그린 블록이 곧 원문 줄이므로, 고른 글이 `lo..hi` 로 바로 바뀐다. LaTeX 문서와 PDF 화면 위의 모든 것은 그대로 둔다.

### 1단계 범위

- **등록.** 확장자 `.md` 로 `markdown` 종류를 받는다(`--doc KEY=NAME:path.md`, `limn doc add`). 빌드하지 않는다.
- **읽기 화면.** 네 기기군에서 흐르는 글로 보인다. 목차는 제목에서 만든다. 찾기는 브라우저의 찾기(Ctrl/⌘+F)를 쓰고, Limn 찾기 칸은 숨긴다(§결정 7).
- **줄 핀.** 고르는 방법은 셋이다. 마우스로 글을 끌거나, 블록을 누르거나, 휴대폰에서 길게 눌러 손잡이로 고른다. 고른 결과는 `file`·`lo`·`hi`·`quote` 다. 핀 표시는 그린 줄 위에 한다. 작성 패널·카드·편집 카드·겹침 규칙·줄 맞춤(anchor)은 `.md` 파일에서 그대로 돈다.
- **범위 사다리.** 고른 줄 → 블록(문단·목록 항목·표·코드 블록·인용·HTML 블록) → 절(제목부터 같은 단계 이상의 다음 제목 전까지)이다. LaTeX 환경 단계는 없다.
- **제안 수정.** Markdown 줄 핀에도 둔다. 편집 칸에는 Markdown 원문이 보인다. [ADR-0020](../../adr/0020-suggested-edit-pins.md) D1의 "LaTeX 문서의 줄 핀에만" 을 부분 대체한다.
- **판정 핀.** Markdown 줄 핀의 판정 대상은 그 줄이다. 쪽 전체 판정과 쪽 판정 줄은 없다.
- **변경 보기.** `.md` 파일의 소스 diff와 핀 단위 hunk만 낸다. 그린 화면끼리의 비교는 없다.

1단계에서 다루지 않는 것은 다음과 같다. 그린 화면끼리의 전후 비교, 일반 텍스트와 코드 종류, 그림 불러오기, 원시 HTML 그리기, CommonMark와 GFM 표·취소선 밖의 확장(수식, 각주, 머리 정보), 다른 Markdown 문서로 가는 상대 링크.

## 현재 코드 대조 (개정 1)

초판 뒤 `main` 에 354개 커밋이 들어왔다(0.4.23 → 0.4.45). 아래 근거는 모두 `main` b13aa8c0(0.4.45)의 `src/limn/` 기준 경로와 줄이다. 지금 `main` 은 0.4.46(0befcdea)이다. 0.4.46은 뷰어의 한글 조합 키만 바꿨다(#388, `fix/ime-composition-tail-keys`: `core.js` 의 `imeKey`·`imeTail`·`imeHeldIn`, 판정 이유 칸의 미루기). 아래에서 인용한 줄은 0.4.46에서도 같다(`core.js` 에는 `:64` 뒤에 91줄이 들어왔고, `verdict.js` 는 `:196` 부터 바뀌었다). 0.4.46도 Markdown 문서 등록을 거절한다(`administration/serve_documents.py:265`).

### 그대로 맞는 것

- 문서의 행동은 능력으로 갈린다. `builds_from_source`·`watches_files`·`takes_line_pins`·`shows_revisions`·`view_only`·`has_element_map`(`runtime/documents.py:298-336`)이 있고, 문서 종류는 확장자로 한 번 정한다(`administration/serve_documents.py:256-266`).
- 제안 수정의 관문은 `builds_from_source`, 곧 "LaTeX인가"로 열린다. 근거는 `pins/editing/rules.py:686-692`의 `check_suggestion(latex)`, `pins/editing/service.py:79`, `pins/editing/http.py:85`, `SuggestFacts.latex`(`rules.py:525-532`)다. 뷰어 쪽은 `suggestOff`(`viewer/js/suggest.js:32`)이고, [api.md](../../handbook/api.md) §받는 핀과 한도에도 "LaTeX 문서(`kind:"tex"`)의 줄 핀만 받는다"고 적혀 있다.
- LaTeX 문서의 변경 보기 pathspec은 메인 폴더의 `tex`·`bib`·`sty`·`cls`·`bst` 뿐이다(`revisions/core.py:424-426`). 그림 문서는 확장자가 아니라 파일 목록으로 이력을 고른다(`:403-408`, `builds/queries.py:273-286`).
- 서버의 줄 번호는 `str.splitlines()` 로 센다(`platform/files.py:207`, `tex_lines` `:286`).
- 서버 런타임은 표준 라이브러리만 쓰고, 번들을 더하는 것은 멈춤 신호다([architecture.md](../../handbook/architecture.md) §불변식 2, §멈춤 신호).

### 낡은 것

| 초판의 서술 | 지금 | 근거 |
| --- | --- | --- |
| "가지는 능력에 묻고 종류에 묻지 않는다" | 판정 핀이 들어오며 종류를 직접 묻는 곳이 생겼다. 새 종류로 조용히 틀리는 곳은 서버의 배치 하나다(§새로 지나야 하는 길의 판정 핀). 나머지는 그림·PDF를 먼저 가려내고 남은 줄 핀을 줄 대상으로 두므로 Markdown에서도 맞다 | 배치 `pins/runtime.py:273-280`(`doc.kind == "tex"`·`"pdf"`). 맞게 도는 곳 `pins/verdict.py:191-207`(`order_target`), 뷰어 `verdict.js:76`·`:92`(`kind!==DOC_KIND.PDF`). 타입 목록 `pins/verdict.py:84`(`TargetKind`) |
| `page`/`frac` 없는 줄 핀을 위해 `pins/model.py`·`pins/record.py` 를 고친다 | 저장과 읽기는 이미 받는다. 막는 곳은 만드는 길과 고치는 길이다 | 레코드 검사는 `page` 가 있을 때만 정수인지 본다(`pins/record.py:92`). 모델도 선택 필드다(`pins/model.py:379`). 반면 만드는 길에서 `parse_loc` 는 `page` 기본값 1을 넣고(`pins/editing/location.py:200`), `to_record` 는 늘 쓰며(`:51`), `new_line_pin` 은 `pdf_build` 를 늘 넣는다(`pins/editing/rules.py:913`). 고치는 길에서 `LinePlace` 는 `page` 를 요구하고(`rules.py:142-154`), 위치를 바꿀 때 `frac` 이 오면 `pdf_build` 를 되살리며(`pins/editing/input.py:254-265`), 이름이 불리지 않은 `page`·`frac` 은 저장된 값을 그대로 둔다(`rules.py:755-759`) |
| `builds/document_facts.py` 를 고친다 | 쪽 사실은 고치지 않는다. Markdown 문서는 쪽 사실을 묻지 않는다. 다만 만드는 길과 고치는 길이 쪽 없는 문서인지 알도록 능력 하나를 싣는다(§결정 1) | 요소 지도가 같은 길로 실린다(`has_element_map`, `builds/document_facts.py:37-40`). PoC는 싣지 않아 `page: 1` 을 저장했다 |
| 원문 서빙과 변경 감시를 위해 `documents/`·`builds/` 에 감시를 더한다 | 감시 스레드가 필요 없다. 빌드하지 않는 문서의 `src_mtime` 은 이미 그 파일 자체의 시각이고, 가벼운 meta 폴링이 그 값을 싣는다 | `builds/artifacts.py:989-991`(`src_mtime`: 빌드하지 않는 문서는 그 파일의 `st_mtime`), `viewer/js/polling.js:45-50`. PoC는 원문이 바뀌면 다시 그린다 |
| pick을 위해 `pins/location/`(`compute_levels`, `resolve.py`)을 고친다 | Markdown의 pick은 뷰어 안에서 끝난다. 서버는 저장할 때 `lo..hi` 만 확인한다(`parse_loc`). 사다리의 블록·절은 파서의 줄 지도에서 나온다 | PoC가 `/api/pick` 없이 저장한다. 에이전트는 pick을 쓰지 않고 `file`·`lo`·`hi` 로 바로 핀을 만든다 |
| `apart_paths` 를 고친다 | 필요 없다. LaTeX 문서의 원천 목록은 `SRC_TEX_EXTS` 만 보므로 `.md` 를 떼어 둘 일이 없다 | `runtime/documents.py:141-174`, `builds/artifacts.py:64` |
| 뷰어는 `pdf-open.js` 등 아홉 파일이 PDF 중심이다 | 쪽을 전제한 코드가 더 늘었다. 쪽 판정 줄·쪽 판정 패널(`verdict.js`·`verdict-reason.js`·`verdict-panel.js`), 비교 PDF 확대(`revision-zoom.js`), 목록의 `쪽순`(`list.js:161-163`)이다. 뷰어 JS는 6,225줄에서 10,839줄(0.4.45), 10,941줄(0.4.46)이 되었다 | `git show v0.4.23`·b13aa8c0·0befcdea 의 `viewer/js` 줄 수 |

### 새로 지나야 하는 길

초판에 없던 길이다. Markdown 화면이 지나가야 한다.

| 길 | 무엇이 걸리나 | 근거 |
| --- | --- | --- |
| 시작할 때의 빌드 | 소스 빌드도 지도도 아닌 문서는 모두 "보기 전용 PDF 렌더"로 떨어진다. `.md` 는 `pdfinfo` 가 실패해 빌드 실패로 표시된다(PoC에서 재현) | `builds/run.py:51-58`(`needs_build`), `builds/service.py:79-86`(`build_step` 의 마지막 가지) |
| 판정 핀 ([ADR-0021](../../adr/0021-verdict-pins.md)–[0023](../../adr/0023-superseded-verdict-field.md)) | **결함(고칠 것).** 서버의 배치가 종류 `tex` 에만 `file` 을 싣는다. `markdown` 은 `file` 없이 넘어가 `order_target` 이 대상을 내지 못하고, `superseded_by` 가 조용히 빠진다. 고칠 곳은 이 배치 하나다. `order_target` 은 그림·PDF가 아닌 줄 핀을 이미 줄 대상으로 놓고, 뷰어의 `verdictTargetOf` 도 `kind!==DOC_KIND.PDF` 가지로 Markdown 줄 핀을 받는다. **정리(동작 그대로).** 종류 비교를 능력으로 바꾸는 일(배치의 `tex`·`pdf`, `TargetKind`, 뷰어의 두 비교)은 결함과 따로 한다. 쪽 판정 줄과 쪽 판정 패널은 쪽이 없는 문서에서 숨겨야 한다. 판정 낱말 파일의 이름은 `<stem>.limnverdicts.json` 이라 그대로 된다 | 결함 `pins/runtime.py:273-274`, `pins/verdict.py:199-201`. 맞게 도는 곳 `pins/verdict.py:191-207`, `verdict.js:90-94`. 정리 `pins/runtime.py:273`·`:275`, `pins/verdict.py:84`, `verdict.js:76`·`:92`. 낱말 파일 `documents/verdicts.py:195-199` |
| 제안 수정 ([ADR-0020](../../adr/0020-suggested-edit-pins.md), [ADR-0024](../../adr/0024-suggested-edit-obvious-errors.md)) | 관문을 능력으로 옮긴다(§결정 3). `suggest_state`·`## 제안 문안`·원문 대조는 파일 종류를 가리지 않는다. PoC의 `fixture.md` 핀이 "바꿀 준비됨"으로 나왔다. ADR-0024의 "앞뒤 글과 대조한 명백한 오류"에는 Markdown 문법을 깨는 글도 든다. 표의 칸 수가 어긋나거나, 강조·코드 표시가 닫히지 않거나, 목록 들여쓰기가 틀린 경우다. SKILL 예시에 더한다(규칙은 그대로) | `pins/editing/rules.py:686-692`, `pins/listing/render.py` §제안 문안 |
| 댓글 타임라인·목록 순서 (0.4.42) | 카드의 타임라인은 문서 종류를 가리지 않는다. 목록의 `쪽순` 은 `page` 로 먼저 정렬하므로 `page` 없는 핀은 줄로만 정렬해야 한다. 저장 응답을 잃었을 때 되찾는 길은 `p.page===d.page` 로 핀을 찾는다 | `list.js:161-163`, `save.js:96`, `cards.js:64`(카드의 `N쪽`) |
| 능력의 전달 | 뷰어는 `/api/docs` 의 `kind` 에서 능력을 한 곳에서 계산한다(`isFigureKind`·`buildsFromSource`). 같은 자리에 `rendersInBrowser` 를 둔다. API에 능력 필드를 따로 더하지 않는다(§결정 3) | `viewer/js/core.js:60-64` |
| 조합을 끝내는 키 (0.4.46) | 한글 마지막 음절을 확정한 Enter·Esc는 조합만 끝낸다. Enter나 Esc로 무엇을 하는 키 처리는 모두 `imeKey` 부터 묻는다. Markdown 화면이 더하는 키 처리도 같다. 문서 안 `#제목` 링크의 Enter(PoC는 누르기만 받는다), 원문 줄 보기나 뒤에 올 문서 찾기 같은 새 글 칸이 그렇다. 원문이 바뀌어 화면을 다시 지을 때(`mdBuild`) 그 안에 조합 중인 칸이나 조합을 끝낸 키가 붙든 칸(`imeHeldIn`)이 있으면, 쪽을 다시 짓는 새 빌드처럼 칸을 놓을 때까지 미루고 `IME_ON_FREE` 로 잇는다. PoC의 Markdown 영역에는 글 칸이 없다. 작성 패널은 영역 밖이고 쪽 판정 줄은 숨긴다. 그래서 지금은 다시 지어도 칸을 빼앗지 않는다. PoC 브랜치는 0.4.45 기반이라 이 규칙이 없고, 구현은 0.4.46 이후 `main` 에서 한다. 시험은 Linux의 순서를 CDP로 보내는 기존 도구(`ime_end_with`)로 한다 | `viewer/js/core.js`(`imeKey`, `imeHeldIn`, `IME_ON_FREE`), `rebuild.js`(`refreshDoc` 의 `pvReasonComposed`), [viewer.md](../../handbook/viewer.md) §조합을 끝내는 키 |
| 변경 보기 ([ADR-0005](../../adr/0005-pin-scoped-changes.md), [ADR-0014](../../adr/0014-two-commit-comparison.md)) | 공유 pathspec에 `md` 를 더하지 않는다. 더하면 같은 폴더 LaTeX 문서의 이력에 Markdown 커밋이 섞이고, Markdown 문서는 폴더의 `.tex` 이력을 받는다. Markdown 문서의 이력 파일은 그 `.md` 하나다. 그림 문서처럼 파일 목록 길로 넘기고, 목록은 `history_files` 가 능력으로 고른다(요소 지도 → 지도·PDF·스크립트, 브라우저가 그리는 문서 → 그 파일). LaTeX의 확장자 거름은 그대로 둔다. 핀 단위 hunk는 `splitlines` 줄 번호와 git 줄 번호를 이미 맞춘다. 비교 PDF(latexdiff)는 Markdown에서 돌리지 않으므로 소스 diff만 연다 | `revisions/core.py:396-427`(`revision_scope`, `files` 가 있으면 `_files_scope` `:430-448`), `builds/queries.py:273-286`(`history_files`), `revisions/scope.py:252-264` |
| `pins.md` | 쪽 칸이 `r.get("page", 0)` 이라 `page` 없는 핀은 `0`, PoC처럼 기본값 1을 저장하면 `1` 이 찍힌다. 절 제목에 문서 종류 꼬리말이 없다. `기준:` 줄은 빌드가 없어 빠진다. 범위 칸은 모르는 `scope` 이면 `kind` 를 싣는다 | `pins/listing/render.py:694`, `:812-819`, `:169-182` |
| 되돌리기 계약 | 옛 서버(≤0.4.46)는 `.md` 문서가 있는 설정으로는 시작하지 않는다(`DocKindUnknown`). 인스턴스 셸도 거절한다. 그래서 되돌리려면 먼저 그 문서를 설정에서 뺀다. 상태 폴더는 그대로 읽힌다. Markdown 핀은 평범한 줄 핀이고, 설정에 없는 문서의 핀은 `## 설정에 없는 문서` 절로 간다. 새 `scope`·`kind` 값은 레코드 검사(문자열인지만 본다)를 지난다 | `administration/serve_documents.py:265`, `administration/instance_documents.sh:63`, `pins/record.py:128`, `pins/listing/render.py:821-829`. 선례: `tests/contracts/test_suggest_rollback.py` |
| 읽기 권한 | 새 읽기 경로는 등록 전까지 거부된다(닫힌 기본값). 원문 경로와 `/vendor/markdown-it/` 을 선언해야 한다 | `security/access.py:645-670`, `:689` |
| 보안 헤더 | 뷰어 페이지의 CSP는 `frame-ancestors 'none'` 뿐이고, 인라인 스크립트를 막지 않는다. 같은 출처에서 남이 쓴 글을 그리게 되므로 렌더러의 규율에만 기대게 된다(§결정 5) | `web/handler.py:141-148` |

### 쉬워진 것과 어려워진 것

**쉬워진 것.**

- 그림 문서([ADR-0011](../../adr/0011-figure-documents.md))가 "latexmk로 빌드하지 않는데 줄 핀을 받는 문서"를 이미 만들어 두었다. 그래서 `doc_for_file`, `pins.md` 의 문서별 절, 값 목록을 늘리는 선례(D5)를 그대로 쓴다.
- 뷰어가 책임별 조각(`viewer/parts.txt`)으로 나뉘어 있고, `innerHTML` 을 쓰는 곳은 `markup.js:43` 한 곳뿐이다. PoC는 새 조각 하나(`md-surface.js` 278줄, `md-surface.css` 58줄)와 기존 JS 조각 열둘에 걸친 연결 24줄로 화면을 붙였다. 서버 쪽은 Python 63줄을 더하고 11줄을 바꿨다.
- 원문 대조·`suggest_state`·줄 맞춤·겹침은 텍스트 일반이다. `GET /api/snippet?text=1` 로 정확한 원문도 받는다.
- `revisions/scope.py:252-264` 가 `splitlines` 와 git 의 줄 번호 차이를 이미 다룬다.
- `doc_start_line` 의 완전 매치(`administration/serve_documents.py:356-367`)가 새 종류의 표시 이름이 빠지면 mypy에서 실패한다. PoC 브랜치의 mypy는 통과한다.

**어려워진 것.**

- 판정 핀 코드가 종류를 직접 묻는다. 쪽을 전제한 판정 화면(쪽 판정 줄·패널·사유 팝오버)도 크다.
- 시작할 때의 빌드가 모르는 문서를 PDF로 렌더하려 든다.
- 뷰어가 커졌다. 화면 하나를 더할 때 꺼 두어야 하는 쪽 전제 코드가 늘었다.

## 결정 (추천안)

| # | 결정 | 추천 | 소유자 몫 |
| --- | --- | --- | --- |
| 1 | 핀 위치 모델 | Markdown 줄 핀은 `page`·`frac`·`pdf_build` 를 저장하지 않는다. 만드는 길과 고치는 길 모두 그 값을 지운다. `pins.md` 쪽 칸은 `—` 로 쓴다 | 예 — 저장 형식과 `pins.md` 표시 |
| 2 | 종류 값 | 문서 `kind` 에 `markdown` 을 더한다. `scope` 에 `block`·`section`, 핀 `kind` 에 `md:<블록>`·`md:section` 을 더한다(ADR-0011 D5 선례) | 아니오 — 선례를 따르는 덧셈. ADR과 함께 승인 |
| 3 | 능력으로 판단 | `renders_in_browser`·`takes_suggestions` 를 더하고, 판정 대상 계산과 시작 빌드에 남은 종류 비교를 능력으로 바꾼다. API에 능력 필드는 더하지 않는다 | 아니오 — 내부 구조 |
| 4 | 파서 | markdown-it(ESM 브라우저 빌드)을 뷰어에 번들한다. Markdown 문서를 열 때만 불러오고, 토큰을 직접 DOM으로 짓는다. 서버는 Markdown을 파싱하지 않는다 | 예 — 멈춤 신호(번들 추가) |
| 5 | 보안 | DOM API로만 짓는다. 원시 HTML은 그리지 않는다. 링크는 렌더러의 허용 목록으로만 연다(다른 출처의 `http(s)`, `mailto`, 문서 안 `#제목`). 뷰어 자신의 출처와 루프백 주소는 열지 않는다. 그림은 불러오지 않는다. 읽기·파싱·그리기에 한도를 둔다. 앞서 뷰어 페이지에 `script-src` CSP를 붙인다 | 예 — 보안 경계와 제품 영향 |
| 6 | 줄 나누기와 줄 대응 | 서버가 나눈 줄을 그대로 보내고, 뷰어는 `\n` 으로 이어 파싱할 뿐 원문 바이트를 다시 나누지 않는다. 블록 안에서는 인라인의 줄바꿈 토큰 수가 원문의 줄 끝 수와 같을 때만 줄 단위로 가리키고, 다르면 그 범위 전체로 물러선다 | 아니오 — 줄 번호와 블록 범위는 구성으로 같고, 블록 안의 줄 대응은 시험으로 지킨다 |
| 7 | 뷰어 구조 | 같은 탭·패널·목록·작성 패널 뒤에 두 번째 문서 영역을 둔다. 쪽 전용 조작은 숨긴다. 글을 끌면 줄(줄을 가릴 수 없는 글이면 그 범위), 블록을 누르면 블록을 고른다 | 부분 — 조작과 모양은 PoC로 소유자가 본다 |

### 결정 1. 핀 위치 모델

**추천.** Markdown 문서의 줄 핀은 `file`·`lo`·`hi`·`kind`·`scope`·`quote`(와 `raw_lo`·`raw_hi`)만 가진다. `page`·`frac`·`pdf_build` 는 저장하지 않는다. 표시는 그린 블록 위에 `lo..hi` 로 한다.

**근거.**

- 읽기 쪽은 이미 `page` 없는 줄 핀을 받는다(`pins/record.py:92`, `pins/model.py:379`). 옛 서버로 되돌려도 레코드가 깨지지 않는다.
- `page: 1` 을 저장하는 길(PoC가 기본값 때문에 그렇게 했다)은 코드가 가장 적다. 그러나 `pins.md` 의 쪽 칸에 거짓 `1` 이 찍히고(PoC의 `pins.md`), 에이전트 계약에 뜻 없는 값이 남는다. 한번 퍼진 값은 되돌리기 어렵다.

**바꿀 곳.** 쪽 없는 문서라는 사실을 만드는 길과 고치는 길 끝까지 싣는다. 입력 파서는 `DocumentFacts` 에서 읽는다. 요소 지도와 같은 길이다(`has_element_map`, `builds/document_facts.py:37-40`). 순수 규칙(`new_line_pin`, 편집 규칙)은 그 값을 인자로 받는다.

- `parse_loc` 는 `renders_in_browser` 문서에서 `page`·`frac`·`pdf_build` 를 받아도 버린다. 그림 문서가 아닌 곳의 `el` 을 버리는 선례를 따른다. 에이전트가 습관처럼 `page: 1` 을 보내도 실패하지 않게 하려는 것이다(`pins/editing/location.py:200`, `:51`).
- `LinePlace` 는 그런 문서에서 `page` 를 요구하지 않는다(`pins/editing/rules.py:142-154`).
- `new_line_pin` 은 그런 문서에 `pdf_build` 를 넣지 않는다. 지금은 보내지 않아도 화면의 빌드를 넣는다(`rules.py:913`).
- 편집은 위치를 바꿀 때 `pdf_build` 를 되살리지 않고(`_placed_build`, `pins/editing/input.py:254-265`), 이름이 불리지 않은 `page`·`frac` 을 저장된 값에서 남기지 않는다(`keep`, `rules.py:755-759`). 위치를 바꾸지 않는 편집(메모·제안·판정)도 레코드에 남은 `page`·`frac`·`pdf_build`·`frac_build` 를 지운다. PoC가 남긴 `page: 1`, 손으로 고친 레코드, 생성 `.tex` 탭에서 옮겨 온 핀이 그런 값을 가질 수 있다.
- `pins.md` 의 쪽 칸은 `page` 가 없는 줄 핀에 `—` 를 쓴다(`pins/listing/render.py:694`). 지금은 `0` 이다.
- 뷰어는 카드의 `N쪽`(`cards.js:64`), `쪽순`(`list.js:161-163`), 응답을 잃은 저장 되찾기(`save.js:96`)를 `page` 없이도 맞게 고친다.

**시험.** 보낸 값이든 물려받은 값이든 쪽 필드가 Markdown 저장을 지나 남지 않는다.

- 만들 때 보낸 `page`·`frac`·`pdf_build` 가 저장되지 않는다. 보내지 않아도 `pdf_build` 가 생기지 않는다(`null` 도 아니다).
- 위치를 바꾸는 편집에 `page`·`frac`·`pdf_build` 를 보내도 남지 않는다.
- 그 값을 이미 가진 Markdown 레코드(`page`·`frac`·`pdf_build`·`frac_build`)는 위치를 바꾸는 편집 뒤에도, 메모만 고치는 편집 뒤에도 그 값을 잃는다.
- LaTeX 줄 핀은 지금처럼 `page`·`frac`·`pdf_build` 를 지킨다.

**대안.** 블록 번호를 저장하는 안은 편집에 살아남지 못해 기각했다. 새 위치 필드를 더하는 안은 줄 범위로 충분해서 기각했다.

### 결정 2. 종류 값과 옛 에이전트

**추천.** `/api/docs`·`/api/meta` 의 `kind` 에 `markdown` 을 더한다. 사다리 값은 `scope` `block`·`section`(`levels[].level` 도 같다)이고, 핀 `kind` 는 `md:paragraph`·`md:item`·`md:table`·`md:code`·`md:quote`·`md:html`·`md:section` 이다. 옛 핀의 `kind` 값 `block`(환경 블록)과 겹치지 않게 접두를 붙인다.

**근거.** ADR-0011 D5가 값 목록을 한 변경에서 늘린 선례다. 레코드 검사는 문자열인지만 보고(`pins/record.py:128`), `pins.md` 범위 칸은 모르는 `scope` 이면 `kind` 를 싣는다(`render.py:169-182`). 옛 에이전트는 SKILL의 "`kind:"tex"` 만 재빌드" 규칙을 따르는데, Markdown은 재빌드가 필요 없으므로 결과가 맞다. 확장자는 1단계에서 `.md` 하나만 받는다.

### 결정 3. 종류가 아니라 능력으로

**추천.**

- `Doc` 에 `renders_in_browser`(HTML 화면)와 `takes_suggestions`(LaTeX·Markdown)를 더한다. Markdown은 `takes_line_pins` 가 참, `builds_from_source`·`watches_files`·`has_element_map` 이 거짓이다. `shows_revisions` 는 변경 보기를 붙이는 단계에서 참이 된다.
- 제안 관문(`check_suggestion` 과 그 호출자, `suggestOff`)을 `takes_suggestions` 로 옮긴다.
- 판정 대상의 배치(`pins/runtime.py:273-274`)가 "줄 핀을 받고 요소 지도가 없는 문서"에 `file` 을 싣게 한다. 이것이 Markdown 판정 핀의 결함을 고치는 곳이다. 남은 종류 비교(`pins/runtime.py:273`·`:275`, `pins/verdict.py:84`, `verdict.js:76`·`:92`)를 능력으로 바꾸는 것은 동작을 바꾸지 않는 정리라 따로 한다.
- 시작 빌드(`builds/run.py:51-58`, `builds/service.py:79-86`)는 `renders_in_browser` 문서를 건너뛴다.
- 뷰어는 `core.js` 의 종류 → 능력 함수 자리에 `rendersInBrowser` 를 더한다. 뷰어와 서버는 늘 같은 판이므로 API에 능력 필드를 따로 싣지 않는다.

### 결정 4. Markdown 파서

**추천.** markdown-it을 `src/limn/vendor/markdown-it/` 에 번들한다. PoC는 15.0.3 ESM 브라우저 빌드(`markdown-it.esm.min.mjs` 124,681바이트, MIT)를 썼다. 이 한 파일에 의존성이 함께 들어 있다. `entities` 8.1.0(BSD-2-Clause), `mdurl` 2.1.0(MIT, Node.js `url` 코드에 대한 Joyent 고지 포함), `linkify-it` 6.1.0·`uc.micro` 3.0.0·`punycode.js` 2.3.1(MIT), 번들러가 넣은 rolldown 1.2.14 실행 도우미와 `@oxc-project/runtime` 0.154.0 도우미(MIT)다. oxc 도우미는 `@babel/runtime` 에서 베낀 코드다(그 패키지의 README). 번들의 네 도우미 가운데 `typeof`(Babel 표지 `"@babel/helpers - typeof"` 가 남아 있다)·`toPropertyKey`·`defineProperty` 는 `@babel/runtime` 8.0.7·7.29.10의 `helpers/esm` 과 바이트까지 같고, `toPrimitive` 는 Babel 것에서 `typeof Symbol` 검사를 뺀 것이다. 그래서 Babel의 MIT 고지(Sebastian McKenzie and other contributors)도 함께 둔다. 판은 markdown-it 15.0.3 태그의 lockfile로 확인했다. 고지는 하나도 빼지 않고 `src/limn/vendor/markdown-it/licenses/` 와 `THIRD_PARTY_NOTICES.md` 에 둔다(PoC 브랜치에 넣었다). BSD-2-Clause는 배포물에 저작권 고지·조건·면책 문구를 함께 실어야 한다. 뷰어는 Markdown 문서를 열 때만 `import()` 로 불러온다. PDF.js가 `/vendor/pdfjs/` 로 서빙되는 방식과 같다.

**근거 (PoC로 확인).**

- 블록 토큰의 `map` 이 원문 줄 범위다. 문단·제목·목록 항목·표 행·코드 블록·인용·구분선에 다 붙는다.
- 문단 안에서는 줄바꿈 토큰(`softbreak`·`hardbreak`)이 원문 줄의 경계다. 단, 줄 끝을 삼키는 인라인 구성이 있으면 그 뒤의 줄을 셀 수 없다. 그래서 줄바꿈 토큰 수가 원문의 줄 끝 수와 같은 인라인만 줄마다 `span[data-line]` 을 두고, 다르면 그 범위 전체로 물러선다(§결정 6). 코드 블록은 내용 줄을 하나씩 감싼다.
- 좁은 목록의 숨은 문단은 항목에 바로 그린다. 표 칸의 줄은 행으로 묶는다.
- 렌더러의 HTML 문자열은 쓰지 않는다. 토큰을 따라 `createElement`·`textContent` 로 짓는다(§결정 5).
- 서버는 Markdown을 파싱하지 않는다. 사다리의 블록·절도 뷰어가 줄 지도에서 계산한다. 서버는 저장할 때 `lo..hi` 가 파일 안인지만 본다.

**대안: 서버에서 표준 라이브러리로 렌더.** 번들은 없다. 대신 CommonMark 블록 규칙(게으른 이어짐, 목록 들여쓰기, setext 제목, 참조 링크 정의, HTML 블록, GFM 표)을 Limn이 소유하고 시험해야 한다. 게다가 GitHub 렌더와 경계 사례에서 어긋난다. 렌더 결과를 뷰어에 넣으려면 서버가 만든 HTML을 넣는 두 번째 sink나 별도 트리 형식도 필요하다.

**대안: 블록 경계만 손으로 나누고 글은 평문으로.** 코드는 가장 적다. 그러나 표·강조·목록 모양이 없어 "흐르는 글"을 읽는다는 목적에 못 미친다.

**소유자 몫.** 런타임 번들을 더하는 것은 멈춤 신호다. ADR-0025 D5가 이 결정이다.

### 결정 5. 보안

렌더한 문서는 뷰어와 같은 출처에서 사용자의 신원을 쓴다. 문서 안의 무엇도 스크립트가 되거나 API를 부르거나 밖으로 요청을 보내지 않아야 한다.

**추천.**

1. **DOM API로만 짓는다.** markdown-it의 `render()` 를 쓰지 않는다. `innerHTML` 을 쓰는 곳은 `markup.js:43` 하나로 남는다.
2. **원시 HTML은 그리지 않는다.** 파서는 원시 HTML을 별도 토큰으로 내도록 켜 두되(`html:true`), 블록은 줄 범위를 가진 자리표시("HTML N줄 · 그리지 않습니다"와 첫 줄)로, 인라인 태그는 코드 글자로 보인다. 자리표시도 줄 핀을 받는다. 원시 HTML을 끄면(`html:false`) 그 글이 문단 글자로 길게 풀린다. 실제 README 머리의 로고·배지 HTML이 그랬다(PoC 캡처).
3. **링크는 렌더러의 허용 목록으로만 연다.** markdown-it의 `validateLink` 는 거부 목록이다. `javascript:`·`vbscript:`·`file:`·`data:` 만 막고, 그중 `data:image/gif|png|jpeg|webp` 는 통과시킨다. `ftp:` 와 임의 scheme은 링크가 된다(PoC 시험으로 확인). 그래서 일반 링크·자동 링크·참조 링크의 모든 `link_open` 이 같은 허용 목록을 지나야 하고, `validateLink` 에는 기대지 않는다. 열리는 것은 셋이다. 다른 출처의 `http:`·`https:` 는 새 탭(`rel="noopener noreferrer"`)으로, `mailto:` 도 새 탭으로 연다. 문서 안 `#제목` 은 그 제목으로 간다. 상대 경로, `//호스트`, 그 밖의 scheme은 글자로 두고 팁에 대상을 적는다. 상대 경로는 나중에 등록된 다른 문서로 이을 수 있다. 주소는 페이지 기준 없이 `URL` 로 파싱해 검사하고, 검사한 그 값을 `href` 로 넣는다. 날 문자열 `https:/api/meta` 는 페이지 기준으로 풀면 뷰어 자신의 출처가 되기 때문이다.
   - **같은 출처의 절대 주소는 열지 않는다(추천).** 뷰어와 같은 출처(`location.origin`)와 루프백 호스트(`localhost`, `127.0.0.0/8`, `[::1]`, `0.0.0.0`)를 가리키는 `http(s)` 링크는 글자로 둔다. 사용자 이름·비밀번호가 든 주소도 글자로 둔다. 근거는 셋이다. Limn의 GET은 읽는 사람의 신원으로 답하고, 그중에는 쓰기를 하는 것이 있다. 전체 `/api/meta`·`/api/pins`·`/pins.md` 는 핀을 다시 맞춰 쓰고, `/` 는 연 사람을 기록한다([api.md](../../handbook/api.md)). 서버 기계에서 문서를 읽는 사람에게 루프백 주소는 헤더 없는 루프백 요청, 곧 로컬 에이전트로 닿는다. 문서 안 이동은 `#제목` 으로 되므로, 문서를 쓴 사람이 읽는 사람의 Limn 요청을 만들 까닭이 없다. 등록된 다른 문서로 가는 링크는 이후 단계에서 따로 연다.
   - **호스트는 한 철자로 비교한다.** 같은 호스트를 다르게 쓴 주소가 관문을 지나면 안 된다. `URL` 파서는 대소문자, 전각 글자, 퍼센트 이스케이프, IPv4의 모든 표기(`127.1`, `0x7f.1`, `017700000001`, `2130706433`, `127.0.0.1.`)를 점 네 개 꼴로, IPv6을 짧은 16진 꼴로 바꾼다. 그러나 이름 끝의 점은 남긴다(`localhost.`, `localhost%2e`·`localhost。` 도 `localhost.` 가 된다). DNS는 `이름.` 을 `이름` 으로 읽고, Limn의 Host·Origin 검사도 끝의 점을 뗀다. 그래서 관문은 목적지와 뷰어(`location.origin`)의 호스트를 모두 같은 규칙으로 바꾼 뒤 비교한다. 소문자로, IPv6 괄호를 빼고, 끝의 점을 모두 뗀다. 같은 출처는 scheme·호스트·포트가 모두 같은 것이다(기본 포트는 파서가 지운다). 루프백은 `localhost`·`*.localhost`, `127.0.0.0/8`·`0.0.0.0/8`, IPv6 `::`·`::1` 과 그 두 IPv4 범위의 IPv4 대응 주소(`::ffff:a.b.c.d`)·호환 주소(`::a.b.c.d`)다. 뷰어 출처를 파싱하지 못하면(`null`) 같은 출처로 보아 웹 링크를 하나도 열지 않는다. hosts 파일이 루프백으로 잇는 다른 이름(`ip6-localhost`, 기계 이름)은 넣지 않는다. Limn의 Host 검사가 루프백으로 받는 이름은 `localhost`·`127.0.0.1`·`::1` 뿐이고, 그 밖의 이름에는 403으로 답한다(PoC에서 `ip6-localhost` 로 확인). PoC 시험은 일반 링크·참조 링크·자동 링크, linkify를 켠 맨 주소의 토큰으로 이 규칙을 본다. linkify-it은 맨 주소의 호스트를 끝의 점에서 끊는다. 그래서 `http://localhost.:18920/…` 는 `http://localhost` 링크와 그 뒤의 글자가 된다. 뷰어는 linkify를 끈다.
   - **서버의 Host 검사는 끝의 점을 그대로 받는다(권고: 바꾸지 않는다).** 지금 `split_host`(`security/access.py:247-257`)는 이름을 소문자로 바꾸고 끝의 점을 모두 뗀다. 그래서 `host_ok` 는 `localhost.`·`LOCALHOST..`·`127.0.0.1.`·`<호스트>.ts.net.` 을 받고, `origin_ok`(`:317`)도 Origin의 끝 점을 뗀다. 이 정규화는 시험이 지킨다(`security/tests/test_header_parsers.py:59`). 실행 중인 PoC는 `Host: localhost.:18920` 에 200으로 답했고, tailscale serve 너머의 `https://<호스트>.ts.net.:18020/api/source` 도 200이었다(인증서는 점 없는 이름과 맞았다). 끝에 점을 붙인 Host를 서버가 거절해도 얻는 것이 없다. Host 검사는 DNS 리바인딩, 곧 남의 이름을 막는 장치다. `localhost.` 는 남의 이름이 아니고, 거절해도 `127.0.0.1`·`[::1]` 은 그대로 닿는다. 관문은 어차피 그 주소들을 막아야 한다. 거절하면 서버와 관문이 호스트를 읽는 규칙이 반대로 어긋날 뿐이다. 그래서 관문이 서버의 규칙을 그대로 쓴다. 모든 철자를 덮는 서버 쪽 방어는 다른 곳에 있다. 쓰기를 하는 GET(전체 `/api/meta`·`/api/pins`·`/pins.md`, `/`)이 다른 사이트에서 온 이동(`Sec-Fetch-Site: cross-site`·`same-site`)에서는 쓰지 않게 하는 것이다. 이것은 Markdown 화면과 따로 다룰 보안 변경으로 남긴다.
4. **그림은 불러오지 않는다.** 대체 글로 보인다. 원격 그림은 누가 언제 문서를 열었는지와 IP를 제3자에게 알린다. 나중 단계에서도 원고 트리 안의 그림만, 검사된 읽기 경로로 연다.
5. **뷰어 페이지에 CSP를 붙인다.** 이것을 앞선 조건으로 둔다. 서버는 조립할 때 인라인 스크립트의 바이트를 알므로 `script-src 'self' 'sha256-…'`, `object-src 'none'`, `base-uri 'none'` 을 걸 수 있다. 뷰어는 인라인 이벤트 처리기 없이 `data-act` 로 나누므로 걸림돌이 적다. PDF.js worker와 사람 사진(`img-src`)은 실측해서 정한다. 보안 경계 변경이므로 Markdown 화면보다 먼저, 따로 승인받는다.
6. **읽기·파싱·그리기에 한도를 둔다.** 아래 표가 한도와 넘었을 때의 화면이다. 값은 PoC 번들(markdown-it 15.0.3)을 node 26으로 잰 결과와, 이 저장소에서 가장 큰 Markdown(Limn `docs/handbook/viewer.md`, 612 KB, 블록 토큰 7,856, 인라인 토큰 11,963, 중첩 5단계)을 근거로 잡았다. 승인 전에 네 기기군에서 다시 잰다.

   | 한도 | 값 | 넘으면 |
   | --- | --- | --- |
   | 원문 바이트 | 1 MiB. 원문 경로가 검사된 원고 핸들의 `read_bounded(1_048_576)` 로 읽는다 | 서버가 줄을 보내지 않고 `413`, `reason:"source_too_large"`(`bytes`, `limit`)로 답한다. 뷰어는 문서 자리에 "이 문서는 N MiB라 그리지 않습니다(한도 1 MiB)"를 보인다. 핀 목록·카드·에이전트 경로는 그대로 쓴다 |
   | 중첩 | markdown-it `maxNesting: 20`(기본 100) | markdown-it은 한도에 닿으면 남은 줄을 알리지 않고 버린다. 40단 목록에서 10단 아래 항목과 그 뒤 문단이 사라졌다(잰 값). 그래서 어느 토큰의 `level` 이 19에 닿으면 한도를 넘은 것으로 보고 원문 줄 보기로 간다 |
   | 블록 토큰 | 30,000 | 원문 줄 보기 |
   | 인라인 토큰 | 150,000 | 원문 줄 보기 |
   | 그린 요소 | 60,000(줄 span 포함, 짓는 동안 센다) | 짓던 것을 버리고 원문 줄 보기 |
   | 원문 줄 보기의 줄 | 50,000(서버가 보낸 줄 목록의 길이) | 그리지 않는다. 바이트 한도와 다른 까닭을 실제 줄 수와 한도로 알린다. "이 문서는 원문이 N줄이라 그리지 않습니다(한도 50,000줄)"이고, 까닭 값은 `lines`(실제 줄 수)와 `limit` 이다(바이트 한도의 `bytes`·`limit` 과 같은 꼴). 이 한도는 뷰어가 본다. 1 MiB 안의 문서라면 서버는 줄을 보낸다. 핀 목록·카드·에이전트 경로는 그대로 쓴다 |
   | 시간 | 파싱은 전용 Worker에서 하고, 2초가 지나면 끝낸다(`terminate`). DOM은 2,000 토큰씩 나눠 짓고, 새 원문이 오면 짓던 것을 버린다 | 원문 줄 보기 |

   **원문 줄 보기.** 파싱하지 않고 서버가 보낸 줄을 번호와 함께 한 줄씩(`span[data-line]`) 그린다. 줄 핀·작성 패널·제안 수정은 그대로 되고, 사다리에는 "고른 줄"만 있다. 머리에 걸린 한도를 한 줄로 알린다("표가 너무 커서 원문 줄로 보입니다" 등).

   **왜 Worker인가.** 1 MiB에서 잰 최악의 파싱은 데스크톱 node에서 1.3초였다(`[` 백만 개). 휴대폰은 더 느리다. 메인 스레드에서 돌리면 그동안 화면이 멈추고 중간에 끊을 수 없다. 바이트 한도를 줄이면 이미 쓰는 문서(612 KB)가 걸린다. Worker는 PDF.js가 이미 쓰는 방식이고, CSP의 `worker-src 'self'` 하나로 덮인다.

   | 1 MiB 입력 | 파싱 | 블록 토큰 | 인라인 토큰 |
   | --- | ---: | ---: | ---: |
   | 보통 글(강조·코드·링크 섞음) | 98 ms | 3 | 124,583 |
   | 긴 한 줄(`a` 백만 개) | 5 ms | 3 | 1 |
   | `*a` 반복 | 472 ms | 3 | 1,048,576 |
   | `_a_ ` 반복 | 663 ms | 3 | 1,048,575 |
   | `[` 반복 | 1,339 ms | 3 | 1 |
   | `` `a `` 반복 | 180 ms | 3 | 524,288 |
   | 좁은 표(행 17만) | 755 ms | 1,398,118 | 349,528 |
   | 넓은 표(500열) | 929 ms | 1,574,102 | 523,742 |
   | 참조 정의 반복 | 268 ms | 3 | 4 |

   96 KB의 좁은 표도 블록 토큰 131,086개였다. 바이트 한도만으로는 DOM 크기를 막지 못하므로 토큰·요소 한도가 따로 필요하다.

**PoC로 확인한 것.** 시험 문서에 `<script>`, `onerror` 가 붙은 `<img>`, `javascript:` 링크, 원격 그림, 문서 밖 상대 링크를 넣었다. 그린 결과에 `script`·`img` 요소와 `on*` 속성이 하나도 없었고, `javascript:` href도 없었다. 원격 요청과 대화상자도 0건이었다(Chrome 156 자동화).

**소유자 몫.** 보안 경계가 바뀌고(CSP), README류 문서의 머리 HTML이 그려지지 않는 제품 영향이 있다. 대안은 허용 목록 소독기(DOMPurify 등)다. 번들이 하나 더 늘고 정책을 소유해야 해서 1단계에서는 추천하지 않는다.

### 결정 6. 줄 나누기와 줄 대응

**추천.** 서버가 줄의 권위다. 원문 경로는 `tex_lines`(`str.splitlines()`)로 나눈 줄 목록을 보낸다. 뷰어는 그것을 `\n` 으로 이어 파서에 넣을 뿐, 원문 바이트를 다시 나누지 않는다. 그래서 `\r\n`, 외톨이 `\r`, 폼 피드, `\v`, U+2028·U+2029, `\x1c`–`\x1e`, `\x85` 가 있어도 두 쪽의 줄 번호가 구성으로 같다. PoC가 이렇게 한다. 변경 보기는 `revisions/scope.py:252-264` 가 git 줄 번호와 맞춘다.

**블록 안의 줄 대응은 따로 지킨다.** 구성으로 같은 것은 줄 번호와 블록의 줄 범위(블록 토큰의 `map`)까지다. 그린 글에서 원문 줄로 가는 길은 그렇지 않다. markdown-it은 인라인 자식에 원문 위치를 달지 않고, 표 칸의 인라인 토큰에는 `map` 도 없다. 줄바꿈 토큰을 세어 줄을 매기면, 줄 끝을 삼키는 구성 뒤의 글이 한 줄씩 앞당겨진다. 여러 줄에 걸친 코드 표시(줄 끝이 공백이 된다), 원시 HTML 태그, 링크 주소와 제목, 참조 이름, 그림 대체 글이 그렇다. 그러면 고른 줄과 핀이 다른 줄을 가리키고, 제안 수정이 엉뚱한 원문을 바꾼다. 여러 줄에 걸친 강조와 링크 글은 줄바꿈 토큰을 남기지만, 줄바꿈이 열린 요소 안에 있으면 다음 줄의 글이 앞 줄의 span에 들어간다(PoC 첫 판의 결함).

**규칙.** 인라인 토큰마다 자식의 줄바꿈 토큰 수와 그 원문(`content`)의 줄 끝 수를 비교한다.

- 같으면 모든 줄 끝이 줄바꿈 토큰이 된 것이다. 그 수로 줄을 매겨 줄마다 `span[data-line]` 을 둔다. 강조·링크 안의 줄바꿈에서는 열린 요소를 닫고 새 줄의 span 안에 같은 요소를 다시 연다.
- 다르면 그 인라인 전체를 한 범위(`data-lo`..`data-hi`)로 둔다. 그 안을 고르면 범위 전체가 핀이 되고, 사다리의 블록 단계는 그 블록이다.
- 표 칸은 행(`tr`)의 범위를 쓴다.

줄을 틀리게 매기는 일은 없다. 줄을 가릴 수 없는 곳만 블록 범위로 물러선다. PoC가 이렇게 하고(`mdInlineLines`), 순수 시험이 있다(`viewer/tests/test_md_surface_poc.py`). 줄 끝 수 비교를 빼면 이 시험의 여섯 사례가 실패한다.

**대안: 원문 오프셋을 인라인 파서에 싣는다.** 인라인 규칙마다 `state.pos` 를 토큰에 기록하는 플러그인이면 물러서지 않고 정확히 맞출 수 있다. 그러나 대기 중 글(pending), 이스케이프, 강조의 후처리가 위치를 옮겨 규칙마다 따로 다뤄야 하고, 판을 올릴 때마다 다시 맞춰야 한다. 물러서는 경우가 드물어 1단계에서는 추천하지 않는다.

**검증.** 위 구분자를 모두 담은 시험 파일로 뷰어의 `data-line` 이 서버의 줄과 같은지 확인한다. 블록 안에서는 다음 사례마다, 줄 단위로 매긴 글 조각이 그 원문 줄에 실제로 있는지 본다. 여러 줄의 강조·굵게·링크 글·강제 줄바꿈은 줄 단위로 맞는다. 여러 줄의 코드 표시·인라인 HTML·링크 주소와 제목·그림 대체 글·참조 이름은 범위로 물러선다. 물러선 블록 뒤의 블록은 제 줄을 지킨다. 첫 줄이 아닌 곳의 블록(제목, 목록, 인용, setext 제목), 표의 행도 본다.

### 결정 7. 뷰어 구조

**추천 (PoC 구현).**

- **두 번째 문서 영역.** `#doc` 안에 흐르는 단 하나(`article#md`)를 그린다. 같은 탭·패널·목록·작성 패널·카드를 쓴다. 갈리는 곳은 `buildDoc`·`marks`·`jumpPin`·`pickOutline`·`vecOpen`·클릭으로 선택 취소(`pressOutsideSelection`)·meta 폴링이다.
- **숨기는 쪽 전용 조작.** 쪽 칸과 쪽 목록, PDF 확대(막대와 [더보기]), [선택] 모드, PDF 내려받기, 단 띠의 쪽 표시, Limn 찾기 칸, 변경 보기 전환(1단계는 붙일 때까지)이다. 브라우저의 찾기는 그대로 쓸 수 있다.
- **고르기.** 마우스로 글을 끌면 그 줄들이고, 사다리의 기본은 "고른 줄"이다. 줄을 가릴 수 없는 글(§결정 6) 안에서 끝나는 선택은 그 범위 전체를 잡는다. 블록을 누르면(마우스·손가락) 그 블록이고, 기본은 "블록"이다. 손가락으로 길게 눌러 손잡이로 고르면 선택이 멈춘 뒤 0.5초에 줄을 고른다. 고른 줄은 파란 바탕으로 보인다.
- **핀 표시.** 핀의 줄에 상태색 바탕을 깐다(열림 초록, 검토 대기 보라, 위치 잃음 주황). 표 칸의 줄은 행으로 묶는다. 첫 줄 높이에 맞춰 단의 왼쪽 여백에 번호 배지를 세우고, 누르면 카드로 간다(44px 누름 영역). 배지는 글 흐름 밖 층에 있어 글을 밀지 않고, 단 폭이 바뀌면 다시 놓인다.
- **목차.** 제목에서 만들고 오른쪽에 `L<줄>` 을 붙인다.
- **목록 순서.** `쪽순` 은 Markdown 문서에서 줄 순서다. 이름을 `위치순` 으로 바꿀지는 소유자가 정한다.
- **판정.** 쪽 판정 줄·쪽 판정 패널은 Markdown 문서에서 그리지 않는다. 판정 행은 줄 대상으로 동작한다(§결정 3).
- **위치 표시.** 쪽이 없으므로 휴대폰 위치 단추는 읽는 줄의 원문 줄과 전체 줄 수(`L37/164`)를 보이고, 절 띠와 목차의 현재 항목은 읽는 줄 위의 제목이다.

PoC 첫 판에서 드러난 두 가지(휴대폰 위치 단추의 `−/−`, 빈 목록 도움말의 PDF 문구)는 개정 1 검토 반영에서 고쳤다.

## 바꿀 곳 (개정 1)

| 영역 | 파일 (`main` 기준 줄) | 크기 |
| --- | --- | --- |
| 등록: `DocKind`, 능력, 확장자, 메시지, 시작 줄, 셸 검사 | `runtime/documents.py:40`·`:298-336`, `administration/serve_documents.py:256-266`·`:356-367`, `administration/instance_documents.sh:55-63` | 작음 |
| 시작 빌드 건너뛰기 | `builds/run.py:51-58`, `builds/service.py:79-86` | 작음 |
| 원문 경로(1 MiB 제한 읽기, 줄 목록, `413 source_too_large`)와 읽기 권한 | `documents/` 또는 `pins/location/`(PoC), `platform/files.py:219-247`(`read_bounded`), `security/access.py:645-670` | 작음, 계약(새 경로) |
| `page` 없는 Markdown 줄 핀(만들기·고치기) | `builds/document_facts.py:37-40`(능력 싣기), `pins/editing/location.py:51`·`:200`, `pins/editing/rules.py:142-154`·`:755-759`·`:913`, `pins/editing/input.py:254-265`, `pins/listing/render.py:694` | 중간, 계약 |
| 사다리 값과 범위 칸 | `pins/editing/values.py:22-25`, `pins/listing/render.py:169-182` | 작음, 계약 |
| 제안 관문을 능력으로 | `pins/editing/rules.py:525-532`·`:686-692`, `pins/editing/service.py:79`, `pins/editing/http.py:85`, `viewer/js/suggest.js:32` | 작음, 계약(ADR-0020 D1 부분 대체) |
| 판정 대상: 배치 결함 | `pins/runtime.py:273-274`(Markdown 줄 핀에도 `file` 을 싣는다) | 작음 |
| 판정 대상: 종류 비교 정리(동작 그대로), 쪽 판정 화면 끄기 | `pins/runtime.py:273`·`:275`, `pins/verdict.py:84`, `viewer/js/verdict.js:76`·`:92`, `verdict-reason.js`·`verdict-panel.js` | 작음 |
| `pins.md` 문서 절 꼬리말 | `pins/listing/render.py:812-819` | 작음, 계약 |
| 변경 보기 | `builds/queries.py:273-286`(`history_files` 가 능력으로 이력 파일을 고른다), `revisions/core.py:396-448`(파일 목록 길, LaTeX pathspec `:424-426` 은 그대로), 비교 PDF 끄기, 뷰어는 소스 diff로 연다 | 작음~중간 |
| 번들과 서빙(번들 의존성의 고지 전부) | `src/limn/vendor/markdown-it/`(`licenses/`), `THIRD_PARTY_NOTICES.md`, `viewer/assemble.py:44`, `viewer/routes.py:27-32`·`:98-101`, `viewer/application.py:32-38`, `security/access.py:689` | 작음, 멈춤 신호 |
| CSP | `web/handler.py:141-148`, `viewer/assemble.py`(인라인 스크립트 해시) | 작음, 보안 경계(앞선 조건) |
| 뷰어 HTML 화면(줄 대응 규칙, 링크 허용 목록, 파싱 Worker와 한도, 원문 줄 보기) | 새 조각 `js/md-surface.js`·`css/md-surface.css`, `core.js`, `pages.js`, `list.js`, `outline.js`, `pdf-open.js`, `composer.js`, `cards.js`, `boot.js`, `selection.js`, `polling.js`, `levels.js`, `save.js` | 큼 |
| Handbook과 SKILL | `purpose.md`(범위), `architecture.md`, `domain.md`(능력 표), `api.md`(종류 값, `page` 없는 줄 핀, 제안 관문, 판정 대상), `viewer.md`, `instances.md`, `operations.md`, `build-sync.md`, `skill/SKILL.md`·`.ko.md` | 넓음 |
| 종류를 나열하는 시험 | `documents/tests/test_meta.py`, `administration/tests/test_serve_documents.py`, `runtime/tests/test_startup.py`, `administration/tests/test_instances.sh`, `viewer/tests/test_viewer.py`, 판정 시험, 계약 스냅숏 | 중간 |

## 버리는 PoC

`poc/html-surface` 브랜치에 있다. 소유자가 네 기기군에서 방향을 판단하라고 만든 것이고, 머지하지 않는다([workflow.md](../../handbook/workflow.md) §경로가 달라지는 경우의 탐색 규칙). 실행법과 시험 문서는 `tools/poc-html-surface/` 에 있다.

**보여 주는 것.**

- `.md` 등록, 흐르는 렌더, 블록과 줄마다의 원문 범위.
- 선택에서 줄 핀으로, 사다리, 작성 패널·카드·편집 카드·제안 수정(Markdown 원문 diff), 검토 대기 표시.
- `pins.md` 의 Markdown 핀, 제목 목차, 원문 변경 시 다시 그리기.
- 원시 HTML 자리표시와 보안 시험.
- 블록 안 줄 대응 규칙과 링크 허용 목록(같은 출처·루프백 제외), 그 순수 시험(`viewer/tests/test_md_surface_poc.py`).
- 번들 의존성의 판과 고지(`vendor/markdown-it/README.md`, `licenses/`).

**지름길 (설계가 아니다).** `page: 1` 저장(결정 1과 다르다), 서버 쪽 능력 판단의 임시 분기, 찾기·변경 보기·비교 없음, 시험은 위 순수 시험 하나뿐. 원문 경로를 `pins/location/` 에 두었고, §결정 5의 한도(바이트·중첩·토큰·요소·시간, Worker, 원문 줄 보기)가 없다. CSP도 없다.

**측정.** PoC 브랜치에서 구조 경계 시험(`tests/architecture`)과 뷰어 조립·조각 목록 시험 138건, PoC 순수 시험 5건(하위 사례 13), mypy(167개 파일)가 통과한다. 전체 시험은 돌리지 않았다.

## 이후 단계

1. 일반 텍스트와 소스 코드 파일을 같은 화면에(줄마다 또는 문단마다 블록 하나).
2. Markdown의 그린 화면 비교(두 판을 그리고 바뀐 블록 표시).
3. 원문 위치를 지키는 렌더러가 있는 다른 줄 단위 형식.
4. 원고 트리 안의 그림, 등록된 다른 Markdown 문서로 가는 상대 링크.

## 검증

- **순수 시험.** 서버와 뷰어의 줄 번호가 구분자 전부에서 같다. 블록 안 줄 대응(§결정 6의 사례: 여러 줄의 강조·링크 글·코드 표시·인라인 HTML·링크 주소·그림 대체 글·참조 이름). 사다리의 단계(블록 종류별, 좁은·넓은 목록, 중첩 목록, 표, 코드 블록, 절 경계). 선택 → 줄(끝이 다음 블록의 맨 앞에서 멈춘 선택, 줄을 가릴 수 없는 글 안의 선택 포함). 링크 허용 목록(일반·자동·참조 링크, 다른 scheme, 상대·`//` 경로, 같은 출처, 루프백, 자격 증명이 든 주소).
- **계약 시험.** `/api/docs`·`/api/meta` 의 `markdown`. `page`·`frac` 없는 Markdown 줄 핀이 왕복하고, `pins.md` 에 `—` 로 찍힌다. 보낸 값이든 물려받은 값이든 쪽 필드가 Markdown 저장(만들기, 위치 편집, 메모만 고치는 편집)을 지나 남지 않는다(§결정 1). 같은 폴더의 `.tex` 와 `.md` 에서 두 문서의 이력이 섞이지 않는다. 원문 경로가 1 MiB를 넘으면 `413 source_too_large` 다. Markdown 줄 핀이 제안을 받고, 보기 전용·그림 문서는 여전히 거절한다. Markdown 판정 핀의 `superseded_by`. 직전 릴리스가 이런 레코드를 지우지 않는다.
- **보안 시험.** 스크립트·이벤트 처리기·`javascript:` 링크·원격 그림·원시 HTML 시험 문서가 무력하게 그려지고, 요청이 나가지 않는다. `ftp:`·임의 scheme·`data:image` 링크와 뷰어 자신의 API 주소가 열리지 않는다.
- **한도 시험.** 바이트 한도 경계(1 MiB와 1 MiB+1), 긴 한 줄, 구분자 폭탄(`*a`, `_a_`, `[`, `` ` ``, `<a`, `&amp;`), 깊은 목록과 인용(중첩 한도 직전·직후), 좁은 표와 넓은 표, 참조 정의 반복. 각각 2초 안에 그린 화면이나 원문 줄 보기가 나오고, 그린 요소가 한도 아래이며, 모든 원문 줄이 `data-line` 이나 `data-lo..hi` 안에 있거나 알림이 원문 줄 보기를 말한다. CSP가 걸린 뒤 PDF 화면의 기존 시험이 그대로 통과한다.
- **뷰어.** pick·표시·작성 패널·제안·판정·목록 순서의 동작 시험. PDF 화면의 기존 가드는 그대로 통과한다. 네 기기군 PoC를 보인다.
