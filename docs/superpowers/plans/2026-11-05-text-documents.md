# 텍스트·코드 문서 구현 계획

범위: [승인된 설계](../specs/2026-11-05-text-documents.md), [ADR-0029](../../adr/0029-text-documents.md)의 D1–D8. 출발점은 PoC 브랜치 `poc/md-text-docs` 의 다섯 커밋이고, 이를 `origin/main`(190c4500) 위로 옮긴 `feat/text-documents` 에서 시험과 문서를 더해 구현으로 만든다. 서버·뷰어 코드는 PoC 그대로 두고, 시험이 드러낸 결함만 고친다.

각 시험 묶음은 그 기능 줄을 되돌리면 실패해야 한다. 묶음마다 변이 하나를 적는다.

## Task 1: 브랜치와 승인 기록

- [x] Step 1: `origin/main` 위로 리베이스하고 브랜치 이름을 `feat/text-documents` 로 바꾼다. Expected: 충돌 없음, PoC 다섯 커밋이 그대로 위에 선다.
- [x] Step 2: ADR-0029를 `승인됨` 으로 올리고(결정일·결정자, 결정마다의 상태), 설계 머리에 승인을 적는다. D7의 `pins.md` 숨은 문자 줄과 D8의 `line_ends` 는 승인 질문 뒤 더한 것이라 마지막 PoC에서 확인한다고 둘 다에 적는다. `docs/adr/index.md` 의 행과 ADR-0011·0020·0025 행의 후속 관계를 고친다. Expected: `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 가 `A` 한 줄이다.

## Task 2: 서버 계약 시험

- [x] Step 1: 텍스트 계약 스냅숏 `tests/data/contract_snapshot_text.json`(`TextContractSnapshot`). `--doc` 이 고른 `.py` 텍스트 문서와 LaTeX 문서에서 `/api/docs` 의 `kind:"text"`, `/api/source` 의 `line_ends`(폼 피드 하나), 습관처럼 page 필드를 보낸 줄 핀, 문단(`para`)·들여쓰기 블록(`indent`) 핀, U+202E를 더하는 제안, 들여쓰기 블록으로 옮기는 위치 편집과 메모 편집, 버리기와 휴지통, `pins.md`·핀 목록. Expected: 어느 답에도 page 필드가 없고 `pins.md` 는 `—`·`indent`·`— 텍스트(쪽 없음)`·숨은 문자 줄을 찍는다. 변이: `pins.md` 의 숨은 문자 줄 빼기, `/api/source` 의 `line_ends` 빼기 → 실패.
- [x] Step 2: 텍스트 핀 쓰기 시험 `pins/editing/tests/test_text_pins.py`(8건). `kind`/`scope` `indent`·`para` 가 만들기·위치 편집·메모 편집을 지나 저장 파일과 답에 그대로 남고, page·frac·pdf_build 는 저장되지 않으며, `pins.md` 의 행과 소절 제목, `/api/docs`·`/api/meta` 의 `text`, 파일만 준 요청의 문서, 제안 수정, 판정 핀의 대상과 `figs/plot.limnverdicts.json`. 변이: `SCOPES` 에서 `indent` 빼기 → 위치 편집 실패; `renders_in_browser` 에서 `text` 빼기 → page 필드가 저장된다; `takes_suggestions` 에서 `text` 빼기 → 제안 거절; `pins.md` 꼬리말을 Markdown으로 → 실패.
- [x] Step 3: 원문 경로. `TextSourceRoute` 가 Markdown의 `SourceRoute` 를 텍스트 문서로 한 번 더 돌린다(줄과 `line_ends`, 1 MiB와 413, UTF-8 아님, 트리 밖 경로, 읽는 사람, 쓰기 없음). 변이: `renders_in_browser` 에서 `text` 빼기 → 400 `not_rendered_in_browser`.
- [x] Step 4: 변경 보기 `revisions/tests/test_text_revisions.py`(4건). 한 폴더의 `main.tex`·`plan.md`·`plan.txt`·`refs.bib`: `plan.txt` 의 이력은 제 커밋뿐이고 `.md`·`.tex` 문서와 섞이지 않으며, 핀이 제 hunk만 보고, 비교 PDF가 없다. `.bib` 텍스트 문서는 제 파일만 보고 LaTeX 문서의 이력은 지금처럼 `.bib` 를 넣는다. 변이: `history_files` 의 `renders_in_browser` 가지를 Markdown으로 좁히기 → 실패.
- [x] Step 5: 직전 릴리스 되돌림 `tests/contracts/test_text_rollback.py`(v0.4.50). 말뭉치 `tests/data/pin_records.jsonl` 에 계약 흐름이 저장한 텍스트 레코드 넷(휴지통 사본 포함)을 더했다. 변이: 텍스트 레코드에 `"page": null` 을 넣으면 v0.4.50의 레코드 검사가 그 줄을 깨진 줄로 세어 실패, `page`·`frac` 을 넣으면 말뭉치 시험이 실패.

## Task 3: 브라우저 시험

`src/limn/viewer/tests/test_viewer_text.py` 에 더했다. PoC의 9건(숨은 문자, 한도, 줄 끝, 제안)과 합쳐 24건이고 그중 4건이 Firefox다.

- [x] Step 1: 고르기(`Picking`). 마우스 누르기는 그 줄(기본 단 `raw`), 끌기는 덮은 줄들, 두 문단에 걸친 끌기는 `문단 2개` 와 줄 저장. 저장한 핀에 page 필드가 없고 `pins.md` 는 `—`·`indent`, 표시와 배지. 변이: `kindFor` 의 `indent` 가지 빼기 → 저장된 `kind` 가 `lines`. (`mdPick` 의 `!isTextDoc()` 는 텍스트 사다리에 `block` 단이 없어 되돌려도 결과가 같다. 막는 줄이 하나 더 있는 방어다.)
- [x] Step 2: 사다리. 반복문 머리 줄의 세 단(고른 줄, 블록 5–6, 문단 3–7), 짧은 쪽이 먼저, 같은 범위의 블록은 문단에 합친다. 변이: `mdLevels` 의 `txLevels` 가지 빼기 → 실패.
- [x] Step 3: 손가락(`Touch`). 누르기는 그 줄, 길게 누른 손잡이 선택은 0.5초 뒤 그 줄들, 빈 목록 도움말. 줄은 글자로 찾는다. 변이: 줄 span의 번호를 하나 밀기 → 실패(처음에는 `data-line` 으로 줄을 찾아 놓쳤고, 글자로 찾게 고쳤다); `txHint` 빼기 → 실패.
- [x] Step 4: 344px 폴더블 바깥 화면(`Width`)에서 쪽이 옆으로 넘어가지 않는다(300자 낱말, 탭 들여쓰기, 긴 한국어 줄), 탭 줄의 `--hang` 8. 변이: `.md.tx .ln` 의 `white-space:pre-wrap` 을 `pre` 로 → 실패.
- [x] Step 5: 원문이 바뀌면 다시 그리고 읽던 줄을 지킨다(`Redrawing`). 변이: 텍스트 가지의 `mdShow` 를 첫 그리기에만 → 실패.
- [x] Step 6: 제안 편집 칸 아래 경고: U+202E를 더하는 초안, 저장한 카드의 차이, `pins.md` 의 숨은 문자 줄. 변이: `sg-cc-warn` 토글 빼기 → 실패.
- [x] Step 7: Firefox 변형 `PickingFirefox`·`HiddenCharactersFirefox`. 숨은 문자 묶음의 변이: `CC_RANGES` 에서 U+202E 빼기 → 실패.

## Task 4: 문서 동기화

- [x] Step 1: Handbook `purpose`·`domain`(종류와 능력 표, 텍스트 문서와 그 사다리, 한계)·`viewer`(텍스트 화면, 숨은 문자, 제안 편집 칸 아래 줄, 변경 보기)·`api`(`/api/source` 의 `line_ends`, 문서 매개변수, 텍스트 문서의 핀, 판정 낱말 자리, 레코드 스키마, `pins.md` 의 텍스트 핀 행과 숨은 문자 줄)·`instances`·`operations`·`build-sync`·`architecture`·`verification`, `index.md` 의 목록과 파일 지도. `tests/architecture/test_handbook_refs.py` 통과. 출판 검사는 이 기계에 pandoc이 없어 Pandoc 파싱 단계만 돌지 못했고, 나머지 규약 검사는 통과했다.
- [x] Step 2: `skill/SKILL.md`·`skill/SKILL.ko.md`(종류 `text`, 텍스트 핀과 `indent`, `숨은 문자:` 줄이 붙은 제안은 넣기 전에 묻는다, `limn doc add` 가 받는 파일, 재빌드 없음), README 두 벌, CHANGELOG `Unreleased`.

## Task 5: 검증과 PoC

- [ ] Step 1: ruff check·format, mypy 두 플랫폼, `npm run typecheck`, strict ratchet, boundaries, `pytest -n 4 -m "not browser and not tex"`, `tests/architecture`, 인스턴스 셸 시험, `test_viewer_markdown*.py`, 새·바꾼 브라우저 시험, 건드린 제안·작성 패널·발췌·대비 브라우저 파일. 브라우저는 `-n 4` 까지, 실패는 혼자 다시 돌린 뒤 판단한다.
- [ ] Step 2: `systemctl --user restart limn-poc-text` 뒤 테일넷 주소가 200으로 답한다.

## 열린 것

- **`--main` 에 텍스트 파일.** `--main plot.py` 는 `.md` 처럼 거절하지 않고, 이 변경 전과 같이 LaTeX로 빌드하다 실패한다. 거절을 더하면 기동 규칙이 바뀌므로 이 브랜치에서는 손대지 않았다.
- **제안 거절 문장.** `suggest_unsupported` 의 문장은 여전히 `LaTeX·Markdown 문서의 줄 핀에만` 이다. 설계대로 에이전트가 읽는 문구를 바꾸지 않았다. `reason` 이 정본이다.
- **네 기기군 실측.** 마지막 PoC에서 소유자가 D7의 `pins.md` 숨은 문자 줄과 D8의 `line_ends` 를 함께 확인한다.

## 후속(이 브랜치 밖)

- **Markdown 화면 자체의 숨은 문자 표시.** 지금은 Markdown 문서의 원문 발췌·사다리 이름·제안 차이·변경 보기·인용 줄만 표시하고, Markdown 화면이 그린 글(`md-surface.js` 의 렌더러)은 표시하지 않는다. 형제 브랜치 `poc/md-assets` 가 `md-surface.js` 를 바꾸고 있어 이 브랜치는 `md-surface.js` 의 변경을 텍스트 가지 여섯 곳으로 줄였다. 두 기능이 모두 머지된 뒤 따로 한다.
