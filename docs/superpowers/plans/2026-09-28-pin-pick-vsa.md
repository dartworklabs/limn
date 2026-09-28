# PDF 선택 VSA 시공 계획

1. `location/input.py`에 선택 파서를 옮기고 직접 검사 대상을 새 소유자로 바꾼다.
2. `location/http.py`에 응답과 경고·거절 문장을 옮기며 기존 `web` 소유권을 제거한다.
3. SyncTeX·텍스트 추출, 토큰 캐시와 선택 결과를 위치 기능의 `source.py`·`resolve.py`로 옮긴다. 실행별 `PinSelection`를 조립해 처리기가 기능 HTTP 입구를 부르게 하고 `ServerApplication.pick`과 `App.pick`을 지운다.
4. 계약 비교, 관련 테스트와 전체 게이트를 실행하고 Handbook의 현재 구조를 갱신한다.
