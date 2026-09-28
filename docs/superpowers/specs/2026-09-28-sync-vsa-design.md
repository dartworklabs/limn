# Git 동기화 VSA 이행

`--git-pull`과 원격 main 감시의 판단은 `pull.py`, Git 실행과 잠금·감시 작업은 `gitsync.py`, 실행별 연결은 `server.py`에 있다. 먼저 판단과 실행의 소유권을 `features/sync/rules.py`와 `features/sync/run.py`로 모아 최상위 두 진입점을 없앤다. 이 단계에서는 실행별 `PullShare`·`SyncWatch`가 `Runtime`에 속하고 `server.py`가 설정·문서·빌드 시작 함수를 넘기는 관계를 유지한다. 이후 조립 지점의 전달 메서드를 제거할 때도 두 실행 사이에 감시 상태와 잠금이 섞이지 않아야 한다.

Git 호출 순서, fast-forward와 dirty 판정, 감시 주기·상태, 빌드 시작 순서, 실패와 HTTP 응답을 바꾸지 않는다. 실제 Git 저장소를 쓰는 테스트와 별도 프로세스의 HTTP·상태 비교로 확인한다.
