# 이력·비교 PDF 경로 VSA 이행

Git 이력과 비교 PDF의 다섯 HTTP 경로(`GET /api/revisions`, `/api/revision-diff`, `/api/revision-build`, `/api/revision-pdf`, `POST /api/revision-build`)가 쓰는 입력 검사, 결과·거절 응답, 실행별 협력자를 `features/revisions/`로 모은다. 공통 처리기는 요청 가드·문서 선택·전송을 유지한다. 비교의 캐시·슬롯·샌드박스·상태는 현재 `revisions.py`의 단일 구현을 그대로 사용한다.

기준 커밋과 성공·거절·진행·부재 응답과 상태 파일을 비교한다. 이 묶음에서 파서와 응답의 옛 진입점, 앱의 경로별 전달 메서드를 제거한다. 내부 비교 구현의 분할은 별도 묶음으로 진행한다.
