# 문서 상태 조회 VSA 이행

`GET /api/meta`, `/api/docs`, `/api/outline-labels`의 문서·쪽·빌드 사실은 `meta.py`, 실행별 조립은 `ServerApplication`, 쿼리와 이벤트 합성은 공통 처리기에 있다. 세 조회를 `features/document_views/`의 입력·읽기·서비스·HTTP 입구로 묶고 최상위 `meta.py`와 앱의 `meta`·`meta_settings`·`docs_payload`·`outline_labels` 전달을 제거한다. 빌드 산출물과 핀 상태·동기화 상태·이벤트는 기존 소유자에게서 값 또는 좁은 협력자로 받는다.

특히 `/api/meta`는 `light` 판정 뒤 라이트가 아니면 사람을 기록하고, 기본 문서 상태를 만든 뒤에만 `ev` 커서를 검사한다. 이 순서와 핀 동기화 쓰기 유무, 응답 키 순서, 쪽 `.aux`의 읽기 안전 규칙을 유지한다. 공통 본문·Host·신원·역할 가드는 처리기에 남긴다.
