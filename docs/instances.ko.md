[English](instances.md) | 한국어

# 인스턴스 — 원고마다 Limn 하나

`limn serve` 는 서버 하나를 앞에서 띄운다. 몇 주씩 다루는 원고는 **인스턴스**로 띄운다. 인스턴스는
systemd 사용자 유닛 `limn@<이름>` 하나이고, 포트·상태 폴더·journal 이 인스턴스마다 따로다.
논문마다 저장소가 따로이고 동시에 작업하는 일이 잦아 원고마다 인스턴스를 하나씩 둔다. 설치된 `limn`
패키지 하나를 모든 인스턴스가 함께 쓴다.

| 무엇 | 어디 |
|---|---|
| 유닛 템플릿 | `limn add`·`limn start` 가 패키지의 템플릿을 채워 `~/.config/systemd/user/limn@.service` 에 쓴다(인스턴스 이름 = 논문 슬러그) |
| 인스턴스 설정 | `~/.config/limn/<이름>.env` (`LIMN_CONFIG_DIR`) |
| CLI | `limn` (`uv tool install` 로 설치) |
| 앱 | 설치된 `limn` 패키지 — 올리기·되돌리기는 `limn update` |
| 상태(인스턴스별) | 설정의 `STATE_DIR`, 기본 `~/.local/share/limn/<이름>` — 핀·`build/`·`build.log`·`pins.md` |
| 로그(인스턴스별) | `journalctl --user -u limn@<이름>` · `<STATE_DIR>/build.log` |

## 설정 키

`KEY=VALUE` 한 줄씩. systemd `EnvironmentFile` 형식이고 `limn` 이 직접 읽는다. **셸로 source 하지
않으므로** 값에 셸 문법을 쓰지 않는다. 따옴표·역슬래시·`$`·백틱·줄바꿈은 `limn add` 가 거부한다.

| 키 | 뜻 |
|---|---|
| `MANUSCRIPT` | 원고 폴더(LaTeX 소스 루트, 절대경로) |
| `MAIN` | 최상위 `.tex` 파일 이름(원고 폴더 맨 위) |
| `PORT` / `TS_PORT` | 로컬 `127.0.0.1` 포트와 테일넷 `https` 포트. **실행 때 자동으로 고르지 않는다** — 알린 주소가 바뀌면 안 된다 |
| `STATE_DIR` | 상태 폴더. 다른 인스턴스와 겹치면 `limn add` 가 거부한다 |
| `GIT_PULL` | `1` 이면 재빌드마다 원고 체크아웃을 `--ff-only` 로 당긴다 |
| `LABEL` / `ACCENT` | 뷰어 이름표와 강조색(`#rrggbb`) |
| `EXTRA_ARGS` | 그 밖의 서버 인자(공백으로 나눔). `limn add` 기본값은 `--no-build` — 산출물이 없으면 서버가 어차피 빌드한다 |
| `DOCS` | 여러 문서(본문·답변서·보기 전용 PDF 등)를 탭으로 전환한다. `MAIN` 과 함께 쓰지 않는다. [여러 문서](#여러-문서-docs) 참고 |

## 새 원고 추가

```bash
# 1. 추가 — 포트 배정·설정 작성·유닛 enable·start·tailscale serve·AGENTS.md 조각 출력
limn add paper2 --manuscript ~/papers/paper2 --git-pull --label Paper2
# 2. 출력된 조각을 그 논문 저장소의 AGENTS.md 에 붙인다(다시 보기: limn snippet paper2)
```

`--main`·`--doc` 을 생략하면 문서를 자동 탐지하고(다음 절), 표준 구조가 아니면 원고 폴더 맨 위에서
`\documentclass` 가 있는 `.tex` 하나를 찾는다. 두 개 이상이면 추측하지 않고 멈춘다. `--label` 을
생략하면 원고 저장소 이름(`origin` URL 끝)을 쓴다. 로컬에서만 띄우려면 `--no-serve`.

설정을 다른 저장소(예: dotfiles)에서 관리한다면 `LIMN_SOURCE_DIR` 로 그 폴더를 가리킨다. 그러면
`limn add` 가 설정 원본을 거기에 쓰고 `~/.config/limn/` 에 링크를 건다.

## 기본 문서 탭 자동 탐지

`--doc`·`--main` 없이, 원고 폴더가 표준 논문 저장소 구조면 탭을 자동으로 만든다.

| 탭 | 키 | 경로 | 포함 조건 |
|---|---|---|---|
| 본문 | `ms` | `manuscript/<최신 라운드>/<본문>.tex` | 항상(구조가 맞으면). 라운드는 맨 앞 숫자가 가장 큰 폴더(`1st`·`2nd`…, 숫자로 시작하지 않는 폴더는 무시). 라운드 폴더에 `\documentclass` 후보가 여럿이면 가장 최근에 커밋(없으면 수정)된 파일, 같으면 오류로 멈춘다 |
| 답변서 | `rr` | `submission/review_response/review_response.tex` | revision 단계이고 파일이 있을 때 |
| 하이라이트 | `hl` | `submission/highlights/highlights.tex` | 파일이 있을 때 |
| 커버레터 | `cl` | `submission/cover_letter/cover_letter.tex` | 파일이 있을 때 |

순서는 고정(`ms`→`rr`→`hl`→`cl`). 단계는 `--stage auto|initial|revision`(기본 `auto` =
`<원고 폴더>/reviews/` 가 있으면 revision).

```bash
limn doc suggest --manuscript ~/papers/paper2      # 읽기 전용 — 자동 탐지될 DOCS 미리 보기
limn add paper2 --manuscript ~/papers/paper2        # 같은 결과를 설정에 쓴다
```

## 여러 문서 (`DOCS=`)

```bash
limn add paper2 --manuscript ~/papers/paper2 --label Paper2 \
  --doc 'ms=본문:manuscript::2nd/main.tex' \
  --doc 'rr=답변서:submission/review_response/review_response.tex' \
  --doc 'sub=제출본 PDF:submission/submission_ready/manuscript.pdf'

limn doc add paper2 --doc 'cl=커버레터:submission/cover_letter/cover_letter.tex' --restart
limn doc list paper2
limn doc remove paper2 cl
```

| 항목 | 규칙 |
| --- | --- |
| `--doc` 형식 | `<키>=<표시 이름>:<경로>` — 첫 `=` 앞이 키, 다음 `:` 까지가 이름, 나머지가 경로 |
| 키 | `[a-z0-9-]{1,24}`, 중복 금지. 한 번 정하면 바꾸지 않는다(핀에 남는다) |
| 경로 | `--manuscript` 기준 상대(권장) 또는 절대. 반드시 `--manuscript` 안 |
| `x/main.tex` | LaTeX, 빌드 루트 `x/` |
| `root::sub/main.tex` | LaTeX, 빌드 루트 `root/`(복사 범위를 넓힌다), 메인 `root/sub/main.tex` |
| `x/file.pdf` | 보기 전용(재빌드 없음, 쪽·영역 핀) |
| 개수 | 12개까지 |
| `MAIN` 과의 관계 | 함께 쓰지 않는다 — `add`·`run` 이 거부한다 |
| 설정 파일 형식 | `DOCS="<키1>=<이름1>:<경로1>;<키2>=…"` (`;` 로 나눔, 이름에 공백이 있을 수 있어 따옴표로 싼다) |

단일 문서(`MAIN`) 인스턴스에 `limn doc add` 를 하면 본문이 첫 항목 `main=<이름>:<MAIN>` 으로 옮겨진다.
키 `main` 은 옛 상태 배치를 그대로 쓰므로 빌드 이력과 옛 핀이 이어진다. 서버 쪽 계약은
[operations.ko.md](operations.ko.md) 의 여러 문서 절.

## 동시 실행

인스턴스마다 포트·상태 폴더·빌드 폴더(`<STATE_DIR>/build`)·journal 이 따로다. 서버는 원고를
`<STATE_DIR>/build` 로 복사해 거기서 빌드하므로 동시에 재빌드해도 서로 건드리지 않는다. 두 인스턴스가
같은 원고 폴더를 보면 `limn add` 가 경고한다(`--git-pull` 이 겹친다).

## 업데이트와 되돌리기

```bash
limn update --dry-run          # 무엇을 설치하고 재시작할지 보기만
limn update                    # 가장 최근 v* 태그를 설치하고 켜진 인스턴스를 재시작
limn update --ref v0.1.1       # 특정 태그·브랜치
limn update --from ~/src/limn  # 로컬 체크아웃(개발용)
```

`limn update` 는 `uv tool install --force git+ssh://git@github.com/dartworklabs/limn@<ref>` 를 실행하고
(`LIMN_REPO` 로 원본을 바꾼다), 유닛 템플릿을 다시 쓰고, 켜진 `limn@*` 인스턴스를 모두 재시작한 뒤 HTTP
200 을 기다린다. 설치하는 동안 도는 서버는 그대로이고, 재시작할 때 새 판으로 바뀐다. **상태 폴더는 건드리지
않는다.** 되돌리기는 이전 태그를 다시 설치하는 것이다: `limn update --ref v<이전 판>` (업데이트할 때마다
그 명령을 찍어 준다). 따로 두는 앱 사본은 더 없다 — 설치된 태그가 곧 판이다.

## 끄기·제거

- `limn stop <이름>` — 유닛을 끄고 비활성화한다. 설정·포트·serve 항목은 남는다. `limn start <이름>` 으로 다시 켠다.
- `limn remove <이름>` — 유닛 중지·비활성, tailscale serve 해제(**그 포트가 이 인스턴스의 로컬 포트를 가리킬 때만**), 설정 삭제(= 포트 예약 해제). **상태 폴더는 지우지 않고** 경로만 알린다.

## 포트

- 설정 파일이 곧 예약이다. 다른 인스턴스 설정이 쓰는 포트, 어느 주소에서든 LISTEN 중인 포트, `tailscale serve` 가 이미 쓰는 포트는 `limn add` 가 거부한다(명시해도 같다).
- 자동 배정은 테일넷 `18005–18099`(`LIMN_TS_MIN`/`LIMN_TS_MAX`)에서 첫 빈 포트를 고르고 로컬 포트는 `+100` 을 짝짓는다(18004 ↔ 18104).
- 기기 공용 포트 장부(선택): `~/.config/served/reserved-ports.txt`(`LIMN_LEDGER`)가 있으면 그 `<포트> <주인>` 줄도 피한다. `LIMN_LEDGER_GEN=<스크립트>`(`<스크립트> <유닛 폴더> <설정 폴더>` 로 불리고 `<포트> <주인>` 줄을 찍는다)를 주면 `add`·`remove` 가 장부를 다시 만든다. 생성기가 없으면 읽기만 한다.

## 보안 규칙

- 서버는 `127.0.0.1` 에만 바인드한다(코드에 박혀 있다). 테일넷 노출은 `tailscale serve --bg --https=<TS_PORT> http://127.0.0.1:<PORT>` 뿐이다.
- **funnel 은 쓰지 않는다.** 미공개 원고다. `add`·`start` 는 serve 설정을 되읽어 그 포트가 funnel 이면 멈춘다.
- **sudo 를 부르지 않는다.** tailscale operator 설정도 바꾸지 않는다. 권한이 없어 serve 가 안 걸리면 오류로 멈춘다.
- 남의 serve 항목을 덮거나 내리지 않는다. `serve reset` 은 쓰지 않는다(기기 전체 설정이다).

## 환경 변수

| 변수 | 기본값 | 뜻 |
|---|---|---|
| `LIMN_CONFIG_DIR` | `$XDG_CONFIG_HOME/limn` | 인스턴스 설정 |
| `LIMN_DATA_ROOT` | `$XDG_DATA_HOME/limn` | 상태 폴더 기본 위치 |
| `LIMN_SOURCE_DIR` | = 설정 폴더 | `add` 가 설정 원본을 쓰는 곳(설정 폴더에 링크) |
| `LIMN_USER_UNIT_DIR` | `$XDG_CONFIG_HOME/systemd/user` | 유닛 템플릿을 쓰는 곳 |
| `LIMN_UNIT_PATH` | `pdflatex` 폴더 + `/usr/local/bin:/usr/bin:/bin` | 유닛 안의 `PATH` |
| `LIMN_LEDGER`, `LIMN_LEDGER_GEN` | [포트](#포트) 참고 | 포트 장부(선택) |
| `LIMN_TS_MIN`, `LIMN_TS_MAX`, `LIMN_LOCAL_OFFSET` | `18005`, `18099`, `100` | 자동 배정 대역 |
| `LIMN_REPO`, `LIMN_UV` | `git+ssh://git@github.com/dartworklabs/limn`, `uv` | `limn update` 가 설치할 원본과 쓸 `uv` |
| `LIMN_WAIT` | `240` | 기동·재시작 뒤 HTTP 200 을 기다리는 초 |

예전 이름으로 설치해 쓰던 환경에서 옮겨 오는 경우는 [README](../README.ko.md#출처와-이전) 의 출처 절과
`limn migrate --help` 를 본다.
