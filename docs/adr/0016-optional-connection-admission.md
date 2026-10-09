# ADR-0016: 선택형 연결 입장 상한과 불확실한 worker 시작의 실패 종료

| | |
| --- | --- |
| **번호** | ADR-0016 |
| **제목** | 선택형 연결 입장 상한과 불확실한 worker 시작의 실패 종료 |
| **상태** | 승인됨 |
| **결정일** | 2026-10-10 |
| **결정자** | Limn 소유자 |
| **출처** | [승인 기록](https://github.com/dartworklabs/limn/issues/222#issuecomment-6085831493), [승인된 V2 설계](https://github.com/dartworklabs/limn/issues/222#issuecomment-6077481343), [spec](../superpowers/specs/2026-10-10-connection-admission.md) |

## 맥락

현재 HTTP 리스너는 연결마다 daemon 요청 스레드를 만들며 연결 입장 수를 제한하지 않는다. 연결은 신원을 알기 전에 생기고, 프록시 연결 하나에 여러 사람의 요청이 실릴 수 있어 사용자별 공정성 단위로 쓸 수 없다. 리스너별 선택형 상한은 이 자원 경계만 제한한다. 실제 운영 서버별 FD·스레드 한도와 합법적 동시 수요를 확인하지 않은 상태에서 기본 상한이나 운영 숫자를 정하지 않는다.

기존 전송은 `web/`, 인자·얼린 실행 설정은 `runtime/`, 조립·리스닝·종료 순서는 `server.py`가 소유한다. 그 책임과 표준 라이브러리만 쓰는 런타임을 유지한다. 새 상태 기계·동시성 경계라는 멈춤 신호와 안전성·가용성 trade-off를 이번 기록으로 남기며 기존 설계 축·역사 ADR을 대체하지 않는다.

소유자는 정확한 V2 설계와 구현을 승인했다. 이 ADR은 리뷰 가능한 새 기록이라 `제안`으로 시작하며 머지 시 상태만 `승인됨`으로 올린다. 그 문서 상태는 승인된 구현 범위를 철회하거나 다시 승인받아야 한다는 뜻이 아니다. 구현·검증·운영 활성화는 아직 완료되지 않았다. 이전 탐색 당시 formal Superpowers brainstorming은 사용할 수 없었으므로 실행한 것으로 기록하지 않는다.

## 결정

### D1. 생략하면 기존 동작인 명시적 선택

`limn serve --max-connections N`만 더한다. N은 양의 정수이며 잘못된 값은 리스닝 전에 거부한다. 생략하면 기존 무제한 입장과 thread 시작 실패 동작을 유지한다. 기본 숫자, manager 키·유닛 전개, 운영 활성화는 정하지 않는다.

### D2. HTTP 전송이 소켓 수명의 lease를 소유한다

각 리스너가 받아들인 소켓의 lease를 worker 생성·시작 전에 원자적으로 예약한다. pending·active·idle keep-alive를 모두 세고 물리적 소켓 정리가 확인된 뒤 정확히 한 번 반환한다. 리스너별 불투명 식별자와 재사용하지 않는 generation으로 오래된 정리가 새 연결을 해제하지 못하게 한다. 상한에 찬 새 소켓은 기다리거나 요청 스레드를 만들지 않고 바로 닫는다. 커널 backlog·거부 중인 소켓은 admitted 수 밖이라 전체 FD 상한은 아니다.

### D3. 거부는 HTTP 전의 transport close다

HTTP를 읽기 전에 EOF 또는 reset을 낸다. HTTP 503/429·JSON reason·화면 문구를 만들지 않는다. 프록시의 오류 변환·재시도는 Limn의 계약이 아니다. 받아들인 요청은 매번 기존 신원·역할·본문·오류·30초 소켓 timeout 계약을 지킨다.

### D4. 실제 Thread.start 호출 이후의 모든 시작 예외는 실패 종료한다

실제 `Thread.start()` 호출 이전임을 소유 경계에서 증명한 실패만 소켓을 물리적으로 정리하고 lease를 한 번 반환한 뒤 입장을 재개한다. 정리를 확인하지 못하면 실패 종료한다. 실제 호출 이후 예외는 종류·문구·thread 이벤트와 무관하게 입장을 막고 listener를 닫고 기존 runtime 정리 뒤 프로세스를 0이 아닌 값으로 끝낸다. pending worker가 handler를 만들기 전에 막으며 이미 claimed인 worker는 자기 finally·정리 또는 프로세스 종료까지 lease를 소유한다. parent가 소켓을 닫아도 불확실한 lease를 조기 반환하지 않는다.

CPython의 native launch와 bootstrap 확인 사이에 예외가 발생할 수 있으므로 `Exception`이나 unset `_started`는 no-launch 증거가 아니다. stdlib가 ordinary Exception을 잡아 계속 받는 경로도 실패 종료 근거가 될 수 없다. fatal 경로의 close·fallback·logging·coordination 오류는 최초 시작 오류를 원인으로 보존하며 계속 입장하거나 정상 종료하게 만들지 않는다.

### D5. 기존 정리 비용을 수용하고 활성화는 따로 결정한다

현재 runtime 정리는 stop event를 세우고 등록된 watcher를 각각 최대 5초씩 한 번 join한다. 페이지 렌더링의 기존 `ThreadPoolExecutor`는 interpreter exit에서 executor thread를 기다릴 수 있으므로 이 join 시간은 프로세스 전체 종료 상한이 아니다. 전체 종료 SLA·새 graceful drain·self-restart·자식 프로세스 정책을 더하지 않는다. 다른 in-flight 요청·daemon 빌드·비교 작업이 종료에 끊길 수 있는 비용을 수용한다. 모든 핀 파생 파일의 동시 일관성, 중단된 작업 완료, 모든 subprocess descendant 정리를 새로 보장하지 않는다. 활성화 전 host의 FD/thread·메모리 여유·수요·proxy 동작·rollback 예산은 운영자가 따로 확인한다.

## Trade-off

**장점:** 소유권과 admitted 수를 정확히 묶으며 불확실한 native worker가 존재할 수 있는 상태에서 새 입장을 재개하지 않는다. 기본 비활성은 기존 설치와 운영을 보존한다. 저장·권한·HTTP 오류 계약과 의존성을 늘리지 않는다.

**단점·포기한 것:** 활성화하지 않으면 보호하지 않는다. 사용자의 공정성과 요청 비용은 제한하지 않는다. transport close는 클라이언트·proxy에 HTTP 오류보다 설명이 부족하다. 희귀한 시작 오류에서 해당 프로세스를 종료하므로 다른 요청·작업의 가용성을 포기한다. 실제 OS close 실패·자원 고갈·임의 비동기 신호 전체에 대한 보장은 검증 범위 밖이다.

## 대안

| 대안 | 선택하지 않은 이유 |
| --- | --- |
| limiter 전체 유보 | 새 전송 거부는 피하지만 연결·요청 worker가 계속 무제한이다. 소유자는 선택형 제어 구현을 승인했다 |
| 의무 기본 cap·사용자별/IP quota | 운영 숫자 근거가 없고 프록시 연결과 신원이 일대일이 아니며 승인 범위를 넘는다 |
| HTTP 503/429·대기 queue | 거부를 알리기 위해 HTTP 처리 자원을 쓰거나 새 대기 정책을 만들며 승인된 HTTP 전 경계와 다르다 |
| start 예외를 no-launch로 간주하고 lease 반환 | native 실행이 이미 존재할 수 있어 이중 소유·조기 반환·상한 위반 가능성이 있다 |
| 불확실한 lease만 보유하고 계속 받기 | orphan lease와 알 수 없는 worker가 남은 상태의 입장을 허용하며 V2 실패 종료 계약을 어긴다 |

## 결과

- pure 입장·수명 판단과 소켓·thread adapter는 `web/` 안에 둔다. runtime 설정은 수치만 넘기고 기능 슬라이스를 import하지 않는다.
- 구현과 같은 변경에서 architecture·operations·api·verification·code-style-roadmap에 현재 결론·이유·비용·한계를 완결해서 적고 D1–D5 출처를 붙인다. 새 topic이나 정본 권위는 만들지 않는다.
- 영어·한국어 README를 함께 고친다. skill 문서의 동작 안내가 바뀌면 두 언어를 함께 고친다. UI 자산은 범위 밖이다.
- TCP·process·physical cleanup 관찰과 pure 생성 시퀀스로 검증하고 실제 red 또는 mutation 실패를 보존한다. 기존 열 개 검증 영역과 CI 환경은 유지한다.
- 이 기록의 승인은 구현 완료 증거가 아니다. [계획](../superpowers/plans/2026-10-10-connection-admission.md)의 검수와 현재 코드 관찰 뒤 Handbook을 실제 상태에 맞춘다.
