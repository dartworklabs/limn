# 이력 읽기 경로 VSA 시공 계획

1. 고정 Git 커밋 두 개를 가진 원고로 네 GET 경로의 성공·거절 응답과 상태 파일을 기준 커밋 별도 프로세스에서 기록한다.
2. `features/revisions/routes.py`로 경로 매칭과 JSON/PDF 응답 조립을 옮긴다. 조립 지점은 실행별 `RevisionRequests`를 묶어 등록한다.
3. 처리기의 옛 GET 분기를 지우고 경로 목록 검사가 새 소스도 확인하도록 바꾼다.
4. 관련 테스트, 별도 프로세스 차등 비교와 변이 검사를 실행한다.
5. 전체 pytest, 인스턴스 셸 테스트, Ruff, ShellCheck, mypy, Handbook 출판 검사를 통과시키고 현재 구조 문서를 맞춘 뒤 독립 커밋으로 묶는다.
