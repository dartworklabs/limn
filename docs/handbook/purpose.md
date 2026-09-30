# 목적과 범위

Limn은 LaTeX 원고와 벡터 그래픽을 PDF로 띄우고 그 위에 핀을 찍는 리뷰 도구다. 사람이 브라우저에서 PDF 위에 핀(메모)을 찍으면, 에이전트(또는 다른 사람)가 그 핀을 보고 원고나 그림의 해당 자리를 고치고 핀을 닫는다. 범위를 LaTeX 원고와 벡터 그래픽으로 둔 결정은 [ADR-0011](../adr/0011-figure-documents.md) D1이다.

## 줄이는 비용

- **위치 찾기 비용.** "3쪽 둘째 문단 수식 아래"를 사람이 설명하고 에이전트가 TeX 소스에서 헤매는 시간을 줄인다. PDF 좌표를 SyncTeX로 역변환해 TeX 파일과 줄 번호를 바로 가리킨다.
- **맥락 전달 비용.** 에이전트가 작업할 때 이전 코멘트와 해결 상태(`open`·`closed`·`acknowledged`)를 `pins.md` 파일 하나로 한눈에 읽을 수 있게 한다.
- **협업 마찰.** 사람과 사람, 사람과 에이전트가 같은 뷰어에서 핀을 보고, @멘션으로 알림을 주고받으며, 누가 작업 중인지(`assignee`, `claimed_by`)를 드러낸다.

## 대상 사용자

- **주 사용자 (사람 저자):** 브라우저에서 PDF를 보며 수정 요청 핀을 찍고, 에이전트의 작업 결과(diff, 변경된 PDF)를 검토한다.
- **에이전트 (소프트웨어):** CLI나 HTTP API로 핀 목록을 읽고, TeX 원고를 수정한 뒤 핀을 닫는다.
- **공동 저자 (사람):** 같은 인스턴스에 접속해 코멘트를 남기고 답글을 달며 검토한다.

## 지원 범위

- LaTeX 원고: `latexmk` 또는 `pdflatex`/`xelatex`/`lualatex` 기반 빌드. SyncTeX(`.synctex.gz`)가 나오는 환경.
- 벡터 그래픽: 그림 저장소가 그림을 PDF(그림 한 장이 한 쪽)로 렌더하고 요소 지도(`.limnmap.json`)를 함께 낸 그림. Limn은 렌더하지 않고 두 파일을 가져온다([build-sync.md](build-sync.md) §그림 문서). 지도 형식은 [api.md](api.md) §그림 요소 지도 (`limn-figure-map/1`)에 있다.
- 네트워크: 로컬 루프백(`127.0.0.1`), 사설망(`tailscale serve`), 인증 리버스 프록시 뒤.
- 브라우저: 최신 데스크톱 브라우저 (Chromium, Firefox, Safari).

## 다루지 않는 상황

- 컴파일되지 않는 원고: PDF가 없으면 핀을 찍을 수 없다. 먼저 빌드가 성공해야 한다.
- SyncTeX가 없는 빌드: PDF 좌표에서 TeX 소스 위치를 역변환할 수 없다. 핀은 찍히지만 파일·줄 정보가 빈다.
- 사용자가 이미 파일과 줄 번호를 알고 있다면 서버를 띄우는 비용이 낭비다. 바로 고친다.
- Typst 원고는 범위 밖이다. SyncTeX은 LaTeX 전용이다.
- 요소 지도가 없는 그림(사진, 받은 래스터 그림)은 그림 문서가 아니다. 보기 전용 PDF로 띄운다.

## 하지 않는 일

- **공개 인터넷에 직접 열지 않는다.** 신원 방식·에이전트 토큰·멤버 역할은 있지만, 로그인 화면(OIDC)이나 초대 링크는 없다. 사설망(`tailscale serve`)이나 인증 프록시(`--auth trusted-proxy`) 뒤에서만 노출한다.
- **원고를 서버가 직접 고치지 않는다.** 고치는 것은 에이전트나 사람이고, 서버는 위치와 요청을 기록한다.
- **VPN이나 조정 서버를 제품으로 운영하지 않는다.** 테일넷은 지원하는 자체 호스팅 방법 중 하나일 뿐이다.
- **그림을 렌더하지 않는다.** 그림 저장소의 코드를 실행하지 않고, SVG를 래스터화하지도 않는다. 화면에는 그림 저장소가 낸 PDF만 그린다.

## 진실 소스

"지금 값이 무엇인가"를 물을 때 어디가 정답인지 영역별로 정리한다. Handbook이 모든 영역의 정본은 아니다. 직접 절차를 소유하는 영역과, 다른 정본을 가리키는 안내판 역할만 하는 영역을 구분한다.

| 영역 | 현재 정답이 있는 곳 | Handbook의 역할 |
| --- | --- | --- |
| 서버 동작·비즈니스 규칙 | 코드 [`src/limn/__init__.py`](../../src/limn/__init__.py) 패키지와 그것을 고정하는 테스트. 기능 소유권과 공통 경계는 [architecture.md](architecture.md) §현재 구조 | 안내판. 규칙의 이유와 중요한 값(한도·시간·임계치)을 [domain.md](domain.md), [build-sync.md](build-sync.md)에 설명한다 |
| 뷰어 화면 규칙 | `src/limn/viewer/`의 파일과 `src/limn/viewer/tests/test_viewer.py`의 `Frontend*` 가드 | 안내판. 규칙과 근거는 [viewer.md](viewer.md) |
| 에이전트 계약 (`pins.md`, HTTP API) | [api.md](api.md)가 계약 문서이고, 코드가 그 계약을 구현한다. 둘이 어긋나면 결함이다 | **정본.** 계약을 바꾸려면 이 문서부터 바꾼다 |
| 에이전트 작업 절차 | [SKILL.ko.md](../../skill/SKILL.ko.md) / [SKILL.md](../../skill/SKILL.md) | 안내판 |
| 핀·빌드·사람·권한 데이터 | 인스턴스의 상태 디렉터리 (`pins.jsonl`, `pins.seq`, `builds.json`, `people.json`의 멤버와 역할, `tokens.json`의 토큰 해시, `events.jsonl` 등) | 안내판. 파일 배치는 [operations.md](operations.md) §상태 파일 배치 |
| 인스턴스 설정 | 머신의 `~/.config/limn/<이름>.env` | 안내판. 키 목록은 [instances.md](instances.md) |
| 런타임 의존성·지원 파이썬 | [`pyproject.toml`](../../pyproject.toml), [`uv.lock`](../../uv.lock) | 안내판 |
| 구조·불변식 | Handbook [architecture.md](architecture.md) | **정본** |
| 검증 절차와 합격 기준 | Handbook [verification.md](verification.md). 실행 증거는 CI 로그 | **정본** |
| 변경 절차 | Handbook [workflow.md](workflow.md), 기여 조건은 [CONTRIBUTING.md](../../CONTRIBUTING.md)와 [CLA.md](../../CLA.md) | **정본** |
| 코딩 규칙 | 팀 스킬 `code-implement`, `code-testing`, `code-security` | [code-style-roadmap.md](code-style-roadmap.md)가 Limn의 적용 경계와 현재 검증 범위를 설명한다 |
| 보안 정책·신고 | [SECURITY.md](../../SECURITY.md) | 안내판 |
| 릴리스 기록 | [CHANGELOG.md](../../CHANGELOG.md), git 태그 `v*` | 안내판 |

> **주의**
>
> 코드와 Handbook 설명이 어긋나면 어느 쪽이 옳은지 추측해서 고르지 않는다. 동작 영역이면 코드와 테스트를 확인하고, 계약 영역이면 [api.md](api.md)를 기준으로 코드가 결함인지 판단한다. 판단이 서지 않으면 멈추고 사람에게 묻는다.
