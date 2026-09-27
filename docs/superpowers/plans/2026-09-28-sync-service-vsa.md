# 동기화 실행 연결 VSA 시공 계획

1. `features/sync/service.py`에 호출 시점 문맥과 `repo_pull`·`status`·`once`·`watch`를 둔다.
2. `ServerApplication`의 세 전달 메서드를 제거하고 빌드·meta·기동을 서비스에 연결한다. 테스트의 실패 주입도 새 소유자로 옮긴다.
3. 동기화·빌드·meta·감시 종료 테스트와 별도 프로세스 HTTP·상태 파일 비교를 수행한다.
4. 전체 게이트와 Handbook 현재 구조를 갱신한다.
