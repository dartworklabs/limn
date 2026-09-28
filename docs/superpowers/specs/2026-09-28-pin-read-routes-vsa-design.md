# 핀 조회 경로 VSA 설계

> **상태: 확정.** 전체 이행의 경계와 불변식은 [백엔드 VSA 점진 이행 설계](2026-09-28-backend-vsa-migration-design.md)와 ADR-0009가 정한다.

## 대상

`GET /pins.md`, `/api/pins`, `/api/pins/dropped`, `/api/pins/<id>`의 본문과 저장 렌더 입력은 `features/pins/listing/`이 소유한다. `GET /api/snippet`, `/api/overlaps`의 입력과 결과는 `features/pins/location/`이 소유한다. 그러나 경로 매칭과 최종 응답은 아직 공통 `web/handler.py`에 있다.

## 선택

목록의 네 GET 경로는 `features/pins/listing/routes.py`, 원문·겹침 두 GET 경로는 `features/pins/location/routes.py`가 매칭하고 응답을 만든다. 공통 처리기의 검사·문서 선택 뒤 이미 만들어지는 `GetRequest`를 받는다. 목록 기능은 자신의 조회 협력자와 휴지통 주기 정리·원격 기본 주소 함수를 조립 지점에서 받는다. 다른 기능의 내부 모듈을 가져와 정리 규칙을 중복 집행하지 않는다.

`/pins.md`와 `/api/pins`의 정리 호출 순서, `pins.md`의 Host 기반 주소와 바이트, 쿼리의 문서 필터, 한 핀과 휴지통의 거절·응답, 원문 범위와 겹침의 입력 순서를 유지한다. `/api/pick`과 핀 변경 POST는 이후 경로 이동 대상으로 남는다.

## 합격 기준

- 여섯 GET 경로의 분기가 공통 처리기에서 사라지고 각 기능 경로가 한 번만 소유한다.
- 목록·`pins.md`·원문·겹침의 성공·거절 HTTP 응답과 상태 파일 바이트·권한이 기준 커밋과 같다.
- 요청 보안 검사, 문서 선택, 휴지통 정리 순서와 전체 게이트가 유지된다.
