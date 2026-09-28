# 동기화 실행 연결 VSA 이행

`features/sync/`가 pull과 감시를 소유하지만 `ServerApplication`이 `repo_pull`·`sync_status`·`sync_main_once`를 각각 전달한다. 실행별 설정·문서·잠금·빌드 시작 함수를 한 번에 조회하는 좁은 `SyncContext`와 이를 쓰는 `SyncService`를 같은 기능에 둔다. 조립 지점은 문맥 생성 함수를 등록하고 빌드·meta·기동에서 서비스를 직접 부른다. 세 전달 메서드는 제거한다.

테스트가 실행 중 `C`나 `RT`를 교체하는 것과 여러 문서의 pull 공유는 계속 동작해야 한다. 문맥은 호출 때마다 만들고 감시 잠금과 상태는 `RT`가 소유한다. Git 호출 순서, 감시 간격과 중지, HTTP `sync` 값, 빌드의 `pull` 기록은 바꾸지 않는다.
