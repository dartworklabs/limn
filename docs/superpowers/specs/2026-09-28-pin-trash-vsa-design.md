# 핀 휴지통 VSA 이행 설계

> **상태: 구현·검증 완료.** [백엔드 VSA 점진 이행](2026-09-28-backend-vsa-migration-design.md)의 휴지통 묶음이다.

## 범위

`drop`·`restore`·`purge`·`clear`의 HTTP 입구와 응답, `pins.dropped.jsonl` 변경, 만료·그림자 사본 정리를 `features/pins/trash/`가 소유한다. 같은 기능의 기동 정리와 주기적 정리도 이 협력자가 소유한다. 실행별 `PinContext`는 호출할 때 만들고, `server.py`는 협력자를 조립하고 호출한다. 삭제한 핀의 조회 응답은 핀 목록 슬라이스로 옮길 때 함께 정리하되 휴지통의 순수 만료·그림자 규칙을 공유한다.

기존 `service/trash.py`와 네 HTTP 동작의 평면 `ServerApplication`·`App` 전달 메서드를 지운다. `PinStore`의 잠금·준비·쓰기 순서, `access.check_role`의 소유자 검사, 상태 타입과 순수 전이는 유지한다.

## 행동과 검증

`drop`은 휴지통 사본을 먼저 쓰고 작성자 알림을 남긴다. `restore`는 살아 있는 핀을 먼저 쓰고 그림자 사본을 치운다. `purge`·`clear`는 감사 줄을 잠금 밖에서 쓰고 로그를 남긴다. 만료를 알 수 없는 항목은 보존하고, 실패한 정리는 주기 시각을 갱신하지 않는다. `clear`의 확인 문구 검사와 `purge`의 소유자 검사는 공통 HTTP 가드 뒤에서 기존 순서대로 적용한다. 기준 커밋과 별도 프로세스에서 HTTP 응답·상태 파일을 비교하고, 해당 기능과 전체 게이트를 통과시킨다.
