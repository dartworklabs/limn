# 사람 목록 조회 VSA 이행

`GET /api/people`은 처리기에서 응답을 조립하고 `ServerApplication.people_payload`가 역할·핀·사람 목록을 결합한다. `features/collaboration/`의 서비스가 읽기 순서를 소유하고 HTTP 입구가 `people`·`me` 본문을 만든다. 조립 지점은 역할 조회·핀 스냅숏·알려진 사람 조회 협력자만 연결하고 옛 `people_payload`를 제거한다.

`people.json`의 공통 읽기·쓰기와 역할 판정은 접근 검사와 멘션도 사용하므로 각각 `people.py`와 `access.py`에 둔다. 요청 가드 순서, `snapshot_pins()`의 동기화 쓰기, 후보 순서·역할·응답 바이트는 유지한다.
