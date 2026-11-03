# HTML 문서 화면 — Markdown 등 줄 단위 원문 (보류 제안, 개정 1)

> **상태: 보류. 승인되지 않았고 구현하지 않는다.**
>
> - 2026-10-24: 소유자가 지금은 LaTeX만 유지하기로 했다("일단은 tex 만 하자"). 이 계획을 구체적으로 적어 공동 관리자 검토에 넘기라고 했다([이슈 #255](https://github.com/dartworklabs/limn/issues/255)). 검토 의견은 아직 없다.
> - 2026-11-04 개정 1: 초판은 0.4.23 무렵에 썼다. 그 뒤 들어온 제안 수정·판정 핀·댓글 타임라인 등을 반영해 현재 `main`(0.4.45)과 다시 대조했다. 일곱 결정에 추천안을 달고, 소유자가 방향을 만져 볼 수 있는 버리는 PoC(`poc/html-surface` 브랜치)를 만들었다. 결정 초안은 [ADR-0025](../../adr/0025-html-document-surface.md)(`제안`)다.
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

초판 뒤 `main` 에 354개 커밋이 들어왔다(0.4.23 → 0.4.45). 아래 근거는 모두 `main` b13aa8c0의 `src/limn/` 기준 경로와 줄이다.

### 그대로 맞는 것

- 문서의 행동은 능력으로 갈린다. `builds_from_source`·`watches_files`·`takes_line_pins`·`shows_revisions`·`view_only`·`has_element_map`(`runtime/documents.py:298-336`)이 있고, 문서 종류는 확장자로 한 번 정한다(`administration/serve_documents.py:256-266`).
- 제안 수정의 관문은 `builds_from_source`, 곧 "LaTeX인가"로 열린다. 근거는 `pins/editing/rules.py:686-692`의 `check_suggestion(latex)`, `pins/editing/service.py:79`, `pins/editing/http.py:85`, `SuggestFacts.latex`(`rules.py:525-532`)다. 뷰어 쪽은 `suggestOff`(`viewer/js/suggest.js:32`)이고, [api.md](../../handbook/api.md) §받는 핀과 한도에도 "LaTeX 문서(`kind:"tex"`)의 줄 핀만 받는다"고 적혀 있다.
- 변경 보기의 pathspec은 `tex`·`bib`·`sty`·`cls`·`bst` 뿐이다(`revisions/core.py:424-426`).
- 서버의 줄 번호는 `str.splitlines()` 로 센다(`platform/files.py:207`, `tex_lines` `:286`).
- 서버 런타임은 표준 라이브러리만 쓰고, 번들을 더하는 것은 멈춤 신호다([architecture.md](../../handbook/architecture.md) §불변식 2, §멈춤 신호).

### 낡은 것

| 초판의 서술 | 지금 | 근거 |
| --- | --- | --- |
| "가지는 능력에 묻고 종류에 묻지 않는다" | 판정 핀이 들어오며 종류를 직접 묻는 곳이 생겼다. 새 종류를 더하면 이 자리들이 조용히 틀린다 | `pins/runtime.py:273-280`(`doc.kind == "tex"`·`"pdf"`), `pins/verdict.py:84`(`TargetKind`), `:191-200`, 뷰어 `verdict.js:76`·`:92`(`kind!==DOC_KIND.PDF`) |
| `page`/`frac` 없는 줄 핀을 위해 `pins/model.py`·`pins/record.py` 를 고친다 | 저장과 읽기는 이미 받는다. 막는 곳은 만드는 길이다 | 레코드 검사는 `page` 가 있을 때만 정수인지 본다(`pins/record.py:92`). 모델도 선택 필드다(`pins/model.py:379`). 반면 `parse_loc` 는 `page` 기본값 1을 넣고(`pins/editing/location.py:200`), `to_record` 는 늘 쓰며(`:51`), 편집의 `LinePlace` 는 `page` 를 요구한다(`pins/editing/rules.py:142-154`) |
| `builds/document_facts.py` 를 고친다 | 필요 없다. Markdown 문서는 쪽 사실을 묻지 않는다 | PoC에서 고치지 않았다 |
| 원문 서빙과 변경 감시를 위해 `documents/`·`builds/` 에 감시를 더한다 | 감시 스레드가 필요 없다. 빌드하지 않는 문서의 `src_mtime` 은 이미 그 파일 자체의 시각이고, 가벼운 meta 폴링이 그 값을 싣는다 | `builds/artifacts.py:409`, `viewer/js/polling.js:45-50`. PoC는 원문이 바뀌면 다시 그린다 |
| pick을 위해 `pins/location/`(`compute_levels`, `resolve.py`)을 고친다 | Markdown의 pick은 뷰어 안에서 끝난다. 서버는 저장할 때 `lo..hi` 만 확인한다(`parse_loc`). 사다리의 블록·절은 파서의 줄 지도에서 나온다 | PoC가 `/api/pick` 없이 저장한다. 에이전트는 pick을 쓰지 않고 `file`·`lo`·`hi` 로 바로 핀을 만든다 |
| `apart_paths` 를 고친다 | 필요 없다. LaTeX 문서의 원천 목록은 `SRC_TEX_EXTS` 만 보므로 `.md` 를 떼어 둘 일이 없다 | `runtime/documents.py:141-174`, `builds/artifacts.py:64` |
| 뷰어는 `pdf-open.js` 등 아홉 파일이 PDF 중심이다 | 쪽을 전제한 코드가 더 늘었다. 쪽 판정 줄·쪽 판정 패널(`verdict.js`·`verdict-reason.js`·`verdict-panel.js`), 비교 PDF 확대(`revision-zoom.js`), 목록의 `쪽순`(`list.js:161-163`)이다. 뷰어 JS는 6,225줄에서 10,839줄이 되었다 | `git show v0.4.23` 과 `main` 의 `viewer/js` 줄 수 |

### 새로 지나야 하는 길

초판에 없던 길이다. Markdown 화면이 지나가야 한다.

| 길 | 무엇이 걸리나 | 근거 |
| --- | --- | --- |
| 시작할 때의 빌드 | 소스 빌드도 지도도 아닌 문서는 모두 "보기 전용 PDF 렌더"로 떨어진다. `.md` 는 `pdfinfo` 가 실패해 빌드 실패로 표시된다(PoC에서 재현) | `builds/run.py:51-58`(`needs_build`), `builds/service.py:79-86`(`build_step` 의 마지막 가지) |
| 판정 핀 ([ADR-0021](../../adr/0021-verdict-pins.md)–[0023](../../adr/0023-superseded-verdict-field.md)) | 서버의 대상 계산이 종류 `tex` 만 줄 대상으로 놓는다. `markdown` 은 `file` 없이 넘어가 대상이 없어지고, `superseded_by` 가 조용히 빠진다. 뷰어의 `verdictTargetOf` 도 같다. 쪽 판정 줄과 쪽 판정 패널은 쪽이 없는 문서에서 숨겨야 한다. 판정 낱말 파일의 이름은 `<stem>.limnverdicts.json` 이라 그대로 된다 | `pins/runtime.py:273-280`, `pins/verdict.py:176-207`, `verdict.js:76-95`, `documents/verdicts.py:195-199` |
| 제안 수정 ([ADR-0020](../../adr/0020-suggested-edit-pins.md), [ADR-0024](../../adr/0024-suggested-edit-obvious-errors.md)) | 관문을 능력으로 옮긴다(§결정 3). `suggest_state`·`## 제안 문안`·원문 대조는 파일 종류를 가리지 않는다. PoC의 `fixture.md` 핀이 "바꿀 준비됨"으로 나왔다. ADR-0024의 "앞뒤 글과 대조한 명백한 오류"에는 Markdown 문법을 깨는 글도 든다. 표의 칸 수가 어긋나거나, 강조·코드 표시가 닫히지 않거나, 목록 들여쓰기가 틀린 경우다. SKILL 예시에 더한다(규칙은 그대로) | `pins/editing/rules.py:686-692`, `pins/listing/render.py` §제안 문안 |
| 댓글 타임라인·목록 순서 (0.4.42) | 카드의 타임라인은 문서 종류를 가리지 않는다. 목록의 `쪽순` 은 `page` 로 먼저 정렬하므로 `page` 없는 핀은 줄로만 정렬해야 한다. 저장 응답을 잃었을 때 되찾는 길은 `p.page===d.page` 로 핀을 찾는다 | `list.js:161-163`, `save.js:96`, `cards.js:64`(카드의 `N쪽`) |
| 능력의 전달 | 뷰어는 `/api/docs` 의 `kind` 에서 능력을 한 곳에서 계산한다(`isFigureKind`·`buildsFromSource`). 같은 자리에 `rendersInBrowser` 를 둔다. API에 능력 필드를 따로 더하지 않는다(§결정 3) | `viewer/js/core.js:60-64` |
| 변경 보기 ([ADR-0005](../../adr/0005-pin-scoped-changes.md), [ADR-0014](../../adr/0014-two-commit-comparison.md)) | pathspec에 `md` 를 더한다. 핀 단위 hunk는 `splitlines` 줄 번호와 git 줄 번호를 이미 맞춘다. 비교 PDF(latexdiff)는 Markdown에서 돌리지 않으므로 소스 diff만 연다 | `revisions/core.py:424-426`, `revisions/scope.py:252-264` |
| `pins.md` | 쪽 칸이 `r.get("page", 0)` 이라 `page` 없는 핀은 `0`, PoC처럼 기본값 1을 저장하면 `1` 이 찍힌다. 절 제목에 문서 종류 꼬리말이 없다. `기준:` 줄은 빌드가 없어 빠진다. 범위 칸은 모르는 `scope` 이면 `kind` 를 싣는다 | `pins/listing/render.py:694`, `:812-819`, `:169-182` |
| 되돌리기 계약 | 옛 서버(≤0.4.45)는 `.md` 문서가 있는 설정으로는 시작하지 않는다(`DocKindUnknown`). 인스턴스 셸도 거절한다. 그래서 되돌리려면 먼저 그 문서를 설정에서 뺀다. 상태 폴더는 그대로 읽힌다. Markdown 핀은 평범한 줄 핀이고, 설정에 없는 문서의 핀은 `## 설정에 없는 문서` 절로 간다. 새 `scope`·`kind` 값은 레코드 검사(문자열인지만 본다)를 지난다 | `administration/serve_documents.py:265`, `administration/instance_documents.sh:63`, `pins/record.py:128`, `pins/listing/render.py:821-829`. 선례: `tests/contracts/test_suggest_rollback.py` |
| 읽기 권한 | 새 읽기 경로는 등록 전까지 거부된다(닫힌 기본값). 원문 경로와 `/vendor/markdown-it/` 을 선언해야 한다 | `security/access.py:645-670`, `:689` |
| 보안 헤더 | 뷰어 페이지의 CSP는 `frame-ancestors 'none'` 뿐이고, 인라인 스크립트를 막지 않는다. 같은 출처에서 남이 쓴 글을 그리게 되므로 렌더러의 규율에만 기대게 된다(§결정 5) | `web/handler.py:141-148` |

### 쉬워진 것과 어려워진 것

**쉬워진 것.**

- 그림 문서([ADR-0011](../../adr/0011-figure-documents.md))가 "latexmk로 빌드하지 않는데 줄 핀을 받는 문서"를 이미 만들어 두었다. 그래서 `doc_for_file`, `pins.md` 의 문서별 절, 값 목록을 늘리는 선례(D5)를 그대로 쓴다.
- 뷰어가 책임별 조각(`viewer/parts.txt`)으로 나뉘어 있고, `innerHTML` 을 쓰는 곳은 `markup.js:43` 한 곳뿐이다. PoC는 새 조각 하나(`md-surface.js` 207줄, `md-surface.css` 58줄)와 기존 JS 조각 열하나에 걸친 연결 스무 줄로 화면을 붙였다. 서버 쪽은 Python 63줄을 더하고 11줄을 바꿨다.
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
| 1 | 핀 위치 모델 | Markdown 줄 핀은 `page`·`frac`·`pdf_build` 를 저장하지 않는다. `pins.md` 쪽 칸은 `—` 로 쓴다 | 예 — 저장 형식과 `pins.md` 표시 |
| 2 | 종류 값 | 문서 `kind` 에 `markdown` 을 더한다. `scope` 에 `block`·`section`, 핀 `kind` 에 `md:<블록>`·`md:section` 을 더한다(ADR-0011 D5 선례) | 아니오 — 선례를 따르는 덧셈. ADR과 함께 승인 |
| 3 | 능력으로 판단 | `renders_in_browser`·`takes_suggestions` 를 더하고, 판정 대상 계산과 시작 빌드에 남은 종류 비교를 능력으로 바꾼다. API에 능력 필드는 더하지 않는다 | 아니오 — 내부 구조 |
| 4 | 파서 | markdown-it(ESM 브라우저 빌드)을 뷰어에 번들한다. Markdown 문서를 열 때만 불러오고, 토큰을 직접 DOM으로 짓는다. 서버는 Markdown을 파싱하지 않는다 | 예 — 멈춤 신호(번들 추가) |
| 5 | 보안 | DOM API로만 짓는다. 원시 HTML은 그리지 않는다. 링크는 `http(s)`·`mailto`·문서 안 `#제목` 만 열고, 그림은 불러오지 않는다. 앞서 뷰어 페이지에 `script-src` CSP를 붙인다 | 예 — 보안 경계와 제품 영향 |
| 6 | 줄 나누기 일치 | 서버가 나눈 줄을 그대로 보내고, 뷰어는 `\n` 으로 이어 파싱할 뿐 원문 바이트를 다시 나누지 않는다 | 아니오 — 구성으로 같다 |
| 7 | 뷰어 구조 | 같은 탭·패널·목록·작성 패널 뒤에 두 번째 문서 영역을 둔다. 쪽 전용 조작은 숨긴다. 글을 끌면 줄, 블록을 누르면 블록을 고른다 | 부분 — 조작과 모양은 PoC로 소유자가 본다 |

### 결정 1. 핀 위치 모델

**추천.** Markdown 문서의 줄 핀은 `file`·`lo`·`hi`·`kind`·`scope`·`quote`(와 `raw_lo`·`raw_hi`)만 가진다. `page`·`frac`·`pdf_build` 는 저장하지 않는다. 표시는 그린 블록 위에 `lo..hi` 로 한다.

**근거.**

- 읽기 쪽은 이미 `page` 없는 줄 핀을 받는다(`pins/record.py:92`, `pins/model.py:379`). 옛 서버로 되돌려도 레코드가 깨지지 않는다.
- `page: 1` 을 저장하는 길(PoC가 기본값 때문에 그렇게 했다)은 코드가 가장 적다. 그러나 `pins.md` 의 쪽 칸에 거짓 `1` 이 찍히고(PoC의 `pins.md`), 에이전트 계약에 뜻 없는 값이 남는다. 한번 퍼진 값은 되돌리기 어렵다.

**바꿀 곳.**

- `parse_loc` 는 `renders_in_browser` 문서에서 `page`·`frac`·`pdf_build` 를 받아도 버린다. 그림 문서가 아닌 곳의 `el` 을 버리는 선례를 따른다. 에이전트가 습관처럼 `page: 1` 을 보내도 실패하지 않게 하려는 것이다(`pins/editing/location.py:200`, `:51`).
- `LinePlace` 는 그런 문서에서 `page` 를 요구하지 않는다(`pins/editing/rules.py:142-154`).
- `pins.md` 의 쪽 칸은 `page` 가 없는 줄 핀에 `—` 를 쓴다(`pins/listing/render.py:694`). 지금은 `0` 이다.
- 뷰어는 카드의 `N쪽`(`cards.js:64`), `쪽순`(`list.js:161-163`), 응답을 잃은 저장 되찾기(`save.js:96`)를 `page` 없이도 맞게 고친다.

**대안.** 블록 번호를 저장하는 안은 편집에 살아남지 못해 기각했다. 새 위치 필드를 더하는 안은 줄 범위로 충분해서 기각했다.

### 결정 2. 종류 값과 옛 에이전트

**추천.** `/api/docs`·`/api/meta` 의 `kind` 에 `markdown` 을 더한다. 사다리 값은 `scope` `block`·`section`(`levels[].level` 도 같다)이고, 핀 `kind` 는 `md:paragraph`·`md:item`·`md:table`·`md:code`·`md:quote`·`md:html`·`md:section` 이다. 옛 핀의 `kind` 값 `block`(환경 블록)과 겹치지 않게 접두를 붙인다.

**근거.** ADR-0011 D5가 값 목록을 한 변경에서 늘린 선례다. 레코드 검사는 문자열인지만 보고(`pins/record.py:128`), `pins.md` 범위 칸은 모르는 `scope` 이면 `kind` 를 싣는다(`render.py:169-182`). 옛 에이전트는 SKILL의 "`kind:"tex"` 만 재빌드" 규칙을 따르는데, Markdown은 재빌드가 필요 없으므로 결과가 맞다. 확장자는 1단계에서 `.md` 하나만 받는다.

### 결정 3. 종류가 아니라 능력으로

**추천.**

- `Doc` 에 `renders_in_browser`(HTML 화면)와 `takes_suggestions`(LaTeX·Markdown)를 더한다. Markdown은 `takes_line_pins` 가 참, `builds_from_source`·`watches_files`·`has_element_map` 이 거짓이다. `shows_revisions` 는 변경 보기를 붙이는 단계에서 참이 된다.
- 제안 관문(`check_suggestion` 과 그 호출자, `suggestOff`)을 `takes_suggestions` 로 옮긴다.
- 판정 대상 계산(`pins/runtime.py:273-280`, `pins/verdict.py:84`·`:191-200`, `verdict.js:76`·`:92`)의 "줄 대상" 조건을 `kind == "tex"` 에서 "줄 핀을 받고 요소 지도가 없는 문서"로 바꾼다.
- 시작 빌드(`builds/run.py:51-58`, `builds/service.py:79-86`)는 `renders_in_browser` 문서를 건너뛴다.
- 뷰어는 `core.js` 의 종류 → 능력 함수 자리에 `rendersInBrowser` 를 더한다. 뷰어와 서버는 늘 같은 판이므로 API에 능력 필드를 따로 싣지 않는다.

### 결정 4. Markdown 파서

**추천.** markdown-it을 `src/limn/vendor/markdown-it/` 에 번들한다. PoC는 15.0.3 ESM 브라우저 빌드(`markdown-it.esm.min.mjs` 124,681바이트, MIT, 의존성 포함)를 썼다. 뷰어는 Markdown 문서를 열 때만 `import()` 로 불러온다. PDF.js가 `/vendor/pdfjs/` 로 서빙되는 방식과 같다.

**근거 (PoC로 확인).**

- 블록 토큰의 `map` 이 원문 줄 범위다. 문단·제목·목록 항목·표 행·코드 블록·인용·구분선에 다 붙는다.
- 문단 안에서는 `softbreak`·`hardbreak` 가 원문 줄의 경계다. 그래서 줄마다 `span[data-line]` 을 둘 수 있고, 문단 안의 한 줄만 골라도 그 줄이 핀이 된다. 코드 블록은 내용 줄을 하나씩 감싼다.
- 좁은 목록의 숨은 문단은 항목에 바로 그린다. 표 칸의 줄은 행으로 묶는다.
- 렌더러의 HTML 문자열은 쓰지 않는다. 토큰을 따라 `createElement`·`textContent` 로 짓는다(§결정 5).
- 서버는 Markdown을 파싱하지 않는다. 사다리의 블록·절도 뷰어가 줄 지도에서 계산한다. 서버는 저장할 때 `lo..hi` 가 파일 안인지만 본다.

**대안: 서버에서 표준 라이브러리로 렌더.** 번들은 없다. 대신 CommonMark 블록 규칙(게으른 이어짐, 목록 들여쓰기, setext 제목, 참조 링크 정의, HTML 블록, GFM 표)을 Limn이 소유하고 시험해야 한다. 게다가 GitHub 렌더와 경계 사례에서 어긋난다. 렌더 결과를 뷰어에 넣으려면 서버가 만든 HTML을 넣는 두 번째 sink나 별도 트리 형식도 필요하다.

**대안: 블록 경계만 손으로 나누고 글은 평문으로.** 코드는 가장 적다. 그러나 표·강조·목록 모양이 없어 "흐르는 글"을 읽는다는 목적에 못 미친다.

**소유자 몫.** 런타임 번들을 더하는 것은 멈춤 신호다. ADR-0025 D4가 이 결정이다.

### 결정 5. 보안

렌더한 문서는 뷰어와 같은 출처에서 사용자의 신원을 쓴다. 문서 안의 무엇도 스크립트가 되거나 API를 부르거나 밖으로 요청을 보내지 않아야 한다.

**추천.**

1. **DOM API로만 짓는다.** markdown-it의 `render()` 를 쓰지 않는다. `innerHTML` 을 쓰는 곳은 `markup.js:43` 하나로 남는다.
2. **원시 HTML은 그리지 않는다.** 파서는 원시 HTML을 별도 토큰으로 내도록 켜 두되(`html:true`), 블록은 줄 범위를 가진 자리표시("HTML N줄 · 그리지 않습니다"와 첫 줄)로, 인라인 태그는 코드 글자로 보인다. 자리표시도 줄 핀을 받는다. 원시 HTML을 끄면(`html:false`) 그 글이 문단 글자로 길게 풀린다. 실제 README 머리의 로고·배지 HTML이 그랬다(PoC 캡처).
3. **링크.** `http:`·`https:`·`mailto:` 만 새 탭(`rel="noopener noreferrer"`)으로 연다. `#제목` 은 문서 안의 그 제목으로 간다. 상대 경로는 1단계에서 열지 않는다(나중에 등록된 다른 문서로 이을 수 있다). 그 밖의 scheme은 markdown-it의 `validateLink` 가 이미 링크로 만들지 않는다.
4. **그림은 불러오지 않는다.** 대체 글로 보인다. 원격 그림은 누가 언제 문서를 열었는지와 IP를 제3자에게 알린다. 나중 단계에서도 원고 트리 안의 그림만, 검사된 읽기 경로로 연다.
5. **뷰어 페이지에 CSP를 붙인다.** 이것을 앞선 조건으로 둔다. 서버는 조립할 때 인라인 스크립트의 바이트를 알므로 `script-src 'self' 'sha256-…'`, `object-src 'none'`, `base-uri 'none'` 을 걸 수 있다. 뷰어는 인라인 이벤트 처리기 없이 `data-act` 로 나누므로 걸림돌이 적다. PDF.js worker와 사람 사진(`img-src`)은 실측해서 정한다. 보안 경계 변경이므로 Markdown 화면보다 먼저, 따로 승인받는다.
6. **원문 읽기는 크기를 제한한다.** 원문 경로는 검사된 원고 핸들의 제한 읽기(`read_bounded`)로 읽고, 한도를 넘으면 그리지 않는다.

**PoC로 확인한 것.** 시험 문서에 `<script>`, `onerror` 가 붙은 `<img>`, `javascript:` 링크, 원격 그림, 문서 밖 상대 링크를 넣었다. 그린 결과에 `script`·`img` 요소와 `on*` 속성이 하나도 없었고, `javascript:` href도 없었다. 원격 요청과 대화상자도 0건이었다(Chrome 156 자동화).

**소유자 몫.** 보안 경계가 바뀌고(CSP), README류 문서의 머리 HTML이 그려지지 않는 제품 영향이 있다. 대안은 허용 목록 소독기(DOMPurify 등)다. 번들이 하나 더 늘고 정책을 소유해야 해서 1단계에서는 추천하지 않는다.

### 결정 6. 줄 나누기 일치

**추천.** 서버가 줄의 권위다. 원문 경로는 `tex_lines`(`str.splitlines()`)로 나눈 줄 목록을 보낸다. 뷰어는 그것을 `\n` 으로 이어 파서에 넣을 뿐, 원문 바이트를 다시 나누지 않는다. 그래서 `\r\n`, 외톨이 `\r`, 폼 피드, `\v`, U+2028·U+2029, `\x1c`–`\x1e`, `\x85` 가 있어도 두 쪽의 줄 번호가 구성으로 같다. PoC가 이렇게 한다. 변경 보기는 `revisions/scope.py:252-264` 가 git 줄 번호와 맞춘다.

**검증.** 위 구분자를 모두 담은 시험 파일로 뷰어의 `data-line` 이 서버의 줄과 같은지 확인한다.

### 결정 7. 뷰어 구조

**추천 (PoC 구현).**

- **두 번째 문서 영역.** `#doc` 안에 흐르는 단 하나(`article#md`)를 그린다. 같은 탭·패널·목록·작성 패널·카드를 쓴다. 갈리는 곳은 `buildDoc`·`marks`·`jumpPin`·`pickOutline`·`vecOpen`·클릭으로 선택 취소(`pressOutsideSelection`)·meta 폴링이다.
- **숨기는 쪽 전용 조작.** 쪽 칸과 쪽 목록, PDF 확대(막대와 [더보기]), [선택] 모드, PDF 내려받기, 단 띠의 쪽 표시, Limn 찾기 칸, 변경 보기 전환(1단계는 붙일 때까지)이다. 브라우저의 찾기는 그대로 쓸 수 있다.
- **고르기.** 마우스로 글을 끌면 그 줄들이고, 사다리의 기본은 "고른 줄"이다. 블록을 누르면(마우스·손가락) 그 블록이고, 기본은 "블록"이다. 손가락으로 길게 눌러 손잡이로 고르면 선택이 멈춘 뒤 0.5초에 줄을 고른다. 고른 줄은 파란 바탕으로 보인다.
- **핀 표시.** 핀의 줄에 상태색 바탕을 깐다(열림 초록, 검토 대기 보라, 위치 잃음 주황). 표 칸의 줄은 행으로 묶는다. 첫 줄 높이에 맞춰 단의 왼쪽 여백에 번호 배지를 세우고, 누르면 카드로 간다(44px 누름 영역). 배지는 글 흐름 밖 층에 있어 글을 밀지 않고, 단 폭이 바뀌면 다시 놓인다.
- **목차.** 제목에서 만들고 오른쪽에 `L<줄>` 을 붙인다.
- **목록 순서.** `쪽순` 은 Markdown 문서에서 줄 순서다. 이름을 `위치순` 으로 바꿀지는 소유자가 정한다.
- **판정.** 쪽 판정 줄·쪽 판정 패널은 Markdown 문서에서 그리지 않는다. 판정 행은 줄 대상으로 동작한다(§결정 3).

PoC에서 드러난 남은 일: 휴대폰 시트 위치 단추가 쪽 수 대신 `−/−` 를 보인다. 첫 방문 안내 문구는 Markdown용으로 바꿨지만, 빈 목록의 도움말은 아직 PDF 문구다.

## 바꿀 곳 (개정 1)

| 영역 | 파일 (`main` 기준 줄) | 크기 |
| --- | --- | --- |
| 등록: `DocKind`, 능력, 확장자, 메시지, 시작 줄, 셸 검사 | `runtime/documents.py:40`·`:298-336`, `administration/serve_documents.py:256-266`·`:356-367`, `administration/instance_documents.sh:55-63` | 작음 |
| 시작 빌드 건너뛰기 | `builds/run.py:51-58`, `builds/service.py:79-86` | 작음 |
| 원문 경로(제한 읽기, 줄 목록)와 읽기 권한 | `documents/` 또는 `pins/location/`(PoC), `platform/files.py`, `security/access.py:645-670` | 작음, 계약(새 경로) |
| `page` 없는 Markdown 줄 핀 | `pins/editing/location.py:51`·`:200`, `pins/editing/rules.py:142-154`, `pins/listing/render.py:694` | 중간, 계약 |
| 사다리 값과 범위 칸 | `pins/editing/values.py:22-25`, `pins/listing/render.py:169-182` | 작음, 계약 |
| 제안 관문을 능력으로 | `pins/editing/rules.py:525-532`·`:686-692`, `pins/editing/service.py:79`, `pins/editing/http.py:85`, `viewer/js/suggest.js:32` | 작음, 계약(ADR-0020 D1 부분 대체) |
| 판정 대상의 종류 비교 제거 | `pins/runtime.py:273-280`, `pins/verdict.py:84`·`:191-200`, `viewer/js/verdict.js:76`·`:92`, 쪽 판정 화면 끄기 | 작음 |
| `pins.md` 문서 절 꼬리말 | `pins/listing/render.py:812-819` | 작음, 계약 |
| 변경 보기 | `revisions/core.py:424-426`, 비교 PDF 끄기, 뷰어는 소스 diff로 연다 | 작음~중간 |
| 번들과 서빙 | `src/limn/vendor/markdown-it/`, `THIRD_PARTY_NOTICES.md`, `viewer/assemble.py:44`, `viewer/routes.py:27-32`·`:98-101`, `viewer/application.py:32-38`, `security/access.py:689` | 작음, 멈춤 신호 |
| CSP | `web/handler.py:141-148`, `viewer/assemble.py`(인라인 스크립트 해시) | 작음, 보안 경계(앞선 조건) |
| 뷰어 HTML 화면 | 새 조각 `js/md-surface.js`·`css/md-surface.css`, `core.js`, `pages.js`, `list.js`, `outline.js`, `pdf-open.js`, `composer.js`, `cards.js`, `boot.js`, `selection.js`, `polling.js`, `levels.js`, `save.js` | 큼 |
| Handbook과 SKILL | `purpose.md`(범위), `architecture.md`, `domain.md`(능력 표), `api.md`(종류 값, `page` 없는 줄 핀, 제안 관문, 판정 대상), `viewer.md`, `instances.md`, `operations.md`, `build-sync.md`, `skill/SKILL.md`·`.ko.md` | 넓음 |
| 종류를 나열하는 시험 | `documents/tests/test_meta.py`, `administration/tests/test_serve_documents.py`, `runtime/tests/test_startup.py`, `administration/tests/test_instances.sh`, `viewer/tests/test_viewer.py`, 판정 시험, 계약 스냅숏 | 중간 |

## 버리는 PoC

`poc/html-surface` 브랜치에 있다. 소유자가 네 기기군에서 방향을 판단하라고 만든 것이고, 머지하지 않는다([workflow.md](../../handbook/workflow.md) §경로가 달라지는 경우의 탐색 규칙). 실행법과 시험 문서는 `tools/poc-html-surface/` 에 있다.

**보여 주는 것.**

- `.md` 등록, 흐르는 렌더, 블록과 줄마다의 원문 범위.
- 선택에서 줄 핀으로, 사다리, 작성 패널·카드·편집 카드·제안 수정(Markdown 원문 diff), 검토 대기 표시.
- `pins.md` 의 Markdown 핀, 제목 목차, 원문 변경 시 다시 그리기.
- 원시 HTML 자리표시와 보안 시험.

**지름길 (설계가 아니다).** `page: 1` 저장(결정 1과 다르다), 서버 쪽 능력 판단의 임시 분기, 찾기·변경 보기·비교 없음, 새 시험 없음. 원문 경로를 `pins/location/` 에 두었고 크기 제한이 없다. CSP도 없다.

**측정.** 기존 시험 중 구조 경계와 뷰어 조립 126건, mypy(167개 파일)가 PoC 브랜치에서 통과한다. 전체 시험은 돌리지 않았다.

## 이후 단계

1. 일반 텍스트와 소스 코드 파일을 같은 화면에(줄마다 또는 문단마다 블록 하나).
2. Markdown의 그린 화면 비교(두 판을 그리고 바뀐 블록 표시).
3. 원문 위치를 지키는 렌더러가 있는 다른 줄 단위 형식.
4. 원고 트리 안의 그림, 등록된 다른 Markdown 문서로 가는 상대 링크.

## 검증

- **순수 시험.** 서버와 뷰어의 줄 번호가 구분자 전부에서 같다. 사다리의 단계(블록 종류별, 좁은·넓은 목록, 중첩 목록, 표, 코드 블록, 절 경계). 선택 → 줄(끝이 다음 블록의 맨 앞에서 멈춘 선택 포함).
- **계약 시험.** `/api/docs`·`/api/meta` 의 `markdown`. `page`·`frac` 없는 Markdown 줄 핀이 왕복하고, `pins.md` 에 `—` 로 찍힌다. Markdown 줄 핀이 제안을 받고, 보기 전용·그림 문서는 여전히 거절한다. Markdown 판정 핀의 `superseded_by`. 직전 릴리스가 이런 레코드를 지우지 않는다.
- **보안 시험.** 스크립트·이벤트 처리기·`javascript:` 링크·원격 그림·원시 HTML 시험 문서가 무력하게 그려지고, 요청이 나가지 않는다. CSP가 걸린 뒤 PDF 화면의 기존 시험이 그대로 통과한다.
- **뷰어.** pick·표시·작성 패널·제안·판정·목록 순서의 동작 시험. PDF 화면의 기존 가드는 그대로 통과한다. 네 기기군 PoC를 보인다.
