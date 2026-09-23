# PDF.js (vendored)

뷰어가 원고 PDF 를 벡터로 그리는 데 쓰는 Mozilla PDF.js 빌드다. 뷰어는 테일넷 안에서만 돌기 때문에 외부 CDN 을 쓰지 않고, 서버가 `GET /vendor/pdfjs/<파일>` 로 직접 준다. 엔드포인트 계약은 스킬 루트의 `references/api.md`에 있다.

| 항목 | 값 |
| --- | --- |
| 패키지 | `pdfjs-dist@6.3.289` (npm `latest`, 2026-08-29 배포, 빌드 `1c8020a7d`) |
| 받은 방법 | `npm pack pdfjs-dist@6.3.289` → `package/legacy/build/` 에서 두 파일, `package/LICENSE` |
| tarball sha256 | `06f25e887adc6489f04c9fcb14198c77e4e5623a59a0bba5c4cea5838a4f1241` |
| 라이선스 | Apache-2.0 — [`LICENSE`](LICENSE) (원본 그대로) |

| 파일 | 바이트 | sha256 |
| --- | ---: | --- |
| `pdf.min.mjs` | 518,555 | `f401927e692efc7735e0cd528c490d0dd31b7f0972c122b7040df805be45cce4` |
| `pdf.worker.min.mjs` | 1,317,034 | `a33cfe728c584fdba4fcc1fd54bcdc2f9f2f13889ddbb5b2bd1d0f8cbe49b84e` |
| `LICENSE` | 10,174 | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |

## 왜 이 두 파일만인가

- **`legacy` 빌드를 쓴다.** 6.x 의 기본 빌드는 `Map.prototype.getOrInsertComputed` 같은 최신 내장 함수를 폴리필 없이 부른다. 조금 오래된 모바일 브라우저에서는 불러오자마자 멈춘다. `legacy` 는 그 폴리필을 담아 두 파일 합쳐 약 110 KB 더 크다.
- **`cmaps/`·`standard_fonts/`·`wasm/` 은 넣지 않았다(실측, 2026-09-23).**
  - 시험 원고(pdfTeX, 28쪽)의 글꼴 148개는 전부 임베드된 Type 1 부분 글꼴이었다(`pdffonts` 의 `emb` 열이 모두 `yes`, 한글도 `nanummjm*` Type 1). 임베드 안 된 표준 14 글꼴이 없으니 `standard_fonts` 가 필요 없다. CID 글꼴이 없어 `cmaps` 도 필요 없다.
  - 래스터 이미지가 없어(`pdfimages -list` 0건) JPEG 2000 디코더(`wasm/openjpeg`)도 쓸 일이 없다. 뷰어는 `useWasm:false` 로 불러 wasm 을 받으러 가지 않는다.
  - 셋을 다 넣으면 약 4 MB 가 는다.
- 임베드 안 된 글꼴을 쓰는 원고라면 PDF.js 가 시스템 글꼴로 대신 그린다. 글자 모양은 조금 달라질 수 있지만 위치는 PDF 좌표 그대로다. 그래도 문제가 되면 `standard_fonts/` 를 이 디렉토리에 추가하고 뷰어의 `standardFontDataUrl` 을 켠다.

## 갱신

1. `npm pack pdfjs-dist@<새 버전>` 을 한 뒤 `legacy/build/pdf.min.mjs`·`legacy/build/pdf.worker.min.mjs`·`LICENSE` 를 덮어쓴다.
2. 위 표의 버전·크기·sha256 을 고친다.
3. `scripts/pin_server.py` 의 `PDFJS_VERSION` 을 바꾼다. 브라우저 캐시를 가르는 `?v=` 값이다.
4. 회귀 테스트(`VendorPdfjs`)가 파일 머리의 `pdfjsVersion` 과 `PDFJS_VERSION` 이 같은지 본다.
