# 빌드 실행 구현 VSA 이행

현재 `build.py`가 여러 기능이 읽는 빌드 산출물·원본 지문·이력과 재빌드 실행·원고 복사·PDF 렌더를 함께 담는다. 문서별 빌드 잠금·상태 전이·결과 기록은 `features/builds/run.py`, LaTeX/PDF 실행과 쪽 게시·보기 전용 다시 그리기는 `features/builds/engine.py`로 옮긴다. 핀 위치·조회와 문서 초기화가 함께 읽는 빌드 산출물·원본 지문·이력 규칙과 결과 타입은 공통 `build.py`에 둔다.

`run.py`는 공통 빌드 사실을 받고, `engine.py`는 공통 빌드 사실과 상태 갱신 함수를 호출한다. `server.py`는 실행별 설정을 연결하고 `features/builds/service.py`가 동기·비동기 선택을 유지한다. 문서별 잠금, 파일 쓰기 순서, 실패 로그·응답과 PDF 감시의 동작을 바꾸지 않는다.
