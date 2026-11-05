# Markdown 화면의 그림과 문서 사이 링크 — 구현 계획

범위: [승인된 설계](../specs/2026-11-05-markdown-images-links.md), [ADR-0030](../../adr/0030-markdown-tree-images-and-document-links.md). PoC 브랜치 `poc/md-assets` 를 `origin/main`(190c4500) 위로 옮겨 구현 브랜치 `feat/markdown-images-links` 로 이어 쓴다. 저장 형식·핀 레코드·`pins.md`·`/api/docs` 는 바꾸지 않는다. 형제 브랜치(일반 텍스트 문서)와 겹치지 않게 `md-surface.js` 는 그림·링크 부분만 고친다.

## Task 1: 서버 읽기 경로 `GET /api/asset`

- [x] 경로 규칙(`asset_path`), 형식 시그니처(`asset_kind`, SVG 머리의 선형 검사 `svg_head`), 8 MiB 제한 읽기(`read_asset`), 응답 정책(`ASSET_POLICY`)·CORP(`Reply.resource_policy`)·내용 ETag, `READ_PATHS` 등록. 검증: `test_assets.py` 의 `AssetPathRule`·`AssetKind`·`AssetRoute`(탈출 경로 전부, 상태 폴더, 특수 파일, 위장 내용, 8 MiB 경계, 역할, 쓰기 없음). PoC 커밋.
- [x] 화소 한도. 래스터 머리의 가로·세로(`raster_size`: PNG IHDR, GIF 화면과 첫 장면, JPEG 첫 SOFn, WebP VP8X·VP8·VP8L)가 8192×8192를 넘으면 413 `asset_too_many_pixels`, 머리에 크기가 없으면 415. 검증: `RasterSize` 두 시험, `test_the_pixel_limit_holds_at_its_edge_whatever_the_file_size`. 변이: 화소 비교를 `if False` 로 바꾸면 경계 시험의 다섯 하위 시험이, GIF의 첫 장면 넓히기를 빼면 GIF 하위 시험 둘이 실패한다.

## Task 2: 뷰어 — 그림과 링크

- [x] 상대 경로 풀기(`mdRelPath`), 그림 분류(`mdImgPath`), 그림 주소(`mdAssetUrl`), 늦게 불러오기·자리 맡기·읽던 자리 되돌리기(`mdPicLoad`·`mdPicError`·`MD_PIC_SIZE`·`MD.spot`), 핀 테두리, 다크 모드의 밝은 판. 검증: `test_md_tree_refs.py`, 브라우저 `TreeImages`·`ReadingSpot`·`ReadingSpotChangedImage`·`SvgOnItsOwn`. PoC 커밋.
- [x] 링크 관문(`mdTarget`), 문서 링크(`mdGoDoc`, `#제목` 은 `MD.headTo`), 링크로 간 전환만 기록 항목 하나, 전환 전의 뒤로 가기(`NAVGEN`). 검증: 브라우저 `DocumentLinks`. PoC 커밋.

## Task 3: 남은 시험

- [x] 다른 출처의 끼워 넣기. `CrossOriginEmbed` 가 실제 루프백 리스너(Limn, 다른 포트의 평범한 페이지)를 띄워 뷰어 자신의 페이지는 그리고, 다른 포트·호스트의 페이지는 서버가 200으로 답했는데도 그리지 못하며, CORP를 뺀 대조에서는 그리는지 본다. 변이: `ASSET_RESOURCE_POLICY = None` 이면 두 엔진의 하위 시험 넷이, `"same-site"` 이면 Firefox의 같은 호스트 하위 시험이 실패한다(Chromium은 같은 IP의 다른 포트를 다른 사이트로 본다).
- [x] 휴대폰 뒤로 가기 층 아래의 링크. `LinksUnderTheBackLayer`. 변이: `mdGoDoc` 의 `if(!BACK)` 을 빼면 기록 길이가 하나 늘고 맨 위 항목이 층의 것이 아니게 되어 실패한다.
- [x] Firefox 한 벌: `TreeImagesFirefox`·`ReadingSpotFirefox`·`SvgOnItsOwnFirefox`·`DocumentLinksFirefox`·`CrossOriginEmbedFirefox`. Firefox가 직접 연 SVG에서 알리는 정책 위반은 시험이 일으킨 것으로 표시한다. 변이: `sandbox` 를 빼면 두 엔진의 SVG 시험이, `mdPicLoad` 의 되돌리기를 빼면 읽던 자리 시험 셋이, 링크의 `pushState` 를 빼면 두 엔진의 문서 링크 시험 넷이, 트리 그림을 대체 글로 돌리면 두 엔진의 그림 시험 넷이 실패한다.
- [x] 알려진 한계로 둔 것(설계 §구현에서 정한 것): 탭을 연 채 바뀐 그림은 페이지를 다시 열 때 보인다. 304도 한도까지 읽는다(8 MiB 읽기와 BLAKE2b 해시를 스무 번 잰 평균 약 8 ms).

## Task 4: 승인 기록과 문서

- [x] ADR-0030 `승인됨`, 설계 머리와 §소유자 결정, ADR 색인의 0030 행과 0025 행의 후속 관계. 검증: `git diff --name-status origin/main...HEAD -- ':(glob)docs/adr/[0-9][0-9][0-9][0-9]-*.md'` 이 `A` 만 보인다.
- [x] Handbook: viewer.md §그림·§링크와 관문·§모바일 레이아웃의 뒤로 가기·§여러 문서 전환의 주소, api.md §화면·PDF·정적 파일과 §오류 응답, architecture.md 문서 조회 슬라이스와 불변식 9의 그림 응답 정책, verification.md §원고 트리의 그림 경로, index.md 파일 지도. `SECURITY.md`, 두 SKILL, CHANGELOG `Unreleased`. 검증: `tests/architecture/test_handbook_refs.py`.

## 검증

- [x] `uv run ruff check`, `uv run ruff format --check`, `uv run mypy`(기본과 `--platform darwin`), `npm run typecheck`, `tools/strict_ratchet.py`.
- [x] `uv run pytest -q -n 4 -m "not browser and not tex"`, `tests/architecture`, `test_assets.py`, `test_md_tree_refs.py`, `src/limn/viewer/tests/test_viewer_markdown*.py`, `test_viewer_document_visit.py`·`test_viewer_cross_doc_actions.py`.
- [x] 테일넷 PoC(`limn-poc-assets`)를 이 브랜치로 다시 띄워 200을 확인한다.
- [ ] 머지 전: 네 기기군 전후 캡처를 소유자에게 보인다([workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다). WebKit 클래스는 두지 않았다(이 기계에서 뜨지 않는다). 스크롤 고정이 없는 WebKit(iOS Safari)의 읽던 자리는 실기기로 확인한다.
