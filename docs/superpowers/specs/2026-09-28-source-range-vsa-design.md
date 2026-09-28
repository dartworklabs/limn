# 원문 구간 조회 VSA 이행

`GET /api/snippet`과 `GET /api/overlaps`의 입력·구간 계산·응답을 `features/pins/location/`이 소유한다. 요청 가드와 문서 선택은 처리기에 남긴다. 파일의 원고 트리 경계 검사는 편집 기능도 쓰는 공통 `source_file`을 그대로 사용한다. 두 경로는 같은 `file`·`lo`·`hi` 검사를 순서까지 공유한다.

`snippet`의 보기 전용 문서 거절, 범위 사다리, 필드 순서와 `overlaps`의 결과 및 읽기 실패가 기존과 같아야 한다. `ServerApplication`과 평면 `App`의 두 전달 메서드는 제거한다. 기준 커밋과 변경을 별도 프로세스에서 실행해 응답과 상태 파일 바이트를 비교한다.
