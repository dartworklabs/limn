# 핀 처리 중 표시 VSA 이행 설계

> **상태: 구현·검증 완료.** [백엔드 VSA 점진 이행](2026-09-28-backend-vsa-migration-design.md)의 핀 수명 주기 묶음이다.

## 범위

`POST /api/pins/{id}/claim`과 `/unclaim`의 입력, HTTP 응답, 잠금 아래 저장을 `features/pins/claims/`로 옮긴다. 처리 중 표시는 닫기·답글과 독립적으로 바뀌므로 자체 협력자 `PinClaims`를 둔다. 완료된 경로의 `ServerApplication`·평면 `App` 전달 메서드와 `service/claim.py`는 제거한다. 여러 핀 동작이 공유하는 상태 타입, 순수 규칙, `PinStore.transact()`와 공통 요청 가드는 현재 소유자를 유지한다.

## 행동과 검증

`claim`의 `eta_min` → `ttl_min` 검사 순서, 상한 절삭과 응답의 `*_applied`, 같은 신원의 연장, 남의 claim과 닫힌 핀의 409 본문을 보존한다. `unclaim`은 현재처럼 행위자 소유권을 확인하지 않고, 지울 claim이 없으면 쓰지 않는다. 두 동작 모두 알림을 보내지 않는다. 기준 커밋과 별도 프로세스에서 HTTP 응답과 상태 파일을 비교하고, 고의 문구 변경이 차등 비교에서 잡히는지 확인한다. 집중·전체 게이트와 Handbook 동기화를 마치면 한 경로 묶음으로 커밋한다.
