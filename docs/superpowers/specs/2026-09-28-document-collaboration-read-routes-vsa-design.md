# 문서·사람 조회 경로 VSA 설계

> **상태: 확정.** 전체 이행의 불변식과 완료 기준은 [백엔드 VSA 점진 이행 설계](2026-09-28-backend-vsa-migration-design.md)와 ADR-0009가 정한다.

## 대상

`GET /api/meta`, `/api/docs`, `/api/outline-labels`는 `features/document_views/http.py`가, `GET /api/people`은 `features/collaboration/http.py`가 응답 본문을 만든다. 경로 매칭과 최종 JSON 응답은 아직 공통 처리기의 서로 다른 메서드에 흩어져 있다. meta의 전체 읽기는 사람 기록 콜백을 부르고, 응답은 요청자 역할을 포함한다.

## 선택

등록 GET 경로에 요청별 `GetRequest` 값 하나를 넘긴다. 값에는 이미 검사·선택된 문서, 쿼리, actor, principal, Host 원문, 사람 기록 콜백만 담는다. 공통 처리기는 보안 검사와 문서 선택을 한 번 수행한 뒤 이 값을 만들고 등록 순서대로 기능 경로에 넘긴다. 빌드·이력 경로도 같은 계약으로 연결하되 기존 입력·응답 함수는 바꾸지 않는다.

문서 상태·목차·문서 목록의 경로 이름과 응답 조립은 `features/document_views/routes.py`, 사람 후보 경로는 `features/collaboration/routes.py`가 소유한다. 실행별 서비스는 조립 지점이 등록 함수에 묶는다. meta의 사람 기록 여부와 이벤트 커서 검사 순서는 현재 `http.meta`를 그대로 써서 보존한다.

## 합격 기준

- 네 GET 경로의 매칭 분기가 공통 처리기에서 사라진다.
- full/light meta, 유효·잘못된 이벤트 커서, 문서 목록·목차, 사람 후보와 역할의 응답 및 상태 파일이 기준 커밋과 같다.
- 공통 요청 가드와 실행별 사람 잠금·캐시, 정적 검사와 전체 게이트가 유지된다.
