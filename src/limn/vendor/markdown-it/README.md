# markdown-it (vendored)

The Markdown parser the viewer draws a Markdown document with ([ADR-0025](../../../../docs/adr/0025-html-document-surface.md)
D5). The viewer never imports it into the page: its parse worker (`GET /md-parse.mjs`) imports it, and only when a Markdown
document opens. The server serves the module itself at `GET /vendor/markdown-it/<name>.mjs`; the licence files and this
README are not served. The endpoint contract is in [docs/handbook/api.md](../../../../docs/handbook/api.md).

| Item | Value |
| --- | --- |
| Package | `markdown-it@15.0.3` (npm, published 2026-10-16 by the maintainer) |
| Obtained by | `npm pack markdown-it@15.0.3` -> `package/dist/browser/markdown-it.esm.min.mjs`, plus `package/LICENSE` |
| tarball sha256 | `98a7453983ab0e268c17dbd5260bf7190ba46b4cca912327fc1c1a2578e4b56d` |
| License | MIT - [`LICENSE`](LICENSE) (unmodified). The bundle also carries the code below, each under its own licence |

| File | Bytes | sha256 |
| --- | ---: | --- |
| `markdown-it.esm.min.mjs` | 124,681 | `d5432491790141da046b1197353705db03264f40b5727f3b4b591f5aba193e30` |
| `LICENSE` | 1,073 | `792c48c5a849a15fdf9e37e8bcf9e6d1dd13b32b46c642a748a0a46a9919d473` |

## What else the bundle carries

The browser build is one file made by rolldown. Besides markdown-it's own `src/`, it inlines the packages below. Versions
are the ones markdown-it's `package-lock.json` at tag `15.0.3` resolves (commit `a8c00d47`, lockfile sha256
`6a552117…3ff0a8`); each is also the only release in markdown-it's declared range published before 15.0.3. Where the
bundle shows them: `//#region node_modules/<package>/…` and `//#region \0<package>…` markers (the `Region` column), or for
the minified parts without a marker the code itself (the `Marker` column: linkify-it's `schema_names`, punycode's
`Overflow: input needs wider integers to process`, uc.micro's `src_Any` and `src_Cc` classes). The vendor tests
(`VendorMarkdownIt`) check that every region the bundle names and every marker below is in this table, and that each
licence file is here with the size and sha256 the table gives.

Every licence file is the package's own, unmodified, taken from `npm pack <package>@<version>`; the BSD-2-Clause notice of
`entities` (copyright notice, conditions and disclaimer) and both notices of `mdurl` (its authors' MIT notice and the Joyent,
Inc. MIT notice for the Node.js `url` code its `parse()` is based on) are kept whole.

| Package | Version | License | Region | Marker | Licence file | Bytes | Licence sha256 | tarball sha256 |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- |
| `entities` | 8.1.0 | BSD-2-Clause | `node_modules/entities` | | [`licenses/entities-8.1.0.LICENSE`](licenses/entities-8.1.0.LICENSE) | 1,260 | `cb992345949ccd6e8394b2cd6c465f7b897c864f845937dbf64e8997f389e164` | `e9a27d66…a37cbe68` |
| `mdurl` | 2.1.0 | MIT (with the Joyent, Inc. notice) | `node_modules/mdurl` | | [`licenses/mdurl-2.1.0.LICENSE`](licenses/mdurl-2.1.0.LICENSE) | 2,303 | `6b6a356c4337e2446841f30f3cdf7e7023af8c5260b5e347c0f987b9f6aa2644` | `23fc27c3…5aabd11d` |
| `linkify-it` | 6.1.0 | MIT | | `schema_names` | [`licenses/linkify-it-6.1.0.LICENSE`](licenses/linkify-it-6.1.0.LICENSE) | 1,058 | `95e3f7f0e81e9b4940cdfaa1956aaff5e4dfd2fb1565041e7c78eb9a606f23e3` | `780a9e82…029076b8` |
| `uc.micro` | 3.0.0 | MIT | | `src_Cc` | [`licenses/uc.micro-3.0.0.LICENSE`](licenses/uc.micro-3.0.0.LICENSE) | 1,077 | `483acb265f182907d1caf6cff9c16c96f31325ed23792832cc5d8b12d5f88c8a` | `23a27049…75552981` |
| `punycode.js` | 2.3.1 | MIT | | `Overflow: input needs wider integers to process` | [`licenses/punycode.js-2.3.1.LICENSE`](licenses/punycode.js-2.3.1.LICENSE) | 1,077 | `483acb265f182907d1caf6cff9c16c96f31325ed23792832cc5d8b12d5f88c8a` | `8768d89a…1f7324a8` |
| `rolldown` runtime helper (`\0rolldown/runtime.js`: `Object.defineProperty` and `__exportAll`, a few lines) | 1.2.14 | MIT | `\0rolldown` | | [`licenses/rolldown-1.2.14.LICENSE`](licenses/rolldown-1.2.14.LICENSE) | 1,302 | `23ecfff35a5a2e80d92142f75228912c3b1abc4b5a8337a821ff4397e2f9f734` | `9c142fca…c806e53d` |
| the parts of rolldown derived from esbuild and Rollup (its `THIRD-PARTY-LICENSE`: see below) | 1.2.14 | MIT | `\0rolldown` | | [`licenses/rolldown-1.2.14.THIRD-PARTY-LICENSE`](licenses/rolldown-1.2.14.THIRD-PARTY-LICENSE) | 2,209 | `a877291d800ed43692f3f9ae09d8e01cc6f7293ad39d43896059c188ffbb8b7c` | `9c142fca…c806e53d` |
| `@oxc-project/runtime` helpers (`typeof`, `toPrimitive`, `toPropertyKey`, `defineProperty`; injected by rolldown) | 0.154.0 (named in the bundle) | MIT | `\0@oxc-project+runtime@0.154.0` | | [`licenses/oxc-project-runtime-0.154.0.LICENSE`](licenses/oxc-project-runtime-0.154.0.LICENSE) | 1,119 | `95ced5ecf1133fbf41d409b5555c86c344f83f3b019926057ddbc07cfdcc27b3` | `1d7d74ef…40e0d0a1` |
| `@babel/runtime` helpers beneath them (the same four: see below) | 8.0.7 (licence text; see below) | MIT | `\0@oxc-project+runtime@0.154.0` | `@babel/helpers - typeof` | [`licenses/babel-runtime-8.0.7.LICENSE`](licenses/babel-runtime-8.0.7.LICENSE) | 1,106 | `117da2af0d4ce0fe1c8e19b5cff9dcd806adf973d328d27b11d4448c4ff24f76` | `1ea91c9b…7e439b1` |

### rolldown's runtime helper and its THIRD-PARTY-LICENSE

rolldown's `LICENSE` (VoidZero Inc. & Contributors) ends by pointing to `THIRD-PARTY-LICENSE` for "externally maintained
libraries from which parts of the Software is derived". In the 1.2.14 package that file holds two MIT notices: Rollup's
(Copyright (c) 2017 Rollup's contributors) and esbuild's (Copyright (c) 2020 Evan Wallace). The runtime helper this bundle
inlines is covered by it: rolldown's runtime (`crates/rolldown/src/runtime/runtime-base.js`, shipped in the package as the
first region of `dist/experimental-runtime.mjs`) keeps esbuild's runtime helpers by name and body - `__defProp`,
`__copyProps`, `__toESM`, `__toCommonJS`, `__reExport` as in esbuild's `internal/runtime/runtime.go` - and its
`__exportAll`, the one helper here besides `Object.defineProperty`, is esbuild's `__export` (a getter per export) on a
fresh object with a `Symbol.toStringTag` of `Module`. So rolldown's `THIRD-PARTY-LICENSE` is kept beside its `LICENSE`,
unmodified, from `npm pack rolldown@1.2.14` (checked 2026-11-04 against esbuild's `runtime.go` at v0.25.0).

### The Babel notice beneath the oxc helpers

The `@oxc-project/runtime` helpers are Babel's. That package's README says its code is copied from the published
`@babel/runtime` ("All credits to the Babel team"), and its own LICENSE names only VoidZero Inc. and Boshen, so Babel's
MIT notice (Sebastian McKenzie and other contributors) is kept beside it. Of the four helpers the bundle inlines
(`//#region \0@oxc-project+runtime@0.154.0/helpers/esm/<name>.js`), `typeof` (which keeps Babel's
`"@babel/helpers - typeof"` marker), `toPropertyKey` and `defineProperty` are byte for byte `helpers/esm/<name>.js` of
`@babel/runtime` 8.0.7 and of 7.29.10, and `toPrimitive` is Babel's with the `typeof Symbol` guard dropped (oxc's change).
Oxc 0.154.0 (published 2026-10-13) names no Babel version: `npm/runtime/upstream.json`, which later records one (8.0.8),
is not in its tag `crates_v0.154.0`. 8.0.7 is the last `@babel/runtime` published before it (2026-10-07); its LICENSE is
the same file as 7.29.10's (sha256 `117da2af0d4ce0fe1c8e19b5cff9dcd806adf973d328d27b11d4448c4ff24f76`), taken unmodified
from `npm pack @babel/runtime@8.0.7` (tarball sha256 `1ea91c9b9b8f1f764b6baec278e28ecb5b47a246298fb01a88e0023db3ed673c`).

## Updating

1. `npm pack markdown-it@<new version>`, then overwrite `markdown-it.esm.min.mjs` and `LICENSE`.
2. Read the new tag's `package-lock.json` for the versions of what the bundle inlines, list the bundle's `//#region`
   markers, and replace each licence file under `licenses/` with that release's own (from `npm pack`). A new region or a
   dropped one changes the table above.
3. Update the version, sizes and sha256 values in the tables above, and the rows of `THIRD_PARTY_NOTICES.md`.
4. Change `MARKDOWN_IT_VERSION` in `src/limn/viewer/assemble.py`: it is the `?v=` that busts the browser cache, and the
   regression tests (`VendorMarkdownIt`) check it against the banner of the file.
