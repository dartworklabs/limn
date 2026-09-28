# 인스턴스 문서 명령과 검사 소유권

`instances.sh`는 `limn doc`의 목록·자동 제안·추가·삭제와 `limn add`가 공유하는 문서 키·경로 검사, 표준 원고 구조 자동 탐지를 여러 위치에 나누어 둔다. 이 규칙을 `features/administration/instance_documents.sh` 한 파일에 둔다. `limn add`와 상태 출력 명령은 그 파일의 `validate_doc_specs`·`detect_docs_layout`·`doc_count`·`doc_keys`를 호출한다. 인스턴스 관리자의 공통 설정 읽기, 파일 값 출력, 유닛 제어와 여러 기능이 쓰는 `stat_fmt`·`detect_main`은 `instances.sh`에 남긴다.

문서 키·개수·이름 길이, 확장자·원고 트리 경계와 `::` 표기, Git 커밋 시각 우선·수정 시각 대체·동점 거절, `MAIN`에서 `DOCS`로 바꿀 때 첫 문서의 상태 폴더 유지, 설정 바이트와 재시작 문구를 유지한다. 문서 파서의 기존 전역 결과(`DOC_KEY`, `DOC_NAME`, `DOC_PATH`, `DETECTED_DOCS`)는 이번 이동에서 호출 계약으로 유지하고, 파일 간 경계에 명시한다. 저장 형식이나 서버의 재검증은 바꾸지 않는다.

이동한 본문을 기준 커밋과 비교하고, 셸 인스턴스 테스트 190건의 정상·거절 시나리오를 실행한다. 새 파일의 wheel 포함·ShellCheck·전체 회귀·Handbook 현재 소유권을 확인한다.
