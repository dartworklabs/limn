# Pretendard (vendored)

The Pretendard Variable font the viewer's interface text is set in. The viewer runs inside a private network, so it does not use an external CDN; the server serves these files itself at `GET /vendor/pretendard/<file>`. The endpoint contract is in [docs/handbook/api.md](../../../../docs/handbook/api.md), and why the viewer bundles a font and how the page loads it is in [docs/handbook/viewer.md](../../../../docs/handbook/viewer.md) §글꼴.

| Item | Value |
| --- | --- |
| Release | Pretendard 1.3.9 (GitHub release `v1.3.9`, published 2023-11-05, the latest release on 2026-10-05). Font version string `Version 1.309` in every file |
| Obtained by | `npm pack pretendard@1.3.9` → the 92 files of `package/dist/web/variable/woff2-dynamic-subset/` and `package/dist/web/variable/pretendardvariable-dynamic-subset.css`. `LICENSE` is `LICENSE.txt` of the release zip `Pretendard-1.3.9.zip` |
| Release zip sha256 | `04be351a74d6bf7d60c480a3087e51d185485d35a52023142af1df19eb8c428a` (`Pretendard-1.3.9.zip`, 47,304,526 bytes) |
| npm tarball sha256 | `0ffc240cee83be02520fb4ac1b2a0a51052b9d13506ade0ba90c591dbbb3bd53` (`pretendard-1.3.9.tgz`) |
| License | SIL Open Font License 1.1, Reserved Font Name "Pretendard" — [`LICENSE`](LICENSE) (unmodified, sha256 `b04538c9…98e38e`) |

## Where the files come from, and how they were checked

The release zip has no `web/variable/woff2-dynamic-subset/` folder: the dynamic subset is published only in the npm package of the same release (and the git tag). The release publishes no checksums (its assets carry no digest). So the files were taken from the npm package and checked against two independent sources:

- The npm tarball's SHA-512 equals the registry's `dist.integrity` for `pretendard@1.3.9` (`sha512-PaQAADyLY5v4…IaywSw==`).
- The git blob hash of each of the 92 `.woff2` files and of the upstream CSS equals the one in the release tag's tree (`packages/pretendard/dist/web/variable/` at `v1.3.9`).
- The npm package's whole variable font (`web/variable/woff2/PretendardVariable.woff2`) is byte for byte the release zip's.
- Every subset's name table says family `Pretendard Variable`, `Version 1.309`, as the release's whole font does.

[`SHA256SUMS`](SHA256SUMS) lists every `.woff2` file with its hash. The regression tests (`PretendardFiles`) check the files against it.

## The stylesheet

[`pretendard.css`](pretendard.css) is the upstream `pretendardvariable-dynamic-subset.css` (sha256 `2973bcae80262dcb630cfb793fbf6af29bd986c769ee54953fb3e5b3e32323ca`) with one change in each of its 92 `@font-face` rules: the `src` URL names the file beside the stylesheet and carries the version, `url(PretendardVariable.subset.<n>.woff2?v=1.3.9)` instead of `url(./woff2-dynamic-subset/PretendardVariable.subset.<n>.woff2)`. The route serves files by leaf name only, so the subfolder goes; the versioned URL lets the server answer `Cache-Control: public, max-age=31536000, immutable`. The family (`Pretendard Variable`), `font-display: swap`, the weight range and every `unicode-range` are upstream's as they are.

**No `local()`.** Upstream's rules load only `url()`, and they stay so: every device draws the interface in this very build. A Pretendard installed on the device can be another version or a static build with other metrics and hinting, and a phone without it fell back to a wider system Korean font. The viewer's spacing and ink alignment are measured against this font, so the device must not choose.

## Why only these files

- **The dynamic subset.** The font is cut into 92 slices by `unicode-range`; a page loads only the slices its text uses. A phone page loads a fraction of the 2.96 MB in total, where the single variable file (`PretendardVariable.woff2`) is 2.06 MB for any page.
- **The variable font.** One slice covers every weight the interface uses (400 to 700), so a bold label costs no second file.
- **Not the static weights, `woff`, `ttf` or `otf`.** A browser that runs the viewer at all (it needs `<dialog>.showModal()`) reads `woff2` variable fonts.
- **Not the GOV, JP and Std families.** They are variants for other uses; the interface needs the standard Korean and Latin set.
- **The author's own subsets, not ours.** Cutting or converting the font here would make a Modified Version under OFL §3, which may not carry the Reserved Font Name; taking the official slices unchanged keeps the name `Pretendard Variable`.

## Updating

1. `npm pack pretendard@<new version>`, then replace every `.woff2` in this folder with `package/dist/web/variable/woff2-dynamic-subset/*` and remove any slice the new release no longer has.
2. Rewrite `pretendardvariable-dynamic-subset.css` into `pretendard.css` the same way (each `src` URL → `<file>?v=<new version>`, nothing else), and replace `LICENSE` from the release zip.
3. Regenerate `SHA256SUMS` (`sha256sum *.woff2 | sort -k2 -V > SHA256SUMS`) and update the version and hashes above, after checking the downloads against the git tag as described.
4. Change `PRETENDARD_VERSION` in `src/limn/viewer/assemble.py`. It is the `?v=` of the stylesheet link; the regression tests check that every URL in the stylesheet carries it and names a file here.
