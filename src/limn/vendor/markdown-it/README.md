# markdown-it (vendored, PoC only)

Throwaway PoC for the HTML document surface (docs/superpowers/specs/2026-10-24-html-document-surface.md). Not approved;
the vendoring decision is the open ADR-0025 D5. The viewer loads this file with `import()` only when a Markdown document
opens. Only `.mjs` files are served (`/vendor/markdown-it/<name>.mjs`); the licence files are not.

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
bundle shows them: `//#region node_modules/<package>/…` markers, or for the minified parts without a marker the code itself
(linkify-it's `LinkifyIt`/`schema_names`, punycode's `Overflow: input needs wider integers to process`, uc.micro's
`src_Any`/`src_Cc`/`src_P`/`src_Z` classes).

Every licence file is the package's own, unmodified, taken from `npm pack <package>@<version>`; the BSD-2-Clause notice of
`entities` (copyright notice, conditions and disclaimer) and both notices of `mdurl` (its authors' MIT notice and the Joyent,
Inc. MIT notice for the Node.js `url` code its `parse()` is based on) are kept whole.

| Package | Version | License | Licence file | Licence sha256 | tarball sha256 |
| --- | --- | --- | --- | --- | --- |
| `entities` | 8.1.0 | BSD-2-Clause | [`licenses/entities-8.1.0.LICENSE`](licenses/entities-8.1.0.LICENSE) | `cb992345…f389e164` | `e9a27d66…a37cbe68` |
| `mdurl` | 2.1.0 | MIT (with the Joyent, Inc. notice) | [`licenses/mdurl-2.1.0.LICENSE`](licenses/mdurl-2.1.0.LICENSE) | `6b6a356c…f6aa2644` | `23fc27c3…5aabd11d` |
| `linkify-it` | 6.1.0 | MIT | [`licenses/linkify-it-6.1.0.LICENSE`](licenses/linkify-it-6.1.0.LICENSE) | `95e3f7f0…606f23e3` | `780a9e82…029076b8` |
| `uc.micro` | 3.0.0 | MIT | [`licenses/uc.micro-3.0.0.LICENSE`](licenses/uc.micro-3.0.0.LICENSE) | `483acb26…d5f88c8a` | `23a27049…75552981` |
| `punycode.js` | 2.3.1 | MIT | [`licenses/punycode.js-2.3.1.LICENSE`](licenses/punycode.js-2.3.1.LICENSE) | `483acb26…d5f88c8a` | `8768d89a…1f7324a8` |
| `rolldown` runtime helper (`\0rolldown/runtime.js`, a few lines) | 1.2.14 | MIT | [`licenses/rolldown-1.2.14.LICENSE`](licenses/rolldown-1.2.14.LICENSE) | `23ecfff3…e2f9f734` | `9c142fca…c806e53d` |
| `@oxc-project/runtime` helpers (`typeof`, `toPrimitive`, `toPropertyKey`, `defineProperty`; injected by rolldown) | 0.154.0 (named in the bundle) | MIT | [`licenses/oxc-project-runtime-0.154.0.LICENSE`](licenses/oxc-project-runtime-0.154.0.LICENSE) | `95ced5ec…fdcc27b3` | `1d7d74ef…40e0d0a1` |
| `@babel/runtime` helpers beneath them (the same four: see below) | 8.0.7 (licence text; see below) | MIT | [`licenses/babel-runtime-8.0.7.LICENSE`](licenses/babel-runtime-8.0.7.LICENSE) | `117da2af…4ff24f76` | `1ea91c9b…7e439b1` |

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

Open before approval (plan Task 5 Step 1): rolldown's licence points to a THIRD-PARTY-LICENSE file for code it derives from
other projects; whether any of that covers the runtime helper lines in this bundle is not checked yet.
