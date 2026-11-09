# KaTeX (vendored)

The TeX renderer the viewer draws a Markdown document's math with ([ADR-0036](../../../../docs/adr/0036-markdown-drawn-math.md)
D1). The viewer imports it in the page, not in the parse worker: the worker still only returns tokens, and the drawn math is
built with the DOM calls KaTeX itself makes (`document.createElement`, `createElementNS`, `createTextNode`,
`createDocumentFragment` - the module holds no `innerHTML`, no `eval` and no `new Function`). The import is dynamic and
happens only when a Markdown document whose tokens hold math opens. The server serves the module, the stylesheet and the
fonts at `GET /vendor/katex/<name>`; the licence file and this README are not served. The endpoint contract is in
[docs/handbook/api.md](../../../../docs/handbook/api.md), and what the drawn math looks like is in
[docs/handbook/viewer.md](../../../../docs/handbook/viewer.md) §수식.

| Item | Value |
| --- | --- |
| Package | `katex@0.19.1` (npm, published 2026-10-23, the latest release on 2026-11-09) |
| Obtained by | `npm pack katex@0.19.1` -> `package/dist/katex.mjs`, `package/dist/katex.min.css`, the 20 `package/dist/fonts/*.woff2`, and `package/LICENSE` |
| npm tarball sha256 | `24da5a599eb2fcede2e270b99a6ff48bca816beecc95feeb84e8cccbd1bb34fd` (`katex-0.19.1.tgz`) |
| License | MIT - [`LICENSE`](LICENSE) (unmodified, sha256 `766ccc1f…ce18e3`). KaTeX bundles no third-party code: its only dependency, `commander`, belongs to the command-line tool, which is not here |

## Where the files come from, and how they were checked

The npm package was checked against two independent sources:

- The tarball's SHA-512 equals the registry's `dist.integrity` for `katex@0.19.1`
  (`sha512-jG8uKntjSEcm2EpQOh0XturpPuuC9r3Sq5HLHdsFdWZT27E672SF19QEi+of0/YeOy15lDgRhKvr5614uRrEfA==`).
- Every file taken is byte for byte the one in the GitHub release asset `katex.zip` of tag `v0.19.1`
  (sha256 `53fc803b117c9ccf625e232e5ce2a6571d39ca87d9345917912e0b7d08839f9e`): `katex.mjs`, `katex.min.css` and all 20
  `fonts/*.woff2`.
- `LICENSE` is byte for byte the repository's `LICENSE` at tag `v0.19.1`.

[`SHA256SUMS`](SHA256SUMS) lists every served file with its hash. The regression tests (`KatexFiles` in
[`src/limn/viewer/tests/test_vendor_katex.py`](../../viewer/tests/test_vendor_katex.py)) check the files against it.

## The module

[`katex.mjs`](katex.mjs) is the package's ESM build, unchanged (603,305 bytes). It is not minified: the package publishes
no minified ESM, and `katex.min.js` is a UMD bundle with no `export`, so a browser cannot `import` it. Limn has no build
step ([architecture.md](../../../../docs/handbook/architecture.md) 불변식 2), so the unminified module is the file. The
page imports it as `/vendor/katex/katex.mjs?v=0.19.1`, so a cached copy never needs revalidating.

Only `katex.renderToString` is called, with `throwOnError: true`, `strict: false` and `trust: false`: a macro KaTeX
refuses throws and the viewer falls back to the source characters, no `\href`, `\url` or `\includegraphics` is honoured,
and non-ASCII letters (the lab writes `\text{지중}`) are drawn rather than refused. `contrib/` is not here - no
`auto-render` (the viewer finds math with its own rules, [ADR-0032](../../../../docs/adr/0032-markdown-front-matter.md)
D6), no `mhchem`, no `copy-tex`.

## The stylesheet

[`katex.css`](katex.css) is the upstream `katex.min.css` (sha256 `00e0b094…f4dcf`, 24,793 bytes) with a provenance
comment prepended and one change in each of its 20 `@font-face` rules: the `src` names the `woff2` file beside the
stylesheet and carries the version, `url(KaTeX_Main-Regular.woff2?v=0.19.1) format("woff2")` instead of the upstream
triple `url(fonts/KaTeX_Main-Regular.woff2) …, url(fonts/KaTeX_Main-Regular.woff) …, url(fonts/KaTeX_Main-Regular.ttf) …`.
The route serves files by leaf name only, so the subfolder goes; the versioned URL lets the server answer
`Cache-Control: public, max-age=31536000, immutable`. The test derives the upstream file back from this one and compares
its sha256, so every other byte is upstream's.

**Only `woff2`.** A browser that runs the viewer at all (it needs `<dialog>.showModal()`) reads `woff2`, and the upstream
`src` lists `woff2` first, so a browser never asks for the `woff` or `ttf` the upstream rules name next. Dropping them
saves 844 KB.

The page adds the stylesheet with a `<link rel="stylesheet">` the first time math is drawn, and waits for it to load:
unstyled KaTeX markup is unreadable, so a stylesheet that fails to arrive means the math is left as its source
characters instead. The one rule of the file that is not under `.katex` is `body { counter-reset: katexEqnNo mmlEqnNo }`,
which only numbers `\tag`.

## The fonts

The 20 `KaTeX_*.woff2` files (259,792 bytes in all) are the upstream `dist/fonts/*.woff2`, unchanged. All 20 are here
because the stylesheet declares all 20 `@font-face` rules and any document may use any of them; a page downloads only
the ones its math actually draws with, as Pretendard's 92 slices work
([`../pretendard/README.md`](../pretendard/README.md)). The 189 formulas of the three manuscripts of the 2026-11-09 PoC
draw with five of the 20, 56,472 bytes in all: `KaTeX_Main-Regular`, `KaTeX_Math-Italic` and `KaTeX_Size2-`, `Size3-` and
`Size4-Regular` (the growing delimiters and the sum sign). No bold or italic text face is among them.

`woff` and `ttf` are not here (see above), nor are the `katex-swap` stylesheets (they swap in system fonts, which would
make the drawn math depend on the device).

## Updating

1. `npm pack katex@<new version>`, then replace `katex.mjs` and every `KaTeX_*.woff2` with the package's
   `dist/katex.mjs` and `dist/fonts/*.woff2`, removing any font the new release no longer has.
2. Re-derive `katex.css` from the new `dist/katex.min.css` by the rule above, keeping the provenance comment's version.
3. Replace `LICENSE` from `package/LICENSE`.
4. Rewrite `SHA256SUMS` (`shasum -a 256 katex.mjs katex.css *.woff2 > SHA256SUMS`) and the hashes, sizes and dates in
   this README.
5. Set `KATEX_VERSION` in [`src/limn/viewer/assemble.py`](../../viewer/assemble.py) to the new version - it is the `?v=`
   of every URL - and update the row in [`THIRD_PARTY_NOTICES.md`](../../../../THIRD_PARTY_NOTICES.md).
6. `uv run pytest -q src/limn/viewer/tests/test_vendor_katex.py` and the Markdown browser tests.
