# 사람·알림 실행 문맥 VSA 시공 계획

1. 사람 파일·후보·기록을 `features/collaboration/directory.py`로 옮기고 `/api/people`이 그 서비스를 쓰게 한다.
2. 이벤트 파일·생성·기록·멘션 재알림·폴링을 `features/collaboration/notices.py`로 옮긴다. 핀 문맥과 문서 조회가 좁은 서비스 메서드를 받게 한다.
3. `ServerApplication`과 `web/app.py`의 옛 전달을 제거하고 직접 호출 테스트를 새 소유자에 연결한다.
4. 별도 프로세스의 기준 커밋과 HTTP 응답·상태 파일 바이트·권한을 비교하고 차이 감지 대조를 확인한다. 집중·전체 게이트를 실행한다.
5. Handbook의 현재 책임과 파일 지도를 코드에 맞춘다.
