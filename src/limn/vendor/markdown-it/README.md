# markdown-it (vendored, PoC only)

Throwaway PoC for the HTML document surface (docs/superpowers/specs/2026-10-24-html-document-surface.md). Not approved;
the vendoring decision is the open ADR. The viewer loads this file with `import()` only when a Markdown document opens.

| Item | Value |
| --- | --- |
| Package | `markdown-it@15.0.3` (npm, published 2026-10-16 by the maintainer) |
| Obtained by | `npm pack markdown-it@15.0.3` -> `package/dist/browser/markdown-it.esm.min.mjs`, plus `package/LICENSE` |
| tarball sha256 | `98a7453983ab0e268c17dbd5260bf7190ba46b4cca912327fc1c1a2578e4b56d` |
| License | MIT - [`LICENSE`](LICENSE) (unmodified); the bundle includes its MIT/BSD dependencies (entities, linkify-it, mdurl, uc.micro, punycode.js) |

| File | Bytes | sha256 |
| --- | ---: | --- |
| `markdown-it.esm.min.mjs` | 124,681 | `d5432491790141da046b1197353705db03264f40b5727f3b4b591f5aba193e30` |
| `LICENSE` | 1,073 | `792c48c5a849a15fdf9e37e8bcf9e6d1dd13b32b46c642a748a0a46a9919d473` |
