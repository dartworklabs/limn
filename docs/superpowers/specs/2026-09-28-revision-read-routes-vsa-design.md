# 이력 읽기 경로 VSA 설계

> **상태: 확정.** 전체 이행의 불변식과 목표는 [백엔드 VSA 점진 이행 설계](2026-09-28-backend-vsa-migration-design.md)와 ADR-0009가 정한다.

## 대상

`GET /api/revisions`, `GET /api/revision-diff`, `GET /api/revision-build`, `GET /api/revision-pdf`는 이미 `features/revisions/http.py`가 입력 검사와 동작 결과를 정한다. `web/handler.py`의 `_get_document`·`_get_revision`이 경로를 고르고 응답 타입과 캐시를 붙이는 부분은 아직 공통 처리기에 있다.

## 선택

네 GET 경로의 매칭과 응답 조립을 `features/revisions/routes.py`가 소유한다. 조립 지점은 실행별 `RevisionRequests`를 받은 경로 함수를 등록한다. 처리기는 기존 기능 경로 등록 목록을 호출하며, 공통 요청 검사·문서 선택·응답 전송·알 수 없는 경로의 404를 계속 맡는다. `POST /api/revision-build`는 이번 단계의 대상이 아니며 이후 POST 등록에서 옮긴다.

## 합격 기준

- 네 GET 경로의 분기가 처리기에서 사라지고 이력 기능의 경로 함수 하나가 소유한다.
- Git 이력·diff, 잘못된 커밋·핀, 비교 작업 상태와 PDF의 없거나 준비 중인 응답이 기준 커밋과 같다.
- 실행별 캐시·작업 목록, 공통 보안 검사 순서, 정적 검사와 전체 게이트가 유지된다.
