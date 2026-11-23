# 설계: 소유자가 뷰어에서 테일넷 사용자를 들이고 뺀다 (viewer access management)

> **승인됨 — 소유자, 2026-11-22.** 이 문서의 설계를 **한 PR로** 시공하는 것으로 승인했다. 이것이 [workflow.md](../../handbook/workflow.md) §핵심이 요구하는 "소유자가 설계 문서에서 그 설계를 명시적으로 승인한 기록"이다. 화면은 **네 기기군 PoC를 소유자가 고른 뒤에만** `main`에 들어가고, PR은 초안으로 두고 머지 전에 소유자 승인을 다시 받는다.
>
> 기준 `main` `62c915a1`(v0.4.68). 이 설계는 **보안 경계(신원 신뢰·역할 권한)** 와 **에이전트 계약(HTTP 경로)** 과 **저장 형식(상태 디렉터리 새 파일)** 을 모두 건드린다.
>
> 소유자가 2026-11-22에 고른 것 셋 — ① 테일넷 목록은 **LocalAPI만**(자격증명 없음, 부분 목록임을 화면에 명시), ② 허용 목록의 정본 전환은 **소유자가 누르는 일회 전환**(자동 흡수하지 않는다), ③ 마지막 `owner` 보호는 **화면과 CLI 두 문 모두**를 묶는다. 그 밖에 이 문서가 §내가 정한 것으로 박은 결정은 구현자가 추측하지 않도록 답을 적어 둔 것이고, 소유자가 읽고 뒤집을 수 있다.
>
> 되돌리기 어려운 결정이라 **ADR-0055**를 함께 쓴다(ADR-0002 §2 권한 층의 "소유자 전용 작업은 당분간 CLI 수준" 조항을 **부분 대체**). ADR-0002·0003·0007 본문은 동결이라 건드리지 않는다([workflow.md](../../handbook/workflow.md) §결정 기록).
>
> **승인 뒤에 고친 문장 셋.** 앞의 둘은 설명 문장이고, 셋째는 **결정 조항 하나**다 — 소유자가 2026-11-23에 고치기로 정했다.
>
> **① §F, 모양 규칙의 줄 높이.** `줄 높이 마우스 32px·터치 44px` 이라고 적고 있었다. 접근 관리의 멤버 행은 이름 위에 로그인이 오는 **두 줄** 행이라 그 수가 맞지 않는다 — 32px은 `css/tokens.css` 의 한 줄 메뉴 행(`--row-h-sm`, 터치는 `--hit`)이고, 두 줄 행의 토큰은 `--row-h`(48px)·`--row-h-touch`(56px)다. 그래서 그 조항이 이미 요구한 "기존 토큰만 쓴다"에 맞춰 수를 토큰 이름으로 바꿨다. **소유자가 2026-11-23에 네 기기군 비교 화면을 보고 48/56을 지키기로 정했다** — 32px을 강제한 화면은 두 줄 행이 넘쳐 데스크톱에서 37~38px이 되고 목록의 율동이 37·38·37·38로 깨졌다. 화면·CSS·토큰은 처음부터 맞았고 문서만 틀렸다.
>
> **② §검증, 전환의 원자성.** 그 항목은 "뒤가 실패해도 넓어지지 않음"이라고 적고 있었다. 시공 중의 시험이 그 반례를 보였다. `--members-only` 인스턴스는 관리 모드가 아니어도 `people.json`으로 입장을 정하므로, `people.json`은 썼고 `access.json`은 못 쓴 절반은 그 누름이 쓴 줄만큼 입장을 **넓힌다**. 그래서 그 문장을 사실대로 고쳤고, 서버는 그 경우를 아무것도 쓰지 못한 실패와 가른 `500 flag_not_written`으로 알린다.
>
> **③ §내가 정한 것 #9, `locks_out_owner`의 규칙 — 결정 조항이다.** "요청한 소유자가 전환 뒤 목록에 없으면 거부한다"라고 적고 있었다. 그 규칙에는 구멍이 있었다 — `--allow`가 자기를 가리키지 않는 인스턴스에서 유일한 소유자가 관리를 **끄면**, 깃발이 꺼져 `--allow`가 다시 걸러 자기가 못 들어오고 소유자 역할을 가진 사람이 아무도 남지 않는다(전체 리뷰가 Critical로 짚었다). 그래서 규칙을 "이 누름이 만드는 상태가 요청자를 들여보내는가"로 바꿨고, 그 판단은 입장 판정과 같은 함수를 쓴다. 덤으로 모두가 들어오는 인스턴스에서 예전 규칙이 내던 거짓 거절도 사라졌다. **소유자가 2026-11-23에 이 교체를 확정했다.**

## 문제

소유자가 공저자 한 명을 인스턴스에 들이려면 지금은 **ssh로 들어가 env 파일을 고치고 유닛을 재시작**해야 한다. 화면에서 바꿀 방법이 하나도 없다.

2026-11-22 TMHP 논문 답변서 작업에서 실제로 막혔다. 인스턴스 `mac-18352`(리눅스 호스트, `--auth tailscale`)는 `EXTRA_ARGS=--allow <소유자 로그인>` 하나로 떠 있었고, 공저자는 **테일넷 안에 멀쩡히 있는데도** 403을 받았다. 원인은 `admit()`의 분기다 — [`src/limn/security/access.py:561`](../../../src/limn/security/access.py):

```python
if p.via == "header":
    if settings.members_only:
        if login not in settings.allow and not is_member(roles(), login): → 403 not_member
    elif settings.allow and login not in settings.allow:                  → 403 not_allowed
```

`--members-only`가 꺼진 채 `--allow`만 있으면 **`limn member add`가 아무 효과가 없다.** `--allow`가 먼저 걸러내고, `people.json`은 `--members-only`일 때만 입장 판정에 들어온다. 소유자를 함정에 빠뜨리는 자리다.

그리고 `--allow`는 **프로세스 인자**다. `RunConfig.allow`로 기동 때 고정되고([`config.py:66`](../../../src/limn/runtime/config.py)) `AccessSettings.allow`로 흘러간다. `people.json`은 요청마다 `FileCache`로 다시 읽히지만([`access.py:119` `AccessLookups`](../../../src/limn/security/access.py)) `--allow`는 재시작 없이는 바뀌지 않는다. **GUI로 바꾸려면 정본이 파일이어야 한다**는 요구가 여기서 나온다.

## 실측 (2026-11-22)

| 잰 것 | 값 | 어떻게 |
| --- | --- | --- |
| 이 맥이 보는 테일넷 사용자 | **2명** (peer 18) | `tailscale status --json`의 `User` 맵 길이 |
| 그 리눅스 호스트가 보는 테일넷 사용자 | **6명** (peer 27) | 같은 명령, ssh |
| 두 기기가 같은 테일넷인가 | **같다** | `CurrentTailnet.Name` 해시 양쪽 `d17c810c…` |
| `User` 맵의 필드 | `DisplayName` `ID` `LoginName` `ProfilePicURL` **넷뿐** | 같은 출력 |
| LocalAPI와 CLI의 스키마 | **같다** (CLI가 들여쓰기만 입힌다) | 최상위 키·`Self`·`User`·`Peer` 필드 전부 일치 |
| 리눅스 소켓 | `/run/tailscale/tailscaled.sock`, **모드 0666 root:root** | `stat`; `/var/run/tailscaled.socket`은 **없다** |
| 리눅스에서 operator 설정 필요 여부 | **불필요** (`OperatorUser`가 다른 계정인데도 읽힌다) | `tailscale debug prefs` + 실제 호출 200 |
| systemd --user 유닛 환경 | **된다** (유닛 PATH에 `/usr/bin` 있음) | `systemd-run --user --pipe` → 200 |
| 맥 전송 | 유닉스 소켓 **없음**. `/Library/Tailscale/ipnport`(심링크 타깃=포트) + `sameuserproof-<포트>`(0640 root:**admin**) → TCP + HTTP Basic | `readlink`, `ls -l`, 실제 호출 200 |
| 표준 라이브러리만으로 호출 | **양쪽 OS 성공** (`http.client` + `socket.AF_UNIX` / TCP + `base64`) | 의존성 0으로 `status 200` 확인 |
| 맥 서브프로세스 함정 | 환경변수가 깎인 컨텍스트에서 **종료코드 0 + 비-JSON 영문 메시지** | `env -i PATH=… HOME=… Tailscale status --json` → exit 0, "The Tailscale GUI failed to start…" |

**가장 중요한 실측**: `User` 맵은 "테일넷 사용자 목록"이 아니다. 그 노드의 netmap에 보이는 peer의 *소유자*만 담고, netmap은 ACL로 걸러진다. 같은 테일넷에서 2명과 6명으로 갈린 것이 그 증거다. 장치가 하나도 없는 사용자, ACL로 가려진 사용자, 초대 대기 중인 사용자는 **영원히 안 보인다.** 테일넷 역할·계정 상태도 없다.

## 의도와 왜

소유자가 뷰어 안에서 ① 같은 테일넷에 누가 있는지 보고 ② 그 가운데 누구를 이 인스턴스에 들일지 고르고 ③ 역할(viewer/editor)을 정하고 ④ 빼는 것까지, **재시작 없이** 한다. ssh와 env 파일과 `systemctl restart`가 공저자 한 명을 들이는 길에서 사라지는 것이 목적이다.

## 목표

1. `--auth tailscale`·`--auth local`·`--auth trusted-proxy` 어디서나, 소유자가 뷰어 패널에서 멤버를 **더하고·역할 바꾸고·빼고**, 다음 요청부터 반영된다(재시작 없음).
2. 그 패널이 **이 서버에 보이는 테일넷 사용자**를 후보로 보여 주고, 목록이 부분적임을 화면에 적는다. 목록에 없는 사람은 로그인을 직접 적어 넣을 수 있다.
3. `--allow`와 `people.json`이 어긋나 소유자를 함정에 빠뜨리는 상태가 **그 인스턴스에서 사라진다** — 소유자가 전환을 누른 뒤에는 정본이 하나다.
4. 전환을 누르기 전까지 `admit()`의 판정은 **한 글자도 바뀌지 않는다.** 판올리기만으로 들어오는 사람이 늘지 않는다.
5. 모든 변경이 `audit.jsonl`에 남는다(기존 `member_added`·`member_role`·`member_removed` 재사용, `via:"http"`).

## 비목표

- 테일넷 **전체** 사용자 목록. Admin API 자격증명을 Limn이 보관하는 길은 소유자가 이번에 고르지 않았다. 부분 목록 + 직접 입력으로 간다.
- `owner` 역할을 화면에서 주는 일. 최초 소유자 지정은 CLI만 한다(§내가 정한 것 1).
- 토큰(`limn token`) 관리의 화면 이전. 멤버만 다룬다.
- 초대 링크, OIDC, 세션 — ADR-0002의 v1.0 단계다.
- `MEMBERS_ONLY`·`EXTRA_ARGS` 같은 인스턴스 설정 키의 자동 정리. 전환 뒤 그 인자는 무시되고 기동 로그가 그렇다고 말하지만, env 파일을 서버가 고치지는 않는다.
- SSE·실시간. 패널은 열 때와 변경 뒤에 다시 읽는다.

## 안티목표 (이것이 되면 기술적으로 작동해도 실패다)

1. **판올리기나 전환이 들어오는 사람을 조용히 늘린다.** 전환 화면이 "지금 들어오는 사람"과 "전환 뒤 들어오는 사람"을 나란히 보이지 않거나, 늘어나는 쪽을 소유자가 못 보고 지나치면 실패다.
2. **화면에서 자기 권한을 올릴 수 있다.** 테일넷에 닿는 사람이 `owner`가 되는 경로가 하나라도 생기면 실패다.
3. **소유자가 자기를 잠근다.** 마지막 owner를 빼거나 내리는 것이 가능하면 실패다.
4. **테일넷 사용자 목록이 아무에게나 보인다.** 소유자 아닌 사람이 `/api/access`를 읽을 수 있으면 실패다.
5. **`tailscaled`가 없으면 패널이 죽는다.** 목록을 못 얻는 것은 정상 상태이고, 직접 입력으로 떨어져야 한다.
6. **목록을 읽는 일이 요청을 멈춘다.** LocalAPI 호출이 느리거나 걸려서 뷰어가 기다리면 실패다.
7. **`people.json`을 또 하나의 writer가 건드린다.** 형식·잠금 규칙 밖에서 쓰면 실패다.

## 제약

- 서버 런타임은 **표준 라이브러리만** 쓴다(`dependencies = []`, [architecture.md](../../handbook/architecture.md) §불변식 2). LocalAPI는 `http.client`·`socket`·`json`·`base64`로 부른다. 실측으로 가능함을 확인했다.
- **새 외부 서비스를 요구하지 않는다.** `tailscaled`는 **있으면 쓰고 없으면 없는 것으로 둔다.** 설치·실행 조건에 들어가지 않는다.
- 신원·입장·역할 판단과 그 비교는 [`security/access.py`](../../../src/limn/security/access.py) **한 곳**에 있다(§불변식 1). 역할 비교를 뷰어 라우트나 기능 슬라이스에 쓰지 않는다.
- 역할·신원 방식·신원 경로는 닫힌 `Literal`이고, **모르는 값은 `viewer`** 다.
- 알 수 없는 경로는 **기본 거부**(`check_read`·`post_operation`). 디스패처 등록만으로 권한이 생기지 않는다([api.md](../../handbook/api.md) §권한).
- HTTP 경로·필드·상태 이름·`reason` 코드는 **더하기만** 한다. 기존 `error` 문장은 글자 하나 바꾸지 않는다.
- 상태 파일은 `atomic_write` + `store_lock`을 거쳐서만 쓴다. 모드 `0600`.
- **GET은 영속 상태를 바꾸지 않는다**(§불변식 10). 새 GET도 아무것도 쓰지 않는다.
- 뷰어의 역할 게이팅은 **숨기는 것으로 끝내지 않고 그리지 않는다**([viewer.md](../../handbook/viewer.md) §역할에 따른 화면).
- 실제 이메일·호스트 이름을 코드·문서·시험에 넣지 않는다(`alice@example.com`, `box.tail1234.ts.net` 꼴).
- 화면이 바뀌므로 `main` 전에 **네 기기군 PoC**를 소유자에게 보인다([workflow.md](../../handbook/workflow.md) §화면 변경은 PoC를 먼저 보인다).

## 현재 권위와 상태

- **`security/access.py`** — 정본. `AccessSettings`(기동 고정) / `AccessLookups`(요청마다 파일 다시 읽음)의 구분이 이 설계의 축이다. `admit()`는 `p.via == "header"`인 사람만 걸러내고, 토큰과 로컬 소유자는 늘 들어온다. `check_read(path)`는 **역할을 보지 않는다**. `check_role(p, path, trash_days)`가 POST만 역할로 가른다. 소유자 전용 경로는 `OWNER_POSTS = ("/api/clear",)`와 `OWNER_POST_RE`(`purge`) 둘뿐이고, docstring이 **"Other owner-only operations - members, tokens, settings - are CLI/file level."** 이라고 적는다([`access.py:609`](../../../src/limn/security/access.py)). 이 문장을 바꾸는 것이 ADR-0055의 핵심이다.
- **`security/people.py` · `administration/member_state.py`** — `people.json`의 두 writer. 서버의 `record_person()`과 CLI의 `_people_update()`가 **같은 `store_lock(state, "people")`** 과 같은 `people_text()` 형식을 쓴다. `people_text()`는 문서를 `{"version":1,"people":rows}`로 **다시 짓는다** — 이것이 §내가 정한 것 2의 근거다.
- **`load_people()`** — 없는 파일은 `[]`, **있는데 못 쓰는 파일은 `PeopleUnreadable`** 로 갈라 fail closed 한다. 새 파일도 이 갈라치기를 따른다.
- **`web/handler.py`** — 검사 순서가 계약이다(`api.md` §검사 순서): 본문 → Host/Origin → `identify` → `admit` → (POST) `check_role` → 본문 형식 → 권한 발급. `check_read`는 GET 경로에서 불린다.
- **`collaboration/routes.py`·`http.py`** — `GET /api/people`가 이미 `{people:[{login,name,pic?,last_seen?,role}], me:{…,role}}`를 준다. 패널의 멤버 목록은 이 답을 쓴다.
- **뷰어가 자기 역할을 아는 경로는 `/api/people`가 아니라 `/api/meta`다.** `documents/state.ts:65 isViewer()`는 `META.me.role`을 읽고, `me`는 [`documents/http.py:41`](../../../src/limn/documents/http.py)이 넣는다. `documents/view-meta.ts:116`이 그 값으로 `body.role-viewer`를 토글한다. 그래서 §F의 `body.role-owner`도 **`/api/meta`의 `me.role`** 을 따라가고, 역할이 바뀌었을 때 무효화해야 하는 것은 `/api/meta` 폴링이다. **`body.role-owner`는 아직 없다.**
- **뷰어 `#more` 다이얼로그** — 설정류가 모여 있는 자리. `.more-grid`의 `#m-trash`가 "따로 선 패널로 가는 항목"의 본보기이고, `#trash` 다이얼로그가 "독립 패널"의 본보기다(`pins/view-cards.ts:435 drawTrash`). 배경 클릭 닫기 목록은 `layout/flow.ts:898`, 뒤로가기 레이어는 `layout/flow-back.ts:32`와 `:84`에 셀렉터가 **각각 하드코딩**돼 있다.
- **`tools/check_viewer_boundaries.mjs`** — `FEATURES`(L43) · `ALLOWED`(L62)에 새 feature를 등록해야 `npm run boundaries`가 통과한다. 모듈 이름은 `<feature>/<role>.ts`, role은 `rules|state|api|view|input|flow`.
- **`viewer/assemble.py:115 STYLESHEETS`** — 새 CSS는 여기 등록해야 `test_viewer_files.py`가 통과한다. JS는 `js/main.ts`에서 import 체인이 닿기만 하면 된다.

### 충돌·미확인

- **`mac-18352`의 `people.json`을 읽지 않았다.** 돌고 있는 인스턴스를 건드리지 말라는 지시 때문이다. 그래서 그 인스턴스에서 "전환하면 새로 들어오게 되는 사람"이 몇 명인지 모른다. **전환 화면이 그 수를 그 자리에서 세어 보이는 것이 이 미확인에 대한 답이다** — 설계가 수를 미리 알 필요가 없게 만든다.
- 리눅스 LocalAPI 소켓이 **operator 설정과 무관하게 읽힌다**는 것은 실측했으나(그 호스트에서), 쓰기(`PermitWrite`)가 막히는지는 변이를 피하려고 확인하지 않았다. 이 설계는 **읽기만** 하므로 영향이 없다.
- 맥 App Store 샌드박스판은 전송 경로가 또 다르다(`lsof`로 `IPNExtension` 추적). 이 맥은 standalone(`macsys`)판이라 해당이 없다. 샌드박스판은 **지원하지 않고 "목록 없음"으로 떨어진다**(§내가 정한 것 6).

## 접근 (검토한 것과 고른 것)

### 테일넷 목록의 출처

| 안 | 내용 | 왜 버렸나 / 골랐나 |
| --- | --- | --- |
| **LocalAPI 직접 (고름)** | `/localapi/v0/status`를 표준 라이브러리 HTTP로 | 의존성 0, 비밀값 0, 바깥 네트워크 0. 오늘 막힌 일을 실제로 푼다. 목록이 부분적인 것은 화면에 적어 해결한다 |
| `tailscale status --json` 서브프로세스 | 같은 데이터 | **버렸다.** 같은 데이터를 얻으면서 맥의 "exit 0 + 비-JSON" 실패 모드만 더해진다(실측 재현) |
| Admin API | 완전한 목록 + 역할·상태 | **버렸다(소유자 결정).** API 키나 OAuth secret 보관이라는 새 보안 경계가 생기고 서버가 바깥으로 나간다 |
| 목록 없음 | 직접 입력만 | **버렸다(소유자 결정).** 요구사항 ①을 포기한다 |

### 허용 목록의 정본

| 안 | 내용 | 왜 버렸나 / 골랐나 |
| --- | --- | --- |
| **소유자가 누르는 일회 전환 (고름)** | 전환 전까지 `admit()` 그대로. 패널이 전환 화면을 먼저 보이고, 소유자가 누르면 상태 파일에 표시하고 `--allow`의 계정을 멤버로 옮긴다 | 들어오는 사람이 소유자 모르게 늘지 않는 **유일한** 안. 안티목표 1을 구조로 막는다 |
| 판올릴 때 자동 흡수 | 서버가 알아서 이관 | **버렸다(소유자 결정).** `--allow` 밖인데 `people.json`에 이미 기록된 사람이 조용히 다시 들어온다. 그 수를 아무도 모른다 |
| `--allow` 목록만 파일로 | 의미 그대로, 목록만 편집 가능 | **버렸다(소유자 결정).** "허용 목록"과 "멤버 목록"이 끝까지 둘로 남아 오늘의 함정이 유지된다 |

### 입장과 역할을 한 축으로 둘지

| 안 | 내용 | 판단 |
| --- | --- | --- |
| **멤버십 = 입장 (고름)** | 전환된 인스턴스에서 `people.json`에 줄이 있으면 들어오고, 역할이 할 수 있는 일을 정한다 | 개념이 하나다. 전환 화면이 "빼야 할 사람"을 소유자에게 보여 처리하므로 두 축이 필요 없다 |
| 줄에 `admit` 필드를 더한다 | 기록은 남기고 입장만 끈다 | **버렸다.** (입장 × 역할) 두 축은 오늘의 "두 목록" 혼란을 모양만 바꿔 되살린다. 기록 손실은 `member_removed` 감사 줄과 핀 작성자에서 오는 `known_people`로 메워진다 |

## 결정한 것

### A. 상태 — `<state>/access.json` 하나, 플래그 하나

```json
{"version": 1, "managed": true, "managed_at": "2026-11-22 21:40:11", "managed_by": "alice@example.com"}
```

- 입장 판정이 읽는 것은 **`managed`뿐**이다. 나머지는 패널이 보여 줄 내력이다.
- **없는 파일** = 관리 안 함 → `admit()`은 오늘과 **똑같이** `--members-only`·`--allow`를 쓴다.
- **있는데 못 쓰는 파일**(읽기 실패·JSON 아님·모양 아님) = **fail closed**. 헤더로 들어온 사람은 전원 `403`(새 코드 `access_unreadable`, 어느 파일이 왜 나쁜지 적는 안내 화면)이고 stderr에 한 번 경고한다. 토큰과 로컬 소유자는 영향이 없어 소유자가 고칠 길이 남는다. `people.json`의 같은 규칙과 같은 철학이다([SECURITY.md](../../../SECURITY.md) "An unusable `people.json` fails closed").
- 요청마다 `FileCache`로 다시 읽는다 → 전환과 멤버 변경이 **재시작 없이** 반영된다.
- **`people.json`에 키를 더하지 않는 이유**: `people_text()`가 문서를 rows로 다시 짓고 writer가 둘(서버·CLI)이다. 다른 판의 CLI가 한 번 쓰면 모르는 키를 **조용히 떨어뜨려** 보안 정책이 꺼진다. 별 파일은 그 두 writer가 건드리지 않는다.
- 되돌리기: 옛 판으로 내려가면 `access.json`을 읽지 않고 `--allow`로 돈다 → 전환 뒤 더한 사람은 **못 들어온다**(닫히는 쪽). 운영 문서에 적는다.

### B. 입장 판정 — `admit()`에 분기 하나를 **앞에** 둔다

```python
if p.via == "header":
    if managed():                    # access.json
        if not is_member(roles(), login): → 403 not_member (기존 코드·기존 안내 화면)
    elif settings.members_only:      # 이하 한 글자도 바뀌지 않는다
        …
    elif settings.allow and login not in settings.allow:
        …
```

- `managed`는 `AccessSettings`(기동 고정)가 아니라 **요청마다 읽는 사실**이다. `admit()`에 **기본값 없는 새 매개변수**로 더한다 — `AccessLookups`에 넣는 것으로는 안 된다. `admit()`은 `lookups`를 받지 않고 맨 `roles: Callable[[], PeopleRoles]`를 받으며([`access.py:561`](../../../src/limn/security/access.py)) `RequestGuards.admit`도 `self.roles`만 넘긴다([`application.py:46`](../../../src/limn/security/application.py)). `AccessLookups`에 필드를 더하면 조립 자리 한 곳만 묶이고 `admit()`의 호출 자리는 아무 말도 하지 않게 된다. 매개변수로 더하면 시험을 포함한 모든 호출 자리가 값을 말한다.
- 타입은 닫힌 값이다 — `Managed` · `NotManaged` · `AccessUnusable` 셋. `bool`로 두면 "못 쓰는 파일"이 `False`(= 오늘 동작)로 조용히 접힌다.
- 전환된 인스턴스에서 `--allow`·`--members-only`는 **무시된다.** 기동 `auth` 로그 줄에 그렇게 적고, 둘 다 주어졌으면 그 줄이 "access.json이 정본"이라고 말한다.
- **전환된 인스턴스에서 빈 `people.json`은 "전원 허용"이 아니라 "아무도 아님"이다.** 오늘의 "목록이 비면 전부 허용"은 관리 안 하는 인스턴스에만 남는다. 이 차이를 `api.md`·`operations.md`·`SECURITY.md`에 명시한다.
- 전환된 인스턴스에서는 모르는 사람이 입장하지 못하므로 **첫 변경 때의 자동 기록(editor)도 일어나지 않는다.** 멤버는 소유자가 명시로만 생긴다.

### C. 전환 — 소유자가 보고 누른다

패널을 열면 관리 안 하는 인스턴스에서는 전환 화면이 먼저 선다. 그 화면이 서버에서 그 자리에 세어 보이는 것:

| 칸 | 내용 |
| --- | --- |
| 지금 들어오는 사람 | `--allow` 목록 ∪ (`--members-only`면 `people.json` 멤버). 아무 목록도 없으면 "테일넷의 모두" |
| 전환 뒤 들어오는 사람 | 소유자가 이 화면에서 체크한 사람들 |
| **새로 들어오게 되는 사람** | 위 둘의 차. 들어오게 하려면 소유자가 켜야 한다 |
| 빠지게 되는 사람 | 체크가 꺼진 사람. 전환이 `member_removed`로 지운다 |

**기본 체크 상태는 "지금 들어오는 사람 그대로"다 — 전환은 기본값에서 무동작(no-op)이다.** 두 대안은 이미 승인된 제약에 걸려 버린다: 전부 체크 해제로 두면 **지금 들어오는 사람이 전환 즉시 잠긴다**(안티목표 3), `people.json`의 모든 줄을 체크해 두면 `--allow` 밖인 사람이 **조용히 들어온다**(안티목표 1). 그래서 기본값은 선택이 아니라 도출이다.

- `--allow`에만 있고 `people.json`에 줄이 없는 로그인은 **체크된 상태로 보이고**, 전환이 그 줄을 만든다(역할은 `editor` — 지금 `person_role`이 그들에게 주는 값과 같다).
- `people.json`에 줄이 있으나 지금 안 들어오는 사람은 **체크 해제로 보이고**, "지금 못 들어옴 → 켜면 새로 들어옴"이라고 적는다.
- **`owner`와 `agent` 역할의 줄은 전환 화면이 고정으로 보이고 체크를 끌 수 없다.** 본문에 빠뜨려서 owner가 지워지는 길을 없앤다(안티목표 3). 요청 본문이 그 줄을 언급하지 않아도 서버는 **보존한다** — 본문은 "이 목록대로 맞춰라"가 아니라 "`viewer`/`editor` 줄을 이 목록대로 맞춰라"다.

- `POST /api/access/managed` 본문: `{"managed": true, "members": [{"login", "role"}, …], "confirm": "manage access from the viewer"}`. 확인 문구는 `/api/clear`의 방식을 따른다.
- 서버는 `store_lock(state, "people")` 안에서 `people.json`을 목표 상태로 맞추고, 그 뒤 같은 잠금 안에서 `access.json`을 쓴다. 감사 줄은 변경마다 하나씩.
- **요청한 소유자가 목록에 없으면 거부한다**(새 코드 `locks_out_owner`). 안티목표 3.
- 관리를 **끄는** 것도 같은 경로다(`{"managed": false, "confirm": …}`). 넓히는 변경이므로 "끄면 `--allow`/`--members-only`로 돌아가고, 지금 들어오는 사람이 이렇게 바뀝니다"를 같은 모양으로 보인 뒤에만 보낸다.

### D. HTTP — 더하는 것 전부

| 메서드·경로 | 누가 | 하는 일 |
| --- | --- | --- |
| `GET /api/access` | **owner만** | `{managed, managed_at?, managed_by?, args:{allow:[…], members_only}, members:[{login,name,role,last_seen?}], tailnet:{users:[{login,name,pic?}], partial:true, reason?}}` |
| `POST /api/access/managed` | owner만 | §C |
| `POST /api/members/add` | owner만 | `{login, role, name?}` → `member_state.member_add` |
| `POST /api/members/role` | owner만 | `{login, role}` → `member_state.member_set_role` |
| `POST /api/members/remove` | owner만 | `{login}` → `member_state.member_remove` |

- **읽기도 역할로 가른다.** `check_read`가 `principal`을 받고 `OWNER_READS = frozenset({"/api/access"})`를 적용한다. 역할 비교가 `access.py` 안에 남는다. 기존 경로는 영향이 없다. 안티목표 4.
- POST는 `MEMBER_OPERATIONS` 표로 `post_operation()`에 등재하고 `OWNER_POSTS`에 더한다. 등재 없이는 `404`, 역할 없이는 `403` — 기본 거부가 유지된다.
- `authority_scope(operation)`가 이 작업들에 **people 저장소**를 효과 소유자로 주고, 싱크가 `require_authority(authority, scope, operation, login)`로 검사한다.
- `role`은 `viewer`·`editor`만 받는다. `owner`·`agent`는 `400`(새 코드 `role_not_settable`). 안티목표 2.
- 마지막 `owner`를 빼거나 내리면 `409`(새 코드 `last_owner`).
- 관리 안 하는 인스턴스에서 멤버 POST는 `409`(새 코드 `not_managed`) — "먼저 전환하세요".
- 새 `reason` 코드: `access_unreadable` · `locks_out_owner` · `role_not_settable` · `last_owner` · `not_managed`. 기존 코드와 문장은 그대로 둔다. 서버가 내는 코드마다 `ui_en.json`에 영어 문장을 더한다.

### E. 테일넷 목록 — 읽기만, 짧게, 실패해도 조용히

- 전송은 `platform/` 에 둔다(`security/`는 I/O에 닿지 않는 "판단" 역할, [code-style-roadmap.md](../../handbook/code-style-roadmap.md) §R11). 새 모듈 `src/limn/platform/tailnet.py`:
  - 리눅스: `socket.AF_UNIX` + `http.client.HTTPConnection` 서브클래스. 소켓 경로는 후보를 순서대로 본다 — `/run/tailscale/tailscaled.sock`, `/var/run/tailscale/tailscaled.sock`, `/var/run/tailscaled.socket`.
  - 맥: `readlink /Library/Tailscale/ipnport`로 포트, `sameuserproof-<포트>`로 토큰 → `127.0.0.1:<포트>` + HTTP Basic(사용자 빈칸). **파일이 stale일 수 있으므로** 연결 실패는 정상 실패로 다룬다.
  - `Host: local-tailscaled.sock` 고정. **`Origin`·`Referer`를 보내지 않는다** — 하나라도 있으면 tailscaled가 `403`이다(실측).
  - 타임아웃 **1초**, 응답 본문 상한을 두고 읽는다. 실패·시간 초과·`BackendState != "Running"`은 전부 "목록 없음 + 이유"로 돌려준다. 예외를 올리지 않는다. 안티목표 5.
- 투영은 `User` 맵에서 `LoginName`·`DisplayName`·`ProfilePicURL`만 꺼내고, **이미 멤버인 사람과 유효하지 않은 로그인(`valid_login`)은 뺀다.** `partial: true`를 늘 붙인다.
- **소유자 전용 GET에서만** 부른다. 폴링 경로가 아니라 패널을 열 때와 변경 뒤에만 불린다. 값을 몇 초 기억해 연타를 막는다. 백그라운드 스레드를 만들지 않는다. 안티목표 6.
- `--auth local`·`trusted-proxy` 인스턴스에서도 같은 목록을 보인다(그 기기가 테일넷에 있으면 쓸 수 있고, 없으면 "목록 없음"이다).

### F. 화면

- **진입점**: `#more`의 `.more-grid`에 `접근 관리`. **소유자에게만 JS로 그린다**(index.html에 두고 숨기지 않는다 — viewer.md §역할에 따른 화면). `body.role-owner`를 `documents/view-meta.ts`가 토글한다.
- **패널**: `#trash`를 본보기로 한 `<dialog id="access">`. 세 구획 —
  1. **이 인스턴스의 멤버** — 로그인·이름·역할 분절(`viewer`/`editor`)·마지막 접속·[빼기]. 자기 줄과 마지막 owner 줄은 조작을 **그리지 않는다**.
  2. **테일넷에서 들이기** — 보이는 사용자 목록, 각 줄에 역할 고르개와 [들이기]. 머리에 "이 서버에 보이는 사용자만 — ACL이나 장치 없는 계정은 안 보입니다" 한 줄. 목록이 없으면 그 자리에 이유.
  3. **로그인으로 들이기** — 입력 칸 + 역할 + [들이기]. 목록에 없는 사람을 위한 길이고, 목록이 없을 때의 대체 경로다.
- 관리 안 하는 인스턴스에서는 위 셋 앞에 **전환 화면**(§C)이 선다.
- 모양 규칙: 기존 토큰만 쓴다(`css/tokens.css`), **둥근 모서리 + 한쪽 강조선 조합을 쓰지 않는다**, 줄 높이는 두 줄짜리 멤버 행의 토큰으로 — 마우스는 `--row-h`, 터치는 `--row-h-touch` 다(32px은 그 파일의 **한 줄** 메뉴 행 `--row-h-sm` 이고 터치는 `--hit` 이라, 두 줄 행에는 맞지 않는다), 다이얼로그는 `showSheet()` 재사용.
- 새 파일: `css/access.css`(→ `assemble.py` `STYLESHEETS` 등록), `js/access/{state,view-panel,flow}.ts`(→ `check_viewer_boundaries.mjs` `FEATURES`·`ALLOWED` 등록, `main.ts` import·디스패치·Esc), `layout/flow.ts:898`·`flow-back.ts:32,84`에 `#access` 더하기.
- `types/api.d.ts`에 `AccessAnswer`·`TailnetUser`·`ApiAnswers`·`ApiRefusals` 항목. `ui_en.json`에 새 한국어 문자열 전부. `tools/page_elements.py` 재생성. `npm run build` 결과 `dist/viewer.js`를 같은 커밋에.

### G. 쓰기 코드가 어디 사는가 (시공자 검토가 찾은 자리)

검토자가 §D의 싱크가 **지금 구조에서 닿지 않는다**는 것을 찾았고, 확인했다. `administration`은 기능 capability이고([`check_boundaries.py:14`](../../../tools/check_boundaries.py)) 그 공개 표면 `__all__`에 멤버 쓰기 함수가 **없다**([`administration/__init__.py:13`](../../../src/limn/administration/__init__.py) — `cmd_member`만 있다). 경계 검사는 **기능이 아닌 모듈(`security/`·`web/`)이 어떤 import 사슬로도 기능 모듈에 닿는 것**을 거부한다(`check_boundaries.py` `violations()`).

- **쓰기 기본 연산은 [`security/people.py`](../../../src/limn/security/people.py)에 둔다.** 그 모듈이 이미 people 저장소의 주인이다 — `people_text`·`load_people`·`PeopleUnreadable`을 소유하고, `record_person()`이 `store_lock(state, "people")` 안에서 이미 쓴다. `security/`는 경계 패키지이므로 `security/application.py`가 닿는다. **writer 모듈이 늘지 않는다**(안티목표 7).
- **`administration/member_state.py`는 얇은 CLI 포장으로 남는다.** 공개 함수 이름·반환값·`ValueError`/`CliError` 문구를 그대로 두어 `limn member`와 그 시험이 움직이지 않는다. `administration`에서 새로 export 할 것은 없다.
- **`store_lock`은 중첩되지 않는다.** 호출마다 새 fd를 열고 `flock(LOCK_EX)`을 건다([`platform/files.py:73`](../../../src/limn/platform/files.py)) — 같은 프로세스에서 두 번째 획득이 막힌다(검토자가 재현). 그래서 전환을 기존 `member_*` 함수들을 이어 붙여 만들 수 없다. 모양은 둘로 나눈다:
  - **잠금 없는 순수 편집** — rows를 받아 제자리에서 고치고 `(결과, 감사 줄들)`을 돌려주는 연산. 전환과 단건 변경이 같은 것을 쓴다.
  - **잠금을 한 번 잡는 트랜잭션** — 읽고, 위 연산을 돌리고, `atomic_write`하고, 같은 잠금 안에서 감사 줄을 적는다. 기존 `_people_update`가 하는 일과 같은 모양이다.
- **쓰는 순서는 `people.json` 먼저, `access.json` 마지막이다.** 뒤가 실패하면 "멤버는 바뀌었지만 아직 관리 안 함"이 남는데, 그 상태는 **오늘의 `--allow` 판정이 그대로 도는 상태**라 들어오는 사람이 늘지 않는다(제거는 효력이 없고 추가도 효력이 없다). 반대 순서면 "관리 중인데 멤버 목록이 어긋난 상태"가 되어 잠금이나 넓힘이 된다. 실패하면 응답이 무엇이 바뀌었고 무엇이 안 바뀌었는지 말하고, 소유자가 다시 누르면 된다(연산은 목표 상태를 적으므로 멱등이다).
- **`require_authority`는 HTTP 싱크에서 부른다 — 공유 연산 안이 아니다.** `PostAuthority`는 `_AUTHORITY_KEY`가 `access.py` 사설이라 **HTTP 경계에서만** 발급된다(`_authorize_post`는 `RequestGuards.authorize_post`에서만 불린다). 공유 연산 안에서 검사하면 CLI가 만족시킬 수 없어 §내가 정한 것 7("CLI는 그대로 남는다")과 부딪힌다. `/api/clear`와 같은 모양이다 — HTTP 문은 권한 값으로, CLI 문은 OS 파일 권한으로 지킨다(오늘과 같다). ADR-0055에 이 비대칭을 적는다.
- **`authority_scope()`에 분기를 더해야 한다.** 지금 [`server.py:324`](../../../src/limn/server.py)는 `rebuild`·`hold`·`revision-build`만 가르고 **나머지는 핀 저장소 범위로 떨어진다** — 분기를 더하지 않으면 멤버 작업이 조용히 핀 저장소를 상대로 권한을 받는다. people 저장소 범위를 새로 만든다(소유자는 프로세스의 people 잠금, 이름 공간은 상태 디렉터리).
- **적합 검사의 제약** — [`tools/check_fitness.py`](../../../tools/check_fitness.py)의 기준선은 **내려가기만** 한다. `security/people.py`의 `isinstance` 기준선은 11이므로 **새 코드에 `isinstance`를 쓰지 않는다.** 새 모듈을 만들 때는 basename이 역할 낱말을 담아야 하고(`*_store.py` → `persistence`, io 허용·`isinstance` 금지) 그 역할의 규칙을 처음부터 지켜야 한다 — 새 파일의 위반 수는 0이어야 한다. `tools/strict_ratchet.py`도 같은 방향이다.
- **`#access`의 배경 클릭은 두 패턴 중 하나를 고른다.** `#trash`는 [`layout/flow.ts`](../../../src/limn/viewer/js/layout/flow.ts)의 공용 배경 클릭 목록에 **없고** 자기 처리기를 따로 갖는다(`pins/view-cards.ts:551`). 뒤로가기 레이어(`flow-back.ts:32`·`:84`)에는 들어 있다. 새 패널은 공용 목록에 넣는 쪽을 고르고, 뒤로가기 셀렉터 두 곳에도 더한다.

## 내가 정한 것 (소유자가 뒤집을 수 있다)

1. **최초 `owner`는 CLI만 만든다** — **`limn member add <인스턴스> <로그인> --role owner`**. `--auth tailscale`에서 헤더로 들어온 사람은 전부 `editor`이므로(`access.py:889`) 지금 돌고 있는 인스턴스에는 owner가 아무도 없을 수 있다. 화면이 최초 owner를 만들 수 있으면 테일넷에 닿는 누구나 권한을 올린다. `--owner <로그인>` 같은 인자도 두지 않는다 — 그러면 다시 프로세스 인자가 정본이 된다.
   - **`limn member role`이 아니다.** `member_set_role`은 `people.json`이 없거나 그 로그인의 줄이 없으면 `None`을 돌려주고([`member_state.py:99`](../../../src/limn/administration/member_state.py)) CLI가 `"... is not in ... (add it with \`limn member add\`)"`로 거부한다([`members.py:62`](../../../src/limn/administration/members.py)). 갓 만든 인스턴스나 아직 한 번도 들어온 적 없는 공저자가 바로 그 경우다 — 즉 이 한 줄이 **필요한 상황에서 정확히 실패**한다. `member_add`는 `--role owner`를 받는다(`is_role("owner")`가 참, [`member_state.py:58`](../../../src/limn/administration/member_state.py)).
   - 이미 줄이 있는 사람을 올릴 때는 `limn member role <인스턴스> <로그인> owner`가 맞다. 운영 문서에 두 경우를 함께 적는다.
2. **상태는 `people.json`이 아니라 새 파일에** — §A의 이유(writer가 둘, `people_text()`가 문서를 다시 짓는다).
3. **입장과 역할을 한 축으로** — §접근 셋째 표.
4. **`access.json`이 못 쓰는 파일이면 fail closed** — 헤더로 들어온 사람 전원 `403`. 보안 파일의 house rule을 따른다.
5. **목록 타임아웃 1초, 백그라운드 스레드 없음** — 멈춤 신호 "새 백그라운드 스레드"를 피한다.
6. **맥 App Store 샌드박스판은 지원하지 않는다** — 전송 경로가 또 다르고(`lsof` 추적) 실측할 기기가 없다. "목록 없음 + 이유"로 떨어진다.
7. **CLI는 그대로 남는다** — `limn member`는 화면과 같은 파일을 같은 잠금으로 고친다. 둘 중 하나를 없애지 않는다.
8. **역할 분절은 `viewer`/`editor` 둘만** — `agent`는 토큰 주체의 역할이라 사람에게 화면에서 주지 않는다. `role_not_settable`은 **HTTP 문의 규칙**이고 CLI는 네 역할을 그대로 받는다(그러지 않으면 §1의 부트스트랩이 막힌다).
9. **`locks_out_owner`는 전환에만 있는 규칙** — HTTP 문에서만 본다. **이 누름이 만드는 상태가 요청한 소유자를 들여보내지 않으면 거부한다** — 목록에 있는지가 아니라, 그 상태의 `people.json` 줄(보존되는 `owner`·`agent` 줄 + 본문의 목록)과 그 실행의 인자를 입장 판정과 **같은 함수**에 넣어 묻는다. 켜는 누름과 끄는 누름 모두에 걸린다. 파일과 무관하게 들어오는 주체(토큰, `--auth local`의 본인)는 면제다 — 그들의 줄을 빼도 쫓겨나지 않으므로, 면제를 로그인 모양으로 판단하지 않고 HTTP 문에서 주체를 보고 정한다. 모두가 들어오는 인스턴스(깃발도 `--allow`도 `--members-only`도 없음)는 아무도 내쫓을 수 없으므로 거부하지 않는다.
10. **전환 기본 체크 상태는 "지금 그대로"** — §C. 두 대안이 각각 안티목표 1·3에 걸려 도출된 값이다.

## 물을 것 (모두 답해졌다)

**마지막 `owner` 보호는 두 문 모두를 묶는다 — 소유자 결정, 2026-11-22.** 지금 `limn member remove <유일한 owner>`는 성공한다(`member_state.member_remove`에 역할 검사가 없다). 안티목표 3("소유자가 자기를 잠근다")은 *상태*에 대한 말이므로, 규칙을 §G의 **잠금 없는 공유 편집 연산**에 넣어 화면과 CLI가 같이 지키게 한다.

- 마지막 `owner`를 빼거나 내리는 일은 어느 문으로도 안 된다. HTTP는 `409 last_owner`, CLI는 `limn: ...` 한 줄.
- **`limn member remove`의 동작이 바뀐다.** 전용 CLI 시험을 더하고 CHANGELOG에 **Changed** 항목으로 적는다.
- 소유자를 **교체**하는 순서가 뒤집힌다 — 새 소유자를 `limn member add <인스턴스> <로그인> --role owner`로 먼저 더한 뒤 옛 소유자를 지운다. 이 한 줄을 [operations.md](../../handbook/operations.md)와 [instances.md](../../handbook/instances.md)에 적는다.
- 그래도 `people.json`을 손으로 고치는 길은 막지 않는다(파일은 소유자의 것이다). 그 경우의 복구 절차는 기존 "쓸 수 없는 `people.json`" 절과 같은 자리에 둔다.

## 검증

- `security/tests/test_access.py` — 전환 전/후 `admit()` 판정표. **전환 전 판정이 바뀌지 않는다**를 `--allow`·`--members-only`·둘 다 없음 세 구성에서 못박는다. 전환된 인스턴스에서 빈 `people.json`이 아무도 들이지 않는 것, `--allow`가 무시되는 것.
- `security/tests/test_access_paths.py` `RoleMatrix` — 새 경로 다섯을 owner·editor·viewer·agent·토큰·로컬 소유자 × 각각으로. `GET /api/access`가 owner 아닌 전원에게 `403`.
- `security/tests/test_authority.py` — 새 작업의 권한 발급, 등록 안 된 경로의 기본 거부, 다른 작업의 권한으로 멤버를 고치려는 시도의 거부.
- 새 `security/tests/test_access_managed.py` — `access.json` 없음/정상/못 쓰는 파일 세 상태, 전환의 원자성(`people.json` 먼저·`access.json` 마지막, 뒤가 실패하면 멤버 목록만 서고 플래그는 그대로인 것 — `--members-only` 에서는 그 줄이 곧 입장이라 그 절반이 입장을 넓히므로, 서버가 그 상태를 `500 flag_not_written` 으로 알리는 것까지), 전환의 멱등성, 자기 잠금 거부(`locks_out_owner`), `owner`·`agent` 줄이 본문에서 빠져도 보존되는 것, 감사 줄의 순서.
- `administration/tests/test_cli.py` — **`limn member remove`·`role`이 마지막 `owner`를 거부한다**(소유자 결정으로 바뀐 동작). 새 소유자를 먼저 더하면 옛 소유자를 지울 수 있다는 것도 같이 못박는다. 화면과 CLI가 같은 공유 연산을 쓰는지는 두 문의 거부가 같은 조건에서 나는 것으로 확인한다.
- 새 `platform/tests/test_tailnet.py` — `User` 맵 투영(부분 목록 표시, 멤버·무효 로그인 제외), 소켓 없음·타임아웃·`BackendState` 비정상·비-JSON 응답에서 예외를 올리지 않고 이유를 돌려주는 것. **가짜 유닉스 소켓 서버**로 전송까지 돈다(실기기 테일넷 없이).
- `web/tests/test_errors.py` — 새 `reason` 코드마다 `ui_en.json` 문장이 있고, 내지 않는 코드의 문장은 없음.
- `tests/contracts/` — 기존 필드·경로의 스냅샷 불변.
- 뷰어: 새 `viewer/tests/test_viewer_access.py` — owner가 아니면 진입점과 패널 컨트롤이 **문서에 없음**(숨김이 아니라 없음), 네 기기군 레이아웃, 키보드 Tab 트랩과 Esc, 배경 클릭.
- `AGENTS.md` §검증의 명령 블록 전부. `uv run python tools/page_elements.py --check`·`npm run boundaries`·`npm run build:check` 포함.
- **네 기기군 PoC**를 `main` 전에 소유자에게. 전환 화면·멤버 구획·목록 없음 상태 각각, 그리고 `#more`의 진입점 전후.

## 범위 밖

- 테일넷 **전체** 사용자 목록(Admin API), 초대 링크, OIDC·세션.
- 토큰 관리의 화면 이전.
- SSE·실시간 반영.
- `~/.config/limn/<이름>.env`의 자동 정리.
- 멤버 변경의 알림(이벤트·브라우저 알림).
- 다른 인스턴스의 접근을 한 화면에서 관리하는 일.

## 이 변경에서 함께 고칠 문서

`docs/adr/0054-*.md`(새, `제안`) · `docs/adr/index.md` · `docs/handbook/api.md` · `architecture.md` · `operations.md` · `viewer.md` · `instances.md` · `verification.md` · `index.md`(파일 지도) · `SECURITY.md` · `README.md`+`README.ko.md`(쌍) · `skill/SKILL.md:239`+`skill/SKILL.ko.md:239`(쌍) · `CHANGELOG.md`.
