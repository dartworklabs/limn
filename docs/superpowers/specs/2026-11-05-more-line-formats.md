# 원문 위치를 지키는 다른 줄 단위 형식 — 연구실이 쓰는 것부터: Markdown의 머리 정보, 그다음 수식

> **상태: 제안 (2026-11-05).** [HTML 문서 화면 설계](2026-10-24-html-document-surface.md) §이후 단계의 3이다. 소유자가 이 단계를 진행하라고 했고, 첫 일은 어느 형식이 이 연구실의 쓰임에 값하는지 정하는 것이었다. 결론은 새 문서 종류가 아니라 Markdown 종류 안의 두 확장이다. 핀 값 하나(`md:front`)를 더하므로 에이전트 계약 변경이고, [workflow.md](../../handbook/workflow.md) §기본 경로의 HARD-GATE에 따라 소유자 승인 뒤에 `main` 에 넣는다. 결정 초안은 [ADR-0032](../../adr/0032-markdown-front-matter.md)(`제안`)다.
>
> - 대조한 코드: `main` ea798484(0.4.51). 아래 `file:line` 은 PoC 브랜치 기준이다.
> - PoC: 브랜치 `poc/line-formats`. 1단계(머리 정보)를 끝까지 구현했고 시험이 붙어 있다. 테일넷 시안 <https://ml-a6000.tail8937e8.ts.net:18051/> 은 합성 문서 넷(논문 노트, 스킬, 머리 정보가 없는 구분선 문서, 다음 단계의 수식 문제를 보이는 수식 노트)을 띄운다.
> - 조사 자료: 이 머신의 저장소 11개(`git ls-files`, worktree 사본 제외)와 홈 아래의 추적되지 않은 파일(`find`, 캐시·가상 환경 제외), 2026-11-05.

## 문제

이후 단계 3은 "원문 위치를 지키는 렌더러가 있는 다른 줄 단위 형식"이다. 후보는 많다. Quarto·R Markdown, AsciiDoc, Org, reStructuredText, Jupyter, Typst 등이다. 형식 하나를 받을 때마다 렌더러 번들(멈춤 신호), 새 보안 면, 줄 대응 규칙, 사다리 값이 는다. 그래서 먼저 이 연구실이 실제로 무엇으로 쓰고 무엇을 사람이 검토하는지 셌다.

## 조사

### 이 연구실이 쓰는 문서

| 확장자 | 추적 파일 | 2026-08-05 뒤 바뀐 파일 수(커밋별 합) | 쓰임 |
| --- | ---: | ---: | --- |
| `.md` | 1,281 (15.4 MB) | 5,873 | 원고 백본(Limn `bb` 탭), 감사·ADR·Handbook, 제안서 초안, 논문 노트, 개념도 명세, 스킬 |
| `.tex` | 88 | 655 | 원고·하이라이트·커버레터(Limn `ms`·`hl`·`cl`) |
| `.typ` | 53 | 26 | 제안서 보관본 24, CV 22, 서식 5, 진행 중 제안서 1(마지막 변경 2026-05-27). 26은 cpptl-code Handbook 20(2026-09에 Markdown으로 옮김)과 하네스 기록 6이고, 제안서 저장소의 Typst는 8월 뒤 0 |
| `.hwpx`·`.hwp` | 27·14 | — | 정부 과제 서식. 압축한 XML이라 줄 단위가 아니다 |
| `.bib` | 10 | — | 이미 텍스트 문서([ADR-0029](../../adr/0029-text-documents.md)) |
| `.qmd`·`.Rmd`·`.ipynb`·`.adoc`·`.org`·`.rst`·`.mdx` | **0** | 0 | 추적되지 않은 파일까지 홈 전체에서 0 |

연구실은 Markdown과 LaTeX로 쓴다. Typst는 줄고 있다. Handbook은 Typst에서 Markdown으로 옮겼고, 제안서는 Markdown 초안과 HWPX 서식으로 간다. 그래서 후보 형식에는 지금 검토할 파일이 하나도 없다.

수요는 Markdown 안에 있다. 1,281개 파일에서 CommonMark·GFM 밖의 구성을 쓰는 파일 수는 다음과 같다.

| 구성 | 파일 | 어디에 |
| --- | ---: | --- |
| TeX 수식(코드 밖 `$…$`·`$$`) | 134 | 개념도 명세 38, 분석 감사 15, ceit 원고 노트 10, 설계 8, 백본 보조 문서 6 등. 113개는 수식 안에 `*`·`_` 가 있다 |
| 각주 `[^x]` | 92 | 88개가 dataset-catalog |
| YAML 머리 정보 | 71 | 논문 노트 17, 에이전트 규칙·스킬 31, 기타. 길이 중앙값 4줄, 90분위 20줄, 최대 38줄 |
| 할 일 목록 `- [ ]` | 92 | 여러 곳(GFM 확장. 지금 `[ ]` 글자로 보인다) |
| 원시 HTML | 31 | 이미 자리표시([ADR-0025](../../adr/0025-html-document-surface.md) D6) |
| GFM 알림 `> [!NOTE]` | 8 | |
| Pandoc 교차 참조 `{#fig:…}`·`:::` 구획·청크 ` ```{r} ` | 0 | |

지금 Limn이 그리는 모습을 번들한 markdown-it 15.0.3으로 재현했다.

- **머리 정보.** 첫 줄 `---` 가 구분선이 되고, YAML 줄은 문단 하나로 이어지거나 setext 제목이 된다. 스킬 파일은 `name:`·`description:` 이 h2 제목이 되어 목차와 절 사다리에 든다. 논문 노트는 구분선 아래 YAML을 이은 한 문단이다.
- **수식.** `$t^*$ 는 … $t^*=\infty$` 의 두 `*` 가 기울임으로 짝지어져 `*` 가 사라지고 그 사이 글이 기운다. 보이는 글이 원문과 다르다.

두 경우 모두 줄 번호는 맞다(블록 `map`). 그러나 사람이 보는 글이 원문과 다르고, 머리 정보는 목차와 절을 어지럽힌다.

### 후보 형식

| 형식 | 연구실 파일 | 렌더러(판, 라이선스) | 크기 | 줄 대응 | 보안 면 | 품 |
| --- | ---: | --- | --- | --- | --- | --- |
| **YAML 머리 정보** (`.md` 안) | 71 | 자체 블록 규칙. 참고: markdown-it-front-matter 0.2.4(MIT, 3.6 KB) | worker 25줄 | 블록 `map` 그대로, 안의 줄마다 | YAML을 파싱하지 않고 글자로만 보인다 | 작다 |
| **TeX 수식, 글자로 지키기** (`.md` 안) | 134 | 자체 인라인·블록 규칙 | 수십 줄 | `$$` 블록은 줄마다. 인라인은 D7 규칙(줄 끝을 삼키면 블록 범위) | 글자뿐 | 작다 |
| TeX 수식 그리기 | 134 | KaTeX 0.19.1(MIT) | JS 273 KB, CSS 25 KB, woff2 260 KB. markdown-it 번들(125 KB)의 약 4.5배 | 위와 같다 | HTML 출력이 `style` 속성을 써서 [ADR-0026](../../adr/0026-viewer-csp.md)의 엄격한 `style-src`와 부딪힌다. 출력이 문자열이라 두 번째 sink나 MathML을 `DOMParser`로 옮기는 길이 필요하다. `trust`·`maxExpand` 한도 | 크다(번들, CSP) |
| Quarto `.qmd`·R Markdown `.Rmd` | 0 | markdown-it + 머리 정보. 청크는 이미 코드 블록 | 접미사 둘 | Markdown과 같다 | Markdown과 같다. `:::`·`{#fig-}`·`@fig-` 는 글자 | 아주 작다 |
| Typst `.typ` | 53(8월 뒤 0) | typst 0.15.1 CLI(Apache-2.0)는 PDF·SVG·HTML 어디에도 원문 위치를 싣지 않는다(§Typst 확인). 거꾸로 찾기는 Rust 라이브러리 typst-ide의 `jump_from_click`(쪽 위 점 → 파일·바이트), 또는 tinymist 미리보기(typst.ts 렌더러 0.7.0, wasm 972 KB) | CLI 17 MB(tar.xz) | `jump_from_click` 은 SyncTeX와 같은 결의 점 → 원문 | 컴파일러가 파일을 읽고(`#include`·`read()`, 루트 제한) `@preview` 패키지를 내려받는다 | 크다. 새 외부 도구(멈춤 신호), PDF 화면의 빌드·pick 길 하나 더 |
| Jupyter `.ipynb` | 0 | JSON. nbformat 4의 `source` 는 문자열이거나 줄 목록 | — | 줄 목록으로 저장된 셀만 JSON 줄과 셀 줄이 1:1이다. 핀의 줄이 JSON으로 이스케이프된 글이라 제안 수정이 JSON을 고친다 | 출력(HTML·JS·그림) | 크다 |
| AsciiDoc `.adoc` | 0 | asciidoctor.js 4.2.1(MIT), `sourcemap` 이 블록 `lineno` | 브라우저 빌드 1.0 MB | 블록 시작 줄만(메타 줄은 건너뛴다, include 경계 주의), 끝 줄은 없다 | `include::`, `+++`·`pass:[]` 로 원시 HTML | 크다 |
| Org `.org` | 0 | uniorg-parse 3.2.2, **GPL-3.0-or-later**, `trackPosition` | 304 KB와 unified 의존성 | 노드마다 줄·열 | 내보내기 블록의 원시 HTML | 중간. [CLA](../../../CLA.md)가 독점 조건 재허락을 허용하므로 GPL 번들은 그 길을 막는다 |
| reStructuredText `.rst` | 0 | restructured 0.0.11(2019년 뒤 멈춤, 위치 없음), docutils-ts 1.0.7(위치를 밝히지 않음) | — | 지키지 못한다 | `raw` 지시문 | 크다 |
| MDX | 0 | JSX는 코드 실행이다 | — | — | 실행 | — |

`.adoc`·`.org`·`.rst` 는 이미 텍스트 문서다. [ADR-0029](../../adr/0029-text-documents.md) D2는 확장자 목록이 "더하기만 한다"고 정했으므로, 이들을 그리는 종류로 옮기려면 그 조항부터 바꿔야 한다. 파일이 없는 지금 그럴 까닭이 없다.

### Typst 확인

`/tmp` 에 typst 0.15.1(musl 빌드, sha256 `a6d077d0…`)을 받아 합성 문서(제목 둘, 두 줄 문단, 목록, 수식)를 시험했다. 전역 설치는 하지 않았다.

- `typst compile` 의 PDF(14.9 KB)·SVG·HTML(`--features html`) 어디에도 원본 파일 이름이나 원문 위치가 없다.
- `typst eval 'query(heading).map(it => (repr(it.body), it.location().position()))' --in probe.typ` 은 요소의 쪽과 좌표를 준다(`[Introduction]` → 1쪽 27pt, 27pt). 앞으로 찾기(원문 → 쪽)는 라벨·제목에 한해 된다. 그러나 원문 줄은 주지 않는다. `typst query` 는 0.15에서 폐기 예정이다.
- 고른 자리에서 원문 줄로 가는 길(Limn의 pick)은 CLI에 없다. typst-ide의 `jump_from_click` 을 품은 도우미를 Limn이 만들어 싣거나 tinymist를 요구해야 한다. 둘 다 새 외부 도구라 멈춤 신호다.

## 제안

이 단계는 새 문서 종류를 더하지 않는다. Markdown 종류를 연구실이 쓰는 두 방언으로 넓힌다.

1. **머리 정보(이 설계, PoC 완료).** 문서 맨 앞의 YAML 머리 정보를 제 블록으로 그린다. 원문 줄 그대로 보이고 YAML은 파싱하지 않는다. 목차와 절에는 들지 않고, 핀 값은 `md:front` 다.
2. **수식을 글자로 지키기(다음 설계).** `$…$`·`$$…$$` 를 인식해 기울임·굵게가 그 안을 건드리지 못하게 하고, TeX 원문을 고정폭 글자로 보인다. 번들이 없다.

수식 그리기(KaTeX), Typst, 그 밖의 형식은 §결정 5의 조건이 생길 때 따로 연다.

## 결정 (추천안)

| # | 결정 | 추천 | 소유자 몫 |
| --- | --- | --- | --- |
| 1 | 이 단계의 범위 | 새 종류 없이 Markdown 방언 둘. 머리 정보 먼저, 수식 글자 지키기 다음 | 예 |
| 2 | 머리 정보를 알아보는 규칙 | Pandoc `yaml_metadata_block` 의 시작·끝에 "첫 내용 줄은 키나 주석"을 더한다 | 아니오. 시험으로 지킨다 |
| 3 | 보이는 법 | 원문 줄 그대로 상자에 보이고 펼쳐 둔다. YAML은 파싱하지 않는다. 목차·절에서 빠진다 | 부분. 모양은 PoC로 본다 |
| 4 | 핀 값 | 블록 종류 `front` 를 더한다. 핀 `kind` 는 `md:front`, `scope` 는 `block` 이다 | 예. 에이전트 계약 값 |
| 5 | 다른 형식 | `.qmd`·`.Rmd` 는 검토할 파일이 생기면 접미사를 더한다. Typst는 검토할 Typst 문서가 생기면 별도 트랙으로 연다. `.ipynb` 는 미룬다. `.adoc`·`.org`·`.rst` 는 텍스트 문서 그대로 둔다. MDX는 기각한다 | 예 |
| 6 | 라이브러리 | 번들하지 않는다. worker 안의 자체 블록 규칙이다 | 아니오 |

### 결정 2. 알아보는 규칙

머리 정보는 다음을 모두 만족할 때만이다(`mdFrontMatter`, `md-parse.mjs:29`).

- 첫 줄이 `---` 다. 앞에 바이트 순서 표시가 있어도 되고, 뒤에 공백이 붙어도 된다. 들여 쓴 `---` 와 `----` 는 아니다.
- 둘째 줄이 비지 않았다(Pandoc: "The initial line `---` must not be followed by a blank line").
- 둘째 줄이 YAML 매핑을 연다. 키와 쌍점(`title:`, `"key": v`) 또는 `#` 주석이다. `https://…` 나 평범한 글은 아니다.
- 뒤의 어느 줄이 `---` 나 `...` 다(Pandoc의 끝 줄).

하나라도 어기면 다른 규칙이 지금처럼 읽는다. 구분선, setext 제목, 문단이다. 그래서 규칙이 틀려도 줄을 잘못 매기지 않는다. 연구실의 머리 정보 71개는 모두 이 규칙에 든다. Pandoc은 문서 중간의 메타데이터 블록도 받지만 여기서는 받지 않는다. 중간의 `---` 는 대개 구분선이기 때문이다.

### 결정 3. 보이는 법

상자 하나가 `---` 두 줄까지 블록 범위를 가진다(`data-lo..hi`, `data-kind="front"`). 머리 줄은 화면 언어로 `머리 정보 · YAML N줄` 이다. 그 아래 코드 상자에 안쪽 줄이 줄마다 하나씩 선다(`data-line`). 글은 서버의 줄(`MD.lines`)을 `textContent` 로 넣는다. 그래서 링크도, 그림도, 마크업도 없다. 머리 정보는 제목이 아니므로 목차·절 표시줄·절 단계에 들지 않는다. YAML 주석 `# …` 이 제목으로 보이던 것도 사라진다.

긴 값(스킬의 `description:` 은 한 줄이 길다)은 상자 안에서 접는다. 코드 블록처럼 옆으로 넘기면 휴대폰에서 끌기가 글 고르기와 부딪히고 값이 잘려 보인다. 텍스트 문서가 긴 줄을 접는 까닭과 같다([ADR-0029](../../adr/0029-text-documents.md) §대안). 블록을 누른 핀의 `quote` 는 안쪽 줄의 글만이다. 머리 줄은 뷰어의 말이라 원문 인용에 넣지 않는다.

펼쳐 둔다. 중앙값이 4줄이고, 핀은 그 줄(제목, 날짜, 태그)에 붙는다. 접는 단추는 원시 HTML 묶음(`md-html-run`)에만 있다. 그 묶음은 그리지 않는 것을 모아 두는 자리라 사정이 다르다.

YAML을 표로 그리지 않는다. GitHub는 표로 보이지만, 그러려면 YAML 파서(번들, 앵커 폭탄 같은 한도)가 필요하다. 줄 핀에는 원문 줄이 더 정확하다. 표의 칸에서는 어느 줄을 골랐는지 말할 수 없기 때문이다.

### 결정 4. 핀 값 `md:front`

머리 정보는 문단도 코드 블록도 아니다. 에이전트가 `md:code` 를 받으면 코드 블록을 찾는다. `md:front` 를 받으면 문서의 메타데이터를 고친다는 것을 안다. 사다리는 `고른 줄` → `머리 정보` 다. 첫 제목 위라 절 단계는 없다(뷰어의 기존 규칙). 누르면 블록이 기본이다.

서버는 바꾸지 않는다. 레코드 검사는 `kind` 가 문자열인지만 보고(`pins/record.py:128`), `pins.md` 범위 칸은 `md:` 로 시작하는 값을 그대로 쓴다(`pins/listing/render.py:196`). 그래서 직전 릴리스도 이 핀을 지우지 않고 `md:front` 로 적는다. 옛 뷰어는 그 문서를 지금처럼(구분선과 문단으로) 그리지만, 핀의 줄은 같다. 되돌리기에 설정을 바꿀 일이 없다.

### 결정 5. 다른 형식을 여는 조건

| 형식 | 열 조건 | 그때 할 일 |
| --- | --- | --- |
| `.qmd`·`.Rmd` | 검토할 파일이 생긴다 | Markdown 접미사에 더한다(닫힌 목록, 더하기만). 머리 정보와 청크 펜스는 이미 그려진다. 교차 참조는 글자로 둔다 |
| 수식 그리기 | 2단계(글자 지키기) 뒤에 그린 수식을 원한다 | KaTeX를 MathML 출력으로만 쓰고 `DOMParser` 로 옮기는 길과 CSP를 따로 정한다(번들 멈춤 신호) |
| Typst | Typst 원고나 제안서를 Limn에 올리려 한다 | PDF 화면의 새 빌드 종류. `typst compile` 로 빌드하고, `jump_from_click` 을 품은 도우미로 pick한다. 외부 도구 ADR이 필요하다 |
| `.ipynb` | 검토할 노트북이 생긴다 | 셀을 블록으로 그리고, 핀 위치를 무엇으로 할지(JSON 줄인가, 셀과 셀 안 줄인가) 먼저 정한다 |
| `.adoc`·`.org`·`.rst` | 파일이 생기고 텍스트 문서로 부족하다 | ADR-0029 D2의 "더하기만"을 바꾸는 결정부터 한다 |

### 결정 6. 번들하지 않는다

markdown-it-front-matter(MIT)가 있지만 3.6 KB짜리를 위해 판 고정, sha256, 고지 절차를 하나 더 둘 까닭이 없다. 또 Pandoc의 시작 규칙과 첫 줄 검사를 지키려면 결국 고쳐야 한다. 자체 규칙은 worker 안에 있고 같은 출처의 번들(markdown-it)만 부른다. 런타임 의존성이 늘지 않으므로 멈춤 신호가 아니다.

## 바꿀 곳

PoC가 바꾼 곳이다.

| 파일 | 무엇 |
| --- | --- |
| `src/limn/viewer/md-parse.mjs:17`, `:29`, `:54` | `mdParser`(설정과 규칙 설치), `mdFrontMatter`(블록 규칙), worker가 `mdParser` 를 쓴다 |
| `src/limn/viewer/js/md-surface.js:274`, `:289` | `front_matter` 토큰을 `mdFront` 가 상자로 짓는다 |
| `src/limn/viewer/js/md-surface.js:577`, `:584` | 블록 종류 목록과 사다리 이름에 `front`(`머리 정보`) |
| `src/limn/viewer/js/md-surface.js:762` | 머리 정보를 누른 핀의 `quote` 는 안쪽 줄의 글만이다(머리 줄은 뷰어의 말) |
| `src/limn/viewer/css/md-surface.css:68-71` | 상자와 머리 줄. 긴 값은 접는다 |
| `src/limn/viewer/ui_en.json` | `Front matter`, `Front matter · YAML, {n} lines` |
| `src/limn/viewer/tests/test_viewer_markdown.py` | 파서를 멈추게 하는 가짜 모듈이 `block.ruler.before` 를 갖춘다(worker가 규칙을 설치하므로) |

구현 단계에서 더할 곳이다.

- [api.md](../../handbook/api.md) §Markdown 문서의 핀의 값 목록과 핀 필드 표의 `kind` 칸에 `md:front`.
- [viewer.md](../../handbook/viewer.md) §Markdown 화면의 §그리기(머리 정보 상자)와 §고르기와 범위 사다리의 블록 목록.
- `skill/SKILL.md`·`skill/SKILL.ko.md` 의 Markdown 핀 범위 목록. 머리 정보 핀은 YAML 줄을 고친다는 한 문장.
- 사다리 블록 칸의 설명(`고른 자리를 감싸는 블록 전체입니다(문단·…·HTML 블록)`)에 머리 정보.
- CHANGELOG. 서버 코드는 바꾸지 않는다.

## 검증

- **순수 시험**(`test_md_surface.py` `FrontMatterRule`, node + 번들 markdown-it, worker의 함수를 그대로 뽑아 쓴다). 열두 경우: 닫힌 블록, `...` 끝, 주석으로 시작하고 빈 줄이 든 블록, 바이트 순서 표시와 끝 공백, 쌍점이 든 값, 여는 줄 뒤 빈 줄, 닫지 않음, 첫 줄이 아님, 문단, 주소, `----`, 들여 쓴 여는 줄. 머리 정보 뒤 블록의 `map` 이 그 줄을 빈 줄로 바꾼 문서와 같다. 키 검사를 끄면 세 경우가 실패하는 것을 확인했다.
- **브라우저 시험**(`test_viewer_markdown.py` `FrontMatter`). 상자가 1–5줄을 가지고, 안쪽 줄이 서버의 줄이며, 머리 줄이 화면 언어이고, 긴 값이 접히며, 구분선·h2가 없고, 목차가 진짜 제목에서 시작하며, 비지 않은 모든 원문 줄이 화면에 있다. YAML 줄을 누르면 사다리가 `고른 줄` → `머리 정보` 이고, `quote` 가 YAML 글만이며, 저장한 핀이 `md:front`·`block`·쪽 없음이며, `pins.md` 에 `md:front` 와 `—` 가 찍힌다.
- **실행한 시험.** `uv run pytest -q -n 4 -m "not browser and not tex"` 3,841 통과(1 건너뜀). Markdown·텍스트·CSP·i18n·타입·계약 시험 293 통과(3 건너뜀). `tsc -p .` 와 `tsc -p tsconfig.strict.json` 통과. 테일넷 PoC를 네 기기군(데스크톱 1440×900, 폴더블 안쪽 673×841, 태블릿 768×1024, 휴대폰 390×844)에서 찍었다.
- **구현 단계에서 더할 것.** 계약 스냅숏과 SKILL 시험, 직전 릴리스가 `md:front` 핀을 지우지 않는 시험, 큰 머리 정보(요소 한도 안에서 원문 줄 보기로 물러서기), 네 기기군 실측.

## 열린 결정

1. **이 단계를 "Markdown 방언 둘"로 바꾼다.** 추천: 예. 후보 형식의 파일은 0개이고, 수요는 Markdown 안에 있다(머리 정보 71개, 수식 134개).
2. **핀 값 `md:front` 를 더한다.** 추천: 예. 에이전트가 메타데이터를 고친다는 것을 값만 보고 안다. 옛 서버도 그대로 받는다.
3. **머리 정보 상자는 펼쳐 둔다.** 추천: 펼침. 중앙값 4줄로 짧고, 핀이 그 줄에 붙는다.
4. **다음 단계는 수식을 글자로 지키기다.** 추천: 예, 짧은 설계를 따로 쓴다. 134개 파일 가운데 113개가 지금 기울임에 깨질 수 있고, 번들이 필요 없다.
5. **Typst는 검토할 Typst 문서가 생길 때 연다.** 추천: 미룸. 제안서 저장소의 Typst는 8월 뒤 바뀐 적이 없고, CLI가 원문 위치를 주지 않아 새 외부 도구가 필요하다.

## 출처

- Pandoc User's Guide, Extension `yaml_metadata_block`: <https://pandoc.org/MANUAL.html#extension-yaml_metadata_block>
- nbformat, The Notebook file format: <https://nbformat.readthedocs.io/en/latest/format_description.html>
- Asciidoctor, Map Source Location of Blocks: <https://docs.asciidoctor.org/asciidoctor/latest/api/sourcemap/>
- uniorg: <https://github.com/rasendubi/uniorg>. `uniorg-parse` 3.2.2의 `license` 는 npm 등록부에서 `GPL-3.0-or-later`
- typst-ide `jump`(0.14.2): <https://docs.rs/typst-ide/0.14.2/src/typst_ide/jump.rs.html>
- Typst 포럼, SyncTeX 대응물 질문: <https://forum.typst.app/t/is-there-a-synctex-equivalent-for-typst-cli/995>
- tinymist 미리보기(옛 typst-preview): <https://github.com/Enter-tainer/typst-preview>
- restructured: <https://github.com/seikichi/restructured>
- markdown-it-front-matter: <https://github.com/parksb/markdown-it-front-matter>
- 크기와 라이선스는 npm 등록부(`registry.npmjs.org/<이름>/latest`)에서 받은 판의 실측이다. KaTeX 0.19.1, @asciidoctor/core 4.2.1, @myriaddreamin/typst-ts-renderer 0.7.0, docutils-ts 1.0.7
