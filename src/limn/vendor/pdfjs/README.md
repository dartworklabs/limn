# PDF.js (vendored)

The Mozilla PDF.js build the viewer uses to draw the manuscript PDF as vectors. The viewer runs inside a private network, so it does not use an external CDN; the server serves these files itself at `GET /vendor/pdfjs/<file>`. The endpoint contract is in [docs/handbook/api.md](../../../../docs/handbook/api.md).

| Item | Value |
| --- | --- |
| Package | `pdfjs-dist@6.3.289` (npm `latest`, published 2026-08-29, build `1c8020a7d`) |
| Obtained by | `npm pack pdfjs-dist@6.3.289` → the two files from `package/legacy/build/`, plus `package/LICENSE` |
| tarball sha256 | `06f25e887adc6489f04c9fcb14198c77e4e5623a59a0bba5c4cea5838a4f1241` |
| License | Apache-2.0 — [`LICENSE`](LICENSE) (unmodified) |

| File | Bytes | sha256 |
| --- | ---: | --- |
| `pdf.min.mjs` | 518,555 | `f401927e692efc7735e0cd528c490d0dd31b7f0972c122b7040df805be45cce4` |
| `pdf.worker.min.mjs` | 1,317,034 | `a33cfe728c584fdba4fcc1fd54bcdc2f9f2f13889ddbb5b2bd1d0f8cbe49b84e` |
| `LICENSE` | 10,174 | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |

## Why only these two files

- **The `legacy` build.** The default 6.x build calls recent built-ins such as `Map.prototype.getOrInsertComputed` without polyfills and stops right after loading on slightly older mobile browsers. `legacy` carries those polyfills; the two files together are about 110 KB larger.
- **No `cmaps/`, `standard_fonts/` or `wasm/` (measured 2026-09-23).**
  - All 148 fonts of the test manuscript (pdfTeX, 28 pages) were embedded Type 1 subsets (`pdffonts` `emb` column all `yes`, Hangul included). With no non-embedded standard-14 fonts, `standard_fonts` is not needed; with no CID fonts, `cmaps` is not needed.
  - There were no raster images (`pdfimages -list`: 0), so the JPEG 2000 decoder (`wasm/openjpeg`) is never used. The viewer loads PDF.js with `useWasm:false`, so it does not fetch wasm.
  - Adding all three would add about 4 MB.
- For manuscripts with non-embedded fonts, PDF.js substitutes system fonts. Glyph shapes may differ slightly but positions stay at the PDF coordinates. If that is a problem, add `standard_fonts/` to this directory and enable the viewer's `standardFontDataUrl`.

## Updating

1. `npm pack pdfjs-dist@<new version>`, then overwrite `legacy/build/pdf.min.mjs`, `legacy/build/pdf.worker.min.mjs` and `LICENSE`.
2. Update the version, sizes and sha256 values in the tables above.
3. Change `PDFJS_VERSION` in `src/limn/server.py`. It is also the `?v=` value that busts the browser cache.
4. The regression tests (`VendorPdfjs`) check that `pdfjsVersion` in the file headers equals `PDFJS_VERSION`.
