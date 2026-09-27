# 관리 CLI VSA 이행

`cli.py`는 진입 명령 선택과 함께 인스턴스 상태 폴더 찾기, 토큰 파일 안전 검사·쓰기, 토큰 명령, 멤버 명령을 한 파일에서 다룬다. 이 기능들을 `features/administration/`의 대상 해석·토큰 파일·토큰 명령·멤버 명령으로 나누고 `cli.py`에는 `serve`·`version`·`migrate`와 셸 인스턴스 명령의 선택·전달만 남긴다. 기존 `access.py`의 신원·권한·저장 형식 판단은 건드리지 않는다.

명령 인자, stdout·stderr, 종료 코드, 토큰 파일 권한·심링크·Git 작업 트리 거절, 토큰 생성 실패 시 취소, 감사 파일 바이트·순서를 유지한다. `version`·인스턴스 명령의 빠른 시작과 `token`·`member`의 `server.py` 비의존성을 유지한다. `instances.sh`의 명령 구현은 이번 묶음에서 그대로 둔다. 배포 패키지는 새 Python 기능 패키지를 포함한다.
