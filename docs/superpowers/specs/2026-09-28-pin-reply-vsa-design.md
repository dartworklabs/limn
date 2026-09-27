# 핀 답글 VSA 이행 설계

> **상태: 구현·검증 완료.** [백엔드 VSA 점진 이행](2026-09-28-backend-vsa-migration-design.md)의 다음 경로다.

## 범위와 소유권

`POST /api/pins/{id}/reply`의 본문 검사, HTTP 응답, 잠금 아래 답글·재열림·알림을 `features/pins/lifecycle/`로 옮긴다. 공통 요청 보안 검사와 `PinStore.transact()`는 유지한다. `Principal.is_human()`이 판단한 값을 HTTP 입구에 넘겨 현재의 역할 해석을 지킨다.

완료되면 `ServerApplication.reply_pin`, 평면 `App.reply_pin`, `service/transitions.py`의 답글 구현을 지운다. 답글이 다시 여는 경우의 알림은 이미 같은 기능의 서비스에 있는 한 헬퍼가 계속 결정한다. 순수 전이 규칙은 아직 다른 핀 동작이 쓰는 `pins/lifecycle.py`에 유지한다.

## 행동 계약

입력의 첫 거절 순서는 `text` → `mentions` → `reopen`이다. `reopen`이 없는 경우의 사람·에이전트 판정, 이미 닫힌 핀의 재열림, 멘션 대상과 이전 참여자에 대한 알림, 스레드가 가득 찼을 때의 무기록 거절을 보존한다. HTTP 상태·본문·오류 문장과 `pins.jsonl`·`pins.md` 바이트는 기준 커밋과 같아야 한다.

## 확인

답글·알림·수명 주기·HTTP·접근 테스트와 전체 게이트를 통과한다. 기준 커밋과 별도 프로세스에서 유효·거절·재열림 답글의 HTTP 응답과 단계별 상태 파일을 비교하고, 고의 문구 변경이 차등 비교에서 잡히는지 확인한다. 현재 구조는 같은 변경에서 Handbook에 반영한다.
