# Third-party notices

Limn bundles the following third-party components, each under its own license. Their license files
are kept unmodified next to the vendored files.

| Component | Version | Where | License |
| --- | --- | --- | --- |
| [PDF.js](https://github.com/mozilla/pdf.js) (`pdfjs-dist`, legacy build) | 6.3.289 | `src/limn/vendor/pdfjs/` | Apache-2.0 — [`src/limn/vendor/pdfjs/LICENSE`](src/limn/vendor/pdfjs/LICENSE) |
| [Pretendard](https://github.com/orioncactus/pretendard) Variable (`pretendard`, dynamic subset: 92 `woff2` slices and their stylesheet) | 1.3.9 | `src/limn/vendor/pretendard/` | SIL Open Font License 1.1, Reserved Font Name "Pretendard" — [`src/limn/vendor/pretendard/LICENSE`](src/limn/vendor/pretendard/LICENSE) |
| [markdown-it](https://github.com/markdown-it/markdown-it) (ESM browser build, imported by the Markdown parse worker) | 15.0.3 | `src/limn/vendor/markdown-it/` | MIT — [`src/limn/vendor/markdown-it/LICENSE`](src/limn/vendor/markdown-it/LICENSE) |
| Bundled in the markdown-it file above: `entities` 8.1.0, `mdurl` 2.1.0, `linkify-it` 6.1.0, `uc.micro` 3.0.0, `punycode.js` 2.3.1, the rolldown 1.2.14 runtime helper (derived from esbuild's runtime, whose notice rolldown's THIRD-PARTY-LICENSE carries with Rollup's), `@oxc-project/runtime` 0.154.0 helpers (copied from `@babel/runtime`, whose notice is kept too) | (each its own) | `src/limn/vendor/markdown-it/markdown-it.esm.min.mjs` | `entities` BSD-2-Clause; `mdurl` MIT with the Joyent, Inc. notice; rolldown MIT with its THIRD-PARTY-LICENSE (esbuild's and Rollup's MIT notices); `@oxc-project/runtime` MIT with Babel's MIT notice (Sebastian McKenzie and other contributors); the rest MIT — each in [`src/limn/vendor/markdown-it/licenses/`](src/limn/vendor/markdown-it/licenses/) |
| [KaTeX](https://github.com/KaTeX/KaTeX) (ESM browser build, its stylesheet and its 20 `woff2` fonts, imported by the page to draw a Markdown document's math) | 0.19.1 | `src/limn/vendor/katex/` | MIT — [`src/limn/vendor/katex/LICENSE`](src/limn/vendor/katex/LICENSE) (the bundle carries no third-party code of its own) |
| [Lucide](https://github.com/lucide-icons/lucide) icons (`lucide-static`, SVG elements inlined in `src/limn/server.py`) | 1.47.0 | `src/limn/vendor/lucide/` (license and provenance) | ISC; icons derived from Feather are MIT — [`src/limn/vendor/lucide/LICENSE`](src/limn/vendor/lucide/LICENSE) |

Provenance (how each file was obtained, sizes and sha256) is recorded in the README of each vendor directory.
