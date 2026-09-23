# 원고 핀 뷰어 — 논문별 인스턴스

writing-agent-playbook 스킬 `manuscript-pin-picker` 의 서버(`pin_server.py`)를 **논문마다 따로** 띄운다.
논문마다 저장소가 따로이고, 두 논문을 동시에 작업하면 뷰어도 동시에 따로 돌아야 한다.

| 무엇 | 어디 |
|---|---|
| 템플릿 유닛 | `machines/example-host/systemd/pin-viewer@.service` → `~/.config/systemd/user/` (인스턴스 이름 = 논문 슬러그) |
| 인스턴스 설정 (원본) | `machines/example-host/pin-viewer/<이름>.env` → `~/.config/pin-viewer/<이름>.env` 심링크 |
| 관리 CLI | `bin/pin-viewer.sh` → `~/.local/bin/pin-viewer` |
| 앱 사본 (공유) | `~/.local/share/pin-viewer/app/{pin_server.py,vendor/pdfjs/,SOURCE}` — 직전 판은 `app.prev` |
| 상태 (인스턴스별) | 설정의 `STATE_DIR`, 기본 `~/.local/share/pin-viewer/<이름>` — 핀·`build/`·`build.log`·`pins.md` |
| 로그 (인스턴스별) | `journalctl --user -u pin-viewer@<이름>` · `<STATE_DIR>/build.log` |

앱을 플러그인 캐시에서 바로 돌리지 않는다. 캐시 경로에 버전 해시가 들어 있어 플러그인을 업데이트할
때마다 바뀌기 때문이다. `pin-viewer update` 가 **설치된 판**(`~/.claude/plugins/installed_plugins.json` 의
`installPath`)을 고정 위치로 복사한다. 캐시 폴더를 `ls | tail -1` 로 고르면 사전순으로 아무 옛 판이나
잡는다(실측 2026-09-23: 설치본 `a8e83e9b60af` 대신 `e0023cdef0c9`).

## 설정 키

`KEY=VALUE` 한 줄씩 쓴다. systemd `EnvironmentFile` 과 `pin-viewer` 가 같은 파일을 읽는다. **셸로 source 하지 않으므로**
값에 셸 문법을 쓰지 않는다. 따옴표·역슬래시·`$`·백틱은 `add` 가 거부한다.

| 키 | 뜻 |
|---|---|
| `MANUSCRIPT` | 원고 폴더(LaTeX 소스 루트, 절대경로) |
| `MAIN` | 최상위 `.tex` 파일 이름(원고 폴더 맨 위) |
| `PORT` / `TS_PORT` | 로컬 `127.0.0.1` 포트와 테일넷 `https` 포트. **자동 선택에 맡기지 않는다**. 광고한 주소가 바뀌면 안 된다 |
| `STATE_DIR` | 상태 폴더. 인스턴스끼리 겹치면 `add` 가 거부한다 |
| `GIT_PULL` | `1` 이면 재빌드마다 원고 체크아웃을 `--ff-only` pull 한다 |
| `LABEL` / `ACCENT` | 뷰어 이름표와 강조색(`#rrggbb`). **앱 사본의 `--help` 에 그 인자가 있을 때만** 넘긴다. 옛 판에 넘기면 argparse 가 죽어 뷰어가 통째로 안 뜨므로, 그때는 journal 에 경고만 남긴다 |
| `EXTRA_ARGS` | 그 밖의 서버 인자(공백으로 나눔). `add` 기본값은 `--no-build`. 산출물이 없으면 서버가 어차피 빌드한다 |

## 새 논문 추가 — 3단계

```bash
# 1. 추가 — 포트 자동 배정·설정 작성·유닛 enable·start·tailscale serve·AGENTS.md 조각 출력
pin-viewer add paper2 --manuscript ~/Codes/paper2/manuscript --main main.tex --git-pull --label Paper2
# 2. 설정 원본을 dotfiles 브랜치에서 커밋 (add 가 경로를 알려 준다)
git -C ~/dotfiles add machines/example-host/pin-viewer/paper2.env
# 3. 출력된 조각을 그 논문 저장소 AGENTS.md 에 붙인다 (다시 보기: pin-viewer snippet paper2)
```

`--main` 을 생략하면 원고 폴더 맨 위에서 `\documentclass` 가 있는 `.tex` 를 찾는다. 두 개 이상이면 추측하지 않고 멈춘다.
`--label` 을 생략하면 원고 저장소 이름(`origin` URL 끝)을 쓴다. 로컬에서만 띄우려면 `--no-serve` 를 쓴다.

## 동시 실행

인스턴스마다 포트·상태 폴더·빌드 폴더(`<STATE_DIR>/build`)·journal 이 갈린다. 공유하는 것은 읽기 전용
앱 사본 하나다. 서버는 원고를 `<STATE_DIR>/build` 로 복사해 거기서 빌드하므로 두 뷰어가 동시에 재빌드해도
서로의 산출물을 건드리지 않는다. 같은 원고 폴더를 두 인스턴스가 보면 `add` 가 경고한다(`--git-pull` 이 겹친다).

실측(2026-09-23, paper-a 원고 두 벌 `test-a`·`test-b`): 두 서버가 각자 포트에서 200, 동시에
`POST /api/rebuild?async=1` 을 보내 둘 다 `ok`(27.1s), `test-a` 에 만든 핀이 `test-b` 에 안 보였고
`pins.jsonl` 도 `test-a` 상태 폴더에만 생겼다.

## 업데이트

```bash
pin-viewer update            # 설치된 플러그인 판으로 앱 사본 교체 → 켜진 인스턴스 전부 재시작
pin-viewer update --from <skills/manuscript-pin-picker 폴더>   # 특정 판(브랜치 체크아웃 등)
```

새 판은 옆 폴더에 먼저 만든 뒤 이름만 바꿔 끼운다. `--help` 가 안 도는 판이나 `vendor/pdfjs` 가 빠진 판은 거부한다.
같은 판이면 재시작하지 않는다(`--force`). **상태 폴더는 건드리지 않는다.** 직전 판으로 되돌리려면
`cd ~/.local/share/pin-viewer && mv app app.bad && mv app.prev app && systemctl --user restart 'pin-viewer@*'`.

## 끄기·제거

- `pin-viewer stop <이름>` — 유닛만 끈다. 설정·포트 예약·serve 항목은 남는다. `pin-viewer start <이름>` 으로 다시 켠다.
- `pin-viewer remove <이름>` — 유닛 disable·stop, serve 해제(**그 포트가 이 인스턴스의 로컬 포트를 가리킬 때만**),
  설정 원본·홈 링크 삭제(= 포트 예약 해제), 장부 재생성. **상태 폴더는 지우지 않고 경로만 알린다.** 설정 원본 삭제는 dotfiles 에서 커밋한다.

## 포트 규칙

- 장부는 `~/.config/served/reserved-ports.txt` 다. `bin/served-reserved-ports.sh` 가 유닛 파일과 인스턴스 설정의
  `PORT=`·`TS_PORT=` 에서 만든다. 손으로 쓰지 않는다. 설정 파일을 쓰는 것이 곧 예약이고, `add`·`remove`·`install.sh` 가 장부를 다시 만든다.
- 자동 배정은 테일넷 `18005–18099` 에서 고르고, 로컬 포트는 거기에 `+100` 을 붙인다(18003↔18103, 18004↔18104 관례).
  장부에 있거나, 어느 주소에서든 LISTEN 중이거나(`ss`, 테일넷 IP 에만 붙은 것도 본다), `tailscale serve` 가 이미 쓰는 포트는 건너뛴다.
  포트를 명시해도 같은 검사를 통과해야 한다.

## 보안 규칙

- 서버는 `127.0.0.1` 에만 바인드한다(서버 코드에 박혀 있다). 테일넷 노출은 `tailscale serve --bg --https=<TS_PORT> http://127.0.0.1:<PORT>` 만 쓴다.
- **funnel 은 쓰지 않는다.** 미공개 원고다. `add`·`start` 는 serve 를 건 뒤 되읽어 그 포트가 funnel 이 아닌지 확인한다.
- **sudo 를 부르지 않는다.** tailscale operator 설정도 바꾸지 않는다. 이 호스트는 operator 가 `alice` 이라 serve 가 sudo 없이 걸린다. 안 걸리면 멈추고 오류를 보인다.
- 남의 serve 항목을 덮거나 내리지 않는다. `serve reset` 은 쓰지 않는다. 머신 단위 공유 상태라 다른 서빙까지 날아간다.

## paper-a 전환 (옛 전용 유닛 → `pin-viewer@paper-a`)

옛 `paper-a-pin-serve.service` 는 이 변경이 들어가도 그대로 돈다. 설정 `paper-a.env` 는 옛 유닛과 **같은 포트(18104/18004)와
같은 상태 폴더**(`~/.local/share/paper-a-pin`)를 쓰므로 핀·빌드·주소가 그대로 이어진다. 전환 순서는 다음과 같다.

```bash
git -C ~/dotfiles pull --ff-only && (cd ~/dotfiles && ./install.sh)   # CLI·템플릿·paper-a.env 링크 (인스턴스는 안 켠다)
pin-viewer update --no-restart && cat ~/.local/share/pin-viewer/app/SOURCE   # 앱 사본 설치
sed -n 6p ~/.local/share/paper-a-pin/pins.md                        # 전환 전 핀 수 기록(디스크, 서버를 찌르지 않는다)
systemctl --user disable --now paper-a-pin-serve.service                # 옛 유닛 중지·비활성
ss -ltnH 'sport = :18104'                                                   # 비었는지 확인
pin-viewer start paper-a                                                      # enable·start, 18004 serve 는 "이미 있음"
pin-viewer status paper-a                                                     # active/enabled, 로컬 200
curl -s -o /dev/null -w '%{http_code}\n' https://host.tail0000.ts.net:18004/   # 테일넷 200
sed -n 6p ~/.local/share/paper-a-pin/pins.md                        # 핀 수가 전환 전과 같은지(새 서버가 기동 때 다시 그린다)
```

되돌리기: `systemctl --user disable --now pin-viewer@paper-a && systemctl --user enable --now paper-a-pin-serve.service`.

전환 뒤 후속 PR 에서 `machines/example-host/systemd/paper-a-pin-serve.service`, `install.sh` 의 `_serve_units` 한 줄과
그 옆 전환 가드, 홈의 `~/.config/systemd/user/paper-a-pin-serve.service` 링크를 지운다. 가드가 있는 동안에는
`install.sh` 를 다시 돌려도 `pin-viewer@paper-a` 이 enabled 이면 옛 유닛을 되살리지 않는다. 상태 폴더 안의 옛
`pin_server.py`·`vendor/` 사본은 더는 쓰이지 않는다. 핀 파일과 섞여 있으므로 폴더째 지우지 않는다.
