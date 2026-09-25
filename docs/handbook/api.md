# HTTP API·pins.md 계약

Limn 서버(`limn serve`, 구현은 [`src/limn/server.py`](../../src/limn/server.py))는 뷰어와 에이전트에게 같은 HTTP API를 연다. 에이전트는 이 API와 `<state_dir>/pins.md` 표만 보고 핀을 읽고, 잡고, 고친 뒤 닫는다. 이 문서는 그 계약 전체를 다룬다. 요청 경계, 엔드포인트, 핀 수정·닫기·claim·겹침 규칙, 레코드 스키마, pins.md 형식이 여기에 있다.

[SKILL.ko.md](../../skill/SKILL.ko.md) 의 짧은 API 표로 모자랄 때 이 문서를 연다. 경로·필드·상태·pins.md 표시를 바꾸거나 새로 더할 때는 같은 diff에서 이 문서를 고친다. 재빌드·자동 동기화·위치 추정은 [build-sync.md](build-sync.md) 에 있다. Host·Origin 검사 규칙은 [operations.md](operations.md) §Host·Origin 검사에 있다.

> **핵심**
>
> 이 API와 pins.md 형식은 다른 저장소의 에이전트가 읽는 안정 계약이다. 경로, JSON 필드 이름, 상태 이름, pins.md 형식(열, 번호 칸 표시, 한국어 머리말 낱말)은 버전을 붙인 이관 계획 없이 바꾸지 않는다. 새 필드와 새 경로는 덧붙이기만 한다. 오류 응답은 언제나 한국어 메시지를 담은 `{"error": ...}` JSON이다. 이 원칙의 정본은 [CONTRIBUTING.md](../../CONTRIBUTING.md) 다.
>
> 접근 제어를 넣은 0.2.0도 이 원칙을 지켰다. 기존 경로, 필드, 상태 이름은 그대로다. 더한 것은 `me`·사람 목록의 `role` 필드, `401` 응답, 역할에 따른 `403` 응답, pins.md 안내 한 줄뿐이다(§인증).

## 요청 형식과 경계

요청 본문은 1 MiB 이하의 JSON 객체여야 하고 `Content-Type: application/json` 을 달아야 한다. 어기면 `400`·`413`·`415` 중 하나가 온다. 본문이 없는 POST는 헤더 없이도 통과한다. 에이전트의 `curl -X POST …/close` 가 이런 요청이다.

오류 응답은 항상 `{"error": "<한국어 메시지>"}` JSON이다. 예상 밖 예외도 연결을 끊지 않고 `500` JSON으로 돌려준다. 기존 경로는 계약을 유지해 왔고, 새 필드·경로는 덧붙이기만 했다.

- **본문을 먼저 끝까지 읽는다.** 서버는 어떤 응답보다 먼저 본문을 Content-Length 만큼 읽는다. 오류(`4xx`·`5xx`)를 보낸 뒤에는 연결을 닫는다. 읽지 않은 본문이 남으면 같은 keep-alive 연결의 다음 요청으로 해석된다. 그러면 신원 확인, `--allow`·`--members-only` 입장 검사, 작성자 기록을 우회할 수 있다. `tailscale serve` 는 백엔드 연결을 재사용하므로 이 틈이 실제로 열린다.
- **`Transfer-Encoding` 요청은 `400`** 이다. Content-Length 가 여러 개이거나 음이 아닌 정수가 아니어도 `400` 이다.
- **잘린 본문은 실행하지 않는다.** 본문이 Content-Length 보다 짧게 끊기면 `400` 이고 아무 동작도 하지 않는다. `/api/clear` 도 예외가 아니다.
- **교차 출처 `Origin` 과 낯선 `Host` 는 `403`** 이다. 허용하는 Host는 루프백 이름, `*.ts.net`, 그리고 0.2.0부터 `--public-host` 로 준 이름이다. 규칙과 이유는 [operations.md](operations.md) §Host·Origin 검사에 있다.
- **소켓 타임아웃은 30초**다. 본문을 보내다 멈춘 연결과 유휴 keep-alive 연결이 닫힌다. 재빌드처럼 오래 걸리는 처리 시간과는 관계없다.
- **이 경계를 지난 요청은 신원 확인을 거친다.** 신원을 정하지 못하면 `401`, 들어올 수 없는 사람이면 `403`, 역할이 허락하지 않는 변경이면 `403` 이다. 순서와 규칙은 §인증에 있다.

## 인증

모든 요청은 처리되기 전에 "이 요청은 누구인가"부터 정한다. 0.1까지는 이 신원이 핀에 누가 했는지 적는 데만 쓰였다. 0.2.0부터는 같은 신원으로 들어올 수 있는 사람과 바꿀 수 있는 일도 가를 수 있다. 설계와 단계 계획은 [ADR-0002](../adr/0002-access-control.md), 신원·역할의 뜻은 [domain.md](domain.md) §작성자 귀속에 있다. 서버 인자는 [operations.md](operations.md) §실행 인자, 인스턴스 설정 키와 `limn token`·`limn member` 명령은 [instances.md](instances.md) 에서 다룬다.

> **핵심**
>
> 아무 설정도 하지 않은 테일넷 인스턴스(`--auth tailscale`, 허용 목록 없음)는 0.1과 똑같이 동작한다. 테일넷에서 닿는 사람은 누구나 들어와 첫 방문 때 역할 없이(`editor`) 기록되고, 헤더 없는 루프백 요청은 여전히 에이전트다. 역할, 허용 목록, 토큰 전용 운영은 모두 켜야만 적용된다.

### 신원을 정하는 순서

서버는 요청마다 아래 순서로 신원을 정한다. 앞 단계에서 정해지면 뒤 단계는 보지 않는다.

1. **`Authorization: Bearer <토큰>`** 이 있으면 에이전트 API 토큰으로 본다(§토큰). 유효한 토큰은 어떤 신원 헤더보다 앞선다. 요청자는 에이전트 `{"login": "agent:<토큰 이름>", "name": "<토큰 이름>"}` 이 된다. 이 규칙은 모든 신원 방식에 같다.
2. 토큰이 없으면 인스턴스의 **신원 방식**(`--auth`)이 정한다. 아래 표를 본다.
3. 신원 방식이 `tailscale` 일 때만, 헤더도 토큰도 없는 루프백 요청은 에이전트 `{"login":"local","name":"로컬/에이전트"}` 다. 0.1의 동작이고 **폐지 예정**이다(§헤더 없는 루프백 에이전트). 0.2.1부터는 이 기기를 부른 요청(`Host` 가 루프백 이름이거나 없고, `X-Forwarded-*`·`Forwarded` 헤더가 없는 요청)에만 해당한다. `tailscale serve` 를 거친 헤더 없는 요청(태그 장치 등)은 토큰을 쓰라는 메시지와 함께 `403` 이다.

어느 단계에서도 정해지지 않으면 `401 {"error": …}` 이고 응답 헤더 `WWW-Authenticate: Bearer realm="limn"` 이 붙는다. 오류 메시지는 에이전트에게 `limn token create <인스턴스>` 로 토큰을 받으라고 알려 준다.

| 신원 방식 | 신원을 읽는 곳 | 그 밖의 요청 |
| --- | --- | --- |
| `tailscale`(기본) | `Tailscale-User-Login`·`-Name`·`-Profile-Pic` 헤더. TCP 피어가 루프백일 때만 믿는다. `tailscale serve` 가 루프백에서 붙기 때문이다 | 헤더 없는 루프백 요청은 3단계로 간다. 루프백 밖 피어의 헤더는 무시하고 `401` |
| `local` | 루프백 요청은 모두 소유자(사람, 역할 `owner`)다. 로그인은 `--local-user`, 없으면 `$USER`, 그것도 없으면 `owner` 다. Tailscale 헤더는 무시한다 | 루프백 밖은 `401`. 에이전트는 토큰을 써야 한다 |
| `trusted-proxy` | `--trusted-proxies`(기본 `127.0.0.1,::1`) 피어가 보낸 `--proxy-user-header`(기본 `X-Forwarded-User`) 헤더. 이름은 `--proxy-name-header`(기본 `X-Forwarded-Preferred-Username`)에서 읽는다. `--proxy-email-header` 를 주고 값이 오면 이메일이 로그인이다 | 그 밖의 피어나 사용자 헤더 없는 요청은 `401` |

헤더로 온 로그인이 `local` 이거나 `agent:` 로 시작하면 `401` 이다. 에이전트 신원은 토큰과 루프백 규칙으로만 생긴다. 사람이 헤더로 에이전트를 흉내 낼 수 없게 하려는 것이다.

```bash
export LIMN_TOKEN=limn_…            # limn token create <인스턴스> 가 한 번 보여 준 값
curl -s -H "Authorization: Bearer $LIMN_TOKEN" <base>/pins.md
curl -s -X POST -H "Authorization: Bearer $LIMN_TOKEN" -H 'Content-Type: application/json' \
  -d '{"reply": "…", "ref": "PR #12"}' <base>/api/pins/3/close
```

### 토큰

토큰은 사용자가 만들어 에이전트에게 건네는 비밀 값이다. 에이전트는 이것을 환경 변수(예: `LIMN_TOKEN`)에 두고 모든 요청에 붙인다.

- **발급**: `limn token create <인스턴스>` 다. 인스턴스 관리자 없이 `limn serve` 만 쓰면 `limn token create --state-dir <디렉토리>` 다. `--name` 으로 이름을 줄 수 있고, 없으면 `agent`, `agent-2` … 순으로 붙는다. 평문 토큰(`limn_…`)은 이때 한 번만 보여 준다.
- **저장**: 서버는 SHA-256 해시만 `<state_dir>/tokens.json`(권한 `0600`)에 둔다. 평문은 어디에도 남지 않는다.
- **폐기**: `limn token revoke <인스턴스> <id 또는 이름>` 이다. 서버는 `tokens.json` 이 바뀌면 다시 읽는다. 그래서 폐기는 재시작 없이 다음 요청부터 적용된다.
- **어디서나 같다**: 토큰은 루프백 밖에서 와도, 프록시 뒤에서 와도 같은 에이전트다.
- **물러서지 않는다**: 모르는 토큰, 폐기된 토큰, 빈 Bearer 헤더, Bearer 헤더가 두 번 온 요청은 `401` 이다. 다른 신원으로 물러서지 않는다. 물러서면 폐기한 토큰을 든 에이전트가 사람이나 로컬 에이전트로 조용히 통과한다.
- **다른 방식은 무시한다**: `Basic` 처럼 `Bearer` 가 아닌 `Authorization` 방식은 Limn의 것이 아니므로 읽지 않는다.

### 입장 — `--allow` 와 `--members-only`

신원이 정해지면 들어올 수 있는지 본다. 이 검사는 헤더로 신원이 정해진 사람에게만 한다.

| 설정 | 들어오는 사람 |
| --- | --- |
| `--members-only` | `people.json` 에 있거나 `--allow` 에 있는 로그인 |
| `--allow` 만 | `--allow` 에 있는 로그인. 0.1과 같은 뜻이다 |
| 둘 다 없음 | 신원 방식이 확인한 모든 사람. 첫 방문 때 `role` 필드 없이 `people.json` 에 기록된다 |

거부된 로그인은 `403` 이고 `people.json` 에 기록되지 않는다. 토큰과 `local` 방식의 소유자는 늘 들어온다. `*.ts.net` Host로 헤더 없이 온 요청(태그 장치 등)은 0.2.1부터 허용 목록이 없어도 `403` 이다. 0.1은 허용 목록이 있을 때만 막았고, 0.2.0은 허용 목록이 없으면 이것을 에이전트로 받았다. `--tailnet-agent` 로 0.2.0 동작을 되살려도 허용 목록이 있으면 `403` 이다. `limn member add`·`remove` 로 바꾼 명단은 재시작 없이 다음 요청부터 적용된다.

### 역할

사람마다 `people.json` 의 선택 필드 `role` 이 바꿀 수 있는 범위를 정한다. 서버는 모든 POST에서 처리 직전에 한 번 역할을 검사한다(`check_role`).

| 역할 | 누가 이 역할인가 | 허용되는 POST |
| --- | --- | --- |
| `viewer` | `role` 이 `viewer` 인 사람, 그리고 `role` 값을 알 수 없는 사람 | `/api/pick`, `/api/revision-build` 만(상태를 바꾸지 않는 계산). 그 밖은 모두 `403` |
| `agent` | 모든 토큰, 헤더 없는 루프백 에이전트, `role` 이 `agent` 인 사람 | `/api/pins/{id}/confirm`, `/api/clear`, `/api/pins/{id}/purge` 를 뺀 전부. 셋은 `403` 이다. 본문에 `review` 없이 닫으면 검토 대기로 가고, 답글은 규칙으로 핀을 다시 열지 않는다(§스레드 (답글)) |
| `editor` | `role` 이 없거나 `editor` 인 사람 | `/api/clear` 와 `/api/pins/{id}/purge` 를 뺀 전부(`403`) |
| `owner` | `role` 이 `owner` 인 사람, `local` 방식의 루프백 소유자 | 전부 |

- `GET` 은 들어온 모든 역할에 열려 있다. `viewer` 도 핀 목록, `pins.md`, PDF를 읽는다.
- 알 수 없는 `role` 값을 `viewer` 로 보는 것은 일부러다. 오타 난 역할이 전권이 되지 않고 가장 좁은 권한으로 닫힌다.
- 역할은 `limn member role` 로 바꾸고, 재시작 없이 다음 요청부터 적용된다. 서버가 사람 항목을 다시 쓸 때도 `role` 은 그대로 둔다.
- 소유자만 부를 수 있는 HTTP 경로는 둘이다. `POST /api/clear`(0.2.1부터, `OWNER_POSTS`)는 모든 핀을 한꺼번에 지우는 유일한 경로라서 확인 본문도 요구한다. `POST /api/pins/{id}/purge`(0.2.2부터, `OWNER_POST_RE`)는 휴지통의 핀 하나를 영구 삭제한다(§엔드포인트, [ADR-0004](../adr/0004-one-reply-trash-sections.md)). 나머지 소유자 동작(멤버, 토큰, 설정)은 CLI와 파일 수준이다(`limn member`, `limn token`).

`/api/meta` 와 `/api/people` 의 `me`, 그리고 `/api/people` 의 각 항목에 `role` 필드가 덧붙는다. `people.json` 에 없는 사람(예: 옛 핀의 작성자)은 `editor` 로 나온다.

### 검사 순서

한 요청이 거치는 검사는 다음 순서다. 앞에서 걸리면 뒤는 보지 않는다.

1. 본문 경계: `Transfer-Encoding`, Content-Length, 잘린 본문(`400`·`413`) — §요청 형식과 경계
2. Host·Origin(`403`)
3. 신원(`401`)
4. 입장(`403`)
5. 역할, POST만(`403`)
6. 본문 형식: `Content-Type`, JSON 객체(`415`·`400`)

역할 검사가 본문 형식보다 앞이다. 그래서 `viewer` 가 틀린 본문으로 핀을 만들려 해도 `400` 이 아니라 `403` 을 받는다.

### 헤더 없는 루프백 에이전트

0.1에서는 헤더 없이 루프백으로 온 요청을 에이전트로 봤다. 0.2.0은 이 동작을 `tailscale` 방식에서 기본으로 남겨 두되 **폐지 예정**으로 표시한다. 서버는 기동 로그와 처음 그런 요청이 왔을 때 경고를 한 번 남긴다.

- `--no-agent-loopback`(인스턴스 설정 `AGENT_LOOPBACK=0`)을 주면 이런 요청은 `401` 이다. 에이전트가 토큰을 쓰기 시작하면 끈다.
- `local`, `trusted-proxy` 방식이나 루프백이 아닌 `--bind` 에서는 늘 꺼져 있다. 거기서 `--agent-loopback` 을 요구하면 서버가 기동을 거부한다.
- 같은 머신의 로컬 프로세스는 헤더를 빼서 에이전트를, 헤더를 붙여 사람을 흉내 낼 수 있다. 여러 사람이 쓰는 머신이면 에이전트에게 토큰을 주고, 이 동작을 끄고, `--members-only` 나 역할로 좁힌다.
- **이 기기를 부른 요청에만 해당한다(0.2.1).** `tailscale serve` 도 루프백에서 붙으므로 TCP 피어만으로는 구별되지 않는다. `Host` 만으로도 구별되지 않는다. `tailscale serve` 는 TLS 이름으로 경로를 고르고 클라이언트가 보낸 `Host` 를 그대로 넘기므로, 태그 장치가 `Host: localhost` 를 보낼 수 있다. 대신 `tailscale serve` 는 `X-Forwarded-For`·`X-Forwarded-Host`·`X-Forwarded-Proto` 를 늘 스스로 채운다(클라이언트가 보낸 값은 덮어쓴다). 그래서 이런 전달 헤더(`X-Forwarded-Port`·`X-Real-IP`·`Forwarded`·`Via` 포함)가 하나라도 있거나 `Host` 가 루프백 이름이 아니면(`*.ts.net`, `--public-host`) 프록시를 거친 요청으로 보고, 신원 헤더가 없으면 에이전트로 받지 않는다(`came_through_proxy`). 로컬 에이전트의 curl 은 둘 다 보내지 않는다. `--auth local` 에서도 프록시를 거친 요청은 소유자가 아니라 `403` 이다. 헤더를 더하지 않는 원시 TCP 전달(`tailscale serve --tcp`, `ssh -L`/`-R`, 단순 포트 포워딩)은 로컬 요청과 구별되지 않는다. 그런 설정에서는 토큰을 쓰고 `AGENT_LOOPBACK=0` 을 둔다([ADR-0003](../adr/0003-tailnet-headerless-and-owner-clear.md) §남는 한계). 0.2.0은 허용 목록이 없을 때 이런 요청(태그 장치, 공용 CI 노드)을 에이전트로 받아 핀을 닫고 모두 지울 수도 있었다. 이제는 `403` 이고 메시지가 토큰을 쓰라고 알려 준다.
- `--tailnet-agent`(인스턴스 설정 `TAILNET_AGENT=1`)는 0.2.0 동작을 일부러 되살린다. 헤더 없는 루프백 에이전트가 켜져 있어야 하고(`--no-agent-loopback`, `local`, `trusted-proxy`, 루프백이 아닌 `--bind` 와 함께 주면 기동을 거부한다), 기동 로그에 폐지 예정 경고가 남는다. 허용 목록(`--allow`, `--members-only`)은 여전히 이런 요청을 막는다.

### pins.md 안내 줄

`<state_dir>/pins.md` 의 안내 문단 바로 뒤에 다음 두 줄이 늘 붙는다(§pins.md 형식). 앞 줄은 0.2.1에 더한 claim 안내이고, `<base>` 는 close 예시와 같은 base URL이다. 뒷줄은 0.2.0부터 있던 인증 안내이고, 0.2.1에서 마지막 구절(테일넷 주소의 헤더 없는 요청은 `403`)이 붙었다. 에이전트가 표를 읽는 순간 핀을 잡는 법과 인증 방법을 알게 하려는 것이다. 머리줄의 다른 줄은 바뀌지 않았다.

```text
처리를 시작하는 핀은 먼저 잡는다 — `curl -X POST -H 'Content-Type: application/json' -d '{"eta_min":15}' <base>/api/pins/N/claim`(eta_min = 예상 분, 번호 칸에 '처리 중(이름, 약 N분)' 으로 보인다) · 고치기 직전에 그 핀 하나만 잡는다 · 409 면 다른 쪽이 잡은 핀이니 건너뛴다 · 포기하면 `<base>/api/pins/N/unclaim`
에이전트 인증: 모든 요청에 `Authorization: Bearer <토큰>` 헤더를 붙인다(`curl -H "Authorization: Bearer $LIMN_TOKEN" …`, 토큰은 사용자가 `limn token create <인스턴스>` 로 발급해 준다) · 헤더 없는 로컬 요청을 에이전트로 받는 방식은 폐지 예정이다 · 테일넷 주소(원격)로 오는 신원 헤더 없는 요청(태그 장치 등)은 403 이다 — 원격 에이전트는 반드시 토큰을 붙인다
```

실행 정본은 [`src/limn/server.py`](../../src/limn/server.py) 의 `identify`, `came_through_proxy`, `admit`, `check_role`, `OWNER_POSTS`, `bearer_of`, `token_lookup`, `claim_guidance`, `TOKEN_GUIDANCE` 다.

## 문서 매개변수 (`doc=`)

한 인스턴스는 여러 문서를 함께 띄울 수 있다(`--doc`, [operations.md](operations.md) §여러 문서 (`--doc`)). 이때 문서가 걸리는 경로는 `doc=<키>` 로 대상 문서를 고른다.

| 방식 | 경로 |
| --- | --- |
| `GET` 쿼리 | `/api/meta`, `/api/build`, `/pdf`, `/pages/<쪽>`, `/api/snippet`, `/api/overlaps`, `/api/pins`(그 문서의 핀만 거른다), `/api/revisions`, `/api/revision-diff`, `/api/outline-labels`, `/api/revision-build`, `/api/revision-pdf` |
| `POST` 쿼리 또는 JSON 본문 | `/api/pick`, `/api/pin`, `/api/rebuild`, `/api/revision-build` |

규칙은 다음과 같다.

- `doc` 이 없으면 첫 문서다.
- POST는 쿼리와 JSON 본문의 `doc` 을 둘 다 받는다. 둘이 다르면 `400` 이다.
- `POST /api/pin` 에 `doc` 없이 `file` 만 오면 문서를 짐작한다. 에이전트의 `curl` 이 이런 요청을 보낸다. 서버는 그 파일을 빌드 루트가 가장 깊게 감싸는 LaTeX 문서를 고른다.
- 없는 키는 `404 {error, docs:[키…]}` 다. 조용히 첫 문서로 물러서지 않는다. 물러서면 핀이 다른 문서에 붙기 때문이다.
- 핀 id로 가는 경로(`/api/pins/{id}/…`)는 `doc` 이 필요 없다. 핀의 문서는 레코드에 들어 있다.
- 단일 문서 인스턴스는 `doc` 을 무시해도 된다. 그 문서의 키는 `main` 이다.

## 엔드포인트

경로를 성격별로 나눴다. 표의 "§" 참조는 이 문서 안의 절이다. 모든 경로는 먼저 §인증의 신원·입장 검사를 거치고, POST는 역할 검사도 거친다.

### 버전·상태·사람

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/version` | `{"name":"limn","version":<문자열>}`. `limn serve --version` 과 같은 값이다. 지금 인스턴스가 어느 설치 버전으로 도는지 확인할 때 쓴다. 쓰기 없음 |
| `GET` | `/api/meta` | `pages`(쪽 목록), `built_at`, `head`(원고 커밋), `main`(최상위 `.tex` 이름), `label`·`accent`·`repo`(이 인스턴스의 이름표·강조색·git origin URL, [operations.md](operations.md) §여러 논문 인스턴스를 동시에 띄울 때), `n_open`·`n_review`·`n_done`(§검토 대기), `pins_md`·`state_dir`(절대경로), `me`(지금 요청자. 0.2.0부터 `role` 이 붙는다 — §인증), `building`(재빌드 진행 중), `stale_build`(이 PDF 를 만든 뒤 원고 `.tex` 가 바뀌었는가), `src_mtime`·`build_src_mtime`·`src_age_s`·`pins_rev`([build-sync.md](build-sync.md) §자동 동기화 (가벼운 meta 폴링)), `pages_build`(지금 화면의 빌드 id, `pages.cur` 값), `build_seq`(끝난 빌드 수)·`last_build:{state,errors,finished_at,seq}`·`build:{state,phase,started_at}`([build-sync.md](build-sync.md) §비동기 재빌드), `doc`·`doc_name`·`kind`·`view_only`·`multi`(§문서 매개변수), `ev_seq`(§브라우저 알림 커서). 여러 문서면 `docs`(`/api/docs` 항목에서 `n_open` 을 뺀 것)와 `src_sig` 가 붙는다(라이트 포함). `src_sig` 는 문서마다의 `src_mtime` 을 이은 문자열이다. 그래서 뷰어는 다른 문서의 원고가 바뀌어도 목록을 다시 읽는다. 전체 meta는 요청한 사람을 기록한다(§@태그·사람·이벤트) |
| `GET` | `/api/meta?light=1` | 위와 같되 `n_open`·`n_review`·`n_done` 이 없고 **쓰기를 하지 않는다**(`snapshot_pins()` 의 sync 쓰기를 하지 않는다). 폴링 전용이다. [build-sync.md](build-sync.md) §자동 동기화 (가벼운 meta 폴링) |
| `GET` | `/api/meta?ev=<seq>` | 라이트와 함께 쓸 수 있다. 요청자에게 온 새 이벤트를 `events` 로 싣는다 — §브라우저 알림 커서 |
| `GET` | `/api/docs` | 문서 목록 `{docs:[{key,name,kind:"tex"\|"pdf",view_only,path,main,n_open,stale_build,building,build:{state,phase},build_seq,last_state,pages_build,n_pages,src_mtime}], default, multi, other_open}`. 핀은 읽기만 한다(sync 쓰기 없음). `other_open` 은 지금 설정에 없는 문서 키의 열린 핀 수다 |
| `GET` | `/api/people` | @태그 후보 `{people:[{login,name,pic?,last_seen?,role}], me}` — §@태그·사람·이벤트. `role` 과 `me.role` 은 §인증. 쓰기 없음 |

### 화면·PDF·정적 파일

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/` | 뷰어 HTML. 이 뷰어를 연 사람을 기록한다(§@태그·사람·이벤트). 에이전트(토큰, 헤더 없는 루프백 요청)는 기록하지 않는다 |
| `GET` | `/pages/<파일>` | 지금 빌드의 쪽 이미지(`page-<번호>.png`)를 `image/png` 로 준다. 이름이 이 모양이 아니거나 파일이 없으면 `404` |
| `GET` | `/pdf?build=<pages_build>` | 그 빌드의 쪽 이미지와 짝인 PDF 사본(`pages-<build>/<main>.pdf`)을 `application/pdf` 로 준다(`Cache-Control: private, max-age=600`). 뷰어가 벡터로 그릴 때 쓴다([viewer.md](viewer.md) §벡터 렌더링). `build` 를 빼면 지금 빌드다. 이름이 틀렸거나, 이미 지워졌거나, 그 디렉토리에 PDF 가 없으면 `404 {error, pdf_build_gone, pages_build}` 다. `build/` 나 다른 빌드로 물러서지 않는다. 화면의 쪽 이미지와 어긋나면 좌표가 틀리기 때문이다. `Range` 는 받지 않고 통째로 준다. Host·Origin 검사는 다른 `GET` 과 같다 |
| `GET` | `/vendor/pdfjs/<파일>.mjs` | 뷰어가 쓰는 PDF.js(`pdf.min.mjs`·`pdf.worker.min.mjs`)를 `text/javascript; charset=utf-8` 로 준다(`Cache-Control: public, max-age=86400`). 뷰어는 `?v=<버전>` 을 붙여 캐시를 가른다. 이름 한 칸의 `.mjs` 만 받는다. 하위 경로, `..`, 점으로 시작하는 이름, `%` 인코딩, 디렉토리 밖을 가리키는 심볼릭 링크, `.mjs` 가 아닌 파일(`LICENSE`·`README.md`)은 모두 `404` 다. PDF.js는 패키지 안 `src/limn/vendor/pdfjs/` 에 들어 있고 기본으로 이것을 준다. `--pdfjs-dir`([operations.md](operations.md) §실행 인자)로 디렉토리를 바꿀 수 있다. 출처·버전은 [`src/limn/vendor/pdfjs/README.md`](../../src/limn/vendor/pdfjs/README.md). Host·Origin 검사는 다른 `GET` 과 같다 |
| `GET` | `/api/outline-labels?doc=<키>` | 현재 PDF와 함께 보존한 `.aux` 의 목차 → `{build,labels:[{number,title,page,level,anchor}]}`. PDF.js outline과 제목·계층·순서가 일치할 때만 번호를 붙인다. `page` 는 인쇄 쪽번호 문자열(로마 숫자 가능)이며 물리 PDF 페이지 인덱스가 아니다. `.aux` 가 없는 기존 빌드는 빈 배열이다. 지원하지 않는 복잡한 TeX 제목은 빈 `number`·`title` 자리표시자가 된다 |
| `GET` | `/sw.js` | 브라우저 알림용 서비스 워커(`text/javascript; charset=utf-8`, `Cache-Control: no-cache`, 범위 `/`). `fetch` 처리기가 없어 앱 데이터를 캐시하지 않는다 |
| `GET` | `/favicon.ico` | 빈 본문 `204` |

### 빌드

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/build` | `{state:"idle\|running\|ok\|ok_errors\|fail", phase:"pull\|copy\|latex\|render"\|null, started_at, finished_at, seq, last, elapsed_s, last_s, pages, errors:[{line,msg}], log_tail, built_at, head, pull}` — [build-sync.md](build-sync.md) §비동기 재빌드. 서버를 다시 띄워도 마지막 빌드 결과(`state`·`errors`·`log_tail`·`seq`·`head`·`pull`)는 `builds.json` 에서 되살린다. `log_tail` 은 [build-sync.md](build-sync.md) §에이전트 응답 다이어트를 따른다. `state=="ok"` 면 빠지고, 아니면 40줄이며, `?log=1` 이면 전체다 |
| `POST` | `/api/rebuild` | PDF 재빌드(동기) — [build-sync.md](build-sync.md) §재빌드 (동기). 응답에 `head`(빌드한 커밋의 짧은 해시, 성공 때만)와 `pull`(`--git-pull` 일 때만, [build-sync.md](build-sync.md) §재빌드 전 원격 main 당겨오기 (`--git-pull`))이 붙는다. `log` 는 [build-sync.md](build-sync.md) §에이전트 응답 다이어트를 따른다. 보기 전용 문서면 `400` |
| `POST` | `/api/rebuild?async=1` | PDF 재빌드(비동기). 잠금을 얻으면 데몬 스레드로 같은 빌드 함수를 돌리고 바로 `202 {"state":"running"}` 을 준다. 이미 도는 중이면 `409 {"state":"running","busy":true}`. 진행은 `GET /api/build` 로 폴링한다([build-sync.md](build-sync.md) §비동기 재빌드) |
| `POST` / `GET` | `/api/rebuild?log=1` / `/api/build?log=1` | [build-sync.md](build-sync.md) §에이전트 응답 다이어트를 끄고 전체 로그 꼬리(4000자)를 그대로 받는다. 뷰어는 오류 패널을 위해 이 플래그를 항상 붙인다 |

### 변경 보기와 비교 PDF

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/revisions?doc=<키>` | 선택한 메인 `.tex` 폴더의 `.tex`·`.bib`·`.sty`·`.cls`·`.bst` 파일을 바꾼 최근 Git 커밋 12개 → `{available,revisions:[{id,date,subject}]}`. Git 저장소가 아니거나 보기 전용 PDF면 `available:false` |
| `GET` | `/api/revision-diff?doc=<키>&commit=<40자리 SHA-1>` | 위 목록에 나온 커밋의 실제 unified diff → `{id,diff,truncated}`. 선택한 메인 파일 폴더 안의 같은 원고 확장자만 포함하고 최대 256 KiB를 보낸다. 잘못된 ID는 `400`, 목록 밖 ID와 보기 전용 PDF는 `404`. 0.3부터 선택 `&pin=<번호>` 를 주면 `scope` 를 더한다(§핀 단위 변경 보기). 빈 `pin=` 은 없는 것과 같다. `pin` 이 양의 정수가 아니면 `400`, 이 문서의 핀이 아니면 `404` |
| `POST` | `/api/revision-build` | 본문 `{commit,doc?,pin?}`. 선택 커밋의 첫 부모 → 선택 커밋 비교 PDF를 비동기로 시작한다. `202 {state:"running",job_id,base,head,engine,warnings,error,reason}`, 성공 캐시가 있으면 `200 {state:"ready",…}`. `doc` 은 쿼리로도 받는다. 0.3의 선택 `pin`(정수)을 주면 그 핀의 변경만 적용한 비교가 되고 상태에 `scope`·`pin`·`source`·`hunks`·`other` 가 더해진다(§핀 단위 변경 보기). 그 밖의 필드가 있거나 `pin` 이 정수가 아니면 `400` |
| `GET` | `/api/revision-build?doc=<키>&commit=<40자리 SHA-1>[&pin=<번호>]` | 같은 상태 스키마를 조회한다. `state` 는 `idle`(미실행·만료), `running`, `ready`, `error`. `error` 는 설명, `reason` 은 오류 분류다. 매번 현재 문서의 최근 커밋 목록을 다시 확인한다 |
| `GET` | `/api/revision-pdf?doc=<키>&commit=<40자리 SHA-1>[&pin=<번호>]` | 성공한 같은 비교의 PDF(`Cache-Control: private, max-age=600`). 미완성·실패·만료는 `404` 이며 현재 원고 PDF로 대체하지 않는다. 현재 쪽·SyncTeX·핀 좌표와 무관한 열람 전용 결과다 |

실행 조건과 캐시는 아래 §비교 PDF 실행과 캐시에, 핀 하나의 변경만 가르는 규칙은 §핀 단위 변경 보기에 있다.

### 핀 읽기

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `GET` | `/api/pins` | 열린 핀 목록(JSON). 레코드마다 `rev`, `rel`(§겹친 핀과 덧붙이기), `est`(불리언, [build-sync.md](build-sync.md) §위치 추정 (`est`)), `state`(§검토 대기)가 채워진다. `rel`·`est`·`state` 는 계산 필드라 저장하지 않는다. `?all=1` 이면 닫힌 핀까지 준다. 이 경로는 줄 맞춤(sync) 쓰기를 한다 |
| `GET` | `/api/pins/{id}` | 핀 한 건 `{pin}`. `GET /api/pins?all=1` 의 한 항목과 같은 모양이다(스레드 전부와 계산 필드 포함). 없으면 `404` |
| `GET` | `/api/pins/dropped` | 휴지통 → `{dropped: [...]}`. `pins.dropped.jsonl` 을 `dropped_at` 순으로 그대로 낸다(쓰기 부작용 없음). 계산 필드는 0.2.2에서 더한 `expires_ts`(지워질 시각, epoch 초) 하나다. `dropped_at` 에서 30일(`TRASH_DAYS`)이 지난 항목은 싣지 않는다(§휴지통). 뷰어의 휴지통이 이것을 쓴다. 열린 목록에서 사라진 핀이 완료인지 삭제인지 가르는 알림도 이것을 쓴다([build-sync.md](build-sync.md) §자동 동기화 (가벼운 meta 폴링)) |
| `GET` | `/pins.md` | 원격 에이전트 진입점. `<state_dir>/pins.md` 와 같은 내용을 `text/markdown; charset=utf-8` 로 낸다. `GET /api/pins` 와 같은 sync 경로를 탄 뒤 렌더한다. 안내 줄의 base URL만 요청 `Host` 에 맞춘다. `Host` 가 `*.ts.net` 이면 `https://<Host 그대로>`, `--public-host` 이름이면 `https://<이름>[:<포트>]`, 루프백이면 기존 `http://127.0.0.1:<port>` 다. 디스크의 `<state_dir>/pins.md` 는 항상 루프백 base다. Host·Origin 검사는 다른 `GET` 과 같다 — §원격 에이전트 진입점 (`GET /pins.md`) |
| `GET` | `/api/snippet?file=&lo=&hi=` | 원문 줄 스니펫(80줄 캡). `&levels=1` 이면 그 범위를 기준으로 한 범위 사다리도 준다. 원고 트리 밖이거나 범위가 틀리면 `400`. 보기 전용 문서면 `400` |
| `GET` | `/api/overlaps?file=&lo=&hi=` | 그 범위(저장 전 선택)와 열린 핀의 겹침 `{overlaps}`. 뷰어는 더 이상 쓰지 않는다(§겹친 핀과 덧붙이기). 에이전트와 옛 뷰어 호환용으로 남긴다 |

### 핀 만들기와 상태 바꾸기

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| `POST` | `/api/pick` | 드래그 좌표를 원문 위치로 되짚는다. 입력은 `page`, `x0`, `y0`, `x1`, `y1` 이다. 선택 `frac` 은 쪽 대비 비율 숫자 4개 목록 `[x, y, w, h]` 이고, 다른 모양이면 `400`. 선택 `pdf_build` 는 드래그할 때 화면의 빌드 id이며, 그 빌드의 PDF로 되짚는다. 그 빌드가 이미 지워졌으면 `200 {error, pdf_build_gone:true}`, 모양이 틀리면 `400`. 응답은 `{file, name, lo, hi, raw_lo, raw_hi, kind, via, score, warn, snippet, frac, levels, default_level, n_lines, quote, overlaps, pdf_build}`. `quote` 는 선택 영역 글자를 공백 정규화해 자른 60자다. `overlaps` 는 같은 파일의 열린 핀과의 겹침이다(§겹친 핀과 덧붙이기). 입력 오류는 `400`, 되짚기 실패는 `200 {error}`. `levels`·`via`·`score` 의 뜻은 [domain.md](domain.md) §범위 사다리와 §역변환이 두 경로인 이유 |
| `POST` | `/api/pin` | 새 핀 추가 → `{id}`. 저장 필드 화이트리스트는 `file, name, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, note, scope, quote, pdf_build`. 선택으로 `kind_req`(§스레드 (답글)), `mentions`(힌트), `assignee`(담당, §@태그·사람·이벤트)를 받는다. `pdf_build` 를 안 보내면(에이전트 `curl`) 지금 빌드로 찍는다 |
| `POST` | `/api/pins/{id}/edit` | 제자리 수정 — §핀 수정 (`/api/pins/{id}/edit`) |
| `POST` | `/api/pins/{id}/close` | 핀 한 건을 닫는다(`done: true`, `closed_by`). 에이전트가 닫으면 검토 대기(`review: true`), 사람이 닫으면 완료다 — §검토 대기. 선택 본문 `{"reply", "ref", "changes", "review"}` — §닫을 때 사유 남기기. 레코드는 남는다. `<state_dir>/pins.md` 에서는 열린 표에서 빠지고 머리줄 건수로만 남는다(§pins.md 형식). 응답은 `{ok, pin, state}`. 그 id가 없으면 `200 {"ok": false, "pin": null}` 이다(reopen도 같다). **이미 닫힌 핀을 다시 닫으면 `{ok: true, pin}` 을 그대로 돌려주고 아무 필드도 바꾸지 않는다.** `rev` 도 그대로다 |
| `POST` | `/api/pins/{id}/reopen` | 닫은 핀을 되돌린다(`reopened_by`). `close_reply`·`close_ref`·`changes`·`review`·`confirmed_*` 가 있었으면 지운다. 다시 닫을 때 새로 남기기 위해서다. 선택 본문 `{"reason"}` 은 스레드에 남는다 → `{ok, pin, state}`. 0.2.2부터 뷰어에는 [다시 열기] 버튼이 없다. 사람의 답글이 규칙으로 다시 연다(§스레드 (답글)). 이 경로는 호환과 [완료]의 되돌리기에 남는다 |
| `POST` | `/api/pins/{id}/confirm` | 검토 대기 → 완료. 사람만 누를 수 있다. 에이전트 역할(토큰 포함)이면 `403` 이다 → `{ok, pin, state}` — §검토 대기, §인증 |
| `POST` | `/api/pins/{id}/reply` | 답글 `{"text", "mentions"?, "reopen"?}` → `{ok, pin, msg, state, reopened}`. 닫힌 핀에 사람이 단 답글은 규칙에 따라 핀을 다시 열 수 있다 — §스레드 (답글) |
| `POST` | `/api/pins/{id}/drop` | 핀을 목록에서 빼 휴지통(`pins.dropped.jsonl`)으로 옮긴다(`dropped_by`) → `{ok}`. 없는 id면 `200 {"ok": false}`. 작성자가 아닌 쪽이 지우면 작성자에게 `dropped` 이벤트가 간다(§이벤트). 같은 쓰기에서 30일이 지난 휴지통 항목을 뺀다 |
| `POST` | `/api/pins/{id}/restore` | 삭제한 핀을 같은 id로 되살린다. 서버를 다시 띄운 뒤에도 된다(`restored_by`). 응답은 `200 {ok, pin}`, 휴지통에 없으면(30일이 지난 항목 포함) `404`, 같은 id가 이미 있으면 `409` |
| `POST` | `/api/pins/{id}/purge` | 휴지통의 핀을 영구 삭제한다(0.2.2). **`owner` 역할만**(그 밖은 `403`). 휴지통에 없으면(열린·닫힌 핀 포함) `404` → `{ok, purged: <id>}`. `purged` 감사 이벤트와 서버 로그를 남긴다. 번호는 다시 쓰이지 않는다 — §휴지통 |
| `POST` | `/api/pins/{id}/claim` | 처리 중 표시를 걸거나, 같은 신원이면 연장한다 — §처리 중 표시 (claim). 선택 본문 `{"eta_min": 1..240, "ttl_min": 1..120}`. 정수가 아니거나 1보다 작으면 `400`, 상한을 넘으면 상한으로 깎는다. 응답은 `{ok, pin, ttl_min_applied, eta_min_applied?}`. 다른 신원이 유효한 claim을 쥐고 있으면 `409 {"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}`. 닫힌 핀이면 `409 {"error":"done","pin":...}`. 없는 id면 `200 {"ok": false}` |
| `POST` | `/api/pins/{id}/unclaim` | 처리 중 표시를 지운다. claim을 건 신원과 무관하다. claim은 잠금이 아니라 표시이기 때문이다 → `{ok, pin}`. 없는 id면 `200 {"ok": false}`. `viewer` 역할은 다른 변경처럼 `403` 이다 |
| `POST` | `/api/clear` | 전체를 아카이브하고 비우는 일괄 리셋이다. **`owner` 역할만** 부를 수 있고(0.2.1부터, 그 밖은 `403`), 본문 `{"confirm": "clear all pins"}` 가 있어야 한다(없거나 다르면 `400`). 아카이브 이름은 `pins_<timestamp>.jsonl.bak` 이고, 같은 초에 또 비우면 `pins_<timestamp>-1.jsonl.bak` … 로 이어진다. id 발급 번호는 이어진다. 응답은 `{"ok": true, "cleared": <지운 핀 수>, "archive": "<보관본 이름>"}` 이고, 누가 했는지 `cleared` 이벤트와 서버 로그에 남는다. 뷰어는 이 경로를 쓰지 않는다. **에이전트는 쓰지 않는다** |

## 비교 PDF 실행과 캐시

변경 보기의 비교 PDF는 선택 커밋이 원고를 어떻게 바꿨는지 PDF 위에 강조해 보여 준다. 비교 대상은 **선택 커밋의 첫 부모 → 선택 커밋**이다. 합병 커밋도 첫 부모를 쓴다.

- 저장소의 첫 커밋은 부모가 없으므로 `422 reason:no_parent` 다.
- Git 객체에서 빌드 루트의 두 스냅샷을 만든다. 커밋하지 않은 수정은 포함하지 않는다.
- 과거 커밋에 현재 메인 경로가 없으면 `missing_main` 으로 실패한다. 이름을 바꾸기 전 경로를 추측하지 않는다.

### 실행 환경과 격리

Linux의 `bwrap`, `latexdiff`, `latexmk` 가 필요하다. 실행 파일은 `/usr` 아래 시스템 설치본만 허용한다. 두 명령은 bwrap 격리 안에서 돈다. 이 격리는 홈 디렉토리, 원본 저장소, 네트워크를 노출하지 않는다.

```text
latexdiff --flatten --math-markup=off
latexmk -norc -pdf -no-shell-escape -interaction=nonstopmode -halt-on-error
```

격리 실행이 불가능하면 실패한다. 격리 없이 다시 시도하지 않는다. 현재 비교 엔진은 pdfLaTeX다. XeLaTeX·LuaLaTeX 전용 원고는 소스 변경사항으로 확인한다. kotex 같은 원고 패키지를 임의로 제거하지 않는다.

### 한도

`input`·`include`·`subfile` 등은 각 Git 스냅샷 안에서 펼친다. 포함 파일이 없으면 비교 PDF를 성공으로 처리하지 않는다. 심링크, gitlink, 경로 이탈은 거부한다. 시간 초과나 출력 초과가 나면 프로세스 그룹을 통째로 종료한다.

| 대상 | 한도 |
| --- | --- |
| 파일 하나 | 64 MiB |
| 스냅샷 하나 | 256 MiB, 4,000개 |
| 비교 PDF | 32 MiB |
| 두 프로세스 파이프 출력의 합 | 기본 8 MiB |
| Git 사본 만들기 | 각각 60초 |
| `latexdiff` | 60초 |
| `latexmk` | 서버 `--timeout` 과 180초 중 작은 값 |

### 상태와 캐시

비교 상태는 문서별 `<state>/revisions/` 에 보존한다. 캐시 키에는 저장소, 빌드 루트, 메인 경로, 두 전체 SHA, 엔진, 구현 버전이 들어간다. 핀 하나의 변경만 적용한 비교(0.3)는 여기에 핀 번호와 고른 블록 목록이 더해진다. 그래서 (핀, 커밋, hunk 집합)마다 한 비교이고, 커밋 전체 비교와 캐시를 나누지 않는다. 핀이 커밋 전체를 가지거나 하나도 없으면 커밋 전체 비교의 키를 그대로 쓴다. 성공 PDF와 상태는 작업이 끝난 뒤에 확정한다. 원고의 `pages.cur`, `builds.json`, 핀은 바꾸지 않는다.

- 프로세스 전체에서 동시에 최대 두 작업, 한 문서 상태 폴더에서 최대 한 작업을 허용한다.
- 같은 작업을 다시 요청하면 기존 상태를 돌려준다. 다른 작업이 자리를 차지했으면 `409 reason:busy` 다.
- 문서별 캐시는 최대 여섯 비교, 24시간이며 다음 요청 때 정리한다.
- 도중에 서버가 재시작된 작업은 다음 요청에서 다시 만든다. 실패한 작업은 POST로 다시 시도할 수 있다.

### 경고와 로그

경고는 실패와 구분한다. 다음 경우는 PDF가 나와도 강조가 불완전할 수 있다.

- 삭제된 문장이 옛 라벨을 참조하면 `??` 가 생길 수 있다.
- 수식 내부의 변경과, 같은 파일명인 그림 바이너리의 변경은 강조되지 않을 수 있다.
- 서지·스타일·주석만 바뀐 커밋은 본문에 강조가 없을 수 있다.

응답은 `warnings` 를 싣고, 원래 소스 diff 경로를 함께 제공한다. 서버 쪽 `build.log` 는 마지막 8,000자만 보존한다. HTTP 응답에는 로그 전체를 노출하지 않는다.

## 핀 단위 변경 보기

0.3부터 변경 보기의 세 경로(`/api/revision-diff`, `/api/revision-build`, `/api/revision-pdf`)가 선택 `pin` 을 받는다. 한 커밋이 핀 여럿을 고쳤을 때 그 핀의 변경만 보이기 위해서다. 결정과 버린 대안은 [ADR-0005](../adr/0005-pin-scoped-changes.md)에 있다. `pin` 이 없는 요청의 응답은 0.2.2와 같다.

### 핀의 hunk를 고르는 순서

커밋을 파일마다 `git diff -U0` 의 hunk(블록)로 나눈다. 이름 바꾸기는 찾아 짝짓는다(`-M`). 첫 부모와 비교한다.

| 순서 | 고르는 것 | `source` |
| --- | --- | --- |
| 1 | 핀의 `changes`(새 쪽 줄 범위)와 겹치는 블록 | `changes` |
| 2 | 1이 아무것도 못 고르면, 핀 범위를 커밋에 비춰 겹치는 블록 | `inferred` |
| 3 | 2도 못 고르면 없음. 커밋 전체를 보인다 | `none` |

- 2의 핀 범위는 이렇게 정한다. 닫힌 핀은 마지막 줄 맞춤의 번호를 지니는데, 그 번호가 커밋의 새 쪽인지 옛 쪽인지는 기록이 없다. 그래서 anchor를 새 쪽과 옛 쪽 모두에서 기록된 줄 가까이 찾고(`sync_all()` 과 같은 규칙), 기록된 줄에 더 가까운 쪽부터 쓴다(같으면 새 쪽). 거기서 블록이 안 겹치면 다음 후보로 간다. 마지막 후보는 날 범위다. `stale` 이면 옛 쪽, 아니면 새 쪽으로 읽는다.
- 핀 파일은 짝의 옛 이름이든 새 이름이든 맞으면 된다.
- 한쪽이 빈 블록(순수 삽입·삭제)은 그 자리 앞뒤 줄에 닿은 것으로 본다. 지운 줄 바로 앞이나 뒤를 가리켜도 그 삭제를 고른다.
- 원고 파일이 60개(`SCOPE_FILES_MAX`)를 넘게 바뀌었거나, 두 쪽 합계가 16 MiB(`SCOPE_BYTES_MAX`)를 넘거나, git 읽기가 모두 합쳐 60초(`SCOPE_SECONDS_MAX`)를 넘거나, 파일 이름이 UTF-8이 아니면 가르지 않는다(`none`).
- 블록은 `git diff -U0 --inter-hunk-context=0` 으로 읽는다. 사용자의 `diff.interHunkContext` 설정이 가까운 두 핀의 블록을 하나로 붙이지 못하게 하려는 것이다.
- 핀의 줄 번호는 `str.splitlines()`(`tex_lines`)로 센 번호이고 git은 줄바꿈 문자(`\n`)로만 센다. 폼 피드·홀로 쓴 CR·U+2028 같은 문자가 있으면 둘이 어긋나므로, anchor 찾기와 날 범위는 splitlines 번호로 하고 git 번호로 바꿔 블록과 견준다.
- `changes` 는 그것을 적은 닫기(`changes_at` = 그때의 `done_at`)일 때만 쓴다. 0.2.2로 되돌린 동안 다시 열고 닫으면 0.2.2가 `changes` 를 지우지도 새로 적지도 않으므로, 이전 닫기의 줄을 이번 커밋에 쓰지 않으려는 것이다.

### `GET /api/revision-diff?pin=`

응답에 `scope` 를 더한다. `diff`(커밋 전체)·`truncated` 는 그대로다.

| 필드 | 뜻 |
| --- | --- |
| `pin` | 요청한 핀 번호 |
| `mode` | `pin` = 핀이 커밋의 일부만 가진다. `commit` = 커밋 전체가 핀의 것이거나, 하나도 아니거나, 가를 수 없었다. 뷰어는 `commit` 이면 0.2.2와 똑같이 보인다 |
| `source` | `changes`·`inferred`·`none` (위 표) |
| `hunks` / `other` | 핀의 것 / 나머지 바뀐 자리(블록) 수. 이름만 바뀐 파일·바이너리 파일은 나머지 한 자리다 |
| `diff` / `other_diff` | `mode` 가 `pin` 일 때만. 핀의 블록 / 나머지 블록만 담은 unified diff(각각 UTF-8 최대 256 KiB, 잘렸으면 `truncated` / `other_truncated` 가 `true`). 앞뒤 3줄 맥락은 이웃 블록에서 멈추므로 다른 핀의 변경이 맥락 줄로 끼지 않는다. 새 쪽 줄 번호는 커밋의 실제 번호다 |

### 비교 PDF

`mode` 가 `pin` 이면 새 쪽을 **옛 판 + 핀의 블록만** 적용한 합성 판으로 만들어 옛 판과 latexdiff 한다. 옛 스냅숏을 한 번 더 떠서 블록을 적용하고, 파일은 옛 이름을 지킨다(핀의 것인 이름 바꾸기는 제자리 수정). 더한 파일은 쓰고 지운 파일은 지운다. 실행은 §비교 PDF 실행과 캐시의 격리 파이프라인과 한도를 그대로 쓴다. 상태 응답에 `scope`(`pin`|`commit`)·`pin`·`source`·`hunks`·`other` 가 더해진다. 합성 판이 컴파일되지 않으면 그 비교는 `state:"error"` 이고, 뷰어가 커밋 전체 비교로 넘어간다. 두 SHA-1과 파이프라인이 같으면 결과도 같으므로, 핀 비교의 컴파일·diff 실패(`compile_failed`·`diff_failed`·`scope_failed`)는 캐시가 살아 있는 동안 POST에 다시 빌드하지 않고 그 오류를 돌려준다. 커밋 전체 비교는 예전처럼 다시 시도한다. 상태 파일(`status.json`)에는 요청마다 다른 `scope`·`pin`·`source`·`hunks`·`other` 를 저장하지 않는다. 이 절의 거부(이 문서의 핀이 아님, 핀의 블록을 다시 읽지 못함·찾지 못함, 허용되지 않는 경로)는 안쪽 코드가 이유만 담은 `ScopeRejected` 로 내고, 상태 코드·한국어 문구·`reason` 은 한 표 `SCOPE_REJECTIONS` 가 정한다(요청은 `Handler._run`, 빌드 상태는 워커). 문구는 계약이라 `test_v03.ScopedErrorBodies` 가 본문을 그대로 고정한다. 커밋 전체 비교를 여러 핀과 `pin` 없는 요청이 함께 쓰기 때문이다.

## 핀 수정 (`/api/pins/{id}/edit`)

```json
{"note": "고친 메모", "lo": 185, "hi": 262, "scope": "env2", "kind": "env:minipage", "base_rev": 3}
```

- **`base_rev` 는 필수다.** 수정하려는 핀을 읽을 때 받은 `rev` 를 보낸다. 다르면 `409 {"error":"conflict","pin":<최신>}` 이고 아무것도 바뀌지 않는다. 다른 에이전트가 먼저 닫았거나 자동 줄 맞춤이 옮긴 핀을 옛 `lo`·`hi` 로 조용히 덮어쓰지 않기 위해서다. `409` 를 받으면 응답의 최신 `pin` 을 보고 다시 보낸다.
- **위치를 통째로 바꿀 때는 `loc` 을 보낸다.** 모양은 `loc: {file, page, lo, hi, raw_lo, raw_hi, kind, via, score, frac, scope, pdf_build}` 이고, 이것을 "위치 다시 잡기"라 부른다. 필수는 `file`·`lo`·`hi` 다. `loc` 에 없는 `page`·`frac` 은 기존 값을 둔다. `kind` 가 없으면 `lines` 가 되고, 나머지 위치 필드는 지워진다. id, 메모, 작성자는 그대로다.
- **`pdf_build` 는 `loc` 에 `frac` 이 있을 때만 바뀐다.** 이때 값은 `loc` 에 담긴 `pdf_build` 다. 뷰어는 여기에 pick 응답 값을 넣는다. 둘 다 없으면 지금 빌드다. 메모, `note_append`, `lo`·`hi` 만 고치는 편집은 `pdf_build` 를 건드리지 않는다.
- **범위가 바뀌면 `anchor` 를 새로 뜨고 `stale`·`sync` 를 지운다.** 위치를 잃은(`stale`) 핀도 이 경로로 고친다.
- **닫힌 핀은 메모만 고칠 수 있다.** 범위나 위치를 보내면 `409 {"error":"done"}` 이다.
- 성공하면 `edited_at`·`edited_by` 가 기록되고 `rev` 가 1 오른다.

### 메모 덧붙이기 (`note_append`)

`note_append` 는 `base_rev` 없이도 받는다. 겹친 핀에 "덧붙이기"를 할 때마다 최신 `rev` 를 먼저 조회하지 않아도 되게 하려는 것이다(§겹친 핀과 덧붙이기). 서버는 `note += "\n(추가 HH:MM) " + note_append` 로 붙인다.

- 빈 문자열이나 공백만 있으면 `400` 이다. 조각 하나는 2000자 이하여야 한다.
- 합친 길이가 메모 상한(`NOTE_MAX`, 4000자)을 넘으면 `400` 이고 아무것도 바뀌지 않는다. 조각이 2000자 이하여도 기존 메모와 합치면 넘을 수 있다.
- 되돌리려면 응답의 `pin.rev` 를 `base_rev` 로 삼아 `{"note": <이전 note>}` 를 다시 보낸다.

## 닫을 때 사유 남기기

`POST /api/pins/{id}/close` 는 선택 본문으로 닫는 사유를 받는다.

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/close \
  -H 'Content-Type: application/json' \
  -d '{"reply": "제목을 …로 바꿈", "ref": "PR #227 (abc1234)", "changes": [{"file": "main.tex", "lo": 12, "hi": 14}]}'
```

- **에이전트는 무엇을 고쳤는지와 커밋을 남긴다.** `reply` 에는 고친 내용(≤500자), `ref` 에는 참조(≤80자)를 적는다. 서버에는 둘 다 선택이다. 나중에 공저자가 닫힌 핀을 볼 때 원고를 다시 뒤지지 않고도 왜 닫혔는지 알 수 있다.
- **에이전트 규칙(0.3).** 에이전트는 닫을 때 늘 `changes` 를 보내고 `ref` 에 `PR #번호 (커밋 해시)` 를 적는다. 해시는 그 수정이 들어간 커밋이다. 원고 저장소가 PR을 스쿼시 머지하고 에이전트가 머지 뒤에 닫으면 `main` 의 머지 커밋이고, `changes` 의 번호도 그 커밋이 만든 판(머지된 `main`) 기준이다. 뷰어는 `ref` 의 해시로 커밋을 찾고, 그 커밋 안에서 `changes` 로 핀의 hunk를 고른다. 핀마다 커밋을 나누면 커밋이 곧 핀이라 더 좋지만 필수는 아니다. 서버가 강제하지는 않는다([ADR-0005](../adr/0005-pin-scoped-changes.md)).
- **`changes`(0.3, 서버에는 선택).** `[{file, lo, hi}]` 는 `ref` 의 커밋에서 **이 핀 때문에** 바꾼 줄 범위다. 줄 번호는 그 커밋 뒤(새 쪽) 기준이고, `file` 은 `pins.md` 위치 칸처럼 `--manuscript` 기준 상대 경로이거나 그 안의 절대 경로다. 목록이고 50개(`CLOSE_CHANGES_MAX`) 이하, 항목마다 `file`·`lo`·`hi` 세 필드만, `lo`·`hi` 는 `1 ≤ lo ≤ hi ≤ 1,000,000` 인 정수(불리언 아님), `file` 은 비어 있지 않고 1,024자 이하이며 NUL이 없고 풀어 쓴 경로가 원고 폴더 안이어야 한다. 어기면 `400` 이고 아무것도 바뀌지 않는다. 빈 목록은 없는 것과 같다. 첫 닫기에만 절대 경로로 풀어 `changes` 에 저장하고(그 닫기의 `done_at` 을 `changes_at` 에 함께), 다시 닫아도 바뀌지 않으며, 다시 열기가 지운다. `GET /api/pins`·`/api/pins/{id}` 에 그대로 나오고 `pins.md` 에는 싣지 않는다.
- 본문이 없거나 비어 있으면(빈 문자열·공백만) 예전과 같이 동작한다. 옛 에이전트의 본문 없는 `curl -X POST …/close` 는 그대로 통과한다.
- 문자열이 아니거나 상한을 넘으면 `400` 이고 아무것도 바뀌지 않는다. 값은 다른 필드처럼 뷰어에서 `esc()` 로 이스케이프해 렌더한다.
- 성공하면 핀에 `close_reply`·`close_ref` 로 저장되고 닫힌 카드에 보인다. 같은 `ref` 를 가진 닫힌 핀은 UI가 묶어 보일 수 있다.
- 토큰 없는 에이전트의 `curl` 은 신원 헤더가 없으므로 `closed_by` 가 `{"login":"local","name":"로컬/에이전트"}` 로 남는다. 토큰을 붙이면 `{"login":"agent:<토큰 이름>","name":"<토큰 이름>"}` 이다(§인증).

> **주의**
>
> 이미 닫힌 핀을 다시 닫으면 아무것도 바꾸지 않는다. `done_at`, `closed_by`, `rev`, `close_reply`, `close_ref` 가 모두 첫 닫기 값 그대로고, 두 번째 호출의 `reply`·`ref` 는 버려진다. 예전에는 두 번째 닫기가 `done_at`·`closed_by` 를 덮어써 처음 닫은 사람이 사라졌다(실측 결함). 사유를 새로 남기려면 `/reopen` 으로 한 번 연 뒤 다시 `/close` 한다. `reopen` 이 옛 `close_reply`·`close_ref` 를 지우므로 다음 닫기가 새 사유로 채운다.

## 스레드 (답글)

초기 시범 원고의 핀 42건 중 10건(24%)은 고칠 곳이 아니라 질문이었다. 예를 들어 #30은 '구간이 0을 포함한다는 게 뭐지?'였다. 그런데 답을 남길 곳이 닫기 사유 한 칸뿐이라 되물을 수 없었다. 그래서 핀마다 선택 필드 `thread` 를 두고, 사람과 에이전트가 같은 경로(`POST /api/pins/{id}/reply`)로 글을 단다.

```bash
curl -s -X POST <base>/api/pins/12/reply -H 'Content-Type: application/json' -d '{"text": "95% 신뢰구간이다"}'
```

- `text` 는 앞뒤 공백을 걷은 뒤 1..1000자인 문자열이다. CRLF는 LF로 바꾸고, 줄바꿈·탭이 아닌 제어 문자는 뺀다.
- 틀린 입력은 `400`, 없는 id는 `200 {"ok": false}`, 답글이 이미 200건이면 `409 {"error":"full"}` 이다. 상태 전환 기록은 이 상한과 무관하게 붙는다.
- 메시지 모양은 `{id, by:{login,name,pic?}, at, text, mentions?, ev?, ref?}` 다. `id` 는 핀 안에서 1부터 오른다.
- 상태 전환도 스레드에 한 줄씩 남는다. `ev` 가 `close` 면 글은 닫기 사유이고 `ref` 가 붙는다. `reopen` 이면 글은 다시 연 이유다. 그 밖에 `confirm`, `assign`(§@태그·사람·이벤트)이 있다.
- 닫기 사유는 옛 `close_reply`·`close_ref` 에도 그대로 적힌다. 옛 뷰어와 에이전트 호환을 위해서다.
- 질문 핀은 답글을 단 뒤 따로 닫는다.

### 답글이 핀을 다시 여는 규칙 (0.2.2)

뷰어의 닫힌 핀에는 [답글] 하나만 있다. 답글이 핀을 다시 여는지는 서버가 정한다(`reply_reopens`, [ADR-0004](../adr/0004-one-reply-trash-sections.md)). 뷰어는 같은 규칙으로 답글 칸 아래 한 줄에 결과를 미리 보인다.

| 핀 상태 | 쓴 쪽 | 답글이 사람을 @태그하나 | 결과 |
| --- | --- | --- | --- |
| 검토 대기·완료 | 사람 | 아니오 | **다시 연다.** 답글은 `ev:reopen` 기록(다시 연 이유)이 되고, `POST /reopen` 과 똑같이 `review`·`confirmed_*`·`close_reply`·`close_ref` 를 지우고 `reopened_by`·`reopened_at` 을 남긴다. 이벤트도 같다(작성자에게 `reopened`) |
| 검토 대기·완료 | 사람 | 예 | 상태 그대로. 보통 답글이다(태그된 사람에게 `mention`) |
| 열림 | 누구나 | — | 상태 그대로 |
| 질문 핀 | 누구나 | — | 답으로 남는다. 상태 그대로 |

- **사람**은 에이전트가 아닌 신원이다. 토큰, 헤더 없는 루프백 요청, `agent` 역할인 사람은 에이전트라 규칙으로는 다시 열지 않는다.
- **토큰 없이 사람 신원으로 보내는 에이전트**(사람으로 로그인한 머신에서 테일넷 주소로 보내며 닫을 때 `"review": true` 를 넣는 에이전트, `--auth local` 인스턴스에 헤더 없는 `curl`)는 서버에게 사람이다. 그런 에이전트는 답글마다 `"reopen": false` 를 넣는다. `pins.md` 안내 줄(`REPLY_GUIDANCE`, 토큰 안내 줄 다음에 더한 줄)과 SKILL이 같은 말을 한다.
- **사람을 @태그한다**는 풀린 `mentions` 가 글쓴이 자신과 `agent` 역할인 계정을 빼고 하나라도 있다는 뜻이다. `@Codex 고쳐 주세요`처럼 에이전트 역할 계정을 부른 답글은 사람을 부른 것이 아니다.
- 본문의 선택 `reopen` 이 `true`/`false` 면 규칙보다 앞선다. 불리언이 아니면 `400` 이다. 열린 핀은 `reopen: true` 여도 바뀌지 않는다. 뷰어의 [상태 유지]가 `false` 를 보낸다.
- 응답은 `{ok, pin, msg, state, reopened}` 다. `reopened` 가 참이면 `msg` 는 `ev:"reopen"` 기록이다. `state`·`reopened` 는 0.2.2에서 더했다.
- 다시 여는 답글에는 답글 200건 상한이 걸리지 않는다. 상태 전환 기록이기 때문이다.
- 다시 여는 답글도 보통 답글처럼 알린다. 작성자는 `reopened`, 이 글이 태그한 사람은 `mention`, 그 밖에 이 핀에서 불린 적 있는 사람은 `replied` 다. 한 사람이 둘을 받지 않는다.
- 다시 열린 핀은 `pins.md` 열린 표로 돌아온다. 번호 칸에 `다시 열림`, 메모 칸 뒤에 `다시 연 이유(<이름>): <답글>` 이 붙는다(§질문·다시 열림·사람에게 물은 핀). 형식은 예전 그대로다.
- 핀 종류는 `kind_req`(`fix`|`question`, 없으면 `fix`)다. `POST /api/pin` 과 `/edit` 이 받고, `/edit` 은 닫힌 핀에서도 받는다. 범위 종류를 뜻하는 옛 `kind` 와는 다른 필드다.

## 검토 대기

흐름은 `close` → `review` → `confirm` 이다. 초기 시범 원고에서 에이전트가 닫은 핀을 작성자가 다시 연 일이 42건 중 2건(#28·#42) 있었다. 그런데 사람이 결과를 봤다는 기록이 없었다. 그래서 에이전트가 닫은 핀은 바로 완료가 아니라 검토 대기로 보낸다.

| 전환 | 조건 | 결과 |
| --- | --- | --- |
| 닫기 | 에이전트: 토큰, 헤더 없는 루프백 요청(로컬 curl), `agent` 역할인 사람 | `done:true` + `review:true` = **검토 대기**. 헤더 없는 태그 장치는 0.2.1부터 `403` 이다(§인증) |
| 닫기 | 사람(`editor`·`owner` 역할, `local` 방식의 소유자) | `done:true` = 완료(그 사람이 검토자다) |
| 닫기 | 본문 `"review": true`·`false` | 그 값을 따른다. 토큰 없이 테일넷 주소로 닫는 원격 에이전트는 그 기기 사람의 신원을 달고 가므로 `true` 를 보낸다. 같은 에이전트는 답글에 `"reopen": false` 를 넣는다(사람 신원의 답글은 닫힌 핀을 다시 연다, §답글이 핀을 다시 여는 규칙 (0.2.2)) |
| `POST /confirm` | 검토 대기 | `review` 를 지우고 `confirmed_by`·`confirmed_at` 을 남긴다(스레드 `ev:confirm`) |
| `POST /confirm` | 에이전트 역할의 요청(토큰, 헤더 없는 루프백 요청, `agent` 역할인 사람) | `403`, 메시지는 `확인은 사람이 합니다 — …` |
| `POST /confirm` | `viewer` 역할 | `403`(§인증의 역할 검사) |
| `POST /confirm` | 사람 신원으로 완료 / 열림 / 없음 | 멱등 `{ok:true}` / `409 {"error":"open"}` / `200 {"ok":false}` |
| `POST /reopen` | 닫힌 핀(검토 대기·완료) | 열림. `review`·`confirmed_*`·`close_reply`·`close_ref` 를 지우고 스레드에 `ev:reopen` 을 남긴다. 선택 `{"reason"}`(≤1000자)이 그 글이다 |
| `POST /reply` | 닫힌 핀에 사람이, 사람을 @태그하지 않은 답글 | `POST /reopen` 과 같다. 답글이 그 글이다(§답글이 핀을 다시 여는 규칙 (0.2.2)) |

확인은 사람만 누를 수 있다. 뷰어는 작성자에게 확인을 권할 뿐이고, `editor`·`owner` 역할인 사람이면 누구나 누를 수 있다. 토큰은 늘 `agent` 역할이라 토큰으로는 확인할 수 없다.

- **하위 호환**: 검토 대기도 `done:true` 라서 옛 계약이 그대로 선다. `GET /api/pins`(열린 핀만)에 나오지 않고, `claim` 은 `409 done` 이며, 줄 맞춤·겹침 계산은 건너뛴다. 옛 서버와 옛 탭은 완료로 본다. `review` 가 없는 옛 `done:true` 는 완료다. 읽을 때 이관 쓰기를 하지 않는다.
- 응답과 `GET /api/pins` 항목에는 계산 필드 `state`(`open`|`review`|`done`)가 붙는다. 저장하지 않는다. `/api/meta` 는 `n_open`·`n_review`·`n_done` 을 싣는다. `n_done` 은 완료만 센다.
- 두 번째 닫기는 예전처럼 아무것도 바꾸지 않는다. 검토 대기 핀을 에이전트가 다시 닫아도 그대로다.

## @태그·사람·이벤트

@태그는 뷰어 안에서만 사람을 부른다. GitHub, Telegram, 메일 같은 바깥 알림은 보내지 않는다. 대신 나중에 붙일 수 있게 `events.jsonl` 에 적어 둔다.

### 사람 목록

`<state_dir>/people.json` 은 `{"version":1,"people":[{login,name,pic?,first_seen,last_seen,role?}]}` 모양이다. @태그 후보이자 0.2.0부터는 멤버 명단이다.

- 이 뷰어를 연(`GET /`, 전체 `/api/meta`) 사람과, 쓰기 요청을 보낸 사람을 적는다. `limn member add` 로 더한 사람도 있다. 에이전트(토큰 포함)는 적지 않는다.
- 선택 필드 `role` 은 `owner`·`editor`·`viewer`·`agent` 중 하나이고, 없으면 `editor` 다. `limn member` 로 정하며, 서버가 항목을 다시 써도 그대로 둔다(§인증). 처음 온 사람은 `role` 없이 적힌다. `local` 방식의 소유자만 `owner` 로 적힌다.
- 같은 값이면 10분에 한 번만 다시 쓴다. `/api/meta?light=1` 폴링은 쓰지 않는다.
- `GET /api/people` 은 이 파일과 핀의 작성자·행위자·스레드 글쓴이를 합쳐 준다.

### @이름 풀기

서버가 글 속 `@이름` 을 로그인으로 푼다. 맞추는 대상은 다음 넷이다.

1. 이름 전체
2. 로그인
3. 로그인의 `@` 앞부분
4. 다른 사람과 겹치지 않는 이름 첫 단어

대소문자는 가리지 않는다. 한글 조사가 붙어도 된다(`@Bob님`). 반면 다음은 태그가 아니다.

- `@` 앞이 글자인 경우. 메일 주소다.
- 영문 이름 뒤에 영문이 바로 이어지는 경우(`@Alicex`). 다른 말이다.

뷰어가 고른 로그인은 본문 `mentions`(≤10개)로 온다. 이것은 첫 단어가 여러 사람과 겹칠 때 가르는 힌트일 뿐이다. 글은 `@이름` 그대로 두고, 풀린 로그인은 핀(메모)의 `mentions` 와 메시지의 `mentions` 에 둔다. 글쓴이가 자기 자신을 태그하면 항상 뺀다. 자기 자신을 '부른 핀'으로 만들지 않기 위해서다.

### 사람에게 물은 핀 (옛 핀의 추론)

담당(`assignee`)이 없는 옛 핀은 태그로 누구에게 물었는지 추론한다. 계산 필드 `addressed` 는 메모의 `mentions` 와 지금 차례 스레드 글의 `mentions` 를 합친 것이다. "지금 차례"는 마지막 닫기 뒤, 다시 열렸으면 그 다시 엶부터다([viewer.md](viewer.md) §스레드와 검토).

- `addressed` 는 **질문(`kind_req=question`) 핀에서만** 채워진다. pins.md 번호 칸의 `→ @이름` 이 이것이고, 에이전트는 건너뛴다.
- 수정 요청(`fix`) 핀의 같은 재료는 `fyi` 필드에 담긴다. pins.md 에는 `참고 @이름` 으로만 보이고, 건너뛰지 않는다. 예전에는 FYI로 사람을 태그한 수정 요청 핀이 `→ @이름` 으로 잡혀 영영 건너뛰어졌다(실측).
- 번호 칸 표시 우선순위는 `다시 열림` > `→ @이름` > `질문` 이다.

### 담당 (`assignee`)

`assignee` 는 누가 이 핀을 처리하는지 적은 값이다. `"agent"` 또는 사람 로그인이다. 본문 글에서 짐작하던 건너뛰기 규칙이 모호했기 때문에 생겼다. 초기 시범 원고 #43의 수정 요청 핀 `이거 콜링 제대로 작동하나 @Bob Park 확인 부탁합니다` 는 Bob에게 맡긴 것이었다. 그런데 `참고 @Bob Park` 로 떠서 에이전트가 자기 일로 읽었다.

- `POST /api/pin` 과 `/edit` 이 받는다. `"agent"` 이거나 이 뷰어가 아는 사람(`GET /api/people`)의 로그인이 아니면 `400`(한국어 메시지)이다.
- `/edit` 은 닫힌 핀에서도 받는다. 담당이 바뀌면 스레드에 `ev:"assign"` 을 남긴다. 글은 `담당: @이름` 또는 `담당: 에이전트` 다. 만들 때의 담당은 스레드에 기록하지 않는다.
- 뷰어는 새 핀에 늘 담당을 적는다. @태그가 없으면 `agent` 다.

| 담당 | `addressed` | pins.md | 에이전트 | 알림 |
| --- | --- | --- | --- | --- |
| 사람 | `[그 사람]` | `→ @이름` | 건너뛴다 | 그 사람의 [나를 부른 핀]·`나를 부름`에 뜬다. 담당이 된 사람에게 `assigned` 이벤트 |
| `agent` | `[]` | 메모·지금 차례의 @태그가 모두 `fyi` → `참고 @이름` | 처리한다 | @태그된 사람에게 `mention` |
| 없음(옛 핀) | 위 추론(질문 핀의 @태그) | 질문 핀 `→ @이름`, 수정 요청 핀 `참고 @이름` | 추론대로 | @태그된 사람에게 `mention` |

옛 핀은 읽을 때 이관 쓰기를 하지 않는다. 어느 경우든 @태그된 사람에게는 `mention` 알림이 간다.

### 이벤트 (`events.jsonl`)

`<state_dir>/events.jsonl` 은 한 줄에 한 건인 추가 전용 기록이다. 레코드 모양은 `{seq, type, pin, doc, to:[login], by:{login,name}, at, ts, kind_req?, msg?, excerpt?}` 다.

| `type` | 언제 | `to` |
| --- | --- | --- |
| `mention` | 답글이나 다시 연 이유가 누군가를 @태그함. 전에 불린 사람이어도 **매번** 간다(0.2.1). 메모 저장·수정은 @태그 횟수가 전보다 늘어난 사람에게 간다(새 핀은 태그된 모두). 그래서 `@이름` 옆의 오타만 고치면 아무도 받지 않고, `note_append` 로 `@이름` 을 다시 쓰면 받는다 | 태그된 사람(글쓴이 자신은 빠진다) |
| `review_requested` | 핀이 검토 대기로 감 | 작성자 |
| `replied` | 답글 | 작성자 + 이 핀에서 불린 적 있는 사람. 단 이 답글이 @태그한 사람은 빠진다. 그 사람은 `mention` 하나만 받는다. 한 글로 한 사람이 두 알림을 받지 않는다 |
| `reopened` | 닫힌 핀을 다시 엶 | 작성자. 다시 연 이유가 작성자를 @태그하면 `mention` 하나만 받는다 |
| `assigned` | 핀을 만들거나 고치며 담당을 사람으로 정함(바뀔 때만) | 새 담당 |
| `cleared` | 소유자가 `/api/clear` 로 모든 핀을 지움(0.2.1) | 아무도 아님(`to` 는 `[]`). 알림이 아니라 감사 기록이다. `pin`·`doc` 대신 `n`(보관한 핀 수)과 `archive`(보관본 이름)를 싣는다 |
| `dropped` | 핀을 휴지통으로 보냄(0.2.2) | 작성자(작성자 자신이 지웠으면 기록하지 않는다). `excerpt` 는 메모다. 뷰어는 [되살리기]를 단 알림으로 보인다 |
| `purged` | 소유자가 휴지통에서 영구 삭제함(0.2.2) | 아무도 아님(`to` 는 `[]`). `cleared` 처럼 감사 기록이다. `pin` 과 `by` 만 싣는다 |

- `to` 에서 행위자 자신과 `local` 은 빠진다. `to` 가 비면 기록하지 않는다. `cleared`·`purged` 만 예외로 `to` 가 비어도 남긴다.
- 핀 쓰기가 커밋된 뒤, 잠금 아래에서 파일 전체를 원자적으로 바꿔 쓴다. 앞부분은 그대로 두므로 추가 전용이 유지된다.
- 최근 5000건만 남긴다. 그래도 `seq` 는 계속 오른다. 소비자는 바이트 위치가 아니라 `seq` 로 따라온다.

## 브라우저 알림 커서

`/api/meta` 는 라이트 여부와 관계없이 늘 `ev_seq`(`events.jsonl` 의 마지막 `seq`)를 싣는다. `ev=<마지막으로 본 seq>` 를 붙이면 그 뒤의 이벤트 가운데 다음 조건을 모두 만족하는 것을 `events` 로 싣는다.

- `type` 이 `mention`, `review_requested`, `replied`, `reopened`, `assigned`, `dropped` 중 하나다.
- `to` 에 **지금 요청자**(사람의 로그인)가 들어 있다.
- 행위자가 요청자 자신이 아니다.

최대 20건(가장 최근 것부터 20건)을 싣고, 항목마다 `doc_name` 을 더한다. 에이전트 요청(토큰 포함)은 늘 빈 목록이다. `ev` 가 정수가 아니면 `400` 이다. 이 조회는 읽기만 하므로 라이트 폴링의 쓰기 없음 계약이 그대로 선다. 뷰어 쪽 규칙은 [viewer.md](viewer.md) §브라우저 알림에 있다.

## 원격 에이전트 진입점 (`GET /pins.md`)

공저자의 에이전트는 서버 머신에 로그인하지 않고 테일넷 주소나 공개 이름(`--public-host`)으로만 닿는다. 그래서 디스크의 `<state_dir>/pins.md` 를 파일로 열 수 없다. `GET /pins.md` 는 같은 내용을 HTTP로 내고, 안내 줄을 요청이 도착한 `Host` 에 맞춘다.

```bash
curl -s -H "Authorization: Bearer $LIMN_TOKEN" https://<기기>.<tailnet>.ts.net:<port>/pins.md
```

원격 에이전트도 토큰을 붙인다(§인증). 토큰을 붙이면 어디서 붙든 에이전트로 기록되고, 닫기가 검토 대기로 간다. 토큰 없이 테일넷 주소로 오면 `tailscale serve` 가 그 기기의 테일넷 사용자 신원을 붙인다. 사람 계정으로 로그인한 기기라면 그 사람의 신원이 붙고, 이때는 닫을 때 본문에 `"review": true` 를 넣어야 한다(§검토 대기). **태그 장치**(서버, CI 러너)에는 신원이 없어서, 토큰 없는 요청은 0.2.1부터 `403` 이다(§인증). 그러니 원격 에이전트는 토큰을 쓰는 것이 기본이다. 루프백(`http://127.0.0.1:<port>`) 에이전트는 바뀌지 않았다.

- `GET /api/pins` 와 같은 sync 경로(`snapshot_pins()`)를 탄 뒤 렌더한다. 그래서 줄 번호가 최신이다.
- 바뀌는 것은 close 예시의 base URL뿐이다. `Host` 가 `*.ts.net` 이면 포트까지 `Host` 그대로 쓴 `https://<Host>` 다. `--public-host` 로 준 이름이면 `https://<이름>` 이고, 설정한 포트가 443이 아니면 `:<포트>` 가 붙는다. 루프백이면 지금까지처럼 `http://127.0.0.1:<port>` 다.
- 원격일 때는 안내 문단에 `원격: curl -s <base>/pins.md` 한 줄이 더 붙는다. 루프백에는 없다. 루프백 쪽은 이미 그 파일을 직접 읽고 있기 때문이다.
- 디스크의 `<state_dir>/pins.md` 는 이 요청과 무관하게 항상 루프백 base로 쓴다. 다른 세션이 그 파일을 직접 읽어도 안내가 바뀌지 않는다.
- Host·Origin 검사는 다른 `GET` 과 같다([operations.md](operations.md) §Host·Origin 검사). 낯선 Host는 `403` 이다.

## 처리 중 표시 (claim)

작성자 쪽과 공저자 쪽의 두 에이전트가 같은 핀을 동시에 고칠 수 있다. `POST /api/pins/{id}/claim` 은 이 충돌을 줄이는 표시다. 이것은 **잠금이 아니라 TTL이 있는 낙관적 표시**다. 다른 사람이 그 핀을 닫거나 강제로 다시 잡는 것을 막지 않는다. 협업은 "claim 먼저, `처리 중(…)` 은 건너뛰기" 관례에 기댄다([SKILL.ko.md](../../skill/SKILL.ko.md) §핀 처리).

> **주의**
>
> claim은 고치기 직전에 그 핀만 건다. 한꺼번에 잡으면 손대지 않은 핀까지 잠긴다. 실측(2026-09-23)에서 23건을 `ttl_min` 480으로 한꺼번에 잡았고, 뷰어의 `~04:02` 가 예상 완료 시각처럼 읽혔다.

```bash
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/claim -H 'Content-Type: application/json' -d '{"eta_min": 15}'
curl -s -X POST http://127.0.0.1:<port>/api/pins/3/unclaim
```

### 본문 두 칸

| 칸 | 범위 | 뜻 |
| --- | --- | --- |
| `eta_min` | 1..240 | **처리 예상 시간(견적)**. 레코드에 `eta_ts = 지금 + eta_min×60`(epoch 초)으로 저장한다. 견적 기준은 [SKILL.ko.md](../../skill/SKILL.ko.md) §핀 처리 4단계 |
| `ttl_min` | 1..120 | **잠금 자동 해제**까지의 시간(안전장치). 생략하면 `eta_min` 이 있을 때 `min(120, max(30, eta_min×2))`, 없으면 120. 상한은 480에서 120으로 낮췄다. 멈춘 에이전트가 한나절 동안 핀을 쥐지 않게 하려는 것이다 |

두 칸 모두 선택이다. 정수가 아니거나 1보다 작으면 `400` 이고 아무것도 바뀌지 않는다. **상한을 넘는 값은 거부하지 않고 상한으로 깎는다.** 예를 들어 `ttl_min` 480은 120, `eta_min` 300은 240이 된다. 옛 절차대로 `ttl_min` 480으로 잡은 에이전트가 같은 값으로 연장하다 `400` 을 받아 작업이 깨지지 않게 하려는 하위 호환이다. 응답의 `ttl_min_applied`(늘)와 `eta_min_applied`(`eta_min` 을 보냈을 때)가 실제로 적용한 값이다.

### 신원·연장·충돌

- 신원은 §인증과 같은 방식으로 정한다. 토큰이면 `agent:<토큰 이름>`, 헤더로 온 사람이면 그 사람, 헤더 없는 루프백 요청이면 `로컬/에이전트` 다. 토큰 이름이 다르면 다른 신원이라서, 두 에이전트에게 토큰을 따로 주면 서로의 claim이 `409` 로 갈린다.
- **같은 신원이 다시 걸면 연장**이다. `claim_until` 을 지금부터 다시 잰다. `eta_min` 을 주면 `eta_ts` 도 지금부터 새 견적으로 바꾸고, 안 주면 앞 견적을 둔다. 시작 시각(`claimed_at`·`claim_ts`)은 그대로이고 `rev` 가 1 오른다.
- **다른 신원이 유효한(만료 안 된) claim을 쥐고 있으면 `409`** 다. 본문은 `{"error":"claimed","claimed_by":{...},"claim_until":...,"eta_ts":...}` 다.
- 새로 잡으면 옛 `eta_ts` 는 지운다. 만료된 남의 claim을 새로 잡는 경우도 같다.
- 닫힌 핀에 claim을 걸면 `409 {"error":"done","pin":...}`. 없는 id는 기존 관례대로 `200 {"ok": false}` 다.
- `unclaim` 은 claim을 건 신원과 무관하게 지운다. claim은 들어온 사람끼리의 협업 표시이지 잠금이 아니다([domain.md](domain.md) §작성자 귀속). 그래서 처리 중 표시는 소유자 확인 없이 풀 수 있다. 막는 것은 역할 검사뿐이다. `viewer` 역할의 `unclaim` 은 `403` 이다.
- `close` 와 `drop` 은 claim 필드를 함께 지운다. 닫히거나 삭제된 핀에 처리 중 표시가 남지 않는다. 다른 사람이 claim한 핀을 닫는 것 자체는 막지 않는다. 그래서 에이전트는 처리를 포기하거나 사용자에게 넘길 때만 `unclaim` 을 부른다.

### 시각 필드

`claim_until`·`claim_ts`·`eta_ts` 는 epoch 초다. 브라우저 시간대와 무관하게 비교하기 위해서다([build-sync.md](build-sync.md) §위치 추정 (`est`)과 같은 이유).

이름이 `*_at` 이 아닌 것은 일부러다. 레코드 검증(`valid_rec`)은 `*_at` 을 문자열 시각으로 본다. 숫자인 `*_at` 필드를 쓰면, 이 필드를 모르는 옛 서버가 그 레코드를 깨진 줄로 버린다.

- 만료된 claim은 모든 표시에서 없는 것으로 본다. `<state_dir>/pins.md`, 뷰어 카드, 충돌 판정이 모두 그렇다. 저장값 자체는 다음 쓰기 때 정리될 뿐이다.
- `claim_ts` 가 없는 옛 claim은 `GET /api/pins` 가 `claimed_at`(서버 현지 시각 문자열)을 epoch로 풀어 계산 필드 `claim_ts` 로 싣는다. 저장하지 않는다.

### 표시

`<state_dir>/pins.md` 번호 칸에는 유효한 claim이 있으면 `처리 중(<이름>, 약 15분)` 이 붙는다(§pins.md 형식). 분은 남은 견적을 5분 단위로 올린 값이다. 견적을 넘겼으면 `예상 초과` 가 붙고, 견적 없이 잡았으면 `처리 중(<이름>)` 이다.

뷰어 카드는 머리에 호박색 점을 두고 아래 배지를 보인다. 분과 시각은 모두 5분 단위로 올린다. 견적은 대략이기 때문이다. 시각은 보는 기기의 현지 시각이고, 30초마다 다시 센다.

| 상태 | 배지 |
| --- | --- |
| 견적 안 | `처리 중 · 약 15분 · 20:40쯤` |
| 견적 초과 | `예상보다 늦어짐 (+5분)`(초과한 분) |
| 견적 없는 claim | `처리 중 · 20:02부터 (23분째)` |

잠금 자동 해제 시각(`claim_until`)은 배지에 쓰지 않고 설명(툴팁)에만 둔다. 배지에 두었을 때 예상 완료 시각으로 읽혔기 때문이다. 배지와 함께 [풀기] 버튼(unclaim)이 뜬다. **뷰어에는 claim을 거는 버튼이 없다.** claim은 에이전트 전용 동작이다.

## 겹친 핀과 덧붙이기

같은 파일의 열린 핀 두 개가 겹칠 수 있다. 한쪽이 다른 쪽 범위 안에 통째로 들거나, 일부만 걸치는 경우다. 이때 `GET /api/pins` 와 `POST /api/pick` 응답에 계산 필드 `rel`·`overlaps` 가 붙는다. 이 값은 **저장하지 않고** 요청마다 다시 계산한다. 서버는 겹친 핀을 자동으로 합치지 않는다.

- `rel: [{"id", "rel": "inside"|"contains"|"partial"}]` 은 저장된 핀끼리의 관계다. 그 핀을 기준으로 다른 핀과의 관계를 적는다. 범위가 완전히 같으면 id가 작은 쪽을 `contains`(바깥)로 본다.
- `overlaps` 는 pick과 `/api/overlaps` 응답에 붙는다. 모양은 `[{"id","lo","hi","rel": "equal"|"inside"|"contains"|"partial"}]` 이고, 저장 전 선택을 기준으로 한 관계(`selection_rel`)다.

| `rel` | 뜻 |
| --- | --- |
| `equal` | 범위가 같다. 같은 문단·환경을 다시 찍는 가장 흔한 중복이다 |
| `inside` | 선택이 기존 핀 안에 든다 |
| `contains` | 선택이 기존 핀을 감싼다 |
| `partial` | 일부만 걸친다 |

### 뷰어의 배너

- **범위가 바뀔 때마다 다시 센다.** 뷰어는 드래그, 단계 전환, 한 줄 버튼마다 이 탭의 열린 핀 목록으로 같은 규칙(`overlapsFor`·`selRel`)을 돌린다. 회귀 테스트가 이 규칙을 서버 구현과 대조한다. pick 순간에만 세던 때는 [문단] 단계로 바꿔 기존 핀과 똑같은 범위를 만들어도 배너가 안 떠서 중복 핀이 저장됐다(실측).
- 서버가 본 겹친 핀이 이 탭 목록에 없으면 목록을 다시 받는다. 다른 사람이 방금 저장한 경우다.
- 네 관계 모두 배너 대상이다. 대표 하나를 이 순서로 고른다: 같은 범위 > 안(가장 좁은 바깥 핀) > 감쌈(가장 넓은 안쪽 핀) > 걸침(id가 가장 작은 것).
- 문구가 관계를 밝힌다: `열린 핀 #4와 같은 범위입니다 (L405-L406)` / `… #4 범위 안입니다` / `… #4를 감쌉니다` / `… #4와 일부 겹칩니다`. 조사는 숫자 읽기로 가린다. 버튼은 `[#4 메모에 덧붙이기] [별도 핀으로 저장]` 이다.
- "덧붙이기"는 `note_append` 로 기존 핀에 붙이고(§핀 수정 (`/api/pins/{id}/edit`)), 지금 선택은 새 핀으로 만들지 않는다.
- [별도 핀으로 저장]은 **그 핀과의 그 관계**만 끈다. 범위를 바꿔 관계가 달라지면 다시 알리고, 다음 드래그에서는 초기화한다.

`<state_dir>/pins.md` 번호 칸의 `#N과 같은 범위`, `#N 범위 안`, `#N과 일부 겹침` 이 이 계산의 대표값이다(§pins.md 형식). 뷰어 카드 배지도 같은 말과 같은 규칙을 쓴다.

## 보기 전용 PDF 문서의 pick·핀

`kind:"pdf"` 문서는 LaTeX 원고가 없는 PDF라 SyncTeX이 없다. 그래서 줄 범위 대신 쪽과 영역으로 핀을 찍는다.

**pick.** `doc` 이 보기 전용인 `POST /api/pick` 은 좌표를 받아 `{doc, kind:"region", view_only:true, page, frac, pdf, name, quote, n_chars, warn, overlaps:[], pdf_build}` 를 돌려준다. `quote` 는 영역 글자다(pdftotext, 공백 정규화, 160자). `frac` 을 안 보냈으면 좌표로 만든다. 줄 범위(`lo`·`hi`·`levels`)는 없다.

**핀 만들기.** `POST /api/pin` 은 `{doc, page, frac, note?, quote?, pdf_build?}` 를 받는다.

- `frac` 은 필수이고 LaTeX 핀보다 엄하다. 숫자 4개, 쪽 안 0..1, 넓이 > 0 이어야 한다.
- `page` 는 1..쪽 수다.
- `file`·`lo`·`hi`·`scope` 를 보내면 `400` 이다.
- 저장 레코드는 `{id, doc, pdf:<절대경로>, name, kind:"region", page, frac, quote?, note, at, author, rev, pdf_build}` 다. `file`·`lo`·`hi`·`anchor` 가 없다.

**그 밖의 경로.**

- `/edit` 은 메모(`note`·`note_append`)와 영역 다시 잡기(`loc:{page, frac, quote?}`)만 받는다. `lo`·`hi`·`scope`·`kind` 는 `400` 이다.
- 닫기, claim, drop은 LaTeX 핀과 같다.
- `POST /api/rebuild` 는 `400` 이다. 재빌드가 없고, 파일이 바뀌면 쪽을 저절로 다시 그린다([build-sync.md](build-sync.md) §보기 전용 PDF 문서).
- `/api/snippet` 도 `400` 이다.

## 휴지통

삭제(`/drop`)한 핀은 휴지통에 30일(`TRASH_DAYS`) 동안 머문다(0.2.2, [ADR-0004](../adr/0004-one-reply-trash-sections.md)). 저장은 예전과 같은 `pins.dropped.jsonl` 이고 레코드 모양도 같다.

| 동작 | 규칙 |
| --- | --- |
| 보기 | `GET /api/pins/dropped`. `dropped_at` 에서 30일이 지난 항목은 싣지 않는다. 항목마다 계산 필드 `expires_ts`(지워질 시각, epoch 초)가 붙는다. 뷰어의 '며칠 뒤 지워짐'이 이것을 써서 보는 기기의 시간대와 상관없다. 읽기는 파일을 고치지 않는다 |
| 되살리기 | `POST /api/pins/{id}/restore`. 누구나(`viewer` 제외). 30일이 지난 항목은 `404` 다 |
| 저절로 지우기 | 30일이 지난 항목은 서버 기동 때, 삭제·되살리기 때, 그리고 오래 떠 있는 서버를 위해 `GET /api/pins`·`GET /pins.md`(이미 줄 맞춤 쓰기를 하는 읽기)에서 한 시간에 한 번(`TRASH_CHECK_EVERY_S`) 파일에서 뺀다. 라이트 폴링(`/api/meta?light=1`)은 여전히 쓰지 않는다. 서버 로그에 `trash: purged N pin(s)` 가 남는다. `dropped_at` 은 `now_str` 모양(서버 현지 시각)과 ISO+오프셋을 읽고, 읽을 수 없는 항목은 나이를 모르므로 남긴다. 쓰기가 실패하면(읽기 전용 상태 디렉터리) 경고만 남기고 기동은 계속된다. 읽을 수 없는 줄은 휴지통 파일을 다시 쓸 때 `pins.dropped.jsonl.corrupt-<시각>.bak` 으로 원래 바이트를 남긴다 |
| 영구 삭제 | `POST /api/pins/{id}/purge`. **`owner` 역할만** 한다. 휴지통에 없으면 `404` 다. `purged` 감사 이벤트와 서버 로그를 남긴다 |
| 알림 | 작성자가 아닌 쪽이 지우면 작성자에게 `dropped` 이벤트가 간다(§이벤트 (`events.jsonl`)) |

- 핀 번호는 `pins.seq` 에 남으므로 영구 삭제한 번호도 다시 쓰이지 않는다.
- `pins.md` 는 예전처럼 삭제한 핀을 싣지 않는다.
- 0.2.1로 되돌려도 휴지통 파일을 그대로 읽는다. 옛 서버는 30일 규칙을 모를 뿐이다.

## 핀 레코드 스키마

핀은 `pins.jsonl` 에 한 줄 한 레코드로 저장된다.

```json
{"id": 3, "at": "2026-09-21 20:10:00", "page": 4, "file": "<절대경로>/introduction.tex",
 "lo": 120, "hi": 134, "raw_lo": 122, "raw_hi": 131, "kind": "env:minipage", "scope": "env",
 "via": "synctex", "score": 0.93, "note": "이 문단 톤을 낮춰줘", "frac": [0.12, 0.30, 0.55, 0.18],
 "pdf_build": "pages-20260921200500",
 "anchor": {"head": "이 절에서는 소스 재선정 주기를...", "tail": "...효과가 관측된다."},
 "synced_at": 1758450000.0, "sync": "moved +3", "rev": 2, "done": false,
 "author": {"login": "bob@example.com", "name": "Bob Park", "pic": "https://..."},
 "edited_at": "2026-09-21 21:00:00", "edited_by": {"login": "local", "name": "로컬/에이전트"}}
```

새 필드는 모두 선택이다. 새 필드가 없는 옛 레코드도 그대로 읽힌다.

| 필드 | 뜻 |
| --- | --- |
| `doc` | 핀이 속한 문서 키(§문서 매개변수 (`doc=`)). 없는 옛 레코드는 첫 문서로 **읽는다**. 이관 쓰기를 하지 않는다. `GET /api/pins` 응답에는 늘 채워진다(계산) |
| `pdf` | 보기 전용 PDF 문서의 핀에만 있다. 그 PDF의 절대경로다. 이 필드가 있고 `file` 이 없으면 보기 전용 핀으로 검증한다(`page`·`frac` 필수, `lo`·`hi` 없음). 문서 키가 지금 설정에 없어도 깨진 줄로 치지 않는다 |
| `rev` | 레코드 내용이 바뀌는 모든 쓰기(줄 이동·stale, 수정, 닫기, 다시 열기, 되살리기)에서 +1. 없으면 0 |
| `scope` | `raw\|para\|env\|env2\|env3\|lines`. 저장할 때 고른 범위 사다리 단계다 |
| `quote` | 선택. 호출자가 붙인 짧은 인용이다(60자에서 자른다) |
| `pdf_build` | `frac` 을 찍은 빌드 id(쪽 디렉토리 이름). 없으면 옛 핀이다. 옛 필드명 `frac_build` 도 같은 뜻으로 읽는다([build-sync.md](build-sync.md) §위치 추정 (`est`)) |
| `anchor` | `{head, tail, head_off, tail_off}`. 줄 맞춤의 기준이다. `*_off` 가 없는 옛 앵커는 0으로 본다([domain.md](domain.md) §줄 번호 재동기화) |
| `kind` | `paragraph\|float\|block\|none`(옛 값) 또는 `env:<이름>`, `lines`. 모르는 값은 원문 그대로 둔다 |
| `author` | 만든 사람 `{login, name, pic?}` |
| `edited_at`, `edited_by` | 저장 뒤 마지막 수정 시각과 사람 |
| `closed_by` / `reopened_by` | 닫은 사람과 다시 연 사람(`done_at`·`reopened_at` 과 함께) |
| `close_reply` / `close_ref` | 닫을 때 남긴 선택 사유. 무엇을 고쳤는지(≤500자)와 참조(PR 번호 등, ≤80자)다. 첫 닫기에만 적히고, 이미 닫힌 핀을 다시 닫아도 바뀌지 않는다(§닫을 때 사유 남기기). `reopen` 이 지운다 |
| `changes` / `changes_at` | 0.3. 닫을 때 남긴 선택 `[{file, lo, hi}]` — 이 핀 때문에 바꾼 줄(커밋 뒤 번호, `file` 은 절대 경로)이다(§닫을 때 사유 남기기). `changes_at` 은 그 닫기의 `done_at` 이다(§핀 단위 변경 보기). 첫 닫기에만 적히고 `reopen` 이 둘 다 지운다. 모양이 틀리면(목록이 아니거나 `file` 이 문자열이 아니거나 `lo`·`hi` 가 정수가 아니면) 그 줄은 깨진 줄이다 |
| `dropped_by` / `restored_by` | 삭제 기록(`pins.dropped.jsonl`)의 삭제자, 되살린 레코드의 복원자 |
| `kind_req` | `fix`\|`question`. 핀 종류다(§스레드 (답글)). 없으면 fix |
| `thread` | 답글과 상태 전환 기록 `[{id, by, at, text, mentions?, ev?, ref?}]`(§스레드 (답글)) |
| `mentions` | 메모가 부른 사람의 로그인 목록(§@태그·사람·이벤트) |
| `assignee` | 담당. `agent` 또는 사람 로그인이다(§@태그·사람·이벤트). 없으면 옛 핀이고 추론 규칙을 따른다 |
| `review` | `true` = 검토 대기. `done:true` 와 함께일 때만 뜻이 있다(§검토 대기) |
| `confirmed_by` / `confirmed_at` | 검토 대기를 확인한 사람과 시각 |
| `claimed_by` / `claimed_at` / `claim_ts` / `claim_until` / `eta_ts` | 처리 중 표시(§처리 중 표시 (claim)). `claimed_by` 는 작성자 귀속과 같은 `{login,name}` 형식이고, `claimed_at` 은 시작 시각 문자열이다. `claim_ts`(시작), `claim_until`(잠금 자동 해제), `eta_ts`(예상 완료)는 epoch 초다. `claim_until` 이 지난 값이면 없는 것으로 본다. `close`·`drop`·`unclaim` 이 모두 지운다 |

`snippet`, `warn`, `levels`, `default_level`, `rel`, `overlaps`, `est`, `state`, `addressed` 는 응답에만 있고 저장하지 않는다(§겹친 핀과 덧붙이기, [build-sync.md](build-sync.md) §위치 추정 (`est`)).

## pins.md 형식

`<state_dir>/pins.md` 는 에이전트가 읽는 열린 핀 표다. 5열 표 `| # | 쪽 | 위치 | 범위 | 메모 |` 로 되어 있다.

- 옛 `종류` 열이 `범위` 로 바뀌었다.
- `작성` 열은 v2에서 없앴다. 작성자는 `GET /api/pins` 와 뷰어 카드에서만 본다. 닫힌 핀도 마찬가지다.
- 스니펫은 일부러 넣지 않는다. 줄 범위만 있으면 에이전트가 원본을 `Read` 로 직접 읽는 편이 항상 더 싸고 정확하다. 스니펫은 그 시점의 스냅샷이라 원본과 어긋날 수 있다.

> **주의**
>
> 아래의 한국어 문자열(열 머리, 번호 칸 표시, 상태 이름, 머리줄)은 계약의 일부다. 뷰어 UI는 다른 언어로 현지화될 수 있어도, pins.md와 API의 필드·상태 이름은 번역하지 않고 바꾸지 않는다.

### 머리줄

1. `원고: <경로>` 바로 다음 줄은 `논문: <이름표> · 저장소: <git origin URL 또는 (없음)>` 이다([operations.md](operations.md) §여러 논문 인스턴스를 동시에 띄울 때). 여러 인스턴스를 동시에 열었을 때 다른 논문의 핀을 처리하지 않게 하려는 줄이다.
2. `저장소` 값이 있으면 안내 문단에 `처리 전 자기 체크아웃의 git remote get-url origin 이 위 저장소와 같은지 확인. 다르면 다른 논문의 핀이니 멈춘다` 가 덧붙는다.
3. 그다음 `head.txt`·`built_at.txt` 가 둘 다 있으면 두 줄이 온다. `기준: <head 짧은 해시> · 빌드 <built_at>` 과 `다른 체크아웃에서 처리하면 먼저 git rev-parse --short HEAD 가 같은지 확인` 이다. git 저장소가 아니거나 아직 빌드하지 않아 파일이 없으면 이 두 줄만 생략한다.
4. 안내 문단의 첫 문장(닫기 안내)은 0.3에서 바뀌었다(§닫기 안내 줄). 머리줄에서 바뀐 곳은 이것 하나다.
5. 안내 문단 바로 뒤에 두 줄이 늘 붙는다. 0.2.1부터 `처리를 시작하는 핀은 먼저 잡는다 — … <base>/api/pins/N/claim … · 포기하면 <base>/api/pins/N/unclaim` 이 오고, 0.2.0부터 `에이전트 인증: 모든 요청에 Authorization: Bearer <토큰> 헤더를 붙인다(…) · 헤더 없는 로컬 요청을 에이전트로 받는 방식은 폐지 예정이다 · 테일넷 주소(원격)로 오는 신원 헤더 없는 요청(태그 장치 등)은 403 이다 — …` 이 온다(마지막 구절은 0.2.1). 전문은 §인증의 pins.md 안내 줄에 있다. 둘 다 더한 줄이고 머리줄의 다른 부분은 바뀌지 않았다.

### 닫기 안내 줄

안내 문단은 닫기 안내로 시작한다. 0.3에서 이 문장만 바뀌었다. 줄의 시작 `처리한 핀은 닫는다` 와 `· 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다` 부터의 뒤쪽은 0.2.2와 같다. 닫을 때 `changes` 와 `ref` = `PR #번호 (커밋 해시)` 를 보내라고 하고, 핀별 커밋은 권하되 요구하지 않는다([ADR-0005](../adr/0005-pin-scoped-changes.md)). `<base>` 는 base URL이다.

```text
처리한 핀은 닫는다 — 닫을 때 `changes` 에 이 핀 때문에 바꾼 줄 범위를, `ref` 에 `PR #번호 (커밋 해시)` 를 적는다: `curl -X POST -H 'Content-Type: application/json' -d '{"reply":"무엇을 고쳤는지(≤500자)","ref":"PR #12 (커밋 해시)","changes":[{"file":"main.tex","lo":12,"hi":14}]}' <base>/api/pins/N/close`(본문 생략 가능, 그러면 옛 방식처럼 사유 없이 닫힘. `changes` 의 줄 번호는 `ref` 의 커밋이 만든 판 기준 — 스쿼시 머지 뒤 닫으면 머지된 main 기준, 경로는 위치 칸 기준. 핀마다 커밋을 나누면 더 좋지만 필수는 아니다) · 줄 번호는 갱신 시각 기준이니 원문을 다시 읽고 고친다 · …
```

### 열

- **위치**: `--manuscript`(`C.src`) 기준 **상대경로**다. 루트 파일은 basename과 같아서 단일 파일 원고의 행은 예전과 같다. `\input`·`\include` 로 쪼갠 하위 파일은 `sections/intro.tex L12-L18` 처럼 구분된다. 파일명의 `|` 는 `\|` 로 이스케이프한다(아래 §이스케이프).
- **범위**: `scope` 가 있으면 `env*`→`env:<이름>`, `para`→`paragraph`, `raw`·`lines`→`lines` 로 쓴다. 없으면 옛 `kind` 값을 그대로 쓴다.
- **줄 번호 시점**: `<state_dir>/pins.md` 를 갱신한 시각 기준이다. 앞선 핀을 고쳐 줄이 밀렸을 수 있으면 `GET /api/pins` 로 다시 맞춘 값을 받는다.

### 번호 칸의 표시

표시는 번호 뒤에 ` · ` 로 이어 쓴다. 예: `7 · #6 범위 안 · 처리 중(에이전트 B, 약 10분) · 수정됨`. 예전 기호(`⊂#N` `∩#N` `⏳` `✎` `⚠`)는 뜻이 드러나지 않아 짧은 말로 바꿨다. 겹침 표시는 핀당 하나이고, 우선순위는 같은 범위 > 범위 안 > 일부 겹침이다.

| 표시 | 뜻 | 에이전트의 행동 |
| --- | --- | --- |
| `#N과 같은 범위` | 열린 핀 `#N` 과 줄 범위가 똑같다. 같은 곳을 두 번 찍은 경우다. 그런 상대가 여럿이면 id가 가장 작은 것을 쓴다. 두 핀 모두에 붙는다 | 한 번에 고치고 둘 다 닫는다 |
| `#N 범위 안` | 이 핀이 열린 핀 `#N` 범위 **안**에 통째로 든다. 범위가 가장 작은 바깥 핀 하나만 표시한다. 뷰어 카드의 태그도 같은 규칙이라 이 파일과 화면 표기가 어긋나지 않는다 | `#N` 과 한 번에 고치고 둘 다 닫기를 권한다. 따로 고치면 같은 문단을 두 번 손대거나 `#N` 의 제약을 놓칠 수 있다 |
| `#N과 일부 겹침` | 일부만 겹친다. 위 둘이 없을 때만, id가 가장 작은 상대로 붙는다. 조사(`과`·`와`)는 숫자 읽기의 끝소리로 가린다(`#20과`, `#2와`) | 참고만 하고 각자 처리해도 된다 |
| `처리 중(<이름>, 약 N분)` | 다른 에이전트가 유효한 claim을 쥐고 있다(§처리 중 표시 (claim)). 이름은 `claimed_by.name` 이다. 토큰이면 토큰 이름, 헤더 없는 루프백 요청이면 `로컬/에이전트` 다. `약 N분` 은 남은 견적(5분 단위 올림)이고, 넘겼으면 `예상 초과`, 견적이 없으면 이름만 쓴다 | **건너뛴다.** 처리 중인 사람과 겹치지 않게 한다 |
| `수정됨` | 저장한 뒤 메모나 범위를 수정했다(`edited_at` 있음) | — |
| `위치 잃음` | 위치를 잃었다(`stale`) | 방금 그 범위를 직접 고친 직후라면 이미 반영됐을 수 있다. 원문을 확인하고 닫아도 된다. 무조건 사용자에게 보고할 필요는 없다. 단 방금 자기가 만든 변경이 원인일 때에 한한다 |

표시 범례 줄은 열린 핀에 표시가 하나라도 있을 때만 실린다. 모양은 `표시: '#N 범위 안'·'#N과 같은 범위' = … · '#N과 일부 겹침' = … · '처리 중(이름, 약 N분)' = … · '수정됨' = … · '위치 잃음' = … · «…» = …` 다.

### 질문·다시 열림·사람에게 물은 핀

번호 칸에는 다음 표시도 붙는다.

| 표시 | 뜻 | 에이전트의 행동 |
| --- | --- | --- |
| `질문` | 질문 핀(`kind_req=question`) | 답글을 단 뒤 따로 닫는다(§스레드 (답글)) |
| `다시 열림` | 마지막으로 완료된 뒤 다시 열린 적이 있다. 지금 차례가 다시 엶부터 시작한다 | — |
| `→ @이름` | 담당이 사람인 핀이다. 담당 없는 옛 핀은 사람에게 물은 질문 핀이다(§@태그·사람·이벤트) | 사용자가 시키지 않으면 건너뛴다 |
| `참고 @이름` | 알림만 간 참고용 태그다. 담당이 사람인 핀에서도 담당이 아닌 태그는 여기에 붙는다 | 건너뛰지 않는다 |

표시 순서(우선순위)는 `다시 열림` > `→ @이름`·`참고 @이름` > `질문` 이다. 메모 칸 뒤에는 지금 차례의 스레드가 `[스레드 N건] 이름: … ⏎ 다시 연 이유(이름): …` 로 붙는다. 뒤에서 3건, 한 건 200자까지다. 나머지는 `GET /api/pins/{id}` 로 읽는다. 사람에게 물은 핀이 있으면 안내 문단에 건너뛰기 규칙이 붙는다.

### 메모 칸의 덧붙임

**`«…»` 인용.** 메모 앞에 최대 60자 인용이 붙는 조건부 예외다. 다음 세 조건을 모두 만족할 때만 붙는다.

1. 핀 범위가 **한 줄**이다.
2. 그 줄이 **600자를 넘는다.** 문단 하나가 줄바꿈 없이 이어지는 원고에서는 줄 번호만으로 지목한 부분을 찾을 수 없다.
3. `scope` 가 `raw`·`para`·없음이다.

60자를 넘어 잘렸으면 인용 끝에 `…` 를 붙인다(예: `«문장의 앞부분까지만…»`). 잘린 인용을 완결된 문장으로 오인하지 않게 하려는 것이다.

> **주의**
>
> 이 인용은 `pdftotext` 로 렌더된 글자다. 검색 힌트일 뿐, `Edit` 의 `old_string` 으로 그대로 쓸 문자열이 아니다. 리거처, 하이픈, 공백이 원문 LaTeX 소스와 다를 수 있다. 줄 범위로 파일을 `Read` 한 뒤 인용을 검색해 정확한 위치를 확인한다.

**메모 앞 `[작성자]`.** 열린 핀의 작성자가 2명 이상이면 메모 앞에 `[<author.name>] ` 이 붙는다. 작성자는 `author.login` 으로 가르고, 작성자 없는 옛 핀은 한 부류로 친다.

- `@` 로 시작하지 않게 한 것은 @태그로 잘못 읽히지 않게 하려는 것이다. 실측에서 `@Alice Kim: …` 이 멘션처럼 보였다.
- 작성자가 1명뿐이면 토큰을 아끼려고 붙이지 않는다.
- 결과 보고나 `close` 의 `reply` 를 쓸 때 누구 핀인지 참고하는 용도다([domain.md](domain.md) §작성자 귀속). 배정 기준이 아니다.

### 검토 대기와 닫힌 핀

- **검토 대기**: 열린 표에서 빠지고 맨 아래 `## 검토 대기 N건 — …처리하지 않는다` 소절의 4열 표 `| # | 위치 | 확인할 사람 | 닫을 때 남긴 답 |` 에 실린다. 여러 문서면 위치 앞에 문서 키가 붙는다. 검토 대기 핀이 있을 때만 머리줄에 `검토 대기 N건(맨 아래, 처리하지 않는다)` 이 끼고, 없으면 머리줄은 예전 모양 그대로다.
- **닫힌 핀**: 표에서 빠지고 머리줄에 건수로만 남는다(`닫힌 핀 N건(뷰어의 '닫힌 핀'에서 확인)`). 닫힌 핀이 쌓여도 `<state_dir>/pins.md` 크기가 늘지 않는다. `<details>` 로 펼쳐야 했던 예전 방식은 없앴다.

### 여러 문서

`--doc` 이 둘 이상이거나, 첫 문서가 아닌 키의 열린 핀이 있으면 여러 문서 모양이 된다. 파일은 한 장 그대로다.

1. 머리에 `` 문서: 본문(`ms`) 3건 · … · 리뷰어 코멘트(`rv`, 보기 전용) 1건 `` 한 줄과 소절 안내를 둔다.
2. 열린 핀이 있는 문서마다 소절 `` ## <이름> · `<키>` · `<--manuscript 기준 경로>` `` 를 둔다. 보기 전용이면 제목 끝에 `— 보기 전용 PDF(줄 번호 없음)` 이 붙는다.
3. 소절 안에 그 문서의 `기준: <head> · 빌드 <built_at>` 줄이 온다. 보기 전용은 `빌드` 대신 `그림` 이다. 그 뒤에 5열 표가 온다.

머리의 단일 `기준:` 줄은 소절로 옮겨 간다. 설정에 없는 문서 키의 핀은 `` ## 설정에 없는 문서 · `<키>` `` 소절로 드러난다. 단일 문서는 예전 모양 그대로다.

### 보기 전용 핀의 행

- 위치 칸은 `쪽 3, 영역 가로 10–60% 세로 20–30%` 모양이다.
- 범위 칸은 `영역` 이다.
- 메모 앞에 영역 글자 `«…»` 가 늘 붙는다. 한 줄·600자 조건이 없다. 줄 번호가 없어 영역 글자가 유일한 원문 단서이기 때문이다.
- 보기 전용 핀이 있으면 안내 문단에 "줄 번호가 없다 — 쪽·영역 글자·메모로 판단, 고칠 곳은 LaTeX 문서에서" 가 붙는다.

### 이스케이프

이스케이프 규칙은 모든 칸에 같고, 한 함수(`md_cell`)로 처리한다.

- `|` 는 `\|` 가 된다.
- 줄바꿈은 메모 칸에서 `⏎`, 나머지 칸(번호, 쪽, 위치, 범위, 인용)에서 공백이 된다.

칸마다 따로 처리하던 때 범위 칸의 env 분기가 빠져, kind `env:x|y` 가 8열 행을 만든 적이 있다(독립 검증 실측). 그래서 한 함수로 모았다.
