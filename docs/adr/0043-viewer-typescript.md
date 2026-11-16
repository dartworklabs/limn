# ADR-0043: 뷰어 모듈을 TypeScript로 쓰고, 빌드가 타입만 걷어 낸다

| | |
| --- | --- |
| **번호** | ADR-0043 |
| **제목** | 뷰어 모듈을 TypeScript로 쓰고, 빌드가 타입만 걷어 낸다 |
| **상태** | 제안 |
| **결정일** | 2026-11-16 |
| **결정자** | Limn 소유자가 작업 지시로 정함(원본의 언어, 지울 수 있는 문법, 타입 검사와 빌드의 분리, 검사의 수준). 타입을 걷는 도구와 주석 처리는 지시가 이 변경에 맡겼다 |
| **출처** | 이 변경의 변환 도구가 센 값, 지은 파일의 정규형 비교(아래 결과), 전체 검사 |
| **부분 대체** | [ADR-0042](0042-viewer-es-modules.md) D7의 "JS 원본에 `checkJs`, 타입은 JSDoc" 구절과 §대안의 "`.ts` 원본" 기각. D2의 빌드는 모듈 글에서 `import`·`export` 문에 더해 타입을 걷어 낸다. ADR-0042의 나머지(ES 모듈, Rollup, 커밋한 한 파일, 실행 순서, 페이지 정책, 경계 어휘)는 그대로다 |

## 맥락

뷰어 모듈 57개는 JavaScript였고 타입은 JSDoc 주석이었다. `@param` 1,498개, `@type` 959개(그중 824개는 `/** @type {T} */ (x)` 꼴의 캐스트), `@returns` 383개, `@template` 52개, `@typedef` 27개다. TypeScript가 `checkJs`로 검사했지만 함수 머리는 주석과 코드로 나뉘어 읽혔고(`/** @param {VerdictChoice} c @param {number} page @param {string} [how] */` 다음 줄의 `function pvPress(c, page, how)`), 캐스트는 괄호와 주석에 묻혔으며, JSDoc만의 문법(`[name]`, `T=`, `...T`)이 섞였다.

[ADR-0042](0042-viewer-es-modules.md)는 `.ts` 원본을 "지은 파일이 원본과 글이 달라지고 변환 단계가 하나 는다"는 이유로 기각했다. 그 뒤로 빌드가 이미 있다. 설치와 배포는 커밋한 지은 파일만 읽으므로, 타입을 걷는 단계가 하나 늘어도 인스턴스 기계에는 아무것도 늘지 않는다.

## 결정

| | | |
| --- | --- | --- |
| D1 | **뷰어 모듈은 TypeScript다.** 57개 모듈은 같은 자리, 같은 이름의 `js/*.ts`이고 타입은 코드에 쓴다. JSDoc 주석에는 설명만 남는다(`limn/no-jsdoc-type`). 모듈 사이 import는 `./core.ts`처럼 파일 이름 그대로 쓴다. 번들 밖에서 제 경로로 내보내는 서비스 워커 `sw.js`와 Markdown 파싱 worker `md-parse.mjs`는 JavaScript로 둔다. 바꾸면 파일마다 지은 산출물과 그 검사가 따로 필요하다 | 제안 |
| D2 | **지울 수 있는 문법만 쓴다.** `erasableSyntaxOnly`(`enum`·`namespace`·매개변수 속성·데코레이터 없음)와 `verbatimModuleSyntax`(타입만 가져오는 import는 `import type`)를 켠다. 닫힌 값 표는 지금처럼 얼린 객체다. 클래스 필드는 `declare`로 적어 지은 파일에 필드 정의가 생기지 않게 한다 | 제안 |
| D3 | **타입 검사와 빌드를 나눈다.** 타입은 `tsc --noEmit`(TypeScript 7)이 검사한다. 지은 파일은 `tsc`의 출력이 아니라 원본에서 타입만 지운 글이다. 지우는 단계 `tools/strip_types.mjs`는 typescript-eslint를 위해 이미 고정한 TypeScript 6.0.3의 파서로 타입인 조각(타입 주석, `as`·`satisfies`·`!`, 타입 인자, 타입만 있는 문과 import 항목)만 지우고 코드·주석·배치는 그대로 둔다. 문법을 낮추지 않고 다시 찍지 않으며, 지울 수 없는 TypeScript와 파싱되지 않는 모듈은 거부한다. 주석은 남긴다. 지은 파일은 전처럼 모듈의 글을 주석째 담고, 설명이 디버깅에 남는다. `npm test`가 모든 모듈에서 이 단계의 결과를 `ts.transpileModule`의 출력과 프로그램(노드 종류와 이름·리터럴, 괄호와 주석 제외) 단위로 대조한다 | 제안 |
| D4 | **검사는 지금보다 느슨해지지 않는다.** 엄격하지 않은 `tsconfig.json`은 오류 0을 지키고, `tsconfig.strict.json`은 파일마다 줄기만 하는 기준선이다. ESLint는 `no-jsdoc-any`를 `no-explicit-any`로, `no-jsdoc-cast`를 `consistent-type-assertions`(`assertionStyle: never`, `as const`는 세지 않는다)와 `no-non-null-assertion`으로 바꾸고, `ban-ts-comment`와 `limn/no-jsdoc-type`을 더한다. `no-imported-state-write`는 타입 단언을 거친 쓰기도 본다. 타입 정보는 `tsconfig.strict.json`으로 읽는다. TypeScript는 `noImplicitAny`가 켜져야 타입 없는 `let x;`와 `[]`를 JavaScript 때처럼 대입한 값으로 추론하기 때문이다. `no-undef`는 `types/`의 선언을 보지 못해 돌리지 않고, 없는 이름은 `tsc`가 오류로 거절한다 | 제안 |
| D5 | **시험은 빌드가 읽는 글을 읽는다.** 모듈의 글을 직접 읽거나 node에서 돌리는 파이썬 시험은 같은 단계로 타입을 걷은 글을 읽는다(`tests/support/helpers_js.py`의 `module_texts`). 그래서 그 시험에는 node와 `npm ci --ignore-scripts`가 필요하고, Node를 둔 CI 작업은 개발 도구도 설치한다. 없으면 건너뛰고, `LIMN_TEST_REQUIRE_NODE=1`이면 실패한다 | 제안 |

## Trade-off

- **얻는 것.** 타입이 코드에 붙어 함수 머리 한 줄이 인자와 반환을 말한다. 캐스트는 `x as T`로 보이고 ESLint가 그 노드를 직접 본다. JSDoc만의 문법이 없어진다. 브라우저가 받는 코드는 바뀌지 않는다.
- **감수하는 것.**
  - 타입을 걷는 도구(약 200줄)를 저장소가 소유한다. `transpileModule` 대조와 제 사례 시험이 그 정확성을 지키고, 파서는 typescript-eslint가 이미 쓰는 고정 판이라 새 의존성은 없다. 다만 타입 검사는 TypeScript 7, 걷기는 TypeScript 6.0의 파서라 새 문법이 7에만 생기면 걷기가 먼저 거부한다.
  - 엄격하지 않은 TypeScript는 JavaScript보다 덜 추론한다. 타입 없는 `[]`는 `never[]`, `new Set()`은 `Set<unknown>`, 나중에 속성을 더하는 객체 리터럴은 그 속성이 없다. 이런 선언에는 타입을 단다. 처음 변환에서 손으로 단 타입은 엄격 검사의 수를 117개 줄였고(1,113 → 996, 늘어난 파일 없음), 한편 더 좁아진 타입이 `any` 값을 받는 자리를 드러내 `no-unsafe-*`의 수가 몇 파일에서 늘었다.
  - 지은 파일에는 지운 자리의 흔적이 남는다. 여러 줄로 나뉜 타입 주석은 줄바꿈을, 단언을 지운 자리는 쓸모없는 괄호를 남긴다. 프로그램은 같다.
  - 파이썬 시험 일부가 node와 개발 도구를 요구한다. 이전에는 node 없이 돌던 소스 검사 몇 가지(`test_viewer_source`, `test_viewer_markup`, CSS 클래스와 스크롤 쓰기의 검사)가 그것 없이는 건너뛴다. 페이지 정책의 소스 검사는 TypeScript 글을 그대로 읽어 node가 필요 없다.

## 대안

- **JSDoc을 그대로 둔다.** 검사의 힘은 같지만 위의 읽기 비용이 남고, JSDoc 캐스트는 ESLint가 주석으로만 볼 수 있다(지역 규칙 `no-jsdoc-cast`가 필요했다). 채택하지 않는다.
- **`tsc`(또는 그것을 쓰는 `@rollup/plugin-typescript`)가 내보낸 JavaScript를 묶는다.** 내보내기는 코드를 다시 찍어(들여쓰기, 줄바꿈, 일부 괄호와 주석) 지은 파일이 원본과 글이 달라지고, 결과가 타입 검사기의 판에 묶이며, 검사와 출력이 한 단계에 섞인다. 채택하지 않는다.
- **esbuild·sucrase·amaro.** 새 개발 의존성이 늘고, esbuild는 [ADR-0042](0042-viewer-es-modules.md)가 다시 찍기 때문에 기각했다. Node 내장 `module.stripTypeScriptTypes`는 Node 판마다 다른 swc를 실어 CI와 기여자의 판에 따라 결과가 달라질 수 있다. 채택하지 않는다.
- **지운 자리를 공백으로 채워 위치를 지킨다.** 소스 맵 없이도 열이 맞지만 지은 파일이 공백 투성이가 된다. 지은 파일은 소스 맵 없이 읽히는 것이 목적이라 지운 만큼 줄인다.

## 결과

- 현재 규칙은 Handbook에 있다: [viewer.md](../handbook/viewer.md) §뷰어 규칙을 바꿀 때, §타입 검사, §모듈 경계, [verification.md](../handbook/verification.md) §1, §9, [architecture.md](../handbook/architecture.md) 불변식 2.
- 바뀌지 않은 것의 증거: 지은 `dist/viewer.js`를 terser 5.31.6(`compress:false, mangle:false, comments:false`)로 정규화한 SHA-256이 변환 전과 같다(`19bb94120d164e5b537b25fa93a30983ae65ae38491a8fbd1954162d07033328`). 지은 파일은 JSDoc 타입이 주석에서 빠져 1,752,362바이트에서 1,664,338바이트가 되었다.
- 되돌릴 조건: 걷는 단계가 잘못된 코드를 지은 파일에 남기면 이전 태그로 업데이트한다(`limn update --ref <태그>`). 상태·저장 형식·API는 바뀌지 않았다.
