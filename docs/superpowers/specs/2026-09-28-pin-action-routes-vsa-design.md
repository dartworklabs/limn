# 핀 ID 동작·전체 비우기 POST 경로 VSA 설계

> **상태: 확정.** 전체 이행의 불변식과 목표는 [백엔드 VSA 점진 이행 설계](2026-09-28-backend-vsa-migration-design.md)와 ADR-0009가 정한다.

## 대상

`POST /api/pins/<id>/<동작>`의 닫기·다시 열기·확인·답글, claim·unclaim, 편집, 삭제·복원·영구 삭제와 `POST /api/clear`는 각 핀 기능의 `http.py`가 입력·응답을 맡는다. 공통 처리기는 아직 열 동작 이름을 정규식에 넣고 기능별 호출을 분기한다.

## 선택

공통 처리기는 본문 읽기 → Host/Origin → 신원 → 입장 → POST 역할 검사 → 사람 기록 → JSON 파싱을 마친 뒤 `/api/pins/<숫자>/<영문 동작>` 모양과 등록된 동작 이름을 검사한다. 기능 패키지는 자신의 동작 이름과 요청별 `PinActionRequest`를 받는 응답 함수를 등록한다. `PinActionRequest`는 정수 ID, actor, 본문, principal만 담는다. `reply`의 `is_human`과 `close`의 `review_on_close`는 principal의 기존 메서드를 함수로 넘긴다.

`/api/clear`는 휴지통 기능이 이름과 `OtherPostRequest` 응답 함수를 등록한다. 조립 지점은 기능별 표를 합치며 동작 이름 중복을 거절한다. 보안 경계인 `access.check_role`의 경로 규칙과 핀 파일의 `transact()` 순서는 그대로다. 알 수 없는 동작은 기존 404 본문으로 끝난다.

## 합격 기준

- 공통 처리기에서 열 동작의 기능별 분기와 `/api/clear` 이름이 사라진다.
- 성공·거절·역할 금지, 저장 파일·감사·알림 순서가 기준 커밋과 같다.
- 경로 등록 충돌이 조용히 덮이지 않고, 전체 게이트가 통과한다.
