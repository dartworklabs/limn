# 텍스트·코드 문서 구현 계획

범위: [승인된 설계](../specs/2026-11-05-text-documents.md), [ADR-0029](../../adr/0029-text-documents.md)의 D1–D8. 출발점은 PoC 브랜치 `poc/md-text-docs` 의 다섯 커밋이고, 이를 `origin/main`(190c4500) 위로 옮긴 `feat/text-documents` 에서 시험과 문서를 더해 구현으로 만든다. 서버·뷰어 코드는 PoC 그대로 두고, 시험이 드러낸 결함만 고친다.

각 시험 묶음은 그 기능 줄을 되돌리면 실패해야 한다. 묶음마다 변이 하나를 적는다.

## Task 1: 브랜치와 승인 기록

- [x] Step 1: `origin/main` 위로 리베이스하고 브랜치 이름을 `feat/text-documents` 로 바꾼다. Expected: 충돌 없음, PoC 다섯 커밋이 그대로 위에 선다.
- [x] Step 2: ADR-0029를 `승인됨` 으로 올리고(결정일·결정자, 결정마다의 상태), 설계 머리에 승인을 적는다. D7의 `pins.md` 숨은 문자 줄과 D8의 `line_ends` 는 승인 질문 뒤 더한 것이라 마지막 PoC에서 확인한다고 둘 다에 적는다. `docs/adr/index.md` 의 행과 ADR-0011·0020·0025 행의 후속 관계를 고친다. Expected: `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 가 `A` 한 줄이다.

## Task 2: 서버 계약 시험

- [ ] Step 1: 텍스트 계약 스냅숏 `tests/data/contract_snapshot_text.json`(`TextContractSnapshot`). `--doc` 이 고른 `.py` 텍스트 문서와 LaTeX 문서에서 `/api/docs`·`/api/meta` 의 `kind:"text"`, 습관처럼 page 필드를 보낸 줄 핀, 문단(`para`)·들여쓰기 블록(`indent`) 핀, 숨은 문자를 더하는 제안, 위치 편집과 메모 편집, 판정 핀, 버리기와 휴지통, `pins.md`·핀 목록. Expected: 어느 답에도 page 필드가 없고 `pins.md` 는 `—`·`indent`·`— 텍스트(쪽 없음)`·숨은 문자 줄을 찍는다. 변이: `pins.md` 꼬리말을 `Markdown(쪽 없음)` 으로 되돌린다.
- [ ] Step 2: 텍스트 핀 쓰기 시험 `pins/editing/tests/test_text_pins.py`. `kind`/`scope` `indent` 가 만들기·위치 편집·메모 편집을 지나 저장 파일과 답에 그대로 남고, page·frac·pdf_build 는 저장되지 않으며, 제안 수정을 받고, 판정 핀의 대상이 그 줄이다. Expected: 변이 `SCOPES` 에서 `indent` 빼기 → 400 `bad_scope`; `renders_in_browser` 에서 `text` 빼기 → page 필드가 저장된다; `takes_suggestions` 에서 `text` 빼기 → 400 `suggest_unsupported`.
- [ ] Step 3: 원문 경로. Markdown의 `SourceRoute` 를 텍스트 문서로 한 번 더 돌린다(줄, `line_ends`, 1 MiB와 413, UTF-8 아님, 거절). Expected: 변이 `rendersInBrowser`(서버)에서 `text` 빼기 → 400 `not_rendered_in_browser`.
- [ ] Step 4: 변경 보기. 한 폴더의 `main.tex`·`plan.md`·`plan.txt` 와 `refs.bib`: 텍스트 문서의 이력은 제 파일 하나이고, `.tex`·`.md` 문서의 이력과 섞이지 않으며, 핀이 제 hunk만 본다. `.bib` 텍스트 문서는 제 파일만 보고, LaTeX 문서의 이력은 지금처럼 `.bib` 를 넣는다. Expected: 변이 `history_files` 의 `renders_in_browser` 가지를 Markdown으로 좁히기 → 텍스트 이력에 `.tex` 커밋이 섞인다.
- [ ] Step 5: 직전 릴리스 되돌림 `tests/contracts/test_text_rollback.py`(v0.4.50, `test_markdown_rollback.py` 와 같은 방식). 말뭉치 `tests/data/pin_records.jsonl` 에 텍스트 레코드(`indent`, `para`, 제안, 휴지통 사본)를 더한다. Expected: v0.4.50의 저장소가 모든 텍스트 레코드를 읽고 두 파일을 바이트 그대로 다시 쓴다. 변이: 말뭉치 레코드의 `lo` 를 문자열로 바꾸면 옛 레코드 검사가 그 줄을 깨진 줄로 센다.

## Task 3: 브라우저 시험

- [ ] Step 1: 고르기. 마우스 누르기(그 줄, 기본 단 `raw`), 끌기(덮은 줄들), 손가락 누르기, 길게 누르기에 해당하는 선택(손잡이로 만든 선택이 멈춘 뒤 0.5초). 저장한 핀에 page 필드가 없다. Expected: 변이 `mdPick` 의 `!isTextDoc()` 빼기 → 누르기가 문단을 고른다.
- [ ] Step 2: 사다리. 함수 머리 줄의 세 단(고른 줄, 문단, 들여쓰기 블록), 짧은 쪽이 먼저, 같은 범위는 합친다, 두 문단에 걸친 선택은 `문단 2개` 이고 줄로 저장한다, 블록을 고르면 `indent` 로 저장한다. Expected: 변이 `kindFor` 의 `indent` 가지 빼기 → 저장된 `kind` 가 `lines`.
- [ ] Step 3: 344px 폴더블 바깥 화면에서 쪽이 옆으로 넘어가지 않는다(긴 줄, 탭, 긴 토큰). Expected: 변이 `.md.tx .ln` 의 `white-space:pre-wrap` 을 `pre` 로 → 가로 넘김.
- [ ] Step 4: 원문이 바뀌면 다시 그리고 읽던 줄을 지킨다. Expected: 변이 텍스트 가지의 `mdShow` 를 첫 그리기에만 → 새 글이 보이지 않는다.
- [ ] Step 5: 제안 편집 칸 아래 경고: U+202E를 더하는 초안. Expected: 변이 `sg-cc-warn` 토글 빼기 → 경고색이 없다.
- [ ] Step 6: Firefox 변형. 고르기·사다리 묶음과 숨은 문자 표시를 Firefox에서 한 번 더 돌린다(엔진 표시 클래스).

## Task 4: 문서 동기화

- [ ] Step 1: Handbook `purpose`·`domain`·`viewer`·`api`·`instances`·`operations`·`architecture`(해당할 때)와 `index.md` 의 파일 지도에 새 파일(`text-surface.js`·`text-surface.css`·`hidden-chars.js`, 시험)을 더한다. topic은 현재형으로 쓰고 날짜를 넣지 않는다. Expected: `make handbook-check` 에 해당하는 검사와 `tests/architecture/test_handbook_refs.py` 통과.
- [ ] Step 2: `skill/SKILL.md`·`skill/SKILL.ko.md`(종류 `text`, `scope` `indent`, `pins.md` 숨은 문자 줄, `limn doc add` 가 받는 파일), README 두 벌(지원 문서 목록), CHANGELOG `Unreleased`.

## Task 5: 검증과 PoC

- [ ] Step 1: ruff check·format, mypy 두 플랫폼, `npm run typecheck`, strict ratchet, boundaries, `pytest -n 4 -m "not browser and not tex"`, `tests/architecture`, 인스턴스 셸 시험, `test_viewer_markdown*.py`, 새·바꾼 브라우저 시험, 건드린 제안·작성 패널·발췌·대비 브라우저 파일. 브라우저는 `-n 4` 까지, 실패는 혼자 다시 돌린 뒤 판단한다.
- [ ] Step 2: `systemctl --user restart limn-poc-text` 뒤 테일넷 주소가 200으로 답한다.

## 후속(이 브랜치 밖)

- **Markdown 화면 자체의 숨은 문자 표시.** 지금은 Markdown 문서의 원문 발췌·사다리 이름·제안 차이·변경 보기·인용 줄만 표시하고, Markdown 화면이 그린 글(`md-surface.js` 의 렌더러)은 표시하지 않는다. 형제 브랜치 `poc/md-assets` 가 `md-surface.js` 를 바꾸고 있어 이 브랜치는 `md-surface.js` 의 변경을 텍스트 가지 여섯 곳으로 줄였다. 두 기능이 모두 머지된 뒤 따로 한다.
