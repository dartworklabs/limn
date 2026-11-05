# Markdown 머리 정보와 수식 글자 구현 계획

범위: [승인된 설계](../specs/2026-11-05-more-line-formats.md), [ADR-0032](../../adr/0032-markdown-front-matter.md)의 D1–D9. 출발점은 PoC 브랜치 `poc/line-formats` 의 열 커밋(파싱 worker의 규칙 셋, Markdown 화면의 상자 둘과 인라인 수식, 순수·브라우저 시험)이고, 같은 브랜치를 `origin/main`(92e6c0dd) 위로 옮겨 문서와 계약 시험을 더해 구현으로 만든다. 서버 코드는 바꾸지 않는다.

각 시험 묶음은 그 기능 줄을 되돌리면 실패해야 한다. 묶음마다 변이 하나를 적는다.

## Task 1: 브랜치와 승인 기록

- [x] Step 1: `origin/main`(92e6c0dd, #413·#421 포함) 위로 리베이스한다. Expected: 충돌 없음, PoC 열 커밋이 그대로 위에 선다. #420(Markdown 본문의 숨은 문자 표시)은 아직 `main` 에 없다.
- [x] Step 2: ADR-0032를 `승인됨` 으로 올리고(결정일·결정자·승인한 결정, D1–D9의 상태), 설계 머리에 승인을 적는다. `docs/adr/index.md` 의 0032 행과 ADR-0025 행의 후속 관계를 고친다. 코드와 시험 주석의 `ADR-0032 제안` 을 `ADR-0032` 로. Expected: `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 가 `A` 한 줄이다.

## Task 2: 계약 시험

- [x] Step 1: 계약 스냅숏 `tests/data/contract_snapshot_markdown_dialect.json`(`MarkdownDialectContractSnapshot`). 머리 정보와 따로 선 수식이 있는 `.md` 에서 서버가 그대로 보내는 원문 줄, page 필드를 보낸 YAML 줄 핀, `md:front`·`md:math` 블록 핀, 수식의 TeX를 바꾸는 제안, 머리 정보 블록으로 옮기는 위치 편집과 메모 편집, 버리기와 휴지통, `pins.md`·핀 목록·제안 핀. Expected: 두 `kind` 가 보낸 그대로 저장·응답되고 범위 칸에 찍히며, page 필드가 없다. 다른 스냅숏은 바이트 그대로다.
- [x] Step 2: 직전 릴리스 되돌림 `tests/contracts/test_markdown_dialect_rollback.py`(v0.4.51). 말뭉치 `tests/data/pin_records.jsonl` 에 그 흐름이 저장한 레코드 넷(휴지통 사본 포함)을 더했다. v0.4.51이 깨진 줄 없이 읽고 두 파일을 바이트 그대로 되쓰며 `range_label` 이 각 `kind` 다. 변이: 머리 정보 레코드에 `"page": null` → 말뭉치 시험과 v0.4.51의 읽기가 모두 실패.
- [x] Step 3: `tests/architecture/test_markdown_kinds.py`. `md-surface.js` 의 `MD_BLOCK_KINDS` 로 저장하는 모든 `md:<블록>` 과 `md:section` 이 api.md(값 목록과 레코드 스키마의 `kind` 행)·viewer.md·SKILL 두 벌에 있다. 변이: SKILL.ko.md에서 두 값을 빼면 실패.

## Task 3: 브라우저 시험

- [x] Step 1: 한도(`Limits`)에 여섯 경우. 줄 보기 한도 가까이(45,000줄)의 머리 정보와 따로 선 수식은 그려지고, 40,000줄과 그 뒤의 강조는 요소 한도를 넘어 원문 줄로 보이며, 닫는 기호 없는 `\(` 10만 개와 `\[` 줄 8,000개는 시간 안에 읽힌다. 변이: `mdFront`·`mdMath` 의 줄 span을 `mdEl` 대신 `createElement` 로 → 요소 6만 2천 개로 두 경우 실패.
- [x] Step 2: PoC의 `FrontMatter`·`Math`(상자·서버의 줄·목차·사다리·`quote`·저장한 `md:front`·`md:math`·`pins.md`)와 순수 시험(`FrontMatterRule`·`MathRule`)은 그대로 통과한다.

## Task 4: 문서 동기화

- [x] Step 1: Handbook `api`(값 목록, 두 값의 뜻, 레코드 스키마, `pins.md` 범위 칸, 되돌리기)·`viewer`(§그리기의 머리 정보와 수식, §줄 대응의 수식 조각, §한도, §고르기와 범위 사다리, §시험, 알려진 제약)·`purpose`·`domain`·`verification`, `index.md` 의 파일 지도. 사다리 블록 칸의 설명(`core.js`, `ui_en.json`)에 머리 정보와 수식.
- [x] Step 2: `skill/SKILL.md`·`skill/SKILL.ko.md`(두 값과 그때 고칠 것), CHANGELOG `Unreleased`.

## Task 5: 검증과 PoC

- [x] Step 1: ruff check·format, mypy 두 플랫폼, `npm run typecheck`, strict ratchet, `pytest -n 4 -m "not browser and not tex"`, `tests/architecture`, `test_viewer_markdown*.py`, `test_md_surface.py`, 계약·되돌림 시험. 브라우저는 `-n 4` 까지, 실패는 혼자 다시 돌린 뒤 판단한다.
- [x] Step 2: `systemctl --user restart limn-poc-formats` 뒤 테일넷 주소가 200으로 답한다.

## 열린 것

- **숨은 문자 표시와 합치기(설계 §결정 10).** #420(Markdown 본문의 숨은 문자 표시)이 `main` 에 들어오면 머리 정보 상자(`mdFront`)의 줄과 인라인·따로 선 수식의 글을 그 길(`ccBox`·`ccHtml`)로 넣고, 그 없이는 실패하는 브라우저 시험을 더한다. 이 브랜치를 리베이스할 때 #420은 아직 머지되지 않았다.
- **네 기기군 실측.** PoC 화면을 소유자가 보았다. 구현은 화면을 바꾸지 않았다(사다리 설명 문구만).
